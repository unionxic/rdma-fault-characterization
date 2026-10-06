# transparent_probe: 상세 기록

이 문서는 예전 README 본문을 그대로 옮긴 상세 기록이다(영문). 요약은 [README.md](README.md)에 있다.

**2026-10-06 리뷰 정정** (`harness/gpu-initiated/propagation/review_20261006/nccl_netib_design.md`)
- 응답 쪽 PSN 비교 28/28 가운데 burst 중간에 놓인 점은 ra_s4 하나뿐이다. ERR 점은 모두 prefix 0–3이나 256이라, 응답 QP를 메시지 중간에 ERR로 만든 적은 없다.
- 장애를 넣은 20회(run1과 run2의 ra, rb) 모두에서 요청 쪽 자신의 next_send_psn도 응답 쪽 next_rcv_psn과 같았다(원시 로그에만 있음). 그래서 이 probe는 응답 쪽 값이 요청 쪽 완료 수(223 대 234)보다 낫다는 것까지만 보였다. 요청 쪽 QP 상태보다 낫다는 것은 보이지 못했다.
- exactly-once 재전송 질문의 "hundreds of ops in flight"에 대한 exactly-once 근거는 재전송이 있었던 1회(22개)뿐이다. 유효한 Mode B 재전송은 0회다. 설계 문서 §6.2도 같은 과장이 있다. `../RESULTS.md`는 "next_rcv_psn = executed prefix"를 조건 없이 적는데, burst 중간 점은 1개뿐이다.
- 중복 창 "16 이상 64 미만"은 깊이마다 1회 결과다. max_rd_atomic과의 관계는 추정이다. 깊이 4의 되감기에는 atomic이 없었다(깊이 4, 16, 64, 200에서 0, 3, 13, 34개).
- 원시 로그 재집계: 응답 쪽 QUERY_QP 시간은 28점에서 57.8–83.5 µs다. 설계 문서 §11.1의 "60–84 µs"는 run2만의 범위다(run1 rb_s1이 57.8 µs).
- 아래 본문의 Files 표가 가리키는 `results/run1`, `results/run2`는 저장소에 없다. 로그는 Release `data-20261006`에 있다.

Supports `../TRANSPARENT_RECOVERY_DESIGN.md`. CPU-only mlx5 DEVX, one RC QP pair
(requester = rain `mlx5_1`, responder = sunny `mlx5_0`), so it needs no GPU and runs quickly, yet
it reproduces the WQE/PSN/CQ mechanics the GPU libraries depend on: RDMA WRITE (one SGE, 64 B to
7·MTU), 8-byte ATOMIC FETCH_ADD (one distinct counter per atomic), RDMA READ; a 64-byte **ring**
CQ; every WQE signaled; the SQ doorbell record's **send** word (word 1) written — the correct word,
so it does not hit the CPU-proxy `nvshmem_rootcause` bug. It answers the four feasibility questions
the design turns on:

| name | question | scenario | key output field |
|---|---|---|---|
| PSN authority | Does the responder's `QUERY_QP.next_rcv_psn` equal the executed prefix (ground truth = responder memory), after the responder QP → ERR, and while it stays RTS and only the requester errs? | `resp_err`, `req_err` | `Q1_MATCH`, `prefix_from_psn`, `mem_prefix` |
| exactly-once replay | With that PSN, is "reset + replay whole requests from the first unexecuted one" exactly-once for hundreds of ops in flight? Mode B (both reset) and Mode A (responder untouched). | `resp_err` (B), `req_err` (A) | `EXACTLY_ONCE`, `fadd_multi`, `notlanded`, `corrupt` |
| duplicate absorption | If the requester alone rewinds its PSN into already-executed requests, are duplicate atomics re-executed or absorbed, and at what rewind depth does the responder NAK? | `dup` (depth sweep) | `fadd_multi`, `duperr`, `poll_rc` |
| WQE index | After `2RST`, does the NIC take the WQE ctrl index field or its own restarted counter, and what `wqe_counter` does the CQE carry? | `wqeidx` | per-CQE `wqe_counter`, `landed` |

Exactly-once is checked end to end: the responder holds the deterministic plan and, from its own
memory, reports how many WRITEs landed (byte-for-byte vs the pattern), how many FETCH_ADD counters
are 0 / exactly 1 / >1, and its `next_rcv_psn`/`rmsn` from `QUERY_QP`. The requester verifies READ
data locally. A recovery is a success only if every write landed, every atomic counter is exactly
1, no counter is >1 (`fadd_multi==0`), and every read verified.

## Ground truth and why it is trustworthy

- WRITE landing: the requester's source buffer is filled with a seeded 64-bit pattern
  `pat(seed_w, offset)`; the responder pre-fills its buffer with a different background pattern.
  After execution the responder reads each write's target region and reports landed / not-landed /
  corrupt (partial). Offsets are distinct per request, so a landed write is unambiguous.
