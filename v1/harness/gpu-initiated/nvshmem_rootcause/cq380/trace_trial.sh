#!/usr/bin/env bash
# trace_trial.sh <stock|fix> <cpu_host_memory|gpu> <kill 0|1> <trial> <outdir>
# One ../official380/run.sh trial with the CQ-reading program (NVS_BIN=nvs_cq_repro CQSCAN=1).
# The program reads every CQ itself when no kernel is stuck. When its scan cannot run (a kernel
# is stuck in nvshmem_quiet), it prints "CQSCAN hold" and sleeps CQSCAN_HOLD_S; this script then
# reads every CQ buffer listed in the program's "CQSCAN prep" lines from GPU memory with cuda-gdb
# (x/ of the whole buffer, in <tag>.cudagdb.txt) and decodes them with cqdump.py. Run it inside ../../common/cluster_run.sh.
set -u
VAR=$1; HANDLER=$2; KILL=$3; TRIAL=$4; OUT=$5
HERE=$(cd "$(dirname "$0")" && pwd)
RUN=$HERE/../official380/run.sh
mkdir -p "$OUT"
tag=${VAR}_${HANDLER}_kill${KILL}_t${TRIAL}
L0=$OUT/$tag.pe0.log
export NVS_BIN=nvs_cq_repro CQSCAN=1 CQSCAN_HOLD_S=${CQSCAN_HOLD_S:-40}

bash "$RUN" "$VAR" "$HANDLER" "$KILL" "$TRIAL" "$OUT" > "$OUT/$tag.row" 2> "$OUT/$tag.runner.err" &
RUN_PID=$!
while kill -0 $RUN_PID 2>/dev/null; do
  grep -q "CQSCAN hold\|CQSCAN queues=" "$L0" 2>/dev/null && break
  sleep 0.2
done
dump=none
if grep -q "CQSCAN hold" "$L0" 2>/dev/null; then
  pid=$(pgrep -x nvs_cq_repro | head -1)
  cmds=(-ex 'set pagination off')
  # x/ reads GPU global memory; "dump binary memory" was found to read the host side (zeros)
  while read -r i addr n; do
    cmds+=(-ex "echo CQBEGIN $i\\n" -ex "x/$(( n * 64 ))xb (@global unsigned char *)$addr" -ex "echo CQEND $i\\n")
  done < <(sed -n 's/^CQSCAN prep cq=\([0-9]*\) type=[a-z]* qpn=0x[0-9a-f]* ncqes=\([0-9]*\) cqe=\(0x[0-9a-f]*\).*/\1 \3 \2/p' "$L0")
  sudo timeout 120 /usr/local/cuda/bin/cuda-gdb -p "$pid" -batch -nx "${cmds[@]}" > "$OUT/$tag.cudagdb.txt" 2>&1
  echo "cudagdb_rc $?" >> "$OUT/$tag.cudagdb.txt"
  python3 "$HERE/cqdump.py" "$L0" "$OUT/$tag.cudagdb.txt" > "$OUT/$tag.cqdump.txt" 2>&1
  dump=$(tail -1 "$OUT/$tag.cqdump.txt")
fi
wait $RUN_PID
echo "$(cat "$OUT/$tag.row"),\"$dump\""
