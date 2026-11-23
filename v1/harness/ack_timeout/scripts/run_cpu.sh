#!/usr/bin/env bash
# run_cpu.sh - one ackt cell: responder on sunny, requester on rain, N trials at (T, R).
# Must run inside ../../gpu-initiated/common/cluster_run.sh (and, for floor-off cells, inside
# ../ackfloor_window.sh). Every process is bounded by `timeout -s KILL`.
#
#   run_cpu.sh <outdir> <label> <T> <R> <N> [extra requester args, e.g. -K ... -N -W ms]
#
# Appends to <outdir>/trials.csv and <outdir>/events.csv; per-cell logs in <outdir>/logs/.
set -u
OUTDIR=$1; LABEL=$2; T=$3; R=$4; N=$5; shift 5
EXTRA=("$@")
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/agent_ack
BIN=$SCR/ackt                      # same path on both nodes (built from the same sources)
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
SUNNY_MGMT=192.0.2.194
PORT=${ACKT_PORT:-18591}
CAP_MS=${CAP_MS:-120000}
CLIENT_CPU=${CLIENT_CPU:-2}
SAMPLER_CPU=${SAMPLER_CPU:-4}
mkdir -p "$OUTDIR/logs"

GID_PROBE='d=/sys/class/infiniband/$1/ports/1
for g in $(ls "$d/gids" | sort -n); do
  [ "$(cat "$d/gid_attrs/types/$g" 2>/dev/null)" = "RoCE v2" ] || continue
  case "$(cat "$d/gids/$g")" in 0000:0000:0000:0000:0000:ffff:*) echo "$g"; exit 0;; esac
done; exit 1'
G0=$(bash -c "$GID_PROBE" _ mlx5_1) || { echo "no RoCE v2 GID on rain mlx5_1" >&2; exit 1; }
G1=$(ssh -n -o ConnectTimeout=5 "$SUNNY_SSH" bash -c "'$GID_PROBE'" _ mlx5_0) || { echo "no GID on sunny" >&2; exit 1; }

# bound: N trials x (cap + quiet + setup) + margin
BOUND=$(( N * (CAP_MS / 1000 + 5) + 60 ))
stem="${LABEL}_T${T}_R${R}"
SLOG=$OUTDIR/logs/${stem}.srv.log; CLOG=$OUTDIR/logs/${stem}.cli.log

ssh -n -o ConnectTimeout=5 "$SUNNY_SSH" "pgrep -x ackt >/dev/null && echo 'stale ackt on sunny' >&2; \
  exec timeout -s KILL $((BOUND + 20)) $BIN -S -d mlx5_0 -g $G1 -p $PORT" > "$SLOG" 2>&1 &
SSH_PID=$!
for i in $(seq 1 50); do grep -q listening "$SLOG" 2>/dev/null && break; sleep 0.1; done

{
  echo "# $(date '+%F %T') $stem gid rain=$G0 sunny=$G1 port=$PORT bound=${BOUND}s extra='${EXTRA[*]}'"
  echo "# ROCE_ACCL min_ack_timeout_limit_disabled (rain 17:00.1) at start: $(sudo -n mlxreg -d 17:00.1 --reg_name ROCE_ACCL --get 2>/dev/null | awk -F'|' '/^min_ack_timeout_limit_disabled /{gsub(/ /,"",$2); print $2}')"
} >> "$CLOG"
timeout -s KILL "$BOUND" "$BIN" -c "$SUNNY_MGMT" -p "$PORT" -d mlx5_1 -g "$G0" -T "$T" -R "$R" -n "$N" \
  -o "$OUTDIR/trials.csv" -e "$OUTDIR/events.csv" -L "$LABEL" -W "$CAP_MS" \
  -C "$CLIENT_CPU" -X "$SAMPLER_CPU" "${EXTRA[@]}" >> "$CLOG" 2>&1
RC=$?
wait "$SSH_PID" 2>/dev/null
LEFT=$(ssh -n -o ConnectTimeout=5 "$SUNNY_SSH" "pgrep -x ackt | wc -l")
LEFT0=$(pgrep -x ackt | wc -l)
echo "# rc=$RC leftover_sunny=$LEFT leftover_rain=$LEFT0 end=$(date '+%F %T')" >> "$CLOG"
echo "[run_cpu] $stem rc=$RC leftover=$LEFT/$LEFT0"
exit $RC
