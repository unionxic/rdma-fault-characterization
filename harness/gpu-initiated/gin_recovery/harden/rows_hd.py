#!/usr/bin/env python3
"""gin-harden: the columns of EXPERIMENT.md section 3.1 that ../scripts/ts2/rows.py, ../s2_close/rows_extra.py,
../pair_check/rows_pc.py and ../oneway/rows_ow.py do not produce, read from the per-trial files (<stem>_r0.log,
<stem>_r1.log, <stem>_r0.kv, <stem>_r1.kv, <stem>_kill.out, <stem>_mute.out, <stem>_meta.txt). score.py imports
extra_hd(). kv files are read as rows.py reads them (a value may hold blanks up to the next key). Times are mono_ms
(CLOCK_MONOTONIC, ms) of the rank whose file they come from unless a column says "rank 0 clock" or "rank 1 clock";
clock_offset_ms of rank 0's kv is (rank 1 clock - rank 0 clock).

Columns (_r<r>: from rank r's log or kv):
  hd_on_r*, prod_r*          "GIN/TS: harden=1 rank=<r> nonce=.. ... production=<0|1>": 1 if present; its production value
  hk_gap_r*, hk_badnonce_r*, hk_fwdelay_r*, hk_copystall_r*, hk_badrepost_r*
                             "GIN/TS: TEST harden knobs rank=<r> listen_gap=<a>:<b> bad_nonce=<n> fw_delay=<ms>@<ph>
                             copy_stall=<ms> bad_repost=<k>" values (empty without the line)
  n_judged_r*, judged_cause_r*, judged_ms_r*   "GIN/TS: rank <r>: rank <p> judged dead (cause=<C>) mono_ms=<t>"
  n_left_r*                  "GIN/TS: rank <r>: rank <p> left the communicator (BYE)" lines
  n_refused_dial_r*, refusal1_ms_r*            "GIN/TS: rank <r>: re-dial to rank <p> refused (ECONNREFUSED) mono_ms=<t>
                             refusal=<n>" lines and the first mono_ms
  n_probe_refused_r*, probe_refusal1_ms_r*     the same for "probe of rank <p> refused (ECONNREFUSED) mono_ms=<t>"
  refusal_span_ms_r*         judged_ms - the first refusal (re-dial or probe) of the same rank; empty if either is missing
  n_nonce_ref_r*             "GIN/TS: rank <r>: refused a reconnect from rank <p> (nonce mismatch)" lines
  n_badnonce_sent_r*         "GIN/TS: TEST sent a wrong nonce in" lines
  n_probe_noans_r*           "probe of rank <p> not answered by the peer" lines
  n_cancel_r*                "round <n> with rank <p> cancelled" (initiator) + "round <n> from rank <p> cancelled" (responder)
  sock_retries_max_r*        largest sock_retries= of the rank's "GIN/TS: recovered" lines (initiator); empty if none
  rec_total_us_r*            total_us of the rank's first "GIN/TS: recovered ... role=initiator" line
  n_fwdog_r*, fwdog_run_ms_r*, fwdog_ms_r*     "GIN/TS: watchdog rank=<r>: firmware command phase <ph> has run <x> ms";
                             x and the mono_ms of the first such line
  n_uarel_r*, uarel_why_r*, uarel_ms_r*        "GIN/TS: user devComm waits released rank=<r> why=<w> mono_ms=<t>" (first)
  n_copyto_r*                "device-state copy (...) not complete after" lines
  n_esc_r*                   "GIN/TS: escalated rank=" lines
  n_plan_rej_r*, plan_rej_qp_r*, plan_rej_total_r*   "re-post plan to rank <p> rejected at qp <i> of <n>" (first)
  n_orphan_r*                "the recovery helper did not stop within" lines
  n_dump_r*                  "device wait-timeout dump" lines
  gap_on_ms_r1, gap_off_ms_r1, gap_listening_r1   "GIN/TS: TEST listen gap on/off rank=1 ... listening=<0|1>"
  rs_*_r*                    kv rs_api, rs_rounds, rs_recovered, rs_declined, rs_reconnects, rs_deaths, rs_escalations,
                             rs_cancelled, rs_fw_overruns, rs_copy_timeouts, rs_contexts
  rx_phantom_r*, post_abort_rx_phantom_r*, post_abort_rx_rc_r*, post_abort_read_r*   kv
  ho_*                       rank 0 kv: ho_kernel_done_before_shrink, ho_shrink_rc, ho_shrink_ms, ho_newcomm,
                             ho_newcomm_nranks, ho_check_ok, ho_allreduce_rc, ho_old_kernel_done
  hog_blocks_r*, hog_sms_r*, hog_launch_err_r*, hog_launch_after_launch_ms_r*   kv
  fault_after_launch_r0_ms   rank 0's first hook fire (fire_mono_ms) - its kv launch_mono_ms
  q4_after_fault_ms_r0       rank 0's first classifier record - the fault instant on rank 0's clock (rows.py
                             fault_mono_r0: the first hook fire of either rank, moved to rank 0's clock)
  decl_after_q4_ms_r0        rank 0's first decline - its first classifier record (both rank 0 clock)
  kill_r1clock_ms            rank 0 kill (KILL_R0, kill.out rank=0, rank 0 clock) moved to rank 1's clock
  release_after_kill_ms_r1   rank 1's kernel end (kv launch_mono_ms + kernel_ms) - kill_r1clock_ms
  async_after_kill_ms_r1     rank 1's first async error (launch_mono_ms + async_first_ms_after_launch) - kill_r1clock_ms
  decl_after_kill_ms_r0      rank 1 kill (F4, kill.out without rank=0, rank 1 clock) moved to rank 0's clock; rank 0's first
                             decline minus it
  r1close_after_q4_ms        rank 1's first socket close (rank 1 clock, moved to rank 0's clock) - rank 0's first
                             classifier record
  mute_applied, mute_on_ms, mute_rules_on, mute_rules_left, mute_skipped   <stem>_mute.out (production mute cell)
  left_rules                 meta left_rules (gin-harden iptables rules left after the trial)
"""
import os, re

