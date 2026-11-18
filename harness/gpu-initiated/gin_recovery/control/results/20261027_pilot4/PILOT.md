# gin-control pilot 4 (2026-10-27 03:24–03:37, 채점 안 함)

반례 셀 둘(조용한 긴 계산 `gc4_quiet12000`, 멈춘 rank를 기다리는 정상 rank `gc4_gpuhang12000_waitpend_fence`; [../../impl/notes_counterexample.md](../../impl/notes_counterexample.md))을
새 driver(`gin_mi` 5bd02b27, 소스 a28df3fe)와 지금 라이브러리 pf2(gc 39024bef)로 실제 RNIC, launcher, 두 노드에서 처음 돌렸다. hold P5(셀마다 n 2)와, Codex 검토 지적 4가 요구한 대조로
같은 driver의 GPU hang 셀 `gc4_gpuhang12000_fence` n 1(`GC_WAITPEND` 없음)이다. pilot은 본 실험에 들지 않고 채점하지 않는다. 판과 셀 env는 [VERSIONS.md](VERSIONS.md), 앞선 Codex 지적의
재확인은 [RECHECK.md](RECHECK.md)다.

표시: `[측정]` 원자료에서 다시 셈, `[소스]` 코드를 읽음, `[추론]` 해석, `[미확인]` 확인 안 함. 시각은 모두 주입 줄(rank 3의 `GINRS gpuhang` 또는 `GINRS quiet` 줄) 뒤 ms이고,
sunny 쪽 줄은 meta의 노드 시계 차(왕복 0.17–0.19 ms)로 rain 시계에 옮겼다(스크래치 `events.py`, 이 폴더에 사본 [events.py](events.py)). 범위는 그 시행 안의 관측자 사이 최소–최대다.

## 시도

`harness/gpu-initiated/common/cluster_run.sh` 안에서 `chain_gc.sh` → `hold_gc.sh`로 돌렸고 STOP 규칙이 켜져 있었다. 시도 2번(한도 8), 클러스터 시간 약 11분(한도 2 h).

| 시도 | 시각 | hold | 시행 | 결과 |
|---|---|---|--:|---|
| [a1](a1/) | 03:24:56–03:30:20 | `P5` | 3 | 셀 B n1 뒤 **STOP_nic**(rank 3 kv `watchdog=1`) → 대조 hold 건너뜀. 기록은 [a1_STOP_nic.txt](a1_STOP_nic.txt) |
| [a2](a2/) | 03:32:19–03:37:43 | `P5`(이어 돌기, 파일 꼬리 `-r2`), `PCELL-gc4_gpuhang12000_fence` | 1 + 1 | STOP 0. 셀 B n2의 같은 줄은 [hang_watchdog.txt](hang_watchdog.txt)에 적힘 |

- 세 hold 모두 새 mlx5 커널 줄 0, rain 펌웨어 명령 실패 합 31 그대로, rain mlx5 cmd_err 2 그대로, 남은 프로세스 0, QUERY_QP 상한 넘음 0(`qp_over.txt` 없음) `[측정: snap, mlx5_new]`.
- launcher의 STOP 줄 0, launcher QP 잃음 0(다섯 시행 `la_stop_n` 0, `la_qp_err_n` 0) `[측정]`.

### 실행기 고침 (a1의 STOP, 한 번 다시 돌림)

- **원인.** 셀 B n1에서 rank 3은 펜스되지 않았다(아래 셀 B). GPU hang 스위치의 커널은 스스로 끝나지 않으므로 rank 3은 driver의 200 s watchdog으로 끝났고(`watchdog=1 exit=7`), `hold_gc.sh`의
  `after_trial`이 rank kv의 `watchdog=1`을 NIC 오류로 읽어 STOP_nic를 냈다. 생존 셋의 kv에는 오류 키가 없고(`xchg=released exit=4 tx_err=0`), 새 mlx5 줄 0, 펌웨어 실패 그대로였다 `[측정]`.
  이것은 이 셀의 측정된 결과이고 NIC 장애가 아니라서 실행기 쪽 문제로 보았다 `[추론]`.
- **고침**(`impl/test/hold_gc.sh` `after_trial`, +14줄): 시행 meta의 `subject_rank`가 가리키는 rank의 env에 `GC_GPUHANG_IT=`가 있고, 그 rank kv가 `watchdog=1`이며 `cuda_error=`, `nccl_error=`가 없을 때만
  STOP 대신 `hang_watchdog.txt`에 한 줄 적는다. 다른 kv와 다른 오류 키는 그대로 STOP이다. 확인 `[측정: 로컬 실행]`: `bash -n`, a1 시행 사본으로 함수만 돌려 기록 줄이 나고, 같은 kv에 `nccl_error=`를 더하면 STOP_nic.
