"""Widget tests: rendering behaviour, stale-greying, and the registry."""

import pytest

from pigauge.core.databus import Quality, Reading
from pigauge.render.canvas import PillowCanvas
from pigauge.render.widgets import WIDGET_REGISTRY, common, create_widget

SIZE = 240
CENTER = {"x": 120, "y": 120}
BACKGROUND = (0, 0, 0)

STALE_RGB = (0x6B, 0x72, 0x80)  # common.STALE_COLOR
ACCENT_RGB = (0x2D, 0xD4, 0xBF)  # common.ACCENT_COLOR
REDLINE_RGB = (0xEF, 0x44, 0x44)  # common.REDLINE_COLOR


def blank_canvas() -> PillowCanvas:
    return PillowCanvas(SIZE, SIZE, background="#000000")


def color_counts(canvas: PillowCanvas) -> dict[tuple[int, int, int], int]:
    counts: dict[tuple[int, int, int], int] = {}
    data = canvas.to_image().tobytes()
    for i in range(0, len(data), 3):
        pixel = (data[i], data[i + 1], data[i + 2])
        counts[pixel] = counts.get(pixel, 0) + 1
    return counts


def painted(canvas: PillowCanvas) -> int:
    return sum(count for pixel, count in color_counts(canvas).items() if pixel != BACKGROUND)


def ok_reading(channel="boost.pressure", value=100.0):
    return Reading(channel, value, 0.0, Quality.OK)


def stale_reading(channel="boost.pressure", value=100.0):
    return Reading(channel, value, 0.0, Quality.STALE)


BOOST_ARC_CONFIG = {
    "type": "arc_gauge",
    "channel": "boost.pressure",
    "display_unit": "psi",
    "position": CENTER,
    "radius": 110,
    "sweep": {"start_deg": 135, "end_deg": 405},
    "range": {"min": -15, "max": 30},
    "redline": {"from": 22},
    "ticks": {"major": 5, "minor": 1},
}


class TestRegistry:
    def test_all_phase_2_widgets_registered(self):
        assert set(WIDGET_REGISTRY) == {
            "numeric_readout",
            "arc_gauge",
            "needle_gauge",
            "bar_gauge",
            "sparkline",
            "status_icon",
        }

    def test_create_widget_by_name(self):
        widget = create_widget(dict(BOOST_ARC_CONFIG))
        assert type(widget).__name__ == "ArcGauge"
        assert widget.channel == "boost.pressure"

    def test_unknown_type_lists_known_types(self):
        with pytest.raises(ValueError, match="hologram.*arc_gauge"):
            create_widget({"type": "hologram", "position": CENTER})


class TestEveryWidgetContract:
    """All widgets must handle OK, STALE, and missing readings."""

    CONFIGS = {
        "numeric_readout": {"position": CENTER, "decimals": 1},
        "arc_gauge": BOOST_ARC_CONFIG,
        "needle_gauge": {"position": CENTER, "radius": 100, "range": {"min": 0, "max": 100}},
        "bar_gauge": {"position": CENTER, "width": 200, "height": 40,
                      "range": {"min": 0, "max": 100}},
        "sparkline": {"position": CENTER, "width": 100, "height": 30},
        "status_icon": {"position": CENTER},
    }

    @pytest.mark.parametrize("widget_type", sorted(WIDGET_REGISTRY))
    def test_draws_without_error_for_all_qualities(self, widget_type):
        config = {"type": widget_type, "channel": "boost.pressure",
                  **self.CONFIGS[widget_type]}
        widget = create_widget(config)
        for reading in (ok_reading(), stale_reading(), None):
            widget.draw(blank_canvas(), reading)  # must not raise

    @pytest.mark.parametrize("widget_type", sorted(WIDGET_REGISTRY))
    def test_ok_reading_paints_pixels(self, widget_type):
        config = {"type": widget_type, "channel": "boost.pressure",
                  **self.CONFIGS[widget_type]}
        widget = create_widget(config)
        canvas = blank_canvas()
        widget.draw(canvas, ok_reading(value=50.0))
        if widget_type == "sparkline":  # needs two samples before it draws
            widget.draw(canvas, ok_reading(value=60.0))
        assert painted(canvas) > 0

    @pytest.mark.parametrize("widget_type", sorted(WIDGET_REGISTRY))
    def test_stale_rendering_greys_the_widget(self, widget_type):
        config = {"type": widget_type, "channel": "boost.pressure",
                  **self.CONFIGS[widget_type]}
        widget = create_widget(config)
        if widget_type == "sparkline":  # seed history so there is a line to grey
            seeded = blank_canvas()
            widget.draw(seeded, ok_reading(value=40.0))
            widget.draw(seeded, ok_reading(value=60.0))
        canvas = blank_canvas()
        widget.draw(canvas, stale_reading(value=50.0))
        assert color_counts(canvas).get(STALE_RGB, 0) > 0


