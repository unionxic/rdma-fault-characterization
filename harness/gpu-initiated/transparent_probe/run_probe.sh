#!/usr/bin/env bash
# run_probe.sh - one tr_probe trial: responder on sunny (mlx5_0), requester on rain (mlx5_1).
# MUST be launched inside ../common/cluster_run.sh (it does not take the cluster lock itself).
#
#   run_probe.sh <tag> <outdir> <scen> [-- extra requester args]
#     scen: resp_err | req_err | dup | wqeidx
# env: SEED (1), K (256), RECOVER (1), DELAY_MAX_US, DUP_DEPTH, READS, ACK_TIMEOUT (14), PORT (18744)
# Deploys the binary to sunny:/tmp/tr_probe (built there, OFED may differ). Prints the SUMMARY line.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
BIN="$HERE/tr_probe"
SUNNY=unionxic@192.0.2.194
SUNNY_IP=192.0.2.194
RBIN=/tmp/tr_probe/tr_probe
TAG=$1; OUT=$2; SCEN=$3; shift 3
[ "${1:-}" = "--" ] && shift
PORT=${PORT:-18744}
ACK=${ACK_TIMEOUT:-14}
SEED=${SEED:-1}; K=${K:-256}; RECOVER=${RECOVER:-1}
DELAY_MAX_US=${DELAY_MAX_US:-2000}; DUP_DEPTH=${DUP_DEPTH:-8}
READS=${READS:--1}
mkdir -p "$OUT"
[ -x "$BIN" ] || { echo "build $BIN first (make)"; exit 4; }

# build on sunny (its own OFED); md5-guard the source so we don't rebuild needlessly
ssh -n -o ConnectTimeout=8 "$SUNNY" "mkdir -p /tmp/tr_probe" || { echo "ssh sunny failed"; exit 4; }
scp -q "$HERE/tr_probe.c" "$HERE/tr_prm.h" "$HERE/Makefile" "$SUNNY:/tmp/tr_probe/" || exit 4
ssh -n -o ConnectTimeout=8 "$SUNNY" "cd /tmp/tr_probe && make >/tmp/tr_probe/build.log 2>&1" || {
  echo "sunny build failed:"; ssh -n "$SUNNY" "cat /tmp/tr_probe/build.log"; exit 4; }

GID_PROBE='d=/sys/class/infiniband/$1/ports/$2
for g in $(ls "$d/gids" | sort -n); do
  [ "$(cat "$d/gid_attrs/types/$g" 2>/dev/null)" = "RoCE v2" ] || continue
  case "$(cat "$d/gids/$g")" in 0000:0000:0000:0000:0000:ffff:*) echo "$g"; exit 0;; esac
done; exit 1'
GID_RAIN=$(bash -s -- mlx5_1 1 <<< "$GID_PROBE") || { echo "no RoCE v2 IPv4 GID on rain" >&2; exit 4; }
GID_SUNNY=$(ssh -o ConnectTimeout=5 "$SUNNY" "bash -s -- mlx5_0 1" <<< "$GID_PROBE") || { echo "no GID on sunny" >&2; exit 4; }

READARG=""; [ "$READS" != "-1" ] && READARG="--reads $READS"

# only our own stragglers, exact binary name
pkill -x tr_probe 2>/dev/null
ssh -n -o ConnectTimeout=5 "$SUNNY" "pkill -x tr_probe 2>/dev/null; true"

ssh -n -o ConnectTimeout=8 "$SUNNY" \
  "exec timeout -s KILL 130 $RBIN -m tgt -d mlx5_0 -g $GID_SUNNY -p $PORT -S $SCEN -k $K --seed $SEED --timeout $ACK --life-s 90" \
  > "$OUT/$TAG.tgt.log" 2>&1 &
SSH_PID=$!
sleep 0.5
timeout -s KILL 140 "$BIN" -m req -d mlx5_1 -g "$GID_RAIN" -s "$SUNNY_IP" -p "$PORT" -S "$SCEN" -k "$K" \
  --seed "$SEED" --recover "$RECOVER" --delay-max-us "$DELAY_MAX_US" --dup-depth "$DUP_DEPTH" $READARG \
  --timeout "$ACK" --life-s 90 "$@" > "$OUT/$TAG.req.log" 2>&1
RC=$?
wait "$SSH_PID" 2>/dev/null
pkill -x tr_probe 2>/dev/null
ssh -n -o ConnectTimeout=5 "$SUNNY" "pkill -x tr_probe 2>/dev/null; true"
S=$(grep -m1 '^SUMMARY' "$OUT/$TAG.req.log")
if [ -z "$S" ]; then
  echo "tag=$TAG rc=$RC NO_SUMMARY $(grep -m1 FATAL "$OUT/$TAG.req.log" "$OUT/$TAG.tgt.log" 2>/dev/null | tr '\n' ' ')"
else
  echo "tag=$TAG rc=$RC $S"
fi
