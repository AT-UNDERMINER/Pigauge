"""Transport contract shared by the CAN and ELM327 vehicle sources.

A transport is a thin adapter over one physical link: connect, ask for a
few PIDs, hand back their raw data bytes, close. It holds no scheduling,
no decoding, and no reconnect policy — those live in
:mod:`pigauge.sources.obd_source` so both links share one tested
implementation (CLAUDE.md golden rule 2).

Failure convention: a PID the ECU simply did not answer is *omitted* from
the result (the channel then goes STALE on its own), while a link-level
fault — bus down, serial unplugged, adapter wedged — raises
:class:`ObdTransportError` and triggers reconnection with backoff.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

DEFAULT_INITIAL_BACKOFF_S = 0.5
DEFAULT_BACKOFF_FACTOR = 2.0
DEFAULT_MAX_BACKOFF_S = 30.0


class ObdTransportError(Exception):
    """A link-level fault; the source reconnects with backoff."""


@runtime_checkable
class ObdTransport(Protocol):
    """One vehicle link, driven by :class:`~pigauge.sources.obd_source.ObdSource`."""

    name: str
    max_pids_per_request: int
    """1 for CAN (one PID per ISO-TP request), more for ELM327 batching."""

    def connect(self) -> None:
        """Open the link, raising :class:`ObdTransportError` on failure."""
        ...

    def request(self, pids: Sequence[int]) -> dict[int, bytes]:
        """Query mode 01 PIDs, returning ``{pid: data bytes}`` for answers."""
        ...

    def close(self) -> None:
        """Release the link; must not raise."""
        ...


@dataclass(frozen=True)
class BackoffPolicy:
    """Exponential retry delays, capped so a dead link retries forever.

    A vehicle link drops for ordinary reasons — ignition off, adapter
    knocked loose — so reconnection never gives up; it just stops trying
    hard once ``max_s`` is reached.
    """

    initial_s: float = DEFAULT_INITIAL_BACKOFF_S
    factor: float = DEFAULT_BACKOFF_FACTOR
    max_s: float = DEFAULT_MAX_BACKOFF_S

    def delay_for(self, attempt: int) -> float:
        """Seconds to wait after ``attempt`` consecutive failures (1-based)."""
        if attempt < 1:
            raise ValueError("attempt is 1-based")
        return min(self.max_s, self.initial_s * self.factor ** (attempt - 1))
