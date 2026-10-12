#!/usr/bin/env python3
"""Independent QA recount of the gin-restore main run (results/20261013_main): restore, refusal and regression cells.

Written without reading the study's scorer (impl/test/score.py, rows_rs.py, selftest_rs.py) or its outputs (SCORE.md,
trials_scored.csv). Inputs: the per-trial files of raw/ (run_rs.sh: <stem>_r<r>.kv/.log, _spare.kv/.log, _kill.out,
_spare_kill.out, _meta.txt; every log line is "<rain CLOCK_MONOTONIC at receipt, s> <line>") and reg/ (gin-remaining's
run_mr_hr.sh: gin_mr kv/log per rank, _kill.out, _meta.txt; logs are not receipt-stamped). Each quantity is derived from
the condition text of EXPERIMENT.md section 3 (see recount.md for the definitions).

usage: recount_rs.py <results dir> <out dir> [cost]
writes <out dir>/trials_recount.csv (one row per trial) and <out dir>/summary.txt; prints the summary. With "cost": only the
cost holds (cost_*/), into <out dir>/cost_runs.csv (one row per run) and <out dir>/cost_summary.txt.
Every printed or written line is IPv4-masked (the reg logs are not masked by their runner; nothing from them is copied).
"""
import csv
import glob
import json
import os
import re
import sys

IPV4 = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")


def mask(s):
    return IPV4.sub("<ip>", str(s))


KV_RE = re.compile(r"([A-Za-z0-9_]+)=(.*?)(?=\s+[A-Za-z0-9_]+=|$)")


def parse_kv(path):
    """key=value lines; a value may hold spaces (gin_mr's rc strings); a later key overrides an earlier one."""
    d = {}
    if not os.path.exists(path):
        return None
    for line in open(path, errors="replace"):
        for m in KV_RE.finditer(line.strip()):
            d[m.group(1)] = m.group(2).strip()
    return d


def parse_log(path):
    """[(receipt time s, message)]: the message is the text after 'NCCL WARN ' for library lines, else the raw line."""
    out = []
    if not os.path.exists(path):
        return out
    for line in open(path, errors="replace"):
        line = line.rstrip("\n")
        t, _, rest = line.partition(" ")
        try:
            tt = float(t)
        except ValueError:
            continue
        rest = rest.strip()
        if not rest:
            continue
        i = rest.find("NCCL WARN ")
        out.append((tt, rest[i + len("NCCL WARN "):] if i >= 0 else rest))
    return out


def first(log, rx):
    r = re.compile(rx)
    for t, m in log:
        g = r.search(m)
        if g:
            return t, g
    return None, None


def allm(log, rx):
    r = re.compile(rx)
    return [(t, g) for t, m in log for g in [r.search(m)] if g]


def fnum(x, nd=1):
    if x is None:
        return "-"
    if isinstance(x, float):
        return ("%." + str(nd) + "f") % x
    return str(x)


def ival(d, k, default=None):
    try:
        return int(d.get(k))
    except (TypeError, ValueError, AttributeError):
        return default


# ---------------------------------------------------------------------------------------------------------------- rs
def load_rs(raw, stem):
    meta = parse_kv(os.path.join(raw, stem + "_meta.txt")) or {}
    P = {}
    for name in ("r0", "r1", "r2", "r3", "spare"):
        kv = parse_kv(os.path.join(raw, "%s_%s.kv" % (stem, name)))
        log = parse_log(os.path.join(raw, "%s_%s.log" % (stem, name)))
        if kv is not None or log:
            P[name] = {"kv": kv or {}, "log": log}
    kill = parse_log(os.path.join(raw, stem + "_kill.out"))
    skill = parse_log(os.path.join(raw, stem + "_spare_kill.out"))
    return meta, P, kill, skill


def survivor_view(P, s, kr):
    """the lines of survivor s about the dead rank kr (receipt time t and the process's own mono_ms)"""
    log = P["r%d" % s]["log"]
    v = {}

    def mono(g_line):
        mm = re.search(r"mono_ms=([0-9.]+)", g_line)
        return float(mm.group(1)) if mm else None

    def find(key, rx):
        for t, m in log:
            g = re.search(rx, m)
            if g:
                v[key] = t
                v[key + "_mono"] = mono(m)
                v[key + "_msg"] = m
                v[key + "_g"] = g
                return

    find("dead", r"rank %d: rank %d judged dead" % (s, kr))
    find("held", r"rank %d: rank %d \(incarnation \d+\) is held for a restore" % (s, kr))
    find("hold", r"rank %d: hold of rank %d started: gates odd since (-?[0-9.]+) ms before the start, (\d+) WQE\(s\) rung, "
               r"deadline in (\d+) ms, HOLDING to buddy rank (\d+), (\d+) QP\(s\) \(executed/sent at the hold: (\d+)/(\d+)\)"
         % (s, kr))
    find("rejoin", r"rank %d: rank %d's spare rejoined as incarnation (\d+) \(([0-9.]+) ms after the hold start" % (s, kr))
    find("restored", r"rank %d: rank %d restored as incarnation (\d+) \(([^;]*); ([0-9.]+) ms after the hold start, "
                     r"([0-9.]+) ms after the publish\)" % (s, kr))
    find("activated", r"rank %d: every survivor holds rank %d: its spare activated \(incarnation (\d+), ([0-9.]+) ms after "
                      r"this rank's hold start\), (\d+) 'later' answers over ([0-9.]+) ms" % (s, kr))
    find("later", r"rank %d: rank %d's spare answered 'later'" % (s, kr))
    find("fallback", r"rank %d: the restore of rank %d \(incarnation \d+\) is given up \((.*)\) in state (\w+)" % (s, kr))
    find("declined", r'declined rank=%d peer=%d reason="([^"]*)"' % (s, kr))
    find("gin_error", r"rank %d: GIN error raised for rank %d" % (s, kr))
    find("degraded", r"user devComm waits released rank=%d why=degraded" % s)
    find("release", r"GINRS step rank=%d step=(\d+) released=1 got=(\d+) want=(\d+)" % s)
    find("async", r"GINRS async rank=%d err=(\d+)" % s)
    v["n_declined"] = sum(1 for t, m in log if re.search(r"declined rank=%d peer=" % s, m))
    v["n_gin_error"] = sum(1 for t, m in log if "GIN error raised" in m)
    v["n_degraded"] = sum(1 for t, m in log if re.search(r"communicator degraded", m))
    v["n_release_lines"] = sum(1 for t, m in log if re.search(r"GINRS step rank=%d step=\d+ released=1" % s, m))
    v["n_async_lines"] = sum(1 for t, m in log if m.startswith("GINRS async"))
    v["n_hold_lines"] = sum(1 for t, m in log if re.search(r"is held for a restore|hold of rank \d+ started", m))
    # the last step this survivor completed before its restored line (or before the end when there is none)
    tcut = v.get("restored", float("inf"))
    steps = [int(g.group(1)) for t, g in allm(log, r"GINRS step rank=%d step=(\d+) released=0" % s) if t < tcut]
    v["last_step_before_restore"] = max(steps) if steps else None
    # stable-checkpoint arming of kr seen by this survivor
    v["armed"] = [(t, int(g.group(1))) for t, g in allm(log, r"rank %d: rank %d armed at its stable checkpoint (\d+)" % (s, kr))]
    return v


