# rdma-recovery: NCCL와 NVSHMEM 오류 복구

이 폴더의 단일 기록이다. `~/rdma-error`의 실험 문서와 따로 관리하고, 그쪽 문서에는 덧붙이지 않는다.
기존 복구 패치와 설계 문서는 참고하지 않고 원본 소스에서 새로 만든다.
현재 유효한 것만 적는다. 폐기된 결정과 지나간 경위는 남기지 않고 지운다.

표시: `[측정]` 원자료나 코드에서 직접 확인, `[추론]` 해석, `[미확인]` 확인 안 함.

| 항목 | 값 |
|---|---|
| 상태 | `RUNNING` |
| 작성일 | 2026-11-19 |
| 마지막 갱신 | 2026-11-25, 죽음 판정(`rp_cnp_handled` + 소켓), 커밋 정리, 되돌린 구현의 기록을 줄임 |

## 1. 목표 (결정, 2026-11-19)

- 대상은 NCCL과 NVSHMEM의 오류 복구다.
- 먼저 직접 보고한 이슈 네 건을 고친다. 오류가 보이지 않으면 복구가 판정할 것이 없다.
- 그다음 4절의 분류에서 복구할 수 있는 것 전부를 복구한다.
- 판정에는 CQE의 syndrome과 vendor_err, 포트 카운터 `rp_cnp_handled`, 그리고 TCP 소켓의 열림/닫힘을 쓴다.
- 생사 확인에 새 소켓을 만들지 않는다(결정, 2026-11-23). 이미 열려 있는
  소켓으로 볼 수 있는 경우만 본다. 볼 수 없는 경우는 생사를 "모름"으로 두고 규칙의 기본값으로 간다.
  - NCCL 일반 IB 경로: 연결마다 열려 있는 TCP 소켓 `[측정: 소스, net_ib/common.h:386, :654]`.
  - NCCL GIN: GIN `collComm`이 양옆 이웃(rank±1)과 열어 둔 소켓(`sendComm`, `recvComm`; 연결 뒤에는 아무도 읽고 쓰지 않음)
    `[측정: 소스]`. 이웃이 아닌 상대(rank 4개 이상)는 볼 수 없다. 판정은 4.2절.
  - NVSHMEM: 상대 PE로 가는 소켓이 없다(6절 2026-11-20). mpirun으로 띄우면 PE 하나가 죽을 때 mpirun이 job 전체를 끝낸다
    `[측정: 6절 2026-11-23, n=1]`. 그래서 살아남아 오류를 보는 PE에게 상대는 죽지 않은 것으로 본다.
  - 소켓은 열림/닫힘만 읽는다.

## 2. 소스

| 무엇 | 경로 | 버전 | 확인 |
|---|---|---|---|
| NCCL | `nccl/` | v2.32.6-1, `ad2d192` (최신 release, 2026-11-09) | `[측정]` `git log -1`, `makefiles/version.mk` |
| NVSHMEM | `nvshmem/` | v3.8.0-0, `270759e5` (최신 release) | `[측정]` `git log -1` |

