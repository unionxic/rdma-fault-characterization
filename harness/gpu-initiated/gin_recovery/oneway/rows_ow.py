#!/usr/bin/env python3
"""gin-oneway: the columns of EXPERIMENT.md section 3.1 that ../scripts/ts2/rows.py, ../s2_close/rows_extra.py and
../pair_check/rows_pc.py do not produce, read from the per-trial files (<stem>_r0.log, <stem>_r1.log, <stem>_r0.kv,
<stem>_kill.out). score.py imports extra_ow(). kv files are read as rows.py reads them (a value may hold blanks up to the
next key). All times are mono_ms (CLOCK_MONOTONIC, ms) of the rank whose log they come from, unless stated.

Columns (definitions and log formats fixed in EXPERIMENT.md 3.1; _r<r> = read from rank r's log):
  ow_mode_r*                     "GIN/TS: helper liveness oneway=<0|1> rank=<r>"
  knob_uto_r*, knob_refuse_r*    "GIN/TS: TEST socket knobs rank=<r> uto_ms=<x> refuse_hello=<n>"
  n_mute_on_r*, mute_off_ms_r*   TEST socket mute on lines; mono_ms of the first mute off line
  close1_cause_r*, close1_lv_r*, close1_ms_r*   first "socket to rank <p> closed cause=<C> mono_ms=<t> liveness=<L>"
  n_dead_r*, dead_cause_r*, dead_ms_r*          close lines with liveness=dead; cause and mono_ms of the first
  n_reconn_r*, reconn_ms_r*      "socket to rank <p> reconnected gen=<g> attempts=<n> mono_ms=<t>" lines; first mono_ms
  n_notacc_r0                    rank 0's "re-dial to rank <p> not accepted (...)" lines
  n_probe_ref_r1, n_probe_ans_r1 rank 1's "probe of rank <p> refused (ECONNREFUSED)" / "probe of rank <p> answered" lines
  n_refuse_test_r1               rank 1's "TEST refused a reconnect HELLO" lines
  wait_end_r*, wait_ms_r*        first "reconnect wait for rank <p> ended=<e> wait_ms=<x>"
  q4_ms_r*                       mono_ms of the first "device-classified error CQE" line (first classifier record)
  decl_ms_r*                     mono_ms of the first "GIN/TS: declined" line
  r0_killed                      1 if <stem>_kill.out holds kill_mono_ms and rank=0, else 0
  unmute_ms                      the latest mute-off time over the ranks that have one, on rank 0's clock (rank 1's
                                 time minus clock_offset_ms of rank 0's kv); empty if none
  reconn_after_unmute_ms_r*      reconn_ms_r* (rank 1: moved to rank 0's clock) - unmute_ms; empty if either is missing
  decl_after_q4_ms_r1            decl_ms_r1 - q4_ms_r1 (both rank 1's clock); empty if either is missing
"""
import os, re

RE_OWMODE = re.compile(r"GIN/TS: helper liveness oneway=(\d) rank=")
RE_KNOBS = re.compile(r"GIN/TS: TEST socket knobs rank=\d+ uto_ms=(\d+) refuse_hello=(\d+)")
RE_MUTE_ON = re.compile(r"GIN/TS: TEST socket mute on rank=\d+ peers=\d+ mono_ms=([\d.]+)")
RE_MUTE_OFF = re.compile(r"GIN/TS: TEST socket mute off rank=\d+ peers=\d+ mono_ms=([\d.]+)")
RE_CLOSE = re.compile(r"GIN/TS: rank \d+: socket to rank \d+ closed cause=(\S+) mono_ms=([\d.]+) liveness=(\w+)")
RE_RECONN = re.compile(r"GIN/TS: rank \d+: socket to rank \d+ reconnected gen=\d+ attempts=\d+ mono_ms=([\d.]+)")
RE_NOTACC = re.compile(r"GIN/TS: rank \d+: re-dial to rank \d+ not accepted \(")
RE_PROBE_REF = re.compile(r"GIN/TS: rank \d+: probe of rank \d+ refused \(ECONNREFUSED\) mono_ms=")
RE_PROBE_ANS = re.compile(r"GIN/TS: rank \d+: probe of rank \d+ answered mono_ms=")
RE_REFUSE_TEST = re.compile(r"GIN/TS: TEST refused a reconnect HELLO from rank \d+ gen=\d+ mono_ms=")
RE_WAIT = re.compile(r"GIN/TS: rank \d+: reconnect wait for rank \d+ ended=(\w+) wait_ms=([\d.]+) mono_ms=")
RE_Q4 = re.compile(r"device-classified error CQE.*?\bmono_ms=([\d.]+)")
RE_DECL = re.compile(r"GIN/TS: declined .*?mono_ms=([\d.]+)")


def kvfile(path):  # as ../scripts/ts2/rows.py
    d = {}
    if os.path.exists(path):
        for line in open(path, errors="replace"):
            for m in re.finditer(r"(\w+)=(.*?)(?= \w+=|$)", line.rstrip("\n")):
                d[m.group(1)] = m.group(2).strip().strip('"')
    return d


