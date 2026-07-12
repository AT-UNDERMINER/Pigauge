"""Needle gauge: classic round dial with a pivoting needle."""

from pigauge.core.databus import Reading
from pigauge.render.canvas import Canvas
from pigauge.render.widgets import common
from pigauge.render.widgets.dial import DialBase

FACE_OUTLINE_WIDTH = 2
NEEDLE_TIP_FRACTION = 0.80
NEEDLE_TAIL_FRACTION = 0.16
NEEDLE_HALF_WIDTH_FRACTION = 0.035
HUB_RADIUS_FRACTION = 0.08


class NeedleGauge(DialBase):
    """Classic dial: face outline, scale, and a needle from the hub."""

    def draw(self, canvas: Canvas, reading: Reading | None) -> None:
        """Face and scale always draw; the needle needs a reading."""
        canvas.circle(
            self._center,
            self._radius,
            outline=common.TRACK_COLOR,
            width=FACE_OUTLINE_WIDTH,
        )
        self.draw_scale(canvas, reading)

        value = common.display_value(reading, self._display_unit)
        if value is not None:
            self._draw_needle(canvas, self.angle_of(value), common.paint(self._color, reading))
        hub_radius = max(3, round(self._radius * HUB_RADIUS_FRACTION))
        canvas.circle(self._center, hub_radius, fill=common.paint(self._text_color, reading))

    def _draw_needle(self, canvas: Canvas, angle_deg: float, color: str) -> None:
        tip = common.polar(self._center, self._radius * NEEDLE_TIP_FRACTION, angle_deg)
        tail = common.polar(self._center, self._radius * NEEDLE_TAIL_FRACTION, angle_deg + 180)
        half_width = max(2.0, self._radius * NEEDLE_HALF_WIDTH_FRACTION)
        left = common.polar(self._center, half_width, angle_deg + 90)
        right = common.polar(self._center, half_width, angle_deg - 90)
        canvas.polygon([tip, left, tail, right], fill=color)
