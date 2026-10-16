#!/usr/bin/env python3
"""test_rows_gc.py - gin-control, test side: CPU-only self-test of rows_gc.py and score_gc.py on synthetic trial logs (no
cluster, no verbs device, no GPU). Standard library only.

    test_rows_gc.py [--keep <dir>]     builds a synthetic results folder (a temporary one unless --keep), checks the rows and
                                       the verdicts, prints "self-test: N checks, F failed" and exits 1 on any failure

The synthetic trials (their lines are rows_gc.py's formats, the TODO ones included):
  A  gc4_kill3_ow@gc x 10            a confirm-window judgement (witness FIN, W 30, FIN+NORESP 30.4 ms after the FIN)
  B  gc4_fdhold_sock_kill3@gc x 10   a normal restore judged by the launcher's EXITED (kill + 120 ms), the fd-holder fork line
  C  gc4_fdhold_sock_kill3_noreport@gc x 5   a READ-failure judgement (NORESP kill + 3.9 s), FENCING -> FENCED -> activation
  D  gc4_stop12000_fence@gc x 1      a STOP_launcher line (the launcher refused to signal, FENCE_NAK); a hold over 1 s
  E  gc4_kill3_ow@gc n11 (launchers not ready), n12 (no stable checkpoint before the kill), smoke/ (a smoke trial)
  F  gc4_kill3_ow@gc n13, n14        the second kill of rank 3 by recorded PID: after the armed lines / before them
  G  gc4_none_probe@gc x 10 with torn reads (page_torn_n 5), gc4_none_ow@gc x 5
  H  local/gate_fenced.log           ten "gate_fenced trial" lines
"""
import argparse, os, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rows_gc  # noqa: E402
import score_gc  # noqa: E402

N = 4
BASE = {"rain": 500000.0, "sunny": 900000.0}  # each node's CLOCK_MONOTONIC (ms) at receipt time 0
GOOD = dict(init_rc=0, reg_rc=0, devcomm_rc=0, resume_rc=0, resume_why="none", steps=600, steps_done=600, released=0,
            recv_bad=0, xhist_bad=0, dev_bad=0, x_match=1, sig_exact=1, reexec_any=0, async_n=0, exit=0, recv_poison=0,
            dev_poison=0, rs_hooks_live=1, workload="overwrite", overwrite=1, train=0, ring=4, mirror_env=1,
            checksum_env="off", active_mtu=4096)
CHECKS = [0, 0]


def check(cond, what):
    CHECKS[0] += 1
    if not cond:
        CHECKS[1] += 1
        print("FAIL " + what)


def node(r):
    return "rain" if r % 2 == 0 else "sunny"


def ln(nd, t, text):
    """a stamped line of node nd at receipt time t (s) with that node's mono_ms (the receipt delay is 0 here)"""
    return (t, "%.6f %s mono_ms=%.3f" % (t, text, BASE[nd] + t * 1000.0))


def kvline(d):
    return " ".join("%s=%s" % kv for kv in d.items()) + "\n"


def write(path, lines):
    with open(path, "w") as f:
        f.write("\n".join(x for _, x in sorted(lines)) + ("\n" if lines else ""))