class TestNumericReadout:
    def test_converts_to_display_unit(self):
        config = {"type": "numeric_readout", "channel": "boost.pressure",
                  "position": CENTER, "decimals": 1, "font_size": 40}
        converted = blank_canvas()
        create_widget({**config, "display_unit": "psi"}).draw(
            converted, ok_reading(value=101.325)  # 101.325 kPa = 14.7 psi
        )
        reference = blank_canvas()
        create_widget(config).draw(reference, ok_reading(value=14.7))  # renders "14.7" as-is
        assert converted.to_image().tobytes() == reference.to_image().tobytes()

    def test_no_reading_renders_placeholder(self):
        widget = create_widget({"type": "numeric_readout", "position": CENTER})
        canvas = blank_canvas()
        widget.draw(canvas, None)
        assert color_counts(canvas).get(STALE_RGB, 0) > 0  # "--" in stale grey


class TestArcGauge:
    def test_higher_value_paints_longer_arc(self):
        low, high = blank_canvas(), blank_canvas()
        # 20 kPa = 2.9 psi and 120 kPa = 17.4 psi: both below the 22 psi redline
        create_widget(dict(BOOST_ARC_CONFIG)).draw(low, ok_reading(value=20.0))
        create_widget(dict(BOOST_ARC_CONFIG)).draw(high, ok_reading(value=120.0))
        assert color_counts(high).get(ACCENT_RGB, 0) > color_counts(low).get(ACCENT_RGB, 0)

    def test_value_in_redline_paints_red_arc(self):
        canvas = blank_canvas()
        # 25 psi > redline 22 psi; 25 psi = 172.4 kPa base
        create_widget(dict(BOOST_ARC_CONFIG)).draw(canvas, ok_reading(value=172.4))
        counts = color_counts(canvas)
        assert counts.get(REDLINE_RGB, 0) > counts.get(ACCENT_RGB, 0)


class TestBarGauge:
    CONFIG = {
        "type": "bar_gauge", "channel": "engine.rpm", "position": {"x": 120, "y": 40},
        "width": 200, "height": 40, "range": {"min": 0, "max": 4500},
        "redline": {"from": 3800},
    }

    def test_fill_grows_with_value(self):
        low, high = blank_canvas(), blank_canvas()
        create_widget(dict(self.CONFIG)).draw(low, ok_reading("engine.rpm", 1000.0))
        create_widget(dict(self.CONFIG)).draw(high, ok_reading("engine.rpm", 3000.0))
        assert color_counts(high).get(ACCENT_RGB, 0) > color_counts(low).get(ACCENT_RGB, 0)

    def test_redline_value_turns_fill_red(self):
        canvas = blank_canvas()
        create_widget(dict(self.CONFIG)).draw(canvas, ok_reading("engine.rpm", 4200.0))
        assert color_counts(canvas).get(REDLINE_RGB, 0) > 0


class TestSparkline:
    def test_only_ok_readings_recorded(self):
        widget = create_widget({"type": "sparkline", "channel": "engine.rpm",
                                "position": CENTER})
        widget.draw(blank_canvas(), ok_reading("engine.rpm", 1000.0))
        widget.draw(blank_canvas(), stale_reading("engine.rpm", 2000.0))
        widget.draw(blank_canvas(), None)
        assert list(widget._history) == [1000.0]


class TestStatusIcon:
    def test_on_off_render_differently(self):
        config = {"type": "status_icon", "channel": "system.ignition", "position": CENTER}
        on, off = blank_canvas(), blank_canvas()
        create_widget(dict(config)).draw(on, ok_reading("system.ignition", 1.0))
        create_widget(dict(config)).draw(off, ok_reading("system.ignition", 0.0))
        assert on.to_image().tobytes() != off.to_image().tobytes()
        assert painted(on) > painted(off)  # filled vs outline


class TestCommonHelpers:
    def test_angle_clamps_to_sweep(self):
        assert common.angle_for(-100, 0, 100, 135, 405) == 135
        assert common.angle_for(50, 0, 100, 135, 405) == 270
        assert common.angle_for(999, 0, 100, 135, 405) == 405

    def test_display_value_converts_from_base_unit(self):
        reading = ok_reading("engine.coolant_temp", 100.0)
        assert common.display_value(reading, "F") == pytest.approx(212.0)
        assert common.display_value(reading, None) == 100.0

    def test_format_value(self):
        assert common.format_value(14.7268, 1) == "14.7"
        assert common.format_value(None, 1) == "--"

    def test_tick_values_inclusive(self):
        assert common.tick_values(-15, 30, 5) == list(range(-15, 31, 5))
        assert common.tick_values(0, 100, 0) == []

    def test_format_tick_drops_trailing_zero(self):
        assert common.format_tick(5.0) == "5"
        assert common.format_tick(-2.5) == "-2.5"
