# gin-peer: independent recount of the main run (2026-10-09)

Independent agent, 2026-10-09. Scope: the main run in this folder (holds H1–H8, 203 trials), recounted from the raw
per-trial files without the study's scorer. The pilots (`../20261009_pilot/`, `../20261009_pilot2/`) are not scored; they
were read only to check statements about them in EXPERIMENT.md 12.

Marks: `[measured]` read from the raw files by [../../qa/recount.py](../../qa/recount.py), `[inferred]` interpretation,
`[source]` read in the library or driver source.

## 1. Method

- **Script.** `python3 qa/recount.py` (from the study folder; `--pilots` adds the pilot-statement checks) prints the whole
  recount. It only reads files. Its only git calls are `git rev-parse` and `git cat-file -p prereg/gin-peer-v1:<path>`,
  which apply no filter. It never prints a line that holds the management address. Run time about 35 s.
- **Read.**
  - Data: every `<stem>_meta.txt`, `_r<r>.kv`, `_r<r>.log`, `_kill.out`, `_decoy.out` and `_lat_raw.csv.gz` under `hq/`,
    `hf/`, `hqp/`, `hfp/`, `mr_hq/`, `mr_hf/`; `hold_H1.out`–`hold_H8.out`, `chain.out`, `snap_*`, `mlx5_new_*`,
    `LEFT_STREAK`; the md5 lines of `../../deploy_check.txt`.
  - Study files: `EXPERIMENT.md`, `predictions.csv`, `PREREG.txt`, `cells.sh`, `hold.sh`, `chain.sh`, `run_trial_hq.sh`,
    `run_mr_hq.sh`, `portpick.sh`; the drivers `../gin_ts2.cu` and `gin_mr.cu` (kv keys, the p50 rule, the transparent
    definition); the library tree `agent_ts2hq/nccl-src` (`gin_host_gdaki.cc`, `init.cc`) for every log format.
  - Column definitions: this study's EXPERIMENT.md 3.1, `../harden/EXPERIMENT.md` 3.1, `../handoff/EXPERIMENT.md` 3.1,
    `../multirank/EXPERIMENT.md` 3.1, `../s2_close/EXPERIMENT.md` 3.1–3.2 (grammar).
- **Not read or run.** `score.py`, `rows_pq.py`, `SCORE.md`, any `trials_*.csv`, and the scorers and row extractors of
  the earlier studies: `../scripts/ts2/rows.py`, `../s2_close/rows_extra.py`, `../harden/rows_hd.py`,
  `../handoff/rows_hf.py`, `../multirank/rows_mr.py`, and their `score.py`. I also did not open the earlier studies'
  `qa/recount.py`.
