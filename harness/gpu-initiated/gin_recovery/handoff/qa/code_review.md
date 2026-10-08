# gin-handoff: code review after the main run

Reviewer: an independent agent, 2026-10-09, after hold H1–H4 and the refill hold (`results/20261009/`). Read-only review: no
program, script or cluster command was run; files were read directly, the tag was read with `git show <tag>:<path>`
(no clean filter), and checksums were taken with `md5sum`/`sha256sum`.

Marks: `[source]` read in code, `[measured]` read by this reviewer from the raw per-trial files (`*_meta.txt`, `*_r*.kv`,
`*_r*.log`, `hold_*.out`), not copied from `SCORE.md`, `[inferred]`, `[unverified]`.

Paths: the library tree is `agent_ts2hf/nccl-src` in the session scratch (called "tree" below); `hf_layer.diff`, `cells.sh`,
`hold.sh`, `chain.sh`, `rows_hf.py`, `score.py`, `predictions.csv` are in this folder; the driver is `../gin_ts2.cu`; the
runner is `../harden/run_trial_hd.sh`.

## Verdict

- **Measured results: nothing found that biased or invalidated them.** No blocker, no high finding. The 115 scored trials
  and runs (one trial excluded for a port bind failure, outcome-independent) can stand as scored.
- **The shrink change is safe for what it claims.** An aborting shrink cannot get past the parent's error when any GIN error
  raise named a peer that is not excluded, or named no peer; every refusal returns exactly the stock value; the child of an
  aborting shrink shares nothing with the parent. All uncertain cases fail closed (stock answer).
- Two medium findings limit **what the evidence supports**, not the scoring: the hand-off rule tests the peer an error was
  *raised for*, not the peer that *caused* it (M1), and the child-isolation check covers only a child without GIN state (M2).
- Low findings: the rendezvous port range, stop rules that are not automated, two rules whose precondition is not encoded
  (it held in the data), the probe's time resolution, the drifting per-node clock offset, and wording.

## What was checked

| Area | How | Result |
|---|---|---|
| Layer vs tree | `hf_layer.diff` read against tree `src/init.cc`, `src/transport/net_ib/gdaki/gin_host_gdaki.cc`, `src/gin/gin_host.cc` | the diff is what the tree contains; md5 `a2bcaf69…` and `882dfff7…` equal section 5 `[measured]` |
| Every GIN error raise | grep of all writers of `q4->hasError` and of every `queryLastError` | 3 setters + the QUERY_QP query, all noted before the flag `[source]` |
| Driver change | `diff` of `../gin_ts2.cu` against `prereg/gin-harden-v1` (282 diff lines) | as designed (details under "Focus 2") |
| Post-tag changes | `cmp` of each working file against `git show prereg/gin-handoff-v1:<path>` | none that matter (see "Focus 5") |
| Spot checks | kv/log/meta of all 116 trials for exit codes, `left`, ports; kv of the shrink, devComm-first and GPU-full cells | consistent with `SCORE.md` |
| Bundles on rain | `md5sum $HOME/gi-bundle/gin_ts2/{hf,hfp,hd,hdp}/*` | equal to section 5 `[measured]`; sunny `[unverified]` (only `deploy_check.txt` 04:51) |

## Findings

### Blocker

None.

### High

None.

### Medium

**M1. The hand-off rule checks "raised for", not "caused by".**
- Where: tree `gin_host_gdaki.cc:4139–4140` (`gdakiTsDecline` notes the declined peer), `init.cc:3620–3633` (the rule);
  `hf_layer.diff:164–179, 234`.
- What: a decline always notes the peer whose QPs it declines. Many decline reasons are local to the declining rank
  `[source]`: "commit failed" (4419, 4749), "QUERY_QP failed" (4619), "prepare declined" (4605), the replay plan
  (`rs.detail`, 4609), escalation (4568), a firmware-phase check (4593, 4606, 4620, 4750), and a device-state copy that misses
  `NCCL_GIN_TS_COPY_MS` inside a round. Inside a round the watchdog surfaces (no-peer note) only after
  `NCCL_GIN_TS_ROUND_MS` (25 s; `gdakiTsWatchdog`, 2851–2852), so a 2 s copy timeout declines with a peer and no no-peer
  note before it.
