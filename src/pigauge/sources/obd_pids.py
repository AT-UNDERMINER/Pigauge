"""Standard OBD2 mode 01 decode table and response parsing.

This module owns the *protocol* knowledge shared by every vehicle
transport: how a mode 01 PID's data bytes become a base-unit value, and
how a response payload is split back into PIDs. It must match the decode
table in docs/PROTOCOLS.md exactly — the test suite parses that table and
fails on any drift, the same contract core/channels.py has.

What lives here is the standard, vehicle-independent mapping. Which PIDs
a given vehicle actually polls, and how often, comes from the vehicle
profile YAML (see :mod:`pigauge.sources.obd_profile`) — no source ever
hard-codes a PID list.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

MODE_CURRENT_DATA = 0x01
MODE_VEHICLE_INFO = 0x09
RESPONSE_MODE_OFFSET = 0x40
"""A positive response echoes the request mode plus this offset (01 -> 41)."""

NEGATIVE_RESPONSE_BYTE = 0x7F
SUPPORT_QUERY_PIDS = (0x00, 0x20, 0x40)
"""PIDs whose response is a bitmask of the next 32 supported PIDs."""

SUPPORT_BITMASK_BYTES = 4
BITS_PER_BYTE = 8
PIDS_PER_BITMASK = SUPPORT_BITMASK_BYTES * BITS_PER_BYTE

RATIO_SCALE = 100 / 255
"""Single-byte ratio PIDs report 0-255 across 0-100 %."""

TEMPERATURE_OFFSET_C = 40
"""Single-byte temperature PIDs are offset so -40 C encodes as 0."""

RPM_PER_COUNT = 0.25
MILLIVOLTS_PER_VOLT = 1000


class UnknownPidError(KeyError):
    """A PID with no entry in the standard mode 01 decode table."""

    def __init__(self, pid: int) -> None:
        """Record the offending PID with a pointer to the decode table."""
        super().__init__(
            f"unknown mode 01 PID 0x{pid:02X} "
            "(see pigauge.sources.obd_pids.PID_DECODERS / docs/PROTOCOLS.md)"
        )
        self.pid = pid


def _word(data: bytes) -> int:
    """Combine the first two data bytes as 256A + B."""
    return (data[0] << BITS_PER_BYTE) | data[1]


def _ratio_percent(data: bytes) -> float:
    """A x 100/255 — single-byte percentage PIDs."""
    return data[0] * RATIO_SCALE


def _temperature_c(data: bytes) -> float:
    """A - 40 — single-byte temperature PIDs."""
    return float(data[0] - TEMPERATURE_OFFSET_C)


def _byte_value(data: bytes) -> float:
    """A — PIDs whose raw byte is already the base unit (kPa, km/h)."""
    return float(data[0])


def _rpm(data: bytes) -> float:
    """(256A + B)/4 — engine speed in RPM."""
    return _word(data) * RPM_PER_COUNT


def _volts(data: bytes) -> float:
    """(256A + B)/1000 — control module voltage in V."""
    return _word(data) / MILLIVOLTS_PER_VOLT


@dataclass(frozen=True)
class PidDecoder:
    """How one standard mode 01 PID maps onto a canonical channel."""

    pid: int
    channel_id: str
    data_bytes: int
    formula: str
    """Human-readable formula, kept identical to docs/PROTOCOLS.md."""
    function: Callable[[bytes], float]

    def decode(self, data: bytes) -> float:
        """Decode this PID's data bytes into the channel's base unit."""
        if len(data) < self.data_bytes:
            raise ValueError(
                f"PID 0x{self.pid:02X} needs {self.data_bytes} data byte(s), got {len(data)}"
            )
        return self.function(data)


PID_DECODERS: dict[int, PidDecoder] = {
    decoder.pid: decoder
    for decoder in (
        PidDecoder(0x04, "engine.load", 1, "A*100/255", _ratio_percent),
        PidDecoder(0x05, "engine.coolant_temp", 1, "A-40", _temperature_c),
        PidDecoder(0x0B, "engine.map", 1, "A", _byte_value),
        PidDecoder(0x0C, "engine.rpm", 2, "(256A+B)/4", _rpm),
        PidDecoder(0x0D, "vehicle.speed", 1, "A", _byte_value),
        PidDecoder(0x0F, "engine.intake_temp", 1, "A-40", _temperature_c),
        PidDecoder(0x11, "engine.throttle", 1, "A*100/255", _ratio_percent),
        PidDecoder(0x2F, "fuel.level", 1, "A*100/255", _ratio_percent),
        PidDecoder(0x33, "ambient.baro", 1, "A", _byte_value),
        PidDecoder(0x42, "electrical.battery_v", 2, "(256A+B)/1000", _volts),
    )
}

CHANNEL_PIDS: dict[str, int] = {
    decoder.channel_id: decoder.pid for decoder in PID_DECODERS.values()
}


def decoder_for_pid(pid: int) -> PidDecoder:
    """Look up a PID, raising :class:`UnknownPidError` if it is not standard."""
    try:
        return PID_DECODERS[pid]
    except KeyError:
        raise UnknownPidError(pid) from None


def decode_supported_pids(query_pid: int, data: bytes) -> list[int]:
    """Expand a supported-PID bitmask response into the PIDs it advertises.

    ``query_pid`` is one of :data:`SUPPORT_QUERY_PIDS`; the four data bytes
    are a big-endian bitmask where the most significant bit is
    ``query_pid + 1``. Used by tools/scan_vehicle.py.
    """
    if query_pid not in SUPPORT_QUERY_PIDS:
        raise ValueError(
            f"0x{query_pid:02X} is not a supported-PID query (expected {SUPPORT_QUERY_PIDS})"
        )
    if len(data) < SUPPORT_BITMASK_BYTES:
        raise ValueError(
            f"supported-PID response needs {SUPPORT_BITMASK_BYTES} bytes, got {len(data)}"
        )
    bitmask = int.from_bytes(data[:SUPPORT_BITMASK_BYTES], "big")
    return [
        query_pid + offset
        for offset in range(1, PIDS_PER_BITMASK + 1)
        if bitmask >> (PIDS_PER_BITMASK - offset) & 1
    ]


def parse_mode01_payload(payload: bytes) -> dict[int, bytes]:
    """Split a mode 01 positive response into ``{pid: data bytes}``.

    ``payload`` starts at the ``41`` response-mode byte and may carry
    several PIDs back to back (ELM327 batched requests). Each PID's length
    comes from the decode table, so parsing stops at the first unknown PID
    — its length is unknowable and everything after it would be
    misaligned. Whatever was parsed before that point is still returned.
    """
    if not payload or payload[0] != MODE_CURRENT_DATA + RESPONSE_MODE_OFFSET:
        return {}
    values: dict[int, bytes] = {}
    offset = 1
    while offset < len(payload):
        pid = payload[offset]
        decoder = PID_DECODERS.get(pid)
        if decoder is None:
            logger.debug("stopping payload parse at unknown PID 0x%02X", pid)
            break
        start = offset + 1
        end = start + decoder.data_bytes
        if end > len(payload):
            logger.debug("truncated data for PID 0x%02X", pid)
            break
        values[pid] = payload[start:end]
        offset = end
    return values
