#!/usr/bin/env python3
"""gin-pair-reset: independent recount from the raw per-trial files.

usage: recount.py [<results dir>]        (default: ../results/20261008 next to this file)

Written for QA without reading or running score.py, without rows_pr.py output, SCORE.md, trials_scored.csv or the
trials_*.csv files. It imports nothing from ../scripts/ts2/rows.py, ../s2_close/rows_extra.py or ./rows_pr.py: every
column is re-derived here from <stem>_meta.txt, <stem>_r{0,1}.kv, <stem>_r{0,1}.log, <stem>_kill.out and
<stem>_lat_raw.csv.gz, following the definitions of EXPERIMENT.md 3.1 (and ../s2_close/EXPERIMENT.md 3.1, 3.2 for the
columns and the grammar it inherits). The acceptance strings are read verbatim from ../predictions.csv and evaluated
with an evaluator written here (blank -> NA, any comparison or arithmetic with NA is false).

Prints: frozen-file checks, the trial set and exclusions, setup checks, the per-prediction table, cell-level detail
(scope paths, gate epochs, the dual-context window, Commit and round times, conflict sequence, latency recomputed from
the per-iteration file), and the safety records per hold.
"""
import csv, glob, gzip, hashlib, os, re, statistics, subprocess, sys
from collections import Counter, OrderedDict, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
RES = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(STUDY, "results", "20261008")
SUBDIRS = ["lat", "rep_pr", "dual", "conflict"]

# ---------------------------------------------------------------- parsing


def kv(path):
    """key=value lines (values may hold spaces, e.g. tx_rc=no error). Later keys overwrite earlier ones."""
    d = {}
    if not os.path.exists(path):
        return d
    for line in open(path, errors="replace"):
        line = line.rstrip("\n")
        for m in re.finditer(r"(?:^|(?<= ))(\w+)=(.*?)(?= \w+=|$)", line):
            d[m.group(1)] = m.group(2).strip().strip('"')
    return d


RE_FIRE = re.compile(r"GIN/FAULT: GDAKI fault fired.*?moved (\d+)/(\d+) GIN QP\(s\) to ERR(?: context=(\d+))? "
                     r"fire_mono_ms=([\d.]+) done_mono_ms=([\d.]+)")
RE_ARMED = re.compile(r"GIN/FAULT: GDAKI fault hook armed \((\w+):(-?\d+)\)")
RE_DEC = re.compile(r"GIN/TS: rank (\d+): round (\d+) peer (\d+) scope=(0x[0-9a-f]+) qps=(\d+) reason=(\w+) "
                    r"mono_ms=([\d.]+)")
RE_DECL = re.compile(r'GIN/TS: declined rank=\d+ peer=\d+ reason="([^"]*)"')
RE_PR = re.compile(r"GIN/TS: pair reset=(\d+) rank=(\d+)")
RE_CONF = re.compile(r"GIN/TS: rank=(\d+) scope conflict: REQ round (\d+) from rank (\d+) scope=(0x[0-9a-f]+), "
                     r"ours scope=(0x[0-9a-f]+) round (\d+); ours is requeued as a full reset")
RE_EP = re.compile(r"GIN/TS: rank (\d+) gate epochs to rank (\d+): \[([\d,]*)\]")
RE_STALL = re.compile(r"GIN/TS: TEST stall rank=(\d+) (\d+) ms after quiesce mono_ms=([\d.]+)")
RE_TD = re.compile(r"GIN/TS: communicator teardown rank=\d+: .*?\(round_in_progress=(\d+) queued=(\d+) "
                   r"helper_dead=(\d+) rounds=(\d+) recovered=(\d+) declined=(\d+)\)")


def fields(s):
    """key=value tokens of a WARN line (bracketed lists kept whole)."""
    return dict(re.findall(r"([\w/]+)=(\[[^\]]*\]|\"[^\"]*\"|\S+)", s))


def scan(path):
    o = dict(fires=[], armed=[], q4=[], dec=[], rec=[], decl=[], pr=[], conf=[], ep=[], stall=[], td=[], ts_on=0, ua=0,
             trig_miss=0, rec_aborted=0, tie_kept=0, yielded=0, simreq=0, bind=0, sockclose=[], order=[], text="")
    if not os.path.exists(path):
        o["missing"] = 1
        return o
    txt = open(path, errors="replace").read()
    o["text"] = txt
    if "bind: Address already in use" in txt:
        o["bind"] = 1
    for line in txt.splitlines():
        w = line.split("NCCL WARN ", 1)[1] if "NCCL WARN " in line else line
        m = RE_FIRE.search(w)
        if m:
            o["fires"].append(dict(moved=int(m.group(1)), of=int(m.group(2)), ctx=m.group(3),
                                   fire=float(m.group(4)), done=float(m.group(5))))
            o["order"].append(("fire", float(m.group(4))))
            continue
        m = RE_ARMED.search(w)
        if m:
            o["armed"].append((m.group(1), int(m.group(2))))
            continue
        if "GIN/FAULT: shot 1 trigger not reached" in w:
            o["trig_miss"] += 1
        if "device-classified error CQE" in w:
            f = fields(w)
            o["q4"].append(f)
            o["order"].append(("q4", float(f["mono_ms"])))
            continue
        m = RE_DEC.search(w)
        if m:
            d = dict(rank=int(m.group(1)), round=int(m.group(2)), peer=int(m.group(3)), scope=m.group(4),
                     qps=int(m.group(5)), reason=m.group(6), mono=float(m.group(7)))
            o["dec"].append(d)
            o["order"].append(("dec", d["mono"]))
            continue
        if "GIN/TS: recovered " in w:
            f = fields(w)
            o["rec"].append(f)
            t = f.get("t_start") or f.get("t_req")
            o["order"].append(("rec_" + f.get("role", "?"), float(t) if t else None))
            continue
        m = RE_DECL.search(w)
        if m:
            o["decl"].append(m.group(1))
            continue
        m = RE_PR.search(w)
        if m:
            o["pr"].append(int(m.group(1)))
            continue
        m = RE_CONF.search(w)
        if m:
            o["conf"].append(m.groups())
            o["order"].append(("conflict", None))
            continue
        m = RE_EP.search(w)
        if m:
            o["ep"].append([int(x) for x in m.group(3).split(",") if x != ""])
            continue
        m = RE_STALL.search(w)
        if m:
            o["stall"].append((int(m.group(1)), int(m.group(2)), float(m.group(3))))
            continue
        m = RE_TD.search(w)
        if m:
            o["td"].append(tuple(int(x) for x in m.groups()))
            continue
        if "GIN/TS: transparent recovery ON" in w:
            o["ts_on"] += 1
        elif "GIN/TS: user devComm abort flag set" in w:
            o["ua"] += 1
        elif "GIN/REC: recovery aborted" in w:
            o["rec_aborted"] += 1
            o["order"].append(("rec_aborted", None))
        elif "the lower rank keeps the initiator role" in w:
            o["tie_kept"] += 1
            o["simreq"] += 1
        elif "the higher rank yields its round" in w:
            o["yielded"] += 1
            o["simreq"] += 1
        elif "socket to rank" in w and "closed cause=" in w:
            o["sockclose"].append(w.strip())
    return o


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def rank_ok(k, iters, sender, receiver):
    """the transparent definition of ../scripts/ts2/rows.py (docstring): outcome ok and no async error; a sender ran
    every iteration without error; a receiver got every iteration, 0 bad slots (device, host), exact final signals."""
    if k.get("outcome") != "ok" or k.get("async_first") != "none":
        return False
    if sender and not (k.get("tx_done") == str(iters) and k.get("tx_rc") == "no error"):
        return False
    if receiver and not (k.get("rx_done") == str(iters) and k.get("rx_rc") == "no error" and
                         k.get("dev_bad_slots") == "0" and k.get("host_bad_slots") == "0" and
                         k.get("signal_exact") == "1"):
        return False
    return True


