# gin-control pilot 2 (2026-10-23 23:13–23:40, 채점 안 함)

2026-10-24 사전 등록 전 확정에서 바뀐 셀 여덟, 비용 팔 둘을 노드마다 두 묶음, gin-mirror 회귀 hold 여덟(`RG-gc-*`)의 pilot 꼴을 셀마다 n 1로 돌렸고 `gate_fenced`를 로컬 CPU에서 돌렸다.
pilot은 본 실험에 들지 않고 채점하지 않는다. 아래 "규칙" 열은 `score_gc.py`를 세션 스크래치 사본(`agent_gc_pilot2/sc/`)에서 pilot 표시를 끄고 계획 n을 있는 시행 수로 둔 채 돌린 결과다(`agent_gc_pilot2/score_pilot.py`, pilot 1의 것과 같음).
판정이 아니라 예측의 시행 조건이 이 시행에서 참인지만 본 것이다. 예측 표는 그때 worktree의 `predictions_gc.csv`(md5 `f6780b42`, 커밋 `2bbdcfca`의 credit 행 바뀜 포함), `score_gc.py` `05d979d5`, `rows_gc.py` `8b91ec1f`, `cells_gc.json` `69af9e3c`이다.
표시: `[측정]` 원자료에서 다시 셈, `[소스]` 코드를 읽음, `[추론]` 해석, `[미확인]` 확인 안 함. 시각과 열은 모두 `rows_gc.py`가 원자료에서 다시 셈한 값이다.

## 빌드와 배포

- 스크래치 트리 `agent_gc_p2a2/nccl-src`: HEAD `e791639` "gin-control: gcp prints the probe summary at WARN", 작업 트리 깨끗함, ln4 `f53e5d2` 대비 patience diff md5 `393ed485` = [../../impl/gc_layer_int.diff](../../impl/gc_layer_int.diff) `[측정]`.
- 라이브러리는 다시 빌드하지 않았다. `chain_sf1.sh`의 출력 md5가 지시와 같다 `[측정]`.

| 무엇 | md5 | 비고 |
|---|---|---|
| libnccl `gc` | `c128c4c891555f194240d371410c7f68` | `out/gc_sf1`(= `build/lib`) |
| libnccl `gcp` | `60e5a9f7b219493e0f6430d8f66de8ca` | `out/gcp_sf1`(= `build-gcp/lib`) |
| libnccl `gct` | `8ea3e598f9f77122738aabee7e189393` | `out/gct_sf1`, 이번에 쓰는 셀 없음 |
| `gin_mi` | `31a0704125b9e68e854d6e97afb19702` | `impl/test/driver/build_driver_gc.sh mi`(`MIOUT=mi_pl2`), `gin_mi.cu` `6cb4ff28`, 머리 digest `65fdf19b`, lib `gc_sf1` |
| `gin_mi_nomacro` | `83d55087b4894bd6c2a37e80947147a2` | 같은 `gin_mi.cu`를 매크로 없이(R3, `rs4_refuse_nomacro`) |
| `mr/ff/gin_mr`, `mr/hold/gin_mr` | `cc96215e…`, `493533bb…` | gin-remaining `gin_mr.cu` `a6a526ad`, 회귀 R1 |
| `gin_ts2_mi` | `7a47cb3b29eafd2dce79c02c784f0f47` | pilot 1의 `build_cost_pl1.sh`와 같은 단계, lib `gcp_sf1` |
| `gin_launcher` | `d1aceaf68f00d99eafa4d585195f3348` | smoke 6, pilot 1과 같음 |

- 셋째에서 다섯째 줄은 스크래치 `agent_gc_pilot2/build_extra_pl2.sh`(컴파일만, gc 트리 설치 머리의 사본)로 빌드했다. 출력 `agent_gc_pilot2/drv/build.txt`.
- **배포.** 묶음 `~/rs-bundle/gc_pilot2/`를 `impl/test/deploy_gc.sh`로 배포했다. 두 노드의 새 파일 md5가 서로 같고 원본과 같으며, ldd는 묶음의 libnccl을 가리킨다. 다른 묶음의 기존 파일(rain 960, sunny 1 015)은 바뀌지 않았다. 출력은 [deploy.txt](deploy.txt)다 `[측정]`.