- **Consequence for the columns.** Earlier recounts re-implemented `rows.py` from its source. I did not read it, so the
  columns that the documents only describe as "rows.py" are re-derived from the driver and the document text. They are
  independent in code and in definition (risk noted in section 7):
  - `transparent_ok` (two ranks): the driver header's definition: every sender `tx_done == iters` with `tx_rc` "no
    error"; every receiver `rx_done == iters`, `rx_rc` "no error", `dev_bad_slots` 0, `host_bad_slots` 0,
    `signal_exact` 1; `async_first` "none" on both ranks. Cross-check: "both outcome=ok and both rc 0" gives the same
    value in every trial of every cell that uses it.
  - `decl_r*` every decline reason of the rank joined with ";"; `rec_init_r0` the count of rank 0's
    `recovered ... role=initiator` lines; `teardown_r*` and `teardown_ms_r*` the kv `abort_ret` and `teardown_ms`;
    `bind_fail` a "bind: Address already in use" line in any rank log; `n_fires_r*` "GDAKI fault fired" lines;
    `trigger_miss` "trigger not reached" lines; `killed` a `kill_mono_ms` in `kill.out`.
  - The new columns follow the 3.1 table of this study; the four-rank ones follow `../multirank/EXPERIMENT.md` 3.1
    (lists sorted and joined with ";"; `async_ranks` with ","; edge ok = sender done and "no error", receiver done,
    "no error", no bad slot on device or host, exact final signal).
  - Each log line is matched with the format string of the library source. Parse coverage over the 542 rank logs (lines
    containing the line's fixed text against lines parsed) is complete for all 21 line types used, for example declines
    315/315, causes 240/240, per-peer releases 235/235, devComm-word lines 452/452, plan validated 120/120, plan rejected
    20/20, FAIL answers 15/15, FAIL received 15/15, watchdog 25/25, hand-off pass 50/50, keep 15/15, recovered 75/75
    `[measured]`.
- **Rule evaluator.** My own AST evaluator of the grammar of `../s2_close/EXPERIMENT.md` 3.2, applied to the
  `acceptance` text of `predictions.csv` verbatim: `count`, `has`, `nonempty`, `median`, `abs`, `per cell:`; numeric
  strings become floats, blanks None, any comparison or arithmetic with None is false; chained comparisons need every
  pair; a rule is judged only when every cell key it names has its planned judged trials (section 7); `all@all` is every
  trial with no plan. As a check that the rules and columns are not vacuous, each new or control rule's condition was
  also counted on the other build's cell of the same name: 0 hits in all 19 such pairs (for example the per-peer
  release condition on the gin-handoff control 0/5, the gin-handoff control conditions on this study's build 0/10)
  `[measured]`.
- **Exclusions.** Section 8 in this order: bind failure; fault not applied (a hooked rank without a fire, taken from the
  meta `fault` and `r<r>env`; trigger miss; a kill cell without a kill record; four ranks: `fires` not "0:0" or
  "0:0;2:6" where expected or outside the rank's traffic window, a kill outside traffic); condition not applied (rank 1
  initiating in the responder-rejects cell; no cancel while waiting for the ACK, or the responder's first decline not a
  post-commit one, in the race cells; no copy timeout on the held rank; no watchdog line in the firmware cells);
  firmware overrun (any watchdog line or `rs_fw_overruns` > 0 outside the firmware cells).
- **Setting checks.** Section 8: start lines per build (harden with `production=0`, handoff, this study's line, the
  transparent-recovery line, the abort-word line; none at WARN in `hqp`/`hfp` with `rs_api=1`, `rs_contexts >= 1`), the
  test-switch values on the right rank only, the mute on the muted rank only, `GIN_TS_END_WAIT_S=12` on the responder of
  the race cells, and the four-rank line counts.
- **Hold logs.** Each start and result line of `hold_H*.out` is lined up with the trial that `hold.sh` runs at that
  position and compared with the meta (build, trial, port, tries, skipped, decoy, every rank's rc, left, wall_s); the
  first and last log line of every trial must fall inside its hold's snapshot window; every SIGKILL line must match one
  `kill.out`.

## 2. Integrity `[measured]`

- Tag `prereg/gin-peer-v1` resolves to commit `551c796f` (2026-10-09 09:00:54 +0900).
- sha256 of `predictions.csv` is `dccdf05c819976a067950aae2649cd33b8da161a506214633f64cab9402884db` in the working tree,
  in the tag's copy and in `PREREG.txt`. `PREREG.txt` equals the tag's copy. 37 rows: 18 new, 9 control, 10 regression.
- EXPERIMENT.md sections 2, 3, 7 and 8 are byte-identical to the tag. The whole file is identical to the tag too (sha256
  `e62610c6…`): nothing has been written into it since the pre-registration (see section 6).
- `cells.sh`, `chain.sh`, `portpick.sh`, `../gin_ts2.cu` and `gin_mr.cu` are identical to the tag. `run_trial_hq.sh`,
  `run_mr_hq.sh` and `hold.sh` differ from the tag in one line each, the `SUNNY_SSH` default, which the repository's
  address filter stores as a placeholder in commits.
- `deploy_check.txt` lists the md5s of EXPERIMENT.md 5 for `hq` and `hqp` libnccl, `gin_ts2`, `mr/hq/gin_mr`, and the
  unchanged `hf`/`hfp` bundles; it states "deployed md5 == source on both nodes" and "existing bundle unchanged on both
  nodes". The md5 of `../gin_ts2.cu` (`92a78218`) and `gin_mr.cu` (`7b238951`) in the working tree equal the source md5s
  recorded there. I did not check the binaries on the nodes (no cluster access).
- Trial set against section 7: 203 trials (two-rank cells 115, latency runs 20, four-rank 68) in 35 cell keys; every
  planned key has exactly its planned trials, numbered n1..nK without gaps; no key or file outside the plan; no rank
  without a kv or a log. Every meta line carries the arguments `cells.sh` gives that trial (app, fault, iterations,
  bytes, injection time, kill rank and delay, `R*_ENV`, `EXTRA_ENV`, flush), the folder matches the build, and the
  bundle or libdir and driver path match the build; `rdv_nonce_set=1` everywhere. No fill hold was run.
- The first log line of the main run is at 09:01:36 and the last at 09:51:32, after the pre-registration at 09:00:54.

## 3. Exclusions, setting checks and safety `[measured]`

- **Exclusions: 0 of 203.** Judged 203. This confirms the scorer's reported "203 trials, 203 scored, 0 excluded" (taken
  from the task statement; I did not read SCORE.md).
  - Inputs: bind failures 0; hooked ranks without a fire 0; trigger misses 0; kill cells without a kill record 0;
    four-rank fires not as expected 0; four-rank kills outside traffic 0 (the kill came 7 955–8 056 ms after the last
    kernel launch and 6 945–7 045 ms before the earliest nominal traffic end, n=30 kill trials); watchdog lines or
    firmware overruns outside the two firmware cells 0; rank 1 initiating in `pq_repost_r1_b` 0/15; the race cells
    cancelled while waiting for the ACK in 15/15 (HELLO form) and 10/10 (PROBE form), and every responder's first
    decline was "peer closed the socket before DONE (ETIMEDOUT)"; copy timeout on the held rank in every copy-hold
    trial; a watchdog line in every firmware-cell trial.
- **Setting checks: 0 problems in 203 trials.**
- **Hold logs.** All 203 start and result lines match their trial files in `hold.sh` order with no difference in port,
  tries, skipped, decoy, rc, left or wall_s, and every trial's log lies inside its hold's window. 50 SIGKILL lines, each
  matching one of the 50 `kill.out` files. `chain.out`: H1–H8 rc 0; `gin-` iptables rules 0 before and after every hold.
- **Stop criteria.** No STOP file; `LEFT_STREAK` 0; `left` 0 in every trial; no rank exit 139; no illegal-address or
  launch-failure string in any log or kv. Per hold: rain cmd_err 2→2, sunny 0→0, rain firmware-command failures 31→31.
  One new mlx5 line in H1 (sunny, "FWTracer: Events were lost"), not a command-error line.
- **Exit codes** per cell key are uniform: decline cells 4/4; transparent cells 0/0; killed rank 255 (rank 0 kill: 137);
  `pq4_local_shrink@hq` ranks 2 and 3 exit 8 (phase bound); `pq4_fwslow@hq` ranks 2 and 3 exit 0, `@hf` rank 2 exits 4.

## 4. Verdicts `[measured]`

37 holds, 0 fails, 0 data insufficient. "n" is judged trials; "hits" the trials meeting the rule's condition.

| What was predicted | id | cell | n | hits | rule | verdict |
|---|---|---|--:|--:|---|---|
| Responder rejects its plan before commit: rank 0 never plans, nobody logs a recovery, both decline, rank 0 with the plan NACK | A1 | `pq_repost_r1_b@hq` | 10 | 10 | ≥9 | holds |
| Control: rank 0 re-posts and logs a recovery, then declines | A2 | `pq_repost_r1_b@hf` | 5 | 5 | ≥4 | holds |
| Regression: initiator rejects the second QP, nobody re-posts, both decline | A3 | `hd_repost_f1_b@hq` | 5 | 5 | =5 | holds |
| Regression, two ranks: watchdog trips once at 3.0–3.5 s in commit, releases with fw-watchdog, abort within 6 s, helper detached, rank 1 declines | B1 | `hd_fwslow_f1_b@hq` | 5 | 5 | =5 | holds |
| Four ranks: the overrun declines only rank 1; the later rank 2 / rank 0 round recovers | B2 | `pq4_fwslow@hq` | 10 | 10 | ≥9 | holds |
| Only the overrun pair's per-peer words, no devComm word | B3 | `pq4_fwslow@hq` | 10 | 10 | ≥9 | holds |
| Every edge other than 0>1 and 1>0 ends ok | B4 | `pq4_fwslow@hq` | 10 | 10 | ≥9 | holds |
| Control: the overrun is permanent, rank 0 refuses rank 2's round, rank 0's other edges fail | B5 | `pq4_fwslow@hf` | 5 | 5 | ≥4 | holds |
| Rank 3 killed, per-peer flush: the six survivor edges all ok | K1 | `mr4_kill3_peer@hq` | 10 | 10 | ≥9 | holds |
| Each survivor declines only rank 3 as dead, raises only rank 3's word, no devComm word | K2 | `mr4_kill3_peer@hq` | 10 | 10 | ≥9 | holds |
| Sends to rank 3 fail, receives from it end on their own timeout, all survivors see the async error | K3 | `mr4_kill3_peer@hq` | 10 | 10 | ≥9 | holds |
| Control: the six survivor receives fail, sends finish | K4 | `mr4_kill3_peer@hf` | 5 | 5 | ≥4 | holds |
| Context-wide flush: survivor sends fail, survivor receives end on their own timeout | K5 | `mr4_kill3@hq` | 5 | 5 | ≥4 | holds |
| Local cause (copy bound on rank 0): the shrink keeps the stock answer and names the local cause | H1 | `pq_copystall_shrink_b@hq` | 10 | 10 | ≥9 | holds |
| Control: the same shrink goes on to a 1-rank child with a correct allreduce | H2 | `pq_copystall_shrink_b@hf` | 5 | 5 | ≥4 | holds |
| Cause on rank 1: rank 0 records peer-reported, rank 1 local, the shrink goes on | H3 | `pq_copystall1_shrink_b@hq` | 5 | 5 | ≥4 | holds |
| Regression: peer death gives peer-dead and the shrink goes on | H4 | `hd_shrink_b@hq` | 5 | 5 | ≥4 | holds |
| Four ranks, rank 3 killed: three shrinks go on, the 3-rank child opens its devComm, six child edges ok | H5 | `pq4_kill3_shrink@hq` | 10 | 10 | ≥9 | holds |
| Four ranks, local cause on rank 0: its shrink keeps the stock answer, no child | H6 | `pq4_local_shrink@hq` | 5 | 5 | ≥4 | holds |
| (Limit) ranks 2 and 3 wait in the child creation until the 12 s phase bound | H7 | `pq4_local_shrink@hq` | 5 | 5 | ≥4 | holds |
| Control: rank 0's shrink goes on, every survivor gets a 3-rank child | H8 | `pq4_local_shrink@hf` | 5 | 5 | ≥4 | holds |
| HELLO form: rank 1 answers the re-dial with FAIL, rank 0 declines within 1.5 s of the mute end | C1 | `pq_ackrace_f1_b@hq` | 10 | 10 | ≥9 | holds |
| Control: rank 0 waits out the reconnect bound, declines "liveness unknown" ≥5 s after the mute end | C2 | `pq_ackrace_f1_b@hf` | 5 | 5 | ≥4 | holds |
| PROBE form: rank 0 answers the probe with FAIL, rank 1 declines within 1.5 s | C3 | `pq_ackrace_f1r1_b@hq` | 5 | 5 | ≥4 | holds |
| Control: rank 1 declines "liveness unknown" ≥5 s after the mute end | C4 | `pq_ackrace_f1r1_b@hf` | 5 | 5 | ≥4 | holds |
| No main-run trial fails to bind its rendezvous port | Q1 | `all@all` | 203 | 0 bind failures | =0 | holds |
| Held candidate skipped, decoy gets no byte and is rejected, both ranks verify, transparent | Q2 | `pq_rdv_b@hq` | 5 | 5 | =5 | holds |
| Same with four ranks | Q3 | `pq4_rdv@hq` | 3 | 3 | =3 | holds |
| Recovery cells stay transparent (per cell) | R1 | `f1_b`, `f3_b`, `bidirf_sym_b` `@hq` | 5, 5, 5 | 5, 5, 5 | =5 each | holds |
| Two ranks, kill: peer-dead decline within 2 s, devComm word follows | R2 | `f4_b@hq` | 5 | 5 | =5 | holds |
| Receive-only rank's waitSignal released within 2 s of the sender's kill | R3 | `hd_rxdeath_b@hq` | 5 | 5 | =5 | holds |
| Remote access error: decline, receiver released with an error, abort within 5 s | R4 | `f2rel_b@hq` | 5 | 5 | =5 | holds |
| Production kill: dead within 2 s, one death, no informational line at WARN | R5 | `hdp_kill_b@hqp` | 5 | 5 | =5 | holds |
| Four ranks, no fault and one pair's local QP error: transparent (per cell) | R6 | `mr4_none`, `mr4_f1_01` `@hq` | 5, 5 | 5, 5 | =5 each | holds |
| Statistics API: one round, one recovery, no decline | R7 | `f1_b@hq` | 5 | 5 | =5 | holds |
| 4 KiB p50, production build vs gin-handoff production | P1 | `lat_4k@hqp` vs `@hfp` | 5/5 | +0.06 µs | ≤0.40 | holds |
| 256 KiB p50 | P2 | `lat_256k@hqp` vs `@hfp` | 5/5 | −0.03 µs | ≤0.30 | holds |

No rule had a missing trial. Margins: every timing rule holds with a wide margin except the lower bound of the two-rank watchdog
rule (B1): the
watchdog line's `has run <x> ms` is exactly "3000" in 5/5 (the line prints whole ms; the rule is `3000 <= x`)
`[measured]`. The same value is printed in all 10 trials of the four-rank firmware cell.

## 5. Key numbers (each range says what it is a range of) `[measured]`

**Port fix.**
- Bind failures: 0 in 203 trials (rank logs) and 0 "Address already in use" in the hold logs. Rendezvous ports
  29019–30999 over the 203 trials (all inside 29000–30999; 193 distinct).
- Port picks: 1 candidate in 195 trials, 2 in 7, 4 in 1. Every multi-candidate pick is a held-port trial. No trial
  without a held port skipped a candidate. In `pq_rdv_b` n5 the pick skipped 29354 (held), 29355 and 29356; those were
  n1's rendezvous and decoy ports earlier in the same hold [inferred: their sockets were still in TIME_WAIT].
- Held first candidate skipped: 8/8 (5 two-rank, 3 four-rank). Decoy: 1 connection and 0 bytes in each of 5 two-rank
  trials; 3 connections and 0 bytes in each of 3 four-rank trials. The decoy was rejected by rank 1 in 5/5 and by ranks
  1–3 in 3/3.
- Verified rendezvous, counted per rank kv: `hq` 180/180, `hqp` 30/30, `mr/hq` driver with `hq` libnccl 212/212, with
  `hf` libnccl 60/60. The two-rank `hf`/`hfp` controls use the old driver and write no `rdv` key (40 and 20 rank files),
  as EXPERIMENT.md 9.2 says. `rdv_rejected` summed over ranks > 0: 0; `rdv_foreign` on rank 0: 0.

**Per-peer release, four ranks, rank 3 killed** (pooled ranges are over three survivors × the trials).
- Survivor edges ok per trial: `mr4_kill3_peer@hq` 6/6 in 10/10; `@hf` 0/6 in 5/5 (all six survivor receives failed
  with "remote process exited or there was a network error", survivor sends 0 failed); `mr4_kill3@hq` (context-wide
  flush) 0/6 in 5/5 (6 sends failed, 6 receives ended "timeout"); `pq4_kill3_shrink@hq` 6/6 in 10/10.
- Edges to rank 3: 3/3 failed at the sender in every kill trial of both builds. Receives from rank 3: "timeout" in
  every `hq` trial, "remote process exited ..." in every `hf` trial. Async error on r0, r1, r2 in every trial.
- First decline after the kill (rank 0 clock): `mr4_kill3_peer@hq` 6.1–18.5 ms (n=30), `@hf` 6.5–8.9 ms (n=15),
  `mr4_kill3@hq` 6.3–15.2 ms (n=15), `pq4_kill3_shrink@hq` 5.8–8.9 ms (n=30). From "judged dead" to the decline on the
  same rank's clock: 5.4–8.5 ms across all four cells. "Judged dead" after the kill: −0.2–10.2 ms (the negative end is
  the clock-offset error, round trip ≈0.1 ms) [inferred].
