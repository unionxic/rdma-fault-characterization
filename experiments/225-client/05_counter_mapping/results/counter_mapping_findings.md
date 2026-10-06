# HW Counter x Error Type Mapping: 실험 결과 종합

## 1. 실험 환경

| 항목 | Client (225) | Server (224) |
|---|---|---|
| NIC | ConnectX-6 (MT28908) | ConnectX-5 (MT27800) |
| Firmware | 20.40.1000 | 16.35.8002 |
| Kernel | 6.14.0-custom-junseolee | 6.16.2 |
| RDMA IP | 10.0.0.2 (enp1s0f0np0) | 10.0.0.3 (enp1s0f0np0) |
| Link | 100 Gbps RoCE v2 | 100 Gbps RoCE v2 |
| Counter device | rocep1s0f0 (mlx5_0에서 5/28 udev rename) | mlx5_0 |

Heterogeneous NIC pair (CX-6 ↔ CX-5). 서로 다른 NIC 세대 간에도 counter signature가 deterministic.

Traffic policy: single in-flight WR. Fault inject 시점에 pending WR 1개로 제한.

주의: 225 NIC이 mlx5_0 → rocep1s0f0로 udev rename(5/28)됨. counter sysfs 경로는 디바이스 이름을 런타임에 resolve해서 읽는다(common.h: resolve_ib_dev_name / counters_dir). 6/2 1차 재측정은 경로가 mlx5_0로 하드코딩돼 client counter가 전부 -1(무효)이었고, 6/4 동적 resolve 수정 후 재측정한 것이 아래 결과다.

---

## 2. Fault Scenario 요약

| 시나리오 | Fault | Injection | ibv_wc_status | vendor_err | Detection Latency (median) | N |
|---|---|---|---|---|---|---|
| SGE length 초과 | SGE length > MR size | client SGE.length 초과 | LOC_PROT_ERR (4) | 0x53 | 1.50 ms | 100 |
| invalid lkey | Invalid lkey | client 잘못된 lkey | LOC_PROT_ERR (4) | 0x52 | 0.32 ms | 100 |
| MR 권한 위반 | MR permission violation | LOCAL_WRITE 없는 MR로 READ | LOC_PROT_ERR (4) | 0x33 | 1.50 ms | 100 |
| WR_FLUSH_ERR | QP→ERR flush | ibv_modify_qp(ERR) 후 pending WR | WR_FLUSH_ERR (5) | 0xf5 | 0.52 ms | 100 |
| REMOTE_WRITE 권한 없음 | No REMOTE_WRITE perm | server MR에 REMOTE_WRITE 없음 | REM_INV_REQ (9) | 0x8a | 1.64 ms (bimodal) | 100 |
| invalid rkey | Invalid rkey | client 잘못된 rkey로 WRITE | REM_ACCESS_ERR (10) | 0x88 | 1.74 ms (bimodal) | 100 |
| recv buffer 부족 | Recv buffer 부족 | SEND/RECV, server recv WQE 미게시 | RNR_RETRY_EXC (13) | 0x87 | 0.26 ms | 100 |
| 서버 QP ERR | QP crash | server ibv_modify_qp(ERR) | RETRY_EXC (12) | 0x81 | 3.56 s | 30 |
| 프로세스 kill | Process kill | kill -9 server | RETRY_EXC (12) | 0x81 | 5.13 s* | 30 |
| link down | Link down | ip link set down | (재현 실패) | — | — | 3 |
| 주소 범위 초과 | Address out of bounds | client raddr MR 범위 밖 | REM_ACCESS_ERR (10) | 0x88 | 0.57 ms (bimodal) | 100 |

\* 프로세스 kill 5.13s는 inject 코드의 signal + sleep(1s) coordination이 포함된 측정값으로 실제 detection이 아니다. RETRY_EXC의 실측 retry exhaustion은 서버 QP ERR 3.56s다. 기존 N=10의 invalid rkey와 주소 범위 초과 ~3.1ms는 warmup-biased였고, N=100 median은 그보다 낮다(아래 2-1).

link down 실패 원인: `ip link set enp1s0f0np0 down`이 RoCE v2 트래픽을 차단하지 못함 (3 trial 모두 status=0 SUCCESS). 소프트웨어 link down으로는 RDMA path가 끊기지 않음.

---

## 2-1. Detection Latency 분포 (빠른 에러 N=100 / timeout N=30, 2026-06-04 재측정)

