## Detection per fault (5 seeds each): detected / median MTTD in seconds

| Fault | D0 | D1 | D2 | D1H | D2H |
| --- | --- | --- | --- | --- | --- |
| crah_fan_failure | 5/5 · 30 s | 5/5 · 30 s | 5/5 · 30 s | 5/5 · 30 s | 5/5 · 30 s |
| sensor_stuck | 0/5 · – | 1/5 · 2610 s | 0/5 · – | 5/5 · 70 s | 5/5 · 70 s |
| sensor_drift | 5/5 · 780 s | 5/5 · 120 s | 5/5 · 120 s | 5/5 · 120 s | 5/5 · 120 s |
| pump_degradation | 0/5 · – | 5/5 · 210 s | 5/5 · 170 s | 5/5 · 210 s | 5/5 · 170 s |
| chw_supply_drift | 5/5 · 280 s | 5/5 · 90 s | 5/5 · 90 s | 5/5 · 90 s | 5/5 · 90 s |
| rack_hotspot | 5/5 · 30 s | 5/5 · 30 s | 5/5 · 30 s | 5/5 · 30 s | 5/5 · 30 s |
| ups_battery_overheat | 5/5 · 800 s | 5/5 · 80 s | 5/5 · 80 s | 5/5 · 80 s | 5/5 · 80 s |
| pdu_overload | 5/5 · 40 s | 0/5 · – | 5/5 · 30 s | 5/5 · 30 s | 5/5 · 30 s |

## Overall

| Detector | Faults detected | Median MTTD (s) | Wrong automated events | False alarms / 24 h (automated) | False alarms / 24 h (notify-only) |
| --- | --- | --- | --- | --- | --- |
| D0 | 30/40 | 155 | 0 | 0.00 | 0.00 |
| D1 | 31/40 | 90 | 0 | 0.00 | 12.99 |
| D2 | 35/40 | 80 | 0 | 0.00 | 14.99 |
| D1H | 40/40 | 75 | 0 | 0.00 | 12.99 |
| D2H | 40/40 | 75 | 0 | 0.00 | 14.99 |
