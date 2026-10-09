#!/usr/bin/env python3
"""Independent recount of gpu-detect app trials (results/20261009/raw/<id>/) from the raw log lines.
Written without reading the study's rows_gd.py / score.py. Rules follow EXPERIMENT.md 3.1 and blind-apps 3.1 prose.
Usage: app_recount.py <results_dir> <out_csv>
"""
import csv, json, os, re, statistics, sys

R = sys.argv[1]
OUT = sys.argv[2]
RAW = os.path.join(R, "raw")

# ---------------- regexes (own) ----------------
G_FIRE = re.compile(r"GIN/FAULT: GDAKI fault fired \(shot (\d+)/(\d+)\): moved (\d+)/(\d+) GIN QP\(s\) to ERR.*?fire_mono_ms=([\d.]+) done_mono_ms=([\d.]+)")
G_WATCH = re.compile(r"GIN/TS: rank (\d+): QP watch: qpn (\S+) \(rank (\d+), context (\d+)\) is in state (ERR|SQER) with no fault record for ([\d.]+) ms; class (\S+) from (\S+) .*mono_ms=([\d.]+)")
G_WATCH_ANY = re.compile(r"GIN/TS: rank \d+: QP watch: qpn")
G_DEV = re.compile(r"GIN/Q4: device-classified error CQE rank=(\d+) .*mono_ms=([\d.]+)")
G_REC = re.compile(r"GIN/TS: recovered rank=(\d+) peer=(\d+) role=(\w+) round=(\d+) class=(\S+).*t_resumed=([\d.]+)")
G_DECL = re.compile(r"GIN/TS: declined rank=(\d+) peer=(\d+) reason=\"([^\"]*)\"")
G_JUDGED = re.compile(r"GIN/TS: rank (\d+): rank (\d+) judged dead")
G_REL_ERR = re.compile(r"devComm waits.*released.*why=(declined|peer-dead|fw-watchdog)")
G_EXAMPLE_ERR = re.compile(r"Failed, NCCL error|Failed: Cuda error|ERROR:")
G_RECFAIL = re.compile(r"GIN/REC: (commit failed|recovery aborted|prepare declined)")
G_WD = re.compile(r"watchdog.*(surfac|raised)", re.I)
G_RESULT = re.compile(r"GIN Ring Exchange result: (\w+)")
G_MISMATCH = re.compile(r"mismatch at CTA")
G_TS_ON = re.compile(r"GIN/TS: transparent recovery ON rank=(\d+)")
G_TS_OFF = re.compile(r"transparent recovery OFF")
G_DETECT = re.compile(r"GIN/TS: detect=1 rank=(\d+) qpwatch_ms=(\d+)")
G_REMAIN = re.compile(r"GIN/TS: remaining=1 rank=(\d+)")
G_LB = re.compile(r"NIC copy path on: .*?(\d+) QP struct\(s\) equal to the host shadow")
G_POL = re.compile(r"GIN/TS: fault policy rank=(\d+) requested=(\w+) agreed=(\d) effective=(\w+)")
G_WQ = re.compile(r"GIN/TS: rank (\d+) QP watch at teardown: qpwatch_ms=(\d+) queries=(\d+) query_fail=(\d+) query_us_mean=([\d.]+) query_us_max=([\d.]+) detections=(\d+)")
G_ANCHOR = re.compile(r"=== Comparing GIN ring-exchange implementations ===")
G_CQE_RAW = re.compile(r"error CQE", re.I)

