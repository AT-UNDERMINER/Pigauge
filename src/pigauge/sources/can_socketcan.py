"""socketcan OBD2 transport (MCP2515 HAT on the Pi, vcan0 in tests).

Speaks ISO 15765-4 as described in docs/PROTOCOLS.md: a broadcast request
``02 01 <PID>`` on 0x7DF, a positive response ``<len> 41 <PID> <data...>``
from 0x7E8-0x7EF. Request/response IDs and bitrate come from the vehicle
profile, never from this module.

Only single-frame responses are handled, which is all a mode 01 PID or a
supported-PID bitmask ever needs. Multi-frame reassembly (VIN, mode 22)
would require flow-control frames and is deliberately out of scope until
Phase 9.

python-can is an optional extra (``pip install 'pigauge[vehicle]'``): the
module always imports, and the dependency is only required when opening a
real bus, so the decode path stays testable with an injected fake.
"""

import logging
import time
from collections.abc import Callable, Sequence
from typing import Any

from pigauge.core.config.models import CanProfileConfig, VehicleProfile
from pigauge.core.databus import DataBus
from pigauge.sources.obd_pids import MODE_CURRENT_DATA, RESPONSE_MODE_OFFSET, parse_mode01_payload
from pigauge.sources.obd_profile import build_poll_plan
from pigauge.sources.obd_source import ObdSource
from pigauge.sources.obd_transport import ObdTransportError

try:  # vehicle-only dependency (pip install 'pigauge[vehicle]')
    import can
except ImportError:  # pragma: no cover - exercised by the guarded-import test
    can = None

logger = logging.getLogger(__name__)

DEFAULT_INTERFACE = "can0"
DEFAULT_RESPONSE_TIMEOUT_S = 0.2
CAN_DATA_LENGTH = 8
PADDING_BYTE = 0x00
SINGLE_FRAME_TYPE = 0x0
PCI_TYPE_SHIFT = 4
PCI_LENGTH_MASK = 0x0F
STANDARD_ID_MAX = 0x7FF
REQUEST_HEADER_BYTES = 2
"""A mode 01 request payload is ``<mode> <pid>`` after the PCI byte."""

INSTALL_HINT = (
    "python-can is not installed - install vehicle extras: pip install 'pigauge[vehicle]'"
)


def build_request_payload(mode: int, pid: int) -> bytes:
    """Build the 8-byte single-frame request payload for one PID."""
    payload = bytes([REQUEST_HEADER_BYTES, mode, pid])
    return payload.ljust(CAN_DATA_LENGTH, bytes([PADDING_BYTE]))


def single_frame_payload(data: bytes) -> bytes:
    """Extract the PDU from an ISO-TP single frame, or b'' if it is not one."""
    if not data:
        return b""
    pci = data[0]
    if pci >> PCI_TYPE_SHIFT != SINGLE_FRAME_TYPE:
        return b""  # first/consecutive/flow-control frame: not handled here
    length = pci & PCI_LENGTH_MASK
    return bytes(data[1 : 1 + length])


