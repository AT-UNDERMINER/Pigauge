"""socketcan transport against an in-process fake ECU (no python-can needed)."""

import pytest
from fake_ecu import OBD_REQUEST_ID, FakeCanBus, FakeEcu, FakeMessage, single_frame

from pigauge.core.config.loader import load_vehicle_profile
from pigauge.core.config.models import CanProfileConfig
from pigauge.core.databus import DataBus
from pigauge.sources import can_socketcan
from pigauge.sources.can_socketcan import (
    CanTransport,
    build_request_payload,
    create_can_source,
    single_frame_payload,
)
from pigauge.sources.obd_profile import build_poll_plan
from pigauge.sources.obd_transport import ObdTransportError

GENERIC_PROFILE = "config/vehicles/generic_obd2.yaml"
SECOND_ECU_ID = 0x7E9


def make_transport(bus=None, profile_can=None, **kwargs):
    bus = bus if bus is not None else FakeCanBus()
    transport = CanTransport(
        profile_can or CanProfileConfig(),
        bus=bus,
        message_factory=FakeMessage,
        **kwargs,
    )
    transport.connect()
    return transport, bus


class TestFraming:
    def test_request_matches_protocols_md(self):
        assert build_request_payload(0x01, 0x0C) == b"\x02\x01\x0c\x00\x00\x00\x00\x00"

    def test_request_is_always_eight_bytes(self):
        assert len(build_request_payload(0x09, 0x00)) == 8

    def test_single_frame_payload_extracted_by_length(self):
        assert single_frame_payload(b"\x04\x41\x0c\x1a\xf8\x00\x00\x00") == b"\x41\x0c\x1a\xf8"

    def test_multi_frame_is_not_treated_as_single(self):
        assert single_frame_payload(b"\x10\x14\x49\x02\x01\x00\x00\x00") == b""

    def test_empty_frame(self):
        assert single_frame_payload(b"") == b""


class TestRequestResponse:
    def test_decoded_pid_round_trip(self):
        transport, _bus = make_transport()
        assert transport.request([0x0C]) == {0x0C: b"\x1a\xf8"}

    def test_request_frame_uses_profile_ids(self):
        profile_can = CanProfileConfig(request_id=OBD_REQUEST_ID, response_ids=[0x7E8])
        transport, bus = make_transport(profile_can=profile_can)
        transport.request([0x0D])
        assert bus.sent[0].arbitration_id == OBD_REQUEST_ID
        assert bus.sent[0].is_extended_id is False

    def test_extended_ids_flagged(self):
        profile_can = CanProfileConfig(request_id=0x18DB33F1, response_ids=[0x18DAF110])
        transport, bus = make_transport(profile_can=profile_can)
        transport.request([0x0C])
        assert bus.sent[0].is_extended_id is True

    def test_one_pid_per_frame(self):
        transport, bus = make_transport()
        transport.request([0x0C, 0x0D, 0x05])
        assert len(bus.sent) == 3
        assert transport.max_pids_per_request == 1

    def test_unsupported_pid_stays_silent(self):
        transport, _bus = make_transport(bus=FakeCanBus(FakeEcu(values={0x0C: b"\x1a\xf8"})))
        assert transport.request([0x0D]) == {}

    def test_unrelated_bus_traffic_is_ignored(self):
        noise = [
            FakeMessage(0x123, b"\x00" * 8),
            FakeMessage(0x7E0, b"\x02\x01\x0c\x00\x00\x00\x00\x00"),
        ]
        transport, _bus = make_transport(bus=FakeCanBus(noise=noise))
        assert transport.request([0x0C]) == {0x0C: b"\x1a\xf8"}

    def test_second_ecu_response_id_accepted(self):
        profile_can = CanProfileConfig(response_ids=[0x7E8, SECOND_ECU_ID])
        bus = FakeCanBus(response_id=SECOND_ECU_ID)
        transport, _bus = make_transport(bus=bus, profile_can=profile_can)
        assert transport.request([0x0C]) == {0x0C: b"\x1a\xf8"}

    def test_response_from_an_unlisted_id_is_ignored(self):
        profile_can = CanProfileConfig(response_ids=[0x7E8])
        transport, _bus = make_transport(
            bus=FakeCanBus(response_id=0x7EF), profile_can=profile_can
        )
        assert transport.request([0x0C]) == {}

    def test_mismatched_pid_response_is_ignored(self):
        class WrongPidBus(FakeCanBus):
            def send(self, message, timeout=None):
                self.sent.append(message)
                self._inbox.append(FakeMessage(0x7E8, single_frame(b"\x41\x0d\x50")))

        transport, _bus = make_transport(bus=WrongPidBus())
        assert transport.request([0x0C]) == {}

    def test_mode_09_support_query(self):
        transport, _bus = make_transport()
        assert transport.query(0x09, 0x00)[:2] == b"\x49\x00"


