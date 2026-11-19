"""Concept figures for Chapters 2-4 of the thesis report (drawn, not measured).

    python3 thesis/report/figures/make_concept_figures.py

Writes power-cooling-chain.png, iot-core-mqtt-shadow.png and mape-k-mapping.png next to this file.
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

HERE = Path(__file__).resolve().parent
INK, MUTED = "#1f2937", "#6b7280"
BLUE, BLUE_BG = "#1d4ed8", "#dbeafe"
RED, RED_BG = "#b91c1c", "#fee2e2"
GREEN, GREEN_BG = "#047857", "#d1fae5"
AMBER, AMBER_BG = "#b45309", "#fef3c7"
GREY_BG = "#f3f4f6"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9})


def box(ax, x, y, w, h, title, sub="", fc=GREY_BG, ec=INK, dashed=False, tsize=9.5):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08",
                                fc=fc, ec=ec, lw=1.3, ls="--" if dashed else "-"))
    if not sub:
        ax.text(x + w / 2, y + h / 2, title, ha="center", va="center", fontsize=tsize, weight="bold", color=INK)
        return
    ax.text(x + w / 2, y + h - 0.32, title, ha="center", va="center", fontsize=tsize, weight="bold", color=INK)
    ax.text(x + w / 2, y + (h - 0.55) / 2, sub, ha="center", va="center", fontsize=7.4, color=MUTED,
            linespacing=1.2)


def arrow(ax, p, q, color=INK, text="", rad=0.0, dashed=False, tpos=0.5, toff=(0, 0.14), lw=1.4):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=11, color=color, lw=lw,
                                 ls="--" if dashed else "-", connectionstyle=f"arc3,rad={rad}",
                                 shrinkA=2, shrinkB=2))
    if text:
        x = p[0] + (q[0] - p[0]) * tpos + toff[0]
        y = p[1] + (q[1] - p[1]) * tpos + toff[1]
        ax.text(x, y, text, ha="center", va="center", fontsize=7.4, color=color)


def canvas(w_cm, h_cm, xmax, ymax):
    fig, ax = plt.subplots(figsize=(w_cm / 2.54, h_cm / 2.54))
    ax.set_xlim(0, xmax)
    ax.set_ylim(0, ymax)
    ax.axis("off")
    fig.subplots_adjust(0.01, 0.01, 0.99, 0.99)
    return fig, ax


def power_cooling():
    fig, ax = canvas(16, 9.2, 16, 9.2)
    xs, w = (0.2, 4.5, 8.8), 2.9
    # power chain (top)
    ax.text(0.2, 8.85, "Power chain", fontsize=10, weight="bold", color=AMBER)
    y, h = 6.9, 1.5
    box(ax, xs[0], y, w, h, "Utility and\ngenerators", fc=AMBER_BG, ec=AMBER)
    box(ax, xs[1], y, w, h, "UPS 1 and 2", "bridge outages;\nbattery temp., load", fc=AMBER_BG, ec=AMBER)
    box(ax, xs[2], y, w, h, "PDU 1–4", "power per zone;\nload", fc=AMBER_BG, ec=AMBER)
    for a, b in ((xs[0] + w, xs[1]), (xs[1] + w, xs[2])):
        arrow(ax, (a, y + h / 2), (b, y + h / 2), AMBER)
    # racks
    box(ax, 12.3, 4.0, 3.5, 2.4, "IT racks", "20 GPU racks, 4 zones;\ninlet and outlet\ntemperature, power", fc=GREY_BG)
    arrow(ax, (xs[2] + w, y + h / 2), (12.9, 6.4), AMBER, "electricity", tpos=0.5, toff=(0.75, 0.15))
    # cooling chain (bottom)
    ax.text(0.2, 3.45, "Cooling chain", fontsize=10, weight="bold", color=BLUE)
    yc, hc = 1.5, 1.5
    box(ax, xs[0], yc, w, hc, "Chiller", "rejects heat;\nwater temperature", fc=BLUE_BG, ec=BLUE)
    box(ax, xs[1], yc, w, hc, "Pumps 1 and 2", "water loop;\nflow, vibration", tsize=9, fc=BLUE_BG, ec=BLUE)
    box(ax, xs[2], yc, w, hc, "CRAH 1–4", "fan and coil;\nfan speed, air temp.", fc=BLUE_BG, ec=BLUE)
    box(ax, xs[2], 0.1, w, 1.0, "Standby CRAH 5", fc="white", ec=BLUE, dashed=True, tsize=8.5)
    arrow(ax, (xs[0] + w, yc + 1.0), (xs[1], yc + 1.0), BLUE, "chilled", toff=(0, 0.2))
    arrow(ax, (xs[1], yc + 0.45), (xs[0] + w, yc + 0.45), BLUE, "return", dashed=True, toff=(0, -0.2))
    arrow(ax, (xs[1] + w, yc + 1.0), (xs[2], yc + 1.0), BLUE, "chilled", toff=(0, 0.2))
    arrow(ax, (xs[2], yc + 0.45), (xs[1] + w, yc + 0.45), BLUE, "return", dashed=True, toff=(0, -0.2))
    arrow(ax, (xs[2] + w, yc + 1.2), (12.9, 4.0), BLUE, "cold air", tpos=0.45, toff=(-0.6, 0.15))
    arrow(ax, (15.2, 4.0), (xs[2] + w, yc + 0.35), RED, "hot air", rad=-0.35, tpos=0.5, toff=(1.3, -0.35))
    arrow(ax, (xs[2] + w / 2, 1.1), (xs[2] + w / 2, yc), BLUE, dashed=True)
    ax.text(xs[2] + w + 0.2, 0.6, "N+1 standby: started\nwhen a CRAH fails", fontsize=7.2, color=BLUE, va="center")
    ax.text(15.9, 8.85, "Grey text: quantities measured by the gateways", ha="right", fontsize=7.2,
            color=MUTED, style="italic")
    fig.savefig(HERE / "power-cooling-chain.png", dpi=220)
    plt.close(fig)


def iot_core():
    fig, ax = canvas(16, 8.0, 16, 8.0)
    # device side
    box(ax, 0.2, 4.6, 3.1, 1.9, "Gateway (zone 2)", "thing with its own\nX.509 certificate", fc=GREEN_BG, ec=GREEN, tsize=9)
    box(ax, 0.2, 0.9, 3.1, 1.9, "Sensors and\nactuators", fc=GREY_BG)
    arrow(ax, (1.1, 2.8), (1.1, 4.6), INK, "readings", toff=(-0.55, 0))
    arrow(ax, (2.4, 4.6), (2.4, 2.8), INK, "commands", toff=(0.0, 0.0))
    # IoT Core frame
    ax.add_patch(FancyBboxPatch((5.0, 0.5), 6.0, 7.0, boxstyle="round,pad=0.02,rounding_size=0.12",
                                fc="#fafafa", ec=MUTED, lw=1.0, ls="--"))
    ax.text(8.0, 7.15, "AWS IoT Core", ha="center", fontsize=10.5, weight="bold", color=INK)
    box(ax, 5.4, 4.9, 5.2, 1.7, "MQTT broker", "topic dc/hall1/zone2/telemetry;\nTLS, policy per device", fc=BLUE_BG, ec=BLUE)
    box(ax, 5.4, 2.9, 5.2, 1.4, "Rules engine", "SELECT * FROM\n'dc/hall1/+/telemetry'", fc=BLUE_BG, ec=BLUE)
    box(ax, 5.4, 0.8, 5.2, 1.5, "Device shadow (zone2)", "desired ≠ reported → delta", fc=AMBER_BG, ec=AMBER)
    arrow(ax, (3.3, 5.9), (5.4, 5.9), GREEN, "publish", toff=(0, 0.2))
    arrow(ax, (8.0, 4.9), (8.0, 4.3), BLUE)
    arrow(ax, (3.3, 5.0), (5.4, 1.9), GREEN, "reported", dashed=True, tpos=0.42, toff=(0.55, 0.15))
    arrow(ax, (5.4, 1.2), (3.1, 4.6), AMBER, "delta", tpos=0.55, toff=(-0.45, -0.15))
    # cloud services
    box(ax, 12.0, 4.9, 3.8, 1.4, "DynamoDB", "stores every message", fc=GREY_BG)
    box(ax, 12.0, 2.9, 3.8, 1.4, "Lambda", "detector function", fc=GREY_BG)
    box(ax, 12.0, 0.8, 3.8, 1.5, "Application", "remediation workflow;\nwrites desired state", fc=GREY_BG)
    arrow(ax, (10.6, 3.9), (12.0, 5.3), BLUE, "action 1", tpos=0.4, toff=(-0.45, 0.35))
    arrow(ax, (10.6, 3.4), (12.0, 3.5), BLUE, "action 2", toff=(0, -0.22))
    arrow(ax, (12.0, 1.5), (10.6, 1.5), AMBER, "desired", toff=(0, 0.2))
    fig.savefig(HERE / "iot-core-mqtt-shadow.png", dpi=220)
    plt.close(fig)


def mape_k():
    fig, ax = canvas(16, 9.0, 16, 9.0)
    cx, cy = 8.0, 4.7
    box(ax, cx - 2.5, cy - 0.85, 5.0, 1.7, "Knowledge", "DynamoDB: telemetry, incidents,\nlocks; playbooks; models", fc=AMBER_BG, ec=AMBER)
    w, h = 4.6, 1.9
    pos = {"Monitor": (0.4, 6.6), "Analyse": (11.0, 6.6), "Plan": (11.0, 0.6), "Execute": (0.4, 0.6)}
    sub = {"Monitor": "gateways → IoT Core (MQTT)\ntopic rule stores telemetry",
           "Analyse": "detector Lambda: limits,\nIsolation Forest, LSTM-AE,\ndiagnosis rules",
           "Plan": "Step Functions playbook:\nlocks, precheck, risk tier,\nhuman approval if high risk",
           "Execute": "commands via device shadow;\nverify on new telemetry,\nrollback, escalate"}
    col = {"Monitor": (GREEN_BG, GREEN), "Analyse": (BLUE_BG, BLUE), "Plan": (BLUE_BG, BLUE), "Execute": (GREEN_BG, GREEN)}
    for k, (x, y) in pos.items():
        box(ax, x, y, w, h, k, sub[k], fc=col[k][0], ec=col[k][1], tsize=10.5)
    arrow(ax, (0.4 + w, 7.5), (11.0, 7.5), INK, "telemetry every 10 s", toff=(0, 0.22))
    arrow(ax, (13.3, 6.6), (13.3, 0.6 + h), INK, "anomaly event\n(EventBridge)", toff=(1.15, 0))
    arrow(ax, (11.0, 1.5), (0.4 + w, 1.5), INK, "approved plan", toff=(0, 0.22))
    arrow(ax, (2.7, 0.6 + h), (2.7, 6.6), INK, "effect in the\nnext telemetry", toff=(-1.05, 0))
    for (x, y) in pos.values():
        p = (x + w / 2, y + (0 if y > cy else h))
        q = (cx + (-1.4 if x < cx else 1.4), cy + (0.85 if y > cy else -0.85))
        arrow(ax, p, q, MUTED, dashed=True, lw=1.0)
    ax.text(8.0, 8.75, "Managed element: the data hall's power and cooling equipment", ha="center",
            fontsize=8, color=MUTED, style="italic")
    fig.savefig(HERE / "mape-k-mapping.png", dpi=220)
    plt.close(fig)


if __name__ == "__main__":
    power_cooling()
    iot_core()
    mape_k()
    print("written:", ", ".join(p.name for p in sorted(HERE.glob("*.png")) if p.stat().st_mtime > 0
                                 and p.name in ("power-cooling-chain.png", "iot-core-mqtt-shadow.png", "mape-k-mapping.png")))
