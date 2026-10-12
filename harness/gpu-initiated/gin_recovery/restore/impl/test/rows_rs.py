#!/usr/bin/env python3
"""rows_rs.py - gin-restore work package 10: one row per trial from the raw files (EXPERIMENT.md 9.8 judging, section 3
search keys). Fixed with predictions_rs.csv: the columns and rules below are what score.py's acceptance formulas read.

    rows_rs.py <results dir> [--out trials.csv]     one row per trial (raw/, reg/, cost*/)

Inputs. raw/ holds the restore trials of run_rs.sh: <stem>_r<r>.kv (gin_rs's kv per live rank), <stem>_spare.kv,
<stem>_r<r>.log / _spare.log / _kill.out (every line "<rain CLOCK_MONOTONIC at receipt, s> <line>": the receipt clock),
<stem>_meta.txt (stem = <cell>_<lib>_n<k>). reg/ holds gin-remaining's run_mr_hr.sh trials (score.py adds gin-remaining's
own columns). cost*/ hold run_cost.sh runs.

Restore trial columns. Survivors = the live ranks other than kill_rank; the spare is apart.
  void            a live survivor failed before its exchange (init/registration/devComm error, exit 2, rendezvous)
  applied         kill cell: the killed rank ended by SIGKILL (exit 137) or a kill line ("GINRS killed", "GINRS die")
                  arrived; the checkpoint-pause cell since 2026-10-13 (meta die_switch=NCCL_GIN_RESTORE_TEST_DIE_IN_CKPT):
                  only the library's test-switch line (below) is its kill record (an exit 137 alone may be a timeout's
                  kill); other cells: 1
  config_ok       the cell's intended configuration (policy/restore as the cell asks; the refusal cells: 1)
  restore_live    1 when some live rank's Step hook returned success (the library implements it)
  surv_released   survivors whose untimed wait was let go below its target (kv released)
  surv_async      survivors' async-error samples (kv async_n)
  surv_unfinished survivors that did not finish every step (a hang shows here, not as "held")
  decline_n       survivor log lines of a decline or degraded reaction ("GIN/TS: declined rank=", why=declined|peer-dead|
                  degraded). The death-judged line is detection and stays under hold (9.10.6 (가)): not counted
  wait_held       (a) 1 iff surv_released = 0, surv_async = 0, decline_n = 0 and surv_unfinished = 0
  data_equal      (b) 1 iff every survivor has recv_bad = 0, xhist_bad = 0, dev_bad = 0, x_match = 1, sig_exact = 1, and,
                  when a spare ran, the spare too (all ranks' final state and received slots equal the host reference)
  no_reexec       (c) 1 iff no survivor re-executed a step (reexec_any = 0)
  revived_done    (d) 1 iff the spare revived (kv revived=1: Resume gave back its blob), finished every step, exit 0
  resume_err_all  1 iff every live rank's Resume returned non-success (the refusal cells)
  reason_same     1 iff every live rank reported the same refusal reason (kv resume_why, from ncclGetLastError)
  ff_fallthrough  1 iff some live rank's Resume returned success in a refusal cell
  strict_forced / strict_notforced / strict_bad   the library's window-report lines: forced=1 strict=1 ro=0 / forced=0 /
                  forced=1 with strict=0 or ro=1 (rs_layer.diff gdakiRsWinReport; printed for hold and spare processes)
Library-provided columns (line patterns checked against the integrated library, EXPERIMENT.md 12; empty without them):
  t_dead          first survivor "judged dead" line (receipt, s)          (hk's detection line, exists)
  suppress_ok     (e) "GIN/RS: rank R: suppress ... budget=B ... suppressed=S" lines: 1 iff every S = B (>= 1 line)
  restore_time_ms "judged dead" -> the last survivor's first "GIN/RS: rank R: ... published" line after it
  ckpt_before     the killed rank's "GIN/RS: rank R: checkpoint K stable" line for the spare's resume step K arrived
                  before the kill line (the checkpoint-pause cell); a survivor's "GIN/RS: rank Q: rank R armed at its
                  stable checkpoint K" line counts as well (CKPT_STABLE goes to the buddy first, 2026-10-13)
  ckpt_stable_before_kill  1/0 any such stable line of the killed rank before the kill (section 8 exclusion when 0)
  The kill line: the runner's recorded-PID kill ("GINRS killed", _kill.out), the driver's own ("GINRS die"), or, in the
  checkpoint-pause cell since 2026-10-13 (meta kill_in_hook=1, no _kill.out), the library's test-switch line in the killed
  rank's log: "GIN/RS: rank R: test switch NCCL_GIN_RESTORE_TEST_DIE_IN_CKPT: dying U us after the pause request of
  checkpoint K (stable checkpoints before: S)". Its receipt time is the kill time of that cell.
  die_ckpt        the checkpoint K that line names (empty without it)
  die_in_pause    survivors whose "input pause for rank R's checkpoint K ended (a hold of that rank took its gates)" line
                  names that K: the death landed inside that checkpoint's input pause there (the pilot's check; reported)
  activate_ms / later_n / later_ms  the buddy's "every survivor holds rank P: its spare activated (incarnation I, X ms
                  after this rank's hold start), N 'later' answers over Y ms" line (2026-10-13: the spare answers 'later'
                  while the killed process is still present; the buddy asks again every 20 ms)
  hold_started    survivor "GIN/RS: rank R: hold of rank P started" lines (the host branch's hold start)
  nospare_failfast_ok  no spare registered: hold_started = 0, a decline line, degraded_release = 1 (the hk reaction)
  hold_to_fallback_ms  the first hold-start line -> the first "the restore of rank P (incarnation I) is given up" line
  spare_absent_ok spare registered but absent: hold start and fallback lines, hold_to_fallback_ms 500-1500 (draft "about
                  1 s"), every survivor released 2000-2500 ms after the fallback (empty when neither line exists)
  spare_killed_first  the spare-absent cell: the spare's recorded-PID kill line arrived before the rank's kill line
  driver          the build the trial ran (meta driver; regression: mr/ff or mr/hold; cost: the program's file name)
  nomacro_reason  every rank's refusal reason names NCCL_GIN_RESTORE_DEVICE (the no-macro refusal cell)
  refused_ran_ok  every rank ran the workload fail-fast to the end after the refusal, exact, exit 0 (no trap)
  degraded_release every survivor released 2000-2500 ms after t_dead (the hk control)
  restore_count   "GIN/RS: rank R: rank P restored as incarnation" lines
  ckpt_pause_ms   the largest "GIN/RS: rank R: ... input pause ... pause_us=U" over survivors, in ms
The spare and the trial (meta and the spare's stamped lines; the spare branch's pilot items):
  spare_start_fail  a spare was wanted and did not start, never printed "GINRS spare_ready", or failed its init (section 8:
                  "예비 프로세스가 활성화 전에 시작에 실패함(따로 셈)")
  foreign_gpu     another process used a GPU when the trial started (meta gpu_apps_before; section 8)
  spare_replay_ms the spare's start line -> its ready line (the init replay with 4 ranks)
  spare_activate_ms  the kill line -> the spare's successful Resume line ("GINRS resume rank=R rc=0": activation and state
                  transfer; a spare whose wait ran out prints rc != 0 and is not counted)
  spare_peer_before / spare_peer_after  the spare's connects to a peer (not loopback, not its node) before and after its
                  ready point (strace; before must be 0: the replay contacts nobody; after: REJOIN and the data sockets)
  spare_uds_own / spare_uds_other  AF_UNIX connects to NCCL's proxy sockets of its own rank / of other ranks
  neg_cut_failed / neg_field_failed  the negative replays failed in the init replay with a "GIN/RS: replay" line
  neg_peer_connects  peer connects of the two negative spares (must be 0)
Regression trial (reg): id, cell, build (the library key), stem; score.py adds gin-remaining's columns.
Cost trial: metric, arm, rx, lib, value (lat: lat_p50_us; bw: burst_K x bytes / lat_p50_us, GB/s), exit0, exit1.
"""
import argparse, csv, glob, os, re

