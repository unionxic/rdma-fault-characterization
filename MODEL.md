# 오류 전파 규칙

RDMA 장애 정보가 NIC에서 앱까지 올라가며 어디서 남고 어디서 사라지는지를 설명하는 규칙 다섯 가지다.
측정 결과를 설명할 뿐 아니라, 새 스택에서 무엇이 보일지 측정 전에 맞히는 데 쓴다. 수식으로 증명한
것이 아니라, NIC 문서에 적힌 계약, 우리 측정, 기존 이론에서 세운 규칙이다. 범위는 mlx5 기반
스택(ConnectX-6에서 측정)이다.

각 규칙에는 세 가지를 붙였다.
- **근거:** 문서, 측정, 기존 이론 중 무엇에서 왔나.
- **맞힌 것:** 규칙에서 나온 예측을 측정 전에 적고 확인한 것.
- **한계:** 아직 확인하지 않은 것.

## 용어

- **계층 여섯 개:** NIC(QP 상태, 포트 카운터), CQE(NIC가 쓴 완료 기록), CQ를 읽는 코드(프록시 스레드나
  GPU 장치 코드), API(앱이 받는 값), 호스트(비동기 오류와 로그), 정리(abort나 finalize).
- **구분된다:** 그 계층에서 두 장애가 서로 다른 값으로 보인다. 계층마다 장애가 몇 묶음으로 갈리는지를
  "원인 구분 수"라고 부른다.
- **통로:** 바로 아래 계층을 거치지 않고 위 계층에 정보를 주는 경로. 예: 상대 생존을 확인하는 TCP 연결,
  프록시 스레드가 직접 쓰는 로그, 호스트의 주기적 오류 검사.

## 규칙 1. 완료 계약: 장애가 CQE 계층에 들어오는 조건

**규칙.** 장애가 앱에 보이려면 먼저 NIC가 오류 완료를 만들어야 한다. 오류 상태의 NIC는 doorbell
record에 적힌 값까지만 완료를 만든다. 그래서 record 값이 소프트웨어가 게시한 작업 수를 따라가지 않으면,
뒤처진 만큼 완료가 사라진다. 하나도 남지 않으면 장애는 어느 계층에도 보이지 않는다.

**근거.**
- 문서: NIC 프로그래밍 문서(PRM Rev 0.40, 7.4.2–7.4.3절)는 record의 송신 값을 "게시한 작업 수"로
  정하고, 작업의 소유권이 record를 갱신할 때 NIC로 넘어간다고 적는다.
- 측정: record 값을 바꿔 가며 225회 쟀다.
  - 첫 미완료 작업부터 record 값 바로 앞까지 정확히 완료가 나왔다(195/195).
  - record 값이 첫 미완료 위치 이하면, 이미 실행된 작업의 원인 CQE조차 없었다(65/65).
  - 오류 상태에서 나중에 record 값을 올리면 빠진 완료가 14–73 µs 안에 나왔다(30/30).

**맞힌 것.**
- NVSHMEM 3.5.x–3.8.0의 CPU 프록시는 송신 값을 record의 다른 칸에 쓴다(소스 확인). 규칙대로라면 어떤
  장애도 보이지 않아야 한다. 오류 CQE는 GPU 없는 재현에서 0/35, NVSHMEM 안에서 0/12였고, 수정하지 않은
  공식 3.8.0에서도 3/3 재현됐다. 그 칸만 고치면 21/21, 16/16으로 돌아왔다.
- 공식 3.8.0의 CQ를 직접 읽는 측정을 사전 등록했다. 예측대로 CPU 프록시는 상대 kill 뒤 오류 CQE가 0/5였고,
  GPU 처리 경로와 그 칸만 고친 수정본은 5/5였다. 장애가 없으면 어느 쪽도 오류 CQE가 없었다(10/10).
- GIN GDAKI는 GPU가 doorbell을 울리는 경로에서도 record를 먼저 쓴다(소스 확인). 규칙대로라면 완료가
  생겨야 한다. 사전 등록한 예측대로 원격 접근 오류와 상대 QP 오류에서 20/20 생겼다.
