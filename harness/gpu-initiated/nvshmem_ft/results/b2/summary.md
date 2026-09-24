
### classify (30 trials)

| fault | mode | variant | n | recorded class (first record) | fp | path | fault -> device (ms) | device -> mailbox (us) | fault -> host API (ms) | target | teardown r0/r1 (finalize ms) | exit r0/r1 |
|---|---|---|--:|---|---|---|---|---|---|---|---|---|
| F1 | blocking | - | 3 | LOCAL_QP_ERR 3 | 5/0xf5 | poll 3 | 3.603 [3.331-4.080] | 60 [21-76] | 3.663 [3.407-4.101] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-25]) | 3 / 9 |
| F1 | timeout | - | 3 | LOCAL_QP_ERR 3 | 5/0xf5 | bounded 3 | 3.499 [3.462-3.599] | 65 [59-99] | 3.598 [3.521-3.664] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-25]) | 3 / 9 |
| F2b | blocking | - | 3 | REM_ACCESS 3 | 10/0x88 | poll 3 | 1.222 [1.210-1.234] | 33 [24-48] | 1.246 [1.243-1.282] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-28]) | 3 / 9 |
| F2b | timeout | - | 3 | REM_ACCESS 3 | 10/0x88 | bounded 3 | 1.267 [1.217-2.238] | 14 [11-20] | 1.278 [1.231-2.258] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-25]) | 3 / 9 |
| F3 | blocking | - | 3 | RETRY_EXC 3 | 12/0x81 | poll 3 | 3603.393 [3601.952-3623.054] | 81 [67-105] | 3603.460 [3602.033-3623.159] | rc9 3 | 3/3 returned (18 [18-18] / 26 [26-26]) | 3 / 9 |
| F3 | timeout | - | 3 | RETRY_EXC 3 | 12/0x81 | bounded 3 | 3614.824 [3579.468-3677.944] | 74 [27-116] | 3614.940 [3579.495-3678.018] | rc9 3 | 3/3 returned (18 [18-18] / 26 [25-26]) | 3 / 9 |
| F4 | blocking | - | 3 | RETRY_EXC 3 | 12/0x81 | poll 3 | 3782.814 [3731.075-3792.024] | 116 [106-123] | 3782.937 [3731.181-3792.140] | rc255 3 | 3/0 returned (18 [18-18] / -) | 3 / 255 |
| F4 | timeout | - | 3 | RETRY_EXC 3 | 12/0x81 | bounded 3 | 3729.194 [3612.698-3794.177] | 91 [28-102] | 3729.296 [3612.789-3794.205] | rc255 3 | 3/0 returned (18 [18-18] / -) | 3 / 255 |
| none | blocking | - | 3 | - 3 | - | - 3 | - | - | - | rc0 3 | 3/3 returned (20 [20-20] / 26 [26-26]) | 0 / 0 |
| none | timeout | - | 3 | - 3 | - | - 3 | - | - | - | rc0 3 | 3/3 returned (20 [20-20] / 26 [26-26]) | 0 / 0 |

### recover (30 trials)

| fault | mode | variant | n | faults fired | fault rounds | recovered ops | r0 ops ok | r1 data ok | r1 signal exact / final | declined | teardown r0/r1 | exit r0/r1 |
|---|---|---|--:|---|---|---|---|---|---|---|---|---|
| F1 | blocking | - | 3 | 1/1/1 | 1/1/1 | 1/1/1 | 200/200/200 | 200/200/200 | 200/200/200 ; final 3/3 | - | 3/3 | 0 / 0 |
| F1 | timeout | - | 3 | 1/1/1 | 1/1/1 | 1/1/1 | 200/200/200 | 200/200/200 | 200/200/200 ; final 3/3 | - | 3/3 | 0 / 0 |
| F2b | blocking | - | 3 | 1/1/1 | 1/1/1 | 0/0/0 | 4/4/4 | 4/4/4 | 4/4/4 ; final 0/3 | class not recoverable | 3/3 | 9 / 9 |
| F2b | timeout | - | 3 | 1/1/1 | 1/1/1 | 0/0/0 | 4/4/4 | 4/4/4 | 4/4/4 ; final 0/3 | class not recoverable | 3/3 | 9 / 9 |
| F3 | blocking | - | 3 | 1/1/1 | 1/1/1 | 1/1/1 | 200/200/200 | 200/200/200 | 200/200/200 ; final 3/3 | - | 3/3 | 0 / 0 |
| F3 | timeout | - | 3 | 1/1/1 | 1/1/1 | 1/1/1 | 200/200/200 | 200/200/200 | 200/200/200 ; final 3/3 | - | 3/3 | 0 / 0 |
| F4 | blocking | - | 3 | 1/1/1 | 1/1/1 | 0/0/0 | 19/20/21 | 19/20/21 | 19/20/21 ; final 0/3 | RETRY_EXC with the peer dead | 3/0 | 9 / 255 |
| F4 | timeout | - | 3 | 1/1/1 | 1/1/1 | 0/0/0 | 20/19/21 | 20/19/21 | 20/19/21 ; final 0/3 | RETRY_EXC with the peer dead | 3/0 | 9 / 255 |
| none | blocking | - | 3 | 0/0/0 | 0/0/0 | 0/0/0 | 200/200/200 | 200/200/200 | 200/200/200 ; final 3/3 | - | 3/3 | 0 / 0 |
| none | timeout | - | 3 | 0/0/0 | 0/0/0 | 0/0/0 | 200/200/200 | 200/200/200 | 200/200/200 ; final 3/3 | - | 3/3 | 0 / 0 |