def window_mr(P):
    """(forced, notforced, bad, per-process counts) over every process's 'window MR' lines"""
    forced = notforced = bad = 0
    per = {}
    for name, p in P.items():
        n = 0
        for t, m in p["log"]:
            g = re.search(r"window MR rank=(\d+) bytes=(\d+) strict=(\d) forced=(\d) flag_strict=(\d) ro=(\d) "
                          r"restore_requested=(\d)", m)
            if not g:
                continue
            n += 1
            strict, frc, rr = int(g.group(3)), int(g.group(4)), int(g.group(7))
            if frc:
                forced += 1
            else:
                notforced += 1
            # bad: forced but not strict; restore requested but not forced; forced without a restore request
            if (frc and not strict) or (rr and not frc) or (frc and not rr):
                bad += 1
        per[name] = n
    return forced, notforced, bad, per


def pause_lines(P, ranks):
    out = []
    for r in ranks:
        name = "r%d" % r
        if name not in P:
            continue
        for t, g in allm(P[name]["log"], r"rank (\d+): input pause for rank (\d+)'s checkpoint (\d+) ended \((.*?)\) pause_us=(\d+)"):
            out.append((t, int(g.group(1)), int(g.group(2)), int(g.group(3)), g.group(4), int(g.group(5))))
    return out


def data_ok(kv, steps=600):
    return (ival(kv, "x_match") == 1 and ival(kv, "recv_bad") == 0 and ival(kv, "xhist_bad") == 0 and
            ival(kv, "dev_bad") == 0 and ival(kv, "sig_exact") == 1 and ival(kv, "steps_done") == steps)


