"""ObdSource: publishing, scheduling, reconnection and backoff.

The transport is faked here — this covers the logic both vehicle links
share, independent of CAN frames or serial bytes.
"""

import threading

import pytest

from pigauge.core.databus import DataBus, Quality
from pigauge.sources.base import SourceStatus
from pigauge.sources.obd_pids import decoder_for_pid
from pigauge.sources.obd_profile import PollEntry
from pigauge.sources.obd_source import ObdSource
from pigauge.sources.obd_transport import BackoffPolicy, ObdTransportError

RPM = PollEntry("engine.rpm", 0x0C, 10.0, decoder_for_pid(0x0C))
SPEED = PollEntry("vehicle.speed", 0x0D, 5.0, decoder_for_pid(0x0D))
COOLANT = PollEntry("engine.coolant_temp", 0x05, 1.0, decoder_for_pid(0x05))

ECU_DATA = {0x0C: b"\x1a\xf8", 0x0D: b"\x50", 0x05: b"\x5a"}  # 1726 rpm, 80 km/h, 50 C
JOIN_TIMEOUT_S = 2.0


class FakeTransport:
    """Scriptable stand-in for a vehicle link."""

    name = "fake"

    def __init__(self, data=None, max_pids_per_request=1, fail_connects=0):
        self.max_pids_per_request = max_pids_per_request
        self.data = dict(ECU_DATA if data is None else data)
        self.requests: list[list[int]] = []
        self.connects = 0
        self.closes = 0
        self.connected = False
        self.fail_connects = fail_connects
        self.fail_next_request = False

    def connect(self):
        self.connects += 1
        if self.connects <= self.fail_connects:
            raise ObdTransportError(f"link down (attempt {self.connects})")
        self.connected = True

    def request(self, pids):
        if self.fail_next_request:
            self.fail_next_request = False
            raise ObdTransportError("bus off mid-request")
        self.requests.append(list(pids))
        return {pid: self.data[pid] for pid in pids if pid in self.data}

    def close(self):
        self.closes += 1
        self.connected = False


class FakeClock:
    """Manually advanced monotonic clock."""

    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class BackoffRecorder(threading.Event):
    """Stop event that records wait durations instead of sleeping."""

    def __init__(self, stop_after):
        super().__init__()
        self.waits: list[float] = []
        self._stop_after = stop_after

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if len(self.waits) >= self._stop_after:
            self.set()
        return self.is_set()


def make_source(transport=None, plan=(RPM, SPEED, COOLANT), **kwargs):
    bus = DataBus()
    transport = transport or FakeTransport()
    source = ObdSource(bus, transport, list(plan), **kwargs)
    return source, bus, transport


class TestPublishing:
    def test_decoded_base_units_reach_the_bus(self):
        source, bus, _transport = make_source()
        source.poll_once()
        assert bus.get("engine.rpm").value == pytest.approx(1726.0)
        assert bus.get("vehicle.speed").value == pytest.approx(80.0)
        assert bus.get("engine.coolant_temp").value == pytest.approx(50.0)

    def test_published_readings_are_fresh(self):
        source, bus, _transport = make_source()
        source.poll_once()
        assert bus.get("engine.rpm").quality is Quality.OK

    def test_unanswered_pid_is_not_published(self):
        source, bus, _transport = make_source(FakeTransport(data={0x0C: b"\x1a\xf8"}))
        source.poll_once()
        assert bus.get("engine.rpm") is not None
        assert bus.get("vehicle.speed") is None  # ECU stayed silent -> no reading

    def test_malformed_data_is_skipped_not_fatal(self):
        transport = FakeTransport(data={0x0C: b"\x1a", 0x0D: b"\x50"})  # rpm truncated
        source, bus, _transport = make_source(transport)
        assert source.poll_once() is True
        assert bus.get("engine.rpm") is None
        assert bus.get("vehicle.speed").value == pytest.approx(80.0)

    def test_provided_channels_follow_the_plan_priority(self):
        source, _bus, _transport = make_source()
        assert source.provided_channels == [
            "engine.rpm", "vehicle.speed", "engine.coolant_temp"
        ]


class TestBatching:
    def test_single_pid_transport_requests_one_at_a_time(self):
        source, _bus, transport = make_source()
        source.poll_once()
        assert transport.requests == [[0x0C], [0x0D], [0x05]]

    def test_batching_transport_groups_due_pids(self):
        source, _bus, transport = make_source(FakeTransport(max_pids_per_request=6))
        source.poll_once()
        assert transport.requests == [[0x0C, 0x0D, 0x05]]

    def test_batch_size_respected(self):
        source, _bus, transport = make_source(FakeTransport(max_pids_per_request=2))
        source.poll_once()
        assert transport.requests == [[0x0C, 0x0D], [0x05]]


