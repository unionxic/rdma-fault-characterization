#!/usr/bin/env python3
"""qa_check.py - independent recomputation of the README's CPU claims from the raw files
(trials.csv + events.csv), without analyze.py. Prints one line per claim.

usage: qa_check.py results/20260925
"""
import csv
import statistics as st
import sys
from collections import defaultdict

R0 = sys.argv[1]


def rows(p):
    return list(csv.DictReader(open(p)))


def runs(rs):
    # run index by order: new run when (label,T,R) reappears after other rows or trial decreases
    last, lt, n = None, {}, defaultdict(int)
    for r in rs:
        k = (r["label"], r["T"], r["R"])
        t = int(r["trial"])
        if (k != last and k in lt) or (k in lt and t < lt[k]):
            n[k] += 1
        r["run"] = n[k]
        lt[k] = t
        last = k
    return rs


def timeline(evs, name, det):
    out = []
    for e in evs:
        if e["counter"] != name:
            continue
        lo, hi = float(e["lo_us"]) / 1e3, float(e["hi_us"]) / 1e3
        mid = (lo + hi) / 2
        if mid < 0 or mid > det + 50:
            continue
        out += [(mid, hi - lo)] * (int(e["new"]) - int(e["old"]))
    return sorted(out)


def load(d):
    T = runs(rows(f"{R0}/{d}/trials.csv"))
    E = defaultdict(list)
    for e in runs(rows(f"{R0}/{d}/events.csv")):
        E[(e["label"], e["T"], e["R"], e["run"], e["trial"])].append(e)
    out = []
    for t in T:
        det = int(t["detect_ns"]) / 1e6
        ev = E[(t["label"], t["T"], t["R"], t["run"], t["trial"])]
        lat = timeline(ev, "local_ack_timeout_err", det)
        adp = timeline(ev, "roce_adp_retrans", det)
        rcv = [m for m, _ in timeline(ev, "port_rcv_packets", det)]
        xm = [m for m, _ in timeline(ev, "port_xmit_packets", det)]
        # xmit at t in [-1, 0) is the original post (bracket straddles t0)
        allx = []
        for e in ev:
            if e["counter"] == "port_xmit_packets":
                m = (float(e["lo_us"]) + float(e["hi_us"])) / 2e3
                if -1.0 <= m <= det + 50:
                    allx += [m] * (int(e["new"]) - int(e["old"]))
        own = [m for m in allx if not any(abs(m - r) <= 1.0 for r in rcv)]
        out.append(dict(t=t, det=det, lat=lat, adp=adp, own=own))
    return out


A = load("A") + load("smoke")
B = load("B")
nom = lambda T: 4.096e-3 * 2 ** T
I = lambda T: 2 * nom(max(T, 16))

sampled = [x for x in A + B if x["t"]["sampler"] == "1"]
print("sampled trials:", len(sampled), " all trials A+smoke:", len(A), " B:", len(B))
print("RETRY_EXC 12/0x81 in all trials:", sum(x["t"]["status"] == "12" and x["t"]["vendor_err"] == "0x81" for x in A + B), "/", len(A + B))
print("warm-up ok:", sum(x["t"]["warm_ok"] == "1" for x in A + B), "/", len(A + B))
print("T_q==T and R_q==R:", sum(x["t"]["T_q"] == x["t"]["T"] and x["t"]["R_q"] == x["t"]["R"] for x in A + B), "/", len(A + B))
bg = [x for x in sampled if x["t"]["bg_local_ack_timeout_err"] != "0" or x["t"]["bg_roce_adp_retrans"] != "0"]
print("sampled trials with timeout/adp change in quiet window:", len(bg))
print("max sampler round (ms):", max(float(x["t"]["max_round_us"]) for x in sampled) / 1e3,
      " trials with a round > 2 ms:", sum(float(x["t"]["max_round_us"]) > 2000 for x in sampled),
      " mean round range (us):", min(float(x["t"]["mean_round_us"]) for x in sampled), max(float(x["t"]["mean_round_us"]) for x in sampled))
print("widest adp/lat bracket (ms):", max(w for x in sampled for _, w in x["lat"] + x["adp"]))
fl = [x["lat"][-1][0] - x["det"] for x in sampled if x["lat"]]
print("final lat - CQE (ms) range:", round(min(fl), 3), round(max(fl), 3))
# unchanged counters in fault window
for c in ["roce_adp_retrans_to", "roce_slow_restart", "roce_slow_restart_trans", "packet_seq_err", "out_of_sequence",
          "implied_nak_seq_err", "duplicate_request"]:
    print(f"  d_{c} nonzero in", sum(x["t"][f"d_{c}"] != "0" for x in A + B), "trials")
print("  d_req_cqe_error values:", sorted(set(x["t"]["d_req_cqe_error"] for x in A + B)))

on = [x for x in A if x["t"]["label"] in ("on", "smoke") and x["t"]["sampler"] == "1"]
# regular interval vs 2*nominal(max(T,16))
dev = []
for x in on:
    T = int(x["t"]["T"])
    ts = [m for m, _ in x["lat"]]
    dev += [abs((b - a) - I(T)) for a, b in zip(ts, ts[1:])]
