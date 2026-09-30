"""Detection engine: score assets, confirm anomalies, diagnose the fault, emit events.

For each gateway message the engine looks at the last WINDOW + CONFIRM messages of
that gateway. An asset is *confirmed* anomalous when its last CONFIRM windows are all
anomalous; an event is emitted only on the rising edge (newly confirmed).

The detector (D0, D1 or D2) decides *whether* an asset is anomalous. The diagnosis
rules decide *what* the fault is. All three detectors share the same rules, so
experiments compare detection, not diagnosis.

`process` is the online path (one message at a time, used by the Lambda).
`process_series` gives identical events for a whole recorded run, much faster;
a test checks that both paths agree.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from common.catalog import FAULT_CATALOG

from .features import CONFIRM, FLAT_STD, FLATLINE_SIGNALS, SIGNALS, WINDOW, asset_series, windows, window_features
from .models import DETECTORS, Bundle, ae_errors, d0_flags, flatline_flags, if_score

Z = 3.0                    # z-score limit used by the diagnosis rules
# A diagnosis needs a deviation that is unusual (z-score) AND physically meaningful (absolute),
# so that sensor noise on a secondary signal can never decide the fault type.
MIN_DEV = {"peer": 1.0, "sup_minus_sp": 1.0, "t_batt": 1.0,
           "vib_mms": 0.5, "i_a": 1.0, "flow_lps": 2.0, "i_per_flow": 0.05}
SUPPRESSED = None          # diagnosis result meaning "not this gateway's fault to report"
ZONE_CONSEQUENCES = {"unexplained", "rack_hotspot", "sensor_drift"}


class DetectionEngine:
    def __init__(self, bundle: Bundle, detector: str = "d1h", confirm: int = CONFIRM):
        if detector not in DETECTORS:
            raise ValueError(f"unknown detector {detector!r}; choose from {DETECTORS}")
        self.bundle = bundle
        self.detector = detector
        self.confirm = confirm
        self.messages_needed = WINDOW + confirm

    # ------------------------------------------------------------------ scoring
    def score(self, kind: str, win: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """win: (P, WINDOW, n) -> (scores, flags) per window. Windows with gaps are never flagged."""
        valid = ~np.isnan(win).any(axis=(1, 2))
        scores = np.full(win.shape[0], np.nan)
        rules = np.zeros(win.shape[0], dtype=bool)
        ml = self.detector[:2]
        if valid.any():
            w = win[valid]
            if ml == "d0":
                s = d0_flags(kind, w[:, -1, :]).astype(float)
            elif ml == "d1":
                mu, sd = self.bundle.scaler(kind, "feat")
                s = if_score((window_features(w) - mu) / sd, self.bundle.forest(kind))
            else:
                mu, sd = self.bundle.scaler(kind, "base")
                s = ae_errors(self.bundle.ae_params(kind), (w - mu) / sd).mean(axis=1)
            scores[valid] = s
            if self.detector.endswith("h"):                  # hybrid: limits + data-quality rule
                rules[valid] = d0_flags(kind, w[:, -1, :]) | flatline_flags(kind, w)
        thr = self.bundle.threshold(kind, self.detector)
        flags = valid & ((np.nan_to_num(scores, nan=-np.inf) > thr) | rules)
        return scores, flags

    def _score_assets(self, series: dict) -> dict:
        """asset -> (kind, windows, scores, flags); assets of one type are scored in one batch."""
        by_kind = defaultdict(list)
        for asset, (kind, arr) in series.items():
            if self.bundle.has(kind):
                by_kind[kind].append((asset, windows(arr)))
        out = {}
        for kind, items in by_kind.items():
            sizes = [w.shape[0] for _, w in items]
            if sum(sizes) == 0:
                continue
            scores, flags = self.score(kind, np.concatenate([w for _, w in items]))
            start = 0
            for (asset, w), size in zip(items, sizes):
                out[asset] = (kind, w, scores[start:start + size], flags[start:start + size])
                start += size
        return out

    # ------------------------------------------------------------------ online
    def process(self, msgs: list[dict]) -> list[dict]:
        """msgs: this gateway's most recent messages, oldest first. Returns new events."""
        msgs = msgs[-self.messages_needed:]
        if len(msgs) < WINDOW + self.confirm - 1:
            return []                                        # not enough history yet
        k = self.confirm
        diagnoses = {}
        for asset, (kind, win, scores, flags) in self._score_assets(asset_series(msgs)).items():
            now = len(flags) >= k and bool(flags[-k:].all())
            if not now:
                continue
            before = len(flags) >= k + 1 and bool(flags[-k - 1:-1].all())
            d = self._diagnosis(asset, kind, win[-1], scores[-1])
            # new event when the asset becomes anomalous, or when its diagnosis changes
            d["new"] = not before or self.diagnose(asset, kind, win[-2])[0] != d["fault"]
            diagnoses[asset] = d
        return self._events(diagnoses, msgs[-1])

    # ------------------------------------------------------------------ offline
    def process_series(self, msgs: list[dict]) -> list[dict]:
        """All events for one gateway's full message list (oldest first)."""
        k = self.confirm
        scored = self._score_assets(asset_series(msgs))
        confirmed = {}
        for asset, (kind, win, scores, flags) in scored.items():
            c = np.zeros(len(flags), dtype=bool)
            for t in range(k - 1, len(flags)):
                c[t] = flags[t - k + 1:t + 1].all()
            confirmed[asset] = c
        events = []
        previous: dict = {}                                  # asset -> fault at the previous point
        n_points = max((len(v[3]) for v in scored.values()), default=0)
        for t in range(n_points):
            diagnoses = {}
            for asset, (kind, win, scores, flags) in scored.items():
                c = confirmed[asset]
                if not (t < len(c) and c[t]):
                    previous.pop(asset, None)
                    continue
                d = self._diagnosis(asset, kind, win[t], scores[t])
                was_confirmed = t > 0 and c[t - 1]
                d["new"] = not was_confirmed or previous.get(asset, "?") != d["fault"]
                previous[asset] = d["fault"]
                diagnoses[asset] = d
            if diagnoses:
                events.extend(self._events(diagnoses, msgs[t + WINDOW - 1]))
        return events

    # ------------------------------------------------------------------ shared
    def _diagnosis(self, asset, kind, win, score) -> dict:
        fault, target, evidence = self.diagnose(asset, kind, win)
        return {"fault": fault, "target": target, "evidence": evidence,
                "score": float(score), "threshold": self.bundle.threshold(kind, self.detector)}

    def _events(self, diagnoses: dict, latest: dict) -> list[dict]:
        # Gateway-level root cause: a failed CRAH explains the hot racks in its zone
        crah_failed = any(d["fault"] == "crah_fan_failure" for d in diagnoses.values())
        events, seen = [], set()
        for asset, d in diagnoses.items():
            if not d["new"] or d["fault"] is SUPPRESSED:
                continue
            if crah_failed and asset.startswith("rack") and d["fault"] in ZONE_CONSEQUENCES:
                continue                                     # consequence of the failed CRAH
            key = (d["fault"], d["target"])
            if key in seen:
                continue
            seen.add(key)
            risk, playbook = FAULT_CATALOG[d["fault"]]
            events.append({
                "detector": self.detector, "gw": latest["gw"], "ts": latest["ts"], "seq": latest.get("seq"),
                "asset": asset, "target": d["target"], "fault_type": d["fault"],
                "risk": risk, "playbook": playbook,
                "score": round(d["score"], 6), "threshold": round(d["threshold"], 6),
                "evidence": d["evidence"],
            })
        return events

    def diagnose(self, asset: str, kind: str, win: np.ndarray):
        """win: (WINDOW, n) raw signals of the confirmed window. Returns (fault, target, evidence)."""
        mu, sd = self.bundle.scaler(kind, "base")
        last = win[-1]
        z = (last - mu) / sd
        names = SIGNALS[kind]
        zs = dict(zip(names, z))
        dev = dict(zip(names, last - mu))
        evidence = {n: round(float(v), 2) for n, v in zs.items() if abs(v) >= Z}

        def high(s):
            return zs[s] > Z and dev[s] > MIN_DEV.get(s, 0.0)

        def low(s):
            return zs[s] < -Z and dev[s] < -MIN_DEV.get(s, 0.0)

        # Data quality first: a direct reading that did not change at all is a frozen sensor
        for s in FLATLINE_SIGNALS.get(kind, []):
            if win[:, names.index(s)].std() < FLAT_STD:
                return "sensor_stuck", asset, {"signal": s, "window_std": 0.0}

        if kind == "rack":
            if high("peer"):
                # Reading hotter than its peers: a real hotspot if the outlet rose too,
                # a faulty sensor if the rack's air temperature rise shrank by the same amount.
                if dev["dT"] < -0.5 * dev["peer"]:
                    return "sensor_drift", asset, dict(evidence, signal="t_in")
                return "rack_hotspot", asset, evidence
            if zs["t_in"] > Z and abs(zs["approach"]) < Z:
                return SUPPRESSED, asset, evidence           # supply air is warm: the plant's fault
            return "unexplained", asset, evidence

        if kind == "crah":
            if last[4] < 1.0 or last[2] < 5.0:
                return "crah_fan_failure", asset, {"status_ok": float(last[4]), "fan_pct": float(last[2])}
            if zs["t_sup"] > Z and abs(zs["fan_resid"]) < Z:
                return SUPPRESSED, asset, evidence           # warm supply air: chilled water side
            return "unexplained", asset, evidence

        if kind == "pdu":
            if last[0] > 90.0 or zs["load_pct"] > Z:
                return "pdu_overload", asset, evidence
            return "unexplained", asset, evidence

        if kind == "chiller":
            if high("sup_minus_sp"):
                return "chw_supply_drift", asset, evidence
            return "unexplained", asset, evidence

        if kind == "pump":
            if high("vib_mms") or high("i_a") or low("flow_lps") or high("i_per_flow"):
                return "pump_degradation", asset, evidence
            return "unexplained", asset, evidence

        if kind == "ups":
            # the battery itself must be hot; a high residual alone can be thermal lag after a load drop
            if high("t_batt"):
                return "ups_battery_overheat", asset, evidence
            return "unexplained", asset, evidence

        return "unexplained", asset, evidence