- Failure scenario: 3 or more ranks; rank A's helper declines peer P for a local reason (its own GPU copy stalled, its own
  firmware command failed, a REM_ACCESS from A's own bad address). The application excludes P. The hand-off passes and logs
  "raised for rank(s) P, all excluded", while the cause stays on rank A.
- In this study the GPU-full cell was kept only because the watchdog surfaced first: `hf/hf_hog_f1_b_n1_r0.log` has the
  surface at mono 2647289070.312, the decline of peer 1 ("the watchdog surfaced a fault earlier") at 2647290072.716 and the
  keep line "(a GIN error was raised without a peer)" at 2647290073.099 `[measured]`.
- Effect on results: none. With 2 ranks the only peer is rank 1, and no scored rule depends on the cause. Effect on claims:
  the conclusion and README should say the error was "raised for" the excluded ranks, not "came from" them. A later version
  could note local-cause declines as no-peer raises.

**M2. The child-isolation check covers only a child without GIN state.**
- Where: driver `../gin_ts2.cu:1280–1312`; tree `init.cc:4067` (GIN is queried only when `ginState.connected`),
  `enqueue/enqueue.cc:3325–3336` ("Single-rank collectives execute immediately").
- What: the driver never creates a devComm on the child, so the child's GIN state is never connected and
  `ncclCommGetAsyncError(child)` never reads GIN. The 1-rank allreduce is a local copy. "No async error on the child" can
  fail only if the child shared the parent's resources (then the shared, connected GIN state would report the error) or its
  own init failed. The rule is not vacuous for sharing, which is the mechanism the layer relies on (`init.cc:3701–3703`,
  `shareResources` is false for `NCCL_SHRINK_ABORT`; `commAlloc` value-initializes a new `ncclSharedResources`).
- Effect on results: the scored predictions about the 1-rank communicator (S1–S3, S6, S8) hold as written. The conclusion
  should say "a child without GIN contexts gets no parent error" and not claim that a child that opens its own devComm (the
  real GIN use) works after a hand-off: that was not run `[unverified]`.

### Low

**L1. The rendezvous port is drawn inside rain's ephemeral range.**
- Where: `../harden/run_trial_hd.sh:41` (`PORT=46000 + (PID + RANDOM) % 3000`); driver `../gin_ts2.cu:847–853`.
- `[measured]`: rain `ip_local_port_range` is 32768–60999, `ip_local_reserved_ports` is empty; the 116 trials used ports
  46004–48955 (from `hold_*.out`). `SO_REUSEADDR` does not help against a LISTEN socket or an ephemeral socket bound without
  it.
- What happened: `hf/hf_hogpre_f1_b_n1` failed to bind (rank 0 log "bind: Address already in use", `r0rc=1`); its rank 1
  ran into its 45 s global watchdog (`r1rc=7`; `wall_s=0.0` measures rank 0 only). `score.py:94` excludes it; the refill
  `n6` ran in hold `fill` (06:17:49–06:17:58) with the same outcome as `n2`–`n5`.
- Effect on results: none. The failure precedes NCCL init and does not depend on the cell. Side effect: the failed trial's
  rank 1 kept connecting to a rain port this study did not own (another process's listener would have accepted it; rank 1
  only reads). Fix for later studies: draw from a range outside 32768–60999 (checked free), or let rank 0 bind port 0 and
  pass the port to rank 1.

**L2. Three stop/exclusion rules of section 8 are not automated.**
- "`left > 0` in two trials in a row: stop" is in no script (`hold.sh`, `cells.sh`, `chain.sh`).
- "A configuration check failure stops the block": `score.py:117–146` only labels the trial `config_*` and leaves it
  unscored; nothing stops the hold.
