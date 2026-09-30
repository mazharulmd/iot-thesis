# Data hall simulator

The simulator replaces real facility equipment. It produces IoT telemetry, accepts
remediation commands, and lets faults be injected with known ground truth.

## Layout

| Asset | Count | Gateway | Signals | Commands |
| --- | --- | --- | --- | --- |
| GPU rack (45 kW rated) | 20 (5 per zone) | zone1–zone4 | `t_in`, `t_out`, `p_kw` | `cap_kw`, `sensor_flag` |
| CRAH unit | 4 (one per zone) | zone1–zone4 | `t_sup`, `t_ret`, `fan_pct`, `status` | `fan_pct`, `fan_mode` |
| Standby CRAH `crah5` | 1 | plant | `status`, `zone`, `fan_pct`, `t_sup`, `t_ret` | `status`, `zone`, `fan_pct` |
| PDU (260 kW) | 4 | zone1–zone4 | `p_kw`, `i_a`, `load_pct` | – |
| Chiller | 1 | plant | `t_sup`, `t_ret`, `sp`, `assist` | `sp`, `assist` |
| Pump (duty + standby) | 2 | plant | `status`, `flow_lps`, `dp_kpa`, `vib_mms`, `i_a` | `status` |
| UPS | 2 | plant | `load_kw`, `t_batt`, `v_batt` | `load_share` |

Five gateways (`zone1`–`zone4`, `plant`) each publish one JSON message every 10 s.

## Model (reduced-order)

Each zone is one lumped hot-aisle node:

    C · dT_hot/dt = P_IT − m_eff · cp · (T_hot − T_sa) − UA · Σ(T_hot − T_hot,neighbour)

- **Supply air:** `T_sa = T_chw + approach`, where the coil approach grows when chilled water flow falls.
- **Rack inlet:** `T_in = T_sa + r · (T_hot − T_sa)`; recirculation `r` rises when a rack gets less air than it needs.
- **Airflow sharing:** surplus CRAH air partly spills into neighbouring zones, so boosting neighbours helps a zone whose CRAH failed.
- **CRAH control:** in auto mode, fans supply 110 % of IT airflow demand (0.068 kg/s per kW).
- **IT load:** each rack alternates between training jobs (90 % of rating) and idle (25 %), with exponential durations.
- **Throttling:** GPUs reduce power above 32 °C inlet, down to 50 % at 40 °C.
- **Chilled water:** return temperature follows the heat removed; pump flow, pressure, vibration and current depend on pump health.
- **UPS battery:** first-order temperature model with extra heating from a battery fault, proportional to load.

All parameters are in `simulator/config.py`. Energy balance is checked by a test: heat removed by air matches IT power within 2 %.

## Faults

| Type | Target | Shape | Symptom | Scripted remediation | Risk |
| --- | --- | --- | --- | --- | --- |
| `crah_fan_failure` | `crah2` | step | Zone 2 inlets jump above 35 °C | Boost neighbours, start `crah5` on zone 2 | Low |
| `sensor_stuck` | `zone2.rack07.t_in` | stuck | Reading goes perfectly flat | Flag sensor | Low |
| `sensor_drift` | `zone3.rack12.t_in` | ramp 0.5 K/min | Reading climbs, outlet unchanged | Flag sensor | Low |
| `pump_degradation` | `pump1` | ramp 30 min | Vibration and current up, flow down, stays below ISO alarm | Start `pump2`, stop `pump1` | Medium |
| `chw_supply_drift` | `chiller` | ramp +7 K | Supply above setpoint, all inlets above 27 °C | Lower setpoint, assist on | Medium |
| `rack_hotspot` | `rack07` | step | One rack above 27 °C, neighbours normal | Zone fan to 100 % | Medium |
| `ups_battery_overheat` | `ups1` | step | Battery above 35 °C and rising | Move load to `ups2` | High |
| `pdu_overload` | `zone3` | step | PDU load above 95 % | Cap racks at 40 kW | High |

Ground truth goes to `labels.json` only; it is never inside published messages.

## Running

```bash
make sim S=crah_fan_failure   # one scenario, with and without remediation
make sim-all                  # all scenarios
```

Each run writes to `runs/<scenario>/`:

| File | Contents |
| --- | --- |
| `messages.jsonl` | Exactly what the gateways will publish over MQTT in Step 3 |
| `telemetry.csv` | Same data as one row per 10 s, plus `truth.*` columns and `label` |
| `labels.json` | Fault type, target, start, risk, expected playbook, actions applied |
| `plot.png` | Key signals with the fault window and actions marked |

## Limitations (state these in the thesis)

- Lumped zones: no CFD, no spatial temperature gradients inside a zone.
- Parameters are plausible round numbers, not calibrated to a specific facility.
- Faults are idealised shapes (step, ramp, stuck); real failures are noisier.
- Sensor faults affect only the reading, not the physics, which is correct by definition.
