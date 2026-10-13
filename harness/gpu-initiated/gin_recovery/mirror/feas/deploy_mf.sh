#!/usr/bin/env bash
# deploy_mf.sh <check output file> <set> - put one gin-mirror feasibility build on rain and sunny (main session only), into ONE
# NEW directory per node, never overwriting a file (as ../../restore/feas/deploy_feas.sh):
#   mf     ~/rs-bundle/mf/mirror_feas   source $SCR/mirror_feas/$MF_BUILD/mirror_feas (MF_BUILD: mf2), env WANT_MF = its md5
#                                       as recorded in EXPERIMENT.md 12 (build_mf.sh prints it)
#   mfcm   ~/rs-bundle/mfcm/gin_ts2     source CM_SRC (required: the test work package's manual-mirror gin_ts2, cost_man.md),
#                                       env WANT_MFCM = its md5
# Refuses if ~/rs-bundle is missing on a node, if ~/rs-bundle/<set> exists on either node, or if the source is not the
# expected build. ~/gi-bundle, ~/gd-bundle, ~/blind-bundle and every other file and link of ~/rs-bundle are read (md5) before
# and after on both nodes and must be unchanged. The checks are written to the output file only (never piped): md5 of the
# new file on both nodes == the source; ldd resolves libibverbs, libmlx5 and libcuda (mf) or libnccl inside CMLIB (mfcm,
# default ~/rs-bundle/i5/lib/rsp, read only). No GPU program, no RDMA traffic: ssh and rsync on the management network only.
# env: SUNNY_SSH (required: user@sunny's management address, from the management env file; never written by this script)
set -euo pipefail
OUTF=${1:?output file (the check is written to a file only; never pipe it)}
K=${2:?set: mf or mfcm}
SUNNY_SSH=${SUNNY_SSH:?set SUNNY_SSH (user@address) from the management env file}
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
CMLIB=${CMLIB:-\$HOME/rs-bundle/i5/lib/rsp}
case "$K" in
  mf)   SRC=$SCR/mirror_feas/${MF_BUILD:-mf2}/mirror_feas; FN=mirror_feas
        WANT=${WANT_MF:?expected md5 of mirror_feas (EXPERIMENT.md 12)}
        LDD="cd \$HOME/rs-bundle && echo \"mf: \$(ldd mf/mirror_feas | grep -E 'ibverbs|mlx5|libcuda|not found' | tr -s ' ' | tr '\n' ';')\"" ;;
  mfcm) SRC=${CM_SRC:?CM_SRC: the manual-mirror gin_ts2 build (cost_man.md)}; FN=gin_ts2
        WANT=${WANT_MFCM:?expected md5 of the manual-mirror gin_ts2 (EXPERIMENT.md 12)}
        LDD="cd \$HOME/rs-bundle && echo \"mfcm: \$(LD_LIBRARY_PATH=$CMLIB ldd mfcm/gin_ts2 | grep -E 'nccl|not found' | tr -s ' ' | tr '\n' ';')\"" ;;
  *) echo "set must be mf or mfcm" >&2; exit 2 ;;
esac
md5() { md5sum < "$1" | cut -c1-32; }
[ -f "$SRC" ] && [ "$(md5 "$SRC")" = "$WANT" ] || { echo "$SRC is not the expected build" >&2; exit 1; }
[ -d ~/rs-bundle ] && ssh -n "$SUNNY_SSH" '[ -d $HOME/rs-bundle ]' || { echo "~/rs-bundle missing on a node" >&2; exit 1; }
if [ -e ~/rs-bundle/$K ] || ssh -n "$SUNNY_SSH" "[ -e \$HOME/rs-bundle/$K ]"; then echo "~/rs-bundle/$K exists on a node: refusing" >&2; exit 1; fi
EX="cd \$HOME && { for d in gi-bundle gd-bundle blind-bundle; do [ -d \"\$d\" ] && find \"\$d\" -type f -print; done; find rs-bundle -path rs-bundle/$K -prune -o \\( -type f -o -type l \\) -print; } | sort | xargs -r md5sum"
BEFORE_L=$(bash -c "$EX"); BEFORE_S=$(ssh -n "$SUNNY_SSH" "$EX")
mkdir ~/rs-bundle/$K
cp "$SRC" ~/rs-bundle/$K/$FN
chmod 755 ~/rs-bundle/$K/$FN
ssh -n "$SUNNY_SSH" "mkdir \$HOME/rs-bundle/$K"
rsync -a ~/rs-bundle/$K/ "$SUNNY_SSH:rs-bundle/$K/"
SUM="cd \$HOME && find rs-bundle/$K -type f -print0 | sort -z | xargs -0 md5sum"
L=$(bash -c "$SUM"); S=$(ssh -n "$SUNNY_SSH" "$SUM")
AFTER_L=$(bash -c "$EX"); AFTER_S=$(ssh -n "$SUNNY_SSH" "$EX")
{
  echo "== $(date '+%F %T') $K (rain)"; echo "$L"
  echo "== sunny"; echo "$S"
  [ "$L" = "$S" ] && echo "$K: rain == sunny" || echo "$K MD5 MISMATCH"
  [ "$(md5 "$SRC")" = "$(md5 ~/rs-bundle/$K/$FN)" ] && echo "source == deployed: $K/$FN" || echo "SOURCE MISMATCH: $K"
  echo "rain $(bash -c "$LDD")"; echo "sunny $(ssh -n "$SUNNY_SSH" "$LDD")"
  [ "$BEFORE_L" = "$AFTER_L" ] && [ "$BEFORE_S" = "$AFTER_S" ] &&
    echo "existing files unchanged (rain $(echo "$BEFORE_L" | grep -c .) files, sunny $(echo "$BEFORE_S" | grep -c .) files, rs-bundle outside $K included)" ||
    echo "EXISTING FILE CHANGED"
  [ "$K" = mf ] && [ -f "$(dirname "$SRC")/build_src.txt" ] && echo "mf build: $(cat "$(dirname "$SRC")/build_src.txt")"
} > "$OUTF"
exit 0
