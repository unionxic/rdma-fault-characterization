#!/usr/bin/env python3
"""score_pilot.py <scratch copy of the pilot folder>: score_gc.score() on a SCRATCH copy with the pilot/smoke marks off and
every key planned at the n it has, so each prediction's count() reads as "k of n" on the pilot's single trials. Not a
score: a rule check per trial. Prints per prediction: verdict, and per count() part key, inner condition, count/n."""
import os, sys, json
T = "/home/unionxic/rdma-error-wt/gin-control/harness/gpu-initiated/gin_recovery/control/impl/test"
sys.path.insert(0, T)
import score_gc as sg

R = os.path.abspath(sys.argv[1])
sg.smoke_of = lambda r: None
rows = sg.rows_gc.all_rows(R)
have = {}
for r in rows:
    have[r["key"]] = have.get(r["key"], 0) + 1
c = sg.load_cells()
po = {k: have.get(k, 0) for k in list(c["cells"].keys())}
po.update({k: n for k, n in have.items()})
captured = []
orig = sg.perf_review
res_holder = {}
_orig_score = sg.score


def run():
    out = []
    import csv
    # re-run the scorer's prediction loop through score() and capture its results via a patched SCORE.md writer is
    # complex; instead call score() for its files and evaluate parts ourselves with the same helpers
    _orig_score(R, planned_override=po)
    return out


run()
# per-prediction per-trial evaluation with the scorer's own helpers
mc = sg.mirror_cells(); reg = sg.regression_entries(c, mc)
import csv, re
tr = list(csv.DictReader(open(os.path.join(R, "trials_scored.csv"))))
scored = {}
for r in tr:
    if r["status"] == "scored":
        scored.setdefault(r["key"], []).append(r)
preds = list(csv.DictReader(open(sg.PREDS, encoding="utf-8")))
mpreds = list(csv.DictReader(open(sg.MPREDS, encoding="utf-8")))
res = {}
for p in preds:
    acc = p["acceptance"].strip()
    keys = [x.strip() for x in p["cells"].split(";") if x.strip()]
    if acc.startswith("cost:"):
        res[p["id"]] = {"kind": "cost", "keys": keys}
        continue
    parts = []
    for part in [x.strip() for x in acc.split(";;")]:
        if part.startswith("mirror:"):
            mres, missing = sg.mirror_part(part[len("mirror:"):].strip(), scored, {k: len(v) for k, v in scored.items()}, mpreds)
            for mid, v, mk, mev, sh in mres:
                parts.append(("mirror:" + mid, v, str(mk)[:80]))
            continue
        m = re.match(r"([A-Za-z0-9_]+@[a-z]+|build:[a-z]+|local:[a-z_]+):\s*(.*)$", part)
        pk, pa = ([m.group(1)], m.group(2)) if m else (keys, part)
        ev, sh, nd, gp = sg.eval_part(pa, pk, scored, {k: len(v) for k, v in scored.items()}, {})
        for e in ev:
            k, ok, dd = e[0], e[1], e[2]
            for inner, cnt, n, *rest in dd:
                ids = [r["id"] for r in scored.get(k, [])]
                parts.append((k, "%d/%d" % (cnt, n), inner[:160], ids, [g[1] for g in gp]))
    res[p["id"]] = {"kind": sg.kind_of(p), "parts": parts}
json.dump(res, open(os.path.join(R, "rulecheck.json"), "w"), ensure_ascii=False, indent=1, default=str)
for pid, d in res.items():
    print(pid, d.get("kind"))
    for x in d.get("parts", []):
        print("   ", x[0], x[1], "|", x[2] if len(x) > 2 else "")
