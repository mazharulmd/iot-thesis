E2 load test on AWS IoT Core, eu-north-1, 19.11.2026. Virtual gateways on an EC2 instance in the same
region, one message per gateway every 10 s, 50 gateways per MQTT connection; 3 min warm-up and 30 min
measured per level. Latency percentiles are upper edges of histogram buckets (…75, 100, 150 ms…).
Loss is (sent − processed) / sent in the measured window; ±0.01 % comes from messages in flight at
the window edges.

| Gateways | Sent/s | Processed/s | Loss | p50 ms | p95 ms | p99 ms | Gateway→IoT ms | IoT→Lambda ms | Handler ms | Lambda p95 ms | Peak concurrency | Throttles (Lambda / DynamoDB) | Rule failures |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 50 | 5.0 | 5.0 | 0.0 % | 100 | 100 | 150 | 6 | 59 | 13 | 44 | 1 | 0 / 0 | 0 |
| 500 | 50.0 | 50.0 | -0.01 % | 100 | 100 | 150 | 6 | 60 | 11 | 41 | 11 | 0 / 0 | 0 |
| 2,000 | 200.02 | 200.0 | 0.01 % | 100 | 100 | 150 | 6 | 64 | 12 | 41 | 43 | 0 / 0 | 0 |

Extrapolation to 10,000 gateways (1,000 messages/s): the detector needs about 29 concurrent executions at the measured average duration of 29 ms (concurrency = rate x duration); this account allows 400.
Scaling the measured peak concurrency (43 at 2,000 gateways) linearly instead gives about 215, a conservative bound because the peak includes bursts and container start-ups.

Messages sent: 9,901 (50), 99,010 (500) and 396,080 (2,000) in the measured windows.
