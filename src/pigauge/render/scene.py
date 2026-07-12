"""GaugeScene: a validated layout bound to the DataBus, rendered per frame.

The scene builds its widget list once from a :class:`GaugeLayout` (failing
fast on unknown widget types or channels) and then renders frames on
demand: each render reads the latest cached value per channel from the bus
— never blocking (golden rule 5) — and hands it to the widget, which
converts to display units and greys itself when the reading is stale.
"""

from PIL import Image

from pigauge.core.config import GaugeLayout
from pigauge.core.databus import DataBus
from pigauge.render.canvas import PillowCanvas
from pigauge.render.widgets import create_widget


class GaugeScene:
    """One display's widget tree, rebuilt only when the layout changes."""

    def __init__(self, layout: GaugeLayout, bus: DataBus) -> None:
        """Build widgets from ``layout``, validating types and channels."""
        self._layout = layout
        self._bus = bus
        self._widgets = []
        known_channels = bus.channels
        for index, widget_config in enumerate(layout.widgets):
            config = widget_config.model_dump()
            try:
                widget = create_widget(config)
            except ValueError as error:
                raise ValueError(f"{layout.name}: widgets[{index}]: {error}") from None
            if widget.channel is not None and widget.channel not in known_channels:
                raise ValueError(
                    f"{layout.name}: widgets[{index}]: unknown channel {widget.channel!r}"
                )
            self._widgets.append(widget)

    @property
    def resolution(self) -> tuple[int, int]:
        """Canvas size in pixels (width, height)."""
        return (self._layout.canvas.width, self._layout.canvas.height)

    @property
    def shape(self) -> str:
        """Canvas shape: ``round`` or ``rect``."""
        return self._layout.canvas.shape

    def render(self) -> Image.Image:
        """Draw every widget against the latest bus values; returns the frame."""
        width, height = self.resolution
        canvas = PillowCanvas(width, height, background=self._layout.canvas.background)
        for widget in self._widgets:
            reading = self._bus.get(widget.channel) if widget.channel else None
            widget.draw(canvas, reading)
        return canvas.to_image()