def eval_rs(raw, stem, cellenv):
    meta, P, kill, skill = load_rs(raw, stem)
    cell, lib = meta.get("cell"), meta.get("lib")
    row = {"stem": stem, "cell": cell, "lib": lib, "key": "%s@%s" % (cell, lib)}
    excl = []
    # -- configuration checks (section 8: the cell's driver; section 7: the deployment i5)
    want_driver = cellenv.get((cell, lib), {}).get("driver")
    row["driver"] = meta.get("driver")
    if want_driver and meta.get("driver") != want_driver:
        excl.append("config_driver")
    md5_drv = {"gin_rs": "303e812d", "gin_rs_nomacro": "0f0826e6", "gin_rs_hk": "4ec9b846"}
    if not str(meta.get("driver_md5", "")).startswith(md5_drv.get(meta.get("driver"), "?")):
        excl.append("driver_md5")
    want_lib = {"rs": "4811f28f93294338812d8f83dafa8b61", "hk": "2913c777aa0b05d4d566c9f7638c6a0e"}[lib]
    if meta.get("lib_md5") != want_lib:
        excl.append("lib_md5")
    if meta.get("gpu_apps_before") != "0/0":
        excl.append("foreign_gpu")
    if meta.get("spare_wanted") == "1" and meta.get("spare_ready") != "1":
        excl.append("spare_start_fail")
    row["left"] = meta.get("left")
    row["rcs"] = " ".join("%s=%s" % (k, meta.get(k)) for k in ("r0rc", "r1rc", "r2rc", "r3rc", "sparerc") if k in meta)
    live = [r for r in range(4) if "r%d" % r in P]
    for r in live:
        if ival(P["r%d" % r]["kv"], "devcomm_rc") != 0:
            excl.append("no_gin_context_r%d" % r)
    kr = ival(meta, "kill_rank")
    row["kill_rank"] = kr
    # ---------------------------------------------------------------------------------------------- kill cells
    if kr is not None:
        surv = [r for r in range(4) if r != kr]
        krlog = P["r%d" % kr]["log"]
        # the kill time: the recorded-PID kill line (_kill.out), or the test switch's death line (checkpoint-pause cell)
        t_die, g_die = first(krlog, r"rank %d: test switch NCCL_GIN_RESTORE_TEST_DIE_IN_CKPT: dying (\d+) us after the pause "
                                    r"request of checkpoint (\d+) \(stable checkpoints before: (\d+)\)" % kr)
        t_k, _ = first(kill, r"GINRS killed rank=%d " % kr)
        row["t_kill"] = t_die if meta.get("kill_in_hook") == "1" else t_k
        row["die_ckpt"] = int(g_die.group(2)) if g_die else None
        row["killed_137"] = meta.get("r%drc" % kr) == "137"
        if row["t_kill"] is None or not row["killed_137"]:
            excl.append("no_fault")
        kr_steps = [int(g.group(1)) for t, g in allm(krlog, r"GINRS step rank=%d step=(\d+) released=0" % kr)]
        row["kr_last_step"] = max(kr_steps) if kr_steps else None
        V = {s: survivor_view(P, s, kr) for s in surv}
        deads = [V[s].get("dead") for s in surv if V[s].get("dead") is not None]
        row["t_dead_first"] = min(deads) if deads else None
        row["n_dead_lines"] = len(deads)
        if row["t_kill"] is not None and row["t_dead_first"] is not None:
            row["dead_after_kill_ms"] = (row["t_dead_first"] - row["t_kill"]) * 1e3
        # kill before the first stable (armed) checkpoint (section 8): only where the restore is wanted (a spare)
        if meta.get("spare_wanted") == "1" and meta.get("spare_kill_first") != "1":
            tk = row["t_kill"] or row["t_dead_first"]
            armed_before = [s for s in surv if any(t < tk for t, k in V[s]["armed"])]
            row["n_armed_before_kill"] = len(armed_before)
            if len(armed_before) < len(surv):
                excl.append("kill_before_first_stable_ckpt")
        # ---- survivors: wait held, no re-execution, refusal lines
        wh = []
        for s in surv:
            kv = P["r%d" % s]["kv"]
            ok = (ival(kv, "released") == 0 and ival(kv, "steps_done") == 600 and ival(kv, "async_n") == 0 and
                  V[s]["n_release_lines"] == 0 and V[s]["n_async_lines"] == 0 and V[s]["n_declined"] == 0)
            wh.append(ok)
        row["wait_held"] = int(all(wh))
        row["surv_declined"] = sum(V[s]["n_declined"] for s in surv)
        row["surv_gin_error_lines"] = sum(V[s]["n_gin_error"] for s in surv)
        row["surv_degraded_lines"] = sum(V[s]["n_degraded"] for s in surv)
        row["surv_async"] = sum(ival(P["r%d" % s]["kv"], "async_n", 0) or 0 for s in surv)
        row["no_reexec"] = int(all(ival(P["r%d" % s]["kv"], "reexec_any") == 0 and ival(P["r%d" % s]["kv"], "reexec_max") == 1
                                   and ival(P["r%d" % s]["kv"], "steps_done") == 600 for s in surv))
        sp = P.get("spare")
        if meta.get("spare_wanted") == "1" and meta.get("spare_kill_first") != "1":
            skv = sp["kv"] if sp else {}
            slog = sp["log"] if sp else []
            finals = [P["r%d" % s]["kv"] for s in surv] + [skv]
            row["data_equal"] = int(all(data_ok(k) for k in finals))
            row["revived_done"] = int(ival(skv, "revived") == 1 and ival(skv, "steps_done") == 600 and ival(skv, "exit") == 0
                                      and skv.get("xchg") == "ok" and meta.get("sparerc") == "0")
            row["spare_start_step"] = ival(skv, "start_step")
            # restore time: first judged-dead line of any survivor -> the last survivor's "restored as incarnation" line
            rest = [V[s].get("restored") for s in surv]
            row["n_restored"] = sum(1 for x in rest if x is not None)
            if row["n_restored"] == len(surv) and row["t_dead_first"] is not None:
                row["restore_time_ms"] = (max(rest) - row["t_dead_first"]) * 1e3
                row["restore_after_kill_ms"] = (max(rest) - row["t_kill"]) * 1e3 if row["t_kill"] else None
            # activation (the buddy's line) and the spare's 'later' answers
            act = [(s, V[s]) for s in surv if V[s].get("activated") is not None]
            if act:
                s, v = act[0]
                g = v["activated_g"]
                row["act_by"] = s
                row["act_after_hold_ms"] = float(g.group(2))
                row["later_n"] = int(g.group(3))
                row["later_ms"] = float(g.group(4))
                row["act_after_dead_ms"] = (v["activated"] - row["t_dead_first"]) * 1e3
            t_a, g_a = first(slog, r"spare rank %d: activating incarnation (\d+) from step (\d+) \((.*?)\)(?:; after (\d+) 'later' "
                                   r"answer\(s\) over ([0-9.]+) ms)?(?=\s+mono_ms=|$)" % kr)
            row["spare_activating_why"] = g_a.group(3) if g_a else None
            row["spare_later_n"] = int(g_a.group(4)) if g_a and g_a.group(4) else 0
            t_f, g_f = first(slog, r"spare rank %d: checkpoint (\d+) fetched from buddy rank (\d+) and written \((\d+) bytes, (\d+) "
                                   r"regions, blob (\d+) bytes\) in ([0-9.]+) ms" % kr)
            row["ckpt_used"] = int(g_f.group(1)) if g_f else None
            row["ckpt_fetch_ms"] = float(g_f.group(6)) if g_f else None
            t_r, g_r = first(slog, r"summary at devcomm mode=replay bound=\d+ recorded=\d+ replayed=(\d+) transcript_entries=(\d+) "
                                   r"diverged=(\d+) beyond=(\d+) own_diff_bytes=\d+ strict_mismatch=(\d+)")
            row["init_replay"] = ("%s/%s div=%s beyond=%s strict_mm=%s" % g_r.groups()) if g_r else None
            t_i, g_i = first(slog, r"rank %d: log import: checkpoint=(\d+) survivors=(\d+) entries=(\d+) data_bytes=(\d+) copies=(\d+) "
                                   r"signal_adds=(\d+)" % kr)
            row["log_import_entries"] = int(g_i.group(3)) if g_i else None
            # suppression: the spare's final line per (peer, qp) against X - P computed from the application's progress
            sup = {}
            for t, g in allm(slog, r"rank %d: suppress peer=(\d+) qp=(\d+) budget=(\d+) suppressed=(\d+) left=(\d+)" % kr):
                sup[(int(g.group(1)), int(g.group(2)))] = tuple(int(x) for x in g.groups()[2:])
            k = row["ckpt_used"]
            okall = True
            detail = []
            for q in surv:
                lines = {qp: val for (pq, qp), val in sup.items() if pq == q}
                pos = {qp: val for qp, val in lines.items() if val[0] > 0 or val[1] > 0}
                Sq = V[q]["last_step_before_restore"]
                ends = [x for x in (row["kr_last_step"], Sq, row.get("die_ckpt")) if x is not None]
                if k is None or not ends:
                    okall = False
                    detail.append("q%d:?" % q)
                    continue
                expect = 2 * (max(ends) - k)   # X_q - P_q in messages (put + signal per step)
                # survivor-side cross-check for the channel whose responder QP is the survivor's first QP to kr
                # (the hold-start line prints QP 0's executed count; context 0 is the traffic to rank 0)
                x0 = None
                if q == 0 and V[q].get("hold_g") is not None:
                    x0 = int(V[q]["hold_g"].group(6)) - 2 * (k + 1)
                okq = (len(pos) == 1 and all(val[0] == 0 and val[1] == 0 for qp, val in lines.items() if qp not in pos) and
                       list(pos.values())[0] == (expect, expect, 0) and (x0 is None or x0 == expect))
                okall = okall and okq
                b = list(pos.values())[0] if pos else (0, 0, 0)
                detail.append("q%d:exp=%d supp=%d bud=%d left=%d%s" % (q, expect, b[1], b[0], b[2],
                                                                      "" if x0 is None else " x0chk=%d" % x0))
            row["n_suppress_lines"] = len(sup)
            row["suppress_ok"] = int(okall and len(sup) > 0)
            row["suppress_detail"] = "; ".join(detail)
            # the steps the revived rank re-executed that the original had already completed (largest channel)
            ends = [x for x in [row["kr_last_step"], row.get("die_ckpt")] + [V[q]["last_step_before_restore"] for q in surv]
                    if x is not None]
            row["replayed_dup_steps"] = (max(ends) - k) if (k is not None and ends) else None
            # pause max over the survivors' input-pause lines (any rank's checkpoint)
            pl = pause_lines(P, surv)
            row["pause_max_ms"] = max(x[5] for x in pl) / 1e3 if pl else None
            # checkpoint-pause kill: the survivors inside the input pause of kr's dying checkpoint
            if meta.get("kill_in_hook") == "1":
                C = row["die_ckpt"]
                inpause = 0
                offs = []
                for s in surv:
                    # the survivor's pause for kr's dying checkpoint C did not end normally: the hold took its gates, and
                    # the hold-start line says the gates were already odd (paused) before the hold started
                    hit = [x for x in pl if x[1] == s and x[2] == kr and x[3] == C and "a hold of that rank took its gates" in x[4]]
                    hg = V[s].get("hold_g")
                    if hit and hg is not None and float(hg.group(1)) > 0:
                        inpause += 1
                    # report only: the pause start on the survivor's own clock (end mono - pause_us) minus its own
                    # judged-dead time (a positive value: the pause began after the death was judged)
                    for t, g in allm(P["r%d" % s]["log"], r"rank %d: input pause for rank %d's checkpoint %d ended \(a hold of that "
                                                         r"rank took its gates\) pause_us=(\d+) mono_ms=([0-9.]+)" % (s, kr, C)):
                        offs.append("r%d:%+.2f" % (s, float(g.group(2)) - int(g.group(1)) / 1e3 - V[s]["dead_mono"]))
                row["die_in_pause"] = inpause
                row["pause_start_minus_dead_ms"] = " ".join(offs)
                # on sunny's clock (rank 1 and the dying rank 3 share it): rank 1's pause start minus the SIGKILL instant
                # (the die line's mono_ms + the switch's delay)
                if kr == 3 and g_die is not None:
                    dm = re.search(r"mono_ms=([0-9.]+)", [m for t, m in krlog if "dying" in m][0])
                    for t, g in allm(P["r1"]["log"], r"rank 1: input pause for rank 3's checkpoint %d ended \(a hold of that rank took "
                                                     r"its gates\) pause_us=(\d+) mono_ms=([0-9.]+)" % C):
                        row["r1_pause_start_minus_kill_ms"] = float(g.group(2)) - int(g.group(1)) / 1e3 - \
                            (float(dm.group(1)) + int(g_die.group(1)) / 1e3)
                stable_before = [t for s in surv for t, kk in V[s]["armed"] if kk == k and t < row["t_kill"]]
                row["ckpt_before"] = int(k is not None and C is not None and k < C and len(stable_before) > 0)
                row["stable_before_n"] = int(g_die.group(3)) if g_die else None
        else:
            row["data_equal_surv"] = int(all(data_ok(P["r%d" % s]["kv"]) for s in surv))
        # fail-fast / fallback timings, per survivor (own process clock: both lines carry mono_ms)
        rel_dead, rel_dead_rc, fb_hold, rel_fb = [], [], [], []
        for s in surv:
            v = V[s]
            rm = v.get("release_mono")
            if rm is not None and v.get("dead_mono") is not None:
                rel_dead.append(rm - v["dead_mono"])
            if v.get("release") is not None and row.get("t_dead_first") is not None:
                rel_dead_rc.append((v["release"] - row["t_dead_first"]) * 1e3)
            if v.get("fallback") is not None and v.get("hold") is not None:
                fb_hold.append(v["fallback_mono"] - v["hold_mono"])
            if v.get("fallback") is not None and rm is not None:
                rel_fb.append(rm - v["fallback_mono"])
        row["rel_after_dead_ms"] = ",".join("%.1f" % x for x in rel_dead) or None
        row["rel_after_dead_rc_ms"] = ",".join("%.1f" % x for x in rel_dead_rc) or None
        row["fb_after_hold_ms"] = ",".join("%.1f" % x for x in fb_hold) or None
        row["rel_after_fb_ms"] = ",".join("%.1f" % x for x in rel_fb) or None
        row["n_hold_lines"] = sum(V[s]["n_hold_lines"] for s in surv)
        row["n_surv_declined"] = sum(1 for s in surv if V[s]["n_declined"] > 0)
        row["n_surv_released_kv"] = sum(1 for s in surv if ival(P["r%d" % s]["kv"], "released") == 1)
        row["fallback_why"] = "|".join(sorted(set(V[s]["fallback_g"].group(1) for s in surv if V[s].get("fallback_g") is not None))) or None
        if cell == "rs4_kill3_nospare":
            row["nospare_failfast_ok"] = int(row["n_hold_lines"] == 0 and row["n_surv_declined"] == 3 and len(rel_dead) == 3 and
                                             all(2000 <= x <= 2500 for x in rel_dead))
        if cell == "rs4_kill3_spareabsent":
            row["spare_killed_first"] = int(bool(first(skill, r"GINRS killed rank=%d " % kr)[0]))
            row["spare_absent_ok"] = int(all(V[s].get("hold") is not None for s in surv) and len(fb_hold) == 3 and
                                         all(500 <= x <= 1500 for x in fb_hold) and len(rel_fb) == 3 and
                                         all(2000 <= x <= 2500 for x in rel_fb) and row["n_surv_released_kv"] == 3)
        if cell == "rs4_kill3" and lib == "hk":
            row["degraded_release"] = int(len(rel_dead) == 3 and all(2000 <= x <= 2500 for x in rel_dead) and
                                          row["n_surv_released_kv"] == 3)
    # ---------------------------------------------------------------------------------------------- no-fault cells
    else:
        finals = [P["r%d" % r]["kv"] for r in range(4)]
        if cell in ("rs4_none", "rs4_none_off"):
            row["data_equal"] = int(all(data_ok(k) for k in finals))
            holdlines = sum(1 for r in range(4) for t, m in P["r%d" % r]["log"]
                            if re.search(r"is held for a restore|hold of rank \d+ started|restored as incarnation", m))
            closes = [g for r in range(4) for t, g in allm(P["r%d" % r]["log"], r"hold at close: armed_comm=(\d+) comm_lost=(\d+) "
                                                                                 r"holds=(\d+) restored=(\d+) fallbacks=(\d+)")]
            row["restore_count"] = holdlines + sum(int(g.group(3)) + int(g.group(4)) + int(g.group(5)) for g in closes) + \
                (1 if "spare" in P else 0)
            row["hold_close_lines"] = len(closes)
            row["armed_comm"] = ",".join(g.group(1) for g in closes)
            pl = pause_lines(P, range(4))
            row["pause_n"] = len(pl)
            row["pause_max_ms"] = max(x[5] for x in pl) / 1e3 if pl else 0.0
            f, nf, bad, per = window_mr(P)
            row["strict_forced"], row["strict_notforced"], row["strict_bad"] = f, nf, bad
            row["mr_lines_per_rank"] = ",".join(str(per.get("r%d" % r, 0)) for r in range(4))
        if cell.startswith("rs4_refuse_"):
            rc = [ival(k, "resume_rc") for k in finals]
            why = [k.get("resume_why") for k in finals]
            row["resume_rc"] = ",".join(str(x) for x in rc)
            row["resume_err_all"] = int(all(x is not None and x != 0 for x in rc))
            row["reason_same"] = int(len(set(why)) == 1 and why[0] not in (None, "none"))
            row["reason"] = why[0]
            cont = cell == "rs4_refuse_nomacro"
            ff = 0
            for r in range(4):
                k = finals[r]
                steps = sum(1 for t, m in P["r%d" % r]["log"] if re.match(r"GINRS step rank=%d " % r, m))
                if cont:
                    # ran on without having been told: a step run while Resume returned success, or without the report
                    if steps and (ival(k, "resume_rc") == 0 or ival(k, "refused_then_ran") != 1):
                        ff += 1
                else:
                    if steps or k.get("xchg") != "refused":
                        ff += 1
            row["ff_fallthrough"] = ff
            row["refuse_reason_ok"] = int(row["resume_err_all"] == 1 and row["reason_same"] == 1 and ff == 0)
            if cont:
                row["nomacro_reason"] = int(all("NCCL_GIN_RESTORE_DEVICE" in (w or "") for w in why))
                row["refused_ran_ok"] = int(all(ival(k, "refused_then_ran") == 1 and data_ok(k) and ival(k, "released") == 0 and
                                                ival(k, "async_n") == 0 and k.get("xchg") == "ok" and ival(k, "exit") == 0 and
                                                "cuda_error" not in k for k in finals) and
                                            all(meta.get("r%drc" % r) == "0" for r in range(4)))
                row["refuse_nomacro_clean"] = int(row["resume_err_all"] == 1 and row["reason_same"] == 1 and
                                                  row["nomacro_reason"] == 1 and row["refused_ran_ok"] == 1)
            f, nf, bad, per = window_mr(P)
            row["strict_forced"], row["strict_notforced"], row["strict_bad"] = f, nf, bad
    row["excluded"] = ",".join(sorted(set(excl))) or ""
    return row


