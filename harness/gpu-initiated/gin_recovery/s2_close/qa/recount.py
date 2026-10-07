#!/usr/bin/env python3
"""gin-s2-close: independent recount of the 28 frozen predictions from the raw per-trial files.

usage: recount.py [<resultsdir>]   (default: ../results/20261007 next to this script)

Written for the QA step without reading score.py, SCORE.md, trials_scored.csv or the trials_*.csv written by the row
scripts. Only the raw files are read: <stem>_meta.txt, <stem>_r{0,1}.kv, <stem>_r{0,1}.log, <stem>_kill.out,
<stem>_lat_raw.csv.gz, gate_test.txt, hold_*.out, snap_*.txt, fwcmd_*.txt. The column definitions follow EXPERIMENT.md
3.1 (rows.py columns keep the meaning rows.py gives them; the new columns follow the 3.1 table); the acceptance
expressions are taken verbatim from predictions.csv and evaluated with the 3.2 grammar (numbers -> float, blank ->
None, other -> str; any comparison or arithmetic with None is false).
"""
import csv, glob, gzip, os, re, statistics, sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
RES = sys.argv[1] if len(sys.argv) > 1 else os.path.join(STUDY, "results", "20261007")
SUBDIRS = ["lat", "rep_s2", "rel", "rep_s2r", "nonmsg", "mute"]

# ---------------------------------------------------------------- planned trials (EXPERIMENT.md section 7)
PLAN = {}
for c, b in [("lat_base_4k", "base"), ("lat_base_256k", "base"), ("lat_s1off_4k", "s1"), ("lat_s1off_256k", "s1"),
             ("lat_s1on_4k", "s1"), ("lat_s1on_256k", "s1"), ("lat_s2off_4k", "s2"), ("lat_s2off_256k", "s2"),
             ("lat_s2on_4k", "s2"), ("lat_s2on_256k", "s2"), ("lat_s2sys_4k", "var_sys"), ("lat_s2sys_256k", "var_sys"),
             ("lat_s2r_on_4k", "s2r"), ("lat_s2r_on_256k", "s2r")]:
    PLAN[f"{c}@{b}"] = 5
for k, n in [("mt16_f1_b@s2", 5), ("mt64_f1_b@s2", 5), ("bidirf_sym_b@s2", 5), ("bidirf_sym_notie_b@s2", 5),
             ("f2rel_b@s2r", 10), ("ringf2rel_b@s2r", 10), ("f2rel_off_b@s2r", 5), ("off_f1_b@s2r", 5),
             ("f1_b@s2r", 5), ("f3_b@s2r", 5), ("f1g0_b@s2r", 5), ("mt256_f1_b@s2r", 5), ("bidirf_f1both_b@s2r", 5),
             ("f4_b@s2r", 5), ("get_f1_b@s2rget", 10), ("get_none_b@s2rget", 5), ("mt1024_norescue_b@s2r", 5),
             ("mute8_f1_b@s2r", 10), ("mute_f3_b@s2r", 10), ("mute1_f1_b@s2r", 5)]:
    PLAN[k] = n
GATE_PLAN = 14


# ---------------------------------------------------------------- raw readers
def kv(path):
    """key=value file; a value runs until the next ' key=' or the end of the line (values may hold spaces)."""
    d = {}
    if not os.path.exists(path):
        return d
    for line in open(path, errors="replace"):
        line = line.rstrip("\n")
        keys = list(re.finditer(r"(?:^| )(\w+)=", line))
        for i, m in enumerate(keys):
            end = keys[i + 1].start() if i + 1 < len(keys) else len(line)
            d[m.group(1)] = line[m.end():end].strip().strip('"')
    return d


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


RE_FIRE = re.compile(r"GIN/FAULT: GDAKI fault fired.*fire_mono_ms=([\d.]+)")
RE_DECL = re.compile(r'GIN/TS: declined rank=(\d+) peer=(\d+) reason="([^"]*)".*?mono_ms=([\d.]+)')
RE_MUTE_ON = re.compile(r"GIN/TS: TEST socket mute on rank=(\d+) peers=(\d+) mono_ms=([\d.]+)")
RE_MUTE_OFF = re.compile(r"GIN/TS: TEST socket mute off rank=(\d+) peers=(\d+) mono_ms=([\d.]+)")
RE_CLOSE = re.compile(r"GIN/TS: rank (\d+): socket to rank (\d+) closed cause=(\S+) mono_ms=([\d.]+)")
RE_TSON = re.compile(r"(gin_host_gdaki\.cc:\d+) \(gdakiTsStart\) NCCL WARN GIN/TS: transparent recovery ON")
RE_UA = re.compile(r"(dev_runtime\.cc:\d+) .*GIN/TS: user devComm abort flag set rank=(\d+)")


