# 09. GPU×RDMA 통합 계획 (2단계)

> 상태: 계획 + 구현 착수(2026-09-17). 이 문서는 설계·범위이고, 실측·패치 결과는
> `harness/nccl-integration/`에 누적된다.

## 9.1 배경과 전제 변화

1단계에서 CQE(`ibv_wc_status`+`vendor_err`) 기반 분류와 QP recovery를 CPU RDMA에서
범용 실증했다(통합 장치 `harness/`). 2단계 목표는 이 분류·복구를 **GPU 통신 경로**에
넣고, 실제 분산 통신 런타임에서 fault가 났을 때 completion time에 미치는 영향을
측정하는 것이다.

전제 변화: 원 클러스터(224/225)와 달리 현 클러스터는 **두 노드 모두 GPU가 있다.**

| 노드 | GPU | compute cap | RoCE dev | CUDA |
|---|---|---|---|---|
| rain (requester) | Quadro RTX 5000 16GB | sm_75 | mlx5_1 / ens4f1np1 / 30.0.0.3 | 12.8 |
| sunny (responder) | RTX A4000 | sm_86 | mlx5_0 / enp23s0f0np0 / 30.0.0.4 | 12.8 |

즉 문서 `01_overview.md` 1.6절이 "GPU 노드 확보 후로 미룸"이라 했던 NCCL end-to-end
경로가 이제 가능하다.

## 9.2 통합 지점: NCCL 내부 코드 (외부 프로그램 아님)

핵심 방침(사용자 지시): **외부 wrapper/daemon이 아니라 NCCL 자체 코드(in-tree)를
수정**하는 방안을 최우선으로 한다. 근거는 1단계 결론(`theory/07`, `theory/01` 1.5절)과
일치한다 — CQE/vendor_err는 QP를 소유한 user-space 런타임만 볼 수 있고(CQ가 그
프로세스의 user-space mmap), 분류+복구가 가능한 유일한 자리는 통신 런타임이다.
데몬·드라이버는 cross-process coarse 관측까지만 가능하다.

- **통합 대상**: NCCL의 IB transport `src/transport/net_ib.cc`.
- **정확한 지점**: CPU proxy thread가 `ibv_poll_cq`로 completion을 확인하는 경로
  (`ncclIbTest`/completion 처리 함수). 현재는 `wc.status != IBV_WC_SUCCESS`이면
  `ncclRemoteError`/`ncclInternalError`를 반환해 communicator를 통째로 실패시킨다.
- **framing 조율**(`theory/07` 7.5절): "GPU-initiated 감지"는 proxy 현실에 맞춰
  감지=CPU proxy `ibv_poll_cq`, 분류=`vendor_err` 분기 추가, 복구=QP ops로 매핑된다.
  GPU가 CQE를 직접 읽는 GPUDirect Async는 범위 밖(특수 경로).

## 9.3 구현 범위 (in-tree 패치)

1. **분류 삽입**: 실패 completion에서 `classify(status, vendor_err)`(harness
   `common/probe.c`에서 이식)를 호출해 cause/action/auto_recoverable을
   NCCL 로깅(INFO/WARN)으로 남긴다. status+vendor_err도 함께 찍는다.
2. **복구 삽입**: auto_recoverable(NAK 계열: REM_ACCESS 0x88 / REM_INV_REQ 0x8a /
   RNR 0x87 / WR_FLUSH 0xf5)일 때, communicator를 죽이는 대신 IB transport 내부에서
   QP-level recovery/reconnect(ERR→RESET→INIT→RTR→RTS, 필요 시 재-handshake)를
   시도하고 실패한 WR을 재전송한다.
3. **비-복구 분기**: RETRY_EXC 0x81은 liveness로 하위 분류(`server_qp_err`는 재접속
   시도, `proc_kill`/`link_down`은 상위로 에스컬레이션). 1단계 검증대로 RDMA
   카운터로는 원인이 안 갈리므로 liveness(또는 NCCL bootstrap TCP 상태)를 쓴다.
4. **게이팅**: `NCCL_RDMA_FAULT_RECOVERY=1` 환경변수로 켜고, 꺼짐이 기본(기존 동작
   보존). 패치는 최소·주석화·경계 명확.

## 9.4 평가 (마이크로 + end-to-end)

| 축 | 측정 | 비교 |
|---|---|---|
| 마이크로 | 단일 QP fault→감지→복구 시간 (NCCL 내부 로깅) | harness 수치와 대조 |
| end-to-end | 2노드 `all_reduce_perf` completion time | fault 주입 시 (a) 패치 off=communicator 실패 vs (b) 패치 on=복구 후 지속 |

- baseline: `nccl-tests`의 `all_reduce_perf`, 1 GPU/노드, RoCE 경유
  (`NCCL_IB_HCA`로 rain mlx5_1 / sunny mlx5_0, `NCCL_IB_GID_INDEX=3`,
  `NCCL_SOCKET_IFNAME`은 bootstrap용).
- fault 주입: 실행 중 peer rank kill(→0x81 proc_kill), 또는 QP→ERR 유도.
  1단계 fault catalog를 그대로 재사용.

## 9.5 리스크와 열린 항목

- NCCL IB transport는 에러 시 communicator 전체를 실패시키는 설계라, QP만 국소
  복구해 통신을 잇는 것이 침습적일 수 있다. 재전송·PSN 재동기의 정합성이 관건.
- 버전 정합: CUDA 12.8과 맞는 NCCL 태그(v2.21+ 예상), gencode sm_75+sm_86.
- rkey/lkey·MR 수명: NCCL의 MR 등록 방식과 우리 recovery의 rkey refresh 조율.
- GPUDirect Async(GPU가 CQ 직접 접근)는 2단계에서도 범위 밖으로 명시.
- 실측 GPU/root 의존 항목은 구현 에이전트 결과에서 확정한다.

## 9.6 단계

1. NCCL + nccl-tests 빌드, baseline all_reduce over RoCE 확인.
2. net_ib 완료 경로에 분류+로깅 삽입(패치 최소).
3. QP-level 복구/재전송 삽입, 게이팅.
4. fault 주입 end-to-end 평가(off vs on completion time).
