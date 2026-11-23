#!/usr/bin/env python3
"""Compares base and fix runs of an A/B folder (ab_shmem.sh, ab_gin.sh). usage: ab_report.py <runs/ab-...> [--all]
Rows: metric, median of base, median of fix, fix/base - 1, and the run-to-run spread of base (max/min - 1).
Without --all only the 4 B..4 KiB rows are printed, where per-operation overhead is not hidden by the transfer."""
import collections, glob, os, re, statistics as st, sys
d, show_all = sys.argv[1], "--all" in sys.argv
v = collections.defaultdict(lambda: {"base": [], "fix": []})
for f in sorted(glob.glob(d + "/*.log")):
    test, variant, _ = os.path.basename(f)[:-4].rsplit("-", 2)
    section = ""
    for line in open(f, errors="replace"):
        w = line.split()
        if line.startswith("#"): section = line[1:].strip()
        elif len(w) == 3 and w[0].isdigit() and re.fullmatch(r"[\d.]+", w[2]):   # NVSHMEM perftest: size scope value
            v[(test, section, w[1], int(w[0]))][variant].append(float(w[2]))
        elif len(w) == 5 and w[0].isdigit() and w[3].endswith("x"):              # ring_exchange: case us/batch us/put speedup result
            v[(test, "us/batch", "case", int(w[0]))][variant].append(float(w[1]))
print(f"{'metric':58} {'n':>5} {'base':>12} {'fix':>12} {'fix/base-1':>10} {'base spread':>11}")
for k in sorted(v):
    b, x = v[k]["base"], v[k]["fix"]
    if not b or not x or (not show_all and k[2] != "case" and k[3] > 4096): continue
    mb, mx = st.median(b), st.median(x)
    print(f"{' '.join(map(str, k)):58} {len(b):2}/{len(x):<2} {mb:12.4f} {mx:12.4f} {(mx / mb - 1) * 100:+9.2f}% {(max(b) / min(b) - 1) * 100:10.2f}%")