## 시도

`harness/gpu-initiated/common/cluster_run.sh` 안에서 `chain_gc.sh` → `hold_gc.sh`로 돌렸고 hold의 STOP 규칙이 켜져 있었다.
- 시도는 7번(한도 12)이다. 클러스터 시간은 23:13:22–23:39:58, 약 27분이고 hold 자체는 합 1 278 s다.
- 모든 hold의 새 mlx5 커널 줄은 0, rain 펌웨어 명령 실패 합은 31 그대로(스냅숏 14개), 남은 프로세스 0, QUERY_QP 상한 넘음 0(`qp_over.txt` 없음) `[측정]`.

| 시도 | hold | 시행 | 결과 |
|---|---|--:|---|
| [a1](a1/) | `PCELL-`(바뀐 셀 여덟) | 8 | 통과 |
| [a2](a2/) | `COSTPILOT-sunny-2` | 4 | 통과 |
| [a3](a3/) | `COSTPILOT-rain-2` | 4 | 통과 |
| [a4](a4/) | `PRG-gc-G1+G3` | 5 | **STOP_launcher**: `mi4_kill2_kill3_ow`의 launcher 기록 QP 잃음 줄 2(아래 문제 4). 남은 11셀 건너뜀 |
| [a5](a5/) | `PRG-gc-G1+G3` 다시(한 번) | 11 | 통과. STOP 파일은 [a4/stopped_a4_PRG-gc-G1+G3_launcher.txt](a4/stopped_a4_PRG-gc-G1+G3_launcher.txt)로 옮겼고, 실행기 고침(아래) 뒤 이어 돌림 |
| [a6](a6/) | `PRG-gc-T1+T2+G2+R1` | 10 | 통과. 두 죽음 학습 셀의 같은 줄 2는 [a6/la_qp_twokill.txt](a6/la_qp_twokill.txt)에 기록만 |
| [a7](a7/) | `PRG-gc-R2+R3` | 13 | 통과 |
| [local](local/) | `gate_fenced`(CPU) | 10 + 10 | 아래 |

시도 기록의 첫 STOP 줄은 "attempt 5"로 잘못 적었고 바로 뒤 줄에서 a4로 고쳤다([attempts.txt](attempts.txt)).

## 바뀐 셀 (a1, n 1씩)

시각표는 주입 줄 뒤 ms이고 대상 노드의 생존 rank 기준이다: 의심 / 판정 / hold 시작 / 펜스 / 게시 / 첫 걸음. 모든 시행의 사본 상태는 "채점"(제외 0, STOP 0)이다.

