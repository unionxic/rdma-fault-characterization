# CPU verbs harness: detailed notes

이 문서는 예전 README 본문을 그대로 옮긴 상세 기록이다(영문). 요약은 [README.md](README.md)에 있다.

**2026-10-06 리뷰 정정** (`gpu-initiated/propagation/review_20261006/cpu_baseline.md`)
- "각 (status, vendor_err) 쌍은 RETRY_EXC를 빼면 고유하다"는 틀리다. `local_qp_err`와 `partial_write`가 모두 5/0xf5다.
- `retry_proc_kill`은 SIGKILL이 아니다. QP를 먼저 정리하고 정상 종료한다. 실제 SIGKILL은 270회 중 111회가 0x88로 나온다(`fingerprint_teardown/`).
- `retry_server_qp_err` 행은 30/30이 `auto_recoverable=0`으로 기록됐다. `probe_client.c`의 라벨 버그이고, 실제로는 복구됐다.


One requester/responder pair that consolidates the main RDMA-side faults of experiments 01–09 into a
single instrument. It injects a selectable RDMA fault, measures how fast the
requester detects it, classifies it from the CQE alone, recovers the QP, and
verifies the connection — all into one CSV schema.

Not covered here: the three LOC_PROT variants of the original study (0x53 SGE length,
0x52 invalid lkey, 0x33 MR permission) and the invalid-rkey variant of REM_ACCESS, so the
vendor_err step that splits LOC_PROT (6/10 -> 8/10 in the docs) is not reproduced by this tool.

```
rain  (requester, mlx5_1, 30.0.0.3)  --RoCEv2 100G-->  sunny (responder, mlx5_0, 30.0.0.4)
   probe_client  ------ TCP control (sunny mgmt IP 192.0.2.194:18580, TCP_NODELAY) ------  probe_server
```

## What it measures (per fault, per trial, one CSV row)

| column | meaning |
|---|---|
| `detect_ns` | inject → first error CQE (CLOCK_MONOTONIC_RAW tight poll); `-1` if no error CQE arrived within the detect timeout |
| `status` / `status_name` / `vendor_err` | the CQE fingerprint — the paper's classification key (`-1` / `no_error_cqe` when the fault did not manifest) |
| `cause` / `action` / `peer_alive` / `auto_recoverable` | `classify(status,vendor_err)` output |
| `recover_ns` | coordinated QP recovery latency (both ends); `-1` for `-r none` and `retry_proc_kill` |
| `verify_ok` | 1 if a post-recovery 4 KiB WRITE+READ-back matched; `-1` if no recovery was attempted |
| `bytes_sent_psn` / `sq_psn_delta` / `mtu_bytes` | partial_write: bytes the requester had **sent** when its QP was forced to ERR, from the send-queue PSN advance: `((sq_psn_after − sq_psn_before) & 0xFFFFFF) × PMTU` |
| `bytes_landed_readback` / `matching_bytes_total` | partial_write: bytes that actually **landed** at the responder, measured by RDMA-READ readback (below): matching-prefix length / matching bytes anywhere in the region |
| `counter` / `cnt_delta` | a chosen `hw_counter` delta across the trial (diagnosis / early detection) |
| `sub_cause` / `peer_rx_delta` | split of the ambiguous RETRY_EXC (0x81): server_qp_err vs proc_kill vs link_down; for REM_ACCESS / REM_INV_REQ, `proc_kill` when the peer does not answer the liveness PROBE |
| `srv_qp_state` | responder QP state (`ibv_query_qp`) after the fault, before recovery: `RESET INIT RTR RTS SQD SQE ERR`; `-` if the responder is dead, `?` if it did not answer |
| `srv_async` | responder's async events since its GO, at the same moment (format below); `-` / `?` as above |
| `cli_async` | requester's own async events since its GO, at the same moment |

The four partial-write columns are `-1` for every other fault. The last three columns were
added on 2026-10-06 (below); older CSVs end at `peer_rx_delta`.

### Partial-write accounting (measured, not derived)

