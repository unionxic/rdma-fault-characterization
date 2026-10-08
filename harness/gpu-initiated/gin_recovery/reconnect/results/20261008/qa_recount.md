# gin-reconnect: independent recount (QA)

Date 2026-10-08. Recount by a separate agent from the raw per-trial files only. Tags: `[measured]` read from raw files,
`[source]` read from code, `[inferred]` interpretation, `[unverified]` not checked.

## 1. Method

- Script: [`../../qa/recount.py`](../../qa/recount.py). Run from the study folder: `python3 qa/recount.py`. It prints
  the pre-registration check, trial set, exclusions, build and configuration checks, the 20 verdicts, the values below
  and the hold safety records. It writes nothing (`--rows <csv>` optionally dumps the per-trial columns).
- Not read or run: `score.py`, the output of `rows_rc.py`, `SCORE.md`, `trials_scored.csv`, the untracked `trials_*.csv`.
  `EXPERIMENT.md` section 15 was read only after the recount was finished.
- Read only for log formats and definitions: `EXPERIMENT.md` 3.1 and `../s2_close/EXPERIMENT.md` 3.1–3.2,
  `../scripts/ts2/rows.py`, `../s2_close/rows_extra.py`, `../scripts/ts2/run_trial.sh`, `cells.sh`, `hold.sh`,
  `deploy_rc.sh`. Nothing is imported from them. Columns whose meaning 3.1 delegates to `rows.py` or `rows_extra.py`
  (`transparent_ok`, `fault_mono_r0`, `async_before_fault`, `r1_alive_at_decline`, `bind_fail`) are re-implemented from
  those definitions, so they are independent in code, not in definition.
- Inputs: `<stem>_meta.txt`, `_r{0,1}.kv`, `_r{0,1}.log`, `_kill.out`, `_lat_raw.csv.gz` in `mute/`, `rep_rc/`, `lat/`,
  plus `chain.out`, `hold_*.out`, `snap_*.txt`, `mlx5_*.txt`, `fwcmd_*.txt`.
- Rules: every acceptance rule is hand-coded with the 3.2 grammar (blank is None, any comparison or arithmetic with None
  is false). As a second check the `acceptance` text of `predictions.csv` is also evaluated verbatim on the same rows. The
  two agree on 20/20. For every new log line, the count of raw substrings equals the count of parsed lines (wait 25,
  reconnected 40, closed 182, declined 40, mute on 100, mute off 80, reconnect mode 200).
- Latency: every run's p50 was also recomputed from its 3000 raw samples. All 20 match the kv `lat_p50_us`.

## 2. Pre-registration integrity `[measured]`

- `sha256(predictions.csv)` = `5f9b8508b814…`, the value in `PREREG.txt`. Tag `prereg/gin-reconnect-v1` resolves to
  commit `ddf9b114`. `predictions.csv` (20 rows) and `PREREG.txt` are byte-identical to the tag.
- `EXPERIMENT.md` sections 2, 3, 7 and 8 are byte-identical to the tag. Changed since the tag: the header table and
  sections 5, 10–15.

## 3. Trial set, exclusions, refills (sections 7 and 8) `[measured]`

- 112 trial meta files: `mute/` 51, `rep_rc/` 41, `lat/` 20. All 18 cell keys of section 7 are present and no other.
- Counted apart: 2 trials, both `bind: Address already in use` in the rank-0 log, `r0rc=1`, `r1rc=7`, wall 0.0 s.
  - `f3_b@rc` n2 (hold H1), refilled by n6 in the fill hold.
  - `rc_mutef3l_b@rc` n10 (hold H4), refilled by n11 in the fill hold.
  - Each refill is the next number, 1 of 5 and 1 of 10 planned (at most 50%). No other exclusion rule fires: every
    local-error cell fired on rank 0, every peer-error cell on rank 1, no trigger miss, both kill cells have a kill record,
    and in the three mute-then-fault cells the first rank-0 socket close precedes the first classifier record in 30/30.
- Judged: 110 = 90 cell trials (new 40, reproduction 40, control 10) + 20 latency runs. Every cell has exactly its
  planned count. Smoke (`results/20261008_smoke/`, 12 + 7 = 19 trials) is not in the folder that was counted.
- Conditions in the meta files match section 7 for the six new and control cells and `f2rel_b` (mute spec, receive wait,
  reconnect switch, fault, hook delay, iterations, bytes). Kill delay 6550 ms in all 10 kill-during-mute trials (hold
  output); the kill came 5968.8–6019.9 ms after rank 1's devComm creation (rank 1 clock, n=10). `ABORT_WD_S` and
  `WATCHDOG_S` are not written to any per-trial file `[unverified]`.