Recovery rounds (ms, median [min-max]):

| fault | mode | variant | rounds | class | d | fault -> device | kernel return -> commit done | prepare / handshake / commit | commit -> replay done | kernel return -> recovered | fault -> recovered |
|---|---|---|--:|---|---|---|---|---|---|---|---|
| F1 | blocking | - | 3 | LOCAL_QP_ERR 3 | d=1 3 | 3.8 [3.7-4.2] | 2.91 [2.85-2.94] | 0.17 [0.16-0.20] / 1.26 [1.24-1.30] / 1.38 [1.36-1.41] | 0.07 [0.07-0.07] | 2.98 [2.92-3.00] | 6.8 [6.7-7.1] |
| F1 | timeout | - | 3 | LOCAL_QP_ERR 3 | d=1 3 | 3.6 [3.5-3.9] | 2.91 [2.86-2.92] | 0.17 [0.14-0.17] / 1.33 [1.29-1.34] / 1.36 [1.32-1.37] | 0.06 [0.06-0.06] | 2.98 [2.92-2.98] | 6.6 [6.5-6.8] |
| F3 | blocking | - | 3 | RETRY_EXC 3 | d=1 3 | 3517.9 [3504.6-3529.4] | 3.23 [3.22-3.27] | 0.24 [0.22-0.25] / 1.92 [1.89-1.93] / 0.98 [0.97-1.00] | 0.08 [0.08-0.08] | 3.31 [3.30-3.35] | 3521.2 [3507.9-3532.8] |
| F3 | timeout | - | 3 | RETRY_EXC 3 | d=1 3 | 3519.1 [3514.2-3527.5] | 3.35 [2.96-3.65] | 0.25 [0.21-0.30] / 2.00 [1.75-2.06] / 0.99 [0.90-1.12] | 0.08 [0.08-0.08] | 3.44 [3.04-3.73] | 3522.6 [3517.3-3531.3] |

### d0 (6 trials)

| fault | mode | variant | n | faults fired | fault rounds | recovered ops | r0 ops ok | r1 data ok | r1 signal exact / final | declined | teardown r0/r1 | exit r0/r1 |
|---|---|---|--:|---|---|---|---|---|---|---|---|---|
| none | blocking | d0 | 3 | 0/0/0 | 1/1/1 | 1/1/1 | 200/200/200 | 200/200/200 | 200/200/200 ; final 3/3 | - | 3/3 | 0 / 0 |
| none | timeout | d0 | 3 | 0/0/0 | 1/1/1 | 1/1/1 | 200/200/200 | 200/200/200 | 200/200/200 ; final 3/3 | - | 3/3 | 0 / 0 |

Recovery rounds (ms, median [min-max]):

| fault | mode | variant | rounds | class | d | fault -> device | kernel return -> commit done | prepare / handshake / commit | commit -> replay done | kernel return -> recovered | fault -> recovered |
|---|---|---|--:|---|---|---|---|---|---|---|---|
| none | blocking | d0 | 3 | FORCED 3 | d=0 3 | - | 2.58 [2.52-2.58] | 0.43 [0.43-0.45] / 1.34 [1.33-1.36] / 0.77 [0.74-0.78] | - | 2.58 [2.52-2.58] | - |
| none | timeout | d0 | 3 | FORCED 3 | d=0 3 | - | 2.66 [2.58-2.68] | 0.45 [0.44-0.47] / 1.34 [1.33-1.43] / 0.80 [0.79-0.83] | - | 2.66 [2.58-2.68] | - |

### config (4 trials)

