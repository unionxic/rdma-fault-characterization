#!/usr/bin/env bash
# Hold F: in-flight local faults (exactly-once of the signal ADD when the responder executed it).
set -u
R=${1:?resultsdir}
cd "$(dirname "$0")"
bash batch.sh "$R/runs" f1g0_b 30
