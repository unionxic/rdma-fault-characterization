# blind-apps: independent recount of the main run (QA)

Recount by a separate agent on 2026-10-09, done without the study's scorer. The script is
[../../qa/recount.py](../../qa/recount.py). It is read-only and prints the whole report. Run it from `harness/blind`
with `python3 qa/recount.py --trials`. The output has 385 lines. Nothing in this file is copied from `SCORE.md`. That
file was opened only after the tables below were final, and only to list disagreements (last section).

Marks: `[측정]` recomputed from raw files or git objects, `[추론]` interpretation, `[미확인]` not checked.

## Method

- **Not used.** `score.py` and `rows_blind.py` were neither read nor run. `trials_scored.csv` was not opened. The only
  contact with `score.py` and `rows_blind.py` was hashing their bytes for the PREREG check.
- **Inputs.**
  - The opened seal `schedule.json`.
  - Per trial: `raw/<id>/{r0,r1,a0,a1}.log` and `trial.meta`. `trial.meta` was used for the harness-end flag, the
    mute rule record and the runner's signal-ack time. Exit codes came from the agent logs and were checked against
    `trial.meta` (no mismatch).
  - The 12 reference runs `raw/ref-*`.
  - `judgments.csv`, `predictions.csv`, `calib.json`, `schedule_config.json`, `PREREG.txt`.
  - Git objects of tag `prereg/blind-apps-v1` and commit `46419a49`, read with `git cat-file`, `log`, `diff-tree`
    and `merge-base` only.
- **Definitions.** Every regex was written from EXPERIMENT.md 3.1 and from reading the raw logs. Each one is listed
  at the top of `recount.py`. Choices that 3.1 leaves open:
  - **none trials.** Counted as `applied = 1`, since there is nothing to apply.
  - **Fault time.**
    - Hooks: the hook's fire line on the target rank (`[FAULT-INJECT] forced ...`, `GIN/FAULT: GDAKI fault fired`,
      the NVSHMEM `shot N fire_mono_ms` line). Applied means the moved-QP count is at least 1.
    - kill and stop: the agent's first `sig=KILL` or `sig=STOP` ack with `rc=0`.
    - mute: the rule insertion time `t_on`, with at least 1 rule.
  - **GIN error lines.** The 3.1 list plus three failure lines that only ever appear next to listed ones: `GIN Error
    detected`, `GIN error raised`, `Failed NCCL operation`.
  - **GIN classifier line.** `GIN/QN: device-classified error CQE` is a classification line on the recovery path,
    not an error line. It appears only in the 2 recovered GIN trials.
  - **NVSHMEM.** `library socket closed (FIN)` is neither an error line nor a death line, as recorded in EXPERIMENT.md
    12 at 13:55. Death lines are `FAULT ... peer_fin=1` only.
  - **"Everyone exits 0" in the silent-wrong rule.** Read as every surviving rank.
- **Sanity check** `[측정]`. On the 24 blind fault-free trials and the 12 references, my regexes find 0 error, 0
  recovery, 0 death and 0 management lines. All 36 are transparent.
- **Prediction grammar.** I wrote my own evaluator of the grammar in 3.2:
  - It replaces `count(...)` with the number of selected valid trials for which the inner expression is true.
  - An empty cell is a value whose every comparison is false and whose arithmetic raises an error. A trial whose
    inner expression raises an error is not counted.
  - The result is insufficient data if n < `n_min`, if any selected trial is `UNKNOWN`, or (for E) if a selected trial
    has no judgment.

## Integrity

All `[측정]`.

