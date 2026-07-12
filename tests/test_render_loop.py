"""Multi-display render loop tests: bindings, FPS overlay, pacing, stats."""

from pathlib import Path

import pytest

from pigauge.core.config import load_app_config
from pigauge.core.databus import DataBus
from pigauge.displays import DISPLAY_REGISTRY, create_display
from pigauge.render.loop import RenderLoop, bindings_from_config

REPO_ROOT = Path(__file__).parent.parent

TWO_DISPLAY_CONFIG = """
vehicle_profile: config/vehicles/generic_obd2.yaml
displays:
  - name: boost_pod
    driver: virtual
    resolution: [240, 240]
    shape: round
    layout: config/gauges/single_round_boost.yaml
  - name: dash
    driver: virtual
    resolution: [800, 480]
    shape: rect
    layout: config/gauges/dash_800x480.yaml
render: {target_fps: 30, fps_overlay: false}
"""


@pytest.fixture
def two_display_bindings(tmp_path):
    config_file = tmp_path / "two_displays.yaml"
    config_file.write_text(TWO_DISPLAY_CONFIG, encoding="utf-8")
    config = load_app_config(config_file)
    bus = DataBus()
    bus.publish("boost.pressure", 110.0)
    bus.publish("engine.rpm", 3000.0)
    return bindings_from_config(config, bus, base_dir=REPO_ROOT), bus


class TestDisplayRegistry:
    def test_registry_names(self):
        assert set(DISPLAY_REGISTRY) == {"virtual", "gc9a01", "framebuffer"}

    def test_unknown_driver_rejected(self, tmp_path):
        config_file = tmp_path / "bad.yaml"
        config_file.write_text(
            TWO_DISPLAY_CONFIG.replace("driver: virtual", "driver: hologram", 1),
            encoding="utf-8",
        )
        config = load_app_config(config_file)
        with pytest.raises(ValueError, match="hologram.*virtual"):
            create_display(config.displays[0])


class TestBindings:
    def test_each_display_gets_its_own_layout(self, two_display_bindings):
        bindings, _bus = two_display_bindings
        assert [binding.name for binding in bindings] == ["boost_pod", "dash"]
        assert bindings[0].display.resolution == (240, 240)
        assert bindings[0].scene.resolution == (240, 240)
        assert bindings[1].display.resolution == (800, 480)
        assert bindings[1].scene.resolution == (800, 480)


class TestRenderLoop:
    def test_step_services_every_display(self, two_display_bindings):
        bindings, _bus = two_display_bindings
        loop = RenderLoop(bindings)
        loop.step()
        for binding in bindings:
            frame = binding.display.latest_frame
            assert frame is not None
            assert frame.size == binding.scene.resolution
        assert loop.frame_counts == {"boost_pod": 1, "dash": 1}

    def test_fps_overlay_changes_the_frame(self, two_display_bindings):
        bindings, _bus = two_display_bindings
        RenderLoop(bindings, fps_overlay=False).step()
        plain = bindings[0].display.latest_frame.tobytes()
        overlay_loop = RenderLoop(bindings, fps_overlay=True)
        overlay_loop.step()
        overlay_loop.step()  # second frame has a real FPS number
        stamped = bindings[0].display.latest_frame.tobytes()
        assert plain != stamped

    def test_run_with_duration_returns_and_counts_frames(self, two_display_bindings):
        bindings, _bus = two_display_bindings
        loop = RenderLoop(bindings, target_fps=120)
        loop.run(duration_s=0.2)
        assert loop.frame_counts["boost_pod"] >= 2
        assert loop.frame_counts["boost_pod"] == loop.frame_counts["dash"]
        assert loop.fps["boost_pod"] > 0

    def test_stop_makes_run_return(self, two_display_bindings):
        bindings, _bus = two_display_bindings
        loop = RenderLoop(bindings, target_fps=120)
        loop.stop()  # pre-armed — but run() clears it, so stop from a callback
        _original_step = loop.step

        def step_then_stop():
            _original_step()
            loop.stop()

        loop.step = step_then_stop
        loop.run()  # no duration: only stop() can end it
        assert loop.frame_counts["boost_pod"] == 1

    def test_pacing_sleeps_toward_target_fps(self, two_display_bindings):
        bindings, _bus = two_display_bindings
        sleeps = []
        fake_now = [0.0]

        def clock():
            fake_now[0] += 0.001  # each clock() call advances 1 ms
            return fake_now[0]

        loop = RenderLoop(bindings, target_fps=10, clock=clock, sleep=sleeps.append)
        loop.run(duration_s=1.0)
        assert sleeps, "expected the loop to sleep between frames"
        assert all(0 < duration <= 0.1 for duration in sleeps)