RE_HD = re.compile(r"GIN/TS: harden=1 rank=\d+ .*?production=(\d)")
RE_HK = re.compile(r"GIN/TS: TEST harden knobs rank=\d+ listen_gap=(-?\d+:\d+) bad_nonce=(\d+) fw_delay=(\d+@\S+) "
                   r"copy_stall=(\d+) bad_repost=(-?\d+)")
RE_JUDGED = re.compile(r"GIN/TS: rank \d+: rank \d+ judged dead \(cause=(\S+)\) mono_ms=([\d.]+)")
RE_LEFT = re.compile(r"GIN/TS: rank \d+: rank \d+ left the communicator \(BYE\)")
RE_DIALREF = re.compile(r"GIN/TS: rank \d+: re-dial to rank \d+ refused \(ECONNREFUSED\) mono_ms=([\d.]+)")
RE_PROBEREF = re.compile(r"GIN/TS: rank \d+: probe of rank \d+ refused \(ECONNREFUSED\) mono_ms=([\d.]+)")
RE_NONCEREF = re.compile(r"GIN/TS: rank \d+: refused a reconnect from rank \d+ \(nonce mismatch\)")
RE_BADNONCE = re.compile(r"GIN/TS: TEST sent a wrong nonce in")
RE_NOANS = re.compile(r"GIN/TS: rank \d+: probe of rank \d+ not answered by the peer")
RE_CANCEL = re.compile(r"GIN/TS: rank \d+: round \d+ (?:with|from) rank \d+ cancelled")
RE_REC = re.compile(r"GIN/TS: recovered ")
RE_KV = re.compile(r"([\w/]+)=(\[[^\]]*\]|\S+)")
RE_FWDOG = re.compile(r"GIN/TS: watchdog rank=\d+: firmware command phase \S+ has run ([\d.]+) ms.*?mono_ms=([\d.]+)")
RE_UAREL = re.compile(r"GIN/TS: user devComm waits released rank=\d+ why=(\S+) mono_ms=([\d.]+)")
RE_COPYTO = re.compile(r"device-state copy \(.*\) not complete after")
RE_ESC = re.compile(r"GIN/TS: escalated rank=")
RE_PLANREJ = re.compile(r"re-post plan to rank \d+ rejected at qp (-?\d+) of (\d+)")
RE_ORPHAN = re.compile(r"the recovery helper did not stop within")
RE_DUMP = re.compile(r"device wait-timeout dump")
RE_GAPON = re.compile(r"GIN/TS: TEST listen gap on rank=\d+ .*?mono_ms=([\d.]+)")
RE_GAPOFF = re.compile(r"GIN/TS: TEST listen gap off rank=\d+ listening=(\d) errno=\d+ mono_ms=([\d.]+)")
RE_CLOSE = re.compile(r"GIN/TS: rank \d+: socket to rank \d+ closed cause=(\S+) mono_ms=([\d.]+) liveness=(\w+)")
RE_Q4 = re.compile(r"device-classified error CQE.*?\bmono_ms=([\d.]+)")
RE_DECL = re.compile(r"GIN/TS: declined .*?mono_ms=([\d.]+)")
RE_FIRE = re.compile(r"GIN/FAULT: GDAKI fault fired.*?fire_mono_ms=([\d.]+)")
RS_KEYS = ["rs_api", "rs_rounds", "rs_recovered", "rs_declined", "rs_reconnects", "rs_deaths", "rs_escalations",
           "rs_cancelled", "rs_fw_overruns", "rs_copy_timeouts", "rs_contexts"]