- "Refills over 50% of the plan: the cell key is 자료 부족": no such rule in `score.py`.
- Effect: none. `left=0` in 116/116 metas, no trial got a `config_*` status, one refill against 5 planned in one cell
  (20%) `[measured]`. `hold.sh:83–99` does write the mlx5, iptables and CUDA stop files, and `chain.sh:13` honours them.

**L3. Two rules do not encode that the parent had an error before the shrink.**
- `predictions.csv:7` (the production build hands the failure off the same way, S6) does not require the parent's GIN
  error; with no error the stock path would also succeed and print no line at WARN. `predictions.csv:9` (the devComm-first
  application gets a 1-rank communicator, S8) does not require that the parent had an error before the destroy.
- Data: in all 5 production-build trials `ho_async_seen=1` and `ho_parent_async_after` is the remote error; in all 5
  devComm-first trials `ho_async_seen=1`, `async_first` is the remote error and `ho_parent_async_after=no error`
  (`hfp/hd_shrink_b_n*_r0.kv`, `hf/hf_shrinkdc_b_n*_r0.kv`) `[measured]`. The precondition held; the verdicts stand.

**L4. The probe cannot say when a held copy completed, or whether the host call itself waited.**
- Where: `../gin_ts2.cu:1183–1215, 1574–1576`.
- After the 200 ms window the driver records only `probe_done_end` at the end of the run. The prediction text "they all
  finish after the GIN kernel ends" (G2) is supported only as "not within 200 ms, done by the end"; a copy queued behind the
  GPU-filling kernel (3 s) would look the same. `p0` is taken before the `cudaMemcpyAsync` loop, so a host-side wait inside
  the call would also read as "not done within 200 ms". `probe_max_ms=0.000` is printed when none finished, the same value a
  very fast copy would give.
- Effect: none on the verdicts. For the cause analysis, poll the events until the end and log each completion time and the
  issue time of each copy.

**L5. The per-node clock offset of `hog_*_start_rel_ms` drifts.**
- Section 3.1 calls it constant per node. Recounted from the cells whose blocks start at once (`hogpre`, `hogpreslack`,
  9 rank-trials per node in H2, 05:42–05:45): rain 3361.8–3362.2 ms, sunny 3692.7–3693.5 ms; the refill at 06:17: rain
  3372.8 ms, sunny 3699.2 ms; the pilot (section 12, 05:05): rain 3358.6–3358.7 ms, sunny 3672.6 ms `[measured]`. The
  reference is `CLOCK_REALTIME`, which NTP slews `[inferred]`.
- Effect: none (no rule uses these columns; the effect sizes are seconds). Do not subtract a pilot offset from main-run
  values; use same-hold cells, or `hog_start_spread_ms`.

**L6. The 2 × 2 cannot name which call holds the GPU.**
- The "calls between the launches" variant bundles a lazy kernel load (occupancy query), a `cudaMalloc` and a stream
  creation (`../gin_ts2.cu:1164–1170`). The driver does exactly this in both "held" cells and none of it in the two other
  cells (`1083–1091` moves it before the GIN launch). The CUDA lazy-loading documentation separately warns that loading a
  module can wait for running kernels `[unverified on this testbed]`, so "allocation" should not be named alone as the
  cause. Section 19 already lists the split as next work.

**L7. Scope wording on revoke.** Section 4 says a shrink after `ncclCommRevoke` keeps the stock answer. In code the rule
applies to every `NCCL_SHRINK_ABORT` shrink, revoked or not (`init.cc:3681–3684` checks no `revokedFlag`). No cell revokes;
fix the wording or add the check.

**L8. The refill trial was not interleaved.** `hf_hogpre_f1_b_n6` ran 32 min after its cell's other trials, alone in hold
`fill`. Its values match `n2`–`n5` (191/192 and 287/288 blocks at the probe, 8/8 copies within 0.034–0.057 ms, transparent)
`[measured]`. No effect.

### Nits

