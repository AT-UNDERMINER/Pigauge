"""bus_monitor smoke tests (Phase 1 acceptance: prints live values)."""

from pigauge.core.channels import CHANNELS
from pigauge.tools.bus_monitor import main


def test_monitor_prints_every_channel_and_exits_zero(capsys):
    assert main(["--duration", "0.6", "--interval", "0.2", "--seed", "7"]) == 0
    output = capsys.readouterr().out
    for channel_id in CHANNELS:
        assert channel_id in output
    assert "OK" in output  # live values arrived within the run


def test_monitor_replay_mode(tmp_path, capsys):
    log = tmp_path / "log.csv"
    log.write_text("timestamp,engine.rpm\n0.0,1234\n", encoding="utf-8")
    assert main(["--replay", str(log), "--duration", "0.3", "--interval", "0.1"]) == 0
    assert "1234.0" in capsys.readouterr().out


def test_monitor_bad_replay_file_exits_one(tmp_path, capsys):
    missing = tmp_path / "nope.csv"
    assert main(["--replay", str(missing), "--duration", "0.1"]) == 1
    assert "nope.csv" in capsys.readouterr().err
