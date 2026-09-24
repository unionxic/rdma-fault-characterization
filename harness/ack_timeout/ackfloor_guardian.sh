#!/usr/bin/env bash
# ackfloor_guardian.sh - detached helper of ackfloor_window.sh (started with setsid).
# Waits until the window process (pid + /proc start time) is gone. If the window did not
# leave its "restored" marker (e.g. it was SIGKILLed), writes back the recorded value of
# ROCE_ACCL.min_ack_timeout_limit_disabled on rain's 17:00.1 (only that field) and logs
# the full register state. Gives up waiting after 2 h (windows are < 15 min).
#   ackfloor_guardian.sh <window_pid> <window_starttime> <before_value> <done_marker> <log> <tag> <stamp>
set -u
WPID=$1; WSTART=$2; BVAL=$3; MARK=$4; LOG=$5; TAG=$6; STAMP=$7
DEV=17:00.1; FIELD=min_ack_timeout_limit_disabled
SEL="roce_adp_retrans_field_select=0,roce_tx_window_field_select=0,roce_slow_restart_field_select=0,roce_slow_restart_idle_field_select=0,${FIELD}_field_select=1,adaptive_routing_forced_en_field_select=0,selective_repeat_forced_en_field_select=0,dc_half_handshake_en_field_select=0,ack_dscp_force_field_select=0"
log() { echo "$(date '+%F %T.%3N') [$TAG guardian pid=$$ stamp=$STAMP] $*" >> "$LOG"; }
cur() { sudo -n mlxreg -d "$DEV" --reg_name ROCE_ACCL --get 2>&1 | awk -F'|' -v f="$FIELD" '{n=$1; v=$2; gsub(/[ \t]/,"",n); gsub(/[ \t]/,"",v); if (n==f) print v}'; }
end=$(( $(date +%s) + 7200 ))
while [ "$(awk '{print $22}' /proc/"$WPID"/stat 2>/dev/null)" = "$WSTART" ]; do
  sleep 0.5
  [ "$(date +%s)" -gt "$end" ] && { log "window still alive after 2 h; guardian exits without action"; exit 0; }
done
if [ -e "$MARK" ]; then
  log "window $WPID gone, restore marker present (clean exit); nothing to do"
  exit 0
fi
v=$(cur)
log "window $WPID gone WITHOUT restore marker; $FIELD currently $v"
if [ "$v" != "$BVAL" ]; then
  for attempt in 1 2 3; do
    sudo -n mlxreg -d "$DEV" --reg_name ROCE_ACCL --yes --set "$SEL,$FIELD=$BVAL" >/dev/null 2>&1
    v=$(cur)
    [ "$v" = "$BVAL" ] && break
    sleep 1
  done
fi
log "guardian result: $FIELD=$v (want $BVAL); full state: $(sudo -n mlxreg -d "$DEV" --reg_name ROCE_ACCL --get 2>&1 | awk -F'|' 'NF==2 && $1 !~ /Field/ {n=$1; v=$2; gsub(/[ \t]/,"",n); gsub(/[ \t]/,"",v); if (n !~ /field_select/) printf "%s=%s ", n, v}')"
[ "$v" = "$BVAL" ] && touch "$MARK.guardian"