## 4. Build per trial

- No raw file carries an md5. Per-trial library identity is therefore `[unverified]` directly. Evidence instead:
  - Bundle path in every meta: 102 `@rc` trials `$HOME/gi-bundle/gin_ts2/rc`, 10 `@s2r` runs `.../s2r` `[measured]`.
  - Source line numbers in the start WARN lines. Every `@rc` trial that started (100; the two port-collision trials have
    no NCCL line) logs `gin_host_gdaki.cc:3929` (transparent recovery ON) and `:3930` (helper socket reconnect) on both
    ranks. The smoke-1 build (`1193a5f8`) logs `:3924` and `:3925`; smoke 2
    and the main run log `:3929` and `:3930`. Every `@s2r` run logs `:3647` and no reconnect line `[measured]`.
  - The scratch build tree `agent_ts2rc` holds a libnccl with md5 `8354411f198e9d980b8b3459918afbea`, and its
    `gin_host_gdaki.cc` has those two WARN calls ending at lines 3929 and 3930 `[measured]`.
  - [`deploy_check.txt`](../../deploy_check.txt) records `8354411f` on both nodes and `1193a5f8` moved to
    `rc_smoke_1193a5f8/`. Main-run log time stamps run 11:02:20–11:39:31, after the 10:50 redeploy.
  - `rc_layer.diff` md5 `fb72ffd3`, `gin_transparent_rc.diff` md5 `411919a4`, as in section 5.
- Conclusion `[inferred]`: all 100 started `@rc` trials ran the fixed source; none ran the smoke-1 build. That the
  deployed file was still `8354411f` at each trial is inferred from the deploy record and timing, not logged.

## 5. Configuration checks (section 8) `[measured]`

Over the 110 judged trials: transparent recovery ON and the abort-flag line on both ranks in every trial; reconnect
mode 0 on both ranks in `rc_mute8off_b`, 1 in every other `@rc` trial, bound 10000 ms everywhere; a rank-0 mute-on line
in every mute trial; `left=0` in all 112 trials. No violation. The two port-collision trials never reached NCCL init.

## 6. Verdicts `[measured]`

n is judged trials of the cell; every range is over those trials of that cell unless stated. Times are rank 0
`mono_ms` differences.

