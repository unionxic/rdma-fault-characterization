# gin-restore 본 실행 독립 재계산 (QA, 20261013_main)

대상: `results/20261013_main/raw/`(복원과 거절 셀 57시행)와 `reg/`(회귀 셀 20시행). 비용 hold(`cost_log_*`, `cost_ffbranch_*`)는
아직 쓰는 중이라 읽지 않았다. 채점기(`impl/test/score.py`, `rows_rs.py`, `selftest_rs.py`)와 그 출력(`SCORE.md`, `trials_scored.csv`)은
1–3절을 쓸 때까지 열지 않았다. 4절만 `SCORE.md`를 읽고 쓴다.

읽은 것: `EXPERIMENT.md` 3절(조건 문장), 7절(셀과 n), 8절(제외와 중단), 9.8절(workload와 판정), `impl/test/predictions_rs.csv`(판정식),
`impl/test/run_rs.sh`와 `impl/test/gin_rs.cu`의 머리말(로그 줄과 kv 키), `../remaining/run_mr_hr.sh` 머리말, `impl/test/cells_rs.json`(셀의
driver), `impl/test/hold_rs.sh`(STOP 파일과 QUERY_QP 상한이 어디에 남는지), gin-remaining `EXPERIMENT.md`의 DG1, DG3 행(회귀 판정의 원문).

재계산 스크립트: `recount_rs.py`(원자료 → 시행별 표 `out/trials_recount.csv`와 판정 `out/summary.txt`), `ranges.py`(셀별 범위),
`table_md.py`(아래 시행별 표). 실행: `python3 recount_rs.py <results/20261013_main> out`. 출력의 IPv4 형태 문자열은 모두 가린다(회귀
로그는 실행기가 가리지 않으므로 숫자만 뽑고 줄은 옮기지 않음).

표시: `[측정]` 원자료에서 다시 셈, `[추론]` 해석, `[미확인]` 확인 못 함.

## 1. 예측마다 쓴 방법

공통.
- 시각: raw 로그의 줄 앞 숫자(rain CLOCK_MONOTONIC의 수신 시각, s)를 "수신 시각"이라 부른다. 같은 프로세스의 두 줄 사이 간격은 줄 안의
  `mono_ms`(그 프로세스의 시계)로도 잰다. 노드가 다른 rank 사이 간격은 수신 시각으로만 잰다.
- 죽은 rank kr = meta `kill_rank`. 생존 rank = 나머지 셋. kill 시각 = `_kill.out`의 `GINRS killed rank=kr` 줄의 수신 시각. 체크포인트 멈춤 중
  kill 셀은 kr 로그의 `test switch NCCL_GIN_RESTORE_TEST_DIE_IN_CKPT: dying 300 us after the pause request of checkpoint C` 줄의 수신 시각.
  kill이 실제로 들어갔는지는 meta `r<kr>rc=137`(SIGKILL)과 그 줄로 본다.
- 죽음 판정 = 생존 rank s 로그의 `rank s: rank kr judged dead` 줄. "첫 죽음 판정" = 세 생존 rank 가운데 가장 이른 수신 시각.
- kv는 프로세스마다 `key=value`이고 같은 키가 다시 나오면 뒤의 값을 쓴다.

예측별(괄호 안은 찾는 키).

| 무엇을 예측했나 | 시행마다 쓴 줄과 키, 계산 |
|---|---|
| 생존 rank의 상대를 모르는 대기가 풀리지 않음 (`wait_held`) | 생존 rank 셋 모두: kv `released=0`, `steps_done=600`(600단계의 모든 `waitSignal`이 문턱 이상으로 돌아옴), `async_n=0`; 로그에 `GINRS step ... released=1` 줄 0, `GINRS async` 줄 0, 거절 줄(`declined rank=s peer=kr`) 0. 보고만: `GIN error raised`, `communicator degraded` 줄 수(모두 0) |
| 최종 데이터가 기준과 같음 (`data_equal`) | 논리 rank 넷의 마지막 프로세스(생존 rank 셋 + 되살린 예비 프로세스) 모두 kv `x_match=1`, `recv_bad=0`, `xhist_bad=0`, `dev_bad=0`, `sig_exact=1`, `steps_done=600`. 이 키들은 gin_rs가 호스트 기준(같은 `__host__ __device__` 함수)과 비트 단위로 비교한 결과다 |
| 생존 rank는 다시 실행하지 않음 (`no_reexec`) | 생존 rank 셋 모두 kv `reexec_any=0`, `reexec_max=1`, `steps_done=600`(모든 단계 실행 수가 정확히 1) |
| 되살린 rank가 끝까지 감 (`revived_done`) | 예비 프로세스 kv `revived=1`, `steps_done=600`, `exit=0`, `xchg=ok`, meta `sparerc=0` |
| 다시 보내기 억제가 정확함 (`suppress_exact`) | 비교한 것: 예비 프로세스 로그의 `rank kr: suppress peer=q qp=k budget=B suppressed=S left=L` 줄(같은 (q, k)는 마지막 줄)의 S와, 원자료에서 따로 센 X_q − P_q. X_q − P_q = 2 × (max(L_kr, S_q, C) − k): k = 예비 프로세스가 쓴 체크포인트(`checkpoint k fetched from buddy`; 체크포인트 k는 단계 k 뒤에 찍히므로 그때 kr이 q에 보낸 메시지는 2(k+1)개, 단계마다 put+신호 둘), L_kr = kr 로그의 마지막 `GINRS step rank=kr step=L released=0`(그 단계의 put은 flush로 실행 완료), S_q = q가 자기 "restored as" 줄 전에 끝낸 마지막 단계(q가 단계 s를 끝내려면 kr의 단계 s 메시지를 이미 실행했어야 함), C = 체크포인트 멈춤 중 kill의 죽은 체크포인트(단계 C까지 kr이 끝냄). 시행 조건: q마다 예산이 0이 아닌 QP가 정확히 하나이고 그 줄이 S = B = 예상값, L = 0이며 나머지 QP는 B = S = 0. 생존 rank 쪽 교차 확인: rank 0의 `hold of rank kr started ... (executed/sent at the hold: X/…)`는 그 rank의 첫 QP(context 0, kr → rank 0 통로)의 응답 쪽 실행 수라 X − 2(k+1)이 rank 0 통로의 예상값과 같아야 함(rank 1, 2 통로는 이 줄에 수가 없음) |
| 복원 시간이 시한 안 (`restore_time`) | 첫 죽음 판정 줄 → 세 생존 rank의 `rank s: rank kr restored as incarnation 1 (on time; …)` 줄 가운데 마지막(그 줄이 hold 상태를 끄고 게이트를 다시 엶). 둘 다 수신 시각. ≤ 2 000 ms |
| 체크포인트 멈춤 중 kill (`ckpt_kill`) | 죽음 줄(시험 스위치) 있음; 멈춤 안 생존 rank 수 = 생존 rank s 로그에 `input pause for rank kr's checkpoint C ended (a hold of that rank took its gates)`가 있고 그 rank의 hold 시작 줄이 `gates odd since x ms before the start`(x > 0)인 rank의 수(= 3 이어야 함); 위 넷(대기, 데이터, 재실행 없음, 끝까지); 쓰인 체크포인트 k < C이고 kill 수신 시각 전에 생존 rank 로그에 `rank kr armed at its stable checkpoint k` 줄이 있음 |
| 같은 GPU의 다른 rank가 죽어도 같음 (`kill_other`) | kr = 1로 위 넷을 같은 방식으로 |
| 예비 프로세스 미등록이면 fail-fast (`nospare_failfast`) | 생존 rank 셋 모두: hold 줄(`is held for a restore`, `hold of rank kr started`) 0, 거절 줄 있음, kv `released=1`, 그리고 `GINRS step ... released=1` 줄의 `mono_ms` − 자기 죽음 판정 줄의 `mono_ms`가 2 000–2 500 ms. 보고만: 수신 시각으로 첫 죽음 판정부터 잰 값 |
| 등록한 예비 프로세스가 없어지면 fallback (`spare_absent_fallback`) | 생존 rank 셋 모두: hold 시작 줄 있음, `the restore of rank kr (incarnation 0) is given up (…)` 줄의 `mono_ms` − 자기 hold 시작 줄의 `mono_ms`가 500–1 500 ms, 풀림 줄의 `mono_ms` − fallback 줄의 `mono_ms`가 2 000–2 500 ms, kv `released=1`. 예비 프로세스가 kr보다 먼저 죽었는지는 `_spare_kill.out` |
| 대조: 복원 없는 빌드는 degraded로 풀림 (`control_degraded`) | 생존 rank 셋 모두 kv `released=1`이고 풀림 − 자기 죽음 판정(`mono_ms`)이 2 000–2 500 ms |
| 장애 없음 (`none_clean`) | rank 넷 모두 데이터 키(위와 같음); 복원 수 = hold와 복원 줄 수 + `hold at close`의 holds, restored, fallbacks 합 + 예비 프로세스 유무 = 0; 입력 멈춤 = 모든 rank의 `rank s: input pause for rank r's checkpoint c ended (…) pause_us=N` 줄의 최대 ≤ 10 ms |
| window strict (`strict_forced`, `strict_notforced`) | 모든 프로세스의 `window MR rank=… strict= forced= flag_strict= ro= restore_requested=` 줄을 셈. 강제 = forced=1, 강제 아님 = forced=0, 어긋남 = (forced=1이고 strict=0) 또는 (restore_requested=1이고 forced=0) 또는 (forced=1이고 restore_requested=0). 복원 켠 셀은 강제 > 0, 강제 아님 0, 어긋남 0; 끈 셀은 강제 아님 > 0, 강제 0, 어긋남 0 |
| 켤 수 없으면 같은 이유의 오류 (`refuse_reason`) | rank 넷 kv `resume_rc` ≠ 0, `resume_why`가 넷 모두 같음, 오류 없이 넘어간 rank 0: 매크로 셀이 아닌 셋은 rank마다 `GINRS step` 줄 0이고 kv `xchg=refused`; 매크로 없는 셀은 단계를 돈 rank가 `resume_rc` ≠ 0과 `refused_then_ran=1`을 모두 가짐 |
| 매크로 없는 프로그램 (`refuse_nomacro_clean`) | 위에 더해 넷의 이유에 `NCCL_GIN_RESTORE_DEVICE`가 들고, 넷 모두 데이터 키, `released=0`, `async_n=0`, `xchg=ok`, `exit=0`, `cuda_error` 없음, meta rc 0 |
| 회귀, 장애 없음 (`regression_none`) | rank 넷 kv `exit=0`, `tx_ok=3`, `rx_ok=3`, meta rc 0 |
| 회귀, rank 3 kill (`regression_kill3`) | 생존 rank 셋 kv `rx_3s_rel=1`이고 `rx_3s_rc`가 오류 문자열; `rx_3s_rel_mono_ms` − 자기 로그의 `rank s: rank 3 judged dead … mono_ms`가 2 000–3 000 ms(gin-remaining DG1 원문: 죽음 판정부터); 생존 rank 사이 보내기 6개 모두 `tx_ab_done=1000`, `tx_ab_rc=no error`, `tx_ab_nerr=0`; 생존 rank 셋 `kernel_done=1`, watchdog 없음 |

