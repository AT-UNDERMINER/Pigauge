"""ELM327 transport against the FakeELM327 serial emulator."""

import pytest
from fake_ecu import FakeEcu
from fake_elm327 import KLINE_HEADER, FakeELM327

from pigauge.core.config.loader import load_vehicle_profile
from pigauge.core.config.models import Elm327ProfileConfig, VehicleProfile
from pigauge.core.databus import DataBus
from pigauge.sources import elm327 as elm327_module
from pigauge.sources.base import SourceStatus
from pigauge.sources.elm327 import (
    INIT_COMMANDS,
    MAX_BATCH_PIDS,
    PROTOCOL_PROBE,
    Elm327Transport,
    create_elm327_source,
    extract_pdu,
    frame_bytes,
    reassemble_isotp,
)
from pigauge.sources.obd_transport import ObdTransportError

GENERIC_PROFILE = "config/vehicles/generic_obd2.yaml"


class FakeClock:
    """Manually advanced monotonic clock for the poll schedule."""

    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def make_transport(adapter=None, batch_pids=False, **kwargs):
    adapter = adapter or FakeELM327()
    transport = Elm327Transport(
        Elm327ProfileConfig(batch_pids=batch_pids), serial_port=adapter, **kwargs
    )
    transport.connect()
    return transport, adapter


class TestResponseParsing:
    def test_odd_length_line_drops_the_11bit_header(self):
        assert frame_bytes("7E804410C1AF8") == b"\x04\x41\x0c\x1a\xf8"

    def test_even_length_line_is_left_intact(self):
        assert frame_bytes("486B10410C1AF8") == b"\x48\x6b\x10\x41\x0c\x1a\xf8"

    def test_spaces_are_tolerated(self):
        assert frame_bytes("7E8 04 41 0C 1A F8") == b"\x04\x41\x0c\x1a\xf8"

    def test_garbage_line_yields_nothing(self):
        assert frame_bytes("NO DATA") == b""

    def test_pdu_found_after_a_pci_byte(self):
        assert extract_pdu(b"\x04\x41\x0c\x1a\xf8", 0x41, [0x0C]) == b"\x41\x0c\x1a\xf8"

    def test_pdu_found_after_a_kline_header(self):
        frame = b"\x48\x6b\x10\x41\x0c\x1a\xf8"
        assert extract_pdu(frame, 0x41, [0x0C]) == b"\x41\x0c\x1a\xf8"

    def test_pdu_for_another_pid_is_not_accepted(self):
        assert extract_pdu(b"\x04\x41\x0d\x50", 0x41, [0x0C]) == b""

    def test_multi_frame_reassembly_honours_declared_length(self):
        frames = [b"\x10\x08\x41\x0c\x1a\xf8\x0d\x32", b"\x21\x05\x5a\x00\x00\x00\x00\x00"]
        assert reassemble_isotp(frames) == b"\x41\x0c\x1a\xf8\x0d\x32\x05\x5a"

    def test_single_frame_is_not_reassembled(self):
        assert reassemble_isotp([b"\x04\x41\x0c\x1a\xf8"]) == b""


class TestInitSequence:
    def test_documented_commands_in_order(self):
        _transport, adapter = make_transport()
        assert adapter.commands[: len(INIT_COMMANDS)] == list(INIT_COMMANDS)

    def test_protocol_probe_follows_init(self):
        _transport, adapter = make_transport()
        assert adapter.commands[len(INIT_COMMANDS)] == PROTOCOL_PROBE

    def test_negotiated_protocol_recorded(self):
        transport, _adapter = make_transport()
        assert "ISO 15765-4" in transport.protocol

    def test_command_echo_before_ate0_is_tolerated(self):
        transport, adapter = make_transport()
        assert adapter.echo is False  # ATE0 took effect
        assert transport.request([0x0C]) == {0x0C: b"\x1a\xf8"}


class TestPolling:
    def test_single_pid_round_trip(self):
        transport, _adapter = make_transport()
        assert transport.request([0x0C]) == {0x0C: b"\x1a\xf8"}

    def test_request_uses_plain_pid_hex(self):
        transport, adapter = make_transport()
        transport.request([0x0C])
        assert adapter.commands[-1] == "010C"

    def test_unsupported_pid_returns_no_data(self):
        transport, _adapter = make_transport(FakeELM327(FakeEcu(values={0x0C: b"\x1a\xf8"})))
        assert transport.request([0x0D]) == {}

    def test_kline_style_headers_still_decode(self):
        transport, _adapter = make_transport(FakeELM327(header=KLINE_HEADER))
        assert transport.request([0x0C]) == {0x0C: b"\x1a\xf8"}

    def test_mode_09_support_query(self):
        transport, _adapter = make_transport()
        assert transport.query(0x09, 0x00)[:2] == b"\x49\x00"