def scan(path):
    o = {"mode": "", "uto": "", "refuse": "", "mute_on": 0, "mute_off": None, "close": [], "reconn": [], "notacc": 0,
         "probe_ref": 0, "probe_ans": 0, "refuse_test": 0, "wait": None, "q4": None, "decl": None}
    if not os.path.exists(path):
        return o
    for line in open(path, errors="replace"):
        m = RE_OWMODE.search(line)
        if m and o["mode"] == "":
            o["mode"] = m.group(1)
        m = RE_KNOBS.search(line)
        if m and o["uto"] == "":
            o["uto"], o["refuse"] = m.group(1), m.group(2)
        if RE_MUTE_ON.search(line):
            o["mute_on"] += 1
        m = RE_MUTE_OFF.search(line)
        if m and o["mute_off"] is None:
            o["mute_off"] = float(m.group(1))
        m = RE_CLOSE.search(line)
        if m:
            o["close"].append((m.group(1), float(m.group(2)), m.group(3)))
        m = RE_RECONN.search(line)
        if m:
            o["reconn"].append(float(m.group(1)))
        if RE_NOTACC.search(line):
            o["notacc"] += 1
        if RE_PROBE_REF.search(line):
            o["probe_ref"] += 1
        if RE_PROBE_ANS.search(line):
            o["probe_ans"] += 1
        if RE_REFUSE_TEST.search(line):
            o["refuse_test"] += 1
        m = RE_WAIT.search(line)
        if m and o["wait"] is None:
            o["wait"] = (m.group(1), m.group(2))
        m = RE_Q4.search(line)
        if m and o["q4"] is None:
            o["q4"] = float(m.group(1))
        m = RE_DECL.search(line)
        if m and o["decl"] is None:
            o["decl"] = float(m.group(1))
    return o


def blank(x):
    return "" if x is None else x


def extra_ow(stem):
    l = {0: scan(stem + "_r0.log"), 1: scan(stem + "_r1.log")}
    k0 = kvfile(stem + "_r0.kv")
    kill = kvfile(stem + "_kill.out")
    try:
        off = float(k0.get("clock_offset_ms"))
    except (TypeError, ValueError):
        off = None
    d = {}
    for r in (0, 1):
        o = l[r]
        d["ow_mode_r%d" % r] = o["mode"]
        d["knob_uto_r%d" % r] = o["uto"]
        d["knob_refuse_r%d" % r] = o["refuse"]
        d["n_mute_on_r%d" % r] = o["mute_on"]
        d["mute_off_ms_r%d" % r] = blank(o["mute_off"])
        c1 = o["close"][0] if o["close"] else None
        d["close1_cause_r%d" % r] = c1[0] if c1 else ""
        d["close1_lv_r%d" % r] = c1[2] if c1 else ""
        d["close1_ms_r%d" % r] = c1[1] if c1 else ""
        dead = [c for c in o["close"] if c[2] == "dead"]
        d["n_dead_r%d" % r] = len(dead)
        d["dead_cause_r%d" % r] = dead[0][0] if dead else ""
        d["dead_ms_r%d" % r] = dead[0][1] if dead else ""
        d["n_reconn_r%d" % r] = len(o["reconn"])
        d["reconn_ms_r%d" % r] = o["reconn"][0] if o["reconn"] else ""
        d["wait_end_r%d" % r] = o["wait"][0] if o["wait"] else ""
        d["wait_ms_r%d" % r] = o["wait"][1] if o["wait"] else ""
        d["q4_ms_r%d" % r] = blank(o["q4"])
        d["decl_ms_r%d" % r] = blank(o["decl"])
    d["n_notacc_r0"] = l[0]["notacc"]
    d["n_probe_ref_r1"] = l[1]["probe_ref"]
    d["n_probe_ans_r1"] = l[1]["probe_ans"]
    d["n_refuse_test_r1"] = l[1]["refuse_test"]
    d["r0_killed"] = 1 if (kill.get("kill_mono_ms") and kill.get("rank") == "0") else 0
    offs = []
    if l[0]["mute_off"] is not None:
        offs.append(l[0]["mute_off"])
    if l[1]["mute_off"] is not None and off is not None:
        offs.append(l[1]["mute_off"] - off)
    unmute = max(offs) if offs else None
    d["unmute_ms"] = blank(unmute)
    rc0 = l[0]["reconn"][0] if l[0]["reconn"] else None
    rc1 = (l[1]["reconn"][0] - off) if (l[1]["reconn"] and off is not None) else None
    d["reconn_after_unmute_ms_r0"] = (rc0 - unmute) if (rc0 is not None and unmute is not None) else ""
    d["reconn_after_unmute_ms_r1"] = (rc1 - unmute) if (rc1 is not None and unmute is not None) else ""
    d["decl_after_q4_ms_r1"] = (l[1]["decl"] - l[1]["q4"]) if (l[1]["decl"] is not None and l[1]["q4"] is not None) else ""
    return d
