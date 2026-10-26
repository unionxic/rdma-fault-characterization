# notes_counterexample.md — 반례 셀 둘: 조용한 긴 계산, 멈춘 rank를 기다리는 정상 rank (2026-10-27)

EXPERIMENT.md 19절 차례 4의 남은 반례 둘을 사전 등록 전에 넣은 기록이다. 결정은 12절 2026-10-27 "반례 셀 둘" 행, 시험 쪽 세부는 [test/notes_test.md](test/notes_test.md) 끝 절.
근거 문서는 저장소 밖 scratch `next/counterexample/DESIGN.md`(설계, 100줄)와 `next/counterexample/review1.md`(Codex 검토, 읽기만)이고 링크하지 않는다.

## 설계 요약

- **셀 A `gc4_quiet12000`.** rank 3의 모든 CTA가 걸음 155의 첫머리에서 어떤 post나 기다림보다 먼저 12 000 ms 돈다(`GC_QUIET_IT=155@12000`). 앞 걸음의 flush가 끝나 모든 문맥이
  조용하고 호스트 박동은 오른다. 다른 rank는 걸음 155에서 남은 일 없이 기다린다. 예측: 어느 rank의 의심도, 판정, 거절, hold, 예비 프로세스 사용도 0, 데이터 같음 `[추론]`.
- **셀 B `gc4_gpuhang12000_waitpend_fence`.** GPU hang 셀(rank 3)에 rank 1의 `GC_WAITPEND=1`: rank 1의 보내는 CTA가 put 뒤 flush 전에 상대 put이 닿기를 기다린다. rank 3이 서면 rank 1의
  rank 3 쪽 CTA만 post했으나 poll하지 않은 put을 둔 채 기다리므로 그 문맥 줄이 남은 일을 둔 채 그대로다. 지금 규칙(문맥 줄의 남은 일을 목적지와 상관없이 합침)은 rank 1도 약 10 s 뒤
  판정할 수 있다 `[추론: 설계 3절]`.
- **설계가 권한 규칙(대안 다): 상대마다 나눈 정체.** 관측 rank의 원소(문맥, 목적지)마다 시계를 두고, 목적지가 후보(먼저 선 rank)이거나 면제(hold, 거절, 판정됨, 읽지 못함)면 그 원소를 판정에서
  빼고 "기다림"으로 보고한다. 판정 표 21행과 1 170점 격자는 그대로, 호스트만 약 170줄. 다른 대안: (가) 옛 규칙을 두고 연쇄 판정을 한계로, (나) 모든 생존 rank의 목적지 보기를 페이지로 합의.

## Codex 검토의 지적 일곱 (요지)

1. [high] 분할 막이는 유효한 보기만 본다: 모든 생존 rank의 동의가 아니고, 반쪽 hold를 200 ms 경쟁으로 한정할 수 없다.
2. [high] 후보가 들고 나기를 되풀이하거나 영구 면제되면 실제 멈춤이 무기한 숨는다(고리 밖에서도).
3. [medium] first-match 표는 유지되지만 원시 시계와 유예 시계, 남은 일의 저장, 후보와 면제의 계산 차례, 화신 변경 때 지울 상태가 덜 정해졌다.
4. [medium] 셀 B의 옛 규칙 거짓 교체는 rank 3의 판정, hold, 복원과 경쟁해 조건부다. 대조는 같은 수정 driver와 옛 라이브러리여야 한다.
5. [medium] 새 칸 기다림은 abort를 보지 않으면 fallback 때 풀리지 않는다. 표지(첫 낱말)의 0 아님과 반복 load를 고정해야 한다.
6. [medium] 예측식과 채점: 일반 꼴은 첫 셀만 채점(`keys[:1]`), `suspect_n`은 대상만 셈, hold와 spare 열 없음, 주입 확인이 새 스위치를 모름, `WAITER_RANK` 경로, 조용한 주기의 정의.
7. [medium] 단위 장면에 관측자 rank 1, 무효 보기의 반대자, 비순환 반복, 3 ↔ 1 고리, 같은 문맥의 다른 QP, READ 누락과 화신 변경, 어긋난 READ 위상이 빠졌다.

검토 결론: 대안 다를 지금 사전 등록하는 것은 권하지 않음, **권고 (a)**(옛 규칙을 두고 A와 수정 driver의 B를 넣고, 정상 대기자 보호 주장을 flush 조건으로 좁힘).

## 결정 (조율 세션, 2026-10-27)

권고 (a). 두 셀을 **지금 판정 규칙 아래** 넣는다. 상대마다 나눈 규칙은 후속(EXPERIMENT 19절)이고 위 일곱 지적이 그 요구 사항이다. 라이브러리(`impl/gc_layer*`)는 바꾸지 않는다.
지적 5와 6은 이번 시험 쪽에서 닫았다: 칸 기다림의 abort 검사와 released 보고, 표지 0 아님 확인; `per cell:` 판정과 일반 꼴 검사, `suspect_any_n`, `hold_any_n`, `spare_used`, `quiet_periods`,
`waiter_*`, 두 스위치의 주입 확인, meta `waiter_rank`. 주장은 "기다리기 전에 flush하는 workload"로 좁혔다(EXPERIMENT 1, 3, 9.3, 18절).

## 바뀐 파일

| 파일 | 무엇 |
|---|---|
| `test/driver/gin_mi.cu` | `GC_QUIET_IT`, `GC_WAITPEND`(머리 주석). 소스 md5 `a28df3feb4172230b9304099f2c83625`(HEAD aee023e8의 `6cb4ff28` 대비 바뀐 줄 251). `build_driver_gc.sh mi`로 빌드됨(경고 0, gin_mi `5bd02b27`, 라이브러리 pf2 `39024bef`), 실행 안 함 |
| `test/driver/build_driver_gc.sh` | 머리 주석 |
| `test/cells_gc.json` | 셀 둘, 7절 30행, hold C10에 둘, pilot hold P5(셀마다 n 2) |
| `test/predictions_gc.csv` | `quiet_compute_no_judge`, `waiter_old_rule`, `gpuhang_fence_restore`의 `per cell:` |
| `test/rows_gc.py`, `test/score_gc.py` | 새 열, 주입 확인, `LIB_COLS`, `REQUIRED_COLS` |
| `test/run_gc.sh` | meta `waiter_rank` |
| `test/check_cells_gc.py` | `plain_part_fails`(키가 둘 이상인 행의 일반 꼴) |
| `test/test_rows_gc.py`, `test/notes_test.md` | 자체 시험 B7, 기록 |
| `../EXPERIMENT.md` | 1, 3, 7, 9.3, 9.9, 11.1, 12, 18, 19절, 현재 상태 |

검증 `[측정: 로컬 실행, 2026-10-27]`: `test_rows_gc.py` 221 검사 실패 0, `check_cells_gc.py` drift 0(7절 30행, 셀 28, 예측 33), `tools/check_md.py`, `git diff --check`, `bash -n run_gc.sh`.
하드웨어 검증은 pilot 4(hold P5) 대기다.