| 셀 | 판정 원인 | 시각표 (ms) | 자료 | 규칙(시행 하나) |
|---|---|---|---|---|
| `gc4_none_probe` | 판정 0, 의심 0 | – | `STEPS` 6 000 등록되고 끝까지 돎(wall 62.6 s); 페이지 READ 7 296, 장치 줄 READ 29 136, 성공 100 %, 박동 간격 최대 1.097 ms, 데이터 같음, 입력 멈춤 16.526 ms | 장애 없음의 조용함(`none_probe_clean`) **어긋남**: `ckpt_pause_ms <= 16`만 거짓(16.526) |
| `gc4_freeze12000_fence` | STALL_HELPER ×3 | 2 003.0 / 10 006.3 / 10 011.1 / 10 164.5 / 10 207.8 / 10 366.9 | 판정은 FREEZE_PAGE 줄 뒤 10 006.3–10 009.5 ms, launcher SIGKILL → FENCED 148.1 ms, 복원, 데이터 같음; 창 줄 3개 모두 `changed=2, 1, 2` | 살아 도는 프로세스의 펜스(`freeze_fence_restore`) **어긋남**: `win_verified == 1`만 거짓(문제 1) |
| `gc4_helper_freeze12000` | STALL_HELPER ×3 | 2 004.3 / 10 008.0 / 10 012.3 / 10 132.6 / 10 175.4 / 10 262.8 | 판정 10 008.0 ms, SIGKILL → FENCED 117.9 ms, 복원, 데이터 같음; 창 `changed=1, 1, 1` | helper 멈춤의 펜스(`helper_stall_fence`) **어긋남**: 같은 항(문제 1) |
| `gc4_fdhold_sock_kill3` | EXITED ×3 | 60.8 / 60.9 / 65.9 / 65.4 / 106.5 / 299.3 | kill → 판정 60.789–60.870 ms, 복원 76.0 ms, 데이터 같음 | FIN 없는 죽음의 launcher 보고(`finless_exit_report`, 40–200 ms) 맞음 |
| `gc4_stop12000_none` | STALL_HELPER ×3 | 2 087.7 / 10 091.9 / – | 거절 16, `surv_released` 4(생존 3 + rank 3), `subject_fenced` 0, 멈춤 길이 어긋남 11.957 ms | 펜스 끈 긴 멈춤(`stall_none_refuse`) 맞음 |
| `gc4_kill3_ow_spareabsent` | FIN+STALE ×3 | 0.3 / 20.7 / 24.8 / 131.2 / – | 간격 5.020 ms(한도 10 ms 안, 제외 아님); FENCED → fallback 2.4 ms, `surv_released` 3; launcher 까닭 "could not hand over to the spare" | 예비 프로세스 없음의 fallback(`spare_absent_refused`) **어긋남**: 까닭 낱말만(문제 2) |
| `gc4_credit_stall` | 판정 0 | – | `sendq_max` 0, `sendq_deferred` 0, `records_lost` 0, `records_dup` 0, RNR 0, 모든 rank 끝까지(`surv_unfinished` 0), 입력 멈춤 396.6 ms(멈춤 500 ms), 데이터 같음 | credit 멈춤에도 잃음 없음(`credit_stall_no_loss`, 2bbdcfca의 행) 맞음; 창은 이번에도 차지 않음 |
| `gc4_qperr_record` | 판정 0 | – | QP_ERR 주입, 대상이 PAIR를 보냄, `qperr_rec_gen_delta` 1(채점기 고침 뒤), READ QP 세대 그대로, 그 쌍 READ 실패 0, 뒤 기록 151, 데이터 같음 | 기록 QP 오류의 다시 짝 맺기(`qp_err_repair`) 맞음 |

- freeze 둘은 pilot 1(판정 전에 끝남)과 달리 `@2000`, `STEPS` 3 000으로 판정, 펜스, 복원까지 갔다 `[측정]`. 판정은 FREEZE_PAGE 줄 뒤 10 006–10 010 ms로 띠 10 000–10 300 ms 안이다.
- ring live는 시행 여덟에서 1 006.4–1 081.1 ms(`LIVE_BOUND_MS` 10 000 안), READ 지연 최대 16.5–31.5 ms(pilot 1 문제 9와 같은 꼴) `[측정]`.

## 비용 팔 (a2, a3; 팔마다 노드마다 두 묶음, 150 000회)

| 수신 노드 | 팔 | 묶음 | p50 (µs) | 평균 (ns) | kernel (ms) | `cost_valid` | `cost_probe_evidence` | `cost_probe_inwindow_lb` / 기대 |
|---|---|---|--:|--:|--:|---|---|---|
| sunny | probe-off | k1, k2 | 12.704, 12.608 | 12 902.0, 12 834.9 | 2 122.2, 2 110.4 | 1, 1 | ok, ok | – |
| sunny | probe-on | k1, k2 | 12.832, 12.768 | 12 960.4, 12 907.0 | 2 130.7, 2 122.5 | 1, 1 | ok, ok | r0 71, r1 71 / 52 |
| rain | probe-off | k1, k2 | 13.312, 13.312 | 12 861.3, 12 841.4 | 2 106.2, 2 104.0 | 1, 1 | ok, ok | – |
| rain | probe-on | k1, k2 | 13.312, 12.288 | 12 826.3, 12 806.7 | 2 101.2, 2 098.0 | 1, 1 | ok, ok | r0 71, r1 71 / 50–52 |

