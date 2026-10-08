#!/usr/bin/env python3
"""Independent recount of the live_boundary study (tag prereg/live-boundary-v1).

Reads only raw files under results/<date>/{CP,CG,G}/ and the frozen predictions.csv. It does not
read score.py, SCORE.md, score.json or trials_scored.csv. Usage:

    python3 qa/recount.py [results/20261008]

Prints: trial-set check (section 7), exclusions (section 8), per-prediction verdicts computed from
the frozen acceptance strings (section 3.0 grammar), descriptive values, and safety records.
"""
import csv
import glob
import math
import os
import re
import sys
from statistics import median

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
RES = os.path.join(BASE, sys.argv[1] if len(sys.argv) > 1 else "results/20261008")
if not os.path.isabs(RES):
    RES = os.path.abspath(RES)

PLAN = {  # EXPERIMENT.md section 7
    "CP0": 5, "CP900": 5, "CP990": 5, "CP1008": 10, "CP1024": 10, "CP1040": 5, "CP1100": 5,
    "CG4300": 5, "CG4600": 10, "CG5000": 5,
    "G2900": 5, "G2985": 5, "G2992": 5, "G2995": 10, "G2998": 10, "G3010": 5, "G3100": 5,
}


class Missing(Exception):
    pass


# ---------------------------------------------------------------- CPU harness
def load_cpu(series):
    trials, excluded = [], []
    fault = "live_stop_probe" if series == "CP" else "live_stop_err"
    for d in sorted(glob.glob(os.path.join(RES, series, "runs", "*"))):
        tag = os.path.basename(d)
        m = re.match(r"lb_c[pg](\d+)_t(\d+)$", tag)
        cell = f"{series}{m.group(1)}"
        stop = int(m.group(1))
        csvs = glob.glob(os.path.join(d, f"{fault}_*.csv"))
        srvs = glob.glob(os.path.join(d, f"{fault}_*.srv.log"))
        t = {"tag": tag, "cell": cell, "set_ms": stop, "series": series}
        if len(csvs) != 1:
            excluded.append((tag, "runner failure: no CSV")); continue
        rows = list(csv.DictReader(open(csvs[0])))
        if len(rows) != 1:
            excluded.append((tag, f"runner failure: {len(rows)} CSV rows")); continue
        r = rows[0]
        srv = open(srvs[0]).read() if srvs else ""
        if f"fault_applied fault={fault}" not in srv:
            excluded.append((tag, "fault not applied: no fault_applied")); continue
        se = re.search(r"stall_end mono_ns=(\d+) measured_ms=([\d.]+)", srv)
        sb = re.search(r"stall_begin mono_ns=(\d+) ms=(\d+)", srv)
        fa = re.search(r"fault_applied fault=\S+ mono_ns=(\d+)", srv)
        lsm = re.search(r"LIVE_STOP_MS=(\d+)", srv)
        if stop > 0 and not se:
            excluded.append((tag, "fault not applied: no stall_end")); continue
        t.update({
            "sub_cause": r["sub_cause"], "status": int(r["status"]), "vendor_err": r["vendor_err"],
            "cqe_ns": int(r["cqe_ns"]), "probe_ms": float(r["probe_ms"]),
            "stall_meas_ms": float(se.group(2)) if se else 0.0,
            "verify_ok": int(r["verify_ok"]), "stale_lines": int(r["stale_lines"]),
            "resync_ms": int(r["resync_ms"]), "t_post_mono_ns": int(r["t_post_mono_ns"]),
            "srv_live_stop_ms": int(lsm.group(1)) if lsm else None,
            "goack_srv_ns": int(fa.group(1)),
            "stall_begin_ns": int(sb.group(1)) if sb else None,
            "stall_end_ns": int(se.group(1)) if se else None,
            "stall_on_probe": bool(sb and "on=probe" in srv),
        })
        out = os.path.join(RES, series, "logs", tag + ".out")
        t["out_ok"] = os.path.exists(out) and "done: 1/1 trials" in open(out).read() \
            and f"=== fault: {fault}" in open(out).read()
        ps = os.path.join(RES, series, "logs", tag + ".pstate")
        t["pstate"] = open(ps).read().split("\n")[0].strip() if os.path.exists(ps) else None
        trials.append(t)
    return trials, excluded


