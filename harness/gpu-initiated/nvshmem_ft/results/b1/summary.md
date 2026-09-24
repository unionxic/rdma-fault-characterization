
### classify (30 trials)

| fault | mode | variant | n | recorded class (first record) | fp | path | fault -> device (ms) | device -> mailbox (us) | fault -> host API (ms) | target | teardown r0/r1 (finalize ms) | exit r0/r1 |
|---|---|---|--:|---|---|---|---|---|---|---|---|---|
| F1 | blocking | - | 3 | LOCAL_QP_ERR 3 | 5/0xf5 | poll 3 | 3.529 [3.303-3.885] | 49 [8-101] | 3.537 [3.404-3.934] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-25]) | 3 / 9 |
| F1 | timeout | - | 3 | LOCAL_QP_ERR 3 | 5/0xf5 | bounded 3 | 3.361 [3.324-3.623] | 67 [36-103] | 3.427 [3.397-3.690] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-25]) | 3 / 9 |
| F2b | blocking | - | 3 | REM_ACCESS 3 | 10/0x88 | poll 3 | 4.380 [4.379-4.385] | 56 [10-99] | 4.436 [4.389-4.484] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-25]) | 3 / 9 |
| F2b | timeout | - | 3 | REM_ACCESS 3 | 10/0x88 | bounded 3 | 4.426 [4.390-5.589] | 29 [23-105] | 4.531 [4.419-5.612] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-28]) | 3 / 9 |
| F3 | blocking | - | 3 | RETRY_EXC 3 | 12/0x81 | poll 3 | 3583.450 [3552.748-3622.414] | 50 [24-82] | 3583.532 [3552.772-3622.464] | rc9 3 | 3/3 returned (18 [18-18] / 26 [26-26]) | 3 / 9 |
| F3 | timeout | - | 3 | RETRY_EXC 3 | 12/0x81 | bounded 3 | 3630.457 [3594.882-3673.830] | 55 [48-59] | 3630.505 [3594.941-3673.885] | rc9 3 | 3/3 returned (18 [18-18] / 26 [26-26]) | 3 / 9 |
| F4 | blocking | - | 3 | RETRY_EXC 3 | 12/0x81 | poll 3 | 3735.214 [3723.951-3742.595] | 73 [43-88] | 3735.287 [3724.039-3742.638] | rc255 3 | 3/0 returned (18 [18-18] / -) | 3 / 255 |
| F4 | timeout | - | 3 | RETRY_EXC 3 | 12/0x81 | bounded 3 | 3733.841 [3580.521-3793.119] | 46 [23-85] | 3733.864 [3580.606-3793.165] | rc255 3 | 3/0 returned (18 [18-18] / -) | 3 / 255 |
| none | blocking | - | 3 | - 3 | - | - 3 | - | - | - | rc0 3 | 3/3 returned (20 [20-20] / 26 [26-26]) | 0 / 0 |
| none | timeout | - | 3 | - 3 | - | - 3 | - | - | - | rc0 3 | 3/3 returned (20 [20-21] / 26 [26-26]) | 0 / 0 |

### recover (30 trials)

