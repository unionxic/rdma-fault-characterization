# experiment1: RDMA 장애 감지 시간 기준선

상대가 갑자기 응답을 멈추면, 요청 쪽이 CQ를 쉬지 않고 polling해도 오류를 언제 받는지 쟀다.
CPU가 CQE로 장애를 아는 가장 빠른 경우의 기준선이다. 장애를 내는 응답 쪽 코드와 결과 문서는 224 쪽 같은 폴더에 있다.
수치는 옛 클러스터(225 요청 ConnectX-6, 224 응답 ConnectX-5)에서 쟀다.

## 무엇을 쟀나

- **장애 세 가지.** 응답 QP를 ERR로 바꾸기, 응답 프로세스 종료, 응답 쪽 link down이다.
- **장애마다 100회.** 장애 주입부터 첫 오류 CQE까지의 시간과 오류 코드(status와 vendor_err)를 기록했다.
- **조건.** 4 KiB RDMA WRITE를 계속 보내는 중에 장애를 냈다. CQ는 쉬지 않고 polling했다.
  IB 타임아웃 14(약 67 ms), retry_cnt 7, PMTU 1024, RoCE v2.

## 결론

- **장애 종류와 상관없이 약 3.7 s가 걸린다.** 세 장애의 중앙값이 3,701~3,749 ms다. 장애마다 변동계수는 0.3% 아래다.
- **오류 코드도 모두 같다.** 300회 모두 RETRY_EXC 12/0x81이었다.
  - 응답 QP를 ERR로 바꾼 경우에도 응답 쪽은 NAK를 보내지 않았다.
  - 그래서 요청 쪽은 재전송을 다 쓰고서야 오류를 안다. 오류 코드로는 세 장애를 가를 수 없다.
- **감지 시간은 장애가 아니라 NIC의 재전송이 정한다.** polling을 아무리 빨리 해도 이 시간은 줄지 않는다.
  - 3.7 s가 어디서 오는지는 retry 분해와 펌웨어 하한 실험에서 쪼갰다.
    NIC 펌웨어의 ACK 타임아웃 하한 때문이었다([docs/experiments/01](../../../../docs/experiments/01_detection_firmware_retry.md)).

## 결과

| 장애 | N | 중앙값 | 평균 ± 표준편차 | 최소~최대 | 오류 코드 |
|---|--:|--:|--:|--:|---|
| 응답 QP를 ERR로 | 100 | 3,749 ms | 3,748 ± 11.9 ms | 3,631~3,751 ms | 12 / 0x81 |
| 응답 프로세스 종료 | 100 | 3,701 ms | 3,701 ± 8.5 ms | 3,699~3,786 ms | 12 / 0x81 |
| 응답 쪽 link down | 100 | 3,702 ms | 3,701 ± 10.3 ms | 3,603~3,706 ms | 12 / 0x81 |

장애 주입 시각은 제어용 TCP 왕복 시간의 절반으로 추정했다. 그 오차는 감지 시간의 1% 미만이다.

## 한계와 주의

- **"프로세스 종료"는 실제 kill -9가 아니다.** 응답 프로세스가 명령을 받고 스스로 바로 끝나게 해서 흉내 냈다.
- **QP ERR 시나리오의 N 기록이 엇갈린다.** [docs/experiments/01](../../../../docs/experiments/01_detection_firmware_retry.md)은 원본 CSV에 1회분만 남았다고 적었다.
  그림용 표(`../../plots/data/exp1_distribution.csv`)에는 세 장애 모두 100회가 있고 위 값과 맞는다.
- **소프트웨어 link down의 효과는 실험마다 달랐다.** 여기서는 100회 모두 오류가 났다.
  나중 카운터 매핑 실험에서는 같은 방식이 RoCE 트래픽을 끊지 못했다(3회 모두 성공, `../../05_counter_mapping/`).
- **QP 설정 하나만 썼다.** 설정을 바꾼 결과는 [experiment4](../experiment4/README.md)와 [docs/experiments/01](../../../../docs/experiments/01_detection_firmware_retry.md)에 있다.
- **옛 클러스터 값이다.** 새 테스트베드의 같은 질문은 `../../../../harness/`에 있다. PMTU와 NIC 조합이 달라 직접 비교하지 않는다.

## 파일

| 파일 | 내용 |
|---|---|
| [NOTES.md](NOTES.md) | 예전 README(영문). 빌드, 실행, 출력 형식, 측정 방법 |
| [EXPERIMENT1_RESULTS.md](../../../224-server/01_cpu_baseline/experiment1/EXPERIMENT1_RESULTS.md) | 결과 문서(영문). 224 쪽 폴더에 있다 |
| `../../plots/data/exp1_distribution.csv` | 시험별 감지 시간 300행. 원본 CSV는 레포에 올라온 적이 없다 |
| [docs/experiments/01](../../../../docs/experiments/01_detection_firmware_retry.md) | 3.7 s 분해와 펌웨어 하한 |
