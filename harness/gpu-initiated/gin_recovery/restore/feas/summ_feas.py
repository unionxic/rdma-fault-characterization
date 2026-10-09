#!/usr/bin/env python3
"""summ_feas.py <resultsdir> - verdicts of gin-restore's feasibility tests from their raw files (EXPERIMENT.md 9.15).

Applies the criteria fixed in 9.15.2 (B2), 9.15.3 (B3) and 9.15.4 (B1) before the runs; prints one table per test and
writes <resultsdir>/SUMMARY.txt. Reads only the kv, log, strace-count and meta files of run_b3.sh and run_spike.sh. Never
scored: these are DRAFT-stage feasibility checks.
"""
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
        if not on or "NCCL " in line or line.startswith("["):
            continue
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
def b3():
    dirs = [os.path.join(R, "b3")] + sorted(glob.glob(os.path.join(R, "b3_rerun*")),
                                            key=lambda d: int(re.sub(r"\D", "", os.path.basename(d)) or 0))
    latest, history = {}, {}
    for d in dirs:
        for f in sorted(glob.glob(os.path.join(d, "*_resp.kv"))):
            cell = os.path.basename(f)[:-len("_resp.kv")]
            if cell in latest:
                history.setdefault(cell, []).append("%s:%s" % (os.path.basename(os.path.dirname(latest[cell])),
                                                                kv(latest[cell]).get("result", "none")))
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
        say("earlier runs of %s: %s" % (c, ", ".join(history[c])))
    say()
    say("== B3: per responder node and ordering (every cell x, s, h valid and passing; pooled fence n)")
    verdict = {}
    for node in ("rain", "sunny"):
        for o in ("ro", "so"):
            names = ["b3_%s_%s_%s" % (m, node, o) for m in "xsh"]
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
            say("%s %s: %s (scored fence iterations %d; 95%% upper bound of the failure rate if 0 failed: %s)" % (
                node, o, verdict[(node, o)], n, ("%.4f%%" % (300.0 / n)) if n else "-"))
    v = verdict
    nodes = ("rain", "sunny")
    if any(v[(n, o)] in ("missing", "open") for n in nodes for o in ("ro", "so")):
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


b3()
b2()
b1()
with open(os.path.join(R, "SUMMARY.txt"), "w") as f:
    f.write("\n".join(OUT) + "\n")
