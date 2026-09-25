#!/usr/bin/env python3
"""predict.py - the floor-on model of README section A, frozen, as a predictor; and the check of
its predictions against new measurements (out-of-sample, review item 1).

  predict.py                      print the predictions for the out-of-sample cells (table + CSV)
  predict.py --csv FILE           also write them to FILE
  predict.py --check DIR [...]    compare with DIR/attempts.csv (analyze.py output): per trial
                                  and per cell, non-first trials (trial >= 2) scored, trial 1 listed

Model (frozen from results/20260925/A, trials >= 2; not refitted here):
  nominal(T) = 4.096 us x 2^T;  Tc = max(T,16);  I = 2 x nominal(Tc)
  firmware adaptive schedule, absolute times after the post (ms), the entry point varies:
      S = 12.4 21.0 37.6 71.3 138.4 239.0 440.4 977.2 1782.5 3930.3 8225.1
  t_A  = last point reached while each step S[k]-S[k-1] <= nominal(Tc) (+0.5 ms tolerance)
  s_next = S[k+1]-S[k] after t_A (unknown after 8225.1 -> infinity)
  first regular timeout  t_L1 = t_A + min(s_next, I)
  detect(R=1) = t_A;  detect(R>=2) = t_L1 + (R-2) x I;  R=0 not modelled
  regular timeouts = R-1, spaced I; adaptive retransmissions = (k - j + 1) for entry point j in 0..3
Acceptance (stated before the run): |measured - predicted| <= 1.5 ms for every non-first trial.
"""
import csv
import math
import statistics as st
import sys

S = [12.4, 21.0, 37.6, 71.3, 138.4, 239.0, 440.4, 977.2, 1782.5, 3930.3, 8225.1]
TOL = 0.5
ACCEPT_MS = 1.5
CELLS = [(10, 7), (12, 7), (15, 7), (16, 7), (15, 1), (15, 3), (15, 5), (17, 1), (17, 2), (17, 3), (17, 5)]


def opt(v):
    return "-" if v is None else f"{v:.1f}"


def nominal(T):
    return 4.096e-3 * 2 ** T


def model(T, R):
    Tc = max(T, 16)
    nc = nominal(Tc)
    I = 2 * nc
    k = 0
    while k + 1 < len(S) and S[k + 1] - S[k] <= nc + TOL:
        k += 1
    tA = S[k]
    s_next = S[k + 1] - S[k] if k + 1 < len(S) else math.inf
    tL1 = tA + min(s_next, I)
    if R == 0:
        det = None
    elif R == 1:
        det = tA
    else:
        det = tL1 + (R - 2) * I
    return dict(T=T, R=R, I=I, tA=tA, tL1=tL1 if R >= 2 else None, detect=det,
                n_lat=R - 1 if R >= 1 else None, n_adp=(k - 3 + 1, k + 1))


def show(cells):
    print("| T | R | I (ms) | t_A end of adaptive phase (ms) | first regular timeout (ms) | regular timeouts | "
          "adaptive retransmissions | predicted detect (ms) |")
    print("|---|---|---|---|---|---|---|---|")
    for T, R in cells:
        m = model(T, R)
        print(f"| {T} | {R} | {m['I']:.2f} | {m['tA']:.1f} | {opt(m['tL1'])} | "
              f"{m['n_lat']} | {m['n_adp'][0]}-{m['n_adp'][1]} | {m['detect']:.2f} |")


def check(dirs):
    rows = []
    for d in dirs:
        rows += list(csv.DictReader(open(f"{d}/attempts.csv")))
    out = []
    print("| T | R | non-first trials | predicted (ms) | measured median [min-max] (ms) | error median [min-max] (ms) | "
          "within 1.5 ms | regular timeouts (pred / meas) | regular interval (pred / meas median) | "
          "first regular timeout (pred / meas median) | trial 1 detect (error) |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    cells = sorted(set((int(r["T"]), int(r["R"])) for r in rows))
    for T, R in cells:
        m = model(T, R)
        c = [r for r in rows if int(r["T"]) == T and int(r["R"]) == R]
        nf = [r for r in c if r["trial"] != "1"]
        f1 = [r for r in c if r["trial"] == "1"]
        if m["detect"] is None or not nf:
            continue
        det = [float(r["detect_ms"]) for r in nf]
        err = [d - m["detect"] for d in det]
        ok = sum(abs(e) <= ACCEPT_MS for e in err)
        gaps = []
        for r in nf:
            lt = [float(x) for x in r["lat_times_ms"].split()]
            gaps += [b - a for a, b in zip(lt, lt[1:])]
        fl = [float(r["t_first_lat"]) for r in nf if r["t_first_lat"] not in ("-", "")]
        nl = sorted(set(int(r["n_lat"]) for r in nf))
        t1 = ", ".join(f"{float(r['detect_ms']):.1f} ({float(r['detect_ms']) - m['detect']:+.1f})" for r in f1)
        print(f"| {T} | {R} | {len(nf)} | {m['detect']:.2f} | {st.median(det):.2f} [{min(det):.2f}-{max(det):.2f}] | "
              f"{st.median(err):+.2f} [{min(err):+.2f}-{max(err):+.2f}] | {ok}/{len(nf)} | {m['n_lat']} / {','.join(map(str, nl))} | "
              f"{m['I']:.1f} / {st.median(gaps):.1f} | "
              f"{opt(m['tL1'])} / {opt(st.median(fl) if fl else None)} | {t1} |")
        out += [(T, R, r["trial"], float(r["detect_ms"]), m["detect"]) for r in c]
    allnf = [(T, R, d, p) for T, R, tr, d, p in out if tr != "1"]
    if allnf:
        e = [abs(d - p) for _, _, d, p in allnf]
        print(f"\nnon-first trials: {sum(x <= ACCEPT_MS for x in e)}/{len(e)} within {ACCEPT_MS} ms; max |error| {max(e):.2f} ms")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "--check":
        check(a[1:])
    else:
        show(CELLS)
        if len(a) == 2 and a[0] == "--csv":
            with open(a[1], "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["T", "R", "I_ms", "tA_ms", "tL1_ms", "n_lat", "n_adp_min", "n_adp_max", "detect_ms"])
                for T, R in CELLS:
                    m = model(T, R)
                    w.writerow([T, R, f"{m['I']:.3f}", m["tA"], "" if m["tL1"] is None else f"{m['tL1']:.2f}",
                                m["n_lat"], m["n_adp"][0], m["n_adp"][1], f"{m['detect']:.2f}"])
