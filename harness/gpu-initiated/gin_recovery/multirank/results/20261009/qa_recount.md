# gin-multirank: independent recount of the main run

2026-10-09. Independent recount agent. Script: [`../../qa/recount.py`](../../qa/recount.py) (read-only on the data; run
`python3 qa/recount.py` from the study folder, `--trials` adds one line of columns per trial). Every number below comes
from that script's output on `results/20261009/` unless it is marked otherwise.

Marks: `[measured]` read or recomputed from the raw files, `[inferred]` interpretation, `[unverified]` not checked.

## Method

- **Not read, not run:** `score.py`, `rows_mr.py`, `results/20261009/SCORE.md`, `results/20261009/trials_scored.csv`,
  any `trials_*.csv`, `../s2_close/score.py` (the evaluator the study imports). No cluster action, no GPU or RDMA program.
- **Read:** `EXPERIMENT.md` (working tree and tag), `predictions.csv`, `PREREG.txt`, `gin_mr.cu`, `run_mr.sh`, `cells.sh`,
  `hold.sh`, `chain.sh`, the grammar text in `../oneway/EXPERIMENT.md` 3.2 and `../s2_close/EXPERIMENT.md` 3.2, and the
  log format strings of the hd library (`agent_ts2hd/nccl-src/.../gin_host_gdaki.cc`, md5 `36995301`, the same file
  EXPERIMENT.md 1 names), `deploy_check_hd.txt`. The pilot folder `results/20261009_pilot/p0/` was parsed only to check
  statements about the pilot (last section); it is not scored.
- **Git:** only reading commands in the script (`show`, `rev-parse`, `log`, `cat-file`).
- **Inputs per trial:** `<stem>_meta.txt`, `<stem>_r<r>.kv`, `<stem>_r<r>.log`, `<stem>_kill.out`; 137 trials in
  `h1/`–`h7/`. Also every `hold_*.out`, `chain.out`, `snap_*`, `mlx5_*`, `fwcmd_*`, `LEFT_STREAK`.
- **Columns:** every section-3.1 column was rebuilt from the WARN lines and the driver kv, following the 3.1 text.
  Times in rank 0's clock subtract rank 0's kv `clock_offset_ms_r<r>` (rank r's clock minus rank 0's; the driver's
  definition in `gin_mr.cu`). Lists are sorted strings joined with `;` (`async_ranks` with `,`); `ep_peers` and
  `notrts_peers` are sets.
- **Choices where 3.1 leaves room** (each checked for its effect on a verdict, section "Disagreements"):
  - `n_rounds` (used by I3) is not defined in 3.1. Taken as the number of `round K peer P` lines.
  - `bind_fail` (section 8) is not defined in 3.1. Taken as a rank log line starting `bind: `.
  - `n_refused`: the responder's scope-check lines `REQ round ... refused reason=` only (3.1: "응답 쪽 범위 확인의 refused
    줄"), not the initiator's `refused the scope ...; rerunning` line.
  - `kill_in_traffic`: "traffic end" taken as the planned end, kernel launch + iters × 15 ms, per rank.
  - `p50_inter_med`: `statistics.median` of the between-node edges (mean of the two middle values for 8 edges).
  - `async_ranks`: kv `async_first != none`. Using `final_async != no error` gives the same set in every trial
    `[measured]`.
- **Evaluator:** my own implementation of the 3.2 grammar. `count(E)` evaluates E per scored trial of the cell; numeric
  text becomes float, blank becomes a value for which every comparison is false and arithmetic stays blank; `has`,
  `nonempty`, `median(F, "cell@build")`, `abs`, `per cell:` (all cells must hold). A prediction is "insufficient" when a
  cell it needs has fewer scored trials than section 7 plans.

## Pre-registration integrity

