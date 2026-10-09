#!/usr/bin/env python3
"""gin-remaining: the columns of EXPERIMENT.md section 3.1 that the earlier extractors do not produce, read from the
per-trial files. score.py imports extra_hr2() (two-rank trials of run_trial_hr.sh: <stem>_r0.log, _r1.log, _r0.kv,
_r1.kv, _meta.txt), extra_hr4() (N-rank trials of run_mr_hr.sh: <stem>_r<r>.log/.kv for every rank, _meta.txt, _kill.out,
plus the row of ../multirank/rows_mr.py), bench_row() (run_bench_hr.sh: <stem>_rain.kv, _sunny.kv, _meta.txt) and ngt_row()
(run_ngt_hr.sh: the same files; columns in its docstring).
Times are mono_ms (CLOCK_MONOTONIC, ms) of the process whose file they come from; a difference of two times is taken
within one process only. Lists are sorted and joined with ";".

Log lines (the hr library, EXPERIMENT.md 3.1 table; WARN in hr, the notes INFO in hrp):
  START   "GIN/TS: remaining=1 rank=<r> copy_path=<nic|stream> lb_mrs=<n> serve_wait=<0|1> degraded_ms=<g>"
  LBON    "GIN/TS: rank <r>: NIC copy path on: loopback qpn <a>-><b>, own PD, gid_index <i> (<link-local|gin|lid>), <n> GPU
           MR(s) (dmabuf <a>, peermem <b>), self-test ok (...), ..."
  LBOFF   "GIN/TS: rank <r>: the NIC copy path is off (<why>); ..."
  TDCOPY  "GIN/TS: rank <r> copy path at teardown: path=<nic|nic-off|stream> nic_ops=<a> nic_bytes=<b> nic_timeouts=<c>
           stream_copies=<d> served_in_wait=<e> kept=<f> fallbacks=<g>[ why=<w>]" (path=orphan: the helper was not
           joined; the NIC counters then read 0)
  SERVED  "GIN/TS: rank <r>: answering REQ round <k> from rank <p> while waiting for the ACK of round <j> from rank <t> ..."
  KEPT    "GIN/TS: rank <r>: REQ round <k> from rank <p> kept until round <j> with rank <t> ends ..."
  KEPTANS "GIN/TS: rank <r>: answering the kept REQ round <k> from rank <p> (kept <x> ms) ..."
  KEPTDROP "GIN/TS: rank <r>: the kept REQ round <k> from rank <p> is dropped ..."
  DEGSCHED "GIN/TS: rank <r>: communicator degraded in <g> ms: rank <p> was judged dead; ..."
  UAALL   "GIN/TS: user devComm waits released rank=<r> why=<w> mono_ms=<t>"   (why=degraded is new)
  JUDGED  "GIN/TS: rank <r>: rank <p> judged dead (cause=<c>) mono_ms=<t>"     (gin-harden)

Two-rank columns (_r<r> for rank r = 0, 1):
  hr_on_r*, copy_path_r*, lb_mrs_r*           START lines; copy_path and lb_mrs of the first
  lb_on_r*, lb_off_r*, lb_off_why_r*          LBON lines, LBOFF lines, the first LBOFF reason
  lb_gid_r*                                   the first LBON line's loopback GID as "<kind>:<index>"
  td_path_r*, td_nic_ops_r*, td_nic_timeouts_r*, td_stream_copies_r*, td_fallbacks_r*   the TDCOPY line (empty
                                              without it)
  hog_calls_after_r*                          kv hog_calls_after (gin_ts2.cu GIN_TS_HOG_CALLS; empty: an older driver)
  drvkey                                      meta drvkey (the driver's bundle)
N-rank columns (sums over the ranks unless _r<r>; "R-P" = rank R and peer P):
  n_hr_on, n_lb_on, n_lb_off                  ranks with START; LBON lines; LBOFF lines
  served, n_served                            SERVED lines as "R-P" (R answered P inside its own wait; a refusal of the
                                              REQ, NACK 12, 2 or 16, counts too)
  served_rec, n_served_rec                    of those, the ones whose nested round ended in R's responder recovery line
                                              with P before R's BACK line (descriptive; added after the re-review, L-A)
  kept, n_kept, n_kept_answered, n_kept_dropped   KEPT lines as "R-P"; KEPTANS lines; KEPTDROP lines
  td_stream_copies, n_td                      sum of TDCOPY stream_copies over the ranks that have the line (empty if
                                              none has it); the number of such ranks
  n_degr_sched, n_degraded, degr_ranks        DEGSCHED lines; UAALL lines with why=degraded; their ranks "r0,r1,..."
  dead_ms_r<r>                                rank r's first JUDGED line
  degr_after_dead_ms_r<r>                     rank r's degraded UAALL line - dead_ms_r<r>
  kill trials (kill_rank k; survivors s):
  rel_dead_r<s>                               kv rx_<k><s>_rel of survivor s (1: its untimed receive from k was released)
  rel_after_dead_ms_r<s>                      kv rx_<k><s>_rel_mono_ms - dead_ms_r<s> (survivor s's own clock)
  n_rel_dead                                  survivors with rel_dead == 1
  n_rel_surv                                  receive edges between survivors with rx_<a><b>_rel == 1
  surv_tx_ok                                  send edges between survivors with tx_<a><b>_done == iters and rc "no error"
  n_kdone_surv, n_stuck_surv                  survivors with kv kernel_done == 1; survivors whose outcome is
                                              async_error_kernel_stuck
  rx_untimed                                  1 if every rank's kv says rx_untimed=1
Benchmark columns (_rain, _sunny): name, host_native_atomic, lat_dev_atom_ns, lat_host_atom_ns, lat_host_atom_sys_ns,
  lat_dev_ld_ns, lat_host_ld_ns, race_host_writes, race_lost_host_writes, race_dev_ops, race_final_low, race_rc, exit;
  rc_rain, rc_sunny (meta)
"""
import os, re

