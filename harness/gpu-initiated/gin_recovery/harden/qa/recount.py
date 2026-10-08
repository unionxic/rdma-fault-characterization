#!/usr/bin/env python3
"""gin-harden: independent recount of the main run (results/20261009) from the raw per-trial files.

usage: python3 qa/recount.py            (prints the report; reads only; writes nothing)

Independence. This script does not import or call the study's scorer chain: it never reads score.py, rows_hd.py,
results/*/SCORE.md, results/*/trials_*.csv or ../s2_close/score.py. Every column is parsed again from
<build>/<cell>_n<k>_{meta.txt,r0.kv,r1.kv,r0.log,r1.log,kill.out,mute.out,lat_raw.csv.gz}, following EXPERIMENT.md
section 3.1. The legacy columns (rows.py, rows_extra.py, rows_pc.py, rows_ow.py) follow the definitions those files
state (EXPERIMENT.md 3.1 says the definitions are theirs); the new columns follow the 3.1 table and the log formats of
3.1 only. The acceptance rules of predictions.csv are evaluated by the evaluator below (section 3.2 grammar of
../s2_close/EXPERIMENT.md: count, None rule, has, nonempty, median, abs, "per cell:").

Read-only: files are opened for reading; git is only asked for blobs of the tag (git cat-file), which writes nothing and
runs no clean filter.
"""
import gzip, hashlib, math, os, re, statistics, subprocess, sys, csv, io

QA = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(QA)
RES = os.path.join(STUDY, "results", "20261009")
PILOT = os.path.join(STUDY, "results", "20261009_pilot")
TAG = "prereg/gin-harden-v1"
REL = "harness/gpu-initiated/gin_recovery/harden"
BUILDS = ["hd", "hdp", "ow", "ow2", "stk"]

# ---------------------------------------------------------------------------------------------------------------
# plan (EXPERIMENT.md section 7)
REG = ["f1_b", "f3_b", "bidirf_sym_b", "f4_b", "f2rel_b", "pc_dual_f1c0_r1c2_b", "rc_mute8_f1_b", "rc_mutekill_b",
       "ow_r1in_f1_b", "ow_r0in_f1r1_b", "ow_kill0_b", "ow_hello_f1_b"]
NEW = ["hd_ref1_f1_b", "hd_ref2_f1_b", "hd_nonce_f1_b", "hd_rround_f1_b", "hd_rxdeath_b", "hd_hog_f1_b",
       "hd_fwslow_f1_b", "hd_copystall_f1_b", "hd_repost_f1_b", "hd_esc_f1_b", "hd_shrink_b"]
PLAN = {}
for c in REG:
    PLAN[c + "@hd"] = 5
for c in NEW:
    PLAN[c + "@hd"] = 10
for k in ["hd_rround_f1_b@ow", "hd_rxdeath_b@ow", "hd_fwslow_f1_b@ow", "hd_esc_f1_b@ow", "hd_shrink_b@ow2"]:
    PLAN[k] = 5
for c in ["lat_4k", "lat_256k"]:
    for b in ["hdp", "ow", "stk"]:
        PLAN[c + "@" + b] = 5
PLAN["hdp_kill_b@hdp"] = 5
PLAN["hdp_mute_b@hdp"] = 5
PLAN["to20_f3_b@hd"] = 5
PLAN["to20_f3_t@hd"] = 3

# section 8 cell classes
HOOK_R0 = {"f1_b", "rc_mute8_f1_b", "ow_r1in_f1_b", "ow_hello_f1_b", "hd_ref1_f1_b", "hd_nonce_f1_b", "hd_rround_f1_b",
           "hd_hog_f1_b", "hd_fwslow_f1_b", "hd_copystall_f1_b", "hd_repost_f1_b", "hd_esc_f1_b"}
# hd_ref2_f1_b is a rank 0 hook cell in cells.sh, but its hook requirement was dropped before the tag (EXPERIMENT.md 3,
# "pilot 뒤 확정": the trial ends at the death decline before the 12 s hook)
HOOK_R0_EXEMPT = {"hd_ref2_f1_b"}
HOOK_R1 = {"f3_b", "ow_r0in_f1r1_b", "to20_f3_b", "to20_f3_t"}
HOOK_BOTH = {"bidirf_sym_b", "pc_dual_f1c0_r1c2_b"}
KILL_R1 = {"f4_b", "rc_mutekill_b", "hd_shrink_b", "hdp_kill_b"}
KILL_R0 = {"ow_kill0_b", "hd_rxdeath_b"}
MUTE_BOTH = {"rc_mute8_f1_b", "rc_mutekill_b", "ow_kill0_b", "ow_hello_f1_b", "hd_ref1_f1_b", "hd_ref2_f1_b",
             "hd_nonce_f1_b"}
MUTE_R1 = {"ow_r1in_f1_b", "hd_rround_f1_b"}
MUTE_R0 = {"ow_r0in_f1r1_b"}

# ---------------------------------------------------------------------------------------------------------------
# parsing


def kvparse(text):
    """key=value pairs; a value runs up to the next ' key=' (values may hold blanks, e.g. error strings)."""
    d = {}
    for line in text.splitlines():
        keys = [m for m in re.finditer(r"(?:(?<=\s)|^)(\w+)=", line)]
        # keep only keys whose '=' is not inside a previous value without blanks (e.g. r0env=A=B): a key must start
        # at the line start or after a blank
        for i, m in enumerate(keys):
            end = keys[i + 1].start() if i + 1 < len(keys) else len(line)
            d[m.group(1)] = line[m.end():end].strip().strip('"')
    return d


def readf(path):
    if not os.path.exists(path):
        return None
    with open(path, errors="replace") as f:
        return f.read()


