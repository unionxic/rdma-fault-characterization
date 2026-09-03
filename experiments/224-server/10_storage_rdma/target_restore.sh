#!/bin/bash
# [한국어 요약] TARGET_RECOVERY용 — target_crash.sh가 제거한 nvmet RDMA 포트만
#   재생성한다. crash는 포트(+subsystem 링크)만 지우고 subsystem/namespace/loop/
#   dm은 건드리지 않으므로, 이 스크립트는 정확히 그 역연산(포트 재생성 + 링크
#   복원)이다. "죽음이 아니라 부활을 측정" — 초기자(nvme-rdma)가 자동 재연결로
#   I/O를 재개하기까지의 시간을 orchestrator가 잰다.
#
# target_restore.sh — recreate ONLY the nvmet RDMA port that target_crash.sh
# removed (the inverse of the crash). The subsystem, namespace, loop, and dm
# layers are untouched by the crash, so restoring is just: recreate the port
# dir, set its addr_* attrs, and re-link the subsystem. The RDMA listener
# reappears and the initiator's nvme-rdma reconnect logic picks it up on its
# next reconnect-delay tick.
#
# Prints a /dev/kmsg-comparable epoch-nanosecond timestamp on stdout so the
# orchestrator (225) can align the restore instant with the initiator clock.
#
# Requires root. Run: sudo ./target_restore.sh
#
# 안전: subsystem이 남아 있지 않으면(=setup을 안 했거나 teardown됨) 아무것도
# 만들지 않고 실패한다 — 엉뚱한 빈 포트를 export하지 않도록.

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib_storage.sh
source "${HERE}/lib_storage.sh"

[ "$(id -u)" = "0" ] || die "target_restore needs root (sudo)"
[ -d "$CFG" ] || die "nvmet configfs $CFG missing — nothing to restore"

# crash는 subsystem/namespace를 남긴다. 그게 없으면 복원할 대상이 없는 것이므로
# 조용히 빈 포트를 만들지 말고 실패한다(멱등 teardown 후 restore 오용 방지).
[ -d "${CFG}/subsystems/${NQN}" ] || \
  die "subsystem ${NQN} absent — run target_setup.sh first (crash only removes the port, not the subsystem)"

ts_ns="$(date +%s%N)"
echo "RESTORE_TRIGGER_NS=${ts_ns}"
echo "STORAGE_RDMA_RESTORE ${ts_ns} port-recreate" > /dev/kmsg 2>/dev/null || true

# 포트 재생성 — target_setup.sh의 export 절과 동일한 순서/속성.
# addr_* 는 subsystem 링크 전에 설정해야 한다(라이브 포트는 속성 변경을 거부).
mkdir -p "${CFG}/ports/${NVMET_PORT_ID}"
echo "$RDMA_IP"    > "${CFG}/ports/${NVMET_PORT_ID}/addr_traddr"
echo rdma          > "${CFG}/ports/${NVMET_PORT_ID}/addr_trtype"
echo "$RDMA_SVCID" > "${CFG}/ports/${NVMET_PORT_ID}/addr_trsvcid"
echo ipv4          > "${CFG}/ports/${NVMET_PORT_ID}/addr_adrfam"

# subsystem→port 링크 복원(이미 있으면 건너뜀 — 멱등).
if [ ! -e "${CFG}/ports/${NVMET_PORT_ID}/subsystems/${NQN}" ]; then
  ln -s "${CFG}/subsystems/${NQN}" "${CFG}/ports/${NVMET_PORT_ID}/subsystems/${NQN}"
fi

log "RESTORE done (port ${NVMET_PORT_ID} recreated, subsystem re-linked) at ${ts_ns} ns"
