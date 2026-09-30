"""Train D1 (Isolation Forest) and D2 (LSTM autoencoder) on normal operation only.

    python -m detection.train                 # defaults: 8 x 6 h training, 4 x 6 h validation

Steps
  1. simulate normal operation (different seeds = different load and noise)
  2. fit per-asset-type scalers on training data
  3. fit one Isolation Forest and one LSTM autoencoder per asset type
  4. set each threshold at a high quantile of validation scores (normal data only)
  5. write detection/models/bundle.json + bundle.npz

No fault data is used for training or thresholds; faults are only used in evaluation.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
from sklearn.ensemble import IsolationForest

from .data import collect, normal_runs
from .features import CONFIRM, SIGNALS, WINDOW, feature_names, window_features
from .lstm_jax import train_autoencoder
from .models import BUNDLE_DIR, Bundle, ae_errors, average_path_length, if_score

SD_FLOOR = 1e-2


def export_forest(model: IsolationForest) -> tuple[dict, float]:
    """Pad every tree to the same size so NumPy can traverse them together."""
    trees = [e.tree_ for e in model.estimators_]
    width = max(t.node_count for t in trees)
    arrays = {k: np.full((len(trees), width), -1, dtype=np.int32) for k in ("left", "right", "feature")}
    arrays["threshold"] = np.zeros((len(trees), width))
    arrays["path"] = np.zeros((len(trees), width))
    for i, t in enumerate(trees):
        n = t.node_count
        arrays["left"][i, :n] = t.children_left
        arrays["right"][i, :n] = t.children_right
        arrays["feature"][i, :n] = t.feature
        arrays["threshold"][i, :n] = t.threshold
        depth = np.zeros(n)
        for node in range(n):                      # parents always precede children
            for child in (t.children_left[node], t.children_right[node]):
                if child >= 0:
                    depth[child] = depth[node] + 1
        arrays["path"][i, :n] = depth + average_path_length(t.n_node_samples)
    denominator = len(trees) * float(average_path_length(np.array([model.max_samples_]))[0])
    return arrays, denominator


def main() -> None:
    ap = argparse.ArgumentParser(description="Train detectors on normal simulator data")
    ap.add_argument("--hours", type=float, default=6.0, help="hours per simulated run")
    ap.add_argument("--train-seeds", type=int, default=8)
    ap.add_argument("--val-seeds", type=int, default=8)
    ap.add_argument("--quantile", type=float, default=0.9999, help="threshold quantile of validation scores")
    ap.add_argument("--epochs", type=int, default=15)
    ap.add_argument("--max-samples", type=int, default=40000, help="training windows per asset type")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", type=Path, default=BUNDLE_DIR, help="where to write the bundle")
    args = ap.parse_args()
    t0 = time.time()

    train_seeds = list(range(101, 101 + args.train_seeds))
    val_seeds = list(range(201, 201 + args.val_seeds))
    print(f"1. simulating normal operation: {len(train_seeds)} training + {len(val_seeds)} validation runs "
          f"x {args.hours:g} h", flush=True)
    train = collect(normal_runs(train_seeds, args.hours, args.workers))
    val = collect(normal_runs(val_seeds, args.hours, args.workers))
    rng = np.random.default_rng(0)

    meta = {"window": WINDOW, "confirm": CONFIRM, "quantile": args.quantile,
            "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "train_seeds": train_seeds, "val_seeds": val_seeds, "hours_per_run": args.hours,
            "lstm": {"hidden": 16}, "types": {}}
    arrays = {}
    for kind in SIGNALS:
        if kind not in train:
            continue
        tr, va = train[kind], val[kind]
        print(f"2. {kind}: {len(tr['win'])} training windows, {len(va['win'])} validation windows", flush=True)
        base_mu, base_sd = tr["base"].mean(0), np.maximum(tr["base"].std(0), SD_FLOOR)
        feats = window_features(tr["win"])
        feat_mu, feat_sd = feats.mean(0), np.maximum(feats.std(0), SD_FLOOR)

        pick = rng.choice(len(tr["win"]), size=min(args.max_samples, len(tr["win"])), replace=False)
        xf = (feats[pick] - feat_mu) / feat_sd
        forest = IsolationForest(n_estimators=100, max_samples=256, random_state=0).fit(xf)
        f_arrays, denominator = export_forest(forest)

        xs = (tr["win"][pick] - base_mu) / base_sd
        xv = (va["win"] - base_mu) / base_sd
        latent = int(min(4, max(2, len(SIGNALS[kind]))))
        print(f"   LSTM autoencoder: {len(SIGNALS[kind])} signals, hidden 16, latent {latent}", flush=True)
        params, history = train_autoencoder(xs, latent=latent, epochs=args.epochs, x_val=xv, seed=0)

        # thresholds from validation data (normal operation only)
        f_forest = dict(f_arrays, denominator=denominator)
        s1 = if_score((window_features(va["win"]) - feat_mu) / feat_sd, f_forest)
        s2 = ae_errors(params, xv).mean(axis=1)
        thr = {"d1": float(np.quantile(s1, args.quantile)), "d2": float(np.quantile(s2, args.quantile))}
        print(f"   thresholds  d1 {thr['d1']:.4f}   d2 {thr['d2']:.4f}", flush=True)

        meta["types"][kind] = {
            "signals": SIGNALS[kind], "features": feature_names(kind),
            "base_mu": base_mu.tolist(), "base_sd": base_sd.tolist(),
            "feat_mu": feat_mu.tolist(), "feat_sd": feat_sd.tolist(),
            "if_denominator": denominator, "latent": latent,
            "thresholds": thr, "n_train_windows": int(len(tr["win"])), "ae_history": history,
        }
        arrays.update({f"if/{kind}/{k}": v for k, v in f_arrays.items()})
        arrays.update({f"ae/{kind}/{k}": v for k, v in params.items()})

    Bundle(meta, arrays).save(args.out)
    print(f"3. saved {args.out}/bundle.json + bundle.npz in {time.time() - t0:.0f} s", flush=True)


if __name__ == "__main__":
    main()
