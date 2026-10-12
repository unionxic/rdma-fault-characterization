#!/usr/bin/env bash
# obj_cmp.sh <hk build dir> <rs build dir> <out dir>: every device object (obj/device/**.o, obj/diagnostics/device/**.o) of
# the rs build against hk's: identical SASS, or every differing instruction a GPU-context-stride immediate (sass_cmp.py).
set -u
HKB=$1; RSB=$2; O=$3; CU=/usr/local/cuda-12.8/bin
mkdir -p "$O"
same=0; strideOnly=0; other=0; missing=0
while IFS= read -r rel; do
  h="$HKB/$rel"; r="$RSB/$rel"
  [ -f "$h" ] || { echo "MISSING in hk: $rel"; missing=$((missing+1)); continue; }
  k=$(echo "$rel" | tr '/' '_')
  "$CU/cuobjdump" -sass "$h" > "$O/${k}_hk.sass" 2>/dev/null
  "$CU/cuobjdump" -sass "$r" > "$O/${k}_rs.sass" 2>/dev/null
  if cmp -s "$O/${k}_hk.sass" "$O/${k}_rs.sass"; then same=$((same+1)); rm -f "$O/${k}_hk.sass" "$O/${k}_rs.sass"; continue; fi
  if (cd "$O" && python3 "$(dirname "$0")/sass_cmp.py" "$k" > "$k.cmp" 2>&1); then strideOnly=$((strideOnly+1)); echo "stride only: $rel: $(tail -1 "$O/$k.cmp")"
  else other=$((other+1)); echo "OTHER DIFFERENCE: $rel"; tail -3 "$O/$k.cmp"; fi
done < <(cd "$RSB" && find obj/device obj/diagnostics/device -name '*.o' | LC_ALL=C sort)
echo "device objects: identical SASS $same, stride-immediate differences only $strideOnly, other $other, missing in hk $missing"
