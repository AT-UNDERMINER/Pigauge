# PiGauge Hardware Reference

This file is the single source of truth for wiring and pin assignments.
config/default.yaml mirrors these pins; if they ever disagree, this file wins.

## Compute

| Option | Notes |
|---|---|
| **Pi Zero 2 W (recommended)** | Quad-core A53. Comfortably meets all FPS budgets. |
| Pi Zero W (original) | Single-core ARMv6. Will run ONE SPI gauge at reduced FPS; multi-display and web preview simultaneously will struggle. Fine for early bring-up only. |
| CM4/CM5 | Target for the custom PCB phase. |

OS: Raspberry Pi OS Lite (Bookworm, 64-bit on Zero 2 W). No desktop.

## Vehicle interfaces (both supported)

### Option A — MCP2515 + SN65HVD230 CAN HAT (preferred where the car is CAN)
- Bus: SPI0, CE0 (or per HAT docs), INT → GPIO25 (typical; confirm your HAT)
- /boot/firmware/config.txt:
  ```
  dtparam=spi=on
  dtoverlay=mcp2515-can0,oscillator=8000000,interrupt=25
  ```
  ⚠ `oscillator` must match the crystal ON YOUR HAT (8 or 16 MHz — read the can).
- Bring-up: `sudo ip link set can0 up type can bitrate 500000` (OBD2 CAN is
  500 kbit/s, 11-bit IDs; some vehicles use 250 k / 29-bit — scan tool detects).
