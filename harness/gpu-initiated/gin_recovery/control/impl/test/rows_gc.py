#!/usr/bin/env python3
"""rows_gc.py - gin-control, test side: one row per trial from the raw files (../../EXPERIMENT.md 9.3 and 9.8's columns,
section 3's search keys). gin-mirror's rows_mi.py (imported, UNCHANGED) gives gin-restore's and gin-mirror's columns; this file
adds the control-path columns. Standard library only.

    rows_gc.py <results dir> [--out trials.csv]     one row per trial (raw/, reg/, cost*/, local/)

Inputs: run_gc.sh's trials (raw/: <stem>_r<r>.kv/.log, _spare*.kv/.log, _kill.out, _spare_kill.out, _inject.out,
_fdhold.out, _cleanup.out, _launcher_<node>.log, _meta.txt; stem <cell>_<build>_n<k>); gin-remaining's runner (reg/);
run_cost_gc.sh (cost*/); the CPU program gate_fenced (local/gate_fenced*.log, one row per "gate_fenced trial" line). Every log
line is "<rain CLOCK_MONOTONIC at receipt, s> <line>" (the receipt clock). A library or runner line also carries its own
"mono_ms=" (the process's CLOCK_MONOTONIC). Intervals inside one process use mono_ms; intervals between two processes of one
node use their mono_ms (section 3: "같은 노드 시계"); between nodes the receipt clock (lines from sunny arrive over ssh, so a
rain - sunny interval carries that delay; the *_clock columns say which was used).

The library's lines this file reads. "exists" = in the tree now (gc_layer*.diff, ln4); "TODO(pN)" = the format this file
defines for phase N to emit exactly (notes_test.md lists them):
  DEAD      GIN/TS: rank R: rank P judged dead (cause=C) mono_ms=M                                  exists (ln4); C in rdma:
            EXITED, FIN+STALE, FIN+NORESP, REMACC+FIN, NORESP, LINKDOWN (TODO(p1): the rdma build prints its cause names)
  STALLED   GIN/RC: rank R: rank P (incarnation I) judged stalled (... STALL | STALL_HELPER ...) ... mono_ms=M   exists (p1)
  CLOSED    GIN/TS: rank R: socket to rank P closed cause=C mono_ms=M [liveness=...]                 exists (ln4; FIN, ECONNRESET)
  PAGEUP    GIN/RC: rank R: status page up (B B in use, probe_ms=P stall_ms=S W=W) mono_ms=M         exists (p1)
  CONFIRM   GIN/RC: rank R: confirm window for rank P opened by FIN|RST W=W mono_ms=M                TODO(p1)
            GIN/RC: rank R: confirm window for rank P closed: alive|STALE|NORESP|REMACC|unconfirmed mono_ms=M   TODO(p1)
  SUSPECT   GIN/RC: rank R: rank P suspected (kind=watch|helper stale_ms=X) mono_ms=M                TODO(p1)
  TIMEOUT   GIN/RC: rank R: probe of rank P timed out (no CQE in T ms) mono_ms=M                     TODO(p1)
  PROBESUM  GIN/RC: rank R: probe summary peer=P reads=N ok=K remacc=A noresp=B timeout=C gen=G lat_med_us=X lat_max_us=Y
            beat_gap_max_ms=Z torn=T mono_ms=M   (at teardown, one per peer)                          TODO(p1)
  WITLOST   GIN/RC: rank R: witness of rank P lost; liveness alive mono_ms=M (table row 8)           TODO(p1)
  FENCING   GIN/RC: rank R: rank P (incarnation I) fence FENCING: FENCE sent to the launcher of node N mono_ms=M   TODO(p3)
  FENCED    GIN/RC: rank R: rank P (incarnation I) fence FENCED (by FENCED|EXITED from node N) mono_ms=M        TODO(p3)
  WINCHG    GIN/RC: rank R: window check after the fence|judgement of rank P: changed=N cells mono_ms=M        TODO(p3)
  CTRLSUM   GIN/RC: rank R: control summary tcp_record_bytes=.. tcp_data_bytes=.. tcp_conns=.. witness_conns=..
            records_lost=.. records_dup=.. repairs=.. sendq_deferred=.. sendq_max=.. rnr=.. async=.. active_mtu=.. mono_ms=M
            (at teardown, every process)                                                            TODO(p2)
  RINGSUM   GIN/RC: rank R: ring summary peer=P gen=G sent=S received=V lost=L dup=D mono_ms=M      TODO(p2)
  PAIRSENT  GIN/RC: rank R: PAIR(record, gen G) to rank P (local ERR) mono_ms=M                      TODO(p2)
  REPAIRED  GIN/RC: rank R: record QP|liveness READ QP to rank P re-paired (gen G) mono_ms=M         TODO(p2)
  REJOIN    GIN/RS: rank R: rank P's spare rejoined as incarnation I (...)                           exists (ln4)
            GIN/RC: rank R: REJOIN to rank P resent (try T) mono_ms=M (the spare)                  TODO(p2)
            GIN/RS: spare rank R: rank P answered the REJOIN with X: it is gone for this restore    exists (the FAIL)
  switches  GIN/TS: rank R: test switch DIE_RST: linger 0 on N socket(s); SIGKILL now mono_ms=M      TODO(p1)
            GIN/TS: rank R: test switch RST_GAP: N socket(s) reset, listener closed for L ms mono_ms=M   TODO(p1)
            GIN/TS: rank R: test switch FD_HOLDER=sock|uverbs: child gin_fdhold pid=P holds N fd(s) mono_ms=M  TODO(p1)
            GIN/RC: rank R: test switch FREEZE_PAGE=L[:helper]: <beats> frozen mono_ms=M            TODO(p1)
            GIN/RC: rank R: test switch QP_ERR: record QP to rank P moved to ERR mono_ms=M          TODO(p2)
            GIN/RC: rank R: test switch CREDIT_STALL: no RECV re-posted for L ms mono_ms=M          TODO(p2)
            GIN/RC: rank R: test switch DROP_UD: the REJOIN datagram to rank P dropped mono_ms=M    TODO(p2)
            GIN/TS: TEST socket mute on|off rank=R peers=N mono_ms=M                                exists (gin-harden)
  The launcher's lines (GIN/LA: node N: ..., ../launcher/gin_launcher.c, exist): EXITED, "exited; EXITED not sent", FENCE ...
  SIGKILL sent, FENCED (after SIGKILL X ms / ended before), "(STOP_launcher)", "refused to signal", activation ... LATER |
  ACCEPTED | REFUSED (why), "record QP of rank R ... lost", "liveness-READ QP of rank R failed", "is leaving".
  The runner's lines (run_gc.sh): GINRS killed rank=R node=N pid=P which=W mono_ms=M; GINRS stop / cont (present=, stopped_ms=);
  GINRS duty start / end; GINRS fdhold_killed; GINRS cleanup_stopped.

Columns (empty when the lines are missing; counts are 0 when the lines exist but none matched):
  subject, n_surv            the rank under test (meta subject_rank) and the ranks judging it (every other rank)
  confirm_w_ms               W of the trial (the PAGEUP lines' W, else meta confirm_ms)
  n_judge, n_judge_confirm, n_judge_exited, n_judge_noresp, n_judge_stall, n_judge_stall_helper, n_judge_linkdown
                             survivors with a judgement of the subject (their first DEAD or STALLED line), by cause
  weak_cause_n               rdma builds: DEAD lines (any subject) whose cause is not one of the seven or LINKDOWN
  timeout_judge_n            DEAD lines whose cause names a timeout only
  judge_any_n                every DEAD and STALLED line of the trial (every subject, every process)
  fin_judge_dev_min_ms/max   confirm-window survivors: (judgement - its window's t_F) - W; t_F = the CONFIRM open line, else
                             the last CLOSED line (FIN or ECONNRESET) naming the subject before the judgement (same process)
  n_rst_surv, n_rst_confirm, n_rst_exited, rst_judge_dev_min/max_ms, rst_exited_kill_judge_min/max_ms, rst_judge_ms_min/max
                             survivors with an ECONNRESET CLOSED line naming the subject: their judgement's cause; for the
                             confirm causes (judgement - that RST) - W; for EXITED kill -> judgement; any cause RST -> judgement
  kill_judge_ms_min/max, kill_judge_exited_min_ms/max, kill_judge_clock   kill -> first judgement per survivor
  stop_judge_ms_min/max      injection start (GINRS stop, or the FREEZE_PAGE line) -> the survivor's STALLED line
  judge_spread_ms            the survivors' first judgements, max - min (receipt clock)
  judge_to_publish_ms, kill_to_publish_ms   the first judgement / the kill -> the last survivor's first "published" line
  hold_ms_max, hold_other_n, kill_hold_ms_min   the survivors' hold durations (hold start -> restored, given up or the log's
                             end), hold starts naming another rank than the subject, kill -> first hold start
  suspect_n, suspect_stale_ms_min/max   SUSPECT lines naming the subject
  read_n, read_ok_n, read_success_pct, read_lat_med_us_max, read_lat_max_us, beat_gap_max_ms, page_torn_n   PROBESUM, summed
  witness_lost_n, confirm_alive_n   WITLOST lines; CONFIRM closed alive lines
  fence_sent, fenced, fence_order_ok, fence_names_ok, fence_sent_to_fenced_ms, fenced_to_fallback_ms
                             the buddy's (subject xor 1, the revived buddy's spare log when the buddy died first) FENCING and
                             FENCED lines for the subject, and its activation line (rows_rs ACTIVATED): fence_order_ok =
                             FENCED and the activation exist, FENCING (when there) <= FENCED <= the activation;
                             fence_names_ok = both FENCING and FENCED exist; FENCED -> the buddy's first "is given up" line
  cont_target_present        the runner's SIGCONT line: was the stopped PID still there (0 when the fence ended it)
  win_changed_after          WINCHG lines summed
  la_exited_n, la_exit_silent_n, la_fence_sigkill_n, la_fenced_n, la_fenced_after_sigkill_ms, la_later_n,
  la_act_refused_why, la_stop_n, la_refused_signal_n, la_pid_mismatch_n, la_qp_err_n, launcher_same, launcher_ready
                             the trial's launcher logs (both nodes) for the subject; la_stop_n counts every "(STOP_launcher)"
                             line; la_qp_err_n the launcher's QP-loss lines for ranks other than the subject before the first
                             "is leaving" line (TODO(p3): the teardown rule); launcher_same = both launchers' pid and start equal
                             before and after the trial and alive after
  tcp_ctrl_bytes, tcp_data_bytes, tcp_ctrl_conn_n, witness_pairs, rec_lost_n, rec_dup_n, rec_repair_n, sendq_deferred,
  sendq_max, rnr_n, async_n, active_mtu_kv_min   CTRLSUM summed (rnr_n adds the meta's RNR port-counter growth);
                             witness_pairs = the summed witness_conns with the witness on, 0 with it off (so
                             tcp_ctrl_conn_n == witness_pairs says every TCP connection of the layer is a witness)
  active_mtu_rain, active_mtu_sunny   the runner's ibv_devinfo reading (meta)
  ckpt_stable_in_mute, ckpt_void_in_mute, helper_reconnect_n   stable / void checkpoint lines inside the socket mute's on -> off
                             window (receipt), and helper reconnect lines
  qperr_pair_sent_by_target, qperr_rec_gen_delta, qperr_probe_gen_delta, qperr_pair_read_fail, qperr_records_after
                             the QP_ERR target rank T and its peer P (the switch line): T logged PAIRSENT to P; the highest
                             re-paired record gen on T toward P; liveness-READ re-pairings of the pair (both ends); the pair's
                             PROBESUM failures; RINGSUM received by T from P in a gen >= 1
  rejoin_dropped, rejoin_resent, rejoin_accept_n, rejoin_accept_dup_n, fail_to_spare_n
  inject_ok, inject_off_ms, inject_dur_off_ms   the injection's record exists (runner line or library switch line); the
                             runner's injection receipt - its plan (meta inj_plan_rt); a stop's measured length - STOP_MS
  kill2_after_armed          KILL2_KIND=pid_after_armed: the second kill's receipt >= the survivors' last armed line (meta)
  stable_between_pair_kills  the spare-absent cell: a stable checkpoint of the subject between the spare kill and its kill
  gate rows (local/): old_go_ms, fenced_go_ms, gate_diff_ms, second_thread_ms
"""
import argparse, csv, glob, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "mirror", "impl", "test"))
import rows_mi  # noqa: E402  (imports rows_rs)
rows_rs = rows_mi.rows_rs