- Survivor kernels ended 8 197–9 536 ms after the kill in `mr4_kill3_peer@hq` (the receive from rank 3 runs to its own
  bound) and 7 109–7 393 ms in `@hf` (senders finish their 1 000 iterations [inferred]). The first async error came
  6–19 ms after the kill in `mr4_kill3_peer@hq` and 7–9 ms in `@hf`.
- Words raised: `hq` per-peer words exactly "0-3;1-3;2-3" in 10/10 (`mr4_kill3_peer`), 5/5 (`mr4_kill3`), 10/10
  (`pq4_kill3_shrink`), with 0 devComm-word error lines; causes "peer-dead" three times per trial. `hf`: no per-peer
  line, three devComm-word error lines per trial.

**Plan before commit (two ranks).**
- `pq_repost_r1_b@hq` (n=10): rank 1 rejected its plan at QP 1 of 4 in 10/10; rank 0 validated no plan; recovered
  lines 0 on both ranks; rank 0 declined with "peer NACK (its re-post plan was rejected)" (the plan NACK) in 10/10;
  causes unknown on both ranks.
- `pq_repost_r1_b@hf` (n=5): rank 1 rejected at QP 1 of 4 after DONE; rank 0 logged one recovered initiator round per
  trial (it had re-posted) and then declined "the peer declined".
