#!/usr/bin/env python3
"""gin-handoff: independent recount of the main run (results/20261009) from the raw per-trial files.

usage: python3 qa/recount.py            (from the study folder or anywhere; prints a Markdown report to stdout)

Read-only: it opens the per-trial files (<stem>_meta.txt, _r0.kv, _r1.kv, _r0.log, _r1.log, _kill.out,
_lat_raw.csv.gz), the hold outputs (hold_*.out, chain.out, snap_*, mlx5_*, fwcmd_*), EXPERIMENT.md, predictions.csv,
PREREG.txt, and the tagged copies of those files through `git cat-file -p` (no filter, no write). It writes nothing.

Written without this study's score.py or rows_hf.py and without ../harden/score.py or ../harden/rows_hd.py; it does
not read SCORE.md or any trials_*.csv. Every column is parsed again from the logs and kv files following the
definitions in EXPERIMENT.md 3.1 (and ../harden/EXPERIMENT.md 3.1, ../scripts/ts2/rows.py, ../s2_close/rows_extra.py,
../oneway/rows_ow.py for the older columns), and every acceptance rule of predictions.csv is evaluated per trial by the
small evaluator below (grammar of ../s2_close/EXPERIMENT.md 3.2: count, has, nonempty, median, abs, "per cell:";
numeric-looking values are floats, blanks are None, any comparison or arithmetic with None is false).
"""
import ast
import collections
import gzip
import hashlib
import os
import re
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
RES = os.path.join(STUDY, "results", "20261009")
PILOT = os.path.join(STUDY, "results", "20261009_pilot")
TAG = "prereg/gin-handoff-v1"
TAG_COMMIT = "c9efc7b9"
PREREG_TIME = "2026-10-09 05:12:42"
BUILDS = ("hf", "hfp", "hd", "hdp")
OUT = []


def out(s=""):
    OUT.append(s)


def scrub(s):
    # never print a dotted-quad address (none is expected in what this script prints)
    return re.sub(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "<addr>", s)


# ---------------------------------------------------------------------------------------------------------------------
# plan (EXPERIMENT.md 7) and cell classes (EXPERIMENT.md 8)
PLAN = collections.OrderedDict([
    ("hd_shrink_b@hf", 10), ("hd_shrink_b@hfp", 5), ("hd_shrink_b@hd", 5),
    ("hf_shrinkoff_b@hf", 5), ("hf_shrinkdc_b@hf", 5),
    ("hf_hog_f1_b@hf", 5), ("hf_hogslack_f1_b@hf", 5), ("hf_hogpre_f1_b@hf", 5), ("hf_hogpreslack_f1_b@hf", 5),
    ("f1_b@hf", 5), ("f3_b@hf", 5), ("bidirf_sym_b@hf", 5), ("f4_b@hf", 5), ("f2rel_b@hf", 5),
    ("hd_rxdeath_b@hf", 5), ("hdp_kill_b@hfp", 5),
    ("lat_4k@hfp", 5), ("lat_4k@hdp", 5), ("lat_4k@hd", 5), ("lat_256k@hfp", 5), ("lat_256k@hdp", 5),
    ("lat_256k@hd", 5)])
HOG = {"hf_hog_f1_b", "hf_hogslack_f1_b", "hf_hogpre_f1_b", "hf_hogpreslack_f1_b"}
R0_HOOK = {"f1_b"} | HOG
R1_HOOK = {"f3_b"}
BOTH_HOOK = {"bidirf_sym_b"}
R1_KILL = {"f4_b", "hd_shrink_b", "hf_shrinkoff_b", "hf_shrinkdc_b", "hdp_kill_b"}
R0_KILL = {"hd_rxdeath_b"}
SWITCH_OFF_R0 = {"hf_shrinkoff_b", "hf_shrinkdc_b"}
RERR = "remote process exited or there was a network error"


def expected_meta(cell, k):
    """What cells.sh / ../harden/cells.sh pass to the runner for trial n<k> (checked against the meta line)."""
    inj = 500 + (k * 137) % 700
    shrink = dict(app="bidir", fault="F4", iters="400", bytes="16384", kill_delay_ms="3500",
                  r0env={"GIN_TS_SHRINK=1", "GIN_TS_HO_WAIT_S=3", "GIN_TS_POST_ABORT_WAIT_S=10"},
                  extra={"GIN_TS_BIDIR_FUSED=1", "GIN_TS_RX_WAIT_S=60"})
    hog = dict(app="default", fault="F1", iters="120", bytes="262144", inject=str(inj),
               extra={"GIN_TS_HOG_MS=3000", "GIN_TS_HOG_PROBE=1"}, r0env=set())
    e = None
    if cell == "hd_shrink_b":
        e = shrink
    elif cell == "hf_shrinkoff_b":
        e = dict(shrink, r0env=shrink["r0env"] | {"NCCL_GIN_SHRINK_HANDOFF=0"})
    elif cell == "hf_shrinkdc_b":
        e = dict(shrink, r0env=shrink["r0env"] | {"NCCL_GIN_SHRINK_HANDOFF=0", "GIN_TS_SHRINK_DEVCOMM_DESTROY=1"})
    elif cell == "hf_hog_f1_b":
        e = dict(hog, r0env={"GIN_TS_SHRINK=1", "GIN_TS_HO_WAIT_S=3"})
    elif cell == "hf_hogslack_f1_b":
        e = dict(hog, extra=hog["extra"] | {"GIN_TS_HOG_SLACK=1"})
    elif cell == "hf_hogpre_f1_b":
        e = dict(hog, extra=hog["extra"] | {"GIN_TS_HOG_PREALLOC=1"})
    elif cell == "hf_hogpreslack_f1_b":
        e = dict(hog, extra=hog["extra"] | {"GIN_TS_HOG_PREALLOC=1", "GIN_TS_HOG_SLACK=1"})
    elif cell == "f1_b":
        e = dict(app="default", fault="F1", iters="120", inject=str(inj), extra=set(), r0env=set())
    elif cell == "f3_b":
        e = dict(app="default", fault="F3", iters="120", inject=str(inj), extra=set(), r0env=set())
    elif cell == "bidirf_sym_b":
        i0 = 60 + (k * 7) % 50
        e = dict(app="bidir", fault="F1both", iters="8000", bytes="4096", gap_us="0", inject=str(i0),
                 inject1=str(i0 - 1 - k % 2), extra={"GIN_TS_BIDIR_FUSED=1"}, r0env=set())
    elif cell in ("f4_b", "hdp_kill_b"):
        e = dict(app="default", fault="F4", iters="200", gap_us="30000", kill_delay_ms=str(3500 + (k * 211) % 900),
                 extra=set(), r0env=set())
    elif cell == "f2rel_b":
        e = dict(app="default", fault="F2", iters="120",
                 extra={"GIN_TS_RX_WAIT_S=20", "GIN_TS_POST_ABORT_WAIT_S=3", "NCCL_GIN_TS_USER_ABORT=1"}, r0env=set())
    elif cell == "hd_rxdeath_b":
        e = dict(app="default", fault="none", iters="1000", bytes="16384", kill_r0="1", kill_delay_ms="3000",
                 extra={"GIN_TS_RX_WAIT_S=15"}, r0env=set())
    elif cell == "lat_4k":
        e = dict(app="default", fault="lat", iters="3000", bytes="4096", gap_us="0", extra=set(), r0env=set())
    elif cell == "lat_256k":
        e = dict(app="default", fault="lat", iters="3000", bytes="262144", gap_us="0", extra=set(), r0env=set())
    return e


# ---------------------------------------------------------------------------------------------------------------------
# parsing
KEY = re.compile(r"(?:^| )(\w+)=")


def read_kv(path):
    """key=value pairs; a value runs (blanks included) up to the next ' <word>=' or the end of the line; last wins."""
    d = {}
    if not os.path.exists(path):
        return d
    with open(path, errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            ms = list(KEY.finditer(line))
            for i, m in enumerate(ms):
                end = ms[i + 1].start() if i + 1 < len(ms) else len(line)
                d[m.group(1)] = line[m.end():end].strip().strip('"')
    return d


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


RX = {
    "fire": re.compile(r"GIN/FAULT: GDAKI fault fired.*?fire_mono_ms=([\d.]+)"),
    "q4": re.compile(r"device-classified error CQE.*?\bmono_ms=([\d.]+)"),
    "rec": re.compile(r"GIN/TS: recovered .*?\brole=(\w+)"),
    "decl": re.compile(r"GIN/TS: declined .*?reason=\"([^\"]*)\".*?mono_ms=([\d.]+)"),
    "oneway": re.compile(r"GIN/TS: helper liveness oneway=(\d) rank="),
    "harden": re.compile(r"GIN/TS: harden=1 rank=(\d+) .*?production=(\d)"),
    "handoff": re.compile(r"GIN/TS: handoff=1 rank=(\d+) shrink_handoff=(\d)"),
    "hoff_ok": re.compile(r"GIN/TS: rank \d+: aborting shrink proceeds past the parent's GIN error, raised for "
                          r"rank\(s\) (\S+), all excluded"),
    "hoff_keep": re.compile(r"GIN/TS: rank \d+: aborting shrink keeps the parent's error \((.*)\) mono_ms="),
    "surface": re.compile(r"GIN/TS: watchdog rank=\d+: (.*); the fault surfaces.*?mono_ms=([\d.]+)"),
    "copyto": re.compile(r"GIN/TS: rank \d+: device-state copy \((.*?)\) not complete after (\d+) ms "
                         r"\(NCCL_GIN_TS_COPY_MS\).*?mono_ms=([\d.]+)"),
    "fwdog": re.compile(r"GIN/TS: watchdog rank=\d+: firmware command phase (\S+) has run ([\d.]+) ms"),
    "judged": re.compile(r"GIN/TS: rank \d+: rank \d+ judged dead \(cause=(\w+)\) mono_ms=([\d.]+)"),
    "ts_stamp": re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\]"),
    "done": re.compile(r"\[rank\d\] DONE outcome=(\S+) exit=(\d+) progress=(\d+)/(\d+)"),
}
CUDA_FAULT = re.compile(r"illegal address|illegal memory access|unspecified launch failure", re.I)


