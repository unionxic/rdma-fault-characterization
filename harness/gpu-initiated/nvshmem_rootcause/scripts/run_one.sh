#!/usr/bin/env bash
# run_one.sh - one nrc_devx trial: target on sunny, requester on rain. Call it from inside
# ../../common/cluster_run.sh (it does not take the cluster lock itself).
#
#   run_one.sh <tag> <outdir> <fault> <preset> [<sets>] [-- extra requester args]
#     fault : none | f1 | f1post | f2b | f3
#     preset: nvshmem | doca        sets: "k=v,k=v" (same on both ends), or "" / "-"
# env: ACK_TIMEOUT (14), OBSERVE_MS (8000), PORT (18633)
# Prints the requester's SUMMARY line. Logs: <outdir>/<tag>.{req,tgt}.log, <tag>.timeline.csv
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
BIN="$HERE/../nrc_devx"
RBIN='~/gi-bundle/nrc/nrc_devx'
SUNNY=unionxic@192.0.2.194
SUNNY_IP=192.0.2.194
TAG=$1; OUT=$2; FAULT=$3; PRESET=$4; SETS=${5:-}
shift 4; [ $# -gt 0 ] && shift
[ "$SETS" = "-" ] && SETS=""
[ "${1:-}" = "--" ] && shift
PORT=${PORT:-18633}
ACK=${ACK_TIMEOUT:-14}
OBS=${OBSERVE_MS:-8000}
LIFE=$(( OBS / 1000 + 40 ))
mkdir -p "$OUT"

GID_PROBE='d=/sys/class/infiniband/$1/ports/$2
for g in $(ls "$d/gids" | sort -n); do
  [ "$(cat "$d/gid_attrs/types/$g" 2>/dev/null)" = "RoCE v2" ] || continue
  case "$(cat "$d/gids/$g")" in 0000:0000:0000:0000:0000:ffff:*) echo "$g"; exit 0;; esac
done; exit 1'
GID_RAIN=$(bash -s -- mlx5_1 1 <<< "$GID_PROBE") || { echo "no RoCE v2 IPv4 GID on rain" >&2; exit 4; }
# no ssh -n here: the probe script goes in on stdin
GID_SUNNY=$(ssh -o ConnectTimeout=5 "$SUNNY" "bash -s -- mlx5_0 1" <<< "$GID_PROBE") || { echo "no GID on sunny" >&2; exit 4; }

SETARG=(); [ -n "$SETS" ] && SETARG=(--set "$SETS")

# our own stragglers only (exact binary name)
pkill -x nrc_devx 2>/dev/null
ssh -n -o ConnectTimeout=5 "$SUNNY" "pkill -x nrc_devx 2>/dev/null; true"

ssh -n -o ConnectTimeout=8 "$SUNNY" \
  "exec timeout -s KILL $((LIFE + 10)) $RBIN -m tgt -d mlx5_0 -g $GID_SUNNY -p $PORT --preset $PRESET ${SETS:+--set $SETS} --timeout $ACK --life-s $LIFE" \
  > "$OUT/$TAG.tgt.log" 2>&1 &
SSH_PID=$!
sleep 0.5
timeout -s KILL $((LIFE + 20)) "$BIN" -m req -d mlx5_1 -g "$GID_RAIN" -s "$SUNNY_IP" -p "$PORT" --preset "$PRESET" \
  "${SETARG[@]}" -f "$FAULT" --timeout "$ACK" --observe-ms "$OBS" --life-s "$LIFE" -T "$OUT/$TAG.timeline.csv" "$@" \
  > "$OUT/$TAG.req.log" 2>&1
RC=$?
wait "$SSH_PID"
pkill -x nrc_devx 2>/dev/null
ssh -n -o ConnectTimeout=5 "$SUNNY" "pkill -x nrc_devx 2>/dev/null; true"
S=$(grep -m1 '^SUMMARY' "$OUT/$TAG.req.log")
if [ -z "$S" ]; then
  echo "tag=$TAG rc=$RC NO_SUMMARY $(grep -m1 FATAL "$OUT/$TAG.req.log" "$OUT/$TAG.tgt.log" | tr '\n' ' ')"
else
  echo "tag=$TAG rc=$RC $S"
fi
