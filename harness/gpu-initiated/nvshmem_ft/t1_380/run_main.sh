#!/usr/bin/env bash
# run_main.sh <results dir> [holds] - the main holds of t1_380 (A B C by default), one cluster_run.sh lock
# per hold (-w 10800: the GIN reconnect study shares the lock). After each hold the chain stops on a new
# mlx5 command error on either node, a t1sock iptables rule or a process of this study left.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
FT="$(cd "$HERE/.." && pwd)"
R=$1; shift
HOLDS=${*:-A B C}
CR="$FT/../common/cluster_run.sh"
cd "$FT"
for h in $HOLDS; do
  case $h in
    A) parts="t1:t1_380/specs/holdA.txt:1:780:gate_test" ;;
    B) parts="t1:t1_380/specs/holdB.txt:1:780" ;;
    C) parts="t1:t1_380/specs/holdC.txt:1:780" ;;
    smoke) parts="t1:t1_380/specs/smoke.txt:0:780" ;;
    *) echo "unknown hold $h"; exit 2 ;;
  esac
  mkdir -p "$R/$h"
  echo "[main] hold $h queued $(date '+%F %T')"
  # shellcheck disable=SC2086
  "$CR" -w 10800 -t "t1x-$h" -- timeout -s KILL 900 bash t1_380/hold.sh "$R/$h" $parts > "$R/$h/cluster_run.out" 2>&1
  rc=$?
  echo "[main] hold $h rc=$rc $(date '+%F %T') $(grep -h -E 'mlx5_cmd_errors|iptables_t1sock_left|hold start|hold end' "$R/$h/hold.log" 2>/dev/null | tr '\n' ' ')"
  if grep -q -E 'mlx5_cmd_errors_(rain|sunny)=[1-9]' "$R/$h/hold.log" 2>/dev/null; then echo "[main] STOP: new mlx5 command error"; exit 3; fi
  if ! grep -q 'iptables_t1sock_left=0 procs_left_rain=0 procs_left_sunny=0' "$R/$h/hold.log" 2>/dev/null; then echo "[main] STOP: leftover rule or process, or check missing"; exit 4; fi
done
echo "[main] done $(date '+%F %T')"
