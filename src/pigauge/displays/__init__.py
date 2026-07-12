"""Display registry: config ``driver`` strings to classes (golden rule 3).

The core never imports a concrete driver directly; displays are selected
by name from YAML via :func:`create_display`. Hardware drivers construct
lazily, so a config that only uses ``virtual`` never touches spidev or
pygame.
"""

from pigauge.core.config.models import DisplayConfig
from pigauge.displays.base import Display
from pigauge.displays.framebuffer import FramebufferDisplay
from pigauge.displays.gc9a01 import Gc9a01Display
from pigauge.displays.virtual import VirtualDisplay

__all__ = [
    "DISPLAY_REGISTRY",
    "Display",
    "FramebufferDisplay",
    "Gc9a01Display",
    "VirtualDisplay",
    "create_display",
]

DISPLAY_REGISTRY: dict[str, type[Display]] = {
    "virtual": VirtualDisplay,
    "gc9a01": Gc9a01Display,
    "framebuffer": FramebufferDisplay,
}


def create_display(config: DisplayConfig) -> Display:
    """Build the display named by ``config.driver`` from its config entry."""
    if config.driver not in DISPLAY_REGISTRY:
        raise ValueError(
            f"unknown display driver {config.driver!r} (known: {sorted(DISPLAY_REGISTRY)})"
        )
    if config.driver == "virtual":
        return VirtualDisplay(config.resolution, shape=config.shape)
    if config.driver == "framebuffer":
        return FramebufferDisplay(config.resolution)
    gc9a01_settings = {
        "spi_bus": config.spi_bus,
        "cs_pin": config.cs_pin,
        "dc_pin": config.dc_pin,
        "rst_pin": config.rst_pin,
        "backlight_pin": config.backlight_pin,
        "spi_hz": config.spi_hz,
    }
    provided = {key: value for key, value in gc9a01_settings.items() if value is not None}
    return Gc9a01Display(resolution=config.resolution, rotation=config.rotation, **provided)