| 에러 (vendor_err) | median (us) | mean | std | min~max | 비고 |
|---|---|---|---|---|---|
| SGE length (0x53) | 1503 | 1503 | 42 | 1490~1904 | 안정, wire 5pkt 후 감지 |
| invalid lkey (0x52) | 319 | 358 | 203 | 316~1554 | 즉시 거부(wire pkt 0), 97/100 안정 |
| MR permission (0x33) | 1500 | 1496 | 202 | 348~1707 | RDMA READ 왕복 |
| WR_FLUSH (0xf5) | 520 | 523 | 64 | 398~689 | 안정, SW flush |
| REM_INV_REQ (0x8a) | 1641 | 1080 | 584 | 467~1751 | bimodal |
| REM_ACCESS rkey (0x88) | 1738 | 1416 | 582 | 554~2008 | bimodal |
| RNR (0x87) | 255 | 255 | 11 | 248~289 | 최안정 |
| REM_ACCESS addr (0x88) | 565 | 1052 | 761 | 555~3213 | bimodal |
| RETRY_EXC QP ERR (0x81) | 3.56 s | 3.56 s | 30 ms | 3.54~3.71 s | 실측 retry exhaustion (N=30) |
| RETRY_EXC kill (0x81) | 5.13 s* | 5.13 s | 116 ms | 4.91~5.25 s | *signal+sleep artifact (N=30) |

발견:

1. invalid lkey 정정: 기존 N=10 "~1.5ms"는 부정확. N=100 median 319us로, length·permission(~1.5ms)과 분리된다. ethtool상 lkey는 wire 패킷 0개(즉시 거부)인 반면 length는 5패킷(NIC이 MR boundary를 pre-validate하지 않고 DMA 시작 후 감지)이라, latency가 error pipeline stage를 그대로 반영한다.

2. NAK 에러 bimodal: REM_INV_REQ·REM_ACCESS(rkey/addr)는 ~0.5ms와 ~1.6ms 두 모드를 오간다(두 모드 차 ~1ms로 일정). busy-poll(poll_cq_block) 중 OS scheduler의 CPU 양보로 추정 — 실행 내 phase shift이며 방향(앞/뒤 어느 쪽이 느린지)은 실행마다 다르다(warmup이 아님). counter·vendor_err는 N=100에서 100% deterministic인데 latency만 host 환경에 의존한다 → latency는 분류 신호로 부적합하고, CQE(vendor_err) 기반 분류의 근거가 된다. 절대값을 보고하려면 CPU pinning/core isolation이 필요하다.

3. firmware retry counter는 deterministic: RETRY_EXC 두 시나리오의 local_ack_timeout_err +6, roce_adp_retrans +8이 N=30 전부 동일하다 — retry state machine은 latency와 달리 흔들리지 않는다.

---

## 3. Counter Signature Table (sysfs hw_counters)

각 scenario에서 non-zero delta counter만 표시. 빠른 에러 N=100, timeout(서버 QP ERR/프로세스 kill) N=30 전 trial 100% deterministic (2026-06-04 재측정, NIC rename 경로 수정 후).

### 3-1. Client-side

컬럼 헤더는 시나리오 의미명: SGE length / lkey / 권한 / WR_FLUSH / REM_INV / rkey / RNR / QP ERR / kill / addr.

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

### 3-2. Server-side

컬럼 헤더는 위 client-side 표와 동일한 시나리오 의미명.

| Counter | SGE length | lkey | 권한 | WR_FLUSH | REM_INV | rkey | RNR | QP ERR | kill | addr |
|---|---|---|---|---|---|---|---|---|---|---|
| rx_read_requests | | | +1 | | | | | | | |
| rx_write_requests | | | | | | +1 | | | | +1 |
| out_of_buffer | | | | | | | +1 | | | |

Server-side error counter(resp_cqe_error, resp_remote_access_errors 등)는 어떤 scenario에서도 증가하지 않음.

### 3-3. 관찰

1. `vendor_err`로 LOC_PROT_ERR 3종 완전 구분: 0x53 (length), 0x52 (lkey), 0x33 (permission)
2. Error visibility가 requester(client)에 편향 — responder(server)는 error counter를 올리지 않음
3. Server counter 중 유일한 변화: rx_write_requests(invalid rkey, 주소 범위 초과), rx_read_requests(MR 권한 위반), out_of_buffer(recv buffer 부족) — 모두 "정상 request 수신" counter
4. WR_FLUSH_ERR인데 `req_cqe_flush_error` 미증가 (baseline 335,228, delta=0). `req_cqe_error`만 +1 — counter 이름과 실제 동작 불일치
5. MR 권한 위반의 server rx_read_requests=+1 → valid operation이 RDMA READ임을 확인. (invalid rkey와 주소 범위 초과는 WRITE)

