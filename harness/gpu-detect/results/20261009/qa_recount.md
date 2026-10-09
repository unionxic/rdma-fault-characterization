# gpu-detect: 본 실행의 독립 재계산 (2026-10-09)

다른 에이전트가 2026-10-09 22:26–22:34에 본 실행 폴더(`results/20261009/`, hold G1–R4, 시행 248)를 원자료에서 다시 셌다. 이 문서는 그
결과를 실험 폴더에 옮긴 요약이다. 재계산이 만든 행 표 두 개와 판정 표는 스크립트로 다시 만들 수 있어 커밋하지 않았다.

표시: `[측정]` 재계산 스크립트가 원자료에서 셈, `[내 확인]` 이 문서를 쓴 에이전트(마감)가 원자료나 `trials_scored.csv`에서 따로 셈(독립
확인 아님), `[추론]` 해석.

## 1. 방법

- **스크립트.** [../../qa/app_recount.py](../../qa/app_recount.py)(app 130회: `raw/<id>/`의 `r0.log`, `r1.log`, `a0.log`, `a1.log`,
  `trial.meta`), [../../qa/reg_recount.py](../../qa/reg_recount.py)(회귀와 지연 118회: `reg/hk/`, `reg/mr_hk/`, `reg/mr_hw/`의 kv, 로그,
  meta, `kill.out`, 원시 지연), [../../qa/verdicts.py](../../qa/verdicts.py)(두 행 표에서 41개 판정식을 자기 열로 다시 써서 판정하고,
  예측 문장이 판정식보다 많이 말하는 곳은 따로 따짐).
- **읽지 않은 것.** `score.py`, `rows_gd.py`, `SCORE.md`, `trials_scored.csv`, `trials_reg_hk.csv`, gin-remaining의 `score.py`. 정규식은
  직접 썼고, 열의 뜻은 EXPERIMENT.md 3.1절의 글과 `predictions.csv`의 문장에서 가져왔다.
- **제외.** app은 8절의 규칙(장애가 걸리지 않음, 시작 실패, 설정 확인 실패)을 다시 구현해 130회 모두 판정 가능으로 셌다. 회귀 스크립트는
  8절의 제외 규칙을 다시 구현하지 않고 118회를 모두 썼다. 회귀의 "제외 0"은 채점기의 값과 같다는 것까지이고 독립 확인은 아니다.
- **다시 돌리기.** 결과 폴더 밖의 빈 폴더에서:

  ```
  python3 <폴더>/qa/app_recount.py <폴더>/results/20261009 app_rows.csv
  python3 <폴더>/qa/reg_recount.py <폴더>/results/20261009 reg_rows.csv
  python3 <폴더>/qa/verdicts.py > verdicts.txt
  ```

  세 스크립트는 인자로 받은 CSV와 표준 출력에만 쓴다. 마감 때 Release와 같은 원자료로 다시 돌려 재계산 에이전트의 세 출력과 바이트 단위로 같은
  파일을 얻었다 `[내 확인]`.

## 2. 판정

재계산의 판정은 41개 모두 `SCORE.md`와 같다(모두 맞음). 범위는 따로 적지 않으면 그 셀 키의 모든 시행에 걸친 범위다 `[측정]`.