RE_START = re.compile(r"GIN/TS: remaining=1 rank=(\d+) copy_path=(\w+) lb_mrs=(\d+) serve_wait=(\d) degraded_ms=(-?\d+)")
RE_LBON = re.compile(r"GIN/TS: rank (\d+): NIC copy path on: loopback qpn")
RE_LBGID = re.compile(r"NIC copy path on: .*?gid_index (-?\d+) \(([\w-]+)\)")
RE_LBOFF = re.compile(r"GIN/TS: rank (\d+): the NIC copy path is off \((.*?)\);")
RE_TD = re.compile(r"GIN/TS: rank (\d+) copy path at teardown: path=(\S+) nic_ops=(\d+) nic_bytes=(\d+) nic_timeouts=(\d+) "
                   r"stream_copies=(\d+) served_in_wait=(\d+) kept=(\d+)(?: fallbacks=(\d+))?")
RE_SERVED = re.compile(r"GIN/TS: rank (\d+): answering REQ round \d+ from rank (\d+) while waiting for the ACK of round \d+ "
                       r"from rank (\d+)")
RE_KEPT = re.compile(r"GIN/TS: rank (\d+): REQ round \d+ from rank (\d+) kept until round \d+ with rank (\d+) ends")
RE_KEPTANS = re.compile(r"GIN/TS: rank (\d+): answering the kept REQ round \d+ from rank (\d+)")
RE_KEPTDROP = re.compile(r"GIN/TS: rank (\d+): the kept REQ round \d+ from rank (\d+) is dropped")
RE_DEGSCHED = re.compile(r"GIN/TS: rank (\d+): communicator degraded in (-?\d+) ms: rank (\d+) was judged dead")
RE_UAALL = re.compile(r"GIN/TS: user devComm waits released rank=(\d+) why=(\S+) mono_ms=([\d.]+)")
RE_JUDGED = re.compile(r"GIN/TS: rank (\d+): rank (\d+) judged dead \(cause=\S+\) mono_ms=([\d.]+)")
RE_RECRESP = re.compile(r"GIN/TS: recovered rank=(\d+) peer=(\d+) role=responder")
RE_BACK = re.compile(r"GIN/TS: rank (\d+): back to round \d+ with rank \d+ after answering rank (\d+)")


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
    o = {"start": [], "lbon": 0, "lbgid": "", "lboff": [], "td": None, "served": [], "served_rec": [], "pending": None, "kept": [], "keptans": 0, "keptdrop": 0,
         "degsched": 0, "degraded": [], "judged": []}
    if not os.path.exists(path):
        return o
    for line in open(path, errors="replace"):
        m = RE_RECRESP.search(line)
        if m:
            if o["pending"] is not None and o["pending"] == (m.group(1), m.group(2)):
                o["served_rec"].append("%s-%s" % o["pending"])
                o["pending"] = None
            continue
        if RE_BACK.search(line):
            o["pending"] = None
            continue
        m = RE_START.search(line)
        if m:
            o["start"].append(m.groups())
            continue
        if RE_LBON.search(line):
            o["lbon"] += 1
            g = RE_LBGID.search(line)
            if g and not o["lbgid"]:
                o["lbgid"] = "%s:%s" % (g.group(2), g.group(1))
            continue
        m = RE_LBOFF.search(line)
        if m:
            o["lboff"].append(m.group(2))
            continue
        m = RE_TD.search(line)
        if m:
            o["td"] = m.groups()
            continue
        m = RE_SERVED.search(line)
        if m:
            o["served"].append("%s-%s" % (m.group(1), m.group(2)))
            o["pending"] = (m.group(1), m.group(2))
            continue
        m = RE_KEPT.search(line)
        if m:
            o["kept"].append("%s-%s" % (m.group(1), m.group(2)))
            continue
        if RE_KEPTANS.search(line):
            o["keptans"] += 1
            continue
        if RE_KEPTDROP.search(line):
            o["keptdrop"] += 1
            continue
        if RE_DEGSCHED.search(line):
            o["degsched"] += 1
            continue
        m = RE_UAALL.search(line)
        if m and m.group(2) == "degraded":
            o["degraded"].append(float(m.group(3)))
            continue
        m = RE_JUDGED.search(line)
        if m:
            o["judged"].append(float(m.group(3)))
    return o


