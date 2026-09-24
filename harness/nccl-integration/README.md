# GPU×RDMA fault tolerance: in-tree NCCL IB-transport classification + safe recovery

The patch adds RDMA fault **classification** to NCCL's own IB transport
(`src/transport/net_ib.cc`, NCCL v2.23.4-1), plus a **bilateral QP recovery** that runs only
when it can be shown to be correct. It is not an external wrapper.

Everything is behind `NCCL_RDMA_FAULT_RECOVERY=1`. With the flag off, the transport makes the
same verbs calls and returns the same results as stock.

**Status: rebuilt, statically verified, and validated on the 2-node GPU setup on 2026-09-23**
(all six runs of `logs/autorun_recovery_test.sh` behaved as designed; logs in `logs/run_20260923/`).
All earlier run logs came from superseded, defective builds and are kept only as history in
`logs/historical/` (see `HISTORICAL.md` there). The full design and the safety argument are in
`DESIGN_recovery.md`.

## Scope (Stage 1, what the code actually does)

When recovery is enabled and an IB completion fails, the patch first classifies the fault and
logs it together with an OOB-socket liveness probe. It then recovers only if **all** of the
following hold:

- **Fault class.** The first error CQE of the incident is `WR_FLUSH_ERR` on the **send** comm,
  meaning a transient local ERR such as the `NCCL_RDMA_FAULT_INJECT` hook.
- **Configuration.** `nqps == 1`, `ndevs == 1`, and the send has `nreqs == 1`. That means
  a single QP, a single NIC, and no multi-recv.
- **Quiescence on both sides, checked before any QP is modified.**
  - Initiator: the failed send, decoded from `wc->wr_id`, is the only request in flight on
    the comm.
  - Responder: the matching receive (found by the CTS FIFO sequence number) is the only
    request in flight, and its data has not been consumed. A GPU-flush read still in flight
    is waited out, for a bounded time.
- **Health.** No async fatal event is recorded, and the peer's socket shows no FIN/RST.
- **Bounds.** At most 3 initiations per comm and 1 replay per request.

When all of these hold, the patch does the following:

1. Both QPs are reset through a non-blocking REQ/ACK handshake on the comm's OOB socket, with
   fresh random PSNs. Each QP comes back up with its connect-time attributes: access flags,
   `override_tc`, and ECE.
2. The responder re-posts exactly that one receive.
3. The initiator replays exactly that one `RDMA_WRITE_WITH_IMM`. This is safe because the
   write is idempotent and the remote buffer is still reserved.

In every other case the comm fails exactly like stock, with `ncclRemoteError`, and the failure
is latched: every later operation on the comm fails too. Failure is bounded in time (default
deadline `NCCL_RDMA_FAULT_HANDSHAKE_MS=2000`). The peer is told with NACK or FAIL, so it fails
promptly as well.

The patch never blocks the proxy thread on a socket, never drops another request's
completion, and never completes a receive without its data. Replaying several outstanding
requests at once (Stage 2) is **not implemented**. In that situation the patch declines.

## Defects fixed (line numbers = patched `net_ib.cc`, git hash-object `0f3397fd`, as in the diff banner)

