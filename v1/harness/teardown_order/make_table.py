#!/usr/bin/env python3
"""make_table.py - the README results table, recomputed from the raw trials.csv files.

usage: make_table.py <results_dir>     (e.g. results/20260925)

Reads every <results_dir>/*/trials.csv except superseded_*; the node of the victim is taken
from the session directory name (*_rain = victim on rain, else sunny). Smoke rows are left out.
"""
import csv
import glob
import os
import statistics
import sys
from collections import OrderedDict, Counter


def f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v == -1 else v


def rng(vals, fmt="%.1f"):
    vals = [v for v in vals if v is not None]
    if not vals:
        return "-"
    return (fmt + " [" + fmt + "-" + fmt + "]") % (statistics.median(vals), min(vals), max(vals))


def main(d):
    rows = []
    for p in sorted(glob.glob(os.path.join(d, "*", "trials.csv"))):
        sess = os.path.basename(os.path.dirname(p))
        if sess.startswith("superseded"):
            continue
        node = "rain" if sess.endswith("_rain") else "sunny"
        for r in csv.DictReader(open(p)):
            if r["variant"].startswith("smoke"):
                continue
            r["_node"] = node
            r["_sess"] = sess
            rows.append(r)
    by = OrderedDict()
    for r in rows:
        by.setdefault((r["_node"], r["variant"]), []).append(r)

    def order(key):
        """SIGKILL rows first (sunny then rain, verbs then DEVX), then the live controls"""
        node, v = key
        rs = by[key]
        return (rs[0]["trigger"] != "kill", node != "sunny", "devx" in v, v.startswith("ctl") or "ctl_" in v,
                list(by).index(key))
    by = OrderedDict((k, by[k]) for k in sorted(by, key=order))
    print("| victim | variant | trigger | N | first error CQE | error ms | last ACK ms | OOB FIN ms | reaped ms |")
    print("|---|---|---|---|---|---|---|---|---|")
    for (node, v), rs in by.items():
        c = Counter()
        for r in rs:
            c["none" if r["status_name"] == "none" else "%s %s/%s" % (r["status_name"], r["status"], r["vendor_err"])] += 1
        fp = ", ".join("%s **%d/%d**" % (k, n, len(rs)) for k, n in c.most_common())
        kill = rs[0]["trigger"] == "kill"
        errs_by = {}
        for r in rs:
            errs_by.setdefault(r["status_name"], []).append(f(r["err_ms"]))
        err = "; ".join("%s %s" % (k.split("_")[0] if len(errs_by) > 1 else "", rng(vv)) for k, vv in errs_by.items() if k != "none").strip() or "-"
        print("| %s | `%s` | %s | %d | %s | %s | %s | %s | %s |" % (
            node, v, rs[0]["trigger"], len(rs), fp, err,
            rng([f(r["last_ok_ms"]) for r in rs], "%.2f") if kill else "-",
            rng([f(r["oob_close_ms"]) for r in rs], "%.2f") if kill else "-",
            rng([f(r["reap_ms"]) for r in rs]) if kill else "-"))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1])
