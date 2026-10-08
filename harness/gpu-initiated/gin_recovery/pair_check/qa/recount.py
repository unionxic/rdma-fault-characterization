#!/usr/bin/env python3
"""gin-pair-check: independent recount from the raw per-trial files (QA).

usage: recount.py [<results dir, default ../results/20261008>] [--csv <out.csv>]

Written without score.py, rows_pc.py, SCORE.md or trials_scored.csv. Every column of EXPERIMENT.md 3.1 that a
prediction uses is re-derived here from <stem>_meta.txt, <stem>_r{0,1}.kv, <stem>_r{0,1}.log and <stem>_kill.out.
The acceptance strings are read from predictions.csv and evaluated with the grammar of ../s2_close/EXPERIMENT.md 3.2
(count, median, has, nonempty, abs, per cell; numbers as floats, blanks as None, any comparison or arithmetic with
None is false), implemented anew below. Exclusions follow EXPERIMENT.md 8; the hold of each trial comes from the
hold windows in hold_<H>.out and the trial's own file time and first log time stamp.
Prints the report to stdout. Reads only; writes nothing unless --csv is given.
"""
import argparse, csv, glob, gzip, os, re, statistics, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
SUBDIRS = ["lat", "rep_pc", "dual", "f3", "conflict"]

# EXPERIMENT.md 7: planned scored trials (latency cells: runs)
PLAN = {
    "f3_b@pc": 10, "pc_dual_f1c0_r1c2_b@pcd": 10, "pc_dual_f1c0_b@pcd": 10, "pc_bidirf_conflict_b@pc": 10,
    "f3_b_nocheck@pc": 5, "pc_dual_f1c0_r1off_b@pcd": 5, "pr_dual_f1c0_b@prd": 5,
    "f1_b@pc": 5, "bidirf_sym_b@pc": 5, "mt256_f1_b@pc": 5, "f4_b@pc": 5, "f2rel_b@pc": 5,
    "pc_dual_f3c0_b@pcd": 5, "pc_dual_f1all_b@pcd": 5,
    "lat_pr_on_4k@pr": 5, "lat_pr_on_256k@pr": 5, "lat_pc_on_4k@pc": 5, "lat_pc_on_256k@pc": 5,
}
# EXPERIMENT.md 8: fault-not-applied groups
R0_HOOK = {"pc_dual_f1c0_b", "pc_dual_f1c0_r1off_b", "pr_dual_f1c0_b", "pc_dual_f1all_b", "f1_b", "mt256_f1_b"}
R1_HOOK = {"f3_b", "f3_b_nocheck", "pc_dual_f3c0_b"}
BOTH_HOOK = {"pc_dual_f1c0_r1c2_b", "pc_bidirf_conflict_b", "bidirf_sym_b"}
KILL = {"f4_b"}


# ---------------------------------------------------------------- raw readers
def read_kv(path):
    """key=value tokens; a value runs to the next ' key=' (values may hold blanks, e.g. tx_rc=no error)."""
    d = {}
    if not os.path.exists(path):
        return d
    with open(path, errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            keys = list(re.finditer(r"(?:^| )([A-Za-z_][\w]*)=", line))
            for i, m in enumerate(keys):
                end = keys[i + 1].start() if i + 1 < len(keys) else len(line)
                d[m.group(1)] = line[m.end():end].strip()
    return d


R_PR = re.compile(r"GIN/TS: pair reset=(\d) rank=(\d+)")
R_PC = re.compile(r"GIN/TS: pair check=(\d) rank=(\d+)")
R_DEC = re.compile(r"GIN/TS: rank (\d+): round (\d+) peer (\d+) scope=(0x[0-9a-fA-F]+) qps=(\d+) reason=(\w+) mono_ms=([\d.]+)")
R_CHK = re.compile(r"GIN/TS: rank (\d+): REQ round (\d+) from rank (\d+) scope=(0x[0-9a-fA-F]+) checked=(\d+) not_rts=(\d+) "
                   r"check_us=(\d+) (accepted|refused reason=(\w+)) mono_ms=([\d.]+)")
R_RERUN = re.compile(r"GIN/TS: rank (\d+): peer (\d+) refused the scope of round (\d+); rerunning as a full reset mono_ms=([\d.]+)")
R_CONF = re.compile(r"GIN/TS: rank=(\d+) scope conflict: REQ round (\d+) from rank (\d+) scope=(0x[0-9a-fA-F]+), ours "
                    r"scope=(0x[0-9a-fA-F]+) round (\d+); ours is requeued (for a new scope decision|as a full reset)")
R_EP = re.compile(r"GIN/TS: rank (\d+) gate epochs to rank (\d+): \[([^\]]*)\]")
R_QPS = re.compile(r"GIN/TS: rank (\d+) qp states to rank (\d+): \[([^\]]*)\]")
R_FIRE = re.compile(r"GIN/FAULT: GDAKI fault fired.*?moved (\d+)/(\d+) GIN QP\(s\) to ERR(?: context=(\d+))? fire_mono_ms=([\d.]+)")
R_STALL = re.compile(r"GIN/TS: TEST stall rank=0 (\d+) ms after quiesce mono_ms=([\d.]+)")
R_Q4 = re.compile(r"device-classified error CQE .*?mono_ms=([\d.]+)")
R_DECL = re.compile(r'GIN/TS: declined .*?reason="([^"]*)"')
R_TS = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\]")


def rec_fields(line):
    tail = line.split("GIN/TS: recovered", 1)[1]
    return dict(re.findall(r"([\w/]+)=(\[[^\]]*\]|\S+)", tail))