# --------------------------------------------------------------------------------------------------------------- reg
def eval_reg(reg, stem):
    meta = parse_kv(os.path.join(reg, stem + "_meta.txt")) or {}
    cell = meta.get("cell")
    row = {"stem": stem, "cell": cell, "lib": "rs", "key": "%s@rs" % cell}
    excl = []
    want = {"reg_mr4_none": "41f3ce3a", "reg_rm4_kill3_untimed": "41f3ce3a",
            "reg_mr4_none_hold": "169f59c5", "reg_rm4_kill3_untimed_hold": "169f59c5"}[cell]
    if not str(meta.get("driver_md5", "")).startswith(want):
        excl.append("driver_md5")
    if meta.get("lib_md5") != "4811f28f93294338812d8f83dafa8b61":
        excl.append("lib_md5")
    kv = {r: parse_kv(os.path.join(reg, "%s_r%d.kv" % (stem, r))) or {} for r in range(4)}
    row["left"] = meta.get("left")
    row["rcs"] = " ".join("r%drc=%s" % (r, meta.get("r%drc" % r)) for r in range(4))
    kr = ival(meta, "kill_rank")
    row["kill_rank"] = kr
    if kr is None:
        ok = all(ival(kv[r], "exit") == 0 and ival(kv[r], "tx_ok") == 3 and ival(kv[r], "rx_ok") == 3 for r in range(4))
        row["transparent_ok"] = int(ok and all(meta.get("r%drc" % r) == "0" for r in range(4)))
        row["outcomes"] = ",".join(str(kv[r].get("outcome")) for r in range(4))
    else:
        surv = [r for r in range(4) if r != kr]
        kill = open(os.path.join(reg, stem + "_kill.out")).read() if os.path.exists(os.path.join(reg, stem + "_kill.out")) else ""
        row["killed"] = int("kill_mono_ms=" in kill and meta.get("r%drc" % kr) not in ("0", None))
        if not row["killed"]:
            excl.append("no_fault")
        rel, nrel, kd, stuck = [], 0, 0, 0
        for s in surv:
            log = open(os.path.join(reg, "%s_r%d.log" % (stem, s)), errors="replace").read()
            m = re.search(r"rank %d: rank %d judged dead \(cause=[^)]*\) mono_ms=([0-9.]+)" % (s, kr), log)
            dead = float(m.group(1)) if m else None
            k = kv[s]
            # released with an error (DG1: "오류로 풀림"): the rx edge from the dead rank let go and its rc is not "no error"
            if ival(k, "rx_%d%d_rel" % (kr, s)) == 1 and k.get("rx_%d%d_rc" % (kr, s)) not in (None, "no error"):
                nrel += 1
                try:
                    rel.append(float(k["rx_%d%d_rel_mono_ms" % (kr, s)]) - dead)
                except (TypeError, KeyError, ValueError):
                    rel.append(None)
            if ival(k, "kernel_done") == 1:
                kd += 1
            else:
                stuck += 1
            if "watchdog" in k:
                stuck += 1
        edges = [(a, b) for a in surv for b in surv if a != b]
        txok = sum(1 for a, b in edges if ival(kv[a], "tx_%d%d_done" % (a, b)) == 1000 and kv[a].get("tx_%d%d_rc" % (a, b)) == "no error"
                   and ival(kv[a], "tx_%d%d_nerr" % (a, b)) == 0)
        row["n_rel_dead"] = nrel
        row["rel_after_dead_ms"] = ",".join("-" if x is None else "%.1f" % x for x in rel)
        row["n_surv_edges"] = len(edges)
        row["surv_tx_ok"] = txok
        row["n_kdone_surv"] = kd
        row["n_stuck_surv"] = stuck
        row["regression_kill3_ok"] = int(nrel == 3 and all(x is not None and 2000 <= x <= 3000 for x in rel) and len(edges) == 6
                                         and txok == 6 and kd == 3 and stuck == 0)
    row["excluded"] = ",".join(excl)
    return row



