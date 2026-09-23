#!/usr/bin/env bash
set -u
R="/home/unionxic/rdma-error/harness/gpu-initiated/nvshmem/results/20260923"; RT="/home/unionxic/rdma-error/harness/gpu-initiated/nvshmem/run_trial.sh"; O="$R/ab"
P=/sys/class/infiniband/mlx5_1/ports/1/counters
( echo "wall_s xmit_pkts rcv_pkts"
  while [ ! -f "$O/.stop" ]; do
    echo "$(date +%s.%N) $(cat $P/port_xmit_packets) $(cat $P/port_rcv_packets)"
    sleep 0.5
  done ) > "$O/rain_counters.txt" &
SP=$!
run() {  # cc fault trial extra_env...
  local cc=$1 fault=$2 t=$3; shift 3
  echo "$(date +%s.%N) START cc=$cc fault=$fault trial=$t" >> "$O/timeline.txt"
  env NVSHMEM_IBGDA_FAULT_CQ_COLLAPSED=$cc ITERS=1 PROC_TIMEOUT=45 NVSHMEM_FAULT_WATCHDOG_S=30 \
      WATCH_MS=300 WATCH_QPONLY=1 WATCH_DELAY_MS=100 "$@" \
      bash "$RT" "$fault" timeout "cc${cc}_${t}" "$O" >/dev/null
  echo "$(date +%s.%N) END   cc=$cc fault=$fault trial=$t" >> "$O/timeline.txt"
}
for cc in 1 0; do
  for t in 1 2 3; do
    run $cc none  $t DEV_TIMEOUT_MS=5000
    run $cc F1    $t DEV_TIMEOUT_MS=5000 FAULT_MS=300 PREFAULT_MS=900
    run $cc F2b   $t DEV_TIMEOUT_MS=10000 CORRUPT_AT=0
    run $cc F3    $t DEV_TIMEOUT_MS=10000 FAULT_MS=300 PREFAULT_MS=900
  done
done
touch "$O/.stop"; wait $SP 2>/dev/null
echo "abbatch done"
