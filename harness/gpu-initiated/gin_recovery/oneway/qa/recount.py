#!/usr/bin/env python3
"""gin-oneway: independent recount of the main run from the raw per-trial files.

usage: qa/recount.py [results/20261008]

Written without reading or running score.py, posthoc_ow.py, rows_ow.py, SCORE.md, trials_scored.csv or the untracked
trials_*.csv. Column definitions come from EXPERIMENT.md 3.1 (and, for the inherited columns, from
../scripts/ts2/rows.py, ../s2_close/rows_extra.py and ../pair_check/rows_pc.py, read only for their definitions; every
column here is parsed again from the logs). The acceptance strings are read from predictions.csv and evaluated by the
small evaluator below that follows ../s2_close/EXPERIMENT.md 3.2 (blank -> None; any comparison or arithmetic with
None is false). The post-hoc count follows DEVIATIONS.md 3: dead lines of rank r earlier than the other rank's first
"communicator teardown" t0_mono_ms, both on rank 0's clock (rank 1 time minus rank 0 kv clock_offset_ms); all dead
lines when the other rank has no such line. Prints the report to stdout; writes nothing.
"""
import csv, glob, gzip, os, re, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
RES = sys.argv[1] if len(sys.argv) > 1 else os.path.join(STUDY, "results", "20261008")

# ---------------------------------------------------------------- planned trial set (EXPERIMENT.md 7)
PLAN = {
    "ow_r1in_f1_b@ow": 10, "ow_r1in_f1_b@pcm": 5,
    "ow_r0in_f1r1_b@ow": 10, "ow_r0in_f1r1_b@pcm": 5,
    "ow_kill0_b@ow": 10, "ow_kill0_b@pcm": 5,
    "ow_hello_f1_b@ow": 10, "ow_hello_f1_b@pcm": 5,
    "ow_r0in_nat_f1r1_b@pc": 5, "ow_r0in_nat_f1r1_b@ow": 5,
    "f1_b@ow": 5, "f3_b@ow": 5, "bidirf_sym_b@ow": 5, "f4_b@ow": 5, "f2rel_b@ow": 5,
    "rc_mute8_f1_b@ow": 5, "rc_mutekill_b@ow": 5,
    "lat_pc_on_4k@pc": 5, "lat_pc_on_256k@pc": 5, "lat_ow_on_4k@ow": 5, "lat_ow_on_256k@ow": 5,
}
# source line of the "transparent recovery ON" WARN per build (WARN macro start line + 4 in the build trees:
# pc 4173, pcm 4200, ow 4365)
START_LINE = {"pc": "4177", "pcm": "4204", "ow": "4369"}

# ---------------------------------------------------------------- parsing
def kvfile(path):
    d = {}
    if not os.path.exists(path):
        return d
    for line in open(path, errors="replace"):
        for m in re.finditer(r"(\w+)=(.*?)(?= \w+=|$)", line.rstrip("\n")):
            d[m.group(1)] = m.group(2).strip().strip('"')
    return d

R = {
    "close": re.compile(r"GIN/TS: rank (\d+): socket to rank (\d+) closed cause=(\S+) mono_ms=([\d.]+) liveness=(\w+)"),
    "reconn": re.compile(r"GIN/TS: rank (\d+): socket to rank (\d+) reconnected gen=(\d+) attempts=(\d+) mono_ms=([\d.]+)"),
    "notacc": re.compile(r"GIN/TS: rank (\d+): re-dial to rank (\d+) not accepted \((.*)\) attempts=(\d+) mono_ms=([\d.]+)"),
    "pref": re.compile(r"GIN/TS: rank (\d+): probe of rank (\d+) refused \(ECONNREFUSED\) mono_ms=([\d.]+)"),
    "pans": re.compile(r"GIN/TS: rank (\d+): probe of rank (\d+) answered mono_ms=([\d.]+)"),
    "refuse": re.compile(r"GIN/TS: TEST refused a reconnect HELLO from rank (\d+) gen=(\d+) mono_ms=([\d.]+)"),
    "wait": re.compile(r"GIN/TS: rank (\d+): reconnect wait for rank (\d+) ended=(\w+) wait_ms=([\d.]+) mono_ms=([\d.]+)"),
    "decl": re.compile(r'GIN/TS: declined rank=(\d+) peer=(\d+) reason="([^"]*)" class=(\d+) mono_ms=([\d.]+)'),
    "mon": re.compile(r"GIN/TS: TEST socket mute on rank=(\d+) peers=(\d+) mono_ms=([\d.]+)"),
    "moff": re.compile(r"GIN/TS: TEST socket mute off rank=(\d+) peers=(\d+) mono_ms=([\d.]+)"),
    "knobs": re.compile(r"GIN/TS: TEST socket knobs rank=(\d+) uto_ms=(\d+) refuse_hello=(\d+)"),
    "ow": re.compile(r"GIN/TS: helper liveness oneway=(\d+) rank=(\d+)"),
    "pc": re.compile(r"GIN/TS: pair check=(\d+) rank=(\d+)"),
    "td": re.compile(r"GIN/TS: communicator teardown rank=(\d+):.*\bt0_mono_ms=([\d.]+)"),
    "qpst": re.compile(r"GIN/TS: rank \d+ qp states to rank \d+: \[([^\]]*)\]"),
    "fire": re.compile(r"GIN/FAULT: GDAKI fault fired.*?(?:context=(\d+) )?fire_mono_ms=([\d.]+)"),
    "start": re.compile(r"gin_host_gdaki\.cc:(\d+) \(gdakiTsStart\) NCCL WARN GIN/TS: transparent recovery ON"),
}

def parse_log(path):
    o = {k: [] for k in ("close", "reconn", "notacc", "pref", "pans", "refuse", "wait", "decl", "mon", "moff", "knobs",
                         "ow", "pc", "td", "qpst", "fire", "q4", "rec", "start")}
    o.update(ts_on=0, ua=0, trigger_miss=0, bind=0, lines=0)
    if not os.path.exists(path):
        o["missing"] = True
        return o
    for line in open(path, errors="replace"):
        o["lines"] += 1
        if "GIN/TS: transparent recovery ON" in line:
            o["ts_on"] += 1
        if "GIN/TS: user devComm abort flag set" in line:
            o["ua"] += 1
        if "GIN/FAULT: shot 1 trigger not reached" in line:
            o["trigger_miss"] += 1
        if "bind: Address already in use" in line:
            o["bind"] += 1
        if "device-classified error CQE" in line:
            ms = re.findall(r"\bmono_ms=([\d.]+)", line)
            cl = re.search(r"\bclass=(\w+)", line)
            o["q4"].append((float(ms[-1]) if ms else None, cl.group(1) if cl else ""))
            continue
        if "GIN/TS: recovered " in line:
            m = re.search(r"\brole=(\w+)", line)
            o["rec"].append(m.group(1) if m else "")
            continue
        for k, rx in R.items():
            m = rx.search(line)
            if m:
                o[k].append(m.groups())
    return o

