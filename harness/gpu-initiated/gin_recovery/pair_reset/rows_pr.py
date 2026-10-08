#!/usr/bin/env python3
"""gin-pair-reset: the columns of EXPERIMENT.md section 3.1 that ../scripts/ts2/rows.py and ../s2_close/rows_extra.py do
not produce, read from the per-trial files (<stem>_r0.log, <stem>_r1.log, <stem>_r0.kv, <stem>_r1.kv). score.py imports
extra_pr().

Columns (definitions and log formats fixed in EXPERIMENT.md 3.1):
  pr_mode_r0, pr_mode_r1      "GIN/TS: pair reset=<0|1> rank=<r>"
  scope_r0, scope_reason_r0   rank 0's first "GIN/TS: rank <r>: round <n> peer <p> scope=<0x..> qps=<k> reason=<w> mono_ms=<t>"
  rec_scope_r*, rec_qps_r*    each rank's first "GIN/TS: recovered" line (either role): scope, qps
  n_rec_r0, n_rec_r1          recovered lines per rank
  init_qps_r1                 qps of rank 1's first recovered line with role=initiator
  commit_us_r0, total_us_r0   rank 0's first recovered line with role=initiator
  conflict_r1                 rank 1's "GIN/TS: rank=<r> scope conflict:" lines
  ep_c<c>_r<r>                context c of rank r's "GIN/TS: rank <r> gate epochs to rank <p>: [<e0>,<e1>,...]"
  inj_ctx_r0, inj_ctx_r1      context=<c> of the first "GIN/FAULT: GDAKI fault fired" line (empty: every context)
  r1_q4_in_stall              rank 1's first device-classified record, moved to rank 0's clock (minus clock_offset_ms of
                              rank 0's kv), inside [t, t + ms - 2] of rank 0's "GIN/TS: TEST stall rank=0 <ms> ms after
                              quiesce mono_ms=<t>": 1, else 0; empty if either line is missing
  dual_r0, dual_r1            kv dual of each rank
  dual_win_us, dual_c1_in_win, dual_c1_max_in_win_us, dual_c1_end_after_win, dual_c1_max_us   rank 0's kv keys
"""
import os, re

RE_MODE = re.compile(r"GIN/TS: pair reset=(\d) rank=")
RE_DEC = re.compile(r"GIN/TS: rank \d+: round \d+ peer \d+ scope=(\S+) qps=(\d+) reason=(\w+) mono_ms=")
RE_KV = re.compile(r"([\w/]+)=(\[[^\]]*\]|\S+)")
RE_EP = re.compile(r"GIN/TS: rank \d+ gate epochs to rank \d+: \[([^\]]*)\]")
RE_STALL = re.compile(r"GIN/TS: TEST stall rank=\d+ (\d+) ms after quiesce mono_ms=([\d.]+)")
RE_Q4 = re.compile(r"device-classified error CQE.*?\bmono_ms=([\d.]+)")
RE_CTX = re.compile(r"\bcontext=(\d+) ")
DUAL_KEYS = ["dual_win_us", "dual_c1_in_win", "dual_c1_max_in_win_us", "dual_c1_end_after_win", "dual_c1_max_us"]
PR_COLS = (["pr_mode_r0", "pr_mode_r1", "scope_r0", "scope_reason_r0", "rec_scope_r0", "rec_qps_r0", "rec_scope_r1",
            "rec_qps_r1", "n_rec_r0", "n_rec_r1", "init_qps_r1", "commit_us_r0", "total_us_r0", "conflict_r1"]
           + ["ep_c%d_r%d" % (c, r) for r in (0, 1) for c in range(4)]
           + ["inj_ctx_r0", "inj_ctx_r1", "r1_q4_in_stall", "dual_r0", "dual_r1"] + DUAL_KEYS)


def kvfile(path):
    d = {}
    if os.path.exists(path):
        for line in open(path, errors="replace"):
            for k, v in re.findall(r"(\w+)=(\S+)", line):
                d[k] = v
    return d


def scan(path):
    o = {"mode": "", "dec": None, "rec": [], "conflict": 0, "ep": None, "inj_ctx": None, "stall": None, "q4": None}
    if not os.path.exists(path):
        return o
    for line in open(path, errors="replace"):
        m = RE_MODE.search(line)
        if m and o["mode"] == "":
            o["mode"] = m.group(1)
        m = RE_DEC.search(line)
        if m and o["dec"] is None:
            o["dec"] = (m.group(1), m.group(2), m.group(3))
        if "GIN/TS: recovered" in line:
            o["rec"].append(dict(RE_KV.findall(line)))
        if "scope conflict:" in line and "GIN/TS: rank=" in line:
            o["conflict"] += 1
        m = RE_EP.search(line)
        if m and o["ep"] is None:
            o["ep"] = [x.strip() for x in m.group(1).split(",")]
        if "GIN/FAULT: GDAKI fault fired" in line and o["inj_ctx"] is None:
            m = RE_CTX.search(line)
            o["inj_ctx"] = m.group(1) if m else ""
        m = RE_STALL.search(line)
        if m and o["stall"] is None:
            o["stall"] = (float(m.group(1)), float(m.group(2)))
        m = RE_Q4.search(line)
        if m and o["q4"] is None:
            o["q4"] = float(m.group(1))
    return o


def extra_pr(stem):
    l0, l1 = scan(stem + "_r0.log"), scan(stem + "_r1.log")
    k0, k1 = kvfile(stem + "_r0.kv"), kvfile(stem + "_r1.kv")
    d = {"pr_mode_r0": l0["mode"], "pr_mode_r1": l1["mode"],
         "scope_r0": l0["dec"][0] if l0["dec"] else "", "scope_reason_r0": l0["dec"][2] if l0["dec"] else "",
         "n_rec_r0": len(l0["rec"]), "n_rec_r1": len(l1["rec"]), "conflict_r1": l1["conflict"]}
    for r, l in ((0, l0), (1, l1)):
        first = l["rec"][0] if l["rec"] else {}
        d["rec_scope_r%d" % r] = first.get("scope", "")
        d["rec_qps_r%d" % r] = first.get("qps", "")
        for c in range(4):
            d["ep_c%d_r%d" % (c, r)] = l["ep"][c] if l["ep"] and c < len(l["ep"]) else ""
        d["inj_ctx_r%d" % r] = l["inj_ctx"] if l["inj_ctx"] is not None else ""
    init1 = [x for x in l1["rec"] if x.get("role") == "initiator"]
    d["init_qps_r1"] = init1[0].get("qps", "") if init1 else ""
    init0 = [x for x in l0["rec"] if x.get("role") == "initiator"]
    d["commit_us_r0"] = init0[0].get("commit_us", "") if init0 else ""
    d["total_us_r0"] = init0[0].get("total_us", "") if init0 else ""
    d["r1_q4_in_stall"] = ""
    if l0["stall"] is not None and l1["q4"] is not None and "clock_offset_ms" in k0:
        ms, t = l0["stall"]
        x = l1["q4"] - float(k0["clock_offset_ms"])
        d["r1_q4_in_stall"] = 1 if t <= x <= t + ms - 2 else 0
    d["dual_r0"], d["dual_r1"] = k0.get("dual", ""), k1.get("dual", "")
    for k in DUAL_KEYS:
        d[k] = k0.get(k, "")
    return d