sysfs resolution: **10 scenarios → 구별되는 조합 8개** (REM_ACCESS_ERR 잘못된 rkey ≡ 주소 범위 초과, RETRY_EXC_ERR 서버 QP ERR ≡ 프로세스 종료 구분 불가)

---

## 4. ethtool 트래픽 counter 패턴 (tx/rx_vport_rdma/unicast)

ethtool -S의 2,394개 counter 중 RDMA traffic counter만 non-zero delta. error/diagnostic counter 31개는 전부 zero. N=3, deterministic.

### 4-1. 패킷 수 패턴

| 시나리오 | C_TX RDMA | C_TX RDMA bytes | S_TX RDMA | S_TX RDMA bytes | C_TX TCP | S_TX TCP |
|---|---|---|---|---|---|---|
| SGE length | 5 | 4,542 | 1-2 | 74-148 | 10 | 9 |
| lkey | 1 | 150 | 1 | 74 | 10 | 9 |
| 권한 | 2 | 236 | 2 | 212 | 10 | 9 |
| WR_FLUSH | 0 | 0 | 0 | 0 | 10 | 9 |
| REM_INV | 1 | 150 | 1 | 74 | 10 | 9 |
| rkey | 2 | 300 | 2 | 148 | 10 | 9 |
| RNR | 1 | 134 | 1 | 74 | 10 | 9 |
| QP ERR | 15 | 2,250 | 1 | 74 | 12-13 | 10 |
| kill | 15 | 2,250 | 1 | 74 | 8 | 7 |
| addr | 2 | 300 | 2 | 148 | 10 | 9 |

C_TX RDMA = client tx_vport_rdma_unicast_packets, C_TX TCP = client tx_vport_unicast_packets (non-RDMA)

ethtool 추가 후 resolution: **10 scenarios → 구별되는 조합 9개** (REM_ACCESS_ERR 잘못된 rkey ≡ 주소 범위 초과만 남음)

### 4-2. RETRY_EXC_ERR 서버 QP ERR ≡ 프로세스 종료 구분

| Metric | 서버 QP ERR | 프로세스 kill (-9) | 원인 |
|---|---|---|---|
| C_TX TCP | 12-13 | **8** | server alive → TCP FIN handshake vs dead → RST |
| S_TX TCP | 10 | **7** | 동일 |
| C_TX RDMA | 15 | 15 | NIC retry는 동일 |
| S_TX RDMA | 1 | 1 | 동일 |

non-RDMA unicast (TCP sideband traffic) 패킷 수가 서버 QP ERR과 프로세스 kill을 deterministic하게 구분. Server process liveness가 TCP layer에 반영됨.

일반화: NCCL bootstrap TCP, UCX control channel 등 실제 RDMA deployment는 항상 TCP sideband가 있음. Process death는 TCP connection 단절로 나타나며, ethtool이 이를 port-level에서 캡처.

### 4-3. RDMA packet count → error pipeline stage

| C_TX RDMA | Scenarios | Pipeline Stage |
|---|---|---|
| 0 | WR_FLUSH | pre-post — QP가 이미 ERR, WR이 wire에 안 나감 |
| 1 | lkey, REM_INV, RNR | post-immediate — 첫 operation에서 즉시 error/NAK |
| 2 | 권한, rkey, addr | operation-level — valid op 1회 + faulty op 1회 |
| 5 | SGE length | mid-DMA — multi-packet WRITE 도중 error 감지 |
| 15 | QP ERR, kill | timeout-loop — retry exhaustion (standard + adaptive) |

SGE length 초과가 5 packets(4,542B) 전송 후에야 error 감지 → NIC이 MR boundary를 pre-validate하지 않고 DMA 시작 후 중간에 error를 잡음.

### 4-4. Wire-level packet size

