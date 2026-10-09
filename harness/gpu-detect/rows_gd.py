#!/usr/bin/env python3
"""rows_gd.py - gpu-detect: one row per app trial from the raw files (EXPERIMENT.md 3.1), and the extra columns of the
regression trials (extra_gd2, extra_gd4, imported by score.py). Fixed with the predictions: the regexes and the outcome
rule below are the definitions the scorer uses.

    rows_gd.py <results dir> [--out trials_app.csv]   every app trial (raw/<id>/)
    rows_gd.py <results dir> --progress                per hold: trials done, trials without the start line, leftovers

App trials (apprun.py): r<r>.log holds rank r's lines as "<rain CLOCK_MONOTONIC at receipt> <line>"; a<r>.log the
agent's lines; trial.meta the runner's record. The outcome rule is the blind study's (../blind/rows_blind.py; its
EXPERIMENT.md 3.1) with this study's lines added to the error, death and configuration patterns:
  HUNG          a survivor was ended by the harness (grace or wall cap; n_harness_end counts them)
  SILENT_WRONG  not HUNG, the result is wrong, no survivor printed an error line and every survivor exited 0
  DECLINED      not HUNG and not SILENT_WRONG, and a survivor printed an error line or exited non-zero
  TRANSPARENT   every survivor exited 0, no error line, and the result is correct
  OTHER         anything else
Result: gin correct iff rank 0 printed "GIN Ring Exchange result: PASSED" and no rank printed a mismatch line (wrong if
FAILED or a mismatch line); nvs correct iff PE 0 printed all three size lines and no PE printed a validation line (wrong
if any validation line, also one the agent only counted).
New columns (gin): det_by (watch: the target's QP-watch line came first; device: a device-classified error CQE on the
target came first; none), det_ms (the first of them minus the hook's done_mono_ms, the target's own clock), det_src (where
the watch line took its class: cq, slot-wait, none, unread), n_watch (QP-watch
detection lines, both ranks), n_q4 (device-classified error CQE lines, both ranks), rec_ms (the target's first recovered
line t_resumed minus done_mono_ms), rec_rx_s (receipt of the first recovered line minus receipt of the fire line, rain
clock), n_decl, n_judged, det_cfg (ranks with the "GIN/TS: detect=1" start line), watch_cfg (its qpwatch_ms values, as
"r0:10;r1:10"), lb_on (ranks with "NIC copy path on"), lb_shadow (the smallest "N QP struct(s) equal to the host shadow"),
wq_queries, wq_us_mean, wq_us_max (the teardown watch line: the sum over ranks, the largest mean, the largest max),
us_case1..us_case4 (rank 0's us/batch per case).
New columns (nvs): t1w_cfg (PEs with the "t1w: gpu-detect=1" line), failstop_cfg (its failstop_ms values), n_fin_verdict
(survivor lines "FIN) without a goodbye: the peer process is gone"), n_bye_sent ("goodbye sent to" lines), n_bye_seen
("said goodbye"), n_left ("after its goodbye: it left"), n_failstop ("t1w: FAILSTOP: exiting"), n_released ("device waits
released"), n_declines (DECLINE lines, both PEs), surv_rc (the survivor's exit code, kill cells), surv_end, verdict_s (the
survivor's first FIN verdict line minus the kill acknowledgement, rain clock), n_val (validation lines kept + counted),
ms_16m, ms_32m, ms_64m (PE 0's per-iteration ms of each size).
"""
import argparse, csv, glob, json, os, re, sys

ERR = {
    "gin": [r"GIN/TS: declined rank=", r"judged dead", r"why=(declined|peer-dead|fw-watchdog|degraded)",
            r"the fault surfaces \(ncclRemoteError\)", r"NCCL (failure|error)", r"nccl(Remote|System|Internal|UnhandledCuda|InvalidUsage)Error",
            r"(?i)\bcuda (failure|error)\b", r"^Failed[,:] ", r"Failed to execute NCCL operations", r"^ERROR:|\bERROR: rank",
            r"GIN/REC: (commit failed|recovery aborted|prepare declined)", r"escalated rank=",
            r"NET/IB ?: Got completion from peer", r"Segmentation fault|Aborted"],
    "nvs": [r"\[nvshmem-t1\] PE\d+ [0-9.]+ DECLINE", r"\[nvshmem-ft\] PE\d+ marked failed", r"transparent mode (stays )?off",
            r"cuda failed with", r"NVSHMEM.*(ERROR|[Ee]rror)", r"error status: -?\d+ \(|non-zero status: -?\d+",
            r"CUDA error", r"Segmentation fault|Aborted", r"t1w: FAILSTOP: exiting", r"t1w: device waits released"],
}
NOT_ERR = r"error, data\["
REC = {"gin": r"GIN/TS: recovered rank=", "nvs": r"\[nvshmem-t1\] PE\d+ [0-9.]+ RECOVERED"}
DEATH = {"gin": r"judged dead|why=peer-dead",
         "nvs": r"peer_fin=1|FIN\) without a goodbye: the peer process is gone"}
