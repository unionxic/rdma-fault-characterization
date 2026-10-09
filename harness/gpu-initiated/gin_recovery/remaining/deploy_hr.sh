#!/usr/bin/env bash
# Deploy this study's bundles to NEW directories on rain (local) and sunny, never overwriting a file (gin-remaining: a copy
# of ../peer/deploy_hq.sh with this study's directories and files):
#   $HOME/gi-bundle/gin_ts2/hr/      the research libnccl (agent_ts2hr/out/hr) + this study's gin_ts2 and hm_bench
#                                    (agent_ts2hr/out/drv); the hq controls run this gin_ts2 with the hq libnccl (DRVKEY=hr)
#   $HOME/gi-bundle/gin_ts2/hrp/     the production libnccl (agent_ts2hr/out/hrp, same source) + the same gin_ts2
#   $HOME/gi-bundle/gin_ts2/mr/hr/   this study's gin_mr (agent_ts2hr/out/mr); its libnccl comes from the bundle the
#                                    runner names (hr, or hq for the controls)
# The hq and hqp bundles of gin-peer are used as they are (controls, latency baseline) and are not touched; another study
# (blind-apps) uses them at the same time.
# Refuses if any of the three directories already holds a file on either node, or if a source file is not the expected
# build (md5 below, recorded in EXPERIMENT.md 5). Checks, written to the output file only (never piped): the md5 of every
# deployed file on both nodes equals the source; ldd of each driver resolves libnccl inside the bundle it runs with (hr,
# hrp; hr's gin_ts2 also with hq; mr/hr with hr and with hq); the md5 of every file of the existing bundle
# $HOME/gi-bundle/gin_ts2 (outside the new directories) is the same before and after, on both nodes.
# usage: deploy_hr.sh <check file>
set -euo pipefail
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
B=gi-bundle/gin_ts2
OUT=${1:?output file (the check is written to a file only; never pipe it)}
H=$SCR/agent_ts2hr/out
# the builds recorded in EXPERIMENT.md 5 (override only after a rebuild that is recorded there)
WANT_HR=${WANT_HR:-2dee2b5bf36b3477dd85f0197987f028}
WANT_HRP=${WANT_HRP:-786f70bcb82ea21cb678dcb056256ed5}
WANT_DRV=${WANT_DRV:-4e81d8d8e7418f84fe1804284378d618}
WANT_BENCH=${WANT_BENCH:-a00094b07445f2ddc5baff3a5c5626bb}
WANT_MR=${WANT_MR:-d588e9cecfc05fd114e61d83ce9c3074}
declare -A SRC WANT
SRC[hr/libnccl.so.2.32.3]=$H/hr/libnccl.so.2.32.3;   WANT[hr/libnccl.so.2.32.3]=$WANT_HR
SRC[hr/gin_ts2]=$H/drv/gin_ts2;                      WANT[hr/gin_ts2]=$WANT_DRV
SRC[hr/hm_bench]=$H/drv/hm_bench;                    WANT[hr/hm_bench]=$WANT_BENCH
SRC[hrp/libnccl.so.2.32.3]=$H/hrp/libnccl.so.2.32.3; WANT[hrp/libnccl.so.2.32.3]=$WANT_HRP
SRC[hrp/gin_ts2]=$H/drv/gin_ts2;                     WANT[hrp/gin_ts2]=$WANT_DRV
SRC[mr/hr/gin_mr]=$H/mr/gin_mr;                      WANT[mr/hr/gin_mr]=$WANT_MR
FILES="hr/libnccl.so.2.32.3 hr/gin_ts2 hr/hm_bench hrp/libnccl.so.2.32.3 hrp/gin_ts2 mr/hr/gin_mr"
DIRS="hr hrp mr/hr"
for f in $FILES; do
  [ -f "${SRC[$f]}" ] || { echo "missing source for $f" >&2; exit 1; }
  [ "$(md5sum < "${SRC[$f]}" | cut -d' ' -f1)" = "${WANT[$f]}" ] || { echo "the source of $f is not the expected build" >&2; exit 1; }
done
for k in hq hqp; do  # the controls' bundles must be there (read only)
  [ -f ~/$B/$k/libnccl.so.2 ] && ssh -n "$SUNNY_SSH" "[ -f $B/$k/libnccl.so.2 ]" || { echo "bundle $k missing on a node" >&2; exit 1; }
done
existing() { echo "cd ~/$B && find . \( -path ./hr -o -path ./hrp -o -path ./mr/hr \) -prune -o -type f -print | sort | xargs md5sum"; }
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
for d in hr hrp; do
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
  for d in hr hrp; do
    echo "rain $d: $(cd ~/$B/$d && LD_LIBRARY_PATH=$HOME/$B/$d ldd ./gin_ts2 | grep nccl)"
    ssh -n "$SUNNY_SSH" "cd ~/$B/$d && echo \"sunny $d: \$(LD_LIBRARY_PATH=\$HOME/$B/$d ldd ./gin_ts2 | grep nccl)\""
  done
  echo "rain hr/gin_ts2 with hq: $(LD_LIBRARY_PATH=$HOME/$B/hq ldd ~/$B/hr/gin_ts2 | grep nccl)"
  ssh -n "$SUNNY_SSH" "echo \"sunny hr/gin_ts2 with hq: \$(LD_LIBRARY_PATH=\$HOME/$B/hq ldd ~/$B/hr/gin_ts2 | grep nccl)\""
  for lib in hr hq; do
    echo "rain mr/hr with $lib: $(LD_LIBRARY_PATH=$HOME/$B/$lib ldd ~/$B/mr/hr/gin_mr | grep nccl)"
    ssh -n "$SUNNY_SSH" "echo \"sunny mr/hr with $lib: \$(LD_LIBRARY_PATH=\$HOME/$B/$lib ldd ~/$B/mr/hr/gin_mr | grep nccl)\""
  done
  [ "$L" = "$SRCSUM" ] && [ "$S" = "$SRCSUM" ] && echo "deployed md5 == source on both nodes" || echo "DEPLOYED MD5 MISMATCH"
  [ "$BEFORE_L" = "$AFTER_L" ] && [ "$BEFORE_S" = "$AFTER_S" ] && echo "existing bundle unchanged on both nodes ($(echo "$BEFORE_L" | wc -l) files each)" \
    || echo "EXISTING BUNDLE CHANGED"
  echo "== existing bundle md5 (rain)"; echo "$AFTER_L"
  echo "== existing bundle md5 (sunny)"; echo "$AFTER_S"
} > "$OUT"
