#!/bin/bash
# [한국어 요약] initiator(225) 공용 라이브러리 — orchestrator/precheck가 source.
#   (1) 시나리오 실명 라벨·FAIL_SLOW sweep·NQN/IP 상수 (224 lib과 문자열 동일 유지)
#   (2) 안전 assert: 부팅 디스크(nvme0*) 거부 + 루트 디스크 역추적 거부
#   (3) find_fabric_namespace: /sys/block에서 subsysnqn==우리 NQN으로 탐색
#       (multipath 커널에서는 컨트롤러 디렉토리에 블록 노드가 없어서 이 방식이 필수)
#   (4) ssh_target: sudo로 실행돼도 ssh는 원래 사용자(SUDO_USER)로 — 키 소유 문제
#   (5) RDMA sysfs 카운터 스냅샷/델타 요약
# lib_storage.sh — shared constants + safety asserts + sysfs counter snapshot
# for the Phase-1 (SSD x RDMA) INITIATOR side (node 225).
#
# Sourced by initiator_precheck.sh and run_storage_experiment.sh. NOT executable
# on its own. Assumes `set -euo pipefail` in the sourcing script.
#
# Kernel-consumer CQE invisibility (see README): the NVMe-oF initiator QP is
# owned by the kernel (nvme-rdma). Userspace CANNOT read its CQEs
# (wc_status/vendor_err). So every observable here is one of:
#   (NVMe status/errno) + (initiator dmesg delta) + (RDMA HW-counter delta,
#   both nodes) + (latency distribution). There is deliberately no wc_status.

# ---------------------------------------------------------------------------
# Scenario labels — FULL NAMES ONLY. Keep in exact sync with 224/lib_storage.sh.
# ---------------------------------------------------------------------------
readonly SC_BASELINE="BASELINE"
readonly SC_MEDIA_ERROR_READ="MEDIA_ERROR_READ"
readonly SC_MEDIA_ERROR_PARTIAL_READ="MEDIA_ERROR_PARTIAL_READ"
readonly SC_FULL_IO_FAIL="FULL_IO_FAIL"
readonly SC_FAIL_SLOW="FAIL_SLOW"
readonly SC_TARGET_CRASH="TARGET_CRASH"
readonly SC_INITIATOR_STATUS_INJECT="INITIATOR_STATUS_INJECT"

# Default run order for `all`.
readonly SCENARIOS=(
  "$SC_BASELINE" "$SC_MEDIA_ERROR_READ" "$SC_MEDIA_ERROR_PARTIAL_READ"
  "$SC_FULL_IO_FAIL" "$SC_FAIL_SLOW" "$SC_TARGET_CRASH"
  "$SC_INITIATOR_STATUS_INJECT"
)

# FAIL_SLOW delay sweep (ms). Last value (35000) crosses the default nvme
# io_timeout (30s) boundary => expect transition latency-only -> abort/reconnect
# (Fable note 5).
readonly FAIL_SLOW_SWEEP=(1 10 100 1000 5000 35000)

# ---------------------------------------------------------------------------
# Phase 1b — "에러 시그널의 복구 활용" 시나리오 라벨 (실명, 224/lib_storage.sh와
# 문자열 완전 동일 유지). Phase 1이 "어떤 신호가 뜨는가"(신호 지도)였다면 1b는
# "그 신호로 어떻게 복구하는가"(신호→복구 실증)다. 이 라벨들은 의도적으로
# SCENARIOS 배열(=`all`)에 넣지 않는다: `all`은 Phase 1만 돌고, 1b는 개별 실행
# 또는 `phase1b` 메타 인자(4개 순차)로만 실행된다.
# ---------------------------------------------------------------------------
readonly SC_FAULT_ISOLATION="FAULT_ISOLATION"           # E1: NVMe 에러는 per-command 격리(⟷ RDMA QP 전멸)
readonly SC_TIMEOUT_TUNING="TIMEOUT_TUNING"             # E2: io_timeout/fast_io_fail 정책 레버로 hang→에러
readonly SC_TARGET_RECOVERY="TARGET_RECOVERY"           # E3: crash→restore, I/O 재개 시간 = 정책 산술
readonly SC_COUNTER_EARLY_DETECT="COUNTER_EARLY_DETECT" # E4: RDMA 카운터 lead time(앱 에러보다 먼저 발화?)