def meta(stem):
    return kvfile(stem + "_meta.txt")


def extra_hr2(stem):
    d = {}
    mt = meta(stem)
    d["drvkey"] = mt.get("drvkey", "")
    for r in (0, 1):
        o = scan(f"{stem}_r{r}.log")
        k = kvfile(f"{stem}_r{r}.kv")
        d[f"hr_on_r{r}"] = len(o["start"])
        d[f"copy_path_r{r}"] = o["start"][0][1] if o["start"] else ""
        d[f"lb_mrs_r{r}"] = o["start"][0][2] if o["start"] else ""
        d[f"lb_on_r{r}"] = o["lbon"]
        d[f"lb_off_r{r}"] = len(o["lboff"])
        d[f"lb_off_why_r{r}"] = o["lboff"][0] if o["lboff"] else ""
        d[f"lb_gid_r{r}"] = o["lbgid"]
        td = o["td"]
        d[f"td_path_r{r}"] = td[1] if td else ""
        d[f"td_nic_ops_r{r}"] = td[2] if td else ""
        d[f"td_nic_timeouts_r{r}"] = td[4] if td else ""
        d[f"td_stream_copies_r{r}"] = td[5] if td else ""
        d[f"td_fallbacks_r{r}"] = (td[8] or "") if td else ""
        d[f"hog_calls_after_r{r}"] = k.get("hog_calls_after", "")
    return d


def extra_hr4(stem, row):
    d = {}
    mt = meta(stem)
    n = int(fnum(mt.get("n")) or 0)
    iters = int(fnum(mt.get("iters")) or 0)
    kill = mt.get("kill_rank", "")
    kr = int(kill) if kill not in ("", None) else None
    logs = [scan(f"{stem}_r{r}.log") for r in range(n)]
    kvs = [kvfile(f"{stem}_r{r}.kv") for r in range(n)]
    d["n_hr_on"] = sum(1 for o in logs if o["start"])
    d["n_lb_on"] = sum(o["lbon"] for o in logs)
    d["n_lb_off"] = sum(len(o["lboff"]) for o in logs)
    served = sorted(x for o in logs for x in o["served"])
    served_rec = sorted(x for o in logs for x in o["served_rec"])
    d["served_rec"] = ";".join(served_rec)
    d["n_served_rec"] = len(served_rec)
    kept = sorted(x for o in logs for x in o["kept"])
    d["served"] = ";".join(served)
    d["n_served"] = len(served)
    d["kept"] = ";".join(kept)
    d["n_kept"] = len(kept)
    d["n_kept_answered"] = sum(o["keptans"] for o in logs)
    d["n_kept_dropped"] = sum(o["keptdrop"] for o in logs)
    tds = [o["td"] for o in logs if o["td"] is not None]  # a killed rank has none
    d["td_stream_copies"] = sum(int(t[5]) for t in tds) if tds else ""
    d["n_td"] = len(tds)
    d["n_degr_sched"] = sum(o["degsched"] for o in logs)
    d["n_degraded"] = sum(len(o["degraded"]) for o in logs)
    d["degr_ranks"] = ",".join(f"r{r}" for r in range(n) if logs[r]["degraded"])
    for r in range(n):
        dead = min(logs[r]["judged"]) if logs[r]["judged"] else None
        d[f"dead_ms_r{r}"] = dead if dead is not None else ""
        deg = logs[r]["degraded"][0] if logs[r]["degraded"] else None
        d[f"degr_after_dead_ms_r{r}"] = (deg - dead) if (deg is not None and dead is not None) else ""
    d["rx_untimed"] = 1 if n and all(k.get("rx_untimed") == "1" for k in kvs) else 0
    if kr is not None and 0 <= kr < n:
        surv = [r for r in range(n) if r != kr]
        nrel = 0
        for s in surv:
            rel = kvs[s].get(f"rx_{kr}{s}_rel", "")
            d[f"rel_dead_r{s}"] = rel
            if rel == "1":
                nrel += 1
            t = fnum(kvs[s].get(f"rx_{kr}{s}_rel_mono_ms"))
            dead = fnum(d.get(f"dead_ms_r{s}"))
            d[f"rel_after_dead_ms_r{s}"] = (t - dead) if (t is not None and t >= 0 and dead is not None) else ""
        d["n_rel_dead"] = nrel
        d["n_rel_surv"] = sum(1 for a in surv for b in surv if a != b and kvs[b].get(f"rx_{a}{b}_rel") == "1")
        d["surv_tx_ok"] = sum(1 for a in surv for b in surv if a != b and fnum(kvs[a].get(f"tx_{a}{b}_done")) == iters and
                              kvs[a].get(f"tx_{a}{b}_rc") == "no error")
        d["n_kdone_surv"] = sum(1 for s in surv if kvs[s].get("kernel_done") == "1")
        d["n_stuck_surv"] = sum(1 for s in surv if kvs[s].get("outcome") == "async_error_kernel_stuck")
    else:
        for c in ("n_rel_dead", "n_rel_surv", "surv_tx_ok", "n_kdone_surv", "n_stuck_surv"):
            d[c] = ""
    return d


