"""GC9A01 240x240 round SPI display driver.

Pillow frame -> RGB565 (big-endian) blit over spidev, with DC/RST/backlight
on gpiozero pins. Pin defaults mirror docs/HARDWARE.md (SPI1, CS GPIO18,
DC GPIO16, RST GPIO13, BL GPIO12). Hardware libraries are optional
extras with guarded imports (golden rule 2): the module always imports; a
clear error is raised only when constructing without hardware or injected
test doubles. Rotation is handled on the panel via MADCTL, so frames are
never rotated in Python.

On-Pi items still to verify visually (flagged in Phase 3 summary):
MADCTL rotation/colour-order values and the vendor init sequence.
"""

import time
from collections.abc import Callable
from typing import Any

from PIL import Image, ImageChops

from pigauge.displays.base import Display
from pigauge.displays.gc9a01_init import INIT_SEQUENCE

try:  # hardware-only dependencies (pip install pigauge[pi])
    import spidev
except ImportError:  # pragma: no cover - dev machines have no spidev
    spidev = None
try:
    from gpiozero import DigitalOutputDevice, PWMOutputDevice
except ImportError:  # pragma: no cover
    DigitalOutputDevice = None
    PWMOutputDevice = None

NATIVE_RESOLUTION = (240, 240)
DEFAULT_SPI_HZ = 40_000_000
SPI_CHUNK_BYTES = 4096
RESET_PULSE_S = 0.01
RESET_SETTLE_S = 0.12

CMD_CASET = 0x2A
CMD_RASET = 0x2B
CMD_RAMWR = 0x2C
CMD_MADCTL = 0x36
CMD_DISPLAY_OFF = 0x28

# spidev addresses (bus, chip-enable index); CS GPIO pins per docs/HARDWARE.md
CS_PIN_TO_DEVICE = {(0, 8): 0, (0, 7): 1, (1, 18): 0, (1, 17): 1, (1, 16): 2}

# MADCTL per rotation, BGR bit set (typical GC9A01 panels) - verify on-Pi
MADCTL_BY_ROTATION = {0: 0x08, 90: 0x68, 180: 0xC8, 270: 0xA8}

# RGB888 -> RGB565 via per-channel LUTs; hi|lo pairs never overlap bits,
# so ImageChops.add acts as bitwise OR at C speed (no numpy needed).
_R_HI = [value & 0xF8 for value in range(256)]
_G_HI = [value >> 5 for value in range(256)]
_G_LO = [(value << 3) & 0xE0 for value in range(256)]
_B_LO = [value >> 3 for value in range(256)]


def frame_to_rgb565(frame: Image.Image) -> bytes:
    """Pillow RGB image to big-endian RGB565 bytes (panel byte order)."""
    red, green, blue = frame.split()
    hi = ImageChops.add(red.point(_R_HI), green.point(_G_HI)).tobytes()
    lo = ImageChops.add(green.point(_G_LO), blue.point(_B_LO)).tobytes()
    interleaved = bytearray(2 * len(hi))
    interleaved[0::2] = hi
    interleaved[1::2] = lo
    return bytes(interleaved)


def spi_device_for_cs(spi_bus: int, cs_pin: int) -> int:
    """Chip-enable index for a CS GPIO pin (mapping from docs/HARDWARE.md)."""
    try:
        return CS_PIN_TO_DEVICE[(spi_bus, cs_pin)]
    except KeyError:
        raise ValueError(
            f"no chip-enable mapping for cs_pin {cs_pin} on SPI{spi_bus} "
            f"(known: {sorted(CS_PIN_TO_DEVICE)})"
        ) from None


