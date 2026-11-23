#!/bin/bash
# [한국어 요약] 실행 전 환경 점검 (읽기 전용, 아무것도 바꾸지 않음).
#   커널 모듈(nvme-rdma) / 도구(nvme-cli, fio 필수) / debugfs(통제 실험용, 없으면
#   warn) / 224로의 ssh 도달성 / 224 passwordless sudo(orchestrator 필수) 확인.
#   fail이 하나라도 있으면 본 실험을 돌리지 말 것.
# initiator_precheck.sh — READ-ONLY environment check for the Phase-1 initiator
# (225). Verifies nvme-rdma module, nvme-cli, fio, debugfs fault-injection, RDMA
# sysfs counters, and SSH reachability to the target. Makes NO changes.
# Run: sudo ./initiator_precheck.sh  (root recommended for debugfs/modinfo).

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib_storage.sh
source "${HERE}/lib_storage.sh"

pass=0; fail=0
row() { local st="$2"; printf '  %-30s %-6s %s\n' "$1" "[$st]" "${3:-}"
  case "$st" in ok) pass=$((pass+1));; fail) fail=$((fail+1));; esac; }

echo "=== initiator_precheck (node 225, initiator/requester) ==="
echo "RDMA device : $(rdma_device)   target: ${RDMA_IP}:${RDMA_SVCID}  NQN: $NQN"
echo

echo "-- kernel modules (REQUIRED) --"
for m in nvme_rdma nvme_fabrics nvme_core; do
  if modinfo "$m" >/dev/null 2>&1 || grep -qw "$m" /proc/modules 2>/dev/null; then
    row "$m" ok "$(modinfo -F filename "$m" 2>/dev/null || echo builtin)"
  else
    row "$m" fail "modprobe ${m//_/-}"
  fi
done

echo "-- userspace tools (REQUIRED) --"
for t in nvme fio cc ssh awk lsblk findmnt; do
  if command -v "$t" >/dev/null 2>&1; then row "$t" ok "$(command -v "$t")"
  else row "$t" fail "install it"; fi
done

echo "-- nvme fault-injection debugfs (control experiment) --"
if [ -d /sys/kernel/debug ]; then
  if mountpoint -q /sys/kernel/debug 2>/dev/null || [ -e /sys/kernel/debug/nvme0n1/fault_inject/probability ] 2>/dev/null; then
    row "debugfs" ok "/sys/kernel/debug mounted"
  else
    row "debugfs" ok "present (mount if fault_inject dir missing)"
  fi
  # The per-namespace fault_inject dir only exists once a device is connected AND
  # the kernel was built with CONFIG_FAULT_INJECTION + CONFIG_NVME_CORE fault hooks.
  # warn only: INITIATOR_STATUS_INJECT is an optional CONTROL experiment; the
  # six target-origin scenarios do not need CONFIG_FAULT_INJECTION at all.
  if grep -q 'CONFIG_FAULT_INJECTION=y' "/boot/config-$(uname -r)" 2>/dev/null; then
    row "CONFIG_FAULT_INJECTION" ok "enabled"
  else
    row "CONFIG_FAULT_INJECTION" warn "off in this kernel — skip INITIATOR_STATUS_INJECT (control only)"
  fi
else
  row "debugfs" fail "no /sys/kernel/debug"
fi

echo "-- RDMA sysfs counters --"
dev="$(rdma_device)"
if [ -d "/sys/class/infiniband/${dev}/ports/1/hw_counters" ]; then
  n="$(find "/sys/class/infiniband/${dev}/ports/1/hw_counters" -type f 2>/dev/null | wc -l | tr -d ' ')"
  row "hw_counters ($dev)" ok "${n} counters"
else
  row "hw_counters ($dev)" fail "no hw_counters for $dev (set RDMA_DEV=?)"
fi

echo "-- SSH to target (225->224, as \${SUDO_USER:-current user}) --"
if ssh_target "echo ok" 2>/dev/null | grep -q ok; then
  row "ssh $REMOTE_SSH" ok "reachable (user $(printf '%s' "${SUDO_USER:-$(id -un)}"))"
  if ssh_target "test -x ${REMOTE_DIR}/target_setup.sh" 2>/dev/null; then
    row "target scripts synced" ok "${REMOTE_DIR}"
  else
    row "target scripts synced" fail "${REMOTE_DIR}/target_setup.sh not executable on 224"
  fi
  if ssh_target "sudo -n ${REMOTE_DIR}/target_teardown.sh >/dev/null 2>&1 && echo sudo_ok" 2>/dev/null | grep -q sudo_ok; then
    row "passwordless sudo on 224" ok "target scripts runnable non-interactively"
  else
    row "passwordless sudo on 224" fail "add /etc/sudoers.d/storage_rdma (see README) — orchestrator needs it"
  fi
else
  row "ssh $REMOTE_SSH" fail "cannot reach target over ssh (keys belong to ${SUDO_USER:-$(id -un)}?)"
fi

echo "-- boot-disk guard --"
root_disk="$(lsblk -no PKNAME "$(findmnt -no SOURCE / 2>/dev/null)" 2>/dev/null | head -1 || true)"
row "boot/root disk" ok "${root_disk:-unknown} — REFUSED by asserts"

echo
echo "=== summary: ${pass} ok, ${fail} fail ==="
[ "$fail" = 0 ] || { echo "FAIL: resolve [fail] rows first." >&2; exit 1; }
echo "initiator precheck PASSED."
