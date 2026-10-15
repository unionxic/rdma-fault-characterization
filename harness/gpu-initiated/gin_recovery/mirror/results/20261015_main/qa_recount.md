# gin-mirror 본 실행 독립 재계산 (QA, 20261015_main)

대상: `results/20261015_main/`의 `raw/`(run_mi.sh 시행 168), `reg/`(gin-remaining 실행기 회귀 20), `cost_mirror_*/`(비용 실행 240), 합 428.
채점기(`impl/test/score.py`, `rows_mi.py`, `rows_rs.py`)와 그 출력(`SCORE.md`, `trials_scored.csv`)은 1–6절을 다 쓸 때까지 열지 않았다. 7절만 그 둘을 읽고 쓴다.
클러스터, ssh, 프로세스 kill 없음; 작업 트리는 고치지 않았다(읽기만).

읽은 것: `EXPERIMENT.md` 2, 3, 7, 8절과 9.3, 9.4, 9.6절(로그 줄의 뜻), `impl/test/predictions_mi.csv`(판정식), `impl/test/cells_mi.json`(셀, n, driver, env),
`PREREG.txt`, `impl/test/run_mi.sh`, `gin_mi.cu`, `run_cost_mi.sh`의 머리말(kv 키와 로그 줄), `hold_mi.sh`, `cells_mi.sh`의 STOP 파일 부분, gin-restore의
`results/20261013_main/qa_recount.md`(방법의 선례).

재계산 스크립트(세션 스크래치 `mi_recount/`): `recount_mi.py`(원자료 → `out/trials_recount.csv`, `out/reg_recount.csv`, `out/cost_runs.csv`),
`verdict.py`(판정식을 손으로 다시 옮겨 판정, `out/verdicts.tsv`), `keys.py`, `rt_both.py`, `cost.py`(아래 표), `compare.py`(7절, 채점기 출력과 견줌).
실행: `python3 recount_mi.py <results/20261015_main> out && python3 verdict.py`.

표시: `[측정]` 원자료에서 다시 셈, `[추론]` 해석, `[미확인]` 확인 못 함.

## 0. 고정 파일 확인

- 작업 트리 `gin-mirror-fix`의 HEAD = 태그 `prereg/gin-mirror-v1`의 커밋 `ad9183cf`이고, `git diff prereg/gin-mirror-v1 -- harness/gpu-initiated/gin_recovery/mirror`는 빈 출력이다
  (추적 파일 변경 없음; untracked는 `results/`뿐). 그래서 `EXPERIMENT.md` 2, 3, 7, 8절도 태그 그대로다 `[측정]`.
- `sha256sum`: `predictions_mi.csv` `2db0c694…bbd`, `cells_mi.json` `697e8b6c…00ab`, 둘 다 `PREREG.txt`의 줄과 같다 `[측정]`.
- 시행 meta의 `lib_md5`는 188/188이 `c74e6ffb…`(mi_ln4), `driver_md5`는 셀의 driver와 같다(`gin_mi` `4f7ba8bf`, `gin_mi_nomacro` `89878018`, `mr/ff` `9fcd8239`,
  `mr/hold` `c5575a76`); 비용 240/240은 `21b0be95…`(mip_ln4)와 `gin_ts2_mi` `f402e72a`. 모두 `PREREG.txt`와 같고 `rs_set=mi6` `[측정]`.

## 1. 예측마다 쓴 방법

공통.
- 시각: raw 로그 줄 앞의 숫자(rain의 수신 시각, s). 같은 프로세스 안의 간격은 줄의 `mono_ms`로도 잰다. 노드가 다른 rank 사이는 수신 시각만 쓴다.
- 죽은 rank d = meta `kill_rank`(둘째 죽음 셀은 `kill2_rank`도). 생존 rank: 첫 죽음은 나머지 셋의 원래 프로세스, 둘째 죽음(rank 3)은 r0, r1과 되살린 rank 2(`_spare`).
  kill 시각 = `_kill.out`의 `GINRS killed` 줄(트래픽 kill, 확정 뒤 15단계 kill), driver kill은 죽은 rank의 `GINRS die rank=d step=s` 줄,
  체크포인트 멈춤 중 kill은 `test switch NCCL_GIN_RESTORE_TEST_DIE_IN_CKPT: dying 300 us after the pause request of checkpoint C` 줄.
- 첫 죽음 판정 = 생존 rank의 `rank s: rank d judged dead` 줄 가운데 가장 이른 수신 시각.
- kv는 `key=value`(같은 키는 뒤의 값); 회귀 실행기의 kv는 값에 빈칸이 있어 다음 `key=` 앞에서 자른다.

