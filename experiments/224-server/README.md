# RDMA Fault / Recovery 실험 — server 노드 (224)

이 노드(SERVER_224_ADDR, ConnectX-5)는 실험의 **server/responder** 역할이다.
모든 orchestration은 225에서 실행되며(SSH는 225→224 방향만 가능), 여기 있는
서버 바이너리들은 225의 `run*.sh` 스크립트가 SSH로 빌드/기동/정리한다.
이 노드에서 직접 뭔가 실행할 일은 거의 없다.

전체 실험 설명과 디렉토리 맵은 **225의 `README.md`**를 보라. 여기는 225와 같은
번호 체계를 쓰되 server 쪽 소스만 있다 (`02_retry_decomposition`, `03_modifyqp`, `plots`는 225 전용).
225와 똑같던 client 쪽 사본(experiment2, experiment4, `02_retry_decomposition`, 각 orchestrator와
분석 스크립트), 한 번 쓴 통합 검증 `09_verify`, 분류 라이브러리 `07_fault_classify`와 미들웨어 데모
`08_middleware`(`docs/`의 수치가 기대지 않는다)는 2026-10-06에 지웠다. git 태그
`archive/results-tables-20261006`에 남아 있다.

| 디렉토리 | 이 노드에서의 역할 |
|---|---|
| `01_cpu_baseline/` | experiment1, experiment3의 server (fault 주입 대상). experiment2, experiment4와 `02_retry_decomposition`은 experiment1의 server를 `server_loop.sh`, `server_link_loop.sh`로 띄워 재사용한다 |
| `04_error_codes/` | 시나리오별 RDMA 설정을 바꿔주는 server (이 저장소에는 없다) |
| `05_counter_mapping/` | 카운터 매핑(장애별 오류 코드와 카운터 변화) server + `multi_server`. 예외: swap 실험에서는 이 노드가 **requester(client)** 가 된다 — orchestration 스크립트(`run_swap.sh`)는 225에만 있음 (224 사본은 안 되는 ssh 방향을 전제해 2026-07-15 삭제) |
| `06_recovery/` | NAK 유형별 fault를 만들어주는 server 5종 |
| `10_storage_rdma/` | **Phase 1 (SSD × RDMA)** target 쪽: file-backed nvmet-rdma export + dm-dust/flakey/delay 고장 주입. 부팅 디스크(nvme0n1) 절대 미접촉 — loop 디바이스만 export(어기면 중단하는 필수 검사). 225의 `run_storage_experiment.sh`가 ssh로 setup/teardown/crash 호출. 상세: 그 안 `README.md` |
| `rdma-core/` | upstream 소스 사본 (레퍼런스 열람용으로 추정 — 실험 Makefile들은 참조하지 않음, 이 저장소에는 없다) |

## 2026-07-10 디렉토리 재구성 (구 → 신)

```
cpu_baseline        → 01_cpu_baseline      counter_mapping → 05_counter_mapping
retry_decomposition → 02_retry_decomposition   recovery    → 06_recovery
exp_error_codes     → 04_error_codes       fault_classify  → 07_fault_classify
middleware          → 08_middleware        verify          → 09_verify
```
