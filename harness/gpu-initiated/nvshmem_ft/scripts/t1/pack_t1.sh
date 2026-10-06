#!/usr/bin/env bash
# pack_t1.sh <results dir> <set> [<set> ...] - pack per-trial directories to <set>.tar.xz (after
# rows_t1.py has produced the CSVs). The management addresses are replaced by the documentation
# addresses first (192.0.2.193 / .194), as the git filter does for text files, since an archive is
# binary to git. The directory is removed only after the archive lists the same number of files.
set -eu
# The real addresses live outside the repository (see docs/GIT_WORKFLOW.md).
. "${MGMT_ENV:-$HOME/.config/rdma-error/mgmt.env}"
ea=${MGMT_A//./\\.}; eb=${MGMT_B//./\\.}
prefix=${MGMT_A%.*}.; eprefix=${prefix//./\\.}
R=$1; shift
cd "$R"
for s in "$@"; do
  [ -d "$s" ] || { echo "no dir $s"; continue; }
  find "$s" -type f -print0 | xargs -0 sed -i -e "s/$ea/192.0.2.193/g" -e "s/$eb/192.0.2.194/g"
  n=$(find "$s" -type f | wc -l)
  tar -cJf "$s.tar.xz" "$s"
  m=$(tar -tJf "$s.tar.xz" | grep -vc '/$')
  if [ "$n" = "$m" ] && ! tar -xJOf "$s.tar.xz" | grep -q "$eprefix"; then
    rm -rf "$s"; echo "packed $s ($n files)"
  else
    echo "pack check failed for $s ($n files, $m in archive); directory kept"
  fi
done
