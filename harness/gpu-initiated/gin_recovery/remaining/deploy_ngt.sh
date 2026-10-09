#!/usr/bin/env bash
# Deploy this study's NIC gate test (nic_gate_test.cu, EXPERIMENT.md 9, 5) to a NEW directory on rain (local) and sunny,
# never overwriting a file (a copy of deploy_hr.sh reduced to one file):
#   $HOME/gi-bundle/gin_ts2/ngt/nic_gate_test   (agent_ts2hr/out/ngt; no NCCL; libibverbs and libcuda of the node)
# The bundles hr, hrp, mr/hr (this study) and hq, hqp (gin-peer) are not touched.
# Refuses if the directory already holds a file on either node, or if the source is not the expected build (md5 below,
# recorded in EXPERIMENT.md 12). Checks, written to the output file only (never piped): the md5 of the deployed file on
# both nodes equals the source; ldd resolves libibverbs and libcuda on both nodes; the md5 of every file of the existing
# bundle $HOME/gi-bundle/gin_ts2 (outside the new directory) is the same before and after, on both nodes.
# usage: deploy_ngt.sh <check file>
set -euo pipefail
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
B=gi-bundle/gin_ts2
OUT=${1:?output file (the check is written to a file only; never pipe it)}
SRCF=$SCR/agent_ts2hr/out/ngt/nic_gate_test
WANT_NGT=${WANT_NGT:-abb2af4cb61a8075242f348c599b407a}
F=ngt/nic_gate_test
[ -f "$SRCF" ] || { echo "missing source $SRCF" >&2; exit 1; }
[ "$(md5sum < "$SRCF" | cut -d' ' -f1)" = "$WANT_NGT" ] || { echo "the source is not the expected build" >&2; exit 1; }
existing() { echo "cd ~/$B && find . -path ./ngt -prune -o -type f -print | sort | xargs md5sum"; }
BEFORE_L=$(bash -c "$(existing)"); BEFORE_S=$(ssh -n "$SUNNY_SSH" "$(existing)")
if [ -n "$(ls -A ~/$B/ngt 2>/dev/null)" ] || [ -n "$(ssh -n "$SUNNY_SSH" "ls -A ~/$B/ngt 2>/dev/null")" ]; then
  echo "$B/ngt is not empty on one node: refusing to overwrite" >&2; exit 1
fi
mkdir -p ~/$B/ngt; ssh -n "$SUNNY_SSH" "mkdir -p ~/$B/ngt"
[ ! -e ~/$B/$F ] || { echo "exists: $F" >&2; exit 1; }
cp "$SRCF" ~/$B/$F.tmp && mv -n ~/$B/$F.tmp ~/$B/$F && chmod +x ~/$B/$F
ssh -n "$SUNNY_SSH" "[ ! -e $B/$F ]" || { echo "exists on sunny: $F" >&2; exit 1; }
scp -q "$SRCF" "$SUNNY_SSH:$B/$F.tmp" && ssh -n "$SUNNY_SSH" "mv -n $B/$F.tmp $B/$F && chmod +x $B/$F"
SRCSUM="$(md5sum < "$SRCF" | cut -d' ' -f1)  $F"
L=$(cd ~/$B && md5sum $F); S=$(ssh -n "$SUNNY_SSH" "cd ~/$B && md5sum $F")
AFTER_L=$(bash -c "$(existing)"); AFTER_S=$(ssh -n "$SUNNY_SSH" "$(existing)")
{
  echo "== source"; echo "$SRCSUM"; cat "$SCR/agent_ts2hr/out/ngt/build_info.txt" 2>/dev/null
  echo "== rain"; echo "$L"; echo "== sunny"; echo "$S"
  echo "rain ldd: $(ldd ~/$B/$F | grep -E 'ibverbs|libcuda|not found' | tr -s ' \t' ' ' | tr '\n' ';')"
  ssh -n "$SUNNY_SSH" "echo \"sunny ldd: \$(ldd ~/$B/$F | grep -E 'ibverbs|libcuda|not found' | tr -s ' \t' ' ' | tr '\n' ';')\""
  [ "$L" = "$SRCSUM" ] && [ "$S" = "$SRCSUM" ] && echo "deployed md5 == source on both nodes" || echo "DEPLOYED MD5 MISMATCH"
  [ "$BEFORE_L" = "$AFTER_L" ] && [ "$BEFORE_S" = "$AFTER_S" ] && echo "existing bundle unchanged on both nodes ($(echo "$BEFORE_L" | wc -l) files each)" \
    || echo "EXISTING BUNDLE CHANGED"
} > "$OUT"
