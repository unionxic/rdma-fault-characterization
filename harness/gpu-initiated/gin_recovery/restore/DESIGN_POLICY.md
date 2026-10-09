# 장애 반응 정책: 감지와 반응을 나눈 통합 설계 (gin-restore, gpu-detect)

**목적:** gpu-detect 계층(GIN `hw`, NVSHMEM `t1w`)이 섞어 둔 "장애 감지"와 "fail-fast 반응"을 나누고, gin-restore가 요구하는 반대
반응(대기를 붙잡고, degraded 해제를 막고, 새 프로세스를 같은 논리 rank로 받아 재실행)을 communicator마다 고르는 정책으로 넣었을 때, 기존
장치와 충돌이 남지 않는지 한 표로 정리한다.

| 항목 | 값 |
|---|---|
| 상태 | 검토용 설계. 사용자 결정(2026-10-09)으로 충돌이 남아 있는 동안 구현하지 않는다. 이 문서의 검토가 끝날 때까지 아무것도 빌드하지 않는다 |
| 실험 | [EXPERIMENT.md](EXPERIMENT.md)(gin-restore, `DRAFT`). 그 문서의 상호작용 표와 막는 문제는 이 문서로 옮겼다 |
| 작성일 | 2026-10-09 |
| 근거 트리 | hr: 세션 스크래치 `agent_ts2hr/nccl-src`(gin-remaining). hw: `agent_gd/gin/nccl-src`(기준 커밋 `382bbb4` = hr, gpu-detect worktree의 `harness/gpu-detect/hw_layer.diff` md5 `be0ea9ed`, libnccl md5 `efc48ca1`). nvs: `agent_gd/nvs/src`(t1_380 위의 t1w, t1w_layer.diff md5 `ac24448b`). 모두 2026-10-09에 읽기만 함 |

표시: `[소스]` 코드에서 읽음, `[측정]` 원자료에서 확인, `[추론]` 해석, `[미확인]` 확인 안 함.

**줄 번호 규칙.** `gin_host_gdaki.cc`의 줄은 "hr N / hw M" 꼴로 둘 다 적는다. hw는 이 파일만 바꿨고, 장치 헤더(`gin_gdaki.h`,
`gin_gdaki_device_host_common.h`), `init.cc`, `transport/net_ib/gin.cc`는 hr과 hw가 같은 파일이다(md5 확인 `[측정]`). 그래서 그 파일들은 줄 번호
하나만 적는다. NVSHMEM은 `ibgda.cpp`(= `src/modules/transport/ibgda/ibgda.cpp`)와 `wait_until.cuh`(=
`src/include/non_abi/device/wait/nvshmemi_wait_until_apis.cuh`)다. gpu-detect 문서는 gpu-detect worktree의 `harness/gpu-detect/EXPERIMENT.md`다
(아직 master에 없음).

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

감지는 "무슨 일이 있었는가"의 증거만 만든다. 증거를 만드는 코드와 그 로그 줄은 두 정책에서 같다.

| id | 감지원 | 만드는 증거 | 코드 |
|---|---|---|---|
| S1 | 장치 분류: 요청 대기, flush, 보내기의 slot 대기가 본 오류 CQE를 분류해 기록 | QP 장애(분류: RETRY_EXC, LOCAL_QP_ERR, REM_ACCESS 등) | `q4Report` gin_gdaki.h 859–, `tsPoll` 1103–1108, `tsSwErrReport` 1031–1045; 호스트 `gdakiQ4Handle` 1008–1030(hr = hw) → `gdakiTsRoutes` hr 3260–3264 / hw 3285–3289 → `gdakiTsPushFault` hr 3266–3271 / hw 3291–3296 |
| S2 | hw QP 상태 감시: 라운드 밖에서 10 ms마다 QUERY_QP, ERR/SQER이면 합성 기록 | QP 장애 | hw `gdakiDetWatchStep` 6085–6187(상대 거르기 6094), `gdakiDetRecord` 5986–6058, `gdakiDetQueued` 6060–6069, helper 루프에서 부름 6410, 변수 2673–2675 |
| S3 | helper 소켓 liveness | 죽음: BYE 없는 FIN(`gdakiTsCauseLiveness` hr 3712–3718 / hw 3737–3743, `gdakiTsSocketLost` hr 3746–3777 / hw 3771–3802), 1–5 s 간격 거절 둘(`gdakiTsRefused` hr 3783–3810 / hw 3808–3835). 떠남: BYE(hr 6078–6080 / hw 6363–6365). 모름: reset, 시간 초과(`gdakiTsMakeUnknown` hr 3724–3741 / hw 3749–3766). 상대의 거절: FAIL(hr 3896–3906 / hw 3921–3931). 남의 연결: nonce 불일치(hr 4198–4203 / hw 4223–4228) | |
| S4 | 감시(watchdog): 펌웨어 명령 단계 초과, 라운드 초과, 기록이 쌓였는데 helper가 돌지 않음 | 로컬 정체 | `gdakiTsWatchdog` hr 3463–3526 / hw 3488–3551, `gdakiRecFwGuard` hr 1742–1770 / hw 1743–1771 |
| S5 | 장치의 포기와 훑기: 쉬던 장치 스레드가 hold 한도 뒤 포기(DEV_FAILED, abandoned), 기록 유실 | "application이 이미 실패를 들음" | `tsGiveUp` gin_gdaki.h 188–192, `tsLateFail` 200–214, `tsParkStable` 252–297; `gdakiTsScan` hr 5862–5900 / hw 5891–5929 |
| S6 | NVSHMEM t1w: BYE 없는 FIN 판정 | 죽음 | ibgda.cpp 7930–7951, `t1_peer_fin` 6442–(BYE 먼저 읽기), `t1_fini`의 BYE 8243– , `NVSHMEM_IBGDA_FT_T1_FIN_DEATH` 8047 |

증거의 종류: 죽음(DEAD), 떠남(LEFT), 모름(UNKNOWN: 재연결 기계가 맡음, 반응 아님), 상대의 거절(PEER_DECLINED), QP 장애(PAIR_FAULT, 상대가 살아
있으면 라운드), 로컬 정체(LOCAL), application이 이미 들음(TOLD: 상대별 단어, 칸 0, 비동기 오류, 장치 스레드의 실패 가운데 하나라도 그 상대나
communicator에 대해 이미 나감).

### 2.2 반응(정책)

