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
  C  gc4_kill3_noreport_nofdhold@gc x 5   a READ-failure judgement (NORESP kill + 3.9 s, its READ failure line just before),
                                     FENCING -> FENCED -> activation (finless_read_fail; 2026-10-23, smoke 5's cell without the fd holder)
  C2 gc4_fdhold_sock_kill3_noreport@gc x 5   the inherited-mapping death: judged STALL_HELPER kill + 10.07 s with no READ
                                     failure line before it (one after), FENCING -> FENCED -> activation (fdhold_sock_helper_stall)
  D  gc4_stop12000_fence@gc x 1      a "(STOP_launcher)" line (FENCE_NAK); a hold over 1 s; judged STALL_HELPER (smoke3's form)
  E  gc4_kill3_ow@gc n11 (launchers not ready), n12 (no stable checkpoint before the kill), smoke/ (a smoke trial)
  F  gc4_kill3_ow@gc n13, n14        the second kill of rank 3 by recorded PID after / before the armed lines (reported only)
  G  gc4_none_probe@gc x 10 with torn reads, gc4_none_ow@gc x 5
  H  local/gate_fenced.log (the simulated program: gate_real 0) and local/gate_proc.log (real-process lines, no gate program)
  B1 the active_mtu query handed to the remote shell: one word list (shlex) and 4096 read through a fake ibv_devinfo
  B2 gc4_freeze12000_fence@gc x 5 (judged STALL_HELPER) and gct4_rstgap_live50@gctc x 10, gct4_rstgap_live300@gctc x 5: cells injected by a library
     test switch, with SUBJECT_RANK, judged
  B3 mi4_kill2_kill3_ow@gc: the second kill before the re-arm: counted (scored), its re-image condition false
  B5 gc4_gpuhang12000_fence@gc x 5: the test driver's GPU hang (GC_GPUHANG_IT in R3_ENV, its GINRS gpuhang line), judged
     STALL (table row 14) 10.1 s after the hang line, FENCE -> FENCED by the launcher; the rule takes STALL, a STALL_HELPER
     copy fails (2026-10-23)
  B6 gc4_gpuhang12000_ctx1_fence@gc x 5: the same hang with the context filter (GC_GPUHANG_CTX=1, its hang line ctx=1),
     judged STALL with ctx=1 on the STALLED line (n1, n3-n5) or only on the suspect line before it (n2): stall_ctx 1; the
     rule gpuhang_ctx1_fence_restore takes it, "1+none", "0+1", empty and 0 fail; a ctx=all hang line in that cell is no
     injection record (2026-10-24, decision (가))
  B4 "(STOP_launcher: ...)" in the gap before trial_start (n16) and a launcher QP loss (n17): rows_gc.py --stops, the hold's
     tail check on a whole launcher log, and the launcher table read
  J  section 3's 2026-10-22 revision on copies of the rows above: the stall rules count STALL_HELPER (a STALL copy fails),
     the uverbs rule takes EXITED or either stall cause, the launcher-report band 100-150 ms (101 and 149 in, 99 and 151
     out) in kill_judge_rdma, finless_exit_report and kill_no_witness, the confirm window W to W + 2 ms; and
     check_cells_gc.py's drift check on the revised rows (none) and on the old ones (each caught)
  I  the launcher daemon's warm spare (2026-10-22, one launcher per trial): gc4_kill3_ow@gc n18 (rank 3 killed twice, the
     second restore by the daemon's next spare, incarnation 2), n19 (the same without that spare: spare_start_fail), n20 (a
     stale launcher socket at the trial's start: nothing ran, launcher_stale and --stops la_stale_n); gc4_kill3_ow_spareabsent
     n1 (the one expected respawn-cap line is not a STOP; the same line in a normal cell is); launcher_gc.sh stale on a
     scratch root with a left socket
"""
import argparse, os, re, shlex, shutil, subprocess, sys, tempfile

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
          page=True, probe=None, killed=True, offset=True, ss=True, live_ranks=None, rec_bytes=0, ctrl_kv="",
          spare_live=None, mtu="4096", kv_extra=None, spare_kv=None):
    """one synthetic run_gc.sh trial; lines: {rank or 'spare': [(t, text)]} in node seconds; dead: the ranks that died.
    rdma builds: every rank in live_ranks (default all) logs the ring's live line at 0.6 s; the spare logs its restore and
    its live line when a survivor's line names its rejoin (spare_live None) or when spare_live is True; rec_bytes and
    ctrl_kv go into the survivors' control summaries; mtu is the summaries' active_mtu= (the library prints the ibv_mtu
    enum, 5); kv_extra {rank: {k: v}} changes a rank's kv (a value None drops the key); spare_kv replaces the spare's kv"""
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
                launcher_ready=1 if rdma else "", launcher_scope="trial" if rdma else "none",
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
        kv.update((kv_extra or {}).get(r, {}))
        kv = {k: v for k, v in kv.items() if v is not None}
        with open("%s_r%d.kv" % (stem, r), "w") as f:
            f.write(kvline(kv))
        nd = node(r)
        L = [raw_line(0.0, "GINRS start rank=%d mode=live" % r)]
        if page:
            L.append(ln(nd, 0.5, "host NCCL WARN GIN/RC: rank %d: status page up (448 B in use, probe_ms=100 stall_ms=10000 W=30)" % r))
        if rdma and (live_ranks is None or r in live_ranks):
            L.append(ln(nd, 0.6, LIVE % r))
        L += [ln(nd, t, x) for t, x in lines.get(r, [])]
        if not is_dead:
            if probe is not None:  # one summary per peer (the library's teardown line; Codex finding 1)
                pl = probe(r)
                L += [ln(nd, 9.0, x) for x in ([pl] if isinstance(pl, str) else pl)]
            if ctrlsum:
                w = 3 if witness == "1" else 0
                L.append(ln(nd, 9.1, "GIN/RC: rank %d: control summary tcp_record_bytes=%d tcp_data_bytes=0 tcp_conns=%d "
                                     "witness_conns=%d records_lost=0 records_dup=0 repairs=0 sendq_deferred=0 sendq_max=0 "
                                     "rnr=0 async=0 active_mtu=%s%s" % (r, rec_bytes, w, w, mtu, ctrl_kv)))
                nsum += 1
        else:
            L.append(raw_line(1.9, "GINRS step rank=%d step=100 released=0" % r))
        write("%s_r%d.log" % (stem, r), L)
    if spare:
        sn = node(spare_rank)
        with open(stem + "_spare.kv", "w") as f:
            f.write(kvline(spare_kv if spare_kv is not None else
                           dict(GOOD, rank=spare_rank, mode="spare", resume_step=100, revived=1, start_step=101)))
        S = [raw_line(0.0, "GINRS start rank=%d mode=spare" % spare_rank),
             raw_line(1.0, "GINRS spare_ready rank=%d rt_s=1.0" % spare_rank)]
        S += [ln(sn, t, x) for t, x in lines.get("spare", [])]
        rj = [t for k, v in lines.items() if k != "spare" for t, x in v if "spare rejoined as incarnation" in x]
        if rdma and (spare_live or (spare_live is None and rj)):
            t0 = min(rj) if rj else 2.5
            S += [ln(sn, t0 + 0.004, "GIN/RS: spare rank %d: restored as incarnation 1 from step 100" % spare_rank),
                  ln(sn, t0 + 0.005, LIVE % spare_rank)]
        if probe is not None:  # the spare's own summaries (required when it became active)
            pl = probe(spare_rank)
            S += [ln(sn, 9.15, x) for x in ([pl] if isinstance(pl, str) else pl)]
        if ctrlsum:
            w = 3 if witness == "1" else 0
            S.append(ln(sn, 9.2, "GIN/RC: rank %d: control summary tcp_record_bytes=0 tcp_data_bytes=0 tcp_conns=%d "
                                 "witness_conns=%d records_lost=0 records_dup=0 repairs=0 sendq_deferred=0 sendq_max=0 rnr=0 "
                                 "async=0 active_mtu=%s" % (spare_rank, w, w, mtu)))
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


def gpu_ctx1_trial(d, k, *, on_stall=True, ctxs=(1, 1, 1), hang_ctx="1"):
    """one gc4_gpuhang12000_ctx1_fence@gc trial (B6): the hang line names ctx=hang_ctx; survivor r's STALL judgement names
    ctxs[r] (None: no ctx= at all) on its STALLED line (on_stall) or only on a gpu suspect line 2 s before it"""
    fz = [(12.101, "GIN/RC: rank 2: rank 3 (incarnation 0) fence FENCING: FENCE sent to the launcher of node 1"),
          (12.130, "GIN/RC: rank 2: rank 3 (incarnation 0) fence FENCED (by FENCED from node 1)")]
    L = restore_lines(3, 12.1, "STALL", buddy_fence=fz, t_pub=12.45)
    for r in (0, 1, 2):
        c = ctxs[r]
        tok = (" ctx=%d" % c) if (c is not None and on_stall) else ""
        L[r] = [x if "judged dead" not in x[1] else
                (x[0], "GIN/RC: rank %d: rank 3 (incarnation 0) judged stalled (liveness stall judged (STALL)%s); STALLED to 3 rank(s)" % (r, tok))
                for x in L[r]]
        if c is not None and not on_stall:
            L[r].append((10.1, "GIN/RC: rank %d: rank 3 suspected (kind=gpu ctx=%d stale_ms=2000.4)" % (r, c)))
        L[r].append((12.5, "GIN/RC: rank %d: window check after the fence of rank 3: changed=0 cells against=snapshot_at_judgement unreadable=0" % r))
    L[3] += [(2.0, "GINRS gpuhang rank=3 step=155 spin=1 ctx=%s wait_ms=0.120" % hang_ctx)]
    return trial(d, "gc4_gpuhang12000_ctx1_fence", k, kill=None, subject=3, dead=[3], inject="none", lines=L, probe=probe_ok(),
                 meta_extra={"r3_env": "GC_GPUHANG_IT=155+GC_GPUHANG_CTX=1"},
                 la={"sunny": [(12.102, "FENCE of rank 3 incarnation 0 from rank 2: SIGKILL sent through its pidfd (pid 999)"),
                               (12.128, "rank 3 incarnation 0 FENCED: the group ended 26.000 ms after SIGKILL through its pidfd")]})


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
                 (t_pub - 0.020, "GIN/RS: rank %d: rank %d's spare rejoined as incarnation 1 (20.0 ms after the hold start)" % (r, subject)),
                 (t_pub - 0.015, "GIN/TS: rank %d: socket to rank %d reconnected gen=2 attempts=1" % (r, subject))]
    b = subject ^ 1
    fz = buddy_fence or [(t_judge + 0.002, "GIN/RC: rank %d: rank %d (incarnation 0) fence FENCED (by EXITED from node 1)" % (b, subject))]
    L[b] += fz + [(t_judge + 0.040, "GIN/RS: rank %d: every survivor holds rank %d: its spare activated (incarnation 1, 39.0 ms "
                                    "after this rank's hold start), 0 'later' answers over 0.0 ms" % (b, subject))]
    for k, v in (extra or {}).items():
        L[k] += v
    return L


def probe_ok(torn=0, dev=False, dev_fail=None, drop=None, no_dev_ok=False):
    """the probe summaries of rank r, one per peer (the library's teardown lines): 300 page READs, all ok; torn on rank 0's
    first line only; dev: the device line's counters too (dev_line=1, 299 READs in one context, smoke 5's form with ctxall's
    dev_ctx= tokens); dev_fail (r, peer): that line's dev_ok one short; drop (r, peer): that line left out; no_dev_ok: every
    line without dev_ok="""
    def lines(r):
        out = []
        for i, p in enumerate(q for q in range(N) if q != r):
            if drop == (r, p):
                continue
            x = ("GIN/RC: rank %d: probe summary peer=%d reads=300 ok=300 remacc=0 noresp=0 timeout=0 gen=0 lat_med_us=6.1 "
                 "lat_max_us=40.0 beat_gap_max_ms=4.0 torn=%d after_end_reads=0 after_end_ok=0" % (r, p, torn if (r == 0 and i == 0) else 0))
            if dev:
                ok = 298 if dev_fail == (r, p) else 299
                x += " dev_line=1 dev_reads=299%s dev_quiet=%d dev_ag_diff=0 dev_bad=0 pair_max=2 dev_ctx=1 dev_reads_ctx=299 dev_ok_ctx=%d" % (
                    "" if no_dev_ok else " dev_ok=%d" % ok, ok, ok)
            out.append(x)
        return out
    return lines


EXITED3 = "rank 3 incarnation 0 EXITED (its pidfd is readable: the thread group ended)"
LIVE = ("GIN/RC: rank %d: the records go on the ring from now (live): 3 peer(s), record and liveness READ QPs paired; the "
        "helper sockets are the witness's")
# the launcher's warm-spare lines (../launcher/README_launcher.md, exact; the prefix "GIN/LA: node N: " is added by trial())
SPAWN = "spare spawned (spawn %d, incarnation %d, pid %d, why %s, log /tmp/gc_rt_1_2.spare/spare_n%d_s%d_i%d_p77.log)"
HELLO = "spawned spare said HELLO (spawn %d, incarnation %d, pid %d, hello pid %d, rank %d incarnation %d, after 310.5 ms)"
CAP0 = ("spawned spare exited unused (spawn %d, incarnation %d, pid %d, after HELLO, signal 9): respawn cap 0 within 60000 ms "
        "reached; no more spares (STOP_launcher)")


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
    # C: the READ-failure judgement (NORESP kill + 3.9 s), FENCING -> FENCED -> activation, witness off, no fd holder
    noreport = {"launcher_env_rain": "NCCL_GIN_CTRL_TEST_NO_EXIT_REPORT=1", "launcher_env_sunny": "NCCL_GIN_CTRL_TEST_NO_EXIT_REPORT=1"}
    for k in range(1, 6):
        fz = [(5.901, "GIN/RC: rank 2: rank 3 (incarnation 0) fence FENCING: FENCE sent to the launcher of node 1"),
              (5.903, "GIN/RC: rank 2: rank 3 (incarnation 0) fence FENCED (by FENCED from node 1)")]
        ex = {r: [(2.5, "GIN/RC: rank %d: probe of rank 3 timed out (no CQE in 500 ms)" % r),
                  (5.8995, "GIN/RC: rank %d: liveness READ of rank 3: retry exceeded (no response) (status 12)" % r)]
              for r in (0, 1, 2)}
        L = restore_lines(3, 5.900, "NORESP", buddy_fence=fz, extra=ex)
        trial(raw, "gc4_kill3_noreport_nofdhold", k, witness="0", lines=L, probe=probe_ok(), meta_extra=dict(noreport),
              la={"sunny": [(2.12, "rank 3 incarnation 0 exited; EXITED not sent (test switch NO_EXIT_REPORT)"),
                            (5.902, "FENCE of rank 3 incarnation 0 from rank 2: already ended; FENCED"),
                            (5.902, "rank 3 incarnation 0 FENCED: it had ended before the FENCE (already exited)")]})
    # C2: the fd holder's inherited mappings keep rank 3's QPs and MRs: the READs answer, the host beats stop; judged
    # STALL_HELPER (row 15) kill + 10.07 s, one READ failure line only after the judgement (not counted)
    for k in range(1, 6):
        fz = [(12.071, "GIN/RC: rank 2: rank 3 (incarnation 0) fence FENCING: FENCE sent to the launcher of node 1"),
              (12.073, "GIN/RC: rank 2: rank 3 (incarnation 0) fence FENCED (by FENCED from node 1)")]
        L = restore_lines(3, 12.070, "STALL_HELPER", buddy_fence=fz)
        for r in (0, 1, 2):
            L[r] = [x if "judged dead" not in x[1] else
                    (x[0], "GIN/RC: rank %d: rank 3 (incarnation 0) judged stalled (liveness stall judged (STALL_HELPER)); STALLED to 3 rank(s)" % r)
                    for x in L[r]]
            L[r] += [(4.07, "GIN/RC: rank %d: rank 3 suspected (kind=watch stale_ms=2000.4)" % r),
                     (12.5, "GIN/RC: rank %d: liveness READ of rank 3: retry exceeded (no response) (status 12)" % r)]
        L[3] += [(0.6, "GIN/TS: rank 3: test switch FD_HOLDER=sock: child gin_fdhold pid=4243 holds 0 fd(s)")]
        trial(raw, "gc4_fdhold_sock_kill3_noreport", k, witness="0", inject="fd_holder_kill", lines=L, probe=probe_ok(),
              meta_extra=dict(noreport, fdhold=1),
              la={"sunny": [(2.12, "rank 3 incarnation 0 exited; EXITED not sent (test switch NO_EXIT_REPORT)"),
                            (12.072, "FENCE of rank 3 incarnation 0 from rank 2: already ended; FENCED"),
                            (12.072, "rank 3 incarnation 0 FENCED: it had ended before the FENCE (already exited)")]})
    # D: a STOP_launcher line (FENCE_NAK) in a stall cell; a hold of 1.4 s; the runner's stop/cont lines
    L = {r: [(12.05, "GIN/RC: rank %d: rank 3 (incarnation 0) judged stalled (liveness stall judged (STALL_HELPER)); STALLED to 2 rank(s)" % r),
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
        L = restore_lines(3, 12.1, "STALL_HELPER")
        for r in (0, 1, 2):
            L[r] = [x if "judged dead" not in x[1] else
                    (x[0], "GIN/RC: rank %d: rank 3 (incarnation 0) judged stalled (liveness stall judged (STALL_HELPER)); STALLED to 2 rank(s)" % r)
                    for x in L[r]]
            L[r].append((12.3, "GIN/RC: rank %d: window check after the fence of rank 3: changed=0 cells against=snapshot_at_judgement unreadable=0" % r))
        L[3] += [(2.0, "GIN/RC: rank 3: test switch FREEZE_PAGE=12000: watchBeat+helperBeat frozen")]
        trial(raw, "gc4_freeze12000_fence", k, kill=None, subject=3, dead=[3], inject="none", lines=L, probe=probe_ok(),
              meta_extra={"r3_env": "NCCL_GIN_TS_TEST_FREEZE_PAGE=12000"},
              la={"sunny": [(12.102, "FENCE of rank 3 incarnation 0 from rank 2: SIGKILL sent through its pidfd (pid 999)"),
                            (12.104, "rank 3 incarnation 0 FENCED: the group ended 1.500 ms after SIGKILL through its pidfd")]})
    # B5: the GPU-hang cell (the driver's GC_GPUHANG_IT on rank 3, SUBJECT_RANK 3, no KILL_RANK): judged STALL (row 14)
    for k in range(1, 6):
        fz = [(12.101, "GIN/RC: rank 2: rank 3 (incarnation 0) fence FENCING: FENCE sent to the launcher of node 1"),
              (12.130, "GIN/RC: rank 2: rank 3 (incarnation 0) fence FENCED (by FENCED from node 1)")]
        L = restore_lines(3, 12.1, "STALL", buddy_fence=fz, t_pub=12.45)
        for r in (0, 1, 2):
            L[r] = [x if "judged dead" not in x[1] else
                    (x[0], "GIN/RC: rank %d: rank 3 (incarnation 0) judged stalled (liveness stall judged (STALL)); STALLED to 3 rank(s)" % r)
                    for x in L[r]]
            L[r].append((12.5, "GIN/RC: rank %d: window check after the fence of rank 3: changed=0 cells against=snapshot_at_judgement unreadable=0" % r))
        L[3] += [(2.0, "GINRS gpuhang rank=3 step=155 spin=1 wait_ms=0.120")]
        trial(raw, "gc4_gpuhang12000_fence", k, kill=None, subject=3, dead=[3], inject="none", lines=L, probe=probe_ok(),
              meta_extra={"r3_env": "GC_GPUHANG_IT=155"},
              la={"sunny": [(12.102, "FENCE of rank 3 incarnation 0 from rank 2: SIGKILL sent through its pidfd (pid 999)"),
                            (12.128, "rank 3 incarnation 0 FENCED: the group ended 26.000 ms after SIGKILL through its pidfd")]})
    # B6: the GPU hang counterexample (GC_GPUHANG_CTX=1: only rank 3's sender on context 1 spins; 2026-10-24, decision (가))
    for k in range(1, 6):
        gpu_ctx1_trial(raw, k, on_stall=(k != 2))
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
                      "spare2_ready": 1, "hold": "RG-gc-G1"},
          la_pre={"rain": [(0.01, SPAWN % (1, 1, 1200, "start", 0, 1, 1)), (0.02, HELLO % (1, 1, 1200, 1200, 2, 1))],
                  "sunny": [(0.01, SPAWN % (1, 1, 1201, "start", 1, 1, 1)), (0.02, HELLO % (1, 1, 1201, 1201, 3, 1))]})
    # I: the launcher daemon's warm spare. n18: rank 3 killed twice by recorded PID; the second restore by the daemon's next
    # spare (spawned after the first activation, incarnation 2); n19: the same, no incarnation 2 spawned
    for k, second in ((18, True), (19, False)):
        L = restore_lines(3, 2.0306, "FIN+NORESP")
        for r in (0, 1, 2):
            L[r].append((2.6, "GIN/RS: rank %d: rank 3 armed at its stable checkpoint 140" % r))
        ko = [ln("sunny", 2.0, "GINRS killed rank=3 node=sunny pid=999 which=first"),
              ln("sunny", 3.0, "GINRS killed rank=3 node=sunny pid=1301 which=second")]
        la = [(2.2, "spawned spare activated (spawn 1, incarnation 1, pid 1301, by DONE): next spare incarnation 2")]
        if second:
            la += [(2.2, SPAWN % (2, 2, 1302, "activated", 1, 2, 2)), (2.5, HELLO % (2, 2, 1302, 1302, 3, 2))]
        trial(raw, "gc4_kill3_ow", k, lines=L, probe=probe_ok(), kout=ko, la={"sunny": la},
              la_pre={"sunny": [(0.01, SPAWN % (1, 1, 1301, "start", 1, 1, 1)), (0.02, HELLO % (1, 1, 1301, 1301, 3, 1))]},
              meta_extra={"kill2_rank": 3, "kill2_kind": "pid_after_armed", "armed2_rt": "2.600000", "spare2": int(second),
                          "spare2_wanted": 1, "spare2_ready": int(second), "launcher_spare_sunny": 3})
    # n20: a stale launcher socket on sunny at the trial's start (run_gc.sh exit 7: only the early meta)
    os.makedirs(raw, exist_ok=True)
    with open(os.path.join(raw, "gc4_kill3_ow_gc_n20_meta.txt"), "w") as f:
        f.write(kvline(dict(cell="gc4_kill3_ow", lib="gc", ctrl="rdma", driver="gin_mi", trial="n20", hold="C1", subject_rank=3,
                            inject="kill_traffic", launcher_scope="trial", launcher_ready=0, launcher_stale="sunny:1+0",
                            launcher_before_rain="-", launcher_before_sunny="-", runner="gcr")))
    # the spare-absent cell: the runner killed the armed spare, the launcher (--spare-respawn-max 0) did not replace it
    L = restore_lines(3, 2.0306, "FIN+NORESP")
    trial(raw, "gc4_kill3_ow_spareabsent", 1, inject="kill_spare_then_rank", lines=L, probe=probe_ok(),
          kout=[ln("sunny", 2.005, "GINRS killed rank=3 node=sunny pid=999 which=after_spare gap_ms=5.010")],
          la={"sunny": [(2.001, CAP0 % (1, 1, 1301))]},
          la_pre={"sunny": [(0.01, SPAWN % (1, 1, 1301, "start", 1, 1, 1)), (0.02, HELLO % (1, 1, 1301, 1301, 3, 1))]},
          meta_extra={"kill_kind": "spare_then_rank", "launcher_respawn_max": 0, "spare_gap_ms": 5})
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
    # I: launcher_gc.sh stale on a scratch root (rain = this machine, no ssh; never the real /tmp): a left socket counts
    import socket
    root = os.path.join(R, "stale_root")
    os.makedirs(os.path.join(root, "gc_la.abc123"))
    e0 = subprocess.run(["bash", os.path.join(HERE, "launcher_gc.sh"), "stale", "rain", ld, "h2"], stdout=subprocess.PIPE,
                        env=dict(lenv, LA_STALE_ROOT=root)).stdout.decode().strip()
    so = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    so.bind(os.path.join(root, "gc_la.abc123", "launcher.sock"))
    e1 = subprocess.run(["bash", os.path.join(HERE, "launcher_gc.sh"), "stale", "rain", ld, "h2"], stdout=subprocess.PIPE,
                        env=dict(lenv, LA_STALE_ROOT=root)).stdout.decode().strip()
    # start: a refused --spare-env ends before anything (exit 2); a stale socket: nothing started, exit 3 and its line
    st1 = subprocess.run(["bash", os.path.join(HERE, "launcher_gc.sh"), "start", "rain", ld, "h3", "--spare-cmd", "bash x",
                          "--spare-env", "NCCL_GIN_RESTORE_RECORD=/x"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         env=dict(lenv, LA_STALE_ROOT=root))
    st2 = subprocess.run(["bash", os.path.join(HERE, "launcher_gc.sh"), "start", "rain", ld, "h4", "--spare-cmd", "bash x",
                          "--spare-env", "RS_STEPS=600", "--spare-log", root], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         env=dict(lenv, LA_STALE_ROOT=root))
    so.close()
    check(e0.startswith("stale sock=0 ") and e1.startswith("stale sock=1 "), "I: the stale socket check (%r, %r)" % (e0, e1))
    check(st1.returncode == 2 and st2.returncode == 3 and st2.stdout.decode().startswith("stale sock=1 ")
          and not os.path.exists(os.path.join(ld, "la_h4_rain.rec")),
          "I: start refuses a record variable (rc %d) and starts nothing on a stale socket (rc %d, %r)" % (
              st1.returncode, st2.returncode, st2.stdout.decode().strip()))


def rule(pid, cell=None):
    """the per-trial rule of prediction pid in predictions_gc.csv (the part for cell when the row has one rule per cell)"""
    import csv as _csv
    acc = [p for p in _csv.DictReader(open(score_gc.PREDS, encoding="utf-8")) if p["id"] == pid][0]["acceptance"]
    if cell is not None:
        acc = [x for x in acc.split(";;") if x.strip().startswith(cell + ":")][0].split(":", 1)[1]
    acc = acc.strip()
    return acc[len("count("):acc.rindex(")")]


def revision_checks(A, B, F):
    """J: section 3's 2026-10-22 revision (stall causes STALL_HELPER, launcher-report band 100-150 ms, W to W + 2 ms) on
    copies of rows A (confirm window), B (EXITED 120 ms) and F (freeze, STALL_HELPER), and the drift check"""
    ok = score_gc.s2.cond_true
    as_stall = lambda r: dict(r, n_judge_stall=r["n_judge_stall_helper"], n_judge_stall_helper=0)
    fr = rule("freeze_fence_restore")
    check(ok(fr, F) and not ok(fr, as_stall(F)), "J: freeze_fence_restore takes STALL_HELPER, a STALL copy fails")
    sn = rule("stall_none_refuse")
    S = dict(n_judge_stall_helper=3, n_judge_stall=0, decline_n=1, surv_released=3, n_surv=3, win_changed_after=0, win_verified=1)
    check(ok(sn, S) and not ok(sn, as_stall(S)), "J: stall_none_refuse takes STALL_HELPER, a STALL copy fails")
    sf = rule("stall_fence_restore")
    check("n_judge_stall_helper == n_judge" in sf and not re.search(r"\bn_judge_stall\b", sf),
          "J: stall_fence_restore counts STALL_HELPER only (%s)" % sf[:60])
    fu = rule("fdhold_uverbs_refuse")
    U = dict(n_judge=3, n_surv=3, n_judge_exited=1, n_judge_stall_helper=1, n_judge_stall=1, restore_count=0, decline_n=1,
             surv_released=3)
    check(ok(fu, U) and ok(fu, dict(U, n_judge_exited=3, n_judge_stall_helper=0, n_judge_stall=0))
          and not ok(fu, dict(U, n_judge_stall=0)), "J: fdhold_uverbs_refuse takes EXITED or either stall cause, every judgement counted")
    kj, fe = rule("kill_judge_rdma", "gc4_kill3_ow@gc"), rule("finless_exit_report")
    kw = rule("kill_no_witness")
    Bw = dict(B, judge_to_publish_ms=70.0, hold_other_n=0, hold_after_restore_n=0)
    for ms, want in ((101.0, True), (120.0, True), (149.0, True), (99.0, False), (151.0, False), (160.0, False)):
        e = dict(kill_judge_ms_min=ms, kill_judge_ms_max=ms, kill_judge_exited_min_ms=ms, kill_judge_exited_max_ms=ms)
        got = (ok(kj, dict(B, **e)), ok(fe, dict(B, **e)), ok(kw, dict(Bw, **e)))
        check(got == (want,) * 3, "J: EXITED %g ms after the kill: kill_judge_rdma, finless_exit_report, kill_no_witness %r (want %r)" % (
            ms, got, want))
    for dev, want in ((1.5, True), (2.0, True), (2.5, False)):
        check(ok(kj, dict(A, fin_judge_dev_max_ms=dev)) == want, "J: confirm window judgement W + %g ms: %r" % (dev, not want))
    import csv as _csv
    import check_cells_gc as cc
    text = open(os.path.join(HERE, "..", "..", "EXPERIMENT.md"), encoding="utf-8").read()
    s3 = {}
    for cols in cc.table_rows(cc.section(text, 3)):
        m = re.search(r"`([a-z0-9_]+)`", cols[-1])
        if m:
            s3[m.group(1)] = cols
    pr = {p["id"]: p for p in _csv.DictReader(open(score_gc.PREDS, encoding="utf-8"))}
    now = {pid: cc.drift(p, s3[pid]) for pid, p in pr.items() if pid in s3}
    check(not any(now.values()), "J: no drift against section 3 (%s)" % [x for v in now.values() for x in v][:2])
    old = {"stall_fence_restore": ("acceptance", "n_judge_stall_helper == n_judge", "n_judge_stall == n_judge"),
           "fdhold_uverbs_refuse": ("acceptance", " + n_judge_stall_helper", ""),
           "kill_judge_rdma": ("acceptance", "kill_judge_exited_max_ms <= 150", "kill_judge_exited_max_ms <= 206"),
           "rst_judge_rdma": ("acceptance", "rst_judge_dev_max_ms <= 2", "rst_judge_dev_max_ms <= 1"),
           "none_probe_clean": ("acceptance", "beat_gap_max_ms < 300", "beat_gap_max_ms <= 300"),
           "finless_read_fail": ("per_trial", "NORESP", "STALL")}
    for pid, (col, a, b) in old.items():
        p = dict(pr[pid])
        p[col] = p[col].replace(a, b)
        check(a in pr[pid][col] and cc.drift(p, s3[pid]), "J: the drift check catches %s with %r for %r" % (pid, b, a))


def int3_checks():
    """REVIEW_INT3 B1, B3, F6, F7 on a folder of their own (the main folder's verdicts stay as they are)"""
    R = tempfile.mkdtemp(prefix="gc_selftest_int3_")
    raw = os.path.join(R, "raw")
    try:
        # B1: the 2a-2-C status page line (", device line named 1184 B" after W=) and a SUSPECT line naming the subject
        L = restore_lines(3, 2.120, "EXITED")
        for r in range(N):
            L[r].insert(0, (0.55, "GIN/RC: rank %d: status page up (320 B in use, probe_ms=100 stall_ms=10000 W=20, device line "
                                  "named 1184 B)" % r))
        L[0].append((2.05, "GIN/RC: rank 0: rank 3 suspected (kind=watch stale_ms=2000.8)"))
        trial(raw, "gc4_kill3_ow", 31, lines=L, probe=probe_ok(), page=False, la={"sunny": [(2.119, EXITED3)]})

        # B3: the UD REJOIN as smoke3 logs it: survivors' FIN, the REJOIN taken, the fd -1 install, re-dialled, the real
        # reconnect; the spare re-dials and reconnects each peer before its live line; bootstrap bytes 5616 per survivor
        def ud_restore(reconnect=True):
            L = restore_lines(3, 2.120, "EXITED")
            for r in (0, 1, 2):
                L[r] = [x for x in L[r] if "reconnected" not in x[1]]
                L[r] += [(2.0003, "GIN/TS: rank %d: socket to rank 3 closed cause=FIN liveness=pending (the confirm window judges: W=20 ms)" % r),
                         (2.140, "GIN/RC: rank %d: the REJOIN of rank 3 (incarnation 1) taken over UD: record QP gen 1048577" % r),
                         (2.1401, "GIN/TS: rank %d: socket to rank 3 reconnected gen=1 attempts=0" % r),
                         (2.1402, "GIN/RC: rank %d: rank 3's witness socket after its REJOIN over UD: unknown, re-dialled" % r)]
                if reconnect:
                    L[r].append((2.200, "GIN/TS: rank %d: socket to rank 3 reconnected gen=2 attempts=1" % r))
                L[r].append((8.9, "GIN/TS: rank %d: socket to rank 3 closed cause=FIN liveness=left" % r))
            L["spare"] = [(2.141 + 0.01 * p, "GIN/RC: rank 3: rank %d's witness socket after its REJOIN over UD: unknown, re-dialled" % p)
                          for p in (0, 1, 2)] + [(2.199, "GIN/TS: rank 3: socket to rank %d reconnected gen=2 attempts=0" % p) for p in (0, 1, 2)]
            return L
        trial(raw, "gc4_kill3_ow", 32, lines=ud_restore(), probe=probe_ok(), rec_bytes=5616, la={"sunny": [(2.119, EXITED3)]})
        trial(raw, "gc4_kill3_ow", 33, lines=ud_restore(), probe=probe_ok(), rec_bytes=5616, ctrl_kv=" tcp_record_bytes_prelive=5616",
              la={"sunny": [(2.119, EXITED3)]})
        trial(raw, "gc4_kill3_ow", 34, lines=ud_restore(), probe=probe_ok(), rec_bytes=5616, ctrl_kv=" tcp_record_bytes_live=1872",
              la={"sunny": [(2.119, EXITED3)]})
        trial(raw, "gc4_kill3_ow", 35, lines=ud_restore(reconnect=False), probe=probe_ok(), la={"sunny": [(2.119, EXITED3)]})
        # F6: a rank-side STOP_launcher line, a launcher Unix socket loss line, and one more after the trial_end marker
        L = restore_lines(3, 2.120, "EXITED")
        L[1].append((3.0, "GIN/RC: rank 1: rank 3 (incarnation 1) fence: the launcher of node 1 is lost (QP error) (STOP_launcher)"))
        L[2] += [(3.1, "GIN/RC: rank 2: launcher Unix socket closed (EOF)"), (21.0, "GIN/RC: rank 2: launcher Unix socket closed (EPIPE)")]
        trial(raw, "gc4_kill3_ow", 36, lines=L, probe=probe_ok(), la={"sunny": [(2.119, EXITED3)]})
        # F7: rank 2's ring never went live (n37); rank 1's live line 12 s after its start, beyond the setup bound (n38)
        trial(raw, "gc4_kill3_ow", 37, lines=restore_lines(3, 2.120, "EXITED"), probe=probe_ok(), live_ranks=(0, 1, 3),
              la={"sunny": [(2.119, EXITED3)]})
        L = restore_lines(3, 2.120, "EXITED")
        L[1].append((12.0, LIVE % 1))
        trial(raw, "gc4_kill3_ow", 38, lines=L, probe=probe_ok(), live_ranks=(0, 2, 3), la={"sunny": [(2.119, EXITED3)]})
        rows = {r["id"]: r for r in rows_gc.all_rows(R)}
        b1 = rows["gc4_kill3_ow_gc_n31"]
        check(b1["confirm_w_ms"] == 20 and b1["probe_ms_page"] == 100 and b1["suspect_n"] == 1,
              "INT3 B1: W, the READ period and suspect_n from the device-line PAGEUP form (%r %r %r)" % (
                  b1["confirm_w_ms"], b1["probe_ms_page"], b1["suspect_n"]))
        r32, r33, r34, r35 = (rows["gc4_kill3_ow_gc_n%d" % k] for k in (32, 33, 34, 35))
        check(r32["ring_live_pairs"] == 6 and r32["tcp_ctrl_conn_n"] == r32["witness_pairs"] == r32["witness_expected"] == 6,
              "INT3 B3 (b, c): the UD restore's new pairs replace the old, the fd -1 install is not a socket (%r %r)" % (
                  r32["witness_pairs"], r32["witness_expected"]))
        check(r32["tcp_ctrl_bytes"] == "" and r32["tcp_record_bytes_unsplit"] == 3 * 5616 and r32["tcp_record_bytes_prelive"] == 0,
              "INT3 B3 (a): a summary without the live split leaves the bytes unknown (%r %r)" % (
                  r32["tcp_ctrl_bytes"], r32["tcp_record_bytes_unsplit"]))
        check(r33["tcp_ctrl_bytes"] == 0 and r33["tcp_record_bytes_prelive"] == 3 * 5616 and r33["tcp_record_bytes_unsplit"] == 0,
              "INT3 B3 (a): the bootstrap bytes before live apart, 0 after (%r %r)" % (r33["tcp_ctrl_bytes"], r33["tcp_record_bytes_prelive"]))
        check(r34["tcp_ctrl_bytes"] == 3 * 1872, "INT3 B3 (a): bytes after live counted (%r)" % r34["tcp_ctrl_bytes"])
        check(r35["witness_pairs"] == 3 and r35["witness_expected"] == 6,
              "INT3 B3: a new incarnation's witness never re-dialled (%r)" % r35["witness_pairs"])
        import csv as _csv
        nt = [p for p in _csv.DictReader(open(score_gc.PREDS, encoding="utf-8")) if p["id"] == "no_tcp_control"][0]["acceptance"]
        nt = nt[len("count("):nt.rindex(")")]
        check(score_gc.s2.cond_true(nt, r33) and not any(score_gc.s2.cond_true(nt, x) for x in (r32, r34, r35)),
              "INT3 B3: no_tcp_control's per-trial rule holds on the split bootstrap bytes only")
        f6 = rows["gc4_kill3_ow_gc_n36"]
        s36 = subprocess.run([sys.executable, os.path.join(HERE, "rows_gc.py"), "--stops", os.path.join(raw, "gc4_kill3_ow_gc_n36")],
                             stdout=subprocess.PIPE).stdout.decode().strip()
        check(f6["rank_stop_n"] == 1 and f6["rank_la_sock_lost_n"] == 1 and f6["la_stop_n"] == 2 and "la_stop_n=2 " in s36,
              "INT3 F6: the rank side's STOP_launcher and Unix socket lines before trial_end (%r %r %s)" % (
                  f6["rank_stop_n"], f6["rank_la_sock_lost_n"], s36))
        check(rows["gc4_kill3_ow_gc_n37"]["ring_live_n"] == 3 and rows["gc4_kill3_ow_gc_n38"]["ring_live_all"] == 0
              and r32["ring_live_all"] == 1, "INT3 F7: a rank without a live line, one beyond the bound")
        _, srows = score_gc.score(R)
        st = {r["id"]: r["status"] for r in srows}
        # Codex review 2026-10-23 item 4: a ring that did not go live under the cell's configuration is a preparation
        # failure (counted, never refilled), no longer the exclusion ring_not_live
        check(st["gc4_kill3_ow_gc_n37"] == st["gc4_kill3_ow_gc_n38"] == "prep_failure" and st["gc4_kill3_ow_gc_n32"] == "scored",
              "INT3 F7 (review item 4): a ring not live is a prep failure (%s, %s, %s)" % (
                  st["gc4_kill3_ow_gc_n37"], st["gc4_kill3_ow_gc_n38"], st["gc4_kill3_ow_gc_n32"]))
        md = open(os.path.join(R, "SCORE.md"), encoding="utf-8").read()
        check("gc4_kill3_ow_gc_n37(prep_failure), gc4_kill3_ow_gc_n38(prep_failure)" in md and
              "Unix 소켓 끊김 줄 1개 포함" in md and "gc4_kill3_ow_gc_n36(2)" in md, "INT3 F6, F7: SCORE.md lists them")
    finally:
        shutil.rmtree(R, ignore_errors=True)


# real lines and kv of the hardware smokes (address-redacted raw logs, ../../results/20261023_smoke4/a1/raw/)
REAL_CTRLSUM = ("GIN/RC: rank 1: control summary tcp_record_bytes=7488 tcp_data_bytes=0 tcp_conns=0 witness_conns=3 records_lost=0 "
                "records_dup=0 repairs=0 sendq_deferred=0 sendq_max=0 rnr=0 async=0 active_mtu=5 tcp_rx_bytes_peer0=3744 "
                "tcp_rx_bytes_peer2=1872 tcp_rx_bytes_peer3=1872 async_rec=0 async_read=0 async_la=0 tcp_late_records=0 "
                "tcp_record_bytes_prelive=7488 tcp_record_bytes_live=0 tcp_data_bytes_prelive=0 tcp_data_bytes_live=0 live=1")
REAL_SPARE_KV = dict(mode="spare", rank=3, nranks=4, buddy=2, steps=600, bytes=4096, rs_device_macro=1, rs_api=1, workload="overwrite",
                     overwrite=1, train=0, ring=0, mirror_env=1, checksum_env="off", gpuhang_it=-1, init_rc=0, reg_rc=0,
                     devcomm_rc=0, register_rc=0, registered=1)  # the warm spare that was never activated: no revived, no steps
WIN = "GIN/RC: rank %d: window check after the fence of rank 3: changed=%d cells against=snapshot_at_judgement unreadable=%d"
WHY41 = ("GIN/RS:_ncclGinRestoreResume:_the_restore_cannot_be_enabled_on_this_communicator:_rank_1:_the_restore_was_asked_but_this_"
         "rank_is_not_paired_with_its_node's_launcher")  # smoke1 a1, rank 1's kv (Resume condition 41: a preparation failure)
WHY42 = ("GIN/RS:_ncclGinRestoreResume:_the_restore_cannot_be_enabled_on_this_communicator:_rank_1:_a_rank's_active_MTU_is_below_"
         "2048_(a_control_datagram_does_not_fit)_(rank_1's_active_MTU_(enum_3)_is_below_2048)")  # condition 42: configuration


def review_checks():
    """Codex review 2026-10-23: (1) the ibv_mtu enum in bytes, (2) data equality over the final generation (an unused
    warm spare contributes nothing), (3) the window check's completeness (unreadable cells, a missing survivor line),
    (4) Resume refusals and a ring not live: config only for a named configuration, else a prep failure that keeps its
    place, (5) safety predictions at 0 failures, (6) the event timeline on the subject node's survivor"""
    R = tempfile.mkdtemp(prefix="gc_selftest_review_")
    raw = os.path.join(R, "raw")
    ok = score_gc.s2.cond_true
    try:
        def kill_lines(extra=None):
            return restore_lines(3, 2.0206, "FIN+STALE", extra=extra)
        la = {"sunny": [(2.119, EXITED3)]}
        # gc4_kill3_ow@gc (planned 10): n1 the timeline (rank 1's window line only: ranks 0 and 2 miss theirs), n2 a
        # Resume refusal by condition 41 (prep), n3 by condition 42 (config), n4 a ring not live (prep), n5 a ring not
        # live after the setup agreement's condition 42 (config), n6 a data mismatch, n7 every window line, n8 one
        # unreadable=48, n9-n13 good (n13 beyond the plan)
        tl = {1: [(2.0003, "GIN/RC: rank 1: confirm window for rank 3 opened by FIN W=20 over the watch beat"),
                  (2.100, WIN % (1, 0, 0)),
                  (2.300, "GINRS step rank=1 step=139 released=0 tx_err=0 hook_rc=0 stable=120")]}
        trial(raw, "gc4_kill3_ow", 1, lines=kill_lines(tl), probe=probe_ok(), la=la)
        trial(raw, "gc4_kill3_ow", 2, lines=kill_lines(), probe=probe_ok(), la=la,
              kv_extra={1: {"resume_rc": 5, "resume_why": WHY41}})
        trial(raw, "gc4_kill3_ow", 3, lines=kill_lines(), probe=probe_ok(), la=la,
              kv_extra={r: {"resume_rc": 5, "resume_why": WHY42} for r in range(N)})
        trial(raw, "gc4_kill3_ow", 4, lines=kill_lines(), probe=probe_ok(), la=la, live_ranks=(0, 1, 3))
        L = kill_lines()
        L[2].append((0.55, "GIN/RC: rank 2: setup agreement: rank 1's active MTU (enum 3) is below 2048 (rank 1): transparent "
                           "recovery off at the setup (Resume condition 42) min_active_mtu=3"))
        trial(raw, "gc4_kill3_ow", 5, lines=L, probe=probe_ok(), la=la, live_ranks=(0, 1, 3))
        trial(raw, "gc4_kill3_ow", 6, lines=kill_lines(), probe=probe_ok(), la=la, kv_extra={0: {"x_match": 0}})
        trial(raw, "gc4_kill3_ow", 7, lines=kill_lines({r: [(2.1, WIN % (r, 0, 0))] for r in (0, 1, 2)}), probe=probe_ok(), la=la)
        trial(raw, "gc4_kill3_ow", 8, lines=kill_lines({r: [(2.1, WIN % (r, 0, 48 if r == 0 else 0))] for r in (0, 1, 2)}),
              probe=probe_ok(), la=la)
        for k in range(9, 14):
            trial(raw, "gc4_kill3_ow", k, lines=kill_lines(), probe=probe_ok(), la=la)
        # the killed rank's spare that never revived (the warm spare's kv): the restore was expected, data_equal 0
        trial(raw, "gc4_kill3_ow_nowitness", 1, witness="0", lines=kill_lines(), probe=probe_ok(), la=la, spare_kv=REAL_SPARE_KV)
        # fault-free with the unused warm spare (smoke4 a1's form: active_mtu=5 in the summaries, none in the kv), a copy
        # with a data mismatch on rank 2, and a copy whose summaries say enum 3 (1024 B)
        nomtu = {r: {"active_mtu": None} for r in range(N)}
        ff = dict(kill=None, subject=None, inject="none", killed=False, probe=probe_ok(), spare_kv=REAL_SPARE_KV)
        trial(raw, "gc4_none_ow", 1, mtu="5", kv_extra=nomtu, lines={1: [(9.5, REAL_CTRLSUM)]}, **ff)
        trial(raw, "gc4_none_ow", 2, mtu="5", kv_extra={r: ({"active_mtu": None, "x_match": 0} if r == 2 else {"active_mtu": None}) for r in range(N)}, **ff)
        trial(raw, "gc4_none_ow", 3, mtu="3", kv_extra=nomtu, **ff)
        # gin-mirror's regression cell at @gc with the condition 41 refusal: a prep failure there too
        trial(raw, "mi4_kill3_ow", 1, lines=kill_lines(), probe=probe_ok(), la=la, meta_extra={"hold": "RG-gc-G1"},
              kv_extra={1: {"resume_rc": 5, "resume_why": WHY41}})
        rows = {r["id"]: r for r in rows_gc.all_rows(R)}
        g = lambda k: rows["gc4_kill3_ow_gc_n%d" % k]
        # (1) MTU
        f1, f3 = rows["gc4_none_ow_gc_n1"], rows["gc4_none_ow_gc_n3"]
        check([rows_gc.mtu_bytes(x) for x in ("1", "3", "5", "4096", "0", "")] == [256, 1024, 4096, 4096, None, None],
              "review 1: the ibv_mtu enum 1..5 is 256..4096 B, a byte value stays")
        nt = rule("no_tcp_control")
        check(f1["active_mtu_kv_min"] == 4096 and ok(nt, f1) and f3["active_mtu_kv_min"] == 1024 and not ok(nt, f3),
              "review 1: active_mtu=5 in the real summary is 4096 B; enum 3 fails no_tcp_control (%r %r)" % (
                  f1["active_mtu_kv_min"], f3["active_mtu_kv_min"]))
        # (2) data equality
        check(f1["data_equal"] == 1 and f1["ow_data_equal"] == 1 and f1["spare_state"] == "unused" and f1["final_gen_n"] == 4,
              "review 2: fault-free with the unused warm spare: data equal over the four ranks (%r %r %r)" % (
                  f1["data_equal"], f1["ow_data_equal"], f1["spare_state"]))
        check(rows["gc4_none_ow_gc_n2"]["data_equal"] == 0 and rows["gc4_none_ow_gc_n2"]["ow_data_equal"] == 0,
              "review 2: a rank's mismatch still fails it")
        nr = rows["gc4_kill3_ow_nowitness_gc_n1"]
        check(nr["data_equal"] == 0 and nr["ow_data_equal"] == 0 and nr["spare_state"] == "not_restored"
              and g(9)["spare_state"] == "restored" and g(9)["ow_data_equal"] == 1 and g(6)["ow_data_equal"] == 0,
              "review 2: a killed rank whose spare did not revive fails, a revived one counts (%r %r)" % (
                  nr["spare_state"], g(9)["spare_state"]))
        # (3) the window check
        check(g(7)["win_verified"] == 1 and g(7)["win_changed_after"] == 0 and g(7)["win_lines_n"] == 3,
              "review 3: every survivor's line, all read, no change: verified (%r)" % g(7)["win_verified"])
        check(g(8)["win_verified"] == 0 and g(8)["win_unreadable"] == 48 and g(8)["win_changed_after"] == "",
              "review 3: unreadable=48 is not '0 changes' (%r %r)" % (g(8)["win_verified"], g(8)["win_changed_after"]))
        check(g(1)["win_verified"] == 0 and g(1)["win_missing"] == "0+2" and g(1)["win_changed_after"] == "",
              "review 3: a survivor without its line: not verified (%r %r)" % (g(1)["win_verified"], g(1)["win_missing"]))
        ff_rule = rule("freeze_fence_restore")
        import csv as _csv0
        wrules = [p["acceptance"] for p in _csv0.DictReader(open(score_gc.PREDS, encoding="utf-8"))]
        check(not ok("win_verified == 1", g(8)) and not ok("win_verified == 1", g(1)) and ok("win_verified == 1", g(7))
              and "win_verified == 1" in ff_rule and not any("win_changed_after == 0" in a for a in wrules)
              and sum("win_verified == 1" in a for a in wrules) == 6,
              "review 3: the six window rules (five on 2026-10-23, the GPU hang counterexample's 2026-10-24) read "
              "win_verified == 1, false on an incomplete window")
        # (4) refusal classes
        check(g(2)["resume_refusal"] == "prep" and g(3)["resume_refusal"] == "config" and g(4)["ring_not_live_class"] == "prep"
              and g(5)["ring_not_live_class"] == "config" and "not paired with its node's launcher" in g(2)["resume_why_refused"],
              "review 4: refusal and ring classes (%r %r %r %r)" % (g(2)["resume_refusal"], g(3)["resume_refusal"],
                                                                  g(4)["ring_not_live_class"], g(5)["ring_not_live_class"]))
        # (6) the timeline on rank 1 (subject 3's node), ms after the kill (2.0 s on sunny)
        t = g(1)
        want = dict(t_suspect_ms=0.3, t_judge_ms=20.6, t_block_ms=21.6, t_fenced_ms=100.0, t_publish_ms=170.6, t_first_ok_ms=300.0)
        check(t["tl_rank"] == 1 and t["tl_clock"] == "mono" and t["t_fenced_src"] == "window_fence" and t["t_first_ok_step"] == 139
              and all(t[k] != "" and abs(t[k] - v) < 0.01 for k, v in want.items()),
              "review 6: the timeline on rank 1 (%s)" % {k: t[k] for k in want})
        check(g(9)["t_first_ok_ms"] == "" and g(9)["t_fenced_ms"] == "", "review 6: no step line, no window line: empty")
        # (4), (5) the scorer: the prep failures keep their places; a safety copy of a rule fails on one bad trial
        tmp = os.path.join(R, "preds.csv")
        import csv as _csv
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = _csv.DictWriter(f, fieldnames=["id", "predicted", "cells", "kind", "acceptance", "todo"], quoting=_csv.QUOTE_ALL)
            w.writeheader()
            for kd in ("safety", "perf"):
                w.writerow(dict(id="t_" + kd, predicted="t", cells="gc4_kill3_ow@gc", kind=kd,
                                acceptance="count(ow_data_equal == 1) >= 7", todo=""))
            # EXPERIMENT 8 (2026-10-23): a perf rule failing its count is re-examined too; one without a safety term is not
            w.writerow(dict(id="t_perf_count", predicted="t", cells="gc4_kill3_ow@gc", kind="perf",
                            acceptance="count(ow_data_equal == 1 and n_judge == n_surv) >= 8", todo=""))
            w.writerow(dict(id="t_perf_plain", predicted="t", cells="gc4_kill3_ow@gc", kind="perf",
                            acceptance="count(n_judge == n_surv) >= 7", todo=""))
        import io, contextlib
        old, score_gc.PREDS = score_gc.PREDS, tmp
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                verd, srows = score_gc.score(R)
        finally:
            score_gc.PREDS = old
        st = {r["id"]: r["status"] for r in srows}
        sk = lambda k: st["gc4_kill3_ow_gc_n%d" % k]
        check([sk(k) for k in range(1, 14)] == ["scored", "prep_failure", "config", "prep_failure", "config"] + ["scored"] * 7 +
              ["surplus"], "review 4: statuses %s" % [sk(k) for k in range(1, 14)])
        check(st["mi4_kill3_ow_gc_n1"] == "prep_failure", "review 4: the regression cell's prep refusal (%s)" % st["mi4_kill3_ow_gc_n1"])
        check(verd.get("t_safety") == "틀림" and verd.get("t_perf") == "재검토(안전성 항 어긋남 1/8)",
              "review 5, EXPERIMENT 8: one data mismatch in 8: safety 틀림, perf passing its count (>= 7) 재검토 (%s, %s)" % (
                  verd.get("t_safety"), verd.get("t_perf")))
        check(verd.get("t_perf_count") == "재검토(안전성 항 어긋남 1/8)" and verd.get("t_perf_plain") == "맞음",
              "EXPERIMENT 8: a perf rule failing its count with a safety term false is 재검토, one without a safety term keeps 맞음 (%s, %s)" % (
                  verd.get("t_perf_count"), verd.get("t_perf_plain")))
        check(score_gc.SAFETY_TERMS[:2] == ("data_equal", "ow_data_equal") and "win_verified" in score_gc.SAFETY_TERMS
              and "fence_order_ok" in score_gc.SAFETY_TERMS, "EXPERIMENT 8: SAFETY_TERMS names the columns")
        out = buf.getvalue()
        md = open(os.path.join(R, "SCORE.md"), encoding="utf-8").read()
        check("[safety] gc4_kill3_ow@gc planned=10 run=13 excluded=config:2 prep_failure=2 scored=8 cond=7/8 whole=7/10" in out,
              "review 4: the output's per-prediction counts (%s)" % [x for x in out.splitlines() if "planned=" in x][:1])
        check("| `gc4_kill3_ow@gc` | 10 | 13 | config 2 | 2 | 8 | 0 | `ow_data_equal == 1` | 7/8 = 87.5 % | 7/10 = 70.0 % |" in md
              and "성능 예측 안의 안전성 항(어긋나면 재검토, 8절) `gc4_kill3_ow@gc` `ow_data_equal == 1`: 실패 1/8 (gc4_kill3_ow_gc_n6)" in md
              and "안전성 항 어긋남(재검토): `gc4_kill3_ow_gc_n6` (`ow_data_equal == 1`)" in md
              and "안전 예측의 실패(실패 0 규칙)" in md, "review 4, 5: SCORE.md's counts, rates and safety lines")
        # (5) the kind column: every row has one, cost rows are cost
        import csv as _csv2
        pr = list(_csv2.DictReader(open(score_gc.PREDS, encoding="utf-8")))
        check(all(p["kind"] in score_gc.KINDS for p in pr) and
              all((p["kind"] == "cost") == p["acceptance"].startswith("cost:") for p in pr),
              "review 5: predictions_gc.csv kind is safety, perf or cost on every row")
    finally:
        shutil.rmtree(R, ignore_errors=True)


def ctrlsum_checks():
    """Codex review 2026-10-23 (control summary): a required process without its control summary, a summary without a
    counter, and a window line without unreadable= are 자료 부족 or incomplete, never a pass by a 0 that was not read"""
    import io, contextlib
    ok = score_gc.s2.cond_true
    tops = []
    try:
        def credit(R, edit=None, act=False):
            """five gc4_credit_stall@gc trials (the switch on rank 2, fault-free, the unused warm spare); edit(stem) changes
            the raw files after they are written; act: rank 3 died and its spare revived (kv revived=1, its summary)"""
            for k in range(1, 6):
                st = trial(os.path.join(R, "raw"), "gc4_credit_stall", k, kill=3 if act else None, subject=2, inject="none",
                           killed=act, probe=probe_ok(), spare_kv=None if act else REAL_SPARE_KV, ctrl_kv=" sendq_deferred=4",
                           meta_extra={"r2_env": "NCCL_GIN_CTRL_TEST_CREDIT_STALL=3000:500"},
                           lines={2: [(3.0, "GIN/RC: rank 2: test switch CREDIT_STALL: no RECV re-posted for 500 ms")]})
                if edit:
                    edit(st)

        def sub(path, old, new):
            t = open(path).read()
            with open(path, "w") as f:
                f.write("\n".join(new(x) if old in x else x for x in t.split("\n")))
        drop_r1 = lambda st: sub(st + "_r1.log", "control summary", lambda x: "")
        no_lost = lambda st: sub(st + "_r0.log", "control summary", lambda x: x.replace(" records_lost=0", ""))
        rm = lambda suf: (lambda st: os.remove(st + suf))
        res = {}
        for tag, ed, act in (("good", None, False), ("nosum", drop_r1, False), ("nolost", no_lost, False),
                             ("act", None, True), ("act_nolog", rm("_spare.log"), True), ("dead_nolog", rm("_r3.log"), True)):
            R = tempfile.mkdtemp(prefix="gc_selftest_ctrlsum_")
            tops.append(R)
            credit(R, ed, act)
            rows = {r["id"]: r for r in rows_gc.all_rows(R)}
            with contextlib.redirect_stdout(io.StringIO()):
                verd, _ = score_gc.score(R)
            res[tag] = (rows["gc4_credit_stall_gc_n1"], verd)
        cr, nt = rule("credit_stall_no_loss"), rule("no_tcp_control")
        g, vg = res["good"]
        check(g["ctrlsum_missing"] == "" and g["ctrlsum_fields_missing"] == "" and g["rec_lost_n"] == 0 and g["sendq_deferred"] == 16
              and ok(cr, g) and ok(nt, g) and vg.get("credit_stall_no_loss") == "맞음",
              "ctrlsum: the control (every summary, every counter): both rules hold, credit_stall_no_loss 맞음 (%r %r %s)" % (
                  g["ctrlsum_missing"], g["sendq_deferred"], vg.get("credit_stall_no_loss")))
        m, vm = res["nosum"]
        empty = ("tcp_ctrl_bytes", "tcp_data_bytes", "rec_lost_n", "rec_dup_n", "rnr_n", "sendq_deferred", "tcp_record_bytes_prelive")
        check(m["ctrlsum_missing"] == "r1" and all(m[c] == "" for c in empty) and not ok(cr, m) and not ok(nt, m)
              and vm.get("credit_stall_no_loss") == "자료 부족" and vm.get("no_tcp_control") == "자료 부족",
              "ctrlsum: rank 1 without its summary: the summary columns empty, both rules 자료 부족 (%r %s %s)" % (
                  m["ctrlsum_missing"], vm.get("credit_stall_no_loss"), vm.get("no_tcp_control")))
        f, vf = res["nolost"]
        check(f["ctrlsum_missing"] == "" and f["ctrlsum_fields_missing"] == "r0:records_lost" and f["rec_lost_n"] == ""
              and f["rec_dup_n"] == 0 and not ok(cr, f) and vf.get("credit_stall_no_loss") == "자료 부족",
              "ctrlsum: a summary without records_lost: rec_lost_n empty (not 0), credit_stall_no_loss 자료 부족 (%r %r %s)" % (
                  f["ctrlsum_fields_missing"], f["rec_lost_n"], vf.get("credit_stall_no_loss")))
        # Codex re-check 2026-10-23: the active spare's .log removed, its kv (revived=1) kept: still required, named spare:nolog
        a, va = res["act"]
        s, vs = res["act_nolog"]
        check(a["ctrlsum_missing"] == "" and a["dead_log_missing"] == "" and a["rec_lost_n"] == 0 and ok(cr, a) and ok(nt, a)
              and s["ctrlsum_missing"] == "spare:nolog" and all(s[c] == "" for c in empty) and not ok(cr, s) and not ok(nt, s)
              and vs.get("credit_stall_no_loss") == "자료 부족" and vs.get("no_tcp_control") == "자료 부족",
              "ctrlsum: the active spare without its .log (kv revived=1 kept): spare:nolog, the summary columns empty, both "
              "rules 자료 부족 (%r %r %s %s)" % (a["ctrlsum_missing"], s["ctrlsum_missing"], vs.get("credit_stall_no_loss"),
                                                vs.get("no_tcp_control")))
        x, _ = res["dead_nolog"]
        check(x["dead_log_missing"] == "r3" and x["ctrlsum_missing"] == "" and a["dead_log_missing"] == "",
              "ctrlsum: the killed rank's .log removed: dead_log_missing r3, no summary required of it (%r %r)" % (
                  x["dead_log_missing"], x["ctrlsum_missing"]))
        # the window line of rank 1 without unreadable=: incomplete, not verified, no change count
        R = tempfile.mkdtemp(prefix="gc_selftest_win_")
        tops.append(R)
        wl = {r: [(2.1, WIN % (r, 0, 0) if r != 1 else
                   "GIN/RC: rank 1: window check after the fence of rank 3: changed=0 cells against=snapshot_at_judgement")]
              for r in (0, 1, 2)}
        trial(os.path.join(R, "raw"), "gc4_kill3_ow", 1, lines=restore_lines(3, 2.0206, "FIN+STALE", extra=wl), probe=probe_ok(),
              la={"sunny": [(2.119, EXITED3)]})
        w = {r["id"]: r for r in rows_gc.all_rows(R)}["gc4_kill3_ow_gc_n1"]
        check(w["win_verified"] == 0 and w["win_missing"] == "1:unreadable" and w["win_changed_after"] == "" and w["win_unreadable"] == ""
              and w["win_lines_n"] == 3 and not ok("win_verified == 1", w)
              and not ok(rule("freeze_fence_restore"), dict(w, n_judge_stall_helper=3)),
              "ctrlsum: a window line without unreadable=: incomplete, the window rules fail (%r %r %r)" % (
                  w["win_verified"], w["win_missing"], w["win_changed_after"]))
    finally:
        for R in tops:
            shutil.rmtree(R, ignore_errors=True)


def gap_checks():
    """EXPERIMENT 8 (2026-10-23, DRAFT): a scored trial whose rule reads an empty required summary column is 자료 부족 for
    that prediction (neither a pass nor a fail); the verdict is judged over the trials with data against the k; fewer than
    k with data is 자료 부족(n<k); a safety rule keeps its 0-failure rule over the trials with data, with the gap listed"""
    import io, contextlib, csv as _csv
    dg = score_gc.data_gaps
    # unit: a presence test, an event column and a summary column without its gap marker are measurements, not gaps
    r0 = dict(id="u", stem="u", rec_lost_n="", ow_data_equal=1, kill_judge_ms_min="", ctrlsum_missing="r1",
              ctrlsum_fields_missing="")
    g0 = dg("rec_lost_n == 0 and ow_data_equal == 1", [r0])
    check(sorted(g0) == ["u"] and g0["u"][:2] == (["rec_lost_n"], "ctrlsum_missing=r1")
          and dg("rec_lost_n == 0 and ow_data_equal == 0", [r0]) == {} and dg("nonempty(rec_lost_n)", [r0]) == {}
          and dg("kill_judge_ms_min <= 5", [r0]) == {} and dg("rec_lost_n == 0", [dict(r0, ctrlsum_missing="")]) == {},
          "gap: an empty required column with its marker is a gap; a measured false term beside it, nonempty(), an event "
          "column and a column without a marker are not (%r)" % g0)
    tops = []
    try:
        def five(R, gaps=(), bad=()):
            """five gc4_credit_stall@gc trials (ctrlsum_checks' form); rank 1's control summary removed in the trials gaps,
            rank 0's data mismatch (x_match 0) in the trials bad"""
            for k in range(1, 6):
                st = trial(os.path.join(R, "raw"), "gc4_credit_stall", k, kill=None, subject=2, inject="none", killed=False,
                           probe=probe_ok(), spare_kv=REAL_SPARE_KV, ctrl_kv=" sendq_deferred=4",
                           meta_extra={"r2_env": "NCCL_GIN_CTRL_TEST_CREDIT_STALL=3000:500"},
                           kv_extra={0: {"x_match": 0}} if k in bad else None,
                           lines={2: [(3.0, "GIN/RC: rank 2: test switch CREDIT_STALL: no RECV re-posted for 500 ms")]})
                if k in gaps:
                    t = open(st + "_r1.log").read()
                    with open(st + "_r1.log", "w") as f:
                        f.write("\n".join(x for x in t.split("\n") if "control summary" not in x))
        tmp = tempfile.mkdtemp(prefix="gc_selftest_gap_preds_")
        tops.append(tmp)
        pf = os.path.join(tmp, "preds.csv")
        cond = "rec_lost_n == 0 and ow_data_equal == 1"
        with open(pf, "w", newline="", encoding="utf-8") as f:
            w = _csv.DictWriter(f, fieldnames=["id", "predicted", "cells", "kind", "acceptance", "todo"], quoting=_csv.QUOTE_ALL)
            w.writeheader()
            for pid, kd, acc in (("g_perf4", "perf", "count(%s) >= 4" % cond), ("g_perf5", "perf", "count(%s) >= 5" % cond),
                                 ("g_safe4", "safety", "count(%s) >= 4" % cond),
                                 ("g_safe_all", "safety", "count(rec_lost_n == 0) >= N_SCORED")):
                w.writerow(dict(id=pid, predicted="t", cells="gc4_credit_stall@gc", kind=kd, acceptance=acc, todo=""))
        res = {}
        for tag, gaps, bad in (("one", (1,), ()), ("two", (1, 2), ()), ("bad", (1,), (1,))):
            R = tempfile.mkdtemp(prefix="gc_selftest_gap_")
            tops.append(R)
            five(R, gaps, bad)
            old, score_gc.PREDS = score_gc.PREDS, pf
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    verd, _ = score_gc.score(R)
            finally:
                score_gc.PREDS = old
            res[tag] = (verd, open(os.path.join(R, "SCORE.md"), encoding="utf-8").read(), buf.getvalue())
        v, md, out = res["one"]
        check(v.get("g_perf4") == "맞음" and v.get("g_safe4") == "맞음" and v.get("g_safe_all") == "맞음"
              and v.get("g_perf5") == "자료 부족(n<k)",
              "gap: one trial without rank 1's summary: perf k 4 맞음 over the other four, perf k 5 자료 부족(n<k), safety k 4 "
              "and N_SCORED 맞음 (%s %s %s %s)" % (v.get("g_perf4"), v.get("g_perf5"), v.get("g_safe4"), v.get("g_safe_all")))
        check("채점 n 5, 자료 부족 n 1, 자료 있는 n 4, 문턱 k 4" in md and "채점 n 5, 자료 부족 n 1, 자료 있는 n 4, 문턱 k 5 → 자료 부족(n<k)" in md
              and "자료 부족 시행(빈 필수 열; 통과도 실패도 아님, 8절): `gc4_credit_stall_gc_n1` (rec_lost_n; ctrlsum_missing=r1)" in md
              and "| 5 (자료 부족 1) | 맞음 |" in md and "scored=5 cond=4/4 whole=4/5 data_gap=1" in out
              and "`count(%s)` = 4/4. 만족하지 않은 시행: 없음" % cond in md
              and "`rec_lost_n == 0`: 실패 0/4, 자료 부족 1 (gc4_credit_stall_gc_n1)" in md,
              "gap: SCORE.md gives the scored n, the gap n, the trial and its column, the verdict over the trials with data")
        v, md, _ = res["two"]
        check(v.get("g_perf4") == "자료 부족(n<k)" and v.get("g_safe4") == "자료 부족(n<k)" and v.get("g_safe_all") == "맞음",
              "gap: two trials without the summary: three with data against k 4 is 자료 부족(n<k), never 맞음 by the smaller "
              "denominator (%s %s %s)" % (v.get("g_perf4"), v.get("g_safe4"), v.get("g_safe_all")))
        v, md, _ = res["bad"]
        check(v.get("g_safe4") == "틀림" and v.get("g_perf4") == "재검토(안전성 항 어긋남 1/5)" and v.get("g_safe_all") == "맞음",
              "gap: the gap trial with a measured data mismatch is a fail, not 자료 부족: safety 틀림, perf 재검토; the rule "
              "on the empty column alone stays a gap (%s %s %s)" % (v.get("g_safe4"), v.get("g_perf4"), v.get("g_safe_all")))
    finally:
        for R in tops:
            shutil.rmtree(R, ignore_errors=True)


def probe_checks():
    """Codex finding 1 (2026-10-23): read_success_pct counts the device-line READs too, every process of the final generation
    must leave one probe summary per peer, and a summary whose peer named a device line its dev_* counters; a gap is
    자료 부족 (every trial) or no pass (one trial), never 맞음 by a 0 or a ratio that was not read"""
    import io, contextlib
    tops = []
    pause = lambda us: {r: [(1.0, "GIN/RS: rank %d: input pause for rank 0's checkpoint 20 ended (ok) pause_us=%d" % (r, us))]
                        for r in range(N)}

    def none_cells(R, kw_of):
        """gc4_none_probe@gc x 10 and gc4_none_ow@gc x 5, device line on; kw_of(cell, k) -> probe_ok's arguments"""
        raw = os.path.join(R, "raw")
        for cell, n, us in (("gc4_none_probe", 10, 2300), ("gc4_none_ow", 5, 8100)):
            for k in range(1, n + 1):
                trial(raw, cell, k, kill=None, subject=None, inject="none", spare=False, killed=False, lines=pause(us),
                      probe=probe_ok(**dict(dict(dev=True), **kw_of(cell, k))))

    try:
        res = {}
        one = lambda cell, k: cell == "gc4_none_probe" and k == 1
        for tag, kw_of in (("clean", lambda c, k: {}),
                           ("devfail", lambda c, k: {"dev_fail": (0, 1)} if one(c, k) else {}),
                           ("nosum", lambda c, k: {"drop": (1, 2)}),
                           ("nosum1", lambda c, k: {"drop": (1, 2)} if one(c, k) else {}),
                           ("nodevok", lambda c, k: {"no_dev_ok": True})):
            R = tempfile.mkdtemp(prefix="gc_selftest_probe_")
            tops.append(R)
            none_cells(R, kw_of)
            rows = {r["id"]: r for r in rows_gc.all_rows(R)}
            with contextlib.redirect_stdout(io.StringIO()):
                verd, _ = score_gc.score(R)
            res[tag] = (rows["gc4_none_probe_gc_n1"], rows["gc4_none_probe_gc_n2"], verd.get("none_probe_clean"))
        c1, _, vc = res["clean"]
        check(c1["read_n"] == 3600 and c1["dev_read_n"] == 3588 and c1["dev_read_ok_n"] == 3588 and c1["read_success_pct"] == 100.0
              and c1["probe_missing"] == "" and vc == "맞음",
              "probe: clean, device line on: page 3600 + device 3588 READs, 100 %%, none_probe_clean 맞음 (%r %r %r %s)" % (
                  c1["read_n"], c1["dev_read_n"], c1["read_success_pct"], vc))
        d1, d2, vd = res["devfail"]
        check(d1["read_page_success_pct"] == 100.0 and d1["read_dev_success_pct"] < 100.0 and d1["read_success_pct"] < 100.0
              and d2["read_success_pct"] == 100.0 and vd == "틀림",
              "probe: one device READ failure in one trial: page 100 %% (the old formula), total %r, none_probe_clean 틀림 (%s)" % (
                  d1["read_success_pct"], vd))
        m1, _, vm = res["nosum"]
        check(m1["probe_missing"] == "r1:p2" and all(m1[c] == "" for c in ("read_n", "dev_read_n", "read_success_pct",
                                                                             "read_page_success_pct", "page_torn_n"))
              and vm == "자료 부족",
              "probe: rank 1's summary for peer 2 missing in every trial: every count empty, 자료 부족 (%r %s)" % (
                  m1["probe_missing"], vm))
        o1, o2, vo = res["nosum1"]
        check(o1["probe_missing"] == "r1:p2" and o1["read_success_pct"] == "" and o2["read_success_pct"] == 100.0
              and vo == "자료 부족(n<k)",
              "probe: the same gap in one trial: that trial's rate empty, the trial 자료 부족 (8절, 2026-10-23), 9 with data "
              "against k 10: 자료 부족(n<k) (%s)" % vo)
        n1, _, vn = res["nodevok"]
        check("r0:p1:dev_ok" in n1["probe_missing"] and "dev_reads" not in n1["probe_missing"] and n1["dev_read_ok_n"] == ""
              and n1["read_dev_success_pct"] == "" and n1["read_success_pct"] == "" and n1["read_n"] == 3600 and vn == "자료 부족",
              "probe: dev_ok= removed while the device line is on: the device side and the total empty, the page side kept, "
              "자료 부족 (%r %s)" % (n1["probe_missing"][:40], vn))
        # the active spare's summaries are required; an old-format summary whose peer's page named a device line lacks
        # dev_*; two contexts need dev_ok_ctx= of two values
        R = tempfile.mkdtemp(prefix="gc_selftest_probe_")
        tops.append(R)
        raw = os.path.join(R, "raw")
        st = trial(raw, "gc4_kill3_ow", 1, lines=restore_lines(3, 2.0306, "FIN+NORESP"), probe=probe_ok(dev=True))
        t = open(st + "_spare.log").read()
        with open(st + "_spare.log", "w") as f:
            f.write("\n".join(x for x in t.split("\n") if "probe summary" not in x))
        named = {r: [(0.55, "GIN/RC: rank %d: status page up (320 B in use, probe_ms=100 stall_ms=10000 W=20, device line named "
                            "1184 B)" % r)] for r in range(N)}
        trial(raw, "gc4_none_ow", 1, kill=None, subject=None, inject="none", spare=False, killed=False, lines=named, probe=probe_ok())
        two = lambda r: [x.replace("dev_ctx=1 dev_reads_ctx=299 dev_ok_ctx=299", "dev_ctx=2 dev_reads_ctx=150/149 dev_ok_ctx=299")
                         for x in probe_ok(dev=True)(r)]
        trial(raw, "gc4_none_ow", 2, kill=None, subject=None, inject="none", spare=False, killed=False, probe=two)
        rows = {r["id"]: r for r in rows_gc.all_rows(R)}
        a, b, c = rows["gc4_kill3_ow_gc_n1"], rows["gc4_none_ow_gc_n1"], rows["gc4_none_ow_gc_n2"]
        check(a["probe_missing"] == "spare:p0+spare:p1+spare:p2" and a["read_success_pct"] == "",
              "probe: the active spare without its summaries: named, the rate empty (%r)" % a["probe_missing"])
        check("r0:p1:dev_reads" in b["probe_missing"] and "r0:p1:dev_ok" in b["probe_missing"] and b["read_n"] == 3600
              and b["read_success_pct"] == "",
              "probe: the peer's page named a device line, the summary has no dev_*: a gap (%r)" % b["probe_missing"][:40])
        check(c["probe_missing"].split("+")[0] == "r0:p1:dev_ok_ctx" and "dev_reads_ctx" not in c["probe_missing"]
              and c["read_success_pct"] == "",
              "probe: dev_ctx=2 with a one-value dev_ok_ctx: a gap (%r)" % c["probe_missing"][:40])
    finally:
        for R in tops:
            shutil.rmtree(R, ignore_errors=True)


def cost_trial(d, arm, k, *, lib="gcp", sums=None, kv_extra=None, page_ms=900.0):
    """one run_cost_gc.sh trial (lat4k, receiving node rain; plain logs without receipt stamps): each rank's status page
    line (mono page_ms, probe_ms 100) and, unless sums says otherwise, its summary for the peer (mono 4100): 32 page
    READs and 32 device READs (one context), the full cadence over the 3 200 ms span; the kv's measurement window
    launch_mono_ms 1000, kernel_ms 3000. sums: {rank: None (no summary) | {field: value} (changes)}"""
    os.makedirs(d, exist_ok=True)
    cell = "cost_lat4k_%s_rain" % arm
    stem = os.path.join(d, "%s_k%d" % (cell, k))
    with open(stem + "_meta.txt", "w") as f:
        f.write(kvline(dict(cell=cell, tag="k%d" % k, metric="lat4k", arm=arm, rx="rain", tx="sunny", mode="lat", iters=3000,
                            bytes=4096, lib=lib, launcher_ready=1, runner="costgc", bin="gin_ts2_mi")))
    on = arm == "probe-on"
    for r in (0, 1):
        kv = dict(rank=r, exit=0, win_flags="0x3", launch_mono_ms=1000.0, kernel_ms=3000.0)
        if r == 0:
            kv.update(lat_p50_us=10.5, tx_done=3000)
        kv.update((kv_extra or {}).get(r, {}))
        with open("%s_r%d.kv" % (stem, r), "w") as f:
            f.write(kvline({x: v for x, v in kv.items() if v is not None}))
        L = ["[t] host:1:1 [0] gin_host_gdaki.cc:1 (gdakiPageSetup) NCCL WARN GIN/RC: rank %d: status page up (320 B in use, "
             "probe_ms=%d stall_ms=10000 W=20, device line named 1184 B, contexts=1 page_read=320 B) mono_ms=%.3f" % (r, 100 if on else 0, page_ms)]
        s = dict(reads=32 if on else 0, ok=32 if on else 0, after_end_reads=0, after_end_ok=0, dev_line=1,
                 dev_reads=32 if on else 0, dev_ok=32 if on else 0, dev_ctx=1, dev_reads_ctx=32 if on else 0,
                 dev_ok_ctx=32 if on else 0, mono_ms="4100.000")
        sx = (sums or {}).get(r, {})
        if sx is not None:
            s.update(sx)
            L.append("[t] host:1:1 [0] gin_host_gdaki.cc:2 (gdakiCtrlProbeSummary) NCCL WARN GIN/RC: rank %d: probe summary "
                     "peer=%d %s" % (r, 1 - r, " ".join("%s=%s" % kv for kv in s.items() if kv[1] is not None)))
        with open("%s_r%d.log" % (stem, r), "w") as f:
            f.write("\n".join(L) + "\n")
    return stem


def cost_checks():
    """Codex finding 2 (2026-10-23): a probe-on cost trial needs the probe's READs in its own logs (a summary per rank with
    page and device READs > 0, overlapping the measurement window), a probe-off trial none; otherwise cost_valid 0 and the
    scorer's cost_invalid"""
    import io, contextlib
    R = tempfile.mkdtemp(prefix="gc_selftest_cost_")
    try:
        d = os.path.join(R, "cost")
        two = {"dev_ctx": 2, "dev_reads": 64, "dev_ok": 64, "dev_reads_ctx": "32/32", "dev_ok_ctx": "32/32"}
        low = {"reads": 10, "ok": 10, "dev_ctx": 2, "dev_reads": 20, "dev_ok": 20, "dev_reads_ctx": "10/10", "dev_ok_ctx": "10/10"}
        cases = [("on_good", "probe-on", {}, None, 900.0, 1), ("on_nosum", "probe-on", {1: None}, None, 900.0, 0),
                 ("on_reads0", "probe-on", {0: {"reads": 0, "ok": 0}}, None, 900.0, 0),
                 ("on_dev0", "probe-on", {1: {"dev_reads": 0, "dev_ok": 0, "dev_reads_ctx": 0, "dev_ok_ctx": 0}}, None, 900.0, 0),
                 ("on_ctx0", "probe-on", {0: {"dev_ctx": 2, "dev_reads_ctx": "32/0", "dev_ok_ctx": "32/0"}}, None, 900.0, 0),
                 ("on_before", "probe-on", {0: {"mono_ms": "950.000"}, 1: {"mono_ms": "950.000"}}, None, 100.0, 0),
                 ("on_notime", "probe-on", {}, {0: {"launch_mono_ms": None}, 1: {"launch_mono_ms": None}}, 900.0, 0),
                 ("on_nokernel", "probe-on", {}, {0: {"kernel_ms": None}}, 900.0, 0),
                 ("on_after", "probe-on", {0: {"mono_ms": "4800.000"}, 1: {"mono_ms": "4800.000"}}, None, 4050.0, 0),
                 ("on_ctx2_full", "probe-on", {0: two, 1: two}, None, 900.0, 1),
                 ("on_low", "probe-on", {0: low, 1: low}, None, 900.0, 0),
                 ("off_none", "probe-off", {0: None, 1: None}, None, 900.0, 1), ("off_zero", "probe-off", {}, None, 900.0, 1),
                 ("off_reads", "probe-off", {1: {"reads": 15, "ok": 15}}, None, 900.0, 0)]
        for k, (_, arm, sm, kx, pg, _) in enumerate(cases, 1):
            cost_trial(d, arm, k, sums=sm, kv_extra=kx, page_ms=pg)
        cost_trial(d, "tcp", 99, lib="gctp", sums={0: None, 1: None})
        rows = {r["id"]: r for r in rows_gc.all_rows(R)}
        with contextlib.redirect_stdout(io.StringIO()):
            _, srows = score_gc.score(R)
        stt = {r["id"]: r["status"] for r in srows}
        for k, (tag, arm, _, _, _, want) in enumerate(cases, 1):
            rid = "cost_lat4k_%s_rain_k%d" % (arm, k)
            r = rows[rid]
            check(r["cost_valid"] == want and (r["cost_probe_evidence"] == "ok") == (want == 1)
                  and (stt[rid] == "cost_invalid") == (want == 0),
                  "cost: %s: cost_valid %r (want %d), %r, status %s" % (tag, r["cost_valid"], want, r["cost_probe_evidence"],
                                                                       stt[rid]))
        on = lambda i: rows["cost_lat4k_probe-on_rain_k%d" % i]
        g, f2, lo = on(1), on(10), on(11)
        check(g["cost_probe_window"] == "r0:covers+r1:covers" and g["cost_probe_inwindow_lb"] == "r0:56+r1:56"
              and g["cost_probe_expected"] == "r0:30+r1:30" and f2["cost_probe_inwindow_lb"] == "r0:84+r1:84"
              and f2["cost_probe_expected"] == "r0:45+r1:45",
              "cost: the in-window bound, one and two contexts (%r %r; %r %r)" % (
                  g["cost_probe_inwindow_lb"], g["cost_probe_expected"], f2["cost_probe_inwindow_lb"], f2["cost_probe_expected"]))
        check("r0:p1:no_overlap" in on(6)["cost_probe_evidence"] and "r1:p0:no_overlap" in on(9)["cost_probe_evidence"]
              and on(7)["cost_probe_window"] == "r0:no_time+r1:no_time" and "r0:p1:no_time" in on(8)["cost_probe_evidence"]
              and "r1:p0:no_time" not in on(8)["cost_probe_evidence"]
              and lo["cost_probe_window"] == "r0:reads_outside_window+r1:reads_outside_window" and lo["cost_probe_inwindow_lb"] == "r0:18+r1:18",
              "cost: before, after, no time, no kernel_ms, below the cadence (%r %r %r)" % (
                  on(6)["cost_probe_evidence"][:30], on(8)["cost_probe_evidence"][:30], lo["cost_probe_inwindow_lb"]))
        tc = rows["cost_lat4k_tcp_rain_k99"]
        check(tc["cost_probe_evidence"] == "" and tc["cost_valid"] == 1, "cost: the tcp arm is not checked (%r %r)" % (
            tc["cost_probe_evidence"], tc["cost_valid"]))
    finally:
        shutil.rmtree(R, ignore_errors=True)


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
    check(A["tcp_ctrl_bytes"] == 0 and A["tcp_ctrl_conn_n"] == A["witness_pairs"] == A["witness_expected"] == A["ring_live_pairs"] == 6
          and A["active_mtu_kv_min"] == 4096 and A["ring_live_all"] == 1,
          "B3: no tcp control bytes, the witness opened on every live pair of the final generation (%r %r)" % (A["tcp_ctrl_conn_n"], A["witness_expected"]))
    check(A["ss_tcp_conn_n"] == 20 and A["ss_pids_both"] == 4 and A["ss_tx_delta_bytes"] == 0, "fix 10: the ss snapshots read")
    check(A["fenced"] == 1 and A["fence_order_ok"] == 1 and A["fence_names_ok"] == 0, "A: FENCED (by EXITED) before the activation, no FENCE sent")
    check(A["la_exited_n"] == 1 and A["la_stop_n"] == 0 and A["launcher_same"] == 1, "fix 6: the earlier trial's EXITED before trial_start not counted (%r)" % A["la_exited_n"])
    check(A["hold_after_restore_n"] == 0, "fix 9: no hold after the restore")
    B = rows["gc4_fdhold_sock_kill3_gc_n1"]
    check(B["n_judge_exited"] == 3 and abs(B["kill_judge_exited_min_ms"] - 120.0) < 0.01 and abs(B["kill_judge_ms_max"] - 120.0) < 0.01, "B: EXITED 120 ms after the kill")
    check(B["inject_ok"] == 1 and abs(B["inject_off_ms"] - 4.0) < 0.01, "B: the fd-holder injection record (receipt 4 ms after the plan)")
    C = rows["gc4_kill3_noreport_nofdhold_gc_n1"]
    check(C["n_judge_noresp"] == 3 and abs(C["kill_judge_ms_min"] - 3900.0) < 0.01, "C: NORESP 3.9 s after the kill (%r)" % C["kill_judge_ms_min"])
    check(C["probe_fail_n"] == 3, "C: one READ failure line per survivor before its judgement (%r)" % C["probe_fail_n"])
    C2 = rows["gc4_fdhold_sock_kill3_noreport_gc_n1"]
    hs = rule("fdhold_sock_helper_stall")
    check(C2["n_judge_stall_helper"] == 3 and C2["n_judge_noresp"] == 0 and abs(C2["kill_judge_ms_min"] - 10070.0) < 0.01
          and C2["probe_fail_n"] == 0 and C2["fence_names_ok"] == 1 and C2["fence_order_ok"] == 1 and C2["la_exit_silent_n"] == 1,
          "C2: STALL_HELPER kill + 10.07 s, the READ failure line after the judgement not counted (%r %r)" % (
              C2["kill_judge_ms_min"], C2["probe_fail_n"]))
    check(score_gc.s2.cond_true(hs, C2) and not score_gc.s2.cond_true(hs, dict(C2, probe_fail_n=1))
          and not score_gc.s2.cond_true(hs, C) and not score_gc.s2.cond_true(hs, dict(C2, kill_judge_ms_max=10600.0)),
          "C2: fdhold_sock_helper_stall holds on C2, not with a READ failure line before the judgement, not on C, not at 10.6 s")
    check(C["fence_names_ok"] == 1 and C["fence_order_ok"] == 1 and abs(C["fence_sent_to_fenced_ms"] - 2.0) < 0.01, "C: FENCING -> FENCED -> activation")
    check(C["timeout_judge_n"] == 0 and C["probe_timeout_n"] == 3 and C["la_exit_silent_n"] == 1 and C["la_fenced_n"] == 1
          and C["witness_pairs"] == 0 and C["witness_expected"] == 0, "C: time-out lines before the judgement, the silent exit, witness off")
    D = rows["gc4_stop12000_fence_gc_n1"]
    check(D["la_stop_n"] == 1 and D["la_refused_signal_n"] == 1, "D: the STOP_launcher line counted")
    check(D["n_judge_stall_helper"] == 3 and D["n_judge_stall"] == 0 and abs(D["stop_judge_ms_min"] - 10050.0) < 0.01 and abs(D["hold_ms_max"] - 1400.0) < 0.01, "D: stall judgement 10 050 ms after STOP, hold 1.4 s (%r %r)" % (D["stop_judge_ms_min"], D["hold_ms_max"]))
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
    check(F["subject"] == "3" and F["n_judge"] == 3 and F["n_judge_stall_helper"] == 3 and F["n_judge_stall"] == 0 and abs(F["stop_judge_ms_min"] - 10100.0) < 0.01
          and F["la_fence_sigkill_n"] == 1 and F["la_fenced_n"] == 1 and F["inject_ok"] == 1 and F["ckpt_stable_before_inj"] == 1
          and F["subject_fenced"] == 1 and F["ow_data_equal"] == 1,
          "B2: the freeze cell judged on its subject (%r %r %r)" % (F["subject"], F["n_judge"], F["stop_judge_ms_min"]))
    G3 = rows["gct4_rstgap_live300_gctc_n1"]
    check(G3["subject"] == "1" and G3["n_judge"] == 3 and G3["n_rst_surv"] == 3 and abs(G3["rst_judge_ms_min"] - 103.0) < 0.01,
          "B2: the live RST cell judged on rank 1, RST -> judgement 103 ms (%r %r)" % (G3["n_judge"], G3["rst_judge_ms_min"]))
    revision_checks(A, B, F)
    # B5: the GPU-hang cell judged STALL on its subject; the rule takes STALL only
    H5 = rows["gc4_gpuhang12000_fence_gc_n1"]
    check(H5["subject"] == "3" and H5["n_judge"] == 3 and H5["n_judge_stall"] == 3 and H5["n_judge_stall_helper"] == 0
          and abs(H5["stop_judge_ms_min"] - 10100.0) < 0.01 and H5["inject_ok"] == 1 and H5["ckpt_stable_before_inj"] == 1
          and H5["la_fence_sigkill_n"] == 1 and H5["la_fenced_n"] == 1 and H5["fence_order_ok"] == 1 and H5["subject_fenced"] == 1
          and H5["ow_data_equal"] == 1,
          "B5: the GPU-hang cell judged STALL 10 100 ms after the hang line (%r %r %r %r)" % (
              H5["n_judge_stall"], H5["stop_judge_ms_min"], H5["inject_ok"], H5["fence_order_ok"]))
    gh = rule("gpuhang_fence_restore")
    ok5 = score_gc.s2.cond_true
    check(ok5(gh, H5) and not ok5(gh, dict(H5, n_judge_stall=0, n_judge_stall_helper=3))
          and not ok5(gh, dict(H5, stop_judge_ms_max=10600.0)),
          "B5: gpuhang_fence_restore takes STALL in 10 000-10 500 ms; a STALL_HELPER copy and 10 600 ms fail")
    # B6: the counterexample cell: STALL naming context 1 (on the judgement, or on the suspect line before it)
    H6, H6b = rows["gc4_gpuhang12000_ctx1_fence_gc_n1"], rows["gc4_gpuhang12000_ctx1_fence_gc_n2"]
    check(H6["n_judge_stall"] == 3 and H6["stall_ctx"] == "1" and H6b["stall_ctx"] == "1" and H6["inject_ok"] == 1
          and abs(H6["stop_judge_ms_min"] - 10100.0) < 0.01 and H6["fence_order_ok"] == 1 and H6["ow_data_equal"] == 1,
          "B6: ctx=1 read from the STALLED line and from the suspect line (%r %r %r %r)" % (
              H6["stall_ctx"], H6b["stall_ctx"], H6["inject_ok"], H6["stop_judge_ms_min"]))
    check(H5["stall_ctx"] == "none", "B6: the GPU hang cell's STALL lines name no context: stall_ctx none (%r)" % H5["stall_ctx"])
    g6 = rule("gpuhang_ctx1_fence_restore")
    check(ok5(g6, H6) and ok5(g6, H6b) and not any(ok5(g6, dict(H6, stall_ctx=v)) for v in ("1+none", "0+1", "", "0", "none"))
          and not ok5(g6, dict(H6, n_judge_stall=0, n_judge_stall_helper=3)) and not ok5(g6, dict(H6, stop_judge_ms_min=9900.0)),
          "B6: gpuhang_ctx1_fence_restore takes STALL with stall_ctx 1 only")
    neg6 = tempfile.mkdtemp(prefix="gc_selftest_ctx_")
    try:
        nraw = os.path.join(neg6, "raw")
        gpu_ctx1_trial(nraw, 6, ctxs=(1, 0, 1))
        gpu_ctx1_trial(nraw, 7, ctxs=(1, None, 1))
        gpu_ctx1_trial(nraw, 8, hang_ctx="all")
        nr = {r["id"]: r for r in rows_gc.all_rows(neg6) if r["sub"] == "raw"}
        n6, n7, n8 = (nr.get("gc4_gpuhang12000_ctx1_fence_gc_n%d" % i, {}) for i in (6, 7, 8))
        check(n6.get("stall_ctx") == "0+1" and n7.get("stall_ctx") == "1+none" and not ok5(g6, n6) and not ok5(g6, n7),
              "B6: a survivor naming context 0, or none, fails the rule (%r %r)" % (n6.get("stall_ctx"), n7.get("stall_ctx")))
        check(n8.get("inject_ok") == 0 and n6.get("inject_ok") == 1,
              "B6: the hang line must name the cell's context: ctx=all is no injection record there (%r)" % n8.get("inject_ok"))
    finally:
        shutil.rmtree(neg6, ignore_errors=True)
    # B4: rows_gc.py --stops (the hold's per-trial check) on both forms and on the QP loss
    def stops(stem):
        return subprocess.run([sys.executable, os.path.join(HERE, "rows_gc.py"), "--stops", os.path.join(R, "raw", stem)],
                              stdout=subprocess.PIPE).stdout.decode().strip()
    s16, sD, s17, sA = stops("gc4_kill3_ow_gc_n16"), stops("gc4_stop12000_fence_gc_n1"), stops("gc4_kill3_ow_gc_n17"), stops("gc4_kill3_ow_gc_n1")
    check("la_stop_n=1 " in s16 + " " and "la_pid_mismatch_n=1" in s16, "B4: '(STOP_launcher: ...)' in the gap before trial_start counted (%s)" % s16)
    check("la_stop_n=1 " in sD + " ", "B4: '(STOP_launcher)' counted (%s)" % sD)
    check("la_qp_err_n=1" in s17 and "la_stop_n=0" in s17, "B4: the launcher QP loss of rank 1 before 'is leaving' counted (%s)" % s17)
    check("la_stop_n=0 la_qp_err_n=0" in sA, "B4: a clean trial (%s)" % sA)
    # I: the daemon's warm spare, the expected cap line, the stale socket
    I18, I19 = rows["gc4_kill3_ow_gc_n18"], rows["gc4_kill3_ow_gc_n19"]
    check(I18["spare2_inc_want"] == 2 and I18["spare2_inc_got"] == 2 and I18["spare2_daemon_ok"] == 1 and
          I18["la_spare_spawn_n"] == 2 and I18["spare_hello_after_ms"] == 310.5 and I18["la_stop_n"] == 0,
          "I: the same rank's second restore by the daemon's next spare, incarnation 2 (%r %r %r %r)" % (
              I18["spare2_inc_want"], I18["spare2_inc_got"], I18["spare2_daemon_ok"], I18["la_spare_spawn_n"]))
    check(I19["spare2_daemon_ok"] == 0 and I19["spare2_inc_got"] == 1, "I: no incarnation 2 spawned: not ok (%r %r)" % (
        I19["spare2_daemon_ok"], I19["spare2_inc_got"]))
    M0 = rows["mi4_kill2_kill3_ow_gc_n1"]
    check(M0["spare2_inc_want"] == 1 and M0["spare2_daemon_ok"] == 1, "I: another rank's second spare is its node's own warm spare (%r %r)" % (
        M0["spare2_inc_want"], M0["spare2_daemon_ok"]))
    SA = rows["gc4_kill3_ow_spareabsent_gc_n1"]
    sSA, s20 = stops("gc4_kill3_ow_spareabsent_gc_n1"), stops("gc4_kill3_ow_gc_n20")
    check(SA["la_stop_n"] == 0 and SA["la_spare_cap_expected_n"] == 1 and "la_stop_n=0 " in sSA,
          "I: the spare-absent cell's one cap line is expected, not a STOP (%r, %s)" % (SA["la_stop_n"], sSA))
    check("la_not_up=1 la_stale_n=1" in s20 and rows["gc4_kill3_ow_gc_n20"]["launcher_stale"] == "sunny:1+0",
          "I: the stale socket trial's --stops (%s)" % s20)
    neg = tempfile.mkdtemp(prefix="gc_selftest_neg_")
    try:  # the same cap line in a cell that does not expect it is a STOP
        trial(neg, "gc4_kill3_ow", 21, lines=restore_lines(3, 2.0306, "FIN+NORESP"), probe=probe_ok(),
              la={"sunny": [(2.001, CAP0 % (1, 1, 1301))]})
        sN = subprocess.run([sys.executable, os.path.join(HERE, "rows_gc.py"), "--stops", os.path.join(neg, "gc4_kill3_ow_gc_n21")],
                            stdout=subprocess.PIPE).stdout.decode().strip()
        check("la_stop_n=1 " in sN + " ", "I: the cap line outside the spare-absent cells is a STOP (%s)" % sN)
    finally:
        shutil.rmtree(neg, ignore_errors=True)
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
    check(st["gc4_kill3_ow_gc_n20"] == "launcher_stale" and st["gc4_kill3_ow_gc_n19"] == "spare_start_fail"
          and st["gc4_kill3_ow_gc_n18"] == "surplus",
          "I: stale socket excluded, a second death without the daemon's spare excluded, with it counted (%s, %s, %s)" % (
              st["gc4_kill3_ow_gc_n20"], st["gc4_kill3_ow_gc_n19"], st["gc4_kill3_ow_gc_n18"]))
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
                      ("fdhold_sock_helper_stall", "맞음"),
                      ("none_probe_clean", "맞음"), ("gate_fenced", "자료 부족"), ("no_tcp_control", "맞음"),
                      ("long_hold_lane", "맞음"), ("stall_fence_restore", "자료 부족"), ("restore_time_rdma", "자료 부족"),
                      ("regression_tcp", "자료 부족"), ("cost_probe_lat4k", "자료 부족"), ("freeze_fence_restore", "맞음"),
                      ("gpuhang_fence_restore", "맞음"), ("gpuhang_ctx1_fence_restore", "맞음")):
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
    check("한도 줄(실행기가 끝낸 예비 프로세스를 launcher가 다시 띄우지 않음; STOP으로 세지 않음): 1줄" in md and
          "gc4_kill3_ow_gc_n20(낡은 소켓이나 프로세스 sunny:1+0)" in md, "SCORE.md lists the expected cap line and the stale trial")
    check(os.path.exists(os.path.join(R, "trials_scored.csv")), "trials_scored.csv written")
    shell_checks(R)
    int3_checks()
    review_checks()
    ctrlsum_checks()
    gap_checks()
    probe_checks()
    cost_checks()
    print("self-test: %d checks, %d failed%s" % (CHECKS[0], CHECKS[1], "" if a.keep else " (folder %s removed)" % R))
    if not a.keep:
        shutil.rmtree(R, ignore_errors=True)
    sys.exit(1 if CHECKS[1] else 0)


if __name__ == "__main__":
    main()
