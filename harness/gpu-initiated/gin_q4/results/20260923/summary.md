# GIN GDAKI device-side classifier: summary

source: `results/20260923`

## Task A: collapsed vs ring CQ inside GIN GDAKI

`-EIO seen` = the device poll returned -EIO (error CQE, opcode 0xd) in n trials. `root` = the
status/vendor_err pair the device classified (ring: first error CQE in [cqe_ci, ticket]; collapsed:
slot 0). `polled/slot` = CQE at the polled index (ring) or slot 0 (collapsed) when the poll
returned. `late` = collapsed slot 0 re-read ~500 us later. `QP ERR` = first host QUERY_QP showing
ERR (100 ms watch). Times in ms after the fault.

| cq | classify | fault | wait | n | -EIO seen | root (status/vendor) | class | polled/slot CQE | window err/ok | late re-read | CQ buffer err | t_dev | t_api | QP ERR (watch) | init / target | init_silent_iters | teardown |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| collapsed | 0 | F1 | blocking | 2 | 0/2 | - x2 | - x2 | - | - x2 | - | - x2 | - | 9401.6 [9401.4-9401.8] | - | ok x2 / hang_killed x2 | 1/1 | clean x2 |
| collapsed | 0 | F1 | timeout | 2 | 0/2 | - x2 | - x2 | - | - x2 | - | - x2 | - | 9401.7 [9401.3-9402.0] | - | timeout x2 / timeout x2 | 0/0 | clean x2 |
| collapsed | 0 | F2 | blocking | 2 | 0/2 | - x2 | - x2 | - | - x2 | - | - x2 | - | 9999.8 [9999.8-9999.8] | - | ok x2 / hang_killed x2 | 1/1 | clean x2 |
| collapsed | 0 | F2 | timeout | 2 | 0/2 | - x2 | - x2 | - | - x2 | - | - x2 | - | 9999.7 [9999.7-9999.8] | - | timeout x2 / timeout x2 | 0/0 | clean x2 |
| collapsed | 0 | F3 | blocking | 2 | 0/2 | - x2 | - x2 | - | - x2 | - | - x2 | - | 9401.7 [9401.6-9401.8] | - | ok x2 / hang_killed x2 | 1/1 | clean x2 |
| collapsed | 0 | F3 | timeout | 2 | 0/2 | - x2 | - x2 | - | - x2 | - | - x2 | - | 9401.6 [9401.6-9401.6] | - | timeout x2 / timeout x2 | 0/0 | clean x2 |
| collapsed | 1 | none | timeout | 3 | 0/3 | - x3 | - x3 | - | - x3 | - | - x3 | - | - | - | ok x3 / ok x3 | 0/0/0 | clean x3 |
| collapsed | 1 | F1 | blocking | 3 | 3/3 | 5/0xf5 x3 | LOCAL_QP_ERR x3 | 0xd 0x5/0xf5 @76 x3 | 1/0 x3 | 0xd 0x5/0xf9 @77 x3 | 1/128 x3 | 15.24 [14.72-15.27] | 15.8 [15.4-15.9] | 100 [100-100] | error x3 / hang_killed x3 | 0/0/0 | clean x3 |
| collapsed | 1 | F1 | timeout | 6 | 6/6 | 5/0xf5 x6 | LOCAL_QP_ERR x6 | 0xd 0x5/0xf5 @76 x6 | 1/0 x6 | - x3, 0xd 0x5/0xf9 @77 x3 | 1/128 x6 | 14.96 [14.35-15.42] | 15.2 [14.9-16.2] | 100 [100-100] | error x6 / timeout x6 | 0/0/0/0/0/0 | clean x6 |
| collapsed | 1 | F2 | blocking | 3 | 3/3 | 10/0x88 x3 | REM_ACCESS x3 | 0xd 0x13/0x88 @0 x3 | 1/0 x3 | 0xd 0x5/0xf9 @1 x3 | 1/128 x3 | 2.50 [2.49-2.66] | 3.3 [3.2-3.4] | 98 [98-98] | error x3 / hang_killed x3 | 0/0/0 | clean x3 |
| collapsed | 1 | F2 | timeout | 6 | 6/6 | 10/0x88 x6 | REM_ACCESS x6 | 0xd 0x13/0x88 @0 x6 | 1/0 x6 | - x3, 0xd 0x5/0xf9 @1 x3 | 1/128 x6 | 2.52 [2.50-2.62] | 3.0 [2.8-3.3] | 98 [98-99] | error x6 / timeout x6 | 0/0/0/0/0/0 | clean x6 |
| collapsed | 1 | F3 | blocking | 3 | 3/3 | 12/0x81 x3 | RETRY_EXC x3 | 0xd 0x15/0x81 @76 x3 | 1/0 x3 | 0xd 0x5/0xf9 @77 x3 | 1/128 x3 | 3743.43 [3662.45-3791.80] | 3744.1 [3663.1-3792.5] | 3800 [3700-3800] | error x3 / hang_killed x3 | 0/0/0 | clean x3 |
| collapsed | 1 | F3 | timeout | 6 | 6/6 | 12/0x81 x6 | RETRY_EXC x6 | 0xd 0x15/0x81 @74 x2, 0xd 0x15/0x81 @76 x4 | 1/0 x6 | - x3, 0xd 0x5/0xf9 @75 x1, 0xd 0x5/0xf9 @77 x2 | 1/128 x6 | 3623.76 [3524.85-3751.96] | 3624.2 [3524.9-3752.1] | 3707 [3600-3800] | error x6 / timeout x6 | 0/0/0/0/0/0 | clean x6 |
| collapsed_host | 1 | none | timeout | 1 | 0/1 | - | - | - | - | - | - | - | - | - | unknown / unknown | 0 | clean |
| collapsed_host_force | 1 | none | timeout | 1 | 0/1 | - | - | - | - | - | - | - | - | - | unknown / unknown | 0 | n/a |
| ring | 1 | none | timeout | 3 | 0/3 | - x3 | - x3 | - | - x3 | - | - x3 | - | - | - | ok x3 / ok x3 | 0/0/0 | clean x3 |
| ring | 1 | F1 | timeout | 3 | 3/3 | 5/0xf5 x3 | LOCAL_QP_ERR x3 | 0xd 0x5/0xf9 @77 x3 | 2/0 x3 | - | 2/128 x3 | 14.61 [14.54-15.56] | 14.9 [14.8-15.9] | 100 [100-100] | error x3 / timeout x3 | 0/0/0 | clean x3 |
| ring | 1 | F2 | timeout | 3 | 3/3 | 10/0x88 x3 | REM_ACCESS x3 | 0xd 0x5/0xf9 @1 x3 | 2/0 x3 | - | 2/128 x3 | 2.61 [2.59-3.23] | 2.8 [2.8-3.5] | 98 [98-99] | error x3 / timeout x3 | 0/0/0 | clean x3 |
| ring | 1 | F3 | timeout | 3 | 3/3 | 12/0x81 x3 | RETRY_EXC x3 | 0xd 0x5/0xf9 @77 x3 | 2/0 x3 | - | 2/128 x3 | 3591.81 [3547.00-3656.04] | 3592.1 [3547.2-3656.4] | 3600 [3600-3700] | error x3 / timeout x3 | 0/0/0 | clean x3 |