def read_log(path):
    o = {"pr": None, "pc": None, "dec": [], "chk": [], "rerun": [], "conf": [], "ep": None, "qps": None, "fires": [],
         "stall": [], "q4": [], "decl": [], "rec": [], "ts_on": 0, "ua": 0, "trigger_miss": 0, "first_ts": None,
         "bind_fail": 0, "events": []}
    if not os.path.exists(path):
        return o
    with open(path, errors="replace") as f:
        for line in f:
            if o["first_ts"] is None:
                m = R_TS.match(line)
                if m:
                    o["first_ts"] = m.group(1)
            if "bind: Address already in use" in line:
                o["bind_fail"] = 1
            if "GIN/TS: transparent recovery ON" in line:
                o["ts_on"] += 1
            if "GIN/TS: user devComm abort flag set" in line:
                o["ua"] += 1
            if "GIN/FAULT: shot 1 trigger not reached" in line:
                o["trigger_miss"] += 1
            m = R_PR.search(line)
            if m:
                o["pr"] = int(m.group(1))
            m = R_PC.search(line)
            if m:
                o["pc"] = int(m.group(1))
            m = R_DEC.search(line)
            if m:
                d = {"round": int(m.group(2)), "scope": m.group(4), "qps": int(m.group(5)), "reason": m.group(6),
                     "mono": float(m.group(7))}
                o["dec"].append(d)
                o["events"].append("dec(r%d %s %s)" % (d["round"], d["scope"], d["reason"]))
            m = R_CHK.search(line)
            if m:
                d = {"round": int(m.group(2)), "scope": m.group(4), "checked": int(m.group(5)), "not_rts": int(m.group(6)),
                     "check_us": int(m.group(7)), "accepted": m.group(8) == "accepted", "reason": m.group(9) or "",
                     "mono": float(m.group(10))}
                o["chk"].append(d)
                o["events"].append("chk(r%d %s %s%s)" % (d["round"], d["scope"], "accepted" if d["accepted"] else
                                                         "refused " + d["reason"], "" if d["accepted"] else
                                                         " not_rts=%d" % d["not_rts"]))
            m = R_RERUN.search(line)
            if m:
                o["rerun"].append(int(m.group(3)))
                o["events"].append("rerun(r%s)" % m.group(3))
            m = R_CONF.search(line)
            if m:
                d = {"req_round": int(m.group(2)), "req_scope": m.group(4), "our_scope": m.group(5),
                     "our_round": int(m.group(6)), "how": m.group(7)}
                o["conf"].append(d)
                o["events"].append("conflict(REQ %s vs ours %s -> %s)" % (d["req_scope"], d["our_scope"],
                                                                         "re-decide" if d["how"].startswith("for")
                                                                         else "full"))
            m = R_EP.search(line)
            if m:
                o["ep"] = [x.strip() for x in m.group(3).split(",")]
            m = R_QPS.search(line)
            if m:
                o["qps"] = [x.strip() for x in m.group(3).split(",")]
            m = R_FIRE.search(line)
            if m:
                o["fires"].append({"moved": int(m.group(1)), "of": int(m.group(2)), "ctx": m.group(3),
                                   "mono": float(m.group(4))})
            m = R_STALL.search(line)
            if m:
                o["stall"].append((float(m.group(1)), float(m.group(2))))
            if "device-classified error CQE" in line:
                m = R_Q4.search(line)
                if m:
                    mc = re.search(r" class=(\w+)", line)
                    o["q4"].append((float(m.group(1)), mc.group(1) if mc else ""))
            m = R_RERUN.search(line)
            if m:
                o["rerun_mono"] = o.get("rerun_mono", []) + [float(m.group(4))]
            m = R_DECL.search(line)
            if m and "GIN/TS: declined" in line:
                o["decl"].append(m.group(1))
            if "GIN/TS: recovered" in line:
                d = rec_fields(line)
                o["rec"].append(d)
                o["events"].append("rec(%s %s qps=%s)" % (d.get("role"), d.get("scope"), d.get("qps")))
    return o


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def rank_ok(k, iters, sender, receiver):
    """transparent_ok, as rows.py defines it (kv of one rank)."""
    if k.get("outcome") != "ok" or k.get("async_first") != "none":
        return False
    if sender and not (k.get("tx_done") == str(iters) and k.get("tx_rc") == "no error"):
        return False
    if receiver and not (k.get("rx_done") == str(iters) and k.get("rx_rc") == "no error" and k.get("dev_bad_slots") == "0"
                         and k.get("host_bad_slots") == "0" and k.get("signal_exact") == "1"):
        return False
    return True