# ---------------------------------------------------------------- GIN
def kv_fields(line):
    return dict(re.findall(r"(\w+)=(\S+)", line))


def load_gin():
    trials, excluded = [], []
    for r0 in sorted(glob.glob(os.path.join(RES, "G", "logs", "rec1_F3_timeout_g*_r0.kv"))):
        stem = r0[:-len("_r0.kv")]
        tag = re.search(r"_(g\d+_t\d+)$", stem).group(1)
        m = re.match(r"g(\d+)_t(\d+)", tag)
        t = {"tag": tag, "cell": f"G{m.group(1)}", "set_ms": int(m.group(1)), "series": "G"}
        r1 = stem + "_r1.kv"; meta = stem + "_meta.txt"
        if not (os.path.getsize(r0) and os.path.exists(r1) and os.path.getsize(r1)):
            excluded.append((tag, "runner failure: kv missing")); continue
        L0 = open(r0).read().split("\n"); L1 = open(r1).read().split("\n")
        fault = next((kv_fields(l) for l in L0 if l.startswith("fault ev=")), None)
        rec = next((kv_fields(l) for l in L0 if l.startswith("rec ev=")), None)
        si = next((i for i, l in enumerate(L1) if l.startswith("stall ")), None)
        if fault is None:
            excluded.append((tag, "fault not applied: no fault ev=")); continue
        if si is None or "end_mono_ms=" not in L1[si]:
            excluded.append((tag, "fault not applied: no stall end")); continue
        st = kv_fields(L1[si])
        off = next(kv_fields(l) for l in L0 if l.startswith("clock_offset_ms="))
        mt = kv_fields(open(meta).read())
        t.update({
            "fault_t_query": float(fault["t_query"]), "fault_t_kret": float(fault["t_kret"]),
            "r0rc": int(mt["r0rc"]), "r1rc": int(mt["r1rc"]), "left": int(mt["left"]),
            "bundle": mt.get("bundle"),
            "r1_stall_ms": float(st["measured_ms"]), "r1_stall_set": int(st["ms"]),
            "r1_stall_on": st["on"],
            "r1_stall_end_r0clock": float(st["end_mono_ms"]) - float(off["clock_offset_ms"]),
            "r1_stall_begin_r0clock": float(st["begin_mono_ms"]) - float(off["clock_offset_ms"]),
            "clock_rtt_ms": float(off["clock_rtt_ms"]),
            "r1_n_rxrec_after_stall": sum(1 for l in L1[si + 1:] if l.startswith("rxrec ")),
            "r1_data_check": next((kv_fields(l).get("data_check") for l in L1 if "data_check=" in l), None),
        })
        if rec:
            t["rec_outcome"] = rec.get("outcome"); t["rec_reason"] = rec.get("reason")
            for k in ("t_prep", "t_ack", "t_decl"):
                if k in rec:
                    t["rec_" + k] = float(rec[k])
        rx = next((kv_fields(l) for l in L1[si + 1:] if l.startswith("rxrec ")), None)
        if rx:
            t["r1_t_req_r0clock"] = float(rx["t_req"]) - float(off["clock_offset_ms"])
            if "t_commit" in rx:
                t["r1_t_commit_r0clock"] = float(rx["t_commit"]) - float(off["clock_offset_ms"])
        r0log = open(stem + "_r0.log").read()
        t["nccl_ver"] = (re.search(r"NCCL version (\S+)", r0log) or [None, None])[1]
        r1log = open(stem + "_r1.log").read()
        sw = re.search(r"stall switch: (\d+) ms on (\w+)", r1log)
        t["r1_switch"] = (int(sw.group(1)), sw.group(2)) if sw else None
        trials.append(t)
    return trials, excluded


