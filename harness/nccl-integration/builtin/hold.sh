#!/usr/bin/env bash
# nccl-builtin holds (each <= 15 min; each inside ../../gpu-initiated/common/cluster_run.sh -w 10800, see chain.sh).
# usage: hold.sh <resultsdir> <P1|P2|H1|...|H8|fill:<cell>@<cfg>:<n>:<start>[,...]>
#   P1, P2 = pilot (results/<date>_pilot/, never scored); H1-H8 = main run (EXPERIMENT.md 9).
# Trial folders under <resultsdir>: one per configuration (off/, rec/, fo/, forec/, s2on/, s2off/).
# Before and after every hold: GPU users; the md5 of both bundles on both nodes; the RoCE port counters of both nodes;
# the full mlx5 kernel lines of both nodes (mlx5_<tag>_<node>.txt); the count of mlx5 command-error lines; rain's
# mlx5_1 firmware-command counters (debugfs, read-only). New mlx5 lines go to mlx5_new_<hold>.txt and are printed. A new
# command-error line or a growth of the firmware-command failure counters writes <resultsdir>/STOP_mlx5, and chain.sh
# runs no further hold (EXPERIMENT.md 8). cells.py writes STOP_config / STOP_left (EXPERIMENT.md 8); no cell runs once
# any STOP_* file exists.
set -u
R=${1:?resultsdir}; H=${2:?hold}
D=$(cd "$(dirname "$0")" && pwd)
G=$D/../../gpu-initiated/gin_recovery
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
export SUNNY_SSH
R0_MGMT=$(ip -4 -o addr show dev eno1 | awk '{print $4}' | cut -d/ -f1 | head -1)
export R0_MGMT
[ -n "$R0_MGMT" ] || { echo "no IPv4 address on eno1" >&2; exit 1; }
HT=$(echo "$H" | cut -d: -f1)
[ "$HT" = fill ] && HT=fill-$(date +%H%M%S)   # every replacement hold keeps its own snapshot files
CMDERR='grep -i mlx5 | grep -iE "cmd|command" | grep -icE "failed|timeout|leak"'
CNT="duplicate_request out_of_sequence packet_seq_err implied_nak_seq_err local_ack_timeout_err req_cqe_error req_cqe_flush_error resp_cqe_error resp_cqe_flush_error rnr_nak_retry_err roce_adp_retrans"
BMD5='cd $HOME/nb-bundle && md5sum n232/libnccl.so.2.32.3 n232/nb_ct s2/libnccl.so.2.23.4 s2/nb_ct'
snap() {  # snap <tag>
  echo "== $1 $(date '+%F %T')"
  nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader 2>/dev/null | sed 's/^/rain gpu: /'
  ssh -n "$SUNNY_SSH" "nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader" 2>/dev/null | sed 's/^/sunny gpu: /'
  PORTS='echo "kernel $(uname -r)"; for d in /sys/class/infiniband/*; do echo "$(basename $d) fw $(cat $d/fw_ver) port1 $(cat $d/ports/1/state)"; done'
  bash -c "$PORTS" 2>&1 | sed 's/^/rain: /'
  ssh -n "$SUNNY_SSH" "$PORTS" 2>&1 | sed 's/^/sunny: /'
  bash -c "$BMD5" 2>&1 | sed 's/^/rain bundle: /'
  ssh -n "$SUNNY_SSH" "$BMD5" 2>&1 | sed 's/^/sunny bundle: /'
  for c in $CNT; do echo "rain mlx5_1 $c $(cat /sys/class/infiniband/mlx5_1/ports/1/hw_counters/$c 2>/dev/null || echo NA)"; done
  ssh -n "$SUNNY_SSH" "for c in $CNT; do echo \"sunny mlx5_0 \$c \$(cat /sys/class/infiniband/mlx5_0/ports/1/hw_counters/\$c 2>/dev/null || echo NA)\"; done"
  sudo -n dmesg 2>/dev/null | grep -i mlx5 > "$R/mlx5_$1_rain.txt"
  ssh -n "$SUNNY_SSH" "sudo -n dmesg 2>/dev/null | grep -i mlx5" > "$R/mlx5_$1_sunny.txt"
  echo "rain mlx5 dmesg lines: $(wc -l < "$R/mlx5_$1_rain.txt")"
  echo "sunny mlx5 dmesg lines: $(wc -l < "$R/mlx5_$1_sunny.txt")"
  echo "rain mlx5 cmd_err lines: $(eval "cat $R/mlx5_$1_rain.txt | $CMDERR")"
  echo "sunny mlx5 cmd_err lines: $(eval "cat $R/mlx5_$1_sunny.txt | $CMDERR")"
  bash "$G/scripts/ts1/fwcmd_snapshot.sh" "$1" > "$R/fwcmd_$1.txt" 2>&1
  echo "rain fwcmd failed sum: $(awk '{for(i=1;i<=NF;i++) if($i ~ /^failed=|^failed_mbox_status=/){split($i,a,"="); s+=a[2]}} END{print s+0}' "$R/fwcmd_$1.txt")"
}
mkdir -p "$R"
snap "before-$HT" | tee "$R/snap_before-$HT.txt"
c() { python3 "$D/cells.py" "$R/$2" "$1" "$2" "${3:-1}" "${4:-1}"; }  # c <cell> <cfg> [n] [start]
next() { echo $(( $(ls "$R/$2" 2>/dev/null | grep -c "^${1}\.${2}_n[0-9]*_meta.txt") + 1 )); }  # next free number
inter() {  # inter <n> <cell@cfg> ...: n rounds, one trial of each key per round, in the order given
  local n=$1; shift
  for ((k = 1; k <= n; k++)); do for key in "$@"; do c "${key%@*}" "${key#*@}" 1 "$(next "${key%@*}" "${key#*@}")"; done; done
}
case "$H" in
  P1)  # pilot, part 1 (not scored): every send- and recv-QP cell key once, every overhead key once
    inter 1 sqp@off sqp@rec sqp@fo sqp@forec sqp@s2on sqp@s2off rqp@off rqp@fo rqp@forec rqp@s2on rqp@s2off \
      ovh64k@off ovh64k@fo ovh64k@forec ovh64k@s2on ovh64k@s2off ovh16m@off ovh16m@fo ovh16m@forec ovh16m@s2on ovh16m@s2off ;;
  P2)  # pilot, part 2 (not scored): every silent-fault and kill cell key once
    inter 1 slbc@off slbc@fo slbc@forec slbc@s2on slar@off slar@fo slar@forec slar@s2on \
      kill@off kill@fo kill@forec kill@s2on kill@s2off ;;
  H1)  # fault-free all-reduce time: 5 rounds over both sizes and the five configurations
    inter 5 ovh64k@off ovh64k@fo ovh64k@forec ovh64k@s2on ovh64k@s2off ovh16m@off ovh16m@fo ovh16m@forec ovh16m@s2on ovh16m@s2off ;;
  H2)  inter 5 sqp@off rqp@off sqp@rec sqp@s2on ;;
  H3)  inter 10 sqp@fo sqp@forec ;;
  H4)  inter 10 rqp@fo rqp@forec ;;
  H5)  inter 5 rqp@s2on sqp@s2off rqp@s2off kill@s2off ;;
  H6)  inter 5 slbc@off slbc@fo slbc@forec slbc@s2on ;;
  H7)  inter 5 slar@off slar@fo slar@forec slar@s2on ;;
  H8)  inter 5 kill@off kill@fo kill@forec kill@s2on ;;
  fill:*)  # replacement trials (EXPERIMENT.md 8): fill:<cell>@<cfg>:<n>:<start>[,...]
    spec=${H#fill:}
    IFS=',' read -ra items <<< "$spec"
    for it in "${items[@]}"; do
      IFS=':' read -r key n st <<< "$it"
      c "${key%@*}" "${key#*@}" "$n" "$st"
    done ;;
  *) echo "unknown hold $H" >&2; exit 2 ;;
esac
snap "after-$HT" | tee "$R/snap_after-$HT.txt"
for node in rain sunny; do
  diff <(sort "$R/mlx5_before-${HT}_$node.txt") <(sort "$R/mlx5_after-${HT}_$node.txt") | grep '^>' | sed "s/^> /$node: /"
done > "$R/mlx5_new_$HT.txt"
echo "new mlx5 kernel lines in hold $HT: $(wc -l < "$R/mlx5_new_$HT.txt")"; cat "$R/mlx5_new_$HT.txt"
b=$(grep -h "cmd_err lines\|fwcmd failed sum" "$R/snap_before-$HT.txt" | awk -F': ' '{s+=$2} END{print s+0}')
a=$(grep -h "cmd_err lines\|fwcmd failed sum" "$R/snap_after-$HT.txt" | awk -F': ' '{s+=$2} END{print s+0}')
if [ "$a" -gt "$b" ]; then
  echo "$(date '+%F %T') hold $H: mlx5 command errors or firmware-command failures grew ($b -> $a)" | tee -a "$R/STOP_mlx5"
fi
