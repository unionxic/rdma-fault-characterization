#!/usr/bin/env python3
"""q4_row.py - turn one Q4 trial's KV files and logs into one CSV row.

All times are placed on rank 0's CLOCK_MONOTONIC (ms):
  fault      F1: hook fire_mono_ms (rank0 log); F3: hook fire_mono_ms (rank1 log) - offset;
             F2: fault_mono_ms (rank0 KV, just before the first out-of-bounds put launch);
             F4: kill_mono_ms (taken on sunny by the killing process) - offset.
  dev        device detection = mailbox record gtimer_ns converted with gt_off_ns
             (%globaltimer - CLOCK_MONOTONIC, calibrated by the driver at start).
  mbx        host watcher read the record (mono_ms in the GIN/Q4 WARN line).
  rc         host saw the kernel return the error code (device_rc_mono_ms, rank0 KV).
  api        first non-success ncclCommGetAsyncError (either rank, driver poll).
t_* = time - fault. offset = rank1_clock - rank0_clock (min-RTT ping-pong, rank0 KV).
"""
import argparse, csv, os, re

COLS = ["stack", "backend", "cq_type", "classify", "fault", "wait_mode", "trial",
        "init_outcome", "target_outcome", "data_check", "silent_success", "init_silent_iters",
        "iters_ok_r0", "iters_ok_r1", "device_rc", "host_error", "surface_by",
        "fault_ms", "t_dev_ms", "t_mbx_ms", "t_rc_ms", "t_api_ms",
        "q4_nrec", "q4_ndump", "q4_class", "q4_fault", "q4_status", "q4_vendor", "q4_syndrome", "q4_qpn", "q4_wqe",
        "q4_path", "q4_cq", "q4_root_op", "q4_polled", "q4_window", "q4_buffer_err",
        "dump_class", "dump_polled", "dump_window", "dump_buffer_err", "late_reread",
        "host_query", "qpwatch_err_ms", "stock_gin_error", "teardown", "leftover_procs",
        "lat_n", "lat_p50_us", "lat_p90_us", "lat_p99_us", "lat_p999_us", "lat_max_us", "lat_mean_us", "lat_cpu_ms", "lat_wall_ms",
        "gt_spread_us", "clock_offset_ms", "notes"]


def kvload(path):
    d = {}
    try:
        for line in open(path, errors="replace"):
            for m in re.finditer(r"(\w+)=(\S+)", line):
                d[m.group(1)] = m.group(2)  # last value wins
    except OSError:
        pass
    return d


def kvall(path, key):
    out = []
    try:
        for line in open(path, errors="replace"):
            for m in re.finditer(r"\b%s=(\S+)" % key, line):
                out.append(m.group(1))
    except OSError:
        pass
    return out


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def lines(path):
    try:
        return open(path, errors="replace").read().splitlines()
    except OSError:
        return []


def parse_q4(line):
    g = lambda pat: (re.search(pat, line).group(1) if re.search(pat, line) else "")
    return {
        "seq": g(r"seq=(\d+)"), "qpn": g(r"qpn=(0x[0-9a-f]+|0)"), "wqe": g(r" wqe=(\d+)"),
        "path": g(r"path=(\S+)"), "cq": g(r"cq=(\S+)"), "fp": g(r"fp=(\S+)"), "syndrome": g(r"syndrome=(\S+)"),
        "class": g(r"class=(\S+)"), "fault": g(r" fault=(\S+)"), "root_op": g(r"root_op=(\S+)"),
        "polled": g(r"polled\[([^\]]*)\]").replace(" ", ";"), "window": g(r"window\[([^\]]*)\]").replace(" ", ";"),
        "buffer_err": g(r"cq_buffer_err=(\S+)"), "gtimer_ns": g(r"gtimer_ns=(\d+)"), "mono_ms": g(r"mono_ms=([0-9.]+)"),
    }


