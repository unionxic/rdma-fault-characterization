#!/usr/bin/env bash
# deploy_mi.sh <check output file> - put gin-mirror's test-branch files on rain and sunny (MAIN SESSION only), in
# gin-restore's deploy_rs.sh style: NEW directories under ~/rs-bundle/<RS_SET>/ only (nothing is written into ~/gi-bundle,
# ~/gd-bundle or ~/blind-bundle, nor into gin-restore's or the feasibility tools' first-set folders); never overwriting a
# file; a read-only md5 of every existing file of those bundles before and after on both nodes (the new directories left
# out); md5 of every new file on both nodes against its source; ldd of the programs. ssh, scp and rsync on the management
# network only; no GPU program, no RDMA traffic. RS_SET is required (gin-mirror never uses the first set's paths).
#   ~/rs-bundle/<RS_SET>/lib/mi/     the mirror research libnccl (+ .so.2, .so links)   source MI_LIB_SRC,  md5 WANT_MI
#   ~/rs-bundle/<RS_SET>/lib/mip/    the mirror production libnccl (+ links)             source MIP_LIB_SRC, md5 WANT_MIP
#   ~/rs-bundle/<RS_SET>/mitest/     gin_mi (macro), gin_mi_nomacro, gin_ts2_mi (cost)   out/<MIOUT>/ and out/cost/,
#                                                                                        md5 WANT_GINMI, WANT_GINMI_NOMACRO,
#                                                                                        WANT_COST_MI
#   ~/rs-bundle/<RS_SET>/mr/ff/, mr/hold/   gin_mr against the mirror layer's headers    out/mr/,  md5 WANT_MR_FF, WANT_MR_HOLD
# An artifact is deployed only when its WANT_* is set, and then its source must exist and match (else the script refuses
# before touching anything). Refuses if a target directory exists on either node. The libraries are MI_LIB_SRC and
# MIP_LIB_SRC ($SCR/<MITREE>/out/<build>/libnccl.so.2.32.3: the integrated tree agent_mi_int, or since the fixes of pilot 1
# the fix tree agent_mi_fix; PILOT_MI.md names them); the drivers are build_mi_test.sh's outputs of the same tree
# ($SCR/<MITREE>/test/out). The md5 checks (WANT_*) are what keeps a driver built with other headers away from a library:
# the device does not read the side table's magic.
# env: SUNNY_SSH (required), RS_SET (required), the WANT_* above, MI_LIB_SRC, MIP_LIB_SRC, MIOUT (default mi), MITREE
#      (default agent_mi_int; agent_mi_fix for the drivers of the fixes of pilot 1)
set -euo pipefail
OUTF=${1:?output file (the check is written to a file only; never pipe it)}
SUNNY_SSH=${SUNNY_SSH:?set SUNNY_SSH (user@address) from the management env file}
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
MITREE=${MITREE:-agent_mi_int}  # agent_mi_fix: the drivers built against the fixes of pilot 1 (2026-10-15)
case "$MITREE" in agent_mi_int | agent_mi_fix) ;; *) echo "MITREE is agent_mi_int or agent_mi_fix" >&2; exit 2 ;; esac
T=$SCR/$MITREE/test/out  # the drivers build_mi_test.sh built against that tree's headers (MITREE as there)
MIOUT=${MIOUT:-mi}
RS_SET=${RS_SET:-}
. "$(cd "$(dirname "$0")" && pwd)/rs_set_mi.sh"
rs_set_check || exit 1
B=rs-bundle/$RS_SET   # the set's folder, relative to $HOME
# sunny must answer first (the integration's review: an ssh failure would read as "absent" below)
ssh -n "$SUNNY_SSH" true || { echo "sunny does not answer over ssh: nothing deployed" >&2; exit 1; }
md5() { md5sum < "$1" | cut -c1-32; }
# artifact table: <WANT var>|<source>|<target dir relative to $HOME>|<file name>|<lib: 1 = add .so.2/.so links>
ART=(
  "WANT_MI|${MI_LIB_SRC:-}|$B/lib/mi|libnccl.so.2.32.3|1"
  "WANT_MIP|${MIP_LIB_SRC:-}|$B/lib/mip|libnccl.so.2.32.3|1"
  "WANT_GINMI|$T/$MIOUT/gin_mi|$B/mitest|gin_mi|0"
  "WANT_GINMI_NOMACRO|$T/$MIOUT/gin_mi_nomacro|$B/mitest|gin_mi_nomacro|0"
  "WANT_COST_MI|$T/cost/gin_ts2_mi|$B/mitest|gin_ts2_mi|0"
  "WANT_MR_FF|$T/mr/ff/gin_mr|$B/mr/ff|gin_mr|0"
  "WANT_MR_HOLD|$T/mr/hold/gin_mr|$B/mr/hold|gin_mr|0"
)
SEL=(); DIRS=()
for a in "${ART[@]}"; do
  IFS='|' read -r want src dir fn lib <<< "$a"
  w=${!want:-}
  [ -n "$w" ] || continue
  [ -f "$src" ] || { echo "$want set but its source is missing ($src)" >&2; exit 1; }
  [ "$(md5 "$src")" = "$w" ] || { echo "$src is not the expected build ($want)" >&2; exit 1; }
  SEL+=("$a")
  case " ${DIRS[*]:-} " in *" $dir "*) ;; *) DIRS+=("$dir") ;; esac
