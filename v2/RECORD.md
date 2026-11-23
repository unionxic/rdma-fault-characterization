# rdma-recovery: NCCL와 NVSHMEM 오류 복구

이 폴더의 단일 기록이다. `~/rdma-error`의 실험 문서와 따로 관리하고, 그쪽 문서에는 덧붙이지 않는다.
기존 복구 패치와 설계 문서는 참고하지 않고 원본 소스에서 새로 만든다.
현재 유효한 것만 적는다. 폐기된 결정과 지나간 경위는 남기지 않고 지운다.

표시: `[측정]` 원자료나 코드에서 직접 확인, `[추론]` 해석, `[미확인]` 확인 안 함.

| 항목 | 값 |
|---|---|
| 상태 | `RUNNING` |
| 작성일 | 2026-11-19 |
| 마지막 갱신 | 2026-11-23, NCCL `cqe_ci` 오류 표시, 오류 분류 근거를 syndrome 13개 기준으로 다시 씀, QP context 원인 조회 채택 |

## 1. 목표 (결정, 2026-11-19)

- 대상은 NCCL과 NVSHMEM의 오류 복구다.
- 먼저 직접 보고한 이슈 네 건을 고친다. 오류가 보이지 않으면 복구가 판정할 것이 없다.
- 그다음 4절의 분류에서 복구할 수 있는 것 전부를 복구한다.
- 판정에는 CQE의 status와 vendor_err, 그리고 TCP 소켓의 열림/닫힘을 쓴다.
- 생사 확인에 새 소켓을 만들지 않는다(결정, 2026-11-23; 2026-11-21의 "전용 소켓을 따로 연다"를 바꿈). 이미 열려 있는
  소켓으로 볼 수 있는 경우만 본다. 볼 수 없는 경우는 생사를 "모름"으로 두고 규칙의 기본값으로 간다.
  - NCCL 일반 IB 경로: 연결마다 열려 있는 TCP 소켓 `[측정: 소스, net_ib/common.h:386, :654]`.
  - NCCL GIN: bootstrap ring의 양옆 이웃과의 소켓 `[측정: bootstrap.cc:500–513]`. 이웃이 아닌 상대(rank 4개 이상)는 볼 수 없다.
    지금 클러스터(노드 2개)에서는 상대가 곧 이웃이다.
  - NVSHMEM: 상대 PE로 가는 소켓이 없다(6절 2026-11-20). mpirun으로 띄우면 PE 하나가 죽을 때 mpirun이 job 전체를 끝낸다
    `[측정: 6절 2026-11-23, n=1]`. 그래서 살아남아 오류를 보는 PE에게 상대는 죽지 않은 것으로 본다.
  - 소켓은 열림/닫힘만 읽는다. 새 스레드는 띄우지 않고, 오류가 났을 때 기존 스레드가 본다.

## 2. 소스

| 무엇 | 경로 | 버전 | 확인 |
|---|---|---|---|
| NCCL | `nccl/` | v2.32.6-1, `ad2d192` (최신 release, 2026-11-09) | `[측정]` `git log -1`, `makefiles/version.mk` |
| NVSHMEM | `nvshmem/` | v3.8.0-0, `270759e5` (최신 release) | `[측정]` `git log -1` |

