#!/usr/bin/env python3
"""Independent recount of teardown_channel Q1-Q6 from raw files (not score.py / SCORE.md)."""
import csv, os, re, sys

R = "/home/unionxic/rdma-error-wt/teardown-channel/harness/gpu-initiated/nvshmem_rootcause/teardown_channel/results/20261007"
LOOP_LO, LOOP_HI = 0x1ee0, 0x1f70  # DEVIATIONS.md item 1


def rd(p):
    try:
        with open(p, errors="replace") as f:
            return f.read()
    except FileNotFoundError:
        return None


def fin(log, pe):
    if log is None:
        return ("missing", None)
    m = re.search(rf"^PE {pe}: nvshmem_finalize returned after ([0-9.]+) ms", log, re.M)
    if m:
        return ("returned", float(m.group(1)))
    if re.search(rf"^PE {pe}: nvshmem_finalize did not return after 30 s", log, re.M):
        return ("no_return_30s", None)
    if re.search(rf"^PE {pe}: .*calling nvshmem_finalize", log, re.M):
        return ("called_no_outcome", None)
    return ("not_called", None)


def main_stack(gdb, pid):
    """frames (list of function names) of the thread whose LWP == pid."""
    if gdb is None:
        return None
    blocks = re.split(r"\n(?=Thread \d+ \()", gdb)
    for b in blocks:
        m = re.match(r"Thread \d+ \(Thread 0x[0-9a-f]+ \(LWP (\d+)\)", b)
        if m and m.group(1) == str(pid):
            frames = []
            for line in b.splitlines():
                fm = re.match(r"#(\d+)\s+(?:0x[0-9a-f]+ in )?(.+?) (?:\(|from|at)", line)
                if fm:
                    frames.append((int(fm.group(1)), fm.group(2)))
            return frames
    return None


rows = list(csv.DictReader(open(os.path.join(R, "trials.csv"))))
out = []
for r in rows:
    var = r["variant"]; h = r["handler_env"]; k = r["kill"]; t = r["trial"]
    tag = f"{var}_{h}_kill{k}_t{t}"
    p = lambda ext: os.path.join(R, f"{tag}.{ext}")
    L0, L1 = rd(p("pe0.log")), rd(p("pe1.log"))
    cap = rd(p("capture")) or ""
    d = dict(tag=tag, cell=f"{var}/{h}/kill{k}", kill_at=r["kill_at"], csv_cap=r["capture"])
    d["pe0_fin"], d["pe0_ms"] = fin(L0, 0)
    d["pe1_fin"], d["pe1_ms"] = fin(L1, 1)
    it0 = re.findall(r"^PE 0 iter (\d+): (.*)$", L0 or "", re.M)
    d["pe0_iters"] = len(it0)
    d["pe0_maxms"] = max([float(x) for _, s in it0 for x in re.findall(r"returned after ([0-9.]+) ms", s)] or [0])
    d["pe0_hang"] = any("has not returned" in s for _, s in it0)
    it1 = re.findall(r"^PE 1 iter (\d+):", L1 or "", re.M)
    d["pe1_last_iter"] = int(it1[-1]) if it1 else None
    # fault applied? kill_at set and PE 1 stopped before finishing 40 iterations
    d["fault_applied"] = (r["kill_at"] != "-") and (d["pe1_last_iter"] is not None and d["pe1_last_iter"] < 39)
    pm = re.search(r"capture_at \S+ pid (\d+)", cap)
    pid = pm.group(1) if pm else None
    d["gdb_rc"] = (re.search(r"gdb_rc (\d+)", cap) or [None, None])[1]
    d["cudagdb_rc"] = (re.search(r"cudagdb_rc (\d+)", cap) or [None, None])[1]
    gdb = rd(p("gdb.txt"))
    st = main_stack(gdb, pid) if pid else None
    d["gdb_observable"] = st is not None and len(st) > 0
    if st:
        names = [n for _, n in st]
        idx = lambda pat: next((i for i, n in enumerate(names) if re.search(pat, n)), None)
        ib, ifin, isync = idx(r"^nvshmemi_barrier\b"), idx(r"^nvshmemi_finalize\b"), idx(r"^cudaStreamSynchronize\b")
        d["main_top_nvshmem"] = " < ".join(n for n in names if "nvshmem" in n or "cuda" in n.lower() or n in ("main",))
        d["has_barrier_under_fin"] = ib is not None and ifin is not None and ib < ifin
        d["has_cudasync"] = isync is not None and (ib is None or isync < ib)
        d["main_has_bootstrap_barrier"] = idx(r"bootstrap_uid_barrier") is not None
        d["main_has_transport_fin"] = idx(r"nvshmemi_transport_finalize") is not None
        d["any_thread_bootstrap_or_transport_fin"] = bool(re.search(r"bootstrap_uid_barrier|nvshmemi_transport_finalize|bootstrap_.*barrier", gdb))
        others = re.findall(r"#0\s+0x[0-9a-f]+ in (\S+?)\(", gdb)
        d["thread_tops"] = sorted(set(others))
    cg = rd(p("cudagdb.txt"))
    if cg:
        kern = re.findall(r"^\*?\s+\d+\s+-\s+\d+\s+(\d+)\s+Active\s+\S+\s+\S+\s+\S+\s+(\S+?)\(", cg, re.M)
        d["cuda_kernels"] = [f"grid{g}:{n}" for g, n in kern]
        foc = re.search(r"\[Switching focus to CUDA kernel \d+, grid (\d+).*lane 0\]\n0x[0-9a-f]+ in (.+?) \(\)", cg)
        d["lane0_func"] = foc.group(2) if foc else None
        offs = re.findall(r"^=> 0x[0-9a-f]+ <(\S+)\+(\d+)>:\s+(.*)$", cg, re.M)
        d["lane0_off"] = hex(int(offs[0][1])) if offs else None
        d["lane0_sym"] = offs[0][0] if offs else None
        d["lane0_insn"] = offs[0][2] if offs else None
        l1 = re.search(r"lane 1\]\n0x[0-9a-f]+ in (\S+)", cg)
        d["lane1_func"] = l1.group(1) if l1 else ("invalid coords" if "Invalid coordinates" in cg else None)
        d["cuda_attached"] = bool(kern)
        d["in_loop"] = bool(offs) and "barrier_on_stream_kernel_threadgroup" in offs[0][0] and LOOP_LO <= int(offs[0][1]) <= LOOP_HI
    st_txt = rd(p("strace.txt"))
    if st_txt is not None:
        calls = set()
        for line in st_txt.splitlines():
            m = re.match(r"^\d+\s+\S+\s+(?:<\.\.\. )?([a-z_0-9]+)", line)
            if m:
                calls.add(m.group(1))
        d["strace_calls"] = sorted(calls)
        d["strace_recv"] = sorted(c for c in calls if re.match(r"(recv|recvfrom|recvmsg|recvmmsg|read|readv|accept4?)$", c))
        d["strace_lines"] = len(st_txt.splitlines())
    d["gpuutil"] = (rd(p("gpuutil")) or "").strip()
    out.append(d)