FIRE = {("gin", "qperr"): r"GIN/FAULT: GDAKI fault fired", ("nvs", "qperr"): r"\[nvshmem-fault-inject\] shot 1 fire_mono_ms",
        ("nvs", "remacc"): r"\[nvshmem-fault-inject\] shot 1 fire_mono_ms"}
FIRE_DONE = {("nvs", "qperr"): r"\[nvshmem-fault-inject\] moved [1-9]\d* QP",
             ("nvs", "remacc"): r"\[nvshmem-fault-inject\] revoked remote access on [1-9]\d* RC QP",
             ("gin", "qperr"): r"GIN/FAULT: GDAKI fault fired.*moved [1-9]\d*/"}
ANCHOR = {"gin": r"=== Comparing GIN ring-exchange implementations ===", "nvs": r"^\[nvshmem-t1\] PE0 [0-9.]+ enabled:"}
INIT_FAIL = {"gin": r"(?!x)x", "nvs": r"nvshmemi_setup_transport failed|heap registration setup failed|nvshmem_init.*failed"}
CONFIG_OFF = {"gin": r"GIN/TS: transparent recovery OFF|GIN/REC: .*recovery disabled|the NIC copy path is off",
              "nvs": r"transparent mode (stays )?off|FT stays off"}
RE_FIRE_GIN = re.compile(r"GIN/FAULT: GDAKI fault fired.*moved (\d+)/\d+ .*fire_mono_ms=([0-9.]+) done_mono_ms=([0-9.]+)")
RE_WATCH = re.compile(r"GIN/TS: rank (\d+): QP watch: qpn \S+ \(rank (\d+), context (\d+)\) is in state (\S+) with no fault "
                      r"record for ([0-9.]+) ms; class (\S+) from (\S+) .*mono_ms=([0-9.]+)")
RE_Q4 = re.compile(r"GIN/Q4: device-classified error CQE rank=(\d+) .*class=(\S+) .*mono_ms=([0-9.]+)")
RE_REC = re.compile(r"GIN/TS: recovered rank=(\d+) peer=(\d+) role=(\w+) .*t_resumed=([0-9.]+)")
RE_DET_CFG = re.compile(r"GIN/TS: detect=1 rank=(\d+) qpwatch_ms=(\d+) grace_ms=(\d+) nocqe_ms=(\d+) nest_once=1 "
                        r"selftest=nic degraded_rounds=(\d)")
RE_LBON = re.compile(r"GIN/TS: rank (\d+): NIC copy path on: .*?(\d+) QP struct\(s\) equal to the host shadow, NIC only")
RE_WQ_TD = re.compile(r"GIN/TS: rank (\d+) QP watch at teardown: qpwatch_ms=(\d+) queries=(\d+) query_fail=(\d+) "
                      r"query_us_mean=([0-9.]+) query_us_max=([0-9.]+) detections=(\d+) other_states=(\d+)")
RE_CASE = re.compile(r"^\s+([1-4])\s+([0-9.]+)\s+([0-9.]+)\s+[0-9.]+x\s+\S+")
RE_T1W_CFG = re.compile(r"\[nvshmem-t1\] PE(\d+) [0-9.]+ t1w: gpu-detect=1 fin_death=(\d) goodbye=1 failstop_ms=(-?\d+) "
                        r"failstop_code=(\d+) wait_word=(\w+)")
