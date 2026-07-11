"""Config loader tests: real repo configs validate; bad configs raise ConfigError."""

from pathlib import Path

import pytest

from pigauge.core.config import (
    ConfigError,
    check_config,
    load_app_config,
    load_gauge_layout,
    load_vehicle_profile,
)

REPO_ROOT = Path(__file__).parent.parent
CONFIG_DIR = REPO_ROOT / "config"


class TestRealConfigsValidate:
    """Every YAML shipped in config/ must pass validation (Phase 0 acceptance)."""

    @pytest.mark.parametrize("name", ["dev_sim.yaml", "default.yaml"])
    def test_app_config_valid(self, name):
        config = load_app_config(CONFIG_DIR / name)
        assert config.sources.sim.enabled
        assert config.displays[0].name == "boost_pod"
        assert config.displays[0].resolution == (240, 240)
        assert config.web.port == 8080

    def test_single_round_boost_layout(self):
        layout = load_gauge_layout(CONFIG_DIR / "gauges" / "single_round_boost.yaml")
        assert layout.canvas.shape == "round"
        assert (layout.canvas.width, layout.canvas.height) == (240, 240)
        assert len(layout.widgets) == 3
        assert layout.widgets[0].type == "arc_gauge"
        assert layout.widgets[0].channel == "boost.pressure"

    def test_dash_layout(self):
        layout = load_gauge_layout(CONFIG_DIR / "gauges" / "dash_800x480.yaml")
        assert layout.canvas.shape == "rect"
        assert (layout.canvas.width, layout.canvas.height) == (800, 480)
        assert len(layout.widgets) == 7
        assert {w.type for w in layout.widgets} == {"bar_gauge", "arc_gauge", "numeric_readout"}

    def test_generic_obd2_profile(self):
        profile = load_vehicle_profile(CONFIG_DIR / "vehicles" / "generic_obd2.yaml")
        assert profile.transport == "auto"
        assert profile.channels["engine.rpm"].pid == 0x0C
        assert profile.channels["engine.rpm"].rate_hz == 10

    def test_patrol_profile_inherits_generic_channels(self):
        profile = load_vehicle_profile(
            CONFIG_DIR / "vehicles" / "patrol_zd30_gu.yaml", base_dir=REPO_ROOT
        )
        assert profile.name.startswith("Nissan Patrol")
        assert profile.inherits is None  # resolved away by the loader
        assert profile.channels["engine.rpm"].pid == 0x0C
        assert len(profile.channels) >= 9

    def test_check_config_walks_whole_tree(self):
        result = check_config(CONFIG_DIR / "dev_sim.yaml", base_dir=REPO_ROOT)
        checked = {p.name for p in result.validated_files}
        assert checked == {"dev_sim.yaml", "generic_obd2.yaml", "single_round_boost.yaml"}


