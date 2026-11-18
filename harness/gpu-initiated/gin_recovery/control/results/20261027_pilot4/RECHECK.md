# pilot 4 자료로 앞선 Codex 지적 다시 보기 (2026-10-27)

대상은 채점기와 판정에 대한 앞선 Codex 지적 셋이다: 2026-10-23 감독자 관점 리뷰의 [high] 셋 가운데 채점기 둘(EXPERIMENT.md 12절 2026-10-23 행, 8절 "제외한 시행의 분모 공개", "시행 하나의 자료 부족")과,
2026-10-27 반례 셀 검토(`impl/notes_counterexample.md` "Codex 검토의 지적 일곱")의 정상 rank 오판이다. 근거는 이 폴더의 시행 표(`a1/trials.csv`, `a2/trials.csv`)와
`score_v0/`(HEAD 1f3e8ebf의 채점기를 스크래치 사본에서 pilot 표시를 끄고 돌린 출력)이다. 채점기, 라이브러리, 셀과 예측 파일은 고치지 않았다.

표시: `[측정]` 원자료나 채점기 출력에서 다시 셈, `[소스]` 코드를 읽음, `[추론]` 해석, `[미확인]` 확인 안 함.

## 1. 정상 rank의 오판 — 여전히 맞다, 예상보다 나쁨

- **조용한 긴 계산 쪽(경계 (1))은 오판 없음.** `gc4_quiet12000_gc_n1`, `_n2`: 어느 rank에 대한 의심, 판정, 거절, hold도 0, 예비 프로세스 안 쓰임, `quiet_periods` 114, 115 `[측정]`. 남은 일이 없는 12 s 계산은 지금 규칙이 판정하지 않는다(n 2).
- **기다리는 정상 rank 쪽(경계 (2))은 오판함.** `gc4_gpuhang12000_waitpend_fence_gc_n1`, `_n2`: rank 1을 관측자 셋 모두(rank 0, 2, 그리고 멈춘 rank 3)가 STALL로 판정했다(`waiter_judge_n` 3, 3).
  hang 줄 뒤 10 041.7–10 044.6 ms, 10 067.4–10 068.5 ms, 원인 `STALL:3`, ctx 3(rank 3으로 가는 문맥) `[측정]`.
- **결과가 지적의 예상(rank 3의 복원과 경쟁하는 거짓 교체)보다 나쁘다.** rank 1이 rank 0, 2에서 rank 3보다 2.9–4.0 ms 먼저 판정돼 degraded raise가 잡혔고, rank 3은 "declined without a hold"로 거절됐다(n2에서는
  rank 1의 hold 하나가 0.8 ms 만에 포기). 펜스 0, 복원 0, 생존 셋 fallback, rank 3은 GPU에서 driver watchdog까지 삶(2/2) `[측정: PILOT.md 셀 B]`. rank 1은 펜스되지 않았다(`waiter_fenced` 0).
- **driver만의 영향은 없음.** 같은 바이너리의 대조 `gc4_gpuhang12000_fence_gc_n1`은 rank 3만 의심, 판정, 펜스, 복원했다(`suspect_any_n` = `suspect_n` 3, 판정 10 032.7–10 035.9 ms) `[측정]`.
- 남은 것: 판정 규칙의 상대마다 나눔(후속, 지적 일곱이 요구 사항). 그 전에는 셀 B의 주장이 "복원"이 아니라 "fallback으로 끝남"이다. 라이브러리 일이라 보고만 한다.

## 2. 필수 로그가 빠질 때 분모가 줄어듦 — 표시는 됨, `>= N_SCORED` 꼴의 분모는 여전히 줄어듦

- **자료 부족 표시는 된다.** 셀 B 두 시행은 rank 3이 watchdog으로 끝나 제어 요약이 없다(`ctrlsum_missing=r3`, `tcp_ctrl_bytes` 빈칸). `no_tcp_control`의 `build:gc` 묶음에서 두 시행이 자료 부족 시행으로
  SCORE.md에 열과 함께 적혔다: "`gc4_gpuhang12000_waitpend_fence_gc_n1` (tcp_ctrl_bytes; ctrlsum_missing=r3); `…_n2` (같음)" `[측정: score_v0/SCORE.md 485행]`. 통과로도 실패로도 세지 않았다.
- **수를 세는 문턱 k의 행은 계획 n을 지킨다.** `waiter_old_rule`(`>= 4`)은 시행 조건 2/2인데도 "자료 부족(n<k)"이다 `[측정: score_v0/score_out.txt]`. 자료 부족 시행이 생겨도 k보다 적으면 판정하지 않는 길이 서 있다 `[소스: score_gc.py score() below_k]`.
- **`>= N_SCORED` 꼴은 분모가 자료 있는 시행 수로 줄어든다(여전히 맞음).** 같은 `build:gc` 부분을 이 사본에서 따로 대 보면 채점 5, 자료 부족 2, 자료 있는 3, k 3, 그 부분 참이다
  `[측정: score_v0/gapdemo.py]`. `with_data_n`이 `N_SCORED`를 자료 있는 수로 바꾸고 k도 그 수라 `below_k`가 걸리지 않는다 `[소스: score_gc.py with_data_n, score()]`. 8절이 "`>= N_SCORED` 꼴은 자료 있는 시행 전부(1 이상)"라
  정해 두었으므로 채점기 결함이 아니라 규칙의 결과다. 이번 사본에서는 다른 키(`gc4_none_ow`, `gc4_none_probe`)가 비어 행이 "자료 부족"이라 드러나지 않았다.
  본 실행에서는 셀 B 다섯이 모두 이렇게 되면 `no_tcp_control`의 `build:gc`(safety)가 나머지 시행만으로 "맞음"이 될 수 있다 `[추론]`.