HO_KEYS = ["ho_kernel_done_before_shrink", "ho_shrink_rc", "ho_shrink_ms", "ho_newcomm", "ho_newcomm_nranks",
           "ho_check_ok", "ho_allreduce_rc", "ho_old_kernel_done"]


def kvfile(path):  # as ../scripts/ts2/rows.py
    d = {}
    if os.path.exists(path):
        for line in open(path, errors="replace"):
            for m in re.finditer(r"(\w+)=(.*?)(?= \w+=|$)", line.rstrip("\n")):
                d[m.group(1)] = m.group(2).strip().strip('"')
    return d


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def scan(path):
    o = {"hd": None, "hk": None, "judged": [], "left": 0, "dialref": [], "proberef": [], "nonceref": 0, "badnonce": 0,
         "noans": 0, "cancel": 0, "rec": [], "fwdog": [], "uarel": [], "copyto": 0, "esc": 0, "planrej": [], "orphan": 0,
         "dump": 0, "gapon": None, "gapoff": None, "close": [], "q4": None, "decl": None, "fire": None}
    if not os.path.exists(path):
        return o
    for line in open(path, errors="replace"):
        m = RE_HD.search(line)
        if m and o["hd"] is None:
            o["hd"] = m.group(1)
        m = RE_HK.search(line)
        if m and o["hk"] is None:
            o["hk"] = m.groups()
        m = RE_JUDGED.search(line)
        if m:
            o["judged"].append((m.group(1), float(m.group(2))))
        if RE_LEFT.search(line):
            o["left"] += 1
        m = RE_DIALREF.search(line)
        if m:
            o["dialref"].append(float(m.group(1)))
        m = RE_PROBEREF.search(line)
        if m:
            o["proberef"].append(float(m.group(1)))
        if RE_NONCEREF.search(line):
            o["nonceref"] += 1
        if RE_BADNONCE.search(line):
            o["badnonce"] += 1
        if RE_NOANS.search(line):
            o["noans"] += 1
        if RE_CANCEL.search(line):
            o["cancel"] += 1
        if RE_REC.search(line):
            o["rec"].append(dict(RE_KV.findall(line)))
        m = RE_FWDOG.search(line)
        if m:
            o["fwdog"].append((float(m.group(1)), float(m.group(2))))
        m = RE_UAREL.search(line)
        if m:
            o["uarel"].append((m.group(1), float(m.group(2))))
        if RE_COPYTO.search(line):
            o["copyto"] += 1
        if RE_ESC.search(line):
            o["esc"] += 1
        m = RE_PLANREJ.search(line)
        if m:
            o["planrej"].append((m.group(1), m.group(2)))
        if RE_ORPHAN.search(line):
            o["orphan"] += 1
        if RE_DUMP.search(line):
            o["dump"] += 1
        m = RE_GAPON.search(line)
        if m and o["gapon"] is None:
            o["gapon"] = float(m.group(1))
        m = RE_GAPOFF.search(line)
        if m and o["gapoff"] is None:
            o["gapoff"] = (m.group(1), float(m.group(2)))
        m = RE_CLOSE.search(line)
        if m:
            o["close"].append((m.group(1), float(m.group(2)), m.group(3)))
        m = RE_Q4.search(line)
        if m and o["q4"] is None:
            o["q4"] = float(m.group(1))
        m = RE_DECL.search(line)
        if m and o["decl"] is None:
            o["decl"] = float(m.group(1))
        m = RE_FIRE.search(line)
        if m and o["fire"] is None:
            o["fire"] = float(m.group(1))
    return o


