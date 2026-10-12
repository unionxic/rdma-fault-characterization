# gin-restore 구현과 실행 메모

[README.md](README.md)의 연구 내용 밖에 있는 구현, 빌드, 배포, 실행, 채점을 짧게 모았다. 설계와 기록은 [EXPERIMENT.md](EXPERIMENT.md)의 해당 절이
기준이다.

## 계층

| 빌드 | 파일 | 무엇을 | 자세히 |
|---|---|---|---|
| GIN `rs`(연구) | [impl/rs_layer.diff](impl/rs_layer.diff)(파일 열둘, gpu-detect `hk` 위) | 복원 계층: 장애 반응 정책(`NCCL_GIN_FAULT_POLICY=hold`), 모든 rank가 함께 부르는 `ncclGinRestoreResume`(켤 수 없으면 같은 이유의 오류), strict window 강제, 송신 쪽 로그(rank마다 고리 하나, 64 B 항목, 내용 복사 없음), 체크포인트(짝 rank의 호스트 메모리, 증분, 입력 멈춤), 붙잡기 상태 기계, 예비 프로세스(초기화 기록과 재생, 활성화, REJOIN, 끝점 바꾸기), 다시 보내기 억제, 라이브러리 시험 스위치 | EXPERIMENT.md 9.1–9.11, 9.14절 |
| GIN `rsp`(운영) | 같은 소스에 `-DNCCL_GIN_TS_PRODUCTION` | 비용 셀의 라이브러리. 연구 빌드의 시험 스위치와 일부 줄이 없음 | 9.14절, 12절의 빌드 행 |
| 장치 쪽 | `rs_layer.diff` 안의 장치 헤더 둘 | 빌드 매크로 `NCCL_GIN_RESTORE_DEVICE`를 켠 프로그램만 hold 보내기 길(게이트 뒤 키 다시 읽기, 억제, 로그)을 가진다. 매크로 없는 프로그램의 기계어는 `hk`와 같다 | 9.9절 끝의 메모, 12절의 기계어 비교 행 |

- 재현: 순정 NCCL v2.32.3-1 + `../remaining/gin_transparent_hr.diff` + `../../../gpu-detect/hw_layer.diff` + `../../../gpu-detect/hk_layer.diff` +
  `impl/rs_layer.diff`. NCCL 빌드가 장치 전용 헤더의 의존성을 놓치므로 [impl/build_rs.sh](impl/build_rs.sh)는 헤더 요약이 바뀌면 장치 객체를 다시
  만든다(12절, 2026-10-12).
- 빌드 md5와 배포 묶음은 EXPERIMENT.md 7절(본 실행의 i5)과 [PREREG.txt](PREREG.txt), 빌드 단계는 `impl/build_rs.sh` 머리와 12절.

## 파일

