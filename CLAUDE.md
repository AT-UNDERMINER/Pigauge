## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).

# CLAUDE.md — PiGauge Development Guide

PiGauge is a modular smart digital gauge system for vehicles. A Raspberry Pi Zero 2 W
reads live data from the OBD2 port (CAN via MCP2515 HAT, or ELM327-compatible USB
adapter) plus external analog sensors (boost, EGT, oil pressure), and renders
customisable gauges to one or more displays (2" round GC9A01 SPI displays for 52mm
gauge pods, and/or a rectangular HDMI/DSI dash display). A web UI provides live
WYSIWYG layout editing. See docs/ARCHITECTURE.md before writing any code.

## Golden rules

1. **Work one phase at a time.** docs/ROADMAP.md defines Phases 0-9, each with
   acceptance criteria. Never start a phase until the previous phase's tests pass.
   Never implement features from a later phase "while you're in there".
2. **Everything must run without hardware.** Every hardware component has a
   simulated/virtual counterpart (SimVehicleSource, VirtualDisplay, vcan). All
   business logic must be testable on a dev machine with `pytest` alone. Hardware
   drivers are thin adapters at the edges — keep logic out of them.
3. **Interfaces are contracts.** `sources/base.py`, `displays/base.py`, and
   `render/widgets/base.py` define ABCs. New sources/displays/widgets implement
   these; the core never imports a concrete driver directly. Concrete classes are
   selected by name from YAML config via the registry pattern.
4. **Tests before commit.** Run `pytest` and `ruff check src tests` before every
   commit. Do not commit failing tests. Add tests in the same commit as the code
   they cover.
5. **No blocking calls in the render loop.** Data acquisition runs in its own
   thread(s)/tasks and publishes to the DataBus. The render loop only ever reads
   the latest cached value. A slow or disconnected adapter must never drop display FPS.
6. **Units are explicit.** All values on the DataBus are stored in SI/metric base
   units defined in core/units.py (kPa, °C, km/h, RPM, V). Conversion for display
   happens only in the render layer, driven by gauge config.
7. **Config over code.** Gauge layouts, channels, thresholds, calibrations, and
   vehicle profiles all live in YAML under config/. Adding a gauge to a screen must
   never require code changes.

## Code style

- Python 3.11+, PEP 8, ruff-clean.
- Follow SRP and CP1404 style guidelines (https://github.com/CP1404/Starter/wiki):
  functions do one thing, meaningful names, constants in UPPER_SNAKE_CASE at module
  top, no magic numbers.
- Type hints on all public functions and methods. Docstrings on all modules,
  classes, and public functions.
- Prefer composition over inheritance except for the ABC interface hierarchies.
- Keep files under ~300 lines; split when they grow past that.

## Git commit style

- Imperative mood, capitalised, no trailing full stop: `Add arc gauge widget`,
  `Fix EGT cold-junction compensation`, `Refactor DataBus to use RLock`.
- One logical change per commit. Reference the phase in the body when relevant.

## Development workflow (every session)

1. Read docs/ROADMAP.md and CHANGELOG.md to determine the current phase and state.
2. Implement the next incomplete item in the current phase.
3. Write/extend tests. Run `pytest -q` and `ruff check src tests`.
4. For anything visual, render golden frames with the VirtualDisplay
   (`python -m pigauge.tools.render_preview --layout <file> --out /tmp/frame.png`)
   and eyeball them before declaring done.
5. Update CHANGELOG.md with what was completed.
6. After completing a phase, the git hook rebuilds the knowledge graph; use /graphify query or /graphify explain <NodeName> to orient before modifying code you didn't just write.
7. Commit.

## Running without hardware

- `python -m pigauge --config config/dev_sim.yaml` runs the full stack with the
  simulator source and virtual display; the web UI at :8080 shows live output.
- CAN logic is tested against Linux vcan: `sudo scripts/vcan_up.sh` then run tests
  marked `@pytest.mark.vcan` (skipped automatically if vcan0 is absent).
- ELM327 logic is tested against the built-in FakeELM327 serial emulator (tests/).

## Hardware sessions (on the Pi)

When running on the actual Pi, consult docs/HARDWARE.md for wiring, /boot/config.txt
overlays, and interface enablement. Never guess pin assignments — they are defined
once in docs/HARDWARE.md and mirrored in config/default.yaml. If they conflict,
HARDWARE.md wins; fix the config.

## Performance budgets (Pi Zero 2 W)

- GC9A01 240x240 SPI @ 62.5 MHz: target ≥ 25 FPS per display, ≥ 15 FPS with two.
- HDMI 800x480 via pygame/KMSDRM: target ≥ 30 FPS.
- OBD polling: fast channels (RPM, boost) ≥ 10 Hz on CAN, ≥ 4 Hz on ELM327;
  slow channels (coolant, voltage) ≥ 1 Hz.
- If a budget can't be met, profile first (py-spy), optimise second, and only then
  discuss dropping the target.

## Definition of done (per phase)

- All acceptance criteria in ROADMAP.md met.
- `pytest` green, `ruff` clean.
- New config options documented in the relevant docs/ file and example YAML.
- CHANGELOG.md updated.
