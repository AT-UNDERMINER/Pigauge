# PiGauge Roadmap

Each phase is independently shippable and ends with all acceptance criteria met,
tests green, and CHANGELOG.md updated. Claude Code: work strictly in order.

## Phase 0 — Scaffold & tooling
- [x] Package layout under src/pigauge/, installable with `pip install -e .`
- [x] pytest + ruff configured (pyproject.toml); `pytest -q` runs the smoke test
- [x] Config loader: pydantic models for default.yaml, gauge layouts, vehicle
      profiles; invalid config raises ConfigError with file/field context
- [x] `python -m pigauge --check-config config/dev_sim.yaml` validates and exits

**Accept:** fresh clone → `pip install -e .[dev]` → `pytest` green.

## Phase 1 — Core: DataBus, channels, units, simulator
- [x] core/units.py: base units per quantity + conversions (kPa↔psi/bar, °C↔°F,
      km/h↔mph), property-tested round-trips
- [x] core/channels.py: canonical channel registry (id, quantity, stale_after)
- [x] core/databus.py: thread-safe publish/get/subscribe with staleness
- [x] sources/sim.py: SimSource generating plausible driving data (idle → rev →
      cruise cycles) for every registered channel; deterministic with a seed
- [x] Optional replay mode: SimSource can replay a CSV log at real-time speed

**Accept:** unit tests for bus concurrency (publisher thread + reader), staleness
transitions, unit conversions; `python -m pigauge.tools.bus_monitor` prints live
simulated values in the terminal.

## Phase 2 — Render engine + VirtualDisplay
- [x] Canvas abstraction over Pillow (and later pygame)
- [x] Widgets: NumericReadout, ArcGauge (sweep, ticks, redline zone), NeedleGauge
      (classic round dial), BarGauge, Sparkline, StatusIcon
- [x] GaugeScene: build from layout YAML, per-frame update from DataBus,
      display-unit conversion, stale = greyed
- [x] displays/virtual.py: VirtualDisplay saving latest frame; render_preview CLI
      tool outputs PNG for a layout + simulated data
- [x] Golden-image tests: render fixed scenes with fixed data, compare to
      tests/fixtures/golden/*.png within tolerance

**Accept:** `render_preview --layout config/gauges/single_round_boost.yaml` produces
a correct 240x240 round boost gauge PNG; golden tests pass.

## Phase 3 — Physical displays (on-Pi milestone)
- [ ] displays/gc9a01.py: SPI driver (Pillow buffer → RGB565 blit), configurable
      bus/CE/DC/RST/backlight pins, rotation
- [ ] displays/framebuffer.py: pygame KMSDRM fullscreen for HDMI/DSI dash
- [ ] Multi-display: config binds each display to its own layout; render loop
      services all displays; FPS counter overlay (debug flag)
- [ ] scripts/bench_display.py reports achieved FPS per display

**Accept (hardware):** simulated data animates on the physical GC9A01 at ≥ 25 FPS
(≥ 15 with two), HDMI at ≥ 30 FPS, on a Pi Zero 2 W.
**Accept (dev):** drivers import cleanly and are unit-tested with a mocked SPI/
pygame layer (hardware libs are optional extras, guarded imports).

## Phase 4 — Vehicle sources: CAN + ELM327
- [ ] sources/can_socketcan.py: python-can on can0 (MCP2515), OBD2 broadcast
      queries (0x7DF) + response parsing (0x7E8+), per-channel poll scheduler,
      DBC-less decode driven by vehicle profile YAML
- [ ] sources/elm327.py: pyserial driver for ELM327/STN-compatible adapters
      (init AT sequence, protocol auto/forced, batched PID requests), same
      profile-driven decode
- [ ] Vehicle profiles: generic_obd2.yaml complete for the standard PID set in
      docs/PROTOCOLS.md; patrol_zd30_gu.yaml stub pending on-vehicle scan
- [ ] tools/scan_vehicle.py: connects, detects protocol, enumerates supported
      PIDs (modes 01/09), dumps a report to seed the vehicle profile
- [ ] Tests: vcan-based round-trip (fake ECU responder fixture answers 0x7DF)
      and FakeELM327 serial emulator; reconnection/backoff tests

**Accept (dev):** vcan test suite green; FakeELM327 suite green.
**Accept (hardware):** scan_vehicle.py produces a PID report on the Patrol; RPM
and coolant temp live on a physical gauge.

## Phase 5 — External analog sensors
- [ ] sources/ads1115.py: I2C ADC, per-channel transfer functions in YAML
      (voltage → kPa/°C via linear or table interpolation), oversampling/filtering
- [ ] sources/max31856.py: SPI thermocouple (K-type EGT), fault detection
- [ ] Calibration doc section + example config for: 3-bar MAP sensor (boost),
      0-150 psi oil pressure transducer, EGT probe
- [ ] Median/EMA filtering configurable per channel

**Accept:** transfer-function unit tests (known voltage → known pressure);
hardware smoke test procedure documented in HARDWARE.md.

## Phase 6 — Alerts + logging
- [ ] core/alerts.py: threshold rules with hysteresis + qualifiers; actions:
      widget flash, fullscreen warning takeover, buzzer GPIO, event log
- [ ] core/logger.py: SQLite session logging (configurable channels/rates),
      ring-buffer pruning by size; CSV export CLI
- [ ] Warning takeover screen widget (all displays)

**Accept:** simulated EGT exceedance triggers flash → takeover → clears with
hysteresis, covered by tests; log export produces a valid CSV.

## Phase 7 — Power: ignition sense & safe shutdown
- [ ] system/ignition.py: debounced GPIO monitor (opto input per HARDWARE.md),
      configurable grace period (default 15 s) with on-screen countdown, cancel
      on ignition return, then clean stop + `systemctl poweroff`
- [ ] systemd/pigauge.service installed by scripts/setup_pi.sh; Restart=on-failure
- [ ] docs: overlayfs read-only root setup + config-write workflow (remount rw)

**Accept:** bench test with a toggle switch on the opto input: ignition off →
countdown → halt; SD card survives 20 hard power-pull cycles after halt completes.

## Phase 8 — Web UI: live preview + layout editor
- [ ] Flask app: status page (sources, channels, FPS), MJPEG live preview per
      display (frames from the real engine), REST API (channels, config CRUD)
- [ ] Layout editor: edit widget list/properties for a layout, preview renders
      against SimSource or live data, "Deploy" writes YAML + hot-reloads scene
- [ ] Mobile-friendly (this is the phone interface until a native app exists)

**Accept:** from a phone browser: view live gauges, change a gauge's range and
colour, preview it, deploy it, see the physical display update without restart.

## Phase 9 — Later / stretch
- Manufacturer-specific PIDs (mode 22) for the Patrol ZD30 via profile entries
- MQTT/UDP DataBus bridge → multi-Pi / RP2040 display satellites
- Native phone app consuming the existing API
- Custom carrier PCB (see HARDWARE.md §Custom PCB path)
- Dirty-region SPI updates, theming system, day/night auto-dim (CDS cell or time)
