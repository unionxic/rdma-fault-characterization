#!/usr/bin/env python3
"""recount.py - independent recount of the nccl-builtin main run from the raw per-trial files.

Reads only: the trial files <results>/<cfg>/<cell>.<cfg>_n<k>_{r0.log,r1.log,meta.txt}, the hold outputs
<results>/hold_H*.out and chain.out, the hold snapshots' mlx5 files, EXPERIMENT.md, predictions.csv, PREREG.txt, and
the blobs of the pre-registration tag through `git show <tag>:<path>` (no working-tree file passes through git, so
no clean filter runs). Writes nothing.

It does not import, read or run score.py, rows_nb.py, SCORE.md or any trials_*.csv. Every column of EXPERIMENT.md 3.1
is parsed again here from the logs, the exclusion and configuration rules of EXPERIMENT.md 8 are applied here, and the
acceptance rules of predictions.csv are evaluated by the evaluator below (grammar of
../../gpu-initiated/gin_recovery/s2_close/EXPERIMENT.md 3.2, written from that text, not from its score.py).

usage: python3 qa/recount.py [results_dir]        (default: results/20261009 next to this folder)
Output: a Markdown-formatted report on stdout. Log lines are never printed (they carry peer socket addresses).
"""
import ast
import csv
import glob
import hashlib
import json
import os
import re
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
RES = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(STUDY, "results", "20261009")
TAG = "prereg/nccl-builtin-v1"
TAG_COMMIT = "0ca10eb7"
PREREG_TIME = "2026-10-09 01:27:17"

CFGS = ("off", "rec", "fo", "forec", "s2on", "s2off")
CFG_BUNDLE = {"off": "n232", "rec": "n232", "fo": "n232", "forec": "n232", "s2on": "s2", "s2off": "s2"}
CFG_ENV = {  # cells.py CFG, the environment a configuration gives both ranks
    "off": {}, "rec": {"NCCL_IB_RESILIENCY_PORT_RECOVERY": "1"}, "fo": {"NCCL_IB_RESILIENCY_PORT_FAILOVER": "1"},
    "forec": {"NCCL_IB_RESILIENCY_PORT_FAILOVER": "1", "NCCL_IB_RESILIENCY_PORT_RECOVERY": "1"},
    "s2on": {"NCCL_RDMA_FAULT_RECOVERY": "1"}, "s2off": {"NCCL_RDMA_FAULT_RECOVERY": "0"}}
CELL_FAULT = {"sqp": "inject0", "rqp": "inject1", "slbc": "inject1", "slar": "inject1", "kill": "kill1",
              "ovh64k": "none", "ovh16m": "none"}
CELL_INFO = {"sqp", "rqp", "slbc", "slar"}          # NCCL_DEBUG=INFO cells (EXPERIMENT.md 6)
HOOK_KIND = {"sqp": "send", "rqp": "recv", "slbc": "silent", "slar": "silent"}
INJ_RANK = {"sqp": 0, "rqp": 1, "slbc": 1, "slar": 1}

NCCL_ERR = {  # ncclGetErrorString (v2.32.3-1 src/init.cc; the same strings in v2.23.4-1)
    "no error": "ncclSuccess",
    "unhandled cuda error (run with NCCL_DEBUG=INFO for details)": "ncclUnhandledCudaError",
    "unhandled system error (run with NCCL_DEBUG=INFO for details)": "ncclSystemError",
    "internal error - please report this issue to the NCCL developers": "ncclInternalError",
    "invalid argument (run with NCCL_DEBUG=WARN for details)": "ncclInvalidArgument",
    "invalid usage (run with NCCL_DEBUG=WARN for details)": "ncclInvalidUsage",
    "remote process exited or there was a network error": "ncclRemoteError",
    "NCCL operation in progress": "ncclInProgress",
    "timeout": "ncclTimeout",
}

# ---------------------------------------------------------------------------------------------------- line patterns
RE_LINE = re.compile(r"^(\d+\.\d+) (.*)$")
RE_READY = re.compile(r"^\[rank\d\] comm ready:")
RE_VER = re.compile(r"NCCL version (\d+\.\d+\.\d+)")
RE_INJ = re.compile(r"\[FAULT-INJECT\] forced (send|recv) QP")
RE_ASYNC = re.compile(r"^\[rank\d\] iter -?\d+ async NCCL error(?: after sync)?: (.*)$")
RE_CALL = re.compile(r"^\[rank\d\] (?:iter -?\d+ |warmup )ncclAllReduce -> (.*)$|^\[rank\d\] NCCL \S+:\d+ (.*)$")
RE_TIMEOUT = re.compile(r"^\[rank\d\] iter (-?\d+) TIMEOUT after")
RE_MISM = re.compile(r"^\[rank\d\] iter (-?\d+) MISMATCH count=(\d+) first=(\d+) got=(\S+) expect=(\S+)")
RE_SUM = re.compile(r"^SUMMARY rank=(\d+) rc=(-?\d+) start=(\d+) iters=(\d+) ok=(\d+) fail_iter=(-?\d+) .*"
                    r"med_ms=([\d.]+) ")
RE_IT = re.compile(r"^IT (\d+) ([\d.]+)$")
# first error CQE status (EXPERIMENT.md 3.1 wc_status): 2.32.3 stock, 2.32.3 resiliency INFO, 2.23.4 stock, Stage 2
RE_WC = [re.compile(r"NET/IB: Got completion from peer .* with status=[A-Z_]+\((\d+)\)"),
         re.compile(r"wc->status=\([A-Z_]+\)(\d+)"),
         re.compile(r"NET/IB: Got completion from peer .* with status=(\d+) "),
         re.compile(r"\[FAULT-RECOVERY2\] \w+ comm: incident via [^:]+: status=(\d+)\(")]
RE_S2TOTAL = re.compile(r"\[FAULT-RECOVERY2\] send comm: recovered .*\(total ([\d.]+) ms\)")
STOCK_CQE = ("NET/IB: Got CQE with error", "NET/IB: Got completion from peer")
PREC = ("marked as failed. Initiating recovery", "into the recovery queue", "Starting port recovery for",
        "Port recovery succeeded", "Port recovery failed", "Replacing QP", "Posting probe")
# a wider net for "did any failover or recovery step run" (not a column; every runtime branch of p2p_resiliency*.cc
# past the fatality check, plus the non-fatal branch of that check)
WIDE = ("The error is not fatal", "marked as failed", "was already marked as failed", "into the recovery queue",
        "Starting port recovery for", "Port recovery succeeded", "Port recovery failed", "Replacing QP",
        "Posting probe", "Fatal error. Detected", "Fatal error status in work completion",
        "Unsupported completion status", "ncclIbResiliencyHandleCompletionErrorSender",
        "ncclIbResiliencyHandleCompletionErrorReceiver", "Restoring QP", "Probe")
COUNTS = {  # column -> substring (EXPERIMENT.md 3.1)
    "single_dev": "no other device to fail over to",
    "fatal_nfd": "The error is fatal (No functional devices left)",
    "res_init": "Resiliency context was initialized on the",
    "res_disabled": "Resiliency is disabled on the",
    "prec_enabled": "Port recovery is enabled for the resiliency context",
    "prec_disabled_ctx": "Port recovery is disabled for the resiliency context",
    "prec_thread": "Starting port recovery async thread",
    "n232_mark": "Receive work requests will be",
    "s2_on": "[FAULT-RECOVERY2] recovery on for",
    "s2_fin": "closed its OOB socket (FIN)",
    "timeout": "TIMEOUT after",
    "abort_ret": "ncclCommAbort returned",
    "abort_hang": "ABORT-HANG",
}


def read_log(path):
    lines, bad = [], 0
    with open(path, errors="replace") as f:
        for ln in f:
            m = RE_LINE.match(ln.rstrip("\n"))
            if m:
                lines.append((float(m.group(1)), m.group(2)))
            elif ln.strip():
                bad += 1
    return lines, bad


def read_meta(path):
    meta = {}
    with open(path) as f:
        for ln in f:
            k, _, v = ln.rstrip("\n").partition("=")
            meta[k] = v
    return meta


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def first(lines, pred):
    for t, s in lines:
        r = pred(s)
        if r:
            return t, s, r
    return None


