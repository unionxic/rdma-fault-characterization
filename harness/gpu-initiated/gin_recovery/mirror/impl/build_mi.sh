#!/usr/bin/env bash
# build_mi.sh - build gin-mirror's mirror layer (EXPERIMENT.md 9.8, impl/PARALLEL.md) in a NEW scratch tree per branch,
# on top of gin-restore's final layer (build i5). Modeled on ../../restore/impl/build_rs.sh. SKELETON: written with the
# shared interface (2026-10-13) and not run yet; its first run is a branch's `setup`. No GPU or RDMA program runs here;
# nothing outside agent_mi_$BR/ is written but impl/mi_layer_$BR.diff (stage diff) in this worktree. agent_rs_int/ (i5)
# and agent_gd/gin_hk (hk) are read only.
# usage: BR=<dev|host|store|spare|test|int|fix> build_mi.sh <setup|paste|api|mi|mip|unit|ident|diff|info>
#   fix (2026-10-15, the fixes of pilot 1): agent_mi_fix/ is a copy of agent_mi_int/ (nccl-src, build, build-mip; the
#          absolute paths in the dependency files and device manifests rewritten, mtimes kept; done by hand, `setup`
#          refuses for fix); it works as int: impl/mi_layer.diff, the hold v2 text, every unit test, ident.
#   setup  once: check that agent_rs_int is gin-restore's i5 (head commit "gpu-detect hk (libnccl 2913c777)", working tree
#          diff md5 f005bb67 = ../../restore/impl/rs_layer.diff, build/lib libnccl 4811f28f, build-rsp/lib be91b270), copy
#          its nccl-src, build and build-rsp to agent_mi_$BR/{nccl-src,build,build-mip}, rewrite the absolute paths in the
#          dependency files and device manifests (mtimes kept), and commit the rs layer in the copy as
#          "gin-restore i5 (rs_layer.diff f005bb67)" (history: hq, hr, hw, hk, i5); check that commit's diff is
#          rs_layer.diff byte for byte and the copied libraries are i5's.
#   paste  once, the branch's first commit (the "interface commit"): paste the shared interface into the tree exactly as
#          PARALLEL.md's table says (every block for every branch; rs_hold_api.h v2's shared text only for host and int).
#          Refused when the tree already has a gin-mirror block.
#   api    every pasted block is its header's, byte for byte (the hold shared text: v2 for host and int, v1 elsewhere; the
#          checkpoint's shared text: v1, unchanged), the gdakiRecHost member line is there once, and the six headers
#          compile together (g++ -fsyntax-only, with and without their entry-point declarations).
#   mi     apply impl/mi_layer_$BR.diff unless the working tree already carries changes (the changed files must be among
#          MI_FILES); incremental make into agent_mi_$BR/build -> agent_mi_$BR/out/$MIOUT/libnccl.so.2.32.3 (research
#          build; MIOUT default mi_$BR; a folder that already holds a build is refused: give a new name).
#   mip    the production build of the same source (-DNCCL_GIN_TS_PRODUCTION) into agent_mi_$BR/build-mip ->
#          agent_mi_$BR/out/$MIPOUT/ (default mip_$BR; same refusal).
#   unit   the branch's CPU unit test impl/mi_unit_$BR.cc (int: every branch's, one after the other): gin-restore's pure
#          regions and the branch's "gin-mirror ($BR): pure" region cut out of the working tree into .inc files, the impl/
#          headers on the include path; g++ with ASan and UBSan; no NCCL, no CUDA, no network.
#   ident  the fail-fast identity of 9.5 (dev and int): impl/exact_cmp_mi.sh and impl/ff_cmp_mi.sh, which the dev branch
#          writes from gin-restore's exact_cmp_dev.sh and ff_cmp_dev.sh (against hk AND i5). Refused until they exist.
#   diff   write impl/mi_layer_$BR.diff (int: impl/mi_layer.diff, the integrated layer; the working tree against the i5
#          commit, histogram, new files as intent-to-add) and check that it applies in reverse on the working tree.
#   info   agent_mi_$BR/out/build_info.txt (INFO=<file> for another name): md5 of every output and input, the base.
# The device objects are rebuilt whenever the device header trees differ from the last build of that directory (devsync,
# build_rs.sh's rule; the mirror layer changes the device-host common header, so the first mi build rebuilds them all).
# All compiles run at nice 19 and idle I/O priority (other studies use this node).
set -euo pipefail
STAGE=${1:?stage}
BR=${BR:?BR=<dev|host|store|spare|test|int|fix>}
case "$BR" in dev | host | store | spare | test | int | fix) ;; *) echo "unknown branch $BR" >&2; exit 2 ;; esac
SCR=${SCR:-/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad}
D=$(cd "$(dirname "$0")" && pwd)          # this worktree's mirror/impl
RSD=$(cd "$D/../../restore/impl" && pwd)  # gin-restore's impl (read only)
CUDA=/usr/local/cuda-12.8
GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86"
JOBS=${JOBS:-8}
MIOUT=${MIOUT:-mi_$BR}
MIPOUT=${MIPOUT:-mip_$BR}
LAYER=$D/mi_layer_$BR.diff  # the branch's diff; the integration's is impl/mi_layer.diff
case "$BR" in int | fix) LAYER=$D/mi_layer.diff ;; esac
INFO=${INFO:-}
I5=$SCR/agent_rs_int     # gin-restore's integrated tree, build i5 (read only)
HK=$SCR/agent_gd/gin_hk  # gpu-detect's hk (read only; ident)
W=$SCR/agent_mi_$BR
OUT=$W/out
HOSTF=src/transport/net_ib/gdaki/gin_host_gdaki.cc
COMMON=src/include/nccl_device/gin/gdaki/gin_gdaki_device_host_common.h
DEVF=src/include/nccl_device/gin/gdaki/gin_gdaki.h
MI_FILES="$COMMON $DEVF $HOSTF"  # files the mirror layer may change (a new one: the main session updates this and PARALLEL.md)
I5_SUBJECT="gin-restore i5 (rs_layer.diff f005bb67)"
I5_DIFF=f005bb6794f549377025216599f06293
I5_LIB=4811f28f93294338812d8f83dafa8b61
I5_LIBP=be91b270155005827bfa0e79c527165c
MEMBER='  struct gdakiMiState mi;  // gin-mirror (impl/rs_mirror_api.h): the mirror layer'"'"'s per-context state'
IG() { git -C "$I5/nccl-src" "$@"; }
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
  [ -d "$W/nccl-src" ] && { echo "agent_mi_$BR already set up" >&2; return 0; }
  [ "$BR" != fix ] || { echo "the fix tree is a copy of agent_mi_int (see the usage); setup does not make it" >&2; exit 1; }
  [ "$(md5 "$RSD/rs_layer.diff")" = $I5_DIFF ] || { echo "restore/impl/rs_layer.diff is not f005bb67" >&2; exit 1; }
  case "$(IG log -1 --format=%s)" in "gpu-detect hk (libnccl 2913c777)") ;; *) echo "agent_rs_int head is not hk" >&2; exit 1 ;; esac
  [ "$(IG diff --diff-algorithm=histogram HEAD -- src | md5sum | cut -c1-32)" = $I5_DIFF ] ||
    { echo "agent_rs_int's working tree is not rs_layer.diff (i5)" >&2; exit 1; }
  [ "$(md5 "$I5/build/lib/libnccl.so.2.32.3")" = $I5_LIB ] || { echo "agent_rs_int/build is not i5" >&2; exit 1; }
  [ "$(md5 "$I5/build-rsp/lib/libnccl.so.2.32.3")" = $I5_LIBP ] || { echo "agent_rs_int/build-rsp is not i5" >&2; exit 1; }
  mkdir -p "$W"
  cp -a "$I5/nccl-src" "$I5/build" "$W/"
  cp -a "$I5/build-rsp" "$W/build-mip"
  rm -rf "$W/nccl-src/.git/worktrees"
  rewrite "$I5/build-rsp/" "$W/build-mip/" "$W/build-mip"
  rewrite "$I5/" "$W/" "$W/build-mip"
  rewrite "$I5/" "$W/" "$W/build"
  MG add -A src
  MG commit -qm "$I5_SUBJECT"
  [ "$(MG diff --diff-algorithm=histogram HEAD~1 HEAD -- src | md5sum | cut -c1-32)" = $I5_DIFF ] ||
    { echo "the i5 commit is not rs_layer.diff" >&2; exit 1; }
  [ "$(md5 "$W/build/lib/libnccl.so.2.32.3")" = $I5_LIB ] || { echo "the copied build is not i5" >&2; exit 1; }
  [ "$(md5 "$W/build-mip/lib/libnccl.so.2.32.3")" = $I5_LIBP ] || { echo "the copied build-mip is not i5's production" >&2; exit 1; }
  echo "setup: agent_mi_$BR at $(MG rev-parse --short HEAD) ($(MG log -1 --format=%s)); base libnccl i5 ${I5_LIB:0:8} / ${I5_LIBP:0:8}"
}
head_ok() {
  [ "$(MG log -1 --format=%s)" = "$I5_SUBJECT" ] || { echo "unexpected head commit in agent_mi_$BR" >&2; exit 1; }
}
files_ok() {  # the working tree changes MI_FILES only
  local f
  for f in $(MG diff --name-only HEAD -- src); do
    case " $MI_FILES " in *" $f "*) ;; *) echo "the working tree changes $f, which is not in MI_FILES" >&2; exit 1 ;; esac
  done
}
tree() {  # the branch's mirror diff on the working tree of the copy
  head_ok
  if MG diff --quiet HEAD -- src; then
    [ -f "$LAYER" ] || { echo "no changes in the tree and no impl/$(basename "$LAYER")" >&2; exit 1; }
    MG apply "$LAYER"
  fi
  files_ok
}

