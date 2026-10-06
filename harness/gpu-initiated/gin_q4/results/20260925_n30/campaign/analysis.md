### 0. Summary: one row per cell (success criteria in the stack sections; times in ms, median [p10-p90] max)

| cell | N | success | failures | Wilson 95% CI | time | other | earlier small-N (success, time median [min-max]) | same as earlier? |
|---|--:|--:|---|---|---|---|---|---|
| GIN device-side classifier, ring CQ, F1 | 30 | 30 | 0 | 88.6-100.0% | fault->host API 15.60 [14.78-15.97] 16.05 (n=30) | class 30/30; silent success 0/30 (blocking 0/15) | 09-23 CPU doorbell, Task B, n=6: 6/6, 15.42 [14.90-15.97]; 09-24 GPU doorbell (windows + `q4` re-run), n=5: 5/5, 15.75 [14.82-16.08] | same; same |
| GIN device-side classifier, ring CQ, F2 | 30 | 30 | 0 | 88.6-100.0% | fault->host API 1.60 [1.55-2.84] 2.85 (n=30) | class 30/30; silent success 0/30 (blocking 0/15) | 09-23 CPU doorbell, Task B, n=6: 6/6, 2.79 [2.74-3.06]; 09-24 GPU doorbell (windows + `q4` re-run), n=3: 3/3, 4.33 [4.08-6.77] | diff: time (N30 median -1.19 ms vs earlier); diff: time (N30 median -2.73 ms vs earlier) |
| GIN device-side classifier, ring CQ, F3 | 30 | 30 | 0 | 88.6-100.0% | fault->host API 3678 [3537-3747] 3776 (n=30) | class 30/30; silent success 0/30 (blocking 0/15) | 09-23 CPU doorbell, Task B, n=6: 6/6, 3668 [3547-3753]; 09-24 GPU doorbell (windows + `q4` re-run), n=4: 4/4, 3632 [3513-3731] | same; same |
| GIN device-side classifier, ring CQ, F4 | 30 | 30 | 0 | 88.6-100.0% | fault->host API 3686 [3598-3799] 3816 (n=30) | class 30/30; initiator 1 op ahead of the killed target 4/30 (last op ACKed before the kill; see §1) | 09-23 CPU doorbell, Task B, n=6: 6/6, 3673 [3574-3803]; 09-24 GPU doorbell (windows + `q4` re-run), n=2: 2/2, 3651 [3589-3714] | same; same |
| GIN device-side classifier, collapsed CQ, F1 | 30 | 30 | 0 | 88.6-100.0% | fault->host API 15.24 [14.77-15.55] 16.00 (n=30) | class 30/30; silent success 0/30 (blocking 0/15) | 09-23 CPU doorbell, Task A, n=9: 9/9, 15.41 [14.86-16.15]; 09-24 GPU doorbell (windows + `q4` re-run), n=1: 1/1, 14.63 [14.63-14.63] | same; same |
| GIN device-side classifier, collapsed CQ, F2 | 30 | 30 | 0; 1 harness-invalid excluded + replaced | 88.6-100.0% | fault->host API 1.60 [1.52-2.83] 4.36 (n=30) | class 30/30; silent success 0/30 (blocking 0/15) | 09-23 CPU doorbell, Task A, n=9: 9/9, 3.24 [2.79-3.35]; 09-24 GPU doorbell (windows + `q4` re-run), n=1: 1/1, 3.84 [3.84-3.84] | diff: time (N30 median -1.65 ms vs earlier); same |
| GIN device-side classifier, collapsed CQ, F3 | 30 | 30 | 0 | 88.6-100.0% | fault->host API 3632 [3547-3753] 3808 (n=30) | class 30/30; silent success 0/30 (blocking 0/15) | 09-23 CPU doorbell, Task A, n=9: 9/9, 3646 [3525-3792]; 09-24 GPU doorbell (windows + `q4` re-run), n=1: 1/1, 3536 [3536-3536] | same; same |
| GIN device-side classifier, collapsed CQ, F4 | 30 | 30 | 0 | 88.6-100.0% | fault->host API 3698 [3598-3806] 3830 (n=30) | class 30/30; initiator 1 op ahead of the killed target 1/30 (last op ACKed before the kill; see §1) | - | - |
| GIN stock control (classifier off), ring, F1, blocking: silent success | 10 | 10 | - | 72.2-100.0% | fault->host API 9401.8 [9401.6-9402.0] 9402.2 (n=10) | success here = the failed put was reported done | 09-23 CPU doorbell, Task B, n=3: 3/3, 9401.4 [9401.1-9401.5]; 09-24 GPU doorbell window 1, n=2: 2/2, 9401.2 [9401.0-9401.4] | diff: time (N30 median +0.5 ms vs earlier); diff: time (N30 median +0.7 ms vs earlier) |
| GDAKI recovery v2 F1 | 30 | 30 | 0 | 88.6-100.0% | kernel return->recovered 8.87 [8.49-9.18] 9.39 (n=30) | rounds: 30 recovered, 0 replay failed; d=1 30, d=0 0 | 09-24 v2, GPU doorbell, n=6: 6/6, 8.71 [8.13-9.20]; 09-24 v1, CPU-doorbell fallback (before PMO), n=10: 10/10, 8.23 [8.04-8.85] | same; diff: time (N30 median +0.64 ms vs earlier) |
| GDAKI recovery v2 F3 | 30 | 30 | 0 | 88.6-100.0% | kernel return->recovered 8.35 [8.22-8.61] 8.64 (n=30) | rounds: 30 recovered, 0 replay failed; d=1 30, d=0 0 | 09-24 v2, GPU doorbell, n=6: 6/6, 8.41 [8.24-8.45]; 09-24 v1, CPU-doorbell fallback (before PMO), n=8: 8/8, 8.10 [7.96-8.22] | same; diff: time (N30 median +0.25 ms vs earlier) |
| GDAKI recovery v2 F1 x5 | 10 | 10 | 0 | 72.2-100.0% | kernel return->recovered 8.30 [8.06-8.67] 9.17 (n=40) | rounds: 40 recovered, 10 replay failed; d=1 50, d=0 0 | 09-24 v2, GPU doorbell, n=3: 3/3, 8.18 [7.87-8.44]; 09-24 v1, CPU-doorbell fallback (before PMO), n=12: 12/12, 8.05 [7.61-8.40] | same; diff: time (N30 median +0.25 ms vs earlier) |
| GDAKI recovery v2 F3 x5 | 10 | 10 | 0 | 72.2-100.0% | kernel return->recovered 8.43 [8.20-9.07] 22.03 (n=40) | rounds: 40 recovered, 10 replay failed; d=1 50, d=0 0 | 09-24 v2, GPU doorbell, n=3: 3/3, 8.30 [8.11-8.55]; 09-24 v1, CPU-doorbell fallback (before PMO), n=12: 12/12, 8.02 [7.74-8.30] | diff: time (N30 median +0.14 ms vs earlier); diff: time (N30 median +0.42 ms vs earlier) |
| GDAKI recovery v2 D0 | 30 | 30 | 0 | 88.6-100.0% | kernel return->recovered 23.18 [23.04-23.35] 23.72 (n=90) | rounds: 90 recovered, 0 replay failed; d=1 0, d=0 90 | 09-24 v2, GPU doorbell, n=2: 2/2, 23.08 [22.94-23.33]; 09-24 v1, CPU-doorbell fallback (before PMO), n=8: 8/8, 22.94 [22.79-23.15] | same; diff: time (N30 median +0.24 ms vs earlier) |
| GDAKI recovery v2 F2 | 30 | 30 | 0 | 88.6-100.0% | fault->host API 2.90 [2.88-3.05] 5.17 (n=30) | declined: class_REM_ACCESS 30 | 09-24 v2, GPU doorbell, n=4: 4/4, 4.15 [3.90-6.43]; 09-24 v1, CPU-doorbell fallback (before PMO), n=8: 8/8, 3.90 [3.88-5.68] | diff: time (N30 median -1.25 ms vs earlier); diff: time (N30 median -1.00 ms vs earlier) |
| GDAKI recovery v2 F4 | 30 | 30 | 0 | 88.6-100.0% | fault->host API 3720 [3626-3794] 3822 (n=30) | declined: retry_exc_peer_dead 30 | 09-24 v2, GPU doorbell, n=4: 4/4, 3762 [3698-3830]; 09-24 v1, CPU-doorbell fallback (before PMO), n=8: 8/8, 3668 [3578-3800] | same; same |
| GDAKI recovery v2 off F1 | 10 | 10 | 0 | 72.2-100.0% | fault->host API 1.43 [0.93-10.24] 14.79 (n=10) | classifier class LOCAL_QP_ERR 10; recovery events 0 | 09-24 v1, CPU-doorbell fallback (before PMO), n=4: 4/4, 0.83 [0.74-0.94] | diff: time (N30 median +0.60 ms vs earlier) |
| GDAKI recovery v2 off F3 | 10 | 10 | 0 | 72.2-100.0% | fault->host API 3674 [3653-3746] 3773 (n=10) | classifier class RETRY_EXC 10; recovery events 0 | 09-24 v1, CPU-doorbell fallback (before PMO), n=4: 4/4, 3600 [3521-3644] | diff: time (N30 median +74 ms vs earlier) |
| GDAKI recovery v1cpu F1 | 10 | 10 | 0 | 72.2-100.0% | kernel return->recovered 8.49 [8.30-9.09] 9.17 (n=10) | rounds: 10 recovered, 0 replay failed; d=1 10, d=0 0 | 09-24 v1, CPU-doorbell fallback (before PMO), n=10: 10/10, 8.23 [8.04-8.85] | diff: time (N30 median +0.26 ms vs earlier) |
| GDAKI recovery v1cpu F3 | 10 | 10 | 0 | 72.2-100.0% | kernel return->recovered 8.39 [8.19-9.45] 13.65 (n=10) | rounds: 10 recovered, 0 replay failed; d=1 10, d=0 0 | 09-24 v1, CPU-doorbell fallback (before PMO), n=8: 8/8, 8.10 [7.96-8.22] | diff: time (N30 median +0.29 ms vs earlier) |
| NVSHMEM FT classify F1 | 30 | 30 | 0 | 88.6-100.0% | fault->host mailbox 4.14 [3.84-8.71] 9.38 (n=30) | finalize PE0 19.7 [19.4-20.0] 20.2 (n=30) | b2, n=6: 6/6, 3.63 [3.41-4.10] | diff: time (N30 median +0.51 ms vs earlier) |
| NVSHMEM FT classify F2b | 30 | 30 | 0 | 88.6-100.0% | fault->host mailbox 1.40 [1.34-1.46] 1.76 (n=30) | finalize PE0 19.0 [18.7-19.2] 19.3 (n=30) | b2, n=6: 6/6, 1.26 [1.23-2.26] | diff: time (N30 median +0.14 ms vs earlier) |
| NVSHMEM FT classify F3 | 30 | 30 | 0 | 88.6-100.0% | fault->host mailbox 3717 [3555-3771] 3796 (n=30) | finalize PE0 18.5 [18.1-19.0] 19.1 (n=30) | b2, n=6: 6/6, 3609 [3579-3678] | diff: time (N30 median +108 ms vs earlier) |
| NVSHMEM FT classify F4 | 30 | 30 | 0 | 88.6-100.0% | fault->host mailbox 3612 [3595-3627] 3821 (n=30) | finalize PE0 18.3 [18.1-18.6] 19.0 (n=30) | b2, n=6: 6/6, 3757 [3613-3794] | diff: time (N30 median -145 ms vs earlier) |
| NVSHMEM FT recover F1 | 30 | 30 | 0 | 88.6-100.0% | kernel return->recovered 3.16 [3.04-3.45] 3.62 (n=30) | finalize PE0 20.4 [20.1-20.7] 21.2 (n=30) | b2, n=6: 6/6, 2.98 [2.92-3.00] | diff: time (N30 median +0.18 ms vs earlier) |
| NVSHMEM FT recover F3 | 30 | 30 | 0 | 88.6-100.0% | kernel return->recovered 3.25 [3.10-3.60] 3.87 (n=30) | finalize PE0 20.9 [20.6-21.3] 22.0 (n=30) | b2, n=6: 6/6, 3.33 [3.04-3.73] | same |
| NVSHMEM FT recover F1 x5 | 10 | 10 | 0 | 72.2-100.0% | kernel return->recovered 2.82 [2.72-3.48] 3.64 (n=40) | finalize PE0 21.2 [20.9-21.5] 21.6 (n=10) | b2, n=10: 10/10, 2.79 [2.69-3.12] | same |
| NVSHMEM FT recover F3 x5 | 10 | 10 | 0 | 72.2-100.0% | kernel return->recovered 4.77 [3.59-5.07] 5.42 (n=40) | finalize PE0 25.2 [25.0-25.4] 25.7 (n=10) | b2, n=10: 10/10, 4.97 [3.00-5.67] | diff: time (N30 median -0.20 ms vs earlier) |
| NVSHMEM FT decline F2b | 10 | 10 | 0 | 72.2-100.0% | fault->host mailbox 2.56 [2.52-2.74] 2.74 (n=10) | finalize PE0 19.6 [19.4-20.2] 20.2 (n=10) | b2, n=6: 6/6, 1.29 [1.26-2.52] | diff: time (N30 median +1.27 ms vs earlier) |
| NVSHMEM FT decline F4 | 10 | 10 | 0 | 72.2-100.0% | fault->host mailbox 3652 [3604-3693] 3694 (n=10) | finalize PE0 19.3 [19.1-19.5] 19.9 (n=10) | b2, n=6: 6/6, 3734 [3638-3783] | diff: time (N30 median -82 ms vs earlier) |

