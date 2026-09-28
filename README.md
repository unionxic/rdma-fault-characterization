# RDMA 장애 특성화와 복구

RDMA RC QP의 장애를 오류 CQE, vendor_err, HW 카운터로 실측해 분류하고, 가장 작은 단위로 복구한다. 같은 틀을 NCCL과 GPU-initiated RDMA(NCCL GIN, NVSHMEM IBGDA)로 넓혔다.

## 테스트베드

| 노드 | 역할 | NIC | GPU |
| --- | --- | --- | --- |
| rain | requester, rank 0 | ConnectX-6 VPI, fw 20.43.4100 (`mlx5_1`) | Quadro RTX 5000 (sm_75) |
| sunny | responder, rank 1 | ConnectX-6 VPI, fw 20.43.4100 (`mlx5_0`) | RTX A4000 (sm_86) |

100 GbE RoCE v2 직결이다. 초기 연구(`experiments/`, `docs/`)는 다른 클러스터(ConnectX-5/6, GPU 없음)에서 했다. 관리망 주소는 문서용 주소(192.0.2.x)로 바꿔 두었다.

## 핵심 결과

**장애 분류와 복구 (CPU verbs)**
- 10가지 장애를 오류 코드만으로 6개, vendor_err를 더해 8개, 상대 프로세스 생존 여부까지 더해 9개로 구분한다.
- 해당 QP만 재설정해 2.8 ms에 복구한다(드라이버 재적재는 7.9 s). 다른 연결에는 영향이 없다.
- RETRY_EXC 감지 3.7 s는 firmware의 적응형 재전송과 두 배 간격의 timeout 때문이다. NCCL 기본값(timeout 20)에서는 59.8 s이고, floor를 풀면 9.5 ms다.
- 죽은 상대가 0x81 또는 0x88로 보이는 차이는 커널이 verbs 객체를 지우는 순서에서 나온다.

**NCCL 2.23 (`net_ib.cc` 패치)**
- 요청이 여러 개 비행 중이어도 복구한다. 기본 설정에서 30/30, 약 2.2 ms. 주소 재구성 fault도 15/15 복구했다(원본은 6/6 실패).
- fault 한 번에 제자리 복구는 +2 ms, 재시작은 +1.1 s.
- 관리망 장애를 상대 사망으로 오판해 멀쩡한 작업을 죽이지 않는다(FIN만 사망으로 판정).

**GPU-initiated RDMA (NCCL GIN, NVSHMEM IBGDA)**
- NVSHMEM CPU 프록시 버그: 송신 인덱스를 doorbell record의 엉뚱한 칸에 써서 에러 CQE가 사라진다. 고치면 0/35에서 21/21. 3.5.x부터 3.8.0까지의 회귀다.
- GPU 분류기로 실패를 성공으로 보고하던 문제를 없앴고, 호스트 감지는 9.4 s에서 ms 단위로 줄었다.
- GDAKI와 NVSHMEM 모두 로컬 QP 에러와 상대 QP 에러는 복구하고 나머지는 거절한다. N=30 재실행에서 모든 셀이 100 %였다.
- 투명 복구 1단계(GIN): 응용 수정 없이 95/95 복구. 비행 중 op 1개까지이고, 켜면 4 KiB 지연이 60 % 늘어난다.
- NVSHMEM FT v2.2: ring CQ로 원인 CQE를 90/90 보존하고, 실패한 fetch AMO가 이전 값을 돌려주던 버그를 고쳤다.

## 구성

| 경로 | 내용 |
| --- | --- |
| `harness/` | 장애 주입과 측정 장치 (C) |
| `harness/nccl-integration/` | NCCL 패치(`stage2/net_ib_stage2.diff`), 시험, 완료 시간 비교 |
| `harness/gpu-initiated/` | GIN, NVSHMEM 패치와 드라이버, 설계 문서 (`RESULTS.md`가 종합) |
| `harness/ack_timeout/` | RETRY_EXC 감지 시간 분석 |
| `harness/fingerprint_teardown/` | 죽은 상대의 오류 코드가 갈리는 원인 분석 |
| `experiments/`, `docs/` | 초기 연구의 실험 코드와 이론 문서 |

## 한계

- 노드 한 쌍, NIC 한 종류에서만 측정했다.
- 진짜 link flap과 GPU 스택의 실제 경로 fault는 시험하지 않았다.
- GPU 투명 복구는 비행 중 op 1개까지다.
- 원시 로그와 결과 파일은 이 저장소에 올리지 않았다.
