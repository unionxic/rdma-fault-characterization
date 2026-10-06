#!/usr/bin/env bash
# trace_trial.sh <stock|fix> <cpu_host_memory|gpu> <kill 0|1> <trial> <outdir>
# One ../official380/run.sh trial with FINALIZE=1. When PE 0 starts nvshmem_finalize, waits
# CAPTURE_AFTER_S (8) seconds; if finalize has not returned, records on rain:
#   GPU utilisation (nvidia-smi), all host thread stacks (gdb), 3 s of syscalls (strace -f),
#   then the running GPU kernel and its stack (cuda-gdb, best effort).
# Run it inside ../../common/cluster_run.sh. Prints run.sh's CSV row plus the capture status.
set -u
VAR=$1; HANDLER=$2; KILL=$3; TRIAL=$4; OUT=$5
HERE=$(cd "$(dirname "$0")" && pwd)
RUN=$HERE/../official380/run.sh
BIN=nvs_kill_repro
CAPTURE_AFTER_S=${CAPTURE_AFTER_S:-8}
mkdir -p "$OUT"
tag=${VAR}_${HANDLER}_kill${KILL}_t${TRIAL}
L0=$OUT/$tag.pe0.log

FINALIZE=1 bash "$RUN" "$VAR" "$HANDLER" "$KILL" "$TRIAL" "$OUT" > "$OUT/$tag.row" 2> "$OUT/$tag.runner.err" &
RUN_PID=$!

# wait for PE 0 to start finalize (or for the trial to end)
while kill -0 $RUN_PID 2>/dev/null; do
  grep -q "calling nvshmem_finalize" "$L0" 2>/dev/null && break
  sleep 0.1
done
cap=none
if grep -q "calling nvshmem_finalize" "$L0" 2>/dev/null; then
  t_fin=$(date +%s.%N)
  echo "finalize_seen $(date +%T.%N | cut -c1-12)" > "$OUT/$tag.capture"
  sleep "$CAPTURE_AFTER_S"
  pid=$(pgrep -x $BIN | head -1)
  if grep -q "nvshmem_finalize returned\|nvshmem_finalize did not return" "$L0"; then
    cap=returned_before_capture
  elif [ -n "$pid" ]; then
    cap=captured
    echo "capture_at $(date +%T.%N | cut -c1-12) pid $pid" >> "$OUT/$tag.capture"
    nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits -i 0 > "$OUT/$tag.gpuutil" 2>&1
    sudo timeout 30 gdb -p "$pid" -batch -nx -ex 'set pagination off' -ex 'thread apply all bt' \
      > "$OUT/$tag.gdb.txt" 2>&1
    echo "gdb_rc $?" >> "$OUT/$tag.capture"
    sudo timeout -s INT 3 strace -f -tt -p "$pid" -o "$OUT/$tag.strace.txt" 2> "$OUT/$tag.strace.err"
    echo "strace_done $(date +%T.%N | cut -c1-12)" >> "$OUT/$tag.capture"
    sudo timeout 40 /usr/local/cuda/bin/cuda-gdb -p "$pid" -batch -nx -ex 'set pagination off' \
      -ex 'info cuda kernels' -ex 'info cuda threads' -ex 'bt' -ex 'x/4i $pc' \
      -ex 'cuda lane 1' -ex 'x/2i $pc' > "$OUT/$tag.cudagdb.txt" 2>&1
    echo "cudagdb_rc $?" >> "$OUT/$tag.capture"
  else
    cap=process_gone
  fi
fi
wait $RUN_PID
echo "capture $cap" >> "$OUT/$tag.capture" 2>/dev/null
echo "$(cat "$OUT/$tag.row"),$cap"
