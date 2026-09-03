# Latency 분포 분석

> [실험 인덱스와 canonical 수치 기준](README.md)

이 섹션은 counter mapping 실험에서 수집한 detection latency, 즉 에러 inject 시점부터 client가 CQE를 회수해 error status를 인지하는 시점까지의 분포를 다룬다. 핵심 질문은 하나다: latency를 에러를 구분하는 신호로 쓸 수 있는가? 결론을 먼저 적으면, counter signature와 vendor_err는 N=100(timeout 2종은 N=30)에서 100% deterministic인데 latency만 host 환경(OS scheduler)에 의존해 흔들린다. 따라서 latency는 분류 신호로 부적합하고, 이 사실이 CQE(vendor_err) 기반 분류를 정당화한다.

여기서 detection latency는 polling thread가 busy-poll(`poll_cq_block`, CQE가 나올 때까지 CPU를 점유하며 반복 poll) 방식으로 CQE를 회수하기까지의 wall-clock 시간이다. 따라서 RDMA wire 동작뿐 아니라 polling thread가 CPU를 잡고 있는 동안의 OS scheduler 간섭까지 함께 잡힌다 — 이 점이 아래 bimodal 분포의 원인이 된다.

배경: 왜 이 측정을 다시 했는가. 초기 N=10 측정에서 LOC_PROT_ERR 3종(SGE length 초과 / invalid lkey / MR 권한 위반)이 모두 약 1.5ms로 비슷하게 보였고, invalid rkey·주소 범위 초과는 약 3.1ms로 기록됐다. N=100으로 재측정하면서 두 가지가 드러났다. (1) invalid lkey는 사실 다른 두 LOC_PROT_ERR보다 훨씬 빠르다(median 319us). (2) NAK 계열은 단일 평균이 아니라 두 봉우리를 갖는 bimodal 분포여서, N=10 평균값(약 3.1ms)이 warmup에 치우친 artifact였다.

실험 환경(원본 findings §1): client 225 = ConnectX-6(firmware 20.40.1000, kernel 6.14.0-custom), server 224 = ConnectX-5(firmware 16.35.8002, kernel 6.16.2), 100Gbps RoCE v2. 두 NIC은 서로 다른 세대(CX-6 ↔ CX-5)다. Traffic policy는 single in-flight WR(fault inject 시점에 pending WR 1개). 빠른 에러 8종은 2026-06-04 N=100, timeout 2종은 같은 날 N=30 재측정이다. 이 재측정은 225 NIC이 5/28 udev rename(mlx5_0 → rocep1s0f0)된 뒤 sysfs counter 경로를 런타임에 동적 resolve하도록 고친 버전으로 수행했다(이전 6/2 측정은 경로를 mlx5_0로 하드코딩해 client counter가 전부 읽기 실패였음; vendor_err·status·latency·server counter는 RDMA 연결 fallback으로 유효했다).

### 6.1 N=100 latency median / mean / std (에러별)

빠른 에러 8종 N=100, timeout 2종 N=30. 단위는 us(timeout 2종만 s). 모든 수치는 원본 findings §2-1 표에서 인용.

| 에러 (vendor_err) | median | mean | std | min–max | 분포 특성 |
|---|---|---|---|---|---|
| SGE length 초과 (0x53) | 1503 us | 1503 us | 42 us | 1490–1904 us | 단봉, 안정 |
| invalid lkey (0x52) | 319 us | 358 us | 203 us | 316–1554 us | 단봉, 97/100 안정 |
| MR 권한 위반 (0x33) | 1500 us | 1496 us | 202 us | 348–1707 us | 단봉, RDMA READ 왕복 |
| WR_FLUSH_ERR (0xf5) | 520 us | 523 us | 64 us | 398–689 us | 단봉, SW flush |
| REMOTE_WRITE 권한 없음 / REM_INV_REQ_ERR (0x8a) | 1641 us | 1080 us | 584 us | 467–1751 us | bimodal |
| invalid rkey / REM_ACCESS_ERR (0x88) | 1738 us | 1416 us | 582 us | 554–2008 us | bimodal |
| recv buffer 부족 / RNR_RETRY_EXC_ERR (0x87) | 255 us | 255 us | 11 us | 248–289 us | 단봉, 최안정 |
| 주소 범위 초과 / REM_ACCESS_ERR (0x88) | 565 us | 1052 us | 761 us | 555–3213 us | bimodal |
| 서버 QP ERR / RETRY_EXC_ERR (0x81) | 3.56 s | 3.56 s | 30 ms | 3.54–3.71 s | 실측 retry exhaustion (N=30) |
| 프로세스 kill / RETRY_EXC_ERR (0x81) | 5.13 s | 5.13 s | 116 ms | 4.91–5.25 s | signal+sleep artifact (N=30) |