# -------------------------------------------------------------------------------------------------------------- cost
# The eight cost holds (run_cost.sh; EXPERIMENT.md 3 cost rows and 9.15.6's frame). Per run: rank 0 sends, rank 1 receives on
# the node the cell names. Value: lat4k, lat256k = rank 0's lat_p50_us (put + signal + flush, 3 000 iterations); bw256k =
# burst_K x bytes / rank 0's lat_p50_us (the p50 of the 12 burst-iteration times; the kv has no bandwidth key), in GB/s
# (10^9 B/s). Valid run (9.15.6): both kv exit=0, rank 0 tx_done = iters, rank 1 rx_done = iters, no nccl_error/cuda_error/
# watchdog, win_flags=0x3 on both ranks, meta rc_r0=rc_r1=0, left=0, library and driver md5 those of PREREG.txt for the arm.
# An arm with fewer than 5 valid runs is incomplete. Difference in the worse direction against the base arm's median, % of
# the base median: latency (arm - base) / base; bandwidth (base - arm) / base. within:10 = worse <= 10 % on every node and
# metric. Separated = every valid run of one arm above every valid run of the other (ties do not separate).
COST_MD5 = {"lib": {"rsp": "be91b270155005827bfa0e79c527165c", "hkp": "84209c03a497bd28206210205bfc6cf5"},
            "drv": {"gin_ts2@rsp": "dd44e14ef4af4e5a1200706965b1c771", "gin_ts2_ff@rsp": "5e4db845a693f65fd18341fa2e30eb7d",
                    "gin_ts2@hkp": "64418f216c68bf1f518b25737a7e5c9d"}}
