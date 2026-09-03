# CQE와 에러 식별

> [이론 문서 인덱스](README.md)

RDMA 작업의 성공/실패는 Completion Queue Entry(CQE)에 기록된다. 애플리케이션은 CQ를 polling해서 CQE를 읽고, 그 안의 필드로 무슨 일이 일어났는지 판단한다. 이 절은 CQE에서 에러 식별에 쓰이는 두 필드 — `ibv_wc_status`와 `vendor_err` — 의 구조, 그 둘이 어떻게 채워지는지(운반 메커니즘), 그리고 왜 같은 status가 서로 다른 원인에서 나오는지를 정리한다.

실험 환경은 모든 시나리오 공통으로 클라이언트(225, ConnectX-6, fw 20.40.1000) → 서버(224, ConnectX-5, fw 16.35.8002), 100Gbps RoCEv2다. 각 시나리오는 N=10 반복, 결과는 100% deterministic이었다.

### 3.1 두 필드: 표준 status와 firmware syndrome

CQE에서 에러 식별에 쓰는 필드는 두 개다. 둘은 의미와 출처가 완전히 다르다.

| 필드 | 정체 | 정의 주체 | 값의 성격 | 안정성 |
|---|---|---|---|---|
| `ibv_wc_status` | IBA 표준 상태 코드 | InfiniBand Architecture spec | 에러의 "종류"(category) | driver가 결정 → mlx5 driver 전반 안정 |
| `vendor_err` | NIC firmware raw syndrome | NIC 제조사(Mellanox) | NIC이 감지 시점에 본 raw 값 | firmware artifact(fw/세대 의존, 단 mlx5 계열 공유 정황) |

`ibv_wc_status`는 IBA 규격이 정의한 표준 enum이다. 성공이면 `IBV_WC_SUCCESS`(0), 실패면 spec상 24종 중 하나다. 그중 mlx5 환경에서 실제 발생 가능한 것은 14종으로 분류했고, 이 실험에서 다룬 status는 다음 6종이다.

| ibv_wc_status | 의미 |
|---|---|
| LOC_PROT_ERR | 로컬 메모리 보호 위반 (내 NIC이 내 메모리 접근 실패) |
| WR_FLUSH_ERR | ERR 상태 QP에 post되어 flush됨 |
| REM_INV_REQ_ERR | 서버가 "Invalid Request" NAK 응답 |
| REM_ACCESS_ERR | 서버가 "Remote Access Error" NAK 응답 |
| RNR_RETRY_EXC_ERR | RNR(Receiver Not Ready) 재시도 소진 |
| RETRY_EXC_ERR | transport 재시도 소진 (ACK 미수신) |

`vendor_err`는 규격에 없는, 제조사가 자유롭게 채우는 값이다. mlx5에서는 NIC hardware가 에러를 감지한 시점에 관찰한 raw syndrome이다. 즉 "NIC이 내부적으로 무엇을 보았는가"를 그대로 돌려주는 값이다. IBA spec 자체가 `vendor_err`를 vendor-defined로 열어두었기 때문에(libibverbs man, RDMAmojo) 의미는 벤더마다 다르고, mlx5의 `vendor_err_synd` 인코딩은 공식 문서가 없다 — 이 값들은 실험 재현으로 알아낸 것이다.

### 3.2 같은 status가 다른 원인에서 나오는 이유

핵심 문제는 `ibv_wc_status`의 분류가 거칠다는 것이다. IBA spec은 내부 원인이 다른 여러 상황을 하나의 status로 묶는다. 두 대표 사례를 보자.

LOC_PROT_ERR는 "내 NIC이 내 로컬 메모리에 접근하려다 실패했다"는 공통점만 있는 세 가지 원인을 한 코드로 묶는다. 이 셋은 detection 경로도, 패킷이 wire에 나가는지 여부도 다르다.

| 원인(의미명) | vendor_err | 패킷이 wire에 나가나 | detection 시점 |
|---|---|---|---|
| SGE length가 MR 크기 초과 | 0x53 | 안 나감 | 패킷 생성 전 로컬 검증 |
| invalid lkey (존재하지 않는 lkey) | 0x52 | 안 나감 | 패킷 생성 전 로컬 검증 |
| MR 권한 위반 (LOCAL_WRITE 없는 MR에 READ 응답 기록) | 0x33 | 나감(서버 왕복 후) | 원격 응답 데이터를 로컬 MR에 쓰는 시점 |

세 경우 모두 status는 LOC_PROT_ERR로 동일하다. status만 보면 구분이 불가능하다. 그러나 `vendor_err`는 0x53 / 0x52 / 0x33으로 셋을 구분한다. MR 권한 위반(0x33)은 실측에서 서버 counter `rx_read_requests +1`이 함께 관찰되어, "로컬" 에러임에도 RDMA READ 요청이 서버를 왕복한 뒤 응답 데이터를 로컬 MR에 쓰는 시점에 발생한다는 것이 확인된다. 이것이 vendor_err가 status를 "세분화"하는 실제 정보를 담는다는 직접 증거다.

