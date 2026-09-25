#!/usr/bin/env python3
"""run_tests.py - Stage 2 validation on 2 nodes (design §11). Orchestration only; the mechanism
under test is inside libnccl (stage2 build). Run under ../../gpu-initiated/common/cluster_run.sh.

usage: run_tests.py --out DIR [--tests T1 T2 ...] [--n N] [--build stage2]
Verdict per run:
  RECOVERED   both ranks rc 0, every iteration bit-exact (nccl_ct checks the whole buffer), and at
              least one "[FAULT-RECOVERY2] send comm: recovered" line (count = rounds).
  CLEAN_FAIL  both ranks surfaced an NCCL error (rc 2/3/7 or killed after it), no mismatch/timeout.
  PASS        (no-fault cases) both rc 0, no recovery lines.
  FAIL        anything else (mismatch, timeout, hang, a recovery that did not complete, ...).
"""
import argparse, csv, os, subprocess, sys, threading, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "perf"))
import ctlib as C

FR = {"NCCL_RDMA_FAULT_RECOVERY": "1", "NCCL_IB_TIMEOUT": "14"}
DEFAULT = {}
COUNT_SINGLE, COUNT_DEFAULT = 65536, 4194304      # 256 KB, 16 MB


def classify(res, expect):
    rc0, rc1 = res["rc0"], res["rc1"]
    lines = [l for _, l in res["lines0"]] + [l for _, l in res["lines1"]]
    mism = sum("MISMATCH" in l for l in lines)
    tmo = sum("TIMEOUT after" in l for l in lines) or res.get("timed_out")
    rec = sum("[FAULT-RECOVERY2] send comm: recovered" in l for l in lines)
    rrec = sum("[FAULT-RECOVERY2] recv comm: recovered" in l for l in lines)
    failed = sum("comm FAILED" in l for l in lines)
    inj = sum("[FAULT-INJECT]" in l for l in lines)
    s0, s1 = res["s0"] or {}, res["s1"] or {}
    if mism or tmo:
        v = "FAIL"
    elif rc0 == 0 and rc1 == 0:
        if expect == "pass":
            v = "PASS" if rec == 0 and failed == 0 else "FAIL(unexpected recovery)"
        else:
            if rec > 0 and failed == 0:
                v = "RECOVERED"
            elif expect == "recover-gbh" and rec == 0 and failed == 0:
                v = "MASKED"            # the NIC's own retransmission hid the outage
            else:
                v = "PASS(no fault fired)" if inj == 0 else "FAIL(no recovery line)"
    elif rc0 in (2, 3, 7, -9, 137, 255) and rc1 in (2, 3, 7, -9, 137, 255) and mism == 0:   # 137/255: the rank the test killed
        v = "CLEAN_FAIL"
    else:
        v = f"FAIL(rc {rc0}/{rc1})"
    return v, dict(mismatch=mism, timeout=int(bool(tmo)), rec_send=rec, rec_recv=rrec, failed_lines=failed, injected=inj,
                   ok0=s0.get("ok"), ok1=s1.get("ok"), wall_s=round(res["wall_s"], 3))


def rec_times(res):
    """total ms of each recovery from the send-comm log line."""
    out = []
    for _, l in res["lines0"] + res["lines1"]:
        if "send comm: recovered" in l and "total" in l:
            try:
                out.append(float(l.split("total ")[1].split(" ms")[0]))
            except Exception:
                pass
    return out


def gbh(cmd, *a):
    return subprocess.run([os.path.join(HERE, "gid_blackhole.sh"), cmd] + list(a), capture_output=True, text=True)