| check | result |
|---|---|
| tag `prereg/gin-multirank-v1` | annotated tag on commit `460488de`, committed 2026-10-09 03:40:58 +0900; the worktree HEAD is the same commit `[measured]` |
| sha256 of `predictions.csv` | working tree = `PREREG.txt` = file at the tag = `3a35b6db…192a90ee`; 42 rows `[measured]` |
| `PREREG.txt` | identical to the tag's `[measured]` |
| EXPERIMENT.md sections 2, 3, 7, 8 | byte-identical to the tag (2 502, 26 735, 3 786, 4 519 bytes); the whole file is identical to the tag `[measured]` |
| driver and scripts | `gin_mr.cu`, `cells.sh`, `chain.sh`, `build_mr.sh` byte-identical to the tag. `run_mr.sh`, `hold.sh`, `deploy_mr.sh` differ only in the management-address lines that the repository's `mgmtip` git filter rewrites (compared with addresses masked; addresses not printed) `[measured]` |
| `gin_mr.cu` md5 | `fd90b11f`, as EXPERIMENT.md 5 and `deploy_check_hd.txt` state `[measured]` |
| order | the tag (03:40:58) precedes the first main-run hold (chain start 03:41:05, H1 snapshot 03:44:25) `[measured]` |
| build of every scored trial | meta `lib=hd`, `mrkey=hd`; every rank prints the hd start line `harden=1` (n_hd = n in all 135 trials) `[measured]` |

## Trial set, exclusions, fills

| cell | kind | planned (sect. 7) | run | excluded | scored n |
|---|---|--:|--:|---|--:|
| `mr4_none` | new | 10 | 10 | - | 10 |
| `mr4_none_peer` | control | 5 | 5 | - | 5 |
| `mr3_none` | control | 5 | 5 | - | 5 |
| `mr2_none` | control | 5 | 5 | - | 5 |
| `mr4_f1_01` | new | 10 | 11 | n4 (h3): port bind failure | 10 |
| `mr4_f1_02` | new | 10 | 10 | - | 10 |
| `mr4_f3_01` | new | 10 | 10 | - | 10 |
| `mr4_f1_01_23` | new | 10 | 10 | - | 10 |
| `mr4_f1_10_30` | new | 10 | 10 | - | 10 |
| `mr4_f1all0` | new | 10 | 11 | n3 (h5): port bind failure | 10 |
| `mr4_kill3` | new | 10 | 10 | - | 10 |
| `mr4_kill3_peer` | new | 10 | 10 | - | 10 |
| `mr4_cyc_stall` | new | 5 | 5 | - | 5 |
| `mr4_chain_stall` | control | 5 | 5 | - | 5 |
| `mr3_f1_01` | control | 5 | 5 | - | 5 |
| `mr2_lat` | control | 5 runs | 5 | - | 5 |
| `mr4_lat_solo` | control | 5 runs | 5 | - | 5 |
| `mr4_lat` | exploratory | 5 runs | 5 | - | 5 |

- **Confirmed: two trials excluded for a port bind failure, two fills.** `h3/mr4_f1_01_n4` and `h5/mr4_f1all0_n3`: rank 0's
  log is the single line `bind: Address already in use`, ranks 1–3 end with `WATCHDOG: global deadline exceeded;
  exiting 7`, rc 1/7/7/7, wall 60.3 s, no devComm and no hook fire `[measured]`. The fills are `h3/mr4_f1_01_n11` and
  `h5/mr4_f1all0_n11` (hold `fill`, 05:52:20–05:53:04), the next number as section 8 says; one fill per cell, below the
  50 % stop `[measured]`.
- Scored: 135 = 120 cell trials + 15 latency runs, matching section 7 for every cell; trial ids contiguous from n1 in every
  cell `[measured]`.
- Hold contents match the section-7 plan: H1 `mr4_none` 10, `mr4_none_peer` 5, `mr2_none` 5; H2 the three latency
  cells × 5, `mr3_none` 5, `mr3_f1_01` 5; H3 `mr4_f1_01` 10, `mr4_f1_02` 10; H4 `mr4_f3_01` 10, `mr4_f1_01_23` 10; H5
  `mr4_f1_10_30` 10, `mr4_f1all0` 10; H6 `mr4_kill3` 10, `mr4_kill3_peer` 5; H7 `mr4_kill3_peer` 5, `mr4_chain_stall` 5,
  `mr4_cyc_stall` 5; fill 1 + 1 `[measured]`.
- Other section-8 exclusions, none triggered: every hook trial fired exactly the planned rank:context set inside its
  traffic; every kill trial has `killed = 1` and `kill_in_traffic = 1`; the cycle and chain cells' round-start spread is
  0.6–14.8 ms (range over the 10 trials of both cells; limit 250 ms) `[measured]`.
