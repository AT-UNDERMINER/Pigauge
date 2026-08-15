"""Turn a validated vehicle profile into a poll plan.

The vehicle profile YAML (config/vehicles/*.yaml) is the single place that
decides *which* PIDs a vehicle is polled for and *how often*; this module
converts those entries into :class:`PollEntry` objects carrying the
decoder from the standard table. Sources consume the plan and never look
at PIDs themselves (CLAUDE.md golden rule 7).

Profile faults are raised as :class:`ConfigError` so a bad profile fails
fast at startup with a readable message rather than mid-drive.
"""

from dataclasses import dataclass

from pigauge.core.channels import UnknownChannelError, get_channel
from pigauge.core.config.errors import ConfigError
from pigauge.core.config.models import VehicleProfile
from pigauge.sources.obd_pids import PidDecoder, UnknownPidError, decoder_for_pid

PROFILE_SOURCE_LABEL = "<vehicle profile>"


@dataclass(frozen=True)
class PollEntry:
    """One channel to poll: its PID, rate, and decoder."""

    channel_id: str
    pid: int
    rate_hz: float
    decoder: PidDecoder

    @property
    def period_s(self) -> float:
        """Seconds between polls of this channel."""
        return 1.0 / self.rate_hz


def build_poll_plan(
    profile: VehicleProfile, source: str = PROFILE_SOURCE_LABEL
) -> list[PollEntry]:
    """Build the poll plan for ``profile``, fastest channels first.

    Every entry is checked against the canonical channel registry and the
    standard decode table, including that the profile's PID is the one
    that actually carries that channel — a profile claiming
    ``engine.rpm: {pid: 0x0D}`` is a config bug, not a decode surprise.
    """
    entries = []
    problems = []
    for channel_id, poll in profile.channels.items():
        try:
            entries.append(_build_entry(channel_id, poll.pid, poll.rate_hz))
        except ConfigError as error:
            problems.extend(error.problems)
    if problems:
        raise ConfigError(source, problems)
    return sorted(entries, key=lambda entry: (-entry.rate_hz, entry.channel_id))


def _build_entry(channel_id: str, pid: int, rate_hz: float) -> PollEntry:
    """Validate one profile channel entry and pair it with its decoder."""
    field = f"channels.{channel_id}"
    try:
        get_channel(channel_id)
    except UnknownChannelError:
        raise ConfigError(
            PROFILE_SOURCE_LABEL, f"{field}: not a canonical channel (core/channels.py)"
        ) from None
    try:
        decoder = decoder_for_pid(pid)
    except UnknownPidError:
        raise ConfigError(
            PROFILE_SOURCE_LABEL,
            f"{field}.pid: 0x{pid:02X} has no standard mode 01 decode "
            "(docs/PROTOCOLS.md); manufacturer-specific PIDs arrive in Phase 9",
        ) from None
    if decoder.channel_id != channel_id:
        raise ConfigError(
            PROFILE_SOURCE_LABEL,
            f"{field}.pid: 0x{pid:02X} decodes to {decoder.channel_id!r}, not {channel_id!r}",
        )
    return PollEntry(channel_id, pid, rate_hz, decoder)
