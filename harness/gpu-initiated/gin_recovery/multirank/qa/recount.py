#!/usr/bin/env python3
"""gin-multirank: independent recount of the main run from the raw per-trial files.

Written without reading or running the study's scorer (score.py), its column builder (rows_mr.py), SCORE.md or any
trials_*.csv. Every column is parsed again from <stem>_meta.txt, <stem>_r<r>.kv, <stem>_r<r>.log and <stem>_kill.out,
following EXPERIMENT.md section 3.1 (and gin_mr.cu / the hd library source for the line formats). The acceptance rules of
predictions.csv are evaluated with an evaluator of the section-3.2 grammar written here (s2_close EXPERIMENT.md 3.2:
count, None rule, has, nonempty, median, abs, "per cell:").

Read-only: it opens files for reading and runs read-only git commands (git show, git rev-parse). It writes nothing.

usage: python3 qa/recount.py [results-dir]      (default: results/20261009 next to this folder)
       python3 qa/recount.py --trials             (also print one compact line per trial)
"""
import csv
import glob
import hashlib
import os
import re
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
REPO_REL = "harness/gpu-initiated/gin_recovery/multirank"
TAG = "prereg/gin-multirank-v1"
ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
SHOW_TRIALS = "--trials" in sys.argv
RES = ARGS[0] if ARGS else os.path.join(STUDY, "results", "20261009")
PILOT = os.path.join(STUDY, "results", "20261009_pilot")

out = []


def P(s=""):
    out.append(s)


# ----------------------------------------------------------------------------------------------------------------------
# small helpers
# ----------------------------------------------------------------------------------------------------------------------
def git(*a):
    return subprocess.run(["git", "-C", STUDY] + list(a), capture_output=True, check=True).stdout


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def rng(vals, nd=1):
    v = [x for x in vals if x is not None]
    if not v:
        return "-"
    lo, hi = min(v), max(v)
    f = "%%.%df" % nd
    return (f % lo) if lo == hi else (f % lo + "–" + f % hi)


def med(vals):
    v = [x for x in vals if x is not None]
    return statistics.median(v) if v else None


KEYRE = re.compile(r"(?:^|\s)([A-Za-z_][A-Za-z0-9_/]*)=")


def parse_kv_line(line):
    """k=v tokens; a value runs to the next ' key=' (values such as 'no error' hold spaces)."""
    d = {}
    ms = list(KEYRE.finditer(line))
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(line)
        d[m.group(1)] = line[m.end():end].strip()
    return d


