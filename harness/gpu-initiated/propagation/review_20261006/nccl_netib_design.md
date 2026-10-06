# Review: NCCL net_ib CPU-proxy path, transparent-recovery probe, address flap

Read-only review, 2026-10-06. Nothing in the repo was modified and no cluster command was run.
The Stage 2 and perf log archives were extracted to `scratchpad/review/x/` and recounted with
`scratchpad/review/recount_nccl.py` (referred to below as **[RC]**).

Path abbreviations:
- **S1L** = `~/rdma-error/harness/nccl-integration/logs/run_20260923/`. Verdicts come from `summary.log`, written by `logs/autorun_recovery_test.sh` `verdict()`.
- **S2R** = `~/rdma-error/harness/nccl-integration/stage2/results/20260925/<campaign>/`. Each holds `results.csv` (from `stage2/run_tests.py` `classify()`), `logs.tar.gz` (thinned by `perf/thin_logs.py`, all recovery and error lines kept) and `hw_counters_{before,after}.txt`.
- **PRF** = `~/rdma-error/harness/nccl-integration/perf/results/20260925/`, summarised by `perf/summarize.py`.
- **PRB** = `~/rdma-error/harness/gpu-initiated/transparent_probe/results/run{1,2}/*.req.log`.
- **TRD** = `~/rdma-error/harness/gpu-initiated/TRANSPARENT_RECOVERY_DESIGN.md`.

Variants:
- **STOCK** = NCCL 2.23.4. This is either the stock library (md5 `1c15db8e`, T10/T12 controls only) or the patched library with the recovery flag off (all other controls).
- **S1** = Stage 1 patch, flag on (`net_ib_fault_recovery.diff`).
- **S2** = Stage 2 patch, flag on. Builds: `f7f45278` (A, B, smoke3), `3b0b760d` (C2, perf), `78f96f38` (A2, A3, C4–C7, D2, D2ctl, T10old, T10b_old), `7b0d0122` (A4, T10new, T10b_new, T12c_rst) and `a037de42` (final: A5, T12b_new2, T12c_new, T12d_*).
- **PROBE** = `transparent_probe` (CPU DEVX raw verbs, no NCCL).

Test drivers: custom `nccl_ar2.cu` (S1) and `perf/nccl_ct.cu` (S2, perf). nccl-tests was not used. Every iteration's whole rbuf is poisoned and then checked bit-exactly on both ranks. L3 is read through `ncclCommGetAsyncError` polling or through the next `ncclAllReduce` return.

## 1. Observed cells (variant, fault, layer)

Fault labels:
- F1s / F1r: local ERR of the send or recv QP, from the inject hook.
- F3: the peer's recv QP is put silently into ERR while the peer process stays alive (the `INJECT_RECV_SILENT` hook).
- F4: SIGKILL of the peer.
- FLAP: sunny's secondary RoCE address is removed for 0.5, 6 or 15 s and then re-added (`stage2/gid_blackhole.sh`).
- OOB: the job's TCP connections on the management network are blackholed for 12 s with iptables.
- MUTE: the peer never answers the recovery handshake.

All dates are 2026-09-25 unless marked otherwise.

