#!/usr/bin/env python3
# summarize.py - aggregate results/<date>/matrix.csv into summary.md
import csv, sys, collections
csvpath = sys.argv[1] if len(sys.argv) > 1 else "results/matrix.csv"
rows = list(csv.DictReader(open(csvpath)))
cells = collections.OrderedDict()
for r in rows:
    k = (r["fault"], r["wait_mode"])
    cells.setdefault(k, []).append(r)
def agg(rs, col):
    c = collections.Counter(r[col] for r in rs)
    return ";".join(f"{k}x{v}" for k, v in c.items())
out = []
out.append("# NVSHMEM IBGDA fault x wait_mode summary\n")
out.append(f"Source: `{csvpath}`  ({len(rows)} trials)\n")
out.append("| fault | wait_mode | n | init_outcome | target_outcome | data_check | silent_success | status(cqe) | cqe_op/syn/ven | teardown | host_err_ms(med) |")
out.append("|---|---|--:|---|---|---|--:|---|---|---|--:|")
def med(rs):
    v = sorted(float(r["host_error_ms"]) for r in rs if r["host_error_ms"] not in ("na",""))
    return f"{v[len(v)//2]:.0f}" if v else "na"
for k, rs in cells.items():
    ss = sum(int(r["silent_success"]) for r in rs)
    fp = agg(rs, "status")
    op = collections.Counter((r["cqe_opcode"], r["cqe_syndrome"], r["cqe_vendor_err"]) for r in rs)
    opstr = ";".join(f"{o}/{s}/{v}x{n}" for (o, s, v), n in op.items())
    out.append(f"| {k[0]} | {k[1]} | {len(rs)} | {agg(rs,'init_outcome')} | {agg(rs,'target_outcome')} | {agg(rs,'data_check')} | {ss}/{len(rs)} | {fp} | {opstr} | {agg(rs,'teardown')} | {med(rs)} |")
open(csvpath.rsplit('/',1)[0] + "/summary.md", "w").write("\n".join(out) + "\n")
print("\n".join(out))
