#!/usr/bin/env python3
"""Exp4: kill-mode detection latency heatmap (retry x timeout)."""
import csv
import os
import math
import numpy as np
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
src = os.path.join(HERE, "data", "exp4_kill_heatmap.csv")
out = os.path.join(HERE, "exp4_kill_heatmap.png")

retries = [0, 1, 3, 7]
timeouts = [8, 12, 14, 17, 20]

# (retry, timeout) -> mean_ms (or None if timed out)
m = {}
with open(src) as f:
    for r in csv.DictReader(f):
        R = int(r["retry_cnt"])
        T = int(r["qp_timeout"])
        if int(r["timed_out"]):
            m[(R, T)] = None
        else:
            m[(R, T)] = float(r["mean_ms"])

mat = np.full((len(retries), len(timeouts)), np.nan)
for i, R in enumerate(retries):
    for j, T in enumerate(timeouts):
        v = m.get((R, T))
        if v is not None:
            mat[i, j] = v

# Use log color scale (ms)
import matplotlib.colors as mcolors
vmin = max(np.nanmin(mat), 1e-1)
vmax = np.nanmax(mat)
norm = mcolors.LogNorm(vmin=vmin, vmax=vmax)

fig, ax = plt.subplots(figsize=(7.4, 4.2))
cmap = plt.cm.viridis.copy()
cmap.set_bad(color="lightgray")

im = ax.imshow(mat, aspect="auto", cmap=cmap, norm=norm)
ax.set_xticks(range(len(timeouts)))
ax.set_xticklabels([f"{T}\n({4.096 * (2**T) / 1000:.1f}ms)" for T in timeouts])
ax.set_yticks(range(len(retries)))
ax.set_yticklabels([str(r) for r in retries])
ax.set_xlabel("qp_timeout encoding (and decoded ms)")
ax.set_ylabel("retry_cnt")
ax.set_title("Exp 4: Persistent-fault (kill) detection latency  (mean, log color)")

for i, R in enumerate(retries):
    for j, T in enumerate(timeouts):
        v = mat[i, j]
        if np.isnan(v):
            ax.text(j, i, "TIMEOUT", ha="center", va="center",
                    color="black", fontsize=8)
        else:
            if v >= 1000:
                lbl = f"{v/1000:.1f}s"
            elif v >= 1:
                lbl = f"{v:.0f}ms"
            else:
                lbl = f"{v*1e3:.0f}us"
            ax.text(j, i, lbl, ha="center", va="center",
                    color="white" if v < 200 else "black",
                    fontsize=9)

fig.colorbar(im, ax=ax, label="Detection latency (ms, log)")
fig.tight_layout()
fig.savefig(out, dpi=150)
print(f"wrote {out}")