### 0p. Pooled claims (same per-trial verdicts, pooled over cells)

| claim | N | success | Wilson 95% CI |
|---|--:|--:|---|
| GIN classifier: classification exact (class + error code), all CQ x fault cells | 240 | 240 | 98.4-100.0% |
| GIN classifier: all criteria, all CQ x fault cells | 240 | 240 | 98.4-100.0% |
| GIN classifier: no silent success, F1-F3 | 180 | 180 | 97.9-100.0% |
| GDAKI recovery: fault runs recovered with exact data and signals (v2 F1, F3, x5; v1cpu F1, F3) | 100 | 100 | 96.3-100.0% |
| GDAKI recovery: forced d=0 runs exact | 30 | 30 | 88.6-100.0% |
| GDAKI recovery: F2/F4 declined for the right reason | 60 | 60 | 94.0-100.0% |
| NVSHMEM FT: classification exact, classify cells | 120 | 120 | 96.9-100.0% |
| NVSHMEM FT: recovery runs exact (F1, F3, x5) | 80 | 80 | 95.4-100.0% |
| NVSHMEM FT: F2b/F4 declined for the right reason | 20 | 20 | 83.9-100.0% |
| NVSHMEM FT: nvshmem_finalize returned on PE0, all cells | 220 | 220 | 98.3-100.0% |

### 1a. GIN GDAKI + device-side classifier (flag on), per CQ type x fault