# ---- paste: the interface commit (PARALLEL.md's table), one python program, refused on a tree that has any block ----
paste() {
  head_ok
  local holdv2=0
  case "$BR" in host | int | fix) holdv2=1 ;; esac
  python3 - "$W/nccl-src" "$D" "$holdv2" "$MEMBER" <<'PY'
import sys
root, impl, holdv2, member = sys.argv[1], sys.argv[2], sys.argv[3] == '1', sys.argv[4]
COMMON = root + '/src/include/nccl_device/gin/gdaki/gin_gdaki_device_host_common.h'
HOSTF = root + '/src/transport/net_ib/gdaki/gin_host_gdaki.cc'
def lines(p): return open(p, encoding='utf-8').read().split('\n')
def block(p, begin, end, nth=1):  # the nth block from the line starting `begin` to the line starting `end`, inclusive
    L, out, k, on = lines(p), [], 0, False
    for l in L:
        if l.startswith(begin):
            k += 1
            on = k == nth
        if on: out.append(l)
        if on and l.startswith(end): return out
    sys.exit('no block %r in %s' % (begin, p))
def one(L, pred, what, start=0):
    idx = [i for i in range(start, len(L)) if pred(L[i])]
    if len(idx) != 1: sys.exit('%s: %d matches, want 1' % (what, len(idx)))
    return idx[0]