- p50은 `score_gc.py`가 쓰는 시행 값(`value`)이고, 평균과 p50은 `lat_raw.csv.gz` 150 000개에서 다시 셌다(같은 값) `[측정]`. 고친 `gcp`가 READ 요약과 status page 줄을 WARN으로 내 probe-on 팔의 증거가 처음으로 섰다(창 `covers`).
- **sunny 수신(판정 노드).** 팔마다 두 묶음의 중앙값: probe-off 12.656, probe-on 12.800 µs, 차 +0.144 µs = **+1.14 %** `[측정]`.
  - 같은 팔 두 묶음 사이 퍼짐: probe-off 0.096 µs(0.76 %), probe-on 0.064 µs(0.50 %).
  - 리뷰 D8 권고 문턱 max(2 %, probe-off 퍼짐 × 2 = 1.52 %)는 2 %다 `[추론: 두 묶음뿐]`.
- **rain 수신(보고만).** 값이 1 024 ns 단위(값 13–14가지)라 p50이 12 288 또는 13 312로만 나온다. 평균 차는 −0.2 % 남짓이다 `[측정]`.

## 회귀 hold의 pilot 꼴 (a4–a7, 셀마다 n 1, 시행 39)

- 돈 것: G1 7, G3 9, T1 2, T2 1, G2 3, R1 4(gin-remaining 실행기), R2 7, R3 6. rdma 빌드 `gc`, 증인 켬.
- 상태 `[측정]`: 채점 31, `launcher_changed` 제외 2(두 죽음 셀, 문제 4), `prep_failure` 6(거절 셀 `mi4_refuse_*` 셋, `rs4_refuse_gintype`, `rs4_refuse_restoreoff1`, `rs4_refuse_symgin`). 거절 셀은 모두 기대한 까닭으로 Resume이 거절됐고(`resume_why_refused`, 7셀), 이 실험의 예측은 그 셀을 쓰지 않는다.
- gin-mirror 규칙(`regression_rdma`, `regression_rdma_mirror_off`)의 시행 조건 `[측정: agent_gc_pilot2/mirror_check.py]`: 자료가 있는 규칙 열한 개(대기 붙잡힘, 데이터 같음, 재실행 없음, 되살린 rank가 끝까지, 억제 정확, 내용이 pool에서 옴, 체크포인트 중 kill, rank 1 kill, 학습 데이터 같음, mirror 끈 데이터 같음과 재실행 없음)가 모두 1/1이다. `score_gc.py`의 "틀림"은 gin-mirror의 k(≥ 9 또는 ≥ 4)를 n 1에 댄 것이라 뜻이 없다.
- mirror 끈 길의 이미지 바이트 0과 데이터 같음(`rs4_kill3`, `rs4_kill3_ckpt`, `rs4_kill1`, `rs4_none`): 모두 1/1.
- **두 죽음 셀 둘은 둘째 죽음이 복원되지 않았다**(문제 3). 다시 이미지(`reimage_ok`) 1, 첫 복원 176.0 ms(4 KiB), 254.0 ms(학습); `second_ok` 0, `wait_held` 0, 데이터 다름.
- R1의 네 시행은 gin-remaining 실행기로 돌았다(launcher 없음, 남은 프로세스 0; kill 셀은 생존 rank `exit=4`). 이 실험의 예측은 이 셀을 쓰지 않는다.

## gate_fenced (로컬 CPU)

- `gate_proc_gc.py --trials 10`: 실제 자식 프로세스 10개에서 둘째 thread 끝 500.04–500.43 ms, pidfd 읽힘 500.66–501.81 ms, Z 0.38–0.43 ms(주 thread 끝 뒤). `--gate-bin`이 없어 관문 열(`old_go_ms`, `fenced_go_ms`)은 빈칸이고 규칙은 0/10, 판정은 자료 부족이다 `[측정: local/gate_proc.log]`.
- `gate_fenced.cc` 단위 프로그램(`out/unit_rdma/gate_fenced`, md5 `9675a073`): 10/10, FENCED GO가 마지막 thread 끝(+500.1 ms) 뒤 0.7–1.7 ms, 64 검사 실패 0 `[측정: local/gate_fenced_n1.log]`. 그러나 이 줄 꼴("old gate GO +0.5 ms … FENCED gate GO +501.6 ms")은 `rows_gc.py`의 `GATE` 정규식("old GO at … ms, FENCED GO at …")과 맞지 않아 행이 0이다(문제 6). `--pid` 인자는 받지 않는다(실제 pid 모드 없음 `[측정]`).

