#!/usr/bin/env bash
# deploy_feas.sh <check output file> - put gin-restore's feasibility builds (EXPERIMENT.md 9.15) on rain and sunny (main
# session only). One NEW directory per node, never overwriting a file:
#   ~/rs-bundle/rsx/      libnccl.so.2.32.3 = the rsx build (hw + rs_spike.diff; B1, and B2 with report lines only)
#                         + libnccl.so.2, libnccl.so links
#   ~/rs-bundle/app/      rs_spike (B1 and B2 application, built against the hw headers)
#   ~/rs-bundle/b3/       rs_drain_test (B3; no NCCL)
# ~/gi-bundle, ~/gd-bundle and ~/blind-bundle are not touched: read-only md5 of every file there before and after, on both
# nodes. Refuses if ~/rs-bundle exists on either node, or if a source is not the expected build (md5 below; EXPERIMENT.md
# 12). Checks, written to the output file only (never piped): md5 of every new file on both nodes equals the source; ldd of
# rs_spike resolves libnccl inside rs-bundle/rsx; ldd of rs_drain_test resolves libibverbs, libmlx5,
# libcuda. No GPU program, no RDMA traffic: ssh, scp and rsync on the management network only.
# env: SUNNY_SSH (required: user@sunny's management address, from ~/.config/rdma-error/mgmt.env), WANT_RSX,
#      WANT_APP, WANT_B3 (override only after a rebuild recorded in EXPERIMENT.md 12)
# usage: deploy_feas.sh <check output file>          the first deploy (2026-10-09; ~/rs-bundle must not exist)
#        deploy_feas.sh <check output file> rsx2     the second rsx build (after the pass-3 review) into the NEW directory
#                                                    ~/rs-bundle/rsx2/ (+ links); refuses unless ~/rs-bundle exists and
#                                                    ~/rs-bundle/rsx2 exists on neither node; every other file of
#                                                    ~/rs-bundle and of the other bundles must be the same before and after.
#                                                    env WANT_RSX2 (the rsx2 md5, EXPERIMENT.md 12)
#        deploy_feas.sh <check output file> b3v2     the second rs_drain_test build (setup self-check fix) into the NEW
#                                                    directory ~/rs-bundle/b3v2/, with the same refusals and checks;
#                                                    env WANT_B3V2
set -euo pipefail
OUTF=${1:?output file (the check is written to a file only; never pipe it)}
if [ "${2:-}" = rsx2 ] || [ "${2:-}" = b3v2 ]; then
  K=$2
  SUNNY_SSH=${SUNNY_SSH:?set SUNNY_SSH (user@address) from the management env file}
  SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
  if [ "$K" = rsx2 ]; then
    SRC=$SCR/agent_restore/out/rsx2/libnccl.so.2.32.3; FN=libnccl.so.2.32.3
    WANT=${WANT_RSX2:?expected md5 of the rsx2 libnccl (EXPERIMENT.md 12)}
    LDD2='cd $HOME/rs-bundle && echo "app rsx2: $(LD_LIBRARY_PATH=$HOME/rs-bundle/rsx2 ldd app/rs_spike | grep -E "nccl|not found" | tr -s " " | tr "\n" ";")"'
  else
    SRC=$SCR/agent_restore/out/b3v2/rs_drain_test; FN=rs_drain_test
    WANT=${WANT_B3V2:?expected md5 of the b3v2 rs_drain_test (EXPERIMENT.md 12)}
    LDD2='cd $HOME/rs-bundle && echo "b3v2: $(ldd b3v2/rs_drain_test | grep -E "ibverbs|mlx5|libcuda|not found" | tr -s " " | tr "\n" ";")"'
  fi
  md5() { md5sum < "$1" | cut -c1-32; }
  [ "$(md5 "$SRC")" = "$WANT" ] || { echo "$K is not the expected build" >&2; exit 1; }
  [ -d ~/rs-bundle ] && ssh -n "$SUNNY_SSH" '[ -d $HOME/rs-bundle ]' || { echo "~/rs-bundle missing on a node" >&2; exit 1; }
  if [ -e ~/rs-bundle/$K ] || ssh -n "$SUNNY_SSH" "[ -e \$HOME/rs-bundle/$K ]"; then echo "~/rs-bundle/$K exists on a node: refusing" >&2; exit 1; fi
  ex2="cd \$HOME && { for d in gi-bundle gd-bundle blind-bundle; do [ -d \"\$d\" ] && find \"\$d\" -type f -print; done; find rs-bundle -path rs-bundle/$K -prune -o \\( -type f -o -type l \\) -print; } | sort | xargs -r md5sum"
  BEFORE_L=$(bash -c "$ex2"); BEFORE_S=$(ssh -n "$SUNNY_SSH" "$ex2")
  mkdir ~/rs-bundle/$K
  cp "$SRC" ~/rs-bundle/$K/
  if [ "$K" = rsx2 ]; then (cd ~/rs-bundle/rsx2 && ln -s libnccl.so.2.32.3 libnccl.so.2 && ln -s libnccl.so.2 libnccl.so); else chmod +x ~/rs-bundle/$K/$FN; fi
  ssh -n "$SUNNY_SSH" "mkdir \$HOME/rs-bundle/$K"
  rsync -a ~/rs-bundle/$K/ "$SUNNY_SSH:rs-bundle/$K/"
  SUM2="cd \$HOME && find rs-bundle/$K -type f -print0 | sort -z | xargs -0 md5sum; ls -l rs-bundle/$K | grep -c ' -> ' || true"
  L=$(bash -c "$SUM2"); S=$(ssh -n "$SUNNY_SSH" "$SUM2")
  AFTER_L=$(bash -c "$ex2"); AFTER_S=$(ssh -n "$SUNNY_SSH" "$ex2")
  {
    echo "== $(date '+%F %T') $K (rain)"; echo "$L"
    echo "== sunny"; echo "$S"
    [ "$L" = "$S" ] && echo "$K: rain == sunny" || echo "$K MD5 MISMATCH"
    [ "$(md5 "$SRC")" = "$(md5 ~/rs-bundle/$K/$FN)" ] && echo "source == deployed: $K/$FN" || echo "SOURCE MISMATCH: $K"
    echo "rain $(bash -c "$LDD2")"; echo "sunny $(ssh -n "$SUNNY_SSH" "$LDD2")"
    [ "$BEFORE_L" = "$AFTER_L" ] && [ "$BEFORE_S" = "$AFTER_S" ] &&
      echo "existing files unchanged (rain $(echo "$BEFORE_L" | grep -c .) files, sunny $(echo "$BEFORE_S" | grep -c .) files, rs-bundle outside $K included)" ||
      echo "EXISTING FILE CHANGED"
    grep -E "^$K |^rs_drain_test $K |^rsx2 " "$SCR/agent_restore/out/build_info.txt" 2>/dev/null
  } > "$OUTF"
  exit 0
