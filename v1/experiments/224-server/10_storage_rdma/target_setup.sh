#!/bin/bash
# [한국어 요약] 시나리오별 fault 스택 구성 — 224(target)에서 root로 실행.
#   구조: 파일(8GB) → loop → [dm 고장 층] → nvmet configfs export(RDMA 4420).
#   부팅 디스크는 3중 게이트(이름/루트 역추적/loop 강제)로 절대 못 건드림.
#
#   시나리오→dm 매핑: MEDIA_ERROR_*=dm-dust(없으면 linear+error 합성 테이블),
#   FULL_IO_FAIL=dm-flakey(down 고정), FAIL_SLOW=dm-delay — 단 delay는 linear로
#   만들어 export를 끝낸 뒤 마지막에 테이블 스왑(§7). 큰 지연 디바이스를 바로
#   만들면 udev/blkid 프로브 read가 지연×수십 개로 setup이 수십 분 블록됨.
#
#   시작 시 자가 치유: 우리 dm 이름을 쥔 stale dmsetup 프로세스를 발견하면
#   kill (중단된 이전 실행의 잔여물이 dm 락을 영원히 쥐는 사고 방지).
# target_setup.sh — build the nvmet-rdma export for one Phase-1 scenario (224).
#
# Usage: sudo ./target_setup.sh <SCENARIO> [param]
#   SCENARIO : one of the full-name labels (see lib_storage.sh)
#   param    : scenario-dependent (see below); safe defaults if omitted
#     MEDIA_ERROR_READ          param = bad-block BYTE offset      (default 32768)
#     MEDIA_ERROR_PARTIAL_READ  param = bad-block BYTE offset      (default 2097152 = 2MiB)
#     FAIL_SLOW                 param = per-I/O delay in ms        (default 100)
#     others                    param ignored
#
# Builds: file image -> losetup -> [optional dm target] -> nvmet subsystem/ns/port.
# ALWAYS the boot disk is untouched: only a loop device backed by $BACKING_IMG
# ever reaches a dm target or nvmet. Records the built stack to $STATE_FILE so
# target_teardown.sh can reverse exactly what exists.
#
# Requires root (loop/dm/configfs). Idempotent: tears down any prior stack first.

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib_storage.sh
source "${HERE}/lib_storage.sh"

SCENARIO="${1:-}"
PARAM="${2:-}"
[ -n "$SCENARIO" ] || die "usage: $0 <SCENARIO> [param]"

# validate scenario label
valid=0
for s in "${ALL_TARGET_SCENARIOS[@]}"; do [ "$s" = "$SCENARIO" ] && valid=1; done
[ "$valid" = 1 ] || die "unknown scenario '$SCENARIO' (valid: ${ALL_TARGET_SCENARIOS[*]})"

assert_root "target_setup needs loop/dm/configfs access"

# Region (bytes from offset 0) that gets the offset-ident pattern for the
# partial-read scenario. Must comfortably exceed the initiator's large read.
readonly PARTIAL_PATTERN_BYTES=$((64 * 1024 * 1024))   # 64 MiB

# ---------------------------------------------------------------------------
# 0. best-effort cleanup of any leftover stack (idempotent re-setup)
#    SELF-HEAL: a previous dmsetup on OUR device can be stuck for an hour+
#    (udev probe I/O through a large-delay table) holding the dm/udev lock —
#    every later dmsetup on the same name then queues behind it forever.
#    Kill any stale dmsetup touching $DM_NAME before tearing down.
# ---------------------------------------------------------------------------
log "cleaning any prior stack for NQN=$NQN / dm=$DM_NAME ..."
if pgrep -f "dmsetup .*${DM_NAME}" >/dev/null 2>&1; then
  log "killing stale dmsetup processes on ${DM_NAME} (leftover from an interrupted run)"
  pkill -9 -f "dmsetup .*${DM_NAME}" 2>/dev/null || true
  sleep 1
fi
udevadm settle --timeout=5 2>/dev/null || true
"${HERE}/target_teardown.sh" >/dev/null 2>&1 || true

