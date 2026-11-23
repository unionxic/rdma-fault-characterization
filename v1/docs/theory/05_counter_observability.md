# counter signature와 관측성

> [이론 문서 인덱스](README.md)

이 절은 "CQE status만으로 RDMA 에러의 근본 원인을 구분할 수 있는가"라는 질문에서 출발한다. ibv_wc_status는 IBA가 정의한 완료 상태값일 뿐이라 서로 다른 fault가 같은 status로 합쳐진다. 예컨대 SGE length 초과, invalid lkey, MR 권한 위반은 모두 LOC_PROT_ERR 하나로 보고되고, invalid rkey와 주소 범위 초과는 REM_ACCESS_ERR로, 서버 QP ERR와 프로세스 kill은 RETRY_EXC_ERR로 합쳐진다. 따라서 status 위에 무엇을 더 관측하면 원인이 분리되는지를 알아내기 위해, NIC이 노출하는 counter 계층 전부를 전수조사했다.

조사 대상은 세 계층이다.

| Counter source | 위치 | 개수 | 성격 |
|---|---|---|---|
| sysfs `hw_counters` | `/sys/.../<dev>/ports/1/hw_counters` | 20 | RDMA protocol counter |
| `ethtool -S` | netdev | 2,394 | Ethernet/MAC traffic·error counter |
| NIC register (mlxreg, root) | PPCNT/MPCNT/MISC | 169 | firmware/PHY/PCIe register |

방법은 동일하다. 각 fault scenario에서 fault inject 직전과 직후 counter snapshot을 찍어 그 차이(delta)를 측정하고, "어느 fault가 어느 counter를 얼마나 올리는가"를 그 fault의 counter signature로 정의한다. 그런 다음 counter source를 하나씩 더해 가며 10개 scenario 중 몇 개가 서로 다른 신호 조합(오류 코드와 counter signature)을 갖는지(구별되는 조합 수)를 센다.

### 5.1 실험 셋업과 deterministic 여부

| 항목 | 내용 |
|---|---|
| Client (225) | ConnectX-6 (MT28908), firmware 20.40.1000, counter device `rocep1s0f0` |
| Server (224) | ConnectX-5 (MT27800), firmware 16.35.8002, counter device `mlx5_0` |
| Link | 100 Gbps RoCE v2, heterogeneous NIC pair (CX-6 ↔ CX-5) |
| Traffic policy | single in-flight WR (fault inject 시점 pending WR 1개) |
| 빠른 에러 N | 100 (8종: SGE length 초과 / invalid lkey / MR 권한 위반 / WR_FLUSH_ERR / REMOTE_WRITE 권한 없음 / invalid rkey / recv buffer 부족 / 주소 범위 초과) |
| timeout 에러 N | 30 (서버 QP ERR / 프로세스 kill) |
| ethtool·register | N=3 |

서로 다른 NIC 세대(CX-6 ↔ CX-5) 사이에서도 counter signature는 흔들리지 않는다. 빠른 에러 N=100, timeout 에러 N=30(2026-06-04 재측정) 전 trial에서 counter delta·vendor_err·status가 100% deterministic이다.

단, detection latency만 host 환경에 의존하는 bimodal jitter를 보인다. NAK 계열(REMOTE_WRITE 권한 없음·invalid rkey·주소 범위 초과)은 약 0.5 ms와 약 1.6 ms 두 모드를 오가며(두 모드 차 약 1 ms로 일정, std 580–760 us), busy-poll(`poll_cq_block`) 도중 OS scheduler가 CPU를 양보해 생기는 실행 내 phase shift로 추정된다(warmup이 아니라 실행마다 빠른 쪽이 바뀜). 즉 latency는 분류 신호로 부적합하고, deterministic한 vendor_err/counter가 CQE 기반 분류의 근거가 된다. (latency 자체 분석은 experiments 문서의 "6. Latency 분포 분석". 여기서는 분류 신호로서의 적격성만 다룬다.)

### 5.2 Counter signature 표 (sysfs hw_counters)

