"""Shared widget helpers: palette, stale-greying, unit conversion, dial math.

Stale policy (docs/ARCHITECTURE.md): a STALE or missing reading renders in
STALE_COLOR instead of the configured colour — data is still shown, but
visibly untrusted.
"""

import math
from typing import Any

from pigauge.core.channels import CHANNELS
from pigauge.core.databus import Quality, Reading
from pigauge.core.units import convert

TEXT_COLOR = "#f5f5f5"
LABEL_COLOR = "#9ca3af"
ACCENT_COLOR = "#2dd4bf"
REDLINE_COLOR = "#ef4444"
REDLINE_ZONE_COLOR = "#7f1d1d"
STALE_COLOR = "#6b7280"
TRACK_COLOR = "#2a2a33"
NO_DATA_TEXT = "--"


def is_live(reading: Reading | None) -> bool:
    """True when the reading exists and is fresh (quality OK)."""
    return reading is not None and reading.quality is Quality.OK


def paint(color: str, reading: Reading | None) -> str:
    """The configured colour while data is fresh, STALE_COLOR otherwise."""
    return color if is_live(reading) else STALE_COLOR


def display_value(reading: Reading | None, display_unit: str | None) -> float | None:
    """Reading value converted from base units to the widget's display unit."""
    if reading is None or math.isnan(reading.value):
        return None
    if display_unit is None:
        return reading.value
    base = CHANNELS[reading.channel_id].base_unit
    return convert(reading.value, base, display_unit)


def format_value(value: float | None, decimals: int) -> str:
    """Fixed-decimals number, or the no-data placeholder."""
    if value is None:
        return NO_DATA_TEXT
    return f"{value:.{decimals}f}"


def position_of(config: dict[str, Any]) -> tuple[float, float]:
    """Widget anchor point from its layout entry."""
    position = config.get("position", {})
    return (float(position.get("x", 0)), float(position.get("y", 0)))


def range_of(config: dict[str, Any], default: tuple[float, float]) -> tuple[float, float]:
    """(min, max) from a layout ``range:`` entry, in display units."""
    rng = config.get("range", {})
    return (float(rng.get("min", default[0])), float(rng.get("max", default[1])))


def sweep_of(config: dict[str, Any], default: tuple[float, float]) -> tuple[float, float]:
    """(start_deg, end_deg) from a layout ``sweep:`` entry."""
    sweep = config.get("sweep", {})
    return (
        float(sweep.get("start_deg", default[0])),
        float(sweep.get("end_deg", default[1])),
    )


def redline_from(config: dict[str, Any]) -> float | None:
    """Start of the redline zone in display units, if configured."""
    redline = config.get("redline")
    if not redline or "from" not in redline:
        return None
    return float(redline["from"])


def fraction_for(value: float, minimum: float, maximum: float) -> float:
    """Position of ``value`` in [min, max], clamped to [0, 1]."""
    span = maximum - minimum
    if span == 0:
        return 0.0
    return min(1.0, max(0.0, (value - minimum) / span))


def angle_for(
    value: float, minimum: float, maximum: float, start_deg: float, end_deg: float
) -> float:
    """Dial angle for ``value``, clamped to the sweep."""
    return start_deg + fraction_for(value, minimum, maximum) * (end_deg - start_deg)


def polar(center: tuple[float, float], radius: float, angle_deg: float) -> tuple[float, float]:
    """Point at ``radius``/``angle_deg`` using the Pillow angle convention."""
    radians = math.radians(angle_deg)
    return (center[0] + radius * math.cos(radians), center[1] + radius * math.sin(radians))


def tick_values(minimum: float, maximum: float, step: float) -> list[float]:
    """Values from min to max inclusive at ``step`` (empty if step invalid)."""
    if step <= 0:
        return []
    count = round((maximum - minimum) / step)
    return [minimum + i * step for i in range(count + 1)]


def format_tick(value: float) -> str:
    """Compact tick label (no trailing .0)."""
    return f"{value:g}"