- `../gin_ts2.cu:1288–1302`: the allreduce output half of `dbuf` is not filled with a known value before the call, so the
  equality check relies on `cudaMalloc` memory not holding 1..1024 already. Fill it with NaN first.
- `gdakiBlameUnkeyed` (tree `gin_host_gdaki.cc:823`) is process-wide and never reset: one raise without a slot turns the
  hand-off off for every communicator until exit. Fails closed; worth one sentence in section 9.
- `gdakiBlameMu`/`gdakiBlameReg` are function-scope statics like gin-harden's `gdakiUaMu`/`gdakiUaReg`; a helper thread
  still running at `exit()` could note into a destroyed registry. The driver leaves with `_exit`. Pre-existing pattern.
- The keep line is WARN in the production build for every aborting shrink of a failed communicator, also without GIN ("the
  communicator or its proxy has an error of its own"). Intended, but it is a new WARN line for non-GIN users.
- The hand-off control on gin-harden's library (S4) and the latency baselines (`hd`, `hdp`) run gin-harden's driver
  `c0b73e09`, the new cells run `9493584d`. The differences are after the shrink call and outside the latency loop
  (`[source]`, diff against `prereg/gin-harden-v1`), so the contrasts are library-only in effect `[inferred]`.
- `ssh`/`scp` in the runner have no `ConnectTimeout`; they are bounded only by the hold's `timeout -s KILL 880`. In-hold
  times were 1 min 46 s – 3 min 27 s (H1 3:19, H2 3:06, H3 3:27, H4 1:46, fill 0:09) `[measured]`.
- `hold.sh:83–87` compares the sum of command-error lines (both nodes) and rain's firmware failure counters; a drop in one
  term (dmesg ring buffer) could mask a rise in another. No rise was seen.
- `EXPERIMENT.md` still shows `PREREGISTERED` and has no run records for H1–H4, the refill hold or the bind-failure
  exclusion (rule 12 of `CLAUDE.md`).

## Focus answers

### 1. Shrink layer safety

- **Non-excluded peer or no peer.** Cannot pass `[source]`. `ncclCommGetAsyncError` reports a GIN error only through
  `ncclGinQueryLastError` (tree `gin/gin_host.cc:595–608`) or, with GIN progress threads, `ginState.asyncResult`
  (`init.cc:4070`; the rule keeps the stock answer when such threads exist, 3606). For GDAKI the query returns the error
  from `q4->hasError` or from QUERY_QP (`gin_host_gdaki.cc:6717–6745`). `q4->hasError` is set in exactly three places, each
  after a note: `gdakiQ4Handle` 996–997 (the QP's peer), `gdakiTsSurface` 2815–2816 (no peer), `gdakiTsDecline` 4139–4147
  (the peer); the QUERY_QP path notes "no peer" before it returns (6741–6742). A slot-less raise sets the process-wide
  "unkeyed" flag (823), which makes every later query refuse. The rule refuses on no record, on any no-peer raise, on more
  than 64 peers, on a peer that maps outside the communicator, to itself, or to a rank not in the sorted exclude list
  (3620–3633; the list is sorted at 3673). The rank mapping is `ncclTeamRankToWorld` of the team `ncclGinConnectOnce`
  connects (`gin_host.cc:156–166`); with 2 ranks it was only exercised as the identity.
- **Races.** Notes are taken under `gdakiBlameMu` before a release store of the flag; the rule reads the flag (acquire, in
  `ncclCommEnsureReady`) before it takes the same mutex, so a seen flag implies a seen note. A raise after the check is
  equivalent to an error that arrives after a stock check and does not reach the child. Lock order is
  `outMu` → `gdakiBlameMu` (decline) and `devCommRwMutex` (shared) → `gdakiBlameMu` (query); nothing takes another lock
  under `gdakiBlameMu`. One benign window: `gdakiTsDecline` raises the user abort word inside the lambda and sets
  `hasError` after it (4141, 4147), so a kernel released by the word could let a shrink run before the flag is set; the
  shrink then sees no error and takes the stock path (no hand-off line). In the data the hand-off line was present once in each of
  the 10 research-build shrink trials and came 4.7–10.0 ms after the decline line (`hf/hd_shrink_b_n1`–`n10_r0.log`,
  recounted, n=10) `[measured]`.
- **Child isolation.** `shareResources` is false for `NCCL_SHRINK_ABORT` (`init.cc:3701–3703`); the child gets a new,
  value-initialized `ncclSharedResources` (`commAlloc`, 548–564; `NEW_NOTHROW` uses `x{}`), new abort flags (3711–3717), and a
  zero async result (`ncclCalloc`). Its GIN state is unconnected until it creates a devComm. See M2 for what the test covers.
- **Lifetime of the notes.** One entry per GIN state, keyed by `&sharedRes->ginState.asyncResult` (the same pointer every
  GDAKI context gets through the thread-local `ncclGinQ4AsyncResult`, `gin_host.cc:371, 391`). `commFree` drops it right
  after `ncclGinFinalize` and before `delete sharedRes` (`init.cc:371–384`), so an address cannot be reused while its entry
  exists. If `ncclGinFinalize` fails, `commFree` returns early and leaks both the entry and `sharedRes` (no reuse). The Q4
  watcher is stopped before the helper join (`gin_host_gdaki.cc:5659`) and an orphaned helper cannot note
  (`gdakiTsToComm`, 2557–2562), so no note follows the drop. Stale entries could only add peers.
- **`NCCL_GIN_SHRINK_HANDOFF=0`.** Returns the stock value with a keep line naming the switch; notes are still recorded (memory
  only). Measured in the switch-off control: 5/5 shrinks failed at 0.0 ms with the remote error and the keep line named the
  switch (`hf/hf_shrinkoff_b_n1`–`n5`, recounted) `[measured]` (prediction S5).
- **Stock answer in refused cases.** Exact: `commShrinkAbortReady` calls `ncclCommEnsureReady` once, as stock did, and every
  refusal returns that same `ret` (`init.cc:3586–3639`). Success and "used before init ended" pass through untouched (3587).
  Split and non-aborting shrink call `ncclCommEnsureReady` as before (3681–3684). The only additions on a refusal are one
  WARN line and two lock acquisitions.

### 2. Driver

- **Shrink call order** (`../gin_ts2.cu:1246–1320`): main wait; optional `ncclDevCommDestroy` only if the old kernel ended;
  `ncclCommShrink(..., {1}, NCCL_SHRINK_ABORT)` under `alarm`; the parent's async error; `ncclCommCount`; a 1024-float
  out-of-place allreduce on a new stream, polled 5 s; element-wise check `out == in × nRanks`; the child's async error;
  `ncclCommDestroy(child)`; wait for the old kernel; later the parent's `ncclCommAbort`. The allreduce is really checked
  (`ho_check_ok` needs the stream done and all 1024 values equal); with one rank it checks a local copy (M2, nit on the
  output fill).
- **2 × 2 allocations.** As designed `[source]`: the start-time array (`cudaHostAlloc` mapped), the probe's device word,
  staging, 8 streams and 8 events are made before the GIN launch in all four cells (1049–1082). Without
  `GIN_TS_HOG_PREALLOC` the calls between the launches are gin-harden's sequence unchanged (1165–1170 against the tag);
  with it they move before the GIN launch, plus `cudaFuncGetAttributes` (1083–1091), and only a host poll,
  `clock_gettime` and the launch remain between the launches. The GPU-filling stream is created right after the 8 probe
  streams in both variants with no stream created in between, so its creation order is the same `[source]`.
  `hog_launch_after_launch_ms` was 0.2–0.4 ms in all 40 rank-trials `[measured]`.
- **Probe and block starts.** Probe issued 20.0–20.1 ms after the GPU-filling launch `[measured]`. Each block writes its
  `globaltimer` start to host-mapped memory with `__threadfence_system` (702–703); counts and spread compare the same
  clock. The absolute "rel" columns carry a drifting offset (L5).
- **Failed looks ok, or the reverse.** Not found in the code paths that feed the rules: missing kv values become empty
  fields that make every comparison false (`../s2_close/score.py:77–90, 133–138`), CUDA errors exit with code 6 through
  `CK`, and `ho_newcomm` is the returned pointer (the shrink failure path leaves it null, `init.cc:3755–3768`). The two
  weaker spots are the output fill (nit) and `probe_max_ms=0.000` for "none finished" (L4).

### 3. Runner and scripts

- **Kills.** Only recorded PIDs: rank 1's remote shell writes its PID and execs into `timeout`; the kill and the cleanup
  signal that PID's `gin_ts2` child or that PID only if `/proc/<pid>/cmdline` carries the trial's unique tag
  (`../harden/run_trial_hd.sh:81–83, 169–170`); rank 0's kill takes the child of the recorded `timeout` PID (97). Nothing is
  killed by name alone. `left=0` in 116/116 trials `[measured]`.
- **Bounded times.** Each rank runs under `timeout -s KILL WATCHDOG_S+20`, each hold under `timeout -s KILL 880`
  (`chain.sh:19`), each hold inside `cluster_run.sh -w 10800`. SSH without a connect timeout (nit).
- **Ports.** L1.
- **STOP rules.** mlx5, iptables and CUDA-fault stops are implemented and were checked before each hold; three section 8
  rules are not automated (L2). Exit codes `[measured]`: `r0rc=137` only in the 5 trials whose rank 0 is killed by design
  (`hd_rxdeath_b`), `r0rc=1` only in the bind failure, no 139 anywhere.

### 4. Parser and scorer

- **Columns.** `rows_hf.py:33–98` matches section 3.1 and the log formats in the tree (`init.cc:3638, 3646–3653`,
  `gin_host_gdaki.cc:2823, 5574`). The keep-line regex is greedy up to " mono_ms", so a reason that itself contains
  parentheses ("which is not excluded") is captured whole. `hoff_ranks_r0` "1" compares as the number 1; a list such as
  "1,2" stays a string and fails `== 1`.
- **Exclusions.** `score.py:91–116` implements section 8 in order: bind failure, fault not applied per hook rank, trigger
  missed, no kill per killed rank, fault outside the GPU-filling kernel's 3 s window (`h < f < h + 3000`), firmware
  overrun. The configuration checks (117–146) match section 8 but do not stop the block (L2).
- **Vacuous passes.** Missing columns cannot pass (empty-field semantics). Every count rule needs the planned number of
  scored trials or it is 자료 부족 (`score.py:189`). The two rules without an encoded precondition are L3; their
  preconditions held.

### 5. Changes after the tag

- `prereg/gin-handoff-v1` is an annotated tag on commit `c9efc7b9`, which is the branch head; there are no later commits.
- Working-tree files equal to the tag blobs `[measured]`: `predictions.csv` (sha256 `04ac4a66…`, equal to `PREREG.txt`),
  `score.py`, `rows_hf.py`, `cells.sh`, `chain.sh`, `build_hf.sh`, `make_diff_hf.sh`, `EXPERIMENT.md`, `PREREG.txt`,
  `hf_layer.diff`, `gin_transparent_hf.diff`, `deploy_check.txt`, `../gin_ts2.cu` (md5 `1e4fd2f4…`, as section 5),
  `../harden/rows_hd.py`, `../harden/cells.sh`, `../harden/score.py`, `../scripts/ts2/rows.py`, `../s2_close/score.py`,
  `../s2_close/rows_extra.py`, `../pair_check/rows_pc.py`, `../oneway/rows_ow.py`.
- `deploy_hf.sh:14`, `hold.sh:16`, `../harden/run_trial_hd.sh:33` and `../../common/cluster_run.sh:23` differ only in the
  management-address default, which the repository's address filter rewrites between checkout and commit; no other
  change.
- Every main-run trial started after the tag (H1 idle check 05:21:09, tag 05:12:42) `[measured]`. Nothing that affects
  scoring changed after the tag.