| 무엇을 예측했나 (찾는 키) | 시행마다 쓴 줄과 키, 계산 |
|---|---|
| 대기가 붙잡힘 (`wait_held`) | 생존 rank 모두: 로그에 `GINRS step … released=1` 0, `GINRS async` 0, `declined rank=s peer=d` 0; 실행 끝까지 산 프로세스는 kv `released=0`, `async_n=0`, `steps_done`=단계 수. 둘째 죽음 셀은 두 죽음 모두 참일 때 1 |
| 데이터 같음 (`data_equal`, `ow_data_equal`) | 논리 rank 넷의 마지막 프로세스 kv `x_match=1`, `recv_bad=0`, `xhist_bad=0`, `dev_bad=0`, `sig_exact=1`, `steps_done`=단계 수; `ow_`는 더해 `recv_poison=0`, `dev_poison=0` |
| 재실행 없음 (`no_reexec`) | 끝까지 산 생존 프로세스 kv `reexec_any=0`, `reexec_max=1`, `steps_done`=단계 수 |
| 되살린 rank 끝까지 (`revived_done`) | 예비 프로세스 kv `revived=1`, `steps_done`, `exit=0`, `xchg=ok`, meta `sparerc=0`(`spare_2ndrc`) |
| 억제 정확 (`suppress_ok`) | 예비 프로세스의 `suppress peer=q qp=k budget=B suppressed=S left=L`(같은 (q, k)는 마지막 줄). q마다 0이 아닌 줄이 하나이고 S = B, L = 0, 다른 QP는 0. S를 원자료에서 따로 센 범위 [2(M − K), 2(M′ − K)]와 견줌: K = 예비 프로세스의 `restored as incarnation 1 from checkpoint K`, M = max(죽은 rank의 마지막 `GINRS step … released=0` 단계 L, q가 자기 `restored as` 줄 전에 끝낸 마지막 단계 S_q, 멈춤 중 kill의 C), M′ = max(L + 1, S_q, C). 한 단계 폭을 두는 까닭은 6절 3. 교차 확인: rank 0의 `hold of rank d started: … (executed/sent at the hold: X/…)`에서 X − 2(K + 1) |
| 재실행 내용이 pool에서 (`from_pool_ok`, `export_source_bytes`) | 생존 rank의 `export to rank d: entries=E mirror_entries=E′ mirror_bytes=B source_bytes=0 …`에서 E = E′ 셋 모두, Σ B = 예비 프로세스 `import plan … mirror_bytes` = `import done: … pool_bytes`(left 0, failed 0) = FETCH 줄의 `segment_bytes`; `export_source_bytes` = Σ source_bytes |
| 복원 시간 (`restore_time_ms`) | 첫 죽음 판정 → 생존 rank 셋의 `rank s: rank d restored as incarnation 1 (on time; …)` 줄 가운데 마지막(수신 시각). 7절: 채점기는 끝점을 `restore round with rank d published` 줄로 잡는다 |
| 멈춤 중 kill (`die_in_pause`, `ckpt_before`) | `die_in_pause` = 생존 rank 가운데 `input pause for rank d's checkpoint C ended (a hold of that rank took its gates)` 줄이 있고 hold 시작 줄이 `gates odd since x ms`(x > 0)인 수(이 자료에서 두 조건은 늘 함께 참이거나 함께 거짓). `ckpt_before`: K < C이고 kill 전에 생존 rank 셋 모두 `rank d armed at its stable checkpoint K` |
| mirror 없는 대조 (`nomirror_corrupt`) | 대기 붙잡힘, 생존 셋의 `restored as` 줄, 예비 프로세스 kv의 `x_match≠1` 또는 `recv_bad`, `xhist_bad`, 독 수 가운데 하나가 0이 아님 |
| checksum 대조 (`nomirror_detect`) | 생존 rank 로그에 `source buffer changed`, 셋 모두 `the restore of rank d … is given up` 줄, kv `released=1`, 풀림 줄(`released=1`)의 `mono_ms` − 자기 fallback 줄 `mono_ms`가 2 000–2 500 ms |
| FETCH (`fetch_us`, `fetch_bytes`) | 예비 프로세스의 `fetch for checkpoint K from buddy rank b: image_bytes=I segment_bytes=G … fetch_us=F`; 바이트 = I + G, 모형 5 + 바이트 / 11 880(µs); 시행 조건 abs(F − 모형) ≤ 0.15 × 모형 |
| pool (`pool_max_bytes`, `restarts`) | 모든 프로세스의 `mirror summary … restarts=R third_slot=T max_live_bytes=X pulls_sent=P …`: 최고 X, R의 합 |
| 당기기 (`pulls_sent`, `lane_broken`, `disarm_n`) | `pulls_sent` = 네 rank summary의 합(같은 시행 `CKPT_PULL to rank` 줄 수와 같음); `lane_broken` = `lane to rank e broken` 줄 수; `disarm_n` = `rank e disarmed (its mirror lane on this rank broke …)` 줄 수(모든 프로세스) |
| 짝 보호 공백 밖 (`lane_broken_other`, `disarm_other`, `broken_other`) | 공백 = 맡은 rank e = d xor 1에 대한 줄, kill 수신 시각부터 e의 프로세스가 복원 뒤 처음 찍은 `checkpoint K stable at buddy rank d` 줄까지(±5 ms). 그 밖의 `lane to rank … broken`, `rank … disarmed (its mirror lane …)`, `first mirror break toward rank …` 줄을 센다 |
| 넘침 fail-fast (`overflow_failfast`) | `lane_broken` ≥ 1; hold 시작 줄 수; 생존 셋 kv `released=1`이고 풀림 − 자기 죽음 판정(`mono_ms`) 2 000–2 500 ms(degraded), 또는 풀림 − fallback 2 000–2 500 ms |
| 장애 없음 (`restore_count`, `ckpt_pause_ms`) | `restore_count` = `hold at close`의 holds + restored + fallbacks와 hold, 복원, fallback 줄 수와 되살린 예비 프로세스(0인지만 판정에 씀); `ckpt_pause_ms` = 모든 프로세스 `input pause … pause_us=N`의 최대 |
| 거절 (`resume_err_all`, `reason_same`, `ff_fallthrough`) | rank 넷 kv `resume_rc≠0`, `resume_why` 넷이 같음, Resume 오류 없이 `GINRS step` 줄을 낸 rank 수(매크로 없는 셀은 `refused_then_ran=1` 없이 돈 rank 수); 이유 글자는 rank 0의 `resume_why` |
| 다시 무장 (`reimage_ok`) | 첫 죽음의 대기와 억제 조건; rank 3 로그에서 `rank 2 restored as incarnation 1` 뒤 처음 `checkpoint K stable at buddy rank 2`가 된 K의 `stored … bytes`가 rank 3의 첫 저장 바이트(전체 이미지)와 같음; 그 사이 rank 3의 `checkpoint N is void` ≤ 1; 둘째 kill 전에 둘째 죽음의 생존 셋 모두 `rank 3 armed at its stable checkpoint K′`(K′ ≥ K); 둘째 hold 시작에서 생존 셋 모두 `hold of rank 3: mirror to buddy rank 2 … path_ok=1 cell_valid=1`(rank 3으로 가는 lane이 켜져 있음) |
| 둘째 죽음 (`second_ok`) | 둘째 죽음의 대기 붙잡힘, 재실행 없음, `_spare_2nd` 끝까지, 그 FETCH가 `from buddy rank 2`, 생존 셋의 `restored as`, 끝에 넷의 데이터 같음 |
| 단계 맞춤 가져오기 (`paced_ok`, `inj_from_n`) | 예비 프로세스의 `import step N` 줄이 K+1부터 `import done`의 last_step까지 하나씩 차례대로; 각 N의 줄 `mono_ms`가 같은 프로세스의 `GINRS step N−1` 줄 앞(그 커널 전)이고 `GINRS step N−2` 줄 뒤(한꺼번에 아님); `import done left=0`; `INJECTED sent step=last survivors=3 unsent=0` 한 번; `inj_from_n` = `INJECTED from rank d` 줄이 한 번인 생존 rank 수 |
| RDMA 저장소 (`tcp_image_bytes`, `tcp_segment_bytes`) | 모든 프로세스 `checkpoints at close … upload_bytes`와 TCP FETCH의 `served to its spare (N bytes)` 합; `log export to rank … data_bytes`의 합 |
| 회귀(mirror 끔) | gin-restore 선례의 정의 그대로(대기, 데이터, 억제, 멈춤 중 kill, fail-fast 풀림 2 000–2 500 ms, fallback = hold 시작 + 500–1 500 ms와 풀림 = fallback + 2 000–2 500 ms, window MR strict) |
| gin-remaining 실행기 회귀 | 장애 없음: rank 넷 kv `exit=0`, `tx_ok=3`, `rx_ok=3`, meta rc 0. rank 3 kill: 생존 rank s의 `rx_3s_rel=1`, `rx_3s_rc`가 오류 글, `rx_3s_rel_mono_ms` − 자기 `judged dead` `mono_ms` 2 000–3 000 ms, 생존 rank 사이 보내기 6개 `done=1000`, `rc=no error`, `nerr=0`, `kernel_done=1` 셋 |
| 비용 | r0 kv `lat_p50_us`; 대역 = `burst_K` × bytes / `lat_p50_us`(GB/s). 유효 실행: 두 rank `exit=0`, `tx_done`/`rx_done` = 반복 수, 오류 키 없음, `win_flags=0x3`, meta rc 0, `left=0`, md5 일치, mirror 팔은 `mirror summary`의 broken 0이고 max_live_bytes > 0. 노드, 지표, 팔마다 6개의 중앙값 |

판정: 8절의 제외를 뺀 유효 시행에서 조건이 참인 수 k를 판정식의 문턱과 견줌. "= N"은 유효 시행 전부.

