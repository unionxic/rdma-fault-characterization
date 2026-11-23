# GIN (NCCL 2.32.3) error-propagation review: proxy and GDAKI, stock and patched

Read-only review, 2026-10-06. Nothing in the repo was changed; archives were unpacked only into this
scratchpad (`review/q4n30/`, `review/ts1/`). Every count I recounted myself is marked **[recount]**.

Path prefixes (all under `/home/unionxic/rdma-error/harness/gpu-initiated/`):

| tag | path | date | doorbell |
|---|---|---|---|
| `GIN` | `gin/results/20260923/` (`v2/logs/`, `ref60/logs/`, `gin_results.csv`, `summary.md`) | 09-23 | proxy: CPU (ibverbs); GDAKI: CPU-doorbell fallback |
| `Q4A`, `Q4B` | `gin_q4/results/20260923/taskA/`, `taskB/` (`logs/`, `taskA.csv`, `taskB.csv`) | 09-23 | CPU fallback |
| `DBW` | `gpu_doorbell/results/20260924{,_w2}/gin_q4/logs/` | 09-24 11:16-12:06 | GPU (inferred, not logged) |
| `RV1` | `gin_recovery/results/20260924/` (`runs/`, `confirm/`, `diag/`) | 09-24 12:07-12:47 | CPU fallback (inferred from time + v1 guard) |
| `RV2` | `gin_recovery/results/20260924_gpudb/` (`runs/`, `q4/`, `v1/`) | 09-24 15:10-15:39 | GPU (logged `mode=GPU`), plus forced CPU proxy |
| `Q4N` | `gin_q4/results/20260925_n30/` (`main/stock/posctl.tar.xz`, `q4_n30_trials.csv`) | 09-25 02:10-09:34 | GPU (2 indicators, inferred) |
| `RN` | `gin_recovery/results/20260925_n30/` (`v2/v1cpu.tar.xz`, `rec_n30_*.csv`) | 09-25 | v2 GPU logged; v1cpu CPU forced |
| `TS1` | `gin_recovery/results/20260925_ts1/` (`*.tar.xz`, `trials*.csv`) | 09-25 | GPU (logged) |
| `TS2a`, `TS2b` | `gin_recovery/results/20260930_ts2/`, `20261001_ts2/` (**uncommitted**) | 09-30, 10-01 | GPU |

Scripts: `gin/scripts/merge_v2.py`, `summarize.py`; `gin_q4/scripts/q4_row.py`, `rebuild_csv.py`,
`summarize.py`; `Q4N/campaign/bin/analyze_n30.py`, `qa_n30.py`; `gin_recovery/scripts/rec_rows.py`,
`summarize.py`, `recount.py` (-> `gin_recovery/results/RECOUNT.md`); `gin_recovery/scripts/ts1/rows.py`,
`summarize.py`, `followup_summary.py`, `followup3_summary.py`, `psn_check.py`;
`gin_recovery/scripts/ts2/rows.py`, `summarize.py`, `tables.sh`.

Setup common to all: rank 0 = rain (initiator), rank 1 = sunny (target), 4 GIN contexts, put 256 KiB +
signal ADD (2 WQEs) per iteration with a 15 ms gap unless stated, IB timeout 14, one op in flight
(except S2 B/C). F1/F3 = env-gated NCCL hook moves this rank's 4 peer QPs to ERR (`gin_fault_inject.diff`);
F2 = put at a 64 MiB offset (outside the MR); F4 = SIGKILL of rank 1 plus driver "drain" puts.

---

## 1. Observed cells

Status: **M** measured (raw logs), **I** inferred, **S** source-only. "r0"/"r1" = rank 0 / rank 1.

### 1a. Stock proxy backend (`NCCL_GIN_TYPE=2`), 09-23, CPU ibverbs, raw `GIN/v2/logs/proxy_*`, script `gin/scripts/summarize.py`

