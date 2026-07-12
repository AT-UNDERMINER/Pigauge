"""VirtualDisplay and render_preview CLI tests."""

import pytest
from PIL import Image

from pigauge.displays.virtual import VirtualDisplay
from pigauge.tools.render_preview import main, simulated_bus


class TestVirtualDisplay:
    def test_show_stores_an_independent_copy(self):
        display = VirtualDisplay((240, 240), shape="round")
        frame = Image.new("RGB", (240, 240), "#102030")
        display.show(frame)
        frame.paste("#ff0000", (0, 0, 240, 240))  # mutate the original
        assert display.latest_frame.getpixel((0, 0)) == (0x10, 0x20, 0x30)

    def test_no_frame_before_first_show(self):
        display = VirtualDisplay((240, 240))
        assert display.latest_frame is None
        with pytest.raises(RuntimeError, match="no frame"):
            display.save("never.png")

    def test_wrong_resolution_rejected(self):
        display = VirtualDisplay((240, 240))
        with pytest.raises(ValueError, match="does not match"):
            display.show(Image.new("RGB", (800, 480)))

    def test_save_writes_png(self, tmp_path):
        display = VirtualDisplay((16, 16))
        display.show(Image.new("RGB", (16, 16), "#123456"))
        out = tmp_path / "frame.png"
        display.save(out)
        assert Image.open(out).size == (16, 16)


class TestSimulatedBus:
    def test_same_seed_and_time_give_identical_bus_state(self):
        first = simulated_bus(seed=42, sim_time_s=12.0)
        second = simulated_bus(seed=42, sim_time_s=12.0)
        for channel_id, reading in first.snapshot().items():
            assert reading.value == second.get(channel_id).value

    def test_stale_flag_ages_every_reading(self):
        bus = simulated_bus(seed=42, sim_time_s=12.0, stale=True)
        assert all(reading.quality.name == "STALE" for reading in bus.snapshot().values())


class TestRenderPreviewCli:
    def test_renders_boost_layout_to_png(self, tmp_path):
        out = tmp_path / "boost.png"
        result = main([
            "--layout", "config/gauges/single_round_boost.yaml", "--out", str(out),
        ])
        assert result == 0
        assert Image.open(out).size == (240, 240)

    def test_same_arguments_produce_identical_bytes(self, tmp_path):
        first, second = tmp_path / "a.png", tmp_path / "b.png"
        for out in (first, second):
            assert main([
                "--layout", "config/gauges/single_round_boost.yaml",
                "--out", str(out), "--seed", "7", "--sim-time", "9",
            ]) == 0
        assert first.read_bytes() == second.read_bytes()

    def test_missing_layout_exits_one(self, tmp_path, capsys):
        result = main(["--layout", "config/gauges/nope.yaml", "--out", str(tmp_path / "x.png")])
        assert result == 1
        assert "nope.yaml" in capsys.readouterr().err