TESTS = {
    # id: (description, cfg env, count, iters, env0 extra, env1 extra, expect, special)
    "T0s": ("flag on, no fault, single", C.SINGLE, COUNT_SINGLE, 300, {}, {}, "pass", None),
    "T0d": ("flag on, no fault, default", DEFAULT, COUNT_DEFAULT, 60, {}, {}, "pass", None),
    "T1": ("S inject, single, unaligned k", C.SINGLE, COUNT_SINGLE, 300, {"NCCL_RDMA_FAULT_INJECT": "403"}, {}, "recover", None),
    "T2": ("S inject, default config", DEFAULT, COUNT_DEFAULT, 60, {"NCCL_RDMA_FAULT_INJECT": "301"}, {}, "recover", None),
    "T3": ("R inject (NOTIFY path), default", DEFAULT, COUNT_DEFAULT, 60, {}, {"NCCL_RDMA_FAULT_INJECT_RECV": "301"}, "recover", None),
    "T3s": ("R inject (NOTIFY path), single", C.SINGLE, COUNT_SINGLE, 300, {}, {"NCCL_RDMA_FAULT_INJECT_RECV": "403"}, "recover", None),
    # 64 MB broadcast: many 512 KB steps per op, receives posted ahead, so when R's QP dies right
    # after a receive completion S is streaming the next steps into it and meets RETRY_EXC
    "T4": ("R dies silently (S RETRY_EXC path), 64 MB broadcast stream, single", C.SINGLE, 16777216, 60, {},
           {"NCCL_RDMA_FAULT_INJECT_RECV": "301", "NCCL_RDMA_FAULT_INJECT_RECV_SILENT": "1"}, "recover", "bcast"),
    # all-reduce variant: R dies silently at the end of an iteration while S has nothing left to send
    # and waits for a CTS that never comes (a 2-rank ring has a data dependency back from R): only R's
    # WAITREQ deadline (120 s) can end it -- a documented limitation, kept as a test of the bound
    "T4ar": ("R dies silently, all-reduce (limitation: S idle)", C.SINGLE, COUNT_SINGLE, 300, {},
             {"NCCL_RDMA_FAULT_INJECT_RECV": "403", "NCCL_RDMA_FAULT_INJECT_RECV_SILENT": "1"}, "fail", None),
    "T1b": ("S inject, broadcast stream, single", C.SINGLE, COUNT_SINGLE, 300, {"NCCL_RDMA_FAULT_INJECT": "203"}, {}, "recover", "bcast"),
    "T5": ("S inject x5, default", DEFAULT, COUNT_DEFAULT, 80,
           {"NCCL_RDMA_FAULT_INJECT": "101", "NCCL_RDMA_FAULT_INJECT_REPEAT": "5", "NCCL_RDMA_FAULT_INJECT_PERIOD": "150"}, {}, "recover", None),
    "T6": ("symmetric S inject, default", DEFAULT, COUNT_DEFAULT, 60, {"NCCL_RDMA_FAULT_INJECT": "301"},
           {"NCCL_RDMA_FAULT_INJECT": "301"}, "recover", None),
    "T8": ("SIGKILL rank1, single", C.SINGLE, COUNT_SINGLE, 100000, {}, {}, "fail", "kill"),
    "T9": ("mute peer, R inject", C.SINGLE, COUNT_SINGLE, 300, {}, {"NCCL_RDMA_FAULT_INJECT_RECV": "403", "NCCL_RDMA_FAULT_TEST_MUTE": "1"},
           "fail", None),
    "T7a": ("GID blackhole 0.5 s", DEFAULT, COUNT_DEFAULT, 15000, {}, {}, "recover-gbh", ("gbh", 0.5)),
    "T7b": ("GID blackhole 6 s", DEFAULT, COUNT_DEFAULT, 15000, {}, {}, "recover-gbh", ("gbh", 6.0)),
    "T7c": ("GID blackhole 15 s", DEFAULT, COUNT_DEFAULT, 15000, {}, {}, "recover-gbh", ("gbh", 15.0)),
    # management-network outage: every TCP connection of this job between the two nodes is blackholed
    # for 12 s (iptables on rain, only this job's local ports), RDMA untouched. The OOB keepalive then
    # reports ETIMEDOUT after ~5 s on both sides. Must not fail the job (stock does not use TCP then).
    "T10": ("management-network (OOB) outage 12 s, default", DEFAULT, COUNT_DEFAULT, 12000, {}, {}, "pass", ("oob", 12.0)),
    # same with 1 GiB all-reduces (~0.3 s each): a comm then has requests outstanding for longer than
    # the FIN rule's 50 ms grace, which is what made the pre-fix build treat an OOB timeout as death
    "T10b": ("management-network (OOB) outage 12 s, 1 GiB all-reduces", DEFAULT, 268435456, 100, {}, {}, "pass", ("oob", 12.0)),
}