| fault | mode | variant | n | faults fired | fault rounds | recovered ops | r0 ops ok | r1 data ok | r1 signal exact / final | declined | teardown r0/r1 | exit r0/r1 |
|---|---|---|--:|---|---|---|---|---|---|---|---|---|
| F1 | timeout | cpuproxy_sqdbr | 2 | 1/1 | 1/1 | 0/0 | 51/51 | 51/51 | 51/51 ; final 0/2 | prepare -2: declined: recovery needs the GPU NIC handler | 2/2 | 9 / 9 |
| F1 | timeout | cpuproxy | 2 | 1/1 | 1/1 | 0/0 | 51/51 | 51/51 | 51/51 ; final 0/2 | device wait expired, no error record | 2/2 | 9 / 9 |

### multi (20 trials)

| fault | mode | variant | n | faults fired | fault rounds | recovered ops | r0 ops ok | r1 data ok | r1 signal exact / final | declined | teardown r0/r1 | exit r0/r1 |
|---|---|---|--:|---|---|---|---|---|---|---|---|---|
| F1 | blocking | x5 | 5 | 5/5/5/5/5 | 5/5/5/5/5 | 4/4/4/4/4 | 200/200/200/200/200 | 200/200/200/200/200 | 200/200/200/200/200 ; final 5/5 | - | 5/5 | 0 / 0 |
| F1 | timeout | x5 | 5 | 5/5/5/5/5 | 5/5/5/5/5 | 4/4/4/4/4 | 200/200/200/200/200 | 200/200/200/200/200 | 200/200/200/200/200 ; final 5/5 | - | 5/5 | 0 / 0 |
| F3 | blocking | x5 | 5 | 5/5/5/5/5 | 5/5/5/5/5 | 4/4/4/4/4 | 200/200/200/200/200 | 200/200/200/200/200 | 200/200/200/200/200 ; final 5/5 | - | 5/5 | 0 / 0 |
| F3 | timeout | x5 | 5 | 5/5/5/5/5 | 5/5/5/5/5 | 4/4/4/4/4 | 200/200/200/200/200 | 200/200/200/200/200 | 200/200/200/200/200 ; final 5/5 | - | 5/5 | 0 / 0 |

Recovery rounds (ms, median [min-max]):

| fault | mode | variant | rounds | class | d | fault -> device | kernel return -> commit done | prepare / handshake / commit | commit -> replay done | kernel return -> recovered | fault -> recovered |
|---|---|---|--:|---|---|---|---|---|---|---|---|
| F1 | blocking | x5 | 25 | LOCAL_QP_ERR 25 | d=1 25 | 3.9 [0.6-7.3] | 2.75 [2.65-3.36] | 0.15 [0.12-0.20] / 1.18 [1.14-1.35] / 1.31 [1.26-1.93] | 0.06 [0.06-0.07] | 2.79 [2.71-3.09] | 6.7 [3.4-9.9] |
| F1 | timeout | x5 | 25 | LOCAL_QP_ERR 25 | d=1 25 | 4.0 [0.6-8.9] | 2.76 [2.63-3.32] | 0.15 [0.12-0.20] / 1.18 [1.14-1.37] / 1.32 [1.27-1.86] | 0.06 [0.06-0.07] | 2.78 [2.69-3.12] | 6.7 [3.3-11.9] |
| F3 | blocking | x5 | 25 | RETRY_EXC 25 | d=1 25 | 3734.4 [3622.1-3754.7] | 5.00 [4.40-6.02] | 0.49 [0.39-0.67] / 2.86 [2.62-3.80] / 1.49 [1.29-1.66] | 0.07 [0.07-0.08] | 4.97 [4.47-5.34] | 3739.1 [3627.1-3759.8] |
| F3 | timeout | x5 | 25 | RETRY_EXC 25 | d=1 25 | 3734.4 [3538.3-3754.4] | 5.03 [2.92-6.83] | 0.54 [0.22-0.75] / 2.90 [1.69-4.22] / 1.46 [0.89-1.75] | 0.07 [0.07-0.09] | 4.98 [3.00-5.67] | 3739.2 [3541.4-3759.5] |

### capture_blocking (72 trials)