class TestInvalidConfigs:
    """Invalid input must raise ConfigError with file and field context."""

    def test_missing_file(self, tmp_path):
        with pytest.raises(ConfigError, match="file not found"):
            load_app_config(tmp_path / "nope.yaml")

    def test_yaml_syntax_error(self, tmp_path):
        bad = tmp_path / "broken.yaml"
        bad.write_text("displays: [unclosed", encoding="utf-8")
        with pytest.raises(ConfigError, match="YAML syntax error"):
            load_app_config(bad)

    def test_non_mapping_top_level(self, tmp_path):
        bad = tmp_path / "list.yaml"
        bad.write_text("- just\n- a\n- list\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="top level must be a mapping"):
            load_gauge_layout(bad)

    def test_unknown_key_reports_field_and_file(self, tmp_path):
        bad = tmp_path / "typo.yaml"
        bad.write_text(
            "name: X\ncanvas: {width: 10, height: 10, shape: rect}\n"
            "widgetz: []\n",
            encoding="utf-8",
        )
        with pytest.raises(ConfigError) as excinfo:
            load_gauge_layout(bad)
        message = str(excinfo.value)
        assert "typo.yaml" in message
        assert "widgetz" in message

    def test_bad_enum_value_reports_dotted_path(self, tmp_path):
        bad = tmp_path / "layout.yaml"
        bad.write_text(
            "name: X\ncanvas: {width: 240, height: 240, shape: hexagon}\n"
            "widgets: [{type: arc_gauge, position: {x: 0, y: 0}}]\n",
            encoding="utf-8",
        )
        with pytest.raises(ConfigError, match="canvas.shape"):
            load_gauge_layout(bad)

    def test_bad_background_colour(self, tmp_path):
        bad = tmp_path / "layout.yaml"
        bad.write_text(
            "name: X\ncanvas: {width: 240, height: 240, shape: round, background: blue}\n"
            "widgets: [{type: arc_gauge, position: {x: 0, y: 0}}]\n",
            encoding="utf-8",
        )
        with pytest.raises(ConfigError, match="canvas.background"):
            load_gauge_layout(bad)

    def test_alert_rule_without_thresholds(self, tmp_path):
        bad = tmp_path / "app.yaml"
        bad.write_text(
            "vehicle_profile: p.yaml\n"
            "displays: [{name: d, driver: virtual, resolution: [240, 240],"
            " shape: round, layout: l.yaml}]\n"
            "alerts: {rules: [{channel: engine.rpm, direction: above}]}\n",
            encoding="utf-8",
        )
        with pytest.raises(ConfigError, match="warn.*critical|critical.*warn"):
            load_app_config(bad)

    def test_zero_displays_rejected(self, tmp_path):
        bad = tmp_path / "app.yaml"
        bad.write_text("vehicle_profile: p.yaml\ndisplays: []\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="displays"):
            load_app_config(bad)

    def test_bad_poll_rate_reports_channel(self, tmp_path):
        bad = tmp_path / "profile.yaml"
        bad.write_text(
            "name: X\nchannels: {engine.rpm: {pid: 0x0C, rate_hz: 0}}\n",
            encoding="utf-8",
        )
        with pytest.raises(ConfigError, match="channels.engine.rpm.rate_hz"):
            load_vehicle_profile(bad)

    def test_inheritance_cycle_detected(self, tmp_path):
        a = tmp_path / "a.yaml"
        b = tmp_path / "b.yaml"
        a.write_text(f"name: A\ninherits: {b.as_posix()}\n", encoding="utf-8")
        b.write_text(f"name: B\ninherits: {a.as_posix()}\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="inheritance cycle"):
            load_vehicle_profile(a, base_dir=tmp_path)

    def test_check_config_catches_broken_referenced_layout(self, tmp_path):
        layout = tmp_path / "layout.yaml"
        layout.write_text("name: X\n", encoding="utf-8")  # missing canvas + widgets
        profile = tmp_path / "profile.yaml"
        profile.write_text("name: P\n", encoding="utf-8")
        app = tmp_path / "app.yaml"
        app.write_text(
            f"vehicle_profile: {profile.as_posix()}\n"
            f"displays: [{{name: d, driver: virtual, resolution: [240, 240],"
            f" shape: round, layout: {layout.as_posix()}}}]\n",
            encoding="utf-8",
        )
        with pytest.raises(ConfigError) as excinfo:
            check_config(app, base_dir=tmp_path)
        assert "layout.yaml" in str(excinfo.value)


class TestWidgetFlexibility:
    """Widget entries accept arbitrary extra parameters (config over code)."""

    def test_unknown_widget_params_allowed(self, tmp_path):
        layout_file = tmp_path / "layout.yaml"
        layout_file.write_text(
            "name: X\ncanvas: {width: 240, height: 240, shape: round}\n"
            "widgets: [{type: future_widget, position: {x: 5, y: 5},"
            " frobnication_level: 11}]\n",
            encoding="utf-8",
        )
        layout = load_gauge_layout(layout_file)
        assert layout.widgets[0].type == "future_widget"
        assert layout.widgets[0].model_extra["frobnication_level"] == 11
