# propagation: 층별 오류 전파 분석

장애가 NIC에서 앱까지 올라가는 동안 어느 층에서 정보가 사라지는지 정리한다.
2026-10-06에 기존 결과를 모두 다시 검토해, 층마다 가를 수 있는 장애 묶음을 표로 만들었다.
다음 측정 캠페인의 예측은 실행 전에 고정했다. 이 폴더에는 새 측정이 없다.

## 무엇을 쟀나

- **새로 잰 것은 없다.** 검토 4건이 기존 결과 폴더를 모두 다시 봤다.
  - 대상은 CPU verbs 기준선, NCCL GIN, NVSHMEM IBGDA, NCCL net_ib과 투명 복구 probe다.
  - 핵심 숫자는 원시 데이터(지금은 Release `data-20261006`)에서 다시 셌다. 정정 목록의 작은 항목 외에는 모두 맞았다.
- **층 6개.** L0 NIC(QP 상태, doorbell record, 카운터), L1 CQE, L2 CQ를 읽는 코드, L3 API, L4 호스트(비동기 오류, 로그, 호스트에 오류를 알리는 공유 메모리 칸), L5 종료.
  - L1은 NIC가 쓴 root CQE와, 읽는 쪽이 실제로 읽은 CQE(root 또는 뒤따르는 flush)를 따로 본다.
- **장애 5가지.** F0 없음, F1 로컬 QP 오류, F2 원격 접근 오류, F3 상대 QP 오류(상대는 살아 있음), F4 상대 SIGKILL.
- **범위.** ConnectX-6(fw 20.43.4100), RoCE v2 위의 GPU 스택이다. CPU verbs와 net_ib은 CPU가 요청을 내는 기준선이다.
- **사전 등록.** 다음 캠페인의 예측 24개를 2026-10-06에 고정했다(태그 `prereg/propagation-v1`). 아직 실행하지 않았다.
  - 예측은 세 전제에서 나온다. DEVX로 만든 QP에는 비동기 오류 경로가 없다. 단방향 연산의 대상은 완료를 받지 않는다. doorbell record가 맞으면 CQE는 생긴다.

## 결론

- **stock 스택에서는 위층으로 갈수록 정보가 줄기만 한다.**
  - GDAKI는 root CQE에서 4묶음, 장치에서 2묶음이다. blocking에서는 F0~F3가 같아 보인다.
  - NVSHMEM GPU handler는 L1에서 4묶음, L3에서 1묶음이다.
- **덧붙인 채널은 두 종류다.**
  - 불필요한 손실만 막는 채널. GDAKI 장치 쪽 분류기와 NVSHMEM FT는 뒤따르는 flush 대신 root CQE를 읽는다. 많아야 L1의 분할까지 간다.
  - L1에 없던 정보를 더하는 채널. OOB 소켓의 FIN으로 본 상대 생존이다. F3와 F4를 가르는 것은 이것뿐이다.
- **한 층을 고치면 위층이 더 거칠어질 수 있다.**
  - NVSHMEM doorbell record를 고치면 CQE가 없던 L1이 4묶음이 된다.
  - 그런데 L3는 2묶음(hang과 반환)에서 1묶음(조용한 성공)이 된다. stock 장치 코드가 CQE를 버리기 때문이다.
- **복구는 일부러 묶음을 합친다.**
  - GIN 투명 복구 1, 2단계, NVSHMEM 투명 복구, NCCL net_ib 복구 2단계(Stage 2)는 복구한 장애를 L3에서 F0와 같게 만든다. 장애 종류는 로그에만 남는다.
- **단방향 GIN에서 수동 쪽(대상)은 오류를 받을 길이 없었다.** 단방향 연산은 대상에 완료를 주지 않는다.
  - stock GIN의 대상 rank는 F1~F3에서 비동기 오류를 한 번도 받지 못했다(backend마다 18/18). 자기 QP가 ERR인 F3도 그렇다.
  - blocking F1~F3에서 대상의 abort는 돌아오지 않았다(stock 9/9, 장치 쪽 분류기 N=30 90/90).
- **있는데 아무도 안 쓰는 정보가 있다.**
  - net_ib 주소 재구성(flap) 29/29회에서 GID 변경 비동기 이벤트가 RETRY_EXC보다 약 3.5 s 먼저 왔다.
  - 검토한 어느 스택도 이것을 읽지 않는다.

## 결과

시작 쪽에서 가를 수 있는 장애 묶음 수다. F0도 한 묶음으로 센다. 괄호는 한 묶음으로 합쳐지는 장애다.