| Prediction | Cell | n | Hits | Verdict | Values | id |
|---|---|--:|--:|---|---|---|
| After an 8 s mute, a local QP error is recovered transparently (need 9 or more) | `rc_mute8_f1_b@rc` | 10 | 10 | holds | 10/10 transparent, 0 declines | M1a |
| The rank-0 socket closes by timeout, classified unknown (9 or more) | `rc_mute8_f1_b@rc` | 10 | 10 | holds | first close ETIMEDOUT, `liveness=unknown` 10/10; 4573.0–4599.7 ms after mute on | M1b |
| Reconnect within 1.5 s after the mute ends (9 or more) | `rc_mute8_f1_b@rc` | 10 | 10 | holds | 75.9–104.4 ms after the mute-off line (median 90.7); one reconnect line per rank per trial; rank 0 `attempts=8`, rank 1 `attempts=0` | M1c |
| No async error before the fault (0 trials) | `rc_mute8_f1_b@rc` | 10 | 0 | holds | no async error at all on either rank | M1d |
| Peer QP error during a mute that ends inside the bound is recovered (9 or more) | `rc_mutef3s_b@rc` | 10 | 10 | holds | 10/10 transparent | M2a |
| Initiator waited and the wait ended by reconnect, 0–10 s (9 or more) | `rc_mutef3s_b@rc` | 10 | 10 | holds | `ended=reconnected` 10/10, wait 2848.2–3037.4 ms (median 2978.4) | M2b |
| Peer QP error during a mute longer than the bound is declined "peer liveness unknown" (9 or more) | `rc_mutef3l_b@rc` | 10 | 10 | holds | 10/10 "RETRY_EXC and peer liveness unknown (ETIMEDOUT, no reconnect within 10000 ms)" | M3a |
| No decline with a dead-peer cause (0 trials) | `rc_mutef3l_b@rc` | 10 | 0 | holds | | M3b |
| Decline 10.0–11.5 s after the first classifier record (9 or more) | `rc_mutef3l_b@rc` | 10 | 10 | holds | 10001.7–10003.0 ms | M3c |
| Rank 1 alive at the decline (9 or more) | `rc_mutef3l_b@rc` | 10 | 10 | holds | rank 1 kernel ended 10908.4–11379.9 ms after the decline, `r1rc=4` 10/10 | M3d |
| Peer killed during the mute is declined as dead via ECONNREFUSED (9 or more) | `rc_mutekill_b@rc` | 10 | 10 | holds | 10/10 "RETRY_EXC and the peer's socket shows ECONNREFUSED" | M4a |
| None declined as unknown, none recovered (0 and 0) | `rc_mutekill_b@rc` | 10 | 0 and 0 | holds | | M4b |
| Decline within 2 s of the first classifier record (9 or more) | `rc_mutekill_b@rc` | 10 | 10 | holds | 1.13–2.05 ms | M4c |
| Six regression cells stay transparent (5/5 each) | `f1_b`, `f3_b`, `f1g0_b`, `mt256_f1_b`, `bidirf_f1both_b`, `bidirf_sym_b` (`@rc`) | 5 each | 5 each | holds | 30/30, no decline | G1 |
| Kill without mute declined with a dead cause and rank-0 abort returns (5/5) | `f4_b@rc` | 5 | 5 | holds | first close FIN/dead 5/5, "RETRY_EXC and the peer's socket shows FIN" 5/5, decline 1.19–2.05 ms after the classifier record, rank-0 abort `no error` in 682.3–1001.8 ms | G2 |
| Receiver abort still released after a declined remote access error (5/5) | `f2rel_b@rc` | 5 | 5 | holds | rank-1 abort `no error` in 854.7–876.4 ms, `r1rc=3`, `async_error_kernel_stuck` 5/5 | G3 |
| 1 s mute: no close, no reconnect, transparent (5/5) | `rc_mute1_f1_b@rc` | 5 | 5 | holds | mute on 1 line, close 0, reconnect 0, 5/5 transparent | C1 |
| Reconnect off: "no helper socket" decline after an 8 s mute (5/5) | `rc_mute8off_b@rc` | 5 | 5 | holds | 5/5 "no helper socket to the peer: peer liveness unknown (ETIMEDOUT, reconnect off)", `ended=off wait_ms=0.0`, no reconnect line on either rank | C2 |
| 4 KiB latency difference 0.40 µs or less | `lat_rc_on_4k@rc` vs `lat_s2r_on_4k@s2r` | 5 + 5 runs | | holds | run-median p50 10.59 vs 10.59 µs, difference 0.00 | L1 |
| 256 KiB latency difference 0.30 µs or less | `lat_rc_on_256k@rc` vs `lat_s2r_on_256k@s2r` | 5 + 5 runs | | holds | run-median p50 38.91 vs 38.88 µs, difference +0.03 | L2 |

20 hold, 0 fail, 0 insufficient data. Per-run p50 (each over its 5 runs of hold H1): 4 KiB `rc` 10.56–10.59, `s2r`
10.56–10.59 µs; 256 KiB `rc` 38.88–38.91, `s2r` 38.88–38.91 µs. All samples are multiples of 32 ns, so both differences
are within one timer step.

## 7. Mechanism details `[measured]`

- **Socket close cause and class.** First rank-0 close ETIMEDOUT/unknown in all 45 judged trials of the five 8–30 s mute
  cells. Close after mute on: 8 s mute 4573.0–4599.7 ms, reconnect-off 4586.4–4597.7 ms, short-mute peer error
  4772.1–4801.1 ms, long-mute peer error 4768.1–4801.5 ms, kill during mute 4772.7–4801.3 ms. Kill without mute: FIN/dead
  5/5. 1 s mute: no close.
- **Reconnect after the mute ends.** Idle reconnect (8 s mute) 75.9–104.4 ms; reconnect inside the wait (short-mute peer
  error) 276.9–305.3 ms. Both sit at a multiple of 500 ms after the close: 3503.4–3504.5 ms (8 s mute, `attempts=8`) and
  7504.8–7507.4 ms (short mute, `attempts=16`).
- **Reconnect wait.**
  - Short-mute peer error: starts 0.1–1.0 ms after the first classifier record (wait line minus `wait_ms`), ends
    `reconnected` 276.9–305.3 ms after the mute-off line and 0.03–0.04 ms after the rank-0 reconnected line. Rank 1
    answered as responder 10/10.
  - Long-mute peer error: starts 0.06–0.80 ms after the classifier record, ends `bound` after 10000.0–10001.0 ms. No
    rank-0 mute-off line before exit, no reconnect line.
  - Reconnect off: `ended=off`, `wait_ms=0.0`, decline 0.25–1.03 ms after the classifier record.
  - Kill during mute and the 8 s local-error cell: no wait line.