- a1의 STOP 파일은 `a1_STOP_nic.txt`로 옮기고 같은 결과 폴더에서 다시 돌렸다(meta가 있는 시행은 건너뜀). [skipped.txt](skipped.txt)의 한 줄은 a1의 STOP 때 것이다.

## 시행마다

| 시행 | 시도 | wall | 끝 | 의심 줄(대상) | 판정 줄(대상) | hold | 펜스 | 복원 | 데이터 같음 |
|---|---|--:|---|---|---|---|---|---|---|
| `gc4_quiet12000_gc_n1` | a1 | 22.6 s | 모든 rank rc 0 | 0 | 0 | 0 | 없음 | 없음(예비 안 씀) | 1 |
| `gc4_quiet12000_gc_n2` | a1 | 22.6 s | 모든 rank rc 0 | 0 | 0 | 0 | 없음 | 없음(예비 안 씀) | 1 |
| `gc4_gpuhang12000_waitpend_fence_gc_n1` | a1 | 200.4 s | 생존 rc 4(released), rank 3 rc 7(watchdog) | 6(rank 1 셋, rank 3 셋) | 6(rank 1 셋, rank 3 셋) | 0 | 없음 | 없음(fallback) | 0 |
| `gc4_gpuhang12000_waitpend_fence_gc_n2` | a2 | 200.4 s | 같음 | 6(같음) | 6(같음) | 1(rank 1이 rank 3을, 0.8 ms 뒤 포기) | 없음 | 없음(fallback) | 0 |
| `gc4_gpuhang12000_fence_gc_n1` (대조) | a2 | 21.1 s | 생존 rc 0, rank 3 rc 137(펜스) | 3(rank 3) | 3(rank 3) | 3 | SIGKILL → FENCED | 됨 | 1 |

모든 시행의 `scored` 상태(제외 0), `inject_ok` 1, `probe_timeout_n` 0이다. 열 값은 `rows_gc.py`가 원자료에서 다시 셈한 것이다(시행 표 [a1/trials.csv](a1/trials.csv), [a2/trials.csv](a2/trials.csv)) `[측정]`.

## 셀 B: 멈춘 rank 3을 기다리는 rank 1 (n 2)

두 시행이 같은 길을 갔다. **지금 규칙은 정상 rank 1을 모든 관측자(rank 0, 2, 그리고 멈춘 rank 3 자신)가 멈춤으로 판정했고, 그 판정이 rank 3보다 먼저 나서 rank 3의 hold와 펜스를 막았다.
결과는 복원이 아니라 communicator 전체의 fallback이다** `[측정]`.

| 시각 (ms) | n1 | n2 |
|---|---|---|
| rank 1 긴 기다림 줄(걸음 156, dest 3, `wait_ms` 1 000) | 1 007.7 | 1 008.2 |
| rank 1 의심(종류 gpu, ctx 3), 관측자 | 2 037.3 (r3), 2 037.5 (r2), 2 041.0 (r0) | 2 063.6 (r2), 2 064.1 (r3), 2 065.4 (r0) |
| rank 3 의심(종류 gpu), 관측자와 ctx | 2 040.7 (r0, ctx 1), 2 041.7 (r2, ctx 0), 2 042.4 (r1, ctx 0) | 2 066.0 (r1, ctx 1), 2 066.1 (r0, ctx 0), 2 068.1 (r2, ctx 1) |
| **rank 1 판정**(STALL, 판정 표 14행, ctx 3) | **10 041.7 (r2), 10 042.3 (r3), 10 044.6 (r0)** | **10 067.4 (r3), 10 067.5 (r2), 10 068.5 (r0)** |
| rank 3 판정(STALL, 14행) | 10 044.6 (r2, ctx 0), 10 046.4 (r1, ctx 1), 10 048.3 (r0, ctx 1) | 10 069.6 (r1, ctx 0), 10 071.5 (r0, ctx 1), 10 071.5 (r2, ctx 1) |
| rank 3에 대한 생존 rank의 반응 | r0, r2: "declined without a hold (a degraded raise is scheduled (another death))", NOHOLD; r1: 거절 | r0, r2: 같은 NOHOLD; r1: hold 시작 10 074.8 → NOHOLD(r0)로 포기 10 075.6, FALLBACK |
| launcher FENCE / FENCED | 없음 | 없음 |
| 생존 셋 풀림(걸음 156, `released=1`, `tx_err=0`) | 12 047.9–12 052.8 | 12 073.5–12 077.5 |
| rank 1 기다림 끝(`result=released`) | 12 053.1 (`wait_ms` 12 045.4) | 12 077.7 (`wait_ms` 12 070.0) |
| rank 3 끝(launcher EXITED, 자기 watchdog) | 197 281.0 | 197 295.6 |

