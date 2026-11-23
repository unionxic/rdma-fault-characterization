# v2: 원본 소스에서 다시 만드는 오류 전달과 복구

NCCL v2.32.6-1과 NVSHMEM v3.8.0-0의 release 소스에서 출발한다. v1의 복구 패치와 설계는 참고하지 않았다. 지금까지 한 것은
**오류가 application까지 원인과 함께 전달되게 하는 것**이고, 복구 구현은 아직 시작하지 않았다(규칙만 제안 상태).

기록은 [`RECORD.md`](RECORD.md) 한 파일이다. 결정, 분류의 근거, 실행 기록(날짜별 무엇을 돌렸고 무엇이 나왔는지)이 모두 거기 있다.

## 파일

| 경로 | 내용 |
|---|---|
| `RECORD.md` | 단일 기록. 4절이 오류 분류의 근거, 4.1절이 복구 규칙(제안), 6절이 실행 기록 |
| `patches/nccl-v2.32.6-1.diff` | NCCL `ad2d192`(v2.32.6-1) 대비 변경. 11개 파일 +326 −46 |
| `patches/nvshmem-v3.8.0-0.diff` | NVSHMEM `270759e5`(v3.8.0-0) 대비 변경. 15개 파일 +254 −11 |
| `repro/gin_fault.cu` | nccl#2483 재현: 창 밖 주소로 put을 보내고 flush와 host 조회가 무엇을 돌려주는지 본다 |
| `repro/shmem_fault.cu` | nvshmem#120 재현: 잘못된 주소 또는 정렬 안 된 atomic, 스레드 수 조절 |
| `repro/synd.c`, `synd.sh` | CQE syndrome 13개 재현 시도(CPU verbs, 한 프로세스 loopback). CQE, QP context의 오류 기록, 비동기 이벤트, 포트 카운터, 커널 로그를 경우마다 기록 |
| `repro/decode_test.cpp` | NVSHMEM 분류 표의 자체 검사(GPU와 NIC 없이 돈다) |
| `repro/build.sh` | 재현 프로그램 빌드 |
| `run_gin_fault.sh`, `shmem_fault.sh`, `shmem_cnt.sh` | 재현 실행과 집계 |
| `ab.sh`, `ab_report.py` | 원본과 수정본을 번갈아 돌리는 성능 비교와 중앙값 표 |
| `env.sh`, `verify.sh`, `shmem_sunny.sh`, `socks.sh` | 실행 환경, 첫 동작 확인, 보조 스크립트 |

스크립트는 `~/rdma-recovery/` 아래에 `nccl/`, `nvshmem/`(패치 적용본), `base/`(원본 빌드), `repro/`가 있고 host 이름이
`rain`, `sunny`라고 가정한다. 다른 환경에서는 경로와 host 이름을 바꿔야 한다.

패치 적용:

```
git clone https://github.com/NVIDIA/nccl && cd nccl && git checkout ad2d192 && git apply ../patches/nccl-v2.32.6-1.diff
git clone https://github.com/NVIDIA/nvshmem && cd nvshmem && git checkout 270759e5 && git apply ../patches/nvshmem-v3.8.0-0.diff
```

## 고친 이슈

| 이슈 | 증상 | 고친 내용 |
|---|---|---|
| [NVIDIA/nvshmem#117](https://github.com/NVIDIA/nvshmem/issues/117) | CPU 프록시가 doorbell record의 틀린 word에 써서, 장애 뒤 오류 CQE가 생기지 않고 `nvshmem_quiet()`가 멈춘다 | 주소 계산 2줄. upstream은 devel 브랜치에서 고쳤고 release 3.8.0에는 없다 |
| [NVIDIA/nvshmem#120](https://github.com/NVIDIA/nvshmem/issues/120) | release 빌드가 오류 CQE를 읽고 버린다. quiet가 정상 반환하고 fetch가 틀린 값을 준다 | GPU 코드가 첫 오류를 남기고, host가 한 줄로 알리고, application이 `nvshmemx_get_op_error()`로 오류와 분류를 묻는다 |
| [NVIDIA/nccl#2483](https://github.com/NVIDIA/nccl/issues/2483) | GIN GDAKI에서 실패한 put을 device 코드가 알 수 없고 기다림이 끝나지 않는다. host는 10 s 조회에서 한 번만 본다 | 첫 오류를 CQ에 기록하고, flush와 wait가 `ncclRemoteError`를 돌려주고, host 경고에 원인이 찍힌다. CQ 방식 3가지 모두 |
| [NVIDIA/nccl#2480](https://github.com/NVIDIA/nccl/issues/2480) | `NCCL_GIN_GDAKI_NIC_HANDLER=6`이 init을 통과한 뒤 조용히 멈춘다 | 지원하지 않는 값을 경고와 함께 거절한다. upstream은 dev 브랜치에서 고쳤다 |

## 측정으로 확인한 것

- **원인은 QP context에 남는다.** CQ 칸이 하나뿐인 구성(NVSHMEM 기본)에서는 뒤따른 flush가 원인 CQE를 덮어쓴다. NIC는 QP마다
  첫 오류를 QP context에 보관하고(`QUERY_QP`의 `qpc_ext`) flush가 그것을 지우지 않는다. 두 라이브러리의 host가 이 값을 읽는다.
  NVSHMEM에서 스레드 8개와 64개로 장애를 넣으면 고치기 전에는 매번 flush만 보였고, 고친 뒤에는 매번 원인이 나왔다.
- **오류 분류의 근거.** 전체 집합은 드라이버가 정의한 CQE syndrome 13개다. 그중 10개를 소프트웨어로 재현했고, 두 라이브러리의
  GPU 경로(write, read, atomic만 쓰고 수신 큐가 없다)가 낼 수 있는 것은 6개다(`RECORD.md` 4절).
- **정상 경로 비용.** NCCL `ring_exchange`는 원본 대비 +0.6%, +1.2%, +0.1%, +0.1%(구성 4가지, 20회, 원본의 회차 간 편차
  0.4–1.9%). NVSHMEM은 put 지연 +1.1%, p 지연 +2.2%, 대역폭은 편차 안(10회).
- **오류 주입 재시험.** NCCL은 CQ 방식 3가지 × 양방향 120회에서 멈춤 0회, host 조회 90회 모두 원인(`0x13/0x88`)이 찍혔다.

## 한계

- 소프트웨어로 넣은 장애만 봤다. 케이블이나 펌웨어 결함 같은 물리 장애는 없다.
- vendor_err 값은 드라이버 헤더에 정의가 없어 측정으로 정했고, ConnectX-6(MT4123) 펌웨어 20.43.4100 한 가지에서 쟀다.
- 노드 2개(NVSHMEM은 GPU 한 장에 PE 둘)에서만 돌렸다.
- 원인은 되찾지만 어느 요청이 실패했는지(WQE 번호)는 flush에 덮이면 알 수 없다.
- 복구 규칙(`RECORD.md` 4.1절)은 제안이고 실행해 확인한 것이 없다.
- 실행 로그는 올리지 않았다. 관리망 주소가 찍혀 있기 때문이다. `RECORD.md`가 가리키는 `runs/...` 경로는 이 저장소에 없다.