## 2. 시행 수, 제외, 중단 파일

**시행 수** `[측정: ls, meta 수]`: run_mi 시행 168(셀 35), 회귀 실행기 20(셀 4), 비용 240(받는 노드 2 × 지표 5 × 팔 4 × 6라운드), 합 **428**(계획 428).
hold별로 G1 40, G3 37, T1 15, T2 5, G2 9, R1 20, R2 40, R3 22(합 188), COST 10 hold × 24. 셀마다 계획 n과 실행 n이 모두 같다(`cells_mi.json`의 본 실행 hold).
뒤에 다시 부른 `-r2` hold 여덟은 188시행 모두 "already done"으로 건너뛰었고 새 시행은 0이다(`hold_*-r2.out`; 그 hold의 rain QUERY_QP 증가 0) `[측정]`.

**제외: 428 가운데 0** `[측정: recount_mi.py의 excluded 열]`.

| 8절의 제외 조건 | 본 것 | 결과 |
|---|---|---|
| 셀이 정한 빌드가 아님 | meta md5(0절) | 188/188, 240/240 맞음 |
| workload 모드나 mirror 설정이 셀과 다름 | 프로세스 kv `workload`(학습 셀은 `train`, 덮어쓰기 셀은 `overwrite`, 나머지 `gin_rs`), `mirror_env`(`mi4_refuse_mirror1`의 rank 3만 0) | 어긋남 0 |
| GIN 사용자 문맥 전에 끝남 | 살아 있는 rank kv `devcomm_rc=0` | 0 |
| kill이 무장한 첫 확정 체크포인트 전 | 복원을 기대하는 kill 시행 80개(죽음 90개, 둘째 죽음 셀은 첫 kill): kill 전에 생존 셋 모두 `rank d armed at its stable checkpoint` | 80/80 |
| 예비 프로세스가 활성화 전 시작 실패 | meta `spare_wanted=1` → `spare_ready=1`, `spare2_wanted=1` → `spare2_ready=1` | 모두 1 |
| 다른 사용자의 GPU 작업 | meta `gpu_apps_before=0/0` 168/168; hold 앞뒤 snap의 GPU 사용자 줄 0 | 해당 없음 |
| smoke, pilot | 이 폴더에 없음 | 해당 없음 |

**중단(STOP)** `[측정: ls, hold 출력]`: `STOP_mlx5`, `STOP_cuda`, `STOP_left`, `STOP_nic`, `STOP_mem`, `refused.txt`, `skipped.txt`, `spare_wait.txt`, `qp_over.txt` 없음, `LEFT_STREAK` = 0.
hold 출력 26개 모두 `idle (rate=0Mb/s)`로 시작, 중단 줄 0, `left=` 0이 아닌 값 0. meta `left=0` 188/188. kv와 로그의 `cuda_error`, `watchdog=1`, `nccl_error`,
`illegal address`, `illegal memory access`, `unspecified launch failure` 0. `Killed` 알림 125개는 의도한 SIGKILL 수와 같다(G1 40, G3 25, T1 10, T2 10, R2 35(예비 프로세스 먼저 kill 5 포함), R3 5; R1 회귀 실행기의 kill은 hold 출력에 알림 없음).

**rain QUERY_QP** `[측정: snap_before/after]`: `qp_over.txt`와 `STOP_mlx5`가 없으므로 시행 하나가 상한(복원 50 000, 회귀 150 000)을 넘은 일은 없다 `[추론: hold_mi.sh after_trial]`. 시행별 값은 남지 않아 `[미확인]`.

| hold | 시행 | QUERY_QP 증가 | 시행당 평균 | 상한 |
|---|--:|--:|--:|--:|
| G1 | 40 | 947 063 | 23 677 | 50 000 |
| G3 | 37 | 773 696 | 20 911 | 50 000 |
| T1 | 15 | 411 157 | 27 410 | 50 000 |
| T2 | 5 | 137 779 | 27 556 | 50 000 |
| G2 | 9 | 1 548 | 172 | 50 000 |
| R1 | 20 | 1 972 980 | 98 649 | 150 000 |
| R2 | 40 | 663 912 | 16 598 | 50 000 |
| R3 | 22 | 257 027 | 11 683 | 50 000 |
| COST × 10 | 24씩 | 444씩 | 18.5 | 50 000 |

**mlx5, 펌웨어, BAR1** `[측정]`: `mlx5_new_*.txt` 26개 모두 0줄; 26 hold 모두 rain mlx5 cmd_err 2 → 2, sunny 0 → 0, rain 펌웨어 명령 실패 합 31 → 31, NVRM 줄 941 → 941,
rain BAR1 Free 앞뒤 251 MiB. 학습 hold의 시행 시작 문 BAR1(보고만): T1 시행 15개 Free 133 MiB, T2 시행 5개 74 MiB.

**시행 시간**(meta `wall_s`) `[측정]`: 학습 모양 밖 2.0–17.7 s(`mi4_overflow` 17.7 s), 학습 29.7–34.7 s, 회귀 실행기 17.5–17.6 s. 한도(60, 150, 150 s) 안.

## 3. 판정 (재계산)

`[측정: verdict.py, out/verdicts.tsv]`. 유효 n = 계획 n(제외 0).

