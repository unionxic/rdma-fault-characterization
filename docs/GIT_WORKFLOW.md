# How this repository is run

Follows common research-software practice:
- [The Turing Way](https://book.the-turing-way.org/reproducible-research/vcs/vcs-workflow-branches/):
  single-purpose branches merged through pull requests;
- [Good Enough Practices](https://journals.plos.org/ploscompbiol/article?id=10.1371%2Fjournal.pcbi.1005510):
  raw data kept as generated and stored outside the history;
- [Conventional Commits](https://www.conventionalcommits.org/) for messages.

## Branches

- **`master`** is the only long-lived branch and the public record. It is never force-pushed or
  rewritten; a GitHub ruleset blocks both.
- **Everything else happens on a short-lived branch.** It is merged with a pull request, using
  "Rebase and merge", then deleted. Rebase keeps each commit's author (the noreply address) and
  message. A web squash would record the account's primary e-mail as the author.

| prefix | for | example |
|---|---|---|
| `feat/` | new code or a new experiment tool | `feat/evrec` |
| `fix/` | a bug fix | `fix/harness-auto-recoverable-label` |
| `exp/` | an experiment campaign: plan, scripts, results tables | `exp/propagation-campaign` |
| `data/` | derived tables, data manifests | `data/release-20261006` |
| `docs/` | write-ups only | `docs/results-refresh` |
| `chore/` | repository housekeeping | `chore/git-workflow` |
| `wip/` | unfinished work, pushed daily so nothing lives only on one disk; opened as a draft PR | `wip/gin-s2` |

## Commits

- One logical change per commit.
- Subject line `type(scope): summary`, at most 72 characters, imperative mood.
  - Types: `feat`, `fix`, `exp`, `data`, `docs`, `test`, `refactor`, `chore`.
  - Scopes are directory names: `harness`, `gin`, `nvshmem`, `nvshmem-ft`, `propagation`, ...
- The body says why, and names the evidence (result folder, counts).
- Author: `187358711+unionxic@users.noreply.github.com`. No tool or co-author trailers.

## What is tracked

`.gitignore` is an allow-list. Git tracks:
- code: `.c .h .cu .cc .py .sh .diff`, `Makefile`;
- docs: `.md`;
- small derived data: `.csv`; `.txt .json .spec` outside result folders.

Raw data is not in the history. That means logs, per-trial `.kv/.meta` files, `.out/.console`,
archives, and any `.txt/.json` inside `results/`. Each data release is a GitHub Release
`data-YYYYMMDD`:
- one `.tar.xz` per result folder;
- a `SHA256SUMS` file;
- `DATA.md` in the repository, mapping folders to assets.

Raw data stays as generated. Management IPs are replaced by `192.0.2.x` before packing, as in the
history.

## Management addresses

Commits store `192.0.2.193/194`; working trees keep the real addresses. Every clone needs the
local filter once, with the real addresses in place of `<A>` and `<B>`. The addresses are never
written into the repository:

```
git config filter.mgmtip.clean  "sed -e 's/<A>/192.0.2.193/g' -e 's/<B>/192.0.2.194/g'"
git config filter.mgmtip.smudge "sed -e 's/192\.0\.2\.193/<A>/g' -e 's/192\.0\.2\.194/<B>/g'"
printf '%s filter=mgmtip\n' '*.sh' '*.py' '*.md' '*.txt' '*.csv' '*.json' '*.spec' '*.c' '*.h' '*.cc' '*.cu' '*.diff' > .git/info/attributes
```

Scripts that must match the real addresses as patterns read them at run time from
`~/.config/rdma-error/mgmt.env`, which defines `MGMT_A` and `MGMT_B`. That file is local and is
never committed. Examples: `nvshmem_ft/scripts/t1/pack_t1.sh` and
`nvshmem_rootcause/official380/redact.py`.

Before every push, a grep of the index (`git grep --cached`) for the real prefix must print
nothing, in any spelling, escaped or not.

## Tags and releases

| tag | meaning |
|---|---|
| `prereg/<study>-v<n>` | annotated tag on the commit that fixes a pre-registered plan, before any run. Later deviations go to that study's `DEVIATIONS.md`. |
| `data-YYYYMMDD` | a raw-data release (see above) |
| `vX.Y` | a snapshot cited in a report or paper; can be archived on Zenodo for a DOI |

A claim in a report cites a tag or a commit, never a branch.

## Backups

`git bundle create ~/rdma-error-backup-<date>/repo.bundle --all` before any operation that moves
refs. The history before this workflow (local branch `full`, with the raw data in it) is kept as
the local branch `archive/full-20261006` and as `~/rdma-error-backup-20261006/repo_full_20261006.bundle`.
