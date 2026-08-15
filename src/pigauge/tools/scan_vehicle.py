"""Scan a vehicle's OBD2 port and report what it actually supports.

Connects over CAN or an ELM327 adapter, works out the transport details,
walks the mode 01 and mode 09 supported-PID bitmasks, and prints a report
plus a starting ``channels:`` block for a vehicle profile.

This tool *discovers*; it never writes config. The profile snippet is
printed for a human to review and paste, because a scan cannot tell you
what poll rate a vehicle sustains in traffic — only that a PID answered
once, parked, with the engine idling.

    python -m pigauge.tools.scan_vehicle --transport elm327 --port /dev/ttyUSB0
    python -m pigauge.tools.scan_vehicle --transport can --interface can0
"""

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pigauge.core.config.errors import ConfigError
from pigauge.core.config.loader import load_vehicle_profile
from pigauge.core.config.models import CanProfileConfig, Elm327ProfileConfig
from pigauge.sources.can_socketcan import CanTransport
from pigauge.sources.elm327 import DEFAULT_BAUDRATE, DEFAULT_PORT, Elm327Transport
from pigauge.sources.obd_pids import (
    MODE_CURRENT_DATA,
    MODE_VEHICLE_INFO,
    PID_DECODERS,
    PIDS_PER_BITMASK,
    RESPONSE_MODE_OFFSET,
    SUPPORT_QUERY_PIDS,
    decode_supported_pids,
)
from pigauge.sources.obd_transport import ObdTransportError

DEFAULT_CAN_INTERFACE = "can0"
GENERIC_PROFILE = "config/vehicles/generic_obd2.yaml"
"""Poll rates for the printed snippet come from here, not from the scan:
a scan proves a PID answers, never how fast it answers in traffic."""

SUPPORT_HEADER_BYTES = 2
"""A bitmask response is ``<mode+0x40> <query pid>`` then the mask."""

CAN_CANDIDATES = (
    ("CAN 11-bit (0x7DF/0x7E8-0x7EF)", CanProfileConfig(
        request_id=0x7DF, response_ids=[0x7E8, 0x7E9, 0x7EA, 0x7EB, 0x7EC, 0x7ED, 0x7EE, 0x7EF]
    )),
    ("CAN 29-bit (0x18DB33F1/0x18DAF110)", CanProfileConfig(
        request_id=0x18DB33F1, response_ids=[0x18DAF110]
    )),
)
"""ID schemes tried in order (docs/PROTOCOLS.md §CAN transport)."""

BITRATE_NOTE = (
    "socketcan bitrate is set when the interface comes up, not by this tool: "
    "if nothing answers, re-run after `sudo ip link set can0 down && "
    "sudo ip link set can0 up type can bitrate 250000`."
)


@dataclass
class ScanReport:
    """What one scan found; render it, do not act on it."""

    transport: str
    link: str
    protocol: str | None = None
    supported_pids: list[int] = field(default_factory=list)
    mode09_pids: list[int] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def decodable(self) -> dict[str, int]:
        """Supported PIDs PiGauge can decode, as ``{channel: pid}``."""
        return {
            PID_DECODERS[pid].channel_id: pid
            for pid in self.supported_pids
            if pid in PID_DECODERS
        }

    @property
    def undecodable(self) -> list[int]:
        """Supported PIDs with no entry in the standard decode table."""
        return [pid for pid in self.supported_pids if pid not in PID_DECODERS]

    def render(self) -> str:
        """Human-readable scan report."""
        lines = [
            "PiGauge vehicle scan",
            "====================",
            f"Transport      : {self.transport}",
            f"Link           : {self.link}",
            f"Protocol       : {self.protocol or 'not reported by this transport'}",
            "",
            f"Mode 01 PIDs supported ({len(self.supported_pids)}):",
            f"  {self._hex_list(self.supported_pids) or '(none answered)'}",
            "",
            f"Mode 09 PIDs supported ({len(self.mode09_pids)}):",
            f"  {self._hex_list(self.mode09_pids) or '(none answered)'}",
            "",
            "Channels PiGauge can decode from this vehicle:",
        ]
        lines.extend(
            f"  {channel:<22} PID 0x{pid:02X}" for channel, pid in sorted(self.decodable.items())
        )
        if not self.decodable:
            lines.append("  (none)")
        if self.undecodable:
            lines += [
                "",
                "Supported but not decoded by PiGauge (Phase 9 candidates):",
                f"  {self._hex_list(self.undecodable)}",
            ]
        if self.notes:
            lines += ["", "Notes:", *(f"  - {note}" for note in self.notes)]
        return "\n".join(lines)

    def profile_snippet(self, rates: dict[str, float] | None = None) -> str:
        """A ``channels:`` block to review and paste into a vehicle profile."""
        rates = rates or {}
        lines = [
            "# Reviewed starting point - NOT a finished profile.",
            "# Poll rates below are the generic defaults; confirm each one is",
            "# actually sustained on the vehicle before trusting a gauge.",
            "channels:",
        ]
        for channel, pid in sorted(self.decodable.items()):
            rate = rates.get(channel)
            suffix = "" if rate is not None else "  # TODO: set rate_hz from a road test"
            lines.append(
                f"  {channel + ':':<22} {{pid: 0x{pid:02X}, rate_hz: {rate or 1}}}{suffix}"
            )
        return "\n".join(lines)

    @staticmethod
    def _hex_list(pids: list[int]) -> str:
        """Format PIDs as a comma-separated hex list."""
        return ", ".join(f"0x{pid:02X}" for pid in pids)


