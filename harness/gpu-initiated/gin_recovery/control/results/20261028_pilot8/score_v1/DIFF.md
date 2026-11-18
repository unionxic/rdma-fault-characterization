# pilot 8 다시 채점: score_v1 대 score_v0 (2026-11-18, 채점 아님)

채점기 고침 둘(EXPERIMENT.md 12절 2026-11-18 "채점기 고침 둘(검수 뒤)" 행) 뒤 pilot 8 원자료를 다시 처리했다. pilot은 본 실험에 들지 않고, 이것은 시행마다의 규칙 확인이지 채점이 아니다.

표시: `[측정]` 원자료나 출력에서 다시 셈, `[추론]` 해석.

## 어떻게

- [a1/](../a1/)를 세션 스크래치에 복사하고 그 사본에 [score_v0/score_pilot.py](../score_v0/score_pilot.py)(바꾸지 않음: pilot 표시 끔, 계획 n을 있는 시행 수로)를 돌렸다. score_v0과 같은 방법이다.
- 나온 `SCORE.md`는 그대로, `trials_scored.csv`는 `stem` 열의 스크래치 경로 앞부분만 지워 score_v0과 같은 `raw/...` 꼴로 두었다.
- 채점기: `rows_gc.py`(열 `n_judge_taken`), `score_gc.py`(짧은 키의 안전 예측 실패), 예측 표 sha256 `de6bf8ec70ca7cb16818be540fb530c12be576f73d186c436874703aa72ce4a8`(score_v0은 `3f3cbc13…`).

## 바뀐 것 `[측정]`

| 파일 | 다른 곳 |
|---|---|
| [SCORE.md](SCORE.md) | 예측 표 sha256 줄 하나, `fdhold_uverbs_refuse`의 판정식 글 셋(판정식 줄, count 줄, 셈 표의 행). 첫 항이 `n_judge == n_surv`에서 `n_judge + n_judge_taken == n_surv`로 |
| [trials_scored.csv](trials_scored.csv) | 열 `n_judge_taken` 하나가 `n_judge_linkdown` 뒤에 더해짐(열 361 → 362). 다른 열의 값은 시행 셋 모두 같음 |

- 판정은 모두 그대로다. `fdhold_uverbs_refuse`는 1/1, 자료 부족(n<k)(n 1, k 4)이다.
- `n_judge_taken`: `gc4_fdhold_uverbs_kill3` 0, `gc4_kill3_ow_spareabsent` 0, `gc4_stop12000_none` **1**.
- 펜스 끈 멈춤 셀의 그 1은 r2다. r2에는 rank 3의 판정 줄이 없고 decline 줄 하나만 있다([a1/raw/gc4_stop12000_none_gc_n1_r2.log](../a1/raw/gc4_stop12000_none_gc_n1_r2.log) 402행): `GIN/TS: declined rank=2 peer=3 reason="ABORT_DECIDED(rank 3, incarnation 0, no. 1, cause STALL_HELPER) of rank 0 (incarnation 0): a confirmed abort decision"`.
- 그 셀의 `n_judge` 2, `n_surv` 3은 그대로다. 그래서 `n_judge + n_judge_taken == n_surv`는 참이고, 옛 `n_judge == n_surv`는 거짓이다.
  다만 이 셀은 `fdhold_uverbs_refuse`의 셀이 아니다. 이 셀의 `surv_released`는 4(멈췄다 풀린 rank 3 포함)라 그 판정식의 `surv_released == n_surv`는 여기서 거짓이다 `[측정]`.
- 짧은 키 고침(`score_gc.py`)은 이 출력에 닿지 않았다. 계획 n을 있는 시행 수로 두어 짧은 키가 없다 `[추론]`.
