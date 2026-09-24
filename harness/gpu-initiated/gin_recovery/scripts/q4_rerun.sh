#!/usr/bin/env bash
# q4_rerun.sh <out_csv> [trials] - re-run the Q4 classifier (unchanged gin_q4 build, runner and
# bundle ~/gi-bundle/gin_q4) for F1..F4 in timeout mode with the same settings as its batch
# B-on-timeout, plus the doorbell-mode probe (thread_probe.sh) and DOCA's own warnings
# (DOCA_GPUNETIO_LOG=4 prints "Enabling CPU proxy mode" when DOCA falls back to the CPU proxy).
# Run inside ../../common/cluster_run.sh.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
Q4=$HERE/../../gin_q4/scripts/run_trial.sh
OUT=${1:?out_csv}; NT=${2:-2}
FAULTS=${Q4_FAULTS:-F1 F2 F3 F4}   # Q4_TAG prefixes the trial number; Q4_EXTRA adds env (e.g. the
TAG=${Q4_TAG:-}                    # positive control NCCL_GIN_GDAKI_NIC_HANDLER=1 forces the CPU proxy)
LOGDIR=$(dirname "$OUT")/logs; mkdir -p "$LOGDIR"
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
for f in $FAULTS; do for n in $(seq 1 "$NT"); do
  t=$TAG$n
  it=120; gap=15; wd=55
  [ "$f" = F4 ] && { it=400; gap=10; }
  echo ">>> [q4 ring c1 $f timeout #$t] $(date +%T)" >&2
  bash "$HERE/thread_probe.sh" gin_q4 $((wd+30)) > /tmp/q4probe0.$$ 2>&1 & P0=$!
  ssh "$SUNNY_SSH" "bash -s gin_q4 $((wd+30))" < "$HERE/thread_probe.sh" > /tmp/q4probe1.$$ 2>&1 & P1=$!
  env CQ_TYPE=ring CLASSIFY=1 WATCHDOG_S=$wd GAP_MS=$gap INJECT_MS=600 KILL_DELAY_MS=2500 DEV_TIMEOUT_S=5 \
    EXTRA_ENV="DOCA_GPUNETIO_LOG=4 NCCL_SET_THREAD_NAME=1 ${Q4_EXTRA:-}" bash "$Q4" "$f" timeout "$t" "$OUT" "$it" 14
  wait $P0 $P1 2>/dev/null
  stem="ring_c1_${f}_timeout_t${t}"
  { sed -n 's/^probe /r0 /p' /tmp/q4probe0.$$; sed -n 's/^probe /r1 /p' /tmp/q4probe1.$$; } > "$LOGDIR/${stem}_probe.txt"
  rm -f /tmp/q4probe0.$$ /tmp/q4probe1.$$
  echo "[q4 $f #$t] $(tr '\n' ' ' < "$LOGDIR/${stem}_probe.txt")" >&2
done; done
echo ">>> q4 rerun complete $(date +%T)" >&2