| Operation | Wire bytes/pkt | 비고 |
|---|---|---|
| RDMA WRITE | 150 B | BTH + RETH(16B) + payload |
| RDMA SEND (recv buffer 부족) | 134 B | BTH + payload (RETH 없음) |
| RDMA READ request (MR 권한 위반 client) | 118 B | BTH + RETH, payload 없음 |
| RDMA READ response (MR 권한 위반 server) | 106 B | BTH + AETH + data |
| ACK/NAK | 74 B | transport ACK |

WRITE(150) - SEND(134) = 16B 차이 = RETH header (raddr 8B + rkey 4B + DMA length 4B). Wire byte count에서 operation type 역추론 가능.

### 4-5. Server response ratio

| Ratio (S_TX / C_TX RDMA) | Category | Scenarios |
|---|---|---|
| 1.0 | 모든 수신에 응답 (ACK/NAK) | lkey, 권한, REM_INV, rkey, RNR, addr |
| 0.07 (1/15) | 첫 ACK만, retry에는 무응답 | QP ERR, kill |
| 0.2-0.4 (1-2/5) | multi-packet WRITE 부분 응답 | SGE length |
| N/A (0/0) | traffic 없음 | WR_FLUSH |

Response ratio로 error category 판별 가능: 1.0 = instant error/NAK, <<1 = timeout.

---

## 5. Firmware Retry State Machine 분해

서버 QP ERR과 프로세스 kill에서 두 counter source를 결합한 retry 동작 분석:

| Source | Counter | Delta | 의미 |
|---|---|---|---|
| sysfs | local_ack_timeout_err | +6 | standard phase timeout event 수 |
| sysfs | roce_adp_retrans | +8 | adaptive retransmission 수 |
| sysfs | req_transport_retries_exceeded | +1 | retry 최종 소진 event |
| ethtool | tx_vport_rdma_unicast_packets | +15 | wire에 나간 총 RDMA packet 수 |

구성: 15 pkts = 1 valid WRITE + 14 faulty WRITE transmissions

retry_cnt=7 (QP attribute) 설정에서:
- Standard phase: original + retries → local_ack_timeout_err=+6
- Adaptive phase: roce_adp_retrans_en=1 (firmware feature) → +8 추가 전송
- 합계: standard transmissions + adaptive transmissions = 14 faulty + 1 valid = 15 pkts

단일 counter source로는 이 분해가 불가능. sysfs(timeout event count)와 ethtool(wire packet count)의 교차 검증으로 firmware retry state machine의 내부 동작을 역추론.

---

## 6. RDMA Error Monitoring Blind Spot

### 6-1. ethtool error counter 전수 조사

31개 error/diagnostic counter × 10 scenarios × 3 trials = 930 측정 → 전부 0

| Counter Category | Tracked Counters | Delta |
|---|---|---|
| Steering/error | rx_steer_missed_packets, rx_out_of_buffer, rx_wqe_err, tx_cqe_err | 0 |
| PHY errors | rx_crc_errors_phy, rx_symbol_err_phy, rx/tx_discards_phy, tx_errors_phy | 0 |
| PCIe | rx/tx_pci_signal_integrity, outbound_pci_stalled_rd/wr | 0 |
| PFC | rx/tx_pause_ctrl_phy, rx/tx_global_pause_duration | 0 |
| Link | link_down_events_phy | 0 |

`rx_wqe_err`, `tx_cqe_err`는 Ethernet netdev driver의 SW counter — RDMA verbs QP의 CQ error와 무관.
`rx_out_of_buffer`는 Ethernet RQ buffer — RDMA recv WQE buffer (recv buffer 부족/RNR)와 별개.

### 6-2. NIC register-level 조사 (mlxreg, root 권한)

| Register | Group | 결과 |
|---|---|---|
| PPCNT grp=0x00 | IEEE 802.3 | Ethernet frame/octet counter — sysfs/ethtool과 동일 layer |
| PPCNT grp=0x10 | Extended Ethernet | 위와 동일 |
| PPCNT grp=0x12 | Physical Layer | PHY bit/symbol error |
| PPCNT grp=0x13 | FEC | 전부 0 (FEC inactive) |
| PPCNT grp=0x16 | IB Port Counters | sysfs port counters와 동일 데이터 |
| PPCNT grp=0x19 | PLR | 전부 0 |
| PPCNT grp=0x1a | Diagnostic | **전부 0 — Collie의 diagnostic counter 미노출** |
| MPCNT grp=0 | PCIe Performance | BER/equalization data, error-type 무관 |
| MISC_COUNTERS | — | ECC=0, ldb_silent_drop=0 |
| UNIT_PERF_COUNTERS_ | — | WO cmd register (cmd=0x01), counter data 접근 불가 |
| ROCE_ACCL | — | 설정 register (counter 아님) |