# ---------------------------------------------------------------------------
# 1. modules
# ---------------------------------------------------------------------------
modprobe nvmet 2>/dev/null || true
modprobe nvmet-rdma 2>/dev/null || true
case "$SCENARIO" in
  # Phase 1b: FAULT_ISOLATION은 MEDIA_ERROR_READ와 같은 dm-dust,
  #           TIMEOUT_TUNING은 FAIL_SLOW와 같은 dm-delay를 재사용한다.
  "$SC_MEDIA_ERROR_READ"|"$SC_MEDIA_ERROR_PARTIAL_READ"|"$SC_FAULT_ISOLATION") modprobe dm-dust 2>/dev/null || true ;;
  "$SC_FULL_IO_FAIL") modprobe dm-flakey 2>/dev/null || true ;;
  "$SC_FAIL_SLOW"|"$SC_TIMEOUT_TUNING")    modprobe dm-delay  2>/dev/null || true ;;
esac
[ -d "$CFG" ] || die "nvmet configfs $CFG missing after modprobe nvmet"

# ---------------------------------------------------------------------------
# 2. backing image + loop device
# ---------------------------------------------------------------------------
mkdir -p "$BACKING_DIR"
if [ ! -f "$BACKING_IMG" ]; then
  log "creating sparse backing image $BACKING_IMG ($BACKING_SIZE)"
  truncate -s "$BACKING_SIZE" "$BACKING_IMG"
fi

LOOPDEV="$(losetup --find --show "$BACKING_IMG")"
[ -n "$LOOPDEV" ] || die "losetup failed for $BACKING_IMG"
log "loop device: $LOOPDEV"
# HARD SAFETY GATE: the thing we are about to layer on MUST be a loop device.
assert_loop_device "$LOOPDEV"

SECTORS="$(blockdev --getsz "$LOOPDEV")"      # size in 512B sectors
[ "$SECTORS" -gt 0 ] || die "blockdev --getsz returned '$SECTORS'"

# ---------------------------------------------------------------------------
# 3. optional pattern write (partial-read scenario only)
# ---------------------------------------------------------------------------
if [ "$SCENARIO" = "$SC_MEDIA_ERROR_PARTIAL_READ" ]; then
  # build pattern_write if needed
  if [ ! -x "${HERE}/pattern_write" ]; then
    command -v cc >/dev/null 2>&1 || die "cc not found — needed to build pattern_write"
    log "compiling pattern_write ..."
    cc -O2 -o "${HERE}/pattern_write" "${HERE}/pattern_write.c"
  fi
  log "writing offset-ident pattern over first $((PARTIAL_PATTERN_BYTES/1024/1024)) MiB of $LOOPDEV"
  "${HERE}/pattern_write" "$LOOPDEV" "$PARTIAL_PATTERN_BYTES"
fi

# ---------------------------------------------------------------------------
# 4. dm stack (scenario-specific). DEVPATH = what nvmet exports.
# ---------------------------------------------------------------------------
DEVPATH="$LOOPDEV"
DM_USED=0
DM_DETAIL=""
DELAY_SWAP_MS=""   # FAIL_SLOW: delay table is swapped in AFTER the export (below)

