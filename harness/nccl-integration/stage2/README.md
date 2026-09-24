# Stage 2: in-tree NCCL recovery with many requests in flight

NCCL v2.23.4-1, `src/transport/net_ib.cc` only, behind `NCCL_RDMA_FAULT_RECOVERY=1`.
Design and the two QA rounds: [DESIGN_stage2.md](DESIGN_stage2.md). Patch: [net_ib_stage2.diff](net_ib_stage2.diff).
Everything is inside the library: detection, classification, the handshake with the peer (over the
comm's own OOB socket), the drain, reconciliation, QP re-drive, replay, and a helper thread that
serves comms NCCL is not calling. The test program (`../perf/nccl_ct.cu`) only runs all-reduces and
checks every result buffer bit-exactly; the runner (`run_tests.py`) only launches and judges.

## What it does (one paragraph)

When the connection QP of a send comm S or recv comm R fails (WR_FLUSH, or RETRY_EXC with the peer
alive), both sides drain their QP the way `ib_drain_qp` does (ERR + a marker WR whose flush CQE
proves every earlier WR was accounted for). R computes `R_done`, the last receive that completed
(completed receives are a prefix, because one RC QP executes S's groups in FIFO order), re-drives
its QP with a fresh PSN, re-posts every pending receive and ACKs. S completes the groups R already
had, re-drives its QP, replays the groups R did not get, in FIFO order, and sends DONE; R then
rewrites the CTS entries S may lack. Either side may detect first (R sends NOTIFY; S always leads).
The local GID is looked up again by value at every re-drive, because an address that comes back
gets a new GID index.

## Results (2026-09-25; 2 nodes, ConnectX-6 VPI, RoCE v2, IB timeout 14; every run checks every iteration's whole result buffer on both ranks)

Raw data: `results/20260925/<campaign>/` (`results.csv`, `logs.tar.gz`, hardware counters before/after,
`lib_md5.txt`). The larger log archives are thinned by `../perf/thin_logs.py`: every NCCL, recovery,
error and SUMMARY line is kept. Of the per-iteration `IT` lines it keeps the first and last 20, every
1000th, and 5 on each side of every stall, so the fault and recovery timelines are intact. Library builds: `f7f45278` (after code QA round 2), `3b0b760d` (+ test-hook fix),
`78f96f38` (+ the FIN rule, §7; final; `net_ib_stage2.diff` is this build's source). The later changes
do not touch the paths the first campaigns exercise, and campaigns A2/A3 re-ran the core cases on
the final build (rows marked "final build").

| case | what happens | build | N | result | recovery time (median, range) |
|---|---|---|---|---|---|
| T0s / T0d | no fault, flag on (single / default config) | f7f45278 | 10 / 10 | 20/20 pass | - |
| T1 | send QP forced to ERR (256 KB, 1 channel) | f7f45278 | 30 | **30/30 recovered** | 2.22 ms (2.14–2.34) |
| T2 | same, **default config** (2 channels, pipelined, 16 MB) — Stage 1 declined this 3/3 | f7f45278 | 30 | **30/30 recovered** | 2.26 ms (2.22–2.35) |
| T3 | recv QP forced to ERR, default config (R detects, NOTIFY) | f7f45278 | 30 | **30/30 recovered** | 2.15 ms (2.11–2.27) |
| T3s | same, single config | f7f45278 | 10 | 10/10 recovered | 2.07 ms (2.05–2.13) |
| T5 | 5 faults per run, default config | f7f45278 | 10 | 10/10 runs, **50/50 recoveries** | 2.14 ms (2.05–2.40) |
| T6 | both ranks inject at once (both directions) | f7f45278 | 10 | 10/10 runs, 20/20 recoveries, no deadlock | 2.34 ms (2.23–2.40) |
| T1 / T2 / T3, final build | as above | 78f96f38 | 10 / 10 / 10 | **30/30 recovered** | 2.22 / 2.24 / 2.14 ms (2.10–2.37) |
| T5 / T6 / T0d, final build | as above | 78f96f38 | 5 / 5 / 5 | 5/5 runs, 25/25 recoveries; 5/5 runs, 10/10 recoveries; 5/5 pass | 2.15 ms (2.07–2.41); 2.29 ms (2.25–2.36) |
| T1b | send inject, one-way broadcast stream | 78f96f38 | 10 | 10/10 recovered | 2.22 ms (2.14–2.46) |
| **T7a** | **real path fault: sunny's RoCE address removed 0.5 s** (packets lost; both NICs exhaust retries → RETRY_EXC; the address comes back at a new GID index) | 78f96f38 | 5 | **5/5 recovered** (4 connections each, 15,000/15,000 iterations exact) | 2.64 ms (2.00–4.11) after RETRY_EXC |
| **T7b** | same, 6 s outage | 78f96f38 | 5 | **5/5 recovered** | 3.26 s (waits for the address, 2.26–3.27 s) |
| **T7c** | same, 15 s outage | 78f96f38 | 5 | **5/5 recovered** | 12.27 s (waits for the address) |
| T7a/T7b stock control | same faults, recovery off | 78f96f38 | 3 / 3 | **6/6 fail** (RETRY_EXC 12/0x81 at iteration ~443, then NCCL 2.23's abort hang) | - |
| T8 | rank 1 SIGKILLed while rank 0 waits to receive | 78f96f38 | 10 | 10/10 fail cleanly, error surfaced **50.2 ms** after the peer's last iteration (FIN rule) | - |
| T8 stock control | same, recovery off (the stock code path) | 78f96f38 | 3 | **3/3 hang**: the survivor prints nothing (no NCCL warning) until the runner kills it at 60 s | - |
| T9 | peer never answers REQ (mute test hook) | 3b0b760d | 5 | 5/5 fail cleanly at the handshake deadline | - |
| T4ar | R's QP dies silently at the end of an all-reduce iteration (S idle) | 78f96f38 | 1 | fails cleanly at the 120 s WAITREQ bound (both sides) | - |

- Hardware counters `duplicate_request`, `out_of_sequence`, `packet_seq_err`, `implied_nak_seq_err`
  stayed at 0 on both NICs across every campaign: no stale packet of an old QP incarnation was seen.
- The storage traffic on the same link (NVMe-oF on the primary addresses) logged nothing during the
  address-flap runs (sunny's last NVMe kernel message is the 2026-09-22 mount).
- Before the FIN rule, T8 hung 5/5 until the test timeout: with back-to-back all-reduces the survivor
  is usually waiting to receive when the peer dies, so nothing of its own is in flight and no RETRY_EXC
  ever comes. Stock NCCL behaves the same way: the T8 stock control hung 3/3.
- T4 (a silent R death meant to exercise the RETRY_EXC-led path) could not be produced with this
  workload (see DESIGN §15); the RETRY_EXC-led path is exercised by the real fault T7 instead.
- Fault-free overhead with the flag on (`../perf`, 3 runs each, medians vs stock 2.23.4): single
  config 64 KB +0.7 %, 1 MB −0.2 %, 16 MB +0.6 %, 64 MB +0.4 %; default config +0.6 / +0.1 / −0.1 /
  +0.1 %. Flag off equals stock within noise.
- Completion time of a whole job with one fault (`../perf/README.md`): recovery adds about 2 ms and
  restart-from-the-failed-iteration about 1.1 s. With NCCL's default IB timeout, a real path fault
  takes about a minute to surface, and recovery and restart then finish within noise of each other.

## Files

| file | what |
|---|---|
| `DESIGN_stage2.md` | design, invariants, exactly-once argument, QA rounds 1 and 2 |
| `net_ib_stage2.diff` | the patch against v2.23.4-1 |
| `run_tests.py` | the validation matrix (design §11) |
| `gid_blackhole.sh`, `gbh_feasibility.sh` | the address-flap fault (secondary RoCE address removed and re-added) and its feasibility test |
| `linkflap_window.sh` | a real link down/up on sunny's RoCE port, with a watchdog that brings the link back. **Not run**: the link carries the user's NVMe-oF, so the script refuses to run without explicit approval |
| `results/` | per-run logs, `results.csv`, hardware counters before/after each campaign |
