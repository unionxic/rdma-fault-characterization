#!/usr/bin/env python3
"""rows_mi.py - gin-mirror, test branch: one row per trial from the raw files (../../EXPERIMENT.md 9.8 judging, section 3
search keys). gin-restore's rows_rs.py (imported for the shared restore columns, UNCHANGED) plus the mirror columns. Fixed
with predictions_mi.csv: the columns and rules below are what score.py's acceptance formulas read.

    rows_mi.py <results dir> [--out trials.csv]     one row per trial (raw/, reg/, cost*/)

Inputs as rows_rs.py (raw/: run_mi.sh's restore trials; reg/: gin-remaining's 4-rank runner; cost*/: run_cost_mi.sh).
Restore rows are rows_rs.rs_row (gin-restore's columns) with the overlay below; stems <cell>_<lib>_n<k>.

The mirror lines (impl/rs_mirror_api.h and impl/rs_store_api.h "line keys"): each starts "GIN/MI: rank %d: ", then the key
text, then key=value tokens, then " mono_ms=". The parser matches only the key text at the start (a prefix) and reads every
key=value of the rest in any order (rows_rs.KVTOK), so a separator or an added key does not lose a column. A key the
headers name but a line lacks reads empty.

Mirror columns (empty when the library does not emit the line yet):
  workload, overwrite, train, ring, mirror_env, checksum_env, resume_why0   gin_mi's kv (rank 0's resume_why)
  resume_refused     some rank's Resume returned non-success (an exclusion outside the refusal cells, section 8)
  recv_poison, dev_poison   poisoned received slots (host at the end / device when read), every final process summed
  ow_data_equal      every final process (live ranks and revived spares) bit-exact and no poison
  nomirror_corrupt   mirror off: the restore finished (wait_held = 1) and the data differ or a poison was replayed
  nomirror_detect    the checksum arm: a survivor's line says "source buffer changed" (the FALLBACK reason) and every
                     survivor released 2000-2500 ms after the first FALLBACK ("is given up") line (section 3)
  export_entries, export_mirror_entries, export_source_bytes   summed over the survivors' export lines
  import_pool_bytes  the spare's "import done" pool_bytes (else the sum of its import step lines)
  from_pool_ok       export_source_bytes = 0 and import_pool_bytes = the survivors' export mirror_bytes summed
  paced_ok           the spare's import step lines (one per step that had inputs: gaps allowed) rise strictly from its
                     start_step, each before that step's GINRS step line, "import done" left=0, one "INJECTED sent"
                     whose step is "import done"'s last_step (else the last import step line's)
  fetch_us, fetch_image_bytes, fetch_segment_bytes, fetch_bytes, fetch_extents   the slowest FETCH line of the spares
  tcp_image_bytes, tcp_segment_bytes   the store summaries summed (mirror on: 0, store_rdma). No process logs its
                     "store summary" in pilots 1 and 2 (0 lines of 109 logs: gdakiStoreFree prints it from the context's
                     free, after the last line the logs hold; 2026-10-15): then tcp_image_bytes is the sum of
                     "GIN/RS: rank R checkpoints at close: ... upload_bytes=N" over every process (gdakiCkptTeardownLine;
                     the same counter ck->nUploadBytes the summary prints) and tcp_segment_bytes 0 (no store path sends
                     segment bytes over a socket: the summary prints a constant 0 too), empty when neither line exists
  store_d2h_us, store_write_us, store_slot_bytes   the last "checkpoint K stored at buddy" line
  switches, rollbacks, restarts, third_slot, pool_max_bytes (max of max_live_bytes), pulls_sent, pulls_taken,
  broken_total, absorbed   the mirror summaries
  lane_broken, disarm_n, seg_restart_n   survivor "lane ... broken", DISARM ("rank P disarmed" or lane broken), restarts
  lane_broken_designed, lane_broken_other, disarm_designed, disarm_other, broken_other   the designed buddy gap split
                     out (../../EXPERIMENT.md 9.6; 2026-10-15, before the pre-registration, the review of the pilot 1
                     fixes): when rank b dies, the rank e whose checkpoint and pool lanes live on b (b's buddy, the rank the
                     hold lines name) is unprotected from b's death until e's next stable checkpoint after b's restore; the
                     survivors' lanes toward e break and DISARM e in that window by design. A window per dead rank b (each
                     death of a second-death cell):
                       ward e     the buddy named by the hold lines
                                  "GIN/RS: rank R: hold of rank b started: ... HOLDING to buddy rank e, ..." (gdakiHoldStart);
                                  no such line (no hold, e.g. a rank not armed at the kill): no window for b
                       start      the earliest of b's kill record ("GINRS killed rank=b" in _kill.out, "GINRS die rank=b"
                                  in _kill.out or b's log) and those hold lines' receipt times
                       end        e's own first "GIN/RS: rank e: checkpoint K stable at buddy rank b (...)" line after e's own
                                  "GIN/RS: rank e: rank b restored as incarnation ..." line; e's log is rank e's, or the
                                  revived spare's when e was the first death of the cell; no such line: the trial's end
                     A survivor line "GIN/MI: rank R: lane to rank e broken (...): DISARM" (K_LANE_BROKEN) or "GIN/RS: rank R:
                     rank e disarmed (...)" (DISARMED) with its receipt time in [start, end] of a window whose ward is e is
                     designed; every other such line (toward another rank, or outside the window) is other.
                       lane_broken_designed / lane_broken_other = lane_broken split; disarm_designed = lane_broken_designed
                       + the designed "disarmed" lines, disarm_other = disarm_n - disarm_designed
                       broken_other = broken_total - lane_broken_designed (empty when broken_total is): in the restore mode
                       a summary's broken= is that process's count of "lane ... broken" lines (gdakiMiPoll's device breaks,
                       gdakiMiLaneBroken's host breaks), summed over every process; a missing summary makes it negative
  inj_sent_step, inj_survivors, inj_from_n, gate_odd_ms_max   INJECTED
  ow_none_clean      data equal, no restore, input pause <= 10 ms, no segment restart (the no-fault cells)
Second death (meta kill2_rank; mi4_kill2_kill3_ow, mi4_train_kill2_kill3; K1 = kill_rank, K2 = kill2_rank):
  applied2           both kills recorded (rc 137 or a kill/die line)
  restore_time_ms_1, restore_time_ms_2   per death: its first "judged dead" line naming the rank -> the last of that
                     death's survivors' "restore round with rank R published" lines after it (death 2's survivors include
                     the revived K1)
  restored_subjects  how many of K1, K2 are named by "rank R restored as incarnation" lines (both: 2)
  stored_after       K2's first "checkpoint K stored at buddy rank K1" line after K2 logged K1 restored (the full image to
                     the revived buddy, 9.6) came before the second kill; void_between: K2's "checkpoint K is void" lines
                     between those two times
  rearm_ok           every survivor of the second death logged "rank K2 armed at its stable checkpoint" after K1's restore
                     and before the second kill (the lanes' re-enable is implied by the armable PAUSED, rs_mirror_api.h
                     gdakiMiPausedArmable; no line of its own [추론])
  fetch2_from_buddy  the second spare's FETCH line names buddy rank K1 (image and segments from the revived buddy)
  reimage_ok         applied2, stored_after, void_between <= 1, rearm_ok (section 3 reimage_after_restore)
  second_ok          applied2, both restore times <= 2000 ms, restored_subjects = 2, fetch2_from_buddy
  wait_held, no_reexec, data_equal are recomputed over the true survivors (both kills excluded, the revived K1 included)
  spare2_start_fail  the second spare was wanted and did not start, never got ready, or failed its init
Cost rows: rows_rs.cost_row, with value recomputed for every bw* metric (burst_K x bytes / p50, GB/s; rows_rs converts
  bw256k only), man_mirror passed through, and for the mirror-* arms mi_summary_ok (rank 0 logged its "mirror summary" with
  broken=0: the library did post mirror WRITEs); cost_valid requires it for those arms.
"""
import argparse, csv, glob, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "restore", "impl", "test"))
import rows_rs  # noqa: E402

