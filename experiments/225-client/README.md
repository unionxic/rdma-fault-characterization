# 225-client: 초기 연구의 요청 쪽 노드

초기 연구(2026년 4~7월)에서 요청(requester) 역할을 한 노드 225의 실험 폴더다. NIC는 ConnectX-6, fw 20.40.1000이다.
응답 쪽은 224(ConnectX-5, fw 16.35.8002)이고, 실험은 모두 여기서 조율했다. 짝이 되는 코드는 [224-server](../224-server/README.md)에 있다.
수치는 모두 이 옛 클러스터에서 쟀다. 지금 테스트베드(rain, sunny)의 수치(`../../harness/`)와 직접 비교하지 않는다.

## 무엇이 있나

폴더 번호는 연구 순서다.

- **감지와 복구 기준선 (`01_cpu_baseline/`).** 실험 네 개다.
  - 상대가 응답을 멈추면 오류는 약 3.7 s 뒤에 온다(experiment1).
  - polling 간격을 늘리면 그만큼 늦어진다(experiment2). QP 복구 동작은 약 2.7 ms다(experiment3).
  - retry_cnt 7에서는 IB 타임아웃을 내려도 3.55 s 아래로 못 내려간다(experiment4).
- **3.7 s 분해 (`02_retry_decomposition/`, `03_modifyqp/`).** README가 없다. 해설은 [docs/experiments/01](../../docs/experiments/01_detection_firmware_retry.md)에 있다.
  - 3.7 s는 NIC 펌웨어의 ACK 타임아웃 하한 때문이었다. 하한을 끄면 retry_cnt 7에서 12.26 ms다.
- **오류 코드와 카운터 (`05_counter_mapping/`).** 장애 10가지의 오류 코드와 카운터, partial write, 복구 전략 비교, NIC 세대 맞바꾸기.
  - 오류 코드로 10가지 중 8가지가 갈린다. 오류는 요청 쪽에만 보인다.
- **복구 비용 (`06_recovery/`).** 오류 종류별 복구 시간, 다중 QP 격리, 카운터 기반 조기 감지.
  - QP만 재설정하면 1.3~2.8 ms, 드라이버 재적재는 7.9 s다. 카운터를 보면 재전송 소진을 18.4 ms에 안다.
- **스토리지 경계 (`10_storage_rdma/`).** NVMe-oF over RDMA에서 SSD 장애가 어느 계층에 보이는지.
  - 명시적 장애는 NVMe에만, 조용한 장애는 RDMA 카운터에만 보였다.
- **그림용 표 (`plots/data/`).** 실험 1~4의 원시 CSV에서 뽑은 요약 표다. 그림 자체는 레포에 없다.
- **미들웨어 데모 점검 기록 (`08_middleware/results/qa_20260923/`).** 2026-09-23 새 클러스터에서 한 실기 점검이다. 코드는 지웠다.
- **지운 것.** 분류 라이브러리(07), 미들웨어 데모(08), 한 번 쓴 통합 검증(09), 쓰이지 않던 계측 코드와 그림 스크립트다.
  2026-10-06에 지웠고 태그 `archive/results-tables-20261006`에 남아 있다. 해설 문서의 수치는 이 코드에 기대지 않는다.
- **처음부터 레포에 없는 것.** 오류 코드 채집 실험(04_error_codes)과 그 보고서, 2026-05-06 시점 종합 요약이다.

## 파일

| 경로 | 내용 |
|---|---|
| [NOTES.md](NOTES.md) | 예전 README. 실행 방법, 폴더 간 의존, 2026-07-10 디렉토리 이름 변경표 |
| [01_cpu_baseline/experiment1/](01_cpu_baseline/experiment1/README.md) | 감지 시간 기준선 |
| [01_cpu_baseline/experiment2/](01_cpu_baseline/experiment2/README.md) | polling 간격과 감지 지연 |
| [01_cpu_baseline/experiment3/](01_cpu_baseline/experiment3/README.md) | QP 복구 단계별 비용 |
| [01_cpu_baseline/experiment4/](01_cpu_baseline/experiment4/README.md) | NIC 재전송 설정의 경계 |
| `02_retry_decomposition/`, `03_modifyqp/` | 결과 표는 태그 `archive/results-tables-20261006`에만 있다. retry 분해의 원시 기록은 Release `data-20261006` |
| [05_counter_mapping/](05_counter_mapping/README.md) | 장애별 오류 코드와 카운터 |
| [06_recovery/](06_recovery/README.md) | 오류 종류별 복구 비용 |
| [10_storage_rdma/](10_storage_rdma/README.md) | SSD 장애와 RDMA 경계 |
| `plots/data/` | 실험 1~4 요약 표 |
| [08_middleware/results/qa_20260923/](08_middleware/results/qa_20260923/README.md) | 미들웨어 데모 실기 점검(새 클러스터) |
| [../../docs/experiments/README.md](../../docs/experiments/README.md) | 초기 연구 해설과 기준값 |
