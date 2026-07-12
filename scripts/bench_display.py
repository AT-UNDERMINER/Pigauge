"""Benchmark achieved FPS per configured display.

Runs the real render loop against live simulated data and reports what
each display actually achieved. Run uncapped (default) to measure
throughput against the Phase 3 budgets, or pass --target-fps to observe
paced behaviour:

    python scripts/bench_display.py --config config/dev_sim.yaml --seconds 5

Budgets on the Pi Zero 2 W (CLAUDE.md): GC9A01 >= 25 FPS (>= 15 with two),
HDMI >= 30 FPS.
"""

import argparse
import sys
from pathlib import Path

from pigauge.core.config import ConfigError, load_app_config
from pigauge.core.databus import DataBus
from pigauge.render.loop import RenderLoop, bindings_from_config
from pigauge.sources.sim import SimSource

DEFAULT_SECONDS = 5.0


def main(argv: list[str] | None = None) -> int:
    """Render every configured display flat-out and report FPS."""
    parser = argparse.ArgumentParser(
        prog="bench_display", description="report achieved FPS per display"
    )
    parser.add_argument("--config", default="config/default.yaml", help="main config YAML")
    parser.add_argument("--seconds", type=float, default=DEFAULT_SECONDS, help="bench duration")
    parser.add_argument(
        "--target-fps", type=float, default=None,
        help="pace the loop instead of running uncapped",
    )
    parser.add_argument("--fps-overlay", action="store_true", help="stamp FPS onto frames")
    args = parser.parse_args(argv)

    try:
        config = load_app_config(args.config)
        bus = DataBus()
        bindings = bindings_from_config(config, bus, base_dir=Path.cwd())
    except (ConfigError, ValueError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1

    source = SimSource(bus, seed=config.sources.sim.seed)
    source.start()
    loop = RenderLoop(
        bindings,
        target_fps=args.target_fps,
        fps_overlay=args.fps_overlay or config.render.fps_overlay,
    )
    try:
        loop.run(duration_s=args.seconds)
    finally:
        source.stop()
        for binding in bindings:
            binding.display.close()

    mode = "uncapped" if args.target_fps is None else f"paced to {args.target_fps} FPS"
    print(f"\nbench: {args.seconds:.1f}s per display, {mode}")
    print(f"{'display':<16} {'driver':<14} {'frames':>7} {'avg FPS':>9}")
    for binding in bindings:
        frames = loop.frame_counts[binding.name]
        average = frames / args.seconds
        driver_name = type(binding.display).__name__
        print(f"{binding.name:<16} {driver_name:<14} {frames:>7} {average:>9.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
