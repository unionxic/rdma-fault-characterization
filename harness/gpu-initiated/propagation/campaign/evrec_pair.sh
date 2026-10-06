#!/usr/bin/env bash
# evrec_pair.sh start|stop <outdir> <tag> - run evrec on rain (mlx5_1) and sunny (mlx5_0) around
# one trial. "start" returns once both have written their start snapshot; "stop" sends SIGTERM,
# waits for the end snapshot and leaves <tag>.evrec.rain and <tag>.evrec.sunny in <outdir>.
# Each evrec also ends by itself after MAX_S seconds, so a lost "stop" cannot leave it running.
set -u
CMD=$1; OUT=$2; TAG=$3
E=$HOME/gi-bundle/evrec/evrec
MAX_S=${MAX_S:-1800}
mkdir -p "$OUT"
L=$OUT/$TAG.evrec.rain; R=/tmp/evrec_$TAG.log

wait_line() {  # wait_line <file> <pattern> <tries of 0.05 s>
  for _ in $(seq "$3"); do grep -q "$2" "$1" 2>/dev/null && return 0; sleep 0.05; done; return 1
}

case "$CMD" in
start)
  "$E" -d mlx5_1 -p 1 -o "$L" -T "$MAX_S" >/dev/null 2>&1 &
  echo $! > "$OUT/.$TAG.evrec.pid"
  ssh -n sunny "nohup $E -d mlx5_0 -p 1 -o $R -T $MAX_S >/dev/null 2>&1 & echo \$!" > "$OUT/.$TAG.evrec.rpid"
  wait_line "$L" '^snap phase=start dir=counters' 100 || echo "evrec_pair: no start snapshot on rain for $TAG" >&2
  ssh -n sunny "for i in \$(seq 100); do grep -q '^snap phase=start dir=counters' $R && exit 0; sleep 0.05; done; exit 1" \
    || echo "evrec_pair: no start snapshot on sunny for $TAG" >&2
  ;;
stop)
  kill -TERM "$(cat "$OUT/.$TAG.evrec.pid")" 2>/dev/null
  ssh -n sunny "kill -TERM $(cat "$OUT/.$TAG.evrec.rpid") 2>/dev/null; for i in \$(seq 100); do grep -q '^end ' $R && break; sleep 0.05; done; cat $R; rm -f $R" \
    > "$OUT/$TAG.evrec.sunny"
  wait_line "$L" '^end ' 100 || echo "evrec_pair: no end record on rain for $TAG" >&2
  rm -f "$OUT/.$TAG.evrec.pid" "$OUT/.$TAG.evrec.rpid"
  ;;
*) echo "usage: $0 start|stop <outdir> <tag>" >&2; exit 2 ;;
esac
