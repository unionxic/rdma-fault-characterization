#!/bin/bash
# Baselines for the cost of recovery, one table: normal path (ab.sh gin 10: ring_exchange base vs this build), init/teardown
# times and per-process memory (accept.sh S5 and S5-4 with DESTROY=1, base vs this build), how long the application waits on
# a fault today (accept.sh S1f S1s S2f S2s S3 S3b, this build only: the base build has no #2483 fix), and the error thread's CPU.
# usage: baseline.sh [reps=5] [ab] [init] [lat]   (no part named: all three; run on rain inside the cluster lock)
#        BL=<runs/baseline-... folder> adds the parts to an earlier folder, so they can run in separate lock slots; the table covers all.
R=$HOME/rdma-recovery; M=$HOME/opt/openmpi-4.1.8; N=${1:-5}; shift; P=${*:-ab init lat}
BL=${BL:-$R/runs/baseline-$(date +%Y%m%d-%H%M%S)}; mkdir -p $BL
B=$R/base/nccl/build # the test program against the unmodified release, flags as in repro/build.sh, on both hosts
C="cd $R/repro && { [ gin_fault_base -nt gin_fault.cu ] || /usr/local/cuda/bin/nvcc -std=c++17 -O2 -gencode arch=compute_70,code=sm_70 \
  -gencode arch=compute_80,code=sm_80 -Wno-deprecated-gpu-targets -I$B/include -I$M/include gin_fault.cu -o gin_fault_base -L$B/lib -lnccl \
  -L$M/lib -lmpi -Xlinker -rpath -Xlinker $B/lib -Xlinker -rpath -Xlinker $M/lib; }"
bash -c "$C" && ssh sunny "$C" || exit 1
acc() { bash $R/accept.sh "$@" | tail -1 | sed 's/^verdict lines: //; s#/verdicts.txt$##' >> $BL/folders.txt; }
for p in $P; do case $p in
  ab) EXTRA="-x NCCL_DEBUG=WARN" bash $R/ab.sh gin 10 | tail -1 > $BL/ab-folder.txt;;
  init) CQS=0 CTRS=0 XTRA="-x DESTROY=1 -x NCCL_SET_THREAD_NAME=1" acc bl-head $N S5 S5-4
        CQS=0 CTRS=0 XTRA="-x DESTROY=1 -x NCCL_SET_THREAD_NAME=1 -x RR_ROOT=$R/base" BIN=$R/repro/gin_fault_base acc bl-base $N S5 S5-4;;
  lat) CQS=0 CTRS=0 XTRA="-x NCCL_SET_THREAD_NAME=1" acc bl-lat $N S1f S1s S2f S2s S3 S3b;;
esac; done
[ -s $BL/ab-folder.txt ] && python3 $R/ab_report.py $(cat $BL/ab-folder.txt)
python3 - $(cat $BL/folders.txt 2>/dev/null) <<'EOF'
import collections, glob, re, statistics as st, sys
v = collections.defaultdict(lambda: collections.defaultdict(list))  # (scenario, build, rank) -> metric -> values
for d in sys.argv[1:]:
    build = "base" if "/accept-bl-base-" in d else "head"
    for f in glob.glob(d + "/ginfault-*/*.log"):
        sc = re.sub(r"^ginfault-|-\d{8}-\d{6}$", "", f.split("/")[-2]).split(".")[0]
        for line in open(f, errors="replace"):
            w = line.split()
            kv = dict(x.split("=", 1) for x in w[1:] if "=" in x)
            if w[:1] == ["TIMES"] or w[:1] == ["MEM"]:
                for m, x in kv.items():
                    if m != "rank" and x: v[(sc, build, "rank" + kv["rank"])][m].append(float(x.rstrip("kB")) / (1024 if x.endswith("kB") else 1))
            elif w[:1] == ["ERRTHREAD"]: v[(sc, build, "rank0")]["errthread_cpu_us"].append(int(w[1].split("=")[1].split(",")[0]) / 1e3)
    for line in open(d + "/verdicts.txt"):
        kv = dict(x.split("=", 1) for x in line.split() if "=" in x)
        ff, fa, lc = (float(kv.get(k) or -1) for k in ("first_fail_ms", "fault_ms", "longest_call_ms"))
        if fa >= 0 and ff >= 0: v[(line.split(".")[0], build, "rank0")]["fault_to_first_fail_ms"].append(ff - fa)
        if fa >= 0: v[(line.split(".")[0], build, "rank0")]["longest_call_ms"].append(lc)
print("median [min-max] n per metric; *_ms ms, Vm* MiB, gpu_mib MiB (nvidia-smi), errthread_cpu_us: each NCCL GIN Err thread of rank 0")
for k in sorted(v):
    print(" ".join(k), " ".join(f"{m}={st.median(x):.1f}[{min(x):.1f}-{max(x):.1f}]n{len(x)}" for m, x in v[k].items()))
EOF
echo $BL