| 무엇을 예측했나 (찾는 키) | 셀 | n | k | 기준 | 판정 | 시행별 값의 범위 (무엇의 범위인지) |
|---|---|--:|--:|---|---|---|
| 덮어쓰는 workload에서 생존 rank의 대기가 붙잡힘 (`ow_wait_held`) | `mi4_kill3_ow` | 10 | 10 | ≥ 9 | 맞음 | 생존 rank 30개 모두 풀림 0, 비동기 오류 0, 거절 줄 0 |
| 최종 데이터가 기준과 비트 단위로 같고 독 값 없음 (`ow_data_equal`) | `mi4_kill3_ow` | 10 | 10 | ≥ 9 | 맞음 | 프로세스 40개 모두 같음, 독 0 |
| 생존 rank 재실행 없음 (`ow_no_reexec`) | `mi4_kill3_ow` | 10 | 10 | 10/10 | 맞음 | 생존 rank 30개 실행 수 최대 1 |
| 되살린 rank가 끝까지 (`ow_revived_done`) | `mi4_kill3_ow` | 10 | 10 | ≥ 9 | 맞음 | 시작 단계 121, 600단계, exit 0 |
| 다시 보내기 억제가 정확 (`ow_suppress_exact`) | `mi4_kill3_ow` | 10 | 10 | ≥ 9 | 맞음 | 통로 30개 30–36 메시지, S = B, 남은 예산 0, 따로 센 범위 안; rank 0 통로 10개는 hold 줄의 X − 2(K+1)과 정확히 같음 |
| 재실행 내용이 모두 pool에서 (`ow_from_pool`) | `mi4_kill3_ow` | 10 | 10 | ≥ 9 | 맞음 | 원본 바이트 0, 내보낸 mirror 바이트 합 = 가져온 pool 바이트 = FETCH segment 바이트(192 512–217 088 B) |
| 복원 시간 ≤ 2 000 ms (`ow_restore_time`) | `mi4_kill3_ow` | 10 | 10 | ≥ 9 | 맞음 | 176.2–199.0 ms (시행 10개) |
| 체크포인트 입력 멈춤 중 kill도 앞의 확정 체크포인트에서 복원 (`ckpt_kill_ow`) | `mi4_kill3_ckpt_ow` | 5 | **1** | ≥ 4 | **틀림** | 멈춤 안 생존 rank 수 2, 1, 1, 3, 2(n1–n5); 나머지 조건(대기, 데이터, 재실행 없음, 끝까지, 앞 체크포인트 확정)은 5/5 참. 6절 1 |
| 같은 GPU의 다른 rank가 죽어도 같음 (`kill_other_ow`) | `mi4_kill1_ow` | 5 | 5 | ≥ 4 | 맞음 | 복원 178.4–200.7 ms |
| 대조: mirror 없이 덮어쓰면 데이터가 틀림 (`nomirror_corrupt`) | `mi4_kill3_ow_nomirror` | 5 | 5 | ≥ 4 | 맞음 | 복원은 끝남(셋 모두 `restored`); 되살린 rank `x_match=0`, `recv_bad` 1 440–1 443, `xhist_bad` 481–482, 독 0 |
| 대조: checksum 표본이면 찾아서 fallback (`nomirror_detect`) | `mi4_kill3_ow_sampled` | 5 | 5 | ≥ 4 | 맞음 | `source buffer changed` 5/5, 풀림 = fallback + 2 000.7–2 004.0 ms (생존 rank 15개) |
| FETCH가 바이트와 함께 늘고 모형 ±15% 안, 복원 ≤ 2 000 ms (`seg_restore_slope`) | `mi4_seg_4k`, `_32k`, `_128k` | 5/5/5 | 5/5/5 | 셀마다 = N, 중앙값 차례 | 맞음 | FETCH 중앙값 1 273 < 2 408 < 2 942 µs; 모형과의 차 +0.78–+4.45% (시행 15개) |
| pool이 간격에 비례 (`pool_vs_interval`) | `mi4_int_10`, `_20`, `_40` | 3/3/3 | 3/3/3 | 다시 시작 0, 비 2 ± 0.5 | 맞음 | 최고 바이트 중앙값 45 056, 81 920, 167 936 B; 비 1.818, 2.050; 셋째 자리 0 |
| 당기기가 넘침을 막음, 장애 없음 (`pull_no_disarm_none`) | `mi4_pull_none` | 3 | 3 | 3/3 | 맞음 | `pulls_sent` 801–833(≥ 30), lane 깨짐 0, DISARM 0 |
| 당기기 셀의 kill도 공백 밖 DISARM 없음 (`pull_no_disarm_kill`) | `mi4_pull` | 5 | 5 | ≥ 4 | 맞음 | 공백 밖 깨짐 0, DISARM 0; 공백 안 깨짐 0, 2, 0, 2, 1줄 |
| 넘치면 DISARM하고 fail-fast (`overflow_failfast`) | `mi4_overflow` | 5 | 5 | ≥ 4 | 맞음 | lane 깨짐 84–87줄; hold 시작 0(5/5); 풀림 = 자기 죽음 판정 + 2 001.9–2 005.5 ms (생존 rank 15개) |
| 장애 없음: 데이터, 복원 0, 멈춤 ≤ 16 ms, 다시 시작 0 (`ow_none_clean`) | `mi4_none_ow` | 5 | 5 | 5/5 | 맞음 | 멈춤 최대 6.750–8.151 ms |
| mirror와 checksum 함께 켬 → 같은 이유로 거절 (`refuse_csum`) | `mi4_refuse_csum` | 3 | 3 | 3/3 | 맞음 | rc 5 넷, 이유 `…MIRROR_and_…CHECKSUM_are_both_on` |
| rank 하나만 mirror 끔 → 거절 (`refuse_mirror1`) | `mi4_refuse_mirror1` | 3 | 3 | 3/3 | 맞음 | 이유 `…the_setup_agreement_turned_it_off` |
| S나 L이 다름 → 거절 (`refuse_sl`) | `mi4_refuse_sl` | 3 | 3 | 3/3 | 맞음 | 이유 `…differs_between_ranks_(S_2,_L_1048576;_rank_0:_S_3,…)` |
| 짝이 되살아난 뒤 맡은 rank가 보호를 되찾음 (`reimage_after_restore`) | `mi4_kill2_kill3_ow` | 5 | 5 | ≥ 4 | 맞음 | 전체 이미지 체크포인트 = 되살린 뒤 첫 간격(200 또는 220), 그 사이 void 0, 둘째 kill 전 다시 무장 3/3, lane 켜짐 3/3 |
| 둘째 죽음도 되살림 (`second_death_restored`) | `mi4_kill2_kill3_ow` | 5 | 5 | ≥ 4 | 맞음 | 복원 첫 76.6–200.0, 둘째 185.0–210.0 ms; FETCH는 되살린 rank 2에서 5/5 |
| 회귀(mirror 켬): 장애 없음 (`regression_none_on`) | `rs4_none_mion` | 5 | 5 | 5/5 | 맞음 | 복원 0 |
| 회귀(mirror 켬): rank 3 kill (`regression_kill3_on`) | `rs4_kill3_mion` | 5 | 5 | ≥ 4 | 맞음 | 복원 197.6–220.8 ms |
| 학습 모양에서 데이터 같음 (`train_data_equal`) | `mi4_train_kill3` | 10 | 10 | ≥ 9 | 맞음 | kill 단계 323–1 478, 프로세스 40개 같음 |
| 단계 맞춤 가져오기 (`train_paced_import`) | `mi4_train_kill3` | 10 | 10 | ≥ 9 | 맞음 | 넣은 단계 2–20개, 차례 어긋남 0, INJECTED 생존 셋 모두 한 번 |
| 학습 FETCH 모형 안, 복원 ≤ 1 000 ms (`train_restore_parts`) | `mi4_train_kill3` | 10 | 10 | ≥ 9 | 맞음 | 모형과의 차 +1.27–+4.85%, 복원 249.8–298.2 ms |
| segment 다시 시작 0 (`train_segments`) | `mi4_train_none`, `mi4_train_kill3` | 5/10 | 5/10 | = N | 맞음 | 셋째 자리 0, 최고 바이트 44 040 192–46 137 344 B |
| 공백 밖 깨짐과 DISARM 0 (`train_pull_count`) | `mi4_train_none`, `mi4_train_kill3` | 5/10 | 5/10 | = N | 맞음 | kill 시행마다 공백 안 깨짐 2줄; 당기기(보고) 장애 없음 784–866, kill 687–821 |
| 장애 없는 학습 모양 (`train_none_clean`) | `mi4_train_none` | 5 | 5 | 5/5 | 맞음 | 멈춤 최대 8.999–10.227 ms |
| 체크포인트는 RDMA로 (`store_rdma`) | mirror 켠 4 KiB 셀 다섯과 학습 셀 셋 | 5/10/5/5/5/5/10/5 | 같음 | = N | 맞음 | TCP 이미지와 segment 바이트 0 (시행 50개) |
| 학습 모양 둘째 죽음 (`train_second_death`) | `mi4_train_kill2_kill3` | 5 | 5 | ≥ 4 | 맞음 | 복원 첫 92.9–274.9, 둘째 104.6–267.3 ms |
| 회귀(mirror 끔) 대기, 데이터, 재실행, 끝까지, 억제, 복원 시간 (`rg_wait_held` … `rg_restore_time`) | `rs4_kill3` | 10 | 10 | ≥ 9 또는 10/10 | 맞음(여섯) | 복원 369.8–403.7 ms |
| 회귀 멈춤 중 kill (`rg_ckpt_kill`) | `rs4_kill3_ckpt` | 5 | 5 | ≥ 4 | 맞음 | 멈춤 안 생존 rank 3/3이 5/5 |
| 회귀 rank 1 kill (`rg_kill_other`) | `rs4_kill1` | 5 | 5 | ≥ 4 | 맞음 | 복원 376.3–379.0 ms |
| 회귀 예비 없음 fail-fast (`rg_nospare_failfast`) | `rs4_kill3_nospare` | 5 | 5 | ≥ 4 | 맞음 | hold 줄 0, 풀림 = 자기 판정 + 2 002.1–2 006.0 ms |
| 회귀 예비 먼저 없어짐 fallback (`rg_spare_absent_fallback`) | `rs4_kill3_spareabsent` | 5 | 5 | ≥ 4 | 맞음 | fallback = hold + 1 000.7–1 003.1 ms, 풀림 = fallback + 2 000.5–2 003.4 ms |
| 회귀 장애 없음, strict (`rg_none_clean`, `rg_strict_forced`, `rg_strict_notforced`) | `rs4_none`, `rs4_none_off` | 5/5 | 5/5 | 5/5 | 맞음(셋) | 멈춤 최대 4.946–6.310 ms; 강제 16 / 강제 아님 16 |
| 회귀 거절 (`rg_refuse_reason`, `rg_refuse_nomacro_clean`) | 거절 셀 넷 | 3씩 | 3씩 | 3/3 | 맞음(둘) | rc 5 넷, 이유 같음; 매크로 없는 셀 600단계 데이터 같음, exit 0 |
| 회귀 gin-remaining 실행기 (`regression_restore_off`, `regression_kill3_off`) | `reg_*` 넷 | 5씩 | 5씩 | = N | 맞음(둘) | rank 3 받기 오류 해제 = 자기 판정 + 2 007.0–2 013.5 ms (생존 rank 30개), 보내기 6/6 |
| mirror 4 KiB 지연 +12 µs 안 (`cost_mirror_lat4k`) | 비용 | 6씩 | – | 노드마다 | 맞음 | 4절 |
| mirror 256 KiB 지연 (`cost_mirror_lat`) | 비용 | 6씩 | – | 보고만 | 보고 | 4절 |
| mirror 2 MiB 지연 1.5–2.2배 (`cost_mirror_lat2m`) | 비용 | 6씩 | – | 노드마다 | 맞음 | 4절 |
| mirror 묶음 대역 0.45–0.70 (`cost_mirror_bw`) | 비용 | 6씩 | – | 노드마다 | 맞음 | 4절 |

