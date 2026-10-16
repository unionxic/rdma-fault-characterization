#!/usr/bin/env bash
# deploy_gc.sh <check output file> - put gin-control's test-side files on rain and sunny (MAIN SESSION only), in gin-mirror's
# deploy_mi.sh style (copied and then changed): NEW directories under ~/rs-bundle/<RS_SET>/ only (nothing is written into
# ~/gi-bundle, ~/gd-bundle or ~/blind-bundle, nor into a gin-restore or gin-mirror set); never overwriting a file; a read-only
# md5 of every existing file of those bundles before and after on both nodes (the new directories left out); md5 of every
# new file on both nodes against its source; ldd of the programs. ssh, scp and rsync on the management network only, to the
# node named by SUNNY_SSH (the variable the mirror scripts read; its value is never printed or written by this script); no
# GPU program, no RDMA traffic, no launcher started. RS_SET is required and must be a set of its own.
#   ~/rs-bundle/<RS_SET>/lib/gc/    the research libnccl, rdma control (+ .so.2, .so links)     source GC_LIB_SRC,   md5 WANT_GC
#   ~/rs-bundle/<RS_SET>/lib/gct/   NCCL_GIN_CTRL_TCP=1 (the tcp regression arm)               source GCT_LIB_SRC,  md5 WANT_GCT
#   ~/rs-bundle/<RS_SET>/lib/gctc/  + NCCL_GIN_CTRL_TCP_CELLS=1 (the tcp control cells only)   source GCTC_LIB_SRC, md5 WANT_GCTC
#   ~/rs-bundle/<RS_SET>/lib/gcp/   gc + NCCL_GIN_TS_PRODUCTION (cost)                         source GCP_LIB_SRC,  md5 WANT_GCP
#   ~/rs-bundle/<RS_SET>/lib/gctp/  gct + NCCL_GIN_TS_PRODUCTION (cost)                        source GCTP_LIB_SRC, md5 WANT_GCTP
#   ~/rs-bundle/<RS_SET>/gctest/    gin_mi, gin_mi_nomacro, gin_ts2_mi (built against the gc tree's headers; DRV_DIR/<name>),
#                                   gin_launcher (LAUNCHER_SRC)  md5 WANT_GINMI, WANT_GINMI_NOMACRO, WANT_COST, WANT_LAUNCHER
#   ~/rs-bundle/<RS_SET>/mr/ff/, mr/hold/   gin_mr against the gc tree's headers (DRV_DIR/mr/<ff|hold>/gin_mr)
#                                   md5 WANT_MR_FF, WANT_MR_HOLD
# An artifact is deployed only when its WANT_* is set, and then its source must exist and match (else the script refuses
# before touching anything). Refuses if a target directory exists on either node. The libraries are build_gc.sh's outputs
# ($SCR/agent_gc_<BR>/out/<key>_<BR>/libnccl.so.2.32.3; TODO(phase4): build_gc.sh has no gctc library stage yet, only its
# preprocessed check), the launcher build_launcher.sh's ($OUT/gin_launcher, built with verbs), the drivers the gc tree's
# test build (TODO: gin-mirror's build_mi_test.sh accepts only its own trees; a gc copy is not part of this delivery).
# env: SUNNY_SSH (required), RS_SET (required), the WANT_* and *_SRC above, DRV_DIR (the drivers' folder)
set -euo pipefail
OUTF=${1:?output file (the check is written to a file only; never pipe it)}
SUNNY_SSH=${SUNNY_SSH:?set SUNNY_SSH (user@address) from the management env file}
RS_SET=${RS_SET:-}
# shellcheck source=../../../mirror/impl/test/rs_set_mi.sh
. "$(cd "$(dirname "$0")" && pwd)/../../../mirror/impl/test/rs_set_mi.sh"
rs_set_check || exit 1
DRV_DIR=${DRV_DIR:-}
B=rs-bundle/$RS_SET   # the set's folder, relative to $HOME
ssh -n -o LogLevel=ERROR "$SUNNY_SSH" true 2>/dev/null || { echo "sunny does not answer over ssh: nothing deployed" >&2; exit 1; }
md5() { md5sum < "$1" | cut -c1-32; }
# artifact table: <WANT var>|<source>|<target dir relative to $HOME>|<file name>|<lib: 1 = add .so.2/.so links>
ART=(
  "WANT_GC|${GC_LIB_SRC:-}|$B/lib/gc|libnccl.so.2.32.3|1"
  "WANT_GCT|${GCT_LIB_SRC:-}|$B/lib/gct|libnccl.so.2.32.3|1"
  "WANT_GCTC|${GCTC_LIB_SRC:-}|$B/lib/gctc|libnccl.so.2.32.3|1"
  "WANT_GCP|${GCP_LIB_SRC:-}|$B/lib/gcp|libnccl.so.2.32.3|1"
  "WANT_GCTP|${GCTP_LIB_SRC:-}|$B/lib/gctp|libnccl.so.2.32.3|1"
  "WANT_GINMI|$DRV_DIR/gin_mi|$B/gctest|gin_mi|0"
  "WANT_GINMI_NOMACRO|$DRV_DIR/gin_mi_nomacro|$B/gctest|gin_mi_nomacro|0"
  "WANT_COST|$DRV_DIR/gin_ts2_mi|$B/gctest|gin_ts2_mi|0"
  "WANT_LAUNCHER|${LAUNCHER_SRC:-}|$B/gctest|gin_launcher|0"
  "WANT_MR_FF|$DRV_DIR/mr/ff/gin_mr|$B/mr/ff|gin_mr|0"
  "WANT_MR_HOLD|$DRV_DIR/mr/hold/gin_mr|$B/mr/hold|gin_mr|0"
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
# a gin-restore set (lib/rs, lib/rsp, rstest, rscost) or a gin-mirror set (lib/mi, lib/mip, mitest) is not reused
for g in lib/rs lib/rsp rstest rscost lib/mi lib/mip mitest; do
  if [ -e "$HOME/$B/$g" ] || ssh -n "$SUNNY_SSH" "[ -e \$HOME/$B/$g ]"; then echo "~/$B is another study's set ($g): use a new RS_SET" >&2; exit 1; fi
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
LDD='cd $HOME/__B__ && for p in gctest/gin_mi:lib/gc gctest/gin_mi_nomacro:lib/gc gctest/gin_ts2_mi:lib/gcp mr/ff/gin_mr:lib/gc mr/hold/gin_mr:lib/gc gctest/gin_launcher:-; do b=${p%%:*}; l=${p#*:}; [ "$l" = - ] && l= || l=$HOME/__B__/$l; [ -f "$b" ] && echo "$b: $(LD_LIBRARY_PATH=$l ldd $b | grep -E "nccl|ibverbs|not found" | tr -s " " | tr "\n" ";")"; done'
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
