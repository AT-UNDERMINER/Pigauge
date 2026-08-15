"""FakeELM327: a serial-level emulator of an ELM327 adapter.

Implements the slice of pyserial the transport uses (``write``, ``read``,
``close``) and the adapter behaviour that matters: command echo until
``ATE0``, ``OK`` acknowledgements, a ``SEARCHING...`` line on the first
protocol probe, ``ATS0``/``ATH1`` output formatting (unspaced hex with
headers), ISO-TP framing for batched replies, and ``NO DATA`` when the
ECU stays silent.

The vehicle data itself comes from :class:`fake_ecu.FakeEcu`, so this
emulator and the CAN fake answer from one shared source of truth.
"""

from fake_ecu import FakeEcu, isotp_frames

CAN_11BIT_HEADER = "7E8"
KLINE_HEADER = "486B10"
"""Even-width header (ISO 9141-2 style) for exercising header-agnostic parsing."""

PROMPT = ">"
LINE_END = "\r"
IDENTITY = "ELM327 v1.5"
DEFAULT_PROTOCOL = "AUTO, ISO 15765-4 (CAN 11/500)"
OK = "OK"
NO_DATA = "NO DATA"
UNABLE_TO_CONNECT = "UNABLE TO CONNECT"
SEARCHING = "SEARCHING..."
UNKNOWN_COMMAND = "?"

MODE_CURRENT_DATA = 0x01
MODE_VEHICLE_INFO = 0x09
HEX_CHARS_PER_BYTE = 2


class FakeELM327:
    """Serial-port stand-in that talks like an ELM327 adapter."""

    def __init__(
        self,
        ecu: FakeEcu | None = None,
        *,
        protocol: str = DEFAULT_PROTOCOL,
        header: str = CAN_11BIT_HEADER,
        unable_to_connect: bool = False,
        silent: bool = False,
        port: str = "/dev/ttyUSB0",
        baudrate: int = 38400,
        timeout: float = 1.0,
    ) -> None:
        """Emulate an adapter in front of ``ecu``; kwargs mirror serial.Serial."""
        self.ecu = ecu or FakeEcu()
        self.protocol = protocol
        self.header = header
        self.unable_to_connect = unable_to_connect
        self.silent = silent
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.is_open = True
        self.commands: list[str] = []
        self.echo = True  # real adapters echo until ATE0
        self.write_error: Exception | None = None
        self.read_error: Exception | None = None
        self.closes = 0
        self._searched = False
        self._input = bytearray()
        self._output = bytearray()

    def write(self, data: bytes) -> int:
        """Accept command bytes, answering once a carriage return arrives."""
        if self.write_error is not None:
            raise self.write_error
        if not self.is_open:
            raise OSError("port is closed")
        self._input += data
        while LINE_END.encode("ascii") in self._input:
            line, _, rest = self._input.partition(LINE_END.encode("ascii"))
            self._input = bytearray(rest)
            self._handle(line.decode("ascii", errors="replace").strip())
        return len(data)

    def read(self, size: int = 1) -> bytes:
        """Return buffered output, or b'' to emulate a read timeout."""
        if self.read_error is not None:
            raise self.read_error
        if not self._output:
            return b""
        chunk = bytes(self._output[:size])
        del self._output[:size]
        return chunk

    def close(self) -> None:
        """Close the emulated port."""
        self.closes += 1
        self.is_open = False

    def _handle(self, command: str) -> None:
        """Dispatch one command and queue the adapter's reply."""
        if not command:
            return
        self.commands.append(command)
        if self.silent:
            return  # wedged adapter: never sends a prompt
        lines = [command] if self.echo else []
        lines.extend(self._reply_for(command))
        self._queue(lines)

    def _reply_for(self, command: str) -> list[str]:
        """The adapter's answer lines for one command."""
        upper = command.upper()
        if upper.startswith("AT"):
            return self._reply_to_at(upper)
        if self.unable_to_connect:
            return [UNABLE_TO_CONNECT]
        return self._reply_to_obd(upper)

    def _reply_to_at(self, command: str) -> list[str]:
        """AT command handling, including the echo and protocol settings."""
        if command == "ATZ":
            self.echo = True
            self._searched = False
            return [IDENTITY]
        if command == "ATE0":
            self.echo = False
            return [OK]
        if command == "ATDP":
            return [self.protocol]
        if command in ("ATL0", "ATS0", "ATH1", "ATSP0"):
            return [OK]
        return [UNKNOWN_COMMAND]

    def _reply_to_obd(self, command: str) -> list[str]:
        """Answer a mode 01/09 request from the fake ECU."""
        try:
            request = bytes.fromhex(command)
        except ValueError:
            return [UNKNOWN_COMMAND]
        if len(request) < 2:
            return [UNKNOWN_COMMAND]
        prefix = []
        if not self._searched:
            self._searched = True
            prefix = [SEARCHING]  # first request after ATSP0 negotiates
        payload = self.ecu.respond(request[0], list(request[1:]))
        if payload is None:
            return [*prefix, NO_DATA]
        return prefix + [self.header + frame.hex().upper() for frame in isotp_frames(payload)]

    def _queue(self, lines: list[str]) -> None:
        """Serialise reply lines the way the adapter does, ending at the prompt."""
        text = "".join(f"{line}{LINE_END}" for line in lines) + PROMPT
        self._output += text.encode("ascii")