| fault | mode | variant | n | recorded class (first record) | fp | path | fault -> device (ms) | device -> mailbox (us) | fault -> host API (ms) | target | teardown r0/r1 (finalize ms) | exit r0/r1 |
|---|---|---|--:|---|---|---|---|---|---|---|---|---|
| F1 | blocking | cexit_b16 | 3 | FLUSH_TRAILING 3 | 5/0xf9 | exit 3 | 4.432 [4.083-4.766] | 87 [17-106] | 4.538 [4.170-4.783] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-25]) | 3 / 9 |
| F1 | blocking | cexit_d0 | 3 | FLUSH_TRAILING 3 | 5/0xf9 | exit 3 | 3.819 [3.768-3.985] | 79 [76-102] | 3.921 [3.847-4.061] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-26]) | 3 / 9 |
| F1 | blocking | cexit_d200 | 3 | FLUSH_TRAILING 3 | 5/0xf9 | exit 3 | 3.897 [3.764-4.390] | 74 [68-102] | 3.971 [3.832-4.492] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-25]) | 3 / 9 |
| F1 | blocking | cloop_b16 | 3 | LOCAL_QP_ERR 3 | 5/0xf5 | poll 3 | 3.752 [3.713-3.907] | 79 [75-104] | 3.827 [3.792-4.011] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-25]) | 3 / 9 |
| F1 | blocking | cloop_d0 | 3 | LOCAL_QP_ERR 3 | 5/0xf5 | poll 3 | 4.047 [3.691-4.048] | 45 [15-98] | 4.062 [3.789-4.093] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-25]) | 3 / 9 |
| F1 | blocking | cloop_d2000 | 3 | FLUSH_TRAILING 3 | 5/0xf9 | poll 3 | 5.985 [5.923-5.995] | 52 [33-92] | 6.047 [5.956-6.077] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-25]) | 3 / 9 |
| F1 | blocking | cloop_d200 | 3 | FLUSH_TRAILING 3 | 5/0xf9 | poll 3 | 4.073 [3.934-4.333] | 71 [44-85] | 4.158 [4.005-4.377] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-25]) | 3 / 9 |
| F1 | blocking | csent_d2000 | 3 | LOCAL_QP_ERR 3 | 5/0xf5 | sentinel 3 | 3.906 [3.877-3.980] | 89 [44-103] | 4.009 [3.966-4.024] | rc9 3 | 3/3 returned (17 [17-17] / 25 [25-25]) | 3 / 9 |
| F1 | blocking | csent_d200 | 3 | LOCAL_QP_ERR 3 | 5/0xf5 | sentinel 3 | 3.817 [3.815-3.912] | 87 [70-94] | 3.911 [3.902-3.982] | rc9 3 | 3/3 returned (17 [17-17] / 25 [25-26]) | 3 / 9 |
| F2b | blocking | cexit_b16 | 3 | FLUSH_TRAILING 3 | 5/0xf9 | exit 3 | 1.574 [1.569-1.587] | 52 [13-57] | 1.621 [1.587-1.644] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-29]) | 3 / 9 |
| F2b | blocking | cexit_d0 | 3 | FLUSH_TRAILING 3 | 5/0xf9 | exit 3 | 1.551 [1.346-3.922] | 37 [12-97] | 1.563 [1.383-4.019] | rc9 3 | 3/3 returned (19 [19-19] / 29 [26-29]) | 3 / 9 |
| F2b | blocking | cexit_d2000 | 3 | FLUSH_TRAILING 3 | 5/0xf9 | exit 3 | 2.248 [1.955-2.268] | 81 [9-96] | 2.329 [1.964-2.364] | rc9 3 | 3/3 returned (19 [17-19] / 25 [25-28]) | 3 / 9 |
| F2b | blocking | cexit_d200 | 3 | FLUSH_TRAILING 3 | 5/0xf9 | exit 3 | 1.286 [1.274-1.290] | 81 [46-104] | 1.371 [1.320-1.390] | rc9 3 | 3/3 returned (19 [17-19] / 27 [26-27]) | 3 / 9 |
| F2b | blocking | cloop_b16 | 3 | REM_ACCESS 3 | 10/0x88 | poll 3 | 1.238 [1.220-1.245] | 69 [27-79] | 1.289 [1.272-1.317] | rc9 3 | 3/3 returned (19 [19-19] / 26 [25-28]) | 3 / 9 |
| F2b | blocking | cloop_d0 | 3 | REM_ACCESS 3 | 10/0x88 | poll 3 | 1.265 [1.253-1.298] | 61 [35-108] | 1.359 [1.288-1.373] | rc9 3 | 3/3 returned (19 [18-19] / 27 [27-27]) | 3 / 9 |
| F2b | blocking | cloop_d2000 | 3 | FLUSH_TRAILING 3 | 5/0xf9 | poll 3 | 2.265 [2.265-2.266] | 66 [11-99] | 2.331 [2.276-2.365] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-29]) | 3 / 9 |
| F2b | blocking | cloop_d200 | 3 | REM_ACCESS 3 | 10/0x88 | poll 3 | 1.224 [1.219-1.232] | 65 [30-96] | 1.297 [1.249-1.320] | rc9 3 | 3/3 returned (19 [19-19] / 27 [26-28]) | 3 / 9 |
| F2b | blocking | csent_b16d2000 | 3 | REM_ACCESS 3 | 10/0x88 | sentinel 3 | 1.249 [1.230-1.254] | 39 [34-66] | 1.293 [1.264-1.315] | rc9 3 | 3/3 returned (18 [17-19] / 26 [25-26]) | 3 / 9 |
| F2b | blocking | csent_d0 | 3 | REM_ACCESS 3 | 10/0x88 | poll 3 | 1.228 [1.219-1.232] | 62 [30-93] | 1.281 [1.262-1.321] | rc9 3 | 3/3 returned (19 [19-19] / 27 [27-27]) | 3 / 9 |
| F2b | blocking | csent_d2000 | 3 | REM_ACCESS 3 | 10/0x88 | sentinel 3 | 1.215 [1.205-1.235] | 87 [71-106] | 1.321 [1.276-1.322] | rc9 3 | 3/3 returned (18 [17-19] / 25 [25-29]) | 3 / 9 |
| F2b | blocking | csent_d200 | 3 | REM_ACCESS 3 | 10/0x88 | poll 3 | 1.228 [1.204-1.237] | 33 [11-61] | 1.239 [1.237-1.298] | rc9 3 | 3/3 returned (19 [17-19] / 25 [25-25]) | 3 / 9 |
| F3 | blocking | cexit_b16 | 3 | FLUSH_TRAILING 3 | 5/0xf9 | exit 3 | 3604.568 [3529.622-3605.292] | 47 [18-57] | 3604.586 [3529.679-3605.339] | rc9 3 | 3/3 returned (19 [18-19] / 27 [27-27]) | 3 / 9 |
| F3 | blocking | cloop_b16 | 3 | RETRY_EXC 3 | 12/0x81 | poll 3 | 3591.868 [3581.323-3606.599] | 88 [45-108] | 3591.913 [3581.431-3606.687] | rc9 3 | 3/3 returned (18 [18-18] / 27 [26-27]) | 3 / 9 |
| F3 | blocking | cloop_d2000 | 3 | RETRY_EXC 3 | 12/0x81 | poll 3 | 3595.881 [3553.908-3605.400] | 77 [77-105] | 3595.986 [3553.985-3605.477] | rc9 3 | 3/3 returned (18 [18-18] / 28 [28-28]) | 3 / 9 |

