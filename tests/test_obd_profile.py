"""Poll plans built from vehicle profile YAML (no PIDs hard-coded in sources)."""

import pytest

from pigauge.core.config.errors import ConfigError
from pigauge.core.config.loader import load_vehicle_profile
from pigauge.core.config.models import ChannelPollConfig, VehicleProfile
from pigauge.sources.obd_profile import build_poll_plan

GENERIC_PROFILE = "config/vehicles/generic_obd2.yaml"
PATROL_PROFILE = "config/vehicles/patrol_zd30_gu.yaml"


def profile_with(channels: dict[str, dict]) -> VehicleProfile:
    """Build an in-memory profile from raw channel entries."""
    return VehicleProfile(
        name="test",
        channels={cid: ChannelPollConfig(**entry) for cid, entry in channels.items()},
    )


class TestShippedProfiles:
    def test_generic_profile_builds_a_plan(self):
        plan = build_poll_plan(load_vehicle_profile(GENERIC_PROFILE))
        assert {entry.channel_id for entry in plan} == {
            "engine.rpm",
            "engine.map",
            "vehicle.speed",
            "engine.throttle",
            "engine.load",
            "engine.coolant_temp",
            "engine.intake_temp",
            "ambient.baro",
            "electrical.battery_v",
        }

    def test_patrol_stub_inherits_a_valid_plan(self):
        # The stub must stay loadable while its real PID set is unscanned.
        assert build_poll_plan(load_vehicle_profile(PATROL_PROFILE))

    def test_fast_channels_lead_the_plan(self):
        plan = build_poll_plan(load_vehicle_profile(GENERIC_PROFILE))
        assert plan[0].rate_hz >= plan[-1].rate_hz
        assert plan[0].channel_id in {"engine.rpm", "engine.map"}

    def test_rates_meet_the_claude_md_budget(self):
        plan = {e.channel_id: e.rate_hz for e in build_poll_plan(load_vehicle_profile(
            GENERIC_PROFILE))}
        assert plan["engine.rpm"] >= 10  # fast channels >= 10 Hz on CAN
        assert plan["engine.map"] >= 10
        assert plan["engine.coolant_temp"] >= 1  # slow channels >= 1 Hz


class TestPollEntry:
    def test_period_is_the_inverse_rate(self):
        entry = build_poll_plan(profile_with({"engine.rpm": {"pid": 0x0C, "rate_hz": 10}}))[0]
        assert entry.period_s == pytest.approx(0.1)

    def test_entry_carries_its_decoder(self):
        entry = build_poll_plan(profile_with({"engine.rpm": {"pid": 0x0C, "rate_hz": 10}}))[0]
        assert entry.decoder.decode(b"\x1a\xf8") == pytest.approx(1726.0)


class TestProfileFaults:
    def test_pid_that_decodes_to_another_channel_rejected(self):
        with pytest.raises(ConfigError, match="decodes to 'vehicle.speed'"):
            build_poll_plan(profile_with({"engine.rpm": {"pid": 0x0D, "rate_hz": 10}}))

    def test_non_standard_pid_points_at_phase_9(self):
        with pytest.raises(ConfigError, match="Phase 9"):
            build_poll_plan(profile_with({"engine.rpm": {"pid": 0x99, "rate_hz": 10}}))

    def test_unknown_channel_rejected(self):
        profile = VehicleProfile(name="test")
        profile.channels["engine.turbo_speed"] = ChannelPollConfig(pid=0x0C, rate_hz=1)
        with pytest.raises(ConfigError, match="not a canonical channel"):
            build_poll_plan(profile)

    def test_all_faults_reported_together(self):
        with pytest.raises(ConfigError) as caught:
            build_poll_plan(profile_with({
                "engine.rpm": {"pid": 0x0D, "rate_hz": 10},
                "vehicle.speed": {"pid": 0x99, "rate_hz": 5},
            }))
        assert len(caught.value.problems) == 2

    def test_error_names_the_profile(self):
        with pytest.raises(ConfigError, match="patrol.yaml"):
            build_poll_plan(
                profile_with({"engine.rpm": {"pid": 0x99, "rate_hz": 10}}), source="patrol.yaml"
            )

    def test_empty_profile_gives_an_empty_plan(self):
        assert build_poll_plan(VehicleProfile(name="empty")) == []