def read_log(path):
    o = dict(fires=[], trigger_miss=0, q4=[], rec_roles=[], decl=[], ts_on=0, ts_off=0, ua=0, oneway="", hd_on=0,
             prod="", hf_on=0, hf_switch="", hoff_ok=[], hoff_keep=[], surface=[], surface_ms=[], late_copy=0,
             copyto=[], fwdog=[], judged=[], test=0, mute=0, cuda=0, bind=0, first_ts=None, done=None, cannot_set=0,
             lines=0)
    if not os.path.exists(path):
        return o
    with open(path, errors="replace") as f:
        for line in f:
            o["lines"] += 1
            if o["first_ts"] is None:
                m = RX["ts_stamp"].search(line)
                if m:
                    o["first_ts"] = m.group(1)
            if "bind: Address already in use" in line:
                o["bind"] = 1
            if CUDA_FAULT.search(line):
                o["cuda"] += 1
            if "GIN/" not in line and "DONE outcome" not in line:
                continue
            m = RX["fire"].search(line)
            if m:
                o["fires"].append(float(m.group(1)))
            if "GIN/FAULT: shot 1 trigger not reached" in line:
                o["trigger_miss"] += 1
            m = RX["q4"].search(line)
            if m:
                o["q4"].append(float(m.group(1)))
            m = RX["rec"].search(line)
            if m:
                o["rec_roles"].append(m.group(1))
            m = RX["decl"].search(line)
            if m:
                o["decl"].append((m.group(1), float(m.group(2))))
            if "GIN/TS: transparent recovery ON" in line:
                o["ts_on"] += 1
            if "GIN/TS: transparent recovery OFF" in line:
                o["ts_off"] += 1
            if "GIN/TS: user devComm abort flag set" in line:
                o["ua"] += 1
            m = RX["oneway"].search(line)
            if m and o["oneway"] == "":
                o["oneway"] = m.group(1)
            m = RX["harden"].search(line)
            if m:
                o["hd_on"] = 1
                o["prod"] = m.group(2)
            m = RX["handoff"].search(line)
            if m:
                o["hf_on"] = 1
                o["hf_switch"] = m.group(2)
            m = RX["hoff_ok"].search(line)
            if m:
                o["hoff_ok"].append(m.group(1))
            m = RX["hoff_keep"].search(line)
            if m:
                o["hoff_keep"].append(m.group(1))
            m = RX["surface"].search(line)
            if m:
                o["surface"].append(m.group(1))
                o["surface_ms"].append(float(m.group(2)))
            if "the late device-state copy completed" in line:
                o["late_copy"] += 1
            m = RX["copyto"].search(line)
            if m:
                o["copyto"].append((m.group(1), int(m.group(2)), float(m.group(3))))
            m = RX["fwdog"].search(line)
            if m:
                o["fwdog"].append((m.group(1), float(m.group(2))))
            m = RX["judged"].search(line)
            if m:
                o["judged"].append((m.group(1), float(m.group(2))))
            if "GIN/TS: TEST" in line:
                o["test"] += 1
            if "socket mute on" in line:
                o["mute"] += 1
            if "cannot set the device error state" in line:
                o["cannot_set"] += 1
            m = RX["done"].search(line)
            if m:
                o["done"] = m.groups()
    return o


def rank_ok(k, iters, sender, receiver):
    """../scripts/ts2/rows.py: the per-rank part of transparent_ok."""
    if k.get("outcome") != "ok" or k.get("async_first") != "none":
        return False
    if sender and not (k.get("tx_done") == str(iters) and k.get("tx_rc") == "no error"):
        return False
    if receiver and not (k.get("rx_done") == str(iters) and k.get("rx_rc") == "no error" and
                         k.get("dev_bad_slots") == "0" and k.get("host_bad_slots") == "0" and
                         k.get("signal_exact") == "1"):
        return False
    return True


def p50_raw(path):
    """p50 of the raw latencies (ns) as the driver's latStats computes it: sorted[(int)(0.5 * (n - 1) + 0.5)] / 1e3."""
    if not os.path.exists(path):
        return None, 0
    v = []
    with gzip.open(path, "rt") as f:
        for line in f:
            p = line.strip().split(",")
            if len(p) == 2:
                v.append(int(p[1]))
    if not v:
        return None, 0
    v.sort()
    return round(v[int(0.5 * (len(v) - 1) + 0.5)] / 1e3, 2), len(v)


def load_trial(folder, meta_path):
    stem = meta_path[: -len("_meta.txt")]
    m = read_kv(meta_path)
    k0, k1 = read_kv(stem + "_r0.kv"), read_kv(stem + "_r1.kv")
    l0, l1 = read_log(stem + "_r0.log"), read_log(stem + "_r1.log")
    kill = read_kv(stem + "_kill.out")
    cell, build = m.get("cell", ""), m.get("build", "")
    iters = int(m.get("iters", "0") or 0)
    bidir = m.get("app") == "bidir"
    off = fnum(k0.get("clock_offset_ms"))  # rank 1 clock - rank 0 clock
    t = {"folder": folder, "stem": os.path.basename(stem), "cell": cell, "build": build, "key": cell + "@" + build,
         "trial": m.get("trial", ""), "n": int(m.get("trial", "n0")[1:] or 0), "meta": m, "k0": k0, "k1": k1,
         "l0": l0, "l1": l1, "kill": kill}
    r = {}
    # ../scripts/ts2/rows.py columns
    r["transparent_ok"] = int(rank_ok(k0, iters, True, bidir) and rank_ok(k1, iters, bidir, True))
    r["r1_outcome"] = k1.get("outcome", "")
    r["rx_rc"] = k1.get("rx_rc", "")
    r["rec_init_r0"] = sum(1 for x in l0["rec_roles"] if x == "initiator")
    r["rec_init_r1"] = sum(1 for x in l1["rec_roles"] if x == "initiator")
    r["decl_r0"] = ";".join(x[0] for x in l0["decl"])
    r["decl_r1"] = ";".join(x[0] for x in l1["decl"])
    r["teardown_r0"], r["teardown_r1"] = k0.get("abort_ret", ""), k1.get("abort_ret", "")
    r["teardown_ms_r0"], r["teardown_ms_r1"] = k0.get("teardown_ms", ""), k1.get("teardown_ms", "")
    r["lat_p50_us"] = k0.get("lat_p50_us", "")
    r["ts_on_r0"], r["ts_on_r1"] = l0["ts_on"], l1["ts_on"]
    r["n_fires_r0"], r["n_fires_r1"] = len(l0["fires"]), len(l1["fires"])
    r["trigger_miss"] = l0["trigger_miss"] + l1["trigger_miss"]
    r["bind_fail"] = l0["bind"]
    # ../s2_close/rows_extra.py, ../oneway/rows_ow.py
    r["ua_r0"], r["ua_r1"] = l0["ua"], l1["ua"]
    r["killed"] = 1 if kill.get("kill_mono_ms") else 0
    r["r0_killed"] = 1 if (kill.get("kill_mono_ms") and kill.get("rank") == "0") else 0
    r["ow_mode_r0"], r["ow_mode_r1"] = l0["oneway"], l1["oneway"]
    # ../harden EXPERIMENT.md 3.1 columns (re-implemented from the definitions)
    for rk, lg, kv in ((0, l0, k0), (1, l1, k1)):
        r["hd_on_r%d" % rk] = lg["hd_on"]
        r["prod_r%d" % rk] = lg["prod"]
        r["n_judged_r%d" % rk] = len(lg["judged"])
        r["n_copyto_r%d" % rk] = len(lg["copyto"])
        r["n_fwdog_r%d" % rk] = len(lg["fwdog"])
        r["rx_phantom_r%d" % rk] = kv.get("rx_phantom", "")
        for key, val in kv.items():
            if key.startswith("rs_") or key.startswith("hog_") or key.startswith("probe_"):
                r["%s_r%d" % (key, rk)] = val
        # this study's columns (EXPERIMENT.md 3.1, rows_hf.py summary)
        r["hf_on_r%d" % rk] = lg["hf_on"]
        r["hf_switch_r%d" % rk] = lg["hf_switch"]
        r["n_surface_r%d" % rk] = len(lg["surface"])
        r["surface_why_r%d" % rk] = lg["surface"][0] if lg["surface"] else ""
        r["n_late_copy_r%d" % rk] = lg["late_copy"]
    for key, val in k0.items():
        if key.startswith("ho_"):
            r[key] = val
    r["n_hoff_ok_r0"] = len(l0["hoff_ok"])
    r["hoff_ranks_r0"] = l0["hoff_ok"][0] if l0["hoff_ok"] else ""
    r["n_hoff_keep_r0"] = len(l0["hoff_keep"])
    r["hoff_why_r0"] = l0["hoff_keep"][0] if l0["hoff_keep"] else ""
    r["left_rules"] = m.get("left_rules", "")
    # times
    la0, la1 = fnum(k0.get("launch_mono_ms")), fnum(k1.get("launch_mono_ms"))
    r["fault_after_launch_r0_ms"] = (l0["fires"][0] - la0) if (l0["fires"] and la0 is not None) else ""
    km = fnum(kill.get("kill_mono_ms"))
    r["decl_after_kill_ms_r0"] = ""
    if km is not None and kill.get("rank") != "0" and off is not None and l0["decl"]:
        r["decl_after_kill_ms_r0"] = l0["decl"][0][1] - (km - off)  # rank 1 kill (sunny clock) moved to rank 0's
    r["release_after_kill_ms_r1"] = r["async_after_kill_ms_r1"] = ""
    if km is not None and kill.get("rank") == "0" and off is not None and la1 is not None:
        k_r1 = km + off  # rank 0 kill (rain clock) moved to rank 1's clock
        kms1 = fnum(k1.get("kernel_ms"))
        if kms1 is not None:
            r["release_after_kill_ms_r1"] = la1 + kms1 - k_r1
        if k1.get("async_first") not in (None, "", "none") and fnum(k1.get("async_first_ms_after_launch")) is not None:
            r["async_after_kill_ms_r1"] = la1 + float(k1["async_first_ms_after_launch"]) - k_r1
    t["row"] = r
    t["lat_raw_p50"], t["lat_raw_n"] = p50_raw(stem + "_lat_raw.csv.gz")
    return t