판정: 8절의 제외를 뺀 유효 시행 n개 가운데 조건이 참인 시행 수 k를 판정식(`predictions_rs.csv`)의 문턱과 견준다. "N_SCORED"는 유효 시행
전부. 유효 시행이 계획의 75% 미만이면 "자료 부족"으로 둔다.

## 2. 결과

`[측정: recount_rs.py, out/trials_recount.csv]` 제외한 시행은 0이다(3절).

| 무엇을 예측했나 (찾는 키) | 셀 | n 계획 | n 유효 | k | 기준 | 판정 | 시행별 값의 범위 (무엇의 범위인지) |
|---|---|---|---|---|---|---|---|
| 생존 rank의 상대를 모르는 대기가 풀리지 않음 (`wait_held`) | `rs4_kill3@rs` | 10 | 10 | 10 | ≥ 9 | 맞음 | 생존 rank 30개 모두 600단계, 풀림 0, 비동기 오류 0, 거절 줄 0 |
| 최종 데이터가 기준과 같음 (`data_equal`) | `rs4_kill3@rs` | 10 | 10 | 10 | ≥ 9 | 맞음 | 프로세스 40개(생존 30 + 되살린 10) 모두 같음 |
| 생존 rank는 다시 실행하지 않음 (`no_reexec`) | `rs4_kill3@rs` | 10 | 10 | 10 | 10/10 | 맞음 | 생존 rank 30개 모두 실행 수 최대 1 |
| 되살린 rank가 끝까지 감 (`revived_done`) | `rs4_kill3@rs` | 10 | 10 | 10 | ≥ 9 | 맞음 | 시작 단계 113–134, 600단계, exit 0 |
| 다시 보내기 억제가 정확함 (`suppress_exact`) | `rs4_kill3@rs` | 10 | 10 | 10 | ≥ 9 | 맞음 | 통로 30개 모두 억제 수 = 예상(10–50 메시지), 남은 예산 0; rank 0 통로 10개는 hold 시작 줄의 실행 수로도 같음 |
| 복원 시간이 2 000 ms 안 (`restore_time`) | `rs4_kill3@rs` | 10 | 10 | 10 | ≥ 9 | 맞음 | 278.0–397.9 ms (시행 10개) |
| 체크포인트 멈춤 중 kill도 앞 체크포인트에서 복원 (`ckpt_kill`) | `rs4_kill3_ckpt@rs` | 5 | 5 | 4 | ≥ 4 | 맞음 | n4가 조건 불충족: 짝 rank 2가 그 체크포인트의 입력 멈춤에 들지 않음(멈춤 안 2/3). 다섯 모두 대기, 데이터, 재실행 없음, 끝까지 참; 쓰인 체크포인트는 죽은 체크포인트의 20단계 앞(73/93, 91/111, 93/113); 복원 378.0–395.1 ms |
| 같은 GPU의 다른 rank가 죽어도 같음 (`kill_other`) | `rs4_kill1@rs` | 5 | 5 | 5 | ≥ 4 | 맞음 | 복원 372.5–400.8 ms, 억제 통로 15개 모두 예상과 같음 |
| 예비 프로세스 미등록이면 fail-fast (`nospare_failfast`) | `rs4_kill3_nospare@rs` | 5 | 5 | 5 | ≥ 4 | 맞음 | hold 줄 0, 생존 rank 15개 모두 거절 줄, 풀림은 자기 죽음 판정 2 002.0–2 006.2 ms 뒤 (생존 rank 15개) |
| 등록한 예비 프로세스가 없어지면 fallback (`spare_absent_fallback`) | `rs4_kill3_spareabsent@rs` | 5 | 5 | 5 | ≥ 4 | 맞음 | fallback은 hold 시작 1 000.5–1 003.0 ms 뒤, 풀림은 fallback 2 000.5–2 004.5 ms 뒤 (생존 rank 15개) |
| 대조: 복원 없는 빌드는 degraded로 풀림 (`control_degraded`) | `rs4_kill3@hk` | 5 | 5 | 5 | ≥ 4 | 맞음 | 자기 죽음 판정 2 001.5–2 004.7 ms 뒤 (생존 rank 15개) |
| 장애 없음: 데이터 같음, 복원 0, 멈춤 짧음 (`none_clean`) | `rs4_none@rs` | 5 | 5 | 5 | 5/5 | 맞음 | 입력 멈춤 최대 5.177–5.619 ms (시행마다 멈춤 줄 348개의 최대, 시행 5개) |
| hold 셀의 window MR은 모두 strict 강제 (`strict_forced`) | `rs4_none@rs` | 5 | 5 | 5 | 5/5 | 맞음 | 시행마다 강제 16 (rank마다 4), 강제 아님 0, 어긋남 0 |
| 복원 끈 셀은 강제 0 (`strict_notforced`) | `rs4_none_off@rs` | 5 | 5 | 5 | 5/5 | 맞음 | 시행마다 강제 아님 16 (strict=0, ro=1), 강제 0 |
| 켤 수 없으면 모든 rank가 같은 이유의 오류 (`refuse_reason`) | `rs4_refuse_symgin@rs` | 3 | 3 | 3 | 3/3 | 맞음 | rc 5 넷, 이유 같음 (symmetric 커널의 GIN) |
| 같은 예측 | `rs4_refuse_gintype@rs` | 3 | 3 | 3 | 3/3 | 맞음 | rc 5 넷, 이유 같음 (GIN 백엔드가 GDAKI 아님, type 2); meta `gin_type=2` |
| 같은 예측 | `rs4_refuse_restoreoff1@rs` | 3 | 3 | 3 | 3/3 | 맞음 | rc 5 넷, 이유 같음 (rank 3만 복원을 요청하지 않음) |
| 같은 예측 | `rs4_refuse_nomacro@rs` | 3 | 3 | 3 | 3/3 | 맞음 | rc 5 넷, 이유 같음; 거절 뒤 단계를 돈 rank는 모두 오류를 보고한 뒤 |
| 매크로 없는 프로그램은 거절 뒤 fail-fast로 끝까지 (`refuse_nomacro_clean`) | `rs4_refuse_nomacro@rs` | 3 | 3 | 3 | 3/3 | 맞음 | 이유에 `NCCL_GIN_RESTORE_DEVICE`, 600단계, 데이터 같음, exit 0 (rank 12개) |
| 회귀 없음, 장애 없음 (`regression_none`) | `reg_mr4_none@rs` | 5 | 5 | 5 | 5/5 | 맞음 | rank 20개 exit 0, 보내기 3/3, 받기 3/3 |
| 같은 예측 | `reg_mr4_none_hold@rs` | 5 | 5 | 5 | 5/5 | 맞음 | 같음 |
| 회귀 없음, rank 3 kill (`regression_kill3`) | `reg_rm4_kill3_untimed@rs` | 5 | 5 | 5 | 5/5 | 맞음 | rank 3 받기 오류 해제 2 006.4–2 013.3 ms (생존 rank 15개), 생존 rank 사이 보내기 6/6, 커널 3/3 |
| 같은 예측 | `reg_rm4_kill3_untimed_hold@rs` | 5 | 5 | 5 | 5/5 | 맞음 | 2 006.3–2 012.0 ms (생존 rank 15개), 6/6, 3/3 |