- 스택 14개의 소스를 읽어, record를 누가 언제 쓰는지만으로 "보인다, 사라진다, 조건부"를 미리 적었다. 다른
  에이전트가 근거 줄을 원본 커밋에서 다시 확인했다(14/14). 그중 이 테스트베드에서 잴 수 있는 칸을 사전 등록하고
  쟀다(55회).
  - NVSHMEM 3.4.5의 CPU 프록시는 같은 프록시지만 송신 칸에 쓴다. 상대 kill 뒤 대기가 재전송이 끝나자 10/10
    돌아왔다. 같은 경로가 3.8.0에서는 오류 CQE 0/5였다. 걸린 시간(57.0–58.5 s)은 예측에 적은 3–5 s가
    아니었다. 3.4.5가 IB 타임아웃을 20으로 고정한 것을 예측할 때 놓쳤기 때문이다.
  - NCCL GIN GDAKI의 BlueFlame 처리 방식(설정값 6)은 doorbell도 record도 쓰지 않는다. 장애가 없어도 첫 반복이
    10/10 시간 초과였고, 받는 쪽에 데이터가 없었다.
  - 같은 스택의 CPU 프록시 처리 방식은 진행 스레드가 record를 올린다. 로컬 QP 오류, 원격 접근 오류, 상대 QP
    오류에서 호스트 오류가 15/15 나왔다.

**한계.** NIC 한 종류(ConnectX-6, 펌웨어 20.43.4100)와 RC QP에서만 쟀다. record 값과 첫 미완료
위치의 차이는 -8부터 +18까지만 시험했다. "오류 상태의 NIC가 record를 다시 읽는다"는 동작 방식은
세 번째 측정에서 추론한 것이다. record를 읽지 않게 설정한 QP(DOCA의 record 없는 모드)는 규칙 1의 범위
밖이다. UCX, rocSHMEM, DeepEP는 소스 예측만 있고 재지 않았다.

## 규칙 2. 위로 갈수록 줄어든다

**규칙.** 위 계층의 값이 바로 아래 계층의 값만으로 정해진다면, 위 계층은 아래보다 원인을 잘게 가를 수
없다. 그러니 위에서 더 잘게 갈렸다면 아래를 거치지 않는 통로가 있다는 뜻이다. 통로는 두 종류다.
- **손실을 막는 통로:** 아래 계층에 있던 정보를 버리지 않게 한다. 예: CQ에서 원인 CQE를 다시 찾는
  GDAKI 장치 쪽 분류기, NVSHMEM 장애 대응판의 링 CQ. 이 통로로는 CQE 계층보다 잘게 가를 수 없다.
- **정보를 더하는 통로:** 아래 계층에 없던 정보를 넣는다. 예: TCP 연결로 본 상대 생존. 재시도 초과와
  상대 kill을 가른 것은 이 통로뿐이었다.

**근거.** 규칙의 앞 절반은 정의에서 바로 나온다. 경험으로 확인할 부분은 "실제 스택에서 통로가 어디에
있나"와 "통로가 없는 곳에서 정보가 실제로 줄어드나"다. 이것을 사전 등록한 계층별 측정으로 확인했다
(325회와 재실행 20회).

**맞힌 것.**
- 원본 스택에서 정보는 줄기만 했다.
  - GIN 프록시: CQE에서 4묶음이던 장애가 API에서는 "오류 있음/없음" 2묶음이 됐다.
  - GIN GDAKI의 blocking 대기: 로컬 QP 오류, 원격 접근 오류, 상대 QP 오류를 API가 성공으로
    돌려줬다(25/25).
  - NVSHMEM 3.8.0의 GPU 처리 경로와 수정본: 상대 kill도 API가 성공으로 돌려줬다(10/10).
- 측정 전에 예측한 계층별 원인 구분은 비교한 20줄 중 19줄이 맞았다.
- 위가 바로 아래보다 잘게 갈린 11곳 모두에서 통로를 찾았다. 상대 생존 확인, 장치 쪽 분류기, 프록시
  스레드가 쓰는 로그, 호스트의 주기 검사, NIC의 비동기 QP 이벤트, 앞 단계가 멈춘 결과, 그리고 상대의
  참여를 기다리는 정리 장벽이다.
