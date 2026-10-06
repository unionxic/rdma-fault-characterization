# ack_timeout: 상세 기록

아래는 예전 README 본문을 그대로 옮긴 것이다(영문). 요약은 [README.md](README.md)에 있다.

**2026-10-06 리뷰 정정**
- 59.8 s는 한 프로세스 안 연속 장애 값이다. 새 프로세스는 58.46~58.79 s, NCCL GIN 측정은 57.1~58.4 s다. 다른 문서에서 인용할 때 이 조건을 붙인다.
- 9.5 ms는 T=8, floor 끔 값이다. T=20, floor 끔은 37.9 s다(2회). floor 끄기는 NIC function 전체에 걸리는 레지스터 변경이다.
- D1b의 "back-to-back 시험의 약 5%가 몇 ms 일찍 끝난다"는 D1의 첫 시험 제외 55회 중 3회다. A절의 42회에는 없었으므로 합치면 97회 중 3회다.
- 아래 본문에 이미 반영된 정정: GIN 57~59 s가 "모델 범위 안"이라는 문장 철회, 레지스터 창 잠금 확인 수정, 각 칸 첫 시험이 모델에서 벗어나는 현상(원인 미상).

Answers a review of `docs/experiments/01_detection_firmware_retry.md` and of the GPU stage
(`harness/gpu-initiated/`):

- **A.** Why did NCCL at its default IB timeout 20 report RETRY_EXC after 57-59 s, when
  4.096 us x 2^20 x 8 = 34.4 s? (floor on, no register change)
- **B.** The old study's floor-off sweep, reproduced on this cluster.
- **C.** The floor-off setting carried into the GPU stage (NCCL GIN GDAKI with the GPU device
  classifier, NVSHMEM IBGDA with the FT patch), "peer QP error" fault (RETRY_EXC).

Cluster: rain (requester, ConnectX-6 VPI `mlx5_1` = PCI 17:00.1, fw 20.43.4100, OFED 23.10,
kernel 5.15) -> sunny (responder, `mlx5_0`), RoCE v2, direct link, PMTU 4096. Only rain's NIC
register was changed, and only inside `ackfloor_window.sh`; sunny's NIC kept its defaults.
Default register state of rain 17:00.1 (read before every window): `roce_adp_retrans_en=1`,
`roce_slow_restart_en=1`, `min_ack_timeout_limit_disabled=0`, all other ROCE_ACCL fields 0.
**[measured]** = computed from a file under `results/20260925/`; **[inferred]** = derived or read
from source, not measured here. "nominal" below always means 4.096 us x 2^T (the IBA encoding).

## TL;DR

- **The 34 s vs 57-59 s gap is explained [measured, T=20 R=7: 59.05-59.77 s back-to-back (N=5),
  58.46-58.79 s in fresh processes (N=10), 57.69-58.24 s in fresh processes with traffic before
  the fault (N=5)].** With the
  firmware defaults the NIC does not make "R+1 attempts of 4.096 us x 2^T". Per fault it runs
  1. an **adaptive-retransmission phase**: 4-11 early retransmissions on a firmware schedule
     (typical steps 8.6, 16.6, 33.7, 67.1, 100.6, 201.4, 536.8, 805.3, 2147.8, 4294.8 ms), counted
     in `roce_adp_retrans`, not in `local_ack_timeout_err`. It continues while the step is at most
     nominal(max(T,16)) (within 0.3 ms) and, whatever its length, uses up **one** unit of `retry_cnt`
     (this schedule is the back-to-back one; in a fresh process it differs, section D);
  2. then **R-1 regular ACK timeouts** (`local_ack_timeout_err`), spaced exactly
     **I = 2 x 4.096 us x 2^max(T,16)**: 536.9 ms for T<=16, then 1073.8 / 2147.6 / 4295.1 /
     8590.2 ms at T=17/18/19/20 (interval / nominal(max(T,16)) = 2.000 in every cell). The first R-2 of them
     retransmit; the last one completes the WQE with RETRY_EXC 12/0x81 (0.37 ms before to 0.07 ms
     after the CQE was polled).

  At T=20, R=7, back-to-back: adaptive phase to 8.225 s (10-11 retransmissions), first regular
  timeout at 16.815 s, then 5 x 8.590 s -> **59.766 s**. The naive (R+1) x nominal is short by
  about 2R/(R+1) = 1.75 at R=7 (59.8 / 34.4 = 1.74).
- **What the model predicts, and what not (review follow-up, section D) [measured].**
  - *Back-to-back faults in one process*: detect = R x I - c (c fitted: 96 / 364 ms). Out of
    sample, with predictions written down before the run, 52/55 non-first trials at T=10, 12, 15,
    16 (R=7), T=15 (R=1, 3, 5) and T=17 (R=1, 2, 3, 5) were within 1.5 ms (per-cell median error -0.45 to
    -0.82 ms); the `max(T,16)` clamp, R-1 regular timeouts and the T=17 first-timeout rule held in
    55/55; 3 trials ran 2.6-7.6 ms early (their whole adaptive schedule shifted).
  - *First fault of a process* (every GPU/NCCL trial): only the regular part is predicted. In
    all 205 sampled floor-on trials with R >= 1 (sections A and D, every mode) there were R-1
    regular timeouts spaced I (within 0.56 ms), the last one within 0.6 ms of the CQE, so
    detect = t_L1 + (R-2) x I (within 1.0 ms; 1.7 ms at T=20, where I = 2.00003 x nominal). Where the regular
    part starts (t_L1) depends on history: at T=14 R=7 detect was 3.50-3.76 s across fresh
    processes, fresh contexts, idle gaps and prior traffic (model 3.66 s); at T=20 57.7-59.8 s.
  - *NCCL GIN proxy 57-59 s*: below the back-to-back model (59.77 s; the earlier README wrongly
    said "within range"); matched in range by fresh CPU processes with GIN-like traffic before
    the fault (57.69-58.24 s, N=5).
- **"The floor" is a firmware mode, not only a clamp [measured].** With the defaults, the
  interval is clamped to 536.9 ms (= 2 x nominal(16)) for T<=16 - the old study's "537 ms per
  retry"; the old "429 ms first timeout" matches the adaptive phase (440 ms here) and "adp absorbs
  one retry" the unit of `retry_cnt` the phase consumes [inferred mapping; the old CX-5 data were
  not re-examined]. With `min_ack_timeout_limit_disabled=1`
  the NIC made **no** adaptive retransmission (`roce_adp_retrans` +0 in 99/99 trials) and the
  interval became **1.000 x nominal** (also above T=16), with exactly R retransmissions.
- **Floor off, CPU verbs [measured]:** R=7: **9.49 ms at T=8** (N=10), 37.9 ms at T=10, 147.0 ms
  at T=12, **574.9 ms at T=14** (N=10); at T=8, R=0 / 3: 2.24 / 5.43 ms (old study, CX-5:
  1.2 / 5.9 / 12.26 ms). Every trial fits detect = t1 + (R+1) x nominal within 1.2 ms, where t1
  is a first `local_ack_timeout_err` that triggers no retransmission, at 0.51-1.16 x nominal.
  T=20 R=7 floor off: 37.6-38.3 s (vs 59.8 s with the floor on).
- **GPU stage, floor off [measured, N=10 per cell]:** fault -> host-visible fingerprint (device
  classifier -> host mailbox) **13.3 ms (NVSHMEM IBGDA FT) / 24.6 ms (NCCL GIN GDAKI + device classifier) at T=8**,
  40.4 / 51.9 ms at T=10, 585.1 / 599.3 ms at T=14, vs 3.54 / 3.61 s with the defaults at T=8.
  The NIC part (failing op posted -> error: 9.5 / 10.2 ms at T=8) equals the CPU verbs number;
  the rest is the application's gap until it next touches the QP. 60/60 classified RETRY_EXC
  12/0x81, teardown clean, no spurious error before the fault. No knob was missing
  (`NCCL_IB_TIMEOUT`, `NVSHMEM_IB_TIMEOUT`); nothing was rebuilt.
- **Register restored [measured]:** 9 set/restore cycles (5 restore-path tests, B, B2, C_gin,
  C_nvshmem); 8 restored by the window's trap and verified field by field (19/19 equal to the
  before-dump), 1 (the SIGKILL test) by the guardian within 0.5 s. The final read (06:47:50)
  equals the first before-dump in all 19 fields (`window/final_check_17:00.1.txt`).