NVS_SIZE = re.compile(r"^(\d+)B\s+([0-9.]+)ms")
COLS = ["id", "key", "hold", "cell", "build", "workload", "cls", "target", "env", "t_ms", "t_after_anchor_s", "d_s",
        "applied", "void", "config_ok", "config_why", "valid", "killed_rank", "rc0", "rc1", "end0", "end1", "n_harness_end",
        "n_err0",
        "n_err1", "err0", "err1", "n_rec", "n_death", "result", "outcome", "dt_err", "dt_end", "wall_s", "left", "rerun",
        "det_by", "det_ms", "det_src", "n_watch", "n_q4", "rec_ms", "rec_rx_s", "n_decl", "n_judged", "det_cfg", "watch_cfg",
        "lb_on", "lb_shadow", "wq_queries", "wq_us_mean", "wq_us_max", "us_case1", "us_case2", "us_case3", "us_case4",
        "t1w_cfg", "failstop_cfg", "n_fin_verdict", "n_bye_sent", "n_bye_seen", "n_left", "n_failstop", "n_released",
        "n_declines", "surv_rc", "surv_end", "verdict_s", "n_val", "ms_16m", "ms_32m", "ms_64m"]


def read_log(p):
    out = []
    try:
        with open(p, errors="replace") as f:
            for l in f:
                t, _, rest = l.rstrip("\n").partition(" ")
                try:
                    out.append((float(t), rest))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def first_match(lines, rx, start=None):
    r = re.compile(rx)
    for t, l in lines:
        if (start is None or t >= start) and r.search(l):
            return t, l
    return None, None


def count(lines, rx):
    r = re.compile(rx)
    return sum(1 for _, l in lines if r.search(l))


def err_lines(wl, lines):
    rs = [re.compile(x) for x in ERR[wl]]
    ne = re.compile(NOT_ERR)
    return [(t, l) for t, l in lines if not ne.search(l) and any(r.search(l) for r in rs)]


def expected_cfg(wl, build, env):
    """What the start lines must show for this build and cell environment."""
    if wl == "gin":
        return {"watch": int(env.get("NCCL_GIN_TS_QPWATCH_MS", "10"))} if build == "hw" else {}
    return {"failstop": int(env.get("NVSHMEM_IBGDA_FT_T1_FAILSTOP_MS", "0"))} if build == "t1w" else {}


