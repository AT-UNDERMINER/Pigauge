"""Fullscreen pygame display for the HDMI/DSI dash (KMSDRM, no desktop).

pygame is an optional extra with a guarded import (golden rule 2): the
module always imports on a dev machine; constructing without pygame (or an
injected test double) raises an install hint. On the Pi the SDL video
driver defaults to KMSDRM so the dash renders straight to the display
stack from a console boot (docs/HARDWARE.md §Displays).
"""

import os
from typing import Any, Literal

from PIL import Image

from pigauge.displays.base import Display

try:  # hardware-only dependency (pip install pigauge[pi])
    import pygame
except ImportError:  # pragma: no cover - dev machines run the mock
    pygame = None

DEFAULT_SDL_DRIVER = "kmsdrm"


class FramebufferDisplay(Display):
    """Rectangular dash display: PIL frames blitted to a pygame surface."""

    shape: Literal["round", "rect"] = "rect"

    def __init__(
        self,
        resolution: tuple[int, int],
        fullscreen: bool = True,
        sdl_driver: str | None = DEFAULT_SDL_DRIVER,
        pygame_module: Any = None,
    ) -> None:
        """Initialise the video mode (KMSDRM fullscreen by default)."""
        self._pygame = pygame_module if pygame_module is not None else pygame
        if self._pygame is None:
            raise RuntimeError(
                "pygame is not installed - install hardware extras: pip install 'pigauge[pi]'"
            )
        self.resolution = (int(resolution[0]), int(resolution[1]))
        if sdl_driver:
            os.environ.setdefault("SDL_VIDEODRIVER", sdl_driver)
        self._pygame.display.init()
        flags = self._pygame.FULLSCREEN if fullscreen else 0
        self._surface = self._pygame.display.set_mode(self.resolution, flags)
        self._pygame.mouse.set_visible(False)

    def show(self, frame: Image.Image) -> None:
        """Blit one frame and flip; must arrive at the native resolution."""
        if frame.size != self.resolution:
            raise ValueError(
                f"frame size {frame.size} does not match display resolution {self.resolution}"
            )
        surface = self._pygame.image.frombuffer(frame.tobytes(), frame.size, "RGB")
        self._surface.blit(surface, (0, 0))
        self._pygame.display.flip()

    def close(self) -> None:
        """Release the video mode."""
        self._pygame.display.quit()
