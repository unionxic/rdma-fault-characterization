# v2: 원본 소스에서 다시 만드는 오류 전달과 복구

NCCL v2.32.6-1과 NVSHMEM v3.8.0-0의 release 소스에서 출발한 작업. v1의 복구 패치와 설계는 미참고.
현재까지의 범위는 **오류가 application까지 원인과 함께 전달되게 하는 것**. 복구 구현은 시작 전(규칙 제안 단계).

기록은 [`RECORD.md`](RECORD.md) 한 파일: 결정, 분류의 근거, 날짜별 실행 기록.

## 파일

| 경로 | 내용 |
|---|---|
| `RECORD.md` | 단일 기록. 4절이 오류 분류의 근거, 4.1절이 복구 규칙(제안), 6절이 실행 기록 |
| `patches/nccl-v2.32.6-1.diff` | NCCL `ad2d192`(v2.32.6-1) 대비 변경. 11개 파일 +329 −47 |
| `patches/nvshmem-v3.8.0-0.diff` | NVSHMEM `270759e5`(v3.8.0-0) 대비 변경. 16개 파일 +285 −11 |
| `repro/gin_fault.cu` | nccl#2483 재현: 창 밖 주소로 put을 보낸 뒤 flush와 host 조회의 반환 확인 |
| `repro/shmem_fault.cu` | nvshmem#120 재현: 잘못된 주소 또는 정렬 안 된 atomic, 스레드 수 조절 |
| `repro/synd.c`, `synd.sh` | CQE syndrome 13개 재현 시도(CPU verbs, 한 프로세스 loopback). CQE, QP context의 오류 기록, 비동기 이벤트, 포트 카운터, 커널 로그를 경우마다 기록 |
| `repro/qperr.c` | LD_PRELOAD 주입기. 프로세스의 QP를 실행 중에 오류 상태로 바꿔 "연결 쪽 문제"를 재현(라이브러리 코드 변경 없음) |
| `repro/decode_test.cpp` | NVSHMEM 분류 표의 자체 검사(GPU와 NIC 불필요) |
| `repro/build.sh` | 재현 프로그램 빌드 |
| `run_gin_fault.sh`, `shmem_fault.sh`, `shmem_cnt.sh` | 재현 실행과 집계 |
| `ab.sh`, `ab_report.py` | 원본과 수정본을 번갈아 돌리는 성능 비교와 중앙값 표 |
| `env.sh`, `verify.sh`, `shmem_sunny.sh`, `socks.sh` | 실행 환경, 첫 동작 확인, 보조 스크립트 |

스크립트의 가정: `~/rdma-recovery/` 아래에 `nccl/`, `nvshmem/`(패치 적용본), `base/`(원본 빌드), `repro/`, host 이름은
`rain`과 `sunny`. 다른 환경에서는 경로와 host 이름 변경 필요.

패치 적용:

```
git clone https://github.com/NVIDIA/nccl && cd nccl && git checkout ad2d192 && git apply ../patches/nccl-v2.32.6-1.diff
git clone https://github.com/NVIDIA/nvshmem && cd nvshmem && git checkout 270759e5 && git apply ../patches/nvshmem-v3.8.0-0.diff
```

## 고친 이슈

