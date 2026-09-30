"""Diagnostic plots: a few signals per panel, fault window shaded, actions marked."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# Reference categorical palette (light mode), fixed order
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
GRID = "#e4e3df"
SURFACE = "#fcfcfb"
FAULT_BAND = "#ebeae6"


def plot_run(frame, labels: dict, spec: dict, out_path: str | Path) -> Path:
    panels = spec.get("panels", [])
    if not panels:
        return Path(out_path)
    minutes = frame["t_s"] / 60.0
    fig, axes = plt.subplots(len(panels), 1, figsize=(11.5, 2.6 * len(panels) + 0.6),
                             sharex=True, facecolor=SURFACE, squeeze=False)
    title = labels["scenario"] + ("" if labels.get("actions_enabled", True) else "  (no remediation)")
    fig.suptitle(title, color=TEXT, fontsize=13, x=0.06, ha="left")

    for ax, panel in zip(axes[:, 0], panels):
        ax.set_facecolor(SURFACE)
        for f in labels["faults"]:
            ax.axvspan(f["start_s"] / 60.0, f["end_s"] / 60.0, color=FAULT_BAND, lw=0, zorder=0)
        for k, col in enumerate(panel["series"][:4]):
            ax.plot(minutes, frame[col], color=SERIES[k], lw=2, label=col.split(".", 1)[1], zorder=3)
        for lim in panel.get("limits", []):
            ax.axhline(lim["value"], color=TEXT_2, lw=1, ls=(0, (4, 3)), zorder=2)
            ax.text(minutes.iloc[-1], lim["value"], f" {lim['label']}", color=TEXT_2,
                    va="bottom", ha="right", fontsize=8)
        for a in labels.get("actions", []):
            ax.axvline(a["at_s"] / 60.0, color=TEXT_2, lw=1, zorder=2)
        ax.set_ylabel(panel.get("ylabel", ""), color=TEXT_2, fontsize=9)
        ax.grid(axis="y", color=GRID, lw=0.8)
        ax.tick_params(colors=TEXT_2, labelsize=8)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(GRID)
        if len(panel["series"]) > 1:
            ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), fontsize=8,
                      frameon=False, labelcolor=TEXT)
        ax.set_title(panel.get("title", ""), loc="left", fontsize=10, color=TEXT)

    last = axes[-1, 0]
    last.set_xlabel("minutes (grey band = fault active, vertical lines = remediation actions)",
                    color=TEXT_2, fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path, dpi=110, facecolor=SURFACE)
    plt.close(fig)
    return Path(out_path)