COST_BIN = {"off": ("gin_ts2", "rsp"), "ua-hold": ("gin_ts2", "rsp"), "on": ("gin_ts2", "rsp"), "sampled": ("gin_ts2", "rsp"),
            "full": ("gin_ts2", "rsp"), "ffb-rs": ("gin_ts2_ff", "rsp"), "ffb-rs-macro": ("gin_ts2", "rsp"),
            "ffb-hk": ("gin_ts2", "hkp")}


def median(v):
    v = sorted(v)
    n = len(v)
    return None if n == 0 else (v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2)


def cost_run(d, stem):
    meta = parse_kv(os.path.join(d, stem + "_meta.txt")) or {}
    k0 = parse_kv(os.path.join(d, stem + "_r0.kv")) or {}
    k1 = parse_kv(os.path.join(d, stem + "_r1.kv")) or {}
    row = {"stem": stem, "folder": os.path.basename(d), "metric": meta.get("metric"), "arm": meta.get("arm"), "node": meta.get("rx"),
           "tag": meta.get("tag"), "lib": meta.get("lib"), "bin": meta.get("bin")}
    iters = ival(meta, "iters")
    bad = []
    for name, k in (("r0", k0), ("r1", k1)):
        if ival(k, "exit") != 0:
            bad.append("%s_exit" % name)
        if any(x in k for x in ("nccl_error", "cuda_error", "watchdog")):
            bad.append("%s_error_key" % name)
        if k.get("win_flags") != "0x3":
            bad.append("%s_win_flags" % name)
    if ival(k0, "tx_done") != iters:
        bad.append("tx_done")
    if ival(k1, "rx_done") != iters:
        bad.append("rx_done")
    if meta.get("rc_r0") != "0" or meta.get("rc_r1") != "0":
        bad.append("rc")
    if meta.get("left") != "0":
        bad.append("left")
    want_bin, want_lib = COST_BIN.get(meta.get("arm"), (None, None))
    if meta.get("bin") != want_bin or meta.get("lib") != want_lib:
        bad.append("arm_build")
    if meta.get("lib_md5") != COST_MD5["lib"].get(meta.get("lib")):
        bad.append("lib_md5")
    if meta.get("driver_md5") != COST_MD5["drv"].get("%s@%s" % (meta.get("bin"), meta.get("lib"))):
        bad.append("driver_md5")
    p50 = k0.get("lat_p50_us")
    p50 = float(p50) if p50 not in (None, "") else None
    if meta.get("metric") == "bw256k":
        K = ival(k0, "burst_K")
        row["value"] = (K * ival(meta, "bytes") / p50 / 1e3) if (K and p50) else None   # B/us = MB/s -> GB/s
        row["unit"] = "GB/s"
    else:
        row["value"] = p50
        row["unit"] = "us"
    row["p50_us"] = p50
    row["signal_exact_rx"] = k1.get("signal_exact")
    row["invalid"] = ",".join(bad)
    return row


