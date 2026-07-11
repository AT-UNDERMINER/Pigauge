"""--check-config CLI tests (Phase 0 acceptance: validates and exits)."""

import subprocess
import sys
from pathlib import Path

import pytest

from pigauge.__main__ import main

REPO_ROOT = Path(__file__).parent.parent


@pytest.fixture(autouse=True)
def run_from_repo_root(monkeypatch):
    """Config paths inside YAML are project-root relative; pin the cwd."""
    monkeypatch.chdir(REPO_ROOT)


def test_check_config_dev_sim_exits_zero(capsys):
    assert main(["--check-config", "config/dev_sim.yaml"]) == 0
    output = capsys.readouterr().out
    assert "dev_sim.yaml" in output
    assert "Config valid: 3 file(s) checked." in output


def test_check_config_bare_flag_uses_config_option(capsys):
    assert main(["--check-config"]) == 0
    assert "default.yaml" in capsys.readouterr().out


def test_check_config_missing_file_exits_one(capsys):
    assert main(["--check-config", "config/nonexistent.yaml"]) == 1
    error_output = capsys.readouterr().err
    assert "nonexistent.yaml" in error_output
    assert "file not found" in error_output


def test_check_config_invalid_field_exits_one(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("vehicle_profile: p.yaml\ndisplays: []\n", encoding="utf-8")
    assert main(["--check-config", str(bad)]) == 1
    error_output = capsys.readouterr().err
    assert "bad.yaml" in error_output
    assert "displays" in error_output


def test_module_invocation_matches_roadmap_command():
    """`python -m pigauge --check-config config/dev_sim.yaml` validates and exits."""
    completed = subprocess.run(
        [sys.executable, "-m", "pigauge", "--check-config", "config/dev_sim.yaml"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Config valid" in completed.stdout


def test_no_arguments_still_exits_zero(capsys):
    assert main([]) == 0
    assert "Phase 1" in capsys.readouterr().out
