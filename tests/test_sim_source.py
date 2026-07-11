"""SimSource tests: determinism, plausibility, lifecycle, and CSV replay."""

import time

import pytest

from pigauge.core.channels import CHANNELS
from pigauge.core.databus import DataBus
from pigauge.sources.base import SourceStatus
from pigauge.sources.sim import CYCLE_S, DrivingSimulation, SimSource

TICK_S = 0.05
FULL_CYCLE_STEPS = int(CYCLE_S / TICK_S)


def run_cycle(seed: int = 1) -> list[dict[str, float]]:
    simulation = DrivingSimulation(seed)
    return [simulation.step(TICK_S) for _ in range(FULL_CYCLE_STEPS)]


class TestDeterminism:
    def test_same_seed_gives_identical_sequences(self):
        assert run_cycle(seed=42) == run_cycle(seed=42)

    def test_different_seeds_diverge(self):
        assert run_cycle(seed=1) != run_cycle(seed=2)


class TestPlausibility:
    def test_every_registered_channel_every_step(self):
        for values in run_cycle():
            assert set(values) == set(CHANNELS)

    def test_values_stay_in_plausible_ranges(self):
        for values in run_cycle():
            assert 0 <= values["engine.rpm"] <= 5000
            assert 0 <= values["vehicle.speed"] <= 200
            assert 0 <= values["engine.load"] <= 100
            assert 0 <= values["engine.throttle"] <= 100
            assert 0 <= values["boost.pressure"] <= 250
            assert values["engine.map"] >= values["boost.pressure"]  # map = baro + boost
            assert 50 <= values["oil.pressure"] <= 600
            assert 15 <= values["exhaust.egt1"] <= 700
            assert 10 <= values["electrical.battery_v"] <= 16
            assert 0 <= values["fuel.level"] <= 100
            assert values["system.ignition"] == 1.0

    def test_cycle_visits_idle_and_high_rpm(self):
        rpm_values = [values["engine.rpm"] for values in run_cycle()]
        assert min(rpm_values) < 1000  # idle phase
        assert max(rpm_values) > 2800  # accel peak

    def test_coolant_warms_up_over_time(self):
        simulation = DrivingSimulation(seed=1)
        first = simulation.step(TICK_S)["engine.coolant_temp"]
        for _ in range(FULL_CYCLE_STEPS * 4):
            last = simulation.step(TICK_S)["engine.coolant_temp"]
        assert last > first + 10


class TestSourceLifecycle:
    def test_start_publish_stop(self):
        bus = DataBus()
        source = SimSource(bus, seed=42, tick_hz=50)
        assert source.status is SourceStatus.STOPPED
        assert set(source.provided_channels) == set(CHANNELS)

        source.start()
        assert source.status is SourceStatus.CONNECTED
        deadline = time.monotonic() + 2.0
        while bus.get("engine.rpm") is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert bus.get("engine.rpm") is not None, "no data published within 2 s"

        stop_started = time.monotonic()
        source.stop()
        assert time.monotonic() - stop_started < 2.0
        assert source.status is SourceStatus.STOPPED

    def test_start_twice_is_harmless(self):
        source = SimSource(DataBus(), seed=1)
        source.start()
        source.start()
        source.stop()

    def test_stop_without_start_is_harmless(self):
        SimSource(DataBus(), seed=1).stop()


class TestReplay:
    def write_log(self, tmp_path, text):
        log = tmp_path / "log.csv"
        log.write_text(text, encoding="utf-8")
        return log

    def test_replay_publishes_rows_in_order_then_stops(self, tmp_path):
        log = self.write_log(
            tmp_path,
            "timestamp,engine.rpm,vehicle.speed\n"
            "0.0,800,0\n"
            "0.02,1200,\n"
            "0.04,1600,20\n",
        )
        bus = DataBus()
        source = SimSource(bus, replay_csv=log)
        assert source.provided_channels == ["engine.rpm", "vehicle.speed"]

        rpm_seen, speed_seen = [], []
        bus.subscribe("engine.rpm", lambda reading: rpm_seen.append(reading.value))
        bus.subscribe("vehicle.speed", lambda reading: speed_seen.append(reading.value))
        source.start()
        deadline = time.monotonic() + 2.0
        while source.status is SourceStatus.CONNECTED and time.monotonic() < deadline:
            time.sleep(0.01)

        assert source.status is SourceStatus.STOPPED  # replay ran to completion
        assert rpm_seen == [800.0, 1200.0, 1600.0]
        assert speed_seen == [0.0, 20.0]  # empty cell skipped

    def test_replay_rejects_unknown_channel(self, tmp_path):
        log = self.write_log(tmp_path, "timestamp,warp.speed\n0.0,9\n")
        with pytest.raises(ValueError, match="unknown channels"):
            SimSource(DataBus(), replay_csv=log)

    def test_replay_rejects_missing_timestamp_column(self, tmp_path):
        log = self.write_log(tmp_path, "time,engine.rpm\n0.0,800\n")
        with pytest.raises(ValueError, match="timestamp"):
            SimSource(DataBus(), replay_csv=log)

    def test_replay_rejects_decreasing_timestamps(self, tmp_path):
        log = self.write_log(
            tmp_path, "timestamp,engine.rpm\n1.0,800\n0.5,900\n"
        )
        with pytest.raises(ValueError, match="must not decrease"):
            SimSource(DataBus(), replay_csv=log)

    def test_replay_rejects_empty_log(self, tmp_path):
        log = self.write_log(tmp_path, "timestamp,engine.rpm\n")
        with pytest.raises(ValueError, match="no data rows"):
            SimSource(DataBus(), replay_csv=log)
