# notes_test.md — gin-mirror test 갈래 (exp/gin-mirror-test)

impl/PARALLEL.md의 기록 규칙대로, EXPERIMENT.md 12절에 들어갈 행과 인터페이스 밖에서 정한 것을 여기 쌓는다. 통합 때 메인
세션이 12절로 옮기고 이 파일을 지운다. 이 갈래는 `impl/test/` 아래 새 파일만 만들었고 `restore/`는 읽기만 했으며 라이브러리를
빌드하지 않았다.

## 12절에 넣을 행 (날짜, 무엇을, 근거)

| 시각 | 무엇을 했나 | 결과와 근거 |
|---|---|---|
| 2026-10-13 | test 갈래(시험과 비용) 구현(DRAFT, 빌드됨, CPU 자체 시험함, 클러스터 실행 없음). gin-restore의 `restore/impl/test/`를 바탕으로 `impl/test/`에 새 파일로: 드라이버 `gin_mi.cu`(gin_rs.cu + `RS_OVERWRITE` 4 KiB 덮어쓰기 모드와 `RS_TRAIN` 학습 모양 모드, local 완료 직후 독 값 덮어쓰기, 받는 고리 R, 학습 모양의 상태 이력을 따로 등록), 비용 diff `gin_ts2_mi.diff`(`GIN_TS_MAN_MIRROR` self/peer 둘째 put을 문맥 1로, `GIN_TS_BURST_REUSE`), 실행기 `run_mi.sh`(예비 프로세스 둘, seed kill, 호스트 메모리 시작 검사, KILL_AFTER_STABLE, RS_SET 이름 강제), `cells_mi.sh`·`cells_mi.json`·`hold_mi.sh`·`chain_mi.sh`·`run_cost_mi.sh`·`deploy_mi.sh`·`build_mi_test.sh`·`rs_set_mi.sh`, 채점기 `rows_mi.py`·`score.py`·`predictions_mi.csv`·`selftest_mi.py`, `PILOT_MI.md` | 드라이버는 i5 설치 헤더로 sm_75·sm_86 경고 0 컴파일(md5 아래). `bash -n` 9개 통과, `selftest_mi.py`(파서 명령, 모든 rs 셀의 실행기 dry 설정, seed 결정성, RS_SET 검사, 채점기 A–D) 통과. `impl/test/`, `impl/notes_test.md` |
| 2026-10-13 | 독립 리뷰(같은 모델의 다른 에이전트, 읽기만; 버그 5, 의심 14, 문체 4). 반영: (1) bw2m 비용 값이 지연(µs)으로 남아 대역 판정이 거꾸로 → 모든 bw 지표를 GB/s로 다시 셈. (2) `mi4_seg_32k`, `_128k`의 lane이 1 MiB라 넘침 → 2 MiB, 6 MiB. (3) `nomirror_detect`가 죽음 기준 → 3절대로 FALLBACK + 2 000–2 500 ms. (4) mirror 셀에서 Resume 거절이 제외되지 않음 → `resume_refused`면 `config`. (5) mirror 줄을 고정 순서 정규식으로 읽음 → 키 글자 앞머리만 맞추고 key=value는 순서 없이 읽음. 의심 반영: 둘째 죽음 판정을 3절대로(되살린 짝에 전체 이미지 확정, 그 사이 void ≤ 1, 둘째 kill 전 모든 생존 rank 다시 무장, 죽음마다 복원 ≤ 2 000 ms, 둘째 FETCH가 되살린 짝에서, 되살린 rank 2를 생존 rank로 셈); 둘째 예비 프로세스 시작 실패 제외; mirror와 checksum 설정 불일치 제외; 단계 맞춤 가져오기 차례(`paced_ok`); 비용 규칙 `within_us`, `ratio`(3절의 +2.5 µs와 0.40–0.60 그대로)와 판정 지표만 자료 부족 검사; mirror 팔은 rank 0의 `mirror summary`(broken=0)가 있어야 유효; `pool_vs_interval`의 비 2 ± 25%와 `seg_restore_slope`의 중앙값 증가를 판정식에; `store_rdma`를 학습 셀과 mirror 켠 4 KiB 셀 모두로; 당기기 20단계마다 ≥ 1과 kill 셀의 DISARM 0; gin-restore 7절의 복원과 거절 셀을 그 이름 그대로 mirror 끔 @mi로(R2, R3, 예측 `rg_*`), mirror 켠 회귀는 `_mion`; pilot hold P2, P3; 학습 kill의 단계 안 지연 0–8 ms, `mi4_overflow` 예비 프로세스 기다림 30 s, 학습 시행 한도 150 s; 거절 셀 셋을 이유 글자로 나눔; 문체: 손 mirror 팔의 kv 꼬리표, hold 머리 주석, gin-restore 묶음 재사용 거절 | 리뷰 결과는 이 갈래의 기록. 고친 뒤 자체 시험 다시 통과, 비용 드라이버 다시 빌드(md5 아래) |