def blank(x):
    return "" if x is None else x


def extra_hd(stem, fault_mono_r0=None):
    """stem: path prefix of the trial's files; fault_mono_r0: rows.py's fault_mono_r0 (string or number) or None."""
    l = {0: scan(stem + "_r0.log"), 1: scan(stem + "_r1.log")}
    k = {0: kvfile(stem + "_r0.kv"), 1: kvfile(stem + "_r1.kv")}
    kill = kvfile(stem + "_kill.out")
    mute = kvfile(stem + "_mute.out")
    meta = kvfile(stem + "_meta.txt")
    off = fnum(k[0].get("clock_offset_ms"))  # rank 1 clock - rank 0 clock
    d = {}
    for r in (0, 1):
        o = l[r]
        d["hd_on_r%d" % r] = 1 if o["hd"] is not None else 0
        d["prod_r%d" % r] = blank(o["hd"])
        hk = o["hk"]
        d["hk_gap_r%d" % r] = hk[0] if hk else ""
        d["hk_badnonce_r%d" % r] = hk[1] if hk else ""
        d["hk_fwdelay_r%d" % r] = hk[2] if hk else ""
        d["hk_copystall_r%d" % r] = hk[3] if hk else ""
        d["hk_badrepost_r%d" % r] = hk[4] if hk else ""
        d["n_judged_r%d" % r] = len(o["judged"])
        d["judged_cause_r%d" % r] = o["judged"][0][0] if o["judged"] else ""
        d["judged_ms_r%d" % r] = o["judged"][0][1] if o["judged"] else ""
        d["n_left_r%d" % r] = o["left"]
        d["n_refused_dial_r%d" % r] = len(o["dialref"])
        d["refusal1_ms_r%d" % r] = o["dialref"][0] if o["dialref"] else ""
        d["n_probe_refused_r%d" % r] = len(o["proberef"])
        d["probe_refusal1_ms_r%d" % r] = o["proberef"][0] if o["proberef"] else ""
        firsts = [x for x in (o["dialref"][:1] + o["proberef"][:1])]
        d["refusal_span_ms_r%d" % r] = (o["judged"][0][1] - min(firsts)) if (o["judged"] and firsts) else ""
        d["n_nonce_ref_r%d" % r] = o["nonceref"]
        d["n_badnonce_sent_r%d" % r] = o["badnonce"]
        d["n_probe_noans_r%d" % r] = o["noans"]
        d["n_cancel_r%d" % r] = o["cancel"]
        init = [x for x in o["rec"] if x.get("role") == "initiator"]
        sr = [fnum(x.get("sock_retries")) for x in init if fnum(x.get("sock_retries")) is not None]
        d["sock_retries_max_r%d" % r] = max(sr) if sr else ""
        d["rec_total_us_r%d" % r] = init[0].get("total_us", "") if init else ""
        d["n_fwdog_r%d" % r] = len(o["fwdog"])
        d["fwdog_run_ms_r%d" % r] = o["fwdog"][0][0] if o["fwdog"] else ""
        d["fwdog_ms_r%d" % r] = o["fwdog"][0][1] if o["fwdog"] else ""
        d["n_uarel_r%d" % r] = len(o["uarel"])
        d["uarel_why_r%d" % r] = o["uarel"][0][0] if o["uarel"] else ""
        d["uarel_ms_r%d" % r] = o["uarel"][0][1] if o["uarel"] else ""
        d["n_copyto_r%d" % r] = o["copyto"]
        d["n_esc_r%d" % r] = o["esc"]
        d["n_plan_rej_r%d" % r] = len(o["planrej"])
        d["plan_rej_qp_r%d" % r] = o["planrej"][0][0] if o["planrej"] else ""
        d["plan_rej_total_r%d" % r] = o["planrej"][0][1] if o["planrej"] else ""
        d["n_orphan_r%d" % r] = o["orphan"]
        d["n_dump_r%d" % r] = o["dump"]
        for key in RS_KEYS:
            d["%s_r%d" % (key, r)] = k[r].get(key, "")
        d["rx_phantom_r%d" % r] = k[r].get("rx_phantom", "")
        d["post_abort_rx_phantom_r%d" % r] = k[r].get("post_abort_rx_phantom", "")
        d["post_abort_rx_rc_r%d" % r] = k[r].get("post_abort_rx_rc", "")
        d["post_abort_read_r%d" % r] = k[r].get("post_abort_read", "")
        d["hog_blocks_r%d" % r] = k[r].get("hog_blocks", "")
        d["hog_sms_r%d" % r] = k[r].get("hog_sms", "")
        d["hog_launch_err_r%d" % r] = k[r].get("hog_launch_err", "")
        d["hog_launch_after_launch_ms_r%d" % r] = k[r].get("hog_launch_after_launch_ms", "")
    for key in HO_KEYS:
        d[key] = k[0].get(key, "")
    d["gap_on_ms_r1"] = blank(l[1]["gapon"])
    d["gap_off_ms_r1"] = l[1]["gapoff"][1] if l[1]["gapoff"] else ""
    d["gap_listening_r1"] = l[1]["gapoff"][0] if l[1]["gapoff"] else ""
    la0 = fnum(k[0].get("launch_mono_ms"))
    d["fault_after_launch_r0_ms"] = (l[0]["fire"] - la0) if (l[0]["fire"] is not None and la0 is not None) else ""
    fm = fnum(fault_mono_r0)
    d["q4_after_fault_ms_r0"] = (l[0]["q4"] - fm) if (l[0]["q4"] is not None and fm is not None) else ""
    d["decl_after_q4_ms_r0"] = (l[0]["decl"] - l[0]["q4"]) if (l[0]["decl"] is not None and l[0]["q4"] is not None) else ""
    kms = fnum(kill.get("kill_mono_ms"))
    r0kill = kill.get("rank") == "0"
    d["kill_r1clock_ms"] = (kms + off) if (kms is not None and r0kill and off is not None) else ""
    la1, km1, as1 = fnum(k[1].get("launch_mono_ms")), fnum(k[1].get("kernel_ms")), fnum(k[1].get("async_first_ms_after_launch"))
    kr1 = d["kill_r1clock_ms"] if d["kill_r1clock_ms"] != "" else None
    d["release_after_kill_ms_r1"] = (la1 + km1 - kr1) if (kr1 is not None and la1 is not None and km1 is not None) else ""
    d["async_after_kill_ms_r1"] = (la1 + as1 - kr1) if (kr1 is not None and la1 is not None and as1 is not None
                                                      and as1 >= 0) else ""
    d["decl_after_kill_ms_r0"] = (l[0]["decl"] - (kms - off)) if (kms is not None and not r0kill and off is not None
                                                                   and l[0]["decl"] is not None) else ""
    c1 = l[1]["close"][0][1] if l[1]["close"] else None
    d["r1close_after_q4_ms"] = ((c1 - off) - l[0]["q4"]) if (c1 is not None and off is not None and l[0]["q4"] is not None) else ""
    d["mute_applied"] = 1 if (mute.get("mute_on_mono_ms") and not mute.get("mute_skipped")) else 0
    d["mute_on_ms"] = mute.get("mute_on_mono_ms", "")
    d["mute_rules_on"] = mute.get("mute_rules_on", "")
    d["mute_rules_left"] = mute.get("mute_rules_left", "")
    d["mute_skipped"] = mute.get("mute_skipped", "")
    d["left_rules"] = meta.get("left_rules", "")
    return d