반대 사례가 RETRY_EXC_ERR다. 이것은 "transport 재시도를 다 소진했다"는 뜻이고, 다음 상황들에서 나온다.

| 원인(의미명) | 클라이언트 NIC이 본 것 | vendor_err | 실측 여부 |
|---|---|---|---|
| 서버 QP가 ERR 상태로 전환 | "보냈는데 ACK가 안 옴" | 0x81 | 실측(N=10) |
| 서버 프로세스 kill (QP 리소스 해제) | "보냈는데 ACK가 안 옴" | 0x81 | 실측(N=10) |
| 네트워크 단절 (패킷 미도달) | "보냈는데 ACK가 안 옴" | 0x81 (추론) | 미실측 |

여기서는 vendor_err가 셋을 구분하지 못하고 모두 0x81이다. 단, 세 번째 "네트워크 단절"은 이 실험에서 직접 재현하지 못했다 — `ip link set down`이 kernel bypass 때문에 RDMA data path를 막지 못해 link down 시나리오 재현에 실패했다(물리 케이블 분리나 스위치 포트 차단이 필요). 따라서 네트워크 단절도 vendor_err 0x81로 동일하리라는 것은 실측이 아니라 추론이다. 근거는 클라이언트 NIC의 인식 모델이다: 서버 QP ERR / 프로세스 kill / 네트워크 단절 모두 클라이언트 NIC 관점에서는 "패킷을 보냈는데 ACK가 안 왔다"로 완전히 동일하다 — NIC 자체가 원인을 모르므로 syndrome도 같을 수밖에 없다. vendor_err의 0x81 수렴은 vendor_err의 한계가 아니라 NIC의 인식 한계를 그대로 반영한 것이다. vendor_err는 "NIC이 본 것"을 충실히 돌려줄 뿐, NIC이 못 본 것을 만들어내지는 않는다.

실측한 두 원인(서버 QP ERR, 프로세스 kill)은 sysfs counter signature까지 100% 동일했고(local_ack_timeout_err~+6, req_transport_retries_exceeded~+1, roce_adp_retrans~+8), 실제 retry timeout latency도 약 3.7s로 동일했다. 둘의 구분은 오직 ethtool traffic counter(`tx_vport_unicast_packets`)로만 가능했다: 서버 프로세스가 살아 있는 서버 QP ERR는 TCP 정상 종료(FIN)로 패킷 12–13개, 프로세스 kill(`kill -9`)은 TCP RST로 패킷 8개로 나타났다. 즉 RDMA-level counter는 둘을 못 가르고, non-RDMA TCP 종료 패턴만이 둘을 가른다.

두 사례의 대비가 vendor_err의 성격을 정의한다.

| | LOC_PROT_ERR 3원인 | RETRY_EXC_ERR 원인들 |
|---|---|---|
| 에러 발생 위치 | 로컬 NIC 내부 검증(원인이 NIC에 보임) | 원격/네트워크(원인이 NIC에 안 보임) |
| vendor_err 구분력 | 있음 (0x53/0x52/0x33) | 없음 (모두 0x81) |
| 추가 식별 수단 필요 | 불필요 | 필요(counter, ethtool traffic 등) |

### 3.3 vendor_err 운반 메커니즘 (코드 확정)

vendor_err가 "firmware raw 그대로"라는 주장은 driver 소스에서 확정된다. CQE 구조체 안에서 status용 바이트와 vendor용 바이트는 애초에 별개다.

CQE 안에는 두 개의 별도 바이트가 있다(rdma-core `providers/mlx5/device.h:813-814`).

- `syndrome` 바이트: `ibv_wc_status` 결정에 쓰임
- `vendor_err_synd` 바이트: `vendor_err`로 전달됨

이 둘이 채워지는 경로가 다르다.

```
firmware가 CQE에 두 syndrome 바이트를 씀
        │
        ├─ syndrome 바이트
        │     ↓  driver switch(syndrome) → ibv_wc_status   (커널 mlx5_ib/cq.c:288-337)
        │     ibv_wc_status (가공/매핑됨)
        │
        └─ vendor_err_synd 바이트
              ↓  가공 없이 그대로 복사 (커널 mlx5_ib/cq.c:339, rdma-core providers/mlx5/cq.c)
              vendor_err (firmware raw)
```

핵심:

- `status`: driver의 switch 문이 firmware syndrome을 `ibv_wc_status`로 매핑한다. 여러 syndrome이 하나의 status로 수렴할 수 있다(위 LOC_PROT_ERR 3원인이 그 예). 매핑 로직이 mlx5 driver에 박혀 있으므로 status 분류는 firmware 버전과 무관하게 안정적이다.
- `vendor_err`: driver가 `cqe->vendor_err_synd`를 가공 0으로 패스스루한다. 커널(mlx5_ib/cq.c)과 user-space(rdma-core providers/mlx5/cq.c) 양쪽 모두 변형하지 않는다. 따라서 애플리케이션이 보는 값은 firmware가 쓴 raw syndrome 그대로다.

예외 하나: 이 실험에 등장한 8개 distinct vendor_err hex(0x53 / 0x52 / 0x33 / 0xf5 / 0x8a / 0x88 / 0x87 / 0x81; 9개 시나리오 중 0x88은 invalid rkey와 주소 범위 초과 두 시나리오가 공유) 중 7개(0x53 / 0x52 / 0x33 / 0x8a / 0x88 / 0x87 / 0x81)는 firmware-raw 경로다. WR_FLUSH_ERR의 0xf5만은 SW-flush 경로(ERR 상태 QP에 post → driver가 소프트웨어 레벨에서 flush, rdma-core `providers/mlx5/cq.c:419/600`)에서 driver가 채우는 상수일 가능성이 있다. 즉 0xf5는 firmware가 아니라 driver가 정한 값일 수 있다(일반 flush 경로에서는 firmware raw로 추정). 다만 0xf5에 해당하는 driver 상수(`MLX5_CQE_SYNDROME_WR_FLUSH_ERR`)의 실제 값과 매핑은 서버 헤더 `<linux/mlx5/cq.h>`에서 직접 확인이 필요하다 [TODO: 확인]. 위 커널 라인 번호(288-337, 339)와 device.h 라인 번호(813-814)는 memory 기록 기반이므로, 단정하기 전 서버에 설치된 커널 버전의 소스와 재대조하는 것이 안전하다 [TODO: 확인]. (코드 라인·증거의 상세는 부록 A 참조.)

### 3.4 2층 구조의 의미

위 메커니즘이 만들어내는 것은 robustness가 다른 2층 식별 체계다.

| 층 | 필드 | robustness 근거 | 활용 방식 |
|---|---|---|---|
| 상층(coarse) | ibv_wc_status | driver가 매핑 결정 → mlx5 driver 안정, 14종 분류 신뢰 | 에러 "종류" 1차 분기 |
| 하층(fine) | vendor_err | firmware artifact, 그러나 mlx5 세대 간 동일 실측됨(LOC_PROT 3종) | status를 세분화하는 2차 분기 |

상층(`ibv_wc_status`)은 driver가 결정하므로 어떤 mlx5 NIC에서든 일관된 분류를 보장한다 — 여기에 의존하는 로직은 portable하다. 하층(`vendor_err`)은 본질적으로 firmware가 만든 값이므로 이론상 firmware/세대에 종속될 수 있지만, swap 실측(2026-06-02, N=10)에서 CX-5(224, fw 16.35.8002)와 CX-6(225, fw 20.40.1000)이 LOC_PROT 3종(0x53/0x52/0x33)에서 100% 동일했다. 여기서 swap이란 클라이언트(requester)와 서버(responder) NIC을 물리적으로 맞바꿔 같은 시나리오를 재실행한 것을 말한다. 원격 NAK(0x8a/0x88)도 동일하게 관찰됐으나, swap 시 requester와 responder를 동시에 바꿔(req+resp confounded) requester-only 효과로 분리하지 못했으므로 LOC_PROT 3종보다 약한 증거다. 정리하면 mlx5 계열은 syndrome 인코딩을 공유하며, requester-side로 깨끗하게 검증된 LOC_PROT 3종은 적어도 CX-5↔CX-6 범위에서 stable하다. (벤더 간 일반화 — EFA/irdma/bnxt_re/cxgb4는 각자 독립 enum — 와 CX-7 검증은 6절에서 다룬다.)

이 2층 구조가 실용적으로 의미하는 바는 다음과 같다. NCCL/UCX/SPDK 같은 런타임은 `ibv_wc_status`만으로 분기하고 `vendor_err`는 로그에만 찍는다(런타임 분기에 미사용). 그러나 위 분석은 vendor_err가 LOC_PROT_ERR 하나를 세 원인으로 가르는 실제 식별 정보를 담고 있음을 보여준다. status로 "메모리 보호 위반"임을 알고, vendor_err로 "SGE 초과인지 lkey 오류인지 권한 위반인지"를 가르는 — coarse-to-fine 2단계 분류가 단일 CQE만으로 가능하다. 다만 RETRY_EXC_ERR처럼 NIC이 원인을 못 보는 경우(vendor_err 0x81 동일)에는 이 2층만으로는 부족하고, counter signature나 ethtool traffic 같은 외부 관측을 추가로 동원해야 한다(5절).
