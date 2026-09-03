# 실험과 결과

RDMA subsystem failure/error behavior 연구의 전 실험 실측 기록. 각 문서는 "셋업 + 방법 + 수치 + 결론" 묶음이며, 모든 수치는 원본 실험 데이터(각 실험 코드 디렉토리의 results/ CSV)에서 그대로 인용한다. 문서 간 수치가 충돌하면 아래 canonical 표가 단일 기준이다.

| 문서 | 내용 | 대응 실험 코드 |
|------|------|----------------|
| [01 Detection·firmware retry 분해](01_detection_firmware_retry.md) | 3.7s baseline의 정체(min_ack_timeout_limit), 297배 단축 | 01_cpu_baseline, 02_retry_decomposition, 03_modifyqp |
| [02 Early detection](02_early_detection.md) | counter 감시 기반 조기 감지 (203배 / 3.5배) | 06_recovery/RETRY_EXC_ERR/early_detect |
| [03 Recovery 방법론](03_recovery.md) | QP-only / Full rebuild / Driver reload 비교, CQE sufficiency | 06_recovery |
| [04 Multi-QP isolation](04_multi_qp_isolation.md) | QP-only 격리 복구, CQE per-QP vs counter port-level | 06_recovery/multi_qp |
| [05 Partial write와 A/B recovery](05_partial_write_ab_recovery.md) | sq_psn 기반 data-plane 복원, reactive vs proactive | 05_counter_mapping |
| [06 Latency 분포](06_latency_distribution.md) | N=100 분포, bimodal, latency는 분류 신호로 부적합 | 05_counter_mapping |
| [07 Silent partial 대응 전략](07_silent_partial_strategy.md) | commit-flag / CRC / read-back 3전략 실측 | 05_counter_mapping (silent_strategy) |
| [08 Storage×RDMA 경계 실험](08_storage_rdma.md) | SSD 오류의 RDMA 경계 통과, 관측성 역전 | 10_storage_rdma |

## 핵심 수치 canonical (정합성 기준)
본문 여러 섹션이 같은 수치를 다르게 인용하는 경우가 있다. 충돌 시 아래 값을 기준으로 본다.

| 항목 | 기준값 | 정의·출처 | 주의 |
|------|--------|-----------|------|
| RETRY_EXC_ERR detection baseline | 약 3.7 s | CQ tight-loop 측정. 프로세스 kill 3,701 ± 8.5 ms, link down 3,701 ± 10.3 ms (N=100) | 서버 QP ERR은 cpu_baseline에서 N=1만 저장(3,748 ± 11.9 ms, 데이터 손실). 유효 canonical은 counter_mapping 재측정 3.56s ± 30 ms (N=30) |
| firmware retry 산술 모델 | 429 + 6 × 537 ≈ 3,651 ms | min_ack_timeout_limit floor 분해 | 본문에서 "3.5 s"로 표기된 곳은 이 retry timeout을 가리킴 (측정 baseline 3.7s와 구분) |
| min_ack_timeout_limit 비활성 (R=7) | 12.26 ms | N=30 실측 (추정 아님) | |
| detection 단축비 | 약 297배 | 3,651ms ÷ 12.26ms ≈ 297 (산술 모델 기준) | 측정 baseline 3.7s 기준이면 약 302배. 본문의 "297배"는 산술 모델 기준 |
| recovery latency | QP-only 2.8 ms / Full rebuild 9.6 ms / Driver reload 7.9 s | recovery 실험 (RETRY_EXC_ERR, N=10) | |
| Driver reload ÷ QP-only | 약 2,845배 | 7,889,068 ÷ 2,773 = 2,845 | 원본 문서(recovery_results_summary.md)는 2,847배로 표기 — 반올림/오기. 실계산은 2,845 |
| 프로세스 kill detection | 3,701 ± 8.5 ms (N=100) | cpu_baseline | counter_mapping의 5.13 s는 inject 코드의 signal + sleep(1s) coordination이 포함된 artifact (실 detection 아님) |
| A/B 실험 A recover | 42.7 ms (아티팩트 포함) | ab_recovery.csv 실측 ([05 문서](05_partial_write_ab_recovery.md)) | 2026-07-15 판명: 224 `05_counter_mapping/server.c`의 accept 소켓 TCP_NODELAY 누락 → 40 ms delayed-ACK floor 혼입. 수정 완료, silent 전략 실험에서 동일 시퀀스 recover 2,833–2,889 µs 실측으로 검증(아티팩트 재현 0/300). ab_recovery 재실행 대기 — §5.6 배수(228배/1851배)는 약 1/15로 축소 예상, B 우위 결론은 불변 |
| counter 분류 해상도 | 6/10 → 8/10 → 9/10 | ibv_wc_status → +vendor_err → +ethtool | 남은 1종: REM_ACCESS_ERR의 invalid rkey ≡ 주소 범위 초과 (모든 counter source에서 동일) |
| silent partial 대응 3전략 | C3 read-back total 4,003 µs / C1 commit-flag 4,164 µs / C2 CRC32C 5,130 µs (4MB PARTIAL, 에러당) | silent_strategy.csv ([07 문서](07_silent_partial_strategy.md)) | 정상경로 오버헤드: C3 0 / C1 +약 1 µs 상수 / C2 +89% @4MB. C2 judge 수치는 오염 의심(7.4절) |
| Storage(SSD) 경계 대표값 | target crash 에러 표면화 33.36 s ± 0.03 / RDMA counter 최초 발화 0.6 s (lead 54배) | Phase 1/1b, PHASE1_FINDINGS.md ([08 문서](08_storage_rdma.md)) | 33.36 s는 물리 감지가 아니라 재연결 정책(3회 × 10 s) 지배 |