# ---------------------------------------------------------------- one row per trial
def trial_row(sub, stem):
    m = read_kv(stem + "_meta.txt")
    k0, k1 = read_kv(stem + "_r0.kv"), read_kv(stem + "_r1.kv")
    l0, l1 = read_log(stem + "_r0.log"), read_log(stem + "_r1.log")
    kill = read_kv(stem + "_kill.out")
    iters = int(m.get("iters", "0"))
    bidir = m.get("app") == "bidir"
    off = fnum(k0.get("clock_offset_ms"))
    r = {"sub": sub, "stem": os.path.basename(stem), "cell": m.get("cell"), "build": m.get("build"),
         "trial": m.get("trial"), "bundle": m.get("bundle"), "app": m.get("app"), "iters": iters,
         "r0rc": fnum(m.get("r0rc")), "r1rc": fnum(m.get("r1rc")), "left": fnum(m.get("left")),
         "meta_mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(stem + "_meta.txt"))),
         "first_ts": l0["first_ts"] or l1["first_ts"]}
    r["key"] = "%s@%s" % (r["cell"], r["build"])
    r["bind_fail"] = l0["bind_fail"]
    r["transparent_ok"] = int(rank_ok(k0, iters, True, bidir) and rank_ok(k1, iters, bidir, True))
    r["r1_outcome"] = k1.get("outcome")
    r["teardown_r0"], r["teardown_r1"] = k0.get("abort_ret"), k1.get("abort_ret")
    r["teardown_ms_r1"] = fnum(k1.get("teardown_ms"))
    r["decl_r0"], r["decl_r1"] = ";".join(l0["decl"]), ";".join(l1["decl"])
    r["lat_p50_us"] = fnum(k0.get("lat_p50_us"))
    r["n_fires_r0"], r["n_fires_r1"] = len(l0["fires"]), len(l1["fires"])
    r["fire_moved_r0"] = "%d/%d" % (l0["fires"][0]["moved"], l0["fires"][0]["of"]) if l0["fires"] else ""
    r["fire_moved_r1"] = "%d/%d" % (l1["fires"][0]["moved"], l1["fires"][0]["of"]) if l1["fires"] else ""
    r["trigger_miss"] = l0["trigger_miss"] + l1["trigger_miss"]
    r["ts_on_r0"], r["ts_on_r1"], r["ua_r0"], r["ua_r1"] = l0["ts_on"], l1["ts_on"], l0["ua"], l1["ua"]
    r["killed"] = 1 if kill.get("kill_mono_ms") else 0
    r["pr_mode_r0"], r["pr_mode_r1"], r["pc_mode_r0"], r["pc_mode_r1"] = l0["pr"], l1["pr"], l0["pc"], l1["pc"]
    r["scope_r0"] = l0["dec"][0]["scope"] if l0["dec"] else None
    r["scope_reason_r0"] = l0["dec"][0]["reason"] if l0["dec"] else None
    r["n_dec_r0"], r["n_dec_r1"] = len(l0["dec"]), len(l1["dec"])
    r["last_reason_r0"] = l0["dec"][-1]["reason"] if l0["dec"] else None
    r["last_reason_r1"] = l1["dec"][-1]["reason"] if l1["dec"] else None
    for rk, lg in (("r0", l0), ("r1", l1)):
        r["rec_scope_" + rk] = lg["rec"][0].get("scope") if lg["rec"] else None
        r["rec_qps_" + rk] = fnum(lg["rec"][0].get("qps")) if lg["rec"] else None
        r["n_rec_" + rk] = len(lg["rec"])
        r["n_checked_" + rk] = sum(1 for c in lg["chk"] if c["accepted"])
        r["n_refused_" + rk] = sum(1 for c in lg["chk"] if not c["accepted"])
        r["qpst_" + rk] = "[" + ",".join(lg["qps"]) + "]" if lg["qps"] is not None else None
        r["n_notrts_" + rk] = sum(1 for s in lg["qps"] if s != "3") if lg["qps"] is not None else None
        r["ep_" + rk] = "[" + ",".join(lg["ep"]) + "]" if lg["ep"] is not None else None
        for c in range(4):
            r["ep_c%d_%s" % (c, rk)] = fnum(lg["ep"][c]) if (lg["ep"] is not None and c < len(lg["ep"])) else None
        r["inj_ctx_" + rk] = lg["fires"][0]["ctx"] if lg["fires"] else None
        r["events_" + rk] = " ".join(lg["events"])
    init1 = [x for x in l1["rec"] if x.get("role") == "initiator"]
    r["init_qps_r1"] = fnum(init1[0].get("qps")) if init1 else None
    init0 = [x for x in l0["rec"] if x.get("role") == "initiator"]
    r["commit_us_r0"] = fnum(init0[0].get("commit_us")) if init0 else None
    r["total_us_r0"] = fnum(init0[0].get("total_us")) if init0 else None
    acc1 = [c for c in l1["chk"] if c["accepted"]]
    r["check_us_r1"] = acc1[0]["check_us"] if acc1 else None
    ref1 = [c for c in l1["chk"] if not c["accepted"]]
    r["refuse_reason_r1"] = ref1[0]["reason"] if ref1 else None
    r["not_rts_r1"] = ref1[0]["not_rts"] if ref1 else None
    r["refuse_check_us_r1"] = ref1[0]["check_us"] if ref1 else None
    r["n_rerun_r0"] = len(l0["rerun"])
    r["conflict_r1"] = len(l1["conf"])
    r["conflict_how_r1"] = ";".join("re-decide" if c["how"].startswith("for") else "full" for c in l1["conf"])
    r["dec_r1"] = ";".join("%s/%s/q%d" % (d["scope"], d["reason"], d["qps"]) for d in l1["dec"])
    r["dec_r0"] = ";".join("%s/%s/q%d" % (d["scope"], d["reason"], d["qps"]) for d in l0["dec"])
    r["rec_r1"] = ";".join("%s/%s/q%s" % (x.get("role"), x.get("scope"), x.get("qps")) for x in l1["rec"])
    r["rec_r0"] = ";".join("%s/%s/q%s" % (x.get("role"), x.get("scope"), x.get("qps")) for x in l0["rec"])
    # r1_q4_in_stall (../pair_reset/EXPERIMENT.md 3.1): rank 1's first device-side classification record on rank 0's clock inside
    # [t, t + ms - 2] of rank 0's TEST stall line (the first one); blank if either is missing
    r["r1_q4_in_stall"] = None
    r["r1_q4_in_any_stall"] = None
    if l1["q4"] and l0["stall"] and off is not None:
        q = l1["q4"][0][0] - off
        ms, t = l0["stall"][0]
        r["r1_q4_in_stall"] = 1 if (t <= q <= t + ms - 2) else 0
        r["r1_q4_in_any_stall"] = 1 if any(t2 <= q <= t2 + m2 - 2 for m2, t2 in l0["stall"]) else 0
    r["n_stall_r0"] = len(l0["stall"])
    # r1_fire_before_dec: rank 1's first hook fire on rank 0's clock before rank 0's first scope decision
    r["r1_fire_before_dec"] = None
    r["r1_fire_lead_ms"] = None
    if l1["fires"] and l0["dec"] and off is not None:
        f1 = l1["fires"][0]["mono"] - off
        r["r1_fire_before_dec"] = 1 if f1 < l0["dec"][0]["mono"] else 0
        r["r1_fire_lead_ms"] = l0["dec"][0]["mono"] - f1
    r["fire_dt_r1_minus_r0_ms"] = ((l1["fires"][0]["mono"] - off) - l0["fires"][0]["mono"]
                                   if (l0["fires"] and l1["fires"] and off is not None) else None)
    # timings used by section 15 (all on rank 0's clock, ms; rank 1 moved with rank 0 kv clock_offset_ms)
    q0 = l0["q4"][0][0] if l0["q4"] else None
    d0 = l0["dec"][0]["mono"] if l0["dec"] else None
    r["q4_class_r0"] = l0["q4"][0][1] if l0["q4"] else None
    r["n_q4_r1"] = len(l1["q4"])
    r["r1fire_to_r0q4_ms"] = (q0 - (l1["fires"][0]["mono"] - off)) if (q0 and l1["fires"] and off is not None) else None
    r["r0fire_to_r0q4_ms"] = (q0 - l0["fires"][0]["mono"]) if (q0 and l0["fires"]) else None
    r["r0q4_to_dec_ms"] = (d0 - q0) if (q0 and d0) else None
    rr = l0.get("rerun_mono", [])
    r["dec_to_rerun_ms"] = (rr[0] - d0) if (rr and d0) else None
    r["dec_to_dec2_ms"] = (l0["dec"][1]["mono"] - d0) if len(l0["dec"]) > 1 else None
    res0 = fnum(init0[0].get("t_resumed")) if init0 else None
    r["dec_to_resumed_ms"] = (res0 - d0) if (res0 and d0) else None
    r["acc_checked_r1"] = ";".join(str(c["checked"]) for c in l1["chk"] if c["accepted"])
    r["ref_checked_r1"] = ";".join("%d/%d" % (c["checked"], c["check_us"]) for c in l1["chk"] if not c["accepted"])
    r["dual_r0"], r["dual_r1"] = fnum(k0.get("dual")), fnum(k1.get("dual"))
    for key in ("dual_c1_in_win", "dual_c1_max_in_win_us", "dual_c1_end_after_win", "dual_c1_done", "dual_win_us"):
        r[key] = fnum(k0.get(key))
    r["dual_c1_rc"] = k0.get("dual_c1_rc")
    # the window keys cannot be recomputed (no per-iteration times are kept); check them against other kv keys
    if r["dual_r0"] == 1:
        ok = True
        lm, li = fnum(k0.get("lat_max_us")), k0.get("lat_max_it")
        ok &= lm is not None and r["dual_win_us"] is not None and abs(lm - r["dual_win_us"]) < 0.1
        ok &= li == k0.get("dual_win_it")
        l1m = fnum(k0.get("lat1_max_us"))
        ok &= l1m is not None and r["dual_c1_max_in_win_us"] is not None and r["dual_c1_max_in_win_us"] <= l1m + 0.05
        we, ce = fnum(k0.get("dual_win_end_gt")), fnum(k0.get("dual_c1_last_end_gt"))
        ok &= we is not None and ce is not None and (1 if ce > we else 0) == r["dual_c1_end_after_win"]
        r["dual_kv_consistent"] = int(ok)
    # p50 recomputed from the raw latency samples (gin_ts2.cu latStats: sorted v[(size_t)(0.5*(n-1)+0.5)] / 1e3)
    r["lat_p50_raw_us"] = None
    raw = stem + "_lat_raw.csv.gz"
    if os.path.exists(raw):
        with gzip.open(raw, "rt") as f:
            v = sorted(int(line.split(",")[1]) for line in f if "," in line)
        if v:
            r["lat_p50_raw_us"] = round(v[int(0.5 * (len(v) - 1) + 0.5)] / 1e3, 2)
            r["lat_raw_n"] = len(v)
    return r