| fault | layer | observation | N | st |
|---|---|---|---|---|
| F0 | L3-L5 | 120/120 ok, no async error, abort clean | 5+5 (v1 baseline, `GIN/gin_results.csv`) | M |
| any | L0 | QP state never queried in this backend | - | gap |
| F1 | L1/L2 | proxy thread WARN `NET/IB/GIN: Got completion ... status=5 ... vendor err 245` (5/0xf5) | 6 | M |
| F2 | L1/L2 | `status=10 ... vendor err 136` (10/0x88) | 6 | M |
| F3 | L1/L2 | `status=12 ... vendor err 129` (12/0x81) | 6 (+4 IB=20) | M |
| F4 | L1/L2 | 10/0x88 (REM_ACCESS, not RETRY_EXC), 6/6 **[recount]** | 6 | M |
| any | L2 | only the first error CQE is logged; progress thread then exits; trailing flushes never logged | - | S (`DESIGN.md`) |
| F1-F3 | L3 timeout | both ranks' device waits `ncclTimeout` at 4780-4807 ms (5 s device cap); data missing **[recount]** | 9 | M |
| F1-F3 | L3 blocking | both ranks hang to the 25 s cap | 9 | M |
| F4 | L3 | initiator drain `drain_device_rc=8` (ncclTimeout, 4.8 s); `init_outcome=error` is the host async error, not a device error | 6 | M |
| F1-F4 | L4 r0 | `ncclCommGetAsyncError` = ncclRemoteError; surface after fault: F1 6.3-10.7 ms, F2 3.2-3.4 ms, F3 3539-3696 ms, F4 59.9-62.0 ms (`GIN/gin_results.csv`); IB=20 F3 ~57.1-58.4 s (estimated, older driver) | 24 | M |
| F1-F3 | L4 r1 (target) | **no async error on rank 1**, 15 s post-poll, incl. F3 whose own QPs were forced to ERR (`host_error=none` 18/18 **[recount]**) | 18 | M |
| F1-F3 | L5 | timeout mode: abort returned both ranks; blocking: abort did **not** return on r0 **and** r1 (`WATCHDOG: abort/teardown did not return; exiting 7`, 9/9 each) **[recount]** | 9+9 | M |
| F4 | L5 | r0 abort returned | 6 | M |

### 1b. Stock GDAKI (`NCCL_GIN_TYPE=3`), raw `GIN/v2/logs/gdaki_*`, `GIN/ref60/logs`, `DBW`, `Q4N/stock`

| fault | layer | observation | N, date, doorbell | st |
|---|---|---|---|---|
| any | L1 | ring CQ (`cq_collapsed=0`, 64B, 128 entries); root-cause CQE kept at its slot | - | S (`gin/README.md`), content measured only in the Q4 build (1c) |
| any | L2 | device poll reads opcode only: REQ_ERR -> `-EIO`; syndrome/vendor_err discarded | - | S |
| F1-F3 | L3 timeout | both ranks `ncclTimeout` at 4784-4808 ms; same code a slow peer gives | 9, 09-23, CPU | M |
| F1-F3 | L3 blocking | initiator flush returns **success**, iteration counted, data never arrives: `init_silent_iters=1` **9/9 [recount]** (+1 IB=20); target hangs to 25 s | 9, 09-23, CPU | M |
| F1 | L3 blocking | same silent success: 2/2 (`DBW` window 1), 10/10 (`Q4N/stock`) **[recount]**; collapsed CQ flag off F1-F3 6/6 (`Q4A`) **[recount]** | 09-24/25, GPU; 09-23 CPU | M |
| F4 | L3 | initiator drain `drain_device_rc=8` (ncclTimeout, the 5 s cap), both "wait modes" use the timeout drain; no -EIO-derived code reaches the app | 6, 09-23, CPU | M |
| F1-F4 | L4 r0 | ncclRemoteError + `GIN Error detected` (no status/vendor_err), at the 10 s QP-state tick: F1 9401-9403, F2 9999.5-10001, F3 9401-9403, F4 8003-8041 ms after fault; IB=20 F3 59407 ms | 24+1, 09-23, CPU | M (time = tick phase, not fault) |
| F1-F3 | L4 r1 | **no async error on rank 1** in 18/18 (15 s post-poll; F3 QPs on r1 are in ERR) **[recount]** | 18 | M; cause not established |
| any | L0 | host check = DOCA `query_last_error` (QP state), throttled `NCCL_GIN_ERROR_QUERY_SEC=10` | - | S; r0 behaviour consistent, r1 F3 not |
| F4 | side | initiator first sees peer death on the driver's management TCP barrier | 6 | M |
| F1-F4 | L5 | r0 abort returned 24/24; **r1 abort did not return in blocking F1-F3 9/9 [recount]**; timeout mode r1 clean 9/9 | 09-23, CPU | M |

### 1c. GDAKI + Q4 device classifier + host mailbox (`gin_q4_classify.diff`, `NCCL_GIN_FAULT_CLASSIFY=1`)

