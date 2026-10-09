#!/usr/bin/env python3
"""gin-remaining: independent recount of the main run (results/20261009), read-only.

Rebuilds every column the 34 pre-registered predictions use from the raw per-trial files (meta, kv, rank logs, kill.out,
raw latency samples), applies the section 8 exclusions and setting checks, evaluates each acceptance rule of
predictions.csv with its own evaluator of the rule grammar, and prints the report (integrity, exclusions, hold logs,
verdicts, key numbers). Nothing is written.

Independent of the study's scorer: it does not read or import score.py, rows_hr.py or any earlier study's score.py or row
extractor (../scripts/ts2/rows.py, ../s2_close/rows_extra.py, ../pair_check/rows_pc.py, ../oneway/rows_ow.py,
../harden/rows_hd.py, ../handoff/rows_hf.py, ../peer/rows_pq.py, ../multirank/rows_mr.py), and it does not read
SCORE.md or any trials_*.csv. Column definitions come from the EXPERIMENT.md 3.1 tables (this study, gin-peer,
gin-harden, gin-handoff, gin-multirank, gin-oneway, gin-s2-close), the drivers' headers (../gin_ts2.cu, gin_mr.cu,
hm_bench.cu, nic_gate_test.cu) and the log formats of the library source (gin_host_gdaki.cc of the hr tree).

Git: only `git rev-parse` and `git cat-file -p <tag>:<path>` (no filter runs). No line holding the management address is
printed: runner files are compared with the tag after masking their SUNNY_SSH default line, and hold-log lines are parsed,
never echoed.

usage: python3 qa/recount.py [--pilots]      (from the study folder or anywhere)
"""
import ast
import gzip
import hashlib
import os
import re
import statistics
import subprocess
import sys
from collections import Counter, OrderedDict, defaultdict

STUDY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(STUDY, "results", "20261009")
PILOT = os.path.join(STUDY, "results", "20261009_pilot")
PILOT2 = os.path.join(STUDY, "results", "20261009_pilot2")
TAG = "prereg/gin-remaining-v1"
REL = "harness/gpu-initiated/gin_recovery/remaining"

OUT = []


def out(s=""):
    OUT.append(s)
    print(s)


# ------------------------------------------------------------------------------------------------ planned trial set
# EXPERIMENT.md section 7 (cell keys and planned judged trials); the folder of each key (hold.sh `sub`)
PLANNED = OrderedDict([
    ("rh_hog_f1_b@hr", 10), ("rh_hog_f1_b@hq", 5), ("rh_hog_copystream_f1_b@hr", 5),
    ("rh_hogcall_load_f1_b@hq", 5), ("rh_hogcall_malloc_f1_b@hq", 5), ("rh_hogcall_stream_f1_b@hq", 5),
    ("rh_hogcall_load_f1_b@hr", 3), ("rh_hogcall_malloc_f1_b@hr", 3), ("rh_hogcall_stream_f1_b@hr", 3),
    ("mr4_cyc_stall@hr", 10), ("mr4_cyc_stall@hq", 5), ("mr4_chain_stall@hr", 5),
    ("rm4_kill3_untimed@hr", 10), ("rm4_kill3_untimed@hq", 5), ("mr4_kill3_peer@hr", 5),
    ("f1_b@hr", 5), ("f3_b@hr", 5), ("bidirf_sym_b@hr", 5), ("f4_b@hr", 5), ("f2rel_b@hr", 5), ("hd_rxdeath_b@hr", 5),
    ("hdp_kill_b@hrp", 5), ("mr4_none@hr", 5), ("mr4_f1_01@hr", 5),
    ("lat_4k@hrp", 5), ("lat_4k@hqp", 5), ("lat_256k@hrp", 5), ("lat_256k@hqp", 5),
    ("hm_bench@hr", 5), ("nic_gate@hr", 5),
])


def folder_of(cell, build):
    if cell.startswith("mr4_") or cell.startswith("rm4_"):
        return "mr_" + build
    if cell == "hm_bench":
        return "bench"
    if cell == "nic_gate":
        return "ngt"
    return build


def kind_of(cell):
    if cell.startswith("mr4_") or cell.startswith("rm4_"):
        return "4"
    if cell == "hm_bench":
        return "bench"
    if cell == "nic_gate":
        return "ngt"
    return "2"


# ------------------------------------------------------------------------------------------------ parsing helpers
KEY_RE = re.compile(r"(?:(?<=\s)|^)([A-Za-z_][A-Za-z0-9_]*)=")


def parse_kv_text(text):
    d = {}
    for line in text.splitlines():
        ms = list(KEY_RE.finditer(line))
        for i, m in enumerate(ms):
            end = ms[i + 1].start() if i + 1 < len(ms) else len(line)
            k = m.group(1)
            if k not in d:
                d[k] = line[m.end():end].strip()
    return d


def read(path):
    try:
        with open(path, "r", errors="replace") as f:
            return f.read()
    except FileNotFoundError:
        return None


def num(x):
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


MSG_RE = re.compile(r"NCCL (?:WARN|INFO) (GIN/.*)$")
TS_RE = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\]")


def log_msgs(text):
    """(timestamp or None, message) for every GIN/ line of a rank log, in order; plus first and last timestamps."""
    msgs, first, last = [], None, None
    if text is None:
        return msgs, first, last
    for line in text.splitlines():
        t = TS_RE.match(line)
        if t:
            first = first or t.group(1)
            last = t.group(1)
        m = MSG_RE.search(line)
        if m:
            msgs.append(m.group(1))
    return msgs, first, last


# log formats (gin_host_gdaki.cc of the hr tree, and the earlier layers' lines it still prints)
R = {
    "fire": re.compile(r"^GIN/FAULT: GDAKI fault fired \(shot \d+/\d+\): moved \d+/\d+ GIN QP\(s\) to ERR(?: context=(\d+))? "
                       r"fire_mono_ms=([\d.]+) done_mono_ms=([\d.]+)"),
    "trigmiss": re.compile(r"^GIN/FAULT: shot 1 trigger not reached"),
    "round": re.compile(r"^GIN/TS: rank (\d+): round (\d+) peer (\d+) scope=(\S+) qps=(\d+) reason=(\S+) mono_ms=([\d.]+)"),
    "rec": re.compile(r"^GIN/TS: recovered rank=(\d+) peer=(\d+) role=(initiator|responder) round=(\d+) .*? total_us=(\d+) "
                      r".*?t_resumed=([\d.]+)"),
    "decl": re.compile(r'^GIN/TS: declined rank=(\d+) peer=(\d+) reason="(.*)" class=(-?\d+) mono_ms=([\d.]+)'),
    "cause": re.compile(r"^GIN/TS: rank (\d+): GIN error raised for rank (\d+) cause=([a-z-]+)(?: \(firmware overrun\))? "
                        r"mono_ms=([\d.]+)"),
    "judged": re.compile(r"^GIN/TS: rank (\d+): rank (\d+) judged dead \(cause=([^)]*)\) mono_ms=([\d.]+)"),
    "uapeer": re.compile(r"^GIN/TS: user devComm waits on rank (\d+) released rank=(\d+) why=(\S+) mono_ms=([\d.]+)"),
    "uaword": re.compile(r"^GIN/TS: user devComm waits released rank=(\d+) why=(\S+) mono_ms=([\d.]+)"),
    "abortflag": re.compile(r"^GIN/TS: user devComm abort flag set rank=(\d+)"),
    "tson": re.compile(r"^GIN/TS: transparent recovery ON rank=(\d+)"),
    "hd": re.compile(r"^GIN/TS: harden=1 rank=(\d+) .* production=([01])$"),
    "hf": re.compile(r"^GIN/TS: handoff=1 rank=(\d+) shrink_handoff=([01])"),
    "pq": re.compile(r"^GIN/TS: peer=1 rank=(\d+) per_peer_words=1 "),
    "hr": re.compile(r"^GIN/TS: remaining=1 rank=(\d+) copy_path=(nic|stream) lb_mrs=(\d+) serve_wait=([01]) "
                     r"degraded_ms=(-?\d+)$"),
    "lbon": re.compile(r"^GIN/TS: rank (\d+): NIC copy path on: loopback qpn (\S+)->(\S+), own PD, gid_index (\d+) "
                       r"\(([^)]*)\), (\d+) GPU MR\(s\) \(dmabuf (\d+), peermem (\d+)\), self-test ok \((\d+) B read and "
                       r"written back, (\d+) nonzero\), setup_ms=([\d.]+) mono_ms=([\d.]+)$"),
    "lboff": re.compile(r"^GIN/TS: rank (\d+): the NIC copy path is off \("),
    "copyto": re.compile(r"^GIN/TS: rank (-?\d+): device-state copy \((over the NIC, )?([^,]+), (\d+) B\) not complete after "
                         r"(\d+) ms \(NCCL_GIN_TS_COPY_MS\); the round declines"),
    "td": re.compile(r"^GIN/TS: rank (\d+) copy path at teardown: path=(\S+) nic_ops=(\d+) nic_bytes=(\d+) "
                     r"nic_timeouts=(\d+) stream_copies=(\d+) served_in_wait=(\d+) kept=(\d+) fallbacks=(\d+)(?: why=(.*))?$"),
    "served": re.compile(r"^GIN/TS: rank (\d+): answering REQ round (\d+) from rank (\d+) while waiting for the ACK of round "
                         r"(\d+) from rank (\d+) \(a lower rank is answered at once\) mono_ms=([\d.]+)$"),
    "back": re.compile(r"^GIN/TS: rank (\d+): back to round (\d+) with rank (\d+) after answering rank (\d+) \(([\d.]+) ms\) "
                       r"mono_ms=([\d.]+)$"),
    "kept": re.compile(r"^GIN/TS: rank (\d+): REQ round (\d+) from rank (\d+) kept until round (\d+) with rank (\d+) ends "
                       r"\(a higher rank waits\) mono_ms=([\d.]+)$"),
    "keptans": re.compile(r"^GIN/TS: rank (\d+): answering the kept REQ round (\d+) from rank (\d+) \(kept ([\d.]+) ms\) "
                          r"mono_ms=([\d.]+)$"),
    "keptdrop": re.compile(r"^GIN/TS: rank (\d+): the kept REQ round (\d+) from rank (\d+) is dropped \((.*)\) "
                           r"mono_ms=([\d.]+)$"),
    "degsched": re.compile(r"^GIN/TS: rank (\d+): communicator degraded in (\d+) ms: rank (\d+) was judged dead; waits that "
                           r"name no peer are released then \(NCCL_GIN_TS_DEGRADED_MS\) mono_ms=([\d.]+)$"),
    "deginfo": re.compile(r"^GIN/TS: rank (\d+): communicator degraded: rank (\d+) was judged dead ([\d.]+) ms ago; "),
    "wdfw": re.compile(r"^GIN/TS: watchdog rank=(\d+): firmware command phase (\S+) has run (\d+) ms"),
    "wdany": re.compile(r"^GIN/TS: watchdog rank=(\d+): (.*)$"),
    "knob": re.compile(r"^GIN/TS: TEST knobs rank=(\d+) stall_ms=(\d+) "),
    "test": re.compile(r"^GIN/TS: TEST "),
    "refq": re.compile(r"^GIN/TS: rank (\d+): REQ round (\d+) from rank (\d+) scope=\S+ checked=\d+ not_rts=\d+ check_us=\d+ "
                       r"(refused reason=(\S+)|accepted) mono_ms=([\d.]+)$"),
}

UA_ERR_WHY = ("declined", "peer-dead", "fw-watchdog")


def parse_rank_log(text):
    """Every line type this recount uses, from one rank's log, in log order."""
    msgs, first, last = log_msgs(text)
    L = defaultdict(list)
    L["_first_ts"], L["_last_ts"] = first, last
    L["_bind"] = 1 if text and "Address already in use" in text else 0
    seq = []  # (type, match) in order, for the nested-round scan
    for m in msgs:
        for k in ("fire", "trigmiss", "round", "rec", "decl", "cause", "judged", "uapeer", "uaword", "abortflag", "tson",
                  "hd", "hf", "pq", "hr", "lbon", "lboff", "copyto", "td", "served", "back", "kept", "keptans",
                  "keptdrop", "degsched", "deginfo", "wdfw", "knob", "refq"):
            mm = R[k].search(m)
            if mm:
                L[k].append(mm)
                seq.append((k, mm))
                break
        if R["wdany"].search(m):
            L["wdany"].append(R["wdany"].search(m))
        if R["test"].search(m):
            L["test"].append(m)
    L["_seq"] = seq
    # fixed-text coverage: lines that contain the line's fixed text, to compare with the parsed counts
    cov = Counter()
    for m in msgs:
        for k, fixed in COVER.items():
            if fixed in m:
                cov[k] += 1
    L["_cov"] = cov
    return L


COVER = {
    "fire": "GDAKI fault fired", "round": ": round ", "rec": "GIN/TS: recovered rank=", "decl": "GIN/TS: declined rank=",
    "cause": "GIN error raised for rank", "judged": "judged dead (cause=", "uapeer": "user devComm waits on rank",
    "uaword": "user devComm waits released rank=", "hr": "GIN/TS: remaining=1", "lbon": "NIC copy path on",
    "lboff": "NIC copy path is off", "copyto": "not complete after", "td": "copy path at teardown",
    "served": "while waiting for the ACK of round", "back": "after answering rank", "kept": "kept until round",
    "keptans": "answering the kept REQ", "keptdrop": "is dropped (", "degsched": "communicator degraded in",
    "deginfo": "communicator degraded: rank", "wdfw": "firmware command phase", "knob": "GIN/TS: TEST knobs rank=",
}


def first_mono(lst, idx):
    return float(lst[0].group(idx)) if lst else None


# ------------------------------------------------------------------------------------------------ trial loading
def stems(folder):
    d = os.path.join(RES_DIR[0], folder)
    if not os.path.isdir(d):
        return []
    return sorted({f[:-len("_meta.txt")] for f in os.listdir(d) if f.endswith("_meta.txt")})


RES_DIR = [RES]


def load_trial(folder, stem):
    base = os.path.join(RES_DIR[0], folder, stem)
    meta = parse_kv_text(read(base + "_meta.txt") or "")
    t = {"_folder": folder, "_stem": stem, "_meta": meta}
    m = re.match(r"^(.*)_n(\d+)$", stem)
    t["cell"], t["n"] = m.group(1), int(m.group(2))
    return t, base


