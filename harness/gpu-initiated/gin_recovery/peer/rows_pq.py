#!/usr/bin/env python3
"""gin-peer: the columns of EXPERIMENT.md section 3.1 that the earlier extractors do not produce, read from the per-trial
files. score.py imports extra_pq2() (two-rank trials of run_trial_hq.sh: <stem>_r0.log, _r1.log, _r0.kv, _r1.kv,
_meta.txt, _decoy.out) and extra_pq4() (N-rank trials of run_mr_hq.sh: <stem>_r<r>.log/.kv for every rank, _meta.txt,
_kill.out, _decoy.out, plus the row of ../multirank/rows_mr.py). Times are mono_ms (CLOCK_MONOTONIC, ms) of the rank
whose file they come from, unless a column says otherwise. Lists are sorted and joined with ";". "R-P" = rank R, peer P.

Log lines (the hq library, EXPERIMENT.md 3.1 table):
  START    "GIN/TS: peer=1 rank=<r> per_peer_words=1 ..."                          (WARN in hq, INFO in hqp)
  UAPEER   "GIN/TS: user devComm waits on rank <p> released rank=<r> why=<w> mono_ms=<t>"
  UAALL    "GIN/TS: user devComm waits released rank=<r> why=<w> mono_ms=<t>"      (also hd/hf; why abort|revoke|shrink
           are the communicator's own teardown and are not counted in n_uaerr)
  CAUSE    "GIN/TS: rank <r>: GIN error raised for rank <p> cause=<c>[ (firmware overrun)] mono_ms=<t>"
  FAILANS  "GIN/TS: rank <r>: answered a <re-dial|probe> of declined rank <p> with FAIL mono_ms=<t>"
  PEERFAIL "GIN/TS: rank <r>: rank <p> declined this pair (FAIL on <re-dial|probe>) mono_ms=<t>"
  PLANOK   "GIN/TS: rank <r>: re-post plan to rank <p> validated: <q> qp(s), <w> WQE(s), role=<role>, before this rank's
           commit mono_ms=<t>"
  PLANREJ  "GIN/TS: rank <r>: re-post plan to rank <p> rejected at qp <i> of <n> (<why>); nothing re-posted mono_ms=<t>"
  FWOVER   "GIN/TS: watchdog rank=<r>: firmware command phase <ph> has run <x> ms, more than NCCL_GIN_TS_FW_MS=<n>; device
           waits on rank <p> are released ... (round <k>; later rounds are not affected) mono_ms=<t>"   (hq form)
  FWOLD    "... more than NCCL_GIN_TS_FW_MS=<n>; device waits are released with an error ..."           (hd/hf form)
  CANCEL   "GIN/TS: rank <r>: round <k> with rank <p> cancelled (<stage>, socket <c>) before the commit ..."
  DECL     "GIN/TS: declined rank=<r> peer=<p> reason="<why>" class=<c> mono_ms=<t>"
  MUTEOFF  "GIN/TS: TEST socket mute off rank=<r> peers=<n> mono_ms=<t>"
  FORGET   "GIN/TS: rank <r>: refusal by rank <p> from <x> ms ago forgotten ..."
  HOFF     "GIN/TS: rank <r>: aborting shrink proceeds past the parent's GIN error, raised for rank(s) <list>, all excluded"
  KEEP     "GIN/TS: rank <r>: aborting shrink keeps the parent's error (<why>) mono_ms=<t>"

Two-rank columns (_r<r> for rank r = 0, 1):
  pq_on_r*                  START lines
  n_uapeer_r*, uapeer_r*    UAPEER lines; their peers "p:<why>" (list)
  n_uaerr_r*, uaerr_why_r*  UAALL lines whose why is declined, peer-dead or fw-watchdog; the first why
  causes_r*, cause_r*       CAUSE lines as "p:c" (list); c of the first
  n_failans_r*, failans_r*  FAILANS lines; their kinds (list)
  n_peerfail_r*, peerfail_r*  PEERFAIL lines; their kinds (list)
  n_planok_r*, planok_role_r*, planok_ms_r*   PLANOK lines; role and t of the first
  n_planrej_r*, planrej_ms_r*, planrej_qp_r*  PLANREJ lines; t and i of the first
  n_fwover_r*, fwover_phase_r*, fwover_ms_r*, fwover_peer_r*, n_fwold_r*
                            FWOVER lines; phase, run ms and peer of the first; FWOLD lines
  n_cancel_ack_r*, cancel_ms_r*   CANCEL lines with stage "waiting for ACK"; t of the first CANCEL line
  declwhy_r*, decl_ms_r*    reason and t of the first DECL line
  muteoff_ms_r*             t of the first MUTEOFF line
  decl_after_unmute_ms_r*   decl_ms_r* - muteoff_ms_r* (same clock)
  decl_after_cancel_ms_r*   decl_ms_r* - cancel_ms_r* (same clock)
  n_forget_r*               FORGET lines
  n_rec_any                 "GIN/TS: recovered" lines of both ranks
  rdv_r*, rdv_rejected_r*, rdv_foreign_r0, rdv_decoy_r1   kv of the verified rendezvous (empty with an older driver)
  decoy_conns, decoy_bytes  <stem>_decoy.out
  port, port_tries, port_skipped, occupy_port, occupy_skipped, decoy_port   meta (runner)
N-rank columns (sums over the ranks unless _r<r>):
  n_pq_on                   ranks with a START line
  n_uapeer, uapeer          UAPEER lines; "R-P" pairs (list)
  n_uaerr                   UAALL lines with why declined, peer-dead or fw-watchdog
  causes                    CAUSE lines as "R-P=c" (list); n_cause_peerdead, n_cause_local: their counts
  n_fwover, fwover          FWOVER lines; "R-P:phase" (list); fwover_ms_r0: run ms of rank 0's first; n_fwold
  rec_20, rec_02            1 if rank 2 logged "recovered ... peer=0 role=initiator" / rank 0 "... peer=2 role=responder"
  n_bad_0_23                edges among 0>2, 0>3, 2>0, 3>0 that are not ok (as rows_mr's edge test)
  dead_rx_timeout, dead_tx_failed, surv_rx_timeout
                            kill trials: edges from the killed rank whose receiver rc is "timeout"; edges to it whose
                            sender rc is not "no error"; edges between survivors whose receiver rc is "timeout"
  n_hoff_ok, n_hoff_keep, keep_why_r0   HOFF and KEEP lines (all ranks); rank 0's first KEEP reason
  ch_ok_ranks, ch_created_ranks, ch_timeout_ranks, ch_shrink_fail_r0, ch_tx_ok_sum, ch_rx_ok_sum, ch_nranks_set
                            kv of the child phase (gin_mr.cu): ranks whose ch_outcome is ok (with ch_nranks = n - 1),
                            whose child exists with n - 1 ranks (ch_outcome ok or created), whose ch_outcome is timeout;
                            1 if rank 0's ch_shrink_rc is not "no error"; sums of ch_tx_ok and ch_rx_ok; the set of
                            ch_nranks values ("3" when every child rank saw 3)
  n_rdv_verified, n_decoy_rejected      ranks with rdv=verified; ranks with rdv_decoy=rejected
  decoy_conns, decoy_bytes, port, port_tries, port_skipped, occupy_port, occupy_skipped, decoy_port   as for two ranks
"""
import os, re