| fault | layer | observation | N, date, doorbell | raw | st |
|---|---|---|---|---|---|
| F1-F4 | L0 | host QUERY_QP at record time = ERR in every classified trial; 100 ms QP watch: F1/F2 ERR at first sample (98-100 ms), F3 at 3.6-3.8 s | 36 (`Q4A`) + 24 (`Q4B`) **[recount from CSV]**, 09-23, CPU | `Q4A/taskA.csv` `host_query`, `qpwatch_err_ms` | M |
| F1-F4 | L1 ring | polled (signal, WQE T) CQE = 5/0xf9 in every ring trial; root at T-1 (F1 @76, F2 @0, F3 @76/74, F4 @354-358); window err=2 ok=0; CQ buffer 2/128 | 33 **[recount]**, CPU | `Q4A`, `Q4B` logs | M |
| F1-F3 | L1 collapsed | slot at poll = root (5/0xf5, 0x13/0x88, 0x15/0x81) 27/27 **[recount]**; 500 µs later 5/0xf9 18/18; buffer 1/128 | 27, CPU (patched: `CPU_PROXY_UPDATE_PI` needed or deadlock at first SQ wrap) | `Q4A` | M |
| F1-F4 | L2 | class: F1 LOCAL_QP_ERR 5/0xf5, F2 REM_ACCESS 10/0x88, F3 RETRY_EXC 12/0x81, F4 RETRY_EXC 12/0x81: 6/6 per cell (`Q4B`), 9/9 per collapsed cell (`Q4A`) **[recount]** | 09-23, CPU | logs | M |
| F1-F4 | L2 | same, N30: 240/240 (ring+collapsed x F1-F4, 30 each) **[recount]** | 09-25, GPU (inferred) | `Q4N/main` | M |
| F1-F3 | L2 GPU-db | `DBW`: F1 ring2+coll1, F2 ring1+coll1, F3 ring2+coll1 correct **[recount]**; `RV2/q4`: F1 3, F2 2, F3 2, F4 2 | 09-24, GPU | `DBW`, `RV2/q4/logs` | M |
| F1-F4 | L3 | device wait (timeout and blocking) returns ncclRemoteError; `init_silent_iters` 0 in F1-F3 (18/18 `Q4B`, 180/180 `Q4N`) | | | M |
| F4 | L3 | initiator 1 op ahead of killed target: 1/6 (`Q4B`), 5/60 (`Q4N`) **[recount]**; last op had a success CQE, so landed | | | M, landing I |
| F1-F4 | L3 r1 | target unchanged: timeout -> ncclTimeout, blocking -> hang | | | M |
| F1-F4 | L4 | mailbox read 94 µs [56-126] after `%globaltimer` detection, `ncclCommGetAsyncError` 190 µs [69-371] after detection, kernel return seen 372 µs (n=33 ring, CPU) **[recount]**; WARN carries fp, class, cause; API value is only ncclRemoteError | 09-23 | `Q4A/B` CSV | M |
| F1-F4 | L4 time | fault -> API: `Q4B` F1 15.2/15.7, F2 2.8, F3 3638/3698, F4 3702/3643 ms; `Q4N` ring F1 15.60, F2 1.60, F3 3678, F4 3686; collapsed 15.24, 1.60, 3632, 3698 ms (medians) | | `N30_20260925.md` §1 | M |
| F1-F3 | L5 | r0 abort returned (54/54 `Q4B`, 240/240 `Q4N`); **r1 abort did not return in blocking F1-F3: 90/90 `Q4N/main` + 10/10 `Q4N/stock` [recount]** | | `*_r1.log` WATCHDOG line | M |
| none | overhead | p50 +0.06-0.10 µs at 4 KiB (not recounted) | 40 runs, 09-23, CPU | `gin_q4/results/20260923/lat/` | M |

### 1d. GDAKI + Q4 + recovery, application-driven (`gin_recovery.diff` v1 CPU; `gin_recovery_gpudb.diff` v2 GPU)