def two_rank(folder, stem):
    t, base = load_trial(folder, stem)
    meta = t["_meta"]
    t["build"] = meta.get("build")
    t["kind"] = "2"
    kv = [parse_kv_text(read(base + "_r%d.kv" % r) or "") for r in (0, 1)]
    raw = [read(base + "_r%d.log" % r) for r in (0, 1)]
    L = [parse_rank_log(x) for x in raw]
    t["_kv"], t["_L"] = kv, L
    t["_has"] = [os.path.exists(base + "_r%d.kv" % r) and os.path.exists(base + "_r%d.log" % r) for r in (0, 1)]
    kill = parse_kv_text(read(base + "_kill.out") or "")
    t["_kill"] = kill
    iters = int(meta.get("iters"))
    t["iters"] = iters
    bidir = meta.get("app") == "bidir"
    # transparent_ok (../gin_ts2.cu header): every flush ncclSuccess and every iteration ran, every slot bit-exact, every
    # final signal exact, no host saw an async error. One-way: rank 0 sends, rank 1 receives; bidir: both do both.
    def tx_ok(k):
        return num(k.get("tx_done")) == iters and k.get("tx_rc") == "no error"

    def rx_ok(k):
        return (num(k.get("rx_done")) == iters and k.get("rx_rc") == "no error" and num(k.get("dev_bad_slots")) == 0
                and num(k.get("host_bad_slots")) == 0 and num(k.get("signal_exact")) == 1)
    ok = tx_ok(kv[0]) and rx_ok(kv[1]) and all(k.get("async_first") == "none" for k in kv)
    if bidir:
        ok = ok and tx_ok(kv[1]) and rx_ok(kv[0])
    t["transparent_ok"] = 1 if ok else 0
    t["_outcome_ok"] = 1 if all(k.get("outcome") == "ok" for k in kv) and meta.get("r0rc") == "0" and meta.get("r1rc") == "0" else 0
    for r in (0, 1):
        k, l = kv[r], L[r]
        s = "_r%d" % r
        t["rec_init" + s] = sum(1 for m in l["rec"] if m.group(3) == "initiator" and int(m.group(1)) == r)
        t["rec_resp" + s] = sum(1 for m in l["rec"] if m.group(3) == "responder" and int(m.group(1)) == r)
        reasons = [m.group(3) for m in l["decl"]]
        t["decl" + s] = ";".join(reasons) if reasons else None
        t["declwhy" + s] = reasons[0] if reasons else None
        t["decl_ms" + s] = first_mono(l["decl"], 5)
        t["cause" + s] = l["cause"][0].group(3) if l["cause"] else None
        t["n_copyto" + s] = len(l["copyto"])
        t["n_fires" + s] = len(l["fire"])
        t["fire_ms" + s] = first_mono(l["fire"], 2)
        t["ts_on" + s] = len(l["tson"])
        t["ua" + s] = len(l["abortflag"])
        t["hd_on" + s] = len(l["hd"])
        t["prod" + s] = l["hd"][0].group(2) if l["hd"] else None
        t["hf_on" + s] = len(l["hf"])
        t["pq_on" + s] = len(l["pq"])
        t["hr_on" + s] = len(l["hr"])
        t["copy_path" + s] = l["hr"][0].group(2) if l["hr"] else None
        t["lb_on" + s] = len(l["lbon"])
        t["lb_off" + s] = len(l["lboff"])
        t["td_path" + s] = l["td"][0].group(2) if l["td"] else None
        t["td_stream_copies" + s] = int(l["td"][0].group(6)) if l["td"] else None
        t["td_nic_ops" + s] = int(l["td"][0].group(3)) if l["td"] else None
        t["td_nic_timeouts" + s] = int(l["td"][0].group(5)) if l["td"] else None
        t["td_fallbacks" + s] = int(l["td"][0].group(9)) if l["td"] else None
        t["n_td" + s] = len(l["td"])
        t["n_judged" + s] = len(l["judged"])
        t["judged_ms" + s] = first_mono(l["judged"], 4)
        uae = [m for m in l["uaword"] if m.group(2) in UA_ERR_WHY]
        t["uaerr_why" + s] = uae[0].group(2) if uae else None
        t["n_uaerr" + s] = len(uae)
        t["n_wdfw" + s] = len(l["wdfw"])
        t["n_wdany" + s] = len(l["wdany"])
        t["n_test" + s] = len(l["test"])
        for key in ("hog_calls_after", "probe_n", "probe_done_200ms", "hog_started_probe", "hog_launch_after_launch_ms",
                    "hog_launch_err", "hog_blocks", "hog_sms", "probe_done_end", "hog_started_end", "outcome", "rx_rc",
                    "tx_rc", "rx_phantom", "kernel_done", "lat_p50_us"):
            t[key + s] = k.get(key)
        t["teardown" + s] = k.get("abort_ret")
        t["teardown_ms" + s] = num(k.get("teardown_ms"))
        for key in ("api", "rounds", "recovered", "declined", "deaths", "fw_overruns", "copy_timeouts", "contexts"):
            t["rs_%s%s" % (key, s)] = k.get("rs_" + key)
        lm = num(k.get("launch_mono_ms"))
        t["launch" + s] = lm
        km = num(k.get("kernel_ms"))
        t["kernel_end" + s] = lm + km if lm is not None and km is not None else None
        af = num(k.get("async_first_ms_after_launch"))
        t["async_ms" + s] = lm + af if lm is not None and af is not None and af >= 0 else None
    t["r1_outcome"] = kv[1].get("outcome")
    t["rx_rc"] = kv[1].get("rx_rc")
    t["lat_p50_us"] = kv[0].get("lat_p50_us")
    t["bind_fail"] = 1 if (L[0]["_bind"] or L[1]["_bind"]) else 0
    t["trigger_miss"] = len(L[0]["trigmiss"]) + len(L[1]["trigmiss"])
    t["killed"] = 1 if kill.get("kill_mono_ms") else 0
    off = num(kv[0].get("clock_offset_ms"))  # rank 1 clock - rank 0 clock (rank 0 kv)
    t["clock_offset_ms"] = off
    kms = num(kill.get("kill_mono_ms"))
    t["fault_after_launch_r0_ms"] = (t["fire_ms_r0"] - t["launch_r0"]) if t["fire_ms_r0"] is not None and t["launch_r0"] is not None else None
    t["decl_after_kill_ms_r0"] = None
    t["release_after_kill_ms_r1"] = None
    t["async_after_kill_ms_r1"] = None
    if kms is not None and off is not None:
        if kill.get("rank") == "0":  # rank 0 killed on rain: move to rank 1's clock
            k1 = kms + off
            if t["kernel_end_r1"] is not None:
                t["release_after_kill_ms_r1"] = t["kernel_end_r1"] - k1
            if t["async_ms_r1"] is not None:
                t["async_after_kill_ms_r1"] = t["async_ms_r1"] - k1
        else:  # rank 1 killed on sunny: move to rank 0's clock
            k0 = kms - off
            if t["decl_ms_r0"] is not None:
                t["decl_after_kill_ms_r0"] = t["decl_ms_r0"] - k0
            if t["judged_ms_r0"] is not None:
                t["judged_after_kill_ms_r0"] = t["judged_ms_r0"] - k0
    t["rx_phantom_r1"] = kv[1].get("rx_phantom")
    return t


def edge_ok(kv, a, b, iters):
    s, r = kv[a], kv[b]
    return (num(s.get("tx_%d%d_done" % (a, b))) == iters and s.get("tx_%d%d_rc" % (a, b)) == "no error"
            and num(r.get("rx_%d%d_done" % (a, b))) == iters and r.get("rx_%d%d_rc" % (a, b)) == "no error"
            and num(r.get("rx_%d%d_devbad" % (a, b))) == 0 and num(r.get("rx_%d%d_hostbad" % (a, b))) == 0
            and num(r.get("rx_%d%d_sigexact" % (a, b))) == 1)


def four_rank(folder, stem):
    t, base = load_trial(folder, stem)
    meta = t["_meta"]
    t["build"] = meta.get("lib")
    t["kind"] = "4"
    N = int(meta.get("n"))
    t["N"] = N
    kv = [parse_kv_text(read(base + "_r%d.kv" % r) or "") for r in range(N)]
    raw = [read(base + "_r%d.log" % r) for r in range(N)]
    L = [parse_rank_log(x) for x in raw]
    t["_kv"], t["_L"] = kv, L
    t["_has"] = [os.path.exists(base + "_r%d.kv" % r) and os.path.exists(base + "_r%d.log" % r) for r in range(N)]
    kill = parse_kv_text(read(base + "_kill.out") or "")
    t["_kill"] = kill
    iters = int(meta.get("iters"))
    gap = float(meta.get("gap_us"))
    t["iters"] = iters
    off = [0.0] + [num(kv[0].get("clock_offset_ms_r%d" % r)) for r in range(1, N)]  # r clock - r0 clock
    t["_off"] = off

    def to0(r, x):
        return None if x is None or off[r] is None else x - off[r]
    edges = [(a, b) for a in range(N) for b in range(N) if a != b]
    bad = [(a, b) for (a, b) in edges if not edge_ok(kv, a, b, iters)]
    asyncr = [r for r in range(N) if kv[r].get("async_first") not in ("none", None)]
    t["edges_bad"] = ";".join("%d>%d" % e for e in bad) if bad else None
    t["async_ranks"] = ",".join("r%d" % r for r in asyncr) if asyncr else None
    t["transparent_ok"] = 1 if (not bad and all(kv[r].get("outcome") == "ok" for r in range(N))
                                and all(kv[r].get("async_first") == "none" for r in range(N))) else 0
    # fires "rank:context", in traffic
    fires, fin = [], True
    for r in range(N):
        for m in L[r]["fire"]:
            fires.append("%d:%s" % (r, m.group(1) if m.group(1) is not None else "all"))
            lm = num(kv[r].get("launch_mono_ms"))
            fm = float(m.group(2))
            if lm is None or not (lm < fm < lm + iters * gap / 1000.0):
                fin = False
    t["fires"] = ";".join(sorted(fires)) if fires else None
    t["fire_in_traffic"] = 1 if (fires and fin) else (0 if fires else None)
    t["trigger_miss"] = sum(len(L[r]["trigmiss"]) for r in range(N))
    t["bind_fail"] = 1 if any(L[r]["_bind"] for r in range(N)) else 0
    # rounds, recoveries, declines (rank 0 clock where ranks are compared)
    first_round = {}
    all_rounds0 = []
    for r in range(N):
        for m in L[r]["round"]:
            x0 = to0(r, float(m.group(7)))
            all_rounds0.append(x0)
            if r not in first_round:
                first_round[r] = (float(m.group(7)), x0)
    t["n_round_lines"] = len(all_rounds0)
    fr0 = [v[1] for v in first_round.values() if v[1] is not None]
    t["cyc_spread_ms"] = (max(fr0) - min(fr0)) if len(fr0) >= 1 else None
    rec_i, rec_r, resumed0 = [], [], []
    for r in range(N):
        for m in L[r]["rec"]:
            tag = "%s-%s" % (m.group(1), m.group(2))
            (rec_i if m.group(3) == "initiator" else rec_r).append(tag)
            resumed0.append(to0(r, float(m.group(6))))
    t["rec_i"] = ";".join(sorted(rec_i)) if rec_i else None
    t["rec_r"] = ";".join(sorted(rec_r)) if rec_r else None
    t["n_rec_i"] = len(rec_i)
    e0 = min(all_rounds0) if all_rounds0 else None
    t["rec_first_after_round_ms"] = (min(resumed0) - e0) if resumed0 and e0 is not None else None
    t["rec_last_after_round_ms"] = (max(resumed0) - e0) if resumed0 and e0 is not None else None
    decl, hs = [], []
    for r in range(N):
        for m in L[r]["decl"]:
            decl.append("%s-%s" % (m.group(1), m.group(2)))
            if m.group(3) == "handshake timeout":
                hs.append((to0(r, float(m.group(5))), r, float(m.group(5))))
    t["decl"] = ";".join(sorted(decl)) if decl else None
    t["n_decl"] = len(decl)
    t["n_hs"] = len(hs)
    t["decl_reasons"] = Counter(m.group(3) for r in range(N) for m in L[r]["decl"])
    if hs:
        hs.sort()
        _, r, x = hs[0]
        t["hs_first_after_round_ms"] = (x - first_round[r][0]) if r in first_round else None
        t["hs_after_round_all"] = [h[2] - first_round[h[1]][0] for h in hs if h[1] in first_round]
    else:
        t["hs_first_after_round_ms"] = None
        t["hs_after_round_all"] = []
    # stall knob lines, start lines, NIC path lines
    knobs = ["%s:%s" % (m.group(1), m.group(2)) for r in range(N) for m in L[r]["knob"]]
    t["knob_stall"] = ";".join(sorted(knobs)) if knobs else None
    for key in ("tson", "abortflag", "pq", "hr", "lbon", "lboff", "hd", "hf"):
        t["n_" + key] = sum(len(L[r][key]) for r in range(N))
    t["n_wdfw"] = sum(len(L[r]["wdfw"]) for r in range(N))
    t["n_wdany"] = sum(len(L[r]["wdany"]) for r in range(N))
    t["rs_fw_overruns_any"] = sum(1 for r in range(N) if (num(kv[r].get("rs_fw_overruns")) or 0) > 0)
    t["copy_paths"] = Counter(m.group(2) for r in range(N) for m in L[r]["hr"])
    t["td_paths"] = Counter(m.group(2) for r in range(N) for m in L[r]["td"])
    t["td_stream_copies"] = sum(int(m.group(6)) for r in range(N) for m in L[r]["td"])
    t["td_nic_timeouts"] = sum(int(m.group(5)) for r in range(N) for m in L[r]["td"])
    t["td_fallbacks"] = sum(int(m.group(9)) for r in range(N) for m in L[r]["td"])
    t["n_copyto"] = sum(len(L[r]["copyto"]) for r in range(N))
    # served inside an ACK wait, kept REQs, and served rounds that ended with this rank's responder recovery line
    served, kept, served_rec, served_ms = [], [], [], []
    for r in range(N):
        cur = None
        for typ, m in L[r]["_seq"]:
            if typ == "served":
                served.append("%s-%s" % (m.group(1), m.group(3)))
                cur = [int(m.group(3)), False]
            elif typ == "rec" and cur is not None and m.group(3) == "responder" and int(m.group(2)) == cur[0]:
                cur[1] = True
            elif typ == "back" and cur is not None and int(m.group(4)) == cur[0]:
                if cur[1]:
                    served_rec.append("%d-%d" % (r, cur[0]))
                served_ms.append(float(m.group(5)))
                (t.setdefault("_served_ms_rec", []) if cur[1] else t.setdefault("_served_ms_norec", [])).append(
                    float(m.group(5)))
                cur = None
            elif typ == "kept":
                kept.append("%s-%s" % (m.group(1), m.group(3)))
    t["served"] = ";".join(sorted(served)) if served else None
    t["n_served"] = len(served)
    t["kept"] = ";".join(sorted(kept)) if kept else None
    t["n_kept"] = len(kept)
    t["served_rec"] = ";".join(sorted(served_rec)) if served_rec else None
    t["n_served_rec"] = len(served_rec)
    t["_served_ms"] = served_ms
    t["_keptans"] = [(r, float(m.group(4))) for r in range(N) for m in L[r]["keptans"]]
    t["_keptdrop"] = [(r, m.group(4)) for r in range(N) for m in L[r]["keptdrop"]]
    t["_refq"] = Counter((m.group(5) or "accepted") for r in range(N) for m in L[r]["refq"])
    # kill
    kms = num(kill.get("kill_mono_ms"))
    t["killed"] = 1 if kms is not None else 0
    kr = meta.get("kill_rank")
    kr = int(kr) if kr not in (None, "") else None
    t["kill_rank"] = kr
    t["kill_ms0"] = to0(kr, kms) if (kms is not None and kr is not None) else None
    if t["kill_ms0"] is not None:
        launches0 = [to0(r, num(kv[r].get("launch_mono_ms"))) for r in range(N)]
        ends0 = [x + iters * gap / 1000.0 for x in launches0 if x is not None]
        t["kill_in_traffic"] = 1 if (all(x is not None and x < t["kill_ms0"] for x in launches0)
                                     and t["kill_ms0"] <= min(ends0) - 5000) else 0
        t["kill_after_last_launch"] = t["kill_ms0"] - max(launches0)
        t["kill_before_end"] = min(ends0) - t["kill_ms0"]
    else:
        t["kill_in_traffic"] = None
    for r in range(N):
        s = "_r%d" % r
        d = first_mono(L[r]["decl"], 5)
        t["decl_after_kill_ms" + s] = (to0(r, d) - t["kill_ms0"]) if (d is not None and t["kill_ms0"] is not None) else None
        jd = first_mono(L[r]["judged"], 4)
        t["dead_ms" + s] = jd
        t["judged_after_kill_ms" + s] = (to0(r, jd) - t["kill_ms0"]) if (jd is not None and t["kill_ms0"] is not None) else None
        t["decl_after_judged_ms" + s] = (d - jd) if (d is not None and jd is not None) else None
        t["outcome" + s] = kv[r].get("outcome")
        t["kernel_done" + s] = kv[r].get("kernel_done")
        t["rx_untimed" + s] = kv[r].get("rx_untimed")
    # survivors (kill cells)
    if kr is not None:
        surv = [r for r in range(N) if r != kr]
        se = [(a, b) for (a, b) in edges if a != kr and b != kr]
        t["n_surv_edges"] = len(se)
        t["surv_edges_ok"] = sum(1 for e in se if edge_ok(kv, e[0], e[1], iters))
        t["surv_tx_failed"] = sum(1 for (a, b) in se if kv[a].get("tx_%d%d_rc" % (a, b)) != "no error")
        t["surv_rx_failed"] = sum(1 for (a, b) in se if kv[b].get("rx_%d%d_rc" % (a, b)) != "no error")
        t["surv_tx_ok"] = sum(1 for (a, b) in se if num(kv[a].get("tx_%d%d_done" % (a, b))) == iters
                              and kv[a].get("tx_%d%d_rc" % (a, b)) == "no error")
        t["n_kdone_surv"] = sum(1 for r in surv if kv[r].get("kernel_done") == "1")
        t["n_stuck_surv"] = sum(1 for r in surv if kv[r].get("kernel_done") == "0")
        t["n_stuck_surv_outcome"] = sum(1 for r in surv if kv[r].get("outcome") == "async_error_kernel_stuck")
        nrd, nrs = 0, 0
        for s_ in surv:
            k = kv[s_]
            rel = k.get("rx_%d%d_rel" % (kr, s_))
            t["rel_dead_r%d" % s_] = num(rel)
            relms = num(k.get("rx_%d%d_rel_mono_ms" % (kr, s_)))
            jd = t["dead_ms_r%d" % s_]
            t["rel_after_dead_ms_r%d" % s_] = (relms - jd) if (rel == "1" and relms is not None and jd is not None) else None
            if rel == "1":
                nrd += 1
            for a in surv:
                if a != s_ and k.get("rx_%d%d_rel" % (a, s_)) == "1":
                    nrs += 1
        t["n_rel_dead"] = nrd
        t["n_rel_surv"] = nrs
        # survivor kernel end and async after the kill (rank 0 clock)
        t["_surv_kend_after_kill"] = [to0(r, num(kv[r].get("kernel_end_mono_ms"))) - t["kill_ms0"]
                                      for r in surv if num(kv[r].get("kernel_end_mono_ms")) is not None and t["kill_ms0"] is not None]
        t["_rel_it"] = {(a, s_): kv[s_].get("rx_%d%d_rel_it" % (a, s_)) for s_ in surv for a in range(N) if a != s_}
    # degraded release lines (word [0], why=degraded) and the dead judgement of the same rank
    degr = []
    for r in range(N):
        dm = [float(m.group(3)) for m in L[r]["uaword"] if m.group(2) == "degraded"]
        if dm:
            degr.append(r)
        jd = t.get("dead_ms_r%d" % r)
        t["degr_after_dead_ms_r%d" % r] = (dm[0] - jd) if (dm and jd is not None) else None
        sch = [float(m.group(4)) for m in L[r]["degsched"]]
        t["degr_after_sched_ms_r%d" % r] = (dm[0] - sch[0]) if (dm and sch) else None
        dcl = first_mono(L[r]["decl"], 5)
        t["degr_after_decl_ms_r%d" % r] = (dm[0] - dcl) if (dm and dcl is not None) else None
        t["degr_info_ms_r%d" % r] = float(L[r]["deginfo"][0].group(3)) if L[r]["deginfo"] else None
        if kr is not None and r != kr:
            relms = num(kv[r].get("rx_%d%d_rel_mono_ms" % (kr, r)))
            t["rel_after_decl_ms_r%d" % r] = (relms - dcl) if (kv[r].get("rx_%d%d_rel" % (kr, r)) == "1" and relms is not None
                                                             and dcl is not None) else None
        t["degr_n_r%d" % r] = len(dm)
    t["n_degraded"] = sum(t["degr_n_r%d" % r] for r in range(N))
    t["degr_ranks"] = ",".join("r%d" % r for r in degr) if degr else None
    t["n_uapeer"] = sum(len(L[r]["uapeer"]) for r in range(N))
    t["uapeer"] = ";".join(sorted("%s-%s" % (m.group(2), m.group(1)) for r in range(N) for m in L[r]["uapeer"])) or None
    t["n_uaerr"] = sum(1 for r in range(N) for m in L[r]["uaword"] if m.group(2) in UA_ERR_WHY)
    t["causes"] = Counter(m.group(3) for r in range(N) for m in L[r]["cause"])
    t["outcomes"] = Counter(kv[r].get("outcome") for r in range(N))
    return t


