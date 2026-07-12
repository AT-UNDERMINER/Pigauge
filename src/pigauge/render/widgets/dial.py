"""Shared geometry for round dials (ArcGauge and NeedleGauge).

Both gauges share the same scale model: a sweep of degrees mapped over a
value range, tick marks with labels at major steps, and a redline zone
band at the rim. DialBase parses that config once; subclasses draw the
value indicator (arc sweep or needle).
"""

from typing import Any

from pigauge.render.canvas import Canvas
from pigauge.render.widgets import common
from pigauge.render.widgets.base import Widget

DEFAULT_RADIUS = 100.0
DEFAULT_SWEEP = (135.0, 405.0)
DEFAULT_RANGE = (0.0, 100.0)
BAND_WIDTH_FRACTION = 0.14
REDLINE_BAND_FRACTION = 0.05
MAJOR_TICK_INNER = 0.84
MINOR_TICK_INNER = 0.91
TICK_OUTER = 0.98
TICK_LABEL_RADIUS = 0.68
TICK_LABEL_SIZE_FRACTION = 0.11
MIN_TICK_LABEL_SIZE = 9


class DialBase(Widget):
    """Round gauge scaffolding: scale band, ticks, labels, redline zone."""

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._center = common.position_of(config)
        self._radius = float(config.get("radius", DEFAULT_RADIUS))
        self._sweep = common.sweep_of(config, DEFAULT_SWEEP)
        self._range = common.range_of(config, DEFAULT_RANGE)
        self._redline = common.redline_from(config)
        ticks = config.get("ticks") or {}
        self._major_step = float(ticks.get("major", 0) or 0)
        self._minor_step = float(ticks.get("minor", 0) or 0)
        colors = config.get("colors") or {}
        self._color = colors.get("arc", common.ACCENT_COLOR)
        self._redline_color = colors.get("redline", common.REDLINE_COLOR)
        self._text_color = colors.get("text", common.TEXT_COLOR)
        self._display_unit = config.get("display_unit")

    def angle_of(self, value: float) -> float:
        """Dial angle for a display-unit value, clamped to the sweep."""
        start_deg, end_deg = self._sweep
        return common.angle_for(value, *self._range, start_deg, end_deg)

    def draw_scale(self, canvas: Canvas, reading: object) -> None:
        """Redline zone band, then tick marks and labels."""
        if self._redline is not None:
            band = max(2, round(self._radius * REDLINE_BAND_FRACTION))
            canvas.arc(
                self._center,
                self._radius,
                self.angle_of(self._redline),
                self._sweep[1],
                common.paint(self._redline_color, reading),
                band,
            )
        self._draw_ticks(canvas)

    def _draw_ticks(self, canvas: Canvas) -> None:
        minimum, maximum = self._range
        for value in common.tick_values(minimum, maximum, self._minor_step):
            self._tick_line(canvas, value, MINOR_TICK_INNER, common.TRACK_COLOR, 1)
        label_size = max(MIN_TICK_LABEL_SIZE, round(self._radius * TICK_LABEL_SIZE_FRACTION))
        for value in common.tick_values(minimum, maximum, self._major_step):
            color = (
                self._redline_color
                if self._redline is not None and value >= self._redline
                else common.LABEL_COLOR
            )
            self._tick_line(canvas, value, MAJOR_TICK_INNER, color, 2)
            label_at = common.polar(
                self._center, self._radius * TICK_LABEL_RADIUS, self.angle_of(value)
            )
            canvas.text(label_at, common.format_tick(value), color, label_size)

    def _tick_line(
        self, canvas: Canvas, value: float, inner_fraction: float, color: str, width: int
    ) -> None:
        angle = self.angle_of(value)
        start = common.polar(self._center, self._radius * inner_fraction, angle)
        end = common.polar(self._center, self._radius * TICK_OUTER, angle)
        canvas.line(start, end, color, width)