fi
SUNNY_SSH=${SUNNY_SSH:?set SUNNY_SSH (user@address) from the management env file}
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
O=$SCR/agent_restore/out
WANT_RSX=${WANT_RSX:?expected md5 of the rsx libnccl (EXPERIMENT.md 12)}
WANT_APP=${WANT_APP:?expected md5 of rs_spike (EXPERIMENT.md 12)}
WANT_B3=${WANT_B3:?expected md5 of rs_drain_test (EXPERIMENT.md 12)}
md5() { md5sum < "$1" | cut -c1-32; }
[ "$(md5 "$O/rsx/libnccl.so.2.32.3")" = "$WANT_RSX" ] || { echo "rsx libnccl is not the expected build" >&2; exit 1; }
[ "$(md5 "$O/app/rs_spike")" = "$WANT_APP" ] || { echo "rs_spike is not the expected build" >&2; exit 1; }
[ "$(md5 "$O/b3/rs_drain_test")" = "$WANT_B3" ] || { echo "rs_drain_test is not the expected build" >&2; exit 1; }
existing() { echo 'cd $HOME && for d in gi-bundle gd-bundle blind-bundle; do [ -d "$d" ] && find "$d" -type f -print; done | sort | xargs -r md5sum'; }
BEFORE_L=$(bash -c "$(existing)"); BEFORE_S=$(ssh -n "$SUNNY_SSH" "$(existing)")
if [ -e ~/rs-bundle ] || ssh -n "$SUNNY_SSH" '[ -e $HOME/rs-bundle ]'; then echo "~/rs-bundle exists on a node: refusing" >&2; exit 1; fi
# rain
mkdir -p ~/rs-bundle/rsx ~/rs-bundle/app ~/rs-bundle/b3
cp "$O/rsx/libnccl.so.2.32.3" ~/rs-bundle/rsx/
(cd ~/rs-bundle/rsx && ln -s libnccl.so.2.32.3 libnccl.so.2 && ln -s libnccl.so.2 libnccl.so)
cp "$O/app/rs_spike" ~/rs-bundle/app/
cp "$O/b3/rs_drain_test" ~/rs-bundle/b3/
chmod +x ~/rs-bundle/app/rs_spike ~/rs-bundle/b3/rs_drain_test
# sunny: the same files (the target does not exist there: checked above)
rsync -a ~/rs-bundle/ "$SUNNY_SSH:rs-bundle/"
SUM='cd $HOME && find rs-bundle -type f -print0 | sort -z | xargs -0 md5sum'
L=$(bash -c "$SUM"); S=$(ssh -n "$SUNNY_SSH" "$SUM")
LDD='cd $HOME/rs-bundle && echo "app rsx: $(LD_LIBRARY_PATH=$HOME/rs-bundle/rsx ldd app/rs_spike | grep -E "nccl|not found" | tr -s " " | tr "\n" ";")" && echo "b3: $(ldd b3/rs_drain_test | grep -E "ibverbs|mlx5|libcuda|not found" | tr -s " " | tr "\n" ";")" && echo "strace: $(command -v strace || echo missing)"'
AFTER_L=$(bash -c "$(existing)"); AFTER_S=$(ssh -n "$SUNNY_SSH" "$(existing)")
{
  echo "== $(date '+%F %T') new files (rain)"; echo "$L"
  echo "== sunny"; echo "$S"
  [ "$L" = "$S" ] && echo "new files: rain == sunny ($(echo "$L" | wc -l) files)" || echo "NEW FILES MD5 MISMATCH"
  for p in "rsx/libnccl.so.2.32.3:rsx/libnccl.so.2.32.3" "app/rs_spike:app/rs_spike" "b3/rs_drain_test:b3/rs_drain_test"; do
    [ "$(md5 "$O/${p%%:*}")" = "$(md5 ~/rs-bundle/"${p#*:}")" ] && echo "source == deployed: ${p%%:*}" || echo "SOURCE MISMATCH: ${p%%:*}"
  done
  echo "rain $(bash -c "$LDD" | tr '\n' ' ')"; echo "sunny $(ssh -n "$SUNNY_SSH" "$LDD" | tr '\n' ' ')"
  [ "$BEFORE_L" = "$AFTER_L" ] && [ "$BEFORE_S" = "$AFTER_S" ] &&
    echo "existing bundles unchanged (rain $(echo "$BEFORE_L" | grep -c .) files, sunny $(echo "$BEFORE_S" | grep -c .) files)" ||
    echo "EXISTING BUNDLE CHANGED"
  cat "$O/build_info.txt" 2>/dev/null
} > "$OUTF"
