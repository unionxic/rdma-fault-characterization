# perf: 상세 기록

이 문서는 예전 README 본문을 그대로 옮긴 상세 기록이다(영문). 요약은 [README.md](README.md)에 있다.

**2026-10-06 리뷰 정정** (`harness/gpu-initiated/propagation/review_20261006/nccl_netib_design.md`)
- 본문은 78f96f38을 "the final build"라 부른다. 최종 빌드는 a037de42다. 측정한 Stage 2 빌드는 3b0b760d이고, 그 뒤 변경은 상대 생존 판정 규칙만 바꿨다.

**2026-10-06 README 정리 때 CSV와 로그로 다시 센 정정**
- 주입 장애 표 첫 행의 "300 × 256 KB"는 Stage 2에만 맞다. Stage 1 작업은 200 × 256 KB였다(CSV와 로그 모두 200회). 오류는 Stage 1이 반복 95, Stage 2가 반복 96에서 올라왔고, restart는 반복 94와 95부터 다시 시작했다.
- 오버헤드 표의 "each the median of 400 iterations"는 64 KB와 1 MB에만 맞다. 실행 하나의 반복 수는 16 MB가 25회, 64 MB가 20회다(CSV 기준).
- "0.8–0.9 s per rank"는 rain rank에만 맞다(0.79~0.88 s). sunny rank는 실행부터 통신 준비까지 0.31~0.39 s였다. comm 초기화 0.16~0.23 s도 rain 값이다(sunny 0.16~0.26 s).
- Stage 1 default 행의 restart 증가분은 중앙값끼리 빼면 +1.18 s다(2.596 − 1.412). "+1.19 s"는 반올림한 값끼리 뺀 것으로 보인다.
- Stage 1 default의 recover는 "killed at 21.6 s"가 아니다. abort가 돌아오지 않아 시험 프로그램의 20 s 감시 시간 뒤 스스로 끝났다.
- "restart (stock)"과 baseline은 원본 바이너리가 아니다. 같은 패치 라이브러리에서 플래그를 끈 것이다. 원본 빌드는 오버헤드 비교에만 썼다.

Same 2-rank job, run three ways, and the wall time of the whole job compared:

- **baseline**: no fault.
- **recover**: one fault, recovery flag on. The library repairs the connection in place and the job
  keeps going.
- **restart**: the same fault with the flag off, i.e. the stock error path. As soon as either rank
  prints the error, the runner kills both ranks and relaunches the job from the failed iteration.
  That assumes a checkpoint after every iteration, which is the best case for restart; a real
  job would also lose the work since its last checkpoint.

Every run checks every iteration's whole result buffer on both ranks, on the GPU, bit for bit.

| file | what |
|---|---|
| `nccl_ct.cu` | the job. NCCL all-reduce (or broadcast) loop with GPU fill and check kernels, per-iteration time, comm init and ready times. `--start k` resumes at iteration k; the data for iteration k is a function of k, so a relaunched job produces the same bytes. |
| `ctlib.py` | launches the pair (rain: `mlx5_1`, sunny: `mlx5_0`, OOB on `eno1`) with a given library build and returns both ranks' summaries |
| `completion_time.py` | `smoke`, `overhead`, `fault` (fault = `inject` test hook or `gbh:<s>`, the address-flap fault of `../stage2/gid_blackhole.sh`) |
| `summarize.py` | the tables below, from the CSVs |
| `results/20260925/` | CSVs, raw logs (`logs.tar.gz`; the address-flap archive is thinned), runner consoles |

Builds: `stock` (NCCL v2.23.4-1), `stage1i` (Stage 1 patch, `../DESIGN_recovery.md`), `stage2f`
(Stage 2 patch, `../stage2/`; library md5 `3b0b760d`, the same recovery code as the final build
`78f96f38`, which only adds the FIN rule for dead peers). Configs: **single** = 1 channel, Ring,
Simple, 1 QP per connection (the only case Stage 1 handles); **default** = NCCL's own choice, which on
this pair is 2 channels, pipelined, several requests in flight per connection.

## Results (2026-09-25, rain ↔ sunny, ConnectX-6 VPI, RoCE v2)

### A fault the library sees immediately (test hook forces the connection QP to ERR)

Wall times are medians, from launch until both ranks exit. For restart, the wall time is the sum of
the two segments (killed job + relaunched job). The runner's own cleanup between the segments
(`pkill`, then 1 s of sleep) is not counted; with it, the runner-level wall time is about 4.9–5.0 s
(the `runner_wall_s` column).