정책은 communicator마다 하나이고 두 값이 있다.
- **fail-fast**(기본): 지금의 hr, hw 동작 그대로. 죽음 → 그 상대 거절(상대별 단어, 비동기 오류, QP를 ERR로, 게이트 실패) → 2 s 뒤 degraded로 칸 0 →
  (hw) `DEGRADED_ROUNDS=0`이면 그 뒤 어느 상대와도 라운드 게시 없음.
- **hold-for-restore**: 죽음의 증거가 있고, 그 상대가 무장(ARMED)이고, 그 상대나 communicator에 대해 application이 아직 아무것도 듣지 않았으면(TOLD
  아님) 거절하지 않고 복원 중(RESTORING)으로 둔다. 복원 시한까지 복원이 안 되면 그때 fail-fast 반응을 그대로 한다.

정책이 바꾸는 것은 **죽음에 대한 반응 하나**와, 복원 중인 상대에게서 온 QP 장애 기록의 처리(라운드 대신 흡수)뿐이다. 살아 있는 상대의 QP 장애,
분류 불가, 확대 상한, 상대의 FAIL, BYE, 감시, 장치의 포기는 두 정책에서 같게 처리한다.

NVSHMEM은 정책이 fail-fast 하나다(복원은 범위 밖). t1w의 `FIN_DEATH`, `FAILSTOP_MS`, `FAILSTOP_CODE`는 fail-fast 반응의 변수다.

### 2.3 정책 고르기와 기본값

- 환경 변수 `NCCL_GIN_FAULT_POLICY=failfast|hold`. 기본 `failfast`. GIN 문맥을 만들 때(`gdakiTsSetup` hr 6152– / hw 6438–) 읽고, 설정 all-gather
  (`gdakiTsAddr`, hr 6232 / hw 6518)에 실어 모든 rank가 같은지 본다. 다르면 그 communicator는 fail-fast다(WARN 한 줄).
- communicator마다의 선택은 API로: `hold`는 application이 그 communicator에 `ncclGinRestoreResume`을 부른 뒤에만 무장한다(EXPERIMENT.md 9.4절).
  부르지 않는 application의 communicator는 변수와 상관없이 fail-fast다. 이 호출은 새 `nccl.h`에만 있으므로 그 application의 장치 코드가 새 헤더로
  빌드됐다는 증거로도 쓴다(4.5절 A1, `[추론]`: 한 프로그램이 헤더 둘을 섞는 경우는 막지 못함).
- 상대마다의 무장(ARMED): 그 상대의 확정된 체크포인트가 짝에 있고, 그 상대로 가는 이 rank의 로그가 그 절단점 뒤로 빠짐없고(넘침 없음), 그 상대의 예비
  프로세스가 등록돼 있음. 하나라도 아니면 그 상대의 죽음에는 fail-fast다.
- 같은 프로세스가 NVSHMEM t1w를 쓰면 `hold`는 t1w의 fail-stop이 꺼져 있어야 한다(4.8절 X6).

### 2.4 우선순위와 fallback 순서

위가 이긴다.
1. application이 고른 동작: `ncclCommAbort`, `ncclCommRevoke`, 중단 shrink, `ncclCommDestroy`(모든 단어를 올림). 복원 중이면 취소(CANCELLED).
2. 이미 application에 닿은 것(TOLD): 그 상대의 단어나 칸 0이 올라 있음, 비동기 오류가 서 있음, 그 상대의 QP에서 장치 스레드가 실패함(포기, DEV_FAILED),
   펌웨어 감시가 그 상대에 대해 단어를 올림. 이 상태에서는 hold를 시작하지 않고, 복원 중이었으면 fallback.
3. hold-for-restore(무장된 상대의 죽음).
4. 복원 시한(`NCCL_GIN_RESTORE_MS`, 초안 20 000 ms) 또는 복원 중 실패 → fallback.
5. fail-fast.

fallback 순서는 hold-for-restore → 복원 시한 → fail-fast다. fallback은 지금의 거절을 그때 부르는 것이고, degraded 시계도 그때 시작한다(칸 0은
죽음 판정 + 시한 + `NCCL_GIN_TS_DEGRADED_MS`).

더 정한 것.
- TOLD의 판단: (a) communicator 등록부(`gdakiUa`)에서 그 상대의 단어, 칸 0, `allWhy`(hr 2705–2718 / hw 2712–2725), (b) 그 문맥의 비동기 오류가 서
  있음(`q4->setAsync`, 다른 상대의 거절이 세운 것도 communicator에 대한 것이므로 TOLD), (c) 그 상대로 가는 게이트의 `abandoned`나 DEV_FAILED(게이트
  읽기, NIC 복사 경로). (c)의 읽기가 실패하면 TOLD로 본다(보수적).
- communicator마다 복원 중인 상대는 하나다. 복원 중 다른 상대의 죽음 증거가 오면 복원 중인 상대도 fallback하고 새 죽음은 fail-fast다(단일 실패 범위).
- 잘못된 죽음 판정(살아 있는 프로세스의 소켓이 BYE 없이 닫힘)에 대한 막이 둘이다. (1) 예비 프로세스는 같은 노드에 있으므로 활성화 전에 원래 프로세스의
  PID(등록 때 받음)가 없어졌는지 스스로 확인한다(`kill(pid, 0)`이 ESRCH). 살아 있으면 활성화를 거절하고 생존 rank는 fallback한다. (2) 복원 라운드가
  생존 rank의 QP를 예비 프로세스의 새 QPN에만 다시 이으므로, 옛 프로세스가 살아 있어도 RC 연결이 없어 생존 rank의 메모리에 쓰지 못한다(펜싱 `[추론]`).
  복원 중이거나 복원 뒤의 그 논리 rank에서 오는 HELLO는 화신 번호가 지금과 같아야 받는다(옛 화신이 다시 붙지 못함).

### 2.5 불변식

- (가) hold 동안 그 상대에 대해 application에 닿는 것은 없다: 상대별 단어, 칸 0, 비동기 오류, degraded 예약, 오류 줄 모두 없다. 대기는 붙잡혀 있다.
- (나) 그 상대나 communicator에 대해 무언가가 application에 닿았으면 hold는 시작되지 않거나 끝난다(fallback). 실패를 들은 연산은 다시 내지 않는다는
  기존 규칙(게시 전 확인 `gdakiUaPeerRaised`, 커밋 지점 Dekker)이 그대로 지켜진다.
