# 에러 분류 체계와 responder pipeline

> [이론 문서 인덱스](README.md)

### 4.1 배경: 왜 분류 체계가 필요한가

RDMA 작업이 실패하면 completion queue entry(CQE)에 두 개의 필드가 담긴다. 하나는 IBA(InfiniBand Architecture) 규격이 정의한 표준 상태 코드 `ibv_wc_status`(24종), 다른 하나는 NIC 제조사가 붙이는 32비트 `vendor_err`다. mlx5에서 `vendor_err`는 NIC hardware가 에러를 감지한 시점에 관찰한 raw syndrome 값으로, 드라이버가 이를 `ibv_wc_status`로 변환할 때 여러 syndrome이 하나의 status로 합쳐질 수 있다. 즉 `ibv_wc_status` 하나로는 원인을 구분하지 못하는 경우가 생긴다.

이 절은 10개 fault scenario를 의도적으로 주입(inject)하고 각각의 (`ibv_wc_status`, `vendor_err`, 의미, injection 방법, detection latency)를 실측해, status code가 원인을 가리지 못하는 지점을 `vendor_err`로 어디까지 풀어낼 수 있는지 정리한다. 이어서 server 측 counter의 증가 시점을 역추론해 ConnectX-5 responder의 내부 처리 순서를 규명하고, error NAK 이후 server QP의 상태 전이까지 다룬다.

실험 환경: client 225(ConnectX-6 MT28908, firmware 20.40.1000) → server 224(ConnectX-5 MT27800, firmware 16.35.8002), 100 Gbps RoCE v2. heterogeneous NIC pair. fault injection 시점에 in-flight WR을 1개로 제한해 counter delta를 깨끗하게 격리. 빠른 에러는 N=100, timeout 에러는 N=30 (2026-06-04 재측정, NIC rename 경로 버그 수정 후 — 225 NIC이 `mlx5_0`에서 `rocep1s0f0`로 udev rename되어 client counter sysfs 경로가 무효였던 것을 동적 device resolve로 수정. 상세는 부록 A). 단, `vendor_err`·`ibv_wc_status`·server counter·QP state는 RDMA 연결이 fallback으로 정상 동작했으므로 rename 이전 측정값도 유효하다.

### 4.2 10개 fault scenario 전체 표

각 시나리오의 의미, injection 방법, 두 식별 필드, detection latency를 한 표에 정리한다. latency는 N=100/N=30 재측정 median이며, NAK 3종은 host scheduler jitter로 bimodal이라 절대값보다 분포 폭이 더 의미 있다(4.5절).

| 시나리오(의미) | ibv_wc_status | vendor_err | injection 방법 | detection latency (median) | N |
|---|---|---|---|---|---|
| SGE length 초과 | LOC_PROT_ERR (4) | 0x53 | client에서 SGE.length를 MR 크기보다 크게 설정 | 1.50 ms | 100 |
| invalid lkey | LOC_PROT_ERR (4) | 0x52 | client에서 존재하지 않는 lkey로 WQE 구성 | 0.32 ms | 100 |
| MR 권한 위반 | LOC_PROT_ERR (4) | 0x33 | LOCAL_WRITE 없는(access=0) MR을 대상으로 RDMA READ 발행 | 1.50 ms | 100 |
| 서버 QP ERR flush (WR_FLUSH_ERR) | WR_FLUSH_ERR (5) | 0xf5 | client QP를 `ibv_modify_qp(ERR)`로 전환 후 WQE post | 0.52 ms | 100 |
| REMOTE_WRITE 권한 없음 | REM_INV_REQ_ERR (9) | 0x8a | server QP access flags에서 REMOTE_WRITE 제외 | 1.64 ms (bimodal) | 100 |
| invalid rkey | REM_ACCESS_ERR (10) | 0x88 | client에서 잘못된 rkey로 RDMA WRITE | 1.74 ms (bimodal) | 100 |
| 주소 범위 초과 | REM_ACCESS_ERR (10) | 0x88 | rkey는 유효하나 remote_addr를 MR 범위 밖으로 설정 | 0.57 ms (bimodal) | 100 |
| recv buffer 부족 | RNR_RETRY_EXC_ERR (13) | 0x87 | SEND/RECV에서 server가 recv WQE 미게시 | 0.26 ms | 100 |
| 서버 QP ERR | RETRY_EXC_ERR (12) | 0x81 | server에서 `ibv_modify_qp(ERR)` → ACK 중단 | 3.56 s | 30 |
| 프로세스 kill | RETRY_EXC_ERR (12) | 0x81 | server 프로세스 `kill -9` → QP 리소스 해제 | 5.13 s* | 30 |
| link down (재현 실패) | — | — | `ip link set <dev> down` | — | 3 |

