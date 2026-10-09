# gin-remaining: independent recount of the main run (2026-10-09)

Independent agent, 2026-10-09. Scope: the main run in this folder (holds H1–H5, 159 trials), recounted from the raw
per-trial files without the study's scorer. The pilots (`../20261009_pilot/`, `../20261009_pilot2/`) are not scored; they
were read only to check what EXPERIMENT.md 12 says about them.

Marks: `[measured]` read from the raw files by [../../qa/recount.py](../../qa/recount.py), `[inferred]` interpretation,
`[source]` read in the library or driver source.

## 1. Method

- **Script.** `python3 qa/recount.py` (from the study folder; `--pilots` adds the pilot-statement checks) prints the whole
  recount in about 15 s. It only reads files. Its git calls are `git rev-parse`, `git log -1 --format=%ci <commit>` and
  `git cat-file -p prereg/gin-remaining-v1:<path>`; none of them runs the address filter. It never prints a hold-log line
  or a runner line: runner files are compared with the tag after masking their `SUNNY_SSH` default line, and hold-log
  lines are parsed, not echoed.
- **Read.**
  - Data: every `<stem>_meta.txt`, `_r<r>.kv`, `_r<r>.log`, `_kill.out`, `_lat_raw.csv.gz` under `hr/`, `hq/`, `hrp/`,
    `hqp/`, `mr_hr/`, `mr_hq/`; `_rain.kv`, `_sunny.kv` under `bench/` and `ngt/` (their `.log` files are all 0 bytes);
    `hold_H1.out`–`hold_H5.out`, `chain.out`, `snap_*`, `mlx5_new_*`, `LEFT_STREAK`.
  - Study files: `EXPERIMENT.md`, `predictions.csv`, `PREREG.txt`, `cells.sh`, `hold.sh`, `chain.sh`, the four runners,
    `deploy_check.txt`, `deploy_ngt_check.txt`; the drivers `../gin_ts2.cu`, `gin_mr.cu`, `hm_bench.cu`,
    `nic_gate_test.cu` (kv keys, the p50 index rule, the transparent definition); the library tree
    `agent_ts2hr/nccl-src` (`gin_host_gdaki.cc`) for every log format.
  - Column definitions: this study's EXPERIMENT.md 3.1, `../peer/EXPERIMENT.md` 3.1, `../harden/EXPERIMENT.md` 3.1,
    `../handoff/EXPERIMENT.md` 3.1, `../multirank/EXPERIMENT.md` 3.1, `../oneway/EXPERIMENT.md` 3.1–3.2,
    `../s2_close/EXPERIMENT.md` 3.1–3.2 (grammar). As a layout model only, the text of `../peer/results/20261009/qa_recount.md`.
- **Not read or run.** `score.py`, `rows_hr.py`, `SCORE.md`, any `trials_*.csv`, the row extractors and scorers of the
  earlier studies (`../scripts/ts2/rows.py`, `../s2_close/rows_extra.py`, `../pair_check/rows_pc.py`, `../oneway/rows_ow.py`,
  `../harden/rows_hd.py`, `../handoff/rows_hf.py`, `../peer/rows_pq.py`, `../multirank/rows_mr.py`) and the earlier
  studies' `qa/recount.py`. One note: at the start of the session a byte comparison (`cmp`) of every tagged file of this
  folder with the tag also covered `score.py` and `rows_hr.py` (identical); their content was never displayed or used, and
  the script skips them.