- (다) fail-fast에서 동작은 hw와 같다. 정책 hook은 fail-fast에서 늘 같은 값을 돌려주는 분기 하나씩이다(4.10절 G1–G5).

## 3. 상태 기계 (상대 하나, hold-for-restore)

```
 OFF ──(Resume 호출, 첫 확정 체크포인트, 로그 무결, 예비 등록)──▶ ARMED ──(로그 넘침, 체크포인트 무효)──▶ OFF
 ARMED ──(죽음의 증거, TOLD 아님)──▶ RESTORING ──(REJOIN, 상태 적용, 복원 라운드 게시)──▶ ARMED(화신 + 1; 생존 rank는 자기 다음 체크포인트까지 OFF)
 RESTORING ──(시한, 실패, TOLD)──▶ FALLBACK = fail-fast 거절
 RESTORING ──(abort, revoke, shrink, destroy)──▶ CANCELLED
 OFF 또는 ARMED가 아닌 상대의 죽음 ──▶ fail-fast 거절
```

hold의 시작(RESTORING으로 갈 때): (1) 그 상대로 가는 모든 QP의 게이트를 홀수로(보내기가 더 들어오지 않음), (2) 그 QP들을 ERR로(거절이 먼저 하는 일과
같음: 죽은 상대로 간 WQE가 flush 오류로 끝나 slot을 기다리던 보내기가 게이트를 나감), (3) 개수 0을 기다림(한도 `quiesceMs`, 넘으면 fallback).
상대별 단어, 칸 0, 비동기 오류는 건드리지 않는다. 장치 대기가 본 flush 오류는 기록(D1)이 되고 흡수된다.

복원 뒤 생존 rank 자신의 무장: 죽은 rank가 보낸 메시지의 로그는 그 rank와 함께 사라졌다. 그래서 생존 rank q의 확정 체크포인트의 절단점(되살린 rank에서
q로 오는 통로)이 복원 뒤 로그의 시작보다 앞이면, q는 자기 다음 확정 체크포인트까지 OFF다(그 사이 q가 죽으면 fail-fast). 단일 실패 범위의 약한 창이다
`[추론]`.

## 4. 통합 상호작용 표

열: 장치와 코드 위치 / fail-fast에서 / hold-for-restore에서 / 우선 / 바꿀 것. "바꿀 것"의 G는 gpu-detect 계층에 넣을 정책 hook(4.10절), L은 복원 계층의
일이다. "(검토 1)", "(검토 2)"는 독립 검토(6절)에서 온 행이나 고침이다.

### 4.1 감지

| # | 장치와 코드 | fail-fast | hold-for-restore | 우선 | 바꿀 것 |
|---|---|---|---|---|---|
| D1 | 장치 분류와 기록 경로(S1). helper의 기록 처리 hr 6114–6124 / hw 6399–6409 → `gdakiTsInitiate` hr 5419– / hw 5448– | 기록 → 라운드: liveness 확인 → 살아 있으면 복구, 죽었으면 거절(hr 5478–5489 / hw 5507–5518) | 살아 있는 상대: 같음. 복원 중인 상대의 기록: 라운드를 열지 않고 흡수하고 `qs[].handled`를 올림(라운드를 열면 liveness가 죽음을 보고 거절로 감) | 감지(반응은 정책) | G4: 기록 처리 루프에 정책 hook(fail-fast에서 늘 "라운드"). L: 흡수 |
| D2 | hw QP 상태 감시(S2) | 거절 안 된 모든 상대의 QP를 10 ms마다 QUERY_QP. ERR/SQER + 유예 5 ms(뿌리 CQE 없으면 50 ms) → 합성 기록 → D1 | 복원 중인 상대는 감시하지 않음(QUERY_QP도, QP와 CQ의 NIC 읽기도 없음). 이미 줄에 선 기록은 D1처럼 흡수. 복원 뒤(QP가 예비 프로세스와 RTS) 다시 감시 | 감지 | G3: 상대 거르기(hw 6094)에 정책 hook(fail-fast에서 늘 "감시함") |
| D3 | 감시의 펌웨어 명령 부하(S2) | rank마다 (상대 수 × 문맥 수)번/10 ms, `opMu` 안 | 이 rank에서는 복원 라운드와 겹치지 않음(같은 helper 스레드, `fs.empty()`일 때만 감시 hw 6410). 같은 NIC의 다른 rank의 감시와 예비 프로세스의 초기화(QP 생성, MR 등록)는 겹침. 복원 라운드의 펌웨어 단계가 3 000 ms를 넘으면 감시가 그 상대의 단어를 올림 → TOLD → fallback | 펌웨어 감시 | L: 복원 셀에서 `detQueryUsMax`와 복원 단계 시간을 잼. 기준이 넘으면 복원 중 감시 주기를 늘리는 변수를 검토 |
| D4 | helper 소켓 liveness(S3). 죽음: FIN, 거절 둘. 다시 걸지 않음: `gone`/`declined` 상대(hr 3972, 4069 / hw 3997, 4094). HELLO는 낮은 rank에서만, 더 새 세대만(hr 4209–4215 / hw 4234–4240). 거절한 상대에는 FAIL(hr 3910–3923, 4176–4180, 4204–4207 / hw 3935–3948, 4201–4205, 4229–4232). nonce(hr 6237–6239 / hw 6523–6525) | 죽음 → `deadJudged` → helper 루프가 바로 거절(R1) | 판정과 그 줄은 같음(`deadJudged`, `cDeaths`). 반응만 다름(R1). 새 프로세스 받기: 새 메시지 REJOIN을 받기 루프(hr 4164–4243 / hw 4189–4268)에서, 복원 중인 상대에게서만, nonce가 맞고(초기화 재생으로 같은 nonce, EXPERIMENT.md 9.3절) 화신 번호 = 지금 + 1일 때. 받으면 `gone`, `deadJudged`, `refusals`, `left`, `peerFailed`, `failedPending`을 지우고 `gdakiTsInstall`(hr 3859–3872 / hw 3884–3897). 복원 중이 아니면 REJOIN은 남의 HELLO처럼 닫음. 복원 중인 상대의 HELLO는 받지 않고, 복원 뒤에는 화신 번호가 맞는 HELLO만 받음(2.4절 펜싱) | 감지 | L: REJOIN, HELLO의 화신 확인. hw 변경 없음 |
| D5 | 감시(S4) | 펌웨어 단계 초과 → 그 상대의 단어 + 비동기 오류(hr 3476–3516 / hw 3501–3541). 라운드 25 s 초과, 기록이 쌓였는데 helper 정지 → 드러냄, 이후 모든 라운드 거절(hr 3517–3525 / hw 3542–3550) | 같음. 복원 기다림은 라운드가 아님(`gdakiTsBusy` 없음, heartbeat 계속, 기록은 흡수되어 쌓이지 않음) → 라운드 감시와 쌓임 감시는 조용함. 복원 라운드는 라운드(`gdakiTsBusy`, `gdakiRecFwGuard` 안). 감시가 그 상대나 communicator를 드러내면 TOLD → fallback | 감시 | 없음 |
| D6 | 장치의 포기와 훑기(S5) | 포기 → 거절(hr 5892–5893 / hw 5921–5922). 기록 유실 두 번 → 거절(hr 5894–5896 / hw 5923–5925) | 포기는 TOLD → fallback(훑기의 거절은 보통 거절이므로 R1 hook이 "TOLD"로 보고 fail-fast). 유실 검사: 흡수가 `handled`를 올리므로 보통은 조용함. 장치 기록 우편함이 넘친 경우 그 상대는 건너뜀 | 장치 실패(TOLD) | G5: 훑기의 유실 검사에 정책 hook(fail-fast에서 늘 "검사함") |
| D7 | NVSHMEM t1w FIN 판정(S6) | BYE 없는 FIN → 바로 `t1_decline` | NVSHMEM에는 hold가 없음. 같은 프로세스가 GIN hold와 NVSHMEM t1w를 함께 쓰면 같은 죽음에 NVSHMEM 쪽이 fail-fast로 반응함(R6, X6) | NVSHMEM fail-fast | 없음(제약으로 둠) |

