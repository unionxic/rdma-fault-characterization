#!/usr/bin/env bash
# deploy_rs.sh <check output file> - put gin-restore work package 10's files on rain and sunny (MAIN SESSION only), in the
# deploy_feas.sh style: NEW directories under ~/rs-bundle only (nothing is written into ~/gi-bundle, ~/gd-bundle or
# ~/blind-bundle: 9.15.1), never overwriting a file; a read-only md5 of every existing file of those bundles and of the rest
# of ~/rs-bundle on both nodes before and after (the new directories are left out of that comparison); md5 of every new
# file on both nodes against its source; ldd of the programs. ssh, scp and rsync on the management network only; no GPU
# program, no RDMA traffic.
#   ~/rs-bundle/lib/rs/      the restore research libnccl (+ .so.2, .so links)   source RS_LIB_SRC,  md5 WANT_RS
#   ~/rs-bundle/lib/rsp/     the restore production libnccl (+ links)            source RSP_LIB_SRC, md5 WANT_RSP
#   ~/rs-bundle/rstest/      gin_rs (macro), gin_rs_nomacro, gin_rs_hk (control) out/<RSTOUT>/, md5 WANT_GINRS,
#                                                                                  WANT_GINRS_NOMACRO, WANT_GINRS_HK
#   ~/rs-bundle/rscost/      gin_ts2 (macro) and gin_ts2_ff (cost drivers)       out/cost/,     md5 WANT_COST, WANT_COST_FF
#   ~/rs-bundle/mr/ff/, mr/hold/   gin_mr against this layer's headers          out/mr/,       md5 WANT_MR_FF, WANT_MR_HOLD
#   ~/rs-bundle/lib/hkp/     gpu-detect's production libnccl (hkp, + links)       source HKP_LIB_SRC, md5 WANT_HKP
#                            (2026-10-13: the cost family's ffb-hk arm; ~/gi-bundle/gin_ts2/hkp was never deployed and
#                            nothing may be written into ~/gi-bundle, 9.15.1)
# RS_SET (2026-10-13; empty: the paths above): a second deployment set beside the first, without touching it: every target
# above moves to ~/rs-bundle/<RS_SET>/ (lib/rs, lib/rsp, lib/hkp, rstest, rscost, mr/ff, mr/hold); the runners take the
# same RS_SET (run_rs.sh, run_cost.sh, cells_rs.sh, hold_rs.sh, chain_rs.sh).
# An artifact is deployed only when its WANT_* is set, and then its source must exist and match (else the script refuses
# before touching anything). Refuses if a target directory exists on either node. The libraries are the INTEGRATED restore
# build (work packages 5-9): RS_LIB_SRC and RSP_LIB_SRC name its libnccl.so.2.32.3 (the main session's integration folder).
# Every file that existed before in ~/gi-bundle, ~/gd-bundle, ~/blind-bundle and ~/rs-bundle (the first set included) is
# md5-compared before and after on both nodes; only the new target directories are left out.
# env: SUNNY_SSH (required), the WANT_* above, RS_LIB_SRC, RSP_LIB_SRC, HKP_LIB_SRC, RSTOUT (default rs), RS_SET
set -euo pipefail
OUTF=${1:?output file (the check is written to a file only; never pipe it)}
SUNNY_SSH=${SUNNY_SSH:?set SUNNY_SSH (user@address) from the management env file}
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
T=$SCR/agent_rs_int/test/out  # integration (2026-10-12): the drivers built against the integrated headers
RSTOUT=${RSTOUT:-rs}
RS_SET=${RS_SET:-}
case "$RS_SET" in */*|*..*|-*|.*) echo "RS_SET must be a plain name" >&2; exit 1 ;; esac
case "$RS_SET" in lib|rstest|rscost|mr|ord) echo "RS_SET may not be a name the first set uses ($RS_SET)" >&2; exit 1 ;; esac
B=rs-bundle${RS_SET:+/$RS_SET}   # the set's folder, relative to $HOME
md5() { md5sum < "$1" | cut -c1-32; }
# artifact table: <WANT var>|<source>|<target dir relative to $HOME>|<file name>|<lib: 1 = add .so.2/.so links>
ART=(
  "WANT_RS|${RS_LIB_SRC:-}|$B/lib/rs|libnccl.so.2.32.3|1"
  "WANT_RSP|${RSP_LIB_SRC:-}|$B/lib/rsp|libnccl.so.2.32.3|1"
  "WANT_HKP|${HKP_LIB_SRC:-}|$B/lib/hkp|libnccl.so.2.32.3|1"
  "WANT_GINRS|$T/$RSTOUT/gin_rs|$B/rstest|gin_rs|0"
  "WANT_GINRS_NOMACRO|$T/$RSTOUT/gin_rs_nomacro|$B/rstest|gin_rs_nomacro|0"
  "WANT_GINRS_HK|$T/$RSTOUT/gin_rs_hk|$B/rstest|gin_rs_hk|0"
  "WANT_COST|$T/cost/gin_ts2|$B/rscost|gin_ts2|0"
  "WANT_COST_FF|$T/cost/gin_ts2_ff|$B/rscost|gin_ts2_ff|0"
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
# the existing files that must not change, with the new target directories left out
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
# ldd of the programs against their libraries (HOME/...: a path under $HOME; else under the set's folder)
LDD='cd $HOME/__B__ && for p in rstest/gin_rs:lib/rs rstest/gin_rs_nomacro:lib/rs rstest/gin_rs_hk:HOME/gi-bundle/gin_ts2/hk rscost/gin_ts2:lib/rsp rscost/gin_ts2_ff:lib/rsp mr/ff/gin_mr:lib/rs mr/hold/gin_mr:lib/rs; do b=${p%%:*}; l=${p#*:}; case $l in HOME/*) l=$HOME/${l#HOME/} ;; *) l=$HOME/__B__/$l ;; esac; [ -f "$b" ] && echo "$b: $(LD_LIBRARY_PATH=$l ldd $b | grep -E "nccl|not found" | tr -s " " | tr "\n" ";")"; done'
LDD=${LDD//__B__/$B}
{
  echo "== $(date '+%F %T') deploy (rain)"; echo "$L"
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