def scan(path):
    o = dict(fires=[], trig_miss=0, decl=[], ts_on=0, ts_src=set(), ua=0, ua_src=set(), mute_on=[], mute_off=[],
             close=[], kept=0, yld=0, bind=0, attach_fail=0, exists=os.path.exists(path))
    if not o["exists"]:
        return o
    for line in open(path, errors="replace"):
        if "GIN/" not in line and "bind" not in line:
            continue
        m = RE_FIRE.search(line)
        if m:
            o["fires"].append(float(m.group(1)))
        if "GIN/FAULT: shot 1 trigger not reached" in line:
            o["trig_miss"] += 1
        m = RE_DECL.search(line)
        if m:
            o["decl"].append((m.group(3), float(m.group(4))))
        elif "GIN/TS: declined" in line:
            o["decl"].append(("?", None))
        m = RE_TSON.search(line)
        if m:
            o["ts_on"] += 1
            o["ts_src"].add(m.group(1))
        elif "GIN/TS: transparent recovery ON" in line:
            o["ts_on"] += 1
        m = RE_UA.search(line)
        if m:
            o["ua"] += 1
            o["ua_src"].add(m.group(1))
        elif "GIN/TS: user devComm abort flag set" in line:
            o["ua"] += 1
        m = RE_MUTE_ON.search(line)
        if m:
            o["mute_on"].append(float(m.group(3)))
        m = RE_MUTE_OFF.search(line)
        if m:
            o["mute_off"].append(float(m.group(3)))
        m = RE_CLOSE.search(line)
        if m:
            o["close"].append((m.group(3), float(m.group(4)), int(m.group(1)), int(m.group(2))))
        if "the lower rank keeps the initiator role" in line:
            o["kept"] += 1
        if "the higher rank yields its round" in line:
            o["yld"] += 1
        if "bind: Address already in use" in line:
            o["bind"] = 1
        if "SO_ATTACH_FILTER failed" in line:
            o["attach_fail"] += 1
    return o


def lat_p50_raw(path):
    """p50 recomputed from the per-iteration samples the driver wrote (ns), with the driver's index rule."""
    if not os.path.exists(path):
        return None
    v = sorted(int(l.split(",")[1]) for l in gzip.open(path, "rt") if l.strip())
    if not v:
        return None
    return v[int(0.5 * (len(v) - 1) + 0.5)] / 1e3


# ---------------------------------------------------------------- one row per trial
def rank_ok(k, iters, sender, receiver):
    if k.get("outcome") != "ok" or k.get("async_first") != "none":
        return False
    if sender and not (k.get("tx_done") == str(iters) and k.get("tx_rc") == "no error"):
        return False
    if receiver and not (k.get("rx_done") == str(iters) and k.get("rx_rc") == "no error"
                         and k.get("dev_bad_slots") == "0" and k.get("host_bad_slots") == "0"
                         and k.get("signal_exact") == "1"):
        return False
    return True


