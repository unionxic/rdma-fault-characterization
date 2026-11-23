# gpu-detect 채점 결과

`score.py`가 원자료(`results/20261009/`의 시행 파일)에서 만들었다. 손으로 고친 값은 없다.

- 예측 파일 sha256: `c62592393a8798f7c9e914c5f2d9031f8501a5a2052d73be0e8645371a564f66`. `PREREG.txt`의 값과 같다.
- 시행 수(모든 hold): 248. 판정한 시행: 248.
- 판정식 원문은 `predictions.csv`, 열과 문법은 `EXPERIMENT.md` 3절.

## 판정 요약

| 예측 | 셀 | n | 판정 |
|---|---|--:|---|
| GIN example, QP error at a random time (watch 10 ms): transparent with a recovery line, all but at most one trial (GD1) | `gin_qperr@hk` | 16 | 맞음 |
| the fault is detected on the target within 100 ms of the hook (by the watch or by a device thread) (GD2) | `gin_qperr@hk` | 16 | 맞음 |
| the target's round has resumed traffic within 1000 ms of the hook (GD3) | `gin_qperr@hk` | 16 | 맞음 |
| the watch period does not change the outcome: 1 ms and 100 ms periods are transparent too, with detection within 70 ms (1 ms) and 200 ms (100 ms) (GD4) | `gin_qperr_w1@hk`, `gin_qperr_w100@hk` | 8 / 8 | 맞음 |
| the median detection delay of the watch grows with the period, over the trials the watch detected with its class from a root CQE (without the fixed 50 ms wait of a window with no root CQE) (GD5) | `gin_qperr_w1@hk`, `gin_qperr@hk`, `gin_qperr_w100@hk` | 8 / 16 / 8 | 맞음 |
| control (gin-remaining's and gin-peer's libraries, no watch): the same faults are not detected fast: no detection on either rank within 100 ms and no recovery within 1000 ms of the hook (they hang, or recover late through a RETRY_EXC read in a CQ-reading call) (GC1) | `gin_qperr@hr`, `gin_qperr@hq` | 6 / 6 | 맞음 |
| control inside the hk build: with the watch off nothing detects the fault fast: no watch detection, no detection on either rank within 100 ms and no recovery within 1000 ms of the hook (the GD2 and GD3 bounds); the trial hangs, or a CQ-reading call reads the peer's RETRY_EXC late (about 3.6 s) and the round recovers then (GC2) | `gin_qperr_w0@hk` | 4 | 맞음 |
| GIN example, kill of one rank: no transparent or silent result, the survivor's first error line within 5 s; the watch adds no detection (GR1) | `gin_kill@hk` | 6 | 맞음 |
| GIN example, one rank stopped 1-8 s: transparent, no death verdict, no decline, no watch detection (GF1) | `gin_stop@hk` | 8 | 맞음 |
| GIN example without a fault: transparent with no watch detection and no decline (GF2) | `gin_none@hk` | 6 | 맞음 |
| NVSHMEM example, kill of one PE: the survivor declines on the FIN without a goodbye within 0.1 s and ends itself with code 70 within 1 s (ND1) | `nvs_kill@t1w` | 8 | 맞음 |
| NVSHMEM example, remote access revoked: both PEs decline and end themselves with code 70 within 2 s of the hook (ND2) | `nvs_remacc@t1w` | 8 | 맞음 |
| control (t1_380): the survivor hangs until the harness ends it, with no error line (NC1) | `nvs_kill@t1_380` | 4 | 맞음 |
| control (t1_380): both PEs decline and still hang until the wall cap (NC2) | `nvs_remacc@t1_380` | 4 | 맞음 |
| release policy (NVSHMEM_IBGDA_FT_T1_FAILSTOP_MS=-1): the decline releases the device waits and every surviving process ends by itself (not by the harness), with a released-waits line (NR1) | `nvs_kill_rel@t1w`, `nvs_remacc_rel@t1w` | 5 / 5 | 맞음 |
| NVSHMEM example, PE 0 stopped 1-8 s: transparent, no death verdict, no decline (NF1) | `nvs_stop@t1w` | 8 | 맞음 |
| NVSHMEM example without a fault: transparent, no decline, no FIN verdict, and at least one PE sends its goodbye at teardown (the normal FIN is not death) (NF2) | `nvs_none@t1w` | 8 | 맞음 |
| the wait-word check costs at most 10% of the 64 MiB per-iteration time (NO1) | `nvs_none@t1w`, `nvs_none@t1_380` | 8 / 6 | 맞음 |
| NVSHMEM example QP error: transparent with a recovery line (t1w changes no recovery path) (NQ1) | `nvs_qperr@t1w` | 6 | 맞음 |
| the two-rank recovery cells stay transparent (RG1) | `f1_b@hk`, `f3_b@hk`, `bidirf_sym_b@hk` | 5 / 5 / 5 | 맞음 |
| two ranks, peer killed: declined within 2 s with cause peer-dead (RG3) | `f4_b@hk` | 5 | 맞음 |
| two ranks, a receive-only rank's waitSignal is released with an error within 2 s of the sender's kill (RG4) | `hd_rxdeath_b@hk` | 5 | 맞음 |
| remote access error: rank 0 declines, rank 1's wait is released with an error, its abort returns within 5 s (RG5) | `f2rel_b@hk` | 5 | 맞음 |
| the stats API counts one round, one recovery, no decline on both ranks (the watch adds no second round) (RG7) | `f1_b@hk` | 5 | 맞음 |
| four ranks, no fault and one pair's local QP error: transparent (RG8) | `mr4_none@hk`, `mr4_f1_01@hk` | 5 / 5 | 맞음 |
| four ranks, rank 3 killed, untimed receives: each survivor's receive from rank 3 is released 2000-3000 ms after its judgment and the survivor sends all complete (RG9) | `rm4_kill3_untimed@hk` | 5 | 맞음 |
| the cycle of three initiators recovers without a handshake timeout or a decline (RG10) | `mr4_cyc_stall@hk` | 5 | 맞음 |
| review M-A: rank 3 answers both lower REQs (ranks 0 and 1) inside its ACK wait, one nested round per pass; no handshake timeout, no decline, transparent (MA1) | `mr4_twolow_stall@hk` | 5 | 맞음 |
| review M-C default rule: a fault on the healthy pair 0-1 after the degraded raise declines that pair at its publish check; it is not recovered (MC1) | `rm4_late01@hk` | 3 | 맞음 |
| control: with NCCL_GIN_TS_DEGRADED_ROUNDS=1 (gin-remaining's rule) the same fault recovers (MC2) | `rm4_late01_rounds@hk` | 3 | 맞음 |
| responder-side gap fixed: rank 3 dies after rank 0 (its responder) committed and before DONE; rank 0 judges it dead from the FIN and declines it with cause peer-dead, and every survivor's untimed receive from rank 3 is released 2000-3000 ms after that survivor's judgment; no kernel stays stuck (GP1) | `rm4_gap@hk` | 5 | 맞음 |
| control (hw, the same condition): rank 0 declines rank 3 with cause unknown and no judgment; its untimed receive from rank 3 is not released and its kernel still runs when the application's 15 s grace ends; ranks 1 and 2 are released 2000-3000 ms after their judgment (GP2) | `rm4_gap@hw` | 3 | 맞음 |
| the test switch hits the same window deterministically: rank 3 ends with code 73 right after the ACK, rank 0 declines it with cause peer-dead, every survivor is released 2000-3000 ms after its judgment, no kernel stuck (GP3) | `rm4_gapx@hk` | 3 | 맞음 |
| NCCL_GIN_FAULT_POLICY=hold on every rank of this build: one WARN per rank, every rank effective fail-fast, and the kill of rank 3 behaves as RG9 (PH1) | `rm4_kill3_hold@hk` | 3 | 맞음 |
| policies differ across ranks (rank 0 hold, rank 1 fail-fast): both ranks WARN once and run fail-fast; the kill of rank 1 is declined within 2 s with cause peer-dead, as RG3 (PH2) | `f4_mix_b@hk` | 3 | 맞음 |
| review L-C: the NIC copy path is on with its NIC-only self-test on every rank (at least one device QP struct equal to the host shadow) (LC1) | `gin_none@hk`, `f1_b@hk` | 6 / 5 | 맞음 |
| pilot 1's logging gap fixed: the GIN example (it destroys its devComm before the communicator) writes the watch's teardown line on both ranks (WT1) | `gin_none@hk` | 6 | 맞음 |
| 4 KiB latency with the default watch (10 ms) within 0.40 us of the watch off (LT1) | `lat_4k_w10@hk`, `lat_4k_w0@hk` | 5 / 5 | 맞음 |
| 256 KiB latency with the default watch within 0.30 us of the watch off (LT2) | `lat_256k_w10@hk`, `lat_256k_w0@hk` | 5 / 5 | 맞음 |
| 4 KiB latency with a 1 ms watch within 1.0 us of the watch off (4000 firmware commands per second, not measured before) (LT3) | `lat_4k_w1@hk`, `lat_4k_w0@hk` | 5 / 5 | 맞음 |
| 256 KiB latency with a 1 ms watch within 1.0 us of the watch off (LT4) | `lat_256k_w1@hk`, `lat_256k_w0@hk` | 5 / 5 | 맞음 |

## 예측별 세부

### GD1: 맞음

- 판정식: `count(outcome == "TRANSPARENT" and n_rec >= 1 and result == "correct") >= N_SCORED - 1`
- 셀 `gin_qperr@hk`: 판정한 시행 16회, 대입한 식 `16 >= 16 - 1` → 참
  - `count(outcome == "TRANSPARENT" and n_rec >= 1 and result == "correct")` = 16/16. 조건을 만족하지 않은 시행: 없음

### GD2: 맞음

- 판정식: `count((det_by == "watch" or det_by == "device") and 0 <= det_ms <= 100) >= N_SCORED - 1`
- 셀 `gin_qperr@hk`: 판정한 시행 16회, 대입한 식 `16 >= 16 - 1` → 참
  - `count((det_by == "watch" or det_by == "device") and 0 <= det_ms <= 100)` = 16/16. 조건을 만족하지 않은 시행: 없음

### GD3: 맞음

- 판정식: `count(nonempty(rec_ms) and rec_ms <= 1000) >= N_SCORED - 1`
- 셀 `gin_qperr@hk`: 판정한 시행 16회, 대입한 식 `16 >= 16 - 1` → 참
  - `count(nonempty(rec_ms) and rec_ms <= 1000)` = 16/16. 조건을 만족하지 않은 시행: 없음

### GD4: 맞음

- 판정식: `per cell: count(outcome == "TRANSPARENT" and nonempty(det_ms) and det_ms <= (70 if cell == "gin_qperr_w1" else 200)) >= N_SCORED - 1`
- 셀 `gin_qperr_w1@hk`: 판정한 시행 8회, 대입한 식 `8 >= 8 - 1` → 참
  - `count(outcome == "TRANSPARENT" and nonempty(det_ms) and det_ms <= (70 if cell == "gin_qperr_w1" else 200))` = 8/8. 조건을 만족하지 않은 시행: 없음
- 셀 `gin_qperr_w100@hk`: 판정한 시행 8회, 대입한 식 `8 >= 8 - 1` → 참
  - `count(outcome == "TRANSPARENT" and nonempty(det_ms) and det_ms <= (70 if cell == "gin_qperr_w1" else 200))` = 8/8. 조건을 만족하지 않은 시행: 없음

### GD5: 맞음

- 판정식: `median(det_wcq_ms, "gin_qperr_w1@hk") < median(det_wcq_ms, "gin_qperr@hk") < median(det_wcq_ms, "gin_qperr_w100@hk")`
- 셀 `gin_qperr_w1@hk`: 판정한 시행 8회, 대입한 식 `6.202 < 18.549 < 91.749` → 참

### GC1: 맞음

- 판정식: `per cell: count(n_watch == 0 and not (nonempty(det1_s) and det1_s <= 0.1) and not (nonempty(rec_rx_s) and rec_rx_s <= 1.0)) >= N_SCORED - 1`
- 셀 `gin_qperr@hr`: 판정한 시행 6회, 대입한 식 `6 >= 6 - 1` → 참
  - `count(n_watch == 0 and not (nonempty(det1_s) and det1_s <= 0.1) and not (nonempty(rec_rx_s) and rec_rx_s <= 1.0))` = 6/6. 조건을 만족하지 않은 시행: 없음
- 셀 `gin_qperr@hq`: 판정한 시행 6회, 대입한 식 `6 >= 6 - 1` → 참
  - `count(n_watch == 0 and not (nonempty(det1_s) and det1_s <= 0.1) and not (nonempty(rec_rx_s) and rec_rx_s <= 1.0))` = 6/6. 조건을 만족하지 않은 시행: 없음

### GC2: 맞음

- 판정식: `count(n_watch == 0 and not (nonempty(det1_s) and det1_s <= 0.1) and not (nonempty(rec_rx_s) and rec_rx_s <= 1.0)) >= N_SCORED - 1`
- 셀 `gin_qperr_w0@hk`: 판정한 시행 4회, 대입한 식 `3 >= 4 - 1` → 참
  - `count(n_watch == 0 and not (nonempty(det1_s) and det1_s <= 0.1) and not (nonempty(rec_rx_s) and rec_rx_s <= 1.0))` = 3/4. 조건을 만족하지 않은 시행: gin_qperr_w0.hk.n3

### GR1: 맞음

- 판정식: `count((outcome == "DECLINED" or outcome == "HUNG") and nonempty(dt_err) and dt_err <= 5 and n_watch == 0) >= N_SCORED - 1`
- 셀 `gin_kill@hk`: 판정한 시행 6회, 대입한 식 `6 >= 6 - 1` → 참
  - `count((outcome == "DECLINED" or outcome == "HUNG") and nonempty(dt_err) and dt_err <= 5 and n_watch == 0)` = 6/6. 조건을 만족하지 않은 시행: 없음

### GF1: 맞음

- 판정식: `count(outcome == "TRANSPARENT" and n_death == 0 and n_decl == 0 and n_watch == 0) >= N_SCORED - 1`
- 셀 `gin_stop@hk`: 판정한 시행 8회, 대입한 식 `8 >= 8 - 1` → 참
  - `count(outcome == "TRANSPARENT" and n_death == 0 and n_decl == 0 and n_watch == 0)` = 8/8. 조건을 만족하지 않은 시행: 없음

### GF2: 맞음

- 판정식: `count(outcome == "TRANSPARENT" and n_watch == 0 and n_decl == 0) == N_SCORED`
- 셀 `gin_none@hk`: 판정한 시행 6회, 대입한 식 `6 == 6` → 참
  - `count(outcome == "TRANSPARENT" and n_watch == 0 and n_decl == 0)` = 6/6. 조건을 만족하지 않은 시행: 없음

### ND1: 맞음

- 판정식: `count(outcome == "DECLINED" and n_fin_verdict >= 1 and surv_rc == 70 and n_harness_end == 0 and nonempty(verdict_s) and verdict_s <= 0.1 and dt_end <= 1.0) >= N_SCORED - 1`
- 셀 `nvs_kill@t1w`: 판정한 시행 8회, 대입한 식 `8 >= 8 - 1` → 참
  - `count(outcome == "DECLINED" and n_fin_verdict >= 1 and surv_rc == 70 and n_harness_end == 0 and nonempty(verdict_s) and verdict_s <= 0.1 and dt_end <= 1.0)` = 8/8. 조건을 만족하지 않은 시행: 없음

### ND2: 맞음

- 판정식: `count(outcome == "DECLINED" and rc0 == 70 and rc1 == 70 and n_harness_end == 0 and nonempty(dt_end) and dt_end <= 2.0) >= N_SCORED - 1`
- 셀 `nvs_remacc@t1w`: 판정한 시행 8회, 대입한 식 `8 >= 8 - 1` → 참
  - `count(outcome == "DECLINED" and rc0 == 70 and rc1 == 70 and n_harness_end == 0 and nonempty(dt_end) and dt_end <= 2.0)` = 8/8. 조건을 만족하지 않은 시행: 없음

### NC1: 맞음

- 판정식: `count(outcome == "HUNG" and n_death == 0) >= N_SCORED - 1`
- 셀 `nvs_kill@t1_380`: 판정한 시행 4회, 대입한 식 `4 >= 4 - 1` → 참
  - `count(outcome == "HUNG" and n_death == 0)` = 4/4. 조건을 만족하지 않은 시행: 없음

### NC2: 맞음

- 판정식: `count(outcome == "HUNG" and n_declines >= 1) >= N_SCORED - 1`
- 셀 `nvs_remacc@t1_380`: 판정한 시행 4회, 대입한 식 `4 >= 4 - 1` → 참
  - `count(outcome == "HUNG" and n_declines >= 1)` = 4/4. 조건을 만족하지 않은 시행: 없음

### NR1: 맞음

- 판정식: `per cell: count(n_released >= 1 and n_harness_end == 0) >= N_SCORED - 1`
- 셀 `nvs_kill_rel@t1w`: 판정한 시행 5회, 대입한 식 `5 >= 5 - 1` → 참
  - `count(n_released >= 1 and n_harness_end == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `nvs_remacc_rel@t1w`: 판정한 시행 5회, 대입한 식 `5 >= 5 - 1` → 참
  - `count(n_released >= 1 and n_harness_end == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### NF1: 맞음

- 판정식: `count(outcome == "TRANSPARENT" and n_death == 0 and n_declines == 0) >= N_SCORED - 1`
- 셀 `nvs_stop@t1w`: 판정한 시행 8회, 대입한 식 `8 >= 8 - 1` → 참
  - `count(outcome == "TRANSPARENT" and n_death == 0 and n_declines == 0)` = 8/8. 조건을 만족하지 않은 시행: 없음

### NF2: 맞음

- 판정식: `count(outcome == "TRANSPARENT" and n_declines == 0 and n_fin_verdict == 0 and n_bye_sent >= 1) >= N_SCORED - 1`
- 셀 `nvs_none@t1w`: 판정한 시행 8회, 대입한 식 `8 >= 8 - 1` → 참
  - `count(outcome == "TRANSPARENT" and n_declines == 0 and n_fin_verdict == 0 and n_bye_sent >= 1)` = 8/8. 조건을 만족하지 않은 시행: 없음

### NO1: 맞음

- 판정식: `median(ms_64m, "nvs_none@t1w") <= 1.10 * median(ms_64m, "nvs_none@t1_380")`
- 셀 `nvs_none@t1w`: 판정한 시행 8회, 대입한 식 `18.960 <= 1.10 * 18.970` → 참

### NQ1: 맞음

- 판정식: `count(outcome == "TRANSPARENT" and n_rec >= 1) >= N_SCORED - 1`
- 셀 `nvs_qperr@t1w`: 판정한 시행 6회, 대입한 식 `6 >= 6 - 1` → 참
  - `count(outcome == "TRANSPARENT" and n_rec >= 1)` = 6/6. 조건을 만족하지 않은 시행: 없음

### RG1: 맞음

- 판정식: `per cell: count(transparent_ok == 1) == N_SCORED`
- 셀 `f1_b@hk`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `f3_b@hk`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `bidirf_sym_b@hk`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### RG3: 맞음

- 판정식: `count(has(declwhy_r0, "the peer's socket shows") and cause_r0 == "peer-dead" and 0 <= decl_after_kill_ms_r0 <= 2000 and teardown_r0 == "no error" and uaerr_why_r0 == "peer-dead") == N_SCORED`
- 셀 `f4_b@hk`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(has(declwhy_r0, "the peer's socket shows") and cause_r0 == "peer-dead" and 0 <= decl_after_kill_ms_r0 <= 2000 and teardown_r0 == "no error" and uaerr_why_r0 == "peer-dead")` = 5/5. 조건을 만족하지 않은 시행: 없음

### RG4: 맞음

- 판정식: `count(n_judged_r1 >= 1 and rx_rc == "remote process exited or there was a network error" and 0 <= release_after_kill_ms_r1 <= 2000 and 0 <= async_after_kill_ms_r1 <= 2000 and teardown_r1 == "no error") == N_SCORED`
- 셀 `hd_rxdeath_b@hk`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(n_judged_r1 >= 1 and rx_rc == "remote process exited or there was a network error" and 0 <= release_after_kill_ms_r1 <= 2000 and 0 <= async_after_kill_ms_r1 <= 2000 and teardown_r1 == "no error")` = 5/5. 조건을 만족하지 않은 시행: 없음

### RG5: 맞음

- 판정식: `count(has(decl_r0, "REM_ACCESS is not recoverable") and r1_outcome == "device_error" and rx_rc == "remote process exited or there was a network error" and rx_phantom_r1 == 0 and teardown_r1 == "no error" and teardown_ms_r1 <= 5000) == N_SCORED`
- 셀 `f2rel_b@hk`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(has(decl_r0, "REM_ACCESS is not recoverable") and r1_outcome == "device_error" and rx_rc == "remote process exited or there was a network error" and rx_phantom_r1 == 0 and teardown_r1 == "no error" and teardown_ms_r1 <= 5000)` = 5/5. 조건을 만족하지 않은 시행: 없음

### RG7: 맞음

- 판정식: `count(rs_api_r0 == 1 and rs_rounds_r0 == 1 and rs_recovered_r0 == 1 and rs_declined_r0 == 0 and rs_rounds_r1 == 1 and rs_recovered_r1 == 1) == N_SCORED`
- 셀 `f1_b@hk`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(rs_api_r0 == 1 and rs_rounds_r0 == 1 and rs_recovered_r0 == 1 and rs_declined_r0 == 0 and rs_rounds_r1 == 1 and rs_recovered_r1 == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### RG8: 맞음

- 판정식: `per cell: count(transparent_ok == 1) == N_SCORED`
- 셀 `mr4_none@hk`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `mr4_f1_01@hk`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### RG9: 맞음

- 판정식: `count(n_rel_dead == 3 and 2000 <= rel_after_dead_ms_r0 <= 3000 and 2000 <= rel_after_dead_ms_r1 <= 3000 and 2000 <= rel_after_dead_ms_r2 <= 3000 and n_surv_edges == 6 and surv_tx_ok == 6 and n_kdone_surv == 3 and n_stuck_surv == 0) == N_SCORED`
- 셀 `rm4_kill3_untimed@hk`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(n_rel_dead == 3 and 2000 <= rel_after_dead_ms_r0 <= 3000 and 2000 <= rel_after_dead_ms_r1 <= 3000 and 2000 <= rel_after_dead_ms_r2 <= 3000 and n_surv_edges == 6 and surv_tx_ok == 6 and n_kdone_surv == 3 and n_stuck_surv == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### RG10: 맞음

- 판정식: `count(n_hs == 0 and transparent_ok == 1 and n_decl == 0 and has(rec_i, "0-1") and has(rec_i, "1-2") and has(rec_i, "2-0")) >= N_SCORED - 1`
- 셀 `mr4_cyc_stall@hk`: 판정한 시행 5회, 대입한 식 `5 >= 5 - 1` → 참
  - `count(n_hs == 0 and transparent_ok == 1 and n_decl == 0 and has(rec_i, "0-1") and has(rec_i, "1-2") and has(rec_i, "2-0"))` = 5/5. 조건을 만족하지 않은 시행: 없음

### MA1: 맞음

- 판정식: `count(transparent_ok == 1 and n_decl == 0 and n_hs == 0 and has(served3, "3-0") and has(served3, "3-1")) >= N_SCORED - 1`
- 셀 `mr4_twolow_stall@hk`: 판정한 시행 5회, 대입한 식 `5 >= 5 - 1` → 참
  - `count(transparent_ok == 1 and n_decl == 0 and n_hs == 0 and has(served3, "3-0") and has(served3, "3-1"))` = 5/5. 조건을 만족하지 않은 시행: 없음

### MC1: 맞음

- 판정식: `count(decl01 >= 1 and rec01 == 0) == N_SCORED`
- 셀 `rm4_late01@hk`: 판정한 시행 3회, 대입한 식 `3 == 3` → 참
  - `count(decl01 >= 1 and rec01 == 0)` = 3/3. 조건을 만족하지 않은 시행: 없음

### MC2: 맞음

- 판정식: `count(rec01 >= 1 and decl01 == 0) == N_SCORED`
- 셀 `rm4_late01_rounds@hk`: 판정한 시행 3회, 대입한 식 `3 == 3` → 참
  - `count(rec01 >= 1 and decl01 == 0)` = 3/3. 조건을 만족하지 않은 시행: 없음

### GP1: 맞음

- 판정식: `count(gap_hit == 1 and gap_cause == "peer-dead" and gap_lac == 1 and gap_judged_r == 1 and gap_n_rel == 3 and gap_n_rel23 == 3 and gap_kdone == 3 and gap_stuck == 0) >= N_SCORED - 1`
- 셀 `rm4_gap@hk`: 판정한 시행 5회, 대입한 식 `5 >= 5 - 1` → 참
  - `count(gap_hit == 1 and gap_cause == "peer-dead" and gap_lac == 1 and gap_judged_r == 1 and gap_n_rel == 3 and gap_n_rel23 == 3 and gap_kdone == 3 and gap_stuck == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### GP2: 맞음

- 판정식: `count(gap_hit == 1 and gap_cause == "unknown" and gap_judged_r == 0 and gap_resp_rel == 0 and gap_resp_stuck == 1 and gap_others_rel23 == 2) >= N_SCORED - 1`
- 셀 `rm4_gap@hw`: 판정한 시행 3회, 대입한 식 `3 >= 3 - 1` → 참
  - `count(gap_hit == 1 and gap_cause == "unknown" and gap_judged_r == 0 and gap_resp_rel == 0 and gap_resp_stuck == 1 and gap_others_rel23 == 2)` = 3/3. 조건을 만족하지 않은 시행: 없음

### GP3: 맞음

- 판정식: `count(gap_exit_line == 1 and gap_rc_x == 73 and gap_hit == 1 and gap_cause == "peer-dead" and gap_n_rel23 == 3 and gap_kdone == 3 and gap_stuck == 0) >= N_SCORED - 1`
- 셀 `rm4_gapx@hk`: 판정한 시행 3회, 대입한 식 `3 >= 3 - 1` → 참
  - `count(gap_exit_line == 1 and gap_rc_x == 73 and gap_hit == 1 and gap_cause == "peer-dead" and gap_n_rel23 == 3 and gap_kdone == 3 and gap_stuck == 0)` = 3/3. 조건을 만족하지 않은 시행: 없음

### PH1: 맞음

- 판정식: `count(pol_n == 4 and pol_eff_ff == 1 and hold_warn_ranks == 4 and n_hold_warn == 4 and n_rel_dead == 3 and 2000 <= rel_after_dead_ms_r0 <= 3000 and 2000 <= rel_after_dead_ms_r1 <= 3000 and 2000 <= rel_after_dead_ms_r2 <= 3000 and n_surv_edges == 6 and surv_tx_ok == 6 and n_kdone_surv == 3 and n_stuck_surv == 0) == N_SCORED`
- 셀 `rm4_kill3_hold@hk`: 판정한 시행 3회, 대입한 식 `3 == 3` → 참
  - `count(pol_n == 4 and pol_eff_ff == 1 and hold_warn_ranks == 4 and n_hold_warn == 4 and n_rel_dead == 3 and 2000 <= rel_after_dead_ms_r0 <= 3000 and 2000 <= rel_after_dead_ms_r1 <= 3000 and 2000 <= rel_after_dead_ms_r2 <= 3000 and n_surv_edges == 6 and surv_tx_ok == 6 and n_kdone_surv == 3 and n_stuck_surv == 0)` = 3/3. 조건을 만족하지 않은 시행: 없음

### PH2: 맞음

- 판정식: `count(pol_agreed_min == 0 and mix_warn_ranks == 2 and n_hold_warn == 0 and pol_eff_ff == 1 and has(declwhy_r0, "the peer's socket shows") and cause_r0 == "peer-dead" and 0 <= decl_after_kill_ms_r0 <= 2000 and teardown_r0 == "no error" and uaerr_why_r0 == "peer-dead") == N_SCORED`
- 셀 `f4_mix_b@hk`: 판정한 시행 3회, 대입한 식 `3 == 3` → 참
  - `count(pol_agreed_min == 0 and mix_warn_ranks == 2 and n_hold_warn == 0 and pol_eff_ff == 1 and has(declwhy_r0, "the peer's socket shows") and cause_r0 == "peer-dead" and 0 <= decl_after_kill_ms_r0 <= 2000 and teardown_r0 == "no error" and uaerr_why_r0 == "peer-dead")` = 3/3. 조건을 만족하지 않은 시행: 없음

### LC1: 맞음

- 판정식: `per cell: count((nonempty(lb_shadow) and lb_shadow >= 1) or (nonempty(lb_shadow2) and lb_shadow2 >= 1)) == N_SCORED`
- 셀 `gin_none@hk`: 판정한 시행 6회, 대입한 식 `6 == 6` → 참
  - `count((nonempty(lb_shadow) and lb_shadow >= 1) or (nonempty(lb_shadow2) and lb_shadow2 >= 1))` = 6/6. 조건을 만족하지 않은 시행: 없음
- 셀 `f1_b@hk`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count((nonempty(lb_shadow) and lb_shadow >= 1) or (nonempty(lb_shadow2) and lb_shadow2 >= 1))` = 5/5. 조건을 만족하지 않은 시행: 없음

### WT1: 맞음

- 판정식: `count(outcome == "TRANSPARENT" and wq_lines == 2 and wq_queries >= 1) == N_SCORED`
- 셀 `gin_none@hk`: 판정한 시행 6회, 대입한 식 `6 == 6` → 참
  - `count(outcome == "TRANSPARENT" and wq_lines == 2 and wq_queries >= 1)` = 6/6. 조건을 만족하지 않은 시행: 없음

### LT1: 맞음

- 판정식: `abs(median(lat_p50_us, "lat_4k_w10@hk") - median(lat_p50_us, "lat_4k_w0@hk")) <= 0.40`
- 셀 `lat_4k_w10@hk`: 판정한 시행 5회, 대입한 식 `abs(10.500 - 10.500) <= 0.40` → 참

### LT2: 맞음

- 판정식: `abs(median(lat_p50_us, "lat_256k_w10@hk") - median(lat_p50_us, "lat_256k_w0@hk")) <= 0.30`
- 셀 `lat_256k_w10@hk`: 판정한 시행 5회, 대입한 식 `abs(38.880 - 38.880) <= 0.30` → 참

### LT3: 맞음

- 판정식: `abs(median(lat_p50_us, "lat_4k_w1@hk") - median(lat_p50_us, "lat_4k_w0@hk")) <= 1.0`
- 셀 `lat_4k_w1@hk`: 판정한 시행 5회, 대입한 식 `abs(10.500 - 10.500) <= 1.0` → 참

### LT4: 맞음

- 판정식: `abs(median(lat_p50_us, "lat_256k_w1@hk") - median(lat_p50_us, "lat_256k_w0@hk")) <= 1.0`
- 셀 `lat_256k_w1@hk`: 판정한 시행 5회, 대입한 식 `abs(38.880 - 38.880) <= 1.0` → 참

## 셀별 시행 수와 따로 센 시행

| 셀 | 계획 | 실행 | 판정 | 따로 셈(사유: 시행) |
|---|--:|--:|--:|---|
| `bidirf_sym_b@hk` | 5 | 5 | 5 | 없음 |
| `f1_b@hk` | 5 | 5 | 5 | 없음 |
| `f2rel_b@hk` | 5 | 5 | 5 | 없음 |
| `f3_b@hk` | 5 | 5 | 5 | 없음 |
| `f4_b@hk` | 5 | 5 | 5 | 없음 |
| `f4_mix_b@hk` | 3 | 3 | 3 | 없음 |
| `gin_kill@hk` | 6 | 6 | 6 | 없음 |
| `gin_none@hk` | 6 | 6 | 6 | 없음 |
| `gin_qperr@hk` | 16 | 16 | 16 | 없음 |
| `gin_qperr@hq` | 6 | 6 | 6 | 없음 |
| `gin_qperr@hr` | 6 | 6 | 6 | 없음 |
| `gin_qperr_w0@hk` | 4 | 4 | 4 | 없음 |
| `gin_qperr_w100@hk` | 8 | 8 | 8 | 없음 |
| `gin_qperr_w1@hk` | 8 | 8 | 8 | 없음 |
| `gin_stop@hk` | 8 | 8 | 8 | 없음 |
| `hd_rxdeath_b@hk` | 5 | 5 | 5 | 없음 |
| `lat_256k_w0@hk` | 5 | 5 | 5 | 없음 |
| `lat_256k_w100@hk` | 5 | 5 | 5 | 없음 |
| `lat_256k_w10@hk` | 5 | 5 | 5 | 없음 |
| `lat_256k_w1@hk` | 5 | 5 | 5 | 없음 |
| `lat_4k_w0@hk` | 5 | 5 | 5 | 없음 |
| `lat_4k_w100@hk` | 5 | 5 | 5 | 없음 |
| `lat_4k_w10@hk` | 5 | 5 | 5 | 없음 |
| `lat_4k_w1@hk` | 5 | 5 | 5 | 없음 |
| `mr4_cyc_stall@hk` | 5 | 5 | 5 | 없음 |
| `mr4_f1_01@hk` | 5 | 5 | 5 | 없음 |
| `mr4_none@hk` | 5 | 5 | 5 | 없음 |
| `mr4_twolow_stall@hk` | 5 | 5 | 5 | 없음 |
| `nvs_kill@t1_380` | 4 | 4 | 4 | 없음 |
| `nvs_kill@t1w` | 8 | 8 | 8 | 없음 |
| `nvs_kill_rel@t1w` | 5 | 5 | 5 | 없음 |
| `nvs_none@t1_380` | 6 | 6 | 6 | 없음 |
| `nvs_none@t1w` | 8 | 8 | 8 | 없음 |
| `nvs_qperr@t1w` | 6 | 6 | 6 | 없음 |
| `nvs_remacc@t1_380` | 4 | 4 | 4 | 없음 |
| `nvs_remacc@t1w` | 8 | 8 | 8 | 없음 |
| `nvs_remacc_rel@t1w` | 5 | 5 | 5 | 없음 |
| `nvs_stop@t1w` | 8 | 8 | 8 | 없음 |
| `rm4_gap@hk` | 5 | 5 | 5 | 없음 |
| `rm4_gap@hw` | 3 | 3 | 3 | 없음 |
| `rm4_gapx@hk` | 3 | 3 | 3 | 없음 |
| `rm4_kill3_hold@hk` | 3 | 3 | 3 | 없음 |
| `rm4_kill3_untimed@hk` | 5 | 5 | 5 | 없음 |
| `rm4_late01@hk` | 3 | 3 | 3 | 없음 |
| `rm4_late01_rounds@hk` | 3 | 3 | 3 | 없음 |
