#!/usr/bin/env python3
"""Follow-up (external review) tables, recomputed from the raw per-trial files through rows.py.

usage: followup_summary.py <results/20260925_ts1>   (prints markdown; reads v2_split, v2_f1g0,
       v2_bounds, v2_lat, v2_confirm when present; writes trials_v2_<dir>.csv next to them)
"""
import csv, glob, gzip, math, os, re, statistics, subprocess, sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))


def rows_for(d, out):
    subprocess.run([sys.executable, os.path.join(HERE, "rows.py"), d, "--out", out], check=True,
                   stderr=subprocess.DEVNULL)
    return [r for r in csv.DictReader(open(out)) if r.get("bind_fail") != "1"]


def binom_cdf(x, n, p):
    return sum(math.comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(x + 1))


def cp_upper(x, n, alpha):
    """Clopper-Pearson upper limit: p with P(X <= x | n, p) = alpha."""
    if x >= n:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if binom_cdf(x, n, mid) > alpha:
            lo = mid
        else:
            hi = mid
    return hi


def f(x, d=1):
    try:
        return f"{float(x):.{d}f}"
    except (TypeError, ValueError):
        return "-"


def med(v):
    v = [float(x) for x in v if x not in (None, "", "None")]
    return (statistics.median(v), min(v), max(v)) if v else None


def mfmt(t, d=1):
    return "-" if t is None else f"{t[0]:.{d}f} [{t[1]:.{d}f}-{t[2]:.{d}f}]"