- **Columns.** Re-derived from the documents and the drivers, independent in code and in definition. Where the documents
  only say "rows.py" or leave a choice, I used:
  - `transparent_ok`, two ranks: the `../gin_ts2.cu` header. Sender `tx_done == iters` and `tx_rc` "no error"; receiver
    `rx_done == iters`, `rx_rc` "no error", `dev_bad_slots` 0, `host_bad_slots` 0, `signal_exact` 1; `async_first` "none"
    on both ranks; in bidir mode both ranks both ways. Four ranks: `../multirank/EXPERIMENT.md` 3.1 (every edge ok, every
    rank outcome ok, no async error). Cross-check: it equals "every rank outcome=ok and exit 0" in all 149 two- and
    four-rank trials `[measured]`.
  - `rec_init_r*`, `n_copyto_r*`, `n_judged_r*`, `ts_on_r*`, `hr_on_r*`: line counts of the rank's log.
  - `decl_r*` every decline reason joined with ";"; `declwhy_r*`, `cause_r*` the first ones; `uaerr_why_r*` the first
    devComm-word line with why declined, peer-dead or fw-watchdog; `teardown_r*`, `teardown_ms_r*` the kv `abort_ret` and
    `teardown_ms`.
  - Clocks: two ranks, rank 0 kv `clock_offset_ms` (rank 1 − rank 0); four ranks, `clock_offset_ms_r<r>`. A kill on sunny
    is on sunny's clock. Survivor columns (`dead_ms_r*`, `rel_after_dead_ms_r*`, `degr_after_dead_ms_r*`) use one process's
    own clock, as 3.1 says.
  - `hs_first_after_round_ms`: the earliest "handshake timeout" decline by the rank 0 clock, minus that rank's first round
    line on its own clock. `rec_last_after_round_ms`: the latest `t_resumed` of every recovered line (both roles, rank 0
    clock) minus the earliest round line (rank 0 clock).
  - `served`, `kept`: the lines of 3.1, "R-P" sorted and joined with ";"; `n_served_rec` counts a nested round when R's
    responder recovered line with peer P comes before its `back to round` line.
  - `degr_ranks`: "r0,r1,r2" joined with "," (the rule's literal). `n_stuck_surv`: survivors with `kernel_done=0`; equal
    to the survivors with outcome `async_error_kernel_stuck` in every trial `[measured]`.
  - `surv_tx_ok`: survivor edges whose sender kv has `done == iters` and rc "no error"; `surv_tx_failed`,
    `surv_rx_failed`: rc not "no error" (a missing key counts as failed; only the `hq` control, where the survivor kernels
    never ended, has missing keys, and no rule reads these columns there).
  - `ng_rounds_*`: min of `a_rounds`, `b_rounds`; `ng_lost_writes_*` and the other counters: phase a + phase b.
  - Each log line is matched with the format string in `gin_host_gdaki.cc`. Parse coverage over the 398 rank logs (lines
    holding the fixed text / lines parsed) is complete for all 22 line types used, for example round 149/149, recovered
    178/178, declined 145/145, judged dead 75/75, devComm word 323/323, this study's start line 268/268, NIC path on
    258/258, teardown copy path 243/243, served in a wait 43/43, kept 17/17, degraded schedule 45/45 `[measured]`.
- **Rule evaluator.** My own AST evaluator of the grammar of `../s2_close/EXPERIMENT.md` 3.2 (with the arithmetic of
  `../pair_reset` 3.2), applied to the `acceptance` text of `predictions.csv` verbatim: `count`, `has`, `nonempty`,
  `median`, `abs`, `per cell:`; numeric strings become floats, blanks None; any comparison or arithmetic with None is false;
  a chained comparison needs every pair; a rule is judged only when every cell key it names has its planned judged trials
  (section 7). Non-vacuity check: each new or control rule's condition counted on the other build's cell of the same name
  gives 0 hits in 14 of 16 pairs; the two others are expected (the held-stream condition of the GPU-full order holds on
  `hq` too, 5/5; the stream-creation-only condition holds on `hr` too, 3/3) `[measured]`.
- **Exclusions.** Section 8 in order: bind failure; fault not applied (a hooked rank without a fire, taken from the meta
  `fault`; trigger miss; a kill cell without a kill record; four ranks: `fires` not "0:0;1:4;2:6", "0:0;1:4" or "0:0"
  where expected, or a fire outside its rank's traffic window, or a kill outside traffic); condition not applied (GPU-full
  cells: rank 0's fault outside the 3 000 ms window after the GPU-filling launch; cycle and chain: `cyc_spread_ms` blank or
  above 250); firmware overrun (a "firmware command phase" watchdog line or `rs_fw_overruns` > 0); benchmark exit code not
  0; NIC gate test exit code not 0 or 1.
- **Setting checks.** Section 8: start lines per build, copy path per cell, no NIC-path-off line, no test switch line in a
  two-rank trial, `hog_calls_after` per GPU-full cell, driver bundle; production builds without start lines at WARN and
  with `rs_api=1`, `rs_contexts >= 1`; four ranks: line counts against n, stall switch "0:300;1:300;2:300" or "0:300;1:300"
  or none, `rx_untimed=1` on every rank of the untimed cell; NIC gate `mr=dmabuf`, `gid_kind=link-local`.
- **Hold logs.** `hold.sh`'s order for H1–H5 is rebuilt and every start and result line is lined up with its trial
  (build, cell, trial, port, tries, flush, every rank's rc, left, wall_s); every rank log's first and last line must fall
  between its hold's two snapshots; every SIGKILL line must match a `kill.out`.

## 2. Integrity `[measured]`

- Tag `prereg/gin-remaining-v1` resolves to commit `b0489048` (2026-10-09 14:49:16 +0900), which is also the worktree's
  HEAD.
- sha256 of `predictions.csv` is `a63389f26f1f2e1ed9b09efb4d0460e88c1922a4116b189004c7668d51a1cb5b` in the working tree, in
  the tag's copy and in `PREREG.txt`. `PREREG.txt` equals the tag's copy. 34 rows: 19 new, 6 control, 9 regression.
- EXPERIMENT.md sections 2 (2 277 bytes), 3 (14 057), 7 (3 279) and 8 (6 198) are byte-identical to the tag. The whole file
  is identical to the tag (sha256 `d119ca8f…`): nothing has been written into it since the pre-registration (section 6).
- `build_hr.sh`, `cells.sh`, `chain.sh`, `portpick.sh`, `make_diff_hr.sh`, `gin_mr.cu`, `hm_bench.cu`, `nic_gate_test.cu`,
  `hr_layer.diff`, `gin_transparent_hr.diff`, `deploy_check.txt` and `deploy_ngt_check.txt` are identical to the tag.
  `deploy_hr.sh`, `deploy_ngt.sh`, `hold.sh`, `run_trial_hr.sh`, `run_mr_hr.sh`, `run_bench_hr.sh` and `run_ngt_hr.sh` differ
  from the tag in one line each, the `SUNNY_SSH` default, which the repository's address filter stores as a placeholder.
- Source md5s in the working tree equal the build records: `../gin_ts2.cu` `1779db9d`, `gin_mr.cu` `a6a526ad`,
  `hm_bench.cu` `9b13a4b8`, `nic_gate_test.cu` `4d87f2b8`. `deploy_check.txt` lists the md5s of EXPERIMENT.md 5 (`hr`
  libnccl `2dee2b5b`, `hrp` `786f70bc`, `gin_ts2` `4e81d8d8`, `gin_mr` `d588e9ce`, `hm_bench` `a00094b0`) for source, rain
  and sunny, "deployed md5 == source on both nodes" and "existing bundle unchanged", and the unchanged `hq`/`hqp` files
  (`c1311625`, `4fa076e1`, `3e053ff2`). `deploy_ngt_check.txt` lists `abb2af4c` three times and "deployed md5 == source".
  I did not check the binaries on the nodes (no cluster access).
- Trial set against section 7: 159 trials (two-rank 79, latency runs 20, four-rank 50, benchmark 5, NIC gate 5) in 30 cell
  keys; every planned key has exactly its planned trials, numbered n1..nK without gaps; no key or file outside the plan; no
  rank without a kv or a log (killed ranks included). Every meta line carries the arguments `cells.sh` gives that trial
  (fault, app, iterations, bytes, injection time, gap, kill rank and delay, `R*_ENV` hooks with contexts 0, 4, 6 and the
  stall switch, `EXTRA_ENV`, flush), the folder matches the build, the bundle, library and driver paths match the build
  (`hq` two-rank controls with `drvkey=hr`), `rdv_nonce_set=1` everywhere. No fill hold was run.
- The first log line of the main run is at 14:53:30, after the pre-registration commit at 14:49:16.

## 3. Exclusions, setting checks and safety `[measured]`

- **Exclusions: 0 of 159; judged 159.** This confirms the scorer's reported "159 trials, 159 scored, 0 excluded" (taken
  from the task statement; I did not read SCORE.md).
  - Inputs: bind failures 0; trigger misses 0; hooked ranks without a fire 0; kill trials without a kill record 0 (35 kill
    records).
  - GPU-full cells (44 trials): the GPU-filling kernel was launched 0.2 ms after the GIN launch in every trial; rank 0's
    fault came 582.6–1 146.6 ms after it (range over the 44 trials), inside the 0–3 000 ms window.
  - Cycle cells: fires exactly "0:0;1:4;2:6" and inside traffic in 15/15; round-start spread 1.4–17.0 ms (`hr`, n=10) and
    3.0–3.9 ms (`hq`, n=5). Chain: fires "0:0;1:4" in 5/5, spread 0.9–17.4 ms. `mr4_f1_01`: "0:0" in 5/5.
  - Four-rank kills (20 trials): 7 956.2–8 037.0 ms after the last kernel launch and 6 963.0–7 043.8 ms before the earliest
    nominal traffic end (the rule needs at least 5 000 ms), rank 0 clock.
  - Firmware watchdog lines 0; `rs_fw_overruns` > 0 in no rank kv.
  - Benchmark exit codes 0/0 in 5/5; NIC gate exit codes 0/0 in 5/5.
- **Reading of "감시 줄" (section 8, firmware overrun).** 15 two-rank trials carry a different watchdog line, "fault records
  are queued and the recovery helper is not running; the fault surfaces", once on rank 0: all 5 of the GPU-full `hq`
  control, all 5 of the stream-copy control and all 5 of the load-only `hq` cell. It is not a firmware overrun, so I did not
  exclude them; the scorer's 0 exclusions agree with that reading. The pilot recorded the same line in the same cells before
  the tag (section 12). If every `watchdog rank=` line counted, those three cell keys would have no judged trial.
- **Setting checks: 0 problems in 159 trials.** `hr` two-rank: harden (`production=0`), handoff, gin-peer, this study's,
  transparent-recovery and abort-word lines on every live rank; copy path `nic` (stream in the stream-copy cell); no
  NIC-path-off line; no test switch line. `hq`: no line of this study. `hrp`/`hqp`: no start line at WARN, `rs_api=1`,
  `rs_contexts >= 1`. Four ranks: every count as required, stall switch values as required, `rx_untimed=1` on all 4 ranks of
  all 15 untimed trials. NIC gate: `dmabuf` and `link-local` on both nodes in 5/5.
- **Hold logs.** All 159 result lines (and their start lines) match their trial files in `hold.sh` order, with no
  difference in build, trial, port, tries, flush, rc, left or wall_s, and every trial's rank logs lie inside its hold's
  snapshot window. 35 SIGKILL lines, each matching one of the 35 `kill.out` files. `chain.out`: H1–H5 rc 0; `gin-`
  iptables rules 0 before and after every hold. Port picks: 1 candidate in all 149 rank trials, no skipped, decoy or
  occupied port; 0 "Address already in use"; rendezvous ports 29 005–30 987.
- **Stop criteria.** No STOP file; `LEFT_STREAK` 0; no `stale.txt`; `left=0` in every trial; no exit 139; no
  illegal-address or launch-failure string in any log or kv. Per hold: rain cmd_err 2→2, sunny 0→0, rain firmware-command
  failures 31→31; `mlx5_new_H1`–`H5` are empty.
- **Hold times** (idle to exit): H1 14:53:27–14:58:28, H2 15:02:52–15:09:04, H3 15:10:42–15:18:55, H4 15:19:26–15:26:55,
  H5 15:27:26–15:33:14.
- **Exit codes** are uniform within every cell key: transparent cells 0 on every rank; the declining two-rank cells
  (GPU-full `hq`, stream copies, load-only `hq`, `f2rel_b`) 4/4; `f4_b` and `hdp_kill_b` 4 and 255 (rank 1 killed);
  `hd_rxdeath_b` 137 (rank 0 killed) and 4; the `hq` cycle 4/4/4 and 0; the untimed `hr` cell and gin-peer's kill cell
  4/4/4 and 255 (rank 3 killed); the untimed `hq` cell 3/3/3 and 255.

## 4. Verdicts `[measured]`

**33 hold, 1 fails, 0 data insufficient.** "n" is judged trials; "hits" the trials meeting the rule's condition.

| What was predicted | id | cell | n | hits | rule | verdict |
|---|---|---|--:|--:|---|---|
| Three initiators in a cycle recover with no handshake timeout and no decline, every edge ok, each pair logs an initiator recovery | CY1 | `mr4_cyc_stall@hr` | 10 | 10 | ≥9 | holds |
| The last recovery of the cycle resumes within 5 000 ms of the first round line | CY2 | `mr4_cyc_stall@hr` | 10 | 10 | ≥9 | holds |
| At least one REQ is answered inside another round's ACK wait | CY3 | `mr4_cyc_stall@hr` | 10 | 10 | ≥9 | holds |
| Control (gin-peer library): the cycle waits for the ACK bound and declines with a handshake timeout 24.3–24.8 s after the round start | CY4 | `mr4_cyc_stall@hq` | 5 | 5 | ≥4 | holds |
| Regression: the chain without a cycle stays transparent and resumes within 5 000 ms | CY5 | `mr4_chain_stall@hr` | 5 | 5 | ≥4 | holds |
| Untimed receives, rank 3 killed: every survivor's receive from rank 3 is released with an error 2 000–3 000 ms after that survivor judged rank 3 dead | DG1 | `rm4_kill3_untimed@hr` | 10 | 10 | ≥9 | holds |
| Each survivor logs one degraded release of the abort word, 2 000–2 500 ms after its judged-dead line | DG2 | `rm4_kill3_untimed@hr` | 10 | 10 | ≥9 | holds |
| The six per-peer sends between survivors complete and every survivor kernel ends | DG3 | `rm4_kill3_untimed@hr` | 10 | 10 | ≥9 | holds |
| The cost: the six receives between survivors are released with an error too | DG4 | `rm4_kill3_untimed@hr` | 10 | 10 | ≥9 | holds |
| Control: nothing is released, the survivor kernels run until the application gives up | DG5 | `rm4_kill3_untimed@hq` | 5 | 5 | ≥4 | holds |
| gin-peer's kill cell (receives bounded at 10 s): survivor sends succeed, the six survivor receives fail on the degraded word, three degraded lines | DG6 | `mr4_kill3_peer@hr` | 5 | 5 | ≥4 | holds |
| GPU-full order of gin-handoff (three calls after the GIN launch): transparent, every copy over the NIC, no copy timeout | GR1 | `rh_hog_f1_b@hr` | 10 | 10 | ≥9 | holds |
| The CUDA streams were held all the same: no probe copy within 200 ms, no GPU-filling block at the probe, on both ranks | GR2 | `rh_hog_f1_b@hr` | 10 | 10 | ≥9 | holds |
| No device-state copy of the helper went through the stream (teardown counters) | GR3 | `rh_hog_f1_b@hr` | 10 | 10 | ≥9 | holds |
| Control: the gin-peer library's copy times out, no recovery, not transparent | GC1 | `rh_hog_f1_b@hq` | 5 | 5 | ≥4 | holds |
| Control inside `hr`: with the stream copy path the same order declines on a copy timeout | GC2 | `rh_hog_copystream_f1_b@hr` | 5 | 5 | ≥4 | holds |
| Only the kernel load after the GIN launch: probe copies held, the `hq` round declines on a copy timeout | GS1 | `rh_hogcall_load_f1_b@hq` | 5 | 5 | ≥4 | holds |
| Only `cudaMalloc` after the GIN launch: probe copies held, the `hq` round declines on a copy timeout | GS2 | `rh_hogcall_malloc_f1_b@hq` | 5 | 0 | ≥4 | **fails** |
| Only the stream creation after the GIN launch: probe copies finish within 200 ms, the `hq` round is transparent | GS3 | `rh_hogcall_stream_f1_b@hq` | 5 | 5 | ≥4 | holds |
| `hr` is transparent whichever single call is made (per cell) | GS4 | load, malloc, stream `@hr` | 3, 3, 3 | 3, 3, 3 | =3 each | holds |
| Regression: the recovery cells stay transparent (per cell) | RG1 | `f1_b`, `f3_b`, `bidirf_sym_b` `@hr` | 5, 5, 5 | 5, 5, 5 | =5 each | holds |
| Every device-state copy of those rounds went over the NIC (per cell) | RG2 | same | 5, 5, 5 | 5, 5, 5 | =5 each | holds |
| Two ranks, peer killed: peer-dead decline within 2 s, the abort word goes up at once (no degraded schedule) | RG3 | `f4_b@hr` | 5 | 5 | =5 | holds |
| Two ranks, a receive-only rank's `waitSignal` is released with an error within 2 s of the sender's kill | RG4 | `hd_rxdeath_b@hr` | 5 | 5 | =5 | holds |
| Remote access error: rank 0 declines, rank 1's wait is released with an error, its abort returns within 5 s | RG5 | `f2rel_b@hr` | 5 | 5 | =5 | holds |
| Production build, peer killed: decline within 2 s, one death, no informational line at WARN | RG6 | `hdp_kill_b@hrp` | 5 | 5 | =5 | holds |
| Statistics API: one round, one recovery, no decline on both ranks | RG7 | `f1_b@hr` | 5 | 5 | =5 | holds |
| Four ranks, no fault and one pair's local QP error: transparent (per cell) | RG8 | `mr4_none`, `mr4_f1_01` `@hr` | 5, 5 | 5, 5 | =5 each | holds |
| 4 KiB p50: production build within 0.40 µs of gin-peer's production build | LT1 | `lat_4k@hrp` vs `@hqp` | 5/5 | −0.25 µs | ≤0.40 | holds |
| 256 KiB p50: within 0.30 µs | LT2 | `lat_256k@hrp` vs `@hqp` | 5/5 | 0.00 µs | ≤0.30 | holds |
| Neither GPU has native host atomics | HB1 | `hm_bench@hr` | 5 | 5 | =5 | holds |
| A dependent atomic add on host-mapped memory costs at least 400 ns more than on device memory, both GPUs | HB2 | `hm_bench@hr` | 5 | 5 | =5 | holds |
| The race phase ends normally and no device update of the count half is lost | HB3 | `hm_bench@hr` | 5 | 5 | =5 | holds |
| The gate protocol over NIC-loopback writes and reads passes on both GPUs with at least 1 000 rounds per phase | NG1 | `nic_gate@hr` | 5 | 5 | =5 | holds |

- **The failure.** In all 5 trials of the `cudaMalloc`-only cell on `hq`, every probe copy (8 of 8) finished within
  200 ms on both ranks, 191 (rank 0) and 287 (rank 1) GPU-filling blocks had started at the probe, no copy timed out, and
  the round recovered transparently (rank 0 one initiator recovery). The same cell on `hr` (n=3) looks the same. The pilot
  had shown this already; section 12 recorded it and kept the prediction, as section 3 requires.
- **The hypotheses** `[inferred]`, reading each "falsified if" of section 2 against the counts above: H4 is falsified (the
  one-call `hq` cells have 5 trials against the prediction, all in the `cudaMalloc` cell; the kernel-load cell alone holds
  the streams); H1, H2, H3, H5 and H6 are not.
- **Margins.** The thinnest: the host-memory cost on rain, 407.9 ns in n3 against the 400 ns bound (all 10 node runs
  407.9–423.9 ns; HB2); the degraded release, 2 005.4 ms against its 2 000 ms lower bound (DG2), because the line comes
  2 000.0–2 000.1 ms after the decline and the decline 5.4–8.5 ms after the judgment; the release of the receive from rank 3,
  2 006.7 ms against 2 000 ms (DG1); the 4 KiB latency, |−0.25| µs against 0.40 µs (LT1). The handshake-timeout window of
  the `hq` cycle has 204.7 ms to spare (CY4); the 5 000 ms bounds of the cycle and the chain have about 4 s. The kill rules
  of the regression cells have a lower bound of 0 ms, which only orders the event after the kill (declines 1.51–1.70 ms;
  the receive-only rank's async error 1.8–2.1 ms and kernel end 20.2–21.5 ms).

## 5. Key numbers (each range says what it is a range of) `[measured]`

**Cycle and chain (four ranks).**
- Cycle on `hr` (n=10): transparent 10/10; handshake timeouts 0 and declines 0 in every trial; initiator recoveries exactly
  "0-1;1-2;2-0" in 10/10. Last resume after the first round line 694.6–1 002.8 ms (range over 10 trials, median 707.6 ms);
  first resume 653.1–676.3 ms. The 1 002.8 ms trial (n3) is the one where rank 0 kept rank 2's REQ for 310.7 ms.
- How the cycle broke (`hr`, n=10): every trial first ran its pair rounds, each refused at the responder's scope check
  (`not_rts`, 3 per trial, 30 in all), then reran them as full resets. REQs answered inside an ACK wait: 3–4 per trial (38
  in all: "1-0" and "2-1"); 19 of these nested rounds ended with the answering rank's responder recovery (2 per trial in 9
  trials, 1 in n3) and lasted 39.6–58.7 ms; the other 19 were the refusals of round 1 and lasted 0.7–0.9 ms. Rank 0 kept
  rank 2's REQ 1–2 times per trial (17 in all) and answered every kept REQ after 1.0–310.7 ms; none was dropped. The
  teardown counters agree: `served_in_wait` sums to 38 and `kept` to 17.
- Cycle on `hq` (n=5): 3 handshake timeouts and 6 declines per trial (3 "handshake timeout", 3 "the peer declined"), no
  recovery, first handshake timeout 24 504.7–24 507.3 ms after its rank's first round line (range over 5 trials; all 15
  handshake timeouts 24 504.7–24 508.0 ms), wall 33.1 s.