- `hd_repost_f1_b@hq` (n=5): rank 0 rejected at QP 1 of 4; rank 1 had validated its own plan as responder (1 line per
  trial) but re-posted nothing (recovered 0); rank 1 declined "peer FAIL before DONE".
- Re-posts per rank (recovered lines r0/r1): `hq` responder-rejects 0/0 (10/10), `hf` 1/0 (5/5), `hq` initiator-rejects
  0/0 (5/5).

**Per-round firmware watchdog.**
- `hd_fwslow_f1_b@hq` (n=5): one trip per trial in phase commit at "3000 ms"; first devComm-word line why
  fw-watchdog; abort 650.6–1 002.2 ms (range over 5 trials); helper detached in 5/5; rank 1 declined "peer closed the
  socket before DONE (FIN)".
- `pq4_fwslow@hq` (n=10): one new-format trip "rank 0 - peer 1, commit" at 3000 ms; no old-format or "surfaces" line;
  declines exactly 0-1 (watchdog) and 1-0 ("peer FAIL before DONE"); rank 2 initiator and rank 0 responder recovered
  their later round in 10/10; per-peer words only 0-1 and 1-0; no devComm-word error line; bad edges exactly 0>1 and
  1>0. Rank 0 declined rank 1 4 057–4 067 ms after its hook fired; rank 2's hook fired 1 433–1 443 ms after that
  decline (ranges over 10 trials).
