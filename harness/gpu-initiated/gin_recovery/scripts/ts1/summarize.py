#!/usr/bin/env python3
"""trials.csv + rounds.csv (rows.py) -> summary.md tables for TRANSPARENT_S1.md. Recomputed from the CSVs,
which rows.py recomputes from the raw per-trial logs."""
import csv, statistics, sys
from collections import defaultdict


def load(p):
    with open(p) as f:
        return list(csv.DictReader(f))


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def med(v):
    v = [x for x in v if x is not None]
    return statistics.median(v) if v else None


def rng(v):
    v = [x for x in v if x is not None]
    return (min(v), max(v)) if v else (None, None)


def fmt(x, d=2):
    return "-" if x is None else f"{x:.{d}f}"


def cell_of(r):
    if r["base"] == "1":
        tag = "gpudb build"
    elif r["ts"] == "0":
        tag = "S1 build, flag off"
    else:
        tag = "S1 build, flag on"
    d = f" diag={r['diag']}" if r.get("diag") else ""
    return (r.get("cell", ""), r["fault"], r["wait"], r["bytes"], tag + d)


def main():
    trials = load(sys.argv[1])
    rounds = load(sys.argv[2]) if len(sys.argv) > 2 else []
    out = []
    # ---- outcomes (fault trials) ----
    groups = defaultdict(list)
    bindfail = defaultdict(int)
    for r in trials:
        if r["fault"] == "lat":
            continue
        if r.get("bind_fail") == "1":  # never reached NCCL: the driver's own rendezvous port was taken
            bindfail[cell_of(r)] += 1
            continue
        groups[cell_of(r)].append(r)
    out.append("## Outcomes (one row per cell; every value counted from the per-trial logs)\n")
    out.append("| cell | fault | flush | bytes | build/flag | n | transparent (all ok, no error anywhere) | flush rc != ok | "
               "slots bad (dev/host) | final signal exact | async error r0 / r1 | recovered rounds (init/resp) | "
               "declined r0 | r0 exit / r1 exit | left |")
    out.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for k in sorted(groups):
        g = groups[k]
        n = len(g)
        tr = sum(int(r["transparent_ok"]) for r in g)
        rcbad = sum(1 for r in g if r["tx_rc"] not in ("no error", None, ""))
        dbad = sum(1 for r in g if r["dev_bad_slots"] not in ("0", None, ""))
        hbad = sum(1 for r in g if r["host_bad_slots"] not in ("0", None, ""))
        sx = sum(1 for r in g if r["signal_exact"] == "1")
        a0 = sum(1 for r in g if r["r0_async"] not in ("none", None, ""))
        a1 = sum(1 for r in g if r["r1_async"] not in ("none", None, ""))
        ri = sum(int(r["n_rec_init"] or 0) for r in g)
        rr = sum(int(r["n_rec_resp"] or 0) for r in g)
        dec = sum(1 for r in g if r["decl_r0"])
        ex0 = defaultdict(int)
        ex1 = defaultdict(int)
        for r in g:
            ex0[r["r0rc"]] += 1
            ex1[r["r1rc"]] += 1
        exs = ",".join(f"{c}x{e}" for e, c in sorted(ex0.items())) + " / " + ",".join(
            f"{c}x{e}" for e, c in sorted(ex1.items()))
        left = sum(int(r["left"] or 0) for r in g)
        out.append(f"| {k[0]} | {k[1]} | {k[2]} | {k[3]} | {k[4]} | {n} | {tr}/{n} | {rcbad} | {dbad}/{hbad} | {sx}/{n} | "
                   f"{a0}/{a1} | {ri}/{rr} | {dec} | {exs} | {left} |")
    # ---- declines ----
    out.append("\n## Declines\n")
    out.append("| cell | n | reason on rank 0 (first) | reason on rank 1 | flush rc (rank 0) | r0 async error after launch ms "
               "median [range] | fault -> rank-0 decline ms median [range] | mailbox -> decline ms median | r1 async |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for k in sorted(groups):
        g = [r for r in groups[k] if r["decl_r0"] or r["decl_r1"]]
        if not g:
            continue
        reasons0 = sorted(set(r["decl_r0"].split(";")[0] for r in g))
        reasons1 = sorted(set(r["decl_r1"].split(";")[0] for r in g if r["decl_r1"]))
        rcs = sorted(set(r["tx_rc"] for r in g))
        am = [f(r["r0_async_ms"]) for r in g]
        lo, hi = rng(am)
        a1 = sorted(set(r["r1_async"] for r in g))
        fd = [f(r.get("fault_to_decline_ms")) for r in g]
        dlo, dhi = rng(fd)
        out.append(f"| {' '.join(k)} | {len(g)} | {'; '.join(reasons0)} | {'; '.join(reasons1) or '-'} | {', '.join(rcs)} | "
                   f"{fmt(med(am),1)} [{fmt(lo,1)}-{fmt(hi,1)}] | {fmt(med(fd),1)} [{fmt(dlo,1)}-{fmt(dhi,1)}] | "
                   f"{fmt(med([f(r.get('mbx_to_decline_ms')) for r in g]),2)} | {', '.join(a1)} |")
    # ---- recovery timing ----
    if rounds:
        out.append("\n## Recovery rounds (rank 0 initiator lines; ms unless stated)\n")
        rg = defaultdict(list)
        tmap = {r["stem"]: r for r in trials}
        for x in rounds:
            t = tmap.get(x["stem"], {})
            rg[(x.get("cell", ""), x["fault"], x["wait"], t.get("diag", ""))].append(x)
        out.append("| cell | fault | flush | diag | rounds | class | S/U/n (QP 0) seen | quiesce us | prepare us | handshake us | "
                   "commit us | re-post+resume us | helper total ms | mailbox -> resumed ms | fault -> resumed ms |")
        out.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for k in sorted(rg):
            g = rg[k]
            cls = ",".join(sorted(set(x["class"] for x in g)))
            sun = ",".join(sorted(set(x["S/U/n"].strip("[]").split(",")[0] for x in g)))
            if len(sun) > 60:
                sun = sun[:57] + "..."
            def m(key, scale=1.0):
                v = [f(x[key]) for x in g]
                v = [a * scale for a in v if a is not None]
                if not v:
                    return "-"
                lo, hi = min(v), max(v)
                return f"{statistics.median(v):.{0 if scale == 1.0 else 2}f} [{lo:.{0 if scale == 1.0 else 2}f}-{hi:.{0 if scale == 1.0 else 2}f}]"
            out.append(f"| {k[0]} | {k[1]} | {k[2]} | {k[3] or '-'} | {len(g)} | {cls} | {sun} | {m('quiesce_us')} | "
                       f"{m('prepare_us')} | {m('handshake_us')} | {m('commit_us')} | {m('replay_us')} | "
                       f"{m('total_us', 1e-3)} | {m('mbx_to_resumed_us', 1e-3)} | {m('fault_to_resumed_ms', 1.0001)} |")
    # ---- held flush (what the application saw) ----
    out.append("\n## The iteration that held (rank 0: the one flush that lasted longest)\n")
    out.append("| cell | n | max flush latency ms median [range] | other flushes p50 us (median) | fault after launch ms [range] |")
    out.append("|---|---|---|---|---|")
    for k in sorted(groups):
        g = groups[k]
        mx = [f(r["lat_max_us"]) for r in g]
        mx = [x / 1e3 for x in mx if x is not None]
        p50 = [f(r["lat_p50_us"]) for r in g]
        fa = [f(r["fault_after_launch_ms"]) for r in g]
        lo, hi = rng(mx)
        flo, fhi = rng(fa)
        out.append(f"| {' '.join(k)} | {len(g)} | {fmt(med(mx))} [{fmt(lo)}-{fmt(hi)}] | {fmt(med(p50))} | "
                   f"{fmt(flo,0)}-{fmt(fhi,0)} |")
    if bindfail:
        out.append("\nExcluded (the driver's own rendezvous socket could not bind its random port; NCCL never started): " +
                   ", ".join(f"{k[0]} x{v}" for k, v in sorted(bindfail.items())))
    print("\n".join(out))


if __name__ == "__main__":
    main()