`*` 프로세스 kill의 5.13 s(N=30, std 116 ms)는 injection 코드 내부의 2-phase signal coordination + `sleep(1s)`가 포함된 측정값으로 실제 detection이 아니다. RETRY_EXC_ERR의 실측 retry exhaustion은 서버 QP ERR의 3.56 s다(둘은 같은 retry state machine을 타며, retry counter signature가 30/30 동일하다 — 4.6절 참조).

link down은 fault scenario로 의도했으나 재현에 실패했다. `ip link set <dev> down`은 kernel network interface만 비활성화하는데, RoCE는 kernel network stack을 bypass하고 user-space(libibverbs)에서 NIC hardware에 직접 접근하므로 RDMA data path가 끊기지 않는다. 3 trial 모두 WRITE가 status=0(SUCCESS)으로 성공했다. 같은 이유로 `tc netem`(패킷 지연/손실 주입), `iptables`(방화벽)도 RDMA에 무효임을 확인했다. RoCE에서 실제 link 장애를 재현하려면 물리 케이블을 뽑거나 switch port를 내려야 한다.

### 4.3 status code가 합쳐지는 지점과 vendor_err의 분해력

위 표에서 같은 `ibv_wc_status`가 서로 다른 원인을 가리는 구간이 셋 있다. `vendor_err`가 이 중 하나(LOC_PROT_ERR)를 완전히 풀어낸다.

| ibv_wc_status | 묶인 원인 | vendor_err로 구분되는가 |
|---|---|---|
| LOC_PROT_ERR | SGE length 초과 / invalid lkey / MR 권한 위반 | 가능. 0x53 / 0x52 / 0x33으로 3종 완전 구분 |
| REM_ACCESS_ERR | invalid rkey / 주소 범위 초과 | 불가능. 둘 다 0x88로 동일 |
| RETRY_EXC_ERR | 서버 QP ERR / 프로세스 kill / link down | 불가능. 둘 다 0x81로 동일 (link down은 재현 실패) |

LOC_PROT_ERR 3종이 `vendor_err`로 갈리는 것은, 세 에러가 NIC 내부의 서로 다른 검증 경로(SGE 범위 검사 / lkey 테이블 lookup / MR 권한 비트 검사)에서 발생하고 각 경로가 고유 syndrome을 남기기 때문이다. N=100에서 100% deterministic하다.

반면 REM_ACCESS_ERR 2종과 RETRY_EXC_ERR 2종이 `vendor_err`로도 안 갈리는 것은 NIC이 그 두 경우를 내부적으로 동일하게 처리하기 때문이다. invalid rkey와 주소 범위 초과는 server firmware에서 둘 다 동일한 "Remote Access Error" NAK으로 귀결되고, 서버 QP ERR과 프로세스 kill은 client NIC 관점에서 모두 "보냈는데 ACK가 안 온다"로 완전히 동일하다. RETRY_EXC_ERR의 경우 NIC 자체가 원인을 모른다 — ACK 부재라는 사실만 알 뿐이므로 syndrome도 0x81 하나로 고정된다.

