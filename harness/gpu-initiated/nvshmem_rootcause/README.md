# Why NVSHMEM IBGDA never gets an error CQE (and why F3 seemed to leave its QP in RTS)

Follow-up to `../nvshmem/` (Q2/Q3, Root cause section) and `../gin_q4/` (Task A). Same
cluster: rain (requester, mlx5_1) and sunny (target, mlx5_0), ConnectX-6 Dx fw 20.43.4100,
RoCE v2, PMTU 4096, IB ack timeout 14, retry count 7. Every cluster run went through
`../common/cluster_run.sh`. Tags: **[measured]**, **[source]** (read in the code),
**[inferred]**.

## Answers

**Question 1: why no error CQE ever reaches NVSHMEM's CQ.** NVSHMEM's CPU proxy writes the
send-queue producer index into the **wrong word of the QP doorbell record** [source].
`ibgda_rc_progress` (ibgda.cpp:581-589) and `ibgda_dci_progress` (:517-525) write to
`dbr_mobject->cpu_ptr + dbr_offset * sizeof(__be32)`. For an RC endpoint `dbr_offset` is 0,
so the value lands in word 0, which is the receive counter (`MLX5_RCV_DBR`). The send counter
(`MLX5_SND_DBR`, word 1) stays 0 for the life of the QP. The GPU NIC handler of the same file
writes word 1 (:3910-3911), and so do DOCA's CPU proxy (doca_gpunetio.cpp:877) and rdma-core
(qp.c:769). Normal traffic still works, because the UAR doorbell carries the index. When
the QP enters ERR, though, the NIC reloads the send producer counter from the doorbell record
[measured]: QUERY_QP's `sw_sq_wqebb_counter` equals the UAR index while the QP is in RTS and
drops to the record's value (0) at the ERR transition. With producer 0 the NIC treats the send
queue as empty [inferred] and generates **no completion at all**. That covers both the
root-cause CQE of the failing WQE and the flushes behind it (q counter `req_cqe_error` +0). The
NIC does detect the fault (`req_remote_access_errors` +1, `local_ack_timeout_err` +6) and does
move the QP to ERR [measured]. The CQ plays no part: collapsed or ring, its size, page size,
init pattern and GPU placement change nothing.

- CPU reproduction: 56 fault trials. With the SQ doorbell-record word left at 0 (NVSHMEM's
  proxy), 0/35 got an error CQE. With it written (word 1), 21/21 did. The QP went to ERR in
  all 56. NVSHMEM's exact field set with only this word changed gets every CQE, and DOCA's field
  set with only this word changed loses every CQE. None of the other 15 differences between the
  two stacks, applied one at a time, changes the outcome [measured].
- NVSHMEM on the GPUs, CPU-proxy handler, with the env knob `NVSHMEM_IBGDA_PROXY_SQ_DBR=1`
  (default off) that changes only that word: F2b gives 0xd / 0x13 / 0x88 (REM_ACCESS) at wqe 23
  and the device wait returns an error 10 ms after the put (2/2). F3 gives 0xd / 0x15 / 0x81
  (RETRY_EXC) at wqe 27 after 3.52-3.63 s (3/3). F1 gives 0xd / 0x05 / 0xf5 at wqe 27 (1/1).
  With the knob off: no error CQE in 10/10 trials that ran (an 11th never initialized, see
  below), the full 1024-entry scan shows errs=0, the watch shows
  `DBR word0(rq)=pi word1(sq)=0`, and the QP is in ERR with `sw_sq_wqebb=0` [measured].
- The lead's GPU-doorbell window (the GPU handler writes word 1) gets the same CQEs with the
  stock binary [measured by the lead]. Re-run under the now-permanent PeerMappingOverride as a
  3-way comparison (53 trials): GPU handler = CPU proxy + knob (an error CQE in 32/32 fault
  trials, the root cause in all 24 timeout-mode ones), stock CPU proxy 0/12 ("3-way comparison"
  below).

**Question 2: F3, ~4 s of retransmission then silence, QP in RTS for 16 s.** These were two
observations from two different runs, and the "RTS" one is an instrument artifact.
1. The diagnostic watch thread of `../nvshmem/nvshmem_ibgda_fault_inject.diff` holds
   `rc_endpoint_lock` across its `sleep_for(period)` [source]. `ibgda_rc_progress`, the CPU
   proxy that rings every doorbell, takes the same lock (ibgda.cpp:542). So
   while the watch runs, the post-fault put is never rung: nothing is outstanding, nothing is
   retransmitted, and RTS is the correct state. This was reproduced exactly [measured, nv2]. With
   the Q2 watch settings (300 ms period, 800 ms delay, lock held), F3 shows `state=3,
   hw_sq=sw_sq=23` for the whole window with `ready_head=25`, the Q2 qptl signature, and rain
   transmits nothing after the fault until the watch ends (17.6 s). Only then does the starved
   put go out and get retransmitted. The same watch with the lock released during the sleep: the
   put is rung, retransmitted, and the QP goes to ERR ~3.6 s later. The fault-inject thread takes
   the same lock: in all three Q2 `ab/F1_timeout_tcc1_*` runs its 2ERR executed only after the
   watch's final dump (log line 308 of 313).
