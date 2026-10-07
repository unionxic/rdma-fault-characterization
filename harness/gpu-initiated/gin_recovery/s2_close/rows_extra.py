#!/usr/bin/env python3
"""gin-s2-close: the columns of EXPERIMENT.md section 3.1 that ../scripts/ts2/rows.py does not produce, read from the
per-trial files (<stem>_r0.kv, _r1.kv, _r0.log, _r1.log, _kill.out).

usage: rows_extra.py <trials.csv from rows.py> <logdir> [<logdir> ...] --out <trials_ext.csv>
(score.py imports extra() and does the same for every hold directory.)

Columns (definitions fixed in EXPERIMENT.md 3.1):
  get_n, get_bad            rank 0 kv (get mode)
  ua_r0, ua_r1              WARN "GIN/TS: user devComm abort flag set" lines per rank
  n_mute_on_r0, mute_on_ms_r0
                            WARN "GIN/TS: TEST socket mute on rank=<r> peers=<n> mono_ms=<t>" (count, first mono_ms)
  n_sock_close_r0, sock_close_ms_r0, sock_close_cause_r0, sock_close_cause_r1
                            WARN "GIN/TS: rank <r>: socket to rank <p> closed cause=<NAME> mono_ms=<t>" (first line)
  decl_mono_r0              mono_ms of rank 0's first "GIN/TS: declined" line
  killed                    1 if <stem>_kill.out holds kill_mono_ms (the F4 kill happened)
  async_before_fault        1 if the first async error of either rank (kv launch_mono_ms + async_first_ms_after_launch,
                            rank 1 moved to rank 0's clock with rank 0's clock_offset_ms) is earlier than fault_mono_r0
  r1_alive_at_decline       1 if rank 1's launch_mono_ms + kernel_ms on rank 0's clock is later than decl_mono_r0 and
                            r1rc is not 137, 139 or 255
  silent_bad                1 if tx_rc == "no error" and r0_async == "none" and (dev_bad_slots > 0 or
                            host_bad_slots > 0 or signal_exact == 0 or get_bad > 0)
"""
import argparse, csv, os, re, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "ts2"))
from rows import kvfile, fnum  # noqa: E402

RE_UA = "GIN/TS: user devComm abort flag set"
RE_MUTE = re.compile(r"GIN/TS: TEST socket mute on rank=\d+ peers=\d+ mono_ms=([\d.]+)")
RE_CLOSE = re.compile(r"GIN/TS: rank \d+: socket to rank \d+ closed cause=(\S+) mono_ms=([\d.]+)")
RE_DECL = re.compile(r"GIN/TS: declined .*?mono_ms=([\d.]+)")
EXTRA_COLS = ["get_n", "get_bad", "ua_r0", "ua_r1", "n_mute_on_r0", "mute_on_ms_r0", "n_sock_close_r0",
              "sock_close_ms_r0", "sock_close_cause_r0", "sock_close_cause_r1", "decl_mono_r0", "killed",
              "async_before_fault", "r1_alive_at_decline", "silent_bad"]


def scan_log(path):
    o = {"ua": 0, "mute": [], "close": [], "decl": []}
    if not os.path.exists(path):
        return o
    for line in open(path, errors="replace"):
        if RE_UA in line:
            o["ua"] += 1
        m = RE_MUTE.search(line)
        if m:
            o["mute"].append(float(m.group(1)))
        m = RE_CLOSE.search(line)
        if m:
            o["close"].append((m.group(1), float(m.group(2))))
        if "GIN/TS: declined" in line:
            m = RE_DECL.search(line)
            if m:
                o["decl"].append(float(m.group(1)))
    return o


def num(x):
    v = fnum(x)
    return v


def extra(row, stem):
    """row: a rows.py dict (strings); stem: path prefix of the trial's files. Returns the extra columns."""
    k0, k1 = kvfile(stem + "_r0.kv"), kvfile(stem + "_r1.kv")
    l0, l1 = scan_log(stem + "_r0.log"), scan_log(stem + "_r1.log")
    e = {}
    e["get_n"] = k0.get("get_n", "")
    e["get_bad"] = k0.get("get_bad", "")
    e["ua_r0"], e["ua_r1"] = l0["ua"], l1["ua"]
    e["n_mute_on_r0"] = len(l0["mute"])
    e["mute_on_ms_r0"] = l0["mute"][0] if l0["mute"] else ""
    e["n_sock_close_r0"] = len(l0["close"])
    e["sock_close_ms_r0"] = l0["close"][0][1] if l0["close"] else ""
    e["sock_close_cause_r0"] = l0["close"][0][0] if l0["close"] else ""
    e["sock_close_cause_r1"] = l1["close"][0][0] if l1["close"] else ""
    e["decl_mono_r0"] = l0["decl"][0] if l0["decl"] else ""
    kill = kvfile(stem + "_kill.out")
    e["killed"] = 1 if kill.get("kill_mono_ms") else 0
    off = num(k0.get("clock_offset_ms"))
    asyncs = []
    for k, is_r1 in ((k0, False), (k1, True)):
        if k.get("async_first") not in (None, "", "none"):
            la, ms = num(k.get("launch_mono_ms")), num(k.get("async_first_ms_after_launch"))
            if la is not None and ms is not None and (not is_r1 or off is not None):
                asyncs.append(la + ms - (off if is_r1 else 0.0))
    fault = num(row.get("fault_mono_r0"))
    e["async_before_fault"] = 1 if (fault is not None and any(a < fault for a in asyncs)) else 0
    decl = e["decl_mono_r0"] if e["decl_mono_r0"] != "" else None
    la1, km1 = num(k1.get("launch_mono_ms")), num(k1.get("kernel_ms"))
    r1rc = num(row.get("r1rc"))
    alive = 0
    if decl is not None and la1 is not None and km1 is not None and off is not None:
        if la1 + km1 - off > decl and r1rc not in (137.0, 139.0, 255.0):
            alive = 1
    e["r1_alive_at_decline"] = alive
    def pos(x):
        v = num(x)
        return v is not None and v > 0
    bad = pos(row.get("dev_bad_slots")) or pos(row.get("host_bad_slots")) or num(row.get("signal_exact")) == 0.0 \
        or pos(e["get_bad"])
    e["silent_bad"] = 1 if (row.get("tx_rc") == "no error" and row.get("r0_async") == "none" and bad) else 0
    return e


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trials")
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    dirmap = {os.path.basename(os.path.normpath(d)): d for d in a.dirs}
    rows = list(csv.DictReader(open(a.trials)))
    for r in rows:
        r.update(extra(r, os.path.join(dirmap[r["dir"]], r["stem"])))
    keys = list(rows[0].keys()) if rows else []
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"{len(rows)} trials", file=sys.stderr)


if __name__ == "__main__":
    main()
