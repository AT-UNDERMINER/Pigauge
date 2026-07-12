"""Status icon: on/off indicator for boolean-ish channels."""

from typing import Any

from pigauge.core.databus import Reading
from pigauge.render.canvas import Canvas
from pigauge.render.widgets import common
from pigauge.render.widgets.base import Widget

DEFAULT_RADIUS = 10.0
DEFAULT_ON_COLOR = "#22c55e"
DEFAULT_OFF_COLOR = "#374151"
ON_THRESHOLD = 0.5
OUTLINE_WIDTH = 2


class StatusIcon(Widget):
    """Filled dot when the channel is on, outline when off, grey when stale."""

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._center = common.position_of(config)
        self._radius = float(config.get("radius", DEFAULT_RADIUS))
        self._on_color = config.get("on_color", DEFAULT_ON_COLOR)
        self._off_color = config.get("off_color", DEFAULT_OFF_COLOR)

    def draw(self, canvas: Canvas, reading: Reading | None) -> None:
        """One circle: fill for on, outline for off; stale renders grey."""
        value = common.display_value(reading, None)
        if value is None:
            canvas.circle(
                self._center, self._radius, outline=common.STALE_COLOR, width=OUTLINE_WIDTH
            )
        elif value >= ON_THRESHOLD:
            canvas.circle(self._center, self._radius, fill=common.paint(self._on_color, reading))
        else:
            canvas.circle(
                self._center,
                self._radius,
                outline=common.paint(self._off_color, reading),
                width=OUTLINE_WIDTH,
            )
