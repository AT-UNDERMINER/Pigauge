"""The fake ECU itself: PDU answers, ISO-TP framing, and the bus responder.

test_vcan_roundtrip.py cannot run without Linux vcan, so the responder
logic it depends on is proven here against a queue-backed loopback pair
that blocks on recv() the way a real socketcan bus does. What vcan then
adds is only the kernel socket layer.
"""

import queue
import threading

import pytest
from fake_ecu import (
    OBD_REQUEST_ID,
    OBD_RESPONSE_ID,
    FakeEcu,
    FakeMessage,
    isotp_frames,
    serve_on_bus,
    single_frame,
)

from pigauge.core.config.models import CanProfileConfig
from pigauge.sources.can_socketcan import CanTransport
from pigauge.sources.obd_pids import decode_supported_pids, parse_mode01_payload

RESPONDER_JOIN_TIMEOUT_S = 2.0


class LoopbackBus:
    """Blocking in-memory bus: what one end sends, the other receives."""

    def __init__(self, inbox: queue.Queue, outbox: queue.Queue) -> None:
        """Wire this end to a pair of queues shared with its peer."""
        self.inbox = inbox
        self.outbox = outbox

    def send(self, message, timeout=None):
        self.outbox.put(message)

    def recv(self, timeout=None):
        try:
            return self.inbox.get(timeout=timeout)
        except queue.Empty:
            return None  # a real bus returns None when the timeout expires

    def shutdown(self):
        pass


def loopback_pair() -> tuple[LoopbackBus, LoopbackBus]:
    """Two buses joined back to back."""
    to_ecu: queue.Queue = queue.Queue()
    to_client: queue.Queue = queue.Queue()
    return LoopbackBus(to_client, to_ecu), LoopbackBus(to_ecu, to_client)


class TestModeOneResponses:
    def test_single_pid(self):
        assert FakeEcu().respond(0x01, [0x0C]) == b"\x41\x0c\x1a\xf8"

    def test_batched_pids_concatenate(self):
        assert FakeEcu().respond(0x01, [0x0C, 0x0D]) == b"\x41\x0c\x1a\xf8\x0d\x50"

    def test_unsupported_pid_omitted_from_a_batch(self):
        assert FakeEcu().respond(0x01, [0x0C, 0x2F]) == b"\x41\x0c\x1a\xf8"

    def test_wholly_unsupported_request_is_silent(self):
        assert FakeEcu().respond(0x01, [0x2F]) is None

    def test_unknown_mode_is_silent(self):
        assert FakeEcu().respond(0x22, [0x12, 0x34]) is None

    def test_values_are_mutable_mid_test(self):
        ecu = FakeEcu()
        ecu.values[0x0C] = b"\x00\x00"
        assert ecu.respond(0x01, [0x0C]) == b"\x41\x0c\x00\x00"

    def test_requests_are_logged(self):
        ecu = FakeEcu()
        ecu.respond(0x01, [0x0C])
        assert ecu.requests == [(0x01, (0x0C,))]


class TestSupportBitmasks:
    def test_default_ecu_advertises_its_own_pids(self):
        ecu = FakeEcu()
        supported = decode_supported_pids(0x00, ecu.supported_bitmask(0x00))
        assert 0x0C in supported and 0x05 in supported
        assert 0x2F not in supported  # not served

    def test_continuation_bit_points_at_the_next_bank(self):
        ecu = FakeEcu()  # 0x42 lives in the third bank
        assert 0x20 in decode_supported_pids(0x00, ecu.supported_bitmask(0x00))
        assert 0x40 in decode_supported_pids(0x20, ecu.supported_bitmask(0x20))
        assert 0x42 in decode_supported_pids(0x40, ecu.supported_bitmask(0x40))

    def test_last_bank_has_no_continuation(self):
        ecu = FakeEcu()
        assert 0x60 not in decode_supported_pids(0x40, ecu.supported_bitmask(0x40))

    def test_mode_09_bitmask_lists_vin(self):
        payload = FakeEcu().respond(0x09, [0x00])
        assert payload[:2] == b"\x49\x00"
        assert decode_supported_pids(0x00, payload[2:]) == [0x02]

    def test_vin_itself_is_not_served(self):
        assert FakeEcu().respond(0x09, [0x02]) is None