The responder zeroes its 4 MiB buffer when it acks a `partial_write` TRIAL. The
requester posts one `MSG_SIZE` (4 MiB) WRITE, forces its own QP to ERR mid-transfer
and records the sq_psn advance (bytes **sent**). Once the QP is back in RTS (after
RECOVER, or after the NORECOVER bring-up with `-r none`), and before the 4 KiB verify
step overwrites remote offset 0, it RDMA-READs the responder region `[0, MSG_SIZE)`
and compares it with the pattern it wrote that trial (byte *i* = `(0x40+iter) + (i & 0xff)`).
The matching-prefix length is `bytes_landed_readback`; `matching_bytes_total` counts
matches anywhere, so a larger value would reveal out-of-order or non-prefix placement.
Pattern bytes that happen to be `0x00` cannot be told apart from the zero fill; they
are judged by a neighbour in the same 256-byte-aligned block (always the same packet,
since PMTU ≥ 256), so both counts are exact at packet granularity.

The PSN-derived value and the readback are two independent measurements;
`analyze.py` reports the landed range and how often landed == sent. (Earlier versions
recorded only `sq_psn_delta × PMTU` and then "checked" that same identity.)

### Sub-classification of RETRY_EXC (0x81)

The CQE fingerprint RETRY_EXC (12 / 0x81) is ambiguous: a responder QP that went to
ERR, a dead responder process, and a downed link all produce it. The harness splits
it with signals outside the CQE:

1. **link state** — the requester's RDMA port is not ACTIVE (direct cable), or the
   responder reports its own port not ACTIVE in the PROBE reply (via a switch) ⇒ `link_down`.
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

**REM_ACCESS (10 / 0x88) and REM_INV_REQ (9 / 0x8a) get the same liveness PROBE**
(2026-09-25). A SIGKILLed peer whose MR is torn down before its QP NAKs with 0x88 instead
of going silent (`fingerprint_teardown/`: REM_ACCESS 111/192 kills when the MR was
registered after the QP). An answered PROBE leaves the CQE classification unchanged. An
unanswered one is split (changed after review, 2026-09-25): EOF or reset on the control connection
sets `sub_cause=proc_kill`, `peer_alive=0`, `auto_recoverable=0` (peer death, not an access bug); no
answer within 1 s on a connection that is still open sets `sub_cause=no_answer`, `peer_alive=-1`
(unknown), `auto_recoverable=0`, so a live but slow peer with a real access bug is not recorded as
dead. The same split applies to RETRY_EXC (before, a timeout also counted as `proc_kill`).
A first version of this split could never report `no_answer`: `ctrl_recv_line` called `perror()`
after the timed-out `recv()`, and glibc 2.31 then sets errno to EINVAL when stderr is a file or a pipe
(as it is under `run.sh`). `ctrl_recv_line` now saves and restores errno and stays quiet on the
expected timeout. Validated with the server's test switch `PROBE_TEST_NO_PROBE_REPLY=1` (a live
server that ignores PROBE): `rem_access`, `rem_inv_req` and `retry_server_qp_err` 3/3 each gave
`no_answer`, `peer_alive=-1`, and still recovered and verified; without the switch `rem_access`,
`retry_server_qp_err` and `retry_proc_kill` gave the same results as before
(`results/validation_20260925_no_answer/`). Validated with a live peer: `rem_access` 5/5 and `rem_inv_req`
5/5 still recovered. `retry_server_qp_err` 5/5 and `retry_proc_kill` 3/3 were unchanged.
The dead-peer 0x88 path itself is not produced by this harness's faults.

## Fault catalog (`-f`)

| fault | trigger | expected fingerprint (ConnectX-6 (VPI, MT28908), fw 20.43.4100) |
|---|---|---|
| `none` | F0 control: the normal 4 KiB write, polled to its completion | success; `detect_ns=-1` |
| `local_qp_err` | deep write burst, then force own QP→ERR | WR_FLUSH_ERR (5) / 0xf5 |
| `rem_inv_req` | atomic to a responder QP that doesn't enable atomics | REM_INV_REQ_ERR (9) / 0x8a |
| `rem_access` | write past the end of the remote MR | REM_ACCESS_ERR (10) / 0x88 |
| `rnr` | SEND with no remote recv WQE (finite rnr_retry) | RNR_RETRY_EXC_ERR (13) / 0x87 |
| `retry_server_qp_err` | responder QP→ERR, stops ACKing | RETRY_EXC_ERR (12) / 0x81, ~3.75 s firmware floor |
| `partial_write` | 4 MiB write, force own QP→ERR mid-transfer | WR_FLUSH_ERR (5) / 0xf5; landed bytes measured by readback |
| `retry_proc_kill` | responder process exits on GO (runner restarts it per trial; client needs `-n 1`) | RETRY_EXC_ERR (12) / 0x81 |
| `retry_proc_sigkill` | responder raises SIGKILL on GO: no cleanup by the process (restarted per trial; `-n 1`) | not yet measured |
| `retry_link_down` | responder runs `sudo -n ip link set dev $SERVER_IFACE down` on GO (see below) | RETRY_EXC_ERR (12) / 0x81 expected — not yet measured |