def bench_row(stem):
    t, base = load_trial("bench", stem)
    meta = t["_meta"]
    t["build"] = meta.get("build")
    t["kind"] = "bench"
    for node in ("rain", "sunny"):
        k = parse_kv_text(read(base + "_%s.kv" % node) or "")
        t["_kv_" + node] = k
        t["rc_" + node] = meta.get("rc_" + node)
        for key in ("host_native_atomic", "can_map_host", "lat_dev_atom_ns", "lat_host_atom_ns", "lat_host_atom_sys_ns",
                    "lat_dev_ld_ns", "lat_host_ld_ns", "race_host_writes", "race_lost_host_writes", "race_dev_ops",
                    "race_final_low", "race_ms", "race_rc", "name", "exit"):
            t["%s_%s" % (key, node)] = k.get(key)
    return t


def ngt_row(stem):
    t, base = load_trial("ngt", stem)
    meta = t["_meta"]
    t["build"] = meta.get("build")
    t["kind"] = "ngt"
    for node in ("rain", "sunny"):
        k = parse_kv_text(read(base + "_%s.kv" % node) or "")
        t["_kv_" + node] = k
        s = "_" + node
        t["rc" + s] = meta.get("rc_" + node)
        t["ng_result" + s] = k.get("result")
        ra, rb = num(k.get("a_rounds")), num(k.get("b_rounds"))
        t["ng_rounds" + s] = min(ra, rb) if ra is not None and rb is not None else None
        for key in ("lost_writes", "lost_inc", "dekker", "inside_nonzero", "quiesce_timeouts", "backouts", "enters"):
            a, b = num(k.get("a_" + key)), num(k.get("b_" + key))
            t["ng_%s%s" % (key, s)] = a + b if a is not None and b is not None else None
        t["ng_idx_ok" + s] = 1 if (k.get("a_idx_ok") == "1" and k.get("b_idx_ok") == "1") else 0
        t["ng_mr" + s] = k.get("mr")
        t["ng_gid_kind" + s] = k.get("gid_kind")
        t["ng_error" + s] = k.get("setup_error") or k.get("nic_error")
        t["ng_phase_results" + s] = (k.get("a_result"), k.get("b_result"))
        t["ng_hi_ok" + s] = (k.get("a_final_hi") == k.get("a_expected_hi") and k.get("b_final_hi") == k.get("b_expected_hi"))
    return t


def load_all(res):
    RES_DIR[0] = res
    trials = []
    for folder in ("hr", "hq", "hrp", "hqp"):
        for s in stems(folder):
            trials.append(two_rank(folder, s))
    for folder in ("mr_hr", "mr_hq"):
        for s in stems(folder):
            trials.append(four_rank(folder, s))
    for s in stems("bench"):
        trials.append(bench_row(s))
    for s in stems("ngt"):
        trials.append(ngt_row(s))
    for t in trials:
        t["key"] = "%s@%s" % (t["cell"], t["build"])
    return trials


# ------------------------------------------------------------------------------------------------ section 8
HOG_CELLS = {"rh_hog_f1_b", "rh_hog_copystream_f1_b", "rh_hogcall_load_f1_b", "rh_hogcall_malloc_f1_b",
             "rh_hogcall_stream_f1_b"}
FIRES_EXPECTED = {"mr4_cyc_stall": "0:0;1:4;2:6", "mr4_chain_stall": "0:0;1:4", "mr4_f1_01": "0:0"}
HOG_CALLS = {"rh_hog_f1_b": "load,malloc,stream", "rh_hog_copystream_f1_b": "load,malloc,stream",
             "rh_hogcall_load_f1_b": "load", "rh_hogcall_malloc_f1_b": "malloc", "rh_hogcall_stream_f1_b": "stream"}


def exclusion(t):
    """section 8: the first matching exclusion reason, or None (judged)."""
    k = t["kind"]
    if k == "bench":
        if t["rc_rain"] != "0" or t["rc_sunny"] != "0":
            return "bench exit code"
        return None
    if k == "ngt":
        if t["rc_rain"] not in ("0", "1") or t["rc_sunny"] not in ("0", "1"):
            return "NIC gate test ended without a verdict"
        return None
    if t["bind_fail"]:
        return "bind_fail"
    meta = t["_meta"]
    if k == "2":
        f = meta.get("fault")
        hooked = {"F1": [0], "F1both": [0, 1], "F3": [1]}.get(f, [])
        if any(t["n_fires_r%d" % r] == 0 for r in hooked):
            return "fault not applied (no fire)"
        if t["trigger_miss"] > 0:
            return "trigger miss"
        if (f == "F4" or meta.get("kill_r0") == "1") and not t["killed"]:
            return "no kill record"
        if t["cell"] in HOG_CELLS:
            h = num(t["hog_launch_after_launch_ms_r0"])
            fa = t["fault_after_launch_r0_ms"]
            if h is None or fa is None or not (h < fa < h + 3000):
                return "fault outside the GPU-filling window"
        if any(t["n_wdfw_r%d" % r] > 0 or (num(t["rs_fw_overruns_r%d" % r]) or 0) > 0 for r in (0, 1)):
            return "firmware overrun"
        return None
    # four ranks
    c = t["cell"]
    if c in FIRES_EXPECTED:
        if t["fires"] != FIRES_EXPECTED[c] or t["fire_in_traffic"] != 1:
            return "fault not applied (fires)"
    elif t["fires"] is not None:
        return "unexpected fire"
    if t["trigger_miss"] > 0:
        return "trigger miss"
    if t["kill_rank"] is not None and (not t["killed"] or t["kill_in_traffic"] != 1):
        return "kill missing or outside traffic"
    if c in ("mr4_cyc_stall", "mr4_chain_stall"):
        if t["cyc_spread_ms"] is None or t["cyc_spread_ms"] > 250:
            return "rounds do not overlap (cyc_spread_ms)"
    if t["n_wdfw"] > 0 or t["rs_fw_overruns_any"] > 0:
        return "firmware overrun"
    return None


def setting_problems(t):
    """section 8 setting checks; a list of problems (empty: fine)."""
    p = []
    k = t["kind"]
    meta = t["_meta"]
    if k == "ngt":
        for node in ("rain", "sunny"):
            if t["ng_mr_" + node] != "dmabuf" or t["ng_gid_kind_" + node] != "link-local":
                p.append("ngt config %s" % node)
        return p
    if k == "bench":
        return p
    if k == "2":
        b = t["build"]
        killed = None
        if meta.get("fault") == "F4":
            killed = 1
        if meta.get("kill_r0") == "1":
            killed = 0
        for r in (0, 1):
            if r == killed:
                continue
            s = "_r%d" % r
            if b in ("hr", "hq"):
                if not (t["hd_on" + s] >= 1 and t["prod" + s] == "0" and t["hf_on" + s] >= 1 and t["pq_on" + s] >= 1
                        and t["ts_on" + s] >= 1 and t["ua" + s] >= 1):
                    p.append("start lines r%d" % r)
                if b == "hr" and t["hr_on" + s] < 1:
                    p.append("remaining line missing r%d" % r)
                if b == "hq" and t["hr_on" + s] != 0:
                    p.append("remaining line on hq r%d" % r)
                if b == "hr":
                    want = "stream" if t["cell"] == "rh_hog_copystream_f1_b" else "nic"
                    if t["copy_path" + s] != want:
                        p.append("copy path r%d=%s" % (r, t["copy_path" + s]))
                    if want == "nic" and t["lb_off" + s] != 0:
                        p.append("NIC path off line r%d" % r)
            else:  # hrp, hqp
                if t["hd_on" + s] or t["ts_on" + s] or t["hr_on" + s] or t["pq_on" + s] or t["hf_on" + s]:
                    p.append("start line at WARN in production r%d" % r)
                if t["rs_api" + s] != "1" or (num(t["rs_contexts" + s]) or 0) < 1:
                    p.append("rs_api/rs_contexts r%d" % r)
            if t["n_test" + s]:
                p.append("test switch line r%d" % r)
        want_drv = "hr" if b in ("hr", "hq") else b
        if meta.get("drvkey") != want_drv:
            p.append("drvkey %s" % meta.get("drvkey"))
        if t["cell"] in HOG_CELLS:
            for r in (0, 1):
                if t["hog_calls_after_r%d" % r] != HOG_CALLS[t["cell"]]:
                    p.append("hog_calls_after r%d" % r)
        return p
    # four ranks
    N = t["N"]
    b = t["build"]
    if t["n_tson"] < N or t["n_abortflag"] < N:
        p.append("ts/abort lines")
    if t["n_pq"] != N:
        p.append("peer start lines %d" % t["n_pq"])
    if b == "hr":
        if t["n_hr"] != N:
            p.append("remaining lines %d" % t["n_hr"])
        if t["n_lbon"] < N or t["n_lboff"] != 0:
            p.append("NIC path lines on=%d off=%d" % (t["n_lbon"], t["n_lboff"]))
    else:
        if t["n_hr"] != 0:
            p.append("remaining lines on hq")
    if meta.get("mrkey") != "hr":
        p.append("mrkey")
    want = {"mr4_cyc_stall": "0:300;1:300;2:300", "mr4_chain_stall": "0:300;1:300"}.get(t["cell"])
    if t["knob_stall"] != want:
        p.append("stall knob %s" % t["knob_stall"])
    if t["cell"] == "rm4_kill3_untimed":
        if any(t["rx_untimed_r%d" % r] != "1" for r in range(N)):
            p.append("rx_untimed")
    return p


