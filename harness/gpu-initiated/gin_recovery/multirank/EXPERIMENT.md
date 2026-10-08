# GIN 투명 복구를 랭크 3–4개로: GPU 하나에 프로세스 둘 (gin-multirank)

**목적:** 노드마다 GPU가 하나인 이 테스트베드에서 GPU마다 프로세스 둘을 두어 랭크 4개(노드마다 2개)와 랭크 3개(2+1)의 GIN GDAKI
통신기를 만들고, 투명 복구가 상대가 여럿일 때도 한 쌍의 장애를 그 쌍 안에서 복구하는지, 여러 쌍의 장애와 한 랭크의 죽음을 어떻게 다루는지,
소스에서 찾은 순환 대기가 실제로 생기는지를 잰다.

| 항목 | 값 |
|---|---|
| 상태 | `DRAFT` |
| 담당자 | @unionxic |
| 작성일 | 2026-10-09 |
| 기준 브랜치와 커밋 | `exp/gin-multirank` @ `d834f86c` (master) |
| 사전 등록 태그 | 없음. 파일럿 뒤 확정한 예측을 사전 등록 커밋에서 태그로 고정한다(3절) |
| 마지막 갱신 | 2026-10-09, 파일럿 P0(`ow`) 검토와 예측 확정(3.6), `mr/hd` 배포 기록 |

표시: `[측정]` 원자료나 시행별 표에서 확인, `[소스]` 코드에서 읽음, `[추론]` 해석, `[미확인]` 확인 안 함.

이 문서의 소스 줄 번호는 gin-oneway 라이브러리 트리(빌드 `ow`)의 것이다. 세션 스크래치 `agent_ts2ow/nccl-src`의 작업 트리이고, 파일 md5 앞
8자는 `gin_host_gdaki.cc` `b63f505d`, `gin_gdaki.h` `43413e53`, `init.cc` `9c57a672`, `graph/paths.cc` `f9e578a2`, `dev_runtime.cc`
`1b82f51f`, `gin/gin_host.cc` `58007ef4`다 `[측정]`. 장치 쪽 헤더는 설치된 `build/include` 트리를 쓴다(9절 빌드).

**용어.**
- 간선 a>b: rank a가 보내고 rank b가 받는 방향 하나. 랭크 4개면 간선이 12개다. 노드 사이 간선은 8개, 노드 안 간선(rain의 0과 2, sunny의
  1과 3 사이)은 4개다.
- 문맥: GIN context. 이 실험의 드라이버는 간선마다 문맥 하나를 쓴다(9절 1번). 문맥 하나는 상대마다 QP 하나를 가진다.
- helper: 투명 복구가 GDAKI 문맥 묶음(이 실험에서는 랭크)마다 하나 띄우는 호스트 스레드. 장애를 맡아 상대와 복구 라운드를 연다.
- 시작 쪽, 응답 쪽: 라운드를 여는 helper와 그 요청(REQ)에 답하는(ACK) helper.
- 쌍 범위 라운드: 장애 난 문맥의 QP 쌍 하나만 다루는 라운드(gin-pair-reset). 전체 범위 라운드: 두 랭크 사이의 모든 문맥의 QP를 다루는 라운드.
- 거절: helper가 복구를 포기하고 오류를 앱에 드러내는 것. 상대마다 정해진다.
- 문맥 전체 flush: `gin.flush(ncclCoopCta())`. 기존 드라이버 `gin_ts2`가 쓰는 방식이다. 상대별 flush: `gin.flushAsync(world, peer)`와
  한도가 있는 `gin.wait`.
- 게이트 epoch: QP마다 호스트가 쓰는 값. 라운드 하나를 거치면 2 늘고, 거절도 짝수로 올린다. teardown 때 각 랭크가 상대별로 남긴다.
- 메일박스: 장치가 분류한 오류 기록을 helper에게 넘기는 호스트 메모리의 칸 16개.

장애 기호와 셀 이름은 원자료를 찾는 키로만 괄호나 표의 id 열에 둔다.

| 장애 | 기호 |
|---|---|
| 로컬 QP 오류 | F1 |
| 상대 QP 오류 | F3 |
| 상대 프로세스 kill | F4 |

빌드 키는 둘이다. 드라이버는 빌드마다 따로 만든다(장치 API가 헤더에만 있어서, 실행할 libnccl의 헤더로 컴파일해야 한다).

| 빌드 | 키 | 내용 |
|---|---|---|
| gin-oneway 라이브러리 | `ow` | libnccl `b4af65c5`(`$HOME/gi-bundle/gin_ts2/ow/`, 2026-10-08 배포). 파일럿에 쓴다 |
| gin-harden 라이브러리 | `hd` | libnccl `e2090323`(`$HOME/gi-bundle/gin_ts2/hd/`, gin-harden이 배포). 본 실행에 쓴다. 장치 헤더가 `ow`와 달라 드라이버를 따로 빌드했다(5절) |
| 이 실험의 드라이버 | `mr/<키>` | `gin_mr`(이 폴더의 `gin_mr.cu`)만 담은 새 디렉터리 `$HOME/gi-bundle/gin_ts2/mr/<키>/`. libnccl은 그 빌드의 번들에서 쓴다 |

## 1. 배경과 연구 질문

**지금까지의 측정.** GIN 투명 복구의 측정은 모두 랭크 2개, 노드마다 GPU 하나와 프로세스 하나였다 `[측정]`(각 실험 5절; gin-oneway 4절은
"3 rank 이상"을 범위에서 뺐다). 상대가 하나뿐이라 다음은 한 번도 일어나지 않았다.
- 한 helper가 여러 상대와 라운드를 차례로 처리하는 일, 서로 다른 쌍의 라운드가 동시에 열리는 일.
- 복구 중인 쌍 말고 다른 쌍이 계속 트래픽을 보내는 일.
- 한 랭크가 죽었을 때 살아남은 여럿이 그 상대만 거절하는지.

이 테스트베드는 노드마다 GPU가 하나다. 랭크를 늘리려면 GPU 하나에 프로세스 둘을 둬야 한다.

**같은 GPU에 랭크 둘** `[소스]`.
- NCCL은 같은 호스트에서 두 랭크가 같은 GPU를 쓰면 초기화를 거부한다. `NCCL_MULTI_RANK_GPU_ENABLE=1`이면 이 검사를 건너뛴다
  (`init.cc` 1286–1296). 같은 장치를 쓴다는 표시(`hasMultiRankNvml`)는 NVLS만 끈다(`transport/nvls.cc` 170).
- GIN의 대칭 메모리는 같은 노드의 모든 랭크가 CUDA P2P로 이어질 것을 요구한다(`init.cc` 1934의 `isAllCudaP2p`). `ncclTopoCheckP2p`는
  같은 물리 GPU의 두 랭크를 NVML 검사 없이 "같은 호스트이므로 P2P 가능"으로 본다(`graph/paths.cc` 397–458).
- `NCCL_CROSS_NIC` 기본값이 2라서 GIN은 모든 랭크가 서로 이어지는 FULL 연결이 된다(`graph/search.cc` 16, `init.cc` 1923–1927). 드라이버는
  FULL을 요청한다.
- LSA 팀(서로 메모리를 직접 매핑하는 랭크 묶음)의 크기는 연속된 랭크 중 같은 노드에 있는 수의 최대공약수다(`dev_runtime.cc` 128–153).
  이 실험은 랭크를 번갈아 둔다(rain 0, 2, sunny 1, 3). 그러면 LSA 팀은 랭크 하나라서, 어느 프로세스도 다른 프로세스의 GPU 메모리를
  매핑하지 않는다. 연속 배치(rain 0, 1)는 크기 2가 되어 같은 GPU의 두 프로세스가 서로의 메모리를 매핑하므로 쓰지 않는다.

**노드 안 쌍의 경로** `[소스]`.
- GDAKI 문맥을 만들 때 다른 모든 랭크에 QP를 하나씩 잇는다. 상대가 같은 노드인지는 보지 않는다(`gin_host_gdaki.cc` 4863–4886).
- 장치 API의 `put`은 언제나 상대의 GDAKI QP로 간다. LSA 경로로 바꾸는 분기가 없다(`nccl_device/impl/gin__funcs.h`의 `put`).
- 그래서 노드 안 쌍(rain의 0과 2)은 같은 NIC 안에서 되돌아가는 RC QP 쌍(NIC loopback)으로 통신한다. 두 프로세스 사이의 RoCE loopback
  트래픽은 이 테스트베드에서 재 본 적이 없다 `[미확인]`. 파일럿 P0(`ow`)에서는 노드 안 간선이 장애 없는 랭크 4개 시행 4회에서 모두
  정확히 전달됐고, 간선 0>2의 로컬 QP 오류가 쌍 범위 라운드로 투명하게 복구됐다(1회) `[측정, 파일럿]`.
- GIN 통신기의 allgather 고리는 rank r에서 r+1로 이어진다(`transport/net_ib/gin.cc` `ncclGinIbConnect`). 랭크 4개를 번갈아 두면 고리의
  모든 연결이 노드 사이다. 랭크 3개면 2에서 0으로 가는 연결 하나가 rain 안이다.

**장애 훅** `[소스]`. `NCCL_GIN_FAULT_INJECT=local_err:<ms>`는 그 랭크의 QP를 상대 모두에게 걸쳐 ERR로 옮긴다. 상대를 고르는 스위치는 없다.
`NCCL_GIN_FAULT_INJECT_CTX=<c>`를 주면 문맥 c의 QP만 옮긴다(`gin_host_gdaki.cc` 648–685). 그래서 드라이버는 간선마다 문맥을 따로 주어,
문맥 번호로 간선 하나를 고르게 한다(9절 1번). 이때 그 문맥의 나머지 상대 N−2개로 가는 QP도 ERR이 되지만 그 QP로는 아무것도 보내지 않는다.
다만 그 QP가 그 랭크에 쌍 범위 라운드를 요청하는 상대로 가는 QP이면, 응답 쪽 범위 확인이 범위 밖 QP가 RTS가 아니라며 그 요청을 거부한다.
시작 쪽은 같은 장애를 곧 전체 범위로 다시 연다(사유 `peer`). 순환과 사슬 셀에서 생긴다. 초안의 소스 분석은 이것을 놓쳤고 파일럿 순환
시행에서 처음 봤다(3.6) `[소스, 측정]`.

**helper와 상대 여럿** `[소스]`.
- 랭크마다 helper 스레드 하나다(`gdakiTsStart` 4363). 상대마다 관리망 TCP 소켓 하나를 연다. 낮은 rank가 높은 rank에 연결하고 높은 rank가
  받는다(`gdakiTsSetup` 4121–4174). 수신 대기 포트는 eno1 주소의 임의 포트라서 한 노드의 두 프로세스가 부딪치지 않는다(4074–4089).
- 장애 기록은 하나씩 처리한다(`gdakiTsMain` 4014–4028). 시작 쪽은 ACK를 기다리는 동안 그 상대의 소켓만 읽는다(`gdakiTsInitiate`
  3696–3782). 다른 상대의 REQ는 helper가 자기 루프로 돌아올 때까지 소켓에 남는다(3993–4013).
- **순환 대기.** 그래서 시작 쪽 셋이 X에서 Y, Y에서 Z, Z에서 X로 동시에 라운드를 열면, 셋 모두 오지 않을 ACK를 한도까지 기다린다. 한도는
  라운드 시작 + min(3 000 + 5 000 + 1 000 + 경로 대기 21 000, 25 000 − 500) = 라운드 시작 + 24 500 ms다(`gdakiTsRoundLeftMs` 2171–2176,
  3694–3695; 경로 대기는 시작 때 21 000 ms로 잘린다, 4291–4299). 그 뒤 "handshake timeout"으로 거절한다. 랭크 2개로는 순환을 만들 수 없어
  한 번도 재지 않았다.