KVTOK = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)")
LIBCOLS = ["t_dead", "suppress_ok", "restore_time_ms", "ckpt_before", "ckpt_stable_before_kill", "hold_to_fallback_ms",
           "spare_absent_ok",
           "degraded_release", "restore_count", "ckpt_pause_ms"]
# reported only (no acceptance formula reads them): the checkpoint-pause kill and the activation's 'later' answers
INFOCOLS = ["kill_in_hook", "die_ckpt", "die_in_pause", "activate_ms", "later_n", "later_ms"]
RS_COLS = ["id", "stem", "sub", "key", "cell", "build", "runner", "tnum", "n", "void", "applied", "config_ok",
           "restore_live", "kill_rank", "spare", "surv_released", "surv_async", "surv_unfinished", "decline_n",
           "wait_held", "data_equal", "no_reexec", "revived_done", "resume_err_all", "reason_same", "ff_fallthrough",
           "strict_forced", "strict_notforced", "strict_bad", "steps", "wall_s"] + LIBCOLS + INFOCOLS + \
          ["spare_start_fail", "foreign_gpu", "spare_replay_ms", "spare_activate_ms", "spare_peer_before",
           "spare_peer_after", "spare_uds_own", "spare_uds_other", "strace_known", "neg_cut_failed", "neg_field_failed",
           "neg_peer_connects", "hold_started", "nospare_failfast_ok", "spare_killed_first", "driver", "nomacro_reason",
           "refused_ran_ok"] + \
          ["metric", "arm", "rx", "lib", "value", "exit0", "exit1", "win0", "win1", "tx_done", "iters", "cost_valid"]
