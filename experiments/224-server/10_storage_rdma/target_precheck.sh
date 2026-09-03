#!/bin/bash
# target_precheck.sh — READ-ONLY environment check for the Phase-1 target (224).
# Verifies kernel modules, configfs, dm targets, and userspace tools. Makes NO
# changes. Prints a PASS/FAIL table and exits non-zero if any REQUIRED item
# fails. Run: sudo ./target_precheck.sh  (some checks need root to load/inspect).

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib_storage.sh
source "${HERE}/lib_storage.sh"

pass=0; fail=0
row() { # <name> <ok|warn|fail> <detail>
  local st="$2"
  printf '  %-28s %-6s %s\n' "$1" "[$st]" "${3:-}"
  case "$st" in
    ok)   pass=$((pass+1));;
    fail) fail=$((fail+1));;
  esac
}

echo "=== target_precheck (node 224, target/responder) ==="
echo "RDMA device : $(rdma_device)   RDMA IP: ${RDMA_IP}:${RDMA_SVCID}"
echo

echo "-- kernel modules (REQUIRED) --"
for m in nvmet nvmet_rdma; do
  # modules may be builtin or loadable; accept either.
  if modinfo "$m" >/dev/null 2>&1 || grep -qw "$m" /proc/modules 2>/dev/null; then
    row "$m" ok "$(modinfo -F filename "$m" 2>/dev/null || echo builtin)"
  else
    row "$m" fail "modinfo/proc both miss it"
  fi
done

echo "-- dm fault-injection targets (REQUIRED) --"
# dm targets register under /proc as they get used; probe via modinfo/dmsetup.
for m in dm_flakey dm_delay; do
  if modinfo "$m" >/dev/null 2>&1 || grep -qw "$m" /proc/modules 2>/dev/null; then
    row "$m" ok "$(modinfo -F filename "$m" 2>/dev/null || echo builtin)"
  else
    row "$m" fail "not found (modprobe ${m//_/-})"
  fi
done
# dm-dust is OPTIONAL: target_setup falls back to a linear+error composite
# table (core dm targets, always present) when dust is missing.
if modinfo dm_dust >/dev/null 2>&1 || grep -qw dm_dust /proc/modules 2>/dev/null; then
  row "dm_dust" ok "$(modinfo -F filename dm_dust 2>/dev/null || echo builtin)"
elif dmsetup targets 2>/dev/null | awk '{print $1}' | grep -qx error; then
  row "dm_dust" ok "absent — using linear+error composite fallback"
else
  row "dm_dust" fail "no dust AND no error target (dmsetup targets)"
fi
# dmsetup targets listing (informational — shows what is currently registered)
if command -v dmsetup >/dev/null 2>&1; then
  targets="$(dmsetup targets 2>/dev/null | awk '{print $1}' | tr '\n' ' ')"
  row "dmsetup targets" ok "${targets:-<none loaded yet>}"
else
  row "dmsetup" fail "not installed (apt install dmsetup)"
fi

echo "-- configfs / nvmet (REQUIRED) --"
if [ -d /sys/kernel/config ]; then
  row "configfs mounted" ok "/sys/kernel/config"
else
  row "configfs mounted" fail "mount -t configfs none /sys/kernel/config"
fi
if [ -d "$CFG" ]; then
  row "nvmet configfs" ok "$CFG"
else
  row "nvmet configfs" warn "$CFG absent (appears after modprobe nvmet)"
fi

echo "-- userspace tools --"
for t in nvme fio losetup truncate findmnt lsblk cc; do
  if command -v "$t" >/dev/null 2>&1; then
    row "$t" ok "$(command -v "$t")"
  else
    # nvme/fio not strictly needed on target, cc needed for pattern_write.
    if [ "$t" = cc ]; then row "$t" fail "needed to build pattern_write (apt install gcc)"
    else row "$t" warn "not found (target may not need it)"; fi
  fi
done

echo "-- backing storage safety --"
if [ -d "$BACKING_DIR" ]; then
  row "backing dir" ok "$BACKING_DIR"
else
  row "backing dir" warn "$BACKING_DIR absent (target_setup creates it)"
fi
root_disk="$(lsblk -no PKNAME "$(findmnt -no SOURCE / 2>/dev/null)" 2>/dev/null | head -1 || true)"
row "boot/root disk" ok "${root_disk:-unknown} — will be REFUSED by asserts"

echo
echo "=== summary: ${pass} ok, ${fail} fail ==="
[ "$fail" = 0 ] || { echo "FAIL: resolve the [fail] rows before running experiments." >&2; exit 1; }
echo "target precheck PASSED."