class TestTimeouts:
    def test_silence_returns_no_answers(self):
        class SilentBus(FakeCanBus):
            def send(self, message, timeout=None):
                self.sent.append(message)

        transport, _bus = make_transport(bus=SilentBus())
        assert transport.request([0x0C]) == {}

    def test_deadline_expires_without_blocking_forever(self):
        clock_ticks = iter([0.0, 0.0, 0.05, 0.3, 0.3])

        class ChattyBus(FakeCanBus):
            def send(self, message, timeout=None):
                self.sent.append(message)

            def recv(self, timeout=None):
                return FakeMessage(0x123, b"\x00" * 8)  # endless unrelated traffic

        transport, _bus = make_transport(
            bus=ChattyBus(), timeout_s=0.2, clock=lambda: next(clock_ticks)
        )
        assert transport.request([0x0C]) == {}


class TestLinkFaults:
    def test_send_failure_raises_transport_error(self):
        bus = FakeCanBus()
        bus.send_error = OSError("Network is down")
        transport, _bus = make_transport(bus=bus)
        with pytest.raises(ObdTransportError, match="CAN send failed"):
            transport.request([0x0C])

    def test_receive_failure_raises_transport_error(self):
        bus = FakeCanBus()
        bus.recv_error = OSError("bus off")
        transport, _bus = make_transport(bus=bus)
        with pytest.raises(ObdTransportError, match="CAN receive failed"):
            transport.request([0x0C])

    def test_request_before_connect_is_a_transport_error(self):
        transport = CanTransport(CanProfileConfig(), message_factory=FakeMessage)
        with pytest.raises(ObdTransportError, match="not open"):
            transport.request([0x0C])

    def test_injected_bus_is_not_shut_down(self):
        transport, bus = make_transport()
        transport.close()
        assert bus.shutdowns == 0  # the test owns the fake bus, not the transport


class TestGuardedImport:
    def test_module_imports_without_python_can(self):
        assert can_socketcan is not None  # importing this test file proves it

    def test_construction_without_python_can_gives_install_hint(self, monkeypatch):
        monkeypatch.setattr(can_socketcan, "can", None)
        with pytest.raises(RuntimeError, match=r"pigauge\[vehicle\]"):
            CanTransport(CanProfileConfig())

    def test_injected_bus_needs_no_python_can(self, monkeypatch):
        monkeypatch.setattr(can_socketcan, "can", None)
        transport, _bus = make_transport()
        assert transport.request([0x0C]) == {0x0C: b"\x1a\xf8"}


class TestCanSource:
    def test_source_publishes_the_whole_profile(self):
        bus = DataBus()
        profile = load_vehicle_profile(GENERIC_PROFILE)
        source = create_can_source(
            bus, profile, can_bus=FakeCanBus(), message_factory=FakeMessage
        )
        source.poll_once()
        assert bus.get("engine.rpm").value == pytest.approx(1726.0)
        assert bus.get("vehicle.speed").value == pytest.approx(80.0)
        assert bus.get("engine.coolant_temp").value == pytest.approx(50.0)
        assert bus.get("electrical.battery_v").value == pytest.approx(14.12)

    def test_provided_channels_come_from_the_profile(self):
        profile = load_vehicle_profile(GENERIC_PROFILE)
        source = create_can_source(
            DataBus(), profile, can_bus=FakeCanBus(), message_factory=FakeMessage
        )
        expected = [entry.channel_id for entry in build_poll_plan(profile)]
        assert source.provided_channels == expected

    def test_channel_absent_from_the_ecu_is_never_published(self):
        bus = DataBus()
        profile = load_vehicle_profile(GENERIC_PROFILE)
        ecu = FakeEcu(values={0x0C: b"\x1a\xf8"})  # rpm only
        source = create_can_source(
            bus, profile, can_bus=FakeCanBus(ecu), message_factory=FakeMessage
        )
        source.poll_once()
        assert bus.get("engine.rpm") is not None
        assert bus.get("engine.coolant_temp") is None