def trial(sub, meta):
    stem = meta[: -len("_meta.txt")]
    m = kv(meta)
    k0, k1 = kv(stem + "_r0.kv"), kv(stem + "_r1.kv")
    l0, l1 = scan(stem + "_r0.log"), scan(stem + "_r1.log")
    kill = kv(stem + "_kill.out")
    iters = int(m.get("iters", "0"))
    bidir = m.get("app") == "bidir"
    off = f(k0.get("clock_offset_ms"))  # rank 1 clock - rank 0 clock
    r = dict(sub=sub, stem=os.path.basename(stem), cell=m.get("cell"), build=m.get("build"), trial=m.get("trial"),
             tnum=int(m.get("trial", "n0")[1:]), fault=m.get("fault"), app=m.get("app"), ts=m.get("ts"),
             extra=m.get("extra", ""), r0env=m.get("r0env", ""), inject=m.get("inject"), bytes=m.get("bytes"),
             gap_us=m.get("gap_us"), bundle=m.get("bundle"), wall_s=m.get("wall_s"), iters=iters,
             r0rc=m.get("r0rc"), r1rc=m.get("r1rc"), left=m.get("left"))
    r["key"] = f"{r['cell']}@{r['build']}"
    r["transparent_ok"] = int(rank_ok(k0, iters, True, bidir) and rank_ok(k1, iters, bidir, True))
    r["r0_outcome"], r["r1_outcome"] = k0.get("outcome"), k1.get("outcome")
    r["tx_rc"], r["tx_done"] = k0.get("tx_rc"), k0.get("tx_done")
    r["dev_bad_slots"], r["host_bad_slots"], r["signal_exact"] = (k1.get("dev_bad_slots"), k1.get("host_bad_slots"),
                                                                  k1.get("signal_exact"))
    r["r0_async"], r["r1_async"] = k0.get("async_first"), k1.get("async_first")
    r["decl_r0"] = ";".join(x[0] for x in l0["decl"])
    r["decl_r1"] = ";".join(x[0] for x in l1["decl"])
    r["tie_kept"], r["yielded"] = l0["kept"] + l1["kept"], l0["yld"] + l1["yld"]
    r["teardown_r0"], r["teardown_r1"] = k0.get("abort_ret"), k1.get("abort_ret")
    r["teardown_ms_r0"], r["teardown_ms_r1"] = k0.get("teardown_ms"), k1.get("teardown_ms")
    r["lat_p50_us"] = k0.get("lat_p50_us")
    r["lat_p50_raw"] = lat_p50_raw(stem + "_lat_raw.csv.gz")
    r["n_fires_r0"], r["n_fires_r1"] = len(l0["fires"]), len(l1["fires"])
    r["trigger_miss"] = l0["trig_miss"] + l1["trig_miss"]
    r["bind_fail"] = 1 if l0["bind"] else 0
    r["bind_r1"] = l1["bind"]
    r["ts_on_r0"], r["ts_on_r1"] = l0["ts_on"], l1["ts_on"]
    r["ts_src"] = ",".join(sorted(l0["ts_src"] | l1["ts_src"]))
    r["ua_src"] = ",".join(sorted(l0["ua_src"] | l1["ua_src"]))
    r["attach_fail"] = l0["attach_fail"] + l1["attach_fail"]
    # fault instant on rank 0's clock: first hook fire on either rank, else the kill
    cands = l0["fires"][:1] + ([l1["fires"][0] - off] if (l1["fires"] and off is not None) else [])
    fire = min(cands) if cands else None
    if fire is None and kill.get("kill_mono_ms") and off is not None:
        fire = float(kill["kill_mono_ms"]) - off
    r["fault_mono_r0"] = fire
    la0 = f(k0.get("launch_mono_ms"))
    r["fault_after_launch_ms"] = (fire - la0) if (fire is not None and la0) else None
    r["killed"] = 1 if kill.get("kill_mono_ms") else 0
    r["get_n"], r["get_bad"] = k0.get("get_n", ""), k0.get("get_bad", "")
    r["ua_r0"], r["ua_r1"] = l0["ua"], l1["ua"]
    r["n_mute_on_r0"] = len(l0["mute_on"])
    r["mute_on_ms_r0"] = l0["mute_on"][0] if l0["mute_on"] else None
    r["n_mute_on_r1"] = len(l1["mute_on"])
    r["mute_off_ms_r0"] = l0["mute_off"][0] if l0["mute_off"] else None
    r["n_sock_close_r0"] = len(l0["close"])
    r["sock_close_ms_r0"] = l0["close"][0][1] if l0["close"] else None
    r["sock_close_cause_r0"] = l0["close"][0][0] if l0["close"] else None
    r["sock_close_cause_r1"] = l1["close"][0][0] if l1["close"] else None
    r["sock_close_ms_r1"] = l1["close"][0][1] if l1["close"] else None
    r["n_sock_close_r1"] = len(l1["close"])
    r["decl_mono_r0"] = l0["decl"][0][1] if l0["decl"] else None
    # first async error per rank on rank 0's clock
    asyncs = []
    for k, sh in ((k0, 0.0), (k1, off)):
        if k.get("async_first") not in (None, "", "none"):
            la, ms = f(k.get("launch_mono_ms")), f(k.get("async_first_ms_after_launch"))
            if la is not None and ms is not None and sh is not None:
                asyncs.append(la + ms - sh)
    r["async_first_mono_r0clock"] = min(asyncs) if asyncs else None
    r["async_before_fault"] = 1 if (fire is not None and any(a < fire for a in asyncs)) else 0
    la1, km1 = f(k1.get("launch_mono_ms")), f(k1.get("kernel_ms"))
    r["r1_kernel_end_r0clock"] = (la1 + km1 - off) if (la1 is not None and km1 is not None and off is not None) else None
    d0 = r["decl_mono_r0"]
    r["r1_alive_at_decline"] = 1 if (d0 is not None and r["r1_kernel_end_r0clock"] is not None
                                     and r["r1_kernel_end_r0clock"] > d0
                                     and f(r["r1rc"]) not in (137.0, 139.0, 255.0)) else 0

    def pos(x):
        v = f(x)
        return v is not None and v > 0
    bad = (pos(r["dev_bad_slots"]) or pos(r["host_bad_slots"]) or f(r["signal_exact"]) == 0.0 or pos(r["get_bad"]))
    r["silent_bad"] = 1 if (r["tx_rc"] == "no error" and r["r0_async"] == "none" and bad) else 0
    # extra receiver-side facts used in the report
    r["r1_kernel_done"], r["r1_kernel_ms"] = k1.get("kernel_done"), k1.get("kernel_ms")
    r["r1_abort_start"] = f(k1.get("abort_start_mono_ms"))
    r["r1_post_abort_state"] = k1.get("post_abort_state")
    r["r1_kernel_exit_after_async_ms"] = k1.get("kernel_exit_after_async_ms")
    r["r1_async_ms"] = k1.get("async_first_ms_after_launch")
    r["r1_launch"] = la1
    r["clock_offset_ms"] = off
    r["first_line_time"] = None
    if l0["exists"]:
        for line in open(stem + "_r0.log", errors="replace"):
            mm = re.match(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\]", line)
            if mm:
                r["first_line_time"] = mm.group(1)
                break
    return r


