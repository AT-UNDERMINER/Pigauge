"""Sparkline: recent value history as a small polyline."""

from collections import deque
from typing import Any

from pigauge.core.databus import Reading
from pigauge.render.canvas import Canvas
from pigauge.render.widgets import common
from pigauge.render.widgets.base import Widget

DEFAULT_WIDTH = 80.0
DEFAULT_HEIGHT = 24.0
DEFAULT_SAMPLES = 60
LINE_WIDTH = 1
FLATLINE_PAD = 1.0


class Sparkline(Widget):
    """Rolling history plot; only fresh (OK) readings are recorded."""

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        center = common.position_of(config)
        self._width = float(config.get("width", DEFAULT_WIDTH))
        self._height = float(config.get("height", DEFAULT_HEIGHT))
        self._top_left = (center[0] - self._width / 2, center[1] - self._height / 2)
        self._samples = int(config.get("samples", DEFAULT_SAMPLES))
        self._fixed_range = (
            common.range_of(config, (0.0, 0.0)) if config.get("range") else None
        )
        self._color = config.get("color", common.ACCENT_COLOR)
        self._display_unit = config.get("display_unit")
        self._history: deque[float] = deque(maxlen=self._samples)

    def draw(self, canvas: Canvas, reading: Reading | None) -> None:
        """Append fresh values, then plot the history (greyed when stale)."""
        if common.is_live(reading):
            value = common.display_value(reading, self._display_unit)
            if value is not None:
                self._history.append(value)
        if len(self._history) < 2:
            return
        minimum, maximum = self._plot_range()
        x0, y0 = self._top_left
        pitch = self._width / (self._samples - 1) if self._samples > 1 else self._width
        newest_x = x0 + self._width
        points = []
        for index, value in enumerate(self._history):
            x = newest_x - (len(self._history) - 1 - index) * pitch
            fraction = common.fraction_for(value, minimum, maximum)
            points.append((x, y0 + self._height * (1 - fraction)))
        canvas.polyline(points, common.paint(self._color, reading), LINE_WIDTH)

    def _plot_range(self) -> tuple[float, float]:
        """Configured range, or autoscale to history (padded when flat)."""
        if self._fixed_range is not None:
            return self._fixed_range
        low, high = min(self._history), max(self._history)
        if low == high:
            return (low - FLATLINE_PAD, high + FLATLINE_PAD)
        return (low, high)
