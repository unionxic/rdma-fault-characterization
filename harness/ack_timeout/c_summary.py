#!/usr/bin/env python3
"""c_summary.py - GPU-stage table (Task C) from the gin_q4 CSVs and the nvshmem_ft rows.

usage: c_summary.py results/20260925/C
  expects gin_<label>_T<T>.csv (written by gin_q4's q4_row.py through scripts/gpu_gin.sh) and
  nvshmem_trials.csv (written by nvshmem_ft's rows.py over the nvshmem_<label>_T<T>_rec0 dirs).
Times are ms after the fault on rain's CLOCK_MONOTONIC, as the two stacks' own tools compute them
(except "failing op posted -> error": GIN = the driver's device_rc_ms, start of the failing
iteration -> device wait returned the error, host-observed with a 0.5 ms poll; NVSHMEM = the
events' post_to_dev_ms, post of the failing put -> device record):
  GIN:     t_dev (device record %globaltimer), t_mbx (host watcher read the record = host-visible
           fingerprint), t_api (first non-success ncclCommGetAsyncError)
  NVSHMEM: fault->device, fault->mailbox (host watcher read the record = host-visible fingerprint)
"""
import csv
import glob
import os
import re
import statistics as st
import sys

D = sys.argv[1]


def rng(xs, nd=1):
    xs = [x for x in xs if x is not None]
    if not xs:
        return "-"
    return f"{st.median(xs):.{nd}f} [{min(xs):.{nd}f}-{max(xs):.{nd}f}]"


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


print("| stack | floor | IB timeout T | N | class (fingerprint) | failing op posted -> error (ms) | fault -> device detection (ms) | fault -> host-visible fingerprint (ms) | fault -> API error (ms) | teardown / leftover |")
print("|---|---|---|---|---|---|---|---|---|---|")
for p in sorted(glob.glob(f"{D}/gin_*_T*.csv"), key=lambda s: (s.split("_")[-2], int(re.search(r"_T(\d+)", s).group(1)))):
    m = re.search(r"gin_(\w+?)_T(\d+)\.csv", os.path.basename(p))
    label, T = m.group(1), m.group(2)
    rs = list(csv.DictReader(open(p)))
    cls = sorted(set(f"{r['q4_class']} {r['q4_status']}/{r['q4_vendor']}" for r in rs))
    td = sorted(set(r["teardown"] for r in rs))
    post = []
    for r in rs:
        kv = f"{D}/logs/{r['cq_type']}_c{r['classify']}_{r['fault']}_{r['wait_mode']}_t{r['trial']}_r0.kv"
        m2 = re.search(r"device_rc_ms=([0-9.]+)", open(kv).read()) if os.path.exists(kv) else None
        post.append(float(m2.group(1)) if m2 else None)
    left = sum(int(r["leftover_procs"] or 0) for r in rs)
    print(f"| GIN GDAKI + Q4 | {label} | {T} | {len(rs)} | {', '.join(cls)} ({sum(r['q4_class'] == 'RETRY_EXC' for r in rs)}/{len(rs)}) | "
          f"{rng(post)} | {rng([fnum(r['t_dev_ms']) for r in rs])} | {rng([fnum(r['t_mbx_ms']) for r in rs])} | "
          f"{rng([fnum(r['t_api_ms']) for r in rs])} | {','.join(td)} / {left} |")

nv = f"{D}/nvshmem_trials.csv"
if os.path.exists(nv):
    rs = list(csv.DictReader(open(nv)))
    evp = {}
    if os.path.exists(f"{D}/nvshmem_events.csv"):
        for e in csv.DictReader(open(f"{D}/nvshmem_events.csv")):
            if e["round"] == "0":
                evp[(e["dir"], e["tag"])] = fnum(e["post_to_dev_ms"])
    groups = {}
    for r in rs:
        m = re.search(r"nvshmem_(\w+?)_T(\d+)_rec(\d)", r["dir"])
        groups.setdefault((m.group(1), int(m.group(2))), []).append(r)
    for (label, T) in sorted(groups):
        g = groups[(label, T)]
        cls = sorted(set(f"{r['first_class']} {r['first_fp']}" for r in g))
        print(f"| NVSHMEM IBGDA + FT | {label} | {T} | {len(g)} | {', '.join(cls)} ({sum(r['first_class'] == 'RETRY_EXC' for r in g)}/{len(g)}) | "
              f"{rng([evp.get((r['dir'], r['tag'])) for r in g])} | "
              f"{rng([fnum(r['first_fault_to_dev_ms']) for r in g])} | {rng([fnum(r['first_fault_to_mbx_ms']) for r in g])} | - | "
              f"{','.join(sorted(set(r['teardown0'] + '/' + r['teardown1'] for r in g)))} / {','.join(sorted(set(r['leftover'] for r in g)))} |")