def fl(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None

def rank_ok(k, iters, sender, receiver):
    if k.get("outcome") != "ok" or k.get("async_first") != "none":
        return False
    if sender and not (k.get("tx_done") == str(iters) and k.get("tx_rc") == "no error"):
        return False
    if receiver and not (k.get("rx_done") == str(iters) and k.get("rx_rc") == "no error" and k.get("dev_bad_slots") == "0"
                         and k.get("host_bad_slots") == "0" and k.get("signal_exact") == "1"):
        return False
    return True

def load(sub):
    out = []
    for meta in sorted(glob.glob(os.path.join(RES, sub, "*_meta.txt"))):
        stem = meta[:-len("_meta.txt")]
        m = kvfile(meta)
        t = {"stem": os.path.relpath(stem, RES), "sub": sub, "meta": m}
        t["k0"], t["k1"] = kvfile(stem + "_r0.kv"), kvfile(stem + "_r1.kv")
        t["l0"], t["l1"] = parse_log(stem + "_r0.log"), parse_log(stem + "_r1.log")
        t["kill"] = kvfile(stem + "_kill.out")
        t["killraw"] = open(stem + "_kill.out").read().strip() if os.path.exists(stem + "_kill.out") else ""
        t["latraw"] = stem + "_lat_raw.csv.gz" if os.path.exists(stem + "_lat_raw.csv.gz") else None
        t["files"] = sorted(os.path.basename(p)[len(os.path.basename(stem)) + 1:] for p in glob.glob(stem + "_*"))
        out.append(t)
    return out

# ---------------------------------------------------------------- columns (EXPERIMENT.md 3.1)
def columns(t):
    m, k0, k1, l0, l1 = t["meta"], t["k0"], t["k1"], t["l0"], t["l1"]
    off = fl(k0.get("clock_offset_ms"))  # rank1 - rank0
    iters = int(m.get("iters", "0"))
    bidir = m.get("app") == "bidir"
    c = {"cell": m.get("cell"), "build": m.get("build"), "iters": iters, "key": "%s@%s" % (m.get("cell"), m.get("build")),
         "off": off}
    c["transparent_ok"] = int(rank_ok(k0, iters, True, bidir) and rank_ok(k1, iters, bidir, True))
    c["r1rc"], c["r0rc"] = fl(m.get("r1rc")), fl(m.get("r0rc"))
    c["left"] = fl(m.get("left"))
    c["r1_outcome"], c["r0_outcome"] = k1.get("outcome"), k0.get("outcome")
    for r, l, k in ((0, l0, k0), (1, l1, k1)):
        c["decl_r%d" % r] = ";".join(x[2] for x in l["decl"])
        c["decl_ms_r%d" % r] = float(l["decl"][0][4]) if l["decl"] else None
        c["rec_init_r%d" % r] = sum(1 for x in l["rec"] if x == "initiator")
        c["rec_resp_r%d" % r] = sum(1 for x in l["rec"] if x == "responder")
        c["teardown_r%d" % r] = k.get("abort_ret")
        c["teardown_ms_r%d" % r] = fl(k.get("teardown_ms"))
        c["n_fires_r%d" % r] = len(l["fire"])
        c["ts_on_r%d" % r] = l["ts_on"]
        c["ua_r%d" % r] = l["ua"]
        c["pc_mode_r%d" % r] = fl(l["pc"][0][0]) if l["pc"] else None
        c["ow_mode_r%d" % r] = fl(l["ow"][0][0]) if l["ow"] else None
        c["knob_uto_r%d" % r] = fl(l["knobs"][0][1]) if l["knobs"] else None
        c["knob_refuse_r%d" % r] = fl(l["knobs"][0][2]) if l["knobs"] else None
        c["n_knob_lines_r%d" % r] = len(l["knobs"])
        c["n_mute_on_r%d" % r] = len(l["mon"])
        c["mute_on_ms_r%d" % r] = float(l["mon"][0][2]) if l["mon"] else None
        c["mute_off_ms_r%d" % r] = float(l["moff"][0][2]) if l["moff"] else None
        cl = l["close"]
        c["close1_cause_r%d" % r] = cl[0][2] if cl else None
        c["close1_lv_r%d" % r] = cl[0][4] if cl else None
        c["close1_ms_r%d" % r] = float(cl[0][3]) if cl else None
        dead = [x for x in cl if x[4] == "dead"]
        c["n_dead_r%d" % r] = len(dead)
        c["dead_cause_r%d" % r] = dead[0][2] if dead else None
        c["dead_ms_r%d" % r] = float(dead[0][3]) if dead else None
        c["n_reconn_r%d" % r] = len(l["reconn"])
        c["reconn_ms_r%d" % r] = float(l["reconn"][0][4]) if l["reconn"] else None
        c["wait_end_r%d" % r] = l["wait"][0][2] if l["wait"] else None
        c["wait_ms_r%d" % r] = float(l["wait"][0][3]) if l["wait"] else None
        c["q4_ms_r%d" % r] = l["q4"][0][0] if l["q4"] else None
        c["n_notrts_r%d" % r] = (sum(1 for x in l["qpst"][0][0].split(",") if x.strip() != "3") if l["qpst"] else None)
        c["td_t0_r%d" % r] = float(l["td"][0][1]) if l["td"] else None
        c["abort_start_r%d" % r] = fl(k.get("abort_start_mono_ms"))
    c["n_notacc_r0"] = len(l0["notacc"])
    c["n_probe_ref_r1"] = len(l1["pref"])
    c["n_probe_ans_r1"] = len(l1["pans"])
    c["n_refuse_test_r1"] = len(l1["refuse"])
    f1 = l1["fire"][0] if l1["fire"] else None
    c["inj_ctx_r1"] = fl(f1[0]) if (f1 and f1[0] is not None) else None
    c["trigger_miss"] = l0["trigger_miss"] + l1["trigger_miss"]
    c["bind_fail"] = 1 if l0["bind"] else 0
    c["killed"] = 1 if t["kill"].get("kill_mono_ms") else 0
    c["r0_killed"] = 1 if (t["kill"].get("kill_mono_ms") and re.search(r"\brank=0\b", t["killraw"])) else 0
    c["kill_ms"] = fl(t["kill"].get("kill_mono_ms"))
    # unmute: latest mute-off among ranks that have one, on rank 0's clock
    offs = []
    if c["mute_off_ms_r0"] is not None:
        offs.append(c["mute_off_ms_r0"])
    if c["mute_off_ms_r1"] is not None and off is not None:
        offs.append(c["mute_off_ms_r1"] - off)
    c["unmute_ms"] = max(offs) if offs else None
    for r in (0, 1):
        rc = c["reconn_ms_r%d" % r]
        if rc is not None and r == 1:
            rc = rc - off if off is not None else None
        c["reconn_after_unmute_ms_r%d" % r] = (rc - c["unmute_ms"]) if (rc is not None and c["unmute_ms"] is not None) else None
    c["decl_after_q4_ms_r1"] = (c["decl_ms_r1"] - c["q4_ms_r1"]) if (c["decl_ms_r1"] is not None and c["q4_ms_r1"] is not None) else None
    # inherited: fault instant on rank 0's clock (first hook fire on either rank; else the kill record moved as rows.py does)
    cands = []
    if l0["fire"]:
        cands.append(float(l0["fire"][0][1]))
    if l1["fire"] and off is not None:
        cands.append(float(l1["fire"][0][1]) - off)
    fault = min(cands) if cands else None
    if fault is None and c["kill_ms"] is not None and off is not None:
        fault = c["kill_ms"] - off  # rows.py convention (kill on rank 1's clock); meaningless for a rank 0 kill
    c["fault_mono_r0"] = fault
    asyncs = []
    for k, is1 in ((k0, False), (k1, True)):
        if k.get("async_first") not in (None, "", "none"):
            la, ms = fl(k.get("launch_mono_ms")), fl(k.get("async_first_ms_after_launch"))
            if la is not None and ms is not None and (not is1 or off is not None):
                asyncs.append(la + ms - (off if is1 else 0.0))
    c["async_before_fault"] = 1 if (fault is not None and any(a < fault for a in asyncs)) else 0
    la1, km1 = fl(k1.get("launch_mono_ms")), fl(k1.get("kernel_ms"))
    d0 = c["decl_ms_r0"]
    c["r1_alive_at_decline"] = int(d0 is not None and la1 is not None and km1 is not None and off is not None
                                   and la1 + km1 - off > d0 and c["r1rc"] not in (137.0, 139.0, 255.0))
    c["lat_p50_us"] = fl(k0.get("lat_p50_us"))
    # ---- post-hoc (DEVIATIONS.md 3): dead lines before the other rank's teardown start, rank 0's clock
    to0 = lambda r, x: x if r == 0 else (x - off)
    for r in (0, 1):
        o = 1 - r
        lr = l0 if r == 0 else l1
        other_t0 = c["td_t0_r%d" % o]
        dead = [(x[2], to0(r, float(x[3]))) for x in lr["close"] if x[4] == "dead"]
        if other_t0 is None:
            live = dead
        else:
            ot = to0(o, other_t0)
            live = [x for x in dead if x[1] < ot]
        c["n_dead_live_r%d" % r] = len(live)
        c["dead_live_r%d" % r] = live
        c["dead_all_r%d" % r] = dead
        # the same with the kv abort_start_mono_ms as the teardown start (cross-check)
        oa = c["abort_start_r%d" % o]
        if other_t0 is None:
            c["n_dead_live_kv_r%d" % r] = len(dead)
        else:
            c["n_dead_live_kv_r%d" % r] = len([x for x in dead if oa is not None and x[1] < to0(o, oa)])
        # margin of each dead line to the other rank's teardown start (positive: after it)
        c["dead_margin_r%d" % r] = [x[1] - to0(o, other_t0) for x in dead] if other_t0 is not None else []
    return c

# ---------------------------------------------------------------- exclusion (EXPERIMENT.md 8) and setup checks
HOOK0 = {"ow_r1in_f1_b", "ow_hello_f1_b", "f1_b", "rc_mute8_f1_b"}
HOOK1 = {"ow_r0in_f1r1_b", "ow_r0in_nat_f1r1_b", "f3_b"}
KILL1 = {"f4_b", "rc_mutekill_b"}

def exclusion(c, t):
    why = []
    cell = c["cell"]
    if c["bind_fail"] == 1:
        why.append("bind_fail")
    if cell in HOOK0 and c["n_fires_r0"] == 0:
        why.append("n_fires_r0==0")
    if cell in HOOK1 and c["n_fires_r1"] == 0:
        why.append("n_fires_r1==0")
    if cell == "bidirf_sym_b" and (c["n_fires_r0"] == 0 or c["n_fires_r1"] == 0):
        why.append("fires")
    if c["trigger_miss"] > 0:
        why.append("trigger_miss")
    if cell in KILL1 and c["killed"] != 1:
        why.append("killed!=1")
    if cell == "ow_kill0_b" and (c["r0_killed"] != 1 or c["q4_ms_r1"] is None):
        why.append("r0_killed/q4_ms_r1")
    if cell in ("ow_r0in_f1r1_b", "ow_r0in_nat_f1r1_b", "ow_kill0_b"):
        if c["close1_ms_r1"] is None or (c["q4_ms_r1"] is not None and c["q4_ms_r1"] < c["close1_ms_r1"]):
            why.append("order r1")
    if cell == "rc_mutekill_b":
        if c["close1_ms_r0"] is None or (c["q4_ms_r0"] is not None and c["q4_ms_r0"] < c["close1_ms_r0"]):
            why.append("order r0")
    return why

def setup_check(c, t):
    bad = []
    if t["meta"].get("ts") == "1":
        for k in ("ts_on_r0", "ts_on_r1", "ua_r0", "ua_r1"):
            if not (c[k] >= 1):
                bad.append(k)
    if not (c["pc_mode_r0"] == 1 and c["pc_mode_r1"] == 1):
        bad.append("pc_mode")
    if c["build"] == "ow":
        if not (c["ow_mode_r0"] == 1 and c["ow_mode_r1"] == 1):
            bad.append("ow_mode")
    elif not (c["ow_mode_r0"] is None and c["ow_mode_r1"] is None):
        bad.append("ow_mode not blank")
    cell = c["cell"]
    n0, n1 = c["n_knob_lines_r0"], c["n_knob_lines_r1"]
    if cell == "ow_r1in_f1_b":
        ok = c["knob_uto_r0"] == 20000 and n1 == 0
    elif cell == "ow_r0in_f1r1_b":
        ok = c["knob_uto_r1"] == 20000 and n0 == 0
    elif cell == "ow_hello_f1_b":
        ok = c["knob_refuse_r1"] == 1 and n0 == 0
    else:
        ok = n0 == 0 and n1 == 0
    if not ok:
        bad.append("knobs")
    m0, m1 = c["n_mute_on_r0"], c["n_mute_on_r1"]
    if cell == "ow_r1in_f1_b" and not (m1 >= 1 and m0 == 0):
        bad.append("mute")
    if cell in ("ow_r0in_f1r1_b", "ow_r0in_nat_f1r1_b") and not (m0 >= 1 and m1 == 0):
        bad.append("mute")
    if cell in ("ow_kill0_b", "ow_hello_f1_b", "rc_mute8_f1_b", "rc_mutekill_b") and not (m0 >= 1 and m1 >= 1):
        bad.append("mute")
    if cell in ("ow_r0in_f1r1_b", "ow_r0in_nat_f1r1_b") and c["inj_ctx_r1"] != 1:
        bad.append("inj_ctx_r1")
    return bad

# ---------------------------------------------------------------- acceptance evaluator (../s2_close/EXPERIMENT.md 3.2)
class Null:
    def _f(self, *a):
        return False
    __eq__ = __ne__ = __lt__ = __le__ = __gt__ = __ge__ = _f
    def _n(self, *a):
        return self
    __add__ = __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = __truediv__ = __rtruediv__ = __neg__ = __abs__ = _n
    def __bool__(self):
        return False
    __hash__ = object.__hash__
NULL = Null()

def val(x):
    if x is None or x == "":
        return NULL
    if isinstance(x, (int, float)):
        return float(x)
    v = fl(x)
    return v if v is not None else str(x)

def has(F, s):
    return isinstance(F, str) and s in F

def nonempty(F):
    return not isinstance(F, Null)

def split_count(expr):
    """Replace each count(...) by a placeholder; return (outer, [inner,...])."""
    out, inners, i = "", [], 0
    while True:
        j = expr.find("count(", i)
        if j < 0:
            out += expr[i:]
            break
        out += expr[i:j]
        k, depth = j + len("count("), 1
        while depth:
            if expr[k] == "(":
                depth += 1
            elif expr[k] == ")":
                depth -= 1
            k += 1
        inners.append(expr[j + len("count("):k - 1])
        out += "__C%d" % (len(inners) - 1)
        i = k
    return out, inners

def evaluate(acc, keys, rows_by_key, colmap=None):
    """Returns (verdict, detail) with detail = [(key, n, hits)]."""
    colmap = colmap or {}
    per_cell = acc.startswith("per cell:")
    body = acc[len("per cell:"):].strip() if per_cell else acc
    groups = [[k] for k in keys] if per_cell else [keys]
    verdicts, detail = [], []
    for g in groups:
        if any(len(rows_by_key.get(k, [])) < PLAN[k] for k in g):
            verdicts.append("insufficient")
            detail.append((g, [len(rows_by_key.get(k, [])) for k in g], None))
            continue
        outer, inners = split_count(body)
        ns = {}
        for i, inner in enumerate(inners):
            rows = rows_by_key[g[0]]
            hits = 0
            for c in rows:
                env = {name: val(c.get(colmap.get(name, name))) for name in set(re.findall(r"[A-Za-z_]\w*", inner))
                       if name not in ("and", "or", "not", "has", "nonempty", "abs")}
                env.update(has=has, nonempty=nonempty, abs=abs)
                r = eval(inner, {"__builtins__": {}}, env)
                hits += 1 if (r is True or (not isinstance(r, Null) and bool(r))) else 0
            ns["__C%d" % i] = hits
            detail.append((g, len(rows), hits))
        def median(col, key):
            return statistics.median(c[col] for c in rows_by_key[key])
        names = {n: n for n in set(re.findall(r"[A-Za-z_]\w*", outer)) if n not in ns}
        ns.update(names)
        ns.update(median=median, abs=abs)
        r = eval(outer, {"__builtins__": {}}, ns)
        if not inners:
            detail.append((g, [len(rows_by_key[k]) for k in g], None))
        verdicts.append("hold" if r else "fail")
    if "insufficient" in verdicts:
        v = "insufficient"
    else:
        v = "hold" if all(x == "hold" for x in verdicts) else "fail"
    return v, detail

# ---------------------------------------------------------------- main
def rng(xs, fmt="%.1f"):
    xs = [x for x in xs if x is not None]
    if not xs:
        return "none"
    return (fmt + "–" + fmt) % (min(xs), max(xs)) + " (n=%d)" % len(xs)

def main():
    trials = []
    for sub in ("ow", "pcm", "pc", "lat"):
        trials += load(sub)
    print("== trial set")
    rows_by_key, excluded, setup_bad = {}, [], []
    for t in trials:
        c = columns(t)
        c["stem"] = t["stem"]
        t["c"] = c
        # bundle checks: folder, meta build, bundle path, source line of the start WARN in both logs
        b = c["build"]
        bpath = t["meta"].get("bundle", "")
        lines = {x[0] for x in t["l0"]["start"]} | {x[0] for x in t["l1"]["start"]}
        if not (bpath.endswith("/gin_ts2/" + b) and (t["sub"] == "lat" or t["sub"] == b) and lines == {START_LINE[b]}):
            print("BUNDLE MISMATCH", t["stem"], b, bpath, lines)
        need = {"meta.txt", "r0.kv", "r0.log", "r1.kv", "r1.log"}
        if not need <= set(t["files"]):
            print("MISSING FILES", t["stem"], t["files"])
        why = exclusion(c, t)
        bad = setup_check(c, t)
        if why:
            excluded.append((t["stem"], why))
        if bad:
            setup_bad.append((t["stem"], bad))
        if not why:
            rows_by_key.setdefault(c["key"], []).append(c)
    keys_seen = sorted(set(t["c"]["key"] for t in trials))
    for k in sorted(PLAN):
        n_all = sum(1 for t in trials if t["c"]["key"] == k)
        print("  %-26s planned %2d  files %2d  scored %2d" % (k, PLAN[k], n_all, len(rows_by_key.get(k, []))))
    extra = [k for k in keys_seen if k not in PLAN]
    print("  keys outside the plan:", extra or "none")
    print("  total trials %d (cell %d, latency %d)" % (len(trials), sum(1 for t in trials if t["sub"] != "lat"),
                                                       sum(1 for t in trials if t["sub"] == "lat")))
    print("  excluded:", excluded or "none")
    print("  setup check failures:", setup_bad or "none")
    lefts = [(t["stem"], t["c"]["left"]) for t in trials if (t["c"]["left"] or 0) > 0]
    print("  left > 0:", lefts or "none")
    print("  bind_fail:", sum(t["c"]["bind_fail"] for t in trials), " trigger_miss:", sum(t["c"]["trigger_miss"] for t in trials))

    # ---- predictions
    preds = list(csv.DictReader(open(os.path.join(STUDY, "predictions.csv"))))
    print("\n== predictions (frozen rules)")
    POSTHOC = {"A1", "B1", "E1", "U2", "G2"}
    for p in preds:
        keys = [k.strip() for k in p["cells"].split(";")]
        v, det = evaluate(p["acceptance"], keys, rows_by_key)
        miss = []
        if "count(" in p["acceptance"] and v != "insufficient":
            outer, inners = split_count(p["acceptance"].replace("per cell:", "").strip())
            for k in keys:
                for c in rows_by_key[k]:
                    env = {name: val(c.get(name)) for name in set(re.findall(r"[A-Za-z_]\w*", inners[0]))
                           if name not in ("and", "or", "not", "has", "nonempty", "abs")}
                    env.update(has=has, nonempty=nonempty, abs=abs)
                    r = eval(inners[0], {"__builtins__": {}}, env)
                    if not (r is True or (not isinstance(r, Null) and bool(r))):
                        miss.append(c["stem"])
        print("  %-3s %-12s %s  %s" % (p["id"], v, det, p["acceptance"]))
        if miss:
            print("      missed:", miss)
        if p["id"] in POSTHOC:
            colmap = {"n_dead_r0": "n_dead_live_r0", "n_dead_r1": "n_dead_live_r1"}
            v2, det2 = evaluate(p["acceptance"], keys, rows_by_key, colmap)
            print("      post-hoc (n_dead_live_r*): %s %s" % (v2, det2))
            colmap = {"n_dead_r0": "n_dead_live_kv_r0", "n_dead_r1": "n_dead_live_kv_r1"}
            v3, det3 = evaluate(p["acceptance"], keys, rows_by_key, colmap)
            print("      post-hoc with kv abort_start as teardown start: %s %s" % (v3, det3))
    return trials, rows_by_key

def report(trials, rows_by_key):
    K = rows_by_key
    def col(key, name):
        return [c[name] for c in K[key]]
    print("\n== one-way cells: who timed out first, when the other got the reset (rank 0 clock)")
    for key in ("ow_r1in_f1_b@ow", "ow_r1in_f1_b@pcm", "ow_r0in_f1r1_b@ow", "ow_r0in_f1r1_b@pcm",
                "ow_r0in_nat_f1r1_b@pc", "ow_r0in_nat_f1r1_b@ow"):
        print(" ", key)
        for c in K[key]:
            off = c["off"]
            t0 = c["close1_ms_r0"]
            t1 = c["close1_ms_r1"] - off if c["close1_ms_r1"] is not None else None
            mon = c["mute_on_ms_r0"] if c["mute_on_ms_r0"] is not None else (c["mute_on_ms_r1"] - off)
            first = "r0" if t0 < t1 else "r1"
            print("    %-28s r0 %-10s %-7s  r1 %-10s %-7s  first=%s  r0-mute_on %.1f  r1-mute_on %.1f  later-earlier %.1f ms"
                  % (c["stem"], c["close1_cause_r0"], c["close1_lv_r0"], c["close1_cause_r1"], c["close1_lv_r1"], first,
                     t0 - mon, t1 - mon, abs(t1 - t0)))
    print("\n== every close line by cell@build and rank: (cause, liveness) counts")
    allkeys = sorted(K)
    for key in allkeys:
        cnt = {}
        for t in trials:
            if t["c"]["key"] != key:
                continue
            for r, l in ((0, t["l0"]), (1, t["l1"])):
                for x in l["close"]:
                    cnt[(r, x[2], x[4])] = cnt.get((r, x[2], x[4]), 0) + 1
        if cnt:
            print("  %-26s %s" % (key, ", ".join("r%d %s/%s x%d" % (k[0], k[1], k[2], v) for k, v in sorted(cnt.items()))))
    print("\n== dead lines vs the other rank's teardown start (post-hoc split), per cell@build")
    for key in allkeys:
        live, after, margins, causes = 0, 0, [], {}
        for c in K[key]:
            for r in (0, 1):
                n = len(c["dead_all_r%d" % r])
                live += c["n_dead_live_r%d" % r]
                after += n - c["n_dead_live_r%d" % r]
                margins += [m for m in c["dead_margin_r%d" % r] if m >= 0]
                for x in c["dead_live_r%d" % r]:
                    causes[(r, x[0])] = causes.get((r, x[0]), 0) + 1
        if live or after:
            print("  %-26s before-teardown %2d %s | after %2d, margin %s ms" % (
                key, live, {"r%d %s" % k: v for k, v in causes.items()}, after, rng(margins, "%.2f")))
        kvdiff = [c for c in K[key] for r in (0, 1) if c["n_dead_live_r%d" % r] != c["n_dead_live_kv_r%d" % r]]
        if kvdiff:
            print("    kv abort_start changes the split in", len(kvdiff), "rank-trials")
    print("\n  dead lines before teardown in kill cells, relative to the kill (rank 0 clock):")
    for key in ("f4_b@ow", "rc_mutekill_b@ow", "ow_kill0_b@ow", "ow_kill0_b@pcm"):
        for c in K[key]:
            for r in (0, 1):
                for cause, ms in c["dead_live_r%d" % r]:
                    # kill.out clock: rank 0 kill on rain (rank 0 clock); rank 1 kill on sunny (rank 1 clock)
                    kill0 = c["kill_ms"] if c["r0_killed"] else c["kill_ms"] - c["off"]
                    print("    %-28s r%d %-12s %.1f ms after the kill" % (c["stem"], r, cause, ms - kill0))
    print("\n== reconnects after unmute (ms, rank 0 clock)")
    for key in ("ow_r1in_f1_b@ow", "ow_r0in_f1r1_b@ow", "ow_r0in_nat_f1r1_b@ow", "ow_r0in_nat_f1r1_b@pc",
                "ow_hello_f1_b@ow", "rc_mute8_f1_b@ow", "ow_r1in_f1_b@pcm", "ow_r0in_f1r1_b@pcm", "ow_hello_f1_b@pcm"):
        print("  %-26s n_reconn r0 %s r1 %s | r0 %s | r1 %s" % (
            key, sorted(set(col(key, "n_reconn_r0"))), sorted(set(col(key, "n_reconn_r1"))),
            rng(col(key, "reconn_after_unmute_ms_r0")), rng(col(key, "reconn_after_unmute_ms_r1"))))
    print("\n== rank 1 waits")
    for key in sorted(K):
        w = [(c["wait_end_r1"], c["wait_ms_r1"]) for c in K[key] if c["wait_end_r1"] is not None]
        w0 = [(c["wait_end_r0"], c["wait_ms_r0"]) for c in K[key] if c["wait_end_r0"] is not None]
        if w or w0:
            ends = {}
            for e, _ in w:
                ends[e] = ends.get(e, 0) + 1
            print("  %-26s r1 ends %s wait_ms %s; r0 waits %d" % (key, ends, rng([x[1] for x in w]), len(w0)))
    for key in ("ow_r0in_f1r1_b@ow", "ow_r0in_nat_f1r1_b@ow"):
        print("  %s: rank 1 fire during the mute? fire-to-unmute (ms), wait end - reconn (ms)" % key)
        for c in K[key]:
            t = next(x for x in trials if x["c"] is c)
            fire1 = float(t["l1"]["fire"][0][1]) - c["off"]
            print("    %-30s fire %.1f ms before unmute; wait_end %s wait_ms %s; reconn-unmute %.1f; rec_init_r1 %d; decl_r1 '%s'" % (
                c["stem"], c["unmute_ms"] - fire1, c["wait_end_r1"], c["wait_ms_r1"], c["reconn_after_unmute_ms_r1"] or float("nan"),
                c["rec_init_r1"], c["decl_r1"]))
    print("\n== rank 0 kill cell")
    for key in ("ow_kill0_b@ow", "ow_kill0_b@pcm"):
        print(" ", key)
        for c in K[key]:
            t = next(x for x in trials if x["c"] is c)
            off = c["off"]
            kill_r1 = c["kill_ms"] + off  # kill (rain clock) on rank 1's clock
            pref = float(t["l1"]["pref"][0][2]) if t["l1"]["pref"] else None
            launch0 = fl(t["k0"].get("t0_mono_ms"))
            print("    %-26s kill-r0_t0 %.0f; mute_off_r1-kill %.1f; probe_ref-mute_off %s; dead %s@%s-mute_off %s; "
                  "q4-kill %.1f; q4 class %s; decl-q4 %s; decl-probe_ref %s; probe_ref-before-q4 %s; wait %s/%s; decl '%s'; rec_init %d; r1rc %s"
                  % (c["stem"], c["kill_ms"] - launch0 if launch0 else float("nan"), c["mute_off_ms_r1"] - kill_r1,
                     "%.1f" % (pref - c["mute_off_ms_r1"]) if pref else "-", c["dead_cause_r1"],
                     "", "%.1f" % (c["dead_ms_r1"] - c["mute_off_ms_r1"]) if c["dead_ms_r1"] else "-",
                     c["q4_ms_r1"] - kill_r1, t["l1"]["q4"][0][1],
                     "%.1f" % c["decl_after_q4_ms_r1"] if c["decl_after_q4_ms_r1"] is not None else "-",
                     "%.1f" % (c["decl_ms_r1"] - pref) if pref else "-",
                     (pref < c["q4_ms_r1"]) if pref else "-", c["wait_end_r1"], c["wait_ms_r1"], c["decl_r1"],
                     c["rec_init_r1"], c["r1rc"]))
            if t["l1"]["pans"]:
                print("      probe answered lines:", len(t["l1"]["pans"]))
    print("\n== HELLO refusal cell")
    for key in ("ow_hello_f1_b@ow", "ow_hello_f1_b@pcm"):
        print(" ", key)
        for c in K[key]:
            t = next(x for x in trials if x["c"] is c)
            na = t["l0"]["notacc"]
            rf = t["l1"]["refuse"]
            rec0 = t["l0"]["reconn"]
            print("    %-26s refuse %s; notacc %s; reconn r0 %s r1 %d; r0 reconn-unmute %s; r1 reconn-unmute %s; dead r0 %s r1 %s; decl_r0 '%s'; transparent %d"
                  % (c["stem"], [("gen", x[1]) for x in rf], [(x[2], "att", x[3]) for x in na],
                     [("gen", x[2], "att", x[3]) for x in rec0], c["n_reconn_r1"],
                     "%.1f" % c["reconn_after_unmute_ms_r0"] if c["reconn_after_unmute_ms_r0"] is not None else "-",
                     "%.1f" % c["reconn_after_unmute_ms_r1"] if c["reconn_after_unmute_ms_r1"] is not None else "-",
                     [(x[0], round(x[1] - (c["td_t0_r1"] - c["off"]), 2)) for x in c["dead_all_r0"]],
                     [(x[0], round(x[1] - c["td_t0_r0"], 2)) for x in c["dead_all_r1"]] if c["td_t0_r0"] else c["dead_all_r1"],
                     c["decl_r0"], c["transparent_ok"]))
            if key.endswith("@pcm"):
                # time from the refused HELLO to rank 0's FIN death, rank 0 clock
                if rf and c["dead_ms_r0"] is not None:
                    print("      refuse->r0 FIN dead %.2f ms; r0 reconn->dead %.2f ms" % (
                        c["dead_ms_r0"] - (float(rf[0][2]) - c["off"]), c["dead_ms_r0"] - c["reconn_ms_r0"]))
    print("\n== natural race cells")
    for key in ("ow_r0in_nat_f1r1_b@pc", "ow_r0in_nat_f1r1_b@ow"):
        print(" ", key)
        for c in K[key]:
            print("    %-30s close1 r0 %s/%s r1 %s/%s; dead r0 %s r1 %s; decl_r0 '%s' decl_r1 '%s'; transparent %d; wait_r1 %s"
                  % (c["stem"], c["close1_cause_r0"], c["close1_lv_r0"], c["close1_cause_r1"], c["close1_lv_r1"],
                     [x[0] for x in c["dead_all_r0"]], [x[0] for x in c["dead_all_r1"]], c["decl_r0"], c["decl_r1"],
                     c["transparent_ok"], c["wait_end_r1"]))
    print("\n== one-way cells, details")
    for key in ("ow_r1in_f1_b@ow", "ow_r1in_f1_b@pcm", "ow_r0in_f1r1_b@ow", "ow_r0in_f1r1_b@pcm"):
        print(" ", key)
        for c in K[key]:
            print("    %-28s dead r0 %s r1 %s; reconn r0 %d r1 %d; decl_r0 '%s' decl_r1 '%s'; transparent %d; rec_init_r1 %d; alive %d; async_bf %d"
                  % (c["stem"], [x[0] for x in c["dead_all_r0"]], [x[0] for x in c["dead_all_r1"]], c["n_reconn_r0"],
                     c["n_reconn_r1"], c["decl_r0"], c["decl_r1"], c["transparent_ok"], c["rec_init_r1"],
                     c["r1_alive_at_decline"], c["async_before_fault"]))
    print("\n== replication cells")
    for key in ("f1_b@ow", "f3_b@ow", "bidirf_sym_b@ow", "rc_mute8_f1_b@ow", "f4_b@ow", "rc_mutekill_b@ow", "f2rel_b@ow"):
        cs = K[key]
        print("  %-20s transparent %d/%d; decl_r0 %s; decl_r1 %s; teardown_r0 %s; teardown_r1 %s; r1rc %s; r1_outcome %s; notrts %s; dead r0 %s r1 %s; teardown_ms_r1 %s"
              % (key, sum(c["transparent_ok"] for c in cs), len(cs), sorted(set(c["decl_r0"] for c in cs)),
                 sorted(set(c["decl_r1"] for c in cs)), sorted(set(str(c["teardown_r0"]) for c in cs)),
                 sorted(set(str(c["teardown_r1"]) for c in cs)), sorted(set(c["r1rc"] for c in cs)),
                 sorted(set(str(c["r1_outcome"]) for c in cs)),
                 sorted(set((c["n_notrts_r0"], c["n_notrts_r1"]) for c in cs), key=str),
                 sorted(set(tuple(x[0] for x in c["dead_all_r0"]) for c in cs)),
                 sorted(set(tuple(x[0] for x in c["dead_all_r1"]) for c in cs)), rng([c["teardown_ms_r1"] for c in cs])))
    for key in ("f4_b@ow", "rc_mutekill_b@ow"):
        print("  %s rank 0 dead line after the kill (ms):" % key,
              rng([c["dead_ms_r0"] - (c["kill_ms"] - c["off"]) for c in K[key] if c["dead_ms_r0"] is not None]),
              " decline after the kill:", rng([c["decl_ms_r0"] - (c["kill_ms"] - c["off"]) for c in K[key] if c["decl_ms_r0"]]))
    print("\n== latency (rank 0 kv lat_p50_us; raw recomputation from lat_raw.csv.gz)")
    meds = {}
    for key in ("lat_ow_on_4k@ow", "lat_pc_on_4k@pc", "lat_ow_on_256k@ow", "lat_pc_on_256k@pc"):
        vals, raws = [], []
        for c in K[key]:
            t = next(x for x in trials if x["c"] is c)
            vals.append(c["lat_p50_us"])
            if t["latraw"]:
                v = sorted(int(line.split(",")[1]) for line in gzip.open(t["latraw"], "rt") if "," in line)
                raws.append(v[int(0.5 * (len(v) - 1) + 0.5)] / 1e3)
        meds[key] = statistics.median(vals)
        print("  %-20s p50 per run %s median %.2f; raw p50 %s (match %s); transparent %d/%d" % (
            key, vals, meds[key], [round(x, 2) for x in raws],
            all(abs(round(a, 2) - b) < 0.006 for a, b in zip(raws, vals)), sum(c["transparent_ok"] for c in K[key]), len(K[key])))
    print("  4 KiB diff ow-pc %.2f us; 256 KiB diff ow-pc %.2f us" % (
        meds["lat_ow_on_4k@ow"] - meds["lat_pc_on_4k@pc"], meds["lat_ow_on_256k@ow"] - meds["lat_pc_on_256k@pc"]))

def extras(trials, K):
    print("\n== extra checks")
    # hold of each trial from the first log timestamp and the hold windows in hold_H*.out
    wins = {}
    for h in ("H1", "H2", "H3", "H4", "H5"):
        s = open(os.path.join(RES, "hold_%s.out" % h), errors="replace").read()
        a = re.search(r"(\d\d:\d\d:\d\d) \[gow-%s\] idle" % h, s).group(1)
        b = re.search(r"(\d\d:\d\d:\d\d) \[gow-%s\] command exited" % h, s).group(1)
        wins[h] = (a, b)
    per = {}
    for t in trials:
        stem = os.path.join(RES, t["stem"])
        first = None
        for line in open(stem + "_r0.log", errors="replace"):
            m = re.match(r"\[\d{4}-\d\d-\d\d (\d\d:\d\d:\d\d)\]", line)
            if m:
                first = m.group(1)
                break
        h = next((h for h, (a, b) in wins.items() if a <= first <= b), "none")
        per.setdefault(h, {}).setdefault(t["c"]["key"], 0)
        per[h][t["c"]["key"]] += 1
    for h in sorted(per):
        print("  %s %s %s" % (h, wins.get(h), per[h]))
    # kill PIDs: the kill record's pid is the PID in the killed rank's log
    bad = []
    nk = 0
    for t in trials:
        if not t["killraw"]:
            continue
        nk += 1
        pid = re.search(r"pid=(\d+)", t["killraw"]).group(1)
        r = 0 if t["c"]["r0_killed"] else 1
        host = "rain" if r == 0 else "sunny"
        logpid = re.search(r"\] %s:(\d+):" % host, open(os.path.join(RES, t["stem"] + "_r%d.log" % r), errors="replace").read())
        if not logpid or logpid.group(1) != pid:
            bad.append(t["stem"])
    print("  kill records %d; pid differs from the killed rank's log pid: %s" % (nk, bad or "none"))
    rtts = [fl(t["k0"].get("clock_rtt_ms")) for t in trials]
    print("  clock_rtt_ms over all %d trials: %s" % (len(trials), rng(rtts, "%.3f")))
    # rank 0 kill: kill after rank 0 devComm creation (rank 0 clock)
    for key in ("ow_kill0_b@ow", "ow_kill0_b@pcm"):
        xs = []
        for t in trials:
            if t["c"]["key"] == key:
                xs.append(t["c"]["kill_ms"] - fl(t["k0"].get("devcomm_mono_ms")))
        print("  %s kill after rank 0 devComm creation (ms): %s" % (key, rng(xs)))
    # one-way cells: signed time from the timing-out rank's ETIMEDOUT line to the other rank's ECONNRESET line
    for key in ("ow_r1in_f1_b@ow", "ow_r1in_f1_b@pcm", "ow_r0in_f1r1_b@ow", "ow_r0in_f1r1_b@pcm",
                "ow_r0in_nat_f1r1_b@pc", "ow_r0in_nat_f1r1_b@ow"):
        xs, firsts, aft = [], {}, []
        for c in K[key]:
            t0 = c["close1_ms_r0"]
            t1 = c["close1_ms_r1"] - c["off"]
            if c["close1_cause_r0"] == "ETIMEDOUT":
                xs.append(t1 - t0)
                firsts["r0 ETIMEDOUT"] = firsts.get("r0 ETIMEDOUT", 0) + 1
                aft.append(t0 - c["mute_on_ms_r0"])
            else:
                xs.append(t0 - t1)
                firsts["r1 ETIMEDOUT"] = firsts.get("r1 ETIMEDOUT", 0) + 1
                aft.append(t1 - (c["mute_on_ms_r1"] - c["off"]))
        print("  %-24s timed out: %s; reset line minus timeout line %s ms; timeout after mute start %s ms"
              % (key, firsts, rng(xs, "%.3f"), rng(aft)))
    # probe answered lines (rank 1) per cell
    for key in sorted(K):
        n = [c["n_probe_ans_r1"] for c in K[key]]
        if any(n):
            print("  %-24s rank 1 probe-answered lines per trial: %s" % (key, sorted(set(n))))
    # normal end: trials with a FIN dead line after the other rank's teardown start
    for key in sorted(K):
        n = sum(1 for c in K[key] if any(m >= 0 for r in (0, 1) for m in c["dead_margin_r%d" % r]))
        if n:
            print("  %-24s trials with a dead line after the other rank's teardown start: %d/%d" % (key, n, len(K[key])))
    allm = [m for k in K for c in K[k] for r in (0, 1) for m in c["dead_margin_r%d" % r] if m >= 0]
    print("  all dead lines after the other rank's teardown start: %s ms" % rng(allm, "%.2f"))


def detail_values(trials, K):
    """Further values from the raw logs, used to check the numbers stated in EXPERIMENT.md 15."""
    print("\n== further values (rank 0 clock unless noted; ranges over the scored trials of the cell@build)")
    T = {id(t["c"]): t for t in trials}
    def tr(c):
        return T[id(c)]
    def recs(t, r, role=None):
        out = []
        for line in open(os.path.join(RES, t["stem"] + "_r%d.log" % r), errors="replace"):
            if "GIN/TS: recovered " in line:
                d = dict(re.findall(r"([\w/]+)=(\[[^\]]*\]|\S+)", line))
                if role is None or d.get("role") == role:
                    out.append(d)
        return out
    def fire(t, r):
        f = t["l%d" % r]["fire"]
        return float(f[0][1]) if f else None
    # 1. ow_r1in_f1_b
    for key in ("ow_r1in_f1_b@ow", "ow_r1in_f1_b@pcm"):
        cs = K[key]
        att = sorted(set(tr(c)["l0"]["reconn"][0][3] for c in cs if tr(c)["l0"]["reconn"]))
        f2q = [c["q4_ms_r0"] - fire(tr(c), 0) for c in cs]
        d2q = [c["decl_ms_r0"] - c["q4_ms_r0"] for c in cs if c["decl_ms_r0"] is not None]
        ri = [recs(tr(c), 0, "initiator") for c in cs]
        tot = [float(x[0]["total_us"]) for x in ri if x]
        qps = sorted(set(x[0].get("qps") for x in ri if x))
        pans, pre = [], 0
        for c in cs:
            t = tr(c)
            if t["l1"]["pans"]:
                pans.append(float(t["l1"]["pans"][0][2]) - c["off"] - c["unmute_ms"])
                if float(t["l1"]["pans"][0][2]) > c["reconn_ms_r1"]:
                    pre += 1
        print("  %s: re-dial attempts %s; fire->first Q4 r0 %s; decl-q4 r0 %s; initiator qps %s total_us %s; "
              "probe answered in %d trials at %s after unmute (after the r1 reconnect line in %d)"
              % (key, att, rng(f2q, "%.2f"), rng(d2q, "%.2f"), qps, rng(tot, "%.0f"), len(pans), rng(pans), pre))
    # 2. ow_r0in_f1r1_b and the race cells
    for key in ("ow_r0in_f1r1_b@ow", "ow_r0in_f1r1_b@pcm", "ow_r0in_nat_f1r1_b@ow", "ow_r0in_nat_f1r1_b@pc"):
        cs = K[key]
        f2q = [c["q4_ms_r1"] - fire(tr(c), 1) for c in cs]
        d2q = [c["decl_ms_r1"] - c["q4_ms_r1"] for c in cs if c["decl_ms_r1"] is not None]
        ri = [recs(tr(c), 1, "initiator") for c in cs]
        commit = [float(x[0]["commit_us"]) for x in ri if x]
        tot = [float(x[0]["total_us"]) for x in ri if x]
        scope = sorted(set((x[0].get("qps"), x[0].get("scope")) for x in ri if x))
        d0 = [c["decl_ms_r0"] - c["q4_ms_r0"] for c in cs if c["decl_ms_r0"] is not None and c["q4_ms_r0"] is not None]
        q0cls = sorted(set(tr(c)["l0"]["q4"][0][1] for c in cs if tr(c)["l0"]["q4"]))
        d0fin = [(c["dead_ms_r0"] - c["reconn_ms_r0"]) for c in cs if c["dead_cause_r0"] == "FIN" and c["reconn_ms_r0"]]
        print("  %s: fire->first Q4 r1 %s; decl-q4 r1 %s; r1 initiator (qps, scope) %s commit_us %s total_us %s; "
              "r0 decl-q4 %s (r0 first Q4 class %s); r0 FIN dead after its reconnect line %s"
              % (key, rng(f2q, "%.2f"), rng(d2q, "%.2f"), scope, rng(commit, "%.0f"), rng(tot, "%.0f"),
                 rng(d0, "%.2f"), q0cls, rng(d0fin, "%.2f")))
    # signed reset delay per trial for the mirror cells (how many beyond 0.1 ms)
    for key in ("ow_r0in_f1r1_b@ow", "ow_r0in_f1r1_b@pcm", "ow_r1in_f1_b@ow", "ow_r1in_f1_b@pcm"):
        xs = [abs((c["close1_ms_r1"] - c["off"]) - c["close1_ms_r0"]) for c in K[key]]
        print("  %s: |reset line - timeout line| > 0.100 ms in %d of %d (max %.3f)" % (key, sum(1 for x in xs if x > 0.1), len(xs), max(xs)))
    # 4. ow_kill0_b
    for key in ("ow_kill0_b@ow", "ow_kill0_b@pcm"):
        cs = K[key]
        k_m = [c["kill_ms"] - c["mute_on_ms_r0"] for c in cs]
        before = sum(1 for c in cs if c["close1_ms_r0"] < c["kill_ms"] and c["close1_ms_r1"] - c["off"] < c["kill_ms"]
                     and c["close1_cause_r0"] == c["close1_cause_r1"] == "ETIMEDOUT" and c["close1_lv_r0"] == c["close1_lv_r1"] == "unknown")
        q_u = [c["q4_ms_r1"] - c["mute_off_ms_r1"] for c in cs]
        d2q = [c["decl_ms_r1"] - c["q4_ms_r1"] for c in cs]
        print("  %s: kill after r0 mute start %s; both closed ETIMEDOUT/unknown before the kill %d/%d; r1 Q4 after r1 unmute %s; decl-q4 %s"
              % (key, rng(k_m), before, len(cs), rng(q_u), rng(d2q, "%.2f")))
    # 5. ow_hello_f1_b
    for key in ("ow_hello_f1_b@ow", "ow_hello_f1_b@pcm"):
        cs = K[key]
        tmo = []
        for c in cs:
            tmo.append(c["close1_ms_r0"] - c["mute_on_ms_r0"])
            tmo.append(c["close1_ms_r1"] - c["mute_on_ms_r1"])
        ref = [float(tr(c)["l1"]["refuse"][0][2]) - c["off"] - c["unmute_ms"] for c in cs if tr(c)["l1"]["refuse"]]
        na = [float(tr(c)["l0"]["notacc"][0][4]) - c["unmute_ms"] for c in cs if tr(c)["l0"]["notacc"]]
        d2q = [c["decl_ms_r0"] - c["q4_ms_r0"] for c in cs if c["decl_ms_r0"] is not None]
        print("  %s: ETIMEDOUT after own mute start (both ranks) %s; refusal after unmute %s; not-accepted after unmute %s; decl-q4 r0 %s"
              % (key, rng(tmo), rng(ref), rng(na), rng(d2q, "%.2f")))
    # 6. replication
    for key in ("f4_b@ow", "rc_mutekill_b@ow"):
        cs = K[key]
        print("  %s: decl-q4 r0 %s" % (key, rng([c["decl_ms_r0"] - c["q4_ms_r0"] for c in cs], "%.2f")))
    cs = K["f3_b@ow"]
    print("  f3_b@ow qp states:", sorted(set((tr(c)["l0"]["qpst"][0][0], tr(c)["l1"]["qpst"][0][0]) for c in cs)))
    # post-hoc: trials with a dead line before the other rank's teardown start
    for key in sorted(K):
        n = sum(1 for c in K[key] if c["n_dead_live_r0"] + c["n_dead_live_r1"] > 0)
        print("  %-24s trials with a dead line before the other rank's teardown start: %d/%d" % (key, n, len(K[key])))


def smoke_check():
    global RES
    S = os.path.join(os.path.dirname(RES), os.path.basename(RES) + "_smoke")
    if not os.path.isdir(S):
        return
    print("\n== smoke (not scored): race cell on pc, who timed out first")
    for meta in sorted(glob.glob(os.path.join(S, "*", "ow_r0in_nat_f1r1_b_*_meta.txt"))):
        stem = meta[:-len("_meta.txt")]
        l0, l1 = parse_log(stem + "_r0.log"), parse_log(stem + "_r1.log")
        print("  %s r0 %s r1 %s" % (os.path.relpath(stem, S), [x[2:5:2] for x in l0["close"]], [x[2:5:2] for x in l1["close"]]))
    keep = RES
    RES = S
    sm = []
    for sub in ("ow", "pcm", "pc", "lat"):
        sm += load(sub)
    RES = keep
    fins, uncut, kq = [], [], []
    for t in sm:
        c = columns(t)
        c["stem"] = t["stem"]
        for r in (0, 1):
            fins += [(c["stem"], r, x[0], round(m, 2)) for x, m in zip(c["dead_all_r%d" % r], c["dead_margin_r%d" % r])
                     if x[0] == "FIN"]
        if c["cell"] in ("ow_r1in_f1_b", "ow_r0in_f1r1_b") and c["build"] == "pcm":
            uncut.append((c["stem"], c["close1_cause_r0"] if c["cell"] == "ow_r1in_f1_b" else c["close1_cause_r1"]))
        if c["cell"] == "ow_kill0_b":
            kq.append((c["stem"], round(c["q4_ms_r1"] - c["mute_off_ms_r1"], 1),
                       round(c["decl_after_q4_ms_r1"], 1) if c["decl_after_q4_ms_r1"] is not None else None))
    print("  smoke trials %d; FIN dead lines (stem, rank, cause, ms after the other rank's teardown start; nan: no teardown line): %s"
          % (len(sm), fins))
    print("  smoke pcm one-way: first close cause of the unmuted rank:", uncut)
    print("  smoke kill0: rank 1 Q4 after its unmute, decline after Q4 (ms):", kq)
    for when in ("before", "after"):
        p = os.path.join(S, "snap_%s-H0.txt" % when)
        if os.path.exists(p):
            print("  H0 %s:" % when, " | ".join(x for x in open(p).read().splitlines() if ":" in x and "==" not in x))
    p = os.path.join(S, "mlx5_new_H0.txt")
    print("  mlx5_new_H0 lines:", len(open(p).read().splitlines()) if os.path.exists(p) else "missing")


def safety():
    print("\n== safety per hold (snapshots, recomputed from the mlx5 and fwcmd files)")
    for h in ("H1", "H2", "H3", "H4", "H5"):
        out = {}
        for when in ("before", "after"):
            for node in ("rain", "sunny"):
                p = os.path.join(RES, "mlx5_%s-%s_%s.txt" % (when, h, node))
                lines = open(p, errors="replace").read().splitlines() if os.path.exists(p) else None
                out[(when, node)] = lines
            p = os.path.join(RES, "fwcmd_%s-%s.txt" % (when, h))
            s = 0
            if os.path.exists(p):
                for tok in open(p).read().split():
                    m = re.match(r"(failed|failed_mbox_status)=(\d+)$", tok)
                    if m:
                        s += int(m.group(2))
            out[(when, "fw")] = s
        def cmderr(ls):
            return sum(1 for x in ls if "mlx5" in x.lower() and re.search(r"cmd|command", x, re.I)
                       and re.search(r"failed|timeout|leak", x, re.I))
        new = {node: sorted(set(out[("after", node)]) - set(out[("before", node)])) for node in ("rain", "sunny")}
        hold = open(os.path.join(RES, "hold_%s.out" % h), errors="replace").read()
        gpu = re.findall(r"^(?:rain|sunny) gpu: .*$", hold, re.M)
        lock = re.findall(r"\[gow-%s\] (lock acquired.*|idle.*?;|command exited.*)" % h, hold)
        kills = re.findall(r"SIGKILL (rank\d)", hold)
        print("  %s mlx5 lines rain %d->%d sunny %d->%d; cmd-err rain %d->%d sunny %d->%d; fw failed %d->%d; new lines rain %d sunny %d; "
              "other GPU users %d; lock/idle %s; SIGKILL lines %s; mlx5_new file lines %d"
              % (h, len(out[("before", "rain")]), len(out[("after", "rain")]), len(out[("before", "sunny")]),
                 len(out[("after", "sunny")]), cmderr(out[("before", "rain")]), cmderr(out[("after", "rain")]),
                 cmderr(out[("before", "sunny")]), cmderr(out[("after", "sunny")]), out[("before", "fw")],
                 out[("after", "fw")], len(new["rain"]), len(new["sunny"]), len(gpu), [x[:40] for x in lock],
                 {k: kills.count(k) for k in set(kills)},
                 len(open(os.path.join(RES, "mlx5_new_%s.txt" % h)).read().splitlines())))
    print("  STOP_mlx5 present:", os.path.exists(os.path.join(RES, "STOP_mlx5")))

if __name__ == "__main__":
    trials, K = main()
    report(trials, K)
    extras(trials, K)
    detail_values(trials, K)
    safety()
    smoke_check()