- **메일박스.** GDAKI 문맥 묶음마다 칸 16개다(`NCCL_GIN_GDAKI_Q4_NSLOTS`, 칸 = (seq − 1) mod 16, `gin_gdaki.h` 947–952). QP마다 epoch당
  한 번만 기록한다(987). 기록에는 상대와 문맥이 들어 있다. 넘쳐 잃은 기록은 helper의 주기 검사가 거절로 드러낸다(3886–3909). 이 실험에서
  한 랭크가 보내는 QP는 많아야 N−1개라서 한 번의 장애로 생기는 기록은 3개 이하다. 넘침은 예상하지 않는다.
- **라운드 범위.** 시작 쪽은 그 상대로 가는 다른 QP가 모두 RTS이고 그 상대의 다른 문맥 기록이 기다리지 않으면 쌍 범위로 줄인다. 아니면
  전체 범위다(`gdakiTsDecideScope` 2245–2298). 응답 쪽은 범위 밖 자기 QP가 RTS인지 확인하고 받는다(`gdakiTsCheckScope` 2304–2327).

**flush의 범위와 거절의 번짐** `[소스]`.
- 문맥 전체 flush는 그 문맥의 **모든 상대**의 QP를 기다린다(`gin_gdaki.h` `flushImplModeCore` 1183–1267, 상대마다 반복). 그리고 그 문맥의
  붙는 오류 표시(sticky)를 돌려준다(`gin__funcs.h` 977–985).
- 거절은 그 상대로 가는 **모든 문맥**의 QP를 실패로 표시하고(`gdakiTsDecline` 3334–3369, 범위 전체, `HOST_FAILED`), 모든 문맥의 붙는 오류
  표시를 켠다(64칸을 한꺼번에 1로 채움, 3352).
- 그래서 한 상대를 거절한 랭크에서는 그 뒤 모든 문맥 전체 flush가 실패한다. 상대가 멀쩡해도 그렇다.
- 상대별 flush는 그 간선의 QP 하나만 보고, 한도가 있는 `wait`는 그 QP의 결과만 돌려준다(붙는 오류 표시를 보지 않음; `flushAsyncImpl`
  688–747, `waitImplCore` 1081–1168, `gin__funcs.h` 1186–1197).
- 전체 범위 라운드도 같은 이유로 번진다. 라운드 동안 그 상대로 가는 모든 문맥의 QP가 홀수 epoch이므로, 그 랭크의 문맥 전체 flush는 모두
  라운드가 끝나기를 기다린다.
- 거절은 통신기 전체의 GIN 비동기 결과를 오류로 바꾼다(3355–3358). 그 랭크의 앱은 `ncclCommGetAsyncError`로 이를 본다.

**본 실행 빌드 `hd`에서 달라지는 점** `[소스]`(`agent_ts2hd/nccl-src`, `gin_host_gdaki.cc` md5 `36995301`; 그 작업 트리의 diff는
gin-harden의 `hd_layer.diff`와 index 줄을 빼고 같다 `[측정]`).
- **거절은 랭크 전체의 장치 대기를 오류로 푼다.** 거절(`gdakiTsDecline` 4052–4099)이 통신기마다 하나인 사용자 devComm abort 단어에
  오류 비트(`NCCL_DEVCOMM_ABORT_ERROR`)를 쓴다. `waitSignal`과 `flush`, `wait`은 폴링 10 000번마다 그 단어를 보고 오류를 돌려준다
  (`utility.h` `testAbort`, `gin__funcs.h` `waitRollingLessEq`, `gin_gdaki.h` `tsPoll`, `waitImplCore`, `flushImplModeCore`).
  - 15 ms 간격 동안 다음 signal을 기다리는 받는 쪽은 곧 그 확인에 닿아 오류로 끝난다.
  - 건강한 상대로의 put은 약 10 µs에 끝나므로, 상대별 flush의 대기는 그 확인 전에 성공한다 `[추론]`. 문맥 전체 flush는 ow와 같이 거절된
    상대의 QP에서 바로 실패한다.
- **죽음은 바로 판정하고 바로 거절한다.** BYE 없는 FIN은 죽음이고(`gdakiTsSocketLost` 3008–3039), helper 루프가 장애를 기다리지 않고
  "peer judged dead: the peer's socket shows <원인>"으로 거절한다(`gdakiTsMain` 5010–5019). 리셋이면 1 000 ms 이상 떨어진 거부 두 번 뒤
  죽음이다(`gdakiTsRefused` 3043–3064). 정상 정리는 BYE를 먼저 보내므로 "떠남"이다.
- **순환 대기는 그대로다.** ACK를 기다리는 동안 그 상대의 소켓만 읽는 구조와 한도(`gdakiTsRoundLeftMs` 2512–2517, `gdakiTsInitiate`
  4576–4669)가 바뀌지 않았다.
- **범위 결정, 응답 쪽 범위 확인, 정지(quiesce)는 펌웨어 단계 감시만 더해졌다**(`gdakiTsDecideScope`, `gdakiTsCheckScope`,
  `gdakiTsQuiesce`를 ow와 함수 단위로 비교).
- **라운드 상한.** 문맥(이 실험에서는 랭크)마다 60 000 ms 안의 라운드(두 역할)가 8번이면 거절하고 복구를 멈춘다(`gdakiTsEscalated`
  4207–4231). 문맥 수가 아니라 라운드 수를 센다. 전체 범위 라운드는 12개 문맥을 덮어도 한 번이다. 이 실험의 셀에서 한 랭크의 라운드는
  많아야 3번(`mr4_f1all0`의 rank 0)이라 상한에 닿지 않는다.
- 문맥 번호 대신 고유값(nonce)을 HELLO에 싣는다. 이 실험의 셀에는 재연결이 없어 영향이 없다. 시험 스위치
  `NCCL_GIN_TS_TEST_STALL`, `NCCL_GIN_FAULT_INJECT_CTX`는 연구 빌드 `hd`에 그대로 있다(`gin_host_gdaki.cc` 5285, 677).

**GPU 하나를 두 프로세스가 쓰기.**
- 두 프로세스의 CUDA 문맥은 GPU를 시분할로 나눠 쓴다고 본다 `[추론]`. 이 테스트베드에서 GDAKI 커널로 재 본 적은 없다 `[미확인]`.
- 한 프로세스 안에서는 GIN 받는 커널이 먼저 돌면 다른 스트림의 GIN 보내는 커널이 그것이 끝날 때까지 시작하지 않았다(원인 모름). 한 커널에
  두 역할을 두면 함께 돌았다(`../TRANSPARENT_S2.md` C) `[측정, 랭크 2개]`. 이 실험의 드라이버는 랭크마다 커널 하나에 모든 간선을 CTA로
  둔다.
- 두 노드 GPU의 컴퓨트 모드는 확인하지 않았다 `[미확인]`. 한 프로세스만 허용하는 모드면 두 번째 프로세스가 GPU를 쓰지 못한다. hold의
  스냅숏이 기록한다(9절).
- 파일럿 P0(`ow`)에서 두 노드 모두 `Default` 모드였고, GPU마다 프로세스 둘인 랭크 4개 시행이 교착 없이 돌았다 `[측정, 파일럿]`. 간격 없는
  지연 측정에서는 한 반복이 2 335 µs까지 걸렸고(랭크 2개는 20 µs, 실행 1회씩), 15 ms 간격 트래픽에서는 18.4 µs 이하였다(장애 없는 랭크
  4개 시행 3회). 복구 라운드의 단계 시간도 트래픽 중에 길었다. 문맥 12개 라운드의 commit이 트래픽 중 260–265 ms, 트래픽이 끝난 뒤
  14–137 ms였다(3.6) `[측정]`. 원인은 시분할로 본다 `[추론]`.

**질문.**
1. GPU마다 프로세스 둘로 랭크 4개와 랭크 3개의 GIN GDAKI 통신기가 만들어지고 모든 쌍에 투명 복구가 켜지는가. 두 프로세스의 GDAKI 커널이
   GPU를 나눠 써도 교착 없이 모든 간선이 정확히 전달되는가.
2. 한 쌍의 장애(로컬 QP 오류, 상대 QP 오류; 노드 사이 간선, 노드 안 간선)가 그 쌍만 다루는 라운드로 투명하게 복구되고, 그동안 다른 간선은
   계속 진행하는가.
3. 여러 쌍의 동시 장애(겹치지 않는 두 쌍, 한 응답 쪽으로 오는 두 시작 쪽, 한 랭크의 모든 간선)가 helper의 차례 처리로 모두 복구되는가.
4. 한 랭크가 죽으면 살아남은 랭크들은 그 상대만 거절하는가. 앱이 보는 결과는 flush 방식(문맥 전체, 상대별)에 따라 어떻게 다른가.
5. 시작 쪽 셋이 순환하면 소스에서 읽은 대로 ACK 한도까지 서로 기다리는가.
6. 장애 없는 지연은 랭크 2개와 비교해 어떤가(탐색).

## 2. 가설

| id | 가설 | 다음이 관측되면 틀린 것이다 |
|---|---|---|
| H1 | GPU마다 프로세스 둘로 통신기와 문맥 12개의 devComm이 만들어지고 네 랭크 모두 투명 복구가 켜진다. 두 프로세스의 커널은 GPU를 시분할로 나눠 써서 간선 12개가 모두 정확히 전달된다 | 랭크 4개 장애 없는 셀에서 초기화 실패나 투명하지 않은 시행이 2회 이상이다 |
| H2 | 한 쌍의 장애는 그 쌍의 QP 하나만 다루는 라운드 하나로 투명하게 복구되고, 다른 간선은 그동안 계속 진행한다. 노드 안 간선(NIC loopback)도 같다 | 한 쌍 장애 셀 셋 중 하나라도 쌍 범위 복구나 투명이 9/10 미만이다. 또는 상대 QP 오류로 묶인 동안 다른 간선이 100번 이상 진행한 시행이 9/10 미만이다 |
| H3 | 여러 쌍의 장애는 각 helper가 차례로 처리해 모두 복구된다. 한 랭크의 모든 간선 장애는 상대마다 전체 범위 라운드 하나씩이다 | 동시 장애 셀 셋 중 하나라도 예측한 라운드와 투명이 9/10 미만이다. 또는 한 helper의 두 라운드가 시간상 겹친다 |
| H4 | 한 랭크가 죽으면 살아남은 랭크의 helper는 소켓으로 곧바로 죽음을 판정해 그 상대만 거절한다. 그 거절이 랭크의 사용자 abort 단어를 올리므로 살아남은 랭크 사이의 받는 쪽은 flush 방식과 상관없이 오류로 끝난다. 보내는 쪽은 문맥 전체 flush에서는 거절된 QP 때문에 멈추고, 상대별 flush에서는 끝까지 성공한다 | kill 셀에서 거절 대상이 rank 3뿐이고 kill 2 s 안인 시행이 9/10 미만이다. 또는 문맥 전체 flush에서 살아남은 간선의 보내는 쪽 6개가 모두 실패한 시행, 상대별 flush에서 받는 쪽 6개가 모두 실패하고 보내는 쪽 6개가 모두 성공한 시행이 각각 9/10 미만이다 |
| H5 | 시작 쪽 셋이 순환하면 ACK 한도(라운드 시작 + 24.5 s)까지 서로 기다린 뒤 "handshake timeout"으로 거절한다. 순환이 없는 사슬은 바로 풀린다 | 순환 셀에서 그 거절과 시각이 4/5 미만이다. 또는 사슬 셀이 투명하지 않다 |
| H6 | (탐색) 장애 없는 지연의 중앙값은 랭크 수가 늘어도 거의 그대로이고, GPU 시분할은 드문 긴 반복으로만 보인다 | 지연 예측(3.3 L1–L5)이 틀린다. 탐색 예측(L3, L4)은 틀려도 가설 H1–H5에 영향을 주지 않는다 |