| 파일 | 하는 일 |
|---|---|
| [impl/build_rs.sh](impl/build_rs.sh) | 세션 스크래치의 빌드 단계(`setup`, `rs`, `rsp`, `unitd`, `unith`, `units`, `api`, `units-all`, `info`) |
| [impl/make_diff_rs.sh](impl/make_diff_rs.sh) | 계층 diff를 쓰고 기준 트리에 다시 적용해 같은지 확인 |
| [impl/rs_unit_dev.cc](impl/rs_unit_dev.cc), [impl/rs_unit_host.cc](impl/rs_unit_host.cc), [impl/rs_spare_unit.cc](impl/rs_spare_unit.cc) | 순수 함수의 CPU 단위 시험(장치 로그와 억제, 호스트 체크포인트와 상태 기계, 예비 프로세스의 판정) |
| [impl/ff_cmp_dev.sh](impl/ff_cmp_dev.sh), [impl/exact_cmp_dev.sh](impl/exact_cmp_dev.sh), [impl/obj_cmp.sh](impl/obj_cmp.sh), [impl/sass_cmp.py](impl/sass_cmp.py) 등 | 매크로 없는 프로그램과 라이브러리 장치 객체의 기계어를 `hk`와 비교 |
| [impl/rs_log_api.h](impl/rs_log_api.h), [impl/rs_hold_api.h](impl/rs_hold_api.h), [impl/rs_ckpt_api.h](impl/rs_ckpt_api.h), [impl/rs_spare_api.h](impl/rs_spare_api.h) | 병렬 구현 때 갈래 사이의 공유 인터페이스([impl/PARALLEL.md](impl/PARALLEL.md)) |
| [impl/test/gin_rs.cu](impl/test/gin_rs.cu) | 시험 workload(9.8절): 4 rank, 단계 600개, put과 신호 둘, 호스트 기준과 비트 비교, 예비 프로세스 모드 |
| [impl/test/build_rs_test.sh](impl/test/build_rs_test.sh) | driver 빌드(`gin_rs` 매크로, `gin_rs_nomacro`, `gin_rs_hk`, 비용 `gin_ts2`, 회귀 `gin_mr`) |
| [impl/test/deploy_rs.sh](impl/test/deploy_rs.sh) | 두 노드의 새 디렉터리(`~/rs-bundle/<RS_SET>/`)에 배포하고 앞뒤 md5와 ldd 확인 |
| [impl/test/run_rs.sh](impl/test/run_rs.sh), [impl/test/cells_rs.sh](impl/test/cells_rs.sh), [impl/test/cells_rs.json](impl/test/cells_rs.json) | 복원 시행 하나(기록한 PID로만 kill, 예비 프로세스, 수신 시각 도장), 셀 실행, 셀과 hold 정의 |
| [impl/test/run_cost.sh](impl/test/run_cost.sh) | 비용 실행 하나(9.15.6의 틀, 재기만 하는 모드) |
| [impl/test/hold_rs.sh](impl/test/hold_rs.sh), [impl/test/chain_rs.sh](impl/test/chain_rs.sh), [impl/test/rs_set.sh](impl/test/rs_set.sh) | hold 하나(스냅숏, STOP 규칙, QUERY_QP 상한, 이어 돌리기), hold 사슬(`../../common/cluster_run.sh` 안), 배포 묶음 이름 검사 |
| [impl/test/rows_rs.py](impl/test/rows_rs.py), [impl/test/score.py](impl/test/score.py), [impl/test/predictions_rs.csv](impl/test/predictions_rs.csv), [impl/test/selftest_rs.py](impl/test/selftest_rs.py) | 시행별 열, 채점(사전 등록한 판정식), 자체 시험 |
| [impl/test/PILOT.md](impl/test/PILOT.md) | pilot이 보여야 할 것, 고정한 값, 배포와 실행 명령 |
| [feas/](feas/) | 실행 가능성 시험 B1–B3과 strict 대 relaxed 비교의 코드(9.15절) |

## 실행

- 모든 클러스터 실행은 메인 세션이 `harness/gpu-initiated/common/cluster_run.sh` 안에서 한다(락, 링크가 한가할 때 시작). hold마다 앞뒤 스냅숏(GPU
  사용자, BAR1, mlx5 커널 줄, rain 펌웨어 명령 수)과 STOP 규칙(8절).
- hold 프로세스의 고정 설정은 6절. 복원 변수: `NCCL_GIN_RESTORE`, `_MS`(시한 20 000), `_RESUME_MS`, `_LOG_ENTRIES`(4 096), `_CHECKSUM`(off|sampled|full,
  기본 off), `_CKPT_STEPS`(20), `_RECORD`(초기화 기록, 노드 안에만), `_REPLAY`, `_SPARE`, `_SPARE_PORT`, `_SPARE_ADDR`, `_SPARE_WAIT_MS`(실행기 60 000),
  `_LOG_MEASURE`와 `_LOG_MEASURE_LOG`(비용 셀의 재기만 하는 모드), 연구 빌드만 `_TEST_DIE_IN_CKPT`(체크포인트 멈춤 중 kill 셀).
- 예비 프로세스는 죽을 rank와 같은 노드, 같은 GPU에서 그 rank의 초기화 기록을 재생하며 뜨고 `ncclGinRestoreResume` 안에서 활성화를 기다린다. 짝 rank가
  활성화를 묻고, 원래 프로세스가 아직 /proc에 있으면 예비 프로세스는 'later'로 답하고 짝은 20 ms마다 다시 묻는다(hold 시한까지).
- 본 실행과 채점 명령은 [impl/test/PILOT.md](impl/test/PILOT.md)의 "사전 등록으로 고정한 값과 본 실행 명령".

## 원자료

- 시행별 로그, kv, meta, 비용 실행의 원시 지연 표는 Release 자산에 있다(루트 [DATA.md](../../../../DATA.md)). 폴더에는 채점표와 문서가 인용한 표만 둔다.
- 초기화 기록(`NCCL_GIN_RESTORE_RECORD`)은 관리 주소가 들어 있어 노드 밖으로 옮기지 않고 시행 뒤 지운다. 복사한 로그의 IPv4 주소는 실행기가 가린다.
