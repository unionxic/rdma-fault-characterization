# 이론·분류·관측

RDMA subsystem 연구의 이론 기초와 분류 체계 문서군. 실측 수치는 [experiments](../experiments/README.md)의 canonical 표가 기준이다.

| 문서 | 내용 |
|------|------|
| [01 연구 개요와 방향](01_overview.md) | 문제의식, 연구 흐름, framing |
| [02 RDMA 이론 기초](02_rdma_basics.md) | RC QP, CQE, 상태 전이, RoCE |
| [03 CQE와 에러 식별](03_cqe_error_identification.md) | ibv_wc_status, vendor_err 읽는 법 |
| [04 에러 분류 체계와 responder pipeline](04_error_taxonomy_responder_pipeline.md) | 3-category 분류, responder 검증 단계 복원 |
| [05 counter signature와 관측성](05_counter_observability.md) | sysfs/ethtool/register 관측성, fingerprint |
| [06 vendor_err 일반화](06_vendor_err_generalization.md) | firmware raw 여부, 세대·벤더 간 안정성 |
| [07 구현 레이어 제약과 NCCL](07_layer_constraints_nccl.md) | kernel-bypass가 결정하는 통합 지점 |
| [08 부록: 구현 함정과 코드 증거](08_appendix_code_evidence.md) | MR 권한, GID 재구성, 커널 소스 근거 |