- Settings check (section 8) on all 135 scored trials: `n_ts_on`, `n_ua`, `n_pr`, `n_pc`, `n_ow`, `n_hd` all equal n;
  gated QPs 36/12/2 for N = 4/3/2; stall switch lines exactly `0:300;1:300;2:300` (cycle), `0:300;1:300` (chain), none
  elsewhere; flush mode as the cell; no same-GPU refusal; no fire in a hook-free cell. No deviation `[measured]`.
- Teardown epoch and QP-state lines exist for every live rank and every peer in every scored trial `[measured]`.

## Predictions

42 predictions: **42 hold, 0 fail, 0 insufficient** `[measured]`. Every scored trial meets the rule of every count-based
prediction (no trial misses any rule). "n" is the number of scored trials of the cell; "hits" the trials meeting the rule.

| id | cell | what was predicted | what the recount found | n | hits | verdict |
|---|---|---|---|--:|--:|---|
| I1 | `mr4_none` | 4 ranks, 2 per GPU, build the communicator and a 12-context devComm; recovery on with 36 gated QPs each | all 10: 4 devComms, 4 "ON" lines, 36/36 gated QPs, no same-GPU refusal | 10 | 10 | holds |
| I2 | `mr4_none` | all 12 edges bit-exact with the exact final signal, no async error | all edges ok in every trial | 10 | 10 | holds |
| I3 | `mr4_none` | no round, decline or watchdog line | none in any trial | 10 | 10 | holds |
| I4 | `mr3_none` | 3 ranks transparent, 12 gated QPs | yes | 5 | 5 | holds |
| I5 | `mr2_none` | 2 ranks transparent, 2 gated QPs | yes | 5 | 5 | holds |
| I6 | `mr4_none_peer` | per-peer flush transparent | yes | 5 | 5 | holds |
| A1 | `mr4_f1_01` | local QP error on 0>1 recovered by one pair round (1 QP) of ranks 0 and 1 only | rounds `0>1:1:pair`, recovered 0-1 / 1-0, no decline, no refusal | 10 | 10 | holds |
| A2 | `mr4_f1_01` | all 12 edges transparent | yes | 10 | 10 | holds |
| A3 | `mr4_f1_01` | only context 0's pair at epoch 2; rank 0's other hooked QPs (to 2, 3) end in ERR | exactly that | 10 | 10 | holds |
| B1 | `mr4_f1_02` | same on the in-node edge 0>2 (NIC loopback), transparent | rounds `0>2:1:pair`, transparent | 10 | 10 | holds |
| B2 | `mr4_f1_02` | only context 1's pair at epoch 2; rank 0's context-1 QPs to 1, 3 in ERR | exactly that | 10 | 10 | holds |
| C1 | `mr4_f3_01` | rank 1's QP forced to ERR makes rank 0 see RETRY_EXC; one pair round, transparent | first record class RETRY_EXC on rank 0, one pair round, transparent | 10 | 10 | holds |
| C2 | `mr4_f3_01` | while 0>1 is held, 0>2 and 0>3 each finish ≥ 100 iterations inside the held iteration | held iteration 3 623–3 844 ms; 236–250 and 235–251 iterations inside | 10 | 10 | holds |
| C3 | `mr4_f3_01` | only context 0's pair at epoch 2; rank 1's context-0 QPs to 2, 3 in ERR | exactly that | 10 | 10 | holds |
| C4 | `mr4_f3_01` | first classifier record 3.0–4.5 s after the hook | 3 540.2–3 758.2 ms | 10 | 10 | holds |
| D1 | `mr4_f1_01_23` | two disjoint pairs: two pair rounds, transparent | `0>1:1:pair;2>3:1:pair`, transparent | 10 | 10 | holds |
| D2 | `mr4_f1_01_23` | exactly those two pairs at epoch 2; each hook leaves two QPs in ERR | exactly that | 10 | 10 | holds |
| E1 | `mr4_f1_10_30` | two initiators (1, 3) to one responder (0): both recovered, transparent | yes | 10 | 10 | holds |
| E2 | `mr4_f1_10_30` | rank 0 answers the two rounds without overlap (rule: 10/10) | second round starts 1.13–1.15 ms after the first resumed | 10 | 10 | holds |
| E3 | `mr4_f1_10_30` | exactly the two pairs at epoch 2 | exactly that | 10 | 10 | holds |
| F1 | `mr4_f1all0` | every QP of rank 0 failed: three full-scope rounds of 12 QPs (reason qp_state), no decline | exactly that | 10 | 10 | holds |
| F2 | `mr4_f1all0` | all 12 edges transparent | yes | 10 | 10 | holds |
| F3 | `mr4_f1all0` | the three rounds do not overlap; 72 epoch-2 entries; all RTS at the end | gaps 0.046–1.118 ms between rounds, 72 entries, no non-RTS QP | 10 | 10 | holds |
| R1 | six recovered cells | no escalation, no firmware or copy bound exceeded, no cancelled round, no peer judged dead | zero such lines in each of the six cells | 10 each | 10 each | holds |
| K1 | `mr4_kill3` | survivors judge rank 3 dead from the socket and decline only rank 3 ("peer judged dead") | declines exactly 0-3, 1-3, 2-3, reason "...socket shows FIN" | 10 | 10 | holds |
| K2 | `mr4_kill3` | each survivor's decline 0–2 000 ms after the kill | 5.99–8.95 ms | 10 | 10 | holds |
| K3 | `mr4_kill3` | context-wide flush: all 6 survivor edges stop with a failed sender | 6 failed senders, 0 ok edges | 10 | 10 | holds |
| K4 | `mr4_kill3_peer` | same declines with the per-peer flush | yes | 10 | 10 | holds |
| K5 | `mr4_kill3_peer` | per-peer flush: 6 survivor receivers fail, 0 senders fail | exactly that; senders finish all 1 000 iterations | 10 | 10 | holds |
| K6 | both kill cells | every survivor sees the async error | `r0,r1,r2` in every trial | 10, 10 | 10, 10 | holds |
| K7 | both kill cells | the decline closes the 36 QPs to rank 3 (epoch 2, ERR) and no other | 36 / p3 / 36 / p3 in every trial | 10, 10 | 10, 10 | holds |
| Y1 | `mr4_cyc_stall` | a cycle of three initiators ends in at least one "handshake timeout", not transparent | 3 handshake timeouts per trial, not transparent | 5 | 5 | holds |
| Y2 | `mr4_cyc_stall` | first handshake timeout 24.3–24.8 s after that rank's first round line | 24 504.5–24 507.2 ms | 5 | 5 | holds |
| Y3 | `mr4_cyc_stall` | no recovery before 24 s, no watchdog line | no recovered line at all, no watchdog | 5 | 5 | holds |
| Z1 | `mr4_chain_stall` | chain without the edge back: last resume within 5 s of the first round line, transparent | 2 080.8–2 089.4 ms, transparent | 5 | 5 | holds |
| Z2 | `mr4_chain_stall` | rank 1 refuses rank 0's pair request, rank 0 reruns a 12-context round; only three QPs not RTS at the end | rounds `0>1:12:peer;0>1:1:pair;1>2:1:pair`, one refusal, non-RTS exactly 0-2-0, 0-3-0, 1-3-4 | 5 | 5 | holds |
| T1 | `mr3_f1_01` | 3 ranks: pair round on 0>1, transparent, rank 0's context-0 QP to 2 in ERR | exactly that | 5 | 5 | holds |
| L1 | `mr2_lat` | 2-rank p50 of 0>1 within 10.0–12.0 µs | 10.69–10.85 µs | 5 | 5 | holds |
| L2 | `mr4_lat_solo`, `mr2_lat` | medians of the 0>1 p50 differ by ≤ 1.0 µs | 10.08 vs 10.72 µs, difference 0.64 | 5, 5 | - | holds |
| L3 | `mr4_lat`, `mr4_lat_solo` | (exploratory) median between-node p50 ≤ 2 × solo p50 | 12.00 ≤ 2 × 10.08 | 5, 5 | - | holds |
| L4 | `mr4_lat` | (exploratory) an iteration ≥ 200 µs in ≥ 4 of 5 runs | 5 of 5 (largest per run 2 323.9–2 357.4 µs) | 5 | 5 | holds |
| L5 | `mr2_lat` | no iteration reaches 200 µs in ≥ 4 of 5 runs | 5 of 5 (largest per run 19.46–23.55 µs) | 5 | 5 | holds |

