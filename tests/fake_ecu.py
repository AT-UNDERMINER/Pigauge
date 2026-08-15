"""Fake OBD2 ECU: answers mode 01/09 requests at the PDU level.

One responder serves every vehicle-link test. :class:`FakeEcu` knows only
about PDUs (``01 0C`` in, ``41 0C 1A F8`` out), so the same instance backs
the in-process CAN bus fake, the vcan round-trip fixture, and the
FakeELM327 serial emulator — a bug in one transport's framing cannot be
masked by a differently-behaved stub in another.

Silence is meaningful: like a real ECU, an unsupported PID gets no
response at all rather than an error.
"""

import threading

from pigauge.sources.obd_pids import (
    MODE_CURRENT_DATA,
    MODE_VEHICLE_INFO,
    PIDS_PER_BITMASK,
    RESPONSE_MODE_OFFSET,
    SUPPORT_BITMASK_BYTES,
    SUPPORT_QUERY_PIDS,
)

OBD_REQUEST_ID = 0x7DF
OBD_RESPONSE_ID = 0x7E8
CAN_DATA_LENGTH = 8
PADDING_BYTE = 0x00
FIRST_FRAME_TYPE = 0x10
CONSECUTIVE_FRAME_TYPE = 0x20
SINGLE_FRAME_MAX_PAYLOAD = 7
FIRST_FRAME_PAYLOAD = 6
CONSECUTIVE_FRAME_PAYLOAD = 7
SEQUENCE_MASK = 0x0F
RESPONDER_POLL_S = 0.05

# Plausible steady-state values: 1726 rpm, 80 km/h, 50 C coolant, 100 kPa MAP,
# 49.8 % load, 25.1 % throttle, 20 C intake, 98 kPa baro, 14.12 V.
DEFAULT_VALUES: dict[int, bytes] = {
    0x04: b"\x7f",
    0x05: b"\x5a",
    0x0B: b"\x64",
    0x0C: b"\x1a\xf8",
    0x0D: b"\x50",
    0x0F: b"\x3c",
    0x11: b"\x40",
    0x33: b"\x62",
    0x42: b"\x37\x28",
}
DEFAULT_MODE09_PIDS = (0x02,)  # VIN advertised as supported (never served: multi-frame)


class FakeEcu:
    """Answers OBD2 PDUs from a mutable value map."""

    def __init__(
        self,
        values: dict[int, bytes] | None = None,
        mode09_pids: tuple[int, ...] = DEFAULT_MODE09_PIDS,
    ) -> None:
        """Serve ``values`` (PID -> data bytes), advertising them as supported."""
        self.values = dict(DEFAULT_VALUES if values is None else values)
        self.mode09_pids = mode09_pids
        self.requests: list[tuple[int, tuple[int, ...]]] = []

    @property
    def supported_pids(self) -> list[int]:
        """PIDs this ECU answers, in ascending order."""
        return sorted(self.values)

    def respond(self, mode: int, pids: list[int] | tuple[int, ...]) -> bytes | None:
        """Build the response PDU for a request, or None to stay silent."""
        self.requests.append((mode, tuple(pids)))
        if mode == MODE_CURRENT_DATA:
            return self._respond_mode01(pids)
        if mode == MODE_VEHICLE_INFO:
            return self._respond_mode09(pids)
        return None

    def respond_to_frame(self, request_payload: bytes) -> bytes | None:
        """Answer a request PDU (``01 0C``) with a response PDU."""
        if len(request_payload) < 2:
            return None
        return self.respond(request_payload[0], list(request_payload[1:]))

    def supported_bitmask(self, query_pid: int, pids: list[int] | None = None) -> bytes:
        """Bitmask of supported PIDs in the bank starting after ``query_pid``.

        The lowest bit advertises the next bank's query PID, so a scan tool
        walks 0x00 -> 0x20 -> 0x40 exactly as it would on a real vehicle.
        """
        available = self.supported_pids if pids is None else pids
        bits = 0
        for pid in available:
            offset = pid - query_pid
            if 1 <= offset <= PIDS_PER_BITMASK:
                bits |= 1 << (PIDS_PER_BITMASK - offset)
        if any(pid > query_pid + PIDS_PER_BITMASK for pid in available):
            bits |= 1  # continuation: the next query PID is supported
        return bits.to_bytes(SUPPORT_BITMASK_BYTES, "big")

    def _respond_mode01(self, pids: list[int] | tuple[int, ...]) -> bytes | None:
        payload = bytearray([MODE_CURRENT_DATA + RESPONSE_MODE_OFFSET])
        for pid in pids:
            if pid in SUPPORT_QUERY_PIDS:
                payload += bytes([pid]) + self.supported_bitmask(pid)
            elif pid in self.values:
                payload += bytes([pid]) + self.values[pid]
        return bytes(payload) if len(payload) > 1 else None

    def _respond_mode09(self, pids: list[int] | tuple[int, ...]) -> bytes | None:
        payload = bytearray([MODE_VEHICLE_INFO + RESPONSE_MODE_OFFSET])
        for pid in pids:
            # Only the support bitmask is served; VIN itself needs multi-frame
            # flow control, which PiGauge does not implement (Phase 9).
            if pid == SUPPORT_QUERY_PIDS[0]:
                payload += bytes([pid]) + self.supported_bitmask(pid, list(self.mode09_pids))
        return bytes(payload) if len(payload) > 1 else None


