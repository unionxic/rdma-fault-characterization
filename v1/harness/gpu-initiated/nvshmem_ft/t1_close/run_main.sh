#!/usr/bin/env bash
# run_main.sh <results dir> [holds] - the main holds of t1_close, one cluster_run.sh lock per hold
# (-w 10800: other experiments share the lock), in order A B C D E by default. After each hold the
# chain stops if hold.sh counted a new mlx5 command error on either node or a t1sock iptables rule left.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
FT="$(cd "$HERE/.." && pwd)"
R=$1; shift
HOLDS=${*:-A B C D E}
export T1C_BUNDLE_NAME=${T1C_BUNDLE_NAME:-nvshmem_t1close_b2}
CR="$FT/../common/cluster_run.sh"
cd "$FT"
for h in $HOLDS; do
  case $h in
    A) parts="t1:t1_close/specs/holdA.txt:1:780:gate_test" ;;
    B) parts="t1:t1_close/specs/holdB.txt:1:780" ;;
    C) parts="t1:scripts/t1/specs/lat.txt:1:400 v2:t1_close/specs/v22.txt:400" ;;
    D) parts="t1:t1_close/specs/holdD.txt:0:780" ;;
    E) parts="t1:t1_close/specs/holdE.txt:0:780" ;;
    *) echo "unknown hold $h"; exit 2 ;;
  esac
  mkdir -p "$R/$h"
  echo "[main] hold $h queued $(date '+%F %T')"
  # shellcheck disable=SC2086
  "$CR" -w 10800 -t "t1c-$h" -- timeout -s KILL 900 env T1C_BUNDLE_NAME="$T1C_BUNDLE_NAME" \
      bash t1_close/hold.sh "$R/$h" $parts > "$R/$h/cluster_run.out" 2>&1
  rc=$?
  echo "[main] hold $h rc=$rc $(date '+%F %T') $(grep -h -E 'mlx5_cmd_errors|iptables_t1sock_left|hold start|hold end' "$R/$h/hold.log" 2>/dev/null | tr '\n' ' ')"
  if grep -q -E 'mlx5_cmd_errors_(rain|sunny)=[1-9]' "$R/$h/hold.log" 2>/dev/null; then echo "[main] STOP: new mlx5 command error"; exit 3; fi
  if ! grep -q 'iptables_t1sock_left=0' "$R/$h/hold.log" 2>/dev/null; then echo "[main] STOP: iptables check failed or missing"; exit 4; fi
done
echo "[main] done $(date '+%F %T')"