2. Without the artifact, NVSHMEM F3 behaves like verbs on the wire. Retransmission bursts of
   65-69 packets arrive every ~0.5 s for ~3 s, the same with the knob off and on. The QP goes to
   ERR 3.6 s after the put (watch at 100 ms, lock released: 5210-5304 ms watch clock, failing put
   rung at ~1600-1700 ms). Only the RETRY_EXC CQE is missing, for the reason in question 1
   [measured, nv1/nv2]. The "silence" after ~4 s is simply the end of the retries.
   `nvshmem_finalize` still hangs after the error with the knob on (pe0 exit 7 in every fault
   trial). That is a separate teardown issue.

## Method

1. **Source diff** of every CQ/QP context field, WQE control bit and doorbell step used by
   NVSHMEM 7bb2e99c (IBGDA, CPU-proxy NIC handler) and by NCCL 2.32.3 GIN GDAKI (bundled DOCA
   GPUNetIO, CPU proxy, "valid DBR" mode). Field-by-field table with line references:
   `PRESETS.md`. The NVSHMEM code that depends on the NIC handler is listed in the log (12:20).
2. **CPU reproduction** (`nrc_devx.c`, no GPU): one DEVX CQ + one DEVX RC QP per side, every
   field from a named preset (`nvshmem` or `doca`), any differing field overridable alone
   (`--set key=value`); queues and doorbell records in host memory. The requester runs 4
   baseline put + signal pairs (RDMA WRITE + ATOMIC FETCH_ADD, NVSHMEM's WQE shape and CE bits),
   injects one fault, then for 3 s (10 s for F3) spins over the whole CQ buffer (every CQE write
   is logged with its time). Every 100 ms it issues QUERY_QP and QUERY_CQ, reads the QP doorbell
   record and reads rain's port counters. Target on sunny: the same binary and preset. Faults:
   **F1** 8 x (4 MiB put + signal) outstanding, then local 2ERR; **F1post** local 2ERR with
   nothing outstanding, then one put + signal; **F2b** put + signal with an invalid rkey; **F3**
   the target moves its QP to ERR, then one put + signal. `--qcounter 2` attaches the DEVX QP to
   the port's default q counter (id 3, learned from a throwaway verbs QP), so
   `/sys/.../hw_counters` count this QP's events (DEVX `ALLOC_Q_COUNTER` is refused for a
   user context here: syndrome 0x8975f1).
3. **In NVSHMEM** (`nvshmem_nrc_proxy_sq_dbr.diff`, layered on
   `../nvshmem/nvshmem_ibgda_fault_inject.diff`): `NVSHMEM_IBGDA_PROXY_SQ_DBR=1` makes the proxy
   write word 1 (default off = stock). The watch also prints both doorbell-record words, and it
   now releases the lock while it sleeps (`NVSHMEM_IBGDA_FAULT_WATCH_HOLD_LOCK=1` restores the
   base behaviour for the A/B). Only the transport plugin was rebuilt; it is deployed as
   `~/gi-bundle/nvshmem_nrc` on both nodes (md5 `7d9dc262...` on both). Driver, env and fault
   hooks are the Q2 ones (`../nvshmem/`), via `scripts/run_nvshmem_trial.sh`, which also samples
   rain's port counters every 0.5 s.

## Results: CPU reproduction (57 trials, `results/20260924/b1..b4`, `all_trials.csv`)

Error CQE = any opcode 0xd/0xe written anywhere in the CQ buffer during the observation.
QP->ERR is the first 100 ms QUERY_QP sample in ERR. SQ DBR = doorbell-record word 1 at the
end; the UAR index (pi) was 10 (24 for F1). `sw_sq` = QUERY_QP `sw_sq_wqebb_counter` at the end.

| fault | preset | --set | n | error CQE | first error CQE (syndrome/vendor), ms after fault | QP final, ->ERR ms | SQ DBR | sw_sq |
|---|---|---|--:|---|---|---|---|---|
| F2b | nvshmem | - | 3 | **0/3** | none | ERR, 100 (1st sample) | 0 | 0 |
| F2b | nvshmem | dbr_word=1 | 3 | **3/3** | 0x13/0x88 REM_ACCESS, 4.3 | ERR, 100 | 10 | 10 |
| F2b | doca | - | 2 | 2/2 | 0x13/0x88, 3.4-6.2 | ERR, 100 | 10 | 10 |
| F2b | doca | dbr_word=0 | 2 | **0/2** | none | ERR, 100 | 0 | 0 |
| F1 | nvshmem | - | 2 | **0/2** | none | ERR, 0.3 | 0 | 0 |
| F1 | nvshmem | dbr_word=1 | 2 | **2/2** | 0x05/0xf5 (head WQE), 0.3; slot ends 0xf9@23 | ERR, 0.3 | 24 | 24 |
| F1 | doca | - | 2 | 2/2 | 0x05/0xf5, 0.3-0.4 (+15 x 0xf9) | ERR, 0.3 | 24 | 24 |
| F1 | doca | dbr_word=0 | 2 | **0/2** | none | ERR, 0.3 | 0 | 0 |
| F1post | nvshmem | - | 2 | **0/2** | none | ERR, 0 | 0 | 0 |
| F1post | nvshmem | dbr_word=1 | 2 | **2/2** | 0x05/0xf5 or 0xf9, 0.0-0.4 | ERR, 0 | 10 | 10 |
| F1post | doca | - | 2 | 2/2 | 0x05/0xf5, 0.4 | ERR, 0 | 10 | 10 |
| F1post | doca | dbr_word=0 | 2 | **0/2** | none | ERR, 0 | 0 | 0 |
| F3 | nvshmem | - | 4 | **0/4** | none | **ERR, 3700-3800** | 0 | 0 |
| F3 | nvshmem | dbr_word=1 | 4 | **4/4** | 0x15/0x81 RETRY_EXC, 3516-3767 | ERR, 3600-3800 | 10 | 10 |
| F3 | doca | - | 2 | 2/2 | 0x15/0x81, 3559-3602 | ERR, 3600-3700 | 10 | 10 |
| F3 | doca | dbr_word=0 | 2 | **0/2** | none | ERR, 3700 | 0 | 0 |
| none | nvshmem | - | 1 | 0/1 | (normal CQE, wqe 9) | RTS | 0 | 10 |