| # | variant | fault | layer | observation | N, date | raw source → script | tag |
|---|---|---|---|---|---|---|---|
| 1 | all | F0 | L3 | every iteration bit-exact, no recovery lines | S1 base 60/60 (09-23); S2 T0s 12, T0d 23 runs PASS | S1L/summary.log; S2R B,A3,A4,A5,smoke3/results.csv → [RC] | measured |
| 2 | S1/S2 | F0 | L3 (cost) | flag on vs stock: S1 −0.2…+2.7 %, S2 −0.2…+0.7 %; flag off within ±0.6 % | 3 runs/cell | PRF/overhead_stage{1,2}/*.csv → summarize.py | measured |
| 3 | all | F1s | L1 | first error CQE is WR_FLUSH 5/0xf5 on the faulted send QP only. S1 batch had errCQEs=1. Error-CQE opcode/len fields are garbage (`opcode=32720 len=32720`, `opcode=1 len=32639`) | every F1 run | S1L/inject_r0.log; S2R T12d_flagoff/T12d_0_r0.log | measured |
| 4 | STOCK | F1s | L3/L4 | `ncclRemoteError` ("remote process exited or there was a network error") 0.055–0.242 ms after the inject. Once it came as the synchronous return of the next `ncclAllReduce` (rc 2, "Attempt to use communicator before…"). The **peer rank never surfaced** an error in 3/3 runs; the runner killed it about 20 s later | 3 | S2R T12d_flagoff/logs → [RC] | measured |
| 5 | S1 | F1s, single cfg | L2/L3 | bilateral reset plus one replayed WRITE_WITH_IMM; L3 sees nothing; 60/60 exact; symmetric 2/2 recovered | 1+1 (09-23); perf 5/5, 1.81 ms (1.78–2.21) | S1L/inject_*, symmetric_*; PRF/fault_stage1_single | measured |
| 6 | S1 | F1s, pipelined (default cfg, 16 MB) | L2/L3/L5 | responder NACK "not quiescent", both comms latched, both ranks rc 3, abort hang on both | 1 (09-23); perf 0/3 recovered, killed at 21.6 s | S1L/pipelined_*; PRF/fault_stage1_default | measured |
| 7 | S2 | F1s | L2/L3 | recovered with replay of groups R_done+1..fifoHead; L3 sees nothing. T1 30/30 (2.218 ms med), T2 30/30 (2.264), T5 50/50 recoveries in 10 runs, T6 20/20, T1b 10/10. Regressions on A2/A3 (78f96f38), A4 (7b0d0122) and A5 (final, N=3 each). **Executed-but-unacked groups = 0 in every F1 recovery** | see N | S2R */results.csv + logs → [RC] | measured |
| 8 | S2 | F1r | L1/L2 | R sees 5/0xf5 through its CQE. **S has no CQE** and learns through a NOTIFY record on the OOB socket that carries R's fingerprint ("incident via notify: status=5 vendor_err=0xf5"). T3 30/30, T3s 10/10, plus A2/A4/A5 | 30+10+10+5+3 | S2R A,B,A2,A4,A5 | measured |
| 9 | S2 | F1r+MUTE | L2/L3/L5 | S fails at the handshake deadline (≈35 s by default; 7 s with PATH_WAIT=2000 in C2), sends FAIL, and R latches. Both ranks get `ncclRemoteError`, then abort hang | 5 (C2) + 5 (A4) + 3 (A5) | S2R C2,A4,A5 | measured |
| 10 | S2 final | F1s after OOB loss (T12d) | L2/L3 | refused as "OOB lost". The faulted rank surfaces 0.057–0.065 ms after the inject; **the peer never surfaces** (killed by the runner) | 3 | S2R T12d_new → [RC] | measured |
| 11 | S2 | F3 | L1 at S | RETRY_EXC 12/0x81 3.558 s after the silent ERR **only if S had data in flight** (1/3, 64 MB bcast); that run recovered in 1.935 ms. Otherwise there was **no CQE at S** and it hung until the 90 s runner timeout (B 5/5 all-reduce, C6 2/3). C5: the hook never fired, 10/10 | 5+3+10 | S2R B,C5,C6 | measured |
| 12 | S2 | F3 (T4ar) | L3 | both ranks fail at the 120 s WAITREQ bound (wall 141.6 s incl. the 20 s abort watchdog) | 1 | S2R C4 | measured |
| 13 | STOCK | F4, survivor sends (S1 driver sleeps 200 ms) | L1/L2 | RETRY_EXC 12/0x81 on the recv comm (CTS write, logged "(Recv)", opcode 129), then 5 flush CQEs (0xf9 ×4, 0xf4 ×1). Stock net_ib prints all of them | 1 (09-23) | S1L/prockill_off_r0.log | measured |
| 14 | STOCK | F4 | L1 timing | about 56–58 s after the kill at the default IB timeout 20. This is inferred from `summary.log` minute stamps (kill 13:13:58, verdict 13:15:16, minus the 20 s watchdog); the logs have no per-line timestamps | 1 | S1L/summary.log | inferred |
| 15 | STOCK | F4, survivor waiting to receive (back-to-back) | L0–L4 | **no CQE, no WARN, no counter change**; hung until the runner killed it at 60 s | 3 (C7) | S2R C7 results.csv, logs, hw_counters | measured |
| 16 | S1 | F4 | L2 | RETRY_EXC classified, liveness FIN, "0x81 sub-cause proc_kill", declined (recv comm never initiates), then `ncclRemoteError` and abort hang | 1 (09-23) | S1L/prockill_r0.log | measured |
| 17 | S2 | F4 (T8) | side channel → L3 | FIN rule: the survivor fails **50.09–50.24 ms** after the peer's last iteration line (runner clock; this is the 50 ms grace); no CQE needed; then abort hang | C5 10, A4 5, A5 3 | S2R logs → [RC] | measured |
| 18 | all | FLAP | L4 (async event) | NCCL's async thread logs `"unknown event type (18)"` 4× per run on sunny, at the cut and again at the re-add (0.508–0.519 s apart for 0.5 s cuts). Neither stock nor the patch uses it. Seen in **29/29** flap runs. Type 18 = `IBV_EVENT_GID_CHANGE` | D2 15, D2ctl 6, A4 5, A5 3 | S2R logs → [RC]; enum value from libibverbs | measured (event); inferred (enum name) |
| 19 | STOCK | FLAP 0.5 / 6 s | L1/L3 | RETRY_EXC 12/0x81 on **both** nodes 3.01–3.18 s after the re-add (0.5 s cut), i.e. 3.50–3.72 s after the cut start whatever the cut length (0.5, 6 and 15 s cuts), followed by 0xf9/0xf4 flushes. `ncclRemoteError` at iteration 443–452 on both ranks; abort hang | 3+3 (D2ctl, flag-off 78f96f38) | S2R D2ctl → [RC] | measured |
| 20 | STOCK | FLAP 0.5 s, IB timeout 20 | L3 | stall of about 56–60 s before RETRY_EXC; restart wall 68.28 s (baseline 8.45 s) | 3 | PRF/addrflap_stage2_default → summarize.py | measured |
| 21 | S2 | FLAP | L2/L3 | RETRY_EXC with "no evidence of death" leads to recovery. **"local GID moved from index 5→6 / 6→5" on sunny in 23/23 runs, 0 on rain.** T7a 5/5, T7b 5/5 (3.26 s, waits for the address), T7c 5/5 (12.27 s), A4 T7a 5/5, A5 T7a 3/3; 15000/15000 iterations exact. L3 sees one slow iteration (max 3596 ms) | 15 (D2) + 8 | S2R D2,A4,A5 → [RC] | measured |
| 22 | S2 | FLAP 0.5 s, IB timeout 20 | L3 | recovered 3/3; per-connection 2.46–4.78 ms; wall 67.96 s vs restart 68.28 s | 3 | PRF/addrflap_stage2_default + logs | measured |
| 23 | all | FLAP | L0 | `local_ack_timeout_err` rain +239 / sunny +216 over D2 (15 runs) and +90 / +84 over D2ctl (6 runs). `duplicate_request`, `out_of_sequence` and `packet_seq_err` stay 0 in every campaign | campaign-level only | S2R */hw_counters_* | measured |
| 24 | all | OOB | L0/L1 | no CQE; no port counter changes | T10*, T12* campaigns | S2R hw_counters | measured |
| 25 | STOCK | OOB | L3 | pass: T10 2/2, T10b 2/2, T12c 2/2 | 6 | S2R T10stock,T10b_stock,T12c_stock | measured |
| 26 | S2 78f96f38 | OOB two-way, 1 GiB | L2/L3 | a **healthy job was killed** in 3/3 runs: "peer process gone" 4.29–4.59 s into the outage | 3 | S2R T10b_old → [RC] | measured (superseded) |
| 27 | S2 7b0d0122 | OOB one-way | L2/L3 | a healthy job was killed in 3/3 runs (the live peer received an RST) | 3 | S2R T12c_rst | measured (superseded) |
| 28 | S2 final | OOB | L4/L3 | "OOB socket lost (Connection timed out / reset by peer) … recovery disabled" logged 4.17–4.57 s in; job passes: T12b 3/3, T12c 5/5. T12 (16 MB) was run only on 78f96f38/7b0d0122 (3/3, 5/5) | 8 | S2R T12b_new2,T12c_new,T10old,T10new | measured |
| 29 | all | any surfaced error | L5 | `ncclCommAbort` **never returned**: 83 logs with ABORT-HANG (S1 4, S2 73, perf 6), 0 with "ncclCommAbort returned" | 83 | S1L, S2R, PRF logs → [RC] | measured |
| 30 | all | any surfaced error | L3 | only one result code and string is ever seen: `ncclRemoteError` (72 async + 1 sync) | 73 | S2R logs → [RC] | measured |
| 31 | PROBE | responder ERR / RTS | L0 (QPC) | `next_rcv_psn` and `rmsn` equal the memory prefix in **28/28** points: ERR 10, RTS 18. Prefixes were 0–3 (run1, cut short by a malformed WQE, err 0x02), 256 (13 points) and 234 (1 point, the **only mid-burst point**). QUERY_QP took 60–84 µs | 14+14 | PRB → [RC] | measured |
| 32 | PROBE | req_err | L0 (requester QPC) | the requester's own `next_send_psn` equalled the responder's `next_rcv_psn` in **20/20** trials. This is in the raw logs only, not in the docs | 20 | PRB r[ab]_s*.req.log | measured |
| 33 | PROBE | req_err ra_s4 | recovery | requester completions 223 vs responder executed 234. Mode A replay of 22 from PSN 0x36f; 3 duplicate packets absorbed; 205/205 writes, 51/51 counters = 1 | 1 | PRB run2/ra_s4.req.log | measured |
| 34 | PROBE | dup rewind | L1 | rewinds of 4 and 16 absorbed; 64 and 200 end in RETRY_EXC (syndrome 0x15); no counter > 1 | 1 per depth | PRB run2/dup_d*.req.log | measured |
| 35 | PROBE | wqeidx | L1 | CQE `wqe_counter` 0–3 for index fields 1000–1003; tested on a fresh QP only | 1 | PRB run2/wqeidx.req.log | measured |
| 36 | — | F2 (REM_ACCESS) on NCCL | all | never run. Expected path: the peer's async ACCESS_ERR → `fatalErrorCount` → permanent comm failure | 0 | `DESIGN_recovery.md` §7, `stage2/DESIGN_stage2.md` §3 | source-only |