- OBD2 port pins: 6 = CAN-H, 14 = CAN-L, 16 = +12V batt, 4/5 = ground.
- The SN65HVD230 is a 3.3 V transceiver — fine on the bench; for permanent
  install prefer proper termination awareness (the vehicle bus is already
  terminated — do NOT enable the HAT's 120 Ω jumper when plugged into the car).

### Option B — USB OBD2 cable (PIC18F25K80 + FT232RL)
- Presents as /dev/ttyUSB0, ELM327/STN AT command set, all legacy protocols
  (K-line ISO 9141 / ISO 14230 KWP2000) as well as CAN — this is the fallback
  for vehicles that are NOT CAN on the diagnostic port.
- Slower polling (serial request/response); the source batches PIDs per request
  where the adapter supports it.

**Which one for a given car?** Run `tools/scan_vehicle.py` with the USB cable
first — it reports the active protocol. If it's ISO 15765 (CAN), the MCP2515 HAT
gives much higher poll rates. If it's K-line, the USB cable is your interface.

## Displays

### Round: 1.28" GC9A01 240x240 SPI (fits behind a 52 mm gauge lens)
| Signal | Pin (BCM) | Notes |
|---|---|---|
| SCLK/MOSI | SPI1 (GPIO21/20) | SPI0 is taken by CAN HAT; SPI1 needs `dtoverlay=spi1-1cs` (or 2cs/3cs for multiple gauges) |
| CS | GPIO18 (CE0 on SPI1) | second gauge: GPIO17 (CE1) |
| DC | GPIO16 | |
| RST | GPIO13 | |
| BL | GPIO12 (PWM dimmable) | |
- SPI clock: start at 40 MHz, push to 62.5 MHz if stable.
- 2.1" round 480x480 (ST7701, DPI/MIPI) is an option for a premium single-gauge
  build but consumes the DPI GPIO bank — treat as a dedicated-build variant.

### Rectangular dash: any HDMI display (e.g. 5"/7" 800x480) via pygame/KMSDRM,
or an official DSI panel. No wiring table needed; set resolution in config.

## External sensors

### ADS1115 (I2C, 16-bit, 4 channels) — analog sensors
- I2C1: SDA GPIO2, SCL GPIO3, addr 0x48. `dtparam=i2c_arm=on`
- CH0: 3-bar MAP sensor (boost) — ratiometric 0.5-4.5 V ⇒ divider to ≤3.3 V
  (e.g. 10k/20k) — put the divider in the transfer function config
- CH1: oil pressure transducer 0-150 psi, 0.5-4.5 V (same divider treatment)
- CH2: fuel level / spare
- CH3: ignition/ACC voltage sense (see below) — doubles as battery voltmeter
- All automotive analog grounds star back to one point; keep sensor wiring away
  from injector/alternator looms; twisted pair for EGT.

### MAX31856 (SPI, K-type thermocouple) — EGT
- Share SPI1 with an extra CS (GPIO26 with `spi1-3cs`), or bit-banged SPI —
  decide at Phase 5 based on CS availability.
- Probe: 1/8" NPT K-type, pre-turbo for meaningful ZD30 protection numbers.

## Power & ignition sensing (critical — read fully)

### Supply
- OBD2 pin 16 is BATTERY-permanent 12 V (fused ~10-15 A in most cars).
- Automotive-rated buck converter 12 V → 5 V / 3 A minimum, with load-dump
  tolerance (input rated ≥ 32 V transient). Cheap USB car adapters brown out —
  don't use one.
- Pi stays powered from permanent 12 V; software decides when to shut down.

### Ignition sense circuit (ACC line → opto → GPIO)
```
ACC +12V ──[10k]──┬──[PC817 LED anode]
                  │        PC817 LED cathode ── GND (vehicle)
   (1N4007 reverse-polarity + TVS across input recommended)

Pi side:  3V3 ──[10k pull-up]──┬── GPIO24 (ignition_sense, active LOW)
                                └── PC817 collector
          PC817 emitter ── Pi GND
```
- Ignition ON ⇒ opto conducts ⇒ GPIO24 LOW. Debounce 100 ms in software.
- Additionally, ADS1115 CH3 monitors battery voltage through a 10k/2k2 divider
  (protected by 3.3 V zener) — gives the `electrical.battery_v` channel AND a
  cross-check on ignition state (alternator ≈ 13.8-14.4 V vs ≈ 12.4 V off).

### Safe shutdown & SD protection
- Ignition off → configurable grace period (default 15 s, countdown on screen,
  cancels if ignition returns) → clean service stop → `systemctl poweroff`.
- The buck stays powered after halt (≈ tens of mA). Acceptable short-term; the
  custom PCB adds a hold-up + hard-cut circuit. Interim option: cheap timer
  relay cutting the buck 60 s after ACC drops.
- Enable overlayfs read-only root (`raspi-config` → Performance → Overlay FS).
  Config writes from the web UI remount a small dedicated rw data partition —
  the rootfs itself stays read-only. Procedure in scripts/setup_pi.sh comments.

### Optional
- Piezo buzzer for alerts: GPIO23 via 2N2222/BC337 driver.

## Custom PCB path (Phase 9 — design constraints to respect NOW)
- Everything hardware-specific must be reachable via config: SPI bus numbers,
  CS/DC/RST pins, I2C addresses, GPIO assignments. The PCB revision then only
  changes YAML, not code.
- Likely PCB: CM4/CM5 carrier with on-board MCP2515(or MCP251863)+transceiver,
  ADS1115, MAX31856, automotive buck with ignition-controlled hold-up, opto
  input, buzzer, FPC connectors for GC9A01 panels.
- Alternative topology later: RP2040 per gauge pod receiving frames/channel data
  over CAN or UART — enabled by the DataBus bridge (ARCHITECTURE.md).

## Bill of materials (v1 prototype)

| Item | Qty | Notes |
|---|---|---|
| Pi Zero 2 W + PSU-grade SD (A2, high endurance) | 1 | |
| MCP2515/SN65HVD230 CAN HAT | 1 | already owned |
| ELM327-compatible USB OBD2 cable (PIC18F25K80/FT232RL) | 1 | already owned |
| GC9A01 1.28" round LCD | 1-2 | |
| 800x480 HDMI 5" display (optional dash variant) | 1 | |
| ADS1115 breakout | 1 | |
| MAX31856 breakout + K-type EGT probe kit | 1 | |
| 3-bar MAP sensor (GM style) + oil pressure transducer | 1 ea | |
| Automotive buck 12→5 V 3 A (load-dump rated) | 1 | |
| PC817 opto, 1N4007, TVS (SMBJ33A), resistors, zener 3V3 | — | ignition sense |
| OBD2 male plug w/ breakout leads | 1 | tidy install |
| Piezo buzzer + NPN driver | 1 | alerts (optional) |