class CanTransport:
    """One socketcan link, driven by :class:`~pigauge.sources.obd_source.ObdSource`."""

    name = "can"
    max_pids_per_request = 1
    """ISO 15765-4 carries one PID per request frame; batching is ELM327-only."""

    def __init__(
        self,
        profile_can: CanProfileConfig | None = None,
        *,
        interface: str = DEFAULT_INTERFACE,
        timeout_s: float = DEFAULT_RESPONSE_TIMEOUT_S,
        bus: Any = None,
        message_factory: Callable[..., Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Configure the link from the vehicle profile's ``can`` section."""
        settings = profile_can or CanProfileConfig()
        self._interface = interface
        self._bitrate = settings.bitrate
        self._request_id = settings.request_id
        self._response_ids = set(settings.response_ids)
        self._timeout_s = timeout_s
        self._bus = bus
        self._injected_bus = bus is not None
        self._message_factory = message_factory
        self._clock = clock
        if can is None and not self._injected_bus and message_factory is None:
            raise RuntimeError(INSTALL_HINT)

    def connect(self) -> None:
        """Open the socketcan interface (no-op for an injected bus)."""
        if self._bus is not None:
            return
        try:
            self._bus = can.Bus(
                channel=self._interface, interface="socketcan", bitrate=self._bitrate
            )
        except Exception as error:  # python-can raises OSError/CanError variants
            raise ObdTransportError(f"cannot open {self._interface}: {error}") from error

    def request(self, pids: Sequence[int]) -> dict[int, bytes]:
        """Query mode 01 PIDs one frame at a time, returning what answered."""
        answers: dict[int, bytes] = {}
        for pid in pids:
            payload = self.query(MODE_CURRENT_DATA, pid)
            answers.update(parse_mode01_payload(payload))
        return answers

    def query(self, mode: int, pid: int) -> bytes:
        """Send one request and return its response PDU (b'' if unanswered).

        The PDU starts at the response mode byte, e.g. ``41 0C 1A F8``.
        """
        self._send(mode, pid)
        return self._await_response(mode, pid)

    def close(self) -> None:
        """Release the bus, unless it was injected by a caller or test."""
        if self._bus is None or self._injected_bus:
            return
        try:
            self._bus.shutdown()
        except Exception:  # pragma: no cover - shutdown of a dead bus
            logger.debug("shutdown of %s failed", self._interface)
        finally:
            self._bus = None

    def _send(self, mode: int, pid: int) -> None:
        """Transmit the request frame, mapping bus faults to transport errors."""
        if self._bus is None:
            raise ObdTransportError("CAN bus is not open")
        factory = self._message_factory or (can.Message if can is not None else None)
        if factory is None:  # pragma: no cover - guarded at construction
            raise ObdTransportError(INSTALL_HINT)
        message = factory(
            arbitration_id=self._request_id,
            data=build_request_payload(mode, pid),
            is_extended_id=self._request_id > STANDARD_ID_MAX,
        )
        try:
            self._bus.send(message)
        except Exception as error:
            raise ObdTransportError(f"CAN send failed: {error}") from error

    def _await_response(self, mode: int, pid: int) -> bytes:
        """Read until the matching response arrives or the timeout expires."""
        deadline = self._clock() + self._timeout_s
        while True:
            remaining = deadline - self._clock()
            if remaining <= 0:
                return b""
            try:
                message = self._bus.recv(remaining)
            except Exception as error:
                raise ObdTransportError(f"CAN receive failed: {error}") from error
            if message is None:
                return b""  # silence: the channel will simply go STALE
            if message.arbitration_id not in self._response_ids:
                continue  # unrelated traffic on a live vehicle bus
            payload = single_frame_payload(bytes(message.data))
            if self._matches(payload, mode, pid):
                return payload

    @staticmethod
    def _matches(payload: bytes, mode: int, pid: int) -> bool:
        """Is this PDU the positive response to the request just sent?"""
        expected_mode = mode + RESPONSE_MODE_OFFSET
        return len(payload) >= 2 and payload[0] == expected_mode and payload[1] == pid


def create_can_source(
    bus: DataBus,
    profile: VehicleProfile,
    *,
    interface: str = DEFAULT_INTERFACE,
    profile_source: str = "<vehicle profile>",
    can_bus: Any = None,
    source_clock: Callable[[], float] | None = None,
    **transport_options: Any,
) -> ObdSource:
    """Build a CAN-backed :class:`ObdSource` from a vehicle profile.

    ``source_clock`` overrides the poll-schedule clock (tests only); the
    transport's own response-deadline clock is separate.
    """
    transport = CanTransport(
        profile.can,
        interface=interface,
        bus=can_bus,
        **transport_options,
    )
    plan = build_poll_plan(profile, profile_source)
    source_options = {} if source_clock is None else {"clock": source_clock}
    return ObdSource(bus, transport, plan, **source_options)
