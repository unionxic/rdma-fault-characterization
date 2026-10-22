#!/usr/bin/env bash
# build_gc.sh - build gin-control's control layer (EXPERIMENT.md 9.8) in a NEW scratch tree per work package, on top of
# gin-mirror's final layer (build ln4: ../../mirror/impl/mi_layer.diff, md5 dcd30859). Modeled on ../../mirror/impl/build_mi.sh
# (the same stage semantics). No GPU or RDMA program runs here: the libraries are compiled and linked, the CPU unit tests
# run on the CPU with ASan and UBSan (no NCCL, no CUDA, no verbs at run time), the identity checks compile and compare.
# Nothing outside agent_gc_$BR/ is written but impl/gc_layer*.diff in this worktree. agent_mi_fix/ (ln4) is read only.
# The keys of the work packages after int (their scratch scripts folded in, impl/notes_int2.md): p2b (phase 2b, agent_gc_p2b/),
# p2a2 (phase 2a-2 on "gin-control + 2b (gc_layer_p2b.diff fa3f1b48)", agent_gc_p2a2/, inputs pinned in its pin/), fix3
# (the watch-thread fix on the same commit, agent_gc_fix3/), p3 (phase 3, agent_gc_p3/, inputs in its pin/ and testpin/),
# int2 (their integration in place in agent_gc_p2a2/: head commit "gin-control 2a-2-B + fix3 + p3 (gc_layer_p3.diff
# c755b1df)", the glue in the working tree; inputs and tests this folder; impl/gc_layer_int.diff is the whole layer on ln4).
# usage: SCR=<the session scratch dir> BR=<prep|page|ring|launcher|int|p1|p2|p2b|p2a2|fix3|p3|int2> build_gc.sh
#          <setup|paste|repaste|api|gc|gcp|gct|gctp|unit|unitp1|unitp2|unitp2b|unitp2a2|unitp3|syn|pre|sites|ident|diff|info>
#   prep, the preparation stage (9.8 "준비"); page, ring, launcher: phases 1, 2, 3 (they start from ln4 + the preparation
#   stage's diff); int: their integration (phase 4 binds the rest of the TCP code behind the switch). int's tree holds
#   the fixed preparation stage (impl/gc_layer.diff 0df79ae2, head commit "gin-control prep-fix (gc_layer.diff 0df79ae2)")
#   with phase 1 (impl/gc_layer_p1.diff) and phase 2a-1 (impl/gc_layer_p2.diff) merged onto it: impl/gc_layer_int.diff.
#   p1, p2: the record of phase 1 and phase 2a-1 as they were built (their trees agent_gc_p1, agent_gc_p2 on the old
#   preparation stage f5061a31; inputs pinned in GCPIN, default impl_base/ and agent_gc_p2/pin/; test sources GCTEST,
#   default this folder: the tests here follow the fixed header since the integration, so the phase-time sources are
#   `git show 73be8802:` (p1) and `494cd666:` (p2) of the worktree).
#   setup  once: check that agent_mi_fix is gin-mirror's ln4 (head commit "gin-restore i5 (rs_layer.diff f005bb67)",
#          working tree diff md5 dcd30859 = ../../mirror/impl/mi_layer.diff, build/lib libnccl c74e6ffb, build-mip/lib
#          21b0be95), copy its nccl-src to agent_gc_$BR/nccl-src, its build to build (key gc) and build-gct (key gct), its
#          build-mip to build-gcp (gcp) and build-gctp (gctp), rewrite the absolute paths in the dependency files and
#          device manifests (mtimes kept), and commit ln4's working tree in the copy as "gin-mirror ln4 (mi_layer.diff
#          dcd30859)" (history: ..., hk, i5, ln4); check that commit's diff is mi_layer.diff byte for byte and the copied
#          libraries are ln4's. BR other than prep: then apply impl/gc_layer.diff (md5 PREP_MD5 below) and commit it as
#          "gin-control prep (gc_layer.diff <md5>)" (not run yet: the phases' agents run it first).
#   paste  once, BR=prep's first change: paste impl/rs_ctrl_api.h's two blocks ("gin-control: ctrl API", "gin-control:
#          ctrl seams") right after the end of the block "gin-mirror: store API" of the host file. Refused when the tree
#          already has a gin-control block.
#   repaste replace the tree's two pasted blocks by the header's (after the header changed), byte for byte; any BR (a
#          phase edits only its own "[n]" sub-blocks of the header, then repastes; api checks the result).
#   api    the pasted blocks are the header's, byte for byte; the header compiles standalone (g++ -fsyntax-only) with and
#          without NCCL_GIN_CTRL_TCP=1, with and without its entry-point declarations, with gin-mirror's seven headers.
#   gc     the default build (rdma, research) into agent_gc_$BR/build -> out/$GCOUT (default gc_$BR);
#   gcp    the same source with -DNCCL_GIN_TS_PRODUCTION into build-gcp -> out/$GCPOUT (gcp_$BR);
#   gct    the regression arm, -DNCCL_GIN_CTRL_TCP=1, into build-gct -> out/$GCTOUT (gct_$BR);
#   gctp   both defines into build-gctp -> out/$GCTPOUT (gctp_$BR). A folder that already holds a build is refused.
#          All four: the working tree must change only GC_FILES; the device objects are rebuilt only when the device header
#          trees differ from that directory's last build (devsync, build_mi.sh's rule).
#   unit   CFG=<rdma|tcp|both> (default both): gin-mirror's CPU unit tests (../../mirror/impl/mi_unit_{dev,host,store,
#          spare,lineage}.cc) and gin-restore's (../../restore/impl/rs_unit_host.cc, rs_spare_unit.cc) unchanged, against
#          the working tree's pure regions, then impl/gc_unit_prep.cc; BR p1 and int: then impl/gc_unit_p1.cc (both builds;
#          tcp: no phase 1, 0 checks) and impl/gate_fenced.cc (rdma only: the tcp build has no FENCED gate); BR p2 and
#          int: then impl/gc_unit_p2.cc (both builds; tcp: 0 checks); g++ with ASan and UBSan, with -DNCCL_GIN_CTRL_TCP=1
#          for tcp. No NCCL, no CUDA, no network.
#   unitp1, unitp2  the development loop: phase 1's tests alone (BR p1, int), phase 2a-1's alone (BR p2, int).
#   syn    the host file's compile command of build, build-gcp and build-gct with -fsyntax-only (the development loop).
#   pre    the preprocessed host file (g++ -E -P with the build's own flags) of gct, gctp and gctc (gct's flags with
#          NCCL_GIN_CTRL_TCP_CELLS=1) against ln4's (gctp: its production flags), as is and with the tree's path in the
#          __FILE__ strings and the host file's __LINE__ numbers normalized; gc's for the record; out/pre/.
#   sites  the swap points: impl/gc_sites.tsv (every site's class and action) against ln4's lines and the working tree's
#          rdma side (the code outside the pasted blocks and the preparation region, without the #if NCCL_GIN_CTRL_TCP
#          branches): the counts of every swap point, seam and kept call, the .fd uses left; and every
#          #if NCCL_GIN_CTRL_TCP branch outside the blocks is a run of ln4's lines verbatim. The phases' own regions
#          ("gin-control (page)", "(ring)": new code, no ln4 site) are outside that count; their uses of the same calls
#          are the table's "#use" lines (region, call, count), checked against the tree too.
#   ident  the device identity against ln4 (EXPERIMENT.md 9.8 "동일성 확인"): the four macro-free programs (gin-restore's
#          ff_ops.cu, gin_ts2.cu, gin_mr.cu, NCCL's ring example) compiled against each build's installed headers, without
#          and with NCCL_GIN_RESTORE_DEVICE, against ln4's objects (agent_mi_fix/sass_mi_ln4): whole SASS and -res-usage;
#          every device object of the four build directories against ln4's build (gc, gct) and build-mip (gcp, gctp); the
#          libraries' -res-usage against ln4's. Output out/ident_$IDTAG/.
#   diff   write impl/gc_layer.diff (BR=prep; others impl/gc_layer_$BR.diff): the working tree against the head commit;
#          int: impl/gc_layer_int.diff, the whole layer against the ln4 commit (prep-fix + phase 1 + phase 2a-1)
#          (histogram, new files as intent-to-add), and check that it applies in reverse.
#   info   out/build_info.txt (INFO=<file> for another name): md5 of every output and input, the base.
# All compiles run at nice 19 and idle I/O priority (other studies use this node).
set -euo pipefail
STAGE=${1:?stage}
BR=${BR:?BR=<prep|page|ring|launcher|int|p1|p2|p2b|p2a2|fix3|p3|int2>}
case "$BR" in prep | page | ring | launcher | int | p1 | p2 | p2b | p2a2 | fix3 | p3 | int2) ;; *) echo "unknown work package $BR" >&2; exit 2 ;; esac
SCR=${SCR:?SCR=<the session scratch dir that holds agent_mi_fix and agent_gc_*>}
D=${GCIMPL:-$(cd "$(dirname "$0")" && pwd)}  # this worktree's control/impl (GCIMPL: when a scratch copy of this script runs)
# DI: the header, the site table and gc_unit_prep.cc the stages read (this folder; p1, p2: the inputs they were built
# with, pinned); TI: the phases' test sources (this folder unless GCTEST says otherwise)
case "$BR" in
  p1) DI=${GCPIN:-$SCR/impl_base} ;;
  p2) DI=${GCPIN:-$SCR/agent_gc_p2/pin} ;;
  p2b) DI=${GCPIN:-$D} ;;  # p2b: GCPIN=agent_gc_p2b/pin, the worktree HEAD's inputs (others edit the worktree meanwhile)
  p2a2) DI=${GCPIN:-$SCR/agent_gc_p2a2/pin} ;;  # the worktree HEAD a5f7ef0b's inputs, the header with rs_ctrl_api_p2b.diff (and p2a2's)
  fix3) DI=${GCPIN:-$SCR/agent_gc_fix3/pin} ;;  # the header = the committed header + rs_ctrl_api_p2b.diff
  p3) DI=${GCPIN:-$SCR/agent_gc_p3/pin} ;;  # the worktree HEAD's inputs with rs_ctrl_api_p2b.diff and _p3.diff applied
  *) DI=$D ;;  # int2: this folder (the merged header, the site table, launcher/ at its commit)
