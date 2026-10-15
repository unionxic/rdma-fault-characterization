# gin-mirror 구현과 실행 메모

[README.md](README.md)의 연구 내용 밖에 있는 계층, 빌드, 배포, 실행, 채점, 원자료를 짧게 모았다. 설계와 기록은 [EXPERIMENT.md](EXPERIMENT.md)의 해당 절이
기준이다(설계 9절, 실행 기록 12절, 결과 15절).

## 계층

| 빌드 | 파일 | 무엇을 | 자세히 |
|---|---|---|---|
| GIN `mi`(연구) | [impl/mi_layer.diff](impl/mi_layer.diff)(빌드 ln4, md5 `dcd30859ac6db214e37475c527c37e2f`, 9 114줄; gin-restore i5 위) | mirror 쓰기(mirror 문맥의 따로 된 QP, 완료 따로 세기), 짝 호스트의 pool(segment 자리 셋, lane, 당기기, 넘치면 DISARM), RDMA 저장소(체크포인트 올리기와 FETCH), 단계 맞춤 가져오기, 끝점 갱신, 짝 복원 뒤 전체 이미지와 다시 무장, 계보 | EXPERIMENT.md 9.1–9.6, 9.9절 |
| GIN `mip`(운영) | 같은 소스에 `-DNCCL_GIN_TS_PRODUCTION` | 비용 셀의 라이브러리. 연구 빌드의 시험 스위치와 일부 줄이 없음 | 9.8절, 12절의 빌드 행 |
| 장치 쪽 | `mi_layer.diff` 안의 장치 헤더 둘 | 빌드 매크로 `NCCL_GIN_RESTORE_DEVICE`를 켠 프로그램만 mirror 길을 가진다. 매크로 없는 프로그램 넷의 기계어는 hk, i5와 SASS와 자원까지 같음(빌드 ln4에서 8/8) | 12절의 ln4 행 |

- 재현: 순정 NCCL v2.32.3-1 + `../remaining/gin_transparent_hr.diff` + `../../../gpu-detect/hw_layer.diff` + `../../../gpu-detect/hk_layer.diff` +
  `../restore/impl/rs_layer.diff`(md5 `f005bb67`) + `impl/mi_layer.diff`. 이 라이브러리와 쓰는 모든 프로그램은 이 계층의 헤더로 빌드한다(측 표와 공유 헤더가 바뀜).
- **계보 헤더** [impl/rs_lineage_api.h](impl/rs_lineage_api.h)(md5 `887259ba`): 화신(논리 rank를 맡은 프로세스의 번호)을 적는 두 곳(hold 칸의 화신, 아는 화신)을 한
  번에 읽어 국면(LIVE, HOLD_WAIT, HOLD_SUCC, ENDED, BAD)과 보기를 만들고(`gdakiLnViewOf`), 메시지가 실은 화신을 넷(CURRENT, HELD_OLD, STALE, FUTURE)으로
  가른다(`gdakiLnClassify`). 화신 비교만 바꾸고 상태 조건, wire, 장치 코드, 측 표는 그대로다. 정상 실행에서 나오지 않는 일에만 `GIN/LN: ` 줄을 하나 남기고(채점
  열 `lineage_warn`), 그 줄에는 채점기가 읽는 글자가 없다. 호스트 파일에만 바이트 그대로 붙고 `BR=ln build_mi.sh api`가 견준다. 단위 시험
  [impl/mi_unit_lineage.cc](impl/mi_unit_lineage.cc)의 oracle은 옛 판정과 새 판정을 정당한 모든 보기에서 견준다(9.9절).
- 공유 인터페이스: [impl/rs_mirror_api.h](impl/rs_mirror_api.h), [impl/rs_store_api.h](impl/rs_store_api.h)와 gin-restore에서 판 2로 넓힌
  `rs_log_api.h`, `rs_hold_api.h`, `rs_ckpt_api.h`, `rs_spare_api.h`(갈래 분담은 [impl/PARALLEL.md](impl/PARALLEL.md)).

## 빌드와 배포 묶음

