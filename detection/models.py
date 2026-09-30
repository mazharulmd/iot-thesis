"""Detector runtimes in plain NumPy (no scikit-learn or JAX needed at inference).

D0  static limits, like a building management system's alarms
D1  Isolation Forest, scored from trees exported from scikit-learn
D2  LSTM autoencoder; `lstm_ae_forward` is also used for training with jax.numpy
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .features import FLAT_STD, FLATLINE_SIGNALS, SIGNALS

# d0 limits only | d1 / d2 pure ML | d1h / d2h hybrid = ML + d0 limits + flatline rule
DETECTORS = ("d0", "d1", "d2", "d1h", "d2h")
BUNDLE_DIR = Path(__file__).resolve().parent / "models"


def flatline_flags(kind: str, win: np.ndarray) -> np.ndarray:
    """win: (P, WINDOW, n). True where a direct sensor reading did not change at all."""
    idx = [SIGNALS[kind].index(s) for s in FLATLINE_SIGNALS.get(kind, [])]
    if not idx:
        return np.zeros(win.shape[0], dtype=bool)
    return (win[:, :, idx].std(axis=1) < FLAT_STD).any(axis=1)


# ---------------------------------------------------------------- D0: static limits
def d0_flags(kind: str, sig: np.ndarray) -> np.ndarray:
    """sig: (..., n_signals) at the scoring points. Returns boolean alarms."""
    s = sig
    if kind == "rack":
        return s[..., 0] > 27.0                             # ASHRAE recommended inlet maximum
    if kind == "crah":
        return (s[..., 4] < 1.0) | (s[..., 2] < 5.0)        # unit fault or fan stopped
    if kind == "pdu":
        return s[..., 0] > 90.0                             # load above 90 % of rating
    if kind == "chiller":
        return s[..., 0] > 3.0                              # supply 3 K above setpoint
    if kind == "pump":
        return (s[..., 0] > 7.1) | (s[..., 2] < 20.0)       # ISO vibration alarm or low flow
    if kind == "ups":
        return s[..., 0] > 35.0                             # battery temperature alarm
    return np.zeros(s.shape[:-1], dtype=bool)


# ---------------------------------------------------------------- D1: Isolation Forest
def average_path_length(n: np.ndarray) -> np.ndarray:
    """c(n) from Liu et al. (2008): expected path length of an unsuccessful BST search."""
    n = np.asarray(n, dtype=float)
    out = np.zeros_like(n)
    big = n > 2
    out[n == 2] = 1.0
    out[big] = 2.0 * (np.log(n[big] - 1.0) + np.euler_gamma) - 2.0 * (n[big] - 1.0) / n[big]
    return out


def if_score(X: np.ndarray, forest: dict) -> np.ndarray:
    """Anomaly score in (0, 1]; higher is more anomalous (same as -sklearn.score_samples)."""
    X32 = np.asarray(X, dtype=np.float32)
    n = X32.shape[0]
    left, right, feat, thr, path = (forest[k] for k in ("left", "right", "feature", "threshold", "path"))
    n_trees = left.shape[0]
    trees = np.arange(n_trees)[:, None]                       # all trees traversed together
    rows = np.broadcast_to(np.arange(n)[None, :], (n_trees, n))
    node = np.zeros((n_trees, n), dtype=np.int64)
    while True:
        lt = left[trees, node]
        leaf = lt < 0
        if leaf.all():
            break
        f = np.where(leaf, 0, feat[trees, node])
        go_left = X32[rows, f] <= thr[trees, node]
        node = np.where(leaf, node, np.where(go_left, lt, right[trees, node]))
    total = path[trees, node].sum(axis=0)
    return 2.0 ** (-total / float(forest["denominator"]))


# ---------------------------------------------------------------- D2: LSTM autoencoder
def _sigmoid(x, xp):
    return 1.0 / (1.0 + xp.exp(-x))


def _lstm(x_seq, wx, wh, b, xp):
    """Run one LSTM layer over (B, T, n_in); gate order i, f, g, o. Returns list of hidden states."""
    batch = x_seq.shape[0]
    hidden = wh.shape[0]
    h = xp.zeros((batch, hidden))
    c = xp.zeros((batch, hidden))
    hs = []
    for t in range(x_seq.shape[1]):
        z = x_seq[:, t, :] @ wx + h @ wh + b
        i = _sigmoid(z[:, :hidden], xp)
        f = _sigmoid(z[:, hidden:2 * hidden], xp)
        g = xp.tanh(z[:, 2 * hidden:3 * hidden])
        o = _sigmoid(z[:, 3 * hidden:], xp)
        c = f * c + i * g
        h = o * xp.tanh(c)
        hs.append(h)
    return hs


def lstm_ae_forward(params: dict, x, xp=np):
    """Encoder LSTM -> latent vector -> decoder LSTM -> linear. x: (B, T, n) -> reconstruction (B, T, n)."""
    enc = _lstm(x, params["enc_wx"], params["enc_wh"], params["enc_b"], xp)
    latent = xp.tanh(enc[-1] @ params["lat_w"] + params["lat_b"])
    steps = x.shape[1]
    repeated = xp.stack([latent] * steps, axis=1)
    dec = _lstm(repeated, params["dec_wx"], params["dec_wh"], params["dec_b"], xp)
    return xp.stack([h @ params["out_w"] + params["out_b"] for h in dec], axis=1)


def ae_errors(params: dict, x: np.ndarray) -> np.ndarray:
    """Per-signal mean squared reconstruction error, shape (B, n)."""
    recon = lstm_ae_forward(params, x, np)
    return ((recon - x) ** 2).mean(axis=1)


# ---------------------------------------------------------------- bundle
class Bundle:
    """Trained parameters for all asset types: scalers, forests, autoencoders, thresholds."""

    def __init__(self, meta: dict, arrays: dict):
        self.meta = meta
        self.arrays = arrays
        self.types = meta["types"]

    @classmethod
    def load(cls, directory: str | Path = BUNDLE_DIR) -> "Bundle":
        directory = Path(directory)
        meta = json.loads((directory / "bundle.json").read_text())
        with np.load(directory / "bundle.npz") as data:
            arrays = {k: data[k] for k in data.files}
        return cls(meta, arrays)

    def save(self, directory: str | Path = BUNDLE_DIR) -> None:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "bundle.json").write_text(json.dumps(self.meta, indent=2))
        np.savez_compressed(directory / "bundle.npz", **self.arrays)

    def has(self, kind: str) -> bool:
        return kind in self.types

    def forest(self, kind: str) -> dict:
        p = f"if/{kind}/"
        f = {k[len(p):]: v for k, v in self.arrays.items() if k.startswith(p)}
        f["denominator"] = self.types[kind]["if_denominator"]
        return f

    def ae_params(self, kind: str) -> dict:
        p = f"ae/{kind}/"
        return {k[len(p):]: v for k, v in self.arrays.items() if k.startswith(p)}

    def scaler(self, kind: str, what: str) -> tuple[np.ndarray, np.ndarray]:
        t = self.types[kind]
        return np.array(t[f"{what}_mu"]), np.array(t[f"{what}_sd"])

    def threshold(self, kind: str, detector: str) -> float:
        if detector == "d0":
            return 0.5
        return float(self.types[kind]["thresholds"][detector[:2]])     # d1h uses d1's threshold