def row_of(d):
    m = json.load(open(os.path.join(d, "trial.meta")))
    e, p = m["entry"], m.get("params", {})
    wl, cls, target, build = e["workload"], e["cls"], e.get("target"), e["build"]
    env = {k: str(v) for k, v in (e.get("env") or {}).items()}
    logs = {r: read_log(os.path.join(d, "r%d.log" % r)) for r in (0, 1)}
    agent = {r: read_log(os.path.join(d, "a%d.log" % r)) for r in (0, 1)}
    t_anchor, _ = first_match(logs[0], ANCHOR[wl])
    row = {c: "" for c in COLS}
    row.update({"id": m["id"], "key": "%s@%s" % (e["cell"], build), "hold": e.get("hold", ""), "cell": e["cell"],
                "build": build, "workload": wl, "cls": cls, "target": "" if target is None else target,
                "env": ";".join("%s=%s" % kv for kv in sorted(env.items())), "t_ms": p.get("t_ms", ""),
                "t_after_anchor_s": p.get("t_after_anchor_s", ""), "d_s": p.get("d_s", ""), "wall_s": m.get("wall_s", ""),
                "left": "%s,%s" % tuple(m.get("left", ("", ""))), "rerun": len(glob.glob(d + ".partial*"))})
    f = m.get("fault", {})
    t_fault = None
    if (wl, cls) in FIRE:
        t_fire, _ = first_match(logs[target], FIRE[(wl, cls)])
        done_rx = FIRE_DONE.get((wl, cls))
        applied = t_fire is not None and (done_rx is None or first_match(logs[target], done_rx)[0] is not None)
        t_fault = t_fire if applied else None
    elif cls in ("kill", "stop"):
        applied = bool(f.get("applied"))
        t_fault = f.get("t_ack") if applied else None
    else:
        applied = True
    row["applied"] = int(applied)
    killed = target if (cls == "kill" and applied) else None
    row["killed_rank"] = "" if killed is None else killed
    survivors = [r for r in (0, 1) if r != killed]
    ex = m.get("exit", {})
    for r in (0, 1):
        x = ex.get(str(r), ex.get(r, {})) or {}
        row["rc%d" % r] = "" if x.get("rc") is None else x["rc"]
        row["end%d" % r] = x.get("harness_end", "")
    t_init_fail = min([t for r in (0, 1) for t in [first_match(logs[r], INIT_FAIL[wl])[0]] if t is not None], default=None)
    started = t_anchor is not None and t_init_fail is None
    row["void"] = int(not started and not (applied and cls != "none" and t_fault is not None and
                                           (t_init_fail is None or t_fault < t_init_fail)))
    errs = {r: err_lines(wl, logs[r]) for r in (0, 1)}
    for r in (0, 1):
        row["n_err%d" % r] = len(errs[r])
        row["err%d" % r] = errs[r][0][1][:160] if errs[r] else ""
    surv_errs = sorted((t, l) for r in survivors for t, l in errs[r])
    row["n_rec"] = sum(count(logs[r], REC[wl]) for r in (0, 1))
    row["n_death"] = sum(count(logs[r], DEATH[wl]) for r in survivors)
    if t_fault is not None:
        late = [t for t, _ in surv_errs if t >= t_fault - 0.5]
        row["dt_err"] = round(late[0] - t_fault, 3) if late else ""
        ends = []
        for r in survivors:
            x = ex.get(str(r), ex.get(r, {})) or {}
            if x.get("t_exit") is not None:
                ends.append(x["t_exit"])
        row["dt_end"] = round(max(ends) - t_fault, 3) if ends and len(ends) == len(survivors) else ""
    # result (oracle)
    if wl == "gin":
        res, _ = first_match(logs[0], r"GIN Ring Exchange result: PASSED")
        fail, _ = first_match(logs[0], r"GIN Ring Exchange result: FAILED")
        mis = any(first_match(logs[r], r"mismatch at CTA")[0] is not None for r in (0, 1))
        result = "wrong" if (fail is not None or mis) else ("correct" if res is not None else "none")
    else:
        sizes = {}
        for _, l in logs[0]:
            mm = NVS_SIZE.match(l)
            if mm:
                sizes[int(mm.group(1))] = float(mm.group(2))
        nval = sum(count(logs[r], NOT_ERR) for r in (0, 1))
        for r in (0, 1):
            for _, l in agent[r]:
                mm = re.search(r"AGENT suppressed name=validation count=(\d+)", l)
                if mm:
                    nval += int(mm.group(1))
        row["n_val"] = nval
        for sz, col in ((16 << 20, "ms_16m"), (32 << 20, "ms_32m"), (64 << 20, "ms_64m")):
            row[col] = sizes.get(sz, "")
        result = "wrong" if nval else ("correct" if len(sizes) >= 3 else "none")
    row["result"] = result
    rc_ok = all(row["rc%d" % r] == 0 for r in survivors)
    row["n_harness_end"] = sum(1 for r in survivors if row["end%d" % r] in ("grace", "wall"))
    hung = row["n_harness_end"] > 0
    any_err = bool(surv_errs)
    if hung:
        outcome = "HUNG"
    elif result == "wrong" and not any_err and rc_ok:
        outcome = "SILENT_WRONG"
    elif any_err or not rc_ok:
        outcome = "DECLINED"
    elif result == "correct":
        outcome = "TRANSPARENT"
    else:
        outcome = "OTHER"
    row["outcome"] = outcome
    exp = expected_cfg(wl, build, env)
    why = ""
    present = [r for r in (0, 1) if logs[r] and r != killed]  # a killed rank may end before its start lines
    if wl == "gin":
        row["n_decl"] = sum(count(logs[r], r"GIN/TS: declined rank=") for r in (0, 1))
        row["n_judged"] = sum(count(logs[r], r"judged dead") for r in (0, 1))
        cfg = {}
        lbs = {}
        for r in (0, 1):
            for _, l in logs[r]:
                mm = RE_DET_CFG.search(l)
                if mm:
                    cfg[r] = int(mm.group(2))
                mm = RE_LBON.search(l)
                if mm:
                    lbs[r] = int(mm.group(2))
        row["det_cfg"] = len(cfg)
        row["watch_cfg"] = ";".join("r%d:%d" % (r, cfg[r]) for r in sorted(cfg))
        row["lb_on"] = sum(1 for r in (0, 1) if first_match(logs[r], r"NIC copy path on:")[0] is not None)
        row["lb_shadow"] = min(lbs.values()) if lbs else ""
        ts_on = all(first_match(logs[r], r"GIN/TS: transparent recovery ON rank=")[0] is not None for r in present)
        rem_on = {r: first_match(logs[r], r"GIN/TS: remaining=1 rank=")[0] is not None for r in present}
        if not ts_on:
            why = "transparent recovery not on"
        elif build == "hq" and (any(rem_on.values()) or cfg):
            why = "hq shows a later layer"
        elif build == "hr" and (not all(rem_on.values()) or cfg):
            why = "hr is not gin-remaining's layer alone"
        elif build == "hw" and not (all(r in cfg and cfg[r] == exp["watch"] for r in present) and
                                    all(r in lbs and lbs[r] >= 1 for r in present)):
            why = "hw start lines (detect=1 with the cell's qpwatch_ms, NIC path with its NIC-only self-test) missing"
        # detection and recovery (target rank, its own clock)
        if cls == "qperr" and target is not None:
            fire = None
            for _, l in logs[target]:
                mm = RE_FIRE_GIN.search(l)
                if mm:
                    fire = float(mm.group(3))
                    break
            w = [(float(mm.group(8)), l) for _, l in logs[target] for mm in [RE_WATCH.search(l)] if mm]
            q = [(float(mm.group(3)), l) for _, l in logs[target] for mm in [RE_Q4.search(l)] if mm]
            rec = [float(mm.group(4)) for _, l in logs[target] for mm in [RE_REC.search(l)] if mm]
            if fire is not None:
                firsts = []
                if w:
                    firsts.append((w[0][0], "watch"))
                    row["det_src"] = RE_WATCH.search(w[0][1]).group(7)
                if q:
                    firsts.append((q[0][0], "device"))
                if firsts:
                    t0, by = min(firsts)
                    row["det_by"], row["det_ms"] = by, round(t0 - fire, 3)
                else:
                    row["det_by"] = "none"
                if rec:
                    row["rec_ms"] = round(rec[0] - fire, 3)
            tf, _ = first_match(logs[target], FIRE[(wl, cls)])
            tr = min([t for r in (0, 1) for t in [first_match(logs[r], REC[wl])[0]] if t is not None], default=None)
            if tf is not None and tr is not None:
                row["rec_rx_s"] = round(tr - tf, 3)
        row["n_watch"] = sum(count(logs[r], r"GIN/TS: rank \d+: QP watch: .* fault queued") for r in (0, 1))
        row["n_q4"] = sum(count(logs[r], r"GIN/Q4: device-classified error CQE") for r in (0, 1))
        tds = [mm for r in (0, 1) for _, l in logs[r] for mm in [RE_WQ_TD.search(l)] if mm]
        if tds:
            row["wq_queries"] = sum(int(x.group(3)) for x in tds)
            row["wq_us_mean"] = max(float(x.group(5)) for x in tds)
            row["wq_us_max"] = max(float(x.group(6)) for x in tds)
        for _, l in logs[0]:
            mm = RE_CASE.match(l)
            if mm:
                row["us_case" + mm.group(1)] = float(mm.group(2))
    else:
        cfg = {}
        for r in (0, 1):
            for _, l in logs[r]:
                mm = RE_T1W_CFG.search(l)
                if mm:
                    cfg[r] = int(mm.group(3))
        row["t1w_cfg"] = len(cfg)
        row["failstop_cfg"] = ";".join("r%d:%d" % (r, cfg[r]) for r in sorted(cfg))
        on = all(first_match(logs[r], ANCHOR["nvs"].replace("PE0", r"PE\d"))[0] is not None for r in present)
        if not on:
            why = "transparent mode not on"
        elif build == "t1_380" and cfg:
            why = "t1_380 shows the t1w line"
        elif build == "t1w" and not all(r in cfg and cfg[r] == exp["failstop"] for r in present):
            why = "t1w start line with the cell's failstop_ms missing"
        row["n_fin_verdict"] = sum(count(logs[r], r"FIN\) without a goodbye: the peer process is gone") for r in survivors)
        row["n_bye_sent"] = sum(count(logs[r], r"t1w: goodbye sent to [1-9]\d* peer") for r in (0, 1))
        row["n_bye_seen"] = sum(count(logs[r], r"t1w: peer \d+ said goodbye") for r in (0, 1))
        row["n_left"] = sum(count(logs[r], r"after its goodbye: it left") for r in (0, 1))
        row["n_failstop"] = sum(count(logs[r], r"t1w: FAILSTOP: exiting") for r in (0, 1))
        row["n_released"] = sum(count(logs[r], r"t1w: device waits released") for r in (0, 1))
        row["n_declines"] = sum(count(logs[r], r"\[nvshmem-t1\] PE\d+ [0-9.]+ DECLINE") for r in (0, 1))
        if killed is not None:
            s = 1 - killed
            row["surv_rc"] = row["rc%d" % s]
            row["surv_end"] = row["end%d" % s]
            tv, _ = first_match(logs[s], r"FIN\) without a goodbye: the peer process is gone")
            if tv is not None and t_fault is not None:
                row["verdict_s"] = round(tv - t_fault, 4)
    if not why and any(first_match(logs[r], CONFIG_OFF[wl])[0] is not None for r in (0, 1)):
        why = "a rank reports its recovery (or the NIC copy path) off"
    row["config_ok"] = int(not why)
    row["config_why"] = why
    row["valid"] = int(applied and not row["void"] and not why)
    return row