| fault | layer | observation | N, date, doorbell | raw / script | st |
|---|---|---|---|---|---|
| F1, F3 | L3 | kernel returns ncclRemoteError; `ncclGinFaultQuery` returns class, fp, recoverable (new API) | all rounds | `RV1/runs/logs` | M |
| F1, F3 | L3 app | recovered: 112 rounds after a fault (92 recovered + 20 replay failed by an in-commit shot), 18 forced D0; all d=1 after faults, V+d=expected 130/130 **[recount]**; 32/32 fault runs bit-exact, signal exact | 64 runs, 09-24, CPU | `RV1/runs/logs`, `RECOUNT.md` | M |
| F1, F3 | L3 app | GPU mode: 56 rounds (47+9 rf) incl. controls and forced proxy; matrix 18/18 fault runs | 40 runs, 09-24, GPU | `RV2/runs/logs` | M |
| F1, F3 | L3 app N30 | v2 F1 30/30, F3 30/30, x5 10+10, D0 30; v1cpu F1 10, F3 10; kernel return -> recovered 8.30-8.87 ms | 190+20, 09-25 | `RN`, `N30_20260925.md` §2 | M |
| F1 | time | fault -> recovered 24.0 ms (CPU, includes 15 ms gap), 9.71 ms (N30 v2, in-flight) | | | M |
| F3 | time | 3.64-3.74 s (CPU), 3600 ms (N30): RETRY_EXC detection | | | M |
| F2 | L4 | decline "class not recoverable" 3.9-4.1 ms after bad put (CPU), 2.90 ms (N30, fault -> `ncclGinFaultQuery`); async error stays ncclRemoteError; driver's 200 µs async poll often misses it (decline race, N30 §5.3) | 6 / 30 | | M |
| F4 | side | RETRY_EXC 12/0x81 + FIN on driver OOB socket -> decline without handshake, 3.66-3.73 s (CPU), 3720 ms (N30) | 6 / 30 | | M |
| F1, F3 | L4 | final `ncclCommGetAsyncError` = no error after commit | | | M |
| F1, F3 | L0 | Prepare moves QPs ERR, drains; CQEs in window 2/0 err/ok; Commit 2RST/INIT/RTR/RTS ~3.1 ms (firmware) | | | M |
| F2, F4 | L5 | both aborts return because the driver self-signals its own waiter; before the kernel-warming fix the F2 blocking r1 hung to 30 s (exit 7) | `RV1/diag/f2_before_warm`, `cancel_phase` | | M |
| any | v1 under GPU db | declined at Prepare "doorbell mode is not CPU proxy" 2/2 | `RV2/v1` | | M |
| neg | `doca_cqe_rsvd` | replay succeeded on the wire, initiator flush timed out (spurious failure, stale slot `wqe_counter` 23) 2/2 | `RV1/diag/negative` | | M |

### 1e. Transparent recovery S1 (`gin_transparent_s1.diff`, `NCCL_GIN_FAULT_TRANSPARENT=1`), 09-25, GPU (logged), raw `TS1/*.tar.xz`

| fault | layer | observation | N | st |
|---|---|---|---|---|
| F1, F3, F1x5, F1 in-flight | L3, L4 | every flush ncclSuccess, all slots bit-exact, final signal exact, 0 async errors on both ranks: f1_b 30, f1_t 10, f3_b 10, f3_t 5, f1x5_b 10 (50 rounds), f1g0_b 30 = **95/95 [recount]** | 95 | M |
| F1 in-flight | L0 side | responder `rmsn` = executed prefix; re-posted n=0 in **14/30**, n=2 in 16/30 **[recount]**; `next_rcv_psn` agrees 105/105; forced n=1 30/30 (`v2_split`) | | M |
| F1, F3 | L3 time | one slow iteration: F1 10.4 ms, in-flight 10.6 ms, F3 3.60 s | | M |
| F1, F3 | log | `GIN/TS: recovered ... class=LOCAL_QP_ERR fp=5/0xf5 ... S/U/n=...` keeps class and fp in the log only | | M |
| F2 | L3, L4 | decline 1.49 ms after mailbox; flush ncclRemoteError at it 10; async error on both ranks (r1 via library-socket FAIL) | 30/30 | M |
| F2 | L5 | r0 abort returns; **r1 abort does not return (exit 7)**: its own `waitSignal` kernel spins | 30/30 | M |
| F4 | L3, L4 | decline 3.78 s [3.57-3.82] after kill ("RETRY_EXC and the peer's socket shows FIN/RST"); flush ncclRemoteError; r0 abort returns | 10/10 | M |
| stalled/dead helper | L3 | blocking flush ncclRemoteError at 4.0 s (1x hold, 30/30) or 8.0 s (2x hold, 10/10); watchdog async error 2.0 s after stall; never ends a device wait | `v2_bounds`, `v3_late` | M |
| app timeout 0.5 s | L3 | ncclTimeout at 469 ms (10/10) | `v2_bounds` | M |
| abort mid-round | L5 | 730 ms [588-1010] 10/10; before fix did not return within 15 s (1 run) | `v2_*`, `v3_abortmon` | M |
| flag off / gpudb | L3 | ncclRemoteError at the fault (Q4 behaviour), r1 no async error (5/0) | 5+5 | M |

### 1f. Transparent recovery S2 (`gin_transparent_s2.diff`), **uncommitted, partly unfinished**, GPU

Builds: first 744517c9 (`TS2a`), intermediate 6ff74bb6 (`TS2b/prev_6ff74bb6/`), final 0a32b875 (`TS2b/{reg,b,c,d,new}`).

