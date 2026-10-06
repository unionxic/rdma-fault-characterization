#!/usr/bin/env python3
"""S2 tables from trials.csv / rounds.csv (rows.py) and the gate micro-test output. Prints Markdown.

usage: summarize.py <trials.csv> [--rounds rounds.csv] [--gate gate_test.txt ...] [--cells c1,c2,...]
Every number is counted from the CSV rows (one row per trial, one per recovery round).
"""
import argparse, csv, re, statistics as st
from collections import OrderedDict, Counter


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def med(v, fmt="%.2f"):
    v = [x for x in v if x is not None]
    if not v:
        return "-"
    return (fmt % st.median(v)) + (" [" + (fmt % min(v)) + "–" + (fmt % max(v)) + "]" if len(v) > 1 else "")


def outcome(r):
    if r["transparent_ok"] == "1":
        return "transparent"
    if r.get("decl_r0") or r.get("decl_r1"):
        return "declined"
    return "failed"


def outcomes_table(rows, cells):
    print("| cell | n | transparent | declined | failed | flush rc != ok | bad slots (dev/host) | signals exact | async error r0/r1 | rounds init/resp | tie kept/yielded | declines (reasons) |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for c in cells:
        rs = [r for r in rows if r["cell"] == c and r.get("bind_fail") != "1"]
        if not rs:
            continue
        oc = Counter(outcome(r) for r in rs)
        def num(r, k):
            try:
                return int(r.get(k) or 0)
            except ValueError:
                return 0
        rcbad = sum(1 for r in rs if r.get("tx_rc") not in ("no error", None, "")
                    or r.get("tx_rc_r1") not in ("no error", None, ""))
        dev = sum(num(r, "dev_bad_slots") + num(r, "dev_bad_slots_r0") for r in rs)
        host = sum(num(r, "host_bad_slots") + num(r, "host_bad_slots_r0") for r in rs)
        sig = sum(1 for r in rs if r.get("signal_exact") == "1" and r.get("signal_exact_r0") in ("1", None, ""))
        a0 = sum(1 for r in rs if r.get("r0_async") not in ("none", None, ""))
        a1 = sum(1 for r in rs if r.get("r1_async") not in ("none", None, ""))
        ri = sum(int(r.get("rec_init_r0") or 0) + int(r.get("rec_init_r1") or 0) for r in rs)
        rp = sum(int(r.get("rec_resp_r0") or 0) + int(r.get("rec_resp_r1") or 0) for r in rs)
        tk = sum(int(r.get("tie_kept") or 0) for r in rs)
        yd = sum(int(r.get("yielded") or 0) for r in rs)
        reasons = Counter()
        for r in rs:
            for k in ("decl_r0", "decl_r1"):
                for x in (r.get(k) or "").split(";"):
                    if x:
                        reasons[x] += 1
        rr = "; ".join("%s (%d)" % (k, v) for k, v in reasons.most_common(3))
        print("| %s | %d | %d | %d | %d | %d | %d/%d | %d/%d | %d/%d | %d/%d | %d/%d | %s |" % (
            c, len(rs), oc["transparent"], oc["declined"], oc["failed"], rcbad, dev, host, sig, len(rs), a0, a1, ri, rp,
            tk, yd, rr or "-"))


def lat_table(rows):
    cells = OrderedDict()
    for r in rows:
        if r["cell"].startswith("lat_") and r.get("lat_p50_us"):
            cells.setdefault(r["cell"], []).append(r)
    print("| cell | runs | p50 µs (median of runs) | p99 µs | mean µs | per-run p50 range |")
    print("|---|---|---|---|---|---|")
    for c, rs in cells.items():
        p50 = [f(r["lat_p50_us"]) for r in rs]
        print("| %s | %d | %.2f | %.2f | %.2f | %.2f–%.2f |" % (
            c, len(rs), st.median(p50), st.median([f(r["lat_p99_us"]) for r in rs]),
            st.median([f(r["lat_mean_us"]) for r in rs]), min(p50), max(p50)))


def rounds_table(rounds, cells, burst):
    # burst: stem -> WQEs per iteration of one sending thread (K puts + 1 signal), for the partial-prefix count
    print("| cell | initiator rounds | re-posted n (faulted QP): min/median/max | n not a multiple of the burst | rounds with host-rung WQEs | rescued WQEs (sum) | chunked re-posts | helper total ms | fault → resumed ms |")
    print("|---|---|---|---|---|---|---|---|---|")
    for c in cells:
        rs = [x for x in rounds if x["cell"] == c and x["role"] == "initiator"]
        if not rs:
            continue
        ns, part = [], 0
        K = None
        for x in rs:
            m = re.match(r"\[(\d+)/(\d+)/(\d+)", x.get("S/U/n") or "")
            if m:
                S, U, n = (int(v) for v in m.groups())
                ns.append(n)
                k = burst.get(x["stem"])
                if k and n % k:
                    part += 1
        hr = sum(1 for x in rs if int(x.get("host_rung") or 0) > 0)
        resc = sum(int(x.get("rescued") or 0) for x in rs)
        chk = sum(1 for x in rs if int(x.get("chunks") or 0) > 0)
        print("| %s | %d | %s | %s | %d | %d | %d | %s | %s |" % (
            c, len(rs), ("%d/%d/%d" % (min(ns), st.median(ns), max(ns))) if ns else "-",
            ("%d" % part) if any(burst.get(x["stem"]) for x in rs) else "-", hr, resc, chk,
            med([f(x.get("total_us")) / 1e3 if f(x.get("total_us")) else None for x in rs]),
            med([f(x.get("resumed_after_fault_ms")) for x in rs])))


def teardown_table(rows, cells):
    # review cells: did the kernel exit and did ncclCommAbort return (exit 7 = the application's abort watchdog)
    print("| cell | n | r0 exit codes | r1 exit codes | abort returned r0 / r1 | teardown ms r0 | teardown ms r1 | watchdog surfaces | declines (reasons) |")
    print("|---|---|---|---|---|---|---|---|---|")
    for c in cells:
        rs = [r for r in rows if r["cell"] == c and r.get("bind_fail") != "1"]
        if not rs:
            continue
        def codes(k):
            return ", ".join("%s ×%d" % (a, b) for a, b in sorted(Counter(r.get(k) or "?" for r in rs).items()))
        ab0 = sum(1 for r in rs if r.get("teardown_r0"))
        ab1 = sum(1 for r in rs if r.get("teardown_r1"))
        wd = sum(int(r.get("watchdog") or 0) for r in rs)
        reasons = Counter()
        for r in rs:
            for k in ("decl_r0", "decl_r1"):
                for x in (r.get(k) or "").split(";"):
                    if x:
                        reasons[x] += 1
        print("| %s | %d | %s | %s | %d/%d / %d/%d | %s | %s | %d | %s |" % (
            c, len(rs), codes("r0rc"), codes("r1rc"), ab0, len(rs), ab1, len(rs),
            med([f(r.get("teardown_ms_r0")) for r in rs], "%.0f"), med([f(r.get("teardown_ms_r1")) for r in rs], "%.0f"),
            wd, "; ".join("%s (%d)" % (k, v) for k, v in reasons.most_common(3)) or "-"))


def flap_table(rows, rounds, cells):
    print("| cell | n | transparent | declined | cut length s | first Q4 record after cut start s | GID moved (r1) | GID wait ms | resumed after cut start s | slow iteration s | watchdog surfaces | declines (reasons) |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for c in cells:
        rs = [r for r in rows if r["cell"] == c and r.get("bind_fail") != "1"]
        if not rs:
            continue
        oc = Counter(outcome(r) for r in rs)
        # the longest GID wait of any round of the trial (the cut rank's; the other rank's is < 1 ms)
        gw = []
        for r in rs:
            w = [f(x.get("gid_wait_ms")) for x in rounds if x["stem"] == r["stem"] and f(x.get("gid_wait_ms")) is not None]
            if w:
                gw.append(max(w))
        moved = sum(1 for r in rs if r.get("gid_moved_r1"))
        reasons = Counter()
        for r in rs:
            for k in ("decl_r0", "decl_r1"):
                for x in (r.get(k) or "").split(";"):
                    if x:
                        reasons[x] += 1
        print("| %s | %d | %d | %d | %s | %s | %d/%d | %s | %s | %s | %d | %s |" % (
            c, len(rs), oc["transparent"], oc["declined"],
            med([f(r.get("cut_len_ms")) / 1e3 if f(r.get("cut_len_ms")) else None for r in rs]),
            med([f(r.get("fault_to_mbx_ms")) / 1e3 if f(r.get("fault_to_mbx_ms")) else None for r in rs]),
            moved, len(rs), med(gw, "%.0f"),
            med([f(r.get("fault_to_resumed_ms")) / 1e3 if f(r.get("fault_to_resumed_ms")) else None for r in rs]),
            med([f(r.get("lat_max_us") or r.get("tx_max_iter_us")) / 1e6 if f(r.get("lat_max_us") or r.get("tx_max_iter_us")) else None for r in rs]),
            sum(int(r.get("watchdog") or 0) for r in rs),
            "; ".join("%s (%d)" % (k, v) for k, v in reasons.most_common(3)) or "-"))


def gate_table(paths):
    print("| node | GPU | threads | scope | work ns | quiesce rounds | entries | back-outs | lost CE writes | lost increments | Dekker violations | inside while odd | result |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for p in paths:
        for line in open(p, errors="replace"):
            d = dict(re.findall(r'(\w+)=("[^"]*"|\S+)', line))
            if "result" not in d:
                continue
            print("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                line.split()[0], d["gpu"].strip('"'), d["threads"], d["scope"], d["work_ns"], d["rounds"], d["enters"],
                d["backouts"], d["lost_ce_writes"], d["lost_increments"], d["dekker_violations"],
                d["inside_nonzero_while_odd"], d["result"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trials")
    ap.add_argument("--rounds")
    ap.add_argument("--gate", nargs="*", default=[])
    ap.add_argument("--cells")
    a = ap.parse_args()
    rows = list(csv.DictReader(open(a.trials)))
    cells = a.cells.split(",") if a.cells else list(OrderedDict.fromkeys(r["cell"] for r in rows))
    if a.gate:
        print("### Gate micro-test\n")
        gate_table(a.gate)
        print()
    if any(r["cell"].startswith("lat_") for r in rows):
        print("### Latency\n")
        lat_table(rows)
        print()
    print("### Outcomes\n")
    outcomes_table(rows, [c for c in cells if not c.startswith("lat_")])
    rounds = list(csv.DictReader(open(a.rounds))) if a.rounds else []
    td = [c for c in cells if c.startswith(("ring_", "flap_", "f2_", "f4_"))]
    if td:
        print("\n### Kernel exit and abort return\n")
        teardown_table(rows, td)
    fl = [c for c in cells if c.startswith("flap_")]
    if fl:
        print("\n### Address flaps\n")
        flap_table(rows, rounds, fl)
    if a.rounds:
        print("\n### Recovery rounds\n")
        burst = {r["stem"]: int(r["burst_K"]) + 1 for r in rows if r.get("burst_K")}
        rounds_table(rounds, cells, burst)


if __name__ == "__main__":
    main()
