#!/usr/bin/env python3
"""tables.py - the README tables for Tasks A and B, recomputed from attempts.csv (analyze.py output).

usage: tables.py results/20260925
"""
import csv
import statistics as st
import sys
from collections import defaultdict

R0 = sys.argv[1] if len(sys.argv) > 1 else "results/20260925"


def load(path):
    return list(csv.DictReader(open(path)))


def f(x):
    return float(x) if x not in ("-", "", None) else None


def rng(xs, nd=1):
    xs = [x for x in xs if x is not None]
    if not xs:
        return "-"
    return f"{st.median(xs):.{nd}f} [{min(xs):.{nd}f}-{max(xs):.{nd}f}]"


def irng(xs):
    return f"{min(xs)}-{max(xs)}" if min(xs) != max(xs) else f"{min(xs)}"


def cells(rows, labels):
    c = defaultdict(list)
    for r in rows:
        if r["label"] in labels:
            c[(int(r["T"]), int(r["R"]))].append(r)
    return c


A = load(f"{R0}/A/attempts.csv") + load(f"{R0}/smoke/attempts.csv")
B = load(f"{R0}/B/attempts.csv")

print("### A1: floor ON, retry_cnt 7, T sweep (labels on + smoke)\n")
print("| T | 4.096us*2^T (ms) | I = 2*4.096us*2^max(T,16) (ms) | N | RETRY_EXC 12/0x81 | detect median [min-max] (ms) | "
      "adaptive retransmissions | last adaptive (ms) | first regular timeout (ms) | regular interval median [min-max] (ms) | "
      "interval / 4.096us*2^T | regular timeouts | own transmissions | R*I - detect (ms) | (R+1)*4.096us*2^T (ms) |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
ca = cells(A, {"on", "smoke"})
for (T, R) in sorted(k for k in ca if k[1] == 7):
    rs = ca[(T, R)]
    nom = 4.096e-3 * 2 ** T
    I = 2 * 4.096e-3 * 2 ** max(T, 16)
    det = [f(r["detect_ms"]) for r in rs]
    gaps = []
    for r in rs:
        lt = [float(x) for x in r["lat_times_ms"].split()]
        gaps += [b - a for a, b in zip(lt, lt[1:])]
    print(f"| {T} | {nom:.3f} | {I:.1f} | {len(rs)} | {sum(r['status'] == '12' and r['vendor'] == '0x81' for r in rs)}/{len(rs)} | "
          f"{rng(det)} | {irng([int(r['n_adp']) for r in rs])} | {rng([f(r['t_last_adp']) for r in rs])} | "
          f"{rng([f(r['t_first_lat']) for r in rs])} | {rng(gaps)} | {st.median(gaps) / nom:.3f} | "
          f"{irng([int(r['n_lat']) for r in rs])} | {irng([int(r['n_own_xmit']) for r in rs])} | "
          f"{rng([R * I - d for d in det])} | {(R + 1) * nom:.1f} |")

print("\n### A2: floor ON, T=14, retry_cnt sweep\n")
print("| R | N | detect median [min-max] (ms) | adaptive retransmissions | regular timeouts (per trial) | own transmissions | "
      "R*I - detect median (ms), I = 536.9 ms |")
print("|---|---|---|---|---|---|---|")
for (T, R) in sorted(k for k in ca if k[0] == 14):
    rs = ca[(T, R)]
    I = 2 * 4.096e-3 * 2 ** 16
    det = [f(r["detect_ms"]) for r in rs]
    print(f"| {R} | {len(rs)} | {rng(det)} | {irng([int(r['n_adp']) for r in rs])} | "
          f"{','.join(r['n_lat'] for r in rs)} | {irng([int(r['n_own_xmit']) for r in rs])} | "
          f"{st.median([R * I - d for d in det]):.1f} |")

print("\n### B: floor OFF (min_ack_timeout_limit_disabled=1, inside ackfloor_window.sh)\n")
print("| T | R | 4.096us*2^T (ms) | N | RETRY_EXC 12/0x81 | detect median [min-max] (ms) | mean +- sd (ms) | adaptive retransmissions | "
      "first timeout t1 (ms) | t1 / 4.096us*2^T | regular interval median [min-max] (ms) | interval / 4.096us*2^T | "
      "timeouts counted | own transmissions | t1 + (R+1)*4.096us*2^T - detect, median (ms) |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
cb = cells(B, {"off"})
for (T, R) in sorted(cb):
    rs = cb[(T, R)]
    nom = 4.096e-3 * 2 ** T
    det = [f(r["detect_ms"]) for r in rs]
    t1 = [f(r["t_first_lat"]) for r in rs]
    gaps = []
    for r in rs:
        lt = [float(x) for x in r["lat_times_ms"].split()]
        gaps += [b - a for a, b in zip(lt, lt[1:])]
    sd = st.stdev(det) if len(det) > 1 else 0.0
    print(f"| {T} | {R} | {nom:.3f} | {len(rs)} | {sum(r['status'] == '12' and r['vendor'] == '0x81' for r in rs)}/{len(rs)} | "
          f"{rng(det, 2)} | {st.mean(det):.2f} +- {sd:.2f} | {irng([int(r['n_adp']) for r in rs])} | {rng(t1, 2)} | "
          f"{st.median(t1) / nom:.2f} | {rng(gaps, 2)} | {st.median(gaps) / nom:.3f} | {irng([int(r['n_lat']) for r in rs])} | "
          f"{irng([int(r['n_own_xmit']) for r in rs])} | "
          f"{st.median([a + (R + 1) * nom - d for a, d in zip(t1, det)]):.2f} |")

print("\n### Controls without the sampler thread (-N)\n")
print("| floor | T | R | N | detect median [min-max] (ms) | same cell with sampler, median [min-max] (ms) |")
print("|---|---|---|---|---|---|")
for lab, rows, ref, fl in (("nosamp", A, ca, "on"), ("nosampoff", B, cb, "off")):
    cc = cells(rows, {lab})
    for k in sorted(cc):
        d = [f(r["detect_ms"]) for r in cc[k]]
        dr = [f(r["detect_ms"]) for r in ref[k]]
        print(f"| {fl} | {k[0]} | {k[1]} | {len(d)} | {rng(d, 1 if fl == 'on' else 2)} | {rng(dr, 1 if fl == 'on' else 2)} |")
