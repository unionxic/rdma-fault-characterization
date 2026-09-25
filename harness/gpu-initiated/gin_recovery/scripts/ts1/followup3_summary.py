#!/usr/bin/env python3
"""Third-review tables from the raw per-trial files (through rows.py).

usage: followup3_summary.py <results/20260925_ts1>   (reads v3_late, v3_abortmon, v3_confirm, v3_lat when
       present; writes trials_v3_<dir>.csv next to them)
"""
import csv, glob, gzip, os, statistics, sys
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from followup_summary import rows_for, med, mfmt, cp_upper  # noqa: E402


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    R = sys.argv[1]
    d = os.path.join(R, "v3_late")
    if os.path.isdir(d):
        rs = rows_for(d, os.path.join(R, "trials_v3_late.csv"))
        print("### Stall after the commit point (2 x hold path; hold 4 s)\n")
        print("| cell | n | transparent | first flush rc | failed flush latency ms | slow iteration ms (if ok) | r0 decline reason | async error r0 | fault -> async ms | re-posted in the round (S/U/n) | r0rc/r1rc |")
        print("|---|---|---|---|---|---|---|---|---|---|---|")
        by = defaultdict(list)
        for r in rs:
            by[r["cell"]].append(r)
        for c in ("late_ok_b", "late_fail_b"):
            v = by.get(c, [])
            if not v:
                continue
            errs = [f(r["tx_err_first_lat_us"]) / 1e3 for r in v if r.get("tx_err_n") not in (None, "", "0")]
            slow = [f(r["lat_max_us"]) / 1e3 for r in v if r["transparent_ok"] == "1" and f(r.get("lat_max_us"))]
            fa = [f(r["r0_async_ms"]) - f(r["fault_after_launch_ms"]) for r in v
                  if f(r.get("r0_async_ms")) not in (None, -1.0) and f(r.get("fault_after_launch_ms")) is not None]
            print(f"| {c} | {len(v)} | {sum(r['transparent_ok'] == '1' for r in v)}/{len(v)} | {dict(Counter(r['tx_rc'] for r in v))} | "
                  f"{mfmt(med(errs))} | {mfmt(med(slow))} | {dict(Counter(r['decl_r0'] or '-' for r in v))} | "
                  f"{sum(r['r0_async'] not in ('none', '') for r in v)}/{len(v)} | {mfmt(med(fa))} | "
                  f"{dict(Counter((r.get('S/U/n') or '-').split(',')[0] for r in v))} | {dict(Counter(r['r0rc'] + '/' + r['r1rc'] for r in v))} |")
        print()
    d = os.path.join(R, "v3_abortmon")
    if os.path.isdir(d):
        rs = rows_for(d, os.path.join(R, "trials_v3_abortmon.csv"))
        print("### ncclCommGetAsyncError in a tight loop on another thread while ncclCommAbort runs mid-round\n")
        print("| cell | n | abort returned (r0) | abort ms | teardown found a round in progress | GIN teardown ms | abort start -> GIN teardown start ms | error queries inside the GIN teardown (library count) | monitor calls during the abort | monitor's last call, ms after abort start | kernel running when abort returned | r0rc/r1rc |")
        print("|---|---|---|---|---|---|---|---|---|---|---|---|")
        by = defaultdict(list)
        for r in rs:
            by[r["cell"]].append(r)
        for c in ("abortmon_b", "abortmonfull_b"):
            v = by.get(c, [])
            if not v:
                continue
            print(f"| {c} | {len(v)} | {sum(r['teardown_r0'] == 'no error' for r in v)}/{len(v)} | {mfmt(med(r.get('teardown_ms_r0') for r in v), 0)} | "
                  f"{sum(r.get('td_round_r0') == '1' for r in v)}/{len(v)} | {mfmt(med(r.get('td_ms_r0') for r in v))} | "
                  f"{mfmt(med(r.get('abort_to_td_start_ms') for r in v), 2)} | {mfmt(med(r.get('td_queries_r0') for r in v), 0)} | "
                  f"{mfmt(med(r.get('abort_mon_samples') for r in v), 0)} | {mfmt(med(r.get('abort_mon_last_after_start_ms') for r in v))} | "
                  f"{sum(r.get('post_abort_running_r0') == '1' for r in v)}/{len(v)} | {dict(Counter(r['r0rc'] + '/' + r['r1rc'] for r in v))} |")
        print()
    d = os.path.join(R, "v3_confirm")
    if os.path.isdir(d):
        rs = rows_for(d, os.path.join(R, "trials_v3_confirm.csv"))
        print("### Regression on the third-review build\n")
        print("| cell | n | transparent | flush rc | async r0/r1 | rounds init/resp | declined r0 | teardown line r0 | abort ms r0 | r0rc/r1rc |")
        print("|---|---|---|---|---|---|---|---|---|---|")
        by = defaultdict(list)
        for r in rs:
            by[r["cell"]].append(r)
        for c in sorted(by):
            v = by[c]
            print(f"| {c} | {len(v)} | {sum(r['transparent_ok'] == '1' for r in v)}/{len(v)} | {dict(Counter(r['tx_rc'] for r in v))} | "
                  f"{sum(r['r0_async'] not in ('none', '') for r in v)}/{sum(r['r1_async'] not in ('none', '') for r in v)} | "
                  f"{sum(int(r['n_rec_init']) for r in v)}/{sum(int(r['n_rec_resp']) for r in v)} | {sum(1 for r in v if r['decl_r0'])} | "
                  f"{sum(r.get('td_r0') == '1' for r in v)} | {mfmt(med(r.get('teardown_ms_r0') for r in v), 0)} | "
                  f"{dict(Counter(r['r0rc'] + '/' + r['r1rc'] for r in v))} |")
        print()
    d = os.path.join(R, "v3_lat")
    if os.path.isdir(d):
        cells = defaultdict(list)
        for meta in sorted(glob.glob(os.path.join(d, "*_meta.txt"))):
            stem = meta[: -len("_meta.txt")]
            raw = stem + "_lat_raw.csv.gz"
            if os.path.exists(raw):
                cells[os.path.basename(stem).rsplit("_", 1)[0]].append(
                    [int(l.split(",")[1]) / 1e3 for l in gzip.open(raw, "rt") if "," in l][100:])
        print("### Fault-free latency on the third-review build (p50 of pooled samples, us)\n")
        print("| cell | runs | p50 | per-run p50 range |")
        print("|---|---|---|---|")
        for c in sorted(cells):
            pooled = sorted(x for v in cells[c] for x in v)
            p50s = [statistics.median(v) for v in cells[c]]
            print(f"| {c} | {len(cells[c])} | {pooled[len(pooled) // 2]:.2f} | {min(p50s):.2f}-{max(p50s):.2f} |")
        print()


if __name__ == "__main__":
    main()