- 마지막으로 확인한 2곳은 NVSHMEM 3.8.0 GPU 처리 경로와 수정본의 정리 단계다. 정리는 장치 장벽에서 상대가
  신호를 써 주기를 기다리다 멈췄다(10/10). TCP 장벽이나 QP 정리까지는 가지 않았다. 정리가 상대 kill을 가르는
  것은 오류를 알아서가 아니라, 상대가 참여해야 끝나는 대기이기 때문이다. 이 결과는 측정 전에 예측해 둔
  것이다([teardown_channel](harness/gpu-initiated/nvshmem_rootcause/teardown_channel/EXPERIMENT.md)).
- 아래를 고치면 위가 더 거칠어질 수 있다. NVSHMEM record 칸을 고치면 CQE 계층은 "완료 없음"에서
  4묶음이 된다. 그러나 API는 "멈춤 대 반환" 2묶음에서 "모두 성공" 1묶음이 된다. 대기 함수가 오류 값을
  돌려줄 수 없기 때문이다.

**한계.** 상대의 참여를 기다리는 대기도 통로로 셌다. 이 대기는 원인을 알려 주지 않고, 상대가 오지 않으면
끝나지 않을 뿐이다(규칙 4와 같은 모양). 이것을 통로로 보지 않는다면 정리 단계 2곳이 규칙의 예외가 된다.

## 규칙 3. 오류 코드만으로는 원인을 하나로 정할 수 없다

**규칙.** 재시도 초과는 "정해진 시간 안에 응답이 없다"로 판정한다. 그래서 상대가 죽었는지, 살아 있지만
QP가 오류인지, 느린지를 가를 수 없다. 반대로 같은 원인도 상대 쪽 자원이 어떤 순서로 사라지느냐에 따라
다른 코드로 보인다. 원인을 정하려면 규칙 2의 정보를 더하는 통로가 필요하다. 그 전까지는 "미확정"으로
다뤄야 한다.

**근거.**
- 기존 이론: 비동기 시스템에서 타임아웃만으로는 죽은 상대와 느린 상대를 구분할 수 없다(Fischer, Lynch,
  Paterson 1985; Chandra, Toueg 1996).
- 측정: 상대 QP 오류와 상대 kill은 CPU verbs, GDAKI, NVSHMEM에서 같은 12/0x81로 보였다.
- 측정: 죽은 상대의 코드는 커널이 지우는 순서로 갈렸다.
  - QP가 먼저 사라지면 마지막 ACK 뒤 3.51–3.76 s에 12/0x81이 왔다(159회).
  - 메모리 등록이 먼저 사라지면 0.38–3.51 ms에 10/0x88이 왔다(111회).
  - 살아 있는 상대도 같았다. 메모리 등록 해제는 0x88(90/90), QP 파괴는 0x81(20/20)이었다.
- 측정: 혼잡 알림 처리 카운터는 재시도 초과와 상대 kill에서만 오르는 것처럼 보였지만(105/115), 혼잡이 아니라
  재전송마다 오르는 카운터였다. 실제 혼잡 신호는 125회 모두 0이었고, 오류 없이 끝난 일시 장애에서도 올랐다(10/10).
  그래서 원인 구분에 쓸 수 없다.

**맞힌 것.**
- 검출 시간은 미리 맞힐 수 있었다. 측정 전에 적은 예측이 처음 보는 설정 55회 중 52회에서 1.5 ms 안에
  맞았다.
- 이번 캠페인에서 GIN 프록시의 상대 kill은 12/0x81이 아니라 10/0x88로 보였다. 예측(재시도 초과
  카운터가 오른다)은 틀렸지만, 위의 지우는 순서 규칙과는 맞는다.
