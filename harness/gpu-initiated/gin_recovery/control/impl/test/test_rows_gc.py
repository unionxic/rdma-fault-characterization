#!/usr/bin/env python3
"""test_rows_gc.py - gin-control, test side: CPU-only self-test of rows_gc.py, score_gc.py and the shell pieces that can run
without a cluster (no cluster, no ssh, no verbs device, no GPU). Standard library only.

    test_rows_gc.py [--keep <dir>]     builds a synthetic results folder (a temporary one unless --keep), checks the rows and
                                       the verdicts, prints "self-test: N checks, F failed" and exits 1 on any failure

Synthetic lines use rows_gc.py's formats (the TODO ones included). Each node has its own CLOCK_MONOTONIC (BASE) and sunny's
lines arrive DELAY s late at rain (the ssh delay), so a cross-node interval read on the receipt clock is off by DELAY; the
trials carry run_gc.sh's measured offset unless they say otherwise.
  A  gc4_kill3_ow@gc x 10            a confirm-window judgement (witness FIN, W 30, FIN+NORESP 30.4 ms after the FIN); the
                                     launcher slice starts with an earlier trial's late EXITED before the trial_start marker
  B  gc4_fdhold_sock_kill3@gc x 10   a normal restore judged by the launcher's EXITED (kill + 120 ms), the fd-holder fork line
  C  gc4_fdhold_sock_kill3_noreport@gc x 5   a READ-failure judgement (NORESP kill + 3.9 s), FENCING -> FENCED -> activation
  D  gc4_stop12000_fence@gc x 1      a "(STOP_launcher)" line (FENCE_NAK); a hold over 1 s
  E  gc4_kill3_ow@gc n11 (launchers not ready), n12 (no stable checkpoint before the kill), smoke/ (a smoke trial)
  F  gc4_kill3_ow@gc n13, n14        the second kill of rank 3 by recorded PID after / before the armed lines (reported only)
  G  gc4_none_probe@gc x 10 with torn reads, gc4_none_ow@gc x 5
  H  local/gate_fenced.log (the simulated program: gate_real 0) and local/gate_proc.log (real-process lines, no gate program)
  B1 the active_mtu query handed to the remote shell: one word list (shlex) and 4096 read through a fake ibv_devinfo
  B2 gc4_freeze12000_fence@gc x 5 and gct4_rstgap_live50@gctc x 10, gct4_rstgap_live300@gctc x 5: cells injected by a library
     test switch, with SUBJECT_RANK, judged
  B3 mi4_kill2_kill3_ow@gc: the second kill before the re-arm: counted (scored), its re-image condition false
  B4 "(STOP_launcher: ...)" in the gap before trial_start (n16) and a launcher QP loss (n17): rows_gc.py --stops, the hold's
     tail check on a whole launcher log, and the launcher table read
"""
import argparse, os, shlex, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rows_gc  # noqa: E402
import score_gc  # noqa: E402

N = 4
BASE = {"rain": 500000.0, "sunny": 900000.0}  # each node's CLOCK_MONOTONIC (ms) at receipt time 0 on rain
DELAY = {"rain": 0.0, "sunny": 0.004}         # receipt delay of a node's lines at rain (s)
OFFSET = {"mono_off_sunny_ms": BASE["sunny"] - BASE["rain"], "mono_off_rtt_ms": 0.2,
          "mono_off_after_ms": BASE["sunny"] - BASE["rain"] + 0.05, "mono_off_after_rtt_ms": 0.3}
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
    """a stamped line of node nd at its node time t (s): received DELAY[nd] later, with that node's mono_ms"""
    return (t + DELAY[nd], "%.6f %s mono_ms=%.3f" % (t + DELAY[nd], text, BASE[nd] + t * 1000.0))


def raw_line(t, text):
    return (t, "%.6f %s" % (t, text))


def kvline(d):
    return " ".join("%s=%s" % kv for kv in d.items()) + "\n"


def write(path, lines):
    with open(path, "w") as f:
        f.write("\n".join(x for _, x in sorted(lines)) + ("\n" if lines else ""))