MI_HEAD = re.compile(r"GIN/MI: rank (\d+): (.*)$")
K_LANE_BROKEN = re.compile(r"^lane to rank (\d+) broken\b")
K_SEG_RESTART = re.compile(r"^segments of rank (\d+) restarted at its checkpoint (\d+)")
K_PULL = re.compile(r"^CKPT_PULL to rank (\d+)\b")
K_DRAIN = re.compile(r"^drain for rank (\d+)\b")
K_FETCH = re.compile(r"^fetch for checkpoint (\d+) from buddy rank (\d+)\b")
K_EXPORT = re.compile(r"^export to rank (\d+):")  # not the refusal line "export to rank %d refused: %s"
K_IMPORT_STEP = re.compile(r"^import step (\d+)\b")
K_IMPORT_DONE = re.compile(r"^import done\b")
K_INJ_SENT = re.compile(r"^INJECTED sent\b")
K_INJ_FROM = re.compile(r"^INJECTED from rank (\d+)\b")
K_SUMMARY = re.compile(r"^mirror summary\b")
K_STORED = re.compile(r"^checkpoint (\d+) stored at buddy rank (\d+)\b")
K_STORE_SUMMARY = re.compile(r"^store summary\b")
CKPT_CLOSE = re.compile(r"GIN/RS: rank \d+ checkpoints at close: .*\bupload_bytes=(\d+)")
# gin-restore's lines (rs_layer.diff; rows_rs reads the rest)
DEAD_SUBJ = re.compile(r"GIN/TS: rank \d+: (?:rank|peer) (\d+) judged dead")
PUB_SUBJ = re.compile(r"GIN/RS: rank \d+: restore round with rank (\d+) published")
RESTORED_SUBJ = re.compile(r"GIN/RS: rank \d+: rank (\d+) restored as incarnation")
ARMED_SUBJ = re.compile(r"GIN/RS: rank \d+: rank (\d+) armed at its stable checkpoint (\d+)")
VOID_OWN = re.compile(r"GIN/RS: rank (\d+): checkpoint (\d+) is void")
GIVEN_UP = re.compile(r"GIN/RS: rank \d+: the restore of rank \d+ \(incarnation \d+\) is given up")
DISARMED = re.compile(r"GIN/RS: rank \d+: rank (\d+) disarmed")
# the hold start names the buddy that holds the dead rank's ward (gdakiHoldStart; "HOLDING to buddy rank e")
HOLD_WARD = re.compile(r"GIN/RS: rank \d+: hold of rank (\d+) started: .*\bHOLDING to buddy rank (\d+)")
STABLE_OWN = re.compile(r"GIN/RS: rank (\d+): checkpoint \d+ stable\b")
SRC_CHANGED = re.compile(r"source buffer changed")
KILLED = re.compile(r"GINRS (?:killed|die) rank=(\d+)")
GSTEP = re.compile(r"GINRS step rank=\d+ step=(\d+) ")

