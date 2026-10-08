#!/usr/bin/env python3
"""gin-reconnect: independent recount from the raw per-trial files (QA, EXPERIMENT.md section 10).

usage: python3 qa/recount.py [results/20261008] [--rows <csv>]

Written without reading or running score.py, without the outputs of rows_rc.py and without SCORE.md,
trials_scored.csv or trials_*.csv. Every column of EXPERIMENT.md 3.1 is parsed here again from
  <stem>_meta.txt, <stem>_r{0,1}.kv, <stem>_r{0,1}.log, <stem>_kill.out
(log formats taken from EXPERIMENT.md 3.1, ../s2_close/EXPERIMENT.md 3.1 and the driver sources), and every
acceptance rule of predictions.csv is hand-coded below with the 3.2 grammar (blank -> None, a comparison or
arithmetic with None is false). It also checks the pre-registration (hash, frozen sections against the tag),
the trial set (section 7), exclusions and refills (section 8), the build of every trial, the configuration
checks of section 8 and the safety records of every hold. Reads only; writes nothing unless --rows is given.
"""
import csv, glob, gzip, hashlib, os, re, statistics, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)

# ---------------------------------------------------------------- section 7: cells, builds, planned repetitions
PLAN = {  # cell -> (build, planned n, kind)
    "rc_mute8_f1_b": ("rc", 10, "N"), "rc_mutef3s_b": ("rc", 10, "N"), "rc_mutef3l_b": ("rc", 10, "N"),
    "rc_mutekill_b": ("rc", 10, "N"),
    "f1_b": ("rc", 5, "R"), "f3_b": ("rc", 5, "R"), "f1g0_b": ("rc", 5, "R"), "mt256_f1_b": ("rc", 5, "R"),
    "bidirf_f1both_b": ("rc", 5, "R"), "bidirf_sym_b": ("rc", 5, "R"), "f4_b": ("rc", 5, "R"),
    "f2rel_b": ("rc", 5, "R"),
    "rc_mute1_f1_b": ("rc", 5, "C"), "rc_mute8off_b": ("rc", 5, "C"),
    "lat_s2r_on_4k": ("s2r", 5, "R"), "lat_s2r_on_256k": ("s2r", 5, "R"),
    "lat_rc_on_4k": ("rc", 5, "C"), "lat_rc_on_256k": ("rc", 5, "C"),
}
# section 7 conditions that the meta file records (extra env, hook delay, iterations, bytes) for the new and control cells
COND = {
    "rc_mute8_f1_b": dict(fault="F1", inject="12000", iters="1000", bytes="16384",
                          env={"NCCL_GIN_TS_TEST_SOCK_MUTE": "500:8000", "GIN_TS_RX_WAIT_S": "10"}),
    "rc_mutef3s_b": dict(fault="F3", inject="6000", iters="1000", bytes="16384",
                         env={"NCCL_GIN_TS_TEST_SOCK_MUTE": "300:12000", "GIN_TS_RX_WAIT_S": "30"}),
    "rc_mutef3l_b": dict(fault="F3", inject="6000", iters="1000", bytes="16384",
                         env={"NCCL_GIN_TS_TEST_SOCK_MUTE": "300:30000", "GIN_TS_RX_WAIT_S": "30"}),
    "rc_mutekill_b": dict(fault="F4", iters="1000", bytes="16384",
                          env={"NCCL_GIN_TS_TEST_SOCK_MUTE": "300:8000", "GIN_TS_RX_WAIT_S": "10"}),
    "rc_mute1_f1_b": dict(fault="F1", inject="3000", iters="300", bytes="16384",
                          env={"NCCL_GIN_TS_TEST_SOCK_MUTE": "500:1000"}),
    "rc_mute8off_b": dict(fault="F1", inject="12000", iters="1000", bytes="16384",
                          env={"NCCL_GIN_TS_TEST_SOCK_MUTE": "500:8000", "GIN_TS_RX_WAIT_S": "10",
                               "NCCL_GIN_TS_RECONNECT": "0"}),
    "f2rel_b": dict(fault="F2", iters="120",
                    env={"GIN_TS_RX_WAIT_S": "20", "GIN_TS_POST_ABORT_WAIT_S": "3", "NCCL_GIN_TS_USER_ABORT": "1"}),
}
ORDER_CELLS = ("rc_mutef3s_b", "rc_mutef3l_b", "rc_mutekill_b")  # section 8 order exclusion
HOLD_OF = {"lat": "H1", "rep_rc": "H1", "rc_mute8_f1_b": "H2", "rc_mute1_f1_b": "H2", "rc_mute8off_b": "H2",
           "rc_mutef3s_b": "H3", "rc_mutekill_b": "H3", "rc_mutef3l_b": "H4"}
FILL = {("f3_b", 6), ("rc_mutef3l_b", 11)}  # trials run in the fill hold (chain.out)
# source lines of WARN calls: rc after the mute-schedule fix (8354411f, also smoke 2), the smoke-1 build (1193a5f8),
# and the s2r reference (ba4984bd); read from the smoke-1, smoke-2 and main logs and the build tree
LINE_RC = {"gdakiTsStart_reconnect": 3930, "gdakiTsStart_on": 3929}
LINE_SMOKE1 = {"gdakiTsStart_reconnect": 3925, "gdakiTsStart_on": 3924}
LINE_S2R = {"gdakiTsStart_on": 3647}


# ---------------------------------------------------------------- parsing
def kv(path):
    """key=value file; a value runs to the next ' key=' (values such as 'no error' contain spaces)."""
    d = {}
    if not os.path.exists(path):
        return d
    for line in open(path, errors="replace"):
        line = line.rstrip("\n")
        keys = list(re.finditer(r"(?:^| )([A-Za-z_][A-Za-z0-9_]*)=", line))
        for i, m in enumerate(keys):
            end = keys[i + 1].start() if i + 1 < len(keys) else len(line)
            d[m.group(1)] = line[m.end():end].strip()
    return d


def num(x):
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