MONO = re.compile(r"\bmono_ms=([0-9.]+)")
DEAD = re.compile(r"GIN/TS: rank (\d+): rank (\d+) judged dead \(cause=([^)]*)\)")
STALLED = re.compile(r"GIN/RC: rank (\d+): rank (\d+) \(incarnation \d+\) judged stalled \(.*?\b(STALL_HELPER|STALL)\b")
CLOSED = re.compile(r"GIN/TS: rank (\d+): socket to rank (\d+) closed cause=(\S+)")
PAGEUP = re.compile(r"GIN/RC: rank (\d+): status page up \(\d+ B in use, probe_ms=\d+ stall_ms=\d+ W=(\d+)\)")
CONF_OPEN = re.compile(r"GIN/RC: rank (\d+): confirm window for rank (\d+) opened by (FIN|RST) W=(\d+)")
CONF_CLOSE = re.compile(r"GIN/RC: rank (\d+): confirm window for rank (\d+) closed: (alive|STALE|NORESP|REMACC|unconfirmed)")
SUSPECT = re.compile(r"GIN/RC: rank (\d+): rank (\d+) suspected \(kind=(\w+) stale_ms=([0-9.]+)\)")
PROBESUM = re.compile(r"GIN/RC: rank (\d+): probe summary peer=(\d+) (.*)$")
WITLOST = re.compile(r"GIN/RC: rank (\d+): witness of rank (\d+) lost; liveness alive")
FENCING = re.compile(r"GIN/RC: rank (\d+): rank (\d+) \(incarnation (\d+)\) fence FENCING\b")
FENCEDL = re.compile(r"GIN/RC: rank (\d+): rank (\d+) \(incarnation (\d+)\) fence FENCED\b")
WINCHG = re.compile(r"GIN/RC: rank (\d+): window check after the (?:fence|judgement) of rank (\d+): changed=(\d+)")
CTRLSUM = re.compile(r"GIN/RC: rank (\d+): control summary (.*)$")
RINGSUM = re.compile(r"GIN/RC: rank (\d+): ring summary peer=(\d+) (.*)$")
PAIRSENT = re.compile(r"GIN/RC: rank (\d+): PAIR\(record, gen (\d+)\) to rank (\d+)")
REPAIRED = re.compile(r"GIN/RC: rank (\d+): (record QP|liveness READ QP) to rank (\d+) re-paired \(gen (\d+)\)")
REJOINED = re.compile(r"GIN/RS: rank (\d+): rank (\d+)'s spare rejoined as incarnation")
REJOIN_RESENT = re.compile(r"GIN/RC: rank (\d+): REJOIN to rank (\d+) resent \(try (\d+)\)")
FAIL_SPARE = re.compile(r"GIN/RS: spare rank \d+: rank \d+ answered the REJOIN with \S+: it is gone")
SW_DIE_RST = re.compile(r"GIN/TS: rank (\d+): test switch DIE_RST:")
SW_RST_GAP = re.compile(r"GIN/TS: rank (\d+): test switch RST_GAP:")
SW_FDHOLD = re.compile(r"GIN/TS: rank (\d+): test switch FD_HOLDER=(sock|uverbs): child gin_fdhold pid=(\d+)")
SW_FREEZE = re.compile(r"GIN/RC: rank (\d+): test switch FREEZE_PAGE=")
SW_QPERR = re.compile(r"GIN/RC: rank (\d+): test switch QP_ERR: record QP to rank (\d+) moved to ERR")
SW_CREDIT = re.compile(r"GIN/RC: rank (\d+): test switch CREDIT_STALL:")
SW_DROPUD = re.compile(r"GIN/RC: rank (\d+): test switch DROP_UD: the REJOIN datagram to rank (\d+) dropped")
MUTE_ON = re.compile(r"GIN/TS: TEST socket mute on rank=(\d+)")
MUTE_OFF = re.compile(r"GIN/TS: TEST socket mute off rank=(\d+)")
RECONNECT = re.compile(r"GIN/TS: .*\breconnect")
STABLE_ANY = re.compile(r"GIN/RS: rank (\d+): checkpoint \d+ stable\b")
VOID_ANY = re.compile(r"GIN/RS: rank (\d+): checkpoint \d+ is void")
HOLD_OF = re.compile(r"GIN/RS: rank (\d+): hold of rank (\d+) started")
PUB_OF = re.compile(r"GIN/RS: rank \d+: restore round with rank (\d+) published")
RESTORED_OF = re.compile(r"GIN/RS: rank \d+: rank (\d+) restored as incarnation")
GIVEN_UP_OF = re.compile(r"GIN/RS: rank \d+: the restore of rank (\d+) \(incarnation \d+\) is given up")
KILLED = re.compile(r"GINRS killed rank=(\d+) node=(\w+) pid=\d+(?: which=(\w+))?")
STOPL = re.compile(r"GINRS stop rank=(\d+) pid=\d+ stop_ms=([0-9.]+)")
CONTL = re.compile(r"GINRS cont rank=(\d+) pid=\d+ present=([01]) stopped_ms=([0-9.]+)")
DUTYL = re.compile(r"GINRS duty start rank=(\d+)")
# the launcher (GIN/LA: node N: ...)
LA_EXITED = re.compile(r"GIN/LA: node \d+: rank (\d+) incarnation \d+ EXITED\b")
LA_SILENT = re.compile(r"GIN/LA: node \d+: rank (\d+) incarnation \d+ exited; EXITED not sent")
LA_SIGKILL = re.compile(r"GIN/LA: node \d+: FENCE of rank (\d+) incarnation \d+ from rank \d+: SIGKILL sent")
LA_FENCED = re.compile(r"GIN/LA: node \d+: rank (\d+) incarnation \d+ FENCED: (?:the group ended ([0-9.]+) ms after SIGKILL)?")
LA_ACT = re.compile(r"GIN/LA: node \d+: activation of rank (\d+) incarnation -?\d+ for rank \d+: (LATER|ACCEPTED|REFUSED) \((.*)\)")
LA_STOP = re.compile(r"\(STOP_launcher")
LA_REFSIG = re.compile(r"refused to signal")
LA_PIDMIS = re.compile(r"the pidfd is not the peer's process")
LA_QPLOST = re.compile(r"GIN/LA: node \d+: (?:record QP of rank (\d+)\b.*\blost|liveness-READ QP of rank (\d+) failed)")
LA_LEAVING = re.compile(r"GIN/LA: node \d+: rank \d+ incarnation \d+ is leaving")
GATE = re.compile(r"gate_fenced trial (\d+): old GO at ([0-9.]+) ms, FENCED GO at ([0-9.]+) ms \(diff ([0-9.-]+) ms, second thread ([0-9.]+) ms\)")
KVTOK = rows_rs.KVTOK

