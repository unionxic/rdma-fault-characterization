#!/usr/bin/env python3
"""score.py <results_dir> - score Q1-Q6 of predictions.csv from the trace_trial.sh files.

Per trial (tag = <variant>_<handler>_kill<k>_t<n>): <tag>.pe0.log, .pe1.log, .capture, .gdb.txt,
.strace.txt, .cudagdb.txt. Writes SCORE.md and trials_scored.csv into <results_dir>.
Acceptance (as in the propagation pre-registration): a cell holds if every observable trial shows
the predicted outcome; trials without the needed file are "not observable" and listed apart.
"""
import csv, glob, os, re, sys

R = os.path.abspath(sys.argv[1])
SYNC_LOOP = (0x1ee0, 0x1f70)   # results/20261007/sass_wait_loop.md
VARIANTS = {("stock", "gpu"): "GPU 처리 공식본", ("fix", "cpu_host_memory"): "CPU 프록시 수정본",
            ("stock", "cpu_host_memory"): "CPU 프록시 공식본"}


def text(p):
    try:
        return open(p, errors="replace").read()
    except FileNotFoundError:
        return None


def main_thread(gdb):
    """Stack of Thread 1 (the main thread) from 'thread apply all bt'."""
    if gdb is None:
        return None
    m = re.search(r"^Thread 1 \(.*?(?=^Thread \d+ \(|\Z)", gdb, re.S | re.M)
    return m.group(0) if m else None


def fin(log):
    if log is None:
        return None
    m = re.search(r"nvshmem_finalize returned after ([\d.]+) ms", log)
    if m:
        return float(m.group(1))
    return "hang" if "nvshmem_finalize did not return" in log else None


trials = []
for log0 in sorted(glob.glob(os.path.join(R, "*.pe0.log"))):
    tag = os.path.basename(log0)[:-len(".pe0.log")]
    m = re.match(r"(stock|fix)_(gpu|cpu_host_memory)_kill(\d)_t(\d+)$", tag)
    if not m:
        continue
    b = os.path.join(R, tag)
    l0, l1 = text(log0), text(b + ".pe1.log")
    mt = main_thread(text(b + ".gdb.txt"))
    st = text(b + ".strace.txt")
    cg = text(b + ".cudagdb.txt")
    t = dict(tag=tag, variant=(m.group(1), m.group(2)), kill=int(m.group(3)), trial=int(m.group(4)),
             fin0=fin(l0), fin1=fin(l1), killed="runner: SIGKILL PE 1" in (l0 or ""),
             all_iters="all 40 iterations returned" in (l0 or ""), quiet_hang="has not returned" in (l0 or ""))
    if mt is not None:
        t["stack_barrier"] = "nvshmemi_barrier" in mt
        t["stack_sync"] = "cudaStreamSynchronize" in mt
        t["stack_finalize"] = "finalize" in mt
        t["stack_bootstrap"] = "bootstrap_uid_barrier" in mt
        t["stack_transport_fin"] = "nvshmemi_transport_finalize" in mt
        frames = re.findall(r"#\d+\s+0x[0-9a-f]+ in (\S+)", mt)
        t["stack_named"] = " < ".join(f for f in frames if f != "??")
    if st is not None:
        calls = re.findall(r"^\d+\s+[\d:.]+\s+(?:<\.\.\. )?(\w+)", st, re.M)
        t["sock_recv"] = sum(1 for c in calls if c in ("recvfrom", "recvmsg", "recvmmsg", "recv"))
        t["read_calls"] = sum(1 for c in calls if c == "read")
        t["syscalls"] = len(calls)
    if cg is not None:
        t["kernel_barrier"] = bool(re.search(r"Active.*barrier_on_stream_kernel", cg))
        k = re.search(r"Active\s.*?\)\s+(\S+)\s*$", cg, re.M)
        t["kernel"] = k.group(1) if k else ""
        offs = re.findall(r"<([^>+]+)\+(\d+)>", cg)
        # DEVIATIONS 1: lane 0 stopped inside the sync wait loop of the warp-scope barrier kernel
        first = re.search(r"^=> 0x[0-9a-f]+ <(_Z36barrier_on_stream_kernel_threadgroupIL13threadgroup_t1EEvii)\+(\d+)>", cg, re.M)
        t["sync_step"] = None if not first else (SYNC_LOOP[0] <= int(first.group(2)) <= SYNC_LOOP[1])
        t["pc_offsets"] = ";".join(f"{f.split('(')[0][-40:]}+{o}" for f, o in offs)
    trials.append(t)