class TestScheduling:
    def test_only_due_channels_are_requested(self):
        clock = FakeClock()
        source, _bus, transport = make_source(clock=clock)
        source.poll_once()
        transport.requests.clear()
        clock.advance(0.1)  # rpm due (10 Hz), speed and coolant not
        source.poll_once()
        assert transport.requests == [[0x0C]]

    def test_nothing_due_is_not_an_error(self):
        clock = FakeClock()
        source, _bus, transport = make_source(clock=clock)
        source.poll_once()
        transport.requests.clear()
        assert source.poll_once() is True
        assert transport.requests == []


class TestReconnection:
    def test_connect_failure_reports_reconnecting(self):
        source, _bus, _transport = make_source(FakeTransport(fail_connects=1))
        assert source.poll_once() is False
        assert source.status is SourceStatus.RECONNECTING

    def test_recovers_once_the_link_returns(self):
        source, bus, _transport = make_source(FakeTransport(fail_connects=2))
        assert source.poll_once() is False
        assert source.poll_once() is False
        assert source.poll_once() is True
        assert source.status is SourceStatus.CONNECTED
        assert bus.get("engine.rpm") is not None

    def test_mid_request_fault_drops_the_link(self):
        clock = FakeClock()
        source, _bus, transport = make_source(clock=clock)
        source.poll_once()
        transport.fail_next_request = True
        clock.advance(1.0)
        assert source.poll_once() is False
        assert transport.closes == 1
        assert source.status is SourceStatus.RECONNECTING

    def test_link_is_reopened_after_a_fault(self):
        clock = FakeClock()
        source, bus, transport = make_source(clock=clock)
        source.poll_once()
        transport.fail_next_request = True
        clock.advance(1.0)
        source.poll_once()
        source.poll_once()
        assert transport.connects == 2
        assert transport.connected
        assert bus.get("engine.rpm") is not None

    def test_reconnect_re_polls_every_channel_immediately(self):
        clock = FakeClock()
        source, _bus, transport = make_source(clock=clock)
        source.poll_once()
        transport.fail_next_request = True
        clock.advance(1.0)
        source.poll_once()
        transport.requests.clear()
        source.poll_once()  # reconnect: scheduler reset, nothing waits for its period
        assert transport.requests == [[0x0C], [0x0D], [0x05]]


class TestBackoffPolicy:
    def test_delays_double_up_to_the_cap(self):
        policy = BackoffPolicy(initial_s=0.5, factor=2.0, max_s=4.0)
        delays = [policy.delay_for(attempt) for attempt in range(1, 6)]
        assert delays == [0.5, 1.0, 2.0, 4.0, 4.0]

    def test_first_retry_is_the_initial_delay(self):
        assert BackoffPolicy().delay_for(1) == 0.5

    def test_attempts_are_one_based(self):
        with pytest.raises(ValueError, match="1-based"):
            BackoffPolicy().delay_for(0)


class TestThreadedLoop:
    def test_backoff_delays_are_applied_between_connect_attempts(self):
        source, _bus, _transport = make_source(
            FakeTransport(fail_connects=10), backoff=BackoffPolicy(0.5, 2.0, 30.0)
        )
        source._stop_event = BackoffRecorder(stop_after=4)
        source.start()
        source._thread.join(timeout=JOIN_TIMEOUT_S)
        assert source._stop_event.waits == [0.5, 1.0, 2.0, 4.0]

    def test_thread_publishes_until_stopped(self):
        source, bus, transport = make_source()
        source.start()
        deadline = threading.Event()
        deadline.wait(0.2)
        source.stop()
        assert bus.get("engine.rpm").value == pytest.approx(1726.0)
        assert transport.requests

    def test_stop_returns_promptly_and_closes_the_link(self):
        source, _bus, transport = make_source()
        source.start()
        source.stop()
        assert source.status is SourceStatus.STOPPED
        assert transport.closes == 1

    def test_status_is_reconnecting_before_the_first_connect(self):
        source, _bus, _transport = make_source(FakeTransport(fail_connects=99))
        source.start()
        try:
            assert source.status is SourceStatus.RECONNECTING
        finally:
            source.stop()

    def test_stop_before_start_is_safe(self):
        source, _bus, _transport = make_source()
        source.stop()
        assert source.status is SourceStatus.STOPPED

    def test_double_start_runs_one_thread(self):
        source, _bus, _transport = make_source()
        source.start()
        first = source._thread
        source.start()
        try:
            assert source._thread is first
        finally:
            source.stop()

    def test_unexpected_error_marks_the_source_errored(self):
        class ExplodingTransport(FakeTransport):
            def request(self, pids):
                raise RuntimeError("driver bug")

        source, _bus, _transport = make_source(ExplodingTransport())
        source.start()
        source._thread.join(timeout=JOIN_TIMEOUT_S)
        assert source.status is SourceStatus.ERROR
        source.stop()