- Chain on `hr` (n=5): transparent 5/5, initiator recoveries "0-1;1-2", last resume 652.0–668.1 ms after the first round
  line. One REQ answered inside a wait per trial: rank 1, waiting for rank 2, refused rank 0's pair REQ (`not_rts`) in
  0.8–0.9 ms, and rank 0 reran as a full reset (5 rerun lines); rank 2 accepted rank 1's pair REQ.
- All 40 `hr` cycle and 20 chain ranks: copy path NIC, 0 stream copies, 0 NIC timeouts. Wall 18.5–19.1 s.

**Degraded (four ranks, rank 3 killed).**
- Untimed receives on `hr` (n=10): judged dead 0.4–0.5 ms after the kill (rank 0 clock), declined 5.4–8.5 ms after the
  judgment (same rank, pooled over 3 survivors × 10 trials). The degraded release line came 2 005.4–2 008.5 ms after the
  judged-dead line and 2 000.0–2 000.1 ms after the decline (pooled 30); its info line says "judged dead 2 000.0–2 000.1 ms
  ago", which is measured from the decline (gin_host_gdaki.cc `gdakiUaRaisePeer`) `[source]`.
- Releases on `hr`: the receive from rank 3 was released on every survivor, 2 006.7–2 013.0 ms after that survivor's
  judged-dead line (pooled 30) and 2 000.6–2 004.9 ms after its decline. All 6 survivor-survivor receives were released too
  (DG4's cost), at iterations 649–660 (n=60), rc "remote process exited or there was a network error"; 40 of those 60 had
  received the full 1 000 signals by the end, 20 had 989–990. All 90 receive releases came 2 006.2–2 016.4 ms after the
  receiver's judged-dead line.
- Healthy per-peer edges on `hr`: survivor sends ok 6/6 in 10/10 (per-peer flush); survivor kernels ended 3/3 in 10/10,
  7 129.8–7 404.9 ms after the kill; no devComm word was raised by a decline (the per-peer words were exactly
  "0-3;1-3;2-3"); sends to and receives from rank 3 failed in every trial.
- Control `hq` (n=5): no release, no degraded line, survivor kernels still running (`async_error_kernel_stuck` 15/15)
  until the application gave up 15 007.4–15 010.0 ms after the kill; wall 25.6 s.
- gin-peer's kill cell on `hr` (n=5): survivor sends ok 6/6; survivor receives failed 6/6 at iterations 651–659 with
  "remote process exited ..." (not their 10 s bound); three degraded lines per trial, 2 005.9–2 008.4 ms after the
  judged-dead line.

**NIC copy path.**
- 268 `hr` rank logs carry this study's start line: 258 `copy_path=nic`, 10 `stream` (the stream-copy cell). 258 NIC path
  on lines, 0 off lines. Every on line: link-local GID index 1; GPU MRs all dmabuf (10 per context with two ranks, 98
  contexts; 18 with four ranks, 160 contexts), peermem 0; self-test 580 B (85–93 nonzero) and 1 092 B (269–277 nonzero);
  setup 3.0–4.6 ms (two ranks) and 3.2–10.9 ms (four ranks).
- 243 teardown copy-path lines (the 25 killed ranks write none): 233 `nic`, 10 `stream`; NIC timeouts 0, fallbacks 0;
  stream copies 0 on every NIC-path rank and 13 on each stream-path rank.

**GPU-full cells and the three calls** (per cell; "probe" = the 8 new-stream 4 B copies within 200 ms).
- `hr`, all three calls after the GIN launch (n=10): transparent 10/10, rank 0 one initiator recovery each, copy timeouts 0,
  probe 0/8 and 0 GPU-filling blocks started on both ranks (the streams were held), `hog_calls_after=load,malloc,stream`.
- `hq` same order (n=5) and `hr` with stream copies (n=5): transparent 0, one copy timeout on each rank, decline reason on
  rank 0 "the watchdog surfaced a fault earlier"; the "fault records are queued ..." watchdog line came 902.6–1 001.1 ms
  before rank 0's copy timeout; rank 0's sender error at iterations 40–77; probe 0/8, 0 blocks.
- One call after the GIN launch: load only, `hq` (n=5) as the line above (probe 0/8, declines); load only, `hr` (n=3)
  transparent with probe 0/8. `cudaMalloc` only and stream creation only, both builds (n=5 and 3 each): transparent, probe
  8/8, 191 and 287 blocks started.

**NIC gate test** (5 runs, each on both nodes).
- PASS on both nodes in 5/5 (both phases PASS). Rounds per phase: rain a 8 739–8 755, b 8 805–8 820; sunny a 8 669–8 679,
  b 8 785–8 798. Backouts (a + b) 161.2–161.5 million on rain, 160.0–160.2 million on sunny. Lost writes 0, lost
  increments 0, Dekker violations 0, threads inside on an odd epoch 0, quiesce timeouts 0, index words ok, final high half
  equal to the last NIC write, `nic_errors=0`, 2.10–2.12 million NIC requests per node run. Longest quiesce 0.007–0.133 ms.

**Host-memory benchmark** (5 runs; ranges over the runs of one node).
- Native host atomics 0 on both GPUs. Dependent atomic add: rain device 178.2–178.4 ns, host-mapped 586.1–602.3 ns
  (difference 407.9–423.9 ns); sunny 186.2–186.3 and 601.8–609.3 ns (difference 415.6–423.1 ns). `.sys` scope on host
  memory: 594.9–611.4 ns (rain), 613.4–621.0 ns (sunny).
- Race: 26 343–26 434 host writes per run on rain and 26 001–26 002 on sunny, one per ≈76 µs; the read-back showed a
  device read-modify-write had put back the old high half after 4 132–4 498 writes (15.7–17.0 %) on rain and 4 154–4 739
  (16.0–18.2 %) on sunny (not predicted, as section 3.3 says); the count half ended at 0 and `race_rc=cudaSuccess` in every
  run.

**Regression.**
- `f1_b`, `f3_b`, `bidirf_sym_b`, `mr4_none`, `mr4_f1_01` on `hr`: transparent 5/5 each (`mr4_f1_01` one initiator
  recovery "0-1", `mr4_none` no round line). `f1_b` statistics API: 1 round, 1 recovered, 0 declined on both ranks 5/5.
- `f4_b@hr`: decline 1.58–1.70 ms after the kill, "peer judged dead: the peer's socket shows FIN", cause peer-dead,
  devComm word why peer-dead, no degraded line, abort "no error".
- `hd_rxdeath_b@hr`: rank 1's kernel ended 20.2–21.5 ms and its first async error came 1.8–2.1 ms after rank 0's kill; one
  judged-dead line; `rx_rc` "remote process exited or there was a network error"; abort "no error".
- `f2rel_b@hr`: rank 0 declined "class REM_ACCESS is not recoverable"; rank 1 `device_error`, 0 phantom waits, abort
  returned in 697.2–758.8 ms.
- `hdp_kill_b@hrp`: decline 1.51–1.63 ms after the kill, one death, `rs_api=1`. The only GIN lines at WARN are the
  path-wait clamp, the socket close, the judged-dead line, the per-peer and devComm-word lines and the decline; no start
  line.

**Latency** (each run's p50 recomputed from its 3 000 raw samples with the driver's index rule equals the kv value in
20/20 runs).
- 4 KiB: `hrp` 10.50, 10.50, 10.50, 10.98, 10.46 µs (median 10.50); `hqp` 10.75 µs in 5/5; difference of medians −0.25 µs.
- 256 KiB: `hrp` and `hqp` 38.88 µs in every run; difference 0.00 µs.
- The comparison includes the drivers: `hrp` runs its own new `gin_ts2` (`4e81d8d8`), `hqp` gin-peer's (`3e053ff2`), as
  section 9.2 says.

## 6. Disagreements and notes

With the hold logs: none (section 3).

With EXPERIMENT.md:
1. **The document has not recorded the main run** `[measured]`. It is byte-identical to the tag: status `PREREGISTERED`,
   "last update 14:49", run log ending at the pre-registration, the boxes "본 실행 H1–H5", "채점" and "독립 재계산" unchecked,
   sections 13–16 empty or "not measured yet". The hold logs show H1–H5 ran 14:53:27–15:33:14 with rc 0. Rule 12 of
   CLAUDE.md asks for these to be updated with the run.
2. **P2 and the tag shown as not done.** Section 10's first box says "(P0, P1은 12절에 적음, P2와 태그는 아직)" and section 11
   leaves "NIC 게이트 시험 배포(`deploy_ngt.sh`)와 pilot P2(메인 세션)" unchecked, while section 12 records the deployment at
   14:44 and P2 at 14:48:24–14:48:50 (confirmed by `deploy_ngt_check.txt`, the pilot `chain.out` and `hold_P2.out`) and the
   tag exists. The text was frozen in the tag commit itself. State only.
3. **Section 5, NIC gate test row** ends "배포 전" (before deployment); `deploy_ngt_check.txt` and section 12 show it was
   deployed at 14:44, before P2 and the main run. Stale wording.
4. **Section 12, pilot P1, untimed cell:** "받기 9개 모두 풀림(..., 판정부터 2 007.4–2 011.6 ms)". The pilot kv files give
   2 007.4–2 013.3 ms over the nine receives (rank 0's receive from rank 2 at 2 013.3 ms); 2 007.4–2 011.6 ms is the range of
   the three receives from rank 3 only `[measured, pilot, 1 trial, 9 receives]`. In the next row ("pilot과 예측"), "rank 0의
   rank 1 받기는 ... 반복 650–655에서 풀렸다": that receive was released at iteration 655; 650–655 is the range over the six
   survivor-survivor receives. No prediction depends on either.
5. **Section 12, pilot P2:** "결과 줄 12개". The NIC gate line of `hold_P2.out` carries 6 `result=PASS` (a_result, b_result
   and result on each node), and the two kv files hold the same 6 keys; 12 is only reached by adding both `[inferred]`.
   Wording only.
6. **Section 9.4** says the race host writes "약 20 µs마다". That is the loop's sleep (`sleep_for(20 µs)` in `hm_bench.cu`)
   `[source]`; with the 64 read-backs the measured rate is one write per ≈76 µs (26 001–26 434 writes in 2 000 ms per run).
   No rule uses it.
7. **Wording of the control predictions** (the GPU-full `hq` control, the stream-copy control, the load-only `hq` cell): the
   predictions say the round "declines on a copy timeout". Every trial has the copy-timeout line ("the round declines") on
   both ranks, but rank 0's decline reason is "the watchdog surfaced a fault earlier", from the watchdog line about 1 s
   before. The rules (copy timeout ≥ 1, no recovery, not transparent) are met; the pilot already showed this reason.

Planning numbers of section 9 (`[inferred]` in the document), close to the run: hold time from lock to exit (the estimate
includes the ≈31 s idle-link wait) H1 5.5 min against "약 6분", H2 6.7 against 7, H3 8.7 against 9, H4 8.0 against 8, H5 6.3
against 7, all five 35.3 min against "약 37분". The NIC gate trial took 22.5 s (wall, 5/5) against "약 26 s".

Checked and in agreement (pilot statements of section 12; the pilots are not scored): P0 13 trials 14:08:14–14:09:53 (99 s),
P1 7 trials 14:11:28–14:14:03 (155 s), locks at 14:07:44 and 14:10:57, both rc 0, `left=0`, cmd_err 2 and 0, firmware
failures 31→31, no new mlx5 line, iptables 0/0; P2 14:48:24–14:48:50, PASS on both nodes, `dmabuf`, `link-local`, rounds a
8 749 and 8 677, b 8 806 and 8 797, backouts per phase 18.02–143.34 million; GPU-full `hr` transparent with probe 0/8 and 0
blocks; `hq` and stream-copy declines with the watchdog line 1 001.0–1 001.1 ms before the copy timeout, sender error at
the 41st of 120 iterations, 13 helper stream copies on the stream path; load only `hq` declines, `hr` transparent;
`cudaMalloc` only and stream only transparent with probe 8/8 and 191/287 blocks; rank 0's fault 597.7–598.8 ms after the
GIN launch, the filling launch 0.2 ms after it; `f1_b` stats 1/1; `f4_b` decline 1.68 ms after the kill, devComm word
peer-dead, no degraded line; 4 KiB p50 10.46 and 10.75 µs; NIC path on in all 28 NIC-path contexts (two-rank 6 trials × 2,
four-rank 4 × 4), GID index 1 link-local, MRs 10 and 18 all dmabuf, self-test 580 B (93 nonzero) and 1 092 B (269–277),
setup 3.5–6.5 ms, no off line, fallback or NIC timeout; cycle `hr` 696.5 ms, spread 3.9 ms, nested 42.7 and 56.9 ms, kept
41.2 ms, 4 served (2 recovered), 1 kept and answered; cycle `hq` 3 handshake timeouts, first at 24 504.8 ms, 6 declines,
33.1 s; chain 650.9 ms with one refused answer; untimed `hr` decline 6.0–8.5 ms after the judgment, degraded 2 000.0–2 000.1
ms after the decline (2 006.1–2 008.6 ms after the judgment), sends 6/6, kernels 3/3; untimed `hq` nothing released, 25.6 s;
gin-peer's kill cell receives failed at iterations 653–659, degraded 2 006.7–2 008.3 ms; benchmark 178.3 vs 604.2 ns (rain)
and 186.2 vs 612.3 ns (sunny), margins +425.9 and +426.1 ns, 4 009 of 26 396 and 3 971 of 26 000 writes put back, count
0; pilot wall times (four-rank 18.1–33.1 s, GPU-full 5.8–6.1 s, benchmark 5.7 s). Section 3.3's "pilot 6.0–8.5 ms" for the
decline after the judgment matches the pilot; the main run gives 5.4–8.5 ms (`hr` untimed), 5.7–8.5 ms (`hq`) and 5.8–8.4 ms
(gin-peer's kill cell), pooled over 3 survivors per trial.

## 7. Limits of this recount

- I did not read `rows_hr.py` (whose header is the original definition of this study's new columns) or any earlier row
  extractor, so the columns are my reading of the 3.1 tables, the drivers and the log formats (section 1). Where my reading
  could differ (`transparent_ok`, the clocks of the timing columns, `n_stuck_surv`, `served_rec`, missing keys counted as
  failed), every value a rule uses is far from its threshold except the thin margins named in section 4 (host-memory cost
  7.9 ns, degraded release 5.4 ms, release of the receive from rank 3 6.7 ms, 4 KiB latency 0.15 µs), and those come
  straight from kv values, log timestamps and raw latency samples.
- The section 8 firmware-overrun exclusion was read as firmware-phase watchdog lines only (section 3).
- I did not access the cluster or the deployed binaries; the bundle check rests on `deploy_check.txt`,
  `deploy_ngt_check.txt` and the meta paths.
- The earlier-study numbers quoted in EXPERIMENT.md 1 (gin-multirank's cycle, gin-handoff's GPU-full cells, gin-peer's kill
  cell) were not recounted here.