def load():
    rows = []
    for sub in SUBDIRS:
        for meta in sorted(glob.glob(os.path.join(RES, sub, "*_meta.txt"))):
            rows.append(trial(sub, meta))
    return rows


# ---------------------------------------------------------------- exclusions (section 8) and settings checks
def excluded(r):
    if r["bind_fail"] == 1:
        return "bind_fail (rendezvous port in use)"
    fault = r["fault"]
    if fault in ("F1", "F1both") and r["n_fires_r0"] == 0:
        return "local QP fault not fired on rank 0"
    if fault == "F3" and r["n_fires_r1"] == 0:
        return "peer QP fault not fired on rank 1"
    if r["trigger_miss"] > 0:
        return "trigger_miss > 0"
    if fault == "F4" and not r["killed"]:
        return "no kill record"
    if r["cell"] == "get_f1_b" and not (r["fault_after_launch_ms"] is not None and r["fault_after_launch_ms"] > 0):
        return "get fault before first get"
    return ""


def settings_problems(r):
    p = []
    newlib = r["build"] in ("s2r", "s2rget")
    if newlib and r["ts"] == "1" and not (r["ts_on_r0"] >= 1 and r["ts_on_r1"] >= 1):
        p.append("ts_on missing")
    ua_on = "NCCL_GIN_TS_USER_ABORT=0" not in r["extra"]
    if newlib and r["ts"] == "1" and ua_on and not (r["ua_r0"] >= 1 and r["ua_r1"] >= 1):
        p.append("ua missing")
    if r["cell"].startswith("mute") and r["n_mute_on_r0"] < 1:
        p.append("mute_on missing")
    return p


# ---------------------------------------------------------------- acceptance grammar (section 3.2)
class V:
    """A cell value under the 3.2 rules: any comparison or arithmetic that involves None is false (or None)."""
    __slots__ = ("v",)

    def __init__(self, v):
        self.v = v.v if isinstance(v, V) else v

    @staticmethod
    def conv(x):
        if isinstance(x, V):
            return x.v
        return x

    def _cmp(self, o, op):
        a, b = self.v, V.conv(o)
        if a is None or b is None:
            return False
        if isinstance(a, str) != isinstance(b, str):
            return op in ("ne",)  # str vs number: only != is true
        return {"eq": a == b, "ne": a != b, "lt": a < b, "le": a <= b, "gt": a > b, "ge": a >= b}[op]

    def __eq__(self, o): return self._cmp(o, "eq")
    def __ne__(self, o): return self._cmp(o, "ne")
    def __lt__(self, o): return self._cmp(o, "lt")
    def __le__(self, o): return self._cmp(o, "le")
    def __gt__(self, o): return self._cmp(o, "gt")
    def __ge__(self, o): return self._cmp(o, "ge")
    __hash__ = None

    def _ar(self, o, fn):
        a, b = self.v, V.conv(o)
        if a is None or b is None or isinstance(a, str) or isinstance(b, str):
            return V(None)
        return V(fn(a, b))

    def __sub__(self, o): return self._ar(o, lambda a, b: a - b)
    def __rsub__(self, o): return self._ar(o, lambda a, b: b - a)
    def __add__(self, o): return self._ar(o, lambda a, b: a + b)
    def __radd__(self, o): return self._ar(o, lambda a, b: a + b)
    def __abs__(self): return V(None) if (self.v is None or isinstance(self.v, str)) else V(abs(self.v))
    def __bool__(self): return bool(self.v)
    def __repr__(self): return f"V({self.v!r})"


def cval(x):
    if x is None:
        return V(None)
    if isinstance(x, (int, float)):
        return V(float(x))
    s = str(x)
    if s == "":
        return V(None)
    try:
        return V(float(s))
    except ValueError:
        return V(s)


def has(F, s):
    v = V.conv(F)
    return isinstance(v, str) and v != "" and s in v


