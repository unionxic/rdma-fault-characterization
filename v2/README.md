# v2: 원본 소스에서 다시 만드는 오류 전달과 복구

NCCL v2.32.6-1과 NVSHMEM v3.8.0-0의 release 소스에서 출발한 작업. v1의 복구 패치와 설계는 미참고.
현재까지의 범위는 **오류가 application까지 원인과 함께 전달되게 하는 것**과 **상대 프로세스의 죽음을 일찍 알아채는 것**(NCCL GIN).
복구 구현은 시작 전(규칙과 설계 단계).

기록은 [`RECORD.md`](RECORD.md) 한 파일: 결정, 분류의 근거, 날짜별 실행 기록.

## 파일

| 경로 | 내용 |
|---|---|
| `RECORD.md` | 단일 기록. 4절이 오류 분류의 근거, 4.1절이 복구 규칙, 4.2절이 상대 죽음(복구의 가정과 판정), 4.3절이 복구 설계, 6절이 실행 기록 |
| `patches/nccl-v2.32.6-1.diff` | NCCL `ad2d192`(v2.32.6-1) 대비 변경. 14개 파일 +616 −69 |
| `patches/nvshmem-v3.8.0-0.diff` | NVSHMEM `270759e5`(v3.8.0-0) 대비 변경. 16개 파일 +294 −11 |
| `repro/gin_fault.cu` | nccl#2483 재현: 창 밖 주소로 put을 보낸 뒤 flush와 host 조회의 반환 확인. rank를 실행 도중 죽이는 시험, shrink와 grow, counter 대기도 포함(env는 파일 첫머리) |
| `repro/shmem_fault.cu` | nvshmem#120 재현: 잘못된 주소 또는 정렬 안 된 atomic, 스레드 수 조절 |
| `repro/synd.c`, `synd.sh` | CQE syndrome 13개 재현 시도(CPU verbs, 한 프로세스 loopback). CQE, QP context의 오류 기록, 비동기 이벤트, 포트 카운터, 커널 로그를 경우마다 기록 |
| `repro/qperr.c` | LD_PRELOAD 주입기. 프로세스의 QP를 실행 중에 오류 상태로 바꿔 "연결 쪽 문제"를 재현(라이브러리 코드 변경 없음) |
| `repro/decode_test.cpp` | NVSHMEM 분류 표의 자체 검사(GPU와 NIC 불필요) |
| `repro/dev0.c` | LD_PRELOAD shim. GPU 한 장에 rank 여러 개를 올릴 때 NCCL 예제가 device 0을 쓰게 함 |
| `repro/watch_counters.sh`, `repro/nsys_rank.sh` | 포트 카운터의 변화만 출력, MPI rank 하나만 Nsight로 실행 |
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
| [NVIDIA/nvshmem#117](https://github.com/NVIDIA/nvshmem/issues/117) | CPU 프록시가 doorbell record의 틀린 word에 기록, 장애 뒤 오류 CQE가 생기지 않고 `nvshmem_quiet()` 정지 | 주소 계산 2줄. upstream 수정은 devel 브랜치에만 있고 release 3.8.0에는 없음. 장애를 넣어 확인하지는 않음 |
| [NVIDIA/nvshmem#120](https://github.com/NVIDIA/nvshmem/issues/120) | release 빌드가 오류 CQE를 읽고 버림. quiet는 정상 반환, fetch는 틀린 값 | GPU 코드의 첫 오류 기록, host가 원인을 출력하고 중단(기본). `NVSHMEM_IBGDA_ABORT_ON_OP_ERROR=0`이면 계속 실행하며 application이 `nvshmemx_get_op_error()`로 조회 |
| [NVIDIA/nccl#2483](https://github.com/NVIDIA/nccl/issues/2483) | GIN GDAKI에서 실패한 put을 device 코드가 알 수 없고 대기가 끝나지 않음. host는 10 s 조회에서 한 번만 확인 | 첫 오류를 CQ에 기록, 반환값이 있는 flush와 wait의 `ncclRemoteError` 반환, host 경고에 원인 출력(조회 간격 기본 10 s → 1 s). CQ 방식 3가지 모두 |
| [NVIDIA/nccl#2480](https://github.com/NVIDIA/nccl/issues/2480) | `NCCL_GIN_GDAKI_NIC_HANDLER=6`이 init을 통과한 뒤 조용히 정지 | 지원하지 않는 값을 경고와 함께 거절. upstream 수정은 dev 브랜치 |

## 이슈 밖에서 더한 것 (NCCL GIN GDAKI)

- **host 오류 스레드.** context마다 스레드 하나가 NIC의 오류 이벤트에서 잠들어 있다가 QP 오류를 원인과 함께 경고로 출력. application이 `ncclCommGetAsyncError`를 부르지 않아도 동작. 평소 CPU 사용 스레드당 6–10 us.
- **상대 죽음의 판정.** 원본은 죽은 rank에게 보낸 요청이 NIC의 재시도 한도(약 1분)까지 정지. 스레드가 1 s마다 포트 카운터 `rp_cnp_handled`를 읽고, 올랐을 때 이웃 소켓이 닫혔고 그 rank로 보낸 PSN 중 ACK를 못 받은 것이 있으면(QUERY_QP) 죽음으로 판정, 그 rank로 가는 QP만 오류 상태로 전환. 소켓으로 보내는 것은 없음.
- **죽음 뒤의 shrink.** 오류가 기록된 communicator도 `ncclCommShrink(NCCL_SHRINK_ABORT)`는 수락.
- **`cq->hold`.** 실패한 QP에서 GPU 폴링이 host의 결정을 기다리게 하는 장치. 복구(QP 재구성)의 바탕이며 지금은 꺼 둔 상태.

## 측정으로 확인한 것

- **원인은 QP context에 보존.** CQ 칸이 하나뿐인 구성(NVSHMEM 기본)에서는 뒤따른 flush가 원인 CQE를 덮어씀. NIC는 QP마다
  첫 오류를 QP context에 보관(`QUERY_QP`의 `qpc_ext`)하고 flush는 그것을 지우지 않음. 두 라이브러리의 host가 이 값을 조회.
  NVSHMEM에서 스레드 8개와 64개로 장애를 넣은 결과: 고치기 전 매번 flush만 관측, 고친 뒤 매번 원인 복원.
- **오류 분류의 근거.** 전체 집합은 드라이버가 정의한 CQE syndrome 13개. 그중 10개를 소프트웨어로 재현. 두 라이브러리의
  GPU 경로(write, read, atomic만 사용, 수신 큐 없음)가 낼 수 있는 것은 6개(`RECORD.md` 4절).
- **오류 주입 재시험.** NCCL CQ 방식 3가지 × 양방향 120회에서 멈춤 0회, host 조회 90회 모두 원인(`0x13/0x88`) 출력.
  host 스레드를 넣은 뒤의 82회(장애 70회)에서도 멈춤 0회, 경고 한 번씩, 원인 일치.
- **세 분류의 재현.** 요청이 틀린 경우(`0x13`, `0x12`), 상대 프로세스 종료(`0x15/0x81`), 연결 쪽 문제(보내는 쪽 QP 오류
  `0x05/0xf5`, 받는 쪽 QP 오류 `0x15/0x81`)를 두 라이브러리에서 재현. 분류 결과는 모두 기대와 일치, 멈춤 0회.
- **어디까지 끝났는지는 하한으로 기록.** 오류 기록의 요청 번호는 "그 아래는 모두 완료"를 뜻하는 하한. put 수만 개가
  떠 있는 도중에 QP를 죽인 50회 모두에서 기록된 번호가 실제 도착분 이하(NCCL 기본 CQ는 정확히 일치).
- **상대 죽음은 약 0.5 s에 판정.** rank 4개에서 받는 rank를 전송 도중 SIGKILL(8회): 보내던 rank만 경고 한 줄, flush 정지 0.49–0.72 s(원본은 약 58 s). 같은 포트의
  다른 job이 카운터를 올리는 중에도 동일. 판정의 근거 신호: 사라진 QP로 가는 재전송마다 보내는 쪽 포트의 `rp_cnp_handled`가 +1, 첫 상승은 죽은 뒤 0–20 ms.
- **죽음 오판은 0회.** 장애 없는 실행, 상대가 살아 있는 QP 오류, 이웃의 정상 종료(flush 대기와 counter 대기, 카운터 잡음 유무) 모두. 이전 구현은 요청이
  떠 있는지를 GPU 쪽 번호로 판단해 counter 대기 + 정상 종료 + 잡음에서 3회 중 3회 오판, NIC의 PSN으로 바꾼 뒤 0회.
- **정상 경로 비용.** NCCL `ring_exchange` 원본 대비 +0.06%, +0.5–1.1%, +0.0–0.2%, −0.1–−0.2%(구성 4가지, 20회씩 두 번, 원본의 회차 간 편차
  0.1–4.4%). NVSHMEM put 지연 +1.1%, p 지연 +1.7%, 대역폭은 편차 안(10회).

## 한계

- 소프트웨어로 넣은 장애만 대상. 케이블이나 펌웨어 결함 같은 물리 장애는 미포함
- vendor_err 값은 드라이버 헤더에 정의가 없어 측정으로 정한 값. ConnectX-6(MT4123) 펌웨어 20.43.4100 한 가지에서 측정
- 노드 2개에서만 실행(NCCL은 GPU 한 장에 rank 둘을 올린 rank 4개까지, NVSHMEM은 GPU 한 장에 PE 둘). 스위치 없는 직결 링크
- 죽음 판정은 죽은 rank에게 보내던 ring 이웃만 가능. 받기만 하는 rank, 이웃이 아닌 rank, 장비 전원 차단(소켓이 닫히지 않음)은 대상 밖. counter로 기다리는 GPU 대기는 판정으로 풀리지 않음. 스위치가 있어 혼잡이 카운터를 올리는 망은 미확인(이 직결 링크에서는 실제 부하가 카운터를 올리지 않음)
- 실패한 요청을 정확히 짚지는 못함. 기록은 "여기까지는 끝났다"는 하한이며, 그 뒤 구간의 요청은 완료 여부 미확정
- 복구 규칙과 설계(`RECORD.md` 4.1, 4.3절)는 구현 전. 복구를 실행해 확인한 것 없음
- 실행 로그는 미공개(관리망 주소 포함). `RECORD.md`가 가리키는 `runs/...` 경로는 이 저장소에 없음
