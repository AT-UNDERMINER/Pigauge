"""Thread-safe latest-value cache connecting sources to consumers.

Sources publish from their own threads; the render loop calls :meth:`get`
which never blocks (golden rule 5). Subscriber callbacks run on the
publishing thread and must be fast; exceptions they raise are logged and
swallowed so they can never propagate into a source thread.

Staleness: a reading older than its channel's ``stale_after`` is returned
with quality ``STALE`` (gauges render it greyed out). The clock is
injectable for deterministic tests; it defaults to ``time.monotonic``.
"""

import logging
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum, auto

from pigauge.core.channels import CHANNELS, Channel, UnknownChannelError

logger = logging.getLogger(__name__)

Subscriber = Callable[["Reading"], None]


class Quality(Enum):
    """Trustworthiness of a reading, as defined in docs/ARCHITECTURE.md."""

    OK = auto()
    STALE = auto()
    NO_DATA = auto()


@dataclass(frozen=True)
class Reading:
    """One value on the bus: base units, source timestamp, and quality."""

    channel_id: str
    value: float
    timestamp: float
    quality: Quality

    @classmethod
    def no_data(cls, channel_id: str, timestamp: float = 0.0) -> "Reading":
        """Placeholder for a channel nothing has published yet."""
        return cls(channel_id, float("nan"), timestamp, Quality.NO_DATA)


class DataBus:
    """Thread-safe publish/get/subscribe with per-channel staleness."""

    def __init__(
        self,
        channels: Mapping[str, Channel] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create a bus over ``channels`` (default: the canonical registry)."""
        self._channels = dict(CHANNELS if channels is None else channels)
        self._clock = clock
        self._lock = threading.RLock()
        self._latest: dict[str, tuple[float, float]] = {}
        self._subscribers: dict[str, list[Subscriber]] = {}

    @property
    def channels(self) -> dict[str, Channel]:
        """The channels this bus accepts (a copy; registry is immutable)."""
        return dict(self._channels)

    def publish(self, channel_id: str, value: float, timestamp: float | None = None) -> None:
        """Store the latest value for a channel and notify its subscribers.

        Called from source threads. ``timestamp`` defaults to the bus clock.
        """
        self._require_channel(channel_id)
        stamped = self._clock() if timestamp is None else timestamp
        with self._lock:
            self._latest[channel_id] = (value, stamped)
            subscribers = list(self._subscribers.get(channel_id, ()))
        if not subscribers:
            return
        reading = Reading(channel_id, value, stamped, Quality.OK)
        for callback in subscribers:
            try:
                callback(reading)
            except Exception:
                logger.exception("subscriber for %s raised; continuing", channel_id)

    def get(self, channel_id: str) -> Reading | None:
        """Return the latest reading, or None if nothing was ever published.

        Non-blocking; safe to call from the render loop every frame. The
        quality is OK while the reading's age is within the channel's
        ``stale_after``, STALE afterwards.
        """
        channel = self._require_channel(channel_id)
        with self._lock:
            entry = self._latest.get(channel_id)
        if entry is None:
            return None
        value, stamped = entry
        age = self._clock() - stamped
        quality = Quality.OK if age <= channel.stale_after else Quality.STALE
        return Reading(channel_id, value, stamped, quality)

    def subscribe(self, channel_id: str, callback: Subscriber) -> Callable[[], None]:
        """Register a callback for every publish on a channel.

        Returns an unsubscribe function. Used by the alerts engine and
        logger (Phase 6); callbacks run on the publishing thread.
        """
        self._require_channel(channel_id)
        with self._lock:
            self._subscribers.setdefault(channel_id, []).append(callback)

        def unsubscribe() -> None:
            with self._lock:
                callbacks = self._subscribers.get(channel_id, [])
                if callback in callbacks:
                    callbacks.remove(callback)

        return unsubscribe

    def snapshot(self) -> dict[str, Reading | None]:
        """Latest reading (or None) for every registered channel."""
        return {channel_id: self.get(channel_id) for channel_id in self._channels}

    def _require_channel(self, channel_id: str) -> Channel:
        try:
            return self._channels[channel_id]
        except KeyError:
            raise UnknownChannelError(channel_id) from None
