# NVSHMEM IBGDA error propagation: review of existing results (read-only, 2026-10-06)

`G` = `/home/unionxic/rdma-error/harness/gpu-initiated`. Recount scripts used for this review: `review/{abc_recount,cpu_recount,dbrk_recount,ft_recount}.py` in this scratchpad.

**Build tags.**
- `dev` = devel 7bb2e99 + `G/nvshmem/nvshmem_ibgda_fault_inject.diff`. The hooks are off by default, so `dev` behaves like stock.
- `+nrc` = + `G/nvshmem_rootcause/nvshmem_nrc_proxy_sq_dbr.diff`. With knob 0 the build is stock. With `NVSHMEM_IBGDA_PROXY_SQ_DBR=1` it applies the DBR fix.
- `+ft1` = + `G/nvshmem_ft/nvshmem_ibgda_ft.diff`.
- `+ft2` = + `nvshmem_ibgda_ft_v2.diff` (v2/v2.1/v2.2).
- `+t1` = + `nvshmem_ibgda_transparent.diff`. **Uncommitted.**
- `380` = official v3.8.0-0, unmodified.
- `380fix` = `380` + `G/nvshmem_rootcause/official380/fix.diff`.

**Handler tags.**
- `CPU` = cpu_host_memory proxy. It was the `auto` choice before PMO (2026-09-24 13:53).
- `GPU` = GPU NIC handler.

**Fault tags.**
- F2a = put that overruns its object but stays inside the MR.
- F2b = invalid rkey.
- FLAP = sunny's RoCE address removed for a while.
- SOCK = outage of the library's TCP socket.

## 1. Observed cells

