"""Drawing abstraction so widgets are written once for every backend.

Phase 2 provides the Pillow backend (VirtualDisplay and, later, the GC9A01
SPI driver); a pygame Surface backend arrives with the HDMI dash in
Phase 3. Coordinates are pixels with the origin top-left. Angles follow the
Pillow convention: degrees clockwise from 3 o'clock, y axis pointing down.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import ClassVar

from PIL import Image, ImageDraw, ImageFont

Point = tuple[float, float]
Color = str | tuple[int, int, int]


class Canvas(ABC):
    """Minimal drawing surface contract shared by all widgets."""

    width: int
    height: int

    @abstractmethod
    def line(self, start: Point, end: Point, color: Color, width: int = 1) -> None:
        """Straight line segment."""

    @abstractmethod
    def polyline(self, points: Sequence[Point], color: Color, width: int = 1) -> None:
        """Connected line through ``points`` (needs at least two)."""

    @abstractmethod
    def arc(
        self,
        center: Point,
        radius: float,
        start_deg: float,
        end_deg: float,
        color: Color,
        width: int = 1,
    ) -> None:
        """Circular arc; the stroke extends inward from ``radius``."""

    @abstractmethod
    def circle(
        self,
        center: Point,
        radius: float,
        fill: Color | None = None,
        outline: Color | None = None,
        width: int = 1,
    ) -> None:
        """Filled and/or outlined circle."""

    @abstractmethod
    def rect(
        self,
        top_left: Point,
        bottom_right: Point,
        fill: Color | None = None,
        outline: Color | None = None,
        width: int = 1,
    ) -> None:
        """Filled and/or outlined axis-aligned rectangle."""

    @abstractmethod
    def polygon(self, points: Sequence[Point], fill: Color) -> None:
        """Filled polygon."""

    @abstractmethod
    def text(
        self,
        position: Point,
        message: str,
        color: Color,
        size: int,
        anchor: str = "mm",
    ) -> None:
        """Text at ``position`` with a Pillow-style anchor (default centred)."""


class PillowCanvas(Canvas):
    """Canvas backed by a Pillow RGB image."""

    _fonts: ClassVar[dict[int, ImageFont.FreeTypeFont]] = {}

    def __init__(self, width: int, height: int, background: Color = "#000000") -> None:
        """Create a cleared image of ``width`` x ``height``."""
        self.width = int(width)
        self.height = int(height)
        self._image = Image.new("RGB", (self.width, self.height), background)
        self._draw = ImageDraw.Draw(self._image)

    def to_image(self) -> Image.Image:
        """The backing image (not a copy; displays copy on show)."""
        return self._image

    def line(self, start: Point, end: Point, color: Color, width: int = 1) -> None:
        self._draw.line([start, end], fill=color, width=int(width))

    def polyline(self, points: Sequence[Point], color: Color, width: int = 1) -> None:
        self._draw.line(list(points), fill=color, width=int(width), joint="curve")

    def arc(
        self,
        center: Point,
        radius: float,
        start_deg: float,
        end_deg: float,
        color: Color,
        width: int = 1,
    ) -> None:
        cx, cy = center
        bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
        self._draw.arc(bbox, start_deg, end_deg, fill=color, width=int(width))

    def circle(
        self,
        center: Point,
        radius: float,
        fill: Color | None = None,
        outline: Color | None = None,
        width: int = 1,
    ) -> None:
        cx, cy = center
        bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
        self._draw.ellipse(bbox, fill=fill, outline=outline, width=int(width))

    def rect(
        self,
        top_left: Point,
        bottom_right: Point,
        fill: Color | None = None,
        outline: Color | None = None,
        width: int = 1,
    ) -> None:
        self._draw.rectangle([top_left, bottom_right], fill=fill, outline=outline, width=int(width))

    def polygon(self, points: Sequence[Point], fill: Color) -> None:
        self._draw.polygon(list(points), fill=fill)

    def text(
        self,
        position: Point,
        message: str,
        color: Color,
        size: int,
        anchor: str = "mm",
    ) -> None:
        self._draw.text(position, message, fill=color, font=self.font(int(size)), anchor=anchor)

    @classmethod
    def font(cls, size: int) -> ImageFont.FreeTypeFont:
        """Pillow's embedded default font, cached per size (no system fonts)."""
        if size not in cls._fonts:
            cls._fonts[size] = ImageFont.load_default(size=size)
        return cls._fonts[size]