Unknown `-f` / `-r` names are rejected (exit 2); they no longer fall back to `none`.

Recovery (`-r`): `qp_only` (ERR→RESET→INIT→RTR→RTS on the same QP, coordinated both
ends, fresh PSN), `full_rebuild` (destroy + recreate **the QP only**; the CQ, MR and PD
are kept — this is not a full verbs-context rebuild), or `none` (the QP is still reset
and reconnected so the next trial can run, but the time is not recorded).

### retry_link_down

- **Status: implemented** in client, server and runner. The protocol and every
  link-restore path were validated on 2026-09-23 with `PROBE_LINK_DRYRUN=1` only; a
  real link toggle has not been run, so the fingerprint above is still unmeasured.
- **Requires passwordless sudo for `ip` on the responder** (a NOPASSWD sudoers rule).
  Before acking a `retry_link_down` TRIAL the server checks that `SERVER_IFACE` exists
  and that `sudo -n -l ip link set dev <iface> down|up` is allowed. If not, it replies
  `ERR link_down_unavailable <why>`; the client prints why, writes no rows and exits 3.
  Note that on 2026-09-23 both rain and sunny had a `NOPASSWD: ALL` rule
  (`/etc/sudoers.d/90-unionxic-nopasswd` on sunny), so on this cluster the check passes
  and a non-dry-run `retry_link_down` really takes `enp23s0f0np0` down.
- **The link is restored on every exit path** (`ip link set up`, then a wait for the port
  to be ACTIVE): RECOVER, NORECOVER, BYE or an unexpected line mid-trial, client
  disconnect or kill, fatal errors, normal exit, SIGTERM/SIGINT/SIGHUP (an
  async-signal-safe handler, which matters because `run.sh` runs the server under
  `timeout`), plus `atexit`. SIGKILL cannot be caught, so when `retry_link_down` runs
  without dry-run, `run.sh`'s EXIT trap brings `SERVER_IFACE` back up if it is admin-down.
- **Dry run:** `PROBE_LINK_DRYRUN=1 DETECT_TIMEOUT_MS=1500 ./run.sh retry_link_down`.
  Every toggle only logs `[server] DRYRUN link down|up`, and no sudo is used. Because
  the link never goes down, the rows show `no_error_cqe`.

The final run after all fixes (2026-09-23 12:39, stamp `20260923_123945`, N=30, all seven
faults incl. `retry_proc_kill`, CPU 2 pinned, no other traffic on the link) is the canonical
data set for the results below. It reproduced every fingerprint in the catalog, with
partial-write landed == sent in 30/30.

### Instrumentation for the propagation campaign (2026-10-06)

Added for `gpu-initiated/propagation/PREDICTIONS.md` (cells EV1, EV2, T1). None of it changes
what is posted or polled for the existing faults. Not yet run on the cluster.

- **Async-event thread on both sides.** `probe_client` and `probe_server` each start a thread
  on their device context (`async_mon_*` in `common/probe.c`). It logs every event to stderr:
  `[server] async event IBV_EVENT_QP_ACCESS_ERR qpn=0x1c3 mono_ns=<CLOCK_MONOTONIC ns>`. It then
  acks the event and keeps it for the trial record. The thread blocks all signals, so the
  server's signal handling and its deferral around the link toggle stay on the main thread.
  `CLOCK_MONOTONIC` is the clock `propagation/evrec` uses on the same node.
- **Responder state after the fault.** After detection, and after the PROBE if there is one,
  the client waits `QUERY_SETTLE_MS` (10 ms). The wait lets an event raised with the fault reach
  its thread. Then the client sends `QUERY`. The server answers `QUERIED <state> <events>`: the
  state comes from `ibv_query_qp` on its QP, the events are those its thread took since it
  received GO. The client also formats its own events since it sent GO. All of this happens
  before RECOVER/NORECOVER. When the responder is dead (`retry_proc_kill`,
  `retry_proc_sigkill`, or `sub_cause=proc_kill`), no QUERY is sent and the two server columns
  are `-`. `cli_async` is recorded in every trial.
