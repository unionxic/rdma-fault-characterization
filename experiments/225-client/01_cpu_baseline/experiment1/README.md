# Experiment 1: RDMA Fault Detection Latency Baseline

## What This Measures

This experiment measures the **latency from RDMA fault occurrence to error detection
via CPU-mediated CQ polling**. The goal is to empirically show that even in the best
case (tight `ibv_poll_cq` loop, no kernel transitions), CPU-mediated fault detection
has non-trivial latency that is problematic for GPU-initiated RDMA workloads.

### Fault Scenarios

| Scenario | Fault Type | What Happens |
|----------|-----------|--------------|
| A | `ibv_modify_qp` -> ERR | Remote QP forced to ERROR state; causes WR flush |
| B | Process kill (`exit`/SIGKILL) | Remote process abruptly terminated; QP resources freed by kernel |
| C | Link down (`ip link set down`) | Physical/logical link failure; retry exhaustion |

### What We Measure

For each scenario:
- **Detection latency** = time from fault injection to error CQE receipt at the initiator
- Error CQE status code (to characterize the error type per scenario)
- TCP control channel RTT (to validate timing methodology)

### Expected Results

Based on RDMA protocol behavior on ConnectX-5:
- **Scenario A (QP->ERR)**: Should be fastest. The HCA immediately flushes outstanding WRs.
  Expected: single-digit to tens of microseconds.
- **Scenario B (Process kill)**: OS must clean up the QP. The remote HCA detects the QP is
  gone when the next ACK/NAK exchange occurs. Expected: tens to hundreds of microseconds.
- **Scenario C (Link down)**: Slowest. The HCA retries the operation `retry_cnt` times with
  exponential backoff before reporting `IBV_WC_RETRY_EXC_ERR`. With `timeout=14` (67ms)
  and `retry_cnt=7`, this can take seconds. Expected: hundreds of milliseconds to seconds.

These results motivate GPU-side fault detection mechanisms that bypass the CPU polling path.

## Hardware Requirements

- Two servers connected via RoCE (RDMA over Converged Ethernet)
- Mellanox/NVIDIA ConnectX-5 or later NICs
- rdma-core 50.0+, libibverbs-dev, librdmacm-dev
- Verified firmware: 16.35.8002 (ConnectX-5)

## Dependencies

```
# Ubuntu/Debian
sudo apt install rdma-core libibverbs-dev librdmacm-dev build-essential python3

# Verify
ibv_devinfo    # Should show your NIC
ibstat         # Should show port state = Active
```

## Build

```bash
make            # Build client and server binaries
make debug      # Build with AddressSanitizer (for development)
make check-deps # Verify required libraries are installed
```

## Quick Start (Scenario A only)

### On Server B (the remote/target machine):
```bash
./server -d mlx5_0 -i 1 -g 3 -p 18515
```

### On Server A (the initiator/measurement machine):
```bash
./client -s <server_b_ip> -d mlx5_0 -i 1 -g 3 -p 18515 -n 100 -S a
```

## Full Automated Run

1. Copy `config.sh` and edit it:
   ```bash
   # Edit config.sh with your environment
   vi config.sh
   ```

2. Copy experiment1/ directory to Server B and build there too.

3. Run from Server A:
   ```bash
   ./run_experiment.sh
   ```

## Usage

### Client (Server A)
```
./client -s <server_ip> [-d <dev>] [-i <ib-port>] [-g <gid-index>]
         [-p <ctrl-port>] [-n <iterations>] [-o <output.csv>]
         [-S <scenarios>]

Options:
  -s, --server <ip>        Server B IP address (required)
  -d, --device <name>      IB device name (default: mlx5_0)
  -i, --ib-port <num>      IB port number (default: 1)
  -g, --gid-index <num>    GID index for RoCE (default: 3)
  -p, --port <num>         TCP control port (default: 18515)
  -n, --iterations <num>   Iterations per scenario (default: 100)
  -o, --output <file>      CSV output file
  -S, --scenarios <list>   Comma-separated: a,b,c
```

### Server (Server B)
```
./server [-d <dev>] [-i <ib-port>] [-g <gid-index>] [-p <ctrl-port>]
         [-I <nic-interface>]

Options:
  -d, --device <name>      IB device name (default: mlx5_0)
  -i, --ib-port <num>      IB port number (default: 1)
  -g, --gid-index <num>    GID index for RoCE (default: 3)
  -p, --port <num>         TCP control port (default: 18515)
  -I, --nic <iface>        NIC interface for link-down (default: enp1s0f0np0)
```

## Output Format

### CSV columns
```
scenario,iteration,t_inject_request_ns,t_ack_ns,tcp_rtt_ns,t_error_cqe_ns,detection_latency_ns,error_status,error_vendor_err
```

### Summary (printed to stdout)
```
Scenario A: QP -> ERR:     median=X.X us, mean=X.X us, p99=X.X us (N=100)
Scenario B: Process Kill:  median=X.X us, mean=X.X us, p99=X.X us (N=100)
Scenario C: Link Down:     median=X.X us, mean=X.X us, p99=X.X us (N=100)
```

## Analysis

```bash
python3 analyze.py results/detection_latency_*.csv
python3 analyze.py results/detection_latency_*.csv --plot  # Generate histogram data
```

The analysis script outputs:
- Summary statistics table
- LaTeX table (copy-paste into paper)
- Error status code distribution per scenario
- TCP RTT statistics (timing methodology validation)

## Notes

### Root privileges
- Scenario C (link down) requires root on Server B to run `ip link set down/up`
- Scenarios A and B do not require root

### GID index
The default GID index (3) is typical for RoCEv2 on mlx5 devices but may vary.
Check your GID table:
```bash
# Method 1: show_gids script (if available)
show_gids

# Method 2: sysfs
for i in /sys/class/infiniband/mlx5_0/ports/1/gids/*; do
  echo "$(basename $i): $(cat $i)"
done
```

Use the GID index that corresponds to your RoCE interface IP.

### Timing methodology
Detection latency is estimated as:
```
tcp_one_way = (t_ack - t_inject_request) / 2
t_fault_estimated = t_inject_request + tcp_one_way
detection_latency = t_error_cqe - t_fault_estimated
```

This assumes symmetric TCP latency. For sub-microsecond precision,
use PTP-synchronized clocks and compare timestamps directly.

### QP timeout configuration
The QP is configured with `timeout=14` (~67ms per retry) and `retry_cnt=7`.
This directly affects Scenario C results. These are typical production values;
adjust in `rdma_common.c` if you want to characterize different timeout settings.