- 살아 있는 상대의 오판을 사전 등록하고 쟀다(125회, 예측 34줄 중 33줄 맞음).
  - 데이터 경로는 프로세스 생존을 모른다. 응답 쪽 QP가 요청을 받을 수 없으면 프로세스가 살아 있어도 kill과 같은
    12/0x81이 3.5–3.8 s 뒤에 왔다(55/55). QP가 멀쩡하면 프로세스가 멈춰 있어도 쓰기는 정상 완료했다(10/10).
  - 탐지기는 프로세스가 아니라 제어 연결과 응답 시간을 본다. 살아 있는 상대가 제어 연결만 닫으면 "죽음"(10/10),
    마감보다 오래 멈추면 "복구 불가"(20/20)로 판정됐다. 장애 없이 멈춘 상대는 아무도 알아채지 못했다(15/15).
  - GIN 투명 복구도 같다. 관리망 소켓이 시간 초과로 닫히면 살아 있는 상대의 상대 QP 오류를 상대가 끊은 것으로
    보고 거절했다(10/10).
  - 관리망이 한쪽 방향으로만 끊겨도 같았다. 먼저 시간 초과한 쪽 커널이 보낸 리셋을 받은 쪽이 살아 있는 상대를 죽음으로
    보고 거절했고, 시험 스위치 없는 실제 경주에서도 그랬다(5/5). 리셋을 "모름"으로 두고 다시 연결하게 고치자 오판이
    없어졌고, 죽은 상대는 확인 접속이 거부되어 장애를 본 뒤 1.29–2.12 ms에 판정했다(사전 등록, 예측 28줄 중 23줄 맞음.
    틀린 5줄은 정상 종료 때의 소켓 닫힘까지 죽음으로 센 판정식 탓이다).
- 오판이 시작되는 경계를 사전 등록하고 쟀다. 경계 위치는 소스의 마감 상수와 측정한 지연으로 미리 맞혔다(측정 예측 14줄
  중 12줄 맞음, 판정식을 문자 그대로 읽으면 11줄).
  - CPU harness의 1 s 마감은 커널 타이머가 32 ms 격자로 올려 잡아 실제로 1001.6–1027.1 ms에 끝났다. 정지 990 ms 이하는
    늘 살아 있음, 1040 ms 이상은 늘 응답 없음이었다.
  - GIN 복구의 3 s 핸드셰이크 마감에서는 정지 2992 ms 이하면 늘 복구, 2998 ms 이상이면 늘 거절이었다.
- 관리망 소켓으로 보는 생존 판정을 다듬어 오판을 줄였다(사전 등록).
  - 연결 거부 한 번, 틀린 고유값의 연결, 복구 도중의 소켓 리셋은 죽음으로 보지 않고 다시 연결해 투명하게 복구했다(셀마다 10/10).
    1 s 이상 떨어진 거부 두 번만 죽음으로 정했다(10/10, 첫 거부 뒤 1001.1–1002.2 ms).
  - 거절한 쪽이 재연결에 FAIL로 답하면 상대도 바로 끝낸다. 끊김이 끝난 뒤 0.23–0.44 s에 거절했고(15회), 답하지 않던 이전
    빌드는 8.2–8.5 s를 기다렸다(10회).
- 오류가 어느 상대를 향해 올라왔는지와 그 원인은 다르다. 로컬 원인으로 상대를 거절한 뒤 그 상대를 빼는 중단 shrink는 원래
  오류를 지켰고(rank 2개 10/10, rank 4개 5/5), 원인이 상대 쪽일 때만 넘어갔다.

**한계.** 경계 근처(CPU harness 990–1040 ms, GIN 복구 2992–2998 ms)에서 오판이 날 확률은 재지 않았다.
원인을 가를 수 있는데 아무도 쓰지 않는 정보도 있다.
- 주소 재구성 때 GID 변경 비동기 이벤트가 재시도 초과보다 3.5–3.7 s 먼저 왔다(29/29). 어느 스택도
  이 이벤트를 읽지 않는다.

## 규칙 4. 완료를 받지 않는 쪽은 장애를 모른다

**규칙.** 한쪽에서만 쓰는 통신(RDMA write, put)에서 받는 쪽은 완료를 받지 않는다. 그래서 장애를 알
통로가 처음부터 없고, "기다리던 신호가 오지 않는다"만 알 수 있다. 받는 쪽에 원인을 알리려면 보내는
쪽이 따로 알려 주는 통로가 있어야 한다.

**맞힌 것.**
- GIN 프록시의 받는 쪽: API는 장애 30/30에서 "신호가 오지 않음" 하나로만 끝났고, 비동기 오류는
  0/30이었다. 원격 접근 오류일 때만 받는 쪽 로그에 자기 QP의 오류 경고가 남았다(10/10). 이 경고는 API로
  가지 않는다.
- GIN GDAKI와 분류기의 받는 쪽: blocking 장애 40/40에서 대기와 정리가 모두 멈췄다. 이전 측정에서도
  받는 쪽 비동기 오류는 18/18 없었다.
