# RDMA Fault / Recovery 실험 — client 노드 (225)

RDMA subsystem의 에러 동작을 CQE(`ibv_wc_status` + `vendor_err`) + 하드웨어 카운터
레벨에서 분류하고, 그 위에서 recovery 방법론을 측정하는 실험 모음.
이 노드(SERVER_225_ADDR, ConnectX-6)가 **client/requester** 역할이며, 모든
orchestration 스크립트는 여기서 실행한다 (SSH는 225→224 방향만 가능).

짝이 되는 서버 코드는 224(SERVER_224_ADDR, ConnectX-5)의 같은 경로
`/home/gustlr/Desktop/gpu_fault_recovery/`에 있다.

## 디렉토리 맵 (번호 = 연구 진행 순서)

| 디렉토리 | 내용 | 상태 |
|---|---|---|
| `01_cpu_baseline/` | 실험 1~4: 감지 지연 baseline(3.7s), polling blind window, QP recovery 단계별 비용, NIC retry 한계 sweep | 완료 |
| `02_retry_decomposition/` | 3.7s를 retry_cnt × timeout sweep으로 분해 (Exp A) | 완료 |
| `03_modifyqp/` | `ibv_modify_qp(ERR)`로 SSH/커널 오버헤드를 제거한 순수 HCA retry 시간 측정 → firmware `min_ack_timeout_limit` 발견, 비활성화 시 R=7이 12.26ms | 완료 |
| `04_error_codes/` | 9개 에러 시나리오 재현으로 `ibv_wc_status` 코드 채집. 결과는 `REPORT.md` (둘 다 이 저장소에는 없다) | 완료 |
| `05_counter_mapping/` | 핵심 실험 묶음: 장애별 오류 코드와 카운터 변화(카운터 매핑), multi-QP/WR 조건, partial/interrupted write, A/B recovery, NIC swap. 상세는 그 안의 `README.md` | 완료(A/B recovery 재실행 대기) |
| `06_recovery/` | NAK 4종(REM_ACCESS, REM_INV_REQ, RETRY_EXC, RNR)별 recovery 비용 + multi_qp isolation + early detection. 요약: `recovery_results_summary.md` | 완료(RNR 재실행 대기) |
| `08_middleware/` | 코드는 지웠다(아래). `results/qa_20260923/README.md`(2026-09-23 데모 QA 기록)만 남았다 | — |
| `10_storage_rdma/` | **Phase 1 (SSD × RDMA)** cross-resource 확장: NVMe-oF over RDMA에서 media/fail-slow/target-crash/partial 고장의 NVMe·RDMA 계층 표면화 매핑. initiator/orchestrator 쪽. 커널 QP라 CQE 불가시 → (NVMe status, dmesg, 양쪽 counter, latency) tuple. 상세: 그 안 `README.md` | 코드 완성, 실행 대기 |
| `plots/` | 실험 1~4 원시 CSV → plot용 데이터(`data/`) 생성 | — |
| `docs/` | `SUMMARY.md` (2026-05-06 시점 종합 요약, 이 저장소에는 없다) | — |

2026-10-06에 지운 것: 한 번 쓴 통합 검증 `09_verify/`(실제 fault 5종으로 분류 라이브러리 확인),
분류 라이브러리 `07_fault_classify/`(`librdma_fault.a`)와 그 위의 미들웨어 데모 `08_middleware/`의 코드
(`docs/`의 수치가 기대지 않고, 같은 분류는 `harness/common/probe.c`의 `classify()`가 맡는다),
`02_retry_decomposition/`의 쓰이지 않던 계측 client(`client.c`, `Makefile`, symlink 3개; 실험은
experiment4 client로 돌았다), 그림을 그리던 `plots/plot_exp1~4.py`(그림은 저장소에도 문서에도 없다),
인용되지 않은 `10_storage_rdma/aggregate_results.py`, 224 사본과 똑같던
`01_cpu_baseline/experiment3/server.c`와 `05_counter_mapping/counter_daemon.sh`(둘 다 224에서만 돈다).
git 태그 `archive/results-tables-20261006`에 남아 있다.

로컬 정리본(이론/실험결과/다음계획 3부작)은 맥북
`~/Desktop/Netsys/gpu-fault-recovery/1_이론.md, 2_실험과_결과.md, 3_다음_계획.md`에 있다.

## 실행 방법

- 각 실험 디렉토리의 `run*.sh`를 **225에서** 실행한다. 스크립트가 SSH로 224의
  서버 바이너리를 빌드/기동/정리까지 관리한다.
- 빌드만 따로 하려면 각 디렉토리에서 `make`. 의존 관계:
  `06_recovery`는 `05_counter_mapping/common.h`를 참조한다.
- `02_retry_decomposition`은 `01_cpu_baseline/experiment4`의 client 바이너리를,
  `03_modifyqp`는 `01_cpu_baseline/experiment1`의 server(224)를 재사용한다.
- 예외: `05_counter_mapping/run_swap.sh`만 역할이 뒤집힌다 — 225가 responder,
  224가 requester(CX-5). 스크립트 헤더 참고.

## 2026-07-10 디렉토리 재구성 (구 → 신)

```
cpu_baseline        → 01_cpu_baseline      counter_mapping → 05_counter_mapping
retry_decomposition → 02_retry_decomposition   recovery    → 06_recovery
exp_modifyqp        → 03_modifyqp          fault_classify  → 07_fault_classify
exp_error_codes     → 04_error_codes       middleware      → 08_middleware
SUMMARY.md          → docs/SUMMARY.md      verify          → 09_verify
```

스크립트/Makefile/#include의 경로 참조는 전부 새 이름으로 갱신 완료.
과거 노트·메모리에 옛 경로가 나오면 위 표로 환산하면 된다.