## 3. 사전 예측 (측정 전에 작성)

**예측은 파일럿 P0 뒤에 확정했다(2026-10-09).** 고정은 아직이다. 순서는 다음과 같았다.
1. 본 실행 빌드 `hd`가 나와 3.5대로 그 diff를 읽고, 바뀐 코드에 기댄 예측을 다시 썼다.
2. 본 세션이 파일럿 P0을 `ow`로 돌렸다(17회, 채점하지 않음). 그 결과를 3.6에 적었다. 3.4의 값은 하나도 바꾸지 않았다. 파일럿이 소스
   분석의 빈틈 하나(훅이 ERR로 둔 QP 때문에 응답 쪽이 쌍 범위 요청을 거부함)와 열 하나의 잘못(`init_total_ms_min`)을 보여, 그것에 기댄
   예측을 고치고 하나를 더했다(Y3, Z1, Z2. F2, R1은 근거 문장만). 무엇을 왜 바꿨는지 3.6과 12절에 있다. 파일럿에서 맞거나 틀렸다는
   이유만으로 바꾼 예측은 없다.
3. 다음은 상태 `PREREGISTERED`, 12절 기록, `PREREG.txt`(예측 파일 sha256)를 커밋 하나로 만들고 그 커밋에 `prereg/gin-multirank-v1` 태그를
   다는 일이다. 그때부터 2, 3, 7, 8절과 [predictions.csv](predictions.csv)는 고치지 않는다.

파일럿 시행은 어떤 예측의 판정에도 쓰지 않는다. 파일럿 결과 폴더는 `score.py`에 넘기지 않는다.

예측 원문은 [predictions.csv](predictions.csv)이고 42줄이다. `kind`는 N(새 셀), C(대조), X(탐색)다.

### 3.1 판정에 쓰는 열

시행마다 한 줄이다. 모든 열은 이 폴더의 [rows_mr.py](rows_mr.py)가 시행 파일(`<stem>_meta.txt`, 랭크마다 `<stem>_r<r>.kv`와
`<stem>_r<r>.log`, `<stem>_kill.out`)에서 만든다. 정의 원문은 그 파일 머리말이고, 지금 고정한다. 목록은 정렬해 `;`로 잇는다. "R-P"는 랭크
R과 상대 P, "a>b"는 간선이다. 시각은 CLOCK_MONOTONIC ms이고, "rank 0 시계"는 rank 0 kv의 `clock_offset_ms_r<r>`를 뺀 값이다.

| 열 | 출처와 정의 |
|---|---|
| `cell`, `build`, `n`, `flush`, `iters` | meta 줄. `build`는 libnccl 빌드 키 |
| `init_fail`, `n_devcomm`, `mrge_err` | kv에 `devcomm_mono_ms`가 있는 랭크 수가 n보다 작으면 1. 로그에 "Multiple Ranks are using the same GPU"가 있으면 `mrge_err` 1 |
| `n_ts_on`, `gq_min`, `gq_max` | `GIN/TS: transparent recovery ON rank=<r> gated_qps=<q>` 줄 수와 q의 최소, 최대 |
| `n_ua`, `n_pr`, `n_pc`, `n_ow` | abort 플래그, pair reset=1, pair check=1, `helper liveness oneway=1` 줄 수(설정 확인, 8절) |
| `transparent_ok` | 모든 간선이 정상이고, 모든 랭크의 결과가 `ok`이고, 어느 랭크도 비동기 오류를 보지 않았으면 1. 간선 a>b가 정상이려면 보낸 쪽 `tx_ab_done == iters`, `tx_ab_rc == "no error"`, 받은 쪽 `rx_ab_done == iters`, `rx_ab_rc == "no error"`, 장치와 호스트의 틀린 칸 0, 마지막 signal이 정확해야 한다 |
| `edges_bad`, `async_ranks` | 정상이 아닌 간선 목록, 비동기 오류를 본 랭크(`r0,r1,...`) |
| `fires`, `fire_in_traffic` | `GIN/FAULT: GDAKI fault fired` 줄을 "랭크:문맥"(문맥 없으면 `all`)으로. 모든 발사가 그 랭크의 커널 시작 뒤, 시작 + iters × 간격 전이면 1 |
| `rounds` | `GIN/TS: rank R: round K peer P scope=S qps=Q reason=X` 줄을 "R>P:Q:X"로 |
| `rec_i`, `rec_r`, `n_rec_i` | `GIN/TS: recovered rank=R peer=P role=initiator`(또는 `responder`) 줄을 "R-P"로 |
| `decl`, `decl_reasons`, `n_decl`, `n_hs` | `GIN/TS: declined rank=R peer=P reason="..."` 줄을 "R-P", "R-P=<사유>"로. 사유가 "handshake timeout"인 줄 수 |
| `n_watchdog`, `n_refused` | `GIN/TS: watchdog rank=` 줄 수, 응답 쪽 범위 확인의 "refused" 줄 수 |
| `ep_nz`, `n_ep_nz`, `ep_peers` | teardown 줄 `GIN/TS: rank R gate epochs to rank P: [...]`에서 0이 아닌 칸을 "R-P-문맥=값"으로. 나오는 상대를 "p<P>"로 |
| `notrts`, `n_notrts`, `notrts_peers` | teardown 줄 `GIN/TS: rank R qp states to rank P: [...]`에서 3(RTS)이 아닌 칸을 "R-P-문맥=상태"로(6 = ERR) |
| `q4_first` | 각 랭크의 첫 "device-classified error CQE" 줄의 분류를 "랭크:분류"로 |
| `killed`, `kill_ms0`, `kill_in_traffic` | kill.out에 `kill_mono_ms`가 있으면 1. rank 0 시계의 kill 시각. 모든 랭크의 커널 시작 뒤이고 가장 이른 트래픽 끝보다 5 000 ms 이상 앞서면 1 |
| `decl_after_kill_ms_r<r>` | rank r의 첫 거절(rank 0 시계) − `kill_ms0` |
| `n_surv_edges`, `surv_edges_ok`, `surv_tx_failed`, `surv_rx_failed` | kill 셀: 죽은 랭크가 끼지 않은 간선 수, 그중 정상인 수, 그중 보낸 쪽 결과가 `no error`가 아닌 수, 받은 쪽 결과가 `no error`가 아닌 수 |
| `n_hd`, `n_judged_dead`, `n_esc`, `n_fw_over`, `n_copy_to`, `n_cancel` | `hd`의 줄 수: 시작 줄 `GIN/TS: harden=1 rank=`, `rank P judged dead`, `escalated rank=`, 펌웨어 단계가 `more than NCCL_GIN_TS_FW_MS`, 복사가 `(NCCL_GIN_TS_COPY_MS)`, 라운드가 `cancelled ... before the commit` |
| `f3_detect_ms` | rank 0의 첫 분류 기록 − rank 1의 첫 훅 발사(rank 0 시계) |
| `win_edge_r<r>`, `w_<ab>_in` | 드라이버 kv. 그 랭크가 보낸 반복 중 가장 오래 걸린 반복의 간선, 그리고 다른 보내는 간선이 그 반복 안에 시작해서 끝낸 반복 수 |
| `resp_overlap_r0`, `init_overlap_r0` | rank 0의 응답 라운드 [`t_req`, `t_resumed`] (시작 라운드 [`t_start`, `t_resumed`]) 둘이 겹치면 1, 아니면 0. 둘 미만이면 빈칸 |
| `cyc_spread_ms`, `hs_first_after_round_ms` | 라운드 줄이 있는 랭크들의 첫 라운드 시각(rank 0 시계)의 최대 − 최소. 가장 이른 "handshake timeout" 거절의, 그 랭크 첫 라운드 줄로부터의 시간 |
| `init_total_ms_min`, `init_total_ms_max` | 시작 쪽 recovered 줄의 `total_us` / 1000의 최소, 최대. 거부되어 전체 범위로 다시 연 라운드는 다시 연 때부터 센다 |
| `rec_first_after_round_ms`, `rec_last_after_round_ms` | 모든 recovered 줄(두 역할)의 `t_resumed`(rank 0 시계) 중 가장 이른 것과 늦은 것 − 그 시행의 가장 이른 라운드 줄 시각(rank 0 시계). recovered 줄이 없으면 빈칸. 파일럿 뒤 더함(3.6) |
| `knob_stall` | `GIN/TS: TEST knobs rank=<r> stall_ms=<ms>` 줄을 "랭크:ms"로 |
| `p50_01`, `p50_inter_med`, `max_all` | 간선 0>1의 p50, 노드 사이 간선 p50의 중앙값, 모든 간선의 최대 지연(µs, 보낸 쪽 kv) |

### 3.2 셀 키와 판정식 문법

셀 키(`cell@build`), 판정 대상(8절 제외를 거친 시행), "자료 부족" 규칙, 판정식 문법(`count`, 빈칸 규칙, `has`, `nonempty`, `median`, `abs`,
`per cell:`)은 `../oneway/EXPERIMENT.md` 3.2절과 같다(곧 `../s2_close/EXPERIMENT.md` 3.2절과 산술, 비교). 이 실험의 `score.py`는
`../s2_close/score.py`의 판정식 평가 함수를 그대로 불러 쓴다. 숫자로 읽히는 값은 실수가 되므로, 목록 열은 숫자로 읽히지 않는 꼴("0-1",
"r0", "p3")로 적는다. 시행에 없는 열은 빈칸으로 채운다. 판정은 맞음, 틀림, 자료 부족 중 하나다.

### 3.3 예측 요약

전체 판정식은 [predictions.csv](predictions.csv)에 있다. 아래는 요약이다. 본 실행 빌드의 셀 키는 `@hd`다.

