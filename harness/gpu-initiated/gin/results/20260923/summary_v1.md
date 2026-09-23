# NCCL GIN fault matrix summary -- v1 (SUPERSEDED by summary.md after the lead QA re-run: host_error_ms here is relative to program start, not time-to-surface; GDAKI timeout "host never learns" was a driver artifact; old refs had a 5 s device cap)

source: `gin_results.csv`  (67 trials)

| backend | fault | wait | n | init_outcome | target_outcome | data_check | silent | host_error | surface_ms(med) | fp_where | status/ve | teardown |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gdaki | none | blocking | 5 | ok:5 | ok:5 | ok:5 | 0 | none:5 | - | none:5 | -/-:5 | clean:5 |
| gdaki | none | timeout | 5 | ok:5 | ok:5 | ok:5 | 0 | none:5 | - | none:5 | -/-:5 | clean:5 |
| gdaki | F1 | blocking | 3 | ok:3 | hang_killed:3 | n/a:3 | 0 | remote:3 | 10701 | api:3 | -/-:3 | clean:3 |
| gdaki | F1 | timeout | 3 | timeout:3 | timeout:3 | missing:3 | 0 | none:3 | - | none:3 | -/-:3 | clean:3 |
| gdaki | F2 | blocking | 3 | ok:3 | hang_killed:3 | n/a:3 | 0 | remote:3 | 10714 | api:3 | -/-:3 | clean:3 |
| gdaki | F2 | timeout | 2 | timeout:2 | timeout:2 | missing:2 | 0 | none:2 | - | none:2 | -/-:2 | clean:2 |
| gdaki | F3 | blocking | 3 | ok:3 | hang_killed:3 | n/a:3 | 0 | remote:3 | 10694 | api:3 | -/-:3 | clean:3 |
| gdaki | F3 | timeout | 4 | timeout:4 | timeout:4 | missing:4 | 0 | none:4 | - | none:4 | -/-:4 | clean:4 |
| gdaki | F4 | blocking | 3 | error:3 | killed:3 | missing:3 | 0 | none:3 | - | none:3 | -/-:3 | clean:3 |
| gdaki | F4 | timeout | 3 | error:3 | killed:3 | missing:3 | 0 | none:3 | - | none:3 | -/-:3 | clean:3 |
| proxy | none | blocking | 5 | ok:5 | ok:5 | ok:5 | 0 | none:5 | - | none:5 | -/-:5 | clean:5 |
| proxy | none | timeout | 5 | ok:5 | ok:5 | ok:5 | 0 | none:5 | - | none:5 | -/-:5 | clean:5 |
| proxy | F1 | blocking | 3 | hang_killed:3 | hang_killed:3 | n/a:3 | 0 | remote:3 | 1274 | log:3 | 5/245:3 | hang:3 |
| proxy | F1 | timeout | 3 | timeout:3 | timeout:3 | missing:3 | 0 | remote:3 | 1312 | log:3 | 5/245:3 | clean:3 |
| proxy | F2 | blocking | 3 | hang_killed:3 | hang_killed:3 | n/a:3 | 0 | remote:3 | 716 | log:3 | 10/136:3 | hang:3 |
| proxy | F2 | timeout | 3 | timeout:3 | timeout:3 | missing:3 | 0 | remote:3 | 728 | log:3 | 10/136:3 | clean:3 |
| proxy | F3 | blocking | 3 | hang_killed:3 | hang_killed:3 | n/a:3 | 0 | remote:3 | 4939 | log:3 | 12/129:3 | hang:3 |
| proxy | F3 | timeout | 4 | timeout:4 | timeout:4 | missing:4 | 0 | none:1,remote:3 | 4976 | log:3,none:1 | -/-:1,12/129:3 | clean:4 |
| proxy | F4 | blocking | 3 | error:3 | killed:3 | missing:3 | 0 | remote:3 | 2761 | log:3 | 10/136:3 | clean:3 |
| proxy | F4 | timeout | 1 | error:1 | killed:1 | missing:1 | 0 | remote:1 | 2750 | log:1 | 10/136:1 | clean:1 |