- 대조: 양방향 통신인 net_ib는 받는 쪽도 자기 수신 완료로 오류를 받았다(20/20).
- NVSHMEM 장애 대응판에서는 시작 쪽이 별도 소켓으로 알려 줄 때만 받는 쪽이 원인을 안다.
- 알려 주는 통로가 있으면, 받는 쪽 장치 대기까지 잇는 데는 abort 신호 하나면 된다. GIN 투명 복구에서 사용자
  devComm에 abort 플래그를 이으니 거절 뒤 받는 쪽 abort가 1 s 안에 돌아왔다(20/20). 잇지 않으면 14.3 s 걸렸다(5/5).
- 그 통로가 끊기면 받는 쪽은 다시 아무것도 모른다. 관리망 소켓이 끊긴 뒤의 거절에서 받는 쪽 비동기 오류는 0/10이었다.
- 받기만 하는 rank도 관리망 소켓으로 상대의 죽음을 알고 그것을 대기에 이으면 오류로 끝난다. 대기가 kill 뒤 20.3–21.7 ms에
  오류로 풀렸고(10/10), 잇지 않은 이전 빌드는 12.35–12.46 s 동안 자기 시간 제한까지 기다렸다(5/5).
- 알리는 통로를 communicator 하나에 묶으면 한 상대의 장애가 다른 상대로 번진다. rank 4개에서 rank 3이 죽자, 중단 신호가
  communicator에 하나뿐인 빌드에서는 살아남은 세 rank 사이의 받기 6개가 모두 실패했다(5/5). 중단 신호를 상대마다 두자
  그 간선 6개가 모두 끝까지 동작했다(10/10).
- 상대를 지정하지 않는 대기는 상대별로 풀 수 없다. 문맥 전체를 기다리는 flush에서는 받는 쪽 6개가 일찍 풀리지 않고 자기
  시간 제한까지 기다렸다(5/5). signal 대기와 배리어도 같아서, 시간 제한으로만 끝난다.
- 오류 뒤에도 데이터 경로가 돌면 받는 쪽은 틀린 결과를 성공으로 받는다. NCCL 2.23.4(복구 끔)에서 rank 1의 수신 QP 오류 뒤
  진행 스레드가 멈추지 않고 중단하는 커널이 덜 된 데이터를 보내, rank 0은 오류 없이 결과의 1/8이 틀린 채 반복을 끝냈다(5/5).
  첫 오류에서 진행 스레드를 멈추는 2.32.3에서는 틀린 결과가 없었다(30/30).

**한계.** 받는 쪽 QP의 상태 변화는 GIN에서 직접 재지 않았다. rank 셋 이상은 GPU 두 개를 프로세스 둘씩 나눠 써서 쟀다.

## 규칙 5. 복구에는 실행 여부를 모르는 구간이 있다

**규칙.** 장애 순간 날아가던 작업이 받는 쪽에 반영됐는지 보내는 쪽은 알 수 없다. 같은 곳에 같은 값을
쓰는 작업은 다시 보내도 안전하다. 하지만 더하기 같은 atomic은 두 번 적용될 수 있다. 그래서 복구는 받는
쪽 상태를 보고 다시 보낼지 정하거나, 다시 보낼 수 없는 결과를 오류로 표시해야 한다.

**근거.**
- 기존 이론: 전송 계층의 성공이 앱 수준의 정확성을 보장하지 않는다(end-to-end argument, Saltzer, Reed,
  Clark 1984).

**맞힌 것.**
- GIN 투명 복구는 받는 쪽 signal 값을 보고 더하기가 빠졌을 때만 다시 보낸다.
  - 복구 130회에서 signal이 모두 기대값과 맞았다.
  - 더하기가 이미 실행된 경우를 강제로 만든 실행도 30/30 정확했다.
- NVSHMEM 장애 대응판의 앞선 판은 실패한 QP의 fetch에서 옛 값을 오류 없이 돌려줬다(40회에 510,028개).
  모든 비트가 1인 표시값을 돌려주도록 바꾼 뒤에는 옛 값이 0개였다(38회).
- NVSHMEM 투명 복구에서 응답 쪽이 실행한 수를 보고 fetch를 다시 보낼지 정했다(사전 등록). 실행되지 않은 fetch는 다시
  보내 투명하게 끝났고(27/27), 이미 실행된 fetch가 있을 때만 거절했다(3/3). 그 거절을 끄고 다시 보내게 하면 실제로
  두 번 적용됐다(2/2).
