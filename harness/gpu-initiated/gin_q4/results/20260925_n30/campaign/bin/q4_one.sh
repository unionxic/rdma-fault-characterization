#!/usr/bin/env bash
# q4_one.sh <cq> <classify> <fault> <wait> <trial> <out_csv> [VAR=value ...]   (extra env for both ranks)
# One GIN GDAKI Q4 trial with the UNCHANGED runner ../gin_q4/scripts/run_trial.sh and bundle
# ~/gi-bundle/gin_q4, with the settings of gin_q4/scripts/run_matrix.sh one() (120 iters, 15 ms gap,
# F4: 400 iters, 10 ms gap, kill at 2.5 s; inject at 600 ms; device timeout 5 s; IB timeout 14),
# plus, per trial: the doorbell-mode indicators (DOCA_GPUNETIO_LOG=4 "Enabling CPU proxy mode",
# GIN proxy-thread probe with NCCL_SET_THREAD_NAME=1, both as gin_recovery/scripts/q4_rerun.sh)
# and the nvidia driver configuration of both nodes.
# Post-fault knobs (N30 campaign, documented): GIN_BLOCK_CAP_S 8 (classifier on) / 12 (off) (target's
# blocking-hang cap; driver default 25), GIN_POST_POLL_S=2 (default 15), GIN_ABORT_WATCHDOG_S 4 / 6
# (default 15). They bound only what happens after the initiator's error/exit (target hang, teardown).
set -u
CQ=$1; C=$2; F=$3; W=$4; T=$5; OUT=$6; shift 6; XE="$*"
A=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/agent_n30
G=/home/unionxic/rdma-error/harness/gpu-initiated
Q4=$G/gin_q4/scripts/run_trial.sh
PROBE=$G/gin_recovery/scripts/thread_probe.sh
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
LOGDIR=$(dirname "$OUT")/logs; mkdir -p "$LOGDIR"
it=120; gap=15; wd=55
[ "$W" = blocking ] && wd=80
[ "$F" = F4 ] && { it=400; gap=10; }
stem="${CQ}_c${C}_${F}_${W}_t${T}"
# Post-fault bounds: classifier on -> target blocking cap 8 s, abort watchdog 4 s (the initiator has its
# result ~4 s after the fault at worst: F3/F4 RETRY_EXC); classifier off (stock control) -> 12 s / 6 s so
# that the initiator still sees the 10 s QP-state tick (9.4 s after F1) while the target is alive.
if [ "$C" = 1 ]; then CAP_DEF=8; WD_DEF=4; else CAP_DEF=12; WD_DEF=6; fi
bash "$A/bin/drvcfg.sh" "$LOGDIR/${stem}_drv.txt"
P0F=$(mktemp "$A/work/p0.XXXXXX"); P1F=$(mktemp "$A/work/p1.XXXXXX")
bash "$PROBE" gin_q4 $((wd+30)) > "$P0F" 2>&1 & P0=$!
ssh "$SUNNY_SSH" "bash -s gin_q4 $((wd+30))" < "$PROBE" > "$P1F" 2>&1 & P1=$!
env CQ_TYPE=$CQ CLASSIFY=$C WATCHDOG_S=$wd GAP_MS=$gap INJECT_MS=600 KILL_DELAY_MS=2500 DEV_TIMEOUT_S=5 \
  GIN_BLOCK_CAP_S=${GIN_BLOCK_CAP_S:-$CAP_DEF} GIN_POST_POLL_S=${GIN_POST_POLL_S:-2} Q4_WORKDIR=$A/work \
  EXTRA_ENV="DOCA_GPUNETIO_LOG=4 NCCL_SET_THREAD_NAME=1 GIN_ABORT_WATCHDOG_S=${ABORT_WD:-$WD_DEF} $XE" \
  bash "$Q4" "$F" "$W" "$T" "$OUT" "$it" 14
wait $P0 $P1 2>/dev/null
{ sed -n 's/^probe /r0 /p' "$P0F"; sed -n 's/^probe /r1 /p' "$P1F"; } > "$LOGDIR/${stem}_probe.txt"
rm -f "$P0F" "$P1F"
echo "[q4 $stem] probe: $(tr '\n' ' ' < "$LOGDIR/${stem}_probe.txt") cpu_proxy_lines r0=$(grep -c 'Enabling CPU proxy mode' "$LOGDIR/${stem}_r0.log" 2>/dev/null) r1=$(grep -c 'Enabling CPU proxy mode' "$LOGDIR/${stem}_r1.log" 2>/dev/null)" >&2