print("floor on: max |lat gap - I| (ms):", round(max(dev), 3), "over", len(dev), "gaps")
ok = sum(len(x["lat"]) == int(x["t"]["R"]) - 1 for x in on if x["t"]["R"] != "0")
print("floor on: n_lat == R-1:", ok, "/", sum(1 for x in on if x["t"]["R"] != "0"))
o1 = 0; n1 = 0; bad = []
for x in on:
    R = int(x["t"]["R"])
    if R == 0:
        continue
    n1 += 1
    exp = 1 + len(x["adp"]) + max(R - 2, 0) - (1 if R == 1 else 0)
    if len(x["own"]) == exp:
        o1 += 1
    else:
        bad.append((x["t"]["label"], x["t"]["T"], R, x["t"]["trial"], len(x["own"]), exp))
print("floor on: own transmissions == 1 + adp + (R-2) (R=1: adp):", o1, "/", n1, bad)
na = [len(x["adp"]) for x in on if x["t"]["R"] != "0"]
print("floor on R>=1: adaptive retransmissions range:", min(na), max(na))
fit = [x for x in on if x["t"]["R"] != "0" and x["t"]["trial"] != "1"]
errs = [abs(int(x["t"]["R"]) * I(int(x["t"]["T"])) - (96.3 if int(x["t"]["T"]) <= 16 else 364.0) - x["det"]) for x in fit]
print("floor on trials>=2, R>=1: |R*I - c - detect| max (ms):", round(max(errs), 2), "n", len(errs))
t1s = [x for x in on if x["t"]["R"] != "0" and x["t"]["trial"] == "1"]
e1 = [abs(int(x["t"]["R"]) * I(int(x["t"]["T"])) - (96.3 if int(x["t"]["T"]) <= 16 else 364.0) - x["det"]) for x in t1s]
print("floor on trial 1: n", len(e1), "min dev (ms)", round(min(e1), 1), "max", round(max(e1), 1))
starts = sorted(round(x["adp"][0][0], 1) for x in fit if x["adp"])
print("floor on trials>=2 first adaptive time (ms):", starts)
t20 = [x for x in on if x["t"]["T"] == "20"]
print("T=20 detect:", [round(x["det"], 2) for x in t20])
for x in t20:
    if x["t"]["trial"] == "2":
        print("  T20 trial2 adp:", [round(m, 2) for m, _ in x["adp"]], "lat:", [round(m, 2) for m, _ in x["lat"]], "own:", len(x["own"]))
r0 = [x for x in on if x["t"]["R"] == "0"]
print("floor on R=0: detect", [round(x["det"], 1) for x in r0], "n_lat", [len(x["lat"]) for x in r0], "own", [len(x["own"]) for x in r0])

off = [x for x in B if x["t"]["label"].startswith("off")]
offs = [x for x in B if x["t"]["sampler"] == "1"]
print("floor off: all trials", len(B), " d_roce_adp_retrans nonzero:", sum(x["t"]["d_roce_adp_retrans"] != "0" for x in B),
      " sampled adp events:", sum(len(x["adp"]) for x in offs))
print("floor off sampled: own == R+1:", sum(len(x["own"]) == int(x["t"]["R"]) + 1 for x in offs), "/", len(offs),
      " n_lat == R+2:", sum(len(x["lat"]) == int(x["t"]["R"]) + 2 for x in offs), "/", len(offs))
fe = [abs(x["lat"][0][0] + (int(x["t"]["R"]) + 1) * nom(int(x["t"]["T"])) - x["det"]) for x in offs]
print("floor off: max |t1 + (R+1)*nominal - detect| (ms):", round(max(fe), 2))
r1 = [x["lat"][0][0] / nom(int(x["t"]["T"])) for x in offs]
print("floor off: t1/nominal per-trial range:", round(min(r1), 3), round(max(r1), 3))
dv = []
for x in offs:
    T = int(x["t"]["T"])
    if T < 10:
        continue
    ts = [m for m, _ in x["lat"]][1:]  # gaps between retransmission timeouts
    dv += [(b - a) / nom(T) for a, b in zip(ts, ts[1:])]
print("floor off T>=10: gap/nominal range:", round(min(dv), 3), round(max(dv), 3))
cells = defaultdict(list)
for x in B:
    cells[(x["t"]["label"], int(x["t"]["T"]), int(x["t"]["R"]))].append(x["det"])
for k in sorted(cells):
    print("  B", k, "n", len(cells[k]), "median %.2f min %.2f max %.2f" % (st.median(cells[k]), min(cells[k]), max(cells[k])))
cells = defaultdict(list)
for x in A:
    cells[(x["t"]["label"], int(x["t"]["T"]), int(x["t"]["R"]))].append(x["det"])
for k in sorted(cells):
    print("  A", k, "n", len(cells[k]), "median %.1f min %.1f max %.1f" % (st.median(cells[k]), min(cells[k]), max(cells[k])))
