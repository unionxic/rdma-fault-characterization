#!/usr/bin/env bash
# deploy_blind.sh <check output file> - put blind-apps' bundle and Python stack on rain and sunny (main session).
#
# New directories only, never overwriting a file:
#   ~/blind-bundle/s2/       libnccl.so.2.23.4 = the Stage 2 build 9ed03e1d (scratch nccl_rkey_build), + libnccl.so.2
#   ~/blind-bundle/hq/       libnccl.so.2.32.3 = gin-peer's hq c1311625 (scratch agent_ts2hq/build), + links,
#                            blind_gin_ring (build_blind.sh gin)
#   ~/blind-bundle/nvs/      lib/ = a copy of ~/gi-bundle/nvshmem_t1_380/lib (t1_380, transport d6ae3699, host 825443f8),
#                            blind_nvs_rr, blind_nvs_boot.so (build_blind.sh nvs)
#   ~/blind-bundle/ddp/      ddp_entry.py           ~/blind-bundle/agent/  node_agent.py      ~/blind-bundle/run/ (empty)
#   ~/blind-venv/ on sunny   a byte copy of rain's ~/blind-venv/{py310,nanoGPT,MANIFEST.md5,install_info.txt}
#                            (install_venv.sh on rain; sunny needs no network and no pip)
# Refuses if ~/blind-bundle exists on either node, if ~/blind-venv/py310 exists on sunny, or if a source differs from
# its expected md5. Checks, written to the output file only (never piped): the md5 of every bundle file on both nodes
# equals the source; sunny's venv passes `md5sum -c` of rain's MANIFEST.md5; ldd of both binaries resolves libnccl and
# libnvshmem_host inside the bundle; on both nodes, `import torch` with the Stage 2 library in LD_PRELOAD maps that
# library and no other libnccl (no CUDA call); the md5 of every file of the existing bundles (~/gi-bundle, ~/nb-bundle,
# ~/nccl-ct) is the same before and after. No GPU program, no RDMA traffic: ssh, scp and rsync on the management
# network only.
set -euo pipefail
OUTF=${1:?output file (the check is written to a file only; never pipe it)}
D=$(cd "$(dirname "$0")" && pwd)
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
BO=${BLIND_BUILD_OUT:-$SCR/agent_blind/out}
B=blind-bundle
V=blind-venv
declare -A SRC=(
  [s2/libnccl.so.2.23.4]=$SCR/nccl_rkey_build/lib/libnccl.so.2.23.4
  [hq/libnccl.so.2.32.3]=$SCR/agent_ts2hq/build/lib/libnccl.so.2.32.3
  [hq/blind_gin_ring]=$BO/gin/blind_gin_ring
  [nvs/blind_nvs_rr]=$BO/nvs/blind_nvs_rr
  [nvs/blind_nvs_boot.so]=$BO/nvs/blind_nvs_boot.so
  [ddp/ddp_entry.py]=$D/ddp/ddp_entry.py
  [agent/node_agent.py]=$D/node_agent.py
)
[ "$(md5sum < "${SRC[s2/libnccl.so.2.23.4]}" | cut -c1-32)" = 9ed03e1d4b9833c0c2e01f3aa1f84d1c ] || { echo "s2 is not 9ed03e1d" >&2; exit 1; }
[ "$(md5sum < "${SRC[hq/libnccl.so.2.32.3]}" | cut -c1-32)" = c1311625c7a06c785bc313558504f982 ] || { echo "hq is not c1311625" >&2; exit 1; }
[ "$(md5sum < "$HOME/gi-bundle/nvshmem_t1_380/lib/nvshmem_transport_ibgda.so.7.0.0" | cut -c1-32)" = d6ae3699f95bfeaf0f36af6ebba95b7e ] ||
  { echo "the t1_380 transport is not d6ae3699" >&2; exit 1; }