def trial(d, cell, k, *, build="gc", kill=3, subject=3, witness="1", fence="lineage", inject="kill_traffic", lines=None,
          spare=True, la=None, kout=None, injout=None, meta_extra=None, ctrlsum=True, page=True, probe=None, killed=True):
    """one synthetic run_gc.sh trial; lines: {rank or 'spare': [(t, text)]} in receipt seconds"""
    os.makedirs(d, exist_ok=True)
    stem = os.path.join(d, "%s_%s_n%d" % (cell, build, k))
    lines = lines or {}
    rcs = {r: (137 if (killed and r == kill) else 0) for r in range(N)}
    meta = dict(cell=cell, lib=build, ctrl="rdma" if build in ("gc", "gcp") else "tcp", n=N, policy="hold", restore=1,
                witness=witness, fence=fence, kill_rank="" if kill is None else kill,
                subject_rank="" if subject is None else subject, inject=inject, inj_plan_rt="2.000000",
                spare=int(spare), spare_wanted=int(spare), spare_ready=int(spare), spare_rank=3, launcher_ready=1,
                launcher_before_rain="pid=10,start=100,alive=1,ready=1,log_bytes=0",
                launcher_after_rain="pid=10,start=100,alive=1,ready=1,log_bytes=900",
                launcher_before_sunny="pid=20,start=200,alive=1,ready=1,log_bytes=0",
                launcher_after_sunny="pid=20,start=200,alive=1,ready=1,log_bytes=900",
                active_mtu_rain=4096, active_mtu_sunny=4096, rnr_before_rain=0, rnr_after_rain=0, rnr_before_sunny=0,
                rnr_after_sunny=0, gpu_apps_before="0/0", driver="gin_mi", runner="gcr", hold="C1", kill2_kind="-",
                r0_env="", r1_env="", r2_env="", r3_env="", spare_env="", wall_s=6.0)
    meta.update({"r%drc" % r: rcs[r] for r in range(N)})
    meta.update(meta_extra or {})
    with open(stem + "_meta.txt", "w") as f:
        f.write(kvline(meta))
    for r in range(N):
        dead = killed and r == kill
        kv = dict(rank=r, init_rc=0, reg_rc=0, devcomm_rc=0, resume_rc=0, steps=600, rs_hooks_live=1, workload="overwrite",
                  overwrite=1, train=0, ring=4, mirror_env=1, checksum_env="off") if dead else dict(GOOD, rank=r)
        with open("%s_r%d.kv" % (stem, r), "w") as f:
            f.write(kvline(kv))
        nd = node(r)
        L = [(0.0, "%.6f GINRS start rank=%d mode=live" % (0.0, r))]
        if page:
            L.append(ln(nd, 0.5, "host NCCL WARN GIN/RC: rank %d: status page up (448 B in use, probe_ms=100 stall_ms=10000 W=30)" % r))
        L += [ln(nd, t, x) for t, x in lines.get(r, [])]
        if not dead:
            if probe is not None:
                L.append(ln(nd, 9.0, probe(r)))
            if ctrlsum:
                L.append(ln(nd, 9.1, "GIN/RC: rank %d: control summary tcp_record_bytes=0 tcp_data_bytes=0 tcp_conns=%d "
                                     "witness_conns=%d records_lost=0 records_dup=0 repairs=0 sendq_deferred=0 sendq_max=0 "
                                     "rnr=0 async=0 active_mtu=4096" % (r, 3 if witness == "1" else 0, 3 if witness == "1" else 0)))
        else:
            L.append((1.9, "%.6f GINRS step rank=%d step=100 released=0" % (1.9, r)))
        write("%s_r%d.log" % (stem, r), L)
    if spare:
        with open(stem + "_spare.kv", "w") as f:
            f.write(kvline(dict(GOOD, rank=3, mode="spare", resume_step=100, revived=1, start_step=101)))
        S = [(0.0, "0.000000 GINRS start rank=3 mode=spare"), (1.0, "1.000000 GINRS spare_ready rank=3 rt_s=1.0")]
        S += [ln("sunny", t, x) for t, x in lines.get("spare", [])]
        if ctrlsum:
            S.append(ln("sunny", 9.2, "GIN/RC: rank 3: control summary tcp_record_bytes=0 tcp_data_bytes=0 tcp_conns=0 "
                                      "witness_conns=0 records_lost=0 records_dup=0 repairs=0 sendq_deferred=0 sendq_max=0 rnr=0 async=0 active_mtu=4096"))
        write(stem + "_spare.log", S)
    if kout is None and killed and inject in ("kill_traffic", "fd_holder_kill"):
        kout = [ln("sunny", 2.0, "GINRS killed rank=%d node=sunny pid=999 which=first" % kill)]
    if kout:
        write(stem + "_kill.out", kout)
    if injout:
        write(stem + "_inject.out", injout)
    for nd in ("rain", "sunny"):
        write("%s_launcher_%s.log" % (stem, nd), [ln(nd, t, "GIN/LA: node %d: %s" % (0 if nd == "rain" else 1, x))
                                                  for t, x in (la or {}).get(nd, [])])
    return stem


