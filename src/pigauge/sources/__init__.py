"""Source registry: config selects the vehicle link by name (golden rule 3).

The core never imports a concrete vehicle driver; it asks for whatever the
vehicle profile and app config between them select. The profile says what
the *vehicle* speaks (``transport: auto | can | elm327``) and the app
config says which links are *fitted and enabled*, so a source is built
only when both agree.

A disabled link is an operator decision, not an error: if the profile
names a transport that is switched off, the mismatch is logged and no
source is built (the simulator or analog sources may still be running).
"""

import logging

from pigauge.core.config.models import SourcesConfig, VehicleProfile
from pigauge.core.databus import DataBus
from pigauge.sources.base import Source, SourceStatus
from pigauge.sources.can_socketcan import create_can_source
from pigauge.sources.elm327 import create_elm327_source

logger = logging.getLogger(__name__)

__all__ = [
    "AUTO_TRANSPORT_PREFERENCE",
    "Source",
    "SourceStatus",
    "create_vehicle_source",
    "select_transport",
]

AUTO_TRANSPORT_PREFERENCE = ("can", "elm327")
"""With ``transport: auto`` and both fitted, CAN wins: it polls faster
than an ELM327 adapter (docs/PROTOCOLS.md, CLAUDE.md poll budgets)."""


def select_transport(profile: VehicleProfile, config: SourcesConfig) -> str | None:
    """Name the vehicle link to build, or None when none is available."""
    enabled = [name for name in AUTO_TRANSPORT_PREFERENCE if getattr(config, name).enabled]
    if profile.transport != "auto":
        if profile.transport in enabled:
            return profile.transport
        logger.warning(
            "vehicle profile requests transport %r but it is disabled in config; "
            "no vehicle source will run",
            profile.transport,
        )
        return None
    return enabled[0] if enabled else None


def create_vehicle_source(
    bus: DataBus,
    profile: VehicleProfile,
    config: SourcesConfig,
    *,
    profile_source: str = "<vehicle profile>",
) -> Source | None:
    """Build the vehicle source selected by the profile and app config."""
    transport = select_transport(profile, config)
    if transport is None:
        return None
    if transport == "can":
        return create_can_source(
            bus, profile, interface=config.can.interface, profile_source=profile_source
        )
    return create_elm327_source(
        bus,
        profile,
        port=config.elm327.port,
        baudrate=config.elm327.baudrate,
        profile_source=profile_source,
    )
