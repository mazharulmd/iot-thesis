Monthly cost in USD (2026-09 (list prices; verify for ap-south-1); usage: defaults (not yet measured on AWS)).

| Service | small (1 hall) | medium (10 halls) | large (100 halls) |
| --- | --- | --- | --- |
| IoT Core (messages, rule, 2 actions, shadows) | 1.90 | 18.97 | 189.66 |
| Lambda (detector + remediation) | 0.91 | 9.07 | 90.73 |
| DynamoDB on demand (requests + storage) | 3.24 | 32.40 | 324.00 |
| Step Functions (Standard) | 0.01 | 0.09 | 0.90 |
| EventBridge + SNS | 0.00 | 0.01 | 0.09 |
| CloudWatch Logs | 0.24 | 2.40 | 24.04 |
| **Total at list price** | **6.29** | **62.94** | **629.42** |
| Total after always-free allowances | 4.72 | 49.03 | 613.68 |
| Per rack per month (list price) | 0.315 | 0.315 | 0.315 |

DynamoDB requests on demand vs provisioned capacity sized to the load (50 % headroom):

| | small (1 hall) | medium (10 halls) | large (100 halls) |
| --- | --- | --- | --- |
| Telemetry messages per month | 1,296,000 | 12,960,000 | 129,600,000 |
| On demand (requests) | 2.75 | 27.54 | 275.40 |
| Provisioned (WCU / RCU) | 1.61 (3 / 2) | 12.34 (23 / 15) | 121.00 (225 / 150) |
| Provisioned after the 25/25 always-free units | 0.00 | 0.00 | 106.76 |

Assumed remediation activity per hall and month: automated incidents 5, notify incidents 30, correlated events per incident 3, transitions per automated 30, transitions per notify 5, transitions per correlated 4, remediation invocations per automated 12, remediation ms 150, remediation mb 256, shadow operations per automated 12, emails per automated 2, emails per notify 1.