| fault | layer | observation | N, build | st |
|---|---|---|---|---|
| F1, F3, F1x5, in-flight | L3, L4 | transparent: f1_b 13/13, f3_b 10/10, f1x5_b 10/10 (50 rounds), f1g0_b 30/30 (re-posted n=0 22, n=2 8) **[recount]** | final `TS2b/reg` | M |
| F2, F4 | L3, L4 | declined 10/10 each; r1 F2 abort does not return | final `TS2b/reg` | M |
| F1 bursts, 2x2 CTAs | L3 | transparent 10/10 per cell (burst F1, F1 not aggregated, F3, F1+second F1 in commit, mtb F1, mtb F3) **[recount from CSV]** | first `TS2a/trials_b.csv` | M |
| F1, 256/1024 threads | L3 | transparent 10/10 each; re-posted n 234-265 (rescue 1234), 563-725 (rescue 5282) **[recount]** | final `TS2b/b` | M |
| F1, 16/64 threads | L3 | 10/10 each **only on intermediate build** (`prev_6ff74bb6/b`); 5/5 each on first build | intermediate | M |
| F1, 256 threads | L2 | **misclassification "class OTHER" 1/10**: report ticket = newest WQE, window held a previous-lap CQE (`b4b`); fixed by ticket = consumer index, `root_src=stale` | intermediate `prev_6ff74bb6/b` (9/10) | M |
| F1 both ranks | L3 | symmetric initiation one-way + self-report knob: 30/30 with tie-break (28 overlapped), 1/10 without | first `TS2a/trials_c.csv` | M |
| F1 both, real bidir (fused kernel) | L3 | F1both 20/20, notie 5/5, F1 4/4 (+1 bind fail), F3 5/5 (final); **sym (1-2 ms offset) 20/20 and notie 1/5 only on intermediate build** | `TS2b/c`, `prev_6ff74bb6/c` | M |
| address flap (new fault, sunny secondary GID removed 0.5-30 s) | L0 | GID index moves on every re-add (21/21 + 6 idle); QPs fail even for 0.5 s | `TS2a/TS2b d` | M |
| flap | L1/L2 | RETRY_EXC 12/0x81 first record 3.78-4.06 s after cut start (same class as F3/F4) | | M |
| flap, S1 | L3, L4 | declined 6/6: responder commit fails on stale GID index; flush ncclRemoteError, async error both hosts | `TS2a/trials_d.csv` | M |
| flap, S2 | L3 | transparent 0.5/6/15 s 5/5 each (first and final builds), 20 s 3/3; 30 s declined 3/3 at the 21 s path-wait bound, no watchdog, both aborts return **[recount]** | `TS2b/d` | M |
| full ring F2/F4 | L2-L5 | declined 5/5 via `post-slot-wait` record, kernel exits, r0 abort returns; before fix both hung 1/1 (`smoke7`) | final `TS2b/new` | M |
| helper stall after PUBLISHING | L3 | 10 s: transparent 5/5; 14 s: flush fails at 12.0 s = 3x hold 5/5; 12 s before PUBLISHING: 8.0 s 3/3 | first `TS2a/trials_e.csv` | M |
| none | overhead | 4 KiB p50 +0.67 µs (+6.5 %), 256 KiB +1.5 % | intermediate (hold `lat` 09:52) | M |

---

## 2. Distinguishable classes per variant and layer (initiator unless stated)

`|` separates classes. "=F0" means indistinguishable from no fault.