DECLINE = re.compile(r"GIN/TS: declined rank=|why=(declined|peer-dead|degraded)")
DEAD = re.compile(r"judged dead")
WINREP = re.compile(r"GIN/RS: window MR rank=\d+ .*?\bstrict=(\d+) forced=(\d+) flag_strict=\d+ ro=(\d+)")
SUPPRESS = re.compile(r"GIN/RS: rank \d+: suppress .*\bbudget=(\d+) .*\bsuppressed=(\d+)")
PUBLISHED = re.compile(r"GIN/RS: rank \d+: .*\bpublished\b")
STABLE = re.compile(r"GIN/RS: rank (\d+): checkpoint (\d+) stable")
# the host branch's lines (impl/rs_layer_host.diff): the hold start of a survivor, the restore given up (FALLBACK), restored
HOLD_START = re.compile(r"GIN/RS: rank \d+: hold of rank \d+ started")
FALLBACK = re.compile(r"GIN/RS: rank \d+: the restore of rank \d+ \(incarnation \d+\) is given up")
RESTORED = re.compile(r"GIN/RS: rank \d+: rank \d+ restored as incarnation")
PAUSE = re.compile(r"GIN/RS: rank \d+: .*input pause .*\bpause_us=(\d+)")
RELEASED = re.compile(r"GINRS step rank=(\d+) step=\d+ released=1")
SPARE_START = re.compile(r"GINRS start rank=\d+ mode=spare")
SPARE_READY = re.compile(r"GINRS spare_ready ")
SPARE_RESUME = re.compile(r"GINRS resume rank=\d+ rc=0 ")
# a transcript fault the init replay detects (the spare branch's WARN strings); not the informational "replay ON",
# "replay mark=", "replay entry ... own_slot_bytes" lines, nor a configuration refusal or a missing file
REPLAY_FAIL = re.compile(r"GIN/RS: replay(: transcript entry \d+ is (damaged or )?cut| diverged|: the transcript is not usable"
                         r"|: a \w+ call after the end| entry \d+ \(site \d+\): .* outside the allowed fields)")
KILLED = re.compile(r"GINRS (killed|die) rank=(\d+)")
# the library's test switch of the checkpoint-pause cell (2026-10-13, rs_layer.diff gdakiCkptTestDie): rank, us, checkpoint
DIE_CKPT = re.compile(r"GIN/RS: rank (\d+): test switch NCCL_GIN_RESTORE_TEST_DIE_IN_CKPT: dying (\d+) us after the pause "
                      r"request of checkpoint (\d+) \(stable checkpoints before: (\d+)\)")