| CQ | fault | wait | N | class + error code correct | device wait returned ncclRemoteError | host API returned error | silent success | fault -> host API (ms): median [p10-p90] max | fault -> device (ms): median [p10-p90] max | abort clean / leftover 0 | doorbell (indicators) | driver |
|---|---|---|--:|---|---|---|---|---|---|---|---|---|
| collapsed | F1 | both | 30 | 30/30 [88.6-100.0%] | 30/30 [88.6-100.0%] | 30/30 [88.6-100.0%] | 0/30 | 15.24 [14.77-15.55] 16.00 (n=30) | 15.05 [14.53-15.28] 15.73 (n=30) | 30/30 / 30/30 | GPU 30 | PMO=1,SMO=1 both 30 |
| collapsed | F1 | timeout | 15 | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | 0/15 | 15.25 [14.82-15.63] 16.00 (n=15) | 15.09 [14.57-15.46] 15.73 (n=15) | 15/15 / 15/15 | GPU 15 | PMO=1,SMO=1 both 15 |
| collapsed | F1 | blocking | 15 | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | 0/15 | 15.19 [14.77-15.50] 15.75 (n=15) | 15.03 [14.46-15.22] 15.45 (n=15) | 15/15 / 15/15 | GPU 15 | PMO=1,SMO=1 both 15 |
| collapsed | F2 | both | 30 | 30/30 [88.6-100.0%] | 30/30 [88.6-100.0%] | 30/30 [88.6-100.0%] | 0/30 | 1.60 [1.52-2.83] 4.36 (n=30) | 1.36 [1.31-2.55] 4.15 (n=30) | 30/30 / 30/30 | GPU 30 | PMO=1,SMO=1 both 30 |
| collapsed | F2 | timeout | 15 | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | 0/15 | 1.59 [1.53-2.91] 4.36 (n=15) | 1.36 [1.32-2.61] 4.15 (n=15) | 15/15 / 15/15 | GPU 15 | PMO=1,SMO=1 both 15 |
| collapsed | F2 | blocking | 15 | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | 0/15 | 1.61 [1.52-2.81] 2.86 (n=15) | 1.35 [1.30-2.50] 2.54 (n=15) | 15/15 / 15/15 | GPU 15 | PMO=1,SMO=1 both 15 |
| collapsed | F3 | both | 30 | 30/30 [88.6-100.0%] | 30/30 [88.6-100.0%] | 30/30 [88.6-100.0%] | 0/30 | 3632 [3547-3753] 3808 (n=30) | 3632 [3547-3753] 3808 (n=30) | 30/30 / 30/30 | GPU 30 | PMO=1,SMO=1 both 30 |
| collapsed | F3 | timeout | 15 | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | 0/15 | 3626 [3567-3741] 3788 (n=15) | 3626 [3566-3741] 3788 (n=15) | 15/15 / 15/15 | GPU 15 | PMO=1,SMO=1 both 15 |
| collapsed | F3 | blocking | 15 | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | 0/15 | 3658 [3545-3757] 3808 (n=15) | 3657 [3545-3757] 3808 (n=15) | 15/15 / 15/15 | GPU 15 | PMO=1,SMO=1 both 15 |
| collapsed | F4 | both | 30 | 30/30 [88.6-100.0%] | 30/30 [88.6-100.0%] | 30/30 [88.6-100.0%] | n/a (initiator 1 op ahead of the killed target: 1/30) | 3698 [3598-3806] 3830 (n=30) | 3697 [3597-3806] 3830 (n=30) | 30/30 / 30/30 | GPU 30 | PMO=1,SMO=1 both 30 |
| collapsed | F4 | timeout | 15 | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | n/a (initiator 1 op ahead of the killed target: 1/15) | 3708 [3592-3755] 3780 (n=15) | 3707 [3591-3755] 3775 (n=15) | 15/15 / 15/15 | GPU 15 | PMO=1,SMO=1 both 15 |
| collapsed | F4 | blocking | 15 | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | n/a (initiator 1 op ahead of the killed target: 0/15) | 3648 [3611-3810] 3830 (n=15) | 3648 [3611-3809] 3830 (n=15) | 15/15 / 15/15 | GPU 15 | PMO=1,SMO=1 both 15 |
| ring | F1 | both | 30 | 30/30 [88.6-100.0%] | 30/30 [88.6-100.0%] | 30/30 [88.6-100.0%] | 0/30 | 15.60 [14.78-15.97] 16.05 (n=30) | 15.37 [14.63-15.68] 15.86 (n=30) | 30/30 / 30/30 | GPU 30 | PMO=1,SMO=1 both 30 |
| ring | F1 | timeout | 15 | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | 0/15 | 15.65 [14.84-15.96] 16.02 (n=15) | 15.49 [14.61-15.67] 15.79 (n=15) | 15/15 / 15/15 | GPU 15 | PMO=1,SMO=1 both 15 |
| ring | F1 | blocking | 15 | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | 0/15 | 15.08 [14.79-15.93] 16.05 (n=15) | 14.78 [14.64-15.69] 15.86 (n=15) | 15/15 / 15/15 | GPU 15 | PMO=1,SMO=1 both 15 |
| ring | F2 | both | 30 | 30/30 [88.6-100.0%] | 30/30 [88.6-100.0%] | 30/30 [88.6-100.0%] | 0/30 | 1.60 [1.55-2.84] 2.85 (n=30) | 1.43 [1.37-2.56] 2.62 (n=30) | 30/30 / 30/30 | GPU 30 | PMO=1,SMO=1 both 30 |
| ring | F2 | timeout | 15 | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | 0/15 | 1.76 [1.56-2.82] 2.84 (n=15) | 1.45 [1.40-2.59] 2.62 (n=15) | 15/15 / 15/15 | GPU 15 | PMO=1,SMO=1 both 15 |
| ring | F2 | blocking | 15 | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | 0/15 | 1.59 [1.55-2.81] 2.85 (n=15) | 1.38 [1.37-2.51] 2.54 (n=15) | 15/15 / 15/15 | GPU 15 | PMO=1,SMO=1 both 15 |
| ring | F3 | both | 30 | 30/30 [88.6-100.0%] | 30/30 [88.6-100.0%] | 30/30 [88.6-100.0%] | 0/30 | 3678 [3537-3747] 3776 (n=30) | 3678 [3537-3747] 3776 (n=30) | 30/30 / 30/30 | GPU 30 | PMO=1,SMO=1 both 30 |
| ring | F3 | timeout | 15 | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | 0/15 | 3683 [3543-3762] 3776 (n=15) | 3683 [3543-3762] 3776 (n=15) | 15/15 / 15/15 | GPU 15 | PMO=1,SMO=1 both 15 |
| ring | F3 | blocking | 15 | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | 0/15 | 3675 [3550-3728] 3744 (n=15) | 3675 [3549-3728] 3744 (n=15) | 15/15 / 15/15 | GPU 15 | PMO=1,SMO=1 both 15 |
| ring | F4 | both | 30 | 30/30 [88.6-100.0%] | 30/30 [88.6-100.0%] | 30/30 [88.6-100.0%] | n/a (initiator 1 op ahead of the killed target: 4/30) | 3686 [3598-3799] 3816 (n=30) | 3686 [3597-3799] 3816 (n=30) | 30/30 / 30/30 | GPU 30 | PMO=1,SMO=1 both 30 |
| ring | F4 | timeout | 15 | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | n/a (initiator 1 op ahead of the killed target: 2/15) | 3644 [3596-3777] 3784 (n=15) | 3644 [3596-3777] 3784 (n=15) | 15/15 / 15/15 | GPU 15 | PMO=1,SMO=1 both 15 |
| ring | F4 | blocking | 15 | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | 15/15 [79.6-100.0%] | n/a (initiator 1 op ahead of the killed target: 2/15) | 3744 [3623-3812] 3816 (n=15) | 3744 [3623-3812] 3816 (n=15) | 15/15 / 15/15 | GPU 15 | PMO=1,SMO=1 both 15 |

Harness-invalid trials (excluded from N; a replacement trial was run for each): `main/collapsed_c1_F2_blocking_t9`: rank 0 did not initialise (r0 log: bind: Address already in use)

### 1b. Stock control (classifier off), ring CQ, F1, blocking wait

| N | silent success (initiator counted the failed put as done) | device rc | fault -> host API (ms) | host error | abort clean / leftover 0 | doorbell | driver |
|--:|---|---|---|---|---|---|---|
| 10 | 10/10 [72.2-100.0%] | success (no error returned) 10 | 9401.8 [9401.6-9402.0] 9402.2 (n=10) | ncclRemoteError 10 | 10/10 / 10/10 | GPU 10 | PMO=1,SMO=1 both 10 |