### 4.2 반응

| # | 장치와 코드 | fail-fast | hold-for-restore | 우선 | 바꿀 것 |
|---|---|---|---|---|---|
| R1 | 거절 `gdakiTsDecline` hr 4916–4966 / hw 4941–4991: 준비 풀기(hr 4930 / hw 4955), QP를 ERR로(hr 4931–4934 / hw 4956–4959), 책임 기록, 상대 단어, 비동기 오류(hr 4936–4943 / hw 4961–4968), FAIL, 게이트 실패(hr 4959–4965 / hw 4984–4990). 죽음의 호출 자리: helper 루프(hr 6095–6101 / hw 6380–6386), 라운드의 죽음 길(hr 5478–5489 / hw 5507–5518), 라운드 안 소켓 끊김(hr 5566–5572, 5594–5600 / hw 5595–5601, 5623–5629), 기다림 안 응답이 본 끊김(hr 5332–5334 / hw 5357–5359, 다음 루프의 helper 거절) | 위 모두 | 거절 맨 앞의 정책 hook: 정책 hold, 상대 ARMED, 죽음의 증거(`uaWhy == PEER_DEAD`, 또는 `pe.lostCause`/`pe.closeCause`가 FIN이거나 거절 둘이고 `left`도 `peerFailed`도 아님), TOLD 아님 → 준비 풀기만 하고 RESTORING, 돌아감. 그 밖은 거절 그대로. 라운드 도중의 FIN은 지금 거절이 아니라 취소(`gdakiTsCancelRound` hr 5127–5146 / hw 5152–5171, 응답 쪽 `gdakiTsCancelResponder` hr 5152–5173 / hw 5177–5198)로 가서 상대를 "모름"으로 두고 기록을 다시 줄에 세운다. 죽은 상대는 다시 걸기와 탐침이 거절 둘(1 s 이상 간격)로 죽음이 되고, 그 다음 라운드의 거절이 이 hook에 온다. 그 사이 게이트는 라운드의 정지로 이미 홀수다 | 2.4절 | G2: hook 하나(fail-fast에서 늘 "거절") |
| R2 | 상대별 abort 단어(hq, `gdakiUaRaisePeer` hr 2793–2862 / hw 2800–2869; 배열 hr 2705–2755 / hw 2712–2762). 장치: `tsWaitWord` gin_gdaki.h 241–245, `tsParkStable` 271–277, `tsPoll` 1123–1139, 보내기 `tsPosterAbortWord` 223–228 | 거절이 그 상대의 단어를 바로 올림: 그 상대 QP의 대기, flush, 쉬는 보내기가 바로 실패 | 복원 중에는 올리지 않음. 쉬는 스레드는 64번마다 단어를 읽지만 0이라 계속 쉼(hold 한도까지, T4). fallback에서 올림 | 2.4절 | 없음 |
| R3 | degraded(hr 2826–2840, 2867–2894 / hw 2833–2847, 2874–2901; `NCCL_GIN_TS_DEGRADED_MS` hr 2690 / hw 2697) | 첫 죽음 거절 2 s 뒤 칸 0: `waitSignal`, `waitCounter`, 배리어가 오류 | 복원 중에는 예약 없음(거절이 없으므로). fallback의 거절이 예약 → 칸 0은 fallback + 2 s | 2.4절 | 없음 |
| R4 | `NCCL_GIN_TS_DEGRADED_ROUNDS`(hw M-C, `gdakiUaPeerRaised` hw 2918–2925, 변수 2676) | 0(기본): 칸 0이 오르면 어느 상대와도 라운드 게시 없음, 그 거절은 원인 Local | hold 자체는 칸 0을 올리지 않으므로 이 규칙은 복원 중 잠자고 있음. 복원 중 칸 0이 다른 이유로 오르면(abort, revoke, shrink, 모든 상대 거절, 다른 rank의 죽음의 degraded) 복원 라운드의 게시 전 확인(`gdakiTsRepostPlanAll` hr 4566 / hw 4591, `gdakiTsRepostApply` hr 4708 / hw 4733)이 막음 → fallback | 칸 0(TOLD) | 없음. fail-fast의 변수로 문서화 |
| R5 | 비동기 오류와 문맥의 sticky 오류(거절이 세움 hr 4939–4942 / hw 4964–4967; `tsFail` gin_gdaki.h 1047–1053; Commit은 helper 안에서 지우지 않음 hr 2492–2512 / hw 2493–2513) | 거절 때 비동기 오류. sticky는 실패한 장치 스레드가 그 문맥에 세움 | 복원 중에는 비동기 오류 없음. 그 상대의 QP에서 장치 스레드가 실패했으면(sticky) TOLD → hold 안 함 | TOLD | 없음 |
| R6 | t1w fail-stop과 장치 대기 단어(ibgda.cpp `t1w_after_decline` 6841–6858, `t1w_failstop_exit` 6813–6839, `t1_decline`의 호출 6925, 변수 8047–8049; 장치 `nvshmemi_t1w_aborted` wait_until.cuh 41–56) | 0(기본): 거절 직후 `_exit(70)`. −1: 장치 대기 단어를 올려 대기를 "풀린 채" 돌려줌. 양수: 단어를 올리고 그만큼 뒤 종료 | NVSHMEM에는 hold가 없음. 이 변수들은 NVSHMEM fail-fast 반응의 변수다. NVSHMEM에 hold를 넣는다면 `t1_decline`의 맨 앞에 G2와 같은 hook을 두는 것이 같은 구조다(범위 밖) | NVSHMEM fail-fast | 없음(문서화). X6 |

