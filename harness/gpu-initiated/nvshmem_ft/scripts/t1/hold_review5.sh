#!/usr/bin/env bash
# hold_review5.sh - the review5 spec in one cluster hold; any iptables rule of the socket test left
# behind (comment t1sock) is removed at the end and counted.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
CR=$HERE/../../../common/cluster_run.sh
R=${R:-$HERE/../../results/20260930_t1}
cd "$HERE/../.."
$CR -t t1-review5 -- timeout -s KILL 880 bash -c "INTERLEAVE=0 STOP_AFTER_S=780 bash scripts/t1/hold_generic.sh scripts/t1/specs/review5.txt $R/review5; sudo -n iptables -S | grep t1sock | sed 's/^-A/-D/' | while read -r r; do sudo -n iptables \$r; done; echo iptables_t1sock_left=\$(sudo -n iptables -S | grep -c t1sock)"