# ---------------------------------------------------------------- exclusion and configuration (EXPERIMENT.md 8)
def status_of(r):
    c = r["cell"]
    if r["bind_fail"] == 1:
        return "excluded: bind_fail"
    if c in R0_HOOK and r["n_fires_r0"] == 0:
        return "excluded: no rank-0 fire"
    if c in R1_HOOK and r["n_fires_r1"] == 0:
        return "excluded: no rank-1 fire"
    if c in BOTH_HOOK and (r["n_fires_r0"] == 0 or r["n_fires_r1"] == 0):
        return "excluded: a hook did not fire"
    if r["trigger_miss"] > 0:
        return "excluded: trigger_miss"
    if c in KILL and r["killed"] != 1:
        return "excluded: no kill"
    if c == "pc_dual_f1c0_b" and r["dual_c1_done"] == r["iters"] and r["dual_c1_rc"] == "no error" \
            and r["dual_c1_end_after_win"] == 0:
        return "excluded: context 1 ended before the window"
    if c == "pc_bidirf_conflict_b" and r["r1_q4_in_stall"] != 1:
        return "excluded: r1_q4_in_stall != 1"
    if c == "pc_dual_f1c0_r1c2_b" and r["r1_fire_before_dec"] != 1:
        return "excluded: r1_fire_before_dec != 1"
    return "scored"


def config_problems(r):
    p = []
    c, b = r["cell"], r["build"]
    if r["ts_on_r0"] < 1 or r["ts_on_r1"] < 1 or r["ua_r0"] < 1 or r["ua_r1"] < 1:
        p.append("ts_on/ua")
    if b in ("pc", "pcd", "pr", "prd"):
        if r["pr_mode_r0"] != 1:
            p.append("pr_mode_r0")
        if r["pr_mode_r1"] != (0 if c == "pc_dual_f1c0_r1off_b" else 1):
            p.append("pr_mode_r1")
    if b in ("pc", "pcd"):
        want = 0 if c == "f3_b_nocheck" else 1
        if r["pc_mode_r0"] != want or r["pc_mode_r1"] != want:
            p.append("pc_mode")
    if b in ("pr", "prd") and (r["pc_mode_r0"] is not None or r["pc_mode_r1"] is not None):
        p.append("pair-check line on a pr/prd build")
    if b in ("pcd", "prd") and (r["dual_r0"] != 1 or r["dual_r1"] != 1):
        p.append("dual")
    if b in ("pc", "pr") and (r["dual_r0"] or r["dual_r1"]):
        p.append("dual key on a single-context build")
    want_ctx = {"pc_dual_f1c0_b": ("0", "-"), "pc_dual_f1c0_r1off_b": ("0", "-"), "pr_dual_f1c0_b": ("0", "-"),
                "pc_dual_f3c0_b": ("-", "0"), "pc_dual_f1c0_r1c2_b": ("0", "2"), "pc_bidirf_conflict_b": ("0", "1"),
                "pc_dual_f1all_b": (None, "-"), "f3_b": ("-", None), "f3_b_nocheck": ("-", None)}
    if c in want_ctx:
        w0, w1 = want_ctx[c]
        if w0 != "-" and r["inj_ctx_r0"] != w0:
            p.append("inj_ctx_r0=%s" % r["inj_ctx_r0"])
        if w1 != "-" and r["inj_ctx_r1"] != w1:
            p.append("inj_ctx_r1=%s" % r["inj_ctx_r1"])
    if not (r["bundle"] or "").endswith("/gin_ts2/" + b):
        p.append("bundle %s" % r["bundle"])
    return p


# ---------------------------------------------------------------- acceptance grammar (s2_close 3.2), re-implemented
class _NA:
    def _f(self, *a):
        return False
    __lt__ = __le__ = __gt__ = __ge__ = __eq__ = __ne__ = _f

    def _na(self, *a):
        return self
    __add__ = __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = __truediv__ = __rtruediv__ = __neg__ = __abs__ = _na

    def __bool__(self):
        return False

    def __hash__(self):
        return 0