- **Window lock check fixed (review item 4).** The first version only refused when a
  non-blocking flock on a hard-coded path succeeded, so a flock(1) error let the register change
  go ahead. It now refuses unless its nearest `cluster_run.sh` ancestor verifiably holds the
  shared lock (fdinfo + flock exit code 75 + script and lock path checks, no hard-coded path).
  All six refusal paths and one positive control were tested inside a real hold with no register
  access (register identical before/after in 19/19 fields); no window has run since the fix.

## Method

### Tester (`src/ackt.c`, `scripts/run_cpu.sh`)

A standalone verbs requester/responder pair (reuses `../common/probe.c` for device, MR, TCP
control; built with `-Wall -Wextra -Werror`). Per trial: a fresh RC QP pair (requester:
`timeout=T`, `retry_cnt=R`, read back with `ibv_query_qp` into `T_q,R_q`), one warm-up 64 B WRITE
that must succeed, a 300 ms quiet window, then sunny moves its QP to ERR (it then drops our
packets silently: no NAK), rain posts one signaled 64 B RDMA WRITE at t0 and tight-polls the CQ
until the completion (t1), detect = t1 - t0 (`CLOCK_MONOTONIC_RAW`). QPs are destroyed after each
trial. Every cell ran under `../gpu-initiated/common/cluster_run.sh` (lock + idle link), with all
processes under `timeout -s KILL`; no process was left on either node after any cell
(`leftover=0/0` in every `logs/*.cli.log`).

Options added for the review follow-up (section D): `-F` reopens the device context (PD, MR,
CQ) before every trial, `-G ms` idles before every trial, `-P n:gap_ms:bytes` posts n signaled
WRITEs right before the fault; every trial and event row carries the process's `run_id` (and
the trial row its QPN, pid and these settings), so one-trial processes appended to the same files
stay separable. Files from the first version are refused rather than mixed.

**Per-timeout timing.** A sampler thread (own CPU) loops over (a) one RDMA-netlink
`RDMA_NLDEV_CMD_STAT_GET` of the port's default counter set - all `hw_counters` in one uncached
firmware query, ~0.2 ms - and (b) the sysfs port counters `port_xmit_packets` and
`port_rcv_packets` (~0.09 ms each). Each change is logged with a bracket [lo, hi] (the counter
held the old value after lo and the new one before hi); the event time is the midpoint. Sampling
round: mean 0.38-0.39 ms in every trial; the worst single round was 12.4 ms (a scheduling stall;
17 of 152 sampled trials had one round > 2 ms), but no timeout or adaptive event had a bracket wider than 2.3 ms
(`max_bracket_ms` in `attempts.csv`). Counters recorded: `local_ack_timeout_err`,
`roce_adp_retrans`, `roce_adp_retrans_to`, `roce_slow_restart`, `roce_slow_restart_trans`,
`packet_seq_err`, `out_of_sequence`, `implied_nak_seq_err`, `duplicate_request`, `req_cqe_error`,
`port_xmit_packets`, `port_rcv_packets`. (Sysfs `hw_counters` reads cost 0.19 ms each; the
netlink query returns them all at once.)

**Background check.** The port counters are shared with every other QP on the port: `rdma resource
show qp` listed 18 kernel `rdma_cm` RC QPs in RTS on rain's mlx5_1 (the nvmet-rdma target behind
sunny's NVMe-oF mount [inferred from the setup notes]) and anything else on the port. Measured: in the 300 ms quiet window of
all 152 sampled trials the timeout-related counters (`local_ack_timeout_err`, `roce_adp_retrans`)
changed **0** times; the background shows up only as `port_xmit_packets`+`port_rcv_packets`
pairs (~2-4 packets/s, request/response). Our retransmissions are xmit increments without an rcv
increment within 1 ms (the responder QP is in ERR and never answers); `own transmissions` below
counts those, including the original WRITE.

**Sampler perturbation.** Control cells without the sampler thread (`-N`) gave the same
detection: floor on T=14 R=7 3662.0 ms (sampled 3661.8), floor off T=8 R=7 9.39 ms (9.49),
T=14 R=7 575.1 ms (574.9) (medians; ranges in `results/20260925/tables_AB.md`, last table).

**Analysis.** `analyze.py` (per-trial timeline -> `attempts.csv`, per-cell `summary.md`) and
`tables.py` (the tables below, `tables_AB.md`). Cells run twice (floor-on T=14 R=0 in holds A2 and
A3) are separated by run index.

## A. Floor on (defaults): where 59 s comes from

### A1: T sweep at retry_cnt 7 [measured]

| T | nominal (ms) | I = 2 x nominal(max(T,16)) (ms) | N | RETRY_EXC 12/0x81 | detect median [min-max] (ms) | adaptive retransmissions | last adaptive (ms) | first regular timeout (ms) | regular interval median [min-max] (ms) | interval / nominal | regular timeouts | own transmissions | R x I - detect (ms) | (R+1) x nominal (ms) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 14 | 67.109 | 536.9 | 12 | 12/12 | 3661.8 [3547.1-3751.7] | 4-7 | 440.4 [440.2-530.2] | 977.4 [862.7-1067.3] | 536.9 [536.6-537.2] | 8.000 | 6 | 10-13 | 96.2 [6.4-211.0] | 536.9 |
| 16 | 268.435 | 536.9 | 5 | 5/5 | 3661.8 [3661.6-3738.7] | 4-7 | 440.5 [440.2-517.3] | 977.2 [977.0-1054.3] | 536.9 [536.7-537.2] | 2.000 | 6 | 10-13 | 96.3 [19.4-96.5] | 2147.5 |
| 17 | 536.871 | 1073.7 | 5 | 5/5 | 7151.7 [7151.3-7250.5] | 5-7 | 977.5 [976.9-1076.2] | 1782.7 [1782.4-1881.4] | 1073.8 [1073.5-1074.0] | 2.000 | 6 | 11-13 | 364.5 [265.7-364.9] | 4295.0 |
| 18 | 1073.742 | 2147.5 | 5 | 5/5 | 14667.8 [14667.6-15037.6] | 6-9 | 1782.5 [1782.1-2152.4] | 3929.9 [3929.8-4299.7] | 2147.6 [2147.3-2147.8] | 2.000 | 6 | 12-15 | 364.5 [-5.2-364.8] | 8589.9 |
| 19 | 2147.484 | 4295.0 | 5 | 5/5 | 29700.8 [28451.7-29701.0] | 7-9 | 3930.3 [3754.9-3930.5] | 8225.2 [6976.2-8225.7] | 4295.1 [4294.8-4295.4] | 2.000 | 6 | 13-15 | 364.0 [363.8-1613.1] | 17179.9 |
| 20 | 4294.967 | 8589.9 | 5 | 5/5 | **59766.3** [59053.5-59766.3] | 10-11 | 8225.0 [7512.2-8225.3] | 16815.4 [16102.5-16815.5] | 8590.2 [8589.9-8590.4] | 2.000 | 6 | 16-17 | 363.3 [363.2-1076.1] | **34359.7** |

T=14 includes the 2 smoke trials. Raw: `results/20260925/A/{trials,events}.csv`, per-trial
timelines `A/attempts.csv` (`adp_times_ms`, `lat_times_ms`, `own_xmit_ms`).

One trial at T=20 (`A/attempts.csv`, label `on`, T 20, trial 2), times in ms after the post:

```
adaptive (roce_adp_retrans, each with a retransmission):
  20.7 37.7 71.4 138.4 239.1 440.4 977.3 1782.4 3930.3 8225.1        (steps 17..4295)
regular (local_ack_timeout_err):
  16815.3 25405.6 33995.8 42585.9 51176.1 | 59766.1 = CQE 12/0x81 at 59766.3 (steps 8590.2)
own transmissions: original + 10 adaptive + 5 regular = 16
```

Reading the timelines:
- **Regular interval = 2 x nominal, clamped at T=16 [measured].** 536.9 ms at T=14 and T=16
  (= 2 x 4.096 us x 2^16 = 536.871 ms), then doubling with T. None of the 228 regular gaps
  deviates by more than 0.47 ms from 2 x nominal(max(T,16)).