빌드 트리는 세션 스크래치의 `agent_mi_fix/`(pilot 1까지는 `agent_mi_int/`)이고, [impl/build_mi.sh](impl/build_mi.sh)
(`BR=<dev|host|store|spare|test|int|fix|ln> build_mi.sh <setup|paste|api|mi|mip|unit|ident|diff|info>`, 머리 설명이 단계마다의 뜻)가 만든다. 시험 driver는
[impl/test/build_mi_test.sh](impl/test/build_mi_test.sh)(`MITREE`, `MIOUT`, `COSTOUT`, `MROUT`), 배포는 [impl/test/deploy_mi.sh](impl/test/deploy_mi.sh)가 두 노드의
새 디렉터리 `~/rs-bundle/<묶음>/`에 하고 앞뒤 md5와 ldd를 확인한다(있는 이름과 gin-restore 묶음은 거절).

| 묶음 | 빌드 | 계층 diff md5 | 연구 libnccl | 운영 libnccl | `gin_mi` | `gin_ts2_mi` | 쓴 곳 |
|---|---|---|---|---|---|---|---|
| `mi1` | i2(통합) | `e27998db` | `1b50d11b` | `a34db6e6` | `a1b84951` | `149cb366` | pilot 1 |
| `mi2` | i3(pilot 1의 결함 A, C, D 고침) | `dfaddae8` | `feefaf6d` | `2e4008e6` | `7e522afd` | `ad090844` | pilot 2 |
| `mi3` | i4(고침 묶음 리뷰의 사전 등록 전 항목) | `4dd2927a` | `c89ce744` | `12a0edec` | `5887dfea` | `05093a69` | pilot 3 |
| `mi4` | ln2(계보 + 결함 E 고침) | `23e5407b` | `dac86bed` | `2bb1a973` | `0603ac4d` | `faaac703` | pilot 4 |
| `mi5` | ln3(리뷰와 pilot 4의 고침) | `3e559c86` | `e927457a` | `58d7ff3f` | `0d0dd90b` | `7e3a2ef6` | pilot 5 |
| `mi6` | ln4(멈춤 시한 거절의 사용자 결정) | `dcd30859` | `c74e6ffb60b9ab8e959a7cfc89b7f55c` | `21b0be95b04f4ebeeafd0e6e92eecba0` | `4f7ba8bfb5596912f055480763412f59` | `f402e72a4534a5ce8dab8ddb5ba8d507` | pilot 6, 본 실행 |

`mi6`의 나머지 driver: `gin_mi_nomacro` `89878018aaf2c5c3e3cd792881b4f757`, `mr/ff/gin_mr` `9fcd8239982ebb5a6adfdfbd613232ad`, `mr/hold/gin_mr`
`c5575a76b48d4a953c83bc6c6c0e54d7`(설치 헤더 digest `65fdf19b`). 사전 등록이 고정한 md5는 [PREREG.txt](PREREG.txt)이고, 본 실행 시행 meta의 md5가 188/188,
240/240 같았다. 빌드 ln1(계보만)은 배포하지 않았다. 묶음마다의 배포 명령과 앞선 묶음의 나머지 md5는 [impl/test/PILOT_MI.md](impl/test/PILOT_MI.md)의 "상태"와
"메인 세션 명령".

## 파일

