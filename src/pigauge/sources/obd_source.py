"""Threaded OBD2 source: schedule, request, decode, publish, reconnect.

One implementation serves both vehicle links; the difference between CAN
and ELM327 is entirely inside the injected
:class:`~pigauge.sources.obd_transport.ObdTransport`. The loop honours the
source contract from docs/ARCHITECTURE.md: own thread, own poll schedule,
reconnect with backoff, never raise into the main thread, stop within 2 s.

Unanswered PIDs are not errors — the channel simply stops refreshing and
the DataBus marks it STALE, which is exactly what the gauges should show.
"""

import logging
import threading
import time
from collections.abc import Callable, Sequence

from pigauge.core.databus import DataBus
from pigauge.sources.base import Source, SourceStatus
from pigauge.sources.obd_profile import PollEntry
from pigauge.sources.obd_scheduler import PollScheduler
from pigauge.sources.obd_transport import BackoffPolicy, ObdTransport, ObdTransportError

logger = logging.getLogger(__name__)

STOP_JOIN_TIMEOUT_S = 2.0
"""Source contract: stop() must return within 2 s."""


class ObdSource(Source):
    """Publishes a vehicle poll plan to the DataBus from its own thread."""

    def __init__(
        self,
        bus: DataBus,
        transport: ObdTransport,
        plan: Sequence[PollEntry],
        *,
        backoff: BackoffPolicy | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Poll ``plan`` over ``transport``, publishing base units to ``bus``."""
        self._bus = bus
        self._transport = transport
        self._scheduler = PollScheduler(plan)
        self._backoff = backoff or BackoffPolicy()
        self._clock = clock
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._status = SourceStatus.STOPPED
        self._connected = False

    def start(self) -> None:
        """Spawn the acquisition thread and begin publishing."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"ObdSource-{self._transport.name}", daemon=True
        )
        self._status = SourceStatus.RECONNECTING  # until the first connect succeeds
        self._thread.start()

    def stop(self) -> None:
        """Stop cleanly; returns within 2 s (golden rule: sources never hang)."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=STOP_JOIN_TIMEOUT_S)
            self._thread = None
        self._disconnect()
        self._status = SourceStatus.STOPPED

    @property
    def provided_channels(self) -> list[str]:
        """Channels this vehicle profile polls, in priority order."""
        return [entry.channel_id for entry in self._scheduler.entries]

    @property
    def status(self) -> SourceStatus:
        """Current connection status."""
        return self._status

    def poll_once(self) -> bool:
        """Run one connect/poll iteration; returns False if the link faulted.

        Exposed for tests and tools (scan_vehicle) that drive the source
        without a thread; :meth:`start` calls it in a loop.
        """
        if not self._connected and not self._connect():
            return False
        now = self._clock()
        due = self._scheduler.due(now)
        if not due:
            return True
        return self._poll_due(due, now)

    def _run(self) -> None:
        """Thread body: connect with backoff, then poll on schedule."""
        failures = 0
        try:
            while not self._stop_event.is_set():
                if not self._connected:
                    if self._connect():
                        failures = 0
                    else:
                        failures += 1
                        self._stop_event.wait(self._backoff.delay_for(failures))
                        continue
                now = self._clock()
                due = self._scheduler.due(now)
                if not due:
                    self._stop_event.wait(self._scheduler.seconds_until_next(now))
                    continue
                if not self._poll_due(due, now):
                    failures += 1
                    self._stop_event.wait(self._backoff.delay_for(failures))
        except Exception:  # never raise into the main thread
            logger.exception("%s source thread failed", self._transport.name)
            self._status = SourceStatus.ERROR
        else:
            self._status = SourceStatus.STOPPED

    def _connect(self) -> bool:
        """Try to open the link; returns success, never raises."""
        try:
            self._transport.connect()
        except ObdTransportError as error:
            logger.warning("%s connect failed: %s", self._transport.name, error)
            self._status = SourceStatus.RECONNECTING
            return False
        self._connected = True
        self._scheduler.reset()
        self._status = SourceStatus.CONNECTED
        logger.info("%s connected", self._transport.name)
        return True

    def _disconnect(self) -> None:
        """Drop the link, tolerating a transport that is already broken."""
        if not self._connected:
            return
        self._connected = False
        try:
            self._transport.close()
        except Exception:
            logger.debug("%s close failed while disconnecting", self._transport.name)

    def _poll_due(self, due: Sequence[PollEntry], now: float) -> bool:
        """Request every due entry in transport-sized batches."""
        batch_size = max(1, self._transport.max_pids_per_request)
        for start in range(0, len(due), batch_size):
            batch = due[start : start + batch_size]
            try:
                answers = self._transport.request([entry.pid for entry in batch])
            except ObdTransportError as error:
                logger.warning("%s request failed: %s", self._transport.name, error)
                self._disconnect()
                self._status = SourceStatus.RECONNECTING
                return False
            self._scheduler.mark_polled(batch, now)
            self._publish(batch, answers)
            if self._stop_event.is_set():
                break
        return True

    def _publish(self, batch: Sequence[PollEntry], answers: dict[int, bytes]) -> None:
        """Decode answered PIDs onto the bus; skip the rest (they go STALE)."""
        for entry in batch:
            data = answers.get(entry.pid)
            if data is None:
                continue
            try:
                value = entry.decoder.decode(data)
            except ValueError as error:
                logger.warning("%s: bad data for %s: %s", self._transport.name,
                               entry.channel_id, error)
                continue
            self._bus.publish(entry.channel_id, value)