- **누가 먼저.** rain의 두 관측자(r0, r2)는 두 시행 모두 rank 1을 rank 3보다 2.9–4.0 ms 먼저 판정했다(관측자 넷의 차). 첫 판정이 "degraded raise"를 잡아 두므로 뒤의 rank 3 판정은 hold 없이
  거절됐다 `[측정: r0, r2 로그]`. 첫 의심도 rank 1이 rank 3보다 3.4 ms(n1), 2.4 ms(n2) 일렀다. 왜 그런지는 보지 않았다 `[미확인]`.
- **rank 1은 펜스되지 않았다**(`waiter_fenced` 0, launcher FENCE 줄 0). rank 1의 예비 프로세스가 없어(`SPARE_RANK` 3) rank 1 판정은 처음부터 거절이다 `[추론: "declined … QPs left in ERR" 줄]`.
  rank 1 대상 hold 0, 포기 0(`waiter_hold_n` 0, `waiter_given_up_n` 0).
- **hold.** n1은 hold가 하나도 서지 않았다(`hold_any_n` 0). n2는 rank 1이 rank 3을 hold했다가(그때 rank 1은 아직 자기에 대한 판정 줄을 쓰기 전) rank 0의 NOHOLD로 0.8 ms 만에 포기했다(`hold_any_n` 1).
  rank 1의 창 줄 하나: `window check after the judgement of rank 3: changed=0 … base=judgement sample=hold_end`(`win_verified` 0: 셋 가운데 한 줄) `[측정]`.
- **rank 3은 복원되지 않았다.** 펜스가 없어 rank 3은 GPU에서 돈 채 driver watchdog(200 s)까지 살았고, 예비 프로세스는 활성화 대기 한도(60 s)마다 끝나 launcher가 세 번 다시 띄웠다(모두 안 쓰임) `[측정: launcher_sunny.log]`.
  생존 셋은 첫 판정 2 000 ms 뒤 degraded로 풀려 걸음 156에서 오류로 끝났다(`xchg=released`, rc 4) `[측정]`.
- **rank 1의 `tx_err`와 flush.** 칸 기다림은 abort 검사로 풀렸고(`waitpend_released=1`) 그 걸음의 flush는 건너뛰었다(설계대로) `[소스: notes_test.md 끝 절]`. 풀림 줄 `tx_err=0`, kv `tx_err=0 rx_err=0` `[측정]`.
  복원이 없어 "복원 뒤 다시 내기와 poll 안 된 WQE의 맞물림"은 이 pilot에서 볼 수 없었다 `[미확인]`.
- **멈춘 rank 3도 판정한다.** rank 3의 호스트는 살아 있어 rank 1을 의심, 판정하고 STALLED를 방송했다(두 시행 모두) `[측정]`.
- **rank 3 로그 100 MB.** 풀린 뒤 rank 3의 호스트가 `ncclCommGetAsyncError`를 되풀이해 "GIN Error detected" WARN 줄이 시행마다 692 247, 693 303줄(로그 1 384 961, 1 387 073줄)이다 `[측정]`.
  이 폴더에는 가린 뒤 gzip한 `_r3.log.gz`로 둔다.

## 셀 A: 조용한 긴 계산 (n 2)

- rank 3의 모든 CTA가 걸음 155 첫머리에서 12 001.2 ms, 12 001.1 ms 돌았다(`GINRS quiet` 시작과 끝 줄 모두 있음) `[측정]`.
- 네 rank 모두 의심 줄 0, 판정 줄 0, 거절 0, hold 0(rank마다 8개 로그에서 SUSPECT, STALLED, judged dead, hold 줄 0; `suspect_any_n` 0, `judge_any_n` 0, `decline_n` 0, `hold_any_n` 0) `[측정]`.
- `quiet_periods` 114, 115(창 안의 온전한 주기 `P_w` 119, 관측자마다 조용하지 않은 문맥 READ 4–5) `[측정: quiet_lb_detail]`. 하한 100에 14–15 여유다.
- 데이터 같음(`ow_data_equal` 1, `data_equal` 1), 재실행 없음, 예비 프로세스 안 쓰임(`spare_used` 0, launcher의 끝 SIGKILL로 rc 137), READ 성공 100 %, `tcp_ctrl_bytes` 0, `witness_pairs` 6/6 `[측정]`.
- **걸음 155의 체크포인트 라운드.** 체크포인트는 20걸음마다라 걸음 155에서 열린 라운드는 없다. 140의 라운드가 창 앞에, 160의 라운드가 창 끝 뒤에 끝났고, 모든 rank가
  `checkpoints at close: taken=30 stable=30 void=0`이다(두 시행) `[측정]`. 2 000 ms 한도로 버린 라운드 0.
