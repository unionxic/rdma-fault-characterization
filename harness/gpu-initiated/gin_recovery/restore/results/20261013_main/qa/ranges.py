#!/usr/bin/env python3
"""Ranges over the per-trial recount (out/trials_recount.csv) per cell: min-max of each numeric column, n trials."""
import csv, sys, collections, glob, os, re
rows = list(csv.DictReader(open(sys.argv[1])))
by = collections.defaultdict(list)
for r in rows:
    by[r["key"]].append(r)
def nums(rs, col):
    out = []
    for r in rs:
        for x in str(r.get(col, "")).split(","):
            try:
                out.append(float(x))
            except ValueError:
                pass
    return out
cols = ["restore_time_ms", "restore_after_kill_ms", "dead_after_kill_ms", "act_after_hold_ms", "act_after_dead_ms", "later_n",
        "later_ms", "ckpt_fetch_ms", "log_import_entries", "replayed_dup_steps", "pause_max_ms", "rel_after_dead_ms",
        "rel_after_dead_rc_ms", "fb_after_hold_ms", "rel_after_fb_ms", "pause_n", "r1_pause_start_minus_kill_ms"]
for k in sorted(by):
    rs = by[k]
    parts = []
    for c in cols:
        v = nums(rs, c)
        if v:
            parts.append("%s=%g-%g(n=%d)" % (c, min(v), max(v), len(v)))
    print(k, "trials=%d" % len(rs), " ".join(parts))
# wall time per trial (meta wall_s) per cell
res = sys.argv[2]
w = collections.defaultdict(list)
for mf in glob.glob(os.path.join(res, "raw", "*_meta.txt")) + glob.glob(os.path.join(res, "reg", "*_meta.txt")):
    t = open(mf).read()
    m = re.search(r"wall_s=([0-9.]+)", t); c = re.search(r"cell=(\S+)", t); l = re.search(r" lib=(\S+)", t)
    w[(c.group(1), "hk" if l and l.group(1) == "hk" else "rs")].append(float(m.group(1)))
for k in sorted(w):
    print("wall", "%s@%s" % k, "%g-%g s" % (min(w[k]), max(w[k])))