def fnum(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


F = {  # log line patterns (message part)
    "fire": re.compile(r"GIN/FAULT: GDAKI fault fired .*?(?:context=(\d+) )?fire_mono_ms=([\d.]+)"),
    "trigmiss": re.compile(r"GIN/FAULT: shot 1 trigger not reached"),
    "q4": re.compile(r"GIN/Q4: device-classified error CQE .*?\bclass=(\S+) .*\bmono_ms=([\d.]+)\s*$"),
    "dump": re.compile(r"GIN/Q4: device wait-timeout dump "),
    "rec": re.compile(r"GIN/TS: recovered rank="),
    "decl": re.compile(r'GIN/TS: declined rank=\d+ peer=\d+ reason="([^"]*)" .*?mono_ms=([\d.]+)'),
    "ts_on": re.compile(r"GIN/TS: transparent recovery ON rank="),
    "harden": re.compile(r"GIN/TS: harden=1 rank=(\d+) .*\bproduction=(\d)"),
    "hknobs": re.compile(r"GIN/TS: TEST harden knobs rank=\d+ listen_gap=(\S+) bad_nonce=(\S+) fw_delay=(\S+) "
                         r"copy_stall=(\S+) bad_repost=(\S+)"),
    "sknobs": re.compile(r"GIN/TS: TEST socket knobs rank=\d+ uto_ms=(\d+) refuse_hello=(\d+)"),
    "ua": re.compile(r"GIN/TS: user devComm abort flag set rank="),
    "owmode": re.compile(r"GIN/TS: helper liveness oneway=(\d) rank="),
    "prmode": re.compile(r"GIN/TS: pair reset=(\d) rank="),
    "pcmode": re.compile(r"GIN/TS: pair check=(\d) rank="),
    "mute_on": re.compile(r"GIN/TS: TEST socket mute on rank=\d+ peers=\d+ mono_ms=([\d.]+)"),
    "mute_off": re.compile(r"GIN/TS: TEST socket mute off rank=\d+ peers=\d+ mono_ms=([\d.]+)"),
    "close": re.compile(r"GIN/TS: rank \d+: socket to rank \d+ closed cause=(\S+) mono_ms=([\d.]+)(?: liveness=(\w+))?"),
    "reconn": re.compile(r"GIN/TS: rank \d+: socket to rank \d+ reconnected gen=\d+ attempts=\d+ mono_ms=([\d.]+)"),
    "notacc": re.compile(r"GIN/TS: rank \d+: re-dial to rank \d+ not accepted \("),
    "redial_ref": re.compile(r"GIN/TS: rank \d+: re-dial to rank \d+ refused \(ECONNREFUSED\) mono_ms=([\d.]+)"),
    "probe_ref": re.compile(r"GIN/TS: rank \d+: probe of rank \d+ refused \(ECONNREFUSED\) mono_ms=([\d.]+)"),
    "probe_ans": re.compile(r"GIN/TS: rank \d+: probe of rank \d+ answered mono_ms="),
    "probe_noans": re.compile(r"GIN/TS: rank \d+: probe of rank \d+ not answered by the peer"),
    "refuse_test": re.compile(r"GIN/TS: TEST refused a reconnect HELLO from rank \d+ gen=\d+ mono_ms="),
    "wait": re.compile(r"GIN/TS: rank \d+: reconnect wait for rank \d+ ended=(\w+) wait_ms=([\d.]+) mono_ms="),
    "judged": re.compile(r"GIN/TS: rank \d+: rank \d+ judged dead \(cause=(\w+)\) mono_ms=([\d.]+)"),
    "left": re.compile(r"GIN/TS: rank \d+: rank \d+ left the communicator \(BYE\)"),
    "nonce_ref": re.compile(r"GIN/TS: rank \d+: refused a reconnect from rank \d+ \(nonce mismatch\)"),
    "badnonce": re.compile(r"GIN/TS: TEST sent a wrong nonce in (?:HELLO|PROBE)"),
    "cancel": re.compile(r"GIN/TS: rank \d+: round \d+ (?:with rank \d+ cancelled \(|from rank \d+ cancelled before the commit)"),
    "fwdog": re.compile(r"GIN/TS: watchdog rank=\d+: firmware command phase (\S+) has run ([\d.]+) ms"),
    "uarel": re.compile(r"GIN/TS: user devComm waits released rank=\d+ why=(\S+) mono_ms=([\d.]+)"),
    "copyto": re.compile(r"GIN/TS: rank \d+: device-state copy \(.*\) not complete after"),
    "esc": re.compile(r"GIN/TS: escalated rank=\d+: "),
    "orphan": re.compile(r"GIN/TS: communicator teardown rank=\d+: the recovery helper did not stop within (\d+) ms .*?"
                         r"firmware phase (\S+), current command for ([\d.]+) ms"),
    "planrej": re.compile(r"GIN/TS: rank \d+: re-post plan to rank \d+ rejected at qp (\d+) of (\d+) \(.*\); nothing "
                          r"re-posted mono_ms=([\d.]+)"),
    "initround": re.compile(r"GIN/TS: rank \d+: round \d+ peer \d+ scope=\S+ qps=\d+ reason=\w+ mono_ms=([\d.]+)"),
    "rerun": re.compile(r"GIN/TS: rank \d+: peer \d+ refused the scope of round \d+; rerunning as a full reset"),
    "reqcheck": re.compile(r"GIN/TS: rank \d+: REQ round \d+ from rank \d+ scope=\S+ checked=\d+ not_rts=\d+ check_us=[\d.]+ "
                           r"(accepted|refused)"),
    "qpst": re.compile(r"GIN/TS: rank \d+ qp states to rank \d+: \[([^\]]*)\]"),
    "cuda": re.compile(r"illegal address|illegal memory access|unspecified launch failure", re.I),
    "bind": re.compile(r"bind: Address already in use"),
}
RE_RECKV = re.compile(r"([\w/]+)=(\[[^\]]*\]|\S+)")


def scanlog(path):
    o = {k: [] for k in ["fire", "q4", "rec", "decl", "close", "reconn", "redial_ref", "probe_ref", "judged", "uarel",
                         "fwdog", "planrej", "initround", "mute_on", "mute_off", "wait", "orphan", "reqcheck",
                         "copyto_t", "helper_idle_wd"]}
    cnt = {k: 0 for k in ["trigmiss", "dump", "ts_on", "ua", "notacc", "probe_ans", "probe_noans", "refuse_test", "left",
                          "nonce_ref", "badnonce", "cancel", "copyto", "esc", "rerun", "cuda", "bind"]}
    o["cnt"] = cnt
    o["harden"], o["hknobs"], o["sknobs"], o["owmode"], o["prmode"], o["pcmode"], o["qpst"] = (None,) * 7
    o["present"] = False
    txt = readf(path)
    if txt is None:
        return o
    o["present"] = True
    for line in txt.splitlines():
        if F["cuda"].search(line):
            cnt["cuda"] += 1
        if F["bind"].search(line):
            cnt["bind"] += 1
        if "GIN/" not in line:
            continue
        m = F["fire"].search(line)
        if m:
            o["fire"].append((float(m.group(2)), m.group(1)))
            continue
        if F["trigmiss"].search(line):
            cnt["trigmiss"] += 1
        m = F["q4"].search(line)
        if m:
            o["q4"].append((m.group(1), float(m.group(2))))
            continue
        if F["dump"].search(line):
            cnt["dump"] += 1
            continue
        if F["rec"].search(line):
            o["rec"].append(dict(RE_RECKV.findall(line.split("GIN/TS: recovered", 1)[1])))
            continue
        m = F["decl"].search(line)
        if m:
            o["decl"].append((m.group(1), float(m.group(2))))
            continue
        if F["ts_on"].search(line):
            cnt["ts_on"] += 1
        m = F["harden"].search(line)
        if m and o["harden"] is None:
            o["harden"] = m.group(2)
        m = F["hknobs"].search(line)
        if m and o["hknobs"] is None:
            o["hknobs"] = m.groups()
        m = F["sknobs"].search(line)
        if m and o["sknobs"] is None:
            o["sknobs"] = m.groups()
        if F["ua"].search(line):
            cnt["ua"] += 1
        for k in ("owmode", "prmode", "pcmode"):
            m = F[k].search(line)
            if m and o[k] is None:
                o[k] = m.group(1)
        for k in ("mute_on", "mute_off", "reconn", "redial_ref", "probe_ref"):
            m = F[k].search(line)
            if m:
                o[k].append(float(m.group(1)))
        m = F["close"].search(line)
        if m:
            o["close"].append((m.group(1), float(m.group(2)), m.group(3)))
        for k in ("notacc", "probe_ans", "probe_noans", "refuse_test", "left", "nonce_ref", "badnonce", "cancel",
                  "copyto", "esc", "rerun"):
            if F[k].search(line):
                cnt[k] += 1
        m = F["wait"].search(line)
        if m:
            o["wait"].append((m.group(1), float(m.group(2))))
        m = F["judged"].search(line)
        if m:
            o["judged"].append((m.group(1), float(m.group(2))))
        m = F["fwdog"].search(line)
        if m:
            o["fwdog"].append((m.group(1), float(m.group(2))))
        m = F["uarel"].search(line)
        if m:
            o["uarel"].append((m.group(1), float(m.group(2))))
        m = F["orphan"].search(line)
        if m:
            o["orphan"].append((float(m.group(1)), m.group(2), float(m.group(3))))
        elif "the recovery helper did not stop within" in line:
            o["orphan"].append((None, None, None))
        m = F["planrej"].search(line)
        if m:
            o["planrej"].append((int(m.group(1)), int(m.group(2)), float(m.group(3))))
        if F["copyto"].search(line):
            m = re.search(r"mono_ms=([\d.]+)", line)
            o["copyto_t"].append(float(m.group(1)) if m else None)
        if "recovery helper is not running" in line:
            m = re.search(r"mono_ms=([\d.]+)", line)
            o["helper_idle_wd"].append(float(m.group(1)) if m else None)
        m = F["initround"].search(line)
        if m:
            o["initround"].append(float(m.group(1)))
        if F["rerun"].search(line):
            cnt["rerun"] += 1
        m = F["reqcheck"].search(line)
        if m:
            o["reqcheck"].append(m.group(1))
        m = F["qpst"].search(line)
        if m and o["qpst"] is None:
            o["qpst"] = [x.strip() for x in m.group(1).split(",")]
    return o


def trial(build, stem, root=RES):
    base = os.path.join(root, build, stem)
    meta = kvparse(readf(base + "_meta.txt") or "")
    k = [kvparse(readf(base + "_r%d.kv" % r) or "") for r in (0, 1)]
    lg = [scanlog(base + "_r%d.log" % r) for r in (0, 1)]
    kill = kvparse(readf(base + "_kill.out") or "")
    mute_txt = readf(base + "_mute.out")
    mute = kvparse(mute_txt or "")
    done = []
    for r in (0, 1):
        for line in (readf(base + "_r%d.log" % r) or "").splitlines():
            if "DONE outcome" in line:
                done.append(re.sub(r"^.*\] ", "", line))
    t = {"build": build, "stem": stem, "cell": meta.get("cell", ""), "trial": meta.get("trial", ""),
         "n": int(meta.get("trial", "n0")[1:] or 0), "meta": meta, "k": k, "lg": lg, "kill": kill, "mute": mute,
         "mute_present": mute_txt is not None, "lat_raw": base + "_lat_raw.csv.gz", "done": done,
         "kill_txt": (readf(base + "_kill.out") or "").strip()}
    t["key"] = t["cell"] + "@" + build
    t["c"] = columns(t)
    return t


def rank_ok(kv, iters, sender, receiver):
    if kv.get("outcome") != "ok" or kv.get("async_first") != "none":
        return False
    if sender and not (kv.get("tx_done") == str(iters) and kv.get("tx_rc") == "no error"):
        return False
    if receiver and not (kv.get("rx_done") == str(iters) and kv.get("rx_rc") == "no error" and
                         kv.get("dev_bad_slots") == "0" and kv.get("host_bad_slots") == "0" and
                         kv.get("signal_exact") == "1"):
        return False
    return True


def columns(t):
    m, k0, k1, l0, l1 = t["meta"], t["k"][0], t["k"][1], t["lg"][0], t["lg"][1]
    L = (l0, l1)
    K = (k0, k1)
    c = {}
    off = fnum(k0.get("clock_offset_ms"))  # rank 1 - rank 0
    iters = int(m.get("iters", "0") or 0)
    bidir = m.get("app") == "bidir"
    # ---- rows.py
    c["transparent_ok"] = int(rank_ok(k0, iters, True, bidir) and rank_ok(k1, iters, bidir, True))
    c["r0_outcome"], c["r1_outcome"] = k0.get("outcome"), k1.get("outcome")
    c["tx_rc"], c["rx_rc"], c["rx_rc_r0"] = k0.get("tx_rc"), k1.get("rx_rc"), k0.get("rx_rc")
    c["r0_async"], c["r1_async"] = k0.get("async_first"), k1.get("async_first")
    for r in (0, 1):
        c["decl_r%d" % r] = ";".join(x[0] for x in L[r]["decl"])
        c["rec_init_r%d" % r] = sum(1 for x in L[r]["rec"] if x.get("role") == "initiator")
        c["teardown_r%d" % r] = K[r].get("abort_ret")
        c["teardown_ms_r%d" % r] = K[r].get("teardown_ms")
        c["ts_on_r%d" % r] = L[r]["cnt"]["ts_on"]
        c["n_fires_r%d" % r] = len(L[r]["fire"])
        c["ua_r%d" % r] = L[r]["cnt"]["ua"]
    c["lat_p50_us"] = k0.get("lat_p50_us")
    c["q4_class_r0"] = ";".join(x[0] for x in l0["q4"][:4])
    c["trigger_miss"] = l0["cnt"]["trigmiss"] + l1["cnt"]["trigmiss"]
    c["bind_fail"] = int(l0["cnt"]["bind"] > 0)
    c["killed"] = 1 if t["kill"].get("kill_mono_ms") else 0
    c["r0_killed"] = 1 if (t["kill"].get("kill_mono_ms") and t["kill"].get("rank") == "0") else 0
    kill_ms = fnum(t["kill"].get("kill_mono_ms"))
    fires = []
    if l0["fire"]:
        fires.append(l0["fire"][0][0])
    if l1["fire"] and off is not None:
        fires.append(l1["fire"][0][0] - off)
    fault = min(fires) if fires else None
    if fault is None and kill_ms is not None:
        # rank 1 kill: kill.out is sunny's clock; rank 0 kill: rain's clock (rows.py subtracts the offset in both cases;
        # this column is used only by the IB timeout cells, which have a hook, so the difference does not matter)
        fault = kill_ms if c["r0_killed"] else (kill_ms - off if off is not None else None)
    c["fault_mono_r0"] = fault
    # ---- rows_pc.py
    for r in (0, 1):
        c["n_rec_r%d" % r] = len(L[r]["rec"])
        c["n_notrts_r%d" % r] = (sum(1 for x in L[r]["qpst"] if x != "3") if L[r]["qpst"] is not None else None)
        c["inj_ctx_r%d" % r] = (L[r]["fire"][0][1] or "") if L[r]["fire"] else None
        c["pr_mode_r%d" % r] = L[r]["prmode"]
        c["pc_mode_r%d" % r] = L[r]["pcmode"]
    c["n_refused_r1"] = sum(1 for x in l1["reqcheck"] if x == "refused")
    c["n_rerun_r0"] = l0["cnt"]["rerun"]
    # ---- rows_ow.py
    unmute = []
    for r in (0, 1):
        lr = L[r]
        c["ow_mode_r%d" % r] = lr["owmode"]
        c["knob_uto_r%d" % r] = lr["sknobs"][0] if lr["sknobs"] else None
        c["knob_refuse_r%d" % r] = lr["sknobs"][1] if lr["sknobs"] else None
        c["n_mute_on_r%d" % r] = len(lr["mute_on"])
        c["mute_off_ms_r%d" % r] = lr["mute_off"][0] if lr["mute_off"] else None
        cl = [x for x in lr["close"] if x[2] is not None]  # rows_ow requires the liveness field
        c["close1_cause_r%d" % r] = cl[0][0] if cl else None
        c["close1_lv_r%d" % r] = cl[0][2] if cl else None
        c["close1_ms_r%d" % r] = cl[0][1] if cl else None
        dead = [x for x in cl if x[2] == "dead"]
        c["n_dead_r%d" % r] = len(dead)
        c["n_reconn_r%d" % r] = len(lr["reconn"])
        c["reconn_ms_r%d" % r] = lr["reconn"][0] if lr["reconn"] else None
        c["wait_end_r%d" % r] = lr["wait"][0][0] if lr["wait"] else None
        c["q4_ms_r%d" % r] = lr["q4"][0][1] if lr["q4"] else None
        c["decl_ms_r%d" % r] = lr["decl"][0][1] if lr["decl"] else None
        if lr["mute_off"]:
            if r == 0:
                unmute.append(lr["mute_off"][0])
            elif off is not None:
                unmute.append(lr["mute_off"][0] - off)
    c["n_notacc_r0"] = l0["cnt"]["notacc"]
    c["n_probe_ref_r1"] = len(l1["probe_ref"])
    c["n_refuse_test_r1"] = l1["cnt"]["refuse_test"]
    c["unmute_ms"] = max(unmute) if unmute else None
    rc0 = c["reconn_ms_r0"]
    rc1 = (c["reconn_ms_r1"] - off) if (c["reconn_ms_r1"] is not None and off is not None) else None
    c["reconn_after_unmute_ms_r0"] = (rc0 - c["unmute_ms"]) if (rc0 is not None and c["unmute_ms"] is not None) else None
    c["reconn_after_unmute_ms_r1"] = (rc1 - c["unmute_ms"]) if (rc1 is not None and c["unmute_ms"] is not None) else None
    # ---- new columns (EXPERIMENT.md 3.1 table)
    for r in (0, 1):
        lr, kr = L[r], K[r]
        c["hd_on_r%d" % r] = 1 if lr["harden"] is not None else 0
        c["prod_r%d" % r] = lr["harden"]
        hk = lr["hknobs"]
        c["hk_gap_r%d" % r] = hk[0] if hk else None
        c["hk_badnonce_r%d" % r] = hk[1] if hk else None
        c["hk_fwdelay_r%d" % r] = hk[2] if hk else None
        c["hk_copystall_r%d" % r] = hk[3] if hk else None
        c["hk_badrepost_r%d" % r] = hk[4] if hk else None
        c["n_judged_r%d" % r] = len(lr["judged"])
        c["judged_cause_r%d" % r] = lr["judged"][0][0] if lr["judged"] else None
        c["judged_ms_r%d" % r] = lr["judged"][0][1] if lr["judged"] else None
        c["n_left_r%d" % r] = lr["cnt"]["left"]
        c["n_refused_dial_r%d" % r] = len(lr["redial_ref"])
        c["n_probe_refused_r%d" % r] = len(lr["probe_ref"])
        refs = sorted(lr["redial_ref"] + lr["probe_ref"])
        c["refusal1_ms_r%d" % r] = refs[0] if refs else None
        c["refusal_span_ms_r%d" % r] = ((c["judged_ms_r%d" % r] - refs[0])
                                        if (refs and c["judged_ms_r%d" % r] is not None) else None)
        c["n_nonce_ref_r%d" % r] = lr["cnt"]["nonce_ref"]
        c["n_badnonce_sent_r%d" % r] = lr["cnt"]["badnonce"]
        c["n_probe_noans_r%d" % r] = lr["cnt"]["probe_noans"]
        c["n_cancel_r%d" % r] = lr["cnt"]["cancel"]
        init = [x for x in lr["rec"] if x.get("role") == "initiator"]
        sr = [fnum(x.get("sock_retries")) for x in init if fnum(x.get("sock_retries")) is not None]
        c["sock_retries_max_r%d" % r] = max(sr) if sr else None
        c["rec_total_us_r%d" % r] = fnum(init[0].get("total_us")) if init else None
        c["n_fwdog_r%d" % r] = len(lr["fwdog"])
        c["fwdog_phase_r%d" % r] = lr["fwdog"][0][0] if lr["fwdog"] else None
        c["fwdog_run_ms_r%d" % r] = lr["fwdog"][0][1] if lr["fwdog"] else None
        c["n_uarel_r%d" % r] = len(lr["uarel"])
        c["uarel_why_r%d" % r] = lr["uarel"][0][0] if lr["uarel"] else None
        c["uarel_ms_r%d" % r] = lr["uarel"][0][1] if lr["uarel"] else None
        c["n_copyto_r%d" % r] = lr["cnt"]["copyto"]
        c["n_esc_r%d" % r] = lr["cnt"]["esc"]
        c["n_orphan_r%d" % r] = len(lr["orphan"])
        c["n_dump_r%d" % r] = lr["cnt"]["dump"]
        pr = lr["planrej"]
        c["n_plan_rej_r%d" % r] = len(pr)
        c["plan_rej_qp_r%d" % r] = pr[0][0] if pr else None
        c["plan_rej_total_r%d" % r] = pr[0][1] if pr else None
        c["plan_rej_ms_r%d" % r] = pr[0][2] if pr else None
        c["n_init_round_r%d" % r] = len(lr["initround"])
        for key in ["api", "rounds", "recovered", "declined", "reconnects", "deaths", "escalations", "cancelled",
                    "fw_overruns", "copy_timeouts", "contexts"]:
            c["rs_%s_r%d" % (key, r)] = kr.get("rs_" + key)
        c["rx_phantom_r%d" % r] = kr.get("rx_phantom")
        c["post_abort_rx_phantom_r%d" % r] = kr.get("post_abort_rx_phantom")
        for key in ["ms", "sms", "blocks", "launch_after_launch_ms", "launch_err"]:
            c["hog_%s_r%d" % (key, r)] = kr.get("hog_" + key)
    c["plan_rej_init_r0"] = (None if not l0["planrej"] else
                             (1 if any(x < l0["planrej"][0][2] for x in l0["initround"]) else 0))
    for key in ["kernel_done_before_shrink", "shrink_rc", "shrink_ms", "newcomm", "newcomm_nranks", "allreduce_rc",
                "check_ok", "old_kernel_done"]:
        c["ho_" + key] = k0.get("ho_" + key)
    la0 = fnum(k0.get("launch_mono_ms"))
    c["fault_after_launch_r0_ms"] = (l0["fire"][0][0] - la0) if (l0["fire"] and la0 is not None) else None
    c["q4_after_fault_ms_r0"] = ((c["q4_ms_r0"] - fault) if (c["q4_ms_r0"] is not None and fault is not None) else None)
    c["decl_after_q4_ms_r0"] = ((c["decl_ms_r0"] - c["q4_ms_r0"])
                                if (c["decl_ms_r0"] is not None and c["q4_ms_r0"] is not None) else None)
    la1, km1 = fnum(k1.get("launch_mono_ms")), fnum(k1.get("kernel_ms"))
    a1 = fnum(k1.get("async_first_ms_after_launch"))
    c["release_after_kill_ms_r1"] = c["async_after_kill_ms_r1"] = c["decl_after_kill_ms_r0"] = None
    if c["r0_killed"] and kill_ms is not None and off is not None:
        kill1 = kill_ms + off  # rank 0's kill on rank 1's clock
        if la1 is not None and km1 is not None:
            c["release_after_kill_ms_r1"] = la1 + km1 - kill1
        if la1 is not None and a1 is not None and k1.get("async_first") not in (None, "", "none") and a1 >= 0:
            c["async_after_kill_ms_r1"] = la1 + a1 - kill1
    if c["killed"] and not c["r0_killed"] and kill_ms is not None and off is not None and c["decl_ms_r0"] is not None:
        c["decl_after_kill_ms_r0"] = c["decl_ms_r0"] - (kill_ms - off)
    cl1 = l1["close"][0][1] if l1["close"] else None
    c["r1close_after_q4_ms"] = ((cl1 - off - c["q4_ms_r0"])
                                if (cl1 is not None and off is not None and c["q4_ms_r0"] is not None) else None)
    # mute (production build, run_trial_hd.sh MGMT_MUTE)
    mu = t["mute"]
    c["mute_applied"] = (1 if (t["mute_present"] and "mute_skipped" not in mu and mu.get("mute_on_mono_ms")) else
                         (0 if m.get("mgmt_mute") else None))
    c["mute_rules_on"] = mu.get("mute_rules_on")
    c["mute_rules_left"] = mu.get("mute_rules_left")
    c["left_rules"] = m.get("left_rules")
    c["r0rc"], c["r1rc"], c["left"] = m.get("r0rc"), m.get("r1rc"), m.get("left")
    return c


# ---------------------------------------------------------------------------------------------------------------
# section 8: exclusions and configuration checks


def exclusion(t):
    c, cell, b = t["c"], t["cell"], t["build"]
    if c["bind_fail"] == 1:
        return "bind_fail"
    if cell in HOOK_R0 and c["n_fires_r0"] == 0:
        return "fault not applied (no rank 0 hook fire)"
    if cell in HOOK_R1 and c["n_fires_r1"] == 0:
        return "fault not applied (no rank 1 hook fire)"
    if cell in HOOK_BOTH and (c["n_fires_r0"] == 0 or c["n_fires_r1"] == 0):
        return "fault not applied (a rank without hook fire)"
    if c["trigger_miss"] > 0:
        return "fault not applied (trigger_miss)"
    if cell in KILL_R1 and c["killed"] != 1:
        return "fault not applied (killed != 1)"
    if cell in KILL_R0 and c["r0_killed"] != 1:
        return "fault not applied (r0_killed != 1)"
    if cell == "hdp_mute_b" and c["mute_applied"] != 1:
        return "fault not applied (mute_applied != 1)"
    if cell == "ow_r0in_f1r1_b":
        if c["close1_ms_r1"] is None or (c["q4_ms_r1"] is not None and c["q4_ms_r1"] < c["close1_ms_r1"]):
            return "order not applied (ow_r0in)"
    if cell == "rc_mutekill_b":
        cl = t["lg"][0]["close"]
        if not cl or (c["q4_ms_r0"] is not None and c["q4_ms_r0"] < cl[0][1]):
            return "order not applied (rc_mutekill)"
    if cell == "ow_kill0_b":
        cl = t["lg"][1]["close"]
        if not cl or (c["q4_ms_r1"] is not None and c["q4_ms_r1"] < cl[0][1]):
            return "order not applied (ow_kill0)"
    if cell == "hd_rround_f1_b":
        x = c["r1close_after_q4_ms"]
        if x is None or not (0 < x < 4000):
            return "order not applied (reset not inside the round: r1close_after_q4_ms=%s)" % x
    if cell == "hd_repost_f1_b" and c["n_plan_rej_r0"] >= 1 and c["plan_rej_init_r0"] == 0:
        return "order not applied (rank 0 rejected as the responder)"
    if b in ("hd", "hdp") and not (cell == "hd_fwslow_f1_b" and b == "hd"):
        fo = [fnum(c["rs_fw_overruns_r0"]) or 0, fnum(c["rs_fw_overruns_r1"]) or 0]
        if c["n_fwdog_r0"] or c["n_fwdog_r1"] or any(fo):
            return "firmware overrun (n_fwdog=%s/%s rs_fw_overruns=%s/%s)" % (c["n_fwdog_r0"], c["n_fwdog_r1"], *fo)
    return None


def config_check(t):
    """section 8 '설정 확인' (a failure stops the block; it is not an exclusion). Returns a list of failures."""
    c, cell, b = t["c"], t["cell"], t["build"]
    bad = []
    if c["bind_fail"]:
        return bad
    ranks = [0, 1]
    if b in ("hd",):
        for r in ranks:
            if c["prod_r%d" % r] != "0":
                bad.append("r%d harden line production=0 missing (%s)" % (r, c["prod_r%d" % r]))
            if c["ts_on_r%d" % r] < 1:
                bad.append("r%d no transparent recovery ON line" % r)
            if c["ua_r%d" % r] < 1:
                bad.append("r%d no user devComm abort word line" % r)
            if c["ow_mode_r%d" % r] != "1":
                bad.append("r%d oneway=1 missing" % r)
    elif b == "hdp":
        for r in ranks:
            if c["hd_on_r%d" % r] != 0:
                bad.append("r%d harden line visible at WARN" % r)
        if c["rs_api_r0"] != "1" or (fnum(c["rs_contexts_r0"]) or 0) < 1:
            bad.append("r0 rs_api/rs_contexts")
    elif b in ("ow", "ow2"):
        for r in ranks:
            if c["ow_mode_r%d" % r] != "1" or c["ts_on_r%d" % r] < 1 or c["ua_r%d" % r] < 1 or c["hd_on_r%d" % r]:
                bad.append("r%d ow/ow2 start lines (oneway=%s ts_on=%s ua=%s harden=%s)" % (
                    r, c["ow_mode_r%d" % r], c["ts_on_r%d" % r], c["ua_r%d" % r], c["hd_on_r%d" % r]))
    elif b == "stk":
        for r in ranks:
            if c["ow_mode_r%d" % r] is not None or c["ts_on_r%d" % r] or c["ua_r%d" % r] or c["hd_on_r%d" % r]:
                bad.append("r%d stk shows recovery lines" % r)
    # old test-switch lines (gin-oneway 8 rule, plus hd_rround_f1_b rank 0 uto_ms=20000)
    exp_uto = {"ow_r1in_f1_b": (0, "20000"), "ow_r0in_f1r1_b": (1, "20000"), "hd_rround_f1_b": (0, "20000")}
    if cell in exp_uto:
        r, v = exp_uto[cell]
        if c["knob_uto_r%d" % r] != v or c["knob_uto_r%d" % (1 - r)] is not None:
            bad.append("socket knob line (uto)")
    elif cell == "ow_hello_f1_b":
        if c["knob_refuse_r1"] != "1" or c["knob_uto_r0"] is not None:
            bad.append("socket knob line (refuse_hello)")
    else:
        if c["knob_uto_r0"] is not None or c["knob_uto_r1"] is not None:
            bad.append("unexpected socket knob line")
    # this study's switch lines (hd only; a value equal to the default counts as off)
    if b == "hd":
        exp = {"hd_ref1_f1_b": (1, "gap", "8000:1200"), "hd_ref2_f1_b": (1, "gap", "8000:3000"),
               "hd_nonce_f1_b": (0, "badnonce", "1"), "hd_fwslow_f1_b": (0, "fwdelay", "8000@commit"),
               "hd_copystall_f1_b": (0, "copystall", "4000"), "hd_repost_f1_b": (0, "badrepost", "1")}
        if cell in exp:
            r, f, v = exp[cell]
            if c["hk_%s_r%d" % (f, r)] != v or c["hk_gap_r%d" % (1 - r)] is not None:
                bad.append("harden knob line (%s r%d=%s, other rank line %s)" % (f, r, c["hk_%s_r%d" % (f, r)],
                                                                                   c["hk_gap_r%d" % (1 - r)]))
        elif c["hk_gap_r0"] is not None or c["hk_gap_r1"] is not None:
            bad.append("unexpected harden knob line")
    # mute lines
    m0, m1 = c["n_mute_on_r0"], c["n_mute_on_r1"]
    if cell in MUTE_BOTH:
        ok = m0 >= 1 and m1 >= 1
    elif cell in MUTE_R1:
        ok = m1 >= 1 and m0 == 0
    elif cell in MUTE_R0:
        ok = m0 >= 1 and m1 == 0
    else:
        ok = m0 == 0 and m1 == 0
    if not ok:
        bad.append("mute lines r0=%d r1=%d" % (m0, m1))
    if cell == "ow_r0in_f1r1_b" and c["inj_ctx_r1"] != "1":
        bad.append("hook context r1=%s" % c["inj_ctx_r1"])
    if c["left_rules"] not in ("0",):
        bad.append("left_rules=%s" % c["left_rules"])
    return bad


# ---------------------------------------------------------------------------------------------------------------
# evaluator (section 3.2 grammar)


class Nil:
    """an empty cell: every comparison with it is false; arithmetic with it stays empty"""
    def _false(self, o):
        return False
    __lt__ = __le__ = __gt__ = __ge__ = __eq__ = __ne__ = _false

    def _nil(self, *a):
        return NIL
    __add__ = __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = __truediv__ = __rtruediv__ = _nil
    __neg__ = __abs__ = _nil

    def __bool__(self):
        return False

    __hash__ = object.__hash__

    def __repr__(self):
        return "<empty>"


NIL = Nil()


def conv(v):
    if v is None or v == "":
        return NIL
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    x = fnum(v)
    return x if x is not None else str(v)


def f_has(v, s):
    return isinstance(v, str) and s in v


def f_nonempty(v):
    return v is not NIL


def f_maskbit(v, b):
    if not isinstance(v, str):
        return False
    m = re.search(r"mask 0x([0-9a-fA-F]+)", v)
    return bool(m) and (int(m.group(1), 16) & int(b)) != 0


class NS(dict):
    def __init__(self, cols, missing):
        super().__init__()
        self.cols, self.missing = cols, missing
        self.update({"has": f_has, "nonempty": f_nonempty, "maskbit": f_maskbit, "abs": abs})

    def __missing__(self, name):
        if name in self.cols:
            return conv(self.cols[name])
        self.missing.add(name)
        return NIL


def split_call(s, name):
    """find name( ... ) with balanced parentheses; returns (start, end, inner) of the first one or None"""
    i = s.find(name + "(")
    while i >= 0 and i > 0 and (s[i - 1].isalnum() or s[i - 1] == "_"):
        i = s.find(name + "(", i + 1)
    if i < 0:
        return None
    j = i + len(name) + 1
    depth, q = 1, None
    while j < len(s):
        ch = s[j]
        if q:
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i, j + 1, s[i + len(name) + 1:j]
        j += 1
    raise ValueError("unbalanced: " + s)


def count_expr(expr, trials, missing, misses):
    code = compile(expr, "<acc>", "eval")
    n = 0
    for t in trials:
        try:
            ok = bool(eval(code, {"__builtins__": {}}, NS(t["c"], missing)))
        except TypeError:
            ok = False
        if ok:
            n += 1
        else:
            misses.append(t["stem"])
    return n


def evaluate(acc, keys, scored):
    """returns (verdict, detail list). keys: the prediction's cell keys"""
    per_cell = acc.strip().startswith("per cell:")
    body = acc.split(":", 1)[1].strip() if per_cell else acc.strip()
    missing = set()
    # data sufficiency: every referenced cell key must have its planned number of scored trials
    insufficient = [k for k in keys if len(scored.get(k, [])) < PLAN[k]]
    details = []

    def one(expr_body, cell_trials, key_label):
        s = expr_body
        counts = []
        while True:
            sc = split_call(s, "count")
            if sc is None:
                break
            a, b_, inner = sc
            misses = []
            n = count_expr(inner, cell_trials, missing, misses)
            counts.append((n, len(cell_trials), misses))
            s = s[:a] + repr(float(n)) + s[b_:]
        while True:
            sc = split_call(s, "median")
            if sc is None:
                break
            a, b_, inner = sc
            col, key = [x.strip() for x in inner.split(",", 1)]
            key = key.strip('"')
            vals = [conv(t["c"].get(col)) for t in scored.get(key, [])]
            vals = [v for v in vals if isinstance(v, float)]
            med = statistics.median(vals) if vals else None
            counts.append(("median", key, med, vals))
            s = s[:a] + (repr(med) if med is not None else "None") + s[b_:]
        try:
            val = eval(s, {"__builtins__": {}}, {"abs": abs, "None": None})
        except TypeError:
            val = False
        return bool(val), s, counts

    if per_cell:
        allok = True
        for k in keys:
            ok, s, counts = one(body, scored.get(k, []), k)
            details.append((k, ok, s, counts))
            allok = allok and ok
        verdict_ok = allok
    else:
        trials = scored.get(keys[0], []) if "count(" in body else []
        ok, s, counts = one(body, trials, keys[0])
        details.append((keys[0], ok, s, counts))
        verdict_ok = ok
    if insufficient:
        verdict = "insufficient data"
    else:
        verdict = "holds" if verdict_ok else "refuted"
    return verdict, details, missing, insufficient


# ---------------------------------------------------------------------------------------------------------------
# integrity checks


def git_blob(path):
    try:
        return subprocess.run(["git", "-C", STUDY, "cat-file", "blob", "%s:%s/%s" % (TAG, REL, path)],
                              capture_output=True, check=True).stdout
    except subprocess.CalledProcessError:
        return None


def git_rev(spec):
    try:
        return subprocess.run(["git", "-C", STUDY, "rev-parse", spec], capture_output=True, check=True,
                              text=True).stdout.strip()
    except subprocess.CalledProcessError:
        return None


def sections(text):
    """split EXPERIMENT.md into top-level '## N.' sections; returns {N: text}"""
    out, cur, buf = {}, None, []
    for line in text.splitlines(keepends=True):
        m = re.match(r"## (\d+)\. ", line)
        if m:
            if cur is not None:
                out[cur] = "".join(buf)
            cur, buf = int(m.group(1)), [line]
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        out[cur] = "".join(buf)
    return out


def integrity():
    lines = []
    wt = open(os.path.join(STUDY, "predictions.csv"), "rb").read()
    tagp = git_blob("predictions.csv")
    pre = open(os.path.join(STUDY, "PREREG.txt")).read()
    m = re.search(r"([0-9a-f]{64})\s+predictions\.csv", pre)
    h_wt = hashlib.sha256(wt).hexdigest()
    h_tag = hashlib.sha256(tagp).hexdigest() if tagp is not None else None
    lines.append("tag %s -> commit %s" % (TAG, git_rev(TAG + "^{commit}")))
    lines.append("predictions.csv sha256 (working tree) %s" % h_wt)
    lines.append("predictions.csv sha256 (tag blob)     %s" % h_tag)
    lines.append("PREREG.txt sha256                     %s" % (m.group(1) if m else None))
    ok1 = m is not None and h_wt == m.group(1) == h_tag
    lines.append("predictions.csv hash check: %s" % ("PASS" if ok1 else "FAIL"))
    rows = list(csv.DictReader(io.StringIO(wt.decode())))
    lines.append("predictions.csv rows: %d" % len(rows))
    pt = git_blob("PREREG.txt")
    lines.append("PREREG.txt identical to tag: %s" % (pt == open(os.path.join(STUDY, "PREREG.txt"), "rb").read()))
    ex_wt = open(os.path.join(STUDY, "EXPERIMENT.md"), encoding="utf-8").read()
    ex_tag = (git_blob("EXPERIMENT.md") or b"").decode("utf-8")
    s_wt, s_tag = sections(ex_wt), sections(ex_tag)
    ok2 = True
    for n in (2, 3, 7, 8):
        same = s_wt.get(n) == s_tag.get(n) and s_wt.get(n) is not None
        ok2 = ok2 and same
        lines.append("EXPERIMENT.md section %d byte-identical to tag: %s (%d bytes)" % (
            n, same, len((s_wt.get(n) or "").encode())))
    lines.append("EXPERIMENT.md whole file identical to tag: %s" % (ex_wt == ex_tag))
    for f in ("cells.sh", "run_trial_hd.sh", "hold.sh", "chain.sh"):
        # read-only comparison of the bytes; the tag blob is the cleaned form, so a file whose clean filter rewrites a
        # literal address differs only on those lines
        wtb = open(os.path.join(STUDY, f), "rb").read()
        tb = git_blob(f)
        if tb is None:
            lines.append("%s: not in tag" % f)
            continue
        dl = [i for i, (a, b) in enumerate(zip(wtb.splitlines(), tb.splitlines())) if a != b]
        same_n = len(wtb.splitlines()) == len(tb.splitlines())
        lines.append("%s vs tag: same line count %s, differing lines %d%s" % (
            f, same_n, len(dl), "" if not dl else " (all of them the SUNNY_SSH default, rewritten by the address "
                                                  "clean filter: %s)" % (
                all(tb.splitlines()[i].startswith(b"SUNNY_SSH=") for i in dl))))
    return lines, rows, ok1 and ok2


# ---------------------------------------------------------------------------------------------------------------
# helpers for the report


def rng(vals, fmt="%.1f"):
    v = [x for x in vals if x is not None]
    if not v:
        return "none"
    return ("%s–%s" % (fmt % min(v), fmt % max(v))) + " (n=%d)" % len(v)


def lat_raw_p50(path):
    """recompute p50 from the per-iteration file: the driver's rule (sorted[round(0.5*(n-1))]) and the plain median"""
    if not os.path.exists(path):
        return None, None, 0
    v = []
    with gzip.open(path, "rt") as f:
        for line in f:
            p = line.strip().split(",")
            if len(p) == 2:
                v.append(int(p[1]))
    if not v:
        return None, None, 0
    s = sorted(v)
    k = int(0.5 * (len(s) - 1) + 0.5)
    return s[k] / 1e3, statistics.median(s) / 1e3, len(s)


def main():
    out = []
    P = out.append
    P("# gin-harden independent recount (qa/recount.py)")
    P("")
    # ---- integrity
    il, preds, iok = integrity()
    P("## Pre-registration integrity")
    for x in il:
        P("  " + x)
    P("")
    # ---- trials
    trials = []
    for b in BUILDS:
        d = os.path.join(RES, b)
        for f in sorted(os.listdir(d)):
            if f.endswith("_meta.txt"):
                trials.append(trial(b, f[:-len("_meta.txt")]))
    trials.sort(key=lambda t: (t["key"], t["n"]))
    P("## Trials")
    P("  trial files (meta) found: %d" % len(trials))
    keys_found = sorted(set(t["key"] for t in trials))
    unplanned = [k for k in keys_found if k not in PLAN]
    notrun = [k for k in PLAN if k not in keys_found]
    P("  cell keys found: %d; planned: %d; unplanned keys: %s; planned keys without trials: %s" % (
        len(keys_found), len(PLAN), unplanned or "none", notrun or "none"))
    excl = {}
    scored = {}
    for t in trials:
        e = exclusion(t)
        t["excl"] = e
        if e:
            excl.setdefault(t["key"], []).append((t["trial"], e))
        else:
            scored.setdefault(t["key"], []).append(t)
    P("  excluded trials: %d" % sum(len(v) for v in excl.values()))
    for k, v in sorted(excl.items()):
        for tr, e in v:
            P("    %s %s: %s" % (k, tr, e))
    P("")
    P("  cell key | planned | run | excluded | scored | fill trials (beyond planned numbering) | fill <= 50%")
    tot_s = 0
    for k in sorted(PLAN):
        run = [t for t in trials if t["key"] == k]
        fills = [t["trial"] for t in run if t["n"] > PLAN[k]]
        ns = len(scored.get(k, []))
        tot_s += ns
        P("  %-28s %2d %3d %2d %3d %-10s %s" % (k, PLAN[k], len(run), len(excl.get(k, [])), ns, ",".join(fills) or "-",
                                             len(fills) <= PLAN[k] * 0.5))
    P("  total scored: %d (cell trials %d, latency runs %d)" % (
        tot_s, sum(len(v) for k, v in scored.items() if not k.startswith("lat_")),
        sum(len(v) for k, v in scored.items() if k.startswith("lat_"))))
    over = [k for k in PLAN if len(scored.get(k, [])) > PLAN[k]]
    P("  cell keys with more scored trials than planned: %s" % (over or "none"))
    import time
    mt = sorted(os.path.getmtime(os.path.join(RES, t["build"], t["stem"] + "_meta.txt")) for t in trials)
    tag_t = subprocess.run(["git", "-C", STUDY, "show", "-s", "--format=%ct", TAG + "^{commit}"], capture_output=True,
                           text=True).stdout.strip()
    fmt_t = lambda s: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(s))
    P("  trial meta files written %s .. %s; tag commit time %s; all after the tag: %s" % (
        fmt_t(mt[0]), fmt_t(mt[-1]), fmt_t(int(tag_t)) if tag_t else None, bool(tag_t) and mt[0] > int(tag_t)))
    # bind failures, all trials
    bf = [(t["key"], t["trial"]) for t in trials if t["c"]["bind_fail"]]
    P("  bind failures (r0 log 'bind: Address already in use'): %s" % bf)
    P("")
    # ---- configuration checks, CUDA, leftovers
    P("## Configuration checks (section 8; failures stop a block, they do not exclude)")
    nfail = 0
    for t in trials:
        bad = config_check(t)
        if bad:
            nfail += 1
            P("  %s %s: %s" % (t["key"], t["trial"], "; ".join(bad)))
    P("  trials with a failed check: %d of %d" % (nfail, len(trials)))
    cud = [(t["key"], t["trial"]) for t in trials if t["c"]["r0rc"] == "139" or t["c"]["r1rc"] == "139" or
           t["lg"][0]["cnt"]["cuda"] or t["lg"][1]["cnt"]["cuda"] or
           any(re.search(r"illegal address|illegal memory access|unspecified launch failure", " ".join(kk.values()), re.I)
               for kk in t["k"])]
    P("  CUDA memory faults (rc 139 or illegal address / launch failure in logs or kv): %s" % (cud or "none"))
    lefts = [(t["key"], t["trial"], t["c"]["left"]) for t in trials if t["c"]["left"] != "0"]
    P("  trials with left != 0: %s" % (lefts or "none"))
    lr = [(t["key"], t["trial"], t["c"]["left_rules"]) for t in trials if t["c"]["left_rules"] != "0"]
    P("  trials with left_rules != 0: %s" % (lr or "none"))
    P("")
    # ---- predictions
    P("## Predictions (own evaluator of the section 3.2 grammar)")
    tally = {}
    allmissing = set()
    for p in preds:
        keys = [x.strip() for x in p["cells"].split(";")]
        verdict, details, missing, insuff = evaluate(p["acceptance"], keys, scored)
        allmissing |= missing
        tally[verdict] = tally.get(verdict, 0) + 1
        parts = []
        for k, ok, s, counts in details:
            for cnt in counts:
                if cnt[0] == "median":
                    parts.append("median %s=%s over %s" % (cnt[1], ("%.3f" % cnt[2]) if cnt[2] is not None else None,
                                                           ["%.2f" % v for v in cnt[3]]))
                else:
                    n, N, misses = cnt
                    parts.append("%s %d/%d%s" % (k, n, N, (" misses: " + ",".join(
                        x.replace(k.split("@")[0] + "_", "") for x in misses)) if misses else ""))
            parts.append("=> [%s] %s" % (s if len(s) < 120 else s[:117] + "...", ok))
        P("  %-4s %-8s %-18s %s" % (p["id"], p["kind"], verdict, " | ".join(parts)))
        if insuff:
            P("       insufficient: %s" % insuff)
        if verdict == "refuted" and "count(" in p["acceptance"]:
            # which conjuncts failed: count each top-level 'and' term of the count expression separately
            sc = split_call(p["acceptance"], "count")
            terms, depth, cur, i, s = [], 0, "", 0, sc[2]
            while i < len(s):
                if s[i] in "(":
                    depth += 1
                elif s[i] == ")":
                    depth -= 1
                if depth == 0 and s.startswith(" and ", i):
                    terms.append(cur)
                    cur, i = "", i + 5
                    continue
                cur += s[i]
                i += 1
            terms.append(cur)
            for k in keys:
                for term in terms:
                    n = count_expr(term.strip(), scored.get(k, []), set(), [])
                    P("       %s term %-70s %d/%d" % (k, term.strip()[:70], n, len(scored.get(k, []))))
    P("  verdicts: %s" % tally)
    P("  column names in acceptance rules not computed by this script: %s" % (sorted(allmissing) or "none"))
    P("")
    # ---- key numbers
    P("## Key numbers (ranges are over the scored trials of the named cell key unless stated)")

    def col(k, name):
        return [conv(t["c"].get(name)) for t in scored.get(k, [])]

    def fl(xs):
        return [x for x in xs if isinstance(x, float)]

    def show(label, k, name, fmt="%.1f"):
        P("  %-58s %s" % (label + " [" + k + " " + name + "]", rng(fl(col(k, name)), fmt)))

    P("  -- decline after kill (rank 0 first decline - kill on rank 0's clock), ms")
    for k in ("f4_b@hd", "hdp_kill_b@hdp", "hd_shrink_b@hd"):
        show("decline after kill", k, "decl_after_kill_ms_r0", "%.2f")
    for k in ("f4_b@hd", "hdp_kill_b@hdp"):
        P("    %s decline reasons: %s" % (k, sorted(set(t["c"]["decl_r0"] for t in scored[k]))))
    k = "f2rel_b@hd"
    show("rank 1 abort after its decline", k, "teardown_ms_r1", "%.1f")
    P("    %s r1_outcome %s rx_rc %s rx_phantom_r1 %s decl_r0 %s" % (
        k, sorted(set(str(t["c"]["r1_outcome"]) for t in scored[k])), sorted(set(str(t["c"]["rx_rc"]) for t in scored[k])),
        sorted(set(str(t["c"]["rx_phantom_r1"]) for t in scored[k])), sorted(set(t["c"]["decl_r0"] for t in scored[k]))))
    P("  -- receive-only rank after rank 0's kill (rank 1 clock), ms")
    for k in ("hd_rxdeath_b@hd", "hd_rxdeath_b@ow"):
        show("kernel end after kill", k, "release_after_kill_ms_r1", "%.1f")
        show("async error after kill", k, "async_after_kill_ms_r1", "%.1f")
        P("    %s rx_rc: %s" % (k, sorted(set(str(t["c"]["rx_rc"]) for t in scored[k]))))
    P("  -- refusals")
    for k in ("hd_ref1_f1_b@hd", "hd_ref2_f1_b@hd", "rc_mutekill_b@hd"):
        show("re-dial refusals per trial", k, "n_refused_dial_r0", "%.0f")
        vals = []
        for t in scored.get(k, []):
            c = t["c"]
            if c["refusal1_ms_r0"] is not None and c["mute_off_ms_r0"] is not None:
                vals.append(c["refusal1_ms_r0"] - c["mute_off_ms_r0"])
        P("  %-58s %s" % ("first refusal after rank 0's mute end [" + k + "]", rng(vals, "%.1f")))
        show("judged dead - first refusal", k, "refusal_span_ms_r0", "%.1f")
    k = "ow_kill0_b@hd"
    show("probe refusals per trial", k, "n_probe_ref_r1", "%.0f")
    show("judged dead - first refusal (rank 1)", k, "refusal_span_ms_r1", "%.1f")
    vals = [t["c"]["judged_ms_r1"] - t["c"]["mute_off_ms_r1"] for t in scored.get(k, [])
            if t["c"]["judged_ms_r1"] is not None and t["c"]["mute_off_ms_r1"] is not None]
    P("  %-58s %s" % ("judged dead after rank 1's mute end [" + k + "]", rng(vals, "%.1f")))
    for k in ("hd_ref2_f1_b@hd", "rc_mutekill_b@hd"):
        vals = [t["c"]["decl_ms_r0"] - t["c"]["judged_ms_r0"] for t in scored.get(k, [])
                if t["c"]["decl_ms_r0"] is not None and t["c"]["judged_ms_r0"] is not None]
        P("  %-58s %s" % ("decline - judged dead [" + k + "] ms", rng(vals, "%.2f")))
    P("  -- reconnects after the mute end (latest mute end of the ranks, rank 0 clock), ms")
    for k, r in (("hd_ref1_f1_b@hd", 0), ("hd_nonce_f1_b@hd", 0), ("rc_mute8_f1_b@hd", 0), ("ow_r1in_f1_b@hd", 0),
                 ("ow_hello_f1_b@hd", 0), ("ow_r0in_f1r1_b@hd", 1)):
        show("reconnect after unmute", k, "reconn_after_unmute_ms_r%d" % r, "%.1f")
    for k in ("hdp_mute_b@hdp",):
        show("rank 0 reconnects (rs_reconnects_r0)", k, "rs_reconnects_r0", "%.0f")
        show("rank 1 reconnects (rs_reconnects_r1)", k, "rs_reconnects_r1", "%.0f")
    P("  -- round cancelled by a reset inside the round")
    for k in ("hd_rround_f1_b@hd", "hd_rround_f1_b@ow"):
        show("rank 1 close - rank 0 first classification", k, "r1close_after_q4_ms", "%.1f")
        show("cancel lines r0", k, "n_cancel_r0", "%.0f")
        show("initiator recovered lines r0", k, "rec_init_r0", "%.0f")
        show("sock_retries max r0", k, "sock_retries_max_r0", "%.0f")
        show("recovery total_us r0 (first initiator line)", k, "rec_total_us_r0", "%.0f")
        P("    %s decl_r0: %s" % (k, sorted(set(t["c"]["decl_r0"] for t in scored[k]))))
    P("  -- firmware watchdog, copy bound, abort")
    k = "hd_fwslow_f1_b@hd"
    show("watchdog 'has run' ms", k, "fwdog_run_ms_r0", "%.0f")
    P("    %s watchdog phase: %s; first user-wait release why: %s" % (
        k, sorted(set(str(t["c"]["fwdog_phase_r0"]) for t in scored[k])),
        sorted(set(str(t["c"]["uarel_why_r0"]) for t in scored[k]))))
    vals = []
    for t in scored.get(k, []):
        q = t["c"]["q4_ms_r0"]
        dog = [x for x in t["lg"][0]["uarel"] if x[0] == "fw-watchdog"]
        if q is not None and dog:
            vals.append(dog[0][1] - q)
    P("  %-58s %s" % ("fw-watchdog wait release - first classification [" + k + "] ms", rng(vals, "%.1f")))
    show("rank 0 abort (teardown_ms_r0)", k, "teardown_ms_r0", "%.1f")
    show("rank 1 abort (teardown_ms_r1)", k, "teardown_ms_r1", "%.1f")
    show("helper detached lines r0", k, "n_orphan_r0", "%.0f")
    det = [x for t in scored.get(k, []) for x in t["lg"][0]["orphan"]]
    P("  %-58s %s; phase %s; current command for %s ms" % (
        "teardown join waited before detaching [" + k + "] ms", rng([x[0] for x in det], "%.0f"),
        sorted(set(str(x[1]) for x in det)), rng([x[2] for x in det], "%.0f")))
    vals = [t["c"]["decl_r1"] for t in scored.get(k, [])]
    P("    %s decl_r1: %s; decl_r0 nonempty in %d trials" % (k, sorted(set(vals)), sum(
        1 for t in scored.get(k, []) if t["c"]["decl_r0"])))
    k = "hd_fwslow_f1_b@ow"
    show("recovery total_us r0", k, "rec_total_us_r0", "%.0f")
    k = "hd_copystall_f1_b@hd"
    show("copy-bound lines r0", k, "n_copyto_r0", "%.0f")
    show("first decline - first classification r0", k, "decl_after_q4_ms_r0", "%.1f")
    show("rs_copy_timeouts_r0", k, "rs_copy_timeouts_r0", "%.0f")
    show("rank 0 abort", k, "teardown_ms_r0", "%.1f")
    show("rank 1 abort", k, "teardown_ms_r1", "%.1f")
    k = "hd_hog_f1_b@hd"
    show("hook - kernel launch r0", k, "fault_after_launch_r0_ms", "%.1f")
    show("filler launch - kernel launch r0", k, "hog_launch_after_launch_ms_r0", "%.1f")
    show("copy-bound lines r0", k, "n_copyto_r0", "%.0f")
    show("copy-bound lines r1", k, "n_copyto_r1", "%.0f")
    show("rs_copy_timeouts_r0", k, "rs_copy_timeouts_r0", "%.0f")
    show("rs_copy_timeouts_r1", k, "rs_copy_timeouts_r1", "%.0f")
    show("initiator recovered lines r0", k, "rec_init_r0", "%.0f")
    show("first decline - first classification r0", k, "decl_after_q4_ms_r0", "%.1f")
    for r in (0, 1):
        cps, kes, wds = [], [], []
        for t in scored.get(k, []):
            la = fnum(t["k"][r].get("launch_mono_ms"))
            if la is None:
                continue
            if t["lg"][r]["copyto_t"] and t["lg"][r]["copyto_t"][0] is not None:
                cps.append(t["lg"][r]["copyto_t"][0] - la)
            kes.append(fnum(t["k"][r].get("kernel_ms")))
            q = t["c"]["q4_ms_r%d" % r]
            if t["lg"][r]["helper_idle_wd"] and q is not None:
                wds.append(t["lg"][r]["helper_idle_wd"][0] - q)
        P("  %-58s %s" % ("copy-bound line - own kernel launch r%d [%s] ms" % (r, k), rng(cps, "%.1f")))
        P("  %-58s %s" % ("GIN kernel_ms r%d [%s]" % (r, k), rng(kes, "%.1f")))
        if wds:
            P("  %-58s %s" % ("'helper not running' watchdog - first classification r%d [%s] ms" % (r, k),
                              rng(wds, "%.1f")))
    P("    %s transparent: %d of %d; hog blocks/SMs r0: %s; r1: %s" % (
        k, sum(t["c"]["transparent_ok"] for t in scored[k]), len(scored[k]),
        sorted(set((t["c"]["hog_blocks_r0"], t["c"]["hog_sms_r0"]) for t in scored[k])),
        sorted(set((t["c"]["hog_blocks_r1"], t["c"]["hog_sms_r1"]) for t in scored[k]))))
    P("    %s decl_r0: %s" % (k, sorted(set(t["c"]["decl_r0"] for t in scored[k]))))
    P("  -- re-post plan")
    k = "hd_repost_f1_b@hd"
    P("    %s plan rejection (qp, of, initiator) per trial: %s" % (k, [
        (t["trial"], t["c"]["plan_rej_qp_r0"], t["c"]["plan_rej_total_r0"], t["c"]["plan_rej_init_r0"])
        for t in scored[k]]))
    show("recovered lines r0", k, "n_rec_r0", "%.0f")
    show("recovered lines r1", k, "n_rec_r1", "%.0f")
    P("  -- escalation")
    for k in ("hd_esc_f1_b@hd", "hd_esc_f1_b@ow"):
        show("initiator recovered lines r0", k, "rec_init_r0", "%.0f")
        show("escalation lines r0", k, "n_esc_r0", "%.0f")
        show("hook fires r0", k, "n_fires_r0", "%.0f")
    k = "hd_esc_f1_b@hd"
    for name in ("rs_rounds_r0", "rs_recovered_r0", "rs_declined_r0", "rs_escalations_r0", "rs_rounds_r1",
                 "rs_recovered_r1", "rs_declined_r1", "rs_escalations_r1"):
        show(name, k, name, "%.0f")
    P("    %s decl_r1: %s" % (k, sorted(set(t["c"]["decl_r1"] for t in scored[k]))))
    P("  -- shrink hand-off")
    for k in ("hd_shrink_b@hd", "hd_shrink_b@ow2"):
        for name in ("ho_kernel_done_before_shrink", "ho_shrink_rc", "ho_shrink_ms", "ho_newcomm", "ho_old_kernel_done",
                     "rx_rc_r0", "rx_phantom_r0", "post_abort_rx_phantom_r0"):
            vals = [t["c"][name] for t in scored.get(k, [])]
            P("    %-22s %-34s %s" % (k, name, sorted(set(str(v) for v in vals))))
    P("  -- IB timeout 20")
    k = "to20_f3_b@hd"
    show("first classification - hook (rank 0 clock) ms", k, "q4_after_fault_ms_r0", "%.1f")
    P("    %s first classes r0: %s" % (k, sorted(set(t["c"]["q4_class_r0"] for t in scored[k]))))
    show("recovery total_us r0", k, "rec_total_us_r0", "%.0f")
    show("initiator recovered lines r0", k, "rec_init_r0", "%.0f")
    P("    %s transparent: %d of %d" % (k, sum(t["c"]["transparent_ok"] for t in scored[k]), len(scored[k])))
    k = "to20_f3_t@hd"
    P("    %s tx_rc: %s; dumps r0: %s; rec_init_r0: %s; decl_r0: %s" % (
        k, sorted(set(str(t["c"]["tx_rc"]) for t in scored[k])), [t["c"]["n_dump_r0"] for t in scored[k]],
        [t["c"]["rec_init_r0"] for t in scored[k]], sorted(set(t["c"]["decl_r0"] for t in scored[k]))))
    P("  -- latency p50 (rank 0 kv lat_p50_us; and recomputed from lat_raw.csv.gz), us")
    meds = {}
    for size in ("lat_4k", "lat_256k"):
        for b in ("hdp", "ow", "stk"):
            k = size + "@" + b
            kvv, rawv, raws, truem = [], [], [], []
            for t in scored.get(k, []):
                kvv.append(fnum(t["c"]["lat_p50_us"]))
                p50, med, n = lat_raw_p50(t["lat_raw"])
                rawv.append(p50)
                truem.append(med)
                raws.append(n)
            meds[k] = statistics.median([x for x in kvv if x is not None])
            meds[k + "#raw"] = statistics.median([x for x in rawv if x is not None])
            meds[k + "#true"] = statistics.median([x for x in truem if x is not None])
            agree = all(a is not None and b_ is not None and abs(a - b_) < 0.006 for a, b_ in zip(kvv, rawv))
            P("    %-14s runs %s median %.2f | raw p50 %s (n per run %s) kv==raw: %s | plain median per run %s" % (
                k, ["%.2f" % x for x in kvv], meds[k], ["%.3f" % x for x in rawv], sorted(set(raws)), agree,
                ["%.3f" % x for x in truem]))
    for size in ("lat_4k", "lat_256k"):
        P("    %s: hdp - ow = %+.2f, hdp - stk = %+.2f (kv); from raw p50 %+.3f, %+.3f; from plain medians %+.3f, %+.3f" % (
            size, meds[size + "@hdp"] - meds[size + "@ow"], meds[size + "@hdp"] - meds[size + "@stk"],
            meds[size + "@hdp#raw"] - meds[size + "@ow#raw"], meds[size + "@hdp#raw"] - meds[size + "@stk#raw"],
            meds[size + "@hdp#true"] - meds[size + "@ow#true"], meds[size + "@hdp#true"] - meds[size + "@stk#true"]))
    P("  -- recovery-stats counters (ncclGinGetRecoveryStats, kv rs_*)")
    for k in ("f1_b@hd", "f4_b@hd", "hdp_kill_b@hdp", "hdp_mute_b@hdp", "hd_rxdeath_b@hd", "hd_shrink_b@hd",
              "hd_copystall_f1_b@hd", "hd_fwslow_f1_b@hd", "hd_rround_f1_b@hd"):
        for r in (0, 1):
            vals = []
            for t in scored.get(k, []):
                c = t["c"]
                if c["rs_api_r%d" % r] is None:
                    vals.append("none")
                    continue
                vals.append("api=%s ctx=%s rounds=%s rec=%s decl=%s reconn=%s deaths=%s esc=%s cancel=%s fw=%s copy=%s" % tuple(
                    c["rs_%s_r%d" % (x, r)] for x in ("api", "contexts", "rounds", "recovered", "declined", "reconnects",
                                                     "deaths", "escalations", "cancelled", "fw_overruns",
                                                     "copy_timeouts")))
            agg = {}
            for v in vals:
                agg[v] = agg.get(v, 0) + 1
            P("    %-22s r%d %s" % (k, r, "; ".join("%s x%d" % (v, n) for v, n in sorted(agg.items()))))
    P("  -- iptables mute (hdp_mute_b@hdp; mute.out and meta)")
    for t in scored.get("hdp_mute_b@hdp", []):
        mu, c = t["mute"], t["c"]
        on, offm = fnum(mu.get("mute_on_mono_ms")), fnum(mu.get("mute_off_mono_ms"))
        la = fnum(t["k"][0].get("launch_mono_ms"))
        P("    %s applied=%s rules_on=%s rules_left=%s left_rules=%s start-launch=%s ms window=%s ms ports=%s; "
          "r0 close=%s/%s r1 close=%s/%s reconn r0/r1=%s/%s rs_reconnects=%s/%s deaths=%s/%s decl=%r/%r ok=%s" % (
              t["trial"], c["mute_applied"], c["mute_rules_on"], c["mute_rules_left"], c["left_rules"],
              "%.1f" % (on - la) if on is not None and la is not None else None,
              "%.1f" % (offm - on) if on is not None and offm is not None else None, mu.get("ports"),
              c["close1_cause_r0"], c["close1_lv_r0"], c["close1_cause_r1"], c["close1_lv_r1"], c["n_reconn_r0"],
              c["n_reconn_r1"], c["rs_reconnects_r0"], c["rs_reconnects_r1"], c["rs_deaths_r0"], c["rs_deaths_r1"],
              c["decl_r0"], c["decl_r1"], c["transparent_ok"]))
    P("")
    # ---- hold logs: what each hold printed vs the trial files
    P("## Hold logs vs trial files")
    for h in ["H1", "H2", "H3", "H4", "H5", "H6", "H7", "H8", "fill"]:
        txt = readf(os.path.join(RES, "hold_%s.out" % h)) or ""
        n_tr = len(re.findall(r"\] r0rc=", txt))
        n_bf = len(re.findall(r"wall=0\.0s :: $", txt, re.M))
        newl = re.search(r"new mlx5 kernel lines in hold \S+: (\d+)", txt)
        b = re.search(r"== before-\S+ (\S+ \S+)", txt)
        a = re.search(r"== after-\S+ (\S+ \S+)", txt)
        P("  %-5s trials printed %3d, runner lines with wall=0.0s %d, new mlx5 lines %s, snapshots %s .. %s" % (
            h, n_tr, n_bf, newl.group(1) if newl else None, b.group(1) if b else None, a.group(1) if a else None))
    stops = [f for f in os.listdir(RES) if f.startswith("STOP_")]
    P("  STOP files: %s" % (stops or "none"))
    ch = readf(os.path.join(RES, "chain.out")) or ""
    P("  chain.out: holds rc=0: %d; iptables cleanup lines 'deleted=0 left=0': %d" % (
        len(re.findall(r" rc=0$", ch, re.M)), len(re.findall(r"deleted=0 left=0", ch))))
    for x in hold_crosscheck(trials):
        P("  " + x)
    P("")
    P("## Pilot statements (results/20261009_pilot, never scored; only EXPERIMENT.md's statements about it are checked)")
    for x in pilot_check():
        P("  " + x)
    print("\n".join(out))