esac
TI=${GCTEST:-$D}
{ [ "$BR" = p2a2 ] || [ "$BR" = fix3 ]; } && TI=${GCTEST:-$DI}  # the tests of HEAD a5f7ef0b and gc_unit_p2a2.cc, pinned beside the inputs
[ "$BR" = p3 ] && TI=${GCTEST:-$SCR/agent_gc_p3/testpin}  # p3: the worktree HEAD's tests and gc_unit_p3.cc
MID=$(cd "$D/../../mirror/impl" && pwd)   # gin-mirror's impl (read only)
RSD=$(cd "$D/../../restore/impl" && pwd)  # gin-restore's impl (read only)
CUDA=/usr/local/cuda-12.8
GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86"
JOBS=${JOBS:-8}
GCOUT=${GCOUT:-gc_$BR}
GCPOUT=${GCPOUT:-gcp_$BR}
GCTOUT=${GCTOUT:-gct_$BR}
GCTPOUT=${GCTPOUT:-gctp_$BR}
IDTAG=${IDTAG:-$BR}
LAYER=$D/gc_layer_$BR.diff
[ "$BR" != prep ] || LAYER=$D/gc_layer.diff
[ "$BR" != int2 ] || LAYER=$D/gc_layer_int.diff  # int2: the whole layer on ln4 (as int)
INFO=${INFO:-}
LN4=$SCR/agent_mi_fix  # gin-mirror's tree, build ln4 (read only)
W=$SCR/agent_gc_$BR
[ "$BR" != int2 ] || W=$SCR/agent_gc_p2a2  # int2 works in place in 2a-2's tree (no copy: the disk is tight)
OUT=$W/out
HOSTF=src/transport/net_ib/gdaki/gin_host_gdaki.cc
GC_FILES="$HOSTF"      # files the control layer may change (device code: 0 lines, EXPERIMENT.md 9.8)
LN4_SUBJECT="gin-mirror ln4 (mi_layer.diff dcd30859)"
I5_SUBJECT="gin-restore i5 (rs_layer.diff f005bb67)"
LN4_DIFF=dcd30859ac6db214e37475c527c37e2f
LN4_HOST=0ab4e636fb19ec5c5a6759edf3ea2d40
LN4_LIB=c74e6ffb60b9ab8e959a7cfc89b7f55c
LN4_LIBP=21b0be95b04f4ebeeafd0e6e92eecba0
case "$BR" in  # impl/gc_layer.diff's md5 the phases start from (the main session pins it with the prep commit)
  int) PREP_MD5=${PREP_MD5:-0df79ae2c8b3a285383a48adbbf5ebad} ;;  # the fixed preparation stage (fd4ae2d6)
  p1 | p2) PREP_MD5=${PREP_MD5:-f5061a31bf8760ad4cbb3b607fa5d19a} ;;  # the preparation stage phases 1 and 2a-1 began on
  *) PREP_MD5=${PREP_MD5:-} ;;
esac
PREP_SUBJECT() { [ "$BR" = int ] && echo "gin-control prep-fix (gc_layer.diff ${PREP_MD5:0:8})" ||
                   echo "gin-control prep (gc_layer.diff ${PREP_MD5:0:8})"; }
LG() { git -C "$LN4/nccl-src" "$@"; }
MG() { git -C "$W/nccl-src" -c user.name=build -c user.email=build@localhost "$@"; }
md5() { md5sum < "$1" | cut -c1-32; }
MKS() {  # MKS <builddir> [make args]
  local b=$1; shift
  nice -n 19 ionice -c3 make -j"$JOBS" -C "$W/nccl-src" src.build BUILDDIR="$b" CUDA_HOME=$CUDA NVCC_GENCODE="$GENCODE" "$@"
}
rewrite() {  # rewrite <from prefix> <to prefix> <dir>: absolute paths in *.d and manifests, mtimes kept
  local from=$1 to=$2 dir=$3
  (cd "$dir" && find . \( -name '*.d' -o -name manifest \) -print0 |
     while IFS= read -r -d '' f; do
       local t; t=$(mktemp); touch -r "$f" "$t"
       sed -i "s#$from#$to#g" "$f"; touch -h -r "$t" "$f"; rm -f "$t"
     done)
}

setup() {
  [ -d "$W/nccl-src" ] && { echo "agent_gc_$BR already set up" >&2; return 0; }
  [ "$(md5 "$MID/mi_layer.diff")" = $LN4_DIFF ] || { echo "mirror/impl/mi_layer.diff is not dcd30859" >&2; exit 1; }
  [ "$(LG log -1 --format=%s)" = "$I5_SUBJECT" ] || { echo "agent_mi_fix head is not i5" >&2; exit 1; }
  [ "$(LG diff --diff-algorithm=histogram HEAD -- src | md5sum | cut -c1-32)" = $LN4_DIFF ] ||
    { echo "agent_mi_fix's working tree is not mi_layer.diff (ln4)" >&2; exit 1; }
  [ "$(md5 "$LN4/nccl-src/$HOSTF")" = $LN4_HOST ] || { echo "agent_mi_fix's host file is not ln4's" >&2; exit 1; }
  [ "$(md5 "$LN4/build/lib/libnccl.so.2.32.3")" = $LN4_LIB ] || { echo "agent_mi_fix/build is not ln4" >&2; exit 1; }
  [ "$(md5 "$LN4/build-mip/lib/libnccl.so.2.32.3")" = $LN4_LIBP ] || { echo "agent_mi_fix/build-mip is not ln4" >&2; exit 1; }
  if [ "$BR" != prep ]; then
    [ -n "$PREP_MD5" ] && [ -f "$DI/gc_layer.diff" ] && [ "$(md5 "$DI/gc_layer.diff")" = "$PREP_MD5" ] ||
      { echo "gc_layer.diff ($DI) is not the pinned preparation stage (PREP_MD5)" >&2; exit 1; }
  fi
  mkdir -p "$W"
  cp -a "$LN4/nccl-src" "$W/"
  cp -a "$LN4/build" "$W/build"
  cp -a "$LN4/build" "$W/build-gct"
  cp -a "$LN4/build-mip" "$W/build-gcp"
  cp -a "$LN4/build-mip" "$W/build-gctp"
  rm -rf "$W/nccl-src/.git/worktrees"
  rewrite "$LN4/build-mip/" "$W/build-gcp/" "$W/build-gcp"
  rewrite "$LN4/build-mip/" "$W/build-gctp/" "$W/build-gctp"
  rewrite "$LN4/build/" "$W/build-gct/" "$W/build-gct"
  local b
  for b in build build-gct build-gcp build-gctp; do rewrite "$LN4/" "$W/" "$W/$b"; done
  MG add -A src
  MG commit -qm "$LN4_SUBJECT"
  [ "$(MG diff --diff-algorithm=histogram HEAD~1 HEAD -- src | md5sum | cut -c1-32)" = $LN4_DIFF ] ||
    { echo "the ln4 commit is not mi_layer.diff" >&2; exit 1; }
  for b in build build-gct; do
    [ "$(md5 "$W/$b/lib/libnccl.so.2.32.3")" = $LN4_LIB ] || { echo "the copied $b is not ln4" >&2; exit 1; }
  done
  for b in build-gcp build-gctp; do
    [ "$(md5 "$W/$b/lib/libnccl.so.2.32.3")" = $LN4_LIBP ] || { echo "the copied $b is not ln4's production" >&2; exit 1; }
  done
  if [ "$BR" != prep ]; then
    MG apply "$DI/gc_layer.diff"
    MG add -A src
    MG commit -qm "$(PREP_SUBJECT)"
  fi
  echo "setup: agent_gc_$BR at $(MG rev-parse --short HEAD) ($(MG log -1 --format=%s)); base libnccl ln4 ${LN4_LIB:0:8} / ${LN4_LIBP:0:8}"
}
# INT_BASE (BR=int only): the head commit's subject when a fix pass committed the integration first (the fix of
# REVIEW_P12: "gin-control int (gc_layer_int.diff a7600a46)"); default the prep-fix commit
P2A2_BASE="gin-control + 2b (gc_layer_p2b.diff fa3f1b48)"  # p2a2's, fix3's and p3's base commit (int+fix12, then phase 2b)
P2A2_SUBJECT="gin-control 2a-2-A (gc_layer_p2a2.diff 1eb219f2)"  # p2a2's head commit (2a-2-A committed on the header draft; B works in the tree)
INT_SUBJECT="gin-control int (gc_layer_int.diff a7600a46)"  # p2b's head commit (agent_gc_int's working tree, committed)
P3F_SUBJECT="gin-control p3 (gc_layer_p3.diff cca4bb18)"  # p3's head commit (the fix pass of REVIEW_P3 committed phase 3 first)
INT2_SUBJECT="gin-control 2a-2-B + fix3 + p3 (gc_layer_p3.diff c755b1df)"  # int2's head commit (the three merged; the glue in the tree)
BASE_SUBJECT() { case "$BR" in int2) echo "$INT2_SUBJECT"; return ;; p3) echo "$P3F_SUBJECT"; return ;; p2b) echo "$INT_SUBJECT"; return ;;
                   fix3) echo "$P2A2_BASE"; return ;; p2a2) echo "$P2A2_SUBJECT"; return ;; esac; [ "$BR" = prep ] && echo "$LN4_SUBJECT" || { [ "$BR" = int ] && [ -n "${INT_BASE:-}" ] && echo "$INT_BASE"; } || PREP_SUBJECT; }
head_ok() {
  [ "$(MG log -1 --format=%s)" = "$(BASE_SUBJECT)" ] || { echo "unexpected head commit in agent_gc_$BR" >&2; exit 1; }
}
files_ok() {  # the working tree changes GC_FILES only
  local f
  for f in $(MG diff --name-only HEAD -- src); do
    case " $GC_FILES " in *" $f "*) ;; *) echo "the working tree changes $f, which is not in GC_FILES" >&2; exit 1 ;; esac
  done
}
tree() {  # the work package's diff on the working tree of the copy
  head_ok
  if MG diff --quiet HEAD -- src; then
    [ -f "$LAYER" ] || { echo "no changes in the tree and no impl/$(basename "$LAYER")" >&2; exit 1; }
    [ "$BR" = int ] && [ -n "${INT_BASE:-}" ] && { echo "tree: INT_BASE is set and the tree is clean: nothing to apply" >&2; exit 1; }
    [ "$BR" = int2 ] && { echo "tree: int2's glue is the working tree and the tree is clean: nothing to build" >&2; exit 1; }
    [ "$BR" = int ] && MG apply -R "$DI/gc_layer.diff"  # int's layer is on ln4: the head commit's prep-fix out first
    MG apply "$LAYER"
  fi
  files_ok
}

