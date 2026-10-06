# gin_recovery: 상세 기록

아래는 예전 README 본문을 그대로 옮긴 것이다(영어). 요약은 [README.md](README.md)에 있다.

**2026-10-06 리뷰 정정**

- "Measured vs inferred"와 "Limitations"는 GPU doorbell을 시험하지 않았다(CPU proxy만)고 적고 있다.
  같은 파일의 "GPU doorbell" 절에서 v2로 쟀으므로 그 문장들은 낡았다.
- F4 "blocking" 칸은 사실상 timeout 칸이다. 이 드라이버는 F4 확인에 늘 timeout 대기를 썼다.
  진짜 blocking F4는 S1(`TRANSPARENT_S1.md`)에서만 쟀다.
- `results/20260924/`(v1)의 CPU doorbell은 로그가 아니라 시각과 v1의 모드 검사로 추정한 것이다.
- 09-25 06:45부터 rain `mlx5_1`의 펌웨어 명령 슬롯 하나가 샜다(`TRANSPARENT_S1.md`). 이 폴더의 N30 재측정은
  02:11~03:29에 끝나 영향 밖이다. 같은 날 NVSHMEM과 GIN Q4의 N30(07:04~09:34)은 샌 상태에서 돌았다.

Builds on `../gin_q4/` (device-side classification of the root-cause error CQE + host
mailbox). This adds recovery: a bilateral QP reset with fresh PSNs, a GPU-side state resync,
and an application-level replay that reconciles GIN's non-idempotent signal. The safety
argument is in `RECOVERY_DESIGN.md`. Same cluster and conventions as Q4: rank 0 = rain (put
initiator, Quadro RTX 5000 sm_75, mlx5_1), rank 1 = sunny (target, RTX A4000 sm_86, mlx5_0),
ConnectX-6 (VPI, MT28908) RoCE, GDAKI in its CPU-doorbell fallback (ring CQ in GPU memory),
`NCCL_IB_TIMEOUT=14`, one 256 KiB put + signal ADD per iteration, 15 ms gap.

**Step S1: app-transparent recovery (2026-09-25, `TRANSPARENT_S1.md`, `gin_transparent_s1.diff`,
`NCCL_GIN_FAULT_TRANSPARENT=1`).** The recovery below needs the application to end its kernel, run a
handshake and relaunch. S1 moves all of it into NCCL, so an unmodified put + signal + flush program
survives a local or peer QP error with no error and no relaunch:
- 95/95 recoverable runs transparent; the "WRITE executed, ADD not" boundary 30/30; a fault inside an
  in-flight op 150/150.
- Unrecoverable faults are declined and surface (40/40).
- If the helper stalls or dies before its commit point, the flush returns an error when the device hold
  expires (4.0 s with the 4 s test hold); after the commit point, at 2 x hold (8.0 s measured). The
  watchdog only raises the async error. A blocking flush is bounded only by that hold (30 s by default,
  60 s when the give-up loses), never by anything the application passes.
- **Cost: the flag-on fast path is +60 % at 4 KiB (10.24 → 16.42 µs)**, +7 % at 256 KiB; flag off +1 %.
- Tested with one operation in flight and one posting thread only.

## TL;DR

- **Recoverable faults recover, with nothing lost or doubled** (measured on 2026-09-24: 64
  trials, 48 overhead runs, 4 negative controls, plus a confirmation batch):
  - F1 (local QP → ERR) and F3 (peer QP → ERR, peer alive) recovered in every trial, in both
    wait modes. That is 6 + 6 single-fault runs, plus 10 + 10 runs with **5 faults each**, one
    of which fires *inside* the previous recovery's commit so that it hits the replay.
  - The receiver checked every iteration's data bit-exact. Its signal equalled the expected
    count exactly after every iteration, and at the end (base + iterations): 32/32 runs that
    recovered from injected faults, and 6/6 forced d = 0 runs.
  - There were 130 recovery rounds in the main matrix. A round is one completed Prepare →
    handshake → Commit → replay cycle; all counts here were recounted from the raw logs
    (`scripts/recount.py` → `results/RECOUNT.md`). 112 rounds followed a fault: 92 recovered,
    and 20 were hit by a second fault during the replay, so a further round followed. In all
    112 the receiver read V = expected − 1 (d = 1: put and ADD replayed). The d = 0 branch (the
    ADD had landed before the error) was exercised by 18 forced recoveries, which replayed
    nothing and kept the count exact.
- **Unrecoverable faults decline cleanly.**
  - F2 (REM_ACCESS 10/0x88) is declined 3.9–4.1 ms after the bad put. Both ranks exit with
    "declined" and `ncclCommAbort` returns on both.
  - F4 (SIGKILL of the peer) gives RETRY_EXC 12/0x81 about 3.7 s after the kill. The OOB socket
    shows FIN, so the initiator declines without a handshake, and abort returns.
- **Time.** From the moment the initiator's kernel returns `ncclRemoteError` to the replayed
  operation completing takes **8.0–8.2 ms** (median, every cell):
  - Prepare: 0.2 ms, or 1.1 ms when healthy QPs must first be moved to ERR.
  - Handshake: 3.5–4.6 ms. This includes the responder's own Prepare and Commit.
  - Commit: 3.1 ms. Four QPs × (2RST + INIT/RTR/RTS), about 0.75 ms per QP, all devx firmware
    commands.
  - Replay: 0.26–0.28 ms.
  - Fault to recovered is therefore set by detection: about 24 ms for F1 (the fault lands
    between iterations and is seen by the next put) and 3.65–3.74 s for F3 (RETRY_EXC at IB
    timeout 14).