The address flap on other stacks is documented only; I did not recount it:
- NVSHMEM T1: 18/18 transparent for 0.5/6/15/25 s cuts; v2.2 failed 6/6; a no-GID-re-lookup control declined 3/3; the GID index moved in 72/72 cuts (`gpu-initiated/nvshmem_ft/TRANSPARENT_T1.md` §Address flap).
- GIN TS2: S1 declined 6/6 ("commit failed", stale index); S2 transparent 18/18 up to 20 s; 30 s declined cleanly 3/3; the index alternated 5↔6 in 21/21 cuts (`gpu-initiated/gin_recovery/TRANSPARENT_S2.md` §D).
- The CPU verbs harness only auto-detects the GID index (`harness/config.sh` l.23–25; rain moved 3→4 by 09-23, cause not recorded).
- The old cluster saw link down/up move the index 3→2 (`docs/theory/08_appendix_code_evidence.md` A.2).

## 2. Distinguishable classes per layer

Fault set: F0, F1s, F1r, F3 (peer QP ERR, alive; split into "S has a WR in flight" and "S idle"), F4 (likewise split by whether the survivor transmits), FLAP, OOB. F2 was not run.

| layer | STOCK | S2 (final) |
|---|---|---|
| L0 port counters (campaign-level) | {F0, OOB, F4-idle} ∣ {F1: cqe_error/flush counters, no ack timeout} ∣ {FLAP, F3/F4 with traffic: `local_ack_timeout_err`} (rows 15, 23, 24) | same; the hardware does not change |
| L1 first error CQE | {F1s, F1r → 5/0xf5, faulted side only} ∣ {F4-with-WR, F3-with-WR, FLAP → 12/0x81, indistinguishable} ∣ {F0, OOB, F4-idle, F3-idle → nothing} | same |
| L2 consumer | same as L1. Stock prints every error CQE with status and vendor_err, but the opcode and direction are garbage | {F1} ∣ {FLAP, F3: RETRY_EXC with no evidence of death → recover} ∣ {F4: FIN, including F4-idle through the FIN rule} ∣ {OOB: "OOB lost", logged only} ∣ {MUTE: deadline}. FLAP vs F3 can be told apart only **after the fact**, by the "local GID moved" line on the flapped node during bring-up. F1r is visible at S only through NOTIFY |
| L3 API | {F0} ∣ {every surfaced error → one `ncclRemoteError`} ∣ {silent hang: F4-idle, F3-idle, and the peer side of a one-sided F1} | {F0 ∪ recovered F1/F3-with-WR/FLAP → ncclSuccess, sometimes one slow iteration} ∣ {F4, MUTE, F1-after-OOB, unrecoverable → `ncclRemoteError`} ∣ {F3-idle → hang up to WAITREQ 120 s, then error}. **The patch merges more classes at L3**: a recovered fault is invisible |
| L4 host | WARN lines keep status/vendor_err per CQE. The GID_CHANGE event (type 18) is logged as "unknown". From the error-CQE WARN line to the API error line: 24–73 µs (T12d_flagoff ×3, D2ctl T7a_0) | WARN lines keep class, liveness, R_done, number replayed, GID move and per-phase timing. This is the only place where recovered-fault information survives |
| L5 teardown | abort hangs after every error (row 29) | same; the patch does not change this |