class TestIsoTpFraming:
    def test_short_payload_is_one_padded_frame(self):
        frames = isotp_frames(b"\x41\x0c\x1a\xf8")
        assert frames == [b"\x04\x41\x0c\x1a\xf8\x00\x00\x00"]

    def test_seven_bytes_still_fit_one_frame(self):
        assert len(isotp_frames(b"\x41" + b"\x00" * 6)) == 1

    def test_eight_bytes_spill_into_a_first_and_consecutive_frame(self):
        frames = isotp_frames(b"\x41\x0c\x1a\xf8\x0d\x50\x05\x5a")
        assert len(frames) == 2
        assert frames[0][:2] == b"\x10\x08"  # first frame, 8-byte PDU
        assert frames[1][0] == 0x21  # consecutive frame, sequence 1
        assert all(len(frame) == 8 for frame in frames)

    def test_payload_survives_a_round_trip_through_framing(self):
        payload = b"\x41\x0c\x1a\xf8\x0d\x50\x05\x5a\x0b\x64"
        frames = isotp_frames(payload)
        rebuilt = frames[0][2:] + b"".join(frame[1:] for frame in frames[1:])
        assert rebuilt[: len(payload)] == payload

    def test_single_frame_rejects_oversized_payloads(self):
        with pytest.raises(ValueError, match="multi-frame"):
            single_frame(b"\x00" * 8)


class TestBusResponder:
    """serve_on_bus is the fixture the vcan round-trip depends on."""

    def run_responder(self, ecu):
        client_bus, ecu_bus = loopback_pair()
        stop_event = threading.Event()
        thread = threading.Thread(
            target=serve_on_bus,
            args=(ecu_bus, ecu, stop_event, FakeMessage, OBD_RESPONSE_ID),
            daemon=True,
        )
        thread.start()
        return client_bus, stop_event, thread

    def test_transport_round_trip_through_the_responder(self):
        client_bus, stop_event, thread = self.run_responder(FakeEcu())
        transport = CanTransport(
            CanProfileConfig(), bus=client_bus, message_factory=FakeMessage, timeout_s=1.0
        )
        transport.connect()
        try:
            assert transport.request([0x0C]) == {0x0C: b"\x1a\xf8"}
            assert transport.request([0x05]) == {0x05: b"\x5a"}
        finally:
            stop_event.set()
            thread.join(timeout=RESPONDER_JOIN_TIMEOUT_S)

    def test_responder_answers_on_the_obd_response_id(self):
        client_bus, stop_event, thread = self.run_responder(FakeEcu())
        try:
            client_bus.send(FakeMessage(OBD_REQUEST_ID, b"\x02\x01\x0c\x00\x00\x00\x00\x00"))
            reply = client_bus.recv(timeout=1.0)
            assert reply is not None
            assert reply.arbitration_id == OBD_RESPONSE_ID
            assert parse_mode01_payload(reply.data[1 : 1 + reply.data[0]]) == {0x0C: b"\x1a\xf8"}
        finally:
            stop_event.set()
            thread.join(timeout=RESPONDER_JOIN_TIMEOUT_S)

    def test_unsupported_pid_gets_no_frame_at_all(self):
        client_bus, stop_event, thread = self.run_responder(FakeEcu())
        try:
            client_bus.send(FakeMessage(OBD_REQUEST_ID, b"\x02\x01\x2f\x00\x00\x00\x00\x00"))
            assert client_bus.recv(timeout=0.3) is None
        finally:
            stop_event.set()
            thread.join(timeout=RESPONDER_JOIN_TIMEOUT_S)

    def test_responder_ignores_non_obd_traffic(self):
        client_bus, stop_event, thread = self.run_responder(FakeEcu())
        try:
            client_bus.send(FakeMessage(0x123, b"\xde\xad\xbe\xef\x00\x00\x00\x00"))
            assert client_bus.recv(timeout=0.3) is None
        finally:
            stop_event.set()
            thread.join(timeout=RESPONDER_JOIN_TIMEOUT_S)

    def test_responder_stops_when_asked(self):
        _client_bus, stop_event, thread = self.run_responder(FakeEcu())
        stop_event.set()
        thread.join(timeout=RESPONDER_JOIN_TIMEOUT_S)
        assert not thread.is_alive()