## 빌드됨 (md5, i5 설치 헤더로 빌드; 통합 헤더로 다시 빌드하면 바뀔 수 있음)

- i5 헤더 digest `6a1a3f29`, 연구 libnccl `4811f28f`(읽기만), gin_ts2.cu `1779db9d`, winflags.diff `fb9d2d8d`,
  gin_ts2_mi.diff `0e5aef6c`, gin_mi.cu `556804c0`, gin_mr.cu `a6a526ad`.
- `gin_mi` (macro) `c382a2db`, `gin_mi_nomacro` `75e15e13`, `gin_ts2_mi` (macro) `a0d54cf0`,
  `mr/ff/gin_mr` `9c56307b`, `mr/hold/gin_mr` `3d2857ae`. 모두 sm_75·sm_86 SASS 있음, 경고 0.
- "빌드됨"이고 클러스터에서 돌리지 않았다("시험함"은 CPU 자체 시험뿐). 통합 뒤 메인 세션이 통합 헤더로 다시 빌드한다.

## 의존하는 라이브러리 줄 형식 (scorer가 읽는 것)

`rows_mi.py`가 파싱하는 줄은 공유 헤더가 정한 것뿐이다(PARALLEL.md). mirror 줄은 `"GIN/MI: rank %d: "` 뒤의 키 글자를
앞머리로만 맞추고 나머지 key=value를 순서 없이 읽는다(구분자나 덧붙인 키에 견딤).

- `impl/rs_mirror_api.h` "line keys the test branch reads"(모두 `"GIN/MI: rank %d: "`로 시작, `" mono_ms=%.3f"`로 끝):
  `lane to rank %d broken (%s): DISARM`, `segments of rank %d restarted at its checkpoint %lu`,
  `CKPT_PULL to rank %d`(seg=, fill_pct=), `drain for rank %d`(senders=, queries=, drain_us=),
  `fetch for checkpoint %lu from buddy rank %d`(image_bytes=, segment_bytes=, extents=, fetch_us=),
  `export to rank %d`(entries=, mirror_entries=, mirror_bytes=, source_bytes=, first_step=, last_step=),
  `import step %lu`(entries=, pool_bytes=, signals=, import_us=), `import done`(steps=, pool_bytes=, left=),
  `INJECTED sent`(step=, survivors=), `INJECTED from rank %d`(step=, state=, gate_odd_ms=),
  `mirror summary`(switches=, rollbacks=, restarts=, third_slot=, max_live_bytes=, pulls_sent=, pulls_taken=, broken=, absorbed=).
- `impl/rs_store_api.h` "line keys": `checkpoint %lu stored at buddy rank %d`(slot=, bytes=, d2h_us=, write_us=),
  `store summary`(writes=, failed=, requests=, tcp_image_bytes=, tcp_segment_bytes=).
- gin-restore의 줄(rs_layer.diff; rows_rs.py로 그대로 씀): `rank %d judged dead (cause=%s)`,
  `restore round with rank %d published (...)`, `checkpoint %lu stable at buddy rank %d (...)`, `checkpoint %lu is void (%s)`,
  `rank %d armed at its stable checkpoint %lu`, `hold of rank %d started`, `rank %d restored as incarnation %u ...`,
  `the restore of rank %d (incarnation %u) is given up (%s) ...`(FALLBACK), `suppress peer= ... budget= ... suppressed=`,
  `input pause for rank %d's checkpoint %lu ended (...) pause_us=`, `rank %d disarmed (...)`,
  `test switch NCCL_GIN_RESTORE_TEST_DIE_IN_CKPT: dying %d us after the pause request of checkpoint %lu (stable checkpoints before: %d)`.