### 4.3 복구 기계

| # | 장치와 코드 | fail-fast | hold-for-restore | 우선 | 바꿀 것 |
|---|---|---|---|---|---|
| M1 | 라운드: 쌍 범위와 전체 재설정(`gdakiTsDecideScope` hr 3315–3375 / hw 3340–3400), NACK 12(hr 5611–5619 / hw 5640–5648), 범위 충돌(hr 5639–5653 / hw 5668–5682), 커밋 전 계획과 NACK 15/16(hr 4542–4570, 5621–5627 / hw 4567–4595, 5650–5656), 중첩 응답 라운드(`gdakiTsServeLower` hr 5315–5378 / hw 5341–5407, hw M-A: 한 번에 하나), 미룬 REQ(hr 6023–6056 / hw 6308–6341) | 그대로 | 살아 있는 상대와는 그대로(복원 중에도). 상대 p와 라운드 도중 p가 죽으면 그 라운드의 거절이 R1 hook으로 감(준비는 hook이 풂). 복원 중 p와는 라운드가 없음(D1). 라운드가 ACK를 기다리는 동안 온 새 메시지(CKPT, REJOIN)를 `gdakiTsServeLower`가 버림(hr 5372–5373 / hw 5401–5402) → 버리지 말고 그 상대 칸에 미뤄야 함 | 라운드(살아 있는 상대) | L: 새 메시지 미루기. hw 변경 없음 |
| M2 | 정확히 한 번: 응답 쪽 실행 수(`gdakiTsExecuted` hr 4330–4348 / hw 4355–4373, `gdakiTsBaseline` hr 4351–4367 / hw 4376–4392), 다시 보내기 계획과 적용(hr 4552–4897 / hw 4577–4922), 장치의 `lbase` 다시 매핑(`tsPoll` gin_gdaki.h 1086–1095) | 상대가 REQ/ACK로 알려 준 rmsn으로 실행 안 된 WQE를 다시 보냄 | 죽은 쪽 QP는 없어 QUERY_QP를 못 함. (a) 생존 rank → 죽은 rank: SQ에서 다시 보내지 않고 모든 옛 WQE를 실행된 것으로(계획 `U = S, n = 0`: `lbase += S`), 효과는 생존 rank의 로그를 예비 프로세스에 적용해 넣음. 순서와 번호는 로그 항목 번호(쓰는 쪽 원자 더하기)와 통로의 누적 메시지 수. (b) 죽은 rank → 생존 rank: 생존 rank의 응답 쪽 QP는 남아 있어 누적 실행 수 X(화신마다의 rmsn 증분을 기준을 바꾸기 전에 더함)를 읽음. 억제 예산 X − P(P는 체크포인트 때의 같은 수). 단위는 RC 요청 메시지 | 복원 | L: 누적 실행 수(Executed/Baseline 자리), 계획 `U = S` |
| M3 | 낡은 기록 검사(hr 5431–5435 / hw 5460–5464)와 에폭 회계(장치는 에폭이 바뀌면 `notEpoch`로 쉼, `tsPoll` 1106–1116) | 빈 라운드 없음 | 체크포인트의 입력 멈춤은 에폭을 홀수로 했다가 +2로 게시(빈 라운드: 같은 짝수로 돌려놓으면 `notEpoch`로 쉬던 대기가 hold 한도까지 쉬다 포기함). 그러면 멈춤 앞의 진짜 기록이 "앞 라운드가 덮음"으로 버려짐 → 검사를 진짜 라운드가 덮은 에폭(`coveredEpoch`)으로. hw 감시의 `handled < epoch + 2`, `detPushedEpoch`도 빈 라운드 뒤 새 에폭으로 보이지만 QP가 RTS면 아무 일 없음 | 정확성 | L: `coveredEpoch`(fail-fast에서는 늘 `epoch`와 같음) |
| M4 | Prepare/Commit(`ncclGinRecoverPrepare` hr 2143–2330 / hw 2144–2331, Commit hr 2334–2529 / hw 2335–2530; 토큰 검사 hr 2350–2369 / hw 2351–2370, 다시 연결 hr 2450 / hw 2451, drain hr 2257–2303 / hw 2258–2304) | 살아 있는 상대와의 라운드 | 복원 라운드: Prepare(p)(2ERR, drain: 죽은 상대로 간 WQE는 ERR 뒤 flush 오류 CQE로 끝남 `[추론, 미확인]`), `rq.exch`를 예비 프로세스의 끝점으로(`opMu` 안; 토큰 검사가 `rq.exch.qpn`을 보므로 먼저), Commit(예비 프로세스의 토큰). RC는 양쪽 PSN이 맞아야 하므로 토큰 교환은 양쪽이다: REJOIN이 예비 프로세스의 QPN과 보내기 PSN을 싣고, 생존 rank는 Prepare의 토큰(자기 QPN, 새 보내기 PSN)을 돌려주고, 예비 프로세스는 그 PSN으로 자기 QP를 RTR/RTS로 잇고 READY, 생존 rank는 그 뒤 Commit(지금 라운드의 REQ/ACK와 같은 짝). 예비 프로세스는 초기화 재생 때 QP를 만들기만 하고 잇지 않는다 | 복원 | L |

### 4.4 한도와 감시

