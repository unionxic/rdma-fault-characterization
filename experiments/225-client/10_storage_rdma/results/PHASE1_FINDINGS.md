# Phase 1 (SSD × RDMA) 결과 정리 — 2026-07-15/16 실측

데이터: `raw/storage_rdma.csv` (45 trials: BASELINE 3, MEDIA_ERROR_READ 5,
MEDIA_ERROR_PARTIAL_READ 5, FULL_IO_FAIL 10, FAIL_SLOW 17(sweep 1~35000ms),
TARGET_CRASH 5). 테스트베드: 225(initiator, CX-6) ↔ 224(nvmet-rdma target,
CX-5), file-backed namespace + dm 주입.

## Headline: 관측성 역전 (observability inversion)

**에러가 명시적일수록 RDMA 계층은 조용하고, 에러가 silent할수록 RDMA 카운터가
유일한 신호가 된다.** 두 신호 축(NVMe status ↔ RDMA counter)은 겹치지 않고
상호보완적이다 — cross-layer 관측이 선택이 아니라 필수라는 실증.

| 시나리오 | 앱이 보는 것 (NVMe/errno) | RDMA HW 카운터 | 유일한 판별 신호 |
|---|---|---|---|
| BASELINE | Success (4k p50 ≈ 20µs) | 무결 | — |
| MEDIA_ERROR_READ | **generic Internal Error** (sct 0x0/sc 0x6) | **무결 (에러 카운터 0)** | NVMe status뿐 |
| MEDIA_ERROR_PARTIAL_READ | EIO — 그러나 버퍼에 유효 prefix 2MiB 착지, 경계는 비공개 | 무결 | NVMe status (경계는 어느 계층도 못 줌) |
| FULL_IO_FAIL | **media와 동일한** generic Internal Error | 무결 | 구분 불가 |
| FAIL_SLOW ≤ 5s | **아무것도 없음** — Success, latency만 delay 추종 (p50 ≈ delay+α) | 무결 | latency 분포뿐 |
| FAIL_SLOW 35s (> io_timeout 30s) | **아무것도 없음** — 에러조차 안 돌아옴 (187~220초 hang, 강제 disconnect로만 해제) | **폭발**: resp_cqe_error +7,839 / flush +7,776 / local_ack_timeout_err / roce_adp_retrans / req_transport_retries_exceeded | RDMA 카운터뿐 |
| TARGET_CRASH | 33.36초 후 EIO (±30ms, N=5) | 폭발: resp_cqe_error +2,613 등 | RDMA 카운터 + dmesg |

## 가설 판정

- **H1 (계층 분리) — 확인**: storage 유래 명시적 에러(media/전체 실패)는 NVMe
  캡슐로만 전달되고 RDMA 계층 에러 카운터는 완전 무결 (0/0, 양쪽 노드).
- **H2 (target 붕괴 → RDMA 신호) — 확인**: nvmet 포트 제거 시 RDMA CQE 에러
  카운터 폭발. 에러 표면화 33.36초는 감지가 아니라 **재연결 정책**(attempt 3 ×
  delay 10s)이 지배 — 기존 "3.7s = firmware retry 정책" 발견의 스토리지판.
- **H3 (fail-slow 사각지대) — 확인 + 경계 발견**: io_timeout(30s) 아래에서는
  NVMe·RDMA **어느 계층에도 에러 0** (latency만 신호). io_timeout을 넘으면
  앱은 여전히 에러를 못 보는데(**무한 hang** — 커널이 reset→재연결→재큐 반복)
  RDMA 카운터만 발화한다.

## 추가 발견 (가설 밖)

1. **nvmet 번역 손실**: dm-dust(media)와 dm-flakey(전체 실패)의 블록 계층 EIO가
   전부 동일한 generic Internal Error(sct 0x0/sc 0x6)로 뭉개짐 — initiator는
   media 불량/백엔드 고장/기타를 **원리적으로 구분 불가**. 계층 경계에서 진단
   정보가 손실된다는 논점의 직접 실증.
2. **partial read = RDMA partial write의 쌍둥이**: 4MiB read 실패 시 버퍼에
   정확히 bad-block 경계까지(2,097,152B) 유효 데이터가 착지하지만 read()는
   -1(EIO)만 반환 — 유효 prefix의 존재와 경계를 앱에 알릴 채널이 없음.
   sq_psn 복원/전략 C 연구와 동형 구조.
3. **kernel-consumer CQE 불가시성**: NVMe-oF의 QP는 커널 소유라 wc_status/
   vendor_err를 유저스페이스가 볼 수 없음 — 7절(구현 레이어 제약)의 실증 사례.
   이 실험의 관측 tuple에 wc_status 컬럼이 없는 것 자체가 그 증거.

## 분류축 통합

기존 (status, vendor_err, counter) 3축에 이번 결과로 채워진 새 축:
- **origin-resource**: storage-media / storage-backend / storage-target / (기존 NIC·CPU)
- **detection-modality**: error-code(NVMe) / latency-only / counter-only / hang

## 데이터 주의사항 (canonical 인용 시)

- FAIL_SLOW 35000 pmax(187/220초)는 dd 해제까지의 벽시계로, 강제 disconnect
  대기를 포함 — "무한(>100초 데드라인)"으로만 인용할 것. N=2.
