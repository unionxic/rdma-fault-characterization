#!/usr/bin/env bash
# run_session.sh - run a list of teardown-fingerprint variants (one locked session).
#
# usage: [REVERSE=1] run_session.sh <out_dir> <spec_file>
#   Run it under the cluster lock:
#     ../gpu-initiated/common/cluster_run.sh -w 3600 -t fp-<name> -- ./run_session.sh <out_dir> <spec>
# spec_file: one variant per line, '#' comments allowed:
#   <variant_name> <N> <trigger> <fp_responder flags...>
#   trigger = kill | dereg_mr | destroy_qp | cuda_free | cuda_reset | qp_err
# Default: victim (fp_launcher + fp_responder) on sunny, requester on rain (this node).
# REVERSE=1: victim on rain (this node, mlx5_1), requester on sunny (mlx5_0) - used to
#   compare the two OFED versions' uverbs teardown (rain 23.10, sunny 25.10).
# N trials per variant (one fp_requester process per trial; each trial spawns a fresh
# victim); rows go to <out_dir>/trials.csv; every requester/victim log is kept.
# The session aborts itself after SESSION_MAX_S seconds (default 540) so a locked run
# stays under 10 minutes.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT=${1:?out_dir}; SPEC=${2:?spec_file}
OUT="$(mkdir -p "$OUT" && cd "$OUT" && pwd)"
SUNNY=${SUNNY:-sunny}                         # ssh alias
SUNNY_MGMT_IP=${SUNNY_MGMT_IP:-192.0.2.194}
RAIN_MGMT_IP=${RAIN_MGMT_IP:-192.0.2.193}
REVERSE=${REVERSE:-0}
CPORT=18931; OPORT=18932; KPORT=18933
SESSION_MAX_S=${SESSION_MAX_S:-540}
REQ_OPTS=${REQ_OPTS:-"-w 300 -S 65536 -D 8 -I 20 -T 8000"}
mkdir -p "$OUT/logs"
SID=$(date +%H%M%S)
t_session0=$(date +%s)
log() { echo "[session $(date +%T)] $*" | tee -a "$OUT/session.log" >&2; }

if [ "$REVERSE" = 1 ]; then
    VDEV=mlx5_1; RDEV=mlx5_0; VIP=$RAIN_MGMT_IP
    VDIR="$OUT/logs/victim_rain_$SID"; mkdir -p "$VDIR"
    VBIN="$HERE/fp_responder"
    ssh -n "$SUNNY" "mkdir -p fp-bundle/logs/$SID" || exit 1
    scp -q "$HERE/fp_requester" "$SUNNY:fp-bundle/" || exit 1
    (setsid nohup timeout $((SESSION_MAX_S + 60)) "$HERE/fp_launcher" -p $CPORT -k $KPORT -t 60 \
        > "$VDIR/launcher.log" 2>&1 < /dev/null &)
    sleep 0.5
    LPID=$(pgrep -x -u "$(id -u)" fp_launcher | head -1)
else
    VDEV=mlx5_0; RDEV=mlx5_1; VIP=$SUNNY_MGMT_IP
    VDIR="/home/unionxic/fp-bundle/logs/$SID"
    VBIN="/home/unionxic/fp-bundle/fp_responder"
    ssh -n "$SUNNY" "mkdir -p fp-bundle/logs/$SID" || exit 1
    scp -q "$HERE/fp_launcher" "$HERE/fp_responder" "$SUNNY:fp-bundle/" || exit 1
    # (the subshell matters: without it ssh stayed attached until the launcher exited)
    LPID=$(ssh -n "$SUNNY" "cd fp-bundle && (setsid nohup timeout $((SESSION_MAX_S + 60)) ./fp_launcher -p $CPORT -k $KPORT -t 60 \
        > logs/$SID/launcher.log 2>&1 < /dev/null &) ; sleep 0.5; pgrep -x fp_launcher | head -1")
fi
[ -n "$LPID" ] || { log "launcher did not start"; exit 1; }
log "reverse=$REVERSE launcher pid $LPID; victim dev $VDEV at $VIP, requester dev $RDEV"

cleanup() {
    if [ "$REVERSE" = 1 ]; then
        kill "$LPID" 2>/dev/null
        pgrep -x -u "$(id -u)" fp_responder >/dev/null && log "WARNING: fp_responder still running on rain"
        scp -q "$SUNNY:fp-bundle/logs/$SID/trials.csv" "$OUT/trials_rev_$SID.csv" 2>/dev/null
        if [ -f "$OUT/trials_rev_$SID.csv" ]; then
            if [ -f "$OUT/trials.csv" ]; then tail -n +2 "$OUT/trials_rev_$SID.csv" >> "$OUT/trials.csv"
            else cp "$OUT/trials_rev_$SID.csv" "$OUT/trials.csv"; fi
        fi
    else
        ssh -n "$SUNNY" "kill $LPID 2>/dev/null; pgrep -x fp_responder >/dev/null && echo 'WARNING: fp_responder still running on sunny'; true" \
            | tee -a "$OUT/session.log"
        rsync -a "$SUNNY:fp-bundle/logs/$SID/" "$OUT/logs/victim_$SID/" 2>/dev/null
    fi
}
trap cleanup EXIT

rc=0
while read -r name n trig flags; do
    [ -z "${name:-}" ] && continue
    case "$name" in \#*) continue ;; esac
    log "variant $name: N=$n trigger=$trig flags='$flags'"
    for i in $(seq 1 "$n"); do
        if [ $(( $(date +%s) - t_session0 )) -gt "$SESSION_MAX_S" ]; then
            log "session time cap ${SESSION_MAX_S}s reached; stopping"; exit 3
        fi
        rq="$OUT/logs/req_${SID}_${name}_$i.log"
        if [ "$REVERSE" = 1 ]; then
            # shellcheck disable=SC2029,SC2086
            ssh -n "$SUNNY" "timeout 60 fp-bundle/fp_requester -d $RDEV -L $VIP -p $CPORT -P $OPORT \
                -R '$VBIN -d $VDEV -P $OPORT -K $KPORT $flags' -l '$VDIR/${name}_$i.log' -a $trig \
                -v $name -n $i -o fp-bundle/logs/$SID/trials.csv $REQ_OPTS" 2> "$rq"
        else
            # shellcheck disable=SC2086
            timeout 60 "$HERE/fp_requester" -d "$RDEV" -L "$VIP" -p $CPORT -P $OPORT \
                -R "$VBIN -d $VDEV -P $OPORT -K $KPORT $flags" \
                -l "$VDIR/${name}_$i.log" -a "$trig" -v "$name" -n "$i" -o "$OUT/trials.csv" $REQ_OPTS 2> "$rq"
        fi
        r=$?
        tail -n 3 "$rq" | sed 's/^/    /' >&2
        [ $r -eq 0 ] || { log "trial $name #$i: requester exit $r"; rc=1; }
        sleep 0.3
    done
done < "$SPEC"
exit $rc