- **Event list format.** Each event is `<IBV_EVENT_*>/<element>/dt_ns=<ns after GO>`, and events
  are joined by `;`. The element is `qpn=0x..`, `port=N`, `wqn=0x..`, `cq`, `srq` or `-`. An
  empty list is `none`. A list longer than about 400 characters ends with `;+N_more`; the
  stderr log keeps every event.
- **`none` (F0).** The client posts the normal 4 KiB signaled write (the `retry_*` trigger) and
  polls its own completion with `poll_one`. A success gives `status=0` and
  `status_name=success`, `detect_ns=-1`, and the `classify()` row "no error". An error CQE is
  recorded like any other fault. The trial then runs QUERY, the configured recovery and the
  verify, like every other fault, so `recover_ns` for F0 is the cost of resetting a healthy
  connection. `./run.sh none` selects it.
- **`retry_proc_sigkill` (F4).** The server logs one line and calls `raise(SIGKILL)` on GO,
  before GOACK. No `ep_close` and no `close()` run, so the kernel tears down the QP, MR, PD and
  sockets. The client side is the `retry_proc_kill` flow: no GOACK is expected, a 300 ms wait,
  one 4 KiB write, the liveness PROBE, no recovery. `run.sh` restarts the server per trial, as
  for `retry_proc_kill`.
- **Teardown time.** At exit the client prints
  `[client] teardown (ep_close) returned after X ms`, and the server prints the same with
  `[server]`. `ep_close` stops the async thread first, then destroys the QP, CQ, MR and PD and
  closes the device.
- **Checked locally only (no RDMA peer, no traffic).** The build is clean with
  `-Wall -Wextra -Werror`. On rain `mlx5_1` (device context only), the thread starts, stops
  through `ep_close` in 0.4 ms, and formats an empty list as `none`. Synthetic records gave the
  expected `dt_ns`, the GO filter, `;+N_more` truncation and ring wrap. `analyze.py` reads the
  new columns unchanged.

## Build & run

```bash
make                       # builds probe_client + probe_server (both nodes)
./run.sh                   # runs the default fault set from config.sh, then analyze.py
CLIENT_CPU=2 SERVER_CPU=2 ITERS=30 ./run.sh                 # pinned, 30 trials
FAULTS="rnr rem_access" RECOVERY=full_rebuild ./run.sh      # subset + method
ITERS=30 ./run.sh retry_proc_kill                           # server restarted per trial
ITERS=10 ./run.sh none retry_proc_sigkill                   # F0 control; real SIGKILL (restarted per trial)
```

All environment lives in `config.sh` (server IP/ssh/device/iface, client device, GID
indices, port, iterations, CPU pinning, counter, `PROBE_LINK_DRYRUN`, `SERVER_TIMEOUT`).
Client and server take independent `-d` and `-g` because their devices and GID tables
differ. `CLIENT_GID_INDEX` / `SERVER_GID_INDEX` default to `auto`: `run.sh` picks each
node's RoCE v2 IPv4-mapped GID. On 2026-09-23 that was index 4 on rain (it had moved
from 3) and index 3 on sunny. `GID_INDEX=N` forces N on both sides.

Exit status:
- `run.sh` exits 0 only if every client exited 0 **and** every CSV has exactly `ITERS`
  data rows; otherwise it exits 1 and lists the failing faults. Failed
  `retry_proc_kill` iterations are counted, not masked.
- `probe_client` exits 0 on success, 1 on a protocol/RDMA failure or too few trials
  (rows already written are kept), 2 on bad arguments, and 3 if the server refused the
  fault.
- Each `probe_server` gets a safety-net lifetime of `SERVER_TIMEOUT`, sized from
  `ITERS` (120 s + ITERS × (detect timeout + 25 s)), so long runs are not cut off.

Manual invocation:
```bash
# responder (on sunny); PROBE_LINK_DRYRUN=1 in the env for a link_down dry run
./probe_server -d mlx5_0 -i 1 -g 3 -p 18580 -I enp23s0f0np0
# requester (on rain); control channel over sunny's mgmt IP
./probe_client -s 192.0.2.194 -d mlx5_1 -i 1 -g 4 -p 18580 -f rnr -r qp_only -n 30 -o results/rnr.csv
```

## Reproduced results (N=30, CPU 2 pinned on both nodes, 2026-09-23, this cluster)

PMTU is 4096 B (netdev MTU 9000). Canonical CSVs (numbers from `analyze.py`): detection,
QP-only recovery and verify come from `results/*_20260923_123945.csv` (all seven faults);
the full_rebuild column comes from `results/*_20260923_114031.csv`. The other same-day stamps
are earlier runs and are not used in the table.

