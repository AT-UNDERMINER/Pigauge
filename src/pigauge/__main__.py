"""PiGauge entry point.

Phase 0 implements: --check-config. Later phases grow this into the full
application bootstrap (load config -> build sources/displays -> run loops).
"""

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(prog="pigauge", description="PiGauge digital gauge system")
    parser.add_argument("--config", default="config/default.yaml")
    parser.add_argument("--check-config", action="store_true", help="validate config and exit")
    parser.parse_args()
    print("PiGauge scaffold — implementation starts at Phase 0 (docs/ROADMAP.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