## Key numbers (re-derived from the raw files)

Each range says what it is a range of. All `[measured]`.

**Initialisation** (per rank, over every rank of every scored trial of the group).

| group | trials, rank runs | `ncclCommInitRankConfig` (kv `init_ms`) | `ncclDevCommCreate` (kv `devcomm_ms`) | process start to kernel launch, per rank | earliest process start to last kernel launch, per trial |
|---|---|---|---|---|---|
| 4 ranks | 115, 460 | 193.8–306.8 ms | 174.0–194.3 ms | 920.5–1 298.8 ms | 1 191.1–1 298.9 ms |
| 3 ranks | 10, 30 | 211.5–326.3 ms | 69.2–74.3 ms | 717.9–1 100.2 ms | 980.5–1 100.3 ms |
| 2 ranks | 10, 20 | 190.5–239.9 ms | 19.8–25.8 ms | 541.7–868.0 ms | 804.0–868.1 ms |

**Fault timing.** Hook fire after the last rank's kernel launch: 5 953.1–5 975.8 ms over all 110 fires of the nine hook
cells (per cell in the script output). Kill after the last kernel launch: 7 991.5–8 036.1 ms (`mr4_kill3`, n=10) and
8 001.0–8 058.1 ms (`mr4_kill3_peer`, n=10), leaving 6 941.8–7 008.4 ms to the earliest planned traffic end (both kill
cells). Kill after rank 3's own process start (same clock): 8 985.4–9 021.2 ms (both cells).