def trial(stem):
    m = kv(stem + "_meta.txt")
    k0, k1 = kv(stem + "_r0.kv"), kv(stem + "_r1.kv")
    l0, l1 = scan(stem + "_r0.log"), scan(stem + "_r1.log")
    kill = kv(stem + "_kill.out")
    iters = int(m.get("iters", "0"))
    bidir = m.get("app") == "bidir"
    off = num(k0.get("clock_offset_ms"))  # rank 1 clock minus rank 0 clock
    r = OrderedDict()
    r["dir"] = os.path.basename(os.path.dirname(stem))
    r["stem"] = os.path.basename(stem)
    r["cell"] = m.get("cell")
    r["build"] = m.get("build")
    r["key"] = "%s@%s" % (r["cell"], r["build"])
    r["n"] = int(m.get("trial", "n0")[1:])
    r["iters"] = iters
    r["r0rc"], r["r1rc"], r["left"] = m.get("r0rc"), m.get("r1rc"), m.get("left")
    r["r0_outcome"], r["r1_outcome"] = k0.get("outcome"), k1.get("outcome")
    r["transparent_ok"] = int(rank_ok(k0, iters, True, bidir) and rank_ok(k1, iters, bidir, True))
    r["decl_r0"], r["decl_r1"] = ";".join(l0["decl"]), ";".join(l1["decl"])
    r["teardown_r0"], r["teardown_r1"] = k0.get("abort_ret"), k1.get("abort_ret")
    r["teardown_ms_r1"] = k1.get("teardown_ms")
    r["lat_p50_us"] = k0.get("lat_p50_us")
    r["q4_class_r0"] = ";".join(q.get("class", "") for q in l0["q4"][:4])
    for rk, lg in (("r0", l0), ("r1", l1)):
        r["rec_init_" + rk] = sum(1 for x in lg["rec"] if x.get("role") == "initiator")
        r["rec_resp_" + rk] = sum(1 for x in lg["rec"] if x.get("role") == "responder")
        r["n_fires_" + rk] = len(lg["fires"])
        r["ts_on_" + rk] = lg["ts_on"]
        r["ua_" + rk] = lg["ua"]
        r["pr_mode_" + rk] = lg["pr"][0] if lg["pr"] else ""
        r["rec_scope_" + rk] = lg["rec"][0].get("scope", "") if lg["rec"] else ""
        r["rec_qps_" + rk] = lg["rec"][0].get("qps", "") if lg["rec"] else ""
        r["n_rec_" + rk] = len(lg["rec"])
        r["inj_ctx_" + rk] = (lg["fires"][0]["ctx"] or "") if lg["fires"] else ""
        ep = lg["ep"][0] if lg["ep"] else []
        for c in range(4):
            r["ep_c%d_%s" % (c, rk)] = ep[c] if c < len(ep) else ""
    r["trigger_miss"] = l0["trig_miss"] + l1["trig_miss"]
    r["bind_fail"] = int(l0["bind"] or l1["bind"])
    r["killed"] = 1 if kill.get("kill_mono_ms") else 0
    d0 = [d for d in l0["dec"] if d["rank"] == 0]
    r["scope_r0"] = d0[0]["scope"] if d0 else ""
    r["scope_reason_r0"] = d0[0]["reason"] if d0 else ""
    i1 = [x for x in l1["rec"] if x.get("role") == "initiator"]
    r["init_qps_r1"] = i1[0].get("qps", "") if i1 else ""
    i0 = [x for x in l0["rec"] if x.get("role") == "initiator"]
    r["commit_us_r0"] = i0[0].get("commit_us", "") if i0 else ""
    r["total_us_r0"] = i0[0].get("total_us", "") if i0 else ""
    r["conflict_r1"] = sum(1 for c in l1["conf"] if c[0] == "1")
    # r1_q4_in_stall (conflict cell only)
    r["r1_q4_in_stall"] = ""
    r["r1_q4_minus_stall_end_ms"] = ""
    if r["cell"] == "pr_bidirf_conflict_b":
        st = [s for s in l0["stall"] if s[0] == 0]
        if st and l1["q4"] and off is not None:
            t, ms = st[0][2], st[0][1]
            q = float(l1["q4"][0]["mono_ms"]) - off
            r["r1_q4_in_stall"] = int(t <= q <= t + ms - 2)
            r["r1_q4_minus_stall_end_ms"] = q - (t + ms - 2)
            r["r1_q4_after_stall_start_ms"] = q - t
    r["dual_r0"], r["dual_r1"] = k0.get("dual", ""), k1.get("dual", "")
    for key in ("dual_win_us", "dual_win_it", "dual_c1_in_win", "dual_c1_max_in_win_us", "dual_c1_end_after_win",
                "dual_c1_max_us", "dual_win_start_gt", "dual_win_end_gt", "dual_c1_last_end_gt", "lat_max_us",
                "lat_max_it", "lat1_max_us", "dual_c0_done", "dual_c1_done"):
        r[key] = k0.get(key, "")
    for key in ("dual_rx_c0_done", "dual_rx_c1_done", "dual_final_signal1", "dual_expected_final1", "final_signal",
                "expected_final", "host_slots"):
        r["r1_" + key] = k1.get(key, "")
    r["_m"], r["_k0"], r["_k1"], r["_l0"], r["_l1"], r["_off"], r["_kill"] = m, k0, k1, l0, l1, off, kill
    # wall time of the first log line (for hold assignment and order)
    mt = re.search(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\]", l0["text"] or l1["text"])
    # (a trial that never reached NCCL has no timestamped line: fall back to its meta file's mtime)
    r["_wall"] = mt.group(1) if mt else __import__("time").strftime(
        "%Y-%m-%d %H:%M:%S", __import__("time").localtime(os.path.getmtime(stem + "_meta.txt")))
    r["_t0"] = num(k0.get("t0_mono_ms"))
    return r


# ---------------------------------------------------------------- acceptance grammar


class NAType:
    """a blank value: every comparison and every arithmetic result with it is false / NA."""
    def _f(self, *a):
        return False
    __lt__ = __le__ = __gt__ = __ge__ = __eq__ = __ne__ = _f

    def _na(self, *a):
        return self
    __add__ = __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = __truediv__ = __rtruediv__ = __abs__ = __neg__ = _na

    def __bool__(self):
        return False

    def __hash__(self):
        return 0

    def __repr__(self):
        return "NA"


NA = NAType()


def val(x):
    if x is None or x == "":
        return NA
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(x)
    except ValueError:
        return x


def has(v, s):
    return isinstance(v, str) and s in v


def nonempty(v):
    return v is not NA


def outer_call(s, name):
    """(start, end, inner) of the first name( ... ) call with balanced parentheses."""
    i = s.find(name + "(")
    if i < 0:
        return None
    j = i + len(name) + 1
    depth = 1
    q = None
    while depth:
        ch = s[j]
        if q:
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        j += 1
    return i, j, s[i + len(name) + 1: j - 1]


def eval_row(expr, row, errs):
    bare = re.sub(r'"[^"]*"', '""', expr)
    ns = {c: val(row.get(c)) for c in re.findall(r"\b([a-z][a-z0-9_]*)\b", bare)
          if c not in ("and", "or", "not", "has", "nonempty", "abs")}
    for c in ns:
        if c not in row:
            raise KeyError("column %s not computed" % c)
    try:
        return bool(eval(expr, {"__builtins__": {}, "has": has, "nonempty": nonempty, "abs": abs}, ns))
    except TypeError as e:
        errs.append("%s: %s" % (row["stem"], e))
        return False


def evaluate(acc, rows_by_key, cells, planned):
    """returns verdict, detail dict. acc is the acceptance string of predictions.csv."""
    detail = {"counts": {}, "medians": {}, "misses": {}, "errs": []}
    per_cell = acc.startswith("per cell:")
    body = acc[len("per cell:"):].strip() if per_cell else acc
    short = [c for c in cells if len(rows_by_key.get(c, [])) < planned[c]]
    if short:
        detail["short"] = {c: len(rows_by_key.get(c, [])) for c in short}
        return "insufficient data", detail
    results = []
    targets = cells if per_cell else [cells[0]]
    for cell in targets:
        s = body
        while True:
            oc = outer_call(s, "count")
            if not oc:
                break
            i, j, inner = oc
            rows = rows_by_key[cell]
            hits = [r for r in rows if eval_row(inner, r, detail["errs"])]
            detail["counts"][cell] = (len(hits), len(rows))
            detail["misses"][cell] = [r["stem"] for r in rows if r not in hits]
            s = s[:i] + str(len(hits)) + s[j:]
        for mm in list(re.finditer(r'median\((\w+), "([^"]+)"\)', s)):
            col, ck = mm.group(1), mm.group(2)
            vs = [val(r.get(col)) for r in rows_by_key[ck]]
            vals = [v for v in vs if isinstance(v, float)]
            med = statistics.median(vals) if vals else NA
            detail["medians"][(col, ck)] = (med, vals, len(vs) - len(vals))
            s = s.replace(mm.group(0), repr(med), 1)
        detail.setdefault("substituted", []).append(s)
        results.append(bool(eval(s, {"__builtins__": {}, "abs": abs, "NA": NA})))
    return ("holds" if all(results) else "fails"), detail


