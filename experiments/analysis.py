"""Tables, statistics and figures from experiments/results/runs.csv.

    python -m experiments.analysis                 (make analysis)

Writes to experiments/results/:
  e1_summary.md        per fault and mode: detection, recovery, MTTD, MTTR and exposure (median, 95 % CI)
  e1_tests.md          Mann-Whitney U: M1 vs M2 (effect of automation), M2 vs M3 (effect of ML detection)
  m1_sensitivity.md    alert-only recovery time vs the assumed human response time
  e4_summary.md        load surges (false actions), combined faults, message loss
  live_vs_offline.md   the live fidelity runs (tools/live_experiment.py) next to the same offline runs
  fig_e1_mttr.png, fig_e1_exposure.png, fig_m1_sensitivity.png, fig_e4_drop.png

Statistics (as in the proposal): medians with 95 % bootstrap confidence intervals (2,000
resamples, percentile method), two-sided Mann-Whitney U tests with Holm correction across the
eight fault types, and the rank-biserial correlation as effect size. A run that has not
recovered by the end of its 45-minute window is right-censored: it counts as the window length,
which ranks it worse than every recovered run (conservative for the faster mode). A median
that falls on a censored value is reported as "> 45 min".
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu

RESULTS = Path(__file__).resolve().parent / "results"
MODES = ["M1", "M2", "M3"]
MODE_NAMES = {"M1": "M1 alert only", "M2": "M2 limits + automation", "M3": "M3 ML + automation"}
COLORS = {"M1": "#2a78d6", "M2": "#eb6834", "M3": "#1baf7a"}      # validated categorical slots 1-3
MARKERS = {"M1": "o", "M2": "s", "M3": "D"}                        # second encoding (print, CVD)
FAULTS = ["crah_fan_failure", "rack_hotspot", "chw_supply_drift", "pump_degradation", "sensor_stuck",
          "sensor_drift", "ups_battery_overheat", "pdu_overload"]
UNITS = {"crah_fan_failure": "K·min", "rack_hotspot": "K·min", "chw_supply_drift": "K·min",
         "pump_degradation": "(L/s + mm/s)·min", "sensor_stuck": "K·min", "sensor_drift": "K·min",
         "ups_battery_overheat": "K·min", "pdu_overload": "%·min"}
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
RNG = np.random.default_rng(7)


# ---------------------------------------------------------------------------------------- helpers
def load(path: Path = RESULTS / "runs.csv") -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df[df["error"].isna()].copy()
    for col in ("detected", "exceeded", "recovered"):
        df[col] = df[col].map({True: True, False: False, "True": True, "False": False})
    df["mttr_c"] = df["mttr_s"].where(df["recovered"] == True, df["observed_s"])  # noqa: E712 - censored
    return df


def median_ci(values, n_boot: int = 2000) -> tuple[float, float, float]:
    v = np.asarray([x for x in values if x == x], dtype=float)
    if len(v) == 0:
        return (math.nan, math.nan, math.nan)
    boots = np.median(RNG.choice(v, size=(n_boot, len(v)), replace=True), axis=1)
    return float(np.median(v)), float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))


def fmt_min(sec: float, window: float = 2700.0) -> str:
    if sec != sec:
        return "–"
    if sec >= window - 1e-6:
        return "> 45"
    return f"{sec / 60:.1f}"


def fmt_ci(m, lo, hi, f=lambda x: f"{x:.1f}") -> str:
    if m != m:
        return "–"
    return f"{f(m)} [{f(lo)}, {f(hi)}]"


def holm(pvals: list[float]) -> list[float]:
    order = np.argsort(pvals)
    adj, running = [0.0] * len(pvals), 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (len(pvals) - rank) * pvals[i]))
        adj[i] = running
    return adj


def mwu(a, b) -> tuple[float, float]:
    """Two-sided Mann-Whitney U; returns (p, rank-biserial r); r > 0 means a tends to be larger."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) == 0 or len(b) == 0 or (np.all(a == a[0]) and np.all(b == a[0])):
        return 1.0, 0.0
    u, p = mannwhitneyu(a, b, alternative="two-sided")
    return float(p), float(2 * u / (len(a) * len(b)) - 1)


def pct(x) -> str:
    return f"{100 * np.mean(x):.0f} %" if len(x) else "–"