복원 셀의 그 밖의 값 `[측정]`(범위는 셀의 시행 전체):

| 셀 | 활성화: hold 시작 뒤 ms (짝의 줄) | 활성화: 첫 죽음 판정 뒤 ms | 'later' 답 수 / 걸린 ms | 체크포인트 가져오기 ms | 다시 넣은 로그 항목 | 예비 프로세스가 다시 낸 단계 | 생존 rank 입력 멈춤 최대 ms | 초기화 재생 |
|---|---|---|---|---|---|---|---|---|
| `rs4_kill3@rs` | 2.1–128.6 | 2.9–129.4 | 0–6 / 0.0–126.2 | 218.1–225.1 | 15–75 | 5–25 | 4.9–5.7 | 28/29 항목, 어긋남 0, 넘침 0, strict 불일치 0 (10/10) |
| `rs4_kill1@rs` | 103.1–128.7 | 103.5–129.2 | 5–6 / 101.0–126.4 | 214.4–221.6 | 21–31 | 7–11 | 5.1–5.8 | 같음 (5/5) |
| `rs4_kill3_ckpt@rs` | 104.6–127.7 | 105.0–128.2 | 5–6 / 101.9–125.4 | 214.1–224.2 | 60 | 20 | 4.6–5.8 | 같음 (5/5) |

`rs4_kill3` n7은 원래 프로세스가 "zombie (not reaped)"로 보여 'later' 없이 hold 시작 2.1 ms 뒤에 활성화됐고 복원이 278.0 ms로 가장 짧다.
`rs4_kill1` n1도 zombie로 보았으나 'later' 6번 뒤였다 `[측정]`.

시행별 값(셀마다). "억제 rank별"은 통로마다 `억제 수/예상(X − P)`. "다시 낸 단계" = max(L_kr, S_q, C) − k.

**rank 3 kill, 예비 프로세스 있음** (`rs4_kill3@rs`, n=10)

| 시행 | 대기 붙잡힘 | 데이터 같음 | 재실행 없음 | 되살린 rank 끝 | 억제 rank별 (셈/예상) | 복원 시간 ms | 활성화 ms(hold 시작 뒤) | 'later' 수 / ms | 체크포인트 / 죽은 rank 마지막 단계 / 다시 낸 단계 | 체크포인트 가져오기 ms | 입력 멈춤 최대 ms |
|---|---|---|---|---|---|---|---|---|---|---|---|
| n1 | 예 | 예 | 예 | 예 | r0 12/12, r1 12/12, r2 12/12 | 372.9 | 103.0 | 5 / 101.0 | 132 / 138 / 6 | 223.2 | 5.1 |
| n2 | 예 | 예 | 예 | 예 | r0 48/48, r1 48/48, r2 48/48 | 371.7 | 103.5 | 5 / 100.8 | 113 / 137 / 24 | 218.1 | 4.9 |
| n3 | 예 | 예 | 예 | 예 | r0 48/48, r1 48/48, r2 48/48 | 395.0 | 123.0 | 6 / 121.0 | 113 / 137 / 24 | 221.5 | 5.6 |
| n4 | 예 | 예 | 예 | 예 | r0 10/10, r1 10/10, r2 10/10 | 374.5 | 106.5 | 5 / 104.1 | 133 / 138 / 5 | 221.4 | 5.7 |
| n5 | 예 | 예 | 예 | 예 | r0 10/10, r1 10/10, r2 10/10 | 396.0 | 128.6 | 6 / 126.2 | 133 / 138 / 5 | 221.1 | 5.4 |
| n6 | 예 | 예 | 예 | 예 | r0 12/12, r1 12/12, r2 12/12 | 374.6 | 107.5 | 5 / 105.2 | 131 / 136 / 6 | 219.9 | 5.4 |
| n7 | 예 | 예 | 예 | 예 | r0 50/50, r1 50/50, r2 50/50 | 278.0 | 2.1 | 0 / 0.0 | 113 / 138 / 25 | 225.1 | 5.0 |
| n8 | 예 | 예 | 예 | 예 | r0 48/48, r1 48/48, r2 48/48 | 397.9 | 123.4 | 6 / 121.3 | 113 / 136 / 24 | 222.2 | 5.3 |
| n9 | 예 | 예 | 예 | 예 | r0 46/46, r1 46/46, r2 46/46 | 396.5 | 125.2 | 6 / 123.0 | 113 / 136 / 23 | 219.7 | 5.1 |
| n10 | 예 | 예 | 예 | 예 | r0 48/48, r1 48/48, r2 50/50 | 377.6 | 106.9 | 5 / 104.7 | 112 / 136 / 25 | 220.3 | 5.6 |

**rank 1 kill (같은 GPU의 다른 rank)** (`rs4_kill1@rs`, n=5)