# a survivor: the subject R is armed at its stable checkpoint K (gdakiCkptOnStable)
ARMED = re.compile(r"GIN/RS: rank \d+: rank (\d+) armed at its stable checkpoint (\d+)")
# a survivor's input pause for subject R's checkpoint K that a hold of R ended (gdakiCkptOnHoldStart)
PAUSE_HOLD = re.compile(r"GIN/RS: rank \d+: input pause for rank (\d+)'s checkpoint (\d+) ended \(a hold of that rank "
                        r"took its gates\)")
# the buddy's activation line (2026-10-13 wording, WARN)
ACTIVATED = re.compile(r"GIN/RS: rank \d+: every survivor holds rank (\d+): its spare activated \(incarnation \d+, "
                       r"([0-9.]+) ms after this rank's hold start\), (\d+) 'later' answers over ([0-9.]+) ms")


def parse_kv(path):
    d = {}
    try:
        for line in open(path, errors="replace"):
            for m in KVTOK.finditer(line):
                d[m.group(1)] = m.group(2)
    except OSError:
        pass
    return d


def num(d, k, default=None):
    v = d.get(k) if isinstance(d, dict) else None
    if v is None or v == "":
        return default
    try:
        return int(v)
    except ValueError:
        try:
            return float(v)
        except ValueError:
            return default


def read_meta(stem):
    try:
        txt = open(stem + "_meta.txt", errors="replace").read()
    except OSError:
        return {}
    return {m.group(1): m.group(2) for m in KVTOK.finditer(txt)}


def stamped(path):
    """[(t, text)] of a receipt-clock log; lines without a leading time are kept with t = None."""
    out = []
    try:
        for line in open(path, errors="replace"):
            line = line.rstrip("\n")
            t, _, rest = line.partition(" ")
            try:
                out.append((float(t), rest))
            except ValueError:
                out.append((None, line))
    except OSError:
        pass
    return out


def first_t(lines, rx):
    ts = [t for t, l in lines if t is not None and rx.search(l)]
    return min(ts) if ts else None


