#!/usr/bin/env bash
# sass_size_t1.sh <driver> [<driver> ...] - SASS instruction count (sm_75) of the device functions on
# the put + signal + quiet path, per driver binary (built by build_driver_t1.sh; the device library is
# linked statically, so the count covers the library code the application runs).
set -eu
CUDA_HOME=${CUDA_HOME:-/usr/local/cuda-12.8}
for b in "$@"; do
  echo "== $b"
  "$CUDA_HOME/bin/cuobjdump" -sass -arch sm_75 "$b" 2>/dev/null |
    awk '/Function : /{f=$3} /^ +\/\*[0-9a-f]+\*\/ /{c[f]++} END{for (k in c) print c[k], k}' |
    grep -E 'put_signal_dispatch|transfer_quiet|amo_nonfetch|lat_kernel' | sort -rn
done