| 시행 | 대기 붙잡힘 | 데이터 같음 | 재실행 없음 | 되살린 rank 끝 | 억제 rank별 (셈/예상) | 복원 시간 ms | 활성화 ms(hold 시작 뒤) | 'later' 수 / ms | 체크포인트 / 죽은 rank 마지막 단계 / 다시 낸 단계 | 체크포인트 가져오기 ms | 입력 멈춤 최대 ms |
|---|---|---|---|---|---|---|---|---|---|---|---|
| n1 | 예 | 예 | 예 | 예 | r0 22/22, r2 22/22, r3 22/22 | 392.9 | 126.5 | 6 / 124.3 | 127 / 137 / 11 | 214.4 | 5.1 |
| n2 | 예 | 예 | 예 | 예 | r0 16/16, r2 16/16, r3 16/16 | 400.8 | 128.7 | 6 / 126.4 | 130 / 138 / 8 | 221.6 | 5.7 |
| n3 | 예 | 예 | 예 | 예 | r0 14/14, r2 14/14, r3 14/14 | 389.8 | 126.4 | 6 / 124.1 | 131 / 138 / 7 | 216.9 | 5.8 |
| n4 | 예 | 예 | 예 | 예 | r0 14/14, r2 14/14, r3 14/14 | 372.5 | 103.1 | 5 / 101.0 | 130 / 137 / 7 | 221.0 | 5.6 |
| n5 | 예 | 예 | 예 | 예 | r0 14/14, r2 14/14, r3 14/14 | 372.7 | 106.8 | 5 / 104.6 | 130 / 137 / 7 | 220.5 | 5.8 |

**체크포인트 멈춤 중 kill** (`rs4_kill3_ckpt@rs`, n=5)

| 시행 | 죽은 체크포인트 | 멈춤 안 생존 rank 수 | 멈춤 시작 - 자기 죽음 판정 ms | 앞 체크포인트 확정 | 앞 확정 수 | 대기 붙잡힘 | 데이터 같음 | 재실행 없음 | 되살린 rank 끝 | 억제 rank별 (셈/예상) | 복원 시간 ms | 활성화 ms(hold 시작 뒤) | 'later' 수 / ms | 체크포인트 / 죽은 rank 마지막 단계 / 다시 낸 단계 | 체크포인트 가져오기 ms | 입력 멈춤 최대 ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| n1 | 93 | 3 | r0:+1.61 r1:-0.04 r2:+1.33 | 예 | 3 | 예 | 예 | 예 | 예 | r0 40/40, r1 40/40, r2 40/40 | 395.1 | 124.5 | 6 / 121.8 | 73 / 92 / 20 | 221.9 | 5.1 |
| n2 | 111 | 3 | r0:+0.97 r1:+0.87 r2:+0.96 | 예 | 4 | 예 | 예 | 예 | 예 | r0 40/40, r1 40/40, r2 40/40 | 389.7 | 126.9 | 6 / 124.3 | 91 / 110 / 20 | 214.1 | 5.2 |
| n3 | 113 | 3 | r0:+1.49 r1:+0.88 r2:+1.49 | 예 | 4 | 예 | 예 | 예 | 예 | r0 40/40, r1 40/40, r2 40/40 | 378.0 | 105.1 | 5 / 103.0 | 93 / 112 / 20 | 221.3 | 5.2 |
| n4 | 93 | 2 | r0:+0.89 r1:+0.88 | 예 | 3 | 예 | 예 | 예 | 예 | r0 40/40, r1 40/40, r2 40/40 | 392.9 | 127.7 | 6 / 125.4 | 73 / 92 / 20 | 215.3 | 5.8 |
| n5 | 93 | 3 | r0:+1.09 r1:+0.86 r2:+1.56 | 예 | 3 | 예 | 예 | 예 | 예 | r0 40/40, r1 40/40, r2 40/40 | 378.3 | 104.6 | 5 / 101.9 | 73 / 92 / 20 | 224.2 | 4.6 |

**예비 프로세스 등록 안 함** (`rs4_kill3_nospare@rs`, n=5)

| 시행 | hold 줄 수 | 거절 줄 있는 생존 rank | 풀린 생존 rank(kv) | 풀림 - 자기 죽음 판정 ms (r0,r1,r2) | 수신 시각: 풀림 - 첫 죽음 판정 ms | 조건 |
|---|---|---|---|---|---|---|
| n1 | 0 | 3 | 3 | 2005.8,2002.8,2006.2 | 2005.9,2002.9,2006.2 | 예 |
| n2 | 0 | 3 | 3 | 2004.7,2002.0,2002.4 | 2004.7,2001.6,2002.4 | 예 |
| n3 | 0 | 3 | 3 | 2004.3,2002.2,2004.5 | 2004.7,2002.3,2004.5 | 예 |
| n4 | 0 | 3 | 3 | 2002.4,2002.3,2004.6 | 2002.4,2002.4,2004.7 | 예 |
| n5 | 0 | 3 | 3 | 2004.0,2002.5,2004.1 | 2004.0,2002.6,2004.2 | 예 |

**예비 프로세스 등록 뒤 먼저 없어짐** (`rs4_kill3_spareabsent@rs`, n=5)

| 시행 | 예비 프로세스 먼저 kill | hold 줄 수 | fallback - hold 시작 ms (r0,r1,r2) | 풀림 - fallback ms | 풀림 - 죽음 판정 ms | 조건 |
|---|---|---|---|---|---|---|
| n1 | 예 | 6 | 1001.5,1002.3,1001.6 | 2003.6,2001.8,2002.6 | 3007.3,3005.8,3006.3 | 예 |
| n2 | 예 | 6 | 1001.6,1001.9,1001.3 | 2002.2,2001.5,2004.5 | 3005.8,3005.1,3007.9 | 예 |
| n3 | 예 | 6 | 1000.5,1000.9,1000.5 | 2002.1,2002.2,2001.3 | 3004.6,3004.8,3003.8 | 예 |
| n4 | 예 | 6 | 1002.8,1003.0,1002.1 | 2002.2,2001.2,2001.1 | 3006.9,3005.9,3005.6 | 예 |
| n5 | 예 | 6 | 1000.5,1001.5,1000.5 | 2003.0,2000.5,2001.8 | 3005.7,3003.8,3004.4 | 예 |

**복원 없는 빌드 대조** (`rs4_kill3@hk`, n=5)

| 시행 | hold 줄 수 | 거절 줄 있는 생존 rank | 풀린 생존 rank(kv) | 풀림 - 자기 죽음 판정 ms (r0,r1,r2) | 수신 시각: 풀림 - 첫 죽음 판정 ms | 조건 |
|---|---|---|---|---|---|---|
| n1 | 0 | 3 | 3 | 2004.6,2001.5,2004.7 | 2004.6,2002.4,2004.8 | 예 |
| n2 | 0 | 3 | 3 | 2002.3,2002.9,2004.3 | 2002.3,2003.1,2004.4 | 예 |
| n3 | 0 | 3 | 3 | 2004.5,2002.7,2004.2 | 2004.5,2002.9,2004.3 | 예 |
| n4 | 0 | 3 | 3 | 2004.3,2002.8,2003.0 | 2004.3,2003.0,2003.0 | 예 |
| n5 | 0 | 3 | 3 | 2003.5,2002.5,2002.3 | 2003.5,2002.7,2002.3 | 예 |

**장애 없음, 복원 켬** (`rs4_none@rs`, n=5)

| 시행 | 데이터 같음 | 복원 수 | 입력 멈춤 줄 | 입력 멈춤 최대 ms | 강제 strict MR | 강제 아님 MR | 어긋난 MR | rank별 MR 줄 |
|---|---|---|---|---|---|---|---|---|
| n1 | 예 | 0 | 348 | 5.3 | 16 | 0 | 0 | 4,4,4,4 |
| n2 | 예 | 0 | 348 | 5.3 | 16 | 0 | 0 | 4,4,4,4 |
| n3 | 예 | 0 | 348 | 5.6 | 16 | 0 | 0 | 4,4,4,4 |
| n4 | 예 | 0 | 348 | 5.2 | 16 | 0 | 0 | 4,4,4,4 |
| n5 | 예 | 0 | 348 | 5.5 | 16 | 0 | 0 | 4,4,4,4 |

**장애 없음, 복원 끔** (`rs4_none_off@rs`, n=5)

