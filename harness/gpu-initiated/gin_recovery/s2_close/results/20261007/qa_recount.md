# gin-s2-close: independent recount (QA)

Date 2026-10-07. Recount by a separate agent from the raw per-trial files only. Tags: `[measured]` read from raw files,
`[source]` read from code, `[inferred]` interpretation, `[unverified]` not checked.

## 1. Method

- Script: [`../../qa/recount.py`](../../qa/recount.py). Run from the study folder: `python3 qa/recount.py`. It
  writes nothing; it prints the trial set, exclusions, run conditions, latency medians, the 28 verdicts, per-trial values
  and the safety snapshots.
- Not read or run: `score.py`, `SCORE.md`, `trials_scored.csv`, and the untracked `trials_*.csv` in this folder. Read only
  for log formats: `../scripts/ts2/rows.py`, `rows_extra.py`, `gin_ts2.cu` (p50 index rule, receive-wait units), and
  `gin_transparent_s2r.diff` (non-message mask bits, range check). No import of the row scripts.
- Inputs: `<stem>_meta.txt`, `_r{0,1}.kv`, `_r{0,1}.log`, `_kill.out`, `_lat_raw.csv.gz` in `lat/ rep_s2/ rel/ rep_s2r/
  nonmsg/ mute/`, plus `gate_test.txt`, `hold_*.out`, `snap_*.txt`, `fwcmd_*.txt`, `chain.out`.
- Columns follow EXPERIMENT.md 3.1. The rows.py columns (for example `transparent_ok`, `fault_mono_r0`, `bind_fail`) keep
  the meaning rows.py gives them, so their definitions are re-implemented, not independent.
- Acceptance: the `acceptance` text of `predictions.csv` is evaluated verbatim with a small 3.2 evaluator. Numbers become
  floats, blanks None, other values strings. Any comparison or arithmetic with None is false. `per cell:` is applied per
  cell, and `median` is taken over the judged trials of the named cell key.
- Extra check: every latency p50 was recomputed from the 3000 raw samples (driver index rule `v[(int)(0.5(n-1)+0.5)]`).
  All 70 judged runs match the kv `lat_p50_us` to 0.006 µs. All samples are multiples of 32 ns.

## 2. Pre-registration integrity `[measured]`

- `sha256(predictions.csv)` = `0b18ee25…bb563`, the same as `PREREG.txt` and as the file at tag `prereg/gin-s2-close-v1`.
- The tag resolves to commit `883f5816`. `predictions.csv` and `PREREG.txt` have no diff against the tag.
- EXPERIMENT.md sections 2, 3 (3.1–3.3), 7 and 8 are byte-identical to the tag. The diff touches only the header,
  sections 1, 5, 9–14 and the added 15–20.

## 3. Trial set (sections 7 and 8) `[measured]`

- 198 trials (meta files): 72 latency runs and 126 cell trials. Gate micro-test: 14 lines.
- Every cell@build of section 7 is present with the planned count after exclusions. That is 125 cell trials and 70
  latency runs. No cell has more judged trials than planned, so the "over plan" rule of DEVIATIONS.md 2 never applies.
- Run conditions in the meta files (fault, app, iterations, bytes, gap, hook delay, extra environment) match section 7 for
  every cell. Examples: `get_f1_b` hook delay 622–1185 ms over 10 trials; `mt1024_norescue_b` has `RESCUE_LAPS=0` on both
  ranks and triggers at 67 587–174 095 WQEs. `ABORT_WD_S` and `WATCHDOG_S` are not written to the meta `[unverified]`.
- Counted apart: 3 trials. All have `bind: Address already in use` in the rank 0 log, `r0rc=1`, `r1rc=7`, wall 0.0 s.
  - `lat_s2on_4k@s2` n4, `lat_s2r_on_4k@s2r` n2, `mt256_f1_b@s2r` n5.
  - No rank 1 log has a bind error.
  - No other exclusion fires. Every local-QP-error cell fired on rank 0, every peer-QP-error cell on rank 1, there is no
    trigger miss, all 5 kill trials have `_kill.out`, and the get fault fired 563.8–1121.9 ms after launch.