| id | 셀 | 예측 | 판정 기준(요약) | 근거 |
|---|---|---|---|---|
| I1 | `mr4_none` | 랭크 4개가 통신기와 문맥 12개 devComm을 만들고, 네 랭크 모두 게이트 QP 36개로 투명 복구가 켜진다 | ≥9/10 | 1절의 같은 GPU, P2P, FULL, LSA 분석 `[소스]` |
| I2 | `mr4_none` | 두 프로세스가 GPU를 나눠 써도 간선 12개가 모두 정확하고 비동기 오류가 없다 | ≥9/10 | 시분할 `[추론]`, loopback `[소스]` |
| I3 | `mr4_none` | 라운드, 거절, 감시 줄이 없다 | ≥9/10 | 장애 없음 |
| I4 | `mr3_none` | 랭크 3개: 투명, 게이트 QP 12개 | 5/5 | 대조 |
| I5 | `mr2_none` | 새 드라이버를 랭크 2개로: 투명, 게이트 QP 2개 | 5/5 | 대조 |
| I6 | `mr4_none_peer` | 상대별 flush도 장애 없이 투명 | 5/5 | 대조 |
| A1 | `mr4_f1_01` | 간선 0>1의 로컬 QP 오류를 rank 0과 rank 1의 쌍 범위 라운드 하나(QP 1개)로 복구하고, 다른 랭크는 끼지 않는다 | ≥9/10 | 범위 결정 `[소스]` |
| A2 | `mr4_f1_01` | 간선 12개 모두 투명 | ≥9/10 | 랭크 2개 로컬 QP 오류는 늘 투명 `[측정]` |
| A3 | `mr4_f1_01` | 라운드를 거친 QP는 문맥 0의 그 쌍뿐(epoch 2)이고, 훅이 건드린 rank 0의 다른 두 QP는 끝까지 ERR | ≥9/10 | 훅과 flush `[소스]` |
| B1 | `mr4_f1_02` | 노드 안 간선 0>2(NIC loopback)의 로컬 QP 오류도 쌍 범위 라운드로 투명하게 복구 | ≥9/10 | 같음 |
| B2 | `mr4_f1_02` | 라운드를 거친 QP는 문맥 1의 그 쌍뿐, 나머지 두 QP는 ERR | ≥9/10 | 같음 |
| C1 | `mr4_f3_01` | rank 1의 문맥 0 QP를 ERR로 옮기면 rank 0이 재시도 초과를 보고, 쌍 범위 라운드로 투명하게 복구 | ≥9/10 | 랭크 2개 상대 QP 오류는 늘 투명 `[측정]` |
| C2 | `mr4_f3_01` | 간선 0>1이 약 3.6 s 묶인 동안 rank 0의 다른 두 간선이 각각 100번 이상 진행 | ≥9/10 | 분류 기록까지 3 523.5–3 763.0 ms(n=10), 3 548.9–3 770.1 ms(n=10) `[측정]`, 15 ms 간격 |
| C3 | `mr4_f3_01` | 라운드를 거친 QP는 문맥 0의 그 쌍뿐, rank 1의 나머지 두 QP는 ERR | ≥9/10 | 훅 `[소스]` |
| C4 | `mr4_f3_01` | 첫 분류 기록이 훅 3.0–4.5 s 뒤 | ≥9/10 | C2와 같은 측정 |
| D1 | `mr4_f1_01_23` | 겹치지 않는 두 쌍(0>1, 2>3)의 동시 장애가 독립된 쌍 범위 라운드 둘로 투명하게 복구 | ≥9/10 | helper는 랭크마다 하나 `[소스]` |
| D2 | `mr4_f1_01_23` | 라운드를 거친 QP는 그 두 쌍뿐 | ≥9/10 | 같음 |
| E1 | `mr4_f1_10_30` | 두 시작 쪽(1>0, 3>0)이 같은 응답 쪽 rank 0으로 와도 둘 다 투명하게 복구 | ≥9/10 | REQ는 소켓에서 기다리고 ACK 한도는 약 24.5 s `[소스]` |
| E2 | `mr4_f1_10_30` | rank 0의 helper가 두 응답 라운드를 겹치지 않게 차례로 처리 | 10/10 | helper 스레드 하나 `[소스]` |
| E3 | `mr4_f1_10_30` | 라운드를 거친 QP는 그 두 쌍뿐 | ≥9/10 | 같음 |
| F1 | `mr4_f1all0` | rank 0의 모든 문맥 장애를 상대마다 전체 범위(QP 12개, 사유 `qp_state`) 라운드 하나씩, 셋으로 복구 | ≥9/10 | 범위 결정 `[소스]` |
| F2 | `mr4_f1all0` | 간선 12개 모두 투명(다른 랭크가 rank 0의 ERR QP로 보내던 것도 라운드에서 다시 보냄) | ≥9/10 | 라운드 하나가 약 1.0 s, 셋째 라운드가 장애 2.0 s 뒤 시작(파일럿) `[측정]`. 마지막 응답 쪽 QP가 장애 약 2.4 s 뒤 초기화되어 재시도 초과(3.5–3.8 s) 전 `[추론]` |
| F3 | `mr4_f1all0` | 세 라운드가 겹치지 않고, rank 0과 각 상대 사이 QP 72칸 모두 epoch 2, 끝에 모두 RTS | ≥9/10 | 같음 |
| R1 | 복구 셀 여섯 | `hd`의 상한이 조용하다: 라운드 상한, 펌웨어 단계와 복사의 상한 초과, 소켓으로 취소된 라운드, 죽음 판정이 없다 | 셀마다 ≥9/10 | 한 랭크의 라운드는 많아야 3번(상한 8) `[소스]`. 파일럿 라운드의 단계는 가장 긴 것이 376 ms(문맥 12개의 다시 보내기)라, 그 안의 명령 하나나 복사 하나는 상한 3 000, 2 000 ms보다 훨씬 짧다 `[측정, 추론]` |
| K1 | `mr4_kill3` | rank 3 kill 뒤 살아남은 세 랭크가 소켓(BYE 없는 FIN)으로 rank 3의 죽음을 바로 판정하고 rank 3만 거절("peer judged dead") | ≥9/10 | `hd`의 죽음 판정과 거절 `[소스]` |
| K2 | `mr4_kill3` | 그 거절이 kill 0–2 s 뒤(재시도 초과를 기다리지 않음) | ≥9/10 | kill에서 살아남은 쪽 소켓의 FIN까지 0.1–0.3 ms(랭크 2개, n=20) `[측정]` |
| K3 | `mr4_kill3` | 문맥 전체 flush에서는 거절 뒤 살아남은 랭크 사이의 간선 6개도 모두 오류로 멈춘다(보내는 쪽 6개 실패) | ≥9/10 | 1절 flush의 범위와 거절의 번짐 `[소스]` |
| K4 | `mr4_kill3_peer` | 상대별 flush에서도 rank 3만 거절 | ≥9/10 | K1과 같음 |
| K5 | `mr4_kill3_peer` | 상대별 flush: 살아남은 랭크 사이의 받는 쪽 6개는 모두 오류로 끝나고, 보내는 쪽 6개는 끝까지 성공 | ≥9/10 | `hd`의 사용자 abort 단어와 폴링 10 000번마다의 확인 `[소스, 추론]` |
| K6 | 두 kill 셀 | 살아남은 세 랭크의 앱이 모두 비동기 오류를 봄 | 셀마다 ≥9/10 | 거절이 통신기 전체 결과를 바꿈 `[소스]` |
| K7 | 두 kill 셀 | 거절은 rank 3으로 가는 QP 36칸(랭크 3 × 문맥 12)만 닫음(epoch 2, ERR) | 셀마다 ≥9/10 | `gdakiTsDecline` `[소스]` |
| Y1 | `mr4_cyc_stall` | 순환하는 세 시작 쪽(0에서 1, 1에서 2, 2에서 0)이 서로를 기다려 "handshake timeout" 거절이 하나 이상 생기고 투명하지 않음 | ≥4/5 | 1절 순환 대기 `[소스]` |
| Y2 | `mr4_cyc_stall` | 첫 "handshake timeout"이 그 랭크의 라운드 시작 24.3–24.8 s 뒤 | ≥4/5 | ACK 한도 24 500 ms `[소스]` |
| Y3 | `mr4_cyc_stall` | 그 한도 전에는 어떤 복구도 끝나지 않고(첫 복구가 첫 라운드 줄 24 s 이상 뒤, 열 `rec_first_after_round_ms`) 감시 줄이 없음 | ≥4/5 | 한도가 라운드 감시(25 s)보다 0.5 s 짧음 `[소스]` |
| Z1 | `mr4_chain_stall` | 순환 없는 사슬(0에서 1, 1에서 2)은 첫 라운드 줄 5 s 안에 두 라운드의 양쪽이 모두 다시 돌고(열 `rec_last_after_round_ms`) 투명 | ≥4/5 | rank 1의 쌍 범위 라운드 약 0.4 s, 거부 뒤 rank 0의 전체 범위 라운드 약 1.7 s, 합 약 2.1 s(파일럿 단계 시간) `[측정, 추론]` |
| Z2 | `mr4_chain_stall` | rank 1이 rank 0의 쌍 범위 요청을 거부하고(훅이 ERR로 둔 문맥 4의 rank 0 쪽 QP) rank 0이 문맥 12개 전체 범위로 다시 연다. 끝에 RTS가 아닌 QP는 rank 0 문맥 0의 rank 2, 3 쪽과 rank 1 문맥 4의 rank 3 쪽뿐 | ≥4/5 | 응답 쪽 범위 확인과 다시 열기 `[소스]`, 파일럿 순환 시행에서 같은 거부 둘 `[측정]` |
| T1 | `mr3_f1_01` | 랭크 3개에서 간선 0>1의 로컬 QP 오류를 쌍 범위 라운드로 투명하게 복구, rank 0의 다른 QP 하나는 ERR | ≥4/5 | 대조 |
| L1 | `mr2_lat` | 랭크 2개 4 KiB p50이 10.0–12.0 µs | ≥4/5 | `gin_ts2` 4 KiB p50 10.56–10.59 µs(실행 5회) `[측정]` |
| L2 | `mr4_lat_solo`, `mr2_lat` | 같은 두 간선을 랭크 4개 통신기에서 돌려도 p50 중앙값 차이 1.0 µs 이하 | 중앙값 비교 | flush가 QP 4개를 돎 `[소스]` |
| L3 | `mr4_lat`, `mr4_lat_solo` | 탐색: 모든 간선이 돌 때 노드 사이 간선 p50 중앙값이 혼자일 때의 2배 이하 | 중앙값 비교 | 시분할 길이 모름 `[미확인]` |
| L4 | `mr4_lat` | 탐색: 실행 5회 중 4회 이상 어떤 간선에 200 µs 이상인 반복이 있다(시분할) | ≥4/5 | 같음 |
| L5 | `mr2_lat` | 프로세스가 GPU마다 하나면 5회 중 4회 이상 200 µs 넘는 반복이 없다 | ≥4/5 | `gin_ts2` 4 KiB 최대 16.3–243.7 µs, 10회 중 1회만 200 µs 넘음 `[측정]` |

측정 근거의 출처: C2, C4는 `../results/20260925_ts1/trials.csv`(`f3_b`)와 `../results/20261001_ts2/trials_reg.csv`(`f3_b`)에서 2026-10-09에
다시 셌다 `[측정]`(시행별 표에서 셈, 원시 로그에서 다시 세지 않음). K2의 kill에서 FIN까지는 gin-s2-close, gin-reconnect, gin-pair-check,
gin-oneway의 `results/*/trials_scored.csv`의 `f4_b` 행 20개(`sock_close_ms_r0 − fault_mono_r0`, 모두 `cause=FIN`)에서 셌다(같음). L1, L5는
`../oneway/results/20261008/trials_scored.csv`의 `lat_*_4k` 행이다(같음).

### 3.4 파일럿 뒤 한 번 바꿀 수 있는 값

파일럿은 소스만으로 정할 수 없는 시각과 설정을 확인한다. 아래 값만, 파일럿 결과를 근거로 태그 전에 한 번 바꿀 수 있다. 그 밖의 예측, 판정식,
셀, 반복 수, 제외 기준은 소스 분석이 틀렸다는 증거가 파일럿에 있을 때만 고치고, 그 근거를 12절에 적는다.

| 값 | 확정 | 바꾸는 규칙 | 파일럿 P0(`ow`) `[측정]` |
|---|---|---|---|
| `F_MS`(훅 지연, 문맥 생성부터) | 6 000 ms(그대로) | 파일럿에서 훅 발사가 커널 시작 2 s 뒤보다 이르면 늘린다 | 훅 발사가 마지막 랭크의 커널 시작 5 959–5 975 ms 뒤(훅 셀 6개, 발사 9번). 트래픽 15 s의 안 |
| `KILL_MS`(kill 지연, 그 랭크 시작부터) | 9 000 ms(그대로) | kill이 모든 랭크의 커널 시작 2 s 뒤이고 트래픽 끝 6 s 전이 되도록 맞춘다 | kill이 커널 시작 7 983–8 026 ms 뒤(2회), 트래픽 끝 약 7.0 s 전. 프로세스 시작에서 커널 시작까지는 랭크 4개 919–1 278 ms(랭크 실행 52번) |
| `STALL`(순환과 사슬 셀의 helper 멈춤) | 300 ms(그대로) | 파일럿 순환 시행의 `cyc_spread_ms`가 200 ms를 넘으면 그 2배 이상으로 늘린다 | `cyc_spread_ms` 17.4 ms(1회). 세 라운드 모두 ACK를 기다렸다 |
| 순서 제외의 퍼짐 한도 | 250 ms(그대로) | `STALL`을 늘리면 `STALL` − 50 ms로 맞춘다 | `STALL`을 그대로 둠 |
| 본 실행 빌드 키 | `hd` | 다른 빌드로 돌리면 그 키로 바꾼다(`score.py`의 `MAIN`, 예측 파일의 셀 키) | 파일럿은 `ow` |
| 빌드 표시 줄 | `ow`: `helper liveness oneway=1`. `hd`: 그 줄과 `harden=1`(3.5에서 정함) | 파일럿과 다르게 찍히면 고친다 | 초기화가 거부된 음성 대조를 뺀 16회 모두 `n_ow == n`. `hd` 줄은 `hd`로 돌린 적이 없어 `[미확인]` |