| fault | mode | variant | n | faults fired | fault rounds | recovered ops | r0 ops ok | r1 data ok | r1 signal exact / final | declined | teardown r0/r1 | exit r0/r1 |
|---|---|---|--:|---|---|---|---|---|---|---|---|---|
| F1 | blocking | - | 3 | 1/1/1 | 1/1/1 | 1/1/1 | 200/200/200 | 200/200/200 | 200/200/200 ; final 3/3 | - | 3/3 | 0 / 0 |
| F1 | timeout | - | 3 | 1/1/1 | 1/1/1 | 1/1/1 | 200/200/200 | 200/200/200 | 200/200/200 ; final 3/3 | - | 3/3 | 0 / 0 |
| F2b | blocking | - | 3 | 1/1/1 | 1/1/1 | 0/0/0 | 4/4/4 | 4/4/4 | 4/4/4 ; final 0/3 | class not recoverable | 3/3 | 9 / 9 |
| F2b | timeout | - | 3 | 1/1/1 | 1/1/1 | 0/0/0 | 4/4/4 | 4/4/4 | 4/4/4 ; final 0/3 | class not recoverable | 3/3 | 9 / 9 |
| F3 | blocking | - | 3 | 1/1/1 | 1/1/1 | 1/1/1 | 200/200/200 | 200/200/200 | 200/200/200 ; final 3/3 | - | 3/3 | 0 / 0 |
| F3 | timeout | - | 3 | 1/1/1 | 1/1/1 | 1/1/1 | 200/200/200 | 200/200/200 | 200/200/200 ; final 3/3 | - | 3/3 | 0 / 0 |
| F4 | blocking | - | 3 | 1/1/1 | 1/1/1 | 0/0/0 | 18/20/21 | 18/20/21 | 18/20/21 ; final 0/3 | RETRY_EXC with the peer dead | 3/0 | 9 / 255 |
| F4 | timeout | - | 3 | 1/1/1 | 1/1/1 | 0/0/0 | 20/21/21 | 20/21/21 | 20/21/21 ; final 0/3 | RETRY_EXC with the peer dead | 3/0 | 9 / 255 |
| none | blocking | - | 3 | 0/0/0 | 0/0/0 | 0/0/0 | 200/200/200 | 200/200/200 | 200/200/200 ; final 3/3 | - | 3/3 | 0 / 0 |
| none | timeout | - | 3 | 0/0/0 | 0/0/0 | 0/0/0 | 200/200/200 | 200/200/200 | 200/200/200 ; final 3/3 | - | 3/3 | 0 / 0 |

Recovery rounds (ms, median [min-max]):

| fault | mode | variant | rounds | class | d | fault -> device | kernel return -> commit done | prepare / handshake / commit | commit -> replay done | kernel return -> recovered | fault -> recovered |
|---|---|---|--:|---|---|---|---|---|---|---|---|
| F1 | blocking | - | 3 | LOCAL_QP_ERR 3 | d=1 3 | 3.6 [3.4-3.7] | 2.91 [2.88-2.94] | 0.15 [0.15-0.18] / 1.27 [1.26-1.27] / 1.36 [1.35-1.40] | 0.07 [0.07-0.07] | 2.98 [2.94-3.00] | 6.6 [6.4-6.7] |
| F1 | timeout | - | 3 | LOCAL_QP_ERR 3 | d=1 3 | 3.6 [3.6-3.7] | 2.94 [2.91-3.07] | 0.17 [0.14-0.17] / 1.29 [1.26-1.38] / 1.35 [1.32-1.43] | 0.06 [0.06-0.06] | 3.00 [2.98-3.13] | 6.7 [6.6-6.7] |
| F3 | blocking | - | 3 | RETRY_EXC 3 | d=1 3 | 3761.1 [3746.2-3771.5] | 3.55 [3.48-3.60] | 0.33 [0.30-0.39] / 2.05 [1.94-2.06] / 1.11 [1.02-1.18] | 0.07 [0.07-0.08] | 3.63 [3.56-3.68] | 3764.8 [3749.9-3775.1] |
| F3 | timeout | - | 3 | RETRY_EXC 3 | d=1 3 | 3727.8 [3499.1-3792.0] | 3.49 [2.84-3.68] | 0.28 [0.19-0.29] / 2.07 [1.71-2.25] / 1.05 [0.83-1.10] | 0.07 [0.07-0.07] | 3.56 [2.92-3.75] | 3730.7 [3502.9-3795.5] |

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
| F1 | blocking | x5 | 25 | LOCAL_QP_ERR 25 | d=1 25 | 4.0 [0.6-7.4] | 2.74 [2.62-3.30] | 0.15 [0.12-0.18] / 1.18 [1.14-1.34] / 1.32 [1.26-1.87] | 0.07 [0.06-0.07] | 2.78 [2.68-3.02] | 6.6 [3.3-9.9] |
| F1 | timeout | x5 | 25 | LOCAL_QP_ERR 25 | d=1 25 | 3.9 [0.6-8.6] | 2.77 [2.56-3.39] | 0.15 [0.12-0.19] / 1.17 [1.14-1.41] / 1.31 [1.26-1.91] | 0.06 [0.06-0.07] | 2.81 [2.62-3.16] | 6.6 [3.3-11.7] |
| F3 | blocking | x5 | 25 | RETRY_EXC 25 | d=1 25 | 3734.4 [3589.1-3754.4] | 5.11 [4.48-6.12] | 0.52 [0.31-0.68] / 2.90 [2.64-3.88] / 1.45 [1.28-1.65] | 0.07 [0.07-0.08] | 5.00 [4.55-5.46] | 3739.2 [3594.5-3759.7] |
| F3 | timeout | x5 | 25 | RETRY_EXC 25 | d=1 25 | 3734.4 [3570.8-3754.6] | 4.98 [2.90-6.58] | 0.51 [0.25-0.71] / 2.92 [1.74-4.19] / 1.44 [0.80-1.68] | 0.07 [0.07-0.08] | 4.95 [2.97-5.32] | 3739.2 [3576.0-3759.8] |

