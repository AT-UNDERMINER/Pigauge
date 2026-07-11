# Changelog

## Unreleased

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