각 scenario에서 non-zero delta만 표시한다. 컬럼은 시나리오 의미명이다(REM_INV = REMOTE_WRITE 권한 없음, RNR = recv buffer 부족, QP ERR = 서버 QP ERR, kill = 프로세스 kill, addr = 주소 범위 초과).

Client-side:

| Counter | SGE length | lkey | 권한 | WR_FLUSH | REM_INV | rkey | RNR | QP ERR | kill | addr |
|---|---|---|---|---|---|---|---|---|---|---|
| req_cqe_error | +1 | +1 | +1 | +1 | +1 | +1 | +1 | +1 | +1 | +1 |
| req_remote_invalid_request | | | | | +1 | | | | | |
| req_remote_access_errors | | | | | | +1 | | | | +1 |
| rnr_nak_retry_err | | | | | | | +1 | | | |
| req_rnr_retries_exceeded | | | | | | | +1 | | | |
| local_ack_timeout_err | | | | | | | | +6 | +6 | |
| req_transport_retries_exceeded | | | | | | | | +1 | +1 | |
| roce_adp_retrans | | | | | | | | +8 | +8 | |

Server-side:

| Counter | SGE length | lkey | 권한 | WR_FLUSH | REM_INV | rkey | RNR | QP ERR | kill | addr |
|---|---|---|---|---|---|---|---|---|---|---|
| rx_read_requests | | | +1 | | | | | | | |
| rx_write_requests | | | | | | +1 | | | | +1 |
| out_of_buffer | | | | | | | +1 | | | |

server-side error counter(resp_cqe_error, resp_remote_access_errors 등)는 어떤 scenario에서도 0이다. server가 올리는 유일한 변화는 "정상 request 수신" counter(MR 권한 위반은 RDMA READ라 rx_read_requests, invalid rkey·주소 범위 초과는 WRITE라 rx_write_requests, recv buffer 부족은 out_of_buffer)뿐이다.

### 5.3 Resolution: 무엇을 더 보면 원인이 갈리는가

counter source를 하나씩 추가하며 10개 scenario 중 몇 개가 서로 구별되는지(구별되는 조합 수)를 측정했다. 출발점인 CQE status only(ibv_wc_status)에서는 LOC_PROT_ERR 3종(SGE length / invalid lkey / MR 권한 위반), REM_ACCESS_ERR 2종(invalid rkey / 주소 범위 초과), RETRY_EXC_ERR 2종(서버 QP ERR / 프로세스 kill)이 각각 한 status로 뭉쳐 6/10만 구별된다.

| Counter source | 구별되는 조합 수 | 남는 구분 불가 쌍 |
|---|---|---|
| CQE status only (ibv_wc_status) | 6/10 | LOC_PROT_ERR 3종, REM_ACCESS_ERR 2종, RETRY_EXC_ERR 2종 |
| + vendor_err | 8/10 | invalid rkey ≡ 주소 범위 초과 (0x88), 서버 QP ERR ≡ 프로세스 kill (0x81) |
| + sysfs hw_counters | 8/10 | 위와 동일 (두 쌍 모두 sysfs signature가 같음) |
| + ethtool traffic | 9/10 | invalid rkey ≡ 주소 범위 초과만 남음 |

핵심 전이는 두 단계다. 첫째, vendor_err가 LOC_PROT_ERR 3종(0x53 SGE length / 0x52 invalid lkey / 0x33 MR 권한 위반)을 완전히 분리해 6/10 → 8/10으로 올린다. sysfs hw_counters를 추가해도 더 이상 갈라지지 않는다(8/10 유지). 둘째, ethtool의 non-RDMA TCP sideband packet count가 서버 QP ERR(client TCP 12–13 pkt, server alive → FIN handshake)과 프로세스 kill(client TCP 8 pkt, server dead → RST)을 구분해 8/10 → 9/10으로 올린다. 두 시나리오의 RDMA packet은 모두 15개로 동일하므로 RDMA counter만으로는 갈리지 않고, server process liveness가 TCP layer에 반영된 덕분에 port-level ethtool이 잡아낸다. NCCL bootstrap TCP, UCX control channel처럼 실제 RDMA 배포는 항상 TCP sideband를 동반하므로 process death의 TCP 단절은 일반적인 신호다.

