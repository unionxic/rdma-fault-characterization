#!/usr/bin/env python3
"""analyze.py - summarize unified RDMA fault harness CSVs.

For each fault, reports the dominant (status, vendor_err) error code, detection
and recovery latency stats (n, mean, median, stddev, p95, p99, 95% CI half-width),
verify success rate, RETRY_EXC sub-causes, and partial-write byte accounting:
bytes that LANDED (measured by RDMA-READ readback of the pre-zeroed responder
buffer) versus bytes SENT as implied by the sq_psn advance (sq_psn_delta x PMTU),
and how often the two independent measurements agree.

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

def ival(r, key, default=-1):
    v = r.get(key)
    if v in (None, ""): return default
    try: return int(v)
    except ValueError: return default

def partial_report(rows, indent):
    """Partial-write accounting. Returns printed lines (may be empty)."""
    out = []
    new = [r for r in rows if ival(r, "bytes_landed_readback") >= 0]
    if new:
        mtu = ival(new[0], "mtu_bytes", 0)
        landed = [ival(r, "bytes_landed_readback") for r in new]
        total = [ival(r, "matching_bytes_total") for r in new]
        sent = [ival(r, "bytes_sent_psn") for r in new]
        sq = [ival(r, "sq_psn_delta") for r in new]
        n = len(new)
        agree = sum(1 for l, s in zip(landed, sent) if l == s)
        diff = [l - s for l, s in zip(landed, sent)]
        nonprefix = sum(1 for l, t in zip(landed, total) if t != l)
        pkt_aligned = sum(1 for l in landed if mtu and l % mtu == 0)
        out.append(f"{indent}partial: landed (RDMA-READ readback) {min(landed)}..{max(landed)} B "
                   f"(mean {st.mean(landed):.0f} B), {pkt_aligned}/{n} PMTU-aligned")
        out.append(f"{indent}         sent (sq_psn_delta x PMTU) {min(sent)}..{max(sent)} B "
                   f"(sq_psn_delta {min(sq)}..{max(sq)}, PMTU={mtu} B)")
        pk = f" ({min(diff)/mtu:+.1f}..{max(diff)/mtu:+.1f} pkts)" if mtu else ""
        out.append(f"{indent}         landed == sent: {agree}/{n} trials; landed-sent "
                   f"{min(diff):+d}..{max(diff):+d} B{pk}; "
                   f"matching bytes outside the prefix: {nonprefix}/{n} trials")
        return out
    legacy = [r for r in rows if ival(r, "bytes_landed", 0) > 0]
    if legacy:
        bl = [ival(r, "bytes_landed") for r in legacy]
        out.append(f"{indent}partial (legacy CSV): bytes_landed {min(bl)}..{max(bl)} B is "
                   f"sq_psn_delta x PMTU only (PSN-derived, not measured)")
    return out

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
    ind = " " * 23
    for fault, rows in sorted(rows_by_fault.items()):
        det = stats([float(r["detect_ns"]) for r in rows if r["detect_ns"] not in ("","-1")])
        rec = stats([float(r["recover_ns"]) for r in rows if r["recover_ns"] not in ("","-1")])
        fp = defaultdict(int)
        for r in rows:
            fp[(r["status_name"], r["vendor_err"])] += 1
        dom = max(fp.items(), key=lambda kv: kv[1])
        vok = [r for r in rows if r.get("verify_ok") == "1"]
        vdone = [r for r in rows if r.get("verify_ok") in ("0", "1")]
        verify = f"{len(vok)}/{len(vdone)}" if vdone else "-"   # "-": no recovery (proc_kill)
        detstr = f"{fmt_ns(det['mean'])} ± {fmt_ns(det['ci'])}" if det else "-"
        recstr = fmt_ns(rec['mean']) if rec else "-"
        fpstr = f"{dom[0][0][:16]}/{dom[0][1]}"
        print(f"{fault:<22} {len(rows):>3} {fpstr:<26} {detstr:<24} {recstr:<12} {verify:>7}")
        if len(fp) > 1:
            print(f"{ind}error codes: " + ", ".join(f"{k[0]}/{k[1]}×{v}" for k, v in
                                                    sorted(fp.items(), key=lambda kv: -kv[1])))
        if det:
            print(f"{ind}detect: median={fmt_ns(det['median'])} "
                  f"p95={fmt_ns(det['p95'])} p99={fmt_ns(det['p99'])} std={fmt_ns(det['std'])}")
        if rec:
            print(f"{ind}recover: median={fmt_ns(rec['median'])} p95={fmt_ns(rec['p95'])} "
                  f"(method {rows[0].get('recovery','?')})")
        for line in partial_report(rows, ind):
            print(line)
        # RETRY_EXC (0x81) sub-classification (link state + control-channel liveness)
        subs = defaultdict(int)
        for r in rows:
            sc = r.get("sub_cause", "-")
            if sc and sc != "-":
                subs[sc] += 1
        if subs:
            rxvals = [int(r["peer_rx_delta"]) for r in rows
                      if r.get("peer_rx_delta","-1") not in ("","-1")]
            rxstr = f", peer_rx_delta {min(rxvals)}..{max(rxvals)} (diagnostic)" if rxvals else ""
            breakdown = " ".join(f"{k}×{v}" for k, v in sorted(subs.items()))
            print(f"{ind}sub-cause (liveness/link): {breakdown}{rxstr}")
    print()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    main(sys.argv[1:])
