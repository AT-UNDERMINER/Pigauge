"""Simulated vehicle source: deterministic driving cycle or CSV replay.

:class:`DrivingSimulation` is a pure, seeded model producing plausible
values for every canonical channel through repeating idle → accel → cruise
cycles; two instances with the same seed emit identical sequences.
:class:`SimSource` wraps it in a thread that publishes to the DataBus, or
replays a CSV log at real-time speed.

Replay CSV format: header ``timestamp,<channel_id>,...`` where timestamp is
seconds from replay start (non-decreasing); empty cells are skipped. The
log is replayed once, then the source stops itself.
"""

import csv
import logging
import math
import random
import threading
from pathlib import Path

from pigauge.core.channels import CHANNELS
from pigauge.core.databus import DataBus
from pigauge.sources.base import Source, SourceStatus

logger = logging.getLogger(__name__)

IDLE_S = 6.0
ACCEL_S = 8.0
CRUISE_S = 16.0
CYCLE_S = IDLE_S + ACCEL_S + CRUISE_S

IDLE_RPM, ACCEL_PEAK_RPM, CRUISE_RPM = 820.0, 3200.0, 2100.0
CRUISE_SPEED_KMH = 100.0
AMBIENT_C = 22.0
WARM_COOLANT_C = 88.0
BARO_KPA = 97.8
BATTERY_RUNNING_V = 14.2
FUEL_START_PERCENT = 75.0
FUEL_BURN_PERCENT_PER_S = 0.005

COOLANT_TAU_S = 90.0
EGT_TAU_S = 4.0
BOOST_TAU_S = 1.0
INTAKE_TAU_S = 10.0

DEFAULT_TICK_HZ = 20.0
STOP_JOIN_TIMEOUT_S = 2.0


def _approach(current: float, target: float, tau: float, dt: float) -> float:
    """Move ``current`` toward ``target`` with time constant ``tau``."""
    return current + (target - current) * min(1.0, dt / tau)


class DrivingSimulation:
    """Deterministic idle → accel → cruise cycle for all canonical channels."""

    def __init__(self, seed: int = 0) -> None:
        """Seed the noise generator and reset slow state to cold-start."""
        self._rng = random.Random(seed)
        self.time = 0.0
        self._coolant = AMBIENT_C
        self._intake = AMBIENT_C
        self._egt = AMBIENT_C
        self._boost = 0.0
        self._fuel = FUEL_START_PERCENT

    def step(self, dt: float) -> dict[str, float]:
        """Advance the cycle by ``dt`` seconds and return all channel values."""
        self.time += dt
        rpm_target, speed, load, throttle, boost_target, egt_target = self._phase_targets()

        noise = self._rng.uniform  # drawn in fixed order for determinism
        rpm = max(0.0, rpm_target + noise(-25.0, 25.0))
        self._boost = _approach(self._boost, boost_target, BOOST_TAU_S, dt)
        self._egt = _approach(self._egt, egt_target, EGT_TAU_S, dt)
        self._coolant = _approach(self._coolant, WARM_COOLANT_C, COOLANT_TAU_S, dt)
        self._intake = _approach(self._intake, AMBIENT_C + 0.15 * load, INTAKE_TAU_S, dt)
        self._fuel = max(0.0, self._fuel - FUEL_BURN_PERCENT_PER_S * dt * (0.3 + load / 100))
        boost = max(0.0, self._boost + noise(-1.5, 1.5))

        return {
            "engine.rpm": rpm,
            "vehicle.speed": max(0.0, speed + noise(-1.0, 1.0)),
            "engine.coolant_temp": self._coolant,
            "engine.intake_temp": self._intake,
            "engine.load": min(100.0, max(0.0, load + noise(-3.0, 3.0))),
            "engine.throttle": min(100.0, max(0.0, throttle + noise(-2.0, 2.0))),
            "engine.map": BARO_KPA + boost,
            "boost.pressure": boost,
            "oil.pressure": 80.0 + 0.09 * rpm + noise(-8.0, 8.0),
            "exhaust.egt1": self._egt,
            "fuel.level": self._fuel,
            "electrical.battery_v": BATTERY_RUNNING_V + noise(-0.05, 0.05),
            "ambient.baro": BARO_KPA,
            "system.ignition": 1.0,
        }

    def _phase_targets(self) -> tuple[float, float, float, float, float, float]:
        """(rpm, speed, load %, throttle %, boost kPa, EGT °C) for the phase."""
        t = self.time % CYCLE_S
        if t < IDLE_S:
            return IDLE_RPM, 0.0, 12.0, 8.0, 0.0, 180.0
        if t < IDLE_S + ACCEL_S:
            progress = (t - IDLE_S) / ACCEL_S
            ramp = math.sin(progress * math.pi / 2)  # fast pull, easing off
            rpm = IDLE_RPM + (ACCEL_PEAK_RPM - IDLE_RPM) * ramp
            return rpm, CRUISE_SPEED_KMH * ramp, 85.0, 90.0, 120.0 * ramp, 560.0
        return CRUISE_RPM, CRUISE_SPEED_KMH, 35.0, 25.0, 40.0, 340.0