def read_kv(path):
    d = {}
    if not os.path.exists(path):
        return None
    with open(path, errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            d.update(parse_kv_line(line))
    return d


# ----------------------------------------------------------------------------------------------------------------------
# log line patterns (hd gin_host_gdaki.cc md5 36995301, dev_runtime.cc, gin_mr.cu)
# ----------------------------------------------------------------------------------------------------------------------
R_TSON = re.compile(r"GIN/TS: transparent recovery ON rank=(\d+) gated_qps=(\d+)")
R_UA = re.compile(r"GIN/TS: user devComm abort flag set rank=(\d+)")
R_PR = re.compile(r"GIN/TS: pair reset=1 rank=")
R_PC = re.compile(r"GIN/TS: pair check=1 rank=")
R_OW = re.compile(r"GIN/TS: helper liveness oneway=1 rank=")
R_HD = re.compile(r"GIN/TS: harden=1 rank=")
R_MRGE = re.compile(r"Multiple Ranks are using the same GPU")
R_FIRE = re.compile(r"GIN/FAULT: GDAKI fault fired.*?: moved (\d+)/(\d+) GIN QP\(s\) to ERR (?:context=(\d+) )?"
                    r"fire_mono_ms=([\d.]+) done_mono_ms=([\d.]+)")
R_ROUND = re.compile(r"GIN/TS: rank (\d+): round (\d+) peer (\d+) scope=(\S+) qps=(\d+) reason=(\S+) mono_ms=([\d.]+)")
R_REC = re.compile(r"GIN/TS: recovered rank=(\d+) peer=(\d+) role=(initiator|responder) (.*)$")
R_DECL = re.compile(r'GIN/TS: declined rank=(\d+) peer=(\d+) reason="([^"]*)" class=(-?\d+) mono_ms=([\d.]+)')
R_WD = re.compile(r"GIN/TS: watchdog rank=")
R_REFUSED = re.compile(r"GIN/TS: rank (\d+): REQ round (\d+) from rank (\d+) scope=(\S+) checked=(\d+) not_rts=(\d+) "
                       r"check_us=\S+ refused reason=(\S+) mono_ms=([\d.]+)")
R_ACCEPTED = re.compile(r"GIN/TS: rank (\d+): REQ round (\d+) from rank (\d+) scope=(\S+) .* accepted mono_ms=([\d.]+)")
R_RERUN = re.compile(r"GIN/TS: rank (\d+): peer (\d+) refused the scope of round (\d+); rerunning as a full reset "
                     r"mono_ms=([\d.]+)")
R_EP = re.compile(r"GIN/TS: rank (\d+) gate epochs to rank (\d+): \[([^\]]*)\]")
R_QS = re.compile(r"GIN/TS: rank (\d+) qp states to rank (\d+): \[([^\]]*)\]")
R_Q4 = re.compile(r"GIN/Q4: device-classified error CQE rank=(\d+) seq=(\d+) ctx=(\d+) peer=(\d+) .*? class=(\S+) .*"
                  r"mono_ms=([\d.]+)\s*$")
R_JD = re.compile(r"GIN/TS: rank (\d+): rank (\d+) judged dead \(cause=([^)]*)\) mono_ms=([\d.]+)")
R_ESC = re.compile(r"GIN/TS: escalated rank=")
R_FWO = re.compile(r"more than NCCL_GIN_TS_FW_MS")
R_COPY = re.compile(r"\(NCCL_GIN_TS_COPY_MS\)")
R_CANCEL = re.compile(r"GIN/TS: rank \d+: round \d+ (?:with|from) rank \d+ cancelled .*before the commit")
R_KNOB = re.compile(r"GIN/TS: TEST knobs rank=(\d+) stall_ms=(-?\d+)")
R_SOCKLOST = re.compile(r"GIN/TS: rank (\d+): socket to rank (\d+) closed cause=(\S+) mono_ms=([\d.]+) liveness=(\S+)")
R_BIND = re.compile(r"^bind: ")
R_DONE = re.compile(r"\[rank(\d+)\] DONE (.*)$")


class Rank:
    pass


def parse_log(path):
    L = Rank()
    L.lines = []
    if os.path.exists(path):
        with open(path, errors="replace") as f:
            L.lines = [x.rstrip("\n") for x in f]
    L.tson, L.ua, L.pr, L.pc, L.ow, L.hd, L.mrge = [], 0, 0, 0, 0, 0, 0
    L.fires, L.rounds, L.recs, L.decls, L.wd, L.refused, L.accepted, L.rerun = [], [], [], [], 0, [], [], []
    L.ep, L.qs, L.q4, L.jd, L.esc, L.fwo, L.copy, L.cancel, L.knob, L.socklost = [], [], [], [], 0, 0, 0, 0, [], []
    L.bind, L.done = 0, None
    for x in L.lines:
        if R_BIND.search(x):
            L.bind = 1
        m = R_DONE.search(x)
        if m:
            L.done = m.group(2)
        if "GIN/" not in x and "Multiple Ranks" not in x:
            continue
        m = R_TSON.search(x)
        if m:
            L.tson.append((int(m.group(1)), int(m.group(2))))
        if R_UA.search(x):
            L.ua += 1
        if R_PR.search(x):
            L.pr += 1
        if R_PC.search(x):
            L.pc += 1
        if R_OW.search(x):
            L.ow += 1
        if R_HD.search(x):
            L.hd += 1
        if R_MRGE.search(x):
            L.mrge += 1
        m = R_FIRE.search(x)
        if m:
            L.fires.append(dict(moved=int(m.group(1)), of=int(m.group(2)), ctx=m.group(3), t=float(m.group(4)),
                                tdone=float(m.group(5))))
        m = R_ROUND.search(x)
        if m:
            L.rounds.append(dict(r=int(m.group(1)), k=int(m.group(2)), p=int(m.group(3)), scope=m.group(4),
                                 qps=int(m.group(5)), reason=m.group(6), t=float(m.group(7))))
        m = R_REC.search(x)
        if m:
            d = parse_kv_line(m.group(4))
            d.update(r=int(m.group(1)), p=int(m.group(2)), role=m.group(3))
            L.recs.append(d)
        m = R_DECL.search(x)
        if m:
            L.decls.append(dict(r=int(m.group(1)), p=int(m.group(2)), why=m.group(3), cls=int(m.group(4)),
                                t=float(m.group(5))))
        if R_WD.search(x):
            L.wd += 1
        m = R_REFUSED.search(x)
        if m:
            L.refused.append(dict(r=int(m.group(1)), k=int(m.group(2)), frm=int(m.group(3)), scope=m.group(4),
                                  not_rts=int(m.group(6)), why=m.group(7), t=float(m.group(8))))
        m = R_ACCEPTED.search(x)
        if m:
            L.accepted.append(dict(r=int(m.group(1)), frm=int(m.group(3)), t=float(m.group(5))))
        m = R_RERUN.search(x)
        if m:
            L.rerun.append(dict(r=int(m.group(1)), p=int(m.group(2)), k=int(m.group(3)), t=float(m.group(4))))
        m = R_EP.search(x)
        if m:
            L.ep.append((int(m.group(1)), int(m.group(2)), [int(v) for v in m.group(3).split(",") if v.strip()]))
        m = R_QS.search(x)
        if m:
            L.qs.append((int(m.group(1)), int(m.group(2)), [int(v) for v in m.group(3).split(",") if v.strip()]))
        m = R_Q4.search(x)
        if m:
            L.q4.append(dict(r=int(m.group(1)), seq=int(m.group(2)), ctx=int(m.group(3)), p=int(m.group(4)),
                             cls=m.group(5), t=float(m.group(6))))
        m = R_JD.search(x)
        if m:
            L.jd.append(dict(r=int(m.group(1)), p=int(m.group(2)), cause=m.group(3), t=float(m.group(4))))
        if R_ESC.search(x):
            L.esc += 1
        if R_FWO.search(x):
            L.fwo += 1
        if R_COPY.search(x):
            L.copy += 1
        if R_CANCEL.search(x):
            L.cancel += 1
        m = R_KNOB.search(x)
        if m:
            L.knob.append((int(m.group(1)), int(m.group(2))))
        m = R_SOCKLOST.search(x)
        if m:
            L.socklost.append(dict(r=int(m.group(1)), p=int(m.group(2)), cause=m.group(3), t=float(m.group(4)),
                                   liveness=m.group(5)))
    return L


# ----------------------------------------------------------------------------------------------------------------------
# one trial -> columns of section 3.1
# ----------------------------------------------------------------------------------------------------------------------
def j(items, sep=";"):
    items = sorted(items)
    return sep.join(items) if items else ""


def edges_of(n, spec):
    if spec in ("all", "", None):
        return [(a, b) for a in range(n) for b in range(n) if a != b]
    e = []
    for t in spec.split(","):
        a, b = t.split("-")
        e.append((int(a), int(b)))
    return e


def node_of(r):
    return "rain" if r % 2 == 0 else "sunny"


def load_trial(meta_path):
    stem = meta_path[:-len("_meta.txt")]
    with open(meta_path) as f:
        meta = parse_kv_line(f.read().strip())
    T = Rank()
    T.stem = stem
    T.hold = os.path.basename(os.path.dirname(stem))
    T.name = os.path.basename(stem)
    T.meta = meta
    n = int(meta["n"])
    T.n = n
    T.kv = [read_kv("%s_r%d.kv" % (stem, r)) for r in range(n)]
    T.log = [parse_log("%s_r%d.log" % (stem, r)) for r in range(n)]
    T.kill = read_kv(stem + "_kill.out") if os.path.exists(stem + "_kill.out") else None
    return T


def compute(T):
    c = {}
    m, n, kv, lg = T.meta, T.n, T.kv, T.log
    iters = int(m["iters"])
    gap_ms = float(m["gap_us"]) / 1000.0
    c["cell"], c["build"], c["n"], c["flush"], c["iters"] = m["cell"], m["lib"], n, m["flush"], iters
    c["trial"] = m["trial"]
    c["bind_fail"] = 1 if any(L.bind for L in lg) else 0
    # clock: rank r's CLOCK_MONOTONIC minus rank 0's, from rank 0's kv
    k0 = kv[0] or {}
    off = [0.0] + [fnum(k0.get("clock_offset_ms_r%d" % r)) for r in range(1, n)]
    T.off = off

    def to0(r, t):
        if t is None or off[r] is None:
            return None
        return t - off[r]

    T.to0 = to0
    ndev = sum(1 for k in kv if k and "devcomm_mono_ms" in k)
    c["n_devcomm"] = ndev
    c["init_fail"] = 1 if ndev < n else 0
    c["mrge_err"] = 1 if any(L.mrge for L in lg) else 0
    tson = [q for L in lg for q in L.tson]
    c["n_ts_on"] = len(tson)
    c["gq_min"] = min(q for _, q in tson) if tson else None
    c["gq_max"] = max(q for _, q in tson) if tson else None
    c["n_ua"] = sum(L.ua for L in lg)
    c["n_pr"] = sum(L.pr for L in lg)
    c["n_pc"] = sum(L.pc for L in lg)
    c["n_ow"] = sum(L.ow for L in lg)
    c["n_hd"] = sum(L.hd for L in lg)
    # edges
    E = edges_of(n, m["edges"])
    bad = []
    edge_ok = {}
    for (a, b) in E:
        ka, kb = kv[a] or {}, kv[b] or {}
        ab = "%d%d" % (a, b)
        ok = (fnum(ka.get("tx_%s_done" % ab)) == iters and ka.get("tx_%s_rc" % ab) == "no error"
              and fnum(kb.get("rx_%s_done" % ab)) == iters and kb.get("rx_%s_rc" % ab) == "no error"
              and fnum(kb.get("rx_%s_devbad" % ab)) == 0 and fnum(kb.get("rx_%s_hostbad" % ab)) == 0
              and fnum(kb.get("rx_%s_sigexact" % ab)) == 1)
        edge_ok[(a, b)] = ok
        if not ok:
            bad.append("%d>%d" % (a, b))
    T.edge_ok = edge_ok
    asy = []
    for r in range(n):
        k = kv[r] or {}
        if k.get("async_first") not in (None, "none"):
            asy.append("r%d" % r)
    outcomes_ok = all((kv[r] or {}).get("outcome") == "ok" for r in range(n))
    c["edges_bad"] = j(bad)
    c["async_ranks"] = j(asy, ",")
    c["transparent_ok"] = 1 if (not bad and outcomes_ok and not asy) else 0
    # hooks
    fires = []
    fit = True
    for r in range(n):
        for fr in lg[r].fires:
            fires.append("%d:%s" % (r, fr["ctx"] if fr["ctx"] is not None else "all"))
            la = fnum((kv[r] or {}).get("launch_mono_ms"))
            if la is None or not (la < fr["t"] < la + iters * gap_ms):
                fit = False
    c["fires"] = j(fires)
    c["fire_in_traffic"] = (1 if fit else 0) if fires else None
    # rounds, recoveries, declines
    rounds = [rd for L in lg for rd in L.rounds]
    c["rounds"] = j("%d>%d:%d:%s" % (rd["r"], rd["p"], rd["qps"], rd["reason"]) for rd in rounds)
    c["n_rounds"] = len(rounds)  # not in the 3.1 table; I3 uses it (count of round lines)
    recs = [x for L in lg for x in L.recs]
    c["rec_i"] = j("%d-%d" % (x["r"], x["p"]) for x in recs if x["role"] == "initiator")
    c["rec_r"] = j("%d-%d" % (x["r"], x["p"]) for x in recs if x["role"] == "responder")
    c["n_rec_i"] = sum(1 for x in recs if x["role"] == "initiator")
    decls = [x for L in lg for x in L.decls]
    c["decl"] = j("%d-%d" % (x["r"], x["p"]) for x in decls)
    c["decl_reasons"] = j("%d-%d=%s" % (x["r"], x["p"], x["why"]) for x in decls)
    c["n_decl"] = len(decls)
    c["n_hs"] = sum(1 for x in decls if x["why"] == "handshake timeout")
    c["n_watchdog"] = sum(L.wd for L in lg)
    c["n_refused"] = sum(len(L.refused) for L in lg)
    c["n_rerun"] = sum(len(L.rerun) for L in lg)  # extra, not a 3.1 column
    # teardown
    epnz, epp, nr, nrp = [], set(), [], set()
    for L in lg:
        for (r, p, v) in L.ep:
            for ci, x in enumerate(v):
                if x != 0:
                    epnz.append("%d-%d-%d=%d" % (r, p, ci, x))
                    epp.add("p%d" % p)
        for (r, p, v) in L.qs:
            for ci, x in enumerate(v):
                if x != 3:
                    nr.append("%d-%d-%d=%d" % (r, p, ci, x))
                    nrp.add("p%d" % p)
    c["ep_nz"], c["n_ep_nz"], c["ep_peers"] = j(epnz), len(epnz), j(epp)
    c["notrts"], c["n_notrts"], c["notrts_peers"] = j(nr), len(nr), j(nrp)
    c["n_ep_lines"] = sum(len(L.ep) for L in lg)
    c["n_qs_lines"] = sum(len(L.qs) for L in lg)
    q4f = []
    for r in range(n):
        if lg[r].q4:
            q4f.append("%d:%s" % (r, lg[r].q4[0]["cls"]))
    c["q4_first"] = j(q4f)
    # kill
    kr = m.get("kill_rank", "")
    c["killed"] = None
    c["kill_ms0"] = None
    c["kill_in_traffic"] = None
    if kr != "":
        kr = int(kr)
        km = fnum((T.kill or {}).get("kill_mono_ms"))
        c["killed"] = 1 if km is not None else 0
        if km is not None:
            k0ms = to0(kr, km)
            c["kill_ms0"] = k0ms
            launches = [to0(r, fnum((kv[r] or {}).get("launch_mono_ms"))) for r in range(n)]
            if all(x is not None for x in launches):
                after = all(k0ms > x for x in launches)
                earliest_end = min(x + iters * gap_ms for x in launches)
                c["kill_in_traffic"] = 1 if (after and k0ms <= earliest_end - 5000.0) else 0
            else:
                c["kill_in_traffic"] = 0
        for r in range(n):
            ds = [to0(r, x["t"]) for x in lg[r].decls]
            c["decl_after_kill_ms_r%d" % r] = (min(ds) - c["kill_ms0"]) if (ds and c["kill_ms0"] is not None) else None
        surv = [(a, b) for (a, b) in E if a != kr and b != kr]
        c["n_surv_edges"] = len(surv)
        c["surv_edges_ok"] = sum(1 for e in surv if edge_ok[e])
        c["surv_tx_failed"] = sum(1 for (a, b) in surv if (kv[a] or {}).get("tx_%d%d_rc" % (a, b)) != "no error")
        c["surv_rx_failed"] = sum(1 for (a, b) in surv if (kv[b] or {}).get("rx_%d%d_rc" % (a, b)) != "no error")
        c["n_judged_dead"] = sum(len(L.jd) for L in lg)
    else:
        c["n_judged_dead"] = sum(len(L.jd) for L in lg)
    c["n_esc"] = sum(L.esc for L in lg)
    c["n_fw_over"] = sum(L.fwo for L in lg)
    c["n_copy_to"] = sum(L.copy for L in lg)
    c["n_cancel"] = sum(L.cancel for L in lg)
    # f3 detection: rank 0's first classifier record - rank 1's first hook fire, rank 0's clock
    c["f3_detect_ms"] = None
    if n > 1 and lg[0].q4 and lg[1].fires:
        c["f3_detect_ms"] = lg[0].q4[0]["t"] - to0(1, lg[1].fires[0]["t"])
    # held window (driver kv), every rank
    for r in range(n):
        k = kv[r] or {}
        c["win_edge_r%d" % r] = k.get("win_edge")
        for key, val in k.items():
            if re.match(r"w_\d\d_in$", key) and r == 0:
                c[key] = fnum(val)
    # overlaps of rank 0's rounds
    resp = [(fnum(x.get("t_req")), fnum(x.get("t_resumed"))) for x in lg[0].recs if x["role"] == "responder"]
    init = [(fnum(x.get("t_start")), fnum(x.get("t_resumed"))) for x in lg[0].recs if x["role"] == "initiator"]

    def overlap(iv):
        if len(iv) < 2:
            return None
        for i in range(len(iv)):
            for k in range(i + 1, len(iv)):
                (a1, b1), (a2, b2) = iv[i], iv[k]
                if a2 < b1 and a1 < b2:
                    return 1
        return 0

    c["resp_overlap_r0"] = overlap(resp)
    c["init_overlap_r0"] = overlap(init)
    # first round line per rank (rank 0 clock), spread, first handshake timeout after that rank's first round line
    first_round = {}
    for r in range(n):
        if lg[r].rounds:
            first_round[r] = to0(r, min(x["t"] for x in lg[r].rounds))
    c["cyc_spread_ms"] = (max(first_round.values()) - min(first_round.values())) if first_round else None
    hs = [(to0(r, x["t"]), r) for r in range(n) for x in lg[r].decls if x["why"] == "handshake timeout"]
    c["hs_first_after_round_ms"] = None
    if hs:
        t, r = min(hs)
        if r in first_round:
            c["hs_first_after_round_ms"] = t - first_round[r]
    it = [fnum(x.get("total_us")) / 1000.0 for x in recs if x["role"] == "initiator" and fnum(x.get("total_us")) is not None]
    c["init_total_ms_min"] = min(it) if it else None
    c["init_total_ms_max"] = max(it) if it else None
    allr = [to0(r, x["t"]) for r in range(n) for x in lg[r].rounds]
    res = [to0(r, fnum(x.get("t_resumed"))) for r in range(n) for x in lg[r].recs if fnum(x.get("t_resumed")) is not None]
    c["rec_first_after_round_ms"] = (min(res) - min(allr)) if (res and allr) else None
    c["rec_last_after_round_ms"] = (max(res) - min(allr)) if (res and allr) else None
    c["knob_stall"] = j("%d:%d" % (r, s) for L in lg for (r, s) in L.knob)
    # latency (sender kv)
    c["p50_01"] = fnum((kv[0] or {}).get("tx_01_p50_us")) if (0, 1) in E else None
    inter = [fnum((kv[a] or {}).get("tx_%d%d_p50_us" % (a, b))) for (a, b) in E if node_of(a) != node_of(b)]
    inter = [x for x in inter if x is not None]
    c["p50_inter_med"] = statistics.median(inter) if inter else None
    mx = [fnum((kv[a] or {}).get("tx_%d%d_max_us" % (a, b))) for (a, b) in E]
    mx = [x for x in mx if x is not None]
    c["max_all"] = max(mx) if mx else None
    T.c = c
    return c


# ----------------------------------------------------------------------------------------------------------------------
# section-3.2 grammar
# ----------------------------------------------------------------------------------------------------------------------
class _NA:
    """a blank cell: every comparison with it is false, arithmetic with it stays blank"""

    def _f(self, o):
        return False

    __eq__ = __ne__ = __lt__ = __le__ = __gt__ = __ge__ = _f

    def _s(self, o=None):
        return self

    __add__ = __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = __truediv__ = __rtruediv__ = _s
    __neg__ = __abs__ = _s

    def __bool__(self):
        return False

    def __hash__(self):
        return 0

    def __repr__(self):
        return "NA"


NA = _NA()


def conv(v):
    if v is None or v == "":
        return NA
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except ValueError:
        return str(v)


def g_has(f, s):
    return (f is not NA) and (s in str(f))


def g_nonempty(f):
    return f is not NA


def g_abs(x):
    return abs(x)


def split_count(expr):
    """replace count(E) by __count(<repr E>) and median(F, "K") by __median("F", "K")"""
    outp, i = "", 0
    while True:
        k = expr.find("count(", i)
        if k < 0:
            outp += expr[i:]
            break
        outp += expr[i:k]
        depth, q = 0, k + len("count")
        for p in range(q, len(expr)):
            if expr[p] == "(":
                depth += 1
            elif expr[p] == ")":
                depth -= 1
                if depth == 0:
                    break
        inner = expr[q + 1:p]
        outp += "__count(%r)" % inner
        i = p + 1
    outp = re.sub(r'median\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*"([^"]+)"\s*\)', r'__median("\1", "\2")', outp)
    return outp


def names_in(expr):
    toks = set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", re.sub(r'"[^"]*"', "", expr)))
    return toks - {"count", "has", "nonempty", "median", "abs", "and", "or", "not", "per", "cell"}


# ----------------------------------------------------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------------------------------------------------
P("# gin-multirank independent recount (qa/recount.py)")
P()
P("results dir: `%s`" % os.path.relpath(RES, STUDY))
P()

# ---- integrity -------------------------------------------------------------------------------------------------------
P("## 1. Pre-registration integrity")
P()
with open(os.path.join(STUDY, "predictions.csv"), "rb") as f:
    pred_bytes = f.read()
h_work = sha256(pred_bytes)
with open(os.path.join(STUDY, "PREREG.txt")) as f:
    prereg_txt = f.read()
m = re.search(r"\b([0-9a-f]{64})\s+predictions\.csv", prereg_txt)
h_prereg = m.group(1) if m else None
tag_commit = git("rev-parse", TAG + "^{commit}").decode().strip()
tag_obj_type = git("cat-file", "-t", TAG).decode().strip()
head = git("rev-parse", "HEAD").decode().strip()
h_tag = sha256(git("show", "%s:%s/predictions.csv" % (TAG, REPO_REL)))
prereg_tag = git("show", "%s:%s/PREREG.txt" % (TAG, REPO_REL)).decode()
tag_date = git("log", "-1", "--format=%cd", "--date=iso", TAG).decode().strip()
P("- tag `%s` (%s object) -> commit `%s`, committed %s; HEAD of the worktree `%s` [measured]"
  % (TAG, tag_obj_type, tag_commit[:8], tag_date, head[:8]))
P("- sha256 predictions.csv: working tree `%s`, PREREG.txt `%s`, file at the tag `%s` -> %s [measured]"
  % (h_work[:16], (h_prereg or "?")[:16], h_tag[:16],
     "ALL EQUAL" if h_work == h_prereg == h_tag else "MISMATCH"))
P("- PREREG.txt in the working tree equals the tag's: %s [measured]" % (prereg_txt == prereg_tag))
P("- predictions.csv rows: %d [measured]" % (len(list(csv.DictReader(open(os.path.join(STUDY, "predictions.csv")))))))

exp_work = open(os.path.join(STUDY, "EXPERIMENT.md"), "rb").read().decode()
exp_tag = git("show", "%s:%s/EXPERIMENT.md" % (TAG, REPO_REL)).decode()


def section(text, num):
    lines = text.split("\n")
    s = None
    for i, x in enumerate(lines):
        if re.match(r"^## %d\. " % num, x):
            s = i
            continue
        if s is not None and x.startswith("## "):
            return "\n".join(lines[s:i])
    return "\n".join(lines[s:]) if s is not None else None


for num in (2, 3, 7, 8):
    a, b = section(exp_work, num), section(exp_tag, num)
    P("- EXPERIMENT.md section %d: %d bytes, byte-identical to the tag: %s [measured]"
      % (num, len(a.encode()) if a else -1, a is not None and a == b))
ADDR = re.compile(rb"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")  # masked, never printed (git filter mgmtip)
same, masked_only = [], []
for f in ("gin_mr.cu", "run_mr.sh", "cells.sh", "hold.sh", "chain.sh", "build_mr.sh", "deploy_mr.sh"):
    a = open(os.path.join(STUDY, f), "rb").read()
    b = git("show", "%s:%s/%s" % (TAG, REPO_REL, f))
    if a == b:
        same.append(f)
    elif ADDR.sub(b"<addr>", a) == ADDR.sub(b"<addr>", b):
        masked_only.append(f)
P("- whole EXPERIMENT.md identical to the tag: %s [measured]" % (exp_work == exp_tag))
P("- run scripts and driver source against the tag: byte-identical %s; identical except the management-address lines "
  "that the repository's mgmtip git filter rewrites %s; other differences: %s [measured; addresses not printed]"
  % (same, masked_only, "none" if len(same) + len(masked_only) == 7 else "YES"))
P("- gin_mr.cu md5 `%s` (EXPERIMENT.md 5 says `fd90b11f`) [measured]"
  % hashlib.md5(open(os.path.join(STUDY, "gin_mr.cu"), "rb").read()).hexdigest()[:8])

# planned counts from the tag's section 7
plan = {}
kinds = {}
for x in section(exp_tag, 7).split("\n"):
    mm = re.match(r"^\| `([a-z0-9_]+)` \| [^|]* \| ([^|]*?) \| ([^|]*) \|$", x)
    if mm:
        cnt = re.findall(r"\d+", mm.group(2))
        plan[mm.group(1)] = int(cnt[-1]) if cnt else None
        kinds[mm.group(1)] = mm.group(3).strip()
plan.pop("mr4_nomrge", None)  # pilot only
P()

# ---- trials ----------------------------------------------------------------------------------------------------------
metas = sorted(glob.glob(os.path.join(RES, "h*", "*_meta.txt")))
trials = []
for mp in metas:
    T = load_trial(mp)
    compute(T)
    trials.append(T)

EXPECT_FIRES = {"mr4_f1_01": "0:0", "mr4_f1_02": "0:1", "mr4_f3_01": "1:0", "mr4_f1_01_23": "0:0;2:8",
                "mr4_f1_10_30": "1:3;3:9", "mr4_f1all0": "0:all", "mr4_cyc_stall": "0:0;1:4;2:6",
                "mr4_chain_stall": "0:0;1:4", "mr3_f1_01": "0:0"}
KILL_CELLS = {"mr4_kill3", "mr4_kill3_peer"}
ORDER_CELLS = {"mr4_cyc_stall", "mr4_chain_stall"}
KNOB_EXPECT = {"mr4_cyc_stall": "0:300;1:300;2:300", "mr4_chain_stall": "0:300;1:300"}
FLUSH_EXPECT = {"mr4_none_peer": "peer", "mr4_kill3_peer": "peer"}

for T in trials:
    c = T.c
    why = []
    if c["bind_fail"] == 1:
        why.append("bind_fail")
    if c["cell"] in EXPECT_FIRES and (c["fires"] != EXPECT_FIRES[c["cell"]] or c["fire_in_traffic"] != 1):
        why.append("fault not applied (fires=%r fire_in_traffic=%r)" % (c["fires"], c["fire_in_traffic"]))
    if c["cell"] in KILL_CELLS and (c["killed"] != 1 or c["kill_in_traffic"] != 1):
        why.append("kill not applied (killed=%r kill_in_traffic=%r)" % (c["killed"], c["kill_in_traffic"]))
    if c["cell"] in ORDER_CELLS and (c["cyc_spread_ms"] is None or c["cyc_spread_ms"] > 250):
        why.append("order not applied (cyc_spread_ms=%r)" % c["cyc_spread_ms"])
    T.excl = why
    # settings check (only where every devComm was made)
    s = []
    if c["init_fail"] == 0:
        n = c["n"]
        for k in ("n_ts_on", "n_ua", "n_pr", "n_pc", "n_ow", "n_hd"):
            if c[k] != n:
                s.append("%s=%r" % (k, c[k]))
        g = (n - 1) * n * (n - 1)
        if not (c["gq_min"] == c["gq_max"] == g):
            s.append("gq=%r/%r want %d" % (c["gq_min"], c["gq_max"], g))
        if c["knob_stall"] != KNOB_EXPECT.get(c["cell"], ""):
            s.append("knob_stall=%r" % c["knob_stall"])
        if c["cell"] not in EXPECT_FIRES and c["fires"]:
            s.append("unexpected fires %r" % c["fires"])
        if c["flush"] != FLUSH_EXPECT.get(c["cell"], "ctx"):
            s.append("flush=%r" % c["flush"])
        if any((k or {}).get("flush") not in (None, c["flush"]) for k in T.kv):
            s.append("kv flush differs from meta")
        if c["mrge_err"] != 0:
            s.append("mrge_err")
        if c["build"] != "hd":
            s.append("build=%r" % c["build"])
    T.setting = s

P("## 2. Trial set, exclusions and the settings check")
P()
P("trial meta files found: %d (hold folders %s) [measured]"
  % (len(trials), ", ".join("%s %d" % (h, sum(1 for T in trials if T.hold == h))
                            for h in sorted(set(T.hold for T in trials)))))
P()
P("| cell | kind | planned (sect. 7) | trials run | excluded (reason, trial) | scored n | match |")
P("|---|---|--:|--:|---|--:|---|")
cells_run = sorted(set(T.c["cell"] for T in trials))
for cell in sorted(set(list(plan) + cells_run)):
    ts = [T for T in trials if T.c["cell"] == cell]
    ex = [T for T in ts if T.excl]
    inc = [T for T in ts if not T.excl]
    P("| `%s` | %s | %s | %d | %s | %d | %s |" % (
        cell, kinds.get(cell, "?"), plan.get(cell, "-"), len(ts),
        "; ".join("%s %s/%s" % (", ".join(T.excl), T.hold, T.c["trial"]) for T in ex) or "-",
        len(inc), "yes" if plan.get(cell) == len(inc) else "NO"))
tot_inc = sum(1 for T in trials if not T.excl)
P()
P("scored trials: %d (cell trials %d, latency runs %d); excluded %d [measured]" % (
    tot_inc, sum(1 for T in trials if not T.excl and "lat" not in T.c["cell"]),
    sum(1 for T in trials if not T.excl and "lat" in T.c["cell"]), sum(1 for T in trials if T.excl)))
fills = [T for T in trials if T.c["trial"] == "n11"]
P("fill trials (trial n11): %s [measured]" % (", ".join("%s/%s" % (T.hold, T.name) for T in fills) or "none"))
P("trial numbering: every cell's trial ids are %s [measured]" % (
    "contiguous from n1" if all(sorted(int(T.c["trial"][1:]) for T in trials if T.c["cell"] == cl) ==
                                 list(range(1, 1 + sum(1 for T in trials if T.c["cell"] == cl))) for cl in cells_run)
    else "NOT contiguous"))
P()
for T in trials:
    if T.excl:
        rcs = " ".join("r%drc=%s" % (r, T.meta.get("r%drc" % r)) for r in range(T.n))
        P("- excluded %s/%s: %s; %s wall_s=%s; rank 0 log: `%s`; other ranks' logs: `%s` [measured]" % (
            T.hold, T.name, ", ".join(T.excl), rcs, T.meta.get("wall_s"),
            (T.log[0].lines[0] if T.log[0].lines else ""),
            " | ".join(sorted(set(x for r in range(1, T.n) for x in T.log[r].lines if x.strip())))))
bad_set = [T for T in trials if not T.excl and T.setting]
P("- settings check (section 8) on every scored trial with all devComms: %s [measured]" % (
    "no deviation" if not bad_set else "; ".join("%s/%s: %s" % (T.hold, T.name, ", ".join(T.setting)) for T in bad_set)))
P("- init_fail among scored trials: %d; mrge_err: %d [measured]" % (
    sum(1 for T in trials if not T.excl and T.c["init_fail"]), sum(1 for T in trials if not T.excl and T.c["mrge_err"])))
P("- hook cells: fires as expected and inside the traffic in every scored trial: %s [measured]" % all(
    T.c["fires"] == EXPECT_FIRES[T.c["cell"]] and T.c["fire_in_traffic"] == 1
    for T in trials if not T.excl and T.c["cell"] in EXPECT_FIRES))
P("- kill cells: killed=1 and kill_in_traffic=1 in every scored trial: %s [measured]" % all(
    T.c["killed"] == 1 and T.c["kill_in_traffic"] == 1 for T in trials if not T.excl and T.c["cell"] in KILL_CELLS))
P("- cycle/chain cells: cyc_spread_ms %s ms (all <= 250: %s) [measured, range over the 10 trials of both cells]" % (
    rng([T.c["cyc_spread_ms"] for T in trials if not T.excl and T.c["cell"] in ORDER_CELLS]),
    all(T.c["cyc_spread_ms"] is not None and T.c["cyc_spread_ms"] <= 250
        for T in trials if not T.excl and T.c["cell"] in ORDER_CELLS)))
P()

# ---- predictions -----------------------------------------------------------------------------------------------------
P("## 3. Predictions")
P()
incl = [T for T in trials if not T.excl]
bycell = {}
for T in incl:
    bycell.setdefault("%s@%s" % (T.c["cell"], T.c["build"]), []).append(T)
all_cols = set()
for T in incl:
    all_cols |= set(T.c.keys())

preds = list(csv.DictReader(open(os.path.join(STUDY, "predictions.csv"))))
verdicts = []
P("| id | kind | cell | n | hits | verdict |")
P("|---|---|---|---|---|---|")
for pr in preds:
    pid, acc = pr["id"], pr["acceptance"].strip()
    cells = [x.strip() for x in pr["cells"].split(";")]
    per_cell = acc.startswith("per cell:")
    expr = acc[len("per cell:"):].strip() if per_cell else acc
    missing = sorted(nm for nm in names_in(re.sub(r"median\([^)]*\)", "", expr)) if nm not in all_cols)
    tr_expr = split_count(expr)
    med_cells = re.findall(r'__median\("[^"]+", "([^"]+)"\)', tr_expr)

    def planned(key):
        return plan.get(key.split("@")[0])

    def run(cellkey):
        hits = {}

        def __count(e):
            k = 0
            for T in bycell.get(cellkey, []):
                env = {nm: conv(T.c.get(nm)) for nm in names_in(e)}
                env.update(has=g_has, nonempty=g_nonempty, abs=g_abs)
                try:
                    if eval(e, {"__builtins__": {}}, env):
                        k += 1
                except TypeError:
                    pass
            hits[cellkey] = k
            return k

        def __median(col, key):
            v = [T.c.get(col) for T in bycell.get(key, [])]
            mv = med(v)
            hits["median(%s, %s)" % (col, key)] = mv
            return NA if mv is None else mv

        env = {"__count": __count, "__median": __median, "abs": g_abs}
        val = bool(eval(tr_expr, {"__builtins__": {}}, env))
        return val, hits

    need = cells if not med_cells else med_cells
    short = [k for k in need if len(bycell.get(k, [])) < (planned(k) or 0)]
    if missing:
        verdict, hitstr, nstr = "column missing: %s" % ",".join(missing), "-", "-"
    elif short:
        verdict, hitstr, nstr = "insufficient", "-", ", ".join("%d" % len(bycell.get(k, [])) for k in need)
    else:
        if per_cell:
            res = [run(k) for k in cells]
            ok = all(v for v, _ in res)
            hitstr = ", ".join("%s %d/%d" % (k.split("@")[0], h[k], len(bycell[k])) for k, (v, h) in zip(cells, res))
        else:
            v, h = run(cells[0])
            ok = v
            if med_cells:
                hitstr = "; ".join("%s = %.3f" % (kk, vv) if vv is not None else "%s = blank" % kk for kk, vv in h.items())
            else:
                hitstr = "%d/%d" % (h[cells[0]], len(bycell[cells[0]]))
        verdict = "holds" if ok else "fails"
        nstr = ", ".join(str(len(bycell.get(k, []))) for k in need)
    verdicts.append((pid, verdict))
    P("| %s | %s | %s | %s | %s | %s |" % (pid, pr["kind"], "; ".join(c.split("@")[0] for c in cells), nstr, hitstr,
                                           verdict))
P()
vc = {}
for _, v in verdicts:
    vc[v] = vc.get(v, 0) + 1
P("verdict counts: %s (of %d predictions) [measured]" % (", ".join("%s %d" % kv_ for kv_ in sorted(vc.items())),
                                                       len(verdicts)))
P()

# ---- missed trials of the failing / partly met predictions ----------------------------------------------------------
P("## 4. Trials that miss a rule (all predictions, trial ids)")
P()
anymiss = False
for pr in preds:
    acc = pr["acceptance"].strip()
    if "count(" not in acc:
        continue
    cells = [x.strip() for x in pr["cells"].split(";")]
    expr = acc[len("per cell:"):].strip() if acc.startswith("per cell:") else acc
    inner = re.search(r"count\((.*)\)\s*(>=|==)", expr).group(1)
    miss = []
    for ck in cells:
        for T in bycell.get(ck, []):
            env = {nm: conv(T.c.get(nm)) for nm in names_in(inner)}
            env.update(has=g_has, nonempty=g_nonempty, abs=g_abs)
            try:
                ok = bool(eval(inner, {"__builtins__": {}}, env))
            except TypeError:
                ok = False
            if not ok:
                cols = sorted(names_in(inner))
                miss.append("%s/%s(%s)" % (T.hold, T.name, ", ".join("%s=%r" % (cc, T.c.get(cc)) for cc in cols)))
    if miss:
        anymiss = True
        P("- %s misses %d: %s" % (pr["id"], len(miss), " || ".join(miss)))
if not anymiss:
    P("none: every scored trial meets the rule of every count-based prediction [measured]")
P()
# sanity: teardown lines complete
tl = []
for T in incl:
    nsurv = T.n - (1 if T.c.get("killed") == 1 else 0)
    want = nsurv * (T.n - 1)
    if T.c["n_ep_lines"] != want or T.c["n_qs_lines"] != want:
        tl.append("%s/%s ep %d qs %d want %d" % (T.hold, T.name, T.c["n_ep_lines"], T.c["n_qs_lines"], want))
P("teardown lines (gate epochs, qp states) present for every live rank and peer in every scored trial: %s [measured]"
  % ("yes" if not tl else tl))
P()
P("Definition checks (columns whose 3.1 wording leaves a choice):")
P()
dis = []
for T in incl:
    a = set("r%d" % r for r in range(T.n) if (T.kv[r] or {}).get("async_first") not in (None, "none"))
    b = set("r%d" % r for r in range(T.n) if (T.kv[r] or {}).get("final_async") not in (None, "no error"))
    if a != b:
        dis.append("%s/%s async_first %s final_async %s" % (T.hold, T.name, sorted(a), sorted(b)))
P("- async_ranks from `async_first != none` and from `final_async != no error` agree in every scored trial: %s [measured]"
  % ("yes" if not dis else dis))
both = {}
for T in incl:
    both.setdefault(T.c["cell"], []).append(T.c["n_refused"] + T.c["n_rerun"])
P("- n_refused counts the responder's scope-check 'refused' lines only. Counting the initiator's 'refused the scope ... "
  "rerunning' lines too would give `mr4_chain_stall` %s and `mr4_cyc_stall` %s [measured]"
  % (sorted(set(both.get("mr4_chain_stall", []))), sorted(set(both.get("mr4_cyc_stall", [])))))
lv = {}
for T in incl:
    for L in T.log:
        for x in L.socklost:
            lv.setdefault(T.c["cell"], {}).setdefault("%s/%s" % (x["cause"], x["liveness"]), 0)
            lv[T.c["cell"]]["%s/%s" % (x["cause"], x["liveness"])] += 1
P("- helper socket closes (cause/liveness) per cell: %s [measured]" % "; ".join(
    "`%s` %s" % (k, v) for k, v in sorted(lv.items())))
tot = {}
for T in incl:
    for k in ("n_watchdog", "n_esc", "n_fw_over", "n_copy_to", "n_cancel", "n_judged_dead", "n_decl", "n_refused"):
        if T.c[k]:
            tot.setdefault(T.c["cell"], {}).setdefault(k, 0)
            tot[T.c["cell"]][k] += T.c[k]
P("- non-zero sums of watchdog, escalation, firmware-bound, copy-bound, cancel, judged-dead, decline and refused lines "
  "per cell (scored trials): %s [measured]" % "; ".join("`%s` %s" % (k, v) for k, v in sorted(tot.items())))
P()

# ---- key numbers ------------------------------------------------------------------------------------------------------
P("## 5. Key numbers (re-derived from the raw files)")
P()


def cell_trials(cell):
    return [T for T in incl if T.c["cell"] == cell]


P("### 5.1 Initialisation (per rank; range over every rank of every scored trial of the group)")
P()
P("| group | trials | rank runs | init_ms (ncclCommInitRankConfig) | devcomm_ms (ncclDevCommCreate) | process start -> kernel launch, ms | earliest process start -> last kernel launch per trial, ms |")
P("|---|--:|--:|---|---|---|---|")
for nn in (2, 3, 4):
    ts = [T for T in incl if T.c["n"] == nn]
    ks = [k for T in ts for k in T.kv if k]
    span = []
    for T in ts:
        t0s = [T.to0(r, fnum((T.kv[r] or {}).get("t0_mono_ms"))) for r in range(T.n)]
        las = [T.to0(r, fnum((T.kv[r] or {}).get("launch_mono_ms"))) for r in range(T.n)]
        if all(x is not None for x in t0s + las):
            span.append(max(las) - min(t0s))
    P("| N=%d | %d | %d | %s | %s | %s | %s |" % (
        nn, len(ts), len(ks), rng([fnum(k.get("init_ms")) for k in ks]), rng([fnum(k.get("devcomm_ms")) for k in ks]),
        rng([fnum(k.get("launch_mono_ms")) - fnum(k.get("t0_mono_ms")) for k in ks
             if fnum(k.get("launch_mono_ms")) is not None and fnum(k.get("t0_mono_ms")) is not None]), rng(span)))
P()
ts4 = [T for T in incl if T.c["n"] == 4]
gq = sorted(set((T.c["gq_min"], T.c["gq_max"]) for T in incl))
P("- gated QPs (min, max) seen per N: %s [measured]" % ", ".join(
    "N=%d %s" % (nn, sorted(set((T.c["gq_min"], T.c["gq_max"]) for T in incl if T.c["n"] == nn))) for nn in (2, 3, 4)))
P()

P("### 5.2 Hook and kill timing")
P()
for cell in sorted(EXPECT_FIRES):
    ts = cell_trials(cell)
    d_launch, d_last = [], []
    for T in ts:
        las0 = [T.to0(r, fnum((T.kv[r] or {}).get("launch_mono_ms"))) for r in range(T.n)]
        for r in range(T.n):
            for fr in T.log[r].fires:
                d_launch.append(fr["t"] - fnum(T.kv[r]["launch_mono_ms"]))
                d_last.append(T.to0(r, fr["t"]) - max(las0))
    P("- `%s`: hook fire after the firing rank's kernel launch %s ms; after the last rank's launch %s ms (n=%d fires in %d trials) [measured]"
      % (cell, rng(d_launch), rng(d_last), len(d_launch), len(ts)))
for cell in sorted(KILL_CELLS):
    ts = cell_trials(cell)
    a, b = [], []
    for T in ts:
        las0 = [T.to0(r, fnum((T.kv[r] or {}).get("launch_mono_ms"))) for r in range(T.n)]
        a.append(T.c["kill_ms0"] - max(las0))
        b.append(min(x + T.c["iters"] * 15.0 for x in las0) - T.c["kill_ms0"])
    st3 = [fnum(T.kill["kill_mono_ms"]) - fnum(T.kv[3]["t0_mono_ms"]) for T in ts]
    P("- `%s`: kill after the last kernel launch %s ms; before the earliest planned traffic end %s ms; after rank 3's "
      "process start (its kv t0_mono_ms, same node clock) %s ms (n=%d) [measured]"
      % (cell, rng(a), rng(b), rng(st3), len(ts)))
P()
P("Trial wall time per cell (meta wall_s, the runner's clock, s): %s [measured]" % "; ".join(
    "`%s` %s" % (cell, rng([fnum(T.meta["wall_s"]) for T in cell_trials(cell)])) for cell in sorted(plan)))
P()

P("### 5.3 Recovery rounds (recovered lines; total_us and commit_us as the library logs them)")
P()
P("| cell | role | scope (qps) | lines | total ms | commit ms | replay ms | t_resumed - first round line of the trial, ms |")
P("|---|---|---|--:|---|---|---|---|")
for cell in ["mr4_f1_01", "mr4_f1_02", "mr4_f3_01", "mr4_f1_01_23", "mr4_f1_10_30", "mr4_f1all0", "mr4_chain_stall",
             "mr3_f1_01", "mr4_cyc_stall"]:
    ts = cell_trials(cell)
    groups = {}
    for T in ts:
        allr = [T.to0(r, x["t"]) for r in range(T.n) for x in T.log[r].rounds]
        for r in range(T.n):
            for x in T.log[r].recs:
                key = (x["role"], x.get("qps"))
                rel = T.to0(r, fnum(x.get("t_resumed"))) - min(allr) if allr else None
                groups.setdefault(key, []).append((fnum(x.get("total_us")), fnum(x.get("commit_us")),
                                                   fnum(x.get("replay_us")), rel))
    if not groups:
        P("| `%s` | - | - | 0 | - | - | - | - |" % cell)
    for (role, q), v in sorted(groups.items()):
        P("| `%s` | %s | %s | %d | %s | %s | %s | %s |" % (
            cell, role, q, len(v), rng([x[0] / 1000 for x in v]), rng([x[1] / 1000 for x in v]),
            rng([x[2] / 1000 for x in v]), rng([x[3] for x in v])))
P()
ts = cell_trials("mr4_f1all0")
st = []
for T in ts:
    fire = T.log[0].fires[0]["t"]
    rr = sorted(x["t"] for x in T.log[0].rounds)
    st.append([x - fire for x in rr])
P("- `mr4_f1all0`: rank 0's three round lines after its hook fire: first %s, second %s, third %s ms (n=%d) [measured]" % (
    rng([s[0] for s in st if len(s) > 0]), rng([s[1] for s in st if len(s) > 1]), rng([s[2] for s in st if len(s) > 2]),
    len(ts)))
for cell in ("mr4_f3_01",):
    ts = cell_trials(cell)
    P("- `%s`: f3_detect_ms %s; win_us (rank 0's held iteration) %s ms; w_02_in %s; w_03_in %s; win_edge_r0 %s (n=%d) [measured]" % (
        cell, rng([T.c["f3_detect_ms"] for T in ts]),
        rng([fnum(T.kv[0].get("win_us")) / 1000 for T in ts if T.kv[0].get("win_us")], 2),
        rng([T.c.get("w_02_in") for T in ts], 0), rng([T.c.get("w_03_in") for T in ts], 0),
        sorted(set(T.c["win_edge_r0"] for T in ts)), len(ts)))
ts = cell_trials("mr4_f1_10_30")
gaps = []
for T in ts:
    iv = sorted((fnum(x.get("t_req")), fnum(x.get("t_resumed"))) for x in T.log[0].recs if x["role"] == "responder")
    if len(iv) == 2:
        gaps.append(iv[1][0] - iv[0][1])
P("- `mr4_f1_10_30`: rank 0's second responder round starts %s ms after the first one resumed (n=%d; negative = overlap) [measured]"
  % (rng(gaps, 2), len(gaps)))
ts = cell_trials("mr4_f1all0")
gaps = []
for T in ts:
    iv = sorted((fnum(x.get("t_start")), fnum(x.get("t_resumed"))) for x in T.log[0].recs if x["role"] == "initiator")
    gaps += [iv[i + 1][0] - iv[i][1] for i in range(len(iv) - 1)]
P("- `mr4_f1all0`: gap between rank 0's consecutive initiator rounds %s ms (n=%d gaps) [measured]" % (rng(gaps, 3), len(gaps)))
for cell in ("mr4_chain_stall", "mr4_cyc_stall"):
    ts = cell_trials(cell)
    P("- `%s`: rec_first_after_round_ms %s; rec_last_after_round_ms %s; rounds %s; n_refused %s; reruns %s (n=%d) [measured]" % (
        cell, rng([T.c["rec_first_after_round_ms"] for T in ts]), rng([T.c["rec_last_after_round_ms"] for T in ts]),
        sorted(set(T.c["rounds"] for T in ts)), sorted(set(T.c["n_refused"] for T in ts)),
        sorted(set(T.c["n_rerun"] for T in ts)), len(ts)))
P()

P("### 5.4 Kill cells: death judgement and declines (rank 0's clock, ms after the kill)")
P()
P("| cell | n | rank | socket FIN seen | judged dead | first decline (decl_after_kill_ms) | decline reasons |")
P("|---|--:|---|---|---|---|---|")
for cell in sorted(KILL_CELLS):
    ts = cell_trials(cell)
    for r in range(3):
        fin, jd, de, why = [], [], [], set()
        for T in ts:
            k0 = T.c["kill_ms0"]
            fin += [T.to0(r, x["t"]) - k0 for x in T.log[r].socklost if x["p"] == 3]
            jd += [T.to0(r, x["t"]) - k0 for x in T.log[r].jd if x["p"] == 3]
            de.append(T.c["decl_after_kill_ms_r%d" % r])
            why |= set("%d-%d=%s" % (x["r"], x["p"], x["why"]) for x in T.log[r].decls)
        P("| `%s` | %d | %d | %s | %s | %s | %s |" % (cell, len(ts), r, rng(fin, 2), rng(jd, 2), rng(de, 2),
                                                    "; ".join(sorted(why))))
for cell in sorted(KILL_CELLS):
    ts = cell_trials(cell)
    P("- `%s`: n_surv_edges %s, surv_edges_ok %s, surv_tx_failed %s, surv_rx_failed %s, async_ranks %s, n_ep_nz %s, ep_peers %s, n_notrts %s, notrts_peers %s, n_judged_dead %s [measured]" % (
        cell, *[sorted(set(T.c[k] for T in ts)) for k in ("n_surv_edges", "surv_edges_ok", "surv_tx_failed",
                                                          "surv_rx_failed", "async_ranks", "n_ep_nz", "ep_peers",
                                                          "n_notrts", "notrts_peers", "n_judged_dead")]))
    # survivor edges: where the senders stopped (done) and their result
    done = {}
    for T in ts:
        for (a, b) in T.edge_ok:
            if 3 in (a, b):
                continue
            done.setdefault("tx", []).append(fnum(T.kv[a].get("tx_%d%d_done" % (a, b))))
            done.setdefault("rx", []).append(fnum(T.kv[b].get("rx_%d%d_done" % (a, b))))
    rcs = sorted(set(T.kv[a].get("tx_%d%d_rc" % (a, b)) for T in ts for (a, b) in T.edge_ok if 3 not in (a, b)))
    rxs = sorted(set(T.kv[b].get("rx_%d%d_rc" % (a, b)) for T in ts for (a, b) in T.edge_ok if 3 not in (a, b)))
    P("  - survivor edges: sender iterations done %s, receiver iterations done %s; sender results %s; receiver results %s [measured]"
      % (rng(done["tx"], 0), rng(done["rx"], 0), rcs, rxs))
P()

P("### 5.5 Cycle: the ACK bound")
P()
ts = cell_trials("mr4_cyc_stall")
rows = []
for T in ts:
    fr = {}
    for r in range(T.n):
        if T.log[r].rounds:
            fr[r] = min(x["t"] for x in T.log[r].rounds)
    hs = ["r%d->%d %.1f" % (r, x["p"], x["t"] - fr[r]) for r in range(T.n) for x in T.log[r].decls
          if x["why"] == "handshake timeout" and r in fr]
    rows.append(hs)
    P("- %s/%s: hs_first_after_round_ms %.1f; every 'handshake timeout' decline after its rank's first round line: %s; n_hs %d; transparent_ok %d; n_watchdog %d; n_rec_i %d; declines %s [measured]" % (
        T.hold, T.name, T.c["hs_first_after_round_ms"], ", ".join(hs), T.c["n_hs"], T.c["transparent_ok"],
        T.c["n_watchdog"], T.c["n_rec_i"], T.c["decl_reasons"]))
    ab = sorted((T.to0(r, x["t"]), r, x["p"]) for r in range(T.n) for x in T.log[r].decls
                if x["why"] == "handshake timeout")
    rf_ = ["r%d refused r%d %.1f" % (r, x["frm"], x["t"] - fr[r]) for r in range(T.n) for x in T.log[r].refused
           if r in fr]
    P("  - handshake timeouts in rank 0's clock relative to the first: %s (spread %.1f ms); scope refusals after the "
      "refusing rank's first round line: %s; rank 3 outcome %s [measured]" % (
          ", ".join("r%d->%d +%.1f" % (r, p, t - ab[0][0]) for t, r, p in ab), ab[-1][0] - ab[0][0], ", ".join(rf_),
          (T.kv[3] or {}).get("outcome")))
P("- range of hs_first_after_round_ms over the 5 cycle trials: %s ms [measured]" % rng(
    [T.c["hs_first_after_round_ms"] for T in ts]))
P()

P("### 5.6 Latency (4 KiB put + signal + flush, back to back, 3000 iterations; sender kv)")
P()
P("| cell | runs | edge | p50 per run, us (range) | median of the runs' p50 | max per run, us (range) |")
P("|---|--:|---|---|---|---|")
for cell in ("mr2_lat", "mr4_lat_solo", "mr4_lat"):
    ts = cell_trials(cell)
    E = edges_of(ts[0].n, ts[0].meta["edges"])
    for (a, b) in E:
        p50 = [fnum(T.kv[a].get("tx_%d%d_p50_us" % (a, b))) for T in ts]
        mx = [fnum(T.kv[a].get("tx_%d%d_max_us" % (a, b))) for T in ts]
        P("| `%s` | %d | %d>%d (%s) | %s | %.2f | %s |" % (cell, len(ts), a, b,
                                                       "between nodes" if node_of(a) != node_of(b) else "in " + node_of(a),
                                                       rng(p50, 2), med(p50), rng(mx, 2)))
for cell in ("mr2_lat", "mr4_lat_solo", "mr4_lat"):
    ts = cell_trials(cell)
    P("- `%s`: p50_01 per run %s, median %.3f; p50_inter_med per run %s, median %.4f; max_all per run %s; runs with max_all >= 200 us: %d of %d [measured]" % (
        cell, [T.c["p50_01"] for T in ts], med([T.c["p50_01"] for T in ts]),
        ["%.4f" % T.c["p50_inter_med"] for T in ts], med([T.c["p50_inter_med"] for T in ts]),
        [T.c["max_all"] for T in ts], sum(1 for T in ts if T.c["max_all"] >= 200), len(ts)))
P()

# ---- hold logs ----------------------------------------------------------------------------------------------------
P("## 6. Hold logs, snapshots and safety files against the raw files")
P()
hold_lines = {}
for hf in sorted(glob.glob(os.path.join(RES, "hold_*.out"))):
    for x in open(hf, errors="replace"):
        mm = re.match(r"^\[(\w+)/n(\d+)/(\w+)/(\w+)#(n\d+)\] (r0rc=.*?) left=(\d+) wall=([\d.]+)s :: (.*)$", x.rstrip("\n"))
        if mm:
            hold_lines[(mm.group(4), mm.group(5), os.path.basename(hf))] = mm
problems = []
for T in trials:
    key = [k for k in hold_lines if k[0] == T.c["cell"] and k[1] == T.c["trial"]]
    if len(key) != 1:
        problems.append("%s: %d hold-log result lines" % (T.name, len(key)))
        continue
    mm = hold_lines[key[0]]
    rcs = " ".join("r%drc=%s" % (r, T.meta.get("r%drc" % r)) for r in range(T.n))
    if mm.group(6).strip() != rcs:
        problems.append("%s rc %r vs meta %r" % (T.name, mm.group(6), rcs))
    if mm.group(7) != T.meta.get("left"):
        problems.append("%s left" % T.name)
    if mm.group(8) != T.meta.get("wall_s"):
        problems.append("%s wall" % T.name)
    dones = [d for d in mm.group(9).split("|") if d]
    exp = []
    for r in range(T.n):
        if T.log[r].done:
            exp.append("DONE " + T.log[r].done)
    if sorted(dones) != sorted(exp):
        problems.append("%s DONE lines differ" % T.name)
    for r in range(T.n):
        k = T.kv[r] or {}
        if T.log[r].done and ("outcome=%s " % k.get("outcome")) not in T.log[r].done + " ":
            problems.append("%s r%d DONE outcome vs kv outcome" % (T.name, r))
P("- hold-log result line per trial: %d of %d trials have exactly one; its rc, left, wall and DONE lines equal the meta "
  "file and the rank logs, and each DONE outcome equals the rank's kv outcome; problems: %s [measured]"
  % (len(trials) - len([p for p in problems if "hold-log result lines" in p]), len(trials), problems or "none"))
problems = []
order = []
for hf in ["hold_H1.out", "hold_H2.out", "hold_H3.out", "hold_H4.out", "hold_H5.out", "hold_H6.out", "hold_H7.out",
           "hold_fill.out"]:
    seq = []
    for x in open(os.path.join(RES, hf), errors="replace"):
        mm = re.match(r"^\[\w+/n\d+/\w+/(\w+)#(n\d+)\] gid ", x)
        if mm:
            seq.append(mm.group(1))
    cnt = {}
    for s_ in seq:
        cnt[s_] = cnt.get(s_, 0) + 1
    order.append("%s: %s" % (hf[5:-4], ", ".join("%s %d" % kv_ for kv_ in cnt.items())))
P("- trials started per hold (from the hold logs' gid lines): %s [measured]" % "; ".join(order))
kills = []
for hf in sorted(glob.glob(os.path.join(RES, "hold_*.out"))):
    for x in open(hf, errors="replace"):
        mm = re.match(r"^\[\w+/n\d+/\w+/(\w+)#(n\d+)\] SIGKILL rank (\d+) after (\d+) ms: (.*)$", x.rstrip("\n"))
        if mm:
            kills.append(mm)
kp = []
for mm in kills:
    T = [T for T in trials if T.c["cell"] == mm.group(1) and T.c["trial"] == mm.group(2)][0]
    if parse_kv_line(mm.group(5)) != T.kill:
        kp.append(T.name)
    # the killed pid is rank 3's gin_mr: rank 3's log lines carry that pid
    pid = T.kill.get("pid")
    if not any((":%s:" % pid) in x for x in T.log[3].lines):
        kp.append(T.name + " pid not in rank 3 log")
P("- kill lines in the hold logs: %d; equal to <stem>_kill.out and the killed PID appears in rank 3's log lines: %s [measured]"
  % (len(kills), "all" if not kp else kp))
P("- left (gin_mr still present after the trial) over all %d trials: %s; LEFT_STREAK file: %r; STOP files: %s [measured]" % (
    len(trials), sorted(set(T.meta.get("left") for T in trials)), open(os.path.join(RES, "LEFT_STREAK")).read().strip(),
    sorted(os.path.basename(x) for x in glob.glob(os.path.join(RES, "STOP_*")) + glob.glob(os.path.join(RES, "stale.txt")))
    or "none"))
CMDERR = re.compile(r"(cmd|command)", re.I)
CMDERR2 = re.compile(r"(failed|timeout|leak)", re.I)
snaps = []
for sf in sorted(glob.glob(os.path.join(RES, "snap_*.txt"))):
    tag = os.path.basename(sf)[len("snap_"):-len(".txt")]
    s = open(sf).read()
    rec = {}
    for node in ("rain", "sunny"):
        lines = open(os.path.join(RES, "mlx5_%s_%s.txt" % (tag, node)), errors="replace").read().splitlines()
        rec[node] = (len(lines), sum(1 for x in lines if "mlx5" in x.lower() and CMDERR.search(x) and CMDERR2.search(x)))
        claim_l = int(re.search(r"%s mlx5 dmesg lines: (\d+)" % node, s).group(1))
        claim_c = int(re.search(r"%s mlx5 cmd_err lines: (\d+)" % node, s).group(1))
        if (claim_l, claim_c) != rec[node]:
            problems.append("snapshot %s %s claims %s, files give %s" % (tag, node, (claim_l, claim_c), rec[node]))
    fw = open(os.path.join(RES, "fwcmd_%s.txt" % tag)).read()
    fsum = sum(int(v) for v in re.findall(r"(?:^|\s)(?:failed|failed_mbox_status)=(\d+)", fw))
    claim_f = int(re.search(r"rain fwcmd failed sum: (\d+)", s).group(1))
    if fsum != claim_f:
        problems.append("snapshot %s fwcmd sum claims %d, file gives %d" % (tag, claim_f, fsum))
    modes = re.findall(r"gpu mode: (.*)", s)
    snaps.append((tag, rec["rain"], rec["sunny"], fsum, modes))
P("- snapshots: %d files; mlx5 line counts and command-error counts (rain, sunny) and rain firmware failed sum recomputed from the mlx5_*/fwcmd_* files: %s; distinct values %s; compute modes %s [measured]" % (
    len(snaps), "all equal to the snapshot text" if not any("snapshot" in p for p in problems) else
    [p for p in problems if "snapshot" in p], sorted(set((a, b, c) for _, a, b, c, _ in snaps)),
    sorted(set(x for *_, mo in snaps for x in mo))))
newl = {os.path.basename(x): os.path.getsize(x) for x in glob.glob(os.path.join(RES, "mlx5_new_*.txt"))}
P("- mlx5_new_*.txt sizes: %s [measured]" % newl)
for hold in ["H1", "H2", "H3", "H4", "H5", "H6", "H7", "fill"]:
    for node in ("rain", "sunny"):
        a = set(open(os.path.join(RES, "mlx5_before-%s_%s.txt" % (hold, node)), errors="replace").read().splitlines())
        b = open(os.path.join(RES, "mlx5_after-%s_%s.txt" % (hold, node)), errors="replace").read().splitlines()
        new = [x for x in b if x not in a]
        if new:
            problems.append("new mlx5 lines %s %s: %d" % (hold, node, len(new)))
P("- new mlx5 kernel lines per hold, recomputed as after minus before: %s [measured]" % (
    [p for p in problems if p.startswith("new mlx5")] or "0 in every hold, both nodes"))
times = []
hsum = fsum_ = 0
for hf in sorted(glob.glob(os.path.join(RES, "hold_*.out"))):
    s = open(hf).read()
    a = re.search(r"== before-\S+ (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", s)
    b = re.search(r"== after-\S+ (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", s)
    lk = re.search(r"(\d\d:\d\d:\d\d) \[gmr-\S+\] lock acquired", s)
    times.append("%s %s–%s (lock %s)" % (os.path.basename(hf)[5:-4], a.group(1)[11:], b.group(1)[11:], lk.group(1)))
    sec = lambda s_: int(s_[11:13]) * 3600 + int(s_[14:16]) * 60 + int(s_[17:19])
    dur = sec(b.group(1)) - sec(a.group(1))
    times[-1] += " %d s" % dur
    if "fill" not in hf:
        hsum += dur
    fsum_ += dur
P("- hold windows (before snapshot – after snapshot): %s [measured]" % "; ".join(times))
P("- snapshot-to-snapshot time: H1–H7 %d s (%d min %d s); with the fill %d s (%d min %d s) [measured]" % (
    hsum, hsum // 60, hsum % 60, fsum_, fsum_ // 60, fsum_ % 60))
P()

# ---- pilot statements ------------------------------------------------------------------------------------------------
P("## 7. Statements about the pilot (never scored; checked only)")
P()
pm = sorted(glob.glob(os.path.join(PILOT, "p0", "*_meta.txt")))
pts = []
for mp in pm:
    T = load_trial(mp)
    compute(T)
    pts.append(T)
P("- pilot trials: %d, cells %d, build(s) %s [measured]" % (len(pts), len(set(T.c["cell"] for T in pts)),
                                                          sorted(set(T.c["build"] for T in pts))))
d_last, kl, cs, hs1, rf, pk = [], [], [], [], [], []
for T in pts:
    las0 = [T.to0(r, fnum((T.kv[r] or {}).get("launch_mono_ms"))) for r in range(T.n)]
    if any(x is None for x in las0):
        continue
    for r in range(T.n):
        for fr in T.log[r].fires:
            d_last.append(T.to0(r, fr["t"]) - max(las0))
    if T.c["kill_ms0"] is not None:
        kl.append(T.c["kill_ms0"] - max(las0))
    if T.c["cell"] == "mr4_cyc_stall":
        cs.append(T.c["cyc_spread_ms"])
        hs1.append(T.c["hs_first_after_round_ms"])
        rf.append(T.c["rec_first_after_round_ms"])
    if T.c["n"] == 4:
        pk += [fnum(k.get("launch_mono_ms")) - fnum(k.get("t0_mono_ms")) for k in T.kv if k and k.get("launch_mono_ms")]
nomrge = [T for T in pts if T.c["cell"] == "mr4_nomrge"]
P("- hook fire after the last rank's kernel launch: %s ms (%d fires) — EXPERIMENT.md 3.4 says 5 959–5 975 ms, 9 fires [measured]"
  % (rng(d_last), len(d_last)))
P("- kill after the last kernel launch: %s ms (%d) — 3.4 says 7 983–8 026 ms (2) [measured]" % (rng(kl), len(kl)))
P("- cycle trial: cyc_spread_ms %s, hs_first_after_round_ms %s, rec_first_after_round_ms %s — 3.4/3.6 say 17.4, 24 506, 25 118 ms [measured]"
  % (cs, hs1, rf))
P("- four-rank process start -> kernel launch: %s ms over %d rank runs — 3.4 says 919–1 278 ms (52) [measured]" % (rng(pk), len(pk)))
P("- negative control `mr4_nomrge`: mrge_err %s, n_devcomm %s [measured]" % ([T.c["mrge_err"] for T in nomrge],
                                                                           [T.c["n_devcomm"] for T in nomrge]))
P("- distinct pilot cells: %s [measured]" % ", ".join(sorted(set(T.c["cell"] for T in pts))))


def pilot_rounds(cells, qps):
    it, rs, cm, rp, it_cm, rs_cm = [], [], [], [], [], []
    for T in pts:
        if T.c["cell"] not in cells:
            continue
        for r in range(T.n):
            for x in T.log[r].recs:
                if x["role"] != "initiator" or x.get("qps") != qps:
                    continue
                ts_ = T.to0(r, fnum(x["t_start"]))
                it.append(T.to0(r, fnum(x["t_resumed"])) - ts_)
                cm.append(fnum(x["commit_us"]) / 1000)
                rp.append(fnum(x["replay_us"]) / 1000)
                for y in T.log[x["p"]].recs:
                    if y["role"] == "responder" and y["p"] == r and y.get("round") == x.get("round"):
                        rs.append(T.to0(x["p"], fnum(y["t_resumed"])) - ts_)
                        cm.append(fnum(y["commit_us"]) / 1000)
                        rp.append(fnum(y["replay_us"]) / 1000)
    return it, rs, cm, rp


it, rs, cm, rp = pilot_rounds({"mr4_f1_01", "mr4_f1_02", "mr4_f3_01", "mr4_f1_10_30"}, "1")
P("- pilot pair rounds (f1_01, f1_02, f3_01, f1_10_30): initiator resumed %s ms and responder %s ms after the "
  "initiator's t_start (%d rounds); commit %s ms, replay %s ms over both roles (%d lines) — 3.6/Z1/R1 say 86–92 and "
  "115–119 ms (4 rounds), commit 18.7–22.5, replay 26.8–38.9 ms (10 lines) [measured]"
  % (rng(it), rng(rs), len(it), rng(cm), rng(rp), len(cm)))
P("  - initiator resume per round, sorted: %s; responder resume per round, sorted: %s [measured]" % (
    ", ".join("%.1f" % x for x in sorted(it)), ", ".join("%.1f" % x for x in sorted(rs))))
it, rs, cm, rp = pilot_rounds({"mr4_f1all0"}, "12")
P("- pilot 12-context rounds of `mr4_f1all0`: initiator %s ms, responder %s ms after the initiator's t_start (%d rounds); "
  "commit %s ms, replay %s ms (%d lines) — Z1/R1/F2 say 1012–1025, 1387–1399 ms (3 rounds), commit 260.2–264.9, "
  "replay 373.4–376.2 ms (6 lines) [measured]" % (rng(it), rng(rs), len(it), rng(cm), rng(rp), len(cm)))
for T in pts:
    if T.c["cell"] == "mr4_f1all0":
        mb = T.log[0].q4[0]["t"]
        P("- pilot `mr4_f1all0`: rank 0's round lines after its first mailbox record: %s ms — F2 says the third started "
          "2022 ms after it [measured]" % ", ".join("%.1f" % (x["t"] - mb) for x in T.log[0].rounds))
    if T.c["cell"] == "mr4_f3_01":
        P("- pilot `mr4_f3_01`: f3_detect_ms %.1f, win_us %s, w_02_in %s, w_03_in %s — 3.6 says 3 694 ms, 3.78 s, 247 and "
          "246 [measured]" % (T.c["f3_detect_ms"], T.kv[0].get("win_us"), T.c.get("w_02_in"), T.c.get("w_03_in")))
    if T.c["cell"] == "mr4_f1_10_30":
        P("- pilot `mr4_f1_10_30`: initiator totals %s ms — 3.6 says the second initiator ended at 205 ms [measured]"
          % sorted(round(fnum(x["total_us"]) / 1000, 1) for L in T.log for x in L.recs if x["role"] == "initiator"))
    if T.c["cell"] in KILL_CELLS:
        P("- pilot `%s`: first decline after the kill, ranks 0-2: %s ms — 3.6 says 3 632–3 810 ms [measured]" % (
            T.c["cell"], ", ".join("%.1f" % T.c["decl_after_kill_ms_r%d" % r] for r in range(3)
                                   if T.c.get("decl_after_kill_ms_r%d" % r) is not None)))
    if T.c["cell"] in ("mr2_lat", "mr4_lat_solo", "mr4_lat"):
        P("- pilot `%s`: p50_01 %s, p50_inter_med %s, max_all %s — 3.6 says p50 11.07, 11.04; four-rank inter median "
          "12.05, max 2 335; two ranks max 20.48 [measured]" % (T.c["cell"], T.c["p50_01"], T.c["p50_inter_med"],
                                                                 T.c["max_all"]))
ff = [T.c["max_all"] for T in pts if T.c["cell"] in ("mr4_none", "mr4_none_peer")]
P("- pilot four-rank fault-free trials with the 15 ms gap: max_all %s us (%d trials) — 1 says 18.4 us or less (3 trials) "
  "[measured]" % (ff, len(ff)))
P("- pilot wall per cell: %s — 3.6 lists 18.0, 21.5, 21.0, 20.1–23.6, 33.6, 1.8–2.5 s [measured]" % "; ".join(
    "%s %s" % (T.c["cell"], T.meta["wall_s"]) for T in pts))
P()

if SHOW_TRIALS:
    P("## 8. Per-trial columns (compact)")
    P()
    keys = ["transparent_ok", "rounds", "rec_i", "rec_r", "decl", "n_refused", "ep_nz", "notrts", "q4_first",
            "f3_detect_ms", "async_ranks", "cyc_spread_ms", "hs_first_after_round_ms", "rec_last_after_round_ms"]
    for T in trials:
        P("- %s/%s excl=%s %s" % (T.hold, T.name, T.excl or "-",
                                  " ".join("%s=%s" % (k, T.c.get(k)) for k in keys if T.c.get(k) not in (None, ""))))

print("\n".join(out))
