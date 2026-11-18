Ranking check: the later mode is significantly slower in **0** of 48 comparisons (Mann–Whitney U, Holm-corrected across the 24 fault × level cells per comparison; MTTR censored at 45 min).

| Fault | Level | Severity | M1 → M2 (automation) | M2 → M3 (ML detection) |
| --- | --- | --- | --- | --- |
| crah_fan_failure | L1 | 40 % of racks busy | **M2 faster** (12.8 → 0.8 min, p = 0.003) | no difference (0.8 vs 0.8 min) |
| crah_fan_failure | L2 | 80 % of racks busy (E1) | **M2 faster** (12.7 → 1.0 min, p = 0.003) | no difference (1.0 vs 1.0 min) |
| crah_fan_failure | L3 | all racks busy | **M2 faster** (13.0 → 1.1 min, p = 0.003) | no difference (1.1 vs 1.1 min) |
| rack_hotspot | L1 | 50 % local airflow loss | no difference (0.0 vs 0.0 min) | no difference (0.0 vs 0.0 min) |
| rack_hotspot | L2 | 65 % local airflow loss (E1) | **M2 faster** (12.5 → 0.8 min, p = 0.004) | no difference (0.8 vs 0.8 min) |
| rack_hotspot | L3 | 80 % local airflow loss | no difference (> 45 vs > 45 min) | no difference (> 45 vs > 45 min) |
| chw_supply_drift | L1 | +4 K over 10 min | **M2 faster** (20.1 → 8.2 min, p = 0.003) | **M3 faster** (8.2 → 1.4 min, p = 0.002) |
| chw_supply_drift | L2 | +7 K over 10 min (E1) | **M2 faster** (16.7 → 4.9 min, p = 0.003) | **M3 faster** (4.9 → 1.7 min, p = 0.002) |
| chw_supply_drift | L3 | +10 K over 10 min | **M2 faster** (15.3 → 3.7 min, p = 0.003) | **M3 faster** (3.7 → 1.3 min, p = 0.002) |
| pump_degradation | L1 | 40 % health lost over 30 min | no difference (> 45 vs > 45 min) | **M3 faster** (> 45 → 0.0 min, p = 0.0004) |
| pump_degradation | L2 | 60 % health lost over 30 min (E1) | no difference (> 45 vs > 45 min) | **M3 faster** (> 45 → 0.0 min, p = 0.0004) |
| pump_degradation | L3 | 80 % health lost over 30 min | no difference (> 45 vs > 45 min) | **M3 faster** (> 45 → 0.0 min, p = 0.0004) |
| sensor_stuck | L1 | frozen at the true value (E1) | no difference (0.0 vs 0.0 min) | no difference (0.0 vs 0.0 min) |
| sensor_stuck | L2 | frozen 3 K below the true value | no difference (> 45 vs > 45 min) | **M3 faster** (> 45 → 1.0 min, p = 0.0004) |
| sensor_stuck | L3 | frozen 6 K below the true value | no difference (> 45 vs > 45 min) | **M3 faster** (> 45 → 1.0 min, p = 0.0004) |
| sensor_drift | L1 | 0.25 K/min | **M2 faster** (37.7 → 26.1 min, p = 0.003) | **M3 faster** (26.1 → 4.1 min, p = 0.002) |
| sensor_drift | L2 | 0.5 K/min (E1) | **M2 faster** (25.1 → 13.3 min, p = 0.003) | **M3 faster** (13.3 → 2.3 min, p = 0.002) |
| sensor_drift | L3 | 1 K/min | **M2 faster** (18.8 → 7.0 min, p = 0.003) | **M3 faster** (7.0 → 1.5 min, p = 0.002) |
| ups_battery_overheat | L1 | 0.5 K/min at half load | no difference (> 45 vs > 45 min) | **M3 faster** (> 45 → 0.0 min, p = 0.002) |
| ups_battery_overheat | L2 | 1 K/min at half load (E1) | no difference (39.2 vs 39.2 min) | **M3 faster** (39.2 → 0.0 min, p = 0.01) |
| ups_battery_overheat | L3 | 2 K/min at half load | no difference (41.8 vs 41.8 min) | no difference (41.8 vs 28.3 min) |
| pdu_overload | L1 | racks at 106 % of rating | no difference (12.6 vs 12.6 min) | no difference (12.6 vs 12.5 min) |
| pdu_overload | L2 | racks at 112 % of rating (E1) | no difference (12.7 vs 12.7 min) | no difference (12.7 vs 12.5 min) |
| pdu_overload | L3 | racks at 118 % of rating | no difference (12.6 vs 12.6 min) | no difference (12.6 vs 12.5 min) |

### All cells

