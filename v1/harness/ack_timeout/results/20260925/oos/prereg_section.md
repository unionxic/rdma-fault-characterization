### D1. Predictions, written before the measurement

Written 2026-09-25 14:11 KST, before any of the runs below: `predict.py` (md5 `9ce7ab8f...`) encodes
the section-A model unchanged (schedule points, `max(T,16)` clamp, `min(s_next, I)` rule, as
fitted on `results/20260925/A` trials >= 2) and wrote `results/20260925/oos/predictions.csv`
(md5 `dbc6ed2a...`, mtime 14:11:19). None of these (T, R) cells was measured before, except
T=16 R=7, which is repeated as a replicate. Acceptance criterion, fixed in advance: every
non-first trial within 1.5 ms of the predicted detection time.

| T | R | I (ms) | t_A end of adaptive phase (ms) | first regular timeout (ms) | regular timeouts | adaptive retransmissions | predicted detect (ms) |
|---|---|---|---|---|---|---|---|
| 10 | 7 | 536.87 | 440.4 | 977.2 | 6 | 4-7 | 3661.55 |
| 12 | 7 | 536.87 | 440.4 | 977.2 | 6 | 4-7 | 3661.55 |
| 15 | 7 | 536.87 | 440.4 | 977.2 | 6 | 4-7 | 3661.55 |
| 16 | 7 | 536.87 | 440.4 | 977.2 | 6 | 4-7 | 3661.55 |
| 15 | 1 | 536.87 | 440.4 | - | 0 | 4-7 | 440.40 |
| 15 | 3 | 536.87 | 440.4 | 977.2 | 2 | 4-7 | 1514.07 |
| 15 | 5 | 536.87 | 440.4 | 977.2 | 4 | 4-7 | 2587.81 |
| 17 | 1 | 1073.74 | 977.2 | - | 0 | 5-8 | 977.20 |
| 17 | 2 | 1073.74 | 977.2 | 1782.5 | 1 | 5-8 | 1782.50 |
| 17 | 3 | 1073.74 | 977.2 | 1782.5 | 2 | 5-8 | 2856.24 |
| 17 | 5 | 1073.74 | 977.2 | 1782.5 | 4 | 5-8 | 5003.73 |

What each cell tests: T=10/12/15 the `max(T,16)` clamp below T=14 and between 14 and 16 (without
the clamp, T=10 would give a regular interval of 8.4 ms, not 536.9 ms); T=17 R=2 the
`min(s_next, I)` rule directly (first regular timeout at 1782.5 = 977.2 + 805.3, against 2050.9 =
977.2 + I without it); R=1 that the WQE fails at the end of the adaptive phase.

For fresh processes (D2) the model makes no timing prediction for the adaptive phase, because the
13 first trials of section A did not follow its schedule. Hypothesis written in advance: the
regular part (spacing I, R-1 regular timeouts, last one = CQE) holds in a fresh process too;
only the adaptive phase differs.

(results below)
