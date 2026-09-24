## Outcomes

| fault | rec | wait | n | shots fired | recovered events | replay failed | declined | r0 ops ok | r1 data exact | signal exact | final async (r0) | teardown r0/r1 | left |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| D0 | 1 | blocking | 1 | 0 | 3 | 0 | 0 | 120/120 | 1/1 | 1/1 | no error | no error/no error | 0 |
| D0 | 1 | timeout | 1 | 0 | 3 | 0 | 0 | 120/120 | 1/1 | 1/1 | no error | no error/no error | 0 |
| F1 | 1 | blocking | 2 | 1,1 | 1,1 | 0,0 | 0,0 | 120/120,120/120 | 2/2 | 2/2 | no error | no error/no error | 0 |
| F1 x5 | 1 | blocking | 1 | 5 | 4 | 1 | 0 | 160/160 | 1/1 | 1/1 | no error | no error/no error | 0 |
| F1 | 1 | timeout | 2 | 1,1 | 1,1 | 0,0 | 0,0 | 120/120,120/120 | 2/2 | 2/2 | no error | no error/no error | 0 |
| F1 x5 | 1 | timeout | 1 | 5 | 4 | 1 | 0 | 160/160 | 1/1 | 1/1 | no error | no error/no error | 0 |
| F2 | 1 | blocking | 1 | 0 | 0 | 0 | 1 | 0/120 | 0/1 | 0/1 | remote process exited or there was a network error | no error/no error | 0 |
| F2 | 1 | timeout | 1 | 0 | 0 | 0 | 1 | 0/120 | 0/1 | 0/1 | remote process exited or there was a network error | no error/no error | 0 |
| F3 | 1 | blocking | 1 | 1 | 1 | 0 | 0 | 120/120 | 1/1 | 1/1 | no error | no error/no error | 0 |
| F3 x5 | 1 | blocking | 1 | 5 | 4 | 1 | 0 | 200/200 | 1/1 | 1/1 | no error | no error/no error | 0 |
| F3 | 1 | timeout | 1 | 1 | 1 | 0 | 0 | 120/120 | 1/1 | 1/1 | no error | no error/no error | 0 |
| F3 x5 | 1 | timeout | 1 | 5 | 4 | 1 | 0 | 200/200 | 1/1 | 1/1 | no error | no error/no error | 0 |
| F4 | 1 | blocking | 1 | 0 | 0 | 0 | 1 | 183/400 | 0/1 | 0/1 | remote process exited or there was a network error | no error/- | 0 |
| F4 | 1 | timeout | 1 | 0 | 0 | 0 | 1 | 184/400 | 0/1 | 0/1 | remote process exited or there was a network error | no error/- | 0 |
| none | 1 | blocking | 1 | 0 | 0 | 0 | 0 | 120/120 | 1/1 | 1/1 | no error | no error/no error | 0 |
| none | 1 | timeout | 1 | 0 | 0 | 0 | 0 | 120/120 | 1/1 | 1/1 | no error | no error/no error | 0 |

## Declined runs

| fault | wait | n | reason | root fp / class | r0 exit | r1 outcome | r1 exit | surface (ms) | teardown r0 (ms) |
|---|---|---|---|---|---|---|---|---|---|
| F2 | blocking | 1 | class_REM_ACCESS | 10/0x88 REM_ACCESS | 9 | declined | 9 | 4.2 | 872.7 |
| F2 | timeout | 1 | class_REM_ACCESS | 10/0x88 REM_ACCESS | 9 | declined | 9 | 5.7 | 887.0 |
| F4 | blocking | 1 | retry_exc_peer_dead | 12/0x81 RETRY_EXC | 9 | (killed) | 255 | 3616.6 | 746.2 |
| F4 | timeout | 1 | retry_exc_peer_dead | 12/0x81 RETRY_EXC | 9 | (killed) | 255 | 3578.2 | 770.9 |

## Recovery timing (per recovered event; ms, median [min-max])