NA = _NA()


def conv(v):
    if v is None or v == "":
        return NA
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except ValueError:
        return v


def has(v, s):
    return isinstance(v, str) and s in v


def nonempty(v):
    return v is not NA


def _close(s, i):
    depth = 0
    q = False
    for j in range(i, len(s)):
        ch = s[j]
        if ch == '"':
            q = not q
        elif not q and ch == "(":
            depth += 1
        elif not q and ch == ")":
            depth -= 1
            if depth == 0:
                return j
    raise ValueError("unbalanced: " + s)


def evaluate(expr, rows_of, cell):
    """rows_of(key) -> scored rows of that cell. cell: the default cell key for count()."""
    hits = {}
    while True:
        m = re.search(r"\bmedian\(\s*(\w+)\s*,\s*\"([^\"]+)\"\s*\)", expr)
        if not m:
            break
        vals = [conv(r.get(m.group(1))) for r in rows_of(m.group(2))]
        vals = [v for v in vals if v is not NA]
        med = statistics.median(vals) if vals else None
        hits["median(%s, %s)" % (m.group(1), m.group(2))] = med
        expr = expr[:m.start()] + (repr(med) if med is not None else "NA") + expr[m.end():]
    while True:
        i = expr.find("count(")
        if i < 0:
            break
        j = _close(expr, i + len("count"))
        inner = expr[i + len("count("):j]
        n = 0
        miss = []
        for r in rows_of(cell):
            ns = {k: conv(v) for k, v in r.items()}
            ns.update({"has": has, "nonempty": nonempty, "abs": abs, "NA": NA})
            if eval(inner, {"__builtins__": {}}, ns) is True:
                n += 1
            else:
                miss.append(r["trial"])
        hits["count"] = n
        hits["miss"] = miss
        expr = expr[:i] + str(n) + expr[j + 1:]
    val = eval(expr, {"__builtins__": {}}, {"abs": abs, "NA": NA})
    return val is True, hits


# ---------------------------------------------------------------- holds and safety
def hold_windows(res):
    w = {}
    for path in sorted(glob.glob(os.path.join(res, "hold_*.out"))):
        h = os.path.basename(path)[5:-4]
        st = en = None
        for line in open(path, errors="replace"):
            m = re.match(r"(\S+ \S+) \[gpc-[^\]]+\] idle .*running:", line)
            if m:
                st = m.group(1)
            m = re.match(r"(\S+ \S+) \[gpc-[^\]]+\] command exited rc=(\d+)", line)
            if m:
                en = m.group(1)
        w[h] = (st, en)
    return w


def hold_of(t, wins):
    for h, (st, en) in wins.items():
        if st and en and st <= t <= en:
            return h
    return "?"


CMDERR = re.compile(r"(cmd|command)", re.I)
CMDERR2 = re.compile(r"(failed|timeout|leak)", re.I)


def safety(res, h):
    out = {}
    for node in ("rain", "sunny"):
        b = open(os.path.join(res, "mlx5_before-%s_%s.txt" % (h, node)), errors="replace").read().splitlines()
        a = open(os.path.join(res, "mlx5_after-%s_%s.txt" % (h, node)), errors="replace").read().splitlines()
        sb = set(b)
        new = [x for x in a if x not in sb]
        ce = lambda ls: sum(1 for x in ls if "mlx5" in x.lower() and CMDERR.search(x) and CMDERR2.search(x))
        out[node] = (len(b), len(a), len(new), ce(b), ce(a))

    def fw(tag):
        s, qq, rst = 0, None, None
        for line in open(os.path.join(res, "fwcmd_%s.txt" % tag), errors="replace"):
            for k, v in re.findall(r"\b(failed|failed_mbox_status)=(\d+)", line):
                s += int(v)
            m = re.match(r"QUERY_QP n=(\d+)", line)
            if m:
                qq = int(m.group(1))
            m = re.match(r"2RST_QP n=(\d+)", line)
            if m:
                rst = int(m.group(1))
        return s, qq, rst
    out["fw_before"], out["fw_after"] = fw("before-" + h), fw("after-" + h)
    newf = os.path.join(res, "mlx5_new_%s.txt" % h)
    out["mlx5_new_file_lines"] = sum(1 for _ in open(newf)) if os.path.exists(newf) else None
    snaps = [os.path.join(res, "snap_%s-%s.txt" % (x, h)) for x in ("before", "after")]
    out["gpu_proc_lines"] = sum(sum(1 for line in open(p) if "gpu:" in line) for p in snaps if os.path.exists(p))
    return out