- **`GC_WAITPEND`의 걸음 시간 비용.** 걸음 20–150의 걸음당 시간은 셀 B 7.850–7.871 ms, 셀 A와 대조 7.835–7.855 ms다(rank 0, 1; 시행 둘 대 셋). 차 약 0.02 ms(약 0.2 %) `[측정]`.

## 대조: 같은 driver의 GPU hang 셀 (`GC_WAITPEND` 없음, n 1)

- 의심은 rank 3 하나만(관측자 셋, ctx 0, 2 029.2–2 032.1 ms), 판정 10 032.7–10 035.9 ms(STALL, 14행), hold 셋 10 036.3–10 041.2, launcher FENCE 10 041.9, FENCED 10 145.7(SIGKILL 뒤 103.8 ms),
  활성화 ACCEPTED 10 147.8, 창 줄 셋 `base=fenced sample=rejoin changed=0`, 복원 10 215.6–10 216.5 ms, 데이터 같음 `[측정]`.
- rank 3이 아닌 rank에 대한 의심과 판정 0(`suspect_any_n` = `suspect_n` 3) `[측정]`. 판정 시각은 pilot 1, 2와 smoke의 GPU hang 다섯 시행 10 028.9–10 086.8 ms의 띠 안이다.
- 그래서 새 driver 바이너리 자체는 GPU hang 셀을 바꾸지 않았고(n 1), 셀 B의 연쇄는 rank 1의 `GC_WAITPEND`가 만든 것이다 `[추론: 같은 바이너리, env 하나 차이]`. 다만 Codex 지적 4가 함께 요구한
  "같은 수정 driver와 옛 라이브러리"의 비교는 이 pilot 범위 밖이다(라이브러리는 pf2 하나).

## 두 예측이 이 시행에서 읽히는 것 (채점 아님)

`score_gc.py`를 세션 스크래치 사본에서 pilot 표시를 끄고 계획 n을 있는 시행 수로 둔 채 돌렸다(pilot 3의 `score_pilot.py`와 같음; 채점기는 HEAD 1f3e8ebf, 바꾸지 않음). 출력 전부는
[score_v0/](score_v0/)이다. 채점기를 고친 것이 없어 `score_v1/`은 없다.

| 예측 (ID) | 무엇을 예측했나 | 이 pilot에서 | 시행 조건 |
|---|---|---|---|
| 조용한 긴 계산은 판정하지 않음 (`quiet_compute_no_judge`, safety) | 의심, 판정, 거절, hold, 예비 사용 0, `quiet_periods` ≥ 100, 데이터 같음; 모든 채점 시행 | 두 시행 모두 참 | 2/2 (사본에서 "맞음", 계획 5) |
| 지금 규칙은 기다리는 정상 rank도 판정함 (`waiter_old_rule`, perf) | rank 1을 판정한 관측자 ≥ 1, hang 줄 → 첫 판정 10 000–12 500 ms; ≥ 4/5 | 10 041.7 ms, 10 067.4 ms(관측자 3, 3) | 2/2 (n < k라 "자료 부족(n<k)") |
| 멈춘 GPU의 펜스(셀 B에 셀마다) (`gpuhang_fence_restore`) | 생존 셋 모두 STALL 판정 10 000–10 500 ms, SIGKILL 펜스, FENCED, 창 검사, 붙잡힘, 데이터 같음, 복원; 셀마다 ≥ 4/5 | 셀 B: rank 3 판정은 띠 안(10 044.6–10 071.5 ms)이나 펜스, FENCED, 붙잡힘, 복원 없음. 대조 셀: 참 | 셀 B 0/2, 대조 1/1 |