| # | 장치와 코드 | fail-fast | hold-for-restore | 우선 | 바꿀 것 |
|---|---|---|---|---|---|
| T1 | 확대 상한 8회/60 s(`gdakiTsEscalated` hr 5081–5102 / hw 5106–5127; 쓰는 곳 hr 5444, 5503–5508 / hw 5473, 5532–5537) | 그대로 | 살아 있는 상대의 라운드는 그대로 셈. 복원 라운드와 체크포인트의 빈 라운드는 복구 라운드가 아니므로 세지 않음(`count = false`) | 상한 | L |
| T2 | 펌웨어 단계 감시(D5) | 그대로 | 복원 라운드의 펌웨어 단계(2ERR, 2RST, INIT/RTR/RTS, QUERY_QP)에도 그대로 → 초과는 TOLD → fallback. 체크포인트의 drain 확인 QUERY_QP도 가드 안에서 하고 한도를 둠 | 감시 | L |
| T3 | 라운드 감시 25 s(D5) | 그대로 | 복원 기다림은 라운드가 아님. 복원 라운드만 라운드 | 감시 | 없음 |
| T4 | 장치 대기의 hold 한도(게이트 `waitMs` = `NCCL_GIN_TS_HOLD_MS` 30 000, hr 6820 / hw 7128; `tsParkStable` gin_gdaki.h 255, 278–294) | 라운드를 기다리는 장치 스레드의 한도 | 복원 시한(20 000) + 복원 라운드 < hold 한도여야 함. 문맥을 만들 때 검사하고 어기면 그 communicator는 fail-fast(WARN). 게이트가 hold보다 먼저 홀수가 된 경우(라운드 도중의 죽음: 라운드의 정지 → 취소 → 거절 둘로 죽음 판정까지 수 초)에는 쉬는 스레드의 시계가 그때부터 가므로, 실제 시한은 min(hold 시작 + 시한, 게이트가 홀수가 된 시각 + hold 한도 − 복원 라운드 몫)으로 잡는다(호스트가 게이트를 쓴 시각을 앎). 포기는 TOLD → fallback | hold 한도 | L: 설정 검사 |
| T5 | 복사 한도 2 000 ms와 NIC 루프백(hr 1232, `gdakiRecCopyWait` 1388–1440, `gdakiLbXfer` 1586–1668 / hw 1232, 1388–1440, 1587–1669), 루프백 설정과 자체 시험(hr 6474–6735 / hw 6761–7040, hw L-C: NIC만으로 시험) | 그대로 | 복원이 쓰는 GPU 메모리(로그 고리, rkey 표, 신호와 카운터 표, 측 표)를 루프백 MR에 더함(`gdakiLbAddRange`). 자체 시험이 그것도 읽고 씀. 로그 내보내기는 고정 사본 크기 조각으로, 조각마다 한도 안 | 복사 한도 | L |

### 4.5 끝점과 메모리

| # | 장치와 코드 | fail-fast | hold-for-restore | 우선 | 바꿀 것 |
|---|---|---|---|---|---|
| A1 | rkey와 주소: window rkey는 등록 때 all-gather(`ncclGinGdakiRegMrSym` hr 7879–7931, all-gather 7902–7905 / hw 8198–8250, 8221–8224), 신호와 카운터 표의 교환(hr 7311–7315 / hw 7630–7634). 장치: 원격 주소는 window 안의 오프셋(gin_gdaki.h 475), rkey는 게이트 전에 읽음(476, 게이트 501; `signalKey` 1460–1464), `loadConst`는 보통 읽기(`utility.h` 449–457) | rkey는 communicator가 사는 동안 고정 | 예비 프로세스의 MR은 새 rkey. 생존 rank는 그 상대로 가는 게이트가 홀수인 동안 모든 window rkey 표와 신호, 카운터 표의 칸 p를 NIC 루프백으로 바꾸고 짝수 에폭을 게시(장치는 획득 원자 연산 뒤 읽음). 게이트에서 쉬던 보내기는 옛 rkey를 레지스터에 가짐 → 새 헤더는 느린 길로 들어간 뒤 키를 다시 읽음(EXPERIMENT.md 9.9절 DV3). 옛 헤더 application은 무장하지 않음(2.3절) | 복원 | L + 장치 헤더 |
| A2 | get 표(Commit이 지움 hr 2436–2446 / hw 2437–2447) | 그대로 | 복원 라운드의 Commit이 그 상대의 get 표를 지움. get은 결정성 요구(EXPERIMENT.md 9.7절 4)로 제한 | 복원 | 없음 |
| A3 | GIN collComm 고리(gin.cc 138–229, 231–259) | rank 하나가 죽으면 고리가 끊겨 그 communicator에서 GIN 집합 교환(새 window 등록, devComm 생성)을 더 못 함 | 같음. 예비 프로세스의 GIN 초기화는 초기화 기록으로 대답(EXPERIMENT.md 9.3절). 복원 뒤 새 GIN 자원은 범위 밖 | 범위 | 없음 |
| A4 | LSA(devComm `lsaRank`, `lsaSize`, `comm__types.h` 35; `dev_runtime.cc` 392) | 해당 없음(GIN만) | 같은 노드의 rank가 LSA 팀이면 생존 rank의 devComm이 죽은 rank의 메모리를 load/store로 가리킴 `[추론]` | 막는 문제 B2 | 5절 |

### 4.6 application과 정리

| # | 장치와 코드 | fail-fast | hold-for-restore | 우선 | 바꿀 것 |
|---|---|---|---|---|---|
| P1 | `ncclCommRevoke`(init.cc 3463), `ncclCommAbort`(3521), 중단 shrink(3796) → `ncclGinTsUserAbortRaise` hr 2760–2788 / hw 2767–2795; 정리 `ncclGinGdakiTsCommTeardown` hr 6962–7084 / hw 7274–7403, `gdakiTsStop` hr 7086–7105 / hw 7405–7424, `gdakiTsFree` hr 7106–7134 / hw 7425–7453 | 모든 단어를 올림, helper 정지 | 같음. 복원 중이면 CANCELLED, 예비 프로세스에 BYE. 복원 라운드 중이면 그 라운드는 정지(`ts->stop`)로 거절 | application | L |
| P2 | 원인 기반 shrink 넘기기(`gdakiBlameNote` hr 841–898 = hw; 거절의 기록 hr 4937 / hw 4962; 질의 init.cc 3572–3640) | 죽은 상대의 거절이 원인 PeerDead로 기록 → 그 상대를 빼는 중단 shrink는 GIN 오류를 넘어감. hw: degraded 뒤 건강한 쌍의 거절은 원인 Local → 넘기기 실패 | 복원 중에는 거절이 없어 기록도 없음. application이 복원 중 (자기 시한으로) shrink하면 P1로 취소되고, 부모에 GIN 오류가 없으므로 넘기기 검사가 필요 없음 `[추론]`. fallback 뒤는 fail-fast와 같음 | application | 없음 |
| P3 | 통계 API(`ncclGinGetRecoveryStats` hr 7135– / hw 7454–) | 그대로 | 복원, fallback, 취소, 체크포인트, 억제 수를 더함 | 없음 | L |