이 두 미구분 쌍은 CQE 바깥의 신호로 갈리는지가 다르다. RETRY_EXC_ERR(서버 QP ERR ≡ 프로세스 kill)는 ethtool의 non-RDMA TCP sideband packet 수로 구분된다(서버 process alive 시 TCP 정상 종료로 12-13 packet vs `kill -9` 시 TCP RST로 8 packet — RDMA packet은 양쪽 모두 15로 동일). 반면 REM_ACCESS_ERR(invalid rkey ≡ 주소 범위 초과)는 sysfs/ethtool/register 어느 counter source로도 갈리지 않는 최종 indistinguishable pair로 남는다(상세는 5절). 단, counter가 아닌 data-plane 검증으로는 갈린다 — invalid rkey는 key check에서 실패해 DMA 자체가 일어나지 않지만, 주소 범위 초과는 시작 주소가 MR 안이고 끝이 MR 밖인 multi-packet WRITE에서 MR 안쪽 packet이 먼저 DMA된 뒤 다음 packet에서 거부되어 partial write가 발생한다. 즉 두 원인은 counter로는 불가분이나 server 메모리 내용으로는 구분 가능하다(partial write data-plane 복원은 experiments 문서의 "5. Partial write와 data-plane 복원, A/B recovery 실험" 참조).

### 4.4 3-category 분류

10개 시나리오는 에러가 발생하는 위치와 wire 동작에 따라 세 범주로 나뉜다.

| Category | 시나리오 | 공통 특성 | wire RDMA packet | server counter |
|---|---|---|---|---|
| Local | SGE length 초과, invalid lkey, MR 권한 위반, WR_FLUSH_ERR | client NIC이 자기 메모리 접근/QP 상태에서 실패 | 0–5 (대부분 wire 미진입) | 변화 없음 (MR 권한 위반은 rx_read_requests +1 예외) |
| Error NAK | REMOTE_WRITE 권한 없음, invalid rkey, 주소 범위 초과 | 패킷이 server에 도달, server가 거부 NAK 전송 | 1–2 | 시나리오별 상이 |
| Timeout | 서버 QP ERR, 프로세스 kill | 패킷 전송됐으나 ACK 무응답, retry 소진 | 15 (retry amplification) | 변화 없음 |

wire RDMA packet 수는 ethtool `tx_vport_rdma_unicast_packets` delta로, error pipeline의 진행 단계를 그대로 노출한다: 0(WR_FLUSH, pre-post) / 1(lkey·REMOTE_WRITE 권한 없음·RNR, post-immediate) / 2(MR 권한 위반·rkey·addr, operation-level) / 5(SGE length, mid-DMA) / 15(QP ERR·kill, retry exhaustion).

경계가 깔끔하지 않은 예외가 하나 있다. MR 권한 위반은 `ibv_wc_status`가 LOC_PROT_ERR(로컬 에러)이지만, 실제로는 RDMA READ 요청이 server에 도달한 뒤(server `rx_read_requests` +1) READ 응답 데이터를 로컬 MR에 쓰려는 시점에 에러가 난다. 에러 탐지는 로컬이지만 패킷은 wire를 타고 원격 왕복을 거친다. SGE length 초과·invalid lkey가 패킷 전송 전 에러인 것과 대비된다.

### 4.5 Detection latency: 분류 신호로는 부적합

latency는 N=100 재측정에서 일관되지 않게 나타나, 분류 신호로 쓰기 어렵다는 점이 확인됐다.

| 에러 (vendor_err) | median | mean | std | min–max | 비고 |
|---|---|---|---|---|---|
| invalid lkey (0x52) | 0.32 ms | 0.36 ms | 0.20 ms | 0.32–1.55 ms | 즉시 거부(wire packet 0), 97/100 안정 |
| recv buffer 부족 (0x87) | 0.26 ms | 0.26 ms | 0.01 ms | 0.25–0.29 ms | 최안정 |
| WR_FLUSH_ERR (0xf5) | 0.52 ms | 0.52 ms | 0.06 ms | 0.40–0.69 ms | SW flush, 안정 |
| SGE length 초과 (0x53) | 1.50 ms | 1.50 ms | 0.04 ms | 1.49–1.90 ms | wire 5 packet 후 감지, 안정 |
| MR 권한 위반 (0x33) | 1.50 ms | 1.50 ms | 0.20 ms | 0.35–1.71 ms | RDMA READ 왕복 |
| REMOTE_WRITE 권한 없음 (0x8a) | 1.64 ms | 1.08 ms | 0.58 ms | 0.47–1.75 ms | bimodal |
| invalid rkey (0x88) | 1.74 ms | 1.42 ms | 0.58 ms | 0.55–2.01 ms | bimodal |
| 주소 범위 초과 (0x88) | 0.57 ms | 1.05 ms | 0.76 ms | 0.56–3.21 ms | bimodal |
| RETRY_EXC_ERR (0x81, 서버 QP ERR) | 3.56 s | 3.56 s | 30 ms | 3.54–3.71 s | 실측 retry exhaustion (N=30) |