예측 53개(셀이 여럿인 예측을 하나로 셈) 가운데 틀림 1개(`ckpt_kill_ow`), 보고만 1개(`cost_mirror_lat`), 맞음 51개 `[측정]`.

## 4. 주요 수치

**복원 시간과 활성화 관문** `[측정: rt_both.py, keys.py]`. "판정 정의"는 이 재계산의 끝점(마지막 `restored as` 줄), "게시 줄 정의"는 채점기와 같은 끝점(마지막
`restore round … published` 줄, 7절). later = 예비 프로세스의 'later' 답 수. 활성화 뒤 부분 = 짝의 `its spare activated` 줄 → 마지막 `restored as` 줄.

| 셀 (죽음) | n / 최소 / 중앙값 / 최대 ms (판정 정의) | 같은 값 (게시 줄 정의) | later 0번: n, 범위 ms | later ≥ 1번: n, 범위 ms | 활성화 뒤 부분 ms |
|---|---|---|---|---|---|
| `mi4_kill3_ow` | 10 / 176.2 / 194.8 / 199.0 | 10 / 175.9 / 194.5 / 198.7 | 0 | 10, 176.2–199.0 | 67.9–70.4 |
| `mi4_kill1_ow` | 5 / 178.4 / 197.4 / 200.7 | 5 / 177.3 / 196.3 / 199.5 | 0 | 5, 178.4–200.7 | 69.5–71.6 |
| `mi4_kill3_ckpt_ow` | 5 / 178.7 / 179.9 / 200.1 | 5 / 178.0 / 179.6 / 199.1 | 0 | 5, 178.7–200.1 | 68.8–71.3 |
| `mi4_kill2_kill3_ow` 첫 죽음 | 5 / 76.6 / 196.6 / 200.0 | 5 / 76.3 / 196.3 / 198.9 | 2, 76.6–77.3 | 3, 196.6–200.0 | 67.2–69.9 |
| `mi4_kill2_kill3_ow` 둘째 죽음 | 5 / 185.0 / 189.7 / 210.0 | 5 / 184.8 / 189.4 / 209.7 | 0 | 5, 185.0–210.0 | 78.0–82.1 |
| `mi4_seg_4k` | 5 / 177.3 / 195.6 / 219.1 | 5 / 177.0 / 195.3 / 218.0 | 0 | 5, 177.3–219.1 | 67.7–71.2 |
| `mi4_seg_32k` | 5 / 197.7 / 198.2 / 198.8 | 5 / 197.4 / 197.9 / 198.5 | 0 | 5, 197.7–198.8 | 68.6–70.6 |
| `mi4_seg_128k` | 5 / 196.9 / 198.4 / 217.1 | 5 / 196.6 / 198.1 / 216.8 | 0 | 5, 196.9–217.1 | 68.7–70.4 |
| `mi4_pull` | 5 / 175.5 / 176.3 / 1 079.3 | 5 / 174.5 / 176.0 / 1 079.0 | 1, 1 079.3 | 4, 175.5–177.6 | 67.6–69.3 |
| `rs4_kill3_mion` | 5 / 197.6 / 199.1 / 220.8 | 5 / 197.3 / 198.8 / 220.5 | 0 | 5, 197.6–220.8 | 70.1–71.7 |
| `mi4_train_kill3` | 10 / 249.8 / 256.2 / 298.2 | 10 / 249.6 / 255.7 / 298.0 | 0 | 10, 249.8–298.2 | 77.5–86.3 |
| `mi4_train_kill2_kill3` 첫 죽음 | 5 / 92.9 / 98.9 / 274.9 | 5 / 92.6 / 98.6 / 274.6 | 3, 92.9–98.9 | 2, 274.0–274.9 | 76.5–81.2 |
| `mi4_train_kill2_kill3` 둘째 죽음 | 5 / 104.6 / 266.2 / 267.3 | 5 / 104.3 / 265.9 / 266.6 | 1, 104.6 | 4, 261.4–267.3 | 89.5–95.5 |
| `mi4_kill3_ow_nomirror` (mirror 끔, TCP) | 5 / 310.5 / 331.9 / 1 215.2 | 5 / 310.2 / 331.6 / 1 214.9 | 2, 1 212.6–1 215.2 | 3, 310.5–331.9 | 206.5–209.0 |
| `rs4_kill3` (mirror 끔) | 10 / 369.8 / 374.9 / 403.7 | 10 / 369.5 / 374.3 / 403.4 | 0 | 10, 369.8–403.7 | 265.8–276.4 |
| `rs4_kill1` (mirror 끔) | 5 / 376.3 / 377.7 / 379.0 | 5 / 376.3 / 377.6 / 379.0 | 0 | 5, 376.3–379.0 | 271.3–273.4 |
| `rs4_kill3_ckpt` (mirror 끔) | 5 / 377.9 / 391.5 / 400.4 | 5 / 376.8 / 390.7 / 400.1 | 0 | 5, 377.9–400.4 | 265.4–274.2 |

