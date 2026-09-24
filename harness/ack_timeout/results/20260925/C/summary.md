| stack | floor | IB timeout T | N | class (fingerprint) | failing op posted -> error (ms) | fault -> device detection (ms) | fault -> host-visible fingerprint (ms) | fault -> API error (ms) | teardown / leftover |
|---|---|---|---|---|---|---|---|---|---|
| GIN GDAKI + Q4 | off | 8 | 10 | RETRY_EXC 12/0x81 (10/10) | 10.2 [10.2-10.3] | 24.5 [14.1-25.2] | 24.6 [14.2-25.3] | 24.7 [14.3-25.5] | clean / 0 |
| GIN GDAKI + Q4 | off | 10 | 10 | RETRY_EXC 12/0x81 (10/10) | 37.3 [36.7-38.4] | 51.8 [50.5-52.8] | 51.9 [50.7-52.9] | 52.1 [50.8-53.0] | clean / 0 |
| GIN GDAKI + Q4 | off | 14 | 10 | RETRY_EXC 12/0x81 (10/10) | 584.3 [574.2-598.0] | 599.2 [587.8-612.6] | 599.3 [587.9-612.6] | 599.5 [588.0-612.8] | clean / 0 |
| GIN GDAKI + Q4 | on | 8 | 2 | RETRY_EXC 12/0x81 (2/2) | 3596.1 [3576.3-3615.9] | 3610.0 [3590.6-3629.4] | 3610.1 [3590.7-3629.5] | 3610.3 [3590.9-3629.7] | clean / 0 |
| GIN GDAKI + Q4 | on | 14 | 1 | RETRY_EXC 12/0x81 (1/1) | 3616.0 [3616.0-3616.0] | 3630.5 [3630.5-3630.5] | 3630.5 [3630.5-3630.5] | 3630.7 [3630.7-3630.7] | clean / 0 |
| NVSHMEM IBGDA + FT | off | 8 | 10 | RETRY_EXC 12/0x81 (10/10) | 9.5 [9.3-10.1] | 13.2 [12.8-18.7] | 13.3 [12.8-18.8] | - | returned/returned / 0/0 |
| NVSHMEM IBGDA + FT | off | 10 | 10 | RETRY_EXC 12/0x81 (10/10) | 36.8 [36.0-37.6] | 40.4 [39.4-41.6] | 40.4 [39.4-41.6] | - | returned/returned / 0/0 |
| NVSHMEM IBGDA + FT | off | 14 | 10 | RETRY_EXC 12/0x81 (10/10) | 581.4 [571.4-603.3] | 585.0 [575.0-606.9] | 585.1 [575.1-606.9] | - | returned/returned / 0/0 |
| NVSHMEM IBGDA + FT | on | 8 | 2 | RETRY_EXC 12/0x81 (2/2) | 3536.3 [3527.5-3545.1] | 3539.8 [3531.0-3548.7] | 3539.9 [3531.0-3548.7] | - | returned/returned / 0/0 |
| NVSHMEM IBGDA + FT | on | 14 | 1 | RETRY_EXC 12/0x81 (1/1) | 3558.3 [3558.3-3558.3] | 3567.0 [3567.0-3567.0] | 3567.1 [3567.1-3567.1] | - | returned/returned / 0/0 |
