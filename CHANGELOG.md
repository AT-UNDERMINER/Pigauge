# Changelog

## Unreleased

### Phase 1 — Core: DataBus, channels, units, simulator (complete)
- `core/units.py`: base units per quantity (kPa, °C, km/h, RPM, %, V) and
  affine conversions for psi, bar, °F, mph; hypothesis property tests
  round-trip every convertible unit pair.
- `core/channels.py`: canonical registry of all 14 channels (id, quantity,
  stale_after); a test parses docs/PROTOCOLS.md and enforces exact parity.
- `core/databus.py`: thread-safe publish/get/subscribe behind an RLock;
  get() computes OK/STALE from the channel's stale_after with an
  injectable clock; subscriber exceptions are logged, never raised into
  source threads. Concurrency test races a publisher thread with a reader.
- `sources/sim.py`: DrivingSimulation (seeded, deterministic idle → accel
  → cruise cycles across every channel) wrapped by SimSource, which also
  replays a `timestamp,<channel>,...` CSV log at real-time speed.
- `tools/bus_monitor.py`: `python -m pigauge.tools.bus_monitor` prints
  live simulated (or replayed) values with quality per channel.
- Added `hypothesis` to the dev extras.

### Phase 0 — Scaffold & tooling (complete)
- Pydantic config loader (`pigauge.core.config`): schemas for the main app
  config, gauge layouts, and vehicle profiles; every failure raised as
  `ConfigError` with the offending file and dotted field paths.
- Vehicle-profile `inherits` resolution with deep merge and cycle detection
  (patrol_zd30_gu.yaml validates against the generic profile it extends).
- `check_config()` walks the whole tree: app config → vehicle profile →
  each display's gauge layout.
- `python -m pigauge --check-config <path>` validates and exits (0 on
  success, 1 with a readable report on failure); bare `--check-config`
  falls back to `--config`.
- Tests validate all shipped configs (dev_sim.yaml, default.yaml, both
  gauge layouts, both vehicle profiles) plus the failure modes; ruff clean.
- Scaffold lint fixes (import order, intentional no-op ABC hooks).

### Earlier
- Project scaffold: documentation set (ARCHITECTURE, ROADMAP, HARDWARE,
  PROTOCOLS), CLAUDE.md workflow, config examples, interface ABCs, systemd
  unit, setup scripts, smoke test.
- Next: Phase 1 (see docs/ROADMAP.md).