# ---------------------------------------------------------------- rule engine (section 3.0)
def wrap_aggregates(expr):
    """ALL(e) -> ALL(lambda T: e, {fields of e}) with field names read from T; returns python source."""
    out, i = [], 0
    while i < len(expr):
        m = re.match(r"(ALL|MOST|NONE|COUNT|MAX|MIN)\(", expr[i:])
        if m:
            depth, j = 1, i + len(m.group(0))
            while depth:
                depth += {"(": 1, ")": -1}.get(expr[j], 0); j += 1
            inner = expr[i + len(m.group(0)):j - 1]
            out.append(f"{m.group(1)}(lambda T: ({field_src(inner)}), {sorted(fields_of(inner))!r})")
            i = j
        else:
            out.append(expr[i]); i += 1
    return "".join(out)


FIELD_RE = re.compile(r"(?<![\w'.])([a-z_][a-z0-9_]*)(?![\w'(])")
KEYWORDS = {"and", "or", "not", "lambda", "e6"}


def field_src(e):
    return FIELD_RE.sub(lambda m: m.group(1) if m.group(1) in KEYWORDS else f"T['{m.group(1)}']", e)


def fields_of(e):
    return {f for f in FIELD_RE.findall(e) if f not in KEYWORDS}


class Rec(dict):
    def __getitem__(self, k):
        if k not in self or dict.get(self, k) is None:
            raise Missing(k)
        return dict.__getitem__(self, k)


def evaluate(expr, trials, strict):
    """Evaluate one clause expression over a list of trials (section 3.0). A trial whose field is
    missing is false in ALL, not counted in COUNT, left out of MAX and MIN. Default reading: the
    expression is evaluated left to right with short-circuit, so a field that is never reached does
    not count as missing. strict=True: a trial missing any field named inside the aggregate is
    treated as missing even if short-circuit would not reach it."""
    misses = []

    def per(f, inner):
        res = []
        for t in trials:
            if strict and any(t.get(k) is None for k in inner):
                res.append((t, None)); continue
            try:
                res.append((t, bool(f(Rec(t)))))
            except Missing:
                res.append((t, None))
        return res

    def mk(name):
        def agg(f, inner):
            if name in ("MAX", "MIN"):
                vals = []
                for t in trials:
                    try:
                        vals.append(f(Rec(t)))
                    except Missing:
                        pass
                return (max if name == "MAX" else min)(vals) if vals else float("nan")
            r = per(f, inner)
            if name == "ALL":
                bad = [t["tag"] for t, v in r if v is not True]
                misses.append(("ALL", bad)); return not bad
            if name == "NONE":
                bad = [t["tag"] for t, v in r if v is True]
                misses.append(("NONE", bad)); return not bad
            if name == "COUNT":
                k = sum(1 for _, v in r if v is True)
                misses.append(("COUNT", [f"count={k} of n={len(trials)}"])); return k
            if name == "MOST":
                n = len(trials); k = sum(1 for _, v in r if v is True)
                misses.append(("MOST", [t["tag"] for t, v in r if v is not True]))
                return k >= math.ceil(0.9 * n) and not any(v is False for _, v in r)
        return agg

    env = {n: mk(n) for n in ("ALL", "MOST", "NONE", "COUNT", "MAX", "MIN")}
    env["N"] = lambda: len(trials)
    val = eval(compile(wrap_aggregates(expr), "<acceptance>", "eval"), env)
    return val, misses


SCOPE_RE = re.compile(r"^\s*(pooled\s+)?((?:[A-Z]+\d+)(?:\s*,\s*[A-Z]+\d+)*)(?:\s+where\s+(.+?))?\s*:\s*(.+)$")


def default_cells(cells_col):
    head = cells_col.split(":", 1)[0]
    return [c.strip() for c in head.split(",") if re.match(r"^[A-Z]+\d+$", c.strip())]