169개 register 전수 조사. RDMA protocol error에 반응하는 register 없음.

### 6-3. Counter observability hierarchy

```
Layer 5: NIC Internal Diagnostic  →  EMPTY (vendor-locked, Collie는 vendor 협조로 접근)
Layer 4: PCIe (MPCNT)            →  bus errors only, RDMA 무관
Layer 3: RDMA Protocol (sysfs)   →  ★ RDMA error가 보이는 유일한 layer (20 counters)
Layer 2: Ethernet/MAC (ethtool)  →  traffic volume만 보임, error 존재 자체 감지 불가
Layer 1: PHY (PPCNT 0x12)        →  bit/symbol errors, RDMA 무관
```

결론: RDMA protocol error는 NIC counter 계층에서 Layer 3 (sysfs hw_counters) 한 곳에서만 관측 가능. 그 위(Diagnostic)는 vendor-locked, 그 아래(Ethernet/PHY/PCIe)는 다른 layer의 counter.

**Privilege를 높여도 (root → register access) RDMA error visibility는 추가로 0.** ethtool(2,394개)에서 RDMA error를 볼 수 있는 것은 tx/rx_vport_rdma_unicast_packets/bytes (traffic volume) 뿐이고, 이것은 error의 존재가 아니라 traffic 패턴 변화로 간접 추론하는 것.

---

## 7. 추가 검증 결과

### 7-1. QP State Verification (N=10)

Error NAK(REMOTE_WRITE 권한 없음/invalid rkey/주소 범위 초과) 후 server QP 상태를 ibv_query_qp로 확인:

| Scenario | Server QP State | 의미 |
|---|---|---|
| REMOTE_WRITE 권한 없음 (REM_INV_REQ) | ERR | Error NAK 전송 후 QP → ERR 전이 |
| invalid rkey (REM_ACCESS_RKEY) | ERR | 동일 |
| 주소 범위 초과 (REM_ACCESS_ADDR) | ERR | 동일 |
| recv buffer 부족 (RNR_RETRY) | **RTS** | RNR NAK은 error가 아님, QP 유지 |

IBA spec과 ConnectX-5 구현이 정확히 일치. Error NAK 후 server QP도 ERR → bilateral recovery 필요.

### 7-2. Partial Write Boundary Test (N=10)

주소 범위 초과 (address out of bounds)에서 multi-packet RDMA WRITE가 MR boundary를 넘을 때:

| Test | write_len | result | within MR | beyond MR |
|---|---|---|---|---|
| single_pkt_cross (64B, 1 pkt) | 64 | NO_WRITE | 0/32 B | 0/32 B |
| multi_pkt_cross (4KB, 4 pkts) | 4096 | **PARTIAL_WRITE** | **2048/2048 B** | 0/2048 B |
| barely_1B_inside (64B, 1 pkt) | 64 | NO_WRITE | 0/1 B | 0/63 B |

- Single-packet: NIC이 packet 내 전체 범위를 검증 후 거부 → write 없음
- Multi-packet: NIC이 packet 단위로 순차 처리 → MR 안쪽 packet은 DMA 완료, 다음 packet에서 에러 → **partial write 발생**
- REMOTE_WRITE 권한 없음/invalid rkey/recv buffer 부족은 partial write 없음. 주소 범위 초과(addr boundary + multi-pkt)에서만 발생.

---

## 8. Resolution Summary

### 8-1. 구분 가능한 신호 조합

| Counter Source | 구별되는 조합 수 | 구분 불가 쌍 |
|---|---|---|
| CQE status only (ibv_wc_status) | 6/10 | LOC_PROT 3종, REM_ACCESS 2종, RETRY_EXC 2종 |
| + vendor_err | 8/10 | rkey ≡ addr (0x88), QP ERR ≡ kill (0x81) |
| + sysfs hw_counters | 8/10 | rkey ≡ addr, QP ERR ≡ kill (동일 counter signature) |
| + ethtool traffic | **9/10** | **rkey ≡ addr만 남음** (QP ERR/kill은 TCP pkt count로 구분) |

### 8-2. 최종 indistinguishable pair: REM_ACCESS_ERR 잘못된 rkey ≡ 주소 범위 초과

