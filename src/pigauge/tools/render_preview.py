"""Render a gauge layout against simulated data to a PNG.

Usage::

    python -m pigauge.tools.render_preview --layout config/gauges/single_round_boost.yaml
           [--out frame.png] [--seed 42] [--sim-time 12] [--stale]

The DrivingSimulation is stepped deterministically to ``--sim-time`` and
the final values published, so the same seed and sim-time always produce
the same PNG — the property the golden-image tests rely on. ``--stale``
ages every reading past its stale_after to preview greyed rendering.
"""

import argparse
import sys
from pathlib import Path

from pigauge.core.channels import CHANNELS
from pigauge.core.config import ConfigError, load_gauge_layout
from pigauge.core.databus import DataBus
from pigauge.displays.virtual import VirtualDisplay
from pigauge.render.scene import GaugeScene
from pigauge.sources.sim import DrivingSimulation

DEFAULT_SEED = 42
DEFAULT_SIM_TIME_S = 12.0
SIM_TICK_HZ = 20.0
STALE_AGE_S = 120.0  # older than every channel's stale_after


class _FixedClock:
    """Bus clock pinned to a constant, so rendered quality is deterministic."""

    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def simulated_bus(seed: int, sim_time_s: float, stale: bool = False) -> DataBus:
    """A DataBus holding one deterministic simulation state.

    Values are published at t=0 and the clock pinned to t=0 (fresh) or
    t=STALE_AGE_S (everything stale) — no wall clock involved.
    """
    clock = _FixedClock(0.0)
    bus = DataBus(clock=clock)
    simulation = DrivingSimulation(seed)
    values: dict[str, float] = dict.fromkeys(CHANNELS, 0.0)
    for _ in range(int(sim_time_s * SIM_TICK_HZ)):
        values = simulation.step(1.0 / SIM_TICK_HZ)
    for channel_id, value in values.items():
        bus.publish(channel_id, value, timestamp=0.0)
    if stale:
        clock.now = STALE_AGE_S
    return bus


def main(argv: list[str] | None = None) -> int:
    """Render one layout to one PNG; returns the process exit code."""
    parser = argparse.ArgumentParser(
        prog="render_preview", description="render a layout + simulated data to PNG"
    )
    parser.add_argument("--layout", required=True, help="gauge layout YAML")
    parser.add_argument("--out", default=None, help="output PNG (default: <layout>_preview.png)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="simulation seed")
    parser.add_argument(
        "--sim-time", type=float, default=DEFAULT_SIM_TIME_S,
        help="seconds of driving cycle to simulate before the snapshot",
    )
    parser.add_argument("--stale", action="store_true", help="render everything stale/greyed")
    args = parser.parse_args(argv)

    out_path = Path(args.out) if args.out else Path(f"{Path(args.layout).stem}_preview.png")
    try:
        layout = load_gauge_layout(args.layout)
        scene = GaugeScene(layout, simulated_bus(args.seed, args.sim_time, stale=args.stale))
    except (ConfigError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1

    display = VirtualDisplay(scene.resolution, shape=layout.canvas.shape)
    display.show(scene.render())
    display.save(out_path)
    width, height = scene.resolution
    print(f"wrote {out_path} ({width}x{height}, seed={args.seed}, t={args.sim_time}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
