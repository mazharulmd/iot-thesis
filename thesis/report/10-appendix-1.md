# Appendix 1: Statistical tests of experiment E1

The tables compare the operating modes per fault type with two-sided Mann–Whitney U tests on the 20 paired runs of each cell. The p-values are Holm-adjusted across the eight fault types. A positive rank-biserial correlation r means that the first mode had larger, that is worse, values. A mode is marked better only when the adjusted p-value is below 0.05. Time to recover is in minutes, censored at 45 minutes; exposure is in the fault's own unit multiplied by minutes.

Table A1. Time to recover: M1 against M2 (effect of automation)

| Fault | Median M1 | Median M2 | Adjusted p | r | Better |
| --- | --- | --- | --- | --- | --- |
| CRAH fan failure | 11.5 | 1.0 | 3.6e-07 | +1.00 | M2 |
| Rack hotspot | 11.8 | 0.8 | 6.1e-07 | +0.97 | M2 |
| Chilled-water drift | 15.0 | 5.0 | 3.6e-07 | +1.00 | M2 |
| Pump degradation | > 45 | > 45 | 1 | +0.00 | – |
| Stuck sensor | 0.0 | 0.0 | 1 | +0.00 | – |
| Drifting sensor | 23.2 | 13.3 | 3.6e-07 | +1.00 | M2 |
| UPS battery overheat | 35.4 | 35.4 | 1 | +0.00 | – |
| PDU overload | 10.8 | 10.8 | 1 | +0.00 | – |

Table A2. Time to recover: M2 against M3 (effect of ML detection)

| Fault | Median M2 | Median M3 | Adjusted p | r | Better |
| --- | --- | --- | --- | --- | --- |
| CRAH fan failure | 1.0 | 1.0 | 1 | +0.00 | – |
| Rack hotspot | 0.8 | 0.8 | 1 | +0.00 | – |
| Chilled-water drift | 5.0 | 1.7 | 2.5e-07 | +1.00 | M3 |
| Pump degradation | > 45 | 0.0 | 3.7e-09 | +1.00 | M3 |
| Stuck sensor | 0.0 | 0.0 | 1 | +0.00 | – |
| Drifting sensor | 13.3 | 2.3 | 2.5e-07 | +1.00 | M3 |
| UPS battery overheat | 35.4 | 0.0 | 2.2e-06 | +0.92 | M3 |
| PDU overload | 10.8 | 10.7 | 1 | +0.05 | – |

Table A3. Exposure: M1 against M2 (effect of automation)

| Fault | Median M1 | Median M2 | Adjusted p | r | Better |
| --- | --- | --- | --- | --- | --- |
| CRAH fan failure | 641.3 | 17.0 | 4.8e-07 | +1.00 | M2 |
| Rack hotspot | 17.2 | 1.0 | 4.8e-07 | +1.00 | M2 |
| Chilled-water drift | 55.1 | 4.2 | 3.6e-07 | +1.00 | M2 |
| Pump degradation | 255.3 | 255.3 | 1 | +0.00 | – |
| Stuck sensor | 0.0 | 0.0 | 1 | +0.00 | – |
| Drifting sensor | 111.4 | 31.7 | 4.8e-07 | +1.00 | M2 |
| UPS battery overheat | 53.2 | 53.2 | 1 | +0.00 | – |
| PDU overload | 72.7 | 72.7 | 1 | +0.00 | – |

Table A4. Exposure: M2 against M3 (effect of ML detection)

| Fault | Median M2 | Median M3 | Adjusted p | r | Better |
| --- | --- | --- | --- | --- | --- |
| CRAH fan failure | 17.0 | 17.0 | 1 | +0.00 | – |
| Rack hotspot | 1.0 | 1.0 | 1 | +0.00 | – |
| Chilled-water drift | 4.2 | 0.0 | 2.5e-07 | +1.00 | M3 |
| Pump degradation | 255.3 | 0.0 | 3.7e-09 | +1.00 | M3 |
| Stuck sensor | 0.0 | 0.0 | 1 | +0.00 | – |
| Drifting sensor | 31.7 | 0.0 | 4.1e-07 | +1.00 | M3 |
| UPS battery overheat | 53.2 | 0.0 | 3e-06 | +0.91 | M3 |
| PDU overload | 72.7 | 71.5 | 1 | +0.05 | – |
