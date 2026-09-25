#!/usr/bin/env python3
"""qa_check_d.py - independent re-computation of the section-D claims from the raw files
(trials.csv, events.csv, predictions.csv), without analyze.py / predict.py / fresh_check.py.

usage: qa_check_d.py results/20260925
"""
import collections
import csv
import statistics as st
import sys

R0 = sys.argv[1]


def nominal(T):
    return 4.096e-3 * 2 ** T


# D1: prediction errors, from trials.csv and the frozen predictions.csv
pred = {(int(r["T"]), int(r["R"])): float(r["detect_ms"]) for r in csv.DictReader(open(f"{R0}/oos/predictions.csv"))}
tr = list(csv.DictReader(open(f"{R0}/oos/trials.csv")))
err = [(int(r["T"]), int(r["R"]), r["trial"], int(r["detect_ns"]) / 1e6 - pred[(int(r["T"]), int(r["R"]))]) for r in tr]
nf = [e for e in err if e[2] != "1"]
print(f"D1: non-first {len(nf)}, within 1.5 ms {sum(abs(e[3]) <= 1.5 for e in nf)}, "
      f"misses {[(T, R, t, round(e, 2)) for T, R, t, e in nf if abs(e) > 1.5]}")
cell = collections.defaultdict(list)
for T, R, t, e in nf:
    cell[(T, R)].append(e)
print("D1: per-cell median error (ms):", {k: round(st.median(v), 2) for k, v in sorted(cell.items())})
print("D1: RETRY_EXC", sum(r["status"] == "12" and r["vendor_err"] == "0x81" for r in tr), "/", len(tr))

# D2-D4: the regular part, from events.csv (local_ack_timeout_err) keyed by run_id
for d in ("fresh", "fresh20", "freshW"):
    ev = collections.defaultdict(list)
    for e in csv.DictReader(open(f"{R0}/{d}/events.csv")):
        if e["counter"] == "local_ack_timeout_err":
            ev[(e["run_id"], e["trial"])] += [(float(e["lo_us"]) + float(e["hi_us"])) / 2e3] * (int(e["new"]) - int(e["old"]))
    out = collections.defaultdict(list)
    chk = []
    for r in csv.DictReader(open(f"{R0}/{d}/trials.csv")):
        T, R = int(r["T"]), int(r["R"])
        I = 2 * nominal(max(T, 16))
        det = int(r["detect_ns"]) / 1e6
        lat = sorted(t for t in ev[(r["run_id"], r["trial"])] if 0 <= t <= det + 50)
        gaps = [abs((b - a) - I) for a, b in zip(lat, lat[1:])]
        chk.append((len(lat) == R - 1, abs(det - (lat[0] + (R - 2) * I)), max(gaps),
                    r["status"] == "12" and r["vendor_err"] == "0x81",
                    int(r["bg_local_ack_timeout_err"]) + int(r["bg_roce_adp_retrans"])))
        first = "first" if r["trial"] == "1" else "later"
        out[(r["label"], T, first)].append(det)
    print(f"{d}: trials {len(chk)}, n_lat==R-1 {sum(c[0] for c in chk)}, max |detect-(t_L1+(R-2)I)| {max(c[1] for c in chk):.2f} ms, "
          f"max |gap-I| {max(c[2] for c in chk):.2f} ms, RETRY_EXC {sum(c[3] for c in chk)}, quiet-window timeouts {sum(c[4] for c in chk)}")
    for k, v in sorted(out.items()):
        print(f"   {k}: n={len(v)} median {st.median(v):.1f} min {min(v):.1f} max {max(v):.1f}")
    if d == "freshW":
        rs = list(csv.DictReader(open(f"{R0}/{d}/trials.csv")))
        print(f"   prior WRITEs completed: {sorted(set((r['pre_n'], r['pre_ok']) for r in rs))}")