def rs_row(stem, sub):
    meta = read_meta(stem)
    cell = meta.get("cell") or os.path.basename(stem).rsplit("_n", 1)[0]
    build = meta.get("lib", "rs")
    n = num(meta, "n", 4) or 4
    kill_rank = meta.get("kill_rank", "")
    kr = int(kill_rank) if kill_rank.isdigit() else -1
    ranks = list(range(n))
    surv = [r for r in ranks if r != kr]
    kv = {r: parse_kv("%s_r%d.kv" % (stem, r)) for r in ranks}
    logs = {r: stamped("%s_r%d.log" % (stem, r)) for r in ranks}
    has_spare = os.path.exists(stem + "_spare.kv") or meta.get("spare") == "1"
    sk = parse_kv(stem + "_spare.kv")
    slog = stamped(stem + "_spare.log")
    kout = stamped(stem + "_kill.out")
    rc = {r: num(meta, "r%drc" % r) for r in ranks}
    steps = num(kv[surv[0]] if surv else {}, "steps", 0) or 0
    refuse = cell.startswith("rs4_refuse")
    # void: a survivor that failed before its exchange
    void = 0
    for r in surv:
        d = kv[r]
        if d.get("rdv_error") or any((num(d, k, 0) or 0) != 0 for k in ("init_rc", "reg_rc", "devcomm_rc")) or rc[r] == 2:
            void = 1
    # applied; the kill time: the recorded-PID kill line, the driver's die line, or the library's test-switch line
    die_k, die = "", []
    if kr >= 0:
        die = [(t, int(m.group(3))) for t, l in logs[kr] if t is not None for m in [DIE_CKPT.search(l)]
               if m and int(m.group(1)) == kr]
        killed_line = [t for t, l in kout + logs[kr] if t is not None and KILLED.search(l)] + [t for t, _ in die]
        if meta.get("die_switch") == "NCCL_GIN_RESTORE_TEST_DIE_IN_CKPT":
            applied = 1 if die else 0  # the library's switch (run_rs.sh since 2026-10-13): its line is the kill record
        else:
            applied = 1 if (rc.get(kr) == 137 or killed_line) else 0
        t_kill = min(killed_line) if killed_line else None
        if die:
            die_k = min(die)[1]
    else:
        applied, t_kill = 1, None
    pol, restore = meta.get("policy", ""), meta.get("restore", "")
    if cell == "rs4_none":
        config_ok = int(pol == "hold" and restore == "1")
    elif cell == "rs4_none_off":
        config_ok = int(pol == "hold" and restore == "0")
    elif refuse:
        config_ok = 1  # the refusal cells misconfigure on purpose; the refusal is the result
    elif build == "hk":
        config_ok = int(pol == "failfast")
    else:
        config_ok = int(pol == "hold" and restore == "1")
    if not refuse and build == "rs" and any((num(kv[r], "resume_rc", 0) or 0) != 0 for r in ranks):
        config_ok = 0  # Resume refused where the cell expects the restore: a configuration error (section 8)
    restore_live = int(any(num(kv[r], "rs_hooks_live", 0) == 1 for r in ranks))
    s_rel = sum(1 for r in surv if (num(kv[r], "released", 0) or 0) > 0)
    s_async = sum(num(kv[r], "async_n", 0) or 0 for r in surv)
    s_unf = sum(1 for r in surv if num(kv[r], "steps_done", -1) != num(kv[r], "steps", -2))
    decl = sum(1 for r in surv for _, l in logs[r] if DECLINE.search(l))

    def exact(d):
        return (num(d, "recv_bad", 1) == 0 and num(d, "xhist_bad", 1) == 0 and num(d, "dev_bad", 1) == 0 and
                num(d, "x_match", 0) == 1 and num(d, "sig_exact", 0) == 1)
    revived = int(bool(sk) and num(sk, "revived", 0) == 1 and num(sk, "exit", 1) == 0 and
                  num(sk, "steps_done", -1) == num(sk, "steps", -2))
    data_equal = int(all(exact(kv[r]) for r in surv) and bool(surv) and (not has_spare or (revived and exact(sk))))
    no_reexec = int(all((num(kv[r], "reexec_any", 1) or 0) == 0 for r in surv) and bool(surv))
    wait_held = int(s_rel == 0 and s_async == 0 and decl == 0 and s_unf == 0)
    # the refusal cells
    resume_err_all = int(bool(ranks) and all((num(kv[r], "resume_rc", 0) or 0) != 0 for r in ranks))
    whys = [kv[r].get("resume_why", "") for r in ranks]
    reason_same = int(len(set(whys)) == 1 and whys[0] not in ("", "none"))
    ff_fallthrough = int(refuse and any(num(kv[r], "resume_rc") == 0 for r in ranks))
    # the no-macro refusal (2026-10-12 design change): the reason names the missing build macro on every rank, and after
    # the refusal every rank ran the workload fail-fast to the end with an exact result (no trap)
    nomacro_reason = int(bool(ranks) and all("NCCL_GIN_RESTORE_DEVICE" in kv[r].get("resume_why", "") for r in ranks))
    refused_ran_ok = int(bool(ranks) and all(num(kv[r], "refused_then_ran", 0) == 1 and kv[r].get("xchg") == "ok" and
                                             num(kv[r], "exit", 1) == 0 for r in ranks))
    # the window-report lines (all live ranks and the spare)
    sf = snf = sbad = 0
    for _, l in [x for r in ranks for x in logs[r]] + slog:
        m = WINREP.search(l)
        if not m:
            continue
        strict, forced, ro = m.group(1), m.group(2), m.group(3)
        if forced == "1" and strict == "1" and ro == "0":
            sf += 1
        elif forced == "0":
            snf += 1
        else:
            sbad += 1
    # library-provided timing columns (assumed patterns; empty when the library does not emit them)
    sl = [x for r in surv for x in logs[r]]
    t_dead = first_t(sl, DEAD)
    sup = [(int(m.group(1)), int(m.group(2))) for _, l in sl + slog for m in [SUPPRESS.search(l)] if m]
    suppress_ok = (1 if all(b == s for b, s in sup) else 0) if sup else ""
    restore_time_ms = ""
    if t_dead is not None:
        firsts = []
        for r in surv:
            ts = [t for t, l in logs[r] if t is not None and t >= t_dead and PUBLISHED.search(l)]
            if ts:
                firsts.append(min(ts))
        if firsts and len(firsts) == len(surv):
            restore_time_ms = round((max(firsts) - t_dead) * 1000.0, 1)
    stab = [(t, int(m.group(1)), int(m.group(2))) for t, l in [x for r in ranks for x in logs[r]]
            for m in [STABLE.search(l) or ARMED.search(l)] if m and t is not None]
    ckpt_before = ckpt_stable_before_kill = ""
    if stab and kr >= 0 and t_kill is not None:
        mine = [(t, k) for t, rr, k in stab if rr == kr]
        ckpt_stable_before_kill = int(any(t < t_kill for t, _ in mine))
        # the checkpoint the spare restored: its own blob names the next step (start_step = k + 1 for checkpoint k), which
        # does not depend on whether Resume's *step is the checkpoint's name or the next step
        st = num(sk, "start_step")
        k_res = st - 1 if st else num(sk, "resume_step")
        if k_res is not None:
            ckpt_before = int(any(t < t_kill and k == k_res for t, k in mine))
    rel_t = {}
    for r in surv:
        ts = [t for t, l in logs[r] if t is not None and RELEASED.search(l)]
        if ts:
            rel_t[r] = min(ts)
    degraded_release = ""
    all_rel = len(rel_t) == len(surv) and bool(surv)
    if t_dead is not None:
        degraded_release = int(all_rel and all(2000 <= (rel_t[r] - t_dead) * 1000.0 <= 2500 for r in surv))
    # the no-spare split (supervisor decision 2026-10-12; draft windows, the host branch states the exact rule):
    # (1) no spare registered: never armed, no hold start, a decline line, degraded release 2000-2500 ms after the death
    # (2) spare registered but absent: a hold start, the fallback about 1 s after it (draft 500-1500 ms), then every
    #     survivor released 2000-2500 ms after the fallback
    hold_started = sum(1 for _, l in sl if HOLD_START.search(l))
    nospare_failfast_ok = int(hold_started == 0 and decl > 0 and degraded_release == 1)
    t_hold, t_fb = first_t(sl, HOLD_START), first_t(sl, FALLBACK)
    hold_to_fallback_ms = round((t_fb - t_hold) * 1000.0, 1) if (t_hold is not None and t_fb is not None) else ""
    spare_absent_ok = ""
    if t_hold is not None or t_fb is not None:
        spare_absent_ok = int(t_hold is not None and t_fb is not None and 500.0 <= hold_to_fallback_ms <= 1500.0 and
                              all_rel and all(2000 <= (rel_t[r] - t_fb) * 1000.0 <= 2500 for r in surv))
    # the checkpoint-pause cell: survivors whose input pause for the dying checkpoint was ended by the hold
    die_in_pause = ""
    if die_k != "":
        die_in_pause = sum(1 for r in surv if any(m and int(m.group(1)) == kr and int(m.group(2)) == die_k
                                                  for _, l in logs[r] for m in [PAUSE_HOLD.search(l)]))
    act = [m for _, l in sl for m in [ACTIVATED.search(l)] if m and kr >= 0 and int(m.group(1)) == kr]
    activate_ms = float(act[0].group(2)) if act else ""
    later_n = int(act[0].group(3)) if act else ""
    later_ms = float(act[0].group(4)) if act else ""
    rcount = sum(1 for _, l in sl + slog if RESTORED.search(l))
    pauses = [int(m.group(1)) for _, l in sl for m in [PAUSE.search(l)] if m]
    ckpt_pause_ms = round(max(pauses) / 1000.0, 3) if pauses else ""
    base = {"id": os.path.basename(stem), "stem": stem, "sub": sub, "cell": cell, "build": build, "runner": "rsr",
            "n": n, "void": void, "applied": applied, "config_ok": config_ok, "restore_live": restore_live,
            "kill_rank": kill_rank, "spare": int(has_spare), "surv_released": s_rel, "surv_async": s_async,
            "surv_unfinished": s_unf, "decline_n": decl, "wait_held": wait_held, "data_equal": data_equal,
            "no_reexec": no_reexec, "revived_done": revived, "resume_err_all": resume_err_all,
            "reason_same": reason_same, "ff_fallthrough": ff_fallthrough, "strict_forced": sf,
            "strict_notforced": snf, "strict_bad": sbad, "steps": steps, "wall_s": meta.get("wall_s", ""),
            "t_dead": "" if t_dead is None else t_dead, "suppress_ok": suppress_ok, "restore_time_ms": restore_time_ms,
            "ckpt_before": ckpt_before, "ckpt_stable_before_kill": ckpt_stable_before_kill,
            "hold_started": hold_started, "nospare_failfast_ok": nospare_failfast_ok, "driver": meta.get("driver", ""),
            "nomacro_reason": nomacro_reason, "refused_ran_ok": refused_ran_ok,
            "hold_to_fallback_ms": hold_to_fallback_ms, "spare_absent_ok": spare_absent_ok,
            "degraded_release": degraded_release, "restore_count": rcount if (rcount or restore_live) else 0,
            "ckpt_pause_ms": ckpt_pause_ms, "kill_in_hook": meta.get("kill_in_hook", ""), "die_ckpt": die_k,
            "die_in_pause": die_in_pause, "activate_ms": activate_ms, "later_n": later_n, "later_ms": later_ms}
    base.update(spare_cols(stem, meta, sk, slog, t_kill))
    return base


