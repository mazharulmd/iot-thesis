### Load surges (normal operation, a zone swings from idle to full load)

| Mode | Runs | False remediations | Commands sent | Alerts / run (median) |
| --- | --- | --- | --- | --- |
| M1 | 20 | 0 | 0 | 0 |
| M2 | 20 | 0 | 0 | 0 |
| M3 | 20 | 0 | 0 | 1 |

### Physical fault while a rack sensor is already faulty

| Combination | Mode | Runs | Detected | Recovered | Median MTTR (min) | Median exposure | Wrong actions |
| --- | --- | --- | --- | --- | --- | --- | --- |
| chw_with_drifting_rack12 | M1 | 10 | 100 % | 100 % | 16.7 | 65.1 | 0 |
| chw_with_drifting_rack12 | M2 | 10 | 100 % | 100 % | 4.9 | 4.0 | 0 |
| chw_with_drifting_rack12 | M3 | 10 | 100 % | 100 % | 1.7 | 0.0 | 0 |
| crah2_with_stuck_rack07 | M1 | 10 | 100 % | 100 % | 12.7 | 641.6 | 0 |
| crah2_with_stuck_rack07 | M2 | 10 | 100 % | 100 % | 1.0 | 16.7 | 0 |
| crah2_with_stuck_rack07 | M3 | 10 | 100 % | 100 % | 1.0 | 16.7 | 0 |

### Message loss between gateways and cloud (all 8 fault types)

| Lost messages | Mode | Runs | Detected | Recovered | Median MTTD (s) | Median MTTR (min) | Wrong actions |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 5% | M2 | 80 | 75 % | 85 % | 215 | 5.8 | 0 |
| 5% | M3 | 80 | 100 % | 100 % | 90 | 1.7 | 0 |
| 10% | M2 | 80 | 75 % | 85 % | 275 | 7.4 | 0 |
| 10% | M3 | 80 | 100 % | 100 % | 100 | 1.8 | 0 |
| 20% | M2 | 80 | 75 % | 82 % | 400 | 13.6 | 0 |
| 20% | M3 | 80 | 100 % | 99 % | 180 | 3.4 | 0 |