| Fault | Level | Severity | Mode | Runs | Detected | Recovered | Median MTTD (s) | Median MTTR (min) [95 % CI] | Median exposure | Wrong actions |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| crah_fan_failure | L1 | 40 % of racks busy | M1 | 10 | 100 % | 100 % | 30 | 12.8 [5.8, 16.8] | 618.4 K·min | 0 |
| crah_fan_failure | L1 | 40 % of racks busy | M2 | 10 | 100 % | 100 % | 30 | 0.8 [0.8, 1.2] | 16.7 K·min | 0 |
| crah_fan_failure | L1 | 40 % of racks busy | M3 | 10 | 100 % | 100 % | 30 | 0.8 [0.8, 1.2] | 16.7 K·min | 0 |
| crah_fan_failure | L2 | 80 % of racks busy (E1) | M1 | 10 | 100 % | 100 % | 30 | 12.7 [6.8, 17.2] | 641.6 K·min | 0 |
| crah_fan_failure | L2 | 80 % of racks busy (E1) | M2 | 10 | 100 % | 100 % | 30 | 1.0 [0.8, 1.7] | 16.7 K·min | 0 |
| crah_fan_failure | L2 | 80 % of racks busy (E1) | M3 | 10 | 100 % | 100 % | 30 | 1.0 [0.8, 1.7] | 16.7 K·min | 0 |
| crah_fan_failure | L3 | all racks busy | M1 | 10 | 100 % | 100 % | 30 | 13.0 [7.8, 17.2] | 623.8 K·min | 0 |
| crah_fan_failure | L3 | all racks busy | M2 | 10 | 100 % | 100 % | 30 | 1.1 [0.8, 1.7] | 17.8 K·min | 0 |
| crah_fan_failure | L3 | all racks busy | M3 | 10 | 100 % | 100 % | 30 | 1.1 [0.8, 1.7] | 17.8 K·min | 0 |
| rack_hotspot | L1 | 50 % local airflow loss | M1 | 10 | 0 % | 100 % | – | 0.0 [0.0, 0.0] | 0.0 K·min | 0 |
| rack_hotspot | L1 | 50 % local airflow loss | M2 | 10 | 0 % | 100 % | – | 0.0 [0.0, 0.0] | 0.0 K·min | 0 |
| rack_hotspot | L1 | 50 % local airflow loss | M3 | 10 | 100 % | 100 % | 30 | 0.0 [0.0, 0.0] | 0.0 K·min | 0 |
| rack_hotspot | L2 | 65 % local airflow loss (E1) | M1 | 10 | 100 % | 100 % | 30 | 12.5 [7.8, 17.0] | 16.7 K·min | 0 |
| rack_hotspot | L2 | 65 % local airflow loss (E1) | M2 | 10 | 100 % | 100 % | 30 | 0.8 [0.8, 2.0] | 0.9 K·min | 0 |
| rack_hotspot | L2 | 65 % local airflow loss (E1) | M3 | 10 | 100 % | 100 % | 30 | 0.8 [0.8, 2.0] | 0.9 K·min | 0 |
| rack_hotspot | L3 | 80 % local airflow loss | M1 | 10 | 100 % | 30 % | 30 | > 45 [41.1, > 45] | 67.9 K·min | 0 |
| rack_hotspot | L3 | 80 % local airflow loss | M2 | 10 | 100 % | 10 % | 30 | > 45 [> 45, > 45] | 130.6 K·min | 0 |
| rack_hotspot | L3 | 80 % local airflow loss | M3 | 10 | 100 % | 10 % | 30 | > 45 [> 45, > 45] | 130.6 K·min | 0 |
| chw_supply_drift | L1 | +4 K over 10 min | M1 | 10 | 100 % | 100 % | 485 | 20.1 [13.5, 23.1] | 41.2 K·min | 0 |
| chw_supply_drift | L1 | +4 K over 10 min | M2 | 10 | 100 % | 100 % | 485 | 8.2 [8.0, 8.5] | 6.4 K·min | 0 |
| chw_supply_drift | L1 | +4 K over 10 min | M3 | 10 | 100 % | 100 % | 155 | 1.4 [0.0, 2.9] | 0.0 K·min | 0 |
| chw_supply_drift | L2 | +7 K over 10 min (E1) | M1 | 10 | 100 % | 100 % | 285 | 16.7 [10.2, 20.6] | 65.1 K·min | 0 |
| chw_supply_drift | L2 | +7 K over 10 min (E1) | M2 | 10 | 100 % | 100 % | 285 | 4.9 [4.8, 5.0] | 4.0 K·min | 0 |
| chw_supply_drift | L2 | +7 K over 10 min (E1) | M3 | 10 | 100 % | 100 % | 90 | 1.7 [0.8, 1.8] | 0.0 K·min | 0 |
| chw_supply_drift | L3 | +10 K over 10 min | M1 | 10 | 100 % | 100 % | 210 | 15.3 [10.2, 19.2] | 87.6 K·min | 0 |
| chw_supply_drift | L3 | +10 K over 10 min | M2 | 10 | 100 % | 100 % | 210 | 3.7 [3.5, 3.7] | 3.3 K·min | 0 |
| chw_supply_drift | L3 | +10 K over 10 min | M3 | 10 | 100 % | 100 % | 70 | 1.3 [1.3, 1.3] | 0.0 K·min | 0 |
| pump_degradation | L1 | 40 % health lost over 30 min | M1 | 10 | 0 % | 0 % | – | > 45 [> 45, > 45] | 102.4 (L/s + mm/s)·min | 0 |
| pump_degradation | L1 | 40 % health lost over 30 min | M2 | 10 | 0 % | 0 % | – | > 45 [> 45, > 45] | 102.4 (L/s + mm/s)·min | 0 |
| pump_degradation | L1 | 40 % health lost over 30 min | M3 | 10 | 100 % | 100 % | 230 | 0.0 [0.0, 0.0] | 0.0 (L/s + mm/s)·min | 0 |
| pump_degradation | L2 | 60 % health lost over 30 min (E1) | M1 | 10 | 0 % | 0 % | – | > 45 [> 45, > 45] | 255.3 (L/s + mm/s)·min | 0 |
| pump_degradation | L2 | 60 % health lost over 30 min (E1) | M2 | 10 | 0 % | 0 % | – | > 45 [> 45, > 45] | 255.3 (L/s + mm/s)·min | 0 |
| pump_degradation | L2 | 60 % health lost over 30 min (E1) | M3 | 10 | 100 % | 100 % | 180 | 0.0 [0.0, 0.0] | 0.0 (L/s + mm/s)·min | 0 |
| pump_degradation | L3 | 80 % health lost over 30 min | M1 | 10 | 0 % | 0 % | – | > 45 [> 45, > 45] | 422.7 (L/s + mm/s)·min | 0 |
| pump_degradation | L3 | 80 % health lost over 30 min | M2 | 10 | 0 % | 0 % | – | > 45 [> 45, > 45] | 422.7 (L/s + mm/s)·min | 0 |
| pump_degradation | L3 | 80 % health lost over 30 min | M3 | 10 | 100 % | 100 % | 140 | 0.0 [0.0, 0.0] | 0.0 (L/s + mm/s)·min | 0 |
| sensor_stuck | L1 | frozen at the true value (E1) | M1 | 10 | 0 % | 100 % | – | 0.0 [0.0, 0.0] | 0.0 K·min | 0 |
| sensor_stuck | L1 | frozen at the true value (E1) | M2 | 10 | 0 % | 100 % | – | 0.0 [0.0, 0.0] | 0.0 K·min | 0 |
| sensor_stuck | L1 | frozen at the true value (E1) | M3 | 10 | 100 % | 100 % | 70 | 0.0 [0.0, 0.0] | 0.0 K·min | 0 |
| sensor_stuck | L2 | frozen 3 K below the true value | M1 | 10 | 0 % | 0 % | – | > 45 [> 45, > 45] | 91.4 K·min | 0 |
| sensor_stuck | L2 | frozen 3 K below the true value | M2 | 10 | 0 % | 0 % | – | > 45 [> 45, > 45] | 91.4 K·min | 0 |
| sensor_stuck | L2 | frozen 3 K below the true value | M3 | 10 | 100 % | 100 % | 50 | 1.0 [1.0, 1.0] | 2.0 K·min | 0 |
| sensor_stuck | L3 | frozen 6 K below the true value | M1 | 10 | 0 % | 0 % | – | > 45 [> 45, > 45] | 226.9 K·min | 0 |
| sensor_stuck | L3 | frozen 6 K below the true value | M2 | 10 | 0 % | 0 % | – | > 45 [> 45, > 45] | 226.9 K·min | 0 |
| sensor_stuck | L3 | frozen 6 K below the true value | M3 | 10 | 100 % | 100 % | 50 | 1.0 [1.0, 1.0] | 5.0 K·min | 0 |
| sensor_drift | L1 | 0.25 K/min | M1 | 10 | 100 % | 90 % | 1555 | 37.7 [31.2, 40.8] | 141.0 K·min | 0 |
| sensor_drift | L1 | 0.25 K/min | M2 | 10 | 100 % | 100 % | 1555 | 26.1 [25.8, 26.3] | 60.4 K·min | 0 |
| sensor_drift | L1 | 0.25 K/min | M3 | 10 | 100 % | 100 % | 235 | 4.1 [3.7, 4.2] | 0.0 K·min | 0 |
| sensor_drift | L2 | 0.5 K/min (E1) | M1 | 10 | 100 % | 100 % | 790 | 25.1 [18.6, 28.9] | 132.3 K·min | 0 |
| sensor_drift | L2 | 0.5 K/min (E1) | M2 | 10 | 100 % | 100 % | 790 | 13.3 [13.3, 13.4] | 31.7 K·min | 0 |
| sensor_drift | L2 | 0.5 K/min (E1) | M3 | 10 | 100 % | 100 % | 130 | 2.3 [2.2, 2.5] | 0.0 K·min | 0 |
| sensor_drift | L3 | 1 K/min | M1 | 10 | 100 % | 100 % | 410 | 18.8 [13.4, 22.0] | 149.2 K·min | 0 |
| sensor_drift | L3 | 1 K/min | M2 | 10 | 100 % | 100 % | 410 | 7.0 [7.0, 7.0] | 17.5 K·min | 0 |
| sensor_drift | L3 | 1 K/min | M3 | 10 | 100 % | 100 % | 80 | 1.5 [1.3, 1.5] | 0.1 K·min | 0 |
| ups_battery_overheat | L1 | 0.5 K/min at half load | M1 | 10 | 90 % | 40 % | 2180 | > 45 [42.2, > 45] | 4.7 K·min | 0 |
| ups_battery_overheat | L1 | 0.5 K/min at half load | M2 | 10 | 90 % | 40 % | 2180 | > 45 [41.7, > 45] | 4.7 K·min | 0 |
| ups_battery_overheat | L1 | 0.5 K/min at half load | M3 | 10 | 100 % | 100 % | 140 | 0.0 [0.0, 0.0] | 0.0 K·min | 0 |
| ups_battery_overheat | L2 | 1 K/min at half load (E1) | M1 | 10 | 100 % | 80 % | 825 | 39.2 [26.6, 43.3] | 62.6 K·min | 0 |
| ups_battery_overheat | L2 | 1 K/min at half load (E1) | M2 | 10 | 100 % | 80 % | 825 | 39.2 [29.0, 43.2] | 62.6 K·min | 0 |
| ups_battery_overheat | L2 | 1 K/min at half load (E1) | M3 | 10 | 100 % | 100 % | 80 | 0.0 [0.0, 23.2] | 0.0 K·min | 0 |
| ups_battery_overheat | L3 | 2 K/min at half load | M1 | 10 | 100 % | 60 % | 390 | 41.8 [28.1, > 45] | 208.6 K·min | 0 |
| ups_battery_overheat | L3 | 2 K/min at half load | M2 | 10 | 100 % | 60 % | 390 | 41.8 [28.1, > 45] | 208.6 K·min | 0 |
| ups_battery_overheat | L3 | 2 K/min at half load | M3 | 10 | 100 % | 80 % | 50 | 28.3 [11.5, 40.7] | 75.1 K·min | 0 |
| pdu_overload | L1 | racks at 106 % of rating | M1 | 10 | 100 % | 100 % | 40 | 12.6 [7.4, 14.7] | 21.2 %·min | 0 |
| pdu_overload | L1 | racks at 106 % of rating | M2 | 10 | 100 % | 100 % | 40 | 12.6 [7.4, 16.3] | 21.2 %·min | 0 |
| pdu_overload | L1 | racks at 106 % of rating | M3 | 10 | 100 % | 100 % | 40 | 12.5 [6.0, 15.8] | 21.1 %·min | 0 |
| pdu_overload | L2 | racks at 112 % of rating (E1) | M1 | 10 | 100 % | 100 % | 40 | 12.7 [6.1, 15.9] | 85.1 %·min | 0 |
| pdu_overload | L2 | racks at 112 % of rating (E1) | M2 | 10 | 100 % | 100 % | 40 | 12.7 [6.1, 16.3] | 85.1 %·min | 0 |
| pdu_overload | L2 | racks at 112 % of rating (E1) | M3 | 10 | 100 % | 100 % | 30 | 12.5 [6.0, 16.2] | 83.9 %·min | 0 |
| pdu_overload | L3 | racks at 118 % of rating | M1 | 10 | 100 % | 100 % | 30 | 12.6 [6.2, 15.8] | 148.2 %·min | 0 |
| pdu_overload | L3 | racks at 118 % of rating | M2 | 10 | 100 % | 100 % | 30 | 12.6 [5.4, 14.8] | 148.2 %·min | 0 |
| pdu_overload | L3 | racks at 118 % of rating | M3 | 10 | 100 % | 100 % | 30 | 12.5 [6.1, 15.8] | 147.2 %·min | 0 |