# Phase 1b 실행 목록. `phase1b` 메타 인자가 이 순서대로 4개를 돌린다.
readonly PHASE1B_SCENARIOS=(
  "$SC_FAULT_ISOLATION" "$SC_TIMEOUT_TUNING"
  "$SC_TARGET_RECOVERY" "$SC_COUNTER_EARLY_DETECT"
)

# E2 TIMEOUT_TUNING: io_timeout 파라미터 스윕(초). 30초는 Phase 1의 기본값이며,
# 5/10초는 정책을 앞당겨 "표면화 시간이 정책값을 추종하는가"를 본다.
readonly TIMEOUT_TUNING_SWEEP=(5 10 30)
# E2에서 함께 거는 연결 레버(초). fast_io_fail_tmo는 재큐 루프를 우회해 hang을
# 유한 에러로 바꾸는 핵심 레버 — 지원 nvme-cli에서만 적용(미지원이면 폴백).
readonly TIMEOUT_TUNING_FAST_IO_FAIL=5
# E2 target dm-delay 지연(ms) 고정값. param(io_timeout 초)과 별개 — target은 항상
# 이 지연을 걸고, 초기자가 io_timeout/fast_io_fail을 바꿔가며 time-to-error를 본다.
readonly TIMEOUT_TUNING_DELAY_MS=35000
# E3 TARGET_RECOVERY: restore 지연 T 파라미터 스윕(초). T=30은 재연결 attempt
# 소진(3회×10s=30s) 경계를 넘봄 — ctrl-loss-tmo=60으로 여유 확보(아래).
readonly TARGET_RECOVERY_SWEEP=(5 15 30)
readonly TARGET_RECOVERY_CTRL_LOSS_TMO=60   # 연결 시 ctrl-loss-tmo(초). reconnect-delay는 기본(10s).
# E1 FAULT_ISOLATION (c): 불량 LBA 읽기를 이 횟수만큼 연속 반복한 뒤에도 정상
# LBA가 여전히 정상인지 + 컨트롤러 reset이 없는지 확인(명령 단위 격리 실증).
readonly FAULT_ISO_REPEAT=20
# E4 COUNTER_EARLY_DETECT: 초기자 RDMA 에러 카운터 감시 대상(공백 구분). 폴링이
# 처음으로 이 중 하나라도 baseline을 넘긴 시각 = counter_first_anomaly.
readonly EARLY_DETECT_COUNTERS="resp_cqe_error req_cqe_error local_ack_timeout_err"
readonly EARLY_DETECT_POLL_MS=200           # 카운터 폴링 간격(ms) = 0.2초
# E4 fail-slow 모드가 target에 요청하는 dm-delay 지연(ms). io_timeout(30s)을 넘겨
# reset 루프를 유발 → 앱은 영원히 hang(lead=∞), 카운터 발화 시각 자체가 결과.
readonly COUNTER_ED_FAILSLOW_MS=35000

# ---------------------------------------------------------------------------
# Fabric / remote constants
# ---------------------------------------------------------------------------
readonly REMOTE_SSH="gustlr@SERVER_224_ADDR"    # management IP (ssh 225->224 only)
readonly REMOTE_DIR="/home/gustlr/Desktop/gpu_fault_recovery/10_storage_rdma"
readonly NQN="nqn.2026-07.io.netsys:storage-rdma"
readonly RDMA_IP="10.0.0.3"                      # target nvmet RDMA IP
readonly RDMA_SVCID="4420"

# Bad-block byte offsets handed to the target per scenario.
readonly MEDIA_BADBLOCK_OFF=32768                # 32 KiB — small read hits it
# Partial-read: large read of PARTIAL_READ_LEN from offset 0; bad block at its
# midpoint so ~half the transfer lands before the media error.
readonly PARTIAL_READ_LEN=$((4 * 1024 * 1024))   # 4 MiB sequential read
readonly PARTIAL_BADBLOCK_OFF=$((PARTIAL_READ_LEN / 2))   # 2 MiB midpoint