**Recovery rounds** (one line per role and round; `total_us`, `commit_us` as logged; range over the lines of the cell).

| cell | role, QPs | lines | total | commit | resume after the trial's first round line |
|---|---|--:|---|---|---|
| `mr4_f1_01` | initiator, 1 | 10 | 84.7–91.8 ms | 18.7–22.4 ms | 84.0–91.1 ms |
| `mr4_f1_01` | responder, 1 | 10 | 109.3–117.1 ms | 21.8–22.0 ms | 113.0–121.6 ms |
| `mr4_f1_02` (loopback) | initiator, 1 | 10 | 86.7–87.6 ms | 19.6–19.7 ms | 86.0–87.0 ms |
| `mr4_f3_01` | initiator, 1 | 10 | 86.1–91.8 ms | 18.8–22.5 ms | 85.4–91.2 ms |
| `mr4_f1_01_23` | initiator, 1 | 20 | 86.3–91.9 ms | 19.0–22.8 ms | 85.7–101.1 ms |
| `mr4_f1_10_30` | initiator, 1 | 20 | 86.2–204.5 ms (second initiator waits) | 18.7–22.8 ms | 85.5–206.4 ms |
| `mr4_f1all0` | initiator, 12 | 30 | 1 009.2–1 035.4 ms | 260.6–265.4 ms | 1 005.6–3 048.8 ms |
| `mr4_f1all0` | responder, 12 | 30 | 1 327.1–1 339.1 ms | 259.4–264.4 ms | 1 379.7–3 423.3 ms |
| `mr4_chain_stall` | initiator, 1 (rank 1) | 5 | 388.1–392.4 ms (includes the 300 ms stall) | 19.1–21.6 ms | 387.3–391.6 ms |
| `mr4_chain_stall` | initiator, 12 (rank 0 rerun) | 5 | 1 317.5–1 321.3 ms | 261.0–264.8 ms | 1 708.9–1 714.9 ms |
| `mr4_chain_stall` | responder, 12 (rank 1) | 5 | 1 330.4–1 337.6 ms | 260.0–263.8 ms | 2 080.8–2 089.4 ms |
| `mr3_f1_01` | initiator, 1 | 5 | 62.8–65.4 ms | 20.1–20.2 ms | 62.5–65.1 ms |

`mr4_f1all0`: rank 0's three round lines come 21.9–24.0, 1 028.5–1 042.4 and 2 045.7–2 059.3 ms after its hook fire
(n=10). `mr4_cyc_stall`: no recovered line in any trial.