마지막으로 남는 invalid rkey ≡ 주소 범위 초과(둘 다 REM_ACCESS_ERR, vendor_err 0x88)는 sysfs·ethtool·register 모든 counter source에서 동일하다(client req_remote_access_errors +1, server rx_write_requests +1, client tx RDMA 2 pkt·300 B, server tx RDMA 2 pkt·148 B, server QP state 모두 ERR). server firmware 내부에서 rkey lookup 실패와 address range 검증 실패가 같은 Remote Access NAK을 생성하고, 두 검증 단계 사이에 public counter가 없기 때문이다. 이 쌍은 counter가 아닌 application-level 정보(어느 parameter가 틀렸는지)나 data integrity 검증으로만 구분된다. 후자의 근거로, multi-packet WRITE 경계 테스트(N=10)에서 주소 범위 초과는 MR 안쪽 packet을 DMA한 뒤 다음 packet에서 실패해 partial write가 발생한 반면(4 KB write 중 MR 안쪽 2 KB가 기록됨), invalid rkey는 key check 단계에서 막혀 partial write가 없다(상세는 experiments 문서의 "5. Partial write와 data-plane 복원, A/B recovery 실험").

### 5.4 에러 가시성의 requester 편향

10개 scenario 전부에서 server error counter가 0으로 유지된다는 사실은 단순한 누락이 아니라 구조적 패턴이다. responder는 NAK을 전송할 때조차 자신의 error counter(resp_cqe_error 등)를 올리지 않고, 정상 request 수신 counter만 올린다. 따라서 RDMA 에러의 가시성은 requester(client) 쪽에 편향되어 있다.

| 관점 | client (requester) | server (responder) |
|---|---|---|
| error counter | req_cqe_error 등 fault별 delta 발생 | 전 scenario 0 |
| 관측되는 counter | error + 일부 traffic | "정상 request 수신" counter만 |
| 함의 | client에서 fault 감지·분류 가능 | error 발생 자체를 counter로 알 수 없음 |

이는 모니터링 설계에 직접적이다. server-side만 보는 telemetry는 자기 QP가 NAK을 쏘고 있어도 그것을 error로 인지하지 못하며, fault 진단은 requester counter에 의존해야 한다.

### 5.5 Monitoring blind spot: RDMA error는 한 layer에서만 보인다

`ethtool -S`의 2,394개 counter 중 RDMA protocol error에 반응하는 것은 없다. error/diagnostic 성격의 counter 31개를 10개 scenario × 3 trial(930 측정) 동안 추적했으나 전부 0이었다.

| Counter category | 추적 counter 예 | delta |
|---|---|---|
| Steering/error | rx_steer_missed_packets, rx_out_of_buffer, rx_wqe_err, tx_cqe_err | 0 |
| PHY errors | rx_crc_errors_phy, rx_symbol_err_phy, rx/tx_discards_phy, tx_errors_phy | 0 |
| PCIe | rx/tx_pci_signal_integrity, outbound_pci_stalled_rd/wr | 0 |
| PFC | rx/tx_pause_ctrl_phy, rx/tx_global_pause_duration | 0 |
| Link | link_down_events_phy | 0 |

이름이 비슷해 RDMA error로 오인하기 쉬운 두 counter를 명시해 둔다. `rx_wqe_err`·`tx_cqe_err`는 Ethernet netdev driver의 SW counter라 RDMA verbs QP의 CQ error와 무관하고, `rx_out_of_buffer`(Ethernet RQ buffer)는 RDMA recv WQE buffer(recv buffer 부족/RNR로 올라가는 sysfs out_of_buffer)와 별개다. 같은 layer가 아니다.

권한을 root로 올려 NIC register를 직접 읽어도 RDMA error visibility는 추가로 0이다. PPCNT 6개 group + MPCNT + MISC_COUNTERS를 포함한 169개 register 전수조사에서 RDMA protocol error에 반응하는 register는 없었다. 특히 PPCNT grp=0x1a(Diagnostic)는 전부 0이고(Collie가 vendor 협조로 접근하는 diagnostic counter가 일반 사용자에게는 미노출), UNIT_PERF_COUNTERS_는 write-only cmd register라 counter data 접근 자체가 막혀 있다.