def load_dir(d):
    trials = []
    for b in BUILDS:
        p = os.path.join(d, b)
        if not os.path.isdir(p):
            continue
        for fn in sorted(os.listdir(p)):
            if fn.endswith("_meta.txt"):
                trials.append(load_trial(b, os.path.join(p, fn)))
    return trials


# ---------------------------------------------------------------------------------------------------------------------
# exclusions (EXPERIMENT.md 8) and the setting checks
def status_of(t):
    r, c = t["row"], t["cell"]
    if r["bind_fail"] == 1:
        return "excluded", "bind_fail (NCCL init failed: port in use)"
    if c in R0_HOOK and r["n_fires_r0"] == 0:
        return "excluded", "fault not applied (n_fires_r0 == 0)"
    if c in R1_HOOK and r["n_fires_r1"] == 0:
        return "excluded", "fault not applied (n_fires_r1 == 0)"
    if c in BOTH_HOOK and (r["n_fires_r0"] == 0 or r["n_fires_r1"] == 0):
        return "excluded", "fault not applied (a rank did not fire)"
    if r["trigger_miss"] > 0:
        return "excluded", "trigger_miss > 0"
    if c in R1_KILL and r["killed"] != 1:
        return "excluded", "killed != 1"
    if c in R0_KILL and r["r0_killed"] != 1:
        return "excluded", "r0_killed != 1"
    if c in HOG:
        fa, hl = fnum(r["fault_after_launch_r0_ms"]), fnum(r.get("hog_launch_after_launch_ms_r0"))
        if fa is None or hl is None or not (hl < fa < hl + 3000):
            return "excluded", "order not applied (fault outside the GPU-filling kernel's 3 s window)"
    for rk in (0, 1):
        # a blank rs_fw_overruns (a killed rank has no stats) is not an overrun
        if r["n_fwdog_r%d" % rk] != 0 or (fnum(r.get("rs_fw_overruns_r%d" % rk)) or 0) != 0:
            return "excluded", "firmware overrun (rank %d)" % rk
    return "judged", ""


def killed_rank(t):
    if t["cell"] in R1_KILL:
        return 1
    if t["cell"] in R0_KILL:
        return 0
    return None


def setting_problems(t):
    r, b, c = t["row"], t["build"], t["cell"]
    p = []
    alive = [rk for rk in (0, 1) if rk != killed_rank(t)]
    if b == "hf":
        for rk in alive:
            if r["hd_on_r%d" % rk] != 1 or r["prod_r%d" % rk] != "0":
                p.append("r%d: no gin-harden start line with production=0" % rk)
            if r["hf_on_r%d" % rk] != 1:
                p.append("r%d: no handoff=1 start line" % rk)
            want = "0" if (c in SWITCH_OFF_R0 and rk == 0) else "1"
            if r["hf_switch_r%d" % rk] != want:
                p.append("r%d: shrink_handoff=%s, want %s" % (rk, r["hf_switch_r%d" % rk], want))
    if b == "hd":
        for rk in alive:
            if r["hd_on_r%d" % rk] != 1 or r["prod_r%d" % rk] != "0":
                p.append("r%d: no gin-harden start line with production=0" % rk)
            if r["hf_on_r%d" % rk] != 0:
                p.append("r%d: handoff start line present on hd" % rk)
    if b in ("hf", "hd"):
        for rk in alive:
            if r["ts_on_r%d" % rk] < 1:
                p.append("r%d: no transparent recovery ON line" % rk)
            if r["ua_r%d" % rk] < 1:
                p.append("r%d: no user devComm abort flag line" % rk)
            if r["ow_mode_r%d" % rk] != "1":
                p.append("r%d: no oneway=1 line" % rk)
        for rk, lg in ((0, t["l0"]), (1, t["l1"])):
            if lg["test"] or lg["mute"]:
                p.append("r%d: test-switch or mute line present (%d, %d)" % (rk, lg["test"], lg["mute"]))
    if b in ("hfp", "hdp"):
        for rk in alive:
            if r["hd_on_r%d" % rk] != 0 or r["hf_on_r%d" % rk] != 0:
                p.append("r%d: a start line shows at WARN in a production build" % rk)
            if r.get("rs_api_r%d" % rk) != "1" or (fnum(r.get("rs_contexts_r%d" % rk)) or 0) < 1:
                p.append("r%d: rs_api/rs_contexts not as required" % rk)
    if r["left_rules"] != "0":
        p.append("left_rules=%s" % r["left_rules"])
    if t["meta"].get("left") != "0":
        p.append("left=%s" % t["meta"].get("left"))
    return p


def meta_problems(t):
    m, c = t["meta"], t["cell"]
    e = expected_meta(c, t["n"])
    if e is None:
        return ["cell not in the plan"]
    p = []
    if not m.get("bundle", "").endswith("/gin_ts2/" + t["build"]):
        p.append("bundle %s" % m.get("bundle"))
    if t["folder"] != t["build"]:
        p.append("folder %s != build %s" % (t["folder"], t["build"]))
    for k, v in e.items():
        if k in ("r0env", "extra"):
            have = set(x for x in m.get(k, "").split("+") if x)
            if have != v:
                p.append("%s %s, want %s" % (k, sorted(have), sorted(v)))
        elif m.get(k) != v:
            p.append("%s=%s, want %s" % (k, m.get(k), v))
    if m.get("r1env", "") != "":
        p.append("r1env=%s" % m.get("r1env"))
    if m.get("ts") != "1" or m.get("ib_timeout") != "14" or m.get("mgmt_mute", "") != "":
        p.append("ts/ib_timeout/mgmt_mute not as defined")
    return p


# ---------------------------------------------------------------------------------------------------------------------
# the acceptance-rule evaluator (grammar of ../s2_close/EXPERIMENT.md 3.2)
def conv(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v)
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return s