| variant | L0 | L1 (what the consumer reads) | L2 | L3 | L4 API value | L4 log / mailbox | L5 |
|---|---|---|---|---|---|---|---|
| stock proxy | not read | F0 \| F1 \| F2,F4 \| F3 (CPU reads root, ring) | same as L1 (WARN) | timeout: F0 \| F1..F4 (ncclTimeout); blocking: F0 \| F1..F3 (hang), F4 not run blocking | F0 \| F1..F4 (ncclRemoteError) | F0 \| F1 \| F2,F4 \| F3 | timeout: all return; blocking: F0,F4 \| F1..F3 (hang, both ranks) |
| stock GDAKI | F0 \| F1..F4 (ERR; F3/F4 only after RETRY_EXC) [I from Q4 build] | root slot: F0 \| F1 \| F2 \| F3,F4 [I]; polled slot: F0 \| F1..F4 (5/0xf9) | F0 \| F1..F4 (-EIO) [S] | timeout: F0 \| F1..F4 (ncclTimeout, = slow peer); **blocking: F0,F1,F2,F3 (success)** | F0 \| F1..F4 at next 10 s tick | F0 \| F1..F4 ("GIN Error detected") | r0 all return; r1 blocking F1..F3 hang |
| + Q4 (ring or collapsed) | same, now read at record time | ring: root found by scan-back, polled = 5/0xf9; collapsed: slot = root at poll | **F0 \| F1 \| F2 \| F3,F4** | F0 \| F1..F4 (ncclRemoteError, both modes) | F0 \| F1..F4 (~0.2 ms after detection) | F0 \| F1 \| F2 \| F3,F4 (WARN, mailbox) | unchanged |
| + recovery v1/v2 | Prepare/Commit act on L0 | as Q4 | as Q4 | `ncclGinFaultQuery`: F0 \| F1 \| F2 \| F3,F4; with OOB FIN: F3 \| F4. App outcome: F0,F1,F3 (completed, exact) \| F2,F4 (declined) | final: F0,F1,F3 (no error) \| F2,F4 | 5-way with liveness | both ranks return (driver releases its waiter) |
| S1 / S2 | QUERY_QP `rmsn` as side channel | as Q4 (+S2 slot-wait record) | as Q4 + liveness | **F0,F1,F3 (success; only latency differs: 10 ms vs 3.6 s)** \| F2,F4 (ncclRemoteError) | F0,F1,F3 \| F2,F4 | 5-way (GIN/TS lines) | r0 returns; r1 F2 hangs |
| target rank, every variant except S1/S2 declines | its QPs ERR in F3 (hook) | no CQE (posts nothing) | - | timeout: ncclTimeout; blocking: hang, for F1..F3 alike | **nothing in any stock/Q4 cell** | nothing | blocking F1..F3 abort hangs |

How channels change the partition:
- Q4 splits {F1}, {F2}, {F3,F4} at L2 and L4-log but the API value stays one class; it removes the F0,F1-F3 merge at L3 (silent success).
- F3 vs F4 is split only by a liveness channel (driver OOB FIN in v1/v2, library socket in S1/S2), never by the CQE on GDAKI. On the proxy F2 vs F4 share 10/0x88; split only by liveness (not implemented there).
- S1/S2 deliberately re-merge F1,F3 with F0 at L3/L4; the class survives only in logs.
- Address flap lands in the F3/F4 class at L1/L2 (RETRY_EXC); S1 then declines it, S2 recovers it if the address returns within ~24 s.

---

## 3. Spot-check recounts against raw data

| claim (doc) | recount (method) | match |
|---|---|---|
| stock GDAKI blocking silent success 9/9 (`gin/README.md`, `RESULTS.md`) | okit lines r0 minus r1 in `GIN/v2/logs/gdaki_F{1,2,3}_blocking_t*_r{0,1}.kv`: 1,1,1 x3; timeout cells 0; IB=20 ref 1 | yes |
| proxy F4 = 10/0x88 | WARN `status=10 ... vendor err 136` in 6/6 `GIN/v2/logs/proxy_F4_*_r0.log` | yes |
| Q4 Task B: class 6/6 per cell, polled = 5/0xf9, flag off silent 1 in 9/9 | regex over `Q4B/logs/*_r0.log` + okit counts | yes; F4 blocking one value of 1 (1-ahead) as documented |
| Q4 Task A collapsed: root in slot 27/27, ring polled 0xf9 | `polled[...]` fields in `Q4A/logs` | yes (collapsed polled = root 27/27; ring 9/9 = 0x5/0xf9) |
| N30 Q4 240/240, silent 0/180, stock silent 10/10, F4 1-ahead 4+1 | unpacked `Q4N/main`, `stock`; first device record vs truth, okit diff; 1 bind-fail trial excluded | yes |
| Q4 device -> mailbox 94 µs, -> API 190 µs | `t_mbx-t_dev`, `t_api-t_dev` over 33 ring rows of `Q4A/B` CSVs: 94 [56-126], 190 [69-371] | yes (190 µs is from detection, not from the mailbox; `RESULTS.md` finding 8 wording is ambiguous) |
| recovery: 130 rounds = 112 (92 + 20 rf) + 18 forced; 12 declines | `rec ev=` lines in `RV1/runs/logs/*_r0.kv` | yes (92/20/18/12) |
| S1 95/95 transparent; in-flight n=0 14/30 | unpacked `TS1/runs.tar.xz`; KV criterion (tx_rc, slots, signal_exact, async_err_samples) + `S/U/n` | yes |
| S2 final-build cells | KV criterion over `TS2b/{reg,b,c,d,new}` and `prev_6ff74bb6/` | **partly**: see section 4 (wrong build labels, placeholders, stale numbers) |
| GPU-db window GIN rows (ring 2/coll 1 etc.), invalid trials | classes per `DBW` log; r1 CUDA errors only in the 5 trials declared invalid | yes |
| "GDAKI teardown returned in all cells" | WATCHDOG line in `*_r1.log` | **no**: r1 hang in 9/9 stock blocking F1-F3, 90/90 + 10/10 N30 blocking |