### capture (72 trials)

| fault | mode | variant | n | recorded class (first record) | fp | path | fault -> device (ms) | device -> mailbox (us) | fault -> host API (ms) | target | teardown r0/r1 (finalize ms) | exit r0/r1 |
|---|---|---|--:|---|---|---|---|---|---|---|---|---|
| F1 | timeout | cexit_b16 | 3 | LOCAL_QP_ERR 3 | 5/0xf5 | bounded 3 | 3.821 [3.782-3.913] | 51 [42-58] | 3.879 [3.824-3.964] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-25]) | 3 / 9 |
| F1 | timeout | cexit_d0 | 3 | LOCAL_QP_ERR 3 | 5/0xf5 | bounded 3 | 3.506 [3.427-3.602] | 86 [71-102] | 3.608 [3.498-3.688] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-25]) | 3 / 9 |
| F1 | timeout | cexit_d200 | 3 | FLUSH_TRAILING 3 | 5/0xf9 | bounded 3 | 3.727 [3.617-3.881] | 100 [18-102] | 3.745 [3.719-3.981] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-25]) | 3 / 9 |
| F1 | timeout | cloop_b16 | 3 | LOCAL_QP_ERR 3 | 5/0xf5 | bounded 3 | 3.814 [3.783-4.039] | 24 [15-87] | 3.838 [3.798-4.126] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-26]) | 3 / 9 |
| F1 | timeout | cloop_d0 | 3 | LOCAL_QP_ERR 3 | 5/0xf5 | bounded 3 | 3.508 [3.506-3.522] | 48 [33-85] | 3.554 [3.541-3.607] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-25]) | 3 / 9 |
| F1 | timeout | cloop_d2000 | 3 | FLUSH_TRAILING 3 | 5/0xf9 | bounded 3 | 5.882 [5.828-5.917] | 78 [76-98] | 5.958 [5.926-5.995] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-25]) | 3 / 9 |
| F1 | timeout | cloop_d200 | 3 | FLUSH_TRAILING 3 | 5/0xf9 | bounded 3 | 3.808 [3.778-4.169] | 63 [18-103] | 3.871 [3.796-4.272] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-25]) | 3 / 9 |
| F1 | timeout | csent_d2000 | 3 | LOCAL_QP_ERR 3 | 5/0xf5 | sentinel 3 | 3.391 [1.909-3.461] | 81 [73-97] | 3.464 [2.006-3.542] | rc9 3 | 3/3 returned (17 [17-17] / 25 [25-25]) | 3 / 9 |
| F1 | timeout | csent_d200 | 3 | LOCAL_QP_ERR 3 | 5/0xf5 | sentinel 3 | 3.564 [3.489-3.570] | 99 [32-104] | 3.602 [3.593-3.663] | rc9 3 | 3/3 returned (17 [17-17] / 25 [25-25]) | 3 / 9 |
| F2b | timeout | cexit_b16 | 3 | REM_ACCESS 3 | 10/0x88 | bounded 3 | 1.214 [1.203-1.226] | 73 [48-91] | 1.276 [1.274-1.305] | rc9 3 | 3/3 returned (19 [18-19] / 25 [25-25]) | 3 / 9 |
| F2b | timeout | cexit_d0 | 3 | REM_ACCESS 3 | 10/0x88 | bounded 3 | 1.447 [1.353-4.408] | 29 [24-78] | 1.525 [1.377-4.437] | rc9 3 | 3/3 returned (19 [19-20] / 25 [25-29]) | 3 / 9 |
| F2b | timeout | cexit_d2000 | 3 | FLUSH_TRAILING 3 | 5/0xf9 | bounded 3 | 2.265 [2.263-2.266] | 30 [15-36] | 2.296 [2.278-2.301] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-29]) | 3 / 9 |
| F2b | timeout | cexit_d200 | 3 | REM_ACCESS 3 | 10/0x88 | bounded 3 | 1.216 [1.215-1.219] | 47 [27-99] | 1.266 [1.243-1.314] | rc9 3 | 3/3 returned (19 [17-19] / 25 [25-28]) | 3 / 9 |
| F2b | timeout | cloop_b16 | 3 | REM_ACCESS 3 | 10/0x88 | bounded 3 | 1.204 [1.200-1.214] | 87 [85-99] | 1.301 [1.285-1.303] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-29]) | 3 / 9 |
| F2b | timeout | cloop_d0 | 3 | REM_ACCESS 3 | 10/0x88 | bounded 3 | 1.258 [1.223-1.263] | 71 [25-88] | 1.329 [1.248-1.351] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-29]) | 3 / 9 |
| F2b | timeout | cloop_d2000 | 3 | FLUSH_TRAILING 3 | 5/0xf9 | bounded 3 | 2.268 [2.268-2.275] | 85 [66-107] | 2.360 [2.334-2.375] | rc9 3 | 3/3 returned (19 [19-19] / 27 [25-29]) | 3 / 9 |
| F2b | timeout | cloop_d200 | 3 | REM_ACCESS 3 | 10/0x88 | bounded 3 | 1.225 [1.210-1.233] | 34 [19-85] | 1.259 [1.252-1.295] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-28]) | 3 / 9 |
| F2b | timeout | csent_b16d2000 | 3 | REM_ACCESS 3 | 10/0x88 | sentinel 3 | 1.233 [1.226-1.259] | 35 [25-69] | 1.284 [1.261-1.302] | rc9 3 | 3/3 returned (19 [17-19] / 25 [25-29]) | 3 / 9 |
| F2b | timeout | csent_d0 | 3 | REM_ACCESS 3 | 10/0x88 | bounded 3 | 1.236 [1.221-1.253] | 41 [14-76] | 1.277 [1.267-1.297] | rc9 3 | 3/3 returned (18 [18-19] / 25 [25-29]) | 3 / 9 |
| F2b | timeout | csent_d2000 | 3 | REM_ACCESS 3 | 10/0x88 | sentinel 3 | 1.212 [1.198-1.219] | 64 [22-82] | 1.276 [1.241-1.280] | rc9 3 | 3/3 returned (19 [17-19] / 25 [25-26]) | 3 / 9 |
| F2b | timeout | csent_d200 | 3 | REM_ACCESS 3 | 10/0x88 | bounded 3 | 1.230 [1.213-1.230] | 92 [26-102] | 1.322 [1.239-1.332] | rc9 2, rc 1 | 3/3 returned (19 [17-20] / 26 [25-26]) | ,3 / ,9 |
| F3 | timeout | cexit_b16 | 3 | RETRY_EXC 3 | 12/0x81 | bounded 3 | 3560.588 [3512.306-3603.980] | 79 [66-129] | 3560.654 [3512.385-3604.109] | rc9 3 | 3/3 returned (19 [18-19] / 26 [26-27]) | 3 / 9 |
| F3 | timeout | cloop_b16 | 3 | RETRY_EXC 3 | 12/0x81 | bounded 3 | 3627.865 [3593.719-3637.381] | 125 [58-133] | 3627.923 [3593.844-3637.514] | rc9 3 | 3/3 returned (18 [18-18] / 26 [26-26]) | 3 / 9 |
| F3 | timeout | cloop_d2000 | 3 | RETRY_EXC 3 | 12/0x81 | bounded 3 | 3596.948 [3574.378-3602.288] | 84 [71-143] | 3597.091 [3574.462-3602.359] | rc9 3 | 3/3 returned (18 [18-18] / 26 [26-26]) | 3 / 9 |

