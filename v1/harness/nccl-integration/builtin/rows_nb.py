#!/usr/bin/env python3
"""rows_nb.py - one row per trial of the nccl-builtin study, from the per-trial files of nbrun.py
(<stem>_r0.log, <stem>_r1.log, <stem>_meta.txt). The columns are defined in EXPERIMENT.md 3.1.

usage: rows_nb.py <logdir> [<logdir> ...] --out trials.csv

Times: every log line carries the CLOCK_MONOTONIC of rain at receipt (rank 1 lines arrive over ssh), and the meta
file carries the runner's times on the same clock, so every *_ms column below is a difference of rain-clock receipt
times (milliseconds). The hook lines of build n232 also carry the emitting process's mono_ms; those are kept as
inj_mono_ms for reference and not used by the acceptance rules.
"""
import csv, glob, json, os, re, sys

API_STR = {  # ncclGetErrorString() of 2.23.4 and 2.32.3 -> result name
    "remote process exited or there was a network error": "ncclRemoteError",
    "unhandled system error": "ncclSystemError",
    "internal error - please report this issue to the NCCL developers": "ncclInternalError",
    "unhandled cuda error": "ncclUnhandledCudaError",
    "invalid usage": "ncclInvalidUsage",
    "invalid argument": "ncclInvalidArgument",
}
RE_ERR = re.compile(r"\[rank(\d)\] (?:iter -?\d+ )?(?:async NCCL error(?: after sync)?: (.*)|ncclAllReduce -> (.*)|"
                    r"warmup ncclAllReduce -> (.*))$")
RE_NK = re.compile(r"\[rank\d\] NCCL \S+:\d+ (.*)$")                 # NK() macro: an NCCL call failed (rc 2)
RE_INJ = re.compile(r"\[FAULT-INJECT\] forced (send|recv) QP ")
RE_MONO = re.compile(r"mono_ms=([\d.]+)")
RE_VER = re.compile(r"NCCL version (\d+\.\d+\.\d+)")
RE_SUM = re.compile(r"SUMMARY (.*)$")
RE_STATUS = [re.compile(r"with status=\S*?\((\d+)\) opcode="),           # 2.32.3 stock: status=IBV_WC_WR_FLUSH_ERR(5)
             re.compile(r"Got completion with error \(devIndex=\d+, wc->status=\(\S*?\)(\d+)"),  # 2.32.3 resiliency INFO
             re.compile(r"Got completion from peer \S+ with status=(\d+) opcode="),            # 2.23.4 stock
             re.compile(r"incident via \S+: status=(\d+)\(")]                                  # stage 2 recovery
RE_S2REC = re.compile(r"\[FAULT-RECOVERY2\] send comm: recovered .*\(total ([\d.]+) ms\)")

COUNTS = {  # column stem -> substring (counted per rank)
    "stock_cqe": ("NET/IB: Got CQE with error", "NET/IB: Got completion from peer"),
    "single_dev": ("no other device to fail over to",),
    "fatal_nfd": ("The error is fatal (No functional devices left)",),
    "unsup_status": ("NET/IB: Unsupported completion status",),
    "res_init": ("Resiliency context was initialized on the",),
    "res_disabled": ("Resiliency is disabled on the",),
    "prec_enabled": ("Port recovery is enabled for the resiliency context",),
    "prec_disabled_ctx": ("Port recovery is disabled for the resiliency context",),
    "prec_thread": ("Starting port recovery async thread",),
    "prec_activity": (" marked as failed. Initiating recovery", "into the recovery queue", "Starting port recovery for",
                      "Port recovery succeeded", "Port recovery failed", "Replacing QP", "Posting probe"),
    "n232_mark": ("Receive work requests will be",),
    "s2_on": ("[FAULT-RECOVERY2] recovery on for",),
    "s2_fin": ("closed its OOB socket (FIN)",),
    "s2_failed": ("comm FAILED in",),
    "s2_incident": ("[FAULT-RECOVERY2]", "incident via"),
    "async_fatal": ("async fatal event",),
    "abort_ret": ("ncclCommAbort returned",),
    "abort_hang": ("ABORT-HANG",),
    "ready": ("comm ready:",),
    "timeout": ("TIMEOUT after",),
    "mism": ("MISMATCH",),
}