- **No-fault overhead: none measurable.** The device code is the same with the flag on or off.
  Pooled means differ by at most 0.3 µs (0.8%), and the per-run p50/p99 ranges of flag-on and
  flag-off runs overlap (6 runs × 10k samples per cell). CPU use is 2.07 cores in both cases.
- **Negative controls confirm the resync design.** Replacing one step with a plausible
  alternative breaks recovery exactly as the design predicts:
  - With DOCA's own `cqe_rsvd` formula (not cumulative), the 2nd recovery's replay completed
    on the wire but the GPU polled a stale slot (`wqe_counter` 23 instead of 1) and timed out.
  - Without zeroing the proxy doorbell mailbox, the 1st replay was never doorbelled (the CQE
    slot still held its initial opcode 0xf).
- **GPU doorbells (since 13:53 the default here): see the "GPU doorbell" section.**
  - GDAKI now rings doorbells from the GPU: `GPU_SM_DB` on every QP, no proxy thread, one fewer
    CPU core.
  - The committed v1 declines in that mode. v2 (`gin_recovery_gpudb.diff`) resets the GPU-side
    doorbell state instead and recovers F1/F3 (×1 and ×5) with exact data and signals.
  - F2/F4 still decline cleanly, and the Q4 classifier is unchanged.
- **Three things the tests taught** (all fixed; details in design §11):
  - A kernel launched while another kernel spins must not need a local-memory resize, or it
    will not start until the spinner exits (in blocking mode: never).
  - The Q4 driver had a barrier race (poison after the ack).
  - "Fire right after the commit" usually misses the replay; firing *inside* the commit does not.

## What was built

| piece | what |
|---|---|
| `gin_recovery.diff` | NCCL patch (+~780 lines, 3 files), layered on `../gin/gin_fault_inject.diff` + `../gin_q4/gin_q4_classify.diff`, env-gated `NCCL_GIN_FAULT_RECOVERY=1` (default off) |
| `RECOVERY_DESIGN.md` | contract, policy, quiescence model, protocol, reset/resync inventory, safety argument, what the tests changed |
| `gin_rec.cu` | 2-rank driver (from `../gin_q4/gin_q4.cu`): typed OOB protocol, initiator recovery loop, responder REQ handling, re-arm, cancel, checks |
| `scripts/` | build, deploy, trial/matrix runners, confirmation batch, log → CSV, summary, diff regeneration |
| `results/20260924/` | all logs, `trials.csv`, `events.csv`, `summary.md`; `diag/` (cancel bug, negative controls), `confirm/` |

### Library side (`gin_recovery.diff`)

Host API, declared in the patched `nccl.h`:

```c
ncclResult_t ncclGinFaultQuery(ncclComm_t, int waitMs, ncclGinFaultInfo_t*);       // Q4 record: class, fp, recoverable
ncclResult_t ncclGinRecoverPrepare(ncclComm_t, int peer, ncclGinRecoverToken_t* local, ncclGinRecoverStats_t*);
ncclResult_t ncclGinRecoverCommit(ncclComm_t, int peer, const ncclGinRecoverToken_t* remote, ncclGinRecoverStats_t*);
ncclResult_t ncclGinRecoverAbort(ncclComm_t, int peer);
```

- **Prepare**, for every QP to `peer` in all GIN contexts of the user devComm:
  1. Pause the CPU-proxy doorbell thread for this context.
  2. Ring any pending doorbell.
  3. Snapshot the device QP struct and check quiescence: `sq_ready_index == sq_rsvd_index ==`
     proxy mailbox `==` rung index.
  4. Move the QP to ERR.
  5. Wait (bounded) for the CQE of the last posted WQE.
  6. Draw a fresh 24-bit send PSN and return the token (QPNs, peer QPNs, PSNs).
- **Commit**, per QP:
  1. `QP_2RST`.
  2. Zero the doorbell record, the proxy mailbox and the proxy counter.
  3. Write the device QP struct with the WQE indices at 0 and
     `cqe_rsvd += WQEs of the ending epoch`.
  4. Clear the GIN get tickets.
  5. Reconnect with the stored connect-time attributes and the exchanged PSNs:
     `gdakiConnectQp(..., rqPsn, sqPsn)`, the stock function with two defaulted parameters.

  Then it clears the Q4 sticky device error, the host flag and the GIN async result, and
  resumes the proxy.
- **Checks and declines.** Configuration (GDAKI, ring CQ, CPU proxy, no counters) and a token
  mismatch are checked before anything is touched. A failure midway leaves every QP of the peer
  in ERR.
- **Test hook.** `NCCL_GIN_FAULT_INJECT=local_err:a,b,...` fires shot k > 1 `b` ms after the
  recovery commit that followed shot k−1; a delay of `-1` fires it inside that commit, after RTS.
- **Diagnostic knob.** `NCCL_GIN_RECOVERY_DIAG` exists for the negative controls only.

### What the application must do (driver = reference)

1. **Stop producers.** On `ncclRemoteError` from a device wait, let the kernel return and wait
   for the stream. The peer must not run a kernel that *posts* on the same QPs until it has
   committed. A waiter spinning on its own signal may keep running.
2. **Policy.** Call `ncclGinFaultQuery`:
   - LOCAL_QP_ERR: recover.
   - RETRY_EXC: recover only if the OOB socket shows no FIN or RST.
   - Anything else: decline.
