#!/usr/bin/env bash
# batch.sh - run a list of nrc_devx trials (one per line of a spec file) and append each
# trial's SUMMARY line to <outdir>/summary.txt. Run inside ../../common/cluster_run.sh.
#
#   batch.sh <spec> <outdir>
# spec lines: <tag> <fault> <preset> <sets|-> <observe_ms> [extra requester args...]
#             blank lines and lines starting with # are skipped
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SPEC=$1; OUT=$2
mkdir -p "$OUT"
cp "$SPEC" "$OUT/$(basename "$SPEC").$(date +%H%M%S)"
while read -r tag fault preset sets obs extra; do
  case "$tag" in ''|\#*) continue ;; esac
  # shellcheck disable=SC2086
  line=$(OBSERVE_MS=$obs bash "$HERE/run_one.sh" "$tag" "$OUT" "$fault" "$preset" "$sets" -- $extra </dev/null)
  echo "$line" | tee -a "$OUT/summary.txt"
  case "$line" in *NO_SUMMARY*) echo "batch aborted after $tag (no SUMMARY)"; exit 5 ;; esac
done < "$SPEC"
echo "batch done: $SPEC"
