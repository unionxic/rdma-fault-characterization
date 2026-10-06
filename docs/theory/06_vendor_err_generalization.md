# vendor_err 일반화

> [이론 문서 인덱스](README.md)

이 절은 우리가 mlx5에서 관측·세분화한 vendor_err(CQE vendor syndrome) 값들이 다른 NIC 환경에서도 통하는지를 다룬다. 1단계 연구의 generalizability 방어에서 가장 약한 고리가 vendor_err이므로, 어느 범위까지 일반화되고 어디서 깨지는지를 코드 분석, 문헌 조사, swap 실측 세 각도로 확정한다. 분석 시점은 2026-06-02다.

배경 한 줄: ibv_wc_status는 IBA(InfiniBand Architecture) spec이 정의한 24종 추상 에러 코드이고, vendor_err는 그 위에서 벤더가 자유롭게 채우는 추가 syndrome 바이트다. 우리는 ibv_wc_status만으로 원인이 갈라지지 않는 에러(예: RETRY_EXC_ERR)를 vendor_err의 hex 값으로 더 잘게 나눴는데, 이 세분화가 mlx5를 벗어나도 유효한지가 쟁점이다.

### 6.1 왜 이게 문제가 되는가

우리는 RETRY_EXC_ERR처럼 ibv_wc_status만으로는 원인이 구분되지 않는 에러를 vendor_err hex로 세분화했다. 그런데 vendor_err가 특정 칩/펌웨어에서만 유효한 값이라면, 이 세분화에 기반한 분류·recovery는 그 환경 밖에서 무효가 된다. 따라서 "vendor_err가 어느 레이어에서 결정되며 어느 경계까지 동일하게 유지되는가"를 먼저 확정해야 한다.

### 6.2 운반 메커니즘: vendor_err는 firmware raw다 (코드 확정)

CQE(Completion Queue Entry)는 status용 바이트(syndrome)와 vendor용 바이트(vendor_err_synd)를 별개로 싣는다(device.h:813-814). driver는 이 둘을 다르게 처리한다.

| 필드 | 결정 주체 | 경로 | 일반화 함의 |
|------|-----------|------|-------------|
| status (ibv_wc_status) | driver switch(syndrome) | cq.c:288-337에서 syndrome을 ibv_wc_status로 매핑 | mlx5 driver 전반에서 안정(driver-stable) |
| vendor_err (vendor_err_synd) | firmware | 커널 mlx5_ib/cq.c:339 + rdma-core providers/mlx5/cq.c, 양쪽 모두 가공 없이 패스스루 | firmware artifact, fw·세대 의존 가능 |

핵심은 vendor_err가 `cqe->vendor_err_synd` 값을 driver가 그대로 패스스루한다는 것이다(가공 없음). 즉 vendor_err의 hex 값은 driver가 아니라 firmware가 정한다. 반면 status는 driver가 syndrome을 보고 switch로 결정하므로 firmware 세부와 분리되어 안정적이다. (운반 경로의 코드 라인 상세는 3.3절과 부록 A.)

이로부터 두 층의 결론이 나온다.

> status 분류는 robust하다(driver가 결정). vendor_err 세부 hex는 firmware artifact다(firmware·칩 세대 의존).

우리가 관측한 8개 코드 중 7개(0x53/0x52/0x33/0x8a/0x88/0x87/0x81)는 firmware-raw 경로다. 유일한 예외는 WR_FLUSH_ERR의 0xf5로, work request가 SW에서 flush되는 경로(cq.c:419/600)에서는 driver가 상수로 채우고, 그 외 일반 경로에서는 다른 코드들과 마찬가지로 firmware raw다. 이 SW-flush 상수의 실값을 정의하는 매크로 MLX5_CQE_SYNDROME_WR_FLUSH_ERR는 우리 작업 repo의 헤더에는 없으므로, 서버 측 `<linux/mlx5/cq.h>`를 grep해 실제 상수값을 확인해야 한다. [TODO: 확인]

### 6.3 벤더 간: 완전 독립, 일반화 불가 (문헌, 출처 확인)