| 파일 | 하는 일 |
|---|---|
| [impl/mi_unit_dev.cc](impl/mi_unit_dev.cc), [impl/mi_unit_host.cc](impl/mi_unit_host.cc), [impl/mi_unit_store.cc](impl/mi_unit_store.cc), [impl/mi_unit_spare.cc](impl/mi_unit_spare.cc), [impl/mi_unit_lineage.cc](impl/mi_unit_lineage.cc) | 순수 영역의 CPU 단위 시험(ASan, UBSan; `build_mi.sh unit`) |
| [impl/ff_cmp_mi.sh](impl/ff_cmp_mi.sh), [impl/exact_cmp_mi.sh](impl/exact_cmp_mi.sh) | 매크로 없는 프로그램과 라이브러리 장치 객체의 기계어를 hk, i5와 비교(`build_mi.sh ident`) |
| `impl/mi_layer_{dev,host,store,spare}.diff` | 병렬 구현 갈래의 diff(통합 전, 기록) |
| [impl/test/gin_mi.cu](impl/test/gin_mi.cu) | 시험 workload: gin-restore의 4 rank driver에 덮어쓰기 모드(`RS_OVERWRITE`)와 학습 모양 모드(`RS_TRAIN`), 예비 프로세스 둘 |
| [impl/test/gin_ts2_mi.diff](impl/test/gin_ts2_mi.diff), [impl/test/run_cost_mi.sh](impl/test/run_cost_mi.sh) | 비용 driver의 mirror 팔(재기만 하는 모드의 self, peer)과 비용 실행 하나 |
| [impl/test/run_mi.sh](impl/test/run_mi.sh), [impl/test/cells_mi.sh](impl/test/cells_mi.sh), [impl/test/cells_mi.json](impl/test/cells_mi.json) | 시행 하나(기록한 PID로만 kill, 예비 프로세스, seed로 뽑는 kill 단계, 수신 시각 도장), 셀 실행, 셀과 hold 정의(사전 등록으로 고정) |
| [impl/test/hold_mi.sh](impl/test/hold_mi.sh), [impl/test/chain_mi.sh](impl/test/chain_mi.sh), [impl/test/rs_set_mi.sh](impl/test/rs_set_mi.sh) | hold 하나(앞뒤 스냅숏, STOP 규칙, rain BAR1 시작 검사, QUERY_QP 상한, 이어 돌리기), hold 사슬, 배포 묶음 이름 검사 |
| [impl/test/rows_mi.py](impl/test/rows_mi.py), [impl/test/score.py](impl/test/score.py), [impl/test/predictions_mi.csv](impl/test/predictions_mi.csv), [impl/test/selftest_mi.py](impl/test/selftest_mi.py) | 시행별 열(gin-restore의 `rows_rs.py` 위에 mirror 열), 채점(사전 등록한 판정식), 자체 시험 |
| [impl/test/PILOT_MI.md](impl/test/PILOT_MI.md) | pilot이 보여야 할 것, 고정한 값, 배포와 실행 명령 |
| [feas/](feas/) | 실행 가능성 확인 1, 3, 4의 도구(`mirror_feas`)와 확인 2의 팔 설명([feas/cost_man.md](feas/cost_man.md)) |

## 실행

- 모든 클러스터 실행은 메인 세션이 `harness/gpu-initiated/common/cluster_run.sh` 안에서 `chain_mi.sh`로 한다(락, 링크가 한가할 때 시작). hold마다 앞뒤
  스냅숏(GPU 사용자, BAR1, mlx5 커널 줄, rain 펌웨어 명령 수)과 8절의 STOP 규칙, rain BAR1 Free < 128 MiB이면 시작 안 함, 시행마다 rain QUERY_QP 증가 상한(복원
  50 000, 회귀 150 000).
- 본 실행(2026-10-15 21:22–22:54): `RS_SET=mi6 chain_mi.sh <결과 폴더> G1 G3 T1 T2 G2 R1 R2 R3 COST-mirror-{rain,sunny}-{lat4k,lat256k,bw256k,lat2m,bw2m}`, 그
  뒤 빠진 시행을 잇는 같은 hold 여덟(모두 "already done"). 명령의 원문은 PILOT_MI.md의 "메인 세션 명령" 5번.

  | hold | 셀(시행 수) |
  |---|---|
  | G1 | `mi4_none_ow` 5, `mi4_kill3_ow` 10, `mi4_kill1_ow` 5, `mi4_kill3_ckpt_ow` 5, `mi4_kill2_kill3_ow` 5, `mi4_kill3_ow_nomirror` 5, `mi4_kill3_ow_sampled` 5 |
  | G3 | `mi4_seg_4k`, `_32k`, `_128k` 각 5, `mi4_int_10`, `_20`, `_40` 각 3, `mi4_pull_none` 3, `mi4_pull` 5, `mi4_overflow` 5 |
  | T1, T2 | `mi4_train_none` 5, `mi4_train_kill3` 10; `mi4_train_kill2_kill3` 5 |
  | G2 | `mi4_refuse_csum`, `_mirror1`, `_sl` 각 3 |
  | R1 | gin-remaining 실행기 `reg_mr4_none`, `reg_rm4_kill3_untimed`, `reg_mr4_none_hold`, `reg_rm4_kill3_untimed_hold` 각 5 |
  | R2, R3 | gin-restore 셀 `rs4_*`(mirror 끔)와 `rs4_none_mion`, `rs4_kill3_mion`(mirror 켬) |
  | COST-mirror-<노드>-<지표> | 팔 넷(off, on, mirror-self, mirror-peer) × 6라운드, 홀수 라운드와 짝수 라운드의 차례를 뒤집어 섞음 |

