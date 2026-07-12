"""Numeric readout: a value in display units with an optional small label."""

from typing import Any

from pigauge.core.databus import Reading
from pigauge.render.canvas import Canvas
from pigauge.render.widgets import common
from pigauge.render.widgets.base import Widget

DEFAULT_FONT_SIZE = 24
LABEL_SIZE_SCALE = 0.45
LABEL_OFFSET_SCALE = 0.9


class NumericReadout(Widget):
    """Big number bound to a channel, e.g. boost psi in the pod centre."""

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._position = common.position_of(config)
        self._font_size = int(config.get("font_size", DEFAULT_FONT_SIZE))
        self._decimals = int(config.get("decimals", 0))
        self._label = config.get("label")
        self._color = config.get("color", common.TEXT_COLOR)
        self._display_unit = config.get("display_unit")

    def draw(self, canvas: Canvas, reading: Reading | None) -> None:
        """Value text (greyed when stale), label above in a smaller font."""
        value = common.display_value(reading, self._display_unit)
        text = common.format_value(value, self._decimals)
        canvas.text(self._position, text, common.paint(self._color, reading), self._font_size)
        if self._label:
            label_position = (
                self._position[0],
                self._position[1] - self._font_size * LABEL_OFFSET_SCALE,
            )
            label_size = max(8, round(self._font_size * LABEL_SIZE_SCALE))
            canvas.text(label_position, self._label, common.LABEL_COLOR, label_size)