def main():
    R = sys.argv[1]
    # ---- exactly-once boundary ----
    d = os.path.join(R, "v2_split")
    if os.path.isdir(d):
        rs = rows_for(d, os.path.join(R, "trials_v2_split.csv"))
        n = len(rs)
        print("### Exactly-once boundary (split_b)\n")
        print("| n | transparent | split fired once, fault acked (nsplit=1, no_ack=0) | S=2k, U=2k-1, n=1 (only the ADD re-posted) | final signal exact | slots bad (GPU/host) | async r0/r1 |")
        print("|---|---|---|---|---|---|---|")
        print(f"| {n} | {sum(r['transparent_ok'] == '1' for r in rs)}/{n} | "
              f"{sum(r['split_n'] == '1' and r['split_noack'] == '0' for r in rs)}/{n} | "
              f"{sum(r.get('split_boundary') == '1' for r in rs)}/{n} | {sum(r['signal_exact'] == '1' for r in rs)}/{n} | "
              f"{sum(int(r['dev_bad_slots'] or 0) for r in rs)}/{sum(int(r['host_bad_slots'] or 0) for r in rs)} | "
              f"{sum(r['r0_async'] not in ('none', '') for r in rs)}/{sum(r['r1_async'] not in ('none', '') for r in rs)} |")
        ks = sorted(int(r["split_k"]) for r in rs if r.get("split_k"))
        print(f"\nsplit put k: {ks[0] if ks else '-'}..{ks[-1] if ks else '-'} ({len(set(ks))} distinct); "
              f"S/U/n seen: {dict(Counter(r.get('S/U/n', '').split(',')[0] + ']' for r in rs))}\n")
        bad = [r["stem"] for r in rs if not (r["transparent_ok"] == "1" and r.get("split_boundary") == "1")]
        if bad:
            print(f"not transparent or not at the boundary: {bad}\n")
    # ---- in-flight cell ----
    d = os.path.join(R, "v2_f1g0")
    if os.path.isdir(d):
        rs = rows_for(d, os.path.join(R, "trials_v2_f1g0.csv"))
        n = len(rs)
        ok = sum(r["transparent_ok"] == "1" for r in rs)
        x = n - ok
        print("### In-flight F1 (f1g0_b), final follow-up build\n")
        ns = Counter()
        for r in rs:
            m = re.match(r"\[(\d+)/(\d+)/(\d+)", r.get("S/U/n") or "")
            ns[m.group(3) if m else "none"] += 1
        print(f"| n | transparent | failures | 95% upper bound on the failure rate (one-sided) | 95% CI (two-sided) | re-posted n=0/1/2 |")
        print("|---|---|---|---|---|---|")
        lo = 0.0 if x == 0 else 1 - cp_upper(n - x, n, 0.025)
        print(f"| {n} | {ok}/{n} | {x} | {100 * cp_upper(x, n, 0.05):.2f}% | {100 * lo:.2f}%-{100 * cp_upper(x, n, 0.025):.2f}% | "
              f"{ns.get('0', 0)}/{ns.get('1', 0)}/{ns.get('2', 0)} |")
        print(f"\nfault after launch (ms): {mfmt(med(r['fault_after_launch_ms'] for r in rs))}; "
              f"fault -> resumed (ms): {mfmt(med(r.get('fault_to_resumed_ms') for r in rs), 2)}\n")
        bad = [r["stem"] for r in rs if r["transparent_ok"] != "1"]
        if bad:
            print(f"failed trials: {bad}\n")
    # ---- bounds ----
    d = os.path.join(R, "v2_bounds")
    if os.path.isdir(d):
        rs = rows_for(d, os.path.join(R, "trials_v2_bounds.csv"))
        print("### Bounds (helper stalled / killed, application timeout shorter than the recovery, abort mid-round)\n")
        print("| cell | n | transparent | first flush rc | failed flush latency ms (app sees) | later failed flushes max us | stall/die -> watchdog ms | r0 async error | fault -> async (ms) | kernel exit after async ms | ncclCommAbort ms | r0 teardown: joined ms / round in progress / gates poisoned | kernel still running when abort returned | r0rc/r1rc |")
        print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        by = defaultdict(list)
        for r in rs:
            by[r["cell"]].append(r)
        for c in ("stallq_b", "stallc_b", "die_b", "tmo_t", "abortmid_b", "slow_b"):
            v = by.get(c, [])
            if not v:
                continue
            rc = Counter(r["tx_rc"] for r in v)
            fa = []
            for r in v:
                a = r.get("r0_async_ms"); fl = r.get("fault_after_launch_ms")
                if a not in (None, "", "-1.0") and fl not in (None, ""):
                    fa.append(float(a) - float(fl))
            errs = [float(r['tx_err_first_lat_us']) / 1e3 for r in v if r.get('tx_err_first_lat_us') not in (None, '') and r.get('tx_err_n') not in (None, '', '0')]
            later = [r.get('tx_err_later_max_lat_us') for r in v if r.get('tx_err_n') not in (None, '', '0', '1')]
            print(f"| {c} | {len(v)} | {sum(r['transparent_ok'] == '1' for r in v)}/{len(v)} | {dict(rc)} | {mfmt(med(errs))} | {mfmt(med(later))} | "
                  f"{mfmt(med(r.get('stall_to_watchdog_ms') for r in v))} | {sum(r['r0_async'] not in ('none', '') for r in v)}/{len(v)} | "
                  f"{mfmt(med(fa))} | {mfmt(med(r.get('kernel_exit_after_async_ms') for r in v if r.get('kernel_exit_after_async_ms') not in (None, '', '-1.0')))} | "
                  f"{mfmt(med(r.get('teardown_ms_r0') for r in v), 0)} | "
                  f"{mfmt(med(r.get('td_join_ms_r0') for r in v))} / {sum(r.get('td_round_r0') == '1' for r in v)} / "
                  f"{mfmt(med(r.get('td_poisoned_r0') for r in v), 0)} | {sum(r.get('post_abort_running_r0') == '1' for r in v)}/{len(v)} | "
                  f"{dict(Counter(r['r0rc'] + '/' + r['r1rc'] for r in v))} |")
        print()
        for r in rs:
            if r.get("left") not in ("0", None):
                print(f"leftover processes: {r['stem']} left={r['left']}")
    # ---- latency, cumulative ----
    d = os.path.join(R, "v2_lat")
    if os.path.isdir(d):
        cells = defaultdict(list)
        for meta in sorted(glob.glob(os.path.join(d, "*_meta.txt"))):
            stem = meta[: -len("_meta.txt")]
            cell = os.path.basename(stem).rsplit("_", 1)[0]
            raw = stem + "_lat_raw.csv.gz"
            if os.path.exists(raw):
                v = [int(l.split(",")[1]) / 1e3 for l in gzip.open(raw, "rt") if "," in l][100:]
                cells[cell].append(v)
        print("### Fault-free latency, cumulative removal (p50 of pooled samples, us)\n")
        order = [("on", "flag on (S1)"), ("c1gpufence", "- system-scope fences -> GPU scope"),
                 ("c2nogate", "- and the poster gate removed"), ("c3nopoll", "- and the poll-region counting removed"),
                 ("off", "flag off"), ("base", "gpudb v2 build")]
        for size in ("4k", "256k"):
            print(f"| {size} | runs | p50 | per-run p50 range | step saves | cumulative saves |")
            print("|---|---|---|---|---|---|")
            prev = None; first = None
            for tag, name in order:
                runs = cells.get(f"lat_{tag}_{size}", [])
                if not runs:
                    continue
                pooled = sorted(x for v in runs for x in v)
                p50 = pooled[int(round(0.5 * (len(pooled) - 1)))]
                p50s = [statistics.median(v) for v in runs]
                if first is None:
                    first = p50
                step = "-" if prev is None else f"{prev - p50:.2f}"
                print(f"| {name} | {len(runs)} | {p50:.2f} | {min(p50s):.2f}-{max(p50s):.2f} | {step} | {first - p50:.2f} |")
                prev = p50
            print()
    # ---- regression confirmation ----
    d = os.path.join(R, "v2_confirm")
    if os.path.isdir(d):
        rs = rows_for(d, os.path.join(R, "trials_v2_confirm.csv"))
        print("### Regression confirmation on the final follow-up build\n")
        print("| cell | n | transparent | flush rc | async r0/r1 | rounds init/resp | declined r0 | teardown line r0/r1 |")
        print("|---|---|---|---|---|---|---|---|")
        by = defaultdict(list)
        for r in rs:
            by[r["cell"]].append(r)
        for c in sorted(by):
            v = by[c]
            print(f"| {c} | {len(v)} | {sum(r['transparent_ok'] == '1' for r in v)}/{len(v)} | {dict(Counter(r['tx_rc'] for r in v))} | "
                  f"{sum(r['r0_async'] not in ('none', '') for r in v)}/{sum(r['r1_async'] not in ('none', '') for r in v)} | "
                  f"{sum(int(r['n_rec_init']) for r in v)}/{sum(int(r['n_rec_resp']) for r in v)} | "
                  f"{sum(1 for r in v if r['decl_r0'])} | {sum(r.get('td_r0') == '1' for r in v)}/{sum(r.get('td_r1') == '1' for r in v)} |")
        print()


if __name__ == "__main__":
    main()