BENCH_KEYS = ["name", "host_native_atomic", "lat_dev_atom_ns", "lat_host_atom_ns", "lat_host_atom_sys_ns", "lat_dev_ld_ns",
              "lat_host_ld_ns", "race_host_writes", "race_lost_host_writes", "race_dev_ops", "race_final_low", "race_rc",
              "exit"]


def bench_row(stem):
    mt = meta(stem)
    d = {"cell": mt.get("cell", "hm_bench"), "build": mt.get("build", ""), "trial": mt.get("trial", ""),
         "stem": os.path.basename(stem), "rc_rain": mt.get("rc_rain", ""), "rc_sunny": mt.get("rc_sunny", "")}
    for node in ("rain", "sunny"):
        k = kvfile(f"{stem}_{node}.kv")
        for key in BENCH_KEYS:
            d[f"{key}_{node}"] = k.get(key, "")
    return d


def ngt_row(stem):
    """The NIC gate test (run_ngt_hr.sh: <stem>_rain.kv, _sunny.kv, _meta.txt; nic_gate_test.cu). Per node:
    ng_result (PASS|FAIL, empty if the run did not finish), ng_rc (meta), ng_mr (dmabuf|peermem), ng_gid_kind,
    ng_rounds (the smaller of the two phases' rounds), and the sums over phases a and b of ng_lost_writes, ng_lost_inc,
    ng_dekker, ng_inside_nonzero, ng_quiesce_timeouts; ng_idx_ok (1 if both phases kept every index-word update);
    ng_q_max_ms (larger phase maximum), ng_nic_errors,
    ng_error (setup_error or nic_error, if any)."""
    mt = meta(stem)
    d = {"cell": mt.get("cell", "nic_gate"), "build": mt.get("build", ""), "trial": mt.get("trial", ""),
         "stem": os.path.basename(stem), "rc_rain": mt.get("rc_rain", ""), "rc_sunny": mt.get("rc_sunny", "")}
    for node in ("rain", "sunny"):
        k = kvfile(f"{stem}_{node}.kv")
        d[f"ng_rc_{node}"] = mt.get(f"rc_{node}", "")
        d[f"ng_result_{node}"] = k.get("result", "")
        d[f"ng_mr_{node}"] = k.get("mr", "")
        d[f"ng_gid_kind_{node}"] = k.get("gid_kind", "")
        d[f"ng_name_{node}"] = k.get("name", "")
        rounds = [fnum(k.get(f"{ph}_rounds")) for ph in ("a", "b")]
        d[f"ng_rounds_{node}"] = min(rounds) if all(x is not None for x in rounds) else ""
        for col, key in (("lost_writes", "lost_writes"), ("lost_inc", "lost_inc"), ("dekker", "dekker"),
                         ("inside_nonzero", "inside_nonzero"), ("quiesce_timeouts", "quiesce_timeouts")):
            v = [fnum(k.get(f"{ph}_{key}")) for ph in ("a", "b")]
            d[f"ng_{col}_{node}"] = sum(v) if all(x is not None for x in v) else ""
        ix = [fnum(k.get(f"{ph}_idx_ok")) for ph in ("a", "b")]
        d[f"ng_idx_ok_{node}"] = min(ix) if all(x is not None for x in ix) else ""
        q = [fnum(k.get(f"{ph}_q_max_ms")) for ph in ("a", "b")]
        d[f"ng_q_max_ms_{node}"] = max(q) if all(x is not None for x in q) else ""
        d[f"ng_nic_errors_{node}"] = k.get("nic_errors", "")
        d[f"ng_error_{node}"] = k.get("setup_error", "") or k.get("nic_error", "") or k.get("cuda_error", "")
    return d