DL = block(impl + '/rs_mirror_api.h', '// ---- gin-mirror: device layout (begin', '// ---- gin-mirror: device layout (end')
DH = block(impl + '/rs_mirror_api.h', '// ---- gin-mirror: device helpers (begin', '// ---- gin-mirror: device helpers (end')
HA = block(impl + '/rs_mirror_api.h', '// ---- gin-mirror: host API (begin', '// ---- gin-mirror: host API (end')
SA = block(impl + '/rs_store_api.h', '// ---- gin-mirror: store API (begin', '// ---- gin-mirror: store API (end')
LA = block(impl + '/rs_log_api.h', '// ---- gin-restore (dev): log API (begin', '// ---- gin-restore (dev): log API (end')
HS = block(impl + '/rs_hold_api.h', '// ---- shared text (begin) ----', '// ---- shared text (end) ----')
C, H = lines(COMMON), lines(HOSTF)
if any('gin-mirror:' in l for l in C + H): sys.exit('the tree already has a gin-mirror block: use api')
# the device-host common header: the side table's definitions (diff 1168-1215) -> device layout; helpers after CsumBuf
a = one(C, lambda l: l.startswith('#define NCCL_GIN_RS_SIDE_MAGIC 0x33535352u'), 'RSS3 magic')
b = one(C, lambda l: '"the side table QP entry layout (the host reads it over the NIC by these offsets)");' in l,
        'QP entry assert', a)
