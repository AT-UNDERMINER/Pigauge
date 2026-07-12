"""GC9A01 driver tests against mocked SPI and pins (Phase 3 dev acceptance)."""

import pytest
from PIL import Image

import pigauge.displays.gc9a01 as gc9a01_module
from pigauge.displays.gc9a01 import (
    CMD_RAMWR,
    SPI_CHUNK_BYTES,
    Gc9a01Display,
    frame_to_rgb565,
    spi_device_for_cs,
)

FRAME_BYTES = 240 * 240 * 2


class FakeSpi:
    def __init__(self):
        self.writes: list[bytes] = []
        self.closed = False

    def writebytes2(self, data):
        self.writes.append(bytes(data))

    def close(self):
        self.closed = True


class FakePin:
    def __init__(self):
        self.value = 0
        self.history: list[float] = []

    def __setattr__(self, name, new_value):
        if name == "value" and hasattr(self, "history"):
            self.history.append(new_value)
        super().__setattr__(name, new_value)


def make_display(**overrides):
    parts = {
        "spi": FakeSpi(),
        "dc": FakePin(),
        "rst": FakePin(),
        "backlight": FakePin(),
        "sleep": lambda seconds: None,
    }
    parts.update(overrides)
    display = Gc9a01Display(**parts)
    return display, parts


def sent_commands(spi: FakeSpi, dc: FakePin) -> list[int]:
    """Command bytes only: single-byte writes are commands when DC was low."""
    # every _command() writes exactly one 1-byte chunk with DC low first
    return [write[0] for write in spi.writes if len(write) == 1]


class TestRgb565Conversion:
    @pytest.mark.parametrize(("color", "expected"), [
        ((255, 0, 0), b"\xf8\x00"),
        ((0, 255, 0), b"\x07\xe0"),
        ((0, 0, 255), b"\x00\x1f"),
        ((255, 255, 255), b"\xff\xff"),
        ((0, 0, 0), b"\x00\x00"),
    ])
    def test_solid_colors(self, color, expected):
        frame = Image.new("RGB", (4, 2), color)
        assert frame_to_rgb565(frame) == expected * 8

    def test_output_length(self):
        frame = Image.new("RGB", (240, 240))
        assert len(frame_to_rgb565(frame)) == FRAME_BYTES


class TestCsMapping:
    def test_hardware_md_pins(self):
        assert spi_device_for_cs(1, 18) == 0  # first gauge (SPI1 CE0)
        assert spi_device_for_cs(1, 17) == 1  # second gauge (SPI1 CE1)
        assert spi_device_for_cs(0, 8) == 0

    def test_unmapped_pin_rejected(self):
        with pytest.raises(ValueError, match="no chip-enable mapping"):
            spi_device_for_cs(1, 22)


class TestInitialisation:
    def test_reset_is_pulsed_before_init(self):
        _display, parts = make_display()
        assert parts["rst"].history == [1, 0, 1]

    def test_init_sequence_sent_and_display_turned_on(self):
        _display, parts = make_display()
        commands = sent_commands(parts["spi"], parts["dc"])
        assert commands[0] == 0xEF  # inter-register enable comes first
        assert 0x3A in commands  # COLMOD 16bpp
        assert 0x11 in commands  # sleep out
        assert 0x29 in commands  # display on
        assert commands.index(0x11) < commands.index(0x29)

    def test_backlight_full_on_after_init(self):
        _display, parts = make_display()
        assert parts["backlight"].value == 1.0

    def test_rotation_selects_madctl(self):
        _display, parts = make_display()
        writes = parts["spi"].writes
        madctl_index = [w[0] for w in writes if len(w) == 1].index(0x36)
        # the data write immediately follows its command write
        command_positions = [i for i, w in enumerate(writes) if len(w) == 1]
        assert writes[command_positions[madctl_index] + 1] == b"\x08"

    def test_invalid_rotation_rejected(self):
        with pytest.raises(ValueError, match="rotation"):
            make_display(**{"spi": FakeSpi(), "dc": FakePin(), "rst": FakePin(),
                            "backlight": FakePin(), "sleep": lambda s: None,
                            "rotation": 45})


class TestShow:
    def test_full_frame_blit_sends_window_then_pixels(self):
        display, parts = make_display()
        parts["spi"].writes.clear()
        display.show(Image.new("RGB", (240, 240), (255, 0, 0)))
        commands = sent_commands(parts["spi"], parts["dc"])
        assert commands == [0x2A, 0x2B, CMD_RAMWR]
        data_bytes = sum(len(w) for w in parts["spi"].writes if len(w) > 1)
        # two 4-byte window payloads (CASET/RASET) plus the full frame
        assert data_bytes == FRAME_BYTES + 8

    def test_pixel_data_chunked_for_spidev(self):
        display, parts = make_display()
        parts["spi"].writes.clear()
        display.show(Image.new("RGB", (240, 240)))
        assert all(len(write) <= SPI_CHUNK_BYTES for write in parts["spi"].writes)

    def test_window_covers_full_panel(self):
        display, parts = make_display()
        parts["spi"].writes.clear()
        display.show(Image.new("RGB", (240, 240)))
        assert parts["spi"].writes[1] == bytes([0, 0, 0, 239])  # CASET 0..239

    def test_wrong_frame_size_rejected(self):
        display, _parts = make_display()
        with pytest.raises(ValueError, match="does not match"):
            display.show(Image.new("RGB", (800, 480)))


class TestLifecycle:
    def test_set_backlight_clamps(self):
        display, parts = make_display()
        display.set_backlight(2.0)
        assert parts["backlight"].value == 1.0
        display.set_backlight(-1.0)
        assert parts["backlight"].value == 0.0

    def test_close_blanks_and_releases(self):
        display, parts = make_display()
        display.close()
        assert parts["spi"].closed
        assert parts["backlight"].value == 0.0
        assert sent_commands(parts["spi"], parts["dc"])[-1] == 0x28  # display off


class TestGuardedImports:
    def test_module_imports_without_hardware_libs(self):
        assert gc9a01_module is not None  # importing this test file proves it

    def test_construction_without_spidev_gives_install_hint(self, monkeypatch):
        monkeypatch.setattr(gc9a01_module, "spidev", None)
        with pytest.raises(RuntimeError, match=r"pigauge\[pi\]"):
            Gc9a01Display(dc=FakePin(), rst=FakePin(), backlight=FakePin(),
                          sleep=lambda s: None)

    def test_construction_without_gpiozero_gives_install_hint(self, monkeypatch):
        monkeypatch.setattr(gc9a01_module, "DigitalOutputDevice", None)
        with pytest.raises(RuntimeError, match=r"pigauge\[pi\]"):
            Gc9a01Display(spi=FakeSpi(), sleep=lambda s: None)
