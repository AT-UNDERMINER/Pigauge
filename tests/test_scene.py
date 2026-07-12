"""GaugeScene tests: real layouts render, stale data greys, bad configs fail."""

from pathlib import Path

import pytest

from pigauge.core.config import load_gauge_layout
from pigauge.core.databus import DataBus
from pigauge.render.scene import GaugeScene
from tests.test_databus import FakeClock

REPO_ROOT = Path(__file__).parent.parent
GAUGES_DIR = REPO_ROOT / "config" / "gauges"

BOOST_CHANNELS = {"boost.pressure": 110.0, "exhaust.egt1": 320.0}


def boost_scene(clock=None):
    bus = DataBus(clock=clock) if clock else DataBus()
    layout = load_gauge_layout(GAUGES_DIR / "single_round_boost.yaml")
    return GaugeScene(layout, bus), bus


class TestRendering:
    def test_boost_layout_renders_at_canvas_size(self):
        scene, bus = boost_scene()
        for channel, value in BOOST_CHANNELS.items():
            bus.publish(channel, value)
        frame = scene.render()
        assert frame.size == (240, 240)
        assert scene.shape == "round"

    def test_dash_layout_renders_at_canvas_size(self):
        bus = DataBus()
        layout = load_gauge_layout(GAUGES_DIR / "dash_800x480.yaml")
        frame = GaugeScene(layout, bus).render()
        assert frame.size == (800, 480)

    def test_renders_with_no_data_at_all(self):
        scene, _bus = boost_scene()
        frame = scene.render()  # every widget gets None; must not raise
        assert frame.size == (240, 240)

    def test_data_changes_the_frame(self):
        scene, bus = boost_scene()
        empty = scene.render().tobytes()
        for channel, value in BOOST_CHANNELS.items():
            bus.publish(channel, value)
        live = scene.render().tobytes()
        assert empty != live

    def test_stale_data_renders_differently_from_fresh(self):
        clock = FakeClock()
        scene, bus = boost_scene(clock=clock)
        for channel, value in BOOST_CHANNELS.items():
            bus.publish(channel, value)
        fresh = scene.render().tobytes()
        clock.advance(60.0)  # beyond every stale_after in the layout
        stale = scene.render().tobytes()
        assert fresh != stale


class TestBuildValidation:
    def test_unknown_widget_type_fails_at_build(self):
        layout = load_gauge_layout(GAUGES_DIR / "single_round_boost.yaml")
        broken = layout.model_copy(deep=True)
        broken.widgets[0].type = "hologram"
        with pytest.raises(ValueError, match=r"widgets\[0\].*hologram"):
            GaugeScene(broken, DataBus())

    def test_unknown_channel_fails_at_build(self):
        layout = load_gauge_layout(GAUGES_DIR / "single_round_boost.yaml")
        broken = layout.model_copy(deep=True)
        broken.widgets[1].channel = "warp.speed"
        with pytest.raises(ValueError, match=r"widgets\[1\].*warp.speed"):
            GaugeScene(broken, DataBus())