# ---------------------------------------------------------------- study constants (EXPERIMENT.md 7, 8)

PLANNED = {
    "pr_dual_f1c0_b@prd": 10, "pr_dual_f3c0_b@prd": 10, "pr_dual_f1all_b@prd": 10, "pr_bidirf_conflict_b@pr": 10,
    "pr_dual_f1c0_full_b@prd": 5, "pr_dual_none_b@prd": 5,
    "f1_b@pr": 5, "f3_b@pr": 5, "bidirf_sym_b@pr": 5, "mt256_f1_b@pr": 5, "f4_b@pr": 5, "f2rel_b@pr": 5,
    "lat_rc_on_4k@rc": 5, "lat_rc_on_256k@rc": 5, "lat_pr_on_4k@pr": 5, "lat_pr_on_256k@pr": 5,
}
LOCAL_F1 = {"pr_dual_f1c0_b", "pr_dual_f1c0_full_b", "pr_dual_f1all_b", "f1_b", "mt256_f1_b"}
PEER_F3 = {"pr_dual_f3c0_b", "f3_b"}
BOTH = {"pr_bidirf_conflict_b", "bidirf_sym_b"}
KILL = {"f4_b"}
DUAL_C0 = {"pr_dual_f1c0_b", "pr_dual_f1c0_full_b", "pr_dual_f3c0_b"}


def exclusion(r):
    c = r["cell"]
    if r["bind_fail"] == 1:
        return "bind_fail (rendezvous port in use before NCCL init)"
    if c in LOCAL_F1 and r["n_fires_r0"] == 0:
        return "fault not applied (n_fires_r0 == 0)"
    if c in PEER_F3 and r["n_fires_r1"] == 0:
        return "fault not applied (n_fires_r1 == 0)"
    if c in BOTH and (r["n_fires_r0"] == 0 or r["n_fires_r1"] == 0):
        return "fault not applied (a rank's hook did not fire)"
    if r["trigger_miss"] > 0:
        return "fault not applied (trigger_miss)"
    if c in KILL and r["killed"] != 1:
        return "fault not applied (killed != 1)"
    if c in DUAL_C0 and r["dual_c1_end_after_win"] != "1":
        return "condition not applied (dual_c1_end_after_win != 1)"
    if c == "pr_bidirf_conflict_b" and r["r1_q4_in_stall"] != 1:
        return "condition not applied (r1_q4_in_stall != 1)"
    return ""


def setup_problems(r):
    p = []
    c, b = r["cell"], r["build"]
    if r["_m"].get("ts") == "1":
        for k in ("ts_on_r0", "ts_on_r1", "ua_r0", "ua_r1"):
            if r[k] < 1:
                p.append("%s=%s" % (k, r[k]))
    if b in ("pr", "prd"):
        want = 0 if c == "pr_dual_f1c0_full_b" else 1
        for k in ("pr_mode_r0", "pr_mode_r1"):
            if r[k] != want:
                p.append("%s=%r (want %d)" % (k, r[k], want))
    if b == "prd":
        for k in ("dual_r0", "dual_r1"):
            if r[k] != "1":
                p.append("%s=%r" % (k, r[k]))
    want_ctx = {"pr_dual_f1c0_b": ("0", None), "pr_dual_f1c0_full_b": ("0", None), "pr_dual_f3c0_b": (None, "0"),
                "pr_bidirf_conflict_b": ("0", "1"), "pr_dual_f1all_b": ("", None)}.get(c)
    if want_ctx:
        for rk, w in zip(("r0", "r1"), want_ctx):
            if w is not None and r["inj_ctx_" + rk] != w:
                p.append("inj_ctx_%s=%r (want %r)" % (rk, r["inj_ctx_" + rk], w))
    return p


def cell_condition_problems(r):
    """meta against EXPERIMENT.md 7 and cells.sh (bundle per build, env, size, gap, injection instant)."""
    p = []
    m, c, b, k = r["_m"], r["cell"], r["build"], r["n"]
    bundle = m.get("bundle", "")
    if not bundle.endswith("/gin_ts2/" + b):
        p.append("bundle %s for build %s" % (bundle, b))
    inj = 400 + (k * 137) % 700
    exp = {
        "pr_dual_f1c0_b": dict(fault="F1", iters="3000", bytes="4096", gap_us="500", r0env="NCCL_GIN_FAULT_INJECT_CTX=0",
                               r1env="", extra="GIN_TS_DUAL=1", inject=str(inj)),
        "pr_dual_f1c0_full_b": dict(fault="F1", iters="3000", bytes="4096", gap_us="500",
                                    r0env="NCCL_GIN_FAULT_INJECT_CTX=0", r1env="",
                                    extra="GIN_TS_DUAL=1+NCCL_GIN_TS_PAIR_RESET=0", inject=str(inj)),
        "pr_dual_f3c0_b": dict(fault="F3", iters="3000", bytes="4096", gap_us="2000", r0env="",
                               r1env="NCCL_GIN_FAULT_INJECT_CTX=0", extra="GIN_TS_DUAL=1", inject=str(inj)),
        "pr_dual_f1all_b": dict(fault="F1", iters="3000", bytes="4096", gap_us="500", r0env="", r1env="",
                                extra="GIN_TS_DUAL=1", inject=str(inj)),
        "pr_dual_none_b": dict(fault="none", iters="3000", bytes="4096", gap_us="500", r0env="", r1env="",
                               extra="GIN_TS_DUAL=1"),
        "pr_bidirf_conflict_b": dict(fault="F1both", app="bidir", iters="8000", bytes="4096", gap_us="0",
                                     r0env="NCCL_GIN_FAULT_INJECT_CTX=0+NCCL_GIN_TS_TEST_STALL=20@quiesce",
                                     r1env="NCCL_GIN_FAULT_INJECT_CTX=1", extra="GIN_TS_BIDIR_FUSED=1",
                                     inject=str(60 + (k * 7) % 50), inject1=str(60 + (k * 7) % 50 + 5)),
        "lat_pr_on_4k": dict(fault="lat", iters="3000", bytes="4096", ts="1"),
        "lat_pr_on_256k": dict(fault="lat", iters="3000", bytes="262144", ts="1"),
        "lat_rc_on_4k": dict(fault="lat", iters="3000", bytes="4096", ts="1"),
        "lat_rc_on_256k": dict(fault="lat", iters="3000", bytes="262144", ts="1"),
        "f1_b": dict(fault="F1", iters="120", inject=str(500 + (k * 137) % 700)),
        "f3_b": dict(fault="F3", iters="120", inject=str(500 + (k * 137) % 700)),
        "bidirf_sym_b": dict(fault="F1both", app="bidir", iters="8000", bytes="4096", gap_us="0",
                             extra="GIN_TS_BIDIR_FUSED=1", inject=str(60 + (k * 7) % 50),
                             inject1=str(60 + (k * 7) % 50 - 1 - k % 2)),
        "f4_b": dict(fault="F4", iters="200", gap_us="30000"),
        "f2rel_b": dict(fault="F2", iters="120",
                        extra="GIN_TS_RX_WAIT_S=20+GIN_TS_POST_ABORT_WAIT_S=3+NCCL_GIN_TS_USER_ABORT=1"),
    }.get(c, {})
    for kk, vv in exp.items():
        if m.get(kk, "") != vv:
            p.append("%s=%r (want %r)" % (kk, m.get(kk), vv))
    # the hook delay the library armed must equal meta inject (rank 0) / inject1 (rank 1)
    for rk, mk in (("_l0", "inject"), ("_l1", "inject1")):
        a = r[rk]["armed"]
        if a and m.get(mk) and str(a[0][1]) != m.get(mk):
            p.append("armed %s on %s vs meta %s=%s" % (a[0], rk, mk, m.get(mk)))
    # driver of the prd bundle prints dual keys; the pr/rc driver does not
    has_dual = r["dual_r0"] != "" or r["dual_r1"] != ""
    if (b == "prd") != has_dual:
        p.append("dual kv keys present=%s for build %s" % (has_dual, b))
    # the pr library logs the pair-reset start line, the rc library does not
    has_pr = bool(r["_l0"]["pr"] or r["_l1"]["pr"])
    if r["bind_fail"] != 1 and (b in ("pr", "prd")) != has_pr:
        p.append("pair reset line present=%s for build %s" % (has_pr, b))
    return p