def restore_lines(subject, t_judge, cause, survivors=(0, 1, 2), t_pub=None, buddy_fence=None, extra=None):
    """the survivors' lines for a restore of subject judged at t_judge (receipt s)"""
    t_pub = t_pub if t_pub is not None else t_judge + 0.150
    L = {r: [] for r in range(N)}
    L["spare"] = []
    L[subject] = [(0.4, "GIN/RS: rank %d: checkpoint 80 stable at buddy rank %d (armable)" % (subject, subject ^ 1))]
    for r in survivors:
        L[r] += [(t_judge, "host NCCL WARN GIN/TS: rank %d: rank %d judged dead (cause=%s)" % (r, subject, cause)),
                 (t_judge + 0.001, "GIN/RS: rank %d: hold of rank %d started: gates odd since 0.0 ms before the start, 0 WQE(s) "
                                   "rung, deadline in 19997 ms, HOLDING to buddy rank %d, 4 QP(s)" % (r, subject, subject ^ 1)),
                 (t_pub, "GIN/RS: rank %d: restore round with rank %d published (4 QP(s))" % (r, subject)),
                 (t_pub + 0.010, "GIN/RS: rank %d: rank %d restored as incarnation 1 (on time); state armed" % (r, subject)),
                 (t_pub - 0.020, "GIN/RS: rank %d: rank %d's spare rejoined as incarnation 1 (20.0 ms after the hold start)" % (r, subject))]
    b = subject ^ 1
    fz = buddy_fence or [(t_judge + 0.002, "GIN/RC: rank %d: rank %d (incarnation 0) fence FENCED (by EXITED from node 1)" % (b, subject))]
    L[b] += fz + [(t_judge + 0.040, "GIN/RS: rank %d: every survivor holds rank %d: its spare activated (incarnation 1, 39.0 ms "
                                    "after this rank's hold start), 0 'later' answers over 0.0 ms" % (b, subject))]
    for k, v in (extra or {}).items():
        L[k] += v
    return L


def probe_ok(torn=0):
    return lambda r: ("GIN/RC: rank %d: probe summary peer=%d reads=300 ok=300 remacc=0 noresp=0 timeout=0 gen=0 lat_med_us=6.1 "
                      "lat_max_us=40.0 beat_gap_max_ms=4.0 torn=%d" % (r, (r + 1) % N, torn if r == 0 else 0))