| 변형 | L1 root CQE | L1 읽힌 CQE | L2 | L3 API | L4 호스트 | L5 종료 |
|---|---|---|---|---|---|---|
| CPU verbs | 4 (F3,F4) | 같음 | 생존 확인 더해 5 | (harness가 곧 앱) | 기록 안 함 | 재지 않음 |
| GIN proxy, stock | 4 (F2,F4) | 같음 | 4 | 2 (시간 초과, blocking은 hang) | 비동기 오류 2, 로그 4 | blocking F1~F3 hang |
| GDAKI, stock | 4 (F3,F4) | 2 (뒤따르는 flush) | 2 | blocking에서 F0~F3 같음 | 10 s 주기 검사에서 2 | 대상 rank hang |
| GDAKI + 장치 쪽 분류기 | 4 | root를 찾음 | 4 | 2 | API 2, 로그와 알림 칸 4 | 대상 rank hang |
| GDAKI + 분류기 + 복구 | 4 | root를 찾음 | 4 | 4, FIN 더해 5 | 5 | 양쪽 반환 |
| GIN 투명 복구 1, 2단계 | 4 | root를 찾음 | 생존 확인 더해 5 | 2 (복구한 F1,F3 = F0) | 로그 5 | 대상 F2 hang |
| NVSHMEM CPU proxy, stock | 없음 (CQE가 안 생김) | 없음 | 2 (spin) | 2 (hang) | 1 | F1~F4 hang |
| NVSHMEM GPU handler, 또는 CPU proxy + 버그 수정 | 4 (F3,F4) | 2 | 2 | 1 (모두 조용한 성공) | 1 | F1~F4 hang |
| NVSHMEM FT v1 | 4 | 기다리는 스레드가 돌 때만 root | 4 | 상태 조회로 4 | 알림 칸 4, FIN 더해 5 | FT abort를 불러야 반환 |
| NVSHMEM FT v2.2 (ring CQ) | 4 | root 유지 | 4 (guard를 두면 범위 초과 쓰기도) | 4, 실패한 fetch에 오염 표시 | 4/5 | FT abort 없이는 hang (flap 6/6) |
| net_ib, stock | 3 (F3,F4,flap) (F0,쉬는 연결) | 같음 | 같음 | 3 (쉬는 연결은 조용한 hang) | WARN 로그, GID 변경 이벤트는 안 씀 | abort hang 83/83 |
| net_ib + Stage 2 | stock과 같음 | stock과 같음 | 5 (F0 제외, 아래 참고) | 2 (복구 = F0) | WARN 로그뿐 | abort hang |

값은 `REVIEW_20261006.md`의 분할 표를 옮긴 것이다.
net_ib 두 행은 장애 집합이 달라 다른 행과 바로 비교할 수 없다. F2는 재지 않았고, flap과 쉬는 연결의 장애를 따로 셌다.
- net_ib stock L1에서 F0은 쉬는 연결의 F3, F4와 같은 "CQE 없음" 묶음이다.
- Stage 2 L2의 5묶음은 F1, 죽음 증거 없는 RETRY_EXC(F3와 flap), FIN을 본 F4, 관리망 끊김, 복구 요청에 답이 없는 상대다. flap과 F3는 나중에 GID 이동 로그로만 갈린다.
- Stage 2 L3의 "복구 못 함"에는 쉬는 연결의 F3도 들어간다. 최대 120 s 기다린 뒤 오류가 난다.
- 83/83은 NCCL 복구 1단계(Stage 1), Stage 2, perf에서 오류가 난 로그 83개를 합친 수다.

예측 24개는 아래 여섯 묶음에 모두 들어 있다. `predictions.csv`에는 EV1a처럼 세부 항목으로 나뉘어 있다.

| 예측 | 대상 | 내용 |
|---|---|---|
| EV1, EV2 | CPU verbs 응답 쪽 | QP 비동기 이벤트는 F2(ACCESS_ERR)와 원격 잘못된 요청(REQ_ERR)에서만 난다. 요청 쪽은 어떤 장애에도 없다. 응답 쪽 QP는 이 둘에서 ERR, RNR과 F1에서 RTS다 |
| EV3 | GIN proxy 대상 rank | F2에서 로그에는 async fatal 경고가 뜨지만, API는 자기 wait가 끝날 때까지 성공이다. F1, F3, F4에서는 경고가 없다 |
| EV4, EV5 | DEVX QP 스택 전부 (비교군 CPU verbs, GIN proxy) | DEVX 스택은 어떤 장애에도 QP 비동기 오류가 없고 port 오류 카운터도 +0이다. verbs QP를 쓰는 CPU verbs와 GIN proxy만 카운터가 오른다 |
| NET1 | net_ib, F2 | 양방향 프로토콜이라 대상도 경고와 API 오류를 받는다. Stage 2는 복구하지 않고 거절한다 |
| D1, D2 | GDAKI, GPU doorbell | F2~F4가 CPU doorbell 때와 같다. F4도 blocking에서 조용한 성공이다 |
| 정리 예측 T1~T4 | 종료 | F0은 양쪽이 5 s 안에 반환한다. NVSHMEM 3.8.0 F4는 finalize가 30 s 안에 안 돌아온다. GDAKI blocking F1~F3은 대상만 hang이다. FT v2.2는 복구한 F1, F3에서 양쪽이 반환하고, 거절한 F2, F4는 FT abort 뒤에만 반환한다 |

