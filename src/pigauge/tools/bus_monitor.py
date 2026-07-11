"""Terminal monitor: print live DataBus values from a SimSource.

Usage::

    python -m pigauge.tools.bus_monitor [--seed N] [--interval S]
                                        [--duration S] [--replay LOG.csv]

Prints a table of every canonical channel at each interval until
interrupted (Ctrl+C) or ``--duration`` elapses. Phase 1 acceptance tool.
"""

import argparse
import sys
import time

from pigauge.core.channels import CHANNELS
from pigauge.core.databus import DataBus, Reading
from pigauge.core.units import Quantity
from pigauge.sources.sim import SimSource

DEFAULT_SEED = 42
DEFAULT_INTERVAL_S = 0.5


def format_reading(reading: Reading | None, quantity: Quantity, unit: str) -> str:
    """One table cell: value with unit, or a placeholder before first data."""
    if reading is None:
        return "--"
    if quantity is Quantity.BOOLEAN:
        return "ON" if reading.value else "OFF"
    return f"{reading.value:8.1f} {unit}"


def render_table(bus: DataBus) -> str:
    """The full channel table for one refresh."""
    lines = [f"{'channel':<22} {'value':>14}  quality"]
    for channel_id, channel in sorted(CHANNELS.items()):
        reading = bus.get(channel_id)
        value_text = format_reading(reading, channel.quantity, channel.base_unit)
        quality = "NO_DATA" if reading is None else reading.quality.name
        lines.append(f"{channel_id:<22} {value_text:>14}  {quality}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Run the monitor loop; returns the process exit code."""
    parser = argparse.ArgumentParser(
        prog="bus_monitor", description="watch live simulated DataBus values"
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="simulation seed")
    parser.add_argument(
        "--interval", type=float, default=DEFAULT_INTERVAL_S, help="refresh period, seconds"
    )
    parser.add_argument(
        "--duration", type=float, default=None, help="stop after this many seconds"
    )
    parser.add_argument("--replay", default=None, metavar="LOG.csv", help="replay a CSV log")
    args = parser.parse_args(argv)

    bus = DataBus()
    try:
        source = SimSource(bus, seed=args.seed, replay_csv=args.replay)
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1

    source.start()
    end_time = None if args.duration is None else time.monotonic() + args.duration
    try:
        while end_time is None or time.monotonic() < end_time:
            print(f"\n-- bus @ {time.strftime('%H:%M:%S')} " + "-" * 24)
            print(render_table(bus))
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        source.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
