#!/usr/bin/env python3
"""summ_feas.py <resultsdir> - verdicts of gin-restore's feasibility tests from their raw files (EXPERIMENT.md 9.15).

Applies the criteria fixed in 9.15.2 (B2), 9.15.3 (B3) and 9.15.4 (B1) before the runs; prints one table per test and
writes <resultsdir>/SUMMARY.txt. Reads only the kv, log, strace-count, meta and timing (tsv) files of run_b3.sh and
run_spike.sh. Never scored: these are DRAFT-stage feasibility checks.
B3 since the user's decision of 2026-10-11 (EXPERIMENT.md 9.15.3): a node and ordering is pooled over the latest runs of x,
s and m (the in-process contention cell, b3m_run<k>/) instead of x, s and h; the old contention cells h (hog process) are
listed apart with their counts and are not pooled; the diagnostic folders b3_diag*/ never enter a verdict or the all-run
total (their readings and the per-node gate for the m cells, fixed before the run, are printed).
"""
import csv
import glob
import os
import re
import sys

R = sys.argv[1] if len(sys.argv) > 1 else "."
OUT = []


def say(s=""):
    print(s)
    OUT.append(s)


def kv(path):
    d = {}
    if not os.path.exists(path):
        return d
    for line in open(path, errors="replace"):
        for m in re.finditer(r"(\w+)=(\"[^\"]*\"|\S+)", line):
            d[m.group(1)] = m.group(2).strip('"')
    return d


def warn_lines(path, prefix="GIN/RS: "):
    out = []
    if not os.path.exists(path):
        return out
    for line in open(path, errors="replace"):
        i = line.find("NCCL WARN " + prefix)
        if i >= 0:
            out.append(line[i + len("NCCL WARN "):].rstrip("\n"))
    return out


def dump_lines(path):
    """ncclDevCommDump output (stdout): from '**** Dev Comm Dump' to its last line (' GIN World Barrier signal0'), log
    lines of other threads that land in between are skipped; pointers and this process's own lkeys masked (they differ
    between processes by nature)."""
    out, on = [], False
    if not os.path.exists(path):
        return out
    for line in open(path, errors="replace"):
        line = line.rstrip("\n")
        if line.startswith("**** Dev Comm Dump"):
            on = True
            out.append("**** Dev Comm Dump PTR ****")
            continue
        if not on or "NCCL " in line or line.startswith("[") or not line.strip():
            continue  # other threads' log lines and the empty lines around them (re-review Q3)
        l2 = re.sub(r"0x[0-9a-fA-F]+|\(nil\)", "PTR", line)
        out.append(re.sub(r"lkey [0-9a-fA-F]+", "lkey LKEY", l2))
        if line.startswith(" GIN World Barrier signal0"):
            on = False
    return out


def num(d, k, default=-1):
    try:
        return float(d.get(k, default))
    except ValueError:
        return default


# ---------------------------------------------------------------- B3
def b3_runlabel(d):
    """one run of a cell, for the earlier-runs list: an error exit has no verdict (its kv's result=FAIL is the exit, not a
    fence failure); otherwise the result with its fence and control counts"""
    for k in ("setup_error", "nic_error", "cuda_error"):
        if k in d:
            return "error %s=\"%s\" (no verdict)" % (k, d[k])
    if d.get("watchdog") == "1":
        return "error watchdog=1 (no verdict)"
    return "%s (fence bad %d/%d, early stale %s, boundary stale-last %s, iterations %s)" % (
        d.get("result", "none"), int(num(d, "fence_W_iters_bad", 0)) + int(num(d, "fence_AW_iters_bad", 0)),
        int(num(d, "fence_W_n", 0)) + int(num(d, "fence_AW_n", 0)), d.get("early_iters_stale", "?"),
        d.get("boundary_iters_stale_last", "?"), d.get("iterations_done", "?"))


