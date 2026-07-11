"""Channel registry tests: code must match docs/PROTOCOLS.md exactly."""

from pathlib import Path

import pytest

from pigauge.core.channels import CHANNELS, Quantity, UnknownChannelError, get_channel

REPO_ROOT = Path(__file__).parent.parent
PROTOCOLS_DOC = REPO_ROOT / "docs" / "PROTOCOLS.md"

DOC_QUANTITY_NAMES = {
    "rotational speed": Quantity.ROTATIONAL_SPEED,
    "speed": Quantity.SPEED,
    "temperature": Quantity.TEMPERATURE,
    "ratio": Quantity.RATIO,
    "pressure (abs)": Quantity.PRESSURE,
    "pressure (gauge)": Quantity.PRESSURE,
    "voltage": Quantity.VOLTAGE,
    "boolean": Quantity.BOOLEAN,
}

DOC_BASE_UNIT_NAMES = {
    "RPM": "rpm",
    "km/h": "kmh",
    "°C": "C",
    "%": "percent",
    "kPa": "kPa",
    "V": "V",
    "—": "bool",
}


def parse_doc_table() -> dict[str, tuple[Quantity, str, float]]:
    """Extract (quantity, base unit, stale_after) per channel from PROTOCOLS.md."""
    text = PROTOCOLS_DOC.read_text(encoding="utf-8")
    section = text.split("## Canonical channels", 1)[1].split("\n## ", 1)[0]
    rows = {}
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or stripped.startswith("|--"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if cells[0] in ("Channel ID", "---"):
            continue
        channel_id, quantity_name, unit_name, _source, stale_text = cells
        rows[channel_id] = (
            DOC_QUANTITY_NAMES[quantity_name],
            DOC_BASE_UNIT_NAMES[unit_name],
            float(stale_text.split()[0]),
        )
    return rows


def test_registry_matches_protocols_doc_exactly():
    doc_rows = parse_doc_table()
    assert doc_rows, "failed to parse any rows from PROTOCOLS.md"
    assert set(CHANNELS) == set(doc_rows)
    for channel_id, (quantity, unit_name, stale_after) in doc_rows.items():
        channel = CHANNELS[channel_id]
        assert channel.quantity is quantity, channel_id
        assert channel.base_unit == unit_name, channel_id
        assert channel.stale_after == stale_after, channel_id


def test_get_channel_returns_registry_entry():
    channel = get_channel("engine.rpm")
    assert channel.quantity is Quantity.ROTATIONAL_SPEED
    assert channel.stale_after == 0.5


def test_get_channel_unknown_id_raises():
    with pytest.raises(UnknownChannelError, match="warp.speed"):
        get_channel("warp.speed")


def test_channel_ids_use_dotted_lowercase_convention():
    for channel_id in CHANNELS:
        assert channel_id == channel_id.lower()
        assert "." in channel_id