- **분모 공개는 된다.** 출력 줄에 계획 5, 실행 5, 채점 5, 자료 부족 2, 조건부 3/3, 전체 3/5가 함께 나온다 `[측정: score_out.txt "build:gc planned=5 run=5 … cond=3/3 whole=3/5 data_gap=2"]`.
- **최소 고침(결정 필요, 적용 안 함):** `>= N_SCORED`의 k를 그 키의 계획 n(준비 실패를 뺀 `EFF`)으로 두어 자료 있는 시행이 계획보다 적으면 "자료 부족(n<k)"으로 하거나, 자료 부족 시행 수의 상한을 사전 등록한다.
  8절 문장 하나와 `score_gc.with_data_n`의 몇 줄이다. 또 셀 B처럼 대상이 펜스되지 않고 watchdog으로 끝난 시행에서 대상의 제어 요약을 필수로 볼지(대상 제외 규칙을 펜스된 대상과 같게 할지) 정해야 한다.

## 3. 복원 실패의 제외 대 셈 — 고쳐졌음, 셀 B의 실패한 복원은 실패로 셈

- 셀 B 두 시행은 상태 `scored`다(제외 0, 준비 실패 0) `[측정: trials.csv status]`. `restore_not_live` 제외는 `KILL_RANK`가 있는 셀에만 걸려 이 셀에는 해당이 없고 `[소스: score_gc.py status_gc]`, Resume 거절도 링 준비 실패도 없었다.
- `gpuhang_fence_restore`의 셀 B 부분이 0/2로 셌다(조건부 0/2, 전체 0/2) `[측정: score_out.txt "gc4_gpuhang12000_waitpend_fence@gc planned=2 run=2 excluded=0 prep_failure=0 scored=2 cond=0/2 whole=0/2"]`.
  복원되지 않은 시행이 빠지고 뒤 시행으로 채워지는 길은 이 자료에서 보이지 않는다.
- 남은 것 둘.
  - **(가) 실행기의 STOP이 실패를 지울 뻔했다.** a1에서 `hold_gc.sh`가 멈춘 대상의 watchdog을 NIC 오류로 읽어 hold를 멈췄다. 본 실행이었다면 셀 B의 나머지 시행이 돌지 않아 그 키가 "자료 부족"이 됐다 `[추론]`.
    고침(이번에 함, 실행기): GPU hang 대상의 자기 watchdog(오류 키 없음)은 `hang_watchdog.txt`에 적기만 한다(PILOT.md "실행기 고침").
  - **(나) perf 행 안의 안전성 항이 fallback을 안전성 어긋남으로 센다.** 셀 B에서 `fence_order_ok`(빈칸: 활성화가 없었음), `ow_data_equal` 0(끝까지 돌지 않음), `revived_done` 0, `wait_held` 0, `win_verified` 빈칸/0이
    2/2 거짓이라 본 실행이면 `gpuhang_fence_restore`가 "재검토(안전성 항 어긋남)"이다 `[측정: score_v0/SCORE.md 275–280행]`. 데이터가 틀리거나 FENCED 전 활성화가 있었던 것이 아니라 복원이 없었던 것이다.
    최소 고침(결정 필요): 안전성 항을 그 항이 지키는 동작이 있었던 시행에서만 보기(활성화가 없으면 `fence_order_ok` 해당 없음, fallback으로 풀린 시행의 `ow_data_equal`은 해당 없음), 또는 8절에 "fallback 시행은 perf 실패로만 셈"을 적기.

## 남은 문제와 필요한 최소 고침

| # | 문제 | 어디 | 최소 고침 | 상태 |
|---|---|---|---|---|
| 1 | 정상 대기자(rank 1)를 먼저 판정해 실제 장애(rank 3)의 hold와 펜스를 막고 fallback | 라이브러리 판정 규칙 | 후보를 목적지로 둔 문맥 원소를 판정에서 뺌(대안 다, 지적 일곱이 요구 사항) 또는 셀 B 주장을 fallback으로 좁힘 | 보고만 |
| 2 | `>= N_SCORED` 꼴은 자료 부족 시행만큼 분모가 줄어듦 | 8절 규칙, `score_gc.with_data_n` | k를 계획 n(`EFF`)으로, 또는 자료 부족 수 상한 | 결정 필요 |
| 3 | perf 행 안의 안전성 항이 fallback(복원 없음)을 어긋남으로 셈 | 8절 규칙, `score_gc.perf_safety_terms` | 동작이 있었던 시행에서만 항을 봄 | 결정 필요 |
| 4 | 셀 B `bound_s` 60 대 실제 200.4 s; 본 실행 hold C10이 880 s KILL에 걸릴 수 있음 | `cells_gc.json` | 셀 B `bound_s` 약 230, 또는 그 셀의 `WATCHDOG_S`를 줄임 | 결정 필요 |
| 5 | fallback 뒤 멈춘 rank 로그에 WARN 약 69만 줄(약 100 MB) | 라이브러리 또는 driver | 그 WARN을 communicator마다 한 번, 또는 driver의 오류 확인 간격 | 보고만 |
| 6 | 멈춘 대상의 자기 watchdog을 STOP_nic로 읽음 | `hold_gc.sh` | 이번에 고침(+14줄) | 고침, 하드웨어 a2에서 돎 |