- Refills follow the section 8 rule: each one uses the next number (n6), there is one per cell (20% of plan, at most 50%),
  and all three ran in the fill hold at 20:45:01–20:45:08.
- Settings checks hold for all judged trials.
  - Transparent recovery ON on both ranks in every judged new-library and get-build trial with TS=1.
  - User-abort line on both ranks wherever `NCCL_GIN_TS_USER_ABORT` is not 0.
  - The flag-off cell (`f2rel_off_b`) and the recovery-off cell (`off_f1_b`) have 0 user-abort lines on both ranks.
  - The mute-on line appears once on each rank in all 25 mute trials, and there is no `SO_ATTACH_FILTER failed` line.
  - Only the two excluded bind-failure trials lack these lines.
- Build md5 per trial: **not recorded in the raw data.** The meta records only the bundle path. The md5 values come from a
  single deploy-time check (`deploy_check.txt`, 19:05, both nodes). The per-trial logs are consistent with the build key
  `[measured]`:
  - The "transparent recovery ON" line comes from `gin_host_gdaki.cc:3556` in s2 and var_sys, `:3647` in s2r and s2rget,
    and `:3077` in s1.
  - Only s2r and s2rget print `dev_runtime.cc:1649` (user devComm abort flag).
  - Only s2rget writes `get_mode=1`.
- Smoke: `results/20261007_smoke/` exists (13 trials, hold H0). Not scored and not examined. The smoke-based block gates of
  section 8 (get block, mute block) were therefore not re-evaluated `[unverified]`. The main data agree with both
  mechanisms: fault-free get had `get_n == iters` in 5/5, and the 8 s mute closed the socket in 10/10.

## 4. Per-prediction recount

n = judged trials (runs for latency). A range is min–max over the judged trials of the cell named, unless stated.

