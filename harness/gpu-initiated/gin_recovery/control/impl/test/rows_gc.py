#!/usr/bin/env python3
"""rows_gc.py - gin-control, test side: one row per trial from the raw files (../../EXPERIMENT.md 9.3 and 9.8's columns,
section 3's search keys). gin-mirror's rows_mi.py (imported, UNCHANGED) gives gin-restore's and gin-mirror's columns; this file
adds the control-path columns. Standard library only.

    rows_gc.py <results dir> [--out trials.csv]     one row per trial (raw/, reg/, cost*/, local/)
    rows_gc.py --stops <stem>                       one line "la_stop_n=.. la_qp_err_n=.. la_refused_signal_n=..
                                                    la_pid_mismatch_n=.. la_not_up=.. la_stale_n=..": the trial's launcher
                                                    counts by the scorer's rule (hold_gc.sh's per-trial STOP_launcher check;
                                                    REVIEW_TEST B4; la_not_up and la_stale_n from the meta)

Inputs: run_gc.sh's trials (raw/: <stem>_r<r>.kv/.log, _spare*.kv/.log, _kill.out, _spare_kill.out, _inject.out,
_fdhold.out, _cleanup.out, _launcher_<node>.log, _meta.txt; stem <cell>_<build>_n<k>); gin-remaining's runner (reg/);
run_cost_gc.sh (cost*/); the CPU program gate_fenced (local/gate_fenced*.log, one row per "gate_fenced trial" line). Every log
line is "<rain CLOCK_MONOTONIC at receipt, s> <line>" (the receipt clock). A library or runner line also carries its own
"mono_ms=" (the process's CLOCK_MONOTONIC). Intervals inside one process use mono_ms; intervals between two processes of one
node use their mono_ms (section 3: "같은 노드 시계"); between nodes the two mono_ms in rain's clock, sunny's less the offset
run_gc.sh measured over one ssh session (meta mono_off_sunny_ms / mono_off_after_ms; the one with the smaller round trip;
REVIEW_TEST fix 2: no ssh delay in a kill -> judgement interval); the receipt clock only when a line has no mono_ms or the
trial has no offset (the *_clock columns say which: mono, mono_xnode, receipt).
The launcher logs (<stem>_launcher_<node>.log): since 2026-10-22 each is the whole log of the trial's own launcher (EXPERIMENT 5:
one launcher per node per trial, meta launcher_scope=trial), its start, the warm spare's spawn lines, the trial_start and
trial_end markers and its shutdown; a hold-scope slice (launcher_scope=hold, earlier runs) ran from the previous trial's
trial_end marker to this trial's. The STOP, "refused to signal" and pid-check counts read the whole log, every other
launcher column of the subject only the lines after this trial's trial_start marker. The spare-absent cells (meta
launcher_respawn_max=0 with spare_kill_first=1 or kill_kind=spare_then_rank) expect one "respawn cap 0 ... reached; no more
spares (STOP_launcher)" line (the runner killed the spare and the launcher must not replace it): that one line is counted in
la_spare_cap_expected_n, not in la_stop_n. A trial whose launcher did not come up or found a stale launcher socket or process
(meta launcher_ready=0, launcher_stale=<node>:<sockets>+<processes>) has its meta only.

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
            beat_gap_max_ms=Z torn=T after_end_reads=E after_end_ok=F mono_ms=M   (at teardown, one per peer; the
            after_end_* READs came after the peer's BYE, LEFT or judgement and are left out of read_n and read_ok_n)  TODO(p1)
  WITLOST   GIN/RC: rank R: witness of rank P lost; liveness alive mono_ms=M (table row 8)           TODO(p1)
  FENCING   GIN/RC: rank R: rank P (incarnation I) fence FENCING: FENCE sent to the launcher of node N mono_ms=M   TODO(p3)
  FENCED    GIN/RC: rank R: rank P (incarnation I) fence FENCED (by FENCED|EXITED from node N) mono_ms=M        TODO(p3)
  WINCHG    GIN/RC: rank R: window check after the fence|judgement of rank P: changed=N cells mono_ms=M        TODO(p3)
  CTRLSUM   GIN/RC: rank R: control summary tcp_record_bytes=.. tcp_data_bytes=.. tcp_conns=.. witness_conns=..
            records_lost=.. records_dup=.. repairs=.. sendq_deferred=.. sendq_max=.. rnr=.. async=.. active_mtu=.. mono_ms=M
            (at teardown and at every confirmed checkpoint, every process; the last one of a process counts)  TODO(p2)
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
  ACCEPTED | REFUSED (why), "record QP of rank R ... lost", "liveness-READ QP of rank R failed", "is leaving"; the warm spare's
  "spare spawned (spawn S, incarnation I, pid P, why W, log PATH)", "spawned spare said HELLO (spawn S, incarnation I, pid P,
  hello pid Q, rank R incarnation J, after X ms)", "spawned spare exited unused (...): respawn cap M ... (STOP_launcher)"
  (../launcher/README_launcher.md "따뜻한 예비 프로세스").
  The runner's lines (run_gc.sh): GINRS killed rank=R node=N pid=P which=W [gap_ms=G] mono_ms=M; GINRS stop / cont (present=,
  stopped_ms=); GINRS duty start / end; GINRS fdhold_killed; GINRS cleanup_stopped; GINRS ss s1|s2 pid=P present= n= acked=
  received= (_ss.out); the launcher logs' markers "GINLA mark trial_start|trial_end <stem>".

Columns (empty when the lines are missing; counts are 0 when the lines exist but none matched):
  subject, n_surv            the rank under test (meta subject_rank: KILL_RANK, STOP_RANK, DUTY_RANK, or the cell's
                             SUBJECT_RANK for a library test switch) and the ranks judging it (every other rank)
  confirm_w_ms, probe_ms_page  W and the READ period of the trial (the PAGEUP lines, else meta confirm_ms)
  mono_off_used_ms, mono_off_rtt_ms, mono_off_drift_ms   the node clock offset used, its round trip, after - before
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
  hold_after_restore_n       hold starts (any rank, any subject, the spares' logs too) after the subject's first restored line
                             (a false hold at the revived rank's own end is counted here; REVIEW_TEST fix 9)
  probe_timeout_n            READ time-out lines naming the subject before that survivor's judgement
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
  launcher_scope, launcher_stale   meta: trial (one launcher per trial) or hold (earlier runs); the stale socket or process found
  la_spare_spawn_n, la_spare_respawn_n, la_spare_cap_expected_n, spare_hello_after_ms
                             the warm spares the launchers spawned (all, the respawns and HELLO retries), the expected cap line
                             of the spare-absent cells, spawn -> HELLO of the subject's spare (incarnation 1; the launcher's ms)
  spare2_inc_want, spare2_inc_got, spare2_daemon_ok   a second death (meta kill2_rank) in an rdma build: the spare the second
                             restore needs is the launcher's, incarnation 2 for the same rank (the daemon's next spare after the
                             first activation: original incarnation + 2) or 1 for another rank (that node's own warm spare);
                             got = the incarnation of the HELLO line for that rank on its node; ok = that HELLO's spawn was the
                             launcher's (why activated for 2, start for 1)
  tcp_ctrl_bytes, tcp_data_bytes, tcp_ctrl_conn_n, witness_pairs, rec_lost_n, rec_dup_n, rec_repair_n, sendq_deferred,
  sendq_max, rnr_n, async_n, active_mtu_kv_min   CTRLSUM (each process's last) summed (rnr_n adds the meta's RNR
                             port-counter growth); witness_pairs = the summed witness_conns with the witness on, 0 with it off
  witness_expected           (N - 1) x the processes with a CTRLSUM line with the witness on, 0 off: from the configuration,
                             not from the library (REVIEW_TEST fix 10)
  ss_tcp_conn_n, ss_pids_both, ss_tx_delta_bytes, ss_rx_delta_bytes   the runner's two ss snapshots of the rank PIDs: the
                             established TCP sockets at the first, the bytes acked / received between the two (pids in both)
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
  pair_gap_ms                the spare-absent cell: the runner's spare kill -> rank kill on that node's clock
  subject_fenced             1 when the runner killed nobody and the subject ended by SIGKILL (the fence): gin-restore's and
                             gin-mirror's columns then read it as the killed rank (fenced_subject)
  ckpt_stable_before_inj     a stable (or armed) checkpoint of the subject before its injection (the kill, DIE_RST, the STOP or
                             FREEZE_PAGE line); section 8's "before the first armed checkpoint" for every injected cell
  kill2_after_armed          KILL2_KIND=pid_after_armed: the second kill's receipt >= the survivors' last armed line (meta)
  stable_between_pair_kills  the spare-absent cell: a stable checkpoint of the subject between the spare kill and its kill
                             (the subject's mono_ms against the runner's on the same node)
  gate rows (local/): gate_real, old_go_ms, fenced_go_ms, gate_diff_ms, second_thread_ms, pidfd_ms, z_ms,
                             fenced_after_second_ms, fenced_vs_pidfd_abs_ms. gate_proc_gc.py's lines (a real child process: its
                             main thread ends first, a second thread 500 ms later; the harness's own pidfd and /proc readings)
                             give gate_real 1; gate_fenced.cc's simulated lines give gate_real 0 (REVIEW_TEST fix 1)
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
PAGEUP = re.compile(r"GIN/RC: rank (\d+): status page up \(\d+ B in use, probe_ms=(\d+) stall_ms=\d+ W=(\d+)\)")
TIMEOUTL = re.compile(r"GIN/RC: rank (\d+): probe of rank (\d+) timed out")
SSL = re.compile(r"GINRS ss (s1|s2) pid=(\d+) present=([01]) n=(\d+) acked=(\d+) received=(\d+)")
GAPL = re.compile(r"GINRS killed rank=(\d+) node=\w+ pid=\d+ which=after_spare gap_ms=([0-9.]+)")
LA_MARK_START = re.compile(r"GINLA mark trial_start ")
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
LA_SPAWNED = re.compile(r"GIN/LA: node \d+: spare spawned \(spawn (\d+), incarnation (\d+), pid -?\d+, why (\w+), log (\S+)\)")
LA_SPHELLO = re.compile(r"GIN/LA: node \d+: spawned spare said HELLO \(spawn (\d+), incarnation (\d+), pid -?\d+, hello pid (-?\d+), "
                        r"rank (\d+) incarnation (\d+), after ([0-9.]+) ms\)")
LA_CAP0 = re.compile(r"GIN/LA: node \d+: spawned spare exited unused \(.*\): respawn cap 0 within \d+ ms reached; no more spares "
                     r"\(STOP_launcher\)")
GATE = re.compile(r"gate_fenced trial (\d+): old GO at ([0-9.]+) ms, FENCED GO at ([0-9.]+) ms \(diff ([0-9.-]+) ms, second thread ([0-9.]+) ms\)")
GATEP = re.compile(r"gate_proc trial (\d+): (.*)$")
KVTOK = rows_rs.KVTOK

STRONG_CONFIRM = ("FIN+STALE", "FIN+NORESP", "REMACC+FIN")
STRONG = set(STRONG_CONFIRM) | {"EXITED", "NORESP", "STALL", "STALL_HELPER", "LINKDOWN"}

GC_COLS = ["subject", "n_surv", "ctrl", "witness_cfg", "fence_cfg", "confirm_w_ms", "probe_ms_page", "mono_off_used_ms",
           "mono_off_rtt_ms", "mono_off_drift_ms", "n_judge", "n_judge_confirm",
           "n_judge_exited", "n_judge_noresp", "n_judge_stall", "n_judge_stall_helper", "n_judge_linkdown", "judge_causes",
           "weak_cause_n", "timeout_judge_n", "judge_any_n", "fin_judge_dev_min_ms", "fin_judge_dev_max_ms", "n_rst_surv",
           "n_rst_confirm", "n_rst_exited", "rst_judge_dev_min_ms", "rst_judge_dev_max_ms", "rst_exited_kill_judge_min_ms",
           "rst_exited_kill_judge_max_ms", "rst_judge_ms_min", "rst_judge_ms_max", "kill_judge_ms_min", "kill_judge_ms_max",
           "kill_judge_exited_min_ms", "kill_judge_exited_max_ms", "kill_judge_clock", "stop_judge_ms_min",
           "stop_judge_ms_max", "judge_spread_ms", "judge_spread_clock", "judge_to_publish_ms", "kill_to_publish_ms",
           "publish_clock", "hold_ms_max", "hold_other_n", "kill_hold_ms_min", "hold_after_restore_n", "probe_timeout_n",
           "end_after_kill_ms", "suspect_n", "suspect_stale_ms_min",
           "suspect_stale_ms_max", "read_n", "read_ok_n", "read_success_pct", "read_lat_med_us_max", "read_lat_max_us",
           "beat_gap_max_ms", "page_torn_n", "witness_lost_n", "confirm_alive_n", "fence_sent", "fenced", "fence_order_ok",
           "fence_names_ok", "fence_sent_to_fenced_ms", "fenced_to_fallback_ms", "cont_target_present",
           "win_changed_after", "la_exited_n", "la_exit_silent_n", "la_fence_sigkill_n", "la_fenced_n",
           "la_fenced_after_sigkill_ms", "la_later_n", "la_act_refused_why", "la_stop_n", "la_refused_signal_n",
           "la_pid_mismatch_n", "la_qp_err_n", "launcher_same", "launcher_ready", "launcher_scope", "launcher_stale",
           "la_spare_spawn_n", "la_spare_respawn_n", "la_spare_cap_expected_n", "spare_hello_after_ms", "spare2_inc_want",
           "spare2_inc_got", "spare2_daemon_ok", "tcp_ctrl_bytes", "tcp_data_bytes",
           "tcp_ctrl_conn_n", "witness_pairs", "witness_expected", "ss_tcp_conn_n", "ss_pids_both", "ss_tx_delta_bytes",
           "ss_rx_delta_bytes", "rec_lost_n", "rec_dup_n", "rec_repair_n", "sendq_deferred", "sendq_max",
           "rnr_n", "async_n", "active_mtu_kv_min", "active_mtu_rain", "active_mtu_sunny", "ckpt_stable_in_mute",
           "ckpt_void_in_mute", "helper_reconnect_n", "qperr_pair_sent_by_target", "qperr_rec_gen_delta",
           "qperr_probe_gen_delta", "qperr_pair_read_fail", "qperr_records_after", "rejoin_dropped", "rejoin_resent",
           "rejoin_accept_n", "rejoin_accept_dup_n", "fail_to_spare_n", "inject", "inject_ok", "inject_off_ms",
           "inject_dur_off_ms", "pair_gap_ms", "ckpt_stable_before_inj", "kill2_after_armed", "stable_between_pair_kills",
           "subject_fenced", "gate_real", "old_go_ms", "fenced_go_ms", "gate_diff_ms", "second_thread_ms", "pidfd_ms", "z_ms",
           "fenced_after_second_ms", "fenced_vs_pidfd_abs_ms"]


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


def to_rain(e, off):
    """the event's time on rain's CLOCK_MONOTONIC (ms): its mono_ms, less the measured offset on sunny; None without"""
    if e is None or e.m is None:
        return None
    if e.node == "rain":
        return e.m
    if e.node == "sunny" and off is not None:
        return e.m - off
    return None


def xdiff(a, b, off=None):
    """ms from event a to event b: mono when both are on one node and carry mono_ms, both mono_ms in rain's clock across the
    nodes when the trial has the offset, else the receipt clock"""
    if a is None or b is None:
        return None, ""
    if a.node == b.node and a.m is not None and b.m is not None:
        return b.m - a.m, "mono"
    ra, rb = to_rain(a, off), to_rain(b, off)
    if ra is not None and rb is not None:
        return rb - ra, "mono_xnode"
    return (b.t - a.t) * 1000.0, "receipt"


def mono_offset(meta):
    """(offset ms, its round trip ms, after - before ms) of sunny's clock against rain's: the smaller round trip of the two"""
    c = []
    for o, r in (("mono_off_sunny_ms", "mono_off_rtt_ms"), ("mono_off_after_ms", "mono_off_after_rtt_ms")):
        ov, rv = fnum(meta.get(o)), fnum(meta.get(r))
        c.append((rv, ov) if ov is not None and rv is not None else None)
    have = [x for x in c if x is not None]
    if not have:
        return None, None, None
    rtt, off = min(have)
    drift = (c[1][1] - c[0][1]) if (c[0] is not None and c[1] is not None) else None
    return off, rtt, drift


def la_logs(stem):
    return {nd: evs(rows_rs.stamped("%s_launcher_%s.log" % (stem, nd)), nd) for nd in ("rain", "sunny")}


def la_after_start(evl):
    """the slice's lines after this trial's trial_start marker (the whole slice when it has none)"""
    st = [i for i, e in enumerate(evl) if LA_MARK_START.search(e.text)]
    return evl[st[-1] + 1:] if st else evl


def cap_expected(meta):
    """the spare-absent cells: the runner killed the spare and the launcher ran with --spare-respawn-max 0 (run_gc.sh)"""
    meta = meta or {}
    return meta.get("launcher_respawn_max") == "0" and (meta.get("spare_kill_first") == "1" or
                                                        meta.get("kill_kind") == "spare_then_rank")


def la_counts(lalog, s, meta=None):
    """the launcher counts every trial gets: STOP lines (both forms; the spare-absent cells' one expected cap line apart),
    refused signals and pid-check failures over the whole logs; the QP-loss lines of ranks other than the subject after the
    trial_start marker and before the first is-leaving"""
    whole = lalog["rain"] + lalog["sunny"]
    after = la_after_start(lalog["rain"]) + la_after_start(lalog["sunny"])
    stops = [e for e in sorted(whole, key=lambda x: x.t) if LA_STOP.search(e.text)]
    capx = [e for e in stops if LA_CAP0.search(e.text)][:1] if cap_expected(meta) else []
    out = {"la_stop_n": len(stops) - len(capx), "la_spare_cap_expected_n": len(capx),
           "la_refused_signal_n": sum(1 for e in whole if LA_REFSIG.search(e.text)),
           "la_pid_mismatch_n": sum(1 for e in whole if LA_PIDMIS.search(e.text))}
    t_leave = min((e.t for e in after if LA_LEAVING.search(e.text)), default=float("inf"))
    out["la_qp_err_n"] = sum(1 for e in after for m in [LA_QPLOST.search(e.text)] if m and e.t < t_leave
                             and int(m.group(1) or m.group(2)) != s)
    return out


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
    OFF, rtt, drift = mono_offset(meta)
    out["mono_off_used_ms"], out["mono_off_rtt_ms"], out["mono_off_drift_ms"] = r1(OFF), r1(rtt), r1(drift)
    xd = lambda a, b: xdiff(a, b, OFF)
    kr = int(meta["kill_rank"]) if str(meta.get("kill_rank", "")).isdigit() else -1
    kr2 = int(meta["kill2_rank"]) if str(meta.get("kill2_rank", "")).isdigit() else -1
    logs = {r: evs(rows_rs.stamped("%s_r%d.log" % (stem, r)), node_of(r)) for r in ranks}
    sp_node = node_of(int(meta["spare_rank"])) if str(meta.get("spare_rank", "")).isdigit() else node_of(max(kr, 0))
    slog = evs(rows_rs.stamped(stem + "_spare.log"), sp_node)
    slog2 = evs(rows_rs.stamped(stem + "_spare_2nd.log"), node_of(kr2) if kr2 >= 0 else "rain")

    def node_ev(path):
        el = evs(rows_rs.stamped(path), "?")
        for e in el:
            m = re.search(r"node=(\w+)", e.text)
            e.node = m.group(1) if m else (node_of(s) if s >= 0 else "?")
        return el
    kout = node_ev(stem + "_kill.out")
    skout = node_ev(stem + "_spare_kill.out")
    inj = evs(rows_rs.stamped(stem + "_inject.out"), node_of(s) if s >= 0 else "?")
    lalog = la_logs(stem)
    every = [e for r in ranks for e in logs[r]] + slog + slog2
    surv = [r for r in ranks if r != s] if s >= 0 else []
    out["n_surv"] = len(surv) if s >= 0 else ""
    # W and the READ period
    pg = [m for e in every for m in [PAGEUP.search(e.text)] if m]
    ws = [int(m.group(3)) for m in pg]
    out["confirm_w_ms"] = max(ws) if ws else (fnum(meta.get("confirm_ms")) if meta.get("confirm_ms") else "")
    out["probe_ms_page"] = max(int(m.group(2)) for m in pg) if pg else ""
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
        out["probe_timeout_n"] = sum(1 for r, (je, _) in js.items() for e in logs[r] for m in [TIMEOUTL.search(e.text)]
                                     if m and int(m.group(2)) == s and e.t <= je.t)

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
                d, _ = xd(o, je)
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
            d, _ = xd(re_ev, je)
            rj.append(d)
            if k in STRONG_CONFIRM:
                nrc += 1
                rc_dev.append(None if (d is None or W is None) else d - W)
            elif k == "EXITED":
                nre += 1
                re_k.append(xd(t_kill_ev, je)[0])
        out["n_rst_confirm"], out["n_rst_exited"] = nrc, nre
        out["rst_judge_dev_min_ms"], out["rst_judge_dev_max_ms"] = mm(rc_dev) if rc_dev else ("", "")
        out["rst_exited_kill_judge_min_ms"], out["rst_exited_kill_judge_max_ms"] = mm(re_k) if re_k else ("", "")
        out["rst_judge_ms_min"], out["rst_judge_ms_max"] = mm(rj) if rj else ("", "")
        # kill -> judgement
        if t_kill_ev is not None and js:
            ds = {r: xd(t_kill_ev, je) for r, (je, _) in js.items()}
            out["kill_judge_ms_min"], out["kill_judge_ms_max"] = mm([d for d, _ in ds.values()])
            ex = [ds[r][0] for r, (_, k) in js.items() if k == "EXITED"]
            out["kill_judge_exited_min_ms"], out["kill_judge_exited_max_ms"] = mm(ex) if ex else ("", "")
            out["kill_judge_clock"] = "+".join(sorted({c for _, c in ds.values()}))
        # stop / freeze -> STALLED
        st_ev, _ = first(inj, STOPL, lambda m: int(m.group(1)) == s)
        if st_ev is None:
            st_ev, _ = first(logs[s], SW_FREEZE)
        if st_ev is not None:
            sj = [xd(st_ev, je)[0] for r, (je, k) in js.items() if k in ("STALL", "STALL_HELPER")]
            out["stop_judge_ms_min"], out["stop_judge_ms_max"] = mm(sj) if sj else ("", "")
        if js:
            jl = [je for je, _ in js.values()]
            j0 = min(jl, key=lambda x: x.t)
            rt = [to_rain(je, OFF) for je in jl]
            if all(x is not None for x in rt):
                out["judge_spread_ms"], out["judge_spread_clock"] = r1(max(rt) - min(rt)), "mono"
            else:
                out["judge_spread_ms"], out["judge_spread_clock"] = r1((max(e.t for e in jl) - j0.t) * 1000.0), "receipt"
            pubs = []
            for r in surv:
                lg = logs[r] if not (r == kr and kr2 >= 0) else slog
                p = [e for e in lg for m in [PUB_OF.search(e.text)] if m and int(m.group(1)) == s and e.t >= j0.t]
                pubs.append(min(p, key=lambda x: x.t) if p else None)
            if pubs and all(p is not None for p in pubs):
                d1 = [xd(j0, p) for p in pubs]
                out["judge_to_publish_ms"] = r1(max(d for d, _ in d1))
                clocks = {c for _, c in d1}
                if t_kill_ev is not None:
                    d2 = [xd(t_kill_ev, p) for p in pubs]
                    out["kill_to_publish_ms"] = r1(max(d for d, _ in d2))
                    clocks |= {c for _, c in d2}
                out["publish_clock"] = "+".join(sorted(clocks))
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
                    hk.append(xd(t_kill_ev, e)[0])
                ends = [x for x in lg for mm2 in [RESTORED_OF.search(x.text) or GIVEN_UP_OF.search(x.text)]
                        if mm2 and int(mm2.group(1)) == p and x.t >= e.t]
                end = min(ends, key=lambda x: x.t) if ends else (max(lg, key=lambda x: x.t) if lg else e)
                hms.append(xd(e, end)[0])
        out["hold_ms_max"] = r1(max(hms)) if hms else 0
        out["hold_other_n"] = hother
        out["kill_hold_ms_min"] = r1(min(x for x in hk if x is not None)) if [x for x in hk if x is not None] else ""
        rest = [e.t for r in surv for e in logs[r] for m in [RESTORED_OF.search(e.text)] if m and int(m.group(1)) == s]
        if rest:
            t_r = min(rest)
            out["hold_after_restore_n"] = sum(1 for e in every if HOLD_OF.search(e.text) and e.t > t_r)
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
        out["fence_sent_to_fenced_ms"] = r1(xd(fe, fd)[0]) if (fe is not None and fd is not None) else ""
        out["fenced_to_fallback_ms"] = r1(xd(fd, gu)[0]) if (fd is not None and gu is not None) else ""
        if not any_fence:  # no fence line in the trial at all: the library does not emit them yet (TODO(p3))
            for c in ("fence_sent", "fenced", "fence_order_ok", "fence_names_ok"):
                out[c] = ""
        ce, cm = first(inj, CONTL, lambda m: int(m.group(1)) == s)
        out["cont_target_present"] = int(cm.group(2)) if cm else ""
        # the launcher: the subject's lines after this trial's trial_start marker
        la = la_after_start(lalog["rain"]) + la_after_start(lalog["sunny"])
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
    # every trial: the launcher's STOP lines (both forms, the whole slice), checks, QP loss
    if lalog["rain"] or lalog["sunny"] or ctrl == "rdma":
        out.update(la_counts(lalog, s, meta))
    # the warm spares of the trial's launchers (EXPERIMENT 9.5; the runner starts none on the launcher path)
    out["launcher_scope"] = meta.get("launcher_scope", "")
    out["launcher_stale"] = "" if meta.get("launcher_stale", "-") in ("", "-") else meta["launcher_stale"]
    if lalog["rain"] or lalog["sunny"]:
        sp = {nd: [m for e in lalog[nd] for m in [LA_SPAWNED.search(e.text)] if m] for nd in ("rain", "sunny")}
        he = {nd: [m for e in lalog[nd] for m in [LA_SPHELLO.search(e.text)] if m] for nd in ("rain", "sunny")}
        out["la_spare_spawn_n"] = sum(len(v) for v in sp.values())
        out["la_spare_respawn_n"] = sum(1 for v in sp.values() for m in v if m.group(3) in ("respawn", "hello_retry"))
        sr = int(meta["spare_rank"]) if str(meta.get("spare_rank", "")).isdigit() else -1
        h1 = [m for m in he[node_of(sr)] if int(m.group(4)) == sr and m.group(5) == "1"] if sr >= 0 else []
        out["spare_hello_after_ms"] = r1(float(h1[0].group(6))) if h1 else ""
        if kr2 >= 0 and ctrl == "rdma":
            want = 2 if kr2 == kr else 1
            n2 = node_of(kr2)
            why = {m.group(1): m.group(3) for m in sp[n2]}
            got = [m for m in he[n2] if int(m.group(4)) == kr2 and int(m.group(5)) == want]
            seen = [int(m.group(5)) for m in he[n2] if int(m.group(4)) == kr2]
            out["spare2_inc_want"] = want
            out["spare2_inc_got"] = want if got else (max(seen) if seen else "")
            out["spare2_daemon_ok"] = int(any(why.get(m.group(1)) == ("activated" if want == 2 else "start") for m in got))
    if ctrl == "rdma":
        same = True
        for nd in ("rain", "sunny"):
            bf, af = meta.get("launcher_before_" + nd, ""), meta.get("launcher_after_" + nd, "")
            key = lambda x: ",".join(p for p in x.split(",") if p.startswith(("pid=", "start=")))
            same = same and bool(bf) and key(bf) == key(af) and "alive=1" in af
        out["launcher_same"] = int(same)
        out["launcher_ready"] = int(meta.get("launcher_ready") == "1")
    # the READ probe (every process; the READs after the peer's end apart: REVIEW_TEST fix 18)
    ps = [kvd(m.group(3)) for e in every for m in [PROBESUM.search(e.text)] if m]
    if ps:
        g = lambda k: [fnum(d.get(k)) for d in ps if fnum(d.get(k)) is not None]
        reads = sum((fnum(d.get("reads")) or 0) - (fnum(d.get("after_end_reads")) or 0) for d in ps)
        oks = sum((fnum(d.get("ok")) or 0) - (fnum(d.get("after_end_ok")) or 0) for d in ps)
        out["read_n"], out["read_ok_n"] = int(reads), int(oks)
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
    # the control summaries: each process's last one
    cs = []
    for lg in [logs[r] for r in ranks] + [slog, slog2]:
        l = [m for e in lg for m in [CTRLSUM.search(e.text)] if m]
        if l:
            cs.append(kvd(l[-1].group(2)))
    if cs:
        sm = lambda k: int(sum(fnum(d.get(k)) or 0 for d in cs))
        wit_on = meta.get("witness", "1") != "0"
        out["tcp_record_bytes_sum"] = sm("tcp_record_bytes")
        out["tcp_data_bytes"] = sm("tcp_data_bytes")
        out["tcp_ctrl_bytes"] = sm("tcp_record_bytes") + sm("tcp_data_bytes")
        out["tcp_ctrl_conn_n"] = sm("tcp_conns")
        out["witness_pairs"] = sm("witness_conns") if wit_on else 0
        out["witness_expected"] = (n - 1) * len(cs) if wit_on else 0
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
    # the runner's ss snapshots (counts only)
    ssl = [m for t, l in rows_rs.stamped(stem + "_ss.out") if t is not None for m in [SSL.search(l)] if m]
    if ssl:
        s1 = {m.group(2): m for m in ssl if m.group(1) == "s1" and m.group(3) == "1"}
        s2_ = {m.group(2): m for m in ssl if m.group(1) == "s2" and m.group(3) == "1"}
        out["ss_tcp_conn_n"] = sum(int(m.group(4)) for m in s1.values())
        both = [p for p in s1 if p in s2_]
        out["ss_pids_both"] = len(both)
        if both:
            out["ss_tx_delta_bytes"] = sum(int(s2_[p].group(5)) - int(s1[p].group(5)) for p in both)
            out["ss_rx_delta_bytes"] = sum(int(s2_[p].group(6)) - int(s1[p].group(6)) for p in both)
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
    inj_ev = t_kill_ev  # the injection event of section 8's "before the first armed checkpoint" (REVIEW_TEST fix 13)
    if kind in ("kill_traffic", "fd_holder_kill", "kill_spare_then_rank") and s >= 0:
        ev, _ = first(kout, KILLED, lambda m: int(m.group(1)) == s and (m.group(3) or "first") in ("first", "after_spare"))
        ok = ev is not None
        if kind == "fd_holder_kill":
            ok = ok and first(logs[s], SW_FDHOLD)[0] is not None
        if kind == "kill_spare_then_rank":
            ok = ok and bool([e for e in skout if "GINRS killed" in e.text])
        out["inject_ok"] = int(ok)
        rk = ev
    elif kind == "sigstop" and s >= 0:
        ev, _ = first(inj, STOPL, lambda m: int(m.group(1)) == s)
        out["inject_ok"] = int(ev is not None and first(inj, CONTL)[0] is not None)
        rk = ev
        inj_ev = ev
        _, cm = first(inj, CONTL, lambda m: int(m.group(1)) == s)
        if cm and fnum(meta.get("stop_ms")) is not None:
            out["inject_dur_off_ms"] = r1(abs(float(cm.group(3)) - float(meta["stop_ms"])))
    elif kind == "duty" and s >= 0:
        rk, _ = first(inj, DUTYL, lambda m: int(m.group(1)) == s)
        out["inject_ok"] = int(rk is not None)
        inj_ev = rk
    elif kind == "kill_self" and s >= 0:
        out["inject_ok"] = int(first(logs[s], SW_DIE_RST)[0] is not None)
    else:
        envs = " ".join(meta.get(k, "") for k in ("r0_env", "r1_env", "r2_env", "r3_env", "spare_env"))
        need = [(sw, rx) for sw, rx in (("TEST_RST_GAP", SW_RST_GAP), ("TEST_FREEZE_PAGE", SW_FREEZE), ("TEST_QP_ERR", SW_QPERR),
                                        ("TEST_CREDIT_STALL", SW_CREDIT), ("TEST_DROP_UD", SW_DROPUD), ("TEST_SOCK_MUTE", MUTE_ON))
                if sw in envs]
        if need:
            out["inject_ok"] = int(all(any(rx.search(e.text) for e in every) for _, rx in need))
        if s >= 0 and "TEST_FREEZE_PAGE" in envs:
            inj_ev = first(logs[s], SW_FREEZE)[0]
    if rk is not None and plan is not None:
        out["inject_off_ms"] = r1(abs(rk.t - plan) * 1000.0)
    if s >= 0 and inj_ev is not None:
        stab = [e for r in ranks for e in logs[r] for m in [rows_rs.STABLE.search(e.text) or rows_rs.ARMED.search(e.text)]
                if m and int(m.group(1)) == s]
        out["ckpt_stable_before_inj"] = int(any(e.t < inj_ev.t for e in stab))
    # the second kill by recorded PID after armed (reported; gin-mirror's rule: never an exclusion)
    if meta.get("kill2_kind") == "pid_after_armed" and kr2 >= 0:
        e2, _ = first(kout, KILLED, lambda m: int(m.group(1)) == kr2 and m.group(3) == "second")
        a2 = fnum(meta.get("armed2_rt"))
        out["kill2_after_armed"] = int(e2 is not None and a2 is not None and e2.t >= a2)
    # the spare-absent cell: the gap between its two kills, and a stable checkpoint of the subject between them (one node)
    if kind == "kill_spare_then_rank" and s >= 0:
        gm = [m for e in kout for m in [GAPL.search(e.text)] if m and int(m.group(1)) == s]
        out["pair_gap_ms"] = r1(float(gm[0].group(2))) if gm else ""
        sk = [e for e in skout if "GINRS killed" in e.text]
        ev, _ = first(kout, KILLED, lambda m: int(m.group(1)) == s)
        if sk and ev is not None:
            sk0 = min(sk, key=lambda x: x.t)
            stab = [e for e in every for m in [STABLE_ANY.search(e.text)] if m and int(m.group(1)) == s]
            out["stable_between_pair_kills"] = int(any((xd(sk0, e)[0] or 0) > 0 and (xd(e, ev)[0] or 0) > 0 for e in stab))
    return out


def fenced_subject(stem, meta):
    """the subject when the runner killed nobody and the subject ended by SIGKILL (its rc 137, or the launcher's FENCE SIGKILL
    line names it): the stop, freeze and helper-freeze cells, where the launcher's fence ends the rank. gin-restore's and
    gin-mirror's columns (rows_rs.rs_row, rows_mi.mi_overlay) take a rank without KILL_RANK as live, so its partial kv would
    fail every data-equal column; for these trials they read the subject as the killed rank (rows_rs and rows_mi unchanged)"""
    subj = meta.get("subject_rank", "")
    if str(meta.get("kill_rank", "")).isdigit() or not str(subj).isdigit():
        return None
    s = int(subj)
    if meta.get("r%drc" % s) == "137":
        return s
    la = la_logs(stem)
    if any(m and int(m.group(1)) == s for e in la_after_start(la["rain"]) + la_after_start(la["sunny"])
           for m in [LA_SIGKILL.search(e.text)]):
        return s
    return None


def gate_rows(R):
    """local/: gate_fenced.cc's simulated lines (gate_real 0) and gate_proc_gc.py's real-process lines (gate_real 1)"""
    rows = []
    for p in sorted(glob.glob(os.path.join(R, "local", "gate_fenced*.log"))):
        for line in open(p, errors="replace"):
            m = GATE.search(line)
            if not m:
                continue
            o, f, d, l2 = float(m.group(2)), float(m.group(3)), float(m.group(4)), float(m.group(5))
            rid = "%s_t%s" % (os.path.basename(p)[:-4], m.group(1))
            r = {"id": rid, "stem": os.path.join(os.path.dirname(p), rid), "sub": "local", "cell": "gate_fenced",
                 "build": "cpu", "runner": "local", "key": "local:gate_fenced", "gate_real": 0, "old_go_ms": o,
                 "fenced_go_ms": f, "gate_diff_ms": d, "second_thread_ms": l2, "tnum": int(m.group(1)) + 1}
            rows.append(r)
    for p in sorted(glob.glob(os.path.join(R, "local", "gate_proc*.log"))):
        for line in open(p, errors="replace"):
            m = GATEP.search(line)
            if not m:
                continue
            d = kvd(m.group(2))
            v = {k: fnum(d.get(k)) for k in ("second_thread_ms", "pidfd_ms", "z_ms", "old_go_ms", "fenced_go_ms")}
            rid = "%s_t%s" % (os.path.basename(p)[:-4], m.group(1))
            r = {"id": rid, "stem": os.path.join(os.path.dirname(p), rid), "sub": "local", "cell": "gate_fenced",
                 "build": "cpu", "runner": "local", "key": "local:gate_fenced", "gate_real": int(d.get("real") == "1"),
                 "tnum": int(m.group(1)) + 1}
            for k, x in v.items():
                r[k] = r1(x)
            if v["fenced_go_ms"] is not None and v["old_go_ms"] is not None:
                r["gate_diff_ms"] = r1(v["fenced_go_ms"] - v["old_go_ms"])
            if v["fenced_go_ms"] is not None and v["second_thread_ms"] is not None:
                r["fenced_after_second_ms"] = r1(v["fenced_go_ms"] - v["second_thread_ms"])
            if v["fenced_go_ms"] is not None and v["pidfd_ms"] is not None:
                r["fenced_vs_pidfd_abs_ms"] = r1(abs(v["fenced_go_ms"] - v["pidfd_ms"]))
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
                fs = fenced_subject(stem, m)
                if fs is None:
                    r = rows_rs.rs_row(stem, sub)
                    r.update(rows_mi.mi_overlay(stem, r, m))
                else:  # the subject ended by the fence: gin-restore's and gin-mirror's columns see it as the killed rank
                    m2 = dict(m, kill_rank=str(fs))
                    orig = rows_rs.read_meta
                    rows_rs.read_meta = lambda st, _o=orig, _s=stem, _m=m2: dict(_m) if st == _s else _o(st)
                    try:
                        r = rows_rs.rs_row(stem, sub)
                        r.update(rows_mi.mi_overlay(stem, r, m2))
                    finally:
                        rows_rs.read_meta = orig
                r.update(gc_overlay(stem, r, m))
                r["subject_fenced"] = int(fs is not None)
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


def stops_line(stem):
    """hold_gc.sh's per-trial launcher check: the scorer's counts for one trial stem"""
    meta = rows_rs.read_meta(stem)
    subj = meta.get("subject_rank", "")
    c = la_counts(la_logs(stem), int(subj) if str(subj).isdigit() else -1, meta)
    c["la_not_up"] = int(meta.get("ctrl") == "rdma" and meta.get("launcher_ready") == "0")
    st = meta.get("launcher_stale", "-")
    c["la_stale_n"] = 0 if st in ("", "-") else len([x for x in st.split(",") if x])
    return " ".join("%s=%d" % (k, c[k]) for k in ("la_stop_n", "la_qp_err_n", "la_refused_signal_n", "la_pid_mismatch_n",
                                                    "la_not_up", "la_stale_n"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results", nargs="?")
    ap.add_argument("--out", default=None)
    ap.add_argument("--stops", default=None, metavar="STEM")
    a = ap.parse_args()
    if a.stops:
        print(stops_line(a.stops))
        return
    if not a.results:
        ap.error("a results dir or --stops <stem>")
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