case "$SCENARIO" in
  # Phase 1b: TARGET_RECOVERY(=crash→restore 대상)와 COUNTER_EARLY_DETECT crash
  # 모드는 TARGET_CRASH처럼 loop 직결로 export한다.
  "$SC_BASELINE"|"$SC_TARGET_CRASH"|"$SC_INITIATOR_STATUS_INJECT"|"$SC_TARGET_RECOVERY"|"$SC_COUNTER_EARLY_DETECT")
    log "no dm layer (loop exported directly)"
    ;;

  # Phase 1b: FAULT_ISOLATION은 MEDIA_ERROR_READ와 동일한 dm-dust 불량 블록.
  "$SC_MEDIA_ERROR_READ"|"$SC_MEDIA_ERROR_PARTIAL_READ"|"$SC_FAULT_ISOLATION")
    # default bad-block byte offset per scenario (FAULT_ISOLATION은
    # MEDIA_ERROR_READ와 동일한 32768 기본값을 쓴다).
    local_off="$PARAM"
    if [ -z "$local_off" ]; then
      if [ "$SCENARIO" = "$SC_MEDIA_ERROR_PARTIAL_READ" ]; then local_off=2097152; else local_off=32768; fi
    fi
    # bad-block number is in DUST_BLKSZ (4096B) units
    (( local_off % DUST_BLKSZ == 0 )) || die "bad-block offset $local_off not a multiple of $DUST_BLKSZ"
    badblock=$(( local_off / DUST_BLKSZ ))
    if dmsetup targets 2>/dev/null | awk '{print $1}' | grep -qx dust; then
      log "dm-dust: blksz=${DUST_BLKSZ}B, bad byte-offset=${local_off} -> block #${badblock}"
      dmsetup create "$DM_NAME" --table "0 ${SECTORS} dust ${LOOPDEV} 0 ${DUST_BLKSZ}"
      dmsetup message "$DM_NAME" 0 addbadblock "$badblock"
      dmsetup message "$DM_NAME" 0 enable     # start failing reads on bad blocks
      DM_DETAIL="dust badblock=${badblock} off=${local_off}"
    else
      # Fallback when the kernel has no dm-dust (e.g. 224's 6.16.2 build): a
      # composite linear+error+linear table. The `error` core target fails ALL
      # I/O (read AND write, vs dust: reads only) in the DUST_BLKSZ-sized range
      # at local_off — equivalent for our read-oriented scenarios. NOTE: the
      # pattern write (step 3) targets the LOOP device directly, so it is not
      # affected by the error range.
      bad_start_sec=$(( local_off / SECTOR ))
      bad_len_sec=$(( DUST_BLKSZ / SECTOR ))
      bad_end_sec=$(( bad_start_sec + bad_len_sec ))
      (( bad_start_sec > 0 )) || die "linear+error fallback needs bad-block offset > 0"
      (( bad_end_sec < SECTORS )) || die "bad block past end of device"
      log "dm-dust unavailable -> linear+error composite: bad range sectors [${bad_start_sec},${bad_end_sec})"
      dmsetup create "$DM_NAME" <<EOF
0 ${bad_start_sec} linear ${LOOPDEV} 0
${bad_start_sec} ${bad_len_sec} error
${bad_end_sec} $(( SECTORS - bad_end_sec )) linear ${LOOPDEV} ${bad_end_sec}
EOF
      DM_DETAIL="linear+error badoff=${local_off} (dm-dust unavailable)"
    fi
    DEVPATH="/dev/mapper/${DM_NAME}"
    DM_USED=1
    ;;

  "$SC_FULL_IO_FAIL")
    # up_interval=0, down_interval=3600s -> device fails ALL I/O for the trial.
    log "dm-flakey: up=0 down=3600 (all I/O errors during trial)"
    dmsetup create "$DM_NAME" --table "0 ${SECTORS} flakey ${LOOPDEV} 0 0 3600"
    DEVPATH="/dev/mapper/${DM_NAME}"
    DM_USED=1
    DM_DETAIL="flakey up=0 down=3600"
    ;;

  # Phase 1b: TIMEOUT_TUNING은 FAIL_SLOW와 동일한 dm-delay(param=지연 ms, 보통 35000).
  "$SC_FAIL_SLOW"|"$SC_TIMEOUT_TUNING")
    ms="$PARAM"; [ -n "$ms" ] || ms=100
    (( ms >= 0 )) || die "FAIL_SLOW delay must be >= 0 ms (got '$ms')"
    # Create as LINEAR first and swap the delay table in only after the nvmet
    # export (see below). Creating the device directly with a large delay
    # stalls setup for tens of minutes: udev/blkid probe the fresh dm node
    # with dozens of small reads, each of which eats the full delay
    # (observed: 35000ms delay -> setup blocked ~30min on 224).
    log "dm-delay: ${ms} ms per I/O — created linear, delay table deferred until after export"
    dmsetup create "$DM_NAME" --table "0 ${SECTORS} linear ${LOOPDEV} 0"
    DEVPATH="/dev/mapper/${DM_NAME}"
    DM_USED=1
    DM_DETAIL="delay ${ms}ms (deferred swap)"
    DELAY_SWAP_MS="$ms"
    ;;
