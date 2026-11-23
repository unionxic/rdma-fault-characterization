# experiment4: 상세 기록

이 문서는 예전 README 본문을 그대로 옮긴 것이다(영문). 실행 방법도 여기에 있다. 요약은 [README.md](README.md)에 있다.

Characterizes the parameter regimes where ConnectX-5 hardware retry
masks transient packet loss versus where the retry budget is
exhausted and the application sees a hard failure.

## Sweep

- `retry_cnt` ∈ {0, 1, 3, 7}
- `qp_timeout` ∈ {8, 12, 14, 17, 20} → 4.096 µs · 2ˣ:
  | x  | t       |
  |----|---------|
  | 8  | 1.05 ms |
  | 12 | 16.8 ms |
  | 14 | 67.1 ms |
  | 17 | 537 ms  |
  | 20 | 4.30 s  |
- Transient (`tc netem loss`): {1%, 5%, 10%, 50%}
- Persistent: process kill (Server B exits abruptly)

## Required setup

- **Local sudo (client side)** — `tc qdisc add/del netem` is run from
  `run_experiment.sh`. Configure passwordless sudo for `tc`, or keep
  a sudo session warm before launching.
- **Remote SSH to Server B** for kill phase (uses
  `experiment1/server_loop.sh`).
- **`experiment1/server` built** on the remote — used as a passive
  write target during transient/baseline phases and via `server_loop.sh`
  during the kill phase.

## Build

```bash
make
```

Reuses experiment1's `common.h`, `rdma_common.c/h` via symlinks. No
changes to shared code; the parametrized RTR→RTS modify lives in
`client.c::connect_qp_custom()`.

## Run

Configure `config.sh` first (especially `SERVER_SSH`, `SERVER_BIN_DIR`,
`NIC_IFACE`).

Full sweep:
```bash
./run_experiment.sh
```

Subset:
```bash
PHASE=baseline ./run_experiment.sh   # 20 configs, no fault
PHASE=netem    ./run_experiment.sh   # 80 configs (4 loss × 20)
PHASE=kill     ./run_experiment.sh   # 20 configs
```

Results are appended to `results/exp4_<TIMESTAMP>.csv` (one row per
configuration, aggregated across all writes / iterations).

## CSV schema

```
mode, retry_cnt, qp_timeout, rnr_retry, loss_pct,
n_attempted, n_observed, n_ok,
n_retry_exc, n_rnr_retry_exc, n_wr_flush, n_other,
mean_us, p50_us, p99_us, min_us, max_us
```

For `mode=kill`, `n_ok` = number of iterations where the client
observed an error CQE within `WRITE_TIMEOUT_SEC`; `mean/p50/p99_us`
report detection latency. `n_retry_exc` etc. are simultaneously
counted (each kill produces both an `ok` latency entry and an error
code).

For `mode=netem`, `n_ok` = number of writes that completed with
`IBV_WC_SUCCESS`; the error counters partition the failed writes
by status. After the first error the QP enters ERR; remaining writes
in the run flush, so you typically see at most one error code per
configuration.

## Analyze

```bash
python3 analyze.py results/exp4_<TS>.csv
python3 analyze.py results/exp4_<TS>.csv --breakdown   # full per-row dump
```

## Mental model for the result

- **retry_cnt=0**: HCA does not retry at all. Even tiny loss → hard
  failure. Persistent fault detected as fast as `qp_timeout` lets it.
- **retry_cnt=7 with small qp_timeout** (e.g., 8): retry budget cycles
  fast; can mask high loss rates within tight latency bounds.
- **retry_cnt=7 with large qp_timeout** (e.g., 20): same retry budget
  but each retry waits seconds; total recovery for persistent faults
  approaches *minutes* — this is the regime where production
  deployments are quietly losing throughput.

This experiment maps the boundary so the paper can argue concretely:
"current default (retry_cnt=7, timeout=14) is a 3.7s-blind-window
trade-off. Lowering timeout exposes you to transient loss; raising
it makes persistent faults invisible for seconds." GPU-initiated
recovery sidesteps both edges by detecting and reacting in software
without depending on transport-level retry as the failure detector.
