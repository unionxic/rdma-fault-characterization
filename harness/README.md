# Unified RDMA fault harness

One requester/responder pair that replaces the scattered experiments 01–09 with a
single instrument. It injects a selectable RDMA fault, measures how fast the
requester detects it, classifies it from the CQE alone, recovers the QP, and
verifies the connection — all into one CSV schema.

```
rain  (requester, mlx5_1, 30.0.0.3)  --RoCEv2 100G-->  sunny (responder, mlx5_0, 30.0.0.4)
   probe_client  ----------------- TCP control (18580, TCP_NODELAY) -----------------  probe_server
```

## What it measures (per fault, per trial, one CSV row)

| column | meaning |
|---|---|
| `detect_ns` | inject → first error CQE (CLOCK_MONOTONIC_RAW tight poll) |
| `status` / `status_name` / `vendor_err` | the CQE fingerprint — the paper's classification key |
| `cause` / `action` / `peer_alive` / `auto_recoverable` | `classify(status,vendor_err)` output |
| `recover_ns` | coordinated QP recovery latency (both ends), then a verified round-trip |
| `verify_ok` | 1 if a post-recovery WRITE+READ-back matched |
| `bytes_landed` / `sq_psn_delta` / `mtu_bytes` | partial-write byte accounting (`bytes == sq_psn_delta × PMTU`) |
| `counter` / `cnt_delta` | a chosen `hw_counter` delta across the trial (diagnosis / early detection) |
| `sub_cause` / `peer_rx_delta` | counter-based split of the ambiguous RETRY_EXC (0x81): server_qp_err vs proc_kill vs link_down |

### Sub-classification of RETRY_EXC (0x81)

The CQE fingerprint RETRY_EXC (12 / 0x81) is ambiguous: a responder QP that went to
ERR, a dead responder process, and a downed link all produce it. The harness splits
it with signals outside the CQE:

1. **requester port state** — not ACTIVE ⇒ `link_down`.
2. **peer liveness** on the control channel (which rides the mgmt IP) — a PROBE that
   gets a reply ⇒ node up, QP broken ⇒ `server_qp_err` (auto-recoverable); no reply
   (dead connection) ⇒ `proc_kill` (process dead, human intervention).

**Liveness is the discriminator, not an RDMA counter** — see `VERIFICATION_0x81.md`.
The verification measured the responder's fault-window RDMA port deltas and found they
do **not** separate the two causes: `port_rcv_packets` ≈ 40–52 for both (retransmits
reach the NIC regardless of QP existence), and `port_xmit_packets` = 0 for both (a QP
in ERR does not NAK; a dead process cannot transmit). This matches the repo docs, which
split the pair via the TCP sideband (FIN vs RST) — the same process-liveness signal the
PROBE uses. The reported `peer_rx_delta` / `peer_tx_delta` are diagnostics, not the
decision input. (An earlier version wrongly used peer_rx as the discriminator.)

## Fault catalog (`-f`)

| fault | trigger | expected fingerprint (ConnectX-6 Dx, fw 20.43.4100) |
|---|---|---|
| `local_qp_err` | deep write burst, then force own QP→ERR | WR_FLUSH_ERR (5) / 0xf5 |
| `rem_inv_req` | atomic to a responder QP that doesn't enable atomics | REM_INV_REQ_ERR (9) / 0x8a |
| `rem_access` | write past the end of the remote MR | REM_ACCESS_ERR (10) / 0x88 |
| `rnr` | SEND with no remote recv WQE (finite rnr_retry) | RNR_RETRY_EXC_ERR (13) / 0x87 |
| `retry_server_qp_err` | responder QP→ERR, stops ACKing | RETRY_EXC_ERR (12) / 0x81, ~3.7 s firmware floor |
| `partial_write` | large multi-packet write, force ERR mid-transfer | WR_FLUSH_ERR (5) / 0xf5, partial bytes |
| `retry_proc_kill` | responder process exits (runner restarts per trial) | RETRY_EXC_ERR (12) / 0x81 |
| `retry_link_down` | responder link down (needs root; runner-driven) | RETRY_EXC_ERR (12) / 0x81 |

Recovery (`-r`): `qp_only` (ERR→RESET→INIT→RTR→RTS, coordinated both ends, fresh PSN),
`full_rebuild` (destroy + recreate the QP), or `none`.

## Build & run

```bash
make                       # builds probe_client + probe_server (both nodes)
./run.sh                   # runs the default fault set from config.sh, then analyze.py
CLIENT_CPU=2 SERVER_CPU=2 ITERS=30 ./run.sh                 # pinned, 30 trials
FAULTS="rnr rem_access" RECOVERY=full_rebuild ./run.sh      # subset + method
```

All environment lives in `config.sh` (server IP/ssh/device, client device, GID index,
port, iterations, CPU pinning, counter). Client and server take independent `-d`
because their active devices differ (client `mlx5_1`, server `mlx5_0`).

Manual invocation:
```bash
# responder (on sunny)
./probe_server -d mlx5_0 -i 1 -g 3 -p 18580
# requester (on rain)
./probe_client -s 30.0.0.4 -d mlx5_1 -i 1 -g 3 -p 18580 -f rnr -r qp_only -n 30 -o results/rnr.csv
```

## Reproduced results (N=30, pinned, 2026-09-15, this cluster)

| fault | status / vendor | detect (mean ± CI95) | QP-only recover | verify |
|---|---|---:|---:|---:|
| local_qp_err | WR_FLUSH / 0xf5 | 308 µs ± 19 µs | 1.37 ms | 30/30 |
| partial_write | WR_FLUSH / 0xf5 | 370 µs ± 11 µs | 1.18 ms | 30/30 |
| rem_inv_req | REM_INV_REQ / 0x8a | 530 µs ± 181 µs | 1.35 ms | 30/30 |
| rem_access | REM_ACCESS / 0x88 | 625 µs ± 182 µs | 0.97 ms | 30/30 |
| rnr | RNR_RETRY_EXC / 0x87 | 12.64 ms ± 81 µs | 1.33 ms | 30/30 |
| retry_server_qp_err | RETRY_EXC / 0x81 | **3.750 s** ± 344 µs | 1.58 ms | 30/30 |

- All six faults are uniquely identified by (status, vendor_err) — the paper's fingerprint, one tool.
- `partial_write`: `bytes_landed == sq_psn_delta × 1024 B` held on all 30 trials (bytes landed 1.04–1.18 MB).
- `retry_server_qp_err` reproduces the ~3.7 s firmware detection floor (min_ack_timeout_limit) on ConnectX-6 Dx.
- Recovery method matters: full_rebuild ≈ 1.8–2× the QP-only latency (local_qp_err 2.49 ms vs 1.37 ms).

## Design notes

- TCP_NODELAY on every control socket (both connect and accepted sides) — avoids the
  ~40 ms delayed-ACK artifact that contaminated the old A/B recovery numbers.
- Manual RC QP setup (no rdmacm) for full control of state transitions.
- Full error checking on every verbs/socket call; clean teardown; `-Wall -Wextra -Werror`.
- CLOCK_MONOTONIC_RAW timing; optional CPU pinning for latency stability.
- `rnr_retry=6` (7 means retry-forever, which never exhausts).
- Not covered here (separate subsystem): the NVMe-oF Storage×RDMA boundary lives in
  `experiments/*/10_storage_rdma`.
```
