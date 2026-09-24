#!/usr/bin/env bash
# apply_peermapping.sh - make /etc/modprobe.d/nvidia-peermapping.conf take effect now,
# without a reboot (2026-09-24, at the user's request: PeerMappingOverride on permanently).
#
# One reload of the nvidia module stack on both nodes with plain `modprobe`, so the
# config file supplies NVreg_RegistryDwords="PeerMappingOverride=1;" and
# NVreg_EnableStreamMemOPs=1. On rain the GPU users (the user's mooncake_client and the gdm
# greeter) are stopped first and restarted afterwards exactly as window.sh does; sunny has
# no GPU user. tmux sessions and other processes are not touched.
# Run under ../common/cluster_run.sh so no experiment uses the GPUs meanwhile.
set -u
S=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/gi/modreload
LOG="$S/apply_peermapping.log"
UNLOAD="nvidia_peermem nvidia_fs nvidia_drm nvidia_modeset nvidia_uvm nvidia"
LOAD_AFTER="nvidia_uvm nvidia_modeset nvidia_drm nvidia_peermem nvidia_fs"
log() { echo "$(date '+%F %T') $*" | tee -a "$LOG" >&2; }
on_sunny() { ssh -n -o ConnectTimeout=8 sunny "$@"; }

for f in /etc/modprobe.d/nvidia-peermapping.conf; do
  grep -q 'PeerMappingOverride=1' "$f" || { log "rain: $f missing the option; stop"; exit 2; }
  on_sunny "grep -q PeerMappingOverride=1 $f" || { log "sunny: $f missing the option; stop"; exit 2; }
done

MC_PID=$(pgrep -x mooncake_client || true)
if [ -n "$MC_PID" ]; then
  sudo -n cat /proc/$MC_PID/cmdline | tr '\0' '\n' > "$S/mooncake_cmdline.txt"
  sudo -n cat /proc/$MC_PID/environ | tr '\0' '\n' > "$S/mooncake_environ.txt"
  sudo -n readlink /proc/$MC_PID/cwd > "$S/mooncake_cwd.txt"
  sudo -n readlink /proc/$MC_PID/fd/1 > "$S/mooncake_out.txt"
fi

restart_users() {
  sudo -n systemctl start gdm
  if [ -n "$MC_PID" ]; then
    mapfile -t CMDV < "$S/mooncake_cmdline.txt"; mapfile -t ENVV < "$S/mooncake_environ.txt"
    ( cd "$(cat $S/mooncake_cwd.txt)" && env -i "${ENVV[@]}" setsid nohup "${CMDV[@]}" \
        >> "$(cat $S/mooncake_out.txt)" 2>&1 < /dev/null 9>&- & )
    sleep 5
    log "mooncake_client restarted: $(pgrep -a -x mooncake_client | cut -c1-100)"
  fi
}

reload() {  # $1 = rain|sunny
  local cmd="set -e; for m in $UNLOAD; do if lsmod | grep -q \"^\$m \"; then sudo -n rmmod \$m; fi; done;
    sudo -n modprobe nvidia; for m in $LOAD_AFTER; do sudo -n modprobe \$m; done;
    grep -E 'RegistryDwords:|EnableStreamMemOPs' /proc/driver/nvidia/params"
  log "reload $1"
  if [ "$1" = rain ]; then bash -c "$cmd" >>"$LOG" 2>&1; else on_sunny "$cmd" >>"$LOG" 2>&1; fi
}

log "=== apply start mooncake=$MC_PID"
if on_sunny 'pgrep -x gdsio >/dev/null'; then log "gdsio running on sunny; stop"; exit 75; fi
[ -n "$MC_PID" ] && { kill -TERM "$MC_PID"; for i in $(seq 1 30); do kill -0 "$MC_PID" 2>/dev/null || break; sleep 1; done; kill -0 "$MC_PID" 2>/dev/null && kill -KILL "$MC_PID"; }
sudo -n systemctl stop gdm; sleep 3
for n in rain sunny; do
  if [ $n = rain ]; then u=$(sudo -n fuser /dev/nvidia* 2>/dev/null | tr -s ' '); else u=$(on_sunny 'sudo -n fuser /dev/nvidia* 2>/dev/null | tr -s " "'); fi
  if [ -n "$u" ]; then log "$n GPU still in use by:$u; restarting users and stopping"; restart_users; exit 3; fi
done
rc=0
reload rain || { log "!! rain reload failed"; rc=4; }
reload sunny || { log "!! sunny reload failed"; rc=4; }
restart_users
for n in rain sunny; do
  if [ $n = rain ]; then r=$("$S/cudacheck_gi" 2>&1); d=$(grep RegistryDwords: /proc/driver/nvidia/params)
  else r=$(on_sunny /tmp/cudacheck_gi 2>&1); d=$(on_sunny 'grep RegistryDwords: /proc/driver/nvidia/params'); fi
  u=$( ( [ $n = rain ] && bash -c 'echo uvm $(awk "\$2==\"nvidia-uvm\"{print \$1}" /proc/devices) node $(stat -c %t /dev/nvidia-uvm)' ) || on_sunny 'echo uvm $(awk "\$2==\"nvidia-uvm\"{print \$1}" /proc/devices) node $(stat -c %t /dev/nvidia-uvm)')
  log "$n: $d | $r | $u"
  case "$r" in CUDA_OK*) ;; *) rc=5 ;; esac
done
log "=== apply done rc=$rc"
exit $rc