firmware가 vendor_err를 정한다는 것은 곧 칩 벤더가 다르면 인코딩이 완전히 독립이라는 뜻이다. IBA spec 자체가 vendor_err를 vendor-defined로 열어두었고(verbs man page, RDMAmojo), 각 벤더가 자기 enum을 쓴다.

| 벤더/driver | vendor_err 인코딩 | 비고 |
|-------------|-------------------|------|
| Mellanox/NVIDIA mlx5 | 우리 관측 hex (0x53, 0x88 등) | 공식 문서 없음, customer support로만 해석 |
| AWS EFA | 자체 enum (0–18) | 정수 인덱스 체계 |
| Intel irdma | major<<16 \| minor | 비트필드 합성 |
| Broadcom bnxt_re | BNXT_RE_*_ST | 자체 status 상수 |
| Chelsio cxgb4 | T4_ERR_* | 자체 에러 상수 |

우리 0x53(LOC_PROT_ERR, invalid lkey)과 0x88(REM_ACCESS_ERR, REMOTE_WRITE 권한 없음)은 mlx5 전용 값이며, 다른 driver에 그대로 들고 가면 의미가 전혀 다르다. 따라서 벤더 간 vendor_err 직접 일반화는 불가능하다. 일반화하려면 값을 그대로 쓸 게 아니라 "의미"를 한 층 위에서 잡고, 각 벤더 enum을 그 의미로 재매핑하는 plug-in 방식이어야 한다.

### 6.4 mlx5 세대 내: ConnectX-5 ↔ ConnectX-6 세대 무관 실측 (N=10)

벤더 간 경계는 깨지지만, 같은 mlx5 계열의 세대 간(ConnectX-5 ↔ ConnectX-6)은 어떤가. "firmware raw니까 세대마다 바뀔 수 있다"가 최악 가설이었고, 이를 swap 실험으로 반증했다.

셋업:

| 항목 | 내용 |
|------|------|
| ground truth (ibv_devinfo) | 225 = ConnectX-6 (vendor_part_id 4123, fw 20.40.1000), 224 = ConnectX-5 (vendor_part_id 4119, fw 16.35.8002) |
| 문서 오류 정정 | 당시 노드에 둔 작업 메모(이 저장소에는 없음)가 225를 ConnectX-5로 잘못 적었으나 ibv_devinfo가 정답 |
| 방법 | requester 역할을 ConnectX-5(224, fw 16.35)로 두고 동일 에러를 유발, 기존 ConnectX-6(225, fw 20.40) 결과와 vendor_err를 비교 |
| orchestration | 225 로컬 server + ssh로 224 client 구동. ssh가 225→224 방향만 되므로 run_swap.sh는 225에서 실행 |
| 반복 수 | N=10 (에러 종류별) |

결과 (confound 열은 "이 행의 vendor_err가 어느 쪽 firmware에서 나온 것인지 분리되는가"를 뜻한다):

| 에러 (의미) | vendor_err | ConnectX-6 (fw 20.40) | ConnectX-5 (fw 16.35) | 판정 | confound |
|-------------|-----------|------------------|------------------|------|----------|
| LOC_PROT_ERR (invalid lkey) | 0x53 | 관측 | 동일 | 세대 무관 | 없음(requester-local) |
| LOC_PROT_ERR (MR 권한 위반) | 0x52 | 관측 | 동일 | 세대 무관 | 없음(requester-local) |
| LOC_PROT_ERR (SGE length 초과) | 0x33 | 관측 | 동일 | 세대 무관 | 없음(requester-local) |
| 원격 NAK (REM 계열, 정확한 의미명 미확정) | 0x8a | 관측 | 동일 | 세대 무관 | req+resp 동시 swap |
| REM_ACCESS_ERR (REMOTE_WRITE 권한 없음) | 0x88 | 관측 | 동일 | 세대 무관 | req+resp 동시 swap |

