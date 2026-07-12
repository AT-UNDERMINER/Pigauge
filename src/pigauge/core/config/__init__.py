"""Config loading and validation: pydantic schemas for all PiGauge YAML.

Public API::

    from pigauge.core.config import (
        AppConfig, GaugeLayout, VehicleProfile,   # schemas
        load_app_config, load_gauge_layout, load_vehicle_profile,
        check_config, CheckResult,                # full-tree validation
        ConfigError,                              # the only error raised
    )
"""

from pigauge.core.config.errors import ConfigError
from pigauge.core.config.loader import (
    CheckResult,
    check_config,
    load_app_config,
    load_gauge_layout,
    load_vehicle_profile,
    resolve_config_path,
)
from pigauge.core.config.models import AppConfig, GaugeLayout, VehicleProfile

__all__ = [
    "AppConfig",
    "CheckResult",
    "ConfigError",
    "GaugeLayout",
    "VehicleProfile",
    "check_config",
    "load_app_config",
    "load_gauge_layout",
    "load_vehicle_profile",
    "resolve_config_path",
]