- 둘 다 release에서 시작한다. upstream이 이미 고친 것도 이 폴더의 코드에 직접 반영한다.
- 두 저장소 모두 로컬 브랜치 `recovery`에서 작업하고, 이슈 하나가 해결될 때마다 커밋한다. NCCL 6개(`cf1e2ec` #2480, `3c0f8bd` #2483,
  `0fd4724` collapsed CQ 하한, `3116a5e` host 스레드, `da35e25` shrink, `d56b15e` 죽음 판정; 2026-11-25에 정리, 6절), NVSHMEM 6개(`26eb3006` #117, `d0f3ee2a` #120, `3f5eeed6`, `20ba0c88`, `efad32f5`, `71856a5e`).
  공개 저장소 `rdma-fault-characterization`의 `v2/`에 라이브러리별 diff 하나로 올린다(`publish.sh`). 마지막 반영은 2026-11-25(위 커밋 전부).
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
| nvshmem #120 | release 빌드가 오류 CQE를 읽고 버린다. `nvshmem_quiet()`가 정상 반환하고 fetch가 틀린 값을 돌려준다 | OPEN, 10-15 이후 답 없음 | 고침(2026-11-20 실행 기록). device가 첫 오류 CQE를 host 메모리에 남기고 host가 WARN 한 줄로 알린다. application은 `nvshmemx_get_op_error()`(host와 GPU 커널 양쪽)로 오류와 분류(요청 문제 / 로컬 QP / 상대 쪽 / 모름)를 물을 수 있다. 기록이 없는 구성(IBGDA가 아닌 transport)에서는 `NVSHMEMX_ERROR_NOT_SUPPORTED`를 돌려준다. 기본 동작은 원인을 찍고 중단이고, `NVSHMEM_IBGDA_ABORT_ON_OP_ERROR=0`이면 계속 돌며 조회에 답한다. 남은 것: 기록 칸이 프로세스에 하나뿐이고 지우는 길이 없음; 오류 뒤에도 송신 큐 칸이 재사용됨; 기록에 상대 PE·주소·길이·key가 없음. 복구 단계에서 다룸 |
| nccl #2483 | GIN GDAKI에서 실패한 put을 device 코드가 알 수 없고, host는 10 s 조회에서 한 번만 본다 | OPEN, 답 없음 | 고침(수정 1–5, 아래 실행 기록, 독립 코드 검사 1회 반영). 양방향(sunny가 보냄, rain이 보냄) 각 54회 확인. host 조회 간격 기본 1 s, 원인은 QP context에서 읽음. host 스레드가 application이 묻지 않아도 오류를 보고함(4.3절). 남은 것: gdrcopy가 없으면 host가 하한(WQE 번호)을 못 읽음; void인 flush·wait는 오류를 못 돌려줌; 오류 뒤에도 put이 SQ 칸을 계속 예약해 덮어씀(4.3절); CPU proxy 방식의 요청 중단은 빌드만 됨 |
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

| syndrome | 뜻 | 재현 | 넣은 장애 → vendor_err | 라이브러리 |
|---|---|---|---|---|
| 0x01 | 로컬 길이 | 응답 쪽 | 수신 버퍼 작음 → 0xd7 | 해당 없음(수신 없음) |
| 0x02 | 로컬 QP 동작 | 함 | WQE 형식 오류 → 0x68 | 남김(라이브러리 결함일 때) |
| 0x04 | 로컬 보호 | 함 | 잘못된 lkey 0x52, SGE가 MR을 넘음 0x53, 쓰기 권한 없는 MR로 READ 0x33 | 남김 |
| 0x05 | flush | 함 | 로컬에서 ERR로 바꾼 QP에 post 0xf5, 앞선 오류 뒤의 요청 0xf9 | 남김. 0xf9는 원인이 아니다 |
| 0x06 | memory window | 못 함 | bind 4가지 중 3가지는 성공으로 끝나고 1가지는 `ibv_bind_mw`가 거절 | 해당 없음(MW 안 씀) |
| 0x10 | 잘못된 응답 | 시도 못 함 | 규격에 어긋난 응답을 보낼 수단이 없음 | 기본값 |
| 0x11 | 로컬 접근 | 응답 쪽 | 즉시값 딸린 write의 잘못된 rkey → 0xc2 | 해당 없음(즉시값 안 씀) |
| 0x12 | 원격 잘못된 요청 | 함 | QP에 쓰기 권한 없음, 정렬 안 된 atomic, 응답 쪽 READ 한도 0, 수신 버퍼 작음 → 모두 0x8a | 남김 |
| 0x13 | 원격 접근 | 함 | 잘못된 rkey, 범위 밖, 권한 없는 MR → 모두 0x88 | 남김 |
| 0x14 | 원격 동작 | 함 | 응답 쪽 수신 버퍼의 lkey·권한 오류 → 0x89 | 해당 없음(수신 없음) |
| 0x15 | 재시도 초과 | 함 | 상대 QP 파괴, ERR, RESET → 모두 0x81 | 남김 |
| 0x16 | RNR | 함 | 수신 WQE 없음 → 0x87 | 해당 없음(수신 없음) |
| 0x22 | 원격 중단 | 시도 못 함 | 정의상 UD/UC와 SRQ의 오류, 넣을 방법을 못 찾음 | 기본값 |

- 라이브러리에 남는 코드는 6개다: 0x02, 0x04, 0x05, 0x12, 0x13, 0x15.
- 같은 코드로 묶이는 원인이 있다(0x13 세 가지, 0x12 네 가지, 0x15 세 가지). 0x13과 0x15에서 상대가 살아 있는지는
  소켓으로 가른다.
- **원인을 읽는 곳.** NIC는 QP마다 첫 오류를 QP context에 보관하고(QUERY_QP `qpc_ext`,
  `qp_context_extension.error_syndrome`), 뒤따른 flush가 그것을 지우지 않는다 `[측정: 6절 2026-11-23]`. CQE가
  flush로 덮여도 host는 이 값으로 원인을 읽는다. 두 라이브러리 모두 이 값을 쓴다.
- 한계: 소프트웨어로 넣은 장애이고 물리 장애(케이블, 펌웨어 결함)가 아니다. vendor_err는 드라이버 헤더에 정의가
  없어 측정값이며 ConnectX-6(MT4123) 펌웨어 20.43.4100 한 가지에서 쟀다. 재현은 한 프로세스 안 loopback RC QP다.
  상대 프로세스 죽음은 이 시험에 없다.

## 4.1 복구 규칙 (결정, 2026-11-23: 질문 1을 가볍게 두는 조건으로 진행)

원인마다 처리를 따로 두지 않고, 질문 세 개를 순서대로 물어 정한다(결정, 2026-11-23: 경우별 처리보다 보편
규칙). 규칙의 틀은 결정됐고, 아래 처리 내용은 `[추론]`이며 복구를 실행해 확인한 것은 없다. 근거는 2026-11-19의 소스 판독 둘(NCCL 2.32.6, NVSHMEM
3.8.0)과 논문·기존 라이브러리 조사, 그리고 4절의 측정이다.

| 순서 | 질문 | 무엇으로 아는가 | 답에 따른 처리 |
|---|---|---|---|
| 1 | 같은 요청을 다시 보내면 또 실패하는가 | syndrome과 vendor_err(4절)의 표 조회만. 상대에게 묻지 않는다(무거워지지 않게, 결정) | 그렇다: 그 요청만 실패시키고 원인을 최대한 특정해 알린다 |
| 2 | 상대가 살아 있는가 | NCCL GIN: `rp_cnp_handled`가 오르고, 이웃 소켓이 닫혔고, 그 rank로 보낸 요청이 떠 있으면 죽음(4.2절). 볼 수 없으면 "모름" | 죽었다: 실패. NCCL은 예비 프로세스로 교체(4.2절), NVSHMEM은 그 PE로 가는 QP를 막는다 |
| 3 | 끝나지 않은 요청을 다시 보내도 안전한가 | 요청 종류. write와 read는 안전, atomic은 실행 여부를 알아야 한다(미결정 사항) | 안전하다: QP를 다시 세우고 미완료분만 재전송(횟수 한도는 4.3절). 아니다: 실패 |

4절에서 라이브러리에 남긴 코드가 이 규칙에서 가는 곳:

| syndrome / vendor_err | 질문 1 | 처리 |
|---|---|---|
| 0x04 로컬 보호 (0x52, 0x53, 0x33) | 그렇다 | 그 요청만 실패. QP는 다시 세워 뒤따르던 정상 요청을 살린다(결정, 아래) |
| 0x02 로컬 QP 동작 (0x68) | 그렇다(WQE 형식이 틀림, 라이브러리 결함) | 그 요청만 실패. 지금 NVSHMEM 코드는 이 코드를 "모름"으로 분류한다 |
| 0x12 원격 잘못된 요청 (0x8a) | 그렇다 | 그 요청만 실패. 넣어 본 네 가지 장애가 모두 요청이나 QP 설정의 문제였다 `[측정: 4절]` |
| 0x13 원격 접근 (0x88) | 그렇다(표 조회). 단 상대가 죽어도 이 코드가 나오므로 질문 2를 먼저 본다 | 상대가 죽었으면 상대 죽음으로 알림. 아니면 그 요청만 실패. 낡은 rkey를 되살리는 복구는 하지 않는다 |
| 0x15 재시도 초과 (0x81) | 아니다 | 질문 2, 3으로. 살아 있으면 QP 쌍을 다시 세우고 하한 뒤의 요청을 재전송(4.3절) |
| 0x05 / 0xf5 로컬 QP가 오류 상태 | 아니다 | 질문 2, 3으로. QP 쌍을 다시 세우고 미완료분만 재전송 |
| 0x05 / 0xf9 뒤따른 flush | 원인이 아니다 | QP context에서 원인을 읽어 위 줄 중 하나로 간다. 못 읽으면 기본값 |
| CQE가 오지 않음 | 알 수 없다 | 질문 2로. 소켓이 닫혔으면 상대 죽음 |
| 그 밖(해당 없음으로 뺀 코드, 처음 보는 코드) | 알 수 없다 | 기본값: 원인을 붙여 바로 실패 |

- RNR(0x16): 두 라이브러리 모두 수신 큐가 없어 해당 없음이다. NCCL 일반 IB 경로의 원본 설정(rnr_retry 7)에서는
  오류가 아니라 정지로 나타난다 `[측정: connect.cc:545]`.
- `0x13`과 `0x15`는 상대가 죽어도 나온다. 그래서 질문 2를 항상 거친다.

결정된 것 (2026-11-19):

- 복구 조정은 RDMA만 쓴다. TCP 소켓은 열림/닫힘만 읽는다(2026-11-24 재확인: 조정 메시지에 TCP를 쓰면 production에서 못 쓴다).
  깨진 QP로는 상대에게 알릴 수 없다. 상대마다 RC QP 하나를 두는 통로는 구현했다가 비싸다는 판단으로 철회했다
  (결정, 2026-11-24; 비용은 재지 않음). **양쪽이 어떻게 합의할지는 정해지지 않았다.**
- `0x04`는 재시도하지 않는다. vendor_err로 요청 문제임이 구분되므로 원인을 붙여 바로 실패시킨다.
- `0x04` 뒤에는 QP를 다시 세워 뒤따르던 정상 요청을 살린다. 틀린 요청만 실패로 돌려주고 그 기록을 로그로 내보낸다.
  로그는 라이브러리의 기존 로그 출력에 한 줄 key=value로 남긴다: status, vendor_err, 상대 rank, QP 번호, 요청의 주소와
  길이와 key, 시각. 수집기는 후속 작업이다. 출력 지점에 "수집기가 생기면 여기서 보낸다"는 주석을 둔다.
- 오류를 알리는 방식: 자동 복구가 되는 것은 자동 복구한다. 안 되는 것은 세분화한 원인을 로그로 알린다. NVSHMEM은
  기본으로 원인을 찍고 중단하며, `NVSHMEM_IBGDA_ABORT_ON_OP_ERROR=0`을 준 application만 `nvshmemx_get_op_error()`로
  묻는다(결정 2026-11-23).
- vendor_err는 NIC 펌웨어가 오류 CQE에 써 넣는 값이다. `mlx5dv.h`는 syndrome 값에는 이름을 붙였지만 vendor_err 값은
  `ODP_PFAULT = 0x93` 하나만 정의한다 `[측정: rain /usr/include/infiniband/mlx5dv.h]`. 우리가 쓰는 값의 뜻은 측정으로
  정한 것이고, 잰 장비는 rain과 sunny 모두 ConnectX-6(MT4123), 펌웨어 20.43.4100이다 `[측정: ibv_devinfo, 2026-11-21]`.
- 코드양 관리(결정, 2026-11-21): 수정할 때마다 리팩토링하고, 수정 전후 길이 차이와 중복 함수·통합 가능 여부를
  본다.
- 로그 문구는 영어로, 각 라이브러리의 기존 양식을 따른다(NCCL은 `WARN` 매크로 양식, NVSHMEM은 그쪽 로그 매크로).
- NVSHMEM은 sunny에서만 돌린다. rain은 GPU BAR1이 256 MiB라 등록이 실패한다. sunny의 GPU 한 장에 PE 둘을 올리고
  `NVSHMEM_DISABLE_P2P=1`로 NIC를 거치게 한다(`shmem_sunny.sh`).

미결정 사항:

- **중복과 손실 방지의 근거.** atomic(GIN signal, NVSHMEM signal과 AMO)은 재전송하면 두 번 실행된다. 두 판독 모두
  "상대 QP의 수신 순번을 QUERY_QP로 읽는다"에 기댄다. 오류 상태 QP에서 그 값이 정확한지는 `[미확인]`이고, 틀리면
  atomic이 걸린 복구는 거부로 내려간다.
- **재무장 PSN.** NCCL 판독은 새 PSN, NVSHMEM 판독은 양쪽 0을 냈다.
- **`0x02`와 `0x16`의 코드 분류.** NVSHMEM 코드는 `0x02`를 "모름", `0x16`을 "상대 쪽"으로 둔다. 표와 맞출지 정하지 않았다.
- **이웃이 아닌 rank의 죽음과 보내는 rank의 죽음.** 지금 판정은 죽은 rank에게 보내던 이웃만 안다. 결정(2026-11-24): 지금은 다루지 않고, 전체를 구성한 뒤 다시 본다.

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
- 있는 API: `ncclCommRevoke`, `ncclCommShrink`, `ncclCommGrow` `[측정: nccl.h.in:327, 345, 362]`. shrink와 grow는 돌려 봤다(아래). revoke는 `[미확인]`.

가정이 성립하는 범위 (2026-11-19 웹 조사, 문서 수준):

| 학습 방식 | rank의 상태 | 가정 |
|---|---|---|
| DDP (rank마다 모델 전체) | 전부 같다 | 성립 |
| Megatron식 TP × PP × DP, DP ≥ 2 | 다른 DP 묶음의 같은 자리 rank와 같다 | 성립 `[추론]`. optimizer 상태를 DP 방향으로 나누는 옵션을 켜면 깨진다 `[미확인]` |
| FSDP, ZeRO-3 | rank마다 다른 조각 | 불성립 |
| DP = 1 | 복제본 없음 | 불성립 |

확인된 것(2026-11-23, rank 4개, 6절 "rank 죽음과 shrink"):

- 통신 쪽의 절반은 된다. rank 하나를 죽인 뒤 남은 셋이 `ncclCommShrink(NCCL_SHRINK_ABORT)`로 12–29 ms 만에 다시 묶이고, 새
  communicator에서 GIN 전송이 정상이다 `[측정]`.
- 원본 NCCL은 상대의 죽음을 스스로 알지 못한다. 죽은 지 1 s 뒤에도 `ncclCommGetAsyncError`는 "오류 없음"이고, NIC의 오류
  (`0x15/0x81`)는 약 56–60 s 뒤에 온다 `[측정, n=2]`. 죽은 상대에게 보내던 시간 제한 없는 flush는 그때까지 멈춰 있다 `[측정, n=5]`.
- **죽음 판정**(커밋 `d56b15e`, 6절 2026-11-24): host 오류 스레드가 조회 간격(기본 1 s)마다 포트의 `rp_cnp_handled`를 읽는다. 올랐고,
  ring 이웃의 소켓이 닫혔고, 그 rank로 보낸 요청이 떠 있으면 죽음으로 보고 그 rank로 가는 QP만 ERR로 바꾼다. 소켓으로 보내는 것은
  없다. 보내던 rank만 알게 된다(그것으로 충분하다는 결정). 죽은 뒤 약 0.5 s에 판정되고 멈추던 flush가 풀린다 `[측정, n=5]`.
  카운터의 근거: 사라진 QP로 가는 재전송마다 보내는 쪽 포트에서 +1, 첫 상승은 죽은 뒤 0–20 ms `[측정]`. 상대가 살아 있고 QP만
  실패해도 오르므로 소켓과 함께 본다.
- "보낸 요청이 떠 있는가"는 NIC에게 묻는다(2026-11-25): 그 rank로 가는 QP를 QUERY_QP로 조회해 `next_send_psn`과 `last_acked_psn`의 차이
  (ACK를 못 받은 PSN 수)를 본다. 이미 실패한 QP는 세지 않는다. 우리 쪽 번호(`sq_rsvd_index > cqe_ci`)로 보던 때는 counter로 기다리는
  application에서 일이 끝나도 참이어서, 이웃의 정상 종료 뒤 다른 이유로 카운터가 오르면 오판했다(3회 중 3회 → 고친 뒤 0회, 6절).
  조회는 카운터가 오르고 소켓이 닫힌 때에만 한다. GDRCopy가 필요 없다.
- 남은 한계: counter로 기다리는 GPU 대기는 죽음 판정으로 풀리지 않는다(counter 값만 봄; 자기 제한 시간으로만 끝남) `[측정]`. 받기만 하는
  rank는 보낸 것이 없어 판정하지 못한다. 조회 한 번의 순간값이라 정상 종료 중 ACK가 아직 오는 중이면 틀릴 수 있다 `[추론]`.
- NCCL은 비동기 오류가 있는 communicator의 shrink를 거절한다 `[측정: 소스 init.cc]`. `NCCL_SHRINK_ABORT`를 준 shrink는
  `ncclRemoteError`가 있어도 받게 고쳤다(커밋 `da35e25`): 남은 rank가 12–18 ms에 다시 묶이고 새 communicator에서 GIN 전송이 정상 `[측정]`.
- shrink 뒤 `ncclCommGrow`로 새 프로세스를 넣는 것도 된다(328–335 ms) `[측정, 6절 2026-11-24]`. 다만 번호가 당겨지고 device 핸들을
  application이 다시 만들어야 한다. 그래서 방향은 제자리 교체다(4.3절).
- `[미확인]`: 보내는 rank가 죽는 경우, 이웃이 아닌 rank의 죽음, 장비 전원이 꺼지는 경우(소켓이 닫히지 않음), application 상태 복사.

## 4.3 복구 설계 (진행 중, 2026-11-23)

대상: NCCL GIN GDAKI의 기본 CQ부터. 복구 동작은 하나이고, 4.1절의 판정이 넘겨준 정보(원인 분류, 상대 생사, 하한과 떠 있던
요청)에 따라 재전송 목록만 달라진다(방향).

| 판정 결과 | 처리 |
|---|---|
| 요청 문제 + 상대 생존 | QP 쌍을 다시 세우고, 틀린 요청 하나만 빼고 재전송 |
| 연결 문제 + 상대 생존 | QP 쌍을 다시 세우고, 하한 뒤의 요청을 재전송(상대가 이미 실행한 것은 제외) |
| 상대 죽음 | 교체할 수 있으면 죽은 rank를 새 프로세스로 교체(4.2절), 아니면 원인을 붙여 실패로 알림(결정 2026-11-23: 안 되는 것은 하지 않되 되는 것은 복구) |
| 모름 | 원인을 붙여 실패로 알림 |

결정된 것(2026-11-23):

- 복구는 gdrcopy가 있을 때만 켠다. 없으면 오류로 멈추지 않고, 복구 없이 원인만 알리는 방식으로 자동 전환하고 로그에 한 줄
  남긴다(GDS compat mode와 같은 방식).
- 복구 횟수 한도는 지금 정하지 않는다. 설정값으로 두고, 복구 1회 비용을 잰 뒤 "일정 시간 안에 몇 번"으로 정한다.

확인된 사실:

- QP 쌍은 양쪽을 RESET으로 내렸다 올리면 다시 쓸 수 있다. NIC의 SQ 번호와 PSN이 0에서 다시 시작하고 QP context의 오류
  기록이 지워진다. 약 1.5 ms `[측정: 6절 2026-11-23 reset_reuse]`. 그래서 판정에 쓸 정보는 초기화 전에 읽어야 하고, 우리 쪽
  번호(티켓)와 NIC 번호를 다시 맞춰야 한다.
- 실패 뒤에도 put은 계속 올라가 SQ(기본 128칸)를 한 바퀴 돌면 끝나지 않은 요청을 덮어쓴다
  `[측정: 소스, dev_verbs_qp.cuh의 wait_until_slot_available이 poll 결과를 버림]`.
- GDAKI에는 실행 중에 양쪽이 말을 주고받는 통로가 없다(QP 정보는 초기화 때 한 번 교환) `[측정: 소스]`.
- QP 쌍은 양방향 공용이라 한쪽을 초기화하면 상대의 요청도 끊긴다. 양쪽이 같은 절차를 밟아야 한다 `[추론: 소스]`.
- host는 gdrcopy로 QP 구조체만 매핑한다. SQ 버퍼(GPU 메모리)는 매핑하지 않는다 `[측정: 소스, doca_gpunetio.cpp:1283–1313]`.
- 원본 GDAKI(GPU가 doorbell을 울리는 방식)에는 host 스레드가 없다. host 오류 조회는 application이 `ncclCommGetAsyncError`를
  부를 때만 돈다. NCCL의 GIN progress 스레드는 CPU proxy 방식에서만 뜨고 yield를 넣은 무한 반복이다 `[측정: 소스,
  gin_host.cc:57–88, :466–487, init.cc:4086–4099]`.
- GPU 커널만으로는 복구할 수 없다. QP를 RESET으로 내리고 다시 올리는 것은 host가 드라이버를 거쳐 NIC에 내는 명령이다
  `[추론: 소스, doca_verbs_qp.cpp의 modify가 devx 명령]`. 감지는 GPU 스레드가 이미 한다.
- host 스레드(결정, 2026-11-23, 커밋 `3116a5e`): context마다 스레드 하나가 NIC의 오류 이벤트 fd(`docaEvent`)에서
  `poll()`로 잠들어 있다가 깨어나 오류 조회를 실행한다. 정상 실행에서 스레드당 CPU 6–10 us(시작할 때 한 번 스케줄됨),
  오류 때 평균 82 us(최대 113 us, 스케줄 최대 10번). application이 오류를 묻지 않아도 원인이 WARN으로 나온다
  `[측정: 6절 2026-11-23 host 스레드]`.
- 기존 `doca_gpu_verbs_reset_tracking_and_memory()`는 GPU 커널이 모두 끝난 상태를 전제로 하므로 쓸 수 없다(6절 2026-11-23).

**상대 죽음 칸의 갈림(2026-11-24, 결정: (나) 제자리 교체로 간다. 연결 오류 복구와 같은 바탕을 쓴다).** (가) 새 communicator로 갈아타기: 전원 멈춤 → shrink → grow → 번호 변환. 있는 함수로 된다(6절 2026-11-24 세 줄, 측정). 돌던 GPU 호출은 오류로 끝나고, application은 device 핸들(`ncclDevComm`, window)을 다시 만들어 그 step을 다시 한다. 4.2절의 "step 하나만 다시"와 맞는다. (나) 제자리 교체: 옛 communicator와 GPU 쪽 구조를 그대로 두고 죽은 rank의 QP만 새 프로세스에 다시 잇는다. GPU 호출은 기다렸다가 이어진다. NCCL에 없는 기능(기존 communicator에 같은 번호로 들어오기, GPU 쪽 QP·rkey 표 고치기, 떠 있던 요청 보존과 재전송)을 새로 만들어야 한다 `[추론]`.

구현 순서(제안): (1) 멈춤과 보존: 실패한 QP에 새 요청이 끝나지 않은 요청을 덮어쓰지 않게 하고, 대기 중인 GPU 스레드가 복구를
기다리게 함. 정상 경로에 load를 더하지 않도록 이미 하는 동작(자리 기다리기의 poll 결과, 예약 atomic)에 실음. (2) 번호 맞추기
시제품: 한쪽 QP를 초기화하고 끝나지 않은 요청을 다시 보냄. 상대 쪽 초기화는 시험 도구(`qperr.c`)가 대신함. (3) 양쪽
합의(방법 미정, 4.1절). (4) 세 칸 모두 검증(데이터 전부 도착, signal 값 정확, 틀린 요청만 실패).

복구는 위의 host 스레드가 실행한다(결정 2026-11-23). application이 묻지 않아도 돈다.

멈춤의 바탕(`cq->hold`, 커밋 `d56b15e`): host만 쓰는 flag가 켜져 있으면 실패한 QP에서 GPU 폴링이 `-EIO`로 끝나지 않고 기다린다. 검사는 폴링의 실패 경로에서만 들어가는 `__noinline__` 함수 하나에 있다(진입점에 두면 구성 1·2가 1–2% 느려짐 `[측정]`). 재구성이 생길 때까지 꺼 둔다(결정 2026-11-25).

## 5. 작업 순서

- [x] 새 폴더에 소스 받기
- [x] 이슈 네 건의 현재 상태 확인
- [x] 빌드(rain과 sunny 모두 NCCL, NVSHMEM 빌드됨)
- [x] 첫 실행(NCCL GIN은 rain과 sunny 사이, NVSHMEM은 sunny 안에서 통과)
- [x] 이슈 네 건 수정과 재현 시험(#117은 장애 확인 없이 수정만)
- [x] 복구 규칙 정하기(4.1절)
- [ ] 복구 설계와 구현(4.3절, 설계 중)

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
| 2026-11-20 | 수정 3(host가 원인을 읽음): gdrcopy가 있으면 QP 구조체를 host에도 매핑해 `cq->err`를 읽고 기존 WARN에 syndrome, vendor_err, WQE 번호를 넣음. 기본 CQ는 오류를 보면 앞 칸으로 거슬러 올라가 첫 실패를 기록. 수정 4: collapsed CQ 두 방식에도 같은 기록을 붙임. sunny가 보내고 rain이 받음, 경우당 n=1 | 기본 CQ와 collapsed(GPU): 정상 실행 120/120, 잘못된 put 뒤 멈춤 없음, 시간 제한 flush 110번 `ncclRemoteError`, host WARN에 `syndrome=0x13 vendor_err=0x88 wqe_counter=20`(실패한 put의 WQE). host가 읽는 collapsed(`NCCL_GIN_GDAKI_CQ_TYPE=2`)는 rain에 gdrcopy가 없어 시작에서 실패, 시험 못 함. 원본 대비 NCCL 8개 파일 +198 −32. 로그 sunny `runs/ginfault-fix4-cq{0,1,2}-*` |
| 2026-11-20 | rain에 gdrcopy v2.5.2 빌드, `gdrdrv` 적재, `gdrcopy_sanity` | 36개 중 31 통과, 0 실패, 5 건너뜀(n=1). 로그 `build-gdrcopy.log` |
| 2026-11-20 | 수정 1–4 반복 시험. 재현에 `BURST`(flush 전에 put 여러 개), `COUNTER`(카운터 put, QP 두 개) 추가. sunny가 보냄. CQ 방식 3가지 × (put 1개, put 8개, 카운터 put) × 10회 = 90회, 모두 host 조회 1 s와 시간 제한 flush 사용 | 90회 모두: 멈춤 없음, 120번 반환, 110번 `ncclRemoteError`, 받는 쪽 10칸 도착, host WARN `syndrome=0x13 vendor_err=0x88`, WQE 번호는 실패한 put(put 1개·카운터 20, put 8개 160). collapsed 두 방식 60회에서 원인이 '취소됨'으로 덮어써진 경우 0회. host가 읽는 collapsed의 정상·시간 제한 없는 경우도 통과(n=1). 로그 sunny `runs/ginfault-rep-cq*`, `runs/ginfault-fix4b-cq2-*` |
| 2026-11-20 | nvshmem #120 재현 `repro/shmem_fault.cu`(sunny, PE 2개, p+quiet+g 40번, 10번째 p가 heap 밖 주소), 실행 `shmem_fault.sh`. 수정 전 n=1 | 정상: 40/40 도착. 잘못된 p: quiet 40번 모두 반환, g는 10번만 맞음, 10칸 도착, 로그에 오류 흔적 없음. 로그 sunny `runs/shmemfault-before-*` |
| 2026-11-20 | nvshmem #120 수정: `ibgda_poll_cq`가 첫 오류 CQE(QP 번호, WQE 번호, syndrome, vendor_err)를 `state.extra`가 가리키는 host 메모리에 남기고, proxy 스레드가 `WARN: IBGDA error CQE: ...` 한 줄을 한 번 출력. 4개 파일 +56 −4(#117 포함) | 정상 3회: 40/40. 잘못된 p 10회: 10회 모두 WARN에 `syndrome=0x13 vendor_err=0x88 wqe_counter=16`. quiet 반환과 g 값은 수정 전과 같음. 로그 sunny `runs/shmemfault-fix-*` |
| 2026-11-20 | nvshmem 조회 함수: `nvshmemx_get_op_error(nvshmemx_op_error_t*)`를 host와 device에 추가. 분류는 CQE만으로 정함: syndrome 0x04·0x12는 요청 문제, 0x05+vendor_err 0xf5는 로컬 QP, 0x13·0x15·0x16은 상대 쪽, 나머지는 모름. WARN에도 `class=` 추가. 재현에 `CHECK=1`(커널이 quiet 뒤에 묻고 멈춤). NVSHMEM 원본 대비 12개 파일 +145 −4 | 정상 3회: 오류 없음(class=0), 40/40. 묻지 않음 5회: 전과 같음(quiet 40번 반환, g 10번만 맞음), host 조회는 `class=3 syndrome=0x13 vendor_err=0x88 wqe_counter=16`. 물음 10회: 10회 모두 커널이 10번째에서 멈춤, 틀린 g 0건. 로그 sunny `runs/shmemfault-q-*` |
| 2026-11-20 | NVSHMEM PE가 가진 소켓 확인(sunny, PE 2개, 실행 중 `ss`와 `/proc/<pid>/fd`, n=1씩). `0x12` 재현: `KIND=1`(8바이트로 정렬되지 않은 주소에 `nvshmem_long_atomic_add`), `CHECK=1`, n=5 | 소켓: btl `self,vader`에서는 PE마다 TCP 1개(두 PE가 같은 포트로 연결, 실행기 쪽)와 unix 6개, 상대 PE로 가는 TCP 없음. btl `self,tcp`에서는 상대 PE와 TCP 2개가 생기지만 OpenMPI 것이고 NVSHMEM 코드는 그 fd를 갖지 않음 `[추론: bootstrap이 MPI 호출만 씀]`. 원인 5: 5회 모두 `syndrome=0x12 vendor_err=0x8a`, 조회 분류 "요청 문제", 커널이 10번째에서 멈춤. 로그 sunny `runs/shmemfault-k1-*` |
| 2026-11-20 | 독립 코드 검사 1회(#2483 변경분, 읽기 전용, 지적 11건). 반영(수정 5): collapsed에서 덮어써지는 중인 CQE를 성공으로 넘기던 경로 제거, CQE 읽기를 cache 우회 load와 앞뒤 헤더 비교로 통일, 재사용된 칸을 오류로 기록하지 않게 확인 추가, 카운터 put에서 한 QP가 실패하면 함께 버려지는 QP도 실패로 표시, host가 읽는 CQ의 기록도 앞뒤 비교, host WARN은 원인이 찍힐 때까지 다시 조회, CPU proxy 방식도 실패한 QP는 전송 중단, 주석 정정. 미반영: 지적 9(오류 뒤 SQ 칸 덮어쓰기)는 재전송 단계로 넘김, 지적 10(WQE 번호 48비트)은 한계로 주석 | 반영 뒤 재시험, sunny가 보냄: CQ 방식 3가지 × (정상, 시간 제한 없음, 시간 제한 각 1회 + put 1개·8개·카운터 각 5회) = 54회 모두 수정 4와 같은 결과(멈춤 없음, `vendor_err=0x88`, WQE 20 또는 160). NCCL 원본 대비 8개 파일 +248 −37. 로그 sunny `runs/ginfault-fix5-*` |
| 2026-11-21 | #2483 수정 5를 rain이 보내는 방향으로 재시험. 구성은 sunny 방향과 같음: CQ 방식 3가지 × (정상, 시간 제한 없음, 시간 제한 각 1회 + put 1개·8개·카운터 각 5회) = 54회 | `[측정]` 54회 모두 sunny 방향과 같은 결과: 멈춤 없음, 시간 제한 flush 110번 `ncclRemoteError`, 받는 쪽 10칸, host WARN `syndrome=0x13 vendor_err=0x88`, WQE 20 또는 160. collapsed 30회에서 원인이 덮어써진 경우 0회. 로그 `runs/ginfault-fix5r-*` |
| 2026-11-21 | 독립 코드 검사 2회(NVSHMEM 변경분 전체). 지적 10건| 반영 7건: (1) 오류 기록을 `cons_idx` 공개 전으로 옮김 (2) 찢긴 CQE 복사는 같은 값이 읽힐 때까지 다시 읽음(NCCL 수정과 같은 방식), 필드를 지역 변수로 먼저 읽음 (3) ABI 심볼 목록 정렬 위치, NVSHMEM 검증 함수 통과 `[측정]` (6) 조회가 `nullptr`에 `INVALID_VALUE`, 기록 없는 구성에 `NOT_SUPPORTED` (7) `0xf5`를 이름 붙인 측정 규칙으로 하고 장비·펌웨어를 주석에, 분류표 자체 검사 `repro/decode_test.cpp` 통과 `[측정]` (9) 주석 정정, 기록 읽기를 `nvshmemi_ibgda_load_err` 하나로 통합, WARN의 `pe=`를 `reporting_pe=`로 (10) 재현이 커널 실행 오류와 종료를 확인, `THREADS` 추가. 2단계로 넘김 3건: (4) QP·세대별 기록과 지우기 (5) 실패 요청 보존 (8) 기록에 상대 PE·주소·길이·key |
| 2026-11-21 | 위 수정 뒤 NVSHMEM 재현(sunny, `shmem_fault.sh`). 스레드 1개: 정상 3회, 조회 안 함 5회, 조회함 10회, 정렬 오류 5회. 스레드 여러 개(`THREADS`, 스레드 0만 잘못된 요청): 8개 정상 3·조회 안 함 5·조회함 20회, 64개 조회함 20회·정렬 오류 10회 | `[측정]` 스레드 1개 23회: 2026-11-20과 같은 결과(`0x13/0x88` class 3, `0x12/0x8a` class 1, 조회하면 10번째에서 멈춤). 스레드 여러 개 55회: 잘못된 요청 뒤 quiet가 돌아왔는데 조회가 "오류 없음"인 경우 0회. **그러나 55회 모두 기록된 것은 원인이 아니라 뒤따른 flush(`syndrome=0x05 vendor_err=0xf9`, class 4 "모름")였다.** 같은 QP에 뒤따라 쌓인 요청의 flush CQE가, 누가 읽기 전에 단일 CQE 칸을 덮어쓴 것 `[추론]`. 수정 전 코드에서 "오류 없음"이 실제로 나오는지는 돌려 보지 않아, 이 시험이 지적 1을 가려낸다는 증거는 없다 `[미확인]`. 또 RC QP가 PE당 2개이고 요청마다 번갈아 쓰여(`ibgda_get_rc`, map type NONE) 한 QP가 실패해도 다른 QP의 요청은 계속 도착한다(스레드 8개·조회 안 함에서 40칸 도착) `[측정: 실행] [추론: 소스]`. 로그 `runs/shmemfault-r2-*` |
| 2026-11-21 | 정상 경로 성능 A/B 1차. 원본 release를 `base/`(git worktree)에 따로 빌드(cmake 옵션 동일 확인), `ab.sh`로 원본·수정본을 번갈아 실행, `ab_report.py`로 중앙값 비교. NVSHMEM: sunny, perftest 4종 × 10회. NCCL: rain↔sunny, `ring_exchange` 예제 × 20회, GDAKI 강제 | `[측정]` NVSHMEM: 4 B–4 KiB 지연이 +0.6–5.2%(0.1–0.5 us, 원본의 회차 간 편차는 1–2%), `shmem_put_bw` 대역폭은 편차 안. atomic 지연 3개 줄은 원본에서도 8.7/13.4 us 두 값을 오가서 비교에서 제외. NCCL us/batch: 구성 1 +7.48%(118.89→127.79), 구성 2 +13.27%, 구성 3 +0.89%, 구성 4 +1.23%(원본 편차 0.2–2.1%). 원인 `[추론]`: NVSHMEM은 폴링마다 CQE `op_own`을 한 번 더 읽음, NCCL은 put마다 `cq->err`를 캐시 우회 load로 읽음(`doca_gpu_dev_verbs_submit`). 로그 `runs/ab-shmem-20261121-173139`, `runs/ab-gin-20261121-174136` |
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
| 2026-11-23 | 오류 기록의 WQE 번호를 "안전한 하한"으로 바꿈(결정: 정확한 번호는 필요 없고 QP별 하한이면 된다). NVSHMEM: `ibgda_latch_err_cqe`가 오류 CQE의 counter 대신 첫 오류를 보기 전에 읽은 `cons_idx`를 기록(커밋 `20ba0c88`, WARN의 `acked_psn`·`next_psn` 포함). NCCL collapsed CQ: `set_err_collapsed`가 실패 뒤 멈추는 `cqe_ci`를 기록하고 flush 기록 특수 처리를 없앰(커밋 `0fd4724`, +13 −11). 양쪽 host 전체 빌드. 검증: NVSHMEM 회귀 18회, NVSHMEM 전송 도중 주입(`STREAM=1`, RC QP 1개, put 20000개, 보내는 PE·받는 PE 각 5회), NVSHMEM 주입 스레드 8개 6회, NCCL 재현 120회(양방향), NCCL 전송 도중 주입 40회(기본 CQ·collapsed 두 방식, 각 10회), A/B NCCL 20회·NVSHMEM 10회 | `[측정]` NCCL 전송 도중 주입, 기록된 put 번호 − 도착 칸 수: 기본 CQ 10회 모두 0, GPU가 폴링하는 collapsed에서 보내는 쪽 주입 10회는 −43에서 0(고치기 전 +18에서 +36), 받는 쪽 주입 10회 모두 0, host가 폴링하는 collapsed 10회는 −1에서 0. 40회 모두 0 이하, 멈춤 0회. NVSHMEM 전송 도중 주입: 스레드 1개 일반 실행에서 put 10개 뒤 기록이 16이므로 이 QP의 WQE 번호는 put 수보다 6 크다고 보고 비교 `[추론]`. 보내는 PE 주입 5회는 기록 10243에 도착 10361–10408칸(기록 − 6이 118–165 아래), 받는 PE 주입 5회는 기록이 도착 + 6으로 정확. 10회 모두 하한이 도착분 이하. NVSHMEM 회귀와 주입: 분류는 전과 같고 스레드 여러 개의 `wqe_counter`가 작아짐(59→56, 361→330). NCCL 120회: 멈춤 0회, host 조회 90회 모두 `0x13/0x88`, collapsed(GPU 폴링)의 WQE 번호가 20→19, 160→159로 하나 작게 나옴(하한이라 허용, 마지막 WQE는 signal atomic). A/B NCCL us/batch: +0.66%, +1.06%, +0.39%, +0.02%. A/B NVSHMEM: put 지연 +1.08%, p 지연 +1.74%, 대역폭 −0.58%(편차 안), atomic 6줄 +0.7–1.8%. 원본 대비 NCCL 11개 파일 +328 −46(코드 230줄), NVSHMEM 15개 파일 +271 −11(코드 203줄). 로그 `runs/ginfault-fix11*`, `runs/ginfault-lbstrm-*`, `runs/shmemfault-lb-*`, `runs/shmemfault-cnt-*`, `runs/ab-gin-20261123-181044`, `runs/ab-shmem-*`(마지막) |
| 2026-11-23 | NCCL host 오류 조회의 비용. `gin_fault`가 `ncclCommGetAsyncError` 호출마다 시간을 재어 50 us를 넘긴 호출 수를 `ASYNCQ` 줄로 출력하게 함. 장애 없이 300회 반복(약 9.3 s), 호출 약 8800번, 조회 간격 1 s와 10 s 각 3회, rain이 보냄 | `[측정]` 6회 모두 50 us를 넘긴 호출 0번. 간격 1 s에서도 조회가 도는 호출(실행당 약 9번)이 50 us 안에 끝났다. 이 장비는 completion channel 이벤트 방식으로 조회한다 `[추론: 소스 gin_host_gdaki.cc:935의 polling 대체 문구가 INFO 로그에 없음]`. 이벤트 방식을 못 쓰는 장비의 polling 방식(QP마다 QUERY_QP, 소스 주석으로 약 250 us)은 재지 못했다. 로그 `runs/ginfault-q1-2026*`, `runs/ginfault-q10-2026*` |
| 2026-11-23 | 기본 동작 두 가지 변경. NCCL: `NCCL_GIN_ERROR_QUERY_SEC` 기본값 10 → 1(커밋 `3c0f8bd`), 시험 스크립트에서 간격 지정을 지움. NVSHMEM: 실패가 기록되면 host가 원인을 찍고 프로세스를 끝냄, `NVSHMEM_IBGDA_ABORT_ON_OP_ERROR=0`이면 전처럼 계속 실행(커밋 `efad32f5`; 2026-11-20의 "중단 대신 조회" 결정을 "기본은 중단, 조회는 선택"으로 바꿈). `shmem_fault.sh`는 조회 방식으로 돌고 `ABORT=1`로 기본 동작을 켠다. 검증: NVSHMEM 조회 방식 회귀 12회, 기본 동작으로 6개 구성 × 3회(정상, 잘못된 주소 스레드 1·8개, 정렬 오류, 보내는 PE QP 주입, 받는 PE QP 주입), NCCL 재현 120회(간격 지정 없음) | `[측정]` NVSHMEM 기본 동작: 장애를 넣은 15회 모두 WARN과 "Aborting after the IBGDA error above" 문구가 찍히고 mpirun 제한 시간 전에 끝남(3.5–9.4 s; 정상 실행 3.45 s, 받는 PE 주입은 재시도 초과 대기 포함), 정상 3회는 끝까지 돌아 SUMMARY 출력. mpirun rc는 정상 실행도 1이라(시험 프로그램이 finalize 없이 끝남) rc로는 구분되지 않는다. 조회 방식 회귀는 전과 같음. NCCL 120회: 간격을 주지 않아도 host 조회 90회 모두 `0x13/0x88` WARN, 멈춤 0회. 원본 대비 NCCL 11개 파일 +329 −47(코드 231줄), NVSHMEM 16개 파일 +285 −11(코드 214줄). 로그 `runs/shmemabort-*`, `runs/ginfault-fix12*`, `runs/shmemfault-cnt-*` |
| 2026-11-23 | 독립 코드 검사 4회"). 대상: 3회 검사 이후의 변경 전부. 지적 5건반영: (1) NCCL host가 폴링하는 collapsed CQ도 CQE의 counter 대신 `old_cqe_ci`(하한)를 기록, (2) NVSHMEM은 원인 조회가 끝난 뒤에 한 줄을 찍고 중단(기본 중단 때문에 2·3번째 조회가 못 돌던 것), (3) NCCL 이벤트 방식에서 실패한 QP를 기억해 원인이 나올 때까지 다시 조회, (4) NCCL polling 대체 방식은 간격의 10배로 돌고 간격을 sweep 끝에서부터 셈, (5) NVSHMEM은 PSN을 못 읽으면 `psn=unavailable`. 주석 정정("완료가 확인되지 않았다"). 커밋 NCCL `3c0f8bd`, NVSHMEM `71856a5e`. 검증: NVSHMEM 조회 방식 12회와 기본 동작 8회, NCCL 재현 120회, host가 폴링하는 collapsed CQ의 전송 도중 주입 20회 | `[측정]` NCCL 전송 도중 주입(host 폴링 collapsed): 기록된 put 번호 − 도착 칸 수가 20회 모두 0, 멈춤 0회. NVSHMEM 기본 동작: 장애 6회 모두 원인과 `acked_psn` 출력 후 종료, 정상 2회는 끝까지 실행. 조회 방식 12회는 전과 같음. NCCL 120회: rain이 보내는 방향의 처음 10회(기본 CQ의 정상·시간 제한 없음·시간 제한, counter 2회, put 1개 5회)가 시작에서 실패했다: rain에서 `ibv_create_cq`가 "Invalid argument"로 실패해 `ncclCommWindowRegister`가 오류를 냄. 약 40 s 동안만 그랬고 원인은 `[미확인]`. 같은 10회를 다시 돌리니 모두 통과. 나머지 110회와 다시 돌린 10회는 전과 같은 결과(멈춤 0회, host 조회 모두 `0x13/0x88`). 독립 검사 복구 단계의 전제로 든 것: 실패 뒤 새 요청을 멈추고 재전송 구간 보존, 기존 QP reset 함수는 번호와 큐를 지우므로 그대로 못 씀, 오류 상태를 QP 단위로 되돌리기, 양쪽 QP의 세대와 PSN 합의. 원본 대비 NCCL 11개 파일 +345 −48(코드 240줄), NVSHMEM 16개 파일 +294 −11(코드 221줄). 로그 `runs/ginfault-fix13*`, `runs/ginfault-rvstrm-*`, `runs/shmemabort2-*` |
| 2026-11-23 | 실패한 QP 쌍을 초기화해 다시 쓸 수 있는지(NIC 수준). `synd.c`의 `reset_reuse`: write 8개 중 4번째를 잘못된 rkey로 실패시킨 뒤, 양쪽 QP를 RESET으로 내리고 INIT·RTR·RTS로 다시 올린 다음 write 8개를 다시 보냄. rain과 sunny 각 3회. 복구 설계에 대한 결정도 같은 날: 조정 통로(예비 QP)는 구현해 메모리와 시간을 재 보고 크면 철회, 복구는 gdrcopy가 있을 때만 켜고 없으면 원인만 알리는 방식으로 자동 전환, 복구 횟수 한도는 근거 없는 숫자(3)를 정하지 않고 복구 비용을 잰 뒤 정함 | `[측정]` 6회 모두 초기화 뒤의 write 8개가 성공. 초기화 전: 요청 쪽 `sq_hw=8 acked_psn=2`, 응답 쪽 `rcv_psn=3`, 오류 기록 있음. 초기화 뒤: 요청 쪽 `sq_hw=8 acked_psn=7 next_psn=8`, 응답 쪽 `rcv_psn=8`, 오류 기록 0. 즉 NIC의 SQ 번호와 PSN이 0에서 다시 시작하고 QP context의 오류 기록이 지워진다. 양쪽 초기화와 재연결에 걸린 시간은 rain 1.46–1.50 ms(한 프로세스 안에서 두 QP를 순서대로). `[측정: 소스]` NCCL의 DOCA에는 `doca_gpu_verbs_reset_tracking_and_memory()`가 있으나 NCCL은 부르지 않는다. 이 함수는 소프트웨어 번호를 0으로 되돌리고 SQ·CQ 버퍼를 지우며 `cudaMemcpy`와 `cudaDeviceSynchronize`를 쓰므로, GPU 스레드가 대기 중인 상태에서는 쓸 수 없다. 로그 없음(화면 출력만) |
| 2026-11-23 | host 스레드 시제품(결정: CPU 사용량을 보고 결정). `gin_host_gdaki.cc`에 context마다 스레드 하나(`NCCL GIN Err`): `docaEvent`의 fd(새 함수 `doca_verbs_comp_channel_get_fd`)와 종료용 eventfd에서 `poll()`로 대기, 이벤트가 오면 오류 조회를 실행. 조회 상태는 mutex로 application 쪽 조회와 공유. WARN은 GPU가 `cq->err`를 기록하면 바로, 늦어도 조회 간격(1 s) 뒤에 한 번 찍음. SDK 방식 channel에서는 fd를 못 얻어 스레드를 띄우지 않음(기존 동작). 시험: `gin_fault`에 `NOASK=1`(application이 오류를 묻지 않음)과 스레드 CPU 시간 출력(`/proc/<pid>/task/<tid>/schedstat`, `NCCL_SET_THREAD_NAME=1` 필요) 추가. 최종 코드로 82회(정상 12, 장애 70): CQ 방식 3가지, 양방향, 잘못된 put·QP 오류 주입·전송 도중 주입, 묻는 application과 묻지 않는 application. A/B 10회는 첫 판(WARN 시점만 다름)으로 측정 | `[측정]` 82회 모두 멈춤 없음, rc 0. 장애 70회 모두 WARN이 정확히 한 번, 원인은 넣은 장애와 일치(`0x13/0x88` 57회, `0x05/0xf5` 13회). 묻지 않는 application 26회에서도 WARN이 나옴. 전송 도중 주입 10회 모두 하한 ≤ 도착 수 × 2(WQE 2개가 put 하나). 스레드 CPU: 깨어나지 않은 스레드 94개 평균 8.4 us·최대 10.2 us·스케줄 1번, 깨어난 스레드 70개 평균 82 us·최대 113 us·스케줄 최대 10번. A/B `ring_exchange` us/batch: +0.72%, +0.00%, +0.59%, +0.51%(원본의 회차 간 편차 0.11–2.66%). 가는 길에 고친 것 둘: (1) 이벤트 직후에 WARN을 찍으면 GPU가 아직 기록하지 않아 하한이 0으로 나옴(전송 도중 주입 10회 모두) → 기록을 기다리게 함. (2) 조회 간격만큼 무조건 미루면 1 s 안에 끝나는 실행에서 WARN이 안 나오고, 묻는 application에서는 두 번 나옴 → 기록이 보이면 바로 찍고 `cause_logged`를 확인. 원본 대비 NCCL 13개 파일 +410 −51(이번 변경 4개 파일 +66 −4, 코드 57줄). 로그 `runs/ginfault-thr3-*`, `runs/ab-gin-20261123-203021` |
| 2026-11-23 | rank 4개 구성(결정: 노드당 rank 둘). `NCCL_MULTI_RANK_GPU_ENABLE=1`로 GPU 한 장을 rank 둘이 쓰고, `--map-by node`로 rank 0·2는 rain, 1·3은 sunny. `gin_fault`는 rank 0이 rank 1에 보내고 나머지는 QP만 가짐. NCCL 예제는 node 안 순번을 device 번호로 써서 `repro/dev0.c`(LD_PRELOAD, `cudaSetDevice`를 항상 0으로)로 돌림. `run_gin_fault.sh`와 `ab.sh`에 `NP`, `SN`(stream의 put 수) 추가. host 스레드 시제품 포함 코드로 장애 시험 41회(정상 9, 장애 32: 잘못된 put·주입·전송 도중 주입, CQ 방식 3가지, 묻지 않는 application 포함)와 `ring_exchange` A/B 10회 | `[측정]` 41회 모두 멈춤 없음. 장애 32회 모두 WARN 정확히 한 번, 원인 일치(`0x13/0x88` 24회, `0x05/0xf5` 8회). 전송 도중 주입 5회 모두 하한 = 도착 수 × 2. 스레드 CPU(36회, rank 0): 깨어나지 않은 스레드 평균 8.4 us·최대 10.8 us, 깨어난 스레드 평균 77 us·최대 110.5 us. A/B us/batch: +0.04%, −0.01%, −0.05%, +1.81%(원본의 회차 간 편차 1.83–1.96%). 단 GPU를 rank 둘이 나눠 써서 batch 시간이 약 1120 us(rank 2개일 때 56–120 us)이고 값이 약 20 us 단위로 뭉쳐 나와 작은 차이는 보이지 않는다. stream을 put 30000개(창 30 MiB)로 돌리면 rain의 `ncclCommWindowRegister`가 실패(3회 모두, rain의 BAR1 256 MiB 때문), 12000개로 줄여 실행. 로그 `runs/ginfault-np4-*`, `runs/ab-gin-20261123-213151` |
| 2026-11-23 | rank 죽음과 shrink(결정: 프로세스 복구도 되는 것은 한다). `gin_fault`의 본문을 함수로 묶어 두 번 돌릴 수 있게 하고 `KILL_RANK`, `KILL_AFTER_MS`를 추가: 지정한 rank가 실행 뒤(`raise(SIGKILL)`) 또는 실행 도중(타이머의 SIGALRM)에 죽고, 남은 rank가 1 s 뒤 `ncclCommGetAsyncError`를 본 다음 `ncclCommShrink(NCCL_SHRINK_ABORT)`로 새 communicator를 만들어 같은 전송(120번)을 다시 함. rank 4개, mpirun `--enable-recovery`. (A) 전송에 끼지 않는 rank 3이 실행 뒤에 죽음 4회. (B) 받는 rank 1이 전송 도중에 죽음, 시간 제한 없는 flush 5회(그중 mpirun 제한 90 s 2회, 35 s 3회). (C) B와 같고 시간 제한 flush 3회. (D) 보내는 rank 0이 죽음 2회 | `[측정]` 12회 모두 남은 세 rank에서 shrink 성공, 12–29 ms, 직전의 `ncclCommGetAsyncError`는 모두 "오류 없음". (A) 4회, (C) 3회: 새 communicator에서 120번 반환, 120칸 도착, signal 120. (C)의 첫 실행은 죽은 뒤의 flush 5–9번이 `ncclTimeout`. (B): 첫 실행의 flush가 죽은 시점(111–116번째)에서 멈춤. 제한 90 s의 2회는 `0x15/0x81` WARN이 죽은 지 약 56–60 s 뒤에 나오고 바로 그때 두 번째 실행이 시작돼 120/120 도착(시각은 mpirun `--timestamp-output`, 초 단위). 제한 35 s의 3회는 두 번째 실행이 시작되기 전에 mpirun이 끝냄. 즉 shrink는 끝났지만 멈춘 GPU 커널이 풀릴 때까지 다음 커널이 못 돈다. (D)는 시험 프로그램의 한계로 결과 없음(rank 0이 나머지에게 진행 신호를 보내는 구조). 로그 `runs/ginfault-shrink*` |
| 2026-11-24 | 죽음을 안 뒤의 shrink(결정: shrink 쪽을 고친다). host가 죽음을 알아 `ncclCommGetAsyncError`가 오류를 내기 시작하면 `ncclCommShrink(NCCL_SHRINK_ABORT)`가 `ncclRemoteError`로 실패한다(10회 중 10회): `ncclCommInitChildComm`이 `ncclCommEnsureReady(parent)`의 GIN 오류를 그대로 돌려주기 때문 `[측정: 소스, init.cc]`. 원본도 NIC 오류가 온 뒤(약 1분)에는 같은 이유로 실패할 것이다 `[추론: 소스]`. 수정(커밋 `da35e25`, `init.cc` +5 −1): `NCCL_SHRINK_ABORT`를 준 shrink는 부모의 `ncclRemoteError`를 거절 사유로 보지 않는다. split, 옵션 없는 shrink, 다른 오류는 전과 같다. rank 1을 init 0.6 s 뒤 SIGKILL, rank 4개 6회(untimed 3, timed 3), rank 2개 3회 | `[측정]` shrink 18회(3 rank × 6회) 모두 성공, 12–18 ms, 새 communicator에서 120번 반환·120칸 도착·오류 없음. rank 2개 3회: shrink 성공(22 ms), 그 뒤는 rank가 하나뿐이라 `put`에서 멈춘다(시험 프로그램의 한계). 검사 지적(미반영): 초기화에 실패한 부모도 통과시킨다. 로그 `runs/ginfault-pd4c-*`, `runs/ginfault-pd2c-*` |
| 2026-11-24 | 방향 결정 셋과 되돌린 구현 둘. 결정(결정, 2026-11-24): (1) 상대 죽음은 "제자리 교체"로 간다. 연결 오류 복구와 같은 바탕 위에 합류·표 교체·상태 전달을 얹고, shrink+grow는 예비 프로세스가 없을 때의 대안이다. (2) 조정 메시지에 TCP를 쓰지 않는다(production의 RDMA 학습에서 못 쓴다). TCP에는 "소켓이 닫혔는지 보기"만 남긴다. (3) 코드가 불어나지 않게 하고 단계마다 독립 코드 검사를 받는다. 되돌린 구현: (가) 이웃 소켓을 늘 지켜보다가 닫히면 죽음으로 보고, 소켓으로 인사와 죽은 rank 번호를 주고받아 communicator의 모든 rank가 QP 전부를 실패시키는 방식. (나) 그 메시지를 상대당 RC QP 하나(inline int32)로 옮긴 조정 통로. | `[측정]` 둘 다 동작은 했다(rank 1 SIGKILL 16회에서 멈춤 0회, 남은 rank 모두 죽음을 알림). (가)는 결정 (2)에 어긋나고 (나)는 비싸다는 판단(결정; 비용은 재지 않음)으로 되돌렸고, 2026-11-25 커밋 정리 때 기록에서도 지웠다. 남는 사실: GIN `collComm`의 이웃 소켓은 연결 뒤 아무도 읽고 쓰지 않는다 `[측정: 소스]`. GDAKI context는 communicator당 둘이라 스레드와 WARN도 둘이다. `gin_fault`는 `ncclCommDestroy` 없이 끝난다. `ibv_create_comp_channel`·`ibv_destroy_comp_channel`은 symbol 버전이 IBVERBS_1.0이라 NCCL의 `LOAD_SYM`(1.1)으로 읽으면 verbs 로딩 전체가 실패한다. 로그 `runs/ginfault-peerdeath-*`, `runs/ginfault-pd4-*`, `runs/ginfault-ctlb*` |
| 2026-11-24 | grow 확인(결정: 죽은 자리를 채우고 나머지는 기다린다, 4단계까지 진행). `repro/gin_fault.cu`에 `SPARE=1`: 마지막 MPI 프로세스가 communicator 밖에서 기다리다가, 남은 rank들의 shrink 뒤 `ncclCommGetUniqueId`로 받은 id(MPI로 전달)로 `ncclCommGrow(NULL, n, &id, n−1)`을 불러 마지막 rank로 들어온다. 남은 rank는 `ncclCommGrow(shrunk, n, …, −1)`. 프로세스 5개(rain 3, sunny 2), rank 1을 init 0.6 s 뒤 SIGKILL, timed. 첫 1회는 CHUNK 64 KiB, 뒤 3회는 16 KiB | `[측정]` 4회 모두 shrink 12–17 ms 뒤 grow가 네 프로세스에서 328–335 ms에 끝난다. 64 KiB 1회는 grow 뒤 rain의 두 rank가 `ncclCommWindowRegister`에서 `ibv_reg_mr_iova2 ... Bad address`로 실패(rain GPU의 BAR1 256 MiB에 프로세스 셋, 환경 한계). 16 KiB 3회는 grow된 communicator(4 rank)에서 120번 반환·120칸 도착·오류 없음. 번호는 소스대로다 `[측정: init.cc:3964, :3971]`: 남은 rank는 shrink된 번호(0, 2→1, 3→2)를 유지하고 새 프로세스가 3이 된다. 따라서 원래 번호로 보이게 하려면 번호 변환이 필요하다. **설계에 영향을 주는 확인** `[측정: 소스]`: NCCL에 딸린 `contrib/nccl_checkpoint`(LD_PRELOAD shim)는 communicator를 다시 만들면서 application이 든 핸들을 그대로 두는 간접 참조(synthetic handle)와 재연결용 KV 저장소를 이미 갖고 있고 shrink·grow도 기록한다. 그러나 README의 한계 항목이 "The device API is not supported. `ncclDevComm` objects and device-visible `ncclWindow_t` values cannot be restored"이다. GIN은 device API이고 `ncclDevComm`은 application의 CUDA 커널에 값으로 넘어가므로, 새 communicator로 갈아타는 방식에서는 application이 device 핸들을 다시 만들어야 한다. 결정 필요(아래 4.3절 갈림). 로그 `runs/ginfault-grow4-*`, `runs/ginfault-grow4b-*` |
| 2026-11-24 | rank가 죽을 때 남는 신호 재검토(결정: 통로는 비싸다, 죽음의 특이점이나 로그가 없는지 다시 본다. 전송 도중의 죽음만 본다). 원본 빌드(`RR_ROOT=base`), rank 4개, rank 0(rain)이 rank 1(sunny)에게 64 KiB put을 보내는 도중 rank 1을 SIGKILL. `repro/watch_counters.sh`(포트 `hw_counters`·`counters`·`ethtool -S`의 변화만 출력)를 양쪽에서, rain 커널 로그, rank 0에 Nsight(`repro/nsys_rank.sh`). 반복: 죽음 4회, 죽음 없는 대조 1회(9.3 s), 상대가 살아 있고 QP만 ERR(`libqperr.so`) 2회, 아무도 보내지 않는 rank 3의 죽음 1회 | `[측정]` 보내던 쪽 장비의 `rp_cnp_handled`만 움직인다: 죽은 뒤 0–20 ms 안에 처음 오르고(20 ms 간격으로 잰 2회; 0.5 s 간격 2회는 0.2–0.3 s), 재전송마다 +1씩 총 +13–15(약 0.03, 0.09, 0.2, 0.5, 1, 2, 4, 8, 14 s, 그 뒤 8.6 s마다). NIC의 오류 CQE는 57.7–58.9 s 뒤. 대조와 rank 3의 죽음에서는 안 움직인다. **죽음에만 나오는 신호는 아니다**: 상대가 살아 있고 QP만 ERR인 2회에서도 같은 모양(+13, +14)이다. 포트 오류 카운터(`local_ack_timeout_err`, `roce_adp_retrans`, `req_cqe_error`, `packet_seq_err`)와 sunny의 `np_cnp_sent`는 한 번도 안 움직였고(GIN QP가 따로 가진 Q counter set 때문일 수 있음 `[추론]`), rain 커널 로그에는 아무것도 없다. Nsight: 죽는 순간의 이벤트 없음(NVTX는 `ncclCommInitRank` 뒤 59–61 s의 `ncclCommShrink`까지 비어 있음), 멈춘 GPU 커널은 두 번 시도에도 기록되지 않았다. 해석 `[추론]`: `rp_cnp_handled`는 "내 패킷이 없어졌거나 실패한 QP에 닿고 있다"는 뜻이고, 보내는 rank만, 포트 단위로만 본다(어느 상대인지는 모름). 실제 혼잡에서도 오를 것이다. 안 본 것: CNP를 누가 내는지, 장비 전원 차단, 작은 put·read·atomic, 스위치가 낀 경우, 보내는 rank의 죽음, 프로세스 안에서만 읽히는 GIN Q counter set. 보고 `runs/death-signals-report.txt`, 로그 `runs/death-signals-*` |
| 2026-11-24 | 죽음 판정을 바꿈(결정: 통로는 비싸다. 카운터가 오르면 소켓을 본다. 보내는 rank만 알아도 된다. 잘못 구현한 것은 치운다). 앞 줄의 두 구현을 되돌림. 새 구현: host 오류 스레드가 `NCCL_GIN_ERROR_QUERY_SEC`(기본 1 s)마다 포트의 `rp_cnp_handled`를 읽고, 올랐으면 ring 이웃 둘의 소켓을 `recv(MSG_PEEK)`로 보아 닫혔고 **그 rank로 보낸 요청이 떠 있으면**(`gdakiOutstanding`, 검수에서 추가: 카운터는 혼잡으로도 오르고 정상 종료 때도 소켓은 닫히므로) 죽음으로 판정, 그 rank로 가는 QP만 ERR로 바꾼다(`gdakiPeerDied`). 소켓으로 보내는 것은 없다. 같이 넣은 것: `cq->hold`(host만 씀)와 `doca_gpu_verbs_qp_hold`, GPU의 두 폴링 진입점이 실패한 QP에서 hold가 켜져 있는 동안 기다림(복구의 바탕; 아직 재구성이 없어 host는 오류를 보면 바로 푼다). 5개 파일 +133 −20, 원본 대비 14개 파일 +541 −65. 시험: 장애 없음·잘못된 put(untimed, timed) 각 2회, rank 1 SIGKILL rank 4개 timed 3회·untimed 2회, 상대 생존 QP 오류(`inject`, `NCCL_IB_TIMEOUT=14`) 2회, `ring_exchange` 5회(예제를 새 헤더로 다시 빌드) | `[측정]` 죽이는 5회: 보내던 rank 0만 죽음 WARN 1줄, 죽은 뒤 약 0.5 s(rank 0 시계로 실패 시작 0.49–0.50 s, 오류 보고 1.00 s), timed flush는 그 뒤 전부 `ncclRemoteError`, untimed도 멈춤 없음(전에는 약 58 s). 죽음 오판 0회: 장애 없음·잘못된 put 6회(프로그램이 `ncclCommDestroy` 없이 끝나도), `inject` 2회(카운터는 오르지만 소켓이 열려 있음), `ring_exchange` 5회. 검수 전 구현(떠 있는 요청 조건 없음)에서는 같은 포트를 쓰는 rank 2도 rank 1을 죽음으로 판정했다(6회). 성능: `ring_exchange` 구성 1·2가 원본 대비 2–3% 느려졌다(n=5). 원인 확인과 수정은 다음 줄. 안 본 것: GPU가 실제로 hold에서 기다렸는지(간접 확인뿐), 보내는 rank의 죽음, 이웃이 아닌 rank의 죽음(판정 못 함), 혼잡한 망, GDRCopy 없는 구성, rank 1개. 로그 `runs/ginfault-cnp*`, `runs/ab-gin-20261124-204107` |
| 2026-11-24 | hold 검사의 비용 확인과 수정(결정: 추론을 측정으로 확인, 필요한 중복만 고침). `ab.sh gin 20`으로 변형마다 양쪽 전체 빌드: A 두 진입점에 검사, C 진입점은 HEAD 그대로(검사 없음), B 진입점 뒤에서 `-EIO`일 때만 cold 함수 호출, 최종 실패 경로에서만 cold 함수 호출. 최종 모양: 검사는 `doca_priv_gpu_dev_verbs_cq_held`(`__noinline__`) 하나에 있고, non-blocking 진입점은 `-EIO`일 때, blocking 폴링은 기존 실패 반환 다섯 곳에서 부른다. blocking 진입점은 HEAD와 같다. 두 진입점에 똑같이 있던 검사 두 줄이 이 함수로 합쳐졌다. 수정 뒤 커밋 `d56b15e`(앞 줄의 죽음 판정 포함, 5개 파일 +172 −28, 원본 대비 14개 파일 +573 −66). 그 뒤 재현: 장애 없음·잘못된 put(untimed, timed) 각 2회, rank 1 SIGKILL rank 4개 timed 3회 | `[측정]` us/batch 원본 대비(구성 1/2/3/4, 괄호는 원본 편차): A +2.31(0.14)/+1.97(4.37)/+0.26/+0.12, C +0.71(0.46)/+0.82(1.86)/+0.15/+0.30, B 2회 +0.33/+2.11·+2.36/+0.27·+0.05/+0.22, 최종 2회 +0.06·+0.06/+1.11·+0.47(3.17, 2.00)/+0.19·+0.02/−0.14·−0.22 %. 즉 검사 비용은 구성 1에서 약 1.6%(원본 편차의 열 배)였고 최종 모양에서 C와 구별되지 않는다. B가 구성 2를 못 고친 이유 `[측정: sm_70 SASS, put당 귀속은 추론]`: `wait_until_slot_available`이 put마다 blocking 폴링을 부르고 결과를 버리므로 HEAD에서는 컴파일러가 상태값을 없앤다. 진입점 뒤에 검사를 두면 put마다 비교와 분기가 생긴다. 재현: 결과 줄이 앞 줄과 같다(120/120, `0x13/0x88` WQE 20, timed는 flush 110회 실패), 죽이는 3회는 rank 0만 죽음 WARN 1줄, 멈춤 없음. 안 본 것: hold가 켜진 채 cold 함수에 실제로 들어갔는지, sm_80 SASS, hold 중 blocking 경로가 non-blocking 폴링을 돌리는 것의 영향(collapsed CQ의 `sq_wqe_pi` 사전 대기를 건너뜀; 재구성이 생기면 확인), 혼잡한 망. 로그 `runs/ab-gin-20261124-214653`(A), `-215608`(C), `-220533`·`-220809`(B), `-223757`·`-223941`(최종), `runs/ginfault-holdperf2-*`, `runs/ginfault-holdperf4-*` |
| 2026-11-24 | `d56b15e`의 독립 코드 검사(읽기 전용, 지적 7개)와 반영. 고친 것 셋(두 파일 +9 −5, 같은 커밋에 합쳐짐): (1번) `ncclCommGetAsyncError`가 CQ 이벤트를 스레드보다 먼저 가져가면 스레드가 hold를 풀 기회가 없어 GPU 폴링이 끝없이 기다릴 수 있었다 → hold 해제를 두 경로가 함께 쓰는 `ncclGinGdakiQueryLastErrorEvent` 안으로 옮김. (3번 일부) 스레드가 `sendComm`·`recvComm` 포인터 대신 소켓 번호 둘만 들고 있게 함(device communicator가 남은 채 communicator를 정리하면 collComm이 스레드보다 먼저 해제됨). (4번) hold 쓰기 뒤 `doca_internal_wc_store_fence`. 안 고친 것: 2번 `gdakiOutstanding`은 `sq_rsvd_index`와 `cqe_ci`를 비교하는데, counter·signal로 기다리는 application은 `cqe_ci`가 안 올라 일이 다 끝나도 '떠 있음'으로 보인다 → 정상 종료 + 혼잡이 겹치면 죽음 오판 가능 `[추론: 소스]`(혼잡 시험에서 확인할 것). 3번 나머지(스레드가 오류 보고 때 `collComm->nranks`를 읽는 것은 host 스레드 커밋부터 있던 것). 5번 종류별 non-blocking 폴링은 hold를 안 본다(호출하는 곳 없음). 6번 hold 중 blocking 대기가 non-blocking 폴링을 돌려 collapsed CQ의 사전 대기를 건너뛰고, EBUSY인 동안 hold를 다시 안 읽는다(재구성이 생길 때 고칠 것). 7번 단독 QP는 `qp_gpu_ro_h`가 없어 hold 불가. 독립 검사 제안: 재구성이 생길 때까지 hold를 켜지 않는 것(지금은 host가 항상 실패를 택하므로). 반영 뒤 재현: 장애 없음·잘못된 put 6회, rank 1 SIGKILL rank 4개 timed 3회·untimed 2회, `inject` 2회, `ring_exchange` 5회 | `[측정]` 결과 줄이 앞과 같다. 죽이는 5회는 rank 0만 죽음 WARN 1줄, 멈춤 0회, timed flush 실패 56–57회. 죽음 오판 0회(13회). us/batch 원본 대비 +0.07/+0.80/+0.37/−0.08 %(원본 편차 0.06/1.80/2.70/4.91, n=5). 1번의 경합 자체는 재현하지 않았다(코드 경로로만 확인). 원본 대비 14개 파일 +577 −66., 로그 `runs/ginfault-rev*`, `runs/ab-gin-20261124-225951` |
| 2026-11-25 | hold를 끔과 커밋 정리. (1) 재구성이 생길 때까지 `gdakiHold(ctx, true)`를 부르지 않는다(한 줄을 주석으로; flag, `doca_gpu_verbs_qp_hold`, cold 함수는 남음). host가 항상 실패를 택하는 지금은 hold가 오류를 늦추기만 하고, 풀지 못하면 GPU가 끝없이 기다리기 때문. 양쪽 라이브러리 빌드 뒤 재현: 장애 없음·잘못된 put 6회, rank 1 SIGKILL rank 4개 timed 3회·untimed 2회, `inject` 2회. (2) NCCL `recovery` 브랜치 기록 정리(작업 트리 파일은 건드리지 않음): `66b1e16`·`626dadb`·`37dd416`(넣었다 되돌림, 합이 0) 삭제, `a8c97b7`·`5e7f428`을 `07adc5b`에, `c55c444`와 (1)을 `39c9f3b`에 합침. 새 기록: `cf1e2ec`(#2480, 그대로), `3c0f8bd`(#2483, 옛 `07adc5b`), `0fd4724`(옛 `6c1d69b` + `5e7f428`의 주석 두 줄), `3116a5e`(옛 `9c52378`), `da35e25`(옛 `6669e46`), `d56b15e`(죽음 판정과 hold, 옛 `39c9f3b`). 이 표의 앞줄들에 적힌 옛 해시는 로컬 브랜치 `recovery-old-20261125`에 남아 있다 | `[측정]` (1) 결과 줄이 앞과 같다: 죽이는 5회는 rank 0만 죽음 WARN 1줄, 멈춤 0회, timed flush 실패 54–63회; 죽음 오판 0회(13회). 성능은 다시 재지 않음(GPU 쪽 코드는 그대로, host의 쓰기 한 번이 빠짐). (2) 새 head의 tree가 옛 head + (1)과 같음(`git diff` 0바이트), 원본 대비 14개 파일 +577 −66. 커밋별 빌드는 확인하지 않음. 로그 `runs/ginfault-nohold*` |
| 2026-11-25 | 카운터 잡음 속의 죽음 판정(결정: 혼잡한 망에서의 동작 확인). 라이브러리는 그대로, `repro/gin_fault.cu`에 `WAITCTR`(flush 대신 counter를 기다려 주 CQ를 폴링하지 않음), `HOLD_MS`(rank 0이 다른 rank가 끝난 뒤에도 살아 있음), 끝날 때 `sq_rsvd_index`·`cqe_ci`를 찍는 `QPIDX` 줄을 추가(+36 −5). 잡음원: 같은 두 장비에서 따로 도는 `inject` job(상대는 살아 있고 QP만 ERR; 75회). 실제 부하(`ib_write_bw`·`ib_send_bw`, QP 8–32개, 양방향 약 196 Gb/s, 20 s × 3)도 한 번 걸어 봄. 조건마다 3회 이상 | `[측정]` **잡음원**: `inject` job 하나가 rain 포트의 `rp_cnp_handled`를 약 3 s 동안 +9–16 올린다(연달아 돌리면 평균 1.4회/s). 실제 부하는 카운터를 올리지 않았다(+0; ECN·CNP 카운터 모두 그대로, pause frame만 +4. 이 직결 링크는 혼잡을 ECN이 아니라 pause로 처리한다 `[추론]`). **오판 없음**: 장애 없는 `gin_fault` rank 2개·4개 각 6회(잡음), `ring_exchange` 13회(잡음), 잡음 job 자체 75회, flush로 기다리는 프로그램에서 이웃이 정상 종료(3회; 번호 240/240). **오판 있음**: counter로 기다리는 프로그램(`WAITCTR=1`)에서 이웃이 정상 종료한 뒤 카운터가 오르면 3회 중 3회 `remoteRank=1 is dead`(종료 뒤 첫 상승 때, hold 2–4 s 지점). 그때 번호는 `sq_rsvd_index`=240, `cqe_ci`=112: `cqe_ci`는 새 예약이 자리를 필요로 할 때만 전진하므로 이 경로에서는 차이가 min(보낸 수, SQ 128칸)으로 남아 닫히지 않는다 `[측정: 번호, 추론: 이유]`. 잡음이 없으면 0회(3회). **실제 죽음 + 잡음**: rank 4개 6회 모두 rank 0만 WARN 1줄, 살아 있는 rank에 대한 판정 0회, flush가 멈춘 시간 0.52–0.72 s(잡음 없음 0.49–0.51 s; 판정은 둘 다 스레드의 다음 tick). 결론: 소켓이 열려 있는 동안은 잡음에 안전하고 실제 죽음도 잡지만, "이웃의 정상 종료 + flush를 쓰지 않는 대기 + 다른 이유의 카운터 상승"이 겹치면 오판한다. 검사 지적 2번이 맞았다. 해결 방안은 4.2절. 안 본 것: 스위치가 있어 ECN이 표시되는 망, sunny 포트의 잡음, rank 4개에서의 오판 조건, `ncclCommDestroy`로 끝나는 경우, signal·barrier 대기(코드상 같은 모양일 것 `[추론]`), 오판 뒤 남은 rank의 동작. 로그 `runs/cnpnoise-*`, `runs/ginfault-q[1-4]*`, `runs/ab-gin-20261125-00*` |
| 2026-11-25 | 오판 수정(결정: NIC의 PSN으로 본다). `gdakiOutstanding`이 그 rank로 가는 주 QP를 `doca_gpu_verbs_query_last_error`로 조회해 ACK를 못 받은 PSN 수 `(next_send_psn − last_acked_psn − 1) & 0xffffff`를 돌려준다(새 필드 `unacked_psns`, 새 getter `doca_verbs_qp_attr_get_send_psns`). 우리 쪽 번호 비교와 GDRCopy 의존은 없앰. 죽음 WARN에 그 수를 찍는다. 독립 코드 검사(지적 5개, 계산식은 맞다고 확인) 반영: 스레드가 읽는 rank 수를 context에 보관(`collComm`이 먼저 해제될 수 있음), 이미 실패한 QP는 세지 않음(실패 때의 차이가 남아 있어 상대에 대해 아무것도 말해 주지 않음), 필드 이름을 PSN으로(read는 응답 패킷의 PSN도 포함). 6개 파일 +57 −21, 중복 없음(QUERY_QP는 한 곳). 양쪽 라이브러리 빌드 뒤 시험 | `[측정]` **PSN**(rank 0 → rank 1의 주 QP, next/acked): 연결 직후 0/0xffffff(차이 0), put 120개가 끝난 뒤 600/599(0), 상대 정상 종료 뒤 flush·counter 대기 모두 600/599(0), 전송 도중 SIGKILL된 뒤 판정 시점 1105/1087·1139/1121(17 = 64 KiB put 하나와 signal). **오판**: 어제 3회 중 3회 틀린 조건(정상 종료 + counter 대기 + 잡음, hold 중 카운터 +27–30)에서 0회(손질 전 3회, 손질 뒤 3회). flush 경로와 잡음 없는 경우 포함 정상 종료 24회 모두 0회. 잡음 job 자체 70여 회 0회. **실제 죽음**: rank 4개, 손질 뒤 8회(잡음 없음 timed 3·untimed 2, 잡음 3) 모두 rank 0만 WARN 1줄(`17 PSNs ... not acknowledged`, 16 KiB에서는 5), 멈춤 0회, flush가 멈춘 시간 0.49–0.72 s. 기존 시험: 장애 없음·잘못된 put 6회와 `inject` 2회 결과 줄 그대로, 죽음 WARN 0줄. `ring_exchange` us/batch 원본 대비 +0.03/+1.14/+0.19/+0.39 %(원본 편차 0.13/9.02/2.87/4.36, n=5). **counter 대기 중의 죽음**(고치지 않음): 죽음은 8회 모두 판정되지만 `waitCounter`는 counter 값만 보므로 판정으로 풀리지 않고 자기 제한 시간(약 1 s씩)으로만 끝난다. 제한 시간이 없으면 멈춘다. 안 본 것: 판정 경로의 조회 시간, read·atomic만 떠 있는 경우의 PSN, DOCA SDK 모드(getter 미지원 → 판정 없음), 정상 종료 중 ACK가 오는 순간의 조회(순간값 하나로 판정, 독립 검사 2번), signal·barrier 대기. 로그 `runs/ginfault-psn-*`, `runs/psnfix-[abc]-*`, `runs/ginfault-psnfix*`, `runs/ab-gin-20261125-07*` |