later 0번 열에는 두 경우가 섞인다 `[측정]`: 원래 프로세스가 zombie로 보인 빠른 활성화 6건(둘째 죽음 셀의 첫 죽음 n2, n4 76.6–77.3 ms; 학습 둘째 죽음 셀의 첫 죽음 n2, n3, n4와 둘째 죽음 n3 92.9–104.6 ms)과,
생존 rank 하나의 죽음 판정이 약 1 s 늦어 그동안 원래 프로세스가 이미 없어진 3건(`mi4_pull` n5, `mi4_kill3_ow_nomirror` n2, n5; 6절 2). 3절 끝의 보고 규칙대로 모드로 제외하지 않았다.
mirror 켬 길(4 KiB)의 활성화 뒤 부분 67.2–82.1 ms 대 mirror 끔 265.4–276.4 ms; 학습 모양 76.5–95.5 ms `[측정]`.

**FETCH 모형과의 차** `[측정]`: FETCH 75건(죽음 75: 4 KiB 덮어쓰기 셀 30, segment 15, 당기기 5, mirror 켬 회귀 5, 학습 20) 모두 모형보다 느리고 +0.27–+4.85%(±15% 띠 안).
셀별: `mi4_seg_4k` +1.41–+2.27%, `_32k` +1.18–+4.45%, `_128k` +0.78–+2.61%, `mi4_train_kill3` +1.27–+4.85%, `mi4_train_kill2_kill3` +0.98–+4.11%.

**입력 멈춤 최대** (`ckpt_pause_ms`, 시행마다 모든 프로세스의 최대) `[측정]`: 장애 없음 `mi4_none_ow` 6.750–8.151, `mi4_int_*` 7.098–8.358, `mi4_pull_none` 7.219–7.725,
`rs4_none_mion` 7.238–8.443, `rs4_none` 4.946–6.310, `mi4_train_none` 8.999–10.227 ms. kill 셀은 그 밖에 4.9–10.5 ms이고 예외가 다섯 시행이다(6절 4: 2 000.4 ms 셋, 1 004.9–1 006.2 ms 둘).

**lane 깨짐, DISARM, 계보** `[측정]`: 공백 밖 깨짐(`lane_broken_other`)과 DISARM(`disarm_other`)은 `mi4_overflow` 밖의 163시행 모두 0. 공백 안 깨짐은
`mi4_kill3_ow` 14, `mi4_kill1_ow` 8, `mi4_kill3_ckpt_ow` 8, `mi4_kill2_kill3_ow` 19, `mi4_seg_*` 25, `mi4_pull` 5, `rs4_kill3_mion` 8, `mi4_train_kill3` 20,
`mi4_train_kill2_kill3` 20줄(셀의 시행 합). `mi4_overflow`는 시행마다 84–87줄(모든 프로세스; 설계대로 공백 밖). `GIN/LN` 줄 0(428시행) `[측정: grep]`.

**비용** `[측정: cost.py]`: 240/240 유효, 셀(노드 × 지표 × 팔)마다 6. 섞기 차례는 k 홀수 off → on → self → peer, 짝수 그 반대(10 hold 모두). 단위 µs(지연), GB/s(대역).

| 받는 노드 | 지표 | off | on (기준) | mirror-self | mirror-peer | self 대 on | peer 대 on | 판정 |
|---|---|---|---|---|---|---|---|---|
| rain | lat4k | 11.260 (11.260–11.260) | 13.310 (13.310–13.310) | 20.480 (20.480–20.480) | 21.500 (21.500–21.500) | +7.170 µs | +8.190 µs | ≤ 12 µs 맞음 |
| sunny | lat4k | 11.840 (11.780–11.870) | 13.760 (13.760–13.790) | 22.340 (22.340–22.340) | 22.560 (22.560–22.590) | +8.580 µs | +8.800 µs | 맞음 |
| rain | lat256k | 40.960 (39.940–45.060) | 43.010 (41.980–49.150) | 74.240 (73.730–74.750) | 71.170 (70.660–71.680) | 1.726배 | 1.655배 | 보고만 |
| sunny | lat256k | 39.745 (39.520–39.810) | 41.395 (41.120–41.500) | 74.320 (73.700–75.330) | 70.255 (66.620–70.780) | 1.795배 | 1.697배 | 보고만 |
| rain | lat2m | 222.210 (222.210–222.210) | 223.230 (223.230–223.230) | 430.590 (430.080–431.100) | 417.280 (416.770–417.790) | 1.929배 | 1.869배 | 1.5–2.2 맞음 |
| sunny | lat2m | 221.180 (221.180–221.180) | 222.560 (222.300–222.820) | 426.270 (426.140–426.430) | 413.630 (413.470–413.700) | 1.915배 | 1.859배 | 맞음 |
| rain | bw256k | 5.447 (5.432–5.461) | 5.172 (5.172–5.185) | 3.277 (3.272–3.282) | 3.282 (3.277–3.287) | 0.634 | 0.635 | peer 0.45–0.70 맞음 |
| sunny | bw256k | 6.428 (6.419–6.438) | 6.021 (5.995–6.024) | 3.752 (3.750–3.759) | 3.799 (3.795–3.803) | 0.623 | 0.631 | 맞음 |
| rain | bw2m | 5.936 (5.932–5.945) | 5.891 (5.889–5.894) | 3.284 (3.282–3.285) | 3.283 (3.283–3.287) | 0.557 | 0.557 | 맞음 |
| sunny | bw2m | 7.096 (7.087–7.101) | 7.027 (7.020–7.033) | 3.870 (3.859–3.873) | 3.877 (3.874–3.882) | 0.551 | 0.552 | 맞음 |

(값은 중앙값과 6실행의 범위; self의 대역은 판정하지 않음.) `bw2m` 48실행 모두 `burst_reuse=1`, `bw256k`는 0 `[측정]`.

## 5. 셀별 시행 값 (판정에 걸린 셀만, `[측정]`)

**체크포인트 멈춤 중 kill** (`mi4_kill3_ckpt_ow`, n=5)

