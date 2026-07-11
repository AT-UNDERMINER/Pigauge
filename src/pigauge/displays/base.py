"""Display interface: anything that can show a rendered frame.

Concrete implementations: VirtualDisplay (Phase 2), Gc9a01Display and
FramebufferDisplay (Phase 3). Frames arrive as Pillow RGB images at the
display's native resolution; drivers only convert and blit.
"""

from abc import ABC, abstractmethod
from typing import Literal

from PIL import Image


class Display(ABC):
    """A physical or virtual output surface."""

    resolution: tuple[int, int]
    shape: Literal["round", "rect"]

    @abstractmethod
    def show(self, frame: Image.Image) -> None:
        """Present a frame. Must not block longer than one frame period."""

    def set_backlight(self, level: float) -> None:  # noqa: B027 - optional hook
        """Optional 0.0-1.0 brightness; default no-op for displays without it."""

    def close(self) -> None:  # noqa: B027 - optional hook
        """Release hardware resources; default no-op."""