# ---------------------------------------------------------------------------------------- tables
def e1_summary(df: pd.DataFrame) -> str:
    rows = ["| Fault | Mode | Runs | Detected | Recovered | Median MTTD (s) | Median time to action (min) "
            "| Median MTTR (min) [95 % CI] | Median exposure [95 % CI] | Wrong actions | Alerts / run |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for f in FAULTS:
        for m in MODES:
            d = df[(df.fault == f) & (df["mode"] == m)]
            if d.empty:
                continue
            mttd, act = d["mttd_s"].dropna(), d["action_s"].dropna()
            cells = [f, m, str(len(d)), pct(d.detected), pct(d.recovered),
                     f"{np.median(mttd):.0f}" if len(mttd) else "–",
                     f"{np.median(act) / 60:.1f}" if len(act) else "–",
                     fmt_ci(*median_ci(d["mttr_c"]), f=fmt_min),
                     f"{fmt_ci(*median_ci(d['exposure']))} {UNITS[f]}",
                     str(int(d.wrong_actions.sum())), f"{d.alerts.median():.0f}"]
            rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def e1_tests(df: pd.DataFrame) -> str:
    out = []
    for metric, label in (("mttr_c", "time to recover (censored at 45 min)"), ("exposure", "exposure")):
        for a, b, what in (("M1", "M2", "automation"), ("M2", "M3", "ML detection")):
            ps, rs, meds = [], [], []
            for f in FAULTS:
                x = df[(df.fault == f) & (df["mode"] == a)][metric].dropna()
                y = df[(df.fault == f) & (df["mode"] == b)][metric].dropna()
                p, r = mwu(x, y)
                ps.append(p)
                rs.append(r)
                meds.append((x.median(), y.median()))
            adj = holm(ps)
            out.append(f"\n### {label}: {a} vs {b} (effect of {what})\n")
            out.append(f"| Fault | Median {a} | Median {b} | p (Holm) | Rank-biserial r | Better |")
            out.append("| --- | --- | --- | --- | --- | --- |")
            for f, (ma, mb), p, r in zip(FAULTS, meds, adj, rs):
                f_ = fmt_min if metric == "mttr_c" else (lambda v: f"{v:.1f}")
                better = "–" if p >= 0.05 else (b if mb < ma else a)
                out.append(f"| {f} | {f_(ma)} | {f_(mb)} | {p:.2g} | {r:+.2f} | {better} |")
    head = ("r > 0: the first mode's values tend to be larger (worse). Better = the mode with the lower median "
            "when the Holm-adjusted p < 0.05.\n")
    return head + "\n".join(out)


def m1_sensitivity(df: pd.DataFrame, e1: pd.DataFrame) -> tuple[str, pd.DataFrame]:
    rows = []
    for delay, d in sorted(df.groupby("param"), key=lambda kv: float(kv[0])):
        m, lo, hi = median_ci(d["mttr_c"])
        rows.append({"median human delay (min)": float(delay), "runs": len(d), "recovered": np.mean(d.recovered),
                     "median": m, "lo": lo, "hi": hi, "exposure": d["exposure"].median()})
    ref = {}
    for mode in ("M2", "M3"):
        d = e1[(e1["mode"] == mode) & (e1.seed.isin(df.seed.unique()))]
        ref[mode] = median_ci(d["mttr_c"])
    t = pd.DataFrame(rows)
    lines = ["| Median human response (min) | Runs | Recovered | Median MTTR (min) [95 % CI] |",
             "| --- | --- | --- | --- |"]
    for _, r in t.iterrows():
        lines.append(f"| {r['median human delay (min)']:.0f} | {int(r.runs)} | {100 * r.recovered:.0f} % | "
                     f"{fmt_ci(r['median'], r.lo, r.hi, f=fmt_min)} |")
    for mode, (m, lo, hi) in ref.items():
        lines.append(f"| {mode} (no human in the loop for low/medium risk) | – | – | {fmt_ci(m, lo, hi, f=fmt_min)} |")
    return "\n".join(lines), t.assign(**{f"ref_{k}": v[0] for k, v in ref.items()})


def e4_summary(df: pd.DataFrame) -> str:
    out = ["### Load surges (normal operation, a zone swings from idle to full load)\n",
           "| Mode | Runs | False remediations | Commands sent | Alerts / run (median) |", "| --- | --- | --- | --- | --- |"]
    s = df[df.suite == "e4_surge"]
    for m in MODES:
        d = s[s["mode"] == m]
        if len(d):
            out.append(f"| {m} | {len(d)} | {int(d.false_remediations.sum())} | {int(d.commands.sum())} | "
                       f"{d.alerts.median():.0f} |")
    out += ["\n### Physical fault while a rack sensor is already faulty\n",
            "| Combination | Mode | Runs | Detected | Recovered | Median MTTR (min) | Median exposure | Wrong actions |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    c = df[df.suite == "e4_sensor"]
    for combo in sorted(c.fault.unique()):
        for m in MODES:
            d = c[(c.fault == combo) & (c["mode"] == m)]
            if len(d):
                out.append(f"| {combo} | {m} | {len(d)} | {pct(d.detected)} | {pct(d.recovered)} | "
                           f"{fmt_min(d.mttr_c.median())} | {d.exposure.median():.1f} | {int(d.wrong_actions.sum())} |")
    out += ["\n### Message loss between gateways and cloud (all 8 fault types)\n",
            "| Lost messages | Mode | Runs | Detected | Recovered | Median MTTD (s) | Median MTTR (min) | Wrong actions |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    dr = df[df.suite == "e4_drop"]
    for rate in sorted(dr.param.astype(float).unique()):
        for m in ("M2", "M3"):
            d = dr[(dr.param.astype(float) == rate) & (dr["mode"] == m)]
            if len(d):
                out.append(f"| {rate:.0%} | {m} | {len(d)} | {pct(d.detected)} | {pct(d.recovered)} | "
                           f"{d.mttd_s.median():.0f} | {fmt_min(d.mttr_c.median())} | {int(d.wrong_actions.sum())} |")
    return "\n".join(out)


def live_vs_offline(live: pd.DataFrame, e1: pd.DataFrame, window_s: float = 1800.0) -> str:
    """Pairs each live run with the offline run of the same fault, mode and seed. The live window is
    30 minutes after the fault, so offline recovery later than that counts as not recovered."""
    off = e1.set_index(["fault", "mode", "seed"])
    lines = ["| Fault | Mode | Seed | Detected live / offline | MTTD (s) live / offline | "
             "First action (min) live / offline | MTTR (min) live / offline | Limit exceeded live / offline |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    agree_det, agree_exc, d_mttd, d_mttr = [], [], [], []

    def mttr_w(r):
        return r["mttr_s"] if r["recovered"] and r["mttr_s"] <= window_s else math.nan

    for _, r in live.sort_values(["fault", "mode", "seed"]).iterrows():
        key = (r.fault, r["mode"], int(r.seed))
        if key not in off.index:
            continue
        o = off.loc[key]
        o = o.iloc[0] if isinstance(o, pd.DataFrame) else o
        agree_det.append(bool(r.detected) == bool(o.detected))
        agree_exc.append(bool(r.exceeded) == bool(o.exceeded))
        if r.mttd_s == r.mttd_s and o.mttd_s == o.mttd_s:
            d_mttd.append(abs(r.mttd_s - o.mttd_s))
        lm, om = mttr_w(r), mttr_w(o)
        if lm == lm and om == om:
            d_mttr.append(abs(lm - om))
        f = lambda v, k=1.0, d=0: "–" if v != v else f"{v / k:.{d}f}"  # noqa: E731
        lines.append(f"| {r.fault} | {r['mode']} | {int(r.seed)} | {bool(r.detected)} / {bool(o.detected)} | "
                     f"{f(r.mttd_s)} / {f(o.mttd_s)} | {f(r.action_s, 60, 1)} / {f(o.action_s, 60, 1)} | "
                     f"{f(lm, 60, 1) if lm == lm else '> 30'} / {f(om, 60, 1) if om == om else '> 30'} | "
                     f"{bool(r.exceeded)} / {bool(o.exceeded)} |")
    if not agree_det:
        return "No live runs match offline runs yet."
    head = (f"{len(agree_det)} paired runs. Detection agrees in {100 * np.mean(agree_det):.0f} %, "
            f"'limit exceeded' in {100 * np.mean(agree_exc):.0f} %; median absolute difference "
            f"MTTD {np.median(d_mttd) if d_mttd else math.nan:.0f} s, "
            f"MTTR {np.median(d_mttr) / 60 if d_mttr else math.nan:.1f} min (where both recovered within 30 min).\n"
            f"Live timing includes MQTT, the bridge, Lambda, EventBridge and Step Functions at speed x10, "
            f"and the tool's 1-s polling for human actions (10 simulated seconds).\n\n")
    return head + "\n".join(lines)


# ---------------------------------------------------------------------------------------- figures
def _style(ax, xlabel="", ylabel=""):
    ax.set_facecolor(SURFACE)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(INK2)
    ax.tick_params(colors=INK2, labelsize=9, length=0)
    ax.set_xlabel(xlabel, color=INK2, fontsize=9)
    ax.set_ylabel(ylabel, color=INK2, fontsize=9)


def fig_dot_ci(df: pd.DataFrame, metric: str, path: Path, title: str, xlabel: str, minutes: bool = True) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7.2, 5.2), facecolor=SURFACE)
    offsets = {"M1": -0.22, "M2": 0.0, "M3": 0.22}
    for i, f in enumerate(FAULTS):
        for m in MODES:
            d = df[(df.fault == f) & (df["mode"] == m)][metric]
            med, lo, hi = median_ci(d)
            if med != med:
                continue
            k = 60.0 if minutes else 1.0
            y = i + offsets[m]
            ax.plot([lo / k, hi / k], [y, y], color=COLORS[m], linewidth=2, solid_capstyle="round")
            ax.plot(med / k, y, marker=MARKERS[m], markersize=8, color=COLORS[m], markeredgecolor=SURFACE,
                    markeredgewidth=1.5, linestyle="none", label=MODE_NAMES[m] if i == 0 else None)
    ax.set_yticks(range(len(FAULTS)))
    ax.set_yticklabels([f.replace("_", " ") for f in FAULTS], color=INK, fontsize=9)
    ax.set_ylim(len(FAULTS) - 0.5, -0.6)
    if minutes:
        ax.set_xlim(-1.5, 48)
        ax.axvline(45, color=INK2, linewidth=1, linestyle=(0, (2, 3)))
        ax.text(45, len(FAULTS) - 0.55, " not recovered\n within 45 min", color=INK2, fontsize=7.5,
                va="bottom", ha="right")
    _style(ax, xlabel)
    ax.set_title(title, loc="left", color=INK, fontsize=11, pad=24)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=3, frameon=False, fontsize=8.5,
              labelcolor=INK2, handletextpad=0.3, columnspacing=1.2, borderaxespad=0.2)
    fig.tight_layout()
    fig.savefig(path, dpi=200, facecolor=SURFACE)
    plt.close(fig)


def fig_exposure(df: pd.DataFrame, path: Path) -> None:
    """Small multiples: each fault has its own unit, so each gets its own axis."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(4, 2, figsize=(8.0, 8.0), facecolor=SURFACE)
    for ax, f in zip(axes.flat, FAULTS):
        stats = {m: median_ci(df[(df.fault == f) & (df["mode"] == m)]["exposure"]) for m in MODES}
        top = max([v[2] for v in stats.values() if v[2] == v[2]] + [0.0])
        if top <= 0:                                     # nothing to plot: say so instead of an empty axis
            ax.set_axis_off()
            ax.set_title(f.replace("_", " "), loc="left", color=INK, fontsize=9.5)
            ax.text(0.0, 0.5, "No exposure in any mode:\nthe value stayed within its normal range",
                    transform=ax.transAxes, color=INK, fontsize=9, va="center")
            continue
        for j, m in enumerate(MODES):
            med, lo, hi = stats[m]
            if med != med:
                continue
            ax.plot([lo, hi], [j, j], color=COLORS[m], linewidth=2, solid_capstyle="round")
            ax.plot(med, j, marker=MARKERS[m], markersize=8, color=COLORS[m], markeredgecolor=SURFACE,
                    markeredgewidth=1.5, linestyle="none")
        ax.set_yticks(range(3))
        ax.set_yticklabels(MODES, color=INK, fontsize=8.5)
        ax.set_ylim(2.6, -0.6)
        ax.set_xlim(-0.04 * top, 1.08 * top)
        _style(ax, UNITS[f])
        ax.set_title(f.replace("_", " "), loc="left", color=INK, fontsize=9.5)
    fig.suptitle("Exposure: excess over the normal limit integrated over time (median, 95 % CI; lower is better)\n"
                 "M1 alert only · M2 limits + automation · M3 ML + automation",
                 x=0.02, ha="left", color=INK, fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=200, facecolor=SURFACE)
    plt.close(fig)


def fig_sensitivity(t: pd.DataFrame, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.4, 4.6), facecolor=SURFACE)
    x = t["median human delay (min)"]
    ax.fill_between(x, t.lo / 60, t.hi / 60, color=COLORS["M1"], alpha=0.15, linewidth=0)
    ax.plot(x, t["median"] / 60, color=COLORS["M1"], linewidth=2, marker=MARKERS["M1"], markersize=8,
            markeredgecolor=SURFACE, label=MODE_NAMES["M1"])
    for mode in ("M2", "M3"):
        v = t[f"ref_{mode}"].iloc[0] / 60
        ax.axhline(v, color=COLORS[mode], linewidth=2, linestyle="--" if mode == "M2" else "-",
                   label=f"{MODE_NAMES[mode]} (no wait for low/medium risk)")
    ax.set_xticks(list(x))
    _style(ax, "Median human response time assumed for M1 (min)", "Median time to recover (min)")
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_ylim(bottom=0)
    ax.set_title("Alert-only baseline depends on the assumed human delay", loc="left", color=INK, fontsize=11, pad=10)
    ax.legend(loc="upper left", bbox_to_anchor=(0, -0.2), ncol=1, frameon=False, fontsize=8, labelcolor=INK2)
    fig.tight_layout()
    fig.savefig(path, dpi=200, facecolor=SURFACE)
    plt.close(fig)


def fig_drop(df: pd.DataFrame, e1: pd.DataFrame, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(8.0, 3.6), facecolor=SURFACE)
    for m in ("M2", "M3"):
        base = e1[(e1["mode"] == m) & (e1.seed.isin(df.seed.unique()))]
        xs, det, mttd = [0.0], [base.detected.mean() * 100], [base.mttd_s.median()]
        for rate, d in sorted(df[df["mode"] == m].groupby(df.param.astype(float))):
            xs.append(rate * 100)
            det.append(d.detected.mean() * 100)
            mttd.append(d.mttd_s.median())
        style = dict(color=COLORS[m], linewidth=2, marker=MARKERS[m], markersize=8, markeredgecolor=SURFACE)
        axes[0].plot(xs, det, label=MODE_NAMES[m], **style)
        axes[1].plot(xs, mttd, label=MODE_NAMES[m], **style)
    _style(axes[0], "Messages lost (%)", "Faults detected (%)")
    _style(axes[1], "Messages lost (%)", "Median time to detect (s)")
    for ax in axes:
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        ax.set_xticks([0, 5, 10, 20])
    axes[0].set_ylim(0, 105)
    axes[1].set_ylim(bottom=0)
    axes[0].legend(loc="lower left", frameon=False, fontsize=8, labelcolor=INK2)
    fig.suptitle("Robustness to message loss (all 8 fault types)", x=0.02, ha="left", color=INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=200, facecolor=SURFACE)
    plt.close(fig)


def main() -> None:
    import argparse
    global RESULTS
    ap = argparse.ArgumentParser(description="Experiment tables and figures")
    ap.add_argument("--runs", type=Path, default=RESULTS / "runs.csv")
    ap.add_argument("--out", type=Path, default=RESULTS)
    args = ap.parse_args()
    df = load(args.runs)
    RESULTS = args.out
    e1 = df[df.suite == "e1"]
    RESULTS.mkdir(parents=True, exist_ok=True)
    if len(e1):
        (RESULTS / "e1_summary.md").write_text(e1_summary(e1) + "\n")
        (RESULTS / "e1_tests.md").write_text(e1_tests(e1) + "\n")
        fig_dot_ci(e1, "mttr_c", RESULTS / "fig_e1_mttr.png",
                   "Time to recover after a fault (median, 95 % CI)", "Minutes after fault start (45 = not recovered)",
                   minutes=True)
        fig_exposure(e1, RESULTS / "fig_e1_exposure.png")
    m1 = df[df.suite == "m1"]
    if len(m1) and len(e1):
        table, t = m1_sensitivity(m1, e1)
        (RESULTS / "m1_sensitivity.md").write_text(table + "\n")
        fig_sensitivity(t, RESULTS / "fig_m1_sensitivity.png")
    e4 = df[df.suite.str.startswith("e4")]
    if len(e4):
        (RESULTS / "e4_summary.md").write_text(e4_summary(df) + "\n")
        if len(e4[e4.suite == "e4_drop"]) and len(e1):
            fig_drop(e4[e4.suite == "e4_drop"], e1, RESULTS / "fig_e4_drop.png")
    live_path = args.runs.parent / "live_runs.csv"
    if live_path.exists() and len(e1):
        live = load(live_path)
        (RESULTS / "live_vs_offline.md").write_text(live_vs_offline(live, e1) + "\n")
    print(f"{len(df)} runs analysed -> {RESULTS}")
    for name in ("e1_summary.md", "m1_sensitivity.md", "e4_summary.md", "live_vs_offline.md"):
        if (RESULTS / name).exists():
            print(f"\n## {name}\n" + (RESULTS / name).read_text())


if __name__ == "__main__":
    main()
