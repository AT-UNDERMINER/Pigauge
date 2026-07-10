# PiGauge Architecture

## Design goals

1. **Modular**: any combination of round SPI gauges and rectangular dash displays,
   fed by any combination of OBD2 (CAN or ELM327) and external analog sensors.
2. **Hardware-independent core**: all logic testable on a dev machine; hardware
   drivers are thin edge adapters.
3. **WYSIWYG remote preview**: the web UI streams frames produced by the real
   render engine — never an approximation.
4. **Future-proof for custom PCB**: the same codebase must run unchanged on a
   future custom carrier board (CM4/CM5) where the MCP2515, ADS1115, MAX31856,
   power management, and display connectors move on-board. Nothing may assume a
   specific HAT beyond the pin/bus definitions in config.

## Layer diagram

```
┌─────────────────────────────────────────────────────────────┐
│  Web UI (Flask)     Layout editor · MJPEG live preview ·    │
│                     status/diagnostics · config deploy       │
├─────────────────────────────────────────────────────────────┤
│  Render Engine      GaugeScene → Widgets (arc, needle, bar,  │
│                     numeric, sparkline, warning) → Frame     │
├──────────────┬──────────────────────────────────────────────┤
│  DataBus     │  Alerts Engine        Logger (SQLite)         │
│  (pub/sub,   │  (thresholds,         (ring-buffer +          │
│  latest-value│  hysteresis,          session logging)        │
│  cache)      │  buzzer GPIO)                                 │
├──────────────┴──────────────────────────────────────────────┤
│  Sources                          Displays                   │
│  · CanSource (socketcan/MCP2515)  · Gc9a01Display (SPI)      │
│  · Elm327Source (pyserial)        · FramebufferDisplay       │
│  · Ads1115Source (I2C analog)       (pygame/KMSDRM, HDMI)    │
│  · Max31856Source (SPI EGT)       · VirtualDisplay (PNG/     │
│  · SimSource (dev/testing)          MJPEG, drives web UI)    │
├─────────────────────────────────────────────────────────────┤
│  System services: IgnitionMonitor → safe shutdown ·          │
│  systemd unit · watchdog · overlayfs (read-only root)        │
└─────────────────────────────────────────────────────────────┘
```

## Core concepts

### Channel
A named, typed data stream, e.g. `engine.rpm`, `engine.coolant_temp`,
`boost.pressure`, `exhaust.egt1`, `electrical.battery_v`. Channel IDs are the
universal join key between sources (who publish them), gauges (who subscribe),
alerts, and the logger. The canonical channel registry with base units lives in
`core/channels.py` and docs/PROTOCOLS.md.

### DataBus (`core/databus.py`)
Thread-safe latest-value cache + subscription callbacks.

- `publish(channel_id, value, timestamp)` — called by source threads.
- `get(channel_id) -> Reading | None` — non-blocking, called by render loop.
- `subscribe(channel_id, callback)` — used by alerts engine and logger.
- Each `Reading` carries value (base units), timestamp, and quality
  (`OK | STALE | NO_DATA`). The bus marks a reading STALE when its age exceeds
  the channel's configured `stale_after` — gauges render stale data greyed out.

### Sources (`sources/base.py`)
```python
class Source(ABC):
    def start(self) -> None: ...   # spawn own thread/task
    def stop(self) -> None: ...
    @property
    def provided_channels(self) -> list[str]: ...
    @property
    def status(self) -> SourceStatus: ...  # CONNECTED / RECONNECTING / ERROR
```
Sources own their polling schedule (per-channel rates from vehicle profile YAML),
handle reconnection with backoff, and must never raise into the main thread.

### Render engine (`render/`)
- A `GaugeScene` is built from a layout YAML: canvas size + list of widget
  instances with positions and per-widget config (channel, range, units, colours,
  redline, label, needle style, etc.).
- Widgets draw onto a Pillow `Image` (round SPI displays) or pygame `Surface`
  (HDMI). A thin `Canvas` abstraction wraps both so widgets are written once.
- The engine produces frames at a target FPS; dirty-region tracking is a Phase 3
  optimisation for SPI throughput.
- **The same engine instance renders the web preview.** VirtualDisplay simply
  keeps the latest frame as PNG for the MJPEG endpoint.

### Displays (`displays/base.py`)
```python
class Display(ABC):
    resolution: tuple[int, int]
    shape: Literal["round", "rect"]
    def show(self, frame: Image) -> None: ...
```
One process can drive multiple Display instances, each with its own scene and
layout file (e.g. two GC9A01 on SPI0 CE0/CE1 + one HDMI dash).

### Alerts (`core/alerts.py`)
Config-driven rules: channel, warn/critical thresholds, direction, hysteresis,
minimum-RPM qualifier (for oil pressure), actions (widget flash, fullscreen
takeover, buzzer GPIO, log event).

### Configuration
- `config/default.yaml` — hardware map (buses, CS pins, GPIO), enabled sources,
  display-to-layout bindings, web port.
- `config/gauges/*.yaml` — layouts (deployable from web UI).
- `config/vehicles/*.yaml` — vehicle profiles: protocol, PID/CAN mappings,
  per-channel poll rates. See docs/PROTOCOLS.md.
- All schemas validated on load with pydantic; a bad config must fail fast with a
  human-readable error, never crash mid-drive.

## Threading model (v1, single process)

- Main thread: render loop (all displays, sequential; measure before parallelising).
- One thread per Source.
- Flask served from its own thread (dev server is fine; it's a LAN-only device).
- IgnitionMonitor thread: debounced GPIO watch → grace timer → `systemctl poweroff`.
- Shutdown order: sources → logger flush → displays (draw "goodbye" frame) → exit.

## Future paths (design for, don't build yet)

- **Networked satellites**: DataBus gains an optional MQTT/UDP bridge so slave Pis
  (or RP2040 display satellites on the custom PCB) subscribe to channels and run
  only the render layer. This is why sources never talk to displays directly.
- **Phone app**: consumes the same REST + MJPEG API as the web UI.
- **Manufacturer-specific PIDs**: vehicle profiles already support raw CAN decode
  entries (mode 22 / proprietary frames) — adding them is config + tests only.