## 3. Recovery semantics

**S1.**
- Replays exactly one WRITE_WITH_IMM and re-posts one receive.
- It is allowed only when `nqps=ndevs=nreqs=1`, there is a single request in flight on both sides, the first error is WR_FLUSH and liveness shows no FIN or RST.
- Every observed fault was injected *before* the send was posted. So the executed prefix was trivially empty, and the "R data landed before reset, drop and replay" branch (`DESIGN_recovery.md` §4.3) was never exercised (inferred from the hook placement).

**S2.**
- Both sides drain their QP with an ERR plus marker WR, as `ib_drain_qp` does.
- R computes `R_done` from its consumed receive CQEs as "smallest pending idx − 1". This relies on invariant I3, in-order RC execution.
- S completes groups ≤ R_done without resending them and replays R_done+1..fifoHead in FIFO order. R re-posts its pending receives and rewrites the CTS entries after fifoHead.
- Both sides get fresh random PSNs, and the local GID is looked up again by value.
- There is no "signal delta", since the NCCL net has no signals. The executed prefix is a software count taken after the drain, not a QPC read.

Evidence:
- **422 send-comm recoveries** are in the S2 campaign logs, plus 22 in perf. There are 0 MISMATCH and 0 per-iteration timeouts in any log ([RC]).
- **The duplicate-avoidance branch ran only 5 times**: "completed 1 group(s) R had" in D2 T7a ×2, T7b ×2 and A4 T7a ×1, all on RETRY_EXC (FLAP). Every F1 recovery had 0 executed-but-unacked groups.
- In-flight depth at recovery: unexecuted groups 0–4 and receives posted ahead 1–4. The 256-entry capacity in the design was never approached.
- Every recovery finished in round 1. The `MAX_ROUNDS` path was never exercised.
- Stale-packet counters were 0 on both NICs in all campaigns. `implied_nak_seq_err` went 0→2 on rain between B and C2 and is unattributed.
- **There is no negative control for S2 reconciliation**, i.e. no knob that replays from a wrong `R_done`. That a duplicate WRITE_WITH_IMM would be caught by the bit-exact check (it would consume the next receive WQE) is inferred. Contrast NVSHMEM T1, whose `prefix` knob produced ADD-twice failures in 14/25 rounds (`nvshmem_ft/TRANSPARENT_T1.md` negative controls).