def trial(d, cell, k, *, build="gc", kill=3, subject=3, dead=None, witness="1", fence="lineage", inject="kill_traffic",
          lines=None, spare=True, spare_rank=3, la=None, la_pre=None, kout=None, injout=None, meta_extra=None, ctrlsum=True,
          page=True, probe=None, killed=True, offset=True, ss=True):
    """one synthetic run_gc.sh trial; lines: {rank or 'spare': [(t, text)]} in node seconds; dead: the ranks that died"""
    os.makedirs(d, exist_ok=True)
    stem = os.path.join(d, "%s_%s_n%d" % (cell, build, k))
    lines = lines or {}
    if dead is None:
        dead = [kill] if (killed and kill is not None) else []
    rcs = {r: (137 if r in dead else 0) for r in range(N)}
    rdma = build in ("gc", "gcp")
    meta = dict(cell=cell, lib=build, ctrl="rdma" if rdma else "tcp", n=N, policy="hold", restore=1,
                witness=witness, fence=fence, kill_rank="" if kill is None else kill,
                subject_rank="" if subject is None else subject, inject=inject, inj_plan_rt="2.000000",
                spare=int(spare), spare_wanted=int(spare), spare_ready=int(spare), spare_rank=spare_rank,
                launcher_ready=1 if rdma else "", launcher_table="empty" if rdma else "-",
                launcher_before_rain="pid=10,start=100,alive=1,ready=1,log_bytes=0",
                launcher_after_rain="pid=10,start=100,alive=1,ready=1,log_bytes=900",
                launcher_before_sunny="pid=20,start=200,alive=1,ready=1,log_bytes=0",
                launcher_after_sunny="pid=20,start=200,alive=1,ready=1,log_bytes=900",
                active_mtu_rain=4096, active_mtu_sunny=4096, rnr_before_rain=0, rnr_after_rain=0, rnr_before_sunny=0,
                rnr_after_sunny=0, gpu_apps_before="0/0", driver="gin_mi", runner="gcr", hold="C1", kill2_kind="-",
                r0_env="", r1_env="", r2_env="", r3_env="", spare_env="", wall_s=6.0)
    if not rdma:
        for x in ("launcher_before_rain", "launcher_after_rain", "launcher_before_sunny", "launcher_after_sunny"):
            meta[x] = "-"
    if offset:
        meta.update(OFFSET)
    meta.update({"r%drc" % r: rcs[r] for r in range(N)})
    meta.update(meta_extra or {})
    with open(stem + "_meta.txt", "w") as f:
        f.write(kvline(meta))
    nsum = 0
    for r in range(N):
        is_dead = r in dead
        kv = dict(rank=r, init_rc=0, reg_rc=0, devcomm_rc=0, resume_rc=0, steps=600, rs_hooks_live=1, workload="overwrite",
                  overwrite=1, train=0, ring=4, mirror_env=1, checksum_env="off") if is_dead else dict(GOOD, rank=r)
        with open("%s_r%d.kv" % (stem, r), "w") as f:
            f.write(kvline(kv))
        nd = node(r)
        L = [raw_line(0.0, "GINRS start rank=%d mode=live" % r)]
        if page:
            L.append(ln(nd, 0.5, "host NCCL WARN GIN/RC: rank %d: status page up (448 B in use, probe_ms=100 stall_ms=10000 W=30)" % r))
        L += [ln(nd, t, x) for t, x in lines.get(r, [])]
        if not is_dead:
            if probe is not None:
                L.append(ln(nd, 9.0, probe(r)))
            if ctrlsum:
                w = 3 if witness == "1" else 0
                L.append(ln(nd, 9.1, "GIN/RC: rank %d: control summary tcp_record_bytes=0 tcp_data_bytes=0 tcp_conns=%d "
                                     "witness_conns=%d records_lost=0 records_dup=0 repairs=0 sendq_deferred=0 sendq_max=0 "
                                     "rnr=0 async=0 active_mtu=4096" % (r, w, w)))
                nsum += 1
        else:
            L.append(raw_line(1.9, "GINRS step rank=%d step=100 released=0" % r))
        write("%s_r%d.log" % (stem, r), L)
    if spare:
        sn = node(spare_rank)
        with open(stem + "_spare.kv", "w") as f:
            f.write(kvline(dict(GOOD, rank=spare_rank, mode="spare", resume_step=100, revived=1, start_step=101)))
        S = [raw_line(0.0, "GINRS start rank=%d mode=spare" % spare_rank),
             raw_line(1.0, "GINRS spare_ready rank=%d rt_s=1.0" % spare_rank)]
        S += [ln(sn, t, x) for t, x in lines.get("spare", [])]
        if ctrlsum:
            w = 3 if witness == "1" else 0
            S.append(ln(sn, 9.2, "GIN/RC: rank %d: control summary tcp_record_bytes=0 tcp_data_bytes=0 tcp_conns=%d "
                                 "witness_conns=%d records_lost=0 records_dup=0 repairs=0 sendq_deferred=0 sendq_max=0 rnr=0 "
                                 "async=0 active_mtu=4096" % (spare_rank, w, w)))
        write(stem + "_spare.log", S)
    if kout is None and killed and inject in ("kill_traffic", "fd_holder_kill"):
        kout = [ln("sunny", 2.0, "GINRS killed rank=%d node=sunny pid=999 which=first" % kill)]
    if kout:
        write(stem + "_kill.out", kout)
    if injout:
        write(stem + "_inject.out", injout)
    if ss:
        S = []
        for tag, t in (("s1", 1.0), ("s2", 1.5)):
            for r in range(N):
                S.append(ln(node(r), t, "GINRS ss %s pid=%d present=1 n=5 acked=4096 received=2048" % (tag, 1000 + r)))
        write(stem + "_ss.out", S)
    base = os.path.basename(stem)
    if rdma:
        for nd in ("rain", "sunny"):
            pre = [raw_line(t, "GIN/LA: node %d: %s" % (0 if nd == "rain" else 1, x)) for t, x in (la_pre or {}).get(nd, [])]
            body = [raw_line(t + DELAY[nd], "GIN/LA: node %d: %s" % (0 if nd == "rain" else 1, x)) for t, x in (la or {}).get(nd, [])]
            marks = [raw_line(0.05, "GINLA mark trial_start %s" % base), raw_line(20.0, "GINLA mark trial_end %s" % base)]
            write("%s_launcher_%s.log" % (stem, nd), pre + marks + body)
    return stem