R = {
    "ts_on": re.compile(r"GIN/TS: transparent recovery ON rank="),
    "ua": re.compile(r"GIN/TS: user devComm abort flag set rank="),
    "rcmode": re.compile(r"GIN/TS: helper socket reconnect=(\d+) bound_ms=(\d+) rank=(\d+)"),
    "mute_on": re.compile(r"GIN/TS: TEST socket mute on rank=(\d+) peers=(\d+) mono_ms=([\d.]+)"),
    "mute_off": re.compile(r"GIN/TS: TEST socket mute off rank=(\d+) peers=(\d+) mono_ms=([\d.]+)"),
    "close": re.compile(r"GIN/TS: rank (\d+): socket to rank (\d+) closed cause=(\S+) mono_ms=([\d.]+)(?: liveness=(\S+))?"),
    "recon": re.compile(r"GIN/TS: rank (\d+): socket to rank (\d+) reconnected gen=(\d+) attempts=(\d+) mono_ms=([\d.]+)"),
    "wait": re.compile(r"GIN/TS: rank (\d+): reconnect wait for rank (\d+) ended=(\S+) wait_ms=([\d.]+) mono_ms=([\d.]+)"),
    "decl": re.compile(r'GIN/TS: declined rank=(\d+) peer=(\d+) reason="([^"]*)" class=(\S+) mono_ms=([\d.]+)'),
    "fire": re.compile(r"GIN/FAULT: GDAKI fault fired .*fire_mono_ms=([\d.]+)"),
    "rec": re.compile(r"GIN/TS: recovered rank=(\d+) peer=(\d+) role=(\S+)"),
    "src": re.compile(r"gin_host_gdaki\.cc:(\d+) \((\w+)\) NCCL WARN (GIN/TS: (?:helper socket reconnect|transparent recovery ON))"),
    "stamp": re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\]"),
}


def scan(path):
    o = {"ts_on": 0, "ua": 0, "rcmode": [], "mute_on": [], "mute_off": [], "close": [], "recon": [], "wait": [],
         "decl": [], "fires": [], "trigger_miss": 0, "q4": [], "rec": [], "src": [], "bind": 0, "stamps": [],
         "q4_mono_count_bad": 0}
    if not os.path.exists(path):
        return o
    for line in open(path, errors="replace"):
        m = R["stamp"].match(line)
        if m:
            o["stamps"].append(m.group(1))
        if "bind: Address already in use" in line:
            o["bind"] += 1
        if "trigger not reached" in line:
            o["trigger_miss"] += 1
        if R["ts_on"].search(line):
            o["ts_on"] += 1
        if R["ua"].search(line):
            o["ua"] += 1
        for key in ("rcmode", "mute_on", "mute_off", "close", "recon", "wait", "decl", "rec"):
            m = R[key].search(line)
            if m:
                o[key].append(m.groups())
        m = R["fire"].search(line)
        if m:
            o["fires"].append(float(m.group(1)))
        if "device-classified error CQE" in line:
            ms = re.findall(r"(?<![\w])mono_ms=([\d.]+)", line)
            if len(ms) != 1:
                o["q4_mono_count_bad"] += 1
            cls = re.search(r" class=(\S+)", line)
            o["q4"].append((float(ms[-1]) if ms else None, cls.group(1) if cls else ""))
        m = R["src"].search(line)
        if m:
            o["src"].append((int(m.group(1)), m.group(3)))
    return o


def transparent(k0, k1, iters, bidir):
    def ok(k, sender, receiver):
        if k.get("outcome") != "ok" or k.get("async_first") != "none":
            return False
        if sender and not (k.get("tx_done") == str(iters) and k.get("tx_rc") == "no error"):
            return False
        if receiver and not (k.get("rx_done") == str(iters) and k.get("rx_rc") == "no error"
                             and k.get("dev_bad_slots") == "0" and k.get("host_bad_slots") == "0"
                             and k.get("signal_exact") == "1"):
            return False
        return True
    return 1 if (ok(k0, True, bidir) and ok(k1, bidir, True)) else 0


def trial(meta_path, sub):
    stem = meta_path[: -len("_meta.txt")]
    m = kv(meta_path)
    k0, k1 = kv(stem + "_r0.kv"), kv(stem + "_r1.kv")
    l0, l1 = scan(stem + "_r0.log"), scan(stem + "_r1.log")
    kill = kv(stem + "_kill.out")
    off = num(k0.get("clock_offset_ms"))  # rank 1 clock - rank 0 clock
    iters = int(m.get("iters", "0"))
    t = {"sub": sub, "stem": os.path.basename(stem), "cell": m.get("cell"), "build": m.get("build"),
         "trial": m.get("trial"), "n": int(m.get("trial", "n0")[1:]), "fault": m.get("fault"),
         "bundle": m.get("bundle"), "extra": m.get("extra", ""), "inject": m.get("inject"), "iters": iters,
         "bytes": m.get("bytes"), "r0rc": num(m.get("r0rc")), "r1rc": num(m.get("r1rc")), "left": num(m.get("left")),
         "wall_s": num(m.get("wall_s")), "r0_outcome": k0.get("outcome"), "r1_outcome": k1.get("outcome"),
         "r0_async": k0.get("async_first"), "r1_async": k1.get("async_first"),
         "teardown_r0": k0.get("abort_ret"), "teardown_r1": k1.get("abort_ret"),
         "teardown_ms_r0": num(k0.get("teardown_ms")), "teardown_ms_r1": num(k1.get("teardown_ms")),
         "lat_p50_us": num(k0.get("lat_p50_us")), "off": off}
    t["transparent_ok"] = transparent(k0, k1, iters, m.get("app") == "bidir")
    t["bind_fail"] = 1 if (l0["bind"] or l1["bind"]) else 0
    t["n_fires_r0"], t["n_fires_r1"] = len(l0["fires"]), len(l1["fires"])
    t["trigger_miss"] = l0["trigger_miss"] + l1["trigger_miss"]
    t["ts_on_r0"], t["ts_on_r1"], t["ua_r0"], t["ua_r1"] = l0["ts_on"], l1["ts_on"], l0["ua"], l1["ua"]
    t["rc_mode_r0"] = l0["rcmode"][0][0] if l0["rcmode"] else None
    t["rc_mode_r1"] = l1["rcmode"][0][0] if l1["rcmode"] else None
    t["bound_ms_r0"] = num(l0["rcmode"][0][1]) if l0["rcmode"] else None
    t["n_mute_on_r0"] = len(l0["mute_on"])
    t["mute_on_ms_r0"] = num(l0["mute_on"][0][2]) if l0["mute_on"] else None
    t["mute_off_ms_r0"] = num(l0["mute_off"][0][2]) if l0["mute_off"] else None
    t["n_mute_off_r0"] = len(l0["mute_off"])
    t["n_sock_close_r0"] = len(l0["close"])
    t["sock_close_ms_r0"] = num(l0["close"][0][3]) if l0["close"] else None
    t["sock_close_cause_r0"] = l0["close"][0][2] if l0["close"] else None
    t["sock_close_liveness_r0"] = l0["close"][0][4] if l0["close"] else None
    t["closes_r0"] = [(c[2], num(c[3]), c[4]) for c in l0["close"]]
    t["closes_r1"] = [(c[2], num(c[3]) - off if off is not None else None, c[4]) for c in l1["close"]]
    t["n_reconnect_r0"], t["n_reconnect_r1"] = len(l0["recon"]), len(l1["recon"])
    t["reconnect_ms_r0"] = num(l0["recon"][0][4]) if l0["recon"] else None
    t["recon_attempts_r0"] = l0["recon"][0][3] if l0["recon"] else None
    t["recon_r1_attempts"] = [r[3] for r in l1["recon"]]
    t["n_wait_r0"] = len(l0["wait"])
    t["rc_wait_end_r0"] = l0["wait"][0][2] if l0["wait"] else None
    t["rc_wait_ms_r0"] = num(l0["wait"][0][3]) if l0["wait"] else None
    t["rc_wait_mono_r0"] = num(l0["wait"][0][4]) if l0["wait"] else None
    t["q4_mono_r0"] = l0["q4"][0][0] if l0["q4"] else None
    t["q4_class_r0"] = l0["q4"][0][1] if l0["q4"] else None
    t["q4_bad"] = l0["q4_mono_count_bad"]
    t["decl_r0"] = ";".join(d[2] for d in l0["decl"]) if l0["decl"] else None
    t["decl_r1"] = ";".join(d[2] for d in l1["decl"]) if l1["decl"] else None
    t["n_decl_r0"] = len(l0["decl"])
    t["decl_mono_r0"] = num(l0["decl"][0][4]) if l0["decl"] else None
    t["rec_r0"] = [r[2] for r in l0["rec"]]
    t["rec_r1"] = [r[2] for r in l1["rec"]]
    t["killed"] = 1 if kill.get("kill_mono_ms") else 0
    t["kill_mono_r0"] = (num(kill.get("kill_mono_ms")) - off) if (kill.get("kill_mono_ms") and off is not None) else None
    t["kill_after_devcomm_r1"] = (num(kill.get("kill_mono_ms")) - num(k1.get("devcomm_mono_ms"))) \
        if (kill.get("kill_mono_ms") and k1.get("devcomm_mono_ms")) else None
    t["devcomm_r0"] = num(k0.get("devcomm_mono_ms"))
    # fault instant on rank 0's clock: first hook fire of either rank, else the kill (rows.py definition)
    cands = l0["fires"][:1] + ([l1["fires"][0] - off] if (l1["fires"] and off is not None) else [])
    fault = min(cands) if cands else None
    if fault is None and t["kill_mono_r0"] is not None:
        fault = t["kill_mono_r0"]
    t["fault_mono_r0"] = fault
    asyncs = []
    for k, is_r1 in ((k0, False), (k1, True)):
        if k.get("async_first") not in (None, "", "none"):
            la, ms = num(k.get("launch_mono_ms")), num(k.get("async_first_ms_after_launch"))
            if la is not None and ms is not None and (not is_r1 or off is not None):
                asyncs.append(la + ms - (off if is_r1 else 0.0))
    t["async_before_fault"] = 1 if (fault is not None and any(a < fault for a in asyncs)) else 0
    la1, km1 = num(k1.get("launch_mono_ms")), num(k1.get("kernel_ms"))
    t["r1_end_r0clock"] = (la1 + km1 - off) if (la1 is not None and km1 is not None and off is not None) else None
    alive = 0
    if t["decl_mono_r0"] is not None and t["r1_end_r0clock"] is not None:
        if t["r1_end_r0clock"] > t["decl_mono_r0"] and t["r1rc"] not in (137.0, 139.0, 255.0):
            alive = 1
    t["r1_alive_at_decline"] = alive
    t["src_r0"], t["src_r1"] = l0["src"], l1["src"]
    t["stamps"] = sorted(l0["stamps"] + l1["stamps"])
    return t


