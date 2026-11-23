#!/usr/bin/env python3
"""Independent recount of gpu-detect regression trials (results/20261009/reg/{hk,mr_hk,mr_hw}) from the raw files
(driver kv, library log lines, runner meta and kill.out). Written without reading rows_gd.py / score.py or gin-remaining's
score.py; column meanings come from the EXPERIMENT.md 3.1 prose and the predictions' text.
Usage: reg_recount.py <results_dir> <out_csv>
"""
import csv, glob, gzip, os, re, statistics, sys

R = sys.argv[1]
OUT = sys.argv[2]

RX_FIRE = re.compile(r"GDAKI fault fired \(shot \d+/\d+\): moved (\d+)/(\d+) GIN QP\(s\) to ERR(?: context=(\d+))? fire_mono_ms=([\d.]+) done_mono_ms=([\d.]+)")
RX_DECL = re.compile(r"GIN/TS: declined rank=(\d+) peer=(\d+) reason=\"([^\"]*)\".*mono_ms=([\d.]+)")
RX_CAUSE = re.compile(r"GIN/TS: rank (\d+): GIN error raised for rank (\d+) cause=(\S+) mono_ms=([\d.]+)")
RX_JUDGED = re.compile(r"GIN/TS: rank (\d+): rank (\d+) judged dead \(cause=(\w+)\) mono_ms=([\d.]+)")
RX_UAREL = re.compile(r"GIN/TS: user devComm waits (?:on rank (\d+) )?released rank=(\d+) why=([\w-]+) mono_ms=([\d.]+)")
RX_REC = re.compile(r"GIN/TS: recovered rank=(\d+) peer=(\d+) role=(\w+) round=(\d+) class=(\S+)")
RX_ROUND = re.compile(r"GIN/TS: rank (\d+): round (\d+) peer (\d+) scope=\S+ qps=\d+ reason=(\w+) mono_ms=([\d.]+)")
RX_SERVE = re.compile(r"GIN/TS: rank (\d+): answering REQ round (\d+) from rank (\d+) while waiting for the ACK of round (\d+) from rank (\d+)")
RX_KEPT = re.compile(r"GIN/TS: rank (\d+): REQ round (\d+) from rank (\d+) kept until")
RX_HS = re.compile(r"handshake timeout", re.I)
RX_LAC = re.compile(r"GIN/TS: rank (\d+): socket to rank (\d+) lost after this rank's commit")
RX_EXITACK = re.compile(r"GIN/TS: TEST exit after ACK rank=(\d+) peer=(\d+) round=(\d+)")
RX_STALL = re.compile(r"GIN/TS: TEST stall rank=(\d+) (\d+) ms after (\w+) mono_ms=([\d.]+)")
RX_POL = re.compile(r"GIN/TS: fault policy rank=(\d+) requested=(\w+) agreed=(\d) effective=(\w+)")
RX_HOLDWARN = re.compile(r"NCCL_GIN_FAULT_POLICY=hold requested, not available in this build")
RX_MIXWARN = re.compile(r"NCCL_GIN_FAULT_POLICY differs across ranks")
RX_DETECT = re.compile(r"GIN/TS: detect=1 rank=(\d+) qpwatch_ms=(\d+)")
RX_LB = re.compile(r"NIC copy path on: .*?(\d+) QP struct\(s\) equal to the host shadow")
RX_WATCHDET = re.compile(r"QP watch: qpn \S+ \(rank (\d+), context (\d+)\) is in state (ERR|SQER) with no fault record")
RX_DEV = re.compile(r"GIN/Q4: device-classified error CQE rank=(\d+)")
RX_FWOVER = re.compile(r"firmware .*(overrun|exceed)|fw_overrun", re.I)


def kv(path):
    d = {}
    try:
        txt = open(path, errors="replace").read()
    except OSError:
        return None
    for tok in re.findall(r"(\S+?)=((?:[^=\s]+(?: (?![A-Za-z_0-9]+=)[^=\s]+)*)?)", txt):
        d.setdefault(tok[0], tok[1])
    return d


def kv2(path):
    """key=value tokens; values may contain spaces (e.g. 'rc=no error'): a value runs until the next ' key='."""
    d = {}
    try:
        lines = open(path, errors="replace").read().splitlines()
    except OSError:
        return None
    for line in lines:
        parts = re.split(r" (?=[A-Za-z_][A-Za-z_0-9]*=)", line.strip())
        for p in parts:
            if "=" in p:
                k, v = p.split("=", 1)
                if k not in d:
                    d[k] = v
    return d