| Check | Result |
|---|---|
| Tag `prereg/blind-apps-v1` | Points to `7a839ea7`. `PREREG.txt` in the working tree is byte-identical to the tag's |
| 17 tool, config and calibration sha256 in `PREREG.txt` vs working tree | 17/17 match |
| Same 17 vs blobs at the tag | **15/17.** `hold.sh` (line 20) and `chain.sh` (line 14) differ from their committed blobs in one line each. Masking IPv4 addresses makes them equal. Both files were last modified before the tag. `PREREG.txt` hashed the working-tree files, the ones that ran. The committed copies carry a placeholder address. I take this to be the repository's address filter `[추론]` and did not read the filter configuration `[미확인]` |
| Seal sha256 | `ff04f711…` matches `PREREG.txt`, `schedule.json.sha256` and all 9 per-hold lines in `schedule_sha256.txt` (8 holds, G1 twice) |
| Seal header | Its config equals `schedule_config.json`. Its config, predictions and generator sha256 match the files. Its `git_head` `85147b24` is an ancestor of the tag, and predictions, config and generator are unchanged from that commit to the tag. It was created 13:52:28, before the tag commit at 13:52:59 |
| Seal re-derivation | My copy of the `schedule_gen.py` draw, run with the recorded seed, gives exactly the 166 recorded trials |
| Trials vs seal | 166 raw folders, one per seal trial, with no extra folder and no `.partial`. For all 166, the `trial.meta` entry equals the seal entry. `params` equal my own re-derivation from `u_t`, `u_d`, `calib.json` and config. The hook environment and hook rank match the seal's class and target |
| References | 4 per workload (B0 3 + B9 1). The DDP weight sha256 is a single value per rank (`9d051c49…`, the same on both ranks), so the DDP result check is defined |
| Judgments | sha256 `afb3ae06de9254b6…`, equal to the blob in commit `46419a49`. That commit changes only `judgments.csv` and its parent is the tagged commit. Commit time and reflog time are 15:42:00. The seal copy `schedule.json` (and `.sha256`) has mtime 15:42:09.86, 9.9 s after the commit. Every raw file predates the commit. One judgment per seal trial |
| EXPERIMENT.md sections 2, 3, 7, 8 | Byte-identical to the tag (1156, 11354, 4119, 3645 bytes). The whole file is identical too |
| Run safety files | No `STOP_*` file. All 10 `mlx5_new_*.txt` are empty |

What the timeline cannot show: whether anyone read the seal before 15:42 `[미확인]`. EXPERIMENT.md 9.1 and 18 already
name this limit.

## Exclusions

All `[측정]`. Excluded trials are not refilled.

| Cell | Planned | Valid | Not applied | Start failure | Build check failed | Excluded trials |
|---|--:|--:|--:|--:|--:|---|
| `nvs:kill` | 8 | 7 | 1 | 0 | 0 | `20579d16`: run ended before the fault time |
| `nvs:mute` | 8 | 6 | 2 | 0 | 0 | `1bcf6936`: run ended first. `6c4d85ca`: another process's socket on a target port, so skipped |
| `nvs:stop` | 8 | 7 | 1 | 0 | 0 | `dcd30cbc`: run ended first |
| other 15 cells | 142 | 142 | 0 | 0 | 0 | none |
| **all** | **166** | **162** | **4** | **0** | **0** | |

Pilot and demo trials are not in `results/20261009/raw` (only seal ids and `ref-*`).

## Outcome per class vs truth

Valid trials only (n = 162). Columns show machine outcomes from my recount `[측정]`.

| Cell | n | Transparent | Declined | Hung | Silent wrong | Other or unknown | With recovery line | With death line |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| `ddp:none` | 8 | 8 | 0 | 0 | 0 | 0 | 0 | 0 |
| `ddp:sqp` | 10 | 10 | 0 | 0 | 0 | 0 | 10 | 0 |
| `ddp:rqp` | 10 | 10 | 0 | 0 | 0 | 0 | 10 | 0 |
| `ddp:srq` | 6 | 6 | 0 | 0 | 0 | 0 | 6 | 0 |
| `ddp:kill` | 8 | 0 | 8 | 0 | 0 | 0 | 0 | 8 |
| `ddp:stop` | 8 | 8 | 0 | 0 | 0 | 0 | 0 | 0 |
| `ddp:mute` | 6 | 6 | 0 | 0 | 0 | 0 | 0 | 0 |
| `gin:none` | 8 | 8 | 0 | 0 | 0 | 0 | 0 | 0 |
| `gin:qperr` | 16 | 2 | 0 | 14 | 0 | 0 | 2 | 0 |
| `gin:kill` | 10 | 0 | 3 | 7 | 0 | 0 | 0 | 10 |
| `gin:stop` | 10 | 10 | 0 | 0 | 0 | 0 | 0 | 0 |
| `gin:mute` | 12 | 12 | 0 | 0 | 0 | 0 | 0 | 0 |
| `nvs:none` | 8 | 8 | 0 | 0 | 0 | 0 | 0 | 0 |
| `nvs:qperr` | 14 | 14 | 0 | 0 | 0 | 0 | 14 | 0 |
| `nvs:remacc` | 8 | 0 | 0 | 8 | 0 | 0 | 0 | 0 |
| `nvs:kill` | 7 | 0 | 0 | 7 | 0 | 0 | 0 | 0 |
| `nvs:stop` | 7 | 5 | 0 | 0 | 2 | 0 | 0 | 0 |
| `nvs:mute` | 6 | 6 | 0 | 0 | 0 | 0 | 0 | 0 |
| **all** | **162** | **113** | **11** | **36** | **2** | **0** | | |