| 시행 | 데이터 같음 | 강제 strict MR | 강제 아님 MR | 어긋난 MR | rank별 MR 줄 |
|---|---|---|---|---|---|
| n1 | 예 | 0 | 16 | 0 | 4,4,4,4 |
| n2 | 예 | 0 | 16 | 0 | 4,4,4,4 |
| n3 | 예 | 0 | 16 | 0 | 4,4,4,4 |
| n4 | 예 | 0 | 16 | 0 | 4,4,4,4 |
| n5 | 예 | 0 | 16 | 0 | 4,4,4,4 |

**켤 수 없는 설정** (`rs4_refuse_symgin@rs`, n=3)

| 시행 | Resume rc (r0-r3) | 모두 오류 | 이유 같음 | 오류 없이 넘어간 rank |
|---|---|---|---|---|
| n1 | 5,5,5,5 | 예 | 예 | 0 |
| n2 | 5,5,5,5 | 예 | 예 | 0 |
| n3 | 5,5,5,5 | 예 | 예 | 0 |

**켤 수 없는 설정** (`rs4_refuse_gintype@rs`, n=3)

| 시행 | Resume rc (r0-r3) | 모두 오류 | 이유 같음 | 오류 없이 넘어간 rank |
|---|---|---|---|---|
| n1 | 5,5,5,5 | 예 | 예 | 0 |
| n2 | 5,5,5,5 | 예 | 예 | 0 |
| n3 | 5,5,5,5 | 예 | 예 | 0 |

**켤 수 없는 설정** (`rs4_refuse_restoreoff1@rs`, n=3)

| 시행 | Resume rc (r0-r3) | 모두 오류 | 이유 같음 | 오류 없이 넘어간 rank |
|---|---|---|---|---|
| n1 | 5,5,5,5 | 예 | 예 | 0 |
| n2 | 5,5,5,5 | 예 | 예 | 0 |
| n3 | 5,5,5,5 | 예 | 예 | 0 |

**켤 수 없는 설정** (`rs4_refuse_nomacro@rs`, n=3)

| 시행 | Resume rc (r0-r3) | 모두 오류 | 이유 같음 | 오류 없이 넘어간 rank | 이유에 매크로 | 끝까지 정확히 돎 |
|---|---|---|---|---|---|---|
| n1 | 5,5,5,5 | 예 | 예 | 0 | 예 | 예 |
| n2 | 5,5,5,5 | 예 | 예 | 0 | 예 | 예 |
| n3 | 5,5,5,5 | 예 | 예 | 0 | 예 | 예 |

**회귀, 장애 없음** (`reg_mr4_none@rs`, n=5)

| 시행 | outcome (r0-r3) | 종료 코드 | 조건 |
|---|---|---|---|
| n1 | ok,ok,ok,ok | r0rc=0 r1rc=0 r2rc=0 r3rc=0 | 예 |
| n2 | ok,ok,ok,ok | r0rc=0 r1rc=0 r2rc=0 r3rc=0 | 예 |
| n3 | ok,ok,ok,ok | r0rc=0 r1rc=0 r2rc=0 r3rc=0 | 예 |
| n4 | ok,ok,ok,ok | r0rc=0 r1rc=0 r2rc=0 r3rc=0 | 예 |
| n5 | ok,ok,ok,ok | r0rc=0 r1rc=0 r2rc=0 r3rc=0 | 예 |

**회귀, 장애 없음** (`reg_mr4_none_hold@rs`, n=5)

| 시행 | outcome (r0-r3) | 종료 코드 | 조건 |
|---|---|---|---|
| n1 | ok,ok,ok,ok | r0rc=0 r1rc=0 r2rc=0 r3rc=0 | 예 |
| n2 | ok,ok,ok,ok | r0rc=0 r1rc=0 r2rc=0 r3rc=0 | 예 |
| n3 | ok,ok,ok,ok | r0rc=0 r1rc=0 r2rc=0 r3rc=0 | 예 |
| n4 | ok,ok,ok,ok | r0rc=0 r1rc=0 r2rc=0 r3rc=0 | 예 |
| n5 | ok,ok,ok,ok | r0rc=0 r1rc=0 r2rc=0 r3rc=0 | 예 |

**회귀, rank 3 kill** (`reg_rm4_kill3_untimed@rs`, n=5)

| 시행 | rank 3 받기 오류로 풀린 생존 rank | 풀림 - 자기 죽음 판정 ms (r0,r1,r2) | 생존 rank 사이 보내기 정상 (/6) | 커널 끝난 생존 rank | 멈춘 생존 rank | 조건 |
|---|---|---|---|---|---|---|
| n1 | 3 | 2013.3,2006.4,2010.6 | 6 | 3 | 0 | 예 |
| n2 | 3 | 2010.0,2008.1,2012.1 | 6 | 3 | 0 | 예 |
| n3 | 3 | 2012.3,2008.3,2009.9 | 6 | 3 | 0 | 예 |
| n4 | 3 | 2012.0,2007.1,2008.9 | 6 | 3 | 0 | 예 |
| n5 | 3 | 2009.1,2008.0,2012.7 | 6 | 3 | 0 | 예 |

**회귀, rank 3 kill** (`reg_rm4_kill3_untimed_hold@rs`, n=5)

| 시행 | rank 3 받기 오류로 풀린 생존 rank | 풀림 - 자기 죽음 판정 ms (r0,r1,r2) | 생존 rank 사이 보내기 정상 (/6) | 커널 끝난 생존 rank | 멈춘 생존 rank | 조건 |
|---|---|---|---|---|---|---|
| n1 | 3 | 2011.0,2008.1,2009.4 | 6 | 3 | 0 | 예 |
| n2 | 3 | 2010.9,2008.4,2008.8 | 6 | 3 | 0 | 예 |
| n3 | 3 | 2011.8,2008.2,2010.4 | 6 | 3 | 0 | 예 |
| n4 | 3 | 2008.7,2008.4,2011.1 | 6 | 3 | 0 | 예 |
| n5 | 3 | 2012.0,2006.3,2009.9 | 6 | 3 | 0 | 예 |

## 3. 8절 확인

**제외: 77시행 가운데 0** `[측정: recount_rs.py의 excluded 열]`. 본 조건과 근거:

| 8절의 제외 조건 | 본 것 | 결과 |
|---|---|---|
| GIN 사용자 문맥 전에 끝남 (장애가 들어가지 않음) | 살아 있는 rank kv `devcomm_rc=0`; kill 셀은 meta `r<kr>rc=137`과 kill 줄(`_kill.out` 또는 시험 스위치 줄), 회귀 kill은 `_kill.out`의 `kill_mono_ms` | 해당 없음 (kill 시행 45개 모두 kill 들어감; raw의 35개에서 kill 줄 → 첫 죽음 판정 −0.0–0.4 ms, 수신 시각) |
| kill이 첫 확정 체크포인트 전 | 복원을 기대하는 kill 시행 20개(`rs4_kill3`, `rs4_kill1`, `rs4_kill3_ckpt`): kill 수신 시각 전에 생존 rank 셋 모두 `rank kr armed at its stable checkpoint k` 줄 | 20/20에서 셋 모두 있음 |
| 예비 프로세스가 활성화 전에 시작 실패 | meta `spare_wanted=1`인 25시행의 `spare_ready=1` | 25/25 |
| 링크가 한가하지 않음, 응답 쪽 GPU에 다른 사용자의 compute app | `hold_G1.out`, `hold_G2.out`, `hold_R1.out`의 `idle (rate=0Mb/s)`; raw meta `gpu_apps_before=0/0`(57/57); 각 hold의 snap 앞뒤에 GPU 사용자 줄 0 | 해당 없음 |
| 셀이 정한 빌드가 아닌 driver | meta `driver`가 `cells_rs.json`의 셀 driver와 같음; driver md5 앞자리가 7절과 같음(`gin_rs` 303e812d, `gin_rs_nomacro` 0f0826e6, `gin_rs_hk` 4ec9b846, `mr/ff` 41f3ce3a, `mr/hold` 169f59c5); 라이브러리 md5가 `rs_i5` 4811f28f…(72시행), 대조 5시행은 gpu-detect 배포 `hk` 2913c777…(9.15.6에 적힌 값) | 77/77 맞음 |
| smoke, pilot | 이 폴더에 없음 | 해당 없음 |