import json
json.dump(out, open(os.path.join(os.path.dirname(__file__), "trials_parsed.json"), "w"), indent=1)

KILL_SYNC = ["stock/gpu/kill1", "fix/cpu_host_memory/kill1"]
def judge(name, cells, pred, needs):
    for c in cells:
        tr = [d for d in out if d["cell"] == c]
        obs = [d for d in tr if needs(d) is not None]
        hits = [d for d in obs if needs(d)]
        miss = [d["tag"] for d in obs if not needs(d)]
        nob = [d["tag"] for d in tr if needs(d) is None]
        print(f"{name} {c}: n={len(tr)} observable={len(obs)} hits={len(hits)} miss={miss} not_observable={nob}")

def q1(d):
    if not d["fault_applied"]: return None
    return d["pe0_fin"] == "no_return_30s"
def q2(d):
    if not d.get("gdb_observable"): return None
    return d["has_barrier_under_fin"] and d["has_cudasync"] and not d["main_has_bootstrap_barrier"] and not d["main_has_transport_fin"]
def q3(d):
    if not d.get("cuda_attached"): return None
    return d.get("lane0_func", "") and "barrier_on_stream_kernel_threadgroup" in d["lane0_func"] and d["in_loop"]
def q4(d):
    if not d.get("gdb_observable"): return None
    return d["has_barrier_under_fin"] and not d["main_has_bootstrap_barrier"]
def q5(d):
    return d["pe0_fin"] == "returned" and d["pe1_fin"] == "returned" and d["pe0_ms"] <= 5000 and d["pe1_ms"] <= 5000
def q6(d):
    if "strace_calls" not in d: return None
    return len(d["strace_recv"]) == 0

judge("Q1", KILL_SYNC, None, q1)
judge("Q2", KILL_SYNC, None, q2)
judge("Q3", KILL_SYNC, None, q3)
judge("Q4", ["stock/cpu_host_memory/kill1"], None, q4)
judge("Q5", ["stock/gpu/kill0", "fix/cpu_host_memory/kill0", "stock/cpu_host_memory/kill0"], None, q5)
judge("Q6", KILL_SYNC + ["stock/cpu_host_memory/kill1"], None, q6)

print()
for d in out:
    print(d["tag"], d["fault_applied"], d["pe1_last_iter"], d["pe0_iters"], d["pe0_maxms"], d["pe0_hang"],
          d["pe0_fin"], d["pe0_ms"], d["pe1_fin"], d["pe1_ms"], d["csv_cap"], d.get("gpuutil"))
    if d["cell"].endswith("kill1"):
        print("   gdb:", d.get("main_top_nvshmem"), "| boot/tf any thread:", d.get("any_thread_bootstrap_or_transport_fin"))
        print("   tops:", d.get("thread_tops"))
        print("   cuda:", d.get("cuda_kernels"), d.get("lane0_func"), d.get("lane0_off"), d.get("lane0_insn"), "| lane1:", d.get("lane1_func"))
        print("   strace:", d.get("strace_calls"), d.get("strace_lines"))