def hold_crosscheck(trials):
    """every runner line printed in hold_*.out against the trial files (multiset match)"""
    from collections import Counter
    res_h, start_h, kill_h = Counter(), Counter(), Counter()
    for h in ["H1", "H2", "H3", "H4", "H5", "H6", "H7", "H8", "fill"]:
        for line in (readf(os.path.join(RES, "hold_%s.out" % h)) or "").splitlines():
            m = re.match(r"^\[(\S+)\] (r0rc=.*)$", line)
            if m:
                res_h[(m.group(1), m.group(2).rstrip())] += 1
                continue
            m = re.match(r"^\[(\S+)\] rain=(\S+) sunny=(\S+) port=\d+ inject=(\S+) bytes=(\d+) iters=(\d+) rtag=", line)
            if m:
                start_h[m.groups()] += 1
                continue
            m = re.match(r"^\[(\S+)\] SIGKILL rank(\d) after (\d+) ms: (.*)$", line)
            if m:
                kill_h[(m.group(1), m.group(3), m.group(4).strip())] += 1
    res_t, start_t, kill_t = Counter(), Counter(), Counter()
    for t in trials:
        m = t["meta"]
        tag = "%s/ts%s/%s/%s/%s#%s" % (m.get("build"), m.get("ts"), m.get("app"), m.get("fault"), m.get("wait"),
                                       m.get("trial"))
        res = "r0rc=%s r1rc=%s left=%s left_rules=%s wall=%ss :: %s" % (
            m.get("r0rc"), m.get("r1rc"), m.get("left"), m.get("left_rules"), m.get("wall_s"),
            "".join(d + "|" for d in t["done"]))
        res_t[(tag, res.rstrip())] += 1
        start_t[(tag, m.get("gid0"), m.get("gid1"), m.get("inject"), m.get("bytes"), m.get("iters"))] += 1
        if t["kill_txt"]:
            kill_t[(tag, m.get("kill_delay_ms") or "1200", t["kill_txt"])] += 1
    out = []
    for name, a, b in (("result lines", res_h, res_t), ("start lines", start_h, start_t), ("kill lines", kill_h, kill_t)):
        only_h, only_t = a - b, b - a
        out.append("hold %s: %d printed, %d from trial files, printed-only %d, file-only %d" % (
            name, sum(a.values()), sum(b.values()), sum(only_h.values()), sum(only_t.values())))
        for x in list(only_h)[:6]:
            out.append("    printed only: %s" % (x,))
        for x in list(only_t)[:6]:
            out.append("    file only:    %s" % (x,))
    return out