### 메인 세션에 알림 (통합 때 확인할 것)

1. **`nomirror_detect`의 이유 글자.** 음성 대조 `mi4_kill3_ow_sampled`는 생존 rank의 FALLBACK 줄(`... is given up (%s) ...`)의
   `%s`에 "source buffer changed"(rs_log_api.h `gdakiRsLogXEnd.why`)가 들어가는 것에 기댄다. 리뷰는 내보내기 실패가
   `"the log export failed: %.120s"`로 FALLBACK 이유에 실린다고 읽었다 `[추론]`. 다른 글자면 알려 주면 정규식을 맞춘다.
2. **재기만 하는 모드의 mirror 팔.** (가) `NCCL_GIN_RESTORE_LOG_MEASURE_MIRROR=self|peer`에 `NCCL_GIN_RESTORE_MIRROR=1`도
   필요한지(실행기는 둘 다 준다). (나) 3 000 × 2 MiB(lat2m)처럼 lane L보다 훨씬 많이 보내는 측정에서 lane을 어떻게 돌려 쓰는지
   (체크포인트 멈춤이 없어 segment 바꾸기가 없다). 넘쳐 깨지면 mirror 쓰기가 나가지 않아 비용이 낮게 잡힌다. 그래서 mirror
   팔은 rank 0의 teardown `mirror summary`가 broken=0일 때만 유효한 실행으로 센다(없으면 `cost_invalid`). 측정 모드도 그
   줄을 찍어야 한다.
3. **`pool_vs_interval`의 값.** 3절은 "lane마다 segment 최대 채움"이고 헤더 줄 키에는 `max_live_bytes`(짝이 가진 살아 있는
   바이트의 최고)만 있다. 둘은 간격에 함께 비례하나 같은 값은 아니다 `[추론]`. 정확히 lane 채움이 필요하면 mirror summary에
   `max_fill=` 키를 더해 달라.
4. **lane 다시 켜짐.** 둘째 죽음의 "보내는 rank마다 rank 3의 lane이 다시 켜짐"은 줄이 없어 생존 rank의 "rank 3 armed" 줄로
   대신한다(무장 가능 PAUSED가 mirror 바꾸기 성공을 요구함, rs_mirror_api.h `gdakiMiPausedArmable`) `[추론]`.

## 인터페이스 밖에서 정함 (test 갈래가 정한 것, 라이브러리 인터페이스 아님)

1. **드라이버 독 값 규칙** `gin_mi.cu`: 보낸 칸을 flush 반환 직후 `poisonWord(rank, dst, step)`(상위 16비트 0xDEAD)과
   0xA5로 덮고, 받은 칸의 첫 낱말이 그 표시이고 다음 8바이트가 0xA5이면 독으로 센다(`isPoison`). 시험 전용 규칙이다.
2. **학습 모양의 상태 이력과 받는 고리**: 창 크기(보내는 칸 상대마다 하나 6 MiB, 받는 고리 R = 4로 24 MiB)를 지키려고
   상태 이력 x(0..S)를 창 밖 버퍼에 두고 `ncclGinRestoreRegister`로 둘째로 등록한다(단계 카운터가 첫째, 모든 rank 같은
   차례). 요구 14는 구조로 지킨다: 단계 s 커널은 신호 s % 2의 문턱을 기다리고 고리 자리 s mod R만 읽으며, 보내는 rank는
   많아야 한 단계 앞서므로(R ≥ 3) 다른 단계의 put이 그 자리를 덮지 않는다.
3. **비용 드라이버** `gin_ts2_mi`: 재기만 하는 모드의 mirror 팔(off/on/mirror-self/mirror-peer)은 `GIN_TS_MAN_MIRROR` 없이
   돌고 mirror 쓰기는 라이브러리의 측정 모드가 낸다. `cost_man.md`의 손으로 하는 mirror 팔(one/man-self/man-peer)은 드라이버가
   둘째 put을 내는 실행 가능성 확인이고 feas 폴더(`run_mf.sh`)가 돌린다. 둘 다 이 드라이버 하나다. `cost_man.md`와 다른 점
   하나: 문맥 1에는 그 반복의 묶음을 울릴 신호가 없어 묶음 모드의 마지막 둘째 put만 모으지 않고 낸다(반복마다 WQE K개와
   doorbell 하나로 문맥 0과 같음). `GIN_TS_MAN_MIRROR` 없을 때도 `txBody`가 둘째 `ncclGin`과 분기 하나를 더 가지므로
   gin-restore 비용 셀의 gin_ts2와 바이트까지 같지는 않다: 비교는 mirror 가족 안에서만 한다.