| 무엇을 예측했나 | id | 셀 | 재계산 | 수치 |
|---|---|---|---|---|
| GIN 예제 QP 오류(감시 10 ms): 복구 줄과 함께 투명 | GD1 | `gin_qperr@hk` | 16/16 | |
| 대상 rank가 훅 뒤 100 ms 안에 감지 | GD2 | 같음 | 16/16 | 0.208–58.182 ms, 중앙값 18.549. 감시 15(분류 출처 뿌리 CQE 14, 없음 1), 장치 1 |
| 훅 뒤 1 000 ms 안에 재개 | GD3 | 같음 | 16/16 | 11.588–69.502 ms, 중앙값 30.285 |
| 주기 1 ms, 100 ms에서도 투명, 감지 70 ms, 200 ms 안 | GD4 | `gin_qperr_w1@hk`, `_w100@hk` | 8/8, 8/8 | 1 ms: −0.085–50.978 ms(중앙값 41.189), 100 ms: 20.940–116.225 ms(중앙값 91.749) |
| 뿌리 CQE로 분류한 감시 감지의 중앙값이 주기 순서 | GD5 | 세 셀 | 맞음 | 6.202(n=3) < 18.549(n=14) < 91.749 ms(n=8) |
| 감시 없는 앞 빌드: 빠른 감지와 복구 없음 | GC1 | `gin_qperr@hr`, `@hq` | 6/6, 6/6 | 12회 모두 두 rank가 감지와 복구 줄 없이 20 s 상한까지 멈춤 |
| 같은 빌드의 감시 끔: 같음 | GC2 | `gin_qperr_w0@hk` | 3/4(N − 1) | 놓친 시행 `gin_qperr_w0.hk.n3`(3절 1번) |
| GIN kill: 5 s 안 오류, 감시 감지 없음 | GR1 | `gin_kill@hk` | 6/6 | 살아남은 rank의 첫 오류 줄 kill 0.0002–0.0071 s 뒤. 6회 모두 결과는 멈춤(유예로 끝남) |
| GIN 1–8 s 멈춤: 투명, 죽음과 거절과 감시 감지 없음 | GF1 | `gin_stop@hk` | 8/8 | |
| GIN 장애 없음: 투명, 감시 감지와 거절 없음 | GF2 | `gin_none@hk` | 6/6 | |
| NVSHMEM kill: FIN 판정 0.1 s 안, 종료 코드 70으로 1 s 안 | ND1 | `nvs_kill@t1w` | 8/8 | 판정 kill 응답 0.027–0.494 ms 뒤, 살아남은 PE 종료 73.0–95.4 ms 뒤 |
| 원격 접근 회수: 두 PE가 2 s 안에 종료 코드 70 | ND2 | `nvs_remacc@t1w` | 8/8 | 두 PE의 거절 훅 3.3–11.2 ms 뒤, 두 PE 종료 86.4–105.9 ms 뒤 |
| t1_380 kill: 오류 줄 없이 멈춤 | NC1 | `nvs_kill@t1_380` | 4/4 | 문장 확인 4/4(3절 4번) |
| t1_380 원격 접근 회수: 거절하고도 멈춤 | NC2 | `nvs_remacc@t1_380` | 4/4 | 문장 확인 4/4(3절 4번) |
| release: 해제 줄과 함께 스스로 끝남 | NR1 | `nvs_kill_rel@t1w`, `nvs_remacc_rel@t1w` | 5/5, 5/5 | 3절 7번 |
| NVSHMEM PE 0 멈춤: 투명, 죽음과 거절 없음 | NF1 | `nvs_stop@t1w` | 8/8 | |
| NVSHMEM 장애 없음: 투명, 거절과 FIN 판정 없음, 작별 보냄 | NF2 | `nvs_none@t1w` | 8/8 | 4절 1번 |
| 장치 대기 단어 확인의 비용 10% 이하 | NO1 | `nvs_none@t1w`, `@t1_380` | 맞음 | 중앙값 18.960463(n=8)과 18.970415 ms(n=6), 비 0.99948 |
| NVSHMEM QP 오류: 투명 | NQ1 | `nvs_qperr@t1w` | 6/6 | |
| 랭크 2개 회귀: 투명 | RG1 | `f1_b`, `f3_b`, `bidirf_sym_b` | 5/5씩 | |
| 랭크 2개 kill: 2 s 안 peer-dead 거절 | RG3 | `f4_b@hk` | 5/5 | kill 1.643–1.788 ms 뒤 |
| 받기만 하는 rank의 대기가 2 s 안에 풀림 | RG4 | `hd_rxdeath_b@hk` | 5/5 | 해제 줄 1.704–1.844 ms, 비동기 오류 2.019–2.119 ms(kill 뒤, 4절 2번) |
| 원격 접근 오류: rank 0 거절, rank 1 해제, abort 5 s 안 | RG5 | `f2rel_b@hk` | 5/5 | abort 725.3–753.0 ms |
| 통계 API 라운드 1, 복구 1 | RG7 | `f1_b@hk` | 5/5 | |
| 랭크 4개 장애 없음, 한 쌍 QP 오류: 투명 | RG8 | `mr4_none`, `mr4_f1_01` | 5/5씩 | |
| rank 3 kill, 시간 제한 없는 받기: 판정 2 000–3 000 ms 뒤 해제 | RG9 | `rm4_kill3_untimed@hk` | 5/5 | 2 006.4–2 013.9 ms(생존 rank 값 15) |
| 순환하는 시작 쪽 셋 복구 | RG10 | `mr4_cyc_stall@hk` | 5/5 | |
| M-A: rank 3이 낮은 rank의 REQ 둘에 기다림 안에서 답함 | MA1 | `mr4_twolow_stall@hk` | 5/5 | |
| M-C 기본 규칙: 건강한 쌍 거절 | MC1 | `rm4_late01@hk` | 3/3 | |
| M-C 대조: 복구 | MC2 | `rm4_late01_rounds@hk` | 3/3 | |
| 응답 쪽 틈 고침(`hk`) | GP1 | `rm4_gap@hk` | 5/5 | 원인 peer-dead 5/5, 해제 2 007.7–2 013.0 ms(값 15) |
| 대조(`hw`) | GP2 | `rm4_gap@hw` | 3/3 | rank 0 원인 unknown, 풀리지 않음, 커널이 돎, 종료 코드 3(3/3). rank 1, 2 해제 2 007.8–2 012.3 ms(값 6) |
| ACK 뒤 종료 시험 스위치 | GP3 | `rm4_gapx@hk` | 3/3 | rank 3 종료 코드 73, 해제 2 008.1–2 012.5 ms(값 9) |
| hold 요청: rank마다 WARN 하나, fail-fast | PH1 | `rm4_kill3_hold@hk` | 3/3 | 해제 2 007.1–2 013.0 ms(값 9) |
| 정책 불일치: 두 rank WARN 하나씩, fail-fast | PH2 | `f4_mix_b@hk` | 3/3 | agreed 0, peer-dead 거절 kill 1.54–1.76 ms 뒤 |
| NIC 경로가 NIC만 쓴 자체 시험과 함께 켜짐 | LC1 | `gin_none@hk`, `f1_b@hk` | 6/6, 5/5 | |
| 정리 때 감시 줄이 두 rank에 | WT1 | `gin_none@hk` | 6/6 | |
| 4 KiB, 256 KiB 지연 차이(감시 10 ms, 1 ms 대 끔) | LT1–LT4 | 지연 셀 | 맞음 | kv p50 중앙값 4 KiB 10.500, 256 KiB 38.880 µs로 모든 주기에서 같음(차이 0.000). 원시 지연에서 다시 계산한 p50 중앙값 10.4960, 38.8800 µs |