# ---- paste: the two blocks of impl/rs_ctrl_api.h, once, after the store API block ----
paste() {
  [ "$BR" = prep ] || { echo "paste is the preparation stage's (the phases start from its commit)" >&2; exit 1; }
  head_ok
  python3 - "$W/nccl-src" "$D" <<'PY'
import sys
root, impl = sys.argv[1], sys.argv[2]
HOSTF = root + '/src/transport/net_ib/gdaki/gin_host_gdaki.cc'
L = open(impl + '/rs_ctrl_api.h', encoding='utf-8').read().split('\n')
def block(begin, end):
    a = [i for i, l in enumerate(L) if l.startswith(begin)]
    b = [i for i, l in enumerate(L) if l.startswith(end)]
    if len(a) != 1 or len(b) != 1 or b[0] < a[0]: sys.exit('no block %r in rs_ctrl_api.h' % begin)
    return L[a[0]:b[0] + 1]
API = block('// ---- gin-control: ctrl API (begin', '// ---- gin-control: ctrl API (end')
SEAM = block('// ---- gin-control: ctrl seams (begin', '// ---- gin-control: ctrl seams (end')
H = open(HOSTF, encoding='utf-8').read().split('\n')
if any('gin-control:' in l for l in H): sys.exit('the tree already has a gin-control block: use api')
e = [i for i, l in enumerate(H) if l == '// ---- gin-mirror: store API (end) ----']
if len(e) != 1: sys.exit('the store API block end: %d matches, want 1' % len(e))
H[e[0] + 1:e[0] + 1] = API + SEAM
open(HOSTF, 'w', encoding='utf-8').write('\n'.join(H))
print('paste: ctrl API %d lines, ctrl seams %d lines after the store API block' % (len(API), len(SEAM)))
PY
  files_ok
}

repaste() {  # the header's two blocks over the tree's (each phase changes only its own sub-blocks in them)
  head_ok
  python3 - "$W/nccl-src" "$DI" <<'PY'
import sys
root, impl = sys.argv[1], sys.argv[2]
HOSTF = root + '/src/transport/net_ib/gdaki/gin_host_gdaki.cc'
def block(L, begin, end, what):
    a = [i for i, l in enumerate(L) if l.startswith(begin)]
    b = [i for i, l in enumerate(L) if l.startswith(end)]
    if len(a) != 1 or len(b) != 1 or b[0] < a[0]: sys.exit('no block %r in %s' % (begin, what))
    return a[0], b[0]
L = open(impl + '/rs_ctrl_api.h', encoding='utf-8').read().split('\n')
H = open(HOSTF, encoding='utf-8').read().split('\n')
n = []
for begin, end in (('// ---- gin-control: ctrl seams (begin', '// ---- gin-control: ctrl seams (end'),
                   ('// ---- gin-control: ctrl API (begin', '// ---- gin-control: ctrl API (end')):
    a, b = block(L, begin, end, 'rs_ctrl_api.h')
    x, y = block(H, begin, end, 'the host file')
    H[x:y + 1] = L[a:b + 1]
    n.append(b + 1 - a)
open(HOSTF, 'w', encoding='utf-8').write('\n'.join(H))
print('repaste: ctrl seams %d lines, ctrl API %d lines' % (n[0], n[1]))
PY
  files_ok
}

region() {  # region <begin regex> <end regex> <file>
  awk -v b="$1" -v e="$2" '$0 ~ b {on=1} on {print} $0 ~ e {on=0}' "$3"
}
same() {  # same <what> <begin regex> <end regex> <tree file> <header>: the tree's block is the header's
  local a b
  a=$(region "$2" "$3" "$W/nccl-src/$4" | md5sum | cut -c1-32)
  b=$(region "$2" "$3" "$5" | md5sum | cut -c1-32)
  [ -n "$(region "$2" "$3" "$5")" ] || { echo "api: no $1 block in $(basename "$5")" >&2; exit 1; }
  [ "$a" = "$b" ] || { echo "api: the tree's $1 block differs from $(basename "$5") ($a vs $b)" >&2; exit 1; }
  echo "api: $1 = $(basename "$5") ($a)"
}
PRELUDE='#include <stddef.h>
#include <stdint.h>
typedef enum { ncclSuccess = 0, ncclSystemError = 2, ncclInternalError = 3, ncclInvalidUsage = 5 } ncclResult_t;
typedef struct {
  unsigned int magic, nqp, qpn[64], remoteQpn[64], sqPsn[64];
  unsigned long long epochWqes[64];
} ncclGinRecoverToken_t;'
api() {
  head_ok
  same "ctrl API" '^// ---- gin-control: ctrl API [(]begin' '^// ---- gin-control: ctrl API [(]end' "$HOSTF" "$DI/rs_ctrl_api.h"
  same "ctrl seams" '^// ---- gin-control: ctrl seams [(]begin' '^// ---- gin-control: ctrl seams [(]end' "$HOSTF" "$DI/rs_ctrl_api.h"
  if [ "$BR" = p3 ] || [ "$BR" = int2 ]; then  # the pasted launcher wire is launcher/launcher_msg.h byte for byte
    mkdir -p "$OUT"
    region '^// ---- gin-control: launcher wire [(]begin' '^// ---- gin-control: launcher wire [(]end' "$W/nccl-src/$HOSTF" | sed '1d;$d' > "$OUT/launcher_wire.h"
    cmp -s "$OUT/launcher_wire.h" "$DI/launcher/launcher_msg.h" ||
      { echo "api: the tree's launcher wire differs from launcher/launcher_msg.h" >&2; exit 1; }
    echo "api: launcher wire = launcher/launcher_msg.h ($(md5 "$DI/launcher/launcher_msg.h"), $(wc -l < "$DI/launcher/launcher_msg.h") lines)"
  fi
  local o=$OUT/api; mkdir -p "$o"
  { echo "$PRELUDE"
    for h in rs_hold_api.h rs_mirror_api.h rs_log_api.h rs_ckpt_api.h rs_store_api.h rs_spare_api.h rs_lineage_api.h; do
      echo "#include \"$h\""
    done
    echo '#include "rs_ctrl_api.h"'
    echo 'int main() { return 0; }'; } > "$o/headers.cc"
  local f
  for f in "" "-DNCCL_GIN_CTRL_TCP=1"; do
    g++ -std=c++17 -Wall -Wextra -Werror -Wno-unused-function $f -fsyntax-only -I"$DI" -I"$MID" "$o/headers.cc"
    g++ -std=c++17 -Wall -Wextra -Werror -Wno-unused-function $f -DGDAKI_MI_API_NO_ENTRY_DECLS -DGDAKI_HOLD_API_NO_ENTRY_DECLS \
      -DGDAKI_CTRL_API_NO_ENTRY_DECLS -fsyntax-only -I"$DI" -I"$MID" "$o/headers.cc"
  done
  if g++ -std=c++17 -DNCCL_GIN_CTRL_TCP_CELLS=1 -fsyntax-only -I"$DI" -I"$MID" "$o/headers.cc" 2> "$o/cells_alone.err"; then
    echo "api: NCCL_GIN_CTRL_TCP_CELLS=1 without NCCL_GIN_CTRL_TCP compiled; it must not" >&2; exit 1
  fi
  echo "api: NCCL_GIN_CTRL_TCP_CELLS=1 without NCCL_GIN_CTRL_TCP is refused ($(grep -c '#error' "$o/cells_alone.err") #error line)"
  echo "api: rs_ctrl_api.h compiles with gin-mirror's seven headers (g++ -fsyntax-only; rdma and tcp; with and without the" \
       "entry-point declarations); launcher/launcher_msg.h $( [ -f "$DI/launcher/launcher_msg.h" ] && echo "present: its envelope checked" || echo absent)"
}

NDEV=src/include/nccl_device
NDOCA=src/transport/net_ib/gdaki/doca-gpunetio/include
ndevDigest() { (cd "$W/nccl-src" && find "$NDEV" "$NDOCA" -type f | LC_ALL=C sort | xargs md5sum | md5sum | cut -c1-32); }
devsync() {
  local b=$1
  if [ "$(cat "$b/.rs_nccl_device_digest" 2>/dev/null)" != "$(ndevDigest)" ]; then
    echo "devsync: $NDEV or $NDOCA differs from the last build of $(basename "$b"): its device objects are rebuilt"
    rm -rf "$b/obj/device" "$b/obj/diagnostics/device"
  fi
}
devdone() { ndevDigest > "$1/.rs_nccl_device_digest"; }
fresh() {  # fresh <dir>: refuse a folder that already holds a build
  [ ! -e "$1/libnccl.so.2.32.3" ] || { echo "$1 already holds a build; give a new folder name" >&2; exit 1; }
  mkdir -p "$1"
}
lib() {  # lib <build dir> <out name> <extra CXXFLAGS>
  local b=$W/$1 n=$2 fl=$3
  tree; fresh "$OUT/$n"
  devsync "$b"
  CXXFLAGS="$fl" MKS "$b"
  devdone "$b"
  cp "$b/lib/libnccl.so.2.32.3" "$OUT/$n/"
  diff -r -q "$W/build/include" "$b/include" > /dev/null ||
    { echo "$1's installed headers differ from build's" >&2; exit 1; }
  echo "$n libnccl $(md5 "$OUT/$n/libnccl.so.2.32.3")"
}