def enumerate_supported(transport: Any, mode: int) -> list[int]:
    """Walk a mode's supported-PID bitmasks (0x00 -> 0x20 -> 0x40)."""
    supported: list[int] = []
    for query_pid in SUPPORT_QUERY_PIDS:
        payload = transport.query(mode, query_pid)
        if not _is_support_response(payload, mode, query_pid):
            break
        advertised = decode_supported_pids(query_pid, payload[SUPPORT_HEADER_BYTES:])
        supported.extend(pid for pid in advertised if pid not in SUPPORT_QUERY_PIDS)
        if query_pid + PIDS_PER_BITMASK not in advertised:
            break  # no continuation bit: this was the last bank
    return sorted(set(supported))


def _is_support_response(payload: bytes, mode: int, query_pid: int) -> bool:
    """Is this a positive bitmask response for the bank we asked about?"""
    return (
        len(payload) >= SUPPORT_HEADER_BYTES + 4
        and payload[0] == mode + RESPONSE_MODE_OFFSET
        and payload[1] == query_pid
    )


def scan_transport(transport: Any, name: str, link: str) -> ScanReport:
    """Enumerate everything an already-connected transport can tell us."""
    report = ScanReport(transport=name, link=link, protocol=getattr(transport, "protocol", None))
    report.supported_pids = enumerate_supported(transport, MODE_CURRENT_DATA)
    report.mode09_pids = enumerate_supported(transport, MODE_VEHICLE_INFO)
    if not report.supported_pids:
        report.notes.append("no PID answered: check ignition on, adapter seated, protocol")
    return report


def detect_can_link(interface: str, **transport_options: Any) -> tuple[Any, str]:
    """Try each CAN ID scheme in turn; return the first that answers.

    Raises :class:`ObdTransportError` if none does, since a vehicle that
    answers nothing cannot be scanned.
    """
    attempted = []
    for description, candidate in CAN_CANDIDATES:
        transport = CanTransport(candidate, interface=interface, **transport_options)
        transport.connect()
        if transport.query(MODE_CURRENT_DATA, SUPPORT_QUERY_PIDS[0]):
            return transport, f"{interface}, {description}"
        transport.close()
        attempted.append(description)
    raise ObdTransportError(
        f"no response on {interface} from any ID scheme ({', '.join(attempted)}). {BITRATE_NOTE}"
    )


def build_parser() -> argparse.ArgumentParser:
    """Command-line interface for the scan tool."""
    parser = argparse.ArgumentParser(
        prog="scan_vehicle", description="Scan a vehicle's OBD2 port and report support"
    )
    parser.add_argument("--transport", choices=("can", "elm327"), required=True)
    parser.add_argument("--interface", default=DEFAULT_CAN_INTERFACE, help="socketcan interface")
    parser.add_argument("--port", default=DEFAULT_PORT, help="ELM327 serial port")
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("--out", type=Path, default=None, help="also write the report here")
    parser.add_argument(
        "--rates-from",
        type=Path,
        default=Path(GENERIC_PROFILE),
        help="profile whose poll rates seed the printed snippet",
    )
    return parser


def load_rates(path: Path) -> dict[str, float]:
    """Read per-channel poll rates from a profile, or {} if unreadable."""
    try:
        return {
            channel_id: poll.rate_hz
            for channel_id, poll in load_vehicle_profile(path).channels.items()
        }
    except (ConfigError, OSError):
        return {}


def main(argv: list[str] | None = None) -> int:
    """Scan the vehicle and print the report; returns the exit code."""
    args = build_parser().parse_args(argv)
    try:
        transport, link = _open_transport(args)
    except ObdTransportError as error:
        print(f"scan failed: {error}", file=sys.stderr)
        return 1
    try:
        report = scan_transport(transport, args.transport, link)
    except ObdTransportError as error:
        print(f"scan failed mid-enumeration: {error}", file=sys.stderr)
        return 1
    finally:
        transport.close()

    snippet = report.profile_snippet(rates=load_rates(args.rates_from))
    rendered = f"{report.render()}\n\n{snippet}\n"
    print(rendered)
    if args.out is not None:
        args.out.write_text(rendered, encoding="utf-8")
        print(f"report written to {args.out}")
    return 0


def _open_transport(args: argparse.Namespace) -> tuple[Any, str]:
    """Open the requested transport, detecting the CAN ID scheme."""
    if args.transport == "can":
        return detect_can_link(args.interface)
    transport = Elm327Transport(Elm327ProfileConfig(), port=args.port, baudrate=args.baudrate)
    transport.connect()
    return transport, f"{args.port} @ {args.baudrate}"


if __name__ == "__main__":
    sys.exit(main())