| Metric | invalid rkey | 주소 범위 초과 (addr out of bounds) |
|---|---|---|
| ibv_wc_status | REM_ACCESS_ERR (10) | REM_ACCESS_ERR (10) |
| vendor_err | 0x88 | 0x88 |
| Client sysfs | req_remote_access_errors +1 | req_remote_access_errors +1 |
| Server sysfs | rx_write_requests +1 | rx_write_requests +1 |
| C_TX RDMA | 2 pkts, 300B | 2 pkts, 300B |
| S_TX RDMA | 2 pkts, 148B | 2 pkts, 148B |
| TCP traffic | 10 pkts | 10 pkts |
| Latency | ~3.1 ms | ~3.1 ms |
| Server QP state | ERR | ERR |

모든 counter source에서 동일. Server firmware 내부에서 rkey lookup 실패와 address range 검증 실패가 동일 NAK(Remote Access Error)을 생성하며, 두 검증 단계 사이에 public counter가 없음. Application-level 정보(어떤 parameter가 잘못됐는지)로만 구분 가능.

단, partial write 동작은 다를 수 있음: invalid rkey는 key check에서 실패하므로 DMA 자체가 안 됨, 주소 범위 초과는 address check에서 실패하며 multi-packet일 때 partial write 발생. 이 차이는 counter가 아닌 **data integrity 검증**으로만 관측 가능.

---

## 9. 주요 발견 정리

### 9-1. Error classification

| Finding | 근거 |
|---|---|
| vendor_err로 LOC_PROT_ERR 3종 완전 구분 | 0x53/0x52/0x33, N=10 100% |
| Error visibility가 requester에 구조적으로 편향 | 10 scenarios 전부에서 server error counter=0 |
| Responder는 NAK 전송 시 자신의 error counter를 올리지 않음 | REMOTE_WRITE 권한 없음/invalid rkey/주소 범위 초과: server resp_cqe_error=0 |
| Error NAK 후 server QP는 ERR로 전이 (RNR 제외) | ibv_query_qp, N=10 |
| req_cqe_flush_error는 WR_FLUSH_ERR을 count하지 않음 | WR_FLUSH_ERR: baseline=335228, delta=0, req_cqe_error만 +1 |

### 9-2. Firmware behavior

| Finding | 근거 |
|---|---|
| Firmware retry: standard(retry_cnt=7) + adaptive(roce_adp_retrans_en) 2-phase | sysfs timeout_err=+6, adp_retrans=+8, ethtool 15 pkts |
| NIC이 MR boundary를 pre-validate하지 않음 | SGE length 초과: 5 pkts(4,542B) 전송 후 error 감지 |
| Multi-packet WRITE에서 partial write 발생 | 주소 범위 초과 boundary test: 4KB write → MR 안쪽 2KB 써짐 |
| ip link set down이 RoCE 트래픽을 차단하지 못함 | link down: 3 trial 모두 SUCCESS |

### 9-3. Monitoring architecture

| Finding | 근거 |
|---|---|
| RDMA error는 sysfs hw_counters(20개)에서만 관측 가능 | ethtool 2,394개 error counter 전부 zero |
| Ethernet monitoring은 RDMA protocol error에 blind | 31개 error counter × 10 scenarios × 3 trials = 930 measurements, ALL ZERO |
| Root + register access도 추가 RDMA error visibility = 0 | PPCNT, MPCNT, MISC_COUNTERS 전부 무반응 |
| NIC internal diagnostic counter는 vendor-locked | PPCNT grp=0x1a(diagnostic) 전부 zero, UNIT_PERF_COUNTERS_ WO-only |
| TCP sideband traffic이 process liveness를 implicit하게 encode | 서버 QP ERR TCP=12-13 vs 프로세스 kill TCP=8 |

### 9-4. Wire-level characterization

| Finding | 근거 |
|---|---|
| RDMA packet count가 error pipeline stage를 노출 | 0(pre-post) → 1(immediate) → 2(op-level) → 5(mid-DMA) → 15(timeout) |
| Operation type이 wire byte count에서 역추론 가능 | WRITE=150B, SEND=134B, ACK=74B. 차이=RETH(16B) |
| Timeout error의 retry amplification: 15x | 서버 QP ERR/kill: 15 RDMA pkts / 2,250B per single error |
| sysfs + ethtool 교차 검증으로 firmware retry 분해 가능 | timeout_err(6) + adp_retrans(8) = 14 retries + 1 original = 15 wire pkts |