- GIN 투명 복구는 다시 보낼 수 없는 읽기(get)가 낀 라운드를 성공으로 내보내지 않고 거절했다(10/10, 조용한 실패 0).
- 다시 보낼지는 양쪽이 커밋 전에 합의해야 한다. 응답 쪽이 다시 보내기 계획을 거부했을 때, 시작 쪽이 먼저 다시 보내는
  빌드는 시작 쪽이 다시 보낸 뒤 거절됐다(5/5). 양쪽이 커밋 전에 계획을 검사하게 하자 어느 rank도 다시 보내지 않았다(10/10).
- 같은 포트에서 연결을 다시 세우는 복구는 다른 경로 없이도 된다. NCCL 2.32.3의 port failover와 port recovery는 다른 포트가
  있어야 동작해서, 노드마다 포트가 하나인 환경에서는 295회 중 한 번도 동작하지 않고 QP 장애를 바로 치명적 오류로 끝냈다.
  같은 장애를 같은 포트에서 다시 세우는 다중 요청 복구는 약 2.2–2.3 ms에 투명하게 복구했다(송신, 수신 QP 장애 각 5/5).

**한계.** 이전 판의 "이미 실행된 경우는 강제로만 만들었다"는 원자료와 달라 2026-10-07에 바로잡았다. 더하기까지 실행된
라운드는 GIN 투명 복구에서 실제 장애로도 나왔다(1단계 14/30과 73/150, 2단계 21/30). NVSHMEM에서도 이미 실행된 fetch가 실제
장애로 나왔다(3/10). 강제로만 만든 것은 "쓰기만 실행되고 더하기는 아직" 경우다. 읽기의 재전송은 아직 지원하지 않고 거절한다.
라이브러리 안의 복구가 CUDA 스트림을 거치면 application의 CUDA 호출에 막힐 수 있다. GIN 커널을 띄운 뒤 application이 커널 첫 적재, 메모리
할당, 스트림 생성을 하면 복구용 복사가 그 커널이 끝날 때까지 막혀 거절됐다(10/10). 같은 호출을 커널 전에 하면 GPU가 가득 차
있어도 투명하게 복구됐다(10/10).

## 규칙끼리의 관계

- 규칙 1은 정보가 맨 아래로 들어오는 조건이다.
- 규칙 2는 들어온 정보가 위로 가며 줄어드는 방식이다.
- 규칙 3은 들어온 정보 자체의 한계다.
- 규칙 4는 처음부터 정보가 없는 쪽이다.
- 규칙 5는 그 위에서 복구가 지켜야 할 조건이다.

## 새 스택을 볼 때 묻는 것

소스만 보고 아래 질문에 답하면, 그 스택에서 무엇이 보일지 측정 전에 적을 수 있다.

| 질문 | 아니면 | 규칙 |
|---|---|---|
| record 값이 게시한 작업 수를 따라가나 | 장애가 사라진다 | 1 |
| CQ를 읽는 코드가 원인 CQE를 보나, 뒤따르는 flush만 보나 | 원인이 하나로 뭉개진다 | 2 |
| API가 오류 값을 담을 수 있나 | 장애가 성공으로 보인다 | 2 |
| 받는 쪽에 알리는 통로가 있나 | 받는 쪽은 기다리다 멈춘다 | 4 |
| 상대 생존을 보는 통로가 있나 | 재시도 초과와 상대 kill은 미확정이다 | 3 |
| 다시 보낼 때 실행 여부를 확인하나 | atomic이 두 번 적용될 수 있다 | 5 |
| 받는 쪽 대기가 어느 상대를 기다리는지 아나 | 한 상대의 장애가 다른 상대로 번지거나, 시간 제한으로만 끝난다 | 4 |
| 오류 뒤에 진행 스레드와 커널이 데이터를 그만 보내나 | 받는 쪽이 틀린 결과를 성공으로 받는다 | 4 |
| 복구에 다른 포트나 장치가 필요한가 | 포트가 하나면 복구가 동작하지 않는다 | 5 |

## 범위와 남은 확인

