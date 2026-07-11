"""Canonical channel registry: the universal join key of the system.

Channel IDs connect sources (who publish them), gauges (who subscribe),
alerts, and the logger. This registry must match the table in
docs/PROTOCOLS.md §Canonical channels exactly — the test suite parses that
table and fails on any drift.
"""

from dataclasses import dataclass

from pigauge.core.units import Quantity, base_unit


class UnknownChannelError(KeyError):
    """A channel ID that is not in the canonical registry."""

    def __init__(self, channel_id: str) -> None:
        """Record the offending ID with a pointer to the registry."""
        super().__init__(
            f"unknown channel {channel_id!r} (see pigauge.core.channels.CHANNELS)"
        )
        self.channel_id = channel_id


@dataclass(frozen=True)
class Channel:
    """One canonical data stream on the DataBus."""

    id: str
    quantity: Quantity
    stale_after: float
    """Seconds after which an unrefreshed reading is marked STALE."""

    @property
    def base_unit(self) -> str:
        """Base unit this channel's values are stored in (golden rule 6)."""
        return base_unit(self.quantity)


CHANNELS: dict[str, Channel] = {
    channel.id: channel
    for channel in (
        Channel("engine.rpm", Quantity.ROTATIONAL_SPEED, 0.5),
        Channel("vehicle.speed", Quantity.SPEED, 1.0),
        Channel("engine.coolant_temp", Quantity.TEMPERATURE, 5.0),
        Channel("engine.intake_temp", Quantity.TEMPERATURE, 5.0),
        Channel("engine.load", Quantity.RATIO, 1.0),
        Channel("engine.throttle", Quantity.RATIO, 0.5),
        Channel("engine.map", Quantity.PRESSURE, 0.5),
        Channel("boost.pressure", Quantity.PRESSURE, 0.5),
        Channel("oil.pressure", Quantity.PRESSURE, 1.0),
        Channel("exhaust.egt1", Quantity.TEMPERATURE, 1.0),
        Channel("fuel.level", Quantity.RATIO, 30.0),
        Channel("electrical.battery_v", Quantity.VOLTAGE, 5.0),
        Channel("ambient.baro", Quantity.PRESSURE, 60.0),
        Channel("system.ignition", Quantity.BOOLEAN, 1.0),
    )
}


def get_channel(channel_id: str) -> Channel:
    """Look up a channel, raising :class:`UnknownChannelError` if absent."""
    try:
        return CHANNELS[channel_id]
    except KeyError:
        raise UnknownChannelError(channel_id) from None