| job | build | baseline | recover | restart | recovery itself |
|---|---|---|---|---|---|
| 300 × 256 KB, single, fault at iteration ~95 (n = 5) | Stage 1 | 1.44 s | **1.44 s**, 5/5 | 2.54 s (+1.10 s) | 1.81 ms (1.78–2.21) |
| same | Stage 2 | 1.45 s | **1.45 s**, 5/5 | 2.51 s (+1.07 s) | 2.26 ms (2.21–2.35) |
| 100 × 16 MB, default, fault at iteration 13 (n = 3 / 5) | Stage 1 | 1.41 s | **0/3**: declined (several requests in flight), then NCCL's abort hang; killed at 21.6 s | 2.60 s (+1.19 s) | - |
| same | Stage 2 | 1.41 s | **1.42 s**, 5/5 | 2.55 s (+1.14 s) | 2.31 ms (2.29–2.33) |

- Restart costs **about 1.1 s** on top of the baseline, even with a checkpoint after every iteration
  and a relaunch the instant the error appears. Nearly all of it is the relaunched processes getting
  ready again: 0.8–0.9 s per rank from launch until the communicator is ready. Comm init alone is
  0.16–0.23 s; the rest is CUDA context creation, the bootstrap, and the first collective's lazy
  connection setup.
- In-place recovery costs about 2 ms, which is inside the run-to-run noise of the whole job.
- With these short jobs the ratio is large (+75 % vs +0.1 %), but the absolute gap is about one
  second per fault. A real restart pays more: the launcher's detection and scheduling delay, the
  checkpoint load, and the work since the last checkpoint. None of those is modeled here.

### A real path fault with NCCL's default IB timeout (address flap, `gbh:0.5`)

sunny's secondary RoCE address is removed for 0.5 s, 3 s into a 3000 × 16 MB default-config job, and
added back. The address comes back at a new GID index, so every QP on the old index is dead for good.
NCCL's default `NCCL_IB_TIMEOUT=20` / `IB_RETRY_CNT=7` applies (n = 3).

| mode | wall (median, range) | what happens |
|---|---|---|
| baseline | 8.45 s (8.45–10.5) | - |
| recover (Stage 2) | **67.96 s** (66.5–69.0), 3/3 correct | the job stalls for 56–60 s (longest gap between iterations) until the NICs give up with RETRY_EXC on the connections; each recovers in 2.5–4.8 ms (per-connection totals, send side) |
| restart (stock) | 68.28 s (67.8–69.8) | the same ~58 s wait for RETRY_EXC, then kill + relaunch; the relaunched segment (≈2,540 iterations) takes 7.4 s |

- Here **detection dominates both paths**: with the default timeout the NIC retries for about a minute
  before it reports anything, and neither recovery nor restart can start earlier. Recovery and restart
  differ by 0.3 s at the median, less than the run-to-run spread of the detection time (56–60 s). In
  this setting recovery does not buy completion time; it buys not needing a checkpoint and a launcher.
- `../stage2` runs the same fault class with `NCCL_IB_TIMEOUT=14`. There RETRY_EXC comes after about
  3 s and recovery takes 2.6 ms. `../../ack_timeout/` measures how the RETRY_EXC time depends on the
  timeout on this NIC, including the firmware's minimum ACK-timeout floor.

### Fault-free overhead (median of 3 runs, each the median of 400 iterations)

| message | single: Stage 1 flag on | single: Stage 2 flag on | default: Stage 1 flag on | default: Stage 2 flag on |
|---|---|---|---|---|
| 64 KB | +2.7 % | +0.7 % | +1.1 % | +0.6 % |
| 1 MB | +0.5 % | −0.2 % | +1.4 % | +0.1 % |
| 16 MB | +1.8 % | +0.6 % | +0.4 % | −0.1 % |
| 64 MB | −0.0 % | +0.4 % | −0.2 % | +0.1 % |

With the flag off, both patches are within ±0.6 % of stock. Stage 2's flag-on cost is lower than
Stage 1's because it checks the peer's socket only every 100 µs.

## Limits

- One pair of nodes, one job shape per row, 3–5 repetitions: the rows show the size of the effect,
  not a distribution.
- "restart" is optimistic. It detects the error from the first log line (a real job waits for its
  own timeout or its launcher) and it loses no work.
- The injected fault is detected in microseconds. A real fault is detected when the NIC gives up,
  which is the IB timeout, as the address-flap row shows.
