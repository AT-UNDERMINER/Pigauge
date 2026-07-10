"""Widget interface: a drawable gauge element bound to a channel.

Concrete widgets (Phase 2): NumericReadout, ArcGauge, NeedleGauge, BarGauge,
Sparkline, StatusIcon, WarningTakeover (Phase 6). Widgets draw via the Canvas
abstraction so they work on both Pillow and pygame backends.
"""

from abc import ABC, abstractmethod
from typing import Any


class Widget(ABC):
    """One visual element in a GaugeScene, built from a layout YAML entry."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.channel: str | None = config.get("channel")

    @abstractmethod
    def draw(self, canvas: "Canvas", reading: "Reading | None") -> None:  # noqa: F821
        """Draw current state. A None or STALE reading renders greyed out."""