3. **Handshake over the management socket.**
   - Initiator: Prepare, then send REQ with its token.
   - Responder: Prepare; read its signal V on a side stream (its waiter may still spin);
     compute d = expected − V, which must be 0 or 1; Commit; reply ACK with its token and d.
   - Initiator: Commit; replay the put plus the ADD if d = 1, or nothing if d = 0; send DONE.
   - A failed replay starts a new round, which reads V again.
4. Kernels launched during a recovery must be **warmed at init** (local-memory sizing).
5. A responder whose device wait timed out re-arms it while the peer is alive (bounded).
6. On decline, the responder releases its own waiter with a signal to itself and tears down.

## Build, deploy, provenance

```
cd <nccl v2.32.3-1> && git apply ../gin/gin_fault_inject.diff && git apply ../gin_q4/gin_q4_classify.diff \
   && git apply gin_recovery.diff
make -j32 src.build CUDA_HOME=/usr/local/cuda-12.8 BUILDDIR=<scratch>/gi/gin_recovery/build \
     NVCC_GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86"
scripts/build_driver.sh      # gin_rec.cu -> <scratch>/gi/gin_recovery/gin_rec (-Wall -Wextra -Werror clean)
scripts/deploy.sh            # ~/gi-bundle/gin_recovery/ on rain and sunny, md5 + ldd checked (our libnccl)
```

- **Patch integrity.** The three diffs, applied in order to a pristine `git archive v2.32.3-1`,
  reproduce the build tree exactly (checked).
- **Separate build.** Source copy and build dir are separate from Q4's; `gi/gin_q4/build` is
  untouched.
- **Final build.** `libnccl.so.2.32.3` md5 `951001fe…` with driver `50501ffc…`. It was used for
  the negative controls, overhead reps 4–6 and `confirm/`.
- **Driver reproducibility.** nvcc builds are not byte-reproducible (two fresh builds differ),
  but a fresh build of `gin_rec.cu` has the same host `.text` and device SASS as the deployed
  `50501ffc…` (checked).
- **Batches 1–3** used an earlier build of the same source without the diagnostic knob, which
  defaults to off. The driver changed between batches:
  - Batch 1 (base, F1, F3, F1×5, F4): driver with the poison fix only.
  - Batch 2 (F3×5, cancel diagnostic): driver with the cancel phase markers.
  - Batch 3 (F2, D0, flag-off, overhead reps 1–3): the final driver.

  The `confirm/` batch repeats every cell on the final build (see below).

## Results

Run with `scripts/run_matrix.sh` inside `../common/cluster_run.sh`: 5 holds of 2–7 min each,
released in between. Each trial left 0 processes on either node. Tables are generated by
`scripts/summarize.py` (`results/20260924/summary.md`).

### Outcomes

| fault | wait | n | faults fired | recovery rounds (recovered / replay failed) | ops ok r0 | r1 data bit-exact | r1 signal exact | final `ncclCommGetAsyncError` | abort r0 / r1 |
|---|---|---|---|---|---|---|---|---|---|
| none | timeout / blocking | 3 / 3 | 0 | 0 | 120/120 all | 6/6 | 6/6 | no error | returned / returned |
| F1 | timeout / blocking | 3 / 3 | 1 | 1 / 0 each | 120/120 all | 6/6 | 6/6 | no error | returned / returned |
| F3 | timeout / blocking | 3 / 3 | 1 | 1 / 0 each | 120/120 all | 6/6 | 6/6 | no error | returned / returned |
| F1 ×5 | timeout / blocking | 5 / 5 | 5 each | 4 / 1 each | 160/160 all | 10/10 | 10/10 | no error | returned / returned |
| F3 ×5 | timeout / blocking | 5 / 5 | 5 each | 4 / 1 each | 200/200 all | 10/10 | 10/10 | no error | returned / returned |
| D0 (forced, no fault) | timeout / blocking | 3 / 3 | 0 | 3 / 0 each (d = 0) | 120/120 all | 6/6 | 6/6 | no error | returned / returned |
| F2 | timeout / blocking | 3 / 3 | - | declined (REM_ACCESS) | 0/120 | - | - | `ncclRemoteError` (stays surfaced) | returned / returned |
| F4 | timeout / blocking | 3 / 3 | - | declined (RETRY_EXC, peer dead) | 176–180/400 | - | - | `ncclRemoteError` | returned / (killed) |
| F1, F3, flag off | timeout / blocking | 2 each | 1 | none (Q4 behaviour) | 37/120 | - | - | `ncclRemoteError` | returned / returned |

**Why ×5 gives 4 recovered + 1 replay failed.** Shot 3 fires inside the commit of shot 2's
recovery, so shot 2's replay meets a QP in ERR: LOCAL_QP_ERR 5/0xf5 on F1, RETRY_EXC after
3.6 s on F3. The next round reads V again (still expected − 1) and replays again. Five faults
make five rounds but hit four operations.

**Flag-off rows.** These are the Q4 behaviour: the initiator exits with the classified error
(exit 8) at the fault. The receiver's outcome in those rows is this driver's peer-loss handling,
not NCCL's.

### Declined faults