MI_COLS = ["workload", "overwrite", "train", "ring", "mirror_env", "checksum_env", "resume_why0", "resume_refused",
           "recv_poison", "dev_poison", "ow_data_equal", "nomirror_corrupt", "nomirror_detect", "export_entries",
           "export_mirror_entries", "export_source_bytes", "import_pool_bytes", "from_pool_ok", "paced_ok", "fetch_us",
           "fetch_image_bytes", "fetch_segment_bytes", "fetch_bytes", "fetch_extents", "tcp_image_bytes",
           "tcp_segment_bytes", "store_d2h_us", "store_write_us", "store_slot_bytes", "switches", "rollbacks", "restarts",
           "third_slot", "pool_max_bytes", "pulls_sent", "pulls_taken", "broken_total", "absorbed", "lane_broken",
           "disarm_n", "lane_broken_designed", "lane_broken_other", "disarm_designed", "disarm_other", "broken_other",
           "seg_restart_n", "inj_sent_step", "inj_survivors", "inj_from_n", "gate_odd_ms_max",
           "ow_none_clean", "applied2", "restore_time_ms_1", "restore_time_ms_2", "restored_subjects", "stored_after",
           "void_between", "rearm_ok", "fetch2_from_buddy", "reimage_ok", "second_ok", "spare2_start_fail"]


def num(d, k, default=None):
    return rows_rs.num(d, k, default)


def mi_lines(lines):
    """[(t, rank, text, kv)] of the GIN/MI lines of a stamped log; text is what follows "GIN/MI: rank R: " """
    out = []
    for t, l in lines:
        m = MI_HEAD.search(l)
        if m:
            out.append((t, int(m.group(1)), m.group(2), {k: v for k, v in rows_rs.KVTOK.findall(m.group(2))}))
    return out


def kvnum(d, k):
    v = d.get(k)
    if v is None:
        return None
    try:
        return int(v)
    except ValueError:
        try:
            return float(v)
        except ValueError:
            return None


def first_after(lines, rx, subj, t0):
    ts = [t for t, l in lines if t is not None and t >= t0 for m in [rx.search(l)] if m and int(m.group(1)) == subj]
    return min(ts) if ts else None


