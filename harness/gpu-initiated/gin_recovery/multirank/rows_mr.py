#!/usr/bin/env python3
"""gin-multirank: one CSV row per trial, recomputed from the raw per-trial files of run_mr.sh
(<stem>_meta.txt, <stem>_r<r>.kv, <stem>_r<r>.log for every rank r, <stem>_kill.out). score.py imports rows_of().

usage: rows_mr.py <logdir> [<logdir> ...] --out trials.csv

Columns (definitions and log formats fixed in EXPERIMENT.md 3.1). Lists are sorted and joined with ";". "R-P" names a
rank R and a peer P (never a bare number, so the 3.2 grammar keeps it a string); "a>b" names the directed edge from rank
a to rank b. Times are CLOCK_MONOTONIC ms; a time "on rank 0's clock" is the rank's own time minus clock_offset_ms_r<r>
of rank 0's kv.
  cell lib mrkey build n mode flush iters trial stem left rc_all bind_fail
  n_devcomm n_launch init_fail mrge_err        ranks with devcomm_mono_ms / launch_mono_ms in their kv; init_fail = 1 if
                                               n_devcomm < n; mrge_err = 1 if a log holds "Multiple Ranks are using the
                                               same GPU"
  n_ts_on gq_min gq_max n_ts_off n_ua n_ow n_pr n_pc   "transparent recovery ON rank=<r> gated_qps=<q>" lines (count, min
                                               and max q), "transparent recovery OFF" lines, "user devComm abort flag set",
                                               "helper liveness oneway=1", "pair reset=1", "pair check=1" lines
  edges n_edges n_edges_ok edges_bad transparent_ok
                                               edge a>b is ok iff the sender's tx_ab_done == iters, tx_ab_rc == "no error",
                                               the receiver's rx_ab_done == iters, rx_ab_rc == "no error", rx_ab_devbad == 0,
                                               rx_ab_hostbad == 0, rx_ab_sigexact == 1; transparent_ok = 1 iff every edge is
                                               ok, every rank's outcome is ok and no rank saw an async error
  outcomes n_outcome_ok async_ranks n_async    per-rank kv outcome; ranks whose async_first is not "none", as "r<r>,..."
  fires n_fires fire_in_traffic                "GIN/FAULT: GDAKI fault fired" lines as "r:<context>" ("r:all" without a
                                               context); fire_in_traffic = 1 iff every fire lies after its rank's
                                               launch_mono_ms and before launch_mono_ms + iters * gap_us / 1000
  rounds n_rounds                              "GIN/TS: rank R: round K peer P scope=S qps=Q reason=X" as "R>P:Q:X"
  rec_i n_rec_i rec_r n_rec_r                  "GIN/TS: recovered rank=R peer=P role=initiator|responder" as "R-P"
  decl n_decl decl_reasons decl_hs             "GIN/TS: declined rank=R peer=P reason=..." as "R-P"; "R-P=<reason>";
                                               the pairs whose reason is "handshake timeout"
  n_watchdog n_refused n_conflict n_tie        "GIN/TS: watchdog rank=" lines; scope checks "refused"; "scope conflict:";
                                               "the lower rank keeps the initiator role"
  ep_nz n_ep_nz ep_peers                       teardown "gate epochs to rank P: [e_0,...]": "R-P-C=e" for e != 0 (C = GIN
                                               context); the peers P that appear, as "p<P>,..."
  notrts n_notrts notrts_peers                 teardown "qp states to rank P: [s_0,...]": "R-P-C=s" for s != 3 (3 = RTS);
                                               the peers as for ep_peers
  n_teardown                                   "GIN/TS: communicator teardown rank=" lines
  q4_first                                     each rank's first "device-classified error CQE" class as "r:CLASS"
  killed kill_rank kill_ms0 kill_in_traffic    kill.out; kill_ms0 on rank 0's clock; kill_in_traffic = 1 iff kill_ms0 is
                                               after every rank's launch (rank 0's clock) and at least 5000 ms before the
                                               earliest planned traffic end (launch + iters * gap)
  decl_ms_r<r> decl_after_kill_ms_r<r>         rank r's first decline on rank 0's clock; minus kill_ms0
  round_ms_r<r> cyc_spread_ms decl_after_round_ms_r<r>
                                               rank r's first round line on rank 0's clock; max - min of round_ms_r over the
                                               ranks that have one; rank r's first "handshake timeout" decline minus its
                                               first round line (own clock)
  n_hs hs_first_after_round_ms                 "handshake timeout" declines; for the earliest of them (rank 0's clock), its
                                               delay after its own rank's first round line
  init_total_ms_min init_total_ms_max          total_us / 1000 of the recovered lines with role=initiator
  f3_detect_ms                                 rank 0's first classifier record minus the first fire of rank 1, rank 0's clock
  resp_overlap_r0 init_overlap_r0              1 if two of rank 0's responder rounds [t_req, t_resumed] (initiator rounds
                                               [t_start, t_resumed]) overlap; 0 if not; empty with fewer than two
  win_edge_r<r> win_us_r<r> w_<ab>_in w_<ab>_ovlmax_us   copied from the sender's kv (held window, gin_mr.cu)
  p50_<ab> max_<ab> p50_01 p50_inter_med p50_intra_med max_all
                                               the sender's tx_ab_p50_us / tx_ab_max_us; the median of p50 over the edges
                                               between nodes (a, b of different parity) and within a node; the largest max
  n_surv_edges surv_edges_ok surv_tx_failed    kill trials: edges between ranks other than kill_rank; how many are ok; how
                                               many of their senders' tx rc are not "no error"
  knob_stall                                   "GIN/TS: TEST knobs rank=<r> stall_ms=<ms> stage=1" as "r:ms"
  surv_rx_failed                               kill trials: edges between survivors whose receiver's rx rc is not "no error"
  n_hd                                         gin-harden start lines "GIN/TS: harden=1 rank=" (build marker of hd)
  n_judged_dead                                gin-harden "GIN/TS: rank R: rank P judged dead" lines
  n_esc, n_fw_over, n_copy_to, n_cancel        gin-harden WARN lines: "GIN/TS: escalated rank=" (round cap), a firmware
                                               phase "more than NCCL_GIN_TS_FW_MS", a device-state copy "not complete after
                                               ... (NCCL_GIN_TS_COPY_MS)", a round "cancelled ... before the commit"
"""
import argparse, csv, glob, os, re, statistics, sys