- mirror 변수(라이브러리): `NCCL_GIN_RESTORE_MIRROR`(켬), `_MIRROR_SLOTS`(segment 자리, 3), `_MIRROR_LANE`(lane 바이트; 4 KiB 셀은 기본 1 MiB, segment 32 KiB 셀
  2 MiB, 128 KiB 셀 6 MiB, 학습 80 MiB, 당기기 셀 48 KiB, 넘침 셀 2 KiB), `_MIRROR_PULL`(당기기 문턱 %, 50), `_MIRROR_POOL_MAX_MB`, `_MIRROR_FETCH_MB`, `_STORE_MAX_MB`, `_STORE_WRITE_MS`, `_PAUSE_MS`(체크포인트 멈춤
  시한), `_DRAIN_MS`, `_DRAIN_QUERIES`, `_LOG_MEASURE_MIRROR`(비용 셀의 재기만 하는 mirror 팔). gin-restore의 복원 변수는 그 실험의 [NOTES.md](../restore/NOTES.md).
- 실행기 변수(`cells_mi.json`의 env): `OVERWRITE`, `TRAIN`, `MIRROR*`, `CKPT_STEPS`, `KILL_RANK`, `KILL_IN_HOOK`, `KILL_AFTER_STABLE`, `DIE_SEED`(본 실행 `gin-mirror-v1`,
  pilot `mi-v1`)와 `DIE_LO`, `DIE_HI`, `DIE_US_MAX`, `SPARE`, `SPARE_WAIT_MS`, `QPWATCH`. 학습 셀은 QP 감시 50 ms, 예비 프로세스 기다림 120 000 ms.
- 예비 프로세스는 죽을 rank와 같은 노드, 같은 GPU에서 그 rank의 초기화 기록을 재생하며 뜨고 활성화를 기다린다. 원래 프로세스가 아직 `/proc`에 있으면 'later'로
  답하고 짝이 20 ms마다 다시 묻는다(EXPERIMENT.md 3절 끝의 두 모드).

## 채점과 재계산

- 채점: `python3 impl/test/score.py results/20261015_main`이 같은 폴더에 `SCORE.md`와 `trials_scored.csv`를 쓴다. 판정식은
  [impl/test/predictions_mi.csv](impl/test/predictions_mi.csv)(sha256 `2db0c694…`, `PREREG.txt`), 셀과 계획 n은 [impl/test/cells_mi.json](impl/test/cells_mi.json).
  자체 시험은 `python3 impl/test/selftest_mi.py`와 `score.py --selftest`.
- 시행별 열만 보기(판정 아님, pilot에 씀): `python3 impl/test/rows_mi.py <결과 폴더> --out <다른 곳>/trials.csv`.
- 복원 시간의 끝점: 채점기는 마지막 생존 rank의 `restore round with rank d published` 줄, 독립 재계산은 `restored as incarnation` 줄이다(0.02–1.31 ms 차;
  EXPERIMENT.md 16절).
- 독립 재계산: [results/20261015_main/qa_recount.md](results/20261015_main/qa_recount.md). 스크립트는 세션 스크래치 `mi_recount/`(`recount_mi.py <결과 폴더> out`,
  `verdict.py`, `cost.py`, `rt_both.py`, `keys.py`, `compare.py`)이고 저장소에 넣지 않았다. 마무리 때 다시 센 스크립트는 세션 스크래치 `mi_close/`.