def restore_time(subject, survlogs, t_from=0.0):
    """ms from the first "judged dead" line naming subject (at or after t_from) to the last survivor's first "restore round
    with rank subject published" line after it; '' when a survivor has none"""
    td = [t for lg in survlogs for t, l in lg if t is not None and t >= t_from for m in [DEAD_SUBJ.search(l)]
          if m and int(m.group(1)) == subject]
    if not td or not survlogs:
        return ""
    t_dead = min(td)
    firsts = []
    for lg in survlogs:
        t = first_after(lg, PUB_SUBJ, subject, t_dead)
        if t is None:
            return ""
        firsts.append(t)
    return round((max(firsts) - t_dead) * 1000.0, 1)


def gap_windows(kr, kr2, logs, slog, slog2, kout):
    """the designed buddy-gap windows (the head comment): [(ward e, start, end)] over the deaths kr and kr2; end is
    float('inf') when e logged no stable checkpoint after b's restore"""
    every = [x for r in sorted(logs) for x in logs[r]] + slog + slog2
    out = []
    for b in (kr, kr2):
        if b < 0:
            continue
        holds = [(t, int(m.group(2))) for t, l in every if t is not None for m in [HOLD_WARD.search(l)]
                 if m and int(m.group(1)) == b]
        if not holds:
            continue
        kts = [t for t, l in kout + logs.get(b, []) if t is not None for m in [KILLED.search(l)]
               if m and int(m.group(1)) == b]
        start = min([t for t, _ in holds] + kts)
        for e in sorted({w for _, w in holds}):
            elog = slog if (e == kr and b == kr2) else logs.get(e, [])
            t_rest = first_after(elog, RESTORED_SUBJ, b, start)
            end = float("inf")
            if t_rest is not None:
                ts = [t for t, l in elog if t is not None and t > t_rest for m in [STABLE_OWN.search(l)]
                      if m and int(m.group(1)) == e]
                if ts:
                    end = min(ts)
            out.append((e, start, end))
    return out


def in_gap(wins, dest, t):
    return t is not None and any(e == dest and s <= t <= z for e, s, z in wins)