RE_TS_ON = re.compile(r"GIN/TS: transparent recovery ON rank=(\d+) gated_qps=(\d+)")
RE_FIRE = re.compile(r"GIN/FAULT: GDAKI fault fired.*?moved \d+/\d+ GIN QP\(s\) to ERR (?:context=(\d+) )?fire_mono_ms=([\d.]+)")
RE_ROUND = re.compile(r"GIN/TS: rank (\d+): round \d+ peer (\d+) scope=\S+ qps=(\d+) reason=(\w+) mono_ms=([\d.]+)")
RE_KVL = re.compile(r"([\w/]+)=(\[[^\]]*\]|\S+)")
RE_DECL = re.compile(r'GIN/TS: declined rank=(\d+) peer=(\d+) reason="([^"]*)" class=(-?\d+) mono_ms=([\d.]+)')
RE_CHECK = re.compile(r"GIN/TS: rank \d+: REQ round \d+ from rank \d+ scope=\S+ checked=\d+ not_rts=\d+ check_us=[\d.]+ (accepted|refused)")
RE_EP = re.compile(r"GIN/TS: rank (\d+) gate epochs to rank (\d+): \[([^\]]*)\]")
RE_QPST = re.compile(r"GIN/TS: rank (\d+) qp states to rank (\d+): \[([^\]]*)\]")
RE_Q4 = re.compile(r"device-classified error CQE rank=\d+ .*?class=(\w+) .*?mono_ms=([\d.]+)")
RE_KNOBS = re.compile(r"GIN/TS: TEST knobs rank=(\d+) stall_ms=(\d+) stage=(\d+)")


