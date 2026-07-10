# PiGauge

A modular, fully customisable smart digital gauge system for vehicles, built on a
Raspberry Pi Zero 2 W. Reads live engine data from the OBD2 port (direct CAN via
MCP2515 HAT, or any ELM327-compatible adapter for K-line vehicles) plus external
analog sensors (boost, oil pressure, EGT), and renders configurable gauges to any
mix of 2" round SPI displays (52 mm gauge pods) and rectangular HDMI/DSI dash
screens. A built-in web UI provides live, pixel-accurate preview and layout editing
from your phone.

## Highlights
- **Modular displays**: 1 round gauge, a dash screen, or several of each — all
  driven from YAML layouts, no code changes.
- **Two vehicle links**: socketcan (MCP2515) for CAN vehicles, ELM327 serial for
  everything else, behind one interface with automatic reconnection.
- **External sensors**: ADS1115 analog (boost/oil/fuel) and MAX31856 EGT with
  config-defined calibration curves.
- **WYSIWYG web editor**: the browser preview is rendered by the same engine that
  drives the physical displays.
- **Alerts**: threshold warnings with hysteresis — flash, fullscreen takeover,
  buzzer.
- **Vehicle-safe power**: opto-isolated ignition sensing, graceful shutdown,
  read-only root for SD card protection.
- **Runs entirely without hardware** for development: simulator source, virtual
  display, vcan test rig.

## Quickstart (dev machine, no hardware)
```bash
pip install -e .[dev]
pytest -q
python -m pigauge --config config/dev_sim.yaml   # sim data + web UI on :8080
```

## Quickstart (Pi)
See docs/HARDWARE.md for wiring, then:
```bash
sudo scripts/setup_pi.sh
python -m pigauge.tools.scan_vehicle             # identify protocol & PIDs
sudo systemctl enable --now pigauge
```

## Documentation
| File | Contents |
|---|---|
| CLAUDE.md | Development rules & workflow (read first) |
| docs/ROADMAP.md | Phased build plan with acceptance criteria |
| docs/ARCHITECTURE.md | Layers, DataBus, interfaces, threading |
| docs/HARDWARE.md | BOM, wiring, ignition-sense circuit, PCB path |
| docs/PROTOCOLS.md | Channels, PID formulas, vehicle profile format |

## Status
Scaffold complete. Implementation begins at Phase 0 — see docs/ROADMAP.md and
CHANGELOG.md.