Positive control for the doorbell indicators (same `gin_q4` build, `NCCL_GIN_GDAKI_NIC_HANDLER=1`):
px1: proxy thread r0/r1 1/1, DOCA "Enabling CPU proxy mode" lines r0/r1 24/24 -> CPU_PROXY, class
LOCAL_QP_ERR; px2: proxy thread r0/r1 1/1, DOCA "Enabling CPU proxy mode" lines r0/r1 24/24 ->
CPU_PROXY, class LOCAL_QP_ERR

### 2. GDAKI recovery (v2 = gin_recovery_gpudb, GPU doorbells; v1cpu = gin_recovery with the CPU proxy forced)

| cell | wait | N | success (criterion below) | Wilson 95% CI | kernel return -> recovered (ms), per recovered round | fault -> recovered (ms) | fault -> host API (ms; declines: ncclGinFaultQuery returned, flag off: ncclCommGetAsyncError) | rounds: recovered / replay failed / d=1 / d=0 | doorbell | driver |
|---|---|--:|---|---|---|---|---|---|---|---|
| v2 F1 | both | 30 | 30/30 | 88.6-100.0% | 8.87 [8.49-9.18] 9.39 (n=30) | 9.71 [9.49-10.10] 19.70 (n=30) | - | 30 / 0 / 30 / 0 | GPU (logged mode=GPU) 30 | PMO=1,SMO=1 both 30 |
| v2 F1 | timeout | 15 | 15/15 | 79.6-100.0% | 8.96 [8.58-9.15] 9.18 (n=15) | 9.71 [9.48-10.02] 19.70 (n=15) | - | 15 / 0 / 15 / 0 | GPU (logged mode=GPU) 15 | PMO=1,SMO=1 both 15 |
| v2 F1 | blocking | 15 | 15/15 | 79.6-100.0% | 8.84 [8.43-9.23] 9.39 (n=15) | 9.72 [9.53-10.04] 10.11 (n=15) | - | 15 / 0 / 15 / 0 | GPU (logged mode=GPU) 15 | PMO=1,SMO=1 both 15 |
| v2 F3 | both | 30 | 30/30 | 88.6-100.0% | 8.35 [8.22-8.61] 8.64 (n=30) | 3600 [3541-3757] 3791 (n=30) | - | 30 / 0 / 30 / 0 | GPU (logged mode=GPU) 30 | PMO=1,SMO=1 both 30 |
| v2 F3 | timeout | 15 | 15/15 | 79.6-100.0% | 8.40 [8.18-8.62] 8.64 (n=15) | 3594 [3542-3749] 3791 (n=15) | - | 15 / 0 / 15 / 0 | GPU (logged mode=GPU) 15 | PMO=1,SMO=1 both 15 |
| v2 F3 | blocking | 15 | 15/15 | 79.6-100.0% | 8.35 [8.25-8.50] 8.61 (n=15) | 3622 [3548-3762] 3781 (n=15) | - | 15 / 0 / 15 / 0 | GPU (logged mode=GPU) 15 | PMO=1,SMO=1 both 15 |
| v2 F1 x5 | both | 10 | 10/10 | 72.2-100.0% | 8.30 [8.06-8.67] 9.17 (n=40) | 18.59 [9.86-21.81] 23.09 (n=40) | - | 40 / 10 / 50 / 0 | GPU (logged mode=GPU) 10 | PMO=1,SMO=1 both 10 |
| v2 F1 x5 | timeout | 5 | 5/5 | 56.6-100.0% | 8.28 [8.10-8.96] 9.17 (n=20) | 18.57 [9.86-22.21] 23.09 (n=20) | - | 20 / 5 / 25 / 0 | GPU (logged mode=GPU) 5 | PMO=1,SMO=1 both 5 |
| v2 F1 x5 | blocking | 5 | 5/5 | 56.6-100.0% | 8.30 [8.06-8.52] 8.74 (n=20) | 18.61 [9.78-21.47] 21.70 (n=20) | - | 20 / 5 / 25 / 0 | GPU (logged mode=GPU) 5 | PMO=1,SMO=1 both 5 |
| v2 F3 x5 | both | 10 | 10/10 | 72.2-100.0% | 8.43 [8.20-9.07] 22.03 (n=40) | 3730 [3550-3762] 3762 (n=40) | - | 40 / 10 / 50 / 0 | GPU (logged mode=GPU) 10 | PMO=1,SMO=1 both 10 |
| v2 F3 x5 | timeout | 5 | 5/5 | 56.6-100.0% | 8.40 [8.20-8.88] 9.04 (n=20) | 3730 [3587-3762] 3762 (n=20) | - | 20 / 5 / 25 / 0 | GPU (logged mode=GPU) 5 | PMO=1,SMO=1 both 5 |
| v2 F3 x5 | blocking | 5 | 5/5 | 56.6-100.0% | 8.44 [8.21-9.50] 22.03 (n=20) | 3730 [3546-3762] 3762 (n=20) | - | 20 / 5 / 25 / 0 | GPU (logged mode=GPU) 5 | PMO=1,SMO=1 both 5 |
| v2 D0 | both | 30 | 30/30 | 88.6-100.0% | 23.18 [23.04-23.35] 23.72 (n=90) | - | - | 90 / 0 / 0 / 90 | GPU (logged mode=GPU) 30 | PMO=1,SMO=1 both 30 |
| v2 D0 | timeout | 15 | 15/15 | 79.6-100.0% | 23.18 [23.04-23.39] 23.72 (n=45) | - | - | 45 / 0 / 0 / 45 | GPU (logged mode=GPU) 15 | PMO=1,SMO=1 both 15 |
| v2 D0 | blocking | 15 | 15/15 | 79.6-100.0% | 23.18 [23.05-23.33] 23.44 (n=45) | - | - | 45 / 0 / 0 / 45 | GPU (logged mode=GPU) 15 | PMO=1,SMO=1 both 15 |
| v2 F2 | both | 30 | 30/30 | 88.6-100.0% | - | - | 2.90 [2.88-3.05] 5.17 (n=30) | 0 / 0 / 0 / 0 | GPU (logged mode=GPU) 30 | PMO=1,SMO=1 both 30 |
| v2 F2 | timeout | 15 | 15/15 | 79.6-100.0% | - | - | 2.89 [2.88-3.11] 5.17 (n=15) | 0 / 0 / 0 / 0 | GPU (logged mode=GPU) 15 | PMO=1,SMO=1 both 15 |
| v2 F2 | blocking | 15 | 15/15 | 79.6-100.0% | - | - | 2.90 [2.88-2.94] 3.15 (n=15) | 0 / 0 / 0 / 0 | GPU (logged mode=GPU) 15 | PMO=1,SMO=1 both 15 |
| v2 F4 | both | 30 | 30/30 | 88.6-100.0% | - | - | 3720 [3626-3794] 3822 (n=30) | 0 / 0 / 0 / 0 | GPU (logged mode=GPU) 30 | PMO=1,SMO=1 both 30 |
| v2 F4 | timeout | 15 | 15/15 | 79.6-100.0% | - | - | 3709 [3598-3791] 3804 (n=15) | 0 / 0 / 0 / 0 | GPU (logged mode=GPU) 15 | PMO=1,SMO=1 both 15 |
| v2 F4 | blocking | 15 | 15/15 | 79.6-100.0% | - | - | 3724 [3697-3790] 3822 (n=15) | 0 / 0 / 0 / 0 | GPU (logged mode=GPU) 15 | PMO=1,SMO=1 both 15 |
| v2 off F1 | both | 10 | 10/10 | 72.2-100.0% | - | - | 1.43 [0.93-10.24] 14.79 (n=10) | 0 / 0 / 0 / 0 | GPU (logged mode=GPU) 10 | PMO=1,SMO=1 both 10 |
| v2 off F1 | timeout | 5 | 5/5 | 56.6-100.0% | - | - | 1.56 [0.91-6.60] 9.73 (n=5) | 0 / 0 / 0 / 0 | GPU (logged mode=GPU) 5 | PMO=1,SMO=1 both 5 |
| v2 off F1 | blocking | 5 | 5/5 | 56.6-100.0% | - | - | 1.30 [1.21-9.53] 14.79 (n=5) | 0 / 0 / 0 / 0 | GPU (logged mode=GPU) 5 | PMO=1,SMO=1 both 5 |
| v2 off F3 | both | 10 | 10/10 | 72.2-100.0% | - | - | 3674 [3653-3746] 3773 (n=10) | 0 / 0 / 0 / 0 | GPU (logged mode=GPU) 10 | PMO=1,SMO=1 both 10 |
| v2 off F3 | timeout | 5 | 5/5 | 56.6-100.0% | - | - | 3704 [3658-3761] 3773 (n=5) | 0 / 0 / 0 / 0 | GPU (logged mode=GPU) 5 | PMO=1,SMO=1 both 5 |
| v2 off F3 | blocking | 5 | 5/5 | 56.6-100.0% | - | - | 3671 [3644-3681] 3683 (n=5) | 0 / 0 / 0 / 0 | GPU (logged mode=GPU) 5 | PMO=1,SMO=1 both 5 |
| v1cpu F1 | both | 10 | 10/10 | 72.2-100.0% | 8.49 [8.30-9.09] 9.17 (n=10) | 9.61 [9.39-11.29] 19.31 (n=10) | - | 10 / 0 / 10 / 0 | CPU_PROXY (thread+DOCA) 10 | PMO=1,SMO=1 both 10 |
| v1cpu F1 | timeout | 5 | 5/5 | 56.6-100.0% | 8.50 [8.35-8.99] 9.17 (n=5) | 9.53 [9.37-10.13] 10.40 (n=5) | - | 5 / 0 / 5 / 0 | CPU_PROXY (thread+DOCA) 5 | PMO=1,SMO=1 both 5 |
| v1cpu F1 | blocking | 5 | 5/5 | 56.6-100.0% | 8.47 [8.37-8.93] 9.08 (n=5) | 9.65 [9.49-15.63] 19.31 (n=5) | - | 5 / 0 / 5 / 0 | CPU_PROXY (thread+DOCA) 5 | PMO=1,SMO=1 both 5 |
| v1cpu F3 | both | 10 | 10/10 | 72.2-100.0% | 8.39 [8.19-9.45] 13.65 (n=10) | 3638 [3575-3722] 3732 (n=10) | - | 10 / 0 / 10 / 0 | CPU_PROXY (thread+DOCA) 10 | PMO=1,SMO=1 both 10 |
| v1cpu F3 | timeout | 5 | 5/5 | 56.6-100.0% | 8.44 [8.28-11.59] 13.65 (n=5) | 3680 [3588-3711] 3721 (n=5) | - | 5 / 0 / 5 / 0 | CPU_PROXY (thread+DOCA) 5 | PMO=1,SMO=1 both 5 |
| v1cpu F3 | blocking | 5 | 5/5 | 56.6-100.0% | 8.34 [8.14-8.81] 8.98 (n=5) | 3626 [3549-3699] 3732 (n=5) | - | 5 / 0 / 5 / 0 | CPU_PROXY (thread+DOCA) 5 | PMO=1,SMO=1 both 5 |