old = '\n'.join(C[a:b + 1])
if 'struct ncclGinRsSide {' not in old or 'struct ncclGinRsQp {' not in old: sys.exit('unexpected side table range')
C[a:b + 1] = DL
c = one(C, lambda l: l.startswith('NCCL_GIN_RS_HD uint32_t ncclGinRsCsumBuf('), 'ncclGinRsCsumBuf')
e = c + 1
while C[e] != '}': e += 1
C[e + 1:e + 1] = DH
# the host file: the log API block v2, the mirror's host API after it, the member, the store API, the hold v2 text
a = one(H, lambda l: l.startswith('// ---- gin-restore (dev): log API (begin'), 'log API begin')
b = one(H, lambda l: l.startswith('// ---- gin-restore (dev): log API (end'), 'log API end')
H[a:b + 1] = LA
b = a + len(LA) - 1
H[b + 1:b + 1] = HA
m = one(H, lambda l: l.startswith('  struct gdakiRsLogHost* rsLog = nullptr;'), 'rsLog member')
H[m + 1:m + 1] = [member]
ends = [i for i, l in enumerate(H) if l == '// ---- shared text (end) ----']
begins = [i for i, l in enumerate(H) if l == '// ---- shared text (begin) ----']
if len(ends) != 2 or len(begins) != 2: sys.exit('the host file has not two shared-text blocks')
if not any('#define GDAKI_CKPT_MAGIC' in l for l in H[begins[1]:ends[1]]): sys.exit('the second block is not the ckpt text')
H[ends[1] + 1:ends[1] + 1] = SA
if holdv2:
    if not any('GIN_RESTORE_RS_HOLD_API_H_' in l for l in H[begins[0]:ends[0]]): sys.exit('the first block is not hold')
    H[begins[0]:ends[0] + 1] = HS
open(COMMON, 'w', encoding='utf-8').write('\n'.join(C))
open(HOSTF, 'w', encoding='utf-8').write('\n'.join(H))
print('paste: device layout %d, device helpers %d, host API %d, log API v2 %d, store API %d lines, the member; hold v2: %s'
      % (len(DL), len(DH), len(HA), len(LA), len(SA), 'yes' if holdv2 else 'no (v1 kept)'))
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
api() {
  head_ok
  same "device layout" '^// ---- gin-mirror: device layout [(]begin' '^// ---- gin-mirror: device layout [(]end' "$COMMON" "$D/rs_mirror_api.h"
  same "device helpers" '^// ---- gin-mirror: device helpers [(]begin' '^// ---- gin-mirror: device helpers [(]end' "$COMMON" "$D/rs_mirror_api.h"
  same "host API" '^// ---- gin-mirror: host API [(]begin' '^// ---- gin-mirror: host API [(]end' "$HOSTF" "$D/rs_mirror_api.h"
  same "store API" '^// ---- gin-mirror: store API [(]begin' '^// ---- gin-mirror: store API [(]end' "$HOSTF" "$D/rs_store_api.h"
  same "log API v2" '^// ---- gin-restore [(]dev[)]: log API [(]begin' '^// ---- gin-restore [(]dev[)]: log API [(]end' "$HOSTF" "$D/rs_log_api.h"
  [ "$(grep -cxF "$MEMBER" "$W/nccl-src/$HOSTF")" = 1 ] || { echo "api: the gdakiRecHost member line is not there once" >&2; exit 1; }
  local fence='/^\/\/ ---- shared text \(begin\) ----$/{on=1; k++} on && k==N{print} /^\/\/ ---- shared text \(end\) ----$/{on=0}'
  local o=$OUT/api; mkdir -p "$o"
  awk -v N=1 "$fence" "$W/nccl-src/$HOSTF" > "$o/hold_src.txt"
  awk -v N=2 "$fence" "$W/nccl-src/$HOSTF" > "$o/ckpt_src.txt"
  awk -v N=1 "$fence" "$D/rs_hold_api.h" > "$o/hold_v2.txt"
  awk -v N=1 "$fence" "$RSD/rs_hold_api.h" > "$o/hold_v1.txt"
  awk -v N=1 "$fence" "$D/rs_ckpt_api.h" > "$o/ckpt_v2.txt"
  case "$BR" in
    host | int | fix) cmp -s "$o/hold_src.txt" "$o/hold_v2.txt" || { echo "api: the hold shared text is not v2" >&2; exit 1; } ;;
    *) cmp -s "$o/hold_src.txt" "$o/hold_v1.txt" || { echo "api: the hold shared text is not v1 (only host pastes v2)" >&2; exit 1; } ;;
  esac
  cmp -s "$o/ckpt_src.txt" "$o/ckpt_v2.txt" || { echo "api: the checkpoint's shared text is not rs_ckpt_api.h's" >&2; exit 1; }
  echo "api: hold shared text $( [ "$BR" = host ] || [ "$BR" = int ] || [ "$BR" = fix ] && echo v2 || echo v1 ), checkpoint shared text v1 (= v2's)"
  cat > "$o/headers.cc" <<'CC'