### 4.7 빌드와 규약

| # | 장치와 코드 | fail-fast | hold-for-restore | 우선 | 바꿀 것 |
|---|---|---|---|---|---|
| B1x | 운영과 연구 빌드(`GIN_TS_NOTE` hr 82–85 = hw; 시험 스위치는 `#ifndef NCCL_GIN_TS_PRODUCTION`) | 그대로 | 정책과 복원은 두 빌드에 같음. 시험 스위치만 연구 빌드 | 규칙 | L |
| H1x | helper 메시지 규약(종류 hr 2932–2934 / hw 2945–2947, 형식 hr 2953–2967 / hw 2966–2980; 모르는 종류는 idle 루프가 무시 hr 6081–6082 / hw 6366–6367, 기다림 안 응답이 무시 hr 5372–5373 / hw 5401–5402) | 그대로 | 새 종류(CKPT_PAUSE, PAUSED, BUSY, CKPT_RESUME, CKPT_STABLE, ACTIVATE, REJOIN, READY, DONE_RS, LOG_REQ, LOG_DATA). 모든 rank가 같은 빌드, 같은 정책이어야 함(설정 all-gather에서 확인). 기다림 안 응답은 미룸(M1) | 규약 | L |

### 4.8 외부

| # | 장치 | fail-fast | hold-for-restore | 우선 | 바꿀 것 |
|---|---|---|---|---|---|
| X1 | PyTorch ProcessGroupNCCL 감시와 시간 제한, NCCL 자체 시간 제한 | application이 2 s 안에 오류를 봄(degraded) | 복원 동안 생존 rank의 스트림이 GIN 커널에 묶임. 복원 시한(20 s)이 감시 한도보다 짧아야 함. 기본 한도는 이 환경에서 확인하지 않음 `[미확인]` | application의 감시 | 문서 |
| X2 | GIN 밖의 NCCL collective, NCCL P2P, LSA | 그대로 | 로그되지 않음. 복원한 communicator에서 되살린 rank와는 GIN 장치 통신만 됨(collective 전송, proxy 연결은 새 프로세스로 다시 잇지 않음). 쓰면 멈추거나 오류 | 범위 | 문서 |
| X3 | NCCL RAS | 죽은 rank를 보고 | 되살린 rank를 모름: RAS 보고가 어긋날 것 `[추론, 미확인]` | 범위 | 문서 |
| X4 | `NCCL_MULTI_RANK_GPU_ENABLE`(init.cc 73, 1307–1309) | 그대로 | 예비 프로세스도 같은 GPU의 셋째 프로세스로 이 변수가 필요. GPU 시분할로 예비 프로세스의 일이 느려짐(복원 시간에 잼) | 규칙 | 실행기 |
| X5 | NCCL의 shrink, grow, revoke, abort(`nccl.h.in` 321–363) | application의 회복 수단 | 복원 중 이 호출이 오면 P1로 취소. grow는 새 communicator와 새 devComm을 만들어 도는 커널을 지키지 못하므로 복원을 대신하지 못함 | application | 없음 |
| X6 | 같은 프로세스의 NVSHMEM t1w(R6, D7) | NVSHMEM은 FIN 판정 뒤 `_exit(70)`(기본) | 같은 죽음에 NVSHMEM 쪽이 생존 프로세스를 끝냄 → GIN hold가 무의미. 제약: hold 정책의 프로세스는 NVSHMEM을 쓰지 않거나 `NVSHMEM_IBGDA_FT_T1_FAILSTOP_MS=-1`과 `NVSHMEM_IBGDA_FT_T1_FIN_DEATH=0`. 실행기가 확인 | 프로세스 종료가 이김 | 실행기 검사 |

### 4.9 복원 구성 요소

| # | 구성 요소 | fail-fast | hold-for-restore에서 닿는 기존 장치 |
|---|---|---|---|
| C1 | 체크포인트의 입력 멈춤(빈 라운드, EXPERIMENT.md 9.4절) | 없음(체크포인트 없음) | 게이트 에폭(M3), 낡은 기록 검사(M3), 확대 상한(T1, 세지 않음), 기다림 안 응답(M1, 미룸), hold 한도(멈춤은 ms 단위), drain의 QUERY_QP(T2). 멈춤 동안 그 쌍에 라운드가 돌면(QP 장애) 라운드의 게시가 짝수 에폭을 내어 멈춤을 깬다 → 라운드가 이기고 그 체크포인트는 버린다: 멈출 때 게이트마다 에폭을 적고, RESUME 때 생존 rank가 "빈 라운드 밖의 에폭 변화"를 알리면 확정하지 않음. 멈춤 요청을 받은 rank가 라운드 중이면 BUSY, 체크포인트는 다음 경계로 |
| C2 | 송신 쪽 로그(장치) | 꺼짐: 측 표 포인터가 0, put 경로는 그것을 한 번 봄 | 게이트 안 기록(put 경로 gin_gdaki.h 458–547), 넘침은 그 상대 OFF |
| C3 | 예비 프로세스와 초기화 재생 | 없음 | NCCL bootstrap, GIN collComm(A3), `NCCL_MULTI_RANK_GPU_ENABLE`(X4). 막는 문제 B1 |
| C4 | REJOIN | REJOIN은 닫음 | 재연결 기계(D4) |
| C5 | 복원 라운드 | 없음 | Prepare/Commit(M4), rkey(A1), `RepostApply`의 커밋 지점과 PUBLISHING(M2), 펌웨어 감시(T2), hold 한도(T4), 게시 전 확인(R4) |
| C6 | 예비 프로세스의 억제 | 없음 | 게이트 에폭 반쪽의 새 비트(SUPPRESS, `EPOCH_MASK` 30비트 → 29비트), `tsWordOpen`의 검사 상수(gin_gdaki.h 146–148), 느린 길(303–328). fail-fast와 보통 rank에서는 그 비트가 서지 않음 |

### 4.10 gpu-detect 계층에 넣을 변경 (최소)

