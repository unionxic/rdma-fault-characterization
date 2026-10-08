#!/usr/bin/env bash
# Deploy this study's bundles to NEW directories on rain (local) and sunny, never overwriting a file:
#   $HOME/gi-bundle/gin_ts2/hq/      the research libnccl (agent_ts2hq/out/hq) + this study's gin_ts2 (agent_ts2hq/out/drv)
#   $HOME/gi-bundle/gin_ts2/hqp/     the production libnccl (agent_ts2hq/out/hqp, same source) + the same gin_ts2
#   $HOME/gi-bundle/gin_ts2/mr/hq/   this study's gin_mr (agent_ts2hq/out/mr); its libnccl comes from the bundle the
#                                    runner names (hq, or hf for the controls)
# The hf and hfp bundles of gin-handoff are used as they are (controls, latency baseline) and are not touched.
# Refuses if any of the three directories already holds a file on either node, or if a source file is not the expected
# build (md5 below, recorded in EXPERIMENT.md 5). Checks, written to the output file only (never piped): the md5 of every
# deployed file on both nodes equals the source; ldd of each driver resolves libnccl inside the bundle it runs with (hq,
# hqp; mr/hq with hq and with hf); the md5 of every file of the existing bundle $HOME/gi-bundle/gin_ts2 (outside the new
# directories) is the same before and after, on both nodes.
# usage: deploy_hq.sh <check file>
set -euo pipefail
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
B=gi-bundle/gin_ts2
OUT=${1:?output file (the check is written to a file only; never pipe it)}
H=$SCR/agent_ts2hq/out
# the builds recorded in EXPERIMENT.md 5 (override only after a rebuild that is recorded there)
WANT_HQ=${WANT_HQ:-c1311625c7a06c785bc313558504f982}
WANT_HQP=${WANT_HQP:-4fa076e113e43774a9dc2f46298df43b}
WANT_DRV=${WANT_DRV:-3e053ff2ab069ec64198ed4e0f6e237a}
WANT_MR=${WANT_MR:-7f0fc272962b293da0bd0d3655aacc4d}
declare -A SRC WANT
SRC[hq/libnccl.so.2.32.3]=$H/hq/libnccl.so.2.32.3;   WANT[hq/libnccl.so.2.32.3]=$WANT_HQ
SRC[hq/gin_ts2]=$H/drv/gin_ts2;                      WANT[hq/gin_ts2]=$WANT_DRV
SRC[hqp/libnccl.so.2.32.3]=$H/hqp/libnccl.so.2.32.3; WANT[hqp/libnccl.so.2.32.3]=$WANT_HQP
SRC[hqp/gin_ts2]=$H/drv/gin_ts2;                     WANT[hqp/gin_ts2]=$WANT_DRV
SRC[mr/hq/gin_mr]=$H/mr/gin_mr;                      WANT[mr/hq/gin_mr]=$WANT_MR
FILES="hq/libnccl.so.2.32.3 hq/gin_ts2 hqp/libnccl.so.2.32.3 hqp/gin_ts2 mr/hq/gin_mr"
DIRS="hq hqp mr/hq"
for f in $FILES; do
  [ -f "${SRC[$f]}" ] || { echo "missing source for $f" >&2; exit 1; }
  [ "$(md5sum < "${SRC[$f]}" | cut -d' ' -f1)" = "${WANT[$f]}" ] || { echo "the source of $f is not the expected build" >&2; exit 1; }
done
for k in hf hfp; do  # the controls' bundles must be there (read only)
  [ -f ~/$B/$k/libnccl.so.2 ] && ssh -n "$SUNNY_SSH" "[ -f $B/$k/libnccl.so.2 ]" || { echo "bundle $k missing on a node" >&2; exit 1; }