---

## 4. Invalidated or corrected results, and claims stronger than the data

Already corrected by the authors:
- `GIN` v1 (`gin_results_v1.csv`, `summary_v1.md`): surface times were relative to program start; ">55 s at IB 20" came from 5 s-capped runs; "GDAKI host never learns" came from exiting before the 10 s tick; v1 hook also moved host-RMA and internal-devComm QPs; v1 labelled GDAKI F4 "error" (it is ncclTimeout rc 8).
- "The collapsed CQ hides error completions" rejected in-stack (`Q4A`, 27/27 error CQEs delivered).
- `DBW` window 1: 5 GIN trials invalid (sunny `/dev/nvidia-uvm` major mismatch).
- Q4 driver barrier race (receiver poisoned after the ack) found in recovery work, produced "signal done, data poisoned" once (`RECOVERY_DESIGN.md` §11); the Q4/N30 driver still has it (direction: false data mismatch, not false success; none seen).
- S1: phase-1 cost split (overlapping removals), "watchdog wins" explanation, `tmo_t` row reason, "later runs unaffected by the leaked command slot", phase-1 bounds (flushAsync up to 60 s, timeout not charging parked time, posters unbounded, error vanishing with a dead helper), helper outliving the communicator, teardown use-after-free.
- S2: first build's flap bound "~26 s" (30 s path wait exceeded the 25 s round bound); slot wait rang only on odd epoch; slot wait consuming the error CQE (hang 1/1 F2, 1/1 F4); 64-bit doorbell index spill; 1024-thread trigger past end (4/10 trivially transparent); "class OTHER" misclassification 1/10.

Stronger than the data (not corrected anywhere I found):
1. **Teardown "clean" is rank 0 only.** `gin/README.md` ("GDAKI teardown returned in all cells"), `RESULTS.md` table ("GIN GDAKI (stock) ... clean", "GDAKI + Q4 ... clean") and finding 5 ("GDAKI's teardown returned"): the target's `ncclCommAbort` did not return in every blocking F1-F3 trial (stock 9/9, N30 Q4 90/90, N30 stock 10/10). S1 documents this only for F2.
2. **Target-side blindness is unstated for stock.** Rank 1 never got an async error in 18/18 stock F1-F3 trials of each backend (15 s post-poll, 25 s cap), even in F3 where its own QPs are in ERR. This contradicts the README model "host polls QP state every 10 s" for that rank; cause not established (source not checked).
3. **In-MR overrun "silent loss" for GIN has no retained raw data.** Only the comment in `gin/gin_fault.cu` (lines 415-419) and `gin/README.md` "F2 regimes"; the v1 F2 rows in `GIN/gin_results_v1.csv` all show REM_ACCESS (proxy) or the 10 s tick. `RESULTS.md` finding 4 generalises it to GIN.
4. `RESULTS.md` finding 8 "ncclCommGetAsyncError returns it [the fingerprint]": the API returns ncclRemoteError only; the fingerprint is in the WARN log and, with the recovery patch, `ncclGinFaultQuery`.
5. `RESULTS.md` "GIN proxy ... abort hangs (blocking comm)": true for F1-F3 only; F4 blocking returned (6/6). Proxy blocking hang is on both ranks.
6. Stock proxy and GDAKI F2-F4 cells are n=3 (never re-run at N30). The proxy F4 fingerprint (10/0x88, 6/6) is a race per `../fingerprint_teardown/` (111/161 REM_ACCESS outside DEVX cells), so 12/0x81 is possible.
7. `gin_recovery/README.md` "Measured vs inferred" and "Limitations" still list GPU doorbells as untested / CPU proxy only, while the GPU-doorbell section of the same file measures v2.
8. N30 holds after 2026-09-25 06:45 ran with the leaked `mlx5_1` command slot on rain (`TRANSPARENT_S1.md`); `N30_20260925.md` does not mention it.
9. The doorbell mode is logged only by the v2/S1/S2 builds; for `Q4N` and `DBW` it is inferred (indicators), for `RV1` from timestamps.

S1 open items (from `TRANSPARENT_S1.md`): rank 1 F2 abort hang; residual race after a lost give-up (closed in S2 except a 2x-hold stall inside re-post); `opMu` causation inferred (1/30 vs 0/150); Dekker gates never run with concurrent posters in S1; use-after-free absence only by construction; leaked firmware command slot for all runs after 06:45 on 09-25; +60 % fast-path cost.

