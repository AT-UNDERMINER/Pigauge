# Changelog

## Unreleased

### Phase 3 — Physical displays (dev-side complete; on-Pi acceptance PENDING)
- `displays/gc9a01.py` (+ `gc9a01_init.py`): SPI driver — Pillow frame →
  big-endian RGB565 via channel LUTs (no numpy), vendor init sequence,
  CS-pin→chip-enable mapping per HARDWARE.md, MADCTL rotation, PWM
  backlight. spidev/gpiozero are guarded optional imports
  (`pip install 'pigauge[pi]'`); unit-tested against fake SPI/pins.
- `displays/framebuffer.py`: pygame KMSDRM fullscreen dash driver;
  guarded pygame import; unit-tested against a fake pygame module.
- `displays/__init__.py`: DISPLAY_REGISTRY / create_display — drivers
  selected by config `driver` name (virtual | gc9a01 | framebuffer).
- `render/loop.py`: RenderLoop services every configured display, each
  bound to its own layout; per-display smoothed FPS; new
  `render.fps_overlay` debug flag stamps achieved FPS on frames
  (documented in config/default.yaml and dev_sim.yaml).
- `scripts/bench_display.py`: reports frames + average FPS per display
  (uncapped by default, `--target-fps` to pace).
- NOT yet verified (needs the Pi): physical GC9A01/HDMI bring-up, FPS
  budgets (GC9A01 ≥ 25 FPS, ≥ 15 with two; HDMI ≥ 30 FPS), MADCTL
  rotation/colour-order values, and the vendor init sequence.

### Phase 2 — Render engine + VirtualDisplay (complete)
- `render/canvas.py`: Canvas ABC (line, polyline, arc, circle, rect,
  polygon, text) with the Pillow backend using the embedded default font;
  pygame backend arrives in Phase 3.
- `render/widgets/`: NumericReadout, ArcGauge (sweep, ticks, redline
  zone), NeedleGauge, BarGauge, Sparkline, StatusIcon — selected by layout
  `type` via WIDGET_REGISTRY. Base-to-display unit conversion happens at
  draw time; STALE or missing readings render grey.
- `render/scene.py`: GaugeScene builds widgets from a validated layout
  (failing fast on unknown types/channels) and renders frames from the
  latest bus values without blocking.
- `displays/virtual.py`: VirtualDisplay keeps the latest frame
  (thread-safe copy, resolution-checked) for previews, tests, and the
  future MJPEG stream.
- `tools/render_preview.py`: renders a layout against a deterministic
  simulation snapshot (`--seed`, `--sim-time`, `--stale`), producing
  byte-identical PNGs for identical arguments.
- Golden-image tests: both shipped layouts plus a stale variant, approved
  by eye then locked into tests/fixtures/golden/ with an RMS tolerance.
- Pillow floor raised to 10.1 (`ImageFont.load_default(size=...)`).

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
