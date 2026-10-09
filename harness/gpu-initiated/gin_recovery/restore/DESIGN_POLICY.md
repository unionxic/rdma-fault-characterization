# 장애 반응 정책: 감지와 반응을 나눈 통합 설계 (gin-restore, gpu-detect)

**목적:** gpu-detect 계층(GIN `hw`, NVSHMEM `t1w`)이 섞어 둔 "장애 감지"와 "fail-fast 반응"을 나누고, gin-restore가 요구하는 반대
반응(대기를 붙잡고, degraded 해제를 막고, 새 프로세스를 같은 논리 rank로 받아 재실행)을 communicator마다 고르는 정책으로 넣었을 때, 기존
장치와 충돌이 남지 않는지 한 표로 정리한다.

| 항목 | 값 |
|---|---|
| 상태 | 검토용 설계. 사용자 결정(2026-10-09)으로 충돌이 남아 있는 동안 구현하지 않는다. 이 문서의 검토가 끝날 때까지 아무것도 빌드하지 않는다. 사용자 결정(2026-10-09, 뒤): B4는 (나)(5절), B1–B3은 실행 가능성 시험만 빌드한다(EXPERIMENT.md 9.15절). 복원 계층은 여전히 구현하지 않는다 |
| 실험 | [EXPERIMENT.md](EXPERIMENT.md)(gin-restore, `DRAFT`). 그 문서의 상호작용 표와 막는 문제는 이 문서로 옮겼다 |
| 작성일 | 2026-10-09 |
| 근거 트리 | hr: 세션 스크래치 `agent_ts2hr/nccl-src`(gin-remaining). hw: `agent_gd/gin/nccl-src`(기준 커밋 `382bbb4` = hr, gpu-detect worktree의 `harness/gpu-detect/hw_layer.diff` md5 `be0ea9ed`, libnccl md5 `efc48ca1`). nvs: `agent_gd/nvs/src`(t1_380 위의 t1w, t1w_layer.diff md5 `ac24448b`). 모두 2026-10-09에 읽기만 함 |
| 독립 검토 | 검토 1(EXPERIMENT.md 초안 표 대상), 검토 2(이 문서 대상, 재확인 다섯 번) 반영. 검토 2의 마지막 판정(커밋 `0af9190e`): "막는 문제 B1–B4 밖에 풀리지 않은 충돌 없음"(6절) |

표시: `[소스]` 코드에서 읽음, `[측정]` 원자료에서 확인, `[추론]` 해석, `[미확인]` 확인 안 함.

**줄 번호 규칙.** `gin_host_gdaki.cc`의 줄은 "hr N / hw M" 꼴로 둘 다 적는다. hw는 이 파일만 바꿨고, 장치 헤더(`gin_gdaki.h`,
`gin_gdaki_device_host_common.h`), `init.cc`, `transport/net_ib/gin.cc`, `gin/gin_host.cc`는 hr과 hw가 같은 파일이다(앞의 넷은 md5 확인 `[측정]`).
그 파일들은 줄 번호 하나만 적는다. NVSHMEM은 `ibgda.cpp`(= `src/modules/transport/ibgda/ibgda.cpp`)와 `wait_until.cuh`(=
`src/include/non_abi/device/wait/nvshmemi_wait_until_apis.cuh`)다. gpu-detect 문서는 gpu-detect worktree의 `harness/gpu-detect/EXPERIMENT.md`다
(아직 master에 없음). "F번호"는 검토 1, "V번호"는 검토 2의 지적이다(6절).

## 1. 문제

gpu-detect는 감지를 고치면서 반응도 fail-fast로 굳혔다 `[소스]`.
- GIN `hw`: QP 상태 감시(`gdakiDetWatchStep` hw 6085–6187)가 ERR QP를 장애 기록으로 바꾸고, 보통 라운드가 살아 있으면 복구, 죽었으면 거절한다.
  `NCCL_GIN_TS_DEGRADED_ROUNDS=0`(hw 2676)이 기본이라 칸 0이 오른 뒤에는 어느 상대와도 라운드를 게시하지 않는다(`gdakiUaPeerRaised` hw 2918–2925).
  그런 거절은 원인이 Local이라 shrink 넘기기를 막는다(gpu-detect 문서 9.1절 (d)).
- NVSHMEM `t1w`: FIN이 BYE 없이 오면 바로 죽음으로 거절하고(`t1_helper_main`의 판정, ibgda.cpp 7930–7951), 거절마다
  `NVSHMEM_IBGDA_FT_T1_FAILSTOP_MS=0`(기본, ibgda.cpp 8048)이면 `_exit(70)`이다(`t1w_after_decline` 6841–6858, `t1w_failstop_exit` 6813–6839).

gin-restore는 죽음에 반대로 반응해야 한다: 대기를 붙잡고, degraded 해제를 막고, 새 프로세스를 같은 논리 rank로 받아들이고, 재실행한다
([EXPERIMENT.md](EXPERIMENT.md) 9.1–9.8절). 두 반응이 같은 코드 자리(거절)에 섞여 있으면 어느 하나를 넣을 때 다른 하나가 깨진다.

## 2. 감지와 반응

### 2.1 감지(두 정책에 공통)

감지는 "무슨 일이 있었는가"의 증거만 만든다. 증거를 만드는 코드, 그 변수(감시 주기와 유예 등), 그 로그 줄은 두 정책에서 같다.

| id | 감지원 | 만드는 증거 | 코드 |
|---|---|---|---|
| S1 | 장치 분류: 요청 대기, flush, 보내기의 slot 대기가 본 오류 CQE를 분류해 기록 | QP 장애(분류: RETRY_EXC, LOCAL_QP_ERR, REM_ACCESS 등) | `q4Report` gin_gdaki.h 859–, `tsPoll` 1103–1108, `tsSwErrReport` 1031–1045; 호스트 `gdakiQ4Handle` 1008–1030(hr = hw, Q4 감시 스레드) → `gdakiTsRoutes` hr 3260–3264 / hw 3285–3289 → `gdakiTsPushFault` hr 3266–3271 / hw 3291–3296 |
| S2 | hw QP 상태 감시: 라운드 밖에서 10 ms마다 QUERY_QP, ERR/SQER이면 합성 기록 | QP 장애 | hw `gdakiDetWatchStep` 6085–6187(상대 거르기 6094), `gdakiDetRecord` 5986–6058, `gdakiDetQueued` 6060–6069, helper 루프에서 부름 6410, 변수 2673–2675 |
| S3 | helper 소켓 liveness | 죽음: BYE 없는 FIN, BADMAGIC, "모름" 목록 밖의 errno(`gdakiTsCauseLiveness` hr 3712–3718 / hw 3737–3743, `gdakiTsSocketLost` hr 3746–3777 / hw 3771–3802; 판정 WARN 줄 hr 3766, 3774 / hw 3791, 3799), 1–5 s 간격 거절 둘(`gdakiTsRefused` hr 3783–3810 / hw 3808–3835). 떠남: BYE(hr 6078–6080 / hw 6363–6365). 모름: reset, 시간 초과(`gdakiTsMakeUnknown` hr 3724–3741 / hw 3749–3766). 상대의 거절: FAIL(hr 3896–3906 / hw 3921–3931). 남의 연결: nonce 불일치(hr 4198–4203 / hw 4223–4228) | |
| S4 | 감시(watchdog, Q4 감시 스레드): 펌웨어 명령 단계 초과, 라운드 초과, 기록이 쌓였는데 helper가 1 s 넘게 돌지 않음 | 로컬 정체 | `gdakiTsWatchdog` hr 3463–3526 / hw 3488–3551, `gdakiRecFwGuard` hr 1742–1770 / hw 1743–1771 |
| S5 | 장치의 포기와 훑기: 쉬던 장치 스레드가 hold 한도 뒤 포기(DEV_FAILED, abandoned), 기록 유실 | "application이 이미 실패를 들음" | `tsGiveUp` gin_gdaki.h 188–192, `tsLateFail` 200–214, `tsParkStable` 252–297; `gdakiTsScan` hr 5862–5900 / hw 5891–5929 |
| S6 | NVSHMEM t1w: BYE 없는 FIN 판정 | 죽음 | ibgda.cpp 7930–7951, `t1_peer_fin` 6442–(BYE 먼저 읽기), `t1_fini`의 BYE 8243–, `NVSHMEM_IBGDA_FT_T1_FIN_DEATH` 8047 |

증거의 종류: 죽음(DEAD), 떠남(LEFT), 모름(UNKNOWN: 재연결 기계가 맡음, 반응 아님), 상대의 거절(PEER_DECLINED), QP 장애(PAIR_FAULT, 상대가 살아
있으면 라운드), 로컬 정체(LOCAL), application이 이미 들음(TOLD, 2.4절).

### 2.2 반응(정책)

정책은 communicator마다 하나이고 두 값이 있다.
- **fail-fast**(기본): 지금의 hr, hw 동작 그대로. 죽음 → 그 상대 거절(상대별 단어, 비동기 오류, QP를 ERR로, 게이트 실패) → 2 s 뒤 degraded로 칸 0
  (랭크 2개면 "모든 상대 거절" 규칙으로 바로) → (hw) `DEGRADED_ROUNDS=0`이면 그 뒤 어느 상대와도 라운드 게시 없음.
- **hold-for-restore**: 강한 죽음 증거(2.4절)가 있고, 그 상대가 무장(ARMED)이고, TOLD가 아니면 거절하지 않고 붙잡는다(상태 HELD, COMMITTING, PUBLISHED, 이하 "붙잡은 상대"; 3절).
  복원 시한까지 복원이 안 되거나 복원 중 무엇이든 실패하면 그때 fail-fast 반응을 그대로 한다(fallback). fallback은 그 상대를 원인 PeerDead,
  `GDAKI_UA_PEER_DEAD`로 거절하는 것이고, 붙잡은 상대에 대한 다른 거절도 모두 이것으로 바뀐다(V1). 그래서 fallback 뒤의 상태(단어, degraded, 책임 기록)는
  fail-fast에서 그 상대가 죽었을 때와 같다.

정책이 바꾸는 것은 **죽음에 대한 반응**, 붙잡은 상대에게서 온 QP 장애 기록의 처리(라운드 대신 흡수), 붙잡은 상대에 대한 거절의 원인(PeerDead로)뿐이다.
살아 있는 상대의 QP 장애, 분류 불가, 확대 상한, 상대의 FAIL, BYE, 감시, 장치의 포기는 두 정책에서 같게 처리한다.

NVSHMEM은 정책이 fail-fast 하나다(복원은 범위 밖). t1w의 `FIN_DEATH`, `FAILSTOP_MS`, `FAILSTOP_CODE`는 fail-fast 반응의 변수다. hold 정책의 프로세스는
NVSHMEM을 쓰지 않는다(X6).

### 2.3 정책 고르기, 기본값, 무장 조건

- 환경 변수 `NCCL_GIN_FAULT_POLICY=failfast|hold`. 기본 `failfast`. GIN 문맥을 만들 때(`gdakiTsSetup` hr 6152– / hw 6438–) 읽고, 설정 all-gather
  (`gdakiTsAddr`, hr 6232 / hw 6518)에 실어 모든 rank가 같은지 본다. 다르면 그 communicator는 fail-fast다(WARN 한 줄). 레코드가 커지므로 한 job의 모든
  rank가 같은 라이브러리여야 한다(지금도 이 all-gather는 같은 판을 전제함).
- communicator마다의 선택은 API로: `hold`는 application이 그 communicator에 `ncclGinRestoreResume`을 부른 뒤에만 무장한다(EXPERIMENT.md 9.4절).
  부르지 않는 application의 communicator는 변수와 상관없이 fail-fast다. 이 호출은 새 `nccl.h`에만 있으므로 그 application이 새 헤더로 빌드됐다는
  증거로 쓰고(`[추론]`: 한 프로그램이 헤더 둘을 섞는 경우는 막지 못함), 장치 쪽의 확인은 GPU 문맥 판 번호(A5)가 한다.
- **communicator의 무장 조건**(`gdakiTsStart`에서 확인, 하나라도 아니면 그 communicator는 fail-fast):
  - 투명 복구 GDAKI 문맥이 정확히 하나(F6: helper는 문맥마다, 단어는 communicator마다라 둘 이상이면 한 helper의 fallback이 다른 helper의 복원을 깸). 문맥은
    devComm을 만들 때 생기고(`gin_host.cc` 374) GIN 연결마다 하나다(`ginCommCount`, `gin_host.cc` 277).
  - `NCCL_GIN_TS_RECONNECT=1`(F27).
  - 그 문맥이 확대 상한으로 복구를 멈추지 않았음(`ts->escalated`, F26).
  - 복원 시한과 hold 한도의 관계(T4).
  - NIC 복사 경로가 켜져 있고(`gdakiLbOn`), 복원이 쓰는 GPU 버퍼(window rkey 표, 신호와 카운터 표, 로그 고리, 측 표)가 문맥을 만들 때 루프백 MR에
    등록됨(V8, V12). devComm을 만든 뒤 등록한 window가 있으면 무장하지 않는다(그 rkey 표는 루프백 MR에 없음). 도중에 NIC 경로가 꺼지면 fallback.
  - QP 감시가 켜져 있음(`NCCL_GIN_TS_QPWATCH_MS` > 0, hw 6087): 누적 실행 수의 표본(G7, V14).
  - window가 strict ordering으로 등록됨(`NCCL_WIN_STRICT_ORDERING`, 5절 B3의 해결 후보. B3이 풀리기 전에는 조건으로 둔다).
  - 이 rank의 GPU 문맥(판 3, A5)에 0이 아닌 측 표 포인터가 있음(검토 3 W1, 2026-10-09). hw는 GPU 문맥을 `gdakiTsSetup`(hw 7986)보다 먼저 장치로 복사하므로
    (`copy_h_to_d`, hw 7966) 포인터는 그 복사에 실리지 않는다. 복원 계층(RL10)은 측 표를 할당한 `gdakiTsStart` 안에서, `ncclGinGdakiCreateContext`가
    돌아오기 전에 그 칸 하나를 동기 H2D 한 번으로 쓰고(hw 7106처럼 돌아오기 전에 동기화; 호스트 사본 `host_buf`에도 같은 값) 그 뒤에는 쓰지 않는다(그 뒤에
    쓰면 이미 도는 커널이 L1에 남은 0을 계속 읽을 수 있음). 정책 `failfast`나
    `NCCL_GIN_RESTORE=0`이면 포인터는 0이고 그 communicator는 무장하지 않는다.
  - host RMA가 꺼져 있음(`comm->config.numRmaCtx == 0`, B1 설계 검토 T1-1, 2026-10-09): 켜져 있으면 첫 window 등록에서 RMA proxy가 모든 상대에게 hook 밖의
    IB 연결을 맺어(`ncclRmaProxyConnectOnce`, `transport/net_ib/gin.cc` 545–556) 예비 프로세스가 재생할 수 없다(A3).
  - `runtimeConn = 1`, `nvlsSupport = 0`(B2 설계 검토 T2-3): runtime connect를 끄면 초기화가 상대와 전송을 잇고(`init.cc` 1837–1906), NVLS는 multicast handle을
    상대에게서 가져온다. 둘 다 재생할 수 없다. host에서 띄운 NCCL collective나 P2P는 runtime connect로 P2P/SHM 전송을 만들어 상대 버퍼를 가져오므로
    application 요구로 막는다(EXPERIMENT.md 9.7절 6번).
  - 무장할 상대는 이 rank와 LSA 팀이 다름(lsaSize 2 이상이면 메모리 handle의 파일 기술자를 상대 proxy에서 받아 기록할 수 없음, `dev_runtime.cc` 322–328; 5절 B2,
    T1-4).