정리 예측 T1~T4는 이 캠페인 안의 번호다. NVSHMEM 투명 복구(`../nvshmem_ft/TRANSPARENT_T1.md`)나 net_ib Stage 2의 시험 T1~T12와는 관계없다.
새 셀과 옛 로그로도 채점하는 셀은 10회, 반복 셀과 F0 대조는 5회다.
범주 예측은 9/10(또는 5/5) 이상 맞고 예측 밖 결과가 없어야 맞다. 시간 예측은 모든 시험이 범위 안, 분할 예측은 묶음이 같아야 맞다.

틀이 깨지는 경우는 넷이다. DEVX 스택의 비동기 오류, GIN 대상 rank의 API 오류, CQE를 잃는 GPU doorbell GDAKI, 채널을 더하지 않았는데 아래 층보다 고운 분할.

## 한계와 주의

- **새 측정이 아니다.** 분할 표는 기존 결과의 재검토다. 셀마다 날짜, doorbell 방식, 표본 수가 다르다. stock 셀은 대부분 n=3이다.
- **예측은 아직 채점 전이다.** 예측이나 판정 규칙을 바꾸면 이유를 `DEVIATIONS.md`에 덧붙이고, 원래 예측으로 채점한다.
- **비어 있는 칸이 많다.** 캠페인이 채울 몫이다.
  - CPU 기준선에는 F0 대조가 없다. 비동기 이벤트는 어느 스택에서도 따로 기록하지 않았다. GID 변경 이벤트도 net_ib 로그에 찍힌 줄을 검토 때 센 것이다.
  - 대상 쪽(QP 상태, 비동기 오류, API, 종료)과 양쪽 종료 시간이 거의 없다.
  - 재지 않은 것: NVSHMEM GPU handler의 F4 quiet, 3.8.0의 CQE 슬롯 내용과 종료, DEVX QP 카운터, GIN stock F2~F4의 GPU doorbell, GIN 카운터, non-blocking communicator, net_ib F2.
- **검토에서 나온 정정을 표에 반영했다.** 전체 목록은 `REVIEW_20261006.md`에 있다.
  - CPU verbs의 "상대 종료"는 정상 종료였다. 실제 SIGKILL은 270회 중 111회가 F2와 같은 코드(0x88)다.
  - "GDAKI 종료는 깨끗하다"는 시작 rank만 맞다. 대상 rank는 hang이다.
  - NVSHMEM GPU handler의 F4와 종료, 버그 수정 행의 F4와 blocking은 실제로 쟀다(`../RESULTS.md`에서는 "-").
- **GID 변경 이벤트의 이름은 추정이다.** 로그에는 "unknown event type (18)"로 찍혔다. 18을 GID 변경으로 읽은 것은 libibverbs의 값 기준이다.
- **커밋 전 결과가 섞여 있다.**
  - GIN 투명 복구 2단계와 NVSHMEM 투명 복구는 아직 검토 중인 결과다. 표의 GIN 투명 복구 행과 결론의 복구 문장이 여기에 기댄다.
  - GIN 투명 복구 2단계 문서(`../gin_recovery/TRANSPARENT_S2.md`)에는 빈 자리 행과 중간 빌드 표가 있다. NVSHMEM 투명 복구 문서(`../nvshmem_ft/TRANSPARENT_T1.md`)는 대기 한도를 78 s와 93 s로 엇갈리게 적고, 마지막 빌드 실행은 보고하지 않았다.
  - GIN 투명 복구 2단계에는 net_ib Stage 2가 버린 규칙(모든 TCP 오류를 상대 죽음으로 봄)이 아직 남아 있다.

## 파일

| 파일 | 내용 |
|---|---|
| [REVIEW_20261006.md](REVIEW_20261006.md) | 층별 분할 표, 관찰 6가지, 정정 목록, 빈칸 |
| [PREDICTIONS.md](PREDICTIONS.md) | 사전 등록한 예측, 세 전제, 판정 규칙 |
| `predictions.csv` | 같은 예측 24개를 세부 항목으로 |
| `PREREG.txt` | 고정 시각과 세 파일의 sha256 |
| `review_20261006/` | 검토 보고서 4건(CPU 기준선, GIN, NVSHMEM, net_ib과 설계 문서) |
| `../RESULTS.md`, `../N30_20260925.md` | 분할 표가 기대는 GPU 스택 결과 |