class TrialEval:
    """Evaluates the expression inside count(...) for one trial row."""

    def __init__(self, row, used):
        self.row, self.used = row, used

    def raw(self, node):
        if not isinstance(node, ast.Name):
            raise ValueError("field argument must be a column name")
        self.used.add(node.id)
        return self.row.get(node.id)

    def ev(self, n):
        if isinstance(n, ast.BoolOp):
            vals = (bool(self.ev(v)) for v in n.values)
            return all(vals) if isinstance(n.op, ast.And) else any(vals)
        if isinstance(n, ast.UnaryOp):
            x = self.ev(n.operand)
            if isinstance(n.op, ast.Not):
                return not bool(x)
            if isinstance(n.op, ast.USub):
                return None if not isinstance(x, float) else -x
            raise ValueError("unary op")
        if isinstance(n, ast.Compare):
            vals = [self.ev(n.left)] + [self.ev(c) for c in n.comparators]
            for op, a, b in zip(n.ops, vals, vals[1:]):
                if a is None or b is None:
                    return False
                try:
                    ok = {ast.Eq: lambda x, y: x == y, ast.NotEq: lambda x, y: x != y, ast.Lt: lambda x, y: x < y,
                          ast.LtE: lambda x, y: x <= y, ast.Gt: lambda x, y: x > y,
                          ast.GtE: lambda x, y: x >= y}[type(op)](a, b)
                except TypeError:
                    return False
                if not ok:
                    return False
            return True
        if isinstance(n, ast.BinOp):
            a, b = self.ev(n.left), self.ev(n.right)
            if not isinstance(a, float) or not isinstance(b, float):
                return None
            if isinstance(n.op, ast.Add):
                return a + b
            if isinstance(n.op, ast.Sub):
                return a - b
            if isinstance(n.op, ast.Mult):
                return a * b
            if isinstance(n.op, ast.Div):
                return a / b if b else None
            raise ValueError("binary op")
        if isinstance(n, ast.Name):
            self.used.add(n.id)
            return conv(self.row.get(n.id))
        if isinstance(n, ast.Constant):
            return conv(n.value) if isinstance(n.value, (int, float)) else n.value
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            f = n.func.id
            if f == "has":
                v = self.raw(n.args[0])
                s = n.args[1].value
                return v not in (None, "") and s in str(v)
            if f == "nonempty":
                return self.raw(n.args[0]) not in (None, "")
            if f == "abs":
                x = self.ev(n.args[0])
                return abs(x) if isinstance(x, float) else None
        raise ValueError("unsupported node %s" % ast.dump(n))


class RuleEval:
    """Evaluates one acceptance rule for one cell key (count over the judged trials; median over named cells)."""

    def __init__(self, judged, cellkey):
        self.judged, self.cellkey, self.used = judged, cellkey, set()
        self.hits, self.missed, self.medians = None, [], {}

    def ev(self, n):
        if isinstance(n, ast.Compare):
            vals = [self.ev(n.left)] + [self.ev(c) for c in n.comparators]
            for op, a, b in zip(n.ops, vals, vals[1:]):
                if a is None or b is None:
                    return False
                ok = {ast.Eq: a == b, ast.NotEq: a != b, ast.Lt: a < b, ast.LtE: a <= b, ast.Gt: a > b,
                      ast.GtE: a >= b}[type(op)]
                if not ok:
                    return False
            return True
        if isinstance(n, ast.BinOp):
            a, b = self.ev(n.left), self.ev(n.right)
            if a is None or b is None:
                return None
            return a - b if isinstance(n.op, ast.Sub) else a + b
        if isinstance(n, ast.Constant):
            return float(n.value)
        if isinstance(n, ast.Call):
            f = n.func.id
            if f == "count":
                c, missed = 0, []
                for t in self.judged[self.cellkey]:
                    if TrialEval(t["row"], self.used).ev(n.args[0]):
                        c += 1
                    else:
                        missed.append(t["stem"])
                self.hits, self.missed = c, missed
                return float(c)
            if f == "median":
                field, ck = n.args[0].id, n.args[1].value
                self.used.add(field)
                vals = [conv(t["row"].get(field)) for t in self.judged.get(ck, [])]
                vals = [v for v in vals if isinstance(v, float)]
                med = statistics.median(vals) if vals else None
                self.medians[ck] = (med, len(vals))
                return med
            if f == "abs":
                x = self.ev(n.args[0])
                return None if x is None else abs(x)
        raise ValueError("unsupported node %s" % ast.dump(n))


def split_csv_line(text):
    import csv
    import io
    return list(csv.DictReader(io.StringIO(text)))


def evaluate_predictions(preds, judged, counts, known_cols):
    res = []
    for p in preds:
        acc = p["acceptance"].strip()
        per_cell = acc.startswith("per cell:")
        expr = acc[len("per cell:"):].strip() if per_cell else acc
        cells = [c.strip() for c in p["cells"].split(";")]
        tree = ast.parse(expr, mode="eval").body
        rows = []
        if per_cell or len(cells) == 1:
            for ck in cells:
                ev = RuleEval(judged, ck)
                n = len(judged.get(ck, []))
                if n < PLAN[ck] or counts[ck].get("stopped"):
                    rows.append((ck, n, None, "insufficient data", []))
                    continue
                ok = ev.ev(tree)
                unknown = sorted(c for c in ev.used if c not in known_cols)
                rows.append((ck, n, ev.hits, "holds" if ok else "fails", ev.missed, unknown))
        else:  # one rule over several cell keys (median of each)
            ev = RuleEval(judged, None)
            short = [ck for ck in cells if len(judged.get(ck, [])) < PLAN[ck]]
            if short:
                rows.append((" vs ".join(cells), None, None, "insufficient data", []))
            else:
                ok = ev.ev(tree)
                rows.append((" vs ".join(cells), ev.medians, None, "holds" if ok else "fails", []))
        verdict = ("insufficient data" if any(x[3] == "insufficient data" for x in rows) else
                   "holds" if all(x[3] == "holds" for x in rows) else "fails")
        res.append((p, rows, verdict))
    return res