| 이슈 | 증상 | 고친 내용 |
|---|---|---|
| [NVIDIA/nvshmem#117](https://github.com/NVIDIA/nvshmem/issues/117) | CPU 프록시가 doorbell record의 틀린 word에 기록, 장애 뒤 오류 CQE가 생기지 않고 `nvshmem_quiet()` 정지 | 주소 계산 2줄. upstream 수정은 devel 브랜치에만 있고 release 3.8.0에는 없음 |
| [NVIDIA/nvshmem#120](https://github.com/NVIDIA/nvshmem/issues/120) | release 빌드가 오류 CQE를 읽고 버림. quiet는 정상 반환, fetch는 틀린 값 | GPU 코드의 첫 오류 기록, host가 원인을 출력하고 중단(기본). `NVSHMEM_IBGDA_ABORT_ON_OP_ERROR=0`이면 계속 실행하며 application이 `nvshmemx_get_op_error()`로 조회 |
| [NVIDIA/nccl#2483](https://github.com/NVIDIA/nccl/issues/2483) | GIN GDAKI에서 실패한 put을 device 코드가 알 수 없고 대기가 끝나지 않음. host는 10 s 조회에서 한 번만 확인 | 첫 오류를 CQ에 기록, flush와 wait의 `ncclRemoteError` 반환, host 경고에 원인 출력(조회 간격 기본 10 s → 1 s). CQ 방식 3가지 모두 |
| [NVIDIA/nccl#2480](https://github.com/NVIDIA/nccl/issues/2480) | `NCCL_GIN_GDAKI_NIC_HANDLER=6`이 init을 통과한 뒤 조용히 정지 | 지원하지 않는 값을 경고와 함께 거절. upstream 수정은 dev 브랜치 |

## 측정으로 확인한 것

- **원인은 QP context에 보존.** CQ 칸이 하나뿐인 구성(NVSHMEM 기본)에서는 뒤따른 flush가 원인 CQE를 덮어씀. NIC는 QP마다
  첫 오류를 QP context에 보관(`QUERY_QP`의 `qpc_ext`)하고 flush는 그것을 지우지 않음. 두 라이브러리의 host가 이 값을 조회.
  NVSHMEM에서 스레드 8개와 64개로 장애를 넣은 결과: 고치기 전 매번 flush만 관측, 고친 뒤 매번 원인 복원.
- **오류 분류의 근거.** 전체 집합은 드라이버가 정의한 CQE syndrome 13개. 그중 10개를 소프트웨어로 재현. 두 라이브러리의
  GPU 경로(write, read, atomic만 사용, 수신 큐 없음)가 낼 수 있는 것은 6개(`RECORD.md` 4절).
- **정상 경로 비용.** NCCL `ring_exchange` 원본 대비 +0.6%, +1.2%, +0.1%, +0.1%(구성 4가지, 20회, 원본의 회차 간 편차
  0.4–1.9%). NVSHMEM put 지연 +1.1%, p 지연 +2.2%, 대역폭은 편차 안(10회).
- **오류 주입 재시험.** NCCL CQ 방식 3가지 × 양방향 120회에서 멈춤 0회, host 조회 90회 모두 원인(`0x13/0x88`) 출력.
- **세 분류의 재현.** 요청이 틀린 경우(`0x13`, `0x12`), 상대 프로세스 종료(`0x15/0x81`), 연결 쪽 문제(보내는 쪽 QP 오류
  `0x05/0xf5`, 받는 쪽 QP 오류 `0x15/0x81`)를 두 라이브러리에서 재현. 분류 결과는 모두 기대와 일치, 멈춤 0회.
- **어디까지 끝났는지는 하한으로 기록.** 오류 기록의 요청 번호는 "그 아래는 모두 완료"를 뜻하는 하한. put 수만 개가
  떠 있는 도중에 QP를 죽인 50회 모두에서 기록된 번호가 실제 도착분 이하(NCCL 기본 CQ는 정확히 일치).

## 한계

- 소프트웨어로 넣은 장애만 대상. 케이블이나 펌웨어 결함 같은 물리 장애는 미포함
- vendor_err 값은 드라이버 헤더에 정의가 없어 측정으로 정한 값. ConnectX-6(MT4123) 펌웨어 20.43.4100 한 가지에서 측정
- 노드 2개(NVSHMEM은 GPU 한 장에 PE 둘)에서만 실행
- 실패한 요청을 정확히 짚지는 못함. 기록은 "여기까지는 끝났다"는 하한이며, 그 뒤 구간의 요청은 완료 여부 미확정
- 복구 규칙(`RECORD.md` 4.1절)은 제안 단계. 실행으로 확인한 것 없음
- 실행 로그는 미공개(관리망 주소 포함). `RECORD.md`가 가리키는 `runs/...` 경로는 이 저장소에 없음
