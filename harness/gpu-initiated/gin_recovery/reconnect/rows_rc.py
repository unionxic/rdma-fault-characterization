#!/usr/bin/env python3
"""gin-reconnect: the columns of EXPERIMENT.md section 3.1 that ../scripts/ts2/rows.py and ../s2_close/rows_extra.py do not
produce, read from the per-trial logs (<stem>_r0.log, <stem>_r1.log). score.py imports extra_rc().

Columns (definitions and log formats fixed in EXPERIMENT.md 3.1):
  rc_mode_r0, rc_mode_r1    reconnect=<0|1> of the first "GIN/TS: helper socket reconnect=<0|1> bound_ms=<b> rank=<r>" line
  sock_close_liveness_r0    liveness=<dead|unknown> of rank 0's first "... closed cause=<NAME> mono_ms=<t> liveness=<...>" line
  mute_off_ms_r0            mono_ms of rank 0's first "GIN/TS: TEST socket mute off rank=<r> peers=<n> mono_ms=<t>" line
  n_reconnect_r0, reconnect_ms_r0, n_reconnect_r1
                            "GIN/TS: rank <r>: socket to rank <p> reconnected gen=<g> attempts=<n> mono_ms=<t>" lines
                            (count and first mono_ms on rank 0; count on rank 1)
  rc_wait_end_r0, rc_wait_ms_r0
                            ended and wait_ms of rank 0's first
                            "GIN/TS: rank <r>: reconnect wait for rank <p> ended=<...> wait_ms=<x> mono_ms=<t>" line
  q4_mono_r0                mono_ms of rank 0's first "device-classified error CQE" line
"""
import os, re

RE_MODE = re.compile(r"GIN/TS: helper socket reconnect=(\d) bound_ms=(\d+) rank=")
RE_CLOSE = re.compile(r"GIN/TS: rank \d+: socket to rank \d+ closed cause=(\S+) mono_ms=([\d.]+) liveness=(\w+)")
RE_MUTE_OFF = re.compile(r"GIN/TS: TEST socket mute off rank=\d+ peers=\d+ mono_ms=([\d.]+)")
RE_RECON = re.compile(r"GIN/TS: rank \d+: socket to rank \d+ reconnected gen=\d+ attempts=\d+ mono_ms=([\d.]+)")
RE_WAIT = re.compile(r"GIN/TS: rank \d+: reconnect wait for rank \d+ ended=(\w+) wait_ms=([\d.]+)")
RE_Q4 = re.compile(r"device-classified error CQE.*?\bmono_ms=([\d.]+)")
RC_COLS = ["rc_mode_r0", "rc_mode_r1", "sock_close_liveness_r0", "mute_off_ms_r0", "n_reconnect_r0", "reconnect_ms_r0",
           "n_reconnect_r1", "rc_wait_end_r0", "rc_wait_ms_r0", "q4_mono_r0"]


def scan(path):
    o = {"mode": None, "close": [], "mute_off": [], "recon": [], "wait": [], "q4": []}
    if not os.path.exists(path):
        return o
    for line in open(path, errors="replace"):
        m = RE_MODE.search(line)
        if m and o["mode"] is None:
            o["mode"] = m.group(1)
        m = RE_CLOSE.search(line)
        if m:
            o["close"].append((m.group(1), float(m.group(2)), m.group(3)))
        m = RE_MUTE_OFF.search(line)
        if m:
            o["mute_off"].append(float(m.group(1)))
        m = RE_RECON.search(line)
        if m:
            o["recon"].append(float(m.group(1)))
        m = RE_WAIT.search(line)
        if m:
            o["wait"].append((m.group(1), float(m.group(2))))
        m = RE_Q4.search(line)
        if m:
            o["q4"].append(float(m.group(1)))
    return o


def extra_rc(stem):
    l0, l1 = scan(stem + "_r0.log"), scan(stem + "_r1.log")
    return {
        "rc_mode_r0": l0["mode"] if l0["mode"] is not None else "",
        "rc_mode_r1": l1["mode"] if l1["mode"] is not None else "",
        "sock_close_liveness_r0": l0["close"][0][2] if l0["close"] else "",
        "mute_off_ms_r0": l0["mute_off"][0] if l0["mute_off"] else "",
        "n_reconnect_r0": len(l0["recon"]),
        "reconnect_ms_r0": l0["recon"][0] if l0["recon"] else "",
        "n_reconnect_r1": len(l1["recon"]),
        "rc_wait_end_r0": l0["wait"][0][0] if l0["wait"] else "",
        "rc_wait_ms_r0": l0["wait"][0][1] if l0["wait"] else "",
        "q4_mono_r0": l0["q4"][0] if l0["q4"] else "",
    }
