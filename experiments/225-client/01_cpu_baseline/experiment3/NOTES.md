# experiment3: 상세 기록

이 문서는 예전 README 본문을 그대로 옮긴 것이다(영문). 실행 방법도 여기에 있다. 요약은 [README.md](README.md)에 있다.

Measures the minimum cost of the recovery **action** itself — the
per-stage `ibv_modify_qp` latency to bring a broken RC QP from ERR
back to RTS — with coordination between the two endpoints.

Scope: scenario A (QP→ERR) only. Scenarios B and C (process kill,
link down) require full resource rebuild and are not representative
of minimum-action cost.

This is **not** comparable to Minder's "30 minutes manual diagnosis"
or Holmes's "30.3 s localization" — those include detection +
diagnosis + orchestration. Experiment 3 isolates the recovery
action's floor, on top of which production systems stack detection
and coordination overhead.

## Stages measured (per iteration)

| Stage              | What it measures                                      |
|--------------------|-------------------------------------------------------|
| detection          | t(first error CQE) − t(fault injected), est. via TCP RTT/2 |
| drain              | Draining remaining flush CQEs from the CQ             |
| T1                 | `ibv_modify_qp(ERR → RESET)`                          |
| T2                 | `ibv_modify_qp(RESET → INIT)`                         |
| coord1             | TCP send+recv barrier: both sides at INIT             |
| T3                 | `ibv_modify_qp(INIT → RTR)`                           |
| T4                 | `ibv_modify_qp(RTR → RTS)`                            |
| coord2             | TCP send+recv barrier: both sides at RTS              |
| T5                 | Post 1 signaled `RDMA_WRITE`, busy-poll for SUCCESS CQE |
| total_local        | T1 + T2 + T3 + T4 + T5                                |
| total_with_coord   | total_local + coord1 + coord2                         |

QP object is never destroyed between iterations. Same QPN, same MR,
same `remote_info` and `local_psn` reused for the full run.

## Build

```bash
make
```

Shares `common.h`, `rdma_common.c/h` with `experiment1/` via symlinks.
Adds `rdma_recovery.c/h` for per-stage transition helpers and
`common3.h` for recovery-coordination message types.

## Run

**Server (224, fault target, 10.0.0.3):**

```bash
./server -d mlx5_0 -i 1 -g 3 -p 18515 -o results/server_recovery.csv
```

**Client (225, observer, 10.0.0.2):**

```bash
./client -s 10.0.0.3 -d mlx5_0 -g 3 -n 100 -o results/recovery.csv
```

Or via orchestrator (requires SSH to server in `config.sh`):

```bash
./run_experiment.sh
```

## Analyze

```bash
python3 analyze.py results/recovery.csv --latex
```

## Protocol — recovery coordination

Both sides execute the ERR → RESET → INIT → RTR → RTS sequence in
parallel, but synchronize at two TCP points:

1. After INIT: both sides send+recv `MSG_RECOVERY_INIT_DONE` before
   entering INIT → RTR. Ensures neither side proceeds on a stale
   (pre-recovery) peer view.
2. After RTS: both sides send+recv `MSG_RECOVERY_RTS_DONE` before
   the client posts its T5 probe write. Guarantees the server's QP
   is in RTS (can receive) when the write arrives, so T5 measures
   transport latency only, not the server's state-transition tail.

`QPN`, `addr`, and `rkey` do not change across in-place recovery,
so no new `MSG_EXCHANGE_QP_INFO` is needed. `local_psn` is reused;
the hardware reset clears internal PSN counters and `modify(RTS)`
re-establishes them to the same value.

## CSV schema

`results/recovery.csv` (client):

```
iteration,
t_inject_request_ns, t_ack_ns, t_detected_ns, t_drain_done_ns,
t_reset_done_ns, t_init_done_ns, t_barrier1_ns,
t_rtr_done_ns, t_rts_done_ns, t_barrier2_ns, t_write_cqe_ns,
detection_ns, drain_ns, T1_ns, T2_ns, coord1_ns, T3_ns, T4_ns,
coord2_ns, T5_ns, total_local_ns, total_with_coord_ns,
detect_error_status
```

`results/server_recovery.csv` (server, if `-o` given):

```
iteration, t_inject_ns, drain_ns,
T1_ns, T2_ns, coord1_ns, T3_ns, T4_ns, coord2_ns
```