| id | prediction | cell key | n | hits | rule | verdict | values |
|---|---|---|--:|--:|---|---|---|
| RA1 | 16 and 64 threads, local QP error, transparent on final build | `mt16_f1_b@s2`, `mt64_f1_b@s2` | 5, 5 | 5, 5 | 5 each | holds | first-round replayed WQEs 16–20 and 30–49 (5 trials each) |
| RA2a | bidirectional symmetric start transparent | `bidirf_sym_b@s2` | 5 | 5 | 5 | holds | |
| RA2b | lower rank keeps, higher rank yields | `bidirf_sym_b@s2` | 5 | 5 | ≥3 | holds | rank 0 kept 1 and rank 1 yielded 1 in every trial |
| RA3 | tie-break off: mostly declined on both sides | `bidirf_sym_notie_b@s2` | 5 | transparent 1, "simultaneous recovery" 4 | ≤2 and ≥3 | holds | the declined 4 decline on both ranks, rc 7/7 |
| RA4a | 4 KiB: step 2 on is 0.30–1.20 µs slower than off | `lat_s2on_4k@s2` vs `lat_s2off_4k@s2` | 5, 5 | | 0.30 ≤ Δ ≤ 1.20 | **fails** | medians 10.56 and 10.27, Δ = 0.29 (0.288 from raw samples); per-run p50 10.56–10.59 and 10.24–10.27 |
| RA4b | 256 KiB: 0.10–1.00 µs slower | `lat_s2on_256k@s2` vs `lat_s2off_256k@s2` | 5, 5 | | 0.10 ≤ Δ ≤ 1.00 | holds | medians 38.91 and 38.66, Δ = 0.25; per-run 38.88–38.91 and 38.46–38.82 |
| RA4c | gate micro-test passes everywhere | `gate_test.txt` | 14 | 14 | 14 | holds | 7 configurations × 2 nodes |
| RB1a | receiver abort returns within 5 s | `f2rel_b@s2r` | 10 | 10 | ≥9 | holds | `teardown_ms_r1` 862.3–876.1 ms; r1rc 3 in 10/10 |
| RB1b | nothing released before abort | `f2rel_b@s2r` | 10 | 10 | 10 | holds | `async_error_kernel_stuck` 10/10; abort began 2300.7–2301.7 ms after rank 1's first async error |
| RB1c | sender still declines the remote access error | `f2rel_b@s2r` | 10 | 10 | 10 | holds | "class REM_ACCESS is not recoverable" |
| RB2 | burst receiver abort within 8 s | `ringf2rel_b@s2r` | 10 | 10 | ≥9 | holds | `teardown_ms_r1` 795.5–811.0 ms |
| RB3 | flag off: receiver abort waits for its 20 s wait (≥15 000 ms or watchdog) | `f2rel_off_b@s2r` | 5 | 0 | 5 | **fails** | `teardown_ms_r1` 14 274.7–14 339.1 ms; r1rc 3 in 5/5; `ua_r1` 0 in 5/5 |
| RB4a | recovery unchanged with the flag | `f1_b`, `f3_b`, `f1g0_b`, `mt256_f1_b`, `bidirf_f1both_b` (`@s2r`) | 5 each | 5 each | 5 each | holds | |
| RB4b | killed peer declined, survivor abort returns | `f4_b@s2r` | 5 | 5 | 5 | holds | FIN/RST decline 5/5; `teardown_ms_r0` 537.8–810.5 ms; kill record 5/5 |
| RB5 | recovery off: classifier only, no flag | `off_f1_b@s2r` | 5 | 5 | 5 | holds | r0rc 4, user-abort lines 0/0 |
| RB6a | flag costs nothing at 4 KiB (≤0.40) | `lat_s2r_on_4k@s2r` vs `lat_s2on_4k@s2` | 5, 5 | | \|Δ\| ≤ 0.40 | holds | 10.56 vs 10.56, Δ = 0.00 |
| RB6b | flag costs nothing at 256 KiB (≤0.30) | `lat_s2r_on_256k@s2r` vs `lat_s2on_256k@s2` | 5, 5 | | \|Δ\| ≤ 0.30 | holds | 38.91 vs 38.91, Δ = 0.00 |
| RC1a | get round declined with the READ bit | `get_f1_b@s2rget` | 10 | 10 | ≥9 | holds | reason "... cannot count or re-post (mask 0x6)" 10/10; 0x6 = READ 0x4 + DUMP 0x2 `[source]` |
| RC1b | no silent failure, at most one recovered | `get_f1_b@s2rget` | 10 | silent 0, transparent 0 | 0 and ≤1 | holds | gets checked before the fault 32–63 per trial, `get_bad` 0 in 10/10 |
| RC2 | fault-free get mode transparent and exact | `get_none_b@s2rget` | 5 | 5 | 5 | holds | `get_n` 120 = iters, `get_bad` 0 |
| RC3a | rescue off: declined, never silent success | `mt1024_norescue_b@s2r` | 5 | declined 5, silent 0 | 5 and 0 | holds | |
| RC3b | decline names the overwritten WQE | `mt1024_norescue_b@s2r` | 5 | 0 | ≥4 | **fails** | reason "executed count out of range" 5/5; WARN shows in-flight WQEs 648–750 against ring 128, rescue laps 0 |
| RD1a | 8 s mute closes the socket by timeout 2.5–7.0 s after mute start | `mute8_f1_b@s2r` | 10 | 10 | ≥9 | holds | close − mute on (rank 0 clock) 4 574.5–4 599.8 ms; cause ETIMEDOUT on both ranks 10/10 |
| RD1b | socket loss not reported before the next fault | `mute8_f1_b@s2r` | 10 | 0 | 0 | holds | first async error 1.8–3.4 ms after the fault |
| RD1c | later local QP error declined, no helper socket | `mute8_f1_b@s2r` | 10 | 10 | ≥9 | holds | decline 1.6–3.3 ms after the fault, 6.9 s after the close |
| RD1d | receiver gets no async error | `mute8_f1_b@s2r` | 10 | 10 | ≥9 | holds | rank 1 `rx_rc=timeout`, exit 4 in 10/10 |
| RD2 | peer QP error during mute declined as FIN/RST though peer alive | `mute_f3_b@s2r` | 10 | 10 | ≥9 | holds | close − mute on 4 774.0–4 803.0 ms, ETIMEDOUT on both ranks; decline 1.1–2.0 ms after the first RETRY_EXC CQE, 3 562.2–3 773.0 ms after the fault; rank 1 kernel ended 4 526.5–4 737.9 ms after the decline, r1rc 4 |
| RD3 | 1 s mute closes nothing, recovery transparent | `mute1_f1_b@s2r` | 5 | 5 | 5 | holds | mute lasted 999.2–1 000.4 ms; rank 0 close lines 0/5 |