N_ENABLED = re.compile(r"\[nvshmem-t1\] PE(\d) [0-9.]+ enabled:")
N_ANCHOR = re.compile(r"^\[nvshmem-t1\] PE0 [0-9.]+ enabled:")
N_TMOFF = re.compile(r"transparent mode off")
N_T1W = re.compile(r"t1w: gpu-detect=1 fin_death=(\d) goodbye=(\d) failstop_ms=(-?\d+) failstop_code=(\d+)")
N_FINV = re.compile(r"t1w: peer (\d+) library socket closed \(FIN\) without a goodbye: the peer process is gone")
N_FINLOG = re.compile(r"PE(\d) [0-9.]+ peer (\d+) library socket closed \(FIN\)$")
N_DECL = re.compile(r"\[nvshmem-t1\] PE(\d) [0-9.]+ DECLINE peer=(\d+) class=(\S+).*reason=\"([^\"]*)\"")
N_MARKED = re.compile(r"marked failed")
N_BYE_SENT = re.compile(r"t1w: goodbye sent to (\d+) peer")
N_BYE_SEEN = re.compile(r"t1w: peer (\d+) said goodbye \(normal teardown\)")
N_LEFT = re.compile(r"t1w: peer (\d+) library socket closed \(FIN\) after its goodbye: it left")
N_FAILSTOP = re.compile(r"t1w: FAILSTOP: exiting with code (\d+) after the decline of peer (\d+)")
N_FS_ARMED = re.compile(r"FAILSTOP armed")
N_RELEASED = re.compile(r"t1w: device waits released: the decline of peer (\d+)")
N_RECOV = re.compile(r"RECOVERED (initiator|responder)")
N_SIZE = re.compile(r"^(\d+)B \t ([\d.]+)ms$")
N_VAL = re.compile(r"PE \d+ error, data\[")
N_FIRE_QP = re.compile(r"\[nvshmem-fault-inject\] moved (\d+) QP\(s\) to ERR")
N_FIRE_RA = re.compile(r"\[nvshmem-fault-inject\] revoked remote access on (\d+) RC QP\(s\)")
N_CUDAERR = re.compile(r"CUDA error|cuda error|cudaError|NVSHMEM ERROR|nvshmem error|illegal memory", re.I)
N_STARTFAIL = re.compile(r"nvshmemi_setup_transport failed|heap registration setup failed")
A_SUP = re.compile(r"AGENT suppressed name=(\w+) count=(\d+)")


def read_log(p):
    out = []
    try:
        with open(p, errors="replace") as f:
            for line in f:
                line = line.rstrip("\n")
                sp = line.split(" ", 1)
                try:
                    t = float(sp[0])
                except ValueError:
                    continue
                out.append((t, sp[1] if len(sp) > 1 else ""))
    except OSError:
        pass
    return out


def first(lines, rx):
    for t, s in lines:
        m = rx.search(s)
        if m:
            return t, m
    return None, None


def allm(lines, rx):
    return [(t, rx.search(s)) for t, s in lines if rx.search(s)]


def gin_err_lines(lines):
    out = []
    for t, s in lines:
        if (G_DECL.search(s) or G_JUDGED.search(s) or G_REL_ERR.search(s) or G_EXAMPLE_ERR.search(s)
                or G_RECFAIL.search(s) or G_WD.search(s)):
            out.append((t, s))
    return out


def nvs_err_lines(lines):
    out = []
    for t, s in lines:
        if N_DECL.search(s) or N_MARKED.search(s) or N_TMOFF.search(s) or N_CUDAERR.search(s):
            out.append((t, s))
    return out


