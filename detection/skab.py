"""External validation on SKAB (Skoltech Anomaly Benchmark), a real water-pump testbed.

    python -m detection.skab

Follows SKAB's own leaderboard protocol so results are comparable:
  - each of the 34 labelled experiments is split into the first 400 rows (train,
    normal operation) and the rest (test)
  - pointwise evaluation on the test parts: F1, false alarm rate (FAR), missed alarm rate (MAR)
The same detector families as in the thesis are used (window length, features,
LSTM autoencoder architecture). Thresholds are a quantile of each file's training scores.
The data (GPL-3.0) is downloaded on first use and is not redistributed with this project.
"""
from __future__ import annotations

import argparse
import subprocess
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from .data import CACHE
from .features import WINDOW, window_features, windows
from .lstm_jax import train_autoencoder
from .models import ae_errors

REPO = "https://github.com/waico/SKAB"
DATA = CACHE / "SKAB" / "data"
RESULTS = Path(__file__).resolve().parent / "results"
TRAIN_ROWS = 400
LEADERBOARD = [  # from the SKAB README, outlier detection problem (test set)
    ("Conv-AE", 0.78, 13.55, 28.02), ("MSET", 0.78, 39.73, 14.13),
    ("T-squared+Q (PCA)", 0.76, 26.62, 24.92), ("LSTM-AE", 0.74, 29.96, 25.92),
    ("T-squared", 0.66, 19.21, 42.60), ("Isolation forest", 0.29, 2.56, 82.89),
]


def ensure_data() -> None:
    if not DATA.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", "--depth", "1", REPO, str(CACHE / "SKAB")], check=True)


def load_files() -> list[tuple[str, pd.DataFrame]]:
    files = sorted(p for sub in ("valve1", "valve2", "other") for p in (DATA / sub).glob("*.csv"))
    return [(f"{p.parent.name}/{p.stem}", pd.read_csv(p, sep=";", index_col="datetime")) for p in files]


def to_points(win_flags: np.ndarray, n_points: int) -> np.ndarray:
    """Window j ends at point j + WINDOW - 1; earlier points cannot be scored."""
    out = np.zeros(n_points, dtype=bool)
    out[WINDOW - 1:] = win_flags
    return out


def confirm(flags: np.ndarray, k: int) -> np.ndarray:
    if k <= 1:
        return flags
    out = np.zeros_like(flags)
    for i in range(k - 1, len(flags)):
        out[i] = flags[i - k + 1:i + 1].all()
    return out


def score_file(df: pd.DataFrame, quantile: float, epochs: int, seed: int) -> dict[str, np.ndarray]:
    x = df.drop(columns=["anomaly", "changepoint"]).to_numpy(float)
    mu, sd = x[:TRAIN_ROWS].mean(0), np.maximum(x[:TRAIN_ROWS].std(0), 1e-6)
    z = (x - mu) / sd
    win = windows(z)
    train_w = np.arange(len(win)) + WINDOW - 1 < TRAIN_ROWS

    d0 = (np.abs(z) > 3.0).any(axis=1)                          # classic +-3 sigma control limits

    feats = window_features(win)
    f_mu, f_sd = feats[train_w].mean(0), np.maximum(feats[train_w].std(0), 1e-6)
    f = (feats - f_mu) / f_sd
    forest = IsolationForest(n_estimators=100, max_samples=min(256, int(train_w.sum())),
                             random_state=seed).fit(f[train_w])
    s1 = -forest.score_samples(f)
    d1 = to_points(s1 > np.quantile(s1[train_w], quantile), len(z))

    params, _ = train_autoencoder(win[train_w], hidden=16, latent=4, epochs=epochs, batch=32,
                                  seed=seed, log=lambda *_: None)
    s2 = ae_errors(params, win).mean(axis=1)
    d2 = to_points(s2 > np.quantile(s2[train_w], quantile), len(z))
    return {"d0": d0, "d1": d1, "d2": d2, "d1h": d1 | d0, "d2h": d2 | d0}


def metrics(y: np.ndarray, p: np.ndarray) -> dict:
    tp, fp = int((p & y).sum()), int((p & ~y).sum())
    fn, tn = int((~p & y).sum()), int((~p & ~y).sum())
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"f1": f1, "far_pct": 100.0 * fp / max(fp + tn, 1), "mar_pct": 100.0 * fn / max(fn + tp, 1)}


def main() -> None:
    ap = argparse.ArgumentParser(description="SKAB validation of the detector families")
    ap.add_argument("--quantile", type=float, default=0.99, help="threshold quantile of training scores")
    ap.add_argument("--epochs", type=int, default=40)
    args = ap.parse_args()
    t0 = time.time()
    ensure_data()
    files = load_files()
    print(f"SKAB: {len(files)} labelled experiments, train = first {TRAIN_ROWS} rows of each", flush=True)

    preds = {k: {d: [] for d in ("d0", "d1", "d2", "d1h", "d2h")} for k in (1, 3)}
    labels = []
    for i, (name, df) in enumerate(files):
        flags = score_file(df, args.quantile, args.epochs, seed=i)
        y = df["anomaly"].to_numpy() > 0.5
        labels.append(y[TRAIN_ROWS:])
        for k in preds:
            for d, fl in flags.items():
                preds[k][d].append(confirm(fl, k)[TRAIN_ROWS:])
        print(f"  {i + 1:2d}/{len(files)} {name}", flush=True)

    y = np.concatenate(labels)
    rows = []
    for k in preds:
        for d in preds[k]:
            m = metrics(y, np.concatenate(preds[k][d]))
            rows.append({"detector": d, "confirm": k, **m})
    res = pd.DataFrame(rows)
    RESULTS.mkdir(parents=True, exist_ok=True)
    res.to_csv(RESULTS / "skab_results.csv", index=False)

    names = {"d0": "D0 ±3σ limits", "d1": "D1 Isolation Forest", "d2": "D2 LSTM autoencoder",
             "d1h": "D1h hybrid", "d2h": "D2h hybrid"}
    lines = [f"## SKAB test set ({len(files)} experiments, {len(y)} points, {int(y.sum())} anomalous)", "",
             "| Detector | F1 (k=1) | FAR % (k=1) | MAR % (k=1) | F1 (k=3) | FAR % (k=3) | MAR % (k=3) |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for d, label in names.items():
        a = res[(res.detector == d) & (res.confirm == 1)].iloc[0]
        b = res[(res.detector == d) & (res.confirm == 3)].iloc[0]
        lines.append(f"| {label} | {a.f1:.2f} | {a.far_pct:.1f} | {a.mar_pct:.1f} | "
                     f"{b.f1:.2f} | {b.far_pct:.1f} | {b.mar_pct:.1f} |")
    lines += ["", "k = consecutive anomalous points required (k=1 matches the SKAB leaderboard; "
              "k=3 is the setting used in this thesis).", "",
              "SKAB leaderboard for reference (outlier detection, test set, from the SKAB README):", "",
              "| Algorithm | F1 | FAR % | MAR % |", "| --- | --- | --- | --- |"]
    lines += [f"| {n} | {f:.2f} | {fa:.2f} | {ma:.2f} |" for n, f, fa, ma in LEADERBOARD]
    summary = "\n".join(lines)
    (RESULTS / "skab_summary.md").write_text(summary + "\n")
    print("\n" + summary + f"\n\nwrote {RESULTS}/skab_*.* in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