## pilot과 실행 가능성 확인(모두 채점 제외)

| 실행 | 날짜와 시각 | 묶음 | hold | 결과 폴더 | 찾은 것 |
|---|---|---|---|---|---|
| 실행 가능성 확인 1, 3, 4 | 2026-10-13 15:04–15:08 | `feas/` 도구 | `hold_mf.sh` | `exp/gin-mirror` worktree의 `results/20261013_feas/` | 호스트 MR 쓰기의 보임, RDMA 저장소 시간(FETCH 모형의 a와 θ), rain BAR1 |
| pilot 1 | 2026-10-15 08:59–09:15 | `mi1` | P1, P2, P3, COSTPILOT-rain, -sunny | `exp/gin-mirror-int` worktree의 `results/20261015_pilot/` | 결함 A(복원 뒤 lane 깨짐), C(학습 둘째 죽음 실패), D(비용 peer 팔), 점검 B |
| pilot 2 | 2026-10-15 14:28–14:42 | `mi2` | 같음 | `results/20261015_pilot2/` | A, C, D 고침 확인 |
| pilot 3 | 2026-10-15 16:00–16:14 | `mi3` | 같음 | `results/20261015_pilot3/` | 결함 E(당겨진 체크포인트가 거절되면 lane 넘침), rain BAR1 시작 문 |
| pilot 4 | 2026-10-15 17:52–18:05 | `mi4` | P4, P5, COSTPILOT-rain, -sunny | `results/20261015_pilot4/` | 계보 줄 0, E 고침 확인, 복원 시간의 두 모드 |
| pilot 5 | 2026-10-15 19:00–19:03 | `mi5` | P6 | `results/20261015_pilot5/` | 남긴 당기기가 셋째 시도에 찍힘 |
| pilot 6 | 2026-10-15 21:15–21:18 | `mi6` | P6 | `results/20261015_pilot6/` | ln4 회귀 없음 |

pilot의 자세한 기록은 EXPERIMENT.md 12절이고, 체크포인트 멈춤 중 kill 셀의 pilot 값(2/4)은 16절의 충돌 1이다.

## 원자료

- 시행별 로그, kv, meta, hold 출력, 스냅숏, 비용 실행의 원시 지연 표(`*_lat_raw.csv.gz`)는 Release 자산 `data-20261015`에 올린다(메인 세션; 루트
  [DATA.md](../../../../DATA.md)에 체크섬을 적을 때까지는 이 worktree들에만 있음). 폴더에는 채점표, 시행별 표, 재계산만 둔다.
- 올릴 폴더: 본 실행 `results/20261015_main/`(파일 3 627), pilot 2–6(`results/20261015_pilot2`–`pilot6`), pilot 1(`exp/gin-mirror-int` worktree의
  `results/20261015_pilot/`), 실행 가능성 확인(`exp/gin-mirror` worktree의 `results/20261013_feas/`). 관리망 주소는 `tools/pack_release.py`가 문서용 주소로 바꾼다.
- 초기화 기록(`NCCL_GIN_RESTORE_RECORD`)은 관리 주소가 들어 있어 노드 밖으로 옮기지 않고 시행 뒤 지운다. 복사한 로그의 IPv4 주소는 실행기가 가린다.

## 업스트림 이슈(사실만)

- NVIDIA/nvshmem#120: IBGDA release 빌드가 오류 CQE를 버려 `nvshmem_quiet`가 정상 반환하고 fetch가 옛 값을 돌려준다. 2026-10-15 기준 열림.
- NVIDIA/nccl#2480: GIN GDAKI에서 `NCCL_GIN_GDAKI_NIC_HANDLER=6`이 초기화에서 받아들여지나 GIN 작업이 끝나지 않는다. 2026-10-15 기준 열림, 담당자 지정됨.
- 실패한 put 뒤 GIN GDAKI의 flush가 돌아오고 오류가 늦게 한 번만 보이는 문제의 초안은 올리지 않았다(사용자 결정 대기).

둘 다 이 실험의 측정이 아니라 앞 실험들에서 나온 것이고, 이 계층의 장애 감지 가정과 맞닿아 있어 적어 둔다.