# ------------------------------------------------------------------------------------------------ meta vs cells.sh
def expected_meta(t):
    """the arguments cells.sh gives this trial (re-encoded from cells.sh)."""
    c, k = t["cell"], t["n"]
    inj = 500 + (k * 137) % 700
    hog = "GIN_TS_HOG_MS=3000+GIN_TS_HOG_PROBE=1"
    e = {}
    if t["kind"] == "2":
        e.update(app="default", gap_us="15000", inject=str(inj), iters="120", bytes="262144", extra="", fault="F1",
                 kill_r0="0", kill_delay_ms="", inject1="")
        if c == "rh_hog_f1_b":
            e["extra"] = hog
        elif c == "rh_hog_copystream_f1_b":
            e["extra"] = hog + "+NCCL_GIN_TS_COPY_PATH=stream"
        elif c.startswith("rh_hogcall_"):
            e["extra"] = hog + "+GIN_TS_HOG_CALLS=" + c.split("_")[2]
        elif c == "f1_b":
            pass
        elif c == "f3_b":
            e["fault"] = "F3"
        elif c == "bidirf_sym_b":
            i0 = 60 + (k * 7) % 50
            e.update(app="bidir", gap_us="0", inject=str(i0), inject1=str(i0 - 1 - k % 2), extra="GIN_TS_BIDIR_FUSED=1",
                     fault="F1both", iters="8000", bytes="4096")
        elif c in ("f4_b", "hdp_kill_b"):
            e.update(fault="F4", gap_us="30000", kill_delay_ms=str(3500 + (k * 211) % 900), iters="200", inject="700")
        elif c == "f2rel_b":
            e.update(fault="F2", extra="GIN_TS_RX_WAIT_S=20+GIN_TS_POST_ABORT_WAIT_S=3+NCCL_GIN_TS_USER_ABORT=1",
                     inject="700")
        elif c == "hd_rxdeath_b":
            e.update(fault="none", kill_r0="1", kill_delay_ms="3000", extra="GIN_TS_RX_WAIT_S=15", iters="1000",
                     bytes="16384", inject="700")
        elif c in ("lat_4k", "lat_256k"):
            e.update(fault="lat", gap_us="0", iters="3000", bytes="4096" if c == "lat_4k" else "262144", inject="700")
        return e
    if t["kind"] == "4":
        def hook(a, b):
            ctx = a * 3 + (b if b < a else b - 1)
            return "NCCL_GIN_FAULT_INJECT=local_err:6000+NCCL_GIN_FAULT_INJECT_CTX=%d" % ctx
        st = "+NCCL_GIN_TS_TEST_STALL=300@quiesce"
        e.update(n="4", mode="none", flush="ctx", iters="1000", bytes="4096", gap_us="15000", kill_rank="",
                 kill_delay_ms="", r0env="", r1env="", r2env="", r3env="", mrkey="hr")
        if c == "mr4_cyc_stall":
            e.update(extra="GIN_TS_RX_WAIT_S=10+GIN_MR_GRACE_S=40", r0env=hook(0, 1) + st, r1env=hook(1, 2) + st,
                     r2env=hook(2, 0) + st)
        elif c == "mr4_chain_stall":
            e.update(extra="GIN_TS_RX_WAIT_S=10+GIN_MR_GRACE_S=40", r0env=hook(0, 1) + st, r1env=hook(1, 2) + st)
        elif c == "rm4_kill3_untimed":
            e.update(kill_rank="3", kill_delay_ms="9000", flush="peer", extra="GIN_MR_RX_UNTIMED=1+GIN_MR_GRACE_S=15")
        elif c == "mr4_kill3_peer":
            e.update(kill_rank="3", kill_delay_ms="9000", flush="peer", extra="GIN_TS_RX_WAIT_S=10+GIN_MR_GRACE_S=40")
        elif c == "mr4_none":
            e.update(extra="GIN_TS_RX_WAIT_S=10")
        elif c == "mr4_f1_01":
            e.update(extra="GIN_TS_RX_WAIT_S=10", r0env=hook(0, 1))
        return e
    if t["kind"] == "bench":
        return {"n_lat": "20000", "race_ms": "2000"}
    return {"secs": "5", "hca_rain": "mlx5_1", "hca_sunny": "mlx5_0"}


def meta_problems(t):
    meta = t["_meta"]
    p = []
    for key, want in expected_meta(t).items():
        if (meta.get(key) or "") != want:
            p.append("%s=%r (want %r)" % (key, meta.get(key), want))
    if meta.get("cell") != t["cell"]:
        p.append("cell")
    if t["kind"] in ("2", "4") and meta.get("rdv_nonce_set") != "1":
        p.append("rdv_nonce_set")
    if t["kind"] == "2":
        if meta.get("bundle") != "/home/unionxic/gi-bundle/gin_ts2/%s" % t["build"]:
            p.append("bundle")
        if t["_folder"] != t["build"]:
            p.append("folder")
    if t["kind"] == "4":
        if meta.get("libdir") != "/home/unionxic/gi-bundle/gin_ts2/%s" % t["build"]:
            p.append("libdir")
        if meta.get("mrbin") != "/home/unionxic/gi-bundle/gin_ts2/mr/hr/gin_mr":
            p.append("mrbin")
    return p