| fault | status / vendor | detect mean ± CI95 (median) | QP-only recover mean (median) | full_rebuild recover mean (median) | verify |
|---|---|---:|---:|---:|---:|
| local_qp_err | WR_FLUSH / 0xf5 | 226 µs ± 1.5 µs (225 µs) | 0.90 ms (0.79 ms) | 1.80 ms (1.79 ms) | 30/30 |
| partial_write | WR_FLUSH / 0xf5 | 346 µs ± 6 µs (338 µs) | 0.79 ms (0.78 ms) | 1.82 ms (1.81 ms) | 30/30 |
| rem_inv_req | REM_INV_REQ / 0x8a | 532 µs ± 183 µs (304 µs) | 0.78 ms (0.77 ms) | 1.92 ms (1.80 ms) | 30/30 |
| rem_access | REM_ACCESS / 0x88 | 682 µs ± 307 µs (323 µs) | 0.78 ms (0.77 ms) | 1.79 ms (1.79 ms) | 30/30 |
| rnr | RNR_RETRY_EXC / 0x87 | 12.76 ms ± 46 µs (12.79 ms) | 0.79 ms (0.78 ms) | 1.81 ms (1.80 ms) | 30/30 |
| retry_server_qp_err | RETRY_EXC / 0x81 | **3.749 s** ± 0.35 ms (3.749 s) | 0.82 ms (0.81 ms) | — | 30/30 |
| retry_proc_kill | RETRY_EXC / 0x81 | **3.727 s** ± 9.0 ms (3.732 s) | n/a (process gone) | — | — |

- All seven faults keep the fingerprints listed in the catalog. Each (status,
  vendor_err) pair is unique except that the two RETRY_EXC causes share 0x81. Those are
  split by liveness: `server_qp_err`×30 and `proc_kill`×30.
- `partial_write`: readback-measured landed bytes are 1,085,440–1,130,496 B (265–276
  full 4 KiB packets out of 4 MiB). The PSN-based sent bytes equal the readback on
  **30/30** trials; there were no matching bytes outside the prefix, and every value is
  PMTU-aligned. The same exact agreement held in every partial_write run that day:
  130/130 trials in six runs across qp_only, full_rebuild and `-r none`.
- `retry_server_qp_err` / `retry_proc_kill` reproduce the ~3.7 s firmware detection
  floor (min_ack_timeout_limit) on ConnectX-6 (VPI, MT28908).
- Recovery method: full_rebuild ≈ 1.8 ms against ≈ 0.8 ms for QP-only (means 0.78–0.90 ms,
  medians 0.77–0.81 ms), about 2.3× on medians (2.27–2.33× for the five faults with both
  methods; the two columns come from different runs).
- `rem_access` / `rem_inv_req` detection is bimodal: for each, 25 of 30 trials take
  0.30–0.37 ms and 5 of 30 take 1.6–3.0 ms. That is why the mean ± CI is wide; the median
  is the typical value.
- An earlier pinned run the same day (`20260923_113252`) showed a QP-only recovery tail
  of 12.8–17.2 ms on 2–5 of 30 trials in five of the six faults with recovery (none in
  partial_write), while rain's 5-minute load average was ~7.8. Rerun at low load
  (`114046`/`114103`, and again in the canonical `123945`), the tail disappeared: QP-only
  p95 ≤ 1.06 ms and no trial above 1.1 ms. Treat recovery means from a loaded host with care.

## Design notes

- TCP_NODELAY on every control socket (both connect and accepted sides) — avoids the
  ~40 ms delayed-ACK artifact that contaminated the old A/B recovery numbers.
- Manual RC QP setup (no rdmacm) for full control of state transitions.
- Error checking on every verbs/socket call, and a failed post is never recorded as a
  fault trial. Clean teardown; built with `-Wall -Wextra -Werror`.
- CLOCK_MONOTONIC_RAW timing; optional CPU pinning for latency stability.
- `rnr_retry=6` (7 means retry-forever, which never exhausts).
- The runner stops servers with `pkill -x probe_server` (exact process name).
  `pkill -f probe_server` inside `ssh host "..."` matches the remote shell's own
  command line, so it kills itself.
- Not covered here (separate subsystem): the NVMe-oF Storage×RDMA boundary lives in
  `experiments/*/10_storage_rdma`.
