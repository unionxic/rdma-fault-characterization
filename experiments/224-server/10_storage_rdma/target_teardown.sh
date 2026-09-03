#!/bin/bash
# [한국어 요약] setup의 역순 해제(nvmet → dm → loop), 멱등 — 몇 번 불러도 안전.
#   STATE_FILE(setup이 기록)을 읽어 정확히 그 스택을 되감고, 없으면 잘 알려진
#   이름(NQN/DM_NAME)으로 best-effort 정리. 이미지 파일은 재사용 위해 남김.
# target_teardown.sh — reverse the nvmet-rdma export built by target_setup.sh.
# Order: nvmet (port link -> port -> ns -> subsystem) -> dm -> loop.
# Best-effort and idempotent: safe to call even if nothing (or only part) is set
# up. Reads $STATE_FILE when present to reverse the exact stack; otherwise falls
# back to tearing down by the well-known NQN / DM_NAME / image.
#
# Requires root. Run: sudo ./target_teardown.sh

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib_storage.sh
source "${HERE}/lib_storage.sh"

[ "$(id -u)" = "0" ] || die "target_teardown needs root (sudo)"

LOOPDEV=""; DM_USED=0
if [ -f "$STATE_FILE" ]; then
  # source 금지: state의 DM_NAME이 lib의 readonly와 충돌하고, DM_DETAIL의
  # 괄호가 syntax error를 낸다(실측). 필요한 키만 grep으로 안전 파싱.
  LOOPDEV="$(grep '^LOOPDEV=' "$STATE_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)"
  DM_USED="$(grep '^DM_USED=' "$STATE_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)"
fi

# 이전 dmsetup이 SIGKILL로 죽었으면 stale udev cookie(세마포어)가 남아 이후
# 모든 dmsetup 명령이 무한 대기한다(실측: pkill -9 dmsetup 후 재현). 먼저 해제.
dmsetup udevcomplete_all --yes >/dev/null 2>&1 || dmsetup udevcomplete_all >/dev/null 2>&1 </dev/null || true

# ---------------------------------------------------------------------------
# 1. nvmet: remove port->subsystem link, port, namespace, subsystem
# ---------------------------------------------------------------------------
if [ -d "$CFG" ]; then
  link="${CFG}/ports/${NVMET_PORT_ID}/subsystems/${NQN}"
  [ -e "$link" ] && rm -f "$link" && log "removed port link"
  # remove ANY subsystem links on the port (in case NQN changed)
  if [ -d "${CFG}/ports/${NVMET_PORT_ID}/subsystems" ]; then
    for l in "${CFG}/ports/${NVMET_PORT_ID}/subsystems"/*; do
      [ -e "$l" ] && rm -f "$l"
    done
  fi
  [ -d "${CFG}/ports/${NVMET_PORT_ID}" ] && rmdir "${CFG}/ports/${NVMET_PORT_ID}" 2>/dev/null && log "removed port ${NVMET_PORT_ID}" || true

  ns="${CFG}/subsystems/${NQN}/namespaces/1"
  if [ -d "$ns" ]; then
    echo 0 > "${ns}/enable" 2>/dev/null || true
    rmdir "$ns" 2>/dev/null && log "removed namespace 1" || true
  fi
  [ -d "${CFG}/subsystems/${NQN}" ] && rmdir "${CFG}/subsystems/${NQN}" 2>/dev/null && log "removed subsystem" || true
fi

# ---------------------------------------------------------------------------
# 2. dm: remove the mapper device (by recorded name; else well-known name)
# ---------------------------------------------------------------------------
if timeout 10 dmsetup info "$DM_NAME" >/dev/null 2>&1; then
  # dm-dust: clear failing state first so pending I/O drains, then remove.
  # 모든 dmsetup/udevadm에 시간 상한 — dm-delay의 지연 I/O나 stale cookie로
  # 무한 대기하지 않도록. 마지막 수단은 -f(테이블을 error로 바꿔 강제 해제).
  timeout 10 dmsetup message "$DM_NAME" 0 disable >/dev/null 2>&1 || true
  timeout 15 dmsetup remove "$DM_NAME" >/dev/null 2>&1 && log "removed dm $DM_NAME" || {
    udevadm settle --timeout=5 2>/dev/null || true
    timeout 15 dmsetup remove "$DM_NAME" >/dev/null 2>&1 && log "removed dm $DM_NAME (retry)" || {
      timeout 15 dmsetup remove -f "$DM_NAME" >/dev/null 2>&1 && log "removed dm $DM_NAME (forced)" || \
        log "WARN could not remove dm $DM_NAME (still open?)"
    }
  }
fi

# ---------------------------------------------------------------------------
# 3. loop: detach the loop device(s) backed by our image
# ---------------------------------------------------------------------------
# Prefer the recorded loop dev; also sweep any loop still bound to the image.
if [ -n "${LOOPDEV:-}" ] && losetup "$LOOPDEV" >/dev/null 2>&1; then
  losetup -d "$LOOPDEV" 2>/dev/null && log "detached $LOOPDEV" || true
fi
for l in $(losetup -j "$BACKING_IMG" 2>/dev/null | cut -d: -f1); do
  losetup -d "$l" 2>/dev/null && log "detached $l (by image)" || true
done

rm -f "$STATE_FILE" 2>/dev/null || true
log "teardown complete (image $BACKING_IMG left in place for reuse)"