- **Number of timeouts [measured].** Regular timeouts = R-1 in every trial with R >= 1 (A2
  below; 55/55 sampled trials with R >= 1); own transmissions = 1 + adaptive + (R-2) regular
  (R=1: 1 + adaptive - 1) in 54/55 (the other one had a retransmission masked by a background
  xmit/rcv pair within 1 ms).
- **Adaptive phase [measured].** In trials >= 2 the first adaptive retransmission is at one of
  12.3-12.7 / 20.7-21.1 / 37.2-38.0 / 71.1-71.7 ms (varies trial to trial, 42 trials) and follows the same absolute schedule (138.4, 239.0, 440.4, 977.2,
  1782.5, 3930.3, 8225.1 ms) while the step is <= nominal(max(T,16)). The first regular timeout
  then comes after min(next step, I): at T=17 the next step (805.3 ms) is shorter than I, so the
  first regular timeout is at 1782.7 ms, not at 977.5 + 1073.8.
- **First trial of every run is different [measured].** All 13 trial-1s (every R-7 cell, every
  R cell, and the no-sampler control) followed another adaptive schedule (e.g. 94, 161, 262,
  530 ms at T=14; 47, 81, 131, 265, 534, 1071, 2144, 3755 ms at T=19), giving detect 10-1250 ms
  off R x I - c. Trials 2..N (42/42) fit R x I - c within 0.9 ms. The cause (per-process or
  per-context adaptive state) was not identified. Characterised directly in section D2-D4.
- `roce_adp_retrans_to`, `roce_slow_restart*`, `packet_seq_err`, `out_of_sequence`,
  `implied_nak_seq_err`, `duplicate_request` did not change in any fault window (`d_*` columns
  of `trials.csv`); `req_cqe_error` +1 per trial (our CQE).

### A2: retry_cnt sweep at T=14 [measured]

| R | N | detect median [min-max] (ms) | adaptive retransmissions | regular timeouts per trial | own transmissions | R x I - detect, median (ms) |
|---|---|---|---|---|---|---|
| 0 | 8 | 2050.7 [977.5-2051.2] | 5-7 | 2,3,3,3,3,3,3,1 | 8 | (see text) |
| 1 | 3 | 440.6 [440.5-536.7] | 4-7 | 0,0,0 | 4-7 | 96.3 |
| 2 | 3 | 977.6 [977.2-1078.6] | 4-6 | 1,1,1 | 5-7 | 96.1 |
| 3 | 3 | 1514.3 [1347.5-1514.4] | 4-7 | 2,2,2 | 6-9 | 96.3 |
| 4 | 3 | 2051.4 [2051.2-2148.2] | 4-7 | 3,3,3 | 7-10 | 96.1 |
| 5 | 3 | 2588.2 [2587.9-2679.7] | 4-7 | 4,4,4 | 8-11 | 96.1 |
| 6 | 3 | 3124.8 [3115.2-3125.2] | 5-6 | 5,5,5 | 10-11 | 96.4 |
| 7 | 12 | 3661.8 [3547.1-3751.7] | 4-7 | 6 (all 12) | 10-13 | 96.2 |

- R >= 1: regular timeouts = R-1, detect = R x 536.9 - 96 ms (trials >= 2). At R=1 the WQE fails at
  the end of the adaptive phase (440 ms), with 4-7 retransmissions already sent.
- **R=0 does not mean "no retransmission" with the floor on [measured].** All 8 trials sent
  exactly 7 retransmissions (5-7 adaptive + 1-3 regular, 8 transmissions in total) before the
  RETRY_EXC; 6 of 8 had 3 regular timeouts like R=4 (5 of them ended at 2050.4-2051.2 ms, R=4:
  2051.4). With the floor off, R=0 behaves as expected (no retransmission, table B). Not
  explained.

### The formula (floor on, `roce_adp_retrans_en=1`, R >= 1)

```
nominal(T) = 4.096 us x 2^T
I          = 2 x nominal(max(T,16))                         regular retransmission interval
detect     = t_A + min(s_next, I) + (R-2) x I               R >= 2
           ~ R x I - c,   c = 96 ms (T<=16) / 364 ms (T>=17)  (42/42 trials >= 2 within 0.9 ms)
t_A        = end of the adaptive phase: last step <= nominal(max(T,16)) of the firmware schedule
             (440 ms T<=16, 977 T=17, 1782 T=18, 3930 T=19, 8225 T=20)
```

At T=20, R=7: 8225 + 8590 + 5 x 8590 = 59766 ms. The review's 34 s assumed (R+1) attempts of
nominal(T); the NIC runs R-1 regular attempts of **2 x** nominal plus an adaptive phase of about
one more I, which is 7 x 8.59 - 0.36 = 59.8 s.

`c` (96 / 364 ms) was fitted on these same trials, and the rule is valid for back-to-back faults
in one process only; D1 tests it out of sample, D2-D4 show where it stops (first fault of a
process).

**The NCCL GIN proxy's 57-59 s (corrected 2026-09-25 after review).** The first version of this
README said those values fall in this model's range. They do not: the model gives 59.77 s at
T=20 R=7 (back-to-back), and the smallest section-A value was 59.05 s (a first trial). The GIN
values (`../gpu-initiated/gin/results/20260923/gin_results.csv`, rows `ref60*`, `refblk*`) are
host-error times 58.44 / 58.50 s (timeout mode) and 59.07 / 59.67 s (blocking) after rank-0
start, minus a fault time that was not recorded in those runs and was taken as the median F3
fire time of other runs (1.297 s; 1.287-1.313 s there): **57.1-58.4 s fault -> host error**.
The host sees the error after the CQE, and the failing put is posted after the fault, so the
NIC's post -> CQE was at most 57.1-58.4 s. The direct fresh-process measurements (D3, D4) are
consistent with that: a fresh CPU process at T=20 R=7 took 58.46-58.79 s (N=10), and a fresh process
with GIN-like traffic before the fault 57.69-58.24 s (N=5), which overlaps the GIN range. In all
of them the regular part (6 regular timeouts spaced 8.59 s, the last one = CQE) is exact; the
history-dependent part is the first regular timeout (16.8 s back-to-back, 15.5-15.8 s fresh,
14.7-15.3 s fresh with traffic). With the GIN fault times estimated and N=4 / 5, this is agreement
in range, not a per-trial prediction.

## B. Floor off (`min_ack_timeout_limit_disabled=1`, inside `ackfloor_window.sh`) [measured]