def strace_counts(path):
    d = parse_kv(path) if os.path.exists(path) else {}
    return d


def spare_cols(stem, meta, sk, slog, t_kill):
    """the spare's start and timing (9.3; the spare branch's pilot items), its strace counts and the negative replays"""
    wanted = meta.get("spare_wanted") == "1"
    started = meta.get("spare") == "1"
    ready = meta.get("spare_ready") == "1"
    init_bad = any((num(sk, k, 0) or 0) != 0 for k in ("init_rc", "reg_rc", "devcomm_rc"))
    out = {"spare_start_fail": int(wanted and (not started or not ready or init_bad)) if wanted else 0}
    if meta.get("spare_kill_first") == "1":
        tk = [t for t, l in stamped(stem + "_spare_kill.out") if t is not None and "GINRS killed" in l]
        out["spare_killed_first"] = int(bool(tk) and (t_kill is None or min(tk) < t_kill))
    else:
        out["spare_killed_first"] = ""
    apps = meta.get("gpu_apps_before", "")
    out["foreign_gpu"] = int(any(x not in ("", "0") for x in apps.split("/"))) if apps else ""
    t0 = first_t(slog, SPARE_START)
    tr = first_t(slog, SPARE_READY)
    ta = first_t(slog, SPARE_RESUME)
    out["spare_replay_ms"] = round((tr - t0) * 1000.0, 1) if (t0 is not None and tr is not None) else ""
    out["spare_activate_ms"] = round((ta - t_kill) * 1000.0, 1) if (ta is not None and t_kill is not None) else ""
    sc = strace_counts(stem + "_spare_strace.txt")
    out["strace_known"] = int(bool(sc) and "strace_missing" not in sc and num(sc, "rt_known", 0) == 1) if sc else ""
    out["spare_peer_before"] = num(sc, "peer_connect_before_ready", "") if sc else ""
    out["spare_peer_after"] = num(sc, "peer_connect_after_ready", "") if sc else ""
    out["spare_uds_own"] = num(sc, "uds_own_rank", "") if sc else ""
    out["spare_uds_other"] = num(sc, "uds_other_rank", "") if sc else ""
    negs = [x for x in meta.get("negs", "").split(",") if x]
    npeer = 0
    for neg in ("neg_cut", "neg_field"):
        if neg not in negs:
            out[neg + "_failed"] = ""
            continue
        nk = parse_kv("%s_%s.kv" % (stem, neg))
        nl = stamped("%s_%s.log" % (stem, neg))
        # the replay fails at its start (init) and says why; a spare that reached Resume did not fail
        out[neg + "_failed"] = int((num(nk, "init_rc", 0) or 0) != 0 and any(REPLAY_FAIL.search(l) for _, l in nl)
                                   and not any(SPARE_READY.search(l) for _, l in nl))
        c = strace_counts("%s_%s_strace.txt" % (stem, neg))
        npeer += (num(c, "peer_connect_before_ready", 0) or 0) + (num(c, "peer_connect_after_ready", 0) or 0)
    out["neg_peer_connects"] = npeer if negs else ""
    return out