## 남은 `[초안]` 표시에 쓸 자료

시행 수는 모두 채점 안 한 smoke와 pilot의 n이다. smoke 값은 smoke 4–6의 `aN/raw` 사본(스크래치 `agent_gc_pilot2/recount/`)을 지금의 `rows_gc.py`로 다시 셌다 `[측정]`.

- **kill 셀 복원 시간(`restore_time_rdma`, 첫 판정 → 마지막 게시 / kill → 마지막 게시 / 복원 시간, ms).**
  - pilot 2 gin-mirror kill 셀 @gc(이 예측의 셀, n 1씩): `mi4_kill3_ow` 186.8 / 207.6 / 186.7, `mi4_kill1_ow` 174.4 / 195.3 / 174.4, `mi4_kill3_ckpt_ow` 154.7 / 175.2 / 154.7, `mi4_seg_4k` 164.5 / 185.3 / 164.5, `mi4_seg_32k` 170.9 / 192.0 / 170.9, `mi4_seg_128k` 186.8 / 207.7 / 186.7, `mi4_pull` 171.4 / 192.1 / 171.3, `rs4_kill3_mion` 171.2 / 192.0 / 171.1; 학습 `mi4_train_kill3` 250.1 / 270.8 / 250.1. 4 KiB 여덟은 154.7–186.8 / 175.2–207.7 ms로 띠 120–197 / 154.5–240.5 안, 학습은 195–286 / 229.6–318.0 안. 모두 `la_later_n` 0, 펜스 차례 1.
  - 다른 kill 시행(이 예측 밖, 참고): pilot 1 `gc4_kill3_ow` 161.7 / 182.7, `gc4_rst_kill3` 170.4 / 191.4, `gc4_ud_drop_rejoin` 384.8 / 405.6, `gc4_kill3_ow_nowitness` 74.2 / 200.8, `gc4_fdhold_sock_kill3` 72.1 / 134.1, `gc4_kill3_noreport_nofdhold` 80.8 / 3 788.8, `mi4_kill3_ow@gct` 176.4 / 176.6; pilot 2 `gc4_fdhold_sock_kill3` 76.0 / 136.8, `mi4_kill3_ow_nomirror` 154.0 / 174.7, `rs4_kill3` 149.6 / 170.4, `rs4_kill3_ckpt` 158.4 / 179.1, `rs4_kill1` 157.7 / 178.5, 두 죽음 셀의 첫 복원 176.0 / 197.1, 254.0 / 274.9; smoke 4 a2 164.3 / 185.1, smoke 6 a2 164.8 / 185.6.
  - kill → 판정은 확인 창 판정 시행 모두 20.5–22.8 ms(FIN + W 20 ms).
- **GPU hang 판정 시각(hang 줄 → 판정, 생존 셋의 최소–최대, ms).** pilot 1 `gc4_gpuhang12000_fence` 10 031.4–10 033.8, `…_ctx1_fence` 10 028.9–10 032.4; smoke 4 a6 10 032.1–10 033.3; smoke 6 a4 10 084.7–10 086.8, a5(ctx1) 10 031.0–10 034.3. 다섯 시행 10 028.9–10 086.8 ms, 띠 10 000–10 500 안. pilot 2에는 없음.
- **`fdhold_sock_helper_stall`(kill → STALL_HELPER 판정, ms).** pilot 1 a5 10 025.2–10 026.4; smoke 4 a4 10 091.5–10 094.9; smoke 5 a3 10 080.8–10 081.5, a4 10 067.5–10 069.7. 네 시행 10 025.2–10 094.9 ms, 띠 10 000–10 500 안, 판정 앞 READ 실패 0. pilot 2에는 없음.
- **FIN 없는 죽음의 launcher 보고.** pilot 2 60.8–60.9 ms, pilot 1 62.0 ms; 띠 40–200 ms 안.
- **비용 문턱.** 위 절: sunny 같은 팔 퍼짐 0.76 %(off), 0.50 %(on)라 2 %가 퍼짐의 두 배보다 크다. 팔 차 +1.14 %. 두 묶음뿐이라 퍼짐은 어림이다 `[추론]`.
- **회귀 규칙.** 위 절: 자료 있는 gin-mirror 규칙 열한 개와 mirror 끈 네 셀 1/1, 두 죽음 규칙 셋은 제외로 자료 없음(그 시행의 자료로는 거짓).

