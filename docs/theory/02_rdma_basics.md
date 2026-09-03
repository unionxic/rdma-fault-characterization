# RDMA 이론 기초

> [이론 문서 인덱스](README.md)

이 절은 이후의 모든 실험(에러 코드 분류, counter signature, recovery latency)을 읽기 위한 최소한의 이론 토대를 자기완결적으로 정리한다. "왜 server counter가 0이었나", "왜 detection이 약 3.7s 걸렸나" 같은 질문에 곧바로 연결되도록 메커니즘을 단계별로 푼다. 실험에서 확인된 사실과 IBA spec 정의를 명시적으로 구분한다.

### 2.1 DMA에서 RDMA로 — 왜 CPU를 빼는가

일반적인 네트워크 통신은 데이터가 이동할 때마다 양쪽 CPU와 OS 커널이 개입한다. 보내는 쪽은 system call → 커널 버퍼 복사 → 프로토콜 처리 → NIC 드라이버를 거치고, 받는 쪽은 interrupt → 커널 버퍼 복사 → socket 처리를 거친다. 데이터가 application 메모리 → 커널 메모리 → NIC, 반대쪽에서 다시 NIC → 커널 메모리 → application 메모리로 여러 번 복사된다.

규모가 커지면 이 구조가 병목이 된다. AI 학습에서 GPU 수백약 수천 개가 매 통신 라운드마다 gradient를 교환하면, 한 라운드에 수천만 건의 메시지가 오가고, 이때 매번 CPU를 거치면 CPU가 통신 처리에만 매달려 정작 모델 계산을 못 한다. 메모리도 GPU 메모리 → CPU 메모리 → 네트워크 → CPU 메모리 → GPU 메모리로 불필요한 복사가 누적된다.

이를 줄이는 첫 단계가 DMA(Direct Memory Access)다. DMA는 NIC이 CPU를 거치지 않고 PCIe 버스를 통해 host 메모리에 직접 접근하는 기술이다. CPU는 "주소 0x1000에서 1MB를 직접 읽어서 보내라"고 지시만 하고 데이터 이동에서 빠진다. 완료되면 NIC이 interrupt로 알린다.

RDMA(Remote Direct Memory Access)는 이 DMA를 원격으로 확장한 것이다. 핵심 명제는 다음과 같다.

> 서버 B의 CPU를 깨우지 않고, 클라이언트 A의 NIC이 서버 B의 메모리에 직접 데이터를 쓴다.

비유하면 일반 통신이 "전화해서 문 열어달라고 부탁하는 것"이라면, RDMA는 "내가 열쇠를 갖고 있어서 주인을 깨우지 않고 직접 들어가 원하는 것을 놓고 오는 것"이다. 단, 열쇠(rkey)가 있어야 들어갈 수 있고, 허용된 서랍(MR)에만 접근할 수 있다. 이 비유의 "열쇠"와 "서랍"이 각각 2.4절의 key와 MR에 대응한다.

| 구분 | 일반 TCP/IP | DMA | RDMA |
|---|---|---|---|
| 메모리 ↔ NIC 데이터 이동 | CPU가 복사 | NIC이 직접 접근 (로컬) | NIC이 직접 접근 (로컬 + 원격) |
| 원격 메모리 접근 | 원격 CPU/OS 경유 | 해당 없음 | 원격 NIC이 직접 write/read |
| CPU 개입 | 양쪽 모두 | 로컬 지시만 | 원격은 0회 (one-sided 시) |

### 2.2 kernel bypass — RDMA를 이해하는 핵심 개념

RDMA의 성능과 동시에 이후 실험의 여러 negative finding을 결정짓는 단 하나의 개념이 kernel bypass다. RDMA는 OS의 네트워크 스택을 거치지 않고, user-space library(libibverbs)가 NIC hardware에 직접 접근한다.

