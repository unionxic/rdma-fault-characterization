#!/usr/bin/env bash
# build_launcher.sh - build the gin-control launcher and its CPU unit test, then run the unit test.
#
# usage: OUT=<dir> build_launcher.sh [all|build|unit|clean]
#   OUT    output directory (default ${TMPDIR:-/tmp}/gin-launcher-build-$USER); nothing is written into this folder
#   build  the program gin_launcher (with the verbs transport when <infiniband/verbs.h> exists, else -DGL_NO_VERBS:
#          a program that refuses to start), the header checks (C11 and C++17), the unit test binary
#   unit   run the unit test (ASan + UBSan) in $OUT/work; its log is $OUT/unit.log
#   all    build, then unit (the default)
#
# Safety: this machine may be a cluster node. The script never runs gin_launcher, never opens a verbs device or a GPU,
# never runs anything that uses libibverbs or CUDA at run time. Linking gin_launcher against libibverbs is compile time
# only. The unit test uses an in-process transport and forked children of its own.
set -euo pipefail
D="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${OUT:-${TMPDIR:-/tmp}/gin-launcher-build-${USER:-$(id -un)}}"
CC="${CC:-gcc}"
CXX="${CXX:-g++}"
WARN=(-Wall -Wextra -Werror)
SAN=(-O1 -g -fno-omit-frame-pointer -fsanitize=address,undefined -fno-sanitize-recover=undefined)
VERBS_H=/usr/include/infiniband/verbs.h

build() {
  mkdir -p "$OUT"
  echo "== header: C11 and C++17, self-contained"
  printf '#include "launcher_msg.h"\n#include "launcher_transport.h"\n#include "gin_launcher.h"\nint main(void){return 0;}\n' >"$OUT/hdr.c"
  "$CC" -std=c11 "${WARN[@]}" -I"$D" -fsyntax-only "$OUT/hdr.c"
  "$CXX" -std=c++17 "${WARN[@]}" -I"$D" -x c++ -fsyntax-only "$OUT/hdr.c"
  echo "== gin_launcher (program)"
  if [ -f "$VERBS_H" ]; then
    echo "   $VERBS_H found: verbs transport built (not executed here)"
    "$CC" -std=c11 -O2 -g "${WARN[@]}" -I"$D" "$D/gin_launcher.c" "$D/launcher_transport_verbs.c" -libverbs \
      -o "$OUT/gin_launcher"
  else
    echo "   $VERBS_H missing: built with -DGL_NO_VERBS (the program refuses to start)"
    "$CC" -std=c11 -O2 -g "${WARN[@]}" -DGL_NO_VERBS -I"$D" "$D/gin_launcher.c" -o "$OUT/gin_launcher"
  fi
  "$CC" -std=c11 -O2 "${WARN[@]}" -DGL_PRODUCTION -I"$D" -DGL_NO_VERBS -c "$D/gin_launcher.c" -o "$OUT/gin_launcher_prod_noverbs.o"
  echo "== launcher_unit (ASan, UBSan)"
  "$CC" -std=c11 "${SAN[@]}" "${WARN[@]}" -DGL_NO_MAIN -I"$D" -c "$D/gin_launcher.c" -o "$OUT/gin_launcher_core.o"
  "$CXX" -std=c++17 "${SAN[@]}" "${WARN[@]}" -pthread -I"$D" "$D/launcher_unit.cc" "$OUT/gin_launcher_core.o" \
    -o "$OUT/launcher_unit"
  (cd "$OUT" && md5sum gin_launcher launcher_unit) | tee "$OUT/build.md5"
}

unit() {
  [ -x "$OUT/launcher_unit" ] || build
  rm -rf "$OUT/work"
  mkdir -p "$OUT/work"
  chmod 0700 "$OUT/work"
  echo "== run launcher_unit (log $OUT/unit.log; the launcher's own lines in $OUT/work/launcher_unit.log)"
  set +e
  ASAN_OPTIONS=detect_leaks=1:abort_on_error=0 UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1 \
    "$OUT/launcher_unit" "$OUT/work" >"$OUT/unit.log" 2>&1
  local rc=$?
  set -e
  tail -n 30 "$OUT/unit.log"
  echo "== launcher_unit exit $rc"
  return $rc
}

case "${1:-all}" in
  build) build ;;
  unit) unit ;;
  all) build; unit ;;
  clean) rm -rf "$OUT" ;;
  *) echo "usage: OUT=<dir> $0 [all|build|unit|clean]" >&2; exit 2 ;;
esac