파일럿에서 랭크 4개의 통신기가 만들어지지 않거나, 장애 없는 시행이 커널 정지나 감시로 끝나면 이 실험은 `BLOCKED`가 된다. 12절에 원인(로그 줄)과
풀리는 조건(예: GPU 컴퓨트 모드 변경은 사용자 결정)을 적고, 본 실행은 하지 않는다.

### 3.5 본 실행 빌드 `hd`를 위한 다시 읽기

처음 예측은 `ow` 트리의 소스에서 이끌었다. 2026-10-09에 `hd` 트리(gin-harden의 `hd_layer.diff`, gin-harden `EXPERIMENT.md` 9절)를 읽고 예측을
다시 이끌었다. 결과는 1절 끝의 "본 실행 빌드 `hd`에서 달라지는 점"이고, 예측마다 이렇다.

| 예측 | `hd`에서 | 무엇을 읽었나 |
|---|---|---|
| K1, K4 | 바꿈: 사유가 재시도 초과가 아니라 "peer judged dead: the peer's socket shows <원인>" | `gdakiTsSocketLost`, `gdakiTsMain` |
| K2 | 바꿈: kill 3.0–5.0 s 뒤가 아니라 0–2 s 뒤 | 같음, kill에서 FIN까지의 측정 |
| K3 | 판정식 그대로, 근거에 사용자 abort 단어를 더함 | `gdakiTsDecline`, `flushImplModeCore` |
| K5 | 바꿈: 간선 6개가 모두 끝난다가 아니라, 받는 쪽 6개는 오류, 보내는 쪽 6개는 성공 | `ncclGinTsUserAbortRaise`, `testAbort`, `waitRollingLessEq`, `tsPoll` |
| K6, K7 | 그대로(근거만 `hd` 줄로) | `gdakiTsDecline` |
| Y1–Y3 | 그대로(ACK 대기 구조와 한도가 같음) | `gdakiTsInitiate`, `gdakiTsRoundLeftMs` |
| A1–F3, T1, Z1 | 그대로. 범위 결정, 범위 확인, 정지는 펌웨어 단계 감시만 더해짐. 다시 보내기는 모든 QP를 먼저 검사함(결과는 같음) | 함수 단위 비교 |
| R1 | 새로 더함: 라운드 상한, 단계와 복사 상한, 소켓 취소, 죽음 판정이 복구 셀에서 나오지 않음 | `gdakiTsEscalated`, `gdakiRecFwGuard`, `gdakiRecCopyWait` |
| I1–I6, L1–L5 | 그대로. 사용자 devComm 줄은 끝에 `word=own`이 붙었으나 열은 앞부분으로 센다. 장치의 빠른 경로는 바뀌지 않음 | `dev_runtime.cc`, 장치 헤더 diff |

- 장치 헤더가 바뀌었다(`gin_gdaki.h`, `gin_gdaki_device_host_common.h`, `gin__funcs.h`, `utility.h`, `nccl.h`). 그래서 드라이버를 `hd` 트리로
  따로 빌드했다(5절). 소스 `gin_mr.cu`는 파일럿 드라이버와 같다.
- `hd`의 시작 줄은 `ow`의 `helper liveness oneway=1`을 그대로 찍고 `GIN/TS: harden=1 rank=<r> ...`을 더한다. 설정 확인(8절)에 둘 다 쓴다.
- 파일럿은 `ow`로 돈다. 그래서 파일럿의 kill 셀은 `ow`의 동작(재시도 초과 뒤 거절, 상대별 flush에서 간선이 끝남)을 보일 것이고, 위 `hd`
  예측의 근거가 아니다. 파일럿에서 볼 것은 3.4의 값과 실행 가능성이다.

### 3.6 파일럿 P0과 예측 확정

파일럿은 2026-10-09 03:15:51–03:20:56에 빌드 `ow`로 17회 돌았다(셀 14개, `mr4_none`만 2회). 원시 파일은 `results/20261009_pilot/`이고
커밋하지 않는다. 열은 `rows_mr.py`로 다시 만들었다(`trials_p0.csv`). 채점하지 않았다. 아래 수는 모두 이 폴더에서 다시 셌다 `[측정]`.

**실행 확인.**
- hold 전후 mlx5 새 커널 줄 0. 명령 오류 줄(rain 2)과 rain 펌웨어 명령 실패 합(31)은 hold 전과 같다. 남은 `gin_mr` 0, `LEFT_STREAK` 0.
- 훅: 9번 모두 계획한 랭크와 문맥에서, 트래픽 안에서 발사됐다. kill: 기록한 PID 하나(sunny의 rank 3)에만, 트래픽 안에서 갔다.
- 같은 GPU 스위치를 끈 음성 대조는 네 랭크 모두 "Multiple Ranks are using the same GPU"로 0.9 s 안에 초기화를 거부했다.
- 설정 줄: 음성 대조를 뺀 16회 모두 투명 복구, abort 플래그, pair reset, pair check, 단방향 liveness 줄이 랭크 수만큼 있고, 게이트 QP가
  랭크 4개 36, 3개 12, 2개 2다.
- 시행 시간(실행기의 wall): 장애 없는 랭크 4개 18.0 s, 상대 QP 오류 21.5 s, 모든 문맥 장애 21.0 s, kill 20.1–23.6 s, 순환 33.6 s, 지연
  실행 1.8–2.5 s. hold 하나는 시행 시간 합에 약 35 s가 더 들었다(시행 17회).

**`ow`에서 이끈 예측과 비교.** 시행 1회씩이고 판정이 아니다.

| 무엇을 예측했나 | 파일럿에서 본 것 | id |
|---|---|---|
| 랭크 4개 초기화와 게이트 QP 36개, 장애 없이 투명. 랭크 3개, 2개, 상대별 flush도 투명 | 그대로(랭크 4개 2회, 나머지 1회씩) | I1–I6 |
| 간선 0>1, 0>2(loopback)의 로컬 QP 오류를 쌍 범위 라운드 하나로 투명하게 복구, 그 쌍만 epoch 2, 훅의 다른 QP 둘은 ERR | 그대로. 라운드는 시작 쪽 87–92 ms에 끝남 | A1–A3, B1, B2 |
| 상대 QP 오류를 쌍 범위 라운드로 투명하게 복구, 묶인 동안 다른 두 간선이 100번 이상, 첫 분류 기록이 훅 3.0–4.5 s 뒤 | 그대로. 묶인 반복 3.78 s 동안 247번, 246번. 첫 분류 기록 3 694 ms 뒤 | C1–C4 |
| 두 시작 쪽이 rank 0으로: 둘 다 쌍 범위로 복구, rank 0의 응답 라운드 겹침 없음 | 그대로. 둘째 시작 쪽은 첫째를 기다려 205 ms에 끝남 | E1–E3 |
| rank 0의 모든 문맥 장애: 상대마다 전체 범위 라운드 하나, 겹침 없음, 72칸 epoch 2, 끝에 모두 RTS, 투명 | 그대로. 라운드 하나가 1.01–1.03 s(초안 근거는 셋 합 약 0.1 s) | F1–F3 |
| kill(`ow` 동작): rank 3만 거절, 재시도 초과 뒤. 문맥 전체 flush는 살아남은 간선 6개가 모두 실패, 상대별 flush는 모두 성공. 세 랭크 비동기 오류. rank 3 쪽 36칸만 닫힘 | `ow` 예측 그대로. 거절은 kill 3 632–3 810 ms 뒤(랭크 2개 근거 3 555.9–3 874.2 ms 안) | K3, K6, K7과 `ow`의 K1, K2, K4, K5 |
| 순환: "handshake timeout" 하나 이상, 라운드 시작 24.3–24.8 s 뒤, 감시 줄 없음, 투명 아님 | 그대로. 24 506 ms. 첫 복구는 첫 라운드 줄 25 118 ms 뒤 | Y1–Y3 |
| 지연: 랭크 2개 p50 10.0–12.0 µs, 랭크 4개의 같은 두 간선과 차이 1.0 µs 이하, 모든 간선이면 길게 걸린 반복 | p50 11.07, 11.04 µs. 모든 간선이면 노드 사이 p50 중앙값 12.05 µs, 최대 2 335 µs(랭크 2개 20.48 µs) | L1–L5 |

`hd`에만 기댄 예측(K1, K2, K5의 `hd` 판정식, R1)은 `ow` 파일럿이 근거가 될 수 없다. 사슬(`mr4_chain_stall`), 겹치지 않는 두 쌍, 랭크 3개
장애 셀은 파일럿에 없었다.

**파일럿이 보인 것과 바꾼 것.**
1. **열의 잘못(Y3).** `init_total_ms_min`은 응답 쪽이 거부해 전체 범위로 다시 연 라운드를 다시 연 때부터 센다. 순환 시행에서 rank 2의
   복구는 첫 라운드 줄 25.1 s 뒤였지만 그 줄의 `total_us`는 549 ms였다. 이 열로는 "한도 전에는 어떤 복구도 끝나지 않는다"를 잴 수 없다.
   `rec_first_after_round_ms`를 더하고 판정식을 그 열 ≥ 24 000으로 바꿨다. 예측 문장과 한도는 그대로다.
2. **소스 분석의 빈틈(Z1, Z2).** 훅이 ERR로 둔 그 문맥의 다른 QP가 요청하는 상대로 가는 QP이면 응답 쪽이 쌍 범위 요청을 거부한다(1절
   장애 훅). 순환 시행에서 rank 1이 rank 0의, rank 0이 rank 2의 요청을 `not_rts=1`로 거부했고, 둘 다 문맥 12개 전체 범위로 다시 열었다.
   사슬 셀에서도 rank 1의 문맥 4 QP 중 rank 0 쪽이 ERR이라 같은 일이 생긴다 `[소스, 추론]`.
   - Z2를 더했다. 그 거부와 다시 열기, 끝에 남는 ERR QP 셋이다.
   - Z1을 다시 이끌었다. 초안은 "2 s 안에 둘 다 복구"를 `init_total_ms_max` ≤ 2 000으로 쟀다. 그 열은 다시 연 라운드만 세고, 그 값은
     거부를 빼고 이끈 것이었다. 파일럿 단계 시간으로 다시 이끌면 마지막 재개는 첫 라운드 줄 약 2.1 s 뒤다. rank 1의 쌍 범위 라운드(시작 쪽
     86–92 ms, 응답 쪽 115–119 ms에 재개, 라운드 4개)에 멈춤 300 ms, 그 뒤 rank 0의 전체 범위 라운드(시작 쪽 1 012–1 025 ms, 응답 쪽
     1 387–1 399 ms에 재개, 라운드 3개)에 멈춤 300 ms를 더한 값이다 `[측정, 추론]`. 단계 시간이 GPU 사용에 따라 크게 달라서(문맥 12개
     commit이 트래픽 중 260–265 ms, 트래픽이 끝난 뒤 14–137 ms) 한도를 5 000 ms로 두었다. 순환이 기다리는 24.5 s와는 여전히 크게 다르다.
     열은 `rec_last_after_round_ms`(두 역할의 마지막 재개)다.
3. **근거 문장만 고침.**
   - F2: 라운드 하나가 약 1.0 s이고 셋째 라운드가 장애 2.0 s 뒤에 시작했다. 마지막 응답 쪽 QP의 초기화는 장애 약 2.4 s 뒤로, 재시도
     초과(3.5–3.8 s)보다 약 1 s 앞이다 `[추론]`. `hd`에서 라운드가 이보다 0.4 s 넘게 길어지면 rank 0으로 보내던 쪽이 재시도 초과를 볼 수
     있다. 위험으로 적고 예측은 그대로 둔다.
   - R1: 파일럿 라운드의 가장 긴 단계가 376 ms라, 펌웨어 명령 하나나 복사 하나는 `hd`의 상한(3 000, 2 000 ms)보다 훨씬 짧다.
