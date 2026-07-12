"""bench_display.py smoke test (dev machine: virtual display only)."""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def test_bench_reports_fps_for_configured_displays():
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/bench_display.py",
            "--config", "config/dev_sim.yaml",
            "--seconds", "0.5",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert "boost_pod" in completed.stdout
    assert "VirtualDisplay" in completed.stdout
    assert "avg FPS" in completed.stdout


def test_bench_bad_config_exits_one():
    completed = subprocess.run(
        [sys.executable, "scripts/bench_display.py", "--config", "config/nope.yaml",
         "--seconds", "0.1"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 1
    assert "nope.yaml" in completed.stderr