발견 둘. 첫째, invalid lkey는 기존 N=10에서 "약 1.5 ms"로 잘못 보고됐으나 N=100 median은 0.32 ms로, SGE length·MR 권한 위반(약 1.5 ms)과 분리된다. lkey는 wire packet 0개로 즉시 거부되는 반면 length는 5 packet을 전송한 뒤 감지되기 때문에(NIC이 MR boundary를 pre-validate하지 않고 DMA 시작 후 감지), latency가 error pipeline의 진행 단계를 그대로 반영한다.

둘째, NAK 3종(REMOTE_WRITE 권한 없음, invalid rkey, 주소 범위 초과)은 약 0.5 ms와 약 1.6 ms 두 모드를 오가는 bimodal 분포를 보이며 std가 582–761 us에 이른다(두 모드 차 약 1 ms로 일정). 이는 busy-poll(`poll_cq_block`) 중 OS scheduler가 CPU를 양보하면서 생기는 실행 내 phase shift로 추정되며, 어느 모드가 먼저 나오는지는 실행마다 다르다(warmup 효과가 아님). 같은 N=100에서 `vendor_err`와 counter는 100% deterministic인데 latency만 host 환경에 의존한다. 반대로 timeout 2종의 firmware retry counter는 흔들리지 않는다 — 서버 QP ERR·프로세스 kill 모두 N=30 전부에서 `local_ack_timeout_err` +6, `roce_adp_retrans` +8로 동일하다. 따라서 latency는 분류 신호로 부적합하고, 이것이 곧 CQE(`vendor_err`)·counter 기반 분류를 정당화하는 근거가 된다. latency 절대값을 보고하려면 CPU pinning/core isolation이 필요하다(분포 분석은 experiments 문서의 "6. Latency 분포 분석").

### 4.6 서버 responder pipeline 역추론

server 측 counter의 증가 여부를 비교하면, firmware 소스 없이 외부 관측만으로 ConnectX-5 responder의 내부 처리 순서를 알아낼 수 있다. 핵심은 `rx_write_requests` counter의 증가 시점이다.

server `rx_write_requests`는 QP access capability check를 통과한 후, MR-level 검증(rkey lookup, 주소 범위 확인) 전에 카운트된다. 따라서 같은 RDMA WRITE라도 어느 단계에서 거부됐는지에 따라 delta가 갈린다.

| 시나리오 | server rx_write_requests | 해석: 어느 stage에서 거부 |
|---|---|---|
| REMOTE_WRITE 권한 없음 | 0 | Stage 1(QP access check) 이전에 거부 |
| invalid rkey | +1 | Stage 1 통과 → Stage 2(rkey 검증)에서 거부 |
| 주소 범위 초과 | +1 | Stage 1·2 통과 → Stage 3(주소 범위)에서 거부 |

이로부터 responder pipeline을 다음과 같이 복원한다.

```text
패킷 수신 → [Stage 1] QP access flags (REMOTE_WRITE 허용?)
        → [counter: rx_write_requests +1]
        → [Stage 2] rkey 검증 (rkey 유효?)
        → [Stage 3] 주소 범위 (MR 안?)
        → DMA write
```

REMOTE_WRITE 권한 없음은 Stage 1에서 막히므로 counter가 0이고, invalid rkey와 주소 범위 초과는 Stage 1을 통과하므로 +1이 된다. counter는 Stage 1과 Stage 2 사이에 위치한다. invalid rkey(Stage 2 실패)와 주소 범위 초과(Stage 3 실패) 사이에는 public counter가 없어, 두 단계는 외부 counter로 구분되지 않는다 — 이것이 앞서 본 0x88 미구분 쌍의 구조적 원인이다.

MR 권한 위반은 RDMA READ였음이 server `rx_read_requests` +1로 확인된다(WRITE가 아니라 READ 경로). recv buffer 부족은 server `out_of_buffer` +1로, RNR NAK 경로가 별도임을 보여준다.