class SimSource(Source):
    """Source publishing simulated (or replayed) data from its own thread."""

    def __init__(
        self,
        bus: DataBus,
        seed: int = 0,
        tick_hz: float = DEFAULT_TICK_HZ,
        replay_csv: str | Path | None = None,
    ) -> None:
        """Simulate with ``seed`` at ``tick_hz``, or replay ``replay_csv``."""
        self._bus = bus
        self._tick_s = 1.0 / tick_hz
        self._simulation = DrivingSimulation(seed)
        self._replay_rows = None if replay_csv is None else _load_replay(Path(replay_csv))
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._status = SourceStatus.STOPPED

    def start(self) -> None:
        """Spawn the acquisition thread and begin publishing."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="SimSource", daemon=True)
        self._status = SourceStatus.CONNECTED
        self._thread.start()

    def stop(self) -> None:
        """Stop cleanly; returns within 2 s (golden rule: sources never hang)."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=STOP_JOIN_TIMEOUT_S)
            self._thread = None
        self._status = SourceStatus.STOPPED

    @property
    def provided_channels(self) -> list[str]:
        """All canonical channels, or the CSV's columns in replay mode."""
        if self._replay_rows is not None:
            provided = set()
            for _offset, values in self._replay_rows:
                provided.update(values)
            return sorted(provided)
        return sorted(CHANNELS)

    @property
    def status(self) -> SourceStatus:
        """Current connection status."""
        return self._status

    def _run(self) -> None:
        try:
            if self._replay_rows is not None:
                self._run_replay()
            else:
                self._run_simulation()
        except Exception:  # never raise into the main thread
            logger.exception("SimSource thread failed")
            self._status = SourceStatus.ERROR
        else:
            self._status = SourceStatus.STOPPED

    def _run_simulation(self) -> None:
        while not self._stop_event.is_set():
            for channel_id, value in self._simulation.step(self._tick_s).items():
                self._bus.publish(channel_id, value)
            self._stop_event.wait(self._tick_s)

    def _run_replay(self) -> None:
        elapsed = 0.0
        for offset, values in self._replay_rows:
            if self._stop_event.wait(max(0.0, offset - elapsed)):
                return
            elapsed = offset
            for channel_id, value in values.items():
                self._bus.publish(channel_id, value)


def _load_replay(path: Path) -> list[tuple[float, dict[str, float]]]:
    """Parse a replay CSV into (offset seconds, {channel: value}) rows."""
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if not header or header[0] != "timestamp":
            raise ValueError(f"{path}: first CSV column must be 'timestamp'")
        channel_ids = header[1:]
        unknown = [cid for cid in channel_ids if cid not in CHANNELS]
        if unknown:
            raise ValueError(f"{path}: unknown channels in header: {unknown}")
        rows = []
        previous_offset = 0.0
        for line_num, cells in enumerate(reader, start=2):
            if not cells:
                continue
            offset = float(cells[0])
            if offset < previous_offset:
                raise ValueError(f"{path}:{line_num}: timestamps must not decrease")
            previous_offset = offset
            values = {
                cid: float(cell)
                for cid, cell in zip(channel_ids, cells[1:], strict=False)
                if cell.strip()
            }
            rows.append((offset, values))
    if not rows:
        raise ValueError(f"{path}: no data rows")
    return rows
