"""ELM327/STN serial OBD2 transport.

Implements the init and polling sequence in docs/PROTOCOLS.md: ``ATZ ATE0
ATL0 ATS0 ATH1 ATSP0`` then ``0100`` to force protocol negotiation, after
which PIDs are polled as plain hex (``010C``). With ``batch_pids: true``
in the vehicle profile, several PIDs ride in one request (``010C0D05``) —
a CAN-only feature that the profile, not this module, enables.

Response parsing is deliberately header-format-agnostic. ``ATS0`` strips
spaces and ``ATH1`` leaves headers on, and header width varies by
protocol (3 hex chars for 11-bit CAN, more for 29-bit and K-line), so
rather than guessing a width this module locates the ``41 <pid>``
response marker inside the frame. Multi-line replies are reassembled as
ISO-TP when they start with a first frame (11-bit CAN, the common case);
otherwise each line is treated as an independent ECU's answer.

pyserial is an optional extra (``pip install 'pigauge[vehicle]'``); the
module always imports and only needs it to open a real port.
"""

import logging
from collections.abc import Callable, Sequence
from typing import Any

from pigauge.core.config.models import Elm327ProfileConfig, VehicleProfile
from pigauge.core.databus import DataBus
from pigauge.sources.obd_pids import MODE_CURRENT_DATA, RESPONSE_MODE_OFFSET, parse_mode01_payload
from pigauge.sources.obd_profile import build_poll_plan
from pigauge.sources.obd_source import ObdSource
from pigauge.sources.obd_transport import ObdTransportError

try:  # vehicle-only dependency (pip install 'pigauge[vehicle]')
    import serial
except ImportError:  # pragma: no cover - exercised by the guarded-import test
    serial = None

logger = logging.getLogger(__name__)

DEFAULT_PORT = "/dev/ttyUSB0"
DEFAULT_BAUDRATE = 38400
DEFAULT_TIMEOUT_S = 1.0

INIT_COMMANDS = ("ATZ", "ATE0", "ATL0", "ATS0", "ATH1", "ATSP0")
"""Adapter init per docs/PROTOCOLS.md: reset, echo/linefeed/space off,
headers on, protocol auto."""

PROTOCOL_PROBE = "0100"
"""Sent after init to make the adapter negotiate a protocol."""

PROTOCOL_QUERY = "ATDP"
COMMAND_TERMINATOR = "\r"
PROMPT = ">"
MAX_BATCH_PIDS = 6
"""ELM327 accepts at most six PIDs in one mode 01 request."""

MAX_RESPONSE_BYTES = 4096
CAN_11BIT_HEADER_CHARS = 3
FIRST_FRAME_TYPE = 0x10
CONSECUTIVE_FRAME_TYPE = 0x20
PCI_TYPE_MASK = 0xF0
PCI_LENGTH_MASK = 0x0F
BYTE_SHIFT = 8

CONNECT_FAILURES = ("UNABLE TO CONNECT", "BUS INIT: ERROR", "BUS ERROR", "CAN ERROR")
"""Replies meaning the adapter could not reach the ECU (retry with backoff)."""

NO_DATA_REPLIES = ("NO DATA", "STOPPED", "?", "ERROR", "BUFFER FULL", "DATA ERROR")
"""Replies meaning 'no answer this time' — the channel simply goes STALE."""

NOISE_REPLIES = ("SEARCHING...", "SEARCHING", "OK")
"""Informational lines that precede or replace real data."""

INSTALL_HINT = (
    "pyserial is not installed - install vehicle extras: pip install 'pigauge[vehicle]'"
)


def frame_bytes(line: str) -> bytes:
    """Convert one response line to frame bytes, dropping an 11-bit header.

    With ``ATS0`` the line is unspaced hex. An odd number of hex digits can
    only mean a 3-character 11-bit CAN header (``7E8...``), so that width
    is stripped; anything else is left for :func:`extract_pdu` to skip.
    """
    compact = "".join(line.split())
    if len(compact) % 2 == 1:
        compact = compact[CAN_11BIT_HEADER_CHARS:]
    try:
        return bytes.fromhex(compact)
    except ValueError:
        return b""


def extract_pdu(frame: bytes, response_mode: int, pids: Sequence[int]) -> bytes:
    """Locate the response PDU inside a frame, skipping header and PCI bytes."""
    wanted = set(pids)
    for index in range(len(frame) - 1):
        if frame[index] == response_mode and (not wanted or frame[index + 1] in wanted):
            return frame[index:]
    return b""


def reassemble_isotp(frames: Sequence[bytes]) -> bytes:
    """Rebuild a multi-frame PDU from an ISO-TP first + consecutive frames."""
    if not frames or len(frames[0]) < 2:
        return b""
    first = frames[0]
    if first[0] & PCI_TYPE_MASK != FIRST_FRAME_TYPE:
        return b""
    declared = ((first[0] & PCI_LENGTH_MASK) << BYTE_SHIFT) | first[1]
    payload = bytearray(first[2:])
    for frame in frames[1:]:
        if frame and frame[0] & PCI_TYPE_MASK == CONSECUTIVE_FRAME_TYPE:
            payload += frame[1:]
    return bytes(payload[:declared])