| Defect | Change | Where |
|---|---|---|
| C1 wrong request / lost batch | The flag-on path consumes the **whole** poll batch with the stock decoding: successes complete their requests, errors are recorded. The failed request is decoded from the error CQE's `wr_id` (`BODY` tag for unsignaled data WRITEs). The responder picks the receive by the REQ's FIFO sequence number, never by the tested `r`. The error CQE's (undefined) opcode is never used. Recv WQEs and CTS writes carry RQ/CTS tags in bits the stock decoder ignores. | batch loop @3052-3065, `ncclIbFrCompleteWc` @2100, `ncclIbFrNoteErrorWc` @2129, `ncclIbFrFailedSend` @2284, tags @877/2675/2903/2945 |
| C2 reset destroys in-flight work | Nothing is reset unless both sides are quiescent: the initiator checks in `ncclIbFrFailedSend`, the responder checks, *before* reset, in `ncclIbFrResponderEvaluate`. The responder goes RTS→ERR, drains until its receive's WQE has terminated, then goes to RESET, so no earlier completion can be removed by mlx5's CQ clean-up. `ncclIbFrDrainOldQp` drops only the recovered request's CQEs; others are consumed normally, or the recovery fails. There is no blind CQ drain. | @2490, @2441, @2170 |
| M1 multi-QP/NIC | Configuration gate before any handshake, on both sides; the REQ's `nqps` is checked too. | @2327, @2499 |
| M2 blocking handshake / deadlock | Non-blocking `send/recv(MSG_DONTWAIT)` with per-comm offsets. The initiator is a state machine driven by `ncclIbTest` (`InitWait`, deadline). The responder is serviced from every `ncclIbTest` and `ncclIbIrecv` of the recv comm, with no attempt cap on answering. Symmetric injection cannot deadlock. | `ncclIbFrTxProgress`/`RxProgress` @2024/2051, `ncclIbFrInitiatorStep` @2367, `ncclIbFrInitiatorIdle` @2424, `ncclIbFrResponderService` @2550, hooks @3017/2926 |
| M3 fake liveness | `recv(MSG_PEEK\|MSG_DONTWAIT)`: 0 means FIN, ECONNRESET/EPIPE/ETIMEDOUT/ENOTCONN mean RST, EAGAIN means no evidence. The result is used for the 0x81 sub-cause and as the initiation gate. A host death without FIN/RST is not detected until TCP times out. | `ncclIbFrLiveness` @1957, used @2308-2326 |
| M4 re-recovery on a failed comm | Sticky per-comm latch (`ncclIbFrFailed`). Test, isend and irecv return the error without polling or recovering. | `ncclIbFrFail` @2067, `ncclIbFrPreTest` @2598, isend/irecv gates @2739/2926 |
| M5 NAK classes | Only `WR_FLUSH_ERR` is recoverable. REM_ACCESS and REM_INV_REQ raise `IBV_EVENT_QP_ACCESS_ERR`/`QP_REQ_ERR` on the peer QP, which becomes a never-cleared `fatalErrorCount` in `ncclIbAsyncThreadMain`→`ncclIbQpFatalError`, so NCCL fails that comm permanently. RNR cannot occur with `rnr_retry=7`. A fatal counter is also re-checked before any reset. | `ncclIbFrClassify` @1913, `ncclIbFrFatal` @2014 |
| M6 test driver | Per-rank, per-iteration, per-index inputs. rbuf is poisoned with NaN, and the **entire** rbuf is compared bit-exactly on **every** rank. Output is `ok` or `MISMATCH count= first=`. Every wait is bounded, with `ncclCommAbort` on an error or timeout. Exit codes: 0 ok, 2 NCCL, 3 async, 4 timeout, 5 mismatch, 7 abort hang (watchdog). | `nccl_ar2.cu` |
| snapshot ran with flag off | Gated on `fr.enabled`. | @2784 |
| `faultRetries` never reset | Replaced by `frReplays`, reset in `ncclIbGetRequest`, cap 1. | @935, @1688 |
| replayability checked after reset | All checks happen before the REQ (initiator) and before the reset (responder). | as above |
| responder never checked `nqps` | Checked. | @2499 |
| RespWait ~18 ms spin | Removed. Deadlines are time-based: `HANDSHAKE_MS` for the reply, `2×HANDSHAKE_MS` for DONE, `/4` for the flush wait, `min(/10, 100 ms)` for the ERR drain. | @2342, @2542, @2567, @2455 |
| QP rebuilt with different attributes | Access flags are recorded in `ncclIbCreateQp` (data QPs use `REMOTE_WRITE`); remote QPN, `override_tc` (recv QP 0) and ECE are recorded at connect/accept; `ncclIbFrBringUp` repeats `set_ece` before RTR and reuses `ncclIbRtrQp`/`ncclIbRtsQp`. | @1154, @1425-1432, @1578-1585, @2225 |
| stale header comment | Replaced by an accurate block comment. | @1830 |
| deterministic PSN | Random 24-bit PSN from `/dev/urandom` (splitmix fallback). | `ncclIbFrFreshPsn` @1998 |