def mi_overlay(stem, base, meta):
    """the mirror columns of a restore row (base = rows_rs.rs_row's dict); keys here override base's"""
    n = int(base.get("n") or 4)
    kr = int(base["kill_rank"]) if str(base.get("kill_rank", "")).isdigit() else -1
    kr2 = int(meta.get("kill2_rank")) if str(meta.get("kill2_rank", "")).isdigit() else -1
    ranks = list(range(n))
    live = [r for r in ranks if r != kr and r != kr2]
    kv = {r: rows_rs.parse_kv("%s_r%d.kv" % (stem, r)) for r in ranks}
    logs = {r: rows_rs.stamped("%s_r%d.log" % (stem, r)) for r in ranks}
    sk, sk2 = rows_rs.parse_kv(stem + "_spare.kv"), rows_rs.parse_kv(stem + "_spare_2nd.kv")
    slog, slog2 = rows_rs.stamped(stem + "_spare.log"), rows_rs.stamped(stem + "_spare_2nd.log")
    kout = rows_rs.stamped(stem + "_kill.out")
    out = {}
    anchor = kv[live[0]] if live else kv[0]
    for c in ("workload", "mirror_env", "checksum_env"):
        out[c] = anchor.get(c, "")
    for c in ("overwrite", "train", "ring"):
        out[c] = num(anchor, c, "")
    out["resume_why0"] = kv[0].get("resume_why", "")
    out["resume_refused"] = int(any((num(kv[r], "resume_rc", 0) or 0) != 0 for r in ranks if kv[r]))
    finals = [kv[r] for r in live] + ([sk] if sk else []) + ([sk2] if sk2 else [])
    out["recv_poison"] = sum(num(d, "recv_poison", 0) or 0 for d in finals) if finals else ""
    out["dev_poison"] = sum(num(d, "dev_poison", 0) or 0 for d in finals) if finals else ""

    def exact_mi(d):
        return (num(d, "recv_bad", 1) == 0 and num(d, "xhist_bad", 1) == 0 and num(d, "dev_bad", 1) == 0 and
                num(d, "x_match", 0) == 1 and num(d, "sig_exact", 0) == 1 and (num(d, "recv_poison", 0) or 0) == 0 and
                (num(d, "dev_poison", 0) or 0) == 0)

    def revived_of(d):
        return bool(d) and num(d, "revived", 0) == 1 and num(d, "exit", 1) == 0 and \
            num(d, "steps_done", -1) == num(d, "steps", -2)
    has_spare = os.path.exists(stem + "_spare.kv") or meta.get("spare") == "1"
    has_spare2 = os.path.exists(stem + "_spare_2nd.kv") or meta.get("spare2") == "1"
    rev1, rev2 = revived_of(sk), revived_of(sk2)
    out["ow_data_equal"] = int(bool(live) and all(exact_mi(kv[r]) for r in live) and
                               (not has_spare or (rev1 and exact_mi(sk))) and (not has_spare2 or (rev2 and exact_mi(sk2))))
    # the survivors' lines: with one kill every rank but it; with two the live ranks and the revived first rank
    sl = [x for r in live for x in logs[r]]
    sl_all = [x for r in ranks if r != kr for x in logs[r]] if (kr >= 0 and kr2 < 0) else sl + slog
    ml = mi_lines(sl_all)
    spare_ml = mi_lines(slog) + mi_lines(slog2)
    every_ml = mi_lines([x for r in ranks for x in logs[r]] + slog + slog2)
    pois_any = any((num(d, "recv_poison", 0) or 0) > 0 or (num(d, "dev_poison", 0) or 0) > 0 for d in finals)
    out["nomirror_corrupt"] = int(base.get("wait_held") == 1 and
                                  (base.get("data_equal") == 0 or out["ow_data_equal"] == 0 or pois_any))
    # the checksum arm: the FALLBACK reason "source buffer changed", every survivor released 2000-2500 ms after the
    # first FALLBACK line (section 3: "fallback + 2 000-2 500 ms")
    surv_ranks = [r for r in ranks if r != kr] if kr2 < 0 else live
    t_fb = [t for r in surv_ranks for t, l in logs[r] if t is not None and GIVEN_UP.search(l)]
    if t_fb:
        fb0 = min(t_fb)
        rel = {}
        for r in surv_ranks:
            ts = [t for t, l in logs[r] if t is not None and rows_rs.RELEASED.search(l)]
            if ts:
                rel[r] = min(ts)
        src = any(SRC_CHANGED.search(l) for r in surv_ranks for _, l in logs[r])
        out["nomirror_detect"] = int(src and len(rel) == len(surv_ranks) and bool(surv_ranks) and
                                     all(2000.0 <= (rel[r] - fb0) * 1000.0 <= 2500.0 for r in surv_ranks))
    else:
        out["nomirror_detect"] = ""
    exp = [d for _, _, txt, d in ml if K_EXPORT.search(txt)]
    if exp:
        out["export_entries"] = sum(kvnum(d, "entries") or 0 for d in exp)
        out["export_mirror_entries"] = sum(kvnum(d, "mirror_entries") or 0 for d in exp)
        out["export_source_bytes"] = sum(kvnum(d, "source_bytes") or 0 for d in exp)
        exp_mb = sum(kvnum(d, "mirror_bytes") or 0 for d in exp)
    else:
        out["export_entries"] = out["export_mirror_entries"] = out["export_source_bytes"] = ""
        exp_mb = None
    sml1 = mi_lines(slog)
    istep = [(t, int(K_IMPORT_STEP.search(txt).group(1)), d) for t, _, txt, d in sml1 if K_IMPORT_STEP.search(txt)]
    idone = [d for _, _, txt, d in sml1 if K_IMPORT_DONE.search(txt)]
    if idone:
        pool = kvnum(idone[-1], "pool_bytes")
    elif istep:
        pool = sum(kvnum(d, "pool_bytes") or 0 for _, _, d in istep)
    else:
        pool = None
    out["import_pool_bytes"] = pool if pool is not None else ""
    out["from_pool_ok"] = int(out["export_source_bytes"] == 0 and exp_mb is not None and pool is not None and
                              pool == exp_mb) if exp else ""
    # the step-aligned import (9.4): steps start_step.. one by one, each before its kernel's step line; done left 0; one
    # INJECTED sent at the last step
    inj_sent = [d for _, _, txt, d in sml1 if K_INJ_SENT.search(txt)]
    if istep:
        st = num(sk, "start_step")
        steps = [u for _, u, _ in istep]
        # the library writes an "import step" line only for a step that had inputs (the integration, 2026-10-15): the
        # steps rise strictly from start_step on, gaps allowed; "import done" names the last step, which INJECTED carries
        cons = (st is not None and steps[0] >= int(st) and all(b > a for a, b in zip(steps, steps[1:])))
        before = True
        for t, u, _ in istep:
            ts = [tt for tt, l in slog if tt is not None for m in [GSTEP.search(l)] if m and int(m.group(1)) == u]
            if not ts or min(ts) <= t:
                before = False
        left0 = bool(idone) and kvnum(idone[-1], "left") == 0 and (kvnum(idone[-1], "failed") or 0) == 0
        last = kvnum(idone[-1], "last_step") if idone else None
        last = last if last is not None else steps[-1]
        one_inj = len(inj_sent) == 1 and kvnum(inj_sent[0], "step") == last and last >= steps[-1]
        out["paced_ok"] = int(cons and before and left0 and one_inj)
    else:
        out["paced_ok"] = ""
    fetch = [d for _, _, txt, d in spare_ml if K_FETCH.search(txt)]
    for c in ("fetch_image_bytes", "fetch_segment_bytes", "fetch_bytes", "fetch_extents", "fetch_us"):
        out[c] = ""
    if fetch:
        d = max(fetch, key=lambda x: kvnum(x, "fetch_us") or 0)
        ib, sb = kvnum(d, "image_bytes"), kvnum(d, "segment_bytes")
        out["fetch_image_bytes"] = ib if ib is not None else ""
        out["fetch_segment_bytes"] = sb if sb is not None else ""
        out["fetch_bytes"] = (ib or 0) + (sb or 0) if (ib is not None or sb is not None) else ""
        ex, fu = kvnum(d, "extents"), kvnum(d, "fetch_us")
        out["fetch_extents"] = ex if ex is not None else ""
        out["fetch_us"] = fu if fu is not None else ""
    ss = [d for _, _, txt, d in every_ml if K_STORE_SUMMARY.search(txt)]
    out["tcp_image_bytes"] = sum(kvnum(d, "tcp_image_bytes") or 0 for d in ss) if ss else ""
    out["tcp_segment_bytes"] = sum(kvnum(d, "tcp_segment_bytes") or 0 for d in ss) if ss else ""
    if not ss:  # the store summary never reached the logs (head comment): the checkpoint machine's close lines
        up = [int(m.group(1)) for _, l in [x for r in ranks for x in logs[r]] + slog + slog2
              for m in [CKPT_CLOSE.search(l)] if m]
        if up:
            out["tcp_image_bytes"] = sum(up)
            out["tcp_segment_bytes"] = 0
    stored = [d for _, _, txt, d in every_ml if K_STORED.search(txt)]
    for c, k in (("store_d2h_us", "d2h_us"), ("store_write_us", "write_us"), ("store_slot_bytes", "bytes")):
        v = kvnum(stored[-1], k) if stored else None
        out[c] = v if v is not None else ""
    summ = [d for _, _, txt, d in every_ml if K_SUMMARY.search(txt)]
    for c, k, agg in (("switches", "switches", sum), ("rollbacks", "rollbacks", sum), ("restarts", "restarts", sum),
                      ("third_slot", "third_slot", sum), ("pool_max_bytes", "max_live_bytes", max),
                      ("pulls_sent", "pulls_sent", sum), ("pulls_taken", "pulls_taken", sum),
                      ("broken_total", "broken", sum), ("absorbed", "absorbed", sum)):
        vals = [kvnum(d, k) for d in summ if kvnum(d, k) is not None]
        out[c] = agg(vals) if vals else ""
    out["lane_broken"] = sum(1 for _, _, txt, _ in ml if K_LANE_BROKEN.search(txt))
    out["seg_restart_n"] = sum(1 for _, _, txt, _ in ml if K_SEG_RESTART.search(txt))
    out["disarm_n"] = out["lane_broken"] + sum(1 for _, l in sl_all if DISARMED.search(l))
    # the designed buddy gap (9.6; the head comment) apart from the other breaks and DISARMs
    wins = gap_windows(kr, kr2, logs, slog, slog2, kout)
    out["lane_broken_designed"] = sum(1 for t, _, txt, _ in ml for m in [K_LANE_BROKEN.search(txt)]
                                      if m and in_gap(wins, int(m.group(1)), t))
    dis_designed = sum(1 for t, l in sl_all for m in [DISARMED.search(l)] if m and in_gap(wins, int(m.group(1)), t))
    out["lane_broken_other"] = out["lane_broken"] - out["lane_broken_designed"]
    out["disarm_designed"] = out["lane_broken_designed"] + dis_designed
    out["disarm_other"] = out["disarm_n"] - out["disarm_designed"]
    bt = out.get("broken_total", "")
    out["broken_other"] = bt - out["lane_broken_designed"] if bt != "" else ""
    v = kvnum(inj_sent[-1], "step") if inj_sent else None
    out["inj_sent_step"] = v if v is not None else ""
    v = kvnum(inj_sent[-1], "survivors") if inj_sent else None
    out["inj_survivors"] = v if v is not None else ""
    injf = [d for _, _, txt, d in ml if K_INJ_FROM.search(txt)]
    out["inj_from_n"] = len(injf) if injf else ""
    go = [kvnum(d, "gate_odd_ms") for d in injf if kvnum(d, "gate_odd_ms") is not None]
    out["gate_odd_ms_max"] = max(go) if go else ""
    rc = int(base.get("restore_count") or 0)
    cp = base.get("ckpt_pause_ms")
    out["ow_none_clean"] = int(base.get("data_equal") == 1 and out["ow_data_equal"] == 1 and rc == 0 and
                               isinstance(cp, (int, float)) and cp <= 10 and out["seg_restart_n"] == 0)
    # ---- the second death ----
    for c in ("applied2", "restore_time_ms_1", "restore_time_ms_2", "restored_subjects", "stored_after", "void_between",
              "rearm_ok", "fetch2_from_buddy", "reimage_ok", "second_ok"):
        out[c] = ""
    wanted2 = meta.get("spare2_wanted") == "1"
    init_bad2 = any((num(sk2, k, 0) or 0) != 0 for k in ("init_rc", "reg_rc", "devcomm_rc"))
    out["spare2_start_fail"] = int(meta.get("spare2") != "1" or meta.get("spare2_ready") != "1" or init_bad2) \
        if wanted2 else 0
    if kr >= 0 and kr2 >= 0:
        died = set()
        for r in (kr, kr2):
            if num(meta, "r%drc" % r) == 137 or any(m and int(m.group(1)) == r
                                                    for _, l in kout + logs[r] for m in [KILLED.search(l)]):
                died.add(r)
        out["applied2"] = int(kr in died and kr2 in died)
        kt2 = [t for t, l in kout + logs[kr2] if t is not None for m in [KILLED.search(l)] if m and int(m.group(1)) == kr2]
        t_kill2 = min(kt2) if kt2 else None
        surv1 = [logs[r] for r in ranks if r != kr]                  # death 1: every rank but K1 (K2 still alive)
        surv2 = [logs[r] for r in live] + ([slog] if slog else [])  # death 2: the live ranks and the revived K1
        out["restore_time_ms_1"] = restore_time(kr, surv1)
        out["restore_time_ms_2"] = restore_time(kr2, surv2)
        subs = {int(m.group(1)) for _, l in [x for r in ranks for x in logs[r]] + slog + slog2
                for m in [RESTORED_SUBJ.search(l)] if m}
        out["restored_subjects"] = len(subs & {kr, kr2})
        t_rest = first_after(logs[kr2], RESTORED_SUBJ, kr, 0.0)  # K2 logged K1 restored
        t_store = None
        if t_rest is not None:
            st_ts = [t for t, _, txt, _ in mi_lines(logs[kr2]) if t is not None and t > t_rest
                     for m in [K_STORED.search(txt)] if m and int(m.group(2)) == kr]
            t_store = min(st_ts) if st_ts else None
        out["stored_after"] = int(t_store is not None and (t_kill2 is None or t_store < t_kill2))
        t_end = t_store if t_store is not None else t_kill2
        if t_rest is not None:
            out["void_between"] = sum(1 for t, l in logs[kr2] if t is not None and t > t_rest and (t_end is None or t < t_end)
                                      for m in [VOID_OWN.search(l)] if m and int(m.group(1)) == kr2)
        armed = []
        for lg in surv2:
            ts = [t for t, l in lg if t is not None and t_rest is not None and t > t_rest and
                  (t_kill2 is None or t < t_kill2) for m in [ARMED_SUBJ.search(l)] if m and int(m.group(1)) == kr2]
            armed.append(bool(ts))
        out["rearm_ok"] = int(bool(armed) and all(armed) and t_rest is not None)
        f2 = [m for _, _, txt, _ in mi_lines(slog2) for m in [K_FETCH.search(txt)] if m]
        out["fetch2_from_buddy"] = int(any(int(m.group(2)) == kr for m in f2))
        vb = out["void_between"]
        out["reimage_ok"] = int(out["applied2"] == 1 and out["stored_after"] == 1 and vb != "" and vb <= 1 and
                                out["rearm_ok"] == 1)
        rt1, rt2 = out["restore_time_ms_1"], out["restore_time_ms_2"]
        out["second_ok"] = int(out["applied2"] == 1 and rt1 != "" and rt2 != "" and rt1 <= 2000 and rt2 <= 2000 and
                               out["restored_subjects"] == 2 and out["fetch2_from_buddy"] == 1)
        # wait_held / no_reexec / data_equal over the true survivors: the live ranks and the revived K1
        sv = [kv[r] for r in live] + ([sk] if sk else [])
        svlogs = [logs[r] for r in live] + ([slog] if slog else [])
        s_rel = sum(1 for d in sv if (num(d, "released", 0) or 0) > 0)
        s_async = sum(num(d, "async_n", 0) or 0 for d in sv)
        s_unf = sum(1 for d in sv if num(d, "steps_done", -1) != num(d, "steps", -2))
        decl = sum(1 for lg in svlogs for _, l in lg if rows_rs.DECLINE.search(l))
        out["wait_held"] = int(bool(sv) and s_rel == 0 and s_async == 0 and decl == 0 and s_unf == 0)
        out["no_reexec"] = int(bool(sv) and all((num(d, "reexec_any", 1) or 0) == 0 for d in sv))
        out["data_equal"] = out["ow_data_equal"]
    # gin-restore's ff_fallthrough keys on rs4_refuse; the mirror refusal cells too
    if str(base.get("cell", "")).startswith("mi4_refuse"):
        out["ff_fallthrough"] = int(any(num(kv[r], "resume_rc") == 0 for r in ranks if kv[r]))
    return out


