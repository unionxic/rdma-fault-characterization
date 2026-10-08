#!/usr/bin/env python3
"""gin-handoff: the columns of EXPERIMENT.md section 3.1 that ../scripts/ts2/rows.py, ../s2_close/rows_extra.py,
../pair_check/rows_pc.py, ../oneway/rows_ow.py and ../harden/rows_hd.py do not produce, read from the per-trial files
(<stem>_r0.log, <stem>_r1.log, <stem>_r0.kv, <stem>_r1.kv). score.py imports extra_hf(). kv files are read as rows.py
reads them. Times are mono_ms (CLOCK_MONOTONIC, ms) of the rank whose file they come from.

Columns (_r<r>: from rank r's log or kv):
  hf_on_r*, hf_switch_r*     "GIN/TS: handoff=1 rank=<r> shrink_handoff=<0|1>": 1 if present (0 without it); its value
  n_hoff_ok_r0, hoff_ranks_r0, hoff_ok_ms_r0
                             "GIN/TS: rank 0: aborting shrink proceeds past the parent's GIN error, raised for rank(s)
                             <list>, all excluded mono_ms=<t>": lines; <list> and <t> of the first
  n_hoff_keep_r0, hoff_why_r0
                             "GIN/TS: rank 0: aborting shrink keeps the parent's error (<why>) mono_ms=<t>": lines; <why>
                             of the first
  n_surface_r*               "GIN/TS: watchdog rank=<r>: <why>; the fault surfaces" lines (a GIN error raised without a peer)
  surface_why_r*             <why> of the first such line
  n_late_copy_r*             "the late device-state copy completed" lines
  ho_parent_async_after, ho_newcomm_async, ho_newcomm_destroy_rc, ho_check_ms, ho_allreduce_done, ho_allreduce_rc
                             rank 0 kv (GIN_TS_SHRINK)
  hog_slack_r*, hog_started_probe_r*, probe_n_r*, probe_done_200ms_r*, probe_stuck_r*, probe_max_ms_r*,
  probe_after_hog_ms_r*, hog_started_end_r*, hog_start_spread_ms_r*, probe_done_end_r*, hog_running_at_end_r*
                             kv of the GPU-filling kernel and the copy probe (GIN_TS_HOG_MS, GIN_TS_HOG_SLACK,
                             GIN_TS_HOG_PROBE); probe_stuck is "none" or the comma-separated indices still running
"""
import os, re

RE_HF = re.compile(r"GIN/TS: handoff=1 rank=\d+ shrink_handoff=(\d)")
RE_HOFF_OK = re.compile(r"GIN/TS: rank \d+: aborting shrink proceeds past the parent's GIN error, raised for rank\(s\) "
                        r"(\S+), all excluded mono_ms=([\d.]+)")
RE_HOFF_KEEP = re.compile(r"GIN/TS: rank \d+: aborting shrink keeps the parent's error \((.*)\) mono_ms=([\d.]+)")
RE_SURFACE = re.compile(r"GIN/TS: watchdog rank=\d+: (.*?); the fault surfaces")
RE_LATE = re.compile(r"the late device-state copy completed")
HO_KEYS = ["ho_parent_async_after", "ho_newcomm_async", "ho_newcomm_destroy_rc", "ho_check_ms", "ho_allreduce_done",
           "ho_allreduce_rc"]
HOG_KEYS = ["hog_slack", "hog_started_probe", "probe_n", "probe_done_200ms", "probe_stuck", "probe_max_ms",
            "probe_after_hog_ms", "hog_started_end", "hog_start_spread_ms", "probe_done_end", "hog_running_at_end"]


def kvfile(path):  # as ../scripts/ts2/rows.py
    d = {}
    if os.path.exists(path):
        for line in open(path, errors="replace"):
            for m in re.finditer(r"(\w+)=(.*?)(?= \w+=|$)", line.rstrip("\n")):
                d[m.group(1)] = m.group(2).strip().strip('"')
    return d


def scan(path):
    o = {"hf": None, "ok": [], "keep": [], "surface": [], "late": 0}
    if not os.path.exists(path):
        return o
    for line in open(path, errors="replace"):
        m = RE_HF.search(line)
        if m and o["hf"] is None:
            o["hf"] = m.group(1)
        m = RE_HOFF_OK.search(line)
        if m:
            o["ok"].append((m.group(1), float(m.group(2))))
        m = RE_HOFF_KEEP.search(line)
        if m:
            o["keep"].append(m.group(1))
        m = RE_SURFACE.search(line)
        if m:
            o["surface"].append(m.group(1))
        if RE_LATE.search(line):
            o["late"] += 1
    return o


def extra_hf(stem):
    """stem: path prefix of the trial's files."""
    l = {0: scan(stem + "_r0.log"), 1: scan(stem + "_r1.log")}
    k = {0: kvfile(stem + "_r0.kv"), 1: kvfile(stem + "_r1.kv")}
    d = {}
    for r in (0, 1):
        o = l[r]
        d["hf_on_r%d" % r] = 1 if o["hf"] is not None else 0
        d["hf_switch_r%d" % r] = "" if o["hf"] is None else o["hf"]
        d["n_surface_r%d" % r] = len(o["surface"])
        d["surface_why_r%d" % r] = o["surface"][0] if o["surface"] else ""
        d["n_late_copy_r%d" % r] = o["late"]
        for key in HOG_KEYS:
            d["%s_r%d" % (key, r)] = k[r].get(key, "")
    d["n_hoff_ok_r0"] = len(l[0]["ok"])
    d["hoff_ranks_r0"] = l[0]["ok"][0][0] if l[0]["ok"] else ""
    d["hoff_ok_ms_r0"] = l[0]["ok"][0][1] if l[0]["ok"] else ""
    d["n_hoff_keep_r0"] = len(l[0]["keep"])
    d["hoff_why_r0"] = l[0]["keep"][0] if l[0]["keep"] else ""
    for key in HO_KEYS:
        d[key] = k[0].get(key, "")
    return d