def parse_trial(stem_path):
    """All columns of EXPERIMENT.md 3.1 for one trial, plus a few extra fields (prefixed x_)."""
    meta = read_meta(stem_path + "_meta.txt")
    L = {}
    unprefixed = 0
    for r in (0, 1):
        L[r], b = read_log(f"{stem_path}_r{r}.log")
        unprefixed += b
    stem = os.path.basename(stem_path)
    m = re.match(r"^(\w+)\.(\w+)_n(\d+)$", stem)
    cell, cfg, k = m.group(1), m.group(2), int(m.group(3))
    row = {"stem": stem, "cell": cell, "cfg": cfg, "trial": f"n{k}", "x_k": k, "x_unprefixed": unprefixed,
           "x_date": meta.get("date", ""), "x_folder": os.path.basename(os.path.dirname(stem_path))}
    row["rc0"], row["rc1"] = fnum(meta.get("rc0")), fnum(meta.get("rc1"))
    for r in (0, 1):
        row[f"ready_r{r}"] = sum(1 for _, s in L[r] if RE_READY.search(s))
    row["launch_fail"] = int(row["ready_r0"] == 0 or row["ready_r1"] == 0)
    v = first(L[0], lambda s: RE_VER.search(s))
    row["ver_r0"] = v[2].group(1) if v else None
    v1 = first(L[1], lambda s: RE_VER.search(s))
    row["x_ver_r1"] = v1[2].group(1) if v1 else None
    # hook lines
    hooks = []
    for r in (0, 1):
        n = 0
        for t, s in L[r]:
            mm = RE_INJ.search(s)
            if mm:
                n += 1
                hooks.append((t, r, "silent" if "[silent]" in s else mm.group(1)))
        row[f"inj_r{r}"] = n
    hooks.sort()
    row["inj_kind"] = hooks[0][2] if hooks else None
    # fault time
    if CELL_FAULT[cell] == "kill1":
        t_fault = fnum(meta.get("t_kill_req"))
    elif CELL_FAULT[cell].startswith("inject"):
        t_fault = hooks[0][0] if hooks else None
    else:
        t_fault = None
    row["t_fault"] = t_fault
    tk0, tk1 = fnum(meta.get("t_kill_req")), fnum(meta.get("t_kill_done"))
    row["kill_rtt_ms"] = (tk1 - tk0) * 1e3 if tk0 is not None and tk1 is not None else None
    dt = lambda t: (t - t_fault) * 1e3 if (t is not None and t_fault is not None) else None  # noqa: E731
    t_err = {}
    t_to_all = []
    for r in (0, 1):
        e = None
        for t, s in L[r]:
            ma = RE_ASYNC.match(s)
            mc = RE_CALL.match(s)
            if ma:
                e = (t, "async", NCCL_ERR.get(ma.group(1), "?" + ma.group(1)))
                break
            if mc:
                msg = mc.group(1) if mc.group(1) is not None else mc.group(2)
                e = (t, "call", NCCL_ERR.get(msg, "?" + msg))
                break
        row[f"err_r{r}"] = e[1] if e else None
        row[f"errcode_r{r}"] = e[2] if e else None
        row[f"dt_err_r{r}"] = dt(e[0]) if e else None
        t_err[r] = e[0] if e else None
        to = first(L[r], lambda s: RE_TIMEOUT.match(s))
        row[f"dt_to_r{r}"] = dt(to[0]) if to else None
        row[f"x_t_to_r{r}"] = to[0] if to else None
        row[f"x_to_iter_r{r}"] = int(to[2].group(1)) if to else None
        t_to_all += [t for t, s in L[r] if "TIMEOUT after" in s]
        # wc_status: the first of the four patterns in log order
        st, t_st = None, None
        for t, s in L[r]:
            for rx in RE_WC:
                mw = rx.search(s)
                if mw:
                    st, t_st = int(mw.group(1)), t
                    break
            if st is not None:
                break
        row[f"wc_status_r{r}"] = st
        row[f"x_dt_wc_r{r}"] = dt(t_st)
        row[f"stock_cqe_r{r}"] = sum(1 for _, s in L[r] if any(p in s for p in STOCK_CQE))
        row[f"prec_activity_r{r}"] = sum(1 for _, s in L[r] if any(p in s for p in PREC))
        row[f"x_wide_r{r}"] = sum(1 for _, s in L[r] if any(p in s for p in WIDE))
        row[f"x_got_cqe_with_error_info_r{r}"] = sum(1 for _, s in L[r] if "Got completion with error" in s)
        for col, sub in COUNTS.items():
            row[f"{col}_r{r}"] = sum(1 for _, s in L[r] if sub in s)
        # anchored driver-line counts (a cross-check of the substring counts)
        row[f"x_timeout_anch_r{r}"] = sum(1 for _, s in L[r] if RE_TIMEOUT.match(s))
        row[f"x_abort_ret_anch_r{r}"] = sum(1 for _, s in L[r] if re.match(r"^\[rank\d\] ncclCommAbort returned$", s))
        row[f"x_abort_hang_anch_r{r}"] = sum(1 for _, s in L[r] if s.startswith("ABORT-HANG:"))
        row[f"x_s2_rec_r{r}"] = sum(1 for _, s in L[r] if "[FAULT-RECOVERY2]" in s and "comm: recovered" in s)
        # SUMMARY
        sm = first(L[r], lambda s: RE_SUM.match(s))
        if sm:
            g = sm[2]
            row[f"x_sum_rc_r{r}"] = int(g.group(2))
            row[f"iters_r{r}"] = int(g.group(4))
            row[f"ok_r{r}"] = int(g.group(5))
            row[f"med_ms_r{r}"] = float(g.group(7))
            row[f"x_t_sum_r{r}"] = sm[0]
        else:
            row[f"x_sum_rc_r{r}"] = row[f"iters_r{r}"] = row[f"ok_r{r}"] = row[f"med_ms_r{r}"] = None
            row[f"x_t_sum_r{r}"] = None
        row[f"x_nsum_r{r}"] = sum(1 for _, s in L[r] if RE_SUM.match(s))
        ar = first(L[r], lambda s: re.match(r"^\[rank\d\] ncclCommAbort returned$", s))
        row[f"x_abort_ret_ms_r{r}"] = (ar[0] - sm[0]) * 1e3 if (ar and sm) else None
        # per-iteration times, and the driver's own median rule pct(ms, 0.5): index (size_t)(0.5*(n-1)+0.5)
        its = [float(mi.group(2)) for _, s in L[r] for mi in [RE_IT.match(s)] if mi]
        row[f"x_nit_r{r}"] = len(its)
        if its:
            srt = sorted(its)
            row[f"x_itmed_r{r}"] = srt[int(0.5 * (len(srt) - 1) + 0.5)]
        else:
            row[f"x_itmed_r{r}"] = None
        # MISMATCH
        mis = [(t, mm) for t, s in L[r] for mm in [RE_MISM.match(s)] if mm]
        row[f"mism_r{r}"] = sum(1 for _, s in L[r] if "MISMATCH" in s)
        row[f"dt_mism_r{r}"] = dt(mis[0][0]) if mis else None
        row[f"x_mism_detail_r{r}"] = ([dict(iter=int(mm.group(1)), count=int(mm.group(2)), first=int(mm.group(3)),
                                            got=mm.group(4), expect=mm.group(5), t=t) for t, mm in mis])
    row["x_t_err_r0"], row["x_t_err_r1"] = t_err[0], t_err[1]
    if t_err[0] is None and t_err[1] is None:
        row["first_err_rank"] = None
    elif t_err[1] is None or (t_err[0] is not None and t_err[0] <= t_err[1]):
        row["first_err_rank"] = 0
    else:
        row["first_err_rank"] = 1
    # environment (meta)
    env = {r: json.loads(meta.get(f"env{r}", "{}")) for r in (0, 1)}
    for col, var in (("env_fo", "NCCL_IB_RESILIENCY_PORT_FAILOVER"), ("env_rec", "NCCL_IB_RESILIENCY_PORT_RECOVERY"),
                     ("env_s2", "NCCL_RDMA_FAULT_RECOVERY"), ("debug", "NCCL_DEBUG")):
        row[col] = "%s/%s" % (env[0].get(var, ""), env[1].get(var, ""))
    row["x_env"] = env
    row["x_bundle"] = meta.get("bundle")
    row["x_args"] = meta.get("args")
    # Stage 2
    row["s2_rec"] = row["x_s2_rec_r0"] + row["x_s2_rec_r1"]
    rec_lines = sorted((t, s) for r in (0, 1) for t, s in L[r] if RE_S2TOTAL.search(s))
    row["s2_rec_ms"] = float(RE_S2TOTAL.search(rec_lines[0][1]).group(1)) if rec_lines else None
    row["x_s2_rec_ms_all"] = [float(RE_S2TOTAL.search(s).group(1)) for _, s in rec_lines]
    row["x_s2_rec_dt"] = dt(rec_lines[0][0]) if rec_lines else None
    row["x_s2_failed"] = sum(1 for r in (0, 1) for _, s in L[r] if "[FAULT-RECOVERY2]" in s and "FAILED" in s)
    row["x_s2_silent_drain"] = sum(1 for r in (0, 1) for _, s in L[r] if "SILENT test mode: not notifying" in s)
    fin = first(L[0], lambda s: COUNTS["s2_fin"] in s)
    row["x_t_fin_r0"] = fin[0] if fin else None
    # mismatch totals
    row["mism"] = row["mism_r0"] + row["mism_r1"]
    t_to_min = min(t_to_all) if t_to_all else None
    mis_all = [d["t"] for r in (0, 1) for d in row[f"x_mism_detail_r{r}"]]
    row["mism_pre_to"] = row["mism"] if t_to_min is None else sum(1 for t in mis_all if t < t_to_min)
    # runner meta
    row["kill_ok"] = int(bool(re.match(r"^killed \d+$", meta.get("kill_out", ""))))
    row["wallcap"] = int(meta.get("wallcap", "0") or 0)
    row["grace_kill_r0"] = int(meta.get("grace_kill_r0", "0") or 0)
    row["grace_kill_r1"] = int(meta.get("grace_kill_r1", "0") or 0)
    row["wall_s"] = meta.get("wall_s")
    row["left_after"] = meta.get("left_after")
    row["left_before"] = meta.get("left_before")
    row["x_kill_after_done_ms"] = None
    # outcome (EXPERIMENT.md 3.1)
    timeout_any = row["timeout_r0"] + row["timeout_r1"] > 0
    if row["mism_pre_to"] > 0:
        out = "MISMATCH"
    elif (row["rc0"] == 0 and row["rc1"] == 0 and row["ok_r0"] is not None and row["ok_r1"] is not None
          and row["ok_r0"] == row["iters_r0"] and row["ok_r1"] == row["iters_r1"]):
        out = "TRANSPARENT"
    elif row["err_r0"] or row["err_r1"]:
        out = "ERROR"
    elif timeout_any or row["wallcap"]:
        out = "HANG"
    else:
        out = "OTHER"
    row["outcome"] = out
    if cell == "kill" and t_err[0] is not None and tk1 is not None:
        row["x_kill_after_done_ms"] = (t_err[0] - tk1) * 1e3
    return row


