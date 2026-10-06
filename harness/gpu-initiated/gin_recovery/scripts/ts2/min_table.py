#!/usr/bin/env python3
"""Markdown table of the minimal bidirectional program's cells from trials_min.csv (rows_min.py).
usage: min_table.py trials_min.csv"""
import csv, sys
from collections import OrderedDict

def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None

def rng(v, fmt="%.1f"):
    v = [x for x in v if x is not None]
    return "-" if not v else (fmt % min(v) if min(v) == max(v) else (fmt + "–" + fmt) % (min(v), max(v)))

rows = list(csv.DictReader(open(sys.argv[1])))
cells = OrderedDict()
for r in rows:
    if r.get("r0rc") == "1" and r.get("A_ran") != "1" and r.get("B_ran") != "1":
        continue  # did not start (rendezvous port)
    cells.setdefault(r["cell"], []).append(r)
print("| cell | n | ok | A (rain→sunny): tx done / rx done / host bad / signal exact | B (sunny→rain): tx done / rx done / host bad / signal exact | sunny kernel ends ms (tx / rx) | rain kernel ends ms (tx / rx) |")
print("|---|---|---|---|---|---|---|")
for c, rs in cells.items():
    def col(d):
        if not any(r.get(d + "_ran") == "1" for r in rs):
            return "–"
        return "%s / %s / %s / %s" % (rng([f(r.get(d + "_tx_done")) for r in rs], "%.0f"), rng([f(r.get(d + "_rx_done")) for r in rs], "%.0f"),
                                      rng([f(r.get(d + "_host_bad")) for r in rs], "%.0f"), rng([f(r.get(d + "_signal_exact")) for r in rs], "%.0f"))
    # kernel ends: sunny sends B and receives A; rain sends A and receives B
    sunny = "%s / %s" % (rng([f(r.get("B_tx_kernel_end_ms")) for r in rs], "%.0f"), rng([f(r.get("A_rx_kernel_end_ms")) for r in rs], "%.0f"))
    rain = "%s / %s" % (rng([f(r.get("A_tx_kernel_end_ms")) for r in rs], "%.0f"), rng([f(r.get("B_rx_kernel_end_ms")) for r in rs], "%.0f"))
    print("| %s | %d | %d | %s | %s | %s | %s |" % (c, len(rs), sum(int(r["ok"]) for r in rs), col("A"), col("B"), sunny, rain))
