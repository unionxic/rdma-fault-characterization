#!/usr/bin/env python3
"""S2 trial logs -> one CSV row per trial and one per recovery round (recomputed from the raw per-trial files).

usage: rows.py <logdir> [<logdir> ...] --out trials.csv [--rounds rounds.csv]

A trial is <stem>_meta.txt with <stem>_r{0,1}.{kv,log} (+ _cut.out, _gbh.log, _kill.out). Read from them:
  meta   runner line (cell, build, app, fault, wait, gidsel, cut, rc, left, wall)
  r*.kv  tx_* (sender), rx_* / host_* / signal* (receiver), lat_*, async_*, outcome; bidir: both on each rank
  logs   NCCL WARN lines: GIN/FAULT fired, GIN/Q4 device-classified error CQE, GIN/TS recovered (both roles),
         GIN/TS declined, simultaneous-REQ tie-break lines, local GID moved, communicator teardown
A run is transparent iff: both ranks' outcome ok; every sender ran all iterations with no flush error; every
receiver got all iterations, 0 bad slots on the device and on the host, every final signal exact; no host saw
an async error.
"""
import argparse, csv, glob, os, re, sys


def kvfile(path):
    d = {}
    if not os.path.exists(path):
        return d
    for line in open(path, errors="replace"):
        for m in re.finditer(r"(\w+)=(.*?)(?= \w+=|$)", line.rstrip("\n")):
            d[m.group(1)] = m.group(2).strip().strip('"')
    return d