| T | R | nominal (ms) | N | RETRY_EXC 12/0x81 | detect median [min-max] (ms) | mean +- sd (ms) | adaptive retransmissions | first timeout t1 (ms) | t1 / nominal | regular interval median [min-max] (ms) | interval / nominal | timeouts counted | own transmissions | t1 + (R+1) x nominal - detect, median (ms) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 8 | 0 | 1.049 | 5 | 5/5 | 2.24 [2.17-2.34] | 2.24 +- 0.07 | 0 | 1.20 [0.83-1.20] | 1.14 | 0.78 [0.77-1.17] | (a) | 2 | 1 | -0.04 |
| 8 | 1 | 1.049 | 3 | 3/3 | 3.11 [3.10-3.45] | 3.22 +- 0.20 | 0 | 0.82 [0.82-1.19] | 0.78 | 1.17 [1.15-1.18] | (a) | 3 | 2 | -0.18 |
| 8 | 2 | 1.049 | 3 | 3/3 | 4.57 [4.40-4.58] | 4.52 +- 0.10 | 0 | 1.18 [1.17-1.18] | 1.13 | 1.16 [0.77-1.16] | (a) | 4 | 3 | -0.25 |
| 8 | 3 | 1.049 | 5 | 5/5 | 5.43 [5.16-5.59] | 5.37 +- 0.18 | 0 | 1.18 [0.80-1.21] | 1.13 | 1.16 [0.77-1.16] | (a) | 5 | 4 | -0.14 |
| 8 | 5 | 1.049 | 3 | 3/3 | 7.33 [7.33-7.35] | 7.34 +- 0.01 | 0 | 0.80 [0.79-0.82] | 0.76 | 1.16 [0.77-1.16] | (a) | 7 | 6 | -0.24 |
| 8 | 7 | 1.049 | 10 | 10/10 | **9.49** [9.33-9.74] | 9.49 +- 0.12 | 0 | 0.83 [0.81-1.21] | 0.80 | 1.16 [0.77-1.18] | (a) | 9 | 8 | -0.14 |
| 10 | 0 | 4.194 | 5 | 5/5 | 8.38 [6.70-8.75] | 8.04 +- 0.81 | 0 | 4.26 [2.35-4.28] | 1.02 | 4.22 [3.83-4.23] | 1.006 | 2 | 1 | -0.15 |
| 10 | 3 | 4.194 | 5 | 5/5 | 20.97 [19.46-21.15] | 20.72 +- 0.71 | 0 | 4.25 [2.71-4.26] | 1.01 | 4.23 [3.84-4.26] | 1.009 | 5 | 4 | 0.03 |
| 10 | 7 | 4.194 | 5 | 5/5 | 37.91 [37.87-38.10] | 37.96 +- 0.10 | 0 | 4.26 [4.25-4.29] | 1.02 | 4.23 [3.83-4.30] | 1.009 | 9 | 8 | -0.10 |
| 12 | 0 | 16.777 | 5 | 5/5 | 29.56 [29.12-29.90] | 29.56 +- 0.32 | 0 | 12.69 [12.30-13.10] | 0.76 | 16.87 [16.46-16.88] | 1.006 | 2 | 1 | -0.04 |
| 12 | 3 | 16.777 | 5 | 5/5 | 79.94 [79.58-80.04] | 79.86 +- 0.18 | 0 | 12.70 [12.31-12.83] | 0.76 | 16.87 [16.49-17.07] | 1.005 | 5 | 4 | -0.13 |
| 12 | 7 | 16.777 | 5 | 5/5 | 147.04 [146.65-149.68] | 147.42 +- 1.28 | 0 | 12.68 [12.31-15.36] | 0.76 | 16.88 [16.47-17.09] | 1.006 | 9 | 8 | -0.12 |
| 14 | 0 | 67.109 | 5 | 5/5 | 105.07 [104.98-119.36] | 107.93 +- 6.39 | 0 | 37.98 [37.62-52.13] | 0.57 | 67.05 [66.86-67.39] | 0.999 | 2 | 1 | -0.07 |
| 14 | 3 | 67.109 | 5 | 5/5 | 306.29 [306.10-306.49] | 306.27 +- 0.16 | 0 | 37.59 [37.55-37.94] | 0.56 | 67.06 [66.86-67.46] | 0.999 | 5 | 4 | -0.11 |
| 14 | 7 | 67.109 | 10 | 10/10 | **574.90** [574.69-604.34] | 577.80 +- 9.32 | 0 | 37.92 [37.66-67.46] | 0.57 | 67.02 [66.80-67.44] | 0.999 | 9 | 8 | -0.06 |
| 16 | 7 | 268.435 | 3 | 3/3 | 2319.72 [2319.30-2333.41] | 2324.14 +- 8.03 | 0 | 172.09 [171.49-185.64] | 0.64 | 268.43 [268.17-268.71] | 1.000 | 9 | 8 | -0.29 |
| 17 | 7 | 536.871 | 3 | 3/3 | 4735.57 [4571.05-4735.71] | 4680.78 +- 95.03 | 0 | 440.25 [275.69-440.36] | 0.82 | 536.92 [536.69-537.11] | 1.000 | 9 | 8 | -0.39 |
| 18 | 7 | 1073.742 | 2 | 2/2 | 9219.88 [9140.50-9299.25] | 9219.88 +- 112.25 | 0 | 629.60 [550.23-708.97] | 0.59 | 1073.83 [1073.51-1074.03] | 1.000 | 9 | 8 | -0.34 |
| 20 | 7 | 4294.967 | 2 | 2/2 | 37939.02 [37587.71-38290.33] | 37939.02 +- 496.82 | 0 | 3578.17 [3226.80-3929.54] | 0.83 | 4295.09 [4294.88-4295.33] | 1.000 | 9 | 8 | -1.11 |

(a) At T=8 the interval (~1.05 ms) is 2.7 sampling rounds, so the event-to-event gaps are
quantized (0.77 / 1.16 ms). From the detection times instead: the slope over R at T=8 is
(9.49 - 2.24) / 7 = 1.04 ms per retry = 0.99 x nominal.

Raw: `results/20260925/B/`. Window logs: `window.log`, stamps `20260925_030437_3145591` (B) and
`20260925_051723_3366332` (B2: no-sampler controls, T=18, T=20).

- **No adaptive retransmission, interval = nominal [measured].** `roce_adp_retrans` +0 in all 99
  floor-off trials (89 sampled, 10 counted by the main thread only); every sampled trial had
  exactly R+1 own transmissions (original + R retransmissions) and R+2 `local_ack_timeout_err`
  increments (89/89).
- **t1 [measured, not explained].** The first `local_ack_timeout_err` comes at 0.51-1.16 x nominal
  (per trial) without a retransmission; the retransmissions then follow at nominal spacing
  (gap / nominal 0.91-1.02 per gap at T >= 10) and the last timeout completes the WQE. So
  detect = t1 + (R+1) x nominal (within 1.2 ms, all 89 sampled trials). Some
  t1 values coincide with the floor-on adaptive schedule points (12.7, 37.9, 440.3, 3929.5 ms),
  which hints at a common firmware timer grid [inferred].
- **Old study vs this cluster.** CX-5 (old): R=0 1.2 ms, R=3 5.9 ms, R=7 12.26 ms at T=8 (N=30).
  ConnectX-6 VPI here: 2.24 / 5.43 / 9.49 ms (N=5/5/10). Floor-on detection does not depend on T for
  T<=16 (T=14 and T=16 identical on the CPU; T=8 and T=14 identical on both GPU stacks, C), so at
  R=7 the floor-off reduction is 3661.8 / 9.49 = 386x (old study: 297x). Floor-on T=8 was not run
  on the CPU tester itself.
- Floor on vs off at T >= 17 (where the clamp does not bind): 7151.7 vs 4735.6 ms (T=17),
  14667.8 vs 9219.9 ms (T=18), 59766.3 vs 37939.0 ms (T=20). The floor-on mode is slower even
  above the clamp because of the 2x interval and the adaptive phase.

## C. GPU stage: floor off vs on [measured]

Setup. The bundles were used unchanged (`C/provenance_md5_rain.txt`; identical md5 on sunny;
they are the final builds `b2` of `../gpu-initiated/gin_q4/` and `../gpu-initiated/nvshmem_ft/`),
through their own runners (`gin_q4/scripts/run_trial.sh`, `nvshmem_ft/scripts/run_trial.sh`),
wrapped by `scripts/gpu_gin.sh` / `scripts/gpu_nvshmem.sh`. Fault "peer QP error": the
stacks' own hook moves sunny's QP to ERR (GIN: 600 ms after start; NVSHMEM: 800 ms after
connect); rain's next put gets no ACK and ends in RETRY_EXC on rain's QP (the side whose register
was changed). Timeout-mode waits; GIN: ring CQ, `NCCL_GIN_FAULT_CLASSIFY=1`; NVSHMEM:
`NVSHMEM_IBGDA_FT=1`, GPU NIC handler, classification only (the initiator declines, both PEs
tear down). IB timeout knobs: `NCCL_IB_TIMEOUT` (GDAKI passes it to `doca_verbs_qp_attr_set_ack_timeout`,
`gin_host_gdaki.cc:534`; retry count `NCCL_IB_RETRY_CNT`, default 7) and `NVSHMEM_IB_TIMEOUT`
(`ibgda.cpp:2023`, `primary_address_path.ack_timeout`; `NVSHMEM_IB_RETRY_CNT=7`). No knob was
missing and nothing was rebuilt. Each trial is a fresh process pair. Floor-off cells ran in two
windows (`C_gin` 20260925_063047_3507400, 668 s; `C_nvshmem` 20260925_064535_3532116, 70 s);
the floor-on controls ran without a window (hold `ackC-on`).

Times are ms after the fault on rain's `CLOCK_MONOTONIC`, as each stack's own row tool computes
them (`q4_row.py`, `rows.py`); "failing op posted -> error" isolates the NIC part: GIN = the
driver's `device_rc_ms` (start of the failing iteration -> device wait returned the error,
host-observed with a 0.5 ms poll), NVSHMEM = `post_to_dev_ms` (post of the failing put -> device
record). The fault -> fingerprint column was recomputed from the raw logs (hook `fire_mono_ms`
on sunny, clock offset, mailbox `mono_ms` on rain) with identical results.