RE_START = re.compile(r"GIN/TS: peer=1 rank=\d+ per_peer_words=1")
RE_UAPEER = re.compile(r"GIN/TS: user devComm waits on rank (\d+) released rank=(\d+) why=(\S+) mono_ms=([\d.]+)")
RE_UAALL = re.compile(r"GIN/TS: user devComm waits released rank=(\d+) why=(\S+) mono_ms=([\d.]+)")
RE_CAUSE = re.compile(r"GIN/TS: rank (\d+): GIN error raised for rank (-?\d+) cause=(\S+)")
RE_FAILANS = re.compile(r"GIN/TS: rank \d+: answered a (re-dial|probe) of declined rank (\d+) with FAIL mono_ms=([\d.]+)")
RE_PEERFAIL = re.compile(r"GIN/TS: rank \d+: rank (\d+) declined this pair \(FAIL on (re-dial|probe)\) mono_ms=([\d.]+)")
RE_PLANOK = re.compile(r"GIN/TS: rank \d+: re-post plan to rank (\d+) validated: \d+ qp\(s\), \d+ WQE\(s\), role=(\w+), "
                       r"before this rank's commit mono_ms=([\d.]+)")
RE_PLANREJ = re.compile(r"GIN/TS: rank \d+: re-post plan to rank (\d+) rejected at qp (-?\d+) of (\d+) \(.*\); nothing "
                        r"re-posted mono_ms=([\d.]+)")
