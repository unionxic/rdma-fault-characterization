#!/usr/bin/env bash
# gid_blackhole.sh - a real path fault for RoCE QPs without touching the link or the storage.
#
# The rain<->sunny RoCE link also carries the user's NVMe-oF (primary addresses 30.0.0.3/.4).
# This script gives each RoCE netdev a SECONDARY IPv4 address in another subnet
# (30.0.1.3/24 on rain, 30.0.1.4/24 on sunny), which creates new RoCE v2 GIDs. Test QPs use
# those GIDs. To cut the path it removes sunny's secondary address for OUTAGE seconds and adds it
# back: packets of the test QPs lose their GID while every other GID (and the storage traffic on
# the primary addresses) is untouched. Nothing changes the QPs' state; the NICs retransmit, and
# if the outage is longer than the retry budget the requester gets RETRY_EXC.
#
# usage: gid_blackhole.sh setup            add the secondary addresses, print the GID indices
#        gid_blackhole.sh cut <outage_s>   remove sunny's secondary address, sleep, add it back
#        gid_blackhole.sh teardown         remove both secondary addresses
#        gid_blackhole.sh gids             print the RoCE v2 GID index of 30.0.1.x on each node
# Always pair setup with teardown (the runner does it in an EXIT trap). Run under cluster_run.sh.
set -u
R_IF=ens4f1np1;   R_DEV=mlx5_1; R_ADDR=30.0.1.3/24
S_IF=enp23s0f0np0; S_DEV=mlx5_0; S_ADDR=30.0.1.4/24
SUNNY=${SUNNY:-unionxic@192.0.2.194}
LOG=${GBH_LOG:-/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/gid_blackhole.log}
log() { echo "$(date '+%F %T.%N' | cut -c1-23) $*" | tee -a "$LOG" >&2; }
on_sunny() { ssh -n -o ConnectTimeout=5 -o BatchMode=yes "$SUNNY" "$@"; }

gid_of() {  # $1 dev, $2 ipv4 -> RoCE v2 GID index
  local d=/sys/class/infiniband/$1/ports/1 hex
  hex=$(printf '%02x%02x:%02x%02x' $(echo "$2" | tr . ' '))
  for g in $(ls $d/gids | sort -n); do
    [ "$(cat $d/gid_attrs/types/$g 2>/dev/null)" = "RoCE v2" ] || continue
    [ "$(cat $d/gids/$g)" = "0000:0000:0000:0000:0000:ffff:$hex" ] && { echo $g; return 0; }
  done
  return 1
}
GID_FN=$(declare -f gid_of)

nvme_errs() {  # count of nvme error lines in sunny's kernel log (read-only)
  on_sunny "sudo -n dmesg 2>/dev/null | grep -c -i -E 'nvme.*(error|reset|reconnect|timeout)' || true" 2>/dev/null
}

case "${1:-}" in
  setup)
    log "setup: nvme error lines on sunny before: $(nvme_errs)"
    sudo -n ip addr add $R_ADDR dev $R_IF 2>/dev/null || log "rain: $R_ADDR already present?"
    on_sunny "sudo -n ip addr add $S_ADDR dev $S_IF" 2>/dev/null || log "sunny: $S_ADDR already present?"
    sleep 1
    g0=$(gid_of $R_DEV ${R_ADDR%/*}); g1=$(on_sunny "$GID_FN; gid_of $S_DEV ${S_ADDR%/*}")
    log "setup done: rain $R_DEV gid=$g0, sunny $S_DEV gid=$g1"
    echo "$g0 $g1"
    ;;
  gids)
    echo "$(gid_of $R_DEV ${R_ADDR%/*}) $(on_sunny "$GID_FN; gid_of $S_DEV ${S_ADDR%/*}")"
    ;;
  cut)
    t=${2:?outage seconds}
    log "cut: removing sunny $S_ADDR for ${t}s"
    on_sunny "sudo -n ip addr del $S_ADDR dev $S_IF && sleep $t && sudo -n ip addr add $S_ADDR dev $S_IF"
    rc=$?
    g1=$(on_sunny "$GID_FN; gid_of $S_DEV ${S_ADDR%/*}")
    log "cut: restored rc=$rc, sunny gid now=$g1"
    ;;
  teardown)
    sudo -n ip addr del $R_ADDR dev $R_IF 2>/dev/null
    on_sunny "sudo -n ip addr del $S_ADDR dev $S_IF" 2>/dev/null
    log "teardown: rain has $(ip -br addr show $R_IF), sunny has $(on_sunny "ip -br addr show $S_IF"); nvme error lines on sunny: $(nvme_errs)"
    ;;
  *) echo "usage: $0 setup|gids|cut <s>|teardown" >&2; exit 2 ;;
esac