def b3(gates=None):
    gates = gates or {}
    def bynum(prefix):
        return sorted(glob.glob(os.path.join(R, prefix + "*")),
                      key=lambda d: int(re.sub(r"\D", "", os.path.basename(d)[len(prefix):]) or 0))
    dirs = [os.path.join(R, "b3")] + bynum("b3_rerun") + bynum("b3m_run")
    latest, history = {}, {}
    for d in dirs:
        for f in sorted(glob.glob(os.path.join(d, "*_resp.kv"))):
            cell = os.path.basename(f)[:-len("_resp.kv")]
            if cell in latest:
                history.setdefault(cell, []).append("%s: %s" % (os.path.basename(os.path.dirname(latest[cell])),
                                                                 b3_runlabel(kv(latest[cell]))))
            latest[cell] = f
    files = [latest[c] for c in sorted(latest)]
    if not files:
        return
    say("== B3 (9.15.3): per cell (the latest run; earlier runs of a cell are listed after the table)")
    say("cell | result | valid | fence W/AW bad of n | early stale | boundary stale-last | edge | nofence bad | fsame bad | "
        "cuflush bad | WA bad | probe stale | query p50/p99/max us | gdr_order | flush_opt | ro_cap")
    cells = {}
    for f in files:
        cell = os.path.basename(f)[:-len("_resp.kv")]
        d = kv(f)
        meta = kv(os.path.join(os.path.dirname(f), cell + "_meta.txt"))
        fw = int(num(d, "fence_W_iters_bad", 0)) + int(num(d, "fence_AW_iters_bad", 0))
        fn = int(num(d, "fence_W_n", 0)) + int(num(d, "fence_AW_n", 0))
        cells[cell] = d
        say("%s | %s | %s | %d/%d | %s | %s | %s | %s/%s | %s/%s | %s | %s | %s | %s/%s/%s | %s | %s | %s" % (
            cell, d.get("result", "NONE(rc=%s %s)" % (meta.get("rc_resp"), d.get("setup_error", d.get("nic_error", "")))),
            d.get("valid", "?"), fw, fn, d.get("early_iters_stale", "?"), d.get("boundary_iters_stale_last", "?"),
            d.get("edge_fraction", "?"), d.get("nofence_W_iters_bad", "?"), d.get("nofence_AW_iters_bad", "?"),
            d.get("fsame_W_iters_bad", "?"), d.get("fsame_AW_iters_bad", "?"), d.get("cuflush_W_iters_bad", "?"),
            d.get("fence_WA_iters_bad", "?"), d.get("probe_W_iters_stale_before", "?"), d.get("query_p50_us", "?"),
            d.get("query_p99_us", "?"), d.get("query_max_us", "?"), d.get("gdr_writes_ordering", "?"),
            d.get("gdr_flush_options", "?"), d.get("hca_ro_write_cap", "?")))
    for c in sorted(history):
        say("earlier runs of %s: %s" % (c, "; ".join(history[c])))
    allbad = alln = 0
    notally = []
    for d in dirs:
        for f in sorted(glob.glob(os.path.join(d, "*_resp.kv"))):
            x = kv(f)
            if "fence_W_n" not in x:
                notally.append("%s/%s" % (os.path.basename(d), os.path.basename(f)[:-len("_resp.kv")]))
                continue
            allbad += int(num(x, "fence_W_iters_bad", 0)) + int(num(x, "fence_AW_iters_bad", 0))
            alln += int(num(x, "fence_W_n", 0)) + int(num(x, "fence_AW_n", 0))
    say("every run of every main cell (b3, b3_rerun<k>, b3m_run<k>; smoke and diagnostic excluded; valid or not): bad scored "
        "fence iterations %d of %d; "
        "runs without tallies (error exits): %s" % (allbad, alln, ", ".join(notally) or "none"))
    say("cell | run folder | build | last_kb | query budget (stop) | iterations done | selfcheck attempts fence/same (read) | hog "
        "| d2d engine | early copies late/prompt of n | in-process hog GB/s")
    for c in sorted(latest):
        f = latest[c]
        d = kv(f)
        meta = kv(os.path.join(os.path.dirname(f), c + "_meta.txt"))
        hog = kv(os.path.join(os.path.dirname(f), c + "_hog.kv"))
        say("%s | %s | %s | %s | %s (%s) | %s | %s/%s (%s/%s) | %s | %s | %s/%s of %s | %s" % (
            c, os.path.basename(os.path.dirname(f)), os.path.basename(os.path.dirname(meta.get("bin", "?/?"))),
            meta.get("last_kb", "?"), meta.get("query_budget", "0"), d.get("budget_stop", "-"),
            d.get("iterations_done", d.get("progress_iterations_done", "-")),
            d.get("selfcheck_fence_attempts", "-"), d.get("selfcheck_same_attempts", "-"),
            d.get("selfcheck_fence_read", "-"), d.get("selfcheck_same_read", "-"),
            ("%s %s" % (hog.get("result"), hog.get("stopped_by"))) if hog else meta.get("hog", "-"),
            d.get("d2d_engine", "-"), d.get("early_copy_late", "-"), d.get("early_copy_prompt", "-"), d.get("early_copy_n", "-"),
            d.get("hog_gbps", "-")))
        if num(d, "selfcheck_fence_attempts", 1) > 1 or num(d, "selfcheck_same_attempts", 1) > 1:
            say("  NOTE %s: the setup self-check needed more than one READ (record it and raise it before further cells)" % c)
    say()
    say("old contention cells (hog process; replaced in the pooling by b3_m on 2026-10-11, user decision; not pooled; the "
        "old results neither rescue nor sink the new verdict): " + "; ".join(
            "%s latest %s (fence bad %d/%d, early stale %s, boundary stale-last %s)" % (
                c, cells[c].get("result", "none"),
                int(num(cells[c], "fence_W_iters_bad", 0)) + int(num(cells[c], "fence_AW_iters_bad", 0)),
                int(num(cells[c], "fence_W_n", 0)) + int(num(cells[c], "fence_AW_n", 0)), cells[c].get("early_iters_stale", "?"),
                cells[c].get("boundary_iters_stale_last", "?")) for c in sorted(cells) if c.startswith("b3_h_")))
    say()
    say("== B3: per responder node and ordering (every cell x, s, m valid and passing; pooled fence n)")
    verdict = {}
    for node in ("rain", "sunny"):
        for o in ("ro", "so"):
            names = ["b3_%s_%s_%s" % (m, node, o) for m in "xsm"]
            ds = [cells.get(n) for n in names]
            if any(x is None for x in ds):
                verdict[(node, o)] = "missing"
            elif any(x.get("result") == "FENCE_FAIL" for x in ds):
                verdict[(node, o)] = "fail"
            elif all(x.get("result") == "PASS" for x in ds):
                verdict[(node, o)] = "pass"
            else:
                verdict[(node, o)] = "open"
            n = sum(int(num(x, "fence_W_n", 0)) + int(num(x, "fence_AW_n", 0)) for x in ds if x)
            say("%s %s: %s (scored fence iterations %d%s)" % (
                node, o, verdict[(node, o)], n,
                ("; 95%% upper bound of the failure rate: %.4f%%" % (300.0 / n)) if n and verdict[(node, o)] == "pass"
                else "; no bound: a cell is not valid and passing" if verdict[(node, o)] != "fail" else ""))
    v = verdict
    nodes = ("rain", "sunny")
    gated = [n for n in nodes if gates.get(n) is False and any("b3_m_%s_%s" % (n, o) not in cells for o in ("ro", "so"))]
    if gated:
        concl = "B3 open: the diagnostic gate of %s did not pass, so its b3_m cells were not run; report to the user " \
                "(EXPERIMENT.md 9.15.3)" % ", ".join(gated)
    elif any(v[(n, o)] in ("missing", "open") for n in nodes for o in ("ro", "so")):
        concl = "B3 open (missing or inconclusive cells: repeat those cells; if still open, ask the user)"
    elif all(v[(n, "ro")] == "pass" and v[(n, "so")] == "pass" for n in nodes):
        concl = "B3: READ-fence drain check holds on this platform as configured for ro and so (strict condition: user decision)"
    elif all(v[(n, "ro")] == "fail" and v[(n, "so")] == "pass" for n in nodes):
        concl = "B3 resolved by the arming condition 'windows registered strict' (ro fails, so passes)"
    elif any(v[(n, "ro")] == "pass" and v[(n, "so")] == "fail" for n in nodes) or \
            len(set((v[(n, "ro")], v[(n, "so")]) for n in nodes)) > 1:
        concl = "B3 open: unstable or node-dependent result"
    else:
        concl = "B3 open: strict also fails (look at the cuflush path)"
    say("B3 conclusion: " + concl)
    say()


