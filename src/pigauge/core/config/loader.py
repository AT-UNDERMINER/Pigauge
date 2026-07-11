"""Load and validate PiGauge YAML configuration files.

Every loader raises :class:`ConfigError` (never a raw pydantic or YAML
exception) with the offending file and dotted field paths. Relative paths
found inside config files (``vehicle_profile``, display ``layout``, profile
``inherits``) are resolved against ``base_dir``, which defaults to the
current working directory — the project root in the documented quickstarts.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from pigauge.core.config.errors import ConfigError
from pigauge.core.config.models import AppConfig, GaugeLayout, VehicleProfile

ModelT = TypeVar("ModelT", bound=BaseModel)


def load_app_config(path: str | Path) -> AppConfig:
    """Load and validate a main application config (default.yaml shape)."""
    resolved = Path(path)
    return _validate(AppConfig, _read_yaml_mapping(resolved), resolved)


def load_gauge_layout(path: str | Path) -> GaugeLayout:
    """Load and validate a gauge layout (config/gauges/*.yaml shape)."""
    resolved = Path(path)
    return _validate(GaugeLayout, _read_yaml_mapping(resolved), resolved)


def load_vehicle_profile(path: str | Path, base_dir: str | Path | None = None) -> VehicleProfile:
    """Load a vehicle profile, resolving its ``inherits`` chain.

    Parent profiles are merged underneath the child (child keys win;
    nested mappings such as ``channels`` merge recursively). Inheritance
    cycles raise :class:`ConfigError`.
    """
    base = Path(base_dir) if base_dir is not None else Path.cwd()
    data = _read_profile_chain(Path(path), base, seen=[])
    data.pop("inherits", None)
    return _validate(VehicleProfile, data, path)


@dataclass
class CheckResult:
    """Outcome of a full-tree config check."""

    app_config: AppConfig
    validated_files: list[Path] = field(default_factory=list)


def check_config(path: str | Path, base_dir: str | Path | None = None) -> CheckResult:
    """Validate a main config plus every file it references.

    Loads the app config, then its vehicle profile and each display's
    gauge layout. Raises :class:`ConfigError` on the first invalid file.
    """
    base = Path(base_dir) if base_dir is not None else Path.cwd()
    app_path = _resolve(path, base)
    app_config = load_app_config(app_path)
    checked = [app_path]

    profile_path = _resolve(app_config.vehicle_profile, base)
    load_vehicle_profile(profile_path, base_dir=base)
    checked.append(profile_path)

    for display in app_config.displays:
        layout_path = _resolve(display.layout, base)
        load_gauge_layout(layout_path)
        checked.append(layout_path)

    return CheckResult(app_config=app_config, validated_files=checked)


def _resolve(path: str | Path, base_dir: Path) -> Path:
    """Resolve a possibly-relative config path against the project root."""
    candidate = Path(path)
    return candidate if candidate.is_absolute() else base_dir / candidate


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    """Read a YAML file that must contain a top-level mapping."""
    if not path.is_file():
        raise ConfigError(path, "file not found")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(path, f"YAML syntax error: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(path, "top level must be a mapping")
    return data


def _read_profile_chain(path: Path, base_dir: Path, seen: list[Path]) -> dict[str, Any]:
    """Read a profile and fold in its parents, detecting cycles."""
    marker = path.resolve() if path.exists() else path
    if marker in seen:
        chain = " -> ".join(str(p) for p in [*seen, marker])
        raise ConfigError(path, f"inheritance cycle: {chain}")
    data = _read_yaml_mapping(path)
    parent_ref = data.get("inherits")
    if parent_ref is None:
        return data
    parent_path = _resolve(parent_ref, base_dir)
    parent = _read_profile_chain(parent_path, base_dir, [*seen, marker])
    return _merge_mappings(parent, data)


def _merge_mappings(parent: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge two mappings; child values win, nested dicts merge."""
    merged = dict(parent)
    for key, value in child.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_mappings(merged[key], value)
        else:
            merged[key] = value
    return merged


def _validate(model: type[ModelT], data: dict[str, Any], path: str | Path) -> ModelT:
    """Validate ``data`` against ``model``, converting errors to ConfigError."""
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(path, _format_errors(exc)) from exc


def _format_errors(exc: ValidationError) -> list[str]:
    """Turn pydantic errors into ``dotted.field.path: message`` strings."""
    problems = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "<root>"
        problems.append(f"{location}: {error['msg']}")
    return problems