### capture_blocking (72 trials)

| fault | mode | variant | n | recorded class (first record) | fp | path | fault -> device (ms) | device -> mailbox (us) | fault -> host API (ms) | target | teardown r0/r1 (finalize ms) | exit r0/r1 |
|---|---|---|--:|---|---|---|---|---|---|---|---|---|
| F1 | blocking | cexit_b16 | 3 | FLUSH_TRAILING 3 | 5/0xf9 | exit 3 | 4.221 [4.123-4.353] | 93 [70-109] | 4.330 [4.216-4.423] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-25]) | 3 / 9 |
| F1 | blocking | cexit_d0 | 3 | FLUSH_TRAILING 3 | 5/0xf9 | exit 3 | 3.662 [3.658-3.666] | 19 [14-29] | 3.680 [3.677-3.691] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-25]) | 3 / 9 |
| F1 | blocking | cexit_d200 | 3 | FLUSH_TRAILING 3 | 5/0xf9 | exit 3 | 3.733 [3.690-10.305] | 91 [32-95] | 3.828 [3.722-10.396] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-25]) | 3 / 9 |
| F1 | blocking | cloop_b16 | 3 | LOCAL_QP_ERR 3 | 5/0xf5 | poll 3 | 4.162 [3.639-4.463] | 34 [26-81] | 4.188 [3.673-4.544] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-26]) | 3 / 9 |
| F1 | blocking | cloop_d0 | 3 | LOCAL_QP_ERR 3 | 5/0xf5 | poll 3 | 3.802 [3.660-3.970] | 48 [34-49] | 3.836 [3.709-4.018] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-25]) | 3 / 9 |
| F1 | blocking | cloop_d2000 | 3 | FLUSH_TRAILING 3 | 5/0xf9 | poll 3 | 5.950 [5.739-6.434] | 46 [28-75] | 5.978 [5.814-6.480] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-25]) | 3 / 9 |
| F1 | blocking | cloop_d200 | 3 | FLUSH_TRAILING 3 | 5/0xf9 | poll 3 | 3.942 [3.919-3.969] | 58 [12-75] | 4.017 [3.931-4.027] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-25]) | 3 / 9 |
| F1 | blocking | csent_d2000 | 3 | LOCAL_QP_ERR 3 | 5/0xf5 | sentinel 3 | 3.708 [3.513-3.723] | 57 [16-98] | 3.765 [3.529-3.821] | rc9 3 | 3/3 returned (17 [17-18] / 25 [25-26]) | 3 / 9 |
| F1 | blocking | csent_d200 | 3 | LOCAL_QP_ERR 3 | 5/0xf5 | sentinel 3 | 3.653 [3.562-3.933] | 67 [29-103] | 3.682 [3.629-4.036] | rc9 3 | 3/3 returned (17 [17-17] / 25 [25-25]) | 3 / 9 |
| F2b | blocking | cexit_b16 | 3 | FLUSH_TRAILING 3 | 5/0xf9 | exit 3 | 1.577 [1.575-1.581] | 84 [72-105] | 1.665 [1.649-1.680] | rc9 3 | 3/3 returned (19 [17-19] / 25 [25-29]) | 3 / 9 |
| F2b | blocking | cexit_d0 | 3 | FLUSH_TRAILING 3 | 5/0xf9 | exit 3 | 1.518 [1.458-4.686] | 46 [20-96] | 1.564 [1.554-4.706] | rc9 3 | 3/3 returned (19 [19-20] / 29 [25-30]) | 3 / 9 |
| F2b | blocking | cexit_d2000 | 3 | FLUSH_TRAILING 3 | 5/0xf9 | exit 3 | 2.265 [2.249-2.267] | 48 [12-107] | 2.297 [2.279-2.372] | rc9 3 | 3/3 returned (19 [19-19] / 26 [25-26]) | 3 / 9 |
| F2b | blocking | cexit_d200 | 3 | FLUSH_TRAILING 3 | 5/0xf9 | exit 3 | 1.285 [1.284-1.290] | 41 [17-94] | 1.331 [1.301-1.379] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-25]) | 3 / 9 |
| F2b | blocking | cloop_b16 | 3 | REM_ACCESS 3 | 10/0x88 | poll 3 | 1.231 [1.222-1.232] | 89 [50-96] | 1.321 [1.272-1.327] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-28]) | 3 / 9 |
| F2b | blocking | cloop_d0 | 3 | REM_ACCESS 3 | 10/0x88 | poll 3 | 1.246 [1.224-1.292] | 86 [31-90] | 1.336 [1.255-1.378] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-25]) | 3 / 9 |
| F2b | blocking | cloop_d2000 | 3 | FLUSH_TRAILING 3 | 5/0xf9 | poll 3 | 2.268 [2.246-2.282] | 93 [49-104] | 2.372 [2.295-2.375] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-29]) | 3 / 9 |
| F2b | blocking | cloop_d200 | 3 | REM_ACCESS 3 | 10/0x88 | poll 3 | 1.221 [1.212-1.230] | 56 [39-92] | 1.286 [1.260-1.304] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-25]) | 3 / 9 |
| F2b | blocking | csent_b16d2000 | 3 | REM_ACCESS 3 | 10/0x88 | sentinel 3 | 1.212 [1.204-1.226] | 47 [29-69] | 1.259 [1.255-1.273] | rc9 3 | 3/3 returned (19 [17-19] / 29 [25-29]) | 3 / 9 |
| F2b | blocking | csent_d0 | 3 | REM_ACCESS 3 | 10/0x88 | poll 3 | 1.211 [1.208-1.224] | 53 [27-55] | 1.263 [1.251-1.264] | rc9 3 | 3/3 returned (17 [17-19] / 25 [25-25]) | 3 / 9 |
| F2b | blocking | csent_d2000 | 3 | REM_ACCESS 3 | 10/0x88 | sentinel 3 | 1.223 [1.220-1.260] | 54 [40-103] | 1.314 [1.260-1.326] | rc9 3 | 3/3 returned (19 [19-19] / 25 [25-29]) | 3 / 9 |
| F2b | blocking | csent_d200 | 3 | REM_ACCESS 3 | 10/0x88 | poll 3 | 1.217 [1.212-1.234] | 84 [52-102] | 1.314 [1.269-1.318] | rc9 3 | 3/3 returned (17 [17-19] / 28 [25-28]) | 3 / 9 |
| F3 | blocking | cexit_b16 | 3 | FLUSH_TRAILING 3 | 5/0xf9 | exit 3 | 3590.505 [3556.699-3626.189] | 83 [55-125] | 3590.560 [3556.824-3626.272] | rc9 3 | 3/3 returned (19 [18-19] / 27 [26-27]) | 3 / 9 |
| F3 | blocking | cloop_b16 | 3 | RETRY_EXC 3 | 12/0x81 | poll 3 | 3607.619 [3601.534-3621.221] | 108 [95-125] | 3607.744 [3601.629-3621.329] | rc9 3 | 3/3 returned (18 [18-18] / 26 [26-26]) | 3 / 9 |
| F3 | blocking | cloop_d2000 | 3 | RETRY_EXC 3 | 12/0x81 | poll 3 | 3596.081 [3593.439-3599.565] | 66 [33-101] | 3596.182 [3593.472-3599.631] | rc9 3 | 3/3 returned (18 [18-18] / 26 [26-26]) | 3 / 9 |