def b3_diag(emit):
    """the B3 diagnostic (2026-10-11, EXPERIMENT.md 9.15.3): never a verdict; readings and gate fixed before the run.
    Per snapshot (timing tsv): the copy's end lies in [end_lo, end_hi] and its start in [end_lo - exec, end_hi - exec], all
    relative to PAUSED. "late": start_lo > the run's reach p50 (the copy began after the writes had reached M); "prompt":
    end_hi < the run's reach p50. The deciding run of a node is its latest diagnostic folder in which dn, dp and dm all ended
    without an error exit (EXPERIMENT.md 9.15.3). Returns {node: True (gate passed) | False (not passed)} for the nodes that
    have a deciding run."""
    def pctl(v, p):
        if not v:
            return None
        v = sorted(v)
        return v[int(p * (len(v) - 1) + 0.5)]

    def f1(x):
        return "-" if x is None else "%.1f" % x

    def errlabel(k):
        for key in ("setup_error", "nic_error", "cuda_error"):
            if key in k:
                return "error %s=\"%s\"" % (key, k[key])
        if k.get("watchdog") == "1":
            return "error watchdog=1"
        return None

    def bynum(prefix):
        return sorted(glob.glob(os.path.join(R, prefix + "*")),
                      key=lambda d: int(re.sub(r"\D", "", os.path.basename(d)[len(prefix):]) or 0))
    folders = [d for d in bynum("b3_diag") if os.path.isdir(d)]
    cols = ["iter", "path", "tail", "t_paused_us", "enq_us", "end_lo_us", "end_hi_us", "exec_us", "ref_us", "reach_us",
            "stale_before_words", "stale_last_words", "corrupt_words"]
    runs_by_node = {"rain": [], "sunny": []}
    for d in folders:
        nodes_here = [n for n in ("rain", "sunny") if any(os.path.exists(os.path.join(d, "b3_%s_%s_ro_meta.txt" % (h, n)))
                                                          for h in ("dn", "dp", "dm"))]
        if not nodes_here:
            continue
        emit("== B3 diagnostic (no verdict) folder %s" % os.path.basename(d))
        emit("cell | hog (meta) | d2d engine (copy us) | result | iterations | reach p50 us | early stale n/N | early late/prompt "
             "of N | early copy start_lo p50/p90 us | early start_lo p50 stale/not stale us | boundary stale-last n/N (with a "
             "snapshot) | boundary copy start_hi after rmsn=M-1 p50/p90 us | copy exec p50 us | hog GB/s | notes")
        for node in nodes_here:
            st, errs = {}, []
            for hm in ("dn", "dp", "dm"):
                cell = "b3_%s_%s_ro" % (hm, node)
                k = kv(os.path.join(d, cell + "_resp.kv"))
                meta = kv(os.path.join(d, cell + "_meta.txt"))
                if not meta and not k:
                    errs.append("%s missing" % hm)
                    emit("%s | missing" % cell)
                    continue
                notes = []
                el = errlabel(k) if k else "error (no responder kv)"
                if el:
                    errs.append("%s %s" % (hm, el))
                rows, bad = [], 0
                tf = os.path.join(d, cell + "_resp_timing.tsv")
                if os.path.exists(tf):
                    with open(tf) as fh:
                        for r in csv.DictReader(fh, delimiter="\t"):
                            try:
                                [float(r[c]) for c in cols if c not in ("path", "tail")]
                                rows.append(r)
                            except (TypeError, ValueError, KeyError):
                                bad += 1
                if bad:
                    notes.append("%d incomplete tsv rows skipped" % bad)
                if not rows and not el:
                    notes.append("no timing rows")
                F = lambda r, c: float(r[c])
                ea = [r for r in rows if r["path"] == "early"]
                bd = [r for r in rows if r["path"] == "boundary"]
                reach = num(k, "reach_p50_us", -1)
                slo = lambda r: F(r, "end_lo_us") - F(r, "exec_us")
                stale = lambda r: F(r, "stale_before_words") + F(r, "stale_last_words") > 0
                e_lo = [slo(r) for r in ea]
                e_late = sum(1 for r in ea if reach > 0 and slo(r) > reach)
                e_prompt = sum(1 for r in ea if reach > 0 and F(r, "end_hi_us") < reach)
                e_stale = sum(1 for r in ea if stale(r))
                b_stale = sum(1 for r in bd if F(r, "stale_last_words") > 0)
                # the kv carries the same counts (same definitions): cross-check
                for name, a_, b_ in (("early n", len(ea), k.get("early_W_n")), ("early stale", e_stale, k.get("early_iters_stale")),
                                     ("boundary n", len(bd), k.get("boundary_W_n")),
                                     ("boundary stale-last", b_stale, k.get("boundary_iters_stale_last"))):
                    if rows and b_ is not None and str(a_) != b_:
                        notes.append("%s tsv %s vs kv %s" % (name, a_, b_))
                b_aft = [F(r, "end_hi_us") - F(r, "exec_us") - F(r, "ref_us") for r in bd]
                ex = [F(r, "exec_us") for r in rows]
                if hm == "dp":
                    h = kv(os.path.join(d, cell + "_hog.kv"))
                    gbps = (num(h, "rounds", 0) * num(h, "bytes_per_round", 0) / num(h, "run_s", 1) / 1e9) if h else None
                elif hm == "dm":
                    gbps = num(k, "hog_gbps", -1)
                    gbps = None if gbps < 0 else gbps
                else:
                    gbps = None
                eng, ecu = k.get("d2d_engine"), num(k, "d2d_engine_copy_us", -1)
                if eng is not None and ecu >= 0 and ((eng == "ce" and ecu >= 1000) or (eng == "sm" and ecu < 1000)):
                    notes.append("engine %s contradicts its copy time %.1f us (report)" % (eng, ecu))
                st[hm] = dict(reach=reach, e_n=len(ea), e_late=e_late, e_prompt=e_prompt, e_stale=e_stale, b_n=len(bd),
                              b_stale=b_stale, eng=eng, ecu=ecu,
                              hi_p90=pctl([F(r, "end_hi_us") - F(r, "exec_us") for r in ea], 0.9),
                              endhi_p90=pctl([F(r, "end_hi_us") for r in ea], 0.9),
                              exec_p90=pctl([F(r, "exec_us") for r in ea], 0.9), rows=len(rows))
                emit("%s | %s | %s (%s) | %s | %s | %s | %d/%d | %d/%d of %d | %s/%s | %s/%s | %d/%d | %s/%s | %s | %s | %s" % (
                    cell, meta.get("hog", "?"), eng or "?", f1(ecu if ecu >= 0 else None), el or k.get("result", "none"),
                    k.get("iterations_done", k.get("progress_iterations_done", "-")), f1(reach if reach > 0 else None),
                    e_stale, len(ea), e_late, e_prompt, len(ea), f1(pctl(e_lo, 0.5)), f1(pctl(e_lo, 0.9)),
                    f1(pctl([slo(r) for r in ea if stale(r)], 0.5)), f1(pctl([slo(r) for r in ea if not stale(r)], 0.5)),
                    b_stale, len(bd), f1(pctl(b_aft, 0.5)), f1(pctl(b_aft, 0.9)), f1(pctl(ex, 0.5)), f1(gbps),
                    "; ".join(notes) or "-"))
            runs_by_node[node].append((os.path.basename(d), st, errs))
        emit()
    gates = {}
    for node in ("rain", "sunny"):
        runs = runs_by_node[node]
        if not runs:
            continue
        ok = [x for x in runs if not x[2] and all(h in x[1] and x[1][h]["rows"] > 0 for h in ("dn", "dp", "dm"))]
        if not ok:
            emit("%s: no diagnostic run without an error exit (%s): no reading, gate NOT passed (report)" % (
                node, "; ".join("%s: %s" % (x[0], ", ".join(x[2]) or "timing rows missing") for x in runs)))
            gates[node] = False
            continue
        folder, st, _ = ok[-1]
        n_, p_, m_ = st["dn"], st["dp"], st["dm"]
        emit("%s: deciding diagnostic run %s (the latest of %d without an error exit)" % (node, folder, len(ok)))
        # reading 1 (fixed before the run; decides nothing): the time-slicing inference
        if not n_["e_n"] or not p_["e_n"] or n_["reach"] <= 0 or p_["reach"] <= 0:
            inf = "missing data"
        elif 2 * p_["e_prompt"] >= p_["e_n"]:
            inf = "refuted (with the hog process at least half of the early copies ended before the writes reached M)"
        elif 10 * p_["e_late"] >= 9 * p_["e_n"] and 10 * n_["e_prompt"] >= 9 * n_["e_n"]:
            inf = "confirmed (hog process: >= 90% of the early copies began after the writes reached M; no hog: >= 90% ended " \
                  "before)"
        else:
            inf = "unclear"
        emit("%s: reading 1, time-slicing inference: %s (dp late %d of %d, dn prompt %d of %d)" % (
            node, inf, p_["e_late"], p_["e_n"], n_["e_prompt"], n_["e_n"]))
        # reading 2 (fixed before the run; decides nothing): the in-process copy is prompt
        if m_["hi_p90"] is None or m_["reach"] <= 0:
            emit("%s: reading 2, in-process copy prompt: missing data" % node)
        else:
            emit("%s: reading 2, in-process copy prompt: %s (early start_hi p90 %.1f us vs 1/4 of reach p50 %.1f us; "
                 "information: early end_hi p90 %s us, exec p90 %s us)" % (
                     node, "yes" if m_["hi_p90"] < 0.25 * m_["reach"] else "no", m_["hi_p90"], 0.25 * m_["reach"],
                     f1(m_["endhi_p90"]), f1(m_["exec_p90"])))
        # the engine: dn decides, dm should agree, dp is information (time slicing can disturb its check)
        emit("%s: d2d engine: dn %s, dm %s%s; dp %s (information)" % (
            node, n_["eng"], m_["eng"], "" if n_["eng"] == m_["eng"] else " (DISAGREE: report)", p_["eng"]))
        # the gate (fixed before the run; the only thing that decides here): run that node's b3_m cells or not
        why = []
        if not (m_["e_stale"] >= 10 and 2 * m_["e_stale"] >= m_["e_n"]):
            why.append("dm early stale %d of %d" % (m_["e_stale"], m_["e_n"]))
        if not (m_["b_stale"] >= 10 and 2 * m_["b_stale"] >= m_["b_n"]):
            why.append("dm boundary stale-last %d of %d (with a snapshot)" % (m_["b_stale"], m_["b_n"]))
        rises, item3 = "-", ""
        if min(n_["reach"], p_["reach"], m_["reach"]) <= 0:
            why.append("a reach p50 is missing")
        else:
            rm, rp = m_["reach"] - n_["reach"], p_["reach"] - n_["reach"]
            rises = "dm %.1f us, dp %.1f us" % (rm, rp)
            if node == "sunny":
                # user decision 2026-10-11 (EXPERIMENT.md 9.15.3 and 12; sunny only, gate item 3 only): neither hog delayed the
                # NIC-side arrival on sunny (both rises negative), so "half of the dp rise" carries no meaning there
                item3 = "; gate item 3 not applicable (user decision 2026-10-11)"
                if rp > 0 or rm > 0:
                    item3 += "; NOTE: a rise is positive in this run, unlike the run the decision was made on (report)"
            elif rm < 0.5 * rp:
                why.append("dm reach rise %.1f us < half the dp rise %.1f us" % (rm, rp))
        emit("%s: reach p50 rise over dn: %s%s" % (node, rises, item3))
        gates[node] = not why
        emit("%s: gate for b3_m_%s_ro and b3_m_%s_so: %s" % (
            node, node, node, ("passed (run them)" + ("; gate item 3 not applicable (user decision 2026-10-11)" if item3 else ""))
            if not why else "NOT passed (do not run them; report): " + "; ".join(why)))
    if gates:
        emit()
    return gates


