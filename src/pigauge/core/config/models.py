"""Pydantic schemas for the three PiGauge YAML document types.

- :class:`AppConfig` — config/default.yaml, config/dev_sim.yaml (hardware map
  and runtime settings)
- :class:`GaugeLayout` — config/gauges/*.yaml (canvas plus widget list)
- :class:`VehicleProfile` — config/vehicles/*.yaml (transport and PID map)

Schema philosophy: known sections reject unknown keys so typos fail fast,
while widget entries allow extra keys because widget parameters are
config-driven by design (CLAUDE.md golden rule 7). Pin numbers and bus
settings here mirror docs/HARDWARE.md, which is authoritative.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

HEX_COLOR_PATTERN = r"^#[0-9a-fA-F]{6}$"
DEFAULT_SHUTDOWN_GRACE_S = 15.0
DEFAULT_WEB_PORT = 8080
DEFAULT_TARGET_FPS = 30


class StrictModel(BaseModel):
    """Base for schemas that reject unknown keys, catching config typos early."""

    model_config = ConfigDict(extra="forbid")


class CanSourceConfig(StrictModel):
    """socketcan/MCP2515 vehicle link (Phase 4)."""

    enabled: bool = False
    interface: str = "can0"


class Elm327SourceConfig(StrictModel):
    """ELM327/STN serial vehicle link (Phase 4)."""

    enabled: bool = False
    port: str = "/dev/ttyUSB0"
    baudrate: int = Field(default=38400, gt=0)


class TransferConfig(BaseModel):
    """Voltage to engineering-unit transfer function (linear or table)."""

    model_config = ConfigDict(extra="allow")

    type: str


class FilterConfig(BaseModel):
    """Per-channel smoothing filter (e.g. ema, median)."""

    model_config = ConfigDict(extra="allow")

    type: str


class AdsChannelConfig(StrictModel):
    """One ADS1115 input bound to a DataBus channel."""

    adc_channel: int = Field(ge=0, le=3)
    transfer: TransferConfig
    filter: FilterConfig | None = None


class Ads1115SourceConfig(StrictModel):
    """I2C analog sensor source (Phase 5)."""

    enabled: bool = False
    i2c_bus: int = Field(default=1, ge=0)
    address: int = Field(default=0x48, ge=0)
    channels: dict[str, AdsChannelConfig] = Field(default_factory=dict)


class Max31856SourceConfig(StrictModel):
    """SPI thermocouple (EGT) source (Phase 5)."""

    enabled: bool = False
    spi_bus: int = Field(default=1, ge=0)
    cs_pin: int | None = None
    channel: str = "exhaust.egt1"
    tc_type: str = "K"


class SimSourceConfig(StrictModel):
    """Deterministic simulator source for development (Phase 1)."""

    enabled: bool = True
    seed: int = 0


class SourcesConfig(StrictModel):
    """All configurable data sources; each defaults to disabled except sim."""

    can: CanSourceConfig = Field(default_factory=CanSourceConfig)
    elm327: Elm327SourceConfig = Field(default_factory=Elm327SourceConfig)
    ads1115: Ads1115SourceConfig = Field(default_factory=Ads1115SourceConfig)
    max31856: Max31856SourceConfig = Field(default_factory=Max31856SourceConfig)
    sim: SimSourceConfig = Field(default_factory=SimSourceConfig)


class DisplayConfig(StrictModel):
    """One physical or virtual display bound to a gauge layout file."""

    name: str
    driver: str
    resolution: tuple[int, int]
    shape: Literal["round", "rect"]
    layout: str
    spi_bus: int | None = None
    cs_pin: int | None = None
    dc_pin: int | None = None
    rst_pin: int | None = None
    backlight_pin: int | None = None
    spi_hz: int | None = Field(default=None, gt=0)
    rotation: int = 0

    @field_validator("resolution")
    @classmethod
    def _resolution_positive(cls, value: tuple[int, int]) -> tuple[int, int]:
        if value[0] <= 0 or value[1] <= 0:
            raise ValueError("resolution dimensions must be positive")
        return value


class AlertQualifier(StrictModel):
    """Secondary condition gating a rule (e.g. oil pressure only above idle)."""

    channel: str
    above: float | None = None
    below: float | None = None

    @model_validator(mode="after")
    def _require_bound(self) -> "AlertQualifier":
        if self.above is None and self.below is None:
            raise ValueError("qualifier needs at least one of 'above' or 'below'")
        return self


class AlertRule(StrictModel):
    """Threshold rule with hysteresis; values are in channel base units."""

    channel: str
    warn: float | None = None
    critical: float | None = None
    direction: Literal["above", "below"]
    hysteresis: float = Field(default=0.0, ge=0)
    qualifier: AlertQualifier | None = None

    @model_validator(mode="after")
    def _require_threshold(self) -> "AlertRule":
        if self.warn is None and self.critical is None:
            raise ValueError("alert rule needs at least one of 'warn' or 'critical'")
        return self


class AlertsConfig(StrictModel):
    """Alert engine settings (Phase 6)."""

    buzzer_pin: int | None = None
    rules: list[AlertRule] = Field(default_factory=list)


class LoggingConfig(StrictModel):
    """SQLite session logging settings (Phase 6)."""

    enabled: bool = False
    db_path: str = "data/pigauge.sqlite"
    max_size_mb: int = Field(default=512, gt=0)


class SystemConfig(StrictModel):
    """Ignition sensing and safe-shutdown settings (Phase 7)."""

    ignition_pin: int | None = None
    shutdown_grace_s: float = Field(default=DEFAULT_SHUTDOWN_GRACE_S, ge=0)


class WebConfig(StrictModel):
    """Web UI settings (Phase 8)."""

    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = Field(default=DEFAULT_WEB_PORT, ge=1, le=65535)


class RenderConfig(StrictModel):
    """Render loop settings."""

    target_fps: int = Field(default=DEFAULT_TARGET_FPS, gt=0)
    fps_overlay: bool = False
    """Debug flag: draw the achieved FPS onto every frame (Phase 3)."""


class AppConfig(StrictModel):
    """Top-level schema for config/default.yaml and variants."""

    vehicle_profile: str
    displays: list[DisplayConfig] = Field(min_length=1)
    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    alerts: AlertsConfig = Field(default_factory=AlertsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    system: SystemConfig = Field(default_factory=SystemConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    render: RenderConfig = Field(default_factory=RenderConfig)


class CanvasConfig(StrictModel):
    """Layout canvas: size, shape, and background colour."""

    width: int = Field(gt=0)
    height: int = Field(gt=0)
    shape: Literal["round", "rect"]
    background: str = Field(default="#000000", pattern=HEX_COLOR_PATTERN)


class WidgetPosition(StrictModel):
    """Widget anchor point in canvas pixel coordinates."""

    x: int
    y: int


class WidgetConfig(BaseModel):
    """One widget entry in a layout.

    Extra keys are allowed by design: widget-specific parameters (radius,
    sweep, range, colours, ...) are interpreted by the widget class in the
    render layer, so new parameters must not require schema changes.
    """

    model_config = ConfigDict(extra="allow")

    type: str
    position: WidgetPosition
    channel: str | None = None
    display_unit: str | None = None


class GaugeLayout(StrictModel):
    """Top-level schema for config/gauges/*.yaml."""

    name: str
    canvas: CanvasConfig
    widgets: list[WidgetConfig] = Field(min_length=1)


class CanProfileConfig(StrictModel):
    """CAN transport parameters for a vehicle (ISO 15765-4)."""

    bitrate: int = Field(default=500000, gt=0)
    request_id: int = Field(default=0x7DF, ge=0)
    response_ids: list[int] = Field(default_factory=lambda: [0x7E8])


class Elm327ProfileConfig(StrictModel):
    """ELM327 transport parameters for a vehicle."""

    batch_pids: bool = False


class ChannelPollConfig(StrictModel):
    """PID and poll rate for one channel (docs/PROTOCOLS.md)."""

    pid: int = Field(ge=0, le=0xFF)
    rate_hz: float = Field(gt=0)


class VehicleProfile(StrictModel):
    """Top-level schema for config/vehicles/*.yaml.

    ``inherits`` names a parent profile file; the loader merges the parent
    underneath this profile before validation, so an already-validated
    profile never carries an unresolved ``inherits``.
    """

    name: str
    transport: Literal["auto", "can", "elm327"] = "auto"
    inherits: str | None = None
    can: CanProfileConfig | None = None
    elm327: Elm327ProfileConfig | None = None
    channels: dict[str, ChannelPollConfig] = Field(default_factory=dict)