def all_rows(results):
    return [row_of(os.path.dirname(meta)) for meta in sorted(glob.glob(os.path.join(results, "raw", "*", "trial.meta")))]


# ---------------------------------------------------------------- regression trials (score.py adds these columns)
RE_DET_ANY = re.compile(r"GIN/TS: detect=1 rank=(\d+) qpwatch_ms=(\d+)")


def _lines(path):
    try:
        return open(path, errors="replace").read().splitlines()
    except OSError:
        return []


def extra_gd2(stem):
    """Two-rank regression trial (run_trial_hr.sh files): the hw start line, the watch's teardown counters."""
    out = {"det_on_r0": 0, "det_on_r1": 0, "det_ms_cfg": "", "n_watch2": 0, "wq_queries2": "", "wq_us_mean2": "",
           "wq_us_max2": "", "lb_shadow2": ""}
    cfgs, sh, tds = [], [], []
    for r in (0, 1):
        for l in _lines("%s_r%d.log" % (stem, r)):
            mm = RE_DET_ANY.search(l)
            if mm:
                out["det_on_r%d" % r] += 1
                cfgs.append(mm.group(2))
            mm = RE_LBON.search(l)
            if mm:
                sh.append(int(mm.group(2)))
            mm = RE_WQ_TD.search(l)
            if mm:
                tds.append(mm)
            if re.search(r"GIN/TS: rank \d+: QP watch: .* fault queued", l):
                out["n_watch2"] += 1
    out["det_ms_cfg"] = ";".join(sorted(set(cfgs)))
    out["lb_shadow2"] = min(sh) if sh else ""
    if tds:
        out["wq_queries2"] = sum(int(x.group(3)) for x in tds)
        out["wq_us_mean2"] = max(float(x.group(5)) for x in tds)
        out["wq_us_max2"] = max(float(x.group(6)) for x in tds)
    return out