Success criteria: **F1**: recovered once (d=1), 120/120 ops bit-exact + signal exact each op + final
signal exact, both exit 0, aborts return; **F3**: same as F1 (class RETRY_EXC, peer alive); **F1
x5**: 5 shots, 4 recovered + 1 replay failed (shot inside the commit), all d=1, 160/160 bit-exact,
signals exact; **F3 x5**: 5 shots, 4 recovered + 1 replay failed, all d=1, 200/200 bit-exact,
signals exact; **D0**: 3 forced recoveries with d=0 (nothing replayed), 120/120 bit-exact, signals
exact; **F2**: declined (class_REM_ACCESS, code 10/0x88), both ranks exit 9, both aborts return;
**F4**: declined (retry_exc_peer_dead, code 12/0x81), initiator exits 9, abort returns; **off F1**:
recovery flag off: initiator exits 8 with the classifier class LOCAL_QP_ERR, no recovery event,
abort returns; **off F3**: recovery flag off: initiator exits 8 with the classifier class RETRY_EXC,
no recovery event, abort returns.

### 3. NVSHMEM IBGDA + FT patch (GPU NIC handler)

| cell | wait | N | success | Wilson 95% CI | class + error code correct | fault -> device (ms) | fault -> host mailbox (ms) | kernel return -> recovered (ms) | fault -> recovered (ms) | finalize PE0 / PE1 (ms) | silent success | doorbell | driver |
|---|---|--:|---|---|---|---|---|---|---|---|---|---|---|
| classify F1 | both | 30 | 30/30 | 88.6-100.0% | 30/30 [88.6-100.0%] | 4.10 [3.83-8.66] 9.29 (n=30) | 4.14 [3.84-8.71] 9.38 (n=30) | - | - | 19.7 [19.4-20.0] 20.2 (n=30) / 25.4 [25.2-25.6] 25.7 (n=30) | 0/30 | GPU 30 | PMO=1,SMO=1 both 30 |
| classify F1 | timeout | 15 | 15/15 | 79.6-100.0% | 15/15 [79.6-100.0%] | 4.13 [3.82-8.57] 8.75 (n=15) | 4.15 [3.88-8.64] 8.81 (n=15) | - | - | 19.7 [19.4-20.0] 20.1 (n=15) / 25.5 [25.2-25.7] 25.7 (n=15) | 0/15 | GPU 15 | PMO=1,SMO=1 both 15 |
| classify F1 | blocking | 15 | 15/15 | 79.6-100.0% | 15/15 [79.6-100.0%] | 4.05 [3.85-8.62] 9.29 (n=15) | 4.13 [3.90-8.65] 9.38 (n=15) | - | - | 19.7 [19.4-19.9] 20.2 (n=15) / 25.4 [25.2-25.6] 25.6 (n=15) | 0/15 | GPU 15 | PMO=1,SMO=1 both 15 |
| classify F2b | both | 30 | 30/30 | 88.6-100.0% | 30/30 [88.6-100.0%] | 1.34 [1.29-1.44] 1.69 (n=30) | 1.40 [1.34-1.46] 1.76 (n=30) | - | - | 19.0 [18.7-19.2] 19.3 (n=30) / 25.3 [25.1-25.4] 25.5 (n=30) | 0/30 | GPU 30 | PMO=1,SMO=1 both 30 |
| classify F2b | timeout | 15 | 15/15 | 79.6-100.0% | 15/15 [79.6-100.0%] | 1.35 [1.30-1.42] 1.48 (n=15) | 1.41 [1.35-1.45] 1.50 (n=15) | - | - | 19.1 [18.8-19.2] 19.2 (n=15) / 25.3 [25.1-25.4] 25.5 (n=15) | 0/15 | GPU 15 | PMO=1,SMO=1 both 15 |
| classify F2b | blocking | 15 | 15/15 | 79.6-100.0% | 15/15 [79.6-100.0%] | 1.33 [1.29-1.58] 1.69 (n=15) | 1.40 [1.33-1.62] 1.76 (n=15) | - | - | 19.0 [18.7-19.2] 19.3 (n=15) / 25.3 [25.1-25.4] 25.5 (n=15) | 0/15 | GPU 15 | PMO=1,SMO=1 both 15 |
| classify F3 | both | 30 | 30/30 | 88.6-100.0% | 30/30 [88.6-100.0%] | 3717 [3555-3771] 3796 (n=30) | 3717 [3555-3771] 3796 (n=30) | - | - | 18.5 [18.1-19.0] 19.1 (n=30) / 26.1 [25.6-26.7] 26.9 (n=30) | 0/30 | GPU 30 | PMO=1,SMO=1 both 30 |
| classify F3 | timeout | 15 | 15/15 | 79.6-100.0% | 15/15 [79.6-100.0%] | 3715 [3543-3774] 3792 (n=15) | 3715 [3543-3774] 3792 (n=15) | - | - | 18.5 [18.1-18.9] 19.0 (n=15) / 26.1 [25.6-26.7] 26.7 (n=15) | 0/15 | GPU 15 | PMO=1,SMO=1 both 15 |
| classify F3 | blocking | 15 | 15/15 | 79.6-100.0% | 15/15 [79.6-100.0%] | 3719 [3672-3765] 3796 (n=15) | 3719 [3673-3765] 3796 (n=15) | - | - | 18.4 [18.1-19.0] 19.1 (n=15) / 26.0 [25.6-26.7] 26.9 (n=15) | 0/15 | GPU 15 | PMO=1,SMO=1 both 15 |
| classify F4 | both | 30 | 30/30 | 88.6-100.0% | 30/30 [88.6-100.0%] | 3612 [3595-3627] 3821 (n=30) | 3612 [3595-3627] 3821 (n=30) | - | - | 18.3 [18.1-18.6] 19.0 (n=30) / - | - | GPU 30 | PMO=1,SMO=1 both 30 |
| classify F4 | timeout | 15 | 15/15 | 79.6-100.0% | 15/15 [79.6-100.0%] | 3616 [3602-3724] 3821 (n=15) | 3616 [3602-3724] 3821 (n=15) | - | - | 18.3 [18.1-18.8] 19.0 (n=15) / - | - | GPU 15 | PMO=1,SMO=1 both 15 |
| classify F4 | blocking | 15 | 15/15 | 79.6-100.0% | 15/15 [79.6-100.0%] | 3608 [3578-3617] 3626 (n=15) | 3608 [3578-3617] 3626 (n=15) | - | - | 18.3 [18.1-18.6] 18.6 (n=15) / - | - | GPU 15 | PMO=1,SMO=1 both 15 |
| recover F1 | both | 30 | 30/30 | 88.6-100.0% | 30/30 [88.6-100.0%] | 8.27 [8.13-8.48] 8.62 (n=30) | 8.32 [8.21-8.59] 8.71 (n=30) | 3.16 [3.04-3.45] 3.62 (n=30) | 11.52 [11.30-11.77] 11.95 (n=30) | 20.4 [20.1-20.7] 21.2 (n=30) / 26.1 [26.0-26.7] 26.8 (n=30) | - | GPU 30 | PMO=1,SMO=1 both 30 |
| recover F1 | timeout | 15 | 15/15 | 79.6-100.0% | 15/15 [79.6-100.0%] | 8.29 [8.12-8.41] 8.62 (n=15) | 8.38 [8.19-8.47] 8.71 (n=15) | 3.12 [3.05-3.46] 3.62 (n=15) | 11.50 [11.25-11.83] 11.95 (n=15) | 20.3 [20.1-20.9] 21.2 (n=15) / 26.1 [25.9-26.7] 26.7 (n=15) | - | GPU 15 | PMO=1,SMO=1 both 15 |
| recover F1 | blocking | 15 | 15/15 | 79.6-100.0% | 15/15 [79.6-100.0%] | 8.27 [8.13-8.49] 8.55 (n=15) | 8.32 [8.23-8.59] 8.67 (n=15) | 3.18 [3.05-3.44] 3.60 (n=15) | 11.55 [11.35-11.75] 11.76 (n=15) | 20.4 [20.1-20.6] 20.8 (n=15) / 26.1 [26.0-26.7] 26.8 (n=15) | - | GPU 15 | PMO=1,SMO=1 both 15 |
| recover F3 | both | 30 | 30/30 | 88.6-100.0% | 30/30 [88.6-100.0%] | 3623 [3587-3652] 3669 (n=30) | 3623 [3587-3652] 3669 (n=30) | 3.25 [3.10-3.60] 3.87 (n=30) | 3626 [3590-3656] 3672 (n=30) | 20.9 [20.6-21.3] 22.0 (n=30) / 26.6 [26.2-26.9] 27.2 (n=30) | - | GPU 30 | PMO=1,SMO=1 both 30 |
| recover F3 | timeout | 15 | 15/15 | 79.6-100.0% | 15/15 [79.6-100.0%] | 3636 [3584-3655] 3669 (n=15) | 3636 [3584-3656] 3669 (n=15) | 3.19 [3.12-3.55] 3.87 (n=15) | 3640 [3588-3659] 3672 (n=15) | 20.8 [20.6-21.4] 22.0 (n=15) / 26.5 [26.2-26.9] 27.0 (n=15) | - | GPU 15 | PMO=1,SMO=1 both 15 |
| recover F3 | blocking | 15 | 15/15 | 79.6-100.0% | 15/15 [79.6-100.0%] | 3622 [3605-3646] 3652 (n=15) | 3622 [3605-3646] 3652 (n=15) | 3.26 [3.09-3.63] 3.75 (n=15) | 3626 [3609-3650] 3656 (n=15) | 20.9 [20.6-21.2] 21.3 (n=15) / 26.6 [26.2-26.9] 27.2 (n=15) | - | GPU 15 | PMO=1,SMO=1 both 15 |
| recover F1 x5 | both | 10 | 10/10 | 72.2-100.0% | 10/10 [72.2-100.0%] | 3.94 [3.75-4.01] 4.17 (n=10) | 4.00 [3.83-4.08] 4.25 (n=10) | 2.82 [2.72-3.48] 3.64 (n=40) | 7.07 [3.37-9.34] 9.49 (n=40) | 21.2 [20.9-21.5] 21.6 (n=10) / 26.6 [26.3-26.7] 26.8 (n=10) | - | GPU 10 | PMO=1,SMO=1 both 10 |
| recover F1 x5 | timeout | 5 | 5/5 | 56.6-100.0% | 5/5 [56.6-100.0%] | 3.91 [3.74-3.99] 3.99 (n=5) | 4.00 [3.80-4.04] 4.06 (n=5) | 2.82 [2.73-3.44] 3.64 (n=20) | 7.02 [3.37-9.35] 9.49 (n=20) | 21.2 [21.2-21.5] 21.6 (n=5) / 26.5 [26.3-26.7] 26.8 (n=5) | - | GPU 5 | PMO=1,SMO=1 both 5 |
| recover F1 x5 | blocking | 5 | 5/5 | 56.6-100.0% | 5/5 [56.6-100.0%] | 3.96 [3.87-4.09] 4.17 (n=5) | 4.00 [3.95-4.15] 4.25 (n=5) | 2.82 [2.72-3.48] 3.51 (n=20) | 7.11 [3.41-9.32] 9.42 (n=20) | 21.2 [20.8-21.4] 21.5 (n=5) / 26.6 [26.3-26.7] 26.7 (n=5) | - | GPU 5 | PMO=1,SMO=1 both 5 |
| recover F3 x5 | both | 10 | 10/10 | 72.2-100.0% | 10/10 [72.2-100.0%] | 3573 [3559-3591] 3627 (n=10) | 3573 [3559-3591] 3628 (n=10) | 4.77 [3.59-5.07] 5.42 (n=40) | 3740 [3574-3759] 3759 (n=40) | 25.2 [25.0-25.4] 25.7 (n=10) / 29.4 [29.2-30.1] 30.1 (n=10) | - | GPU 10 | PMO=1,SMO=1 both 10 |
| recover F3 x5 | timeout | 5 | 5/5 | 56.6-100.0% | 5/5 [56.6-100.0%] | 3581 [3547-3611] 3627 (n=5) | 3581 [3547-3611] 3628 (n=5) | 4.79 [3.66-5.04] 5.42 (n=20) | 3740 [3584-3759] 3759 (n=20) | 25.2 [25.1-25.6] 25.7 (n=5) / 29.7 [29.4-30.1] 30.1 (n=5) | - | GPU 5 | PMO=1,SMO=1 both 5 |
| recover F3 x5 | blocking | 5 | 5/5 | 56.6-100.0% | 5/5 [56.6-100.0%] | 3571 [3563-3582] 3587 (n=5) | 3571 [3563-3583] 3587 (n=5) | 4.57 [3.57-5.07] 5.18 (n=20) | 3740 [3574-3759] 3759 (n=20) | 25.2 [24.9-25.4] 25.4 (n=5) / 29.3 [29.1-29.5] 29.5 (n=5) | - | GPU 5 | PMO=1,SMO=1 both 5 |
| decline F2b | both | 10 | 10/10 | 72.2-100.0% | 10/10 [72.2-100.0%] | 2.54 [2.48-2.69] 2.71 (n=10) | 2.56 [2.52-2.74] 2.74 (n=10) | - | - | 19.6 [19.4-20.2] 20.2 (n=10) / 25.5 [25.3-25.6] 25.7 (n=10) | - | GPU 10 | PMO=1,SMO=1 both 10 |
| decline F2b | timeout | 5 | 5/5 | 56.6-100.0% | 5/5 [56.6-100.0%] | 2.65 [2.50-2.70] 2.71 (n=5) | 2.73 [2.55-2.74] 2.74 (n=5) | - | - | 19.6 [19.4-20.2] 20.2 (n=5) / 25.3 [25.3-25.7] 25.7 (n=5) | - | GPU 5 | PMO=1,SMO=1 both 5 |
| decline F2b | blocking | 5 | 5/5 | 56.6-100.0% | 5/5 [56.6-100.0%] | 2.52 [2.49-2.57] 2.58 (n=5) | 2.56 [2.51-2.59] 2.61 (n=5) | - | - | 19.7 [19.4-19.9] 19.9 (n=5) / 25.5 [25.4-25.6] 25.6 (n=5) | - | GPU 5 | PMO=1,SMO=1 both 5 |
| decline F4 | both | 10 | 10/10 | 72.2-100.0% | 10/10 [72.2-100.0%] | 3652 [3604-3693] 3694 (n=10) | 3652 [3604-3693] 3694 (n=10) | - | - | 19.3 [19.1-19.5] 19.9 (n=10) / - | - | GPU 10 | PMO=1,SMO=1 both 10 |
| decline F4 | timeout | 5 | 5/5 | 56.6-100.0% | 5/5 [56.6-100.0%] | 3649 [3620-3678] 3694 (n=5) | 3649 [3620-3678] 3694 (n=5) | - | - | 19.4 [19.0-19.5] 19.5 (n=5) / - | - | GPU 5 | PMO=1,SMO=1 both 5 |
| decline F4 | blocking | 5 | 5/5 | 56.6-100.0% | 5/5 [56.6-100.0%] | 3654 [3611-3690] 3693 (n=5) | 3654 [3611-3690] 3693 (n=5) | - | - | 19.3 [19.2-19.7] 19.9 (n=5) / - | - | GPU 5 | PMO=1,SMO=1 both 5 |