def judge(pred, by_cell, strict=False):
    clauses = [c.strip() for c in pred["acceptance"].split("; ")]
    results = []
    for cl in clauses:
        m = SCOPE_RE.match(cl)
        if m:
            pooled, cells, where, expr = bool(m.group(1)), [c.strip() for c in m.group(2).split(",")], m.group(3), m.group(4)
        else:
            pooled, cells, where, expr = False, default_cells(pred["cells"]), None, cl
        groups = [("pooled " + ",".join(cells), sum((by_cell.get(c, []) for c in cells), []))] if pooled \
            else [(c, by_cell.get(c, [])) for c in cells]
        for name, ts in groups:
            if where:
                wf = eval(compile(f"lambda T: ({field_src(where)})", "<where>", "eval"))
                keep = []
                for t in ts:
                    try:
                        if wf(Rec(t)):
                            keep.append(t)
                    except Missing:
                        pass
                ts = keep
            if not ts:
                results.append({"clause": cl, "scope": name, "n": 0, "ok": None, "misses": []}); continue
            ok, misses = evaluate(expr, ts, strict)
            results.append({"clause": cl, "scope": name, "n": len(ts), "ok": bool(ok), "misses": misses,
                            "tags": [t["tag"] for t in ts]})
    if any(r["ok"] is False for r in results):
        verdict = "FAIL"
    elif any(r["ok"] is None for r in results):
        verdict = "NO DATA"
    else:
        verdict = "HOLD"
    return verdict, results


# ---------------------------------------------------------------- helpers
def rng(vals, nd=3):
    vals = [v for v in vals if v is not None]
    if not vals:
        return "none"
    return f"{min(vals):.{nd}f}–{max(vals):.{nd}f} (n={len(vals)})"