정책을 나누는 데 필요한 것만이다. fail-fast에서 모든 hook은 지금의 동작을 그대로 낸다(2.5절 (다)). 그래서 gpu-detect의 pilot과 예측은 이 변경으로
바뀌지 않는다 `[추론]`.

**hw (`gin_host_gdaki.cc`).**
- G1. 정책 칸과 변수: `NCCL_GIN_FAULT_POLICY`(기본 `failfast`)를 `gdakiTsSetup`(hw 6438–)에서 읽고 설정 all-gather(`gdakiTsAddr`, hw 6458–6518)에
  싣는다. rank마다 다르면 fail-fast(WARN). 문맥(`gdakiTs`)과 communicator 등록부(`gdakiUa`)에 둔다.
- G2. 거절 hook: `gdakiTsDecline`(hw 4941) 맨 앞에서 `gdakiPolicyOnDecline(r, peer, why, cause, uaWhy)`를 부르고, 참이면 돌아간다. fail-fast에서는
  늘 거짓이다. 죽음의 모든 호출 자리(R1)가 이 함수로 모이므로 호출 자리는 고치지 않는다.
- G3. 감시 hook: `gdakiDetWatchStep`의 상대 거르기(hw 6094)에 `|| !gdakiPolicyWatch(r, p)`. fail-fast에서는 늘 참(감시함).
- G4. 기록 처리 hook: helper의 기록 처리 루프(hw 6399–6409)에서 `gdakiTsInitiate` 앞에 `if (!gdakiPolicyRoute(r, f)) continue;`(흡수는 hook이 하고
  `nQueued`는 지금처럼 줄임). fail-fast에서는 늘 참(라운드).
- G5. 훑기 hook: `gdakiTsScan`의 유실 검사(hw 5923–5925)를 `gdakiPolicyWatch(r, p)`가 거짓인 상대에서 건너뜀. fail-fast에서는 늘 검사.
- G6. 코드 변경 없음, 문서만: `NCCL_GIN_TS_DEGRADED_MS`, `NCCL_GIN_TS_DEGRADED_ROUNDS`, QP 감시의 변수들은 fail-fast 반응의 변수다. hold에서는 거절이
  일어난 뒤(fallback)에만 효과가 있다.

**t1w (NVSHMEM).** 코드 변경 없음. `NVSHMEM_IBGDA_FT_T1_FIN_DEATH`, `FAILSTOP_MS`, `FAILSTOP_CODE`는 NVSHMEM fail-fast 반응의 변수로 문서화한다.
NVSHMEM 정책은 fail-fast 하나다. GIN hold와 같은 프로세스에서 쓰면 X6의 제약.

### 4.11 복원 계획의 변경

- 복원 계층은 G2–G5의 hold 분기만 채운다. hw의 죽음 처리 코드를 직접 고치지 않는다.
- 로그, 체크포인트, 예비 프로세스는 정책이 hold이고 그 communicator가 `ncclGinRestoreResume`을 부른 뒤에만 켠다. fail-fast에서는 비용이 없다
  (측 표 포인터 0).
- TOLD 규칙(2.4절 2)과 X6 제약, 복원 뒤 생존 rank의 OFF 창(3절)을 설계에 더했다.
- 시제품은 멈췄다: 이 문서의 검토 전에 쓴 초안(로그 고리, 체크포인트 저장소, 복원 계획, CPU 모의)은 빌드도 실행도 하지 않았고, 저장소에 넣지 않고 세션
  스크래치 `agent_restore/proto_draft_unbuilt/`에 두었다. 시험 프로그램 `gin_rs.cu`는 쓰지 않았다.

## 5. 열린 충돌 (막는 문제)

해결이 없는 행이다. 하나라도 남아 있는 동안 복원 계층은 구현하지 않는다.

| id | 무엇 | 왜 막는가 | 풀 조건 |
|---|---|---|---|
| B1 | 예비 프로세스의 초기화 재생(C3) | NCCL bootstrap과 GIN collComm은 모든 rank가 함께 해야 한다. 기록된 결과로 대답하는 길이 NCCL 핵심의 초기화 전체(proxy, 런타임 연결, 대칭 메모리 등록)를 덮는지, 같은 devComm 모양을 만드는지 모른다 `[미확인]` | 초기화 재생 시험(빌드가 필요하므로 이 문서의 승인 뒤): 장애 없이 한 rank의 기록을 만들고, 예비 프로세스가 그 기록으로 초기화를 끝내 같은 rank, nRanks, 컨텍스트 수, 신호 수, window 크기를 얻는지 |
| B2 | LSA 팀(A4) | GPU 하나를 두 프로세스가 나눌 때 devComm의 `lsaSize`가 1인지 모른다. 2 이상이면 생존 rank의 load/store가 죽은 rank의 메모리를 계속 가리키고, 이것을 고치려면 생존 rank에서 CUDA 가상 메모리 호출이 필요하다(생존 rank는 CUDA 호출을 하지 않는다는 원칙과 충돌) `[추론]` | `lsaSize`를 읽어 확인. 2 이상이면 LSA 팀에 든 상대는 무장하지 않음(그 상대의 죽음은 fail-fast)으로 해결한 것으로 본다 |
| B3 | 체크포인트의 drain 확인(C1) | 응답 쪽 rmsn이 멈춤 때의 메시지 수에 이른 뒤 그 쓰기가 GPU 메모리에 보인다는 것은 NIC 루프백 READ 하나의 차례 보장에 기댄다(gin-remaining flush와 같은 가정, relaxed ordering 꺼짐) `[미확인: 이 하드웨어]` | 따로 재는 시험(NIC 게이트 시험과 같은 꼴) |

(검토 결과에 따라 늘어날 수 있다. 6절.)

## 6. 독립 검토

- 검토 1: EXPERIMENT.md 초안의 상호작용 표(9.10절)를 코드와 대조한 읽기 전용 검토. 결과는 아래에 반영한다(진행 중).
- 검토 2: 이 문서를 코드와 대조한 읽기 전용 검토(문서 완성 뒤).

## 7. 참고

- [EXPERIMENT.md](EXPERIMENT.md) 9.1–9.8절(복원 설계)
- `../remaining/EXPERIMENT.md` 9절 1번 (c), (f)
- gpu-detect worktree `harness/gpu-detect/EXPERIMENT.md` 9.1절(hw), 9.2절(t1w), 18, 19절