```
일반 TCP/IP:
    프로그램 → 소켓 API → 커널 네트워크 스택 → 커널 NIC 드라이버 → NIC 하드웨어

RoCE RDMA:
    프로그램 → libibverbs (user-space) → NIC 하드웨어 직접
                            ↑ 커널 스택을 건너뜀
```

이 구조의 직접적 귀결은 "커널 네트워크 스택을 조작하는 도구는 RDMA data path에 영향을 주지 못한다"는 것이다. 세 가지를 실험으로 확인했다.

| 도구 | 동작 계층 | RDMA(RoCE)에 대한 효과 |
|---|---|---|
| `tc netem` (지연/손실 주입) | 커널 네트워크 스택 | 무효 (data path가 스택을 bypass) |
| `iptables` (방화벽) | 커널 네트워크 스택 | 무효 |
| `ip link set down` | 커널 인터페이스 비활성화 | 무효 (RDMA WRITE 계속 성공) |

`ip link set down`은 실제 link down 시나리오(RETRY_EXC_ERR 재현 시도)에서 적용했으나 RDMA WRITE가 계속 성공했다. 따라서 RoCE에서 실제 링크 장애를 재현하려면 물리 케이블을 뽑거나 스위치 포트를 내려야 한다. kernel bypass는 RDMA의 장점(낮은 latency)이자, fault injection 방법론을 제약하는 근본 원인이다.

### 2.3 통신 채널의 단위 — QP / SQ / CQ / CQE / WQE

RDMA 통신은 QP(Queue Pair)라는 전용 채널 위에서 이뤄진다. QP는 TCP socket과 비슷한 연결 단위지만, OS를 거치지 않는다는 점이 다르다. 이름이 "pair"인 이유는 두 개의 작업 큐(Send Queue, Receive Queue)를 가지기 때문이다. 이 문서의 실험은 대부분 RDMA WRITE를 다루므로 Send Queue 쪽을 중심으로 설명한다.

| 약어 | 풀네임 | 역할 |
|---|---|---|
| QP | Queue Pair | RDMA 통신의 전용 채널 (연결 단위) |
| SQ | Send Queue | 보낼 작업(WQE)을 넣는 큐 |
| CQ | Completion Queue | 보내거나 받은 작업이 완료되면 그 결과(CQE)가 쌓이는 큐 |
| WQE | Work Queue Element | 처리할 작업 하나의 명세 (대상 주소, 길이, lkey, rkey 등) |
| CQE | Completion Queue Entry | 완료된 작업 하나의 결과 항목 (성공/실패, status, vendor_err) |

데이터 흐름의 골격은 다음과 같다. 애플리케이션은 "무엇을 어디로 어떻게 보낼지"를 적은 WQE를 SQ에 넣고(post), NIC이 그것을 처리한 뒤 결과를 CQE로 CQ에 쌓는다. 애플리케이션은 CQ를 polling해서 CQE를 읽고 성공/실패를 판정한다. 이 polling-기반 completion 확인은 kernel bypass의 직접적 결과다 — interrupt와 system call 없이 user-space에서 완료를 확인한다.

CQE는 이후 에러 분석의 1차 관측 지점이다. 작업이 실패하면 CQE에 두 개의 필드가 담긴다: IBA 표준 상태 코드인 `ibv_wc_status`(성공 시 `IBV_WC_SUCCESS`, IBA spec상 24종 정의)와, mlx5에서 hardware syndrome을 그대로 담는 vendor_err. 이 두 필드의 의미와 관계는 3절에서 다루므로 여기서는 "CQE가 완료 결과를 담는 자리이며, 에러 시 status + vendor_err를 노출한다"는 사실만 확보한다.

### 2.4 메모리 등록 — MR과 lkey/rkey

RDMA가 메모리에 직접 접근하려면, 그 메모리가 사전에 "등록"되어 있어야 한다. 이 등록 단위가 MR(Memory Region)이다. `ibv_reg_mr()` 한 번의 호출이 세 가지 일을 한다.