def meta(path):
    return kv2(path)


def lines(path):
    try:
        return open(path, errors="replace").read().splitlines()
    except OSError:
        return []


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


rows = []
for sub in ("hk", "mr_hk", "mr_hw"):
    base = os.path.join(R, "reg", sub)
    metas = sorted(glob.glob(os.path.join(base, "*_meta.txt")))
    for mp in metas:
        tid = os.path.basename(mp)[:-len("_meta.txt")]
        m = meta(mp)
        cell = m.get("cell")
        build = m.get("build") or m.get("lib")
        nr = int(m.get("n", "2")) if sub.startswith("mr") else 2
        K = {r: kv2(os.path.join(base, "%s_r%d.kv" % (tid, r))) or {} for r in range(nr)}
        L = {r: lines(os.path.join(base, "%s_r%d.log" % (tid, r))) for r in range(nr)}
        ko = kv2(os.path.join(base, "%s_kill.out" % tid)) or {}
        row = {"id": tid, "sub": sub, "cell": cell, "build": build, "key": "%s@%s" % (cell, build), "nr": nr,
               "wall_s": m.get("wall_s")}
        for r in range(nr):
            row["rc%d" % r] = m.get("r%drc" % r)
            row["outcome_r%d" % r] = K[r].get("outcome", "")
            row["exit_r%d" % r] = K[r].get("exit", "")
        # clock offsets relative to rank 0 (rank r clock = rank 0 clock + off[r])
        off = {0: 0.0}
        if nr == 2:
            off[1] = num(K[0].get("clock_offset_ms"))
        else:
            for r in range(1, nr):
                off[r] = num(K[0].get("clock_offset_ms_r%d" % r))
        # ---- common line counts
        allL = [(r, s) for r in range(nr) for s in L[r]]
        row["n_decl"] = sum(1 for r, s in allL if RX_DECL.search(s))
        row["n_hs"] = sum(1 for r, s in allL if RX_HS.search(s))
        row["n_rec"] = sum(1 for r, s in allL if RX_REC.search(s))
        row["n_watchdet"] = sum(1 for r, s in allL if RX_WATCHDET.search(s))
        row["watchdet_ranks"] = ";".join(sorted(set(str(r) for r, s in allL if RX_WATCHDET.search(s))))
        row["n_dev"] = sum(1 for r, s in allL if RX_DEV.search(s))
        row["n_judged"] = sum(1 for r, s in allL if RX_JUDGED.search(s))
        fires = [(r, RX_FIRE.search(s)) for r, s in allL if RX_FIRE.search(s)]
        row["fires"] = ";".join("%d:%s" % (r, f.group(3) if f.group(3) is not None else "-") for r, f in fires)
        row["fires_moved"] = ";".join("%d:%s/%s" % (r, f.group(1), f.group(2)) for r, f in fires)
        stalls = [(r, RX_STALL.search(s)) for r, s in allL if RX_STALL.search(s)]
        row["stalls"] = ";".join(sorted(set("%d:%s@%s" % (r, x.group(2), x.group(3)) for r, x in stalls)))
        det = [RX_DETECT.search(s) for r, s in allL if RX_DETECT.search(s)]
        row["det_ranks"] = len(set(x.group(1) for x in det))
        row["det_periods"] = ";".join(sorted(set(x.group(2) for x in det)))
        pol = [RX_POL.search(s) for r, s in allL if RX_POL.search(s)]
        row["pol_n"] = len(set(x.group(1) for x in pol))
        row["pol_req"] = ";".join("r%s:%s" % (x.group(1), x.group(2)) for x in pol)
        row["pol_agreed_min"] = min(int(x.group(3)) for x in pol) if pol else ""
        row["pol_eff_ff"] = int(bool(pol) and all(x.group(4) == "failfast" for x in pol))
        hw = {r: sum(1 for s in L[r] if RX_HOLDWARN.search(s)) for r in range(nr)}
        mw = {r: sum(1 for s in L[r] if RX_MIXWARN.search(s)) for r in range(nr)}
        row["n_hold_warn"] = sum(hw.values())
        row["hold_warn_ranks"] = sum(1 for r in hw if hw[r] == 1)
        row["n_mix_warn"] = sum(mw.values())
        row["mix_warn_ranks"] = sum(1 for r in mw if mw[r] == 1)
        lb = {r: [int(RX_LB.search(s).group(1)) for s in L[r] if RX_LB.search(s)] for r in range(nr)}
        row["lb_min"] = min((min(v) for v in lb.values() if v), default="")
        row["lb_ranks"] = sum(1 for v in lb.values() if v and min(v) >= 1)
        row["teardown_watch_lines"] = sum(1 for r, s in allL if "QP watch at teardown" in s)
        row["fw_overrun_lines"] = sum(1 for r, s in allL if RX_FWOVER.search(s))
        kill_ms = num(ko.get("kill_mono_ms"))
        kill_rank = ko.get("rank")
        row["kill_rank"] = kill_rank if kill_rank is not None else (m.get("kill_rank") or "")
        if nr == 2:
            # ---------- two ranks
            k0, k1 = K[0], K[1]
            iters = int(m.get("iters") or k0.get("iters") or 0)
            row["tx_done"], row["tx_rc"] = k0.get("tx_done"), k0.get("tx_rc")
            row["rx_done"], row["rx_rc"] = k1.get("rx_done"), k1.get("rx_rc")
            row["signal_exact"], row["host_bad"] = k1.get("signal_exact"), k1.get("host_bad_slots")
            row["rx_phantom_r1"] = k1.get("rx_phantom")
            row["final_async"] = "%s|%s" % (k0.get("final_async"), k1.get("final_async"))
            tr = (k0.get("outcome") == "ok" and k1.get("outcome") == "ok" and k0.get("exit") == "0" and k1.get("exit") == "0"
                  and m.get("r0rc") == "0" and m.get("r1rc") == "0" and row["n_decl"] == 0)
            if m.get("app") != "bidir" and m.get("fault") != "lat":
                tr = tr and k0.get("tx_rc") == "no error" and k1.get("rx_rc") == "no error" and k1.get("signal_exact") == "1"
            row["transparent_ok"] = int(bool(tr))
            row["rec_lines_r0"] = sum(1 for s in L[0] if RX_REC.search(s))
            row["rec_lines_r1"] = sum(1 for s in L[1] if RX_REC.search(s))
            for r in (0, 1):
                for f in ("rs_api", "rs_rounds", "rs_recovered", "rs_declined"):
                    row["%s_r%d" % (f, r)] = K[r].get(f, "")
            # declines on rank 0
            d0 = [RX_DECL.search(s) for s in L[0] if RX_DECL.search(s)]
            row["declwhy_r0"] = d0[0].group(3) if d0 else ""
            c0 = [RX_CAUSE.search(s) for s in L[0] if RX_CAUSE.search(s)]
            row["cause_r0"] = c0[0].group(3) if c0 else ""
            ua0 = [RX_UAREL.search(s) for s in L[0] if RX_UAREL.search(s) and RX_UAREL.search(s).group(3) != "abort"]
            row["uaerr_why_r0"] = ua0[0].group(3) if ua0 else ""
            row["teardown_r0"] = k0.get("abort_ret", "")
            row["teardown_r1"] = k1.get("abort_ret", "")
            row["teardown_ms_r1"] = k1.get("teardown_ms", "")
            row["r1_outcome"] = k1.get("outcome", "")
            if kill_ms is not None and d0:
                # kill of rank 1 (sunny clock) -> rank 0 clock: kill - off1
                o1 = off.get(1)
                if kill_rank in (None, "1") and o1 is not None and m.get("kill_r0") != "1":
                    row["decl_after_kill_ms_r0"] = round(float(d0[0].group(4)) - (kill_ms - o1), 3)
            if m.get("kill_r0") == "1" and kill_ms is not None:
                o1 = off.get(1)
                kill_r1clock = kill_ms + o1 if o1 is not None else None
                j1 = [RX_JUDGED.search(s) for s in L[1] if RX_JUDGED.search(s)]
                row["n_judged_r1"] = len(j1)
                rel1 = [RX_UAREL.search(s) for s in L[1] if RX_UAREL.search(s) and RX_UAREL.search(s).group(3) != "abort"]
                if kill_r1clock is not None:
                    row["judged_after_kill_ms_r1"] = round(float(j1[0].group(4)) - kill_r1clock, 3) if j1 else ""
                    row["release_after_kill_ms_r1"] = round(float(rel1[0].group(4)) - kill_r1clock, 3) if rel1 else ""
                    la, af = num(k1.get("launch_mono_ms")), num(k1.get("async_first_ms_after_launch"))
                    row["async_after_kill_ms_r1"] = round(la + af - kill_r1clock, 3) if la is not None and af is not None and af >= 0 else ""
                    # kill inside traffic: rank 1 still receiving at the kill
                    row["kill_in_traffic"] = int(la is not None and kill_r1clock > la and int(k1.get("rx_done", "0")) < iters)
            if cell in ("f4_b", "f4_mix_b") and kill_ms is not None:
                la1 = num(k1.get("launch_mono_ms"))
                row["kill_after_launch_ms"] = round(kill_ms - la1, 1) if la1 is not None else ""
                row["kill_in_traffic"] = int(la1 is not None and kill_ms > la1 and int(k0.get("tx_done", "0")) < iters)
            if m.get("fault") == "lat":
                row["lat_p50_us_kv"] = k0.get("lat_p50_us")
                raw = os.path.join(base, "%s_lat_raw.csv.gz" % tid)
                if os.path.exists(raw):
                    v = sorted(int(l.split(",")[1]) for l in gzip.open(raw, "rt").read().splitlines() if "," in l)
                    row["lat_n_raw"] = len(v)
                    row["lat_p50_us_raw_median"] = round(statistics.median(v) / 1000.0, 4)
                    row["lat_p50_us_raw_lower"] = round(v[len(v) // 2] / 1000.0, 4)
            row["lb_shadow2_min"] = row["lb_min"]
        else:
            # ---------- four ranks
            surv = [r for r in range(nr) if str(r) != str(row["kill_rank"])] if row["kill_rank"] not in ("", None) else list(range(nr))
            # transparency
            tr = all(K[r].get("outcome") == "ok" and K[r].get("exit") == "0" and K[r].get("tx_ok") == K[r].get("n_tx")
                     and K[r].get("rx_ok") == K[r].get("n_rx") for r in range(nr)) and row["n_decl"] == 0
            row["transparent_ok"] = int(bool(tr))
            recs = [RX_REC.search(s) for r, s in allL if RX_REC.search(s)]
            row["rec_i"] = ";".join(sorted(set("%s-%s" % (x.group(1), x.group(2)) for x in recs if x.group(3) == "initiator")))
            row["rec_all"] = ";".join(sorted(set("%s-%s" % (x.group(1), x.group(2)) for x in recs)))
            sv = [RX_SERVE.search(s) for r, s in allL if RX_SERVE.search(s)]
            row["served"] = ";".join(sorted(set("%s-%s" % (x.group(1), x.group(3)) for x in sv)))
            row["served3"] = ";".join(sorted(set("%s-%s" % (x.group(1), x.group(3)) for x in sv if x.group(1) == "3")))
            row["n_served3_lines"] = sum(1 for x in sv if x.group(1) == "3")
            kp = [RX_KEPT.search(s) for r, s in allL if RX_KEPT.search(s)]
            row["kept"] = ";".join(sorted(set("%s-%s" % (x.group(1), x.group(3)) for x in kp)))
            # round spread: first round line per initiating rank, rank-0 clock
            firsts = {}
            for r in range(nr):
                for s in L[r]:
                    x = RX_ROUND.search(s)
                    if x:
                        firsts.setdefault(r, float(x.group(5)) - (off.get(r) or 0.0))
                        break
            row["round_spread_ms"] = round(max(firsts.values()) - min(firsts.values()), 1) if len(firsts) >= 2 else ""
            row["round_ranks"] = ";".join(str(r) for r in sorted(firsts))
            # pair 0-1 (M-C)
            row["rec01"] = sum(1 for s in L[0] if RX_REC.search(s) and RX_REC.search(s).group(2) == "1")
            row["decl01"] = sum(1 for s in L[0] if RX_DECL.search(s) and RX_DECL.search(s).group(2) == "1")
            row["decl10"] = sum(1 for s in L[1] if RX_DECL.search(s) and RX_DECL.search(s).group(2) == "0")
            row["rec10"] = sum(1 for s in L[1] if RX_REC.search(s) and RX_REC.search(s).group(2) == "0")
            # death of X
            X = row["kill_rank"]
            if X in ("", None):
                ex = [RX_EXITACK.search(s) for r, s in allL if RX_EXITACK.search(s)]
                X = ex[0].group(1) if ex else ""
            row["gap_x"] = X
            if X not in ("", None):
                Xi = int(X)
                surv = [r for r in range(nr) if r != Xi]
                row["gap_exit_line"] = sum(1 for s in L[Xi] if RX_EXITACK.search(s))
                row["gap_rc_x"] = m.get("r%drc" % Xi)
                # per survivor: judged time, release time, kernel done, stuck
                nrel = nrel23 = kdone = stuck = 0
                ok_window = []
                for s_ in surv:
                    k = K[s_]
                    j = [RX_JUDGED.search(s) for s in L[s_] if RX_JUDGED.search(s) and RX_JUDGED.search(s).group(2) == str(Xi)]
                    jt = float(j[0].group(4)) if j else None
                    rel = k.get("rx_%d%d_rel" % (Xi, s_))
                    relt = num(k.get("rx_%d%d_rel_mono_ms" % (Xi, s_)))
                    row["judged_r%d" % s_] = int(bool(j))
                    row["rel_r%d" % s_] = rel
                    row["relms_r%d" % s_] = round(relt - jt, 1) if (relt is not None and jt is not None and rel == "1") else ""
                    dl = [RX_DECL.search(s) for s in L[s_] if RX_DECL.search(s) and RX_DECL.search(s).group(2) == str(Xi)]
                    row["declwhy_r%d" % s_] = dl[0].group(3)[:70] if dl else ""
                    cz = [RX_CAUSE.search(s) for s in L[s_] if RX_CAUSE.search(s) and RX_CAUSE.search(s).group(2) == str(Xi)]
                    row["cause_r%d" % s_] = cz[0].group(3) if cz else ""
                    if rel == "1":
                        nrel += 1
                        if row["relms_r%d" % s_] != "" and 2000 <= row["relms_r%d" % s_] <= 3000:
                            nrel23 += 1
                    if k.get("kernel_done") == "1":
                        kdone += 1
                    if k.get("outcome") == "async_error_kernel_stuck":
                        stuck += 1
                row["n_rel_dead"], row["n_rel23"], row["n_kdone_surv"], row["n_stuck_surv"] = nrel, nrel23, kdone, stuck
                # survivor-to-survivor sends
                ne = ok = 0
                rx_rel_surv = 0
                for a in surv:
                    for b in surv:
                        if a == b:
                            continue
                        if K[a].get("tx_%d%d_rc" % (a, b)) is not None:
                            ne += 1
                            if K[a].get("tx_%d%d_rc" % (a, b)) == "no error" and K[a].get("tx_%d%d_done" % (a, b)) == K[a].get("iters"):
                                ok += 1
                        if K[b].get("rx_%d%d_rel" % (a, b)) == "1":
                            rx_rel_surv += 1
                row["n_surv_edges"], row["surv_tx_ok"], row["n_rel_surv"] = ne, ok, rx_rel_surv
                # responder side (gap cells): first survivor declining X with "peer closed the socket before DONE"
                resp = ""
                for s_ in surv:
                    if any(RX_DECL.search(s) and RX_DECL.search(s).group(2) == str(Xi) and "peer closed the socket before DONE" in RX_DECL.search(s).group(3) for s in L[s_]):
                        resp = s_
                        break
                row["gap_resp"] = resp
                row["gap_hit"] = int(resp != "")
                if resp != "":
                    row["gap_cause"] = row.get("cause_r%d" % resp, "")
                    row["gap_lac"] = sum(1 for s in L[resp] if RX_LAC.search(s) and RX_LAC.search(s).group(2) == str(Xi))
                    row["gap_judged_r"] = row.get("judged_r%d" % resp)
                    row["gap_resp_rel"] = 1 if row.get("rel_r%d" % resp) == "1" else 0
                    row["gap_resp_stuck"] = 1 if K[resp].get("outcome") == "async_error_kernel_stuck" else 0
                    row["gap_resp_kdone"] = K[resp].get("kernel_done")
                    oth = [s_ for s_ in surv if s_ != resp]
                    row["gap_others_rel23"] = sum(1 for s_ in oth if row.get("relms_r%d" % s_) != "" and 2000 <= row["relms_r%d" % s_] <= 3000)
                # kill inside traffic: X's kill time vs survivors still running (rank-0 clock)
                if kill_ms is not None:
                    kx = kill_ms - (off.get(Xi) or 0.0)
                    lx = num(K[Xi].get("launch_mono_ms"))
                    row["kill_after_launch_ms"] = round(kill_ms - lx, 1) if lx is not None else ""
                    ends = [num(K[r].get("kernel_end_mono_ms")) - (off.get(r) or 0.0) for r in surv if num(K[r].get("kernel_end_mono_ms")) is not None]
                    row["kill_in_traffic"] = int(lx is not None and kill_ms > lx and all(K[r].get("tx_%d%d_done" % (r, Xi)) != K[r].get("iters") for r in surv))
        rows.append(row)

keys = []
for r in rows:
    for k in r:
        if k not in keys:
            keys.append(k)
with open(OUT, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=keys)
    w.writeheader()
    for r in rows:
        w.writerow(r)
print("rows", len(rows))
