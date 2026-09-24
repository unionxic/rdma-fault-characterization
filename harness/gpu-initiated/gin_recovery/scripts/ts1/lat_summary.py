#!/usr/bin/env python3
"""Fault-free latency cells (lat_{on,off,base}_{4k,256k}) from the raw per-iteration files.

usage: lat_summary.py <latdir>
Per cell: runs, samples, pooled p50/p90/p99/mean of the put+signal+flush time measured on the GPU
(%globaltimer around one iteration of the unmodified loop), and the range of the per-run p50.
The first 100 iterations of every run are dropped as warm-up (same rule for every cell).
"""
import glob, gzip, os, re, statistics, sys
from collections import defaultdict

WARM = 100


def q(v, p):
    k = int(round(p * (len(v) - 1)))
    return v[k]


def main():
    d = sys.argv[1]
    cells = defaultdict(list)
    for meta in sorted(glob.glob(os.path.join(d, "*_meta.txt"))):
        stem = meta[: -len("_meta.txt")]
        cell = os.path.basename(stem).rsplit("_", 1)[0]
        raw = stem + "_lat_raw.csv.gz"
        m = open(meta).read()
        ok = " r0rc=0 " in m and " r1rc=0 " in m
        if not os.path.exists(raw):
            cells[cell].append((None, ok))
            continue
        vals = [int(l.split(",")[1]) / 1e3 for l in gzip.open(raw, "rt") if "," in l]
        cells[cell].append((vals[WARM:], ok))
    print("| cell | build / flag | bytes | runs ok | samples | p50 us | p90 us | p99 us | mean us | per-run p50 range us |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    order = ["lat_base_4k", "lat_off_4k", "lat_on_4k", "lat_base_256k", "lat_off_256k", "lat_on_256k"]
    names = {"base": "gpudb (v2) build", "off": "S1 build, flag off", "on": "S1 build, flag on"}
    for c in order + sorted(k for k in cells if k not in order):
        if c not in cells:
            continue
        runs = cells[c]
        pooled = sorted(x for v, ok in runs if v for x in v)
        p50s = [statistics.median(v) for v, ok in runs if v]
        nok = sum(1 for v, ok in runs if ok)
        m = re.match(r"lat_(\w+)_(\w+)", c)
        tag, size = (m.group(1), m.group(2)) if m else (c, "?")
        if not pooled:
            print(f"| {c} | {names.get(tag, tag)} | {size} | {nok}/{len(runs)} | 0 | - | - | - | - | - |")
            continue
        print(f"| {c} | {names.get(tag, tag)} | {size} | {nok}/{len(runs)} | {len(pooled)} | {q(pooled, .5):.2f} | "
              f"{q(pooled, .9):.2f} | {q(pooled, .99):.2f} | {statistics.fmean(pooled):.2f} | "
              f"{min(p50s):.2f}-{max(p50s):.2f} |")


if __name__ == "__main__":
    main()
