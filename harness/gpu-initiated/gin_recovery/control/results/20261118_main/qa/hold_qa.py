#!/usr/bin/env python3
"""hold_qa.py <raw>: per trial with a hold, each survivor's hold start -> INJECTED (gate_odd_ms) or -> given up; trials whose hold > 1000 ms."""
import sys, re, glob, os
raw = sys.argv[1]
H = re.compile(r"GIN/RS: rank (\d+): hold of rank (\d+) started.*?mono_ms=([0-9.]+)")
I = re.compile(r"GIN/MI: rank (\d+): INJECTED from rank (\d+) step=\d+ state=\S+ gate_odd_ms=([0-9.]+) mono_ms=([0-9.]+)")
G = re.compile(r"GIN/RS: rank (\d+): the restore of rank (\d+) \(incarnation \d+\) is given up .*?mono_ms=([0-9.]+)")
D = re.compile(r"GIN/RS: rank (\d+): DISARM")
rows = []
for meta in sorted(glob.glob(os.path.join(raw, "*_meta.txt"))):
    stem = meta[:-9]
    per = {}
    dis = 0
    for k in range(4):
        f = "%s_r%d.log" % (stem, k)
        if not os.path.exists(f): continue
        hs = None
        for ln, l in enumerate(open(f, errors="replace"), 1):
            m = H.search(l)
            if m and hs is None: hs = (float(m.group(3)), ln)
            m = I.search(l)
            if m and hs is not None and ("end" not in per.get(k, {})):
                per[k] = dict(start=hs, end=float(m.group(4)), how="INJECTED", gate_odd=float(m.group(3)), line=ln)
            m = G.search(l)
            if m and hs is not None and ("end" not in per.get(k, {})):
                per[k] = dict(start=hs, end=float(m.group(3)), how="given_up", line=ln)
            if D.search(l): dis += 1
    if not per: continue
    durs = {k: v["end"] - v["start"][0] for k, v in per.items()}
    mx = max(durs.values())
    rows.append((os.path.basename(stem), mx, "+".join(sorted(set(v["how"] for v in per.values()))), dis, " ".join("r%d:%.1f(%s L%d)" % (k, durs[k], per[k]["how"], per[k]["line"]) for k in sorted(per))))
import collections
print("trials with a hold:", len(rows))
for r in rows:
    if r[1] > 1000:
        print("LONG", r)
cells = collections.defaultdict(list)
for r in rows: cells[r[0].rsplit("_n", 1)[0]].append(r[1])
for c, v in sorted(cells.items()):
    print("%-40s n %2d hold max per trial %.1f–%.1f ms" % (c, len(v), min(v), max(v)))