def restore_lines(subject, t_judge, cause, survivors=(0, 1, 2), t_pub=None, buddy_fence=None, extra=None):
    """the survivors' lines for a restore of subject judged at t_judge (node s)"""
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


EXITED3 = "rank 3 incarnation 0 EXITED (its pidfd is readable: the thread group ended)"


def build(R):
    raw = os.path.join(R, "raw")
    # A: the confirm-window judgement (witness FIN at 2.0002, W 30, FIN+NORESP 30.4 ms later); an earlier trial's late EXITED
    # line of rank 3 before this trial's trial_start marker
    for k in range(1, 11):
        ex = {r: [(2.0002, "GIN/TS: rank %d: socket to rank 3 closed cause=FIN" % r),
                  (2.0002, "GIN/RC: rank %d: confirm window for rank 3 opened by FIN W=30" % r),
                  (2.0306, "GIN/RC: rank %d: confirm window for rank 3 closed: NORESP" % r)] for r in (0, 1, 2)}
        trial(raw, "gc4_kill3_ow", k, lines=restore_lines(3, 2.0306, "FIN+NORESP", extra=ex), probe=probe_ok(),
              la={"sunny": [(2.110, EXITED3)]}, la_pre={"sunny": [(0.01, EXITED3)]})
    # B: the normal restore judged by EXITED (kill + 120 ms), the fd holder
    for k in range(1, 11):
        L = restore_lines(3, 2.120, "EXITED")
        L[3] += [(0.6, "GIN/TS: rank 3: test switch FD_HOLDER=sock: child gin_fdhold pid=4242 holds 1 fd(s)")]
        trial(raw, "gc4_fdhold_sock_kill3", k, inject="fd_holder_kill", lines=L, probe=probe_ok(),
              meta_extra={"fdhold": 1, "fdhold_pid": 4242, "fdhold_line": 1}, la={"sunny": [(2.119, EXITED3)]})
    # C: the READ-failure judgement (NORESP kill + 3.9 s), FENCING -> FENCED -> activation, witness off
    for k in range(1, 6):
        fz = [(5.901, "GIN/RC: rank 2: rank 3 (incarnation 0) fence FENCING: FENCE sent to the launcher of node 1"),
              (5.903, "GIN/RC: rank 2: rank 3 (incarnation 0) fence FENCED (by FENCED from node 1)")]
        ex = {r: [(2.5, "GIN/RC: rank %d: probe of rank 3 timed out (no CQE in 500 ms)" % r)] for r in (0, 1, 2)}
        L = restore_lines(3, 5.900, "NORESP", buddy_fence=fz, extra=ex)
        L[3] += [(0.6, "GIN/TS: rank 3: test switch FD_HOLDER=sock: child gin_fdhold pid=4243 holds 0 fd(s)")]
        trial(raw, "gc4_fdhold_sock_kill3_noreport", k, witness="0", inject="fd_holder_kill", lines=L, probe=probe_ok(),
              meta_extra={"fdhold": 1, "launcher_env_rain": "NCCL_GIN_CTRL_TEST_NO_EXIT_REPORT=1",
                          "launcher_env_sunny": "NCCL_GIN_CTRL_TEST_NO_EXIT_REPORT=1"},
              la={"sunny": [(2.12, "rank 3 incarnation 0 exited; EXITED not sent (test switch NO_EXIT_REPORT)"),
                            (5.902, "FENCE of rank 3 incarnation 0 from rank 2: already ended; FENCED"),
                            (5.902, "rank 3 incarnation 0 FENCED: it had ended before the FENCE (already exited)")]})
    # D: a STOP_launcher line (FENCE_NAK) in a stall cell; a hold of 1.4 s; the runner's stop/cont lines
    L = {r: [(12.05, "GIN/RC: rank %d: rank 3 (incarnation 0) judged stalled (liveness stall judged (STALL)); STALLED to 2 rank(s)" % r),
             (12.06, "GIN/RS: rank %d: hold of rank 3 started: gates odd since 0.0 ms before the start" % r),
             (13.46, "GIN/RS: rank %d: the restore of rank 3 (incarnation 0) is given up (FENCE_NAK) in state HELD" % r)]
         for r in (0, 1, 2)}
    L[2] += [(12.07, "GIN/RC: rank 2: rank 3 (incarnation 0) fence FENCING: FENCE sent to the launcher of node 1")]
    L[3] = [(0.4, "GIN/RS: rank 3: checkpoint 80 stable at buddy rank 2 (armable)")]
    trial(raw, "gc4_stop12000_fence", 1, kill=None, inject="sigstop", lines=L, probe=probe_ok(), killed=False,
          meta_extra={"stop_rank": 3, "stop_ms": 12000},
          injout=[ln("sunny", 2.0, "GINRS stop rank=3 pid=999 stop_ms=12000"),
                  ln("sunny", 14.0, "GINRS cont rank=3 pid=999 present=1 stopped_ms=12000.3")],
          la={"sunny": [(12.08, "FENCE of rank 3 incarnation 0 from rank 2: refused to signal: no pidfd held for it (STOP_launcher)")]})
    with open(os.path.join(R, "STOP_launcher"), "w") as f:
        f.write("2026-10-17 00:00:00 hold C9: gc4_stop12000_fence_gc_n1: 1 launcher line(s) (STOP_launcher) or (STOP_launcher: ...)\n")
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
    # a negative case: a judgement whose cause is the witness FIN alone (a weak cause in the rdma build), and no clock offset
    trial(raw, "gc4_kill3_ow", 15, lines=restore_lines(3, 2.0306, "FIN"), probe=probe_ok(), offset=False)
    # B4: the pid-check failure line in the gap before trial_start (n16); a launcher QP loss of rank 1 after it (n17)
    trial(raw, "gc4_kill3_ow", 16, lines=restore_lines(3, 2.0306, "FIN+NORESP"), probe=probe_ok(),
          la_pre={"sunny": [(0.02, "REGISTER of rank 3 incarnation 1 refused: the pidfd is not the peer's process "
                                   "(STOP_launcher: a pidfd that is not the peer's own)")]})
    trial(raw, "gc4_kill3_ow", 17, lines=restore_lines(3, 2.0306, "FIN+NORESP"), probe=probe_ok(),
          la={"sunny": [(1.5, "record QP of rank 1 (incarnation 0, generation 0) lost: the CQ reported an error"),
                        (8.0, "rank 1 incarnation 0 is leaving")]})
    # G: torn reads in the no-fault probe cell, and the clean no-fault cell
    for k in range(1, 11):
        trial(raw, "gc4_none_probe", k, kill=None, subject=None, inject="none", spare=False, killed=False,
              lines={r: [(1.0, "GIN/RS: rank %d: input pause for rank 0's checkpoint 20 ended (ok) pause_us=2300" % r)] for r in range(N)},
              probe=probe_ok(torn=5))
    for k in range(1, 6):
        trial(raw, "gc4_none_ow", k, kill=None, subject=None, inject="none", spare=False, killed=False, probe=probe_ok(),
              lines={r: [(1.0, "GIN/RS: rank %d: input pause for rank 0's checkpoint 20 ended (ok) pause_us=8100" % r)] for r in range(N)})
    # B2: the freeze cell (FREEZE_PAGE on rank 3, SUBJECT_RANK 3, no KILL_RANK); the launcher's FENCE SIGKILL and FENCED
    for k in range(1, 6):
        L = restore_lines(3, 12.1, "STALL")
        for r in (0, 1, 2):
            L[r] = [x if "judged dead" not in x[1] else
                    (x[0], "GIN/RC: rank %d: rank 3 (incarnation 0) judged stalled (liveness stall judged (STALL)); STALLED to 2 rank(s)" % r)
                    for x in L[r]]
            L[r].append((12.3, "GIN/RC: rank %d: window check after the fence of rank 3: changed=0 cells" % r))
        L[3] += [(2.0, "GIN/RC: rank 3: test switch FREEZE_PAGE=12000: watchBeat+helperBeat frozen")]
        trial(raw, "gc4_freeze12000_fence", k, kill=None, subject=3, dead=[3], inject="none", lines=L, probe=probe_ok(),
              meta_extra={"r3_env": "NCCL_GIN_TS_TEST_FREEZE_PAGE=12000"},
              la={"sunny": [(12.102, "FENCE of rank 3 incarnation 0 from rank 2: SIGKILL sent through its pidfd (pid 999)"),
                            (12.104, "rank 3 incarnation 0 FENCED: the group ended 1.500 ms after SIGKILL through its pidfd")]})
    # B2: the live RST and port gap on rank 1 in the tcp control build (SUBJECT_RANK 1; fail-fast, no restore)
    for cell, n, judged in (("gct4_rstgap_live50", 10, False), ("gct4_rstgap_live300", 5, True)):
        for k in range(1, n + 1):
            L = {1: [(3.0, "GIN/TS: rank 1: test switch RST_GAP: 3 socket(s) reset, listener closed for %s ms" % cell[-2:])]}
            for r in (0, 2, 3):
                L[r] = [(3.0005, "GIN/TS: rank %d: socket to rank 1 closed cause=ECONNRESET" % r)]
                if judged:
                    L[r].append((3.1035, "host NCCL WARN GIN/TS: rank %d: rank 1 judged dead (cause=ECONNRESET)" % r))
            trial(raw, cell, k, build="gctc", kill=None, subject=1, inject="none", spare=False, killed=False, lines=L,
                  probe=probe_ok(), page=False,
                  meta_extra={"r1_env": "NCCL_GIN_TS_TEST_RST_GAP=3000:%s" % cell[-2:], "policy": "failfast", "restore": 0})
    # B3: gin-mirror's second-death cell at @gc: rank 2 killed and restored, rank 3 killed before the survivors re-armed
    L = restore_lines(2, 1.0, "FIN+NORESP", survivors=(0, 1, 3))
    ko = [ln("rain", 0.95, "GINRS killed rank=2 node=rain pid=998 which=first"),
          ln("sunny", 2.0, "GINRS killed rank=3 node=sunny pid=999 which=first")]
    trial(raw, "mi4_kill2_kill3_ow", 1, kill=2, subject=2, dead=[2, 3], lines=L, probe=probe_ok(), spare_rank=2, kout=ko,
          meta_extra={"kill2_rank": 3, "die_at": "200:10", "die2_at": "400:10", "spare2": 1, "spare2_wanted": 1,
                      "spare2_ready": 1, "hold": "RG-gc-G1"})
    # H: the CPU programs: the simulated gate_fenced.cc lines and real-process lines without a gate program
    os.makedirs(os.path.join(R, "local"), exist_ok=True)
    with open(os.path.join(R, "local", "gate_fenced.log"), "w") as f:
        for t in range(10):
            sec = 500 + (t % 7) - 3
            f.write("gate_fenced trial %d: old GO at 0 ms, FENCED GO at %d ms (diff %d ms, second thread %d ms)\n" % (t, sec, sec, sec))