표 읽는 법: 단봉(unimodal) 에러는 median ≈ mean이고 std가 작다(SGE length 42us, RNR 11us). bimodal 에러는 median과 mean이 크게 벌어지고 std가 580–760us로 크다(예: 주소 범위 초과 median 565us vs mean 1052us). 즉 std가 큰 항목이 곧 분포가 두 봉우리로 갈라진 항목이다. invalid lkey는 median 319us·mean 358us로 거의 단봉이지만 min–max가 316–1554us까지 벌어진다 — 100회 중 3회만 느린 쪽으로 튀어 std 203us를 만든 것이고, 97/100은 316–360us 부근에 모인다.

### 6.2 invalid lkey 정정: 약 1.5ms → median 319us

기존 N=10에서 invalid lkey를 다른 LOC_PROT_ERR 2종과 함께 "약 1.5ms"로 묶었던 것은 부정확했다. N=100 median은 319us로, SGE length 초과·MR 권한 위반(약 1.5ms)과 명확히 분리된다.

원인은 latency가 error pipeline의 어느 stage에서 잡히는지를 그대로 반영하기 때문이다. ethtool traffic fingerprint(원본 findings §4-1, N=3 deterministic)와 교차하면 세 LOC_PROT_ERR이 wire에 보내는 RDMA 패킷 수가 다르다. 여기서 client TX/server TX RDMA 패킷은 ethtool의 tx_vport_rdma_unicast_packets delta다.

| 에러 | latency median | client TX RDMA 패킷 | server TX RDMA 패킷 | 의미 |
|---|---|---|---|---|
| invalid lkey | 319 us | 1 (150 B) | 1 (74 B ACK/NAK) | 첫 WRITE 1개만 나가고 서버가 즉시 NAK — 추가 operation·retry 없음 |
| MR 권한 위반 | 1500 us | 2 (236 B) | 2 (212 B) | RDMA READ request가 서버까지 가서 거부 응답을 받는 왕복 |
| SGE length 초과 | 1503 us | 5 (4,542 B) | 1–2 (74–148 B) | DMA 시작 후 multi-packet WRITE 도중 MR boundary 초과 감지 |

invalid lkey가 빠른 이유는 단일 immediate operation(WRITE 1패킷)에서 끝나기 때문이다 — 추가 valid operation이나 multi-packet DMA, retry loop가 없다. 반면 SGE length 초과는 NIC이 MR boundary를 pre-validate하지 않고 DMA를 시작한 뒤 중간에 잡기 때문에 5패킷(4,542B)을 보내고서야 감지한다(원본 findings §4-3, "NIC이 MR boundary를 pre-validate하지 않음"). MR 권한 위반은 RDMA READ가 서버에 도달했다가 거부되는 왕복이 끼어 약 1.5ms가 된다. 세 에러는 같은 ibv_wc_status(LOC_PROT_ERR)·같은 counter 계열이지만 wire 활동량(패킷 1 vs 2 vs 5)으로 갈린다.

[TODO: 확인 필요 — 원본 findings 내부에 lkey wire 패킷 수가 서로 어긋나는 곳이 있다. §2-1 발견 1과 §3 ethtool 노트(line 61)는 invalid lkey를 "wire 패킷 0개(즉시 거부)"로 서술하지만, 같은 문서의 ethtool 측정(§4-1 lkey C_TX RDMA=1·150B, §4-3 "1 pkt = post-immediate", §4-5 "ratio 1.0 = 모든 수신에 응답")은 일관되게 1패킷 전송 + 서버 1응답을 보여준다. 측정 표(1패킷)를 채택했다. SQ posting 단계에서 즉시 거부(wire 0)인지, 첫 WRITE 전송 후 서버 NAK(wire 1)인지는 packet capture로 한 번 더 확정 필요.]

다만 이 wire-활동 차이는 latency가 안정적일 때만 신호가 된다. 6.4가 아니라 6.3·6.5에서 보듯 latency 자체가 host jitter로 흔들리므로, 분류는 latency가 아니라 wire 패킷 수(ethtool)나 vendor_err로 해야 한다.

### 6.3 NAK 에러의 bimodal 분포

REMOTE_WRITE 권한 없음(REM_INV_REQ_ERR) / invalid rkey(REM_ACCESS_ERR) / 주소 범위 초과(REM_ACCESS_ERR) 세 NAK 에러는 단봉이 아니라 두 모드를 오간다. 한 모드는 약 0.5ms 부근, 다른 모드는 약 1.6ms 부근이고, 두 모드 간 차이는 약 1ms로 일정하다.

| 에러 (vendor_err) | 빠른 모드 | 느린 모드 | 모드 차 | std |
|---|---|---|---|---|
| 주소 범위 초과 (0x88) | 약 565 us (median이 여기 붙음) | 약 1.6 ms | 약 1 ms | 761 us |
| REMOTE_WRITE 권한 없음 (0x8a) | 약 0.5 ms | 약 1641 us (median이 여기 붙음) | 약 1 ms | 584 us |
| invalid rkey (0x88) | 약 0.55 ms | 약 1738 us (median이 여기 붙음) | 약 1 ms | 582 us |