STRONG_CONFIRM = ("FIN+STALE", "FIN+NORESP", "REMACC+FIN")
STRONG = set(STRONG_CONFIRM) | {"EXITED", "NORESP", "STALL", "STALL_HELPER", "LINKDOWN"}

GC_COLS = ["subject", "n_surv", "ctrl", "witness_cfg", "fence_cfg", "confirm_w_ms", "n_judge", "n_judge_confirm",
           "n_judge_exited", "n_judge_noresp", "n_judge_stall", "n_judge_stall_helper", "n_judge_linkdown", "judge_causes",
           "weak_cause_n", "timeout_judge_n", "judge_any_n", "fin_judge_dev_min_ms", "fin_judge_dev_max_ms", "n_rst_surv",
           "n_rst_confirm", "n_rst_exited", "rst_judge_dev_min_ms", "rst_judge_dev_max_ms", "rst_exited_kill_judge_min_ms",
           "rst_exited_kill_judge_max_ms", "rst_judge_ms_min", "rst_judge_ms_max", "kill_judge_ms_min", "kill_judge_ms_max",
           "kill_judge_exited_min_ms", "kill_judge_exited_max_ms", "kill_judge_clock", "stop_judge_ms_min",
           "stop_judge_ms_max", "judge_spread_ms", "judge_to_publish_ms", "kill_to_publish_ms", "hold_ms_max",
           "hold_other_n", "kill_hold_ms_min", "end_after_kill_ms", "suspect_n", "suspect_stale_ms_min",
           "suspect_stale_ms_max", "read_n", "read_ok_n", "read_success_pct", "read_lat_med_us_max", "read_lat_max_us",
           "beat_gap_max_ms", "page_torn_n", "witness_lost_n", "confirm_alive_n", "fence_sent", "fenced", "fence_order_ok",
           "fence_names_ok", "fence_sent_to_fenced_ms", "fenced_to_fallback_ms", "cont_target_present",
           "win_changed_after", "la_exited_n", "la_exit_silent_n", "la_fence_sigkill_n", "la_fenced_n",
           "la_fenced_after_sigkill_ms", "la_later_n", "la_act_refused_why", "la_stop_n", "la_refused_signal_n",
           "la_pid_mismatch_n", "la_qp_err_n", "launcher_same", "launcher_ready", "tcp_ctrl_bytes", "tcp_data_bytes",
           "tcp_ctrl_conn_n", "witness_pairs", "rec_lost_n", "rec_dup_n", "rec_repair_n", "sendq_deferred", "sendq_max",
           "rnr_n", "async_n", "active_mtu_kv_min", "active_mtu_rain", "active_mtu_sunny", "ckpt_stable_in_mute",
           "ckpt_void_in_mute", "helper_reconnect_n", "qperr_pair_sent_by_target", "qperr_rec_gen_delta",
           "qperr_probe_gen_delta", "qperr_pair_read_fail", "qperr_records_after", "rejoin_dropped", "rejoin_resent",
           "rejoin_accept_n", "rejoin_accept_dup_n", "fail_to_spare_n", "inject", "inject_ok", "inject_off_ms",
           "inject_dur_off_ms", "kill2_after_armed", "stable_between_pair_kills", "old_go_ms", "fenced_go_ms",
           "gate_diff_ms", "second_thread_ms"]