4. **바꾸지 않은 것.** 3.4의 값 전부, 셀, 반복 수, 제외 기준, 나머지 예측과 판정식. 7절의 hold 추정만 파일럿 시행 시간으로 고쳤다.

## 4. 범위

**포함.**
- 새 드라이버 `gin_mr`(장애를 모르는 앱, 9절 1번)와 실행 스크립트. 라이브러리는 바꾸지 않는다.
- 본 실행 셀 18개(7절), 셀 시행 120회와 지연 실행 15회. 파일럿 전용 음성 대조 셀 하나(`mr4_nomrge`).
- 빌드 `ow`(파일럿), `hd`(본 실행).

**제외.**
- 연속 랭크 배치(rain 0, 1): LSA 팀이 2가 되어 같은 GPU의 두 프로세스가 서로의 메모리를 매핑한다. 이 실험의 질문 밖이다.
- 랭크 5개 이상, 노드마다 GPU 둘 이상, MPS.
- 관리망 끊김(helper 소켓)과 랭크 여럿의 조합, 원격 접근 오류(F2), burst 트래픽, 카운터 QP, LSA나 NVLink 경로.
- 멈춤 스위치 없는 자연 순환: 겹칠 확률이 타이밍에 달려 이번에는 재지 않는다(18절 후보).
- 라이브러리 수정(예: 순환 대기의 해소, 거절의 문맥 번짐 줄이기)은 이 실험에서 하지 않는다. 결과를 보고 사용자가 정한다.

## 5. 테스트베드와 버전

| 항목 | 값 | 확인 방법과 날짜 |
|---|---|---|
| 노드와 랭크 | 랭크 4개: rain 0, 2, sunny 1, 3. 랭크 3개: rain 0, 2, sunny 1. 랭크 2개: rain 0, sunny 1 | `run_mr.sh`(짝수 랭크가 rain) |
| GPU | rain Quadro RTX 5000(sm_75), sunny RTX A4000(sm_86), 노드마다 하나. PeerMappingOverride=1. CUDA 12.8 | 루트 `README.md`, gin-s2-close 5절. 컴퓨트 모드는 두 노드 모두 `Default` `[측정]` 2026-10-09(파일럿 hold 전후 스냅숏) |
| NIC | ConnectX-6, fw 20.43.4100. rain `mlx5_1`, sunny `mlx5_0`. 한 노드의 두 랭크가 같은 NIC를 쓴다 | `[측정]` 2026-10-06(`../../completion_contract/EXPERIMENT.md` 5절) |
| 관리망 | `NCCL_SOCKET_IFNAME=eno1` | `run_mr.sh` |
| 파일럿 빌드 `ow` | libnccl `b4af65c54b14f192803c88adcd2bf759`, 두 노드 같음 | `[측정]` 2026-10-08(`../oneway/deploy_check.txt`) |
| `ow` 장치 헤더 | 설치된 `include/` 트리 요약값(파일별 md5 목록의 md5) `552c7b2c`. 투명 복구 2단계 최종 트리(`agent_ts2/build/include`)와 파일 단위로 같다 | `[측정]` 2026-10-09(`build_mr.sh`, `diff -r`) |
| 본 실행 빌드 `hd` | libnccl `e209032310a2cefd5d71e86533674bd6`(세션 스크래치 `agent_ts2hd/out/hd`, 빌드 트리와 같음). 두 노드의 `$HOME/gi-bundle/gin_ts2/hd/`에 배포됨(gin-harden) | `[측정]` 2026-10-09 rain의 md5. 두 노드 md5와 `ldd`는 gin-harden의 배포 확인(`../harden/deploy_check.txt`, gin-harden 브랜치)에서 읽었다 |
| `hd` 장치 헤더 | 요약값 `2b1b6286`. `ow`와 다른 파일: `gin_gdaki.h`, `gin_gdaki_device_host_common.h`, `gin__funcs.h`, `utility.h`, `nccl.h` | `[측정]` 2026-10-09(`build_mr.sh`, `diff -rq`) |
| 드라이버 `gin_mr`(`hd` 트리로 빌드) | md5 `670509805832745caa3c2c54badb84c5`, 소스 `gin_mr.cu` md5 `fd90b11f`(파일럿 드라이버와 같은 소스). 레지스터 202와 128, 스택 736 B. `LD_LIBRARY_PATH`로 `hd` 번들의 libnccl을 찾는다. 본 세션이 2026-10-09 02:30:47에 `mr/hd/`에 배포했다(종료 코드 0). 두 노드의 md5가 소스와 같고, 두 노드 모두 `ldd`가 `hd` 번들의 libnccl(md5 `e2090323`)을 찾고, 기존 번들 40파일이 그대로다. 아직 실행하지 않았다 | `[측정]` 2026-10-09, 세션 스크래치 `agent_mr/out/hd/build_info.txt`, [deploy_check_hd.txt](deploy_check_hd.txt) |
| 드라이버 `gin_mr`(`ow` 트리로 빌드) | md5 `c0206b603e74073ee7c176ed6f8635fd`, 소스 `gin_mr.cu` md5 `fd90b11f`. sm_75와 sm_86, 커널 레지스터 202와 128, 스레드당 스택 736 B. 본 세션이 `mr/ow/`에 배포했고(`deploy_check_ow.txt`: 두 노드 md5가 소스와 같고 기존 번들 32파일 그대로) 파일럿 P0이 이것으로 돌았다 | `[측정]` 2026-10-09(`build_mr.sh`, `cuobjdump -res-usage`), 세션 스크래치 `agent_mr/out/ow/build_info.txt` |

## 6. 변수

- **독립변수.**
  - 랭크 수(2, 3, 4)와 간선 집합(모두, 또는 0>1과 1>0).
  - 장애: 랭크, 문맥(곧 간선), 종류(로컬 QP 오류, 상대 QP 오류, 모든 문맥, 프로세스 kill).
  - 앱의 flush 방식(문맥 전체, 상대별), helper 멈춤 시험 스위치(순환, 사슬 셀).
  - 트래픽: 간선마다 4 KiB × 1 000, 15 ms 간격, 또는 지연 측정(4 KiB 3 000번, 간격 없음, 칸 재사용).
  - 빌드(`ow` 파일럿, `hd` 본 실행).
- **종속변수.** 3.1의 열: 초기화, 간선마다 전달과 결과, 라운드와 범위, 복구와 거절, 거절 사유와 시각, teardown의 epoch와 QP 상태,
  비동기 오류, 묶인 반복 안의 다른 간선 진행, 지연.
- **통제변수.**
  - IB 타임아웃 14, GPU doorbell, `NCCL_GIN_TYPE=3`, 투명 복구와 분류기와 복구 켬, 투명 복구 스위치 기본값(handshake 3 000 ms, hold
    30 000 ms, 라운드 25 000 ms, 재연결 1, pair reset 1, pair check 1).
  - `GIN_TS_RX_WAIT_S=10`(받는 쪽 반복마다 한도), `ABORT_WD_S=20`, `WATCHDOG_S=60`. kill, 순환, 사슬 셀은 앱이 비동기 오류 뒤 커널을
    40 s까지 기다린다(`GIN_MR_GRACE_S=40`).
  - 랭크는 번갈아 둔다. 시행마다 프로세스를 새로 띄운다.

## 7. 실험 셀, 반복 수, 대조군

반복 수: 새 셀 10, 대조 5. 순환과 사슬 셀은 시행 하나가 길어서(순환 33.6 s, 파일럿) 5다. 지연 셀의 반복은 실행 수다(실행마다 3 000번). 훅 시각(`F_MS`)은
각 랭크의 GDAKI 문맥 생성부터, kill 시각(`KILL_MS`)은 실행기가 그 랭크를 띄운 때부터 잰다. 문맥 번호는 간선 a>b에 a × (N − 1) +
(b < a ? b : b − 1)이다(랭크 4개: 0>1은 0, 0>2는 1, 1>0은 3, 1>2는 4, 2>0은 6, 2>3은 8, 3>0은 9).

| 셀 | 조건 | 반복 수 | 종류 |
|---|---|--:|---|
| `mr4_none` | 랭크 4개, 간선 12개, 문맥 전체 flush, 장애 없음 | 10 | 새 셀 |
| `mr4_none_peer` | 같음, 상대별 flush | 5 | 대조 |
| `mr3_none` | 랭크 3개, 간선 6개 | 5 | 대조 |
| `mr2_none` | 랭크 2개(프로세스 GPU마다 하나, 같은 GPU 스위치 끔), 간선 2개 | 5 | 대조 |
| `mr4_f1_01` | rank 0 로컬 QP 오류, 문맥 0(간선 0>1, 노드 사이) | 10 | 새 셀 |
| `mr4_f1_02` | rank 0 로컬 QP 오류, 문맥 1(간선 0>2, rain 안 loopback) | 10 | 새 셀 |
| `mr4_f3_01` | rank 1 훅, 문맥 0(rank 0이 재시도 초과를 봄) | 10 | 새 셀 |
| `mr4_f1_01_23` | rank 0 문맥 0과 rank 2 문맥 8에 같은 지연으로 훅 | 10 | 새 셀 |
| `mr4_f1_10_30` | rank 1 문맥 3과 rank 3 문맥 9에 같은 지연으로 훅(응답 쪽은 둘 다 rank 0) | 10 | 새 셀 |
| `mr4_f1all0` | rank 0 훅, 문맥 지정 없음(모든 문맥, QP 36개) | 10 | 새 셀 |
| `mr4_kill3` | rank 3(sunny, rank 1과 GPU 공유) SIGKILL, 문맥 전체 flush | 10 | 새 셀 |
| `mr4_kill3_peer` | 같음, 상대별 flush | 10 | 새 셀 |
| `mr4_cyc_stall` | rank 0 문맥 0, rank 1 문맥 4, rank 2 문맥 6에 같은 지연으로 훅. 세 랭크에 `NCCL_GIN_TS_TEST_STALL=300@quiesce` | 5 | 새 셀 |
| `mr4_chain_stall` | rank 0 문맥 0, rank 1 문맥 4만, 같은 멈춤 스위치 | 5 | 대조 |
| `mr3_f1_01` | 랭크 3개, rank 0 로컬 QP 오류, 문맥 0 | 5 | 대조 |
| `mr2_lat` | 랭크 2개 지연, 간선 2개 | 실행 5 | 대조 |
| `mr4_lat_solo` | 랭크 4개 통신기, 간선 0>1과 1>0만(rank 2, 3은 커널 없음) | 실행 5 | 대조 |
| `mr4_lat` | 랭크 4개, 간선 12개 모두 | 실행 5 | 탐색 |
| `mr4_nomrge` | 랭크 4개, 같은 GPU 스위치 끔(초기화가 거부되어야 함). 파일럿에서만 | 파일럿 1 | 음성 대조 |

**합계(본 실행).** 셀 시행 120회(새 셀 95, 대조 25)와 지연 실행 15회. 파일럿은 따로 약 17회다(9절).

**hold 계획**(본 실행, 각 hold ≤ 15분, `timeout -s KILL 880`). 추정은 파일럿 P0(`ow`)의 셀별 시행 시간에 시행마다 2 s와 스냅숏 10 s를
더해 분 단위로 올린 값이다 `[측정, 추론]`. 파일럿에 없던 셀은 비슷한 셀의 시간을 썼다(`mr3_f1_01`, `mr4_f1_01_23`, `mr4_chain_stall`은 18 s). `hd`의
kill 셀은 거절이 바로 와서 더 짧을 수 있다 `[추론]`. 시행 하나가 멈추면 랭크마다 `WATCHDOG_S` + 20 = 80 s에서 끝나므로, 그런 시행이 여럿이면
hold가 880 s에서 잘릴 수 있다(8절).