# ---------------------------------------------------------------- main
def rng(vals):
    v = [x for x in vals if x is not None]
    if not v:
        return "-"
    return "%g-%g (median %g, n=%d)" % (min(v), max(v), statistics.median(v), len(v))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("res", nargs="?", default=os.path.join(STUDY, "results", "20261008"))
    ap.add_argument("--csv")
    a = ap.parse_args()
    res = a.res
    wins = hold_windows(res)
    rows = []
    for sub in SUBDIRS:
        for meta in sorted(glob.glob(os.path.join(res, sub, "*_meta.txt"))):
            r = trial_row(sub, meta[:-len("_meta.txt")])
            t = r["first_ts"] or r["meta_mtime"]
            r["hold"] = hold_of(t, wins)
            r["hold_by_mtime"] = hold_of(r["meta_mtime"], wins)
            r["status"] = status_of(r)
            r["config"] = ";".join(config_problems(r))
            rows.append(r)
    P = print
    P("# gin-pair-check independent recount, results dir %s" % res)
    P("\n## pre-registration integrity (tag prereg/gin-pair-check-v1)")
    import hashlib, subprocess
    tag = "prereg/gin-pair-check-v1"
    git = lambda *a: subprocess.run(["git", "-C", STUDY] + list(a), capture_output=True, text=True).stdout
    rel = os.path.relpath(STUDY, git("rev-parse", "--show-toplevel").strip())
    P("tag commit %s" % git("rev-parse", tag + "^{commit}").strip())
    sha = hashlib.sha256(open(os.path.join(STUDY, "predictions.csv"), "rb").read()).hexdigest()
    P("sha256(predictions.csv) %s; in PREREG.txt: %s; rows %d" % (
        sha, sha in open(os.path.join(STUDY, "PREREG.txt")).read(),
        len(list(csv.DictReader(open(os.path.join(STUDY, "predictions.csv")))))))
    for f in ("predictions.csv", "PREREG.txt"):
        P("%s identical to the tag: %s" % (f, git("show", "%s:%s/%s" % (tag, rel, f)) ==
                                          open(os.path.join(STUDY, f)).read()))

    def sections(t):
        out, cur = {}, None
        for line in t.splitlines():
            m = re.match(r"^## (\d+)\. ", line)
            if m:
                cur = m.group(1)
                out[cur] = []
            if cur:
                out[cur].append(line)
        return out
    st, sc = sections(git("show", "%s:%s/EXPERIMENT.md" % (tag, rel))), sections(
        open(os.path.join(STUDY, "EXPERIMENT.md")).read())
    P("EXPERIMENT.md sections identical to the tag: %s; changed: %s" % (
        [s for s in ("2", "3", "7", "8") if st.get(s) == sc.get(s)],
        [s for s in sorted(set(st) | set(sc), key=int) if st.get(s) != sc.get(s)]))
    P("trials (meta files): %d; latency runs: %d" % (len(rows), sum(1 for r in rows if r["sub"] == "lat")))
    smoke = os.path.join(os.path.dirname(os.path.normpath(res)), os.path.basename(os.path.normpath(res)) + "_smoke")
    hold0 = os.path.join(smoke, "hold_H0.out")
    P("smoke (not scored): meta files %d; trial result lines in hold_H0.out %s" % (
        len(glob.glob(os.path.join(smoke, "smoke", "*_meta.txt"))),
        sum(1 for line in open(hold0) if " r0rc=" in line) if os.path.exists(hold0) else "-"))
    P("\n## holds (window from hold_<H>.out) and trials per hold")
    for h, (st, en) in wins.items():
        rs = [r for r in rows if r["hold"] == h]
        P("%-5s %s .. %s  trials=%d  cells=%s" % (h, st, en, len(rs), sorted(set(r["key"] for r in rs))))
    bad_h = [r["stem"] for r in rows if r["hold"] != r["hold_by_mtime"] or r["hold"] == "?"]
    P("hold by first log stamp vs by meta mtime disagree or unknown: %s" % (bad_h or "none"))
    P("\n## order within H1, H2, H3 (meta mtime)")
    for h in ("H1", "H2", "H3"):
        rs = sorted((r for r in rows if r["hold"] == h), key=lambda r: (r["meta_mtime"], r["stem"]))
        P("%s: %s" % (h, " ".join("%s#%s" % (r["cell"].replace("pc_dual_", "pcd:").replace("pr_dual_", "prd:"),
                                            r["trial"]) for r in rs)))
    P("\n## parse coverage: raw substring lines vs parsed lines, all rank logs")
    logs = [p for sub in SUBDIRS for p in sorted(glob.glob(os.path.join(res, sub, "*_r[01].log")))]
    pats = [("GIN/FAULT: GDAKI fault fired", R_FIRE), ("NCCL WARN GIN/TS: rank ", R_DEC, ": round "),
            ("GIN/TS: recovered", re.compile(r"GIN/TS: recovered rank=\d+ peer=\d+ role=\w+")),
            ("scope conflict", R_CONF), ("refused the scope of round", R_RERUN), ("checked=", R_CHK),
            ("gate epochs to rank", R_EP), ("qp states to rank", R_QPS), ("GIN/TS: pair reset=", R_PR),
            ("GIN/TS: pair check=", R_PC), ("TEST stall", R_STALL), ("GIN/TS: declined", R_DECL),
            ("device-classified error CQE", R_Q4)]
    cov = []
    for item in pats:
        sub_s, rx = item[0], item[1]
        also = item[2] if len(item) > 2 else None
        raw = parsed = 0
        for p in logs:
            for line in open(p, errors="replace"):
                if sub_s in line and (also is None or also in line):
                    raw += 1
                    parsed += 1 if rx.search(line) else 0
        cov.append("%s %d/%d" % (sub_s.strip(), parsed, raw))
    P("rank logs %d; %s" % (len(logs), "; ".join(cov)))
    P("\n## per cell: planned, scored, set apart; refills")
    keys = sorted(set(r["key"] for r in rows))
    for k in keys:
        rs = [r for r in rows if r["key"] == k]
        sc = [r for r in rs if r["status"] == "scored"]
        ex = [(r["trial"], r["status"], r["hold"]) for r in rs if r["status"] != "scored"]
        holds = sorted(set(r["hold"] for r in sc))
        P("%-28s plan=%s run=%d scored=%d apart=%s holds=%s" % (k, PLAN.get(k), len(rs), len(sc), ex or "-", holds))
    P("cells not in plan: %s; planned cells missing: %s" % (sorted(set(keys) - set(PLAN)), sorted(set(PLAN) - set(keys))))
    P("\n## configuration checks (EXPERIMENT.md 8) and bundle per trial")
    cp = [(r["stem"], r["config"]) for r in rows if r["config"] and r["status"] != "excluded: bind_fail"]
    P("problems on non-bind-fail trials: %s" % (cp or "none"))
    for b in ("pc", "pcd", "pr", "prd"):
        rs = [r for r in rows if r["build"] == b and r["bind_fail"] == 0]
        P("build %-3s trials=%d bundles=%s pair-check line r0/r1=%s dual r0/r1=%s" % (
            b, len(rs), sorted(set(r["bundle"] for r in rs)),
            sorted(set((r["pc_mode_r0"], r["pc_mode_r1"]) for r in rs), key=str),
            sorted(set((r["dual_r0"], r["dual_r1"]) for r in rs), key=str)))
    P("left>0 trials: %s" % ([r["stem"] for r in rows if (r["left"] or 0) > 0] or "none"))
    sc_rows = [r for r in rows if r["status"] == "scored"]

    def rows_of(key, pool=sc_rows):
        return [r for r in pool if r["key"] == key]

    P("\n## predictions (frozen acceptance strings from predictions.csv)")
    preds = list(csv.DictReader(open(os.path.join(STUDY, "predictions.csv"))))
    verdicts = {}
    for p in preds:
        acc = p["acceptance"]
        cells = [c.strip() for c in p["cells"].split(";")]
        short = [c for c in cells if len(rows_of(c)) < PLAN[c]]
        if short:
            verdicts[p["id"]] = "insufficient"
            P("%-3s insufficient data: %s" % (p["id"], short))
            continue
        if acc.startswith("per cell:"):
            ok_all, parts = True, []
            for c in cells:
                ok, hits = evaluate(acc[len("per cell:"):].strip(), rows_of, c)
                ok_all &= ok
                parts.append("%s %d/%d miss=%s" % (c, hits.get("count", -1), len(rows_of(c)), hits.get("miss")))
            verdicts[p["id"]] = "holds" if ok_all else "fails"
            P("%-3s %s  %s" % (p["id"], verdicts[p["id"]].upper(), " | ".join(parts)))
        else:
            ok, hits = evaluate(acc, rows_of, cells[0])
            verdicts[p["id"]] = "holds" if ok else "fails"
            extra = ("count=%d/%d miss=%s" % (hits["count"], len(rows_of(cells[0])), hits["miss"])
                     if "count" in hits else ", ".join("%s=%s" % (k, v) for k, v in hits.items()))
            P("%-3s %s  %s" % (p["id"], verdicts[p["id"]].upper(), extra))
    P("holds %d, fails %d, insufficient %d" % tuple(sum(1 for v in verdicts.values() if v == x)
                                                   for x in ("holds", "fails", "insufficient")))

    P("\n## same-hold variants of T1/T2 (pc cell restricted to hold H2, the fill trial left out)")
    h2 = [r for r in sc_rows if r["hold"] == "H2"]
    for col, lim in (("commit_us_r0", None), ("total_us_r0", None)):
        pc_all = [r[col] for r in rows_of("pc_dual_f1c0_b@pcd")]
        pc_h2 = [r[col] for r in rows_of("pc_dual_f1c0_b@pcd", h2)]
        pr = [r[col] for r in rows_of("pr_dual_f1c0_b@prd")]
        P("%s: pc all scored %s; pc H2 only %s; pr %s" % (col, rng(pc_all), rng(pc_h2), rng(pr)))
        if col == "commit_us_r0":
            P("  T1 ratio all=%.4f  H2-only=%.4f  (limit 1.15)" % (statistics.median(pc_all) / statistics.median(pr),
                                                                  statistics.median(pc_h2) / statistics.median(pr)))
        else:
            P("  T2 diff all=%.1f  H2-only=%.1f us (limit 1000)" % (statistics.median(pc_all) - statistics.median(pr),
                                                                   statistics.median(pc_h2) - statistics.median(pr)))
    fill = [r for r in sc_rows if r["hold"] == "fill"]
    for r in fill:
        P("fill trial %s %s: commit_us_r0=%s total_us_r0=%s check_us_r1=%s c1_in_win=%s c1_max_in_win_us=%s" % (
            r["key"], r["trial"], r["commit_us_r0"], r["total_us_r0"], r["check_us_r1"], r["dual_c1_in_win"],
            r["dual_c1_max_in_win_us"]))

    P("\n## value ranges")
    def show(key, cols):
        rs = rows_of(key)
        for c in cols:
            v = [r[c] for r in rs]
            if all(isinstance(x, (int, float)) or x is None for x in v):
                P("%-28s %-22s %s" % (key, c, rng(v)))
            else:
                P("%-28s %-22s %s" % (key, c, sorted(set(str(x) for x in v))))
    show("f3_b@pc", ["fire_moved_r1", "dec_r0", "refuse_reason_r1", "not_rts_r1", "refuse_check_us_r1", "n_rerun_r0",
                     "rec_r0", "rec_r1", "qpst_r0", "qpst_r1", "ep_r0", "ep_r1", "commit_us_r0", "total_us_r0"])
    show("f3_b_nocheck@pc", ["dec_r0", "n_refused_r1", "n_checked_r1", "rec_r0", "rec_r1", "qpst_r0", "qpst_r1",
                             "ep_r0", "ep_r1"])
    show("pc_dual_f1c0_r1c2_b@pcd", ["r1_fire_lead_ms", "dec_r0", "refuse_reason_r1", "not_rts_r1",
                                     "refuse_check_us_r1", "n_rerun_r0", "rec_r0", "rec_r1", "qpst_r0", "qpst_r1",
                                     "ep_r0", "ep_r1", "n_dec_r1"])
    show("pc_dual_f1c0_b@pcd", ["dec_r0", "rec_r0", "rec_r1", "n_checked_r1", "n_refused_r1", "check_us_r1",
                                "dual_c1_in_win", "dual_c1_max_in_win_us", "dual_c1_end_after_win", "dual_c1_done",
                                "dual_c1_rc", "dual_win_us", "ep_r0", "ep_r1", "qpst_r0", "qpst_r1", "commit_us_r0",
                                "total_us_r0"])
    show("pr_dual_f1c0_b@prd", ["dec_r0", "rec_r0", "rec_r1", "dual_c1_in_win", "dual_c1_max_in_win_us", "ep_r0",
                                "ep_r1", "qpst_r0", "qpst_r1", "commit_us_r0", "total_us_r0"])
    show("pc_dual_f1c0_r1off_b@pcd", ["dec_r0", "refuse_reason_r1", "rec_r0", "rec_r1", "ep_r0", "ep_r1", "qpst_r0",
                                      "qpst_r1"])
    show("pc_bidirf_conflict_b@pc", ["fire_dt_r1_minus_r0_ms", "r1_q4_in_stall", "r1_q4_in_any_stall", "n_stall_r0",
                                     "dec_r0", "dec_r1", "conflict_r1", "conflict_how_r1", "n_refused_r1",
                                     "refuse_reason_r1", "not_rts_r1", "n_rerun_r0", "rec_r0", "rec_r1",
                                     "init_qps_r1", "last_reason_r1", "ep_r0", "ep_r1", "qpst_r0", "qpst_r1",
                                     "decl_r0", "decl_r1"])
    for k in ("f1_b@pc", "bidirf_sym_b@pc", "mt256_f1_b@pc", "pc_dual_f3c0_b@pcd", "pc_dual_f1all_b@pcd"):
        show(k, ["dec_r0", "dec_r1", "rec_r0", "rec_r1", "n_refused_r1", "n_checked_r1", "qpst_r0", "qpst_r1",
                 "ep_r0", "ep_r1"])
    show("f4_b@pc", ["decl_r0", "teardown_r0", "killed", "qpst_r0", "r1rc"])
    show("f2rel_b@pc", ["teardown_r1", "r1rc", "teardown_ms_r1", "r1_outcome", "decl_r0", "decl_r1", "qpst_r0",
                        "qpst_r1"])
    for k in ("lat_pc_on_4k@pc", "lat_pr_on_4k@pr", "lat_pc_on_256k@pc", "lat_pr_on_256k@pr"):
        show(k, ["lat_p50_us", "lat_p50_raw_us", "n_rec_r0", "qpst_r0", "qpst_r1", "ep_r0"])
    P("\n## timings and counts that EXPERIMENT.md 15 states (ms on rank 0's clock unless named us)")
    show("f3_b@pc", ["q4_class_r0", "r1fire_to_r0q4_ms", "r0q4_to_dec_ms", "dec_to_rerun_ms", "dec_to_dec2_ms",
                     "dec_to_resumed_ms", "ref_checked_r1"])
    show("f3_b_nocheck@pc", ["dec_to_resumed_ms"])
    show("pc_dual_f1c0_r1c2_b@pcd", ["n_q4_r1", "r1fire_to_r0q4_ms", "r0fire_to_r0q4_ms", "dec_to_rerun_ms",
                                     "dec_to_dec2_ms", "dec_to_resumed_ms", "dual_c1_in_win", "dual_c1_max_in_win_us"])
    show("pc_dual_f1c0_b@pcd", ["acc_checked_r1", "dec_to_resumed_ms"])
    show("pc_dual_f1c0_r1off_b@pcd", ["ref_checked_r1", "dec_to_rerun_ms", "dec_to_dec2_ms", "dec_to_resumed_ms",
                                      "dual_c1_in_win", "dual_c1_max_in_win_us"])
    show("pc_bidirf_conflict_b@pc", ["refuse_check_us_r1", "ref_checked_r1", "dec_to_rerun_ms", "dec_to_dec2_ms",
                                     "dec_to_resumed_ms", "n_dec_r1"])
    show("pc_dual_f3c0_b@pcd", ["q4_class_r0", "r1fire_to_r0q4_ms", "acc_checked_r1", "check_us_r1"])
    cnt = {c: sum(1 for r in sc_rows if r[c] is not None) for c in ("commit_us_r0", "total_us_r0", "check_us_r1")}
    P("non-blank values over the 110 scored trials: %s (sum %d); scored non-latency trials %d" % (
        cnt, sum(cnt.values()), sum(1 for r in sc_rows if r["sub"] != "lat")))
    dk = [r for r in rows if r.get("dual_kv_consistent") is not None and r["bind_fail"] == 0]
    P("dual-context window keys consistent with lat_max_us/it, lat1_max_us and the end stamps (bind-fail trial left out): %d/%d" % (
        sum(r["dual_kv_consistent"] for r in dk), len(dk)))
    mism = [r["stem"] for r in sc_rows if r["sub"] == "lat" and r["lat_p50_us"] != r["lat_p50_raw_us"]]
    P("latency runs whose kv p50 differs from the raw-sample p50: %s" % (mism or "none"))
    rk = [r for r in sc_rows if r["n_refused_r0"] or r["n_checked_r0"]]
    P("rank 0 responder check lines (any cell): %s" % ([(r["stem"], r["n_checked_r0"], r["n_refused_r0"]) for r in rk]
                                                       or "none"))
    acc_all = [r["check_us_r1"] for r in sc_rows if r["check_us_r1"] is not None]
    P("rank 1 accepted check_us over every scored trial with an accept line: %s" % rng(acc_all))
    by_cell = {}
    for r in sc_rows:
        if r["n_checked_r1"]:
            by_cell.setdefault(r["key"], []).append(r["check_us_r1"])
    for k, v in sorted(by_cell.items()):
        P("  %-28s check_us_r1 %s" % (k, rng(v)))

    P("\n## conflict cell, per trial (rank 1 events in log order; rank 0 events)")
    for r in sorted(rows_of("pc_bidirf_conflict_b@pc"), key=lambda r: int(r["trial"][1:])):
        P("%-4s r1: %s" % (r["trial"], r["events_r1"]))
        P("     r0: %s" % r["events_r0"])
        P("     epochs r0 %s r1 %s; qp states r0 %s r1 %s; fire dt %.1f ms; r1_q4_in_stall %s" % (
            r["ep_r0"], r["ep_r1"], r["qpst_r0"], r["qpst_r1"], r["fire_dt_r1_minus_r0_ms"], r["r1_q4_in_stall"]))

    P("E2 sub-conditions, trials meeting each (of %d):" % len(rows_of("pc_bidirf_conflict_b@pc")))
    acc = next(p["acceptance"] for p in preds if p["id"] == "E2")
    inner = acc[acc.index("count(") + len("count("):acc.rindex(")")]
    for part in inner.split(" and "):
        n = 0
        for r in rows_of("pc_bidirf_conflict_b@pc"):
            ns = {k: conv(v) for k, v in r.items()}
            n += eval(part, {"__builtins__": {}}, ns) is True
        P("  %-28s %d" % (part.strip(), n))

    P("\n## safety per hold")
    for h in wins:
        s = safety(res, h)
        P("%-5s rain lines %d->%d new %d cmd-err %d->%d | sunny lines %d->%d new %d cmd-err %d->%d | "
          "fw failed sum %d->%d, QUERY_QP n +%d, 2RST_QP n +%d | mlx5_new file lines %s | gpu process lines %d" % (
              h, *s["rain"][:2], s["rain"][2], *s["rain"][3:], *s["sunny"][:2], s["sunny"][2], *s["sunny"][3:],
              s["fw_before"][0], s["fw_after"][0], s["fw_after"][1] - s["fw_before"][1],
              s["fw_after"][2] - s["fw_before"][2], s["mlx5_new_file_lines"], s["gpu_proc_lines"]))
        P("      trials %d, left>0 %d" % (sum(1 for r in rows if r["hold"] == h),
                                         sum(1 for r in rows if r["hold"] == h and (r["left"] or 0) > 0)))
    P("STOP_mlx5 present: %s" % os.path.exists(os.path.join(res, "STOP_mlx5")))
    if a.csv:
        keys = []
        for r in rows:
            for k in r:
                if k not in keys:
                    keys.append(k)
        with open(a.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)


if __name__ == "__main__":
    main()