def mono(l):
    m = MONO.search(l)
    return float(m.group(1)) if m else None


def node_of(r):
    return "rain" if r % 2 == 0 else "sunny"


def kvd(text):
    return {k: v for k, v in KVTOK.findall(text)}


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def r1(x):
    return "" if x is None else round(x, 3)


def mm(vals):
    v = [x for x in vals if x is not None]
    return (r1(min(v)), r1(max(v))) if v else ("", "")


class Ev:
    """one stamped line: receipt time t (s), mono (ms) or None, node, text"""
    __slots__ = ("t", "m", "node", "text")

    def __init__(self, t, m, node, text):
        self.t, self.m, self.node, self.text = t, m, node, text


def evs(lines, node):
    return [Ev(t, mono(l), node, l) for t, l in lines if t is not None]


def xdiff(a, b):
    """ms from event a to event b: mono when both are on one node and carry mono_ms, else the receipt clock"""
    if a is None or b is None:
        return None, ""
    if a.node == b.node and a.m is not None and b.m is not None:
        return b.m - a.m, "mono"
    return (b.t - a.t) * 1000.0, "receipt"


def first(evl, rx, pred=None):
    for e in sorted(evl, key=lambda x: x.t):
        m = rx.search(e.text)
        if m and (pred is None or pred(m)):
            return e, m
    return None, None