for f in "${!SRC[@]}"; do [ -f "${SRC[$f]}" ] || { echo "missing source ${SRC[$f]}" >&2; exit 1; }; done
[ -f "$HOME/$V/MANIFEST.md5" ] || { echo "run install_venv.sh on rain first" >&2; exit 1; }
existing() { echo 'for d in $HOME/gi-bundle $HOME/nb-bundle $HOME/nccl-ct; do [ -d "$d" ] && find "$d" -type f -print0 | sort -z | xargs -0 md5sum; done; true'; }
BEFORE_L=$(bash -c "$(existing)"); BEFORE_S=$(ssh -n "$SUNNY_SSH" "$(existing)")
if [ -e "$HOME/$B" ] || ssh -n "$SUNNY_SSH" "[ -e \$HOME/$B ]"; then echo "\$HOME/$B exists on one node: refusing" >&2; exit 1; fi
if ssh -n "$SUNNY_SSH" "[ -e \$HOME/$V/py310 ]"; then echo "sunny already has \$HOME/$V/py310: refusing" >&2; exit 1; fi
# rain
mkdir "$HOME/$B" "$HOME/$B/s2" "$HOME/$B/hq" "$HOME/$B/nvs" "$HOME/$B/ddp" "$HOME/$B/agent" "$HOME/$B/run"
for f in "${!SRC[@]}"; do cp "${SRC[$f]}" "$HOME/$B/$f"; done
cp -a "$HOME/gi-bundle/nvshmem_t1_380/lib" "$HOME/$B/nvs/lib"
(cd "$HOME/$B/s2" && ln -s libnccl.so.2.23.4 libnccl.so.2 && ln -s libnccl.so.2 libnccl.so)
(cd "$HOME/$B/hq" && ln -s libnccl.so.2.32.3 libnccl.so.2 && ln -s libnccl.so.2 libnccl.so)
# sunny: the same tree, then the venv
ssh -n "$SUNNY_SSH" "mkdir \$HOME/$B"
rsync -a "$HOME/$B/" "$SUNNY_SSH:$B/"
ssh -n "$SUNNY_SSH" "mkdir -p \$HOME/$V"
rsync -a "$HOME/$V/py310" "$HOME/$V/nanoGPT" "$HOME/$V/MANIFEST.md5" "$HOME/$V/install_info.txt" "$SUNNY_SSH:$V/"
SUM='cd $HOME/blind-bundle && find . -type f -print0 | sort -z | xargs -0 md5sum'
L=$(bash -c "$SUM"); S=$(ssh -n "$SUNNY_SSH" "$SUM")
VCHK=$(ssh -n "$SUNNY_SSH" "cd \$HOME/$V && md5sum -c --quiet MANIFEST.md5 > /dev/null 2>&1 && echo venv_ok || echo venv_MISMATCH")
LDD='cd $HOME/blind-bundle && echo "gin: $(LD_LIBRARY_PATH=$HOME/blind-bundle/hq ldd hq/blind_gin_ring | grep -E "nccl|not found" | tr -s " " | tr "\n" ";")" && echo "nvs: $(LD_LIBRARY_PATH=$HOME/blind-bundle/nvs/lib ldd nvs/blind_nvs_rr | grep -E "nvshmem|not found" | tr -s " " | tr "\n" ";")"'
PRE='cd /tmp && PYTHONDONTWRITEBYTECODE=1 LD_PRELOAD=$HOME/blind-bundle/s2/libnccl.so.2.23.4 timeout 120 $HOME/blind-venv/py310/bin/python3.10 -c "import torch; m={l.split()[-1] for l in open(\"/proc/self/maps\") if \"libnccl\" in l}; print(\"torch\", torch.__version__, \"libnccl mapped:\", sorted(m))"'
AFTER_L=$(bash -c "$(existing)"); AFTER_S=$(ssh -n "$SUNNY_SSH" "$(existing)")
{
  echo "== $(date '+%F %T') blind-bundle md5 (rain)"; echo "$L"
  echo "== sunny"; echo "$S"
  [ "$L" = "$S" ] && echo "bundle: rain == sunny ($(echo "$L" | wc -l) files)" || echo "BUNDLE MD5 MISMATCH"
  for f in "${!SRC[@]}"; do
    [ "$(md5sum < "${SRC[$f]}" | cut -c1-32)" = "$(md5sum < "$HOME/$B/$f" | cut -c1-32)" ] && echo "source == deployed: $f" || echo "SOURCE MISMATCH: $f"
  done
  echo "venv on sunny against rain's MANIFEST.md5 ($(wc -l < "$HOME/$V/MANIFEST.md5") files): $VCHK"
  echo "rain $(bash -c "$LDD" | tr '\n' ' ')"; echo "sunny $(ssh -n "$SUNNY_SSH" "$LDD" | tr '\n' ' ')"
  echo "rain $(bash -c "$PRE" 2>&1 | tail -1)"; echo "sunny $(ssh -n "$SUNNY_SSH" "$PRE" 2>&1 | tail -1)"
  [ "$BEFORE_L" = "$AFTER_L" ] && [ "$BEFORE_S" = "$AFTER_S" ] &&
    echo "existing bundles unchanged (rain $(echo "$BEFORE_L" | grep -c .) files, sunny $(echo "$BEFORE_S" | grep -c .) files)" ||
    echo "EXISTING BUNDLE CHANGED"
} > "$OUTF"