**Verdicts: 25 hold, 3 fail, 0 insufficient data, 0 not measurable.** The verdicts match the experimenter's
(EXPERIMENT.md 12 and 15), and so do the three misses.

## 5. Notes on the focus items

- **4 KiB latency cost (RA4a), measured.** The miss is one GPU timer tick. Δ = 10.560 − 10.272 = 0.288 µs, and p50 values
  move in 32 ns steps.
  - The `lat_s2on_4k@s2` median includes the refill run n6 (10.56). That run was in the fill hold 1.5 h after H1, not
    interleaved with the other latency cells.
  - With the four H1 runs alone the median is 10.575 and Δ = 0.305, which would pass. That set is below plan (n = 4), so
    the frozen rule correctly uses n6. The verdict stands but depends on that one run.
  - RB6a does not change either way: without n6 the medians are 10.575 and 10.56.
- **Flag-off abort (RB3).**
  - `[measured]` Rank 1's abort returned 16 731.8–16 796.5 ms after its kernel launch (abort start 2.457 s after launch,
    plus 14.27–14.34 s).
  - `[source]` The 20 s receive wait is counted in SM cycles from `cudaDevAttrClockRate` (`gin_ts2.cu` 683–685).
  - `[inferred, unverified]` The wait ended early because of the clock. No log line records when the wait ended.
- **Rescue-off reason (RC3b).** `[measured]` The range-check WARN appears 5/5 (in-flight 648–750 > 128). `[source]` In
  the diff, the check `inflight > ringN × (1 + laps)` runs before the overwritten-slot check, so with laps = 0 it declines
  first.
- **Abort release.** `[measured]`
  - Receiver abort (`teardown_ms_r1`): 862–876 ms with the flag (single put cell) and 796–811 ms (ring-burst cell),
    against 14 275–14 339 ms with the flag off.
  - Sender abort: 855–876 ms with the flag off.
  - Every receiver reported `post_abort_state=exited`.
  - Measured from kernel launch, the receiver's abort returned at 3.32–3.34 s with the flag (both cells) and 16.73–16.80 s
    without it.
- **Get cells.** Measured: READ bit set 10/10 (mask 0x6), get data exact in all checked iterations, receiver abort
  returned 10/10 (`teardown_ms_r1` 514.1–1005.6 ms).
- **Socket-mute cells.** `[measured]`
  - In both mute cells the rank 0 socket closed before the fault and the decline: 6.9 s before the decline (8 s mute) and
    4.47–4.69 s before it (peer-error mute).
  - In the 1 s mute cell rank 1 logs one `cause=FIN` close in 5/5. Each comes within 1 ms of rank 0 starting its abort
    and ≈315 ms after rank 1's kernel ended, so it is teardown, not the mute. The acceptance counts rank 0 only.

## 6. Safety per hold `[measured]`

