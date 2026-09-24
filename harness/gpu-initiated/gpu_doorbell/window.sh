#!/usr/bin/env bash
# window.sh - run the GPU-rung-doorbell experiments inside ONE driver-reload window.
#
# The GPU can only ring the NIC doorbell itself (true IBGDA / GDAKI) when the nvidia
# module is loaded with NVreg_RegistryDwords="PeerMappingOverride=1;". This script
#   enter:   stops every GPU user on rain (the user's mooncake_client, two stale
#            nvidia-smi monitors that write into deleted files, and the gdm greeter),
#            then reloads the nvidia module stack on rain and sunny with the override
#            (modprobe parameters only; /etc/modprobe.d is not touched);
#   run:     the experiments in experiments.sh (bounded);
#   exit:    reloads the stack again with the original parameters, restarts gdm and
#            mooncake_client with its original command line, environment, cwd and log.
# Restoring runs from an EXIT trap, so it also happens after a failure.
# The stale nvidia-smi monitors are not restarted: their output files were deleted.
#
# usage (must hold the cluster lock):
#   common/cluster_run.sh -w 7200 -t gpu-doorbell -- gpu_doorbell/window.sh [--dry-run]
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
S=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/gi/modreload
mkdir -p "$S"
LOG="$S/window.log"
DRY=0; [ "${1:-}" = --dry-run ] && DRY=1

UNLOAD="nvidia_peermem nvidia_fs nvidia_drm nvidia_modeset nvidia_uvm nvidia"
LOAD_AFTER="nvidia_uvm nvidia_modeset nvidia_drm nvidia_peermem nvidia_fs"
# Single quotes survive into `bash -c` / ssh, so the ';' stays inside the value.
OVERRIDE="NVreg_RegistryDwords='PeerMappingOverride=1;' NVreg_EnableStreamMemOPs=1"

log() { echo "$(date '+%F %T') $*" | tee -a "$LOG" >&2; }
run() { log "+ $*"; [ $DRY = 1 ] || "$@"; }
on_sunny() { ssh -n -o ConnectTimeout=8 sunny "$@"; }

# ---- the user's GPU processes on rain ------------------------------------------------
MC_PID=$(pgrep -x mooncake_client || true)
MC_CMD="$S/mooncake_cmdline.txt"; MC_ENV="$S/mooncake_environ.txt"
if [ -n "$MC_PID" ]; then
  sudo -n cat /proc/$MC_PID/cmdline | tr '\0' '\n' > "$MC_CMD"
  sudo -n cat /proc/$MC_PID/environ | tr '\0' '\n' > "$MC_ENV"
  MC_CWD=$(sudo -n readlink /proc/$MC_PID/cwd); MC_OUT=$(sudo -n readlink /proc/$MC_PID/fd/1)
  echo "$MC_CWD" > "$S/mooncake_cwd.txt"; echo "$MC_OUT" > "$S/mooncake_out.txt"
fi
# Only the long-running monitors (older than a day), never a short nvidia-smi call.
STALE=$(ps -eo pid=,etimes=,cmd= | awk '$2 > 86400 && $3 == "nvidia-smi" {print $1}')
HOSTMON=$(pgrep -f '^bash /home/unionxic/experiments/vllm-gds-kv/lib/obs/hostmon.sh' || true)

stop_rain_users() {
  if [ -n "$MC_PID" ]; then
    run kill -TERM "$MC_PID"
    if [ $DRY = 0 ]; then
      for i in $(seq 1 30); do kill -0 "$MC_PID" 2>/dev/null || break; sleep 1; done
      kill -0 "$MC_PID" 2>/dev/null && run kill -KILL "$MC_PID"
    fi
  fi
  [ -n "$HOSTMON" ] && run kill -TERM $HOSTMON
  [ -n "$STALE" ] && run kill -TERM $STALE
  run sudo -n systemctl stop gdm
  sleep 3
}

gpu_users() {  # prints users of /dev/nvidia* on the node ("" = none)
  if [ "$1" = rain ]; then sudo -n fuser /dev/nvidia* 2>/dev/null | tr -s ' '
  else on_sunny 'sudo -n fuser /dev/nvidia* 2>/dev/null | tr -s " "'; fi
}

