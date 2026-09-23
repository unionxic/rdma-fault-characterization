# NCCL GIN fault matrix summary

source: `gin_results.csv` (73 trials)

surface_ms = host time-to-surface after the fault fired (rank0 CLOCK_MONOTONIC); init_silent_iters = rank0 okIters - rank1 okIters per trial.

| backend | fault | wait | kind | n | init_outcome | target_outcome | data | init_silent_iters | host_error | surface_ms med [min-max] | surface_by | fp_where | status/ve | teardown |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gdaki | none | blocking | mx | 5 | ok:5 | ok:5 | ok:5 | 0/0/0/0/0 | none:5 | - | -:5 | none:5 | -/-:5 | clean:5 |
| gdaki | none | timeout | mx | 5 | ok:5 | ok:5 | ok:5 | 0/0/0/0/0 | none:5 | - | -:5 | none:5 | -/-:5 | clean:5 |
| gdaki | F1 | blocking | mx | 3 | ok:3 | hang_killed:3 | n/a:3 | 1/1/1 | remote:3 | 9402 [9401-9403] | r0:3 | api:3 | -/-:3 | clean:3 |
| gdaki | F1 | timeout | mx | 3 | timeout:3 | timeout:3 | missing:3 | 0/0/0 | remote:3 | 9402 [9401-9403] | r0:3 | api:3 | -/-:3 | clean:3 |
| gdaki | F2 | blocking | mx | 3 | ok:3 | hang_killed:3 | n/a:3 | 1/1/1 | remote:3 | 10000 [10000-10000] | r0:3 | api:3 | -/-:3 | clean:3 |
| gdaki | F2 | timeout | mx | 3 | timeout:3 | timeout:3 | missing:3 | 0/0/0 | remote:3 | 10000 [10000-10001] | r0:3 | api:3 | -/-:3 | clean:3 |
| gdaki | F3 | blocking | mx | 3 | ok:3 | hang_killed:3 | n/a:3 | 1/1/1 | remote:3 | 9403 [9402-9403] | r0:3 | api:3 | -/-:3 | clean:3 |
| gdaki | F3 | blocking | ref | 1 | ok:1 | hang_killed:1 | n/a:1 | 1 | remote:1 | 59407 [59407-59407] | r0:1 | api:1 | -/-:1 | clean:1 |
| gdaki | F3 | timeout | mx | 3 | timeout:3 | timeout:3 | missing:3 | 0/0/0 | remote:3 | 9402 [9402-9403] | r0:3 | api:3 | -/-:3 | clean:3 |
| gdaki | F4 | blocking | mx | 3 | timeout:3 | killed:3 | missing:3 | 0/0/0 | remote:3 | 8008 [8007-8041] | r0:3 | api:3 | -/-:3 | clean:3 |
| gdaki | F4 | timeout | mx | 3 | timeout:3 | killed:3 | missing:3 | 0/0/0 | remote:3 | 8019 [8004-8022] | r0:3 | api:3 | -/-:3 | clean:3 |
| proxy | none | blocking | mx | 5 | ok:5 | ok:5 | ok:5 | 0/0/0/0/0 | none:5 | - | -:5 | none:5 | -/-:5 | clean:5 |
| proxy | none | timeout | mx | 5 | ok:5 | ok:5 | ok:5 | 0/0/0/0/0 | none:5 | - | -:5 | none:5 | -/-:5 | clean:5 |
| proxy | F1 | blocking | mx | 3 | hang_killed:3 | hang_killed:3 | n/a:3 | 0/0/0 | remote:3 | 9 [8-11] | r0:3 | log:3 | 5/245:3 | hang:3 |
| proxy | F1 | timeout | mx | 3 | timeout:3 | timeout:3 | missing:3 | 0/0/0 | remote:3 | 7 [6-8] | r0:3 | log:3 | 5/245:3 | clean:3 |
| proxy | F2 | blocking | mx | 3 | hang_killed:3 | hang_killed:3 | n/a:3 | 0/0/0 | remote:3 | 3 [3-3] | r0:3 | log:3 | 10/136:3 | hang:3 |
| proxy | F2 | timeout | mx | 3 | timeout:3 | timeout:3 | missing:3 | 0/0/0 | remote:3 | 3 [3-3] | r0:3 | log:3 | 10/136:3 | clean:3 |
| proxy | F3 | blocking | mx | 3 | hang_killed:3 | hang_killed:3 | n/a:3 | 0/0/0 | remote:3 | 3613 [3539-3696] | r0:3 | log:3 | 12/129:3 | hang:3 |
| proxy | F3 | blocking | ref | 2 | hang_killed:2 | hang_killed:2 | n/a:2 | 0/0 | remote:2 | 58074 [57773-58376] | est:2 | log:2 | 12/129:2 | hang:2 |
| proxy | F3 | timeout | mx | 3 | timeout:3 | timeout:3 | missing:3 | 0/0/0 | remote:3 | 3616 [3578-3654] | r0:3 | log:3 | 12/129:3 | clean:3 |
| proxy | F3 | timeout | ref | 2 | timeout:2 | timeout:2 | missing:2 | 0/0 | remote:2 | 57170 [57142-57199] | est:2 | log:2 | 12/129:2 | clean:2 |
| proxy | F4 | blocking | mx | 3 | error:3 | killed:3 | missing:3 | 0/0/0 | remote:3 | 61 [60-62] | r0:3 | log:3 | 10/136:3 | clean:3 |
| proxy | F4 | timeout | mx | 3 | error:3 | killed:3 | missing:3 | 0/0/0 | remote:3 | 60 [60-61] | r0:3 | log:3 | 10/136:3 | clean:3 |