cut1() {  # cut1 <out> <begin regex> <end regex>: a region of the host file, which must exist
  region "$2" "$3" "$W/nccl-src/$HOSTF" > "$1"
  [ -s "$1" ] || { echo "no region '$2' in $HOSTF" >&2; exit 1; }
}
GXX() { nice -n 19 g++ -std=c++17 -O1 -g -Wall -Wextra -Werror -Wno-unused-function -pthread -fsanitize=address,undefined "$@"; }
p2a2regions() {  # p2a2regions <dir>: what gc_unit_p2a2.cc compiles (filled in by phase 2a-2's steps)
  local o=$1
  # 2a-2-A: the setup's pure region, the liveness READ QP's pairing link and the verbs back end as they are, without the
  # back end's libibverbs lookups (the test's fake verbs stand there), and the host-state pieces they use, cut as they are
  cut1 "$o/gc_setup_pure.inc" '^// ==== gin-control [(]ring[)]: setup, pure [(]begin' '^// ==== gin-control [(]ring[)]: setup, pure [(]end'
  cut1 "$o/gc_ring_link.inc" "^// ==== gin-control [(]ring[)]: the liveness READ QP's pairing link [(]begin" \
       "^// ==== gin-control [(]ring[)]: the liveness READ QP's pairing link [(]end"
  # 2a-2-B: the live seams' region as it is, and the swap points' bodies of the "[2] ring" placeholders (the ones that
  # take the ring: gc_unit_p2a2.cc runs them over the fake verbs)
  cut1 "$o/gc_live.inc" '^// ==== gin-control [(]ring[)]: live seams [(]begin' '^// ==== gin-control [(]ring[)]: live seams [(]end'
  cutdefs "$W/nccl-src/$HOSTF" "$o/gc_seam_bodies.inc" 'static int gdakiCtrlSend(' 'static int gdakiCtrlPump(' \
    'static int gdakiCtrlRecv(' 'static int gdakiCtrlRecvOn(' 'static bool gdakiCtrlChanUp(' 'static uint32_t gdakiCtrlChanGen(' \
    'static int gdakiCtrlPollFd(' 'static void gdakiCtrlChanInstall('
  # the TCP branch's counters (before struct gdakiRecHost) and the helper socket's liveness pieces with their rdma lines
  cutdefs "$W/nccl-src/$HOSTF" "$o/gc_tcpcount.inc" '#define GDAKI_CTRL_TCP_COUNT_PEERS ' 'struct gdakiCtrlTcpCount {'
  cutdefs "$W/nccl-src/$HOSTF" "$o/gc_ts_live.inc" 'static int gdakiTsCauseLiveness(' 'static void gdakiTsMakeUnknown('
  python3 - "$W/nccl-src/$HOSTF" "$o" <<'PY4'
import sys
src, o = sys.argv[1], sys.argv[2]
L = open(src, encoding='utf-8').read().split('\n')
def one(prefix, end=None):
    h = [i for i, l in enumerate(L) if l.startswith(prefix)]
    h = [i for i in h if not (L[i].rstrip().endswith(';') and '{' not in L[i])]  # not a declaration
    if not h: sys.exit('cut: no %r' % prefix)
    i = h[0]
    if '{' in L[i] and L[i].rstrip().endswith('}'): return L[i:i + 1]
    k = i
    while L[k] != (end or ('};' if prefix.startswith('struct ') else '}')): k += 1
    return L[i:k + 1]
def region(b, e):
    a = [i for i, l in enumerate(L) if l.startswith(b)]
    z = [i for i, l in enumerate(L) if l.startswith(e)]
    if len(a) != 1 or len(z) != 1: sys.exit('cut: region %r' % b)
    return a[0], z[0]
a, z = region('// ==== gin-control (ring): verbs back end (begin', '// ==== gin-control (ring): verbs back end (end')
x, y = region('// ---- gin-control (ring): libibverbs lookups (begin', '// ---- gin-control (ring): libibverbs lookups (end')
assert a < x < y < z
be = ['// cut from %s (build_gc_p2a2.sh p2a2regions: the verbs back end without its libibverbs lookups)' % src]
be += L[a:x] + ['// (the libibverbs lookups: gc_unit_p2a2.cc\'s fake verbs)'] + L[y + 1:z + 1]
open(o + '/gc_ring_backend.inc', 'w', encoding='utf-8').write('\n'.join(be) + '\n')
hs = ['// cut from %s (build_gc_p2a2.sh p2a2regions: the host state the back end and the link read)' % src]
po = [i for i, l in enumerate(L) if l == '  GDAKI_CTRL_PO_NONE = 0,']
if len(po) != 1 or not L[po[0] - 1].startswith('enum : uint32_t {'): sys.exit('cut: the probe operations enum')
pa, pz = region('// ---- gin-control (page): pure functions (begin', '// ---- gin-control (page): pure functions (end')
if not pa < po[0] < pz:  # since the watch-thread fix (fix3) the enum is in the page's pure region (gc_page_pure.inc)
    k = po[0]
    while L[k] != '};': k += 1
    hs += L[po[0] - 1:k + 1]
for pfx in ('struct gdakiMiHostQp {', 'struct gdakiCtrlCq {', 'struct gdakiCtrlProbeReq {', 'struct gdakiCtrlProbeRes {',
            'struct gdakiCtrlPeerProbe {', 'struct gdakiCtrlPage {', 'static struct gdakiCtrlPage* gdakiPageOf(',
            'static bool gdakiPageUp(', 'static uint32_t gdakiCtrlProbeAsk(', 'static bool gdakiCtrlProbeAnswer(',
            'static uint32_t gdakiCtrlProbeErrTake('):
    hs += one(pfx)
open(o + '/gc_p2a2_host.inc', 'w', encoding='utf-8').write('\n'.join(hs) + '\n')
PY4
}
regions() {  # regions <dir>: every pure region the unit tests read
  local o=$1 x
  cut1 "$o/rs_pure.inc" '^// ---- gin-restore: pure functions [(]begin' '^// ---- gin-restore: pure functions [(]end'
  cut1 "$o/rs_dev_pure.inc" '^// ---- gin-restore [(]dev[)]: log, suppress and replay, pure [(]begin' \
       '^// ---- gin-restore [(]dev[)]: log, suppress and replay, pure [(]end'
  cut1 "$o/rs_hold_pure.inc" '^// ---- gin-restore hold: pure functions [(]begin' '^// ---- gin-restore hold: pure functions [(]end'
  cut1 "$o/rs_ckpt_pure.inc" '^// ---- gin-restore ckpt: pure functions [(]begin' '^// ---- gin-restore ckpt: pure functions [(]end'
  cut1 "$o/rs_spare_pure.inc" '^// ==== gin-restore [(]rs, work package 8, spare branch[)]: pure functions [(]begin' \
       '^// ==== gin-restore [(]rs, work package 8, spare branch[)]: pure functions [(]end'
  for x in dev host store spare lineage; do
    cut1 "$o/mi_pure_$x.inc" "^// ---- gin-mirror [(]$x[)]: pure [(]begin" "^// ---- gin-mirror [(]$x[)]: pure [(]end"
  done
  cut1 "$o/gc_api.inc" '^// ---- gin-control: ctrl API [(]begin' '^// ---- gin-control: ctrl API [(]end'
  case "$BR" in p1 | int | p2b | p2a2 | fix3 | p3 | int2)  # phase 1's region (impl/gc_unit_p1.cc, impl/gate_fenced.cc)
    cut1 "$o/gc_page_pure.inc" '^// ---- gin-control [(]page[)]: pure functions [(]begin' \
         '^// ---- gin-control [(]page[)]: pure functions [(]end' ;;
  esac
  case "$BR" in p2 | int | p2b | p2a2 | fix3 | p3 | int2)  # phase 2a-1's model (impl/gc_unit_p2.cc) and gc_unit_prep.cc's record generator
    cut1 "$o/gc_ring_model.inc" '^// ==== gin-control [(]ring[)]: model [(]begin' '^// ==== gin-control [(]ring[)]: model [(]end'
    region '^static const uint32_t kTypes' '^}$' "$DI/gc_unit_prep.cc" > "$o/gc_prep_gen.inc"
    [ "$(grep -c '^static void fillRandom(' "$o/gc_prep_gen.inc")" = 1 ] ||
      { echo "unit: gc_unit_prep.cc's generator not found" >&2; exit 1; } ;;
  esac
  case "$BR" in p3 | int2)  # phase 3's link region (impl/gc_unit_p3.cc)
    cut1 "$o/gc_la_link.inc" '^// ---- gin-control [(]launcher[)]: link [(]begin' '^// ---- gin-control [(]launcher[)]: link [(]end' ;;
  esac
  if [ "$BR" = p2b ] || [ "$BR" = p2a2 ] || [ "$BR" = fix3 ] || [ "$BR" = p3 ] || [ "$BR" = int2 ]; then  # phase 2b's pure region (gc_unit_p2b.cc) and the TCP text it is compared with, as p2b cut them
    cut1 "$o/gc_store_pure.inc" '^// ---- gin-control [(]store[)]: pure [(]begin' '^// ---- gin-control [(]store[)]: pure [(]end'
    python3 - "$W/nccl-src/$HOSTF" "$o/gc_p2b_rs.inc" <<'PY3'
import sys
src, out = sys.argv[1], sys.argv[2]
L = open(src, encoding='utf-8').read().split('\n')
res = ['// cut from %s (build_gc_p2a2.sh regions, as build_gc_p2b.sh: the TCP send and receive of the rkey list)' % src]
def block(prefix, end):
    h = [i for i, l in enumerate(L) if l.startswith(prefix)]
    if len(h) != 1: sys.exit('cut: %d lines start with %r' % (len(h), prefix))
    k = h[0]
    while L[k] != end: k += 1
    res.extend(L[h[0]:k + 1])