## Build (done here; reproduce with)

```bash
git clone --branch v2.23.4-1 https://github.com/NVIDIA/nccl.git && cd nccl
sed '/^# /d;/^#$/d' ../net_ib_fault_recovery.diff | git apply
git hash-object src/transport/net_ib.cc          # must equal the hash in the diff banner
make -j src.build CUDA_HOME=/usr/local/cuda-12.8 \
  NVCC_GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86"
cd .. && /usr/local/cuda-12.8/bin/nvcc -O2 -std=c++17 \
  -gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86 \
  -I nccl/build/include -L nccl/build/lib -o nccl_ar2 nccl_ar2.cu -lnccl
```

Verification results:

- **Build:** rc=0 with 0 warnings, the same as the stock build.
- **Strict compile** (`-Wall -Wextra -Wunused-function`): 10 warnings for both stock and
  patched `net_ib.cc`, and they are the identical set. The alignment `static_assert`s pass.
- **Driver:** compiles cleanly with `-Wall -Wextra`.
- **Patch:** applies cleanly to a fresh clone of the tag, and the result is byte-identical to
  the tree that was built.
- **Independent review:** a separate read-only review found no critical defect. It reported
  four minor issues:
  - The initiator stopped reading the socket once idle, so the two sides could diverge on a
    late DONE. Fixed: `ncclIbFrInitiatorIdle`, deadline checked before a buffered ACK is used,
    and the responder's DONE deadline doubled.
  - The ERR-drain busy-poll could grow with `HANDSHAKE_MS`. Fixed: capped at 100 ms.
  - The fatal check was skipped while waiting. Fixed.
  - Latched ops starve later ops. Documented below.
  Those fixes were rebuilt and re-verified as above.

## 2-node validation results (2026-09-23)

rain (Quadro RTX 5000, mlx5_1) and sunny (RTX A4000, mlx5_0), RoCE v2, PMTU 4096; the link
carried no other traffic during the runs (sampled every 5 s). Logs: `logs/run_20260923/`.

| Run | Verdict | What happened |
|---|---|---|
| `base` | PASS | Flag off; 60/60 iterations bit-exact on both ranks |
| `inject` | RECOVERED | Fault at net send #40; bilateral reset with fresh PSNs, one WRITE replayed; 60/60 bit-exact on both ranks |
| `symmetric` | RECOVERED | Fault injected on both ranks; both recovered, no deadlock; 60/60 bit-exact |
| `pipelined` | DECLINED-clean | Fault at send #7 of a pipelined 16 MB all-reduce; responder NACK "not quiescent", nothing reset on either side, both comms latched, stock error |
| `prockill_off` | clean failure | **Stock control** (flag off): rank1 killed; rank0 gets RETRY_EXC, then `ncclCommAbort` hangs (watchdog exit 7) |
| `prockill` | clean failure | Flag on: RETRY_EXC classified, 0x81 sub-cause `proc_kill` from the peer's FIN, recovery declined, stock error; `ncclCommAbort` then hangs exactly as in the stock control |

**`ncclCommAbort` hangs after a transport error in stock NCCL 2.23 too.** After any comm
error, the abort's `commFree` joins the proxy service thread, which joins the proxy progress
thread, and `ncclProxyProgress` keeps looping while `state->stop == 1 && state->active`
because the failed op never retires. The flag-off `prockill_off` run shows the same hang,
and the backtraces are in `logs/run_20260923/bt_prockill_off_r0.bt.txt` (stock) and
`bt_pipe_inject_r0.bt.txt` (flag on, same thread structure). The test driver therefore bounds
the abort with a watchdog (`NCCL_AR2_ABORT_WATCHDOG_S`, default 20 s, exit code 7), and the
script counts rc 7 as "error surfaced, then abort hung" instead of an outer-timeout FAIL.

## 2-node validation (how to run it)

