#!/usr/bin/env python3
"""gin-pair-check: the columns of EXPERIMENT.md section 3.1 that ../scripts/ts2/rows.py and ../s2_close/rows_extra.py do
not produce, read from the per-trial files (<stem>_r0.log, <stem>_r1.log, <stem>_r0.kv, <stem>_r1.kv). score.py imports
extra_pc(). kv files are read as rows.py reads them (a value may hold blanks up to the next key).

Columns (definitions and log formats fixed in EXPERIMENT.md 3.1):
  pr_mode_r*, pc_mode_r*        "GIN/TS: pair reset=<0|1> rank=<r>", "GIN/TS: pair check=<0|1> rank=<r>"
  scope_r0, scope_reason_r0     rank 0's first scope-decision line
  n_dec_r*, last_reason_r*      number of decision lines and the reason of the last one, per rank
  rec_scope_r*, rec_qps_r*      each rank's first "GIN/TS: recovered" line (either role)
  n_rec_r*                      recovered lines per rank
  init_qps_r1                   qps of rank 1's first recovered line with role=initiator
  commit_us_r0, total_us_r0     rank 0's first recovered line with role=initiator
  n_checked_r*, check_us_r1     responder check lines ending "accepted"; check_us of rank 1's first
  n_refused_r*, refuse_reason_r1, not_rts_r1   responder check lines with "refused"; reason and not_rts of rank 1's first
  n_rerun_r0                    rank 0's "refused the scope of round ...; rerunning as a full reset" lines
  conflict_r1                   rank 1's "GIN/TS: rank=<r> scope conflict:" lines
  ep_c<c>_r<r>                  context c of rank r's "gate epochs to rank" line
  qpst_r*, n_notrts_r*          rank r's "qp states to rank" list and its entries other than 3 (RTS); empty if no line
  inj_ctx_r*                    context=<c> of the first "GIN/FAULT: GDAKI fault fired" line (empty: every context)
  r1_q4_in_stall                as ../pair_reset/rows_pr.py
  r1_fire_before_dec            rank 1's first hook fire, moved to rank 0's clock (minus clock_offset_ms of rank 0's kv),
                                before rank 0's first scope-decision line: 1, else 0; empty if either line is missing
  dual_r*                       kv dual of each rank
  dual_c1_in_win, dual_c1_max_in_win_us, dual_c1_end_after_win, dual_c1_done, dual_c1_rc   rank 0's kv keys
"""
import os, re

RE_MODE = re.compile(r"GIN/TS: pair reset=(\d) rank=")
RE_CHECK = re.compile(r"GIN/TS: pair check=(\d) rank=")
RE_DEC = re.compile(r"GIN/TS: rank \d+: round \d+ peer \d+ scope=(\S+) qps=(\d+) reason=(\w+) mono_ms=([\d.]+)")
RE_KV = re.compile(r"([\w/]+)=(\[[^\]]*\]|\S+)")
RE_RESP = re.compile(r"GIN/TS: rank \d+: REQ round \d+ from rank \d+ scope=\S+ checked=(\d+) not_rts=(\d+) check_us=([\d.]+) "
                     r"(accepted|refused)(?: reason=(\w+))?")
RE_RERUN = re.compile(r"GIN/TS: rank \d+: peer \d+ refused the scope of round \d+; rerunning as a full reset")
RE_EP = re.compile(r"GIN/TS: rank \d+ gate epochs to rank \d+: \[([^\]]*)\]")
RE_QPST = re.compile(r"GIN/TS: rank \d+ qp states to rank \d+: \[([^\]]*)\]")
RE_STALL = re.compile(r"GIN/TS: TEST stall rank=\d+ (\d+) ms after quiesce mono_ms=([\d.]+)")
RE_Q4 = re.compile(r"device-classified error CQE.*?\bmono_ms=([\d.]+)")
RE_FIRE = re.compile(r"GIN/FAULT: GDAKI fault fired.*?fire_mono_ms=([\d.]+)")
RE_CTX = re.compile(r"\bcontext=(\d+) ")
DUAL_KEYS = ["dual_c1_in_win", "dual_c1_max_in_win_us", "dual_c1_end_after_win", "dual_c1_done", "dual_c1_rc"]


def kvfile(path):  # as ../scripts/ts2/rows.py
    d = {}
    if os.path.exists(path):
        for line in open(path, errors="replace"):
            for m in re.finditer(r"(\w+)=(.*?)(?= \w+=|$)", line.rstrip("\n")):
                d[m.group(1)] = m.group(2).strip().strip('"')
    return d