| fault | wait | n | decision | root fp (class) | r0 exit | r1 | error surfaced after | abort r0 |
|---|---|---|---|---|---|---|---|---|
| F2 | timeout | 3 | class not recoverable | 10/0x88 (REM_ACCESS) | 9 (declined) | declined (exit 9), waiter released by self-signal | 4.0 ms [3.9–4.1] | 882 ms |
| F2 | blocking | 3 | class not recoverable | 10/0x88 (REM_ACCESS) | 9 | declined (exit 9) | 3.9 ms | 889 ms |
| F4 | timeout | 3 | RETRY_EXC, OOB socket shows FIN | 12/0x81 (RETRY_EXC) | 9 | killed | 3.73 s [3.67–3.79] after the kill | 603 ms |
| F4 | blocking | 3 | RETRY_EXC, OOB socket shows FIN | 12/0x81 (RETRY_EXC) | 9 | killed | 3.66 s [3.62–3.78] | 744 ms |

Before the kernel-warming fix, the F2 blocking receiver could not release its waiter: its
release kernel never started, so it hung until the 30 s cap (exit 7). In timeout mode the
release kernel only started when the waiter timed out (4.1 s). Evidence:
`results/20260924/diag/f2_before_warm/`, `diag/cancel_phase/`
(`rx_cancel_phase=0 … waiter_done=0`). After the fix it takes 0.16 ms.

### Time to recover (ms, median [min–max] over recovery rounds)

| fault | wait | rounds | fault → device detects | kernel return → commit done | of which: prepare / REQ→ACK / commit | replay | **kernel return → recovered** | **fault → recovered** |
|---|---|---|---|---|---|---|---|---|
| F1 | timeout | 3 | 15.5 [1.5–16.4] | 7.87 | 0.21 / 4.59 / 3.07 | 0.26 | **8.13** [8.04–8.28] | **24.0** [9.8–24.7] |
| F1 | blocking | 3 | 15.6 [1.0–15.7] | 7.88 | 0.22 / 4.56 / 3.06 | 0.26 | **8.14** [8.12–8.18] | **23.8** [9.4–24.1] |
| F1 ×5 | timeout | 25 | 10.1 [1.4–13.3] | 7.84 | 0.17 / 4.57 / 3.07 | 0.26 | **8.05** [7.90–8.30] | **18.1** [9.4–21.6] |
| F1 ×5 | blocking | 25 | 10.1 [1.4–13.3] | 7.83 | 0.19 / 4.58 / 3.04 | 0.26 | **8.05** [7.90–8.40] | **17.7** [9.6–21.7] |
| F3 | timeout | 3 | 3736 [3613–3767] | 7.92 | 1.06 / 3.65 / 3.15 | 0.28 | **8.20** [8.01–8.22] | **3744** [3621–3775] |
| F3 | blocking | 3 | 3639 [3516–3670] | 7.85 | 1.08 / 3.50 / 3.08 | 0.28 | **8.12** [7.96–8.21] | **3647** [3525–3678] |
| F3 ×5 | timeout | 25 | 3722 [3630–3754] | 7.78 | 1.10 / 3.51 / 3.09 | 0.28 | **8.03** [7.74–8.30] | **3730** [3638–3762] |
| F3 ×5 | blocking | 25 | 3722 [3536–3788] | 7.79 | 1.10 / 3.55 / 3.09 | 0.28 | **8.03** [7.79–8.25] | **3730** [3545–3796] |
| D0 | both | 18 | - | 22.9 | 1.26 / 18.6 / 3.11 | - (d = 0) | 22.9 | - |

How to read the table:
- **Fault time.** It is the hook's `fire_mono_ms`; F3 fires on rank 1 and is converted with the
  measured clock offset.
- **Detection.** "Device detects" is the Q4 record's `%globaltimer` placed on the host clock.
  For F1 it is mostly the wait for the next put: the fault lands between iterations, and the
  ~1 ms minima are shots that hit an in-flight put, or the replay itself. For F3 it is the
  RETRY_EXC floor at IB timeout 14, as in Q1/Q4.
- **Rounds and replay columns.** "rounds" counts every round, including those whose replay
  failed (each ×5 cell: 20 recovered + 5 replay failed). The replay and the two "recovered"
  columns use recovered rounds only; a failed replay shows up as the next round's detection.
- **D0 handshake.** It includes up to 15 ms of the responder sleeping in its inter-iteration
  gap before it reads the REQ.

### Library step costs (µs, median; 4 QPs per side)

| fault | initiator: to ERR / drain / Prepare | initiator: 2RST / resync / INIT-RTR-RTS / Commit | responder: Prepare / Commit | CQEs in the unconsumed window (err/ok) |
|---|---|---|---|---|
| F1 | 150 / 14 / 210 | 1120 / 55 / 1900 / 3060 | 1270 / 3040 | 2/0 (the flushed put + signal) |
| F3 | 1000 / 14 / 1070 | 1140 / 61 / 1900 / 3120 | 180 / 3020 | 2/0 |
| D0 | 1210 / 13 / 1260 | 1160 / 53 / 1880 / 3110 | 1250 / 3030 | 0/0 |

- **Cost.** Moving a healthy RTS QP to ERR takes about 0.3 ms, and each of the four other
  transitions about 0.28 ms: they are firmware commands. The device resync (two small
  copies + memsets) takes about 55 µs.
- **Why "to ERR" differs by fault.** It is cheap on the side whose QPs the hook had already
  moved to ERR: the initiator in F1, the responder in F3.

### Signal reconciliation

| cell | rounds | d = 1 (put + ADD replayed) | d = 0 (ADD had landed, nothing replayed) | V outside {expected−1, expected} |
|---|---|---|---|---|
| F1, F1 ×5, F3, F3 ×5 (both modes) | 112 (20 with a failed replay) | 112 | 0 | 0 |
| D0 (both modes) | 18 | 0 | 18 | 0 |