# ---------------------------------------------------------------- B2
def runs(base):
    """the folders of one test: <base>, then <base>_run2, _run3, ... (repeats never mix into one folder)"""
    ds = [os.path.join(R, base)] + sorted(glob.glob(os.path.join(R, base + "_run*")),
                                          key=lambda d: int(re.sub(r"\D", "", os.path.basename(d)[len(base):]) or 0))
    return [d for d in ds if os.path.isdir(d)]


def b2():
    for d in runs("b2"):
        b2_dir(d)


def b2_dir(DIR):
    files = sorted(glob.glob(os.path.join(DIR, "b2_*_meta.txt")))
    if not files:
        return
    say("== B2 (9.15.2) folder %s" % os.path.basename(DIR))
    trials = {}
    for mf in files:
        stem = os.path.basename(mf)[:-len("_meta.txt")]
        rows, okA = [], True
        for r in range(4):
            d = kv(os.path.join(DIR, "%s_rank_r%d.kv" % (stem, r)))
            comm = [l for l in warn_lines(os.path.join(DIR, "%s_rank_r%d.log" % (stem, r))) if l.startswith("GIN/RS: comm ")]
            c = kv_from_line(comm[0]) if comm else {}
            rows.append((r, d.get("dc_lsa_size"), d.get("dc_lsa_rank"), c.get("nLsaTeams"), c.get("nvlsSupport"),
                         c.get("runtimeConn"), c.get("numRmaCtx"), d.get("xchg"), d.get("exit")))
            okA &= (d.get("dc_lsa_size") == "1" and c.get("nLsaTeams") == "4" and c.get("nvlsSupport") == "0" and
                    c.get("runtimeConn") == "1" and d.get("xchg") == "ok")
        say("%s: %s" % (stem, " ; ".join("r%d lsaSize=%s lsaRank=%s nLsaTeams=%s nvls=%s runtimeConn=%s rma=%s xchg=%s exit=%s" % x
                                          for x in rows)))
        anyB = any(x[1] not in (None, "1") and str(x[1]).isdigit() and int(x[1]) >= 2 for x in rows)
        cls = "A" if okA else "B" if anyB else "open"
        trials.setdefault(stem.rsplit("_t", 1)[0], []).append(cls)
        say("  -> trial class %s" % cls)
    for cellname, cl in sorted(trials.items()):
        if cellname == "b2_inter":
            res = ("resolution A (both trials)" if cl.count("A") >= 2 and len(cl) == cl.count("A") else
                   "resolution B (an LSA team of 2 or more)" if "B" in cl else "open")
            say("B2 conclusion (%s, %d trials): %s" % (cellname, len(cl), res))
        else:
            say("%s (control): %s" % (cellname, ", ".join(cl)))
    say()