| stack | floor | IB timeout T | N | class (fingerprint) | failing op posted -> error (ms) | fault -> device detection (ms) | fault -> host-visible fingerprint (ms) | fault -> `ncclCommGetAsyncError` (ms) | teardown / leftover procs |
|---|---|---|---|---|---|---|---|---|---|
| GIN GDAKI + device classifier | **off** | 8 | 10 | RETRY_EXC 12/0x81 (10/10) | 10.2 [10.2-10.3] | 24.5 [14.1-25.2] | **24.6** [14.2-25.3] | 24.7 [14.3-25.5] | clean / 0 |
| GIN GDAKI + device classifier | **off** | 10 | 10 | RETRY_EXC 12/0x81 (10/10) | 37.3 [36.7-38.4] | 51.8 [50.5-52.8] | **51.9** [50.7-52.9] | 52.1 [50.8-53.0] | clean / 0 |
| GIN GDAKI + device classifier | **off** | 14 | 10 | RETRY_EXC 12/0x81 (10/10) | 584.3 [574.2-598.0] | 599.2 [587.8-612.6] | **599.3** [587.9-612.6] | 599.5 [588.0-612.8] | clean / 0 |
| GIN GDAKI + device classifier | on | 8 | 2 | RETRY_EXC 12/0x81 (2/2) | 3596.1 [3576.3-3615.9] | 3610.0 [3590.6-3629.4] | 3610.1 [3590.7-3629.5] | 3610.3 [3590.9-3629.7] | clean / 0 |
| GIN GDAKI + device classifier | on | 14 | 1 | RETRY_EXC 12/0x81 (1/1) | 3616.0 | 3630.5 | 3630.5 | 3630.7 | clean / 0 |
| NVSHMEM IBGDA + FT | **off** | 8 | 10 | RETRY_EXC 12/0x81 (10/10) | 9.5 [9.3-10.1] | 13.2 [12.8-18.7] | **13.3** [12.8-18.8] | - | returned / 0 |
| NVSHMEM IBGDA + FT | **off** | 10 | 10 | RETRY_EXC 12/0x81 (10/10) | 36.8 [36.0-37.6] | 40.4 [39.4-41.6] | **40.4** [39.4-41.6] | - | returned / 0 |
| NVSHMEM IBGDA + FT | **off** | 14 | 10 | RETRY_EXC 12/0x81 (10/10) | 581.4 [571.4-603.3] | 585.0 [575.0-606.9] | **585.1** [575.1-606.9] | - | returned / 0 |
| NVSHMEM IBGDA + FT | on | 8 | 2 | RETRY_EXC 12/0x81 (2/2) | 3536.3 [3527.5-3545.1] | 3539.8 [3531.0-3548.7] | 3539.9 [3531.0-3548.7] | - | returned / 0 |
| NVSHMEM IBGDA + FT | on | 14 | 1 | RETRY_EXC 12/0x81 (1/1) | 3558.3 | 3567.0 | 3567.1 | - | returned / 0 |

Medians [min-max]. Raw: `results/20260925/C/` (`gin_<floor>_T<T>.csv` + `logs/`,
`nvshmem_<floor>_T<T>_rec0/` per-trial `.meta`/logs, `nvshmem_trials.csv`, `nvshmem_events.csv`,
`summary.md` = this table from `c_summary.py`).

- **Floor off, the host sees the exact fingerprint 13 ms (NVSHMEM) / 25 ms (GIN) after the fault
  at T=8, 40 / 52 ms at T=10, 585 / 599 ms at T=14**, against 3.54 / 3.61 s with the defaults at
  the same T=8 (266x / 147x). With the floor on, T=8 and T=14 give the same ~3.6 s (the clamp).
- **The NIC part equals the CPU measurement.** Post of the failing op -> error: NVSHMEM 9.5 /
  36.8 / 581.4 ms, GIN 10.2 / 37.3 / 584.3 ms, CPU verbs (B) 9.49 / 37.91 / 574.90 ms at T=8 / 10 /
  14. The rest of fault -> fingerprint is the application's own gap until it next touches the
  broken QP (NVSHMEM fault -> kernel start 3.6 ms median; GIN ~14 ms, its 15 ms iteration gap)
  plus device -> mailbox (50-100 us medians).
- **Classification and teardown are unchanged.** 60/60 floor-off trials recorded RETRY_EXC
  12/0x81 for the root-cause WQE (GIN: WQE 76, 74 in one trial, polled trailing CQE 5/0xf9;
  NVSHMEM: WQE 117), host QUERY_QP ERR (GIN), OOB liveness "alive" (NVSHMEM), no silent success,
  GIN `ncclCommAbort` clean, NVSHMEM `nvshmem_finalize` returned on both PEs (17-20 ms on PE0),
  no process left on either node.
- **No spurious failure before the fault** at T=8 floor off (nominal 1 ms): GIN completed 37-38
  iterations and NVSHMEM 51/51 (data verified on PE1) before the injected fault in every trial.
  This is 20 short runs on an idle direct link, not evidence of safety under load.
- With the floor on, the GPU values (post -> error 3.53-3.62 s, 6 trials) are not the CPU steady
  state (3.66 s). Every GPU trial is a fresh process; the direct CPU fresh-process measurement (D2)
  gave 3.50-3.76 s at T=14, but typically 3.74-3.76 s, so the GPU values lie inside that range
  and away from its usual value. Read through the regular part (detect = t_L1 + 5 x 536.9 ms,
  which held in every CPU trial), they correspond to t_L1 = 0.84-0.93 s, a first regular timeout
  seen neither in steady state (0.977 s) nor in the usual fresh-process case (1.06-1.08 s). The
  GPU QPs carried 37-51 successful iterations before the fault, the CPU QPs one WRITE. Adding
  GIN-like traffic before the fault to fresh CPU processes (D4) moved them to 3.59-3.75 s
  (median 3.73 s): the GIN value (3.62 s at T=14, 3.58-3.62 s at T=8) is inside that range, the
  NVSHMEM values (3.53-3.56 s, 51 iterations of a different pattern) still below it. So history
  explains part of the difference; the rest is not reproduced [measured / not identified].
- Not run: recovery. With NVSHMEM FT's measured ~3 ms host recovery (`../gpu-initiated/nvshmem_ft/`),
  fault -> recovered would be ~16 ms at T=8 floor off [inferred, not measured].

## D. Review follow-up: out-of-sample check and fresh processes (floor on, no register change)

### D1a. Predictions, written before the measurement

(The text of this subsection is kept as written before the run; its md5 `52de8f0a...` is in
`oos/prereg.txt`, recorded 14:11:52, and the exact text in `oos/prereg_section.md`; the
pre-run `predict.py` is kept as `oos/predict_prereg.py`.)

Written 2026-09-25 14:11 KST, before any of the runs below: `predict.py` (md5 `9ce7ab8f...`) encodes
the section-A model unchanged (schedule points, `max(T,16)` clamp, `min(s_next, I)` rule, as
fitted on `results/20260925/A` trials >= 2) and wrote `results/20260925/oos/predictions.csv`
(md5 `dbc6ed2a...`, mtime 14:11:19). None of these (T, R) cells was measured before, except
T=16 R=7, which is repeated as a replicate. Acceptance criterion, fixed in advance: every
non-first trial within 1.5 ms of the predicted detection time.

| T | R | I (ms) | t_A end of adaptive phase (ms) | first regular timeout (ms) | regular timeouts | adaptive retransmissions | predicted detect (ms) |
|---|---|---|---|---|---|---|---|
| 10 | 7 | 536.87 | 440.4 | 977.2 | 6 | 4-7 | 3661.55 |
| 12 | 7 | 536.87 | 440.4 | 977.2 | 6 | 4-7 | 3661.55 |
| 15 | 7 | 536.87 | 440.4 | 977.2 | 6 | 4-7 | 3661.55 |
| 16 | 7 | 536.87 | 440.4 | 977.2 | 6 | 4-7 | 3661.55 |
| 15 | 1 | 536.87 | 440.4 | - | 0 | 4-7 | 440.40 |
| 15 | 3 | 536.87 | 440.4 | 977.2 | 2 | 4-7 | 1514.07 |
| 15 | 5 | 536.87 | 440.4 | 977.2 | 4 | 4-7 | 2587.81 |
| 17 | 1 | 1073.74 | 977.2 | - | 0 | 5-8 | 977.20 |
| 17 | 2 | 1073.74 | 977.2 | 1782.5 | 1 | 5-8 | 1782.50 |
| 17 | 3 | 1073.74 | 977.2 | 1782.5 | 2 | 5-8 | 2856.24 |
| 17 | 5 | 1073.74 | 977.2 | 1782.5 | 4 | 5-8 | 5003.73 |