def shell_checks(R):
    """B1 and B4's shell pieces, run locally (no ssh): the remote MTU query, the hold's tail check, the launcher table"""
    fake = os.path.join(R, "fakebin")
    os.makedirs(fake, exist_ok=True)
    with open(os.path.join(fake, "ibv_devinfo"), "w") as f:
        f.write('#!/bin/sh\necho "hca_id:\t$2"\necho "\t\tactive_mtu:\t\t4096 (5)"\necho "\t\tmax_mtu:\t\t4096 (5)"\n')
    os.chmod(os.path.join(fake, "ibv_devinfo"), 0o755)
    cmd = subprocess.run(["bash", "-c", '. "$1"; rcmd "$MTU_Q" mlx5_0', "_", os.path.join(HERE, "remote_gc.sh")],
                         stdout=subprocess.PIPE, check=True).stdout.decode()
    mtu_q = subprocess.run(["bash", "-c", '. "$1"; printf %s "$MTU_Q"', "_", os.path.join(HERE, "remote_gc.sh")],
                           stdout=subprocess.PIPE, check=True).stdout.decode()
    w = shlex.split(cmd)
    check(w == ["bash", "-c", mtu_q, "_", "mlx5_0"], "B1: the remote MTU command splits into bash -c <query> _ mlx5_0 (%r)" % w[:3])
    env = dict(os.environ, PATH=fake + os.pathsep + os.environ.get("PATH", ""))
    got = subprocess.run(["sh", "-c", cmd], stdout=subprocess.PIPE, env=env).stdout.decode().strip()
    check(got == "4096", "B1: the remote shell's reading of active_mtu is 4096 (%r)" % got)
    old_q = "ibv_devinfo -d $1 -i 1 2>/dev/null | awk '/active_mtu/{print $2; exit}'"
    old = shlex.split("bash -c '%s' _ mlx5_0" % old_q)
    check(len(old) != 5, "B1: the old quoting split the query into %d words (the review's finding)" % len(old))
    # B4: the hold's tail check after the last trial_end marker counts both STOP forms
    lg = os.path.join(R, "la_tail.log")
    with open(lg, "w") as f:
        f.write("1.0 GIN/LA: node 1: listening on its Unix socket (Q_Key 0x1)\n2.0 GINLA mark trial_end x_n1\n"
                "3.0 GIN/LA: node 1: REGISTER of rank 3 incarnation 2 refused: the pidfd is not the peer's process "
                "(STOP_launcher: a pidfd that is not the peer's own)\n"
                "3.1 GIN/LA: node 1: FENCE of rank 3 incarnation 1 from rank 2: refused to signal: no pidfd held for it (STOP_launcher)\n")
    n = subprocess.run(["bash", "-c", "tac \"$1\" | sed '/GINLA mark trial_end /q' | grep -c '(STOP_launcher'", "_", lg],
                       stdout=subprocess.PIPE).stdout.decode().strip()
    check(n == "2", "B4: the hold's tail check counts both STOP_launcher forms after the last trial (%r)" % n)
    # the launcher table read (launcher_gc.sh table: no ssh, no process)
    ld = os.path.join(R, "la")
    os.makedirs(ld, exist_ok=True)
    with open(os.path.join(ld, "la_h1_sunny.log"), "w") as f:
        f.write("1.1 GIN/LA: node 1: rank 3 incarnation 0 registered (pid 10)\n"
                "1.3 GIN/LA: node 1: spare of rank 3 incarnation 1 said HELLO (pid 12): replaying\n"
                "2.0 GIN/LA: node 1: rank 3 incarnation 0 EXITED (its pidfd is readable: the thread group ended)\n")
    lenv = dict(os.environ, RS_SET="selftest", SUNNY_SSH="nobody@invalid")
    t1 = subprocess.run(["bash", os.path.join(HERE, "launcher_gc.sh"), "table", "sunny", ld, "h1"], stdout=subprocess.PIPE,
                        env=lenv).stdout.decode().strip()
    with open(os.path.join(ld, "la_h1_sunny.log"), "a") as f:
        f.write("2.2 GIN/LA: node 1: rank 3 incarnation 1 re-registered (the revived process, pid 12): its pidfd swapped\n"
                "3.0 GIN/LA: node 1: rank 3 incarnation 1 left (LEAVING, then the group ended)\n")
    t2 = subprocess.run(["bash", os.path.join(HERE, "launcher_gc.sh"), "table", "sunny", ld, "h1"], stdout=subprocess.PIPE,
                        env=lenv).stdout.decode().strip()
    check(t1 == "table open=1 spare3.1" and t2 == "table open=0", "B4: the launcher table read (%r, %r)" % (t1, t2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", default=None)
    a = ap.parse_args()
    R = a.keep or tempfile.mkdtemp(prefix="gc_selftest_")
    if a.keep:
        shutil.rmtree(R, ignore_errors=True)
        os.makedirs(R)
    build(R)
    # H: real-process gate lines (gate_proc_gc.py, 10 trials of the CPU harness; no gate program: the gate columns stay empty)
    gp = subprocess.run([sys.executable, os.path.join(HERE, "gate_proc_gc.py"), "--trials", "10",
                         "--out", os.path.join(R, "local", "gate_proc.log")], stdout=subprocess.PIPE, timeout=120)
    rows = {r["id"]: r for r in rows_gc.all_rows(R) if r["sub"] in ("raw", "local")}
    A = rows["gc4_kill3_ow_gc_n1"]
    check(A["n_judge"] == 3 and A["n_judge_confirm"] == 3 and A["weak_cause_n"] == 0, "A: three confirm-window judgements %r" % A["judge_causes"])
    check(A["fin_judge_dev_min_ms"] == 0.4 and A["fin_judge_dev_max_ms"] == 0.4, "A: FIN -> judgement - W = 0.4 ms (%r, %r)" % (A["fin_judge_dev_min_ms"], A["fin_judge_dev_max_ms"]))
    check(A["confirm_w_ms"] == 30 and A["probe_ms_page"] == 100, "A: W 30 and the READ period 100 from the status page line")
    check(abs(A["kill_judge_ms_min"] - 30.6) < 0.01 and abs(A["kill_judge_ms_max"] - 30.6) < 0.01 and A["kill_judge_clock"] == "mono+mono_xnode",
          "fix 2: kill -> judgement 30.6 ms on both nodes, no ssh delay (%r %r %r)" % (A["kill_judge_ms_min"], A["kill_judge_ms_max"], A["kill_judge_clock"]))
    check(A["judge_spread_ms"] == 0.0 and A["judge_spread_clock"] == "mono", "nit 19: the judgement spread in one clock (%r)" % A["judge_spread_ms"])
    check(A["mono_off_used_ms"] == 400000.0 and A["mono_off_drift_ms"] == 0.05, "fix 2: the offset with the smaller round trip, its drift")
    W0 = rows["gc4_kill3_ow_gc_n15"]
    check(abs(W0["kill_judge_ms_min"] - 26.6) < 0.01 and "receipt" in W0["kill_judge_clock"],
          "fix 2: without the offset the cross-node interval is the receipt clock, 4 ms short (%r)" % W0["kill_judge_ms_min"])
    check(A["wait_held"] == 1 and A["ow_data_equal"] == 1 and A["revived_done"] == 1, "A: the restore succeeded")
    check(A["tcp_ctrl_bytes"] == 0 and A["tcp_ctrl_conn_n"] == A["witness_pairs"] == A["witness_expected"] == 12 and A["active_mtu_kv_min"] == 4096,
          "fix 10: no tcp control bytes, conns = the configuration's witness count (%r %r)" % (A["tcp_ctrl_conn_n"], A["witness_expected"]))
    check(A["ss_tcp_conn_n"] == 20 and A["ss_pids_both"] == 4 and A["ss_tx_delta_bytes"] == 0, "fix 10: the ss snapshots read")
    check(A["fenced"] == 1 and A["fence_order_ok"] == 1 and A["fence_names_ok"] == 0, "A: FENCED (by EXITED) before the activation, no FENCE sent")
    check(A["la_exited_n"] == 1 and A["la_stop_n"] == 0 and A["launcher_same"] == 1, "fix 6: the earlier trial's EXITED before trial_start not counted (%r)" % A["la_exited_n"])
    check(A["hold_after_restore_n"] == 0, "fix 9: no hold after the restore")
    B = rows["gc4_fdhold_sock_kill3_gc_n1"]
    check(B["n_judge_exited"] == 3 and abs(B["kill_judge_exited_min_ms"] - 120.0) < 0.01 and abs(B["kill_judge_ms_max"] - 120.0) < 0.01, "B: EXITED 120 ms after the kill")
    check(B["inject_ok"] == 1 and abs(B["inject_off_ms"] - 4.0) < 0.01, "B: the fd-holder injection record (receipt 4 ms after the plan)")
    C = rows["gc4_fdhold_sock_kill3_noreport_gc_n1"]
    check(C["n_judge_noresp"] == 3 and abs(C["kill_judge_ms_min"] - 3900.0) < 0.01, "C: NORESP 3.9 s after the kill (%r)" % C["kill_judge_ms_min"])
    check(C["fence_names_ok"] == 1 and C["fence_order_ok"] == 1 and abs(C["fence_sent_to_fenced_ms"] - 2.0) < 0.01, "C: FENCING -> FENCED -> activation")
    check(C["timeout_judge_n"] == 0 and C["probe_timeout_n"] == 3 and C["la_exit_silent_n"] == 1 and C["la_fenced_n"] == 1
          and C["witness_pairs"] == 0 and C["witness_expected"] == 0, "C: time-out lines before the judgement, the silent exit, witness off")
    D = rows["gc4_stop12000_fence_gc_n1"]
    check(D["la_stop_n"] == 1 and D["la_refused_signal_n"] == 1, "D: the STOP_launcher line counted")
    check(D["n_judge_stall"] == 3 and abs(D["stop_judge_ms_min"] - 10050.0) < 0.01 and abs(D["hold_ms_max"] - 1400.0) < 0.01, "D: stall judgement 10 050 ms after STOP, hold 1.4 s (%r %r)" % (D["stop_judge_ms_min"], D["hold_ms_max"]))
    check(D["cont_target_present"] == 1 and D["fence_sent"] == 1 and D["fenced"] == 0 and D["ckpt_stable_before_inj"] == 1, "D: CONT found the PID; FENCE sent, no FENCED; armed before the STOP")
    check(rows["gc4_kill3_ow_gc_n13"]["kill2_after_armed"] == 1 and rows["gc4_kill3_ow_gc_n14"]["kill2_after_armed"] == 0, "F: the second kill after / before the armed lines (reported)")
    import csv as _csv
    kj = [p for p in _csv.DictReader(open(score_gc.PREDS, encoding="utf-8")) if p["id"] == "kill_judge_rdma"][0]["acceptance"]
    kj = kj.split(";;")[0].split(":", 1)[1].strip()
    kj = kj[len("count("):kj.rindex(")")]
    check(W0["weak_cause_n"] == 3 and not score_gc.s2.cond_true(kj, W0) and score_gc.s2.cond_true(kj, A),
          "negative: a FIN-only judgement fails kill_judge_rdma's per-trial rule, the confirm-window one passes")
    G = rows["gc4_none_probe_gc_n1"]
    check(G["page_torn_n"] == 5 and G["read_success_pct"] == 100.0 and G["beat_gap_max_ms"] == 4.0 and G["suspect_n"] == 0, "G: torn reads counted, READ 100 %")
    check(G["judge_any_n"] == 0 and G["ckpt_pause_ms"] == 2.3, "G: no judgement, pause 2.3 ms")
    # B2: the switch-injected cells have a subject and their columns
    F = rows["gc4_freeze12000_fence_gc_n1"]
    check(F["subject"] == "3" and F["n_judge"] == 3 and F["n_judge_stall"] == 3 and abs(F["stop_judge_ms_min"] - 10100.0) < 0.01
          and F["la_fence_sigkill_n"] == 1 and F["la_fenced_n"] == 1 and F["inject_ok"] == 1 and F["ckpt_stable_before_inj"] == 1
          and F["subject_fenced"] == 1 and F["ow_data_equal"] == 1,
          "B2: the freeze cell judged on its subject (%r %r %r)" % (F["subject"], F["n_judge"], F["stop_judge_ms_min"]))
    G3 = rows["gct4_rstgap_live300_gctc_n1"]
    check(G3["subject"] == "1" and G3["n_judge"] == 3 and G3["n_rst_surv"] == 3 and abs(G3["rst_judge_ms_min"] - 103.0) < 0.01,
          "B2: the live RST cell judged on rank 1, RST -> judgement 103 ms (%r %r)" % (G3["n_judge"], G3["rst_judge_ms_min"]))
    # B4: rows_gc.py --stops (the hold's per-trial check) on both forms and on the QP loss
    def stops(stem):
        return subprocess.run([sys.executable, os.path.join(HERE, "rows_gc.py"), "--stops", os.path.join(R, "raw", stem)],
                              stdout=subprocess.PIPE).stdout.decode().strip()
    s16, sD, s17, sA = stops("gc4_kill3_ow_gc_n16"), stops("gc4_stop12000_fence_gc_n1"), stops("gc4_kill3_ow_gc_n17"), stops("gc4_kill3_ow_gc_n1")
    check("la_stop_n=1 " in s16 + " " and "la_pid_mismatch_n=1" in s16, "B4: '(STOP_launcher: ...)' in the gap before trial_start counted (%s)" % s16)
    check("la_stop_n=1 " in sD + " ", "B4: '(STOP_launcher)' counted (%s)" % sD)
    check("la_qp_err_n=1" in s17 and "la_stop_n=0" in s17, "B4: the launcher QP loss of rank 1 before 'is leaving' counted (%s)" % s17)
    check("la_stop_n=0 la_qp_err_n=0" in sA, "B4: a clean trial (%s)" % sA)
    # H: the gate rows
    gate = [r for r in rows.values() if r["key"] == "local:gate_fenced"]
    sim = [r for r in gate if r["gate_real"] == 0]
    real = [r for r in gate if r["gate_real"] == 1]
    check(len(sim) == 10 and gp.returncode == 0 and len(real) == 10, "H: ten simulated and ten real-process gate rows (%d, %d)" % (len(sim), len(real)))
    check(all(r["second_thread_ms"] >= 499 and abs(r["pidfd_ms"] - r["second_thread_ms"]) < 50 and r["z_ms"] < 50 for r in real),
          "fix 1: the harness's own readings: Z soon after the main thread, the pidfd readable at the second thread's end")
    check(all(r["fenced_go_ms"] == "" for r in real), "fix 1: without the gate program the gate columns stay empty")
    # the scorer
    PO = {"gc4_stop12000_fence@gc": 1, "mi4_kill2_kill3_ow@gc": 1}
    verd, srows = score_gc.score(R, planned_override=PO)
    st = {r["id"]: r["status"] for r in srows if r["sub"] == "raw"}
    check(st["gc4_kill3_ow_gc_n11"] == "launcher_not_ready", "E: launcher not ready excluded (%s)" % st["gc4_kill3_ow_gc_n11"])
    check(st["gc4_kill3_ow_gc_n12"] == "kill_before_ckpt", "E: the kill before a stable checkpoint excluded (%s)" % st["gc4_kill3_ow_gc_n12"])
    check(st["gc4_kill3_ow_gc_n17"] == "launcher_changed", "B4: the QP loss outside the test-switch cells excluded (%s)" % st["gc4_kill3_ow_gc_n17"])
    smoke = [r for r in srows if r["sub"].startswith("smoke")]
    check(len(smoke) == 1 and smoke[0]["status"] == "smoke", "E: the smoke trial apart")
    check(st["gc4_kill3_ow_gc_n14"] == "surplus" and st["gc4_kill3_ow_gc_n13"] == "surplus",
          "B3: the second kill before the armed lines is not excluded (%s, %s)" % (st["gc4_kill3_ow_gc_n14"], st["gc4_kill3_ow_gc_n13"]))
    M = [r for r in srows if r["id"] == "mi4_kill2_kill3_ow_gc_n1"][0]
    reim = [p for p in _csv.DictReader(open(score_gc.MPREDS, encoding="utf-8")) if p["id"] == "reimage_after_restore"][0]["acceptance"]
    reim = reim[len("count("):reim.rindex(")")]
    check(M["status"] == "scored" and str(M.get("rearm_ok")) == "0" and not score_gc.s2.cond_true(reim, M),
          "B3: the second death before the re-arm is scored, its re-image condition false (%s, rearm_ok %r)" % (M["status"], M.get("rearm_ok")))
    for pid, want in (("kill_judge_rdma", "자료 부족"), ("finless_exit_report", "맞음"), ("finless_read_fail", "맞음"),
                      ("none_probe_clean", "맞음"), ("gate_fenced", "자료 부족"), ("no_tcp_control", "맞음"),
                      ("long_hold_lane", "맞음"), ("stall_fence_restore", "자료 부족"), ("restore_time_rdma", "자료 부족"),
                      ("regression_tcp", "자료 부족"), ("cost_probe_lat4k", "자료 부족"), ("freeze_fence_restore", "맞음")):
        check(verd.get(pid) == want, "verdict %s: %s (want %s)" % (pid, verd.get(pid), want))
    # the 2026-10-22 trim: regression.builds.gct.cells limits the tcp regression plan; @gc keeps every hold's cells
    reg = score_gc.regression_entries(score_gc.load_cells(), score_gc.mirror_cells())
    rg_gct = sorted(k for k in reg if k.endswith("@gct"))
    check(rg_gct == ["mi4_kill3_ow@gct"] and len([k for k in reg if k.endswith("@gc")]) > 1,
          "trim: the tcp regression plans only mi4_kill3_ow@gct (%s)" % rg_gct)
    # fix 11: a key below its plan is short, never "틀림": nine good trials of gc4_kill3_ow@gc (one dropped)
    verd2, _ = score_gc.score(R, planned_override=dict(PO, **{"gc4_fdhold_sock_kill3@gc": 11}))
    check(verd2.get("finless_exit_report") == "자료 부족", "fix 11: 10 of 11 planned is short (%s)" % verd2.get("finless_exit_report"))
    md = open(os.path.join(R, "SCORE.md"), encoding="utf-8").read()
    check("`STOP_launcher`(1줄)" in md and "FENCE_NAK 포함): 2줄" in md, "SCORE.md lists the STOP file and both STOP_launcher lines")
    check("smoke: 1" in md, "SCORE.md counts the smoke trial apart")
    check(os.path.exists(os.path.join(R, "trials_scored.csv")), "trials_scored.csv written")
    shell_checks(R)
    print("self-test: %d checks, %d failed%s" % (CHECKS[0], CHECKS[1], "" if a.keep else " (folder %s removed)" % R))
    if not a.keep:
        shutil.rmtree(R, ignore_errors=True)
    sys.exit(1 if CHECKS[1] else 0)


if __name__ == "__main__":
    main()
