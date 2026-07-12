"""Arc gauge: a value sweep along the rim with ticks and a redline zone."""

from pigauge.core.databus import Reading
from pigauge.render.canvas import Canvas
from pigauge.render.widgets import common
from pigauge.render.widgets.dial import BAND_WIDTH_FRACTION, DialBase

ARC_INSET_FRACTION = 0.06  # value band sits just inside the tick rim


class ArcGauge(DialBase):
    """Modern gauge: thick coloured arc that grows with the value."""

    def draw(self, canvas: Canvas, reading: Reading | None) -> None:
        """Track and scale always draw; the value arc needs a reading."""
        band_radius = self._radius * (1 - ARC_INSET_FRACTION)
        band_width = max(4, round(self._radius * BAND_WIDTH_FRACTION))
        start_deg, end_deg = self._sweep
        canvas.arc(self._center, band_radius, start_deg, end_deg, common.TRACK_COLOR, band_width)

        value = common.display_value(reading, self._display_unit)
        if value is not None:
            in_redline = self._redline is not None and value >= self._redline
            arc_color = self._redline_color if in_redline else self._color
            canvas.arc(
                self._center,
                band_radius,
                start_deg,
                self.angle_of(value),
                common.paint(arc_color, reading),
                band_width,
            )
        self.draw_scale(canvas, reading)