- 노드 한 쌍, NIC 한 종류(ConnectX-6)에서 쟀다. 장애는 소프트웨어로 주입했다.
- 규칙 3의 오판 경계는 쟀지만, 경계 근처에서 오판이 날 확률은 재지 않았다.
- rank 셋 이상(규칙 4)은 GPU 두 개를 프로세스 둘씩 나눠 쓴 rank 4개까지 쟀다.
- 규칙 1은 스택 14개에 소스로 적용해 봤고, 그중 이 테스트베드에서 잴 수 있는 경로만 쟀다. 소스로만 예측한
  경로(UCX GPU의 지연 게시, rocSHMEM 등)는 재지 않았다.

## 근거 문서

| 규칙 | 문서 |
|---|---|
| 1 | [nvshmem_rootcause/README.md](harness/gpu-initiated/nvshmem_rootcause/README.md), [official380/README.md](harness/gpu-initiated/nvshmem_rootcause/official380/README.md), [cq380/README.md](harness/gpu-initiated/nvshmem_rootcause/cq380/README.md), [completion_contract/README.md](harness/gpu-initiated/completion_contract/README.md) |
| 2, 4 | [propagation/README.md](harness/gpu-initiated/propagation/README.md), [LAYERS.md](harness/gpu-initiated/propagation/results/20261006_campaign/LAYERS.md), [REVIEW_20261006.md](harness/gpu-initiated/propagation/REVIEW_20261006.md) |
| 3 | [teardown_order/README.md](harness/teardown_order/README.md), [ack_timeout/README.md](harness/ack_timeout/README.md), [stage2/README.md](harness/nccl-integration/stage2/README.md), [live_peer/README.md](harness/live_peer/README.md), [boundary/README.md](harness/live_peer/boundary/README.md), [s2_close/README.md](harness/gpu-initiated/gin_recovery/s2_close/README.md), [oneway/README.md](harness/gpu-initiated/gin_recovery/oneway/README.md), [harden/README.md](harness/gpu-initiated/gin_recovery/harden/README.md), [handoff/README.md](harness/gpu-initiated/gin_recovery/handoff/README.md), [peer/README.md](harness/gpu-initiated/gin_recovery/peer/README.md) |
| 4 | [gin/README.md](harness/gpu-initiated/gin/README.md), [nvshmem_ft/README.md](harness/gpu-initiated/nvshmem_ft/README.md), [s2_close/README.md](harness/gpu-initiated/gin_recovery/s2_close/README.md), [harden/README.md](harness/gpu-initiated/gin_recovery/harden/README.md), [multirank/README.md](harness/gpu-initiated/gin_recovery/multirank/README.md), [peer/README.md](harness/gpu-initiated/gin_recovery/peer/README.md), [builtin/README.md](harness/nccl-integration/builtin/README.md) |
| 5 | [gin_recovery/README.md](harness/gpu-initiated/gin_recovery/README.md), [nvshmem_ft/README.md](harness/gpu-initiated/nvshmem_ft/README.md), [t1_close/README.md](harness/gpu-initiated/nvshmem_ft/t1_close/README.md), [s2_close/README.md](harness/gpu-initiated/gin_recovery/s2_close/README.md), [harden/README.md](harness/gpu-initiated/gin_recovery/harden/README.md), [handoff/README.md](harness/gpu-initiated/gin_recovery/handoff/README.md), [peer/README.md](harness/gpu-initiated/gin_recovery/peer/README.md), [builtin/README.md](harness/nccl-integration/builtin/README.md) |

참고 문헌:
- Mellanox Adapters Programmer's Reference Manual, Rev 0.40.
- M. J. Fischer, N. A. Lynch, M. S. Paterson. Impossibility of Distributed Consensus with One Faulty
  Process. JACM 1985.
- T. D. Chandra, S. Toueg. Unreliable Failure Detectors for Reliable Distributed Systems. JACM 1996.
- J. H. Saltzer, D. P. Reed, D. D. Clark. End-to-End Arguments in System Design. ACM TOCS 1984.
- M. Hiller, A. Jhumka, N. Suri. PROPANE: An Environment for Examining the Propagation of Errors in
  Software. ISSTA 2002.
- P. Huang et al. Gray Failure: The Achilles' Heel of Cloud-Scale Systems. HotOS 2017.