# ---------------------------------------------------------------- helpers for the report


def rng(vals, fmt="%g"):
    vals = [v for v in vals if v is not None]
    if not vals:
        return "-"
    lo, hi = min(vals), max(vals)
    return (fmt % lo) if lo == hi else (fmt + "–" + fmt) % (lo, hi)


def fl(x):
    return num(x)


def gt_to_mono(r, gt):
    """rank 0's globaltimer (ns) -> rank 0 CLOCK_MONOTONIC (ms), anchored on rank 0's first device-classified record
    (it carries both gtimer_ns and mono_ms; the host reads the record within its 20 us poll)."""
    q = r["_l0"]["q4"]
    if not q or not gt:
        return None
    return float(q[0]["mono_ms"]) + (int(gt) - int(q[0]["gtimer_ns"])) / 1e6


def section(t):
    print("\n" + "=" * 8 + " " + t)


def main():
    # ---------------- frozen files
    section("frozen files")
    pred_path = os.path.join(STUDY, "predictions.csv")
    h = hashlib.sha256(open(pred_path, "rb").read()).hexdigest()
    prereg = open(os.path.join(STUDY, "PREREG.txt")).read()
    print("predictions.csv sha256 %s; in PREREG.txt: %s" % (h, h in prereg))
    preds = list(csv.DictReader(open(pred_path)))
    print("prediction rows: %d" % len(preds))
    try:
        top = subprocess.run(["git", "-C", STUDY, "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                             check=True).stdout.strip()
        rel = os.path.relpath(os.path.join(STUDY, "EXPERIMENT.md"), top)
        tagc = subprocess.run(["git", "-C", top, "rev-parse", "prereg/gin-pair-reset-v1^{commit}"],
                              capture_output=True, text=True).stdout.strip()
        print("tag prereg/gin-pair-reset-v1 -> %s" % tagc)
        old = subprocess.run(["git", "-C", top, "show", "prereg/gin-pair-reset-v1:" + rel], capture_output=True,
                             text=True).stdout
        cur = open(os.path.join(STUDY, "EXPERIMENT.md")).read()
        oldp = subprocess.run(["git", "-C", top, "show", "prereg/gin-pair-reset-v1:" +
                               os.path.relpath(pred_path, top)], capture_output=True, text=True).stdout
        print("predictions.csv identical to the tag: %s" % (oldp == open(pred_path).read()))

        def sect(txt, a, b):
            s = txt.index("\n## %d." % a)
            e = txt.index("\n## %d." % b)
            return txt[s:e]
        for a, b in ((2, 4), (7, 9)):
            print("EXPERIMENT.md sections %d-%d identical to the tag: %s" % (a, b - 1, sect(old, a, b) == sect(cur, a, b)))
    except Exception as e:  # noqa: BLE001
        print("git check failed: %s" % e)

    # ---------------- trials
    rows = []
    for sd in SUBDIRS:
        for meta in sorted(glob.glob(os.path.join(RES, sd, "*_meta.txt"))):
            rows.append(trial(meta[: -len("_meta.txt")]))
    rows.sort(key=lambda r: (r["_wall"], r["_t0"] or 0))
    section("trial set (%d trials in %s)" % (len(rows), ", ".join(SUBDIRS)))
    for r in rows:
        r["excl"] = exclusion(r)
    scored = [r for r in rows if not r["excl"]]
    by_key = defaultdict(list)
    for r in scored:
        by_key[r["key"]].append(r)
    allk = Counter(r["key"] for r in rows)
    print("%-28s %5s %5s %5s %s" % ("cell@build", "run", "excl", "score", "trial numbers scored"))
    for key in PLANNED:
        ns = sorted(r["n"] for r in by_key[key])
        print("%-28s %5d %5d %5d/%-3d %s" % (key, allk[key], allk[key] - len(by_key[key]), len(by_key[key]),
                                              PLANNED[key], ns))
    extra_keys = set(allk) - set(PLANNED)
    print("cells not in section 7: %s" % sorted(extra_keys))
    print("total run %d, scored %d (cell trials %d, latency runs %d), excluded %d" % (
        len(rows), len(scored), sum(1 for r in scored if not r["cell"].startswith("lat_")),
        sum(1 for r in scored if r["cell"].startswith("lat_")), len(rows) - len(scored)))
    for r in rows:
        if r["excl"]:
            extra = ""
            if r["cell"] == "pr_bidirf_conflict_b":
                extra = " (rank 1 first record - (stall start + 18 ms) = %.3f ms; after stall start %.3f ms)" % (
                    r["r1_q4_minus_stall_end_ms"], r["r1_q4_after_stall_start_ms"])
            print("EXCLUDED %s: %s%s; transparent_ok=%s" % (r["stem"], r["excl"], extra, r["transparent_ok"]))
    print("conflict cell r1_q4_in_stall margins (q - (t+18)) ms:",
          ", ".join("n%d %.3f" % (r["n"], r["r1_q4_minus_stall_end_ms"]) for r in rows
                    if r["cell"] == "pr_bidirf_conflict_b" and r["r1_q4_minus_stall_end_ms"] != ""))

    # holds by wall clock (chain.out)
    chain = open(os.path.join(RES, "chain.out")).read().splitlines()
    spans = []
    for ln in chain:
        m = re.match(r"(\S+ \S+) hold (\S+) (start|rc=\d+)", ln)
        if m:
            if m.group(3) == "start":
                spans.append([m.group(2), m.group(1), None])
            else:
                spans[-1][2] = m.group(1)
    print("holds (chain.out): " + "; ".join("%s %s–%s" % (s[0], s[1][11:], s[2][11:]) for s in spans))
    for r in rows:
        r["hold"] = next((s[0].split(":")[0] + ("" if not s[0].startswith("fill") else ":" + s[0].split(":")[2])
                          for s in spans if s[1] <= r["_wall"] <= s[2]), "?")
    print("trials per hold and cell:")
    hc = Counter((r["hold"], r["key"]) for r in rows)
    for (hh, kk), n in sorted(hc.items()):
        print("  %-40s %-28s %d" % (hh, kk, n))
    h2 = [("%s n%d" % ("on" if r["cell"] == "pr_dual_f1c0_b" else "off" if r["cell"] == "pr_dual_f1c0_full_b" else
                       "none", r["n"])) for r in rows if r["hold"] == "H2"]
    print("H2 order: " + ", ".join(h2))

    # ---------------- setup and cell-condition checks
    section("setup checks (EXPERIMENT.md 8) and cell conditions (7, cells.sh)")
    bad = 0
    for r in rows:
        if r["bind_fail"]:
            continue
        p = setup_problems(r)
        q = cell_condition_problems(r)
        if p or q:
            bad += 1
            print("%s: setup %s; conditions %s" % (r["stem"], p, q))
    print("trials with a setup or condition problem: %d (bind-fail trial skipped)" % bad)
    bun = Counter((r["key"], r["_m"].get("bundle", "").rsplit("/", 1)[-1], "dual" if r["dual_r0"] else "-",
                   "pr-line" if (r["_l0"]["pr"] or r["_l1"]["pr"]) else "-") for r in rows)
    print("bundle per cell (cell@build, bundle dir, dual kv keys, pair-reset start line): ")
    for k_, n_ in sorted(bun.items()):
        print("  %s x%d" % (k_, n_))
    lefts = [(r["stem"], r["left"]) for r in rows if r["left"] not in ("0", None)]
    print("left > 0: %s" % lefts)

    # ---------------- predictions
    section("predictions")
    out = []
    for p in preds:
        cells = [c.strip() for c in p["cells"].split(";")]
        verdict, d = evaluate(p["acceptance"], by_key, cells, PLANNED)
        out.append((p["id"], verdict, d, cells))
        cnt = "; ".join("%s %d/%d" % (c, a, b) for c, (a, b) in d["counts"].items())
        med = "; ".join("median %s %s = %s (n=%d%s)" % (col, ck, med if med is NA else "%.4g" % med, len(v),
                                                         ", %d blank" % nb if nb else "")
                        for (col, ck), (med, v, nb) in d["medians"].items())
        print("%-4s %-17s %s %s | %s" % (p["id"], verdict, cnt, med, " || ".join(d.get("substituted", []))))
        miss = {c: m for c, m in d["misses"].items() if m}
        if miss:
            print("      misses: %s" % miss)
        if d["errs"]:
            print("      type errors: %s" % d["errs"])
    print("verdicts: %s" % Counter(v for _, v, _, _ in out))

    # second check: every rule hand-coded on typed values (blank -> None -> false), independent of the text evaluator
    def f_(r, c):
        return num(r.get(c))

    def s_(r, c):
        v = r.get(c)
        return "" if v is None else str(v)

    def cnt(key, pred):
        return sum(1 for r in by_key[key] if pred(r))

    def med(key, c):
        return statistics.median([f_(r, c) for r in by_key[key]])
    eq = lambda r, c, v: f_(r, c) is not None and f_(r, c) == v  # noqa: E731
    D, F3, ALL, CF, FULL, NONE = ("pr_dual_f1c0_b@prd", "pr_dual_f3c0_b@prd", "pr_dual_f1all_b@prd",
                                  "pr_bidirf_conflict_b@pr", "pr_dual_f1c0_full_b@prd", "pr_dual_none_b@prd")
    inwin = lambda r: (f_(r, "dual_c1_in_win") is not None and f_(r, "dual_c1_in_win") >= 1 and  # noqa: E731
                       f_(r, "dual_c1_max_in_win_us") is not None and 0 <= f_(r, "dual_c1_max_in_win_us") <= 1000)
    hand = OrderedDict([
        ("P1a", cnt(D, lambda r: eq(r, "transparent_ok", 1)) >= 9),
        ("P1b", cnt(D, lambda r: s_(r, "rec_scope_r0") == "0x1" and eq(r, "rec_qps_r0", 1) and
                    s_(r, "rec_scope_r1") == "0x1" and eq(r, "rec_qps_r1", 1) and eq(r, "n_rec_r0", 1) and
                    eq(r, "n_rec_r1", 1)) >= 9),
        ("P1c", cnt(D, lambda r: eq(r, "ep_c0_r0", 2) and eq(r, "ep_c1_r0", 0) and eq(r, "ep_c0_r1", 2) and
                    eq(r, "ep_c1_r1", 0)) >= 9),
        ("P1d", cnt(D, inwin) >= 9),
        ("P2a", cnt(F3, lambda r: eq(r, "transparent_ok", 1)) >= 9),
        ("P2b", cnt(F3, lambda r: "RETRY_EXC" in s_(r, "q4_class_r0") and s_(r, "rec_scope_r0") == "0x1" and
                    eq(r, "rec_qps_r0", 1) and s_(r, "rec_scope_r1") == "0x1" and eq(r, "rec_qps_r1", 1) and
                    eq(r, "ep_c1_r0", 0) and eq(r, "ep_c1_r1", 0)) >= 9),
        ("P2c", cnt(F3, inwin) >= 9),
        ("T1", med(D, "commit_us_r0") <= 0.5 * med(FULL, "commit_us_r0")),
        ("T2", med(D, "total_us_r0") <= 0.6 * med(FULL, "total_us_r0")),
        ("B1a", cnt(ALL, lambda r: eq(r, "transparent_ok", 1)) >= 9),
        ("B1b", cnt(ALL, lambda r: eq(r, "rec_init_r0", 1) and eq(r, "rec_qps_r0", 4) and eq(r, "rec_qps_r1", 4) and
                    s_(r, "scope_reason_r0") in ("qp_state", "queued")) >= 9),
        ("B2a", cnt(CF, lambda r: eq(r, "transparent_ok", 1) and not s_(r, "decl_r0") and not s_(r, "decl_r1")) >= 9),
        ("B2b", cnt(CF, lambda r: eq(r, "conflict_r1", 1) and eq(r, "rec_init_r0", 1) and eq(r, "rec_resp_r0", 1) and
                    eq(r, "rec_resp_r1", 1) and eq(r, "rec_init_r1", 1) and eq(r, "init_qps_r1", 4)) >= 9),
        ("C1a", cnt(FULL, lambda r: eq(r, "transparent_ok", 1) and eq(r, "pr_mode_r0", 0) and eq(r, "rec_qps_r0", 4)
                    and eq(r, "rec_qps_r1", 4)) == 5),
        ("C1b", cnt(FULL, lambda r: f_(r, "dual_c1_max_in_win_us") is not None and
                    f_(r, "dual_c1_max_in_win_us") >= 1000) >= 4),
        ("C2", cnt(NONE, lambda r: eq(r, "transparent_ok", 1) and eq(r, "n_rec_r0", 0) and eq(r, "n_rec_r1", 0) and
                   f_(r, "dual_c1_max_us") is not None and 0 <= f_(r, "dual_c1_max_us") <= 1000) == 5),
        ("G1", all(cnt(k_, lambda r: eq(r, "transparent_ok", 1)) == 5
                   for k_ in ("f1_b@pr", "f3_b@pr", "bidirf_sym_b@pr", "mt256_f1_b@pr"))),
        ("G2", all(cnt(k_, lambda r: eq(r, "rec_qps_r0", 4) and eq(r, "rec_qps_r1", 4)) == 5
                   for k_ in ("f1_b@pr", "mt256_f1_b@pr", "bidirf_sym_b@pr"))),
        ("G3", cnt("f3_b@pr", lambda r: s_(r, "rec_scope_r0") == "0x1" and eq(r, "rec_qps_r0", 1) and
                   eq(r, "rec_qps_r1", 1)) == 5),
        ("G4", cnt("f4_b@pr", lambda r: ("peer's socket shows FIN" in s_(r, "decl_r0") or
                                         "peer's socket shows ECONNRESET" in s_(r, "decl_r0")) and
                   s_(r, "teardown_r0") == "no error") == 5),
        ("G5", cnt("f2rel_b@pr", lambda r: s_(r, "teardown_r1") == "no error" and f_(r, "r1rc") is not None and
                   f_(r, "r1rc") != 7 and f_(r, "teardown_ms_r1") is not None and f_(r, "teardown_ms_r1") <= 5000 and
                   s_(r, "r1_outcome") == "async_error_kernel_stuck") == 5),
        ("L1", abs(med("lat_pr_on_4k@pr", "lat_p50_us") - med("lat_rc_on_4k@rc", "lat_p50_us")) <= 0.40),
        ("L2", abs(med("lat_pr_on_256k@pr", "lat_p50_us") - med("lat_rc_on_256k@rc", "lat_p50_us")) <= 0.30),
    ])
    agree = sum(1 for pid, v, _, _ in out if (v == "holds") == hand[pid])
    print("hand-coded rules: %d hold; agree with the verbatim evaluation on %d/%d" % (
        sum(hand.values()), agree, len(out)))

    # parse coverage: raw substring counts against parsed lines (all trials)
    raw = Counter()
    parsed = Counter()
    for r in rows:
        for lg in (r["_l0"], r["_l1"]):
            t = lg["text"]
            raw["fault fired"] += t.count("GIN/FAULT: GDAKI fault fired")
            raw["scope decision"] += len(re.findall(r"GIN/TS: rank \d+: round \d+ peer", t))
            raw["recovered"] += t.count("GIN/TS: recovered ")
            raw["scope conflict"] += t.count("scope conflict:")
            raw["gate epochs"] += t.count("gate epochs to rank")
            raw["pair reset"] += t.count("GIN/TS: pair reset=")
            raw["TEST stall"] += t.count("GIN/TS: TEST stall rank=")
            raw["declined"] += t.count("GIN/TS: declined")
            raw["device record"] += t.count("device-classified error CQE")
            parsed["fault fired"] += len(lg["fires"])
            parsed["scope decision"] += len(lg["dec"])
            parsed["recovered"] += len(lg["rec"])
            parsed["scope conflict"] += len(lg["conf"])
            parsed["gate epochs"] += len(lg["ep"])
            parsed["pair reset"] += len(lg["pr"])
            parsed["TEST stall"] += len(lg["stall"])
            parsed["declined"] += len(lg["decl"])
            parsed["device record"] += len(lg["q4"])
    print("parse coverage (raw substrings / parsed lines): %s" % ", ".join(
        "%s %d/%d" % (k_, raw[k_], parsed[k_]) for k_ in raw))

    # ---------------- detail per cell
    def K(key):
        return by_key[key]

    section("round scope and QP count, both ranks (first recovered line), decision lines")
    for key in ["pr_dual_f1c0_b@prd", "pr_dual_f3c0_b@prd", "pr_dual_f1all_b@prd", "pr_dual_f1c0_full_b@prd",
                "pr_bidirf_conflict_b@pr", "f1_b@pr", "f3_b@pr", "bidirf_sym_b@pr", "mt256_f1_b@pr", "pr_dual_none_b@prd",
                "f4_b@pr", "f2rel_b@pr"]:
        rs = K(key)
        sc = Counter((r["rec_scope_r0"], r["rec_qps_r0"], r["rec_scope_r1"], r["rec_qps_r1"]) for r in rs)
        nrec = Counter((r["n_rec_r0"], r["n_rec_r1"]) for r in rs)
        dec = Counter(tuple((d["rank"], d["scope"], d["qps"], d["reason"]) for d in r["_l0"]["dec"] + r["_l1"]["dec"])
                      for r in rs)
        roles = Counter((r["rec_init_r0"], r["rec_resp_r0"], r["rec_init_r1"], r["rec_resp_r1"]) for r in rs)
        print("%s (n=%d)" % (key, len(rs)))
        print("   first rec (scope_r0, qps_r0, scope_r1, qps_r1): %s" % dict(sc))
        print("   n_rec (r0, r1): %s; roles (init_r0, resp_r0, init_r1, resp_r1): %s" % (dict(nrec), dict(roles)))
        print("   decision lines (rank, scope, qps, reason) per trial: %s" % dict(dec))
        if any(r["decl_r0"] or r["decl_r1"] for r in rs):
            print("   declines r0: %s; r1: %s" % (dict(Counter(r["decl_r0"] for r in rs)),
                                                  dict(Counter(r["decl_r1"] for r in rs))))

    section("gate epochs at teardown (all four contexts), both ranks")
    for key in ["pr_dual_f1c0_b@prd", "pr_dual_f3c0_b@prd", "pr_dual_f1all_b@prd", "pr_dual_f1c0_full_b@prd",
                "pr_dual_none_b@prd", "pr_bidirf_conflict_b@pr", "f1_b@pr", "f3_b@pr", "bidirf_sym_b@pr",
                "mt256_f1_b@pr", "f4_b@pr", "f2rel_b@pr"]:
        rs = K(key)
        e = Counter((str(r["_l0"]["ep"][:1]), str(r["_l1"]["ep"][:1])) for r in rs)
        print("%-26s %s" % (key, dict(e)))

    section("dual-context window: context 0's longest iteration W vs the round on rank 0's clock")
    for key in ["pr_dual_f1c0_b@prd", "pr_dual_f3c0_b@prd", "pr_dual_f1c0_full_b@prd", "pr_dual_f1all_b@prd",
                "pr_dual_none_b@prd"]:
        rs = K(key)
        rows_out = []
        cons = []
        for r in rs:
            ws, we = gt_to_mono(r, r["dual_win_start_gt"]), gt_to_mono(r, r["dual_win_end_gt"])
            i0 = [x for x in r["_l0"]["rec"] if x.get("role") == "initiator"]
            cover = None
            if ws is not None and i0:
                ts, tr = float(i0[0]["t_start"]), float(i0[0]["t_resumed"])
                cover = (ts - ws, we - tr)
            win = fl(r["dual_win_us"])
            calc = (int(r["dual_win_end_gt"]) - int(r["dual_win_start_gt"])) / 1e3 if r["dual_win_end_gt"] else None
            c_ok = (calc is not None and abs(calc - win) < 0.11 and abs(fl(r["lat_max_us"]) - win) < 0.11 and
                    r["lat_max_it"] == r["dual_win_it"] and abs(fl(r["lat1_max_us"]) - fl(r["dual_c1_max_us"])) < 0.11
                    and fl(r["dual_c1_max_in_win_us"]) <= fl(r["dual_c1_max_us"]) and
                    (int(r["dual_c1_last_end_gt"]) > int(r["dual_win_end_gt"])) == (r["dual_c1_end_after_win"] == "1"))
            cons.append(c_ok)
            rows_out.append((r["n"], win, fl(r["dual_c1_in_win"]), fl(r["dual_c1_max_in_win_us"]),
                             fl(r["dual_c1_max_us"]), cover))
        print("%s (n=%d): W %s us; c1 in W %s; c1 longest overlapping %s us; c1 longest overall %s us; "
              "kv self-consistent %d/%d" % (
                  key, len(rs), rng([x[1] for x in rows_out], "%.1f"), rng([x[2] for x in rows_out], "%.0f"),
                  rng([x[3] for x in rows_out], "%.1f"), rng([x[4] for x in rows_out], "%.1f"), sum(cons), len(cons)))
        cov = [x[5] for x in rows_out if x[5] is not None]
        if cov:
            print("   W starts before round start by %s ms, ends after re-post by %s ms; W covers the round in %d/%d" % (
                rng([c[0] for c in cov], "%.3f"), rng([c[1] for c in cov], "%.3f"),
                sum(1 for c in cov if c[0] >= 0 and c[1] >= 0), len(cov)))
        for x in rows_out:
            print("   n%-2d W=%.1f in=%g max_in=%g max=%g cover=%s" % (x[0], x[1] or -1, x[2], x[3], x[4],
                                                                      "(%.3f, %.3f)" % x[5] if x[5] else "-"))
    # expected iterations of context 1 inside W (period = gap + its mean iteration)
    for key, gap in (("pr_dual_f1c0_b@prd", 500), ("pr_dual_f3c0_b@prd", 2000)):
        dev = []
        for r in K(key):
            w = fl(r["dual_win_us"])
            mean1 = fl(r["_k0"].get("lat1_mean_us"))
            dev.append(fl(r["dual_c1_in_win"]) - w / (gap + mean1))
        print("%s: in-window count minus W/(gap + mean c1 iteration): %s" % (key, rng(dev, "%.2f")))

    section("Commit and whole round, initiator (rank 0), first initiator line; same hold H2")
    a = K("pr_dual_f1c0_b@prd")
    b = K("pr_dual_f1c0_full_b@prd")
    for col in ("commit_us_r0", "total_us_r0"):
        va = sorted(fl(r[col]) for r in a)
        vb = sorted(fl(r[col]) for r in b)
        ma, mb = statistics.median(va), statistics.median(vb)
        print("%s: pair %s (median %.1f, n=%d); full %s (median %.1f, n=%d); ratio %.3f" % (
            col, rng(va, "%.0f"), ma, len(va), rng(vb, "%.0f"), mb, len(vb), ma / mb))
        print("   low/high median ratio: %.3f / %.3f" % (statistics.median_low(va) / mb, statistics.median_high(va) / mb))
    for nm, rk in (("responder commit (rank 1)", "_l1"),):
        va = sorted(fl(x["commit_us"]) for r in a for x in r[rk]["rec"] if x.get("role") == "responder")
        vb = sorted(fl(x["commit_us"]) for r in b for x in r[rk]["rec"] if x.get("role") == "responder")
        print("%s: pair %s (median %.1f); full %s (median %.1f); ratio %.3f" % (
            nm, rng(va, "%.0f"), statistics.median(va), rng(vb, "%.0f"), statistics.median(vb),
            statistics.median(va) / statistics.median(vb)))
    print("holds: pair %s; full %s" % (sorted(set(r["hold"] for r in a)), sorted(set(r["hold"] for r in b))))
    for key in ("pr_dual_f3c0_b@prd", "pr_dual_f1all_b@prd"):
        v = [fl(r["commit_us_r0"]) for r in K(key)]
        t = [fl(r["total_us_r0"]) for r in K(key)]
        print("%s (other hold, not a T1/T2 input): commit %s, total %s" % (key, rng(v, "%.0f"), rng(t, "%.0f")))

    section("timelines on rank 0's clock (rank 1 times minus clock_offset_ms)")

    def tl(key):
        o = defaultdict(list)
        for r in K(key):
            off = r["_off"]
            l0, l1 = r["_l0"], r["_l1"]
            fire = (l0["fires"][0]["fire"] if l0["fires"] else l1["fires"][0]["fire"] - off) if (l0["fires"] or
                                                                                                 l1["fires"]) else None
            fdone = (l0["fires"][0]["done"] if l0["fires"] else l1["fires"][0]["done"] - off) if fire else None
            q0 = float(l0["q4"][0]["mono_ms"]) if l0["q4"] else None
            d0 = l0["dec"][0]["mono"] if l0["dec"] else None
            i0 = [x for x in l0["rec"] if x.get("role") == "initiator"]
            res = float(i0[0]["t_resumed"]) if i0 else None
            if fire is not None and q0 is not None:
                o["fire->q4_r0 ms"].append(q0 - fire)
                o["fire_done->q4_r0 ms"].append(q0 - fdone)
            if q0 is not None and d0 is not None:
                o["q4_r0->decision ms"].append(d0 - q0)
            if d0 is not None and res is not None:
                o["decision->t_resumed ms"].append(res - d0)
            for x in l1["rec"]:
                o["r1 %s commit_us" % x.get("role")].append(float(x["commit_us"]))
            for x in [x for x in l1["rec"] if x.get("role") == "initiator"]:
                o["r1 initiator mbx_to_resumed ms"].append(float(x["mbx_to_resumed_us"]) / 1e3)
                o["r1 first q4 -> r1 initiator t_resumed ms"].append(float(x["t_resumed"]) -
                                                                      float(l1["q4"][0]["mono_ms"]))
            o["r0 lat1_p50 us"].append(fl(r["_k0"].get("lat1_p50_us")))
            o["r0 lat1_p99 us"].append(fl(r["_k0"].get("lat1_p99_us")))
        return o
    for key in ("pr_dual_f1c0_b@prd", "pr_dual_f1c0_full_b@prd", "pr_dual_f3c0_b@prd", "pr_dual_f1all_b@prd",
                "pr_dual_none_b@prd", "pr_bidirf_conflict_b@pr", "f3_b@pr"):
        o = tl(key)
        print("%s: %s" % (key, "; ".join("%s %s" % (k_, rng([v for v in vs if v is not None], "%.3f"))
                                          for k_, vs in o.items() if any(v is not None for v in vs))))
    f1all = K("pr_dual_f1all_b@prd")
    early = [r["n"] for r in f1all if r["_l0"]["dec"] and r["_l0"]["fires"] and
             r["_l0"]["dec"][0]["mono"] < r["_l0"]["fires"][0]["done"]]
    c1first = [r["n"] for r in f1all if r["_l0"]["q4"] and r["_l0"]["q4"][0].get("ctx") == "1"]
    print("pr_dual_f1all_b: decision before the stock hook finished moving the QPs in trials %s; "
          "rank 0's first device record was context 1's in trials %s" % (early, c1first))

    section("all-contexts cell: fallback")
    for r in K("pr_dual_f1all_b@prd"):
        q4 = [(q.get("ctx"), q.get("mono_ms")) for q in r["_l0"]["q4"]]
        d = r["_l0"]["dec"][0] if r["_l0"]["dec"] else {}
        f = r["_l0"]["fires"][0] if r["_l0"]["fires"] else {}
        print("n%-2d reason=%s decision@%.3f fire %.3f-%.3f q4(ctx@ms)=%s rounds(td)=%s rec r0/r1=%s/%s qps=%s/%s" % (
            r["n"], d.get("reason"), d.get("mono", 0), f.get("fire", 0), f.get("done", 0),
            [(c, "%.3f" % float(t)) for c, t in q4], [x[3] for x in r["_l0"]["td"]], r["n_rec_r0"], r["n_rec_r1"],
            r["rec_qps_r0"], r["rec_qps_r1"]))
    print("reasons: %s" % dict(Counter(r["scope_reason_r0"] for r in K("pr_dual_f1all_b@prd"))))

    section("scope-conflict cell: sequence (rank 1 events on rank 0's clock)")
    allconf = [r for r in rows if r["cell"] == "pr_bidirf_conflict_b"]
    for r in allconf:
        off = r["_off"]
        l0, l1 = r["_l0"], r["_l1"]
        st = l0["stall"][0] if l0["stall"] else None
        d1 = [(d["round"], d["scope"], d["qps"], d["reason"], d["mono"] - off) for d in l1["dec"]]
        rec1 = [(x.get("role"), x.get("round"), x.get("scope"), x.get("qps"),
                 float(x.get("t_start") or x.get("t_req")) - off) for x in l1["rec"]]
        rec0 = [(x.get("role"), x.get("round"), x.get("scope"), x.get("qps"), x.get("tie_kept") or x.get("yielded"))
                for x in l0["rec"]]
        conf = l1["conf"][0] if l1["conf"] else None
        ordered = [e[0] for e in l1["order"]]
        print("n%-2d %s excl=%r stall@%.3f q4_r1@%.3f | r1 dec %s | conflict %s | r1 order %s | r1 rec %s | r0 rec %s"
              " | aborted r1=%d | tie_kept r0=%d yield=%d | ep r0 %s r1 %s | decl %r %r | transparent %d" % (
                  r["n"], "", r["excl"], st[2] if st else -1, float(l1["q4"][0]["mono_ms"]) - off,
                  [(a, b_, c, d, "%.3f" % e) for a, b_, c, d, e in d1], conf, ordered,
                  [(a, b_, c, d, "%.3f" % e) for a, b_, c, d, e in rec1], rec0, l1["rec_aborted"], l0["tie_kept"],
                  l0["yielded"] + l1["yielded"], l0["ep"], l1["ep"], r["decl_r0"], r["decl_r1"], r["transparent_ok"]))

    section("replication cells")
    for key in ("f1_b@pr", "f3_b@pr", "bidirf_sym_b@pr", "mt256_f1_b@pr", "f4_b@pr", "f2rel_b@pr"):
        rs = K(key)
        print("%s n=%d transparent %d; r0rc %s r1rc %s; outcomes r0 %s r1 %s; teardown r0 %s r1 %s; "
              "teardown_ms_r1 %s; initiator rank %s; reasons %s; killed %s" % (
                  key, len(rs), sum(r["transparent_ok"] for r in rs), dict(Counter(r["r0rc"] for r in rs)),
                  dict(Counter(r["r1rc"] for r in rs)), dict(Counter(r["r0_outcome"] for r in rs)),
                  dict(Counter(r["r1_outcome"] for r in rs)), dict(Counter(r["teardown_r0"] for r in rs)),
                  dict(Counter(r["teardown_r1"] for r in rs)), rng([fl(r["teardown_ms_r1"]) for r in rs], "%.1f"),
                  dict(Counter("r0" if r["rec_init_r0"] else "r1" if r["rec_init_r1"] else "-" for r in rs)),
                  dict(Counter(tuple(d["reason"] for d in r["_l0"]["dec"] + r["_l1"]["dec"]) for r in rs)),
                  dict(Counter(r["killed"] for r in rs))))
        if key == "f3_b@pr":
            print("   rank 1 hook moved %s; rank 0 q4 contexts %s" % (
                dict(Counter("%d/%d" % (r["_l1"]["fires"][0]["moved"], r["_l1"]["fires"][0]["of"]) for r in rs)),
                dict(Counter(tuple(q.get("ctx") for q in r["_l0"]["q4"]) for r in rs))))

    section("dual-mode transparency, per-context keys")
    for key in ("pr_dual_f1c0_b@prd", "pr_dual_f3c0_b@prd", "pr_dual_f1all_b@prd", "pr_dual_f1c0_full_b@prd",
                "pr_dual_none_b@prd"):
        rs = K(key)
        ok = sum(1 for r in rs if r["dual_c0_done"] == "3000" and r["dual_c1_done"] == "3000" and
                 r["r1_dual_rx_c0_done"] == "3000" and r["r1_dual_rx_c1_done"] == "3000" and
                 r["r1_final_signal"] == r["r1_expected_final"] == "3000" and
                 r["r1_dual_final_signal1"] == r["r1_dual_expected_final1"] == "3000" and r["r1_host_slots"] == "6000")
        print("%s: per-context complete and exact %d/%d; transparent_ok %d/%d" % (
            key, ok, len(rs), sum(r["transparent_ok"] for r in rs), len(rs)))
    for key in ("pr_dual_f3c0_b@prd",):
        print("%s rank 0 q4 classes %s; contexts %s" % (key, dict(Counter(r["q4_class_r0"] for r in K(key))),
                                                       dict(Counter(tuple(q.get("ctx") for q in r["_l0"]["q4"])
                                                                    for r in K(key)))))

    section("latency (p50 recomputed from <stem>_lat_raw.csv.gz with the driver's rank rule v[int(0.5*(n-1)+0.5)])")
    meds = {}
    for key in ("lat_pr_on_4k@pr", "lat_rc_on_4k@rc", "lat_pr_on_256k@pr", "lat_rc_on_256k@rc"):
        rs = sorted(K(key), key=lambda r: r["n"])
        rec = []
        for r in rs:
            p = os.path.join(RES, r["dir"], r["stem"] + "_lat_raw.csv.gz")
            v = sorted(int(ln.split(",")[1]) for ln in gzip.open(p, "rt") if ln.strip())
            n = len(v)
            p50 = v[int(0.5 * (n - 1) + 0.5)] / 1e3
            rec.append((r["n"], n, p50, fl(r["lat_p50_us"])))
        meds[key] = statistics.median([x[2] for x in rec])
        print("%s: runs %s; p50 recomputed %s; kv %s; all equal to 0.01: %s; median %.2f; transparent %d/%d" % (
            key, [x[0] for x in rec], [round(x[2], 2) for x in rec], [x[3] for x in rec],
            all(abs(x[2] - x[3]) < 0.006 for x in rec), meds[key], sum(r["transparent_ok"] for r in rs), len(rs)))
    print("4 KiB |pr - rc| = %.3f us; 256 KiB |pr - rc| = %.3f us" % (
        abs(meds["lat_pr_on_4k@pr"] - meds["lat_rc_on_4k@rc"]), abs(meds["lat_pr_on_256k@pr"] - meds["lat_rc_on_256k@rc"])))
    lat_order = [r["key"].split("@")[0].replace("lat_", "") + "#%d" % r["n"] for r in rows if r["cell"].startswith("lat_")]
    print("latency run order: %s" % lat_order)

    # ---------------- safety
    section("safety per hold")
    cmd_re = re.compile(r"(cmd|command)", re.I)
    bad_re = re.compile(r"(failed|timeout|leak)", re.I)
    tags = sorted(set(re.sub(r"^snap_(before|after)-", "", os.path.basename(p))[:-4]
                      for p in glob.glob(os.path.join(RES, "snap_*.txt"))))
    for t in tags:
        line = [t]
        for node in ("rain", "sunny"):
            be = open(os.path.join(RES, "mlx5_before-%s_%s.txt" % (t, node))).read().splitlines()
            af = open(os.path.join(RES, "mlx5_after-%s_%s.txt" % (t, node))).read().splitlines()
            new = sorted((Counter(af) - Counter(be)).elements())
            ce_b = sum(1 for x in be if "mlx5" in x.lower() and cmd_re.search(x) and bad_re.search(x))
            ce_a = sum(1 for x in af if "mlx5" in x.lower() and cmd_re.search(x) and bad_re.search(x))
            line.append("%s lines %d->%d new %d cmd_err %d->%d" % (node, len(be), len(af), len(new), ce_b, ce_a))

        def fwsum(p):
            s = 0
            for ln in open(p):
                for m in re.finditer(r"\b(failed|failed_mbox_status)=(\d+)", ln):
                    s += int(m.group(2))
            return s

        def fwn(p):
            d = {}
            for ln in open(p):
                m = re.match(r"(\w+) n=(\d+)", ln)
                if m:
                    d[m.group(1)] = int(m.group(2))
            return d
        fb, fa = os.path.join(RES, "fwcmd_before-%s.txt" % t), os.path.join(RES, "fwcmd_after-%s.txt" % t)
        nb, na = fwn(fb), fwn(fa)
        line.append("fw failed sum %d->%d" % (fwsum(fb), fwsum(fa)))
        line.append("fw cmd deltas %s" % {k: na[k] - nb[k] for k in na})
        newf = os.path.join(RES, "mlx5_new_%s.txt" % t)
        line.append("mlx5_new size %d" % os.path.getsize(newf))
        gpu = [ln for f in ("snap_before-%s.txt" % t, "snap_after-%s.txt" % t)
               for ln in open(os.path.join(RES, f)) if "gpu:" in ln]
        line.append("gpu users listed %d" % len(gpu))
        print(" | ".join(line))
    # rain (rank 0) firmware command counters against the QPs that rank 0's recovered lines say were reset:
    # delta(2RST_QP) - sum(qps) and delta(RST2INIT_QP) - sum(qps) should be a constant per trial that created QPs
    hmap = {"fill1": "fill:bidirf_sym_b@pr", "fill2": "fill:pr_bidirf_conflict_b@pr"}
    print("rain firmware counters vs rank 0 recovered lines (QPs reset per hold):")
    for t in tags:
        hs = [r for r in rows if r["hold"] == hmap.get(t, t)]
        made = [r for r in hs if not r["bind_fail"]]
        resets = sum(int(x.get("qps", 0)) for r in hs for x in r["_l0"]["rec"])
        nb = {}
        na = {}
        for d, f in ((nb, "fwcmd_before-%s.txt" % t), (na, "fwcmd_after-%s.txt" % t)):
            for ln in open(os.path.join(RES, f)):
                m = re.match(r"(\w+) n=(\d+)", ln)
                if m:
                    d[m.group(1)] = int(m.group(2))
        d2 = na["2RST_QP"] - nb["2RST_QP"]
        d3 = na["RST2INIT_QP"] - nb["RST2INIT_QP"]
        print("  %-5s trials %d (with QPs %d), QPs reset on rank 0 per logs %d; 2RST delta %d -> per trial %.2f; "
              "RST2INIT delta %d -> per trial %.2f" % (t, len(hs), len(made), resets, d2, (d2 - resets) / len(made),
                                                       d3, (d3 - resets) / len(made)))
    hout = {}
    for p in sorted(glob.glob(os.path.join(RES, "hold_*.out"))):
        txt = open(p).read()
        m = re.search(r"sunny_busy_after=(\d+)", txt)
        lefts = re.findall(r"left=(\d+)", txt)
        hout[os.path.basename(p)] = (m.group(1) if m else None, Counter(lefts), "STOP" in txt)
    print("hold_*.out (sunny_busy_after, left= counts, STOP mention): %s" % hout)
    print("STOP_mlx5 present: %s" % os.path.exists(os.path.join(RES, "STOP_mlx5")))
    print("trial meta left values: %s" % dict(Counter(r["left"] for r in rows)))

    # ---------------- smoke (not scored): the conflict trials' r1_q4_in_stall (DEVIATIONS.md 1)
    sm = os.path.join(os.path.dirname(RES), os.path.basename(RES) + "_smoke", "smoke")
    if os.path.isdir(sm):
        section("smoke (not scored)")
        srows = [trial(p[: -len("_meta.txt")]) for p in sorted(glob.glob(os.path.join(sm, "*_meta.txt")))]
        print("smoke trials %d; transparent %d" % (len(srows), sum(r["transparent_ok"] for r in srows)))
        for r in srows:
            if r["cell"] == "pr_bidirf_conflict_b":
                print("smoke %s r1_q4_in_stall=%s margin %.3f ms conflict_r1=%d" % (
                    r["stem"], r["r1_q4_in_stall"], r["r1_q4_minus_stall_end_ms"], r["conflict_r1"]))


if __name__ == "__main__":
    main()