block('static bool gdakiRsIoAll(', '}')
block('[[maybe_unused]] static ncclResult_t gdakiRsRkeysRecv(', '}')
block('static ncclResult_t gdakiRsRkeysSend(', '}')
open(out, 'w', encoding='utf-8').write('\n'.join(res) + '\n')
PY3
    case "$BR" in p2a2 | int2) p2a2regions "$o" ;; esac
  fi
}
unit1() {  # unit1 <cfg rdma|tcp> <label> <source> [extra g++ args]: one CPU unit test against the cut regions
  local c=$1 n=$2 src=$3; shift 3
  local o=$OUT/unit_$c f=""
  [ "$c" = tcp ] && f="-DNCCL_GIN_CTRL_TCP=1"
  GXX $f "$@" -I"$o" -I"$DI" -I"$MID" -I"$W/nccl-src/src/include" "$src" -o "$o/$n"
  "$o/$n"
}
unitp1one() {  # unitp1one <cfg>: gc_unit_p1.cc, then gate_fenced.cc (rdma only), as run_p1_unit.sh compiled them
  local c=$1 o=$OUT/unit_$1
  grep -E '^#define GDAKI_MI_R(3[4-9]|40) ' "$MID/rs_mirror_api.h" > "$o/mi_reasons.h"
  local p1src=$TI/gc_unit_p1.cc; [ "$BR" = fix3 ] && p1src=$D/gc_unit_p1.cc  # fix3: the worktree's test
  unit1 "$c" gc_unit_p1 "$p1src" -I"$RSD" -include "$o/mi_reasons.h"
  if [ "$c" = rdma ]; then
    unit1 "$c" gate_fenced "$TI/gate_fenced.cc" -I"$RSD" -include "$o/mi_reasons.h"
  else
    echo "unit ($c): gate_fenced is rdma only (the tcp build keeps ln4's /proc gate, no FENCED gate)"
  fi
}
unitp2one() {  # unitp2one <cfg>: gc_unit_p2.cc against the tree's ring model, gc_unit_prep.cc's generator and ln4's
               # TCP back end (gc_ln4_sock.inc of `unit`, or of its own cut for unitp2)
  local p2src=$TI/gc_unit_p2.cc; [ "$BR" = fix3 ] && p2src=$D/gc_unit_p2.cc  # fix3: the worktree's test (the -1 rule)
  unit1 "$1" gc_unit_p2 "$p2src" -DGDAKI_CTRL_API_NO_ENTRY_DECLS
}
unitp3one() {  # unitp3one <cfg>: gc_unit_p3.cc against the tree's launcher link region and the launcher's core (no main)
  local c=$1 o=$OUT/unit_$1
  if [ "$c" = tcp ]; then echo "unit ($c): gc_unit_p3 is rdma only (the tcp build has no launcher link)"; return 0; fi
  nice -n 19 gcc -std=c11 -O1 -g -Wall -Wextra -Werror -fsanitize=address,undefined -DGL_NO_MAIN -DGL_NO_VERBS -I"$DI/launcher" \
    -c "$DI/launcher/gin_launcher.c" -o "$o/gin_launcher_core.o"
  local wd; wd=$(mktemp -d /tmp/gcp3.XXXXXX)
  GXX -DGDAKI_CTRL_API_NO_ENTRY_DECLS -I"$o" -I"$DI" -I"$MID" -I"$DI/launcher" -I"$W/nccl-src/src/include" "$TI/gc_unit_p3.cc" \
    "$o/gin_launcher_core.o" -o "$o/gc_unit_p3"
  local rc=0
  ASAN_OPTIONS=detect_leaks=1 UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1 "$o/gc_unit_p3" "$wd" || rc=$?
  cp "$wd/gc_unit_p3_launcher.log" "$o/gc_unit_p3_launcher.log" 2>/dev/null || true
  rm -rf "$wd"
  return $rc
}
unitp2bone() {  # p2a2: gc_unit_p2b.cc (phase 2b) against the tree's store region, ring model and the cut TCP text
  unit1 "$1" gc_unit_p2b "$TI/gc_unit_p2b.cc" -DGDAKI_CTRL_API_NO_ENTRY_DECLS
}
unitp2a2one() {  # p2a2: gc_unit_p2a2.cc, the live seams over the fake verbs (p2a2regions)
  [ -f "$TI/gc_unit_p2a2.cc" ] || { echo "unit ($1): no gc_unit_p2a2.cc in $TI yet"; return 0; }
  unit1 "$1" gc_unit_p2a2 "$TI/gc_unit_p2a2.cc" -DGDAKI_CTRL_API_NO_ENTRY_DECLS
}
unitp() {  # unitp <1|2|2b|2a2|3>: one phase's tests alone (the development loop)
  head_ok
  case "$1:$BR" in 1:p1 | 1:int | 2:p2 | 2:int | 1:p2a2 | 2:p2a2 | 2b:p2a2 | 2a2:p2a2 | 1:fix3 | 2:fix3 | 2b:fix3 | 1:p2b | 2:p2b | 2b:p2b | 1:p3 | 2:p3 | 2b:p3 | 3:p3 | 1:int2 | 2:int2 | 2b:int2 | 2a2:int2 | 3:int2) ;; *) echo "unitp$1 is not BR=$BR's" >&2; exit 2 ;; esac
  local cfgs="${CFG:-both}" c
  [ "$cfgs" = both ] && cfgs="rdma tcp"
  for c in $cfgs; do
    local o=$OUT/unit_$c; mkdir -p "$o"
    regions "$o"
    echo "== unitp$1 ($c build)"
    if [ "$1" = 2b ] || [ "$1" = 2a2 ] || [ "$1" = 3 ]; then
      cutdefs "$LN4/nccl-src/$HOSTF" "$o/gc_ln4_sock.inc" '#define GDAKI_TS_MAGIC ' 'struct gdakiTsMsg {' 'struct gdakiTsPeer {' \
        'static const char* gdakiTsErrName(' 'static int gdakiTsSend(' 'static int gdakiTsPumpRaw(' 'static int gdakiTsPump(' \
        'static int gdakiTsRecv(' 'static int gdakiRsRecvOn('
      case "$1" in 2b) unitp2bone "$c" ;; 2a2) unitp2a2one "$c" ;; 3) unitp3one "$c" ;; esac
    elif [ "$1" = 2 ]; then
      cutdefs "$LN4/nccl-src/$HOSTF" "$o/gc_ln4_sock.inc" '#define GDAKI_TS_MAGIC ' 'struct gdakiTsMsg {' 'struct gdakiTsPeer {' \
        'static const char* gdakiTsErrName(' 'static int gdakiTsSend(' 'static int gdakiTsPumpRaw(' 'static int gdakiTsPump(' \
        'static int gdakiTsRecv(' 'static int gdakiRsRecvOn('
      unitp2one "$c"
    else
      unitp1one "$c"
    fi
  done
}
unit() {
  head_ok
  local cfgs="${CFG:-both}" c
  [ "$cfgs" = both ] && cfgs="rdma tcp"
  for c in $cfgs; do
    local o=$OUT/unit_$c; mkdir -p "$o"
    regions "$o"
    echo "== unit ($c build: $([ "$c" = tcp ] && echo "-DNCCL_GIN_CTRL_TCP=1" || echo "no switch"))"
    local x
    for x in dev host store spare lineage; do unit1 "$c" "mi_unit_$x" "$MID/mi_unit_$x.cc"; done
    # gin-restore's tests, unchanged, as build_rs.sh unith and units compile them (the restore impl's headers first).
    # Since gin-mirror the restore's pure region names gin-mirror's Resume reasons 34-40 (rs_mirror_api.h's host API),
    # which rs_spare_unit.cc does not include: they are handed in with -include, copied verbatim from that header (ln4's
    # own regions need the same; without it the test does not compile against ln4 either).
    unit1 "$c" rs_unit_host "$RSD/rs_unit_host.cc" -I"$RSD"
    grep -E '^#define GDAKI_MI_R(3[4-9]|40) ' "$MID/rs_mirror_api.h" > "$o/mi_reasons.h"
    [ "$(wc -l < "$o/mi_reasons.h")" = 7 ] || { echo "unit: gin-mirror's reasons 34-40 not found" >&2; exit 1; }
    unit1 "$c" rs_spare_unit "$RSD/rs_spare_unit.cc" -include "$o/mi_reasons.h"
    # gc_unit_prep.cc: the TCP back end of ln4 and of the tree (the record, the peer, the socket helpers), the tree's two
    # blocks and its swap points' bodies, each cut out of its host file as it is
    local x2 b
    for b in ln4 tree; do
      x2=$W/nccl-src/$HOSTF; [ "$b" = ln4 ] && x2=$LN4/nccl-src/$HOSTF
      cutdefs "$x2" "$o/gc_${b}_sock.inc" '#define GDAKI_TS_MAGIC ' 'struct gdakiTsMsg {' 'struct gdakiTsPeer {' \
        'static const char* gdakiTsErrName(' 'static int gdakiTsSend(' 'static int gdakiTsPumpRaw(' 'static int gdakiTsPump(' \
        'static int gdakiTsRecv(' 'static int gdakiRsRecvOn('
    done
    cut1 "$o/gc_seams.inc" '^// ---- gin-control: ctrl seams [(]begin' '^// ---- gin-control: ctrl seams [(]end'
    cutdefs "$W/nccl-src/$HOSTF" "$o/gc_prep_fn.inc" 'static int gdakiCtrlSend(' 'static int gdakiCtrlPump(' \
      'static int gdakiCtrlRecv(' 'static int gdakiCtrlRecvOn('
    if [ "$BR" = p2a2 ] || [ "$BR" = int2 ]; then  # 2a-2-B: the four swap points ask the ring's hooks first; gc_unit_prep.cc runs them with
      # r = nullptr (no ring), so the hooks' answer there is "not the ring's" and nothing counted (the TCP path, ln4's)
      { echo '// build_gc_p2a2.sh: the ring hooks without a ring (gc_unit_prep.cc calls the swap points with r = nullptr)'
        echo 'static bool gdakiCtrlRingSendOf(struct gdakiRecHost*, int, uint32_t, struct gdakiTsMsg*, int, int*) { return false; }'
        echo 'static bool gdakiCtrlRingPumpOf(struct gdakiRecHost*, int, struct gdakiTsPeer&, struct gdakiTsMsg*, int*) { return false; }'
        echo 'static bool gdakiCtrlRingRecvOf(struct gdakiRecHost*, int, uint32_t, struct gdakiTsPeer*, struct gdakiTsMsg*, int,'
        echo '                                std::atomic<bool>*, int*) { return false; }'
        echo 'static void gdakiCtrlTcpCount(struct gdakiRecHost*, int, uint32_t, bool, int) {}'
        cat "$o/gc_prep_fn.inc"; } > "$o/gc_prep_fn.inc.tmp" && mv "$o/gc_prep_fn.inc.tmp" "$o/gc_prep_fn.inc"
    fi
    if cmp -s <(sed 1d "$o/gc_ln4_sock.inc") <(sed 1d "$o/gc_tree_sock.inc"); then
      echo "unit ($c): the tree's TCP back end (gdakiTsMsg, gdakiTsPeer, gdakiTsErrName, gdakiTsSend, gdakiTsPumpRaw, gdakiTsPump, gdakiTsRecv, gdakiRsRecvOn) is ln4's text"
    else
      echo "unit ($c): the tree's TCP back end differs from ln4's" >&2; exit 1
    fi
    unit1 "$c" gc_unit_prep "$DI/gc_unit_prep.cc" -DGDAKI_CTRL_API_NO_ENTRY_DECLS
    case "$BR" in p1 | int | p2b | p2a2 | fix3 | p3 | int2) unitp1one "$c" ;; esac
    case "$BR" in p2 | int | p2b | p2a2 | fix3 | p3 | int2) unitp2one "$c" ;; esac
    case "$BR" in p2b | p2a2 | fix3 | p3 | int2) unitp2bone "$c" ;; esac
    case "$BR" in p2a2 | fix3 | int2) unitp2a2one "$c" ;; esac
    case "$BR" in p3 | int2) unitp3one "$c" ;; esac
  done
}
cutdefs() {  # cutdefs <host file> <out> <start>...: for each start (a line prefix): a #define line as it is, a struct up to
             # its "};", a function's definition (not a declaration) up to the first line "}"
  python3 - "$@" <<'PY'
import sys
src, out, starts = sys.argv[1], sys.argv[2], sys.argv[3:]
L = open(src, encoding='utf-8').read().split('\n')
res = ['// cut from %s' % src]
for s in starts:
    hit = None
    for i, l in enumerate(L):
        if not l.startswith(s): continue
        if s.startswith('#define'): hit = (i, i); break
        j = i
        while j < len(L) and '{' not in L[j] and ';' not in L[j]: j += 1
        if j < len(L) and ';' in L[j] and '{' not in L[j]: continue  # a declaration
        end = '};' if s.startswith('struct ') else '}'
        k = j
        while k < len(L) and L[k] != end: k += 1
        hit = (i, k); break
    if hit is None: sys.exit('cutdefs: no %r in %s' % (s, src))
    res += L[hit[0]:hit[1] + 1]
open(out, 'w', encoding='utf-8').write('\n'.join(res) + '\n')
PY
}

