# experiment1: 감지 시간 기준선 (응답 쪽)

experiment1에서 장애를 당하는 응답 쪽(224, ConnectX-5) 폴더다. 요청 쪽(225)의 쓰기를 받다가 명령이 오면 장애를 낸다.
요청 쪽이 오류를 언제 받는지는 225에서 쟀고, 결과 문서는 이 폴더에 있다.
수치는 옛 클러스터(225 요청 ConnectX-6, 224 응답 ConnectX-5)에서 쟀다.

## 무엇을 쟀나

- **장애 세 가지.** 응답 QP를 ERR로 바꾸기, 응답 프로세스 종료, 응답 쪽 link down이다.
- **장애마다 100회.** 요청 쪽이 장애 주입부터 첫 오류 CQE까지의 시간과 오류 코드를 기록했다.
- **조건.** 요청 쪽이 4 KiB RDMA WRITE를 계속 보낸다. IB 타임아웃 14(약 67 ms), retry_cnt 7, PMTU 1024, RoCE v2.
- **다른 실험에서 다시 쓴 서버.** 실험 2와 4, retry 분해, 펌웨어 하한 실험의 쓰기 대상이기도 하다.

## 결론

- **세 장애 모두 약 3.7 s 뒤에 같은 오류가 온다.** 300회 모두 RETRY_EXC 12/0x81이었다.
- **응답 쪽은 NAK를 보내지 않는다.** QP를 ERR로 바꾼 경우에도 들어오는 패킷을 버릴 뿐이다.
  그래서 요청 쪽은 재전송을 다 쓰고서야 오류를 안다.
- **감지 시간은 장애가 아니라 요청 쪽 NIC의 재전송이 정한다.** 해석은 [225 쪽 README](../../../225-client/01_cpu_baseline/experiment1/README.md)에 있다.

## 결과

| 장애 | N | 중앙값 | 평균 ± 표준편차 | 최소–최대 | 오류 코드 |
|---|--:|--:|--:|--:|---|
| 응답 QP를 ERR로 | 100 | 3,749 ms | 3,748 ± 11.9 ms | 3,631–3,751 ms | 12 / 0x81 |
| 응답 프로세스 종료 | 100 | 3,701 ms | 3,701 ± 8.5 ms | 3,699–3,786 ms | 12 / 0x81 |
| 응답 쪽 link down | 100 | 3,702 ms | 3,701 ± 10.3 ms | 3,603–3,706 ms | 12 / 0x81 |

값은 [EXPERIMENT1_RESULTS.md](EXPERIMENT1_RESULTS.md)의 요약표다.

## 한계와 주의

- **"프로세스 종료"는 실제 kill -9가 아니다.** 응답 프로세스가 명령을 받고 스스로 바로 끝나게 해서 흉내 냈다.
- **결과 문서의 하드웨어 표가 틀려 있다.** 225를 ConnectX-5로 적었지만 fw 20.40.1000은 ConnectX-6이다.
  [초기 연구 해설](../../../../docs/experiments/README.md)은 225를 ConnectX-6으로 적는다.
- **결과 문서의 GPU 쪽 목표값은 측정이 아니다.** "1 ms 미만", "10 ms 안에 복구" 같은 값은 당시 계획이다.
- **QP ERR 시나리오의 N 기록이 엇갈린다.** [docs/experiments/01](../../../../docs/experiments/01_detection_firmware_retry.md)은 원본 CSV에 1회분만 남았다고 적었다.
  그림용 표(`../../../225-client/plots/data/exp1_distribution.csv`)에는 세 장애 모두 100회가 있고 위 값과 맞는다.
- **옛 클러스터 값이다.** 새 테스트베드의 같은 질문은 `../../../../harness/`에 있다. PMTU와 NIC 조합이 달라 직접 비교하지 않는다.

## 파일

| 파일 | 내용 |
|---|---|
| [EXPERIMENT1_RESULTS.md](EXPERIMENT1_RESULTS.md) | 결과 문서(영문). 설정, 요약 통계, 해석 |
| [NOTES.md](NOTES.md) | 예전 README(영문). 빌드, 실행, 출력 형식 |
| [225 쪽 README](../../../225-client/01_cpu_baseline/experiment1/README.md) | 요청 쪽 요약 |
| `../../../225-client/plots/data/exp1_distribution.csv` | 시험별 감지 시간 300행. 원본 CSV는 레포에 올라온 적이 없다 |
| [docs/experiments/01](../../../../docs/experiments/01_detection_firmware_retry.md) | 3.7 s가 어디서 오는지 |