def kvfile(path):  # as ../scripts/ts2/rows.py: a value may hold blanks up to the next key
    d = {}
    if os.path.exists(path):
        for line in open(path, errors="replace"):
            for m in re.finditer(r"(\w+)=(.*?)(?= \w+=|$)", line.rstrip("\n")):
                d[m.group(1)] = m.group(2).strip().strip('"')
    return d


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def scan(path):
    o = {"ts_on": [], "ts_off": 0, "ua": 0, "ow": 0, "pr": 0, "pc": 0, "fires": [], "rounds": [], "rec": [], "decl": [],
         "acc": 0, "ref": 0, "conflict": 0, "tie": 0, "watchdog": 0, "ep": [], "qpst": [], "teardown": 0, "q4": None,
         "mrge": 0, "bind": 0, "knob_stall": None, "hd": 0, "dead_j": 0, "esc": 0, "fw_over": 0, "copy_to": 0,
         "cancel": 0}
    if not os.path.exists(path):
        return o
    for line in open(path, errors="replace"):
        m = RE_TS_ON.search(line)
        if m:
            o["ts_on"].append(int(m.group(2)))
        if "GIN/TS: transparent recovery OFF" in line:
            o["ts_off"] += 1
        if "GIN/TS: user devComm abort flag set" in line:
            o["ua"] += 1
        if "GIN/TS: helper liveness oneway=1" in line:
            o["ow"] += 1
        if "GIN/TS: harden=1 rank=" in line:  # gin-harden
            o["hd"] += 1
        if re.search(r"GIN/TS: rank \d+: rank \d+ judged dead", line):
            o["dead_j"] += 1
        if "GIN/TS: escalated rank=" in line:
            o["esc"] += 1
        if "more than NCCL_GIN_TS_FW_MS" in line:
            o["fw_over"] += 1
        if "(NCCL_GIN_TS_COPY_MS)" in line:
            o["copy_to"] += 1
        if re.search(r"GIN/TS: rank \d+: round \d+ (with|from) rank \d+ cancelled", line):
            o["cancel"] += 1
        if re.search(r"GIN/TS: pair reset=1 rank=", line):
            o["pr"] += 1
        if re.search(r"GIN/TS: pair check=1 rank=", line):
            o["pc"] += 1
        m = RE_FIRE.search(line)
        if m:
            o["fires"].append((m.group(1) if m.group(1) is not None else "all", float(m.group(2))))
        m = RE_ROUND.search(line)
        if m:
            o["rounds"].append((int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4), float(m.group(5))))
        if "GIN/TS: recovered" in line:
            o["rec"].append(dict(RE_KVL.findall(line)))
        m = RE_DECL.search(line)
        if m:
            o["decl"].append((int(m.group(1)), int(m.group(2)), m.group(3), float(m.group(5))))
        m = RE_CHECK.search(line)
        if m:
            o["acc" if m.group(1) == "accepted" else "ref"] += 1
        if "scope conflict:" in line:
            o["conflict"] += 1
        if "the lower rank keeps the initiator role" in line:
            o["tie"] += 1
        if "GIN/TS: watchdog rank=" in line:
            o["watchdog"] += 1
        m = RE_EP.search(line)
        if m:
            o["ep"].append((int(m.group(1)), int(m.group(2)), [x.strip() for x in m.group(3).split(",") if x.strip()]))
        m = RE_QPST.search(line)
        if m:
            o["qpst"].append((int(m.group(1)), int(m.group(2)), [x.strip() for x in m.group(3).split(",") if x.strip()]))
        if "GIN/TS: communicator teardown rank=" in line:
            o["teardown"] += 1
        m = RE_Q4.search(line)
        if m and o["q4"] is None:
            o["q4"] = (m.group(1), float(m.group(2)))
        if "Multiple Ranks are using the same GPU" in line:
            o["mrge"] += 1
        if "bind: Address already in use" in line:
            o["bind"] += 1
        m = RE_KNOBS.search(line)
        if m and o["knob_stall"] is None and m.group(2) != "0":
            o["knob_stall"] = m.group(2)
    return o


def jl(xs):
    return ";".join(sorted(xs))


def overlap(iv):
    iv = sorted(iv)
    if len(iv) < 2:
        return ""
    return int(any(iv[k + 1][0] < iv[k][1] for k in range(len(iv) - 1)))