What each cell tests: T=10/12/15 the `max(T,16)` clamp below T=14 and between 14 and 16 (without
the clamp, T=10 would give a regular interval of 8.4 ms, not 536.9 ms); T=17 R=2 the
`min(s_next, I)` rule directly (first regular timeout at 1782.5 = 977.2 + 805.3, against 2050.9 =
977.2 + I without it); R=1 that the WQE fails at the end of the adaptive phase.

For fresh processes (D2) the model makes no timing prediction for the adaptive phase, because the
13 first trials of section A did not follow its schedule. Hypothesis written in advance: the
regular part (spacing I, R-1 regular timeouts, last one = CQE) holds in a fresh process too;
only the adaptive phase differs.

### D1b. Out-of-sample result [measured]

Run 2026-09-25 14:34-14:40 (hold `ackD1-oos`), N=6 per cell, trial 1 of every cell excluded from
the score (review item: non-first trials). `predict.py --check results/20260925/oos`
(`oos/check.md`); after the run `predict.py` was edited only in its `--check` printing (an empty
list guard); the prediction file is unchanged (md5 `dbc6ed2a...` re-generated identically).

| T | R | non-first trials | predicted (ms) | measured median [min-max] (ms) | error median [min-max] (ms) | within 1.5 ms | regular timeouts (pred / meas) | regular interval (pred / meas median) | first regular timeout (pred / meas median) | trial 1 detect (error) |
|---|---|---|---|---|---|---|---|---|---|---|
| 10 | 7 | 5 | 3661.55 | 3660.96 [3658.98-3661.26] | -0.59 [-2.57--0.29] | 4/5 | 6 / 6 | 536.9 / 536.9 | 977.2 / 976.5 | 3685.7 (+24.2) |
| 12 | 7 | 5 | 3661.55 | 3661.02 [3660.82-3661.17] | -0.54 [-0.74--0.39] | 5/5 | 6 / 6 | 536.9 / 536.9 | 977.2 / 976.4 | 3739.8 (+78.3) |
| 15 | 1 | 5 | 440.40 | 439.72 [439.61-440.11] | -0.68 [-0.79--0.29] | 5/5 | 0 / 0 | - | - / - | 534.4 (+94.0) |
| 15 | 3 | 5 | 1514.07 | 1513.52 [1513.04-1513.71] | -0.55 [-1.03--0.36] | 5/5 | 2 / 2 | 536.9 / 536.9 | 977.2 / 976.3 | 1613.6 (+99.5) |
| 15 | 5 | 5 | 2587.81 | 2587.13 [2587.09-2587.35] | -0.68 [-0.72--0.47] | 5/5 | 4 / 4 | 536.9 / 536.8 | 977.2 / 976.4 | 2675.7 (+87.9) |
| 15 | 7 | 5 | 3661.55 | 3660.74 [3660.47-3661.12] | -0.82 [-1.09--0.44] | 5/5 | 6 / 6 | 536.9 / 536.9 | 977.2 / 976.3 | 3758.2 (+96.6) |
| 16 | 7 | 5 | 3661.55 | 3660.94 [3660.75-3661.08] | -0.61 [-0.81--0.47] | 5/5 | 6 / 6 | 536.9 / 536.9 | 977.2 / 976.4 | 3758.9 (+97.4) |
| 17 | 1 | 5 | 977.20 | 976.75 [976.52-976.83] | -0.45 [-0.68--0.37] | 5/5 | 0 / 0 | - | - / - | 1059.2 (+82.0) |
| 17 | 2 | 5 | 1782.50 | 1781.81 [1781.54-1782.23] | -0.69 [-0.96--0.27] | 5/5 | 1 / 1 | - | 1782.5 / 1781.6 | 2143.5 (+361.0) |
| 17 | 3 | 5 | 2856.24 | 2855.57 [2848.67-2855.75] | -0.67 [-7.57--0.50] | 4/5 | 2 / 2 | 1073.7 / 1073.6 | 1782.5 / 1781.7 | 2940.1 (+83.8) |
| 17 | 5 | 5 | 5003.73 | 5003.27 [4996.15-5003.44] | -0.46 [-7.58--0.28] | 4/5 | 4 / 4 | 1073.7 / 1073.8 | 1782.5 / 1782.0 | 5101.7 (+98.0) |

- **52/55 non-first trials within the 1.5 ms set in advance; median error -0.45 to -0.82 ms per
  cell** (all cells slightly early: the frozen schedule points were counter-event midpoints,
  which lag the firmware event by a fraction of a sampling round [inferred]).
- **The structural predictions held in 55/55:** R-1 regular timeouts; regular interval 536.9 ms at
  T=10, 12 and 15 (the clamp: without it T=10 would space them 8.4 ms apart); the first regular
  timeout at T=17 R=2 at 1781.6 ms, i.e. t_A + 805 ms, as `min(s_next, I)` predicts (t_A + I would
  be 2050.9 ms); R=1 fails at the end of the adaptive phase (439.7 / 976.8 ms).
- **The 3 misses (-2.6, -7.6, -7.6 ms)** had their whole adaptive schedule shifted earlier by the
  same amount, with extra early entry points: e.g. T=17 R=3 trial 2: 6.85, 8.78, 13.0, 21.4, 38.3,
  63.5, 130.5, 231.1, 432.8, 969.3 ms (vs 440.4 / 977.2), then the regular part exact. Two of
  them also had 10 adaptive retransmissions (predicted 5-8). The schedule is therefore not
  anchored exactly to the post; in ~5% of back-to-back trials it runs a few ms early [measured,
  cause unknown]. In-sample (section A) no such shift was seen in 42 trials.
- **Trial 1 of every cell was again off**, this time always late (+24 to +361 ms), see D2.
- Other checks: 66/66 RETRY_EXC 12/0x81, warm-up write ok 66/66, `T_q,R_q` = requested 66/66,
  timeout counters quiet in every quiet window; own transmissions = 1 + adaptive + (R-2) in 54/55
  (one masked by a background xmit/rcv pair). Raw: `results/20260925/oos/`.

### D2. Fresh processes, fresh contexts, idle gaps [measured]

Modes (all floor on, T=14 and T=17 at R=7, `results/20260925/fresh/`, hold `ackD2-fresh`
14:43-14:49; T=20 in `results/20260925/fresh20/`):
- `freshP`: every trial is a new requester **and** responder process (`run_cpu.sh ... 1`, 10
  times): new device context, PD, CQ, MR, QP, new control connection, ~3 s between trials
  (ssh, GID probe, server start). This is what every GPU/NCCL trial is.
- `ctxF` (`ackt -F`): one process; the device context (PD, MR, CQ) is closed and reopened before
  every trial; trials ~1 s apart as in section A.
- `gap5s` (`ackt -G 5000`): one process and context; 5 s idle before every trial.

`fresh_check.py results/20260925/fresh`:

