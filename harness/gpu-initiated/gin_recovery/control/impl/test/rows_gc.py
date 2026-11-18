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
            a "ctx=K" token anywhere on the line (the GIN context whose line froze)   TODO(lib, 2026-10-24 decision (가))
  CLOSED    GIN/TS: rank R: socket to rank P closed cause=C mono_ms=M [liveness=...]                 exists (ln4; FIN, ECONNRESET)
  PAGEUP    GIN/RC: rank R: status page up (B B in use, probe_ms=P stall_ms=S W=W[, device line ...]) mono_ms=M  exists;
            probe_ms= and W= read wherever they stand, any suffix (REVIEW_INT3 B1)
  CONFIRM   GIN/RC: rank R: confirm window for rank P opened by FIN|RST|END W=W ... mono_ms=M        exists
            GIN/RC: rank R: confirm window for rank P closed: alive|STALE|NORESP|REMACC|unconfirmed mono_ms=M   TODO(p1)
  SUSPECT   GIN/RC: rank R: rank P suspected (kind=watch|helper|gpu stale_ms=X) mono_ms=M            exists (p1)
            other tokens inside the parenthesis are allowed; "ctx=K" anywhere on the line   TODO(lib, 2026-10-24 decision (가))
  TIMEOUT   GIN/RC: rank R: probe of rank P timed out (no CQE in T ms) mono_ms=M                     TODO(p1)
  READFAIL  GIN/RC: rank R: liveness READ of rank P[ (device line)]: <why> (status S) mono_ms=M      exists (smoke 5)
  PROBESUM  GIN/RC: rank R: probe summary peer=P reads=N ok=K remacc=A noresp=B timeout=C gen=G lat_med_us=X lat_max_us=Y
            beat_gap_max_ms=Z torn=T after_end_reads=E after_end_ok=F mono_ms=M   (at teardown, one per peer; the
            after_end_* READs came after the peer's BYE, LEFT or judgement and are left out of read_n and read_ok_n)  TODO(p1)
  WITLOST   GIN/RC: rank R: witness of rank P lost; liveness alive mono_ms=M (table row 8)           TODO(p1)
  FENCING   GIN/RC: rank R: rank P (incarnation I) fence FENCING: FENCE sent to the launcher of node N mono_ms=M   TODO(p3)
  FENCED    GIN/RC: rank R: rank P (incarnation I) fence FENCED (by FENCED|EXITED from node N) mono_ms=M        TODO(p3)
  WINCHG    GIN/RC: rank R: window check after the fence|judgement of rank P: changed=N cells against=snapshot_at_judgement
            unreadable=U mono_ms=M        exists; checked=C and "(incarnation I)" after P are read when a later line has them
  CTRLSUM   GIN/RC: rank R: control summary tcp_record_bytes=.. tcp_data_bytes=.. tcp_conns=.. witness_conns=..
            records_lost=.. records_dup=.. repairs=.. sendq_deferred=.. sendq_max=.. rnr=.. async=.. active_mtu=.. mono_ms=M
            (at teardown and at every confirmed checkpoint, every process; the last one of a process counts)  TODO(p2)
  RINGSUM   GIN/RC: rank R: ring summary peer=P gen=G sent=S received=V lost=L dup=D mono_ms=M      TODO(p2)
  PAIRSENT  GIN/RC: rank R: PAIR(record, gen G) to rank P (local ERR) mono_ms=M                      TODO(p2)
  REPAIRED  GIN/RC: rank R: record QP|liveness READ QP to rank P re-paired (gen G) mono_ms=M         TODO(p2)
  LIVE      GIN/RC: rank R: the records go on the ring from now (live): N peer(s), ...               exists (2a-2-B)
  witness   GIN/TS: rank R: socket to rank P reconnected gen=G attempts=A; GIN/RC: rank R: rank P's witness socket after
            its REJOIN over UD: unknown, re-dialled; GIN/RC: rank R: the REJOIN of rank P (incarnation I) taken over UD;
            GIN/RS: spare rank R: restored as incarnation I                                         exist (2a-2-C)
  LA_UNIX   GIN/RC: rank R: launcher Unix socket closed (EOF|<errno>) (rank side; STOP_launcher, F6)  exists
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
  driver    GINRS gpuhang rank=R step=S spin=1 [ctx=all|K ]wait_ms=W mono_ms=M (impl/test/driver/gin_mi.cu GC_GPUHANG_IT:
            the hung kernel's spin started; the injection record of gc4_gpuhang12000_fence, 2026-10-23; ctx= since the
            2026-10-24 context filter GC_GPUHANG_CTX: a cell with GC_GPUHANG_CTX=K needs ctx=K, gc4_gpuhang12000_ctx1_fence)   exists
            GINRS quiet rank=R step=S ms=L spin=1 ctas=C wait_ms=W mono_ms=M and GINRS quiet end rank=R step=S ms=L done=1
            took_ms=T mono_ms=M (GC_QUIET_IT=S@L, 2026-10-27: the start line with the cell's S and L is the injection record of
            gc4_quiet12000; the end line bounds the window)                                          source only (not run)
            GINRS waitpend rank=R step=S dest=D wait_ms=W mono_ms=M (a wait over 1 000 ms) and GINRS waitpend end rank=R step=S
            dest=D result=satisfied|released wait_ms=W mono_ms=M (GC_WAITPEND=1, 2026-10-27; the rank's kv waitpend=1 is the
            injection record, the lines are reported)                                                source only (not run)
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
  n_judge_taken              (2026-11-18, decision (가) after pilot 8) survivors with no judgement line of the subject but a
                             decline of it whose reason is another rank's confirmed abort decision about it ("GIN/TS:
                             declined rank=R peer=<subject> reason="ABORT_DECIDED(rank <subject>, ..."; piece ①, the line of
                             ../notes_abortdec.md "줄"): the survivor applied a peer's decision before its own judgement
                             (pilot 8's fence-off stall cell, pilot 7 n1) and counts as having concluded; n_judge +
                             n_judge_taken <= n_surv
  stall_ctx                  (2026-10-24, decision (가)) the GIN context each survivor's STALL judgement of the subject names:
                             ctx= on its STALLED line, else on its last SUSPECT line naming the subject before it; the
                             distinct values "+"-joined, "none" for a STALL judgement that names none; empty when no
                             survivor judged STALL ("1" is the number 1 to the rules; "1+none" is not)
  weak_cause_n               rdma builds: DEAD lines (any subject) whose cause is not one of the seven or LINKDOWN
  timeout_judge_n            DEAD lines whose cause names a timeout only
  judge_any_n                every DEAD and STALLED line of the trial (every subject, every process)
  fin_judge_dev_min_ms/max   confirm-window survivors: (judgement - its window's t_F) - W; t_F = the CONFIRM open line, else
                             the last CLOSED line (FIN or ECONNRESET) naming the subject before the judgement (same process)
  n_rst_surv, n_rst_confirm, n_rst_exited, rst_judge_dev_min/max_ms, rst_exited_kill_judge_min/max_ms, rst_judge_ms_min/max
                             survivors with an ECONNRESET CLOSED line naming the subject: their judgement's cause; for the
                             confirm causes (judgement - that RST) - W; for EXITED kill -> judgement; any cause RST -> judgement
  kill_judge_ms_min/max, kill_judge_exited_min_ms/max, kill_judge_clock   kill -> first judgement per survivor
  stop_judge_ms_min/max      injection start (GINRS stop, the FREEZE_PAGE line, or the driver's GINRS gpuhang line) ->
                             the survivor's STALLED line
  judge_spread_ms            the survivors' first judgements, max - min (receipt clock)
  judge_to_publish_ms, kill_to_publish_ms   the first judgement / the kill -> the last survivor's first "published" line
  hold_ms_max, hold_other_n, kill_hold_ms_min   the survivors' hold durations (hold start -> restored, given up or the log's
                             end), hold starts naming another rank than the subject, kill -> first hold start
  hold_after_restore_n       hold starts (any rank, any subject, the spares' logs too) after the subject's first restored line
                             (a false hold at the revived rank's own end is counted here; REVIEW_TEST fix 9)
  probe_timeout_n            READ time-out lines naming the subject before that survivor's judgement
  probe_fail_n               READ failure lines (READFAIL, either form) naming the subject before that survivor's judgement
                             (2026-10-23: fdhold_sock_helper_stall wants 0, the inherited mappings keep the READ answered)
  suspect_n, suspect_stale_ms_min/max   SUSPECT lines naming the subject
  read_n, read_ok_n, read_success_pct, read_lat_med_us_max, read_lat_max_us, beat_gap_max_ms, page_torn_n   PROBESUM, summed
                             over every rank and spare process (read_n, read_ok_n: the page READs, after_end_* apart)
  dev_read_n, dev_read_ok_n, read_page_success_pct, read_dev_success_pct, probe_missing   (Codex finding 1, 2026-10-23) the
                             device-line READs (dev_reads=, dev_ok=: every context's sum); the page and device success rates
                             apart; read_success_pct = (page ok + device ok) / (page READs + device READs). Every process of
                             the final generation (required_procs) needs one summary per peer of the final generation, and a
                             summary whose peer named a device line (its dev_line=1, or the peer's "device line named" page
                             line) its dev_reads= and dev_ok= (with dev_ctx= or the peer page's contexts= above 1, also
                             dev_reads_ctx= and dev_ok_ctx= of that many values); probe_missing names each gap
                             ("proc:p<peer>" a summary, "proc:p<peer>:<field>" a counter). A missing summary empties every
                             count and rate, a missing counter its side's, any gap read_success_pct (never a 0 for it)
  cost_probe_evidence, cost_probe_window, cost_probe_inwindow_lb, cost_probe_expected   cost rows (Codex finding 2, 2026-10-23): the probe arms' READ evidence in
                             the trial's own logs (cost_probe); "ok", else the reasons, and the row's cost_valid is then 0
  witness_lost_n, confirm_alive_n   WITLOST lines; CONFIRM closed alive lines
  fence_sent, fenced, fence_order_ok, fence_names_ok, fence_sent_to_fenced_ms, fenced_to_fallback_ms
                             the buddy's (subject xor 1, the revived buddy's spare log when the buddy died first) FENCING and
                             FENCED lines for the subject, and its activation line (rows_rs ACTIVATED): fence_order_ok =
                             FENCED and the activation exist, FENCING (when there) <= FENCED <= the activation;
                             fence_names_ok = both FENCING and FENCED exist; FENCED -> the buddy's first "is given up" line
  cont_target_present        the runner's SIGCONT line: was the stopped PID still there (0 when the fence ended it)
  win_changed_after, win_lines_n, win_missing, win_unreadable, win_checked, win_verified   (Codex review 2026-10-23 item 3)
                             the WINCHG lines: changed= summed (empty unless the samples are complete or a change was seen:
                             an unread window is never "0 changes"), the survivors with a line for the subject and those
                             without ("0+2"), unreadable= and checked= summed (checked empty: the line has none);
                             win_verified 1 iff every survivor's line is there, unreadable 0, checked > 0 where given, changed 0;
                             a line without changed= or unreadable= is incomplete ("rank:field" in win_missing)
  data_equal, ow_data_equal, spare_state, final_gen_n   (item 2) override gin-restore's and gin-mirror's columns for one death:
                             every active process of the final generation (a dead rank: the spare that revived as it; an
                             unused warm spare contributes nothing); spare_state unused | restored | restored_bad |
                             not_restored | revived_unexpected; final_gen_n the processes compared. A second death keeps
                             gin-mirror's columns
  resume_refusal, resume_why_refused, ring_not_live_class   (item 4) a Resume refusal's class (config when a refused rank's
                             reason is one of CONFIG_REFUSALS, else prep) and the reasons; a ring not live: config when a
                             rank's setup agreement turned recovery off for condition 42 or 44, else prep
  tl_rank, tl_inject, tl_clock, t_suspect_ms, t_judge_ms, t_block_ms, t_fenced_ms, t_fenced_src, t_la_fenced_ms, t_publish_ms,
  t_first_ok_ms, t_first_ok_step   (item 6) the event timeline on the subject node's survivor (subject xor 2), ms after the
                             injection (the kill, STOP, FREEZE_PAGE, DIE_RST or gpuhang line), that node's CLOCK_MONOTONIC:
                             the first SUSPECT, confirm-window open or READ time-out line naming the subject, its judgement,
                             its hold start (the gates; no QP-to-ERR line exists), the fence (t_fenced_src: the subject
                             node launcher's FENCED line of the trial launcher_FENCED, else a survivor's FENCE -> FENCED report
                             line survivor_FENCED, else the window line window_fence | window_judgement; 2026-10-24 after
                             pilot 3), the launcher's FENCED line on that node (t_la_fenced_ms),
                             its "published" line, and the first driver step line after the publish with tx_err=0 (the
                             driver prints no per-step check: counted only when the rank's kv dev_bad is 0)
  la_exited_n, la_exit_silent_n, la_fence_sigkill_n, la_fenced_n, la_fenced_after_sigkill_ms, la_later_n,
  la_act_refused_why, la_stop_n, la_refused_signal_n, la_pid_mismatch_n, la_qp_err_n, launcher_same, launcher_ready
                             the trial's launcher logs (both nodes) for the subject; la_stop_n counts every "(STOP_launcher)"
                             line; la_qp_err_n the launcher's QP-loss lines for ranks other than the subject (and the second
                             kill's kill2_rank, 2026-10-24) before the first "is leaving" line (TODO(p3): the teardown rule); launcher_same = both launchers' pid and start equal
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
  tcp_data_bytes, rec_lost_n, rec_dup_n, rec_repair_n, sendq_deferred, sendq_max, rnr_n, async_n, active_mtu_kv_min,
  tcp_conns_lib, witness_conns_lib   CTRLSUM (each process's last, every rank and spare process) summed (rnr_n adds the
                             meta's RNR port-counter growth); the two _lib columns are the library's own counts (reported only)
  ctrlsum_missing, ctrlsum_fields_missing   (Codex review 2026-10-23) the final generation's processes (ctrlsum_required:
                             the ranks that did not die, the spares that became active; not an unused spare) without a
                             summary (every summary column then empty), and "proc:field" for a counter a column reads that a
                             required summary lacks (that column empty; never 0); the spares come from the _spare*.kv as
                             well as the logs, and a required process without a .log is named <proc>:nolog
  dead_log_missing           (Codex re-check 2026-10-23) the killed ranks (kill_rank, kill2_rank; no summary needed) whose
                             _r<k>.log is absent, "+"-joined
  tcp_ctrl_bytes, tcp_record_bytes_prelive, tcp_record_bytes_unsplit   rdma builds (REVIEW_INT3 B3 (a)): the TCP record and
                             data bytes each process sent after its ring went live (the summary's tcp_<k>_bytes_live= or
                             _prelive= split; a total of 0 is 0 on both sides); the bootstrap records before live apart; a
                             summary without the split adds its record total to _unsplit and leaves tcp_ctrl_bytes empty
  ring_live_pairs, tcp_ctrl_conn_n   rdma builds (B3 (b), (c)): the pairs of the final generation (a spare that restored and
                             went live replaces its rank's earlier process) whose two processes went live, and those whose
                             socket both ends opened (witness_view: the live line, reconnected, re-dialled, the REJOIN lines;
                             each socket belongs to the incarnation pair its process's lines name, a spare's peers starting at
                             the incarnations restored before it; 2026-10-24 after pilot 3)
  witness_pairs, witness_expected   tcp_ctrl_conn_n and ring_live_pairs with the witness on, 0 with it off (tcp builds: the
                             library's witness_conns sum and (N - 1) x the summaries, REVIEW_TEST fix 10)
  ring_live_n, ring_live_all, ring_live_ms_max   rdma builds (REVIEW_INT3 F7): the ranks whose live line came within
                             LIVE_BOUND_MS of their first line, all of them, the slowest (ms)
  rank_stop_n, rank_la_sock_lost_n   (F6) the rank and spare processes' "(STOP_launcher" lines and launcher Unix socket loss
                             lines before the trial_end marker; both are in la_stop_n
  ss_tcp_conn_n, ss_pids_both, ss_tx_delta_bytes, ss_rx_delta_bytes   the runner's two ss snapshots of the rank PIDs: the
                             established TCP sockets at the first, the bytes acked / received between the two over the pids
                             alive at both reads; ss_excluded names each pid left out (absent_s1, absent_s2, no_s2) and each
                             live pid with a negative delta ("negative": a socket closed between the reads; the delta is
                             then empty, never 0; 2026-10-24 after pilot 2, ss_deltas)
  active_mtu_rain, active_mtu_sunny   the runner's ibv_devinfo reading (meta); active_mtu_kv_min and these in bytes: the
                             library's active_mtu= is the ibv_mtu enum (5 = 4096 B; item 1, mtu_bytes)
  ckpt_stable_in_mute, ckpt_void_in_mute, helper_reconnect_n   stable / void checkpoint lines inside the socket mute's on -> off
                             window (receipt), and helper reconnect lines
  qperr_pair_sent_by_target, qperr_rec_gen_delta, qperr_probe_gen_delta, qperr_pair_read_fail, qperr_records_after
                             the QP_ERR target rank T and its peer P (the switch line): T logged PAIRSENT to P; the highest
                             re-paired record gen on T toward P less the ring's first gen (REC_GEN0 = 1; pilot 1 problem 4:
                             it was the new gen itself, 2 for one re-pairing); liveness-READ re-pairings of the pair (both ends); the pair's
                             PROBESUM failures; RINGSUM received by T from P in a gen >= 1
  rejoin_dropped, rejoin_resent, rejoin_accept_n, rejoin_accept_dup_n, fail_to_spare_n
  inject_ok, inject_off_ms, inject_dur_off_ms   the injection's record exists (runner line or library switch line); the
                             runner's injection receipt - its plan (meta inj_plan_rt); a stop's measured length - STOP_MS
  pair_gap_ms                the spare-absent cell: the runner's spare kill -> rank kill on that node's clock
  subject_fenced             1 when the runner killed nobody and the subject ended by SIGKILL (the fence): gin-restore's and
                             gin-mirror's columns then read it as the killed rank (fenced_subject)
  ckpt_stable_before_inj     a stable (or armed) checkpoint of the subject before its injection (the kill, DIE_RST, the STOP,
                             FREEZE_PAGE or GINRS gpuhang line); section 8's "before the first armed checkpoint" for every injected cell
  kill2_after_armed          KILL2_KIND=pid_after_armed: the second kill's receipt >= the survivors' last armed line (meta)
  stable_between_pair_kills  the spare-absent cell: a stable checkpoint of the subject between the spare kill and its kill
                             (the subject's mono_ms against the runner's on the same node)
  suspect_any_n, hold_any_n, spare_used   (2026-10-27, Codex review of the counterexample design, item 6) every SUSPECT line
                             of the trial whatever rank it names (page-dependent like suspect_n), every hold start of any rank
                             in any process, and 1 when a spare was used (a spare's "restored as incarnation", a survivor's
                             "rank P restored as incarnation" or a launcher's ACCEPTED activation), else 0
  quiet_ms, quiet_periods, quiet_lb_detail   (2026-10-27, GC_QUIET_IT on the subject) the window (its quiet end - start line,
                             one process) and the least over the observers of max(0, P_w - X_O): P_w = floor(window /
                             probe_ms) - 1, X_O = dev_ctx x reads - dev_quiet of the observer's last summary for the subject
                             (the context READs not counted quiet over the whole run; each spoils at most one period of the
                             window); 0 without the end line (a measured failure), empty without an observer's summary
  waiter, waiter_judge_n, waiter_judge_ms_min/max, waiter_judge_causes, waiter_fenced, waiter_hold_n, waiter_given_up_n
                             (2026-10-27, meta waiter_rank from the cell's WAITER_RANK) the observer processes (every rank and
                             spare log but the waiter's) with a DEAD or STALLED line naming the waiter, the subject's gpuhang
                             line -> their first such line (min, max; cross-node in rain's clock), the causes; reported: the
                             launcher's FENCE SIGKILL or FENCED of the waiter, hold starts and give-ups naming it
  waitpend_kv, waitpend_long_n, waitpend_ms_max, waitpend_result   (GC_WAITPEND=1 in a rank's env) "rank:kv waitpend" (each
                             must be 1, else inject_ok 0), the waiter's long-wait lines, the longest ended wait, the results
                             ("open" when a long wait has no end line)
  hang_lines, judged_ranks   (2026-10-27, pilot 5) hang_lines: for every rank whose env has GC_GPUHANG_IT=S
                             "rank:step:ctx" of its first GINRS gpuhang line ("rank:-" without one); the injection record needs,
                             per such rank, a line rank=R step=S spin=1 (with ctx=K when that rank's env has GC_GPUHANG_CTX=K).
                             judged_ranks: with a GINRS gpuhang line in the trial, every rank that some process judged (a DEAD or
                             STALLED line naming it, the observer's own rank apart) as "rank:ms:observers" in time order, ms =
                             the first hang line (any rank, rain's clock across nodes) -> that rank's first judgement line,
                             observers = the processes (rank and spare logs) with such a line; "none" when nothing was judged
  wait_peer, wait_ended_progress, wait_ended_nogress   (2026-10-27 after pilot 5; the waiting rule of impl/notes_waitpeer.md,
                             meta waiter_rank) over the observer processes of the waiter columns (every rank and spare log but
                             the waiter's): wait_peer the peers named in their "rank W waiting (peer=P[,Q])" lines, sorted and
                             joined by "+" ("none" without such a line); wait_ended_progress 1 when some observer has "rank W
                             wait ended (progress: ...", else 0; wait_ended_nogress the same for "wait ended (its peers
                             resolved, no progress within G ..." (the hard-bound ending sets neither)
  gate rows (local/): gate_real, old_go_ms, fenced_go_ms, gate_diff_ms, second_thread_ms, pidfd_ms, z_ms,
                             fenced_after_second_ms, fenced_vs_pidfd_abs_ms. gate_proc_gc.py's lines (a real child process: its
                             main thread ends first, a second thread 500 ms later; the harness's own pidfd and /proc readings)
                             give gate_real 1; gate_fenced.cc's simulated lines give gate_real 0 (REVIEW_TEST fix 1)
"""
import argparse, csv, glob, math, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "mirror", "impl", "test"))
import rows_mi  # noqa: E402  (imports rows_rs)
rows_rs = rows_mi.rows_rs

MONO = re.compile(r"\bmono_ms=([0-9.]+)")
DEAD = re.compile(r"GIN/TS: rank (\d+): rank (\d+) judged dead \(cause=([^)]*)\)")
STALLED = re.compile(r"GIN/RC: rank (\d+): rank (\d+) \(incarnation \d+\) judged stalled \(.*?\b(STALL_HELPER|STALL)\b")
CLOSED = re.compile(r"GIN/TS: rank (\d+): socket to rank (\d+) closed cause=(\S+)")
# B1 (REVIEW_INT3): the tokens wherever they stand in the parenthesis, any suffix (", device line named 1184 B)" since 2a-2-C)
PAGEUP = re.compile(r"GIN/RC: rank (\d+): status page up \(.*?\bprobe_ms=(\d+)\b.*?\bW=(\d+)\b")
TIMEOUTL = re.compile(r"GIN/RC: rank (\d+): probe of rank (\d+) timed out")
READFAILL = re.compile(r"GIN/RC: rank (\d+): liveness READ of rank (\d+)\b")
SSL = re.compile(r"GINRS ss (s1|s2) pid=(\d+) present=([01]) n=(\d+) acked=(\d+) received=(\d+)")
GAPL = re.compile(r"GINRS killed rank=(\d+) node=\w+ pid=\d+ which=after_spare gap_ms=([0-9.]+)")
LA_MARK_START = re.compile(r"GINLA mark trial_start ")
CONF_OPEN = re.compile(r"GIN/RC: rank (\d+): confirm window for rank (\d+) opened by (FIN|RST|END) W=(\d+)")
CONF_CLOSE = re.compile(r"GIN/RC: rank (\d+): confirm window for rank (\d+) closed: (alive|STALE|NORESP|REMACC|unconfirmed)")
# 2026-10-24: other tokens (ctx=) may stand between kind= and stale_ms= or after it inside the parenthesis
SUSPECT = re.compile(r"GIN/RC: rank (\d+): rank (\d+) suspected \(kind=(\w+)\b[^)]*?\bstale_ms=([0-9.]+)[^)]*\)")
CTXTOK = re.compile(r"\bctx=(\d+)\b")  # the GIN context a STALLED or SUSPECT line names (2026-10-24, decision (가))
# 2026-11-18 (n_judge_taken): a decline whose reason is a confirmed abort decision of another rank (piece ①, gdakiTsDecline)
ADTAKEN = re.compile(r'GIN/TS: declined rank=(\d+) peer=(\d+) reason="ABORT_DECIDED\(rank (\d+),')
PROBESUM = re.compile(r"GIN/RC: rank (\d+): probe summary peer=(\d+) (.*)$")
WITLOST = re.compile(r"GIN/RC: rank (\d+): witness of rank (\d+) lost; liveness alive")
FENCING = re.compile(r"GIN/RC: rank (\d+): rank (\d+) \(incarnation (\d+)\) fence FENCING\b")
FENCEDL = re.compile(r"GIN/RC: rank (\d+): rank (\d+) \(incarnation (\d+)\) fence FENCED\b")
# any window line, its fields as key=value (changed= and unreadable= are required: a line without one is incomplete)
WINCHG = re.compile(r"GIN/RC: rank (\d+): window check after the (?:fence|judgement) of rank (\d+)(?: \(incarnation (\d+)\))?: "
                    r"(.*)$")
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
SW_GPUHANG = re.compile(r"GINRS gpuhang rank=(\d+) step=(\d+) spin=1 ")  # the test driver's GC_GPUHANG_IT (2026-10-23)
HANGCTX_ENV = re.compile(r"\bGC_GPUHANG_CTX=(\d+)\b")  # its context filter (2026-10-24): the line must say ctx=<k>
HANGIT_ENV = re.compile(r"\bGC_GPUHANG_IT=(\d+)\b")  # per rank (2026-10-27, pilot 5: two hung ranks in one trial)
# the test driver's GC_QUIET_IT=<step>@<ms> and GC_WAITPEND=1 (2026-10-27, gc4_quiet12000 and gc4_gpuhang12000_waitpend_fence)
QUIET_ENV = re.compile(r"\bGC_QUIET_IT=(\d+)@(\d+)\b")
SW_QUIET = re.compile(r"GINRS quiet rank=(\d+) step=(\d+) ms=(\d+) spin=1\b")
SW_QUIET_END = re.compile(r"GINRS quiet end rank=(\d+) step=(\d+) ms=(\d+) done=1\b")
WAITPEND_ENV = re.compile(r"\bGC_WAITPEND=1\b")
WP_LONG = re.compile(r"GINRS waitpend rank=(\d+) step=(\d+) dest=(\d+) wait_ms=([0-9.]+)")
WP_END = re.compile(r"GINRS waitpend end rank=(\d+) step=(\d+) dest=(\d+) result=(satisfied|released) wait_ms=([0-9.]+)")
# 2026-10-27 after pilot 5: the library's waiting-rule lines (gin_host_gdaki.cc gdakiCtrlWaitStep)
WAIT_PEER = re.compile(r"GIN/RC: rank (\d+): rank (\d+) waiting \(peer=([0-9,]+)\)")
WAIT_ENDED = re.compile(r"GIN/RC: rank (\d+): rank (\d+) wait ended \((progress: |its peers resolved, no progress within G|the hard bound)")
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
# F6 (REVIEW_INT3): the rank side's launcher loss (a rank or spare lost its launcher's Unix socket): STOP_launcher too
LA_UNIX = re.compile(r"GIN/RC: rank (\d+): launcher Unix socket closed \(")
LA_MARK_END = re.compile(r"GINLA mark trial_end ")
# F7 and B3 (REVIEW_INT3): the ring's live line, the witness lines per pair and incarnation
LIVE = re.compile(r"GIN/RC: rank (\d+): the records go on the ring from now \(live\): (\d+) peer\(s\)")
RECONN = re.compile(r"GIN/TS: rank (\d+): socket to rank (\d+) reconnected gen=\d+ attempts=\d+")
REDIAL = re.compile(r"GIN/RC: rank (\d+): rank (\d+)'s witness socket after its REJOIN over UD: unknown")
RJ_INC = re.compile(r"GIN/R[CS]: rank (\d+): (?:the REJOIN of rank (\d+) \(incarnation (\d+)\) taken|"
                    r"rank (\d+)'s spare rejoined as incarnation (\d+))")
SPARE_INC = re.compile(r"GIN/RS: spare rank (\d+): restored as incarnation (\d+)")
# 2026-10-24 after pilot 3: a spare's own lines that name the incarnation of the peer it rejoins (a peer restored before:
# spare_2nd.log "rank 2 (incarnation 1) is reached over UD at the activation table's endpoint" and "the REJOIN to rank 2
# (incarnation 1, restored before) starts gen ..."); its "reconnected", "re-dialled" and REJOIN_ACK lines name no incarnation
RJ_PEER_INC = re.compile(r"GIN/RC: rank (\d+): (?:rank (\d+) \(incarnation (\d+)\) is reached over UD|"
                         r"the REJOIN to rank (\d+) \(incarnation (\d+)\b)")
STEPL = re.compile(r"GINRS step rank=(\d+) step=(\d+) released=0 tx_err=(\d+) ")  # the driver's step line (gin_mi.cu)
SETUP_OFF = re.compile(r"setup agreement: .*transparent recovery off at the setup \(Resume condition (\d+)\)")
# Codex review 2026-10-23 item 4: the Resume refusals that name a configuration (the cell's env, build or hardware), read
# from the libraries' condition texts (gc_layer_int.diff GDAKI_CTRL_R42-R44T; mi_layer.diff GDAKI_MI_R36, R37, R39;
# rs_layer.diff's GDAKI_RS_L lines that name an env variable, a build macro or the HCA). Any other refusal (the launcher
# pairing of condition 41, a pool, a QP, the side table, the NIC copy path, the atomics, a replay) is a preparation failure
CONFIG_REFUSALS = (
    "a rank's active MTU is below 2048", "ibv_is_fork_initialized() is not IBV_FORK_UNNEEDED",
    "the control path or the launcher node differs between ranks", "the liveness thresholds differ between ranks",
    "NCCL_GIN_RESTORE_MIRROR and NCCL_GIN_RESTORE_CHECKSUM are both on",
    "NCCL_GIN_RESTORE_MIRROR_LANE is not a positive multiple of 64",
    "NCCL_GIN_RESTORE_MIRROR_SLOTS or NCCL_GIN_RESTORE_MIRROR_LANE differs between ranks",
    "GIN connections (NCCL_GIN_NCONNECTIONS)", "host RMA is on", "runtime connect is off (NCCL_RUNTIME_CONNECT)",
    "NVLS is on (NCCL_NVLS_ENABLE)", "transparent recovery is off for this devComm (NCCL_GIN_FAULT_RECOVERY",
    "NCCL_GIN_TS_RECONNECT is not 1", "the QP watch is off (NCCL_GIN_TS_QPWATCH_MS)",
    "the send-side log measurement mode is on", "program not built with NCCL_GIN_RESTORE_DEVICE",
    "does not record its init transcript (NCCL_GIN_RESTORE_RECORD)", "the HCA's atomic capability is below IBV_ATOMIC_HCA")
CONFIG_SETUP_OFF = ("42", "44")  # the setup agreement's off line: an MTU below 2048, the control path differs (config)
LIVE_BOUND_MS = 10000.0  # F7's setup bound: process start -> live line (GL_REPAIR_MS, the pairing bound); fixed 2026-10-24
# (EXPERIMENT 8, pilot 1: ring live after 990.1-1 079.0 ms in 25 rdma trials)
REC_GEN0 = 1  # a record QP's first generation: gen 0 is "not paired" (gc_layer_int.diff, gdakiCtrlRing*: p->gen == 0), and
# every ring summary of a peer without a re-pairing says gen=1 (pilot 1 a3 gc4_qperr_record, ranks 0-3)
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
# ../gate_fenced.cc's line (REVIEW_P12 고칠 것 7: a real child process, the real gate functions on it; times from the
# child's own main-thread end, CLOCK_MONOTONIC). The old line above (a timeline model, gate_real 0) is kept for old folders
GATEU = re.compile(r"gate_fenced trial (\d+): main thread ended \+0, old gate GO \+([0-9.]+) ms \((.*)\); last thread ended "
                   r"\+([0-9.]+) ms, FENCED gate GO \+([0-9.]+) ms; the gates differ by (-?[0-9.]+) ms")
GATEP = re.compile(r"gate_proc trial (\d+): (.*)$")
KVTOK = rows_rs.KVTOK

STRONG_CONFIRM = ("FIN+STALE", "FIN+NORESP", "REMACC+FIN")
STRONG = set(STRONG_CONFIRM) | {"EXITED", "NORESP", "STALL", "STALL_HELPER", "LINKDOWN"}

GC_COLS = ["subject", "n_surv", "ctrl", "witness_cfg", "fence_cfg", "confirm_w_ms", "probe_ms_page", "mono_off_used_ms",
           "mono_off_rtt_ms", "mono_off_drift_ms", "n_judge", "n_judge_confirm",
           "n_judge_exited", "n_judge_noresp", "n_judge_stall", "n_judge_stall_helper", "n_judge_linkdown", "n_judge_taken", "judge_causes", "stall_ctx",
           "weak_cause_n", "timeout_judge_n", "judge_any_n", "fin_judge_dev_min_ms", "fin_judge_dev_max_ms", "n_rst_surv",
           "n_rst_confirm", "n_rst_exited", "rst_judge_dev_min_ms", "rst_judge_dev_max_ms", "rst_exited_kill_judge_min_ms",
           "rst_exited_kill_judge_max_ms", "rst_judge_ms_min", "rst_judge_ms_max", "kill_judge_ms_min", "kill_judge_ms_max",
           "kill_judge_exited_min_ms", "kill_judge_exited_max_ms", "kill_judge_clock", "stop_judge_ms_min",
           "stop_judge_ms_max", "judge_spread_ms", "judge_spread_clock", "judge_to_publish_ms", "kill_to_publish_ms",
           "publish_clock", "hold_ms_max", "hold_other_n", "kill_hold_ms_min", "hold_after_restore_n", "probe_timeout_n", "probe_fail_n",
           "end_after_kill_ms", "suspect_n", "suspect_stale_ms_min",
           "suspect_stale_ms_max", "read_n", "read_ok_n", "read_success_pct", "dev_read_n", "dev_read_ok_n",
           "read_page_success_pct", "read_dev_success_pct", "probe_missing", "read_lat_med_us_max", "read_lat_max_us",
           "beat_gap_max_ms", "page_torn_n", "witness_lost_n", "confirm_alive_n", "fence_sent", "fenced", "fence_order_ok",
           "fence_names_ok", "fence_sent_to_fenced_ms", "fenced_to_fallback_ms", "cont_target_present",
           "win_changed_after", "win_lines_n", "win_missing", "win_unreadable", "win_checked", "win_verified",
           "ctrlsum_missing", "ctrlsum_fields_missing", "dead_log_missing",
           "spare_state", "final_gen_n", "resume_refusal", "resume_why_refused", "ring_not_live_class", "tl_rank",
           "tl_inject", "tl_clock", "t_suspect_ms", "t_judge_ms", "t_block_ms", "t_fenced_ms", "t_fenced_src",
           "t_la_fenced_ms", "t_publish_ms", "t_first_ok_ms", "t_first_ok_step", "la_exited_n", "la_exit_silent_n", "la_fence_sigkill_n", "la_fenced_n",
           "la_fenced_after_sigkill_ms", "la_later_n", "la_act_refused_why", "la_stop_n", "la_refused_signal_n",
           "la_pid_mismatch_n", "la_qp_err_n", "launcher_same", "launcher_ready", "launcher_scope", "launcher_stale",
           "la_spare_spawn_n", "la_spare_respawn_n", "la_spare_cap_expected_n", "spare_hello_after_ms", "spare2_inc_want",
           "spare2_inc_got", "spare2_daemon_ok", "tcp_ctrl_bytes", "tcp_data_bytes",
           "tcp_ctrl_conn_n", "witness_pairs", "witness_expected", "ring_live_pairs", "tcp_record_bytes_prelive",
           "tcp_record_bytes_unsplit", "tcp_conns_lib", "witness_conns_lib", "ring_live_n", "ring_live_all",
           "ring_live_ms_max", "rank_stop_n", "rank_la_sock_lost_n", "ss_tcp_conn_n", "ss_pids_both", "ss_tx_delta_bytes",
           "ss_rx_delta_bytes", "ss_excluded", "rec_lost_n", "rec_dup_n", "rec_repair_n", "sendq_deferred", "sendq_max",
           "rnr_n", "async_n", "active_mtu_kv_min", "active_mtu_rain", "active_mtu_sunny", "ckpt_stable_in_mute",
           "ckpt_void_in_mute", "helper_reconnect_n", "qperr_pair_sent_by_target", "qperr_rec_gen_delta",
           "qperr_probe_gen_delta", "qperr_pair_read_fail", "qperr_records_after", "rejoin_dropped", "rejoin_resent",
           "rejoin_accept_n", "rejoin_accept_dup_n", "fail_to_spare_n", "inject", "inject_ok", "inject_off_ms",
           "inject_dur_off_ms", "pair_gap_ms", "ckpt_stable_before_inj", "kill2_after_armed", "stable_between_pair_kills",
           "subject_fenced", "gate_real", "old_go_ms", "fenced_go_ms", "gate_diff_ms", "second_thread_ms", "pidfd_ms", "z_ms",
           "fenced_after_second_ms", "fenced_vs_pidfd_abs_ms", "gate_src", "cost_probe_evidence", "cost_probe_window",
           "cost_probe_inwindow_lb", "cost_probe_expected",
           # 2026-10-27: the counterexample cells (gc4_quiet12000, gc4_gpuhang12000_waitpend_fence)
           "suspect_any_n", "hold_any_n", "spare_used", "quiet_ms", "quiet_periods", "quiet_lb_detail", "waiter",
           "waiter_judge_n", "waiter_judge_ms_min", "waiter_judge_ms_max", "waiter_judge_causes", "waiter_fenced",
           "waiter_hold_n", "waiter_given_up_n", "waitpend_kv", "waitpend_long_n", "waitpend_ms_max", "waitpend_result",
           # 2026-10-27, pilot 5 (gc4_gpuhang12000_waiter_hung, gc4_gpuhang12000_cycle; pilot-only cells)
           "hang_lines", "judged_ranks",
           # 2026-10-27 after pilot 5 (waiter_not_judged): the waiting rule's lines naming the waiter
           "wait_peer", "wait_ended_progress", "wait_ended_nogress"]


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


def proc_logs(stem):
    """every rank and spare process log of a trial (the --stops path, which has no row): their events, node unknown"""
    ps = sorted(glob.glob(stem + "_r[0-9]*.log")) + sorted(glob.glob(stem + "_spare*.log"))
    return [evs(rows_rs.stamped(p), "?") for p in ps]


def rank_stops(lalog, plogs):
    """F6 (REVIEW_INT3): the rank side's "(STOP_launcher" lines and its launcher Unix socket loss lines, every rank and spare
    process, before the trial's first trial_end marker (receipt clock; the whole log without the marker)"""
    ends = [e.t for nd in ("rain", "sunny") for e in lalog[nd] if LA_MARK_END.search(e.text)]
    t_end = min(ends) if ends else float("inf")
    stop = sum(1 for lg in plogs for e in lg if e.t <= t_end and LA_STOP.search(e.text))
    sock = sum(1 for lg in plogs for e in lg if e.t <= t_end and LA_UNIX.search(e.text) and not LA_STOP.search(e.text))
    return stop, sock


def ss_deltas(ssl, s1, s2_, both):
    """the ss bytes acked / received between the runner's two snapshots, over the processes alive at both reads only
    (EXPERIMENT 8, 2026-10-24 after pilot 2). A process absent at a read is left out and named in ss_excluded:
    "<pid>:absent_s1" (present=0 or no line at the first), "<pid>:absent_s2" (at the second), "<pid>:no_s2" (no second
    snapshot at all). ss sums a process's sockets, so a socket that closed between the reads (the survivors' sockets to a
    rank killed in that window: pilot 2 a5 mi4_seg_4k, 8 -> 6 and 10 -> 7 sockets, -23 712 B) takes its bytes out of the
    second sum: a live process's negative delta is a data problem, never a 0. Then the delta is empty, ss_excluded names
    it ("<pid>:negative"), and the scorer reads the trial as 자료 부족 for a rule on that column (score_gc.REQUIRED_COLS)"""
    seen = sorted({m.group(2) for m in ssl}, key=int)
    no_s2 = not any(m.group(1) == "s2" for m in ssl)
    exc = ["%s:absent_s1" % p for p in seen if p not in s1]
    exc += ["%s:%s" % (p, "no_s2" if no_s2 else "absent_s2") for p in sorted(s1, key=int) if p not in s2_]
    out = {"ss_tx_delta_bytes": "", "ss_rx_delta_bytes": ""}
    tx = {p: int(s2_[p].group(5)) - int(s1[p].group(5)) for p in both}
    rx = {p: int(s2_[p].group(6)) - int(s1[p].group(6)) for p in both}
    neg = sorted((p for p in both if tx[p] < 0), key=int)
    exc += ["%s:negative" % p for p in neg]
    if both and not neg:
        out["ss_tx_delta_bytes"] = sum(tx.values())
    if both and all(v >= 0 for v in rx.values()):  # reported only, the same rule
        out["ss_rx_delta_bytes"] = sum(rx.values())
    out["ss_excluded"] = "+".join(exc)
    return out


def la_counts(lalog, s, meta=None, plogs=None):
    """the launcher counts every trial gets: STOP lines (both forms; the spare-absent cells' one expected cap line apart),
    refused signals and pid-check failures over the whole logs; the QP-loss lines of ranks other than the subject after the
    trial_start marker and before the first is-leaving. The second kill's rank (meta kill2_rank: gin-mirror's two-death
    cells) is a subject too and left out the same way (2026-10-24 after pilot 2: a4 stopped on rank 3's two record-QP
    loss lines in mi4_kill2_kill3_ow). la_stop_n adds the rank side's STOP_launcher lines and its launcher Unix socket
    loss lines (plogs: the trial's process logs; F6)"""
    k2 = str((meta or {}).get("kill2_rank", ""))
    subjects = {s} | ({int(k2)} if k2.isdigit() else set())
    whole = lalog["rain"] + lalog["sunny"]
    after = la_after_start(lalog["rain"]) + la_after_start(lalog["sunny"])
    stops = [e for e in sorted(whole, key=lambda x: x.t) if LA_STOP.search(e.text)]
    capx = [e for e in stops if LA_CAP0.search(e.text)][:1] if cap_expected(meta) else []
    rk_stop, rk_sock = rank_stops(lalog, plogs or [])
    out = {"la_stop_n": len(stops) - len(capx) + rk_stop + rk_sock, "la_spare_cap_expected_n": len(capx),
           "rank_stop_n": rk_stop, "rank_la_sock_lost_n": rk_sock,
           "la_refused_signal_n": sum(1 for e in whole if LA_REFSIG.search(e.text)),
           "la_pid_mismatch_n": sum(1 for e in whole if LA_PIDMIS.search(e.text))}
    t_leave = min((e.t for e in after if LA_LEAVING.search(e.text)), default=float("inf"))
    out["la_qp_err_n"] = sum(1 for e in after for m in [LA_QPLOST.search(e.text)] if m and e.t < t_leave
                             and int(m.group(1) or m.group(2)) not in subjects)
    return out


def first(evl, rx, pred=None):
    for e in sorted(evl, key=lambda x: x.t):
        m = rx.search(e.text)
        if m and (pred is None or pred(m)):
            return e, m
    return None, None


def witness_view(evl, me, n, init=None):
    """B3 (REVIEW_INT3): one process's view, its lines in file order: (went live, {peer: {incarnation of the peer: opened}}).
    init {peer: incarnation}: the peer's incarnation when this process starts (0 for a rank's own process; a spare's from the
    restore order, ring_pairs). The live line opens the helper socket (the witness) of every peer without an earlier witness
    line; a REJOIN taken from a peer's new incarnation, or a spare's own line naming the incarnation of the peer it rejoins
    (RJ_PEER_INC), starts a new pair (EXPERIMENT 8: a revived incarnation's pair is a new pair); "reconnected" opens
    the pair's socket, "unknown, re-dialled" (the UD REJOIN: no socket yet) closes it again (the "reconnected gen=1
    attempts=0" line just before it is the fd -1 install, REVIEW_INT3 F10). A socket's end never undoes "opened". A
    reconnect after the socket's end and before the new incarnation's REJOIN line is that new pair's (a TCP REJOIN).
    Every "reconnected" and "re-dialled" line belongs to the peer's current incarnation in this view (the lines name none)"""
    peers = [p for p in range(n) if p != me]
    init = init or {}
    cur = {p: int(init.get(p, 0)) for p in peers}
    segs = {p: {cur[p]: None} for p in peers}
    lost, carry = dict.fromkeys(peers, False), dict.fromkeys(peers, False)
    live = False
    for e in evl:
        x = e.text
        m = LIVE.search(x)
        if m and int(m.group(1)) == me:
            live = True
            for p in peers:
                if segs[p][cur[p]] is None:
                    segs[p][cur[p]] = True
            continue
        m = RJ_INC.search(x) or RJ_PEER_INC.search(x)
        if m and int(m.group(1)) == me:
            p, i = (int(m.group(2)), int(m.group(3))) if m.group(2) else (int(m.group(4)), int(m.group(5)))
            if p in segs and i not in segs[p]:
                segs[p][i] = True if carry[p] else None
                cur[p], lost[p], carry[p] = i, False, False
            continue
        m = RECONN.search(x)
        if m and int(m.group(1)) == me and int(m.group(2)) in segs:
            p = int(m.group(2))
            carry[p] = carry[p] or lost[p]
            segs[p][cur[p]] = True
            continue
        m = REDIAL.search(x)
        if m and int(m.group(1)) == me and int(m.group(2)) in segs:
            p = int(m.group(2))
            segs[p][cur[p]], carry[p] = False, False
            continue
        m = CLOSED.search(x)
        if m and int(m.group(1)) == me and int(m.group(2)) in segs and "liveness=left" not in x:
            lost[int(m.group(2))] = True
    return live, segs


def final_generation(logs, spare_logs, n):
    """{rank: (its last incarnation's log, incarnation)}: a spare that logged its restore and went live replaces the rank's
    earlier process (the highest incarnation wins); else the rank's own log (incarnation 0)"""
    fin = {r: (logs[r], 0) for r in range(n)}
    for sl in spare_logs:
        m = next((mm for e in sl for mm in [SPARE_INC.search(e.text)] if mm), None)
        if m is None:
            continue
        r, i = int(m.group(1)), int(m.group(2))
        if r in fin and i > fin[r][1] and any(LIVE.search(e.text) and int(LIVE.search(e.text).group(1)) == r for e in sl):
            fin[r] = (sl, i)
    return fin


def restore_order(spare_logs):
    """[(receipt time of the restore line, rank, incarnation)] of every spare that logged its restore, oldest first"""
    out = []
    for sl in spare_logs:
        for e in sl:
            m = SPARE_INC.search(e.text)
            if m:
                out.append((e.t, int(m.group(1)), int(m.group(2))))
                break
    return sorted(out)


def peer_incs_at(order, me, t, n):
    """{peer: its incarnation when a spare of rank me restored at receipt time t}: the highest incarnation of each peer whose
    restore line came earlier (2026-10-24 after pilot 3: the second spare rejoins rank 2's incarnation 1, restored before)"""
    inc = {p: 0 for p in range(n) if p != me}
    for tr, r, i in order:
        if tr < t and r in inc and i > inc[r]:
            inc[r] = i
    return inc


def ring_pairs(logs, spare_logs, n):
    """(pairs of the final generation live at both ends, those with the socket opened at both ends). Each process's sockets
    are attributed to the incarnation pair its own lines name (witness_view), a spare's peers starting at the incarnations
    restored before it (restore order); only the final generation's pairs count (2026-10-24 after pilot 3)"""
    fin = final_generation(logs, spare_logs, n)
    order = restore_order(spare_logs)
    view = {}
    for r in range(n):
        lg, i = fin[r]
        t = next((e.t for e in lg if SPARE_INC.search(e.text)), None) if i > 0 else None
        view[r] = witness_view(lg, r, n, peer_incs_at(order, r, t, n) if t is not None else None)
    live_n = opened_n = 0
    for a in range(n):
        for b in range(a + 1, n):
            if not (view[a][0] and view[b][0]):
                continue
            live_n += 1
            opened_n += int(view[a][1][b].get(fin[b][1]) is True and view[b][1][a].get(fin[a][1]) is True)
    return live_n, opened_n


def ctrl_split(d, k):
    """one control summary's TCP bytes of kind k (record, data) after and before the process's ring went live: the library's
    tcp_<k>_bytes_live= or _prelive= split when the line has one, else known only when the total is 0; (None, None) unknown"""
    tot = fnum(d.get("tcp_%s_bytes" % k)) or 0
    lv, pre = fnum(d.get("tcp_%s_bytes_live" % k)), fnum(d.get("tcp_%s_bytes_prelive" % k))
    if lv is not None:
        return lv, tot - lv
    if pre is not None:
        return tot - pre, pre
    return (0.0, 0.0) if tot == 0 else (None, None)


def mtu_bytes(v):
    """an MTU in bytes: the ibv_mtu enum (1..5: 256..4096 B, the library's active_mtu= and min_active_mtu=) or a byte value
    (256 and up, the runner's ibv_devinfo reading) as it stands; None otherwise (Codex review 2026-10-23 item 1)"""
    x = fnum(v)
    if x is None:
        return None
    if x == int(x) and 1 <= x <= 5:
        return 128 << int(x)
    return int(x) if x >= 256 else None


def _norm(t):
    return " ".join(str(t).replace("_", " ").split())


def refusal_class(whys):
    """config when a refused rank's reason names a configuration (CONFIG_REFUSALS), else prep; "" without a refusal"""
    whys = [w for w in whys if w]
    if not whys:
        return ""
    return "config" if any(_norm(c) in _norm(w) for w in whys for c in CONFIG_REFUSALS) else "prep"


def _num(d, k, dflt=None):
    return rows_rs.num(d, k, dflt)


def exact_rs(d):
    """gin-restore's data check of one final process (rows_rs.rs_row's exact)"""
    return (_num(d, "recv_bad", 1) == 0 and _num(d, "xhist_bad", 1) == 0 and _num(d, "dev_bad", 1) == 0 and
            _num(d, "x_match", 0) == 1 and _num(d, "sig_exact", 0) == 1)


def exact_ow(d):
    """gin-mirror's (rows_mi's exact_mi): the data check and no poison"""
    return exact_rs(d) and (_num(d, "recv_poison", 0) or 0) == 0 and (_num(d, "dev_poison", 0) or 0) == 0


def revived_ok(d):
    return bool(d) and _num(d, "revived", 0) == 1 and _num(d, "exit", 1) == 0 and _num(d, "steps_done", -1) == _num(d, "steps", -2)


def final_data(stem, n, dead, meta):
    """Codex review 2026-10-23 item 2: data equality over the active processes of the final generation (one death). A rank
    that did not die is its own process; a dead rank (killed, or ended by the fence) is the spare that revived as it (kv
    revived=1), which must have finished and be exact; a dead rank whose spare did not revive fails when a spare was there
    for it (the restore was expected) and contributes nothing without one (fail-fast: gin-restore's survivors). A spare
    whose rank did not die (the warm spare of a fault-free or transparent cell) is unused and contributes nothing.
    Returns (data_equal, ow_data_equal, spare_state, final_gen_n)"""
    kv = {r: rows_rs.parse_kv("%s_r%d.kv" % (stem, r)) for r in range(n)}
    spares = [rows_rs.parse_kv(stem + "_spare.kv")] if os.path.exists(stem + "_spare.kv") else []
    states, finals, missing = [], [], False
    for d in spares:
        used = _num(d, "revived", 0) == 1
        if _num(d, "rank", -1) in dead:
            states.append("restored" if (used and revived_ok(d) and exact_ow(d)) else ("restored_bad" if used else "not_restored"))
        else:
            states.append("revived_unexpected" if used else "unused")
    for r in range(n):
        if r not in dead:
            finals.append(kv[r])
            continue
        sp = [d for d in spares if _num(d, "rank", -1) == r]
        if not sp:
            missing = missing or meta.get("spare") == "1"  # the restore's spare was asked and left no kv
            continue
        if revived_ok(sp[-1]):
            finals.append(sp[-1])
        else:
            missing = True
    de = int(bool(finals) and not missing and all(exact_rs(d) for d in finals))
    ow = int(bool(finals) and not missing and all(exact_ow(d) for d in finals))
    return de, ow, "+".join(states), len(finals)


def proc_name(stem, path):
    """a process log's name in ctrlsum_missing: r<k> for a rank, spare / spare_2nd for the spare logs"""
    return os.path.basename(path)[len(os.path.basename(stem)) + 1:-len(".log")]


def ctrlsum_required(stem, n, sp_paths, sp_logs, dead):
    """the names of required_procs (r<k>, spare, spare_2nd, ...)"""
    return [nm for nm, _ in required_procs(stem, n, sp_paths, sp_logs, dead)]


def required_procs(stem, n, sp_paths, sp_logs, dead):
    """Codex review 2026-10-23 (control summary): the processes that must leave a control summary, the final generation
    (final_data's rule): a rank that did not die is its own process (r<k>); a rank with a spare that became active (its
    log's "restored as incarnation I" line, else its kv's revived=1, incarnation the spare's order) is that spare, the highest
    incarnation when two did; a dead rank (dead: the killed ranks) without an active spare and an unused spare need none.
    Codex re-check 2026-10-23: the spares are every _spare*.kv and _spare*.log (a spare whose .log is missing while its kv
    says revived=1 stays required; the caller names it <proc>:nolog), not only the logs that exist.
    Returns [(name, rank)] in rank order (2026-10-23 probe fix: the probe summaries' requirement reuses it)"""
    lg_of = dict(zip(sp_paths, sp_logs))
    names = sorted({proc_name(stem, p) for p in sp_paths} |
                   {os.path.basename(p)[len(os.path.basename(stem)) + 1:-len(".kv")] for p in glob.glob(stem + "_spare*.kv")})
    act = {}
    for i, nm in enumerate(names):
        p = "%s_%s.log" % (stem, nm)
        m = next((mm for e in lg_of.get(p, []) for mm in [SPARE_INC.search(e.text)] if mm), None)
        if m is not None:
            r, inc = int(m.group(1)), int(m.group(2))
        else:
            d = rows_rs.parse_kv(p[:-len(".log")] + ".kv") if os.path.exists(p[:-len(".log")] + ".kv") else {}
            if _num(d, "revived", 0) != 1 or _num(d, "rank", -1) is None:
                continue
            r, inc = int(_num(d, "rank", -1)), i + 1
        if 0 <= r < n and (r not in act or inc > act[r][1]):
            act[r] = (nm, inc)
    return [(act[r][0] if r in act else "r%d" % r, r) for r in range(n) if r in act or r not in dead]


# the probe summary's device line (2026-10-23, Codex finding 1): the page's own line names it ("device line named|none",
# 2a-2-C) and, since ctxall, its context count ("contexts=n"); the summary says dev_line=0|1 for the peer it read
PAGEDEV = re.compile(r"GIN/RC: rank (\d+): status page up \(.*?\bdevice line (named|none)\b")
PAGECTX = re.compile(r"GIN/RC: rank (\d+): status page up \(.*?\bcontexts=(\d+)\b")
DEV_KEYS = ("dev_reads", "dev_ok")


def page_devs(evl):
    """{rank: (device line named on its page: True/False/None, its context count or None)} from the status page lines (any
    process, any incarnation: named on any of them counts as named)"""
    out = {}
    for e in evl:
        m = PAGEDEV.search(e.text)
        mc = PAGECTX.search(e.text)
        if not (m or mc):
            continue
        r = int((m or mc).group(1))
        nm, cx = out.get(r, (None, None))
        if m:
            nm = bool(nm) or m.group(2) == "named"
        if mc:
            cx = max(cx or 0, int(mc.group(2)))
        out[r] = (nm, cx)
    return out


def ctx_list(v):
    """'a/b/..' -> [a, b, ..] (ints); None when absent or not numbers"""
    if v in (None, ""):
        return None
    try:
        return [int(x) for x in str(v).split("/")]
    except ValueError:
        return None


def dev_expected(d, peer, pdev):
    """the summary's peer named a device line: its dev_line=1, or the peer's own page line says named"""
    return d.get("dev_line") == "1" or bool(pdev.get(peer, (None, None))[0])


def ctx_expected(d, peer, pdev):
    """the number of contexts whose device READs the summary must list: its dev_ctx=, else the peer page's contexts= when
    above 1 (one context: dev_reads is that context's), else None"""
    k = fnum(d.get("dev_ctx"))
    if k is not None:
        return int(k)
    c = pdev.get(peer, (None, None))[1]
    return c if (c or 0) > 1 else None


def probe_cols(sums, req, pdev):
    """Codex finding 1 (2026-10-23): the READ probe's counts over every probe summary, with the gaps that make them unknown.
    sums: [(proc, rank, peer, kv)] every summary of the trial; req: required_procs (the final generation), each of which
    must have one summary per peer of the final generation (the library writes one line per peer with a READ QP at the
    teardown); pdev: page_devs. A summary whose peer named a device line must carry dev_reads= and dev_ok= (and, with more
    than one context, dev_reads_ctx= and dev_ok_ctx= of that many values). Page READs are reads - after_end_reads (the
    READs after the peer's end apart: REVIEW_TEST fix 18), the device READs dev_reads (every context's sum). The gaps
    ("proc:p<peer>" for a missing summary, "proc:p<peer>:<field>" for a missing counter) are in probe_missing; a missing
    summary empties every count, a missing page / device counter its side's counts, and any gap read_success_pct: an
    unknown count is never 0"""
    out = {c: "" for c in ("read_n", "read_ok_n", "dev_read_n", "dev_read_ok_n", "read_page_success_pct",
                           "read_dev_success_pct", "read_success_pct", "probe_missing", "page_torn_n")}
    if not sums and not req:
        return out
    fin = {r for _, r in req}
    gaps, gap_sum, gap_page, gap_dev = [], False, False, False
    for nm, r in req:
        for p in sorted(fin - {r}):
            if not any(pp == nm and peer == p for pp, _, peer, _ in sums):
                gaps.append("%s:p%d" % (nm, p))
                gap_sum = True
    for nm, _, p, d in sums:
        for k in ("reads", "ok"):
            if fnum(d.get(k)) is None:
                gaps.append("%s:p%d:%s" % (nm, p, k))
                gap_page = True
        if dev_expected(d, p, pdev):
            for k in DEV_KEYS:
                if fnum(d.get(k)) is None:
                    gaps.append("%s:p%d:%s" % (nm, p, k))
                    gap_dev = True
            kx = ctx_expected(d, p, pdev)
            if kx is not None:
                for k in ("dev_reads_ctx", "dev_ok_ctx"):
                    v = ctx_list(d.get(k))
                    if v is None or len(v) != kx:
                        gaps.append("%s:p%d:%s" % (nm, p, k))
                        gap_dev = True
    out["probe_missing"] = "+".join(dict.fromkeys(gaps))
    g = lambda d, k: fnum(d.get(k)) or 0
    pr = int(sum(g(d, "reads") - g(d, "after_end_reads") for *_, d in sums))
    po = int(sum(g(d, "ok") - g(d, "after_end_ok") for *_, d in sums))
    dr = int(sum(g(d, "dev_reads") for *_, d in sums))
    do = int(sum(g(d, "dev_ok") for *_, d in sums))
    pct = lambda a, b: r1(100.0 * a / b) if b else ""
    if sums and not gap_sum:  # torn= as before: summed where the summary has it (reported, no rule needs it)
        out["page_torn_n"] = int(sum(g(d, "torn") for *_, d in sums))
    if not (gap_sum or gap_page):
        out["read_n"], out["read_ok_n"], out["read_page_success_pct"] = pr, po, pct(po, pr)
    if not (gap_sum or gap_dev):
        out["dev_read_n"], out["dev_read_ok_n"], out["read_dev_success_pct"] = dr, do, pct(do, dr)
    if not gaps:
        out["read_success_pct"] = pct(po + do, pr + dr)
    return out


def proc_sums(named_logs):
    """[(proc, rank, peer, kv)] of every probe summary in [(proc, its events)]"""
    return [(nm, int(m.group(1)), int(m.group(2)), kvd(m.group(3))) for nm, lg in named_logs for e in lg
            for m in [PROBESUM.search(e.text)] if m]


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
        # 2026-11-18: a survivor without its own judgement that applied another rank's confirmed abort decision about the
        # subject (its decline names the subject as the peer and its reason starts with ABORT_DECIDED(rank <subject>,)
        taken = 0
        for r in surv:
            if r in js:
                continue
            lg = logs[r] if not (r == kr and kr2 >= 0) else slog
            if any(m and int(m.group(2)) == s and int(m.group(3)) == s for e in lg for m in [ADTAKEN.search(e.text)]):
                taken += 1
        out["n_judge_taken"] = taken
        out["judge_causes"] = "+".join("%s:%d" % (c, sum(1 for _, (_, k) in js.items() if k == c))
                                       for c in sorted({k for _, (_, k) in js.items()}))
        # stall_ctx (2026-10-24, decision (가)): the context each STALL judgement names (its line, else its last suspect line)
        sc = set()
        for r, (je, k) in js.items():
            if k != "STALL":
                continue
            cm = CTXTOK.search(je.text)
            if cm is None:
                lg = logs[r] if not (r == kr and kr2 >= 0) else slog
                su = [e for e in lg for m in [SUSPECT.search(e.text)] if m and int(m.group(2)) == s and e.t <= je.t
                      and CTXTOK.search(e.text)]
                cm = CTXTOK.search(max(su, key=lambda x: x.t).text) if su else None
            sc.add(cm.group(1) if cm else "none")
        out["stall_ctx"] = "+".join(sorted(sc)) if sc else ""
        out["probe_timeout_n"] = sum(1 for r, (je, _) in js.items() for e in logs[r] for m in [TIMEOUTL.search(e.text)]
                                     if m and int(m.group(2)) == s and e.t <= je.t)
        out["probe_fail_n"] = sum(1 for r, (je, _) in js.items() for e in logs[r] for m in [READFAILL.search(e.text)]
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
        if st_ev is None:
            st_ev, _ = first(logs[s], SW_GPUHANG)
        if st_ev is None:  # 2026-10-27: the quiet computation's start (no judgement is expected there; reported)
            st_ev, _ = first(logs[s], SW_QUIET)
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
    spare_all = [evs(rows_rs.stamped(p), sp_node) for p in sorted(glob.glob(stem + "_spare*.log"))]
    if lalog["rain"] or lalog["sunny"] or ctrl == "rdma":
        out.update(la_counts(lalog, s, meta, [logs[r] for r in ranks] + spare_all))
    # F7: every rank's ring live within the setup bound (its first line -> its live line, one process: mono or receipt)
    if ctrl == "rdma" and any(logs[r] for r in ranks):
        lt = []
        for r in ranks:
            le, _ = first(logs[r], LIVE, lambda m, _r=r: int(m.group(1)) == _r)
            d = xd(min(logs[r], key=lambda x: x.t), le)[0] if (le is not None and logs[r]) else None
            lt.append(d if (d is not None and d <= LIVE_BOUND_MS) else None)
        out["ring_live_n"] = sum(1 for d in lt if d is not None)
        out["ring_live_all"] = int(out["ring_live_n"] == n)
        out["ring_live_ms_max"] = r1(max(d for d in lt if d is not None)) if out["ring_live_n"] else ""
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
    # the page-dependent counts: empty when no process brought its status page up (the library does not run it yet)
    if ws:
        sus = [fnum(m.group(4)) for e in every for m in [SUSPECT.search(e.text)] if m and (s < 0 or int(m.group(2)) == s)]
        out["suspect_n"] = len(sus)
        out["suspect_stale_ms_min"], out["suspect_stale_ms_max"] = mm(sus) if sus else ("", "")
        # 2026-10-27 (Codex review of the counterexample design, item 6): every SUSPECT line of the trial, whatever rank it
        # names and whichever process logged it (suspect_n counts the subject only)
        out["suspect_any_n"] = sum(1 for e in every if SUSPECT.search(e.text))
        out["witness_lost_n"] = sum(1 for e in every if WITLOST.search(e.text))
        out["confirm_alive_n"] = sum(1 for e in every for m in [CONF_CLOSE.search(e.text)] if m and m.group(3) == "alive")
    # 2026-10-27: every hold start (any rank, any subject, every rank and spare log) and whether a spare was used (a spare
    # restored as an incarnation, a survivor's "restored as incarnation" line, or a launcher's ACCEPTED activation)
    out["hold_any_n"] = sum(1 for e in every if HOLD_OF.search(e.text))
    la_all = la_after_start(lalog["rain"]) + la_after_start(lalog["sunny"])
    out["spare_used"] = int(any(SPARE_INC.search(e.text) or RESTORED_OF.search(e.text) for e in every) or
                            any(m and m.group(2) == "ACCEPTED" for e in la_all for m in [LA_ACT.search(e.text)]))
    # the window check (Codex review 2026-10-23 item 3): changed= of every line, unreadable= and checked= (when the line
    # has them) and whether every survivor reported the line for the subject (the line names no incarnation today: any
    # line naming the subject counts). The fence predicate win_verified is 1 only when every survivor's line is there,
    # no sample was unreadable (and checked > 0 when the line says checked=) and changed = 0; win_changed_after is the
    # changed sum when the samples are complete, or when a change was seen anyway, else empty (unknown, never "0 changes")
    # (Codex review 2026-10-23, control summary): a line without changed= or unreadable= leaves the window incomplete
    # (win_verified 0, win_changed_after and the sum it lacks empty) and is listed in win_missing as "rank:field"
    wl = [(e, m, kvd(m.group(4) or "")) for e in every for m in [WINCHG.search(e.text)] if m]
    if wl:
        fl = [(int(m.group(1)), k) for _, m, d in wl for k in ("changed", "unreadable") if fnum(d.get(k)) is None]
        chg = sum(int(fnum(d.get("changed")) or 0) for _, _, d in wl)
        unr = [fnum(d.get("unreadable")) for _, _, d in wl]
        chk = [fnum(d.get("checked")) for _, _, d in wl]
        out["win_unreadable"] = "" if any(x is None for x in unr) else int(sum(unr))
        out["win_checked"] = int(sum(x for x in chk if x is not None)) if any(x is not None for x in chk) else ""
        complete = not fl and out["win_unreadable"] == 0 and all(x is None or x > 0 for x in chk)
        fmis = ["%d:%s" % x for x in fl]
        if s >= 0:
            have = {int(m.group(1)) for e, m, _ in wl if int(m.group(2)) == s}
            miss = [r for r in surv if r not in have]
            out["win_lines_n"] = len(have & set(surv))
            out["win_missing"] = "+".join([str(r) for r in miss] + fmis)
            complete = complete and not miss
            out["win_verified"] = int(complete and chg == 0)
        elif fmis:
            out["win_missing"] = "+".join(fmis)
        out["win_changed_after"] = chg if (complete or (chg > 0 and not fl)) else ""
    # the control summaries: each process's last one. Codex review 2026-10-23 (control summary): the processes of the final
    # generation must each have one (ctrlsum_required); a required process without one leaves every summary column empty
    # (ctrlsum_missing names it), and a counter a column reads that is absent from a required summary leaves that column
    # empty (ctrlsum_fields_missing "proc:field"); an absent counter is never 0. The sums still run over every summary
    sp_paths = sorted(glob.glob(stem + "_spare*.log"))
    bk0 = int(base["kill_rank"]) if str(base.get("kill_rank", "")).isdigit() else -1
    req = ctrlsum_required(stem, n, sp_paths, spare_all, {bk0, kr2})
    named = {}
    for nm, lg in [("r%d" % r, logs[r]) for r in ranks] + [(proc_name(stem, p), lg) for p, lg in zip(sp_paths, spare_all)]:
        l = [m for e in lg for m in [CTRLSUM.search(e.text)] if m]
        if l:
            named[nm] = kvd(l[-1].group(2))
    cs = list(named.values())
    cs_miss = [p for p in req if p not in named]
    out["ctrlsum_missing"] = "+".join(p + ("" if os.path.exists("%s_%s.log" % (stem, p)) else ":nolog") for p in cs_miss)
    # the dead original ranks need no summary, but a missing .log of one is flagged (Codex re-check 2026-10-23)
    out["dead_log_missing"] = "+".join("r%d" % r for r in sorted({bk0, kr2}) if 0 <= r < n
                                       and not os.path.exists("%s_r%d.log" % (stem, r)))
    fmiss = []
    if cs and not cs_miss:
        reqd = [named[p] for p in req]
        lack = lambda *ks: [p + ":" + k for p in req for k in ks if fnum(named[p].get(k)) is None]
        def sm(*ks):  # the sum of the counters ks over every summary; None when a required summary lacks one
            bad = lack(*ks)
            fmiss.extend(x for x in bad if x not in fmiss)
            return None if bad else int(sum(fnum(d.get(k)) or 0 for d in cs for k in ks))
        e0 = lambda v: "" if v is None else v
        wit_on = meta.get("witness", "1") != "0"
        out["tcp_record_bytes_sum"] = e0(sm("tcp_record_bytes"))
        out["tcp_data_bytes"] = e0(sm("tcp_data_bytes"))
        out["tcp_conns_lib"], out["witness_conns_lib"] = e0(sm("tcp_conns")), e0(sm("witness_conns"))  # reported only
        if ctrl == "rdma":
            # B3 (REVIEW_INT3, the coordinator's rule): (a) the TCP bytes after each process's ring went live; the bootstrap
            # records before it apart (tcp_record_bytes_prelive; a process whose summary cannot split them adds its total to
            # tcp_record_bytes_unsplit and leaves tcp_ctrl_bytes empty); (b), (c) the witness sockets opened per pair of the
            # final generation (a revived incarnation's pairs replace the old ones) against the pairs that went live
            if sm("tcp_record_bytes", "tcp_data_bytes") is not None:
                sp = [(ctrl_split(d, "record"), ctrl_split(d, "data"), d) for d in cs]
                unk = [d for (rl, _), (dl, _), d in sp if rl is None or dl is None]
                out["tcp_ctrl_bytes"] = "" if unk else int(sum(rl + dl for (rl, _), (dl, _), _ in sp))
                out["tcp_record_bytes_prelive"] = int(sum(rp for (_, rp), _, _ in sp if rp is not None))
                out["tcp_record_bytes_unsplit"] = int(sum(fnum(d.get("tcp_record_bytes")) or 0 for d in unk))
                for p in req:  # a nonzero total without its live/prelive split (tcp_ctrl_bytes is then empty)
                    fmiss.extend("%s:tcp_%s_bytes_live" % (p, k) for k in ("record", "data") if None in ctrl_split(named[p], k))
        else:  # the tcp control builds: the library's sums (no ring, no live line)
            out["tcp_ctrl_bytes"] = e0(sm("tcp_record_bytes", "tcp_data_bytes"))
            out["tcp_ctrl_conn_n"] = e0(sm("tcp_conns"))
            wc = sm("witness_conns")
            out["witness_pairs"] = (e0(wc) if wit_on else 0)
            out["witness_expected"] = (n - 1) * len(cs) if wit_on else 0
        for c, k in (("rec_lost_n", "records_lost"), ("rec_dup_n", "records_dup"), ("rec_repair_n", "repairs"),
                     ("sendq_deferred", "sendq_deferred"), ("async_n", "async")):
            out[c] = e0(sm(k))
        if sm("sendq_max") is not None:
            out["sendq_max"] = int(max(fnum(d.get("sendq_max")) or 0 for d in cs))
        port = 0
        for nd in ("rain", "sunny"):
            b0, a0 = fnum(meta.get("rnr_before_" + nd)), fnum(meta.get("rnr_after_" + nd))
            if b0 is not None and a0 is not None:
                port += int(a0 - b0)
        rn = sm("rnr")
        out["rnr_n"] = "" if rn is None else rn + port
    out["ctrlsum_fields_missing"] = "+".join(fmiss)
    # the READ probe (Codex finding 1, 2026-10-23): every summary of every rank and spare process; the page READs and the
    # device-line READs (every context) both count in read_success_pct; the final generation's processes (required_procs,
    # as for the control summary) must each have one summary per peer of it, and a summary whose peer named a device line
    # its dev_* counters (probe_cols). Only a trial whose probe ran (a status page line or a summary) has these columns
    named_logs = [("r%d" % r, logs[r]) for r in ranks] + [(proc_name(stem, p), lg) for p, lg in zip(sp_paths, spare_all)]
    sums = proc_sums(named_logs)
    if pg or sums:
        out.update(probe_cols(sums, required_procs(stem, n, sp_paths, spare_all, {bk0, kr2}),
                              page_devs([e for _, lg in named_logs for e in lg])))
        ps = [d for *_, d in sums]
        g = lambda k: [fnum(d.get(k)) for d in ps if fnum(d.get(k)) is not None]
        out["read_lat_med_us_max"] = max(g("lat_med_us")) if g("lat_med_us") else ""
        out["read_lat_max_us"] = max(g("lat_max_us")) if g("lat_max_us") else ""
        out["beat_gap_max_ms"] = max(g("beat_gap_max_ms")) if g("beat_gap_max_ms") else ""
    # 2026-10-27, the quiet computation (GC_QUIET_IT on the subject): quiet_periods, a lower bound of the complete probe
    # periods inside the injection window in which every registered GIN context of the subject was read quiet, the least
    # over the observers (every other rank's own process, its last probe summary for the subject):
    #   P_w = floor(window / probe_ms) - 1, window = the subject's quiet end line - its quiet start line (one process's
    #         mono_ms), probe_ms = probe_ms_page: the complete periods inside the window, at least;
    #   X_O = dev_ctx x reads - dev_quiet: the context READs of the whole run that the observer did not count quiet (work
    #         pending, failed, bad, or not issued in a period whose page READ was), each spoiling at most one period;
    #   quiet_periods = min over O of max(0, P_w - X_O).
    # A context that is always quiet (the subject's receiving context) cannot raise it: a period counts only with every
    # context quiet. No end line (the subject ended inside the window): 0, a measured failure; an observer without its
    # summary or one of reads, dev_ctx, dev_quiet: empty (자료 부족 through probe_missing)
    if s >= 0 and QUIET_ENV.search(" ".join(meta.get(k, "") or "" for k in ("r0_env", "r1_env", "r2_env", "r3_env"))):
        qs, _ = first(logs[s], SW_QUIET)
        qend, _ = first(logs[s], SW_QUIET_END)
        if qs is not None:
            win = xd(qs, qend)[0] if qend is not None else None
            out["quiet_ms"] = r1(win) if win is not None else ""
            pms = fnum(out["probe_ms_page"]) if out["probe_ms_page"] != "" else None
            last = {}
            for nm, rr, peer, d in sums:
                if nm == "r%d" % rr and rr != s and peer == s:
                    last[rr] = d
            xs = {}
            for rr in surv:
                d = last.get(rr)
                vals = [fnum(d.get(k)) for k in ("reads", "dev_ctx", "dev_quiet")] if d else [None]
                xs[rr] = None if any(v is None for v in vals) else int(vals[1] * vals[0] - vals[2])
            if qend is None or win is None:
                out["quiet_periods"] = 0
                out["quiet_lb_detail"] = "no_end_line"
            elif pms and all(v is not None for v in xs.values()) and xs:
                pw = int(math.floor(win / pms)) - 1
                out["quiet_periods"] = min(max(0, pw - x) for x in xs.values())
                out["quiet_lb_detail"] = "P_w=%d " % pw + " ".join("X_%d=%d" % kv for kv in sorted(xs.items()))
            else:
                out["quiet_lb_detail"] = "missing:" + "+".join(str(rr) for rr, x in sorted(xs.items()) if x is None)
    # 2026-10-27, the waiting rank (meta waiter_rank, the cell's WAITER_RANK): the judgements naming it, per observer process
    # (every rank's and spare's log but the waiter's own), from the subject's injection line (the driver's gpuhang line);
    # what followed it (reported): a fence of it by its launcher, holds of it, their give-ups; the waiter's own long-wait
    # lines (GC_WAITPEND)
    wr = int(meta["waiter_rank"]) if str(meta.get("waiter_rank", "")).isdigit() else -1
    if 0 <= wr < n:
        out["waiter"] = wr
        obs = [("r%d" % r, logs[r]) for r in ranks if r != wr] + [(proc_name(stem, p), lg) for p, lg in zip(sp_paths, spare_all)]
        firsts, causes = [], {}
        for nm, lg in obs:
            jl = [(e, m.group(3)) for e in lg for m in [DEAD.search(e.text) or STALLED.search(e.text)] if m and int(m.group(2)) == wr]
            if jl:
                je, cz = min(jl, key=lambda x: x[0].t)
                firsts.append(je)
                causes[cz] = causes.get(cz, 0) + 1
        out["waiter_judge_n"] = len(firsts)
        # 2026-10-27 after pilot 5: the waiting rule's lines naming the waiter, over the same observers
        peers, ends = set(), set()
        for nm, lg in obs:
            for e in lg:
                m = WAIT_PEER.search(e.text)
                if m and int(m.group(2)) == wr:
                    peers.update(int(x) for x in m.group(3).split(",") if x)
                m = WAIT_ENDED.search(e.text)
                if m and int(m.group(2)) == wr:
                    ends.add(m.group(3))
        out["wait_peer"] = "+".join(str(p) for p in sorted(peers)) or "none"
        out["wait_ended_progress"] = int("progress: " in ends)
        out["wait_ended_nogress"] = int("its peers resolved, no progress within G" in ends)
        out["waiter_judge_causes"] = "+".join("%s:%d" % kv for kv in sorted(causes.items()))
        hang_ev = first(logs[s], SW_GPUHANG)[0] if s >= 0 else None
        if hang_ev is not None and firsts:
            ds = [xd(hang_ev, je)[0] for je in firsts]
            ds = [d for d in ds if d is not None]
            out["waiter_judge_ms_min"], out["waiter_judge_ms_max"] = mm(ds) if ds else ("", "")
        if la_all or lalog["rain"] or lalog["sunny"]:
            out["waiter_fenced"] = int(any(m and int(m.group(1)) == wr for e in la_all
                                           for m in [LA_SIGKILL.search(e.text) or LA_FENCED.search(e.text)]))
        out["waiter_hold_n"] = sum(1 for e in every for m in [HOLD_OF.search(e.text)] if m and int(m.group(2)) == wr)
        out["waiter_given_up_n"] = sum(1 for e in every for m in [GIVEN_UP_OF.search(e.text)] if m and int(m.group(1)) == wr)
        wl_ = [m for e in logs[wr] for m in [WP_LONG.search(e.text)] if m and int(m.group(1)) == wr]
        we_ = [m for e in logs[wr] for m in [WP_END.search(e.text)] if m and int(m.group(1)) == wr]
        out["waitpend_long_n"] = len(wl_)
        out["waitpend_ms_max"] = r1(max(float(m.group(5)) for m in we_)) if we_ else ""
        out["waitpend_result"] = "+".join(sorted({m.group(4) for m in we_})) if we_ else ("open" if wl_ else "")
    # 2026-10-27, pilot 5: who was judged when, from the trial's first GINRS gpuhang line (any rank; the earliest in rain's
    # clock across nodes): per judged rank its first DEAD or STALLED line over every process but the judged rank's own lines
    hang_evs = [e for r in ranks for e in [first(logs[r], SW_GPUHANG)[0]] if e is not None]
    if hang_evs:
        h0 = hang_evs[0]
        for e in hang_evs[1:]:
            d_, _ = xd(h0, e)
            if d_ is not None and d_ < 0:
                h0 = e
        per = {}
        for lg in [logs[r] for r in ranks] + spare_all:
            seen = {}
            for e in lg:
                m = DEAD.search(e.text) or STALLED.search(e.text)
                if m and m.group(1) != m.group(2):
                    t = int(m.group(2))
                    if t not in seen or e.t < seen[t].t:
                        seen[t] = e
            for t, e in seen.items():
                per.setdefault(t, []).append(e)
        jr = []
        for t, es in per.items():
            ds = [d_ for d_ in (xd(h0, e)[0] for e in es) if d_ is not None]
            jr.append((min(ds) if ds else None, t, len(es)))
        jr.sort(key=lambda x: (x[0] is None, x[0] or 0.0, x[1]))
        out["judged_ranks"] = "+".join("%d:%s:%d" % (t, "%.1f" % d_ if d_ is not None else "-", k) for d_, t, k in jr) or "none"
    mtus =[mtu_bytes(d.get("active_mtu")) for d in cs if mtu_bytes(d.get("active_mtu")) is not None]
    if ctrl == "rdma" and any(logs[r] for r in ranks):  # B3 (b), (c): from the lines, with or without a summary
        wit_on = meta.get("witness", "1") != "0"
        live_p, open_p = ring_pairs(logs, spare_all, n)
        out["ring_live_pairs"], out["tcp_ctrl_conn_n"] = live_p, open_p
        out["witness_pairs"] = open_p if wit_on else 0
        out["witness_expected"] = live_p if wit_on else 0
    # item 1 (Codex review 2026-10-23): the kv's and the summaries' active_mtu is the ibv_mtu enum (5 = 4096 B); bytes here
    kvm = [mtu_bytes(rows_rs.parse_kv("%s_r%d.kv" % (stem, r)).get("active_mtu")) for r in ranks]
    kvm = [x for x in kvm if x is not None] or mtus
    out["active_mtu_kv_min"] = int(min(kvm)) if kvm else ""
    for nd in ("rain", "sunny"):
        v = mtu_bytes(meta.get("active_mtu_" + nd))
        out["active_mtu_" + nd] = int(v) if v is not None else ""
    # the runner's ss snapshots (counts only)
    ssl = [m for t, l in rows_rs.stamped(stem + "_ss.out") if t is not None for m in [SSL.search(l)] if m]
    if ssl:
        s1 = {m.group(2): m for m in ssl if m.group(1) == "s1" and m.group(3) == "1"}
        s2_ = {m.group(2): m for m in ssl if m.group(1) == "s2" and m.group(3) == "1"}
        out["ss_tcp_conn_n"] = sum(int(m.group(4)) for m in s1.values())
        both = [p for p in s1 if p in s2_]
        out["ss_pids_both"] = len(both)
        out.update(ss_deltas(ssl, s1, s2_, both))
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
        out["qperr_rec_gen_delta"] = max(gens) - REC_GEN0 if gens else 0  # the delta, not the new gen (pilot 1 problem 4)
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
        # the driver's switch: per rank whose env has GC_GPUHANG_IT=S its line rank=R step=S spin=1, with ctx=k when that
        # rank's env has GC_GPUHANG_CTX=k (2026-10-27, pilot 5: two hung ranks, rank 1 with ctx=3; before it the switch's
        # line anywhere, ctx from the first GC_GPUHANG_CTX of all the envs)
        hang_need = []
        for r in ranks:
            ev_ = meta.get("r%d_env" % r, "") or ""
            hm = HANGIT_ENV.search(ev_)
            if hm:
                hc = HANGCTX_ENV.search(ev_)
                hang_need.append((r, re.compile(r"GINRS gpuhang rank=%d step=%s spin=1 %s" % (r, hm.group(1), ("ctx=%s " % hc.group(1)) if hc else ""))))
        for r, rx in hang_need:
            need.append(("GC_GPUHANG_IT", rx))
        if hang_need:
            hl = []
            for r, _ in hang_need:
                m0 = first(every, SW_GPUHANG, lambda m: int(m.group(1)) == r)[1]
                cm = re.search(r"\bctx=(\w+)", m0.string[m0.end():]) if m0 else None
                hl.append("%d:%s:%s" % (r, m0.group(2), cm.group(1) if cm else "-") if m0 else "%d:-" % r)
            out["hang_lines"] = "+".join(hl)
        elif "GC_GPUHANG_IT" in envs:  # the switch on no rank's env (the spare's): its line anywhere
            hc = HANGCTX_ENV.search(envs)
            need.append(("GC_GPUHANG_IT", re.compile(SW_GPUHANG.pattern + r"ctx=%s " % hc.group(1)) if hc else SW_GPUHANG))
        qe_env = QUIET_ENV.search(envs)
        if qe_env:  # 2026-10-27: the driver's GC_QUIET_IT: its start line (spin=1) with the cell's step and length; the end
            # line is not part of the record (a rank fenced inside the window has none: a measured failure, not missing data)
            need.append(("GC_QUIET_IT", re.compile(r"GINRS quiet rank=\d+ step=%s ms=%s spin=1\b" % qe_env.groups())))
        if need:
            out["inject_ok"] = int(all(any(rx.search(e.text) for e in every) for _, rx in need))
        # 2026-10-27: GC_WAITPEND=1 in a rank's env: that rank's kv must say waitpend=1 (the driver read the switch; the
        # kv is written at the start, so a rank fenced later still has it); missing on any such rank: no injection record
        wp_ranks = [r for r in ranks if WAITPEND_ENV.search(meta.get("r%d_env" % r, "") or "")]
        if wp_ranks:
            wkv = {r: str(rows_rs.parse_kv("%s_r%d.kv" % (stem, r)).get("waitpend", "")) for r in wp_ranks}
            out["waitpend_kv"] = "+".join("%d:%s" % (r, wkv[r] or "-") for r in wp_ranks)
            ok_wp = all(wkv[r] == "1" for r in wp_ranks)
            out["inject_ok"] = int(ok_wp and (out["inject_ok"] in ("", 1)))
        if s >= 0 and "TEST_FREEZE_PAGE" in envs:
            inj_ev = first(logs[s], SW_FREEZE)[0]
        if s >= 0 and "GC_GPUHANG_IT" in envs:
            inj_ev = first(logs[s], SW_GPUHANG)[0]
        if s >= 0 and qe_env:
            inj_ev = first(logs[s], SW_QUIET)[0]
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
    # item 2: data equality over the final generation's active processes (one death; a second death keeps gin-mirror's
    # columns, whose two spares are both needed); spare_state names each spare process's part
    bk = int(base["kill_rank"]) if str(base.get("kill_rank", "")).isdigit() else -1
    if os.path.exists("%s_r0.kv" % stem):
        de, ow, sst, fgn = final_data(stem, n, {bk} if bk >= 0 else set(), meta)
        out["spare_state"], out["final_gen_n"] = sst, fgn
        if kr2 < 0:
            out["data_equal"], out["ow_data_equal"] = de, ow
    # item 4: a Resume refusal's class (config: the reason names a configuration; prep: any other) and a ring that did
    # not go live: config when a rank's setup agreement turned recovery off for an MTU or a control path that differ
    whys = [rows_rs.parse_kv("%s_r%d.kv" % (stem, r)) for r in ranks]
    whys = [d.get("resume_why", "") for d in whys if (_num(d, "resume_rc", 0) or 0) != 0]
    out["resume_refusal"] = refusal_class(whys) or ("prep" if whys else "")  # no reason text: not a named configuration
    pre = "GIN/RS: ncclGinRestoreResume: the restore cannot be enabled on this communicator: "
    out["resume_why_refused"] = " | ".join(sorted({_norm(w).replace(pre, "")[:200] for w in whys if w}))
    if str(out.get("ring_live_all")) == "0":
        offs = {m.group(1) for r in ranks for e in logs[r] for m in [SETUP_OFF.search(e.text)] if m}
        out["ring_not_live_class"] = "config" if offs & set(CONFIG_SETUP_OFF) else "prep"
    # item 6: the event timeline on the subject node's survivor (s xor 2: rank 1 for rank 3), ms after the injection, that
    # node's CLOCK_MONOTONIC (the runner's kill, stop and inject lines and the subject's own lines are that node's too)
    if s >= 0 and inj_ev is not None:
        tr = s ^ 2
        tl = logs.get(tr, []) if tr != kr2 else []
        sw = next((nm for nm, rx in (("gpuhang", SW_GPUHANG), ("freeze", SW_FREEZE), ("die_rst", SW_DIE_RST))
                   if rx.search(inj_ev.text)), "")
        out["tl_rank"], out["tl_inject"] = tr, (kind if kind not in ("", "none") else (sw or "switch"))
        jt = js.get(tr, (None, None))[0]
        aft = lambda e: e.t >= inj_ev.t - 0.001
        def at(rx, g=2, lim=None):
            for e in sorted(tl, key=lambda x: x.t):
                m = rx.search(e.text)
                if m and int(m.group(g)) == s and aft(e) and (lim is None or e.t <= lim.t):
                    return e
            return None
        sus = [x for x in (at(SUSPECT, lim=jt), at(CONF_OPEN, lim=jt), at(TIMEOUTL, lim=jt)) if x is not None]
        ev = {"t_suspect_ms": min(sus, key=lambda x: x.t) if sus else None, "t_judge_ms": jt, "t_block_ms": at(HOLD_OF),
              "t_publish_ms": at(PUB_OF, 1)}
        # the fence time (2026-10-24 after pilot 3: the window line moved to the REJOIN take, 14.2-33.1 ms after the
        # launcher's FENCED): the subject node's launcher FENCED line of this trial (launcher_FENCED); else the survivors'
        # FENCE -> FENCED report line naming the subject (survivor_FENCED: the timeline rank's own, else the earliest of the
        # other rank and spare processes; the buddy that sent the FENCE logs it); only else the window line
        lz = [e for e in la_after_start(lalog[node_of(s)]) for m in [LA_FENCED.search(e.text)] if m and int(m.group(1)) == s]
        ev["t_la_fenced_ms"] = min(lz, key=lambda x: x.t) if lz else None
        fz = at(FENCEDL)
        if fz is None:
            oth = [e for r in ranks if r not in (s, tr) for e in logs.get(r, [])] + [e for lg in spare_all for e in lg]
            fo = [e for e in oth for m in [FENCEDL.search(e.text)] if m and int(m.group(2)) == s and aft(e)]
            fz = min(fo, key=lambda x: x.t) if fo else None
        wz = at(WINCHG)
        if ev["t_la_fenced_ms"] is not None:
            ev["t_fenced_ms"], out["t_fenced_src"] = ev["t_la_fenced_ms"], "launcher_FENCED"
        elif fz is not None:
            ev["t_fenced_ms"], out["t_fenced_src"] = fz, "survivor_FENCED"
        elif wz is not None:
            ev["t_fenced_ms"] = wz
            out["t_fenced_src"] = "window_" + ("fence" if "after the fence" in wz.text else "judgement")
        pub = ev["t_publish_ms"]
        kvt = rows_rs.parse_kv("%s_r%d.kv" % (stem, tr))
        # the driver checks a step's received data on the device (dev_bad, summed into the kv at the end) and prints no
        # per-step verdict: the first step line after the publish with tx_err=0 is the first completed step; it counts
        # as checked only when the rank's kv says dev_bad=0 over every step
        if pub is not None and _num(kvt, "dev_bad", 1) == 0:
            st = [(e, m) for e in sorted(tl, key=lambda x: x.t) for m in [STEPL.search(e.text)]
                  if m and int(m.group(1)) == tr and int(m.group(3)) == 0 and e.t > pub.t]
            if st:
                ev["t_first_ok_ms"] = st[0][0]
                out["t_first_ok_step"] = int(st[0][1].group(2))
        clocks = set()
        for c, e in ev.items():
            if e is not None:
                d, ck = xd(inj_ev, e)
                out[c] = r1(d)
                clocks.add(ck)
        out["tl_clock"] = "+".join(sorted(clocks))
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
    """local/: gate_fenced.cc's lines and gate_proc_gc.py's real-process lines (gate_real 1).
    gate_fenced.cc (gate_src unit; 2026-10-24 after pilot 2): a real child process per trial, the real gate functions on it
    (gdakiRsActExamine, gdakiCtrlActGate), times from the child's own main-thread end on one CLOCK_MONOTONIC: old_go_ms,
    second_thread_ms (the child's own reading of its last thread's end: the independent clock of the event), fenced_go_ms,
    gate_diff_ms; gate_real 1. The FENCED gate's input is the pidfd poll of the same 1 ms sample, so the pidfd readable
    time is the FENCED GO's sample and fenced_vs_pidfd_abs_ms is 0 [소스: ../gate_fenced.cc runTrial]; the check against an
    independent clock is fenced_after_second_ms. The old timeline-model line (GATE) stays gate_real 0 (gate_src model).
    gate_proc_gc.py (gate_src proc): its own pidfd and Z readings; the gate columns only with --gate-bin"""
    rows = []
    for p in sorted(glob.glob(os.path.join(R, "local", "gate_fenced*.log"))):
        for line in open(p, errors="replace"):
            mu = GATEU.search(line)
            if mu:
                o, l2, f, d = float(mu.group(2)), float(mu.group(4)), float(mu.group(5)), float(mu.group(6))
                rid = "%s_t%s" % (os.path.basename(p)[:-4], mu.group(1))
                rows.append({"id": rid, "stem": os.path.join(os.path.dirname(p), rid), "sub": "local", "cell": "gate_fenced",
                             "build": "cpu", "runner": "local", "key": "local:gate_fenced", "gate_real": 1,
                             "gate_src": "unit", "old_go_ms": o, "fenced_go_ms": f, "gate_diff_ms": d,
                             "second_thread_ms": l2, "pidfd_ms": f, "fenced_after_second_ms": r1(f - l2),
                             "fenced_vs_pidfd_abs_ms": 0.0, "tnum": int(mu.group(1)) + 1})
                continue
            m = GATE.search(line)
            if not m:
                continue
            o, f, d, l2 = float(m.group(2)), float(m.group(3)), float(m.group(4)), float(m.group(5))
            rid = "%s_t%s" % (os.path.basename(p)[:-4], m.group(1))
            r = {"id": rid, "stem": os.path.join(os.path.dirname(p), rid), "sub": "local", "cell": "gate_fenced",
                 "build": "cpu", "runner": "local", "key": "local:gate_fenced", "gate_real": 0, "gate_src": "model", "old_go_ms": o,
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
                 "gate_src": "proc", "tnum": int(m.group(1)) + 1}
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


COST_PROBE_ARMS = ("probe-on", "probe-off")  # run_cost_gc.sh: both gcp, NCCL_GIN_TS_PROBE_MS=100 and 0
COST_PEERS = 1  # run_cost_gc.sh: two ranks, one peer each (one summary per rank)


def cost_probe(stem, r):
    """Codex finding 2 (2026-10-23): the probe cost arms need the probe's own evidence in the trial's logs (run_cost_gc.sh:
    two ranks, _r0.log and _r1.log, the plain output without receipt stamps; the library's lines carry mono_ms).
    probe-on: each rank has a probe summary for its peer with page READs (reads - after_end_reads) > 0, and when that peer
    named a device line (dev_line=1 or its page line) dev_reads > 0 and, with dev_ctx= or the peer page's contexts= above
    1, every context's READs (dev_reads_ctx) > 0; and READs inside the measurement window W = [launch_mono_ms,
    launch_mono_ms + kernel_ms] (the driver's kv: gin_ts2.cu tLaunch and tEnd - tLaunch, CLOCK_MONOTONIC like the library's
    mono_ms, same process). The summary has totals only, so the in-window count is bounded (Codex re-check 2026-10-23):
    the span S = [the rank's status page line, its summary] (mono_ms), the period P its page line's probe_ms=, per =
    1 + contexts with the device line on (else 1) READs per period per peer, COST_PEERS peers; the READs outside W are at
    most (floor(L/P) + 1) x COST_PEERS x per for each of the two parts of S outside W of length L > 0 (the most periodic
    READs an interval of L ms holds; at least the ceil(|S \ W| / P) the rule names), cost_probe_inwindow_lb = total
    (page reads - after_end_reads + dev_reads) - that, and it must reach cost_probe_expected = max(1, floor(|W| / P) x
    COST_PEERS x per x 0.5) (half the cadence) -> covers; else reads_outside_window; S not meeting W -> no_overlap; a
    missing launch_mono_ms, kernel_ms, page line or summary mono_ms -> no_time; every one of these is invalid.
    probe-off: no summary, or reads, after_end_reads and dev_reads all 0. Any other arm (tcp): not checked (empty).
    Returns {cost_probe_evidence: "ok" | reasons "r<k>:p<peer>:<why>" "; "-joined | "", cost_probe_window: per rank
    "r<k>:<covers|reads_outside_window|no_overlap|no_time|probe_ms=0>", cost_probe_inwindow_lb, cost_probe_expected:
    per rank "r<k>:<n>"}"""
    arm = r.get("arm", "")
    out = {"cost_probe_evidence": "", "cost_probe_window": "", "cost_probe_inwindow_lb": "", "cost_probe_expected": ""}
    if arm not in COST_PROBE_ARMS:
        return out
    why, win, lbs, exp = [], [], [], []
    ln = {k: [Ev(0.0, mono(x), "?", x) for x in rows_mi._lines("%s_r%d.log" % (stem, k))] for k in (0, 1)}
    pdev = page_devs(ln[0] + ln[1])
    for k in (0, 1):
        p = 1 - k
        sm = [(e, kvd(m.group(3))) for e in ln[k] for m in [PROBESUM.search(e.text)] if m and int(m.group(1)) == k
              and int(m.group(2)) == p]
        g = lambda d, f: fnum(d.get(f))
        if arm == "probe-off":
            for _, d in sm:  # a summary without reads= is no proof of none
                if g(d, "reads") is None or sum(g(d, f) or 0 for f in ("reads", "after_end_reads", "dev_reads")) > 0:
                    why.append("r%d:p%d:reads=%s dev_reads=%s on probe-off" % (k, p, d.get("reads"), d.get("dev_reads")))
            continue
        if not sm:
            why.append("r%d:p%d:no_summary" % (k, p))
            continue
        e, d = sm[-1]
        if g(d, "reads") is None:
            why.append("r%d:p%d:reads_missing" % (k, p))
        elif g(d, "reads") - (g(d, "after_end_reads") or 0) <= 0:
            why.append("r%d:p%d:reads=0" % (k, p))
        if dev_expected(d, p, pdev):
            if g(d, "dev_reads") is None:
                why.append("r%d:p%d:dev_reads_missing" % (k, p))
            elif g(d, "dev_reads") <= 0:
                why.append("r%d:p%d:dev_reads=0" % (k, p))
            kx = ctx_expected(d, p, pdev)
            if kx is not None:
                c = ctx_list(d.get("dev_reads_ctx"))
                if c is None or len(c) != kx:
                    why.append("r%d:p%d:dev_reads_ctx_missing" % (k, p))
                else:
                    why += ["r%d:p%d:ctx%d_reads=0" % (k, p, i) for i, x in enumerate(c) if x <= 0]
        # the READs inside the measurement window, by a bound (the summary has totals only; Codex re-check 2026-10-23)
        kv = rows_rs.parse_kv("%s_r%d.kv" % (stem, k))
        w0, km = fnum(kv.get("launch_mono_ms")), fnum(kv.get("kernel_ms"))
        pu, pm = next(((x, mm) for x in ln[k] for mm in [PAGEUP.search(x.text)] if mm and x.m is not None), (None, None))
        if w0 is None or km is None or e.m is None or pu is None:
            win.append("r%d:no_time" % k)
            why.append("r%d:p%d:no_time" % (k, p))
            continue
        w1, s0, s1 = w0 + km, pu.m, e.m
        P = float(pm.group(2))
        if P <= 0:
            win.append("r%d:probe_ms=0" % k)
            why.append("r%d:p%d:probe_ms=0" % (k, p))
            continue
        if s1 < w0 or s0 > w1 or km <= 0:
            win.append("r%d:no_overlap" % k)
            why.append("r%d:p%d:no_overlap" % (k, p))
            continue
        per = 1 + ((ctx_expected(d, p, pdev) or 1) if dev_expected(d, p, pdev) else 0)  # READs per period per peer
        side = lambda L: (math.floor(L / P) + 1) if L > 0 else 0  # periodic READs an interval of L ms can hold
        outside = (side(w0 - s0) + side(s1 - w1)) * COST_PEERS * per
        total = (g(d, "reads") or 0) - (g(d, "after_end_reads") or 0) + (g(d, "dev_reads") or 0)
        lb = int(total - outside)
        want = max(1, int(math.floor(km / P) * COST_PEERS * per * 0.5))
        lbs.append("r%d:%d" % (k, lb))
        exp.append("r%d:%d" % (k, want))
        if lb >= want:
            win.append("r%d:covers" % k)
        else:
            win.append("r%d:reads_outside_window" % k)
            why.append("r%d:p%d:reads_outside_window" % (k, p))
    out["cost_probe_evidence"] = "; ".join(why) if why else "ok"
    out["cost_probe_window"] = "+".join(win)
    out["cost_probe_inwindow_lb"], out["cost_probe_expected"] = "+".join(lbs), "+".join(exp)
    return out


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
                r.update(cost_probe(stem, r))  # Codex finding 2: a probe arm without its READ evidence is invalid
                if r["cost_probe_evidence"] not in ("", "ok"):
                    r["cost_valid"] = 0
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
    c = la_counts(la_logs(stem), int(subj) if str(subj).isdigit() else -1, meta, proc_logs(stem))
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