class Elm327Transport:
    """One ELM327/STN serial link, driven by :class:`ObdSource`."""

    name = "elm327"

    def __init__(
        self,
        profile_elm327: Elm327ProfileConfig | None = None,
        *,
        port: str = DEFAULT_PORT,
        baudrate: int = DEFAULT_BAUDRATE,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        serial_port: Any = None,
        serial_factory: Callable[..., Any] | None = None,
    ) -> None:
        """Configure the link; ``batch_pids`` comes from the vehicle profile."""
        settings = profile_elm327 or Elm327ProfileConfig()
        self._port = port
        self._baudrate = baudrate
        self._timeout_s = timeout_s
        self._serial = serial_port
        self._injected = serial_port is not None
        self._serial_factory = serial_factory
        self.max_pids_per_request = MAX_BATCH_PIDS if settings.batch_pids else 1
        self.protocol: str | None = None
        """Protocol the adapter negotiated, as reported by ATDP."""
        if serial is None and not self._injected and serial_factory is None:
            raise RuntimeError(INSTALL_HINT)

    def connect(self) -> None:
        """Open the port and run the documented init sequence."""
        if self._serial is None:
            self._serial = self._open_port()
        for command in INIT_COMMANDS:
            self._command(command)
        probe = self._command(PROTOCOL_PROBE)
        if self._is_connect_failure(probe):
            raise ObdTransportError(f"adapter could not reach the ECU: {probe.strip()}")
        self.protocol = self._read_protocol()

    def request(self, pids: Sequence[int]) -> dict[int, bytes]:
        """Query mode 01 PIDs (batched when the profile allows it)."""
        payload = self.query(MODE_CURRENT_DATA, *pids)
        return parse_mode01_payload(payload)

    def query(self, mode: int, *pids: int) -> bytes:
        """Send one request and return its response PDU (b'' if unanswered)."""
        command = f"{mode:02X}" + "".join(f"{pid:02X}" for pid in pids)
        reply = self._command(command)
        if self._is_connect_failure(reply):
            raise ObdTransportError(f"link lost: {reply.strip()}")
        return self._parse_reply(reply, mode + RESPONSE_MODE_OFFSET, pids)

    def close(self) -> None:
        """Release the serial port unless it was injected by a caller."""
        if self._serial is None or self._injected:
            return
        try:
            self._serial.close()
        except Exception:  # pragma: no cover - closing an already-dead port
            logger.debug("closing %s failed", self._port)
        finally:
            self._serial = None

    def _open_port(self) -> Any:
        """Open the serial device, mapping driver errors to transport errors."""
        factory = self._serial_factory or (serial.Serial if serial is not None else None)
        if factory is None:  # pragma: no cover - guarded at construction
            raise ObdTransportError(INSTALL_HINT)
        try:
            return factory(port=self._port, baudrate=self._baudrate, timeout=self._timeout_s)
        except Exception as error:
            raise ObdTransportError(f"cannot open {self._port}: {error}") from error

    def _read_protocol(self) -> str | None:
        """Ask the adapter which protocol it settled on (ATDP)."""
        reply = self._command(PROTOCOL_QUERY)
        for line in self._data_lines(reply):
            return line
        return None

    def _command(self, command: str) -> str:
        """Write one command and read the reply up to the ELM327 prompt."""
        if self._serial is None:
            raise ObdTransportError("serial port is not open")
        try:
            self._serial.write((command + COMMAND_TERMINATOR).encode("ascii"))
            return self._read_until_prompt()
        except ObdTransportError:
            raise
        except Exception as error:
            raise ObdTransportError(f"{self._port} failed on {command}: {error}") from error

    def _read_until_prompt(self) -> str:
        """Read bytes until the '>' prompt; a silent adapter is a link fault."""
        buffer = bytearray()
        while len(buffer) < MAX_RESPONSE_BYTES:
            chunk = self._serial.read(1)
            if not chunk:  # read timeout: the adapter never returned a prompt
                raise ObdTransportError(f"{self._port} timed out waiting for prompt")
            if chunk == PROMPT.encode("ascii"):
                return buffer.decode("ascii", errors="replace")
            buffer += chunk
        raise ObdTransportError(f"{self._port} sent {MAX_RESPONSE_BYTES} bytes without a prompt")

    def _parse_reply(self, reply: str, response_mode: int, pids: Sequence[int]) -> bytes:
        """Turn an adapter reply into a response PDU."""
        lines = self._data_lines(reply)
        if not lines:
            return b""
        frames = [frame_bytes(line) for line in lines]
        if len(frames) > 1:
            payload = reassemble_isotp(frames)
            if payload:
                return payload  # already starts at the response mode byte
        for frame in frames:
            pdu = extract_pdu(frame, response_mode, pids)
            if pdu:
                return pdu
        return b""

    @staticmethod
    def _data_lines(reply: str) -> list[str]:
        """Strip prompts, blank lines, and the adapter's chatter."""
        lines = []
        for raw in reply.replace("\r", "\n").split("\n"):
            line = raw.strip()
            if not line or line in NOISE_REPLIES or line in NO_DATA_REPLIES:
                continue
            lines.append(line)
        return lines

    @staticmethod
    def _is_connect_failure(reply: str) -> bool:
        """Does this reply mean the adapter cannot reach the ECU?"""
        upper = reply.upper()
        return any(failure in upper for failure in CONNECT_FAILURES)


def create_elm327_source(
    bus: DataBus,
    profile: VehicleProfile,
    *,
    port: str = DEFAULT_PORT,
    baudrate: int = DEFAULT_BAUDRATE,
    profile_source: str = "<vehicle profile>",
    serial_port: Any = None,
    clock: Callable[[], float] | None = None,
    **transport_options: Any,
) -> ObdSource:
    """Build an ELM327-backed :class:`ObdSource` from a vehicle profile.

    ``clock`` overrides the source's poll-schedule clock (tests only).
    """
    transport = Elm327Transport(
        profile.elm327,
        port=port,
        baudrate=baudrate,
        serial_port=serial_port,
        **transport_options,
    )
    plan = build_poll_plan(profile, profile_source)
    source_options = {} if clock is None else {"clock": clock}
    return ObdSource(bus, transport, plan, **source_options)