RE_FWOVER = re.compile(r"GIN/TS: watchdog rank=(\d+): firmware command phase (\S+) has run ([\d.]+) ms, more than "
                       r"NCCL_GIN_TS_FW_MS=\d+; device waits on rank (-?\d+) are released")
RE_FWOLD = re.compile(r"more than NCCL_GIN_TS_FW_MS=\d+; device waits are released with an error")
RE_CANCEL = re.compile(r"GIN/TS: rank \d+: round \d+ with rank \d+ cancelled \(([^,]*), socket [^)]*\) before the commit.*"
                       r"mono_ms=([\d.]+)")
RE_DECL = re.compile(r'GIN/TS: declined rank=(\d+) peer=(\d+) reason="([^"]*)" class=-?\d+ mono_ms=([\d.]+)')
RE_MUTEOFF = re.compile(r"GIN/TS: TEST socket mute off rank=\d+ peers=\d+ mono_ms=([\d.]+)")
RE_FORGET = re.compile(r"GIN/TS: rank \d+: refusal by rank \d+ from [\d.]+ ms ago forgotten")
RE_REC = re.compile(r"GIN/TS: recovered rank=(\d+) peer=(\d+) role=(\w+)")
RE_HOFF = re.compile(r"GIN/TS: rank \d+: aborting shrink proceeds past the parent's GIN error, raised for rank\(s\) \S+, all "
                     r"excluded")
RE_KEEP = re.compile(r"GIN/TS: rank \d+: aborting shrink keeps the parent's error \((.*)\) mono_ms=")
ERR_WHY = ("declined", "peer-dead", "fw-watchdog")


def kvfile(path):  # as ../scripts/ts2/rows.py: a value may hold blanks up to the next key
    d = {}
    if os.path.exists(path):
        for line in open(path, errors="replace"):
            for m in re.finditer(r"(\w+)=(.*?)(?= \w+=|$)", line.rstrip("\n")):
                d[m.group(1)] = m.group(2).strip().strip('"')
    return d


def scan(path):
    o = {"start": 0, "uapeer": [], "uaerr": [], "cause": [], "failans": [], "peerfail": [], "planok": [], "planrej": [],
         "fwover": [], "fwold": 0, "cancel": [], "decl": [], "muteoff": None, "forget": 0, "rec": [], "hoff": 0, "keep": []}
    if not os.path.exists(path):
        return o
    for line in open(path, errors="replace"):
        if RE_START.search(line):
            o["start"] += 1
        m = RE_UAPEER.search(line)
        if m:
            o["uapeer"].append((int(m.group(1)), m.group(3), float(m.group(4))))
            continue
        m = RE_UAALL.search(line)
        if m and m.group(2) in ERR_WHY:
            o["uaerr"].append((m.group(2), float(m.group(3))))
        m = RE_CAUSE.search(line)
        if m:
            o["cause"].append((int(m.group(2)), m.group(3)))
        m = RE_FAILANS.search(line)
        if m:
            o["failans"].append((m.group(1), int(m.group(2)), float(m.group(3))))
        m = RE_PEERFAIL.search(line)
        if m:
            o["peerfail"].append((m.group(2), int(m.group(1)), float(m.group(3))))
        m = RE_PLANOK.search(line)
        if m:
            o["planok"].append((m.group(2), float(m.group(3))))
        m = RE_PLANREJ.search(line)
        if m:
            o["planrej"].append((int(m.group(2)), int(m.group(3)), float(m.group(4))))
        m = RE_FWOVER.search(line)
        if m:
            o["fwover"].append((m.group(2), float(m.group(3)), int(m.group(4))))
        if RE_FWOLD.search(line):
            o["fwold"] += 1
        m = RE_CANCEL.search(line)
        if m:
            o["cancel"].append((m.group(1), float(m.group(2))))
        m = RE_DECL.search(line)
        if m:
            o["decl"].append((int(m.group(2)), m.group(3), float(m.group(4))))
        m = RE_MUTEOFF.search(line)
        if m and o["muteoff"] is None:
            o["muteoff"] = float(m.group(1))
        if RE_FORGET.search(line):
            o["forget"] += 1
        m = RE_REC.search(line)
        if m:
            o["rec"].append((int(m.group(1)), int(m.group(2)), m.group(3)))
        if RE_HOFF.search(line):
            o["hoff"] += 1
        m = RE_KEEP.search(line)
        if m:
            o["keep"].append(m.group(1))
    return o


def jl(xs):
    return ";".join(sorted(str(x) for x in xs))


