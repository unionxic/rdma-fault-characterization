# docs/theory: 초기 연구의 이론과 분류

초기 연구에서 RDMA 오류를 읽고 나누는 데 쓴 이론, 분류 체계, 관측성 정리다.
실측 수치는 [실험 해설의 기준값 표](../experiments/README.md)를 따른다. 수치는 모두 옛 클러스터(225, 224)에서 쟀다.

## 무엇이 있나

- **연구 개요(01).** 같은 status가 다른 원인에서 나오는 문제, 세 신호(status, vendor_err, 카운터)를 겹쳐 분류하는 방향.
- **RDMA 기초(02).** RC QP, CQE, QP 상태 전이, RoCE, PSN과 재전송.
- **오류 읽기(03).** status는 드라이버가 정하고, vendor_err는 펌웨어 값을 그대로 옮긴다.
- **분류 체계(04).** 장애 10가지를 로컬, 오류 NAK, 타임아웃 세 범주로 나눴다. 응답 쪽 검증 단계를 거꾸로 짚었다.
- **관측성(05).** RDMA 오류는 sysfs RDMA 카운터에서만 보였다. ethtool 오류 카운터와 NIC 레지스터는 반응이 없었다.
- **vendor_err 일반화(06).** ConnectX-5와 ConnectX-6에서 같았다. 다른 벤더와는 인코딩이 독립이다.
- **구현 위치(07).** CQE는 QP를 가진 사용자 공간 런타임만 본다. 그래서 분류와 복구는 NCCL 같은 통신 런타임 안에 넣어야 한다.
- **부록(08).** MR 권한, GID 재구성, 커널 우회 때문에 무효인 장애 주입 같은 구현 함정과 커널 소스 근거.
- **새 테스트베드에서 바뀐 것.** 죽은 상대의 오류 코드는 0x81만이 아니었다(`../../harness/teardown_order/`).
  오류 코드만으로 갈리는 묶음 수도 다시 쟀다(`../../harness/`).

## 파일

| 문서 | 내용 |
|---|---|
| [01 연구 개요와 방향](01_overview.md) | 문제의식, 연구 흐름, 방향 설정 |
| [02 RDMA 이론 기초](02_rdma_basics.md) | RC QP, CQE, 상태 전이, RoCE |
| [03 CQE와 오류 식별](03_cqe_error_identification.md) | status와 vendor_err 읽는 법 |
| [04 오류 분류 체계와 응답 쪽 처리 단계](04_error_taxonomy_responder_pipeline.md) | 세 범주 분류, 응답 쪽 검증 단계 복원 |
| [05 카운터 변화와 관측성](05_counter_observability.md) | sysfs, ethtool, 레지스터 관측성, 오류 신호 조합의 구분 해상도 |
| [06 vendor_err 일반화](06_vendor_err_generalization.md) | 펌웨어 값 여부, 세대와 벤더 간 안정성 |
| [07 구현 계층 제약과 NCCL](07_layer_constraints_nccl.md) | 커널 우회가 정하는 통합 지점 |
| [08 부록: 구현 함정과 코드 증거](08_appendix_code_evidence.md) | MR 권한, GID 재구성, 커널 소스 근거 |
| [../experiments/README.md](../experiments/README.md) | 실험 해설과 기준값 |