rank0 runs on rain (mlx5_1, ens4f1np1, 30.0.0.3) and rank1 on sunny (mlx5_0, enp23s0f0np0).
The driver usage is `nccl_ar2 <rank> <rank0_ip> <port> [iters] [count] [sleep_ms] [timeout_s]`.

```bash
# build as above into ~/nccl-fr (nccl/ and nccl_ar2 side by side), then:
cd ~/rdma-error/harness/nccl-integration/logs
NCCL_LIB=~/nccl-fr/nccl/build/lib DRV=~/nccl-fr/nccl_ar2 ./autorun_recovery_test.sh ~/nccl-fr/run1 deploy
cat ~/nccl-fr/run1/summary.log
```

The script's runs and verdicts:

| Run | What it does | Expected verdict |
|---|---|---|
| `base` | Flag **off** on both ranks | PASS |
| `inject` | Flag on, `NCCL_RDMA_FAULT_INJECT=40` on rank0, 1 channel / Ring / Simple / 1 QP / 256 KB | RECOVERED (every iteration bit-exact on both ranks) or DECLINED-clean (both `rc=3`, reason logged) |
| `symmetric` | Inject on both ranks | Must not deadlock; same verdicts as `inject` |
| `pipelined` | Default channels and protocols, 16 MB, inject 7 | Clean decline or completion, never a hang or MISMATCH |
| `prockill_off` | Stock control: flag off, rank1 SIGKILLed | rank0 exits non-zero (3, or 7 when the abort hangs) |
| `prockill` | Flag on, rank1 SIGKILLed | Same as `prockill_off`, plus the 0x81 sub-cause log |

Any MISMATCH, per-iteration timeout (rc 4) or outer timeout (rc 124) is a FAIL. rc 7 means the error surfaced and then `ncclCommAbort` hung (stock behaviour, see above). The script detects each node's RoCE v2 GID index (rain's moved from 3 to 4 by 2026-09-23) and runs both ranks line-buffered so NCCL WARN lines survive a kill.

**Choosing k.** Recovery requires the peer to have exactly one receive posted. NCCL's recv
proxy posts every receive of an all-reduce up front (up to 8 steps). So the fault must hit the
*last* net send of an all-reduce. With one channel, an all-reduce has 2, 4 or 8 net sends per
rank depending on chunking, so a k that is a multiple of 8 (default 40) is aligned in all
cases. If `inject` reports `NACK (... not quiescent)`, the injection landed mid-op. That is the
correct, safe behaviour. Try `K=48` or `K=64`.

**Single manual pair** (same environment as the script):

```bash
# rain (rank0)
env LD_LIBRARY_PATH=~/nccl-fr/nccl/build/lib:/usr/local/cuda-12.8/lib64 NCCL_IB_HCA=mlx5_1 NCCL_IB_GID_INDEX=4 \
  NCCL_SOCKET_IFNAME=ens4f1np1 NCCL_DEBUG=WARN NCCL_MAX_NCHANNELS=1 NCCL_MIN_NCHANNELS=1 NCCL_ALGO=Ring \
  NCCL_PROTO=Simple NCCL_IB_QPS_PER_CONNECTION=1 NCCL_RDMA_FAULT_RECOVERY=1 NCCL_RDMA_FAULT_INJECT=40 \
  ~/nccl-fr/nccl_ar2 0 30.0.0.3 43210 60 65536 100 60
# sunny (rank1)
cd ~/nccl-fr-bundle && env LD_LIBRARY_PATH=$PWD:/usr/local/cuda-12.8/lib64 NCCL_IB_HCA=mlx5_0 NCCL_IB_GID_INDEX=3 \
  NCCL_SOCKET_IFNAME=enp23s0f0np0 NCCL_DEBUG=WARN NCCL_MAX_NCHANNELS=1 NCCL_MIN_NCHANNELS=1 NCCL_ALGO=Ring \
  NCCL_PROTO=Simple NCCL_IB_QPS_PER_CONNECTION=1 NCCL_RDMA_FAULT_RECOVERY=1 \
  ./nccl_ar2 1 30.0.0.3 43210 60 65536 100 60
```