4. **셀과 반복 수(DRAFT)** `cells_mi.json`: `mi4_pull`을 `mi4_pull_none`(장애 없음)과 `mi4_pull`(kill)로 나눔(한 채점 키에
   두 설정을 못 섞음). `mi4_refuse_sl`(S가 rank 사이에서 다름, Resume 조건 39)을 거절 셀에 더함(과제의 "S/L mismatch").
   gin-restore 회귀(mirror 끔)는 그 셀 이름과 env 그대로 @mi(R2, R3)라 mirror 켠 회귀는 `rs4_none_mion`, `rs4_kill3_mion`.
   4 KiB hold는 G1(복원과 대조)과 G3(segment, 간격, 당기기, 넘침)로 나눔. `DIE_SEED`의 `mi-v1`은 자리값(사전 등록 때 고정).
   `mi4_kill2_kill3_ow`의 kill 단계는 7절의 "200 근처, 400 근처"를 180–220, 380–420으로 둠.
5. **비용 규칙** `score.py` cost_eval: 셀 칸 `cost:<가족>:<팔>:<지표>`로 판정할 지표를 고르고, 규칙 `within_us:<x>`(3절 4 KiB
   +2.5 µs)와 `ratio:<lo>-<hi>`(3절 대역 0.40–0.60)를 더함. 5회 미만의 자료 부족은 판정하는 지표에서만 본다.
6. **RS_SET 강제** `rs_set_mi.sh`: gin-mirror는 첫 묶음 경로를 쓰지 않으므로 빈 RS_SET을 거절하고, `deploy_mi.sh`는
   gin-restore 묶음(lib/rs, rstest 등이 있는 이름)에 넣지 않는다. 배포는 `~/rs-bundle/<RS_SET>/{lib/mi,lib/mip,mitest,mr}`.
7. **호스트 메모리 시작 검사** `run_mi.sh`: 노드마다 (pool + 저장소 + D2H 버퍼 + 예비 프로세스 FETCH 버퍼) + 1 GiB를
   MemAvailable과 견주고 모자라면 시행을 시작하지 않고 exit 5(8절; hold가 `STOP_mem`). 크기는 헤더와 gin_mi의 창 크기에서
   어림한 것이라 실제 고정 메모리는 pilot이 다시 본다.
8. **학습 시행 한도** `hold_mi.sh`: `RS_TRAIN_BOUND_S` 기본 150 s(8절 초안 120 s; fallback한 학습 시행은 예비 프로세스가 120 s를
   기다려 약 125–130 s). pilot의 벽시계로 사전 등록 때 고정.
9. **당기기 판정** `pull_no_disarm_none`의 "20단계마다 ≥ 1"은 모든 rank의 `pulls_sent` 합 ≥ 단계 / 20으로 읽는다(받는 rank마다가
   아님; 너그러운 쪽).

## 열린 항목 (open items)

- 위 "메인 세션에 알림" 넷.
- 라이브러리 줄의 실제 꼴, 재기만 하는 모드의 mirror 팔, 단계 맞춤 가져오기의 차례는 통합 뒤 pilot이 처음 본다.
- 비용 문턱, seed, 반복 수, 시행 한도는 pilot 뒤 사전 등록에서 고정.
- `gin_mi_nomacro`의 매크로 없는 장치 코드가 hk와 같은지는 dev 갈래의 기계어 비교(ident)가 본다(이 갈래 밖).
- 둘째 죽음 셀에서 되살린 rank 2가 rank 3의 예비 프로세스 주소를 아는지(rank 3이 Resume 교환으로 알린 주소가 rank 2의 초기화
  기록에 들어 있어야 함) `[미확인]`: pilot P1의 `mi4_kill2_kill3_ow`가 처음 보인다.
