"""Unit registry and conversions between base units and display units.

All values on the DataBus are stored in the SI/metric base unit of their
quantity (CLAUDE.md golden rule 6): kPa, °C, km/h, RPM, %, V. Conversion to
display units (psi, bar, °F, mph) happens only in the render layer, driven
by gauge config, through :func:`convert`.

Every unit is an affine transform of its quantity's base unit:
``display = base * scale + offset``.
"""

from dataclasses import dataclass
from enum import Enum

KPA_PER_PSI = 6.894757293168361
KPA_PER_BAR = 100.0
KMH_PER_MPH = 1.609344
FAHRENHEIT_SCALE = 9 / 5
FAHRENHEIT_OFFSET = 32.0


class Quantity(Enum):
    """Physical quantity measured by a channel."""

    PRESSURE = "pressure"
    TEMPERATURE = "temperature"
    SPEED = "speed"
    ROTATIONAL_SPEED = "rotational_speed"
    RATIO = "ratio"
    VOLTAGE = "voltage"
    BOOLEAN = "boolean"


class UnitError(ValueError):
    """Unknown unit name, or a conversion between different quantities."""


@dataclass(frozen=True)
class Unit:
    """A unit expressed as an affine transform of its quantity's base unit."""

    name: str
    quantity: Quantity
    scale: float = 1.0
    offset: float = 0.0

    def from_base(self, value: float) -> float:
        """Convert a base-unit value into this unit."""
        return value * self.scale + self.offset

    def to_base(self, value: float) -> float:
        """Convert a value in this unit into the base unit."""
        return (value - self.offset) / self.scale


UNITS: dict[str, Unit] = {
    unit.name: unit
    for unit in (
        Unit("kPa", Quantity.PRESSURE),
        Unit("psi", Quantity.PRESSURE, scale=1 / KPA_PER_PSI),
        Unit("bar", Quantity.PRESSURE, scale=1 / KPA_PER_BAR),
        Unit("C", Quantity.TEMPERATURE),
        Unit("F", Quantity.TEMPERATURE, scale=FAHRENHEIT_SCALE, offset=FAHRENHEIT_OFFSET),
        Unit("kmh", Quantity.SPEED),
        Unit("mph", Quantity.SPEED, scale=1 / KMH_PER_MPH),
        Unit("rpm", Quantity.ROTATIONAL_SPEED),
        Unit("percent", Quantity.RATIO),
        Unit("V", Quantity.VOLTAGE),
        Unit("bool", Quantity.BOOLEAN),
    )
}

BASE_UNITS: dict[Quantity, str] = {
    Quantity.PRESSURE: "kPa",
    Quantity.TEMPERATURE: "C",
    Quantity.SPEED: "kmh",
    Quantity.ROTATIONAL_SPEED: "rpm",
    Quantity.RATIO: "percent",
    Quantity.VOLTAGE: "V",
    Quantity.BOOLEAN: "bool",
}


def get_unit(name: str) -> Unit:
    """Look up a unit by name, raising :class:`UnitError` if unknown."""
    try:
        return UNITS[name]
    except KeyError:
        raise UnitError(f"unknown unit {name!r} (known: {sorted(UNITS)})") from None


def base_unit(quantity: Quantity) -> str:
    """Return the base unit name for a quantity."""
    return BASE_UNITS[quantity]


def convert(value: float, from_unit: str, to_unit: str) -> float:
    """Convert ``value`` between two units of the same quantity."""
    source = get_unit(from_unit)
    target = get_unit(to_unit)
    if source.quantity is not target.quantity:
        raise UnitError(
            f"cannot convert {from_unit!r} ({source.quantity.value}) "
            f"to {to_unit!r} ({target.quantity.value})"
        )
    return target.from_base(source.to_base(value))
