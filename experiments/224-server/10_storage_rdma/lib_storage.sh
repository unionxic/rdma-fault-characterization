#!/bin/bash
# [한국어 요약] target(224) 공용 라이브러리 — 상수(라벨/경로/NQN)와 안전 assert.
#   핵심 안전 철학: 224의 유일한 디스크 = 부팅 디스크이므로, dm/nvmet에 닿는
#   디바이스는 반드시 $BACKING_DIR의 파일 기반 loop여야 한다. assert 3종
#   (실디스크 거부 / loop 강제 / dm slave 전수 검사)이 그 하드 게이트.
# lib_storage.sh — shared constants + safety asserts + sysfs counter snapshot
# for the Phase-1 (SSD x RDMA) target side (node 224).
#
# Sourced by target_precheck.sh / target_setup.sh / target_teardown.sh /
# target_crash.sh. NOT executable on its own. All functions assume
# `set -euo pipefail` in the sourcing script.
#
# Safety philosophy (see README): 224's ONLY disk is the boot disk nvme0n1.
# Nothing here may ever touch a real NVMe namespace. Every device that reaches
# a dm target or a nvmet namespace MUST be a loop device backed by a file under
# $BACKING_DIR. The asserts below are the hard gate that enforces that.

# ---------------------------------------------------------------------------
# Scenario labels — FULL NAMES ONLY (no F1/F2 codes). Keep in exact sync with
# the initiator's lib_storage.sh SCENARIOS list.
# ---------------------------------------------------------------------------
readonly SC_BASELINE="BASELINE"
readonly SC_MEDIA_ERROR_READ="MEDIA_ERROR_READ"
readonly SC_MEDIA_ERROR_PARTIAL_READ="MEDIA_ERROR_PARTIAL_READ"
readonly SC_FULL_IO_FAIL="FULL_IO_FAIL"
readonly SC_FAIL_SLOW="FAIL_SLOW"
readonly SC_TARGET_CRASH="TARGET_CRASH"
readonly SC_INITIATOR_STATUS_INJECT="INITIATOR_STATUS_INJECT"

# Phase 1b — "에러 시그널의 복구 활용" 라벨 (실명, 225/lib_storage.sh와 문자열
# 완전 동일). target 쪽에서 이들은 기존 fault 스택을 그대로 재사용한다:
#   FAULT_ISOLATION      = MEDIA_ERROR_READ와 동일한 dm-dust 불량 블록 셋업
#   TIMEOUT_TUNING       = FAIL_SLOW와 동일한 dm-delay 셋업 (param=지연 ms)
#   TARGET_RECOVERY      = TARGET_CRASH와 동일한 loop 직결 (crash→restore 대상)
#   COUNTER_EARLY_DETECT = loop 직결 (crash 모드). fail-slow 모드는 초기자가
#                          FAIL_SLOW 라벨을 직접 요청하므로 여기서는 loop 직결만.
readonly SC_FAULT_ISOLATION="FAULT_ISOLATION"
readonly SC_TIMEOUT_TUNING="TIMEOUT_TUNING"
readonly SC_TARGET_RECOVERY="TARGET_RECOVERY"
readonly SC_COUNTER_EARLY_DETECT="COUNTER_EARLY_DETECT"

# All scenarios that require a *target* dm/nvmet setup. INITIATOR_STATUS_INJECT
# is a control experiment that never touches the fabric, but it still needs a
# working export to read from, so it is set up as a plain BASELINE export.
# Phase 1b 라벨은 아래에 additive로 추가 — 기존 시나리오의 setup 코드는 재사용.
readonly ALL_TARGET_SCENARIOS=(
  "$SC_BASELINE" "$SC_MEDIA_ERROR_READ" "$SC_MEDIA_ERROR_PARTIAL_READ"
  "$SC_FULL_IO_FAIL" "$SC_FAIL_SLOW" "$SC_TARGET_CRASH"
  "$SC_INITIATOR_STATUS_INJECT"
  "$SC_FAULT_ISOLATION" "$SC_TIMEOUT_TUNING" "$SC_TARGET_RECOVERY"
  "$SC_COUNTER_EARLY_DETECT"
)

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------
readonly BACKING_DIR="/home/gustlr/nvmet_backing"
readonly BACKING_IMG="${BACKING_DIR}/ns1.img"
readonly BACKING_SIZE="8G"                 # truncate size of the sparse image
readonly DM_NAME="storagerdma_ns1"          # dm device name (in /dev/mapper)
readonly NQN="nqn.2026-07.io.netsys:storage-rdma"
readonly NVMET_PORT_ID="1"                   # configfs port number
readonly RDMA_IP="10.0.0.3"                  # target RoCEv2 IP (nvmet port)
readonly RDMA_SVCID="4420"
readonly CFG="/sys/kernel/config/nvmet"

# dm-dust block size in BYTES (bad-block granularity). dm-dust addbadblock takes
# a block number in units of THIS size. dm sector unit is always 512B.
readonly DUST_BLKSZ=4096
readonly SECTOR=512