- **상대의 무장(ARMED)은 communicator 전체의 합의다**(V6). 상대 p는 다음이 모두 참일 때만 ARMED다.
  - p의 확정된 체크포인트가 짝에 있고, 그 체크포인트의 입력 멈춤에서 **모든** 생존 rank가 "p에 대해 무장 가능"으로 답했음(PAUSED에 실음. 그 rank의
    communicator 무장 조건, 위의 측 표 포인터 포함).
  - 그 뒤 어느 rank도 p에 대한 DISARM을 보내지 않았음. rank q는 p로 가는 로그가 넘치거나, p로 `get`을 냈거나(M2), 자기 문맥이 무장 조건을 잃으면
    DISARM(p)를 모든 rank에 보낸다. 받은 rank는 p를 OFF로 둔다(p의 다음 확정 체크포인트까지).
  - p의 예비 프로세스가 짝에 등록돼 있음.
  하나라도 아니면 p의 죽음에는 모든 rank가 fail-fast다.

### 2.4 우선순위, 증거, fallback 순서

위가 이긴다.
1. application이 고른 동작: `ncclCommAbort`, `ncclCommRevoke`, 중단 shrink(이 셋은 모든 단어를 올림), `ncclCommDestroy`(정리: helper를 멈춤, 단어는
   올리지 않음). 복원 중이면 취소(CANCELLED).
2. 이미 application에 닿은 것(TOLD). 이 상태에서는 hold를 시작하지 않고, 복원 중이었으면 fallback.
3. hold-for-restore(무장된 상대의 강한 죽음 증거).
4. 복원 시한 또는 복원 중 실패 → fallback.
5. fail-fast.

fallback 순서는 hold-for-restore → 복원 시한 → fail-fast다. fallback은 지금의 거절을 그때 부르는 것이고, degraded 시계도 그때 시작한다(칸 0은
fallback + `NCCL_GIN_TS_DEGRADED_MS`, 랭크 2개면 바로).

- **TOLD의 판단**: (a) communicator 등록부(`gdakiUa`, hr 2705–2718 / hw 2712–2725)에서 그 상대의 단어, 칸 0, `allWhy`, (b) 그 문맥의 비동기 오류가
  서 있음(`q4->setAsync`; 다른 상대의 거절이 세운 것도 communicator에 대한 것이므로 TOLD), (c) 그 상대로 가는 게이트의 `abandoned`나 DEV_FAILED(게이트
  읽기, NIC 복사 경로). (c)의 읽기가 실패하면 TOLD로 본다(보수적).
- **강한 죽음 증거**(F9, V11): 거절의 `uaWhy`가 `GDAKI_UA_PEER_DEAD`이고, 그 죽음을 판정한 `gdakiTsSocketLost`가 남긴 `pe.lostCause`가 "FIN"(BYE 없음)
  이거나 "ECONNREFUSED"(1–5 s 간격 거절 둘)이고, `pe.lostAfterCommit`가 서 있지 않은 경우만. BADMAGIC과 그 밖의 errno로 판정된 죽음은 hold를 시작하지 않고 fail-fast다(흐름이 어긋난 산
  프로세스일 수 있음). REJOIN은 `lostCause`와 `closeCause`, `lostAfterCommit`를 지운다(낡은 원인이 남지 않게).
- **`pe.lostAfterCommit`**(2026-10-09, gpu-detect와의 계약, 메인 세션이 정함): gpu-detect는 응답 쪽이 Commit한 뒤 게시 전에 소켓을 잃은 길(3절,
  hw 5285–5292, 5298–5303)을 고친다. 그 길에서 소켓을 잃은 자리에서, `gdakiTsSocketLost`를 부르기 전과 어느 돌아가기보다도 먼저 상대별 표시
  `pe.lostAfterCommit = true`를 세우고(검토 3 W10, X5; 규칙은 이것 하나), 그 잃음이 죽음 판정이면 거절을 원인
  PeerDead, `GDAKI_UA_PEER_DEAD`로 한다(degraded 예약). 죽음 판정이 아니면 지금 동작(원인 Unknown, `uaWhy` DECLINED) 그대로다. 그래서 고친 뒤에는 그 거절이
  위의 앞 두 조건을 채울 수 있다. 복원 설계는 이 창을 계속 붙잡지 않는다: G2의 강한 증거 검사가 이 표시가 선 거절을 빼고, 그 상대가 ARMED였으면 NOHOLD(p)를
  보낸 뒤 fail-fast로 거절한다(3절 N4). 표시는 G2가 그 거절 안에서 읽으므로 거절 전에 서 있어야 하고, 지우는 곳은 REJOIN뿐이다(D4).
  검토 3의 다듬음(W10, 메인 세션과 gpu-detect에 넘길 것): 그 고침이 `gdakiTsSocketLost`만 부르고 거절을 helper 루프(hw 6380–6386)나 라운드의 죽음 길
  (hw 5507–5518)에 맡기면 "거절 바로 전"은 그 창을 모르는 코드가 된다. 그래서 표시는 잃은 자리에서, `gdakiTsSocketLost`를 부르기 전과 어느 돌아가기보다도
  먼저 세운다. Commit 뒤 응답 쪽의 다른 출구(DONE 시간 초과 hw 5304, BYE 5305–5307, FAIL이나 모르는 레코드 5309–5311, `RepostApply` 실패 5313)에서도
  세우면 앞으로 원인이 바뀌어도 이 지킴이 따로 선다(선택). 같은 화신에 대해 표시 없는 PEER_DEAD 거절이 뒤따를 수는 없다: 첫 거절이 `pe.declined`를 세우면
  `gdakiTsSocketLost`가 더는 `deadJudged`를 세우지 않고(hw 3796), 다시 걸기와 탐침이 멈추고(hw 3997, 4094), 그 상대 단어가 TOLD로 G2의 hold 갈래를 막는다
  `[소스: 검토 3]`. 2026-10-09 확인: gpu-detect의 `hk` 빌드(`hk_layer.diff`, `prereg/gpu-detect-v1`)의 `gdakiTsDeclineAfterCommit`가 이 규칙대로 두 자리에서
  표시를 맨 먼저 세우고, 표시는 `gdakiTsInstall`에서 지운다 `[소스: hk_layer.diff, 읽기만]`. 검토 3 W11(gpu-detect 쪽 메모): ACK 보내기 실패 길에서는 `gdakiTsSend`가 `pe.closeCause`를 세우지 않고 `gdakiTsInstall`이 지우므로
  (hw 3892), errno를 먼저 `closeCause`에 옮기지 않고 `gdakiTsSocketLost`를 부르면 원인이 "모름"으로 남아 `gdakiTsCauseLiveness`(hw 3737–3743)가 죽음으로
  분류한다(EPIPE가 거짓 죽음과 degraded가 됨). hw 5606, 5749처럼 errno를 먼저 옮겨야 한다. 복원 설계에는 영향이 없다("모름"은 강한 증거가 아니고 표시가 뺌).
  2026-10-09 확인: `hk`는 ACK 보내기 실패 길에서 죽음 판정을 하지 않고 errno 이름을 `closeCause`에 넣는다(hk 검토 지적 1로 받기 쪽 peek을 뺌) `[소스: hk_layer.diff]`.
  복원 계층을 만들 때의 기준은 그때의 gpu-detect 빌드(지금은 `hk`)이고, 이 문서의 hw 줄 번호는 그때 다시 맞춘다.
- **잘못된 죽음 판정의 막**: (1) 예비 프로세스는 같은 노드에 있으므로 활성화 전에 원래 프로세스(등록 때 받은 PID)가 끝났는지 스스로 확인한다:
  `/proc/<pid>`가 없거나, `/proc/<pid>/stat`의 상태가 Z(거두기 전 zombie)나 X이거나, 시작 시각(22번째 칸)이 등록 때의 값과 다르다(거둔 뒤 PID가 다시
  쓰인 경우; V9). 아니면 활성화를 거절하고 모두 fallback한다. (2) 복원 라운드가 생존
  rank의 QP를 예비 프로세스의 새 QPN에만 다시 이으므로, 옛 프로세스가 살아 있어도 RC 연결이 없어 생존 rank의 메모리에 쓰지 못한다(펜싱 `[추론]`).
  (3) 그 논리 rank의 HELLO, HELLO-ACK, PROBE-ACK는 화신 번호가 지금과 같아야 받는다(D4).
- **communicator마다 붙잡은 상대는 하나**. 복원 중 다른 상대의 죽음 증거가 오면 붙잡은 상대도 fallback하고 새 죽음은 fail-fast다(단일 실패 범위).
- **모두 함께**(V6): 예비 프로세스의 활성화는 모든 생존 rank가 p를 붙잡았다고 짝에게 알린 뒤에만 한다(HOLDING(p)). p를 붙잡은 생존 rank가 fallback하면
  FALLBACK(p, 화신)을 모든 rank와 예비 프로세스에 보내고, 그 화신을 붙잡았거나 되살린 rank도 fallback한다(붙잡지 않은 rank는 OFF로만, 3절 Q1).

### 2.5 불변식

- (가) hold 동안 그 상대에 대해 application에 닿는 것은 없다: 상대별 단어, 칸 0, 비동기 오류, degraded 예약, 거절의 WARN 줄이 없다. 대기는 붙잡혀 있다.
  죽음 판정의 WARN 줄(hr 3766, 3774 / hw 3791, 3799)은 감지라서 두 정책에서 남고 `ncclGetLastError`에도 보인다.
- (나) 그 상대나 communicator에 대해 무언가가 application에 닿았으면 hold는 시작되지 않거나 끝난다(fallback). 실패를 들은 연산은 다시 내지 않는다는
  기존 규칙(게시 전 확인 `gdakiUaPeerRaised`, 커밋 지점 Dekker)이 그대로 지켜진다.
- (다) 정책 `failfast`에서 호스트 동작은 hw와 같다(검토 2 확인). 정책 `hold`이지만 무장하지 않은 communicator는 반응은 fail-fast와 같아도 설정이
  다르다: 문맥을 만들 때 루프백 MR이 더 많고(복원 버퍼), 그 등록에서 CUDA driver 함수를 부르고, 자체 시험 범위가 넓다(N5). 정책 hook(4.10절 G1–G9)과 같은 파일에 넣는 복원 계층의 코드(4.11절)는 fail-fast에서 늘 같은 값을 돌려주거나
  닿지 않는다. 장치 헤더의 변경(EXPERIMENT.md 9.9절 DV1–DV4)은 fail-fast에서 같은 결과를 내지만 시간을 바꿀 수 있다: 보내기마다 측 표 포인터를 한 번
  보는 것(DV2), 키 읽기 자리(B4). B4의 결정 (나)(2026-10-09) 뒤 fail-fast에서 키 읽기의 자리와 종류는 지금과 같고, 더해지는 것은 DV2와 같은 포인터 읽기에
  기대는 분기 하나와 내부 인자 하나(신호 키의 주소)다(검토 3 W8: 그 인자가 게이트의 `__noinline__` 느린 길 호출을 건너 살아 있어 레지스터 배치가 바뀔 수
  있음, 결과는 같음). 게이트 뒤의 키 다시 읽기는 측 표 포인터가 0이 아닌 hold 정책의 communicator에서만 한다(A1). 그래서 hold 정책이지만 무장하지 않은
  communicator도 장치에서 fail-fast와 다르다: 문맥을 만든 때부터 보내기마다 키를 게이트 뒤에 다시 읽고(L1 적중을 잃음), coop의 추가 동기화를 치른다(로그 켬
  낱말은 게이트를 잡은 0번 스레드만 보므로 건너뜀 깃발을 적어도 한 번의 동기화로 나눔, C2). 로그는 QP마다의 켬 낱말이 선 뒤에만 쓰고(C2; 검토 3 W2), 그 낱말은
  그 QP의 첫 체크포인트 멈춤에서 서므로 무장하지 않은 communicator도 첫 멈춤 뒤에는 로그를 쓸 수 있다(검토 3 재확인 X1).

## 3. 상태 기계 (상대 하나, hold-for-restore)

```
 OFF ──(Resume 호출, communicator 무장 조건, 모든 생존 rank가 무장 가능으로 답한 확정 체크포인트, 예비 등록)──▶ ARMED ──(DISARM)──▶ OFF
 ARMED ──(강한 죽음 증거, TOLD 아님)──▶ HELD ──(hold 시작, 모두 HOLDING, PID 확인, REJOIN, 상태 적용, 복원 라운드)
 HELD ──(helper CAS, 커밋 지점 직전)──▶ COMMITTING ──(게시)──▶ PUBLISHED ──(예비 프로세스의 RESTORED(p))──▶ ARMED(화신 + 1) 또는 OFF
 HELD ──(시한: G8 CAS와 CPU 쓰기, 실패, TOLD, 다른 죽음, FALLBACK(p, 화신))──▶ FALLBACK = 그 화신을 PeerDead 거절
 COMMITTING ──(커밋 지점 뒤 복사나 doorbell 실패: 게시가 일어나지 않음)──▶ 그 자리에서 PeerDead 거절
 COMMITTING ──(그 사이 온 FALLBACK(p, 화신))──▶ 게시를 마친 뒤 PUBLISHED에서 FALLBACK
 PUBLISHED ──(시한: G8은 상태만, 실패, 그 상대 QP의 장애 기록, FALLBACK(p, 화신))──▶ helper가 PeerDead 거절(2ERR 먼저)
 그 화신을 붙잡았거나 되살린 상태 ──(FALLBACK(p, 화신) 받음)──▶ 그 화신을 PeerDead 거절, 그 화신은 다시 붙잡지 않음
 ARMED 또는 OFF(그 화신을 붙잡지 않음) ──(FALLBACK(p, 화신)이나 NOHOLD(p) 받음)──▶ OFF(거절하지 않음: 아직 죽음 증거가 없음)
 HELD, COMMITTING, PUBLISHED ──(abort, revoke, shrink, destroy)──▶ CANCELLED
 OFF 또는 ARMED가 아닌 상대의 죽음 ──▶ fail-fast 거절(ARMED였으면 NOHOLD(p)도 보냄)
```

"붙잡은 상대"는 HELD, COMMITTING, PUBLISHED의 상대다. 다만 감시와 기록과 훑기에서 빼는 규칙(G3, G4의 흡수, G5)은 QP가 ERR인 HELD와 COMMITTING에만
걸린다. PUBLISHED의 QP는 예비 프로세스와 RTS로 살아 있으므로 감시하고, 그 QP의 장애 기록은 복원 실패로 보아 fallback한다(라운드를 열지 않음; P3). 이 상태는 상대마다 원자 칸 하나이고, helper와 Q4 감시 스레드(G8, G9)는 잠금 없이 읽고 CAS로만
바꾼다(N3: G9는 outMu 안 hw 3530에서 불리고 helper의 거절은 정책 칸을 본 뒤 outMu로 가므로, 정책 잠금을 두면 차례가 뒤집혀 교착될 수 있음).