class TestBatching:
    def test_batching_disabled_by_default(self):
        transport, _adapter = make_transport()
        assert transport.max_pids_per_request == 1

    def test_profile_flag_enables_batching(self):
        transport, _adapter = make_transport(batch_pids=True)
        assert transport.max_pids_per_request == MAX_BATCH_PIDS

    def test_batched_request_is_one_command(self):
        transport, adapter = make_transport(batch_pids=True)
        transport.request([0x0C, 0x0D, 0x05])
        assert adapter.commands[-1] == "010C0D05"

    def test_batched_multi_frame_reply_decodes_every_pid(self):
        transport, _adapter = make_transport(batch_pids=True)
        assert transport.request([0x0C, 0x0D, 0x05]) == {
            0x0C: b"\x1a\xf8",
            0x0D: b"\x50",
            0x05: b"\x5a",
        }


class TestLinkFaults:
    def test_unable_to_connect_is_a_transport_error(self):
        transport = Elm327Transport(
            Elm327ProfileConfig(), serial_port=FakeELM327(unable_to_connect=True)
        )
        with pytest.raises(ObdTransportError, match="could not reach the ECU"):
            transport.connect()

    def test_wedged_adapter_times_out(self):
        transport = Elm327Transport(Elm327ProfileConfig(), serial_port=FakeELM327(silent=True))
        with pytest.raises(ObdTransportError, match="timed out waiting for prompt"):
            transport.connect()

    def test_unplugged_adapter_raises_on_request(self):
        transport, adapter = make_transport()
        adapter.write_error = OSError("device disconnected")
        with pytest.raises(ObdTransportError, match="failed on 010C"):
            transport.request([0x0C])

    def test_port_that_will_not_open_is_a_transport_error(self):
        def broken_factory(**kwargs):
            raise OSError("No such file or directory")

        transport = Elm327Transport(Elm327ProfileConfig(), serial_factory=broken_factory)
        with pytest.raises(ObdTransportError, match="cannot open"):
            transport.connect()

    def test_request_before_connect_is_a_transport_error(self):
        transport = Elm327Transport(Elm327ProfileConfig(), serial_factory=FakeELM327)
        with pytest.raises(ObdTransportError, match="not open"):
            transport.request([0x0C])

    def test_injected_port_is_not_closed(self):
        transport, adapter = make_transport()
        transport.close()
        assert adapter.closes == 0

    def test_opened_port_is_closed(self):
        transport = Elm327Transport(Elm327ProfileConfig(), serial_factory=FakeELM327)
        transport.connect()
        transport.close()
        assert transport._serial is None


class TestGuardedImport:
    def test_module_imports_without_pyserial(self):
        assert elm327_module is not None  # importing this test file proves it

    def test_construction_without_pyserial_gives_install_hint(self, monkeypatch):
        monkeypatch.setattr(elm327_module, "serial", None)
        with pytest.raises(RuntimeError, match=r"pigauge\[vehicle\]"):
            Elm327Transport(Elm327ProfileConfig())

    def test_injected_port_needs_no_pyserial(self, monkeypatch):
        monkeypatch.setattr(elm327_module, "serial", None)
        transport, _adapter = make_transport()
        assert transport.request([0x0C]) == {0x0C: b"\x1a\xf8"}


class TestElm327Source:
    def test_source_publishes_base_units(self):
        bus = DataBus()
        source = create_elm327_source(
            bus, load_vehicle_profile(GENERIC_PROFILE), serial_port=FakeELM327()
        )
        source.poll_once()
        assert bus.get("engine.rpm").value == pytest.approx(1726.0)
        assert bus.get("engine.coolant_temp").value == pytest.approx(50.0)

    def test_batching_flag_reaches_the_transport(self):
        profile = VehicleProfile(
            name="batched", elm327=Elm327ProfileConfig(batch_pids=True),
            channels=load_vehicle_profile(GENERIC_PROFILE).channels,
        )
        adapter = FakeELM327()
        source = create_elm327_source(DataBus(), profile, serial_port=adapter)
        source.poll_once()
        assert any(len(command) > 4 for command in adapter.commands)  # multi-PID request

    def test_reconnects_after_the_adapter_drops(self):
        bus = DataBus()
        adapter = FakeELM327()
        clock = FakeClock()
        source = create_elm327_source(
            bus, load_vehicle_profile(GENERIC_PROFILE), serial_port=adapter, clock=clock
        )
        source.poll_once()
        adapter.write_error = OSError("device disconnected")
        clock.advance(1.0)
        assert source.poll_once() is False
        assert source.status is SourceStatus.RECONNECTING

        adapter.write_error = None  # cable pushed back in
        assert source.poll_once() is True
        assert source.status is SourceStatus.CONNECTED

    def test_reconnect_reruns_the_init_sequence(self):
        adapter = FakeELM327()
        clock = FakeClock()
        source = create_elm327_source(
            DataBus(), load_vehicle_profile(GENERIC_PROFILE), serial_port=adapter, clock=clock
        )
        source.poll_once()
        adapter.write_error = OSError("device disconnected")
        clock.advance(1.0)
        source.poll_once()
        adapter.write_error = None
        adapter.commands.clear()
        source.poll_once()
        assert adapter.commands[: len(INIT_COMMANDS)] == list(INIT_COMMANDS)