# ---------------------------------------------------------------------------------------------------------------------
def git_blob(path_in_repo):
    return subprocess.run(["git", "-C", STUDY, "cat-file", "-p", "%s:%s" % (TAG, path_in_repo)],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout


def git_out(*args):
    return subprocess.run(["git", "-C", STUDY] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          check=True).stdout.decode().strip()


def sections(md_bytes, numbers):
    """the bytes of '## <n>. ' sections (each up to the next '## ' heading)."""
    text = md_bytes.decode("utf-8")
    heads = [(m.start(), m.group(1)) for m in re.finditer(r"(?m)^## (\d+)\. ", text)]
    outd = {}
    for i, (pos, num) in enumerate(heads):
        end = heads[i + 1][0] if i + 1 < len(heads) else len(text)
        if num in numbers:
            outd[num] = text[pos:end].encode("utf-8")
    return outd


def norm_addr(b):
    return re.sub(rb"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", b"<addr>", b)


def integrity():
    out("## Integrity")
    out()
    top = git_out("rev-parse", "--show-toplevel")
    rel = os.path.relpath(STUDY, top)
    commit = git_out("rev-parse", TAG + "^{commit}")
    out("- [measured] tag `%s` -> commit `%s` (%s)" % (TAG, commit[:8], "as stated" if commit.startswith(TAG_COMMIT)
                                                         else "DIFFERS from " + TAG_COMMIT))
    wt = open(os.path.join(STUDY, "predictions.csv"), "rb").read()
    tg = git_blob(rel + "/predictions.csv")
    prereg = open(os.path.join(STUDY, "PREREG.txt")).read()
    m = re.search(r"\b([0-9a-f]{64})\s+predictions\.csv", prereg)
    h_wt, h_tg = hashlib.sha256(wt).hexdigest(), hashlib.sha256(tg).hexdigest()
    h_pr = m.group(1) if m else None
    out("- [measured] sha256 predictions.csv: working tree `%s`, tag `%s`, PREREG.txt `%s` -> %s" %
        (h_wt[:16], h_tg[:16], (h_pr or "none")[:16],
         "all equal" if h_wt == h_tg == h_pr else "MISMATCH"))
    pr_tag = git_blob(rel + "/PREREG.txt")
    out("- [measured] PREREG.txt equals the tag's copy: %s" % (pr_tag == prereg.encode()))
    wt_md = open(os.path.join(STUDY, "EXPERIMENT.md"), "rb").read()
    tg_md = git_blob(rel + "/EXPERIMENT.md")
    s_wt, s_tg = sections(wt_md, {"2", "3", "7", "8"}), sections(tg_md, {"2", "3", "7", "8"})
    for num in ("2", "3", "7", "8"):
        a, b = s_wt.get(num), s_tg.get(num)
        out("- [measured] EXPERIMENT.md section %s: %d bytes, byte-identical to the tag: %s" %
            (num, len(a or b""), a is not None and a == b))
    out("- [measured] EXPERIMENT.md whole file byte-identical to the tag: %s (sha256 `%s`)" %
        (wt_md == tg_md, hashlib.sha256(wt_md).hexdigest()[:16]))
    for f in ("cells.sh", "hold.sh", "chain.sh", "../harden/cells.sh", "../harden/run_trial_hd.sh", "../gin_ts2.cu"):
        p = os.path.normpath(os.path.join(rel, f))
        a = open(os.path.join(top, p), "rb").read()
        b = git_blob(p)
        same = a == b
        same_n = norm_addr(a) == norm_addr(b)
        out("- [measured] `%s` vs tag: %s" % (f, "identical" if same else
                                              "identical up to the management-address filter" if same_n else
                                              "DIFFERS"))
    md5 = hashlib.md5(open(os.path.join(STUDY, "..", "gin_ts2.cu"), "rb").read()).hexdigest()
    out("- [measured] `../gin_ts2.cu` md5 `%s` (EXPERIMENT.md 5: `1e4fd2f48ef9f42343ea672d3388fa23`): %s" %
        (md5, md5 == "1e4fd2f48ef9f42343ea672d3388fa23"))
    out()


def hold_plan(h, spec=None):
    seq = []
    if h == "H1":
        for k in range(1, 6):
            seq += [("hd_shrink_b", "hf", 2 * k - 1), ("hd_shrink_b", "hf", 2 * k), ("hd_shrink_b", "hd", k),
                    ("hd_shrink_b", "hfp", k), ("hf_shrinkoff_b", "hf", k), ("hf_shrinkdc_b", "hf", k)]
    elif h == "H2":
        for k in range(1, 6):
            seq += [(x, "hf", k) for x in ("hf_hog_f1_b", "hf_hogslack_f1_b", "hf_hogpre_f1_b",
                                           "hf_hogpreslack_f1_b")]
    elif h == "H3":
        for x in ("f1_b", "f3_b", "bidirf_sym_b", "f4_b", "f2rel_b", "hd_rxdeath_b"):
            seq += [(x, "hf", k) for k in range(1, 6)]
        seq += [("hdp_kill_b", "hfp", k) for k in range(1, 6)]
    elif h == "H4":
        for k in range(1, 6):
            for x in ("lat_4k", "lat_256k"):
                seq += [(x, b, k) for b in ("hfp", "hdp", "hd")]
    elif h == "fill":
        for it in spec.split(","):
            sub, cb, n, st = it.split(":")
            cell, b = cb.split("@")
            seq += [(cell, b, k) for k in range(int(st), int(st) + int(n))]
    return seq


RES_LINE = re.compile(r"^\[(\w+)/ts\d/\w+/\w+/\w+#(n\d+)\] r0rc=(\d+) r1rc=(\d+) left=(\d+) left_rules=(\d+) "
                      r"wall=([\d.]+)s :: (.*)$")
KILL_LINE = re.compile(r"^\[(\w+)/ts\d/\w+/\w+/\w+#(n\d+)\] SIGKILL rank(\d) after (\d+) ms: kill_mono_ms=([\d.]+)")


def holds_check(by_id):
    out("## Hold logs against the trial files")
    out()
    chain = open(os.path.join(RES, "chain.out")).read()
    fill_spec = None
    m = re.search(r"hold fill:(\S+) start", chain)
    if m:
        fill_spec = m.group(1)
    probs, n_lines, windows = [], 0, {}
    for h in ("H1", "H2", "H3", "H4", "fill"):
        path = os.path.join(RES, "hold_%s.out" % h)
        lines = open(path, errors="replace").read().splitlines()
        b = next((re.search(r"(\d\d:\d\d:\d\d)$", x).group(1) for x in lines if x.startswith("== before-")), None)
        a = next((re.search(r"(\d\d:\d\d:\d\d)$", x).group(1) for x in lines if x.startswith("== after-")), None)
        windows[h] = (b, a)
        plan = hold_plan(h, fill_spec)
        res, kills = [], {}
        for x in lines:
            mk = KILL_LINE.match(x)
            if mk:
                kills[len(res)] = mk.groups()
            mr = RES_LINE.match(x)
            if mr:
                res.append((mr.groups(), kills.get(len(res))))
        n_lines += len(res)
        if len(res) != len(plan):
            probs.append("%s: %d result lines, plan %d" % (h, len(res), len(plan)))
        for (g, kl), (cell, build, k) in zip(res, plan):
            t = by_id.get((cell, build, k))
            if t is None:
                probs.append("%s: no trial files for %s@%s n%d" % (h, cell, build, k))
                continue
            t["hold"] = h
            mt = t["meta"]
            if g[0] != build or g[1] != "n%d" % k:
                probs.append("%s: line [%s#%s] vs plan %s@%s n%d" % (h, g[0], g[1], cell, build, k))
            for name, val in zip(("r0rc", "r1rc", "left", "left_rules", "wall_s"), g[2:7]):
                if mt.get(name) != val:
                    probs.append("%s %s: hold %s=%s, meta %s" % (h, t["stem"], name, val, mt.get(name)))
            if kl is not None and t["kill"].get("kill_mono_ms") != kl[4]:
                probs.append("%s %s: hold kill %s, kill.out %s" % (h, t["stem"], kl[4], t["kill"].get("kill_mono_ms")))
            ts = t["l0"]["first_ts"] or t["l1"]["first_ts"]
            if ts and b and a and not (b <= ts[11:] <= a):
                probs.append("%s %s: first log time %s outside the hold window %s-%s" % (h, t["stem"], ts, b, a))
    out("- [measured] result lines in hold_H1-H4.out and hold_fill.out: %d; each matched in order to the trial that "
        "hold.sh runs at that position (build, trial number, r0rc, r1rc, left, left_rules, wall_s, kill time, first "
        "log time inside the hold's snapshot window)" % n_lines)
    out("- [measured] hold windows (before/after snapshot): " +
        ", ".join("%s %s-%s" % (h, w[0], w[1]) for h, w in windows.items()))
    out("- [measured] fill spec from chain.out: `%s`" % fill_spec)
    out("- mismatches: %s" % ("none" if not probs else ""))
    for p in probs:
        out("  - %s" % p)
    out()
    return probs


def snapshots_check():
    out("## Stop criteria from the snapshots and logs")
    out()

    def cmderr(path):
        n = 0
        for x in open(path, errors="replace"):
            if "mlx5" in x.lower() and re.search(r"cmd|command", x, re.I) and re.search(r"failed|timeout|leak", x, re.I):
                n += 1
        return n

    def fwfail(path):
        s = 0
        for x in open(path, errors="replace"):
            for m in re.finditer(r"\b(failed|failed_mbox_status)=(\d+)", x):
                s += int(m.group(2))
        return s

    def ipt(path):
        m = re.search(r"iptables rules: (\d+)", open(path).read())
        return int(m.group(1)) if m else None

    tags = ("H1", "H2", "H3", "H4", "fill")
    rows = []
    for h in tags:
        new = []
        for node in ("rain", "sunny"):
            bf = collections.Counter(open(os.path.join(RES, "mlx5_before-%s_%s.txt" % (h, node)), errors="replace"))
            af = collections.Counter(open(os.path.join(RES, "mlx5_after-%s_%s.txt" % (h, node)), errors="replace"))
            new += list((af - bf).elements())
        ce = [(cmderr(os.path.join(RES, "mlx5_%s-%s_%s.txt" % (w, h, nd)))) for w in ("before", "after")
              for nd in ("rain", "sunny")]
        fw = [fwfail(os.path.join(RES, "fwcmd_%s-%s.txt" % (w, h))) for w in ("before", "after")]
        ip = [ipt(os.path.join(RES, "snap_%s-%s.txt" % (w, h))) for w in ("before", "after")]
        rows.append((h, len(new), ce, fw, ip))
        out("- [measured] hold %s: new mlx5 lines %d; command-error lines rain %d->%d, sunny %d->%d; rain firmware "
            "command failures %d->%d; gin-harden- iptables rules %s->%s" %
            (h, len(new), ce[0], ce[2], ce[1], ce[3], fw[0], fw[1], ip[0], ip[1]))
    between = []
    seq = list(tags)
    for x, y in zip(seq, seq[1:]):
        for node in ("rain", "sunny"):
            a = collections.Counter(open(os.path.join(RES, "mlx5_after-%s_%s.txt" % (x, node)), errors="replace"))
            b = collections.Counter(open(os.path.join(RES, "mlx5_before-%s_%s.txt" % (y, node)), errors="replace"))
            for line in (b - a).elements():
                between.append("%s, between %s and %s: %s" % (node, x, y, line.strip()[:160]))
    out("- [measured] mlx5 kernel lines that appeared between holds (outside every hold window): %d" % len(between))
    for x in between:
        out("  - %s" % x)
    stops = [f for f in ("STOP_mlx5", "STOP_iptables", "STOP_cuda") if os.path.exists(os.path.join(RES, f))]
    out("- [measured] STOP files: %s" % (", ".join(stops) if stops else "none"))
    out()
    return between


def recount():
    trials = load_dir(RES)
    by_id = {(t["cell"], t["build"], t["n"]): t for t in trials}
    known_cols = set()
    for t in trials:
        known_cols |= set(t["row"].keys())

    out("# gin-handoff independent recount (printed by qa/recount.py)")
    out()
    integrity()

    # ---- inventory
    out("## Trial set against EXPERIMENT.md 7")
    out()
    files = collections.Counter(t["key"] for t in trials)
    out("| cell key | plan | trial files | trial numbers |")
    out("|---|--:|--:|---|")
    for ck, n in PLAN.items():
        ns = sorted(t["n"] for t in trials if t["key"] == ck)
        out("| `%s` | %d | %d | %s |" % (ck, n, files.get(ck, 0), ",".join("n%d" % x for x in ns)))
    extra = sorted(set(files) - set(PLAN))
    out()
    out("- [measured] trial files: %d (cell trials %d, latency runs %d); cell keys outside the plan: %s" %
        (len(trials), sum(1 for t in trials if not t["cell"].startswith("lat_")),
         sum(1 for t in trials if t["cell"].startswith("lat_")), extra or "none"))
    mp = [(t["stem"] + "@" + t["build"], meta_problems(t)) for t in trials]
    mp = [x for x in mp if x[1]]
    out("- [measured] runner arguments in every meta line against cells.sh / ../harden/cells.sh (app, fault, iters, "
        "bytes, inject, kill delay, r0env, extra, bundle): %s" % ("all as defined" if not mp else "%d differ" % len(mp)))
    for s, p in mp:
        out("  - %s: %s" % (s, "; ".join(p)))
    first = sorted(t["l0"]["first_ts"] or t["l1"]["first_ts"] or "" for t in trials if
                   (t["l0"]["first_ts"] or t["l1"]["first_ts"]))
    out("- [measured] first log time of the main-run trials: %s to %s (pre-registration %s)" %
        (first[0], first[-1], PREREG_TIME))
    out()
    hold_probs = holds_check(by_id)
    between = snapshots_check()

    # ---- CUDA faults
    cuda = [t["stem"] + "@" + t["build"] for t in trials
            if t["l0"]["cuda"] or t["l1"]["cuda"] or t["meta"].get("r0rc") == "139" or t["meta"].get("r1rc") == "139"]
    kvcuda = []
    for t in trials:
        for kv in (t["k0"], t["k1"]):
            if any(CUDA_FAULT.search(v or "") for v in kv.values()):
                kvcuda.append(t["stem"])
    out("- [measured] CUDA memory fault (exit 139, illegal address or launch failure in a log or kv): %s" %
        (", ".join(cuda + kvcuda) if (cuda or kvcuda) else "none in %d trials" % len(trials)))
    out()

    # ---- exclusions and settings
    out("## Exclusions (EXPERIMENT.md 8) and setting checks")
    out()
    judged = collections.defaultdict(list)
    excl = []
    counts = {ck: {"judged": 0, "excluded": 0, "stopped": False} for ck in PLAN}
    for t in trials:
        st, why = status_of(t)
        t["status"] = st
        if st == "judged":
            judged[t["key"]].append(t)
            counts[t["key"]]["judged"] += 1
        else:
            excl.append((t, why))
            counts[t["key"]]["excluded"] += 1
    for ck in PLAN:
        if counts[ck]["excluded"] > 0.5 * PLAN[ck]:
            counts[ck]["stopped"] = True
    for t, why in excl:
        out("- [measured] excluded: `%s@%s` (%s); r0rc=%s r1rc=%s wall_s=%s; r0 log %d line(s), r1 log: %s" %
            (t["stem"], t["build"], why, t["meta"].get("r0rc"), t["meta"].get("r1rc"), t["meta"].get("wall_s"),
             t["l0"]["lines"], "watchdog exit" if t["meta"].get("r1rc") == "7" else t["meta"].get("r1rc")))
    out("- [measured] replacement trials: %s" %
        ", ".join("%s n%d" % (k, max(x["n"] for x in judged[k])) for k in PLAN
                  if counts[k]["excluded"] and judged[k]) if excl else "none")
    out("- [measured] judged per cell key equals the plan: %s; any cell key above the 50%% refill limit: %s" %
        (all(counts[ck]["judged"] == PLAN[ck] for ck in PLAN),
         [ck for ck in PLAN if counts[ck]["stopped"]] or "none"))
    sp = [(t["stem"] + "@" + t["build"], setting_problems(t)) for t in trials if t["status"] == "judged"]
    sp = [x for x in sp if x[1]]
    out("- [measured] setting checks on the %d judged trials: %s" %
        (sum(1 for t in trials if t["status"] == "judged"), "all pass" if not sp else "%d fail" % len(sp)))
    for s, p in sp:
        out("  - %s: %s" % (s, "; ".join(p)))
    hog_order = [(t["stem"], round(fnum(t["row"]["fault_after_launch_r0_ms"]) or -1, 1),
                  t["row"].get("hog_launch_after_launch_ms_r0")) for t in trials if t["cell"] in HOG and
                 t["status"] == "judged"]
    fa = [x[1] for x in hog_order]
    out("- [measured] GPU-full cells, rank 0 hook fire after the GIN launch (judged trials, n=%d): %.1f-%.1f ms; "
        "GPU-filling launch %s-%s ms after the GIN launch" %
        (len(fa), min(fa), max(fa), min(x[2] for x in hog_order), max(x[2] for x in hog_order)))
    fw = [(t["stem"], t["row"]["n_fwdog_r0"], t["row"]["n_fwdog_r1"], t["row"].get("rs_fw_overruns_r0"),
           t["row"].get("rs_fw_overruns_r1")) for t in trials]
    out("- [measured] firmware watchdog lines or rs_fw_overruns != 0 in any trial: %s" %
        ([x[0] for x in fw if x[1] or x[2] or (fnum(x[3]) or 0) or (fnum(x[4]) or 0)] or "none"))
    out()

    # ---- predictions
    preds = split_csv_line(open(os.path.join(STUDY, "predictions.csv")).read())
    res = evaluate_predictions(preds, judged, counts, known_cols)
    out("## Predictions")
    out()
    out("| id | kind | cell key | n | hits | rule | verdict | trials that miss |")
    out("|---|---|---|--:|---|---|---|---|")
    vc = collections.Counter()
    unknown_all = set()
    for p, rows, verdict in res:
        vc[verdict] += 1
        acc = p["acceptance"]
        thr = re.findall(r"\)\s*(>=|==|<=)\s*([\d.]+)\s*$", acc)
        rule = ("%s %s" % thr[0]) if thr else ""
        for row in rows:
            if len(row) == 6:
                ck, n, hits, v, missed, unknown = row
                unknown_all |= set(unknown)
                out("| %s | %s | `%s` | %d | %s/%d | count %s | %s | %s |" %
                    (p["id"], p["kind"], ck, n, hits, n, rule, v, ", ".join(missed) or "none"))
            elif isinstance(row[1], dict):
                meds = row[1]
                ks = list(meds)
                d = abs(meds[ks[0]][0] - meds[ks[1]][0])
                lim = re.search(r"<=\s*([\d.]+)\s*$", acc).group(1)
                out("| %s | %s | `%s` | %s | medians %s; abs diff %.2f us | <= %s us | %s | - |" %
                    (p["id"], p["kind"], row[0], "/".join(str(meds[k][1]) for k in ks),
                     " vs ".join("%.2f" % meds[k][0] for k in ks), d, lim, row[3]))
            else:
                out("| %s | %s | `%s` | %s | - | - | %s | - |" % (p["id"], p["kind"], row[0], row[1], row[3]))
        if len(rows) > 1 and len(rows[0]) == 6:
            out("| %s | | (all cells) | | | | **%s** | |" % (p["id"], verdict))
    out()
    out("- [measured] verdicts: %s (of %d predictions)" %
        (", ".join("%s %d" % (k, v) for k, v in sorted(vc.items())), len(res)))
    out("- [measured] column names in the rules that this recount does not produce: %s" %
        (sorted(unknown_all) or "none"))
    out()
    return trials, judged, res, hold_probs, between


# ---------------------------------------------------------------------------------------------------------------------
def rng(vals, fmt="%.1f"):
    v = [x for x in vals if x is not None]
    if not v:
        return "-"
    return (fmt + "-" + fmt) % (min(v), max(v)) if min(v) != max(v) else fmt % v[0]


def key_numbers(trials, judged):
    out("## Key numbers (judged trials only)")
    out()
    out("### Shrink (rank 0 kv; ranges are over the judged trials of each cell key)")
    out()
    out("| cell key | n | shrink rc | shrink ms (range over trials) | new comm ranks | allreduce done/check ok | "
        "check ms | new comm async | parent async after | hand-off / keep lines | child destroy ms | "
        "devComm destroy ms | parent abort |")
    out("|---|--:|---|---|---|---|---|---|---|---|---|---|---|")
    for ck in ("hd_shrink_b@hf", "hd_shrink_b@hfp", "hd_shrink_b@hd", "hf_shrinkoff_b@hf", "hf_shrinkdc_b@hf",
               "hf_hog_f1_b@hf"):
        ts = judged[ck]
        R = [t["row"] for t in ts]
        cnt = lambda f: dict(collections.Counter(r.get(f, "") or "(none)" for r in R))
        out("| `%s` | %d | %s | %s | %s | %s/%s | %s | %s | %s | %s / %s | %s | %s | %s |" % (
            ck, len(ts), cnt("ho_shrink_rc"), rng([fnum(r.get("ho_shrink_ms")) for r in R]),
            cnt("ho_newcomm_nranks"),
            sum(1 for r in R if r.get("ho_allreduce_done") == "1"), sum(1 for r in R if r.get("ho_check_ok") == "1"),
            rng([fnum(r.get("ho_check_ms")) for r in R]), cnt("ho_newcomm_async"), cnt("ho_parent_async_after"),
            sum(r["n_hoff_ok_r0"] for r in R), sum(r["n_hoff_keep_r0"] for r in R),
            rng([fnum(r.get("ho_newcomm_destroy_ms")) for r in R]),
            rng([fnum(r.get("ho_devcomm_destroy_ms")) for r in R]), cnt("teardown_r0")))
    out()
    allsh = [fnum(t["row"].get("ho_shrink_ms")) for ck in ("hd_shrink_b@hf", "hd_shrink_b@hfp", "hf_shrinkdc_b@hf")
             for t in judged[ck] if t["row"].get("ho_shrink_rc") == "no error"]
    out("- [measured] successful shrinks, all three cell keys pooled (n=%d): %s ms" % (len(allsh), rng(allsh)))
    for ck in ("hd_shrink_b@hf", "hf_shrinkoff_b@hf", "hf_hog_f1_b@hf"):
        R = [t["row"] for t in judged[ck]]
        out("- [measured] `%s`: hand-off list %s; keep reasons %s" %
            (ck, dict(collections.Counter(r["hoff_ranks_r0"] or "(none)" for r in R)),
             dict(collections.Counter(r["hoff_why_r0"] or "(none)" for r in R))))
    R = [t["row"] for t in judged["hf_shrinkdc_b@hf"]]
    out("- [measured] `hf_shrinkdc_b@hf`: devComm destroy rc %s; final signal read %s" %
        (dict(collections.Counter(r.get("ho_devcomm_destroy_rc", "") for r in R)),
         dict(collections.Counter(t["k0"].get("final_signal_read", "(none)") for t in judged["hf_shrinkdc_b@hf"]))))
    out()

    out("### Decline after the kill (rank 0's first decline minus the kill moved to rank 0's clock)")
    out()
    out("| cell key | n | decline cause | ms after kill (range over trials) |")
    out("|---|--:|---|---|")
    pool = []
    for ck in ("hd_shrink_b@hf", "hd_shrink_b@hfp", "hd_shrink_b@hd", "hf_shrinkoff_b@hf", "hf_shrinkdc_b@hf",
               "f4_b@hf", "hdp_kill_b@hfp"):
        R = [t["row"] for t in judged[ck]]
        v = [fnum(r["decl_after_kill_ms_r0"]) for r in R]
        pool += v
        out("| `%s` | %d | %s | %s |" % (ck, len(R), dict(collections.Counter(r["decl_r0"] for r in R)),
                                         rng(v, "%.2f")))
    out()
    out("- [measured] all seven kill cell keys pooled (n=%d trials): %s ms" % (len(pool), rng(pool, "%.2f")))
    R = [t["row"] for t in judged["hd_rxdeath_b@hf"]]
    out("- [measured] `hd_rxdeath_b@hf` (rank 0 killed, n=%d): rank 1 wait released %s ms and async error %s ms after "
        "the kill (ranges over trials); judged-dead lines on rank 1: %s" %
        (len(R), rng([fnum(r["release_after_kill_ms_r1"]) for r in R]),
         rng([fnum(r["async_after_kill_ms_r1"]) for r in R]), [r["n_judged_r1"] for r in R]))
    out()

    out("### GPU-full 2 x 2 (per trial; r0 = rain, r1 = sunny)")
    out()
    out("| trial | blocks r0/r1 | started at probe r0/r1 | started at end r0/r1 | start spread ms r0/r1 | "
        "probe done in 200 ms r0/r1 | probe max ms r0/r1 | probe done at end r0/r1 | copy timeouts (log) r0/r1 | "
        "watchdog surface r0/r1 | recovered (initiator r0) | transparent | rank 0 decline |")
    out("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for cell in ("hf_hog_f1_b", "hf_hogslack_f1_b", "hf_hogpre_f1_b", "hf_hogpreslack_f1_b"):
        for t in sorted(judged[cell + "@hf"], key=lambda x: x["n"]):
            r = t["row"]
            two = lambda f: "%s/%s" % (r.get(f + "_r0", ""), r.get(f + "_r1", ""))
            out("| `%s` | %s | %s | %s | %s | %s | %s | %s | %s/%s | %s/%s | %s | %s | %s |" % (
                t["stem"], two("hog_blocks"), two("hog_started_probe"), two("hog_started_end"),
                two("hog_start_spread_ms"), two("probe_done_200ms"), two("probe_max_ms"), two("probe_done_end"),
                r["n_copyto_r0"], r["n_copyto_r1"], r["n_surface_r0"], r["n_surface_r1"], r["rec_init_r0"],
                r["transparent_ok"], r["decl_r0"] or "-"))
    out()
    for cell in ("hf_hog_f1_b", "hf_hogslack_f1_b", "hf_hogpre_f1_b", "hf_hogpreslack_f1_b"):
        ts = judged[cell + "@hf"]
        R = [t["row"] for t in ts]
        sp = {rk: [fnum(r.get("hog_start_spread_ms_r%d" % rk)) for r in R] for rk in (0, 1)}
        km = {rk: [fnum(t["k%d" % rk].get("kernel_ms")) for t in ts] for rk in (0, 1)}
        pm = [fnum(r.get("probe_max_ms_r%d" % rk)) for r in R for rk in (0, 1) if
              (fnum(r.get("probe_done_200ms_r%d" % rk)) or 0) > 0]
        out("- [measured] `%s@hf` (n=%d): start spread r0 %s ms, r1 %s ms; GIN kernel time r0 %s ms, r1 %s ms "
            "(ranges over trials); slowest probe copy that finished within 200 ms, over both ranks: %s ms; "
            "transparent %d/%d; rank 0 declines %d/%d" % (
                cell, len(ts), rng(sp[0]), rng(sp[1]), rng(km[0]), rng(km[1]), rng(pm, "%.3f"),
                sum(r["transparent_ok"] for r in R), len(R), sum(1 for r in R if r["decl_r0"]), len(R)))
    for cell in ("hf_hog_f1_b", "hf_hogslack_f1_b"):
        ts = judged[cell + "@hf"]
        surf = [t["l0"]["surface_ms"][0] - t["l0"]["fires"][0] for t in ts if t["l0"]["surface_ms"] and t["l0"]["fires"]]
        cto = [t["l0"]["copyto"][0][2] - t["l0"]["fires"][0] for t in ts if t["l0"]["copyto"] and t["l0"]["fires"]]
        dcl = [t["l0"]["decl"][0][1] - t["l0"]["copyto"][0][2] for t in ts if t["l0"]["copyto"] and t["l0"]["decl"]]
        out("- [measured] `%s@hf` rank 0 (n=%d): watchdog surface %s ms after the hook fired, reasons %s; copy "
            "timeout line %s ms after the hook fired; decline %s ms after the copy timeout line; rank 1 decline "
            "reasons %s; rank 1 surface lines %s" % (
                cell, len(ts), rng(surf), dict(collections.Counter(t["row"]["surface_why_r0"] for t in ts)), rng(cto),
                rng(dcl, "%.2f"), dict(collections.Counter(t["row"]["decl_r1"] for t in ts)),
                [t["row"]["n_surface_r1"] for t in ts]))
    pa = [fnum(t["row"].get("probe_after_hog_ms_r%d" % rk)) for c in HOG for t in judged[c + "@hf"] for rk in (0, 1)]
    out("- [measured] probe copies issued %s ms after the GPU-filling launch (all 40 rank-trials of the 2 x 2); "
        "probes per rank %s" % (rng(pa), dict(collections.Counter(t["row"].get("probe_n_r%d" % rk) for c in HOG
                                                                    for t in judged[c + "@hf"] for rk in (0, 1)))))
    # node clock offsets in the cells whose blocks started at once (EXPERIMENT.md 3.1 note)
    at_once = collections.defaultdict(list)
    for cell in ("hf_hogpreslack_f1_b",):
        for t in judged[cell + "@hf"]:
            for rk in (0, 1):
                at_once[rk].append(fnum(t["row"].get("hog_first_start_rel_ms_r%d" % rk)))
    out("- [measured] `hog_first_start_rel_ms` in `hf_hogpreslack_f1_b@hf` (all blocks started at once; this is the "
        "node's globaltimer-to-CLOCK_REALTIME difference, n=%d per rank): rain %s ms, sunny %s ms" %
        (len(at_once[0]), rng(at_once[0]), rng(at_once[1])))
    pre = sorted(judged["hf_hogpre_f1_b@hf"], key=lambda x: x["n"])
    out("- [measured] the same value in `hf_hogpre_f1_b@hf` (first block starts at once there too), per trial "
        "rain/sunny: %s" % ", ".join("n%d %s/%s (hold %s)" % (t["n"], t["row"].get("hog_first_start_rel_ms_r0"),
                                                               t["row"].get("hog_first_start_rel_ms_r1"),
                                                               t.get("hold", "?")) for t in pre))
    for cell in ("hf_hog_f1_b", "hf_hogslack_f1_b"):
        d = []
        for t in judged[cell + "@hf"]:
            for rk, base in ((0, statistics.median([x for x in at_once[0] if x is not None])),
                             (1, statistics.median([x for x in at_once[1] if x is not None]))):
                f = fnum(t["row"].get("hog_first_start_rel_ms_r%d" % rk))
                kms = fnum(t["k%d" % rk].get("kernel_ms"))
                hl = fnum(t["row"].get("hog_launch_after_launch_ms_r%d" % rk))
                if f is not None and kms is not None and hl is not None:
                    d.append((f - base + hl) - kms)
        out("- [inferred] `%s@hf`: first GPU-filling block start (minus that node's at-once offset, plus the "
            "launch delay) minus the GIN kernel time: %s ms over %d rank-trials (about 0 means the blocks started when "
            "the GIN kernel ended)" % (cell, rng(d), len(d)))
    out()

    out("### Latency p50 (rank 0, us; 3000 iterations per run)")
    out()
    out("| cell key | n runs | p50 per run (kv) | median of runs | range over runs | p50 recomputed from the raw "
        "latencies equals kv |")
    out("|---|--:|---|--:|---|---|")
    meds = {}
    for ck in ("lat_4k@hfp", "lat_4k@hdp", "lat_4k@hd", "lat_256k@hfp", "lat_256k@hdp", "lat_256k@hd"):
        ts = sorted(judged[ck], key=lambda x: x["n"])
        v = [fnum(t["row"]["lat_p50_us"]) for t in ts]
        rawok = all(t["lat_raw_p50"] is not None and abs(t["lat_raw_p50"] - fnum(t["row"]["lat_p50_us"])) < 0.006
                    and t["lat_raw_n"] == 3000 for t in ts)
        meds[ck] = statistics.median(v)
        out("| `%s` | %d | %s | %.2f | %s | %s |" % (ck, len(ts), ", ".join("%.2f" % x for x in v), meds[ck],
                                                      rng(v, "%.2f"), rawok))
    out()
    for a, b, lim in (("lat_4k@hfp", "lat_4k@hdp", 0.40), ("lat_256k@hfp", "lat_256k@hdp", 0.30),
                      ("lat_4k@hfp", "lat_4k@hd", 0.40), ("lat_256k@hfp", "lat_256k@hd", 0.30)):
        out("- [measured] median %s - median %s = %+.2f us (bound %.2f)" % (a, b, meds[a] - meds[b], lim))
    out()

    out("### Regression cells")
    out()
    out("| cell key | n | transparent | rank 0 decline reasons | other values (ranges over trials) |")
    out("|---|--:|--:|---|---|")
    for ck in ("f1_b@hf", "f3_b@hf", "bidirf_sym_b@hf", "f4_b@hf", "f2rel_b@hf", "hd_rxdeath_b@hf", "hdp_kill_b@hfp"):
        ts = judged[ck]
        R = [t["row"] for t in ts]
        other = ""
        if ck == "f1_b@hf":
            other = "stats r0 rounds/recovered/declined %s, r1 rounds/recovered %s" % (
                dict(collections.Counter("%s/%s/%s" % (r.get("rs_rounds_r0"), r.get("rs_recovered_r0"),
                                                        r.get("rs_declined_r0")) for r in R)),
                dict(collections.Counter("%s/%s" % (r.get("rs_rounds_r1"), r.get("rs_recovered_r1")) for r in R)))
        elif ck in ("f4_b@hf", "hdp_kill_b@hfp"):
            other = "stats r0 deaths/declined %s; decline %s ms after kill; abort %s" % (
                dict(collections.Counter("%s/%s" % (r.get("rs_deaths_r0"), r.get("rs_declined_r0")) for r in R)),
                rng([fnum(r["decl_after_kill_ms_r0"]) for r in R], "%.2f"),
                dict(collections.Counter(r["teardown_r0"] for r in R)))
        elif ck == "f2rel_b@hf":
            other = "r1 outcome %s; rx_rc %s; rx_phantom_r1 %s; r1 abort %s in %s ms" % (
                dict(collections.Counter(r["r1_outcome"] for r in R)), dict(collections.Counter(r["rx_rc"] for r in R)),
                dict(collections.Counter(r["rx_phantom_r1"] for r in R)),
                dict(collections.Counter(r["teardown_r1"] for r in R)),
                rng([fnum(r["teardown_ms_r1"]) for r in R]))
        elif ck == "hd_rxdeath_b@hf":
            other = "r1 rx_rc %s; r1 abort %s" % (dict(collections.Counter(r["rx_rc"] for r in R)),
                                                  dict(collections.Counter(r["teardown_r1"] for r in R)))
        elif ck in ("f3_b@hf", "bidirf_sym_b@hf"):
            other = "initiator rounds r0/r1 %s" % dict(collections.Counter("%d/%d" % (r["rec_init_r0"],
                                                                                       r["rec_init_r1"]) for r in R))
        out("| `%s` | %d | %d/%d | %s | %s |" % (ck, len(R), sum(r["transparent_ok"] for r in R), len(R),
                                                 dict(collections.Counter(r["decl_r0"] or "(none)" for r in R)), other))
    out()
    # other observations
    cs = collections.Counter()
    for t in trials:
        if t["l0"]["cannot_set"] or t["l1"]["cannot_set"]:
            cs[t["key"]] += 1
    out("- [measured] trials with a 'cannot set the device error state' line (either rank), per cell key: %s" %
        (dict(cs) or "none"))
    lc = collections.Counter()
    for t in trials:
        if t["row"]["n_late_copy_r0"] or t["row"]["n_late_copy_r1"]:
            lc[t["key"]] += 1
    out("- [measured] trials with a 'late device-state copy completed' line, per cell key: %s" % (dict(lc) or "none"))
    out()


# ---------------------------------------------------------------------------------------------------------------------
def pilot_checks():
    out("## Statements about the pilot (results/20261009_pilot, never scored; checked only)")
    out()
    pt = load_dir(PILOT)
    out("- [measured] pilot trial files: %d (%s)" % (len(pt), ", ".join(sorted(t["key"] for t in pt))))
    h0 = open(os.path.join(PILOT, "hold_H0.out"), errors="replace").read()
    b = re.search(r"== before-H0 \S+ (\S+)", h0)
    a = re.search(r"== after-H0 \S+ (\S+)", h0)
    out("- [measured] pilot hold window %s-%s" % (b.group(1) if b else "?", a.group(1) if a else "?"))
    exc = [(t["stem"], status_of(t)[1]) for t in pt if status_of(t)[0] != "judged"]
    sp = [(t["stem"], setting_problems(t)) for t in pt]
    out("- [measured] pilot exclusions: %s; setting-check failures: %s" %
        (exc or "none", [x for x in sp if x[1]] or "none"))
    for t in sorted(pt, key=lambda x: x["key"]):
        r = t["row"]
        bits = []
        if r.get("ho_shrink_ms"):
            bits.append("shrink %s %s ms" % (r.get("ho_shrink_rc"), r.get("ho_shrink_ms")))
        if r.get("ho_newcomm_destroy_ms"):
            bits.append("child destroy %s ms" % r.get("ho_newcomm_destroy_ms"))
        if r["decl_after_kill_ms_r0"] != "":
            bits.append("decline %.2f ms after kill" % r["decl_after_kill_ms_r0"])
        if r.get("hog_blocks_r0"):
            bits.append("blocks %s/%s started at probe %s/%s spread %s/%s first_rel %s/%s kernel %s/%s probe done "
                        "%s/%s max %s/%s transparent %s" % (
                            r.get("hog_blocks_r0"), r.get("hog_blocks_r1"), r.get("hog_started_probe_r0"),
                            r.get("hog_started_probe_r1"), r.get("hog_start_spread_ms_r0"),
                            r.get("hog_start_spread_ms_r1"), r.get("hog_first_start_rel_ms_r0"),
                            r.get("hog_first_start_rel_ms_r1"), t["k0"].get("kernel_ms"), t["k1"].get("kernel_ms"),
                            r.get("probe_done_200ms_r0"), r.get("probe_done_200ms_r1"), r.get("probe_max_ms_r0"),
                            r.get("probe_max_ms_r1"), r["transparent_ok"]))
        if r.get("ho_devcomm_destroy_ms"):
            bits.append("devComm destroy %s ms, parent async after %s" % (r.get("ho_devcomm_destroy_ms"),
                                                                          r.get("ho_parent_async_after")))
        if r["hoff_why_r0"]:
            bits.append("keep reason '%s'" % r["hoff_why_r0"])
        if r["surface_why_r0"]:
            bits.append("rank 0 surface '%s'" % r["surface_why_r0"])
        if r["decl_r0"]:
            bits.append("rank 0 decline '%s'" % r["decl_r0"])
        if t["k0"].get("progress") and not t["cell"].startswith("lat_"):
            bits.append("r0rc %s progress %s/%s" % (t["meta"].get("r0rc"), t["k0"].get("progress"),
                                                    t["meta"].get("iters")))
        if r.get("lat_p50_us") and t["cell"].startswith("lat_"):
            bits.append("p50 %s us" % r["lat_p50_us"])
        if bits:
            out("  - `%s`: %s" % (t["key"], "; ".join(bits)))
    out()


def main():
    trials, judged, res, hold_probs, between = recount()
    key_numbers(trials, judged)
    pilot_checks()
    sys.stdout.write(scrub("\n".join(OUT)) + "\n")


if __name__ == "__main__":
    main()
