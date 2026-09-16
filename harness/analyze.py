#!/usr/bin/env python3
"""analyze.py - summarize unified RDMA fault harness CSVs.

For each fault, reports the dominant (status, vendor_err) fingerprint, detection
and recovery latency stats (n, mean, median, stddev, p95, p99, 95% CI half-width),
verify success rate, and partial-write byte accounting where present.

Usage: analyze.py results/*.csv
"""
import csv, sys, math, statistics as st
from collections import defaultdict

def ci95(xs):
    n = len(xs)
    if n < 2: return 0.0
    # Student-t 0.975 quantile, small-n table then normal approx
    t = {2:12.71,3:4.303,4:3.182,5:2.776,6:2.571,7:2.447,8:2.365,9:2.306,
         10:2.262,15:2.145,20:2.093,30:2.045,60:2.000}.get(n, 1.96)
    return t * st.pstdev(xs) / math.sqrt(n) if n else 0.0

def fmt_ns(v):
    if v is None: return "-"
    if v >= 1e9:  return f"{v/1e9:.3f} s"
    if v >= 1e6:  return f"{v/1e6:.3f} ms"
    if v >= 1e3:  return f"{v/1e3:.1f} us"
    return f"{v:.0f} ns"

def stats(xs):
    xs = [x for x in xs if x is not None and x >= 0]
    if not xs: return None
    xs_sorted = sorted(xs)
    p = lambda q: xs_sorted[min(len(xs_sorted)-1, int(q*len(xs_sorted)))]
    return dict(n=len(xs), mean=st.mean(xs), median=st.median(xs),
                std=st.pstdev(xs) if len(xs) > 1 else 0.0,
                p95=p(0.95), p99=p(0.99), ci=ci95(xs))

def main(paths):
    rows_by_fault = defaultdict(list)
    for path in paths:
        try:
            with open(path) as f:
                for row in csv.DictReader(f):
                    rows_by_fault[row["fault"]].append(row)
        except FileNotFoundError:
            print(f"(skip missing {path})"); continue

    if not rows_by_fault:
        print("no data"); return

    print(f"\n{'fault':<22} {'n':>3} {'status/vendor':<26} "
          f"{'detect (mean±CI95)':<24} {'recover mean':<12} {'verify':>7}")
    print("-"*100)
    for fault, rows in sorted(rows_by_fault.items()):
        det = stats([float(r["detect_ns"]) for r in rows if r["detect_ns"] not in ("","-1")])
        rec = stats([float(r["recover_ns"]) for r in rows if r["recover_ns"] not in ("","-1")])
        fp = defaultdict(int)
        for r in rows:
            fp[(r["status_name"], r["vendor_err"])] += 1
        dom = max(fp.items(), key=lambda kv: kv[1])
        vok = [r for r in rows if r.get("verify_ok") == "1"]
        verify = f"{len(vok)}/{len(rows)}"
        detstr = f"{fmt_ns(det['mean'])} ± {fmt_ns(det['ci'])}" if det else "-"
        recstr = fmt_ns(rec['mean']) if rec else "-"
        fpstr = f"{dom[0][0][:16]}/{dom[0][1]}"
        print(f"{fault:<22} {len(rows):>3} {fpstr:<26} {detstr:<24} {recstr:<12} {verify:>7}")
        if det:
            print(f"{'':<22} detect: median={fmt_ns(det['median'])} "
                  f"p95={fmt_ns(det['p95'])} p99={fmt_ns(det['p99'])} std={fmt_ns(det['std'])}")
        # partial-write byte accounting
        bl = [int(r["bytes_landed"]) for r in rows if r.get("bytes_landed","0") not in ("","0")]
        sq = [int(r["sq_psn_delta"]) for r in rows if r.get("sq_psn_delta","0") not in ("","0")]
        if bl and sq:
            mtu = int(rows[0].get("mtu_bytes","0") or 0)
            law_ok = all(int(r["bytes_landed"]) == int(r["sq_psn_delta"])*mtu for r in rows
                         if r.get("sq_psn_delta","0") not in ("","0"))
            print(f"{'':<22} partial: bytes_landed {min(bl)}..{max(bl)} "
                  f"(sq_psn_delta {min(sq)}..{max(sq)}, PMTU={mtu}B, "
                  f"bytes==sq*PMTU: {law_ok})")
        # counter-based sub-classification (RETRY_EXC 0x81 disambiguation)
        subs = defaultdict(int)
        for r in rows:
            sc = r.get("sub_cause", "-")
            if sc and sc != "-":
                subs[sc] += 1
        if subs:
            rxvals = [int(r["peer_rx_delta"]) for r in rows
                      if r.get("peer_rx_delta","-1") not in ("","-1")]
            rxstr = f", peer_rx_delta {min(rxvals)}..{max(rxvals)}" if rxvals else ""
            breakdown = " ".join(f"{k}×{v}" for k, v in sorted(subs.items()))
            print(f"{'':<22} sub-cause (hw counter): {breakdown}{rxstr}")
    print()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    main(sys.argv[1:])
