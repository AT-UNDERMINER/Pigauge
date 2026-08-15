# PiGauge Protocols & Data Reference

## Canonical channels (core/channels.py must match this table)

| Channel ID | Quantity | Base unit | Typical source | stale_after |
|---|---|---|---|---|
| engine.rpm | rotational speed | RPM | OBD 0x0C | 0.5 s |
| vehicle.speed | speed | km/h | OBD 0x0D | 1 s |
| engine.coolant_temp | temperature | °C | OBD 0x05 | 5 s |
| engine.intake_temp | temperature | °C | OBD 0x0F | 5 s |
| engine.load | ratio | % | OBD 0x04 | 1 s |
| engine.throttle | ratio | % | OBD 0x11 | 0.5 s |
| engine.map | pressure (abs) | kPa | OBD 0x0B | 0.5 s |
| boost.pressure | pressure (gauge) | kPa | ADS1115 CH0 (or map − baro) | 0.5 s |
| oil.pressure | pressure (gauge) | kPa | ADS1115 CH1 | 1 s |
| exhaust.egt1 | temperature | °C | MAX31856 | 1 s |
| fuel.level | ratio | % | OBD 0x2F or ADS1115 CH2 | 30 s |
| electrical.battery_v | voltage | V | ADS1115 CH3 (or OBD 0x42) | 5 s |
| ambient.baro | pressure (abs) | kPa | OBD 0x33 | 60 s |
| system.ignition | boolean | — | GPIO24 | 1 s |

Display conversions (psi, bar, °F, mph) are render-layer only.

## Standard OBD2 (mode 01) decode formulas

| PID | Channel | Formula (A,B = data bytes) |
|---|---|---|
| 0x04 | engine.load | A×100/255 |
| 0x05 | engine.coolant_temp | A−40 |
| 0x0B | engine.map | A (kPa) |
| 0x0C | engine.rpm | (256A+B)/4 |
| 0x0D | vehicle.speed | A |
| 0x0F | engine.intake_temp | A−40 |
| 0x11 | engine.throttle | A×100/255 |
| 0x2F | fuel.level | A×100/255 |
| 0x33 | ambient.baro | A |
| 0x42 | electrical.battery_v | (256A+B)/1000 |

Supported-PID discovery: query 0x00, 0x20, 0x40 bitmasks (scan tool does this).

## CAN transport (ISO 15765-4)
- Request: ID 0x7DF, payload `02 01 <PID> 00 00 00 00 00`
- Response: IDs 0x7E8-0x7EF, payload `<len> 41 <PID> <A> <B> ...`
- 500 kbit/s, 11-bit IDs is the common case; scan tool also tries 250 k and
  29-bit (0x18DB33F1 / 0x18DAF110).

## ELM327/STN transport
- Init: `ATZ`, `ATE0`, `ATL0`, `ATS0`, `ATH1`, `ATSP0` (auto) — then `0100` to
  force protocol negotiation. Poll with plain PID hex (`010C`).
- Multi-PID per request (`010C0D05`) works on CAN protocols; profile flag
  `batch_pids: true` controls this.
- K-line vehicles: expect ~4-8 Hz total request rate; scheduler must prioritise
  fast channels.

## Vehicle profile YAML format

```yaml
# config/vehicles/generic_obd2.yaml
name: Generic OBD2
transport: auto            # auto | can | elm327
can:
  bitrate: 500000
  request_id: 0x7DF
  response_ids: [0x7E8, 0x7E9]
channels:
  engine.rpm:        {pid: 0x0C, rate_hz: 10}
  engine.map:        {pid: 0x0B, rate_hz: 10}
  vehicle.speed:     {pid: 0x0D, rate_hz: 5}
  engine.coolant_temp: {pid: 0x05, rate_hz: 1}
  engine.load:       {pid: 0x04, rate_hz: 2}
  electrical.battery_v: {pid: 0x42, rate_hz: 0.5}
# Future manufacturer-specific entries (Phase 9):
# custom_channels:
#   trans.temp: {mode: 0x22, pid: 0x1234, formula: "(256*A+B)/10 - 40", rate_hz: 1}
```

## Choosing a transport (Phase 4)

Two things decide which vehicle link runs:

- the **vehicle profile** says what the vehicle speaks (`transport: auto | can |
  elm327`);
- **config/default.yaml** says which links are fitted and enabled
  (`sources.can.enabled`, `sources.elm327.enabled`).

`pigauge.sources.create_vehicle_source()` builds a source only when both agree.
With `transport: auto` and both links enabled, CAN wins — it sustains the fast
poll rates that an ELM327 cannot. If the profile names a transport that is
disabled in config, the mismatch is logged and no vehicle source runs (the
simulator and analog sources are unaffected).

Decode is table-driven: `sources/obd_pids.py` mirrors the mode 01 table above
(a test parses this file and fails on drift), and the profile supplies only
which PIDs to poll and how fast. Sources contain no PID literals. A profile
whose PID does not match its channel — `engine.rpm: {pid: 0x0D}` — is rejected
at startup with a `ConfigError` rather than silently showing road speed on the
tacho.

Unanswered PIDs are not errors: the channel stops refreshing and the DataBus
marks it STALE, so the gauge greys out. Only link-level faults (bus down,
adapter unplugged, `UNABLE TO CONNECT`) trigger reconnection, which retries
with exponential backoff from 0.5 s to a 30 s ceiling and never gives up.

## Scanning a vehicle (tools/scan_vehicle.py)

```bash
python -m pigauge.tools.scan_vehicle --transport elm327 --port /dev/ttyUSB0
python -m pigauge.tools.scan_vehicle --transport can --interface can0 --out scan.txt
```

The tool connects, reports the negotiated protocol (ELM327 `ATDP`) or the CAN
ID scheme that answered, walks the mode 01 and mode 09 supported-PID bitmasks
(0x00 → 0x20 → 0x40), and prints which channels PiGauge can decode plus a
`channels:` block to review.

It never writes config. The printed poll rates are the generic defaults, not
measurements: a scan proves a PID answers once while parked, not that it
answers ten times a second in traffic. Confirm rates on the road before
trusting a gauge.

For socketcan the bitrate is set when the interface comes up, not by the tool.
If nothing answers, re-run after
`sudo ip link set can0 down && sudo ip link set can0 up type can bitrate 250000`.

## Nissan Patrol GU ZD30 CRD notes (TO CONFIRM on-vehicle)
- 2010+ CRD (ZD30DDTi common rail) generally responds to standard OBD2; the
  active protocol on the diagnostic port must be confirmed with
  `tools/scan_vehicle.py` before assuming CAN — earlier ZD30s are K-line
  (Consult-II era). Do not hard-code until scanned.
- Boost via OBD 0x0B (MAP) is available on CRD, but the dedicated 3-bar MAP
  sensor on ADS1115 gives faster, higher-resolution boost regardless of
  protocol speed — plan on the analog sensor for the boost gauge and OBD MAP
  as cross-check.
- EGT is not in the standard PID set on this vehicle: MAX31856 probe required.
- Fill in patrol_zd30_gu.yaml from the scan report (Phase 4 acceptance item).