esac

# If a dm layer was built, re-assert it sits only on loop devices.
if [ "$DM_USED" = 1 ]; then
  assert_dm_on_loop "$DEVPATH"
fi
# Final gate before export: whatever we export must NOT be a real disk.
assert_not_real_disk "$DEVPATH"

# ---------------------------------------------------------------------------
# 5. nvmet export via configfs (NO nvmetcli — direct mkdir/echo)
# ---------------------------------------------------------------------------
log "nvmet export: NQN=$NQN device_path=$DEVPATH port=${RDMA_IP}:${RDMA_SVCID} (rdma)"
mkdir -p "${CFG}/subsystems/${NQN}"
echo 1 > "${CFG}/subsystems/${NQN}/attr_allow_any_host"

mkdir -p "${CFG}/subsystems/${NQN}/namespaces/1"
echo -n "$DEVPATH" > "${CFG}/subsystems/${NQN}/namespaces/1/device_path"
echo 1 > "${CFG}/subsystems/${NQN}/namespaces/1/enable"

mkdir -p "${CFG}/ports/${NVMET_PORT_ID}"
echo "$RDMA_IP"   > "${CFG}/ports/${NVMET_PORT_ID}/addr_traddr"
echo rdma         > "${CFG}/ports/${NVMET_PORT_ID}/addr_trtype"
echo "$RDMA_SVCID"> "${CFG}/ports/${NVMET_PORT_ID}/addr_trsvcid"
echo ipv4         > "${CFG}/ports/${NVMET_PORT_ID}/addr_adrfam"
ln -s "${CFG}/subsystems/${NQN}" "${CFG}/ports/${NVMET_PORT_ID}/subsystems/${NQN}"

# ---------------------------------------------------------------------------
# 6. record state for teardown
# ---------------------------------------------------------------------------
# 값은 반드시 홑따옴표로 감싼다: DM_DETAIL의 괄호/공백이 소스 시 문법 오류를
# 냈었다. DM_NAME은 기록하지 않는다 — lib의 readonly 상수와 충돌(경고 소음).
{
  echo "SCENARIO='$SCENARIO'"
  echo "PARAM='$PARAM'"
  echo "LOOPDEV='$LOOPDEV'"
  echo "DM_USED='$DM_USED'"
  echo "DEVPATH='$DEVPATH'"
  echo "DM_DETAIL='$DM_DETAIL'"
} > "$STATE_FILE"

# ---------------------------------------------------------------------------
# 7. FAIL_SLOW: swap the delay table in now that probing/export is done.
#    Table reload on a live dm device: suspend -> load -> resume. No I/O is in
#    flight yet (initiator has not connected), so suspend returns immediately.
# ---------------------------------------------------------------------------
if [ -n "$DELAY_SWAP_MS" ]; then
  # --noudevsync on resume: the table change fires a udev change event whose
  # blkid probe reads would each eat the full delay; without the flag, resume
  # blocks on that probe (observed: 35s delay -> resume queued 20+ minutes).
  # The /dev/mapper node already exists from the linear create, so skipping
  # udev synchronization here is safe.
  dmsetup suspend --noudevsync "$DM_NAME"
  dmsetup load "$DM_NAME" --table "0 ${SECTORS} delay ${LOOPDEV} 0 ${DELAY_SWAP_MS}"
  dmsetup resume --noudevsync "$DM_NAME"
  log "delay table swapped in: ${DELAY_SWAP_MS} ms per I/O now active"
fi

echo
log "SETUP DONE — scenario=$SCENARIO devpath=$DEVPATH ${DM_DETAIL:+($DM_DETAIL)}"
log "initiator connects with: nvme connect -t rdma -a $RDMA_IP -s $RDMA_SVCID -n $NQN"