def single_frame(payload: bytes) -> bytes:
    """Wrap a PDU in an ISO-TP single frame, padded to 8 bytes."""
    if len(payload) > SINGLE_FRAME_MAX_PAYLOAD:
        raise ValueError(f"{len(payload)} bytes needs multi-frame; use isotp_frames()")
    framed = bytes([len(payload)]) + payload
    return framed.ljust(CAN_DATA_LENGTH, bytes([PADDING_BYTE]))


def isotp_frames(payload: bytes) -> list[bytes]:
    """Split a PDU into ISO-TP frames (single, or first + consecutive)."""
    if len(payload) <= SINGLE_FRAME_MAX_PAYLOAD:
        return [single_frame(payload)]
    first = bytes([FIRST_FRAME_TYPE | (len(payload) >> 8), len(payload) & 0xFF])
    frames = [(first + payload[:FIRST_FRAME_PAYLOAD]).ljust(CAN_DATA_LENGTH,
                                                            bytes([PADDING_BYTE]))]
    remaining = payload[FIRST_FRAME_PAYLOAD:]
    for index in range(0, len(remaining), CONSECUTIVE_FRAME_PAYLOAD):
        sequence = (index // CONSECUTIVE_FRAME_PAYLOAD + 1) & SEQUENCE_MASK
        chunk = remaining[index : index + CONSECUTIVE_FRAME_PAYLOAD]
        frame = bytes([CONSECUTIVE_FRAME_TYPE | sequence]) + chunk
        frames.append(frame.ljust(CAN_DATA_LENGTH, bytes([PADDING_BYTE])))
    return frames


class FakeMessage:
    """Duck-typed stand-in for can.Message (tests need no python-can)."""

    def __init__(self, arbitration_id: int, data: bytes, is_extended_id: bool = False) -> None:
        """Record the three fields the transport reads."""
        self.arbitration_id = arbitration_id
        self.data = bytes(data)
        self.is_extended_id = is_extended_id

    def __repr__(self) -> str:
        """Readable form for test failure output."""
        return f"FakeMessage(0x{self.arbitration_id:X}, {self.data.hex(' ')})"


class FakeCanBus:
    """In-process CAN bus wired straight to a :class:`FakeEcu`.

    Implements the slice of the python-can Bus API the transport uses:
    ``send``, ``recv``, ``shutdown``.
    """

    def __init__(
        self,
        ecu: FakeEcu | None = None,
        response_id: int = OBD_RESPONSE_ID,
        noise: list[FakeMessage] | None = None,
    ) -> None:
        """Answer requests from ``ecu``; ``noise`` frames precede each reply."""
        self.ecu = ecu or FakeEcu()
        self.response_id = response_id
        self.noise = list(noise or [])
        self.sent: list[FakeMessage] = []
        self.shutdowns = 0
        self.send_error: Exception | None = None
        self.recv_error: Exception | None = None
        self._inbox: list[FakeMessage] = []

    def send(self, message, timeout=None):
        """Accept a request frame and queue the ECU's reply."""
        if self.send_error is not None:
            raise self.send_error
        self.sent.append(message)
        if message.arbitration_id != OBD_REQUEST_ID:
            return
        self._inbox.extend(self.noise)
        payload = bytes(message.data)
        request = payload[1 : 1 + payload[0]] if payload else b""
        response = self.ecu.respond_to_frame(request)
        if response is None:
            return
        for frame in isotp_frames(response):
            self._inbox.append(FakeMessage(self.response_id, frame))

    def recv(self, timeout=None):
        """Return the next queued frame, or None when the inbox is empty."""
        if self.recv_error is not None:
            raise self.recv_error
        return self._inbox.pop(0) if self._inbox else None

    def shutdown(self):
        """Record that the transport released the bus."""
        self.shutdowns += 1


def serve_on_bus(bus, ecu: FakeEcu, stop_event: threading.Event, message_factory,
                 response_id: int = OBD_RESPONSE_ID) -> None:
    """Answer OBD requests on a real python-can bus until ``stop_event`` is set.

    This is the responder half of the vcan round-trip test: it runs in a
    thread with a real socketcan bus on one side and :class:`FakeEcu` on
    the other.
    """
    while not stop_event.is_set():
        message = bus.recv(RESPONDER_POLL_S)
        if message is None or message.arbitration_id != OBD_REQUEST_ID:
            continue
        payload = bytes(message.data)
        response = ecu.respond_to_frame(payload[1 : 1 + payload[0]])
        if response is None:
            continue
        for frame in isotp_frames(response):
            bus.send(message_factory(arbitration_id=response_id, data=frame,
                                     is_extended_id=False))