def main():
    cp, ex_cp = load_cpu("CP"); cg, ex_cg = load_cpu("CG"); g, ex_g = load_gin()
    allt = cp + cg + g
    by_cell = {}
    for t in allt:
        by_cell.setdefault(t["cell"], []).append(t)
    for t in cg:  # derived values used by CGb/CGc (frozen definition) and the mechanism check
        t["x_rule"] = t["stall_meas_ms"] - t["cqe_ns"] / 1e6
        t["d_goack_stop"] = (t["stall_begin_ns"] - t["goack_srv_ns"]) / 1e6

    print("== 1. trial set (section 7)")
    for c, n in PLAN.items():
        got = len(by_cell.get(c, []))
        tags = sorted(by_cell.get(c, []), key=lambda t: int(t["tag"].rsplit("_t", 1)[1]))
        tn = [int(t["tag"].rsplit("_t", 1)[1]) for t in tags]
        print(f"  {c:7s} planned {n:2d} scored {got:2d} t-index {tn == list(range(1, n + 1))}")
    print(f"  total scored {len(allt)} (CP {len(cp)}, CG {len(cg)}, G {len(g)})")
    for s in ("CP", "CG", "G"):
        tl = [l.split() for l in open(os.path.join(RES, s, "trials.log")) if l.strip()]
        print(f"  {s} trials.log lines {len(tl)}, rc!=0: {[x[0] for x in tl if x[1] != 'rc=0']}")
    print("  excluded:", ex_cp + ex_cg + ex_g or "none")
    print("  CPU stop as set (server LIVE_STOP_MS == tag):",
          all(t["srv_live_stop_ms"] == t["set_ms"] for t in cp + cg),
          " stop on PROBE in every CP stall trial:", all(t["stall_on_probe"] for t in cp if t["set_ms"] > 0),
          " runner .out ok:", all(t["out_ok"] for t in cp + cg))
    print("  GIN switch == tag:", all(t["r1_switch"] == (t["set_ms"], "req") and t["r1_stall_set"] == t["set_ms"]
                                     and t["r1_stall_on"] == "req" for t in g),
          " bundle:", {t["bundle"] for t in g}, " NCCL:", {t["nccl_ver"] for t in g})

    print("\n== 2. predictions")
    preds = list(csv.DictReader(open(os.path.join(BASE, "predictions.csv"))))
    for p in preds:
        if p["kind"] != "N":
            continue
        v, res = judge(p, by_cell, strict=False)
        vs, _ = judge(p, by_cell, strict=True)
        print(f"  {p['id']}: {v}" + (f" (strict missing-field reading: {vs})" if vs != v else ""))
        for r in res:
            miss = [(k, b) for k, b in r["misses"] if b]
            print(f"     [{r['scope']}] n={r['n']} ok={r['ok']} details={miss}")

    print("\n== 3. CPU values")
    for c in ("CP0", "CP900", "CP990", "CP1008", "CP1024", "CP1040", "CP1100"):
        ts = by_cell[c]
        ans = [t for t in ts if t["sub_cause"] == "server_qp_err"]
        na = [t for t in ts if t["sub_cause"] == "no_answer"]
        print(f"  {c}: n={len(ts)} answered={len(ans)} no_answer={len(na)} other={len(ts) - len(ans) - len(na)}")
        print(f"     answered probe_ms-stall {rng([t['probe_ms'] - t['stall_meas_ms'] for t in ans])};"
              f" no_answer probe_ms {rng([t['probe_ms'] for t in na])};"
              f" stall-set {rng([t['stall_meas_ms'] - t['set_ms'] for t in ts if t['set_ms']])}")
        for t in sorted(ts, key=lambda t: t["probe_ms"]):
            print(f"       {t['tag']:14s} {t['sub_cause']:13s} probe_ms={t['probe_ms']:9.3f} stall={t['stall_meas_ms']:9.3f}"
                  f" probe-stall={t['probe_ms'] - t['stall_meas_ms']:8.3f} stale={t['stale_lines']}")
    cpstall = [t for t in cp if t["set_ms"] > 0]
    lat = [(t["stall_begin_ns"] - t["goack_srv_ns"]) / 1e6 - t["cqe_ns"] / 1e6 for t in cpstall]
    print(f"  CP stalled: (stall_begin - GOACK)[server clock] - first CQE time = {rng(lat)}"
          " (GOACK->post + CQE->PROBE + PROBE transit)")
    nas = [t for t in cp + cg if t["sub_cause"] == "no_answer"]
    print(f"  pooled no_answer (CP+CG) probe_ms {rng([t['probe_ms'] for t in nas])},"
          f" spread {max(t['probe_ms'] for t in nas) - min(t['probe_ms'] for t in nas):.3f} ms")
    print("     sorted:", " ".join(f"{t['probe_ms']:.2f}" for t in sorted(nas, key=lambda t: t["probe_ms"])))
    for s in ("CP", "CG"):
        print(f"     {s} only: {rng([t['probe_ms'] for t in nas if t['series'] == s])}")
    print(f"  stall_meas - set over CPU stall trials: {rng([t['stall_meas_ms'] - t['set_ms'] for t in cp + cg if t['set_ms']])}")
    ansall = [t for t in cp + cg if t["sub_cause"] == "server_qp_err"]
    print(f"  pooled answered (CP+CG) probe_ms max {max(t['probe_ms'] for t in ansall):.3f}"
          f" ({max(ansall, key=lambda t: t['probe_ms'])['tag']})")
    print(f"  first CQE time (all CPU trials) {rng([t['cqe_ns'] / 1e6 for t in cp + cg], 1)}")
    print(f"  status/vendor_err combos: {sorted({(t['status'], t['vendor_err']) for t in cp + cg})}")

    # wait end on the absolute clock: PROBE send ~ t_post_mono + cqe_ns (rain CLOCK_MONOTONIC; the
    # post->inject and CQE->send gaps are microseconds); end = send + probe_ms
    for t in cp + cg:
        t["send_ms"] = (t["t_post_mono_ns"] + t["cqe_ns"]) / 1e6
        t["end_mod32"] = (t["send_ms"] + t["probe_ms"]) % 32
    gph = median(t["end_mod32"] for t in nas)
    print(f"  no_answer wait ends on the absolute clock: end mod 32 ms, median {gph:.3f};"
          f" {sorted(round(t['end_mod32'], 3) for t in nas)}")
    for t in cp + cg:
        t["grid_wait"] = 1000 + ((gph - 1000 - t["send_ms"]) % 32)
    off = [(t["tag"], round(t["probe_ms"] - t["grid_wait"], 3)) for t in nas if abs(t["probe_ms"] - t["grid_wait"]) > 0.1]
    print(f"  no_answer trials off the grid (> 0.1 ms): {off};"
          f" on grid |dev| max {max(abs(t['probe_ms'] - t['grid_wait']) for t in nas if abs(t['probe_ms'] - t['grid_wait']) <= 0.1):.3f}")
    ans_s = [t for t in cp + cg if t["sub_cause"] == "server_qp_err"]
    marg = [(t["grid_wait"] - t["probe_ms"], t["tag"]) for t in ans_s]
    print(f"  answered trials: grid wait end - answer min {min(marg)[0]:.3f} ({min(marg)[1]}),"
          f" answered with grid wait end before answer: {[x[1] for x in marg if x[0] <= 0]}")
    print(f"  CP1008/CP1024 answered: grid wait end - answer "
          f"{rng([t['grid_wait'] - t['probe_ms'] for t in ans_s if t['cell'] in ('CP1008', 'CP1024')])}")

    print("\n== 4. CG values (x = stall_meas_ms - cqe_ns/1e6, frozen); d = stall_begin - GOACK (server clock)")
    med_lat = median(lat)
    for t in sorted(cg, key=lambda t: t["x_rule"]):
        x_adj = t["x_rule"] + t["d_goack_stop"]
        x_srv = (t["stall_end_ns"] - t["goack_srv_ns"]) / 1e6 - t["cqe_ns"] / 1e6 - med_lat
        print(f"   {t['tag']:14s} {t['sub_cause']:13s} cqe={t['cqe_ns'] / 1e6:8.1f} stall={t['stall_meas_ms']:8.3f}"
              f" x={t['x_rule']:8.3f} d={t['d_goack_stop']:7.3f} probe_ms={t['probe_ms']:8.3f}"
              f" probe-x={t['probe_ms'] - t['x_rule']:7.3f} probe-(x+d)={t['probe_ms'] - x_adj:7.3f}"
              f" stop_left_at_PROBE_arrival(est)={x_srv:8.3f}")
    print(f"  d over CG: {rng([t['d_goack_stop'] for t in cg])};"
          f" without lb_cg4600_t6: {rng([t['d_goack_stop'] for t in cg if t['tag'] != 'lb_cg4600_t6'])}")
    a = [t for t in cg if t["sub_cause"] == "server_qp_err"]
    print(f"  answered CG: probe-x {rng([t['probe_ms'] - t['x_rule'] for t in a])};"
          f" probe-(x+d) {rng([t['probe_ms'] - t['x_rule'] - t['d_goack_stop'] for t in a])}")

    print("\n== 5. GIN values")
    for c in ("G2900", "G2985", "G2992", "G2995", "G2998", "G3010", "G3100"):
        ts = by_cell[c]
        rec = [t for t in ts if t.get("rec_outcome") == "recovered"]
        dec = [t for t in ts if t.get("rec_outcome") == "declined"]
        print(f"  {c}: n={len(ts)} recovered={len(rec)} declined={len(dec)}"
              f" reasons={sorted({t.get('rec_reason') for t in dec})} r0rc={sorted(t['r0rc'] for t in ts)}")
        print(f"     ack-prep-stall {rng([t['rec_t_ack'] - t['rec_t_prep'] - t['r1_stall_ms'] for t in rec])};"
              f" ack-prep {rng([t['rec_t_ack'] - t['rec_t_prep'] for t in rec])};"
              f" ack - r1 stall end(r0 clock) {rng([t['rec_t_ack'] - t['r1_stall_end_r0clock'] for t in rec])}")
        print(f"     prep - query {rng([t['rec_t_prep'] - t['fault_t_query'] for t in rec])};"
              f" r1 stall - set {rng([t['r1_stall_ms'] - t['set_ms'] for t in ts])};"
              f" r1 stall begin - fault query {rng([t['r1_stall_begin_r0clock'] - t['fault_t_query'] for t in ts])}")
        for t in sorted(dec, key=lambda t: t["rec_t_decl"] - t["fault_t_query"]):
            print(f"       {t['tag']:10s} decl-query={t['rec_t_decl'] - t['fault_t_query']:9.3f}"
                  f" r1_end-query={t['r1_stall_end_r0clock'] - t['fault_t_query']:9.3f}"
                  f" decl-r1_end={t['rec_t_decl'] - t['r1_stall_end_r0clock']:7.3f}"
                  f" r1_req_seen-query={t.get('r1_t_req_r0clock', float('nan')) - t['fault_t_query']:9.3f}"
                  f" rxrec_after={t['r1_n_rxrec_after_stall']} r0rc={t['r0rc']}")
    rec = [t for t in g if t.get("rec_outcome") == "recovered"]
    print(f"  pooled recovered: ack-prep-stall {rng([t['rec_t_ack'] - t['rec_t_prep'] - t['r1_stall_ms'] for t in rec])};"
          f" ack - r1 stall end {rng([t['rec_t_ack'] - t['r1_stall_end_r0clock'] for t in rec])};"
          f" prep - query {rng([t['rec_t_prep'] - t['fault_t_query'] for t in rec])}")
    print(f"  recovered: r0 ack - r1 commit end (r0 clock) {rng([t['rec_t_ack'] - t['r1_t_commit_r0clock'] for t in rec])}")
    d98 = [t for t in g if t["cell"] == "G2998" and t.get("rec_outcome") == "declined"]
    print(f"  G2998 declined: r1 commit end - decline {rng([t['r1_t_commit_r0clock'] - t['rec_t_decl'] for t in d98 if 'r1_t_commit_r0clock' in t])}")
    print(f"  r1 stall - set over G: {rng([t['r1_stall_ms'] - t['set_ms'] for t in g])}")
    dec = [t for t in g if t.get("rec_outcome") == "declined"]
    v = [t["rec_t_decl"] - t["fault_t_query"] for t in dec]
    print(f"  pooled declines: decl-query {rng(v)}; early end (<2999.9) {sum(1 for x in v if x <= 2999.9)},"
          f" between (2999.9,3001.7) {sum(1 for x in v if 2999.9 < x < 3001.7)}, late end (>=3001.7) {sum(1 for x in v if x >= 3001.7)}")
    print(f"  kret->query over G: {rng([t['fault_t_query'] - t['fault_t_kret'] for t in g])}")
    print(f"  clock_rtt_ms over G: {rng([t['clock_rtt_ms'] for t in g])}")

    print("\n== 6. safety records")
    print("  CP/CG pstate (stall trials):", sorted({(t["pstate"] or "missing").split(" at ")[0] for t in cp + cg if t["set_ms"] > 0}),
          "count", sum(1 for t in cp + cg if t["set_ms"] > 0))
    print("  CPU verify_ok values:", sorted({t["verify_ok"] for t in cp + cg}))
    print("  GIN left values:", sorted({t["left"] for t in g}), " r1 data_check:", sorted({t["r1_data_check"] for t in g}))
    for f in ("runner_CPU.log", "runner_GIN.log"):
        txt = open(os.path.join(RES, f)).read()
        print(f"  {f}: STOP/SIGCONT/extra lines:",
              [l for l in txt.split("\n") if re.search(r"STOP|SIGCONT|extra trial|left after", l)] or "none")
    print("  STOP file present:", os.path.exists(os.path.join(RES, "STOP")))


if __name__ == "__main__":
    main()
