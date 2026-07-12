"""Bar gauge: horizontal or vertical fill with a redline zone."""

from typing import Any

from pigauge.core.databus import Reading
from pigauge.render.canvas import Canvas
from pigauge.render.widgets import common
from pigauge.render.widgets.base import Widget

DEFAULT_WIDTH = 200.0
DEFAULT_HEIGHT = 30.0
DEFAULT_RANGE = (0.0, 100.0)
BORDER_WIDTH = 2
FILL_INSET = 3


class BarGauge(Widget):
    """Linear gauge: border, redline zone, and a proportional fill."""

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        center = common.position_of(config)
        self._width = float(config.get("width", DEFAULT_WIDTH))
        self._height = float(config.get("height", DEFAULT_HEIGHT))
        self._top_left = (center[0] - self._width / 2, center[1] - self._height / 2)
        self._range = common.range_of(config, DEFAULT_RANGE)
        self._redline = common.redline_from(config)
        self._vertical = config.get("orientation", "horizontal") == "vertical"
        colors = config.get("colors") or {}
        self._color = colors.get("bar", common.ACCENT_COLOR)
        self._redline_color = colors.get("redline", common.REDLINE_COLOR)
        self._display_unit = config.get("display_unit")

    def draw(self, canvas: Canvas, reading: Reading | None) -> None:
        """Border and zone always draw; the fill needs a reading."""
        x0, y0 = self._top_left
        x1, y1 = x0 + self._width, y0 + self._height
        canvas.rect((x0, y0), (x1, y1), outline=common.TRACK_COLOR, width=BORDER_WIDTH)
        if self._redline is not None:
            zone_start = common.fraction_for(self._redline, *self._range)
            self._fill(canvas, zone_start, 1.0, common.REDLINE_ZONE_COLOR)

        value = common.display_value(reading, self._display_unit)
        if value is not None:
            in_redline = self._redline is not None and value >= self._redline
            fill_color = self._redline_color if in_redline else self._color
            fraction = common.fraction_for(value, *self._range)
            self._fill(canvas, 0.0, fraction, common.paint(fill_color, reading))

    def _fill(self, canvas: Canvas, from_fraction: float, to_fraction: float, color: str) -> None:
        """Paint the inner region between two fractions of the range."""
        if to_fraction <= from_fraction:
            return
        x0, y0 = self._top_left
        inner_x0, inner_y0 = x0 + FILL_INSET, y0 + FILL_INSET
        inner_x1 = x0 + self._width - FILL_INSET
        inner_y1 = y0 + self._height - FILL_INSET
        if self._vertical:  # fills upward from the bottom
            span = inner_y1 - inner_y0
            top = inner_y1 - span * to_fraction
            bottom = inner_y1 - span * from_fraction
            canvas.rect((inner_x0, top), (inner_x1, bottom), fill=color)
        else:
            span = inner_x1 - inner_x0
            left = inner_x0 + span * from_fraction
            right = inner_x0 + span * to_fraction
            canvas.rect((left, inner_y0), (right, inner_y1), fill=color)