| mode | T | trials | detect median [min-max] (ms) | steady model | detect - model (ms) | t_A last adaptive (ms) | t_L1 first regular timeout (ms) | t_L1 - t_A (ms) | regular timeouts = R-1 | max abs(gap - I) (ms) | max abs(detect - (t_L1 + (R-2) I)) (ms) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| freshP | 14 | 10 | 3750.1 [3499.9-3764.0] | 3661.6 | +88.6 [-161.7..+102.5] | 528.8 [412.5-542.5] | 1065.6 [815.4-1079.7] | 536.9 [402.8-537.2] | 10/10 | 0.32 | 0.37 |
| freshP | 17 | 10 | 7257.2 [7234.7-7500.4] | 7151.2 | +106.0 [+83.5..+349.2] | 1063.2 [812.6-1095.0] | 1888.3 [1865.7-2131.3] | 805.5 [805.2-1074.0] | 10/10 | 0.32 | 0.34 |
| ctxF, trials >= 2 | 14 | 10 | 3635.4 [3632.8-3639.8] | 3661.6 | -26.2 [-28.8..-21.8] | 415.6 [411.4-552.5] | 950.7 [948.3-955.4] | 536.7 [402.5-537.0] | 10/10 | 0.32 | 0.33 |
| ctxF, trials >= 2 | 17 | 10 | 7127.7 [7123.3-7128.8] | 7151.2 | -23.5 [-27.9..-22.4] | 953.4 [949.0-954.7] | 1758.6 [1754.4-1760.0] | 805.4 [805.0-805.7] | 10/10 | 0.40 | 0.44 |
| gap5s, trials >= 2 | 14 | 10 | 3761.2 [3761.0-3761.4] | 3661.6 | +99.7 [+99.4..+99.8] | 539.8 [539.5-540.1] | 1076.7 [1076.5-1077.0] | 537.0 [536.7-537.1] | 10/10 | 0.37 | 0.31 |
| trial 1 of ctxF / ctxF / gap5s | 14 / 17 / 14 | 1 each | 3502.5 / 7521.9 / 3604.2 | | -159.1 / +370.7 / -57.3 | | 818.0 / 2152.9 / 919.7 | 402.6 / 1073.9 / 402.6 | 3/3 | | |

What the model describes, and what not:
- **Described in every trial (53/53 here; 205/205 over all sampled floor-on trials with R >= 1,
  see TL;DR):** the regular part. After the
  adaptive phase come exactly R-1 regular timeouts spaced I = 2 x nominal(max(T,16)) (worst gap
  error 0.44 ms), the last one is the CQE, so **detect = t_L1 + (R-2) x I within 0.44 ms**. Also
  t_L1 - t_A is always I or 0.75 x I (402.6 / 536.9 ms at T=14; 805.3 / 1073.9 ms at T=17): in all
  177 floor-on trials with both events (sections A, D1-D3), 128 at I and 49 at 0.75 x I, none else.
- **Not described:** where the adaptive phase ends (t_A) and so where the regular part starts
  (t_L1). The steady-state value (t_L1 = 977.2 ms at T<=16, 1782.5 ms at T=17) holds only for
  back-to-back trials in one process and context (section A, D1). It moves with the history:
  a 5 s idle gap shifts it by +99.5 ms (10/10, spread 0.5 ms), reopening the device context by
  -26 ms (10/10, spread 7 ms), and a fresh process pair lands at +80..+102 ms in 9/10 (T=14) and
  +84..+118 ms in 9/10 (T=17), with one outlier each (-162 ms at T=14, +349 ms at T=17).
- So for a fresh process, which is every GPU/NCCL measurement, **detect = t_L1 + (R-2) x I with
  t_L1 unknown in advance**; at T=14 R=7 it measured 3500-3764 ms (model 3661.6), at T=17
  7235-7500 ms (model 7151.2). The spread (T=14: 264 ms, T=17: 266 ms, T=20: 336 ms in D3) comes
  from t_L1 alone.
- **Which condition reproduces the first-trial schedule:** none exactly. The idle gap alone
  reproduces the typical fresh-process shift (+99.7 ms vs +80..+102 ms); reopening the context
  alone gives a different, stable shift (-26 ms); the first trial of each mode, and the fresh
  outliers, are unlike both. The dependence on idle time points to firmware state that ages
  between faults (e.g. an RTT/backoff estimate per function or port) [inferred, not identified].
  All values here come from one warm-up WRITE before the fault; a QP that carried traffic
  before the fault (the GPU runs: 37-51 iterations) starts from yet another state (D4).

### D3. Fresh processes at T=20, R=7 (N=10) [measured]

`results/20260925/fresh20/` (hold `ackD3-fresh20`, 15:18-15:28), mode `freshP` as in D2:

| mode | T | trials | detect median [min-max] (ms) | steady model | detect - model (ms) | t_A last adaptive (ms) | t_L1 first regular timeout (ms) | t_L1 - t_A (ms) | regular timeouts = R-1 | max abs(gap - I) (ms) | max abs(detect - (t_L1 + 5 I)) (ms) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| freshP | 20 | 10 | **58780.4** [58458.2-58794.4] | 59764.7 | -984.3 [-1306.6..-970.3] | 7239.4 [6916.5-7253.1] | 15829.4 [15506.8-15843.3] | 8590.2 [8589.9-8590.4] | 10/10 | 0.52 | 1.67 (b) |

(b) the measured I is 8590.2 ms, 0.27 ms above 2 x nominal(20); over 5 intervals that is 1.35 ms.

- At T=20 a fresh process is ~1 s **faster** than the back-to-back steady state (58.46-58.79 s vs
  59.77 s), while at T=14/17 it was ~0.1 s slower. The regular part is again exact (6 regular
  timeouts, spaced 8590.2 ms); the difference is in the adaptive phase: in fresh processes its
  last points were ... 1054-1079, 1860-1884, 4007-4032, 7229-7253 ms (9/10) (steps ~805, 2148, 3221 =
  0.75 x nominal(20)), in steady state ... 977, 1782, 3930, 8225 ms (last step 4295 = nominal(20)).
- One trial (58458 ms) ended its adaptive phase one point earlier (6916.5 ms), the same kind of
  outlier as at T=14/17.
- For item A this means: at NCCL's default T=20, R=7 the time to RETRY_EXC for a fresh process is
  58.5-58.8 s (N=10), not 59.8 s; both are far from the naive 34.4 s, and 42.95 s of it
  (5 x 8.59 s after the first regular timeout) is fixed by the regular part.

### D4. Fresh processes with GPU-like traffic before the fault [measured]

The GPU drivers run 37-51 successful put+signal iterations on the QP before the fault; D2/D3 had
one WRITE. `ackt -P 37:15:262144` posts 37 signaled 256 KiB WRITEs 15 ms apart (the GIN driver's
iteration pattern) right before the fault (`scripts/d4_traffic.sh`, `results/20260925/freshW/`,
hold `ackD4-traffic` 15:33-15:39; 37/37 WRITEs completed in every trial):

| mode | T | trials | detect median [min-max] (ms) | steady model | detect - model (ms) | t_L1 first regular timeout (ms) | regular timeouts = R-1 | max abs(detect - (t_L1 + 5 I)) (ms) |
|---|---|---|---|---|---|---|---|---|
| freshW (fresh process + traffic) | 14 | 10 | 3726.3 [3594.6-3745.9] | 3661.6 | +64.7 [-66.9..+84.3] | 1041.8 [910.0-1061.2] | 10/10 | 0.38 |
| freshW (fresh process + traffic) | 20 | 5 | **58216.8** [57693.1-58238.2] | 59764.7 | -1547.9 [-2071.6..-1526.5] | 15265.9 [14742.1-15287.4] | 5/5 | 1.32 |
| warmS (one process + traffic), trials >= 2 | 14 | 5 | 3640.2 [3639.9-3640.3] | 3661.6 | -21.4 [-21.7..-21.2] | 955.7 [955.4-955.7] | 5/5 | 0.26 |

- Prior traffic moves t_L1 again (T=14: fresh 1065.6 -> 1041.8 ms median; back-to-back 977.2 ->
  955.7 ms; T=20: fresh 15829 -> 15266 ms), the regular part stays exact (21/21).
- At T=20 the fresh-with-traffic runs gave 57.69-58.24 s, the range of the GIN proxy measurement
  (next paragraph).

### What changes in the earlier text (review items 1-3)

- Section A's formula with the fitted c describes **back-to-back faults in one process**; it
  predicted such trials out of sample within 1.5 ms in 52/55 (D1). It does not predict the
  first fault of a process, which is the GPU/NCCL case: there only the regular part holds, and
  the start of the regular part t_L1 depends on history (D2-D4). Across all modes measured,
  RETRY_EXC at R=7 came 3.50-3.76 s after the post at T=14 and 57.7-59.8 s at T=20.
- The GIN proxy statement is corrected in section A (item 3).

## Register window (`ackfloor_window.sh`, `ackfloor_guardian.sh`)