- **Peer alive at the decline.** Long-mute cell 10/10 (above). Reconnect-off cell 5/5, rank 1 kernel ended
  8276.7–8281.1 ms after the decline. Kill-during-mute cell 0/10 (`r1rc=255`, killed 3595.2–3821.5 ms before the decline).
- **Kill during the mute (no trial took the "wait ended by death" path).** In all 10 trials the order is: ETIMEDOUT
  close (unknown) at +4772.7–4801.3 ms after mute on; kill 869.3–948.8 ms later; mute off at +8000; refused re-dial
  ECONNREFUSED (dead) 276.0–305.5 ms after mute off, which is 3503.7–3505.0 ms after the first close; first classifier
  record 1000.2–1221.8 ms after the refused re-dial; decline 1.13–2.05 ms after that. The socket was already dead when the
  error arrived, so rank 0 declined at once. `ended=dead` occurs 0/10; no wait line at all. The death evidence came from
  the re-dial after the mute, not from the kill while a socket was open.
- **Latency.** See section 6.

## 8. Safety per hold `[measured]`

| Hold | Trials | mlx5 lines rain, sunny (before, after) | New mlx5 lines | Command-error lines rain, sunny | rain fw failed sum | Max `left` | Hold rc |
|---|--:|---|--:|---|---|--:|--:|
| H1 | 60 | 66, 509 (same after) | 0 | 2→2, 0→0 | 31→31 | 0 | 0 |
| H2 | 20 | 66, 509 (same after) | 0 | 2→2, 0→0 | 31→31 | 0 | 0 |
| H3 | 20 | 66, 509 (same after) | 0 | 2→2, 0→0 | 31→31 | 0 | 0 |
| H4 | 10 | 66, 509 (same after) | 0 | 2→2, 0→0 | 31→31 | 0 | 0 |
| fill | 2 | 66, 509 (same after) | 0 | 2→2, 0→0 | 31→31 | 0 | 0 |

Recomputed from `mlx5_before/after-*` (set difference, and the section 8 command-error rule) and `fwcmd_*` (sum of
`failed` and `failed_mbox_status`); `mlx5_new_*.txt` are empty and `STOP_mlx5` is absent. Every hold ends with
`sunny_busy_after=0`. The snapshots list no GPU compute process before or after any hold; the snapshot drops
`nvidia-smi` errors, so "none" cannot be told apart from a failed query `[unverified]`.

## 9. EXPERIMENT.md section 15 against the raw data

Every verdict, n, exclusion, and every range and median in the section 15 table agrees with this recount. Statements
the raw data do not support:

1. 8 s mute cell: "장애는 끊김이 끝난 뒤 3 501.3–3 504.9 ms에 났고". Those numbers are the first rank-0 classifier record
   after the mute-off line. The fault itself (hook fire, `fault_mono_r0`) came 3499.1–3499.9 ms after the mute-off line.
2. 1 s mute control: "장애는 끊김이 끝난 뒤 1 513.1–1 514.1 ms에 났고". Same mix-up: 1513.1–1514.1 ms is the classifier
   record; the fault fired 1499.2–1499.9 ms after the mute-off line.
3. Long-mute cell: "예측 범위의 아래 끝(10 000 ms)과 2–3 ms 차이다". The gap is 1.7–3.0 ms (10001.7–10003.0 ms, as the
   same paragraph says).

The `[inferred]` paragraph on why reconnect times cluster is consistent with the raw data (reconnect or refused re-dial
at 3503.4–3505.0 ms or 7504.8–7507.4 ms after the close, so on the 500 ms cadence).

## 10. Notes for the conclusion (not discrepancies)

- The kill-during-mute cell supports "a dead peer is still declined as dead and the bound is not waited out" only through
  the path where the socket is already dead before the error. The branch where death evidence ends a running wait
  (`ended=dead`, section 9 item 6) was not exercised in any trial.
- The lower edge of the long-mute rule (10000 ms) is met by 1.7 ms; the margin is structural, since the wait starts after
  the classifier record and lasts the full bound `[inferred]`.
- The latency differences are at the 32 ns timer resolution; the cells cannot resolve a change smaller than that.