- **d = 1 rounds.** In every one, V = expected − 1: the ADD had not executed, so the put and
  the ADD were replayed.
- **The d = 0 case from a real fault.** It needs the error to strike after the responder
  executed the ADD and before the ACK arrived. It never occurred in these runs, so it was
  forced: the D0 rows recover after a completed operation. There the responder was already at
  its next barrier, reported V = expected, and nothing was replayed. Final signal: 120/120,
  6/6.

### Negative controls (`results/20260924/diag/negative/`, F1, timeout, 2 trials each)

| variant | expected | observed |
|---|---|---|
| `NCCL_GIN_RECOVERY_DIAG=doca_cqe_rsvd` (`cqe_rsvd` = ending epoch's WQEs, as in DOCA's `reset_tracking_and_memory`) | 1st recovery fine (cumulative = non-cumulative from 0); 2nd recovery: the GPU polls the wrong ring slot | 2/2: recovery 1 ok; recovery 2's replay reached the receiver (receiver verified 30 operations) but the initiator's flush timed out. The Q4 timeout dump shows the polled slot holding a stale previous-epoch CQE (`wqe_counter` 23, success opcode) where WQE 1 was expected. Declined, both ranks exit 9 |
| `NCCL_GIN_RECOVERY_DIAG=keep_proxy_db` (proxy mailbox and counter not reset) | the new epoch's producer index stays below the stale one, so no doorbell rings | 2/2: first replay timed out; the polled slot was never written (opcode 0xf); receiver saw 19 = initiator's 19 operations. Declined, both exit 9 |

### Confirmation on the final build (`results/20260924/confirm/`, 18 trials)

Every cell was run once per wait mode (single F1 twice) on the final build (`951001fe…` +
driver `50501ffc…`), and all 18 trials matched the main matrix:
- none, F1, F3, F1 ×5, F3 ×5 and D0 all completed, with data bit-exact and exact signals on the
  receiver. The ×5 runs again had 5 faults, 4 recovered operations and 1 failed replay.
- F2 and F4 were declined on the initiator (REM_ACCESS; RETRY_EXC with the peer dead). On F2
  the receiver was declined as well.
- Aborts returned, and no processes were left on either node.
- Kernel return → recovered: 8.07 ms median [7.61–8.85] over the 22 recovered rounds after a
  fault (26 rounds after a fault, 4 of them with a failed replay; plus 6 forced D0 rounds).
- Details: `confirm/summary.md`.

### No-fault overhead (`results/20260924/lat/`; classify on in both; 6 interleaved runs × 5 × 2000 put+signal+flush per cell)

| bytes | wait | flag | p50 (µs) median [runs] | p99 median [runs] | pooled mean | CPU (cores) |
|---|---|---|---|---|---|---|
| 4096 | timeout | off / on | 10.13 [9.98–10.21] / 10.21 [10.02–10.21] | 10.59 [10.40–11.30] / 11.32 [10.37–11.33] | 9.92 / 9.95 | 2.07 / 2.07 |
| 4096 | blocking | off / on | 10.27 [10.24–10.27] / 10.24 [10.24–10.27] | 11.46 [11.42–11.52] / 11.48 [11.46–11.49] | 10.35 / 10.35 | 2.07 / 2.07 |
| 262144 | timeout | off / on | 36.88 [36.86–37.38] / 37.49 [36.86–37.66] | 38.94 / 38.94 | 37.23 / 37.51 | 2.07 / 2.07 |
| 262144 | blocking | off / on | 37.69 [36.86–38.27] / 37.38 [36.86–38.30] | 38.98 / 38.96 | 37.69 / 37.64 | 2.07 / 2.07 |

- **What differs with the flag on.** The GPU kernels are byte-identical with the flag on or
  off. On the host, the flag adds two seq_cst atomics per proxy-progress call and a copy of the
  last error record (error path only).
- **Spread.** The 4 KiB timeout p99 is bimodal *per run* (about 10.4 or 11.3 µs) with the flag
  both on and off, so pooled p99 differences reflect the run mix.

## Findings

1. **[measured] The mechanism works as designed, first time.**
   - Recovery replaces the old incarnation of both ends of every QP pair: ERR, RESET, then
     INIT/RTR/RTS with the stored connect-time attributes and fresh random 24-bit PSNs.
   - On the GPU, the WQE index space restarts at 0 while the CQ mapping is advanced by the
     ending epoch's WQEs.
   - The NIC restarts the SQ at WQE counter 0 after `QP_2RST`. After a recovery, the next
     fault's root CQE carries small WQE counters (0 for a fault on the replay itself, 20 ten
     operations later).
   - The stale CQ ring does not need rewriting.
2. **[measured] Exactly-once signal delivery.**
   - The data put is idempotent; the signal ADD is not. The ADD is made exactly-once by
     reading V only after both ends are in ERR and replaying the ADD only if V says it is
     missing.
   - Measured: no double count and no loss in 130 recovery rounds (112 after faults, 18
     forced), including 20 in which a second fault struck the replay. `V + d = expected` held
     in every round, and every per-operation and final signal was exact.
3. **[measured] The fault is recovered in about 8 ms of host time after detection, independent
   of the fault class.** About 6 ms of that is firmware QP-transition commands (four QPs per
   side), so it scales with the number of GIN contexts. It could be halved by resetting only
   the pairs that carried traffic, or by issuing the commands in parallel (not done).