**Kill cells** (rank 0's clock, after the kill; range over the 10 trials of the cell; ranks 0 and 2 on rain, rank 1 on
sunny with rank 3).

| cell | survivor | socket FIN seen | judged dead | first decline |
|---|---|---|---|---|
| `mr4_kill3` | 0 / 1 / 2 | 0.25–0.30 / 0.24–0.35 / 0.25–0.35 ms | 0.28–0.33 / 0.30–0.41 / 0.27–0.38 ms | 8.21–8.74 / 5.99–6.76 / 8.10–8.95 ms |
| `mr4_kill3_peer` | 0 / 1 / 2 | 0.22–0.32 / 0.31–0.35 / 0.27–0.36 ms | 0.25–0.35 / 0.37–0.41 / 0.29–0.38 ms | 8.30–8.76 / 6.03–6.72 / 8.18–8.85 ms |

Survivor edges: with the context-wide flush, senders and receivers stop after 521–527 iterations with "remote process
exited or there was a network error"; with the per-peer flush, senders finish all 1 000 iterations with "no error" and
receivers stop after 522–529 iterations with that error.

**Cycle bound.** `hs_first_after_round_ms` 24 504.5–24 507.2 ms (5 trials). Every one of the 15 "handshake timeout"
declines (3 per trial) came 24 504.5–24 507.3 ms after its rank's first round line, except one: in trial n1 rank 0's
decline of rank 1 came 24 825.8 ms after its first round line, because rank 1 refused rank 0's request first and rank 0
had rerun a 12-context round. The source bound is round start + 24 500 ms.

**Latency** (4 KiB put + signal + flush back to back, 3 000 iterations, sender kv; range over 5 runs; median of the 5 p50s
in brackets).

| cell | edge | p50 per run | largest iteration per run |
|---|---|---|---|
| `mr2_lat` | 0>1 / 1>0 | 10.69–10.85 (10.72) / 12.29 (12.29) µs | 14.88–21.82 / 19.46–23.55 µs |
| `mr4_lat_solo` | 0>1 / 1>0 | 10.05–10.24 (10.08) / 11.26 (11.26) µs | 206.85–217.06 / 15.36–18.43 µs |
| `mr4_lat` | 8 edges between nodes | 10.24–13.31 µs; per-run median over the 8 edges 11.50–12.04 (12.00) | 2 307.07–2 357.44 µs |
| `mr4_lat` | 4 edges inside a node (0>2, 2>0, 1>3, 3>1) | 10.24–12.29 µs | 2 310.14–2 357.22 µs |

Per-edge ranges are in the script output (section 5.6).

## Hold logs and safety

- Every trial has exactly one result line in its hold log; rc, `left`, wall and the DONE lines equal the meta file and the
  rank logs, and each DONE outcome equals the rank's kv outcome (137 of 137) `[measured]`.
- 20 kill lines; each equals its `<stem>_kill.out`, and the killed PID is the PID in rank 3's own log lines `[measured]`.
- `left = 0` in all 137 trials, `LEFT_STREAK` 0, no `STOP_*` or `stale.txt` file `[measured]`.
- 16 snapshots: the mlx5 line counts (rain 66, sunny 510), command-error lines (2, 0) and rain's firmware failed sum (31)
  recomputed from the `mlx5_*` and `fwcmd_*` files equal the snapshot text in every one; new mlx5 kernel lines,
  recomputed as after minus before, 0 in every hold on both nodes; compute mode `Default` on both GPUs throughout
  `[measured]`.
- Hold windows (snapshot to snapshot): H1 03:44:25–03:50:58, H2 03:59:42–04:03:53, H3 04:14:23–04:21:47, H4
  04:34:39–04:41:54, H5 04:56:06–05:03:56, H6 05:16:50–05:20:37, H7 05:35:06–05:41:31, fill 05:52:20–05:53:04; all
  under the 880 s bound `[measured]`.

## Disagreements and notes

No verdict-changing disagreement. Items found:

1. **Column `n_rounds` is not defined in 3.1**, but I3 uses it (`count(n_rounds == 0 and ...)`). Counted here as round
   lines; I3 then holds 10/10. If the study's table lacks the column, the blank rule makes I3 0/10. Check SCORE.md
   `[measured: the 3.1 table has no n_rounds]`.
