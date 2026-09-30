## SKAB test set (34 experiments, 23801 points, 12771 anomalous)

| Detector | F1 (k=1) | FAR % (k=1) | MAR % (k=1) | F1 (k=3) | FAR % (k=3) | MAR % (k=3) |
| --- | --- | --- | --- | --- | --- | --- |
| D0 ±3σ limits | 0.76 | 44.1 | 15.4 | 0.74 | 40.4 | 20.0 |
| D1 Isolation Forest | 0.50 | 13.2 | 63.1 | 0.34 | 4.3 | 78.6 |
| D2 LSTM autoencoder | 0.77 | 55.9 | 7.4 | 0.77 | 51.0 | 8.9 |
| D1h hybrid | 0.76 | 47.3 | 13.1 | 0.75 | 41.9 | 18.1 |
| D2h hybrid | 0.77 | 58.2 | 6.8 | 0.77 | 52.8 | 8.2 |

k = consecutive anomalous points required (k=1 matches the SKAB leaderboard; k=3 is the setting used in this thesis).

SKAB leaderboard for reference (outlier detection, test set, from the SKAB README):

| Algorithm | F1 | FAR % | MAR % |
| --- | --- | --- | --- |
| Conv-AE | 0.78 | 13.55 | 28.02 |
| MSET | 0.78 | 39.73 | 14.13 |
| T-squared+Q (PCA) | 0.76 | 26.62 | 24.92 |
| LSTM-AE | 0.74 | 29.96 | 25.92 |
| T-squared | 0.66 | 19.21 | 42.60 |
| Isolation forest | 0.29 | 2.56 | 82.89 |