종합하면 counter observability는 다음 계층 구조를 가지며, RDMA protocol error는 Layer 3(sysfs hw_counters, 20개 counter) 한 곳에서만 관측된다.

| Layer | Source | RDMA error 관측 |
|---|---|---|
| 5 NIC Internal Diagnostic | PPCNT 0x1a 등 | vendor-locked, 전부 0 |
| 4 PCIe | MPCNT | bus error만, RDMA 무관 |
| 3 RDMA Protocol | sysfs hw_counters | RDMA error가 보이는 유일한 layer |
| 2 Ethernet/MAC | ethtool | traffic volume만, error 존재 감지 불가 |
| 1 PHY | PPCNT 0x12 | bit/symbol error, RDMA 무관 |

ethtool(2,394개)에서 RDMA에 대해 볼 수 있는 것은 `tx/rx_vport_rdma_unicast_packets/bytes`(traffic volume)뿐이며, 이것은 error의 존재가 아니라 traffic 패턴 변화로 간접 추론하는 신호다. Ethernet 기반 모니터링 스택은 RDMA protocol error에 대해 본질적으로 blind하다.

### 5.6 Counter 이름–동작 불일치: req_cqe_flush_error

WR_FLUSH_ERR(QP를 ERR로 전이시킨 뒤 pending WR을 flush) scenario에서, 이름상 flush를 세어야 할 `req_cqe_flush_error`가 증가하지 않는다(fault 직전 baseline 335,228, delta=0). 대신 일반 `req_cqe_error`만 +1이다. 즉 counter 이름이 실제 동작을 반영하지 못한다. WR_FLUSH_ERR을 `req_cqe_flush_error`로 감지하려는 모니터링 로직은 이 에러를 통째로 놓친다. 이런 이름–동작 불일치는 counter 기반 진단이 "이름을 믿지 말고 실측 signature를 봐야 한다"는 점을 보여주는 사례다.

### 5.7 Cross-source 교차 검증: firmware retry state machine 분해

단일 counter source로는 불가능하지만 sysfs와 ethtool을 결합하면 firmware 내부 동작을 역추론할 수 있다. 서버 QP ERR/프로세스 kill에서 wire에 나간 RDMA packet은 15개(ethtool tx_vport_rdma_unicast_packets +15)인데, 이는 valid WRITE 1개 + faulty WRITE 14회 retransmission으로 분해된다. retry_cnt=7(QP attribute) 설정에서 sysfs는 local_ack_timeout_err +6(standard phase timeout event)과 roce_adp_retrans +8(adaptive retransmission)을 보고하며, standard 6 + adaptive 8 = 14 faulty + 1 valid = 15로 wire packet 수와 정합한다. timeout event count(sysfs)와 wire packet count(ethtool)의 교차 검증이 없으면 standard/adaptive 2-phase 구조를 분리할 수 없다(2-phase retry 구조의 상세는 experiments 문서의 "1. Detection latency와 firmware retry 분해").

### 5.8 방법론 신뢰성: NIC rename 하드코딩 버그

이 절의 결과 신뢰도와 직결된 함정이 하나 있었다. 225 NIC이 udev에 의해 `mlx5_0` → `rocep1s0f0`로 rename(5/28)됐는데, counter를 읽는 코드(common.h)가 `mlx5_0` sysfs 경로를 하드코딩하고 있었다. 그 결과 6/2 1차 재측정에서 client counter가 전부 -1(읽기 실패 → delta=0)로 나왔다. RDMA 연결 자체는 `open_ib_device`의 fallback으로 성립했기 때문에 vendor_err·status·latency·server counter는 유효했고 client counter만 무효였다(만약 조기에 발견하지 못했다면 client signature 표가 통째로 비어 보일 위험이 있었다). 수정 내역과 회귀 방지의 코드 수준 상세는 부록 A 참조.