def nonempty(F):
    return V.conv(F) is not None


def maskbit(F, b):
    v = V.conv(F)
    if not isinstance(v, str):
        return False
    m = re.search(r"mask 0x([0-9a-fA-F]+)", v)
    return bool(m) and (int(m.group(1), 16) & int(b)) != 0


class Col:
    def __init__(self, name): self.name = name


def split_count(expr):
    """replace every count(E) by __c[i]; return the new expression and the list of E."""
    out, inner, i = "", [], 0
    while True:
        j = expr.find("count(", i)
        if j < 0:
            out += expr[i:]
            break
        out += expr[i:j]
        depth, k = 0, j + len("count")
        while True:
            ch = expr[k]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            elif ch == '"':
                k = expr.index('"', k + 1)
            k += 1
        inner.append(expr[j + len("count("):k])
        out += f"__c[{len(inner) - 1}]"
        i = k + 1
    return out, inner


class RowNS(dict):
    def __init__(self, row):
        super().__init__()
        self.row = row

    def __missing__(self, name):
        if name in self.row:
            return cval(self.row[name])
        raise NameError(name)


class TopNS(dict):
    def __missing__(self, name):
        return Col(name)


def evaluate(acc, trials_by_key, cells, scalars):
    """returns (holds: bool, per-cell detail list)"""
    per_cell = acc.startswith("per cell:")
    body = acc[len("per cell:"):].strip() if per_cell else acc
    expr, inner = split_count(body)
    groups = [[c] for c in cells] if per_cell else [cells]
    details, ok_all = [], True
    for grp in groups:
        trs = trials_by_key.get(grp[0], []) if len(grp) == 1 else trials_by_key.get(grp[0], [])
        counts = []
        for e in inner:
            n = 0
            for r in trs:
                ns = RowNS(r)
                ns.update(has=has, nonempty=nonempty, maskbit=maskbit, abs=abs)
                if eval(e, {"__builtins__": {}}, ns):
                    n += 1
            counts.append(n)

        def median(col, key):
            vals = [cval(r[col.name]).v for r in trials_by_key.get(key, [])]
            vals = [v for v in vals if isinstance(v, float)]
            return V(statistics.median(vals)) if vals else V(None)
        top = TopNS(__c=counts, median=median, abs=abs, has=has, nonempty=nonempty, maskbit=maskbit)
        top.update({k: V(v) for k, v in scalars.items()})
        ok = bool(eval(expr, {"__builtins__": {}}, top))
        details.append((grp[0] if per_cell else ",".join(grp), len(trs), counts, ok))
        ok_all = ok_all and ok
    return ok_all, details


# ---------------------------------------------------------------- safety records
def safety():
    out = []
    for snapb in sorted(glob.glob(os.path.join(RES, "snap_before-*.txt"))):
        tag = os.path.basename(snapb)[len("snap_before-"):-4]
        snapa = os.path.join(RES, f"snap_after-{tag}.txt")

        def rd(p):
            d, gpu = {}, []
            for line in open(p, errors="replace"):
                m = re.match(r"(rain|sunny) (mlx5 dmesg lines|mlx5 cmd_err lines|fwcmd failed sum): (\d+)", line)
                if m:
                    d[f"{m.group(1)} {m.group(2)}"] = int(m.group(3))
                if " gpu: " in line:
                    gpu.append(line.strip())
            return d, gpu
        b, gb = rd(snapb)
        a, ga = rd(snapa) if os.path.exists(snapa) else ({}, ["(no after snapshot)"])

        def fw(p):
            d = {}
            if not os.path.exists(p):
                return d
            for line in open(p, errors="replace"):
                m = re.match(r"(\S+_QP) (.*)", line)
                if m:
                    vals = dict(re.findall(r"(\w+)=(-?\d+)", m.group(2)))
                    d[m.group(1)] = (int(vals.get("failed", 0)), int(vals.get("failed_mbox_status", 0)))
            return d
        fb, fa = fw(os.path.join(RES, f"fwcmd_before-{tag}.txt")), fw(os.path.join(RES, f"fwcmd_after-{tag}.txt"))
        out.append(dict(tag=tag.split(":")[0], before=b, after=a, gpu_before=gb, gpu_after=ga,
                        fw_changed={k: (fb.get(k), fa.get(k)) for k in set(fb) | set(fa) if fb.get(k) != fa.get(k)}))
    return out


# ---------------------------------------------------------------- report
def rng(vals, fmt="%.1f"):
    vals = [v for v in vals if v is not None]
    if not vals:
        return "-"
    lo, hi = min(vals), max(vals)
    return (fmt % lo) if lo == hi else f"{fmt % lo}–{fmt % hi}"