# ----------------------------------------------------------------------------------- EXPERIMENT.md 8: exclusion, config
def exclusion(r):
    """'' when the trial is scored, else the section-8 exclusion reason."""
    if r["launch_fail"]:
        return "launch_fail"
    c = r["cell"]
    if c == "sqp" and r["inj_r0"] == 0:
        return "no_injection"
    if c in ("rqp", "slbc", "slar") and r["inj_r1"] == 0:
        return "no_injection"
    if c == "kill" and (r["kill_ok"] != 1 or r["ok_r0"] is None or r["ok_r0"] < 1000):
        return "kill_not_applied"
    return ""


def config_check(r):
    """EXPERIMENT.md 8 configuration check, written from the text of section 8."""
    cfg, cell = r["cfg"], r["cell"]
    both = lambda col, f: f(r[f"{col}_r0"]) and f(r[f"{col}_r1"])  # noqa: E731
    bad = []
    want = "2.32.3" if CFG_BUNDLE[cfg] == "n232" else "2.23.4"
    if r["ver_r0"] != want:
        bad.append("version")
    if r["x_bundle"] != CFG_BUNDLE[cfg]:
        bad.append("bundle")
    env = CFG_ENV[cfg]
    for col, var in (("env_fo", "NCCL_IB_RESILIENCY_PORT_FAILOVER"), ("env_rec", "NCCL_IB_RESILIENCY_PORT_RECOVERY"),
                     ("env_s2", "NCCL_RDMA_FAULT_RECOVERY")):
        if r[col] != "%s/%s" % (env.get(var, ""), env.get(var, "")):
            bad.append(col)
    fo = cfg in ("fo", "forec")
    if not both("single_dev", (lambda x: x >= 1) if fo else (lambda x: x == 0)):
        bad.append("single_dev")
    fault = CELL_FAULT[cell]
    if fault in ("none", "kill1") and (r["inj_r0"] or r["inj_r1"]):
        bad.append("hook_fired")
    if fault == "inject0" and r["inj_r1"] or fault == "inject1" and r["inj_r0"]:
        bad.append("hook_rank")
    if fault.startswith("inject") and r["inj_kind"] != HOOK_KIND[cell]:
        bad.append("hook_kind")
    want_debug = "INFO/INFO" if cell in CELL_INFO else "WARN/WARN"
    if r["debug"] != want_debug:
        bad.append("debug")
    if cell in CELL_INFO:
        n232 = CFG_BUNDLE[cfg] == "n232"
        if not both("n232_mark", (lambda x: x >= 1) if n232 else (lambda x: x == 0)):
            bad.append("lib_r1")
        if not both("res_init", (lambda x: x >= 1) if fo else (lambda x: x == 0)):
            bad.append("res_init")
        if not both("prec_thread", (lambda x: x >= 1) if cfg in ("rec", "forec") else (lambda x: x == 0)):
            bad.append("prec_thread")
        if cfg == "forec" and not both("prec_enabled", lambda x: x >= 1):
            bad.append("prec_enabled")
        if cfg == "fo" and not (both("prec_disabled_ctx", lambda x: x >= 1) and both("prec_enabled", lambda x: x == 0)):
            bad.append("prec_ctx")
        if not both("s2_on", (lambda x: x >= 1) if cfg == "s2on" else (lambda x: x == 0)):
            bad.append("s2_flag")
    return ",".join(bad)