def build(R):
    raw = os.path.join(R, "raw")
    # A: the confirm-window judgement (witness FIN at 2.0002, W 30, FIN+NORESP 30.4 ms later)
    for k in range(1, 11):
        ex = {r: [(2.0002, "GIN/TS: rank %d: socket to rank 3 closed cause=FIN" % r),
                  (2.0002, "GIN/RC: rank %d: confirm window for rank 3 opened by FIN W=30" % r),
                  (2.0306, "GIN/RC: rank %d: confirm window for rank 3 closed: NORESP" % r)] for r in (0, 1, 2)}
        trial(raw, "gc4_kill3_ow", k, lines=restore_lines(3, 2.0306, "FIN+NORESP", extra=ex), probe=probe_ok(),
              la={"sunny": [(2.110, "rank 3 incarnation 0 EXITED (its pidfd is readable: the thread group ended)")]})
    # B: the normal restore judged by EXITED (kill + 120 ms), the fd holder
    for k in range(1, 11):
        L = restore_lines(3, 2.120, "EXITED")
        L[3] += [(0.6, "GIN/TS: rank 3: test switch FD_HOLDER=sock: child gin_fdhold pid=4242 holds 1 fd(s)")]
        trial(raw, "gc4_fdhold_sock_kill3", k, inject="fd_holder_kill", lines=L, probe=probe_ok(),
              meta_extra={"fdhold": 1, "fdhold_pid": 4242, "fdhold_line": 1},
              la={"sunny": [(2.119, "rank 3 incarnation 0 EXITED (its pidfd is readable: the thread group ended)")]})
    # C: the READ-failure judgement (NORESP kill + 3.9 s), FENCING -> FENCED -> activation, witness off
    for k in range(1, 6):
        fz = [(5.901, "GIN/RC: rank 2: rank 3 (incarnation 0) fence FENCING: FENCE sent to the launcher of node 1"),
              (5.903, "GIN/RC: rank 2: rank 3 (incarnation 0) fence FENCED (by FENCED from node 1)")]
        ex = {r: [(2.5, "GIN/RC: rank %d: probe of rank 3 timed out (no CQE in 500 ms)" % r)] for r in (0, 1, 2)}
        L = restore_lines(3, 5.900, "NORESP", buddy_fence=fz, extra=ex)
        L[3] += [(0.6, "GIN/TS: rank 3: test switch FD_HOLDER=sock: child gin_fdhold pid=4243 holds 0 fd(s)")]
        trial(raw, "gc4_fdhold_sock_kill3_noreport", k, witness="0", inject="fd_holder_kill", lines=L, probe=probe_ok(),
              meta_extra={"fdhold": 1},
              la={"sunny": [(2.12, "rank 3 incarnation 0 exited; EXITED not sent (test switch NO_EXIT_REPORT)"),
                            (5.902, "FENCE of rank 3 incarnation 0 from rank 2: already ended; FENCED"),
                            (5.902, "rank 3 incarnation 0 FENCED: it had ended before the FENCE (already exited)")]})
    # D: a STOP_launcher line (FENCE_NAK) in a stall cell; a hold of 1.4 s; the runner's stop/cont lines
    L = {r: [(12.05, "GIN/RC: rank %d: rank 3 (incarnation 0) judged stalled (liveness stall judged (STALL)); STALLED to 2 rank(s)" % r),
             (12.06, "GIN/RS: rank %d: hold of rank 3 started: gates odd since 0.0 ms before the start" % r),
             (13.46, "GIN/RS: rank %d: the restore of rank 3 (incarnation 0) is given up (FENCE_NAK) in state HELD" % r)]
         for r in (0, 1, 2)}
    L[2] += [(12.07, "GIN/RC: rank 2: rank 3 (incarnation 0) fence FENCING: FENCE sent to the launcher of node 1")]
    trial(raw, "gc4_stop12000_fence", 1, kill=None, inject="sigstop", lines=L, probe=probe_ok(), killed=False,
          meta_extra={"stop_rank": 3, "stop_ms": 12000},
          injout=[ln("sunny", 2.0, "GINRS stop rank=3 pid=999 stop_ms=12000"),
                  ln("sunny", 14.0, "GINRS cont rank=3 pid=999 present=1 stopped_ms=12000.3")],
          la={"sunny": [(12.08, "FENCE of rank 3 incarnation 0 from rank 2: refused to signal: no pidfd held for it (STOP_launcher)")]})
    with open(os.path.join(R, "STOP_launcher"), "w") as f:
        f.write("2026-10-17 00:00:00 hold C9: gc4_stop12000_fence_gc_n1: sunny launcher: 1 line(s) (STOP_launcher)\n")
    # E: excluded trials and a smoke trial
    trial(raw, "gc4_kill3_ow", 11, lines=restore_lines(3, 2.0306, "FIN+NORESP"), probe=probe_ok(),
          meta_extra={"launcher_ready": 0})
    L = restore_lines(3, 2.0306, "FIN+NORESP")
    L[3] = []  # no stable checkpoint of rank 3 before its kill (rank 0's own is there)
    L[0].append((0.4, "GIN/RS: rank 0: checkpoint 80 stable at buddy rank 1 (armable)"))
    trial(raw, "gc4_kill3_ow", 12, lines=L, probe=probe_ok())
    trial(os.path.join(R, "smoke_20261017"), "gc4_kill3_ow", 1, lines=restore_lines(3, 2.0306, "FIN+NORESP"), probe=probe_ok(),
          meta_extra={"hold": "P0"})
    # F: the second kill of rank 3 by recorded PID: n13 after the survivors' armed lines (2.6), n14 before them
    for k, t2 in ((13, 3.0), (14, 2.4)):
        L = restore_lines(3, 2.0306, "FIN+NORESP")
        for r in (0, 1, 2):
            L[r].append((2.6, "GIN/RS: rank %d: rank 3 armed at its stable checkpoint 140" % r))
        ko = [ln("sunny", 2.0, "GINRS killed rank=3 node=sunny pid=999 which=first"),
              ln("sunny", t2, "GINRS killed rank=3 node=sunny pid=1001 which=second")]
        trial(raw, "gc4_kill3_ow", k, lines=L, probe=probe_ok(), kout=ko,
              meta_extra={"kill2_rank": 3, "kill2_kind": "pid_after_armed", "armed2_rt": "2.600000"})
    # a negative case: a judgement whose cause is the witness FIN alone (a weak cause in the rdma build)
    trial(raw, "gc4_kill3_ow", 15, lines=restore_lines(3, 2.0306, "FIN"), probe=probe_ok())
    # G: torn reads in the no-fault probe cell, and the clean no-fault cell
    for k in range(1, 11):
        trial(raw, "gc4_none_probe", k, kill=None, subject=None, inject="none", spare=False, killed=False,
              lines={r: [(1.0, "GIN/RS: rank %d: input pause for rank 0's checkpoint 20 ended (ok) pause_us=2300" % r)] for r in range(N)},
              probe=probe_ok(torn=5))
    for k in range(1, 6):
        trial(raw, "gc4_none_ow", k, kill=None, subject=None, inject="none", spare=False, killed=False, probe=probe_ok(),
              lines={r: [(1.0, "GIN/RS: rank %d: input pause for rank 0's checkpoint 20 ended (ok) pause_us=8100" % r)] for r in range(N)})
    # H: the CPU program gate_fenced
    os.makedirs(os.path.join(R, "local"), exist_ok=True)
    with open(os.path.join(R, "local", "gate_fenced.log"), "w") as f:
        for t in range(10):
            sec = 500 + (t % 7) - 3
            f.write("gate_fenced trial %d: old GO at 0 ms, FENCED GO at %d ms (diff %d ms, second thread %d ms)\n" % (t, sec, sec, sec))
        f.write("gate_fenced: 10/10 trials show the FENCED gate waits about 500 ms longer than Z=GO; 24 checks, 0 failed\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", default=None)
    a = ap.parse_args()
    R = a.keep or tempfile.mkdtemp(prefix="gc_selftest_")
    if a.keep:
        shutil.rmtree(R, ignore_errors=True)
        os.makedirs(R)
    build(R)
    rows = {r["id"]: r for r in rows_gc.all_rows(R) if r["sub"] in ("raw", "local")}
    A = rows["gc4_kill3_ow_gc_n1"]
    check(A["n_judge"] == 3 and A["n_judge_confirm"] == 3 and A["weak_cause_n"] == 0, "A: three confirm-window judgements %r" % A["judge_causes"])
    check(A["fin_judge_dev_min_ms"] == 0.4 and A["fin_judge_dev_max_ms"] == 0.4, "A: FIN -> judgement - W = 0.4 ms (%r, %r)" % (A["fin_judge_dev_min_ms"], A["fin_judge_dev_max_ms"]))
    check(A["confirm_w_ms"] == 30, "A: W 30 from the status page line")
    check(abs(A["kill_judge_ms_min"] - 30.6) < 0.01 and A["kill_judge_clock"] == "mono+receipt", "A: kill -> judgement 30.6 ms, mono on sunny, receipt across (%r %r)" % (A["kill_judge_ms_min"], A["kill_judge_clock"]))
    check(A["wait_held"] == 1 and A["ow_data_equal"] == 1 and A["revived_done"] == 1, "A: the restore succeeded")
    check(A["tcp_ctrl_bytes"] == 0 and A["tcp_ctrl_conn_n"] == A["witness_pairs"] == 9 and A["active_mtu_kv_min"] == 4096, "A: no tcp control bytes, conns = witness")
    check(A["fenced"] == 1 and A["fence_order_ok"] == 1 and A["fence_names_ok"] == 0, "A: FENCED (by EXITED) before the activation, no FENCE sent")
    check(A["la_exited_n"] == 1 and A["la_stop_n"] == 0 and A["launcher_same"] == 1, "A: the launcher's EXITED")
    B = rows["gc4_fdhold_sock_kill3_gc_n1"]
    check(B["n_judge_exited"] == 3 and abs(B["kill_judge_exited_min_ms"] - 120.0) < 0.01 and abs(B["kill_judge_ms_max"] - 120.0) < 0.01, "B: EXITED 120 ms after the kill")
    check(B["inject_ok"] == 1 and B["inject_off_ms"] == 0.0, "B: the fd-holder injection record")
    C = rows["gc4_fdhold_sock_kill3_noreport_gc_n1"]
    check(C["n_judge_noresp"] == 3 and abs(C["kill_judge_ms_min"] - 3900.0) < 0.01, "C: NORESP 3.9 s after the kill (%r)" % C["kill_judge_ms_min"])
    check(C["fence_names_ok"] == 1 and C["fence_order_ok"] == 1 and abs(C["fence_sent_to_fenced_ms"] - 2.0) < 0.01, "C: FENCING -> FENCED -> activation")
    check(C["timeout_judge_n"] == 0 and C["la_exit_silent_n"] == 1 and C["la_fenced_n"] == 1 and C["witness_pairs"] == 0, "C: no timeout judgement, the silent exit, witness off")
    D = rows["gc4_stop12000_fence_gc_n1"]
    check(D["la_stop_n"] == 1 and D["la_refused_signal_n"] == 1, "D: the STOP_launcher line counted")
    check(D["n_judge_stall"] == 3 and abs(D["stop_judge_ms_min"] - 10050.0) < 0.01 and D["hold_ms_max"] == 1400.0, "D: stall judgement 10 050 ms after STOP, hold 1.4 s (%r %r)" % (D["stop_judge_ms_min"], D["hold_ms_max"]))
    check(D["cont_target_present"] == 1 and D["fence_sent"] == 1 and D["fenced"] == 0, "D: CONT found the PID; FENCE sent, no FENCED")
    check(rows["gc4_kill3_ow_gc_n13"]["kill2_after_armed"] == 1 and rows["gc4_kill3_ow_gc_n14"]["kill2_after_armed"] == 0, "F: the second kill after / before the armed lines")
    import csv as _csv
    kj = [p for p in _csv.DictReader(open(score_gc.PREDS, encoding="utf-8")) if p["id"] == "kill_judge_rdma"][0]["acceptance"]
    kj = kj[len("count("):kj.rindex(")")]
    W = rows["gc4_kill3_ow_gc_n15"]
    check(W["weak_cause_n"] == 3 and not score_gc.s2.cond_true(kj, W) and score_gc.s2.cond_true(kj, A),
          "negative: a FIN-only judgement fails kill_judge_rdma's per-trial rule, the confirm-window one passes")
    G = rows["gc4_none_probe_gc_n1"]
    check(G["page_torn_n"] == 5 and G["read_success_pct"] == 100.0 and G["beat_gap_max_ms"] == 4.0 and G["suspect_n"] == 0, "G: torn reads counted, READ 100 %")
    check(G["judge_any_n"] == 0 and G["ckpt_pause_ms"] == 2.3, "G: no judgement, pause 2.3 ms")
    gate = [r for r in rows.values() if r["key"] == "local:gate_fenced"]
    check(len(gate) == 10 and all(r["old_go_ms"] == 0 for r in gate), "H: ten gate rows")
    # the scorer
    verd, srows = score_gc.score(R)
    st = {r["id"]: r["status"] for r in srows if r["sub"] == "raw"}
    check(st["gc4_kill3_ow_gc_n11"] == "launcher_not_ready", "E: launcher not ready excluded (%s)" % st["gc4_kill3_ow_gc_n11"])
    check(st["gc4_kill3_ow_gc_n12"] == "kill_before_ckpt", "E: the kill before a stable checkpoint excluded (%s)" % st["gc4_kill3_ow_gc_n12"])
    smoke = [r for r in srows if r["sub"].startswith("smoke")]
    check(len(smoke) == 1 and smoke[0]["status"] == "smoke", "E: the smoke trial apart")
    check(st["gc4_kill3_ow_gc_n14"] == "second_before_rearm" and st["gc4_kill3_ow_gc_n13"] == "surplus", "F: the second kill's statuses (%s, %s)" % (st["gc4_kill3_ow_gc_n14"], st["gc4_kill3_ow_gc_n13"]))
    for pid, want in (("kill_judge_rdma", "맞음"), ("finless_exit_report", "맞음"), ("finless_read_fail", "맞음"),
                      ("none_probe_clean", "맞음"), ("gate_fenced", "맞음"), ("no_tcp_control", "맞음"),
                      ("long_hold_lane", "맞음"), ("stall_fence_restore", "자료 부족"), ("restore_time_rdma", "자료 부족"),
                      ("regression_tcp", "자료 부족"), ("cost_probe_lat4k", "자료 부족")):
        check(verd.get(pid) == want, "verdict %s: %s (want %s)" % (pid, verd.get(pid), want))
    md = open(os.path.join(R, "SCORE.md"), encoding="utf-8").read()
    check("`STOP_launcher`(1줄)" in md and "FENCE_NAK 포함): 1줄" in md, "SCORE.md lists the STOP file and the STOP_launcher line")
    check("smoke: 1" in md, "SCORE.md counts the smoke trial apart")
    check(os.path.exists(os.path.join(R, "trials_scored.csv")), "trials_scored.csv written")
    print("self-test: %d checks, %d failed%s" % (CHECKS[0], CHECKS[1], "" if a.keep else " (folder %s removed)" % R))
    if not a.keep:
        shutil.rmtree(R, ignore_errors=True)
    sys.exit(1 if CHECKS[1] else 0)


if __name__ == "__main__":
    main()