- **시한과 게시의 다툼**(N1). helper는 복원 라운드의 게시 전 확인(hr 4708 / hw 4733) 뒤, 커밋 지점(hr 4713 / hw 4738) 전에 CAS(HELD → COMMITTING)를 한다.
  G8은 HELD에서 CAS(HELD → TIMED_OUT)에 이겼을 때만 CPU 쓰기(단어, 비동기 오류, 책임, degraded)를 한다. HELD의 QP는 hold 시작에서 ERR이고, 복원 라운드의 Commit(5단계)부터
  CAS(8단계)까지는 RTS이지만 생존 rank의 게이트가 홀수라 보내지 못하고 예비 프로세스는 모든 DONE_RS 전에는 보내지 않으므로 그 QP로 NIC이 하는 일이 없다(Q4).
  그래서 "QP를 ERR로 먼저, 그 다음 단어"라는 거절의 차례(hr 4931–4943 / hw 4956–4968)가 뜻하는 것이 지켜진다. PUBLISHED에서는 QP가 RTS라 CPU로 단어부터 올리면 그 차례가 깨지므로
  (P1) G8은 CAS(PUBLISHED → TIMED_OUT)로 상태만 바꾸고, 거절 전체(2ERR 먼저)는 helper가 한다. PUBLISHED에서는 게이트가 이미 짝수라 장치 대기가 붙잡혀
  있지 않으므로 급할 일이 없다. PUBLISHED의 시한은 hold 한도 항이 없는 따로 된 값(게시 시각 + `NCCL_GIN_RESTORE_MS`)이다. COMMITTING은 G8이 건드리지 않는다: 남은 일은 정해진
  복사와 게시뿐이고 그 시간은 T4의 "복원 라운드 몫"에 든다(라운드 감시도 덮음). CAS에서 진 helper는 커밋 지점 전에 fallback한다. hold 시작의 걸음마다,
  특히 HOLDING을 보내기 전에 TIMED_OUT을 본다. 이렇게 하면 게시 전 확인 뒤에 라이브러리가 스스로 상대 단어를 올리는 일이 없다(불변식 (나)).