MGMT_PEER = "192.0.2.194"          # sunny on the management network (NCCL_SOCKET_IFNAME=eno1)
_oob_rules = []                          # iptables rule specs currently installed by this runner


def _ipt(op, spec):
    return subprocess.run(["sudo", "-n", "iptables", "-w", op] + spec, capture_output=True, text=True)


def oob_unblock():
    while _oob_rules:
        spec = _oob_rules.pop()
        _ipt("-D", spec)


def oob_partition(hold_s, log):
    """Blackhole every established TCP connection of the local nccl_ct to sunny's management address
    for hold_s seconds (only its local ports; ssh and everything else keep working), then restore."""
    pids = subprocess.run(["pgrep", "-x", "nccl_ct"], capture_output=True, text=True).stdout.split()
    ports = set()
    ss = subprocess.run(["ss", "-tnpH", "state", "established", "dst", MGMT_PEER], capture_output=True, text=True).stdout
    for line in ss.splitlines():
        if any(f"pid={pid}," in line for pid in pids):
            local = line.split()[2] if len(line.split()) > 3 else line.split()[0]
            ports.add(local.rsplit(":", 1)[1])
    try:
        for port in sorted(ports):
            for spec in (["OUTPUT", "1", "-p", "tcp", "-d", MGMT_PEER, "--sport", port, "-j", "DROP"],
                         ["INPUT", "1", "-p", "tcp", "-s", MGMT_PEER, "--dport", port, "-j", "DROP"]):
                r = _ipt("-I", spec)
                if r.returncode == 0:
                    _oob_rules.append([spec[0]] + spec[2:])
        log.write(f"{time.monotonic():.6f} OOB-PARTITION start pids={pids} local_ports={sorted(ports)} rules={len(_oob_rules)}\n")
        log.flush()
        time.sleep(hold_s)
    finally:
        oob_unblock()
        log.write(f"{time.monotonic():.6f} OOB-PARTITION end\n"); log.flush()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--tests", nargs="+", default=["T0s", "T1", "T2", "T3", "T4", "T5", "T6", "T8", "T9"])
    p.add_argument("--n", type=int, default=5)
    p.add_argument("--build", default="stage2")
    p.add_argument("--extra-env", nargs="*", default=[])
    p.add_argument("--run-timeout", type=int, default=240)
    p.add_argument("--recovery", type=int, default=1, help="0 = stock error path (control runs)")
    a = p.parse_args()
    os.makedirs(a.out, exist_ok=True)
    extra = dict(kv.split("=", 1) for kv in a.extra_env)
    # freeze the library for this campaign: both ranks use the same bytes even if it is rebuilt meanwhile
    snap = os.path.join(a.out, "lib_snapshot")
    os.makedirs(snap, exist_ok=True)
    subprocess.run(["cp", "-f", os.path.join(C.LIBS[a.build], "libnccl.so.2.23.4"), snap], check=True)
    for ln in ("libnccl.so.2", "libnccl.so"):
        p = os.path.join(snap, ln)
        if not os.path.exists(p):
            os.symlink("libnccl.so.2.23.4", p)
    C.LIBS[a.build] = snap
    md5 = subprocess.run(["md5sum", os.path.join(snap, "libnccl.so.2.23.4")], capture_output=True, text=True).stdout.split()[0]
    print(f"library snapshot {snap} md5 {md5}", flush=True)
    C.deploy([a.build])
    snap_counters(a.out, "before")
    rows = []
    gbh_up = False
    try:
        for t in a.tests:
            desc, cfg, count, iters, e0, e1, expect, special = TESTS[t]
            env = {**cfg, **FR, **extra}
            if not a.recovery:
                env["NCCL_RDMA_FAULT_RECOVERY"] = "0"
                expect = "fail" if expect.startswith("recover") else expect
            if special and special[0] == "gbh" and not gbh_up:
                r = gbh("setup")
                g0, g1 = r.stdout.split()
                C.run_pair._gids = (g0, g1)       # the job's QPs use the secondary GIDs
                gbh_up = True
            for i in range(a.n):
                tag = f"{t}_{i}"
                args = ["--iters", str(iters), "--count", str(count), "--check", "every", "--warmup", "5", "--timeout", "150"]
                if special == "bcast":
                    args += ["--op", "bcast"]
                killer = None
                if special == "kill":
                    def k():
                        time.sleep(8)
                        C.sh(f"ssh -o BatchMode=yes {C.PEER} 'pkill -9 -x nccl_ct'")
                    killer = threading.Thread(target=k, daemon=True); killer.start()
                elif special and special[0] == "gbh":
                    g = gbh("gids").stdout.split()
                    if len(g) == 2: C.run_pair._gids = (g[0], g[1])   # the index may have moved in a previous cut
                    def k(outage=special[1]):
                        time.sleep(3)   # the job (15000 x 16 MB) runs ~35 s; the cut lands ~2 s into its loop
                        gbh("cut", str(outage))
                    killer = threading.Thread(target=k, daemon=True); killer.start()
                elif special and special[0] == "oob":
                    plog = open(os.path.join(a.out, f"{tag}_partition.log"), "w")
                    def k(hold=special[1]):
                        time.sleep(3)   # ~2 s into the loop, all connections established
                        oob_partition(hold, plog)
                    killer = threading.Thread(target=k, daemon=True); killer.start()
                res = C.run_pair(a.out, tag, a.build, env, env0=e0, env1=e1, args=args, timeout=a.run_timeout,
                                 kill_on_fail=False, early_exit=(special != "kill"))
                if killer: killer.join(60)
                oob_unblock()
                v, info = classify(res, expect)
                rt = rec_times(res)
                row = {"test": t, "desc": desc, "i": i, "verdict": v, "rec_ms": ";".join(f"{x:.3f}" for x in rt), **info}
                rows.append(row)
                print(f"{tag}: {v} {info} rec_ms={row['rec_ms']}", flush=True)
                with open(os.path.join(a.out, "results.csv"), "w", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                    w.writeheader(); w.writerows(rows)
    finally:
        oob_unblock()
        if gbh_up:
            gbh("teardown")
            if hasattr(C.run_pair, "_gids"):
                del C.run_pair._gids
        C.cleanup()
        snap_counters(a.out, "after")


CNT = ["duplicate_request", "out_of_sequence", "packet_seq_err", "implied_nak_seq_err", "local_ack_timeout_err",
       "req_cqe_error", "req_cqe_flush_error", "resp_cqe_error", "resp_cqe_flush_error", "rnr_nak_retry_err",
       "roce_adp_retrans", "rx_read_requests", "rx_write_requests"]


def snap_counters(out, when):
    """Port hw counters on both nodes (stale-packet evidence: duplicate_request, out_of_sequence, ...)."""
    cmd = "for c in " + " ".join(CNT) + "; do printf '%s %s\\n' $c $(cat /sys/class/infiniband/{dev}/ports/1/hw_counters/$c 2>/dev/null || echo NA); done"
    r0 = C.sh(cmd.format(dev="mlx5_1")).stdout
    r1 = C.sh(f"ssh -o BatchMode=yes {C.PEER} bash -s", input=cmd.format(dev="mlx5_0")).stdout
    with open(os.path.join(out, f"hw_counters_{when}.txt"), "w") as f:
        f.write(f"# {time.strftime('%F %T')}\n[rain mlx5_1]\n{r0}[sunny mlx5_0]\n{r1}")


if __name__ == "__main__":
    main()
