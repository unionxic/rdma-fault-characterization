# 224-server: 초기 연구의 응답 쪽 노드

초기 연구(2026년 4–7월)에서 응답(responder) 역할을 한 노드 224의 코드다. NIC는 ConnectX-5, fw 16.35.8002다.
장애를 당하는 쪽이고, 실험은 모두 요청 쪽 225에서 조율했다. 결과와 해설은 대부분 225 쪽에 있다.
수치는 모두 이 옛 클러스터에서 쟀다. 지금 테스트베드(rain, sunny)의 수치와 직접 비교하지 않는다.

## 무엇이 있나

- **감지와 복구 기준선의 응답 쪽.**
  - 감지 시간 기준선 실험은 장애 세 가지를 낸다. 응답 QP를 ERR로 바꾸기, 응답 프로세스 종료, link down이다.
  - 이 서버는 polling 간격, NIC 재전송 설정, retry 분해, 펌웨어 하한 실험에서도 쓰기 대상으로 다시 썼다.
  - QP 복구 단계 실험은 응답 쪽 단계를 따로 기록한다.
- **오류 코드와 카운터의 응답 쪽.**
  - 장애별 응답 서버와 카운터 수집을 맡는다. README는 없다. 설명은 225 쪽 같은 폴더에 있다.
  - NIC 세대 맞바꾸기 실험에서는 이 노드가 요청 쪽이 됐다. ConnectX-5가 낸 오류 코드가 남아 있다.
- **복구 실험의 응답 쪽.** 오류 종류별로 장애를 만드는 서버 5종이다. 결과는 225 쪽에 있다.
- **스토리지 타깃.** 파일로 만든 가짜 디스크를 NVMe-oF로 내보내고 고장을 넣는다. 부팅 디스크는 건드리지 않는다.
- **지운 것.** 225와 똑같던 요청 쪽 사본, 분류 라이브러리, 미들웨어 데모, 한 번 쓴 통합 검증이다.
  2026-10-06에 지웠고 태그 `archive/results-tables-20261006`에 남아 있다. 초기 연구 해설의 수치는 이 코드에 기대지 않는다.
- **처음부터 저장소에 없는 것.** 시나리오별 설정 서버(04_error_codes)와 rdma-core 소스 사본이다.

## 파일

| 경로 | 내용 |
|---|---|
| [NOTES.md](NOTES.md) | 예전 README. 폴더별 역할, 2026-07-10 폴더 이름 변경표 |
| [01_cpu_baseline/experiment1/](01_cpu_baseline/experiment1/README.md) | 감지 시간 기준선의 응답 쪽. 결과 문서가 여기에 있다 |
| [01_cpu_baseline/experiment3/](01_cpu_baseline/experiment3/README.md) | QP 복구 단계의 응답 쪽 기록 |
| `05_counter_mapping/` | 장애별 응답 서버와 카운터 수집. 설명은 [225 쪽 README](../225-client/05_counter_mapping/README.md) |
| `05_counter_mapping/results/raw/` | NIC 맞바꾸기 결과(ConnectX-5가 요청). 시나리오별 표는 태그 `archive/results-tables-20261006`에만 있다 |
| `06_recovery/` | 복구 실험의 응답 쪽 서버. 결과는 [225 쪽 README](../225-client/06_recovery/README.md) |
| [10_storage_rdma/](10_storage_rdma/README.md) | 스토리지 실험의 타깃 쪽 |
| [../225-client/README.md](../225-client/README.md) | 요청 쪽과 결과 |
| [../../docs/experiments/README.md](../../docs/experiments/README.md) | 초기 연구 해설과 기준값 |
