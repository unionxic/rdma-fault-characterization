#!/usr/bin/env bash
# Third-review validation pass: the post-commit-point stall cells, the monitor-through-abort cells, and a
# short regression, each once.
set -u
L=${1:?logdir}
cd "$(dirname "$0")"
for c in late_ok_b late_fail_b abortmon_b abortmonfull_b abortmid_b split_b f1_b none_b off_f1_b; do bash batch.sh "$L" $c 1; done
