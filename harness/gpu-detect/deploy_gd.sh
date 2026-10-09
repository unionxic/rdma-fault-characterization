#!/usr/bin/env bash
# deploy_gd.sh <check output file> [hk|first] - put gpu-detect's builds on rain and sunny (main session). New directories
# only, never overwriting a file. Default mode hk (pilot 2 on); mode first is the deploy of 2026-10-09 17:36 (kept as it
# ran; it refuses now because its directories exist).
# mode hk:
#   ~/gi-bundle/gin_ts2/hk/   libnccl.so.2.32.3 = the hk research build (agent_gd/out/hk) + libnccl.so.2, libnccl.so links.
#                             Nothing else is new: gd_gin_ring (the hw headers equal hk's), the NVSHMEM files and the agent
#                             are the first deploy's, used read only. Refuses if ~/gi-bundle/gin_ts2/hk is not empty on either
#                             node or the source is not WANT_HK; checks that every read-only file (the controls and the first
#                             deploy's files) exists on both nodes with its recorded md5, the new files' md5 on both nodes
#                             equal the source, ldd of gd_gin_ring with hk/ resolves libnccl inside hk/, and every file of the
#                             existing bundles (~/gi-bundle outside hk/, ~/blind-bundle, ~/gd-bundle) is unchanged.
# mode first:
#   ~/gi-bundle/gin_ts2/hw/   libnccl.so.2.32.3 = the hw research build (agent_gd/out/hw) + libnccl.so.2, libnccl.so links
#                             (the app trials' hw library, and the regression runners' BUILD=hw)
#   ~/gd-bundle/gin/          gd_gin_ring (the unmodified GIN example built against the hw headers; build_gd.sh gin-app)
#   ~/gd-bundle/nvs/          gd_nvs_rr (the unmodified ring-reduce built against the t1w install), gd_nvs_boot.so (the
#                             blind study's bootstrap plugin source, rebuilt), lib/ = the t1w install's libraries
#   ~/gd-bundle/agent/        node_agent.py (a byte copy of ../blind/node_agent.py)
# Used read only (must exist on both nodes; never touched): ~/gi-bundle/gin_ts2/{hq,hr} (libraries), hr/gin_ts2 and
# mr/hr/gin_mr (gin-remaining's drivers), ~/blind-bundle/hq/blind_gin_ring, ~/blind-bundle/nvs/{blind_nvs_rr,
# blind_nvs_boot.so,lib} (the blind study's controls).
# Refuses if ~/gd-bundle exists on either node, if ~/gi-bundle/gin_ts2/hw is not empty on either node, or if a source is not
# the expected build (md5 below, EXPERIMENT.md 5 and 12). Checks, written to the output file only (never piped): the md5 of
# every new file on both nodes equals the source; ldd of gd_gin_ring resolves libnccl inside hw/ and hr/, of gd_nvs_rr
# libnvshmem_host inside gd-bundle/nvs/lib; every read-only file exists on both nodes; the md5 of every file of the
# existing bundles (~/gi-bundle outside hw/, ~/blind-bundle) is the same before and after, on both nodes. No GPU program,
# no RDMA traffic: ssh, scp and rsync on the management network only.
set -euo pipefail
OUTF=${1:?output file (the check is written to a file only; never pipe it)}
MODE=${2:-hk}
D=$(cd "$(dirname "$0")" && pwd)
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
O=$SCR/agent_gd/out
INST=$SCR/agent_gd/nvs/install/lib
# the builds recorded in EXPERIMENT.md 12 (override only after a rebuild that is recorded there)
WANT_HW=${WANT_HW:-efc48ca1a8368eb7feadac5d57f8ff23}
WANT_GIN=${WANT_GIN:-719dfaab5a3f4294ab89b12ea102ed5b}
WANT_NVS=${WANT_NVS:-6e93ba5938b0e8f096817dcfabe01907}
WANT_BOOT=${WANT_BOOT:-e3264e83213d6db2e82a60034ade0b7d}
WANT_TR=${WANT_TR:-86c39e91e568fed0a271ca7099b1bb2c}
WANT_HOST=${WANT_HOST:-f3522de834c20c3ffd2044c598485e5d}
WANT_HK=${WANT_HK:-2913c777aa0b05d4d566c9f7638c6a0e}
WANT_AGENT=${WANT_AGENT:-f7f036be96854f022d9dd3f637a81b48}
md5() { md5sum < "$1" | cut -c1-32; }
if [ "$MODE" = hk ]; then
  [ "$(md5 "$O/hk/libnccl.so.2.32.3")" = "$WANT_HK" ] || { echo "hk libnccl is not the expected build" >&2; exit 1; }
  RO="gi-bundle/gin_ts2/hq/libnccl.so.2 gi-bundle/gin_ts2/hr/libnccl.so.2 gi-bundle/gin_ts2/hr/gin_ts2 gi-bundle/gin_ts2/mr/hr/gin_mr \
blind-bundle/hq/blind_gin_ring blind-bundle/nvs/blind_nvs_rr blind-bundle/nvs/blind_nvs_boot.so \
blind-bundle/nvs/lib/nvshmem_transport_ibgda.so.7.0.0 blind-bundle/nvs/lib/libnvshmem_host.so.3.8.0"
  for f in $RO; do
    [ -e ~/"$f" ] && ssh -n "$SUNNY_SSH" "[ -e \$HOME/$f ]" || { echo "read-only file $f missing on a node" >&2; exit 1; }
  done
  # the first deploy's files the hk trials use, with the md5 recorded in EXPERIMENT.md 5 and 12
  FIRST="gi-bundle/gin_ts2/hw/libnccl.so.2.32.3:$WANT_HW gd-bundle/gin/gd_gin_ring:$WANT_GIN gd-bundle/nvs/gd_nvs_rr:$WANT_NVS \
gd-bundle/nvs/gd_nvs_boot.so:$WANT_BOOT gd-bundle/nvs/lib/nvshmem_transport_ibgda.so.7.0.0:$WANT_TR \
gd-bundle/nvs/lib/libnvshmem_host.so.3.8.0:$WANT_HOST gd-bundle/agent/node_agent.py:$WANT_AGENT"
  for fm in $FIRST; do
    f=${fm%%:*}; w=${fm#*:}
    a=$( { md5sum < ~/"$f"; } 2>/dev/null | cut -c1-32 || true); b=$(ssh -n "$SUNNY_SSH" "md5sum < \$HOME/$f 2>/dev/null" | cut -c1-32 || true)
    [ "$a" = "$w" ] && [ "$b" = "$w" ] || { echo "first-deploy file $f is not $w on both nodes" >&2; exit 1; }
  done
  existing() { echo 'cd $HOME && { find gi-bundle -path gi-bundle/gin_ts2/hk -prune -o -type f -print; find blind-bundle gd-bundle -type f -print; } | sort | xargs md5sum'; }
  BEFORE_L=$(bash -c "$(existing)"); BEFORE_S=$(ssh -n "$SUNNY_SSH" "$(existing)")
  if [ -n "$(ls -A ~/gi-bundle/gin_ts2/hk 2>/dev/null)" ] || [ -n "$(ssh -n "$SUNNY_SSH" 'ls -A $HOME/gi-bundle/gin_ts2/hk 2>/dev/null')" ]; then
    echo "gi-bundle/gin_ts2/hk is not empty on a node: refusing" >&2; exit 1
  fi
  mkdir -p ~/gi-bundle/gin_ts2/hk
  cp "$O/hk/libnccl.so.2.32.3" ~/gi-bundle/gin_ts2/hk/
  (cd ~/gi-bundle/gin_ts2/hk && ln -s libnccl.so.2.32.3 libnccl.so.2 && ln -s libnccl.so.2 libnccl.so)
  ssh -n "$SUNNY_SSH" 'mkdir -p $HOME/gi-bundle/gin_ts2/hk'
  rsync -a ~/gi-bundle/gin_ts2/hk/ "$SUNNY_SSH:gi-bundle/gin_ts2/hk/"
  SUM='cd $HOME && find gi-bundle/gin_ts2/hk -type f -print0 | sort -z | xargs -0 md5sum'
  L=$(bash -c "$SUM"); S=$(ssh -n "$SUNNY_SSH" "$SUM")
  LDD='cd $HOME/gd-bundle && echo "gin hk: $(LD_LIBRARY_PATH=$HOME/gi-bundle/gin_ts2/hk ldd gin/gd_gin_ring | grep -E "nccl|not found" | tr -s " " | tr "\n" ";")"'
  AFTER_L=$(bash -c "$(existing)"); AFTER_S=$(ssh -n "$SUNNY_SSH" "$(existing)")
  {
    echo "== $(date '+%F %T') mode hk: new files (rain)"; echo "$L"
    echo "== sunny"; echo "$S"
    [ "$L" = "$S" ] && echo "new files: rain == sunny ($(echo "$L" | wc -l) files)" || echo "NEW FILES MD5 MISMATCH"
    [ "$(md5 "$O/hk/libnccl.so.2.32.3")" = "$(md5 ~/gi-bundle/gin_ts2/hk/libnccl.so.2.32.3)" ] && echo "source == deployed: hk/libnccl.so.2.32.3" ||
      echo "SOURCE MISMATCH: hk/libnccl.so.2.32.3"
    echo "first-deploy files on both nodes with their recorded md5: $(echo $FIRST | wc -w)"
    echo "rain $(bash -c "$LDD" | tr '\n' ' ')"; echo "sunny $(ssh -n "$SUNNY_SSH" "$LDD" | tr '\n' ' ')"
    [ "$BEFORE_L" = "$AFTER_L" ] && [ "$BEFORE_S" = "$AFTER_S" ] &&
      echo "existing bundles unchanged (rain $(echo "$BEFORE_L" | grep -c .) files, sunny $(echo "$BEFORE_S" | grep -c .) files)" ||
      echo "EXISTING BUNDLE CHANGED"
    cat "$O/build_info.txt" 2>/dev/null
  } > "$OUTF"
  exit 0
fi
[ "$MODE" = first ] || { echo "unknown mode $MODE" >&2; exit 2; }
[ "$(md5 "$O/hw/libnccl.so.2.32.3")" = "$WANT_HW" ] || { echo "hw libnccl is not the expected build" >&2; exit 1; }
[ "$(md5 "$O/gin/gd_gin_ring")" = "$WANT_GIN" ] || { echo "gd_gin_ring is not the expected build" >&2; exit 1; }
[ "$(md5 "$O/nvs/gd_nvs_rr")" = "$WANT_NVS" ] || { echo "gd_nvs_rr is not the expected build" >&2; exit 1; }
[ "$(md5 "$O/nvs/gd_nvs_boot.so")" = "$WANT_BOOT" ] || { echo "gd_nvs_boot.so is not the expected build" >&2; exit 1; }
[ "$(md5 "$INST/nvshmem_transport_ibgda.so.7.0.0")" = "$WANT_TR" ] || { echo "the t1w transport is not the expected build" >&2; exit 1; }
[ "$(md5 "$INST/libnvshmem_host.so.3.8.0")" = "$WANT_HOST" ] || { echo "the t1w host library is not the expected build" >&2; exit 1; }
RO="gi-bundle/gin_ts2/hq/libnccl.so.2 gi-bundle/gin_ts2/hr/libnccl.so.2 gi-bundle/gin_ts2/hr/gin_ts2 gi-bundle/gin_ts2/mr/hr/gin_mr \
blind-bundle/hq/blind_gin_ring blind-bundle/nvs/blind_nvs_rr blind-bundle/nvs/blind_nvs_boot.so \
blind-bundle/nvs/lib/nvshmem_transport_ibgda.so.7.0.0 blind-bundle/nvs/lib/libnvshmem_host.so.3.8.0"
for f in $RO; do
  [ -e ~/"$f" ] && ssh -n "$SUNNY_SSH" "[ -e \$HOME/$f ]" || { echo "read-only file $f missing on a node" >&2; exit 1; }
done
existing() { echo 'cd $HOME && { find gi-bundle -path gi-bundle/gin_ts2/hw -prune -o -type f -print; find blind-bundle -type f -print; } | sort | xargs md5sum'; }
BEFORE_L=$(bash -c "$(existing)"); BEFORE_S=$(ssh -n "$SUNNY_SSH" "$(existing)")
if [ -e ~/gd-bundle ] || ssh -n "$SUNNY_SSH" '[ -e $HOME/gd-bundle ]'; then echo "~/gd-bundle exists on a node: refusing" >&2; exit 1; fi
if [ -n "$(ls -A ~/gi-bundle/gin_ts2/hw 2>/dev/null)" ] || [ -n "$(ssh -n "$SUNNY_SSH" 'ls -A $HOME/gi-bundle/gin_ts2/hw 2>/dev/null')" ]; then
  echo "gi-bundle/gin_ts2/hw is not empty on a node: refusing" >&2; exit 1
fi
# rain
mkdir -p ~/gi-bundle/gin_ts2/hw ~/gd-bundle/gin ~/gd-bundle/nvs/lib ~/gd-bundle/agent
cp "$O/hw/libnccl.so.2.32.3" ~/gi-bundle/gin_ts2/hw/
(cd ~/gi-bundle/gin_ts2/hw && ln -s libnccl.so.2.32.3 libnccl.so.2 && ln -s libnccl.so.2 libnccl.so)
cp "$O/gin/gd_gin_ring" ~/gd-bundle/gin/
cp "$O/nvs/gd_nvs_rr" "$O/nvs/gd_nvs_boot.so" ~/gd-bundle/nvs/
cp -a "$INST"/*.so* ~/gd-bundle/nvs/lib/
cp "$D/../blind/node_agent.py" ~/gd-bundle/agent/
# sunny: the same files
ssh -n "$SUNNY_SSH" 'mkdir -p $HOME/gi-bundle/gin_ts2/hw $HOME/gd-bundle'
rsync -a ~/gi-bundle/gin_ts2/hw/ "$SUNNY_SSH:gi-bundle/gin_ts2/hw/"
rsync -a ~/gd-bundle/ "$SUNNY_SSH:gd-bundle/"
SUM='cd $HOME && find gd-bundle gi-bundle/gin_ts2/hw -type f -print0 | sort -z | xargs -0 md5sum'
L=$(bash -c "$SUM"); S=$(ssh -n "$SUNNY_SSH" "$SUM")
LDD='cd $HOME/gd-bundle && echo "gin hw: $(LD_LIBRARY_PATH=$HOME/gi-bundle/gin_ts2/hw ldd gin/gd_gin_ring | grep -E "nccl|not found" | tr -s " " | tr "\n" ";")" && echo "gin hr: $(LD_LIBRARY_PATH=$HOME/gi-bundle/gin_ts2/hr ldd gin/gd_gin_ring | grep -E "nccl|not found" | tr -s " " | tr "\n" ";")" && echo "nvs: $(LD_LIBRARY_PATH=$HOME/gd-bundle/nvs/lib ldd nvs/gd_nvs_rr | grep -E "nvshmem|not found" | tr -s " " | tr "\n" ";")"'
AFTER_L=$(bash -c "$(existing)"); AFTER_S=$(ssh -n "$SUNNY_SSH" "$(existing)")
{
  echo "== $(date '+%F %T') new files (rain)"; echo "$L"
  echo "== sunny"; echo "$S"
  [ "$L" = "$S" ] && echo "new files: rain == sunny ($(echo "$L" | wc -l) files)" || echo "NEW FILES MD5 MISMATCH"
  for p in "hw/libnccl.so.2.32.3:$HOME/gi-bundle/gin_ts2/hw/libnccl.so.2.32.3" "gin/gd_gin_ring:$HOME/gd-bundle/gin/gd_gin_ring" \
           "nvs/gd_nvs_rr:$HOME/gd-bundle/nvs/gd_nvs_rr" "nvs/gd_nvs_boot.so:$HOME/gd-bundle/nvs/gd_nvs_boot.so"; do
    [ "$(md5 "$O/${p%%:*}")" = "$(md5 "${p#*:}")" ] && echo "source == deployed: ${p%%:*}" || echo "SOURCE MISMATCH: ${p%%:*}"
  done
  for f in "$INST"/*.so*; do
    [ -L "$f" ] && continue
    [ "$(md5 "$f")" = "$(md5 ~/gd-bundle/nvs/lib/"$(basename "$f")")" ] && echo "source == deployed: nvs/lib/$(basename "$f")" || echo "SOURCE MISMATCH: nvs/lib/$(basename "$f")"
  done
  [ "$(md5 "$D/../blind/node_agent.py")" = "$(md5 ~/gd-bundle/agent/node_agent.py)" ] && echo "source == deployed: agent/node_agent.py" || echo "SOURCE MISMATCH: agent/node_agent.py"
  echo "rain $(bash -c "$LDD" | tr '\n' ' ')"; echo "sunny $(ssh -n "$SUNNY_SSH" "$LDD" | tr '\n' ' ')"
  [ "$BEFORE_L" = "$AFTER_L" ] && [ "$BEFORE_S" = "$AFTER_S" ] &&
    echo "existing bundles unchanged (rain $(echo "$BEFORE_L" | grep -c .) files, sunny $(echo "$BEFORE_S" | grep -c .) files)" ||
    echo "EXISTING BUNDLE CHANGED"
  cat "$O/build_info.txt" 2>/dev/null
} > "$OUTF"