# ------------------------------------------------------------------------------------------- the acceptance grammar
class Ev:
    """Evaluator for the acceptance grammar (s2_close EXPERIMENT.md 3.2): count(E), median(F, "key"), abs, has,
    nonempty; numbers are floats, blanks are None, other values strings; any comparison or arithmetic with None is
    false (arithmetic gives None, which no comparison accepts)."""

    def __init__(self, rows_by_key, cols):
        self.rows_by_key, self.cols = rows_by_key, cols
        self.row = None
        self.cell = None

    @staticmethod
    def conv(v):
        if v is None or v == "":
            return None
        if isinstance(v, bool):
            return float(v)
        if isinstance(v, (int, float)):
            return float(v)
        try:
            return float(v)
        except (TypeError, ValueError):
            return str(v)

    def name(self, n):
        if n not in self.cols:
            raise KeyError(f"unknown column {n}")
        if self.row is None:
            raise ValueError(f"column {n} outside count()")
        return self.conv(self.row.get(n))

    def ev(self, node):
        if isinstance(node, ast.Expression):
            return self.ev(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in ("True", "False", "None"):
                return {"True": True, "False": False, "None": None}[node.id]
            return self.name(node.id)
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                return all(bool(self.ev(v)) for v in node.values)
            return any(bool(self.ev(v)) for v in node.values)
        if isinstance(node, ast.UnaryOp):
            v = self.ev(node.operand)
            if isinstance(node.op, ast.Not):
                return not bool(v)
            if isinstance(node.op, ast.USub):
                return None if v is None else -v
            raise ValueError("unary op")
        if isinstance(node, ast.BinOp):
            a, b = self.ev(node.left), self.ev(node.right)
            if a is None or b is None:
                return None
            op = node.op
            if isinstance(op, ast.Add):
                return a + b
            if isinstance(op, ast.Sub):
                return a - b
            if isinstance(op, ast.Mult):
                return a * b
            if isinstance(op, ast.Div):
                return a / b
            raise ValueError("binop")
        if isinstance(node, ast.Compare):
            left = self.ev(node.left)
            for op, rn in zip(node.ops, node.comparators):
                right = self.ev(rn)
                if left is None or right is None:
                    return False
                try:
                    ok = {ast.Eq: lambda x, y: x == y, ast.NotEq: lambda x, y: x != y, ast.Lt: lambda x, y: x < y,
                          ast.LtE: lambda x, y: x <= y, ast.Gt: lambda x, y: x > y,
                          ast.GtE: lambda x, y: x >= y}[type(op)](left, right)
                except TypeError:
                    return False
                if not ok:
                    return False
                left = right
            return True
        if isinstance(node, ast.Call):
            fn = node.func.id
            if fn == "count":
                rows = self.rows_by_key[self.cell]
                n = 0
                for r in rows:
                    self.row = r
                    if bool(self.ev(node.args[0])):
                        n += 1
                self.row = None
                return n
            if fn == "median":
                col, key = node.args[0].id, self.ev(node.args[1])
                vals = [self.conv(r.get(col)) for r in self.rows_by_key[key]]
                vals = [v for v in vals if isinstance(v, float)]
                return statistics.median(vals) if vals else None
            if fn == "abs":
                v = self.ev(node.args[0])
                return None if v is None else abs(v)
            if fn == "nonempty":
                return self.name(node.args[0].id) is not None
            if fn == "has":
                v = self.name(node.args[0].id)
                return v is not None and str(self.ev(node.args[1])) in str(v)
            raise ValueError(f"function {fn}")
        raise ValueError(f"node {type(node).__name__}")

    def run(self, expr, cell):
        self.cell = cell
        return self.ev(ast.parse(expr.strip(), mode="eval"))

    def count_inner(self, expr, cell):
        """For count(E) <op> N rules: count(E), and the trials that conform to the prediction and those that do not.
        A rule 'count(E) == 0' predicts E false in every trial; any other rule predicts E true."""
        tree = ast.parse(expr.strip(), mode="eval").body
        if isinstance(tree, ast.Compare) and isinstance(tree.left, ast.Call) and tree.left.func.id == "count":
            inner = tree.left.args[0]
            want_false = (len(tree.ops) == 1 and isinstance(tree.ops[0], ast.Eq)
                          and isinstance(tree.comparators[0], ast.Constant) and tree.comparators[0].value == 0)
            n_true, conf, nonconf = 0, [], []
            for r in sorted(self.rows_by_key[cell], key=lambda x: x["x_k"]):
                self.row = r
                e = bool(self.ev(inner))
                n_true += e
                (conf if e != want_false else nonconf).append(r["trial"])
            self.row = None
            return n_true, conf, nonconf
        return None, None, None


# --------------------------------------------------------------------------------------------- integrity helpers
def git(*args):
    return subprocess.run(["git", "-C", STUDY] + list(args), capture_output=True, check=True).stdout


def sections(text_bytes):
    lines = text_bytes.split(b"\n")
    out, cur, buf = {}, None, []
    for ln in lines:
        m = re.match(rb"^## (\d+)\. ", ln)
        if m:
            if cur is not None:
                out[cur] = b"\n".join(buf)
            cur, buf = int(m.group(1)), [ln]
        elif cur is not None:
            buf.append(ln)
    if cur is not None:
        out[cur] = b"\n".join(buf)
    return out


def plan_from_section7(sec7):
    """Planned trials per cell key from the table of EXPERIMENT.md 7 ('`off`, `fo`, `forec` 각 10, ...'; '같음')."""
    plan, prev = {}, None
    for ln in sec7.decode().split("\n"):
        m = re.match(r"^\| `(\w+)` \| .*? \| (.*?) \| [^|]* \|$", ln)
        if not m:
            continue
        cell, spec = m.group(1), m.group(2)
        if spec.strip() == "같음":
            got = {f"{cell}@{k.split('@')[1]}": v for k, v in prev.items()}
        else:
            got = {}
            for grp, n in re.findall(r"((?:`\w+`(?:, )?)+) (?:각 )?(\d+)", spec):
                for c in re.findall(r"`(\w+)`", grp):
                    got[f"{cell}@{c}"] = int(n)
        plan.update(got)
        prev = got
    return plan


def rng(vals, fmt="%.3f"):
    v = [x for x in vals if x is not None]
    if not v:
        return "none"
    if len(v) == 1:
        return fmt % v[0]
    return (fmt + "–" + fmt) % (min(v), max(v))


def med(vals):
    v = [x for x in vals if x is not None]
    return statistics.median(v) if v else None


def fmtv(x, fmt="%.3f"):
    return "none" if x is None else fmt % x


# --------------------------------------------------------------------------------------------------------- main
def main():
    P = print
    rel = os.path.relpath(STUDY, git("rev-parse", "--show-toplevel").decode().strip())
    P(f"# nccl-builtin independent recount: report of qa/recount.py\n")
    P(f"results folder: `{os.path.relpath(RES, STUDY)}`\n")

    # ---------------- integrity
    P("## Integrity\n")
    wt_pred = open(os.path.join(STUDY, "predictions.csv"), "rb").read()
    tag_pred = git("show", f"{TAG}:{rel}/predictions.csv")
    prereg = open(os.path.join(STUDY, "PREREG.txt")).read()
    m = re.search(r"^([0-9a-f]{64})  predictions\.csv$", prereg, re.M)
    h_wt, h_tag = hashlib.sha256(wt_pred).hexdigest(), hashlib.sha256(tag_pred).hexdigest()
    h_pr = m.group(1) if m else None
    P(f"- predictions.csv sha256: working tree `{h_wt}`, tag blob `{h_tag}`, PREREG.txt `{h_pr}`: "
      f"{'all equal' if h_wt == h_tag == h_pr else 'DIFFERENT'}")
    tag_prereg = git("show", f"{TAG}:{rel}/PREREG.txt")
    P(f"- PREREG.txt equals the tag blob: {open(os.path.join(STUDY, 'PREREG.txt'), 'rb').read() == tag_prereg}")
    tc = git("rev-parse", f"{TAG}^{{commit}}").decode().strip()
    P(f"- tag {TAG} points at commit `{tc[:8]}` (expected `{TAG_COMMIT}`): {tc.startswith(TAG_COMMIT)}")
    wt_exp = open(os.path.join(STUDY, "EXPERIMENT.md"), "rb").read()
    tag_exp = git("show", f"{TAG}:{rel}/EXPERIMENT.md")
    sw, st = sections(wt_exp), sections(tag_exp)
    for n in (2, 3, 7, 8):
        P(f"- EXPERIMENT.md section {n}: {len(sw.get(n, b''))} bytes in the working tree, byte-identical to the tag: "
          f"{sw.get(n) == st.get(n) and n in sw}")
    P(f"- EXPERIMENT.md as a whole equals the tag blob: {wt_exp == tag_exp}")
    npred = len(list(csv.DictReader(open(os.path.join(STUDY, "predictions.csv")))))
    P(f"- predictions.csv rows: {npred}")
    plan = plan_from_section7(st[7])
    P(f"- planned trials from section 7 table: {len(plan)} cell keys, {sum(plan.values())} trials "
      f"(fault {sum(v for k, v in plan.items() if not k.startswith('ovh'))}, "
      f"fault-free {sum(v for k, v in plan.items() if k.startswith('ovh'))})")

    # ---------------- trial set
    rows, problems = [], []
    for cfg in sorted(os.listdir(RES)):
        d = os.path.join(RES, cfg)
        if not os.path.isdir(d):
            continue
        files = sorted(os.listdir(d))
        metas = [f[:-len("_meta.txt")] for f in files if f.endswith("_meta.txt")]
        for f in files:
            if not re.match(r"^\w+\.\w+_n\d+_(r0\.log|r1\.log|meta\.txt)$", f):
                problems.append(f"stray file {cfg}/{f}")
        for s in metas:
            for suf in ("_r0.log", "_r1.log"):
                if s + suf not in files:
                    problems.append(f"missing {cfg}/{s}{suf}")
            r = parse_trial(os.path.join(d, s))
            if r["cfg"] != cfg:
                problems.append(f"{s} in folder {cfg}")
            rows.append(r)
    keys = sorted({f"{r['cell']}@{r['cfg']}" for r in rows})
    P(f"- trial files found: {len(rows)} trials (meta + r0 + r1 each) in {len(keys)} cell keys; "
      f"file problems: {problems if problems else 'none'}")
    by_key = {}
    for r in rows:
        by_key.setdefault(f"{r['cell']}@{r['cfg']}", []).append(r)
    mism_plan = []
    for k in sorted(set(plan) | set(by_key)):
        got = len(by_key.get(k, []))
        ks = sorted(r["x_k"] for r in by_key.get(k, []))
        if got != plan.get(k) or ks != list(range(1, got + 1)):
            mism_plan.append(f"{k}: planned {plan.get(k)}, found {got} {ks}")
    P(f"- trial set against section 7: {'matches (every key, numbering n1..nN without gaps)' if not mism_plan else mism_plan}")
    dates = sorted(r["x_date"] for r in rows)
    P(f"- trial start stamps (meta `date`): {dates[0]} to {dates[-1]}; any before the pre-registration "
      f"{PREREG_TIME}: {sum(1 for x in dates if x < PREREG_TIME)}")
    pil = glob.glob(os.path.join(os.path.dirname(RES), os.path.basename(RES) + "_pilot", "*", "*_meta.txt"))
    pd = sorted(read_meta(p).get("date", "") for p in pil)
    P(f"- pilot folder: {len(pil)} trials, {pd[0] if pd else ''} to {pd[-1] if pd else ''} (not read further, not scored)")
    P(f"- log lines without the receipt-time prefix: {sum(r['x_unprefixed'] for r in rows)}")
    P(f"- SUMMARY lines per rank log: {sorted(set((r['x_nsum_r0'], r['x_nsum_r1']) for r in rows))} "
      f"(pairs r0,r1 seen)")
    for col in ("timeout", "abort_ret", "abort_hang"):
        diff = sum(1 for r in rows for k in (0, 1) if r[f"{col}_r{k}"] != r[f"x_{col}_anch_r{k}"])
        P(f"- `{col}` substring count equals the anchored driver-line count in every rank log: {diff == 0}")

    # ---------------- exclusions and configuration
    P("\n## Exclusions (section 8) and configuration check\n")
    excl = {}
    for r in rows:
        r["x_excl"] = exclusion(r)
        r["x_cfgbad"] = config_check(r)
        if r["x_excl"]:
            excl.setdefault(f"{r['cell']}@{r['cfg']}", []).append((r["trial"], r["x_excl"]))
    nsc = sum(1 for r in rows if not r["x_excl"])
    P(f"- trials: {len(rows)}; excluded: {len(rows) - nsc}; scored: {nsc}")
    P(f"- exclusions by key: {excl if excl else 'none'}")
    bad = [(r["stem"], r["x_cfgbad"]) for r in rows if r["x_cfgbad"]]
    P(f"- configuration-check failures: {bad if bad else 'none'}")
    P(f"- launch failures: {sum(r['launch_fail'] for r in rows)}; hook lines per injected trial: "
      f"{sorted(set(r['inj_r%d' % INJ_RANK[r['cell']]] for r in rows if r['cell'] in INJ_RANK))}; "
      f"hook lines in kill and fault-free trials: {sum(r['inj_r0'] + r['inj_r1'] for r in rows if r['cell'] not in INJ_RANK)}")
    kr = [r for r in rows if r["cell"] == "kill"]
    P(f"- kill trials: {len(kr)}, PID-checked kill sent: {sum(r['kill_ok'] for r in kr)}, survivor iterations done "
      f"before its end {rng([r['ok_r0'] for r in kr], '%d')} (min must be >= 1000), kill ssh round trip "
      f"{rng([r['kill_rtt_ms'] for r in kr], '%.1f')} ms")
    P(f"- `nb_ct` left after a trial (meta left_after != 0,0): {sum(1 for r in rows if r['left_after'] != '0,0')}; "
      f"before a trial: {sum(1 for r in rows if r['left_before'] != '0,0')}; wall cap reached: "
      f"{sum(r['wallcap'] for r in rows)}")
    scored = {k: [r for r in v if not r["x_excl"]] for k, v in by_key.items()}

    # ---------------- predictions
    P("\n## Predictions (own evaluator)\n")
    cols = set(rows[0].keys())
    ev = Ev(scored, cols)
    verdicts = {}
    P("hits = trials that conform to the prediction (for a `count(E) == 0` rule, the trials where E is false; for any "
      "other count rule, the trials where E is true). count(E) is the raw value the rule compares.\n")
    P("| id | cell key | n (planned) | hits | count(E) | rule | non-conforming trials | cell result | verdict |")
    P("|---|---|--:|--:|--:|---|---|---|---|")
    for p in csv.DictReader(open(os.path.join(STUDY, "predictions.csv"))):
        cells = p["cells"].split(";")
        acc = p["acceptance"].strip()
        per = acc.startswith("per cell:")
        expr = acc[len("per cell:"):].strip() if per else acc
        short = [c for c in cells if len(scored.get(c, [])) != plan.get(c)]
        if short:
            verdicts[p["id"]] = "insufficient data"
            P(f"| {p['id']} | {', '.join(cells)} | | | | | | short: {short} | insufficient data |")
            continue
        if "count(" in expr:
            ok_all = True
            targets = cells if per else [cells[0]]
            if not per and len(cells) > 1:
                raise SystemExit(f"{p['id']}: count() over several cells without 'per cell:'")
            rule = re.sub(r"^count\(.*\)\s*", "count(E) ", expr, flags=re.S)
            for c in targets:
                res = ev.run(expr, c)
                n_true, conf, nonconf = ev.count_inner(expr, c)
                ok_all &= bool(res)
                P(f"| {p['id']} | {c} | {len(scored[c])} ({plan[c]}) | {len(conf)} | {n_true} | {rule} | "
                  f"{', '.join(nonconf) if nonconf else '-'} | {'holds' if res else 'fails'} | |")
            verdicts[p["id"]] = "holds" if ok_all else "fails"
        else:
            res = bool(ev.run(expr, None))
            verdicts[p["id"]] = "holds" if res else "fails"
            col = re.search(r"median\((\w+),", expr).group(1)
            for c in cells:
                vals = [r[col] for r in scored[c]]
                P(f"| {p['id']} | {c} | {len(scored[c])} ({plan[c]}) | | median {col} "
                  f"{ev.run(f'median({col}, {chr(34)}{c}{chr(34)})', None):.4f} | | values {rng(vals, '%.4f')} | | |")
        P(f"| **{p['id']}** | | | | | | | | **{verdicts[p['id']]}** |")
    vc = {}
    for v in verdicts.values():
        vc[v] = vc.get(v, 0) + 1
    P(f"\nverdicts: {vc} over {len(verdicts)} predictions")
    P(f"holds: {[k for k, v in verdicts.items() if v == 'holds']}")
    P(f"fails: {[k for k, v in verdicts.items() if v == 'fails']}")

    # ---------------- key numbers
    P("\n## Key numbers per cell key [measured]\n")
    P("Times are receipt times on rain's CLOCK_MONOTONIC minus the fault time (first hook line received; for kill, "
      "the moment the runner sent the kill). Ranges are min–max over the scored trials of that one cell key.\n")
    order = ["sqp", "rqp", "kill", "slbc", "slar"]
    P("| key | n | outcomes | faulting-side app error (rank: code, ms) | other rank's app error (code, ms) | "
      "first CQE status r0/r1 | fatal 'No functional devices left' r0/r1 | stock CQE lines r0/r1 | Stage 2 recovery | "
      "MISMATCH lines (before timeout) |")
    P("|---|--:|---|---|---|---|---|---|---|---|")
    for c in order:
        for cfg in CFGS:
            k = f"{c}@{cfg}"
            if k not in scored:
                continue
            R = scored[k]
            oc = {}
            for r in R:
                oc[r["outcome"]] = oc.get(r["outcome"], 0) + 1
            fr = INJ_RANK.get(c, 0)
            orank = 1 - fr
            codes_f = sorted(set(str(r[f"errcode_r{fr}"]) for r in R))
            codes_o = sorted(set(str(r[f"errcode_r{orank}"]) for r in R))
            n_f = sum(1 for r in R if r[f"err_r{fr}"])
            n_o = sum(1 for r in R if r[f"err_r{orank}"])
            wc = "%s / %s" % (sorted(set(str(r["wc_status_r0"]) for r in R)), sorted(set(str(r["wc_status_r1"]) for r in R)))
            fat = "%s / %s" % (sum(1 for r in R if r["fatal_nfd_r0"]), sum(1 for r in R if r["fatal_nfd_r1"]))
            sto = "%s / %s" % (sum(1 for r in R if r["stock_cqe_r0"]), sum(1 for r in R if r["stock_cqe_r1"]))
            if CFG_BUNDLE[cfg] == "s2":
                s2 = "%d/%d trials, send-comm total %s ms (median %s)" % (
                    sum(1 for r in R if r["s2_rec"] >= 1), len(R), rng([r["s2_rec_ms"] for r in R]),
                    fmtv(med([r["s2_rec_ms"] for r in R])))
            else:
                s2 = "n/a"
            P(f"| {k} | {len(R)} | {oc} | r{fr}: {n_f}/{len(R)} {codes_f} {rng([r[f'dt_err_r{fr}'] for r in R])} "
              f"(median {fmtv(med([r[f'dt_err_r{fr}'] for r in R]))}) | r{orank}: {n_o}/{len(R)} {codes_o} "
              f"{rng([r[f'dt_err_r{orank}'] for r in R], '%.1f')} | {wc} | {fat} | {sto} | {s2} | "
              f"{sum(r['mism'] for r in R)} ({sum(r['mism_pre_to'] for r in R)}) |")

    P("\n### How each rank ended, per cell key [measured]\n")
    P("| key | rank 0 end (rc: n) | rank 1 end (rc: n) | grace kill r0/r1 | TIMEOUT r0/r1 (ms after fault) | "
      "abort returned r0/r1 | ABORT-HANG r0/r1 |")
    P("|---|---|---|---|---|---|---|")
    for c in order:
        for cfg in CFGS:
            k = f"{c}@{cfg}"
            if k not in scored:
                continue
            R = scored[k]
            rcs = lambda col: {int(x): sum(1 for r in R if r[col] == x) for x in sorted(set(r[col] for r in R))}  # noqa
            P(f"| {k} | {rcs('rc0')} | {rcs('rc1')} | {sum(r['grace_kill_r0'] for r in R)}/{sum(r['grace_kill_r1'] for r in R)} | "
              f"{sum(1 for r in R if r['timeout_r0'])} ({rng([r['dt_to_r0'] for r in R], '%.1f')}) / "
              f"{sum(1 for r in R if r['timeout_r1'])} ({rng([r['dt_to_r1'] for r in R], '%.1f')}) | "
              f"{sum(1 for r in R if r['abort_ret_r0'])}/{sum(1 for r in R if r['abort_ret_r1'])} | "
              f"{sum(1 for r in R if r['abort_hang_r0'])}/{sum(1 for r in R if r['abort_hang_r1'])} |")

    # kill details
    P("\n### Peer kill [measured]\n")
    for cfg in ("off", "fo", "forec", "s2on", "s2off"):
        R = scored[f"kill@{cfg}"]
        P(f"- kill@{cfg} (n={len(R)}): survivor rank 0 outcome {sorted(set(r['outcome'] for r in R))}; app error on "
          f"rank 0 in {sum(1 for r in R if r['err_r0'])}; ms from kill request to rank 0's error "
          f"{rng([r['dt_err_r0'] for r in R])}, to its TIMEOUT {rng([r['dt_to_r0'] for r in R], '%.1f')}; ms from the "
          f"kill ssh command's return to rank 0's error {rng([r['x_kill_after_done_ms'] for r in R])}; ms from the FIN "
          f"line to rank 0's error {rng([(r['x_t_err_r0'] - r['x_t_fin_r0']) * 1e3 for r in R if r['x_t_fin_r0'] and r['x_t_err_r0']])}; FIN lines on "
          f"rank 0 in {sum(1 for r in R if r['s2_fin_r0'])} trials; survivor iterations before the end "
          f"{rng([r['ok_r0'] for r in R], '%d')}; kill ssh round trip {rng([r['kill_rtt_ms'] for r in R], '%.1f')} ms")

    # silent recv-QP in 2.23.4 flag off: rqp@s2off
    P("\n### 2.23.4 recv-QP fault with recovery off: wrong data on rank 0 (rqp@s2off) [measured]\n")
    R = scored["rqp@s2off"]
    for r in R:
        d = r["x_mism_detail_r0"]
        P(f"- {r['trial']}: rank 1 error {r['errcode_r1']} {fmtv(r['dt_err_r1'])} ms after the hook; rank 0 MISMATCH "
          f"lines {r['mism_r0']}"
          + (f" (iter {d[0]['iter']}, {d[0]['count']} of 4194304 elements wrong, first index {d[0]['first']}, got "
             f"{d[0]['got']} expected {d[0]['expect']}) {fmtv(r['dt_mism_r0'])} ms after the hook, "
             f"{fmtv(r['dt_mism_r0'] - r['dt_err_r1'])} ms after rank 1's error" if d else "")
          + f"; rank 0 app error: {r['err_r0']}; rank 0 first CQE status {r['wc_status_r0']} "
            f"{fmtv(r['x_dt_wc_r0'], '%.1f')} ms after the hook; rank 1 MISMATCH "
            f"{r['mism_r1']}; Stage 2 recovered lines {r['s2_rec']}; rc {int(r['rc0'])}/{int(r['rc1'])}; "
            f"ABORT-HANG {r['abort_hang_r0']}/{r['abort_hang_r1']}")
    allm = [d for r in rows for k in (0, 1) for d in r[f"x_mism_detail_r{k}"]]
    P(f"- MISMATCH lines in the whole main run: {len(allm)}, in cell keys "
      f"{sorted(set(r['cell'] + '@' + r['cfg'] for r in rows if r['mism']))}")

    # silent faults, per side
    P("\n### Silent recv-QP fault [measured]\n")
    for c in ("slbc", "slar"):
        for cfg in ("off", "fo", "forec", "s2on"):
            R = scored[f"{c}@{cfg}"]
            P(f"- {c}@{cfg} (n={len(R)}): rank 1 app error {sum(1 for r in R if r['err_r1'])}/{len(R)}, "
              f"{rng([r['dt_err_r1'] for r in R])} ms; rank 1 first CQE status {sorted(set(str(r['wc_status_r1']) for r in R))}; "
              f"rank 0 app error {sum(1 for r in R if r['err_r0'])}/{len(R)}, {rng([r['dt_err_r0'] for r in R], '%.1f')} ms, "
              f"rank 0 first CQE status {sorted(set(str(r['wc_status_r0']) for r in R))}; rank 0 grace-killed "
              f"{sum(r['grace_kill_r0'] for r in R)}; Stage 2 recovered {sum(1 for r in R if r['s2_rec'])} "
              f"(send-comm total {rng([r['s2_rec_ms'] for r in R])} ms, recovery line "
              f"{rng([r['x_s2_rec_dt'] for r in R], '%.1f')} ms after the hook); silent drain lines "
              f"{sum(1 for r in R if r['x_s2_silent_drain'])}; MISMATCH {sum(r['mism'] for r in R)} "
              f"(before a timeout {sum(r['mism_pre_to'] for r in R)}); rank 1 failing iteration "
              f"{rng([r['ok_r1'] for r in R if r['err_r1']], '%d')}")

    # resiliency activity
    P("\n### Did failover or recovery code act? [measured]\n")
    n232 = [r for r in rows if CFG_BUNDLE[r["cfg"]] == "n232"]
    fo_rows = [r for r in rows if r["cfg"] in ("fo", "forec")]
    P(f"- `prec_activity` lines (the seven patterns of 3.1) over all {len(rows)} trials: "
      f"{sum(r['prec_activity_r0'] + r['prec_activity_r1'] for r in rows)}")
    P(f"- wider net (non-fatal branch, device marked failed, recovery queue, port recovery start/success/failure, QP "
      f"replacement, probes, sender/receiver error handlers, unsupported status): "
      f"{sum(r['x_wide_r0'] + r['x_wide_r1'] for r in rows)} lines")
    qp_fo = [r for r in fo_rows if r["cell"] in INJ_RANK]
    P(f"- failover-on QP-fault trials with a fatal 'No functional devices left' line on the faulting rank: "
      f"{sum(1 for r in qp_fo if r['fatal_nfd_r%d' % INJ_RANK[r['cell']]] > 0)} of {len(qp_fo)}; failover-on kill "
      f"trials with any fatal line: {sum(1 for r in fo_rows if r['cell'] == 'kill' and r['fatal_nfd_r0'] + r['fatal_nfd_r1'])} "
      f"of {sum(1 for r in fo_rows if r['cell'] == 'kill')}")
    P(f"- total fatal lines {sum(r['fatal_nfd_r0'] + r['fatal_nfd_r1'] for r in rows)}, in configurations "
      f"{sorted(set(r['cfg'] for r in rows if r['fatal_nfd_r0'] + r['fatal_nfd_r1']))}")
    P(f"- 'Got completion with error' INFO lines (resiliency handler entered) in failover-on INFO trials: "
      f"{sum(r['x_got_cqe_with_error_info_r0'] + r['x_got_cqe_with_error_info_r1'] for r in fo_rows)}; in other "
      f"configurations: {sum(r['x_got_cqe_with_error_info_r0'] + r['x_got_cqe_with_error_info_r1'] for r in rows if r['cfg'] not in ('fo', 'forec'))}")
    P(f"- stock CQE lines in failover-on trials: {sum(r['stock_cqe_r0'] + r['stock_cqe_r1'] for r in fo_rows)}")
    unpaired = [(r["stem"], k) for r in rows for k in (0, 1)
                if r[f"x_got_cqe_with_error_info_r{k}"] != r[f"fatal_nfd_r{k}"] and r["cell"] in CELL_INFO]
    P(f"- INFO rank logs where handler-entry lines != fatal lines: {len(unpaired)}")
    brk = {}
    for r in rows:
        for k in (0, 1):
            if r[f"fatal_nfd_r{k}"]:
                key = f"{r['cell']}@{r['cfg']} r{k}"
                brk[key] = brk.get(key, 0) + r[f"fatal_nfd_r{k}"]
    P(f"- fatal lines by key and rank: {brk}")
    cr = [0, 0]
    for r in rows:
        for k in (0, 1):
            for _, s in read_log(os.path.join(RES, r["cfg"], f"{r['stem']}_r{k}.log"))[0]:
                mm = re.search(r"Close request completed for resCtx=\S+ removed (\d+) items", s)
                if mm:
                    cr[0] += 1
                    cr[1] += int(mm.group(1)) > 0
    P(f"- port-recovery close requests: {cr[0]}, with removed items > 0: {cr[1]}")
    P(f"- 2.32.3 trials (off, rec, fo, forec): {len(n232)}")

    # abort
    P("\n### ncclCommAbort [measured]\n")
    P("A rank log 'called abort' when its SUMMARY has rc != 0 (the driver calls ncclCommAbort then).\n")
    for lib in ("n232", "s2"):
        L = [(r, k) for r in rows for k in (0, 1) if CFG_BUNDLE[r["cfg"]] == lib]
        called = [(r, k) for r, k in L if r[f"x_sum_rc_r{k}"] not in (None, 0)]
        ret = [(r, k) for r, k in called if r[f"abort_ret_r{k}"]]
        hang = [(r, k) for r, k in called if r[f"abort_hang_r{k}"]]
        neither = [(r, k) for r, k in called if not r[f"abort_ret_r{k}"] and not r[f"abort_hang_r{k}"]]
        P(f"- {'2.32.3' if lib == 'n232' else '2.23.4 (Stage 2 build)'}: rank logs {len(L)}, abort called "
          f"{len(called)}, returned {len(ret)} ({rng([r[f'x_abort_ret_ms_r{k}'] for r, k in ret], '%.1f')} ms after "
          f"SUMMARY), ABORT-HANG {len(hang)}, neither {len(neither)}"
          + (f" ({sorted(set(r['cell'] + '@' + r['cfg'] + ' r' + str(k) for r, k in neither))})" if neither else ""))
        if hang:
            P(f"  - ABORT-HANG by key: "
              f"{ {kk: sum(1 for r, k in hang if r['cell'] + '@' + r['cfg'] == kk) for kk in sorted(set(r['cell'] + '@' + r['cfg'] for r, k in hang))} }")

    # overhead
    P("\n## Fault-free all-reduce time [measured]\n")
    P("Per run: rank 0's SUMMARY `med_ms` (the driver's upper median of the per-iteration times). Cell value: the "
      "median over the 10 runs (statistics.median, mean of runs 5 and 6 when sorted). Ranges are min–max over the "
      "10 runs of one key.\n")
    itm = sum(1 for r in rows if r["cell"].startswith("ovh") and r["x_itmed_r0"] is not None
              and abs(r["x_itmed_r0"] - r["med_ms_r0"]) > 5e-5)
    P(f"- SUMMARY med_ms_r0 recomputed from the IT lines with the driver's rule: differs in {itm} of "
      f"{sum(1 for r in rows if r['cell'].startswith('ovh'))} runs; IT lines per run "
      f"{sorted(set(r['x_nit_r0'] for r in rows if r['cell'].startswith('ovh')))}")
    hold_of = {}
    for h in sorted(glob.glob(os.path.join(RES, "hold_H*.out"))):
        hn = os.path.basename(h)[5:-4]
        for ln in open(h):
            mm = re.match(r"^(\S+): outcome=", ln)
            if mm:
                hold_of[mm.group(1)] = hn
    P("\n| size | cfg | n | median of med_ms_r0 (ms) | min–max over runs | H1 median | H2 median | rank 1 median |")
    P("|---|---|--:|--:|---|--:|--:|--:|")
    medians = {}
    for c in ("ovh64k", "ovh16m"):
        for cfg in ("off", "fo", "forec", "s2on", "s2off"):
            R = scored[f"{c}@{cfg}"]
            v = [r["med_ms_r0"] for r in R]
            medians[f"{c}@{cfg}"] = statistics.median(v)
            h1 = [r["med_ms_r0"] for r in R if hold_of.get(r["stem"]) == "H1"]
            h2 = [r["med_ms_r0"] for r in R if hold_of.get(r["stem"]) == "H2"]
            P(f"| {c} | {cfg} | {len(v)} | {statistics.median(v):.4f} | {min(v):.4f}–{max(v):.4f} | "
              f"{statistics.median(h1):.4f} | {statistics.median(h2):.4f} | "
              f"{statistics.median([r['med_ms_r1'] for r in R]):.4f} |")
    P("")
    for nm, a, b, lim in (("O1", "ovh16m@fo", "ovh16m@off", 0.02), ("O2", "ovh64k@fo", "ovh64k@off", 0.05),
                          ("O3 16 MiB", "ovh16m@forec", "ovh16m@fo", 0.02), ("O3 64 KiB", "ovh64k@forec", "ovh64k@fo", 0.02),
                          ("O4 16 MiB", "ovh16m@s2on", "ovh16m@s2off", 0.02),
                          ("O4 64 KiB", "ovh64k@s2on", "ovh64k@s2off", 0.03)):
        d = (medians[a] - medians[b]) / medians[b]
        lo = lambda k: sorted(r["med_ms_r0"] for r in scored[k])[4]  # noqa: E731
        hi = lambda k: sorted(r["med_ms_r0"] for r in scored[k])[5]  # noqa: E731
        dlo, dhi = (lo(a) - lo(b)) / lo(b), (hi(a) - hi(b)) / hi(b)
        P(f"- {nm}: {a} {medians[a]:.4f} ms vs {b} {medians[b]:.4f} ms: {100 * d:+.2f} % (limit ±{100 * lim:.0f} %): "
          f"{'within' if abs(d) <= lim else 'OUTSIDE'}; with lower/upper medians instead: {100 * dlo:+.2f} % / "
          f"{100 * dhi:+.2f} %")
    # per-hold differences for O4
    for c, lim in (("ovh16m", 0.02), ("ovh64k", 0.03)):
        for h in ("H1", "H2"):
            a = statistics.median([r["med_ms_r0"] for r in scored[f"{c}@s2on"] if hold_of.get(r["stem"]) == h])
            b = statistics.median([r["med_ms_r0"] for r in scored[f"{c}@s2off"] if hold_of.get(r["stem"]) == h])
            P(f"  - {c} s2on vs s2off inside hold {h} only (5 runs each): {100 * (a - b) / b:+.2f} %")
    for c in ("ovh64k",):
        for cfg in ("s2on", "s2off", "off"):
            R = sorted(scored[f"{c}@{cfg}"], key=lambda x: x["x_k"])
            P(f"  - {c}@{cfg} med_ms_r0 in run order (n1..n10; n1-n5 in H1, n6-n10 in H2): "
              f"{', '.join('%.4f' % r['med_ms_r0'] for r in R)}; holds "
              f"{''.join(hold_of.get(r['stem'], '?')[1:] for r in R)}")
    # spread
    for c in ("ovh64k", "ovh16m"):
        for cfg in ("off", "s2off"):
            v = [r["med_ms_r0"] for r in scored[f"{c}@{cfg}"]]
            P(f"- run-to-run spread (max-min)/median of {c}@{cfg}: {100 * (max(v) - min(v)) / statistics.median(v):.1f} %")
    # ok on fault-free runs
    ff = [r for r in rows if r["cell"].startswith("ovh")]
    P(f"- fault-free runs: {len(ff)}, outcome {sorted(set(r['outcome'] for r in ff))}, rc {sorted(set((r['rc0'], r['rc1']) for r in ff))}, "
      f"ok==iters on both ranks {sum(1 for r in ff if r['ok_r0'] == r['iters_r0'] and r['ok_r1'] == r['iters_r1'])}")

    # ---------------- hold logs
    P("\n## Comparison with the per-trial lines of the hold outputs\n")
    byst = {r["stem"]: r for r in rows}
    seen, diffs = set(), []
    RE_H = re.compile(r"^(\S+): outcome=(\S+) rc=(\S+)/(\S+) inj=(\S+)/(\S+) err=(\S*)/(\S*) dt_err=(\S*)/(\S*) "
                      r"wall=(\S+) left=(\S+) ?(.*)$")
    hold_keys = {}
    for h in sorted(glob.glob(os.path.join(RES, "hold_H*.out")), key=lambda x: int(re.search(r"H(\d+)", x).group(1))):
        hn = os.path.basename(h)[5:-4]
        for ln in open(h):
            mm = RE_H.match(ln.rstrip("\n"))
            if not mm:
                continue
            g = mm.groups()
            st = g[0]
            seen.add(st)
            hold_keys.setdefault(hn, {})
            kk = st.split("_n")[0].replace(".", "@")
            hold_keys[hn][kk] = hold_keys[hn].get(kk, 0) + 1
            r = byst.get(st)
            if r is None:
                diffs.append(f"{hn} {st}: no trial files")
                continue
            mine = {"outcome": r["outcome"], "rc": f"{int(r['rc0'])}/{int(r['rc1'])}",
                    "inj": f"{r['inj_r0']}/{r['inj_r1']}",
                    "err": f"{r['err_r0'] or ''}{r['errcode_r0'] or ''}/{r['err_r1'] or ''}{r['errcode_r1'] or ''}",
                    "wall": r["wall_s"], "left": r["left_after"], "why": r["x_cfgbad"]}
            theirs = {"outcome": g[1], "rc": f"{g[2]}/{g[3]}", "inj": f"{g[4]}/{g[5]}", "err": f"{g[6]}/{g[7]}",
                      "wall": g[10], "left": g[11], "why": g[12].strip()}
            for f in mine:
                if str(mine[f]) != str(theirs[f]):
                    diffs.append(f"{hn} {st} {f}: hold line {theirs[f]!r}, recount {mine[f]!r}")
            for k, gv in ((0, g[8]), (1, g[9])):
                mv = r[f"dt_err_r{k}"]
                if (gv == "") != (mv is None) or (mv is not None and abs(float(gv) - mv) > 0.0015):
                    diffs.append(f"{hn} {st} dt_err_r{k}: hold line {gv!r}, recount {fmtv(mv)}")
    P(f"- per-trial lines in hold_H1..H15.out: {len(seen)}; trials without a hold line: "
      f"{sorted(set(byst) - seen) if set(byst) - seen else 'none'}")
    P(f"- fields compared: outcome, rc, inj, err+errcode, dt_err (to 0.0015 ms), wall, left, configuration status")
    P(f"- differences: {len(diffs)}")
    for d in diffs:
        P(f"  - {d}")
    P("\n| hold | keys run (trials) |")
    P("|---|---|")
    for hn in sorted(hold_keys, key=lambda x: int(x[1:])):
        P(f"| {hn} | {', '.join(f'{k} {v}' for k, v in hold_keys[hn].items())} |")
    P("\n| hold | lock acquired | snapshot before | snapshot after | exited | hold rc line |")
    P("|---|---|---|---|---|---|")
    sec = lambda x: int(x[0:2]) * 3600 + int(x[3:5]) * 60 + int(x[6:8])  # noqa: E731
    tot_lock, tot_snap = 0, []
    for h in sorted(glob.glob(os.path.join(RES, "hold_H*.out")), key=lambda x: int(re.search(r"H(\d+)", x).group(1))):
        txt = open(h).read()
        g = lambda rx: (re.search(rx, txt, re.M).group(1) if re.search(rx, txt, re.M) else "?")  # noqa: E731
        cells_h = [g(r"^\S+ (\S+) \[nb-H\d+\] lock acquired"), g(r"^== before-H\d+ \S+ (\S+)"),
                   g(r"^== after-H\d+ \S+ (\S+)"), g(r"^\S+ (\S+) \[nb-H\d+\] command exited"),
                   g(r"\[nb-H\d+\] command exited (rc=\d+)")]
        tot_lock += sec(cells_h[3]) - sec(cells_h[0])
        tot_snap.append(sec(cells_h[2]) - sec(cells_h[1]))
        P(f"| {os.path.basename(h)[5:-4]} | " + " | ".join(cells_h) + " |")
    P(f"\n- summed hold time, lock acquired to exit: {tot_lock / 60:.1f} min; snapshot-to-snapshot per hold "
      f"{min(tot_snap) // 60}:{min(tot_snap) % 60:02d}–{max(tot_snap) // 60}:{max(tot_snap) % 60:02d} min")
    newl = {os.path.basename(f)[9:-4]: sum(1 for _ in open(f)) for f in glob.glob(os.path.join(RES, "mlx5_new_H*.txt"))}
    P(f"\n- new mlx5 kernel lines per hold: { {k: v for k, v in sorted(newl.items(), key=lambda x: int(x[0][1:])) if v} } "
      f"(other holds 0); STOP files: {[f for f in os.listdir(RES) if f.startswith('STOP')] or 'none'}")
    cmd = set()
    for h in glob.glob(os.path.join(RES, "hold_H*.out")):
        for ln in open(h):
            if "cmd_err lines" in ln or "fwcmd failed sum" in ln:
                cmd.add(ln.strip())
    P(f"- mlx5 command-error and firmware-command-failure lines in every snapshot: {sorted(cmd)}")
    # snapshots against EXPERIMENT.md 5 (bundle md5, ports, kernels)
    md5s, ports, kern = set(), set(), set()
    snaps = glob.glob(os.path.join(RES, "snap_*-H*.txt"))
    for f in snaps:
        for ln in open(f):
            mm = re.match(r"^(rain|sunny) bundle: ([0-9a-f]{32})  (\S+)$", ln.strip())
            if mm:
                md5s.add((mm.group(1), mm.group(3), mm.group(2)[:8]))
            mm = re.match(r"^(rain|sunny): (mlx5_\d) fw (\S+) port1 \d: (\w+)$", ln.strip())
            if mm:
                ports.add(mm.groups())
            mm = re.match(r"^(rain|sunny): kernel (\S+)$", ln.strip())
            if mm:
                kern.add(mm.groups())
    gpu = sum(1 for f in snaps for ln in open(f) if re.match(r"^(rain|sunny) gpu: ", ln))
    P(f"- GPU compute processes listed in the snapshots: {gpu}")
    P(f"- hold snapshots read: {len(snaps)}; distinct bundle md5 (node, file, first 8 hex): {sorted(md5s)}")
    P(f"- distinct port states: {sorted(ports)}; kernels: {sorted(kern)}")
    nd = set()
    for r in rows:
        if r["cell"] in CELL_INFO:
            for k in (0, 1):
                for _, s in read_log(os.path.join(RES, r["cfg"], f"{r['stem']}_r{k}.log"))[0]:
                    mm = re.search(r"Made virtual device \[\d+\] name=(\S+) .*ndevs=(\d+)", s)
                    if mm:
                        nd.add((k, mm.group(1), mm.group(2)))
    P(f"- 'Made virtual device' lines in INFO trials (rank, device, ndevs): {sorted(nd)}")


if __name__ == "__main__":
    main()