# ---- pre: the preprocessed host file of the tcp builds against ln4's ----
precmd() {  # precmd <build dir> <CXXFLAGS>: that build's compile command of the host file (make -n -B), one line, run in src/
  local b=$1
  (cd "$W/nccl-src" && CXXFLAGS="$2" make -n -B -C src "$b/obj/transport/net_ib/gdaki/gin_host_gdaki.o" BUILDDIR="$b" \
     CUDA_HOME=$CUDA NVCC_GENCODE="$GENCODE" 2>/dev/null) |
    grep -E '^g\+\+ ' | grep -F -- ' -c transport/net_ib/gdaki/gin_host_gdaki.cc ' | head -1
}
norm() {  # norm <in> <out>: the tree's path in __FILE__ strings and the host file's __LINE__ after its __FILE__ (and
          # __func__) normalized, and blank lines dropped (REVIEW_PREP nit 7: -E -P keeps blank lines where the #if
          # branches were; the raw line counts are printed beside); nothing else
  sed -E 's#'"$SCR"'/agent_[A-Za-z0-9_]+/nccl-src/#TREE/#g; s#("TREE/src/transport/net_ib/gdaki/gin_host_gdaki\.cc"\)?, (__func__, )?\(?)[0-9]+#\1L#g' "$1" |
    grep -v '^[[:space:]]*$' > "$2"
}
pre1() {  # pre1 <label> <build dir> <CXXFLAGS of that build>
  local lab=$1 b=$2 fl=$3 o=$OUT/pre
  mkdir -p "$o"
  local cmd; cmd=$(precmd "$W/$b" "$fl")
  [ -n "$cmd" ] || { echo "pre: no compile command of the host file for $b (make -n)" >&2; exit 1; }
  local cdir=$W/nccl-src/src
  local ours theirs
  ours=$(echo "$cmd" | sed -E 's# -c transport/net_ib/gdaki/gin_host_gdaki\.cc# -E -P '"$W/nccl-src/$HOSTF"'#; s# -o [^ ]+\.o# -o '"$o/${lab}.i"'#')
  theirs=$(echo "$cmd" | sed -E 's# -c transport/net_ib/gdaki/gin_host_gdaki\.cc# -E -P '"$LN4/nccl-src/$HOSTF"'#; s# -o [^ ]+\.o# -o '"$o/${lab}_ln4.i"'#')
  echo "$ours" > "$o/${lab}.cmd"
  (cd "$cdir" && eval "nice -n 19 $ours")
  (cd "$cdir" && eval "nice -n 19 $theirs")
  norm "$o/${lab}.i" "$o/${lab}.n.i"
  norm "$o/${lab}_ln4.i" "$o/${lab}_ln4.n.i"
  diff "$o/${lab}_ln4.i" "$o/${lab}.i" > "$o/${lab}.raw.diff" || true
  diff -U3 "$o/${lab}_ln4.n.i" "$o/${lab}.n.i" > "$o/${lab}.norm.diff" || true
  echo "pre $lab: ln4 $(wc -l < "$o/${lab}_ln4.i") lines md5 $(md5 "$o/${lab}_ln4.i"), ours $(wc -l < "$o/${lab}.i") lines md5 $(md5 "$o/${lab}.i");" \
       "raw diff $(grep -c '^[<>]' "$o/${lab}.raw.diff") lines; normalized: ln4 $(md5 "$o/${lab}_ln4.n.i"), ours $(md5 "$o/${lab}.n.i")," \
       "$(grep -c '^@@' "$o/${lab}.norm.diff" || true) hunks, $(grep -c '^[-+][^-+]' "$o/${lab}.norm.diff" || true) changed lines"
}
syn1() {  # syn1 <build dir> <CXXFLAGS>: the host file's compile command of that build with -fsyntax-only
  local cmd; cmd=$(precmd "$W/$1" "$2")
  [ -n "$cmd" ] || { echo "syn: no compile command for $1" >&2; exit 1; }
  cmd=$(echo "$cmd" | sed -E 's# -c transport/net_ib/gdaki/gin_host_gdaki\.cc# -fsyntax-only transport/net_ib/gdaki/gin_host_gdaki.cc#; s# -o [^ ]+\.o##')
  (cd "$W/nccl-src/src" && eval "nice -n 19 $cmd") && echo "syn $1: the host file compiles (-fsyntax-only)"
}
pre() {
  head_ok
  pre1 gct build-gct "-DNCCL_GIN_CTRL_TCP=1"
  pre1 gctp build-gctp "-DNCCL_GIN_TS_PRODUCTION -DNCCL_GIN_CTRL_TCP=1"
  # the tcp control cells' build (REVIEW2 고칠 것 3): ln4 plus exactly what NCCL_GIN_CTRL_TCP_CELLS adds (preprocessed only)
  pre1 gctc build-gct "-DNCCL_GIN_CTRL_TCP=1 -DNCCL_GIN_CTRL_TCP_CELLS=1"
  [ -n "${PRE_ALL:-1}" ] && pre1 gc build ""   # for the record: the default build's differences (expected: the new code)
}

