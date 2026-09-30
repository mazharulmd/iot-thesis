"""Turn gateway messages into per-asset signal vectors and window features.

This module is used unchanged by training, offline evaluation and the Lambda,
so it depends on NumPy only.

Asset types and their base signals (one vector per asset per message):
    rack    t_in, dT (t_out - t_in), approach (t_in - zone supply air), peer (t_in - zone median), p_kw
    crah    t_sup, dT_air (t_ret - t_sup), fan_pct, fan_resid (fan vs zone load), status_ok
    pdu     load_pct
    chiller sup_minus_sp, dT_w (t_ret - t_sup)
    pump    vib_mms, i_a, flow_lps, i_per_flow, dp_resid        (only while running)
    ups     t_batt, t_resid (t_batt vs load-based expectation), load_kw
"""
from __future__ import annotations

import numpy as np

WINDOW = 6            # messages per window (60 s at 10 s period)
CONFIRM = 3           # consecutive anomalous windows needed to confirm

SIGNALS = {
    "rack": ["t_in", "dT", "approach", "peer", "p_kw"],
    "crah": ["t_sup", "dT_air", "fan_pct", "fan_resid", "status_ok"],
    "pdu": ["load_pct"],
    "chiller": ["sup_minus_sp", "dT_w"],
    "pump": ["vib_mms", "i_a", "flow_lps", "i_per_flow", "dp_resid"],
    "ups": ["t_batt", "t_resid", "load_kw"],
}
# Signals that are direct sensor readings (not derived) and should never be perfectly flat.
# A window with zero variation in one of them means a frozen sensor (data-quality rule).
FLATLINE_SIGNALS = {"rack": ["t_in", "p_kw"], "crah": ["t_sup"], "pdu": ["load_pct"],
                    "pump": ["vib_mms", "i_a", "flow_lps"], "ups": ["t_batt", "load_kw"]}
FLAT_STD = 0.005
STATUS_VALUE = {"on": 1.0, "starting": 0.5}
FAN_PCT_PER_KW = 100.0 * 1.10 * 0.068 / 22.0        # auto fan control law of the CRAHs
FAN_MIN_PCT = 30.0                                    # fans never run slower than this
PUMP_NOMINAL_DP, PUMP_NOMINAL_FLOW = 150.0, 40.0


def asset_type(asset: str) -> str | None:
    for prefix, kind in (("rack", "rack"), ("pdu", "pdu"), ("pump", "pump"), ("ups", "ups")):
        if asset.startswith(prefix):
            return kind
    if asset == "chiller":
        return "chiller"
    if asset.startswith("crah") and asset != "crah5":       # standby unit is not scored
        return "crah"
    return None


def _apply_quarantine(assets: dict) -> dict:
    """Quarantined sensors (listed by the gateway after a sensor_quarantine playbook) are kept out of
    decisions: a rack's inlet temperature is replaced by the median of its healthy zone peers, and any
    other asset with a quarantined reading is not scored at all."""
    if not any("quarantined" in v for v in assets.values()):
        return assets
    healthy_in = [v["t_in"] for a, v in assets.items()
                  if a.startswith("rack") and "t_in" not in v.get("quarantined", ())]
    out = {}
    for a, v in assets.items():
        q = set(v.get("quarantined", ()))
        if not q:
            out[a] = v
        elif a.startswith("rack") and q == {"t_in"} and healthy_in:
            out[a] = dict(v, t_in=float(np.median(healthy_in)))
    return out


def base_signals(msg: dict) -> dict[str, tuple[str, np.ndarray, dict]]:
    """asset -> (type, signal vector, raw readings) for one gateway message."""
    assets = _apply_quarantine(msg["assets"])
    out: dict = {}
    racks = {a: v for a, v in assets.items() if a.startswith("rack")}
    crah = next((v for a, v in assets.items() if asset_type(a) == "crah"), None)
    pdu = next((v for a, v in assets.items() if a.startswith("pdu")), None)
    median_in = float(np.median([v["t_in"] for v in racks.values()])) if racks else 0.0
    t_sup_zone = crah["t_sup"] if crah else median_in

    for a, v in racks.items():
        vec = [v["t_in"], v["t_out"] - v["t_in"], v["t_in"] - t_sup_zone, v["t_in"] - median_in, v["p_kw"]]
        out[a] = ("rack", np.array(vec, dtype=float), v)
    for a, v in assets.items():
        kind = asset_type(a)
        if kind == "crah":
            zone_kw = pdu["p_kw"] if pdu else 0.0
            expected_fan = min(100.0, max(FAN_MIN_PCT, FAN_PCT_PER_KW * zone_kw))
            vec = [v["t_sup"], v["t_ret"] - v["t_sup"], v["fan_pct"],
                   v["fan_pct"] - expected_fan, STATUS_VALUE.get(v["status"], 0.0)]
        elif kind == "pdu":
            vec = [v["load_pct"]]
        elif kind == "chiller":
            vec = [v["t_sup"] - v["sp"], v["t_ret"] - v["t_sup"]]
        elif kind == "pump":
            if v.get("status") != "on" or v["flow_lps"] < 5.0:
                continue                                     # idle standby pump: not scored
            vec = [v["vib_mms"], v["i_a"], v["flow_lps"], v["i_a"] / max(v["flow_lps"], 1.0),
                   v["dp_kpa"] - PUMP_NOMINAL_DP * (v["flow_lps"] / PUMP_NOMINAL_FLOW) ** 2]
        elif kind == "ups":
            vec = [v["t_batt"], v["t_batt"] - (25.0 + 3.0 * v["load_kw"] / 1000.0), v["load_kw"]]
        else:
            continue
        out[a] = (kind, np.array(vec, dtype=float), v)
    return out


def asset_series(msgs: list[dict]) -> dict[str, tuple[str, np.ndarray]]:
    """asset -> (type, array of shape (len(msgs), n_signals)); NaN rows where the asset was not scored."""
    per_msg = [base_signals(m) for m in msgs]
    names = {a: kind for sig in per_msg for a, (kind, _, _) in sig.items()}
    out = {}
    for a, kind in names.items():
        n = len(SIGNALS[kind])
        arr = np.full((len(msgs), n), np.nan)
        for i, sig in enumerate(per_msg):
            if a in sig:
                arr[i] = sig[a][1]
        out[a] = (kind, arr)
    return out


def windows(arr: np.ndarray, w: int = WINDOW) -> np.ndarray:
    """(T, n) -> (T - w + 1, w, n) sliding windows."""
    if arr.shape[0] < w:
        return np.empty((0, w, arr.shape[1]))
    idx = np.arange(w)[None, :] + np.arange(arr.shape[0] - w + 1)[:, None]
    return arr[idx]


def window_features(win: np.ndarray) -> np.ndarray:
    """(P, w, n) -> (P, 4n): last value, mean, standard deviation and slope of each signal."""
    last = win[:, -1, :]
    mean = win.mean(axis=1)
    std = win.std(axis=1)
    slope = (win[:, -1, :] - win[:, 0, :]) / (win.shape[1] - 1)
    return np.concatenate([last, mean, std, slope], axis=1)


def feature_names(kind: str) -> list[str]:
    return [f"{stat}_{s}" for stat in ("last", "mean", "std", "slope") for s in SIGNALS[kind]]
