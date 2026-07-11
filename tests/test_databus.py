"""DataBus tests: staleness transitions, subscriptions, and thread safety."""

import threading

import pytest

from pigauge.core.channels import UnknownChannelError
from pigauge.core.databus import DataBus, Quality, Reading

RPM = "engine.rpm"  # stale_after 0.5 s
PUBLISH_COUNT = 2000


class FakeClock:
    """Deterministic replacement for time.monotonic."""

    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def bus(clock):
    return DataBus(clock=clock)


class TestPublishGet:
    def test_get_before_any_publish_returns_none(self, bus):
        assert bus.get(RPM) is None

    def test_publish_then_get_returns_ok_reading(self, bus, clock):
        clock.now = 10.0
        bus.publish(RPM, 850.0)
        reading = bus.get(RPM)
        assert reading == Reading(RPM, 850.0, 10.0, Quality.OK)

    def test_explicit_timestamp_is_kept(self, bus, clock):
        clock.now = 10.0
        bus.publish(RPM, 900.0, timestamp=9.75)
        assert bus.get(RPM).timestamp == 9.75

    def test_latest_value_wins(self, bus):
        bus.publish(RPM, 800.0)
        bus.publish(RPM, 1200.0)
        assert bus.get(RPM).value == 1200.0

    def test_unknown_channel_rejected_everywhere(self, bus):
        with pytest.raises(UnknownChannelError):
            bus.publish("warp.speed", 9.0)
        with pytest.raises(UnknownChannelError):
            bus.get("warp.speed")
        with pytest.raises(UnknownChannelError):
            bus.subscribe("warp.speed", lambda reading: None)

    def test_snapshot_covers_all_channels(self, bus):
        bus.publish(RPM, 800.0)
        snapshot = bus.snapshot()
        assert set(snapshot) == set(bus.channels)
        assert snapshot[RPM].value == 800.0
        assert snapshot["vehicle.speed"] is None


class TestStaleness:
    def test_fresh_reading_is_ok(self, bus, clock):
        bus.publish(RPM, 800.0)
        clock.advance(0.49)
        assert bus.get(RPM).quality is Quality.OK

    def test_old_reading_goes_stale(self, bus, clock):
        bus.publish(RPM, 800.0)
        clock.advance(0.51)
        assert bus.get(RPM).quality is Quality.STALE

    def test_republish_recovers_from_stale(self, bus, clock):
        bus.publish(RPM, 800.0)
        clock.advance(5.0)
        assert bus.get(RPM).quality is Quality.STALE
        bus.publish(RPM, 820.0)
        assert bus.get(RPM).quality is Quality.OK

    def test_stale_after_is_per_channel(self, bus, clock):
        bus.publish(RPM, 800.0)                # stale_after 0.5
        bus.publish("fuel.level", 60.0)        # stale_after 30
        clock.advance(2.0)
        assert bus.get(RPM).quality is Quality.STALE
        assert bus.get("fuel.level").quality is Quality.OK

    def test_no_data_placeholder(self):
        placeholder = Reading.no_data(RPM)
        assert placeholder.quality is Quality.NO_DATA
        assert placeholder.value != placeholder.value  # NaN


class TestSubscriptions:
    def test_subscriber_receives_each_publish(self, bus):
        received = []
        bus.subscribe(RPM, received.append)
        bus.publish(RPM, 800.0)
        bus.publish(RPM, 900.0)
        assert [reading.value for reading in received] == [800.0, 900.0]
        assert all(reading.quality is Quality.OK for reading in received)

    def test_subscriber_only_sees_its_channel(self, bus):
        received = []
        bus.subscribe(RPM, received.append)
        bus.publish("vehicle.speed", 50.0)
        assert received == []

    def test_unsubscribe_stops_delivery(self, bus):
        received = []
        unsubscribe = bus.subscribe(RPM, received.append)
        bus.publish(RPM, 800.0)
        unsubscribe()
        bus.publish(RPM, 900.0)
        assert len(received) == 1

    def test_unsubscribe_is_idempotent(self, bus):
        unsubscribe = bus.subscribe(RPM, lambda reading: None)
        unsubscribe()
        unsubscribe()  # must not raise

    def test_subscriber_exception_never_propagates(self, bus, caplog):
        healthy_calls = []

        def broken(reading):
            raise RuntimeError("boom")

        bus.subscribe(RPM, broken)
        bus.subscribe(RPM, healthy_calls.append)
        bus.publish(RPM, 800.0)  # must not raise into the publisher
        assert len(healthy_calls) == 1
        assert "subscriber" in caplog.text


class TestConcurrency:
    """Phase 1 acceptance: publisher thread + reader on the same bus."""

    def test_publisher_thread_with_concurrent_reader(self):
        bus = DataBus()  # real clock
        received = []
        bus.subscribe(RPM, received.append)
        publisher_errors = []

        def publish_all():
            try:
                for i in range(PUBLISH_COUNT):
                    bus.publish(RPM, float(i))
            except Exception as exc:  # pragma: no cover - failure path
                publisher_errors.append(exc)

        publisher = threading.Thread(target=publish_all)
        publisher.start()
        last_seen = -1.0
        while publisher.is_alive():
            reading = bus.get(RPM)
            if reading is not None:
                assert reading.value >= last_seen  # values only move forward
                last_seen = reading.value
        publisher.join(timeout=5.0)

        assert not publisher_errors
        assert bus.get(RPM).value == float(PUBLISH_COUNT - 1)
        assert [r.value for r in received] == [float(i) for i in range(PUBLISH_COUNT)]
