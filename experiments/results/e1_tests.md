r > 0: the first mode's values tend to be larger (worse). Better = the mode with the lower median when the Holm-adjusted p < 0.05.

### time to recover (censored at 45 min): M1 vs M2 (effect of automation)

| Fault | Median M1 | Median M2 | p (Holm) | Rank-biserial r | Better |
| --- | --- | --- | --- | --- | --- |
| crah_fan_failure | 11.5 | 1.0 | 3.6e-07 | +1.00 | M2 |
| rack_hotspot | 11.8 | 0.8 | 6.1e-07 | +0.97 | M2 |
| chw_supply_drift | 15.0 | 5.0 | 3.6e-07 | +1.00 | M2 |
| pump_degradation | > 45 | > 45 | 1 | +0.00 | – |
| sensor_stuck | 0.0 | 0.0 | 1 | +0.00 | – |
| sensor_drift | 23.2 | 13.3 | 3.6e-07 | +1.00 | M2 |
| ups_battery_overheat | 35.4 | 35.4 | 1 | +0.00 | – |
| pdu_overload | 10.8 | 10.8 | 1 | +0.00 | – |

### time to recover (censored at 45 min): M2 vs M3 (effect of ML detection)

| Fault | Median M2 | Median M3 | p (Holm) | Rank-biserial r | Better |
| --- | --- | --- | --- | --- | --- |
| crah_fan_failure | 1.0 | 1.0 | 1 | +0.00 | – |
| rack_hotspot | 0.8 | 0.8 | 1 | +0.00 | – |
| chw_supply_drift | 5.0 | 1.7 | 2.5e-07 | +1.00 | M3 |
| pump_degradation | > 45 | 0.0 | 3.7e-09 | +1.00 | M3 |
| sensor_stuck | 0.0 | 0.0 | 1 | +0.00 | – |
| sensor_drift | 13.3 | 2.3 | 2.5e-07 | +1.00 | M3 |
| ups_battery_overheat | 35.4 | 0.0 | 2.2e-06 | +0.92 | M3 |
| pdu_overload | 10.8 | 10.7 | 1 | +0.05 | – |

### exposure: M1 vs M2 (effect of automation)

| Fault | Median M1 | Median M2 | p (Holm) | Rank-biserial r | Better |
| --- | --- | --- | --- | --- | --- |
| crah_fan_failure | 641.3 | 17.0 | 4.8e-07 | +1.00 | M2 |
| rack_hotspot | 17.2 | 1.0 | 4.8e-07 | +1.00 | M2 |
| chw_supply_drift | 55.1 | 4.2 | 3.6e-07 | +1.00 | M2 |
| pump_degradation | 255.3 | 255.3 | 1 | +0.00 | – |
| sensor_stuck | 0.0 | 0.0 | 1 | +0.00 | – |
| sensor_drift | 111.4 | 31.7 | 4.8e-07 | +1.00 | M2 |
| ups_battery_overheat | 53.2 | 53.2 | 1 | +0.00 | – |
| pdu_overload | 72.7 | 72.7 | 1 | +0.00 | – |

### exposure: M2 vs M3 (effect of ML detection)

| Fault | Median M2 | Median M3 | p (Holm) | Rank-biserial r | Better |
| --- | --- | --- | --- | --- | --- |
| crah_fan_failure | 17.0 | 17.0 | 1 | +0.00 | – |
| rack_hotspot | 1.0 | 1.0 | 1 | +0.00 | – |
| chw_supply_drift | 4.2 | 0.0 | 2.5e-07 | +1.00 | M3 |
| pump_degradation | 255.3 | 0.0 | 3.7e-09 | +1.00 | M3 |
| sensor_stuck | 0.0 | 0.0 | 1 | +0.00 | – |
| sensor_drift | 31.7 | 0.0 | 4.1e-07 | +1.00 | M3 |
| ups_battery_overheat | 53.2 | 0.0 | 3e-06 | +0.91 | M3 |
| pdu_overload | 72.7 | 71.5 | 1 | +0.05 | – |
