#!/usr/bin/env bash
# Pack each per-trial result directory to <dir>.tar.xz (as the S1 results) and check the archive round-trips.
# usage: pack.sh <resultsdir>
set -eu
cd "${1:?resultsdir}"
for d in */; do
  d=${d%/}
  tar cJf "$d.tar.xz" "$d"
  a=$(cd "$d" && find . -type f -exec md5sum {} + | sort -k2 | md5sum)
  t=$(mktemp -d); tar xJf "$d.tar.xz" -C "$t"; b=$(cd "$t/$d" && find . -type f -exec md5sum {} + | sort -k2 | md5sum); rm -rf "$t"
  [ "$a" = "$b" ] || { echo "round-trip mismatch for $d" >&2; exit 1; }
  rm -rf "$d"; echo "packed $d ($(du -h "$d.tar.xz" | cut -f1))"
done
