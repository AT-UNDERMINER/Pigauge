"""PiGauge entry point.

Phase 0 implements: --check-config. Later phases grow this into the full
application bootstrap (load config -> build sources/displays -> run loops).
"""

import argparse
import sys

from pigauge.core.config import ConfigError, check_config

DEFAULT_CONFIG = "config/default.yaml"


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch; returns the process exit code."""
    parser = argparse.ArgumentParser(prog="pigauge", description="PiGauge digital gauge system")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="main config YAML")
    parser.add_argument(
        "--check-config",
        nargs="?",
        const="",
        default=None,
        metavar="PATH",
        help="validate a config file (defaults to --config) and exit",
    )
    args = parser.parse_args(argv)

    if args.check_config is not None:
        return run_config_check(args.check_config or args.config)

    print("PiGauge: application bootstrap arrives in Phase 1 (docs/ROADMAP.md).")
    print(f"Use --check-config to validate configuration (default: {DEFAULT_CONFIG}).")
    return 0


def run_config_check(path: str) -> int:
    """Validate ``path`` plus every config file it references; report and exit."""
    try:
        result = check_config(path)
    except ConfigError as error:
        print(error, file=sys.stderr)
        return 1
    for validated_file in result.validated_files:
        print(f"OK  {validated_file}")
    print(f"Config valid: {len(result.validated_files)} file(s) checked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
