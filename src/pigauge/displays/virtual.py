"""VirtualDisplay: keeps the latest frame for tests, previews, and the web UI.

The MJPEG endpoint (Phase 8) reads ``latest_frame``; render_preview and the
golden-image tests use ``save``. Thread-safe: the render loop shows frames
while other threads read them.
"""

import threading
from pathlib import Path
from typing import Literal

from PIL import Image

from pigauge.displays.base import Display


class VirtualDisplay(Display):
    """A display that stores frames instead of driving hardware."""

    def __init__(
        self,
        resolution: tuple[int, int],
        shape: Literal["round", "rect"] = "rect",
    ) -> None:
        """Fix the native resolution and shape this display accepts."""
        self.resolution = (int(resolution[0]), int(resolution[1]))
        self.shape = shape
        self._lock = threading.Lock()
        self._frame: Image.Image | None = None

    def show(self, frame: Image.Image) -> None:
        """Keep a copy of the frame; rejects frames at the wrong resolution."""
        if frame.size != self.resolution:
            raise ValueError(
                f"frame size {frame.size} does not match display resolution {self.resolution}"
            )
        with self._lock:
            self._frame = frame.copy()

    @property
    def latest_frame(self) -> Image.Image | None:
        """A copy of the most recent frame, or None before the first show()."""
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def save(self, path: str | Path) -> None:
        """Write the latest frame as an image file (format from extension)."""
        frame = self.latest_frame
        if frame is None:
            raise RuntimeError("no frame has been shown yet")
        frame.save(path)