- 둘 다 release에서 시작한다. upstream이 이미 고친 것도 이 폴더의 코드에 직접 반영한다.
- 두 저장소 모두 로컬 브랜치 `recovery`에서 작업한다. 2026-11-23에 이슈별로 커밋했다: NCCL `cf1e2ec`(#2480),
  `07adc5b`(#2483), NVSHMEM `26eb3006`(#117), `d0f3ee2a`(#120). push는 하지 않았다.
- 빌드 환경 `[측정: 2026-11-19 rain]`: MOFED 23.10-7.1.8, rdma-core 2307mlnx47, `mlx5dv.h` 있음, CUDA 12.8.93, gcc 9.4.0,
  cmake 3.28.0, OpenMPI 4.1.8(`~/opt/openmpi-4.1.8`), UCX 1.16.0. DOCA GPUNetIO는 NCCL 소스에 들어 있어 따로 설치할
  필요가 없다. gdrcopy v2.5.2를 2026-11-20에 rain과 sunny 둘 다 넣었다: 라이브러리 `~/opt/gdrcopy/lib`, 모듈은 `~/rdma-recovery/deps/gdrcopy/insmod.sh`로 올림(재부팅하면 다시 올려야 함). NVSHMEM은 gdrcopy를
  실행 중에 불러오므로 빌드에는 필요 없고, IBGDA는 CPU가 doorbell을 울리는 방식에서만 쓴다
  `[측정: 소스, transport_gdr_common.cpp:246의 dlopen, ibgda.cpp:439–444, 2026-11-21 재확인]`.
- sunny `[측정: 2026-11-19]`: Ubuntu 22.04, 커널 6.8, MOFED 25.10, RTX A4000(sm_86), 드라이버 580.178.04, gcc 11.4.0,
  cmake 3.22.1. 홈이 rain과 공유되지 않아 소스를 복사해 따로 빌드한다. 기본 경로의 nvcc가 11.5라 CUDA 경로를 명시한다.
  살아 있는 포트는 rain `mlx5_1`(GID 4), sunny `mlx5_0`(GID 3). rain의 GPU BAR1은 256 MiB.

## 3. 먼저 고칠 이슈

| 이슈 | 내용 | GitHub 상태 (2026-11-19) | 이 폴더의 코드 |
|---|---|---|---|
| nvshmem #117 | CPU 프록시가 doorbell record의 틀린 word에 써서, 장애 뒤 오류 CQE가 안 생기고 `nvshmem_quiet()`가 멈춘다 | CLOSED, "Fixed internally". 수정은 devel에만 있고 release 3.8.0에는 없다 | 소스 고침. `ibgda.cpp:518`, `:582`를 `dbr_offset + sizeof(__be32)`로 바꿨다 `[측정: git diff 2줄]`. GPU 경로의 같은 계산(`ibgda.cpp:3936`)과 일치한다(2차 독립 코드 검사). 장애를 넣은 확인은 하지 않는다(결정, 2026-11-21) |
| nvshmem #120 | release 빌드가 오류 CQE를 읽고 버린다. `nvshmem_quiet()`가 정상 반환하고 fetch가 틀린 값을 돌려준다 | OPEN, 10-15 이후 답 없음 | 고침(2026-11-20 실행 기록). device가 첫 오류 CQE를 host 메모리에 남기고 host가 WARN 한 줄로 알린다. application은 `nvshmemx_get_op_error()`(host와 GPU 커널 양쪽)로 오류와 분류(요청 문제 / 로컬 QP / 상대 쪽 / 모름)를 물을 수 있다. 기록이 없는 구성(IBGDA가 아닌 transport)에서는 `NVSHMEMX_ERROR_NOT_SUPPORTED`를 돌려준다. 남은 것: 묻지 않으면 quiet는 여전히 정상 반환하고 fetch 값은 틀림; 기록 칸이 프로세스에 하나뿐이고 지우는 길이 없음(2차 검사 지적 4); 오류 뒤에도 송신 큐 칸이 재사용됨(지적 5); 기록에 상대 PE·주소·길이·key가 없음(지적 8). 셋 다 2단계에서 다룸 |
| nccl #2483 | GIN GDAKI에서 실패한 put을 device 코드가 알 수 없고, host는 10 s 조회에서 한 번만 본다 | OPEN, 답 없음 | 고침(수정 1–5, 아래 실행 기록, 독립 코드 검사 1회 반영). 양방향(sunny가 보냄, rain이 보냄) 각 54회 확인. 남은 것: host가 원인을 읽으려면 gdrcopy 필요(없으면 vendor_err 0); void인 flush·wait는 오류를 못 돌려줌; host 조회 간격 기본 10 s; 오류 뒤에도 put이 SQ 칸을 계속 예약해 덮어씀(재전송 단계에서 미완료 요청 보존 필요, 검사 지적 9); CPU proxy 방식의 요청 중단은 빌드만 됨 |
| nccl #2480 | `NCCL_GIN_GDAKI_NIC_HANDLER=6`이 init을 통과한 뒤 조용히 멈춘다 | CLOSED 11-17, 수정은 dev 브랜치에만 있다 | 소스 고침. `gdakiCheckDeviceSupport()` 첫머리에서 BlueFlame 플래그가 든 값을 WARN과 `ncclInvalidUsage`로 거절한다 `[측정: git diff 7줄]`. 실행하면 WARN 뒤 CPU proxy로 내려가 통과하고, GDAKI를 강제하면 `ncclCommWindowRegister`가 실패로 끝난다(멈추지 않음) `[측정: 6절 2026-11-19 `verify.sh`]` |

## 4. 오류 분류의 근거 (결정, 2026-11-23)

분류의 정당성은 세 단으로 세운다. "소프트웨어로 일으킬 수 있는 오류를 일으켜 봤다"가 주장의 범위다.

1. **전체 집합은 드라이버 정의다.** 완료 오류 코드(CQE syndrome)는 `mlx5dv.h`에 13개로 닫혀 있다
   `[측정: rain /usr/include/infiniband/mlx5dv.h:1064–1076]`. 전체를 우리가 정하지 않는다.
2. **그중 소프트웨어로 일으킬 수 있는 것을 일으켰다.** 10개 재현, 3개는 못 한 이유를 적는다
   `[측정: 6절 2026-11-23 `synd` 행, rain과 sunny, 경우당 3회, CPU verbs loopback]`.
3. **라이브러리가 낼 수 있는 것만 분류에 남긴다.** NCCL GIN GDAKI와 NVSHMEM IBGDA의 GPU 경로는 RDMA write, read,
   atomic만 쓰고 수신 큐 크기가 0이다 `[추론: 소스의 opcode 상수와 QP 설정, gin_host_gdaki.cc:954,
   ibgda.cpp:2468, ibgda_device.cuh]`. SEND, 즉시값 딸린 write, memory window가 있어야 나는 코드는 "해당 없음"이다.

분류에서 빠진 코드와 처음 보는 코드는 원인을 붙여 바로 실패시킨다(기본값).

| syndrome | 뜻 | 재현 | 넣은 장애 → vendor_err | 라이브러리 | 옛 번호 |
|---|---|---|---|---|---|
| 0x01 | 로컬 길이 | 응답 쪽 | 수신 버퍼 작음 → 0xd7 | 해당 없음(수신 없음) | |
| 0x02 | 로컬 QP 동작 | 함 | WQE 형식 오류 → 0x68 | 남김(라이브러리 결함일 때) | |
| 0x04 | 로컬 보호 | 함 | 잘못된 lkey 0x52, SGE가 MR을 넘음 0x53, 쓰기 권한 없는 MR로 READ 0x33 | 남김 | 1–3 |
| 0x05 | flush | 함 | 로컬에서 ERR로 바꾼 QP에 post 0xf5, 앞선 오류 뒤의 요청 0xf9 | 남김. 0xf9는 원인이 아니다 | 4 |
| 0x06 | memory window | 못 함 | bind 4가지 중 3가지는 성공으로 끝나고 1가지는 `ibv_bind_mw`가 거절 | 해당 없음(MW 안 씀) | |
| 0x10 | 잘못된 응답 | 시도 못 함 | 규격에 어긋난 응답을 보낼 수단이 없음 | 기본값 | |
| 0x11 | 로컬 접근 | 응답 쪽 | 즉시값 딸린 write의 잘못된 rkey → 0xc2 | 해당 없음(즉시값 안 씀) | |
| 0x12 | 원격 잘못된 요청 | 함 | QP에 쓰기 권한 없음, 정렬 안 된 atomic, 응답 쪽 READ 한도 0, 수신 버퍼 작음 → 모두 0x8a | 남김 | 5 |
| 0x13 | 원격 접근 | 함 | 잘못된 rkey, 범위 밖, 권한 없는 MR → 모두 0x88 | 남김 | 6, 9 |
| 0x14 | 원격 동작 | 함 | 응답 쪽 수신 버퍼의 lkey·권한 오류 → 0x89 | 해당 없음(수신 없음) | |
| 0x15 | 재시도 초과 | 함 | 상대 QP 파괴, ERR, RESET → 모두 0x81 | 남김 | 8, 9 |
| 0x16 | RNR | 함 | 수신 WQE 없음 → 0x87 | 해당 없음(수신 없음) | 7 |
| 0x22 | 원격 중단 | 시도 못 함 | 정의상 UD/UC와 SRQ의 오류, 넣을 방법을 못 찾음 | 기본값 | |

- 라이브러리에 남는 코드는 6개다: 0x02, 0x04, 0x05, 0x12, 0x13, 0x15.
- 같은 코드로 묶이는 원인이 있다(0x13 세 가지, 0x12 네 가지, 0x15 세 가지). 0x13과 0x15에서 상대가 살아 있는지는
  소켓으로 가른다(옛 번호 6/9, 8/9).
- **원인을 읽는 곳.** NIC는 QP마다 첫 오류를 QP context에 보관하고(QUERY_QP `qpc_ext`,
  `qp_context_extension.error_syndrome`), 뒤따른 flush가 그것을 지우지 않는다 `[측정: 6절 2026-11-23]`. CQE가
  flush로 덮여도 host는 이 값으로 원인을 읽는다. 두 라이브러리 모두 이 값을 쓴다.
- 한계: 소프트웨어로 넣은 장애이고 물리 장애(케이블, 펌웨어 결함)가 아니다. vendor_err는 드라이버 헤더에 정의가
  없어 측정값이며 ConnectX-6(MT4123) 펌웨어 20.43.4100 한 가지에서 쟀다. 재현은 한 프로세스 안 loopback RC QP다.
  상대 프로세스 죽음(옛 번호 9)은 이 시험에 없다.
- 4.1절과 4.2절의 번호는 이 표의 "옛 번호"다.

## 4.1 복구 규칙 (결정, 2026-11-23: 질문 1을 가볍게 두는 조건으로 진행)

원인마다 처리를 따로 두지 않고, 질문 세 개를 순서대로 물어 정한다(결정, 2026-11-23: 경우별 처리보다 보편
규칙). 규칙의 틀은 결정됐고, 아래 처리 내용은 `[추론]`이며 복구를 실행해 확인한 것은 없다. 근거는 2026-11-19의 소스 판독 둘(NCCL 2.32.6, NVSHMEM
3.8.0)과 논문·기존 라이브러리 조사, 그리고 4절의 측정이다.

| 순서 | 질문 | 무엇으로 아는가 | 답에 따른 처리 |
|---|---|---|---|
| 1 | 같은 요청을 다시 보내면 또 실패하는가 | syndrome과 vendor_err(4절)의 표 조회만. 상대에게 묻지 않는다(무거워지지 않게, 결정) | 그렇다: 그 요청만 실패시키고 원인을 최대한 특정해 알린다 |
| 2 | 상대가 살아 있는가 | 이미 열려 있는 소켓의 열림/닫힘(1절). 볼 수 없으면 "모름" | 죽었다: 실패. NCCL은 예비 프로세스로 교체(4.2절), NVSHMEM은 그 PE로 가는 QP를 막는다 |
| 3 | 끝나지 않은 요청을 다시 보내도 안전한가 | 요청 종류. write와 read는 안전, atomic은 실행 여부를 알아야 한다(미결정 사항) | 안전하다: QP를 다시 세우고 미완료분만 재전송(예산 안에서). 아니다: 실패 |

4절에서 라이브러리에 남긴 코드가 이 규칙에서 가는 곳:

| syndrome / vendor_err | 질문 1 | 처리 | 옛 번호 |
|---|---|---|---|
| 0x04 로컬 보호 (0x52, 0x53, 0x33) | 그렇다 | 그 요청만 실패. QP는 다시 세워 뒤따르던 정상 요청을 살린다(결정, 아래) | 1–3 |
| 0x02 로컬 QP 동작 (0x68) | 그렇다(WQE 형식이 틀림, 라이브러리 결함) | 그 요청만 실패. 지금 NVSHMEM 코드는 이 코드를 "모름"으로 분류한다 | |
| 0x12 원격 잘못된 요청 (0x8a) | 그렇다 | 그 요청만 실패. 넣어 본 네 가지 장애가 모두 요청이나 QP 설정의 문제였다 `[측정: 4절]` | 5 |
| 0x13 원격 접근 (0x88) | 그렇다(표 조회). 단 상대가 죽어도 이 코드가 나오므로 질문 2를 먼저 본다 | 상대가 죽었으면 상대 죽음으로 알림. 아니면 그 요청만 실패. 낡은 rkey를 되살리는 복구는 하지 않는다 | 6 |
| 0x15 재시도 초과 (0x81) | 아니다 | 질문 2로. 살아 있으면 상대에게 QP 상태를 물어, QP 문제면 바로 다시 세우고 경로 문제면 기한까지 재시도 | 8 |
| 0x05 / 0xf5 로컬 QP가 오류 상태 | 아니다 | 질문 2, 3으로. QP 쌍을 다시 세우고 미완료분만 재전송 | 4 |
| 0x05 / 0xf9 뒤따른 flush | 원인이 아니다 | QP context에서 원인을 읽어 위 줄 중 하나로 간다. 못 읽으면 기본값 | |
| CQE가 오지 않음 | 알 수 없다 | 질문 2로. 소켓이 닫혔으면 상대 죽음 | 9 |
| 그 밖(해당 없음으로 뺀 코드, 처음 보는 코드) | 알 수 없다 | 기본값: 원인을 붙여 바로 실패 | 7 |

- 옛 번호 7(RNR): 두 라이브러리 모두 수신 큐가 없어 해당 없음이다. NCCL 일반 IB 경로의 원본 설정(rnr_retry 7)에서는
  오류가 아니라 정지로 나타난다 `[측정: connect.cc:545]`.
- `0x13`과 `0x15`는 상대가 죽어도 나온다(옛 번호 9). 그래서 질문 2를 항상 거친다.

결정된 것 (2026-11-19):

- 복구 조정은 RDMA만 쓴다. TCP 소켓은 열림/닫힘만 읽는다. 깨진 QP로는 상대에게 알릴 수 없으므로 상대마다 조정용
  예비 QP가 필요하다 `[추론]`.
- `0x04`(옛 1–3)는 재시도하지 않는다. vendor_err로 요청 문제임이 구분되므로 원인을 붙여 바로 실패시킨다.
- `0x04` 뒤에는 QP를 다시 세워 뒤따르던 정상 요청을 살린다. 틀린 요청만 실패로 돌려주고 그 기록을 로그로 내보낸다.
  로그는 라이브러리의 기존 로그 출력에 한 줄 key=value로 남긴다: status, vendor_err, 상대 rank, QP 번호, 요청의 주소와
  길이와 key, 시각. 수집기는 후속 작업이다. 출력 지점에 "수집기가 생기면 여기서 보낸다"는 주석을 둔다.
- 오류를 알리는 방식: 자동 복구가 되는 것은 자동 복구한다. 안 되는 것은 세분화한 원인을 로그로 알린다. NVSHMEM은
  기본으로 원인을 찍고 중단하며, `NVSHMEM_IBGDA_ABORT_ON_OP_ERROR=0`을 준 application만 `nvshmemx_get_op_error()`로
  묻는다(결정 2026-11-23; 2026-11-20의 "중단 대신 조회"를 바꿈).
- vendor_err는 NIC 펌웨어가 오류 CQE에 써 넣는 값이다. `mlx5dv.h`는 syndrome 값에는 이름을 붙였지만 vendor_err 값은
  `ODP_PFAULT = 0x93` 하나만 정의한다 `[측정: rain /usr/include/infiniband/mlx5dv.h]`. 우리가 쓰는 값의 뜻은 측정으로
  정한 것이고, 잰 장비는 rain과 sunny 모두 ConnectX-6(MT4123), 펌웨어 20.43.4100이다 `[측정: ibv_devinfo, 2026-11-21]`.
- 코드양 관리(결정, 2026-11-21): 수정할 때마다 리팩토링하고, 수정 전후 길이 차이와 중복 함수·통합 가능 여부를
  본다.
- 로그 문구는 영어로, 각 라이브러리의 기존 양식을 따른다(NCCL은 `WARN` 매크로 양식, NVSHMEM은 그쪽 로그 매크로).
- NVSHMEM은 sunny에서만 돌린다. rain은 GPU BAR1이 256 MiB라 등록이 실패한다. sunny의 GPU 한 장에 PE 둘을 올리고
  `NVSHMEM_DISABLE_P2P=1`로 NIC를 거치게 한다(`shmem_sunny.sh`).

미결정 사항:

- **연결당 복구 예산.** 허용 지연 비율 ÷ 복구 1회 비용. 복구 1회 비용은 `[미확인]`.

- **중복과 손실 방지의 근거.** atomic(GIN signal, NVSHMEM signal과 AMO)은 재전송하면 두 번 실행된다. 두 판독 모두
  "상대 QP의 수신 순번을 QUERY_QP로 읽는다"에 기댄다. 오류 상태 QP에서 그 값이 정확한지는 `[미확인]`이고, 틀리면
  atomic이 걸린 복구는 거부로 내려간다.
- **재무장 PSN.** NCCL 판독은 새 PSN, NVSHMEM 판독은 양쪽 0을 냈다.
- **`0x02`와 `0x16`의 코드 분류.** NVSHMEM 코드는 `0x02`를 "모름", `0x16`을 "상대 쪽"으로 둔다. 표와 맞출지 정하지 않았다.
- **NCCL GIN에서 rank가 4개 이상일 때.** 생사 확인용 소켓을 따로 열면 풀리지만 2노드 클러스터에서는 시험할 수 없다.

조사에서 확인된 것:

- vendor_err를 판정에 쓰는 기존 라이브러리는 찾지 못했다.
- NCCL 2.32.6 내장 복원력은 장치가 하나면 치명 오류로 끝난다 `[측정: p2p_resiliency.cc:45–64]`.
- 가장 가까운 논문은 SHIFT(arXiv 2512.11094), R2CC(arXiv 2512.25059), VCCL(arXiv 2510.00991)이고, 셋 다 예비
  NIC나 예비 QP로 넘기는 방식이다. 상대 죽음과 GPU가 직접 보내는 경로는 다루지 않는다.

## 4.2 상대 프로세스 죽음의 복구: 핵심 가정 (결정, 2026-11-19)

**가정: 죽은 rank의 상태와 같은 것을 살아 있는 rank가 갖고 있다.**

- 나머지 rank를 멈추고, 예비 프로세스가 살아 있는 rank에서 현재 상태를 복사한 뒤, 죽은 순간의 step 하나만 다시 한다.
- 주기적 저장은 하지 않는다.
- 조건: 진행 중이던 step의 입력이 남아 있어야 한다. 결과를 입력 버퍼에 덮어쓰는 allreduce면 입력을 따로 보관한다.
- 쓸 API 후보: `ncclCommRevoke`, `ncclCommShrink`, `ncclCommGrow` `[측정: nccl.h.in:327, 345, 362]`. 동작은 `[미확인]`.

가정이 성립하는 범위 (2026-11-19 웹 조사, 문서 수준):

| 학습 방식 | rank의 상태 | 가정 |
|---|---|---|
| DDP (rank마다 모델 전체) | 전부 같다 | 성립 |
| Megatron식 TP × PP × DP, DP ≥ 2 | 다른 DP 묶음의 같은 자리 rank와 같다 | 성립 `[추론]`. optimizer 상태를 DP 방향으로 나누는 옵션을 켜면 깨진다 `[미확인]` |
| FSDP, ZeRO-3 | rank마다 다른 조각 | 불성립 |
| DP = 1 | 복제본 없음 | 불성립 |

## 5. 작업 순서

- [x] 새 폴더에 소스 받기
- [x] 이슈 네 건의 현재 상태 확인
- [x] 빌드(rain과 sunny 모두 NCCL, NVSHMEM 빌드됨)
- [x] 첫 실행(NCCL GIN은 rain과 sunny 사이, NVSHMEM은 sunny 안에서 통과)
- [x] 이슈 네 건 수정과 재현 시험(#117은 장애 확인 없이 수정만)
- [ ] 4절 분류에서 복구 대상 정하기(4.1절 규칙은 제안 상태)
- [ ] 복구 설계와 구현

## 6. 실행 기록

`runs/`의 NCCL 로그에는 bootstrap이 쓴 관리망 주소가 찍혀 있다. 이 폴더 밖으로 옮기거나 커밋하지 않는다.
2026-11-21에 sunny의 `runs/`와 `socks.sh`를 rain으로 복사했다. 아래 "로그 sunny"로 적힌 폴더는 rain `runs/`에도 있다.

| 시각 | 무엇을 했나 | 결과와 근거 |
|---|---|---|
| 2026-11-19 | NCCL v2.32.6-1과 NVSHMEM v3.8.0-0을 받고 이슈 네 건을 확인. #117 수정 2줄, #2480 검사 7줄을 넣음. 빌드 안 함 | 2절, 3절, 각 저장소 `git diff` |
| 2026-11-19 | 원인별 복구 방안 상의, 논문 조사, 기존 방법론 조사 | 4.1절 |
| 2026-11-19 | rain에서 NCCL을 #2480 검사 포함해 빌드 | 빌드됨, exit 0, 오류 0줄. `nccl/build/lib/libnccl.so.2.32.6`에 검사 문구가 들어 있음 `[측정: strings]`. 실행은 안 함. 로그 `build-nccl.log` |
| 2026-11-19 | GIN GDAKI와 IBGDA의 전제 조건을 rain과 sunny에서 조회(`probe/probe.c`, 트래픽 없음, 각 1회) | 두 서버 모두 통과 `[측정]`: CUDA 가상 메모리 방식 GPU 직접 RDMA 지원 1, dma-buf 지원 1, 기본 NIC context에서 DEVX 명령 성공, UAR 두 종류 할당 성공, GPU가 UAR을 매핑 성공. 실제 초기화와 전송은 안 함 |
| 2026-11-19 | rain에서 NVSHMEM을 #117 수정 포함해 빌드(IBGDA 켬, gdrcopy 끔, sm_75) | 빌드됨, exit 0. `nvshmem/build/src/lib/nvshmem_transport_ibgda.so`와 perftest가 만들어짐. 실행은 안 함. 로그 `build-nvshmem.log` |
| 2026-11-19 | sunny에 소스를 복사해 NCCL, NVSHMEM 빌드 | 둘 다 빌드됨, exit 0 |
| 2026-11-19 | rain과 sunny 한 프로세스씩 NCCL GIN 예제 `alltoall_gin` 실행(`verify.sh`, `cluster_run.sh` 안, 경우당 1회) | `[측정]` 기본 설정: GDAKI로 올라가 PASSED. GDAKI 강제: PASSED. CPU proxy 강제: PASSED. `NIC_HANDLER=6`: 양쪽에 WARN이 나오고 CPU proxy로 내려가 PASSED(멈추지 않음). `NIC_HANDLER=6`에 GDAKI 강제: `ncclCommWindowRegister`가 "internal error"로 실패하고 끝남(멈추지 않음). 로그 `runs/verify-20261119-234007/` |
| 2026-11-19 | sunny 한 대에서 PE 둘로 NVSHMEM `shmem_put_bw` 실행(IBGDA, P2P 끔, 1회) | `[측정]` rc 0, 오류 0줄, 4 B에서 4 MiB까지 대역폭 표가 나옴(최대 7.31 GB/s, 512 KiB). 로그 `runs/shmem-20261119-235539/` |
| 2026-11-20 | #2483 재현 프로그램 `repro/gin_fault.cu`를 새로 작성(put과 flush 120번, 10번째 put이 창 밖 주소, rain이 보내고 sunny가 받음, GDAKI 강제). 수정 전 빌드에서 경우당 1회 | `[측정]` 잘못된 put 없음: 120번 반환, 120칸 도착. 잘못된 put: flush가 74번째에서 멈춤, 10칸 도착, host 오류 표본 1개(10001 ms), 마지막 조회는 오류 없음. 시간 제한 flush: 오류 코드 없이 시간 초과. 로그 `runs/ginfault-before-20261120-001449/` |
| 2026-11-20 | 수정 1(device): CQ 구조체 빈 칸에 오류 기록(WQE 번호, syndrome, vendor_err)을 남기고, 대기 루프가 그 기록을 보면 오류로 빠져나오며, GIN wait와 flush가 `ncclRemoteError`를 돌려줌. 기본 CQ 방식만. 수정 2(host): 한 번 본 QP 오류를 계속 보고 | `[측정, 경우당 1회]` 잘못된 put 없음: 120번 반환, 120칸 도착. 시간 제한 없는 flush: 멈춤 없이 120번 반환. 시간 제한 flush: 10번째부터 110번 모두 `ncclRemoteError`. host(조회 간격 1 s, 느린 커널): 1001 ms부터 끝까지 오류(표본 2578개), 마지막 조회도 오류. 로그 `runs/ginfault-fix2-*/`. 원인 `[측정: 소스]`: 오류 CQE에서는 소비 위치(cqe_ci)가 전진하지 않아, 거기서 CQ 크기(128) 넘게 떨어진 요청이 영원히 대기 |
| 2026-11-20 | sunny에 gdrcopy v2.5.2 빌드, `gdrdrv` 모듈 적재, 자체 검사 `gdrcopy_sanity` 실행 | 36개 중 31 통과, 0 실패, 5 건너뜀(n=1). 로그 sunny `~/rdma-recovery/build-gdrcopy.log` |
| 2026-11-20 | 수정 3(host가 원인을 읽음): gdrcopy가 있으면 QP 구조체를 host에도 매핑해 `cq->err`를 읽고 기존 WARN에 syndrome, vendor_err, WQE 번호를 넣음. 기본 CQ는 오류를 보면 앞 칸으로 거슬러 올라가 첫 실패를 기록. 수정 4: collapsed CQ 두 방식에도 같은 기록을 붙이고, 오류가 기록된 QP에는 새 요청을 NIC에 넘기지 않음(`doca_gpu_dev_verbs_submit`, `submit_multi_qps`). sunny가 보내고 rain이 받음, 경우당 n=1 | 기본 CQ와 collapsed(GPU): 정상 실행 120/120, 잘못된 put 뒤 멈춤 없음, 시간 제한 flush 110번 `ncclRemoteError`, host WARN에 `syndrome=0x13 vendor_err=0x88 wqe_counter=20`(실패한 put의 WQE). host가 읽는 collapsed(`NCCL_GIN_GDAKI_CQ_TYPE=2`)는 rain에 gdrcopy가 없어 시작에서 실패, 시험 못 함. 원본 대비 NCCL 8개 파일 +198 −32. 로그 sunny `runs/ginfault-fix4-cq{0,1,2}-*` |
| 2026-11-20 | rain에 gdrcopy v2.5.2 빌드, `gdrdrv` 적재, `gdrcopy_sanity` | 36개 중 31 통과, 0 실패, 5 건너뜀(n=1). 로그 `build-gdrcopy.log` |
| 2026-11-20 | 수정 1–4 반복 시험. 재현에 `BURST`(flush 전에 put 여러 개), `COUNTER`(카운터 put, QP 두 개) 추가. sunny가 보냄. CQ 방식 3가지 × (put 1개, put 8개, 카운터 put) × 10회 = 90회, 모두 host 조회 1 s와 시간 제한 flush 사용 | 90회 모두: 멈춤 없음, 120번 반환, 110번 `ncclRemoteError`, 받는 쪽 10칸 도착, host WARN `syndrome=0x13 vendor_err=0x88`, WQE 번호는 실패한 put(put 1개·카운터 20, put 8개 160). collapsed 두 방식 60회에서 원인이 '취소됨'으로 덮어써진 경우 0회. host가 읽는 collapsed의 정상·시간 제한 없는 경우도 통과(n=1). 로그 sunny `runs/ginfault-rep-cq*`, `runs/ginfault-fix4b-cq2-*` |
| 2026-11-20 | nvshmem #120 재현 `repro/shmem_fault.cu`(sunny, PE 2개, p+quiet+g 40번, 10번째 p가 heap 밖 주소), 실행 `shmem_fault.sh`. 수정 전 n=1 | 정상: 40/40 도착. 잘못된 p: quiet 40번 모두 반환, g는 10번만 맞음, 10칸 도착, 로그에 오류 흔적 없음. 로그 sunny `runs/shmemfault-before-*` |
| 2026-11-20 | nvshmem #120 수정: `ibgda_poll_cq`가 첫 오류 CQE(QP 번호, WQE 번호, syndrome, vendor_err)를 `state.extra`가 가리키는 host 메모리에 남기고, proxy 스레드가 `WARN: IBGDA error CQE: ...` 한 줄을 한 번 출력. 4개 파일 +56 −4(#117 포함) | 정상 3회: 40/40. 잘못된 p 10회: 10회 모두 WARN에 `syndrome=0x13 vendor_err=0x88 wqe_counter=16`. quiet 반환과 g 값은 수정 전과 같음. 로그 sunny `runs/shmemfault-fix-*` |
| 2026-11-20 | nvshmem 조회 함수(결정: 중단 대신 조회): `nvshmemx_get_op_error(nvshmemx_op_error_t*)`를 host와 device에 추가. 분류는 CQE만으로 정함: syndrome 0x04·0x12는 요청 문제, 0x05+vendor_err 0xf5는 로컬 QP, 0x13·0x15·0x16은 상대 쪽, 나머지는 모름. WARN에도 `class=` 추가. 재현에 `CHECK=1`(커널이 quiet 뒤에 묻고 멈춤). NVSHMEM 원본 대비 12개 파일 +145 −4 | 정상 3회: 오류 없음(class=0), 40/40. 묻지 않음 5회: 전과 같음(quiet 40번 반환, g 10번만 맞음), host 조회는 `class=3 syndrome=0x13 vendor_err=0x88 wqe_counter=16`. 물음 10회: 10회 모두 커널이 10번째에서 멈춤, 틀린 g 0건. 로그 sunny `runs/shmemfault-q-*` |
| 2026-11-20 | NVSHMEM PE가 가진 소켓 확인(sunny, PE 2개, 실행 중 `ss`와 `/proc/<pid>/fd`, n=1씩). 원인 5 재현: `KIND=1`(8바이트로 정렬되지 않은 주소에 `nvshmem_long_atomic_add`), `CHECK=1`, n=5 | 소켓: btl `self,vader`에서는 PE마다 TCP 1개(두 PE가 같은 포트로 연결, 실행기 쪽)와 unix 6개, 상대 PE로 가는 TCP 없음. btl `self,tcp`에서는 상대 PE와 TCP 2개가 생기지만 OpenMPI 것이고 NVSHMEM 코드는 그 fd를 갖지 않음 `[추론: bootstrap이 MPI 호출만 씀]`. 원인 5: 5회 모두 `syndrome=0x12 vendor_err=0x8a`, 조회 분류 "요청 문제", 커널이 10번째에서 멈춤. 로그 sunny `runs/shmemfault-k1-*` |
| 2026-11-20 | 독립 코드 검사 1회(#2483 변경분, 읽기 전용, 지적 11건). 반영(수정 5): collapsed에서 덮어써지는 중인 CQE를 성공으로 넘기던 경로 제거, CQE 읽기를 cache 우회 load와 앞뒤 헤더 비교로 통일, 재사용된 칸을 오류로 기록하지 않게 확인 추가, 카운터 put에서 한 QP가 실패하면 함께 버려지는 QP도 실패로 표시, host가 읽는 CQ의 기록도 앞뒤 비교, host WARN은 원인이 찍힐 때까지 다시 조회, CPU proxy 방식도 실패한 QP는 전송 중단, 주석 정정. 미반영: 지적 9(오류 뒤 SQ 칸 덮어쓰기)는 재전송 단계로 넘김, 지적 10(WQE 번호 48비트)은 한계로 주석 | 반영 뒤 재시험, sunny가 보냄: CQ 방식 3가지 × (정상, 시간 제한 없음, 시간 제한 각 1회 + put 1개·8개·카운터 각 5회) = 54회 모두 수정 4와 같은 결과(멈춤 없음, `vendor_err=0x88`, WQE 20 또는 160). NCCL 원본 대비 8개 파일 +248 −37. 로그 sunny `runs/ginfault-fix5-*` |
| 2026-11-21 | #2483 수정 5를 rain이 보내는 방향으로 재시험. 구성은 sunny 방향과 같음: CQ 방식 3가지 × (정상, 시간 제한 없음, 시간 제한 각 1회 + put 1개·8개·카운터 각 5회) = 54회 | `[측정]` 54회 모두 sunny 방향과 같은 결과: 멈춤 없음, 시간 제한 flush 110번 `ncclRemoteError`, 받는 쪽 10칸, host WARN `syndrome=0x13 vendor_err=0x88`, WQE 20 또는 160. collapsed 30회에서 원인이 덮어써진 경우 0회. 로그 `runs/ginfault-fix5r-*` |
| 2026-11-21 | 독립 코드 검사 2회(NVSHMEM 변경분 전체). 지적 10건| 반영 7건: (1) 오류 기록을 `cons_idx` 공개 전으로 옮김 (2) 찢긴 CQE 복사는 같은 값이 읽힐 때까지 다시 읽음(NCCL 수정과 같은 방식), 필드를 지역 변수로 먼저 읽음 (3) ABI 심볼 목록 정렬 위치, NVSHMEM 검증 함수 통과 `[측정]` (6) 조회가 `nullptr`에 `INVALID_VALUE`, 기록 없는 구성에 `NOT_SUPPORTED` (7) `0xf5`를 이름 붙인 측정 규칙으로 하고 장비·펌웨어를 주석에, 분류표 자체 검사 `repro/decode_test.cpp` 통과 `[측정]` (9) 주석 정정, 기록 읽기를 `nvshmemi_ibgda_load_err` 하나로 통합, WARN의 `pe=`를 `reporting_pe=`로 (10) 재현이 커널 실행 오류와 종료를 확인, `THREADS` 추가. 2단계로 넘김 3건: (4) QP·세대별 기록과 지우기 (5) 실패 요청 보존 (8) 기록에 상대 PE·주소·길이·key |
| 2026-11-21 | 위 수정 뒤 NVSHMEM 재현(sunny, `shmem_fault.sh`). 스레드 1개: 정상 3회, 조회 안 함 5회, 조회함 10회, 정렬 오류 5회. 스레드 여러 개(`THREADS`, 스레드 0만 잘못된 요청): 8개 정상 3·조회 안 함 5·조회함 20회, 64개 조회함 20회·정렬 오류 10회 | `[측정]` 스레드 1개 23회: 2026-11-20과 같은 결과(`0x13/0x88` class 3, `0x12/0x8a` class 1, 조회하면 10번째에서 멈춤). 스레드 여러 개 55회: 잘못된 요청 뒤 quiet가 돌아왔는데 조회가 "오류 없음"인 경우 0회. **그러나 55회 모두 기록된 것은 원인이 아니라 뒤따른 flush(`syndrome=0x05 vendor_err=0xf9`, class 4 "모름")였다.** 같은 QP에 뒤따라 쌓인 요청의 flush CQE가, 누가 읽기 전에 단일 CQE 칸을 덮어쓴 것 `[추론]`. 수정 전 코드에서 "오류 없음"이 실제로 나오는지는 돌려 보지 않아, 이 시험이 지적 1을 가려낸다는 증거는 없다 `[미확인]`. 또 RC QP가 PE당 2개이고 요청마다 번갈아 쓰여(`ibgda_get_rc`, map type NONE) 한 QP가 실패해도 다른 QP의 요청은 계속 도착한다(스레드 8개·조회 안 함에서 40칸 도착) `[측정: 실행] [추론: 소스]`. 로그 `runs/shmemfault-r2-*` |
| 2026-11-21 | 정상 경로 성능 A/B 1차. 원본 release를 `base/`(git worktree)에 따로 빌드(cmake 옵션 동일 확인), `ab.sh`로 원본·수정본을 번갈아 실행, `ab_report.py`로 중앙값 비교. NVSHMEM: sunny, perftest 4종 × 10회. NCCL: rain↔sunny, `ring_exchange` 예제 × 20회, GDAKI 강제 | `[측정]` NVSHMEM: 4 B–4 KiB 지연이 +0.6–5.2%(0.1–0.5 us, 원본의 회차 간 편차는 1–2%), `shmem_put_bw` 대역폭은 편차 안. atomic 지연 3개 줄은 원본에서도 8.7/13.4 us 두 값을 오가서 비교에서 제외. NCCL us/batch: 구성 1 +7.48%(118.89→127.79), 구성 2 +13.27%, 구성 3 +0.89%, 구성 4 +1.23%(원본 편차 0.2–2.1%). 원인 `[추론]`: NVSHMEM은 폴링마다 CQE `op_own`을 한 번 더 읽음, NCCL은 put마다 `cq->err`를 캐시 우회 load로 읽음(`doca_gpu_dev_verbs_submit`). 로그 `runs/ab-shmem-20261121-173139`, `runs/ab-gin-20261121-174136` |
| 2026-11-21 | NCCL 성능 저하 원인 가르기. 수정본 device 헤더를 하나씩 원본으로 바꿔 `ring_exchange`만 다시 빌드해 실행(헤더가 application에 inline되므로 가능), 조합당 3–6회. us/batch, 구성 1 / 구성 2 | `[측정]` 원본 헤더+수정 lib 117.9 / 108.7(host 라이브러리는 비용 없음). 수정본 전체 127.9 / 122.4. 대기 루프의 `cq->err` 읽기만 끔: 123.0 / 117.5. 그것과 submit의 실패 QP 확인까지 끔: 117.5 / 108. `gin_gdaki.h` 변경은 비용 없음(123.0 / 117.4 그대로). 즉 비용은 (가) 대기 루프가 돌 때마다 `cq->err`를 읽는 것 약 +5 us/batch, (나) put마다 submit에서 `cq->err`를 보는 것 약 +5 / +9 us/batch. load 종류를 바꾼 시도: 대기 루프를 sharing mode load로 → 122.8 / 113.3(submit 확인 끈 상태, 효과 없음, 되돌림). submit을 일반 load로 → 구성 2에서만 비용이 사라짐(채택). 읽기 한 번이 약 40 ns라 종류와 무관하게 비용이 남는다 `[추론]` |
| 2026-11-21 | 최종 코드(NVSHMEM: `op_own`을 한 번만 읽게 고침. NCCL: submit의 실패 QP 확인을 일반 load로)로 전체 재확인. NCCL 재현 54회 × 양방향, NVSHMEM 재현 43회(스레드 1개 23, 8개 10, 64개 10), A/B NCCL 20회·NVSHMEM 10회 | `[측정]` NCCL 108회: 수정 5와 같은 결과(멈춤 없음, host 조회 90회 모두 `syndrome=0x13 vendor_err=0x88`, WQE 20 또는 160, collapsed 60회에서 원인 덮어써짐 0회). NVSHMEM 43회: 2026-11-21 앞 시험과 같은 결과(스레드 여러 개 20회는 모두 flush `0x05/0xf9`가 기록됨, "오류 없음" 0회). A/B NCCL us/batch: 구성 1 +7.41%(119.28→128.12), 구성 2 +5.70%(1차 +13.27%), 구성 3 +0.79%, 구성 4 +0.57%. A/B NVSHMEM 4 B–4 KiB 평균: `shmem_put_latency` +1.00%(1차 +1.98%), `shmem_p_latency` +2.26%(1차 +2.92%), atomic 6줄 +1.02%, `shmem_put_bw` +0.10%(편차 안). atomic의 처음 두 시험(`unsigned int`, `unsigned long`)은 수정본이 약 4.7 us 느린 값으로 나온다(17.6 vs 12.8, 13.4 vs 8.7; 원본도 두 번째 시험은 8.7과 13.4를 오감). 원인 `[미확인]`, 위 평균에서 뺐다. 원본 대비 NCCL 8개 파일 +248 −37, NVSHMEM 12개 파일 +188 −9. 로그 `runs/ginfault-fix6*`, `runs/shmemfault-r3-*`, `runs/ab-gin-20261121-185448`, `runs/ab-shmem-20261121-185549` |
| 2026-11-23 | NCCL 대기 루프의 `cq->err` 읽기를 없앰. GPU가 폴링하는 CQ는 첫 기록과 함께 `cqe_ci`의 최상위 비트를 켜고, 대기 함수는 원래 하던 `cqe_ci` 비교에서 실패를 안다. host가 폴링하는 CQ는 그대로. 오류 처리 함수는 `__noinline__`. 양쪽 전체 빌드 뒤 재현 54회 × 양방향, A/B 20회. 원인 가르기는 헤더 조합당 3–4회 | `[측정]` 108회: 수정 5와 같은 결과(멈춤 없음, host 조회 90회 모두 `syndrome=0x13 vendor_err=0x88`, WQE 20 또는 160). A/B us/batch: 구성 1 +5.29%(119.26→125.57), 구성 2 +1.57%(108.20→109.90), 구성 3 +0.41%, 구성 4 +0.37%. submit의 실패 QP 확인을 끄면 구성 1 −0.57%, 구성 2 +1.01%(4회, 원본 편차 안): 남은 비용은 그 확인 하나. 가르는 중 확인한 것: 오류 처리 함수가 폴링 코드에 inline되면 구성 2가 +2–3%(110.7 vs 108), 떼어 내면 사라짐. 같은 코드도 배치에 따라 구성 1이 123.2–125.6으로 움직임. 원본 대비 NCCL 8개 파일 +275 −39(코드 190줄, 주석 73줄). 로그 `runs/ginfault-fix7*`, `runs/ab-gin-20261123-003311`, 가르기 `runs/ab-gin-20261122-23*`, `runs/ab-gin-20261123-00*` |
| 2026-11-23 | NCCL submit의 실패 QP 확인을 뺀 상태의 오류 주입. 소스는 그대로 두고 설치된 `qp.cuh` 사본만 원본으로 바꿔 `gin_fault`를 다시 빌드(양쪽 host에서 확인 문구 0줄 확인), 54회 × 양방향, 끝난 뒤 사본 복원(`cmp` 일치) | `[측정]` 108회 모두 확인을 넣은 상태와 같은 결과: 멈춤 없음, 120번 반환, 시간 제한 flush 110번 `ncclRemoteError`, 받는 쪽 10칸, host 조회 90회 모두 `syndrome=0x13 vendor_err=0x88`, WQE 20 또는 160. 이 시험에서는 확인을 빼서 잃는 것이 없었다. 로그 `runs/ginfault-nosub*` |
| 2026-11-23 | CQE syndrome 13개(`mlx5dv.h`) 재현 시도. `repro/synd.c`(CPU verbs, 한 프로세스 안에서 같은 포트의 RC QP 둘을 연결, A가 요청 B가 응답)와 `synd.sh`. 경우 29가지 × 3회, rain과 sunny 각각. 경우마다 양쪽 CQE, 비동기 이벤트, 포트 `hw_counters` 변화, 커널 로그(rain만, sunny는 권한 없음)를 기록. 라이브러리를 거치지 않은 NIC 수준 시험이다 | `[측정]` 10개 재현, 두 host의 코드와 이벤트가 같음. 요청 쪽 CQE(syndrome/vendor_err): 잘못된 lkey `0x04/0x52`, SGE가 MR을 넘음 `0x04/0x53`, 쓰기 권한 없는 MR로 READ `0x04/0x33`, WQE 형식 오류(byte_count 31번 비트) `0x02/0x68`, 로컬에서 ERR로 바꾼 QP에 post `0x05/0xf5`, 앞선 오류 뒤의 요청 `0x05/0xf9`, 잘못된 rkey·범위 밖·권한 없는 MR 모두 `0x13/0x88`, QP에 쓰기 권한 없음·정렬 안 된 atomic·응답 쪽 READ 한도 0·수신 버퍼 작음 모두 `0x12/0x8a`, 응답 쪽 수신 버퍼의 lkey 오류·쓰기 권한 없음 `0x14/0x89`, 수신 WQE 없음 `0x16/0x87`, 상대 QP 파괴·ERR·RESET 모두 `0x15/0x81`. 응답 쪽 CQE: 수신 버퍼 작음 `0x01/0xd7`, 수신 버퍼 lkey `0x04/0x32`·권한 `0x04/0x33`, WRITE_WITH_IMM의 잘못된 rkey `0x11/0xc2`. 재현 못 함: `0x06`(MW bind 4가지 시도 중 3가지는 성공으로 끝나고 1가지는 `ibv_bind_mw`가 거절), `0x10`·`0x22`(넣을 방법이 없어 시도 안 함). 같은 CQE를 가르는 다른 신호: `0x13/0x88` 세 경우는 응답 쪽 커널 로그가 다름(`QP N error: local protection error (0x3a 0x0 0x84)` / `(0x3b 0x0 0x9d)` / `(0x3b 0x0 0x9b)`), `0x12/0x8a`는 응답 쪽 비동기 이벤트(invalid request / access violation)와 커널 로그(atomic만 `unrecognized status (0xd1 0x0 0x0)`)로 일부 갈림. 커널 로그 괄호 값의 뜻은 `[미확인]`. 포트 카운터: `req_remote_access_errors`(0x13), `req_remote_invalid_request`(0x12), `local_ack_timeout_err`(0x15), `rnr_nak_retry_err`(0x16), `req_cqe_flush_error`(0x05/0xf9)는 따로 오르고, `0x02`·`0x04`·`0x14`·`0x05/0xf5`는 `req_cqe_error`만 오름. sunny에는 `req_transport_retries_exceeded`, `req_rnr_retries_exceeded`가 더 있음. 4절 표의 값(1–3, 4, 5, 6, 7, 8)은 이 장비에서 모두 같은 코드로 다시 나옴. 로그 `runs/synd-{rain,sunny}-20261123-115211`(커널 로그 없는 1차 `-1149*`) |
| 2026-11-23 | NVSHMEM에서 flush에 덮인 원인을 되찾는 방법 시험(sunny). (가) 포트 `hw_counters`: `shmem_cnt.sh`로 재현 전후 변화를 봄, 6개 구성 × 1회. (나) QP context의 오류 기록: `synd.c`에 QUERY_QP(`qpc_ext=1`) 조회를 넣어 rain과 sunny에서 확인한 뒤, NVSHMEM host의 오류 보고(`ibgda_report_device_error`)가 기록이 flush(`0x05`, vendor_err가 `0xf5`가 아님)일 때 그 QP를 조회해 syndrome과 vendor_err를 바꿔 쓰게 함(`ibgda_restore_cause`, RC QP만, WQE 번호는 flush의 것 그대로). 6개 구성 × 3회 | `[측정]` (가) 모든 구성에서 카운터 변화 없음(같은 방법으로 verbs QP의 `bad_rkey`는 `req_remote_access_errors+1`이 보임). 원인 `[측정: 소스]`: `ibgda.cpp:1671`이 QP를 `counter_set_id = 0`으로 만든다. (나) NIC 수준: `0x13/0x88` 뒤에 flush `0x05/0xf9`가 온 QP를 조회하면 `0x13/0x88`이 나옴(rain, sunny). 응답 쪽 QP에는 응답 쪽 원인이 남고(예: 잘못된 rkey `0x04/0x3a`, hw_err `0x84`), rain 커널 로그의 괄호 값은 이 기록의 (vendor_err, hw_type, hw_err)와 같음. NVSHMEM: 스레드 8개 주소 오류 3회 `0x13/0x88` class 3, 스레드 8개 정렬 오류 3회 `0x12/0x8a` class 1, 스레드 64개 주소 오류 2회 `0x13/0x88`·1회 `0x05/0xf9`(그 실행에는 host WARN이 없음: application 조회가 host 스레드의 보고보다 먼저였다 `[추론]`). 스레드 1개와 정상 실행은 전과 같음. 칸 여러 개인 CQ는 시험하지 않음(`ibgda_poll_cq`를 다시 써야 함). NVSHMEM 원본 대비 13개 파일 +228 −10(코드 176줄), 빌드는 sunny만. 로그 `runs/shmemfault-cnt-*` |
| 2026-11-23 | QP context의 원인을 두 라이브러리에 채택(결정 3가지). NVSHMEM: `ibgda_restore_cause` 유지, host `nvshmemx_get_op_error()`가 답하기 전에 같은 보고 함수를 부르게 함(`host_ops.report_op_error`, 보고 함수에 mutex). NCCL: `doca_verbs_qp_query`가 `qpc_ext`로 조회해 `error_syndrome`을 attr에 담고(조회가 거절되면 `qpc_ext` 없이 다시), `doca_gpu_verbs_query_last_error`가 그 값을 syndrome, vendor_err, hw_err, hw_type에 씀(WQE 번호는 전처럼 `cq->err`에서). 양쪽 host 빌드(NVSHMEM은 sunny) 뒤 NVSHMEM 재현 38회, NCCL 재현 54회 × 양방향, NCCL은 gdrcopy 경로를 뺀 실행 3회(sunny가 보냄; rain은 시스템 경로에 gdrcopy가 있어 가려지지 않음) | `[측정]` NVSHMEM: 스레드 8개·64개 29회(주소 오류 26, 정렬 오류 3) 모두 원인이 나옴(`0x13/0x88` class 3, `0x12/0x8a` class 1), flush로 남은 경우 0회. 스레드 1개 6회와 정상 3회는 전과 같음. NCCL 108회: 전과 같은 결과(멈춤 없음, host 조회 90회 모두 `0x13/0x88`, WQE 20 또는 160). gdrcopy 없이 3회: `syndrome=0x13 vendor_err=0x88 wqe_counter=0`(전에는 vendor_err 0이던 구성, WQE 번호만 못 읽음). 성능 A/B는 다시 재지 않음(GPU 쪽 코드 변경 없음). 원본 대비 NCCL 12개 파일 +317 −41(코드 218줄, 주석 85줄), NVSHMEM 14개 파일 +237 −10(코드 184줄, 주석 36줄). 로그 `runs/ginfault-fix8*`, `runs/shmemfault-cnt-*`, `runs/shmemfault-q3-*` |
| 2026-11-23 | 독립 코드 검사 3회. 대상: `cqe_ci` 오류 표시, submit 일반 load, 두 라이브러리의 QP context 원인 조회, NVSHMEM 지난 검사 반영분. 지적 8건반영: (3) NVSHMEM 기록을 남긴 뒤의 fence를 system 범위로(오류 경로만), (4) QPN이 같은 QP가 둘 이상이면 원인을 바꿔 쓰지 않음(기록에 NIC 구분이 없음), (5) NCCL은 `qpc_ext` 조회가 성공했을 때만 확장 영역을 읽음, (7) NVSHMEM 원인 조회를 3번까지 다시 시도, (8) 공개 주석에 필드별 출처(원인은 QP context, WQE 번호는 폴링한 CQE)를 적음. 안 쓰는 alias 삭제. 미반영: (1) collapsed CQ에서 `submit_multi_qps`가 취소한 요청을 그 번호로 기다리면 끝나지 않음, (2) `host_ops`에 멤버를 넣어 transport plugin 배치가 바뀌었는데 plugin 버전은 7 그대로, (6) submit의 일반 load는 다른 스레드의 atomic 쓰기와 섞여 지연 한도가 없음. 재시험: NVSHMEM 재현 28회와 A/B 10회, NCCL 재현 54회 × 양방향. (1)의 재현 시도: counter put + 시간 제한 없는 flush를 collapsed와 기본 CQ에서, release 빌드와 GIN debug 정의(put마다 QP와 companion을 기다림) 빌드로 각 1회 | `[측정]` NVSHMEM 28회: 스레드 여러 개 19회 모두 원인(`0x13/0x88`, `0x12/0x8a`), 나머지는 전과 같음. A/B: `shmem_put_latency` +1.13%, `shmem_p_latency` +2.18%, atomic 6줄 +0.4–1.5%, `shmem_put_bw` −0.41%(편차 안), 첫 atomic 시험의 +37%(17.67 vs 12.86)는 전과 같음. NCCL 108회: 전과 같은 결과. (1) 재현 시도 4회 모두 멈춤 없음: GIN은 companion QP를 취소된 번호로 폴링하지 않는다 `[추론: 소스, gin_gdaki.h의 flush는 주 QP만 폴링, debug의 wait는 sq_wqe_pi까지만]`. DOCA 함수를 직접 쓰는 경우의 결함으로는 남아 있다. 원본 대비 NCCL 12개 파일 +320 −42(코드 220줄), NVSHMEM 14개 파일 +251 −10(코드 192줄). 로그 `runs/ginfault-fix9*`, `runs/ginfault-f1*`, `runs/shmemfault-q4-*`, `runs/shmemfault-cnt-*`, `runs/ab-shmem-20261123-140724` |
| 2026-11-23 | NVSHMEM을 DC QP만 쓰는 구성(`NVSHMEM_IBGDA_NUM_RC_PER_PE=0`)으로 재현. 원인 조회가 RC 목록만 찾던 것을 DCI 목록도 찾게 고침(`ibgda_restore_cause`의 반복을 lambda 하나로). 스레드 1개·8개 각 3회, 고치기 전과 후 | `[측정]` 고치기 전 6회: 오류는 잡히지만 기록이 모두 flush(`0x05/0xf9`, class 4), 스레드 1개에서도 그렇다. 고친 뒤 6회: 모두 `0x13/0x88` class 3. 기본 구성(RC) 스레드 8개 3회는 전과 같음. NVSHMEM 원본 대비 14개 파일 +253 −10(코드 195줄), 빌드는 sunny. 로그 `runs/shmemfault-dci-*`(전), `runs/shmemfault-dci2-*`(후), `runs/shmemfault-rc-*` |
| 2026-11-23 | 3회째 독립 코드 검사의 남은 3건 반영. (1) collapsed CQ의 두 폴링 함수가 `cq_passed`의 실패 표시를 받아, 오류 CQE 없이 실패로 표시된 QP(`submit_multi_qps`가 취소한 경우)에서 `-EIO`로 끝난다. (6) `doca_gpu_dev_verbs_submit`의 실패 QP 확인 6줄 삭제(`qp.cuh`는 원본과 같아짐), `submit_multi_qps`의 확인은 sharing mode의 relaxed load로. (2) NVSHMEM transport plugin 버전 7→8. 양쪽 host NCCL 전체 빌드, sunny NVSHMEM 빌드. NCCL 재현: CQ 방식 3가지 × 양방향 × (정상·시간 제한 없음·시간 제한 각 1회 + counter put의 시간 제한 없음·시간 제한 각 1회 + put 1개·8개·카운터 각 5회) = 120회. NVSHMEM 재현 18회. NCCL A/B 20회 | `[측정]` NCCL 120회: 멈춤 0회, host 조회 90회 모두 `syndrome=0x13 vendor_err=0x88`(WQE 20 또는 160), 시간 제한 flush는 110번 `ncclRemoteError`, 받는 쪽 10칸. NVSHMEM 18회: 전과 같음(스레드 여러 개 9회 모두 원인), `nvshmem_transport_ibgda.so.8`로 실행. A/B us/batch: 구성 1 +0.61%(118.94→119.66, 원본 편차 0.40%), 구성 2 +1.21%(107.55→108.85, 편차 1.88%), 구성 3 +0.10%, 구성 4 +0.13%. submit 확인을 빼기 전은 +5.29% / +1.57%였다. (1)이 고친 경로를 직접 타는 시험은 없다(GIN은 취소된 번호로 companion QP를 기다리지 않는다). 원본 대비 NCCL 11개 파일 +326 −46(코드 229줄, 주석 83줄), NVSHMEM 15개 파일 +254 −11(코드 196줄, 주석 41줄). 로그 `runs/ginfault-fix10*`, `runs/shmemfault-cnt-*`, `runs/ab-gin-20261123-145519` |
| 2026-11-23 | NVSHMEM PE 하나를 죽였을 때 남은 PE가 어떻게 되는지(sunny, mpirun 기본 설정, PE 2개, 장애 주입 없이 25 s 대기 중 12 s에 PE 하나를 `kill -9`), n=1 | `[측정]` mpirun이 "process rank 1 ... exited on signal 9"를 찍고 job을 끝냄. 죽인 뒤 1.3 s 안에 남은 PE도 사라짐, mpirun rc=137. 로그 `runs/shmemkill-*` |
| 2026-11-23 | "연결 쪽 문제" 분류의 재현 수단. `repro/qperr.c`(LD_PRELOAD): 프로세스가 `mlx5dv_devx_obj_create`로 만든 QP를 기억했다가, 첫 QP가 RTS가 된 뒤 정한 시간에 전부 2ERR_QP로 바꾼다. 라이브러리 코드는 바꾸지 않는다(NCCL은 `dlsym`으로 찾으므로 `dlsym`도 감쌈). `run_gin_fault.sh`에 `inject` 갈래 추가(잘못된 put 없음, 시간 제한 flush, host 조회 1 s). NCCL GIN, rain이 보냄, `NCCL_IB_TIMEOUT=14`, 주입 1.5 s 뒤: (가) 보내는 rank의 QP, (나) 받는 rank의 QP. CQ 방식 3가지 × 각 5회(put 1개), CQ 방식 0·1 × 각 5회(put 8개), 그 전 확인 2회 | `[측정]` 62회 모두 멈춤 0회, 120번 모두 반환. (가) 31회: host WARN `syndrome=0x5 vendor_err=0xf5`. (나) 31회: `syndrome=0x15 vendor_err=0x81`. 기록된 WQE 번호가 받는 쪽에 도착한 칸 수와 맞음: put 1개 30회는 모두 도착 47칸에 WQE 94(put당 WQE 2개), put 8개 20회는 도착 46–47칸에 WQE 736–752(칸당 WQE 16개). 즉 이 구성(스레드 1개, flush마다 대기)에서는 실패 경계가 기록에서 읽힌다. 여러 요청이 떠 있는 중간에 끊긴 경우의 경계는 이 시험으로는 알 수 없다(받는 쪽 확인이 flush 단위). NVSHMEM은 아직 안 돌림(`shmem_fault`에 반복 사이 지연이 없음). 로그 `runs/ginfault-inj*` |
| 2026-11-23 | 세 분류의 재현과 "어디까지 끝났나" 측정. (가) NVSHMEM에 `qperr.c` 주입(`shmem_fault`에 반복 사이 지연 `DELAY_CYCLES` 추가, N=200, RTS 4 s 뒤 주입, 보내는 PE·받는 PE × 스레드 1·8개 × 5회). (나) NCCL 전송 도중 주입(`run_gin_fault.sh`의 `stream` 갈래: 1 KiB put 30000개를 flush 없이 보내고 끝에서 한 번 flush, RTS 0.6 s 뒤 주입, 받는 쪽이 도착 칸 수와 signal 값을 보고, `LINGER_MS`로 host 조회를 이어 감; CQ 방식 3가지 × 양쪽 × 5회, 일부 2묶음). (다) NCCL에서 받는 프로세스를 `kill -9`(mpirun `--enable-recovery`, 3회, 죽이기 전후 rank 0의 TCP 소켓 상태를 `ss`로 봄). (라) NIC 수준: `synd.c`에 QP context의 `last_acked_psn`, `next_send_psn`, `next_rcv_psn`, SQ counter 출력과 write 8개를 한꺼번에 올리는 경우 3가지 추가, 두 host 각 3회 | `[측정]` (가) 스레드 1개 10회: 보내는 PE 주입은 `0x05/0xf5` class 2, 받는 PE 주입은 `0x15/0x81` class 3, 커널이 멈춘 반복 = 도착 칸 수 = quiet 반환 수(42 또는 43), 멈춤 0회. 스레드 8개: 받는 PE 주입 5회는 `0x15/0x81` class 3. 보내는 PE 주입 5회는 `0x05/0xf9` class 4였다: `ibgda_restore_cause`가 QP context의 `0x05/0xf5`를 flush라고 버렸기 때문. 조건을 고친 뒤 5회 모두 `0x05/0xf5` class 2(NVSHMEM 커밋 `3f5eeed6`). 초기화가 끝나기 전(RTS 0.8 s 뒤)에 주입하면 mpirun 60 s 제한까지 출력 없이 멈춤(4개 구성 중 본 2개 구성 10회 모두; 초기화 중 장애는 범위 밖). (나) 40회 모두 멈춤 0회, 받는 쪽 signal 값 = 도착 칸 수, 첫 누락 뒤에 도착한 칸 0개. 기록된 WQE 번호 ÷ 2와 도착 칸 수의 차: 기본 CQ 10회 0, host가 폴링하는 collapsed 10회 0, GPU가 폴링하는 collapsed에서 받는 쪽 주입 5회 0, 보내는 쪽 주입 10회 중 8회가 18–36(기록이 실제보다 뒤). 받는 쪽 주입의 첫 묶음 10회는 host 조회가 돌기 전에 끝나 WARN이 없었다. (다) 3회 모두 rank 0은 살아남고 `0x15/0x81`(WQE 112–116), 120번 모두 반환, 멈춤 0회. rank 0의 소켓은 죽이기 전 ESTAB 13개, 1 s 뒤 CLOSE-WAIT 9개와 ESTAB 3개(어느 것이 NCCL bootstrap 소켓인지는 가리지 않음). 오류 CQE는 재시도 초과 뒤(`ASYNC t≈6.0 s`)에 왔다. (라) 두 host 3회씩 같음: 8개 모두 성공이면 요청 쪽 `acked_psn=7 next_psn=8`, 응답 쪽 `rcv_psn=8`. 4번째가 잘못된 rkey면 요청 쪽 `acked_psn=2 next_psn=3`, 응답 쪽 `rcv_psn=3`(3개 실행). 응답 쪽 QP가 먼저 ERR면 요청 쪽 `acked_psn=0xffffff next_psn=8`, 응답 쪽 `rcv_psn=0`. SQ counter(`hw_sq_wqebb_counter`)는 flush된 것까지 세어 8로 같다. 로그 `runs/shmemfault-inj2-*`, `-inj3-*`, `runs/ginfault-strm*`, `runs/ginkill-*`, `runs/synd-burst-*` |
| 2026-11-23 | NVSHMEM에서 NIC 순번(PSN) 읽기. host의 오류 보고가 이미 하는 QUERY_QP 응답에서 `last_acked_psn`과 `next_send_psn`을 같이 읽어 WARN에 `acked_psn`, `next_psn`으로 찍게 함(`ibgda_restore_cause`가 값을 돌려줌; 보고 때 조회 1회, 기록이 뒤따른 flush일 때만 추가 조회). 작업 트리에만 있고 커밋하지 않음(남길지 미정). sunny, 6개 구성 × 3회: 잘못된 주소(스레드 1·8개), 보내는 PE QP 주입(1·8개), 받는 PE QP 주입(1·8개) | `[측정]` 18회 모두 값이 읽힘. 잘못된 주소·스레드 1개: 10번 성공 뒤 실패, `acked_psn=11 next_psn=12`, `wqe_counter=16`. 보내는 PE 주입·스레드 1개: 도착 44칸, `acked_psn=45 next_psn=46`. 받는 PE 주입·스레드 1개: 도착 44칸, `acked_psn=45 next_psn=47`(보냈지만 확인 못 받은 packet 1개). 스레드 8개: 보내는 PE 주입 `acked 93–97, next = acked+1`, 받는 PE 주입 `acked 97, next 99`. 즉 `next_psn − acked_psn − 1`은 요청이 틀린 경우와 로컬 QP 오류에서 0, 상대에 닿지 않는 경우에서 1이었다. PSN은 그 QP에서 끝난 packet 수이고 WQE 번호와 다르다(`wqe_counter` 16 대 PSN 12): RC QP가 PE당 2개이고 요청이 번갈아 실리며, WQE 하나가 packet 하나가 아니다. 요청 번호로 바꾸려면 QP별로 "올린 packet 수"를 세는 값이 필요하다 `[추론]`. 로그 `runs/shmemfault-psn-*` |
| 2026-11-23 | 오류 기록의 WQE 번호를 "안전한 하한"으로 바꿈(결정: 정확한 번호는 필요 없고 QP별 하한이면 된다). NVSHMEM: `ibgda_latch_err_cqe`가 오류 CQE의 counter 대신 첫 오류를 보기 전에 읽은 `cons_idx`를 기록(커밋 `20ba0c88`, WARN의 `acked_psn`·`next_psn` 포함). NCCL collapsed CQ: `set_err_collapsed`가 실패 뒤 멈추는 `cqe_ci`를 기록하고 flush 기록 특수 처리를 없앰(커밋 `6c1d69b`, +13 −11). 양쪽 host 전체 빌드. 검증: NVSHMEM 회귀 18회, NVSHMEM 전송 도중 주입(`STREAM=1`, RC QP 1개, put 20000개, 보내는 PE·받는 PE 각 5회), NVSHMEM 주입 스레드 8개 6회, NCCL 재현 120회(양방향), NCCL 전송 도중 주입 40회(기본 CQ·collapsed 두 방식, 각 10회), A/B NCCL 20회·NVSHMEM 10회 | `[측정]` NCCL 전송 도중 주입, 기록된 put 번호 − 도착 칸 수: 기본 CQ 10회 모두 0, GPU가 폴링하는 collapsed에서 보내는 쪽 주입 10회는 −43에서 0(고치기 전 +18에서 +36), 받는 쪽 주입 10회 모두 0, host가 폴링하는 collapsed 10회는 −1에서 0. 40회 모두 0 이하, 멈춤 0회. NVSHMEM 전송 도중 주입: 스레드 1개 일반 실행에서 put 10개 뒤 기록이 16이므로 이 QP의 WQE 번호는 put 수보다 6 크다고 보고 비교 `[추론]`. 보내는 PE 주입 5회는 기록 10243에 도착 10361–10408칸(기록 − 6이 118–165 아래), 받는 PE 주입 5회는 기록이 도착 + 6으로 정확. 10회 모두 하한이 도착분 이하. NVSHMEM 회귀와 주입: 분류는 전과 같고 스레드 여러 개의 `wqe_counter`가 작아짐(59→56, 361→330). NCCL 120회: 멈춤 0회, host 조회 90회 모두 `0x13/0x88`, collapsed(GPU 폴링)의 WQE 번호가 20→19, 160→159로 하나 작게 나옴(하한이라 허용, 마지막 WQE는 signal atomic). A/B NCCL us/batch: +0.66%, +1.06%, +0.39%, +0.02%. A/B NVSHMEM: put 지연 +1.08%, p 지연 +1.74%, 대역폭 −0.58%(편차 안), atomic 6줄 +0.7–1.8%. 원본 대비 NCCL 11개 파일 +328 −46(코드 230줄), NVSHMEM 15개 파일 +271 −11(코드 203줄). 로그 `runs/ginfault-fix11*`, `runs/ginfault-lbstrm-*`, `runs/shmemfault-lb-*`, `runs/shmemfault-cnt-*`, `runs/ab-gin-20261123-181044`, `runs/ab-shmem-*`(마지막) |
| 2026-11-23 | NCCL host 오류 조회의 비용. `gin_fault`가 `ncclCommGetAsyncError` 호출마다 시간을 재어 50 us를 넘긴 호출 수를 `ASYNCQ` 줄로 출력하게 함. 장애 없이 300회 반복(약 9.3 s), 호출 약 8800번, 조회 간격 1 s와 10 s 각 3회, rain이 보냄 | `[측정]` 6회 모두 50 us를 넘긴 호출 0번. 간격 1 s에서도 조회가 도는 호출(실행당 약 9번)이 50 us 안에 끝났다. 이 장비는 completion channel 이벤트 방식으로 조회한다 `[추론: 소스 gin_host_gdaki.cc:935의 polling 대체 문구가 INFO 로그에 없음]`. 이벤트 방식을 못 쓰는 장비의 polling 방식(QP마다 QUERY_QP, 소스 주석으로 약 250 us)은 재지 못했다. 로그 `runs/ginfault-q1-2026*`, `runs/ginfault-q10-2026*` |
| 2026-11-23 | 기본 동작 두 가지 변경. NCCL: `NCCL_GIN_ERROR_QUERY_SEC` 기본값 10 → 1(커밋 `a8c97b7`), 시험 스크립트에서 간격 지정을 지움. NVSHMEM: 실패가 기록되면 host가 원인을 찍고 프로세스를 끝냄, `NVSHMEM_IBGDA_ABORT_ON_OP_ERROR=0`이면 전처럼 계속 실행(커밋 `efad32f5`; 2026-11-20의 "중단 대신 조회" 결정을 "기본은 중단, 조회는 선택"으로 바꿈). `shmem_fault.sh`는 조회 방식으로 돌고 `ABORT=1`로 기본 동작을 켠다. 검증: NVSHMEM 조회 방식 회귀 12회, 기본 동작으로 6개 구성 × 3회(정상, 잘못된 주소 스레드 1·8개, 정렬 오류, 보내는 PE QP 주입, 받는 PE QP 주입), NCCL 재현 120회(간격 지정 없음) | `[측정]` NVSHMEM 기본 동작: 장애를 넣은 15회 모두 WARN과 "Aborting after the IBGDA error above" 문구가 찍히고 mpirun 제한 시간 전에 끝남(3.5–9.4 s; 정상 실행 3.45 s, 받는 PE 주입은 재시도 초과 대기 포함), 정상 3회는 끝까지 돌아 SUMMARY 출력. mpirun rc는 정상 실행도 1이라(시험 프로그램이 finalize 없이 끝남) rc로는 구분되지 않는다. 조회 방식 회귀는 전과 같음. NCCL 120회: 간격을 주지 않아도 host 조회 90회 모두 `0x13/0x88` WARN, 멈춤 0회. 원본 대비 NCCL 11개 파일 +329 −47(코드 231줄), NVSHMEM 16개 파일 +285 −11(코드 214줄). 로그 `runs/shmemabort-*`, `runs/ginfault-fix12*`, `runs/shmemfault-cnt-*` |