def pilot_check():
    out = []
    pt = []
    for b in BUILDS:
        d = os.path.join(PILOT, b)
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.endswith("_meta.txt"):
                    pt.append(trial(b, f[:-len("_meta.txt")], PILOT))
    P = {t["key"]: t for t in pt}
    out.append("pilot trials: %d" % len(pt))
    h0 = readf(os.path.join(PILOT, "hold_H0.out")) or ""
    b = re.search(r"== before-\S+ (\S+ \S+)", h0)
    a = re.search(r"== after-\S+ (\S+ \S+)", h0)
    nl = re.search(r"new mlx5 kernel lines in hold \S+: (\d+)", h0)
    out.append("pilot snapshots %s .. %s; new mlx5 lines %s; chain: %s" % (
        b.group(1) if b else None, a.group(1) if a else None, nl.group(1) if nl else None,
        " / ".join(x for x in (readf(os.path.join(PILOT, "chain.out")) or "").splitlines() if "cleanup" in x)))

    def g(key, col):
        t = P.get(key)
        return None if t is None else t["c"].get(col)

    def fmt(x, f="%.1f"):
        return "None" if x is None else (f % x if isinstance(x, float) else str(x))
    rows = [
        ("ref2 refusal span (doc 1 001.3 ms)", g("hd_ref2_f1_b@hd", "refusal_span_ms_r0")),
        ("ref2 hook fires r0 (doc: excluded as 'fault not applied' before the fix)", g("hd_ref2_f1_b@hd", "n_fires_r0")),
        ("nonce reconnect after unmute (doc 606.7 ms)", g("hd_nonce_f1_b@hd", "reconn_after_unmute_ms_r0")),
        ("rround r1 close after r0 first classification (doc 2 075.8 ms)", g("hd_rround_f1_b@hd", "r1close_after_q4_ms")),
        ("rround cancel r0 / sock_retries / transparent (doc 1, 1, yes)",
         (g("hd_rround_f1_b@hd", "n_cancel_r0"), g("hd_rround_f1_b@hd", "sock_retries_max_r0"),
          g("hd_rround_f1_b@hd", "transparent_ok"))),
        ("rxdeath kernel end after kill (doc 20.2 ms)", g("hd_rxdeath_b@hd", "release_after_kill_ms_r1")),
        ("rxdeath async after kill (doc 1.9 ms)", g("hd_rxdeath_b@hd", "async_after_kill_ms_r1")),
        ("fwslow watchdog run ms (doc 3 000)", g("hd_fwslow_f1_b@hd", "fwdog_run_ms_r0")),
        ("fwslow rank 0 abort teardown_ms (doc 912 ms)", fnum(g("hd_fwslow_f1_b@hd", "teardown_ms_r0"))),
        ("copystall decline after first classification (doc 2 000.8 ms)", g("hd_copystall_f1_b@hd", "decl_after_q4_ms_r0")),
        ("repost plan rejection qp/of/initiator, rec r0/r1 (doc 1 of 4, initiator, none)",
         (g("hd_repost_f1_b@hd", "plan_rej_qp_r0"), g("hd_repost_f1_b@hd", "plan_rej_total_r0"),
          g("hd_repost_f1_b@hd", "plan_rej_init_r0"), g("hd_repost_f1_b@hd", "n_rec_r0"), g("hd_repost_f1_b@hd", "n_rec_r1"))),
        ("esc rec_init_r0 / n_esc_r0 (doc 3, escalated at the 4th)", (g("hd_esc_f1_b@hd", "rec_init_r0"), g("hd_esc_f1_b@hd", "n_esc_r0"))),
        ("shrink@hd rx_phantom_r0 (doc 0)", g("hd_shrink_b@hd", "rx_phantom_r0")),
        ("shrink rc/ms hd (doc ncclRemoteError at 0 ms)", (g("hd_shrink_b@hd", "ho_shrink_rc"), g("hd_shrink_b@hd", "ho_shrink_ms"))),
        ("shrink rc/ms ow2 (doc ncclRemoteError at 0 ms)", (g("hd_shrink_b@ow2", "ho_shrink_rc"), g("hd_shrink_b@ow2", "ho_shrink_ms"))),
        ("ow2 post-abort phantom (doc 202)", g("hd_shrink_b@ow2", "post_abort_rx_phantom_r0")),
        ("ow2 old kernel done before shrink (doc: still running)", g("hd_shrink_b@ow2", "ho_kernel_done_before_shrink")),
        ("ow rround decl_r0 (doc REQ send failure)", g("hd_rround_f1_b@ow", "decl_r0")),
        ("ow rxdeath rx_rc / release after kill (doc 15 s bound)", (g("hd_rxdeath_b@ow", "rx_rc"), g("hd_rxdeath_b@ow", "release_after_kill_ms_r1"))),
        ("ow fwslow rec total_us (doc waits 8 s then recovers)", g("hd_fwslow_f1_b@ow", "rec_total_us_r0")),
        ("ow esc rec_init_r0 (doc 5)", g("hd_esc_f1_b@ow", "rec_init_r0")),
        ("hdp kill decline after kill (doc 1.6 ms)", g("hdp_kill_b@hdp", "decl_after_kill_ms_r0")),
        ("hdp mute transparent / reconnects / ts_on (doc reconnect, transparent, no info line)",
         (g("hdp_mute_b@hdp", "transparent_ok"), g("hdp_mute_b@hdp", "rs_reconnects_r0"), g("hdp_mute_b@hdp", "rs_reconnects_r1"),
          g("hdp_mute_b@hdp", "ts_on_r0"), g("hdp_mute_b@hdp", "ts_on_r1"))),
        ("to20_f3_b first classification after hook (doc 56.0 s)", g("to20_f3_b@hd", "q4_after_fault_ms_r0")),
        ("to20_f3_b rec total_us (doc 10 ms one round, transparent)", (g("to20_f3_b@hd", "rec_total_us_r0"), g("to20_f3_b@hd", "transparent_ok"))),
        ("to20_f3_t tx_rc / rec_init / decl (doc timeout only)", (g("to20_f3_t@hd", "tx_rc"), g("to20_f3_t@hd", "rec_init_r0"), g("to20_f3_t@hd", "decl_r0"))),
        ("lat_4k p50 hdp/ow/stk (doc 10.69, 10.56, 9.76)", (g("lat_4k@hdp", "lat_p50_us"), g("lat_4k@ow", "lat_p50_us"), g("lat_4k@stk", "lat_p50_us"))),
        ("hog copy-bound lines r0/r1, rs_copy_timeouts r0/r1, transparent (doc: copies missed the bound, both declined)",
         (g("hd_hog_f1_b@hd", "n_copyto_r0"), g("hd_hog_f1_b@hd", "n_copyto_r1"), g("hd_hog_f1_b@hd", "rs_copy_timeouts_r0"),
          g("hd_hog_f1_b@hd", "rs_copy_timeouts_r1"), g("hd_hog_f1_b@hd", "transparent_ok"))),
    ]
    for label, v in rows:
        out.append("%-100s %s" % (label, tuple(fmt(x) for x in v) if isinstance(v, tuple) else fmt(v)))
    # derived timings stated in EXPERIMENT.md section 12
    for key, lab in (("hd_ref1_f1_b@hd", "93.6"), ("hd_ref2_f1_b@hd", "98.6")):
        t = P.get(key)
        if t:
            c = t["c"]
            x = (c["refusal1_ms_r0"] - c["mute_off_ms_r0"]) if (c["refusal1_ms_r0"] is not None and
                                                             c["mute_off_ms_r0"] is not None) else None
            out.append("%-100s %s" % ("%s first refusal after rank 0's mute end (doc %s ms); refusals %s" % (
                key, lab, c["n_refused_dial_r0"]), fmt(x)))
    t = P.get("hd_hog_f1_b@hd")
    if t:
        c = t["c"]
        x = (c["fault_after_launch_r0_ms"] - fnum(c["hog_launch_after_launch_ms_r0"])) if (
            c["fault_after_launch_r0_ms"] is not None and fnum(c["hog_launch_after_launch_ms_r0"]) is not None) else None
        out.append("%-100s %s" % ("hog: hook after the filler launch (doc 599 ms)", fmt(x)))
    # listen-gap timings (rank 1 'TEST listen gap off' moved to rank 0's clock)
    for key in ("hd_ref1_f1_b@hd", "hd_ref2_f1_b@hd"):
        t = P.get(key)
        if not t:
            continue
        off = fnum(t["k"][0].get("clock_offset_ms"))
        gap_off = None
        for line in (readf(os.path.join(PILOT, "hd", t["stem"] + "_r1.log")) or "").splitlines():
            m = re.search(r"TEST listen gap off rank=\d+ listening=\d+ errno=\d+ mono_ms=([\d.]+)", line)
            if m:
                gap_off = float(m.group(1)) - off
        refs = t["lg"][0]["redial_ref"]
        rec = t["c"]["reconn_ms_r0"]
        if key.startswith("hd_ref1"):
            x = (refs[0] + 1000.0 - gap_off) if (refs and gap_off is not None) else None
            y = (rec - gap_off) if (rec is not None and gap_off is not None) else None
            out.append("%-100s %s" % ("ref1: refusal + 1000 ms (the next re-dial) after rank 1 re-listens (doc 393 ms); "
                                      "reconnect line after re-listen", (fmt(x), fmt(y))))
        else:
            x = (gap_off - refs[1]) if (gap_off is not None and len(refs) > 1) else None
            out.append("%-100s %s" % ("ref2: re-listen minus the second refusal (doc 1 400 ms)", fmt(x)))
    cud = [t["key"] for t in pt if t["c"]["r0rc"] == "139" or t["c"]["r1rc"] == "139" or t["lg"][0]["cnt"]["cuda"] or
           t["lg"][1]["cnt"]["cuda"]]
    out.append("pilot CUDA faults / rc 139: %s; fw overrun trials outside the fwslow cell: %s" % (
        cud or "none", [t["key"] for t in pt if (t["c"]["n_fwdog_r0"] or t["c"]["n_fwdog_r1"]) and t["key"] != "hd_fwslow_f1_b@hd"] or "none"))
    return out


if __name__ == "__main__":
    main()