def gc_overlay(stem, base, meta):
    n = int(base.get("n") or 4)
    ranks = list(range(n))
    out = {c: "" for c in GC_COLS}
    subj = meta.get("subject_rank", "")
    s = int(subj) if str(subj).isdigit() else -1
    out["subject"] = subj
    lib = meta.get("lib", base.get("build", ""))
    ctrl = meta.get("ctrl") or ("rdma" if lib in ("gc", "gcp") else "tcp")
    out["ctrl"] = ctrl
    out["witness_cfg"] = meta.get("witness", "")
    out["fence_cfg"] = meta.get("fence", "")
    kr = int(meta["kill_rank"]) if str(meta.get("kill_rank", "")).isdigit() else -1
    kr2 = int(meta["kill2_rank"]) if str(meta.get("kill2_rank", "")).isdigit() else -1
    logs = {r: evs(rows_rs.stamped("%s_r%d.log" % (stem, r)), node_of(r)) for r in ranks}
    sp_node = node_of(int(meta["spare_rank"])) if str(meta.get("spare_rank", "")).isdigit() else node_of(max(kr, 0))
    slog = evs(rows_rs.stamped(stem + "_spare.log"), sp_node)
    slog2 = evs(rows_rs.stamped(stem + "_spare_2nd.log"), node_of(kr2) if kr2 >= 0 else "rain")
    kout = evs(rows_rs.stamped(stem + "_kill.out"), "?")
    for e in kout:
        m = re.search(r"node=(\w+)", e.text)
        e.node = m.group(1) if m else "?"
    inj = evs(rows_rs.stamped(stem + "_inject.out"), node_of(s) if s >= 0 else "?")
    lalog = {nd: evs(rows_rs.stamped("%s_launcher_%s.log" % (stem, nd)), nd) for nd in ("rain", "sunny")}
    every = [e for r in ranks for e in logs[r]] + slog + slog2
    surv = [r for r in ranks if r != s] if s >= 0 else []
    out["n_surv"] = len(surv) if s >= 0 else ""
    # W
    ws = [int(m.group(2)) for e in every for m in [PAGEUP.search(e.text)] if m]
    out["confirm_w_ms"] = max(ws) if ws else (fnum(meta.get("confirm_ms")) if meta.get("confirm_ms") else "")
    W = out["confirm_w_ms"] if out["confirm_w_ms"] != "" else None
    # the kill: the runner's line for the subject (first), the library's DIE_RST line, the driver's die line
    t_kill_ev = None
    if s >= 0:
        e, _ = first(kout, KILLED, lambda m: int(m.group(1)) == s)
        e2, _ = first(logs[s], SW_DIE_RST)
        e3, _ = first(kout + logs[s], re.compile(r"GINRS die rank=%d\b" % s))
        e4, _ = first(logs[s], rows_rs.DIE_CKPT)
        cands = [x for x in (e, e2, e3, e4) if x is not None]
        t_kill_ev = min(cands, key=lambda x: x.t) if cands else None
    # judgements
    every_dead = [(e, m) for e in every for m in [DEAD.search(e.text)] if m]
    every_stall = [(e, m) for e in every for m in [STALLED.search(e.text)] if m]
    out["judge_any_n"] = len(every_dead) + len(every_stall)
    if ctrl == "rdma":
        out["weak_cause_n"] = sum(1 for _, m in every_dead if m.group(3) not in STRONG)
    out["timeout_judge_n"] = sum(1 for _, m in every_dead if "TIMEOUT" in m.group(3).upper() and "+" not in m.group(3))
    js = {}  # survivor -> (event, cause)
    for r in surv:
        lg = logs[r] if not (r == kr and kr2 >= 0) else slog
        cand = [(e, m.group(3)) for e in lg for m in [DEAD.search(e.text)] if m and int(m.group(2)) == s]
        cand += [(e, m.group(3)) for e in lg for m in [STALLED.search(e.text)] if m and int(m.group(2)) == s]
        if cand:
            js[r] = min(cand, key=lambda x: x[0].t)
    if s >= 0:
        cause = lambda c: [r for r, (_, k) in js.items() if k == c]
        out["n_judge"] = len(js)
        out["n_judge_confirm"] = sum(1 for _, (_, k) in js.items() if k in STRONG_CONFIRM)
        out["n_judge_exited"] = len(cause("EXITED"))
        out["n_judge_noresp"] = len(cause("NORESP"))
        out["n_judge_stall"] = len(cause("STALL"))
        out["n_judge_stall_helper"] = len(cause("STALL_HELPER"))
        out["n_judge_linkdown"] = len(cause("LINKDOWN"))
        out["judge_causes"] = "+".join("%s:%d" % (c, sum(1 for _, (_, k) in js.items() if k == c))
                                       for c in sorted({k for _, (_, k) in js.items()}))

        def opener(r, je):
            lg = logs[r]
            o = [e for e in lg for m in [CONF_OPEN.search(e.text)] if m and int(m.group(2)) == s and e.t <= je.t]
            if o:
                return max(o, key=lambda x: x.t)
            c = [e for e in lg for m in [CLOSED.search(e.text)] if m and int(m.group(2)) == s and e.t <= je.t
                 and m.group(3) in ("FIN", "ECONNRESET", "RST")]
            return max(c, key=lambda x: x.t) if c else None
        devs = []
        for r, (je, k) in js.items():
            if k in STRONG_CONFIRM:
                o = opener(r, je)
                d, _ = xdiff(o, je)
                devs.append(None if (d is None or W is None) else d - W)
        out["fin_judge_dev_min_ms"], out["fin_judge_dev_max_ms"] = mm(devs) if devs else ("", "")
        # RST survivors
        rst = {}
        for r in surv:
            c = [e for e in logs[r] for m in [CLOSED.search(e.text)] if m and int(m.group(2)) == s
                 and m.group(3) in ("ECONNRESET", "RST")]
            if c:
                rst[r] = min(c, key=lambda x: x.t)
        out["n_rst_surv"] = len(rst)
        rc_dev, re_k, rj = [], [], []
        nrc = nre = 0
        for r, re_ev in rst.items():
            if r not in js:
                rj.append(None)
                continue
            je, k = js[r]
            d, _ = xdiff(re_ev, je)
            rj.append(d)
            if k in STRONG_CONFIRM:
                nrc += 1
                rc_dev.append(None if (d is None or W is None) else d - W)
            elif k == "EXITED":
                nre += 1
                re_k.append(xdiff(t_kill_ev, je)[0])
        out["n_rst_confirm"], out["n_rst_exited"] = nrc, nre
        out["rst_judge_dev_min_ms"], out["rst_judge_dev_max_ms"] = mm(rc_dev) if rc_dev else ("", "")
        out["rst_exited_kill_judge_min_ms"], out["rst_exited_kill_judge_max_ms"] = mm(re_k) if re_k else ("", "")
        out["rst_judge_ms_min"], out["rst_judge_ms_max"] = mm(rj) if rj else ("", "")
        # kill -> judgement
        if t_kill_ev is not None and js:
            ds = {r: xdiff(t_kill_ev, je) for r, (je, _) in js.items()}
            out["kill_judge_ms_min"], out["kill_judge_ms_max"] = mm([d for d, _ in ds.values()])
            ex = [ds[r][0] for r, (_, k) in js.items() if k == "EXITED"]
            out["kill_judge_exited_min_ms"], out["kill_judge_exited_max_ms"] = mm(ex) if ex else ("", "")
            out["kill_judge_clock"] = "+".join(sorted({c for _, c in ds.values()}))
        # stop / freeze -> STALLED
        st_ev, _ = first(inj, STOPL, lambda m: int(m.group(1)) == s)
        if st_ev is None:
            st_ev, _ = first(logs[s], SW_FREEZE)
        if st_ev is not None:
            sj = [xdiff(st_ev, je)[0] for r, (je, k) in js.items() if k in ("STALL", "STALL_HELPER")]
            out["stop_judge_ms_min"], out["stop_judge_ms_max"] = mm(sj) if sj else ("", "")
        if js:
            ts = [je.t for je, _ in js.values()]
            out["judge_spread_ms"] = r1((max(ts) - min(ts)) * 1000.0)
            t_j0 = min(ts)
            pubs = []
            for r in surv:
                lg = logs[r] if not (r == kr and kr2 >= 0) else slog
                p = [e.t for e in lg for m in [PUB_OF.search(e.text)] if m and int(m.group(1)) == s and e.t >= t_j0]
                pubs.append(min(p) if p else None)
            if pubs and all(p is not None for p in pubs):
                out["judge_to_publish_ms"] = r1((max(pubs) - t_j0) * 1000.0)
                if t_kill_ev is not None:
                    out["kill_to_publish_ms"] = r1((max(pubs) - t_kill_ev.t) * 1000.0)
        # holds
        hms, hother, hk = [], 0, []
        for r in ranks:
            lg = logs[r]
            for e in lg:
                m = HOLD_OF.search(e.text)
                if not m:
                    continue
                p = int(m.group(2))
                if p != s:
                    hother += 1
                    continue
                if t_kill_ev is not None:
                    hk.append((e.t - t_kill_ev.t) * 1000.0)
                ends = [x.t for x in lg for mm2 in [RESTORED_OF.search(x.text) or GIVEN_UP_OF.search(x.text)]
                        if mm2 and int(mm2.group(1)) == p and x.t >= e.t]
                end = min(ends) if ends else (max(x.t for x in lg) if lg else e.t)
                hms.append((end - e.t) * 1000.0)
        out["hold_ms_max"] = r1(max(hms)) if hms else 0
        out["hold_other_n"] = hother
        out["kill_hold_ms_min"] = r1(min(hk)) if hk else ""
        if t_kill_ev is not None:
            last = max((e.t for r in surv for e in logs[r]), default=None)
            out["end_after_kill_ms"] = r1((last - t_kill_ev.t) * 1000.0) if last is not None else ""
        # the fence (the buddy's lines)
        b = s ^ 1
        blog = slog if (b == kr and kr2 == s) else logs.get(b, [])
        fe, _ = first(blog, FENCING, lambda m: int(m.group(2)) == s)
        fd, _ = first(blog, FENCEDL, lambda m: int(m.group(2)) == s)
        ac, _ = first(blog, rows_rs.ACTIVATED, lambda m: int(m.group(1)) == s)
        gu, _ = first(blog, GIVEN_UP_OF, lambda m: int(m.group(1)) == s)
        any_fence = any(FENCING.search(e.text) or FENCEDL.search(e.text) for e in every)
        out["fence_sent"], out["fenced"] = int(fe is not None), int(fd is not None)
        out["fence_order_ok"] = int(fd is not None and ac is not None and (fe is None or fe.t <= fd.t) and fd.t <= ac.t)
        out["fence_names_ok"] = int(fe is not None and fd is not None)
        out["fence_sent_to_fenced_ms"] = r1(xdiff(fe, fd)[0]) if (fe is not None and fd is not None) else ""
        out["fenced_to_fallback_ms"] = r1(xdiff(fd, gu)[0]) if (fd is not None and gu is not None) else ""
        if not any_fence:  # no fence line in the trial at all: the library does not emit them yet (TODO(p3))
            for c in ("fence_sent", "fenced", "fence_order_ok", "fence_names_ok"):
                out[c] = ""
        ce, cm = first(inj, CONTL, lambda m: int(m.group(1)) == s)
        out["cont_target_present"] = int(cm.group(2)) if cm else ""
        # the launcher
        la = lalog["rain"] + lalog["sunny"]
        if la:
            out["la_exited_n"] = sum(1 for e in la for m in [LA_EXITED.search(e.text)] if m and int(m.group(1)) == s)
            out["la_exit_silent_n"] = sum(1 for e in la for m in [LA_SILENT.search(e.text)] if m and int(m.group(1)) == s)
            out["la_fence_sigkill_n"] = sum(1 for e in la for m in [LA_SIGKILL.search(e.text)] if m and int(m.group(1)) == s)
            fz = [m for e in la for m in [LA_FENCED.search(e.text)] if m and int(m.group(1)) == s]
            out["la_fenced_n"] = len(fz)
            fz_ms = [fnum(m.group(2)) for m in fz if m.group(2)]
            out["la_fenced_after_sigkill_ms"] = max(fz_ms) if fz_ms else ""
            acts = [m for e in la for m in [LA_ACT.search(e.text)] if m and int(m.group(1)) == s]
            out["la_later_n"] = sum(1 for m in acts if m.group(2) == "LATER")
            out["la_act_refused_why"] = "; ".join(m.group(3) for m in acts if m.group(2) == "REFUSED")
    # every trial: the launcher's STOP lines, checks, QP loss
    la = lalog["rain"] + lalog["sunny"]
    if la or ctrl == "rdma":
        out["la_stop_n"] = sum(1 for e in la if LA_STOP.search(e.text))
        out["la_refused_signal_n"] = sum(1 for e in la if LA_REFSIG.search(e.text))
        out["la_pid_mismatch_n"] = sum(1 for e in la if LA_PIDMIS.search(e.text))
        t_leave = min((e.t for e in la if LA_LEAVING.search(e.text)), default=float("inf"))
        out["la_qp_err_n"] = sum(1 for e in la for m in [LA_QPLOST.search(e.text)] if m and e.t < t_leave
                                 and int(m.group(1) or m.group(2)) != s)
    if ctrl == "rdma":
        same = True
        for nd in ("rain", "sunny"):
            bf, af = meta.get("launcher_before_" + nd, ""), meta.get("launcher_after_" + nd, "")
            key = lambda x: ",".join(p for p in x.split(",") if p.startswith(("pid=", "start=")))
            same = same and bool(bf) and key(bf) == key(af) and "alive=1" in af
        out["launcher_same"] = int(same)
        out["launcher_ready"] = int(meta.get("launcher_ready") == "1")
    # the READ probe and the control summaries (every process)
    ps = [(int(m.group(1)), int(m.group(2)), kvd(m.group(3))) for e in every for m in [PROBESUM.search(e.text)] if m]
    if ps:
        g = lambda k: [fnum(d.get(k)) for _, _, d in ps if fnum(d.get(k)) is not None]
        out["read_n"], out["read_ok_n"] = int(sum(g("reads"))), int(sum(g("ok")))
        out["read_success_pct"] = r1(100.0 * out["read_ok_n"] / out["read_n"]) if out["read_n"] else ""
        out["read_lat_med_us_max"] = max(g("lat_med_us")) if g("lat_med_us") else ""
        out["read_lat_max_us"] = max(g("lat_max_us")) if g("lat_max_us") else ""
        out["beat_gap_max_ms"] = max(g("beat_gap_max_ms")) if g("beat_gap_max_ms") else ""
        out["page_torn_n"] = int(sum(g("torn")))
    # the page-dependent counts: empty when no process brought its status page up (the library does not run it yet)
    if ws:
        sus = [fnum(m.group(4)) for e in every for m in [SUSPECT.search(e.text)] if m and (s < 0 or int(m.group(2)) == s)]
        out["suspect_n"] = len(sus)
        out["suspect_stale_ms_min"], out["suspect_stale_ms_max"] = mm(sus) if sus else ("", "")
        out["witness_lost_n"] = sum(1 for e in every if WITLOST.search(e.text))
        out["confirm_alive_n"] = sum(1 for e in every for m in [CONF_CLOSE.search(e.text)] if m and m.group(3) == "alive")
    wc = [int(m.group(3)) for e in every for m in [WINCHG.search(e.text)] if m]
    out["win_changed_after"] = sum(wc) if wc else ""
    cs = [kvd(m.group(2)) for e in every for m in [CTRLSUM.search(e.text)] if m]
    if cs:
        sm = lambda k: int(sum(fnum(d.get(k)) or 0 for d in cs))
        out["tcp_record_bytes_sum"] = sm("tcp_record_bytes")
        out["tcp_data_bytes"] = sm("tcp_data_bytes")
        out["tcp_ctrl_bytes"] = sm("tcp_record_bytes") + sm("tcp_data_bytes")
        out["tcp_ctrl_conn_n"] = sm("tcp_conns")
        out["witness_pairs"] = sm("witness_conns") if meta.get("witness", "1") != "0" else 0
        for c, k in (("rec_lost_n", "records_lost"), ("rec_dup_n", "records_dup"), ("rec_repair_n", "repairs"),
                     ("sendq_deferred", "sendq_deferred"), ("async_n", "async")):
            out[c] = sm(k)
        out["sendq_max"] = int(max(fnum(d.get("sendq_max")) or 0 for d in cs))
        port = 0
        for nd in ("rain", "sunny"):
            b0, a0 = fnum(meta.get("rnr_before_" + nd)), fnum(meta.get("rnr_after_" + nd))
            if b0 is not None and a0 is not None:
                port += int(a0 - b0)
        out["rnr_n"] = sm("rnr") + port
        mtus = [fnum(d.get("active_mtu")) for d in cs if fnum(d.get("active_mtu")) is not None]
    else:
        mtus = []
    kvm = [fnum(rows_rs.parse_kv("%s_r%d.kv" % (stem, r)).get("active_mtu")) for r in ranks]
    kvm = [x for x in kvm if x is not None] or mtus
    out["active_mtu_kv_min"] = int(min(kvm)) if kvm else ""
    for nd in ("rain", "sunny"):
        v = fnum(meta.get("active_mtu_" + nd))
        out["active_mtu_" + nd] = int(v) if v is not None else ""
    # the socket mute window (gin-harden's lines)
    mon = [e for e in every if MUTE_ON.search(e.text)]
    if mon:
        t0 = min(e.t for e in mon)
        moff = [e.t for e in every if MUTE_OFF.search(e.text) and e.t >= t0]
        t1 = min(moff) if moff else t0 + 8.0
        out["ckpt_stable_in_mute"] = sum(1 for e in every if STABLE_ANY.search(e.text) and t0 <= e.t <= t1)
        out["ckpt_void_in_mute"] = sum(1 for e in every if VOID_ANY.search(e.text) and t0 <= e.t <= t1)
    out["helper_reconnect_n"] = sum(1 for e in every if RECONNECT.search(e.text))
    # the record-QP error cell
    qe = [(int(m.group(1)), int(m.group(2))) for e in every for m in [SW_QPERR.search(e.text)] if m]
    if qe:
        T, P = qe[0]
        out["qperr_pair_sent_by_target"] = int(any(int(m.group(1)) == T and int(m.group(3)) == P
                                                   for e in logs[T] for m in [PAIRSENT.search(e.text)] if m))
        gens = [int(m.group(4)) for e in logs[T] for m in [REPAIRED.search(e.text)]
                if m and m.group(2) == "record QP" and int(m.group(3)) == P]
        out["qperr_rec_gen_delta"] = max(gens) if gens else 0
        out["qperr_probe_gen_delta"] = sum(1 for q, o in ((T, P), (P, T)) for e in logs[q] for m in [REPAIRED.search(e.text)]
                                           if m and m.group(2) == "liveness READ QP" and int(m.group(3)) == o)
        pf = [kvd(m.group(3)) for q, o in ((T, P), (P, T)) for e in logs[q] for m in [PROBESUM.search(e.text)]
              if m and int(m.group(2)) == o]
        out["qperr_pair_read_fail"] = int(sum((fnum(d.get("remacc")) or 0) + (fnum(d.get("noresp")) or 0) +
                                              (fnum(d.get("timeout")) or 0) for d in pf)) if pf else ""
        rs_ = [kvd(m.group(3)) for e in logs[T] for m in [RINGSUM.search(e.text)] if m and int(m.group(2)) == P]
        out["qperr_records_after"] = int(sum(fnum(d.get("received")) or 0 for d in rs_ if (fnum(d.get("gen")) or 0) >= 1)) if rs_ else ""
    # REJOIN
    if s >= 0 and (slog or kr >= 0):
        out["rejoin_dropped"] = sum(1 for e in slog if SW_DROPUD.search(e.text))
        rr = [int(m.group(3)) for e in slog for m in [REJOIN_RESENT.search(e.text)] if m]
        out["rejoin_resent"] = sum(1 for x in rr if x >= 2) if (rr or out["rejoin_dropped"]) else ""
        per = [sum(1 for e in logs[r] for m in [REJOINED.search(e.text)] if m and int(m.group(2)) == s) for r in surv]
        out["rejoin_accept_n"] = sum(1 for x in per if x >= 1)
        out["rejoin_accept_dup_n"] = sum(max(0, x - 1) for x in per)
        out["fail_to_spare_n"] = sum(1 for e in slog if FAIL_SPARE.search(e.text))
    # the injection record
    kind = meta.get("inject", "")
    out["inject"] = kind
    plan = fnum(meta.get("inj_plan_rt"))
    rk = None
    if kind in ("kill_traffic", "fd_holder_kill", "kill_spare_then_rank") and s >= 0:
        ev, _ = first(kout, KILLED, lambda m: int(m.group(1)) == s and (m.group(3) or "first") in ("first", "after_spare"))
        ok = ev is not None
        if kind == "fd_holder_kill":
            ok = ok and first(logs[s], SW_FDHOLD)[0] is not None
        if kind == "kill_spare_then_rank":
            ok = ok and bool([e for e in rows_rs.stamped(stem + "_spare_kill.out") if e[0] is not None and "GINRS killed" in e[1]])
        out["inject_ok"] = int(ok)
        rk = ev
    elif kind == "sigstop" and s >= 0:
        ev, _ = first(inj, STOPL, lambda m: int(m.group(1)) == s)
        out["inject_ok"] = int(ev is not None and first(inj, CONTL)[0] is not None)
        rk = ev
        _, cm = first(inj, CONTL, lambda m: int(m.group(1)) == s)
        if cm and fnum(meta.get("stop_ms")) is not None:
            out["inject_dur_off_ms"] = r1(abs(float(cm.group(3)) - float(meta["stop_ms"])))
    elif kind == "duty" and s >= 0:
        rk, _ = first(inj, DUTYL, lambda m: int(m.group(1)) == s)
        out["inject_ok"] = int(rk is not None)
    elif kind == "kill_self" and s >= 0:
        out["inject_ok"] = int(first(logs[s], SW_DIE_RST)[0] is not None)
    else:
        envs = " ".join(meta.get(k, "") for k in ("r0_env", "r1_env", "r2_env", "r3_env", "spare_env"))
        need = [(sw, rx) for sw, rx in (("TEST_RST_GAP", SW_RST_GAP), ("TEST_FREEZE_PAGE", SW_FREEZE), ("TEST_QP_ERR", SW_QPERR),
                                        ("TEST_CREDIT_STALL", SW_CREDIT), ("TEST_DROP_UD", SW_DROPUD), ("TEST_SOCK_MUTE", MUTE_ON))
                if sw in envs]
        if need:
            out["inject_ok"] = int(all(any(rx.search(e.text) for e in every) for _, rx in need))
    if rk is not None and plan is not None:
        out["inject_off_ms"] = r1(abs(rk.t - plan) * 1000.0)
    # the second kill by recorded PID after armed
    if meta.get("kill2_kind") == "pid_after_armed" and kr2 >= 0:
        e2, _ = first(kout, KILLED, lambda m: int(m.group(1)) == kr2 and m.group(3) == "second")
        a2 = fnum(meta.get("armed2_rt"))
        out["kill2_after_armed"] = int(e2 is not None and a2 is not None and e2.t >= a2)
    # the spare-absent cell: a stable checkpoint of the subject between the spare kill and its kill
    if kind == "kill_spare_then_rank" and s >= 0:
        sk = [t for t, l in rows_rs.stamped(stem + "_spare_kill.out") if t is not None and "GINRS killed" in l]
        ev, _ = first(kout, KILLED, lambda m: int(m.group(1)) == s)
        if sk and ev is not None:
            out["stable_between_pair_kills"] = int(any(e.t > min(sk) and e.t < ev.t for e in every
                                                       for m in [STABLE_ANY.search(e.text)] if m and int(m.group(1)) == s))
    return out