def cell(name, rows, pred):
    obs = [(r["tag"], pred(r)) for r in rows]
    unobs = [t for t, o in obs if o is None]
    seen = [(t, o) for t, o in obs if o is not None]
    hits = sum(1 for _, o in seen if o)
    misses = [t for t, o in seen if not o]
    verdict = "no data" if not seen else ("holds" if not misses and hits == len(rows) - len(unobs) else "fails")
    return dict(id=name, n=len(seen), hits=hits, misses=misses, unobservable=unobs, verdict=verdict)


def need(r, *keys):
    return all(k in r for k in keys)


killed_main = [r for r in trials if r["kill"] == 1 and r["variant"] in (("stock", "gpu"), ("fix", "cpu_host_memory"))]
results = []
for v in (("stock", "gpu"), ("fix", "cpu_host_memory")):
    rows = [r for r in killed_main if r["variant"] == v]
    results.append(cell(f"Q1 {VARIANTS[v]}", rows, lambda r: None if r["fin0"] is None else r["fin0"] == "hang"))
    results.append(cell(f"Q2 {VARIANTS[v]}", rows, lambda r: (r["stack_barrier"] and r["stack_sync"] and r["stack_finalize"]
                                                              and not r["stack_bootstrap"] and not r["stack_transport_fin"])
                        if need(r, "stack_barrier") else None))
    results.append(cell(f"Q3 {VARIANTS[v]}", rows,
                        lambda r: (r.get("kernel_barrier") and r.get("sync_step")) if r.get("sync_step") is not None else None))
rows = [r for r in trials if r["kill"] == 1 and r["variant"] == ("stock", "cpu_host_memory")]
results.append(cell(f"Q4 {VARIANTS[('stock', 'cpu_host_memory')]}", rows,
                    lambda r: (r["stack_barrier"] and r["stack_finalize"] and not r["stack_bootstrap"])
                    if need(r, "stack_barrier") else None))
for v in VARIANTS:
    rows = [r for r in trials if r["kill"] == 0 and r["variant"] == v]
    results.append(cell(f"Q5 {VARIANTS[v]}", rows,
                        lambda r: None if r["fin0"] is None or r["fin1"] is None else
                        (isinstance(r["fin0"], float) and isinstance(r["fin1"], float) and r["fin0"] <= 5000 and r["fin1"] <= 5000)))
for v in VARIANTS:
    rows = [r for r in trials if r["kill"] == 1 and r["variant"] == v]
    results.append(cell(f"Q6 {VARIANTS[v]}", rows, lambda r: r["sock_recv"] == 0 if "sock_recv" in r else None))

keys = ["tag", "fin0", "fin1", "killed", "all_iters", "quiet_hang", "stack_named", "sock_recv", "read_calls",
        "syscalls", "kernel", "sync_step", "pc_offsets"]
with open(os.path.join(R, "trials_scored.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(keys)
    for r in trials:
        w.writerow([r.get(k, "") for k in keys])
with open(os.path.join(R, "SCORE.md"), "w") as f:
    f.write("# teardown_channel score\n\nScored by `score.py` against `predictions.csv` "
            "(tag prereg/teardown-channel-v1). Per-trial values: `trials_scored.csv`.\n\n")
    f.write("| cell | n | hits | verdict | misses | not observable |\n|---|--:|--:|---|---|---|\n")
    for c in results:
        f.write(f"| {c['id']} | {c['n']} | {c['hits']} | **{c['verdict']}** | {', '.join(c['misses'])} | "
                f"{', '.join(c['unobservable'])} |\n")
print(open(os.path.join(R, "SCORE.md")).read())