**What transparent_probe established about next_rcv_psn.**
- The responder's `next_rcv_psn` and `rmsn` equal the executed prefix in 28/28 points, both in ERR and in RTS.
- READs advance it by ceil(bytes/MTU): 46 READs gave psn0+627.
- Limits:
  - Only **one** point lands mid-burst (ra_s4, responder in RTS).
  - Every ERR point is at prefix 0–3 or 256, so the ERR transition was never placed mid-message.
  - Only one trial had a non-empty replay (Mode A, 22 operations), and there are 0 valid Mode B replays.
  - On this lossless direct link, the requester's own `next_send_psn` gave the same number in 20/20 trials. The probe shows that the responder read beats the requester's *completion count* (223 vs 234). It does not show that it beats the requester's QPC.
  - The duplicate window is ≥16 and <64 requests (n=1 per depth; tying it to `max_rd_atomic` is inferred).

## 4. Spot-checks (raw → README text)

| claim (file) | recount | match |
|---|---|---|
| T2 30/30, 2.26 ms (2.22–2.35) (`stage2/README.md`) | 30 RECOVERED, median 2.264 (2.220–2.346) (S2R A/results.csv) | yes |
| T7a/b/c 15/15 recovered; stock control 6/6 fail at iteration ~443 (`stage2/README.md`, root README) | D2 5/5/5 (60 connection recoveries); D2ctl 6 CLEAN_FAIL at ok = 443–452 | yes (the control is flag-off 78f96f38, not the stock binary) |
| RETRY_EXC 3.1 s after the address is back (`stage2/README.md` T7a) | 3.00–3.22 s, rain and sunny, 0.5 s cuts, D2/D2ctl/A4/A5 (16 runs) | yes |
| T8 error 50.2 ms after the peer's last iteration (`stage2/README.md`) | C5 50.14–50.24, A4 50.09–50.20, A5 50.13–50.16 ms | yes (it is the 50 ms grace) |
| T12b old build killed 4.3–4.6 s in | 4.29–4.59 s | yes |
| Q1 28/28 (ERR 10, RTS 18) (TRD §11.1) | run1 14/14 (ERR 5), run2 14/14 (ERR 5) | yes |
| perf: recovery +2 ms, restart +1.1 s (perf README) | baseline 1.442, recover 1.437, restart 2.537 s (single, S1); identical summarize.py output | yes |
| S1 table (base/inject/symmetric/pipelined/prockill) | `summary.log` and the rc files are identical to the README | yes |
| T12d stock-path error 0.05–2.18 ms after the fault (`stage2/README.md`) | 0.055 / 0.067 / 0.242 ms to the API error; 2.18 ms is inject→SUMMARY line in run 0 | **minor mismatch** |
| stale-packet counters 0, implied_nak 0→2 between B and C2 | confirmed | yes |

