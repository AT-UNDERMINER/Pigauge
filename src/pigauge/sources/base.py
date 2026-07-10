"""Source interface: anything that publishes channel readings to the DataBus.

Concrete implementations (Phases 1, 4, 5): SimSource, CanSource, Elm327Source,
Ads1115Source, Max31856Source. See docs/ARCHITECTURE.md for the contract.
"""

from abc import ABC, abstractmethod
from enum import Enum, auto


class SourceStatus(Enum):
    """Connection state exposed to the web UI status page."""

    STOPPED = auto()
    CONNECTED = auto()
    RECONNECTING = auto()
    ERROR = auto()


class Source(ABC):
    """A data producer running in its own thread.

    Rules (CLAUDE.md): never raise into the main thread; own your polling
    schedule; publish base-unit values only; reconnect with backoff.
    """

    @abstractmethod
    def start(self) -> None:
        """Spawn the acquisition thread and begin publishing."""

    @abstractmethod
    def stop(self) -> None:
        """Stop cleanly; must return within 2 s."""

    @property
    @abstractmethod
    def provided_channels(self) -> list[str]:
        """Channel IDs this source publishes (from config/profile)."""

    @property
    @abstractmethod
    def status(self) -> SourceStatus:
        """Current connection status."""
