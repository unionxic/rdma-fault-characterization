#!/usr/bin/env python3
"""S1 trial logs -> one CSV row per trial (recomputed from the raw per-trial files only).

usage: rows.py <logdir> [<logdir> ...] --out trials.csv [--rounds rounds.csv]

A trial is <stem>_meta.txt with <stem>_r{0,1}.{kv,log}. Everything below is read from those files:
  meta   runner line (fault, wait, ts, base, diag, rc, left, wall)
  r0.kv  tx_done / tx_rc / lat_* / async_* / outcome / clock_offset_ms / launch_mono_ms
  r1.kv  rx_done / rx_rc / dev_bad_slots / host_bad_slots / final_signal / signal_exact / async_* / outcome
  logs   NCCL WARN lines: GIN/FAULT fired (fire_mono_ms), GIN/Q4 device-classified error CQE (class, fp,
         mono_ms = when the watcher read it), GIN/TS recovered (role, timings, S/U/n), GIN/TS declined.
"""
import argparse, csv, glob, os, re, sys


def kvfile(path):
    d = {}
    if not os.path.exists(path):
        return d
    for line in open(path, errors="replace"):
        # values may contain spaces ("no error"): a value runs until the next " key=" or the line end
        for m in re.finditer(r"(\w+)=(.*?)(?= \w+=|$)", line.rstrip("\n")):
            d[m.group(1)] = m.group(2).strip().strip('"')
    return d