def gate_rows(R):
    rows = []
    for p in sorted(glob.glob(os.path.join(R, "local", "gate_fenced*.log"))):
        for line in open(p, errors="replace"):
            m = GATE.search(line)
            if not m:
                continue
            o, f, d, l2 = float(m.group(2)), float(m.group(3)), float(m.group(4)), float(m.group(5))
            rid = "%s_t%s" % (os.path.basename(p)[:-4], m.group(1))
            r = {"id": rid, "stem": os.path.join(os.path.dirname(p), rid), "sub": "local", "cell": "gate_fenced",
                 "build": "cpu", "runner": "local", "key": "local:gate_fenced", "old_go_ms": o, "fenced_go_ms": f,
                 "gate_diff_ms": d, "second_thread_ms": l2, "tnum": int(m.group(1)) + 1}
            rows.append(r)
    return rows


def all_rows(R):
    rows = []
    for sub in sorted(os.listdir(R)):
        p = os.path.join(R, sub)
        if not os.path.isdir(p) or sub in ("local", "launcher"):
            continue
        for meta_p in sorted(glob.glob(os.path.join(p, "*_meta.txt"))):
            stem = meta_p[: -len("_meta.txt")]
            m = rows_rs.read_meta(stem)
            runner = m.get("runner", "")
            if runner in ("costgc", "cost", "costmi") or sub.startswith("cost"):
                r = rows_rs.cost_row(stem, sub)
                r.update(rows_mi.cost_overlay(stem, r))
                r["runner"] = "cost"
                r["key"] = "cost_%s_%s@%s" % (r["metric"], r["arm"], r["lib"])
            elif runner == "mrr" or sub.startswith("reg"):
                r = rows_rs.reg_row(stem, sub)
                r["key"] = "%s@%s" % (r["cell"], r["build"])
                r["lineage_warn"] = rows_mi.reg_lineage_warn(stem)
            else:
                r = rows_rs.rs_row(stem, sub)
                r.update(rows_mi.mi_overlay(stem, r, m))
                r.update(gc_overlay(stem, r, m))
                r["runner"] = "gcr"
                r["key"] = "%s@%s" % (r["cell"], r["build"])
                r["hold"] = m.get("hold", "")
            mt = re.search(r"_[nk](\d+)$", r["id"])
            r["tnum"] = int(mt.group(1)) if mt else 0
            rows.append(r)
    if os.path.isdir(os.path.join(R, "local")):
        rows += gate_rows(R)
    return rows


def columns(rows):
    cols = list(rows_rs.RS_COLS) + rows_mi.MI_COLS + GC_COLS
    for r in rows:
        for c in r:
            if c not in cols:
                cols.append(c)
    return cols


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    rows = all_rows(os.path.abspath(a.results))
    out = a.out or os.path.join(os.path.abspath(a.results), "trials.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns(rows), extrasaction="ignore", restval="")
        w.writeheader()
        for r in sorted(rows, key=lambda x: (x["sub"], x["key"], x["tnum"])):
            w.writerow(r)
    print("%s: %d trial(s)" % (out, len(rows)))


if __name__ == "__main__":
    main()