# ---- sites: the swap points' call sites, ln4 and the working tree; impl/gc_sites.tsv ----
sites() {
  head_ok
  local f=$W/nccl-src/$HOSTF l=$LN4/nccl-src/$HOSTF s
  for s in gdakiTsSend gdakiTsPump gdakiTsRecv gdakiRsRecvOn gdakiTsAnswerFail gdakiHoldSend gdakiCtrlSend gdakiCtrlPump \
           gdakiCtrlRecv gdakiCtrlRecvOn gdakiCtrlRejoinFail gdakiCtrlChanUp gdakiCtrlChanGen gdakiCtrlPollFd gdakiCtrlChanInstall; do
    echo "sites: $s( lines: ln4 $(grep -cE "\\b$s\\(" "$l" || true), tree $(grep -cE "\\b$s\\(" "$f" || true)"
  done
  echo "sites: pe.fd lines: ln4 $(grep -cE '\bpe\.fd\b' "$l"), tree $(grep -cE '\bpe\.fd\b' "$f")"
  python3 - "$DI/gc_sites.tsv" "$l" "$f" <<'PY2'
import re, sys
from collections import Counter
tsv, ln4, tree = sys.argv[1:4]
rows = [l.rstrip('\n').split('\t') for l in open(tsv, encoding='utf-8') if l.strip() and not l.startswith('#')][1:]
uses = [l.rstrip('\n').split('\t')[1:] for l in open(tsv, encoding='utf-8') if l.startswith('#use\t')]
L = open(ln4, encoding='utf-8').read().split('\n')
T = open(tree, encoding='utf-8').read().split('\n')
bad = 0
def isCode(l): return not l.lstrip().startswith('//') and not l.lstrip().startswith('#define')
REG = r'^// (----|====) gin-control(:| \((prep|page|ring)\))'
def views(lines):
    # the rdma side: code lines outside the pasted blocks, the preparation region and the phases' own regions (page,
    # ring: new code; nested markers counted), without the #if NCCL_GIN_CTRL_TCP branches; and those branches (outside
    # the blocks), each a list of lines
    out, branches, depth, stack, cur = [], [], 0, [], None
    for l in lines:
        m = re.match(REG, l)
        if m:
            depth += 1 if '(begin' in l else (-1 if '(end' in l else 0)
            if depth < 0: sys.exit('sites: a region ends that did not begin: %r' % l[:100])
            continue
        if depth > 0: continue
        d = l.strip()
        if d.startswith('#if'):
            k = 'tcp' if d == '#if NCCL_GIN_CTRL_TCP' else 'rdma' if d == '#if !NCCL_GIN_CTRL_TCP' else 'other'
            stack.append(k)
            if k == 'tcp': cur = []
            continue
        if d.startswith('#else') and stack and stack[-1] in ('tcp', 'rdma'):
            if stack[-1] == 'tcp': branches.append(cur); cur = None
            else: cur = []
            stack[-1] = 'rdma' if stack[-1] == 'tcp' else 'tcp'
            continue
        if d.startswith('#endif') and stack:
            if stack[-1] == 'tcp': branches.append(cur); cur = None
            stack.pop()
            continue
        if 'tcp' in stack:
            if stack[-1] == 'tcp' and cur is not None: cur.append(l)
            continue
        if isCode(l) and not d.startswith('#'): out.append(l)
    return out, branches
C, B = views(T)
LC = [l for l in L if isCode(l)]
def n(pat, lines): return sum(len(re.findall(pat, l)) for l in lines)
cnt = Counter((r[0], r[4]) for r in rows)
pe = [i + 1 for i, l in enumerate(L) if re.search(r'\bpe\.fd\b', l)]
if sorted(int(r[1]) for r in rows if r[0] == 'fd') != pe: bad += 1; print('tsv: the fd rows are not ln4\'s pe.fd lines')
FD = r'(\.|->)fd\b'
for r in rows:  # every row names a line of ln4 that has what its kind says
    t = L[int(r[1]) - 1]
    want = {'send': r'\bgdakiTsSend\(', 'pump': r'\bgdakiTsPump\(', 'recv': r'\bgdakiTsRecv\(|\bgdakiRsRecvOn\(',
            'answer': r'\bgdakiTsAnswerFail\(', 'holdsend': r'\bgdakiHoldSend\(', 'fd': r'\bpe\.fd\b', 'fd-other': FD,
            'accept': r'\bgdakiTsRecv\(', 'state': r'\bpe\.(gone|gen|have|unknown)\b|deferredGen'}[r[0]]
    if not re.search(want, t): bad += 1; print('tsv: row %s %s: ln4\'s line has no %s' % (r[0], r[1], want))
conv = sum(v for (k, a), v in cnt.items() if k in ('fd', 'fd-other') and a in ('chanup', 'pollfd', 'install'))
checks = [
  ('gdakiCtrlSend( calls', cnt[('send', 'swapped')], n(r'\bgdakiCtrlSend\(', C)),
  ('gdakiCtrlPump( calls', cnt[('pump', 'swapped')], n(r'\bgdakiCtrlPump\(', C)),
  ('gdakiCtrlRecv(, gdakiCtrlRecvOn( calls', cnt[('recv', 'swapped')], n(r'\bgdakiCtrlRecv(On)?\(', C)),
  ('gdakiCtrlRejoinFail( calls', cnt[('answer', 'swapped')], n(r'\bgdakiCtrlRejoinFail\(', C)),
  ('gdakiTsSend( calls and definition', cnt[('send', 'kept')], n(r'\bgdakiTsSend\(', C)),
  ('gdakiTsPump( calls and definition', cnt[('pump', 'kept')], n(r'\bgdakiTsPump\(', C)),
  ('gdakiTsRecv(, gdakiRsRecvOn( kept', cnt[('recv', 'kept')], n(r'\bgdakiTsRecv\(|\bgdakiRsRecvOn\(', C)),
  ('gdakiTsAnswerFail( kept', cnt[('answer', 'kept')], n(r'\bgdakiTsAnswerFail\(', C)),
  ('gdakiHoldSend( lines', sum(v for (k, a), v in cnt.items() if k == 'holdsend'), n(r'\bgdakiHoldSend\(', C)),
  ('gdakiCtrlChanUp( uses', cnt[('fd', 'chanup')] + cnt[('fd-other', 'chanup')], n(r'\bgdakiCtrlChanUp\(', C)),
  ('gdakiCtrlPollFd( uses', cnt[('fd', 'pollfd')] + cnt[('fd-other', 'pollfd')], n(r'\bgdakiCtrlPollFd\(', C)),
  ('gdakiCtrlChanInstall( uses', cnt[('fd', 'install')] + cnt[('fd-other', 'install')], n(r'\bgdakiCtrlChanInstall\(', C)),
  ('gdakiCtrlChanGen( uses', cnt[('state', 'changen')], n(r'\bgdakiCtrlChanGen\(', C)),
  ('.fd uses left (ln4 minus the seams)', n(FD, LC) - conv, n(FD, C)),
  ('pe.fd uses left', sum(len(re.findall(r'\bpe\.fd\b', L[int(r[1]) - 1])) for r in rows
                          if r[0] == 'fd' and r[4] in ('kept', 'arg')), n(r'\bpe\.fd\b', C)),
]
for what, want, got in checks:
    print('tsv: %-40s table %3d, tree %3d%s' % (what, want, got, '' if want == got else '  MISMATCH'))
    if want != got: bad += 1
# the phases' own regions: the code lines of each top-level "gin-control (page|ring)" region (its sub-regions inside),
# and every call the table's "#use" lines name, counted there
def regionCode(lines):
    res, cur, depth = {}, None, 0
    for l in lines:
        m = re.match(r'^// (----|====) gin-control \((page|ring)\)', l)
        if m and depth == 0 and '(begin' in l: cur, depth = m.group(2), 1; res.setdefault(cur, []); continue
        if m and cur == m.group(2) and depth > 0:
            depth += 1 if '(begin' in l else (-1 if '(end' in l else 0)
            if depth == 0: cur = None
            continue
        if cur and isCode(l) and not l.strip().startswith('#'): res[cur].append(l)
    return res
RC = regionCode(T)
CALLS = ['gdakiTsSend', 'gdakiTsPump', 'gdakiTsRecv', 'gdakiRsRecvOn', 'gdakiTsAnswerFail', 'gdakiHoldSend', 'gdakiCtrlSend',
         'gdakiCtrlPump', 'gdakiCtrlRecv', 'gdakiCtrlRecvOn', 'gdakiCtrlRejoinFail', 'gdakiCtrlChanUp', 'gdakiCtrlChanGen',
         'gdakiCtrlPollFd', 'gdakiCtrlChanInstall']
got = {(rg, c): n(r'\b%s\(' % c, RC.get(rg, [])) for rg in ('page', 'ring') for c in CALLS}
got.update({(rg, '.fd'): n(FD, RC.get(rg, [])) for rg in ('page', 'ring')})
want = {(u[0], u[1]): int(u[2]) for u in uses}
for k in sorted(set(got) | set(want)):
    g, w = got.get(k, 0), want.get(k, 0)
    if g == 0 and w == 0: continue
    print('tsv: %-40s table %3d, tree %3d%s' % ('%s region: %s' % k, w, g, '' if w == g else '  MISMATCH'))
    if w != g: bad += 1
print('tsv: the phases\' regions: %s' % ', '.join('%s %d code lines' % (k, len(v)) for k, v in sorted(RC.items())))
# every tcp branch is ln4's text: a run of consecutive ln4 lines
J = '\n'.join(L)
nb = 0
for b in B:
    if b and ('\n' + '\n'.join(b) + '\n') not in ('\n' + J + '\n'):
        bad += 1; print('tsv: an #if NCCL_GIN_CTRL_TCP branch is not ln4\'s text: %r' % b[0][:100])
    nb += 1
print('tsv: %d #if NCCL_GIN_CTRL_TCP branches outside the blocks, each a run of ln4\'s lines verbatim' % nb if not bad else
      'tsv: %d #if NCCL_GIN_CTRL_TCP branches checked' % nb)
print('tsv: %d rows; %s' % (len(rows), ', '.join('%s %s %d' % (k, a, v) for (k, a), v in sorted(cnt.items()))))
sys.exit(1 if bad else 0)
PY2
}

# ---- ident: the device identity against ln4 ----
LN4SASS=$LN4/sass_mi_ln4  # ln4's programs (ff_cmp_mi.sh, the same flags; read only)
ident() {
  local O=$OUT/ident_$IDTAG CU=$CUDA/bin
  [ -e "$O" ] && { echo "$O exists; give a new IDTAG" >&2; exit 1; }
  mkdir -p "$O"
  local RING=$W/nccl-src/docs/examples/09_gin_optimizations/01_ring_exchange/c
  local DRV="-Xcompiler -Wall,-Wextra,-Werror,-Wno-missing-field-initializers"
  local b
  for b in build build-gct build-gcp build-gctp; do
    diff -r -q "$W/build/include" "$W/$b/include" > /dev/null || { echo "ident: $b's installed headers differ" >&2; exit 1; }
  done
  diff -r -q "$W/build/include" "$LN4/build/include" > /dev/null && echo "ident: the installed headers equal ln4's (build/include)" ||
    echo "ident: the installed headers DIFFER from ln4's"
  rm -rf "$O/inc"; mkdir -p "$O/inc"
  cp -a "$W/build/include/nccl.h" "$W/build/include/nccl_device.h" "$W/build/include/nccl_device" "$O/inc/"
  cc() {  # cc <name> <variant n|m> <source> [flags]
    local n=$1 v=$2 src=$3; shift 3
    local mac=""; [ "$v" = m ] && mac="-DNCCL_GIN_RESTORE_DEVICE"
    local a
    for a in 75 86; do
      nice -n 19 "$CU/nvcc" -std=c++17 -O2 --expt-relaxed-constexpr -gencode=arch=compute_$a,code=sm_$a $mac -isystem "$O/inc" \
        "$@" -c "$src" -o "$O/${n}_$v$a.o" > "$O/${n}_$v$a.log" 2>&1 || { cat "$O/${n}_$v$a.log" >&2; exit 1; }
    done
  }
  local p v a pe=0 pd=0
  for v in n m; do
    cc ff "$v" "$RSD/ff_ops.cu"
    cc gin_ts2 "$v" "$RSD/../../gin_ts2.cu" $DRV
    cc gin_mr "$v" "$RSD/../../remaining/gin_mr.cu" $DRV
    cc ring "$v" "$RING/main.cu" -I"$RING/../../../common/include"
  done
  for v in n m; do
    for p in ff gin_ts2 gin_mr ring; do
      for a in 75 86; do
        "$CU/cuobjdump" -sass "$O/${p}_$v$a.o" > "$O/${p}_$v$a.sass"
        "$CU/cuobjdump" -res-usage "$O/${p}_$v$a.o" | grep -E 'Function|REG' > "$O/${p}_$v$a.res"
        "$CU/cuobjdump" -sass "$LN4SASS/${p}_$v$a.o" > "$O/${p}_$v${a}_ln4.sass"
        "$CU/cuobjdump" -res-usage "$LN4SASS/${p}_$v$a.o" | grep -E 'Function|REG' > "$O/${p}_$v${a}_ln4.res"
        if cmp -s "$O/${p}_$v$a.sass" "$O/${p}_$v${a}_ln4.sass" && cmp -s "$O/${p}_$v$a.res" "$O/${p}_$v${a}_ln4.res"; then
          pe=$((pe + 1))
          echo "program $p ($v) sm_$a vs ln4: SASS and resources identical ($(grep -cE '^\s+/\*[0-9a-f]{4,}\*/' "$O/${p}_$v$a.sass") instructions, $(wc -l < "$O/${p}_$v$a.sass") lines)"
        else
          pd=$((pd + 1))
          echo "program $p ($v) sm_$a vs ln4: DIFFERENT: $(diff "$O/${p}_$v${a}_ln4.sass" "$O/${p}_$v$a.sass" | grep -c '^[<>]') SASS lines"
        fi
      done
    done
  done
  echo "programs vs ln4: identical $pe, different $pd (program x variant x architecture; n = without NCCL_GIN_RESTORE_DEVICE)"
  export CU O
  sum1() {
    local d=$1 rel=$2 t
    t=$(mktemp -p "$O")
    local e try
    e=$(mktemp -p "$O")
    for try in 1 2; do  # REVIEW_P3 고칠 것 7: a failed or empty dump is a line, tried once more, never a silent md5
      "$CU/cuobjdump" -sass "$d/$rel" > "$t" 2> "$e" && [ -s "$t" ] && break
      echo "ident: cuobjdump -sass failed on $d/$rel (try $try, rc $?, $(head -1 "$e"))" >&2
      : > "$t"
    done
    rm -f "$e"
    [ -s "$t" ] || { echo "$rel DUMP_FAILED DUMP_FAILED $(md5sum < "$d/$rel" | cut -c1-32)"; rm -f "$t"; return 0; }
    echo "$rel $(md5sum < "$t" | cut -c1-32) $(sed -E 's/(_INTERNAL_|__nv_static_[0-9]+__|__N__)[0-9a-f]{8}_/\1H_/g; s/_cu_[0-9a-f]{8}_[0-9]+/_cu_H/g' "$t" | md5sum | cut -c1-32) $(md5sum < "$d/$rel" | cut -c1-32)"
    rm -f "$t"
  }
  export -f sum1
  sums() { (cd "$1" && find obj/device obj/diagnostics/device -name '*.o' | LC_ALL=C sort) |
             nice -n 19 xargs -P 8 -I{} bash -c 'sum1 "$0" "$1"' "$1" {} | LC_ALL=C sort > "$2"; }
  objs() {  # objs <label> <ours> <theirs>
    local lab=$1 ours=$2 theirs=$3 le=0 lh=0 ld=0 lm=0 lb=0 rel x xm xb y ym yb
    while read -r rel x xm xb; do
      y=$(awk -v r="$rel" '$1 == r {print $2; exit}' "$theirs"); ym=$(awk -v r="$rel" '$1 == r {print $3; exit}' "$theirs")
      yb=$(awk -v r="$rel" '$1 == r {print $4; exit}' "$theirs")
      if [ -z "$y" ]; then lm=$((lm + 1)); echo "library $lab: missing there: $rel"; continue; fi
      [ "$xb" = "$yb" ] && lb=$((lb + 1))
      if [ "$x" = "$y" ]; then le=$((le + 1)); continue; fi
      if [ "$xm" = "$ym" ]; then lh=$((lh + 1)); echo "library $lab: equal once the compile hash is masked: $rel"; continue; fi
      ld=$((ld + 1)); echo "library $lab: DIFFERENT: $rel"
    done < "$ours"
    echo "library $lab device objects: identical SASS $le, identical with the hash masked $lh, different $ld, missing there $lm" \
         "(byte-identical object files $lb)"
  }
  sums "$LN4/build" "$O/obj_ln4.txt"
  sums "$LN4/build-mip" "$O/obj_ln4p.txt"
  for b in build build-gct build-gcp build-gctp; do sums "$W/$b" "$O/obj_$b.txt"; done
  objs "gc (build) vs ln4 build" "$O/obj_build.txt" "$O/obj_ln4.txt"
  objs "gct (build-gct) vs ln4 build" "$O/obj_build-gct.txt" "$O/obj_ln4.txt"
  objs "gcp (build-gcp) vs ln4 build-mip" "$O/obj_build-gcp.txt" "$O/obj_ln4p.txt"
  objs "gctp (build-gctp) vs ln4 build-mip" "$O/obj_build-gctp.txt" "$O/obj_ln4p.txt"
  mask() { sed -E 's/(_INTERNAL_|__nv_static_[0-9]+__|__N__)[0-9a-f]{8}_/\1H_/g; s/_cu_[0-9a-f]{8}_[0-9]+/_cu_H/g'; }
  libres() {  # libres <label> <ours> <theirs>
    local lab=$1 x y
    [ -f "$2" ] || { echo "library $lab: $2 missing"; return 0; }
    x=$("$CU/cuobjdump" -res-usage "$3" | grep -E 'Function|REG' | mask | md5sum)
    y=$("$CU/cuobjdump" -res-usage "$2" | grep -E 'Function|REG' | mask | md5sum)
    echo "library $lab resource usage (names with the hash masked): $([ "$x" = "$y" ] && echo identical || echo DIFFERENT)"
  }
  libres "$GCOUT vs ln4" "$OUT/$GCOUT/libnccl.so.2.32.3" "$LN4/out/mi_ln4/libnccl.so.2.32.3"
  libres "$GCTOUT vs ln4" "$OUT/$GCTOUT/libnccl.so.2.32.3" "$LN4/out/mi_ln4/libnccl.so.2.32.3"
  libres "$GCPOUT vs ln4p" "$OUT/$GCPOUT/libnccl.so.2.32.3" "$LN4/out/mip_ln4/libnccl.so.2.32.3"
  libres "$GCTPOUT vs ln4p" "$OUT/$GCTPOUT/libnccl.so.2.32.3" "$LN4/out/mip_ln4/libnccl.so.2.32.3"
}
mkdiff() {
  head_ok; files_ok
  local n
  for n in $(MG ls-files --others --exclude-standard -- src); do MG add -N -- "$n"; done
  # int: the whole layer on ln4 (the prep-fix commit and the working tree: prep-fix + phase 1 + phase 2a-1); else the
  # working tree against the head commit
  local base=HEAD
  { [ "$BR" = int ] || [ "$BR" = int2 ]; } && base=$(MG rev-list --max-count=1 --grep="^$LN4_SUBJECT\$" HEAD)
  { [ "$BR" = p2a2 ] || [ "$BR" = fix3 ]; } && base=$(MG rev-list --max-count=1 --fixed-strings --grep="$P2A2_BASE" HEAD)  # on 2efebe3
  [ "$BR" = p3 ] && base=$(MG rev-list --max-count=1 --fixed-strings --grep="$P2A2_BASE" HEAD)  # p3: phase 3 and its fix on 2b (e3faf02)
  MG diff --diff-algorithm=histogram "$base" -- src > "$LAYER"
  MG apply --check -R "$LAYER"
  echo "diff: impl/$(basename "$LAYER") $(md5 "$LAYER") $(wc -l < "$LAYER") lines ($(MG diff --name-only "$base" -- src | tr '\n' ' ')) against $(MG log -1 --format='%h %s' "$base")"
  if [ "$BR" = int2 ]; then  # the glue alone (against the merge commit), for the record
    echo "diff: of it the glue (working tree against HEAD, $(MG log -1 --format=%s)): $(MG diff --diff-algorithm=histogram HEAD -- src | md5sum | cut -c1-32), $(MG diff --diff-algorithm=histogram HEAD -- src | wc -l) lines"
  fi
  if [ "$BR" = int ]; then  # the phases' part alone (against the prep-fix commit), for the record
    echo "diff: of it the phases' part (working tree against HEAD, $(MG log -1 --format=%s)): $(MG diff --diff-algorithm=histogram HEAD -- src | md5sum | cut -c1-32), $(MG diff --diff-algorithm=histogram HEAD -- src | wc -l) lines"
  fi
}
info() {
  {
    echo "built=$(date '+%F %T') host=$(hostname -s) nvcc=$("$CUDA/bin/nvcc" --version | tail -1) g++=$(g++ -dumpfullversion)"
    echo "work package $BR; base: $(basename "$W") head $(MG rev-parse --short HEAD) ($(MG log -1 --format=%s));" \
         "ln4 commit diff md5 $(MG diff --diff-algorithm=histogram "$(MG rev-list --max-count=1 --grep="^$LN4_SUBJECT\$" HEAD)~1" \
         "$(MG rev-list --max-count=1 --grep="^$LN4_SUBJECT\$" HEAD)" -- src | md5sum | cut -c1-32) (mi_layer.diff $(md5 "$MID/mi_layer.diff"))"
    echo "working tree: $(MG diff --name-only HEAD -- src | tr '\n' ' ')"
    echo "working tree diff md5 $(MG diff --diff-algorithm=histogram HEAD -- src | md5sum | cut -c1-32) (histogram)"
    echo "host file md5 $(md5 "$W/nccl-src/$HOSTF") $(wc -l < "$W/nccl-src/$HOSTF") lines (ln4 $(md5 "$LN4/nccl-src/$HOSTF"))"
    [ -f "$LAYER" ] && echo "$(basename "$LAYER") $(md5 "$LAYER") $(wc -l < "$LAYER") lines"
    for b in "$OUT"/*/libnccl.so.2.32.3; do [ -f "$b" ] && echo "$(basename "$(dirname "$b")") libnccl $(md5 "$b")"; done
    for b in build build-gct build-gcp build-gctp; do
      [ -f "$W/$b/obj/transport/net_ib/gdaki/gin_host_gdaki.o" ] &&
        echo "$b gin_host_gdaki.o $(md5 "$W/$b/obj/transport/net_ib/gdaki/gin_host_gdaki.o")"
    done
    echo "include_digest build $(cd "$W/build/include" && find . -type f | LC_ALL=C sort | xargs md5sum | md5sum | cut -c1-32)"
    echo "include_digest ln4 $(cd "$LN4/build/include" && find . -type f | LC_ALL=C sort | xargs md5sum | md5sum | cut -c1-32)"
    for f in rs_ctrl_api.h gc_sites.tsv gc_unit_prep.cc launcher/launcher_msg.h; do
      [ -f "$DI/$f" ] && echo "$f $(md5 "$DI/$f") $(wc -l < "$DI/$f") lines$([ "$DI" = "$D" ] || echo " (pinned, $DI)")"
    done
    for f in build_gc.sh launcher/gin_launcher.c launcher/launcher_transport_verbs.c launcher/launcher_unit.cc; do
      [ -f "$D/$f" ] && echo "$f $(md5 "$D/$f") $(wc -l < "$D/$f") lines"
    done
    [ "$BR" = p2a2 ] && echo "build_gc_p2a2.sh $(md5 "$W/build_gc_p2a2.sh") $(wc -l < "$W/build_gc_p2a2.sh") lines (agent_gc_p2a2/)"
    case "$BR" in p1 | p2 | int | p2b | p2a2 | fix3 | p3 | int2)
      for f in gc_unit_p1.cc gate_fenced.cc gc_unit_p2.cc gc_unit_p2b.cc gc_unit_p2a2.cc gc_unit_p3.cc gc_layer.diff gc_layer_p1.diff gc_layer_p2.diff gc_layer_int.diff gc_layer_p2b.diff gc_layer_p2a2.diff gc_layer_fix3.diff gc_layer_p3.diff; do
        [ -f "$TI/$f" ] && echo "$f $(md5 "$TI/$f") $(wc -l < "$TI/$f") lines"
      done ;;
    esac
  } > "${INFO:-$OUT/build_info.txt}"
  cat "${INFO:-$OUT/build_info.txt}"
}
case "$STAGE" in
  setup) setup ;;
  paste) paste ;;
  repaste) repaste ;;
  api) api ;;
  gc) lib build "$GCOUT" "" ;;
  gcp) lib build-gcp "$GCPOUT" "-DNCCL_GIN_TS_PRODUCTION" ;;
  gct) lib build-gct "$GCTOUT" "-DNCCL_GIN_CTRL_TCP=1" ;;
  gctp) lib build-gctp "$GCTPOUT" "-DNCCL_GIN_TS_PRODUCTION -DNCCL_GIN_CTRL_TCP=1" ;;
  unit) unit ;;
  unitp1) unitp 1 ;;
  unitp2) unitp 2 ;;
  unitp2b) unitp 2b ;;
  unitp2a2) unitp 2a2 ;;
  unitp3) unitp 3 ;;
  syn) head_ok; syn1 build "" && syn1 build-gcp "-DNCCL_GIN_TS_PRODUCTION" && syn1 build-gct "-DNCCL_GIN_CTRL_TCP=1" ;;
  pre) pre ;;
  sites) sites ;;
  ident) ident ;;
  diff) mkdiff ;;
  info) mkdir -p "$OUT"; info ;;
  *) echo "unknown stage $STAGE" >&2; exit 2 ;;
esac