# ------------------------------------------------------------------------------------------------ rule evaluator
class Ev:
    """The grammar of ../s2_close/EXPERIMENT.md 3.2 (with ../pair_reset 3.2 arithmetic): count(E), has(F, s), nonempty(F),
    median(F, key), abs, per cell. Numeric strings are floats, blanks None; a comparison or arithmetic with None is false
    (None); a chained comparison needs every pair."""

    def __init__(self, by_key):
        self.by_key = by_key

    def value(self, t, name):
        v = t.get(name)
        if v is None or v == "":
            return None
        if isinstance(v, bool):
            return 1.0 if v else 0.0
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                return v
        return None

    def ev(self, node, t, cellkey):
        E = lambda n: self.ev(n, t, cellkey)  # noqa: E731
        if isinstance(node, ast.Expression):
            return E(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if t is None:
                raise ValueError("column %s outside count()" % node.id)
            return self.value(t, node.id)
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                for v in node.values:
                    if not E(v):
                        return False
                return True
            for v in node.values:
                if E(v):
                    return True
            return False
        if isinstance(node, ast.UnaryOp):
            v = E(node.operand)
            if isinstance(node.op, ast.Not):
                return not v
            if v is None:
                return None
            if isinstance(node.op, ast.USub):
                return -v
            return v
        if isinstance(node, ast.BinOp):
            a, b = E(node.left), E(node.right)
            if a is None or b is None:
                return None
            try:
                if isinstance(node.op, ast.Add):
                    return a + b
                if isinstance(node.op, ast.Sub):
                    return a - b
                if isinstance(node.op, ast.Mult):
                    return a * b
                if isinstance(node.op, ast.Div):
                    return a / b
            except TypeError:
                return None
            raise ValueError("operator")
        if isinstance(node, ast.Compare):
            left = E(node.left)
            for op, rn in zip(node.ops, node.comparators):
                right = E(rn)
                if left is None or right is None:
                    return False
                try:
                    if isinstance(op, ast.Eq):
                        ok = left == right
                    elif isinstance(op, ast.NotEq):
                        ok = left != right
                    elif isinstance(op, ast.Lt):
                        ok = left < right
                    elif isinstance(op, ast.LtE):
                        ok = left <= right
                    elif isinstance(op, ast.Gt):
                        ok = left > right
                    elif isinstance(op, ast.GtE):
                        ok = left >= right
                    else:
                        raise ValueError("comparison")
                except TypeError:
                    return False
                if not ok:
                    return False
                left = right
            return True
        if isinstance(node, ast.Call):
            fn = node.func.id
            if fn == "count":
                trials = self.by_key.get(cellkey, [])
                hits = [x for x in trials if self.ev(node.args[0], x, cellkey)]
                self.last_hits = hits
                self.last_trials = trials
                return float(len(hits))
            if fn == "has":
                v = E(node.args[0])
                s = E(node.args[1])
                return isinstance(v, str) and s in v
            if fn == "nonempty":
                return E(node.args[0]) is not None
            if fn == "abs":
                v = E(node.args[0])
                return None if v is None else abs(v)
            if fn == "median":
                col = node.args[0].id
                key = E(node.args[1])
                vals = [self.value(x, col) for x in self.by_key.get(key, [])]
                vals = [v for v in vals if isinstance(v, float)]
                return statistics.median(vals) if vals else None
            raise ValueError("function %s" % fn)
        raise ValueError("node %s" % type(node).__name__)


def judge(pred, by_key, planned):
    rule = pred["acceptance"].strip()
    cells = [c.strip() for c in pred["cells"].split(";")]
    per_cell = rule.startswith("per cell:")
    expr = rule[len("per cell:"):].strip() if per_cell else rule
    tree = ast.parse(expr, mode="eval")
    ev = Ev(by_key)
    res = []
    if per_cell:
        for c in cells:
            n = len(by_key.get(c, []))
            if n < planned.get(c, 0):
                res.append((c, n, None, "data insufficient", []))
                continue
            ok = ev.ev(tree, None, c)
            hits = [x["_stem"] for x in ev.last_hits]
            miss = [x["_stem"] for x in ev.last_trials if x["_stem"] not in hits]
            res.append((c, n, len(hits), "holds" if ok else "fails", miss))
        verdict = "data insufficient" if any(r[3] == "data insufficient" for r in res) else (
            "holds" if all(r[3] == "holds" for r in res) else "fails")
        return verdict, res
    # one rule over one cell (count) or two cells (median)
    if any(len(by_key.get(c, [])) < planned.get(c, 0) for c in cells):
        return "data insufficient", [(c, len(by_key.get(c, [])), None, "", []) for c in cells]
    if "count(" in expr:
        ok = ev.ev(tree, None, cells[0])
        hits = [x["_stem"] for x in ev.last_hits]
        miss = [x["_stem"] for x in ev.last_trials if x["_stem"] not in hits]
        return ("holds" if ok else "fails"), [(cells[0], len(by_key.get(cells[0], [])), len(hits), "", miss)]
    ok = ev.ev(tree, None, None)
    return ("holds" if ok else "fails"), [(c, len(by_key.get(c, [])), None, "", []) for c in cells]


def load_predictions():
    import csv
    with open(os.path.join(STUDY, "predictions.csv"), newline="") as f:
        return list(csv.DictReader(f))


# ------------------------------------------------------------------------------------------------ formatting helpers
def rng(vals, fmt="%.1f"):
    v = [x for x in vals if x is not None]
    if not v:
        return "none"
    if min(v) == max(v):
        return fmt % min(v)
    return (fmt % min(v)) + "–" + (fmt % max(v))


def med(vals):
    v = [x for x in vals if x is not None]
    return statistics.median(v) if v else None


def git(*args):
    return subprocess.run(["git"] + list(args), cwd=STUDY, capture_output=True, check=False).stdout


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def md5(b):
    return hashlib.md5(b).hexdigest()


def sections(text, nums):
    """the body of each '## <n>.' section of EXPERIMENT.md, by number."""
    parts = re.split(r"(?m)^(?=## \d+\. )", text)
    d = {}
    for p in parts:
        m = re.match(r"## (\d+)\. ", p)
        if m and int(m.group(1)) in nums:
            d[int(m.group(1))] = p
    return d


MASK_RE = re.compile(r"^\s*SUNNY_SSH=.*$", re.M)


# ------------------------------------------------------------------------------------------------ integrity
def integrity():
    out("## Integrity")
    commit = git("rev-parse", TAG + "^{commit}").decode().strip()
    when = git("log", "-1", "--format=%ci", commit).decode().strip()
    out("- tag %s -> commit %s (%s)" % (TAG, commit, when))
    tagged = {}
    for f in ("predictions.csv", "PREREG.txt", "EXPERIMENT.md"):
        tagged[f] = git("cat-file", "-p", "%s:%s/%s" % (TAG, REL, f))
    wt = {f: open(os.path.join(STUDY, f), "rb").read() for f in tagged}
    pr = wt["PREREG.txt"].decode()
    m = re.search(r"\b([0-9a-f]{64})\s+predictions\.csv", pr)
    h_wt, h_tag = sha256(wt["predictions.csv"]), sha256(tagged["predictions.csv"])
    out("- predictions.csv sha256: working tree %s, tag %s, PREREG.txt %s -> %s" % (
        h_wt[:16], h_tag[:16], m.group(1)[:16] if m else None,
        "all equal" if (m and h_wt == h_tag == m.group(1)) else "MISMATCH"))
    out("- PREREG.txt equals the tag's copy: %s" % (wt["PREREG.txt"] == tagged["PREREG.txt"]))
    nrows = wt["predictions.csv"].decode().count("\n") - 1
    kinds = Counter(p["kind"] for p in load_predictions())
    out("- predictions.csv rows: %d (%s)" % (nrows, ", ".join("%s %d" % kv for kv in sorted(kinds.items()))))
    a = sections(wt["EXPERIMENT.md"].decode(), {2, 3, 7, 8})
    b = sections(tagged["EXPERIMENT.md"].decode(), {2, 3, 7, 8})
    for n in (2, 3, 7, 8):
        out("- EXPERIMENT.md section %d byte-identical to the tag: %s (%d bytes)" % (
            n, a.get(n) == b.get(n) and a.get(n) is not None, len(a.get(n, "").encode())))
    out("- EXPERIMENT.md whole file identical to the tag: %s (sha256 %s)" % (
        wt["EXPERIMENT.md"] == tagged["EXPERIMENT.md"], sha256(wt["EXPERIMENT.md"])[:12]))
    # the other study files
    same, masked, diff = [], [], []
    for f in sorted(os.listdir(STUDY)):
        p = os.path.join(STUDY, f)
        if not os.path.isfile(p) or f in tagged or f in ("score.py", "rows_hr.py"):  # the scorer is never opened
            continue
        tb = git("cat-file", "-p", "%s:%s/%s" % (TAG, REL, f))
        if not tb:
            continue
        wb = open(p, "rb").read()
        if wb == tb:
            same.append(f)
        elif MASK_RE.sub("SUNNY", wb.decode(errors="replace")) == MASK_RE.sub("SUNNY", tb.decode(errors="replace")):
            masked.append(f)
        else:
            diff.append(f)
    out("- other tagged files identical to the tag: %s" % ", ".join(same))
    out("- differ from the tag only in the SUNNY_SSH default line (address filter placeholder): %s" % ", ".join(masked))
    out("- differ otherwise: %s" % (", ".join(diff) if diff else "none"))
    for f, want in (("../gin_ts2.cu", "1779db9d"), ("gin_mr.cu", "a6a526ad"), ("hm_bench.cu", "9b13a4b8"),
                    ("nic_gate_test.cu", "4d87f2b8")):
        h = md5(open(os.path.join(STUDY, f), "rb").read())
        out("- source md5 %s = %s (deploy_check/build_info: %s…) %s" % (f, h[:8], want, "ok" if h.startswith(want) else "MISMATCH"))
    dc = read(os.path.join(STUDY, "deploy_check.txt")) or ""
    dn = read(os.path.join(STUDY, "deploy_ngt_check.txt")) or ""
    for h in ("2dee2b5bf36b3477dd85f0197987f028", "786f70bcb82ea21cb678dcb056256ed5", "4e81d8d8e7418f84fe1804284378d618",
              "d588e9cecfc05fd114e61d83ce9c3074", "a00094b07445f2ddc5baff3a5c5626bb"):
        out("- deploy_check.txt lists %s… on source, rain and sunny: %s" % (h[:8], dc.count(h) >= 3))
    out("- deploy_check.txt: 'deployed md5 == source on both nodes' %s, 'existing bundle unchanged' %s" % (
        "deployed md5 == source on both nodes" in dc, "existing bundle unchanged on both nodes" in dc))
    out("- deploy_ngt_check.txt lists abb2af4c… three times: %s; deployed == source: %s" % (
        dn.count("abb2af4cb61a8075242f348c599b407a") >= 3, "deployed md5 == source on both nodes" in dn))
    out("- hq/hqp bundles in deploy_check existing-bundle list: hq libnccl c1311625 %s, hqp 4fa076e1 %s, hq gin_ts2 3e053ff2 %s" % (
        "c1311625c7a06c785bc313558504f982" in dc, "4fa076e113e43774a9dc2f46298df43b" in dc,
        "3e053ff2ab069ec64198ed4e0f6e237a" in dc))
    return commit


def trial_set(trials):
    out("")
    out("## Trial set against section 7")
    by = defaultdict(list)
    for t in trials:
        by[t["key"]].append(t)
    total = len(trials)
    out("- trials found: %d (two-rank %d, latency %d, four-rank %d, benchmark %d, NIC gate %d)" % (
        total, sum(1 for t in trials if t["kind"] == "2" and not t["cell"].startswith("lat_")),
        sum(1 for t in trials if t["cell"].startswith("lat_")), sum(1 for t in trials if t["kind"] == "4"),
        sum(1 for t in trials if t["kind"] == "bench"), sum(1 for t in trials if t["kind"] == "ngt")))
    probs = []
    for key, n in PLANNED.items():
        got = sorted(t["n"] for t in by.get(key, []))
        if got != list(range(1, n + 1)):
            probs.append("%s: %s (planned 1..%d)" % (key, got, n))
    extra = [k for k in by if k not in PLANNED]
    out("- every planned key has exactly n1..nK: %s%s" % ("yes" if not probs else "NO", "" if not probs else " " + "; ".join(probs)))
    out("- keys outside the plan: %s" % (", ".join(extra) if extra else "none"))
    stray = []
    known = {(t["_folder"], t["_stem"]) for t in trials}
    suf = re.compile(r"^(.*_n\d+)_(meta\.txt|r\d\.kv|r\d\.log|kill\.out|decoy\.out|lat_raw\.csv\.gz|rain\.kv|sunny\.kv|"
                     r"rain\.log|sunny\.log)$")
    for folder in ("hr", "hq", "hrp", "hqp", "mr_hr", "mr_hq", "bench", "ngt"):
        for f in os.listdir(os.path.join(RES_DIR[0], folder)):
            m = suf.match(f)
            if not m or (folder, m.group(1)) not in known:
                stray.append("%s/%s" % (folder, f))
    out("- files in the trial folders that belong to no trial: %s" % (stray if stray else "none"))
    folder_bad = [t["_stem"] for t in trials if t["_folder"] != folder_of(t["cell"], t["build"])]
    out("- trial folder matches the build (hold.sh sub): %s" % ("yes" if not folder_bad else folder_bad))
    miss = [t["_stem"] for t in trials if t["kind"] in ("2", "4") and not all(t["_has"])]
    out("- ranks without kv or log: %s" % (miss if miss else "none (killed ranks included)"))
    mp = [(t["key"], t["n"], meta_problems(t)) for t in trials if meta_problems(t)]
    out("- meta arguments equal to cells.sh for every trial: %s" % ("yes" if not mp else mp[:5]))
    return by


# ------------------------------------------------------------------------------------------------ hold logs and safety
def hold_order():
    """the trials in hold.sh order: (hold, folder, cell, build, k)."""
    seq = []

    def c(h, cell, b, n=1, start=1):
        for k in range(start, start + n):
            seq.append((h, folder_of(cell, b), cell, b, k))

    def alt21(h, cell, nb, cb):
        for k in range(1, 6):
            c(h, cell, nb, 2, 2 * k - 1)
            c(h, cell, cb, 1, k)
    for x in ("f1_b", "f3_b", "bidirf_sym_b", "f4_b", "f2rel_b", "hd_rxdeath_b"):
        c("H1", x, "hr", 5)
    c("H1", "hdp_kill_b", "hrp", 5)
    for k in range(1, 6):
        for x in ("lat_4k", "lat_256k"):
            for b in ("hrp", "hqp"):
                c("H1", x, b, 1, k)
    alt21("H2", "rh_hog_f1_b", "hr", "hq")
    c("H2", "rh_hog_copystream_f1_b", "hr", 5)
    for k in range(1, 6):
        for x in ("rh_hogcall_load_f1_b", "rh_hogcall_malloc_f1_b", "rh_hogcall_stream_f1_b"):
            c("H2", x, "hq", 1, k)
            if k <= 3:
                c("H2", x, "hr", 1, k)
    alt21("H3", "mr4_cyc_stall", "hr", "hq")
    c("H3", "mr4_chain_stall", "hr", 5)
    alt21("H4", "rm4_kill3_untimed", "hr", "hq")
    c("H4", "mr4_kill3_peer", "hr", 5)
    c("H5", "mr4_none", "hr", 5)
    c("H5", "mr4_f1_01", "hr", 5)
    c("H5", "hm_bench", "hr", 5)
    c("H5", "nic_gate", "hr", 5)
    return seq


H2_START = re.compile(r"^\[(\w+)/ts1/(\w+)/(\w+)/(\w+)#n(\d+)\] rain=\d+ sunny=\d+ port=(\d+) tries=(\d+) skipped=(\S+) "
                      r"decoy=(\S+) inject=(\d+) bytes=(\d+) iters=(\d+) rtag=")
H2_END = re.compile(r"^\[(\w+)/ts1/(\w+)/(\w+)/(\w+)#n(\d+)\] r0rc=(\d+) r1rc=(\d+) left=(\d+) wall=([\d.]+)s ::")
H4_START = re.compile(r"^\[(\w+)/hr/n4/none/(\w+)#n(\d+)\] gid rain=\d+ sunny=\d+ port=(\d+) tries=(\d+) skipped=(\S+) "
                      r"decoy=(\S+) edges=(\S+) flush=(\S+) kill=(\S+)")
H4_END = re.compile(r"^\[(\w+)/hr/n4/none/(\w+)#n(\d+)\] r0rc=(\d+) r1rc=(\d+) r2rc=(\d+) r3rc=(\d+) left=(\d+) wall=([\d.]+)s ::")
HB_END = re.compile(r"^\[(hm_bench|nic_gate)#n(\d+)\] rc rain=(\S+) sunny=(\S+) ::")
HKILL = re.compile(r"\] SIGKILL rank ?(\d) after (\d+) ms: kill_mono_ms=([\d.]+) pid=(\d+)")
SNAP = re.compile(r"^== (before|after)-(\w+) (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")


def holds(trials, by):
    out("")
    out("## Hold logs, chain and safety")
    idx = {(t["_folder"], t["_stem"]): t for t in trials}
    seq = hold_order()
    problems, nmatched, kills = [], 0, 0
    windows = {}
    snapvals = {}
    for h in ("H1", "H2", "H3", "H4", "H5"):
        text = read(os.path.join(RES, "hold_%s.out" % h)) or ""
        lines = text.splitlines()
        exp = [s for s in seq if s[0] == h]
        starts, ends = [], []
        for ln in lines:
            m = SNAP.match(ln)
            if m:
                windows.setdefault(h, {})[m.group(1)] = m.group(3)
            for pat, kind in ((H2_START, "s2"), (H2_END, "e2"), (H4_START, "s4"), (H4_END, "e4"), (HB_END, "eb")):
                mm = pat.match(ln)
                if mm:
                    (starts if kind[0] == "s" else ends).append((kind, mm))
            km = HKILL.search(ln)
            if km:
                kills += 1
                # match a kill.out with the same kill_mono_ms
                found = any(t["_kill"].get("kill_mono_ms") == km.group(3) for t in trials if t["kind"] in ("2", "4"))
                if not found:
                    problems.append("%s: SIGKILL line without kill.out" % h)
        for key in ("rain mlx5 cmd_err lines", "sunny mlx5 cmd_err lines", "rain fwcmd failed sum"):
            vals = re.findall(r"^%s: (\d+)$" % re.escape(key), text, re.M)
            snapvals[(h, key)] = vals
        if len(ends) != len(exp):
            problems.append("%s: %d result lines for %d planned trials" % (h, len(ends), len(exp)))
        si = 0
        for (hh, folder, cell, b, k), (kind, m) in zip(exp, ends):
            stem = "%s_n%d" % (cell, k)
            t = idx.get((folder, stem))
            if t is None:
                problems.append("%s: no trial files for %s/%s" % (h, folder, stem))
                continue
            meta = t["_meta"]
            if kind == "e2":
                st = starts[si][1] if si < len(starts) and starts[si][0] == "s2" else None
                si += 1
                ok = (m.group(1) == b and int(m.group(5)) == k and m.group(6) == meta.get("r0rc") and m.group(7) == meta.get("r1rc")
                      and m.group(8) == meta.get("left") and m.group(9) == meta.get("wall_s"))
                if st is not None:
                    ok = ok and st.group(6) == meta.get("port") and st.group(7) == meta.get("port_tries")
                else:
                    ok = False
            elif kind == "e4":
                st = starts[si][1] if si < len(starts) and starts[si][0] == "s4" else None
                si += 1
                ok = (m.group(1) == b and m.group(2) == cell and int(m.group(3)) == k
                      and all(m.group(4 + r) == meta.get("r%drc" % r) for r in range(4))
                      and m.group(8) == meta.get("left") and m.group(9) == meta.get("wall_s"))
                if st is not None:
                    ok = ok and st.group(4) == meta.get("port") and st.group(5) == meta.get("port_tries") and st.group(9) == meta.get("flush")
                else:
                    ok = False
            else:
                ok = (m.group(1) == cell and int(m.group(2)) == k and m.group(3) == meta.get("rc_rain")
                      and m.group(4) == meta.get("rc_sunny"))
            if ok:
                nmatched += 1
            else:
                problems.append("%s: %s/%s differs from its hold line" % (h, folder, stem))
            t["_hold"] = h
    out("- hold result lines matched to trial files in hold.sh order (build, trial, port, tries, every rc, left, wall_s): "
        "%d of %d" % (nmatched, len(seq)))
    nk = sum(1 for t in trials if t["kind"] in ("2", "4") and t["_kill"].get("kill_mono_ms"))
    out("- SIGKILL lines in the hold logs: %d; kill.out files with kill_mono_ms: %d" % (kills, nk))
    # every trial's log inside its hold's snapshot window
    outside = []
    firsts = []
    for t in trials:
        if t["kind"] not in ("2", "4") or "_hold" not in t:
            continue
        w = windows.get(t["_hold"], {})
        for L in t["_L"]:
            if L["_first_ts"] is None:
                continue
            firsts.append(L["_first_ts"])
            if not (w.get("before", "") <= L["_first_ts"] and L["_last_ts"] <= w.get("after", "9")):
                outside.append(t["_stem"])
    out("- rank logs inside their hold's snapshot window: %s; earliest log line %s, latest %s" % (
        "all" if not outside else "NOT %s" % sorted(set(outside)), min(firsts), max(
            L["_last_ts"] for t in trials if t["kind"] in ("2", "4") for L in t["_L"] if L["_last_ts"])))
    for h in ("H1", "H2", "H3", "H4", "H5"):
        w = windows.get(h, {})
        out("  - %s: snapshots %s .. %s; rain cmd_err %s, sunny cmd_err %s, rain fw-command failures %s" % (
            h, w.get("before"), w.get("after"), "->".join(snapvals[(h, "rain mlx5 cmd_err lines")]),
            "->".join(snapvals[(h, "sunny mlx5 cmd_err lines")]), "->".join(snapvals[(h, "rain fwcmd failed sum")])))
    chain = read(os.path.join(RES, "chain.out")) or ""
    rcs = re.findall(r"hold (H\d) rc=(\d+)", chain)
    ipt = re.findall(r"before=(\d+) after=(\d+)", chain)
    out("- chain.out: %s; gin- iptables rules before/after %s" % (", ".join("%s rc %s" % x for x in rcs),
                                                                 ", ".join("%s/%s" % x for x in ipt)))
    newl = [(h, os.path.getsize(os.path.join(RES, "mlx5_new_%s.txt" % h))) for h in ("H1", "H2", "H3", "H4", "H5")]
    out("- mlx5_new_H*.txt sizes: %s" % ", ".join("%s %d B" % x for x in newl))
    stops = [f for f in os.listdir(RES) if f.startswith("STOP")]
    out("- STOP files: %s; LEFT_STREAK %s; stale.txt %s" % (stops or "none", (read(os.path.join(RES, "LEFT_STREAK")) or "").strip(),
                                                           os.path.exists(os.path.join(RES, "stale.txt"))))
    lefts = Counter(t["_meta"].get("left") for t in trials if t["kind"] in ("2", "4"))
    out("- left= per trial: %s" % dict(lefts))
    ex = defaultdict(Counter)
    for t in trials:
        if t["kind"] in ("2", "4"):
            ex[t["key"]][" ".join(t["_meta"].get("r%drc" % r) for r in range(len(t["_L"])))] += 1
    out("- rank exit codes per cell key: %s" % "; ".join("%s %s" % (k, dict(v)) for k, v in sorted(ex.items())))
    rc139 = [t["_stem"] for t in trials if any(v == "139" for k, v in t["_meta"].items() if re.match(r"r\drc|rc_", k))]
    bad = []
    for folder in ("hr", "hq", "hrp", "hqp", "mr_hr", "mr_hq", "bench", "ngt"):
        d = os.path.join(RES, folder)
        for f in os.listdir(d):
            if f.endswith(".log") or f.endswith(".kv"):
                x = read(os.path.join(d, f)) or ""
                if re.search(r"illegal address|illegal memory access|unspecified launch failure", x, re.I):
                    bad.append(f)
    out("- exit 139: %s; illegal-address or launch-failure strings: %s" % (rc139 or "none", bad or "none"))
    pre = "2026-10-09 14:49:16"
    out("- first main-run log line %s is after the pre-registration %s: %s" % (min(firsts), pre, min(firsts) > pre))
    allh = "".join(read(os.path.join(RES, "hold_%s.out" % h)) or "" for h in ("H1", "H2", "H3", "H4", "H5"))
    out("- 'Address already in use' in the hold logs: %d; port tries %s; skipped/decoy/occupy other than none: %d" % (
        allh.count("Address already in use"), dict(Counter(t["_meta"].get("port_tries") for t in trials if t["kind"] in ("2", "4"))),
        sum(1 for t in trials if t["kind"] in ("2", "4") and (t["_meta"].get("port_skipped") != "none"
                                                             or t["_meta"].get("decoy_port") != "none"
                                                             or t["_meta"].get("occupy_port") != "none"))))
    ports = [int(t["_meta"]["port"]) for t in trials if t["kind"] in ("2", "4")]
    out("- rendezvous ports %d–%d (%d distinct of %d)" % (min(ports), max(ports), len(set(ports)), len(ports)))
    tot = 0
    for h in ("H1", "H2", "H3", "H4", "H5"):
        x = read(os.path.join(RES, "hold_%s.out" % h)) or ""
        tl = re.findall(r"(?m)^(\S+ \S+) \[grm-%s\] (lock acquired|idle|command exited)" % h, x)
        secs = lambda s: int(s[11:13]) * 3600 + int(s[14:16]) * 60 + int(s[17:19])  # noqa: E731
        d = {b: secs(a) for a, b in tl}
        tot += d["command exited"] - d["lock acquired"]
        out("  - %s: %s; lock to exit %.1f min, idle to exit %.1f min" % (
            h, ", ".join("%s %s" % (b, a[11:]) for a, b in tl), (d["command exited"] - d["lock acquired"]) / 60.0,
            (d["command exited"] - d["idle"]) / 60.0))
    out("  - lock to exit, all five holds: %.1f min" % (tot / 60.0))
    out("- hold-log problems: %s" % (problems if problems else "none"))
    return problems


# ------------------------------------------------------------------------------------------------ main
def main():
    pilots = "--pilots" in sys.argv
    out("# gin-remaining independent recount (qa/recount.py)")
    out("")
    integrity()
    trials = load_all(RES)
    by = trial_set(trials)
    holds(trials, by)

    out("")
    out("## Exclusions (section 8) and setting checks")
    excl = Counter()
    judged = defaultdict(list)
    for t in trials:
        why = exclusion(t)
        t["_excl"] = why
        if why:
            excl[(t["key"], why)] += 1
        else:
            judged[t["key"]].append(t)
    out("- trials %d, judged %d, excluded %d %s" % (len(trials), sum(len(v) for v in judged.values()), sum(excl.values()),
                                                   dict(excl) if excl else ""))
    sp = [(t["key"], t["n"], setting_problems(t)) for t in trials if setting_problems(t)]
    out("- setting-check problems: %d %s" % (len(sp), sp[:8] if sp else ""))
    # inputs of the exclusions
    two = [t for t in trials if t["kind"] == "2"]
    four = [t for t in trials if t["kind"] == "4"]
    out("- inputs: bind failures %d; trigger misses %d; hooked two-rank ranks without a fire %d; kill trials without a kill "
        "record %d" % (sum(t["bind_fail"] for t in two + four), sum(t["trigger_miss"] for t in two + four),
                       sum(1 for t in two if exclusion(t) == "fault not applied (no fire)"),
                       sum(1 for t in two + four if (t["_meta"].get("fault") == "F4" or t["_meta"].get("kill_r0") == "1"
                                                     or t.get("kill_rank") is not None) and not t["killed"])))
    hogs = [t for t in two if t["cell"] in HOG_CELLS]
    out("  - GPU-full cells (n=%d): rank 0 fault %s ms after the GIN launch, GPU-filling launch %s ms after it; fault − "
        "filling launch %s ms (window 0–3000)" % (
            len(hogs), rng([t["fault_after_launch_r0_ms"] for t in hogs]),
            rng([num(t["hog_launch_after_launch_ms_r0"]) for t in hogs]),
            rng([t["fault_after_launch_r0_ms"] - num(t["hog_launch_after_launch_ms_r0"]) for t in hogs])))
    for c in ("mr4_cyc_stall@hr", "mr4_cyc_stall@hq", "mr4_chain_stall@hr"):
        ts = by.get(c, [])
        out("  - %s: fires %s; fires in traffic %d/%d; cyc_spread_ms %s (limit 250)" % (
            c, dict(Counter(t["fires"] for t in ts)), sum(1 for t in ts if t["fire_in_traffic"] == 1), len(ts),
            rng([t["cyc_spread_ms"] for t in ts])))
    ts = by.get("mr4_f1_01@hr", [])
    out("  - mr4_f1_01@hr: fires %s, in traffic %d/%d" % (dict(Counter(t["fires"] for t in ts)),
                                                         sum(1 for t in ts if t["fire_in_traffic"] == 1), len(ts)))
    kts = [t for t in four if t["kill_rank"] is not None]
    out("  - four-rank kill trials (n=%d): kill %s ms after the last kernel launch, %s ms before the earliest nominal "
        "traffic end (need >= 5000); in traffic %d/%d" % (
            len(kts), rng([t["kill_after_last_launch"] for t in kts]), rng([t["kill_before_end"] for t in kts]),
            sum(1 for t in kts if t["kill_in_traffic"] == 1), len(kts)))
    wd_fw = sum(t.get("n_wdfw_r0", 0) + t.get("n_wdfw_r1", 0) for t in two) + sum(t["n_wdfw"] for t in four)
    wd_other = [(t["key"], t["n"]) for t in two if t["n_wdany_r0"] + t["n_wdany_r1"] > t["n_wdfw_r0"] + t["n_wdfw_r1"]]
    wd_other4 = [(t["key"], t["n"]) for t in four if t["n_wdany"] > t["n_wdfw"]]
    fwo = sum(1 for t in two for r in (0, 1) if (num(t["rs_fw_overruns_r%d" % r]) or 0) > 0)
    out("  - firmware watchdog lines ('firmware command phase'): %d; rs_fw_overruns > 0 (rank kv): %d" % (wd_fw, fwo))
    out("  - other 'watchdog rank=' lines (not firmware): %d trials %s" % (len(wd_other) + len(wd_other4),
                                                                         dict(Counter(k for k, _ in wd_other + wd_other4))))
    bench = by.get("hm_bench@hr", [])
    ngt = by.get("nic_gate@hr", [])
    out("  - benchmark exit codes rain/sunny: %s; NIC gate exit codes: %s; NIC gate mr/gid_kind: %s" % (
        dict(Counter((t["rc_rain"], t["rc_sunny"]) for t in bench)), dict(Counter((t["rc_rain"], t["rc_sunny"]) for t in ngt)),
        dict(Counter((t["ng_mr_rain"], t["ng_gid_kind_rain"], t["ng_mr_sunny"], t["ng_gid_kind_sunny"]) for t in ngt))))

    # parse coverage
    cov, parsed = Counter(), Counter()
    for t in trials:
        if t["kind"] not in ("2", "4"):
            continue
        for L in t["_L"]:
            cov.update(L["_cov"])
            for k in COVER:
                parsed[k] += len(L[k])
    out("- parse coverage (lines with the fixed text / lines parsed): " + ", ".join(
        "%s %d/%d" % (k, cov[k], parsed[k]) for k in COVER))

    # verdicts
    out("")
    out("## Verdicts")
    preds = load_predictions()
    planned = dict(PLANNED)
    vcount = Counter()
    rows = []
    for p in preds:
        v, res = judge(p, judged, planned)
        vcount[v] += 1
        rows.append((p, v, res))
        cellstr = "; ".join("%s n=%d hits=%s%s" % (c, n, "-" if h is None else h, (" miss=" + ",".join(miss)) if miss else "")
                            for (c, n, h, _, miss) in res)
        out("- %-4s %-17s %s :: %s" % (p["id"], v, p["acceptance"][:0], cellstr))
    out("- verdict counts: %s" % dict(vcount))
    # cross-check of transparent_ok: both ranks outcome ok and every rank exit 0
    mism = []
    for t in trials:
        if t["kind"] == "2":
            alt = t["_outcome_ok"]
        elif t["kind"] == "4":
            alt = 1 if (all(t["_kv"][r].get("outcome") == "ok" for r in range(t["N"]))
                        and all(t["_meta"].get("r%drc" % r) == "0" for r in range(t["N"]))) else 0
        else:
            continue
        if alt != t["transparent_ok"]:
            mism.append(t["_stem"])
    out("- transparent_ok equals 'every rank outcome=ok and exit 0' in every two- and four-rank trial: %s" % (
        "yes" if not mism else mism))
    # median rules: show the numbers
    for c in ("lat_4k", "lat_256k"):
        a = med([num(t["lat_p50_us"]) for t in judged["%s@hrp" % c]])
        b = med([num(t["lat_p50_us"]) for t in judged["%s@hqp" % c]])
        out("- %s: median p50 hrp %.2f, hqp %.2f, difference %+.2f us" % (c, a, b, a - b))
    # non-vacuity: each new or control rule's condition counted on the other build's cell of the same name
    out("- rule conditions on the other build's cell (non-vacuity check):")
    for p in preds:
        cells = [c.strip() for c in p["cells"].split(";")]
        if p["kind"] == "R" or len(cells) != 1 or "count(" not in p["acceptance"]:
            continue
        c = cells[0]
        cell, b = c.split("@")
        other = {"hr": "hq", "hq": "hr"}.get(b)
        ok = "%s@%s" % (cell, other)
        if other is None or ok not in judged:
            continue
        expr = p["acceptance"].strip()
        inner = re.match(r"count\((.*)\)\s*(>=|==)\s*\d+$", expr)
        if not inner:
            continue
        tree = ast.parse(inner.group(1), mode="eval")
        ev = Ev(judged)
        hits = sum(1 for t in judged[ok] if ev.ev(tree, t, ok))
        out("  - %s condition on %s: %d/%d" % (p["id"], ok, hits, len(judged[ok])))

    keynumbers(judged, trials)
    if pilots:
        pilot_checks()
    return 0


# ------------------------------------------------------------------------------------------------ key numbers
def keynumbers(J, trials):
    out("")
    out("## Key numbers (each range says what it is a range of)")
    # ---- cycle
    out("### Cycle and chain (four ranks)")
    for c in ("mr4_cyc_stall@hr", "mr4_cyc_stall@hq", "mr4_chain_stall@hr"):
        ts = J.get(c, [])
        out("- %s (n=%d): transparent %d/%d; handshake timeouts per trial %s; declines per trial %s; recovered initiator "
            "lists %s" % (c, len(ts), sum(t["transparent_ok"] for t in ts), len(ts), dict(Counter(t["n_hs"] for t in ts)),
                          dict(Counter(t["n_decl"] for t in ts)), dict(Counter(t["rec_i"] for t in ts))))
        out("  - last resume − first round line (rank 0 clock), range over trials: %s ms (median %s); first resume: %s ms" % (
            rng([t["rec_last_after_round_ms"] for t in ts]), "%.1f" % med([t["rec_last_after_round_ms"] for t in ts])
            if med([t["rec_last_after_round_ms"] for t in ts]) is not None else "none",
            rng([t["rec_first_after_round_ms"] for t in ts])))
        out("  - first handshake timeout − its rank's first round line (same rank's clock): %s ms; all handshake timeouts: %s ms" % (
            rng([t["hs_first_after_round_ms"] for t in ts]), rng([x for t in ts for x in t["hs_after_round_all"]])))
        out("  - round-start spread: %s ms; served inside an ACK wait per trial %s (n_served range %s); kept per trial %s; "
            "served rounds that ended with a responder recovery per trial %s" % (
                rng([t["cyc_spread_ms"] for t in ts]), dict(Counter(t["n_served"] for t in ts)),
                rng([t["n_served"] for t in ts], "%d"), dict(Counter(t["n_kept"] for t in ts)),
                dict(Counter(t["n_served_rec"] for t in ts))))
        out("  - served lists %s; kept lists %s" % (dict(Counter(t["served"] for t in ts)), dict(Counter(t["kept"] for t in ts))))
        out("  - nested round length ('back to round ... (x ms)'), pooled over all nested rounds: %s ms (n=%d); kept REQ "
            "answered after %s ms (n=%d); kept REQs dropped %s" % (
                rng([x for t in ts for x in t["_served_ms"]]), sum(len(t["_served_ms"]) for t in ts),
                rng([x for t in ts for _, x in t["_keptans"]]), sum(len(t["_keptans"]) for t in ts),
                dict(Counter(w for t in ts for _, w in t["_keptdrop"])) or 0))
        out("  - nested rounds that ended with this rank's responder recovery: %s ms (n=%d); the others (refused): %s ms (n=%d)" % (
            rng([x for t in ts for x in t.get("_served_ms_rec", [])]), sum(len(t.get("_served_ms_rec", [])) for t in ts),
            rng([x for t in ts for x in t.get("_served_ms_norec", [])]), sum(len(t.get("_served_ms_norec", [])) for t in ts)))
        tds = [m for t in ts for r in range(t["N"]) for m in t["_L"][r]["td"]]
        out("  - teardown counters: served_in_wait sum %d vs served lines %d; kept sum %d vs kept lines %d" % (
            sum(int(m.group(7)) for m in tds), sum(t["n_served"] for t in ts), sum(int(m.group(8)) for m in tds),
            sum(t["n_kept"] for t in ts)))
        reruns = sum(1 for t in ts for r in range(t["N"])
                     for m in log_msgs(read(os.path.join(RES, t["_folder"], t["_stem"] + "_r%d.log" % r)))[0]
                     if "rerunning as a full reset" in m)
        out("  - 'refused the scope of round ...; rerunning as a full reset' lines: %d" % reruns)
        out("  - REQ scope checks: %s; decline reasons %s; copy paths %s; teardown paths %s; stream copies %d; NIC timeouts %d" % (
            dict(sum((t["_refq"] for t in ts), Counter())), dict(sum((t["decl_reasons"] for t in ts), Counter())),
            dict(sum((t["copy_paths"] for t in ts), Counter())), dict(sum((t["td_paths"] for t in ts), Counter())),
            sum(t["td_stream_copies"] for t in ts), sum(t["td_nic_timeouts"] for t in ts)))
        out("  - wall_s: %s s; outcomes %s" % (rng([num(t["_meta"].get("wall_s")) for t in ts]),
                                              dict(sum((t["outcomes"] for t in ts), Counter()))))
    # ---- degraded
    out("### Degraded (four ranks, rank 3 killed)")
    for c in ("rm4_kill3_untimed@hr", "rm4_kill3_untimed@hq", "mr4_kill3_peer@hr"):
        ts = J.get(c, [])
        surv = (0, 1, 2)
        out("- %s (n=%d): rank 3's receive released on survivors per trial %s; survivor-survivor receives released per "
            "trial %s; degraded lines per trial %s (ranks %s)" % (
                c, len(ts), dict(Counter(t["n_rel_dead"] for t in ts)), dict(Counter(t["n_rel_surv"] for t in ts)),
                dict(Counter(t["n_degraded"] for t in ts)), dict(Counter(t["degr_ranks"] for t in ts))))
        out("  - release of the receive from rank 3 − that survivor's judged-dead line (same clock), pooled over 3 survivors "
            "× trials: %s ms" % rng([t.get("rel_after_dead_ms_r%d" % r) for t in ts for r in surv]))
        out("  - degraded release line − judged-dead line (same rank), pooled: %s ms; − the schedule line: %s ms; "
            "judged dead − kill (rank 0 clock): %s ms; first decline − judged dead (same rank): %s ms" % (
                rng([t.get("degr_after_dead_ms_r%d" % r) for t in ts for r in surv]),
                rng([t.get("degr_after_sched_ms_r%d" % r) for t in ts for r in surv]),
                rng([t.get("judged_after_kill_ms_r%d" % r) for t in ts for r in surv]),
                rng([t.get("decl_after_judged_ms_r%d" % r) for t in ts for r in surv])))
        out("  - survivor edges ok %s; survivor sends ok %s; survivor sends failed %s; survivor receives failed %s; "
            "survivor kernels ended %s; given up %s (outcome kernel_stuck %s)" % (
                dict(Counter(t["surv_edges_ok"] for t in ts)), dict(Counter(t["surv_tx_ok"] for t in ts)),
                dict(Counter(t["surv_tx_failed"] for t in ts)), dict(Counter(t["surv_rx_failed"] for t in ts)),
                dict(Counter(t["n_kdone_surv"] for t in ts)), dict(Counter(t["n_stuck_surv"] for t in ts)),
                dict(Counter(t["n_stuck_surv_outcome"] for t in ts))))
        out("  - survivor kernel end − kill (rank 0 clock), pooled: %s ms; per-peer lines %s; devComm error lines %d; causes %s; "
            "outcomes %s; wall_s %s s" % (
                rng([x for t in ts for x in t.get("_surv_kend_after_kill", [])]), dict(Counter(t["uapeer"] for t in ts)),
                sum(t["n_uaerr"] for t in ts), dict(sum((t["causes"] for t in ts), Counter())),
                dict(sum((t["outcomes"] for t in ts), Counter())), rng([num(t["_meta"].get("wall_s")) for t in ts])))
        rel_its = [int(v) for t in ts for (a, s_), v in t.get("_rel_it", {}).items() if v not in (None, "-1") and a != 3]
        out("  - iteration at which survivor-survivor receives were released: %s (n=%d)" % (rng(rel_its, "%d"), len(rel_its)))
        out("  - degraded release line − first decline line (same rank), pooled: %s ms; the info line's 'judged dead x ms ago': "
            "%s ms; release of the receive from rank 3 − first decline (same rank): %s ms" % (
                rng([t.get("degr_after_decl_ms_r%d" % r) for t in ts for r in surv]),
                rng([t.get("degr_info_ms_r%d" % r) for t in ts for r in surv]),
                rng([t.get("rel_after_decl_ms_r%d" % r) for t in ts for r in surv])))
        rcit = [num(t["_kv"][b].get("rx_%d%d_rcit" % (a, b))) for t in ts for a in surv for b in surv if a != b]
        rcs = Counter(t["_kv"][b].get("rx_%d%d_rc" % (a, b)) for t in ts for a in surv for b in surv if a != b)
        sigs = Counter((t["_kv"][b].get("rx_%d%d_sig" % (a, b)), t["_kv"][b].get("rx_%d%d_sigwant" % (a, b)))
                       for t in ts for a in surv for b in surv if a != b)
        out("  - survivor-survivor receives: rc %s; rc iteration %s (n=%d); final signal/target %s" % (
            dict(rcs), rng(rcit, "%d"), len([x for x in rcit if x is not None]), dict(sigs)))
        d3 = Counter(t["_kv"][b].get("rx_3%d_rc" % b) for t in ts for b in surv)
        t3 = Counter(t["_kv"][a].get("tx_%d3_rc" % a) for t in ts for a in surv)
        out("  - receives from rank 3: rc %s; sends to rank 3: rc %s" % (dict(d3), dict(t3)))
        allrel = [num(t["_kv"][b].get("rx_%d%d_rel_mono_ms" % (a, b))) - t["dead_ms_r%d" % b]
                  for t in ts for b in surv for a in range(4) if a != b
                  and t["_kv"][b].get("rx_%d%d_rel" % (a, b)) == "1" and t["dead_ms_r%d" % b] is not None]
        out("  - every released receive (from any rank) − the receiver's judged-dead line: %s ms (n=%d)" % (
            rng(allrel), len(allrel)))
    # ---- NIC path
    out("### NIC copy path")
    hr_logs = [(t, r) for t in trials if t["build"] == "hr" and t["kind"] in ("2", "4") for r in range(len(t["_L"]))]
    lbon = [m for t, r in hr_logs for m in t["_L"][r]["lbon"]]
    out("- hr rank logs %d; remaining start lines %d (copy_path %s); NIC path on lines %d, off lines %d" % (
        len(hr_logs), sum(len(t["_L"][r]["hr"]) for t, r in hr_logs),
        dict(Counter(m.group(2) for t, r in hr_logs for m in t["_L"][r]["hr"])), len(lbon),
        sum(len(t["_L"][r]["lboff"]) for t, r in hr_logs)))
    out("- NIC path on: gid_index %s (%s); GPU MRs per context %s, dmabuf %s, peermem %s; self-test bytes %s, nonzero %s; "
        "setup %s ms" % (dict(Counter(m.group(4) for m in lbon)), dict(Counter(m.group(5) for m in lbon)),
                         dict(Counter(m.group(6) for m in lbon)), rng([int(m.group(7)) for m in lbon], "%d"),
                         rng([int(m.group(8)) for m in lbon], "%d"), dict(Counter(m.group(9) for m in lbon)),
                         rng([int(m.group(10)) for m in lbon], "%d"), rng([float(m.group(11)) for m in lbon])))
    for kd in ("2", "4"):
        ms = [m for t, r in hr_logs if t["kind"] == kd for m in t["_L"][r]["lbon"]]
        out("  - %s ranks: on lines %d; GPU MRs %s; self-test bytes %s, nonzero %s; setup %s ms" % (
            "two" if kd == "2" else "four", len(ms), dict(Counter(m.group(6) for m in ms)), dict(Counter(m.group(9) for m in ms)),
            rng([int(m.group(10)) for m in ms], "%d"), rng([float(m.group(11)) for m in ms])))
    tds = [m for t, r in hr_logs for m in t["_L"][r]["td"]]
    out("- teardown lines %d: path %s; nic_timeouts sum %d; fallbacks sum %d; stream_copies on nic-path ranks %s; on "
        "stream-path ranks %s" % (len(tds), dict(Counter(m.group(2) for m in tds)), sum(int(m.group(5)) for m in tds),
                                  sum(int(m.group(9)) for m in tds),
                                  rng([int(m.group(6)) for m in tds if m.group(2) == "nic"], "%d"),
                                  rng([int(m.group(6)) for m in tds if m.group(2) == "stream"], "%d")))
    for c in ("rh_hog_f1_b@hr", "rh_hog_copystream_f1_b@hr", "f1_b@hr", "f3_b@hr", "bidirf_sym_b@hr"):
        ts = J.get(c, [])
        out("  - %s: copy paths %s; teardown paths %s; stream copies r0 %s, r1 %s; NIC ops r0 %s; copy timeouts r0 %s, r1 %s" % (
            c, dict(Counter((t["copy_path_r0"], t["copy_path_r1"]) for t in ts)),
            dict(Counter((t["td_path_r0"], t["td_path_r1"]) for t in ts)),
            rng([t["td_stream_copies_r0"] for t in ts], "%d"), rng([t["td_stream_copies_r1"] for t in ts], "%d"),
            rng([t["td_nic_ops_r0"] for t in ts], "%d"), dict(Counter(t["n_copyto_r0"] for t in ts)),
            dict(Counter(t["n_copyto_r1"] for t in ts))))
    # ---- GPU hog cells and three-call split
    out("### GPU-full cells and the three calls")
    for c in ("rh_hog_f1_b@hr", "rh_hog_f1_b@hq", "rh_hog_copystream_f1_b@hr", "rh_hogcall_load_f1_b@hq",
              "rh_hogcall_load_f1_b@hr", "rh_hogcall_malloc_f1_b@hq", "rh_hogcall_malloc_f1_b@hr",
              "rh_hogcall_stream_f1_b@hq", "rh_hogcall_stream_f1_b@hr"):
        ts = J.get(c, [])
        out("- %s (n=%d): transparent %d; rank 0 initiator recoveries %s; copy timeouts r0 %s r1 %s; probe copies done "
            "within 200 ms r0 %s r1 %s (of %s); GPU-filling blocks started at the probe r0 %s r1 %s; hog_calls_after %s; "
            "decline reasons r0 %s; wall_s %s" % (
                c, len(ts), sum(t["transparent_ok"] for t in ts), dict(Counter(t["rec_init_r0"] for t in ts)),
                dict(Counter(t["n_copyto_r0"] for t in ts)), dict(Counter(t["n_copyto_r1"] for t in ts)),
                dict(Counter(t["probe_done_200ms_r0"] for t in ts)), dict(Counter(t["probe_done_200ms_r1"] for t in ts)),
                dict(Counter(t["probe_n_r0"] for t in ts)), dict(Counter(t["hog_started_probe_r0"] for t in ts)),
                dict(Counter(t["hog_started_probe_r1"] for t in ts)), dict(Counter(t["hog_calls_after_r0"] for t in ts)),
                dict(Counter(t["declwhy_r0"] for t in ts)), rng([num(t["_meta"].get("wall_s")) for t in ts])))
        wd = sum(t["n_wdany_r0"] + t["n_wdany_r1"] for t in ts)
        if wd:
            gaps, txit = [], []
            for t in ts:
                L0 = t["_L"][0]
                w = [float(x) for m in L0["wdany"] for x in re.findall(r"mono_ms=([\d.]+)", m.group(2))]
                ct = []
                for msg in log_msgs(read(os.path.join(RES, t["_folder"], t["_stem"] + "_r0.log")))[0]:
                    if R["copyto"].search(msg):
                        ct.append(float(re.search(r"mono_ms=([\d.]+)", msg).group(1)))
                if w and ct:
                    gaps.append(ct[0] - w[0])
                txit.append(t["_kv"][0].get("tx_rc_it"))
            out("  - 'watchdog rank=' lines (not firmware, 'fault records are queued and the recovery helper is not running'): "
                "%d over the cell (%s per rank 0/1); rank 0 copy timeout − that line %s ms; copy-timeout lines per trial (both "
                "ranks) %s; rank 0 sender error at iteration %s" % (
                    wd, dict(Counter((t["n_wdany_r0"], t["n_wdany_r1"]) for t in ts)), rng(gaps),
                    dict(Counter(t["n_copyto_r0"] + t["n_copyto_r1"] for t in ts)), dict(Counter(txit))))
    # ---- NIC gate test
    out("### NIC gate test")
    ts = J.get("nic_gate@hr", [])
    for node in ("rain", "sunny"):
        out("- %s: result %s; phase results %s; rounds min(a,b) %s; a_rounds %s, b_rounds %s; backouts a+b %s; enters a+b %s; "
            "lost writes %s; lost increments %s; Dekker %s; inside while odd %s; quiesce timeouts %s; index words ok %s; final "
            "high half = last write %s; nic_errors %s" % (
                node, dict(Counter(t["ng_result_" + node] for t in ts)), dict(Counter(t["ng_phase_results_" + node] for t in ts)),
                rng([t["ng_rounds_" + node] for t in ts], "%d"), rng([num(t["_kv_" + node].get("a_rounds")) for t in ts], "%d"),
                rng([num(t["_kv_" + node].get("b_rounds")) for t in ts], "%d"), rng([t["ng_backouts_" + node] for t in ts], "%d"),
                rng([t["ng_enters_" + node] for t in ts], "%d"), rng([t["ng_lost_writes_" + node] for t in ts], "%d"),
                rng([t["ng_lost_inc_" + node] for t in ts], "%d"), rng([t["ng_dekker_" + node] for t in ts], "%d"),
                rng([t["ng_inside_nonzero_" + node] for t in ts], "%d"), rng([t["ng_quiesce_timeouts_" + node] for t in ts], "%d"),
                dict(Counter(t["ng_idx_ok_" + node] for t in ts)), dict(Counter(t["ng_hi_ok_" + node] for t in ts)),
                dict(Counter(t["_kv_" + node].get("nic_errors") for t in ts))))
        out("  - quiesce max ms a %s, b %s; nic_ops %s" % (
            rng([num(t["_kv_" + node].get("a_q_max_ms")) for t in ts], "%.3f"),
            rng([num(t["_kv_" + node].get("b_q_max_ms")) for t in ts], "%.3f"),
            rng([num(t["_kv_" + node].get("nic_ops")) for t in ts], "%d")))
    # ---- hm_bench
    out("### Host-memory benchmark")
    ts = J.get("hm_bench@hr", [])
    for node in ("rain", "sunny"):
        out("- %s (%s): host_native_atomic %s, can_map_host %s; dependent atomic add device %s ns, host-mapped %s ns "
            "(sys %s ns); difference host − device %s ns; ld device %s ns, host %s ns" % (
                node, dict(Counter(t["name_" + node] for t in ts)), dict(Counter(t["host_native_atomic_" + node] for t in ts)),
                dict(Counter(t["can_map_host_" + node] for t in ts)), rng([num(t["lat_dev_atom_ns_" + node]) for t in ts]),
                rng([num(t["lat_host_atom_ns_" + node]) for t in ts]), rng([num(t["lat_host_atom_sys_ns_" + node]) for t in ts]),
                rng([num(t["lat_host_atom_ns_" + node]) - num(t["lat_dev_atom_ns_" + node]) for t in ts]),
                rng([num(t["lat_dev_ld_ns_" + node]) for t in ts]), rng([num(t["lat_host_ld_ns_" + node]) for t in ts])))
        out("  - race: host writes %s, read back changed by the device %s (%s of writes); device ops %s; final count half %s; "
            "rc %s" % (rng([num(t["race_host_writes_" + node]) for t in ts], "%d"),
                       rng([num(t["race_lost_host_writes_" + node]) for t in ts], "%d"),
                       rng([100.0 * num(t["race_lost_host_writes_" + node]) / num(t["race_host_writes_" + node]) for t in ts], "%.1f%%"),
                       rng([num(t["race_dev_ops_" + node]) for t in ts], "%d"),
                       dict(Counter(t["race_final_low_" + node] for t in ts)), dict(Counter(t["race_rc_" + node] for t in ts))))
    # ---- regression
    out("### Regression cells")
    for c in ("f1_b@hr", "f3_b@hr", "bidirf_sym_b@hr", "mr4_none@hr", "mr4_f1_01@hr"):
        ts = J.get(c, [])
        extra = ""
        if c == "f1_b@hr":
            extra = "; stats r0 rounds/recovered/declined %s, r1 %s" % (
                dict(Counter((t["rs_rounds_r0"], t["rs_recovered_r0"], t["rs_declined_r0"]) for t in ts)),
                dict(Counter((t["rs_rounds_r1"], t["rs_recovered_r1"]) for t in ts)))
        if c.startswith("mr4_f1"):
            extra = "; recovered initiator lists %s; declines %s" % (dict(Counter(t["rec_i"] for t in ts)),
                                                                     dict(Counter(t["n_decl"] for t in ts)))
        if c == "mr4_none@hr":
            extra = "; round lines %s; declines %s" % (dict(Counter(t["n_round_lines"] for t in ts)),
                                                       dict(Counter(t["n_decl"] for t in ts)))
        out("- %s: transparent %d/%d (cross-check outcome ok and rc 0: %s)%s" % (
            c, sum(t["transparent_ok"] for t in ts), len(ts),
            sum(t.get("_outcome_ok", 1 if t.get("outcomes") == Counter({"ok": 4}) else 0) for t in ts), extra))
    ts = J.get("f4_b@hr", [])
    out("- f4_b@hr: first decline − kill (rank 0 clock) %s ms; reasons %s; cause %s; devComm word why %s; teardown r0 %s; "
        "degraded lines %d" % (rng([t["decl_after_kill_ms_r0"] for t in ts], "%.2f"), dict(Counter(t["declwhy_r0"] for t in ts)),
                               dict(Counter(t["cause_r0"] for t in ts)), dict(Counter(t["uaerr_why_r0"] for t in ts)),
                               dict(Counter(t["teardown_r0"] for t in ts)),
                               sum(1 for t in ts for m in t["_L"][0]["uaword"] if m.group(2) == "degraded")
                               + sum(len(t["_L"][0]["degsched"]) for t in ts)))
    ts = J.get("hd_rxdeath_b@hr", [])
    out("- hd_rxdeath_b@hr: rank 1 kernel end − rank 0 kill %s ms; first async error − kill %s ms; judged-dead lines r1 %s; "
        "rx_rc %s; teardown r1 %s" % (rng([t["release_after_kill_ms_r1"] for t in ts]), rng([t["async_after_kill_ms_r1"] for t in ts]),
                                      dict(Counter(t["n_judged_r1"] for t in ts)), dict(Counter(t["rx_rc"] for t in ts)),
                                      dict(Counter(t["teardown_r1"] for t in ts))))
    ts = J.get("f2rel_b@hr", [])
    out("- f2rel_b@hr: decline r0 %s; r1 outcome %s; rx_rc %s; phantom r1 %s; teardown r1 %s, %s ms" % (
        dict(Counter(t["decl_r0"] for t in ts)), dict(Counter(t["r1_outcome"] for t in ts)), dict(Counter(t["rx_rc"] for t in ts)),
        dict(Counter(t["rx_phantom_r1"] for t in ts)), dict(Counter(t["teardown_r1"] for t in ts)),
        rng([t["teardown_ms_r1"] for t in ts])))
    ts = J.get("hdp_kill_b@hrp", [])
    kinds = Counter()
    for t in ts:
        for r in (0, 1):
            for m in log_msgs(read(os.path.join(RES, "hrp", t["_stem"] + "_r%d.log" % r)))[0]:
                kinds[" ".join(re.sub(r"0x[0-9a-f]+|[0-9.]+", "#", m).split()[:6])] += 1
    out("- hdp_kill_b@hrp: decline − kill %s ms; reasons %s; deaths r0 %s; ts_on r0/r1 %s; remaining line r0 %s; rs_api %s; "
        "teardown r0 %s" % (
            rng([t["decl_after_kill_ms_r0"] for t in ts], "%.2f"), dict(Counter(t["declwhy_r0"] for t in ts)),
            dict(Counter(t["rs_deaths_r0"] for t in ts)), dict(Counter((t["ts_on_r0"], t["ts_on_r1"]) for t in ts)),
            dict(Counter(t["hr_on_r0"] for t in ts)), dict(Counter(t["rs_api_r0"] for t in ts)),
            dict(Counter(t["teardown_r0"] for t in ts))))
    out("  - every GIN/ line kind in the production logs (both ranks, 5 trials): %s" % dict(kinds))
    # ---- latency
    out("### Latency")
    for c in ("lat_4k", "lat_256k"):
        for b in ("hrp", "hqp"):
            ts = J.get("%s@%s" % (c, b), [])
            rec = []
            for t in ts:
                raw = gzip.open(os.path.join(RES, b, t["_stem"] + "_lat_raw.csv.gz"), "rt").read().split()
                v = sorted(int(x.split(",")[1]) for x in raw)
                k = int(0.5 * (len(v) - 1) + 0.5)
                rec.append(("%.2f" % (v[k] / 1e3)) == t["lat_p50_us"])
                t["_n_raw"] = len(v)
            out("- %s@%s: p50 per run %s us (median %.2f); raw samples per run %s; p50 recomputed from raw equals kv %d/%d" % (
                c, b, ", ".join(t["lat_p50_us"] for t in sorted(ts, key=lambda x: x["n"])),
                med([num(t["lat_p50_us"]) for t in ts]), dict(Counter(t["_n_raw"] for t in ts)), sum(rec), len(rec)))


# ------------------------------------------------------------------------------------------------ pilots (statements only)
def pilot_checks():
    out("")
    out("## Pilot statements (EXPERIMENT.md 12; pilots are not scored)")
    tp = load_all(PILOT)
    for t in tp:
        t["_excl"] = None
    by = defaultdict(list)
    for t in tp:
        by[t["key"]].append(t)
    out("- pilot P0/P1 trials: %d (%s)" % (len(tp), dict(Counter(t["key"] for t in tp))))
    for c in ("rh_hog_f1_b@hr", "rh_hog_f1_b@hq", "rh_hog_copystream_f1_b@hr", "rh_hogcall_load_f1_b@hq", "rh_hogcall_load_f1_b@hr",
              "rh_hogcall_malloc_f1_b@hq", "rh_hogcall_malloc_f1_b@hr", "rh_hogcall_stream_f1_b@hq", "rh_hogcall_stream_f1_b@hr"):
        for t in by.get(c, []):
            out("  - %s: transparent %d, rec_init_r0 %d, copy timeouts r0/r1 %d/%d, probe 200ms r0/r1 %s/%s, hog started at "
                "probe r0/r1 %s/%s, fault after GIN launch %.1f ms, after filling launch %.1f ms, decline %s, stream copies r0 %s, "
                "n_wdany %d, copy-timeout errors in 120 its? tx_rc_it %s" % (
                    c, t["transparent_ok"], t["rec_init_r0"], t["n_copyto_r0"], t["n_copyto_r1"], t["probe_done_200ms_r0"],
                    t["probe_done_200ms_r1"], t["hog_started_probe_r0"], t["hog_started_probe_r1"], t["fault_after_launch_r0_ms"],
                    t["fault_after_launch_r0_ms"] - num(t["hog_launch_after_launch_ms_r0"]), t["declwhy_r0"],
                    t["td_stream_copies_r0"], t["n_wdany_r0"] + t["n_wdany_r1"], t["_kv"][0].get("tx_rc_it")))
            if t["build"] == "hr" or True:
                ek = t["_kv"][0]
                out("    tx_done %s tx_err_n %s hog_started_end r0/r1 %s/%s" % (ek.get("tx_done"), ek.get("tx_err_n"),
                                                                          t["hog_started_end_r0"], t["hog_started_end_r1"]))
    for c in ("rh_hog_f1_b@hq", "rh_hog_copystream_f1_b@hr", "rh_hogcall_load_f1_b@hq"):
        for t in by.get(c, []):
            msgs = log_msgs(read(os.path.join(PILOT, t["_folder"], t["_stem"] + "_r0.log")))[0]
            w = [float(re.search(r"mono_ms=([\d.]+)", m).group(1)) for m in msgs if R["wdany"].search(m)]
            ct = [float(re.search(r"mono_ms=([\d.]+)", m).group(1)) for m in msgs if R["copyto"].search(m)]
            out("  - %s: rank 0 copy timeout − the watchdog line %.1f ms" % (c, ct[0] - w[0]))
    for t in by.get("f1_b@hr", []):
        out("  - f1_b@hr: transparent %d, stats r0 %s/%s r1 %s/%s" % (t["transparent_ok"], t["rs_rounds_r0"], t["rs_recovered_r0"],
                                                                     t["rs_rounds_r1"], t["rs_recovered_r1"]))
    for t in by.get("f4_b@hr", []):
        out("  - f4_b@hr: decline − kill %.2f ms, devComm why %s, degraded lines %d" % (
            t["decl_after_kill_ms_r0"], t["uaerr_why_r0"], sum(1 for m in t["_L"][0]["uaword"] if m.group(2) == "degraded")))
    for c in ("lat_4k@hrp", "lat_4k@hqp"):
        for t in by.get(c, []):
            out("  - %s p50 %s" % (c, t["lat_p50_us"]))
    hr_logs = [(t, r) for t in tp if t["build"] == "hr" and t["kind"] in ("2", "4") for r in range(len(t["_L"]))]
    lbon = [m for t, r in hr_logs for m in t["_L"][r]["lbon"]]
    out("  - NIC path: hr contexts with a start line %d, on lines %d, off %d; gid %s; MRs per context two-rank %s four-rank %s; "
        "peermem %s; self-test bytes %s nonzero %s; setup %s ms; fallbacks %d; NIC timeouts %d; stream copies on nic ranks %s" % (
            sum(len(t["_L"][r]["hr"]) for t, r in hr_logs), len(lbon), sum(len(t["_L"][r]["lboff"]) for t, r in hr_logs),
            dict(Counter((m.group(4), m.group(5)) for m in lbon)),
            dict(Counter(m.group(6) for t, r in hr_logs if t["kind"] == "2" for m in t["_L"][r]["lbon"])),
            dict(Counter(m.group(6) for t, r in hr_logs if t["kind"] == "4" for m in t["_L"][r]["lbon"])),
            dict(Counter(m.group(8) for m in lbon)), dict(Counter(m.group(9) for m in lbon)),
            dict(Counter(m.group(10) for m in lbon)), rng([float(m.group(11)) for m in lbon]),
            sum(int(m.group(9)) for t, r in hr_logs for m in t["_L"][r]["td"]),
            sum(int(m.group(5)) for t, r in hr_logs for m in t["_L"][r]["td"]),
            rng([int(m.group(6)) for t, r in hr_logs for m in t["_L"][r]["td"] if m.group(2) == "nic"], "%d")))
    for c in ("mr4_cyc_stall@hr", "mr4_cyc_stall@hq", "mr4_chain_stall@hr", "rm4_kill3_untimed@hr", "rm4_kill3_untimed@hq",
              "mr4_kill3_peer@hr"):
        for t in by.get(c, []):
            out("  - %s: transparent %d, rec_i %s, n_decl %d, n_hs %d, hs_first %s, rec_last %s, spread %s, served %s (%d, rec %d), "
                "kept %s, nested ms %s, keptans %s, refq %s, wall %s" % (
                    c, t["transparent_ok"], t["rec_i"], t["n_decl"], t["n_hs"], t["hs_first_after_round_ms"],
                    t["rec_last_after_round_ms"], t["cyc_spread_ms"], t["served"], t["n_served"], t["n_served_rec"], t["kept"],
                    t["_served_ms"], t["_keptans"], dict(t["_refq"]), t["_meta"].get("wall_s")))
            if t.get("kill_rank") is not None:
                out("    decl−judged %s; degr−decl? sched %s; degr−judged %s; rel−judged %s; n_rel_dead %s n_rel_surv %s; "
                    "surv_tx_ok %s surv_rx_failed %s kdone %s stuck %s; rel its %s" % (
                        [round(t.get("decl_after_judged_ms_r%d" % r) or -1, 1) for r in range(3)],
                        [round(t.get("degr_after_sched_ms_r%d" % r) or -1, 1) for r in range(3)],
                        [round(t.get("degr_after_dead_ms_r%d" % r) or -1, 1) for r in range(3)],
                        [round(t.get("rel_after_dead_ms_r%d" % r) or -1, 1) for r in range(3)], t["n_rel_dead"],
                        t["n_rel_surv"], t["surv_tx_ok"], t["surv_rx_failed"], t["n_kdone_surv"], t["n_stuck_surv"],
                        sorted((k, v) for k, v in t["_rel_it"].items())))
    for t in by.get("hm_bench@hr", []):
        out("  - hm_bench: native %s/%s, dev %s host %s (rain), dev %s host %s (sunny), lost writes %s/%s of %s/%s, final low %s/%s" % (
            t["host_native_atomic_rain"], t["host_native_atomic_sunny"], t["lat_dev_atom_ns_rain"], t["lat_host_atom_ns_rain"],
            t["lat_dev_atom_ns_sunny"], t["lat_host_atom_ns_sunny"], t["race_lost_host_writes_rain"],
            t["race_lost_host_writes_sunny"], t["race_host_writes_rain"], t["race_host_writes_sunny"],
            t["race_final_low_rain"], t["race_final_low_sunny"]))
    tp2 = load_all(PILOT2)
    for t in tp2:
        out("  - P2 %s: results %s/%s, mr %s/%s, gid %s/%s, a_rounds %s/%s, b_rounds %s/%s, backouts %s/%s" % (
            t["key"], t["ng_result_rain"], t["ng_result_sunny"], t["ng_mr_rain"], t["ng_mr_sunny"], t["ng_gid_kind_rain"],
            t["ng_gid_kind_sunny"], t["_kv_rain"].get("a_rounds"), t["_kv_sunny"].get("a_rounds"),
            t["_kv_rain"].get("b_rounds"), t["_kv_sunny"].get("b_rounds"), t["ng_backouts_rain"], t["ng_backouts_sunny"]))
    h2 = read(os.path.join(PILOT2, "hold_P2.out")) or ""
    out("  - hold_P2.out 'result=' matches on the nic_gate line: %d" % sum(ln.count("result=") for ln in h2.splitlines()
                                                                         if ln.startswith("[nic_gate#")))
    for h, folder in (("P0", PILOT), ("P1", PILOT), ("P2", PILOT2)):
        x = read(os.path.join(folder, "hold_%s.out" % h)) or ""
        w = re.findall(r"(?m)^== (before|after)-(\w+) (\S+ \S+)", x)
        tl = re.findall(r"(?m)^(\S+ \S+) \[grm-%s\] (lock acquired|idle|command exited)" % h, x)
        out("  - %s: %s" % (h, ", ".join("%s %s" % (b, a[11:]) for a, b in tl)))
        nres = len([ln for ln in x.splitlines() if HB_END.match(ln) or H2_END.match(ln) or H4_END.match(ln)])
        vals = {key: re.findall(r"(?m)^%s: (\d+)$" % re.escape(key), x) for key in
                ("rain mlx5 cmd_err lines", "sunny mlx5 cmd_err lines", "rain fwcmd failed sum")}
        lefts = re.findall(r" left=(\d+) ", x)
        out("  - %s snapshots %s; trial result lines %d; left values %s; cmd_err rain %s sunny %s; fw failures %s; new mlx5 "
            "lines file %d B" % (h, [(a, c) for a, _, c in w], nres, dict(Counter(lefts)),
                                 "->".join(vals["rain mlx5 cmd_err lines"]), "->".join(vals["sunny mlx5 cmd_err lines"]),
                                 "->".join(vals["rain fwcmd failed sum"]),
                                 os.path.getsize(os.path.join(folder, "mlx5_new_%s.txt" % h))))
    ch = (read(os.path.join(PILOT, "chain.out")) or "") + (read(os.path.join(PILOT2, "chain.out")) or "")
    out("  - pilot chain.out: %s; iptables %s; STOP files %s" % (
        re.findall(r"hold (P\d) rc=(\d+)", ch), re.findall(r"before=(\d+) after=(\d+)", ch),
        [f for d in (PILOT, PILOT2) for f in os.listdir(d) if f.startswith("STOP")] or "none"))
    for t in by.get("mr4_kill3_peer@hr", []):
        kv = t["_kv"]
        out("  - P1 mr4_kill3_peer@hr survivor receive rcit %s, rc %s" % (
            sorted({kv[b].get("rx_%d%d_rcit" % (a, b)) for a in range(3) for b in range(3) if a != b}),
            sorted({kv[b].get("rx_%d%d_rc" % (a, b)) for a in range(3) for b in range(3) if a != b})))
    for t in by.get("rm4_kill3_untimed@hr", []):
        kv = t["_kv"]
        out("  - P1 rm4_kill3_untimed@hr rank 0 receive from rank 1: sig %s/%s, released at iteration %s" % (
            kv[0].get("rx_10_sig"), kv[0].get("rx_10_sigwant"), kv[0].get("rx_10_rel_it")))
        rel = {(a, b): num(kv[b].get("rx_%d%d_rel_mono_ms" % (a, b))) - t["dead_ms_r%d" % b]
               for b in range(3) for a in range(4) if a != b and kv[b].get("rx_%d%d_rel" % (a, b)) == "1"}
        out("  - P1 rm4_kill3_untimed@hr released receives − the receiver's judged-dead line: all %d %s ms; from rank 3 only "
            "%s ms; largest %s" % (len(rel), rng(rel.values()), rng([v for (a, b), v in rel.items() if a == 3]),
                                   max(rel.items(), key=lambda x: x[1])))
    for t in by.get("hm_bench@hr", []):
        out("  - P1 hm_bench wall_s %s" % t["_meta"].get("wall_s"))
    for t in tp:
        if t["kind"] == "2" and t["cell"].startswith("rh_"):
            out("  - P0 %s wall_s %s" % (t["key"], t["_meta"].get("wall_s")))


if __name__ == "__main__":
    sys.exit(main())