## 5. Invalidated or corrected results, overclaims, open QA

**Invalidated or corrected**

1. **Address flap reinterpretation.** It was designed as a packet-dropping blackhole: the plan expected a 0.2 s cut to be "masked by HW retransmission" (`DESIGN_stage2.md` §11 T7). It was corrected in QA round 1 (§13, "high (test validity)") and in §9 and README "What T7 does and does not show". The re-added address gets a new GID index, and the old QPs' source-GID index points at a cleared entry. So even a 0.5 s cut is permanent: RETRY_EXC comes about 3.5 s after the cut start whatever the cut length. Raw support:
   - 23/23 S2 runs log "local GID moved" on sunny.
   - RETRY_EXC comes 3.0–3.2 s after the re-add.
   - The feasibility test itself (0.3 s, 5→6) has **no raw output in the repo**; `gbh_feasibility.sh` wrote to an outdir that was not kept.
   - Stale text remains in the `gid_blackhole.sh` header ("Nothing changes the QPs' state; the NICs retransmit"), the `gbh_feasibility.sh` header ("short = masked"), `DESIGN_stage2.md` §10 ("re-adding it restores the path"), the `run_tests.py` `MASKED` verdict, and TRD §6.2/§10 ("path-flap → Mode A").
2. **Liveness rule history.**
   - `78f96f38` treated a keepalive timeout as death and killed healthy jobs (T12b 0/3).
   - `7b0d0122` treated an RST as death (T12c 0/3).
   - `a037de42` treats only FIN as death.