LOC_PROT_ERR 3종(0x53/0x52/0x33)은 requester-local 에러라 한쪽 firmware만 관여하므로 clean하게 세대 무관이 확정된다. 원격 NAK인 0x8a/0x88은 requester와 responder를 동시에 swap한 구성이라 vendor_err가 어느 쪽 firmware에서 비롯됐는지 분리되지 않는 confounded 결과지만, 값이 100% 동일했다는 사실 자체는 유지된다.

> 결론: vendor_err는 firmware raw이지만 mlx5 계열은 syndrome 인코딩을 공유하여 ConnectX-5 ↔ ConnectX-6 세대 무관이다(N=10 실측). 다른 벤더는 칩이 달라 독립이다. "세대 간 불안정" 최악 가설은 반증되었다.

문헌 정황도 이를 뒷받침한다. REM_ACCESS_ERR=0x88은 ConnectX-2부터 ConnectX-6까지 동일하게 보고되고(NVIDIA forum), RETRY_EXC_ERR=0x81은 다수 mlx5 환경에서 공통이다(UCX, NCCL#426=129=0x81, NCCL#214). fw 버전별로 vendor_err가 바뀐 사례는 공개 자료 0건이다. 단, lukego gist는 CQE vendor_err가 아니라 firmware command syndrome을 다루므로 오인하지 않도록 주의한다.

### 6.5 Production 관점에서의 커버리지

세대 무관성을 production 배치 기준으로 환산하면, 우리 실측이 현재 대량 설치 기반의 어디까지를 덮는지가 보인다.

| 세대 | driver | production 위상 | 우리 검증 |
|------|--------|-----------------|-----------|
| ConnectX-2/3 | mlx4 | EOL | 무관(대상 아님) |
| ConnectX-4 | mlx5 | production 설치 기반 | 미실측(같은 mlx5 계열, swap 결과로 외삽되는 정황) |
| ConnectX-5 | mlx5 | 대량 설치 기반 | 실측 (224) |
| ConnectX-6 | mlx5 | 대량 설치 기반 | 실측 (225) |
| ConnectX-7 | mlx5 | H100급 신규 AI 클러스터 주력 (GPU 타겟과 직결) | 미검증 빈칸 (NIC 미확보) |

production RDMA는 사실상 mlx5 계열(ConnectX-4–7)이고, ConnectX-5/6 실측이 현 대량 설치 기반을 커버한다. 유일한 production 미검증 빈칸은 ConnectX-7으로, 우리 GPU 타겟과 가장 직결되지만 NIC 미확보로 보류 상태다. 구체 점유율 수치는 [TODO: 출하/시장 데이터 출처].

### 6.6 논문 framing

이상을 종합하면, generalizability를 레이어별로 다르게 주장하는 것이 정확하다.

| 자산 | 일반화 주장 | 근거 |
|------|-------------|------|
| methodology (분류·재현·detection 절차) | vendor-agnostic | 절차는 칩과 독립 |
| status (ibv_wc_status 분류) | mlx5-stable | driver가 syndrome→status 결정(cq.c:288-337) |
| vendor_err hex (세부 세분화) | mlx5 firmware artifact, 일부 세대 안정 (ConnectX-5↔6 실측) | swap N=10 + 문헌 정황 |
| 타 벤더(EFA/irdma/bnxt_re/cxgb4) | plug-in 재매핑 필요 | 각자 독립 enum, 직접 일반화 불가 |

즉 vendor_err를 "어디서나 통하는 값"으로 과대 주장하지 않고 mlx5 firmware artifact로 정직하게 framing하되, 세대 무관성은 실측으로 받치고, 타 벤더는 재매핑 인터페이스로 흡수한다는 것이 방어선이다.

### 6.7 남은 검증

| 항목 | 상태 |
|------|------|
| ConnectX-7 / 타 fw / 타 벤더 | NIC 미확보로 보류 |
| WR_FLUSH_ERR 0xf5 상수값 (MLX5_CQE_SYNDROME_WR_FLUSH_ERR) | 서버 `<linux/mlx5/cq.h>` grep 필요 [TODO: 확인] |
| 원격 NAK(0x8a/0x88) confound 해소 | requester/responder 중 한쪽만 swap하는 분리 실험 필요 |