Notes `[측정]`:
- **DDP unnotified receive-QP error.** All 6 recovered through the sender's retry-exceeded CQE (`RETRY_EXC_ERR`,
  then `send comm: recovered`). None hung, and no torch timeout or WAITREQ line appears anywhere in the run.
- **GIN QP error.** In 14 of 16 trials both ranks print nothing after the hook and are killed at the 60 s wall cap.
- **Two silent-wrong NVSHMEM trials.** `37bd4c3d` and `800579c9` are both `nvs:stop` with target PE 1 (stop 5.1 s
  and 2.8 s). In each, PE 1 printed 8 388 607 `error, data[` lines (200 kept, 8 388 407 counted by the agent). There
  is no error line, both PEs exit 0, and PE 0 printed all three size lines.
- **Killed survivors.**
  - NVSHMEM kill: all 7 survivors print only `library socket closed (FIN)` and are ended by the 20 s grace.
  - GIN kill: 7 of 10 survivors are ended by grace after the decline lines, and 3 exit 1 on their own.

## Predictions

My evaluator, applied to the 162 valid trials `[측정]`. Hits are the values of the `count()` terms.

| What was predicted | id | Selection | n (plan) | Hits | Verdict |
|---|---|---|--:|---|---|
| DDP, no fault: transparent in n − 1 or more | D1 | `ddp:none` | 8 (8) | 8 | holds |
| DDP, send-QP error: transparent with a recovery line in 90% or more | D2 | `ddp:sqp` | 10 (10) | 10 | holds |
| DDP, receive-QP error with notice: same | D3 | `ddp:rqp` | 10 (10) | 10 | holds |
| DDP, receive-QP error without notice: torch timeout hang within 45 s in n − 2 or more, the rest transparent | D4 | `ddp:srq` | 6 (6) | hung with timeout 0; hung or transparent 6 | **fails** (0 hung, all 6 transparent) |
| DDP, kill: survivor errors within 5 s and ends within 20 s, n − 1 or more | D5 | `ddp:kill` | 8 (8) | 8 | holds (error 0.056–0.070 s, end 0.295–0.383 s) |
| DDP, 2–12 s stop: transparent with no death line, n − 1 or more | D6 | `ddp:stop` | 8 (8) | 8 | holds |
| DDP, 6–14 s management cut: same | D7 | `ddp:mute` | 6 (6) | 6 | holds |
| GIN, no fault: transparent | G1 | `gin:none` | 8 (8) | 8 | holds |
| GIN, QP error: transparent with a recovery line in 85% or more | G2 | `gin:qperr` | 16 (16) | 2 | **fails** (14 hung at the wall cap) |
| GIN, kill: all declined or hung, error within 5 s in n − 1 or more | G3 | `gin:kill` | 10 (10) | 10; 10 | holds (error 0.000–0.002 s after the ack) |
| GIN, 1–8 s stop: transparent with no death line | G4 | `gin:stop` | 10 (10) | 10 | holds |
| GIN, 2–8 s helper-port cut: same, n − 2 or more | G5 | `gin:mute` | 12 (12) | 12 | holds |
| NVSHMEM, no fault: transparent | N1 | `nvs:none` | 8 (8) | 8 | holds |
| NVSHMEM, QP error: transparent with a recovery line in 85% or more | N2 | `nvs:qperr` | 14 (14) | 14 | holds |
| NVSHMEM, remote-access revoke: all declined or hung, error within 3 s in n − 1 or more | N3 | `nvs:remacc` | 8 (8) | 8; 8 | holds (error 0.005–0.008 s, all hung at the wall cap) |
| NVSHMEM, kill: same | N4 | `nvs:kill` | 7 (8) | 7; 0 | **fails** (all hung, no error line at all) |
| NVSHMEM, 1–8 s stop: transparent with no death line | N5 | `nvs:stop` | 7 (8) | 5 | **fails** (2 silent wrong) |
| NVSHMEM, 4–10 s management cut: same | N6 | `nvs:mute` | 6 (8) | 6 | holds |
| GIN and NVSHMEM: no silent-wrong result | X1 | `gin:*+nvs:*` | 106 (110) | 2 | **fails** (`37bd4c3d`, `800579c9`) |
| DDP: no silent-wrong result | X2 | `ddp:*` | 56 (56) | 0 | holds |
| Evaluator's outcome equals the machine's in 85% or more | E1 | `*:*` | 162 (166) | 162 | holds |
| Evaluator names the class of QP-error hook trials in 80% or more | E2 | 4 hook cells | 50 (50) | 50 | holds (but see the leak section) |
| Evaluator names the class of kill trials in 90% or more | E3 | 3 kill cells | 25 (26) | 25 | holds |
| Evaluator calls fault-free trials fault-free in 75% or more | E4 | `*:none` | 24 (24) | 24 | holds |
| Evaluator names DDP stop and cut in 60% or more | E5 | `ddp:stop+ddp:mute` | 14 (14) | 11 | holds (3 cuts called none) |