class Gc9a01Display(Display):
    """Round SPI gauge display; frames must arrive at native 240x240."""

    shape = "round"

    def __init__(
        self,
        *,
        resolution: tuple[int, int] = NATIVE_RESOLUTION,
        spi_bus: int = 1,
        cs_pin: int = 18,
        dc_pin: int = 16,
        rst_pin: int = 13,
        backlight_pin: int = 12,
        spi_hz: int = DEFAULT_SPI_HZ,
        rotation: int = 0,
        spi: Any = None,
        dc: Any = None,
        rst: Any = None,
        backlight: Any = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Open the SPI device and pins (or use injected test doubles)."""
        if rotation not in MADCTL_BY_ROTATION:
            raise ValueError(f"rotation must be one of {sorted(MADCTL_BY_ROTATION)}")
        self.resolution = (int(resolution[0]), int(resolution[1]))
        self._sleep = sleep
        self._spi = spi if spi is not None else self._open_spi(spi_bus, cs_pin, spi_hz)
        self._dc = dc if dc is not None else self._output_pin(dc_pin)
        self._rst = rst if rst is not None else self._output_pin(rst_pin)
        self._backlight = (
            backlight if backlight is not None else self._pwm_pin(backlight_pin)
        )
        self._reset()
        self._initialise(rotation)
        self.set_backlight(1.0)

    def show(self, frame: Image.Image) -> None:
        """Blit one full frame (RGB565) into the panel RAM."""
        if frame.size != self.resolution:
            raise ValueError(
                f"frame size {frame.size} does not match display resolution {self.resolution}"
            )
        width, height = self.resolution
        self._command(CMD_CASET, self._window_bounds(width))
        self._command(CMD_RASET, self._window_bounds(height))
        self._command(CMD_RAMWR)
        self._write_data(frame_to_rgb565(frame))

    def set_backlight(self, level: float) -> None:
        """Backlight brightness 0.0-1.0 (PWM pin)."""
        self._backlight.value = min(1.0, max(0.0, level))

    def close(self) -> None:
        """Blank the panel, kill the backlight, release the SPI device."""
        self._command(CMD_DISPLAY_OFF)
        self.set_backlight(0.0)
        self._spi.close()

    def _reset(self) -> None:
        self._rst.value = 1
        self._sleep(RESET_PULSE_S)
        self._rst.value = 0
        self._sleep(RESET_PULSE_S)
        self._rst.value = 1
        self._sleep(RESET_SETTLE_S)

    def _initialise(self, rotation: int) -> None:
        for command, data, delay_ms in INIT_SEQUENCE:
            self._command(command, data)
            if delay_ms:
                self._sleep(delay_ms / 1000)
        self._command(CMD_MADCTL, bytes([MADCTL_BY_ROTATION[rotation]]))

    def _command(self, command: int, data: bytes = b"") -> None:
        """Send a command byte (DC low) and optional parameters (DC high)."""
        self._dc.value = 0
        self._spi.writebytes2(bytes([command]))
        if data:
            self._write_data(data)

    def _write_data(self, data: bytes) -> None:
        self._dc.value = 1
        for offset in range(0, len(data), SPI_CHUNK_BYTES):
            self._spi.writebytes2(data[offset : offset + SPI_CHUNK_BYTES])

    @staticmethod
    def _window_bounds(extent: int) -> bytes:
        """CASET/RASET payload covering 0..extent-1."""
        last = extent - 1
        return bytes([0, 0, last >> 8, last & 0xFF])

    @staticmethod
    def _open_spi(spi_bus: int, cs_pin: int, spi_hz: int) -> Any:
        if spidev is None:
            raise RuntimeError(
                "spidev is not installed - install hardware extras: pip install 'pigauge[pi]'"
            )
        device = spi_device_for_cs(spi_bus, cs_pin)
        spi = spidev.SpiDev()
        spi.open(spi_bus, device)
        spi.max_speed_hz = spi_hz
        spi.mode = 0
        return spi

    @staticmethod
    def _output_pin(pin: int) -> Any:
        if DigitalOutputDevice is None:
            raise RuntimeError(
                "gpiozero is not installed - install hardware extras: pip install 'pigauge[pi]'"
            )
        return DigitalOutputDevice(pin)

    @staticmethod
    def _pwm_pin(pin: int) -> Any:
        if PWMOutputDevice is None:
            raise RuntimeError(
                "gpiozero is not installed - install hardware extras: pip install 'pigauge[pi]'"
            )
        return PWMOutputDevice(pin)
