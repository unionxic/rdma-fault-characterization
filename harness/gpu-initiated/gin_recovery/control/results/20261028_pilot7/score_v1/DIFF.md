# pilot 7 다시 채점: score_v1 대 score_v0 (2026-11-18, 채점 아님)

채점기 고침 둘(EXPERIMENT.md 12절 2026-11-18 "채점기 고침 둘(검수 뒤)" 행) 뒤 pilot 7 원자료를 다시 처리했다. 방법은 pilot 8과 같다([../../20261028_pilot8/score_v1/DIFF.md](../../20261028_pilot8/score_v1/DIFF.md) "어떻게"). [a1/](../a1/) 사본에 [score_v0/score_pilot.py](../score_v0/score_pilot.py)를 썼다.

표시: `[측정]` 원자료나 출력에서 다시 셈, `[추론]` 해석.

## 바뀐 것 `[측정]`

| 파일 | 다른 곳 |
|---|---|
| [SCORE.md](SCORE.md) | 예측 표 sha256 줄 하나, `fdhold_uverbs_refuse`의 판정식 글 셋(이 pilot에는 그 셀이 없어 0/0) |
| [trials_scored.csv](trials_scored.csv) | 열 `n_judge_taken` 하나가 더해짐(열 361 → 362). 다른 열의 값은 시행 아홉 모두 같음 |

- 판정은 모두 그대로다.
- `n_judge_taken`은 시행 아홉 모두 0이다.
- pilot 7 문제 1(n1에서 r2가 r0의 결정을 먼저 적용함)의 결정 대상은 rank 1(기다리는 rank)이다. 시행의 대상 열 `subject`는 3이라 `n_judge`와 `n_judge_taken`에 들지 않는다. 그 경우는 rank 1을 세는 `waiter_judge_n`(1)에 보인다 `[측정: ../PILOT.md 문제 1, trials_scored.csv]`.
