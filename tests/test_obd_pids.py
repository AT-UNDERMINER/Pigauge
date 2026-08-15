"""Standard mode 01 decode table: parity with docs/PROTOCOLS.md and decoding."""

import re

import pytest

from pigauge.core.channels import CHANNELS
from pigauge.sources.obd_pids import (
    PID_DECODERS,
    SUPPORT_QUERY_PIDS,
    UnknownPidError,
    decode_supported_pids,
    decoder_for_pid,
    parse_mode01_payload,
)

PROTOCOLS_MD = "docs/PROTOCOLS.md"
DECODE_TABLE_HEADING = "## Standard OBD2 (mode 01) decode formulas"
TABLE_ROW = re.compile(r"^\|\s*0x([0-9A-Fa-f]{2})\s*\|\s*([\w.]+)\s*\|\s*(.+?)\s*\|$")


def normalise_formula(formula: str) -> str:
    """Compare formulas without tripping over typography or unit notes."""
    ascii_formula = formula.replace("×", "*").replace("−", "-")
    without_note = ascii_formula.split("(kPa)")[0]
    return without_note.replace(" ", "").rstrip()


def documented_decoders() -> dict[int, tuple[str, str]]:
    """Parse the decode table from docs/PROTOCOLS.md into {pid: (channel, formula)}."""
    with open(PROTOCOLS_MD, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    start = lines.index(DECODE_TABLE_HEADING)
    documented = {}
    for line in lines[start:]:
        if line.startswith("## ") and not line.startswith(DECODE_TABLE_HEADING):
            break
        match = TABLE_ROW.match(line)
        if match:
            pid_hex, channel_id, formula = match.groups()
            documented[int(pid_hex, 16)] = (channel_id, normalise_formula(formula))
    return documented


class TestProtocolsParity:
    """docs/PROTOCOLS.md is the spec; the table must not drift from it."""

    def test_table_was_parsed(self):
        assert len(documented_decoders()) >= 10

    def test_same_pid_set(self):
        assert set(PID_DECODERS) == set(documented_decoders())

    def test_same_channel_and_formula_per_pid(self):
        for pid, (channel_id, formula) in documented_decoders().items():
            decoder = PID_DECODERS[pid]
            assert decoder.channel_id == channel_id, f"PID 0x{pid:02X} channel"
            assert normalise_formula(decoder.formula) == formula, f"PID 0x{pid:02X} formula"

    def test_every_decoded_channel_is_canonical(self):
        for decoder in PID_DECODERS.values():
            assert decoder.channel_id in CHANNELS

    def test_one_pid_per_channel(self):
        channels = [decoder.channel_id for decoder in PID_DECODERS.values()]
        assert len(channels) == len(set(channels))


class TestDecodeFormulas:
    @pytest.mark.parametrize(("pid", "data", "expected"), [
        (0x04, b"\x7f", 49.8039),          # load 127 -> 49.8 %
        (0x05, b"\x5a", 50.0),             # coolant 90 -> 50 C
        (0x0B, b"\x64", 100.0),            # MAP 100 kPa absolute
        (0x0C, b"\x1a\xf8", 1726.0),       # (256*26+248)/4
        (0x0D, b"\x50", 80.0),             # 80 km/h
        (0x0F, b"\x3c", 20.0),             # intake 60 -> 20 C
        (0x11, b"\xff", 100.0),            # throttle wide open
        (0x2F, b"\x80", 50.1961),          # fuel level
        (0x33, b"\x62", 98.0),             # baro 98 kPa
        (0x42, b"\x37\x28", 14.12),        # (256*55+40)/1000 V
    ])
    def test_documented_examples(self, pid, data, expected):
        assert decoder_for_pid(pid).decode(data) == pytest.approx(expected, abs=1e-4)

    def test_temperature_can_go_negative(self):
        assert decoder_for_pid(0x05).decode(b"\x00") == -40.0

    def test_extra_bytes_are_ignored(self):
        assert decoder_for_pid(0x0D).decode(b"\x50\xff\xff") == 80.0

    def test_missing_bytes_rejected(self):
        with pytest.raises(ValueError, match="needs 2 data byte"):
            decoder_for_pid(0x0C).decode(b"\x1a")

    def test_unknown_pid_names_itself(self):
        with pytest.raises(UnknownPidError, match="0x99"):
            decoder_for_pid(0x99)


class TestSupportedPidBitmask:
    def test_high_bit_is_the_next_pid(self):
        assert decode_supported_pids(0x00, b"\x80\x00\x00\x00") == [0x01]

    def test_low_bit_is_the_query_boundary(self):
        assert decode_supported_pids(0x00, b"\x00\x00\x00\x01") == [0x20]

    def test_second_bank_offsets_from_its_query(self):
        assert decode_supported_pids(0x20, b"\x80\x00\x00\x00") == [0x21]

    def test_realistic_mask(self):
        # BE1FA813: the mask a typical CAN ECU returns for 0x00
        supported = decode_supported_pids(0x00, b"\xbe\x1f\xa8\x13")
        assert 0x0C in supported and 0x0D in supported and 0x05 in supported
        assert 0x02 not in supported

    def test_all_bits_set(self):
        assert decode_supported_pids(0x40, b"\xff\xff\xff\xff") == list(range(0x41, 0x61))

    def test_non_query_pid_rejected(self):
        with pytest.raises(ValueError, match="not a supported-PID query"):
            decode_supported_pids(0x0C, b"\x00\x00\x00\x00")

    def test_short_response_rejected(self):
        with pytest.raises(ValueError, match="needs 4 bytes"):
            decode_supported_pids(0x00, b"\x80\x00")

    def test_query_pids_are_the_documented_three(self):
        assert SUPPORT_QUERY_PIDS == (0x00, 0x20, 0x40)


class TestParsePayload:
    def test_single_pid(self):
        assert parse_mode01_payload(b"\x41\x0c\x1a\xf8") == {0x0C: b"\x1a\xf8"}

    def test_batched_pids_split_by_table_lengths(self):
        payload = b"\x41\x0c\x1a\xf8\x0d\x32\x05\x5a"
        assert parse_mode01_payload(payload) == {
            0x0C: b"\x1a\xf8",
            0x0D: b"\x32",
            0x05: b"\x5a",
        }

    def test_unknown_pid_stops_parsing_but_keeps_earlier_values(self):
        payload = b"\x41\x0c\x1a\xf8\x99\x00\x00"
        assert parse_mode01_payload(payload) == {0x0C: b"\x1a\xf8"}

    def test_truncated_trailing_pid_dropped(self):
        assert parse_mode01_payload(b"\x41\x0d\x32\x0c\x1a") == {0x0D: b"\x32"}

    def test_wrong_response_mode_ignored(self):
        assert parse_mode01_payload(b"\x7f\x01\x12") == {}

    def test_empty_payload(self):
        assert parse_mode01_payload(b"") == {}
