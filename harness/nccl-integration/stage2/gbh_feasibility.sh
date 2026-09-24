#!/usr/bin/env bash
# gbh_feasibility.sh - does removing a secondary RoCE GID behave like a path fault?
# ib_write_bw over the secondary GIDs; cut sunny's secondary address for a short (0.3 s) and a
# long (6 s) outage mid-run. Expect: short = masked by retransmission, long = RETRY_EXC (12).
# Run under ../../gpu-initiated/common/cluster_run.sh.
set -u
D=$(cd "$(dirname "$0")" && pwd)
OUT=${1:?outdir}; mkdir -p "$OUT"
SUNNY=unionxic@192.0.2.194
trap '"$D"/gid_blackhole.sh teardown; pkill -x ib_write_bw; ssh -n $SUNNY "pkill -x ib_write_bw"' EXIT
read g0 g1 < <("$D"/gid_blackhole.sh setup)
[ -n "$g0" ] && [ -n "$g1" ] || { echo "no secondary GIDs ($g0/$g1)"; exit 2; }
echo "gids rain=$g0 sunny=$g1" | tee "$OUT/gids.txt"
for outage in 0.3 6; do
  tag=cut_${outage}
  ssh -n $SUNNY "timeout 30 ib_write_bw -d mlx5_0 -x $g1 -u 14 -D 12 -F --report_gbits -p 18515" > "$OUT/${tag}_server.log" 2>&1 &
  sp=$!
  sleep 1.5
  timeout 30 ib_write_bw -d mlx5_1 -x $g0 -u 14 -D 12 -F --report_gbits -p 18515 192.0.2.194 > "$OUT/${tag}_client.log" 2>&1 &
  cp=$!
  sleep 5
  t0=$(date +%s.%N)
  "$D"/gid_blackhole.sh cut $outage
  t1=$(date +%s.%N)
  wait $cp; crc=$?
  wait $sp; src=$?
  echo "$tag client_rc=$crc server_rc=$src cut_start=$t0 cut_end=$t1" | tee -a "$OUT/summary.txt"
  sleep 2
done