두 모드 차가 약 1ms로 모든 NAK 에러에서 같다는 점이 핵심 단서다. 추정 원인은 busy-poll(`poll_cq_block`) 도중 OS scheduler가 polling thread에서 CPU를 빼앗는 것이다 — RDMA 자체 latency가 아니라 host 측 CPU 양보가 약 1ms의 추가 지연을 만든다(추정, 근거는 아래 두 가지). 이 모드 전환은 실행 도중 일어나는 phase shift이며 warmup이 아니다. 근거: (1) 어느 모드가 더 빈번한지(median이 빠른 쪽에 붙는지 느린 쪽에 붙는지)가 에러마다 다르다 — 주소 범위 초과는 median이 빠른 모드(565us)에, 나머지 둘은 느린 모드(1641us, 1738us)에 붙는다. warmup이라면 항상 초반이 느려야 하는데 방향이 일정하지 않다. (2) 같은 시나리오의 counter delta·vendor_err는 N=100 전부 동일한데 latency만 갈라진다.

기존 N=10에서 invalid rkey·주소 범위 초과를 "약 3.1ms"로 적었던 것은 이 bimodal 분포의 warmup-biased 평균이었고, N=100 median은 그보다 낮다(주소 범위 초과 565us, invalid rkey 1738us).

### 6.4 Timeout 2종: 실측 vs measurement artifact

RETRY_EXC_ERR을 내는 두 시나리오는 latency 크기(초 단위)가 비슷해 보이지만 의미가 전혀 다르다.

| 시나리오 | latency | 의미 | 실 detection인가 |
|---|---|---|---|
| 서버 QP ERR | 3.56 s ± 30 ms (N=30) | retry 소진까지 걸린 실제 시간 | 예 (실측) |
| 프로세스 kill | 5.13 s ± 116 ms (N=30) | inject 코드의 signal + sleep(1s) coordination 포함 | 아니오 (artifact) |

서버 QP ERR의 3.56s는 firmware retry state machine이 standard phase와 adaptive phase를 모두 소진하는 실측 retry exhaustion 시간이다. 두 phase는 client sysfs counter로 구분된다: standard phase는 local_ack_timeout_err +6, adaptive phase는 roce_adp_retrans +8(원본 findings §5). 합치면 14회 faulty 전송 + 최초 1회 valid 전송 = wire 15 packets(ethtool tx_vport_rdma_unicast_packets +15로 교차 확인). 반면 프로세스 kill의 5.13s는 inject 코드가 서버에 signal을 보내고 sleep(1s)으로 coordination한 시간이 포함된 값이라 RDMA 측 실제 detection latency가 아니다. 두 시나리오의 latency 차(약 1.6s)는 RDMA 동작 차이가 아니라 측정 harness 차이다.

중요한 대비: 두 시나리오의 sysfs/firmware retry counter는 N=30 전부 동일하다(local_ack_timeout_err +6, roce_adp_retrans +8, req_transport_retries_exceeded +1, req_cqe_error +1, 30/30 deterministic). retry counter는 latency와 달리 흔들리지 않는 deterministic 신호다 — sysfs만으로는 이 두 시나리오를 구분할 수 없고, 구분은 ethtool의 non-RDMA TCP sideband 패킷 수로만 가능하다(서버 QP ERR은 server alive → client TX TCP 12–13, kill은 server dead → client TX TCP 8; 원본 findings §4-2).

따라서 timeout 계열에서 의미 있는 단일 retry-exhaustion 값은 서버 QP ERR의 3.56s다. 프로세스 kill 5.13s는 보고 시 artifact임을 명시해야 한다.

### 6.5 종합: latency는 분류 신호로 부적합

핵심 대비는 다음과 같다.

| 신호 | deterministic? | host 환경 의존? | 분류 신호로 적합? |
|---|---|---|---|
| counter signature (sysfs) | 예 (N=100/N=30 100%) | 아니오 | 적합 |
| vendor_err (CQE) | 예 (N=100/N=30 100%) | 아니오 | 적합 |
| ibv_wc_status (CQE) | 예 (N=100/N=30 100%) | 아니오 | 적합(단, resolution 낮음 — 6/10) |
| detection latency | 아니오 (NAK bimodal, std 580–760us) | 예 (OS scheduler) | 부적합 |

같은 에러를 N=100(timeout N=30) 반복해도 counter delta와 vendor_err는 단 한 번도 흔들리지 않는데, latency만 OS scheduler의 CPU 양보에 따라 두 모드를 오간다. 더구나 모드 간 차(약 1ms)가 에러 종류와 무관하게 일정하므로, latency 값으로 에러를 구분하려 하면 host jitter와 에러 종류 차이를 섞어버린다. 이것이 latency가 아닌 CQE(vendor_err) 기반 분류를 택해야 하는 정량적 근거다.

한계와 후속: 위 latency 절대값(특히 NAK 3종의 median)은 CPU pinning이나 core isolation 없이 측정한 값이라 host 환경에 따라 달라진다. latency의 절대값을 보고 가능한 수치로 확정하려면 polling thread를 isolated core에 pin하고 OS scheduler 간섭을 제거한 재측정이 필요하다.

[TODO: CPU pinning/core isolation 후 latency 절대값 재측정]
[TODO: invalid lkey wire 패킷 0 vs 1 — packet capture로 확정 (6.2 참조)]