## Task B (device-side classifier): device classification + host mailbox, ring CQ

classify 1 = NCCL_GIN_FAULT_CLASSIFY=1, 0 = same build with the flag off (stock paths). t_dev = device detection (%globaltimer of the record), t_mbx = host watcher read the record, t_rc = host saw the kernel return, t_api = first non-success ncclCommGetAsyncError (driver polls every 200 us); all ms after the fault, median [min-max].

| classify | fault | wait | n | init / target | device rc | class (true: fault) | root code | t_dev | t_mbx | t_rc | t_api | init_silent_iters | host_error | teardown |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | F1 | blocking | 3 | ok x3 / hang_killed x3 | - x3 | - x3 (LOCAL_QP_ERR (5/0xf5)) | - x3 | - | - | - | 9401.38 [9401.13-9401.45] | 1/1/1 | remote x3 | clean x3 |
| 0 | F1 | timeout | 3 | timeout x3 / timeout x3 | ncclTimeout x3 | - x3 (LOCAL_QP_ERR (5/0xf5)) | - x3 | - | - | - | 9401.23 [9401.10-9401.91] | 0/0/0 | remote x3 | clean x3 |
| 0 | F2 | blocking | 3 | ok x3 / hang_killed x3 | - x3 | - x3 (REM_ACCESS (10/0x88)) | - x3 | - | - | - | 9999.83 [9999.68-9999.90] | 1/1/1 | remote x3 | clean x3 |
| 0 | F2 | timeout | 3 | timeout x3 / timeout x3 | ncclTimeout x3 | - x3 (REM_ACCESS (10/0x88)) | - x3 | - | - | - | 9999.84 [9999.66-9999.84] | 0/0/0 | remote x3 | clean x3 |
| 0 | F3 | blocking | 3 | ok x3 / hang_killed x3 | - x3 | - x3 (RETRY_EXC (12/0x81)) | - x3 | - | - | - | 9401.50 [9401.43-9401.58] | 1/1/1 | remote x3 | clean x3 |
| 0 | F3 | timeout | 3 | timeout x3 / timeout x3 | ncclTimeout x3 | - x3 (RETRY_EXC (12/0x81)) | - x3 | - | - | - | 9401.52 [9401.05-9402.06] | 0/0/0 | remote x3 | clean x3 |
| 0 | F4 | blocking | 3 | timeout x3 / killed x3 | - x3 | - x3 (RETRY_EXC or REM_ACCESS) | - x3 | - | - | - | 8039.33 [8018.12-8042.49] | 0/0/0 | remote x3 | clean x3 |
| 0 | F4 | timeout | 3 | timeout x3 / killed x3 | - x3 | - x3 (RETRY_EXC or REM_ACCESS) | - x3 | - | - | - | 8037.98 [8015.63-8043.82] | 0/0/0 | remote x3 | clean x3 |
| 1 | none | blocking | 3 | ok x3 / ok x3 | - x3 | - x3 (-) | - x3 | - | - | - | - | 0/0/0 | none x3 | clean x3 |
| 1 | none | timeout | 3 | ok x3 / ok x3 | - x3 | - x3 (-) | - x3 | - | - | - | - | 0/0/0 | none x3 | clean x3 |
| 1 | F1 | blocking | 3 | error x3 / hang_killed x3 | remote x3 | LOCAL_QP_ERR x3 (LOCAL_QP_ERR (5/0xf5)) | 5/0xf5 x3 | 15.56 [14.92-15.67] | 15.62 [15.04-15.78] | 15.91 [15.15-16.04] | 15.66 [15.03-15.97] | 0/0/0 | remote x3 | clean x3 |
| 1 | F1 | timeout | 3 | error x3 / timeout x3 | remote x3 | LOCAL_QP_ERR x3 (LOCAL_QP_ERR (5/0xf5)) | 5/0xf5 x3 | 14.94 [14.76-15.46] | 15.02 [14.82-15.52] | 15.19 [15.07-15.81] | 15.18 [14.90-15.74] | 0/0/0 | remote x3 | clean x3 |
| 1 | F2 | blocking | 3 | error x3 / hang_killed x3 | remote x3 | REM_ACCESS x3 (REM_ACCESS (10/0x88)) | 10/0x88 x3 | 2.58 [2.55-2.69] | 2.64 [2.64-2.79] | 3.07 [3.07-3.07] | 2.79 [2.77-3.06] | 0/0/0 | remote x3 | clean x3 |
| 1 | F2 | timeout | 3 | error x3 / timeout x3 | remote x3 | REM_ACCESS x3 (REM_ACCESS (10/0x88)) | 10/0x88 x3 | 2.62 [2.60-2.66] | 2.69 [2.67-2.75] | 3.07 [3.06-3.07] | 2.79 [2.74-2.82] | 0/0/0 | remote x3 | clean x3 |
| 1 | F3 | blocking | 3 | error x3 / hang_killed x3 | remote x3 | RETRY_EXC x3 (RETRY_EXC (12/0x81)) | 12/0x81 x3 | 3698.11 [3574.52-3752.68] | 3698.23 [3574.64-3752.78] | 3698.29 [3575.01-3753.06] | 3698.32 [3574.71-3752.82] | 0/0/0 | remote x3 | clean x3 |
| 1 | F3 | timeout | 3 | error x3 / timeout x3 | remote x3 | RETRY_EXC x3 (RETRY_EXC (12/0x81)) | 12/0x81 x3 | 3637.68 [3547.18-3703.28] | 3637.78 [3547.28-3703.39] | 3638.00 [3547.62-3703.87] | 3637.86 [3547.36-3703.59] | 0/0/0 | remote x3 | clean x3 |
| 1 | F4 | blocking | 3 | error x3 / killed x3 | remote x3 | RETRY_EXC x3 (RETRY_EXC or REM_ACCESS) | 12/0x81 x3 | 3643.10 [3573.52-3740.89] | 3643.23 [3573.63-3741.00] | 3643.70 [3573.59-3741.20] | 3643.22 [3573.84-3740.96] | 0/1/0 | remote x3 | clean x3 |
| 1 | F4 | timeout | 3 | error x3 / killed x3 | remote x3 | RETRY_EXC x3 (RETRY_EXC or REM_ACCESS) | 12/0x81 x3 | 3701.74 [3636.46-3802.89] | 3701.85 [3636.55-3803.00] | 3701.97 [3637.05-3803.34] | 3701.89 [3636.69-3802.96] | 0/0/0 | remote x3 | clean x3 |