- **Lock precondition (fail closed, fixed 2026-09-25 after review).** The first version tested
  `flock -n <hard-coded path> true` and refused only if that *succeeded*; any flock(1) error
  (e.g. exit 66 when the path could not be opened) was taken as "held" and the register change
  went ahead. Now, before the first register access, the window refuses (exit 64) unless all of
  these hold: (1) the nearest ancestor process runs `cluster_run.sh`; (2) that process's fd 9 is
  an existing, not deleted, regular file; (3) `/proc/<it>/fdinfo/9` shows a FLOCK WRITE lock on
  that inode and `flock -n -E 75` on the file returns exactly 75 (any other status, including an
  error, refuses); (4) the ancestor runs this repository's `../gpu-initiated/common/cluster_run.sh`;
  (5) the locked file is the shared lock as that script defines it (its `SCRATCH`/`LOCK` lines
  evaluated with `CLUSTER_LOCK` unset), so `CLUSTER_LOCK=<private file> cluster_run.sh` is refused.
  No lock path is hard-coded in the window any more. `ACKFLOOR_CHECK_ONLY=1` runs the checks and
  exits before any register access (for tests).
- (a) reads and saves the full ROCE_ACCL of 17:00.1 (19 fields) and refuses unless
  `min_ack_timeout_limit_disabled` is 0; also saves 17:00.0's ROCE_ACCL (read only);
- (b) `mlxreg -d 17:00.1 --reg_name ROCE_ACCL --yes --set "<all 9 *_field_select=0 except
  min_ack_timeout_limit_disabled_field_select=1>,min_ack_timeout_limit_disabled=1"`, then re-reads:
  the field must be 1 and the other 18 unchanged;
- (c) runs the command in its own process group (`setsid`);
- (d) EXIT/INT/TERM/HUP trap: TERM to the command group, write back the saved value (same
  field-select form), re-read, compare all 19 fields with the before dump (3 attempts), then
  re-read 17:00.0; exit = command's status (70 if the restore could not be verified);
- a detached guardian waits for the window's pid (checked with its /proc start time) and, if the
  window died without leaving its `.restored` marker (SIGKILL), writes the saved value back and
  logs the full state.

Tested before first use (`scripts/test_window.sh`, `results/20260925/window_test.out`, all under
the cluster lock): `true`; a read inside the window (`0x00000001`); command SIGKILLed (window rc
137, restored); window SIGTERMed (rc 143, command group stopped, restored); window SIGKILLed
(guardian restored within 0.5 s); lock not held (refused, register untouched). Every case read
0 afterwards.

Lock-check refusal paths (`scripts/test_lockcheck.sh`, run inside a real hold
`ackW-lockcheck2`, `results/20260925/lockcheck_test2.out`): every case ran with
`ACKFLOOR_CHECK_ONLY=1`; cases A and B were repeated on the real path (no CHECK_ONLY) only after
their CHECK_ONLY run had refused.

| case | setup | result |
|---|---|---|
| A | window re-parented to init (no `cluster_run.sh` ancestor) | refused, check 1 (CHECK_ONLY and real path) |
| B | fake `cluster_run.sh` with fd 9 open, no lock taken | refused, check 3 (CHECK_ONLY and real path) |
| C | fake `cluster_run.sh` holding a flock on its own file | refused, check 4 |
| D | fake `cluster_run.sh` without fd 9 | refused, check 2 |
| E | the real `cluster_run.sh` with `CLUSTER_LOCK=<private file>` | refused, check 5 |
| F | the real `cluster_run.sh` whose lock file was deleted | refused, check 2 ("(deleted)") |
| G | positive control, directly under the real hold | checks passed (CHECK_ONLY exit 0) |

ROCE_ACCL of 17:00.1 read before and after the test: identical in all 19 fields; the window log
gained 10 lines, none of them BEFORE/SET/RESTORED. (The first run, `lockcheck_test.out`, had a
bug in the test harness of case A, which reported "not re-parented" and did not run the window;
fixed and re-run as above.) The dumps of every window are in `results/20260925/window/<stamp>_<tag>_*.txt`
(`before`, `after_set`, `after_restore`, `before_17:00.0`, `after_17:00.0`).

## Caveats

- **The setting is NIC-function-wide and live [measured scope, inferred effects].** It changes
  the retransmission behaviour of every RC QP on rain's 17:00.1 (mlx5_1) for as long as it is set,
  not only ours: the 18 kernel `rdma_cm` QPs (the nvmet-rdma target that serves sunny's NVMe-oF
  mount [inferred]) and any QP that `mooncake_client` (`--device_names=mlx5_1`) opens. Measured here: with the
  floor off, new QPs get no adaptive retransmission and a 1x instead of 2x interval, and a QP
  with a small T gives up after ~(R+2) x nominal of silence (T=8 R=7: 9.5 ms). A PFC pause, a
  congested switch or a busy responder that stalls ACKs for longer than that turns into a
  RETRY_EXC and a dead queue pair. Whether already-established QPs (the NVMe-oF ones) pick up the
  change was not measured; their timeout is set by `rdma_cm` (typically T around 18 from the
  packet lifetime [inferred from kernel defaults, not read on this host]).
- **Scope [measured]:** 17:00.0 (rain's other port, link down) read identical before and after
  every window; the setting is per PCI function here. Sunny's NIC keeps the floor, so the two
  directions are asymmetric (sunny's QPs still retransmit with the adaptive phase and 2x).
- The register was set only inside windows: 74 s (B), 106 s (B2), 668 s (C_gin), 70 s (C_nvshmem),
  plus < 3 s per test case; always restored and verified (window log, dumps). Holds are logged in
  the shared `cluster_run.log` under tags `ack*`.
- **Scope of the floor-on formula [measured, section D].** `detect = R x I - c` holds for faults
  back-to-back in one process (52/55 out of sample within 1.5 ms). For the first fault of a
  process (GPU/NCCL), after an idle gap, with a fresh device context or after prior traffic,
  only the regular part holds (detect = t_L1 + (R-2) x I); detect moved by -165..+371 ms at
  T=14/17 (R=7) and by -2.07..-0.71 s at T=20 against the back-to-back model. The firmware state behind this
  was not identified.
- The adaptive schedule, the trial-1 effect, R=0 with the floor on, and t1 with the floor off are
  firmware behaviour of fw 20.43.4100 observed from counters; no firmware documentation was
  consulted. A single node pair, direct cable, no switch.
- Counter timing resolution ~0.4 ms (worst bracket 2.3 ms); T=8 intervals are therefore taken
  from the R-slope of detect, not from event gaps.

## Files

| path | what |
|---|---|
| `src/ackt.c`, `Makefile` | tester (responder + requester + counter sampler / monitor `-M`) |
| `scripts/run_cpu.sh`, `sweep_cpu.sh` | one cell / several cells in one hold |
| `ackfloor_window.sh`, `ackfloor_guardian.sh`, `scripts/test_window.sh` | register window, guardian, restore-path tests |
| `scripts/gpu_gin.sh`, `scripts/gpu_nvshmem.sh` | GPU trials through the unchanged `gin_q4` / `nvshmem_ft` runners and bundles |
| `analyze.py`, `tables.py`, `qa_check.py` | per-trial timelines, tables, independent re-computation of the CPU claims |
| `predict.py` | the frozen floor-on model as a predictor (`--csv`) and the out-of-sample check (`--check`) |
| `fresh_check.py` | fresh-process / fresh-context / idle-gap / prior-traffic characterisation (D2-D4) |
| `qa_check_d.py` | independent re-computation of the section-D claims from the raw files (`results/20260925/qa_check_d.out`) |
| `scripts/test_lockcheck.sh` | refusal paths of the window's lock check (no register access) |
| `results/20260925/oos/` | D1: `prereg.txt`, `predictions.csv`, trials/events/attempts, `check.md` |
| `results/20260925/fresh/`, `fresh20/`, `freshW/` | D2/D3/D4: fresh-process, fresh-context, idle-gap and prior-traffic runs |
| `scripts/d4_traffic.sh` | D4 cells (fresh processes with 37 x 256 KiB WRITEs before the fault) |
| `results/20260925/lockcheck_test2.out` | lock-check test (first attempt with the case-A harness bug: `lockcheck_test.out`) |
| `results/20260925/{smoke,A,B}/` | `trials.csv`, `events.csv`, `attempts.csv`, `summary.md`, per-cell logs, hold outputs |
| `c_summary.py` | GPU table (Task C) |
| `results/20260925/C/` | GPU trials (CSV + per-trial logs, `summary.md`, bundle md5) |
| `results/20260925/window.log`, `window/` | every window's log and register dumps |
