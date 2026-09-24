# RETRY_EXC detection vs IB ACK timeout: the firmware floor, the 34 s vs 59 s gap, and the GPU stage

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

- **The 34 s vs 59 s gap is explained [measured, T=20 R=7: 59.05-59.77 s, N=5].** With the
  firmware defaults the NIC does not make "R+1 attempts of 4.096 us x 2^T". Per fault it runs
  1. an **adaptive-retransmission phase**: 4-11 early retransmissions on a firmware schedule
     (typical steps 8.6, 16.6, 33.7, 67.1, 100.6, 201.4, 536.8, 805.3, 2147.8, 4294.8 ms), counted
     in `roce_adp_retrans`, not in `local_ack_timeout_err`. It continues while the step is at most
     nominal(max(T,16)) (within 0.3 ms) and, whatever its length, uses up **one** unit of `retry_cnt`;
  2. then **R-1 regular ACK timeouts** (`local_ack_timeout_err`), spaced exactly
     **I = 2 x 4.096 us x 2^max(T,16)**: 536.9 ms for T<=16, then 1073.8 / 2147.6 / 4295.1 /
     8590.2 ms at T=17/18/19/20 (interval / nominal(max(T,16)) = 2.000 in every cell). The first R-2 of them
     retransmit; the last one completes the WQE with RETRY_EXC 12/0x81 (0.37 ms before to 0.07 ms
     after the CQE was polled).

  At T=20, R=7: adaptive phase to 8.225 s (10-11 retransmissions), first regular timeout at
  16.815 s, then 5 x 8.590 s -> **59.766 s**. Every floor-on trial after the first of each run
  (42/42, R=1..7, T=14..20) fits **detect = R x I - c** within 0.9 ms, c = 96 ms (T<=16) or
  364 ms (T>=17). The naive (R+1) x nominal is short by the factor ~2R/(R+1) = 1.75 at R=7:
  59.8 / 34.4 = 1.74. The GIN proxy's 57-59 s (earlier stage) is this, measured through NCCL.
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
  per-context adaptive state) was not identified.
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
one more I, which is 7 x 8.59 - 0.36 = 59.8 s. The 57-59 s seen by NCCL GIN (proxy, peer QP error, 4 trials,
`../gpu-initiated/RESULTS.md` item 6) is within this range; the GIN fault time is when sunny's QP
went to ERR, and the first unacknowledged put can come up to one iteration gap later [inferred].

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
- With the floor on, the GPU values (3.53-3.63 s) sit below the CPU steady state (3.66 s) and among
  the CPU trial-1 values (3.50-3.75 s); every GPU trial is a new process, which fits the trial-1
  effect of A [inferred].
- Not run: recovery. With NVSHMEM FT's measured ~3 ms host recovery (`../gpu-initiated/nvshmem_ft/`),
  fault -> recovered would be ~16 ms at T=8 floor off [inferred, not measured].

## Register window (`ackfloor_window.sh`, `ackfloor_guardian.sh`)

- Must run under `cluster_run.sh` (refuses with exit 64 if the cluster lock is free).
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
0 afterwards. The dumps of every window are in `results/20260925/window/<stamp>_<tag>_*.txt`
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
| `results/20260925/{smoke,A,B}/` | `trials.csv`, `events.csv`, `attempts.csv`, `summary.md`, per-cell logs, hold outputs |
| `c_summary.py` | GPU table (Task C) |
| `results/20260925/C/` | GPU trials (CSV + per-trial logs, `summary.md`, bundle md5) |
| `results/20260925/window.log`, `window/` | every window's log and register dumps |