def read_log(path):
    out = []
    if not os.path.exists(path):
        return out
    with open(path, errors="replace") as f:
        for l in f:
            p = l.rstrip("\n").split(" ", 1)
            try:
                out.append((float(p[0]), p[1] if len(p) > 1 else ""))
            except ValueError:
                pass
    return out


def read_meta(path):
    m = {}
    if os.path.exists(path):
        for l in open(path):
            k, _, v = l.rstrip("\n").partition("=")
            m[k] = v
    return m


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def ms(a, b):
    return "" if a is None or b is None else "%.3f" % ((a - b) * 1e3)


def parse_summary(s):
    d = {}
    for kv in s.split():
        k, _, v = kv.partition("=")
        d[k] = v
    return d


def row(stem_path):
    """stem_path = <logdir>/<cell>.<cfg>_n<k> (no suffix)."""
    stem = os.path.basename(stem_path)
    m = re.match(r"(?P<cell>[^.]+)\.(?P<cfg>[^_]+)_n(?P<k>\d+)$", stem)
    meta = read_meta(stem_path + "_meta.txt")
    L = [read_log(stem_path + "_r0.log"), read_log(stem_path + "_r1.log")]
    r = {"stem": stem, "cell": m["cell"], "cfg": m["cfg"], "trial": "n" + m["k"], "bundle": meta.get("bundle", ""),
         "rc0": meta.get("rc0", ""), "rc1": meta.get("rc1", ""), "wall_s": meta.get("wall_s", ""),
         "wallcap": meta.get("wallcap", ""), "grace_kill_r0": meta.get("grace_kill_r0", ""),
         "grace_kill_r1": meta.get("grace_kill_r1", ""), "killed_r1": meta.get("killed_r1", ""),
         "kill_ok": "1" if meta.get("kill_out", "").startswith("killed ") else ("0" if meta.get("killed_r1") == "1" else ""),
         "left_after": meta.get("left_after", "")}
    envs = []
    for k in ("env0", "env1"):
        try:
            envs.append(json.loads(meta.get(k, "{}")))
        except ValueError:
            envs.append({})
    for col, var in (("env_fo", "NCCL_IB_RESILIENCY_PORT_FAILOVER"), ("env_rec", "NCCL_IB_RESILIENCY_PORT_RECOVERY"),
                     ("env_s2", "NCCL_RDMA_FAULT_RECOVERY"), ("debug", "NCCL_DEBUG")):
        r[col] = "%s/%s" % (envs[0].get(var, ""), envs[1].get(var, ""))
    for col, subs in COUNTS.items():
        for rk in (0, 1):
            r[f"{col}_r{rk}"] = sum(1 for _, l in L[rk] if all(s in l for s in subs)) if col == "s2_incident" else \
                sum(1 for _, l in L[rk] if any(s in l for s in subs))
    r["mism"] = r["mism_r0"] + r["mism_r1"]
    ver = [RE_VER.search(l).group(1) for _, l in L[0] if RE_VER.search(l)]
    r["ver_r0"] = ver[0] if ver else ""
    # fault
    inj = [(t, rk, l) for rk in (0, 1) for t, l in L[rk] if RE_INJ.search(l)]
    inj.sort(key=lambda x: x[0])
    r["inj_r0"] = sum(1 for x in inj if x[1] == 0)
    r["inj_r1"] = sum(1 for x in inj if x[1] == 1)
    r["inj_kind"] = ("silent" if "[silent]" in inj[0][2] else RE_INJ.search(inj[0][2]).group(1)) if inj else ""
    mono = RE_MONO.search(inj[0][2]) if inj else None
    r["inj_mono_ms"] = mono.group(1) if mono else ""
    t_inj = inj[0][0] if inj else None
    t_kill = fnum(meta.get("t_kill_req"))
    t_fault = t_kill if t_kill is not None else t_inj
    r["t_fault"] = "" if t_fault is None else "%.6f" % t_fault
    t_kd = fnum(meta.get("t_kill_done"))
    r["kill_rtt_ms"] = ms(t_kd, t_kill)   # the ssh round trip of the kill command; the kill lands inside it
    # application-visible errors (the driver's lines), timeouts, wrong results, summaries
    first_err = {}
    t_to_all = [t for rk in (0, 1) for t, l in L[rk] if "TIMEOUT after" in l]
    t_first_to = min(t_to_all) if t_to_all else None
    for rk in (0, 1):
        err = [(t, l) for t, l in L[rk] if RE_ERR.search(l) or RE_NK.search(l)]
        if err:
            t, l = err[0]
            mm = RE_ERR.search(l)
            if mm:
                kind = "async" if mm.group(2) is not None else "call"
                msg = next(g for g in mm.groups()[1:] if g is not None).strip()
            else:
                kind, msg = "call", RE_NK.search(l).group(1).strip()
            first_err[rk] = t
            r[f"err_r{rk}"], r[f"errcode_r{rk}"] = kind, API_STR.get(msg, msg)
            r[f"dt_err_r{rk}"] = ms(t, t_fault)
        else:
            r[f"err_r{rk}"] = r[f"errcode_r{rk}"] = r[f"dt_err_r{rk}"] = ""
        to = [t for t, l in L[rk] if "TIMEOUT after" in l]
        r[f"dt_to_r{rk}"] = ms(to[0] if to else None, t_fault)
        mi = [t for t, l in L[rk] if "MISMATCH" in l]
        r[f"dt_mism_r{rk}"] = ms(mi[0] if mi else None, t_fault)
        st = ""
        for _, l in L[rk]:
            for rx in RE_STATUS:
                mm = rx.search(l)
                if mm:
                    st = mm.group(1)
                    break
            if st:
                break
        r[f"wc_status_r{rk}"] = st
        s = [parse_summary(RE_SUM.search(l).group(1)) for _, l in L[rk] if RE_SUM.search(l)]
        r[f"ok_r{rk}"] = s[-1].get("ok", "") if s else ""
        r[f"iters_r{rk}"] = s[-1].get("iters", "") if s else ""
        r[f"med_ms_r{rk}"] = s[-1].get("med_ms", "") if s else ""
        r[f"sum_rc_r{rk}"] = s[-1].get("rc", "") if s else ""
    r["first_err_rank"] = "" if not first_err else str(min(first_err, key=first_err.get))
    rec = [float(RE_S2REC.search(l).group(1)) for rk in (0, 1) for _, l in L[rk] if RE_S2REC.search(l)]
    r["s2_rec"] = sum(1 for rk in (0, 1) for _, l in L[rk] if "[FAULT-RECOVERY2]" in l and "comm: recovered" in l)
    r["s2_rec_ms"] = "%.3f" % rec[0] if rec else ""
    # wrong results received before the first TIMEOUT line of either rank. After a TIMEOUT the driver calls
    # ncclCommAbort; an aborting kernel stops waiting and may hand its peer unfinished data (EXPERIMENT.md 1, 12), so a
    # MISMATCH after a timeout is a product of the harness's own ending and does not set the outcome
    r["mism_pre_to"] = sum(1 for rk in (0, 1) for t, l in L[rk]
                           if "MISMATCH" in l and (t_first_to is None or t < t_first_to))
    # outcome (EXPERIMENT.md 3.1)
    ok_all = (r["rc0"] == "0" and r["rc1"] == "0" and r["ok_r0"] != "" and r["ok_r0"] == r["iters_r0"] and
              r["ok_r1"] != "" and r["ok_r1"] == r["iters_r1"])
    if r["mism_pre_to"] > 0:
        r["outcome"] = "MISMATCH"
    elif ok_all:
        r["outcome"] = "TRANSPARENT"
    elif first_err:
        r["outcome"] = "ERROR"
    elif r["timeout_r0"] or r["timeout_r1"] or r["wallcap"] == "1":
        r["outcome"] = "HANG"
    else:
        r["outcome"] = "OTHER"
    r["launch_fail"] = int(not (r["ready_r0"] and r["ready_r1"]))
    return r


def rows(logdirs):
    out = []
    for d in logdirs:
        for meta in sorted(glob.glob(os.path.join(d, "*_meta.txt"))):
            out.append(row(meta[:-len("_meta.txt")]))
    return out


def main():
    a = sys.argv[1:]
    out = a[a.index("--out") + 1] if "--out" in a else None
    dirs = [x for i, x in enumerate(a) if x != "--out" and (i == 0 or a[i - 1] != "--out")]
    rs = rows(dirs)
    cols = []
    for r in rs:
        for c in r:
            if c not in cols:
                cols.append(c)
    f = open(out, "w", newline="") if out else sys.stdout
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    w.writerows(rs)


if __name__ == "__main__":
    main()