- `pq4_fwslow@hf` (n=5): one old-format trip and one "the fault surfaces" line per trial; rank 0 refused rank 2's round
  with "the watchdog surfaced a fault earlier"; no recovery; devComm-word lines on ranks 0 (fw-watchdog), 1 and 2
  (declined); 9 bad edges per trial, of which 3 among 0>2, 0>3, 2>0, 3>0.

**FAIL on reconnect** (decline time after the same rank's mute end; ranges over the trials of each cell).
- HELLO form: `hq` 234–437 ms (median 370, n=10), reason "the peer declined this pair (FAIL on reconnect)", rank 1
  answered the re-dial with FAIL in 10/10, FAIL received to decline 0.2 ms; `hf` 8 254–8 458 ms (median 8 317, n=5),
  reason "... peer liveness unknown (ETIMEDOUT, no reconnect within 10000 ms)", 16 re-dials "not accepted (FIN)" per
  trial.
- PROBE form: `hq` 227–276 ms (median 259, n=5), rank 0 answered the probe with FAIL in 5/5, FAIL received to decline
  1.2–1.4 ms; `hf` 8 231–8 285 ms (median 8 246, n=5), "liveness unknown".
- Cell conditions in the main run: cancel 5 217–5 448 ms after the round started (all 25 race trials); mute end
  1 543–1 777 ms after the cancel; the responder's abort started 12 036–12 084 ms after its decline
  (`GIN_TS_END_WAIT_S=12`).

**Cause-based shrink hand-off.**
- Two ranks: `pq_copystall_shrink_b@hq` cause r0 local, r1 peer-reported (10/10); rank 0 kept the stock answer with
  "... with a cause that is not the peer's (local)" and the shrink returned "remote process exited or there was a
  network error", no child (10/10). `@hf`: hand-off passed, 1-rank child, allreduce correct (5/5).
  `pq_copystall1_shrink_b@hq`: cause r0 peer-reported, r1 local, hand-off passed, 1-rank child, allreduce correct
  (5/5). `hd_shrink_b@hq`: cause peer-dead, passed, 1-rank child, allreduce correct (5/5).
- `pq4_kill3_shrink@hq` (n=10): 3 pass lines and 0 keep lines per trial; child outcome ok on ranks 0, 1, 2 in 10/10;
  child created with 3 ranks on all three; child devComm "no error" with 6 GIN contexts, opened in 158.4–169.7 ms
  (n=30 ranks); child tx ok 6 and rx ok 6 per trial; child async "no error". Shrink call 10.0–1 297.6 ms (n=30 ranks).
- `pq4_local_shrink@hq` (n=5): rank 0 one keep line "(local)", shrink failed in 0.1 ms; ranks 2 and 3 timed out at the
  12 s phase bound (exit 8); no child created anywhere; one local cause per trial. `@hf` (n=5): rank 0 passed, three
  survivors created a 3-rank child (outcome "created", no child traffic by design).

**Regression.** `f1_b`, `f3_b`, `bidirf_sym_b`, `mr4_none`, `mr4_f1_01` transparent 5/5 each. `f1_b` statistics API
1 round, 1 recovered, 0 declined on both ranks 5/5. `f4_b` decline 1.58–1.70 ms after the kill, cause peer-dead,
devComm word why peer-dead. `hdp_kill_b@hqp` decline 1.43–1.68 ms after the kill, one death, no start line and no
informational line at WARN (only the WARN-level path-wait clamp, socket, judged-dead, per-peer, devComm-word and decline lines appear).
`hd_rxdeath_b` rank 1 released 19.9–20.7 ms and saw the async error 1.8–2.1 ms after rank 0's kill. `f2rel_b` rank 0
declined "class REM_ACCESS is not recoverable", rank 1 device_error with 0 phantom waits, its abort returned in
723–747 ms (ranges over 5 trials each).

**Latency** (each run's p50 recomputed from its 3 000 raw samples with the driver's index rule equals the kv value in
20/20 runs). 4 KiB: `hqp` 10.75 µs in 5/5 runs, `hfp` 10.69 µs in 5/5, difference of medians +0.06 µs. 256 KiB: `hqp`
38.88–38.91 (median 38.88), `hfp` 38.88–38.91 (median 38.91), difference −0.03 µs.

## 6. Disagreements and notes

With the hold logs: none. Every hold line agrees with the trial files (section 3).

With EXPERIMENT.md:
1. **The document has not recorded the main run** `[measured]`. It is byte-identical to the tag: status
   `PREREGISTERED`, "last update 09:00", run log ending at the pre-registration, the "main run H1–H8" box unchecked,
   section 14 without the main-run data, sections 15–16 "not measured yet". The hold logs show H1–H8 ran 09:01:02–09:51:37
   with rc 0. Rule 12 of CLAUDE.md asks for these to be updated with the run.
2. **Section 10, first box** says "the tag remains" (`태그 남음`) while section 11 marks the tag done and the tag exists.
   The sentence was frozen in the tag commit itself. Wording only.
3. **Pilot P1 table, `mr4_kill3_peer@hq`**: "the three survivors saw the FIN and declined rank 3 within 8 ms". The pilot
   logs give 8.15, 6.21 and 8.50 ms from the "socket ... closed cause=FIN" line to the decline on ranks 0, 1 and 2
   (same rank's clock; one trial, three ranks) `[measured]`. Within 8.5 ms, not 8 ms. No prediction depends on it.
4. **Section 9 time estimate** "the changed race cells take about 20 s" `[inferred in the document]`: `wall_s` (rank 0's
   run time) was 10.8 s in all 10 `pq_ackrace_f1_b@hq` trials, 18.8–18.9 s at `@hf` and 20.3–20.8 s in the PROBE form
   `[measured]`. In the HELLO form rank 0 is the initiator and exits after its quick decline; only rank 1 stays 12 s
   [inferred]. Hold H1 took 5.5 min against the estimated 6.5 min; the other holds were within 0.2 min of their
   estimates. Planning numbers only.

Checked and in agreement (pilot statements of section 12, pilots not scored): P0/P1 22 trials and P2 4 trials; P0 race
cells: responder ended 0.34–0.38 s after its decline, initiator declined 1.24–1.28 s after the mute end, cancel
5.23–5.26 s after the round, mute end 1.73–1.77 s after the cancel; P2: responder cleanup 12.04–12.07 s after its
decline, decline after the mute end 233 and 272 ms (`hq`) and 8 375 and 8 270 ms (`hf`), 16 re-dials not accepted; P0
responder-rejects cell declined 3.5 ms after its round; port cell 29342 held, 29343 used, decoy 29344 with 1 connection
and 0 bytes; 4 KiB p50 10.75 and 10.69 µs; watchdog at 3 000 ms in commit and abort 937.5 ms; P1 firmware cell rank 0
declined rank 1 4.07 s after its hook and rank 2's hook came 1.43 s later (both builds); child shrinks 10–1 191 ms and
child devComm 163 ms; four-rank port cell skipped 30088 with 3 connections and 0 bytes; pilot exit codes 255 three
times and 8 twice. The section 7 condition text "socket timeout 5.23–5.26 s after the round" cites the pilot; the main
run's range is wider (5.22–5.45 s over 25 race trials); the cell's condition (a cancel while waiting for the ACK, then
the responder's post-commit decline) held in 25/25.

## 7. Limits of this recount

- I did not read `../scripts/ts2/rows.py` or any earlier row extractor, so the "rows.py" columns are my reading of the
  driver and the documents (section 1). Where my definition could differ (for example `transparent_ok`, `rec_init_r0`
  as a count, `kill_in_traffic` using the nominal traffic end), every value used by a rule sits far from its threshold,
  except the two-rank watchdog time (B1), which sits at its lower bound (section 4).
- I did not read `rows_pq.py`, whose header is the original definition of this study's new columns; I used the 3.1
  summary. Wording ambiguities I resolved: `n_uaerr` counts devComm-word lines (not the per-peer lines) with why
  declined, peer-dead or fw-watchdog; `n_pq_on` counts ranks that print this study's start line (the child adds a second
  line per rank in `pq4_kill3_shrink`); `decl` keeps duplicates (none occur).
- I did not access the cluster or the deployed binaries; the bundle check rests on `deploy_check.txt` and the meta paths.
- Earlier-study numbers quoted in EXPERIMENT.md 1 (7 bind failures in 500 trials, the gin-multirank kill results) were
  not recounted here.