| 단계 | 하는 일 | 이유 |
|---|---|---|
| 1. pin | 해당 메모리 페이지를 물리 메모리에 고정 (swap-out 차단) | 페이지가 swap되면 NIC이 DMA 시 엉뚱한 물리 주소를 읽게 됨 |
| 2. 주소 변환 등록 | 가상 주소 → 물리 주소 변환 테이블을 만들어 NIC에 등록 | NIC의 MMU가 이 테이블을 참조해 직접 접근 |
| 3. 키 발급 | lkey와 rkey 두 개의 접근 키 발급 | 권한·범위 검증의 토큰 |

두 키의 역할은 다음과 같다.

| 키 | 검증 주체 | 어디에 포함되나 | 무엇을 보장하나 |
|---|---|---|---|
| lkey (local key) | 로컬 NIC | 로컬 WQE의 SGE | 내 NIC이 내 메모리에 DMA 접근할 때 이 키가 맞는지 확인 |
| rkey (remote key) | 원격(서버) NIC | 원격 WRITE/READ 요청 패킷 | 상대 NIC이 "이 키가 맞으니 이 메모리에 써도 된다"고 허용 |

여기서 한 가지 IBA 제약이 이후 실험 설계에 영향을 준다: REMOTE_WRITE 권한을 부여하려면 반드시 LOCAL_WRITE도 함께 부여해야 한다. 따라서 "LOCAL_WRITE가 없는 MR"을 만들려면 access flag를 0으로 등록해야 한다 (MR 권한 위반 시나리오의 기반: access=0 MR을 대상으로 RDMA READ를 발행하면, 서버에서 읽어온 데이터를 로컬 MR에 쓸 LOCAL_WRITE 권한이 없어 LOC_PROT_ERR이 난다).

또한 RDMA WRITE가 성립하려면 권한이 두 곳에서 설정되어야 한다(실측). 서버 QP init의 `qp_access_flags`에 REMOTE_WRITE가 있어야 하고, 서버 `ibv_reg_mr`의 MR access flags에도 REMOTE_WRITE가 있어야 한다. 둘 중 하나라도 빠지면 에러가 난다. 이 "QP-level 권한"과 "MR-level 권한"의 분리는 2.6절 responder 검증 파이프라인에서 서로 다른 stage로 나타난다.

### 2.5 QP 상태 기계 — RESET → INIT → RTR → RTS → ERR

QP는 상태 기계(state machine)다. 생성 직후 RESET 상태이며, 데이터를 보내려면 단계를 거쳐 RTS까지 올려야 한다. 각 전이는 `ibv_modify_qp()` 호출로 일어난다.

```
RESET → INIT → RTR(Ready to Receive) → RTS(Ready to Send)
                                              │ (정상 동작)
                                              ▼
                                             ERR ← (오류 발생 시)
```

| 상태 | 의미 | 이 상태에서 가능한 것 |
|---|---|---|
| RESET | 초기 상태 | 아직 통신 불가, attribute 설정 시작 |
| INIT | 기본 속성 설정됨 | recv WQE post 가능 (전송은 불가) |
| RTR | Ready to Receive | 원격 정보(QPN, PSN, GID) 설정 완료, 수신 가능 |
| RTS | Ready to Send | WQE post 후 실제 전송 가능 (정상 동작 상태) |
| ERR | 오류 상태 | 진행 중/이후 WQE가 모두 flush, 재사용 불가 |

ERR 상태는 두 방향에서 중요하다. 첫째, RTS 상태에서 오류가 발생하면 QP가 ERR로 떨어지고, 이후 post되는 WQE는 전송 시도 없이 즉시 flush된다(이것이 `WR_FLUSH_ERR` 발생 메커니즘. QP를 ERR로 강제 전환 후 post하면 latency 약 0.5ms로 전 시나리오 중 가장 짧게 즉시 flush됨을 확인). 둘째, ERR에 빠진 QP는 RESET으로 되돌린 뒤 다시 INIT→RTR→RTS로 올려야 재사용할 수 있다(이것이 recovery latency의 본질로, per-stage 분해는 experiments 문서의 "3. Recovery 방법론" 참조).