## 3. 판정식과 문장의 차이, 눈여겨볼 것

1. **감시 끔 대조(GC2)는 N − 1 허용으로만 맞았다.** `gin_qperr_w0.hk.n3`(훅이 문맥 생성 뒤 16 ms)에서 대상 rank 0의 장치 경로가 훅 발화 0.90 ms
   뒤, 훅이 아직 QP를 옮기는 중에 LOCAL_QP_ERR를 분류했고 11.1 ms에 복구해 투명이었다. 예측 문장 "감시 없이는 아무것도 빨리 감지하지 못한다"는 이
   시행에서 틀렸다. 이 시행은 멈춤도 늦은 RETRY_EXC도 아니다. 나머지 3회는 두 rank 모두 20 s 상한까지 멈췄다 `[측정]`.
2. **음의 감지 지연 둘.** `gin_qperr_w1.hk.n1` −0.085 ms, `gin_qperr_w0.hk.n3` −0.364 ms. 장치가 분류한 CQE 줄의 `mono_ms`가 훅 줄의
   `fire_mono_ms`와 `done_mono_ms` 사이에 있다(발화 뒤 1.28 ms와 0.90 ms) `[측정, 내 확인]`. GD4의 판정식에는 아래 한도가 없어 첫째가 통과했다.
   GD2 셀에는 음수가 없다.
3. **GD5와 50 ms 기다림.** 중앙값에 든 시행은 주기 1 ms 3/8, 10 ms 14/16, 100 ms 8/8이다. 그런데 뿌리 CQE로 분류한 감시 감지 8회도 감시 줄의
   "ERR로 본 시간"이 48.9–51.3 ms로, 뿌리 CQE가 없는 창의 50 ms 기다림을 거쳤다(10 ms의 n8, n9, n16, 100 ms의 n1, n3, n5, n6, n8). 이 8회를
   빼면 6.20 < 14.82 < 91.36 ms(n=3, 11, 3)로 순서는 같다. 모든 시행의 감지 지연 중앙값은 주기 순서가 아니다: 1 ms 41.19, 10 ms 18.55, 100 ms
   91.75 ms. 1 ms 셀은 8회 중 4회가 뿌리 CQE 없이 50.6–51.0 ms에, 1회가 장치로 감지됐다 `[측정, 내 확인]`. 가설 H2의 반증 문장은 이 거름을
   두지 않았다(EXPERIMENT.md 17절).
