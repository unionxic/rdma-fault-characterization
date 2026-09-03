# Experiment 2: CPU Polling Interval Blind Window

## What This Measures

Detection latency as a function of CPU polling interval. When the CPU is not
continuously polling the CQ (because it is busy with other work), faults go
undetected during the "blind window." This experiment quantifies the relationship:

```
detection_delay = max(HCA_retry_time, sleep_time)
```

- **sleep_time < HCA_retry_time (~3.7s):** CPU wakes before error CQE arrives.
  It must busy-poll until the HCA retry mechanism exhausts. Detection delay ~3.7s.
- **sleep_time > HCA_retry_time:** Error CQE is already in the CQ when CPU wakes.
  Detection delay ~ sleep_time. The blind window dominates.

This proves CPU-mediated detection has a hard floor of ~3.7s AND grows unboundedly
with CPU busyness.

## Parameters

| Parameter     | Values                                              |
|---------------|-----------------------------------------------------|
| Sleep (us)    | 0 (busy), 1000, 10000, 100000, 1000000, 5000000, 10000000 |
| Fault types   | (a) QP->ERR, (b) Process kill, (c) Link down        |
| Iterations    | 30 per combination                                   |
| Total         | 7 x 3 x 30 = 630 measurements                       |

## Dependencies

- Same as Experiment 1 (rdma-core, libibverbs-dev, librdmacm-dev)
- Experiment 1 server binary (`../experiment1/server`)
- Experiment 1 wrapper scripts (`server_loop.sh`, `server_link_loop.sh`)
- Python 3 for analysis

## How to Run

1. Edit `config.sh` with your environment (IPs, device names, SSH targets)
2. Build experiment1 server if not already: `make -C ../experiment1`
3. Build experiment2 client: `make`
4. Run: `./run_experiment.sh`

For manual testing of a single combination:
```bash
# On Server B:
cd ../experiment1 && ./server -d mlx5_0 -g 3

# On Server A:
./client -s 10.0.0.4 -T 1000000 -S a -n 30 -o results/test.csv
```

## File Structure

```
experiment2/
├── Makefile              # Builds client only
├── client.c              # Client with configurable sleep parameter
├── analyze.py            # Statistics + tables + LaTeX generation
├── run_experiment.sh     # Orchestration (drives all combinations)
├── config.sh             # Environment configuration
├── common.h -> ../experiment1/common.h
├── rdma_common.h -> ../experiment1/rdma_common.h
├── rdma_common.c -> ../experiment1/rdma_common.c
├── results/              # Output directory
└── README.md
```

## Hardware Environment (verified on)

- ConnectX-5, mlx5_0, RoCEv2, rdma-core 50.0
- QP config: timeout=14 (~67ms), retry_cnt=7
- Expected HCA retry time: ~3.7s (7 retries x exponential backoff)

## Output Format

CSV columns:
```
sleep_us, scenario, iteration,
t_inject_request_ns, t_ack_ns, tcp_rtt_ns,
t_wakeup_ns, t_detected_ns,
detection_delay_ns, wakeup_to_detection_ns,
error_status, vendor_err
```

Key derived columns:
- `detection_delay_ns`: t_detected - estimated_fault_time
- `wakeup_to_detection_ns`: t_detected - t_wakeup (time spent polling after sleep)

The `wakeup_to_detection` column is the key diagnostic:
- Large value (~3.7s): HCA retry still in progress when CPU woke (HCA-dominated)
- Near-zero: error CQE was already in CQ (sleep-dominated)

## Expected Results

| Sleep Interval | Detection Delay (ms) | Regime          |
|----------------|----------------------|-----------------|
| 0 (busy poll)  | ~3,700               | HCA-dominated   |
| 1 ms           | ~3,700               | HCA-dominated   |
| 10 ms          | ~3,700               | HCA-dominated   |
| 100 ms         | ~3,700               | HCA-dominated   |
| 1 s            | ~3,700               | HCA-dominated   |
| 5 s            | ~5,000               | Sleep-dominated |
| 10 s           | ~10,000              | Sleep-dominated |
