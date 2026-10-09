# BGETech Modbus for Home Assistant

Native Home Assistant integration for B+G E-Tech energy meters connected to a
Modbus TCP gateway (RS485 ⇄ Ethernet). No Node-RED, MQTT or helper scripts
are needed. Everything is configured in the Home Assistant UI.

🇩🇪 [Deutsche Dokumentation](README.de.md)

## Features

- Several meters (slave IDs) per gateway, several gateways per installation
- **Block reads:** all values of a meter are read with as few requests as
  possible (DRT428M: 2 requests per meter, independent of the number of
  enabled entities)
- One sequential communication manager per gateway, no parallel requests on
  the RS485 bus, automatic reconnect, timeouts and retries
- A meter that does not answer only affects its own entities and is retried
  with back-off (up to 5 minutes)
- Configurable polling interval per gateway (default 5 s) and optionally per
  meter for instantaneous values and energy counters
- Energy dashboard ready (import/export counters with `total_increasing`)
- **Safe by design:** measured values are read with function codes 03/04.
  The only write access is the *Energy total mode* select (DRT428M combined
  code, FC06 on register 0x000B, values 1/5/9 only, read back after writing)
- Diagnostic entities and a diagnostics download without host names

## Supported devices

| Model | Status | Requests per poll |
|---|---|---|
| B+G E-Tech DRT428M-3 | verified on hardware | 2 |
| B+G E-Tech DRT428M-2 | register map from the manufacturer manual | 2 |

The models of the [BGETech IP-Symcon module](https://github.com/Nall-chan/BGETech)
(Eastron SDM series, DRT710M, DRS210C, DRS458, Smart X96-5C) are analysed in
[docs/reference-analysis.md](docs/reference-analysis.md) and will be added in
a later version.

## Measured values (DRT428M)

| Value | Entities | Enabled by default |
|---|---|---|
| Voltage | L1, L2, L3 | ✔ |
| Current | L1, L2, L3 | ✔ |
| Frequency | | ✔ |
| Active power | total, L1, L2, L3 | ✔ |
| Reactive power | total ✔, L1–L3 | total |
| Apparent power | total ✔, L1–L3 | total |
| Power factor | total ✔, L1–L3 | total |
| Active energy total / import / export | total ✔, L1–L3 | totals |
| Reactive energy total / import / export | total, L1–L3 | – |
| Tariff counters T1–T4 (DRT428M-3) | active/reactive, total/import/export | – |
| Energy total mode (combined code) | select (configuration) | ✔ |
| Meter connection | diagnostic | ✔ |

Power values are reported by the meter in kW/kvar/kVA and shown in W/var/VA
by Home Assistant. Disabled entities can be enabled in the entity settings –
they never cause additional Modbus requests.

Gateway diagnostics: gateway connection, last successful read, last error,
error count, cycle duration, requests per cycle, meters online, average cycle
duration, average response time, reconnects.

## Installation

### HACS

1. HACS → ⋮ → *Custom repositories* → `https://github.com/RcRaCk2k/ha_bgtech_modbus`, type *Integration*
2. Install **BGETech Modbus** and restart Home Assistant

### Manual

Copy `custom_components/bgetech_modbus` into `<config>/custom_components/`
and restart Home Assistant.

## Configuration

1. *Settings → Devices & services → Add integration → BGETech Modbus*
2. Enter name, host and port of the gateway, polling interval (default 5 s),
   timeout (5 s), retries (2) and the maximum registers per request
   (0 = automatic, 125).
3. On the gateway entry use **Add meter** for every meter:
   - **Slave ID** (1–247, unique per gateway)
   - **Name** – free text, can be changed at any time without creating new
     entities
   - **Model** – *DRT428M (detect automatically)* reads register 0x0130 to
     distinguish -2 and -3
   - **Enabled** – disabled meters are not polled
   - **Check connection** – reads the meter once before saving
   - optional **polling intervals** for instantaneous values and energy
     counters (empty = gateway interval)

Meters can be edited or removed via the ⋮ menu of the meter entry. To change
the slave ID, remove the meter and add it again. Host, port and name of the
gateway can be changed with *Reconfigure*, the polling settings with
*Configure*. Changes are applied immediately.

## Energy dashboard

Use **Active energy import** (grid consumption) and **Active energy export**
(return to grid). Both are monotonic counters (`total_increasing`, kWh).

*Active energy total* depends on the meter's *combined code* (register
0x000B, select entity *Energy total mode*):

| Option | Code | *Active energy total* |
|---|---|---|
| Import only | 1 | import |
| Import + export (factory default) | 5 | import + export |
| Import − export | 9 | import − export (can decrease) |

The setting also changes what the meter shows on its display and how the S0
pulse output counts. Import and export counters are not affected. Because
the total can decrease, it is exposed with state class `total` and should not
be used as a consumption source.

The DRT428M offers no command to reset its energy counters, so there is no
reset button.

## Performance

Measured on the reference system (4 × DRT428M-3, RS485 9600 bit/s 8E1,
Modbus TCP gateway):

| | |
|---|---|
| Requests per cycle | 8 (2 per meter) |
| Request instantaneous values (46 registers) | ≈ 190 ms |
| Request energy counters incl. tariffs (96 registers) | ≈ 340–385 ms |
| Average cycle duration (4 meters) | 2.37 s |

The next cycle is scheduled so that cycles start approximately at the configured interval;
cycles never overlap. If a cycle takes longer than the interval, the next one
starts immediately afterwards. With many meters on a 9600 bit/s bus, poll the
energy counters less often (e.g. 30–60 s) or increase the bus speed.

## Troubleshooting

- **Gateway connection off:** check host/port, and that no other Modbus master
  is using the gateway (many gateways allow only one TCP client or mix
  answers of parallel clients).
- **Meter connection off:** check slave ID, wiring and serial settings
  (DRT428M default 9600 bit/s, 8E1). The DRT428M does not answer requests for
  undefined addresses at all, so a wrong model shows up as timeout.
- **Debug logging:**
  ```yaml
  logger:
    logs:
      custom_components.bgetech_modbus: debug
  ```
- *Settings → Devices & services → BGETech Modbus → ⋮ → Download diagnostics*
  contains read plans, counters and the last errors.

## Known limitations

- Only Modbus TCP. RTU over TCP and serial RTU are not supported.
- Only the DRT428M-2/-3 are supported so far.
- The DRT428M energy counters cannot be reset via Modbus.
- Serial number: the meters of the reference system report `00000000`; it is
  only shown when set.
- Requires Home Assistant 2026.10 or newer.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt ruff
ruff check . && ruff format --check .
pytest
```

The tests use a simulated Modbus TCP gateway (`tests/fake_modbus.py`) that
behaves like the DRT428M (no answer for undefined addresses).

## Sources and license

Register definitions: B+G E-Tech DRT428M series manual (Modbus register map),
verified by read-only measurements; cross-checked with
[Nall-chan/BGETech](https://github.com/Nall-chan/BGETech) (CC BY-NC-SA 4.0,
no code taken over). See [docs/reference-analysis.md](docs/reference-analysis.md).

This project is licensed under the [MIT License](LICENSE). It is not
affiliated with B+G E-Tech.