#include <stddef.h>
#include <stdint.h>
typedef enum { ncclSuccess = 0, ncclSystemError = 2, ncclInternalError = 3, ncclInvalidUsage = 5 } ncclResult_t;
typedef struct {
  unsigned int magic, nqp, qpn[64], remoteQpn[64], sqPsn[64];
  unsigned long long epochWqes[64];
} ncclGinRecoverToken_t;
#include "rs_hold_api.h"
#include "rs_mirror_api.h"
#include "rs_log_api.h"
#include "rs_ckpt_api.h"
#include "rs_store_api.h"
#include "rs_spare_api.h"
int main() { return 0; }
CC
  g++ -std=c++17 -Wall -Wextra -Werror -Wno-unused-function -fsyntax-only -I"$D" "$o/headers.cc"
  g++ -std=c++17 -Wall -Wextra -Werror -Wno-unused-function -DGDAKI_MI_API_NO_ENTRY_DECLS -DGDAKI_HOLD_API_NO_ENTRY_DECLS \
    -fsyntax-only -I"$D" "$o/headers.cc"
  echo "api: the six headers compile together (g++ -fsyntax-only, with and without the entry-point declarations)"
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
mi() {
  [ "$BR" != test ] || { echo "the test branch builds no library (PARALLEL.md)" >&2; exit 1; }
  tree; fresh "$OUT/$MIOUT"
  devsync "$W/build"
  MKS "$W/build"
  devdone "$W/build"
  cp "$W/build/lib/libnccl.so.2.32.3" "$OUT/$MIOUT/"
  echo "$MIOUT libnccl $(md5 "$OUT/$MIOUT/libnccl.so.2.32.3")"
}
mip() {
  [ "$BR" != test ] || { echo "the test branch builds no library (PARALLEL.md)" >&2; exit 1; }
  tree; fresh "$OUT/$MIPOUT"
  devsync "$W/build-mip"
  CXXFLAGS=-DNCCL_GIN_TS_PRODUCTION MKS "$W/build-mip"
  devdone "$W/build-mip"
  cp "$W/build-mip/lib/libnccl.so.2.32.3" "$OUT/$MIPOUT/"
  diff -r -q "$W/build/include" "$W/build-mip/include" > /dev/null ||
    { echo "the production build's headers differ from the research build's" >&2; exit 1; }
  echo "$MIPOUT libnccl $(md5 "$OUT/$MIPOUT/libnccl.so.2.32.3")"
}

