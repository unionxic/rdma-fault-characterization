#!/usr/bin/env python3
"""fresh_check.py - review item 2: what the section-A model does and does not describe for fresh
processes / fresh contexts / idle gaps. Reads attempts.csv (analyze.py output) of the given dirs.

Per trial: t_L1 (first regular timeout), t_A (last adaptive retransmission), the regular part
residual detect - (t_L1 + (R-2) x I), regular timeouts vs R-1, regular gaps vs I, and the
deviation of detect from the steady-state model prediction (predict.model).
"""
import csv
import statistics as st
import sys
from predict import model


def rng(x, nd=1):
    return "-" if not x else f"{st.median(x):.{nd}f} [{min(x):.{nd}f}-{max(x):.{nd}f}]"


rows = []
for d in sys.argv[1:]:
    rows += list(csv.DictReader(open(f"{d}/attempts.csv")))
cells = {}
for r in rows:
    cells.setdefault((r["label"], int(r["T"]), int(r["R"])), []).append(r)
print("| mode | T | R | trials | which trials | detect median [min-max] (ms) | model (steady) | detect - model median [min-max] (ms) | "
      "t_A last adaptive (ms) | t_L1 first regular (ms) | t_L1 - t_A (ms) | regular timeouts == R-1 | max abs(gap - I) (ms) | "
      "max abs(detect - (t_L1 + (R-2) I)) (ms) |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for (lab, T, R), rs in sorted(cells.items()):
    m = model(T, R)
    for which, sel in (("all", rs), ("trial 1", [r for r in rs if r["trial"] == "1"]), ("trials >= 2", [r for r in rs if r["trial"] != "1"])):
        if not sel or (which != "all" and len(sel) == len(rs)):
            continue
        if lab.startswith("freshP") and which != "all":
            continue
        det = [float(r["detect_ms"]) for r in sel]
        tA = [float(r["t_last_adp"]) for r in sel if r["t_last_adp"] not in ("-", "")]
        tL = [float(r["t_first_lat"]) for r in sel if r["t_first_lat"] not in ("-", "")]
        dd = [float(r["t_first_lat"]) - float(r["t_last_adp"]) for r in sel if r["t_first_lat"] not in ("-", "") and r["t_last_adp"] not in ("-", "")]
        nl = sum(int(r["n_lat"]) == R - 1 for r in sel)
        gaps, res = [], []
        for r in sel:
            lt = [float(x) for x in r["lat_times_ms"].split()]
            gaps += [abs((b - a) - m["I"]) for a, b in zip(lt, lt[1:])]
            if lt:
                res.append(abs(float(r["detect_ms"]) - (lt[0] + (R - 2) * m["I"])))
        dev = [x - m["detect"] for x in det]
        print(f"| {lab} | {T} | {R} | {len(sel)} | {which} | {rng(det)} | {m['detect']:.1f} | {rng(dev)} | {rng(tA)} | {rng(tL)} | "
              f"{rng(dd)} | {nl}/{len(sel)} | {max(gaps) if gaps else float('nan'):.2f} | {max(res) if res else float('nan'):.2f} |")