체크포인트 멈춤 중 kill 셀의 n4는 제외가 아니라 그 예측의 조건 불충족으로 셌다(8절 문장 그대로).

**STOP 파일.** `STOP_mlx5`, `STOP_cuda`, `STOP_left`, `STOP_nic` 없음; `skipped.txt`, `refused.txt`, `spare_wait.txt`도 없음 `[측정: ls]`.
세 hold 출력에 중단 줄 없음(`no further trial`, `grew`, `CUDA fault`, `left after` 0). 40개의 `Killed` 알림은 의도한 SIGKILL이다: rank 3 30개
(`rs4_kill3` 10, `rs4_kill3_ckpt` 5, `rs4_kill3_nospare` 5, `rs4_kill3_spareabsent` 5, 그 셀의 예비 프로세스 5), rank 1 5개, 대조 rank 3 5개.
kv와 로그에 `cuda_error=`, `watchdog=1`, `nccl_error=`, `illegal address`, `illegal memory access`, `unspecified launch failure` 0 `[측정: grep]`.

**QUERY_QP.** `qp_over.txt` 없음. 이 파일은 pilot hold에서만 쓰이고, 본 hold에서 시행 하나가 상한(복원과 거절 40 000, 회귀 150 000)을 넘으면
`STOP_mlx5`가 생긴다(`hold_rs.sh`의 `after_trial`). 그 파일이 없으므로 넘은 시행은 없다 `[추론: 스크립트 논리]`. 시행별 증가는 파일로 남지 않아
다시 셀 수 없다 `[미확인]`. hold 전체(앞뒤 snap의 `rain fwcmd QUERY_QP n`) `[측정]`:

| hold | 시행 | QUERY_QP 증가 | 시행당 평균 | 시행당 상한 |
|---|---|---|---|---|
| G1 | 45 | 693 156 | 15 403 | 40 000 |
| G2 | 12 | 33 168 | 2 764 | 40 000 |
| R1 | 20 | 1 974 288 | 98 714 | 150 000 |

**mlx5와 펌웨어 명령.** `mlx5_new_G1.txt`, `mlx5_new_G2.txt`, `mlx5_new_R1.txt` 모두 0줄. 세 hold 모두 rain mlx5 명령 오류 줄 2 → 2, sunny 0 → 0,
rain 펌웨어 명령 실패 합 31 → 31 `[측정: snap_before/after]`.

**남은 프로세스.** meta `left=0` 77/77, `LEFT_STREAK` = 0, hold 출력의 `left=` 77개 모두 0 `[측정]`.

**시행 시간.** meta `wall_s`: 복원 kill 10.5–10.6 s, fallback 10.0–10.1 s, fail-fast와 대조 5.0–5.1 s, 장애 없음 6.5–6.6 s, 거절 2.0 s(매크로 없는 셀
6.5 s), 회귀 17.5–17.6 s. 복원 시행 한도 60 s 안 `[측정]`.

**예측 밖의 관찰** (판정에 쓰지 않음).
1. 체크포인트 멈춤 중 kill의 시각 `[측정, 추론]`. 생존 rank의 입력 멈춤 줄은 "a hold of that rank took its gates"이고 hold 시작 줄도 게이트가
   이미 홀수였다고 하므로, hold가 진행 중인 멈춤을 넘겨받은 것은 맞다. 그러나 각 rank 자기 시계로 멈춤 시작(끝 `mono_ms` − `pause_us`)은
   자기 죽음 판정보다 rank 0에서 +0.89–+1.61 ms, rank 2에서 +0.96–+1.56 ms, rank 1에서 −0.04–+0.88 ms였고(멈춤 14개), rank 1(죽은 rank 3과
   같은 sunny 시계)의 멈춤 시작은 죽음 줄 `mono_ms` + 300 µs로 잡은 SIGKILL 순간보다 0.7–0.8 ms 뒤였다(그 줄을 kill 순간에 찍었다면 1.0–1.1 ms 뒤). 곧 kill은 rank 3이 멈춤 요청을 보낸 뒤
   300 µs에 들어갔지만 생존 rank는 그 요청을 죽음 판정과 같은 때나 그 뒤에 처리했다. 3절의 "생존 rank 셋이 모두 그 체크포인트의 입력 멈춤
   안"은 라이브러리 줄로는 참이고, kill 순간에 이미 멈춰 있었다는 뜻으로는 원자료가 받치지 않는다 `[추론]`. n4에서 짝 rank 2는 그때 자기
   체크포인트 92를 rank 3에 올리던 중이라("the buddy rank 3's helper socket could not be reached") 멈춤에 들지 않았다.
