#!/usr/bin/env python3
"""Exp3: per-stage recovery overhead (stacked bar + drilldown)."""
import csv
import os
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
src = os.path.join(HERE, "data", "exp3_stages.csv")
out = os.path.join(HERE, "exp3_stages.png")

# Read stages
data = {}
with open(src) as f:
    for r in csv.DictReader(f):
        data[r["stage"]] = {
            "mean": float(r["mean_us"]),
            "std":  float(r["stddev_us"]),
            "p50":  float(r["p50_us"]),
            "p99":  float(r["p99_us"]),
            "n":    int(r.get("n", 0) or 0),
        }

# Stacked bar: T1+T2+coord1+T3+T4+coord2+T5
stages = [
    ("T1_ERR_RESET",  "T1 ERR→RESET"),
    ("T2_RESET_INIT", "T2 RESET→INIT"),
    ("coord1",         "coord1"),
    ("T3_INIT_RTR",    "T3 INIT→RTR"),
    ("T4_RTR_RTS",     "T4 RTR→RTS"),
    ("coord2",         "coord2"),
    ("T5_write_cqe",   "T5 write→CQE"),
]

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.0, 4.4),
                                gridspec_kw={"width_ratios": [1, 2]})

# --- left: single stacked bar ---
bottom = 0.0
colors = ["C0", "C1", "C7", "C2", "C3", "C7", "C4"]
for i, (k, lbl) in enumerate(stages):
    h = data[k]["mean"]
    color = colors[i]
    if k.startswith("coord"):
        ax1.bar(0, h, bottom=bottom, color=color, hatch="///",
                edgecolor="black", lw=0.5, label=lbl)
    else:
        ax1.bar(0, h, bottom=bottom, color=color,
                edgecolor="black", lw=0.5, label=lbl)
    bottom += h
ax1.set_xticks([0])
ax1.set_xticklabels(["recovery"])
ax1.set_ylabel("Mean time (us)")
ax1.set_title("Stacked recovery cost (mean)")
ax1.grid(True, axis="y", alpha=0.3)
ax1.legend(fontsize=8, loc="upper left", bbox_to_anchor=(1, 1.0))

# --- right: per-stage bar with errorbars ---
labels = [lbl for _, lbl in stages]
means = [data[k]["mean"] for k, _ in stages]
stds  = [data[k]["std"] for k, _ in stages]
xpos  = list(range(len(stages)))
ax2.bar(xpos, means, yerr=stds, color=colors, edgecolor="black", lw=0.5,
        capsize=3)
ax2.set_xticks(xpos)
ax2.set_xticklabels(labels, rotation=20, ha="right")
ax2.set_ylabel("Latency (us)")
ax2.set_title("Per-stage mean +/- 1 sigma")
ax2.grid(True, axis="y", alpha=0.3)

# N = real per-stage trial count (from the aggregated CSV), not a hardcoded guess.
_n = data.get("T1_ERR_RESET", {}).get("n", 0)
fig.suptitle(f"Exp 3: QP recovery breakdown  (N={_n})", y=1.02)
fig.tight_layout()
fig.savefig(out, dpi=150, bbox_inches="tight")
print(f"wrote {out}")