### flagoff (8 trials)

| fault | mode | variant | n | recorded class (first record) | fp | path | fault -> device (ms) | device -> mailbox (us) | fault -> host API (ms) | target | teardown r0/r1 (finalize ms) | exit r0/r1 |
|---|---|---|--:|---|---|---|---|---|---|---|---|---|
| F1 | blocking | - | 2 | - 2 | - | - 2 | - | - | - | rc7 2 | 0/0 returned (- / -) | 7 / 7 |
| F2b | blocking | - | 2 | - 2 | - | - 2 | - | - | - | rc7 2 | 0/0 returned (- / -) | 7 / 7 |
| F3 | blocking | - | 2 | - 2 | - | - 2 | - | - | - | rc7 2 | 0/0 returned (- / -) | 7 / 7 |
| F3 | timeout | - | 2 | NONE 2 | 0/0x00 | - 2 | - | - | - | rc7 2 | 0/0 returned (- / -) | 7 / 7 |

### d0 (6 trials)

| fault | mode | variant | n | faults fired | fault rounds | recovered ops | r0 ops ok | r1 data ok | r1 signal exact / final | declined | teardown r0/r1 | exit r0/r1 |
|---|---|---|--:|---|---|---|---|---|---|---|---|---|
| none | blocking | d0 | 3 | 0/0/0 | 1/1/1 | 1/1/1 | 200/200/200 | 200/200/200 | 200/200/200 ; final 3/3 | - | 3/3 | 0 / 0 |
| none | timeout | d0 | 3 | 0/0/0 | 1/1/1 | 1/1/1 | 200/200/200 | 200/200/200 | 200/200/200 ; final 3/3 | - | 3/3 | 0 / 0 |