| 시행 | 죽은 체크포인트 C | 쓰인 K | 멈춤 안 생존 rank (없던 rank) | hold 시작 "gates odd since" ms (r0, r1, r2) | 앞 체크포인트 확정 | 대기, 데이터, 재실행 없음, 끝까지 | 억제 (셈/따로 센 값) | 복원 ms | 조건 |
|---|--:|--:|---|---|---|---|---|--:|---|
| n1 | 40 | 20 | 2 (r1) | 0.5, −0.0, 0.8 | 예 | 예 | r0 40/40, r1 40/40, r2 40/40 | 179.6 | 아니오 |
| n2 | 40 | 20 | 1 (r1, r2) | 0.5, −0.0, −0.0 | 예 | 예 | 40/40 셋 | 179.9 | 아니오 |
| n3 | 60 | 40 | 1 (r1, r2) | 0.3, −0.0, −0.0 | 예 | 예 | 40/40 셋 | 178.7 | 아니오 |
| n4 | 60 | 40 | 3 | 1.4, 0.6, 1.4 | 예 | 예 | 40/40 셋 | 198.8 | 예 |
| n5 | 60 | 40 | 2 (r0) | −0.0, 0.5, 1.3 | 예 | 예 | 40/40 셋 | 200.1 | 아니오 |

**둘째 죽음** (`mi4_kill2_kill3_ow`, n=5): 첫 kill(rank 2) 단계 182–205, 둘째(rank 3) 389–420; K 180/200과 380/400. 다시 무장 체크포인트 200(n2–n5), 220(n1),
`stored` 바이트 14 749 720 = 첫 저장과 같음(전체), 그 사이 void 0(5/5), 둘째 kill 전 다시 무장 3/3과 `cell_valid=1` 3/3(5/5). 억제는 두 죽음 모두 S = B, 남은 예산 0,
따로 센 범위 안(통로 30개) `[측정]`.

**학습 모양 rank 3 kill** (`mi4_train_kill3`, n=10): kill 단계 323–1 478(단계 안 1 212–7 881 µs), K = kill 앞 마지막 확정(2–20단계 앞), FETCH 48.3–159.4 MB
4 164–13 912 µs, 단계 맞춤 가져오기 2–20단계, 복원 249.8–298.2 ms, later 8–10번 `[측정]`.

## 6. 예측 밖의 관찰과 자료 문제 후보

1. **`ckpt_kill_ow`가 틀린 까닭은 복원이 아니라 "멈춤 안" 조건이다** `[측정, 추론]`. 다섯 시행 모두 대기, 데이터, 재실행 없음, 되살림, 앞 체크포인트 확정이 참이다.
   틀린 넷에서 빠진 생존 rank는 죽은 rank 3의 체크포인트 C에 대한 멈춤 줄이 아예 없다(예: n2의 r1, r2에는 `rank 3's checkpoint 40` 줄이 없고, 자기 체크포인트
   40이 `is void (a peer was declined or is held before it confirmed)`). 멈춤에 든 rank 9개도 그 멈춤이 자기 죽음 판정 줄 0.99–1.95 ms 뒤에 시작했다(같은 프로세스의 `mono_ms`, 시작 = 끝 − `pause_us`) `[측정: n1–n5]`.
   곧 rank 3이 멈춤 요청을 보내고 300 µs 뒤 죽는 시험에서, 요청이 생존 rank에 처리되는지가 죽음 판정과의 경주다 `[추론]`. 같은 계층의 mirror 끈 회귀
   `rs4_kill3_ckpt`는 5/5 모두 3/3이었다(C 93–112, 쓰인 K = C − 20). mirror 켬에서 이 경주가 왜 달리 끝나는지는 원자료로 가르지 못했다 `[미확인]`. 판정은 사전 등록 식대로 틀림이다.
2. **죽음 판정이 약 1 s 늦은 시행 셋** `[측정]`: `mi4_pull` n5의 rank 2, `mi4_kill3_ow_nomirror` n2, n5의 rank 1은 kill 때 소켓이 FIN이 아니라 `ECONNRESET`(liveness
   unknown)으로 닫혀, 다시 걸기가 두 번 거절된 뒤(`ECONNREFUSED`) 약 1 003–1 006 ms 뒤에 죽음을 판정했다. 그래서 복원 시간이 1 079.3, 1 215.2, 1 212.6 ms이다(한도 2 000 ms 안).
   `mi4_pull` n5에서는 그 rank가 짝이라 활성화가 1 010 ms 뒤에야 났다. `mi4_kill3_ow_sampled` n1의 rank 0도 `ECONNRESET`이었다(fallback 셀). 428시행에서 4번.
   pilot 2–4의 보고(감지 52건 모두 FIN, 3절 끝)와 다르다. 결과에서 복원 시간 최대를 쓸 때 이 셋을 따로 적는 편이 맞다.
3. **억제 수를 단계 줄로 따로 셀 때 한 단계 폭이 남는다** `[측정, 추론]`. mirror 켬에서 생존 rank의 죽은 rank 쪽 보내기는 INJECTED까지 게이트에 쉬므로 생존 rank의
   단계는 죽은 rank의 그 단계 put을 이미 받았어도 끝나지 않는다(예: `mi4_kill1_ow` n2의 rank 2, 3은 단계 138 줄을 INJECTED 줄 5–30 µs 뒤에 낸다). 그래서 S_q로 하한만 정해지고,
   억제 값은 4 KiB 셀과 학습 셀의 통로 가운데 일부에서 하한 + 2(한 단계)이다. 모든 통로가 [하한, 하한 + 2] 안이고, rank 0 통로는 hold 줄의 X − 2(K+1)과 100/100 정확히 같으며,
   데이터와 신호 값(`sig_exact=1`)이 모두 맞아 겹치거나 빠진 메시지가 없음을 받친다. mirror 끈 회귀(`rs4_*`)는 모든 통로가 하한과 같다.
4. **2 s 입력 멈춤** `[측정]`: `mi4_kill3_ckpt_ow` n1, n2에서 rank 0의 체크포인트 40이 `no PAUSED from every peer within NCCL_GIN_RESTORE_PAUSE_MS`로 거절될 때까지 rank 1, 2가
   2 000.35–2 000.42 ms 입력 멈춤에 있었고, `mi4_kill3_ow_sampled` n1에서 rank 2의 체크포인트 137에 rank 0, 1이 2 000.37–2 000.42 ms 멈췄다. `mi4_kill3_ow_nomirror` n2, n5의
   rank 1은 2의 늦은 판정 때문에 1 004.9–1 006.2 ms 멈췄다. 판정 셀이 아니지만(멈춤 문턱은 장애 없는 셀에만), 멈춤 시한 거절이 application을 시한만큼 세운다는 18절의 한계가 본 실행에서 실제로 났다.
5. **mirror 없는 대조의 틀린 값은 독 값이 아니다** `[측정]`: 다섯 시행 모두 `recv_poison=0`, `dev_poison=0`이고 받은 칸 1 440–1 443개가 기준과 다르다. 다른 단계 값이 들어간 꼴이다 `[추론]`.
   틀린 상태가 생존 rank로 퍼져 생존 셋도 `x_match=0`(`recv_bad` 1 378–1 384). 판정식(`nomirror_corrupt`)의 조건 안이다.
6. `mi4_overflow`에서 rank 3은 kill 전 체크포인트 120에 "armed"로 적혔지만(생존 셋) 곧 DISARM되어 hold는 5/5 시작하지 않았다(degraded 길) `[측정]`.

## 7. `SCORE.md`, `trials_scored.csv`와 견줌 (1–6절을 쓴 뒤에 처음 열었음)

`SCORE.md`(22:54:52)와 `trials_scored.csv`(429줄 = 머리 1 + 428)를 읽었다. 비교 스크립트 `compare.py`(시행 키 = csv의 `id` 열).