## Overhead: put + signal + flush latency, no fault (ring CQ, same build)

Each run: 5 x 2000 back-to-back iterations in one kernel, each timed on the GPU (%globaltimer). Pooled = all iterations of all runs of the cell; per-run = median [min-max] over runs of the per-run p50 / p99. cpu/wall = process CPU time over wall time of the timed phase (all threads: GIN CPU-proxy doorbell thread, mailbox watcher when on, main). Latencies in us.

| bytes | wait | classify | watcher poll | runs | samples | pooled p50 | pooled p90 | pooled p99 | pooled p99.9 | pooled mean | per-run p50 | per-run p99 | cpu/wall |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 4096 | blocking | 0 | - | 4 | 40000 | 10.21 | 10.27 | 11.36 | 11.94 | 10.15 | 10.21 [10.21-10.21] | 11.33 [11.33-11.36] | 2.02 [2.02-2.02] |
| 4096 | blocking | 1 | 20 us | 4 | 40000 | 10.27 | 10.43 | 11.46 | 14.37 | 10.35 | 10.27 [10.27-10.27] | 11.46 [11.42-11.49] | 2.07 [2.07-2.07] |
| 4096 | blocking | 1 | 1000 us | 2 | 20000 | 10.27 | 10.43 | 11.46 | 14.30 | 10.35 | 10.27 [10.27-10.27] | 11.46 [11.42-11.49] | 2.03 [2.03-2.03] |
| 4096 | timeout | 0 | - | 4 | 40000 | 10.11 | 10.27 | 10.78 | 12.16 | 9.92 | 10.11 [9.98-10.21] | 10.71 [10.37-11.30] | 2.02 [2.02-2.02] |
| 4096 | timeout | 1 | 20 us | 4 | 40000 | 10.21 | 10.30 | 11.39 | 12.19 | 10.00 | 10.21 [10.18-10.24] | 11.41 [11.26-11.62] | 2.08 [2.07-2.08] |
| 4096 | timeout | 1 | 1000 us | 2 | 20000 | 10.21 | 10.27 | 11.26 | 11.78 | 9.96 | 10.21 [10.21-10.21] | 11.00 [10.69-11.30] | 2.03 [2.03-2.03] |
| 262144 | blocking | 0 | - | 4 | 40000 | 37.38 | 38.85 | 38.94 | 40.99 | 37.54 | 37.39 [36.86-37.82] | 38.94 [38.94-38.94] | 2.02 [2.02-2.02] |
| 262144 | blocking | 1 | 20 us | 4 | 40000 | 37.57 | 38.88 | 39.01 | 40.03 | 37.71 | 37.57 [36.93-38.34] | 38.98 [38.98-39.01] | 2.07 [2.07-2.07] |
| 262144 | blocking | 1 | 1000 us | 2 | 20000 | 38.02 | 38.91 | 38.94 | 39.97 | 37.90 | 38.02 [37.79-38.24] | 38.94 [38.94-38.94] | 2.02 [2.02-2.02] |
| 262144 | timeout | 0 | - | 4 | 40000 | 37.31 | 38.69 | 38.94 | 40.19 | 37.44 | 37.39 [36.86-37.63] | 38.94 [38.94-38.94] | 2.02 [2.02-2.02] |
| 262144 | timeout | 1 | 20 us | 4 | 40000 | 37.34 | 38.72 | 38.94 | 40.74 | 37.46 | 37.38 [36.90-37.63] | 38.94 [38.94-38.94] | 2.07 [2.07-2.07] |
| 262144 | timeout | 1 | 1000 us | 2 | 20000 | 37.47 | 38.72 | 38.94 | 38.98 | 37.53 | 37.48 [37.47-37.50] | 38.94 [38.94-38.94] | 2.02 [2.02-2.02] |

