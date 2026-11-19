Monthly cost in USD (2026-09 (list prices; verify for eu-north-1); usage: measured on AWS, 2000 gateways).

| Service | small (1 hall) | medium (10 halls) | large (100 halls) |
| --- | --- | --- | --- |
| IoT Core (messages, rule, 2 actions, shadows) | 1.90 | 18.97 | 189.66 |
| Lambda (detector + remediation) | 0.57 | 5.69 | 56.93 |
| DynamoDB on demand (requests + storage) | 2.27 | 22.67 | 226.69 |
| Step Functions (Standard) | 0.01 | 0.09 | 0.90 |
| EventBridge + SNS | 0.00 | 0.01 | 0.09 |
| CloudWatch Logs | 0.24 | 2.40 | 24.04 |
| **Total at list price** | **4.98** | **49.83** | **498.30** |
| Total after always-free allowances | 3.75 | 39.30 | 482.56 |
| Per rack per month (list price) | 0.249 | 0.249 | 0.249 |

DynamoDB requests on demand vs provisioned capacity sized to the load (50 % headroom):

| | small (1 hall) | medium (10 halls) | large (100 halls) |
| --- | --- | --- | --- |
| Telemetry messages per month | 1,296,000 | 12,960,000 | 129,600,000 |
| On demand (requests) | 1.78 | 17.81 | 178.09 |
| Provisioned (WCU / RCU) | 1.04 (2 / 1) | 7.88 (15 / 8) | 78.29 (150 / 75) |
| Provisioned after the 25/25 always-free units | 0.00 | 0.00 | 64.06 |

Assumed remediation activity per hall and month: automated incidents 5, notify incidents 30, correlated events per incident 3, transitions per automated 30, transitions per notify 5, transitions per correlated 4, remediation invocations per automated 12, remediation ms 150, remediation mb 256, shadow operations per automated 12, emails per automated 2, emails per notify 1.