- 셀 B 두 시행은 제외되지 않고 채점 상태라 복원 실패가 실패로 셌다(RECHECK.md 3). 사본 출력은 셀 B의 안전성 항 다섯(`fence_order_ok`, `ow_data_equal`, `revived_done`, `wait_held`, `win_verified`)이
  2/2 거짓이라 본 실행이면 이 행이 "재검토(안전성 항 어긋남)"로 나온다. 이 거짓은 데이터가 틀린 것이 아니라 fallback으로 복원이 없었기 때문이다(아래 문제 2).
- 셀 B의 두 시행은 `no_tcp_control`의 `build:gc` 묶음에서 자료 부족 시행이다(rank 3 제어 요약 없음, `ctrlsum_missing=r3`). 그 묶음은 채점 5 가운데 자료 있는 3으로 판정됐다(RECHECK.md 2).

## 문제 (고치지 않음; 라이브러리는 보고만)

1. **[라이브러리, high] 정상 대기자의 판정이 실제 장애의 복원을 막는다.** 지금 규칙은 rank 1(멈춘 rank 3으로 post했으나 poll하지 않은 put을 둔 채 기다림)을 rank 3과 거의 같은 때 판정하고(4/4 관측자-시행에서 먼저),
   첫 판정의 degraded raise 때문에 rank 3은 hold 없이 거절된다. 결과는 펜스 없음, 복원 없음, communicator fallback, 멈춘 프로세스가 GPU에서 watchdog까지 삶(2/2). 설계가 예상한 "rank 3의 복원과 경쟁하는 거짓 교체"보다 나쁘다.
   최소 고침의 방향(결정 필요): 판정 표가 후보(먼저 선 상대)를 목적지로 둔 문맥 원소를 판정에서 빼는 것(notes_counterexample.md 대안 다, Codex 지적 일곱이 요구 사항), 또는 그 전까지 이 셀의 주장을
   "fallback(오류 보고)으로 끝남"으로 바꾸는 것.
2. **[채점기 읽기, 결정 필요] fallback 시행의 안전성 항.** perf 행 안의 안전성 항이 "복원이 없었음"을 "안전성 어긋남"으로 센다(빈 `fence_order_ok`는 활성화가 없었다는 뜻인데 `== 1`이 거짓). 8절 규칙이라 채점기는 그대로 두었다.
   최소 고침: 안전성 항을 그 항이 지키는 동작이 일어난 시행에서만 보거나(활성화가 없으면 `fence_order_ok`는 해당 없음), 셀 B의 `gpuhang_fence_restore` 기대를 바꿈.
3. **[셀 값] 셀 B의 `bound_s` 60이 실제 시행 200.4 s와 맞지 않는다.** `hold_gc.sh`의 `fits`는 bound로 840 s 안을 어림하는데, 본 실행 hold C10의 셀 B 다섯 시행만으로 약 1 000 s라 hold의
   `timeout -s KILL 880`에 걸릴 수 있다 `[추론]`. 최소 고침: `cells_gc.json` 셀 B의 `bound_s`를 약 230으로(또는 그 셀만 `WATCHDOG_S`를 줄임), 본 실행 시간 어림에 셀 B 다섯 × 약 200 s를 더함.
4. **[라이브러리 또는 driver] fallback 뒤 멈춘 rank의 WARN 줄 넘침.** 시행마다 약 69만 줄, 로그 약 100 MB. 본 실행 셀 B 다섯이면 약 500 MB다. 최소 고침: 오류 WARN을 communicator마다 한 번으로, 또는 driver의 오류 확인 간격을 늘림.
5. **[채점기 보고 열] 펜스 없는 시행의 `t_fenced_ms`.** 셀 B n2는 펜스가 없는데 창 줄로 `t_fenced_ms` 10 076.5(`t_fenced_src` `window_judgement`)가 찬다. 쓰는 예측은 없다.

## 하지 않은 것

- 같은 수정 driver와 옛 라이브러리의 대조(Codex 지적 4의 둘째 반쪽), 상대마다 나눈 정체 규칙(후속).
- 셀 B에서 복원 뒤의 `tx_err`와 flush 맞물림: 복원이 없어 볼 수 없었다.

원자료는 `aN/raw/`(IPv4 가림; 5 MB 넘는 rank 3 로그 둘은 가린 뒤 `.gz`), 시행 표는 `aN/trials.csv`, 사슬 기록 [chain.out](chain.out), 시도 기록 [attempts.txt](attempts.txt), 배포 출력 [deploy.txt](deploy.txt)다.
IPv4 꼴 0건, 관리망 주소 0건 `[측정: grep, gz는 zcat]`.