def common(stem, o):  # meta (runner) and decoy columns
    m = kvfile(stem + "_meta.txt")
    d = kvfile(stem + "_decoy.out")
    o.update({"port": m.get("port"), "port_tries": m.get("port_tries"), "port_skipped": m.get("port_skipped"),
              "occupy_port": m.get("occupy_port"), "occupy_skipped": m.get("occupy_skipped"),
              "decoy_port": m.get("decoy_port"), "decoy_conns": d.get("decoy_conns"), "decoy_bytes": d.get("decoy_bytes")})
    return o


def extra_pq2(stem):
    o = {}
    n_rec = 0
    for r in (0, 1):
        s = scan(f"{stem}_r{r}.log")
        k = kvfile(f"{stem}_r{r}.kv")
        o[f"pq_on_r{r}"] = s["start"]
        o[f"n_uapeer_r{r}"] = len(s["uapeer"])
        o[f"uapeer_r{r}"] = jl(f"{p}:{w}" for p, w, _ in s["uapeer"])
        o[f"n_uaerr_r{r}"] = len(s["uaerr"])
        o[f"uaerr_why_r{r}"] = s["uaerr"][0][0] if s["uaerr"] else ""
        o[f"causes_r{r}"] = jl(f"{p}:{c}" for p, c in s["cause"])
        o[f"cause_r{r}"] = s["cause"][0][1] if s["cause"] else ""
        o[f"n_failans_r{r}"] = len(s["failans"])
        o[f"failans_r{r}"] = jl(kd for kd, _, _ in s["failans"])
        o[f"n_peerfail_r{r}"] = len(s["peerfail"])
        o[f"peerfail_r{r}"] = jl(kd for kd, _, _ in s["peerfail"])
        o[f"n_planok_r{r}"] = len(s["planok"])
        o[f"planok_role_r{r}"] = s["planok"][0][0] if s["planok"] else ""
        o[f"planok_ms_r{r}"] = s["planok"][0][1] if s["planok"] else ""
        o[f"n_planrej_r{r}"] = len(s["planrej"])
        o[f"planrej_qp_r{r}"] = s["planrej"][0][0] if s["planrej"] else ""
        o[f"planrej_ms_r{r}"] = s["planrej"][0][2] if s["planrej"] else ""
        o[f"n_fwover_r{r}"] = len(s["fwover"])
        o[f"fwover_phase_r{r}"] = s["fwover"][0][0] if s["fwover"] else ""
        o[f"fwover_ms_r{r}"] = s["fwover"][0][1] if s["fwover"] else ""
        o[f"fwover_peer_r{r}"] = s["fwover"][0][2] if s["fwover"] else ""
        o[f"n_fwold_r{r}"] = s["fwold"]
        o[f"n_cancel_ack_r{r}"] = sum(1 for st, _ in s["cancel"] if st == "waiting for ACK")
        cms = s["cancel"][0][1] if s["cancel"] else None
        o[f"cancel_ms_r{r}"] = "" if cms is None else cms
        dms = s["decl"][0][2] if s["decl"] else None
        o[f"declwhy_r{r}"] = s["decl"][0][1] if s["decl"] else ""
        o[f"decl_ms_r{r}"] = "" if dms is None else dms
        o[f"muteoff_ms_r{r}"] = "" if s["muteoff"] is None else s["muteoff"]
        o[f"decl_after_unmute_ms_r{r}"] = "" if dms is None or s["muteoff"] is None else round(dms - s["muteoff"], 3)
        o[f"decl_after_cancel_ms_r{r}"] = "" if dms is None or cms is None else round(dms - cms, 3)
        o[f"n_forget_r{r}"] = s["forget"]
        n_rec += len(s["rec"])
        o[f"rdv_r{r}"] = k.get("rdv", "")
        o[f"rdv_rejected_r{r}"] = k.get("rdv_rejected", "")
        if r == 0:
            o["rdv_foreign_r0"] = k.get("rdv_foreign", "")
        else:
            o["rdv_decoy_r1"] = k.get("rdv_decoy", "")
    o["n_rec_any"] = n_rec
    return common(stem, o)


def edge_ok(kv, a, b, iters):  # as ../multirank/rows_mr.py: sender and receiver results of edge a>b
    ks, kr = kv.get(a, {}), kv.get(b, {})
    e = f"{a}{b}"
    return (ks.get(f"tx_{e}_done") == str(iters) and ks.get(f"tx_{e}_rc") == "no error" and
            kr.get(f"rx_{e}_done") == str(iters) and kr.get(f"rx_{e}_rc") == "no error" and
            kr.get(f"rx_{e}_devbad") == "0" and kr.get(f"rx_{e}_hostbad") == "0" and kr.get(f"rx_{e}_sigexact") == "1")