def cost_recount(res, outd):
    runs = []
    for d in sorted(glob.glob(os.path.join(res, "cost_*"))):
        if not os.path.isdir(d):
            continue
        for mf in sorted(glob.glob(os.path.join(d, "*_meta.txt"))):
            runs.append(cost_run(d, os.path.basename(mf)[:-len("_meta.txt")]))
        # kv files without a meta are not counted (9.15.6): name them
        for kf in glob.glob(os.path.join(d, "*_r0.kv")):
            if not os.path.exists(kf[:-len("_r0.kv")] + "_meta.txt"):
                runs.append({"stem": os.path.basename(kf)[:-6], "folder": os.path.basename(d), "invalid": "no_meta"})
    keys = ["folder", "stem", "metric", "arm", "node", "tag", "lib", "bin", "p50_us", "value", "unit", "signal_exact_rx", "invalid"]
    with open(os.path.join(outd, "cost_runs.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in runs:
            w.writerow({k: mask(fnum(r.get(k), 6) if isinstance(r.get(k), float) else r.get(k, "")) for k in keys})
    grp = {}
    for r in runs:
        if r.get("invalid") == "" and r.get("value") is not None:
            grp.setdefault((r["node"], r["metric"], r["arm"]), []).append(r["value"])
    nrun = {}
    for r in runs:
        nrun[(r.get("node"), r.get("metric"), r.get("arm"))] = nrun.get((r.get("node"), r.get("metric"), r.get("arm")), 0) + 1

    def worse(metric, base, arm):
        if base is None or arm is None:
            return None
        return (base - arm) / base * 100 if metric == "bw256k" else (arm - base) / base * 100

    def separated(a, b):
        return bool(a and b and (min(a) > max(b) or min(b) > max(a)))

    lines = ["family | node | metric | arm | n run | n valid | median | min-max | worse vs base % | separated from base"]
    fam = {"log": (["lat4k", "lat256k", "bw256k"], ["off", "ua-hold", "on", "sampled", "full"], "off"),
           "ffbranch": (["lat4k", "lat256k"], ["ffb-hk", "ffb-rs", "ffb-rs-macro"], "ffb-hk")}
    table = {}
    for fname, (metrics, arms, base) in fam.items():
        for node in ("rain", "sunny"):
            for m in metrics:
                bv = grp.get((node, m, base), [])
                bmed = median(bv)
                for a in arms:
                    v = grp.get((node, m, a), [])
                    med = median(v)
                    wv = worse(m, bmed, med) if a != base else None
                    sep = separated(v, bv) if a != base else None
                    table[(fname, node, m, a)] = {"n": len(v), "med": med, "worse": wv, "sep": sep,
                                                  "complete": len(v) >= 5, "nrun": nrun.get((node, m, a), 0)}
                    lines.append("%s | %s | %s | %s | %d | %d | %s | %s | %s | %s" % (
                        fname, node, m, a, nrun.get((node, m, a), 0), len(v), fnum(med, 3),
                        ("%.3f-%.3f" % (min(v), max(v))) if v else "-", "base" if a == base else fnum(wv, 2),
                        "-" if a == base else ("yes" if sep else "no")))
    # verdicts
    out = []

    def within(arm, pct):
        cells = [table[("log", n, m, arm)] for n in ("rain", "sunny") for m in ("lat4k", "lat256k", "bw256k")]
        bases = [table[("log", n, m, "off")] for n in ("rain", "sunny") for m in ("lat4k", "lat256k", "bw256k")]
        if not all(c["complete"] for c in cells + bases):
            return "자료 부족", None
        over = [(n, m, table[("log", n, m, arm)]["worse"]) for n in ("rain", "sunny") for m in ("lat4k", "lat256k", "bw256k")
                if table[("log", n, m, arm)]["worse"] > pct]
        return ("맞음" if not over else "틀림"), over

    for name, arm in (("cost_log", "on"), ("cost_unarmed", "ua-hold")):
        v, over = within(arm, 10)
        out.append("%s (%s vs off, within 10%%): %s; over 10%%: %s" % (name, arm, v,
                   ", ".join("%s %s %+.2f%%" % o for o in over) if over else "none"))
    ff = [table[("ffbranch", n, m, "ffb-rs")] for n in ("rain", "sunny") for m in ("lat4k", "lat256k")]
    ffb = [table[("ffbranch", n, m, "ffb-hk")] for n in ("rain", "sunny") for m in ("lat4k", "lat256k")]
    if not all(c["complete"] for c in ff + ffb):
        out.append("cost_ff (ffb-rs vs ffb-hk not separated): 자료 부족")
    else:
        sep = [(n, m) for n in ("rain", "sunny") for m in ("lat4k", "lat256k") if table[("ffbranch", n, m, "ffb-rs")]["sep"]]
        out.append("cost_ff (ffb-rs vs ffb-hk not separated): %s; separated: %s" % ("맞음" if not sep else "틀림",
                                                                                   ", ".join("%s %s" % x for x in sep) or "none"))
    out.append("cost_checksum (sampled, full vs off): report only")
    s = "\n".join(mask(x) for x in lines + [""] + out)
    open(os.path.join(outd, "cost_summary.txt"), "w").write(s + "\n")
    print(s)
    return table

# -------------------------------------------------------------------------------------------------------------- main
def main():
    res, outd = sys.argv[1], sys.argv[2]
    os.makedirs(outd, exist_ok=True)
    if len(sys.argv) > 3 and sys.argv[3] == "cost":   # the cost holds only (section 6 of recount.md)
        cost_recount(res, outd)
        return
    raw, reg = os.path.join(res, "raw"), os.path.join(res, "reg")
    cells = json.load(open(os.path.join(res, "..", "..", "impl", "test", "cells_rs.json")))
    cellenv = {}
    for h in ("G1", "G2", "R1"):
        for e in cells["holds"][h]:
            cellenv[(e["cell"], e["build"])] = {"driver": e["driver"], "n": e["n"], "env": e["env"]}
    rows = []
    for mf in sorted(glob.glob(os.path.join(raw, "*_meta.txt"))):
        rows.append(eval_rs(raw, os.path.basename(mf)[:-len("_meta.txt")], cellenv))
    for mf in sorted(glob.glob(os.path.join(reg, "*_meta.txt"))):
        rows.append(eval_reg(reg, os.path.basename(mf)[:-len("_meta.txt")]))
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(os.path.join(outd, "trials_recount.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: mask(fnum(r.get(k), 1) if isinstance(r.get(k), float) else r.get(k, "")) for k in keys})

    # ---- verdicts: count over valid trials (not excluded)
    def sel(key):
        return [r for r in rows if r["key"] == key]

    def valid(rs):
        return [r for r in rs if not r.get("excluded")]

    plan = {"rs4_none@rs": 5, "rs4_none_off@rs": 5, "rs4_kill3@rs": 10, "rs4_kill3_ckpt@rs": 5, "rs4_kill1@rs": 5,
            "rs4_kill3_nospare@rs": 5, "rs4_kill3_spareabsent@rs": 5, "rs4_kill3@hk": 5, "rs4_refuse_symgin@rs": 3,
            "rs4_refuse_gintype@rs": 3, "rs4_refuse_restoreoff1@rs": 3, "rs4_refuse_nomacro@rs": 3, "reg_mr4_none@rs": 5,
            "reg_mr4_none_hold@rs": 5, "reg_rm4_kill3_untimed@rs": 5, "reg_rm4_kill3_untimed_hold@rs": 5}
    preds = [
        ("wait_held", "rs4_kill3@rs", lambda r: r.get("wait_held") == 1, 9),
        ("data_equal", "rs4_kill3@rs", lambda r: r.get("data_equal") == 1, 9),
        ("no_reexec", "rs4_kill3@rs", lambda r: r.get("no_reexec") == 1, "all"),
        ("revived_done", "rs4_kill3@rs", lambda r: r.get("revived_done") == 1, 9),
        ("suppress_exact", "rs4_kill3@rs", lambda r: r.get("suppress_ok") == 1, 9),
        ("restore_time", "rs4_kill3@rs", lambda r: r.get("restore_time_ms") is not None and r["restore_time_ms"] <= 2000, 9),
        ("ckpt_kill", "rs4_kill3_ckpt@rs", lambda r: r.get("die_in_pause") == 3 and r.get("wait_held") == 1 and
         r.get("data_equal") == 1 and r.get("no_reexec") == 1 and r.get("revived_done") == 1 and r.get("ckpt_before") == 1, 4),
        ("kill_other", "rs4_kill1@rs", lambda r: r.get("wait_held") == 1 and r.get("data_equal") == 1 and
         r.get("no_reexec") == 1 and r.get("revived_done") == 1, 4),
        ("nospare_failfast", "rs4_kill3_nospare@rs", lambda r: r.get("nospare_failfast_ok") == 1, 4),
        ("spare_absent_fallback", "rs4_kill3_spareabsent@rs", lambda r: r.get("spare_absent_ok") == 1, 4),
        ("control_degraded", "rs4_kill3@hk", lambda r: r.get("degraded_release") == 1, 4),
        ("none_clean", "rs4_none@rs", lambda r: r.get("data_equal") == 1 and r.get("restore_count") == 0 and
         r.get("pause_max_ms") is not None and r["pause_max_ms"] <= 10, "all"),
        ("strict_forced", "rs4_none@rs", lambda r: r.get("strict_forced", 0) > 0 and r.get("strict_notforced") == 0 and
         r.get("strict_bad") == 0, "all"),
        ("strict_notforced", "rs4_none_off@rs", lambda r: r.get("strict_notforced", 0) > 0 and r.get("strict_forced") == 0 and
         r.get("strict_bad") == 0, "all"),
    ]
    for c in ("rs4_refuse_symgin@rs", "rs4_refuse_gintype@rs", "rs4_refuse_restoreoff1@rs", "rs4_refuse_nomacro@rs"):
        preds.append(("refuse_reason " + c.split("@")[0], c, lambda r: r.get("refuse_reason_ok") == 1, "all"))
    preds.append(("refuse_nomacro_clean", "rs4_refuse_nomacro@rs", lambda r: r.get("refuse_nomacro_clean") == 1, "all"))
    for c in ("reg_mr4_none@rs", "reg_mr4_none_hold@rs"):
        preds.append(("regression_none " + c.split("@")[0], c, lambda r: r.get("transparent_ok") == 1, "all"))
    for c in ("reg_rm4_kill3_untimed@rs", "reg_rm4_kill3_untimed_hold@rs"):
        preds.append(("regression_kill3 " + c.split("@")[0], c, lambda r: r.get("regression_kill3_ok") == 1, "all"))
    lines = ["prediction | cell | n planned | n run | n valid | excluded | k | need | verdict"]
    for name, key, cond, need in preds:
        rs = sel(key)
        vr = valid(rs)
        k = sum(1 for r in vr if cond(r))
        nd = len(vr) if need == "all" else need
        if len(vr) < 0.75 * plan[key]:
            verdict = "자료 부족"
        else:
            verdict = "맞음" if (k >= nd if need != "all" else k == len(vr)) else "틀림"
        ex = ";".join("%s:%s" % (r["stem"], r["excluded"]) for r in rs if r.get("excluded")) or "-"
        lines.append("%s | %s | %d | %d | %d | %s | %d | %s | %s" % (name, key, plan[key], len(rs), len(vr), ex, k,
                                                                    ("=n" if need == "all" else ">=%d" % need), verdict))
    s = "\n".join(mask(x) for x in lines)
    open(os.path.join(outd, "summary.txt"), "w").write(s + "\n")
    print(s)


if __name__ == "__main__":
    main()
