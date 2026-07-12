"""PillowCanvas tests: primitives actually put pixels on the image."""

import pytest

from pigauge.render.canvas import PillowCanvas

BLACK = (0, 0, 0)
WHITE = "#ffffff"
SIZE = 64


@pytest.fixture
def canvas():
    return PillowCanvas(SIZE, SIZE, background="#000000")


def painted_pixel_count(canvas: PillowCanvas) -> int:
    data = canvas.to_image().tobytes()
    return sum(1 for i in range(0, len(data), 3) if data[i : i + 3] != b"\x00\x00\x00")


def test_new_canvas_is_background_only(canvas):
    assert painted_pixel_count(canvas) == 0
    assert canvas.to_image().size == (SIZE, SIZE)


def test_background_colour_applied():
    canvas = PillowCanvas(4, 4, background="#123456")
    assert canvas.to_image().getpixel((0, 0)) == (0x12, 0x34, 0x56)


def test_line_paints_expected_pixels(canvas):
    canvas.line((0, 32), (63, 32), WHITE, width=1)
    assert canvas.to_image().getpixel((10, 32)) == (255, 255, 255)
    assert painted_pixel_count(canvas) == SIZE


def test_polyline_connects_points(canvas):
    canvas.polyline([(0, 0), (31, 31), (63, 0)], WHITE, width=1)
    assert canvas.to_image().getpixel((31, 31)) == (255, 255, 255)


def test_arc_stays_within_radius(canvas):
    canvas.arc((32, 32), 20, 0, 360, WHITE, width=2)
    image = canvas.to_image()
    assert painted_pixel_count(canvas) > 0
    assert image.getpixel((32, 32)) == BLACK  # centre untouched
    assert image.getpixel((32 + 20, 32)) == (255, 255, 255)  # on the rim


def test_circle_fill_and_outline(canvas):
    canvas.circle((32, 32), 10, fill="#ff0000")
    assert canvas.to_image().getpixel((32, 32)) == (255, 0, 0)
    canvas.circle((32, 32), 14, outline=WHITE, width=1)
    assert canvas.to_image().getpixel((32 + 14, 32)) == (255, 255, 255)


def test_rect_fill(canvas):
    canvas.rect((10, 10), (20, 20), fill=WHITE)
    assert canvas.to_image().getpixel((15, 15)) == (255, 255, 255)
    assert canvas.to_image().getpixel((25, 25)) == BLACK


def test_polygon_fill(canvas):
    canvas.polygon([(32, 10), (54, 54), (10, 54)], fill=WHITE)
    assert canvas.to_image().getpixel((32, 40)) == (255, 255, 255)


def test_text_renders_pixels(canvas):
    canvas.text((32, 32), "88", WHITE, size=20)
    assert painted_pixel_count(canvas) > 20


def test_font_cache_reuses_instances():
    assert PillowCanvas.font(17) is PillowCanvas.font(17)