def main():
    rows = load()
    print(f"# trials (meta files): {len(rows)}")
    for r in rows:
        r["excl"] = excluded(r)
        r["settings"] = settings_problems(r)
    by_key_all = defaultdict(list)
    for r in rows:
        by_key_all[r["key"]].append(r)
    # judged set: not excluded; if more than planned, the first ones by trial number
    judged = defaultdict(list)
    extra_over_plan = []
    for key, trs in by_key_all.items():
        ok = sorted([r for r in trs if not r["excl"]], key=lambda r: r["tnum"])
        n = PLAN.get(key)
        if n is not None and len(ok) > n:
            extra_over_plan += ok[n:]
            ok = ok[:n]
        judged[key] = ok

    print("\n## cells: planned / files / excluded / judged")
    for key in sorted(set(PLAN) | set(by_key_all)):
        trs = by_key_all.get(key, [])
        ex = [f"{r['trial']}:{r['excl']}" for r in trs if r["excl"]]
        print(f"{key:28s} plan={PLAN.get(key)} files={len(trs)} judged={len(judged.get(key, []))} excl={ex}")
    print("over plan:", [(r["key"], r["trial"]) for r in extra_over_plan])
    print("bind on rank 1 log:", [(r["key"], r["trial"]) for r in rows if r["bind_r1"]])
    print("settings problems:", [(r["key"], r["trial"], r["settings"]) for r in rows if r["settings"]])
    print("SO_ATTACH_FILTER failed lines:", sum(r["attach_fail"] for r in rows))
    lefts = [(r["key"], r["trial"], r["left"]) for r in rows if r["left"] not in ("0",)]
    print("left != 0:", lefts)
    print("bundle per build:", sorted(Counter((r["build"], r["bundle"]) for r in rows).items()))
    print("transparent-ON source line per build:", sorted(Counter((r["build"], r["ts_src"]) for r in rows).items()))
    print("user-abort source line per build:", sorted(Counter((r["build"], r["ua_src"]) for r in rows).items()))
    print("get kv present per build:", sorted(Counter((r["build"], r["get_n"] != "") for r in rows).items()))
    print("refills (trial > plan):", [(r["key"], r["trial"], r["first_line_time"]) for r in rows
                                      if PLAN.get(r["key"]) and r["tnum"] > PLAN[r["key"]]])
    print("excluded trial times:", [(r["key"], r["trial"], r["first_line_time"]) for r in rows if r["excl"]])
    print("\n## run conditions per cell (meta; compare with section 7)")
    for key in sorted(by_key_all):
        if key.startswith("lat_"):
            continue
        trs = by_key_all[key]
        inj = [int(r["inject"]) for r in trs]

        def uniq(name):
            return sorted(set(r[name] for r in trs))
        print(key, "fault", uniq("fault"), "app", uniq("app"), "ts", uniq("ts"), "iters", uniq("iters"), "bytes",
              uniq("bytes"), "gap_us", uniq("gap_us"), f"inject {min(inj)}–{max(inj)}", "extra", uniq("extra"))

    # gate micro-test
    gate_lines = [l for l in open(os.path.join(RES, "gate_test.txt"), errors="replace") if "gate_ce_test" in l]
    gate_pass = sum(1 for l in gate_lines if re.search(r"\bresult=PASS\b", l))
    cfgs = Counter()
    for l in gate_lines:
        g = dict(re.findall(r"(\w+)=(\S+)", l))
        cfgs[(l.split()[0], g.get("blocks"), g.get("tpb"), g.get("scope"), g.get("work_ns"))] += 1
    print(f"\n## gate: lines={len(gate_lines)} pass={gate_pass} configs={len(cfgs)}")

    # latency: kv p50 against p50 from the raw samples
    lat = [r for r in rows if r["cell"].startswith("lat_") and not r["excl"]]
    mism = [(r["key"], r["trial"], r["lat_p50_us"], r["lat_p50_raw"]) for r in lat
            if f(r["lat_p50_us"]) is None or r["lat_p50_raw"] is None or abs(f(r["lat_p50_us"]) - r["lat_p50_raw"]) > 0.006]
    print(f"\n## latency runs judged={len(lat)}; kv p50 vs raw p50 mismatches: {mism}")
    for key in sorted(k for k in judged if k.startswith("lat_")):
        v = [f(r["lat_p50_us"]) for r in judged[key]]
        vr = [r["lat_p50_raw"] for r in judged[key]]
        print(f"{key:24s} n={len(v)} median={statistics.median(v):.3f} runs={rng(v, '%.2f')} "
              f"values={[round(x, 2) for x in v]} raw-sample median={statistics.median(vr):.3f} "
              f"trials={[r['trial'] for r in judged[key]]}")
    # sensitivity: the refill runs (n6) ran in the fill hold, not interleaved with the other latency cells
    for key in ("lat_s2on_4k@s2", "lat_s2r_on_4k@s2r"):
        v = [f(r["lat_p50_us"]) for r in judged[key] if r["tnum"] <= 5]
        print(f"{key} without the refill run: n={len(v)} median={statistics.median(v):.3f}")
    allns = set()
    for r in lat:
        p = os.path.join(RES, r["sub"], r["stem"] + "_lat_raw.csv.gz")
        allns |= {int(l.split(",")[1]) % 32 for l in gzip.open(p, "rt") if l.strip()}
    print("latency samples modulo 32 ns:", sorted(allns))

    # predictions
    preds = list(csv.DictReader(open(os.path.join(STUDY, "predictions.csv"))))
    scalars = {"gate_pass": gate_pass}
    print("\n## predictions")
    verdicts = {}
    for p in preds:
        cells = [c.strip() for c in p["cells"].split(";")]
        if p["id"] == "RA4c":
            ok, det = evaluate(p["acceptance"], judged, ["gate"], scalars)
            verdict = "holds" if ok else "fails"
            if len(gate_lines) < GATE_PLAN:
                verdict = "insufficient"
        else:
            short = [c for c in cells if PLAN.get(c) is not None and len(judged.get(c, [])) < PLAN[c]]
            ok, det = evaluate(p["acceptance"], judged, cells, scalars)
            verdict = "insufficient" if short else ("holds" if ok else "fails")
        verdicts[p["id"]] = verdict
        print(f"{p['id']:5s} {verdict:12s} {det}")

    # observables per prediction (ranges are over the judged trials of the cell named)
    J = judged

    def col(key, name):
        return [r[name] for r in J[key]]

    print("\n## observables")
    for key in ("mt16_f1_b@s2", "mt64_f1_b@s2", "bidirf_sym_b@s2", "bidirf_sym_notie_b@s2", "f1_b@s2r", "f3_b@s2r",
                "f1g0_b@s2r", "mt256_f1_b@s2r", "bidirf_f1both_b@s2r", "get_none_b@s2rget", "mute1_f1_b@s2r"):
        print(key, "transparent", sum(col(key, "transparent_ok")), "/", len(J[key]),
              "tie(kept,yield)", [(r["tie_kept"], r["yielded"]) for r in J[key]],
              "decl_r0", Counter(col(key, "decl_r0")), "decl_r1", Counter(col(key, "decl_r1")))
    for key in ("f2rel_b@s2r", "ringf2rel_b@s2r", "f2rel_off_b@s2r"):
        t = [f(x) for x in col(key, "teardown_ms_r1")]
        print(key, "teardown_r1", Counter(col(key, "teardown_r1")), "r1rc", Counter(col(key, "r1rc")),
              "teardown_ms_r1", rng(t), "values", [round(x, 1) for x in t],
              "r1_outcome", Counter(col(key, "r1_outcome")), "ua_r1", Counter(col(key, "ua_r1")),
              "decl_r0", Counter(col(key, "decl_r0")),
              "teardown_ms_r0", rng([f(x) for x in col(key, "teardown_ms_r0")]),
              "r1 kernel_done", Counter(col(key, "r1_kernel_done")),
              "r1 kernel_ms", rng([f(x) for x in col(key, "r1_kernel_ms")]),
              "r1 abort start - (launch+async)", rng([r["r1_abort_start"] - r["r1_launch"] - f(r["r1_async_ms"])
                                                      for r in J[key]]),
              "post_abort_state", Counter(col(key, "r1_post_abort_state")),
              "kernel_exit_after_async_ms", Counter(col(key, "r1_kernel_exit_after_async_ms")))
    k = "f4_b@s2r"
    print(k, "decl_r0", Counter(col(k, "decl_r0")), "teardown_r0", Counter(col(k, "teardown_r0")),
          "teardown_ms_r0", rng([f(x) for x in col(k, "teardown_ms_r0")]), "killed", sum(col(k, "killed")))
    k = "off_f1_b@s2r"
    print(k, "r0rc", Counter(col(k, "r0rc")), "ua", Counter(zip(col(k, "ua_r0"), col(k, "ua_r1"))),
          "ts_on", Counter(zip(col(k, "ts_on_r0"), col(k, "ts_on_r1"))))
    for k in ("get_f1_b@s2rget", "get_none_b@s2rget"):
        print(k, "decl_r0", Counter(col(k, "decl_r0")), "silent_bad", sum(col(k, "silent_bad")),
              "transparent", sum(col(k, "transparent_ok")), "get_n", col(k, "get_n"), "get_bad", col(k, "get_bad"),
              "iters", set(col(k, "iters")), "fault_after_launch_ms", rng(col(k, "fault_after_launch_ms")),
              "inject", col(k, "inject"), "r0_outcome", Counter(col(k, "r0_outcome")),
              "tx_rc", Counter(col(k, "tx_rc")), "r0_async", Counter(col(k, "r0_async")))
    k = "mt1024_norescue_b@s2r"
    print(k, "decl_r0", Counter(col(k, "decl_r0")), "decl_r1", Counter(col(k, "decl_r1")), "silent_bad",
          sum(col(k, "silent_bad")), "transparent", sum(col(k, "transparent_ok")), "tx_rc", Counter(col(k, "tx_rc")))
    for k in ("mute8_f1_b@s2r", "mute_f3_b@s2r", "mute1_f1_b@s2r"):
        dt = [(r["sock_close_ms_r0"] - r["mute_on_ms_r0"]) if (r["sock_close_ms_r0"] is not None and
                                                               r["mute_on_ms_r0"] is not None) else None
              for r in J[k]]
        print(k, "n_mute_on_r0", Counter(col(k, "n_mute_on_r0")), "n_mute_on_r1", Counter(col(k, "n_mute_on_r1")),
              "n_sock_close_r0", Counter(col(k, "n_sock_close_r0")),
              "cause_r0", Counter(col(k, "sock_close_cause_r0")), "cause_r1", Counter(col(k, "sock_close_cause_r1")),
              "close-mute_on ms (r0)", rng(dt), "values", [None if x is None else round(x) for x in dt],
              "async_before_fault", Counter(col(k, "async_before_fault")),
              "decl_r0", Counter(col(k, "decl_r0")), "decl_r1", Counter(col(k, "decl_r1")),
              "r1_async", Counter(col(k, "r1_async")), "r0_async", Counter(col(k, "r0_async")),
              "r1_alive_at_decline", Counter(col(k, "r1_alive_at_decline")),
              "transparent", sum(col(k, "transparent_ok")),
              "fault_after_launch_ms", rng(col(k, "fault_after_launch_ms")),
              "decl - fault ms", rng([(r["decl_mono_r0"] - r["fault_mono_r0"]) if (r["decl_mono_r0"] and
                                     r["fault_mono_r0"]) else None for r in J[k]]),
              "r1 kernel end - decl ms", rng([(r["r1_kernel_end_r0clock"] - r["decl_mono_r0"])
                                              if (r["decl_mono_r0"] and r["r1_kernel_end_r0clock"]) else None
                                              for r in J[k]]),
              "mute_off-mute_on (r0)", rng([(r["mute_off_ms_r0"] - r["mute_on_ms_r0"]) if r["mute_off_ms_r0"]
                                            else None for r in J[k]]),
              "r1rc", Counter(col(k, "r1rc")), "r0rc", Counter(col(k, "r0rc")),
              "first async (r0 clock) - fault", rng([(r["async_first_mono_r0clock"] - r["fault_mono_r0"])
                                                     if (r["async_first_mono_r0clock"] and r["fault_mono_r0"])
                                                     else None for r in J[k]]))
    # trials of all cells: per-trial dump of the main observables for the report
    print("\n## per-trial dump")
    for key in sorted(J):
        for r in J[key]:
            print(key, r["trial"], "tok", r["transparent_ok"], "rc", r["r0rc"], r["r1rc"], "out", r["r0_outcome"],
                  r["r1_outcome"], "td", r["teardown_r0"], r["teardown_ms_r0"], r["teardown_r1"], r["teardown_ms_r1"],
                  "decl0", r["decl_r0"], "decl1", r["decl_r1"], "async", r["r0_async"], "|", r["r1_async"],
                  "fires", r["n_fires_r0"], r["n_fires_r1"], "left", r["left"], "p50", r["lat_p50_us"])

    print("\n## safety per hold")
    for s in safety():
        b, a = s["before"], s["after"]
        print(s["tag"], {k: (b.get(k), a.get(k)) for k in sorted(set(b) | set(a))}, "fw_changed", s["fw_changed"],
              "gpu users before/after", s["gpu_before"], s["gpu_after"])
    # consecutive left > 0
    seq = sorted(rows, key=lambda r: (r["first_line_time"] or "", r["stem"]))
    consec = [(x["stem"], y["stem"]) for x, y in zip(seq, seq[1:]) if x["left"] != "0" and y["left"] != "0"]
    print("consecutive left>0 pairs:", consec)
    print("\nsmoke dir exists:", os.path.isdir(os.path.join(os.path.dirname(RES), os.path.basename(RES) + "_smoke")))
    print("\nverdicts:", Counter(verdicts.values()), verdicts)


if __name__ == "__main__":
    main()