def fnum(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def parse_log(path):
    out = {"fires": [], "q4": [], "rec": [], "decl": [], "ts_on": 0, "ts_off": [], "gin_err_warn": 0,
           "watchdog": [], "test_stall": [], "test_die": [], "split": None, "teardown": None}
    if not os.path.exists(path):
        return out
    for line in open(path, errors="replace"):
        if "GIN/FAULT: GDAKI fault fired" in line:
            m = re.search(r"fire_mono_ms=([\d.]+)", line)
            if m:
                out["fires"].append(float(m.group(1)))
        elif "device-classified error CQE" in line:
            d = dict(re.findall(r"(\w+)=(\S+)", line))
            out["q4"].append(d)
        elif "GIN/TS: recovered" in line:
            d = dict(re.findall(r"([\w/]+)=(\[[^\]]*\]|\S+)", line))
            out["rec"].append(d)
        elif "GIN/TS: declined" in line:
            m = re.search(r'reason="([^"]*)"', line)
            out["decl"].append(m.group(1) if m else "?")
            m = re.search(r"mono_ms=([\d.]+)", line)
            if m and "decl_mono" not in out:
                out["decl_mono"] = float(m.group(1))
        elif "GIN/TS: transparent recovery ON" in line:
            out["ts_on"] += 1
        elif "GIN/TS: transparent recovery OFF" in line:
            out["ts_off"].append(line.strip()[-120:])
        elif "GIN Error detected" in line:
            out["gin_err_warn"] += 1
        elif "GIN/TS: watchdog" in line:
            m = re.search(r"mono_ms=([\d.]+)", line)
            out["watchdog"].append(float(m.group(1)) if m else None)
        elif "GIN/TS: TEST stall" in line:
            m = re.search(r"mono_ms=([\d.]+)", line)
            out["test_stall"].append(float(m.group(1)) if m else None)
        elif "GIN/TS: TEST helper thread exits" in line:
            m = re.search(r"mono_ms=([\d.]+)", line)
            out["test_die"].append(float(m.group(1)) if m else None)
        elif "GIN/TS: communicator teardown" in line:
            d = dict(re.findall(r"(\w+)=(-?[\d.]+)", line))
            m = re.search(r"joined in ([\d.]+) ms", line)
            m2 = re.search(r"gates poisoned=(\d+) failed=(\d+)", line)
            out["teardown"] = {"join_ms": float(m.group(1)) if m else None,
                               "round": int(d.get("round_in_progress", -1)), "queued": int(d.get("queued", -1)),
                               "dead": int(d.get("helper_dead", -1)),
                               "poisoned": int(m2.group(1)) if m2 else None, "poison_failed": int(m2.group(2)) if m2 else None}
        elif "GIN/TS: TEST split rank" in line:
            m = re.search(r"nsplit=(\d+) no_ack=(\d+)", line)
            if m:
                out["split"] = (int(m.group(1)), int(m.group(2)))
    return out


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
            off = fnum(k0.get("clock_offset_ms"), 0.0)  # rank1 - rank0
            iters = int(m.get("iters", "0"))
            r = {
                "dir": os.path.basename(os.path.normpath(d)), "stem": os.path.basename(stem),
                "cell": m.get("cell") or os.path.basename(stem).rsplit("_", 1)[0],
                "fault": m.get("fault"), "wait": m.get("wait"), "trial": m.get("trial"), "ts": m.get("ts"),
                "base": m.get("base"), "diag": m.get("diag", ""), "bytes": m.get("bytes"), "iters": iters,
                "r0rc": m.get("r0rc"), "r1rc": m.get("r1rc"), "left": m.get("left"), "wall_s": m.get("wall_s"),
                "r0_outcome": k0.get("outcome"), "r1_outcome": k1.get("outcome"),
                "tx_done": k0.get("tx_done"), "tx_rc": k0.get("tx_rc"), "tx_rc_it": k0.get("tx_rc_it"),
                "rx_done": k1.get("rx_done"), "rx_rc": k1.get("rx_rc"),
                "dev_bad_slots": k1.get("dev_bad_slots"), "host_bad_slots": k1.get("host_bad_slots"),
                "host_missing_slots": k1.get("host_missing_slots"),
                "final_signal": k1.get("final_signal"), "expected_final": k1.get("expected_final"),
                "signal_exact": k1.get("signal_exact"),
                "r0_async": k0.get("async_first"), "r1_async": k1.get("async_first"),
                "r0_async_ms": k0.get("async_first_ms_after_launch"), "r1_async_ms": k1.get("async_first_ms_after_launch"),
                "r0_gin_err_warn": l0["gin_err_warn"], "r1_gin_err_warn": l1["gin_err_warn"],
                "lat_p50_us": k0.get("lat_p50_us"), "lat_p99_us": k0.get("lat_p99_us"), "lat_mean_us": k0.get("lat_mean_us"),
                "lat_max_us": k0.get("lat_max_us"), "lat_max_it": k0.get("lat_max_it"), "lat_n": k0.get("lat_n"),
                "ts_on_r0": l0["ts_on"], "ts_on_r1": l1["ts_on"],
                "n_fires_r0": len(l0["fires"]), "n_fires_r1": len(l1["fires"]),
                "n_q4_r0": len(l0["q4"]), "q4_class": ";".join(q.get("class", "") for q in l0["q4"]),
                "q4_fp": ";".join(q.get("fp", "") for q in l0["q4"]),
                "n_rec_init": sum(1 for x in l0["rec"] if x.get("role") == "initiator"),
                "n_rec_resp": sum(1 for x in l1["rec"] if x.get("role") == "responder"),
                "decl_r0": ";".join(l0["decl"]), "decl_r1": ";".join(l1["decl"]),
                "teardown_r0": k0.get("abort_ret"), "teardown_r1": k1.get("abort_ret"),
                "launch_r0": k0.get("launch_mono_ms"), "kernel_ms_r0": k0.get("kernel_ms"),
                "kernel_ms_r1": k1.get("kernel_ms"), "teardown_ms_r0": k0.get("teardown_ms"),
                "teardown_ms_r1": k1.get("teardown_ms"),
                "tx_err_n": k0.get("tx_err_n"), "tx_err_first_lat_us": k0.get("tx_err_first_lat_us"),
                "tx_err_later_max_lat_us": k0.get("tx_err_later_max_lat_us"),
                "r0_async_first_ms": k0.get("async_first_ms_after_launch"),
                "split_n": l0["split"][0] if l0["split"] else None,
                "split_noack": l0["split"][1] if l0["split"] else None,
                "n_watchdog_r0": len(l0["watchdog"]), "r1_q4": len(l1["q4"]),
                "r0env": m.get("r0env", ""),
                "kernel_exit_after_async_ms": k0.get("kernel_exit_after_async_ms"),
                "post_abort_running_r0": k0.get("post_abort_kernel_running_at_abort_return"),
                "post_abort_state_r0": k0.get("post_abort_state"), "post_abort_exit_ms_r0": k0.get("post_abort_exit_ms"),
                "post_abort_state_r1": k1.get("post_abort_state"),
            }
            for rk, lg in (("r0", l0), ("r1", l1)):
                td = lg["teardown"]
                r["td_" + rk] = int(td is not None)
                r["td_join_ms_" + rk] = td["join_ms"] if td else None
                r["td_round_" + rk] = td["round"] if td else None
                r["td_poisoned_" + rk] = td["poisoned"] if td else None
                r["td_poison_failed_" + rk] = td["poison_failed"] if td else None
            # a trial whose driver could not bind its own rendezvous port never reached NCCL (harness failure)
            r0log = stem + "_r0.log"
            r["bind_fail"] = int(os.path.exists(r0log) and "bind: Address already in use" in open(r0log, errors="replace").read())
            # transparent success: every flush ok, every slot exact, final signal exact, no async error anywhere
            r["transparent_ok"] = int(
                r["r0_outcome"] == "ok" and r["r1_outcome"] == "ok" and r["tx_done"] == str(iters)
                and r["rx_done"] == str(iters) and r["tx_rc"] == "no error" and r["rx_rc"] == "no error"
                and r["dev_bad_slots"] == "0" and r["host_bad_slots"] == "0" and r["signal_exact"] == "1"
                and r["r0_async"] == "none" and r["r1_async"] == "none")
            # fault time on rank 0's clock
            fire = None
            if l0["fires"]:
                fire = l0["fires"][0]
            elif l1["fires"]:
                fire = l1["fires"][0] - off
            kill = kvfile(stem + "_kill.out").get("kill_mono_ms")
            if fire is None and kill:
                fire = float(kill) - off
            r["fault_mono_r0"] = fire
            launch = fnum(k0.get("launch_mono_ms"))
            r["fault_after_launch_ms"] = (fire - launch) if (fire is not None and launch) else None
            q4ms = fnum(l0["q4"][0].get("mono_ms")) if l0["q4"] else None
            r["fault_to_mbx_ms"] = (q4ms - fire) if (fire is not None and q4ms) else None
            # per recovery round (initiator lines on rank 0)
            for i, x in enumerate(l0["rec"]):
                if x.get("role") != "initiator":
                    continue
                rr = {"stem": r["stem"], "cell": r["cell"], "fault": r["fault"], "wait": r["wait"], "bytes": r["bytes"],
                      "round": i + 1}
                for key in ("class", "fp", "S/U/n", "replayed", "quiesce_us", "prepare_us", "handshake_us",
                            "commit_us", "replay_us", "total_us", "mbx_to_resumed_us", "peer_quiesce_us",
                            "peer_prepare_us", "peer_commit_us", "t_mbx", "t_resumed", "rmsn_peer0"):
                    rr[key] = x.get(key)
                res = fnum(x.get("t_resumed"))
                rr["fault_to_resumed_ms"] = (res - fire) if (fire is not None and res and i == 0) else None
                rounds.append(rr)
            if l0["rec"]:
                x = l0["rec"][0]
                res = fnum(x.get("t_resumed"))
                r["fault_to_resumed_ms"] = (res - fire) if (fire is not None and res) else None
                r["mbx_to_resumed_us"] = x.get("mbx_to_resumed_us")
                r["S/U/n"] = x.get("S/U/n")
                # exactly-once boundary (split cell): the k-th put's WRITE executed, its ADD did not ->
                # S = 2k WQEs posted in the epoch, U = 2k-1 executed, n = 1 re-posted (the ADD alone)
                ms = re.search(r"NCCL_GIN_TS_TEST_SPLIT=(\d+)", m.get("r0env", ""))
                su = re.match(r"\[(\d+)/(\d+)/(\d+)", x.get("S/U/n") or "")
                if ms and su:
                    kk = int(ms.group(1)); S_, U_, n_ = (int(v) for v in su.groups())
                    r["split_k"] = kk
                    r["split_boundary"] = int(S_ == 2 * kk and U_ == 2 * kk - 1 and n_ == 1)
            wd = l0["watchdog"][0] if l0["watchdog"] else None
            st0 = (l0["test_stall"] or l0["test_die"] or [None])[0]
            r["stall_to_watchdog_ms"] = (wd - st0) if (wd is not None and st0 is not None) else None
            r["fault_to_watchdog_ms"] = (wd - fire) if (wd is not None and fire is not None) else None
            r["mbx_to_watchdog_ms"] = (wd - q4ms) if (wd is not None and q4ms) else None
            if l0.get("decl_mono") is not None and fire is not None:
                r["fault_to_decline_ms"] = l0["decl_mono"] - fire
            if l0.get("decl_mono") is not None and q4ms:
                r["mbx_to_decline_ms"] = l0["decl_mono"] - q4ms
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
    print(f"{len(rows)} trials, {len(rounds)} initiator rounds", file=sys.stderr)


if __name__ == "__main__":
    main()