Log lines to look for:

- **Recovered:** `[FAULT-INJECT] forced QP0 ... ERR` →
  `[FAULT-RECOVERY] status=5(WR_FLUSH_ERR) ... role=INITIATOR liveness=no-FIN/RST` →
  `initiator: quiescent single send ... RECOVER_REQ seq 1 sent` (rank0), then
  `responder: RECOVER_REQ ... received` → `responder: quiescent ... ACK seq 1 sent` (rank1), then
  `initiator: recovered ... replayed WRITE_WITH_IMM` (rank0), and every `iter N ok` on both
  ranks.
- **Declined:** a `NACK (...)` / `recovery declined: ...` line, then `latched FAILED` on both
  ranks, then `FAILED rc=3`.

## What remains untested at runtime

Validated on 2026-09-23 (above): one injected recoverable fault recovered and the collective
finished bit-exact; symmetric injection did not deadlock; a mid-pipeline fault declined
cleanly; a killed peer was classified `proc_kill` and failed like stock. The drain after
RTS→ERR and the ECE re-application did not break recovery on ConnectX-6 (VPI, MT28908) (whether ECE was
actually negotiated on this pair was not checked). Still untested:

1. faults that are not injected (the only recoverable class is a transient local ERR);
2. more than one fault per run, and long runs;
3. multi-QP or multi-NIC configurations (they decline by design; only the gate was exercised);
4. other NICs, firmware or NCCL versions.

The static argument for correctness is in `DESIGN_recovery.md` §4.

## Limitations

- **`ncclCommAbort` after an error hangs in NCCL 2.23 (stock behaviour).** See the validation
  results above; the patch neither causes nor fixes it.

- **Narrow recoverable class.** In practice, WR_FLUSH_ERR as the first error with no async
  event comes from software moving a QP to ERR, which includes the inject hook. Real NAK,
  retry-exhausted and link faults are classified and logged, then fail like stock.
- **Pipelining.** Under NCCL's default pipelining (several channels, receives posted ahead),
  most faults find more than one request in flight and decline cleanly. Stage 2 (replaying
  several requests) is not implemented.
- **Cost of the flag.** With the flag on, a recv comm makes one extra non-blocking `recv()` per
  `ncclIbTest`/`ncclIbIrecv`. A recovery can also busy-poll the CQ for at most
  `min(HANDSHAKE_MS/10, 100 ms)` on the proxy thread.
- **Peer FIN while idle.** A FIN from the peer while the comm is idle does not fail it, the
  same as stock. A dead peer therefore surfaces as RETRY_EXC (0x81, sub-cause from liveness).
- **Latched ops starve the ops behind them.** Once a comm is latched, its op returns an error
  on every progress call. `proxy.cc` `progressOps` stops at the first failing op, so ops behind
  it on that proxy thread are no longer progressed. This includes a local recv comm that would
  answer a peer's REQ, so that peer then fails through its own deadline instead of a NACK. The
  communicator is already in error at that point (stock sets `asyncResult` too), so the outcome
  is the same failure, reached by a slower path.
- **ERR→RESET drain is mlx5-verified only.** It relies on the device writing no further CQE for
  a QP after `modify_qp(RESET)` returns, which holds on mlx5. The post-RESET drain handles
  CQEs a provider *leaves* in the CQ, not CQEs written afterwards. Even in that case, the
  recovered receive's own WQE has already produced its CQE before RESET, so a late CQE can only
  be an error CQE (dropped, or treated as a new fault that latches the comm). It is never a
  completion.

## Files

- `net_ib_fault_recovery.diff`: the patch. It applies to v2.23.4-1 after stripping the `#`
  banner.
- `DESIGN_recovery.md`: the design and the safety argument.
- `nccl_ar2.cu`: the 2-rank all-reduce driver, with exact whole-buffer checking on every rank.
- `logs/autorun_recovery_test.sh`: the 2-node validation (base / inject / symmetric /
  pipelined / prockill).
- `logs/historical/`: logs of superseded builds. They are not evidence for this patch.