| fault | wait | n | detect (fault -> device) | fault -> kernel return | kernel return -> commit | prepare | handshake (REQ -> ACK) | commit | replay | kernel return -> recovered | fault -> recovered |
|---|---|---|---|---|---|---|---|---|---|---|---|
| D0 | blocking | 3 (3 rec) | - | - | 23.00 [22.84-23.11] | 1.27 [1.17-1.28] | 18.69 [18.51-18.78] | 3.04 [3.02-3.14] | - | 23.00 [22.84-23.11] | - |
| D0 | timeout | 3 (3 rec) | - | - | 22.91 [22.87-22.94] | 1.27 [1.24-1.31] | 18.51 [18.48-18.56] | 3.10 [3.10-3.10] | - | 22.91 [22.87-22.94] | - |
| F1 | blocking | 2 (2 rec) | 0.58 [0.49-0.67] | 0.80 [0.62-0.97] | 8.32 [8.06-8.58] | 0.62 [0.39-0.85] | 4.66 [4.62-4.70] | 3.03 [2.96-3.09] | 0.26 [0.26-0.27] | 8.58 [8.32-8.85] | 9.38 [9.29-9.47] |
| F1 | timeout | 2 (2 rec) | 0.71 [0.70-0.73] | 0.89 [0.82-0.97] | 8.25 [8.09-8.40] | 0.50 [0.42-0.59] | 4.67 [4.67-4.68] | 3.05 [2.97-3.12] | 0.26 [0.26-0.27] | 8.51 [8.35-8.67] | 9.40 [9.32-9.49] |
| F1 x5 | blocking | 5 (4 rec) | 10.47 [1.41-13.13] | 10.68 [1.67-13.40] | 7.93 [7.71-8.83] | 0.17 [0.17-0.20] | 4.57 [4.40-4.65] | 3.09 [3.02-4.08] | 0.26 [0.26-0.27] | 8.11 [7.97-8.21] | 18.62 [9.69-21.37] |
| F1 x5 | timeout | 5 (4 rec) | 10.24 [1.42-13.29] | 10.52 [1.67-13.56] | 7.88 [7.34-9.01] | 0.22 [0.16-0.24] | 4.54 [4.32-4.66] | 3.07 [2.84-4.24] | 0.26 [0.26-0.26] | 8.10 [7.61-8.23] | 18.58 [9.27-21.61] |
| F3 | blocking | 1 (1 rec) | 3721.22 | 3721.31 | 7.70 | 1.05 | 3.52 | 3.09 | 0.28 | 7.98 | 3729.29 |
| F3 | timeout | 1 (1 rec) | 3717.11 | 3717.23 | 7.81 | 1.10 | 3.54 | 3.14 | 0.28 | 8.09 | 3725.32 |
| F3 x5 | blocking | 5 (4 rec) | 3721.91 [3721.60-3757.09] | 3722.20 [3721.97-3757.32] | 7.63 [7.53-8.68] | 1.06 [1.05-1.11] | 3.46 [3.33-4.52] | 3.07 [3.03-3.12] | 0.28 [0.28-0.28] | 7.86 [7.80-8.15] | 3745.90 [3729.84-3765.47] |
| F3 x5 | timeout | 5 (4 rec) | 3721.76 [3721.51-3786.87] | 3722.13 [3721.88-3787.13] | 7.73 [7.68-8.94] | 1.09 [1.04-1.16] | 3.49 [3.48-4.59] | 3.13 [3.08-3.16] | 0.28 [0.28-0.28] | 7.98 [7.95-8.15] | 3746.02 [3729.84-3795.09] |

## Library step costs (us, median [min-max]; sender side, receiver side)

| fault | wait | n | QPs | to ERR | drain | prepare total | 2RST | resync | INIT/RTR/RTS | commit total | rx prepare | rx commit | CQEs err/ok in window |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| D0 | blocking | 3 | 4 | 1224 [1130-1224] | 13 [13-13] | 1266 [1173-1277] | 1113 [1052-1180] | 56 [53-57] | 1896 [1869-1896] | 3041 [3017-3139] | 1246 [1111-1270] | 3098 [3072-3104] | 0/0 |
| D0 | timeout | 3 | 4 | 1219 [1194-1252] | 14 [14-14] | 1264 [1238-1303] | 1149 [1136-1158] | 59 [57-60] | 1880 [1873-1889] | 3095 [3095-3099] | 1222 [1206-1235] | 2987 [2976-3010] | 0/0 |
| F1 | blocking | 2 | 4 | 130 [118-142] | 14 [13-15] | 618 [384-852] | 1058 [979-1136] | 58 [57-59] | 1897 [1885-1909] | 3024 [2959-3090] | 1255 [1245-1265] | 3030 [2983-3077] | 2/0 |
| F1 | timeout | 2 | 4 | 112 [112-112] | 13 [13-13] | 501 [416-586] | 1056 [1025-1086] | 69 [60-78] | 1908 [1874-1941] | 3046 [2973-3120] | 1287 [1238-1336] | 3057 [3038-3076] | 2/0 |
| F1 x5 | blocking | 5 | 4 | 139 [128-162] | 13 [12-13] | 175 [165-198] | 1124 [1035-1148] | 48 [46-58] | 1867 [1841-1909] | 3089 [3019-4079] | 1239 [1197-1310] | 3038 [2878-3092] | 2/0 |
| F1 x5 | timeout | 5 | 4 | 177 [126-192] | 13 [12-14] | 218 [162-235] | 1120 [959-1149] | 51 [51-57] | 1890 [1821-1897] | 3073 [2839-4242] | 1235 [1199-1296] | 3039 [2946-3122] | 2/0 |
| F3 | blocking | 1 | 4 | 978 | 13 | 1047 | 1144 | 61 | 1870 | 3088 | 183 | 3091 | 2/0 |
| F3 | timeout | 1 | 4 | 1023 | 14 | 1095 | 1164 | 59 | 1907 | 3144 | 195 | 2993 | 2/0 |
| F3 x5 | blocking | 5 | 4 | 996 [985-1038] | 14 [13-14] | 1058 [1053-1108] | 1118 [1048-1141] | 60 [59-62] | 1897 [1877-1948] | 3067 [3030-3114] | 183 [158-204] | 3020 [2837-4161] | 2/0 |
| F3 x5 | timeout | 5 | 4 | 1021 [977-1102] | 13 [13-13] | 1088 [1041-1163] | 1148 [1113-1213] | 59 [58-61] | 1894 [1867-1928] | 3127 [3076-3155] | 166 [160-186] | 3051 [2918-4187] | 2/0 |

## Signal reconciliation

| fault | wait | events | d=1 (replayed put+ADD) | d=0 (ADD had landed; nothing replayed) | replay failed -> new round |
|---|---|---|---|---|---|
| D0 | blocking | 3 | 0 | 3 | 0 |
| D0 | timeout | 3 | 0 | 3 | 0 |
| F1 | blocking | 2 | 2 | 0 | 0 |
| F1 | timeout | 2 | 2 | 0 | 0 |
| F1 x5 | blocking | 5 | 5 | 0 | 1 |
| F1 x5 | timeout | 5 | 5 | 0 | 1 |
| F3 | blocking | 1 | 1 | 0 | 0 |
| F3 | timeout | 1 | 1 | 0 | 0 |
| F3 x5 | blocking | 5 | 5 | 0 | 1 |
| F3 x5 | timeout | 5 | 5 | 0 | 1 |