3. **S1 historical logs (09-17) are invalid** (`logs/historical/HISTORICAL.md`). Its last paragraph and `DESIGN_recovery.md` §9 ("Not run on 2-node GPUs yet") are stale; the patch ran on 09-23.
4. **Probe run1 is invalid for exactly-once** because of `ds=0` inline WQEs and no CQ drain. Its 14 Q1 points remain valid.
5. **C5 T8 recorded `FAIL(rc 7/255)`.** It was reclassified as a clean failure only afterwards (stated in the README).
6. **Stale build labels.**
   - `perf/README.md` calls `78f96f38` "the final build".
   - `stage2/README.md` labels A2/A3 rows (`78f96f38`) "final build".
   - The true final is `a037de42`, where each case has N=3 (A5).
7. **`DESIGN_recovery.md` §10 expects RETRY_EXC about 34 s after prockill** (the nominal IB formula). The S1 timestamps imply about 56–58 s (row 14, inferred).

**README claims stronger than the data**

- Root `README.md`: "요청이 여러 개 비행 중이어도 … 30/30". At most 4 groups and 4 receives were in flight; the 30/30 was on pre-final `f7f45278`; the final build has N=3.
- Root `README.md`: "주소 재구성 fault 15/15 (원본은 6/6 실패)". The control was the patched library with the flag off, at 0.5/6 s only; there was no 15 s control. The final build re-ran only T7a ×3.
- Root `README.md`: "제자리 복구 +2 ms, 재시작 +1.1 s". This holds only for injected faults detected in µs. For the address flap at the default IB timeout, recover 67.96 s vs restart 68.28 s (`perf/README.md` says so; the root README omits it).
- Root `README.md`: "관리망 장애를 … 죽이지 않는다". Final build N=3 and N=5. The cost is that OOB loss permanently disables recovery for the comm (T12d), and a dead peer that sends RST, or a host that vanishes, is not detected while the survivor waits to receive (stock-equivalent hang).
- Root `README.md` 한계: "GPU 스택의 실제 경로 fault는 시험하지 않았다" and "GPU 투명 복구는 비행 중 op 1개까지". Both are contradicted by the *untracked* `TRANSPARENT_T1.md` and `TRANSPARENT_S2.md` (flap on both GPU stacks; multi-op TS2). The README lags the working tree.
- TRD §6.2: "[probe] validates Mode A exactly-once with hundreds of ops in flight". This rests on one trial with a 22-operation replay. `gpu-initiated/RESULTS.md` l.35 states "next_rcv_psn = executed prefix" with no qualifier.
- `docs/theory/07_layer_constraints_nccl.md` §7.4: "NCCL은 watchdog timeout까지 hang". Measured: NCCL 2.23 surfaces `ncclRemoteError` 24–73 µs after it logs an error CQE. It hangs only when no CQE arrives (row 15) and in `ncclCommAbort` (row 29). Its "통합 실험은 GPU 확보 후로 미뤄져" is stale.
- `docs/theory/08` A.3 says "ip link set down: RDMA 무효" on the old cluster. This sits uneasily with A.2 in the same file (link down/up moves the GID index) and with this testbed's finding that removing an address kills existing QPs. It is untested here, because a real link down is not allowed.

