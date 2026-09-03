#!/bin/bash
# [한국어 요약] TARGET_CRASH용 즉사 모사 — nvmet RDMA 포트를 제거해 fabric
#   endpoint를 즉시 소멸시킴 (loop/dm/이미지는 안 건드림). orchestrator가 I/O
#   도중 ssh로 호출하고, initiator가 에러를 볼 때까지의 시간을 잰다.
# target_crash.sh — simulate an instantaneous target death for the TARGET_CRASH
# scenario by removing the nvmet RDMA port (and its subsystem link). This kills
# the fabric endpoint immediately without touching the loop/dm/image, so the
# initiator experiences a mid-I/O disappearance of the controller.
#
# The orchestrator (225) triggers this over SSH *during* an in-flight read and
# measures the time until the initiator's I/O returns an error, and which signal
# fires first: NVMe keep-alive timeout vs RDMA RETRY_EXC (see README H2 / Fable
# note 4). Prints a /dev/kmsg-comparable epoch-nanosecond timestamp on stdout so
# the orchestrator can align target-side and initiator-side clocks loosely.
#
# Requires root. Run: sudo ./target_crash.sh

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib_storage.sh
source "${HERE}/lib_storage.sh"

[ "$(id -u)" = "0" ] || die "target_crash needs root (sudo)"

ts_ns="$(date +%s%N)"
echo "CRASH_TRIGGER_NS=${ts_ns}"
echo "STORAGE_RDMA_CRASH ${ts_ns} port-remove" > /dev/kmsg 2>/dev/null || true

# Remove the port->subsystem link and the port itself: the RDMA listener goes
# away instantly. This is the "port/subsystem removal = instant death" model.
if [ -d "$CFG" ]; then
  link="${CFG}/ports/${NVMET_PORT_ID}/subsystems/${NQN}"
  [ -e "$link" ] && rm -f "$link"
  if [ -d "${CFG}/ports/${NVMET_PORT_ID}/subsystems" ]; then
    for l in "${CFG}/ports/${NVMET_PORT_ID}/subsystems"/*; do [ -e "$l" ] && rm -f "$l"; done
  fi
  [ -d "${CFG}/ports/${NVMET_PORT_ID}" ] && rmdir "${CFG}/ports/${NVMET_PORT_ID}" 2>/dev/null || true
fi

log "CRASH injected (port ${NVMET_PORT_ID} removed) at ${ts_ns} ns"