- **게시 뒤의 실패**(N2). 생존 rank가 게시한 뒤(PUBLISHED)에도 예비 프로세스가 모든 DONE_RS를 받아 재실행을 시작하고 RESTORED(p)를 모두에게 보내기 전까지는
  붙잡은 상대다. 그 사이 FALLBACK(p)를 받거나 PUBLISHED의 시한이 오면 helper가 새 화신을 PeerDead/PEER_DEAD로 거절한다(G2 갈래 (가)는 "RESTORED 전의
  화신"을 덮음). 그 거절은 게시 뒤 그 상대 QP에 낸 연산의 실패를 application에 알리는 보통의 거절이다. FALLBACK은 화신 번호를 싣는다. 받은 rank가 그 화신을
  붙잡았거나(HELD, COMMITTING, PUBLISHED) 되살렸으면(RESTORED를 받음) 그 화신을 PeerDead로 거절하고 다시 붙잡지 않는다(RESTORED와 FALLBACK이 엇갈려 와도
  복원에 참여한 모든 rank가 거절로 모임, P2). 그 화신을 붙잡지 않은 rank(ARMED, OFF)는 거절하지 않고 OFF로만 둔다(Q1: 그 rank에는 아직 죽음 증거가 없음). 예비 프로세스는 RESTORED
  뒤에도 FALLBACK을 받으면 BYE 없이 끝난다(BYE를 보내면 생존 rank가 LEFT로 보고 degraded 없이 거절할 수 있음, hr 5487–5488 / hw 5516–5517). 재실행은 모든 DONE_RS 뒤에만 한다.
- **RESTORED 뒤**(P5). ARMED(화신 + 1)는 무장 조건(2.3절)이 맞을 때만이고 아니면 OFF다: 새 예비 프로세스가 짝에 등록됐고, 짝은 그 논리 rank를 지금 맡은 프로세스
  (첫 예비 프로세스)의 PID와 시작 시각을 받았고(다음 PID 확인용), 붙잡은 동안 받은 DISARM(p)가 없어야 한다(그 동안 받은 DISARM은 RESTORED 때 적용). 같은
  rank의 두 번째 복원은 체크포인트 k와 그 뒤의 로그로 다시 할 수 있다(예산 X − P_k가 첫 예비 프로세스의 실행까지 덮음, 검토 2 확인).
- **억제 중인 rank와 남의 체크포인트**(P4). 억제 예산이 남은 rank는 다른 rank의 CKPT_PAUSE에 BUSY로 답한다. 그 rank의 보내기 위치가 상대가 실행한 수보다
  예산만큼 뒤라 절단점을 맞출 수 없기 때문이다. 그래서 생존 rank의 다음 체크포인트는 예비 프로세스의 억제가 끝난 뒤에 확정된다.
- **붙잡지 않고 거절하는 rank**(N4, Q1). ARMED인 p를 hold 없이 거절하는 rank(약한 죽음 판정, 3절의 응답 쪽 Commit 뒤 거절, hold 시작 때의 TOLD, 시작 실패)는
  NOHOLD(p)를 모두에게 보낸다. 받은 rank가 p를 붙잡고 있으면 fallback하고, 아니면 p를 OFF로만 둔다(DISARM과 같은 뜻). 거절의 이유가 산 상대일 수도 있는
  것(BADMAGIC, ACK 보내기의 EPIPE나 ECONNRESET)이라도 다른 rank가 p를 거절하지는 않으므로, 한 쌍의 문제가 communicator 전체의 "p 죽음"으로 번지지
  않는다(fail-fast에서 그 한 쌍만 실패하는 것과 같음).
- **PUBLISHED에서 RESTORED가 시한을 이김**(Q2). helper는 PUBLISHED의 TIMED_OUT을 처리하기 전에 예비 프로세스의 소켓과 미룬 칸에서 RESTORED(p)를 먼저 읽고,
  있으면 RESTORED를 따른다(PUBLISHED의 시한은 진행이 멈추지 않게 하는 장치일 뿐임). PUBLISHED의 시한은 `roundMs` + handshake 한도보다 길게 둔다(helper가
  다른 라운드에 묶여 있어도 RESTORED를 읽을 수 있게).
- **PUBLISHED의 낡은 기록**(Q3). PUBLISHED 상대의 장애 기록은 fallback 전에 `ts_epoch < coveredEpoch`인지 보고 그러면 낡은 기록으로 버린다(복원 라운드의
  게시가 `coveredEpoch`를 올리므로, hold 시작의 2ERR이 낸 flush 기록이 늦게 와도 성공한 복원을 무너뜨리지 않음).
- **예비 프로세스가 여는 라운드**(Q5). `gdakiTsRespond`(hr 5739–5820 / hw 5768–5849)는 상대가 거절됐는지만 보고 REQ에 답한다. 복원 계층은 그 맨 앞에서
  붙잡은 상대(HELD, COMMITTING, PUBLISHED)의 REQ에 NACK(새 이유 17, "복원 중")로 답하고, PUBLISHED이면 fallback한다(P3과 같이 PUBLISHED에서는 라운드를 열지
  않음). HELD에서 보통 라운드가 게시하면 계획이 `U = S − 날아가던 것`이 되어 로그로 이미 넣은 연산을 다시 보내기 때문이다. 예비 프로세스는 RESTORED 전에는
  라운드를 시작하지 않는다.
- **같은 상대의 메시지 차례**(R1). 같은 상대에게서 미룬 제어 메시지(M1)는 그 상대의 REQ보다 먼저, 소켓에 도착한 차례대로 처리한다(기다림 안 응답
  `gdakiTsServeLower` hr 5315–5378 / hw 5341–5407에서 바로 답하는 REQ와 미룬 REQ hr 6023–6056 / hw 6308–6341 모두). NACK 17을 보내기 전에도 그 상대의 미룬
  RESTORED를 먼저 적용한다. 그래야 RESTORED 뒤에 같은 소켓으로 온 REQ가 성공한 복원을 무너뜨리지 않는다.

**hold의 시작**(F8, V10). 거절 hook(G2) 안에서 `gdakiTsBusy` 안으로(라운드처럼 25 s 감시를 받고, 쌓임 감시는 Busy 동안 보지 않음 hr
3522 / hw 3547) 차례로, 걸음마다 heartbeat를 갱신하고 TIMED_OUT을 보며:
0. 상태를 HELD로(맨 먼저: 다음 걸음의 펌웨어 단계 2ERR이 넘쳐도 G9가 책임을 PeerDead로 적게, N3).
1. 범위를 모든 문맥으로(`gdakiTsScope = ALL`, 거절이 하는 것과 같음 hr 4919 / hw 4944): 쌍 범위 라운드나 중첩 응답 라운드 안에서 온 죽음도 모든 문맥을 덮음.
2. 그 상대에 준비된 라운드가 있으면 `ncclGinRecoverAbort`(거절이 하는 것과 같음 hr 4930 / hw 4955).
3. `gdakiTsQuiesce`(hr 4416– / hw 4441–)를 그대로: 게이트 홀수, `opMu` 안에서 QP를 ERR로(죽은 상대로 간 WQE가 flush 오류로 끝나 slot을 기다리던
   보내기가 게이트를 나감), 개수 0, 모아 둔 WQE의 doorbell(hr 4471–4499 / hw 4496–4524; 안 하면 복원 라운드의 Prepare가 "GPU producer not quiescent"로
   거절 hr 2213–2236 / hw 2214–2237), `abandoned` 확인. 실패하면 fallback.
4. `pe.deadJudged`, `pe.failedPending`을 지움(거절이 hr 4923–4924 / hw 4948–4949에서 하는 것. 안 지우면 helper 루프 hr 6095–6101 / hw 6380–6386이 루프마다
   다시 들어옴).
5. 게이트가 처음 홀수가 된 시각(라운드의 정지가 먼저였으면 그 시각)을 적음: 복원 시한 계산(T4).
6. 짝에게 HOLDING(p).

상대별 단어, 칸 0, 비동기 오류는 건드리지 않는다. 장치 대기가 본 flush 오류는 기록(D1)이 되고 흡수된다.

**Commit 뒤 게시 전의 응답 쪽 죽음**(F4, V3). 응답 쪽이 Commit(hr 5228 / hw 5253)한 뒤 ACK를 못 보내거나(hr 5260–5267 / hw 5285–5292) DONE을 기다리다
소켓을 잃으면(hr 5273–5278 / hw 5298–5303) 지금 코드는 죽음 판정(`gdakiTsSocketLost`) 없이 `pe.gone = true`를 세우고 원인 Unknown, `uaWhy` DECLINED로
바로 거절한다. 강한 죽음 증거가 아니므로 이 경우는 **두 정책 모두 fail-fast**다. 그래서 "Commit했으나 게시 전인 에폭"을 복원이 다룰 일은 없다(앞 판의
`S_pending`은 지웠다). 이 길은 hw에도 틈이 있다: PEER_DEAD가 아니라 degraded가 예약되지 않아, 랭크 3개 이상에서 상대를 모르는 대기가 풀리지 않는다
`[소스, 추론]`. 정책과 별개의 hw 고칠 거리로 4.10절 끝에 적었다.

2026-10-09: gpu-detect가 이 틈을 고친다(계약은 2.4절 `pe.lostAfterCommit`). 고친 뒤 이 창에서 죽음이 판정되면 거절은 PeerDead, `GDAKI_UA_PEER_DEAD`가 되고
degraded가 예약된다(fail-fast의 상대를 모르는 대기는 2 s 뒤 풀림). 그래도 hold-for-restore는 이 창을 여전히 붙잡지 않는다: 그 거절에는
`pe.lostAfterCommit`가 서 있어 G2가 강한 증거로 보지 않고, 상대가 ARMED였으면 NOHOLD(p)를 보낸 뒤 fail-fast로 거절한다. 그래서 "Commit했으나 게시 전인
에폭"을 복원이 다룰 일은 고친 뒤에도 없다.

**복원 뒤 생존 rank 자신의 무장.** 죽은 rank가 보낸 메시지의 로그는 그 rank와 함께 사라졌다. 모든 rank가 그 복원에 참여했으므로, 각 생존 rank q는 자기
확정 체크포인트의 절단점(되살린 rank에서 q로 오는 통로)이 복원 뒤 로그의 시작보다 앞임을 알고, 자기 다음 확정 체크포인트까지 DISARM(q)를 보낸다(그
사이 q가 죽으면 fail-fast). 단일 실패 범위의 약한 창이다 `[추론]`.

## 4. 통합 상호작용 표

열: 장치와 코드 위치 / fail-fast에서 / hold-for-restore에서 / 우선 / 바꿀 것. "바꿀 것"의 G는 gpu-detect 계층에 넣을 정책 hook(4.10절), L은 복원 계층의
일(4.11절, EXPERIMENT.md 9.9절 RL), DV는 장치 헤더의 일(EXPERIMENT.md 9.9절)이다.

### 4.1 감지

| # | 장치와 코드 | fail-fast | hold-for-restore | 우선 | 바꿀 것 |
|---|---|---|---|---|---|
| D1 | 장치 분류와 기록 경로(S1). 붙잡은 상대의 처리는 HELD, COMMITTING에서 흡수, PUBLISHED에서 fallback(3절, P3). 경로 판단은 Q4 감시 스레드(hr 1021, false면 1026–1035에서 비동기 오류), 처리는 helper의 기록 루프 hr 6114–6124 / hw 6399–6409 → `gdakiTsInitiate` hr 5419– / hw 5448– | 기록 → 라운드: liveness 확인 → 살아 있으면 복구, 죽었으면 거절(hr 5478–5489 / hw 5507–5518) | 경로 판단은 그대로 참(helper로; F28). 살아 있는 상대: 같음. 붙잡은 상대의 기록: 라운드를 열지 않고 흡수(`qs[].handled` 올림). 루프의 뒷정리(`ts->batch`, heartbeat, `nQueued` 줄이기)는 그대로 둠(V16) | 감지(반응은 정책) | G4. L: 흡수 |
| D2 | hw QP 상태 감시(S2) | 거절 안 된 모든 상대의 QP를 10 ms마다 QUERY_QP. ERR/SQER + 유예 5 ms(뿌리 CQE 없으면 50 ms) → 합성 기록 → D1 | HELD와 COMMITTING의 상대는 감시하지 않음(QUERY_QP도, QP와 CQ의 NIC 읽기도 없음). PUBLISHED는 감시함(P3). 이미 줄에 선 기록은 D1처럼 흡수. 복원 뒤(QP가 예비 프로세스와 RTS) 다시 감시. 감시의 에폭 비교(`gdakiDetQueued` hw 6066, `handled >= epoch + 2` hw 6139)는 빈 라운드(M3)에 맞춰 `coveredEpoch`로 | 감지 | G3, G6 |
| D3 | 감시의 펌웨어 명령 부하(S2) | rank마다 (상대 수 × 문맥 수)번/10 ms, `opMu` 안 | 이 rank에서는 hold 시작과 복원 라운드와 겹치지 않음(같은 helper 스레드, 감시는 기록 줄이 빌 때만 hw 6410). 같은 NIC의 다른 rank의 감시와 예비 프로세스의 초기화(QP 생성, MR 등록)는 겹침. 복원 라운드의 펌웨어 단계가 3 000 ms를 넘으면 감시가 그 상대의 단어를 올림 → TOLD → fallback. 감시의 QUERY_QP가 응답 쪽 rmsn도 받아 누적 실행 수에 쓰므로(G7) 누적을 위해서는 복원 계층이 따로 펌웨어 명령을 내지 않음. 체크포인트의 drain 확인(EXPERIMENT.md 9.4절 3단계)은 예외로, r이 응답 QP마다 체크포인트당 몇 번 QUERY_QP를 낸다(예상 drain 시각에 처음, 그 뒤 50 µs 이상 간격, 상한; B3 설계 검토 T3-8, 2026-10-09) | 펌웨어 감시 | G7. L: 복원 셀에서 `detQueryUsMax`와 복원 단계 시간을 잼 |
| D4 | helper 소켓 liveness(S3). 다시 걸지 않음: `gone`/`declined` 상대(hr 3972, 4069 / hw 3997, 4094). HELLO는 낮은 rank에서만, 더 새 세대만(hr 4209–4215 / hw 4234–4240). 거절한 상대에는 FAIL(hr 3910–3923, 4176–4180, 4204–4207 / hw 3935–3948, 4201–4205, 4229–4232). nonce(hr 6237–6239 / hw 6523–6525). 다시 걸기(hr 4046–4064 / hw 4071–4089), 받기 한 번에 500 ms까지 읽음(hr 4175 / hw 4200) | 죽음 → `deadJudged` → 거절(R1) | 판정과 그 줄은 같음. 반응만 다름(R1). 새 프로세스 받기: 새 메시지 REJOIN을 받기 루프(hr 4164–4243 / hw 4189–4268)에서, 붙잡은 상대에게서만, nonce가 맞고(초기화 재생으로 같은 nonce) 화신 번호 = 지금 + 1일 때. 아직 붙잡지 않은 rank는 REJOIN을 닫고, 예비 프로세스는 시한까지 다시 건다(V6). 받으면 `gone`, `deadJudged`, `refusals`, `left`, `peerFailed`, `failedPending`, `lostCause`, `closeCause`, `lostAfterCommit`(2.4절, 2026-10-09)를 지우고, 옛 주소로 진행 중이던 `dialFd`/`pendFd`/`probeFd`를 닫고(늦은 ECONNREFUSED가 새 화신의 죽음으로 세어지지 않게, hr 4032–4036 / hw 4057–4061), 공통 연결 세대를 정해 `gdakiTsInstall`(hr 3859–3872 / hw 3884–3897; F22). 펜싱(F11): HELLO, HELLO-ACK, PROBE-ACK에 화신 번호를 싣고 생존 rank는 지금 화신이 아니면 받지 않음. 예비 프로세스는 설치되기 전에는 REJOIN 말고 아무것에도 답하지 않고, 원래 rank의 listen 주소(기록에 있음)와 다른 포트에 묶음. REJOIN은 고정 크기 제어 메시지이고, rkey 목록 같은 큰 것은 자료 소켓으로(F23) | 감지 | L. hw 변경 없음 |
| D5 | 감시(S4) | 펌웨어 단계 초과 → 그 상대의 단어 + 비동기 오류 + 책임(그 상대, Local)(hr 3476–3516 / hw 3501–3541, 책임 hr 3505 / hw 3530). 라운드 25 s 초과, 기록이 쌓였는데 helper가 1 s 넘게 정지 → 드러냄, 이후 모든 라운드 거절(hr 3517–3525 / hw 3542–3550) | 같음. 다만 붙잡은 상대에 대한 펌웨어 초과의 책임 원인은 PeerDead로 적음(G9: 안 그러면 Local 책임이 남아 fallback 뒤 shrink 넘기기가 −3을 돌려줌, V1). 복원 기다림은 라운드가 아님(heartbeat 계속). 복원 상태 기계의 한 걸음은 1 s보다 짧게: 소켓 읽기, 로그와 이미지의 NIC 읽기는 조각으로(고정 사본 크기 = max(CQ 크기 × 64 B, 장치 QP 구조) + 4 KiB, hr 1899–1901 / hw 1900–1902), 기록은 흡수되어 쌓이지 않음(F14). hold 시작과 복원 라운드는 `gdakiTsBusy` 안. 복원 시한은 이 감시 스레드가 지킴(G8, V5): helper가 다른 라운드에 묶여 있어도 시한에 HELD에서 CAS(HELD → TIMED_OUT)에 이기면 그 상대의 단어(PEER_DEAD), 비동기 오류, 책임(PeerDead), degraded 예약을 CPU 쓰기로(hw 감시처럼 `gdakiTsToComm` 안에서) 하고(PUBLISHED에서는 CAS로 상태만, P1), 게이트 실패 쓰기와 FAIL은 helper가 풀리면 fallback 거절로 마저 함(이중 거절은 무해: 단어의 first, degraded의 `deadMs`, 책임의 중복 막기, `!pe.declined`; 검토 2 확인). COMMITTING은 건드리지 않음(3절, N1) | 감시 | G8, G9, L |
| D6 | 장치의 포기와 훑기(S5) | 포기 → 거절(원인 Local, hr 5892–5893, 5898 / hw 5921–5922, 5927). 기록 유실 두 번 → 거절(hr 5894–5896 / hw 5923–5925) | 포기는 TOLD. 붙잡은 상대에 대한 훑기의 거절은 G2가 fallback(PeerDead)으로 바꿈(V1). 유실 검사: 흡수가 `handled`를 올리므로 보통은 조용함. 장치 기록 우편함이 넘친 경우 HELD, COMMITTING의 상대는 건너뜀 | 장치 실패(TOLD) | G2, G5 |
| D7 | NVSHMEM t1w FIN 판정(S6) | BYE 없는 FIN → 바로 `t1_decline` | NVSHMEM에는 hold가 없음. hold 정책의 프로세스는 NVSHMEM을 쓰지 않음(X6) | NVSHMEM fail-fast | 없음(제약) |

### 4.2 반응

| # | 장치와 코드 | fail-fast | hold-for-restore | 우선 | 바꿀 것 |
|---|---|---|---|---|---|
| R1 | 거절 `gdakiTsDecline` hr 4916–4966 / hw 4941–4991: 범위 ALL(hr 4919 / hw 4944), 준비 풀기(hr 4930 / hw 4955), QP를 ERR로(hr 4931–4934 / hw 4956–4959), 책임 기록, 상대 단어, 비동기 오류(hr 4936–4943 / hw 4961–4968), FAIL, 게이트 실패(hr 4959–4965 / hw 4984–4990). 죽음이 이 함수에 오는 길: helper 루프(hr 6095–6101 / hw 6380–6386), 라운드의 죽음 길(hr 5478–5489 / hw 5507–5518). 라운드 안의 소켓 끊김(hr 5566–5572, 5594–5600 / hw 5595–5601, 5623–5629)은 보통 거절이 아니라 취소(`gdakiTsCancelRound` hr 5127–5146 / hw 5152–5171, 응답 쪽 `gdakiTsCancelResponder` hr 5152–5173 / hw 5177–5198)로 가서 상대를 "모름"으로 두고 기록을 다시 줄에 세움. 죽은 상대는 다시 걸기와 탐침의 거절 둘로 죽음이 되고, 다시 줄에 선 기록의 라운드(죽음 길)나 helper 루프에서 거절로 옴 | 위 모두 | 거절 맨 앞의 정책 hook(G2), 두 갈래: (가) 그 상대가 이미 붙잡은 상대면 어떤 거절이든(원인, `uaWhy` 무관) fallback 함수 하나로: PeerDead, `GDAKI_UA_PEER_DEAD`로 한 번 거절하고 다시 붙잡지 않음(V1). (나) 붙잡지 않은 상대: 정책 hold, 상대 ARMED, 강한 죽음 증거(2.4절), TOLD 아님 → 3절의 hold 시작, 돌아감. 그 밖은 거절 그대로 | 2.4절 | G2 |
| R2 | 상대별 abort 단어(hq, `gdakiUaRaisePeer` hr 2793–2862 / hw 2800–2869; 배열 hr 2705–2755 / hw 2712–2762). 장치: `tsWaitWord` gin_gdaki.h 241–245, `tsParkStable` 271–277, `tsPoll` 1123–1139, 보내기 `tsPosterAbortWord` 223–228, `tsQpWordError` 230–233 | 거절이 그 상대의 단어를 바로 올림: 그 상대 QP의 대기, flush, 쉬는 보내기가 바로 실패 | 복원 중에는 올리지 않음. 쉬는 스레드는 64번마다 단어를 읽지만 0이라 계속 쉼(hold 한도까지, T4). fallback(또는 G8의 시한)에서 올림. 단어는 communicator마다라서 문맥이 둘 이상이면 무장하지 않음(2.3절, F6) | 2.4절 | 없음 |
| R3 | degraded(hr 2826–2840, 2867–2894 / hw 2833–2847, 2874–2901; `NCCL_GIN_TS_DEGRADED_MS` hr 2690 / hw 2697), "모든 상대 거절" 규칙(hr 2813–2824 / hw 2820–2831) | 첫 죽음 거절(PEER_DEAD) 2 s 뒤 칸 0: `waitSignal`, `waitCounter`, 배리어가 오류. 랭크 2개는 바로. 원인 Unknown의 거절(3절의 응답 쪽 Commit 뒤 길)은 degraded를 예약하지 않음(hw의 틈). gpu-detect가 고친 뒤(2.4절 `pe.lostAfterCommit`, 2026-10-09)에는 그 길의 죽음 판정이 PEER_DEAD 거절이 되어 degraded를 예약함 | 복원 중에는 예약 없음. fallback 거절(PEER_DEAD) 또는 G8이 예약 → 칸 0은 fallback + 2 s(랭크 2개는 fallback 때 바로) | 2.4절 | 없음 |
| R4 | `NCCL_GIN_TS_DEGRADED_ROUNDS`(hw M-C, `gdakiUaPeerRaised` hw 2918–2925, 변수 2676) | 0(기본): 칸 0이 오르면 어느 상대와도 라운드 게시 없음, 그 거절은 원인 Local | hold 자체는 칸 0을 올리지 않으므로 이 규칙은 복원 중 잠자고 있음. 복원 중 칸 0이 다른 이유로 오르면(abort, revoke, shrink, 모든 상대 거절, 다른 rank의 죽음의 degraded) 복원 라운드의 게시 전 확인(`gdakiTsRepostPlanAll` hr 4566 / hw 4591, `gdakiTsRepostApply` hr 4708 / hw 4733)이 막음 → fallback | 칸 0(TOLD) | 없음. fail-fast의 변수로 문서화 |
| R5 | 비동기 오류와 문맥의 sticky 오류(거절이 세움 hr 4939–4942 / hw 4964–4967; `tsFail` gin_gdaki.h 1047–1053; Commit은 helper 안에서 지우지 않음 hr 2492–2512 / hw 2493–2513) | 거절 때 비동기 오류. sticky는 실패한 장치 스레드가 그 문맥에 세움 | 복원 중에는 비동기 오류 없음. 비동기 오류가 서 있거나 그 상대의 QP에서 장치 스레드가 실패했으면 TOLD → hold 안 함 | TOLD | 없음 |
| R6 | t1w fail-stop과 장치 대기 단어(ibgda.cpp `t1w_after_decline` 6841–6858, `t1w_failstop_exit` 6813–6839, `t1_decline`의 호출 6925, 변수 8047–8049; 장치 `nvshmemi_t1w_aborted` wait_until.cuh 41–56) | 0(기본): 거절 직후 `_exit(70)`. −1: 장치 대기 단어를 올려 PE의 모든 대기를 "풀린 채" 돌려줌. 양수: 단어를 올리고 그만큼 뒤 종료 | NVSHMEM에는 hold가 없음. 이 변수들은 NVSHMEM fail-fast 반응의 변수다. NVSHMEM에 hold를 넣는다면 `t1_decline`의 맨 앞에 G2와 같은 hook을 두는 것이 같은 구조다(범위 밖) | NVSHMEM fail-fast | 없음(문서화). X6 |

### 4.3 복구 기계

| # | 장치와 코드 | fail-fast | hold-for-restore | 우선 | 바꿀 것 |
|---|---|---|---|---|---|
| M1 | 라운드: 쌍 범위와 전체 재설정(`gdakiTsDecideScope` hr 3315–3375 / hw 3340–3400), NACK 12(hr 5611–5619 / hw 5640–5648), 범위 충돌(hr 5639–5653 / hw 5668–5682), 커밋 전 계획과 NACK 15/16(hr 4542–4570, 5621–5627 / hw 4567–4595, 5650–5656), 중첩 응답 라운드(`gdakiTsServeLower` hr 5315–5378 / hw 5341–5407, hw M-A: 한 번에 하나), 미룬 REQ(hr 6023–6056 / hw 6308–6341). 모르는 메시지 종류: 시작 쪽 ACK 기다림이 무시(hr 5685 / hw 5714), 미룬 REQ 뒤 무시(hr 6048 / hw 6333), 기다림 안 응답이 무시(hr 5373 / hw 5402), 응답 쪽 DONE 기다림은 살아 있는 상대를 거절(hr 5284–5286 / hw 5309–5311) | 그대로 | 살아 있는 상대와는 그대로(복원 중에도). 라운드 도중의 죽음은 R1. 새 제어 메시지(CKPT_*, HOLDING, DISARM, NOHOLD, FALLBACK, RESTORED)는 설치된 소켓으로 오므로 위의 모든 기다림에서 버리지도, 거절의 이유로 삼지도 않고 그 상대 칸에 미룸(F7 (a)). REJOIN은 listen 소켓으로 와서 받기 루프까지 backlog에 남음. 제어 메시지는 고정 크기이고 helper 스레드만 씀(`gdakiTsPumpRaw`가 정확히 한 레코드를 읽고 magic을 봄 hr 3657–3679 / hw 3682–3704: 섞이면 BADMAGIC → 죽음, F7 (c)) | 라운드(살아 있는 상대) | L |
| M2 | 정확히 한 번: 응답 쪽 실행 수(`gdakiTsExecuted` hr 4330–4348 / hw 4355–4373, 화신마다 mod 2^24 hr 4342 / hw 4367; `gdakiTsBaseline` hr 4351–4367 / hw 4376–4392, 2RST가 rmsn을 0으로 안 할 수 있음 hr 4361–4363 / hw 4386–4388), 다시 보내기 계획과 적용(hr 4552–4897 / hw 4577–4922), 장치의 `lbase` 다시 매핑(`tsPoll` gin_gdaki.h 1086–1095), 비메시지 표시(`gdakiTsNonMsg`, 라운드가 거절에 씀 hr 5548, 5810 / hw 5577, 5839; 게시 때 지움 hr 4875 / hw 4900; get은 READ 표시 gin_gdaki.h 709) | 상대가 REQ/ACK로 알려 준 rmsn으로 실행 안 된 WQE를 다시 보냄 | 죽은 쪽 QP는 없어 QUERY_QP를 못 함. (a) 생존 rank → 죽은 rank: SQ에서 다시 보내지 않고 모든 옛 WQE를 실행된 것으로(계획 `U = S, n = 0`: `lbase += S`), 효과는 생존 rank의 로그를 예비 프로세스에 적용해 넣음. 순서와 번호는 로그 항목 번호와 통로의 누적 메시지 수. 복원 라운드는 게시 전에 `gdakiTsNonMsg`를 읽어 READ(또는 get이 남았다는 DUMP)가 있으면 fallback(F2). 생존 rank가 p로 get을 내면 그때 DISARM(p)(2.3절). (b) 죽은 rank → 생존 rank: 생존 rank의 응답 쪽 QP는 남아 있어 누적 실행 수 X를 읽음. 누적은 화신마다의 증분(mod 2^24)을 감시의 QUERY_QP(G7)와 기준 바꿈(Baseline) 때마다 더해 만들고, 복원 라운드는 2ERR 뒤, Commit 전에 한 번 더 읽음(F19). 표본 사이에 한 QP로 2^23개보다 많은 메시지가 오면 wrap을 놓치므로 이 율을 무장 조건의 한계로 적음(V14 `[추론]`). 억제 예산 X − P. 단위는 RC 요청 메시지. (c) 되살린 rank의 get(V7): READ도 응답 쪽 MSN에 들어 X − P에 섞이고 생존 rank는 WRITE와 가르지 못함 → 결정성 요구(EXPERIMENT.md 9.7절 8번, 검사하지 않는 application 요구). 억제 느린 길이 예산이 남은 QP에 들어온 get을 직접 실패로 표시하고(예산이 남은 동안의 get은 게시 전에 억제 길로 오므로 READ 표시 gin_gdaki.h 709는 서지 않음), 예비 프로세스의 helper가 그 표시를 보면 복원 실패(FALLBACK(p)). NOP, DUMP는 메시지가 아니라 예산을 쓰지 않음 | 복원 | L, G7 |
| M3 | 낡은 기록 검사(hr 5431–5435 / hw 5460–5464), 범위 판단의 산 기록 검사(hr 3336 / hw 3361), hw 감시의 에폭 비교(D2)와 장치의 에폭 회계(`tsPoll` 1106–1116: 에폭이 바뀌면 `notEpoch`로 쉼) | 빈 라운드 없음 | 체크포인트의 입력 멈춤은 에폭을 홀수로 했다가 +2로 게시(빈 라운드: 같은 짝수로 돌려놓으면 `notEpoch`로 쉬던 대기가 hold 한도까지 쉬다 포기함). 그러면 에폭을 쓰는 모든 비교가 빈 라운드를 진짜 라운드로 봄 → 모두 `coveredEpoch`(진짜 라운드와 거절만 올림; 복원 라운드의 게시도 진짜 라운드라 올림)로(F12). 빈 라운드는 `nonmsg`와 `swErr`를 지우지 않음(멈춤 전에 낸 get이 날아가는 중이면 잊지 않게, V17). fail-fast에서는 빈 라운드가 없어 `coveredEpoch == epoch` | 정확성 | G6, L |
| M4 | Prepare/Commit(`ncclGinRecoverPrepare` hr 2143–2330 / hw 2144–2331, Commit hr 2334–2529 / hw 2335–2530; 토큰 검사 hr 2350–2369 / hw 2351–2370, 다시 연결 hr 2450 / hw 2451, drain hr 2257–2303 / hw 2258–2304, 새 PSN hr 2308 / hw 2309) | 살아 있는 상대와의 라운드 | 복원 라운드: Prepare(p)(2ERR은 hold 시작에서 이미, drain: 죽은 상대로 간 WQE는 flush 오류 CQE로 끝남 `[추론, 미확인]`), `rq.exch`를 예비 프로세스의 끝점으로(`opMu` 안; 토큰 검사가 `rq.exch.qpn`을 보므로 먼저), Commit. 양쪽 토큰 교환(F10)의 차례: REJOIN(예비 프로세스의 QPN, 보내기 PSN) → 생존 rank Prepare → 생존 rank 토큰(QPN, 새 보내기 PSN)을 예비 프로세스에 → 예비 프로세스가 그 PSN으로 자기 QP를 RTR/RTS로 잇고 READY → 생존 rank Commit(예비 프로세스의 PSN을 받는 PSN으로), Baseline, rkey 바꿈, 게시 → DONE_RS. 예비 프로세스는 초기화 재생 때 QP를 만들기만 하고 잇지 않는다. 새 QPN이 기록의 죽은 QPN과 같은지 보고 남김(같은 NIC의 QPN 재사용 `[미확인]`; 생존 rank의 QP는 hold 시작에서 ERR이라 옛 패킷을 다시 보내지 않음) | 복원 | L |

### 4.4 한도와 감시

| # | 장치와 코드 | fail-fast | hold-for-restore | 우선 | 바꿀 것 |
|---|---|---|---|---|---|
| T1 | 확대 상한 8회/60 s(`gdakiTsEscalated` hr 5081–5102 / hw 5106–5127; 쓰는 곳: 시작 쪽 hr 5444, 5503–5508 / hw 5473, 5532–5537, 응답 쪽 hr 5786 / hw 5815; 멈춘 표시 hr 5083–5086 / hw 5108–5111) | 그대로 | 살아 있는 상대의 라운드는 그대로 셈. 복원 라운드와 빈 라운드는 복구 라운드가 아니므로 세지 않음(`count = false`). 상한으로 멈춘 문맥은 무장하지 않음(2.3절, F26) | 상한 | L |
| T2 | 펌웨어 단계 감시(D5) | 그대로 | 복원 라운드의 펌웨어 단계(2ERR, 2RST, INIT/RTR/RTS, Commit 전 QUERY_QP)는 가드 안 → 초과는 TOLD → fallback. 체크포인트와 누적용 QUERY_QP는 가드 밖(hw 감시와 같은 이유: 가드 안에서 SIGSTOP이 오면 감시가 산 쌍의 단어를 올림, gpu-detect 리뷰 M1; F21) | 감시 | L |
| T3 | 라운드 감시 25 s, 쌓임 감시 1 s(D5) | 그대로 | 복원 기다림은 라운드가 아님. hold 시작과 복원 라운드는 Busy 안. 상태 기계의 한 걸음은 1 s 안(D5) | 감시 | L |
| T4 | 장치 대기의 hold 한도(게이트 `waitMs` = `NCCL_GIN_TS_HOLD_MS` 30 000, hr 6820 / hw 7128; `tsParkStable` gin_gdaki.h 255, 278–294), `roundMs`는 `gdakiTsStart`에서 정함(hr 6741 / hw 7046), 재연결 기다림의 한도(hr 6773–6778 / hw 7081–7086), helper가 다른 일에 묶이는 시간(라운드 `roundMs`, 재연결 기다림 hr 5461–5472 / hw 5490–5501, 정지 `quiesceMs`) | 라운드를 기다리는 장치 스레드의 한도 | 쉬는 스레드의 시계는 게이트가 처음 홀수가 된 때부터 감(F13). HELD의 실제 시한 = min(hold 시작 + `NCCL_GIN_RESTORE_MS`, 게이트가 홀수가 된 시각 + `holdMs` − 복원 라운드 몫 − 여유). PUBLISHED의 시한은 게시 시각 + `NCCL_GIN_RESTORE_MS`(장치 대기가 붙잡혀 있지 않아 hold 한도 항이 없음, P1). 시한은 Q4 감시 스레드가 지키므로(G8) helper가 묶여 있어도 늦지 않음(V5). 관계 검사는 `gdakiTsStart`에서. 어기면 그 communicator는 fail-fast(WARN). 포기는 TOLD → fallback | hold 한도 | G8, L |
| T5 | 복사 한도 2 000 ms와 NIC 루프백(hr 1232, `gdakiRecCopyWait` 1388–1440, `gdakiLbXfer` 1586–1668 / hw 1232, 1388–1440, 1587–1669), 루프백 설정과 자체 시험(hr 6474–6735 / hw 6761–7040, hw L-C: NIC만으로 시험), MR 목록(`gdakiLbAddRange`는 설정 때만, CUDA driver 함수를 부름 hr 1498, 1508, 1522 / hw 1499, 1509, 1523; 잠금 없는 찾기 hr 1475–1479 / hw 1476–1480), MR이 없으면 스트림 복사(CUDA 호출, hr 1721–1729 / hw 1722–1730; 묶임 hr 1377–1386 / hw 1377–1386), NIC 경로 끄기(`gdakiLbOff` hr 1483–1496 / hw 1484–1497) | 그대로 | 복원이 쓰는 GPU 메모리는 문맥을 만들 때만 루프백 MR에 넣음(실행 중 등록 없음, V12). 복원 라운드는 rkey 표와 신호 표의 칸 p를 모두 쓴 뒤 READ 하나로 GPU 메모리에 닿았음을 확인하고 나서 게시함(검토 3 W5, A1 (3)). 그 뒤 등록한 window가 있으면 무장 안 함(2.3절). 무장된 communicator에서 window 등록 해제(hr 7945 / hw 8264에서 rkey 표를 풂)가 오면 잠금 안에서 DISARM을 먼저 세우고, helper는 같은 잠금 안에서 그 표시와 `ts->stop`을 본 뒤에만 rkey 표에 씀(orphan helper 포함, F15). 풀린 rkey 표를 덮는 루프백 MR은 helper가 DISARM 때 해제(그 전까지 dmabuf 참조가 남는지는 `[미확인]`). `gdakiLbXfer`는 helper 스레드 하나만 씀(스테이징, 루프백 CQ). 자료 스레드는 호스트 버퍼의 소켓 입출력만(F14). NIC 경로가 꺼지면 fallback(V8) | 복사 한도 | L |

### 4.5 끝점과 메모리

| # | 장치와 코드 | fail-fast | hold-for-restore | 우선 | 바꿀 것 |
|---|---|---|---|---|---|
| A1 | rkey와 주소: window rkey는 등록 때 all-gather(`ncclGinGdakiRegMrSym` hr 7879–7931, all-gather 7902–7905 / hw 8198–8250, 8221–8224), 신호와 카운터 표의 교환(hr 7311–7315 / hw 7630–7634). 장치: 원격 주소는 window 안의 오프셋(gin_gdaki.h 475), rkey는 게이트 전에 읽음(476, 게이트 501; `signalKey`는 호출자가 계산해 값으로 넘김 1458–1468), `loadConst`는 보통 읽기(`utility.h` 449–457) | rkey는 communicator가 사는 동안 고정 | 예비 프로세스의 MR은 새 rkey. 생존 rank는 그 상대로 가는 게이트가 홀수인 동안 모든 window rkey 표와 신호, 카운터 표의 칸 p를 NIC 루프백으로 바꾸고 짝수 에폭을 게시. 그러나 키는 게이트 전에 읽히므로, 게이트가 홀수일 때 옛 키를 읽고 게시 뒤 빠른 경로로 들어간 보내기는 옛 키로 보냄(F5): 남의 MR이 그 키 값을 다시 받으면 조용한 손상 `[미확인]`. 해결은 키 읽기를 게이트에 들어간 뒤로 옮기는 것(DV3)이고, `signalKey`의 계산 자리를 옮기는 구조 변경과 읽기 종류의 변경(L1 적중을 잃을 수 있음)이 따름 → 5절 B4(이 문장은 결정 전의 것: 결정 (나)는 옮기지 않고 hold에서만 다시 읽음, 검토 3 W9). **결정 (나)(2026-10-09, 검토 3 반영)**: (1) 갈림과 자리: 측 표 포인터(DV1, `loadConst`로 게이트 전에 한 번; 문맥을 만드는 중 `gdakiTsStart`에서 한 번 쓰고 그 뒤 바뀌지 않음, 2.3절)가 0이 아니면, `tsGateEnter`가 참을 돌려준 뒤(빠른 길이든 느린 길 `tsGateEnterSlow`든) 키를 다시 읽어 덮어씀. `putImplMode`는 게이트(501) 뒤, 보내기 갈림(509) 앞에서 읽어 `tsTestSplitPut`(516)도 새 키를 씀. `raddr.key`(`dstMh->rkeys[peer]`)는 `hasWins`일 때만(신호만 보내는 길 526–533에서는 `dstMh`가 없을 수 있음), `sig_raddr.key`는 키 주소가 null이 아닐 때만 다시 읽음. `putValueImplMode`는 게이트(604) 뒤에 같은 것(window는 늘 있음). `getImplMode`도 게이트(704) 뒤에 `raddr.key`(`remoteMh->rkeys[peer]`, 697)를 다시 읽음(검토 3 W3: 복원을 건너는 커널의 get이 L1에 남은 옛 키를 쓰지 않게; 같은 포인터의 분기 하나). 다시 읽기는 L1을 거치지 않는 시스템 범위 relaxed 32비트 읽기(`ld.relaxed.sys`, 게이트 안의 다른 호스트 쓰기 칸을 읽는 `tsLoadRelaxedSys64` 390, 404, 769와 같은 종류; 쓰는 쪽이 NIC이므로; 검토 3 W4). (2) `signalKey`는 지금처럼 호출자가 계산해 값으로 넘기고(gin_gdaki.h 1458–1468, 1483–1494) fail-fast는 그 값을 씀. 호출자는 그 키를 읽은 주소(`signals_table.rkeys + peer`나 `signalMh->rkeys + peer`, 신호가 없으면 null)를 장치 헤더 안의 내부 인자 하나로 더 넘김(공개 API는 같음). (3) 차례의 근거: 생존 rank의 helper는 p로 가는 게이트가 홀수이고 개수가 0일 때 모든 window rkey 표와 신호 표의 칸 p를 NIC 루프백으로 쓰고, 다 쓴 뒤 READ 하나로 GPU 메모리에 닿았음을 확인한 다음(검토 3 W5; EXPERIMENT.md 9.3절 7단계, RL9, T5) `gdakiTsRepostApply`의 게시(hw 4906)로 짝수 에폭을 냄. 게이트에 든 스레드는 개수 0 전에 나갔거나 게시 뒤에 들어왔고, 진입은 acquire 원자 더하기(`tsWordEnter` 126–130)라 그 뒤의 strong 읽기가 앞당겨지지 않고 L1의 옛 줄을 보지 않으므로 새 키를 읽음 `[추론]`. (4) fail-fast(포인터 0): 키 읽기의 자리, 종류(`loadConst`, L1 적중), 명령 차례가 지금과 같음. 더해지는 것은 put과 putValue에서 분기 하나(DV2와 같은 포인터 읽기)와 내부 인자 하나(검토 3 W8), get에서 포인터 읽기 하나와 분기 하나다(DV2는 get에 포인터 읽기를 더하지 않음, 검토 3 재확인 X3). 결과는 같다. (5) hold: 키를 두 번 읽고(호출자의 게이트 전 읽기는 버려짐) 게이트 뒤 읽기는 L1 적중을 잃음. 무장 전에도(문맥을 만든 때부터) 그렇다. 비용은 계층을 만들 때 4 KiB, 256 KiB에서 잼(EXPERIMENT.md LT1, LT2와 다시 읽기만 따로 재는 셀, 7절). (6) 억제(C6): 느린 길이 SUPPRESS로 내지 않으면 다시 읽기도 없음. 일부만 내거나(신호만) 그대로 내면 참을 돌려준 뒤 같은 자리의 다시 읽기를 지남. 억제는 예비 프로세스에서만 서고 그 프로세스의 생존 rank 키는 바뀌지 않으므로 다시 읽기는 같은 값을 읽음. C2의 coop에서는 게이트를 잡은 0번 스레드가 보내기 전에 읽음. (7) 다시 읽지 않는 것: 카운터 키(자기 rank 칸 493, 바뀌지 않음), flush의 mcst(로컬 lkey, 755). 상대 rkey를 읽는 장치 자리는 476, 592, 697, 1461, 1464, 1487, 1492뿐이고 DOCA의 한쪽 연산 도우미는 키를 값으로 받음(검토 3 W7). 투명 복구는 companion(카운터) QP가 있으면 켜지지 않으므로(hw 2180, 6446) hold에서 카운터 길은 쓰이지 않고, 카운터 표의 칸 p 바꿈은 해가 없는 헛일이다 | 복원 | DV3, 5절 B4 |
| A2 | get 표(Commit이 지움 hr 2436–2446 / hw 2437–2447) | 그대로 | 복원 라운드의 Commit이 그 상대의 get 표를 지움. get은 M2대로 없음 | 복원 | 없음 |
| A3 | GIN collComm 고리(gin.cc 138–229, 연결 231–259: 고리 이웃과 실제로 잇고 받음), helper 설정의 잇기와 받기(hr 6255–6308 / hw 6541–6594: 여기서만 `gated`, `addr`가 섬 hr 6281–6284, 6303–6306 / hw 6567–6570, 6589–6592; 게이트는 `gated` 상대에만 씀 hr 6813–6831 / hw 7121–7139) | rank 하나가 죽으면 고리가 끊겨 그 communicator에서 GIN 집합 교환(새 window 등록, devComm 생성)을 더 못 함 | 같음. 예비 프로세스의 GIN 초기화는 all-gather 대답뿐 아니라 고리 연결과 helper 설정의 잇기/받기도 건너뛰어야 하고, 그러면서 `gated`와 `addr`는 기록으로 세워야 함(안 그러면 게이트가 없어 투명 복구도 억제도 없음, V13). B1. host RMA proxy도 첫 window 등록에서 상대마다 hook 밖의 IB 연결을 맺으므로 꺼야 함(2.3절, B1 설계 검토 T1-1). 복원 뒤 새 GIN 자원은 범위 밖 | 범위 | B1 |
| A4 | LSA(devComm `lsaRank`, `lsaSize`, `comm__types.h` 35; `dev_runtime.cc` 392) | 해당 없음(GIN만) | 같은 노드의 rank가 LSA 팀이면 생존 rank의 devComm이 죽은 rank의 메모리를 load/store로 가리킴 `[추론]` | 막는 문제 | 5절 B2 |
| A5 | GPU 문맥 판(`NCCL_GIN_GDAKI_GPU_CONTEXT_VERSION` = 2, gpucontext.h 19; 장치는 컴파일된 크기로 문맥을 셈 gin_gdaki.h 466) | 그대로 | 측 표 포인터 칸(DV1)이 `ncclGinGdakiGPUContext`의 크기를 바꿈 → 옛 헤더 바이너리가 contextId ≥ 1을 잘못 읽음(F17). 판을 3으로 올리고 판 2 formatter를 남김(판 1처럼, gpucontext.cc 37–45). 판 2 바이너리는 fail-fast | 호환 | DV1 |

### 4.6 application과 정리

| # | 장치와 코드 | fail-fast | hold-for-restore | 우선 | 바꿀 것 |
|---|---|---|---|---|---|
| P1 | `ncclCommRevoke`(init.cc 3463), `ncclCommAbort`(3521), 중단 shrink(3796) → `ncclGinTsUserAbortRaise` hr 2760–2788 / hw 2767–2795; 정리 `ncclGinGdakiTsCommTeardown` hr 6962–7084 / hw 7274–7403, `gdakiTsStop` hr 7086–7105 / hw 7405–7424, `gdakiTsFree` hr 7106–7134 / hw 7425–7453, orphan helper(hr 6936–6956, 6984–6992 / hw 7248–7268, 7296–7304) | revoke, abort, shrink는 모든 단어를 올림. 정리는 helper를 멈춤 | 같음. 복원 중이면 CANCELLED, 예비 프로세스에 BYE. 복원 라운드 중이면 그 라운드는 정지(`ts->stop`)로 거절. orphan helper는 rkey 표 쓰기 전에 `ts->stop`을 봄(T5) | application | L |
| P2 | 원인 기반 shrink 넘기기(`gdakiBlameNote` hr 841–898 = hw: Local 같은 이 rank 쪽 원인이 하나라도 있으면 질의가 −3, 상대 쪽 원인은 상대 목록; 거절의 기록 hr 4937 / hw 4962; 질의 init.cc 3572–3640) | 죽은 상대의 거절이 원인 PeerDead로 기록 → 그 상대를 빼는 중단 shrink는 GIN 오류를 넘어감. hw: degraded 뒤 건강한 쌍의 거절은 원인 Local → 넘기기 실패 | 복원 중에는 거절이 없어 기록도 없음. 붙잡은 상대에 대한 거절과 펌웨어 초과의 책임은 G2, G9로 PeerDead → fallback 뒤의 책임 기록은 fail-fast와 같음(V1). application이 복원 중 (자기 시한으로) shrink하면 P1로 취소되고, 부모에 GIN 오류가 없으므로 넘기기 검사가 필요 없음 `[추론]` | application | G2, G9 |
| P3 | 정상 정리의 bootstrap 배리어(`ncclCommDestroy`/`Finalize`가 abort 단어 0일 때 노드 안 배리어, init.cc 3171–3194) | 그대로 | 배리어에 든 되살린 rank의 bootstrap 끝점은 옛 프로세스의 것이거나 재생으로 만든 것 → 멈추거나 오류 `[미확인]`(F16). 복원한 communicator는 `ncclCommAbort`로 끝내야 함(application 요구, EXPERIMENT.md 9.7절) | application 요구 | 문서 |
| P4 | 통계 API(`ncclGinGetRecoveryStats` hr 7135– / hw 7454–) | 그대로 | 복원, fallback, 취소, 체크포인트, 억제 수를 더함 | 없음 | L |
| P5 | 신호와 카운터의 초기화(`ncclGinApi_ResetCounter`, `ResetSignal` gin_gdaki.h 1507–1527) | 그대로 | 재실행하는 rank가 다른 rank가 더하는 신호를 지우면 재실행 전에 적용한 로그의 더하기를 지움(F24) → 결정성 요구 | application 요구 | 문서 |

### 4.7 빌드와 규약

| # | 장치와 코드 | fail-fast | hold-for-restore | 우선 | 바꿀 것 |
|---|---|---|---|---|---|
| B1x | 운영과 연구 빌드(`GIN_TS_NOTE` hr 82–85 = hw; 시험 스위치는 `#ifndef NCCL_GIN_TS_PRODUCTION` 블록, hr과 hw에 20개) | 그대로 | 정책과 복원은 두 빌드에 같음. 시험 스위치만 연구 빌드 | 규칙 | L |
| H1x | helper 메시지 규약(종류 hr 2932–2934 / hw 2945–2947, 형식 hr 2953–2967 / hw 2966–2980; 모르는 종류는 idle 루프가 무시 hr 6081–6082 / hw 6366–6367) | 그대로(새 종류는 오지 않음) | 새 종류(CKPT_PAUSE, PAUSED, BUSY, CKPT_RESUME, CKPT_STABLE, DISARM, NOHOLD, HOLDING, FALLBACK, ACTIVATE, REJOIN, READY, DONE_RS, RESTORED, LOG_REQ)와 NACK 이유 17. 모두 고정 크기, helper만 씀. 모든 rank가 같은 빌드, 같은 정책이어야 함(설정 all-gather에서 확인). 모든 기다림에서 미룸(M1) | 규약 | L |

### 4.8 외부

| # | 장치 | fail-fast | hold-for-restore | 우선 | 바꿀 것 |
|---|---|---|---|---|---|
| X1 | PyTorch ProcessGroupNCCL 감시와 시간 제한, NCCL 자체 시간 제한, 장치 대기의 호출자 시간 제한(gin_gdaki.h 265, 1078, 1112: 쉬는 동안에도 감) | application이 2 s 안에 오류를 봄(degraded) | 복원 동안 생존 rank의 스트림이 GIN 커널에 묶임. 복원 시한(20 s)이 감시 한도보다 짧아야 함. 기본 한도는 이 환경에서 확인하지 않음 `[미확인]`. 시간 제한을 준 장치 대기는 복원 중 `ncclTimeout`으로 돌아올 수 있음(실패가 아니라 그 연산이 나중에 끝날 수 있다는 뜻, F25) → application의 장치 시간 제한도 복원 시간보다 길어야 함 | application의 감시 | 문서 |
| X2 | GIN 밖의 NCCL collective, NCCL P2P, LSA | 그대로 | 로그되지 않음. 복원한 communicator에서 되살린 rank와는 GIN 장치 통신만 됨(collective 전송, proxy 연결은 새 프로세스로 다시 잇지 않음). 쓰면 멈추거나 오류 | 범위 | 문서 |
| X3 | NCCL RAS | 죽은 rank를 보고 | 되살린 rank를 모름: RAS 보고가 어긋날 것 `[추론, 미확인]` | 범위 | 문서 |
| X4 | `NCCL_MULTI_RANK_GPU_ENABLE`(init.cc 73, 1307–1309) | 그대로 | 예비 프로세스도 같은 GPU의 셋째 프로세스로 이 변수가 필요. GPU 시분할로 예비 프로세스의 일이 느려짐(복원 시간에 잼) | 규칙 | 실행기 |
| X5 | NCCL의 shrink, grow, revoke, abort(`nccl.h.in` 321–363) | application의 회복 수단 | 복원 중 이 호출이 오면 P1로 취소. grow는 새 communicator와 새 devComm을 만들어 도는 커널을 지키지 못하므로 복원을 대신하지 못함 | application | 없음 |
| X6 | 같은 프로세스의 NVSHMEM t1w(R6, D7) | NVSHMEM은 FIN 판정 뒤 `_exit(70)`(기본) | `FAILSTOP_MS=-1`과 `FIN_DEATH=0`으로도 죽은 PE에 대한 거절은 다른 길(RETRY_EXC와 FIN의 `t1_fault`, 포기)로 일어나고, −1이면 거절마다 PE 전체의 대기 단어가 올라 붙잡힌 커널 안의 NVSHMEM 대기가 자료 없이 풀림(V15) → 제약: hold 정책의 프로세스는 NVSHMEM을 쓰지 않음(EXPERIMENT.md 9.7절 6번). 실행기가 확인 | 프로세스 종료가 이김 | 실행기 검사 |

### 4.9 복원 구성 요소

| # | 구성 요소 | fail-fast | hold-for-restore에서 닿는 기존 장치와 규칙 |
|---|---|---|---|
| C1 | 체크포인트의 입력 멈춤(빈 라운드, EXPERIMENT.md 9.4절) | 없음(체크포인트 없음) | 생존 rank q는 `gdakiTsQuiesce`에서 2ERR만 뺀 차례로 멈춤: 게이트 홀수, 개수 0, 모아 둔 WQE의 doorbell(안 울리면 r의 drain이 끝나지 않음, F20). 에폭 회계(M3: `coveredEpoch`, `nonmsg` 유지), 확대 상한(T1, 세지 않음), 기다림의 메시지 미룸(M1), hold 한도(멈춤은 ms 단위), drain의 QUERY_QP(T2, 가드 밖). RESUME은 q가 그 상대를 거절하지 않았고, 멈춤 뒤 진짜 라운드가 없었고, 게이트가 아직 멈춤 때의 에폭일 때만 게시(`gdakiTsWordHiWrite`는 에폭 반쪽을 통째로 씀 hr 4270–4273 / hw 4295–4298: 거절의 HOST_FAILED를 지우면 안 됨, F7 (b)). 멈춤 중 그 쌍에 라운드가 돌면 라운드가 이기고 그 체크포인트는 버림. 멈춤 요청을 받은 rank가 라운드 중이거나 억제 예산이 남았으면 BUSY(P4). PAUSED는 "p에 대해 무장 가능"을 실음(2.3절). 억제 예산이 남은 rank는 체크포인트를 찍지 않음(V18) |
| C2 | 송신 쪽 로그(장치) | 꺼짐: 측 표 포인터가 0 | 측 표의 QP마다 "로그 켬" 낱말이 선 QP에서만 쓴다(검토 3 W2, 2026-10-09: 측 표 포인터 ≠ 0은 B4의 키 다시 읽기를 뜻하고, 로그는 따로 켬). 그 낱말은 helper가 그 QP의 게이트가 홀수이고 개수가 0일 때(체크포인트의 입력 멈춤, C1) NIC 루프백으로 쓰고 READ로 확인한 뒤에야 CKPT_RESUME의 짝수 에폭을 게시하므로(검토 3 재확인 X2) 로그의 시작과 절단점이 같은 자리다. q는 멈춤마다(PAUSED가 "무장 가능"이든 아니든) 아직 서지 않았으면 낱말을 세운다(로그가 더 쓰여도 해가 없음). 장치는 게이트 안에서 strong 읽기로 본다. DISARM은 낱말을 그대로 두거나 다음 멈춤에서 지운다(로그가 더 쓰여도 해가 없음). 게이트 안 기록(put 경로 gin_gdaki.h 458–547). 게이트 계수는 coop의 0번 스레드만 잡으므로(465, 501, 537) 0번 스레드가 계수를 잡은 채 자리를 잡고, coop 동기화 뒤 모든 스레드가 내용을 복사하고, 다시 동기화한 뒤 0번이 적고 보내고 나감(V19: 개수 0이 "항목이 다 적힘"을 뜻하게). 0번 스레드의 게이트 진입이 실패하거나 억제되면 coop 전체가 보는 "건너뜀" 깃발로 복사를 건너뜀. 추가 동기화는 측 표 포인터가 0이 아닐 때만. 넘침은 DISARM. 측 표 포인터 칸은 GPU 문맥 판 3(A5) |
| C3 | 예비 프로세스와 초기화 재생 | 없음 | NCCL bootstrap, GIN collComm 고리와 helper 설정(A3), `NCCL_MULTI_RANK_GPU_ENABLE`(X4). 막는 문제 B1 |
| C4 | REJOIN | REJOIN은 닫음 | 재연결 기계와 펜싱(D4) |
| C5 | 복원 라운드 | 없음 | hold 시작(3절), Prepare/Commit과 양쪽 토큰(M4), rkey(A1), `RepostApply`의 커밋 지점과 PUBLISHING(M2), 비메시지 확인(M2), 펌웨어 감시(T2), hold 한도(T4), 게시 전 확인(R4) |
| C6 | 예비 프로세스의 억제 | 없음 | 게이트 에폭 반쪽의 새 비트 SUPPRESS(`EPOCH_MASK` 30비트 → 29비트). 보내기만 이 비트로 느린 길에 감: 보내기의 열림 검사(`tsGateEnter` gin_gdaki.h 333)에만 넣고, 대기의 열림 검사(`tsPollEnter` 365)와 `tsParkStable`(264)은 그대로(공용 `tsWordOpen`에 넣으면 flush와 wait가 `tsTicketSlow` 382–386에서 끝없이 돎, F1). 장치가 에폭 반쪽을 값으로 쓰는 모든 자리에서 SUPPRESS를 지움: `tsPollEnter`가 저장하는 값(364–366), `tsPoll`의 비교(1106)와 기록(1107–1108), `tsSwErrReport`(1037), `tsLateFail`(206–207)(V4: 안 그러면 `reported`와 `handled`에 2^29가 붙어 그 QP의 다음 장애 보고가 막힘). 느린 길(`tsGateEnterSlow` 303–328)은 나가기와 쉬기 전에 억제를 먼저 처리. SUPPRESS는 예산을 쓰는 동안 에폭 반쪽의 모든 호스트 쓰기(정지 hr 4425, PUBLISHING 4731, 게시 4881, 거절 4963, 훑기 5871, 정리 7039 / hw 4450, 4756, 4906, 4988, 5900, 7351)에서 유지돼야 하므로 helper가 유일한 쓰는 쪽이고 쓸 때마다 OR함(F18; 거절과 훑기, 정리의 HOST_FAILED 쓰기에서 지워지는 것은 그 QP가 끝났으므로 무해). 보통 rank와 fail-fast에서는 이 비트가 서지 않음. B4 결정 (나)(2026-10-09)의 키 다시 읽기는 느린 길이 참을 돌려준 뒤(내기로 한 뒤)에 오므로 억제한 연산은 키를 읽지 않음(A1) |

### 4.10 gpu-detect 계층에 넣을 변경 (최소)

정책을 나누는 데 필요한 것만이다. fail-fast에서 모든 hook은 지금의 동작을 그대로 낸다(2.5절 (다)). 그래서 gpu-detect의 pilot과 예측은 이 변경으로
바뀌지 않는다 `[추론]`. 검토 2는 G1–G7이 fail-fast에서 hw와 같게 돈다고 확인했다(G1은 all-gather 레코드가 커지는 것만 다름, G4는 뒷정리를 지킬 때).
G8, G9는 검토 2 뒤에 더했다.

**hw (`gin_host_gdaki.cc`).**
- G1. 정책 칸과 변수: `NCCL_GIN_FAULT_POLICY`(기본 `failfast`)를 `gdakiTsSetup`(hw 6438–)에서 읽고 설정 all-gather(`gdakiTsAddr`, hw 6458–6518)에
  싣는다. rank마다 다르면 fail-fast(WARN). 문맥(`gdakiTs`)과 communicator 등록부(`gdakiUa`)에 둔다.
- G2. 거절 hook: `gdakiTsDecline`(hw 4941) 맨 앞에서 `gdakiPolicyOnDecline(r, peer, why, cause, uaWhy)`를 부르고, 참이면 돌아간다. 두 갈래는 R1. fail-fast에서는
  늘 거짓이다. 죽음과 붙잡은 상대에 대한 모든 거절이 이 함수로 모이므로 호출 자리는 고치지 않는다. 강한 증거 검사는 `pe.lostAfterCommit`도 본다(2.4절,
  2026-10-09): gpu-detect가 응답 쪽 Commit 뒤 길을 PEER_DEAD 거절로 고친 뒤에도 그 거절은 붙잡지 않는다.
- G3. 감시 hook: `gdakiDetWatchStep`의 상대 거르기(hw 6094)에 `|| !gdakiPolicyWatch(r, p)`. HELD, COMMITTING이면 거짓. fail-fast에서는 늘 참(감시함).
- G4. 기록 처리 hook: helper의 기록 처리 루프(hw 6399–6409)에서 `gdakiTsInitiate(r, f)`를 `if (gdakiPolicyRoute(r, f)) gdakiTsInitiate(r, f);`로 바꾼다
  (HELD, COMMITTING의 상대는 흡수, PUBLISHED의 상대는 낡은 기록이면 버리고 아니면 fallback을 표시하고 거짓, Q3; `ts->batch`, heartbeat, `nQueued`의 뒷정리는 그대로 돎, V16). fail-fast에서는 늘 참. Q4 감시 스레드의 경로 판단(`gdakiTsRoutes`)은 그대로.
- G5. 훑기 hook: `gdakiTsScan`의 유실 검사(hw 5923–5925)를 `gdakiPolicyWatch(r, p)`가 거짓인 상대에서 건너뜀. fail-fast에서는 늘 검사.
- G6. 에폭 비교의 기준: `gdakiDetQueued`(hw 6066)와 `gdakiDetWatchStep`(hw 6139)의 `qs[].epoch`를 `gdakiTsCoveredEpoch(s)`로. fail-fast에서는 빈 라운드가
  없어 `epoch`와 같다. 같은 바꿈을 hr에서 물려받은 비교(hw 5460, 3361)에도 한다.
- G7. 감시의 QUERY_QP가 받는 값: `doca_verbs_qp_query_seq`(hw 6111)에 rmsn 자리를 넘겨 `gdakiPolicyObserveRmsn(r, qp, rmsn)`에 전한다. fail-fast에서는
  아무것도 하지 않는 함수다(펌웨어 명령 수는 그대로).
- G8. 감시 스레드의 정책 걸음: `gdakiTsWatchdog`(hw 3488) 맨 앞, `gdakiUaDegradedStep` 옆에 `gdakiPolicyWatchdogStep(r)`. 복원 시한이 지난 붙잡은 상대에
  대해, HELD면 CAS(HELD → TIMED_OUT)에 이겼을 때 `gdakiTsToComm` 안에서 CPU 쓰기로 그 상대의 단어(PEER_DEAD), 비동기 오류, 책임(PeerDead), degraded
  예약을 하고(PUBLISHED면 CAS로 상태만 바꾸고 거절은 helper가, P1), helper가 나중에 fallback 거절로 마저 하게 표시한다(V5, N1). 정책 칸은 원자 칸이라 잠금을 잡지 않는다(N3).
  fail-fast에서는 붙잡은 상대가 없어 아무것도 하지 않는다.
- G9. 펌웨어 초과의 책임 원인: `gdakiTsWatchdog`의 책임 기록(hw 3530)에서 원인을 `gdakiPolicyBlameCause(r, peer, gdakiCause::Local)`로. 붙잡은 상대면
  PeerDead, 아니면 그대로(fail-fast에서는 늘 그대로, V1).
- 코드 변경 없음, 문서만: `NCCL_GIN_TS_DEGRADED_MS`, `NCCL_GIN_TS_DEGRADED_ROUNDS`는 fail-fast 반응의 변수다. hold에서는 거절(fallback)이 일어난 뒤에만
  효과가 있다. QP 감시의 변수(`QPWATCH_MS`, `GRACE_MS`, `NOCQE_MS`)는 감지의 변수라 두 정책에 같다(V14).

**정책과 별개로 찾은 hw의 틈(권고).** 응답 쪽이 Commit한 뒤 ACK 보내기 실패나 DONE 기다림 중 소켓을 잃으면(hw 5285–5292, 5298–5303) 죽음 판정 없이 원인
Unknown, `uaWhy` DECLINED로 거절하므로 degraded가 예약되지 않는다. 랭크 3개 이상에서는 그 상대를 기다리는 상대를 모르는 대기가 풀리지 않는다 `[소스,
추론]`. 그 두 자리에서 먼저 `gdakiTsSocketLost`로 판정하게 하면 FIN이 죽음으로 판정되어 helper 루프의 PEER_DEAD 거절로 간다. fail-fast의 동작을 바꾸는
고침이므로 gpu-detect가 정할 일이다. 고치기 전에는 이 창의 죽음은 hold에서도 fail-fast다(3절).

2026-10-09: gpu-detect가 이 틈을 고친다(병렬 작업, 메인 세션이 정한 계약). 그 두 자리에서 소켓을 잃은 자리에서(`gdakiTsSocketLost`를 부르기 전과 어느
돌아가기보다도 먼저, 검토 3 W10, X5) `pe.lostAfterCommit = true`를 세우고, 잃음이 죽음
판정이면 거절은 PeerDead, `GDAKI_UA_PEER_DEAD`(degraded 예약), 아니면 지금 그대로다. 복원 계층이 이 계약에 기대는 것은 둘이다: G2의 강한 증거 검사가 이
표시를 본다(2.4절, 붙잡지 않고 NOHOLD), REJOIN이 이 표시를 지운다(D4). 표시를 세우는 자리와 ACK 길의 errno에 대한 검토 3의 메모(W10, W11)는 2.4절에 적었다. 이 문서의 hw 줄 번호는 고치기 전 트리(diff md5 `be0ea9ed`)의 것이다. 고친 뒤 줄이 밀리면
계층을 만들 때 다시 맞춘다.

**t1w (NVSHMEM).** 코드 변경 없음. `NVSHMEM_IBGDA_FT_T1_FIN_DEATH`, `FAILSTOP_MS`, `FAILSTOP_CODE`는 NVSHMEM fail-fast 반응의 변수로 문서화한다.
NVSHMEM 정책은 fail-fast 하나다. hold 정책의 프로세스는 NVSHMEM을 쓰지 않는다(X6).

### 4.11 복원 계층의 변경과 fail-fast

- 복원 계층은 G2–G9의 hold 분기를 채운다. 그 밖에 같은 파일의 hw 코드에도 손을 댄다(EXPERIMENT.md 9.9절): 받기 루프의 REJOIN(RL6), 메시지 처리와 모든
  기다림의 미룸(RL11, RL17, M1), 낡은 기록 검사의 `coveredEpoch`(RL12), 확대 상한의 세지 않기(RL15), 누적 실행 수(RL13), hold 시작과 복원 라운드(RL1,
  RL4, RL7–RL9), 응답의 NACK 17(RL20). 이들도 fail-fast에서 같다: 새 메시지는 오지 않고, `coveredEpoch == epoch`이고, 세지 않기와 누적은 hold 경로에서만 부르고, 붙잡은 상대가 없어 NACK 17이
  나가지 않는다.
- 로그, 체크포인트, 예비 프로세스는 정책이 hold이고 그 communicator가 무장 조건(2.3절)을 갖추고 `ncclGinRestoreResume`을 부른 뒤에만 켠다. 로그를 켜는 것은 QP마다의
  "로그 켬" 낱말이다(C2, 검토 3 W2). 측 표 포인터는 hold 정책이면 문맥을 만들 때부터 0이 아니고 그때부터 키 다시 읽기(A1)가 돈다.
  fail-fast에서는 비용이 보내기마다 측 표 포인터를 한 번 보는 분기와 내부 인자 하나뿐이다(DV2, A1 (4)).
- 시제품은 멈췄다: 이 문서의 검토 전에 쓴 초안(로그 고리, 체크포인트 저장소, 복원 계획, CPU 모의)은 빌드도 실행도 하지 않았고, 저장소에 넣지 않고 세션
  스크래치 `agent_restore/proto_draft_unbuilt/`에 두었다. 시험 프로그램 `gin_rs.cu`는 쓰지 않았다. 초안의 억제 판정은 READ를 다루지 않으므로 다시 쓸 때
  M2에 맞춘다.

## 5. 열린 충돌 (막는 문제)

해결이 없거나 결정이 필요한 행이다. 하나라도 남아 있는 동안 복원 계층은 구현하지 않는다.

| id | 무엇 | 왜 막는가 | 풀 조건 |
|---|---|---|---|
| B1 | 예비 프로세스의 초기화 재생(C3, A3) | NCCL bootstrap, GIN collComm 고리 연결과 all-gather, helper 설정의 잇기/받기는 모든 rank가 함께 해야 한다. 기록된 결과로 대답하는 길이 NCCL 핵심의 초기화 전체(proxy, 런타임 연결, 대칭 메모리 등록)를 덮는지, 같은 devComm 모양을 만드는지, `gated`와 `addr`를 기록으로 세울 수 있는지 모른다 `[미확인]` | 초기화 재생 시험(빌드가 필요하므로 이 문서의 승인 뒤): 장애 없이 한 rank의 기록을 만들고, 예비 프로세스가 그 기록으로 초기화를 끝내 같은 rank, nRanks, 컨텍스트 수, 신호 수, window 크기, 모든 상대의 게이트를 얻는지. 2026-10-09: 시험 설계, 판정 기준, 코드가 검토를 거쳐 빌드됨, 실행 전(EXPERIMENT.md 9.15.4). 설계 검토로 host RMA proxy와 runtime connect, NVLS를 무장 조건에 더함(2.3절). **2026-10-09 시험 결과**: 2회 모두 예비 프로세스가 rank 0과 rank 1의 기록만으로 상대 없이 초기화, window 등록 둘, devComm 생성을 끝내고 다섯 항목(기록 정확 소비, 상대로의 connect 0, 같은 devComm과 window와 rkey, 모든 상대의 gated, addr, 게이트)을 통과했고 음성 대조 둘은 실패했다(EXPERIMENT.md 9.15.4, 12절). 그래서 B1의 "초기화 재생" 부분은 이 범위(2 rank, 노드 사이, lsaSize 1, host RMA와 RAS 꺼짐)에서 풀렸다. 남은 부분(REJOIN, 복원 라운드의 토큰 연결, rkey 바꿈, 4 rank와 노드 안 상대의 재생)은 계층을 만들 때 확인한다 |
| B2 | LSA 팀(A4) | GPU 하나를 두 프로세스가 나눌 때 devComm의 `lsaSize`가 1인지 모른다. 2 이상이면 생존 rank의 load/store가 죽은 rank의 메모리를 계속 가리키고, 이것을 고치려면 생존 rank에서 CUDA 가상 메모리 호출이 필요하다(생존 rank는 CUDA 호출을 하지 않는다는 원칙과 충돌) `[추론]` | `lsaSize`를 읽어 확인. 2 이상이면 LSA 팀에 든 상대는 무장하지 않음(그 상대의 죽음은 fail-fast)으로 해결한 것으로 본다. 2026-10-09: 기존 원자료에는 값이 없음, 확인 시험이 빌드됨, 실행 전(EXPERIMENT.md 9.15.2). **2026-10-09 풀림(해결 A)**: 복원 셀 배치(4 rank 번갈아, GPU마다 둘)에서 2회 모두 네 rank `lsaSize=1`, `nLsaTeams=4`(EXPERIMENT.md 9.15.2, 12절). 다른 배치를 지키는 장치로 "LSA 팀에 든 상대는 무장하지 않음" 규칙과 runtime connect, NVLS 조건(2.3절)은 그대로 둔다 |
| B3 | 체크포인트의 drain 확인(C1) | 응답 쪽 rmsn이 멈춤 때의 메시지 수에 이른 뒤 그 쓰기가 GPU 메모리에 보인다는 것은 NIC 루프백 READ 하나의 차례 보장에 기댄다. 그런데 window MR은 기본으로 relaxed ordering이다(`gdakiRegMr` hr 192 = hw, `NCCL_IB_PCI_RELAXED_ORDERING` 기본 2 net_ib/init.cc 11; strict는 `NCCL_WIN_STRICT_ORDERING`일 때만 gin_host.cc 556; 신호와 카운터 표는 strict hr 7311–7312 / hw 7630–7631). gin-remaining의 flush 근거는 그 계층 자신의 strict 루프백 MR이었다 `[미확인: 이 하드웨어]` | (가) 무장 조건으로 strict window를 요구하고(성능 비용을 잼), (나) NIC 게이트 시험과 같은 꼴로 relaxed와 strict에서 drain 뒤 사본이 맞는지 따로 잼. (나)가 끝나야 풂. 2026-10-09: (나)의 시험(READ 대상은 다른 할당의 fence 낱말, copy engine 복사, 꼬리 셋, 대조 둘)이 검토를 거쳐 빌드됨, 실행 전(EXPERIMENT.md 9.4절 3단계, 9.15.3). **2026-10-09 시험 결과: 열림(사용자 결정 대기)**. 셀 열둘 가운데 열이 통과했다(rain의 노드 사이와 같은 노드 셀 `ro`, `so`; sunny 여섯, sunny 경합 `so`는 다시 해서). 모든 실행에서 채점 fence 실패 0이다. rain의 GPU 경합 셀 둘은 두 번씩 대조(`early`, `boundary`)에서 늦은 낱말이 한 번도 없어 미결이고, 그래서 rain은 열림, sunny는 `ro`, `so` 모두 통과다. 대조가 힘을 잃는 것은 hog 프로세스와 GPU를 시간 나눔으로 쓰느라 복사가 늦게 시작하기 때문으로 본다 `[추론]`. 모든 셀에서 READ 없는 대조 길(`nofence`)도 실패 0이라 이 시험은 READ가 필요한지를 가르지 못한다. 결정 전까지 무장 조건 "window는 strict"(2.3절)는 그대로 둔다(EXPERIMENT.md 9.15.3 결과, 12절) |
| B4 | 빠른 경로의 키 읽기 자리(A1, F5) | 생존 rank의 보내기가 게이트가 홀수일 때 옛 rkey를 읽고, 게시 뒤 빠른 경로로 들어가면 죽은 rank의 rkey로 보낸다. 고치려면 키 읽기를 게이트 진입 뒤로 옮겨야 한다. `signalKey`는 호출자가 계산해 값으로 넘기므로 그 계산 자리를 `putImplMode` 안으로 옮기는 구조 변경이 들고, 보통 읽기(`loadConst`)를 게이트 뒤의 시스템 범위 읽기로 바꾸면 L1 적중을 잃을 수 있다(V2b). 이것은 "빠른 경로는 바꾸지 않는다"는 설계 원칙(EXPERIMENT.md 9.1절)과 충돌한다 | 사용자의 결정: (가) 모든 보내기에서 키 읽기를 게이트 뒤로(지연을 4 KiB, 256 KiB에서 잼), (나) hold 정책의 communicator에서만(측 표 포인터로 가르는 분기가 fail-fast에도 더해짐), (다) 복원을 포기. 결정 전에는 막음. **2026-10-09 사용자 결정: (나).** 설계는 A1과 EXPERIMENT.md 9.9절 DV3. 4 KiB, 256 KiB 지연은 복원 계층을 만들 때 잰다(LT1, LT2). 결정 뒤의 독립 검토는 6절 검토 3 |

## 6. 독립 검토

**검토 1**(읽기 전용 에이전트, 2026-10-09, 대상: EXPERIMENT.md 초안 9.1–9.11절과 hr 트리, hw diff). 새 막는 문제 0, 높음 6(F1–F6), 중간 9(F7–F15),
낮음과 중간-낮음 13(F16–F28), B3 정정 하나, 인용 오류 여섯.

| 지적 | 요지 | 자리 | 지적 | 요지 | 자리 |
|---|---|---|---|---|---|
| F1 | SUPPRESS를 공용 열림 검사에 넣으면 flush와 wait가 끝없이 돎 | C6 | F15 | rkey 표의 MR 등록 | T5 |
| F2 | 생존 rank의 get이 자료 없이 끝남 | M2, 2.3절 | F16 | 정상 정리의 배리어 | P3 |
| F3 | 되살린 rank의 READ, NOP, DUMP의 예산 | M2 | F17 | GPU 문맥 크기 | A5 |
| F4 | 응답 쪽 Commit 뒤 게시 전 죽음 | 3절(검토 2로 fail-fast로 바꿈) | F18 | SUPPRESS가 호스트 쓰기에서 지워짐 | C6 |
| F5 | 빠른 경로의 옛 rkey | A1, B4 | F19 | 실행 수 mod 2^24, Commit 전 읽기 | M2, G7 |
| F6 | 문맥마다 helper, communicator마다 단어 | 2.3절, R2 | F20 | 멈춤 중 울리지 않은 WQE | C1 |
| F7 | 체크포인트 메시지와 라운드의 기다림, RESUME, 고정 크기 | M1, C1, H1x | F21 | 체크포인트 QUERY_QP의 가드 | T2 |
| F8 | hold 시작이 모자람 | 3절 | F22 | REJOIN의 세대와 진행 중인 연결 | D4 |
| F9 | 죽음 증거가 약함 | 2.4절 | F23 | REJOIN의 크기 | D4 |
| F10 | PSN과 QPN | M4 | F24 | 신호 초기화 | P5 |
| F11 | 같은 nonce로 옛 HELLO/PROBE를 통과 | D4 | F25 | 장치 대기의 호출자 시간 제한 | X1 |
| F12 | 빈 라운드와 다른 에폭 비교 | M3, G6 | F26 | 상한으로 멈춘 문맥 | 2.3절, T1 |
| F13 | hold 시계의 시작 | T4 | F27 | 재연결 꺼짐 | 2.3절 |
| F14 | 쌓임 감시와 NIC 복사의 스레드 | D1, D5, T5 | F28 | 경로 판단은 Q4 감시 스레드 | D1, G4 |

그 밖: 예비 프로세스의 helper 설정과 collComm 고리 연결(A3, B1), window MR의 relaxed ordering(B3), 인용 고침(R1의 취소 길, M1의 REJOIN, B1x의 20개,
EXPERIMENT.md 9.3절의 `pe.addr`, T4의 `gdakiTsStart`).

**검토 2**(읽기 전용 에이전트, 2026-10-09, 대상: 검토 1을 반영한 이 문서와 EXPERIMENT.md 9.1–9.9절, hr, hw, nvs 트리). 지적 21개(V1–V20, V2b), 모두 해결안이
있고 B1–B4 밖의 새 막는 문제는 없다고 했다. 인용 확인: "hr N / hw M" 쌍 142개 불일치 0, 틀린 인용 하나(D5의 사본 크기). 반영:

| 지적 | 요지 | 자리 |
|---|---|---|
| V1 | 붙잡은 상대를 죽음 아닌 원인으로 거절하면 fail-fast와 결과가 다름(degraded 없음, Local 책임) | 2.2절, R1(G2 갈래 가), D5, D6, P2, G9 |
| V2 | EXPERIMENT.md DV4가 F1을 되살림 | EXPERIMENT.md 9.9절 DV4, C6 |
| V2b | DV3가 B4에서 막힌 방안, `signalKey`는 값으로 넘김, 읽기 종류 | EXPERIMENT.md DV3, A1, B4 |
| V3 | 응답 쪽 Commit 뒤 죽음은 강한 증거가 아님 → `S_pending`은 죽은 코드. hw의 degraded 틈 | 3절, R3, 4.10절 끝 |
| V4 | SUPPRESS가 장치의 에폭 값에 섞임 | C6, DV4 |
| V5 | 복원 시한을 helper 하나로 못 지킴 | D5, T4, G8 |
| V6 | 무장은 rank마다, 복원은 모두 | 2.3절, 2.4절, 3절, D4 |
| V7 | 되살린 rank의 get | M2 (c), EXPERIMENT.md 9.7절 8번 |
| V8 | NIC 복사 경로가 무장 조건에 없음 | 2.3절, T5 |
| V9 | zombie PID | 2.4절 |
| V10 | hold 시작이 Busy 밖 | 3절, T3 |
| V11 | 낡은 `lostCause` | 2.4절, D4, R1 |
| V12 | 실행 중 MR 등록, 등록 해제, orphan | 2.3절, T5, P1 |
| V13 | 예비 프로세스에 게이트가 없음 | A3, B1 |
| V14 | QP 감시 변수의 성격, 표본 조건 | 2.1절, 2.3절, M2, 4.10절 |
| V15 | NVSHMEM 둘째 선택지가 불완전 | X6, 2.2절 |
| V16 | G4의 `continue`가 뒷정리를 건너뜀 | D1, G4 |
| V17 | 빈 라운드가 `nonmsg`를 지움 | M3 |
| V18 | 억제 예산이 남은 동안 체크포인트 | C1 |
| V19 | 로그 내용 복사가 게이트 계수 밖 | C2 |
| V20 | 사실 불일치 12개(G 개수, `U = S`, 9.1절 그림 차례, 4.11절, destroy, 취소 뒤 길, 판정 WARN 줄, DV2의 시간, D5의 사본 크기, C6의 쓰기 목록, T1의 응답 쪽, X6과 2.3절) | 각 자리, EXPERIMENT.md 9.1, 9.3, 9.9절 |

**검토 2 재확인 1**(커밋 `6e3c1618` 대상). V1–V20 대부분 풀림. G1–G9는 정책 failfast에서 hw와 같음(조건 N5). 인용 쌍 164개 불일치 0. 새 충돌:
N1(높음, G8과 게시의 다툼 → 3절 CAS), N2(높음, 게시 뒤의 FALLBACK → 3절 PUBLISHED), N3(G9의 범위와 잠금 차례 → 3절 0단계, 원자 칸), N4(붙잡지 않고 거절한
rank의 알림 → 3절), N5(정책 hold 무장 전의 설정 차이 → 2.5절 (다)), V7의 남은 부분(→ M2 (c)), V9, V12, V19의 낮은 메모(→ 2.4절, T5, C2), EXPERIMENT.md에 남은
문장 일곱(→ 고침).

**검토 2 재확인 2**(커밋 `568af8c1` 대상). N1–N5, V7, EXPERIMENT.md 7문장 풀림, 인용 쌍 167개 불일치 0, fail-fast 동치 그대로(조건 N5). 새 충돌:
P1(높음, PUBLISHED에서 G8이 단어부터 올리면 거절의 차례가 깨짐 → G8은 PUBLISHED에서 상태만, 따로 된 시한), P2(RESTORED와 FALLBACK의 경쟁 → 화신 번호, 어느
상태든 거절), P3(PUBLISHED의 산 QP를 감시에서 뺌 → HELD, COMMITTING에만, PUBLISHED의 장애는 fallback), P4(억제 중 남의 체크포인트 → BUSY), P5(RESTORED 뒤
무장 조건 → ARMED 또는 OFF, PID 등록, DISARM 적용), P6(COMMITTING의 실패 → 바로 거절), P7(EXPERIMENT.md 그림, 9.3절 8단계, RL9). 모두 3절과 해당 행,
EXPERIMENT.md에 반영.

**검토 2 재확인 3**(커밋 `452e7cf4` 대상). P1–P7 풀림, 인용 쌍 169개 불일치 0, fail-fast 동치 그대로(조건 N5; 정책 failfast에서는 FALLBACK도 NOHOLD도
보내지 않음). 새 충돌: Q1(중간-높음, N4 방송과 "어느 상태든 FALLBACK이면 거절"이 겹쳐 산 상대를 모두가 거절 → NOHOLD로 나누고, FALLBACK의 거절은 그 화신을
붙잡았거나 되살린 rank만), Q2(PUBLISHED에서 RESTORED가 시한을 이김, 시한 ≥ roundMs + handshake), Q3(PUBLISHED의 낡은 기록 버림), Q4(Commit부터 CAS까지의
문장), Q5(예비 프로세스의 REQ에 NACK 17). 모두 3절에 반영.

**검토 2 재확인 4**(커밋 `70b23f28` 대상). Q1–Q5 풀림, 인용 쌍 171개 불일치 0(`gdakiTsRespond`의 끝 줄 하나 고침), fail-fast 동치 그대로(조건 N5).
남은 것 R1(낮음: 미룬 RESTORED보다 같은 상대의 REQ가 먼저 처리될 수 있음 → 같은 상대의 메시지는 도착 차례대로, NACK 17 전에 RESTORED 적용). 3절에 반영.

**검토 2 재확인 5**(커밋 `0af9190e` 대상). R1 풀림(두 길 모두 덮음; 미룬 FALLBACK을 기다림 안에서 처리하는 것은 hw가 FAIL을 그 자리에서 처리하는
방식 hw 5391–5397과 같은 꼴), `gdakiTsRespond` 끝 줄 확인, fail-fast 동치 그대로(조건 N5). **판정: 막는 문제 B1–B4 밖에 풀리지 않은 충돌 없음.**

남은 것은 5절의 B1–B4다. B4는 사용자의 결정이 필요하고, B1과 B3은 빌드가 필요한 시험이므로 이 문서의 승인 뒤에 한다.

2026-10-09 사용자 결정(검토 2 뒤): B4는 (나). B1, B2, B3은 실행 가능성 시험을 한다(시험 프로그램만 빌드, 복원 계층은 구현하지 않음; EXPERIMENT.md
9.15절). 같은 날 gpu-detect와의 계약 `pe.lostAfterCommit`(2.4절)를 넣었다. 이 두 변경의 검토는 아래 검토 3이다.

**검토 3**(읽기 전용 에이전트, 2026-10-09, 대상: 커밋 `60399e85`의 결정 (나)와 `lostAfterCommit` 계약, hw 트리). 막는 문제 0, 중간 3(W1–W3), 낮음 5, 메모 3.
계약 쪽: 같은 화신에 표시 없는 PEER_DEAD 거절이 올 수 없음, 붙잡은 상대는 이 창에 닿지 못함(모든 REQ가 `gdakiTsRespond`의 NACK 17을 지남), N4, Q1, V11,
R3, D4, P2와 맞음, REJOIN에서만 지워도 충분함. (나) 쪽: 차례의 논거는 맞음(W4, W5 제외), SUPPRESS와 coop와 충돌 없음. 반영(커밋 `daa63c69`):

| 지적 | 요지 | 자리 |
|---|---|---|
| W1 | 측 표 포인터를 쓰는 때가 없고 무장 조건에 없음(GPU 문맥은 hw 7966에서 `gdakiTsSetup` 전에 복사됨) | 2.3절(무장 조건, PAUSED), EXPERIMENT.md RL10, 9.6절 |
| W2 | 포인터 ≠ 0이 "키 다시 읽기"와 "로그 씀" 둘을 뜻함 | C2와 4.11절(QP마다 "로그 켬" 낱말), 2.5절 (다), EXPERIMENT.md DV1, DV2, 9.5절, 7절 비용 셀 둘 |
| W3 | get 키를 다시 읽지 않는 이유가 틀림(복원을 건너는 커널의 L1) | A1 (1), (7), EXPERIMENT.md DV3, 9.6절: get도 다시 읽음 |
| W4 | 읽기 범위가 두 가지로 적힘 | A1 (1): 시스템 범위 relaxed 32비트 |
| W5 | 쓰고 READ로 확인하는 걸음이 9.3절과 RL9, T5에 없음 | EXPERIMENT.md 9.3절 7단계, RL9, T5 |
| W6 | 신호만 보내는 길의 null, 자리(509 앞) | A1 (1), DV3 |
| W7 | 보내기 길 목록은 완전함, 카운터 길은 hold에서 쓰이지 않음 | A1 (7) |
| W8 | fail-fast의 변화는 분기 하나와 내부 인자 하나 | 2.5절 (다), A1 (4), 4.11절, DV3 |
| W9 | 결정 전 문장, 없던 절 참조 | A1, EXPERIMENT.md 9.6절(표시), 9.15절(만듦), 이 검토 |
| W10 | 표시를 세우는 자리: 잃은 자리에서, `gdakiTsSocketLost` 전 | 2.4절(메인 세션과 gpu-detect에 넘김) |
| W11 | ACK 길에서 errno를 `closeCause`로 먼저 옮겨야 거짓 죽음이 없음(gpu-detect 쪽) | 2.4절(메모) |

첫 판정: "W1, W2, W3(모두 중간, 문서로 고칠 수 있음) 밖에 풀리지 않은 것 없음. 계약에는 풀리지 않은 충돌 없음(W10의 문구와 W11 메모를 조건으로)."

**검토 3 재확인**(같은 에이전트, 대상: 커밋 `6b33627e`). W1–W11 모두 풀림. 새로 낮음 다섯: X1(무장 전 hold도 coop 추가 동기화를 치르고 첫 멈춤 뒤 로그를 쓸 수 있음 → 2.5절 (다), `lat_hold_unarmed`는 멈춤 없이), X2(로그 켬 낱말을 쓰고 READ로 확인한 뒤 RESUME → C2), X3(fail-fast의 get은 포인터 읽기 하나와 분기 하나 → A1 (4), `lat_ff_branch`에 get), X4(줄 번호 hw 7966, 포인터 쓰기는 동기, `host_buf`에도 → 2.3절), X5(표시 자리 규칙을 "잃은 자리" 하나로 → 2.4절, 4.10절 끝). 모두 반영했다. **판정: "결정 (나)와 `lostAfterCommit` 계약에 낮음 X1–X5 밖에 풀리지 않은 충돌 없음"**(X1–X5는 이 반영으로 닫음).

## 7. 참고

- [EXPERIMENT.md](EXPERIMENT.md) 9.1–9.9절(복원 설계, hook 목록)
- `../remaining/EXPERIMENT.md` 9절 1번 (c), (f)
- gpu-detect worktree `harness/gpu-detect/EXPERIMENT.md` 9.1절(hw), 9.2절(t1w), 18, 19절