4. **[measured] Decline is clean in both wait modes**, but only because the driver releases its
   own blocking waiter. A user devComm has no abort flag, so a blocking `waitSignal` on a peer
   that will never signal can only be ended by writing the waited-on signal. Here that is done
   with a self-signal over the self-loop QP.
5. **[measured] Kernels launched during a recovery must not trigger a local-memory resize.**
   A resize needs an idle device, so it serialises behind the spinning waiter: the launch
   waited until the timeout-mode waiter exited, and never started in blocking mode. A GIN
   `signal`+`flush` kernel has a 336-byte stack frame, while `waitSignal` and `readSignal`
   kernels have none. Launching the kernel once at init fixes it.
6. **[measured] DOCA's own `doca_gpu_verbs_reset_tracking_and_memory` is not usable for repeated
   recovery.**
   - Its `cqe_rsvd` is not cumulative: the negative control shows the second recovery failing.
   - It also refills the CQ with 0xff, whose owner bit is valid in odd laps (inferred to break
     sm_90's owner-only poll; not tested, no Hopper here).
   - It calls `cudaDeviceSynchronize`, which would deadlock against a responder's waiter
     (inferred from finding 5).
7. **[measured] GDAKI's "silent" failure modes also exist on the recovery path.**
   - In the `doca_cqe_rsvd` control the operation succeeded on the wire but the initiator timed
     out: a spurious failure, the mirror image of Q2's silent success.
   - The driver's barrier race (inherited from Q4, found here) produced "signal done, data
     poisoned" once.
   - Both are detectable only by end-to-end data and signal checks.

## Measured vs inferred

- **Measured.** Everything in the tables and findings 1–5 and 7:
  - outcomes and bit-exact data;
  - exact signals per operation and at the end;
  - timing breakdowns (host CLOCK_MONOTONIC; device times from `%globaltimer` via the Q4
    calibration);
  - library step costs;
  - the cancel-kernel phase markers;
  - the stack-frame sizes (`ptxas -v`);
  - the negative controls with their timeout-dump contents;
  - overhead;
  - md5/ldd provenance.
- **From source, consistent with the measurements.**
  - Why each resync step is needed (design §6.3).
  - The NIC fetches only up to the doorbell record.
  - DOCA tracks QP state in software (the 2ERR/2RST path).
  - The CQ has overrun-ignore set.
  - One CQE per WQE on a ring CQ.
- **Inferred, not tested.**
  - The 0xff-refill hazard on sm_90.
  - Behaviour with GPU-rung doorbells (PeerMappingOverride), collapsed CQs, companion (counter)
    QPs, more than two ranks, or pipelined operations (design §7 gives the rule; one operation
    in flight here).
  - Symmetric initiation (both ranks at once).
  - A peer host that dies without FIN, which is covered only by the handshake deadline.
  - The d = 0 branch after a *real* fault (only forced here).

## Limitations

- CPU-proxy doorbell mode and ring CQ only; other modes decline by design.
- **One initiator per QP pair** and one operation in flight (lockstep driver).
- **Quiescence of kernels is a contract**, checked only through QP state. The application must
  stop producers and warm any kernel it launches during recovery.
- **LOCAL_QP_ERR is treated as transient.** A persistent local fault is bounded by the
  4-attempt cap.
- **The reset cost is about 6 ms of firmware commands.** All four GIN contexts' QP pairs are
  reset, including idle ones.
- **Provenance.** Batches 1–3 ran on a build without the (default-off) diagnostic knob; the
  final build is covered by `confirm/`.
- **Two runs may have overlapped another agent's experiments** during the lock-file migration:
  a 15 s smoke at 12:01 and a 14 s smoke at 12:07. Both were smoke runs whose logs were
  discarded or superseded, and both are noted in the shared cluster log.

## GPU doorbell (PeerMappingOverride=1, permanent since 2026-09-24 13:53)

Every result above ran in the CPU-doorbell fallback. With the override, DOCA maps the NIC's UAR
page into the GPU and the GPU rings the doorbells itself. This section re-runs the classifier
and the recovery matrix in that state (`results/20260924_gpudb/`, 2026-09-24 15:10–15:39, 4
holds of 1–9 min).

### Which doorbell mode GDAKI uses now (measured, four indicators)

| indicator | GPU doorbell (default now) | CPU proxy forced (`NCCL_GIN_GDAKI_NIC_HANDLER=1`, positive control) |
|---|---|---|
| new NCCL WARN, once per GDAKI context (`gin_recovery_gpudb.diff`): `GIN/GDAKI: doorbell mode=... first_nic_handler=... needsProxyProgress=` | `mode=GPU`: 12/12 main QPs `GPU_SM_DB`, `needsProxyProgress=0`, on both ranks, for the user and the internal devComm, in every trial | `mode=CPU_PROXY`: 12/12 `CPU_PROXY`, `needsProxyProgress=1` |
| NCCL's GIN progress thread "NCCL GIN P0-0" (`scripts/thread_probe.sh`; needs `NCCL_SET_THREAD_NAME=1`) | absent on both ranks | present on both ranks |
| DOCA's own "Enabling CPU proxy mode" (`DOCA_GPUNETIO_LOG=4`) | 0 lines | 24 lines per rank (one per QP) |
| process CPU with no fault (lat runs) | 1.07 cores | 2.07 cores (the proxy spins one core) |

The indicators agree in every trial. For the unmodified gin_q4 binaries, the DOCA line and the
thread probe are the indicators; both were validated in the same driver state by a forced-proxy
gin_q4 run.

### Q4 classifier (unchanged gin_q4 build and runner; `results/20260924_gpudb/q4/`)

| fault | n | device class, root fp | host `ncclCommGetAsyncError` after the fault | silent success | abort / leftover |
|---|---|---|---|---|---|
| F1 | 3 | LOCAL_QP_ERR 5/0xf5 | 14.8–16.1 ms | 0 | clean / 0 |
| F2 | 2 | REM_ACCESS 10/0x88 | 4.1–6.8 ms | 0 | clean / 0 |
| F3 | 2 | RETRY_EXC 12/0x81 | 3.51–3.58 s | 0 | clean / 0 |
| F4 | 2 | RETRY_EXC 12/0x81 | 3.59–3.71 s | 0 | clean / 0 |
| F1, CPU proxy forced | 1 | LOCAL_QP_ERR 5/0xf5 | 14.7 ms | 0 | clean / 0 |

These match the CPU-doorbell Q4 results, so the classifier does not depend on the doorbell path.

### The committed recovery (v1) under GPU doorbells: declined, not broken

2/2 runs (F1 timeout, F3 blocking; `results/20260924_gpudb/v1/`) were declined at Prepare with
"doorbell mode is not CPU proxy". Both ranks exited "declined" and aborts returned. v1 rejects
every non-proxy QP before touching anything. That guard mattered: v1's Commit writes the
host-memory doorbell record and the proxy mailbox, and in GPU mode neither exists (the pointers
are null and the record lives in GPU memory).

### v2: `gin_recovery_gpudb.diff` (layered on `gin_recovery.diff`, +~95 lines, same env gating)

In GPU_SM_DB mode the GPU's submit raises `sq_wqe_pi` (`atomic_max`), rings the UAR doorbell and
writes the doorbell record, which is in GPU memory. There is no CPU-side doorbell state.

- **Prepare, GPU mode.** Quiescence is `sq_ready_index == sq_rsvd_index == sq_wqe_pi` and the
  GPU-memory doorbell record (read D2H) `== sq_rsvd_index & 0xffff`. CPU-proxy mode is unchanged.
- **Commit, GPU mode.** Zero the doorbell record with `cudaMemsetAsync` on the recovery stream,
  while the QP is in RESET. `sq_wqe_pi` is already reset with the device struct.
- **Other.**
  - Modes other than CPU_PROXY or GPU_SM_DB with a valid DBR (BlueFlame, no-DBR, SW-emulated
    DBR, free-flow) are declined.
  - There is no BlueFlame index to resync: DOCA's GPU submit writes an 8-byte doorbell to a
    fixed UAR offset, and BlueFlame is used only with TMA (sm_90).
  - A doorbell-mode log line was added, and two diagnostic knobs, `keep_gpu_pi` and
    `keep_gpu_dbr`.
- **Build and deploy.** Built in `gi/gin_recovery/build_gpudb` from a separate worktree; the
  four diffs applied to a clean v2.32.3-1 reproduce the tree (checked). Deployed to
  `~/gi-bundle/gin_recovery_gpudb/` (libnccl `1ed8e0a1…`, driver `89e72d50…`). The v1 bundle
  `~/gi-bundle/gin_recovery/` (`951001fe…`) is untouched.

### Recovery v2 results (`results/20260924_gpudb/summary.md`)

| fault | wait | n | doorbell | faults | rounds (recovered / replay failed) | data bit-exact / signal exact | final async |
|---|---|---|---|---|---|---|---|
| none | timeout / blocking | 2 / 2 | GPU | 0 | 0 | 4/4 / 4/4 | no error |
| F1 | timeout / blocking | 3 / 3 | GPU | 1 each | 1 / 0 each | 6/6 / 6/6 | no error |
| F3 | timeout / blocking | 3 / 3 | GPU | 1 each | 1 / 0 each | 6/6 / 6/6 | no error |
| F1 ×5 | blocking | 3 | GPU | 5 each | 4 / 1 each | 3/3 / 3/3 | no error |
| F3 ×5 | blocking | 3 | GPU | 5 each | 4 / 1 each | 3/3 / 3/3 | no error |
| D0 (forced, d = 0) | timeout / blocking | 1 / 1 | GPU | 0 | 3 / 0 each | 2/2 / 2/2 | no error |
| F2 | timeout / blocking | 2 / 2 | GPU | - | declined (REM_ACCESS; surfaced 4.0–6.4 ms) | - | `ncclRemoteError` |
| F4 | timeout / blocking | 2 / 2 | GPU | - | declined (RETRY_EXC, peer dead; 3.7–3.8 s) | - | `ncclRemoteError` |
| F1, F3, F1 ×5 | timeout, blocking | 2, 1, 1 | CPU proxy forced (v2 regression) | as above | all recovered | 4/4 / 4/4 | no error |

- **Correctness.** The 40 trials in `runs/` had 62 recovery rounds (same definition as above):
  56 after a fault (47 recovered, 9 with a failed replay) and 6 forced D0. These include the
  forced-proxy regression (8 rounds) and both negative controls (6). The GPU-mode matrix alone:
  18/18 fault runs recovered with data and signal exact, 42 rounds after a fault (36 + 6 with
  a failed replay) and 6 forced. There were 10 declines: 8 by policy (F2, F4) and 2 after the
  `keep_gpu_pi` control's failed replay. `V + d = expected` held in all 62 rounds. All aborts
  returned, and no processes were left on either node (40 trials, 19 lat runs).
- **Time (GPU mode).** Kernel return → recovered was 8.2–8.8 ms (median per cell): prepare
  0.2–1.2 ms, REQ→ACK 3.6–4.7 ms, commit 3.1 ms, replay 0.26–0.28 ms. This is the same as in
  CPU mode (8.0–8.2 ms).
- **Fault → recovered** is set by detection, as before: F1 at 9.6–9.7 ms (single-fault runs;
  here the fault hit an in-flight operation, so there was no 15 ms wait for the next one) and
  F3 at 3.59 s.
- **Outliers.** Two rounds took about 21 ms because one responder INIT/RTR/RTS sequence took
  15 ms instead of 1.9 ms (firmware command time, inside the modify calls). Both were in
  forced-proxy runs on sunny.

**Negative controls (GPU mode; F1, timeout, 2 shots, 2 trials each).**

| variant | observed |
|---|---|
| `keep_gpu_pi` (device `sq_wqe_pi` not reset) | 2/2 broken, as predicted: the first replay's flush timed out. The polled CQ slot was never written (opcode 0xf), because the GPU's `atomic_max` on the stale `sq_wqe_pi` suppressed the doorbell. Declined, both ranks exit 9. |
| `keep_gpu_dbr` (GPU doorbell record not reset) | 2/2 recovered, 4/4 rounds, data and signal exact. A stale record did no harm here: the GPU's first submit rewrites it before the NIC reads it. The reset is kept as a defensive step (the NIC reads the record on doorbell recovery); it was not shown to be necessary. |

**No-fault overhead (GPU mode).**

- Recovery flag off vs on (classifier on in both): p50 at 4 KiB was 9.66 / 9.64 µs (timeout)
  and 10.21 / 10.21 µs (blocking); at 256 KiB, 37.19 / 37.00 µs and 37.31 / 36.84 µs. That is
  2–3 runs × 10k samples per cell, and no difference within run-to-run spread.
- Same session, 256 KiB timeout, flag on: GPU 37.00 µs at 1.07 cores, forced CPU proxy 37.50 µs
  at 2.07 cores.
- One lat run failed with a TCP port collision in the driver's bootstrap
  (`bind: Address already in use`). It was re-run; the log is kept in `lat/failed/`.

**Measured vs inferred.**
- **Measured.** The doorbell mode per QP (DOCA's resolved `nic_handler`, read from the host
  shadow of the device QP struct), the tables above, and both negative controls.
- **From source.** The GPU submit path (`doca_gpu_dev_verbs_submit_db`: `atomic_max` on
  `sq_wqe_pi`, UAR write, DBR write, second UAR write) and the DBR placement (GPU memory when
  DOCA resolves the GPU handler).
- **Not tested.** BlueFlame and no-DBR GPU modes (declined), and Hopper.

## Files

| path | what |
|---|---|
| `RECOVERY_DESIGN.md` | design and safety argument |
| `gin_recovery.diff` | NCCL patch (header: base, layering, env) |
| `gin_rec.cu` | driver |
| `scripts/build_driver.sh`, `deploy.sh`, `make_diff.sh` | build / deploy / regenerate the diff |
| `scripts/run_trial.sh`, `run_matrix.sh`, `confirm_batch.sh` | one trial / one batch / confirmation batch (inside `../common/cluster_run.sh`) |
| `scripts/rec_rows.py`, `summarize.py` | logs → `trials.csv` + `events.csv` → `summary.md` |
| `scripts/recount.py` → `results/RECOUNT.md` | runs, rounds, declines and bit-exact checks recounted from the raw per-trial logs of `20260924/` and `20260924_gpudb/`, with definitions |
| `results/20260924/runs/logs/` | main matrix (per-trial logs, KV, meta) |
| `results/20260924/lat/logs/` | overhead runs (raw per-iteration latencies gzipped) |
| `results/20260924/diag/` | `f2_before_warm/`, `cancel_phase/` (release-kernel bug), `negative/` (controls) |
| `results/20260924/smoke/` | first end-to-end smoke (base, F1, F3) |
| `results/20260924/confirm/` | every cell once on the final build |
| `results/20260924/{trials,events}.csv`, `summary.md` | generated |
| `gin_recovery_gpudb.diff`, `scripts/make_diff_gpudb.sh` | v2 (GPU doorbells), layered on `gin_recovery.diff` |
| `scripts/run_gpudb.sh`, `q4_rerun.sh`, `thread_probe.sh` | GPU-doorbell matrix, Q4 re-run, doorbell-mode probe |
| `results/20260924_gpudb/` | GPU-doorbell runs: `runs/` (v2 matrix, negative controls, forced-proxy regression), `lat/`, `q4/`, `v1/`, `smoke/`, `summary.md` |

Reproduce (each line one cluster hold):

```
CR=../common/cluster_run.sh; L=results/20260924/runs/logs
$CR -t rec-a -- bash -c "for b in base f1 f3 f2 d0 f4; do bash scripts/run_matrix.sh $L \$b 3; done"
$CR -t rec-b -- bash -c "bash scripts/run_matrix.sh $L f1multi 5; bash scripts/run_matrix.sh $L f3multi 5"
$CR -t rec-c -- bash -c "bash scripts/run_matrix.sh $L flagoff 2; LAT_REP_TO=6 bash scripts/run_matrix.sh results/20260924/lat/logs lat"
$CR -t rec-d -- bash scripts/confirm_batch.sh
python3 scripts/rec_rows.py $L results/20260924/lat/logs --trials results/20260924/trials.csv --events results/20260924/events.csv
python3 scripts/summarize.py results/20260924/trials.csv results/20260924/events.csv > results/20260924/summary.md
```