def rows_of(stem):
    m = kvfile(stem + "_meta.txt")
    n = int(m.get("n", "0") or 0)
    iters = int(m.get("iters", "0") or 0)
    gap_ms = (fnum(m.get("gap_us")) or 0) / 1000.0
    k = [kvfile(f"{stem}_r{r}.kv") for r in range(n)]
    lg = [scan(f"{stem}_r{r}.log") for r in range(n)]
    off = [0.0] + [fnum(k[0].get(f"clock_offset_ms_r{r}")) for r in range(1, n)] if n else []

    def to0(r, t):  # rank r's time on rank 0's clock
        if t is None or off[r] is None:
            return None
        return t - off[r]

    d = {"stem": os.path.basename(stem), "cell": m.get("cell", ""), "lib": m.get("lib", ""), "mrkey": m.get("mrkey", ""),
         "build": m.get("lib", ""), "n": n, "mode": m.get("mode", ""), "flush": m.get("flush", ""), "iters": iters,
         "trial": m.get("trial", ""), "left": m.get("left", ""),
         "rc_all": ",".join(m.get(f"r{r}rc", "") for r in range(n)), "bind_fail": int(lg[0]["bind"] > 0) if n else 0}
    launch = [fnum(x.get("launch_mono_ms")) for x in k]
    d["n_devcomm"] = sum(1 for x in k if "devcomm_mono_ms" in x)
    d["n_launch"] = sum(1 for x in launch if x is not None)
    d["init_fail"] = int(d["n_devcomm"] < n)
    d["mrge_err"] = int(any(x["mrge"] for x in lg))
    gq = [q for x in lg for q in x["ts_on"]]
    d["n_ts_on"] = len(gq)
    d["gq_min"] = min(gq) if gq else ""
    d["gq_max"] = max(gq) if gq else ""
    for key in ("ts_off", "ua", "ow", "pr", "pc", "hd", "esc", "fw_over", "copy_to", "cancel"):
        d["n_" + key] = sum(x[key] for x in lg)
    d["n_judged_dead"] = sum(x["dead_j"] for x in lg)
    # edges
    elist = []
    edges_meta = m.get("edges", "all")
    if edges_meta in ("", "all"):
        elist = [(a, b) for a in range(n) for b in range(n) if a != b]
    else:
        for e in edges_meta.split(","):
            a, b = e.split("-")
            elist.append((int(a), int(b)))
    ok, bad, p50, mx = {}, [], {}, {}
    for a, b in elist:
        t, rv = k[a], k[b]
        e = f"{a}{b}"
        good = (t.get(f"tx_{e}_done") == str(iters) and t.get(f"tx_{e}_rc") == "no error" and
                rv.get(f"rx_{e}_done") == str(iters) and rv.get(f"rx_{e}_rc") == "no error" and
                rv.get(f"rx_{e}_devbad") == "0" and rv.get(f"rx_{e}_hostbad") == "0" and rv.get(f"rx_{e}_sigexact") == "1")
        ok[(a, b)] = good
        if not good:
            bad.append(f"{a}>{b}")
        p50[(a, b)] = fnum(t.get(f"tx_{e}_p50_us"))
        mx[(a, b)] = fnum(t.get(f"tx_{e}_max_us"))
        d[f"p50_{e}"] = "" if p50[(a, b)] is None else p50[(a, b)]
        d[f"max_{e}"] = "" if mx[(a, b)] is None else mx[(a, b)]
        for c in ("in", "ovlmax_us"):
            if f"w_{e}_{c}" in t:
                d[f"w_{e}_{c}"] = t[f"w_{e}_{c}"]
    d["edges"] = jl(f"{a}>{b}" for a, b in elist)
    d["n_edges"] = len(elist)
    d["n_edges_ok"] = sum(1 for v in ok.values() if v)
    d["edges_bad"] = jl(bad)
    outs = [x.get("outcome", "") for x in k]
    d["outcomes"] = ";".join(f"{r}:{o}" for r, o in enumerate(outs))
    d["n_outcome_ok"] = sum(1 for o in outs if o == "ok")
    asy = [f"r{r}" for r, x in enumerate(k) if x.get("async_first", "none") not in ("none", "")]
    d["async_ranks"] = ",".join(asy)
    d["n_async"] = len(asy)
    d["transparent_ok"] = int(n > 0 and len(elist) > 0 and all(ok.values()) and d["n_outcome_ok"] == n and not asy)
    p01 = p50.get((0, 1))
    d["p50_01"] = "" if p01 is None else p01
    inter = [v for (a, b), v in p50.items() if v is not None and a % 2 != b % 2]
    intra = [v for (a, b), v in p50.items() if v is not None and a % 2 == b % 2]
    d["p50_inter_med"] = statistics.median(inter) if inter else ""
    d["p50_intra_med"] = statistics.median(intra) if intra else ""
    mxs = [v for v in mx.values() if v is not None]
    d["max_all"] = max(mxs) if mxs else ""
    for r in range(n):
        if "win_edge" in k[r]:
            d[f"win_edge_r{r}"] = k[r]["win_edge"]
            d[f"win_us_r{r}"] = k[r].get("win_us", "")
    # fault hooks
    fires, inside = [], True
    for r in range(n):
        for c, t in lg[r]["fires"]:
            fires.append(f"{r}:{c}")
            lo = launch[r]
            if lo is None or not (lo < t < lo + iters * gap_ms):
                inside = False
    d["fires"] = jl(fires)
    d["n_fires"] = len(fires)
    d["fire_in_traffic"] = int(bool(fires) and inside) if fires else ""
    # rounds, recoveries, declines
    rounds = [x for r in range(n) for x in lg[r]["rounds"]]
    d["rounds"] = jl(f"{R}>{P}:{Q}:{X}" for R, P, Q, X, _ in rounds)
    d["n_rounds"] = len(rounds)
    rec = [x for r in range(n) for x in lg[r]["rec"]]
    ri = [f"{x.get('rank')}-{x.get('peer')}" for x in rec if x.get("role") == "initiator"]
    rr = [f"{x.get('rank')}-{x.get('peer')}" for x in rec if x.get("role") == "responder"]
    d["rec_i"], d["n_rec_i"], d["rec_r"], d["n_rec_r"] = jl(ri), len(ri), jl(rr), len(rr)
    decl = [x for r in range(n) for x in lg[r]["decl"]]
    d["decl"] = jl(f"{R}-{P}" for R, P, _, _ in decl)
    d["n_decl"] = len(decl)
    d["decl_reasons"] = " | ".join(sorted(f"{R}-{P}={w}" for R, P, w, _ in decl))
    d["decl_hs"] = jl(f"{R}-{P}" for R, P, w, _ in decl if w == "handshake timeout")
    d["n_watchdog"] = sum(x["watchdog"] for x in lg)
    d["n_refused"] = sum(x["ref"] for x in lg)
    d["n_conflict"] = sum(x["conflict"] for x in lg)
    d["n_tie"] = sum(x["tie"] for x in lg)
    # teardown gate epochs and QP states
    ep, st = [], []
    for r in range(n):
        for R, P, vals in lg[r]["ep"]:
            ep += [f"{R}-{P}-{c}={v}" for c, v in enumerate(vals) if v != "0"]
        for R, P, vals in lg[r]["qpst"]:
            st += [f"{R}-{P}-{c}={v}" for c, v in enumerate(vals) if v != "3"]
    d["ep_nz"], d["n_ep_nz"] = jl(ep), len(ep)
    d["ep_peers"] = ",".join("p" + p for p in sorted({x.split("-")[1] for x in ep}, key=int))
    d["notrts"], d["n_notrts"] = jl(st), len(st)
    d["notrts_peers"] = ",".join("p" + p for p in sorted({x.split("-")[1] for x in st}, key=int))
    d["n_teardown"] = sum(x["teardown"] for x in lg)
    d["q4_first"] = ";".join(f"{r}:{lg[r]['q4'][0]}" for r in range(n) if lg[r]["q4"])
    # kill
    ko = kvfile(stem + "_kill.out")
    kr = m.get("kill_rank", "")
    d["kill_rank"] = kr
    d["killed"] = int("kill_mono_ms" in ko)
    kms0 = None
    if d["killed"] and kr != "":
        kr_i = int(kr)
        node_off = off[kr_i] if kr_i < len(off) else None
        if ko.get("node") == "rain":  # rain's clock is rank 0's clock
            node_off = 0.0
        kms0 = None if node_off is None else float(ko["kill_mono_ms"]) - node_off
    d["kill_ms0"] = "" if kms0 is None else kms0
    l0 = [to0(r, launch[r]) for r in range(n)]
    if kms0 is not None and all(x is not None for x in l0) and l0:
        d["kill_in_traffic"] = int(kms0 > max(l0) and kms0 + 5000 <= min(l0) + iters * gap_ms)
    else:
        d["kill_in_traffic"] = 0 if d["killed"] else ""
    for r in range(n):
        dl = lg[r]["decl"]
        t = to0(r, dl[0][3]) if dl else None
        d[f"decl_ms_r{r}"] = "" if t is None else t
        d[f"decl_after_kill_ms_r{r}"] = "" if (t is None or kms0 is None) else t - kms0
        rs = lg[r]["rounds"]
        t0r = to0(r, rs[0][4]) if rs else None
        d[f"round_ms_r{r}"] = "" if t0r is None else t0r
        hs = [x for x in dl if x[2] == "handshake timeout"]
        d[f"decl_after_round_ms_r{r}"] = (hs[0][3] - rs[0][4]) if (hs and rs) else ""
    rts = [d[f"round_ms_r{r}"] for r in range(n) if d[f"round_ms_r{r}"] != ""]
    d["cyc_spread_ms"] = (max(rts) - min(rts)) if rts else ""
    # the first "handshake timeout" decline (rank 0's clock) and its delay after that rank's own first round line
    hs = []
    for r in range(n):
        x = [y for y in lg[r]["decl"] if y[2] == "handshake timeout"]
        if x and lg[r]["rounds"]:
            hs.append((to0(r, x[0][3]), x[0][3] - lg[r]["rounds"][0][4]))
    hs = [h for h in hs if h[0] is not None]
    d["n_hs"] = sum(1 for r in range(n) for y in lg[r]["decl"] if y[2] == "handshake timeout")
    d["hs_first_after_round_ms"] = min(hs)[1] if hs else ""
    # initiator rounds that recovered: their total_us (round start to resumed), in ms
    tot = [fnum(x.get("total_us")) for x in rec if x.get("role") == "initiator"]
    tot = [t / 1000.0 for t in tot if t is not None]
    d["init_total_ms_min"] = min(tot) if tot else ""
    d["init_total_ms_max"] = max(tot) if tot else ""
    # F3 detection: rank 0's first classifier record minus rank 1's first fire (rank 0's clock)
    q0 = lg[0]["q4"][1] if (n and lg[0]["q4"]) else None
    f1 = to0(1, lg[1]["fires"][0][1]) if (n > 1 and lg[1]["fires"]) else None
    d["f3_detect_ms"] = (q0 - f1) if (q0 is not None and f1 is not None) else ""
    # serialisation of rank 0's rounds
    resp0 = [(fnum(x.get("t_req")), fnum(x.get("t_resumed"))) for x in lg[0]["rec"] if x.get("role") == "responder"] if n else []
    init0 = [(fnum(x.get("t_start")), fnum(x.get("t_resumed"))) for x in lg[0]["rec"] if x.get("role") == "initiator"] if n else []
    d["resp_overlap_r0"] = overlap([iv for iv in resp0 if None not in iv])
    d["init_overlap_r0"] = overlap([iv for iv in init0 if None not in iv])
    # kill trials: edges between survivors
    if kr != "":
        kr_i = int(kr)
        surv = [(a, b) for a, b in elist if kr_i not in (a, b)]
        d["n_surv_edges"] = len(surv)
        d["surv_edges_ok"] = sum(1 for e in surv if ok[e])
        d["surv_tx_failed"] = sum(1 for a, b in surv if k[a].get(f"tx_{a}{b}_rc", "") not in ("no error", ""))
        d["surv_rx_failed"] = sum(1 for a, b in surv if k[b].get(f"rx_{a}{b}_rc", "") not in ("no error", ""))
    else:
        d["n_surv_edges"] = d["surv_edges_ok"] = d["surv_tx_failed"] = d["surv_rx_failed"] = ""
    d["knob_stall"] = jl(f"{r}:{lg[r]['knob_stall']}" for r in range(n) if lg[r]["knob_stall"])
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rows = []
    for dd in a.dirs:
        for meta in sorted(glob.glob(os.path.join(dd, "*_meta.txt"))):
            r = rows_of(meta[: -len("_meta.txt")])
            r["dir"] = os.path.basename(os.path.normpath(dd))
            rows.append(r)
    keys = []
    for r in rows:
        for c in r:
            if c not in keys:
                keys.append(c)
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"{len(rows)} trials", file=sys.stderr)


if __name__ == "__main__":
    main()
