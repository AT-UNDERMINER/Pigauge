"""Unit conversion tests: property-tested round-trips plus known values."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pigauge.core.units import BASE_UNITS, UNITS, Quantity, UnitError, base_unit, convert

CONVERTIBLE_PAIRS = [
    (a.name, b.name)
    for a in UNITS.values()
    for b in UNITS.values()
    if a.quantity is b.quantity and a.name != b.name
]


@pytest.mark.parametrize(("from_unit", "to_unit"), CONVERTIBLE_PAIRS)
@given(value=st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False))
def test_round_trip_recovers_value(from_unit, to_unit, value):
    round_tripped = convert(convert(value, from_unit, to_unit), to_unit, from_unit)
    assert round_tripped == pytest.approx(value, rel=1e-9, abs=1e-6)


class TestKnownConversions:
    """Spot checks against published conversion factors."""

    def test_kpa_to_psi(self):
        assert convert(100.0, "kPa", "psi") == pytest.approx(14.503774, abs=1e-5)

    def test_kpa_to_bar(self):
        assert convert(100.0, "kPa", "bar") == pytest.approx(1.0)

    def test_psi_to_kpa(self):
        assert convert(14.7, "psi", "kPa") == pytest.approx(101.353, abs=1e-2)

    def test_celsius_to_fahrenheit(self):
        assert convert(0.0, "C", "F") == pytest.approx(32.0)
        assert convert(100.0, "C", "F") == pytest.approx(212.0)
        assert convert(-40.0, "C", "F") == pytest.approx(-40.0)

    def test_kmh_to_mph(self):
        assert convert(100.0, "kmh", "mph") == pytest.approx(62.137119, abs=1e-5)

    def test_identity_conversion(self):
        assert convert(1234.5, "kPa", "kPa") == 1234.5


class TestErrors:
    def test_cross_quantity_conversion_rejected(self):
        with pytest.raises(UnitError, match="cannot convert"):
            convert(1.0, "kPa", "C")

    def test_unknown_unit_rejected(self):
        with pytest.raises(UnitError, match="unknown unit"):
            convert(1.0, "kPa", "furlongs")


class TestBaseUnits:
    """CLAUDE.md golden rule 6: SI/metric base units per quantity."""

    def test_every_quantity_has_a_base_unit(self):
        assert set(BASE_UNITS) == set(Quantity)

    def test_base_units_are_metric(self):
        assert base_unit(Quantity.PRESSURE) == "kPa"
        assert base_unit(Quantity.TEMPERATURE) == "C"
        assert base_unit(Quantity.SPEED) == "kmh"
        assert base_unit(Quantity.ROTATIONAL_SPEED) == "rpm"
        assert base_unit(Quantity.RATIO) == "percent"
        assert base_unit(Quantity.VOLTAGE) == "V"

    def test_base_units_have_identity_transform(self):
        for quantity, unit_name in BASE_UNITS.items():
            unit = UNITS[unit_name]
            assert unit.quantity is quantity
            assert (unit.scale, unit.offset) == (1.0, 0.0)