여기서 미리 기록해 둘 비대칭이 있다: Error NAK을 보낸 서버 QP도 ERR로 전이하지만, 그 전이를 알리는 CQE나 counter가 없다. 즉 server는 `ibv_query_qp`를 명시적으로 호출하지 않으면 자기 QP가 ERR에 빠진 것을 모를 수 있다. 이 점은 one-sided 특성(2.7절)의 직접적 귀결이다.

### 2.6 RDMA WRITE 한 번의 전체 여정

이제 앞의 요소들을 엮어, RDMA WRITE 한 번이 처음부터 끝까지 어떻게 흐르는지 단계별로 따라간다. 이 여정의 각 단계가 이후 에러 시나리오에서 "어디서 실패했는가"를 가르는 분기점이 되므로, 정확히 이해해 둔다. (검증/DMA read/패킷화 단계를 4a·4b·4c로 세분한다.)

| 단계 | 주체 | 동작 | 어떤 실패가 여기서 갈리나 (참조) |
|---|---|---|---|
| 1 | 클라이언트 SW | WQE를 SQ에 post ("서버 주소 0xABCD에 lkey=… 메모리에서 1MB WRITE") | QP가 ERR면 즉시 flush |
| 2 | 클라이언트 SW | doorbell: NIC 레지스터에 PCIe MMIO write로 "새 작업 있음" 통지 | — |
| 3 | 클라이언트 NIC | doorbell 감지 후 PCIe DMA로 SQ에서 WQE fetch | — |
| 4a | 클라이언트 NIC | 로컬 검증: lkey 확인, SGE.length가 MR 범위 안인지 확인 | invalid lkey / SGE length 초과 → 여기서 거부 |
| 4b | 클라이언트 NIC | 소스 메모리에서 데이터 DMA read | — |
| 4c | 클라이언트 NIC | RoCEv2 헤더 추가하여 패킷화 (대상 주소, rkey, 데이터, PSN) | — |
| 5 | wire | 패킷이 케이블을 통해 서버로 전송 | 4a에서 거부되면 패킷이 wire에 나가지 않음 |
| 6 | 서버 NIC (responder) | rkey 검증 후 문제없으면 서버 메모리에 직접 DMA write | rkey/권한/주소 범위 위반 → NAK (아래 responder 파이프라인) |
| 7 | 서버 NIC | ACK 전송 (RC에서 모든 패킷에 응답) | ACK 없음 → 클라이언트 retry (2.8절) |
| 8 | 클라이언트 NIC | ACK 수신, 완료를 CQE로 CQ에 기록 | — |
| 9 | 클라이언트 SW | CQ polling으로 CQE 읽어 성공/실패 판정 | status + vendor_err 관측 |

이 전체 과정에서 서버 CPU는 한 번도 개입하지 않는다(6단계의 DMA write는 서버 NIC이 단독 수행). 이것이 RDMA WRITE의 핵심이다.

단계 4a(로컬 검증)와 단계 6(원격 검증)이 에러를 가르는 두 관문이다. 로컬 검증에서 걸리면 패킷이 아예 wire에 나가지 않으므로 server counter가 전혀 변하지 않고, 원격 검증에서 걸리면 패킷이 서버에 도달한 흔적(rx_write_requests 등)이 남는다. 이 비대칭이 이후 "장애가 클라이언트 쪽인지 서버 쪽인지"를 counter로 즉시 판별하는 근거가 된다.

서버 responder의 단계 6은 내부적으로 다시 3개의 sub-stage로 나뉘며, 이 순서는 NIC firmware 소스 없이 server counter의 변화 패턴만으로 역추론한 것이다(4절).

