#!/usr/bin/env python3
"""completion_time.py - how much does in-library recovery buy? (NCCL 2.23 net_ib)

Subcommands (run each under ../../gpu-initiated/common/cluster_run.sh):
  smoke     one short fault-free job per build (sanity).
  overhead  fault-free per-iteration latency / bus bandwidth: stock vs patch flag off vs on.
  fault     one job of N iterations with one injected fault, three ways:
              baseline  no fault;
              recover   patch flag on (the library recovers in place);
              restart   same fault with recovery off (stock error path): as soon as a rank
                        reports the error both are killed and the job is relaunched from the
                        failed iteration (per-iteration checkpoint, the best case for restart).
                        Its wall_s is the sum of the two segments' own wall times; the runner's
                        cleanup between them is reported apart (runner_wall_s).
Results: CSV + raw logs under --out.
"""
import argparse, csv, json, os, statistics, subprocess, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ctlib as C

FR_ON = {"NCCL_RDMA_FAULT_RECOVERY": "1"}
GBH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "stage2", "gid_blackhole.sh")


def fault_env_and_thread(a):
    """--fault inject (NCCL_RDMA_FAULT_INJECT=k on rank 0) or gbh:<sec> (remove sunny's secondary
    RoCE address for <sec> seconds, <delay> s after launch; the job runs on the secondary GIDs)."""
    if a.fault == "inject":
        return {"NCCL_RDMA_FAULT_INJECT": str(a.inject)}, None
    sec = float(a.fault.split(":")[1])
    def cut():
        time.sleep(a.gbh_delay)
        subprocess.run([GBH, "cut", str(sec)], capture_output=True)
    return {}, cut


def cfg_env(cfg):
    return dict(C.SINGLE) if cfg == "single" else {}


def row_of(res, **extra):
    s0, s1 = res["s0"] or {}, res["s1"] or {}
    return {**extra, "rc0": res["rc0"], "rc1": res["rc1"], "wall_s": round(res["wall_s"], 4),
            "init_ms0": s0.get("init_ms"), "ready_ms0": s0.get("ready_ms"), "loop_ms0": s0.get("loop_ms"),
            "ok0": s0.get("ok"), "ok1": s1.get("ok"), "fail_iter0": s0.get("fail_iter"), "fail_iter1": s1.get("fail_iter"),
            "med_ms0": s0.get("med_ms"), "p99_ms0": s0.get("p99_ms"), "busbw0": s0.get("busbw_GBs"),
            "med_ms1": s1.get("med_ms"), "busbw1": s1.get("busbw_GBs")}


def write_csv(path, rows):
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def cmd_smoke(a):
    C.deploy(a.builds)
    rows = []
    for b in a.builds:
        for fr in ([False, True] if b != "stock" else [False]):
            env = {**cfg_env(a.cfg), **(FR_ON if fr else {})}
            tag = f"smoke_{b}_{'on' if fr else 'off'}"
            res = C.run_pair(a.out, tag, b, env, args=["--iters", "20", "--count", str(a.count), "--check", "every"],
                             timeout=120)
            rows.append(row_of(res, tag=tag, build=b, fr=int(fr)))
            print(tag, res["rc0"], res["rc1"], (res["s0"] or {}).get("med_ms"), flush=True)
    write_csv(f"{a.out}/smoke.csv", rows)


def cmd_overhead(a):
    C.deploy(a.builds)
    rows = []
    variants = []
    for b in a.builds:
        variants += [(b, False)] + ([(b, True)] if b != "stock" else [])
    port = 43400
    for rep in range(a.reps):
        for count in a.counts:
            iters = max(20, min(a.iters, int(a.iters * 262144 / max(count, 262144))))
            for b, fr in variants:          # interleaved so drift hits every variant alike
                env = {**cfg_env(a.cfg), **(FR_ON if fr else {})}
                tag = f"ovh_{a.cfg}_{count}_{b}_{'on' if fr else 'off'}_r{rep}"
                port += 1
                res = C.run_pair(a.out, tag, b, env, port=port, timeout=300,
                                 args=["--iters", str(iters), "--count", str(count), "--warmup", "20",
                                       "--check", "last", "--quiet"])
                rows.append(row_of(res, tag=tag, cfg=a.cfg, count=count, bytes=count * 4, build=b, fr=int(fr),
                                   rep=rep, iters=iters))
                s0 = res["s0"] or {}
                print(f"{tag}: rc={res['rc0']}/{res['rc1']} med={s0.get('med_ms')} p99={s0.get('p99_ms')} busbw={s0.get('busbw_GBs')}",
                      flush=True)
                write_csv(f"{a.out}/overhead_{a.cfg}.csv", rows)