- FULL_IO_FAIL의 dmesg_signature가 'none'인 행 존재 (nvme-cli 경유 에러가 커널
  로그 없이 status로만 반환된 케이스) — status 컬럼이 근거.
- 하네스 수정 이력(무한 블록 계열 7건)은 agent-memory project_storage_rdma.md
  참고. udev probe I/O × 대지연 dm 상호작용은 자체로 재현 가능한 함정.

---

# Phase 1b 결과 (2026-07-17, 27 trials) — 시그널 → 복구 실증

## E1. FAULT_ISOLATION — NVMe 에러는 명령 단위로 격리된다 (3/3)
- 불량 LBA read 20회 **연속** 실패 후에도: 정상 LBA read 전부 성공(rc=0),
  dmesg에 controller reset **없음**(ctrl_reset=no). 연결·컨트롤러 무사.
- RDMA와의 대비가 핵심: RDMA는 에러 1개가 QP 전체를 죽여 재연결(2.8ms~)이
  필수인데, NVMe-oF는 에러가 해당 명령에만 국한 → **복구 = "그 블록만 피하기"**.
- 원시 status `0x6006` = SC 0x06 + **MORE(0x2000) + DNR(0x4000) 비트 세트**.
  (CSV의 DNR=no는 파서가 nvme-cli 출력 문자열만 봐서 생긴 오탐 — 원시값 기준
  DNR=yes. dmesg의 "MORE DNR"와 일치.)
- good_read_us(5~10ms)는 nvme-cli 프로세스 기동 오버헤드 포함 — 성공 여부만
  유효, latency 비교는 BASELINE(fio) 기준을 쓸 것.

## E2. TIMEOUT_TUNING — io_timeout은 hang을 끊는 레버가 아니다 (9/9 still_hang)
- path 디바이스에 io_timeout 5/10/30s 적용 **성공**(notes의 path_io_timeout 확인).
  그러나 9/9 트라이얼 모두 앱은 에러를 못 받고 hang → watchdog(90s)의 강제
  disconnect로만 해제.
- 해석: io_timeout은 **reset 주기만** 바꾼다. reset 후 커널이 I/O를 재큐하는
  한(신뢰성 계약) 루프는 계속된다. hang을 유한 에러로 바꾸는 레버는 연결
  계층(fast_io_fail_tmo)뿐인데 **이 nvme-cli는 그 플래그가 없다** — "정책
  레버의 가용성 자체가 배포 환경 의존"이라는 발견.
- 부수 관측: 강제 disconnect의 해제 소요조차 reset 주기 위상에 따라 6~98s로
  출렁였다(5s: 97~103s에 해제, 10s: 90.5s 즉시, 30s: 188s). **운영자의 개입
  수단도 루프에 종속된다.**
- notes의 fast_io_fail=5s 표기는 상수 출력일 뿐 실제 연결엔 미적용(플래그
  부재) — 해석 시 주의.

## E3. TARGET_RECOVERY — 부활 시간은 reconnect 격자의 산술 (9/9 recovered)
- crash→I/O 재개: T=5s → **17.4~17.5s**, T=15s → **27.3~27.8s**, T=30s → **38.0s**.
- 모델이 정확히 맞는다: 재개 ≈ (restore 이후 첫 reconnect 슬롯, 10s 격자)
  + ~7s(재연결 완료+네임스페이스 재스캔+프로브). restore_to_resume이 T=5/15에서
  ~12s(다음 슬롯까지 대기 포함), T=30에서 ~7.5s(슬롯 직후 restore)인 것이 증거.
- 처방: 죽음 감지는 0.6s(E4)인데 부활 반영은 슬롯 대기가 지배 →
  **reconnect_delay를 줄이면 복구가 그만큼 빨라진다** (정책 = 복구 레버).

## E4. COUNTER_EARLY_DETECT — 카운터는 앱보다 33초 먼저 안다
- crash 모드: `resp_cqe_error` 첫 발화 **613~616ms** vs 앱 에러 33.3~33.7s →
  **lead ≈ 32.7~33.1초** (약 54배 빠름). 3/3 일관.
- failslow 모드: 카운터 발화 **4.4~4.8s**, 앱은 영원히 hang → **lead = ∞**.
  앱이 원리적으로 알 수 없는 장애를 카운터는 수 초 내 알린다.
- 두 모드 모두 첫 신호가 `resp_cqe_error` → 스토리지판 early-detection의
  감시 대상 카운터 확정. (RDMA판 roce_adp_retrans 18.4ms 발견의 확장.)

## 시그널 → 복구 매핑 (Phase 1+1b 종합)

| 시그널 | 실증된 용도 | 복구 액션 |
|---|---|---|
| NVMe status (SCT/SC + DNR/MORE) | per-command 실패 식별, DNR=재시도 무의미 | 해당 블록 회피 (연결 재구축 불필요 — E1) |
| latency 분포 | fail-slow 유일한 사전 신호 (<30s 구간) | p99 감시 → 선제 조치 |
| RDMA counter (resp_cqe_error) | 앱보다 33s(crash)~∞(failslow) 빠른 감지 | 조기 disconnect/failover 트리거 (E4) |
| 연결 정책 (reconnect_delay, ctrl_loss_tmo) | 표면화·복구 시간을 직접 결정 | 튜닝 자체가 복구 수단 (E2·E3) |
| io_timeout | reset 주기만 변경 — **hang 못 끊음** | 단독으로는 레버 아님 (E2) |