**Verdicts: 20 hold, 5 fail, 0 insufficient data** `[측정]`. System predictions: 15 hold, 5 fail. Evaluator
predictions: 5 hold.

Trials that make a term false:
- D4 term 1: `a27938a8 37f61f7b b3596cab fb20e695 a5497f6d 55f19881`
- G2: `5cc2b822 cbeece3e be33f162 b11ce946 2985f04b 93b96765 46548938 4697f8f1 1f3a059c d3b36aba e1a39229 e5b41fdd ed8a659a a4157450`
- N4 term 2: `6fd46a59 d047aadd 2f9ea2f0 76712ff9 bdc23a73 21a06d5e 929d7e4b`
- N5: `37bd4c3d 800579c9`
- E5: `9246c035 edad63f4 8a85d9e2`

**Evaluator overall** `[측정]`, over the 162 valid trials:
- Outcome: 162/162.
- Class: 141/162. The misses are DDP cut called none (3), GIN cut called none (12) and GIN stop called cut (6).
- Target rank: 102/114 targeted trials.
- `first_error_s`: within 0.05 s of my first error line on all 26 trials that have one. Blank on the 136 that have
  none.

## Blinding leak

How the evaluator's view is built `[소스]`:
- `handoff.py` writes each rank's file through `strip_hooks.view()`, which drops whole lines that match `HOOK`.
- NCCL prints every `WARN` as a blank line followed by the WARN text. Each arrives as its own log line `[측정]`.
- So when a GIN or Stage 2 hook line is a WARN, its blank line stays in the view. I call this an orphan blank.
- NVSHMEM's hook lines (`[nvshmem-fault-inject] ...`) are plain lines, so they leave nothing.

`recount.py` rebuilds every view with `strip_hooks.view` and counts orphan blanks `[측정]`:

| Cell | Trials | Orphan blank on the target rank only | Double or trailing blank visible in the view |
|---|--:|--:|--:|
| `gin:qperr` | 16 | 16 | 16 |
| other GIN cells and GIN references | 40 + 4 | 0 | 0 |
| `ddp:sqp`, `ddp:rqp`, `ddp:srq` | 26 | 26 (`srq`: two at the same instant) | 26 |
| other DDP cells and DDP references | 30 + 4 | 0 | 2 (trailing blank after a C++ backtrace in 2 kill trials, not hook-related) |
| NVSHMEM, all cells and references | 54 + 4 | 0 | 58 (both PEs' views have double blanks in every NVSHMEM run, so the pattern carries no information) |

What it exposed:
- **GIN QP error, all 16 trials** `[측정]`. The view shows two orphan blanks on the target rank only:
  - The armed line, 1.8–3.0 ms before the anchor.
  - The fired line, at the anchor plus 0.008–0.115 s.

  So the view reveals the class, the target rank and the fire time. The pattern appears in no other GIN trial or
  reference.
- **GIN QP-error trials that hung (14)** `[측정]`. Neither rank has a recovery, error or death line, so the orphan
  blanks are the only in-log evidence of the class. The evaluator called class and target right in 16/16 GIN QP-error
  trials, and its evidence cites the "injector-removal artifacts" in all 16. It cites them in no other trial.
- **E2 depends on the leak** `[측정, 추론]`.
  - As judged, E2 is 50/50.
  - Counting the 14 hung GIN QP-error trials as misses gives 36/50, below the required 40, so E2 would fail.
  - Dropping those 14 gives 36/36, which holds.
  - The evaluator might still have reached the class by elimination: a silent hang to the wall cap fits no other GIN
    class in the brief `[추론]`. Even so, the target rank (14/14 right) came only from the leak. No prediction scores
    the target.
- **DDP hooks, all 26 trials** `[측정]`. The same artifact sits on the target rank. Class and target are also visible
  from the recovery lines, which name the send or receive side, how the incident arrived, and the peer's retry-exceeded
  CQE for `srq`. The evaluator's evidence cites only those lines, so the leak was redundant there `[추론]`.
- **E1, E3, E4, E5** `[추론]`. The leak did not touch the outcome evidence (exit codes, harness ends, PASSED, sha256,
  validation lines), kill evidence (signal 9 "not ended by the harness", by design), or the fault-free and DDP stop
  and cut trials, which have no orphan blank.
- **Over-strip, no leak** `[측정]`. `HOOK` contains `BLIND_` and is case-insensitive, so it also drops nanoGPT's
  `Overriding: out_dir = /tmp/blind_ddp_out`. That is 2 lines in every DDP trial and every DDP reference. The line is
  identical everywhere and carries no information.

**GIN kill timing.** I found no pipeline leak. The evaluator wrote that "rank-0 injections land 14–28 ms after the
header, rank-1 injections 33–107 ms". This matches the 10 GIN kill trials `[측정]`:
- The survivor's first error line comes at anchor + 13, 14 and 26 ms for the 3 rank-0 kills.
- It comes at anchor + 32 to 106 ms for the 7 rank-1 kills.
- Kill is overt by design: signal 9 in `exit.txt` and the survivor's FIN and decline lines.

The split comes from the seal, not the harness:
- The 3 rank-0 kills drew the 3 smallest `u_t` (0.078, 0.093, 0.183). The 7 rank-1 kills drew 0.228–0.903.
- The generator draws target and `u_t` independently, and `derive()` uses only `u_t`. The chance of this ordering is
  1/120 `[측정, 추론]`.
- The kill-to-ack path via ssh adds only milliseconds.

The evaluator then applied this "rule" to GIN stop trials. Only 4 of 10 were called stop, 3 with the right target.
The other 6 were called cut. So the kill timing told the evaluator nothing true about other trials. It affects no
prediction: the stop-class misses are not scored, and G4 is outcome-based `[측정]`.

## Disagreements with SCORE.md

I read `SCORE.md` after the tables above were final. I did not open `trials_scored.csv`.

- **Verdicts: no disagreement.** Both give 20 hold and 5 fail (D4, G2, N4, N5, X1). Both have the same n for every
  prediction and the same substituted expression for all 25 `[측정]`.
- **Falsifying trials: no disagreement.**
  - D4, G2, N4, N5 and E5 list exactly my trials.
  - SCORE.md's X1 list (104 ids) is exactly my valid GIN and NVSHMEM set minus the 2 silent-wrong trials.
  - Its X2 list (56 ids) is exactly my valid DDP set.
  - Both were checked by script against the seal `[측정]`.
- **Exclusions: no disagreement.** Both exclude 4 trials in the same cells (`nvs:kill` 1, `nvs:mute` 2, `nvs:stop`
  1) and find 0 start failures. SCORE.md's table has no build-check column. I find 0 build-check failures.
- **Seal and references: no disagreement.** Both find the seal hash equal to PREREG, the re-derivation OK, 0 entry
  mismatches, 0 missing trials, the DDP reference hashes agreeing, and judgments sha256 `afb3ae06…`.
- **Not covered by SCORE.md.**
  1. The tag-blob mismatch of `hold.sh` and `chain.sh` (explained above, IPv4 address only).
  2. The blinding leak and E2's dependence on it.
  3. The judgments-commit vs seal-copy timeline.

  These are additions, not contradictions.
- **Limit.** I did not compare per-trial columns (`dt_err`, `n_rec` and so on) with the scorer's table, because
  that table was off limits. Agreement at the trial level is inferred from the identical lists and counts `[추론]`.