S2 open QA items (uncommitted, unfinished):
- Table B rows "16 threads"/"64 threads" say "final build" with placeholders `MT16_N`, `MT64_N`; raw data exist only on the intermediate build (`prev_6ff74bb6/b`, 10/10 each) and first build (5/5).
- Section C "real bidir" sym cells (20/20, notie 1/5) are labelled "reviewed build, holds c4 and c5"; they exist only in `prev_6ff74bb6/c` (hold c5, 12:16); the final c4 re-run (15:44-15:48) has no sym cells.
- Latency table labelled "reviewed build" but hold `lat` ran 09:52 on the intermediate build (provenance row says it was not re-run).
- In-flight split quoted as n=0 21 / n=2 9 = intermediate build; final build 22/8. F1 n=13 on final, not 10.
- Limits section is stale: "Bidirectional traffic could not be tested" contradicts section C; "+6.0 %, +0.61 µs; +1.2 %" vs table "+6.5 %, +0.67 µs; +1.5 %"; "re-posted n up to 721, 476-593 rescued per round" vs table "563-725, 5282 total".
- Generated files lag the raw data: `TS2b/summary.md` dated 10-01 09:55 (intermediate build, missing reg/b/c sections); `trials_c.csv` 12:19 (intermediate); `trials_d.csv` 15:05 lacks the final 15/20/30 s cuts; `trials_new.csv` 14:12 lacks the 15:37-15:42 re-runs (raw has hring2 8, ring_f2/f4 10). Doc last modified 14:14; final holds ran to 15:48.
- Bind-failure trials in final dirs: f1g0 1, f2 1, bidirf_f3 1 (excluded).
- `tsLateFail` CAS unbounded under contention; E residual (2x-hold stall inside re-post); gate correctness rests on CE-vs-L2-atomic coherence (micro-test only, 2 GPUs).
- The two-kernels-per-GPU bidirectional failure (sender kernel not starting while a GIN receiver kernel runs, 0/16) is unexplained and also on the unpatched build.

---

## 5. Gaps for a cross-layer table

L0
- No port or q counters (`out_of_sequence`, `local_ack_timeout_err`, `packet_seq_err`, `req_remote_access_errors`, ...) were read in any GIN run. Only firmware command counters (`TS1 v2_fwcmd`, `TS2*/fwcmd_*`).
- QP state of the target (rank 1) never queried; initiator QP watch only in `Q4A` (100 ms resolution, F1-F3, CPU doorbell).
- Stock builds: QP state only implied by the 10 s check.

L1
- Stock GDAKI CQE contents never read by the stock binary (only by the Q4 build).
- Proxy: only the first error CQE is visible (WARN); trailing flushes, and whether the consumer ever reads a flush first, unmeasured.
- Op shape is always 2 WQEs (put+signal) except S2 bursts; a collapsed CQ with more WQEs behind the root (would hold 5/0xf9 at poll) is inferred, not measured; collapsed CQ never used with recovery.
- Target-side CQEs: none by design (one-way WRITE + atomic); bidirectional only in S2 fused cells.

L2/L3
- Stock GDAKI `-EIO` never observed directly (source only).
- F4 with a blocking device wait: only in S1/S2 (`f4_b`, flush blocking in the unmodified kernel). Stock, Q4 and v1/v2 drivers always drain with the timeout wait (`gin_q4/gin_q4.cu` line ~719 `useTimeout=1`; `gin_recovery/gin_rec.cu` ~line 912), so their "F4 blocking" cells are timeout-wait cells.
- Stock GDAKI F2-F4 and proxy anything under GPU doorbells: not run (only stock F1 blocking at GPU db).
- `get` (RDMA READ), 0-byte put (NOP), counters/companion QPs, fetch atomics: never faulted (S1/S2 decline them by design).
- No proxy-backend classifier or recovery; proxy F2 vs F4 never separated.

L4
- Target rank's L4 is empty in every stock/Q4 cell; cause (why the 10 s QP-state check never fires on rank 1) not established.
- IB timeout 20 only for proxy F3 (4) and GDAKI F3 blocking (1); Q4/recovery never at 20.
- REM_ACCESS detection latency has two unexplained modes (1.3-1.7 vs 2.5-3.0 ms, N30 §5).

L5
- Non-blocking communicator never tested (registration failed); all abort data are on blocking comms.
- Proxy abort hang never examined beyond watchdog exit; no `ncclCommDestroy` path measured for stock.

Faults never run
- Link down (forbidden), host death without FIN (keepalive path untested), >2 ranks, Hopper, mixed multi-fault (e.g. F1 then F2), F3 x5 fault inside the replay for S1, address flap on stock/Q4/v1/v2 builds (only S1 and S2), RNR (not applicable), in-MR overrun on GIN with retained logs.