**판정과 k/n: 다른 곳 없음.** 예측 53개의 판정이 모두 같다(`ckpt_kill_ow` 틀림, 만족하지 않은 시행 n1, n2, n3, n5도 같음; `cost_mirror_lat` 보고만; 나머지 맞음).
셀마다 계획, 실행, 판정 수와 "따로 셈 없음"도 같고, 시행 수 428, 예측 파일 sha256이 `PREREG.txt`와 같다는 머리말도 맞다. 비용 240실행의 값은 소수 셋째 자리까지
240/240 같고 표의 중앙값과 차, 비도 같다 `[측정]`.

**시행별 열: 판정식에 쓰이는 값은 판정 셀에서 모두 같다.** 같은 이름의 열 5 889칸을 견줬다. 판정 셀의 `wait_held`, `data_equal`, `ow_data_equal`, `no_reexec`,
`revived_done`, `suppress_ok`, `from_pool_ok`, `export_source_bytes`, `import_pool_bytes`, `paced_ok`, `inj_from_n`, `reimage_ok`, `second_ok`, `die_in_pause`, `ckpt_before`,
`fetch_us`, `fetch_bytes`, `pool_max_bytes`, `restarts`, `third_slot`, `pulls_sent`, `pulls_taken`, `later_n`, `nomirror_*`, `degraded_release`, `fallback_release`, `hold_started`,
거절 셀의 `resume_err_all`, `reason_same`, `ff_fallthrough`, `nomacro_reason`, `refused_ran_ok`, 회귀 실행기 열, `lineage_warn`, `steps`, `wall_s`가 모두 같다.

**값이 다른 열(판정에는 닿지 않음)**:

| 열 | 다른 칸 | 차이 | 까닭 |
|---|--:|---|---|
| `restore_time_ms`, `_1`, `_2`, `post_activate_ms*` | 100 죽음 모두 | 채점기가 0.02–1.31 ms 작음 | 끝점이 다름. 채점기 = 마지막 `restore round with rank d published` 줄(그 정의로 다시 세면 단일 죽음 80/80이 0.1 ms까지 같음), 이 재계산 = 마지막 `restored as incarnation 1` 줄(gin-restore 선례). 3절 "마지막 생존 rank의 게시 줄"은 두 줄 모두로 읽힐 수 있다 `[추론]`. 판정 한도(1 000, 2 000 ms)와 거리가 멀어 판정은 같다 |
| `ckpt_pause_ms` | 35/142 (kill 셀만) | 0.01–3.26 ms | 어느 프로세스 줄을 넣는지. 채점기는 죽은 rank의 멈춤 줄을 빼는 것으로 보인다(그렇게 다시 세면 28/35가 같아짐) `[추론]`. 장애 없는 셀 32시행(판정에 쓰는 15시행 포함)은 모두 같다 |
| `lane_broken`, `lane_broken_other`, `broken_other`, `disarm_other` | `mi4_overflow` 5 | 채점기 63–66 / 126–132 대 84–87 | 채점기는 생존 rank 줄만 세고 DISARM은 두 종류 줄을 세는 것으로 보인다 `[추론]`. 판정은 `lane_broken ≥ 1`이라 같다 |
| `disarm_n` | 62 (kill 셀) | 채점기가 두 배 | 줄 종류 정의 차이 `[추론]`. 판정에 쓰는 `mi4_pull_none`은 둘 다 0 |
| `restore_count` | 100 (kill 셀) | 채점기 3, 6 대 18, 33 | 이 재계산은 줄 수를 더함. 0인지만 판정에 쓰고 장애 없는 셀은 둘 다 0 |
| `strict_forced` | 10 (두 죽음 셀) | 20 대 24 | 이 재계산은 둘째 예비 프로세스의 MR 줄 4개를 넣음. 판정 셀(`rs4_none`)은 같다 |
| `tcp_image_bytes`, `tcp_segment_bytes` | 30 (mirror 끈 kill 셀) | 이 재계산이 TCP FETCH와 log export 바이트를 더함 | 판정 셀(mirror 켬)은 모두 0으로 같다 |
| `no_reexec` | 15 (fail-fast, fallback 셀) | 0 대 1 | 이 재계산은 `steps_done`=600을 요구. 그 셀에서 판정하지 않음 |
| `ff_fallthrough`, `refused_ran_ok` | 거절 셀 밖 | – | 이 재계산의 열이 거절 셀 밖에서는 뜻이 없음 |

**판정이 아닌 다른 곳.**
1. `trials_scored.csv`의 `stem` 열이 비용 행 240개에서 홈 디렉터리를 포함한 절대 경로다(`/home/…/results/20261015_main/cost_mirror_…`). 회귀 행의 `build` 열도 상대 경로
   (`../../rs-bundle/mi6/lib/mi`). 주소는 아니지만 공개 표로 옮길 때는 `id` 열을 쓰는 편이 낫다(gin-restore QA의 같은 지적).
2. `SCORE.md` 비용 대역 표의 "기준 팔과의 차" `+1.890 (+36.5%)`는 on − 팔(나쁜 쪽이 양수)이다. 지연 표의 차(팔 − on)와 부호 규칙이 달라 읽을 때 헷갈릴 수 있다.
3. `SCORE.md`는 복원 시간의 끝점 정의를 적지 않는다. 결과 문서에는 "게시 줄 = `restore round … published`"인지 적어 두는 편이 맞다.

## 8. 넘겨 줄 요약

원자료 428(복원과 거절 168, 회귀 실행기 20, 비용 240)을 채점기 없이 다시 셌다. 고정 파일은 태그와 같고(sha256 일치), 제외 0, STOP 파일 0, 새 mlx5 줄 0,
펌웨어 실패 증가 0, 남은 프로세스 0, `GIN/LN` 줄 0이다. 예측 53개의 판정이 `SCORE.md`와 모두 같다: 체크포인트 멈춤 중 kill(`ckpt_kill_ow`)만 틀림(1/5; 복원 자체는 5/5 맞고
"생존 셋이 모두 그 멈춤 안" 조건이 2, 1, 1, 3, 2), 256 KiB 지연은 보고만, 나머지 51개 맞음. 복원 시간은 4 KiB mirror 켬 176.2–219.1 ms(약 1 s 늦은 판정의
`mi4_pull` n5 1 079.3 ms 하나 밖), 학습 249.8–298.2 ms, 두 죽음 셀 76.6–274.9 ms; FETCH 75건 모두 모형보다 +0.27–+4.85%. 비용은 4 KiB +7.17–+8.80 µs,
2 MiB 1.859–1.929배, 묶음 대역 0.552–0.635. 시행별 열에서는 복원 시간의 끝점(채점기는 `restore round … published`, 이 재계산은 `restored as`; 0.02–1.31 ms 차),
입력 멈춤에 넣는 프로세스, 넘침 셀의 줄 세기 범위가 다르나 판정은 바뀌지 않는다. 자료 문제 후보: 소켓이 `ECONNRESET`으로 닫혀 죽음 판정이 약 1 s 늦은 시행 넷(복원 셋은
1 079–1 215 ms), 멈춤 시한 거절로 생존 rank가 2 000 ms 멈춘 시행 셋, 그리고 `trials_scored.csv`의 절대 경로 열.