### 4.7 NAK은 서버 error counter를 올리지 않는다

세 Error NAK 시나리오(REMOTE_WRITE 권한 없음, invalid rkey, 주소 범위 초과)에서 server가 NAK을 보냈음에도, server의 `resp_cqe_error`, `resp_remote_access_errors` 같은 error counter는 모두 0이었다(10 scenario 전부에서 server error counter 0). 증가한 server counter는 위 표의 "정상 request 수신" counter(`rx_write_requests`, `rx_read_requests`, `out_of_buffer`)뿐이다.

이유는 one-sided RDMA의 특성이다. RDMA WRITE는 server software가 모르는 작업이라 server NIC이 알아서 처리하고 server software에 CQE를 생성하지 않는다. CQE가 없으니 CQE-기반 error counter도 오르지 않는다. NAK은 wire-level protocol mechanism으로 NIC이 직접 처리하며, software-visible error event가 아니다. 결과적으로 에러는 requester(client) counter(`req_remote_invalid_request`, `req_remote_access_errors`)에서만 보인다. RDMA monitoring을 server error counter에만 의존해 구축하면 NAK-generating 에러를 전부 놓친다.

### 4.8 Error NAK 후 서버 QP도 ERR로 전이한다 (RNR만 예외)

"server error counter가 0이니 server QP는 정상(RTS)을 유지하고 client만 recovery하면 된다"는 추론은 틀렸다. IBA spec은 RC QP의 responder가 Error NAK(Remote Access Error, Remote Invalid Request)을 생성하면 해당 QP가 Error State로 전이한다고 규정한다. RNR NAK만 예외로, flow control mechanism이므로 QP 상태에 영향을 주지 않는다.

`ibv_query_qp`로 server QP 상태를 직접 검증했다 (N=10, 100% deterministic).

| 시나리오 | NAK 종류 | 서버 QP 상태 (before → after) |
|---|---|---|
| REMOTE_WRITE 권한 없음 | Invalid Request NAK | RTS → ERR |
| invalid rkey | Remote Access NAK | RTS → ERR |
| 주소 범위 초과 | Remote Access NAK | RTS → ERR |
| recv buffer 부족 | RNR NAK | RTS → RTS (유지) |
| 서버 QP ERR | 없음 (control) | RTS → ERR |

ConnectX-5가 IBA spec을 정확히 따른다. 함의가 둘 있다. 첫째, Error NAK 후 recovery는 client QP만으로 끝나지 않고 양쪽 QP 모두 필요하다(bilateral recovery). 둘째, server QP는 ERR로 전이했지만 이를 알리는 counter나 CQE가 없으므로(error counter 0), server software는 `ibv_query_qp`를 명시적으로 호출하지 않으면 자신의 QP가 ERR에 빠진 것을 알 수 없다. error visibility가 requester에 구조적으로 편향된 결과다.

### 4.9 이 절의 결론

`ibv_wc_status` 단독은 10개 시나리오를 6종으로만 구분한다(LOC_PROT_ERR 3종, REM_ACCESS_ERR 2종, RETRY_EXC_ERR 2종이 각각 합쳐짐). `vendor_err`를 더하면 LOC_PROT_ERR 3종이 0x53/0x52/0x33으로 완전히 풀려 8종까지 분해된다. 남는 두 미구분 쌍 중 RETRY_EXC_ERR(서버 QP ERR ≡ 프로세스 kill)는 ethtool TCP sideband로 9종까지 갈리지만, REM_ACCESS_ERR(0x88, invalid rkey ≡ 주소 범위 초과)는 responder pipeline에서 Stage 2와 Stage 3 사이에 counter가 없는 firmware 구조 탓에 어떤 counter 신호로도 구분되지 않는다(data-plane 검증으로만 partial write 차이로 갈림). detection latency는 host scheduler jitter로 bimodal해 분류 신호로 부적합하며, 이는 deterministic한 `vendor_err`/counter 기반 분류의 정당성을 뒷받침한다. responder는 NAK 전송 시 error counter를 올리지 않고 QP만 조용히 ERR로 전이시켜(RNR 제외), error 가시성이 requester에 편향되고 recovery가 bilateral해야 함을 함의한다.