| # | handler / variant | fault | layer | observation | N, date | build | raw data → summariser | status |
|---|---|---|---|---|---|---|---|---|
| 1 | CPU stock | F1,F2b,F3,F4 | L0 | QUERY_QP ERR in every fault trial. `hw_sq` stays at the failing WQE, `sw_sq`=0. DBR word0=pi, word1=0 (e.g. F3: ERR hw 29 sw 0; F4: ERR hw 23/25 sw 0) | abc B 3 per fault, 09-24 15:02-15:27 (PMO, handler forced) | dev+nrc knob0 | `G/nvshmem_rootcause/results/20260924_abc/B/*.pe0.log` → `scripts/abc_table.py` → `abc_trials.csv` | measured |
| 2 | CPU stock | F3 | L0 | QP reaches ERR about 3.6 s after the put (watch clock 5.2-5.3 s; put rung at about 1.6-1.7 s). Rain transmits retry bursts of 65-69 pkts every 0.5 s for about 3 s | nv1/nv2 3+2, 09-24 12:28-12:42 (no PMO) | dev+nrc knob0 | `.../results/20260924/nv1,nv2/*.pe0.log,*.cnt` → `scripts/summarize.py` → `nvshmem_trials.csv` | measured |
| 3 | CPU stock | F2b | L0 | state=6, hw_sq 15, sw_sq 0 (162 samples) | 3, 09-23 | dev | `G/nvshmem/results/20260923/ab/F2b_timeout_tcc1_*` | measured. The run is valid even though the watch held the lock, because the put was rung |
| 4 | CPU stock | F1-F4 | L1 | No 0xd/0xe CQE in any of the 1024 entries of the RC or DCI CQ (SCAN errs=0 in 25/25 scans). Slot opcode was 0x0 in all 363 post-wait reads I found (README says 364) and in 45/45 snapshot samples. At IB timeout 20 (F3 ref) there was still none at 38.1 s. Since the 3-way run: 0/12 in abc B; 0/10 in nv1/nv2 knob0 | 54 + 1 + snapshots, 09-23; abc 09-24 | dev | `G/nvshmem/results/20260923/{matrix.csv,f2b/,ref/,scan/,snap/}` → `G/nvshmem/summarize.py` → `summary.md` | measured |
| 5 | CPU stock | F0 / F2a | L1-L5 | F0: 0x0, ok, finalize clean (15/15 + 3). F2a: 0x0, wait ok, PE1 mismatch, silent 9/9, finalize clean | 09-23 | dev | `G/nvshmem/results/20260923/matrix.csv` | measured |
| 6 | CPU stock | F1-F4 | L2 | `ibgda_poll_cq` spins with no bound. `wqe_counter` is frozen at the last good WQE while `ready_head` keeps advancing | as #4 | dev | same | measured (the stall); spin reason from source |
| 7 | CPU stock | F1,F3,F4 | L3 | Blocking `nvshmem_quiet` hung 9/9 until the 30 s watchdog. Timeout and deepep modes only expired the driver's budget (1.46 / 3.85 / 5.75-5.79 s; these are budgets, not detection times) | 3 per cell, 09-23 | dev | `matrix.csv` | measured |
| 8 | CPU stock | F4 | L3 | Iteration 5 `nvshmem_quiet()` had not returned after 30 s, 3/3. F0: 40/40 iterations, 1.0-2.2 ms | 3 + 1, 10-01 20:35-20:39 | **380** | `G/nvshmem_rootcause/results/20261001_official380/{trials.csv,*.pe0.log}` ← `official380/run.sh` (one CSV row per trial, no summariser) | measured |
| 9 | all 380 variants | F0,F4 | L0 | rain port `hw_counters` (local_ack_timeout_err, req_cqe_error, req_cqe_flush_error, req_remote_access_errors) +0 in 11/11 trials | 11, 10-01 | 380 / 380fix | `trials.csv` col 9 | measured |
| 10 | CPU and GPU stock | F1-F4 | L4 | No host signal. NVSHMEM prints nothing after the fault (official380 logs). ibgda.cpp has no async-event reader, no completion channel and no QUERY_QP | - | dev, 380 | `.../20261001_official380/*.pe0.log`; `G/nvshmem_rootcause/README.md` ("What the host sees") | measured (absence) + source |
| 11 | CPU stock | F1-F4 | L5 | `nvshmem_finalize` hangs. Q2: 12/12 + F2b 3/3 (watchdog exit 7). abc B: pe0 rc 7 in 12/12. **Not measured on 380**, because kill_repro exits without finalize | 09-23, 09-24 | dev | `matrix.csv`, `abc_trials.csv` | measured |
| 12 | CPU DEVX repro (no NVSHMEM) | F1,F1post,F2b,F3 | L0/L1 | With word1=0: QP ERR 35/35 and error CQE 0/35. With word1 written: 21/21. q-counter: F3 local_ack_timeout_err +6, F2b req_remote_access_errors +1, req_cqe_error 0 (word1=0) vs 2 (word1 written) | 57, 09-24 12:08-12:36 | `nrc_devx` | `.../results/20260924/b1..b4/*.req.log` → `scripts/summarize.py` → `all_trials.csv` | measured |
| 13 | CPU DEVX repro | kerr/knak (local 2ERR, NAK, RETRY_EXC) | L0/L1 | The NIC completes exactly [c,P): 195/195. P≤c gives 0 CQEs: 65/65. QUERY_QP sw_sq=P: 225/225. Raising word1 later releases the CQEs within 14-73 µs: 30/30 | 225 + 5 smoke, 09-25 02:08-02:38 | `nrc_devx` | `.../results/20260925_dbrk/{s1..s5}/*.req.log` → `scripts/dbrk_table.py` → `dbrk_trials.csv` | measured |
| 14 | GPU stock | F1/F2b/F3 | L1 (driver's own poll, first 0xd) | F1 0xd/0x05/0xf5@27 at 1.7-1.8 ms. F2b 0x13/0x88@23 at 8.7-9.9 ms. F3 0x15/0x81@27 at 3541-3722 ms (times are post→detection) | 3 each, 09-24 12:00-12:06 (temporary PMO window) | dev (stock binary) | `G/gpu_doorbell/results/20260924_w2/nvshmem/*.pe0.log, matrix.csv` | measured |
| 15 | GPU stock | F1/F2b/F3/**F4** | L1 | F1 0x05/0xf5@27 at 2.0-2.3 ms. F2b 0x13/0x88@23 at 10.3-10.7 ms. F3 0x15/0x81@27 at 3535-3758 ms. **F4 0x15/0x81@23 at 3578-3785 ms**. Scan errs=1. F0 0/3 | 3 each, 09-24 abc A | dev+nrc | `.../20260924_abc/A/` → `abc_trials.csv` | measured |
| 16 | GPU stock | F2b,F3 (+F1 flagoff) | L1 at wake of blocking wait | Slot 0xd/0x05/**0xf9** (trailing flush, failing iteration @24/@28). The root cause is already overwritten | abc A 2+2; w2 F2b 1; b2 flagoff 6 | dev+nrc; dev+nrc+ft1 (FT unset) | `abc_trials.csv`; `G/nvshmem_ft/results/b2/flagoff/*.pe0.log.gz` | measured |
| 17 | GPU stock | F1-F4 | L2 | Wakes when `wqe_counter+1 ≥ idx` (the last WQE, i.e. on the flush). Reads the opcode once and tests REQ_ERR only (not 0xe). Copies the syndrome to `*error` and returns -1. `ibgda_quiet`'s assert is compiled out (NDEBUG). The only release-build trace is the printf in `ibgda_wait_for_slot_availability`, which runs only after an SQ wrap | - | dev = 380 | `G/nvshmem_rootcause/README.md` §"How the GPU-handler path detects" (ibgda_device.cuh:501-633, 1719-1753) | **source-only** (-1 never observed directly; printf never triggered) |
| 18 | GPU stock | F2b,F3 | L3 | `nvshmem_quiet` returned in every iteration. Failing iteration: 9.8-10.8 ms (F2b), 3731-3758 ms (F3); later ones about 2 ms. Driver counted 8/8; PE1 got 4 (F2b) / 6 (F3) | abc A 2+2, 09-24 | dev+nrc | `abc_trials.csv` | measured |
| 19 | GPU stock (ft1 build, FT unset) | F1/F2b/F3 | L3 | Blocking quiet rc=0 on the failed put, 6/6: F1 0.12/0.33 ms, F2b 3.48/3.59 ms, F3 3639/3747 ms. The FT bounded quiet with the flag off: F3 rc=-1 at 3.5-3.6 s, no class | 6 + 2, 09-24 | dev+nrc+ft1 | `G/nvshmem_ft/results/b2/flagoff/` → `scripts/rows.py` → `b2/trials.csv` | measured |
| 20 | GPU stock | **F4** | L3 | Iteration 5 quiet returned after 3537-3755 ms; every later iteration 1.1 ms. All 40 "returned" with the peer dead (silent), 3/3 | 3, 10-01 | **380** | `.../20261001_official380/stock_gpu_*` | measured |
| 21 | GPU stock | F1-F4 | L5 | Finalize hangs: abc A pe0 rc 7 in 16/16 fault trials; b2 flagoff 8/8 on both PEs (pe0 7, pe1 7) | 09-24 | dev+nrc(+ft1 off) | `abc_trials.csv`; `b2/flagoff/*.meta` | measured |
| 22 | GPU stock | F1-F4 | L0 | ERR with hw=sw=pi (abc A watch). DBR word1=pi | abc A | dev+nrc | `abc_trials.csv` | measured |
| 23 | CPU + DBR fix | F1/F2b/F3 | L1 | F1 0x05/0xf5@27 at 1.8 ms (1/1). F2b 0x13/0x88@23 at 10.0-10.3 ms (2/2). F3 0x15/0x81@27 at 3.52-3.63 s (3/3) | nv1/nv2, 09-24 (no PMO) | dev+nrc knob1 | `nvshmem_trials.csv` | measured |
| 24 | CPU + DBR fix | F1/F2b/F3/F4 | L1 | 0x05/0xf5@27 at 1.8 ms. 0x13/0x88@23 at 9.6-10.3 ms. 0x15/0x81@27 at 3581-3792 ms. F4 0x15/0x81@21/@23 at 3508-3696 ms. Identical to A | abc C 3 each | dev+nrc knob1 | `abc_trials.csv` | measured |
| 25 | CPU + DBR fix | F2b,F3 blocking | L1/L3 | Slot 0x05/0xf9. Quiet returned 8/8 while PE1 got 4/6. 9.9-10.4 ms / 3582-3587 ms | abc C 2+2 | dev+nrc knob1 | `abc_trials.csv` | measured |
| 26 | CPU + DBR fix | F4 | L3 | Iteration 5 quiet returned after 3744-3792 ms, later 1.1 ms, 3/3 | 10-01 | **380fix** | `.../20261001_official380/fix_*` | measured |
| 27 | CPU + DBR fix | F1-F4 | L5 | Finalize hang, pe0 rc 7 in 16/16 (abc C) and in every nv1/nv2 fault trial | 09-24 | dev+nrc knob1 | `abc_trials.csv` | measured |
| 28 | FT v1 GPU | F1/F2b/F3/F4 | L2/L3 | The first device record has the true class: **48/48** (b2: 24 classify + 24 recover), fp 5/0xf5, 10/0x88, 12/0x81, 12/0x81. N30: 120/120 classify, 60 recover, 20 multi, 20 decline. Silent success 0/90 (N30, F1-F3) | b2 09-24; N30 09-25 | dev+nrc+ft1, FT=1 | `G/nvshmem_ft/results/b2/{classify,recover}/*.pe0.log.gz` → `scripts/rows.py` → `trials.csv`; `results/20260925_n30/nv_n30_trials.csv` | measured |
| 29 | FT v1 GPU | F1-F3 | L1/L2 capture position | At the stock wait position (CAPTURE=exit) 0/24 records hold the root cause (all 5/0xf9). In-loop read: 21/30, lost when there is 0.2-2 ms of compute between post and wait. Device sentinel: 18/18 | 3 per cell, 09-24 | +ft1 | `b2/capture_blocking/` | measured |
| 30 | FT v1 GPU | F1-F4 | L3 | `nvshmem_quiet` is still void. The error is visible only via `nvshmemx_ibgda_ft_status(pe)` or the bounded quiet returning -1. Internal waits (barriers, collectives) return without propagating the error | - | +ft1 | `G/nvshmem_ft/README.md` Limitations | measured for quiet/status; **collectives source-only** |
| 31 | FT v1 GPU | F1-F4 | L4 | Mailbox record. Device→mailbox median 67 µs (my recount: 11-123 µs, n=24 classify; README 8-137 µs, n=222). Fault→host in b2: F1 3.4-4.2 ms (waits for the next put), F2b 1.2-2.5 ms, F3 3.50-3.68 s, F4 3.61-3.79 s. N30 medians: 4.14 / 1.40 / 3717 / 3612 ms. Host QUERY_QP ERR 222/222 | b2, N30 | +ft1 | `b2/trials.csv` (`first_fault_to_mbx_ms`), `G/N30_20260925.md` §3 | measured |
| 32 | FT v1 GPU | F3 vs F4 | side channel | Only the OOB socket FIN separates them. Decline reason "RETRY_EXC with the peer dead" 20/20 (N30 decline); F3 recovered | N30 | +ft1 | `nv_n30_trials.csv` | measured |
| 33 | FT v1 GPU | F0-F4 | L5 | Finalize returns: 17-29 ms (b2); PE0 220/220, 17.9-25.7 ms (N30). **Only because the driver calls `ft_abort`/`ft_mark_failed` on decline** | b2, N30 | +ft1 | `b2/trials.csv` (`teardown0`, `finalize0_ms`) | measured |
| 34 | FT v1 on CPU proxy | F1 | L1-L5 | Stock proxy: no record, the bounded wait expired, teardown returned (2). Proxy + fix: LOCAL_QP_ERR classified, prepare declines (2) | 2 + 2, 09-24 | +ft1 | `b2/config/` | measured |
| 35 | FT v2 ring | F1, F2b with 0.2/2 ms compute | L2 | Root cause kept: ring 90/90, collapsed in-loop 0/90, sentinel 90/90. The ring records only when a wait reaches the entry (about 1.9-2.25 ms after posting); a sentinel records it in about 0.04-1.04 ms | 30 per cell, 09-25 | +ft2 (v2) | `G/nvshmem_ft/results/20260925_v2/capture.tar.xz` → `scripts/v2/rows_v2.py`, `summarize_v2.py` → `trials_v2.csv`, `summary.md` | measured |
| 36 | FT v2 bounds | F2a exact / gap / straddle / tail / past heap | L3 | Exact F2a: 0/30 detected with bounds only. With a 512 B guard: 30/30, plus 5/5 blocking (class OOB_WRITE, nothing posted, the QP stays healthy). Gap/straddle/tail 30/30 each; past heap 5/5. Control with the check off: 0/20 | 09-25 | +ft2 | `20260925_v2/oob*.tar.xz` | measured |
| 37 | FT v2.1 | F1/F2b with 16k posts after the fault | L1 | Root cause recorded 155/155. With park, at most 1023 WQEs are rung after the error (130/130) | 09-25 | +ft2 v2.1 | `trials_v21.csv`, `summary_v21.md` | measured |
| 38 | FT v2.1 → v2.2 | F1 + fetch AMOs | L3 (value) | v2.1: 510,028 stale fetch values in 40 runs (3 of them hung with CAPTURE=exit+park and returned none). v2.2: 0 stale in 38 runs; 558,498 poisoned | 09-25 | +ft2 | `20260925_v2/trials_v22.csv` (`amo_dup`, `amo_poison`) ← `rows_v2.py` | measured (CSV level) |
| 39 | FT v2.2, app without decline code | **FLAP** 0.5/6/15 s | L1-L5 | RETRY_EXC 12/0x81 3.80-4.05 s after the cut, 6/6. Status set, 906-908 later ops `status_bad`. QUERY_QP ERR. **Finalize did not return within 65 s (pe0 rc 137) in 6/6**; `leftover_rain=1` in each of the 6 `.meta` files | 6, 09-30 23:26-23:33 | +ft2 v2.2 (transport 6913dea6) | `G/nvshmem_ft/results/20260930_t1/flap_v22.tar.xz`, `summary_t1.md` | measured; **uncommitted** |
| 40 | T1 | F1, F1 in flight, F1×5, mt, F3 | L3 | Transparent (no status, data exact): 20/20, 20/20, 5/5, 10/10, 5/5. Round time 4.64 ms (F1); F3 has one 3.6 s slow op | 10-01 10:36-11:11 (final2) | +t1 | `results/20260930_t1/reg_final2.tar.xz` → `scripts/t1/rows_t1.py`, `summarize_t1.py` → `trials_t1.csv` | measured; **uncommitted, QA open** |
| 41 | T1 | recovered faults | L4 | Only library stderr lines (`[nvshmem-ft] ... class=`, `[nvshmem-t1] FAULT ... RECOVERED ...`). The API error view is clean, so the error is deliberately absorbed | final2/3 | +t1 | `reg_final3/F1_loop_ft1_t11_reg_t1.pe0.log` | measured |
| 42 | T1 | F2A (put past the heap) / F4 / F2 hook | L1/L3/L5 | F2A REM_ACCESS 10/0x88 declined 10/10. F4 RETRY_EXC 12/0x81 + FIN declined 5/5. Status set. Finalize 20.8 / 24.6 ms. PE1's `signal_wait_until` is not released (rc 4). Earlier build, F2 hook (responder revokes access): REM_INV_REQ 9/0x8a, 30/30 declined | final2; mainB 09-30 | +t1 | `reg_final2.tar.xz`, `mainB.tar.xz` | measured; uncommitted |
| 43 | T1 | FLAP 0.5/6/15/25 s, SOCK, fetch in [C,R), dci_fill | L3 | FLAP transparent 5/5/5/3 (slowest op is max(3.6 s, cut)). SOCK 5/5 + 5/5. Fetch: declined 12/12 and 10/10 with poison. dci_fill: 0/24 recovered (declined) | 10-01 | +t1 | `flap_*`, `review4`, `fetch_fixed`, `review*` tars | measured; uncommitted |

## 2. Partitions by variant and layer

Classes are separated by `|`. F2a here means the exact in-MR overrun. Timing that only distinguishes classes is noted in parentheses.

| layer | CPU stock (dev, 380) | GPU stock = CPU + DBR fix (dev, 380, 380fix) | FT v1 (GPU, collapsed, in-loop) | FT v2.2 (ring; + bounds/guard) | T1 |
|---|---|---|---|---|---|
| L0 QP/DBR | {F0,F2a} RTS \| {F1,F2b,F3,F4} ERR with sw_sq=0, word1=0 (F1/F2b ≤0.1 s, F3/F4 about 3.6 s) | same split, but sw_sq=word1=pi | same as GPU; the watcher's QUERY_QP makes ERR host-visible | same | same |
| L1 CQE | {F0,F2a} normal \| {F1..F4} **nothing**, no completion at all | {F0,F2a} \| F1 5/0xf5 \| F2b 10/0x88 \| {F3,F4} 12/0x81. Lasts until the trailing 5/0xf9 overwrites it (about 60 µs); after that all faults read 5/0xf9 | same as GPU | same; the ring keeps the root cause until consumed | same |
| L2 consumer | {F0,F2a} return \| {F1..F4} unbounded spin | {F0,F2a} \| {F1..F4} REQ_ERR -1, syndrome 0x05 (woken by the flush) [source] | {F0,F2a} \| F1 \| F2b \| {F3,F4} if a thread spins on arrival; otherwise collapses to {F1..F4} FLUSH_TRAILING | {F0} \| F2a→OOB_WRITE (only with guard) \| F1 \| F2b \| {F3,F4}, robust to compute gaps | as v2.2 |
| L3 API | {F0,F2a} return \| {F1..F4} hang | **one class**: everything returns void; only latency differs (F1 <2 ms, F2b about 10 ms, F3/F4 about 3.5-3.8 s) | {F0,F2a} \| F1 \| F2b \| {F3,F4} via `ft_status` (quiet stays void) | as L2, plus fetch → poison | {F0,F1,F3,FLAP,SOCK} transparent (latency only) \| {F2A,F2,F4,fetch-in-range} declined with status |
| L4 host | one class (nothing) | one class (nothing) | mailbox: {F0} \| F1 \| F2b \| {F3,F4}; the app separates F3 from F4 by FIN | same | stderr only for recovered faults; host error record only on decline |
| L5 teardown | {F0,F2a} return \| {F1..F4} hang | {F0,F2a} \| {F1..F4} hang | all return **if the app calls ft_abort/mark_failed** | flap_v22: hang without it | all return (the library marks the transport failed) |

Effects of each change:
- **DBR fix:** refines L1 from 2 classes to 4, but **coarsens L3 from 2 to 1**. A detectable hang becomes a silent success, because stock device code drops the CQE. L5 is unchanged.
- **FT v1:** carries the L1 partition up to L3/L4. That holds only when a waiter is polling as the root cause arrives.
- **FT v2.2:** makes the L2/L3 partition robust and adds an OOB class (with the guard).
- **T1:** merges recoverable faults back into F0 at L3/L4, by design.

## 3. Spot-check recounts

| claim (where) | recount from raw | match? |
|---|---|---|
| 3-way: GPU 16/16, fix 16/16, stock CPU 0/12, fault-free 0/9 (`nvshmem_rootcause/README.md`, `UPSTREAM_ISSUE_EVIDENCE.md`) | `ITER` cqe_opcode=0xd or `SCAN errs>0` in `20260924_abc/{A,B,C}/*.pe0.log`: A 16/16, C 16/16, B 0/12, F0 0/9. Codes and times match the README table | yes |
| CPU repro 0/35 vs 21/21, QP ERR in all 56 | `b1..b4/*.req.log` SUMMARY and EV `what=cqe op=0xd`: word1=0 0/35, written 21/21, ERR 56/56 | yes |
| [c,P) 195/195, 65 with P≤c, S4 30/30 | `20260925_dbrk/s*/*.req.log` EV lines (torn re-reads deduplicated): 195/195, P≤c 65/65 zero CQEs, sw_sq=P 195/195, S4 30/30 | yes |
| FT v1 48/48, device→mailbox 67 µs | First `device-classified ... seq=1` class in `b2/{classify,recover}/*.pe0.log.gz`: 48/48. Classify median 67 µs | yes |
| official380 3/3 per variant | `*.pe0.log`: stock CPU 3/3 not returned; GPU 3536.8 / 3744.2 / 3754.8 ms; fix 3744.3 / 3752.8 / 3791.8 ms | yes. **Minor:** the README says F0 iterations took 1.1-2.1 ms; the logs show 1.0-2.2 ms |
| flag-off silent 6/6, teardown hang 8/8 | `b2/flagoff`: rc=0, slot d/0x05/0xf9 6/6; pe0_rc=pe1_rc=7 8/8 | yes |
| 510,028 stale in 40 runs | `trials_v22.csv` v21g_before: `amo_dup` sum 510,028 over 40 runs, 3 of which hung with 0 values | yes. Only 37 runs actually returned values |
| N30 120/120, finalize 220/220 | `nv_n30_trials.csv` | yes |
| GPU window F1/F2b/F3 3/3 each, F2b blocking 0xf9 | `gpu_doorbell/results/20260924_w2/nvshmem/*.pe0.log` | yes |
| stock "364/364 reads 0x0", "51-trial matrix" (`nvshmem/README.md`) | 363 reads (336 matrix + 15 f2b + 12 ref), all 0x0; `matrix.csv` has 54 rows (it includes F2b) | **off by 1 read; row count differs** |

## 4. Invalidated or corrected results, and over-claims

**Invalidated or corrected.** The following are listed in `RESULTS.md` "Rejected", `nvshmem_rootcause/README.md` "Corrections" and `V2.md`:
- `nvshmem/results/20260923/ab/` F1/F3 tcc1 cells: the put was never rung, and F1's 2ERR fired after the watch.
- `qptl/F3` "RTS for 16 s".
- "QUERY_QP is blind / the watch raced init". This was a lock-holding watch, not a race.
- "Puts never retire".
- "Infinite RNR explains F3".
- "The collapsed CQ hides error CQEs". Rejected by the gin_q4 A/B; the real cause is the DBR word.
- cc=0 "init hangs" (lock-held watch). The A1 re-run confirmed a hang, but for another reason: the slot-0-only poll.
- gpu_doorbell window-1 NVSHMEM trials (sunny's CUDA was broken).
- nv1 `F3_timeout_fix0_t2` tag collision (re-run as nv2 `nowatch_t3`).
- F2a relabelled from REM_ACCESS to silent.
- FT v1 "resync steps verified". Per V2 §C, only 6 steps are necessary.
- v2's "ring replaces the sentinel". This holds for classification, not early detection (v2.1).
- v2.1 stale fetches, fixed in v2.2.
- v2.1 `prod_before`=0, fixed in v2.2.
- N30 smoke trial counted as classify.
- `nvshmem/README.md`'s explanation that finalize "tries to quiesce the broken QP". `nvshmem_ft/DESIGN.md` §9 shows the hang comes from the device barrier. Several superseded sentences remain under that README's banner, e.g. "QUERY_QP does not report ERR".

**Claims stronger than the data.**
- `RESULTS.md` FT rows ("`nvshmem_finalize` returns in 17-29 ms", v2.2 "returns"). This holds only when the app's decline path calls `ft_abort`/`ft_mark_failed`. A v2.2 app without it hung 6/6 (row 39).
- "Returns an error (FT status)". `nvshmem_quiet` stays void, and barriers and collectives return without the error (source only).
- Finding 3a scope "3.5.x-3.8.0, 3.4.5 correct". Measured only on devel 7bb2e99 and v3.8.0-0; the other versions are source-only. On 3.8.0 only F4 was run.
- `UPSTREAM_ISSUE_*` "Expected: `nvshmem_quiet()` returns after about 3.7 s". At L3 that return is a silent success (void, the peer is dead). The fix turns a hang into a silent success, not into an error report.
- v2.2 row "stale-value bug since v1". The v1 build was never run with fetches, so this is inferred from v2.1 no-park. "In 40 runs" includes 3 hung runs.
- v2.2 row "90/90 without a sentinel" was measured on the v2 build. F3/F4 classification, recovery and decline were never re-run on the v2.2 build; they come from v1/v2.
- `RESULTS.md` GPU-handler row puts "1.8 ms / 9 ms" (w2, n=3) where abc A gives 2.0-2.3 / 10.3-10.7 ms. Both are post→detection, not fault→detection.
- Understated rather than overstated: the GPU-handler row shows F4 and teardown as "-", and the fix row shows F4 and blocking as "-". Rows 15, 18, 20, 21, 24-27 measured them.

**T1 open QA (uncommitted: `TRANSPARENT_T1.md`, the diff, `nvshmem_t1.cu`, `tests_t1/`, `scripts/t1/`, `results/20260930_t1/`).**
- **The build behind the tables does not match the doc or the diff.**
  - The tables come from final2: transport `c69d6cc4`, logs `hold_ms=78000`.
  - The diff and the doc were modified at 14:50, after `deploy_final3.out` at 14:49 (transport `82737569`, host `3d630308`, driver `e2bb70be`). final3 logs show `hold_ms=93000`.
  - The doc contradicts itself: "How it works" gives 93 s and COPY_MS, while Limits gives `HOLD_MS` 78 s. The provenance line "rebuilds to `c69d6cc4`" is probably stale.
- **Final3 sets are unreported.** They are not in the doc, `summary_t1.md` or `trials_t1.csv`:
  - `review5`: dci_fill, 8 of 27 trials ran. All declined fast (max op 0.33-1.17 s, pe0 rc 3) instead of "at the hold bound"; PE1 KERNEL_TIMEOUT.
  - `reg_final3`: 85 trials, same outcome pattern as final2.
  - `flap_final3`: 15 trials, rc 0.
  - `hold_final3_cut25.out` is 0 bytes.
- **Review items still open:**
  - A second device give-up in the same round is not handshaken.
  - QPs created after init can push the count past 8.
  - A DCI post between the quiescence check and the DCI's 2RST is not excluded.
  - The `atexit` join is untested (review #5).
  - The dci_fill cause is not identified.
  - The flag-off cost of +0.5-0.7 µs is not verified at SASS level.
  - T1-on latency is bimodal (4 of 5 runs slow).
  - There is 1 void trial.
  - Each of the 6 flap_v22 trials recorded `leftover_rain=1` after pe0 was SIGKILLed.

## 5. Gaps that matter for a cross-layer table

1. **GPU handler, F4:**
   - On devel, only the driver's own timeout poll was run (L1). There is no blocking-quiet F4.
   - On 380, only L3 was run. There was no slot read and no finalize, so 380's L1 and L5 for F4 are unmeasured on every handler.
   - On 380, F1, F2b and F3 were never run.
2. **L2 return value is source-only.** `ibgda_poll_cq` returning -1 with the syndrome copied has never been observed. Never built or run:
   - a non-NDEBUG build, where the assert would abort the kernel;
   - `NVSHMEM_TIMEOUT_DEVICE_POLLING=ON`.
3. **The only release-build trace is untested.** The `ibgda_wait_for_slot_availability` printf (after an SQ wrap) never fired: stock never posted more than 1024 WQEs after a fault.
4. **Root-cause residence time in NVSHMEM's collapsed slot under the GPU handler is unmeasured.** Snapshot mode ran only on the stock CPU proxy, where the slot never changes. The about 60 µs figure comes from the CPU verbs runs and gin_q4.
5. **Async events** (QP_FATAL on the DEVX QP) were never checked on any variant.
6. **F2a (exact in-MR overrun) on the GPU handler** with stock code or the fix was never run. It is handler-independent by inference.
7. **IB timeout 20 (the default)** was run only on the stock CPU proxy (no CQE at 38.1 s). The GPU handler, the fix and FT at timeout 20 are unmeasured.
8. **F1 with WQEs truly in flight.** On stock and FT v1, F1 always lands between ops (head flush 0xf5). In-flight F1 was run only in the CPU repro and in T1 ("F1 in flight").
9. **F3 vs F4:**
   - Both give 12/0x81 at L1-L4. The reverse direction (a killed PE on rain, OFED 23.10) was never run on NVSHMEM; the 0x88-vs-0x81 race in `../fingerprint_teardown/` depends on the node.
   - The target PE never sees an error by itself on any variant.
10. **Other faults not run:**
    - Address flap, SOCK and multi-fault on stock (either handler) and on the fix: never run. FLAP was run only on v2.2 and T1.
    - Responder-side errors (0xe RESP_ERR) were never produced.
    - DCI traffic: never. The DCI proxy-bug spillover into other DCIs' records is source-only.
11. **Thin cells.** FT on the CPU proxy has n=2. The F1 knob cells in nv1 have n=1. Every stock cell has n=3.