def kv_from_line(line):
    return {m.group(1): m.group(2) for m in re.finditer(r"(\w+)=(\S+)", line)}


# ---------------------------------------------------------------- B1
def b1_compare(rec_kv, rec_log, rep_kv, rep_log, strace_file, rep_rc, strace_avail, self_max=None):
    """the five pass items of 9.15.4 for one replay against its recorded rank; returns (pass, failures, notes).
    strace_avail: the node's strace mode from the meta (0: no strace, item 3 unverified). self_max: the live cell's bound on
    connects to this node's own addresses (the sequential replays' count; a connect to the live rank on the same node
    would show there)."""
    fails, notes = [], []
    a, b = kv(rec_kv), kv(rep_kv)
    # 1. finished, abort in time, own exit
    for k in ("init_rc", "reg_rc", "devcomm_rc", "abort_rc"):
        if b.get(k) != "0":  # numeric ncclResult_t
            fails.append("1:%s=%s" % (k, b.get(k)))
    if num(b, "abort_ms", 1e9) >= 10000:
        fails.append("1:abort_ms=%s" % b.get("abort_ms"))
    if b.get("exit") != "0" or rep_rc != "0":
        fails.append("1:exit=%s rc=%s" % (b.get("exit"), rep_rc))
    la, lb = warn_lines(rec_log), warn_lines(rep_log)
    # 2. the transcript consumed exactly
    rm = [l for l in la if l.startswith("GIN/RS: record mark=devcomm")]
    pm = [l for l in lb if l.startswith("GIN/RS: replay mark=devcomm")]
    if not rm or not pm:
        fails.append("2:no devcomm mark")
    else:
        ke = kv_from_line(rm[-1]).get("entry")
        m = re.search(r"entry=(\d+) of (\d+)", pm[-1])
        if not m or m.group(1) != ke:
            fails.append("2:mark entry record=%s replay=%s" % (ke, pm[-1]))
    sm = [kv_from_line(l) for l in lb if l.startswith("GIN/RS: summary")]
    if not sm or sm[-1].get("diverged") != "0" or sm[-1].get("beyond") != "0" or sm[-1].get("strict_mismatch") != "0":
        fails.append("2:summary %s" % (sm[-1] if sm else "missing"))
    # 3. no network contact
    st = kv(strace_file)
    if not st and str(strace_avail) == "0":
        notes.append("3:unverified (no strace on the node)")
    elif not st:
        fails.append("3:strace counts missing")
    elif num(st, "socket", 0) <= 0 or num(st, "lines_matched", 0) <= 0:
        fails.append("3:strace parser saw no socket (positive control) %s" % st)
    elif st.get("inet_connect_peer_total") != "0":
        fails.append("3:connects to a peer %s" % st.get("inet_connect_peer_total"))
    if st and self_max is not None and num(st, "inet_connect_self", 0) > self_max:
        fails.append("3:connects to this node's own addresses %s > %s (sequential replays)" % (st.get("inet_connect_self"),
                                                                                              self_max))
    elif st and num(st, "inet_connect_self", 0) > 0:
        notes.append("3:self connects %s (review)" % st.get("inet_connect_self"))
    # 4. same as the recorded rank
    for k in ("comm_rank", "comm_count", "dc_rank", "dc_nranks", "dc_lsa_rank", "dc_lsa_size", "dc_gin_contexts",
              "dc_gin_signals", "dc_gin_counters", "dc_gin_connections", "win_bytes", "ts_contexts"):
        if a.get(k) != b.get(k):
            fails.append("4:%s %s!=%s" % (k, a.get(k), b.get(k)))
    pick = lambda ls, p: [l for l in ls if l.startswith(p)]
    for p in ("GIN/RS: comm ", "GIN/RS: devcomm ", "GIN/RS: window ", "GIN/RS: rkeys "):
        if pick(la, p) != pick(lb, p):
            fails.append("4:lines '%s' differ" % p.strip())
    # the compared lines must exist (two user windows and the devComm's resource window; rkey lines of windows and
    # tables), and no hash may be the keyless "nokey" (review pass 3, P5, P6)
    if len(pick(lb, "GIN/RS: window size=")) < 3 or not pick(lb, "GIN/RS: rkeys window ") or \
            not pick(lb, "GIN/RS: comm ") or not pick(lb, "GIN/RS: devcomm "):
        fails.append("4:report lines missing (window %d, rkeys window %d)" % (len(pick(lb, "GIN/RS: window size=")),
                                                                            len(pick(lb, "GIN/RS: rkeys window "))))
    if any("nokey" in x for x in la + lb):
        fails.append("4:a hash printed without key (nokey)")
    c = kv_from_line((pick(lb, "GIN/RS: comm ") or [""])[0])
    if c.get("runtimeConn") != "1" or c.get("nvlsSupport") != "0" or c.get("numRmaCtx") != "0":
        fails.append("4:comm conditions %s" % c)
    ta, tb = pick(la, "GIN/RS: ts gates "), pick(lb, "GIN/RS: ts gates ")
    if [re.sub(r" listen=\d", "", x) for x in ta] != [re.sub(r" listen=\d", "", x) for x in tb] or not ta:
        fails.append("4:ts/nonce lines differ")
    if dump_lines(rec_log) != dump_lines(rep_log) or not dump_lines(rep_log):
        fails.append("4:ncclDevCommDump differs (pointers masked)")
    # 5. gates and endpoints of every peer
    strip_fd = lambda ls: [re.sub(r" fd=\d", "", x) for x in ls]
    me = b.get("dc_rank")
    others = lambda ls: [x for x in ls if not x.startswith("GIN/RS: peer %s " % me)]  # this rank's own index: gated=0
    pa, pb = strip_fd(pick(la, "GIN/RS: peer ")), strip_fd(pick(lb, "GIN/RS: peer "))
    if pa != pb or not others(pb) or any("gated=1" not in x for x in others(pb)):
        fails.append("5:peer lines")
    qa, qb = pick(la, "GIN/RS: qp "), pick(lb, "GIN/RS: qp ")
    if qa != qb or not qb or any(("epoch=0" not in x or "count=0" not in x or "gate_read=1" not in x) for x in qb):
        fails.append("5:qp/gate lines")
    co = [kv_from_line(l) for l in lb if l.startswith("GIN/RS: replay connect_once")]
    if not co or co[-1].get("failed") != "0" or co[-1].get("ok") != str(len(qb)):
        fails.append("5:connect_once %s" % (co[-1] if co else "missing"))
    return (len(fails) == 0, fails, notes)