done
[ "${#SEL[@]}" -gt 0 ] || { echo "nothing selected: set the WANT_* of the artifacts to deploy" >&2; exit 1; }
for dir in "${DIRS[@]}"; do
  if [ -e "$HOME/$dir" ] || ssh -n "$SUNNY_SSH" "[ -e \$HOME/$dir ]"; then echo "~/$dir exists on a node: refusing" >&2; exit 1; fi
done
# a set of gin-restore (it has lib/rs, lib/rsp, rstest or rscost) is not reused: gin-mirror takes a set name of its own
for g in lib/rs lib/rsp rstest rscost; do
  if [ -e "$HOME/$B/$g" ] || ssh -n "$SUNNY_SSH" "[ -e \$HOME/$B/$g ]"; then echo "~/$B is a gin-restore set ($g): use a new RS_SET" >&2; exit 1; fi
done
prune=""; for dir in "${DIRS[@]}"; do prune="$prune -path $dir -prune -o"; done
EXIST="cd \$HOME && { for d in gi-bundle gd-bundle blind-bundle rs-bundle; do [ -d \"\$d\" ] && find \"\$d\" $prune \\( -type f -o -type l \\) -print; done; } | sort | xargs -r md5sum"
BEFORE_L=$(bash -c "$EXIST"); BEFORE_S=$(ssh -n "$SUNNY_SSH" "$EXIST")
for a in "${SEL[@]}"; do
  IFS='|' read -r want src dir fn lib <<< "$a"
  mkdir -p "$HOME/$dir"; ssh -n "$SUNNY_SSH" "mkdir -p \$HOME/$dir"
  cp "$src" "$HOME/$dir/$fn"
  if [ "$lib" = 1 ]; then
    (cd "$HOME/$dir" && ln -s libnccl.so.2.32.3 libnccl.so.2 && ln -s libnccl.so.2 libnccl.so)
  else
    chmod +x "$HOME/$dir/$fn"
  fi
done
for dir in "${DIRS[@]}"; do rsync -a "$HOME/$dir/" "$SUNNY_SSH:$dir/"; done
AFTER_L=$(bash -c "$EXIST"); AFTER_S=$(ssh -n "$SUNNY_SSH" "$EXIST")
NEWSUM="cd \$HOME && find ${DIRS[*]} -type f -print0 | sort -z | xargs -0 md5sum; find ${DIRS[*]} -type l | sort"
L=$(bash -c "$NEWSUM"); S=$(ssh -n "$SUNNY_SSH" "$NEWSUM")
LDD='cd $HOME/__B__ && for p in mitest/gin_mi:lib/mi mitest/gin_mi_nomacro:lib/mi mitest/gin_ts2_mi:lib/mip mr/ff/gin_mr:lib/mi mr/hold/gin_mr:lib/mi; do b=${p%%:*}; l=${p#*:}; l=$HOME/__B__/$l; [ -f "$b" ] && echo "$b: $(LD_LIBRARY_PATH=$l ldd $b | grep -E "nccl|not found" | tr -s " " | tr "\n" ";")"; done'
LDD=${LDD//__B__/$B}
{
  echo "== $(date '+%F %T') deploy (rain) rs_set=$RS_SET"; echo "$L"
  echo "== sunny"; echo "$S"
  [ "$L" = "$S" ] && echo "new files: rain == sunny" || echo "NEW FILES MD5 MISMATCH"
  for a in "${SEL[@]}"; do
    IFS='|' read -r want src dir fn lib <<< "$a"
    [ "$(md5 "$src")" = "$(md5 "$HOME/$dir/$fn")" ] && echo "source == deployed: $dir/$fn ($want)" || echo "SOURCE MISMATCH: $dir/$fn"
  done
  echo "rain ldd:"; bash -c "$LDD"; echo "sunny ldd:"; ssh -n "$SUNNY_SSH" "$LDD"
  [ "$BEFORE_L" = "$AFTER_L" ] && [ "$BEFORE_S" = "$AFTER_S" ] &&
    echo "existing files unchanged (rain $(echo "$BEFORE_L" | grep -c .) files, sunny $(echo "$BEFORE_S" | grep -c .) files; the new directories left out)" ||
    echo "EXISTING FILE CHANGED"
} > "$OUTF"