done
existing() { echo "cd ~/$B && find . \( -path ./hq -o -path ./hqp -o -path ./mr/hq \) -prune -o -type f -print | sort | xargs md5sum"; }
BEFORE_L=$(bash -c "$(existing)"); BEFORE_S=$(ssh -n "$SUNNY_SSH" "$(existing)")
for d in $DIRS; do
  if [ -n "$(ls -A ~/$B/$d 2>/dev/null)" ] || [ -n "$(ssh -n "$SUNNY_SSH" "ls -A ~/$B/$d 2>/dev/null")" ]; then
    echo "$B/$d is not empty on one node: refusing to overwrite" >&2; exit 1
  fi
done
put() {  # put <src> <dst relative to ~/$B>; the destination must not exist
  [ ! -e ~/$B/"$2" ] || { echo "exists: $2" >&2; exit 1; }
  cp "$1" ~/$B/"$2.tmp" && mv -n ~/$B/"$2.tmp" ~/$B/"$2"
  ssh -n "$SUNNY_SSH" "[ ! -e $B/$2 ]" || { echo "exists on sunny: $2" >&2; exit 1; }
  scp -q "$1" "$SUNNY_SSH:$B/$2.tmp" && ssh -n "$SUNNY_SSH" "mv -n $B/$2.tmp $B/$2 && chmod +x $B/$2"
}
for d in $DIRS; do mkdir -p ~/$B/$d; ssh -n "$SUNNY_SSH" "mkdir -p ~/$B/$d"; done
for f in $FILES; do put "${SRC[$f]}" "$f"; done
for d in hq hqp; do
  (cd ~/$B/$d && ln -s libnccl.so.2.32.3 libnccl.so.2 && ln -s libnccl.so.2 libnccl.so)
  ssh -n "$SUNNY_SSH" "cd ~/$B/$d && ln -s libnccl.so.2.32.3 libnccl.so.2 && ln -s libnccl.so.2 libnccl.so"
done
SRCSUM=""
for f in $FILES; do SRCSUM="$SRCSUM$(md5sum < "${SRC[$f]}" | cut -d' ' -f1)  $f
"; done
SRCSUM=$(printf '%s' "$SRCSUM")
# shellcheck disable=SC2086
L=$(cd ~/$B && md5sum $FILES); S=$(ssh -n "$SUNNY_SSH" "cd ~/$B && md5sum $FILES")
AFTER_L=$(bash -c "$(existing)"); AFTER_S=$(ssh -n "$SUNNY_SSH" "$(existing)")
{
  echo "== source"; echo "$SRCSUM"; cat "$H/build_info.txt" 2>/dev/null
  echo "== rain"; echo "$L"; echo "== sunny"; echo "$S"
  for d in hq hqp; do
    echo "rain $d: $(cd ~/$B/$d && LD_LIBRARY_PATH=$HOME/$B/$d ldd ./gin_ts2 | grep nccl)"
    ssh -n "$SUNNY_SSH" "cd ~/$B/$d && echo \"sunny $d: \$(LD_LIBRARY_PATH=\$HOME/$B/$d ldd ./gin_ts2 | grep nccl)\""
  done
  for lib in hq hf; do
    echo "rain mr/hq with $lib: $(LD_LIBRARY_PATH=$HOME/$B/$lib ldd ~/$B/mr/hq/gin_mr | grep nccl)"
    ssh -n "$SUNNY_SSH" "echo \"sunny mr/hq with $lib: \$(LD_LIBRARY_PATH=\$HOME/$B/$lib ldd ~/$B/mr/hq/gin_mr | grep nccl)\""
  done
  [ "$L" = "$SRCSUM" ] && [ "$S" = "$SRCSUM" ] && echo "deployed md5 == source on both nodes" || echo "DEPLOYED MD5 MISMATCH"
  [ "$BEFORE_L" = "$AFTER_L" ] && [ "$BEFORE_S" = "$AFTER_S" ] && echo "existing bundle unchanged on both nodes ($(echo "$BEFORE_L" | wc -l) files each)" \
    || echo "EXISTING BUNDLE CHANGED"
  echo "== existing bundle md5 (rain)"; echo "$AFTER_L"
  echo "== existing bundle md5 (sunny)"; echo "$AFTER_S"
} > "$OUT"