def scan(path):
    o = {"mode": "", "check": "", "dec": [], "rec": [], "acc": [], "ref": [], "rerun": 0, "conflict": 0, "ep": None,
         "qpst": None, "inj_ctx": None, "fire": None, "stall": None, "q4": None}
    if not os.path.exists(path):
        return o
    for line in open(path, errors="replace"):
        m = RE_MODE.search(line)
        if m and o["mode"] == "":
            o["mode"] = m.group(1)
        m = RE_CHECK.search(line)
        if m and o["check"] == "":
            o["check"] = m.group(1)
        m = RE_DEC.search(line)
        if m:
            o["dec"].append((m.group(1), m.group(3), float(m.group(4))))
        if "GIN/TS: recovered" in line:
            o["rec"].append(dict(RE_KV.findall(line)))
        m = RE_RESP.search(line)
        if m:
            (o["acc"] if m.group(4) == "accepted" else o["ref"]).append(
                {"checked": m.group(1), "not_rts": m.group(2), "check_us": m.group(3), "reason": m.group(5) or ""})
        if RE_RERUN.search(line):
            o["rerun"] += 1
        if "scope conflict:" in line and "GIN/TS: rank=" in line:
            o["conflict"] += 1
        m = RE_EP.search(line)
        if m and o["ep"] is None:
            o["ep"] = [x.strip() for x in m.group(1).split(",")]
        m = RE_QPST.search(line)
        if m and o["qpst"] is None:
            o["qpst"] = [x.strip() for x in m.group(1).split(",")]
        if "GIN/FAULT: GDAKI fault fired" in line and o["inj_ctx"] is None:
            m = RE_CTX.search(line)
            o["inj_ctx"] = m.group(1) if m else ""
            m = RE_FIRE.search(line)
            o["fire"] = float(m.group(1)) if m else None
        m = RE_STALL.search(line)
        if m and o["stall"] is None:
            o["stall"] = (float(m.group(1)), float(m.group(2)))
        m = RE_Q4.search(line)
        if m and o["q4"] is None:
            o["q4"] = float(m.group(1))
    return o


def extra_pc(stem):
    l0, l1 = scan(stem + "_r0.log"), scan(stem + "_r1.log")
    k0, k1 = kvfile(stem + "_r0.kv"), kvfile(stem + "_r1.kv")
    off = k0.get("clock_offset_ms")
    d = {"scope_r0": l0["dec"][0][0] if l0["dec"] else "", "scope_reason_r0": l0["dec"][0][1] if l0["dec"] else "",
         "n_rerun_r0": l0["rerun"], "conflict_r1": l1["conflict"]}
    for r, l in ((0, l0), (1, l1)):
        d["pr_mode_r%d" % r] = l["mode"]
        d["pc_mode_r%d" % r] = l["check"]
        d["n_dec_r%d" % r] = len(l["dec"])
        d["last_reason_r%d" % r] = l["dec"][-1][1] if l["dec"] else ""
        first = l["rec"][0] if l["rec"] else {}
        d["rec_scope_r%d" % r] = first.get("scope", "")
        d["rec_qps_r%d" % r] = first.get("qps", "")
        d["n_rec_r%d" % r] = len(l["rec"])
        d["n_checked_r%d" % r] = len(l["acc"])
        d["n_refused_r%d" % r] = len(l["ref"])
        for c in range(4):
            d["ep_c%d_r%d" % (c, r)] = l["ep"][c] if l["ep"] and c < len(l["ep"]) else ""
        d["qpst_r%d" % r] = ",".join(l["qpst"]) if l["qpst"] is not None else ""
        d["n_notrts_r%d" % r] = sum(1 for x in l["qpst"] if x != "3") if l["qpst"] is not None else ""
        d["inj_ctx_r%d" % r] = l["inj_ctx"] if l["inj_ctx"] is not None else ""
    d["check_us_r1"] = l1["acc"][0]["check_us"] if l1["acc"] else ""
    d["refuse_reason_r1"] = l1["ref"][0]["reason"] if l1["ref"] else ""
    d["not_rts_r1"] = l1["ref"][0]["not_rts"] if l1["ref"] else ""
    init1 = [x for x in l1["rec"] if x.get("role") == "initiator"]
    d["init_qps_r1"] = init1[0].get("qps", "") if init1 else ""
    init0 = [x for x in l0["rec"] if x.get("role") == "initiator"]
    d["commit_us_r0"] = init0[0].get("commit_us", "") if init0 else ""
    d["total_us_r0"] = init0[0].get("total_us", "") if init0 else ""
    d["r1_q4_in_stall"] = ""
    if l0["stall"] is not None and l1["q4"] is not None and off not in (None, ""):
        ms, t = l0["stall"]
        x = l1["q4"] - float(off)
        d["r1_q4_in_stall"] = 1 if t <= x <= t + ms - 2 else 0
    d["r1_fire_before_dec"] = ""
    if l1["fire"] is not None and l0["dec"] and off not in (None, ""):
        d["r1_fire_before_dec"] = 1 if l1["fire"] - float(off) < l0["dec"][0][2] else 0
    d["dual_r0"], d["dual_r1"] = k0.get("dual", ""), k1.get("dual", "")
    for k in DUAL_KEYS:
        d[k] = k0.get(k, "")
    return d