def reg_row(stem, sub):
    meta = read_meta(stem)
    lib = meta.get("lib", "")
    mk = meta.get("mrkey", "").rstrip("/")
    drv = "mr/" + os.path.basename(mk) if os.path.basename(mk) in ("ff", "hold") else mk
    return {"id": os.path.basename(stem), "stem": stem, "sub": sub, "cell": meta.get("cell", ""),
            "build": os.path.basename(lib.rstrip("/")) if "/" in lib else lib, "runner": "mrr",
            "n": num(meta, "n", 4) or 4, "driver": drv}


def cost_row(stem, sub):
    meta = read_meta(stem)
    r0, r1 = parse_kv(stem + "_r0.kv"), parse_kv(stem + "_r1.kv")
    metric = meta.get("metric", "")
    p50 = num(r0, "lat_p50_us")
    value = ""
    if p50:
        if metric == "bw256k":
            k, b = num(r0, "burst_K"), num(r0, "bytes")
            value = round(k * b / (p50 * 1e-6) / 1e9, 4) if k and b else ""
        else:
            value = p50
    win0, win1 = r0.get("win_flags", ""), r1.get("win_flags", "")
    tx, it = num(r0, "tx_done"), num(meta, "iters")
    valid = int(num(r0, "exit") == 0 and num(r1, "exit") == 0 and value != "" and win0 == "0x3" and win1 == "0x3" and
                tx is not None and tx == it)
    return {"id": os.path.basename(stem), "stem": stem, "sub": sub, "cell": meta.get("cell", ""),
            "build": meta.get("lib", ""), "runner": "cost", "metric": metric, "arm": meta.get("arm", ""),
            "rx": meta.get("rx", ""), "lib": meta.get("lib", ""), "value": value, "exit0": num(r0, "exit"),
            "exit1": num(r1, "exit"), "driver": meta.get("bin", ""), "win0": win0, "win1": win1,
            "tx_done": "" if tx is None else tx,
            "iters": "" if it is None else it, "cost_valid": valid}


