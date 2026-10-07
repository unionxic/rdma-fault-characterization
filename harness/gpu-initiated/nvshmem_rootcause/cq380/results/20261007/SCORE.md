# cq380 score

Scored by `score.py` against `predictions.csv` (tag prereg/cq380-v1). Per-trial values: `trials_scored.csv`.

`verdict` uses the cuda-gdb read for trials whose own scan failed (DEVIATIONS 1, 3). `strict` reads section 8 literally and counts those trials as not observable.

| cell | n | hits | verdict | strict | misses | not observable |
|---|--:|--:|---|---|---|---|
| C1 CPU 프록시 공식본, kill | 5 | 5 | **holds** | not observable (n=0) |  |  |
| C2 GPU 처리 공식본, kill | 5 | 5 | **holds** | holds (n=5) |  |  |
| C3 CPU 프록시 수정본, kill | 5 | 5 | **holds** | holds (n=5) |  |  |
| C4 CPU 프록시 공식본, 장애 없음 | 5 | 5 | **holds** | holds (n=5) |  |  |
| C4 GPU 처리 공식본, 장애 없음 | 5 | 5 | **holds** | holds (n=5) |  |  |
