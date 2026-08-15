"""Per-channel poll scheduling for OBD2 sources.

The scheduler decides *when* each channel in the poll plan is next due and
hands the source the due entries fastest-channel-first, so a slow link
starves the 1 Hz channels rather than the 10 Hz ones (docs/PROTOCOLS.md
§ELM327: "the scheduler must prioritise fast channels").

It is pure state plus arithmetic — the caller supplies the current time —
which keeps it fully testable without threads or clocks.
"""

from collections.abc import Iterable, Sequence

from pigauge.sources.obd_profile import PollEntry

IDLE_WAIT_CAP_S = 1.0
"""Longest sleep suggested when nothing is due, so stop() stays responsive."""


class PollScheduler:
    """Tracks when each poll entry is next due; every entry starts due now."""

    def __init__(self, entries: Iterable[PollEntry]) -> None:
        """Schedule ``entries``, fastest first, all due immediately."""
        self._entries = sorted(entries, key=lambda entry: (-entry.rate_hz, entry.channel_id))
        self._next_due: dict[str, float] = {entry.channel_id: 0.0 for entry in self._entries}

    @property
    def entries(self) -> list[PollEntry]:
        """The poll plan in priority order (fastest channels first)."""
        return list(self._entries)

    def due(self, now: float) -> list[PollEntry]:
        """Entries whose next poll is due at ``now``, in priority order."""
        return [entry for entry in self._entries if self._next_due[entry.channel_id] <= now]

    def mark_polled(self, entries: Sequence[PollEntry], now: float) -> None:
        """Record that ``entries`` were just requested.

        The next due time is measured from ``now`` rather than from the
        previous due time: a link that falls behind must not build up a
        backlog it then tries to burst through.
        """
        for entry in entries:
            self._next_due[entry.channel_id] = now + entry.period_s

    def seconds_until_next(self, now: float) -> float:
        """How long until something is due, capped for shutdown latency."""
        if not self._entries:
            return IDLE_WAIT_CAP_S
        soonest = min(self._next_due.values())
        return max(0.0, min(soonest - now, IDLE_WAIT_CAP_S))

    def reset(self) -> None:
        """Make every entry due again (called after a reconnect)."""
        self._next_due = {entry.channel_id: 0.0 for entry in self._entries}
