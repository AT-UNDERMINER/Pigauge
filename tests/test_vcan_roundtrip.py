"""End-to-end CAN round-trip over a real Linux vcan0 interface.

Everything here runs through python-can's socketcan backend against the
kernel, so it exercises the framing the in-process fake cannot: real
sockets, real 8-byte frames, real arbitration IDs. Bring the interface up
with ``sudo scripts/vcan_up.sh``; without it these tests skip (see
tests/conftest.py) and the in-process suite in test_can_socketcan.py
still covers the decode path.

A genuine bus-off fault needs hardware, so the reconnection test here
covers the ECU falling silent and coming back — the case a vehicle
actually produces when the ignition is cycled.
"""

import threading

import pytest
from fake_ecu import OBD_RESPONSE_ID, FakeEcu, serve_on_bus

from pigauge.core.config.loader import load_vehicle_profile
from pigauge.core.databus import DataBus, Quality
from pigauge.sources.base import SourceStatus
from pigauge.sources.can_socketcan import CanTransport, create_can_source

can = pytest.importorskip("can", reason="python-can not installed: pip install 'pigauge[vehicle]'")

pytestmark = pytest.mark.vcan

VCAN_INTERFACE = "vcan0"
GENERIC_PROFILE = "config/vehicles/generic_obd2.yaml"
RESPONDER_STOP_TIMEOUT_S = 2.0
PUBLISH_TIMEOUT_S = 3.0
POLL_INTERVAL_S = 0.02


def open_vcan() -> "can.BusABC":
    """Open a socketcan bus on vcan0."""
    return can.Bus(channel=VCAN_INTERFACE, interface="socketcan")


def wait_for(predicate, timeout: float = PUBLISH_TIMEOUT_S) -> bool:
    """Poll ``predicate`` until it is true or ``timeout`` elapses."""
    deadline = threading.Event()
    waited = 0.0
    while waited < timeout:
        if predicate():
            return True
        deadline.wait(POLL_INTERVAL_S)
        waited += POLL_INTERVAL_S
    return predicate()


@pytest.fixture
def ecu():
    """The fake ECU whose values the responder serves."""
    return FakeEcu()


@pytest.fixture
def responder(ecu):
    """Run the fake ECU on vcan0 in a background thread."""
    bus = open_vcan()
    stop_event = threading.Event()
    thread = threading.Thread(
        target=serve_on_bus,
        args=(bus, ecu, stop_event, can.Message, OBD_RESPONSE_ID),
        name="FakeEcuResponder",
        daemon=True,
    )
    thread.start()
    yield stop_event
    stop_event.set()
    thread.join(timeout=RESPONDER_STOP_TIMEOUT_S)
    bus.shutdown()


@pytest.fixture
def profile():
    """The shipped generic OBD2 profile."""
    return load_vehicle_profile(GENERIC_PROFILE)


class TestTransportRoundTrip:
    def test_request_returns_ecu_data(self, responder, profile):
        transport = CanTransport(profile.can, interface=VCAN_INTERFACE)
        transport.connect()
        try:
            assert transport.request([0x0C]) == {0x0C: b"\x1a\xf8"}
        finally:
            transport.close()

    def test_every_profile_pid_answers(self, responder, profile, ecu):
        transport = CanTransport(profile.can, interface=VCAN_INTERFACE)
        transport.connect()
        try:
            for pid in ecu.supported_pids:
                assert transport.request([pid]) == {pid: ecu.values[pid]}
        finally:
            transport.close()

    def test_unsupported_pid_times_out_quietly(self, responder, profile):
        transport = CanTransport(profile.can, interface=VCAN_INTERFACE)
        transport.connect()
        try:
            assert transport.request([0x2F]) == {}  # fuel level not served
        finally:
            transport.close()

    def test_supported_pid_bitmask_query(self, responder, profile):
        transport = CanTransport(profile.can, interface=VCAN_INTERFACE)
        transport.connect()
        try:
            assert transport.query(0x01, 0x00)[:2] == b"\x41\x00"
        finally:
            transport.close()


class TestSourceOverVcan:
    def test_source_publishes_base_units(self, responder, profile):
        bus = DataBus()
        source = create_can_source(bus, profile, interface=VCAN_INTERFACE)
        source.start()
        try:
            assert wait_for(lambda: bus.get("engine.rpm") is not None)
            assert bus.get("engine.rpm").value == pytest.approx(1726.0)
            assert wait_for(lambda: bus.get("engine.coolant_temp") is not None)
            assert bus.get("engine.coolant_temp").value == pytest.approx(50.0)
        finally:
            source.stop()

    def test_source_reports_connected(self, responder, profile):
        bus = DataBus()
        source = create_can_source(bus, profile, interface=VCAN_INTERFACE)
        source.start()
        try:
            assert wait_for(lambda: source.status is SourceStatus.CONNECTED)
        finally:
            source.stop()

    def test_stop_is_prompt(self, responder, profile):
        source = create_can_source(DataBus(), profile, interface=VCAN_INTERFACE)
        source.start()
        source.stop()
        assert source.status is SourceStatus.STOPPED

    def test_silent_ecu_goes_stale_then_recovers(self, responder, profile, ecu):
        bus = DataBus()
        source = create_can_source(bus, profile, interface=VCAN_INTERFACE)
        source.start()
        try:
            assert wait_for(lambda: bus.get("engine.rpm") is not None)
            responder.set()  # ECU stops answering: engine.rpm goes STALE (0.5 s)
            assert wait_for(lambda: bus.get("engine.rpm").quality is Quality.STALE)
            assert source.status is not SourceStatus.ERROR  # silence is not a fault
        finally:
            source.stop()