def main():
    ap = argparse.ArgumentParser()
    for a in ["csv", "fault", "wait", "trial", "cq", "classify", "r0kv", "r1kv", "r0log", "r1log", "kill", "r0rc",
              "r1rc", "left", "stem"]:
        ap.add_argument("--" + a, default="")
    a = ap.parse_args()
    k0, k1 = kvload(a.r0kv), kvload(a.r1kv)
    L0, L1 = lines(a.r0log), lines(a.r1log)
    r0rc, r1rc = a.r0rc, a.r1rc
    F = a.fault

    # ---- outcomes (same rules as the Q2 runner) ----
    init = k0.get("init_outcome", "unknown")
    if r0rc == "137" or (r0rc == "7" and "init_outcome" not in k0):
        init = "hang_killed"
    if F == "F4":
        target = "killed"
    elif r1rc in ("137", "7"):
        target = "hang_killed"
    elif "timeout_ms" in k1 or k1.get("device_rc") == "ncclTimeout":
        target = "timeout"
    elif k1.get("data_check") == "ok" and r1rc == "0":
        target = "ok"
    else:
        target = "error" if k1.get("data_check") else "unknown"
    data = k1.get("data_check", "n/a")
    if F == "F4":
        data = "missing"
    if target == "hang_killed":
        data = "n/a"
    silent = 1 if (init == "ok" and k1.get("data_check") in ("missing", "mismatch")) else 0
    if k0.get("silent_success") == "1" or k1.get("silent_success") == "1":
        silent = 1
    ok0 = int(k0.get("okit", 0) or 0)
    ok1 = int(k1.get("okit", 0) or 0)

    # ---- clocks ----
    t0r0, t0r1, off = fnum(k0.get("t0_mono_ms")), fnum(k1.get("t0_mono_ms")), fnum(k0.get("clock_offset_ms"))
    fire0 = next((m.group(1) for l in L0 for m in [re.search(r"fire_mono_ms=([0-9.]+)", l)] if m), None)
    fire1 = next((m.group(1) for l in L1 for m in [re.search(r"fire_mono_ms=([0-9.]+)", l)] if m), None)
    killt = None
    try:
        m = re.search(r"kill_mono_ms=([0-9.]+)", open(a.kill).read())
        killt = m.group(1) if m else None
    except OSError:
        pass
    fault = None
    if F == "F1":
        fault = fnum(fire0)
    elif F == "F3" and fire1 and off is not None:
        fault = fnum(fire1) - off
    elif F == "F2":
        fault = fnum(k0.get("fault_mono_ms"))
    elif F == "F4" and killt and off is not None:
        fault = fnum(killt) - off

    # ---- ncclCommGetAsyncError ----
    cands = []
    he0, hm0 = k0.get("host_error", "none"), fnum(k0.get("host_error_ms"))
    he1, hm1 = k1.get("host_error", "none"), fnum(k1.get("host_error_ms"))
    if he0 not in ("", "none") and hm0 is not None and hm0 >= 0 and t0r0 is not None:
        cands.append((t0r0 + hm0, he0, "r0"))
    if he1 not in ("", "none") and hm1 is not None and hm1 >= 0 and None not in (t0r1, off):
        cands.append((t0r1 + hm1 - off, he1, "r1"))
    api, host_error, surface_by = (min(cands) if cands else (None, "none", "-"))

    # ---- Q4 records (rank 0) ----
    errs = [parse_q4(l) for l in L0 if "GIN/Q4: device-classified error CQE" in l]
    dumps = [parse_q4(l) for l in L0 if "GIN/Q4: device wait-timeout dump" in l]
    e = errs[0] if errs else {}
    d = dumps[0] if dumps else {}
    gtoff = fnum(k0.get("gt_off_ns"))
    dev = (fnum(e.get("gtimer_ns")) - gtoff) / 1e6 if (e.get("gtimer_ns") and gtoff) else None
    mbx = fnum(e.get("mono_ms")) if e else None
    rc = fnum(k0.get("device_rc_mono_ms"))
    st, ve = "", ""
    if e.get("fp") and "/" in e["fp"]:
        st, ve = e["fp"].split("/", 1)
    hq = next((re.search(r"state=(\S+)", l).group(1) for l in L0 if "GIN/Q4: host QUERY_QP" in l), "")
    qw = next((fnum(re.search(r"mono_ms=([0-9.]+)", l).group(1)) for l in L0
               if "GIN/Q4: QPWATCH" in l and "-> ERR" in l), None)
    stock = "yes" if any("GIN Error detected" in l for l in L0 + L1) else "no"
    late = next((re.search(r"late\[([^\]]*)\]", l).group(1).replace(" ", ";") for l in L0
                 if "GIN/Q4: collapsed slot re-read" in l), "")

    rel = lambda t: ("%.3f" % (t - fault)) if (t is not None and fault is not None) else ""
    teardown = k0.get("teardown", "n/a")
    if r0rc == "7" and "teardown" not in k0:
        teardown = "hang"
    notes = "r0rc=%s;r1rc=%s;gintype=%s;drain_rc=%s;post_poll_ms=%s/%s;hook=%s" % (
        r0rc, r1rc, k0.get("gin_type", "?"), k0.get("drain_device_rc", ""), k0.get("post_poll_ms", ""),
        k1.get("post_poll_ms", ""),
        (re.search(r"moved (\d+/\d+)", " ".join(L0 + L1)).group(1) if re.search(r"moved (\d+/\d+)", " ".join(L0 + L1)) else "-"))
    row = {
        "stack": "nccl-gin", "backend": "gdaki", "cq_type": a.cq, "classify": a.classify, "fault": F,
        "wait_mode": a.wait, "trial": a.trial, "init_outcome": init, "target_outcome": target, "data_check": data,
        "silent_success": silent, "init_silent_iters": ok0 - ok1, "iters_ok_r0": ok0, "iters_ok_r1": ok1,
        "device_rc": k0.get("device_rc", ""), "host_error": host_error, "surface_by": surface_by,
        "fault_ms": ("%.1f" % (fault - t0r0)) if (fault is not None and t0r0 is not None) else "",
        "t_dev_ms": rel(dev), "t_mbx_ms": rel(mbx), "t_rc_ms": rel(rc), "t_api_ms": rel(api),
        "q4_nrec": len(errs), "q4_ndump": len(dumps), "q4_class": e.get("class", ""), "q4_fault": e.get("fault", ""),
        "q4_status": st, "q4_vendor": ve, "q4_syndrome": e.get("syndrome", ""), "q4_qpn": e.get("qpn", ""),
        "q4_wqe": e.get("wqe", ""), "q4_path": e.get("path", ""), "q4_cq": e.get("cq", "") or d.get("cq", ""),
        "q4_root_op": e.get("root_op", ""), "q4_polled": e.get("polled", ""), "q4_window": e.get("window", ""),
        "q4_buffer_err": e.get("buffer_err", ""),
        "dump_class": d.get("class", ""), "dump_polled": d.get("polled", ""), "dump_window": d.get("window", ""),
        "dump_buffer_err": d.get("buffer_err", ""), "late_reread": late,
        "host_query": hq, "qpwatch_err_ms": rel(qw), "stock_gin_error": stock, "teardown": teardown,
        "leftover_procs": a.left,
        "lat_n": k0.get("lat_n", ""), "lat_p50_us": k0.get("lat_p50_us", ""), "lat_p90_us": k0.get("lat_p90_us", ""),
        "lat_p99_us": k0.get("lat_p99_us", ""),
        "lat_p999_us": k0.get("lat_p999_us", ""), "lat_max_us": k0.get("lat_max_us", ""),
        "lat_mean_us": k0.get("lat_mean_us", ""), "lat_cpu_ms": k0.get("lat_cpu_ms", ""),
        "lat_wall_ms": k0.get("lat_wall_ms", ""), "gt_spread_us": k0.get("gt_cal_spread_us", ""),
        "clock_offset_ms": k0.get("clock_offset_ms", ""), "notes": notes,
    }
    if F == "lat":
        bad = kvall(a.r1kv, "lat_data_bad")
        row["data_check"] = ("ok" if bad[-1] == "0" else "mismatch") if bad else "n/a"
        row["init_outcome"] = k0.get("lat_outcome", init)
        row["target_outcome"] = k1.get("lat_outcome", target)
    new = not os.path.exists(a.csv)
    with open(a.csv, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        if new:
            w.writeheader()
        w.writerow(row)
    print("[%s] -> init=%s target=%s data=%s silent=%d init_silent=%d dev_rc=%s api=%s t_dev=%s t_mbx=%s t_rc=%s "
          "t_api=%s class=%s fp=%s/%s path=%s cq=%s polled=%s window=%s late=%s dump=%s/%s qpwatch=%s hq=%s teardown=%s "
          "left=%s lat_p50=%s lat_p99=%s" % (
              a.stem, row["init_outcome"], row["target_outcome"], row["data_check"], silent, ok0 - ok1,
              row["device_rc"], host_error, row["t_dev_ms"], row["t_mbx_ms"], row["t_rc_ms"], row["t_api_ms"],
              row["q4_class"], st, ve, row["q4_path"], row["q4_cq"], row["q4_polled"], row["q4_window"], late,
              row["dump_class"], row["dump_polled"], row["qpwatch_err_ms"], hq, teardown, a.left,
              row["lat_p50_us"], row["lat_p99_us"]))


if __name__ == "__main__":
    main()