2. 복원 뒤 짝의 체크포인트 `[측정, 추론]`. 되살린 rank가 짝으로서 받는 체크포인트 올림을 모두 거절한다("an upload of rank 2's checkpoint N refused:
   the upload's base is not the stable image here"). 그래서 죽은 rank의 짝(rank 3이 죽으면 rank 2, rank 1이 죽으면 rank 0)은 복원 뒤 체크포인트가
   모두 void다: `checkpoints at close`의 void가 `rs4_kill3` rank 2에서 23(10/10), `rs4_kill1` rank 0에서 23(5/5), `rs4_kill3_ckpt` rank 2에서
   25–26(5/5); 다른 rank는 0이고 장애 없는 셀도 0이다. 그 짝은 복원에 참여해 스스로 DISARM을 보냈고 "다음 확정 체크포인트에서 다시 무장"되는데
   그 체크포인트가 오지 않으므로, 실행이 끝날 때까지 그 rank가 죽으면 복원이 아니라 거절로 갈 것이다 `[추론, 실행해 보지 않음]`. 한 번의 죽음만
   다루는 이 실험의 예측과 판정에는 닿지 않지만 한계에 적을 만하다.
3. hold 시작 줄의 `executed/sent at the hold: X/Y`는 그 rank의 첫 QP(context 0) 값만 보인다(rank 1, 2는 늘 0/0). 그래서 억제 예산의 생존 rank 쪽
   교차 확인은 rank 0 통로에서만 된다 `[측정]`.
4. kv `stable_last`는 rank의 자기 확정 체크포인트가 아니다(`rs4_kill3` n1의 rank 0은 132인데 그 rank의 `checkpoints at close`는 void 0,
   stable 29). 재계산에는 쓰지 않았다 `[측정; 뜻은 미확인]`.

## 4. `SCORE.md`와 견줌 (1–3절을 쓴 뒤에 처음 열었음)

`SCORE.md`가 보여 주는 것(예측별 판정, 셀별 k/n, 만족하지 않은 시행, 셀별 계획과 실행과 따로 센 시행)을 위 재계산과 견줬다.
`trials_scored.csv`는 열지 않았으므로 시행별 값(복원 시간 등)은 견주지 않았다.

**판정, k/n, 제외: 다른 곳 없음.** 판정한 예측 18개(셀이 여럿인 `refuse_reason`, `regression_none`, `regression_kill3`을 셀마다 나누면 23개)가 모두 맞음으로 같고,
k/n도 같다: `ckpt_kill` 4/5(만족하지 않은 시행 n4로 같음), 나머지는 셀마다 n/n. 따로 센 시행은 둘 다 0, 셀마다 계획, 실행, 판정 수
(10, 5, 3)도 같다. 비용 넷이 "자료 부족"(n 0)인 것은 채점 때 비용 hold가 아직 없었기 때문이고 이 재계산의 범위 밖이다.

**판정이 아닌 다른 곳 둘.**
1. `SCORE.md` 머리말은 "예측 파일 sha256: `752c8329…`. `PREREG.txt`의 값과 다르다(사전 등록 전)"라고 쓴다. 그러나 `PREREG.txt`의 줄이 바로
   `752c832926acf42a18a8b84482cc30119a283c0f6dfe7385894f516dfe26b596  …/impl/test/predictions_rs.csv`이고, 지금 파일의 sha256도 같은 값이다
   (`cells_rs.json`도 `99b7165c…`로 같음) `[측정: sha256sum, PREREG.txt]`. 곧 채점에 쓴 예측 파일은 사전 등록한 그 파일이고, 머리말의 "다르다"가
   틀렸다. 채점기가 `PREREG.txt`를 읽는 방식의 문제로 보인다 `[추론; score.py는 열지 않음]`. 같은 머리말의 "(work package 10, DRAFT)"와
   "문턱과 반복 수는 pilot 뒤에 고정한다"도 사전 등록 전의 문장이 남은 것이다.
2. `ckpt_kill`의 "만족하지 않은 시행"이 홈 디렉터리를 포함한 절대 경로로 적혀 있다. 주소는 아니지만 공개 문서로 옮길 때 줄기 이름
   (`rs4_kill3_ckpt_rs_n4`)만 쓰는 편이 낫다.

추가(비용 재계산 뒤, 6절): 위 두 점은 03:37:33에 만든 `SCORE.md`를 읽은 것이다. 03:44:46에 다시 만든 `SCORE.md`(시행 329 = 77 + 비용 252)에서는 둘 다
고쳐졌다: 머리말이 "`PREREG.txt`의 값과 같다"이고 DRAFT 문장이 없으며, 만족하지 않은 시행이 줄기 이름 `rs4_kill3_ckpt_rs_n4`로 적힌다.
판정 18개와 k/n은 새 `SCORE.md`에서도 위와 같다 `[측정: 다시 읽음]`.

이 밖에 `SCORE.md`가 주지 않아 견주지 못한 것: 체크포인트 멈춤 중 kill의 "멈춤 안" 정의(3절 관찰 1). 재계산은 라이브러리 줄로 셌고 n4 하나만
2/3이라 채점기와 같은 시행이 빠졌다.

## 5. 넘겨 줄 요약

본 실행의 복원, 거절, 회귀 셀 77시행을 채점기 없이 원자료(kv, 수신 시각 로그, meta, kill 줄)에서 다시 셌다. 제외는 0이고, 판정한 예측 18개가
모두 맞음으로 `SCORE.md`와 같다(체크포인트 멈춤 중 kill만 4/5, 빠진 시행 n4도 같음). rank 3 kill의 복원 시간은 278.0–397.9 ms(시행 10개),
억제는 통로 60개(rank 3 kill 30, rank 1 kill 15, 체크포인트 멈춤 중 kill 15) 모두 따로 센 X − P와 같았다. fail-fast와 대조의 풀림은 죽음 판정 2 001.5–2 006.2 ms 뒤, fallback은
hold 시작 1 000.5–1 003.0 ms 뒤였다. STOP 파일, `qp_over.txt`, 새 mlx5 줄, 펌웨어 실패 증가, 남은 프로세스는 없다. 판정이 아닌 것 셋을 올린다:
(1) 03:37 `SCORE.md` 머리말의 "예측 파일이 `PREREG.txt`와 다르다"는 틀렸다(두 sha256이 같음; 03:44:46의 `SCORE.md`에서 고쳐짐). (2) 체크포인트 멈춤 중 kill에서 생존 rank의 멈춤은
라이브러리 줄로는 진행 중이었지만 자기 시계로는 죽음 판정과 같은 때나 그 뒤(+0.9–+1.6 ms, rank 1은 −0.04–+0.88 ms)에 시작했다. 결과 문장에서
"kill 순간에 멈춰 있었다"고 쓰지 않는 편이 맞다. (3) 복원 뒤 죽은 rank의 짝은 남은 체크포인트가 모두 void(실행마다 23–26개)라 그 뒤 그 rank가
죽으면 복원되지 않을 것이다(실행해 보지 않은 추론). 한계로 적을 만하다.

## 6. 비용 hold 재계산 (8개, 252실행)

채점기와 `trials_scored.csv`는 열지 않았고 `SCORE.md`는 아래 표를 다 만든 뒤에 읽었다. 스크립트: `python3 recount_rs.py <results/20261013_main> out cost`
(실행별 `out/cost_runs.csv`, 요약 `out/cost_summary.txt`), 표는 `python3 table_md.py out/trials_recount.csv out/cost_runs.csv`(`out/cost_tables.md`).

**방법.**
- 폴더: `cost_log_{rain,sunny}_{lat4k,lat256k,bw256k}/`(팔 다섯 × 6라운드 = 30실행씩)와 `cost_ffbranch_{rain,sunny}/`(팔 셋 × 지표 둘 × 6라운드 = 36실행씩).
  hold마다 폴더가 하나이고 `_run<k>` 폴더는 없다. meta 없는 kv 0.
- 실행기(`run_cost.sh`): rank 0이 보내고 rank 1이 셀 이름의 노드에서 받는다. 그래서 지연 값은 보내는 rank 0의 kv(`…_r0.kv`)에 있다(메시지의
  "받는 rank의 kv"는 r0이 아니라 r1이다; 9.15.6과 실행기 머리말대로 r0의 값을 썼다).
- 값: `lat4k`, `lat256k` = r0 kv `lat_p50_us`(3 000반복의 put + 신호 + flush). `bw256k` = `burst_K` × `bytes` / r0 kv `lat_p50_us`(12번의 burst 반복 시간의
  p50; kv에 대역 키는 없음), GB/s(10^9 B/s). 실행기 머리말("bandwidth = burst_K x bytes / p50")과 9.15.6의 식 그대로다. 예: rain `off` k1은 8 × 262 144 B /
  384.00 µs = 5.461 GB/s.
- 유효 실행(9.15.6의 규칙): 두 rank kv `exit=0`, r0 `tx_done` = 반복 수, r1 `rx_done` = 반복 수, `nccl_error`, `cuda_error`, `watchdog` 없음, 두 rank
  `win_flags=0x3`, meta `rc_r0=0`, `rc_r1=0`, `left=0`, 팔의 라이브러리와 driver가 실행기의 짝과 같고 md5가 `PREREG.txt`와 같음(`rsp_i5` be91b270…,
  `hkp` 84209c03…, `gin_ts2`(매크로) dd44e14e…, `gin_ts2_ff` 5e4db845…, ord `gin_ts2` 64418f21…). 유효 실행이 5보다 적은 팔은 미완.
- 셀(노드 × 지표 × 팔)마다 유효 실행의 중앙값(6개라 가운데 둘의 평균)과 범위. 기준 팔(log는 `off`, ffbranch는 `ffb-hk`)에 대한 차를 기준 중앙값의 %로,
  나쁜 쪽이 양수(지연은 (팔 − 기준)/기준, 대역은 (기준 − 팔)/기준).
- 판정(3절과 `predictions_rs.csv`): 로그의 비용(`cost_log`)은 `on`, 무장 전 hold의 비용(`cost_unarmed`)은 `ua-hold`가 노드 둘 × 지표 셋 모두에서 나쁜 쪽
  10% 이하. fail-fast 분기의 비용(`cost_ff`)은 `ffb-rs`가 `ffb-hk`와 노드 둘 × 지표 둘 모두에서 갈리지 않음. 갈림 = 한 팔의 유효 실행 6개가 모두 다른
  팔의 6개보다 큼(같은 값은 갈리지 않음; 9.15.6). checksum(`sampled`, `full`)과 `ffb-rs-macro`는 보고만.

**유효성** `[측정]`: 252/252 유효(무효 0, 미완 셀 0). 셀마다 6실행.

**결과** `[측정: out/cost_runs.csv에서 다시 셈]`.
**log 가족** (받는 노드마다, 팔마다 유효 실행 6개의 중앙값과 범위; 지연 µs, 대역 GB/s; % = 기준 팔 off의 중앙값에 대한 나쁜 쪽 차)

| 노드 | 지표 | off | ua-hold | ua-hold % | on | on % | sampled % | full % |
|---|---|---|---|---|---|---|---|---|
| rain | lat4k | 11.260 (11.260–11.260) | 12.290 (12.290–12.290) | +9.15 | 12.290 (12.290–12.290) | +9.15 | +18.21 | +172.82 |
| rain | lat256k | 39.940 (39.940–40.960) | 42.495 (40.960–46.080) | +6.40 | 41.470 (40.960–45.060) | +3.83 | +17.93 | +2302.33 |
| rain | bw256k | 5.461 (5.461–5.476) | 5.319 (5.306–5.319) | +2.60 | 5.231 (5.224–5.238) | +4.21 | +49.77 | +97.49 |
| sunny | lat4k | 10.925 (10.780–11.070) | 12.380 (12.380–12.380) | +13.32 | 12.580 (12.580–12.610) | +15.15 | +46.18 | +195.84 |
| sunny | lat256k | 39.055 (38.940–39.070) | 40.930 (40.930–40.930) | +4.80 | 40.930 (40.770–40.960) | +4.80 | +16.23 | +2431.56 |
| sunny | bw256k | 6.445 (6.442–6.462) | 6.239 (6.233–6.240) | +3.20 | 6.126 (6.115–6.132) | +4.95 | +51.59 | +97.68 |

**ffbranch 가족** (지연 µs; % = 기준 팔 ffb-hk의 중앙값에 대한 차, 양수가 느림; 갈림 = 한 팔의 6개가 모두 다른 팔의 6개보다 큼)

| 노드 | 지표 | ffb-hk | ffb-rs | ffb-rs % | ffb-rs 갈림 | ffb-rs-macro (보고만) | ffb-rs-macro % | ffb-rs-macro 갈림 |
|---|---|---|---|---|---|---|---|---|
| rain | lat4k | 11.260 (11.260–11.260) | 11.260 (11.260–11.260) | +0.00 | 안 갈림 | 11.260 (11.260–11.260) | +0.00 | 안 갈림 |
| rain | lat256k | 40.450 (39.940–40.960) | 39.940 (39.940–40.960) | -1.26 | 안 갈림 | 40.450 (39.940–40.960) | +0.00 | 안 갈림 |
| sunny | lat4k | 10.560 (10.560–10.560) | 10.620 (10.620–10.660) | +0.57 | 갈림 | 10.940 (10.850–10.980) | +3.60 | 갈림 |
| sunny | lat256k | 38.910 (38.910–38.940) | 38.910 (38.910–38.940) | +0.00 | 안 갈림 | 39.070 (38.940–39.140) | +0.41 | 안 갈림 |

기준 팔과의 갈림(보고): log 가족에서 `on`과 `ua-hold`는 rain `lat256k` 둘만 갈리지 않고 나머지 다섯 셀에서 `off`와 갈린다. `sampled`, `full`은 열두 셀
모두 갈린다. 지연 값의 단위: rain이 받는 셀(보내는 rank 0은 sunny)의 지연은 약 1.02 µs 간격의 값만 나온다(11.26, 12.29, 13.31, …; 39.94, 40.96, …).
그래서 rain `lat4k`의 +9.15%(`on`, `ua-hold` 모두)는 한 칸(1.03 µs)이고 10% 문턱에 0.85%p 가깝다 `[측정; 칸의 까닭은 미확인]`.

**판정.**

| 무엇을 예측했나 (찾는 키) | 비교 | 판정 | 근거 |
|---|---|---|---|
| 로그의 비용: 로그 켬이 fail-fast보다 모든 노드와 지표에서 나쁜 쪽 10% 안 (`cost_log`) | `on` 대 `off`, 노드 둘 × 지표 셋 | 틀림 | sunny `lat4k` +15.15%(10.925 → 12.580 µs). 나머지 다섯은 +3.83–+9.15%. 3절이 미리 적은 대로 4 KiB에서 틀림(비용 pilot 2의 sunny 14.8%와 비슷) |
| 무장 전 hold의 비용: 10% 안 (`cost_unarmed`) | `ua-hold` 대 `off` | 틀림 | sunny `lat4k` +13.32%(10.925 → 12.380 µs). 나머지 다섯은 +2.60–+9.15% |
| fail-fast 분기의 비용 없음: 갈리지 않음 (`cost_ff`) | `ffb-rs` 대 `ffb-hk`, 노드 둘 × 지표 둘 | 틀림 | sunny `lat4k`에서 갈림: `ffb-hk` 6개 모두 10.56 µs, `ffb-rs` 10.62–10.66 µs(중앙값 +0.06 µs, +0.57%). 섞은 차례(k마다 팔 순서가 바뀜)의 6라운드 모두에서 `ffb-rs`가 높다. 나머지 셋은 갈리지 않음(차 −1.26–+0.00%) |
| checksum의 비용 (`cost_checksum`) | `sampled`, `full` 대 `off` | 보고만 | `sampled`: 지연 +16.23–+46.18%, 대역 −49.77%(rain), −51.59%(sunny). `full`: 4 KiB +172.82%, +195.84%; 256 KiB +2 302.33%, +2 431.56%(24–25배); 대역 −97.49%, −97.68% |
| (보고만) 매크로 빌드의 fail-fast | `ffb-rs-macro` 대 `ffb-hk` | 보고만 | sunny `lat4k` +3.60%(갈림), 나머지 셋 +0.00–+0.41%(갈리지 않음) |

`cost_ff`의 "틀림"은 사전 등록한 규칙(6 대 6 완전 갈림)대로다. 크기는 sunny가 받는 4 KiB에서 60 ns(+0.57%)이고, 9.15.6이 적은 우연 갈림 확률은 셀
하나에 2/924, 셀 넷 가운데 하나라도 갈릴 확률은 약 0.9%다 `[추론]`. 판정은 바꾸지 않고, 결과 문장에서 "잴 수 있는 차이가 있다(sunny 4 KiB, +0.06 µs)"로
적는 것이 맞다.

**hold 확인** `[측정: snap_before/after, hold_COST-*.out]`. 여덟 hold 모두 시작 때 `idle (rate=0Mb/s)`, 앞뒤 snap에 GPU 사용자 줄 0, 새 mlx5 줄 0
(`mlx5_new_COST-*.txt`), rain mlx5 명령 오류 2 → 2, sunny 0 → 0, 펌웨어 명령 실패 31 → 31, 실행마다 `left=0`(252개), 중단 줄 0, STOP 파일과
`skipped.txt` 없음. rain QUERY_QP 증가: log hold마다 +480(30실행), ffbranch hold마다 +576(36실행), 곧 실행마다 16(QP 감시 끔). hold 시간 151–182 s.

같은 chain이 비용 뒤에 G1, G2, R1을 다시 불렀다(`hold_G1-r2.out`, `hold_G2-r2.out`, `hold_R1-r2.out`). 셋 모두 시행 77개가 "already done"으로 건너뛰어
돈 시행은 0이고, `raw/`(598파일)와 `reg/`(190파일)는 그대로다 `[측정]`. 1–3절의 재계산은 바뀌지 않는다.

**`SCORE.md`(03:44:46)와 견줌.** 다른 곳 없음. 네 비용 예측의 판정(`cost_log` 틀림, `cost_unarmed` 틀림, `cost_ff` 틀림, `cost_checksum` 보고만)이 같고,
노드와 지표와 팔마다의 n(6)과 중앙값이 모두 같으며(소수 셋째 자리까지), 차의 %도 반올림 차이만 있다(`SCORE.md`는 소수 한 자리: 예 +9.1% 대 +9.15%).
갈림 읽기도 같다(`cost_ff`: sunny `lat4k`의 `ffb-rs`, `ffb-rs-macro`만 갈림). 셀마다 계획, 실행, 판정 수 12도 같고 따로 센 실행은 0으로 같다.
`SCORE.md`의 `cost_log`, `cost_unarmed` 표는 갈림을 적지 않는다(판정에는 쓰지 않으므로 영향 없음).
