#!/usr/bin/env bash
# flap_hold.sh <outdir> <build: t1|v22|t1nogid> <n> <cut_s> [<cut_s> ...] - one cluster hold of address-flap
# trials (harness/nccl-integration/stage2/gid_blackhole.sh): add the secondary RoCE addresses, run each
# trial with the RC QPs on the secondary GIDs (indices re-read before every trial, since a re-added
# address may come back at another index), remove sunny's secondary address for cut_s seconds in the
# middle of the run, and always remove both addresses at the end (EXIT trap). Wrap in cluster_run.sh.
#   t1      T1 build, transparent recovery on (GID re-lookup by value)
#   t1nogid T1 build, the re-lookup skipped (negative control)
#   v22     v2.2 build, FT on with ring CQs, no recovery (classification only): what stock-with-FT does
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
GBH=$HERE/../../../../nccl-integration/stage2/gid_blackhole.sh
OUT=$1; BUILD=$2; N=$3; shift 3
mkdir -p "$OUT"
export GBH_LOG="$OUT/gid_blackhole.log"
teardown() {
  bash "$GBH" teardown >> "$OUT/flap_hold.log" 2>&1
  ip -br addr show ens4f1np1 >> "$OUT/flap_hold.log" 2>&1
  ssh -n -o ConnectTimeout=5 unionxic@192.0.2.194 "ip -br addr show enp23s0f0np0" >> "$OUT/flap_hold.log" 2>&1
}
trap teardown EXIT
echo "setup $(date '+%F %T')" >> "$OUT/flap_hold.log"
bash "$GBH" setup >> "$OUT/flap_hold.log" 2>&1
export BYTES=${BYTES:-65536} ITERS=${ITERS:-1000} GAP_US=${GAP_US:-20000} SYM=${SYM:-128M}
export KTIMEOUT=${KTIMEOUT:-75} PROC_TIMEOUT=${PROC_TIMEOUT:-95} CUT_AT_MS=${CUT_AT_MS:-1500}
case "$BUILD" in
  t1) export FT=1 RING=1 T1=1 ;;
  t1nogid) export FT=1 RING=1 T1=1 T1SKIP=gid ;;
  v22) export FT=1 RING=1 T1=0 BIN=nvt1v22_drv ;;
  *) echo "bad build" >&2; exit 2 ;;
esac
T0=$(date +%s)
for ((k = 1; k <= N; k++)); do
  for c in "$@"; do
    [ $(( $(date +%s) - T0 )) -gt "${STOP_AFTER_S:-700}" ] && { echo "STOP_AFTER_S reached" >> "$OUT/flap_hold.log"; exit 0; }
    read -r GR GS <<< "$(bash "$GBH" gids 2>/dev/null)"
    if [ -z "$GR" ] || [ -z "$GS" ]; then echo "no secondary GID (rain '$GR' sunny '$GS'); stop" >> "$OUT/flap_hold.log"; exit 0; fi
    echo "trial $k cut $c gids_before rain=$GR sunny=$GS $(date '+%T')" >> "$OUT/flap_hold.log"
    GID_R=$GR GID_S=$GS CUT_S=$c TAG="${BUILD}_cut${c}" bash "$HERE/run_trial_t1.sh" FLAP loop "$k" "$OUT" >> "$OUT/flap_hold.log" 2>&1
    echo "trial $k cut $c gids_after $(bash "$GBH" gids 2>/dev/null)" >> "$OUT/flap_hold.log"
  done
done
