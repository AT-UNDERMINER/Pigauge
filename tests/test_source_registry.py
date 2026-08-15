"""Vehicle link selection from profile transport plus app config."""

import pytest

from pigauge.core.config.loader import load_app_config, load_vehicle_profile
from pigauge.core.config.models import (
    CanSourceConfig,
    Elm327SourceConfig,
    SourcesConfig,
    VehicleProfile,
)
from pigauge.core.databus import DataBus
from pigauge.sources import create_vehicle_source, select_transport

GENERIC_PROFILE = "config/vehicles/generic_obd2.yaml"
DEV_SIM_CONFIG = "config/dev_sim.yaml"
DEFAULT_CONFIG = "config/default.yaml"


def sources(can=False, elm327=False) -> SourcesConfig:
    return SourcesConfig(
        can=CanSourceConfig(enabled=can, interface="can1"),
        elm327=Elm327SourceConfig(enabled=elm327, port="/dev/ttyUSB9", baudrate=115200),
    )


def profile(transport="auto") -> VehicleProfile:
    return VehicleProfile(name="test", transport=transport)


class TestSelection:
    def test_nothing_enabled_selects_nothing(self):
        assert select_transport(profile(), sources()) is None

    def test_only_can_enabled(self):
        assert select_transport(profile(), sources(can=True)) == "can"

    def test_only_elm327_enabled(self):
        assert select_transport(profile(), sources(elm327=True)) == "elm327"

    def test_auto_prefers_can_when_both_are_fitted(self):
        assert select_transport(profile(), sources(can=True, elm327=True)) == "can"

    def test_profile_can_overrides_the_auto_preference(self):
        chosen = select_transport(profile("elm327"), sources(can=True, elm327=True))
        assert chosen == "elm327"

    def test_profile_transport_that_is_disabled_selects_nothing(self):
        assert select_transport(profile("can"), sources(elm327=True)) is None

    def test_disabled_profile_transport_is_logged(self, caplog):
        select_transport(profile("can"), sources(elm327=True))
        assert "disabled in config" in caplog.text


class TestSourceConstruction:
    def test_no_source_when_no_link_is_enabled(self):
        assert create_vehicle_source(DataBus(), profile(), sources()) is None

    def test_can_source_takes_its_interface_from_config(self):
        source = create_vehicle_source(
            DataBus(), load_vehicle_profile(GENERIC_PROFILE), sources(can=True)
        )
        assert source._transport.name == "can"
        assert source._transport._interface == "can1"

    def test_elm327_source_takes_its_port_from_config(self):
        source = create_vehicle_source(
            DataBus(), load_vehicle_profile(GENERIC_PROFILE), sources(elm327=True)
        )
        assert source._transport.name == "elm327"
        assert source._transport._port == "/dev/ttyUSB9"
        assert source._transport._baudrate == 115200

    def test_source_publishes_the_profile_channels(self):
        source = create_vehicle_source(
            DataBus(), load_vehicle_profile(GENERIC_PROFILE), sources(can=True)
        )
        assert "engine.rpm" in source.provided_channels

    def test_batch_flag_reaches_the_elm327_transport(self):
        source = create_vehicle_source(
            DataBus(), load_vehicle_profile(GENERIC_PROFILE), sources(elm327=True)
        )
        assert source._transport.max_pids_per_request > 1  # generic profile batches


class TestShippedConfigs:
    def test_dev_sim_runs_without_a_vehicle_link(self):
        config = load_app_config(DEV_SIM_CONFIG)
        profile_ = load_vehicle_profile(config.vehicle_profile)
        assert create_vehicle_source(DataBus(), profile_, config.sources) is None

    def test_default_config_has_both_links_off_until_the_pi(self):
        config = load_app_config(DEFAULT_CONFIG)
        assert config.sources.can.enabled is False
        assert config.sources.elm327.enabled is False

    def test_enabling_can_in_the_default_config_builds_a_source(self):
        config = load_app_config(DEFAULT_CONFIG)
        config.sources.can.enabled = True
        profile_ = load_vehicle_profile(config.vehicle_profile)
        source = create_vehicle_source(DataBus(), profile_, config.sources)
        assert source is not None
        assert source._transport._interface == "can0"


@pytest.mark.parametrize("transport", ["can", "elm327"])
def test_source_never_opens_hardware_at_construction(transport):
    """Building a source must not touch the bus or port — start() does that."""
    source = create_vehicle_source(
        DataBus(),
        load_vehicle_profile(GENERIC_PROFILE),
        sources(**{transport: True}),
    )
    assert source.status.name == "STOPPED"