def _lines(path):
    try:
        return [l.rstrip("\n") for l in open(path, errors="replace")]
    except OSError:
        return []


def cost_overlay(stem, r):
    """the cost row: value for every bw* metric, man_mirror, and the mirror arms' mi_summary_ok; cost_valid again"""
    r0 = rows_rs.parse_kv(stem + "_r0.kv")
    out = {"man_mirror": r0.get("man_mirror", ""), "man_peer_bad_slots": num(r0, "man_peer_bad_slots", "")}
    metric, arm = r.get("metric", ""), r.get("arm", "")
    value = r.get("value", "")
    if metric.startswith("bw"):
        p50, k, b = num(r0, "lat_p50_us"), num(r0, "burst_K"), num(r0, "bytes")
        value = round(k * b / (p50 * 1e-6) / 1e9, 4) if (p50 and k and b) else ""
        out["value"] = value
    out["mi_summary_ok"] = ""
    if arm.startswith("mirror-"):  # run_cost_mi.sh keeps the plain output (no receipt stamps): read every line
        summ = [d for _, _, txt, d in mi_lines([(0.0, l) for l in _lines(stem + "_r0.log")]) if K_SUMMARY.search(txt)]
        # broken=0 (the library counts the device's breaks in the measurement mode) and max_live_bytes > 0 (a cell was
        # valid and took mirror bytes: an arm whose cells never became valid mirrors nothing; the integration's review)
        out["mi_summary_ok"] = int(bool(summ) and all(kvnum(d, "broken") == 0 and (kvnum(d, "max_live_bytes") or 0) > 0
                                                      for d in summ))
    tx, it = r.get("tx_done"), r.get("iters")
    valid = (r.get("exit0") == 0 and r.get("exit1") == 0 and value != "" and r.get("win0") == "0x3" and
             r.get("win1") == "0x3" and tx not in ("", None) and tx == it)
    if arm.startswith("mirror-"):
        valid = valid and out["mi_summary_ok"] == 1
    out["cost_valid"] = int(bool(valid))
    return out


def all_rows(R):
    rows = []
    for sub in sorted(os.listdir(R)):
        p = os.path.join(R, sub)
        if not os.path.isdir(p):
            continue
        for meta in sorted(glob.glob(os.path.join(p, "*_meta.txt"))):
            stem = meta[: -len("_meta.txt")]
            m = rows_rs.read_meta(stem)
            runner = m.get("runner", "")
            if runner in ("costmi", "cost") or sub.startswith("cost"):
                r = rows_rs.cost_row(stem, sub)
                r.update(cost_overlay(stem, r))
                r["runner"] = "cost"
                r["key"] = "cost_%s_%s@%s" % (r["metric"], r["arm"], r["lib"])
            elif runner == "mrr" or sub.startswith("reg"):
                r = rows_rs.reg_row(stem, sub)
                r["key"] = "%s@%s" % (r["cell"], r["build"])
            else:
                r = rows_rs.rs_row(stem, sub)
                r.update(mi_overlay(stem, r, m))
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
    cols = list(rows_rs.RS_COLS) + MI_COLS + ["man_mirror", "man_peer_bad_slots", "mi_summary_ok"]
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