def fault_iter_of(res):
    """Iteration at which the fault surfaced (the one that failed or took longest)."""
    for s in (res["s0"], res["s1"]):
        if s and s.get("rc", 0) != 0 and s.get("fail_iter", -1) >= 0:
            return s["fail_iter"]
    return None


def cmd_fault(a):
    C.deploy(a.builds)
    if a.fault.startswith("gbh"):
        g = subprocess.run([GBH, "setup"], capture_output=True, text=True).stdout.split()
        C.run_pair._gids = (g[0], g[1])
    try:
        _cmd_fault(a)
    finally:
        if a.fault.startswith("gbh"):
            subprocess.run([GBH, "teardown"], capture_output=True)


def refresh_gids(a):
    """After an address flap the secondary GID may sit at another index: re-read before each job."""
    if a.fault.startswith("gbh"):
        g = subprocess.run([GBH, "gids"], capture_output=True, text=True).stdout.split()
        if len(g) == 2:
            C.run_pair._gids = (g[0], g[1])


def _cmd_fault(a):
    common = ["--count", str(a.count), "--check", "every", "--warmup", str(a.warmup), "--timeout", "120"]
    rows = []
    port = 43600
    for rep in range(a.reps):
        # 1. baseline: no fault
        port += 1
        tag = f"fault_{a.cfg}_{a.count}_baseline_r{rep}"
        refresh_gids(a)
        res = C.run_pair(a.out, tag, a.build_rec, cfg_env(a.cfg), port=port, timeout=a.timeout,
                         args=["--iters", str(a.iters)] + common)
        rows.append(row_of(res, tag=tag, mode="baseline", rep=rep, segments=1, t_detect_s=None, t_restart_s=None))
        print(f"{tag}: rc={res['rc0']}/{res['rc1']} wall={res['wall_s']:.3f}s", flush=True)

        # 2. recover in place (flag on)
        port += 1
        tag = f"fault_{a.cfg}_{a.count}_recover_r{rep}"
        env = {**cfg_env(a.cfg), **FR_ON, **dict(kv.split("=", 1) for kv in a.extra_env)}
        e0, cutter = fault_env_and_thread(a)
        th = threading.Thread(target=cutter, daemon=True) if cutter else None
        refresh_gids(a)
        if th: th.start()
        res = C.run_pair(a.out, tag, a.build_rec, env, env0=e0,
                         port=port, timeout=a.timeout, args=["--iters", str(a.iters)] + common)
        if th: th.join(120)
        rec = C.grep(res, r"initiator: recovered|\[FAULT-RECOVERY2?\].*send comm: recovered|\[FAULT-RECOVERY\].*recovered")
        inj = C.grep(res, r"\[FAULT-INJECT\]")
        t_inj = inj[0][0] if inj else None
        t_rec = rec[0][0] if rec else None
        rows.append(row_of(res, tag=tag, mode="recover", rep=rep, segments=1,
                           t_detect_s=None, t_recover_ms=round((t_rec - t_inj) * 1e3, 3) if (t_rec and t_inj) else None,
                           recovered=int(bool(rec)), injected=int(bool(inj))))
        print(f"{tag}: rc={res['rc0']}/{res['rc1']} wall={res['wall_s']:.3f}s injected={bool(inj)} recovered={bool(rec)}",
              flush=True)

        # 3. restart from the failed iteration (recovery off, same injection)
        port += 1
        tag = f"fault_{a.cfg}_{a.count}_restart_r{rep}"
        t_job0 = time.monotonic()
        e0, cutter = fault_env_and_thread(a)
        th = threading.Thread(target=cutter, daemon=True) if cutter else None
        refresh_gids(a)
        if th: th.start()
        res1 = C.run_pair(a.out, tag + "_seg1", a.build_inj, cfg_env(a.cfg), env0=e0,
                          port=port, timeout=a.timeout, kill_on_fail=True, args=["--iters", str(a.iters)] + common)
        if th: th.join(120)
        inj = C.grep(res1, r"\[FAULT-INJECT\]")
        t_inj = inj[0][0] if inj else None
        # the iteration that failed: the first "IT" line missing after the last completed one on rank 0
        its = [int(l.split()[1]) for _, l in res1["lines0"] if l.startswith("IT ")]
        its1 = [int(l.split()[1]) for _, l in res1["lines1"] if l.startswith("IT ")]
        resume = min((max(its) + 1) if its else 0, (max(its1) + 1) if its1 else 0)
        segs, t_detect = 1, None
        if res1["t_fail"] and t_inj:
            t_detect = res1["t_fail"] - t_inj
        res2 = None
        if resume < a.iters and (res1["rc0"] != 0 or res1["rc1"] != 0):
            port += 1
            t_r0 = time.monotonic()
            refresh_gids(a)
            res2 = C.run_pair(a.out, tag + "_seg2", a.build_inj, cfg_env(a.cfg), port=port, timeout=a.timeout,
                              args=["--iters", str(a.iters), "--start", str(resume)] + common)
            segs = 2
        t_job1 = time.monotonic()
        last = res2 or res1
        row = row_of(last, tag=tag, mode="restart", rep=rep, segments=segs, resume_iter=resume,
                     t_detect_s=round(t_detect, 4) if t_detect is not None else None,
                     seg1_wall_s=round(res1["wall_s"], 4), seg2_wall_s=round(res2["wall_s"], 4) if res2 else None,
                     injected=int(bool(inj)))
        # wall_s: the job's own time (both segments, launch to exit), comparable with the baseline's
        # wall_s. runner_wall_s adds the runner's cleanup between segments (pkill + 1 s sleep each),
        # which a job manager need not pay; do not compare it with the baseline.
        row["wall_s"] = round(res1["wall_s"] + (res2["wall_s"] if res2 else 0.0), 4)
        row["runner_wall_s"] = round(t_job1 - t_job0, 4)
        rows.append(row)
        print(f"{tag}: seg1 rc={res1['rc0']}/{res1['rc1']} resume={resume} seg2 rc="
              f"{(res2 or {}).get('rc0')}/{(res2 or {}).get('rc1')} wall={row['wall_s']:.3f}s "
              f"(runner {row['runner_wall_s']:.3f}s) detect={t_detect}",
              flush=True)
        write_csv(f"{a.out}/fault_{a.cfg}_{a.count}.csv", rows)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["smoke", "overhead", "fault"])
    p.add_argument("--out", required=True)
    p.add_argument("--cfg", choices=["single", "default"], default="single")
    p.add_argument("--builds", nargs="+", default=["stock", "stage1i"])
    p.add_argument("--count", type=int, default=65536)
    p.add_argument("--counts", type=int, nargs="+", default=[16384, 262144, 4194304, 16777216])
    p.add_argument("--iters", type=int, default=200)
    p.add_argument("--warmup", type=int, default=5)
    p.add_argument("--reps", type=int, default=3)
    p.add_argument("--inject", type=int, default=400)
    p.add_argument("--build-rec", default="stage1i")
    p.add_argument("--build-inj", default="stage1i")
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--fault", default="inject", help="inject | gbh:<seconds>")
    p.add_argument("--gbh-delay", type=float, default=3.0)
    p.add_argument("--extra-env", nargs="*", default=[])
    a = p.parse_args()
    os.makedirs(a.out, exist_ok=True)
    {"smoke": cmd_smoke, "overhead": cmd_overhead, "fault": cmd_fault}[a.cmd](a)


if __name__ == "__main__":
    main()