# Where target_setup records what it built, so teardown can reverse exactly the
# stack that exists (avoids blind rmdir/dmsetup on a half-built stack).
readonly STATE_FILE="${BACKING_DIR}/.storage_rdma_state"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log()  { echo "[target] $*" >&2; }
die()  { echo "[target][FATAL] $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Safety asserts
# ---------------------------------------------------------------------------

# Refuse anything that looks like a real (boot) NVMe/SATA disk. Belt-and-braces:
# both a name-pattern check and a "is it the disk that carries / ?" check.
assert_not_real_disk() {
  local dev="$1"
  [ -n "$dev" ] || die "assert_not_real_disk: empty device"

  # Name pattern: nvme0* is the boot disk on 224; nvme namespaces and whole
  # sd? disks are never valid targets here.
  case "$dev" in
    /dev/nvme0n*|/dev/nvme0)   die "REFUSING boot disk '$dev' (nvme0 family)";;
    /dev/nvme*n*|/dev/nvme*)   die "REFUSING real NVMe namespace '$dev' — only loop devices may be exported";;
    /dev/sd?|/dev/sd?[0-9]*)   die "REFUSING SATA/SCSI disk '$dev'";;
  esac

  # Root-disk check: resolve the disk that backs '/' and refuse if 'dev' is it
  # (or a partition/child of it).
  local root_src root_disk dev_disk
  root_src="$(findmnt -no SOURCE / 2>/dev/null || true)"
  if [ -n "$root_src" ]; then
    root_disk="$(lsblk -no PKNAME "$root_src" 2>/dev/null | head -1 || true)"
    [ -n "$root_disk" ] || root_disk="$(basename "$root_src")"
    dev_disk="$(lsblk -no PKNAME "$dev" 2>/dev/null | head -1 || true)"
    [ -n "$dev_disk" ] || dev_disk="$(basename "$dev")"
    if [ -n "$root_disk" ] && { [ "$dev_disk" = "$root_disk" ] || [ "$(basename "$dev")" = "$root_disk" ]; }; then
      die "REFUSING '$dev' — it resolves to the root/boot disk '$root_disk'"
    fi
  fi
}

# Require that 'dev' is a loop device (TYPE==loop per lsblk). Used to gate every
# dm stack and every nvmet namespace device_path.
assert_loop_device() {
  local dev="$1"
  [ -b "$dev" ] || die "assert_loop_device: '$dev' is not a block device"
  local t
  t="$(lsblk -no TYPE "$dev" 2>/dev/null | head -1 || true)"
  [ "$t" = "loop" ] || die "assert_loop_device: '$dev' TYPE='$t' (expected 'loop') — refusing"
  assert_not_real_disk "$dev"
}

# Require that a dm device sits ONLY on top of loop device(s). Walks the dm
# slaves in /sys/block/<dm>/slaves and asserts each is a loop.
assert_dm_on_loop() {
  local dmpath="$1"
  local base
  base="$(basename "$(readlink -f "$dmpath")")"   # e.g. dm-3
  local slaves_dir="/sys/block/${base}/slaves"
  [ -d "$slaves_dir" ] || die "assert_dm_on_loop: no slaves dir for '$dmpath'"
  local s found=0
  for s in "$slaves_dir"/*; do
    [ -e "$s" ] || continue
    found=1
    local sname; sname="$(basename "$s")"
    case "$sname" in
      loop*) : ;;
      *) die "assert_dm_on_loop: dm '$dmpath' has non-loop slave '$sname' — refusing" ;;
    esac
  done
  [ "$found" = 1 ] || die "assert_dm_on_loop: dm '$dmpath' has no slaves — refusing"
}

# Require root.
assert_root() {
  [ "$(id -u)" = "0" ] || die "must run as root (sudo). $*"
}

# ---------------------------------------------------------------------------
# RDMA device discovery + sysfs counter snapshot (independent of 05's daemon).
# ---------------------------------------------------------------------------

# Echo the RDMA device name (default: first mlx5 under /sys/class/infiniband).
# Override with RDMA_DEV env var.
rdma_device() {
  if [ -n "${RDMA_DEV:-}" ]; then echo "$RDMA_DEV"; return; fi
  local d
  for d in /sys/class/infiniband/*; do
    [ -e "$d" ] || continue
    basename "$d"; return
  done
  echo "mlx5_0"
}

# Dump "counter_name,value" for hw_counters + counters of the given device/port
# to stdout. Port defaults to 1.
snapshot_counters() {
  local dev="${1:-$(rdma_device)}"
  local port="${2:-1}"
  local hw="/sys/class/infiniband/${dev}/ports/${port}/hw_counters"
  local co="/sys/class/infiniband/${dev}/ports/${port}/counters"
  local f
  for f in "$hw"/* "$co"/*; do
    [ -f "$f" ] || continue
    echo "$(basename "$f"),$(cat "$f" 2>/dev/null || echo NA)"
  done
}
