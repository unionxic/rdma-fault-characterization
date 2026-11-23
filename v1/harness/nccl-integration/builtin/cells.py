#!/usr/bin/env python3
"""cells.py - the cells of the nccl-builtin study (EXPERIMENT.md 7). Runs n trials of one cell under one
configuration, one bounded trial at a time; called by hold.sh inside ../../gpu-initiated/common/cluster_run.sh.

usage: cells.py <logdir> <cell> <cfg> <n> [start]
       cells.py --list            (print the cell and configuration tables)

Trial files: <logdir>/<cell>.<cfg>_n<k>_{r0.log,r1.log,meta.txt} (nbrun.py). After every trial the configuration
check of EXPERIMENT.md 8 runs on that trial (rows_nb.py); a failure appends to <logdir>/../STOP_config and ends this
batch, and two trials in a row that leave an nb_ct process behind append to <logdir>/../STOP_left and end it.
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nbrun  # noqa: E402
import rows_nb  # noqa: E402

# the NCCL network configuration of each workload (as ../stage2/run_tests.py and ../perf/ctlib.py)
SINGLE = {"NCCL_MAX_NCHANNELS": "1", "NCCL_MIN_NCHANNELS": "1", "NCCL_ALGO": "Ring", "NCCL_PROTO": "Simple",
          "NCCL_IB_QPS_PER_CONNECTION": "1"}
DEFAULT = {}
# environment of every trial, both ranks
COMMON = {"NCCL_IB_TIMEOUT": "14", "NCCL_CT_ABORT_WATCHDOG_S": "10"}
# NCCL log level per cell: INFO with the INIT and NET subsystems where the predictions read INFO lines (the QP-fault
# cells); WARN for the kill and fault-free cells, where an INFO line on the data path (for example a CTS completion
# that finds its request already freed, p2p.cc ncclIbCompletionEventProcess) would cost time in every iteration
LOG_INFO = {"NCCL_DEBUG": "INFO", "NCCL_DEBUG_SUBSYS": "INIT,NET"}
LOG_WARN = {"NCCL_DEBUG": "WARN"}
PER_ITER_TIMEOUT_S = "12"   # the driver's --timeout: an iteration that does not finish in 12 s ends with TIMEOUT (rc 4)

# configuration -> (bundle, environment on both ranks)
CFG = {
    "off":   ("n232", {}),
    "rec":   ("n232", {"NCCL_IB_RESILIENCY_PORT_RECOVERY": "1"}),
    "fo":    ("n232", {"NCCL_IB_RESILIENCY_PORT_FAILOVER": "1"}),
    "forec": ("n232", {"NCCL_IB_RESILIENCY_PORT_FAILOVER": "1", "NCCL_IB_RESILIENCY_PORT_RECOVERY": "1"}),
    "s2on":  ("s2", {"NCCL_RDMA_FAULT_RECOVERY": "1"}),
    "s2off": ("s2", {"NCCL_RDMA_FAULT_RECOVERY": "0"}),
}

INJ_SEND = {"NCCL_RDMA_FAULT_INJECT": "301"}
INJ_RECV = {"NCCL_RDMA_FAULT_INJECT_RECV": "301"}
INJ_SILENT_BC = {"NCCL_RDMA_FAULT_INJECT_RECV": "301", "NCCL_RDMA_FAULT_INJECT_RECV_SILENT": "1"}
INJ_SILENT_AR = {"NCCL_RDMA_FAULT_INJECT_RECV": "403", "NCCL_RDMA_FAULT_INJECT_RECV_SILENT": "1"}

# cell -> workload. count is in floats (4 B). fault: inject0 = hook on rank 0, inject1 = hook on rank 1, kill1 = the
# runner SIGKILLs rank 1 at kill_at_s after rank 0's launch, none = no fault. Stage 2 analogue in brackets.
CELLS = {
    # send-QP ERR on rank 0 before multi-send #301; default config, 16 MiB all-reduce [T2]
    "sqp":    dict(net=DEFAULT, count=4194304, iters=150, warmup=0, op="allreduce", env0=INJ_SEND, env1={},
                   fault="inject0", wall=40, log=LOG_INFO),
    # recv-QP ERR on rank 1 before receive post #301; default config, 16 MiB all-reduce [T3]
    "rqp":    dict(net=DEFAULT, count=4194304, iters=150, warmup=0, op="allreduce", env0={}, env1=INJ_RECV,
                   fault="inject1", wall=40, log=LOG_INFO),
    # rank 1 SIGKILLed 5 s after launch while rank 0 runs back-to-back 256 KiB all-reduces (single config) [T8]
    "kill":   dict(net=SINGLE, count=65536, iters=300000, warmup=5, op="allreduce", env0={}, env1={}, quiet=True,
                   fault="kill1", kill_at_s=5.0, wall=40, log=LOG_WARN),
    # rank 1's recv QP silently to ERR after receive completion #301 with a receive pending; 64 MiB broadcast [T4]
    "slbc":   dict(net=SINGLE, count=16777216, iters=60, warmup=0, op="bcast", env0={}, env1=INJ_SILENT_BC,
                   fault="inject1", wall=40, log=LOG_INFO),
    # the same after completion #403; 256 KiB all-reduce [T4ar]
    "slar":   dict(net=SINGLE, count=65536, iters=1000, warmup=0, op="allreduce", env0={}, env1=INJ_SILENT_AR,
                   fault="inject1", wall=40, log=LOG_INFO),
    # fault-free all-reduce time (rank 0's per-iteration median, SUMMARY med_ms); default config
    "ovh64k": dict(net=DEFAULT, count=16384, iters=2000, warmup=20, op="allreduce", env0={}, env1={}, fault="none",
                   wall=15, log=LOG_WARN),
    "ovh16m": dict(net=DEFAULT, count=4194304, iters=200, warmup=5, op="allreduce", env0={}, env1={}, fault="none",
                   wall=15, log=LOG_WARN),
}
HOOK_KIND = {"sqp": "send", "rqp": "recv", "slbc": "silent", "slar": "silent"}
# cell keys of EXPERIMENT.md 7 (the silent hook of build s2 is armed only with its recovery flag on: no slbc/slar@s2off)
KEYS = (["sqp@" + c for c in ("off", "rec", "fo", "forec", "s2on", "s2off")] +
        ["rqp@" + c for c in ("off", "fo", "forec", "s2on", "s2off")] +
        ["kill@" + c for c in ("off", "fo", "forec", "s2on", "s2off")] +
        ["slbc@" + c for c in ("off", "fo", "forec", "s2on")] +
        ["slar@" + c for c in ("off", "fo", "forec", "s2on")] +
        [f"{o}@{c}" for o in ("ovh64k", "ovh16m") for c in ("off", "fo", "forec", "s2on", "s2off")])


def config_status(r):
    """EXPERIMENT.md 8, configuration check of one trial row: '' when it passes, else the reason."""
    cfg, cell = r["cfg"], r["cell"]
    both = lambda col, cond: cond(r[f"{col}_r0"]) and cond(r[f"{col}_r1"])  # noqa: E731
    if r["launch_fail"]:
        return ""            # a launch failure is an exclusion, not a configuration failure
    want_ver = "2.32.3" if CFG[cfg][0] == "n232" else "2.23.4"
    if r["ver_r0"] != want_ver:
        return "config_version"
    # the environment both ranks were given (meta file) must be the configuration's, and nothing else
    env = CFG[cfg][1]
    for col, var in (("env_fo", "NCCL_IB_RESILIENCY_PORT_FAILOVER"), ("env_rec", "NCCL_IB_RESILIENCY_PORT_RECOVERY"),
                     ("env_s2", "NCCL_RDMA_FAULT_RECOVERY")):
        if r[col] != "%s/%s" % (env.get(var, ""), env.get(var, "")):
            return "config_env"
    fo = cfg in ("fo", "forec")
    # WARN level: the single-device warning appears exactly when failover is on (p2p_resiliency.cc 840-844)
    if not both("single_dev", (lambda x: x >= 1) if fo else (lambda x: x == 0)):
        return "config_failover"
    if CELLS[cell]["log"] is not LOG_INFO:
        return config_hooks(r, cell)
    # INFO level (the QP-fault cells): library of rank 1, failover and recovery contexts, Stage 2 flag
    if CFG[cfg][0] == "n232" and not both("n232_mark", lambda x: x >= 1):
        return "config_lib_r1"
    if CFG[cfg][0] == "s2" and not both("n232_mark", lambda x: x == 0):
        return "config_lib_r1"
    if not both("res_init", (lambda x: x >= 1) if fo else (lambda x: x == 0)):
        return "config_failover"
    if not both("prec_thread", (lambda x: x >= 1) if cfg in ("rec", "forec") else (lambda x: x == 0)):
        return "config_recovery_thread"
    if cfg == "forec" and not both("prec_enabled", lambda x: x >= 1):
        return "config_recovery_ctx"
    if cfg == "fo" and not (both("prec_disabled_ctx", lambda x: x >= 1) and both("prec_enabled", lambda x: x == 0)):
        return "config_recovery_ctx"
    if not both("s2_on", (lambda x: x >= 1) if cfg == "s2on" else (lambda x: x == 0)):
        return "config_stage2_flag"
    return config_hooks(r, cell)


def config_hooks(r, cell):
    fault = CELLS[cell]["fault"]
    if fault in ("none", "kill1") and (r["inj_r0"] or r["inj_r1"]):
        return "config_hook_fired"
    if fault == "inject0" and r["inj_r1"] or fault == "inject1" and r["inj_r0"]:
        return "config_hook_rank"
    if r["inj_kind"] and r["inj_kind"] != HOOK_KIND[cell]:
        return "config_hook_kind"
    return ""


def trial(logdir, cell, cfg, k, gids):
    c = CELLS[cell]
    bundle, cenv = CFG[cfg]
    env = {**COMMON, **c["log"], **c["net"], **cenv}
    args = ["--iters", str(c["iters"]), "--count", str(c["count"]), "--check", "every", "--warmup", str(c["warmup"]),
            "--timeout", PER_ITER_TIMEOUT_S, "--op", c["op"]] + (["--quiet"] if c.get("quiet") else [])
    stem = f"{cell}.{cfg}_n{k}"
    nbrun.run_trial(logdir, stem, bundle, {**env, **c["env0"]}, {**env, **c["env1"]}, args, c["wall"],
                    kill_at_s=c.get("kill_at_s"), gids=gids)
    return rows_nb.row(os.path.join(logdir, stem))


def main():
    if sys.argv[1:2] == ["--list"]:
        for k, v in CELLS.items():
            print(k, v)
        for k, v in CFG.items():
            print(k, v)
        print(" ".join(KEYS))
        return
    logdir, cell, cfg, n = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
    start = int(sys.argv[5]) if len(sys.argv) > 5 else 1
    if f"{cell}@{cfg}" not in KEYS:
        sys.exit(f"unknown cell key {cell}@{cfg}")
    R = os.path.dirname(os.path.abspath(logdir))
    for stop in ("STOP_mlx5", "STOP_config", "STOP_left"):
        if os.path.exists(os.path.join(R, stop)):
            sys.exit(f"{stop} present: not running {cell}@{cfg}")
    gids = nbrun.gid_indices()
    streak_f = os.path.join(R, ".left_streak")
    for k in range(start, start + n):
        r = trial(logdir, cell, cfg, k, gids)
        why = config_status(r)
        print(f"{r['stem']}: outcome={r['outcome']} rc={r['rc0']}/{r['rc1']} inj={r['inj_r0']}/{r['inj_r1']} "
              f"err={r['err_r0']}{r['errcode_r0']}/{r['err_r1']}{r['errcode_r1']} dt_err={r['dt_err_r0']}/{r['dt_err_r1']} "
              f"wall={r['wall_s']} left={r['left_after']} {why}", flush=True)
        if why:
            with open(os.path.join(R, "STOP_config"), "a") as f:
                f.write(f"{r['stem']}: {why}\n")
            sys.exit(f"configuration check failed on {r['stem']}: {why}")
        left = sum(int(x) for x in r["left_after"].split(",") if x.isdigit()) if r["left_after"] else 0
        streak = int(open(streak_f).read()) if os.path.exists(streak_f) else 0
        streak = streak + 1 if left > 0 else 0
        open(streak_f, "w").write(str(streak))
        if streak >= 2:
            with open(os.path.join(R, "STOP_left"), "a") as f:
                f.write(f"{r['stem']}: nb_ct left behind two trials in a row ({r['left_after']})\n")
            sys.exit("nb_ct processes left behind two trials in a row")


if __name__ == "__main__":
    main()