4. **NC1, NC2의 문장 확인.** 판정식(NC1은 죽음 줄만, NC2는 한 PE의 거절과 유예 종료도 통과)보다 문장이 강하다(리뷰 M3). 시행마다 문장대로
   따졌다. NC1 4회: 살아남은 PE의 오류 줄 0, 죽음 줄 0, 하네스 유예로 끝남. 시행마다 "library socket closed (FIN)" 줄 하나가 있으나 blind-apps의
   정의로 오류 줄이 아니다. NC2 4회: 두 PE가 한 번씩 거절, 두 PE 모두 시간 상한으로 끝남. 문장도 맞다 `[측정]`.
5. **대상 rank의 균형.** `schedule.json`은 시행마다 대상을 따로 뽑았으므로 셀 안에서 반씩이 아니다. rank 0 : rank 1 = `gin_qperr@hk` 8:8,
   `gin_qperr_w0@hk` 2:2, `nvs_kill@t1_380` 2:2, `gin_qperr@hr` 1:5, `@hq` 2:4, `gin_qperr_w1@hk` 3:5, `gin_qperr_w100@hk` 6:2, `gin_kill@hk` 2:4,
   `gin_stop@hk` 2:6, `nvs_kill@t1w` 5:3, `nvs_remacc@t1w` 3:5, `nvs_remacc@t1_380` 0:4, `nvs_kill_rel@t1w` 1:4, `nvs_remacc_rel@t1w` 4:1,
   `nvs_qperr@t1w` 1:5 `[측정, 내 확인]`. `nvs_stop`은 설계대로 PE 0만이다.
6. **NVSHMEM 실행 속도가 둘로 갈린다.** 64 MiB 반복당 약 11.5 ms와 약 19.0 ms. `t1w` 8회 중 빠름 3, t1_380 6회 중 1. 같은 속도끼리 중앙값의 비는
   빠름 1.0074, 느림 0.9991 `[측정, 내 확인]`. 중앙값 비교(NO1)는 두 셀 모두 느린 쪽이 많아 느린 실행끼리의 비교가 되었다 `[추론]`.
7. **release는 대기를 풀지만 데이터는 주지 않는다.** 살아남은 프로세스는 모두 해제 줄을 남기고 스스로 끝났다(kill 셀은 살아남은 PE 하나, 원격
   접근 셀은 두 PE). 그러나 예제의 결과는 10회 중 9회 틀렸다(틀린 원소 줄 8 388 608–46 137 341, 두 PE 합). 맞은 1회
   `nvs_kill_rel.t1w.n3`은 살아남은 PE가 kill 0.165 s 뒤 끝난 시행이다 `[측정]`. EXPERIMENT.md 9.2절 (d)의 "받지 못한 데이터는 틀린 값 그대로"와
   같다.

## 4. 채점기와 정의가 다른 열 `[내 확인]`

판정은 두 정의 모두에서 같다.
1. `n_bye_sent`(NF2): 채점기는 "goodbye sent to N peer(s)" 줄 중 N ≥ 1인 줄을, 재계산은 모든 줄을 센다. 장애 없는 셀 8회 모두 먼저 정리한 PE가
   1 peer에, 다른 PE가 0 peer에 보냈다고 적었다(채점기 1, 재계산 2). 작별을 받은 PE는 보낼 곳이 없다는 리뷰 H2(12절)의 설명과 맞는다.
2. `release_after_kill_ms_r1`(RG4): 채점기는 gin-harden의 정의(받기만 하는 rank의 커널 끝, kill 뒤 20.6–21.4 ms), 재계산은 devComm 단어의 해제
   줄(1.70–1.84 ms)을 썼다. 둘 다 2 000 ms 안이다.

## 5. 안전과 무결성

- 여덟 hold 모두 첫 회 rc=0, 새 mlx5 줄 0, 스냅숏 16개에서 rain 펌웨어 명령 실패 합 31과 rain 명령 오류 줄 2(sunny 0)가 그대로, iptables 규칙
  0 → 0, STOP 파일 없음 `[측정, 내 확인]`.
- 고정 파일 12개의 sha256이 `PREREG.txt`와 같고, `git diff prereg/gpu-detect-v1 -- predictions.csv cells.json schedule.json`이 비어 있다. app
  hold 넷의 시행 목록 sha256이 `7a5e4875…`다. 본 실행의 첫 시행 파일(21:35:41)은 태그(21:34:56, 커밋 21:33:54) 뒤다 `[내 확인]`.