- FETCH_ADD: each atomic targets a distinct 8-byte counter (initialised 0), `swap_add=1`, so the
  counter value is the execution count — 1 = exactly-once, 2 = double-executed (a replay bug).
- Executed prefix from memory (`mem_prefix`): RC executes in order, so the executed set is a prefix;
  `mem_prefix` is the last executed write/atomic + 1. `prefix_from_psn` is computed independently
  from `next_rcv_psn` and the per-request PSN table. `Q1_MATCH = (they agree)`. For the
  PSN-authority and exactly-once checks the plan excludes READs by default (`--reads 0`) so the
  memory prefix is exact; `dup` includes READs (`--reads 1`).

## Build and run

```
make                         # builds tr_probe here (also built on sunny by run_probe.sh)
# every RoCE run goes through the shared lock:
../common/cluster_run.sh -w 7200 -t tr-matrix -- timeout 560 bash run_matrix.sh run3   # -> results/run3
# or one scenario:
../common/cluster_run.sh -t tr-one -- bash run_probe.sh tag $PWD/results/one resp_err
```

`run_probe.sh <tag> <outdir> <scen> [-- extra]` builds the binary on sunny (its own OFED),
resolves both RoCE v2 IPv4 GIDs, starts the responder on sunny and the requester on rain, and
prints the requester's `SUMMARY` line. Env: `SEED K RECOVER DELAY_MAX_US DUP_DEPTH READS
ACK_TIMEOUT PORT`. Each process self-bounds with `alarm`; only its own binary (`pkill -x tr_probe`)
is ever killed. Logs: `<outdir>/<tag>.{req,tgt}.log`.

`run_matrix.sh` runs the whole feasibility matrix in one bounded hold (< 10 min): 5 seeds each of
`resp_err` (Mode B) and `req_err` (Mode A) with recovery, a `dup` depth sweep (4/16/64/200), and
`wqeidx`.

## Files

| file | what |
|---|---|
| `tr_probe.c` | the probe (requester + responder in one binary) |
| `tr_prm.h` | mlx5 PRM layouts (copied from `../nvshmem_rootcause/nrc_prm.h`, + 2RST_QP) |
| `run_probe.sh` | one trial across rain+sunny (inside `cluster_run.sh`) |
| `run_matrix.sh` | the feasibility matrix in one hold |
| `results/run1` | first run: **invalid for exactly-once** (inline WQEs built with `ds=0`; replay poll without a CQ drain); its 14 PSN-authority lines are valid |
| `results/run2` | corrected binary, 15 trials; the figures in `../TRANSPARENT_RECOVERY_DESIGN.md` §11.1 |

## Results (run2, see the design doc §11.1 for the full table)

- PSN authority: `next_rcv_psn` (and `rmsn`) equalled the memory prefix in 28/28 data points (run1
  14 + run2 14; responder in ERR 10, in RTS 18). READs count `ceil(bytes/MTU)` PSNs (psn0 0x100 +
  627 = 0x373 with 46 READs).
- Exactly-once replay: 10/10 run2 recoveries were exactly-once, but only 1 (Mode A, ra_s4) had a
  non-empty replay: 22 requests incl. a partly received WRITE (3 duplicate packets absorbed); 11
  requests were executed but unacked and correctly not re-sent. No Mode B trial had anything to
  replay. The fault landed after the burst in 9/10: the next run must inject earlier, N >= 30.
- Duplicate absorption: rewind 4 and 16 requests absorbed; 64 and 200 end in RETRY_EXC; no counter >
  1 at any depth.
- WQE index: CQE `wqe_counter` is the NIC's own counter (0..3 for index fields 1000..1003); fresh QP
  only.

## Scope / limitations

- CPU DEVX QPs, not the GPU libraries' QPs: it reproduces the QPC/CQ/WQE/PSN mechanics and the
  `2RST`+replay path, not the device-side pause gate or the block-across-recovery wait (those are
  GPU-only and are staged in the design from step 1 on). It establishes the transport-level
  feasibility the design rests on (the PSN authority, exactly-once replay, the duplicate window, the
  index-field behaviour), not the device control-flow.
- One QP pair; multi-QP is step 3 of the design. One firmware (20.43.4100), RoCE v2, ack timeout 14.
- `dup` does not overwrite WRITE targets before the rewind, so it cannot tell whether duplicate
  WRITEs are executed again; `wqeidx` runs on a fresh QP, not after a 2RST.
- The inline-WRITE builder (`OP_WINL`) is kept in the source but never generated (it computed `ds`
  wrong in run1).
- READ-result verification uses the replay-pass offset; READs are enabled only in `dup` (where they
  are not result-verified), so this does not affect the PSN-authority and exactly-once checks.