reload_node() {  # $1 node, $2 override|orig
  local node=$1 mode=$2 params="" cmd
  [ "$mode" = override ] && params="$OVERRIDE"
  cmd="set -e; for m in $UNLOAD; do if lsmod | grep -q \"^\$m \"; then sudo -n rmmod \$m; fi; done;
       sudo -n modprobe nvidia $params; for m in $LOAD_AFTER; do sudo -n modprobe \$m; done;
       grep -E 'RegistryDwords:|EnableStreamMemOPs' /proc/driver/nvidia/params; nvidia-smi -L"
  log "reload $node ($mode)"
  [ $DRY = 1 ] && { log "  (dry) $cmd"; return 0; }
  if [ "$node" = rain ]; then bash -c "$cmd" >>"$LOG" 2>&1; else on_sunny "$cmd" >>"$LOG" 2>&1; fi
}

restore() {
  local rc=$?
  trap - EXIT
  log "restore (exit code so far $rc)"
  if [ $DRY = 0 ]; then   # our experiment binaries only (we hold the cluster lock)
    pkill -x nvshmem_fault 2>/dev/null; pkill -x gin_q4 2>/dev/null
    on_sunny 'pkill -x nvshmem_fault; pkill -x gin_q4; true' 2>/dev/null
    sleep 2
  fi
  for n in rain sunny; do
    if ! reload_node $n orig; then
      log "!! reload $n with original parameters FAILED; trying to load whatever is missing"
      if [ $n = rain ]; then bash -c "sudo -n modprobe nvidia; for m in $LOAD_AFTER; do sudo -n modprobe \$m; done" >>"$LOG" 2>&1
      else on_sunny "sudo -n modprobe nvidia; for m in $LOAD_AFTER; do sudo -n modprobe \$m; done" >>"$LOG" 2>&1; fi
    fi
  done
  run sudo -n systemctl start gdm
  if [ -n "$MC_PID" ] && [ $DRY = 0 ]; then
    mapfile -t CMDV < "$MC_CMD"; mapfile -t ENVV < "$MC_ENV"
    # 9>&-: never hand the cluster lock fd to the user's long-running process.
    ( cd "$(cat $S/mooncake_cwd.txt)" && env -i "${ENVV[@]}" setsid nohup "${CMDV[@]}" \
        >> "$(cat $S/mooncake_out.txt)" 2>&1 < /dev/null 9>&- & )
    sleep 5
    log "mooncake_client restarted: $(pgrep -a -x mooncake_client | cut -c1-120)"
  fi
  log "after restore: rain $(grep RegistryDwords: /proc/driver/nvidia/params | tr -s ' ') | sunny $(on_sunny 'grep RegistryDwords: /proc/driver/nvidia/params' | tr -s ' ')"
  log "window done (rc=$rc)"
  exit $rc
}

# ---- enter ----------------------------------------------------------------------------
log "=== window start (dry=$DRY) mooncake=$MC_PID stale_smi=[$STALE] hostmon=[$HOSTMON]"
if on_sunny 'pgrep -x gdsio >/dev/null'; then log "gdsio is running on sunny; not starting"; exit 75; fi
trap restore EXIT
stop_rain_users
for n in rain sunny; do
  u=$(gpu_users $n)
  if [ -n "$u" ] && [ $DRY = 0 ]; then log "GPU still in use on $n by PIDs:$u; aborting"; exit 3; fi
  log "$n GPU users: ${u:-none}"
done
reload_node rain override || { log "rain reload failed"; exit 4; }
reload_node sunny override || { log "sunny reload failed"; exit 4; }

# A reload can move the dynamic char-device majors (window 1: sunny's nvidia-uvm moved
# 509 -> 511 while /dev/nvidia-uvm still said 509, so every CUDA init failed). Check
# CUDA on both nodes before running anything; on failure, restore and stop.
if [ $DRY = 0 ]; then
  CC="$S/cudacheck_gi"
  if ! "$CC" >>"$LOG" 2>&1 || ! on_sunny /tmp/cudacheck_gi >>"$LOG" 2>&1; then
    log "CUDA check failed after the override reload; restoring without running"
    exit 5
  fi
fi

# ---- run ------------------------------------------------------------------------------
EXPERIMENTS=${EXPERIMENTS:-$HERE/experiments.sh}
if [ $DRY = 0 ]; then
  timeout 3000 bash "$EXPERIMENTS" 2>&1 | tee -a "$LOG"
  log "experiments exit: ${PIPESTATUS[0]}"
fi
exit 0
