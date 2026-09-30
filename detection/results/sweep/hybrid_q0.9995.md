## Detection per fault (5 seeds each): detected / median MTTD in seconds

| Fault | D1H | D2H |
| --- | --- | --- |
| crah_fan_failure | 5/5 · 30 s | 5/5 · 30 s |
| sensor_stuck | 5/5 · 70 s | 5/5 · 70 s |
| sensor_drift | 5/5 · 130 s | 5/5 · 120 s |
| pump_degradation | 5/5 · 410 s | 5/5 · 170 s |
| chw_supply_drift | 5/5 · 90 s | 5/5 · 90 s |
| rack_hotspot | 5/5 · 30 s | 5/5 · 30 s |
| ups_battery_overheat | 5/5 · 80 s | 5/5 · 80 s |
| pdu_overload | 5/5 · 40 s | 5/5 · 30 s |

## Overall

| Detector | Faults detected | Median MTTD (s) | Wrong automated events | False alarms / 24 h (automated) | False alarms / 24 h (notify-only) |
| --- | --- | --- | --- | --- | --- |
| D1H | 40/40 | 75 | 0 | 0.00 | 4.00 |
| D2H | 40/40 | 75 | 0 | 0.00 | 5.00 |
