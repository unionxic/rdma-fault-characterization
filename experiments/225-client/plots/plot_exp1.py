#!/usr/bin/env python3
"""Exp1: detection latency distribution by scenario (boxplot)."""
import csv
import os
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
src = os.path.join(HERE, "data", "exp1_distribution.csv")
out_box = os.path.join(HERE, "exp1_box.png")
out_violin = os.path.join(HERE, "exp1_violin.png")

groups = {"QP_TO_ERR": [], "KILL_PROCESS": [], "LINK_DOWN": []}
with open(src) as f:
    for r in csv.DictReader(f):
        groups[r["scenario"]].append(float(r["detection_latency_ms"]))

labels = ["A: QP→ERR", "B: Kill", "C: Link Down"]
data = [groups["QP_TO_ERR"], groups["KILL_PROCESS"], groups["LINK_DOWN"]]

fig, ax = plt.subplots(figsize=(6.0, 4.0))
ax.boxplot(data, labels=labels, showfliers=True, widths=0.6,
           medianprops=dict(color="C3", lw=1.5))
ax.set_ylabel("Detection latency (ms)")
ax.set_title(f"Exp 1: CPU-mediated detection latency  (N={len(data[0])} per scenario)")
ax.grid(True, axis="y", alpha=0.3)
fig.tight_layout()
fig.savefig(out_box, dpi=150)
print(f"wrote {out_box}")

fig, ax = plt.subplots(figsize=(6.0, 4.0))
parts = ax.violinplot(data, showmedians=True, widths=0.7)
for pc in parts["bodies"]:
    pc.set_alpha(0.6)
ax.set_xticks(range(1, len(labels) + 1))
ax.set_xticklabels(labels)
ax.set_ylabel("Detection latency (ms)")
ax.set_title("Exp 1: Detection latency density")
ax.grid(True, axis="y", alpha=0.3)
fig.tight_layout()
fig.savefig(out_violin, dpi=150)
print(f"wrote {out_violin}")
