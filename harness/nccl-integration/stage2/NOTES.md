# stage2: 상세 기록

이 문서는 예전 README 본문을 그대로 옮긴 상세 기록이다(영문). 요약은 [README.md](README.md)에 있다.

**2026-10-06 리뷰 정정** (`harness/gpu-initiated/propagation/review_20261006/nccl_netib_design.md`)
- 표에서 "final build"라 적은 A2/A3 행은 78f96f38이다. 진짜 최종은 a037de42이고, 경우마다 3회씩만 돌렸다(A5). T1~T3의 30/30은 최종 이전 빌드 f7f45278 결과다.
- T12d 원본 경로 대조의 "error 0.05–2.18 ms after the fault"는 틀렸다. 앱 오류까지는 0.055/0.067/0.242 ms다. 2.18 ms는 주입에서 SUMMARY 줄까지의 시간이다.
- T7 "stock control"은 원본 바이너리가 아니라 78f96f38의 플래그 끔이고, 0.5 s와 6 s만 있다. 15 s 대조는 없다. 최종 빌드는 T7a만 3회 다시 돌렸다.
- 실행기의 CLEAN_FAIL 판정은 한 rank만 오류를 봐도 붙는다. T12d는 두 변형 모두 3/3이 그렇다. "깨끗한 실패"가 양쪽이 다 알았다는 뜻은 아니다.
- `DESIGN_stage2.md` §10의 "re-adding it restores the path", §11 T7의 "0.2 s masked", 주소 제거 스크립트 두 개의 머리말, 실행기의 MASKED 판정은 낡았다. 다시 넣은 주소는 새 GID 인덱스를 받아 기존 QP는 영영 죽는다. 0.3 s 사전 시험의 원시 출력은 저장소에 없다.
- 장애 없는 오버헤드 문단의 원본 흩어짐 "0.4–1.7 %, one cell 4.6 %"는 아래 끝이 틀렸다. perf의 Stage 2 오버헤드 표에서 원본 3회(rank 0 반복 시간 중앙값)의 (최대−최소)/중앙값을 다시 세면 0.1~1.7 %, 한 칸 4.6 %다. 0.1 %는 default 64 MB 칸이다. 칸별로 보면 single 64 KB의 +0.7 %는 그 칸의 원본 흩어짐(0.4 %)보다 크고, single 16 MB의 +0.6 %는 그 칸의 흩어짐(0.6 %)과 같다. "모두 흩어짐 안"은 전체 범위와 비교할 때만 맞다.
- 아래 본문의 복구 수치는 다음 한계 안에서만 맞다. 걸린 요청은 많아야 4개, 모든 복구가 첫 라운드, "실행됐지만 ACK 못 받은" 경우는 5번(모두 T7), 재전송 위치를 틀리게 하는 음성 대조는 없다.

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
`78f96f38` (+ the FIN rule, §7), `7b0d0122` (+ the OOB-loss fix after the 2026-09-25 review: a keepalive
timeout no longer counts as peer death), `a037de42` (+ after the second review: a reset (RST) no longer
counts as peer death either, only FIN; final), `9ed03e1d` (a037de42 + the test-only F2 hook
`NCCL_RDMA_FAULT_INJECT_RKEY`, DESIGN §10; `net_ib_stage2.diff` is this build's source, and its previous
version in git is a037de42's). The later changes
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
| **T7a** | **address-reconfiguration fault: sunny's secondary RoCE address removed for 0.5 s and re-added** (it comes back at a new GID index, so the old QPs' address vectors name a dead GID entry; both NICs exhaust retries → RETRY_EXC 3.1 s after the address is back) | 78f96f38 | 5 | **5/5 recovered** (4 connections each, 15,000/15,000 iterations exact) | 2.64 ms (2.00–4.11) after RETRY_EXC |
| **T7b** | same, 6 s outage | 78f96f38 | 5 | **5/5 recovered** | 3.26 s (waits for the address, 2.26–3.27 s) |
| **T7c** | same, 15 s outage | 78f96f38 | 5 | **5/5 recovered** | 12.27 s (waits for the address) |
| T7a/T7b stock control | same faults, recovery off | 78f96f38 | 3 / 3 | **6/6 fail** (RETRY_EXC 12/0x81 at iteration ~443, then NCCL 2.23's abort hang) | - |
| T8 | rank 1 SIGKILLed while rank 0 waits to receive | 78f96f38 | 10 | 10/10: rank 0's NCCL error surfaced **50.2 ms** after the peer's last iteration (FIN rule), then rank 0 exited through the driver's abort watchdog (rc 7, NCCL 2.23's `ncclCommAbort` hangs); rank 1 = the killed rank (rc 255 via ssh). The CSV of that campaign (C5) says `FAIL(rc 7/255)`: the classifier accepted rc 7/255 as a clean failure only afterwards | - |
| T8 stock control | same, recovery off (the stock code path) | 78f96f38 | 3 | **3/3 hang**: the survivor prints nothing (no NCCL warning) until the runner kills it at 60 s | - |
| T9 | peer never answers REQ (mute test hook) | 3b0b760d | 5 | 5/5 fail cleanly at the handshake deadline | - |
| T4ar | R's QP dies silently at the end of an all-reduce iteration (S idle) | 78f96f38 | 1 | fails cleanly at the 120 s WAITREQ bound (both sides) | - |
| **T12b** (recorded as T10b) | **management-network outage**: every TCP connection of the job between the nodes blackholed for 12 s (iptables on rain, this job's ports only), RDMA untouched; 1 GiB all-reduces | 78f96f38 (before the fix) | 3 | **0/3: a healthy job killed** 4.3–4.6 s into the outage ("peer closed its OOB socket ... peer process gone") | - |
| **T12b** | same | **7b0d0122 (first fix)** | 5 | **5/5 pass**, 100/100 iterations exact; all 4 comms on both ranks log "OOB socket lost (Connection timed out) ... recovery disabled" 4.2–4.5 s in | - |
| T12b stock control | same, stock library | stock | 2 | 2/2 pass | - |
| T0d / T1 / T2 / T3 / T5 / T6 / T7a / T8 / T9, fixed build (A4) | regression after the OOB-loss fix | 7b0d0122 | 5 each | all as before: 5/5 pass; 5/5, 5/5, 5/5 recovered; 25/25 and 10/10 recoveries; T7a 5/5 (20 recoveries); T8 5/5 error 50.1–50.2 ms after the peer's last iteration (FIN path, no OOB-loss line); T9 5/5 clean fail | 2.24–2.45 ms; T7a 3.30 ms after RETRY_EXC |
| T12 (recorded as T10) | same outage with 16 MB all-reduces | 78f96f38 / 7b0d0122 / stock | 3 / 5 / 2 | all pass (with 16 MB the per-iteration gaps reset the 50 ms grace, so the old rule did not fire) | - |
| **T12c** | **one-sided** management-network outage (only sunny→rain dropped, 12 s, 1 GiB): rain's keepalive times out and its kernel resets the connection; the RST reaches sunny, which is alive | 7b0d0122 (RST still = death) | 3 | **0/3: healthy job killed** on sunny ("peer closed its OOB socket (FIN/RST) ... peer process gone") | - |
| **T12c** | same | **a037de42 (final: only FIN = death)** | 5 | **5/5 pass**, 100/100 iterations exact | - |
| T12c stock control | same, stock library | stock | 2 | 2/2 pass | - |
| T12b | two-way outage again, final build | a037de42 | 3 | 3/3 pass | - |
| **T12d** | a send-QP fault ~10 s after a two-way outage (OOB lost on both sides), 16 MB | a037de42 | 3 | 3/3 fail **like stock**: the incident is refused with "OOB lost" and the error surfaces 0.06–0.07 ms after the fault | - |
| T12d stock-path control | same, recovery flag off (stock error path; the stock library has no injection hook) | a037de42, flag off | 3 | 3/3 fail, error 0.05–2.18 ms after the fault | - |
| T0d / T1 / T2 / T3 / T5 / T6 / T7a / T8 / T9, final build (A5) | regression after the FIN-only change | a037de42 | 3 each | 3/3 pass; T1/T2/T3/T5/T6/T7a all recovered; T8 3/3 clean fail through the FIN path; T9 3/3 clean fail | - |

- Stale-packet counters: `duplicate_request`, `out_of_sequence` and `packet_seq_err` stayed at 0 on both
  NICs across every campaign. `implied_nak_seq_err` was 0 on both NICs up to campaign B (03:41) and 2 on
  rain from C2 (04:08) on; it did not change inside any campaign that has both snapshots (B and C6 lack
  the "after" snapshot, and other experiments used the cluster between B and C2), so its source is
  not attributed. No stale packet of an old QP incarnation was seen.
- The storage traffic on the same link (NVMe-oF on the primary addresses) logged nothing during the
  address-flap runs (sunny's last NVMe kernel message is the 2026-09-22 mount).
- Before the FIN rule, T8 hung 5/5 until the test timeout: with back-to-back all-reduces the survivor
  is usually waiting to receive when the peer dies, so nothing of its own is in flight and no RETRY_EXC
  ever comes. Stock NCCL behaves the same way: the T8 stock control hung 3/3.
- T4 (a silent R death meant to exercise the path where S's own RETRY_EXC leads the recovery): on
  all-reduce (B, 5 runs) S was idle and never met RETRY_EXC; with a 256 KB broadcast (C5, 10 runs) the
  silent injection never fired; with a 64 MB broadcast (C6, 3 runs) it fired 3/3 and S met RETRY_EXC
  once (3.56 s after the silent death), **recovering in 1.9 ms**; the other 2 ran into the 90 s run
  timeout with S idle (below R's 120 s WAITREQ bound). The S-led RETRY_EXC path is also exercised by
  T7 (every T7 run).
- Fault-free overhead with the flag on (`../perf`, 3 runs each, medians vs stock 2.23.4): single
  config 64 KB +0.7 %, 1 MB −0.2 %, 16 MB +0.6 %, 64 MB +0.4 %; default config +0.6 / +0.1 / −0.1 /
  +0.1 %. These are all inside the run-to-run spread of stock itself (0.4–1.7 %, one cell 4.6 %, n=3),
  so the measurement bounds the cost to about 1 % but cannot resolve it. Flag off equals stock within
  the same noise.
- Completion time of a whole job with one fault (`../perf/README.md`): recovery adds about 2 ms and
  restart-from-the-failed-iteration about 1.1 s. The 1.1 s is the relaunch cost of a small 2-rank job
  (process start to communicator ready) with a checkpoint every iteration, so it is a lower bound for
  real jobs, not a typical value. With NCCL's default IB timeout, the address-reconfiguration fault
  takes about a minute to surface, and recovery and restart then finish within noise of each other.
- **What T7 does and does not show.** The fault is an address reconfiguration, not a packet-loss
  transient: the address was back 0.51 s after the cut, yet stock QPs failed (6/6, and 0.3 s in the
  feasibility test) because the re-added address got a new GID index while the old QPs' address
  vectors still name the removed entry. T7 shows that drain, PSN reset, replay and GID re-resolution
  work on a real RETRY_EXC CQE. It does not show tolerance of a transient packet loss with the GID
  index kept (a real link flap): a flap shorter than the retry budget would be absorbed by stock too,
  and a longer one also raises port-state events, a path not tested here. The real link-flap test
  was not run: the link carries the user's NVMe-oF. Its never-run script, `linkflap_window.sh`, was
  removed from the tree on 2026-10-06 (tag `archive/results-tables-20261006`).

## Files

| file | what |
|---|---|
| `DESIGN_stage2.md` | design, invariants, exactly-once argument, QA rounds 1 and 2 |
| `net_ib_stage2.diff` | the patch against v2.23.4-1 |
| `run_tests.py` | the validation matrix (design §11) |
| `gid_blackhole.sh`, `gbh_feasibility.sh` | the address-flap fault (secondary RoCE address removed and re-added) and its feasibility test |
| `results/` | per-run logs, `results.csv`, hardware counters before/after each campaign |