def b1():
    for d in runs("b1"):
        b1_dir(d)


def b1_dir(DIR):
    metas = sorted(glob.glob(os.path.join(DIR, "b1_t*_meta.txt")))
    lives = sorted(glob.glob(os.path.join(DIR, "b1_live_t*_meta.txt")))
    if not metas and not lives:
        return
    say("== B1 (9.15.4) folder %s" % os.path.basename(DIR))
    allpass, negok, unverified, selfmax = True, True, False, None
    for mf in metas:
        stem = os.path.basename(mf)[:-len("_meta.txt")]
        meta = kv(mf)
        P = lambda part, ext: os.path.join(DIR, "%s_%s.%s" % (stem, part, ext))
        rec_ok = all(kv(P("rec_r%d" % r, "kv")).get("xchg") == "ok" and kv(P("rec_r%d" % r, "kv")).get("exit") == "0"
                     for r in (0, 1))
        say("%s: record xchg ok=%s transcript bytes r0=%s r1=%s" % (stem, rec_ok, meta.get("transcript_bytes_r0"),
                                                                    meta.get("transcript_bytes_r1")))
        for r, part in ((1, "rep1"), (0, "rep0")):
            st = kv(os.path.join(DIR, "%s_%s_strace.txt" % (stem, part)))
            say("  %s: strace_mode=%s self_connects=%s init_ms record/replay=%s/%s" % (
                part, st.get("strace_mode"), st.get("inet_connect_self"), kv(P("rec_r%d" % r, "kv")).get("init_ms"),
                kv(P(part, "kv")).get("init_ms")))
            ok, fails, notes = b1_compare(P("rec_r%d" % r, "kv"), P("rec_r%d" % r, "log"), P(part, "kv"), P(part, "log"),
                                          os.path.join(DIR, "%s_%s_strace.txt" % (stem, part)),
                                          meta.get("rc_" + part, "none"), meta.get("strace_" + ("sunny" if r == 1 else "rain")))
            allpass &= ok and rec_ok
            unverified |= any(n.startswith("3:unverified") for n in notes)
            if r == 1 and st:
                selfmax = min(selfmax, num(st, "inet_connect_self", 0)) if selfmax is not None else num(st, "inet_connect_self", 0)
            say("  %s: %s %s %s" % (part, "PASS" if ok else "FAIL", "; ".join(fails), "; ".join(notes)))
        for part in ("neg_cut", "neg_field"):
            d = kv(P(part, "kv"))
            lg = " ".join(warn_lines(P(part, "log")))
            failed = any(d.get(k) not in (None, "0") for k in ("init_rc", "reg_rc", "devcomm_rc")) or d.get("exit") != "0"
            failed_ok = failed and re.search(r"is cut|damaged or cut|diverged at|not usable|after the end", lg)
            negok &= bool(failed_ok)
            say("  %s: %s (init_rc=%s reg_rc=%s devcomm_rc=%s exit=%s)" % (
                part, "replay failed as required" if failed_ok else "DID NOT FAIL", d.get("init_rc"), d.get("reg_rc"),
                d.get("devcomm_rc"), d.get("exit")))
    if metas:
        say("B1 conclusion: %s" % (("init replay works in this scope (2 ranks, cross-node, lsaSize 1, RMA and RAS off)" +
                                   ("; item 3 unverified on a node without strace" if unverified else ""))
                                  if allpass and negok and len(metas) >= 2 else
                                  "B1 stays blocked or open (see the failing items)"))
    for mf in lives:
        stem = os.path.basename(mf)[:-len("_meta.txt")]
        meta = kv(mf)
        P = lambda part, ext: os.path.join(DIR, "%s_%s.%s" % (stem, part, ext))
        ok, fails, notes = b1_compare(P("live_r1", "kv"), P("live_r1", "log"), P("live_rep1", "kv"), P("live_rep1", "log"),
                                      os.path.join(DIR, "%s_live_rep1_strace.txt" % stem),
                                      meta.get("rc_live_rep1", "none"), meta.get("strace_sunny"),
                                      self_max=selfmax if selfmax is not None else 0)
        quiet = all(kv(P("live_r%d" % r, "kv")).get(k) == "0" for r in (0, 1)
                    for k in ("after_hold_rounds", "after_hold_declined", "after_hold_reconnects", "after_hold_deaths"))
        say("%s: replay %s %s %s; live ranks undisturbed=%s" % (stem, "PASS" if ok else "FAIL", "; ".join(fails),
                                                                 "; ".join(notes), quiet))
    say()


GATES = b3_diag(lambda line="": None)  # computed first: the B3 conclusion names a node whose gate did not pass
b3(GATES)
b3_diag(say)
b2()
b1()
with open(os.path.join(R, "SUMMARY.txt"), "w") as f:
    f.write("\n".join(OUT) + "\n")