```
패킷 수신
   ↓
[Stage 1] QP access flags 확인 ("이 QP가 REMOTE_WRITE를 허용하는가?")
   ├─ 거부 → NAK (rx_write_requests 카운트 시점 이전이므로 server delta=0)
   └─ 허용 → rx_write_requests +1
        ↓
[Stage 2] rkey 검증 ("이 rkey가 유효한가?")
   ├─ 무효 → NAK
   └─ 유효
        ↓
[Stage 3] 주소 범위 확인 ("요청 주소가 MR 범위 안인가?")
   ├─ 초과 → NAK
   └─ 유효 → DMA write 실행
```

이 파이프라인이 2.4절의 "QP-level 권한 vs MR-level 권한" 분리를 구체화한다. QP access(Stage 1)는 MR 검증(Stage 2-3)보다 앞이며, rx_write_requests counter가 정확히 Stage 1과 Stage 2 사이에 위치한다는 것이 외부 관측만으로 확인되었다. 즉 REMOTE_WRITE 권한 없음은 Stage 1에서 거부되어 server rx_write_requests delta=0, invalid rkey와 주소 범위 초과는 Stage 1을 통과해 delta=+1이다.

### 2.7 one-sided 특성과 에러 가시성의 비대칭

RDMA WRITE는 one-sided operation이다. 클라이언트가 서버 메모리에 직접 쓰는 작업이며, 서버 소프트웨어는 이 작업이 일어났다는 사실 자체를 모른다. 서버 NIC이 단독으로 처리하고, 서버 소프트웨어에게는 CQE를 생성하지 않는다.

이 특성의 직접적 귀결이 에러 가시성의 구조적 비대칭이다.

| 관점 | one-sided RDMA WRITE에서 보이는 것 |
|---|---|
| 클라이언트(requester) | 정상 시 CQE(SUCCESS), 에러 시 CQE(status + vendor_err), req_* counter |
| 서버(responder) | 정상 시 CQE 없음 (소프트웨어는 write 발생을 모름), NAK 전송 시에도 software-visible error counter 0 |

NAK은 wire-level protocol mechanism이다. NIC이 직접 생성·처리하는 것이며 소프트웨어 completion event가 아니다. 따라서 서버가 NAK을 보내도 `resp_cqe_error`, `resp_remote_access_errors` 같은 software-visible error counter는 오르지 않는다(실측, 모두 delta=0). 에러의 NIC-level 흔적은 requester counter(req_remote_invalid_request, req_remote_access_errors 등)에서만 보인다.

이것은 RDMA 기반 분산 시스템의 fault isolation을 어렵게 만드는 구조적 특성이다. 에러가 났을 때 서버 로그를 아무리 봐도 아무것도 안 보일 수 있다. 다만 SEND/RECV는 two-sided operation이라 서버가 미리 recv WQE를 post해 두어야 하므로 이 비대칭이 부분적으로 다르게 나타난다(recv buffer 부족 시 서버가 RNR NAK을 보내고 server out_of_buffer가 +1로 오르는 것이 그 예. recv buffer 부족 시나리오의 기반).

### 2.8 RC 프로토콜 — PSN / ACK / NAK / retry

RDMA의 신뢰성 모드인 RC(Reliable Connection)는 모든 패킷에 PSN(Packet Sequence Number)을 붙이고, 각 패킷을 ACK로 확인받아 순서와 도달을 보장한다.

정상 흐름과 retry 흐름은 다음과 같다.

```
정상:
  클라이언트 NIC: 패킷 PSN=100 전송 → 타이머 시작
  서버 NIC:       수신·처리 완료 → ACK 전송
  클라이언트 NIC: ACK 수신 → 타이머 해제, 완료

타임아웃(ACK 미수신):
  클라이언트 NIC: 재전송(retry), 타이머 재시작
                 ...retry_cnt번 반복...
                 retry_cnt 소진 → RETRY_EXC_ERR
```

타이머 만료 시간은 `local_ack_timeout` 파라미터로 제어된다. firmware의 `min_ack_timeout_limit`이 이 값을 override하여, 아무리 작게 설정해도 최소값이 고정되고 이것이 약 3.7s detection latency의 원인이 됨을 확인했다(상세는 experiments 문서의 "1. Detection latency와 firmware retry 분해").