Success criteria: **classify**: first device record = true class and error code (F1 LOCAL_QP_ERR
5/0xf5, F2b REM_ACCESS 10/0x88, F3/F4 RETRY_EXC 12/0x81), no op verified wrong on the target, PE0
declines (classification run) and nvshmem_finalize returns (PE1 too unless killed), no leftovers;
**recover**: 1 fault round recovered (d=1, class right), 200/200 ops bit-exact with exact per-op
signal, final signal 200, both exit 0, both finalize return; **recover x5**: 5 shots, 5 rounds, 4
recovered ops + 1 replay hit by the in-commit shot, all d=1, 200/200 bit-exact, final signal 200;
**decline**: declined for the right reason (F2b "class not recoverable", F4 "RETRY_EXC with the peer
dead"), PE0 exits 9, finalize returns.

### 4a. GIN GDAKI + classifier: earlier small-N vs N30 (success = class + error code right, device and host API return the error, no silent success except F4, abort clean; time = fault -> host API, ms)

| cell | earlier source (doorbell) | earlier success | N30 success | earlier time median [min-max] | N30 time median [min-max] | Fisher p | Mann-Whitney p | verdict |
|---|---|---|---|---|---|---|---|---|
| ring F1 | 09-23 CPU doorbell, Task B, n=6 | 6/6 | 30/30 | 15.42 [14.90-15.97] | 15.60 [14.68-16.05] | 1 | 0.978 | same (no detectable difference) |
| ring F1 | 09-24 GPU doorbell (windows + `q4` re-run), n=5 | 5/5 | 30/30 | 15.75 [14.82-16.08] | 15.60 [14.68-16.05] | 1 | 0.569 | same (no detectable difference) |
| ring F2 | 09-23 CPU doorbell, Task B, n=6 | 6/6 | 30/30 | 2.79 [2.74-3.06] | 1.60 [1.53-2.85] | 1 | 0.0063 | different: time (N30 median -1.19 ms vs earlier) |
| ring F2 | 09-24 GPU doorbell (windows + `q4` re-run), n=3 | 3/3 | 30/30 | 4.33 [4.08-6.77] | 1.60 [1.53-2.85] | 1 | 0.000367 | different: time (N30 median -2.73 ms vs earlier) |
| ring F3 | 09-23 CPU doorbell, Task B, n=6 | 6/6 | 30/30 | 3668 [3547-3753] | 3678 [3525-3776] | 1 | 0.919 | same (no detectable difference) |
| ring F3 | 09-24 GPU doorbell (windows + `q4` re-run), n=4 | 4/4 | 30/30 | 3632 [3513-3731] | 3678 [3525-3776] | 1 | 0.519 | same (no detectable difference) |
| ring F4 | 09-23 CPU doorbell, Task B, n=6 | 6/6 | 30/30 | 3673 [3574-3803] | 3686 [3557-3816] | 1 | 0.788 | same (no detectable difference) |
| ring F4 | 09-24 GPU doorbell (windows + `q4` re-run), n=2 | 2/2 | 30/30 | 3651 [3589-3714] | 3686 [3557-3816] | 1 | 0.488 | same (no detectable difference) |
| collapsed F1 | 09-23 CPU doorbell, Task A, n=9 | 9/9 | 30/30 | 15.41 [14.86-16.15] | 15.24 [14.40-16.00] | 1 | 0.126 | same (no detectable difference) |
| collapsed F1 | 09-24 GPU doorbell (windows + `q4` re-run), n=1 | 1/1 | 30/30 | 14.63 [14.63-14.63] | 15.24 [14.40-16.00] | 1 | - | same (no detectable difference) |
| collapsed F2 | 09-23 CPU doorbell, Task A, n=9 | 9/9 | 30/30 | 3.24 [2.79-3.35] | 1.60 [1.47-4.36] | 1 | 5e-05 | different: time (N30 median -1.65 ms vs earlier) |
| collapsed F2 | 09-24 GPU doorbell (windows + `q4` re-run), n=1 | 1/1 | 30/30 | 3.84 [3.84-3.84] | 1.60 [1.47-4.36] | 1 | - | same (no detectable difference) |
| collapsed F3 | 09-23 CPU doorbell, Task A, n=9 | 9/9 | 30/30 | 3646 [3525-3792] | 3632 [3520-3808] | 1 | 0.731 | same (no detectable difference) |
| collapsed F3 | 09-24 GPU doorbell (windows + `q4` re-run), n=1 | 1/1 | 30/30 | 3536 [3536-3536] | 3632 [3520-3808] | 1 | - | same (no detectable difference) |
| stock F1 blocking: silent success | 09-23 CPU doorbell, Task B, n=3 | 3/3 | 10/10 | 9401.4 [9401.1-9401.5] | 9401.8 [9401.5-9402.2] | 1 | 0.00699 | different: time (N30 median +0.5 ms vs earlier) |
| stock F1 blocking: silent success | 09-24 GPU doorbell window 1, n=2 | 2/2 | 10/10 | 9401.2 [9401.0-9401.4] | 9401.8 [9401.5-9402.2] | 1 | 0.0303 | different: time (N30 median +0.7 ms vs earlier) |

### 4b. GDAKI recovery: earlier small-N vs N30 (success = same criterion as table 2; time = kernel return -> recovered per recovered round; declines: fault -> ncclGinFaultQuery returned; flag off: fault -> ncclCommGetAsyncError; ms)

| cell | earlier source | earlier success | N30 success | earlier time median [min-max] | N30 time median [min-max] | Fisher p | Mann-Whitney p | verdict |
|---|---|---|---|---|---|---|---|---|
| v2 F1 | 09-24 v2, GPU doorbell, n=6 | 6/6 | 30/30 | 8.71 [8.13-9.20] | 8.87 [8.38-9.39] | 1 | 0.251 | same (no detectable difference) |
| v2 F1 | 09-24 v1, CPU-doorbell fallback (before PMO), n=10 | 10/10 | 30/30 | 8.23 [8.04-8.85] | 8.87 [8.38-9.39] | 1 | 5e-05 | different: time (N30 median +0.64 ms vs earlier) |
| v2 F3 | 09-24 v2, GPU doorbell, n=6 | 6/6 | 30/30 | 8.41 [8.24-8.45] | 8.35 [7.95-8.64] | 1 | 0.783 | same (no detectable difference) |
| v2 F3 | 09-24 v1, CPU-doorbell fallback (before PMO), n=8 | 8/8 | 30/30 | 8.10 [7.96-8.22] | 8.35 [7.95-8.64] | 1 | 5e-05 | different: time (N30 median +0.25 ms vs earlier) |
| v2 F1 x5 | 09-24 v2, GPU doorbell, n=3 | 3/3 | 10/10 | 8.18 [7.87-8.44] | 8.30 [7.89-9.17] | 1 | 0.0656 | same (no detectable difference) |
| v2 F1 x5 | 09-24 v1, CPU-doorbell fallback (before PMO), n=12 | 12/12 | 10/10 | 8.05 [7.61-8.40] | 8.30 [7.89-9.17] | 1 | 5e-05 | different: time (N30 median +0.25 ms vs earlier) |
| v2 F3 x5 | 09-24 v2, GPU doorbell, n=3 | 3/3 | 10/10 | 8.30 [8.11-8.55] | 8.43 [7.98-22.03] | 1 | 0.0426 | different: time (N30 median +0.14 ms vs earlier) |
| v2 F3 x5 | 09-24 v1, CPU-doorbell fallback (before PMO), n=12 | 12/12 | 10/10 | 8.02 [7.74-8.30] | 8.43 [7.98-22.03] | 1 | 5e-05 | different: time (N30 median +0.42 ms vs earlier) |
| v2 D0 | 09-24 v2, GPU doorbell, n=2 | 2/2 | 30/30 | 23.08 [22.94-23.33] | 23.18 [22.90-23.72] | 1 | 0.0583 | same (no detectable difference) |
| v2 D0 | 09-24 v1, CPU-doorbell fallback (before PMO), n=8 | 8/8 | 30/30 | 22.94 [22.79-23.15] | 23.18 [22.90-23.72] | 1 | 5e-05 | different: time (N30 median +0.24 ms vs earlier) |
| v2 F2 | 09-24 v2, GPU doorbell, n=4 | 4/4 | 30/30 | 4.15 [3.90-6.43] | 2.90 [2.63-5.17] | 1 | 0.00028 | different: time (N30 median -1.25 ms vs earlier) |
| v2 F2 | 09-24 v1, CPU-doorbell fallback (before PMO), n=8 | 8/8 | 30/30 | 3.90 [3.88-5.68] | 2.90 [2.63-5.17] | 1 | 5e-05 | different: time (N30 median -1.00 ms vs earlier) |
| v2 F4 | 09-24 v2, GPU doorbell, n=4 | 4/4 | 30/30 | 3762 [3698-3830] | 3720 [3593-3822] | 1 | 0.453 | same (no detectable difference) |
| v2 F4 | 09-24 v1, CPU-doorbell fallback (before PMO), n=8 | 8/8 | 30/30 | 3668 [3578-3800] | 3720 [3593-3822] | 1 | 0.316 | same (no detectable difference) |
| v2 off F1 | 09-24 v1, CPU-doorbell fallback (before PMO), n=4 | 4/4 | 10/10 | 0.83 [0.74-0.94] | 1.43 [0.90-14.79] | 1 | 0.00799 | different: time (N30 median +0.60 ms vs earlier) |
| v2 off F3 | 09-24 v1, CPU-doorbell fallback (before PMO), n=4 | 4/4 | 10/10 | 3600 [3521-3644] | 3674 [3630-3773] | 1 | 0.00799 | different: time (N30 median +74 ms vs earlier) |
| v1cpu F1 | 09-24 v1, CPU-doorbell fallback (before PMO), n=10 | 10/10 | 10/10 | 8.23 [8.04-8.85] | 8.49 [8.27-9.17] | 1 | 0.0185 | different: time (N30 median +0.26 ms vs earlier) |
| v1cpu F3 | 09-24 v1, CPU-doorbell fallback (before PMO), n=8 | 8/8 | 10/10 | 8.10 [7.96-8.22] | 8.39 [8.10-13.65] | 1 | 0.00137 | different: time (N30 median +0.29 ms vs earlier) |

### 4c. NVSHMEM FT: earlier small-N (results/b2, 2026-09-24, GPU handler) vs N30 (success = same criterion as table 3; time = fault -> host mailbox for classify/decline, kernel return -> recovered per recovered round for recover, ms)

| cell | earlier source | earlier success | N30 success | earlier time median [min-max] | N30 time median [min-max] | Fisher p | Mann-Whitney p | verdict |
|---|---|---|---|---|---|---|---|---|
| classify F1 | b2, n=6 | 6/6 | 30/30 | 3.63 [3.41-4.10] | 4.14 [3.81-9.38] | 1 | 0.0004 | different: time (N30 median +0.51 ms vs earlier) |
| classify F2b | b2, n=6 | 6/6 | 30/30 | 1.26 [1.23-2.26] | 1.40 [1.32-1.76] | 1 | 0.009 | different: time (N30 median +0.14 ms vs earlier) |
| classify F3 | b2, n=6 | 6/6 | 30/30 | 3609 [3579-3678] | 3717 [3506-3796] | 1 | 0.0059 | different: time (N30 median +108 ms vs earlier) |
| classify F4 | b2, n=6 | 6/6 | 30/30 | 3757 [3613-3794] | 3612 [3564-3821] | 1 | 0.0036 | different: time (N30 median -145 ms vs earlier) |
| recover F1 | b2, n=6 | 6/6 | 30/30 | 2.98 [2.92-3.00] | 3.16 [3.00-3.62] | 1 | 5e-05 | different: time (N30 median +0.18 ms vs earlier) |
| recover F3 | b2, n=6 | 6/6 | 30/30 | 3.33 [3.04-3.73] | 3.25 [3.07-3.87] | 1 | 0.659 | same (no detectable difference) |
| recover F1 x5 | b2, n=10 | 10/10 | 10/10 | 2.79 [2.69-3.12] | 2.82 [2.66-3.64] | 1 | 0.0986 | same (no detectable difference) |
| recover F3 x5 | b2, n=10 | 10/10 | 10/10 | 4.97 [3.00-5.67] | 4.77 [3.39-5.42] | 1 | 0.00045 | different: time (N30 median -0.20 ms vs earlier) |
| decline F2b | b2, n=6 | 6/6 | 10/10 | 1.29 [1.26-2.52] | 2.56 [2.50-2.74] | 1 | 0.0005 | different: time (N30 median +1.27 ms vs earlier) |
| decline F4 | b2, n=6 | 6/6 | 10/10 | 3734 [3638-3783] | 3652 [3603-3694] | 1 | 0.011 | different: time (N30 median -82 ms vs earlier) |
| nvshmem_finalize PE0, all cells | b2, n=68 | 68/68 | 220/220 | 19.1 [17.6-25.9] | 19.6 [17.9-25.7] | 1 | 0.142 | same (no detectable difference) |