2. **Column `bind_fail` is not defined in 3.1**, though section 8 excludes on it. The two excluded trials have the
   `bind:` line and no devComm, so any reasonable definition gives the same exclusions `[measured]`.
3. **Z2 depends on counting only the responder's refusal.** With the initiator's "refused the scope ... rerunning" line
   counted too, `n_refused` is 2 in every chain trial and Z2 would fail 0/5. The 3.1 wording (responder's scope check)
   supports the reading used here `[measured counts, inferred reading]`.
4. **`kill_in_traffic` reading.** With the planned traffic end the kill is 6 941.8–7 008.4 ms before it (≥ 5 000).
   Reading "traffic end" as the actual kernel end would exclude every kill trial (the kernels end milliseconds after the
   kill), which cannot be the intent `[inferred]`.
5. **EXPERIMENT.md 3.6, pilot "셀 14개"**: the pilot folder has 17 trials of 16 distinct cells (`mr4_none` twice;
   section 9 step 4 also lists 16) `[measured]`.
6. **F2 basis, "the third started 2022 ms after rank 0's first mailbox record"** (pilot): the third round's `t_start` is
   2 022.0 ms after that round's own mailbox record (peer 3) and 2 039.6 ms after rank 0's first record `[measured]`.
   Basis text only.
7. **The cycle collapses fully on hd.** In trials n2–n5 the three "handshake timeout" declines fell within 1.9–14.6 ms
   of each other (rank 0's clock); in n1 rank 2's and rank 1's came 0.8 ms apart and rank 0's 334.6 ms later, after its
   rerun. Each helper then refused the request that had waited in its socket (`not_rts`, 24 493.6–24 519.9 ms after its
   own first round line). Each of ranks 0, 1, 2 declined both other cycle ranks (6 declines per trial: 3 "handshake
   timeout", the rest "the peer declined" or, once, "peer FAIL before DONE"); no round recovered; rank 3 ended ok. The
   ow pilot trial recovered one round 25.1 s after the first round line. Y1–Y3 hold either way (Y3 through
   `n_rec_i == 0`) `[measured]`.
8. **`mr4_lat_solo` edge 0>1 has one iteration of 206.85–217.06 µs in every run**, although ranks 2 and 3 run no
   kernel; edge 1>0 stays at 15.36–18.43 µs. No prediction covers it (L5 is about `mr2_lat`) `[measured]`; cause
   `[unverified]`.
9. **K2 basis** quotes kill-to-FIN 0.1–0.3 ms (2 ranks). Here the survivors saw the FIN 0.22–0.36 ms after the kill
   (60 sockets). Basis text only `[measured]`.
10. **EXPERIMENT.md is not yet updated for the run.** Status is still `PREREGISTERED`; sections 11–16 have no main-run
    entries, and the two exclusions and the fill hold are not logged in section 12 or 13 `[measured]`. Section 7's
    estimate of about 55 min for H1–H7 compares with 43 min 25 s of snapshot-to-snapshot time (44 min 9 s with the
    fill) `[measured]`.
11. Pilot statements checked and matching: 17 trials on ow; hook fire 5 959.4–5 975.1 ms after the last kernel launch (9
    fires); kill 7 982.9–8 025.8 ms after it (2); cycle spread 17.4 ms, first handshake timeout 24 506.2 ms, first
    recovery 25 118.5 ms; 4-rank process start to kernel launch 919.4–1 278.0 ms (52 rank runs); pair rounds resumed
    85.8–91.7 ms (initiator) and 114.8–118.7 ms (responder) after the initiator's start (4 rounds; the fifth, the
    waiting second initiator of `mr4_f1_10_30`, 204.7 ms); pair-round commit 18.7–22.5 and replay 26.8–38.9 ms (10 lines); 12-context commit 260.2–264.9 and replay 373.4–376.2 ms (6 lines);
    12-context initiator 1 012.1–1 025.5 ms and responder 1 387.1–1 399.1 ms after the initiator's start; decline after
    kill 3 632.1–3 810.1 ms; latency p50 11.07 and 11.04 µs, 4-rank between-node median 12.05 µs, largest 2 335.23 µs;
    the same-GPU negative control refused (no devComm) `[measured]`.