### flagoff (8 trials)

| fault | mode | variant | n | recorded class (first record) | fp | path | fault -> device (ms) | device -> mailbox (us) | fault -> host API (ms) | target | teardown r0/r1 (finalize ms) | exit r0/r1 |
|---|---|---|--:|---|---|---|---|---|---|---|---|---|
| F1 | blocking | - | 2 | - 2 | - | - 2 | - | - | - | rc7 2 | 0/0 returned (- / -) | 7 / 7 |
| F2b | blocking | - | 2 | - 2 | - | - 2 | - | - | - | rc7 2 | 0/0 returned (- / -) | 7 / 7 |
| F3 | blocking | - | 2 | - 2 | - | - 2 | - | - | - | rc7 2 | 0/0 returned (- / -) | 7 / 7 |
| F3 | timeout | - | 2 | NONE 2 | 0/0x00 | - 2 | - | - | - | rc7 2 | 0/0 returned (- / -) | 7 / 7 |

### latency (results/b2/lat)

| cell | reps | p50 us median [min-max] | p99 us median [min-max] | mean us (median of reps) | errors |
|---|--:|---|---|---|---|
| lat256k_off | 30 | 40.32 [40.03-40.58] | 40.99 [40.96-40.99] | 40.27 [40.00-40.48] | 0 |
| lat4k_off | 30 | 12.62 [12.29-14.24] | 13.95 [13.47-14.43] | 12.75 [12.31-14.12] | 0 |
| lat256k_on | 30 | 40.42 [40.16-40.54] | 40.99 [40.99-40.99] | 40.37 [40.10-40.50] | 0 |
| lat256k_sent | 30 | 40.42 [40.35-40.61] | 40.99 [40.99-40.99] | 40.35 [40.30-40.47] | 0 |
| lat4k_on | 30 | 12.70 [12.32-12.83] | 13.90 [13.57-14.14] | 12.85 [12.42-12.89] | 0 |
| lat4k_sent | 30 | 12.61 [12.51-12.67] | 13.76 [13.60-14.14] | 12.65 [12.59-12.85] | 0 |