def extra_pq4(stem, row):
    meta = kvfile(stem + "_meta.txt")
    n = int(meta.get("n", "0") or 0)
    iters = int(meta.get("iters", "0") or 0)
    kill = meta.get("kill_rank", "")
    kv = {r: kvfile(f"{stem}_r{r}.kv") for r in range(n)}
    sc = {r: scan(f"{stem}_r{r}.log") for r in range(n)}
    o = {"n_pq_on": sum(1 for r in range(n) if sc[r]["start"] >= 1)}
    o["n_uapeer"] = sum(len(sc[r]["uapeer"]) for r in range(n))
    o["uapeer"] = jl(f"{r}-{p}" for r in range(n) for p, _, _ in sc[r]["uapeer"])
    o["n_uaerr"] = sum(len(sc[r]["uaerr"]) for r in range(n))
    causes = [(r, p, c) for r in range(n) for p, c in sc[r]["cause"]]
    o["causes"] = jl(f"{r}-{p}={c}" for r, p, c in causes)
    o["n_cause_peerdead"] = sum(1 for _, _, c in causes if c == "peer-dead")
    o["n_cause_local"] = sum(1 for _, _, c in causes if c == "local")
    o["n_fwover"] = sum(len(sc[r]["fwover"]) for r in range(n))
    o["fwover"] = jl(f"{r}-{p}:{ph}" for r in range(n) for ph, _, p in sc[r]["fwover"])
    o["fwover_ms_r0"] = sc[0]["fwover"][0][1] if n and sc[0]["fwover"] else ""
    o["n_fwold"] = sum(sc[r]["fwold"] for r in range(n))
    recs = {(r, p, role) for r in range(n) for (_, p, role) in sc[r]["rec"]}
    o["rec_20"] = int((2, 0, "initiator") in recs)
    o["rec_02"] = int((0, 2, "responder") in recs)
    if n == 4:
        o["n_bad_0_23"] = sum(0 if edge_ok(kv, a, b, iters) else 1 for a, b in ((0, 2), (0, 3), (2, 0), (3, 0)))
    if kill != "":
        k = int(kill)
        surv = [r for r in range(n) if r != k]
        o["dead_rx_timeout"] = sum(1 for r in surv if kv[r].get(f"rx_{k}{r}_rc") == "timeout")
        o["dead_tx_failed"] = sum(1 for r in surv if kv[r].get(f"tx_{r}{k}_rc") not in (None, "no error"))
        o["surv_rx_timeout"] = sum(1 for a in surv for b in surv if a != b and kv[b].get(f"rx_{a}{b}_rc") == "timeout")
    o["n_hoff_ok"] = sum(sc[r]["hoff"] for r in range(n))
    o["n_hoff_keep"] = sum(len(sc[r]["keep"]) for r in range(n))
    o["keep_why_r0"] = sc[0]["keep"][0] if n and sc[0]["keep"] else ""
    want = str(n - 1)
    o["ch_ok_ranks"] = sum(1 for r in range(n) if kv[r].get("ch_outcome") == "ok" and kv[r].get("ch_nranks") == want)
    o["ch_created_ranks"] = sum(1 for r in range(n) if kv[r].get("ch_outcome") in ("ok", "created")
                                and kv[r].get("ch_nranks") == want)
    o["ch_timeout_ranks"] = sum(1 for r in range(n) if kv[r].get("ch_outcome") == "timeout")
    o["ch_shrink_fail_r0"] = int(bool(kv[0].get("ch_shrink_rc")) and kv[0].get("ch_shrink_rc") != "no error") if n else ""
    o["ch_tx_ok_sum"] = sum(int(kv[r].get("ch_tx_ok", "0") or 0) for r in range(n))
    o["ch_rx_ok_sum"] = sum(int(kv[r].get("ch_rx_ok", "0") or 0) for r in range(n))
    o["ch_nranks_set"] = jl({kv[r]["ch_nranks"] for r in range(n) if kv[r].get("ch_nranks")})
    o["n_rdv_verified"] = sum(1 for r in range(n) if kv[r].get("rdv") == "verified")
    o["n_decoy_rejected"] = sum(1 for r in range(n) if kv[r].get("rdv_decoy") == "rejected")
    return common(stem, o)
