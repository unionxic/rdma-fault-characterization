#!/usr/bin/env python3
"""Exp2: sleep duration vs detection delay (log-x, scenario lines)."""
import csv
import os
from collections import defaultdict
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
src = os.path.join(HERE, "data", "exp2_sleep_curve.csv")
out = os.path.join(HERE, "exp2_sleep_curve.png")

# scenario -> [(sleep_us, mean_ms, std_ms)]
g = defaultdict(list)
with open(src) as f:
    for r in csv.DictReader(f):
        g[r["scenario"]].append(
            (int(r["sleep_us"]), float(r["mean_ms"]), float(r["stddev_ms"]))
        )

LABELS = {"QP_TO_ERR": "A: QP→ERR",
          "KILL_PROCESS": "B: Kill",
          "LINK_DOWN":     "C: Link Down"}
COLORS = {"QP_TO_ERR": "C0", "KILL_PROCESS": "C1", "LINK_DOWN": "C2"}

fig, ax = plt.subplots(figsize=(6.4, 4.2))
for sc in ("QP_TO_ERR", "KILL_PROCESS", "LINK_DOWN"):
    pts = sorted(g[sc])
    if not pts:
        continue
    xs = [p[0] / 1e6 if p[0] > 0 else 1e-4 for p in pts]   # seconds, busy=1e-4
    ys = [p[1] for p in pts]
    es = [p[2] for p in pts]
    ax.errorbar(xs, ys, yerr=es, marker="o", capsize=3,
                label=LABELS[sc], color=COLORS[sc])

# y = sleep + 3700 reference
import numpy as np
xs_ref = np.logspace(-4, 1.1, 80)
ax.plot(xs_ref, xs_ref * 1000.0 + 3700.0, "k--", alpha=0.4,
        label="sleep + 3.7 s (additive model)")

ax.set_xscale("log")
ax.set_xlabel("CPU sleep duration (s)  [busy poll plotted at 1e-4]")
ax.set_ylabel("Detection delay (ms)")
ax.set_title("Exp 2: Detection delay vs CPU polling interval")
ax.legend(loc="upper left")
ax.grid(True, which="both", alpha=0.3)
fig.tight_layout()
fig.savefig(out, dpi=150)
print(f"wrote {out}")