rows = []
for tid in sorted(os.listdir(RAW)):
    d = os.path.join(RAW, tid)
    if not os.path.isdir(d):
        continue
    meta = json.load(open(os.path.join(d, "trial.meta")))
    e = meta["entry"]
    wl, cls, build, cell = e["workload"], e["cls"], e["build"], e["cell"]
    tgt = e.get("target")
    L = {r: read_log(os.path.join(d, "r%d.log" % r)) for r in (0, 1)}
    A = {r: read_log(os.path.join(d, "a%d.log" % r)) for r in (0, 1)}
    ex = meta["exit"]
    rc = {r: ex[str(r)]["rc"] for r in (0, 1)}
    tex = {r: ex[str(r)]["t_exit"] for r in (0, 1)}
    hend = {r: ex[str(r)]["harness_end"] for r in (0, 1)}
    fault = meta.get("fault", {})
    killed = meta.get("killed_rank")
    row = {"id": tid, "cell": cell, "build": build, "key": "%s@%s" % (cell, build), "hold": e["hold"], "wl": wl,
           "cls": cls, "target": tgt, "rc0": rc[0], "rc1": rc[1], "end0": hend[0], "end1": hend[1],
           "wall_s": meta.get("wall_s"), "killed": killed}
    row.update({k: v for k, v in meta.get("params", {}).items()})
    # ---- applied, fault time
    t_fault = None
    if (wl, cls) in (("gin", "qperr"),):
        tf, mf = first(L[tgt], G_FIRE)
        row["applied"] = int(bool(mf) and int(mf.group(3)) >= 1)
        if mf:
            t_fault = tf
            row["hook_moved"] = "%s/%s" % (mf.group(3), mf.group(4))
            row["done_mono_ms"] = float(mf.group(6))
    elif wl == "nvs" and cls in ("qperr", "remacc"):
        tf, mf = first(L[tgt], N_FIRE_QP if cls == "qperr" else N_FIRE_RA)
        row["applied"] = int(bool(mf) and int(mf.group(1)) >= 1)
        if mf:
            t_fault = tf
    elif cls in ("kill", "stop"):
        row["applied"] = int(fault.get("applied") == 1)
        t_fault = fault.get("t_ack")
        row["skipped"] = fault.get("skipped", "")
    else:
        row["applied"] = 1
    row["t_fault"] = t_fault
    surv = [r for r in (0, 1) if not (cls == "kill" and killed == r)]
    # ---- void
    anchor_rx = G_ANCHOR if wl == "gin" else N_ANCHOR
    ta, _ = first(L[0], anchor_rx)
    startfail = any(N_STARTFAIL.search(s) for r in (0, 1) for _, s in L[r]) if wl == "nvs" else False
    row["void"] = int(ta is None or startfail)
    # ---- config
    cfg = True
    why = []
    if wl == "gin":
        want_p = int(e.get("env", {}).get("NCCL_GIN_TS_QPWATCH_MS", "10"))
        for r in (0, 1):
            if not L[r]:
                continue
            s_all = [s for _, s in L[r]]
            if not any(G_TS_ON.search(s) for s in s_all):
                cfg = False; why.append("r%d no TS ON" % r)
            if any(G_TS_OFF.search(s) for s in s_all):
                cfg = False; why.append("r%d TS OFF" % r)
            det = [G_DETECT.search(s) for s in s_all if G_DETECT.search(s)]
            rem = [s for s in s_all if G_REMAIN.search(s)]
            if build == "hk":
                if not det or any(int(m.group(2)) != want_p for m in det):
                    cfg = False; why.append("r%d detect/period" % r)
                lb = [int(G_LB.search(s).group(1)) for s in s_all if G_LB.search(s)]
                if not lb or min(lb) < 1:
                    cfg = False; why.append("r%d lb" % r)
                pol = [G_POL.search(s) for s in s_all if G_POL.search(s)]
                if not pol or any(m.group(2) != "failfast" or m.group(4) != "failfast" for m in pol):
                    cfg = False; why.append("r%d policy" % r)
            elif build == "hr":
                if not rem or det:
                    cfg = False; why.append("r%d hr cfg" % r)
            elif build == "hq":
                if rem or det:
                    cfg = False; why.append("r%d hq cfg" % r)
    else:
        want_fs = int(e.get("env", {}).get("NVSHMEM_IBGDA_FT_T1_FAILSTOP_MS", "0"))
        for r in (0, 1):
            if not L[r]:
                continue
            s_all = [s for _, s in L[r]]
            if not any(N_ENABLED.search(s) for s in s_all):
                cfg = False; why.append("r%d no enabled" % r)
            if any(N_TMOFF.search(s) for s in s_all):
                cfg = False; why.append("r%d tm off" % r)
            t1w = [N_T1W.search(s) for s in s_all if N_T1W.search(s)]
            if build == "t1w":
                if not t1w or any(int(m.group(3)) != want_fs for m in t1w):
                    cfg = False; why.append("r%d t1w cfg" % r)
            else:
                if t1w:
                    cfg = False; why.append("r%d t1w line on t1_380" % r)
    row["config_ok"] = int(cfg)
    row["config_why"] = ";".join(why)
    row["valid"] = int(row["applied"] == 1 and row["void"] == 0 and row["config_ok"] == 1)
    # ---- error lines, result
    errf = gin_err_lines if wl == "gin" else nvs_err_lines
    errs = {r: errf(L[r]) for r in (0, 1)}
    row["n_err0"], row["n_err1"] = len(errs[0]), len(errs[1])
    row["err0"] = errs[0][0][1][:160] if errs[0] else ""
    row["err1"] = errs[1][0][1][:160] if errs[1] else ""
    surv_err = sorted(t for r in surv for t, _ in errs[r])
    row["n_err_surv"] = len(surv_err)
    row["dt_err"] = round(surv_err[0] - t_fault, 6) if surv_err and t_fault is not None else ""
    surv_ex = [tex[r] for r in surv if tex[r] is not None]
    row["dt_end"] = round(max(surv_ex) - t_fault, 6) if surv_ex and t_fault is not None and len(surv_ex) == len(surv) else ""
    row["n_harness_end"] = sum(1 for r in surv if hend[r])
    if wl == "gin":
        tr, mr = first(L[0], G_RESULT)
        mism = sum(1 for r in (0, 1) for _, s in L[r] if G_MISMATCH.search(s))
        mism += sum(int(m.group(2)) for r in (0, 1) for _, m in allm(A[r], A_SUP) if m.group(1) == "mismatch")
        if mism or (mr and mr.group(1) != "PASSED"):
            res = "wrong"
        elif mr and mr.group(1) == "PASSED":
            res = "correct"
        else:
            res = "none"
        row["n_mismatch"] = mism
    else:
        sizes = {int(m.group(1)): float(m.group(2)) for _, m in allm(L[0], N_SIZE)}
        nval = sum(1 for r in (0, 1) for _, s in L[r] if N_VAL.search(s))
        nval += sum(int(m.group(2)) for r in (0, 1) for _, m in allm(A[r], A_SUP) if m.group(1) == "validation")
        row["n_val"] = nval
        row["ms_16m"] = sizes.get(16777216, "")
        row["ms_32m"] = sizes.get(33554432, "")
        row["ms_64m"] = sizes.get(67108864, "")
        if nval:
            res = "wrong"
        elif all(k in sizes for k in (16777216, 33554432, 67108864)):
            res = "correct"
        else:
            res = "none"
    row["result"] = res
    any_nonzero = any(rc[r] != 0 for r in surv)
    if row["n_harness_end"] > 0:
        oc = "HUNG"
    elif res == "wrong" and row["n_err_surv"] == 0 and not any_nonzero:
        oc = "SILENT_WRONG"
    elif row["n_err_surv"] > 0 or any_nonzero:
        oc = "DECLINED"
    elif res == "correct":
        oc = "TRANSPARENT"
    else:
        oc = "OTHER"
    row["outcome"] = oc
    # ---- GIN specifics
    if wl == "gin":
        watch = {r: allm(L[r], G_WATCH) for r in (0, 1)}
        dev = {r: allm(L[r], G_DEV) for r in (0, 1)}
        rec = {r: allm(L[r], G_REC) for r in (0, 1)}
        row["n_watch"] = sum(len(watch[r]) for r in (0, 1))
        row["n_watch_anyline"] = sum(1 for r in (0, 1) for _, s in L[r] if G_WATCH_ANY.search(s))
        row["n_q4"] = sum(len(dev[r]) for r in (0, 1))
        row["n_rec"] = sum(len(rec[r]) for r in (0, 1))
        row["n_decl"] = sum(1 for r in (0, 1) for _, s in L[r] if G_DECL.search(s))
        row["n_judged"] = sum(1 for r in (0, 1) for _, s in L[r] if G_JUDGED.search(s))
        row["n_death"] = sum(1 for r in surv for _, s in L[r] if G_JUDGED.search(s))
        row["pol_ranks"] = sum(1 for r in (0, 1) if any(G_POL.search(s) for _, s in L[r]))
        wq = [m for r in (0, 1) for _, m in allm(L[r], G_WQ)]
        row["wq_lines"] = len(wq)
        row["wq_queries"] = sum(int(m.group(3)) for m in wq) if wq else ""
        row["wq_us_mean"] = ";".join(m.group(5) for m in wq)
        row["wq_us_max"] = ";".join(m.group(6) for m in wq)
        lb = [int(G_LB.search(s).group(1)) for r in (0, 1) for _, s in L[r] if G_LB.search(s)]
        row["lb_shadow_min"] = min(lb) if lb else ""
        row["lb_ranks"] = sum(1 for r in (0, 1) if any(G_LB.search(s) for _, s in L[r]))
        if cls == "qperr" and row.get("done_mono_ms") is not None and tgt is not None:
            done = row["done_mono_ms"]
            cands = []
            for t, m in watch[tgt]:
                if int(m.group(1)) == tgt:
                    cands.append((float(m.group(9)), "watch", m.group(8), t, m.group(7), float(m.group(6))))
            for t, m in dev[tgt]:
                if int(m.group(1)) == tgt:
                    cands.append((float(m.group(2)), "device", "", t, "", None))
            cands.sort()
            if cands:
                c = cands[0]
                row["det_by"], row["det_ms"], row["det_src"] = c[1], round(c[0] - done, 3), c[2]
                row["det_class"] = c[4]
                row["det_noreq_ms"] = c[5] if c[5] is not None else ""
                # monotone check of the receipt order vs mono order
            else:
                row["det_by"], row["det_ms"], row["det_src"] = "none", "", ""
            # all detections on target listed
            row["det_all_target"] = ";".join("%s:%.1f:%s" % (c[1], c[0] - done, c[2]) for c in cands)
            # first on either rank by receipt time
            both = []
            for r in (0, 1):
                for t, m in watch[r]:
                    both.append((t, "r%d:watch" % r, m.group(8)))
                for t, m in dev[r]:
                    both.append((t, "r%d:device" % r, ""))
            both.sort()
            if both and t_fault is not None:
                row["det1_s"], row["det1_by"], row["det1_src"] = round(both[0][0] - t_fault, 6), both[0][1], both[0][2]
            else:
                row["det1_s"], row["det1_by"], row["det1_src"] = "", "", ""
            # det_wcq_ms: target watch first with root CQE
            row["det_wcq_ms"] = row["det_ms"] if row.get("det_by") == "watch" and row.get("det_src") == "cq" else ""
            row["det1_wcq_ms"] = row["det_ms"] if (row.get("det1_by") == "r%d:watch" % tgt and row.get("det1_src") == "cq"
                                                   and row.get("det_by") == "watch") else ""
            rt = [float(m.group(6)) for _, m in rec[tgt] if int(m.group(1)) == tgt]
            row["rec_ms"] = round(rt[0] - done, 3) if rt else ""
            rr = sorted(t for r in (0, 1) for t, _ in rec[r])
            row["rec_rx_s"] = round(rr[0] - t_fault, 6) if rr and t_fault is not None else ""
    else:
        fins = {r: allm(L[r], N_FINV) for r in (0, 1)}
        decl = {r: allm(L[r], N_DECL) for r in (0, 1)}
        row["n_fin_verdict"] = sum(len(fins[r]) for r in surv)
        row["n_fin_verdict_all"] = sum(len(fins[r]) for r in (0, 1))
        row["n_finlog"] = sum(1 for r in (0, 1) for _, s in L[r] if N_FINLOG.search(s))
        row["n_declines"] = sum(len(decl[r]) for r in (0, 1))
        row["decl_pe"] = ";".join("PE%d:%d" % (r, len(decl[r])) for r in (0, 1))
        row["decl_reasons"] = " | ".join("PE%d:%s" % (r, m.group(4)[:60]) for r in (0, 1) for _, m in decl[r])
        row["decl_dt"] = ";".join("PE%d:%.4f" % (r, decl[r][0][0] - t_fault) for r in (0, 1) if decl[r] and t_fault)
        row["n_death"] = sum(1 for r in surv for _, s in L[r] if N_FINV.search(s) or "peer process gone" in s)
        row["n_bye_sent"] = sum(1 for r in (0, 1) for _, s in L[r] if N_BYE_SENT.search(s))
        row["n_bye_seen"] = sum(1 for r in (0, 1) for _, s in L[r] if N_BYE_SEEN.search(s))
        row["n_left"] = sum(1 for r in (0, 1) for _, s in L[r] if N_LEFT.search(s))
        row["n_failstop"] = sum(1 for r in (0, 1) for _, s in L[r] if N_FAILSTOP.search(s))
        row["n_released"] = sum(1 for r in (0, 1) for _, s in L[r] if N_RELEASED.search(s))
        row["released_pe"] = ";".join("PE%d:%d" % (r, sum(1 for _, s in L[r] if N_RELEASED.search(s))) for r in (0, 1))
        row["n_rec"] = sum(1 for r in (0, 1) for _, s in L[r] if N_RECOV.search(s))
        if surv and fins[surv[0]] and t_fault is not None:
            row["verdict_s"] = round(fins[surv[0]][0][0] - t_fault, 6)
        else:
            row["verdict_s"] = ""
        if cls == "kill" and len(surv) == 1:
            row["surv_rc"] = rc[surv[0]]
            row["surv_exit_s"] = round(tex[surv[0]] - t_fault, 6) if tex[surv[0]] is not None and t_fault else ""
        row["exit_dt"] = ";".join("PE%d:%s" % (r, round(tex[r] - t_fault, 4) if (tex[r] and t_fault) else "")
                                  for r in (0, 1))
    rows.append(row)

keys = []
for r in rows:
    for k in r:
        if k not in keys:
            keys.append(k)
with open(OUT, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=keys)
    w.writeheader()
    for r in rows:
        w.writerow(r)
print("rows", len(rows))
