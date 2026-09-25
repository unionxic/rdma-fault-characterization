#!/usr/bin/env bash
# d4_traffic.sh - fresh processes with GPU-like traffic before the fault (37 x 256 KiB WRITEs,
# 15 ms apart, as the GIN driver's 37 iterations), T=14 x10 and T=20 x5, plus one back-to-back
# run at T=14 (same process) with the same traffic. Run inside cluster_run.sh.
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$1
P="-P 37:15:262144"
cells=()
for i in $(seq 1 10); do cells+=("freshW:14:7:1:$P"); done
cells+=("warmS:14:7:6:$P")
for i in $(seq 1 5); do cells+=("freshW:20:7:1:$P"); done
exec bash "$HERE/sweep_cpu.sh" "$OUT" "${cells[@]}"