cut1() {  # cut1 <out> <begin regex> <end regex>: a region of the host file, which must exist
  region "$2" "$3" "$W/nccl-src/$HOSTF" > "$1"
  [ -s "$1" ] || { echo "no region '$2' in $HOSTF" >&2; exit 1; }
}
GXX() { nice -n 19 g++ -std=c++17 -O1 -g -Wall -Wextra -Werror -Wno-unused-function -pthread -fsanitize=address,undefined "$@"; }
unit1() {  # unit1 <branch>: impl/mi_unit_<branch>.cc against the working tree's pure regions
  local b=$1 o=$OUT/unit_$1
  [ -f "$D/mi_unit_$b.cc" ] || { echo "no impl/mi_unit_$b.cc" >&2; exit 1; }
  mkdir -p "$o"
  # gin-restore's pure regions (build_rs.sh's names), for the tests that need them
  cut1 "$o/rs_pure.inc" '^// ---- gin-restore: pure functions [(]begin' '^// ---- gin-restore: pure functions [(]end'
  cut1 "$o/rs_dev_pure.inc" '^// ---- gin-restore [(]dev[)]: log, suppress and replay, pure [(]begin' \
       '^// ---- gin-restore [(]dev[)]: log, suppress and replay, pure [(]end'
  cut1 "$o/rs_hold_pure.inc" '^// ---- gin-restore hold: pure functions [(]begin' '^// ---- gin-restore hold: pure functions [(]end'
  cut1 "$o/rs_ckpt_pure.inc" '^// ---- gin-restore ckpt: pure functions [(]begin' '^// ---- gin-restore ckpt: pure functions [(]end'
  cut1 "$o/rs_spare_pure.inc" '^// ==== gin-restore [(]rs, work package 8, spare branch[)]: pure functions [(]begin' \
       '^// ==== gin-restore [(]rs, work package 8, spare branch[)]: pure functions [(]end'
  # this branch's own pure region (PARALLEL.md: "gin-mirror (<branch>): pure"); the test branch has none in the library
  if [ "$b" != test ]; then
    cut1 "$o/mi_pure_$b.inc" "^// ---- gin-mirror [(]$b[)]: pure [(]begin" "^// ---- gin-mirror [(]$b[)]: pure [(]end"
  fi
  GXX -I"$o" -I"$D" -I"$W/nccl-src/src/include" "$D/mi_unit_$b.cc" -o "$o/mi_unit_$b"
  "$o/mi_unit_$b"
}
unit() {
  head_ok
  case "$BR" in int | fix) local b; for b in dev host store spare; do unit1 "$b"; done ;; *) unit1 "$BR" ;; esac
}
ident() {
  case "$BR" in dev | int | fix) ;; *) echo "ident is the dev branch's and the integration's" >&2; exit 1 ;; esac
  [ -x "$D/exact_cmp_mi.sh" ] && [ -x "$D/ff_cmp_mi.sh" ] ||
    { echo "impl/exact_cmp_mi.sh and impl/ff_cmp_mi.sh are not written yet (the dev branch's, PARALLEL.md)" >&2; exit 1; }
  W="$W" HK="$HK" I5="$I5" LIB="$MIOUT" "$D/ff_cmp_mi.sh" "$MIOUT"
  W="$W" HK="$HK" I5="$I5" LIB="$MIOUT" "$D/exact_cmp_mi.sh" "$MIOUT"
}
mkdiff() {
  head_ok; files_ok
  local n
  for n in $(MG ls-files --others --exclude-standard -- src); do MG add -N -- "$n"; done
  MG diff --diff-algorithm=histogram HEAD -- src > "$LAYER"
  MG apply --check -R "$LAYER"
  echo "diff: impl/$(basename "$LAYER") $(md5 "$LAYER") $(wc -l < "$LAYER") lines ($(MG diff --name-only HEAD -- src | tr '\n' ' '))"
}
info() {
  {
    echo "built=$(date '+%F %T') host=$(hostname -s) nvcc=$("$CUDA/bin/nvcc" --version | tail -1) g++=$(g++ -dumpfullversion)"
    echo "branch $BR; base: agent_mi_$BR head $(MG rev-parse --short HEAD) ($(MG log -1 --format=%s));" \
         "i5 commit diff md5 $(MG diff --diff-algorithm=histogram HEAD~1 HEAD -- src | md5sum | cut -c1-32)" \
         "(rs_layer.diff $(md5 "$RSD/rs_layer.diff"))"
    echo "working tree: $(MG diff --name-only HEAD -- src | tr '\n' ' ')"
    echo "working tree diff md5 $(MG diff --diff-algorithm=histogram HEAD -- src | md5sum | cut -c1-32) (histogram)"
    [ -f "$LAYER" ] && echo "$(basename "$LAYER") $(md5 "$LAYER") $(wc -l < "$LAYER") lines"
    for b in "$OUT"/*/libnccl.so.2.32.3; do [ -f "$b" ] && echo "$(basename "$(dirname "$b")") libnccl $(md5 "$b")"; done
    echo "include_digest build $(cd "$W/build/include" && find . -type f | LC_ALL=C sort | xargs md5sum | md5sum | cut -c1-32)"
    echo "include_digest i5 $(cd "$I5/build/include" && find . -type f | LC_ALL=C sort | xargs md5sum | md5sum | cut -c1-32)"
    for f in rs_mirror_api.h rs_store_api.h rs_log_api.h rs_hold_api.h rs_ckpt_api.h rs_spare_api.h PARALLEL.md \
             build_mi.sh mi_unit_dev.cc mi_unit_host.cc mi_unit_store.cc mi_unit_spare.cc; do
      [ -f "$D/$f" ] && echo "$f $(md5 "$D/$f")"
    done
  } > "${INFO:-$OUT/build_info.txt}"
  cat "${INFO:-$OUT/build_info.txt}"
}
case "$STAGE" in
  setup) setup ;;
  paste) paste ;;
  api) api ;;
  mi) mi ;;
  mip) mip ;;
  unit) unit ;;
  ident) ident ;;
  diff) mkdiff ;;
  info) mkdir -p "$OUT"; info ;;
  *) echo "unknown stage $STAGE" >&2; exit 2 ;;
esac