def all_rows(R):
    rows = []
    for sub in sorted(os.listdir(R)):
        p = os.path.join(R, sub)
        if not os.path.isdir(p):
            continue
        for meta in sorted(glob.glob(os.path.join(p, "*_meta.txt"))):
            stem = meta[: -len("_meta.txt")]
            m = read_meta(stem)
            runner = m.get("runner", "")
            if runner == "cost" or sub.startswith("cost"):
                r = cost_row(stem, sub)
                r["key"] = "cost_%s_%s@%s" % (r["metric"], r["arm"], r["lib"])
            elif runner == "mrr" or sub.startswith("reg"):
                r = reg_row(stem, sub)
                r["key"] = "%s@%s" % (r["cell"], r["build"])
            else:
                r = rs_row(stem, sub)
                r["key"] = "%s@%s" % (r["cell"], r["build"])
            mt = re.search(r"_[nk](\d+)$", r["id"])
            r["tnum"] = int(mt.group(1)) if mt else 0
            rows.append(r)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    rows = all_rows(os.path.abspath(a.results))
    cols = list(RS_COLS)
    for r in rows:
        for c in r:
            if c not in cols:
                cols.append(c)
    out = a.out or os.path.join(os.path.abspath(a.results), "trials.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore", restval="")
        w.writeheader()
        for r in sorted(rows, key=lambda x: (x["sub"], x["key"], x["tnum"])):
            w.writerow(r)
    print("%s: %d trial(s)" % (out, len(rows)))


if __name__ == "__main__":
    main()
