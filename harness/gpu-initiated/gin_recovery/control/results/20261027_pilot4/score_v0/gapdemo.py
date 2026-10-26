"""gapdemo.py: no_tcp_control's build:gc part alone on pilot 4's scratch copy (scorer at HEAD, read only): the planned n, the
trials with data, k, and the part's truth, to see whether a data gap shrinks the N_SCORED denominator"""
import sys, csv, re
sys.path.insert(0, "/home/unionxic/rdma-error-wt/gin-control/harness/gpu-initiated/gin_recovery/control/impl/test")
import score_gc as sg
R = sys.argv[1]
rows = [r for r in csv.DictReader(open(R + "/trials_scored.csv")) if r["status"] == "scored"]
p = [x for x in csv.DictReader(open(sg.PREDS, encoding="utf-8")) if x["id"] == "no_tcp_control"][0]
part = [x.strip() for x in p["acceptance"].split(";;") if x.strip().startswith("build:gc:")][0]
rule = part[len("build:gc:"):].strip()
print("rule:", rule[:200])
ak, info = sg.with_data_n(rule, rows)
for inner, g, nd, k in info:
    print("scored n=%d, data-gap trials=%s, trials with data=%d, k=%s" % (len(rows), sorted(g), nd, k))
ev = sg.s2.evaluate(re.sub(r"\bN_SCORED\b", str(len(rows)), ak), {"k": rows}, "k", sg.s2.NIL)
print("part true on the trials with data:", ev[0])