| hold | mlx5 command-error lines rain / sunny (before → after) | rain firmware failed sum | per-command `failed`, `failed_mbox_status` | mlx5 dmesg lines rain / sunny | GPU compute processes | `left` |
|---|---|---|---|---|---|---|
| H1 | 2 → 2 / 0 → 0 | 31 → 31 | unchanged | 66 → 66 / 508 → 508 | none | 0 in 70/70 |
| H2 | 2 → 2 / 0 → 0 | 31 → 31 | unchanged | 66 → 66 / 508 → 508 | none | 0 in 20/20 |
| H3 | 2 → 2 / 0 → 0 | 31 → 31 | unchanged | 66 → 66 / **508 → 509** | none | 0 in 30/30 |
| H4 | 2 → 2 / 0 → 0 | 31 → 31 | unchanged | 66 → 66 / 509 → 509 | none | 0 in 30/30 |
| H5 | 2 → 2 / 0 → 0 | 31 → 31 | unchanged | 66 → 66 / 509 → 509 | none | 0 in 20/20 |
| H6 | 2 → 2 / 0 → 0 | 31 → 31 | unchanged | 66 → 66 / 509 → 509 | none | 0 in 25/25 |
| fill | 2 → 2 / 0 → 0 | 31 → 31 | unchanged | 66 → 66 / 509 → 509 | none | 0 in 3/3 |

- No stop condition was met. No `STOP_mlx5` file exists, every hold exited with rc 0 (`chain.out`), and every hold
  reports `sunny_busy_after=0`. Hold durations were 0.2–8.2 min, under the 880 s bound.
- Sunny gained one mlx5 kernel line during H3. It is not a command-error line, because the command-error count stayed at
  0. The snapshot records only the count for sunny, so the line's content is not in the raw data.

## 7. Discrepancies and unsupported statements

1. **EXPERIMENT.md 12, H3 row, says "mlx5 전후 같음".** The raw snapshots show sunny's mlx5 dmesg count going 508 → 509
   during H3. Section 8 says that when only non-command mlx5 lines grow, their content goes into section 12. That was not
   done, and it cannot be done from the raw data now.
2. **Section 15, flag-off control: "받는 쪽 abort가 5/5 모두 자기 수신 대기가 끝난 뒤에 돌아왔다".** This is written as a
   measurement. The raw data hold only the abort duration and its return 16.73–16.80 s after kernel launch; nothing
   records the receive wait ending. The statement should carry `[추론]`, like the next bullet. That bullet's "약 16 s"
   would be ≈16.6 s from these numbers, if the wait starts ≈0.15 s after launch `[inferred]`.
3. **Section 15, "중간 빌드의 같은 차이는 +0.67 µs ... 최종 빌드의 2단계 켬이 더 빠르다(10.91 → 10.56 µs)".** 10.91
   and +0.67 are not in this study's raw data. The comparison spans days and holds, so it does not separate a build effect
   from run-to-run variation. Not supported by this data; at most `[추론]`.
4. **Section 15, "같은 셀의 최종 빌드(플래그 없음)는 0/10이었다".** That 0/10 is `f2_b` from Release `data-20261006`,
   not this data. `f2_b` is also not the same cell: it has `ABORT_WD_S=5` and no `GIN_TS_RX_WAIT_S=20` or
   `GIN_TS_POST_ABORT_WAIT_S=3`.
5. **Section 15, tie-break off: "투명한 1회는 두 라운드가 겹치지 않은 것으로 본다 [추론]".** The data agree. Trial n1 had
   one round only, with rank 0 as initiator and rank 1 as responder. The data also show more: rank 0's fault fired
   1.3 ms before its kernel launched, and both faulted QPs were at WQE index 0, so no traffic was in flight. Not a
   contradiction.
6. **Build md5 per trial is not recorded** (section 3 above). Section 5's md5 values are deploy-time measurements only.
7. **RA4a depends on the refill run** (section 5 above). This follows the frozen rule, but DEVIATIONS.md does not say
   that the latency refills ran outside the interleaved H1 sequence.

All other numbers in section 15 match this recount. Those are the verdict counts, the 16–20 and 30–49 replayed WQEs, the
latency table and the +4.1% and +1.4% costs, the 862–876, 796–811 and 14 275–14 339 ms aborts, mask 0x6, get 32–63 and
120/120, "executed count out of range" 5/5, 4 575–4 600 ms, 1.6–3.3 ms, 3 562–3 773 ms, and 0/5 closes.