| hold | 내용 | 추정 |
|---|---|---|
| H1 | `mr4_none` 10과 `mr4_none_peer` 5(2:1로 섞어서), `mr2_none` 5 | 7분 |
| H2 | 지연 셀 셋 × 5(섞어서), `mr3_none` 5와 `mr3_f1_01` 5(섞어서) | 5분 |
| H3 | `mr4_f1_01` 10과 `mr4_f1_02` 10(1:1) | 7분 |
| H4 | `mr4_f3_01` 10과 `mr4_f1_01_23` 10(1:1) | 8분 |
| H5 | `mr4_f1_10_30` 10과 `mr4_f1all0` 10(1:1) | 8분 |
| H6 | `mr4_kill3` 10과 `mr4_kill3_peer` 5(2:1) | 7분 |
| H7 | `mr4_kill3_peer` 5, `mr4_chain_stall` 5와 `mr4_cyc_stall` 5(1:1) | 7분 |

hold마다 잠금과 유휴 확인이 약 1분 더 든다(잠금이 비어 있을 때). 본 실행은 잠금 대기를 빼고 모두 약 55분이다 `[추론]`.

## 8. 제외 기준과 중단 기준

**제외 기준.** 제외한 시행은 셀별로 따로 세어 보고한다.
- 파일럿(`results/<날짜>_pilot/`)은 채점하지 않는다.
- 드라이버 랑데부 포트 충돌(`bind_fail == 1`)은 제외하고 다음 번호로 계획한 수를 채운다.
- 장애 미적용: 훅 셀에서 `fires`가 셀의 기대(예: `mr4_f1_01`은 `0:0`, `mr4_f1all0`은 `0:all`, `mr4_cyc_stall`은 `0:0;1:4;2:6`)와
  다르거나 `fire_in_traffic != 1`. 제외하고 채운다.
- kill 미적용: kill 셀에서 `killed != 1`이거나 `kill_in_traffic != 1`. 제외하고 채운다.
- 순서 미적용: 순환과 사슬 셀에서 `cyc_spread_ms`가 비었거나 250 ms를 넘음(멈춘 라운드들이 겹치지 않음). 제외하고 채운다.
- 초기화 실패(`init_fail == 1`)는 제외하지 않는다. I1이 판정한다.
- 채우려고 다시 돈 시행이 셀마다 계획의 50%를 넘으면 그 셀은 멈추고 "자료 부족"으로 둔다.

**설정 확인.** 모든 랭크의 devComm이 만들어진 시행에서, 하나라도 어긋나면 제외가 아니라 그 hold를 멈추고 원인을 12절에 적는다.
- `n_ts_on`, `n_ua`, `n_pr`, `n_pc`가 n이고, `gq_min == gq_max == (n − 1) × n × (n − 1)`.
- `ow` 시행은 `n_ow == n`. `hd` 시행은 `n_ow == n`이고 `n_hd == n`이다(3.5).
- 멈춤 스위치 줄(`knob_stall`)이 순환 셀은 `0:300;1:300;2:300`, 사슬 셀은 `0:300;1:300`, 나머지는 빈칸.
- 훅이 없는 셀에 훅 발사가 없음. flush 방식이 셀과 같음. `mrge_err == 0`.

**중단 기준.**
- **잠금.** 모든 클러스터 명령은 `harness/gpu-initiated/common/cluster_run.sh -w 10800` 안에서 돈다(`chain.sh`). 10 800 s 안에 잠금이나
  유휴 링크를 얻지 못하면(종료 코드 75) 그 hold를 미룬다. `prio-` 작업에는 양보한다. hold 하나는 15분 이하이고 `timeout -s KILL 880`으로
  묶는다.
- **파일럿.** P0에서 랭크 4개 장애 없는 시행 2회 모두 어느 랭크든 `ok`로 끝나지 않으면 P0의 나머지를 건너뛰고(`PILOT_STOP`), 이후 hold도
  돌지 않는다(3.4).
- **하지 않는 것.** 실제 link down이나 flap, 재부팅, 드라이버 재적재, 커널 모듈 적재, RoCE 주소 변경, iptables 같은 방화벽 변경, 시스템
  TCP 설정 변경, GPU 컴퓨트 모드 변경. 이 실험은 관리망 끊김을 쓰지 않는다.
- **프로세스.** 이름으로는 아무것도 끄지 않는다(`pkill`, `killall` 없음). 같은 Unix 계정으로 다른 사용자의 실험과 VS Code가 돈다.
  다른 사용자의 작업(gds-kv, NVMe-oF, gdsio, mooncake, `prio-` 작업)은 건드리지 않는다.
  - 랭크마다 `timeout -s KILL (WATCHDOG_S + 20)`이 제 자식 `gin_mr`만 끝낸다. 실행기는 끄지 않는다.
  - kill 셀의 kill은 하나뿐이다. 실행기가 그 랭크를 띄울 때 기록한 PID에서 부모 관계(`pgrep -P`)로 `gin_mr`의 PID와 그 부모 PID를 기록하고,
    kill 직전에 그 PID가 여전히 `gin_mr`이고 부모가 같은지 확인한 뒤 그 PID에만 SIGKILL을 보낸다(`run_mr.sh`).
  - 시행 뒤 `gin_mr`가 남았는지는 읽기만 해서 센다(`left`). `left > 0`이 두 시행 연속이면 `cells.sh`가 `STOP_left`를 쓰고, 그 hold의 남은
    시행과 이후 hold를 돌지 않는다.
  - hold가 제한 시간으로 잘려 `gin_mr`가 남았으면 그것은 제 `timeout`이 끝낸다. 다음 hold는 시작할 때 남은 `gin_mr`가 없어질 때까지 150 s
    까지 기다리고(`stale.txt`), 그래도 있으면 시행을 하나도 돌지 않는다(`STOP_left`).
- **mlx5 오류.** rain `mlx5_1`은 펌웨어 명령 슬롯 하나가 새어 있다. hold 앞뒤에 두 노드의 mlx5 커널 줄 전체와 rain의 펌웨어 명령 계수를
  남긴다. hold 동안 새 mlx5 명령 오류 줄(`mlx5`와 `cmd` 또는 `command`, 그리고 `failed`, `timeout`, `leak` 중 하나)이 생기거나 명령 실패
  계수(`failed`, `failed_mbox_status`)가 늘면 그 hold 뒤로 멈춘다(`STOP_mlx5`). 이 실험은 한 노드의 두 프로세스가 같은 NIC에 펌웨어 명령을
  동시에 낼 수 있다(겹치지 않는 두 쌍, 모든 문맥 장애).
- **배포.** 드라이버는 새 디렉터리 `$HOME/gi-bundle/gin_ts2/mr/<키>/`에만 둔다. 대상이 비어 있지 않으면 배포 스크립트가 멈추고, 배포 뒤 기존
  번들 파일(`mr/` 밖 전부)의 md5가 두 노드에서 그대로인지 확인한다. libnccl은 복사하지 않는다.

## 9. 실행 방법과 경로

**1. 드라이버** `gin_mr.cu`(이 폴더). 장애와 복구를 모르는 앱이다. `gin_ts2`는 바꾸지 않았다.
- 랭크 수 N(2–6), 간선마다 CTA 하나인 커널 하나, 간선마다 GIN 문맥 하나(signal 0). 보내는 쪽: 반복마다 put(칸 i) + signal 더하기 1,
  flush, 간격. 받는 쪽: signal을 기다리고 칸 i를 장치에서 검사. 끝에 호스트가 모든 칸과 마지막 signal을 다시 검사한다.
- 데이터 패턴은 간선마다 씨앗이 다르다(1 + 16a + b). 다른 간선에 잘못 도착한 칸도 틀린 칸으로 잡는다.
- flush 방식은 `GIN_MR_FLUSH=ctx`(기본, 문맥 전체)와 `peer`(상대별, 한도 60 s).
- 랭크마다 kv 파일 하나: 간선마다 결과(`tx_<ab>_*`, `rx_<ab>_*`), 지연 통계, 묶인 반복 창(`win_*`, `w_<ab>_*`), 비동기 오류, teardown.
- 부트스트랩은 rank 0을 가운데 둔 TCP 별 모양(ncclUniqueId, 시계 차이, 시작 장벽)이다.

**2. 빌드**(rain, 클러스터 동작 없음). `build_mr.sh <키> <NCCL 빌드 디렉터리>`가 nvcc로 sm_75, sm_86용을 만든다. 결과는 세션 스크래치
`agent_mr/out/<키>/gin_mr`와 `build_info.txt`(md5, libnccl md5, 헤더 요약값)다.
```
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
M=harness/gpu-initiated/gin_recovery/multirank
bash $M/build_mr.sh ow $SCR/agent_ts2ow/build      # 2026-10-09에 했음
bash $M/build_mr.sh hd $SCR/agent_ts2hd/build      # 2026-10-09에 했음
```

**3. 배포**(본 세션). `deploy_mr.sh <키> <확인 출력 파일>`. 확인 출력은 파일로만 받는다.
```
bash $M/deploy_mr.sh ow $M/deploy_check_ow.txt     # 파일럿 전, 수 초
bash $M/deploy_mr.sh hd $M/deploy_check_hd.txt     # 2026-10-09 02:30:47에 했음(mr/hd/gin_mr만 두고, libnccl은 hd 번들의 것을 씀)
```

**4. 파일럿(P0, 채점하지 않음).** `mr2_none` 1, `mr4_nomrge` 1, `mr4_none` 2. 앞의 `mr4_none`이 모든 랭크 `ok`면 `mr3_none`,
`mr4_none_peer`, `mr4_f1_01`, `mr4_f1_02`, `mr4_f3_01`, `mr4_f1all0`, `mr4_f1_10_30`, `mr4_kill3`, `mr4_kill3_peer`, `mr4_cyc_stall`,
`mr4_lat`, `mr4_lat_solo`, `mr2_lat` 각 1. 2026-10-09에 했다: 17회, hold 5분 5초, 그 앞의 잠금 대기 약 2시간 8분(3.6, 12절).
```
LIB=ow bash $M/chain.sh $PWD/$M/results/<날짜>_pilot P0
python3 $M/rows_mr.py $M/results/<날짜>_pilot/p0 --out $M/results/<날짜>_pilot/trials_p0.csv
```
파일럿에서 볼 것: `mr4_nomrge`의 모든 랭크 로그에 "Multiple Ranks are using the same GPU"가 있는지(두 랭크가 정말 한 GPU에 있음), `mr4_none`의
초기화와 투명, 스냅숏의 컴퓨트 모드, 훅과 kill 시각(3.4), 순환 시행의 `cyc_spread_ms`, `max_all`(시분할).

**5. 본 실행.** 사전 등록 태그 뒤에, 상태를 `RUNNING`으로 바꾸고 돈다.
```
LIB=hd bash $M/chain.sh $PWD/$M/results/<날짜> H1 H2 H3 H4 H5 H6 H7
LIB=hd bash $M/chain.sh $PWD/$M/results/<날짜> fill:<폴더>:<셀>:<수>:<시작번호>[,...]   # 제외된 시행 채우기
```

**6. 채점.** `python3 $M/score.py $M/results/<날짜>` → `SCORE.md`, `trials_scored.csv`. 판정식 평가는 `../s2_close/score.py`의 함수를 그대로
쓴다.

**파일.** `gin_mr.cu`, `build_mr.sh`, `deploy_mr.sh`, `run_mr.sh`(시행 하나), `cells.sh`(셀), `hold.sh`(hold와 스냅숏), `chain.sh`(hold를
`cluster_run.sh`에 하나씩), `rows_mr.py`(열), `score.py`(채점), `predictions.csv`.

