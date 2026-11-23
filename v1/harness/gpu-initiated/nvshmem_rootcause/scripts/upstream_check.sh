#!/usr/bin/env bash
# upstream_check.sh - is the CPU-proxy SQ doorbell-record bug still in upstream NVSHMEM? (2026-09-25)
# Fetches every upstream branch and tag into remote-tracking refs only (the checked-out tree used
# by the builds is not touched), then greps the proxy doorbell-record lines in each ref.
#   upstream_check.sh [<nvshmem clone>]  > results/20260925_dbrk/upstream/upstream_check.txt
set -u
REPO=${1:-/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/ibgda/nvshmem}
F=src/modules/transport/ibgda/ibgda.cpp
cd "$REPO" || exit 2
echo "# $(date '+%F %T %Z')  repo=$REPO"
echo "# checked-out HEAD (unchanged): $(git rev-parse HEAD) $(git log -1 --format='%ci %s' HEAD)"
echo "# git status: $(git status --porcelain | wc -l) modified/untracked paths"
echo; echo "## git ls-remote origin (heads, tags)"
timeout 60 git ls-remote --heads --tags origin
timeout 300 git fetch -q --tags origin '+refs/heads/*:refs/remotes/origin/*' 2>&1
echo; echo "## per ref: proxy doorbell-record lines (word 0 bug = 'dbr_offset * sizeof(__be32)'; correct = 'dbr_offset + sizeof(__be32)' / '+ sizeof(__be32)' continuation)"
for r in $(git for-each-ref --format='%(refname:short)' refs/remotes/origin refs/tags | grep -v '/HEAD$'); do
  printf '%-40s %s %s\n' "$r" "$(git rev-parse --short "$r^{commit}")" "$(git log -1 --format='%ci' "$r")"
  git grep -n -e 'dbr_offset \* sizeof' -e 'dbr_offset + sizeof' -e 'dbr_offset +$' "$r" -- "$F" 2>/dev/null | sed 's/^/    /'
done
echo; echo "## commit that changed the proxy line (pickaxe over all refs)"
git log --all --format='%h %ci %an | %s' -S'dbr_offset * sizeof(__be32)' -- "$F"
echo; echo "## the change itself in ce9d487 (proxy + GPU handler hunks)"
git show ce9d487 -- "$F" | grep -n -B2 -A2 'dbr_offset \* sizeof\|dbr_offset +$\|dbr_offset + sizeof'
echo; echo "## v3.4.5-0 proxy (last release before the change)"
git show "v3.4.5-0:$F" | grep -n -B1 -A1 'dbr_offset +$'
echo; echo "## GitHub issues/PRs mentioning the topic (search API)"
for q in dbr doorbell dbrec NIC_HANDLER cpu_host_memory "error CQE" "ibgda_rc_progress" "PeerMappingOverride"; do
  echo "q=$q"
  gh api -X GET search/issues -f q="repo:NVIDIA/nvshmem $q" --jq '.items[] | "    #\(.number) \(.state) \(.created_at[:10]) \(.title)"' 2>&1
done
echo; echo "## PRs whose ibgda.cpp patch touches dbrec/dbr_offset"
for n in $(gh pr list -R NVIDIA/nvshmem --state all --limit 500 --json number --jq '.[].number'); do
  hp=$(gh api "repos/NVIDIA/nvshmem/pulls/$n/files" --paginate --jq '.[] | select(.filename=="'"$F"'") | (.patch != null)' 2>/dev/null)
  [ -z "$hp" ] && continue
  if [ "$hp" = true ]; then
    p=$(gh api "repos/NVIDIA/nvshmem/pulls/$n/files" --paginate --jq '.[] | select(.filename=="'"$F"'") | .patch' 2>/dev/null)
    echo "    PR #$n touches ibgda.cpp; dbrec/dbr_offset lines in patch: $(grep -c 'dbrec\|dbr_offset' <<< "$p")"
  else
    # patch too large for the API: fetch the PR head into a remote-tracking ref and grep the file
    git fetch -q origin "+refs/pull/$n/head:refs/remotes/origin/pr/$n" 2>/dev/null
    echo "    PR #$n touches ibgda.cpp; patch too large for the API; its head has:"
    git grep -n -e 'dbr_offset \* sizeof' -e 'dbr_offset + sizeof' -e 'dbr_offset +$' "origin/pr/$n" -- "$F" | sed 's/^/        /'
  fi
done
echo "# done"