# ---------------------------------------------------------------- helpers for the rules (3.2 grammar)
def lt(a, b):
    return a is not None and b is not None and a < b


def le(a, b):
    return a is not None and b is not None and a <= b


def has(v, s):
    return v is not None and s in v


def sub_(a, b):
    return None if (a is None or b is None) else a - b


def rng(vals, fmt="%.1f"):
    v = [x for x in vals if x is not None]
    if not v:
        return "none"
    return (fmt % min(v)) + " to " + (fmt % max(v)) + " (n=%d)" % len(v)


# ---------------------------------------------------------------- verbatim 3.2 evaluator (second check)
class _Nil:
    """a blank value: every comparison is false and arithmetic stays blank (3.2 grammar)."""
    def _f(self, *a):
        return False

    def _n(self, *a):
        return self
    __lt__ = __le__ = __gt__ = __ge__ = __eq__ = __ne__ = _f
    __add__ = __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = __truediv__ = __rtruediv__ = __neg__ = _n

    def __bool__(self):
        return False
    __hash__ = object.__hash__


NIL = _Nil()


class _Col(str):
    pass


def _val(x):
    if x is None or x == "":
        return NIL
    if isinstance(x, bool):
        return float(x)
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(x)
    except (TypeError, ValueError):
        return x


def _calls(src, name):
    """replace name(<balanced>) by name(<python string literal of the argument>)."""
    out, i = "", 0
    while True:
        k = src.find(name + "(", i)
        if k < 0:
            return out + src[i:]
        depth, j = 0, k + len(name)
        while True:
            if src[j] == "(":
                depth += 1
            elif src[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        out += src[i:k] + name + "(" + repr(src[k + len(name) + 1:j]) + ")"
        i = j + 1


def evaluate(acc, cells, byk):
    """acc: the acceptance text; cells: the cell keys of the row; byk: cell key -> judged trial dicts."""
    per = acc.startswith("per cell:")
    expr = _calls(acc.split(":", 1)[1].strip() if per else acc, "count")
    for c in cells:
        if len(byk.get(c, [])) < PLAN[c.split("@")[0]][1]:
            return "insufficient"

    def run(cell):
        def count(src):
            n = 0
            for t in byk[cell]:
                env = {k: _val(v) for k, v in t.items() if isinstance(v, (str, int, float, type(None)))}
                env.update(has=lambda f, s: isinstance(f, str) and s in f, nonempty=lambda f: f is not NIL, abs=abs)
                if eval(src, {"__builtins__": {}}, env):
                    n += 1
            return float(n)

        def median(col, key):
            return statistics.median([_val(t[col]) for t in byk[key]])
        cols = {k: _Col(k) for t in byk[cell] for k in t}
        env = dict(cols, count=count, median=median, abs=abs)
        return bool(eval(expr, {"__builtins__": {}}, env))
    ok = all(run(c) for c in cells) if per else run(cells[0])
    return "holds" if ok else "fails"


# ---------------------------------------------------------------- main
def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    rows_out = sys.argv[sys.argv.index("--rows") + 1] if "--rows" in sys.argv else None
    if rows_out in args:
        args.remove(rows_out)
    res = os.path.abspath(args[0] if args else os.path.join(STUDY, "results", "20261008"))
    out = []
    P = out.append

    # ---- 0. pre-registration
    P("== 0. pre-registration")
    sha = hashlib.sha256(open(os.path.join(STUDY, "predictions.csv"), "rb").read()).hexdigest()
    pre = open(os.path.join(STUDY, "PREREG.txt")).read()
    P("predictions.csv sha256 %s; in PREREG.txt: %s" % (sha[:12], sha in pre))
    rel = os.path.relpath(STUDY, subprocess.check_output(["git", "-C", STUDY, "rev-parse", "--show-toplevel"],
                                                         text=True).strip())
    tagc = subprocess.check_output(["git", "-C", STUDY, "rev-parse", "prereg/gin-reconnect-v1^{commit}"], text=True).strip()
    P("tag prereg/gin-reconnect-v1 -> commit %s" % tagc[:8])
    for f in ("predictions.csv", "PREREG.txt"):
        old = subprocess.check_output(["git", "-C", STUDY, "show", "%s:%s/%s" % (tagc, rel, f)])
        P("%s identical to the tag: %s" % (f, old == open(os.path.join(STUDY, f), "rb").read()))

    def sections(txt):
        parts = re.split(r"(?m)^(## \d+\..*)$", txt)
        return {re.match(r"## (\d+)\.", parts[i]).group(1): parts[i] + parts[i + 1] for i in range(1, len(parts), 2)}
    old = sections(subprocess.check_output(["git", "-C", STUDY, "show", "%s:%s/EXPERIMENT.md" % (tagc, rel)], text=True))
    new = sections(open(os.path.join(STUDY, "EXPERIMENT.md"), encoding="utf-8").read())
    for s in ("2", "3", "7", "8"):
        P("EXPERIMENT.md section %s identical to the tag: %s" % (s, old.get(s) == new.get(s)))
    preds = list(csv.DictReader(open(os.path.join(STUDY, "predictions.csv"))))
    P("prediction rows: %d" % len(preds))

    # ---- 1. trial set
    trials = []
    for sub in ("mute", "rep_rc", "lat"):
        for meta in sorted(glob.glob(os.path.join(res, sub, "*_meta.txt"))):
            trials.append(trial(meta, sub))
    P("\n== 1. trial set (%s)" % os.path.relpath(res, STUDY))
    P("trial meta files: %d (mute %d, rep_rc %d, lat %d)" % (len(trials), *[sum(1 for t in trials if t["sub"] == s)
                                                                          for s in ("mute", "rep_rc", "lat")]))
    unknown = sorted({t["cell"] for t in trials} - set(PLAN))
    P("cells not in section 7: %s" % (unknown or "none"))

    def excl_reason(t):
        if t["bind_fail"]:
            return "bind_fail (rendezvous port in use)"
        f = t["fault"]
        if f in ("F1", "F1both") and t["n_fires_r0"] == 0:
            return "fault not applied (n_fires_r0 == 0)"
        if f == "F3" and t["n_fires_r1"] == 0:
            return "fault not applied (n_fires_r1 == 0)"
        if t["trigger_miss"] > 0:
            return "trigger_miss > 0"
        if f == "F4" and t["killed"] != 1:
            return "kill not applied"
        if t["cell"] in ORDER_CELLS and (t["n_sock_close_r0"] == 0 or lt(t["q4_mono_r0"], t["sock_close_ms_r0"])):
            return "order not applied"
        return None
    for t in trials:
        t["excl"] = excl_reason(t)
    judged = {}
    P("%-18s %-5s %4s %5s %5s %6s  %s" % ("cell", "build", "plan", "files", "judged", "refill", "excluded / refills"))
    for c, (b, n, kind) in PLAN.items():
        ts = sorted([t for t in trials if t["cell"] == c], key=lambda t: t["n"])
        builds = {t["build"] for t in ts}
        j = [t for t in ts if not t["excl"]]
        judged[c] = j
        refill = [t for t in ts if t["n"] > n]
        nums = [t["n"] for t in ts]
        note = "; ".join("%s: %s" % (t["trial"], t["excl"]) for t in ts if t["excl"])
        if refill:
            note += ("; " if note else "") + "refill " + ",".join(t["trial"] for t in refill)
        if nums != list(range(1, len(nums) + 1)):
            note += " NUMBERING GAP %s" % nums
        if builds != {b}:
            note += " BUILD %s" % builds
        over = len(refill) > 0.5 * n
        P("%-18s %-5s %4d %5d %5d %6d  %s%s" % (c, b, n, len(ts), len(j), len(refill), note or "-",
                                                  " REFILL>50%" if over else ""))
    tot_files = len(trials)
    tot_j = sum(len(v) for v in judged.values())
    P("total: %d trial files, %d judged, %d excluded" % (tot_files, tot_j, tot_files - tot_j))
    for t in trials:
        if t["excl"]:
            P("excluded %s: r0rc=%s r1rc=%s wall_s=%s; refilled by %s n%d" % (
                t["stem"], t["r0rc"], t["r1rc"], t["wall_s"], t["cell"], PLAN[t["cell"]][1] + 1))

    # ---- 1b. cell conditions recorded in meta (section 7)
    P("\n== 1b. cell conditions in meta (section 7)")
    for c, cond in COND.items():
        bad = []
        for t in [t for t in trials if t["cell"] == c]:
            env = dict(x.split("=", 1) for x in t["extra"].split("+") if "=" in x)
            for k2, v in cond["env"].items():
                if env.get(k2) != v:
                    bad.append("%s %s=%s" % (t["trial"], k2, env.get(k2)))
            if c not in ("rc_mute8off_b",) and "NCCL_GIN_TS_RECONNECT" in env:
                bad.append("%s has NCCL_GIN_TS_RECONNECT" % t["trial"])
            for k2 in ("fault", "inject", "bytes"):
                if k2 in cond and t[k2] != cond[k2]:
                    bad.append("%s %s=%s" % (t["trial"], k2, t[k2]))
            if str(t["iters"]) != cond["iters"]:
                bad.append("%s iters=%s" % (t["trial"], t["iters"]))
        P("%-15s %s" % (c, "all match" if not bad else "MISMATCH " + ", ".join(bad)))
    kd = {}
    for h in ("H1", "H3"):
        for line in open(os.path.join(res, "hold_%s.out" % h), errors="replace"):
            m = re.search(r"F4/blocking#(n\d+)\] SIGKILL rank1 after (\d+) ms", line)
            if m:
                kd.setdefault(h, []).append(int(m.group(2)))
    P("kill delays from hold output: H1 (f4_b) %s; H3 (rc_mutekill_b) %s" % (kd.get("H1"), kd.get("H3")))
    mk = [t for t in judged["rc_mutekill_b"]]
    P("rc_mutekill_b kill after rank-1 devComm creation (rank 1 clock, ms): %s" %
      rng([t["kill_after_devcomm_r1"] for t in mk]))

    # ---- 1c. build per trial
    P("\n== 1c. build per trial")
    for b in ("rc", "s2r"):
        ts = [t for t in trials if t["build"] == b]
        paths = sorted({t["bundle"] for t in ts})
        P("build %s: %d trials, bundle paths %s" % (b, len(ts), paths))
    bad = []
    for t in trials:
        if t["bind_fail"]:
            continue
        for r in ("src_r0", "src_r1"):
            s = {(ln, txt) for ln, txt in t[r]}
            if t["build"] == "rc":
                want = {(LINE_RC["gdakiTsStart_on"], "GIN/TS: transparent recovery ON"),
                        (LINE_RC["gdakiTsStart_reconnect"], "GIN/TS: helper socket reconnect")}
                if s != want:
                    bad.append("%s %s %s" % (t["stem"], r, sorted(s)))
            else:
                if s != {(LINE_S2R["gdakiTsStart_on"], "GIN/TS: transparent recovery ON")}:
                    bad.append("%s %s %s" % (t["stem"], r, sorted(s)))
    P("rc trials whose start lines sit at gin_host_gdaki.cc:%d/%d (fixed build; smoke-1 build 1193a5f8 logs them at "
      "%d/%d), s2r trials at :%d with no reconnect line; exceptions: %s" % (
          LINE_RC["gdakiTsStart_on"], LINE_RC["gdakiTsStart_reconnect"], LINE_SMOKE1["gdakiTsStart_on"],
          LINE_SMOKE1["gdakiTsStart_reconnect"], LINE_S2R["gdakiTsStart_on"], bad or "none"))
    st = [s for t in trials for s in t["stamps"]]
    P("log time stamps of the main run: %s to %s" % (min(st), max(st)))
    # smoke for contrast (not scored)
    for sm in ("smoke", "smoke2"):
        lines = set()
        for f in glob.glob(os.path.join(res + "_smoke", sm, "*_r[01].log")):
            meta = kv(re.sub(r"_r[01]\.log$", "_meta.txt", f))
            if meta.get("build") != "rc":
                continue
            for ln, txt in scan(f)["src"]:
                lines.add((ln, txt[7:]))
        P("smoke %s rc start-line numbers (contrast only): %s" % (sm, sorted(lines)))

    # ---- 1d. configuration checks (section 8)
    P("\n== 1d. configuration checks (section 8), judged trials")
    cfg = []
    for c, j in judged.items():
        for t in j:
            if not (t["ts_on_r0"] >= 1 and t["ts_on_r1"] >= 1 and t["ua_r0"] >= 1 and t["ua_r1"] >= 1):
                cfg.append("%s ts_on/ua %s/%s/%s/%s" % (t["stem"], t["ts_on_r0"], t["ts_on_r1"], t["ua_r0"], t["ua_r1"]))
            if t["build"] == "rc":
                want = "0" if c == "rc_mute8off_b" else "1"
                if t["rc_mode_r0"] != want or t["rc_mode_r1"] != want:
                    cfg.append("%s rc_mode %s/%s" % (t["stem"], t["rc_mode_r0"], t["rc_mode_r1"]))
                if t["bound_ms_r0"] != 10000.0:
                    cfg.append("%s bound_ms %s" % (t["stem"], t["bound_ms_r0"]))
            if c.startswith("rc_mute") and t["n_mute_on_r0"] < 1:
                cfg.append("%s n_mute_on_r0=0" % t["stem"])
    P("violations: %s" % (cfg or "none"))
    P("left > 0 in any trial: %s" % ([t["stem"] for t in trials if (t["left"] or 0) > 0] or "none"))
    P("rank-0 classifier lines with other than one mono_ms field: %d" % sum(t["q4_bad"] for t in trials))

    # ---- 2. predictions
    P("\n== 2. predictions (judged trials only)")
    J = lambda c: judged[c]  # noqa: E731
    verdicts = []

    def verdict(pid, cells, hits_ok, n_hits, n, extra=""):
        short = any(len(judged[c]) < PLAN[c][1] for c in cells)
        v = "insufficient" if short else ("holds" if hits_ok else "fails")
        verdicts.append((pid, v))
        P("%-4s n=%-3s hits=%-6s %-12s %s" % (pid, n, n_hits, v, extra))

    def count(c, f):
        return sum(1 for t in J(c) if f(t))

    c = "rc_mute8_f1_b"
    h = count(c, lambda t: t["transparent_ok"] == 1)
    verdict("M1a", [c], h >= 9, h, len(J(c)), "transparent_ok == 1, need >= 9")
    h = count(c, lambda t: t["sock_close_cause_r0"] == "ETIMEDOUT" and t["sock_close_liveness_r0"] == "unknown")
    verdict("M1b", [c], h >= 9, h, len(J(c)), "first rank-0 close ETIMEDOUT/unknown, need >= 9")
    d = lambda t: sub_(t["reconnect_ms_r0"], t["mute_off_ms_r0"])  # noqa: E731
    h = count(c, lambda t: t["n_reconnect_r0"] >= 1 and le(0, d(t)) and le(d(t), 1500))
    verdict("M1c", [c], h >= 9, h, len(J(c)), "0 <= reconnect - mute off <= 1500 ms, need >= 9")
    h = count(c, lambda t: t["async_before_fault"] == 1)
    verdict("M1d", [c], h == 0, h, len(J(c)), "async_before_fault == 1, need == 0")
    c = "rc_mutef3s_b"
    h = count(c, lambda t: t["transparent_ok"] == 1)
    verdict("M2a", [c], h >= 9, h, len(J(c)), "transparent_ok == 1, need >= 9")
    h = count(c, lambda t: t["rc_wait_end_r0"] == "reconnected" and lt(0, t["rc_wait_ms_r0"]) and le(t["rc_wait_ms_r0"], 10000))
    verdict("M2b", [c], h >= 9, h, len(J(c)), "wait ended=reconnected, 0 < wait_ms <= 10000, need >= 9")
    c = "rc_mutef3l_b"
    h = count(c, lambda t: has(t["decl_r0"], "peer liveness unknown"))
    verdict("M3a", [c], h >= 9, h, len(J(c)), "decline 'peer liveness unknown', need >= 9")
    h = count(c, lambda t: has(t["decl_r0"], "peer's socket shows"))
    verdict("M3b", [c], h == 0, h, len(J(c)), "decline 'peer's socket shows', need == 0")
    dq = lambda t: sub_(t["decl_mono_r0"], t["q4_mono_r0"])  # noqa: E731
    h = count(c, lambda t: le(10000, dq(t)) and le(dq(t), 11500))
    verdict("M3c", [c], h >= 9, h, len(J(c)), "10000 <= decline - first classifier record <= 11500 ms, need >= 9")
    h = count(c, lambda t: t["r1_alive_at_decline"] == 1)
    verdict("M3d", [c], h >= 9, h, len(J(c)), "r1_alive_at_decline == 1, need >= 9")
    c = "rc_mutekill_b"
    h = count(c, lambda t: has(t["decl_r0"], "ECONNREFUSED"))
    verdict("M4a", [c], h >= 9, h, len(J(c)), "decline contains ECONNREFUSED, need >= 9")
    h1 = count(c, lambda t: has(t["decl_r0"], "peer liveness unknown"))
    h2 = count(c, lambda t: t["transparent_ok"] == 1)
    verdict("M4b", [c], h1 == 0 and h2 == 0, "%d+%d" % (h1, h2), len(J(c)), "unknown declines + transparent, need 0 and 0")
    h = count(c, lambda t: le(dq(t), 2000))
    verdict("M4c", [c], h >= 9, h, len(J(c)), "decline - first classifier record <= 2000 ms, need >= 9")
    g1 = ["f1_b", "f3_b", "f1g0_b", "mt256_f1_b", "bidirf_f1both_b", "bidirf_sym_b"]
    hs = [count(x, lambda t: t["transparent_ok"] == 1) for x in g1]
    verdict("G1", g1, all(x == 5 for x in hs), "/".join(map(str, hs)), "/".join(str(len(J(x))) for x in g1),
            "per cell transparent == 5 (" + ", ".join(g1) + ")")
    c = "f4_b"
    h = count(c, lambda t: (has(t["decl_r0"], "peer's socket shows FIN") or has(t["decl_r0"], "peer's socket shows ECONNRESET"))
              and t["teardown_r0"] == "no error")
    verdict("G2", [c], h == 5, h, len(J(c)), "dead-cause decline and rank-0 abort 'no error', need == 5")
    c = "f2rel_b"
    h = count(c, lambda t: t["teardown_r1"] == "no error" and t["r1rc"] is not None and t["r1rc"] != 7
              and le(t["teardown_ms_r1"], 5000) and t["r1_outcome"] == "async_error_kernel_stuck")
    verdict("G3", [c], h == 5, h, len(J(c)), "rank-1 abort returned <= 5000 ms, r1rc != 7, kernel stuck, need == 5")
    c = "rc_mute1_f1_b"
    h = count(c, lambda t: t["transparent_ok"] == 1 and t["n_mute_on_r0"] >= 1 and t["n_sock_close_r0"] == 0
              and t["n_reconnect_r0"] == 0)
    verdict("C1", [c], h == 5, h, len(J(c)), "transparent, mute on, no close, no reconnect, need == 5")
    c = "rc_mute8off_b"
    h = count(c, lambda t: has(t["decl_r0"], "no helper socket to the peer") and t["n_reconnect_r0"] == 0)
    verdict("C2", [c], h == 5, h, len(J(c)), "'no helper socket to the peer' and no reconnect, need == 5")
    med = {x: statistics.median([t["lat_p50_us"] for t in J(x)]) for x in PLAN if x.startswith("lat_")}
    d4 = med["lat_rc_on_4k"] - med["lat_s2r_on_4k"]
    d256 = med["lat_rc_on_256k"] - med["lat_s2r_on_256k"]
    verdict("L1", ["lat_rc_on_4k", "lat_s2r_on_4k"], abs(d4) <= 0.40, "-", "5+5",
            "median p50 rc %.2f vs s2r %.2f us, diff %+.2f, need |diff| <= 0.40" % (
                med["lat_rc_on_4k"], med["lat_s2r_on_4k"], d4))
    verdict("L2", ["lat_rc_on_256k", "lat_s2r_on_256k"], abs(d256) <= 0.30, "-", "5+5",
            "median p50 rc %.2f vs s2r %.2f us, diff %+.2f, need |diff| <= 0.30" % (
                med["lat_rc_on_256k"], med["lat_s2r_on_256k"], d256))
    P("verdicts: %s" % ", ".join("%s %s" % v for v in verdicts))
    P("holds %d, fails %d, insufficient %d" % tuple(sum(1 for _, v in verdicts if v == k)
                                                 for k in ("holds", "fails", "insufficient")))
    # second check: the acceptance text of predictions.csv evaluated verbatim (3.2 grammar) on the same rows
    byk = {"%s@%s" % (c, PLAN[c][0]): judged[c] for c in PLAN}
    agree = []
    for p in preds:
        v = evaluate(p["acceptance"], [x.strip() for x in p["cells"].split(";")], byk)
        mine = dict(verdicts)[p["id"]]
        agree.append(v == mine)
        if v != mine:
            P("VERBATIM %s: %s, hand-coded %s" % (p["id"], v, mine))
    P("acceptance text evaluated verbatim agrees with the hand-coded rules: %d/%d" % (sum(agree), len(agree)))

    # ---- 3. values and ranges (each over the judged trials of the named cell)
    P("\n== 3. values (ms on rank 0's clock unless noted; ranges over the judged trials of the cell)")
    c = "rc_mute8_f1_b"
    j = J(c)
    P("[%s] first rank-0 close: %s; liveness %s" % (c, sorted({t["sock_close_cause_r0"] for t in j}),
                                                   sorted({t["sock_close_liveness_r0"] for t in j})))
    P("  close - mute on: %s" % rng([sub_(t["sock_close_ms_r0"], t["mute_on_ms_r0"]) for t in j]))
    P("  mute off - mute on: %s" % rng([sub_(t["mute_off_ms_r0"], t["mute_on_ms_r0"]) for t in j]))
    P("  reconnect - mute off: %s; reconnect lines r0 %s, r1 %s; attempts r0 %s" % (
        rng([d(t) for t in j]), sorted({t["n_reconnect_r0"] for t in j}), sorted({t["n_reconnect_r1"] for t in j}),
        sorted({t["recon_attempts_r0"] for t in j})))
    P("  fault - reconnect: %s; transparent %d/%d; wait lines r0 %s; declines %s" % (
        rng([sub_(t["fault_mono_r0"], t["reconnect_ms_r0"]) for t in j]), sum(t["transparent_ok"] for t in j), len(j),
        sorted({t["n_wait_r0"] for t in j}), sorted({t["n_decl_r0"] for t in j})))
    P("  rank-1 closes (cause/liveness, first): %s" % sorted({(t["closes_r1"][0][0], t["closes_r1"][0][2])
                                                              for t in j if t["closes_r1"]}))
    c = "rc_mutef3s_b"
    j = J(c)
    P("[%s] first rank-0 close: %s; classifier class %s" % (c, sorted({(t["sock_close_cause_r0"], t["sock_close_liveness_r0"]) for t in j}),
                                                            sorted({t["q4_class_r0"] for t in j})))
    P("  classifier - close: %s" % rng([sub_(t["q4_mono_r0"], t["sock_close_ms_r0"]) for t in j]))
    P("  wait: ended %s; wait_ms %s" % (sorted({t["rc_wait_end_r0"] for t in j}), rng([t["rc_wait_ms_r0"] for t in j])))
    P("  wait start (wait line - wait_ms) - classifier: %s" % rng([sub_(sub_(t["rc_wait_mono_r0"], t["rc_wait_ms_r0"]), t["q4_mono_r0"]) for t in j]))
    P("  wait end - mute off: %s; reconnect - mute off: %s" % (
        rng([sub_(t["rc_wait_mono_r0"], t["mute_off_ms_r0"]) for t in j]), rng([d(t) for t in j])))
    P("  wait end - reconnect line: %s; transparent %d/%d; rank-1 role %s" % (
        rng([sub_(t["rc_wait_mono_r0"], t["reconnect_ms_r0"]) for t in j], "%.2f"), sum(t["transparent_ok"] for t in j),
        len(j), sorted({tuple(t["rec_r1"]) for t in j})))
    c = "rc_mutef3l_b"
    j = J(c)
    P("[%s] first rank-0 close: %s; mute-off lines on r0 %s" % (c, sorted({(t["sock_close_cause_r0"], t["sock_close_liveness_r0"]) for t in j}),
                                                                  sorted({t["n_mute_off_r0"] for t in j})))
    P("  classifier - close: %s" % rng([sub_(t["q4_mono_r0"], t["sock_close_ms_r0"]) for t in j]))
    P("  declines: %s" % sorted({t["decl_r0"] for t in j}))
    P("  decline - classifier: %s" % rng([dq(t) for t in j]))
    P("  wait: ended %s; wait_ms %s" % (sorted({t["rc_wait_end_r0"] for t in j}), rng([t["rc_wait_ms_r0"] for t in j])))
    P("  decline - devComm: %s" % rng([sub_(t["decl_mono_r0"], t["devcomm_r0"]) for t in j]))
    P("  rank-1 kernel end - decline: %s; r1rc %s; reconnects r0 %s" % (
        rng([sub_(t["r1_end_r0clock"], t["decl_mono_r0"]) for t in j]), sorted({t["r1rc"] for t in j}),
        sorted({t["n_reconnect_r0"] for t in j})))
    c = "rc_mutekill_b"
    j = J(c)
    P("[%s] rank-0 closes per trial (cause, ms after mute on, liveness):" % c)
    for t in j:
        cl = ", ".join("%s +%.0f %s" % (a, b - t["mute_on_ms_r0"], l) for a, b, l in t["closes_r0"])
        P("  %-4s %s | kill +%.0f | mute off +%.0f | classifier +%.0f | wait lines %d %s | decline +%.0f '%s' | decline - classifier %.1f" % (
            t["trial"], cl, t["kill_mono_r0"] - t["mute_on_ms_r0"], t["mute_off_ms_r0"] - t["mute_on_ms_r0"],
            t["q4_mono_r0"] - t["mute_on_ms_r0"], t["n_wait_r0"], t["rc_wait_end_r0"] or "-",
            t["decl_mono_r0"] - t["mute_on_ms_r0"], t["decl_r0"], dq(t)))
    dead_close = lambda t: next((b for a, b, l in t["closes_r0"] if l == "dead"), None)  # noqa: E731
    P("  dead close (ECONNREFUSED) before the classifier record: %d/%d; wait lines ended=dead: %d" % (
        sum(1 for t in j if lt(dead_close(t), t["q4_mono_r0"])), len(j),
        sum(1 for t in j if t["rc_wait_end_r0"] == "dead")))
    P("  dead close - mute off: %s; classifier - dead close: %s" % (
        rng([sub_(dead_close(t), t["mute_off_ms_r0"]) for t in j]), rng([sub_(t["q4_mono_r0"], dead_close(t)) for t in j])))
    P("  kill - first (ETIMEDOUT) close: %s; decline - classifier: %s" % (
        rng([sub_(t["kill_mono_r0"], t["sock_close_ms_r0"]) for t in j]), rng([dq(t) for t in j], "%.2f")))
    c = "rc_mute1_f1_b"
    j = J(c)
    P("[%s] mute on lines %s, closes %s, reconnects %s, transparent %d/%d" % (
        c, sorted({t["n_mute_on_r0"] for t in j}), sorted({t["n_sock_close_r0"] for t in j}),
        sorted({t["n_reconnect_r0"] for t in j}), sum(t["transparent_ok"] for t in j), len(j)))
    c = "rc_mute8off_b"
    j = J(c)
    P("[%s] declines %s; wait %s; reconnects r0 %s r1 %s; first close %s" % (
        c, sorted({t["decl_r0"] for t in j}), sorted({(t["rc_wait_end_r0"], t["rc_wait_ms_r0"]) for t in j}),
        sorted({t["n_reconnect_r0"] for t in j}), sorted({t["n_reconnect_r1"] for t in j}),
        sorted({(t["sock_close_cause_r0"], t["sock_close_liveness_r0"]) for t in j})))
    P("  decline - classifier: %s" % rng([dq(t) for t in j], "%.2f"))
    c = "f4_b"
    j = J(c)
    P("[%s] first rank-0 close %s; declines %s; teardown_r0 %s; reconnects r0 %s" % (
        c, sorted({(t["sock_close_cause_r0"], t["sock_close_liveness_r0"]) for t in j}), sorted({t["decl_r0"] for t in j}),
        sorted({t["teardown_r0"] for t in j}), sorted({t["n_reconnect_r0"] for t in j})))
    P("  rank-0 teardown_ms: %s" % rng([t["teardown_ms_r0"] for t in j]))
    c = "f2rel_b"
    j = J(c)
    P("[%s] teardown_ms_r1: %s; r1rc %s; r1_outcome %s; teardown_r1 %s; decl_r0 %s" % (
        c, rng([t["teardown_ms_r1"] for t in j]), sorted({t["r1rc"] for t in j}), sorted({t["r1_outcome"] for t in j}),
        sorted({t["teardown_r1"] for t in j}), sorted({t["decl_r0"] for t in j})))
    for x in g1:
        P("[%s] transparent %d/%d; declines %s" % (x, sum(t["transparent_ok"] for t in J(x)), len(J(x)),
                                                  sorted({t["decl_r0"] for t in J(x)})))
    for x in sorted(med):
        raw = []
        for t in J(x):
            v = sorted(int(ln.split(",")[1]) for ln in gzip.open(os.path.join(res, "lat", t["stem"] + "_lat_raw.csv.gz"), "rt")
                       if ln.strip())
            raw.append(statistics.median(v) / 1000.0)
        P("[%s] per-run p50 (us, kv): %s; median %.2f; per-run median of the raw samples (us): %s" % (
            x, sorted(t["lat_p50_us"] for t in J(x)), med[x], sorted("%.3f" % r for r in raw)))
    for x in PLAN:
        for t in J(x):
            if t["async_before_fault"] and x != "rc_mute8_f1_b":
                P("async_before_fault=1 in %s" % t["stem"])

    # ---- 3b. further values, used to check the statements of EXPERIMENT.md section 15
    P("\n== 3b. further values (for the section 15 check)")
    med_ = lambda v: statistics.median([x for x in v if x is not None])  # noqa: E731
    j = J("rc_mute8_f1_b")
    P("[rc_mute8_f1_b] reconnect - mute off median %.1f; fault - mute off %s" % (
        med_([d(t) for t in j]), rng([sub_(t["fault_mono_r0"], t["mute_off_ms_r0"]) for t in j])))
    j = J("rc_mutef3s_b")
    P("[rc_mutef3s_b] close - mute on %s; mute off - classifier %s; wait_ms median %.1f; attempts r0 %s" % (
        rng([sub_(t["sock_close_ms_r0"], t["mute_on_ms_r0"]) for t in j]),
        rng([sub_(t["mute_off_ms_r0"], t["q4_mono_r0"]) for t in j]), med_([t["rc_wait_ms_r0"] for t in j]),
        sorted({t["recon_attempts_r0"] for t in j})))
    j = J("rc_mutef3l_b")
    P("[rc_mutef3l_b] close - mute on %s; wait start - classifier %s" % (
        rng([sub_(t["sock_close_ms_r0"], t["mute_on_ms_r0"]) for t in j]),
        rng([sub_(sub_(t["rc_wait_mono_r0"], t["rc_wait_ms_r0"]), t["q4_mono_r0"]) for t in j], "%.2f")))
    j = J("rc_mutekill_b")
    P("[rc_mutekill_b] first close - mute on %s; r1_alive_at_decline %d/%d; decline - kill %s" % (
        rng([sub_(t["sock_close_ms_r0"], t["mute_on_ms_r0"]) for t in j]), sum(t["r1_alive_at_decline"] for t in j),
        len(j), rng([sub_(t["decl_mono_r0"], t["kill_mono_r0"]) for t in j])))
    j = J("rc_mute1_f1_b")
    P("[rc_mute1_f1_b] fault - mute off %s; mute-off lines %s" % (
        rng([sub_(t["fault_mono_r0"], t["mute_off_ms_r0"]) for t in j]), sorted({t["n_mute_off_r0"] for t in j})))
    j = J("rc_mute8off_b")
    P("[rc_mute8off_b] close - mute on %s; r1_alive_at_decline %d/%d; rank-1 kernel end - decline %s" % (
        rng([sub_(t["sock_close_ms_r0"], t["mute_on_ms_r0"]) for t in j]), sum(t["r1_alive_at_decline"] for t in j),
        len(j), rng([sub_(t["r1_end_r0clock"], t["decl_mono_r0"]) for t in j])))
    j = J("f4_b")
    P("[f4_b] decline - classifier %s" % rng([dq(t) for t in j], "%.2f"))
    # raw substring counts against the parsed lines (nothing missed by the patterns)
    want = {"reconnect wait for rank": "wait", "reconnected gen=": "recon", "closed cause=": "close",
            "GIN/TS: declined": "decl", "TEST socket mute on": "mute_on", "TEST socket mute off": "mute_off",
            "helper socket reconnect=": "rcmode"}
    for s, key in want.items():
        raw_n = parsed = 0
        for f in glob.glob(os.path.join(res, "*", "*_r[01].log")):
            txt = open(f, errors="replace").read()
            raw_n += txt.count(s)
            parsed += len(scan(f)[key])
        P("lines '%s': raw %d, parsed %d" % (s, raw_n, parsed))

    # ---- 4. safety per hold
    P("\n== 4. safety per hold")
    CMD = re.compile(r"cmd|command", re.I)
    BAD = re.compile(r"failed|timeout|leak", re.I)

    def cmd_err(path):
        return sum(1 for ln in open(path, errors="replace") if "mlx5" in ln.lower() and CMD.search(ln) and BAD.search(ln))

    def fw(path):
        s = 0
        for ln in open(path, errors="replace"):
            for k2, v in re.findall(r"\b(failed|failed_mbox_status)=(\d+)", ln):
                s += int(v)
        return s
    for h in ("H1", "H2", "H3", "H4", "fill"):
        row = []
        for node in ("rain", "sunny"):
            b = open(os.path.join(res, "mlx5_before-%s_%s.txt" % (h, node)), errors="replace").read().splitlines()
            a = open(os.path.join(res, "mlx5_after-%s_%s.txt" % (h, node)), errors="replace").read().splitlines()
            new_lines = len(set(a) - set(b))
            row.append("%s lines %d->%d new %d cmd_err %d->%d" % (
                node, len(b), len(a), new_lines, cmd_err(os.path.join(res, "mlx5_before-%s_%s.txt" % (h, node))),
                cmd_err(os.path.join(res, "mlx5_after-%s_%s.txt" % (h, node)))))
        fb, fa = fw(os.path.join(res, "fwcmd_before-%s.txt" % h)), fw(os.path.join(res, "fwcmd_after-%s.txt" % h))
        newf = os.path.getsize(os.path.join(res, "mlx5_new_%s.txt" % h))
        gpu = []
        for tag in ("before", "after"):
            g = [ln.strip() for ln in open(os.path.join(res, "snap_%s-%s.txt" % (tag, h))) if " gpu: " in ln]
            gpu.append(len(g))
        ho = open(os.path.join(res, "hold_%s.out" % h), errors="replace").read()
        lefts = [int(x) for x in re.findall(r"\bleft=(\d+)", ho)]
        busy = re.findall(r"sunny_busy_after=(\d+)", ho)
        rcl = re.findall(r"command exited rc=(\d+)", ho)
        P("%-4s %s | fwcmd failed sum %d->%d | mlx5_new file %d B | GPU process lines before/after %s | trials %d, "
          "max left %s | sunny_busy_after %s | hold rc %s" % (h, "; ".join(row), fb, fa, newf, gpu, len(lefts),
                                                              max(lefts) if lefts else "-", busy, rcl))
    P("STOP_mlx5 present: %s" % os.path.exists(os.path.join(res, "STOP_mlx5")))
    # trials per hold from hold output vs trial files
    seen = {}
    for h in ("H1", "H2", "H3", "H4", "fill"):
        seen[h] = len(re.findall(r"\] r0rc=", open(os.path.join(res, "hold_%s.out" % h), errors="replace").read()))
    P("trial result lines per hold: %s (sum %d)" % (seen, sum(seen.values())))

    print("\n".join(out))
    if rows_out:
        keys = ["stem", "cell", "build", "trial", "excl", "transparent_ok", "sock_close_cause_r0", "sock_close_liveness_r0",
                "mute_on_ms_r0", "sock_close_ms_r0", "mute_off_ms_r0", "n_reconnect_r0", "reconnect_ms_r0",
                "n_reconnect_r1", "rc_wait_end_r0", "rc_wait_ms_r0", "rc_wait_mono_r0", "q4_mono_r0", "decl_r0",
                "decl_mono_r0", "kill_mono_r0", "r1_alive_at_decline", "r1_end_r0clock", "async_before_fault",
                "teardown_r0", "teardown_r1", "teardown_ms_r1", "r1rc", "r1_outcome", "lat_p50_us", "rc_mode_r0",
                "rc_mode_r1", "left"]
        with open(rows_out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            for t in trials:
                w.writerow(t)


if __name__ == "__main__":
    main()