**Bisection, F2b, from the nvshmem preset with one DOCA value applied at a time** (1 trial
each; every difference is listed in `PRESETS.md`). No error CQE with `cq_cc=0` (+`cq_log_page_size=0`),
`cq_log_size=7`, `cq_log_page_size=0`, `cq_init=1`, `log_sq_size=7`, `rq_srq=0`,
`user_index=0`, the atomic-enable group (`r2i_rae=0,rtr_rwe_rae=1,rtr_opt_mask=4,atomic_mode=1`),
`udp_sport=-1`, `eth_prio_set=0`, `rts_rwe=1`, `write_ce=8`, `db_style=1` (DOCA's
UAR-DBR-fence-UAR order) or `uar_type=1` (BF UAR). Error CQE with `dbr_word=1` and with
`dbr_word=1,uar_type=1` (the GPU handler's word and UAR). Reverse: `doca` with `cq_cc=1` gets
it; `doca` with `dbr_word=0`, alone, with `db_style=0` or with `cq_cc=1`, does not.

**NIC counters for this QP** (`--qcounter 2`, deltas over the observation):

| cell | local_ack_timeout_err | req_remote_access_errors | req_cqe_error | req_cqe_flush_error |
|---|--:|--:|--:|--:|
| F3 nvshmem | 6 | 0 | **0** | 0 |
| F3 nvshmem dbr_word=1 | 6 | 0 | 2 | 1 |
| F2b nvshmem | 0 | 1 | **0** | 0 |
| F2b nvshmem dbr_word=1 | 0 | 1 | 2 | 1 |

The NIC counts the fault itself (the NAK, the ack timeouts) identically. Only the
completion-generation counters differ, so the CQE is never generated; it is not written
elsewhere or lost on the way.

**Doorbell record vs QUERY_QP.** `sw_sq_wqebb_counter` equals pi while the QP is in RTS
(baseline, and F3 before retry exhaustion) and equals doorbell-record word 1 from the first
sample in ERR, in every trial: 0 with word 0 and pi with word 1. `hw_sq_wqebb_counter` stays at
the failing WQE (8) with word 0 and advances to pi with word 1 [measured]. The inferred reading
is that on the error transition the NIC takes the producer from the doorbell record and
completes (with error or flush) the WQEs in [hw consumer, producer). With 0 that range is
empty [inferred]. The same signature is already in NVSHMEM's Q2 watch logs
(`../nvshmem/results/20260923/ab/F2b_timeout_tcc1_*`: `state=6 hw_sq_wqebb=15 sw_sq_wqebb=0`).

## Results: in NVSHMEM itself (GPU, CPU-proxy handler; 18 trials, `results/20260924/nv1, nv2`, `nvshmem_trials.csv`)

Driver `../nvshmem/nvshmem_fault`, timeout wait mode (the driver's own bounded CQ poll, which
classifies REQ_ERR itself), 8 iterations of 256 KiB put + signal at 250 ms, fault at
iteration 4 (F2b) or 1.5 s after connect (F1, F3). Watch = QUERY_QP every 100 ms (lock released)
unless stated. Scan = the device's scan of all 1024 CQ entries after the wait.

| fault | knob | n | device wait | CQE seen by the device | scan errs | QP (watch) | DBR word0 / word1 |
|---|---|--:|---|---|--:|---|---|
| none | 1 | 1 | 8/8 ok | normal | 0 | RTS, hw = sw = 31 | 0 / 31 |
| F2b | 0 | 2 | timeout 9.6 s | 0x0 (last good CQE, wqe 22) | 0 | ERR, hw 23, sw **0** | 25 / **0** |
| F2b | 1 | 2 | **error after 10.0-10.3 ms** | **0xd / 0x13 / 0x88 at wqe 23** | 1 | ERR, hw = sw = 28 | 0 / 28 |
| F1 | 0 | 1 | timeout 9.6 s | 0x0 (wqe 26) | 0 | ERR, hw 27, sw **0** | 29 / **0** |
| F1 | 1 | 1 | **error after 1.8 ms** | **0xd / 0x05 / 0xf5 at wqe 27** | 1 | ERR, hw = sw = 32 | 0 / 32 |
| F3 | 0 | 3 | timeout 9.6 s | 0x0 (wqe 26) | 0 | **ERR** at 5.2-5.3 s, sw **0** | 29 / **0** |
| F3 | 1 | 2 | **error after 3.52-3.58 s** | **0xd / 0x15 / 0x81 at wqe 27** | 1 | ERR at 5.1-5.2 s, hw = sw = 32 | 0 / 32 |
| F3, no watch | 0 | 2 | timeout 9.6 s | 0x0 | 0 | - | - |
| F3, no watch | 1 | 1 | **error after 3.63 s** | **0xd / 0x15 / 0x81 at wqe 27** | 1 | - | - |
| F3, Q2 watch (lock held, 300 ms / 800 ms) | 0 | 1 | timeout 9.6 s, only 4 of 6 pre-fault iterations done | 0x0 | 0 | **RTS, hw = sw = 23 throughout** | 23 / 0 |
| F2b, Q2 watch (lock held) | 0 | 1 | timeout | 0x0 | 0 | RTS, hw = sw = 23 throughout | 23 / 0 |
| F3, lock held, 100 ms, no delay | 0 | 1 | NVSHMEM init never completed (killed) | - | - | - | - |

The watch clock starts at connect. The failing F3 put is rung at ~1.6-1.7 s, so ERR at 5.2 s is
~3.6 s after the put. In F3 the device saw the error 3.5-3.6 s after the wait began.

**Port counters (rain, 0.5 s samples, `*.cnt`).** F3 with the lock released, knob off or on,
watch or no watch: after the fault, bursts of 65-69 packets with almost no packets received,
every ~0.5 s for ~3 s (samples 2.5-5.5 s of the trial clock), then quiet. This is the "~850
packets then silence" of the original report. F3 with the lock held: no transmission after the
fault until 17.6 s (the watch ends at 0.8 + 16 s), then the same burst pattern.

Note: in nv1 two spec lines shared the tag `F3_timeout_fix0_t2`. The first (no watch) row in
`nvshmem.txt` keeps its KV line, but its logs were overwritten by the second. The no-watch case
was re-run as `nv2/F3_timeout_fix0_nowatch_t3`.

## 3-way comparison under one driver state (2026-09-24 15:02-15:27, `results/20260924_abc/`)

PeerMappingOverride=1 permanent on both nodes (`driver_state.txt`), same NVSHMEM build and the
same plugin for all three (md5 `7c385c5a...` on both nodes). **A** = GPU NIC handler
(`NVSHMEM_IBGDA_NIC_HANDLER=gpu`; the knob does not apply). **B** = CPU proxy forced
(`cpu_host_memory`), knob off = stock proxy. **C** = CPU proxy forced +
`NVSHMEM_IBGDA_PROXY_SQ_DBR=1`. The handler was set by `scripts/run_nvshmem_trial.sh` after
`env_common.sh`, and the log confirms it in every trial (A: 19 "GPU", B: 15 and C: 19 "CPU with
host memory backend"). Same driver and faults as above: 8 x 256 KiB put + signal at 250 ms,
DEV_TIMEOUT 10 s. F2b corrupts the rkeys at iteration 4, F1/F3 fire 1.5 s after connect, F4
SIGKILLs PE1 once PE0 has logged iteration 2. The watch is at 100 ms with the lock released.
53 trials, all 3/3 or 2/2 consistent. Per-trial rows: `abc_trials.csv` (incl. per-iteration
quiet durations); table regenerated by `scripts/abc_table.py`.

"App sees" is the test driver's own bounded poll (timeout mode, which stops at the first 0xd
in the slot) or `nvshmem_quiet()` (blocking). "Detection" is the failing iteration's wait time
(from its launch to the error; for blocking, until quiet returned). "Target iters ok" = how
many iterations PE1 received intact. Teardown: pe0 exit 7 = `nvshmem_finalize` hung until the
driver's watchdog; 0 = clean.

| config | fault | wait | n | handler (log) | app sees (wait_rc / quiet) | error CQE in slot at end of wait (op/syn/ven@wqe) | full-scan errs | detection ms (median, range) | QP (watch, end) | DBR word1 (final) | target iters ok | teardown (pe0 rc) |
|---|---|---|--:|---|---|---|---|---|---|---|---|---|
| A | none | timeout | 3 | GPU | ok | 0x0 (last ok) | 0 | - | RTS hw 31 sw 31 | na | 8 | 0 |
| A | F1 | timeout | 3 | GPU | error | 0xd/0x05/0xf5@27 | 1 | 2.1 (2.0-2.3) | ERR hw 32 sw 32 | 32 | 6 | 7 |
| A | F2b | timeout | 3 | GPU | error | 0xd/0x13/0x88@23 | 1 | 10.4 (10.3-10.7) | ERR hw 28 sw 28 | 28 | 4 | 7 |
| A | F3 | timeout | 3 | GPU | error | 0xd/0x15/0x81@27 | 1 | 3755.0 (3535.3-3758.2) | ERR hw 32 sw 32 | 32 | 6 | 7 |
| A | F4 | timeout | 3 | GPU | error | 0xd/0x15/0x81@23 | 1 | 3730.9 (3577.5-3785.1) | ERR hw 28 sw 28 | 28 | 3,4 | 7 |
| A | F2b | blocking | 2 | GPU | quiet returned 8/8 | 0xd/0x05/0xf9@30 | 1 | 10.3 (9.8-10.8) | ERR hw 34 sw 34 | 34 | 4 | 7 |
| A | F3 | blocking | 2 | GPU | quiet returned 8/8 | 0xd/0x05/0xf9@30 | 1 | 3744.7 (3731.1-3758.3) | ERR hw 34 sw 34 | 34 | 6 | 7 |
| B | none | timeout | 3 | CPU with host memory backend | ok | 0x0 (last ok) | 0 | - | RTS hw 31 sw 31 | na | 8 | 0 |
| B | F1 | timeout | 3 | CPU with host memory backend | timeout | 0x0 (last ok) | 0 | - | ERR hw 27 sw 0 | 0 | 6 | 7 |
| B | F2b | timeout | 3 | CPU with host memory backend | timeout | 0x0 (last ok) | 0 | - | ERR hw 23 sw 0 | 0 | 4 | 7 |
| B | F3 | timeout | 3 | CPU with host memory backend | timeout | 0x0 (last ok) | 0 | - | ERR hw 29 sw 0 | 0 | 6 | 7 |
| B | F4 | timeout | 3 | CPU with host memory backend | timeout | 0x0 (last ok) | 0 | - | ERR hw 23 sw 0,ERR hw 25 sw 0 | 0 | 3 | 7 |
| C | none | timeout | 3 | CPU with host memory backend | ok | 0x0 (last ok) | 0 | - | RTS hw 31 sw 31 | na | 8 | 0 |
| C | F1 | timeout | 3 | CPU with host memory backend | error | 0xd/0x05/0xf5@27 | 1 | 1.8 (1.8-1.8) | ERR hw 32 sw 32 | 32 | 6 | 7 |
| C | F2b | timeout | 3 | CPU with host memory backend | error | 0xd/0x13/0x88@23 | 1 | 9.6 (9.6-10.3) | ERR hw 28 sw 28 | 28 | 4 | 7 |
| C | F3 | timeout | 3 | CPU with host memory backend | error | 0xd/0x15/0x81@27 | 1 | 3622.0 (3581.0-3791.9) | ERR hw 32 sw 32 | 32 | 6 | 7 |
| C | F4 | timeout | 3 | CPU with host memory backend | error | 0xd/0x15/0x81@21,0xd/0x15/0x81@23 | 1 | 3618.3 (3507.5-3696.1) | ERR hw 26 sw 26,ERR hw 28 sw 28 | 26,28 | 3,4 | 7 |
| C | F2b | blocking | 2 | CPU with host memory backend | quiet returned 8/8 | 0xd/0x05/0xf9@30 | 1 | 10.2 (9.9-10.4) | ERR hw 34 sw 34 | 34 | 4 | 7 |
| C | F3 | blocking | 2 | CPU with host memory backend | quiet returned 8/8 | 0xd/0x05/0xf9@30 | 1 | 3584.2 (3581.8-3586.6) | ERR hw 34 sw 34 | 34 | 6 | 7 |

Summary [measured]: **A and C are identical.** The root-cause CQE (F1 0x05/0xf5, F2b 0x13/0x88,
F3/F4 0x15/0x81) sits in the slot when the timeout-mode poll stops, detection takes 2 ms / 10 ms
/ 3.5-3.8 s, the SQ doorbell record = pi, and the QP is in ERR with hw = sw. **B** gets no error
CQE in any of the 12 fault trials: the scan shows errs 0, the wait times out after 10 s, word 1
of the doorbell record = 0, and the QP is in ERR with sw_sq 0. F4 behaves like F3 on every
handler (RETRY_EXC, since the killed peer's QPs vanish). In blocking mode (A and C),
`nvshmem_quiet()` returned on every iteration and the driver counted 8/8 done while the target
received only 4 (F2b) or 6 (F3). The failing quiet returned when the trailing flush arrived
(10 ms / 3.6-3.8 s), and later ones in ~2 ms. The slot then held 0xd / 0x05 / 0xf9, not the root
cause. Teardown hung after every fault on every handler.

### How the GPU-handler path detects an error today (source + config A/C)

Line numbers: `ibgda_device.cuh` = `src/include/non_abi/device/pt-to-pt/ibgda_device.cuh`,
`ibgda.cpp` = `src/modules/transport/ibgda/ibgda.cpp`, NVSHMEM 7bb2e99c, release build
(`-DNDEBUG`, `NVSHMEM_TIMEOUT_DEVICE_POLLING=OFF`, `NVSHMEM_IBGDA_DEBUG` undefined, as printed by
the library at init).

**Who polls what.** Only the device polls, and only inside `ibgda_poll_cq`
(ibgda_device.cuh:501-633). It reads a single CQE, `cq->cqe` (:504), i.e. slot 0 of the collapsed
CQ (`cc=1`, ibgda.cpp:1535). It never indexes further. It is called from three places:
- `ibgda_quiet` (:1719-1734), which is reached from `nvshmem_quiet()` (nvshmem_defines.h:736) ->
  `nvshmemi_transfer_quiet` (transfer_device.cuh.in:440-449) -> `nvshmemi_ibgda_qp_quiet` (:3673)
  -> `ibgda_quiet_with_cst` (:2154-2190), for every RC/DCI in scope. It is also reached from every
  blocking (non-`_nbi`) put, get, AMO and put-signal (`if (!is_nbi) ibgda_quiet(qp)`, e.g. :3392-3393)
  and from the barriers and collectives.
- `ibgda_wait_for_slot_availability` (:1736-1753), only once the SQ has wrapped
  (`wqe_idx >= nwqes`, i.e. after 1024 WQEs on a QP).
- Nothing else. The `_nbi` puts, including `nvshmem_putmem_signal_nbi`, never poll.

**When it returns, and what it checks.** `ibgda_poll_cq(cq, idx)` returns at once if
`cons_idx >= idx` (:524). Otherwise it spins, **without a bound**, until the slot's
`wqe_counter + 1 >= idx` (:561-592): until a CQE of any kind has been written for WQE `idx-1`,
the last WQE posted. Only then does it read the opcode once (:608-611). It tests only
`MLX5_CQE_REQ_ERR` (0xd). `MLX5_CQE_RESP_ERR` (0xe) and the syndrome are not looked at, except
that the syndrome is copied into `*error` (:613). It returns -1. "NVSHMEM always treats CQE errors
as fatal" (:605) is the stated intent.

**What the application gets.** Nothing. `ibgda_quiet` does `assert(likely(status == 0))`
(:1732) and returns the ticket. `nvshmem_quiet()` reaches it through `nvshmemi_transfer_quiet`,
which is instantiated in `libnvshmem_device.a` (transfer_device.cuh.in:476-484), and that
library is built with `-DNDEBUG -O3` (build `src/device/CMakeFiles/nvshmem_device.dir/flags.make`).
So the assert is a no-op. Code that inlines `ibgda_quiet` into an application kernel compiled
without NDEBUG would hit a device assert (kernel abort) instead [source, not measured]. The
printf is inside `#ifdef NVSHMEM_IBGDA_DEBUG` (:1727-1730). `nvshmem_quiet()` and every blocking put are `void`.
The only release-build trace is the unconditional printf in `ibgda_wait_for_slot_availability`
(:1746-1749), "ibgda_poll_cq failed with error=%d" with the syndrome. It fires only if a
later WQE needs a slot after the SQ wrapped, and it never appeared in these runs (8 iterations).

**What the host sees.** Nothing. With the GPU handler there is no proxy
(`host_ops.progress = NULL`, ibgda.cpp:5307-5308; `no_proxy`, :5323). The CQ is bound to EQ 0
(:1518, :1540) but never armed. There is no completion channel, no async-event reader and no
QUERY_QP anywhere in ibgda.cpp (the QP states in the tables come from our diagnostic watch).
`nvshmem_finalize` then hangs (pe0 exit 7 = the driver's watchdog, in every fault trial).

**Root cause vs trailing flush in the collapsed slot.** NVSHMEM's put + signal is two WQEs, and
only the signal (the last) is signaled. The root cause lands on the put (wqe N-1); the flush
0x05/0xf9 for the signal (wqe N) overwrites slot 0 ~60 us later (Q1).
- `ibgda_poll_cq` waits for `wqe_counter == N` (the last WQE). So it wakes on the **flush**, and
  what it reads is 0xd with syndrome 0x05 (WR_FLUSH). The root cause (0x13/0x88, 0x15/0x81,
  0x05/0xf5) is already gone at that point. Only when the failing WQE is itself the last one
  would the root cause be visible. Measured in A blocking: slot 0xd/0x05/0xf9, quiet returned.
- The test driver's own timeout-mode poll (not NVSHMEM code, `../nvshmem/nvshmem_fault.cu:265-289`)
  checks the opcode on every spin and stops at the first 0xd. It therefore catches the root cause
  before the flush arrives (A timeout: 0x13/0x88 @23, 0x15/0x81 @23/@27, 0x05/0xf5 @27; 12/12 timeout-mode fault trials).
  A library-side classifier must read the slot the same way, or it must find the root cause by
  other means (Q1/Q4).
- Blocking, measured (A, 2+2 trials): the failing iteration's `nvshmem_quiet()` returned after
  9.8-10.8 ms (F2b) or 3.73-3.76 s (F3), the arrival time of the flush. Every later iteration's
  quiet returned in ~2 ms, because its WQEs were posted to a QP in ERR and flushed at once. The
  driver counted 8/8 iterations complete while the target received only 4 (F2b) or 6 (F3). Every
  post-fault iteration was a silent success.

## Investigation log (KST, 2026-09-24)

Each entry: hypothesis, experiment, result, conclusion.

- **11:05-11:30, H1 (doorbell-record word), from source.** Diffed both stacks field by field
  (`PRESETS.md`). NVSHMEM's CPU proxy writes the SQ producer index to doorbell-record word 0
  (`dbr_offset * sizeof(__be32)` with RC `dbr_offset` 0, ibgda.cpp:581-589). Its own GPU handler
  (:3910-3911), DOCA's proxy (doca_gpunetio.cpp:877, 1245-1247) and rdma-core (qp.c:769) write
  word 1 (`MLX5_SND_DBR`). In proxy mode the GPU never writes the record
  (`ibgda_proxy_post_send`, ibgda_device.cuh:1588-1606). DOCA's proxy comments that the NIC reads
  the DBR "when the NIC enters a recovery state". Secondary candidates H2-H15: CQ size, page size,
  init pattern; SRQ vs zero-size RQ; atomic-enable placement and opt mask; UDP source port;
  eth_prio; RTR2RTS rwe; the put's CE bit; doorbell order; UAR type; user_index; SQ size.
- **11:30-12:07, blocked.** The cluster lock was held by a leaked fd (the lead's note in
  `cluster_run.log`). Built `nrc_devx` and the NVSHMEM knob meanwhile.
- **12:02, prediction (logged before any result).** The GPU handler writes word 1, so H1
  predicts error CQEs with GPU-rung doorbells, and F3 QP -> ERR.
- **12:04-12:20, the lead's GPU-doorbell window (measured by the lead,
  `../gpu_doorbell/results/20260924_w2/nvshmem/`).** GPU handler, stock binary: F2b 0xd/0x13/0x88
  at wqe 23 (3/3); F1 0xd/0x05/0xf5 at wqe 27 (3/3); F3 0xd/0x15/0x81 at wqe 27 after 3.54-3.72 s
  (3/3). The blocking `nvshmem_quiet` returned success on F2b with 0xd/0x05/0xf9 in the slot
  (Q1's flush overwrite, assert compiled out). This matches the prediction. [source] The
  handler-dependent code is: QP DBR allocation (:2139-2143), the DBR word (:581-589 vs
  :3910-3911), UAR type and mapping (:2356-2357, :1337-1392), who rings (`use_async_postsend`
  :3815, progress hook :5308), and the prod_idx indirection (:2109-2130). CQ creation and
  placement (:5268-5274), the CQ the device polls, every QPC/CQC field and the doorbell ctrl word
  (pi<<8, qpn<<8, opcode 0, ds 0 in both, ibgda_device.cuh:1554-1555 vs ibgda.cpp:586-587) are
  the same in both handlers. The proxy never touches the CQ. That leaves the DBR word, the UAR,
  and who issues the stores.
- **12:08-12:10, b1 (measured).** nvshmem preset: no error CQE in F1/F1post/F2b/F3. doca: all
  present. nvshmem with only `dbr_word=1`: all present. **H1 supported.** A new observation: F3 in
  the nvshmem preset reaches ERR at 3.8 s rather than staying RTS as in Q2.
- **12:15, H16: Q2's "RTS for 16 s" is a watch artifact.** From source: the watch's `lock_guard`
  spans `sleep_for`, and the proxy takes the same lock (ibgda.cpp:542). The Q2 logs agree: qptl F3 `hw = sw = 23`
  with ready_head 25; `ab/*_tcc1_*` F1/F3 `hw = sw = 15` with ready_head 17 in all six runs; F1's
  2ERR after the watch window in 3/3.
- **12:17-12:21, b2/b3 (measured).** Bisection of every other difference: none flips it (H2-H15
  rejected). Reverse: doca + word 0 loses the CQEs. GPU-handler emulation (word 1 + BF UAR) keeps
  them. Replicates. q counters: the fault is detected but `req_cqe_error` = 0. **H1 confirmed on
  CPU.** In ERR, `sw_sq_wqebb_counter` = word 1 of the record.
- **12:28-12:34, nv1 (measured, NVSHMEM on GPUs).** Knob off: no CQE (F2b 2/2, F1 1/1, F3 2/2,
  scan errs 0), DBR word1 = 0, QP ERR with sw_sq 0. Knob on: REM_ACCESS / WR_FLUSH 0xf5 /
  RETRY_EXC reach the device (5/5). **H1 confirmed in NVSHMEM.** With the fixed watch, F3's QP
  goes to ERR (2/2). The old watch (100 ms, no delay) starves NVSHMEM init entirely.
- **12:34-12:36, b4 (measured).** doca + word 0 on F1/F1post/F2b/F3 replicates: 0/5 vs doca 4/4.
- **12:39-12:42, nv2 (measured).** The Q2 qptl run reproduced with the lock-holding watch
  (RTS, hw = sw = 23, ready_head 25, nothing transmitted until the watch ends). The same watch
  with the lock released: put rung, retransmitted, ERR at 5.3 s, no CQE. No watch: same
  retransmission; knob on gives RETRY_EXC at 3.63 s. **H16 confirmed; question 2 answered.**

- **15:02-15:27, 3-way comparison under the permanent PeerMappingOverride (measured).** A (GPU
  handler) = C (CPU proxy + knob): an error CQE in 32/32 fault trials (the root cause in the 24
  timeout-mode ones). B (stock CPU proxy): 0/12. Blocking `nvshmem_quiet()` returns success after a
  fault on both A and C (8/8 iterations counted, 4 or 6 delivered) and wakes on the trailing
  0xf9 flush. The GPU-handler detection path is described from source under "How the
  GPU-handler path detects an error today".

## Corrections to earlier write-ups

- `../nvshmem/README.md` "F3 ... rain's QP stays state = 3 (RTS) for all 54 query-only samples
  over 16 s" and RESULTS.md "F3 ... no error CQE, QP stays RTS": the watched run had a starved
  proxy, so the failing put was never sent. Without that artifact F3's requester QP goes to ERR
  after ~3.6 s of retries. Still no CQE, for question 1's reason.
- `../nvshmem/README.md` "The earlier 'state = 3 always' came from the watch thread racing init":
  the watch did not race init; it blocked the proxy and the fault thread.
- `../nvshmem/results/20260923/ab/F1_*` and `ab/F3_*` (tcc1): the failing put was never rung, and
  F1's 2ERR fired only after the 16 s watch window. These cells did not test F1/F3. The F2b cells
  and the unwatched matrix runs are unaffected. The cc=0 init hang in the same A/B ran with the
  watch holding the lock from 100 ms, and the watch alone can stall init (nv1 `hold_t1`), so that
  result is not reliable either (not re-run).
- The collapsed CQ was already rejected by `../gin_q4/`. This work also rejects the CQ in GPU
  memory (the CPU reproduction keeps every queue in host memory and shows the same absence).

## Limitations

- The NIC-internal step (the producer counter taken from the doorbell record at the error
  transition, completions limited to [consumer, producer)) is inferred from QUERY_QP's
  `sw_sq_wqebb_counter`, the q counters and the single-field flip. The PRM text was not consulted.
- CPU bisection cells other than `dbr_word` have n = 1. The effect is all-or-nothing (0/35 vs
  21/21 overall).
- NVSHMEM cells have n = 1-3. F1 was run once per knob value.
- DCI endpoints share the proxy bug (`ibgda_dci_progress`). Their `dbr_offset` is a byte
  offset (8 per DCI) that is multiplied by 4, so the DCIs after the first also write into other
  DCIs' records [source, not measured]. The knob fixes both paths.
- The knob fixes error-CQE delivery only. `nvshmem_finalize` still hangs after a QP error, and
  the blocking `nvshmem_quiet` still ignores an error CQE (NDEBUG assert).
- One node pair, one firmware (20.43.4100), RoCE only.

## Files

| path | what |
|---|---|
| `nrc_devx.c`, `nrc_prm.h`, `Makefile` | CPU reproduction: DEVX CQ/QP from a preset; requester/target |
| `PRESETS.md` | every field of both presets with source line references |
| `nvshmem_nrc_proxy_sq_dbr.diff` | NVSHMEM knob + watch fix, layered on `../nvshmem/nvshmem_ibgda_fault_inject.diff` (verified: applies cleanly on 7bb2e99c after the base diff and reproduces the built source) |
| `scripts/run_one.sh`, `batch.sh`, `spec_b1..b4.txt` | one CPU trial / a batch from a spec (run inside cluster_run.sh) |
| `scripts/run_nvshmem_trial.sh`, `nvshmem_batch.sh`, `spec_nv1.txt`, `spec_nv2.txt` | NVSHMEM trials with the knob, the watch (optionally lock-holding) and rain port counters |
| `scripts/summarize.py` | SUMMARY lines -> `all_trials.csv` / `all_trials.md`; NVSHMEM KV lines -> `nvshmem_trials.csv` |
| `results/20260924/b1..b4/` | CPU trials: `*.req.log` (EV lines with every CQE write and QP transition, and SUMMARY), `*.tgt.log`, `*.timeline.csv` (100 ms samples incl. DBR words and port counters), `summary.txt` |
| `results/20260924/nv1, nv2/` | NVSHMEM trials: `*.pe0.log` (ITER/SCAN/watch/DBR lines), `*.pe1.log`, `*.cnt` (rain port counters), `nvshmem.txt` |

## Reproduce

```
make                        # rain; sunny: copy nrc_devx.c nrc_prm.h Makefile to ~/gi-bundle/nrc && make
CR=../common/cluster_run.sh
$CR -t nrc-b1 -- bash scripts/batch.sh scripts/spec_b1.txt results/<date>/b1     # also spec_b2..b4
python3 scripts/summarize.py results/<date> > results/<date>/all_trials.md
# NVSHMEM: 7bb2e99c + ../nvshmem/nvshmem_ibgda_fault_inject.diff + nvshmem_nrc_proxy_sq_dbr.diff,
# configured as in ../nvshmem/README.md; `make nvshmem_transport_ibgda` is enough. Deploy
# ~/gi-bundle/nvshmem_nrc/lib = ~/gi-bundle/nvshmem/lib + that plugin, on both nodes.
$CR -t nrc-nv1 -- bash scripts/nvshmem_batch.sh scripts/spec_nv1.txt results/<date>/nv1   # also spec_nv2
# 3-way (PeerMappingOverride=1 on both nodes): one hold per config
$CR -t nrc-abcA -- bash scripts/nvshmem_batch.sh scripts/spec_abc_A.txt results/<date>_abc/A    # B, C likewise
python3 scripts/abc_table.py results/<date>_abc > results/<date>_abc/abc_table.md
```