**Open QA**

1. **The management-network-as-death rule survives on the GPU side.**
   - GIN TS2's `gdakiTsAlive()` treats "FIN or a TCP error = dead", with keepalive and `TCP_USER_TIMEOUT` set (`gin_recovery/gin_transparent_s2.diff` ≈l.3409–3477, untracked).
   - TRD §8 prescribes "ECONNRESET/EPIPE/ETIMEDOUT → dead" while citing stage2 §7, which says the opposite.
   - No OOB-outage test exists for GIN TS2. NVSHMEM T1 fixed this (review finding 3; `sock`/`sock1` 5/5).
   - Source-only.
2. **NCCL S2 never re-dials a lost OOB socket**, so recovery stays off for the comm's lifetime after any management-network blip of more than about 4.2 s (T12d). NVSHMEM T1 re-dials.
3. **The FIN rule's 50 ms grace is the F4 surfacing latency.** An RST from a dead peer (unread OOB data) and silent host death are both untested.
4. **`classify()` labels CLEAN_FAIL even when only one rank surfaced the error** and the runner killed the other (T12d 3/3 in both variants). "Clean" ≠ both ranks notified.
5. **The GID_CHANGE event arrives about 3.5 s before RETRY_EXC and is ignored.** It could identify FLAP at L4 (row 18).
6. **TRD Mode A cannot handle a flap on the responder's node.** The responder's own source-GID index is stale (its ACKs cannot leave), so its QP must be re-driven too (inferred). TRD §6.2/§10 route path flaps to Mode A.
7. **T7b/T7c recovery time includes RTR retry backoff** (20 ms doubling to 1 s, "after 9 bring-up tries"), adding up to about 0.9 s beyond the address return (inferred from the log lines and DESIGN §14).
8. **S1 used the RoCE netdev for the OOB socket** (`ens4f1np1`); S2 used the management network (`eno1`). Liveness evidence is not comparable across the two.

## 6. Gaps that matter for a cross-layer table

- **L0 per trial is missing.** There are no per-QP state or QUERY_QP reads in any NCCL run. Counters are per campaign, and B and C6 lack an "after" snapshot. The mixed campaigns (A4, A5, C5) cannot attribute counter deltas to a fault.
- **Faults that were never run on the NCCL path.**
  - F2 (REM_ACCESS) and REM_INV_REQ, source-only.
  - A real peer-QP error other than the silent hook (F3 is test-hook only).
  - A real link flap (excluded by the 2026-09-25 decision).
  - Rain-side address flap (only sunny's address was cut).
  - Faults with multi-QP/NIC (`nqps>1`), which are declined by design and have no runtime evidence.
- **Stock-binary controls exist only for OOB.** The F4/FLAP/F1 controls are the patched library with the flag off. There are no stock controls at all for F1r and F3.
- **Peer-side views are mostly missing.** In F4 the peer is dead; in T12d and F1-stock the peer was killed by the runner before it surfaced. So "does the far side learn, and when" is unmeasured except where S2 sends FAIL or NOTIFY.
- **Timing comes from the runner's clock.** Line-arrival timestamps run over ssh for sunny; there are no NIC timestamps; the S1 logs have no timestamps at all. L1→L3 deltas are reliable only within one node.
- **Each layer has a single surface.** L3 has one code, `ncclRemoteError`. L4 is free-text WARN. No structured async-error API carries the class, so any "kept at L4, lost at L3" cell rests on log parsing.
- **Recovery depth was at most 4 in flight and always one round.** The executed-but-unacked case came up 5 times, all on FLAP.
- **The probe is CPU DEVX only**, on one link, with one mid-burst point. Its next_rcv_psn result is not yet shown to differ from the requester's QPC.