## 문제 (고치지 않음, 결정 필요)

1. **freeze 셀 둘의 창 검사가 0이 아니다(규칙 또는 라이브러리).**
   - 생존 셋의 "window check after the fence of rank 3: changed=… against=snapshot_at_judgement"가 2, 1, 2칸과 1, 1, 1칸이다 `[측정]`.
   - freeze는 상태 페이지만 멈추고 프로세스는 계속 걸음을 낸다. 기준이 판정 때의 사본이라 판정에서 펜스(117.9–148.1 ms 뒤)까지 옛 화신이 낸 put이 셈에 들었다고 본다 `[추론]`. 펜스 뒤 쓰기인지는 가르지 못했다 `[미확인]`.
   - 멈춘(SIGSTOP, GPU hang) 셀은 그 사이 쓰기가 없어 pilot 1에서 `win_verified` 1이었다. 사본 시각(QP ERR 뒤로)이나 예측의 그 항을 정해야 한다.
2. **예비 프로세스 없음 셀의 거절 까닭이 바뀌었다(launcher 경쟁 또는 규칙 낱말).**
   - launcher가 ACTIVATE를 "could not hand over to the spare"로 거절했고, 예비 프로세스의 끝("spawned spare exited unused")은 그 81 ms 뒤에 적었다 `[측정: a1 launcher_sunny.log]`. pilot 1은 끝을 먼저 보고 "the spare exited"였다.
   - fallback(2.4 ms)과 풀림(3)은 규칙대로다. 규칙의 `has(la_act_refused_why, "the spare exited")`가 이 경쟁의 두 까닭을 다 받을지 정해야 한다.
3. **두 죽음 셀(`mi4_kill2_kill3_ow`, `mi4_train_kill2_kill3`)에서 둘째 죽음이 복원되지 않는다(라이브러리).**
   - 둘째 예비 프로세스(rank 3 화신 1)는 launcher가 활성화를 넘겼고(ACCEPTED), rank 0, 1에서는 REJOIN_ACK를 받았다.
   - 첫 죽음에서 되살린 rank 2(화신 1)에게 보낸 REJOIN은 답이 없어 200 ms마다 다시 보냈다(150번, 149번) `[측정: spare_2nd.log]`.
   - 생존 rank는 새 rank 3을 2.1 s 뒤 의심, 10.2 s 뒤 STALL_HELPER로 판정해 fallback했고, 그 예비 프로세스의 Resume은 30 s 뒤 rc=2다. 두 시행 모두 같다(2/2).
   - 되살린 화신의 UD 끝점을 둘째 예비 프로세스가 옛 것으로 쥔다고 본다 `[추론]`. gin-mirror @mi에서는 이 셀이 복원됐다(그 실험 문서).
4. **두 죽음 셀의 launcher QP 잃음 규칙(채점기, 실행기).**
   - `rows_gc.py --stops`의 `la_qp_err_n`은 대상(`subject_rank`, 첫 kill)만 빼서, 둘째 kill의 rank 3 기록 QP 잃음 줄 2개를 셌다 `[소스: rows_gc.py la_counts; 측정]`. 그래서 a4가 STOP_launcher였고, 채점기는 두 시행을 `launcher_changed`로 제외한다.
   - 실행기 쪽은 고쳤다(아래). `rows_gc.py`가 KILL2_RANK도 빼야 한다(이 작업의 고칠 범위 밖).