Recovery rounds (ms, median [min-max]):

| fault | mode | variant | rounds | class | d | fault -> device | kernel return -> commit done | prepare / handshake / commit | commit -> replay done | kernel return -> recovered | fault -> recovered |
|---|---|---|--:|---|---|---|---|---|---|---|---|
| none | blocking | d0 | 3 | NONE 3 | d=0 3 | - | 2.58 [2.56-2.62] | 0.46 [0.43-0.49] / 1.32 [1.31-1.32] / 0.80 [0.80-0.80] | - | 2.58 [2.56-2.62] | - |
| none | timeout | d0 | 3 | NONE 3 | d=0 3 | - | 2.74 [2.73-2.85] | 0.49 [0.47-0.57] / 1.44 [1.37-1.44] / 0.83 [0.81-0.85] | - | 2.74 [2.73-2.85] | - |

### config (4 trials)

| fault | mode | variant | n | faults fired | fault rounds | recovered ops | r0 ops ok | r1 data ok | r1 signal exact / final | declined | teardown r0/r1 | exit r0/r1 |
|---|---|---|--:|---|---|---|---|---|---|---|---|---|
| F1 | timeout | cpuproxy_sqdbr | 2 | 1/1 | 1/1 | 0/0 | 51/51 | 51/51 | 51/51 ; final 0/2 | prepare -2: declined: recovery needs the GPU NIC handler | 2/2 | 9 / 9 |
| F1 | timeout | cpuproxy | 2 | 1/1 | 1/1 | 0/0 | 51/51 | 51/51 | 51/51 ; final 0/2 | device wait expired, no error record | 2/2 | 9 / 9 |

### latency (b1/lat)

| cell | reps | p50 us median [min-max] | p99 us median [min-max] | mean us (median of reps) | errors |
|---|--:|---|---|---|---|
| lat256k_off | 20 | 40.38 [40.19-40.38] | 40.99 [40.99-40.99] | 40.33 [40.13-40.34] | 0 |
| lat4k_off | 20 | 12.48 [12.32-12.51] | 13.73 [13.54-14.11] | 12.56 [12.43-12.62] | 0 |
| lat256k_on | 20 | 40.90 [40.58-40.93] | 42.06 [40.99-42.21] | 40.79 [40.44-40.88] | 0 |
| lat4k_on | 20 | 13.06 [12.61-13.15] | 14.18 [13.95-14.34] | 13.11 [12.78-13.22] | 0 |