# INITIATOR_STATUS_INJECT (control): NVMe status code to forge locally via the
# nvme debugfs fault-injection. 0x2002 = (SCT=Media, SC=0x02 unrecovered read
# error)? We use a clearly-recognizable generic value; see README. dont_retry=1
# so it surfaces immediately instead of being retried away.
readonly INJECT_STATUS="0x2081"       # example NVMe status (SCT/SC packed); tune in README
readonly INJECT_DONT_RETRY=1
readonly INJECT_TIMES=1
readonly INJECT_PROBABILITY=100

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log()  { echo "[initiator] $*" >&2; }
die()  { echo "[initiator][FATAL] $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# SSH to the target AS THE REAL USER. The harness runs under sudo (root), but
# the SSH keys/known_hosts for 224 belong to the invoking user (gustlr) — a
# plain `ssh` as root cannot reach the target. Drop back to $SUDO_USER for the
# ssh hop; the remote side elevates itself via passwordless sudo on the three
# whitelisted target scripts.
# ---------------------------------------------------------------------------
ssh_target() { # <remote command string>
  local cmd="$1"
  if [ -n "${SUDO_USER:-}" ] && [ "$(id -u)" = "0" ]; then
    sudo -u "$SUDO_USER" ssh -o BatchMode=yes -o ConnectTimeout=10 "$REMOTE_SSH" "$cmd"
  else
    ssh -o BatchMode=yes -o ConnectTimeout=10 "$REMOTE_SSH" "$cmd"
  fi
}

# ---------------------------------------------------------------------------
# Safety asserts (initiator side)
# ---------------------------------------------------------------------------

# Refuse the boot disk. On 225 the boot disk is also nvme0n1 (single disk).
assert_not_boot_disk() {
  local dev="$1"
  [ -n "$dev" ] || die "assert_not_boot_disk: empty device"
  case "$dev" in
    /dev/nvme0n*|/dev/nvme0) die "REFUSING boot disk '$dev' (nvme0 family)";;
  esac
  local root_src root_disk dev_disk
  root_src="$(findmnt -no SOURCE / 2>/dev/null || true)"
  if [ -n "$root_src" ]; then
    root_disk="$(lsblk -no PKNAME "$root_src" 2>/dev/null | head -1 || true)"
    [ -n "$root_disk" ] || root_disk="$(basename "$root_src")"
    dev_disk="$(lsblk -no PKNAME "$dev" 2>/dev/null | head -1 || true)"
    if [ -n "$root_disk" ] && [ -n "$dev_disk" ] && [ "$dev_disk" = "$root_disk" ]; then
      die "REFUSING '$dev' — child of root/boot disk '$root_disk'"
    fi
  fi
}

# Resolve the /dev/nvmeXnY namespace that belongs to OUR fabric subsystem.
# Scan /sys/block (not the controller dir): with CONFIG_NVME_MULTIPATH the
# block device hangs off the nvme-subsystem and the controller dir only has
# per-path nvmeXcYnZ char nodes — scanning the ctrl dir finds nothing there.
# For both multipath and non-multipath kernels, /sys/block/<ns>/device points
# at something (subsystem or controller) that carries subsysnqn; our NQN is
# unique, so matching it alone is sufficient. Never selects by device order.
find_fabric_namespace() {
  local b base sub
  for b in /sys/block/nvme*n*; do
    [ -e "$b" ] || continue
    base="$(basename "$b")"
    case "$base" in nvme*c*n*) continue;; esac      # per-path nodes, not heads
    sub="$(cat "${b}/device/subsysnqn" 2>/dev/null || true)"
    [ "$sub" = "$NQN" ] || continue
    [ -b "/dev/${base}" ] || continue                # wait for the /dev node
    echo "/dev/${base}"
    return 0
  done
  return 1
}

# ---------------------------------------------------------------------------
# RDMA device discovery + sysfs counter snapshot (local = initiator).
# ---------------------------------------------------------------------------
rdma_device() {
  if [ -n "${RDMA_DEV:-}" ]; then echo "$RDMA_DEV"; return; fi
  local d
  for d in /sys/class/infiniband/*; do
    [ -e "$d" ] || continue
    basename "$d"; return
  done
  echo "mlx5_0"
}

snapshot_counters() {  # -> "name,value" lines (hw_counters + counters)
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

# Given two snapshot files (before,after), emit a compact "name=delta;..." string
# of NONZERO deltas only. Used for the CSV counter_deltas summary column.
counter_delta_summary() {
  local before="$1" after="$2"
  awk -F, '
    NR==FNR { b[$1]=$2; next }
    {
      d = $2 - b[$1];
      if (d != 0 && $2 ~ /^[0-9]+$/ && b[$1] ~ /^[0-9]+$/) {
        out = out sprintf("%s=%+d;", $1, d);
      }
    }
    END { if (out=="") out="none"; print out }
  ' "$before" "$after"
}