5. **`no_tcp_control`의 ss 항이 이른 kill 셀 여섯에서 0이 아니거나 빈칸이다(실행기의 잼 시각).**
   - 유효 rdma 시행 35개 가운데 29개만 시행 조건이 참이다 `[측정]`. 거짓 여섯은 모두 `tcp_ctrl_bytes` 0이고 ss 항만 다르다.
   - `ss_tx_delta_bytes` −23 712(`mi4_kill3_ckpt_ow`, `mi4_seg_32k`, `mi4_seg_4k`), −19 969(`rs4_kill3_ckpt`): 두 스냅숏 사이에 죽은 rank의 소켓이 닫혀(연결 수 8 → 6, 10 → 7) 남은 소켓의 보낸 바이트 합이 줄었다 `[측정: _ss.out; 추론]`.
   - 빈칸 둘(`gc4_kill3_ow_spareabsent`, `mi4_seg_128k`): 둘째 스냅숏이 없어 `ss_pids_both` 0이다.
   - pilot 1에서는 이 꼴의 셀이 적어 드러나지 않았다. 소켓마다 차를 내거나 kill 셀은 kill 앞에서 재는 쪽을 정해야 한다.
6. **`gate_fenced`.** 실제 pid 모드가 없고(`--pid`를 무시하고 자기 시행을 돎), 단위 프로그램의 줄 꼴이 `rows_gc.py`의 `GATE`와 맞지 않는다. 지금으로는 자료 부족만 나온다.
7. **`gc4_none_probe`의 입력 멈춤 16.526 ms**가 규칙의 16 ms를 0.53 ms 넘었다(한 시행). 같은 hold들의 장애 없는 셀은 5.4–9.2 ms다(`mi4_none_ow` 7.364, `rs4_none` 5.378, `mi4_train_none` 9.181) `[측정]`. 60 s 셀이라 최대값이 커진 것으로 보이나 n 1이다 `[추론]`.
8. `gc4_credit_stall`은 이번에도 창이 차지 않아 launcher credit READ 재시도는 걸리지 않았다(`send window … exhausted` 줄 0 `[측정: grep]`). 예측은 2bbdcfca에서 그것을 보고만으로 바꿨다.

## 실행기 쪽 바꿈 (이번에 돌았음)

- `impl/test/hold_gc.sh`:
  - pilot hold `PCELL-<셀>[+<셀>…]`: `cells_gc.json`의 이름 댄 셀을 n 1로(pilot 폴더에서만). a1에서 돌았다.
  - `PRG-<빌드>-<h1>+<h2>…`: gin-mirror hold 여럿을 pilot hold 하나로. a4–a7에서 돌았다.
  - `COSTPILOT-<노드>-<묶음 수>`(1–6, 짝수 묶음은 팔 차례를 뒤집음). a2, a3에서 돌았다.
  - 두 죽음 셀(`*_kill2_kill3*`)의 launcher QP 잃음 줄은 STOP 대신 `la_qp_twokill.txt`에 적는다(문제 4). a5 뒤 hold부터 돌았고 a6에서 한 번 적었다.
- 라이브러리, launcher, `rows_gc.py`, `score_gc.py`, 셀과 예측 파일은 고치지 않았다.

## 하지 않은 것

- tcp 회귀 대조 `mi4_kill3_ow@gct`(이번 범위 밖, pilot 1 a7에서 돎), P3(noreport 두 셀), GPU hang 셀은 다시 돌리지 않았다.
- 시도 한도는 5번 남았다.

원자료는 `aN/`(`raw/`, `reg/`, `costpilot_<노드>/`)에 있고 시행 표는 `aN/trials.csv`, `local/trials.csv`다(스크래치 사본 채점의 상태 열 포함). 모두 IPv4 가림을 거쳤다(IPv4 꼴 0건, 관리망 주소 0건 `[측정: grep]`).
이 폴더 루트에는 사슬 기록 [chain.out](chain.out), 시도 기록 [attempts.txt](attempts.txt), 배포 출력 [deploy.txt](deploy.txt)가 있다.