ACK 외에 NAK(Negative Acknowledgment)이 있다. 서버가 요청을 받았지만 처리할 수 없을 때 이유 코드와 함께 돌려보낸다. NAK은 크게 두 종류로 나뉘며, 이 구분이 QP 상태 전이와 직결된다.

| NAK 종류 | 발생 원인 (예) | 의미 | responder QP 상태 영향 (IBA spec) |
|---|---|---|---|
| Error NAK | invalid rkey, REMOTE_WRITE 권한 없음, 주소 범위 초과 | 요청 자체가 잘못됨 | RTS → ERR로 전이 |
| RNR NAK | recv buffer 부족 (Receiver Not Ready) | 일시적으로 받을 수 없음 (flow control) | RTS 유지 (상태 영향 없음) |

IBA spec은 RC QP의 responder가 Error NAK(Remote Access Error, Remote Invalid Request)을 생성하면 해당 QP가 Error State로 전이한다고 규정한다. RNR NAK만 예외로, flow control mechanism이므로 QP 상태에 영향을 주지 않는다. `ibv_query_qp`로 이를 직접 검증했다(N=10, 100% deterministic). 검증 결과는 다음과 같다.

| 시나리오 | NAK 종류 | 서버 QP 상태 (before → after) |
|---|---|---|
| REMOTE_WRITE 권한 없음 (REM_INV_REQ_ERR) | Invalid Request NAK | RTS → ERR |
| invalid rkey (REM_ACCESS_ERR) | Remote Access NAK | RTS → ERR |
| 주소 범위 초과 (REM_ACCESS_ERR) | Remote Access NAK | RTS → ERR |
| recv buffer 부족 (RNR_RETRY_EXC_ERR) | RNR NAK | RTS → RTS |

이 사실은 "Error NAK 후 recovery는 client QP만이 아니라 양쪽 QP 모두 필요하다"는 실용적 결론으로 이어진다.

RC의 retry/ACK/NAK 메커니즘은 이후 timeout 계열 에러(서버 QP ERR, 프로세스 kill: 둘 다 "ACK가 안 온다"로 동일하게 RETRY_EXC_ERR 유발)와 recovery 분석의 직접적 전제다. 실험에서 retry_cnt=7이며, 타임아웃 발생 시마다 재전송하되 마지막 7번째 시도에서는 counter를 올리지 않고 바로 에러 CQE를 생성하므로 `local_ack_timeout_err`는 +6까지만 오른다(local_ack_timeout_err = retry_cnt - 1 = 7 - 1 = 6, 실측). 여기서는 PSN으로 순서를 추적하고, ACK로 도달을 확인하며, 미응답 시 retry하고, retry 소진 시 RETRY_EXC_ERR을 낸다는 골격을 확보한다.

### 2.9 요약 — 이 절이 이후에 연결되는 지점

| 이 절의 개념 | 이후 절에서 설명하는 현상 |
|---|---|
| kernel bypass | tc netem / iptables / ip link set down이 RDMA에 무효 |
| 로컬 검증(단계 4a) vs 원격 검증(단계 6) | client-only counter 변화 vs server counter 변화로 장애 위치 판별 |
| responder 3-stage 파이프라인 | rx_write_requests delta로 REMOTE_WRITE 권한 없음(delta=0) vs invalid rkey(delta=+1) 구분 |
| QP 상태 기계(ERR 전이·복귀) | recovery latency의 per-stage 분해, WR_FLUSH_ERR |
| one-sided 특성 / NAK = wire-level | 서버 software-visible error counter가 0 (에러 가시성 비대칭) |
| RC retry / local_ack_timeout | RETRY_EXC_ERR, 약 3.7s detection latency |
| Error NAK vs RNR NAK의 QP 상태 영향 | 양쪽 QP recovery 필요성 |