**출력.** 결과 폴더 `results/<날짜>/<hold 폴더>/`. 원시 로그는 Release에 올리고 커밋하지 않는다.

## 10. 완료 조건과 QA 기준

- [ ] 모든 셀이 계획한 반복 수만큼 실행됐다. 제외와 실패를 따로 센 표가 있다.
- [ ] 예측 42줄마다 판정(맞음, 틀림, 자료 부족)과 놓친 시행 목록이 있다.
- [ ] 다른 에이전트가 `score.py`를 보지 않고 원시 로그에서 핵심 수치를 다시 셌다. 대상은 간선별 전달, 라운드와 범위, 거절 대상과 사유와
  시각, teardown epoch와 QP 상태, 묶인 반복 안의 진행, 순환의 한도 시각이다.
- [ ] 다른 에이전트가 `gin_mr.cu`, `run_mr.sh`, `rows_mr.py`를 읽고 리뷰했다.
- [ ] smoke, 파일럿, 제외 시행이 결과에 섞이지 않았다.
- [ ] 두 빌드의 드라이버 md5, 헤더 요약값, 배포 확인을 5절에 적었다.
- [ ] 원자료를 Release에 올리고 `DATA.md`에 적었다.
- [ ] hold 전후 mlx5 스냅숏에 새 명령 오류가 없었거나, 있었다면 그 줄의 내용을 12절에 적었다.

## 11. 작업 체크리스트

- [x] 소스 분석, 질문, 가설, 셀 작성 (`DRAFT`)
- [x] 드라이버 `gin_mr` 작성과 빌드(`ow` 트리), 실행 스크립트, 열 추출과 채점기 작성. 합성 시행 파일로 열 추출과 채점기만 확인(클러스터 실행 없음)
- [x] 드라이버 배포(`mr/ow`, 본 세션)
- [x] 파일럿 P0(채점 제외), 3.4 값 확정(바꾼 값 없음)
- [x] `hd` 빌드의 diff 읽기와 예측 다시 이끌기(3.5), `mr/hd` 빌드
- [x] `mr/hd` 배포(본 세션)
- [x] 파일럿 검토와 예측 확정(3.6): 열 `rec_first_after_round_ms`, `rec_last_after_round_ms` 추가, Y3, Z1 고침, Z2 추가
- [ ] 고정 절 완성, 상태 `PREREGISTERED`, 해시 기록을 커밋 하나로 만들고 그 커밋에 `prereg/gin-multirank-v1` 태그
- [ ] 본 실행 (`RUNNING`)
- [ ] 채점 (`QA`)
- [ ] 독립 재계산과 코드 리뷰
- [ ] 결과 정리, 원자료 릴리스, PR
- [ ] 결론 확정 (`COMPLETE`)

## 12. 실행 기록 (시간순)

| 시각 | 무엇을 했나 | 결과와 근거(경로, 커밋, 실행 ID) |
|---|---|---|
| 2026-10-09 | `ow` 트리의 초기화(같은 GPU, P2P, GIN 연결 종류, LSA), GDAKI 문맥 생성, 장애 훅, helper, 메일박스, flush와 거절 코드를 읽음 `[소스]` | 1절 |
| 2026-10-09 | 랭크 2개 측정값을 시행별 표에서 다시 셈: 상대 QP 오류에서 첫 분류 기록까지 3 523.5–3 763.0 ms(n=10), 3 548.9–3 770.1 ms(n=10), kill에서 거절까지 3 555.9–3 874.2 ms(n=10) `[측정]` | `../results/20260925_ts1/trials.csv`, `../results/20261001_ts2/trials_reg.csv` |
| 2026-10-09 | 드라이버 `gin_mr.cu`와 스크립트 작성. `ow` 트리로 빌드됨(md5 `c0206b60`, 경고 없음). 실행하지 않았다 | 5절, 세션 스크래치 `agent_mr/out/ow/build_info.txt` |
| 2026-10-09 | 합성 시행 파일(로그 형식은 소스의 WARN 줄 그대로)로 `rows_mr.py`와 `score.py`가 열을 만들고 판정식을 평가하는지만 확인. 클러스터 실행 없음 | 세션 스크래치 `agent_mr/test/` |
| 2026-10-09 00:5x | 본 세션이 드라이버를 `mr/ow/`에 배포했다. 두 노드 md5가 소스(`c0206b60`)와 같고 기존 번들 32파일이 그대로다. 분 단위 시각은 본 세션의 보고다(확인 파일에는 빌드 시각 00:53:01만 있다) | [deploy_check_ow.txt](deploy_check_ow.txt) |
| 2026-10-09 01:07:43 | 본 세션이 파일럿 P0의 chain을 시작했다(`LIB=ow`). 잠금을 기다렸다 | 파일럿 결과 폴더의 `chain.out` |
| 2026-10-09 | 본 실행 빌드 `hd`가 나와(libnccl `e2090323`) 드라이버를 `hd` 트리로 빌드했다(md5 `67050980`, 소스 같음, 경고 없음). 장치 헤더가 `ow`와 달라 따로 빌드가 필요하다 `[측정]`. 배포와 실행은 하지 않았다 | 5절, 세션 스크래치 `agent_mr/out/hd/build_info.txt` |
| 2026-10-09 | `hd`의 diff를 읽고 예측을 다시 이끌었다(3.5). 바꾼 것: K1, K4(거절 사유), K2(kill 0–2 s 뒤), K5(받는 쪽 오류, 보내는 쪽 성공), 가설 H4. 더한 것: R1, 열 `surv_rx_failed`, `n_hd`, `n_judged_dead`, `n_esc`, `n_fw_over`, `n_copy_to`, `n_cancel`, `score.py`의 `hd` 빌드 표시. 근거 문장만 고친 것: K3, K6, K7, Y1–Y3. 이유: `hd`는 죽음을 소켓으로 바로 판정해 거절하고, 거절이 통신기의 사용자 abort 단어를 올려 랭크의 모든 장치 대기를 오류로 푼다. 라운드 상한(8번/60 s)은 이 실험의 셀에서 닿지 않는다(한 랭크 많아야 3번). 시험 스위치 두 개는 `hd`에 그대로 있다 | 1절 끝, 3.5, [predictions.csv](predictions.csv) |
| 2026-10-09 | 예측은 아직 고정하지 않았다. 파일럿(P0, `ow`, 잠금을 기다리는 중) 뒤 3.4의 값만 바꿀 수 있고, 그 뒤 사전 등록 커밋과 태그 `prereg/gin-multirank-v1`에서 고정한다. 파일럿을 돌리는 동안 파일럿이 읽는 스크립트(`run_mr.sh`, `cells.sh`, `hold.sh`, `chain.sh`)는 고치지 않았다 | 3절 |
| 2026-10-09 02:30:47 | 본 세션이 `hd` 드라이버를 `mr/hd/`에 배포했다(종료 코드 0). 두 노드 md5 `67050980`, 두 노드 `ldd`가 `hd` 번들의 libnccl(`e2090323`)을 찾음, 기존 번들 40파일 그대로 `[측정]` | [deploy_check_hd.txt](deploy_check_hd.txt), 5절 |
| 2026-10-09 03:15:20–03:20:56 | 파일럿 P0(`ow`): 03:15:20에 잠금, 유휴 확인 뒤 03:15:51–03:20:56 hold, 종료 코드 0. 17회, 남은 `gin_mr` 0(`LEFT_STREAK` 0), hold 전후 mlx5 줄과 펌웨어 명령 실패 계수 그대로, 두 노드 컴퓨트 모드 `Default`. 채점하지 않음 | `results/20261009_pilot/`(커밋 안 함: `hold_P0.out`, `chain.out`, `snap_*-P0.txt`, `mlx5_new_P0.txt`, `p0/`), 3.6 |
| 2026-10-09 | 파일럿 검토: `rows_mr.py`로 열을 다시 만들어(`trials_p0.csv`, 17행) `ow` 예측과 비교했다. 훅 9번과 kill 2번이 계획대로 트래픽 안에서 일어났다. 3.4의 값은 바꿀 필요가 없었다(훅이 커널 시작 5 959–5 975 ms 뒤, kill이 7 983–8 026 ms 뒤, 순환 라운드 시작의 퍼짐 17.4 ms). 랭크 4개의 프로세스 시작에서 커널 시작까지 919–1 278 ms(랭크 실행 52번) `[측정]` | 3.4, 3.6, `results/20261009_pilot/trials_p0.csv`(커밋 안 함) |
| 2026-10-09 | 파일럿이 보인 열의 잘못과 소스 분석의 빈틈으로 예측을 고쳤다. `rows_mr.py`에 열 `rec_first_after_round_ms`, `rec_last_after_round_ms`를 더했다. Y3는 판정식의 열만 바꿨다(문장과 한도 그대로). Z1은 다시 이끌었다(열, 한도 2 000 → 5 000 ms, 문장). Z2를 더했다. F2, R1은 근거 문장만 고쳤다. 증거: 순환 시행에서 rank 2의 recovered 줄 `total_us` 549 ms와 첫 라운드 줄 25.1 s 뒤의 재개, 같은 시행의 "refused reason=not_rts" 줄 둘과 "rerunning as a full reset" 줄 둘, 모든 문맥 장애 시행의 라운드 단계 시간 `[측정]`. 파일럿에서 맞거나 틀렸다는 이유만으로 바꾼 예측은 없다. 사슬 셀은 파일럿에 없었다 | 1절 장애 훅, 3.1, 3.3, 3.6, [predictions.csv](predictions.csv), [rows_mr.py](rows_mr.py), [score.py](score.py)(이름표만) |
| 2026-10-09 | 7절 hold 추정을 파일럿 시행 시간으로 고쳤다(본 실행 약 55분). `cells.sh`는 머리말 설명만 고쳤다(값 그대로). 예측 42줄(새 셀 31, 대조 9, 탐색 2)로 확정했다. 확정한 [predictions.csv](predictions.csv)의 sha256은 `3a35b6dba9b99cde8b0d4086ad5b87ad9d0826175f625dea86d725fc192a90ee`다. 상태는 `DRAFT`다. 고정은 사전 등록 커밋과 태그 `prereg/gin-multirank-v1`에서 한다 | 3절, 7절 |

## 13. 사전 등록 이후 변경

> 기존 문장을 고치지 않고 여기에 덧붙인다. 변경이 많으면 `DEVIATIONS.md`에 두고 링크한다.

| 날짜 | 무엇을 | 이유 | 영향 범위 | 커밋 |
|---|---|---|---|---|

## 14. 원자료와 결과표

아직 없다.

## 15. 결과 요약

아직 없다 `[미확인]`.

## 16. QA와 재현성

아직 없다.

## 17. 결론

아직 없다.

## 18. 한계

아직 없다. 설계 단계에서 보이는 한계: 장애 훅이 문맥 단위라서 장애 난 문맥의 다른 QP 둘도 ERR이 된다(쓰지 않는 QP). 그 QP가 라운드를
요청하는 상대 쪽이면 응답 쪽이 쌍 범위를 거부해 전체 범위 라운드가 된다(순환, 사슬 셀, 3.6). QP 하나만 고장 나는 실제 장애에서는 생기지
않는 거부다 `[추론]`. 순환 셀은 helper 멈춤 시험 스위치로 겹침을 만든다. 자연 타이밍에서 얼마나 자주 겹치는지는 재지 않는다.

## 19. 다음 작업

아직 없다.

## 20. 참고자료

- `../TRANSPARENT_S1.md`(helper, 메일박스, 상대별 소켓), `../TRANSPARENT_S2.md`(한 커널에 두 역할, 동시 시작)
- `../pair_reset/EXPERIMENT.md`(쌍 범위 라운드), `../pair_check/EXPERIMENT.md`(응답 쪽 범위 확인)
- `../oneway/EXPERIMENT.md`(빌드 `ow`, 판정식 문법, 스크립트 구조)
