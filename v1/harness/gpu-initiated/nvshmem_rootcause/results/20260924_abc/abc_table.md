<!-- 53 trials -> results/20260924_abc/abc_trials.csv -->
| config | fault | wait | n | handler (log) | app sees (wait_rc / quiet) | error CQE in slot at end of wait (op/syn/ven@wqe) | full-scan errs | detection ms (median, range) | QP (watch, end) | DBR word1 (final) | target iters ok | teardown (pe0 rc) |
|---|---|---|--:|---|---|---|---|---|---|---|---|---|
| A | none | timeout | 3 | GPU | ok | 0x0 (last ok) | 0 | - | RTS hw 31 sw 31 | na | 8 | 0 |
| A | F1 | timeout | 3 | GPU | error | 0xd/0x05/0xf5@27 | 1 | 2.1 (2.0-2.3) | ERR hw 32 sw 32 | 32 | 6 | 7 |
| A | F2b | timeout | 3 | GPU | error | 0xd/0x13/0x88@23 | 1 | 10.4 (10.3-10.7) | ERR hw 28 sw 28 | 28 | 4 | 7 |
| A | F3 | timeout | 3 | GPU | error | 0xd/0x15/0x81@27 | 1 | 3755.0 (3535.3-3758.2) | ERR hw 32 sw 32 | 32 | 6 | 7 |
| A | F4 | timeout | 3 | GPU | error | 0xd/0x15/0x81@23 | 1 | 3730.9 (3577.5-3785.1) | ERR hw 28 sw 28 | 28 | 3,4 | 7 |
| A | F2b | blocking | 2 | GPU | quiet returned 8/8 | 0xd/0x05/0xf9@30 | 1 | 10.3 (9.8-10.8) | ERR hw 34 sw 34 | 34 | 4 | 7 |
| A | F3 | blocking | 2 | GPU | quiet returned 8/8 | 0xd/0x05/0xf9@30 | 1 | 3744.7 (3731.1-3758.3) | ERR hw 34 sw 34 | 34 | 6 | 7 |
| B | none | timeout | 3 | CPU with host memory backend | ok | 0x0 (last ok) | 0 | - | RTS hw 31 sw 31 | na | 8 | 0 |
| B | F1 | timeout | 3 | CPU with host memory backend | timeout | 0x0 (last ok) | 0 | - | ERR hw 27 sw 0 | 0 | 6 | 7 |
| B | F2b | timeout | 3 | CPU with host memory backend | timeout | 0x0 (last ok) | 0 | - | ERR hw 23 sw 0 | 0 | 4 | 7 |
| B | F3 | timeout | 3 | CPU with host memory backend | timeout | 0x0 (last ok) | 0 | - | ERR hw 29 sw 0 | 0 | 6 | 7 |
| B | F4 | timeout | 3 | CPU with host memory backend | timeout | 0x0 (last ok) | 0 | - | ERR hw 23 sw 0,ERR hw 25 sw 0 | 0 | 3 | 7 |
| C | none | timeout | 3 | CPU with host memory backend | ok | 0x0 (last ok) | 0 | - | RTS hw 31 sw 31 | na | 8 | 0 |
| C | F1 | timeout | 3 | CPU with host memory backend | error | 0xd/0x05/0xf5@27 | 1 | 1.8 (1.8-1.8) | ERR hw 32 sw 32 | 32 | 6 | 7 |
| C | F2b | timeout | 3 | CPU with host memory backend | error | 0xd/0x13/0x88@23 | 1 | 9.6 (9.6-10.3) | ERR hw 28 sw 28 | 28 | 4 | 7 |
| C | F3 | timeout | 3 | CPU with host memory backend | error | 0xd/0x15/0x81@27 | 1 | 3622.0 (3581.0-3791.9) | ERR hw 32 sw 32 | 32 | 6 | 7 |
| C | F4 | timeout | 3 | CPU with host memory backend | error | 0xd/0x15/0x81@21,0xd/0x15/0x81@23 | 1 | 3618.3 (3507.5-3696.1) | ERR hw 26 sw 26,ERR hw 28 sw 28 | 26,28 | 3,4 | 7 |
| C | F2b | blocking | 2 | CPU with host memory backend | quiet returned 8/8 | 0xd/0x05/0xf9@30 | 1 | 10.2 (9.9-10.4) | ERR hw 34 sw 34 | 34 | 4 | 7 |
| C | F3 | blocking | 2 | CPU with host memory backend | quiet returned 8/8 | 0xd/0x05/0xf9@30 | 1 | 3584.2 (3581.8-3586.6) | ERR hw 34 sw 34 | 34 | 6 | 7 |
