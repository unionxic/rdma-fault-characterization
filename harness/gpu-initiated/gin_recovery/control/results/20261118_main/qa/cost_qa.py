#!/usr/bin/env python3
"""cost_qa.py <main dir>: lat_p50_us per node, arm, k from r0.kv; also recomputed p50 from lat_raw.csv.gz; medians and probe-on vs probe-off."""
import sys, os, glob, gzip, statistics, re
M = sys.argv[1]
for node in ("rain", "sunny"):
    res = {}
    for arm in ("probe-off", "probe-on"):
        ks = []
        for k in range(1, 7):
            stem = os.path.join(M, "cost_probe_%s" % node, "cost_lat4k_%s_%s_k%d" % (arm, node, k))
            kv = dict(t.split("=", 1) for t in open(stem + "_r0.kv").read().split() if "=" in t)
            raw = sorted(int(l.split(",")[1]) for l in gzip.open(stem + "_lat_raw.csv.gz", "rt") if "," in l)
            p50raw = statistics.median(raw) / 1000.0
            meta = open(stem + "_meta.txt").read()
            pm = re.search(r"\bprobe_ms=(\S*)", meta)
            ks.append((k, float(kv["lat_p50_us"]), p50raw, len(raw), kv.get("tx_err_first_lat_us"), pm.group(1) if pm else "?"))
        res[arm] = ks
        print(node, arm, " ".join("k%d:%.2f(raw %.3f, n %d)" % (k, a, b, n) for k, a, b, n, _, _ in ks), "| median %.3f" % statistics.median(a for _, a, _, _, _, _ in ks), "| probe_ms", sorted(set(x[5] for x in ks)))
    off = statistics.median(a for _, a, _, _, _, _ in res["probe-off"])
    on = statistics.median(a for _, a, _, _, _, _ in res["probe-on"])
    print(node, "probe-on vs probe-off: %.3f vs %.3f us, diff %+.3f us = %+.2f %%" % (on, off, on - off, 100 * (on - off) / off))