def extra_gd4(stem, n):
    """N-rank regression trial (run_mr_hr.sh files): the hw start lines, watch detections, the pair 0-1's end."""
    out = {"n_det_on": 0, "n_watch4": 0, "served3": "", "rec01": 0, "decl01": 0}
    served = set()
    for r in range(n):
        for l in _lines("%s_r%d.log" % (stem, r)):
            if RE_DET_ANY.search(l):
                out["n_det_on"] += 1
            if re.search(r"GIN/TS: rank \d+: QP watch: .* fault queued", l):
                out["n_watch4"] += 1
            mm = re.search(r"GIN/TS: rank (\d+): answering REQ round \d+ from rank (\d+) while waiting", l)
            if mm and mm.group(1) == "3":
                served.add("3-" + mm.group(2))
            if r == 0 and re.search(r"GIN/TS: recovered rank=0 peer=1 ", l):
                out["rec01"] += 1
            if r == 0 and re.search(r"GIN/TS: declined rank=0 peer=1 ", l):
                out["decl01"] += 1
    out["served3"] = ";".join(sorted(served))
    return out


def progress(results):
    out = {}
    for meta in sorted(glob.glob(os.path.join(results, "raw", "*", "trial.meta"))):
        m = json.load(open(meta))
        e = m["entry"]
        o = out.setdefault(e.get("hold", "?"), {"done": 0, "no_start": 0, "left": 0})
        o["done"] += 1
        if first_match(read_log(os.path.join(os.path.dirname(meta), "r0.log")), ANCHOR[e["workload"]])[0] is None:
            o["no_start"] += 1
        o["left"] += int(any(str(x) not in ("0", "") for x in m.get("left", [])))
    for h in sorted(out):
        print("%s: %s" % (h, out[h]))
    for sub in ("hw", "mr_hw"):
        n = len(glob.glob(os.path.join(results, "reg", sub, "*_meta.txt")))
        if n:
            print("reg/%s: %d trial(s)" % (sub, n))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results")
    ap.add_argument("--out", default=None)
    ap.add_argument("--progress", action="store_true")
    a = ap.parse_args()
    if a.progress:
        progress(a.results)
        return
    rows = all_rows(a.results)
    out = a.out or os.path.join(a.results, "trials_app.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    print("%d rows -> %s" % (len(rows), out))


if __name__ == "__main__":
    main()
