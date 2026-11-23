#!/usr/bin/env bash
# test_window.sh - exercise every restore path of ackfloor_window.sh before first real use.
# Run inside cluster_run.sh. Each case prints the register value before and after.
#   1 trivial command (true)                     -> normal exit, restore
#   2 value inside the window                    -> must read 1 inside
#   3 command killed (SIGKILL to the command)    -> window sees rc 137, restore
#   4 window gets SIGTERM while the command runs -> trap stops the command group, restore
#   5 window gets SIGKILL                        -> no trap; the guardian restores
#   6 not under the cluster lock (fresh lock file that nobody holds) -> refuse, register untouched
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
W=$HERE/../ackfloor_window.sh
val() { sudo -n mlxreg -d 17:00.1 --reg_name ROCE_ACCL --get 2>&1 | awk -F'|' '{n=$1; v=$2; gsub(/[ \t]/,"",n); gsub(/[ \t]/,"",v); if (n=="min_ack_timeout_limit_disabled") print v}'; }
say() { echo "[test $(date +%T.%3N)] $*"; }

say "case 1 (true): before=$(val)"
"$W" -t t1_true -- true; say "case 1 rc=$? after=$(val)"

say "case 2 (read inside): before=$(val)"
"$W" -t t2_inside -- bash -c 'echo "inside: $(sudo -n mlxreg -d 17:00.1 --reg_name ROCE_ACCL --get | grep "^min_ack_timeout_limit_disabled ")"'
say "case 2 rc=$? after=$(val)"

say "case 3 (command SIGKILLed): before=$(val)"
"$W" -t t3_cmdkill -- sleep 30 & WP=$!
for i in $(seq 1 50); do CP=$(pgrep -P "$WP" -x sleep); [ -n "$CP" ] && break; sleep 0.1; done
sleep 2; say "inside: $(val); killing command pid $CP with SIGKILL"; kill -KILL "$CP"
wait "$WP"; say "case 3 rc=$? after=$(val)"

say "case 4 (window SIGTERM): before=$(val)"
"$W" -t t4_winterm -- sleep 30 & WP=$!
for i in $(seq 1 50); do CP=$(pgrep -P "$WP" -x sleep); [ -n "$CP" ] && break; sleep 0.1; done
sleep 2; say "inside: $(val); SIGTERM to window pid $WP (command pid $CP)"; kill -TERM "$WP"
wait "$WP"; say "case 4 rc=$? after=$(val); command alive? $(kill -0 "$CP" 2>/dev/null && echo yes || echo no)"

say "case 5 (window SIGKILL): before=$(val)"
"$W" -t t5_winkill -- sleep 20 & WP=$!
for i in $(seq 1 50); do CP=$(pgrep -P "$WP" -x sleep); [ -n "$CP" ] && break; sleep 0.1; done
sleep 2; say "inside: $(val); SIGKILL to window pid $WP"; kill -KILL "$WP"
wait "$WP" 2>/dev/null; say "right after SIGKILL: $(val)"
for i in $(seq 1 40); do [ "$(val)" = 0x00000000 ] && break; sleep 0.25; done
say "case 5 after guardian: $(val) (waited ~$((i / 4)) s)"
kill -KILL "$CP" 2>/dev/null; say "orphaned command pid $CP killed"

say "case 6 (no cluster lock held): before=$(val)"
FREE=$(mktemp /tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/agent_ack/freelock.XXXX)
CLUSTER_LOCK=$FREE "$W" -t t6_nolock -- true; say "case 6 rc=$? (expect 64) after=$(val)"
rm -f "$FREE"
sleep 1
say "final: $(val)"