def fnum(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def parse_log(path):
    out = {"fires": [], "q4": [], "rec": [], "decl": [], "decl_mono": None, "ts_on": 0, "ts_off": [], "tie_kept": 0,
           "yield": 0, "gid_moved": [], "teardown": 0, "watchdog": 0, "trigger_miss": 0, "quiesce_stuck": 0}
    if not os.path.exists(path):
        return out
    for line in open(path, errors="replace"):
        if "GIN/FAULT: GDAKI fault fired" in line:
            m = re.search(r"fire_mono_ms=([\d.]+)", line)
            if m:
                out["fires"].append(float(m.group(1)))
        elif "GIN/FAULT: shot 1 trigger not reached" in line:
            out["trigger_miss"] += 1
        elif "device-classified error CQE" in line:
            out["q4"].append(dict(re.findall(r"(\w+)=(\S+)", line)))
        elif "GIN/TS: recovered" in line:
            out["rec"].append(dict(re.findall(r"([\w/]+)=(\[[^\]]*\]|\S+)", line)))
        elif "GIN/TS: declined" in line:
            m = re.search(r'reason="([^"]*)"', line)
            out["decl"].append(m.group(1) if m else "?")
            m = re.search(r"mono_ms=([\d.]+)", line)
            if m and out["decl_mono"] is None:
                out["decl_mono"] = float(m.group(1))
        elif "GIN/TS: transparent recovery ON" in line:
            out["ts_on"] += 1
        elif "GIN/TS: transparent recovery OFF" in line:
            out["ts_off"].append(line.strip()[-120:])
        elif "the lower rank keeps the initiator role" in line:
            out["tie_kept"] += 1
        elif "the higher rank yields its round" in line:
            out["yield"] += 1
        elif "local GID moved from index" in line:
            m = re.search(r"index (\d+) to (\d+) \(looked up by value after ([\d.]+) ms", line)
            if m:
                out["gid_moved"].append((int(m.group(1)), int(m.group(2)), float(m.group(3))))
        elif "GIN/TS: communicator teardown" in line:
            out["teardown"] += 1
        elif "GIN/TS: watchdog" in line:
            out["watchdog"] += 1
        elif "still inside the gate after" in line:
            out["quiesce_stuck"] += 1
    return out


def rank_ok(k, iters, sender, receiver):
    if k.get("outcome") != "ok" or k.get("async_first") != "none":
        return False
    if sender and not (k.get("tx_done") == str(iters) and k.get("tx_rc") == "no error"):
        return False
    if receiver and not (k.get("rx_done") == str(iters) and k.get("rx_rc") == "no error" and k.get("dev_bad_slots") == "0"
                         and k.get("host_bad_slots") == "0" and k.get("signal_exact") == "1"):
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--rounds")
    a = ap.parse_args()
    rows, rounds = [], []
    for d in a.dirs:
        for meta in sorted(glob.glob(os.path.join(d, "*_meta.txt"))):
            stem = meta[: -len("_meta.txt")]
            m = kvfile(meta)
            k0, k1 = kvfile(stem + "_r0.kv"), kvfile(stem + "_r1.kv")
            l0, l1 = parse_log(stem + "_r0.log"), parse_log(stem + "_r1.log")
            cut = kvfile(stem + "_cut.out")
            off = fnum(k0.get("clock_offset_ms"), 0.0)  # rank1 - rank0
            iters = int(m.get("iters", "0"))
            app = m.get("app", "default")
            bidir = app == "bidir"
            r = {"dir": os.path.basename(os.path.normpath(d)), "stem": os.path.basename(stem),
                 "cell": m.get("cell") or os.path.basename(stem).rsplit("_", 1)[0], "build": m.get("build"), "app": app,
                 "fault": m.get("fault"), "wait": m.get("wait"), "trial": m.get("trial"), "ts": m.get("ts"),
                 "diag": m.get("diag", ""), "bytes": m.get("bytes"), "iters": iters, "inject": m.get("inject"),
                 "gidsel": m.get("gidsel"), "gid0": m.get("gid0"), "gid1": m.get("gid1"), "cut_s": m.get("cut_s"),
                 "r0rc": m.get("r0rc"), "r1rc": m.get("r1rc"), "left": m.get("left"), "wall_s": m.get("wall_s"),
                 "r0_outcome": k0.get("outcome"), "r1_outcome": k1.get("outcome"),
                 "burst_P": k0.get("burst_P"), "burst_K": k0.get("burst_K"), "burst_agg": k0.get("burst_agg"),
                 "tx_done": k0.get("tx_done"), "tx_rc": k0.get("tx_rc"), "tx_rc_it": k0.get("tx_rc_it"),
                 "tx_err_threads": k0.get("tx_err_threads"), "tx_max_iter_us": k0.get("tx_max_iter_us"),
                 "rx_done": k1.get("rx_done"), "rx_rc": k1.get("rx_rc"),
                 "dev_bad_slots": k1.get("dev_bad_slots"), "host_bad_slots": k1.get("host_bad_slots"),
                 "host_missing_slots": k1.get("host_missing_slots"), "host_slots": k1.get("host_slots"),
                 "signals": k1.get("signals"), "signals_bad": k1.get("signals_bad"), "signals_high": k1.get("signals_high"),
                 "signals_low": k1.get("signals_low"), "signal_exact": k1.get("signal_exact"),
                 "tx_done_r1": k1.get("tx_done"), "tx_rc_r1": k1.get("tx_rc"), "rx_done_r0": k0.get("rx_done"),
                 "rx_rc_r0": k0.get("rx_rc"), "dev_bad_slots_r0": k0.get("dev_bad_slots"),
                 "host_bad_slots_r0": k0.get("host_bad_slots"), "signal_exact_r0": k0.get("signal_exact"),
                 "r0_async": k0.get("async_first"), "r1_async": k1.get("async_first"),
                 "r0_async_ms": k0.get("async_first_ms_after_launch"), "r1_async_ms": k1.get("async_first_ms_after_launch"),
                 "async_samples_r0": k0.get("async_samples"), "async_samples_r1": k1.get("async_samples"),
                 "lat_p50_us": k0.get("lat_p50_us"), "lat_p99_us": k0.get("lat_p99_us"), "lat_mean_us": k0.get("lat_mean_us"),
                 "lat_max_us": k0.get("lat_max_us"), "lat_max_it": k0.get("lat_max_it"), "lat_n": k0.get("lat_n"),
                 "ts_on_r0": l0["ts_on"], "ts_on_r1": l1["ts_on"], "ts_off": ";".join(l0["ts_off"] + l1["ts_off"]),
                 "n_fires_r0": len(l0["fires"]), "n_fires_r1": len(l1["fires"]),
                 "trigger_miss": l0["trigger_miss"] + l1["trigger_miss"],
                 "q4_r0": len(l0["q4"]), "q4_r1": len(l1["q4"]),
                 "q4_class_r0": ";".join(q.get("class", "") for q in l0["q4"][:4]),
                 "q4_class_r1": ";".join(q.get("class", "") for q in l1["q4"][:4]),
                 "rec_init_r0": sum(1 for x in l0["rec"] if x.get("role") == "initiator"),
                 "rec_init_r1": sum(1 for x in l1["rec"] if x.get("role") == "initiator"),
                 "rec_resp_r0": sum(1 for x in l0["rec"] if x.get("role") == "responder"),
                 "rec_resp_r1": sum(1 for x in l1["rec"] if x.get("role") == "responder"),
                 "tie_kept": l0["tie_kept"] + l1["tie_kept"], "yielded": l0["yield"] + l1["yield"],
                 "decl_r0": ";".join(l0["decl"]), "decl_r1": ";".join(l1["decl"]),
                 "quiesce_stuck": l0["quiesce_stuck"] + l1["quiesce_stuck"], "watchdog": l0["watchdog"] + l1["watchdog"],
                 "gid_moved_r0": ";".join("%d->%d@%.1fms" % g for g in l0["gid_moved"]),
                 "gid_moved_r1": ";".join("%d->%d@%.1fms" % g for g in l1["gid_moved"]),
                 "teardown_r0": k0.get("abort_ret"), "teardown_r1": k1.get("abort_ret"),
                 "teardown_ms_r0": k0.get("teardown_ms"), "teardown_ms_r1": k1.get("teardown_ms"),
                 "kernel_ms_r0": k0.get("kernel_ms"), "kernel_ms_r1": k1.get("kernel_ms")}
            r["bind_fail"] = int(os.path.exists(stem + "_r0.log") and
                                 "bind: Address already in use" in open(stem + "_r0.log", errors="replace").read())
            r["transparent_ok"] = int(rank_ok(k0, iters, True, bidir) and rank_ok(k1, iters, bidir, True))
            # the fault instant on rank 0's clock: first hook fire on either rank, the kill, or the cut start
            fire = None
            cands = list(l0["fires"][:1]) + [f - off for f in l1["fires"][:1]]
            if cands:
                fire = min(cands)
            kill = kvfile(stem + "_kill.out").get("kill_mono_ms")
            if fire is None and kill:
                fire = float(kill) - off
            cs = fnum(cut.get("cut_start_mono_ms"))
            ce = fnum(cut.get("cut_end_mono_ms"))
            if fire is None and cs is not None:
                fire = cs
            r["fire_dt_r1_minus_r0_ms"] = ((l1["fires"][0] - off) - l0["fires"][0]) if (l0["fires"] and l1["fires"]) else None
            r["fault_mono_r0"] = fire
            launch = fnum(k0.get("launch_mono_ms"))
            r["fault_after_launch_ms"] = (fire - launch) if (fire is not None and launch) else None
            r["cut_start_after_launch_ms"] = (cs - launch) if (cs is not None and launch) else None
            r["cut_len_ms"] = (ce - cs) if (cs is not None and ce is not None) else None
            r["gids_after_cut"] = cut.get("gids_after")
            q0 = fnum(l0["q4"][0].get("mono_ms")) if l0["q4"] else None
            q1 = fnum(l1["q4"][0].get("mono_ms")) - off if l1["q4"] else None
            qs = [q for q in (q0, q1) if q is not None]
            q = min(qs) if qs else None
            r["first_q4_class"] = (l0["q4"][0].get("class") if (q0 is not None and q == q0) else
                                   l1["q4"][0].get("class") if l1["q4"] else "")
            r["fault_to_mbx_ms"] = (q - fire) if (fire is not None and q is not None) else None
            r["cut_end_to_mbx_ms"] = (q - ce) if (ce is not None and q is not None) else None
            if l0["decl_mono"] is not None and fire is not None:
                r["fault_to_decline_ms"] = l0["decl_mono"] - fire
            # recovery rounds (both ranks; times on rank 0's clock)
            first_res = None
            for rk, lg, o in (("r0", l0, 0.0), ("r1", l1, off)):
                for i, x in enumerate(lg["rec"]):
                    rr = {"stem": r["stem"], "cell": r["cell"], "rank": rk, "idx": i + 1, "role": x.get("role"),
                          "round": x.get("round")}
                    for key in ("class", "fp", "S/U/n", "replayed", "rescued", "chunks", "host_rung", "tie_kept", "yielded", "gid", "gid_wait_ms",
                                "quiesce_us", "prepare_us", "handshake_us", "commit_us", "replay_us", "total_us",
                                "mbx_to_resumed_us", "ack_to_done_us", "t_resumed"):
                        rr[key] = x.get(key)
                    res = fnum(x.get("t_resumed"))
                    if res is not None:
                        res -= o
                        rr["resumed_after_fault_ms"] = (res - fire) if fire is not None else None
                        rr["resumed_after_cut_end_ms"] = (res - ce) if ce is not None else None
                        if first_res is None or res < first_res:
                            first_res = res
                    rounds.append(rr)
            r["fault_to_resumed_ms"] = (first_res - fire) if (first_res is not None and fire is not None) else None
            r["cut_end_to_resumed_ms"] = (first_res - ce) if (first_res is not None and ce is not None) else None
            r["S/U/n_first"] = next((x.get("S/U/n") for x in l0["rec"] + l1["rec"] if x.get("role") == "initiator"), None)
            rows.append(r)
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    if a.rounds:
        rk = []
        for r in rounds:
            for k in r:
                if k not in rk:
                    rk.append(k)
        with open(a.rounds, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=rk)
            w.writeheader()
            for r in rounds:
                w.writerow(r)
    print(f"{len(rows)} trials, {len(rounds)} recovery rounds", file=sys.stderr)


if __name__ == "__main__":
    main()
