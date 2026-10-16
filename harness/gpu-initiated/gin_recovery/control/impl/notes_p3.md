# gin-control 3단계(rank 쪽 launcher) 작업 기록

## 단계 목록 (처음에 적은 계획)

1. `agent_gc_p3/`: int 트리 복사, "gin-control int+fix12 (gc_layer_int.diff 60ca3cd9)" 커밋, 2b와 헤더 2b 적용, "gin-control + 2b" 커밋
2. `agent_gc_p3/build_gc_p3.sh`(키 p3, 고정 입력 `pin/`, `testpin/`), 바탕 확인(`syn`, `api`)
3. 헤더 요청 `rs_ctrl_api_p3.diff`: "[3] launcher" 하위 블록(상수, 진입점 선언), repaste
4. 영역 "gin-control (launcher)": launcher 헤더 붙임(바이트 그대로), 순수 고리(Unix 소켓 말, 무장 보기, 펜스, 활성화 중계 상태 기계, 박동 감시, 줄 글)
5. 호스트 몫: 등록(REGISTER, SPARE_HELLO), LEAVING, fork 닫기, `gdakiCtrlLauncherSend`, `gdakiCtrlOnHoldStart`, `gdakiCtrlLauncherFree`, 걸쇠
6. ln4 줄의 `#if` 갈래: `haveSpare`(무장), STORE_REQ 꼬리, 활성화 결정의 등록 검사, `gdakiHoldActivateSend`, `gdakiRsSpareActivateWait`, 관문의 `/proc` 갈래 지움
7. `syn`, `api`, `sites`
8. `gc_unit_p3.cc`(ASan, UBSan; launcher core와 프로세스 안 전송), `unit` 두 빌드
9. 빌드 넷, `pre`, `ident`, `diff`, `info`
10. 이 문서 마무리

## 끝낸 단계 (한 단계 한 줄)

- 1 끝: `agent_gc_p3/`(nccl-src와 빌드 넷 복사, .d와 manifest 경로 다시 씀), 커밋 a2859c4 "gin-control int+fix12 (gc_layer_int.diff 60ca3cd9)"(ln4 대비 diff md5 `60ca3cd9` 확인), 2b diff `fa3f1b48` 적용 + 헤더 2b 요청 적용(고정 헤더 `pin/rs_ctrl_api.h` `6c01c6ff`, repaste, 저장소 순수 영역의 같은 머리 정의를 지움), 커밋 e3faf02 "gin-control + 2b (gc_layer_p2b.diff fa3f1b48)"
- 2 끝: `agent_gc_p3/build_gc_p3.sh`(p2b 스크립트 사본, 키 p3, `pin/`, `testpin/`, `unitp3`), 바탕에서 `api`, `syn` 통과(`logs_p3/api_base.log`, `syn_base.log`)
- 3 끝: 헤더 요청(`pin/rs_ctrl_api.h`: API "[3] launcher" 하위 블록에 상수, launcher 길 등록 32 B, FENCED 표시 함수; seams "[3] launcher" 진입점 선언 12개), repaste, `api` 통과(`api_s3.log`)
- 4–5 끝: 영역 "gin-control (launcher)"(launcher 헤더 붙임 + link + host)을 준비 영역 "[3] launcher" 하위 영역에, 둘째 영역(짝의 활성화, 예비 프로세스의 기다림)을 gin-mirror (spare) restore path 끝 뒤에; 매개변수 둘(`NCCL_GIN_CTRL_LATER_MS`, `_LAUNCHER_STALL_MS`); `syn` 세 빌드 통과(`syn_s4b.log`; 첫 판은 매개변수 정의 없음)
- 6 끝: ln4 줄의 갈래(`#if NCCL_GIN_CTRL_TCP`로 ln4 글, `#else` 3단계): 무장의 `haveSpare`, STORE_REQ 꼬리의 등록, 활성화 결정의 PID와 시작 시각 검사, `gdakiHoldActivateSend`의 보내기, `gdakiRsSpareActivateWait`의 활성화 소켓; rdma만의 한 줄 넷(`gdakiTsStart` 등록, `gdakiTsMain` 걸음, `gdakiTsStop` LEAVING, 예비 프로세스 꼬리); 1단계 `gdakiCtrlActFenceOk`가 FENCE 걸음을 부르고 `/proc` 갈래 없이 FENCED만; `syn` 통과(`syn_s6b.log`; 첫 판은 안 쓰인 `ts` 경고 하나)
- 7 끝: `api`(launcher 헤더 붙임이 `launcher_msg.h` 897641f3과 바이트 같음 검사를 더함) 통과, `sites` 통과: 표 149행 그대로, `#if NCCL_GIN_CTRL_TCP` 갈래 43개 모두 ln4 글(`api_s7.log`, `sites_s7.log`)
- 8a: `gc_unit_p3.cc` 개발 고리(`unitp3`, rdma): 첫 판 3 실패(hold 시작의 무장이 펜스 낱말을 올린 말의 종류를 지움, launcher 잃음에서 ABORT 뒤 상태를 LOST로 덮어씀) → 고침, 11 장면 3 255 검사 실패 0, ASan과 UBSan 보고 0(`unitp3_s8a.log`, `unitp3_s8b.log`)
- 8 끝: `unit` 두 빌드 통과(옛 시험 일곱, gc_unit_prep, p1, gate_fenced, p2, p2b 수가 int와 2b 그대로; gc_unit_p3 rdma 11 장면 3 255 검사, tcp는 영역 없음 0 검사), `unit_s8.log`
- 9 끝: 빌드 넷 빌드됨(경고 0, 다시 컴파일한 것은 호스트 파일과 git_version 둘, devsync 0), `pre`(gct, gctp 0 hunk; gctc RST 간격 2 hunk 3줄), `ident`(아래 표; gcp, gctp의 `device_glue.o` 하나가 SASS 다름으로 나왔으나 그 객체는 ln4와 바이트 같고 따로 다시 돌린 `cuobjdump -sass` 세 개가 같음), `diff`, `info`
- 10 끝: 이 문서

## 무엇을 했나

트리는 스크래치 `agent_gc_p3/`다(ln4 커밋 f53e5d2 → prep-fix 2fc04b6 → int b80ebda → 이 작업이 만든 int+fix12 a2859c4 → 2b e3faf02; 3단계는 그 위의 작업 트리). 호스트 파일 하나만 바뀌고 장치 코드는 0줄이다. 클러스터, ssh, verbs 장치, GPU 실행은 없다. 저장소에는 `git add`, commit, push를 하지 않았다. launcher 프로그램은 실행하지 않았고, 단위 시험이 그 상태 기계(`gin_launcher.c`, `-DGL_NO_MAIN -DGL_NO_VERBS`)를 프로세스 안 시험 전송으로만 돌렸다. 표시: `[측정]` 이 작업이 돌려서 본 것, `[소스]` 코드를 읽어 확인, `[추론]` 해석, `[미확인]` 확인 안 함.

구현한 것(rdma 빌드만; tcp 빌드는 ln4 그대로, `pre` 0 hunk):

1. **launcher 헤더를 호스트 파일에 바이트 그대로.** 영역 "gin-control (launcher)" 머리에 `launcher/launcher_msg.h`(897641f3)를 붙였다. `build_gc_p3.sh api`가 바이트 같음을 본다 `[측정]`.
2. **노드 안 Unix 소켓(link 영역).** 경로는 `NCCL_GIN_CTRL_LAUNCHER_SOCK`, 없으면 launcher의 기본 경로(`gl_default_sock_path`와 같은 규칙). `SOCK_SEQPACKET | SOCK_CLOEXEC`로 잇고, `pidfd_open(getpid())`를 SCM_RIGHTS로 넘긴 뒤 이쪽 사본은 닫는다. 등록한 연결은 프로세스가 사는 동안 열어 두고 `pthread_atfork`의 자식 처리기가 fork한 자식에서 닫는다. REGISTER(rank), SPARE_HELLO(예비 프로세스; 0이 아닌 nonce와 1 이상의 화신을 link가 먼저 요구), LEAVING(등록한 연결로만), SPARE_STATUS READY/REPLAY_FAILED, ACT_TALK(ANSWER, FETCH_EP, FETCH_DONE), 받기는 HELLO_ACK, ACT_BYTES(기록 + 덩어리), ACT_TALK(FETCH_READY, ABORT). 상대 쪽이 닫히면 `launcher Unix socket closed (EOF|<errno 낱말>)` 줄 하나.
3. **등록(호스트).** `gdakiTsStart`(setup thread, 1단계 페이지 다음)에서 복원을 청한 프로세스만: rank는 REGISTER(rank, 화신 = `gdakiRsSelfInc`, nonce), 예비 프로세스(`NCCL_GIN_RESTORE_SPARE`)는 SPARE_HELLO(rank, `NCCL_GIN_RESTORE_SPARE_INC`(기본 1), nonce). 답은 1 000 ms까지 기다린다. `NCCL_GIN_CTRL_LAUNCHER_NODE`가 있으면 HELLO_ACK의 노드 번호와 같아야 한다. 실패는 WARN 한 줄이고 그 rank는 무장되지 않는다(fail-fast로 바꾸는 Resume 조건 41은 2a-2 몫, notes_p2.md 8번).
4. **LEAVING.** `gdakiTsStop`에서 증인의 BYE(`gdakiTsCloseAll`) 바로 앞. 줄 `LEAVING (incarnation %u) to the launcher of node %u`.
5. **launcher와의 짝 맺기(link).** launcher마다 기록 QP 하나, gin-control (ring)의 짝 맺기 모형(`gdakiCtrlPairSt`, `from` = `GL_FROM_LAUNCHER | node`)으로: PAIR(record, gen)에 `glPairBody`(이 rank의 QP, UD, 페이지, `creditOff`), PAIR_ACK에 RTR/RTS와 CONNECTED를 먼저; launcher가 시작한 다시 짝 맺기(PAIR → TAKE → PAIR_ACK, CONNECTED를 받으면 UP). 예비 프로세스는 활성화 전에 짝을 맺지 않는다(`pairOk`): launcher의 `gl_on_pair`는 더 높은 화신의 PAIR에 그 rank의 옛 QP를 닫으므로, 원래 프로세스가 사는 동안 예비 프로세스가 짝을 맺으면 원래 rank의 launcher 길이 끊긴다 `[소스: gin_launcher.c gl_on_pair]`. 전송(UD 보내기, QP 만들기와 잇기, 기록 QP 보내기)은 표(`gdakiCtrlLaTx`)로 받고, 호스트의 표는 아직 늘 실패한다(TODO(2a-2)).
6. **무장.** `haveSpare` = `gl_path_exists`(link의 `glArmView`: own launcher의 HELLO_ACK OK와 그 화신, own 기록 QP CONNECTED, REG_NOTE의 등록 낱말 ALIVE와 그 화신, 예비 자리 낱말 REPLAYING/READY/OFFERED의 inc + 1, 모든 launcher와 짝 맺음(`nLaunchers`개 모두), LEAVING 안 보냄). CKPT_STABLE의 `armable`이 이것을 쓴다.
7. **STORE_REQ 꼬리.** rdma 빌드에서 `gdakiStoreReqSpare`의 32 B 주소 칸에 `gdakiCtrlLaSpareReg`(magic "GRSL", 판 2, 길 = launcher, 노드, rank, 화신, 길 깃발), pid와 시작 시각 0, `haveSpare` = 길이 있음. 짝의 결정은 PID와 시작 시각 검사 대신 `gdakiCtrlLaSpareRegCheck`(그 ward, 죽은 화신, 길 깃발, 그 노드 launcher가 알려짐)로 가른다.
8. **걸쇠와 관문.** own launcher와 짝을 맺고 launcher가 이 화신을 ALIVE로 쥐면 `gdakiCtrlLauncherPairedLatch`(한 번, 내려가지 않음)와 줄 하나. 1단계 `gdakiCtrlActFenceOk`는 rdma 빌드에서 `/proc` 갈래를 지우고 FENCED만 요구한다(`gdakiCtrlActGate(true, …)`; 고칠 것 5). 펜스 낱말은 launcher link의 것(EXITED, FENCED로만 오름, 계보가 CURRENT나 HELD_OLD일 때만, 내려가지 않음)이고 1단계 페이지의 `fencedPlus1`에 사본(`gdakiLnFenced`)과 `fenceSent`를 둔다.
9. **펜스(짝).** `gdakiCtrlOnHoldStart`(모든 생존 rank): 그 (p, i)의 펜스를 무장하고 창 줄의 칸(그 상대 QP들의 응답 쪽 순번, `doca_verbs_qp_query_seq`)을 찍어 두며, 짝이면 SPAWN(p, i + 1)을 낸다(REFUSED는 줄 하나, fallback 아님). 모든 HOLDING이 모여 활성화 결정이 `gdakiCtrlActFenceOk`를 부르면 짝은 낱말이 FENCED가 아닐 때 FENCE(p, i)를 p 노드 launcher에 한 번 보내고 FENCING 줄. FENCED나 EXITED로 낱말이 서면 짝의 FENCED 줄, 생존 rank마다 창 줄. FENCE_NAK, launcher 잃음, 그 노드 launcher 모름은 곧바로 fallback.
10. **활성화(짝, `gdakiHoldActivateSend`의 rdma 몸).** 첫 걸음: 기록(pid, 시작 시각 0, `reserved` = 펜스 낱말 = 새 화신: FENCED를 싣음)과 mirror나 저장소 켬이면 drain과 덩어리(gin-mirror 그대로)를 outbox에 두고 ACTIVATE. 그 뒤 걸음마다 답을 본다(20 ms 다시 묻기 없음): LATER는 한 번만 받고(둘째는 줄 하나로 버림) 그때부터 `NCCL_GIN_CTRL_LATER_MS`(1 000) 안에 마지막 답이 없으면 ABORT와 fallback; 첫 답이 `GDAKI_CTRL_LA_ANSWER_MS`(1 000) 안에 없으면 ABORT와 fallback; launcher 잃음(기록 QP 오류, 또는 끌어 읽은 페이지의 박동이 `NCCL_GIN_CTRL_LAUNCHER_STALL_MS`(1 000) 동안 그대로)은 `(STOP_launcher)` 줄과 fallback; REFUSED는 곧바로 fallback. ACCEPTED(답이 그 rank와 화신을 되풀이) 뒤 1 000 ms 안의 FETCH_EP로 짝의 FETCH QP를 잇고 READY(72 B)를 launcher로, FETCH_DONE은 gin-mirror의 FETCH waiter(그대로)가 읽는 socketpair로 넘긴다. 활성화 줄은 ln4 글 그대로이고 'later' 수는 launcher가 대신 답한 LATER 수(0 또는 1).
11. **예비 프로세스(`gdakiRsSpareActivateWait`의 rdma 몸).** FETCH 버퍼 다음 READY를 launcher에, ACT_BYTES를 기다림(`NCCL_GIN_RESTORE_SPARE_WAIT_MS`). 기록 검사(magic과 kind ACTIVATE, nonce와 rank, HELLO의 화신, FENCED를 싣음; `/proc`은 보지 않음), mirror나 저장소 켬이면 덩어리를 socketpair에 담아 gin-mirror의 `gdakiMiActRecv`가 그대로 읽는다. ACCEPTED/REFUSED를 ANSWER로. ACCEPTED 뒤 FETCH 이야기는 socketpair 한쪽(`actFd`)과 중계 스레드(112 B → FETCH_EP, FETCH_READY → 72 B, 80 B → FETCH_DONE, ABORT나 소켓 잃음이면 닫음)라서 `gdakiMiSpareActivateFetch`가 바이트 그대로 돈다. FETCH가 끝나면 중계를 끝내고 새 화신으로 REGISTER(launcher가 pidfd를 바꿈)하고 짝 맺기를 연다.
12. **되살린 rank의 다시 무장.** 다시 REGISTER가 받아들여지고, 모든 launcher와 짝을 맺고(`nLaunchers`개), 다음 화신(i + 2)의 예비 프로세스가 HELLO 이상이어야 `gl_path_exists`가 참이다. 단위 시험이 차례를 본다(아래).
13. **`gdakiCtrlLauncherFree`.** 중계 스레드를 끝내고 Unix 연결(fork 감시에서 뺌)과 FETCH_DONE socketpair를 닫는다.

## 설계의 자유 안에서 정한 것

1. 펜스 낱말의 주인은 launcher link다. 1단계 페이지는 `NCCL_GIN_CTRL_PAGE=1`일 때만 서므로(기본 0) 낱말이 페이지에만 있으면 페이지 없는 문맥은 활성화할 수 없었다 `[소스]`. 페이지에는 사본을 둔다.
2. "FENCED를 싣는 활성화 기록"은 `gdakiRsActivate.reserved` = 죽은 화신의 펜스 낱말(= 새 화신)이다. launcher는 기록의 이 칸을 건드리지 않고 넘긴다(`gl_handover`가 64 B를 그대로 복사) `[소스]`.
3. launcher 길 등록은 판 번호를 올린 새 구조가 아니라 gin-mirror `gdakiStoreReqSpare`의 32 B 주소 칸에 넣었다(`rs_store_api.h` 사본을 만들지 않음; STORE_REQ의 바이트 배치 그대로). 9.8절 "판을 올린 `rs_store_api.h`의 사본은 impl/에"와 다르다: 그 사본 없이 같은 뜻을 낸다 `[추론]`.
4. 창 줄의 "칸"은 그 상대로 가는 생존 rank QP들의 응답 쪽 순번(`doca_verbs_qp_query_seq`)이다. hold 시작(판정 직후, 시작 정지 뒤)에 찍고 FENCED/EXITED 때 견준다. 읽지 못한 QP는 `unreadable=`로 따로 센다. 낱말 `fence`는 FENCED로, `judgement`는 EXITED로 선 경우다. ERR 상태 QP에서 그 순번 질의가 되는지는 `[미확인]`이다(첫 smoke에서 `unreadable`로 보임).
5. LATER 뒤의 한도, 첫 답 한도, launcher 박동 한도는 모두 짝(rank 쪽)이 센다(사용자 결정 4: 1 000 ms). 박동은 한 번이라도 읽힌 뒤에만 센다(읽는 길이 아직 없음: TODO(2a-2)).
6. FENCE_NAK은 곧바로 fallback이고 rank 쪽 줄을 하나 남긴다(launcher 쪽은 `(STOP_launcher)` 줄).
7. 예비 프로세스는 SPARE_PORT의 숫자 검사를 그대로 거친다(`gdakiRsSpareResume`의 ln4 검사; rdma 빌드에서 그 포트는 열지 않음).
8. 활성화 소켓 길의 TCP 함수(`gdakiMiSendActivate`, `gdakiRsSendActivate`, `/proc` 관문)는 rdma 빌드에서 부르지 않지만 지우지 않았다(4단계 몫). 빌드 경고 0 `[측정]`.

## 시험 쪽 질문의 답 (`test/notes_test.md` TODO 4)

1. **env 이름.** rank와 예비 프로세스 모두 `NCCL_GIN_CTRL_LAUNCHER_SOCK`(없으면 launcher의 기본 경로 `$XDG_RUNTIME_DIR/gin-launcher/launcher.sock`, 그것도 없으면 `/tmp/gin-launcher-<uid>/launcher.sock`)과 `NCCL_GIN_CTRL_LAUNCHER_NODE`(선택; 있으면 launcher의 HELLO_ACK 노드와 같아야 하고 다르면 등록 실패 줄, 그 rank는 무장 안 됨)를 읽는다(launcher 헤더 `GL_SOCK_ENV`, `GL_NODE_ENV`) `[소스]`.
2. **`NCCL_GIN_RESTORE_SPARE_INC`.** 예비 프로세스가 SPARE_HELLO의 화신으로 읽는다(기본 1, 0이나 숫자 아님이면 HELLO 없음). ACTIVATE의 화신이 이것과 다르면 예비 프로세스가 REFUSED한다(검사 3). `run_gc.sh`의 둘째 예비 프로세스 `=2`가 맞다 `[소스, 단위 시험: 검사 3]`.
3. **`SPARE_ADDR`/`SPARE_PORT`.** rdma 빌드의 원래 rank는 `NCCL_GIN_RESTORE_SPARE_ADDR`를 무장과 등록에 쓰지 않는다(`gdakiCkptSelfOf`는 읽지만 rdma 갈래가 그 값을 쓰지 않음). 예비 프로세스는 `NCCL_GIN_RESTORE_SPARE_PORT`가 포트 숫자인지 ln4 검사를 그대로 받지만 그 포트를 열지 않는다. 실행기가 둘을 계속 주어도 해가 없다 `[소스]`.
4. **비용 셀의 측정 모드.** launcher 짝 맺기를 요구하지 않는다. `run_cost_gc.sh`의 `NCCL_GIN_FAULT_POLICY=hold NCCL_GIN_RESTORE=1`이면 등록(Unix 소켓)만 setup 때 한 번 하고, 실패해도 줄 하나뿐이다(Resume 조건 41은 아직 없음, 2a-2). launcher QP는 2a-2 전에는 만들어지지 않는다 `[소스]`.
5. **launcher QP 잃음 줄.** launcher 쪽 `record QP of rank %d … lost`, `liveness-READ QP of rank %d failed`는 지금 규칙(시행 `trial_start` 뒤, 첫 "is leaving" 전, 대상 rank 밖)대로 세면 된다. rank 쪽에서 3단계가 내는 잃음 줄은 활성화나 펜스 중에만 나고 그 복원을 fallback으로 끝내므로 모두 센다: `the launcher of node %u is lost (record_QP_error|beat_stale|not_paired) during rank %d's activation (incarnation %u): falling back (STOP_launcher)`, `rank %d (incarnation %u) fence: the launcher of node %u is lost (%s) (STOP_launcher)`. 지금 `rows_gc.py`의 `LA_STOP`은 launcher 조각만 보므로 rank 쪽 `(STOP_launcher)`를 세려면 rank 로그에도 같은 정규식을 걸어야 한다. `launcher Unix socket closed (%s)`는 launcher 쪽이 닫았을 때만 나고(자기 close에는 줄 없음) 8절의 "그 Unix 소켓이 끊김"이다 `[소스]`.

## 내는 줄 (정확한 글; 끝에 ` mono_ms=%.3f`)

| 줄 | 꼴 | 누가 |
|---|---|---|
| FENCING | `GIN/RC: rank %d: rank %d (incarnation %u) fence FENCING: FENCE sent to the launcher of node %u` | 짝 |
| FENCED | `GIN/RC: rank %d: rank %d (incarnation %u) fence FENCED (by FENCED\|EXITED from node %u)` | 짝(낱말이 선 때, hold 전 EXITED면 hold 시작 때) |
| 바뀐 칸 | `GIN/RC: rank %d: window check after the fence\|judgement of rank %d: changed=%u cells against=snapshot_at_judgement unreadable=%u` | 생존 rank마다 |
| FENCE_NAK | `GIN/RC: rank %d: rank %d (incarnation %u) fence FENCE_NAK from node %u: nothing held, falling back` | 짝 |
| 펜스 중 잃음 | `GIN/RC: rank %d: rank %d (incarnation %u) fence: the launcher of node %u is lost (%s) (STOP_launcher)` | 짝 |
| 활성화 중 잃음 | `GIN/RC: rank %d: the launcher of node %u is lost (%s) during rank %d's activation (incarnation %u): falling back (STOP_launcher)` | 짝 |
| 소켓 끊김 | `GIN/RC: rank %d: launcher Unix socket closed (%s)` | rank, 예비 프로세스 |
| 등록 | `GIN/RC: rank %d: registered incarnation %u at the launcher of node %u (page slot %u)`; 예비 `… spare said HELLO as incarnation %u …`; 실패 `GIN/RC: rank %d: REGISTER\|spare HELLO of incarnation %u at the node's launcher failed (%s): no launcher path, this rank is not armed` | rank, 예비 |
| 걸쇠 | `GIN/RC: rank %d: paired with the launcher of node %u, which holds incarnation %u: the activation gate requires FENCED` | rank |
| 짝 맺기 | `GIN/RC: rank %d: record QP to the launcher of node %u paired (gen %u)`, `… re-paired (gen %u)`, `GIN/RC: rank %d: PAIR(record, gen %u) refused by the launcher of node %u (%s)` | rank |
| LEAVING | `GIN/RC: rank %d: LEAVING (incarnation %u) to the launcher of node %u` | rank |
| SPAWN | `GIN/RC: rank %d: the launcher of node %u refused SPAWN of rank %d (incarnation %u): spawn not built; no fallback on it` | 짝 |
| LATER | `GIN/RS: rank %d: rank %d's spare answered 'later' through the launcher of node %u (replaying for %u ms); waiting at most %.0f ms for its READY`; 둘째 `GIN/RC: rank %d: a second LATER for rank %d (incarnation %u) from node %u: ignored` | 짝 |
| 활성화 | `GIN/RS: rank %d: every survivor holds rank %d: its spare activated (incarnation %u, %.1f ms after this rank's hold start), %d 'later' answers over %.1f ms`(ln4 글) | 짝 |
| FETCH | `GIN/MI: rank %d: rank %d's spare is READY to FETCH checkpoint %lu through the launcher of node %u`; 실패는 ln4 글 | 짝 |
| 예비 | `GIN/RS: spare rank %d: READY (incarnation %u) to the launcher of node %u; waiting for the activation`, `… activating incarnation %u from step %llu (through the launcher of node %u: FENCED carried)`, `… activation refused (%s)`, `… no ACTIVATE from the launcher within %d ms` | 예비 |
| 계보 | `GIN/LN: rank %d: EXITED\|FENCED of rank %d incarnation %u from node %u is not this lineage's (FUTURE or STALE): the fence word stays` | rank |

fallback 까닭(`gdakiHoldFallback`의 글): `the peer's spare is not READY 1000 ms after LATER (ABORT sent)`, `no answer of the launcher to the activation within 1000 ms`, `the peer's spare refused the activation (launcher: %s)`, `the fence of the peer's dead incarnation cannot complete (FENCE_NAK, no launcher path, or the launcher is lost)`, `no launcher path for the peer's activation (TODO(2a-2): the ring and its outbox)` 등.

## TODO(2a-2) (코드의 표시)

1. 호스트 전송 표 넷(`gdakiCtrlLaTxUd`, `gdakiCtrlLaTxCreate`, `gdakiCtrlLaTxConnect`, `gdakiCtrlLaTxSend`): 링의 UD 보내기(봉투 kind PAIR, 본문 256 B `glMsg`), 링 peer 목록의 launcher 자리(nranks + li, `gdakiCtrlQpAttrLauncher`), LAUNCHER 봉투의 기록 QP 보내기(ackSeq = 페이지 `rxConsumedL[li]`). 지금은 늘 -1이라 rdma 빌드에서 launcher와 짝을 맺지 못하고 아무 rank도 무장되지 않는다.
2. 링의 받기가 launcher의 봉투(UD PAIR, PAIR_ACK; 기록 QP의 LAUNCHER)를 `gdakiCtrlLauncherOnEnvelope`로 넘김(지금 UD 받기는 launcher datagram을 `badDgrams`로 버림).
3. all-gather의 launcher 칸: launcher 수(`k.nLaunchers`), rank마다의 launcher 노드(`gdakiCtrlLaSetRankNode`), 다른 launcher의 UD 끝점과 Q_Key와 페이지(`gdakiCtrlLaAddLauncher`), 이 rank의 UD 끝점, 페이지, `creditOff`(`k.ud`, `k.page`, `k.creditOff0`).
4. 활성화 덩어리의 outbox 자리(`gdakiCtrlLaOutboxPut`: 링 outbox 반 하나, REMOTE_READ). 지금은 빈 덩어리만 갈 수 있고 mirror나 저장소 켬의 활성화는 "no launcher path" fallback이다.
5. launcher 페이지 끌어 읽기(감시 스레드의 launcher READ 칸, 생존 READ QP의 PROBE PAIR) → `gdakiCtrlLaOnBeat`. 그 전에는 박동 한도가 세지 않는다.
6. 링 쪽 2b의 TODO(2a-2) 다섯(STATE와 rkey의 outbox, 메모리 줄)은 2b의 것 그대로.
7. Resume 조건 41(복원을 청했는데 own launcher와 짝 맺지 못함 → fail-fast)은 notes_p2.md 8번대로 2a-2의 Resume 검사 자리에.

## 합칠 때 볼 것 (2a-2 트리와)

- 3단계가 2a-2와 같은 함수에 한 줄씩 넣은 자리: `gdakiTsStart`(1단계 `gdakiPageSetup` 다음 줄), `gdakiTsMain`(1단계 `gdakiCtrlPageHelperStep` 다음 줄), `gdakiTsStop`(`gdakiTsCloseAll` 앞 `#if` 셋 줄). 2a-2가 같은 자리에 줄을 넣으면 줄 하나 겹침이다 `[추론]`.
- 헤더: 이 트리의 고정 헤더는 948b3ecf + `rs_ctrl_api_p2b.diff` + `rs_ctrl_api_p3.diff`다. 2b 요청을 적용하며 저장소 순수 영역의 같은 머리 정의를 지웠다(commit e3faf02 안).
- seam 몸과 `gdakiTsSetupConnect`는 손대지 않았다 `[측정: diff의 hunk 머리]`.

## 수

- `gc_layer_p3.diff`: 2b 커밋 e3faf02 대비 2 407줄, 호스트 파일 하나, 더하기 2 254줄, 빼기 21줄, 장치 코드 0줄 `[측정]`.
- 그 가운데: launcher 헤더 붙임 546줄(마커 둘 포함), link 영역 1 050줄, host 몫 306줄, 짝 활성화와 예비 기다림 영역 220줄, 붙인 헤더 블록의 바뀜(API "[3] launcher" 하위 블록, seams 진입점), ln4 줄 `#if NCCL_GIN_CTRL_TCP` 갈래 다섯(무장, STORE_REQ 꼬리, 결정의 등록 검사, 보내기, 예비 활성화 소켓; 2b의 `mi` 갈래 하나는 보내기 갈래 안으로 들어가 없어짐: 39 → 43), rdma만의 한 줄 넷, 1단계 `gdakiCtrlActFenceOk`의 FENCE 걸음과 `/proc` 갈래 지움 `[측정: awk, grep]`.
- 호스트 파일 29 973(2b 커밋) → 32 212줄, md5 `a7152a8f` `[측정]`.
- `rs_ctrl_api_p3.diff` 79줄(2b 적용 헤더 `6c01c6ff` 대비; 결과 헤더 `44c17ffc`, 1 164줄) `[측정]`.
- `gc_unit_p3.cc` 1 007줄, rdma 11 장면 3 255 검사 실패 0, tcp 0 검사 `[측정, n 1]`. 장면: 순수(env 셋, FENCED 표시 999 화신), 등록(실제 자식의 pidfd, `FD_CLOEXEC`, fork한 손자에서 닫힘, launcher 항목의 pid가 자식), LEAVING → LEFT(낱말 그대로), kill → EXITED → 낱말, hold 시작에 "by EXITED" FENCED 줄과 창 줄, FENCE 안 보냄, 옛 화신의 끝은 새 화신을 풀지 않음, 계보 밖 EXITED는 낱말 그대로; SIGSTOP → FENCE → launcher SIGKILL 한 번 → FENCED와 낱말, FENCING/FENCED/창 줄, 자식이 SIGKILL로 끝남; FENCE_NAK → -1, 신호 0; LATER 한 번 → READY 뒤 넘김(덩어리 3 000 B가 outbox와 같음) → 기록 검사 넷 → ACCEPTED → FETCH 이야기 세 조각이 중계로 바이트 같음, SPAWN REFUSED는 줄만; 되살린 rank가 다시 REGISTER(launcher의 promote 1), own launcher만 짝 → 길 없음, 다음 예비 HELLO → 아직 없음, 둘째 launcher 짝 → 길 있음, 그 예비가 끝남 → 길 없음; LATER 뒤 1 000 ms → ABORT와 fallback(LATER에서 fallback까지 1 000–1 100 ms 안), launcher가 예비 프로세스를 ABORTED로 두고 그 grace 뒤 SIGKILL; launcher 멈춤 → 박동 1 000 ms 그대로 → `(STOP_launcher)` 줄과 fallback(1 000–1 200 ms 안), 첫 답 없음 1 000 ms, 기록 QP 오류 곧바로; 무장(예비 없음 → 길 없음, HELLO → 길, `gl_armable`, 등록 꼬리 검사, launcher 수 0이면 없음, LEAVING이면 없음); Unix 소켓 끊김 줄 한 번.
- 시간 검사의 범위는 이 한 번의 실행(n 1) 안의 검사 한도이고 잰 값의 범위가 아니다.

## 확인 표 (이 작업이 돌린 것만; 로그는 `agent_gc_p3/logs_p3/`)

모두 `SCR=<세션 스크래치> BR=p3 agent_gc_p3/build_gc_p3.sh <단계>`(`agent_gc_p3/p3.sh`가 감쌈). ssh, 클러스터, verbs 장치, GPU 실행 없음.

| 단계 | 결과 | 로그 |
|---|---|---|
| `repaste`, `api` | 붙인 블록 둘이 고정 헤더(`pin/rs_ctrl_api.h` `44c17ffc`)와 바이트 같음, launcher 헤더 붙임이 `launcher_msg.h` 897641f3과 바이트 같음, 헤더 단독 컴파일 rdma와 tcp, 진입점 선언 있음/없음, `NCCL_GIN_CTRL_TCP_CELLS=1` 단독 거절: 통과 `[측정]` | `repaste_s3.log`, `api_final.log` |
| `syn` | build, build-gcp, build-gct `-fsyntax-only` 통과 `[측정]` | `syn_s6b.log` |
| `sites` (tsv 057a6da0) | 표 149행과 트리의 rdma 쪽 셈이 모두 같음, `#if NCCL_GIN_CTRL_TCP` 갈래 43개 모두 ln4 글 그대로, 단계 영역 `#use` 같음(page 1 106, ring 1 828 코드 줄): 통과 `[측정]` | `sites_final.log` |
| `gc`, `gcp`, `gct`, `gctp` | 넷 모두 빌드됨, 경고 0, 다시 컴파일한 것은 호스트 파일과 git_version, devsync 0. libnccl gc `9fb267f0`, gcp `81ba0884`, gct `77ec1375`, gctp `7f839954` `[측정]` | `build_{gc,gcp,gct,gctp}_p3.log`, `out/*_p3/` |
| `pre` | gct, gctp 정규화 뒤 ln4와 0 hunk(150 748, 150 175줄); gctc 2 hunk 3줄(RST 거절 간격 매개변수 정의 한 줄과 `>= 1000.0` 한 줄); gc 83 hunk(새 코드, 기록용) `[측정]` | `pre_p3.log`, `out/pre/` |
| `unit` rdma | mi_unit 다섯, rs_unit_host 348 739, rs_spare_unit 171 실패 0; gc_unit_prep 366, gc_unit_p1 669 740, gate_fenced 10/10 64, gc_unit_p2 3 984 398, gc_unit_p2b 11 114, gc_unit_p3 3 255(11 장면) 모두 실패 0: 통과 `[측정, n 1]` | `unit_s8.log` |
| `unit` tcp | 옛 일곱 실패 0, gc_unit_prep 174, p1, p2, p2b, p3 0 검사: 통과 `[측정]` | `unit_s8.log` |
| `ident` (IDTAG=p3) | 설치 헤더 ln4와 같음; 매크로 없는 프로그램 16/16 SASS와 자원 같음; gc, gct 장치 객체 207/207 SASS 같음; gcp, gctp는 206 같음 + `device_glue.o` 1 다름으로 나옴, 그러나 207개 모두 ln4와 바이트 같음(장치 헤더 digest가 같아 다시 빌드되지 않은 사본). 그 객체를 따로 `cuobjdump -sass`로 다시 뽑으면 gcp, gctp, ln4 build-mip 셋이 같음(md5 `13cefe6b`, 11 272 196줄): 병렬 비교 중의 일시 출력 차이로 본다 `[측정; 추론]`; 라이브러리 넷 자원 사용 같음 | `ident_p3.log`, `ident_device_glue_recheck.log`, `out/ident_p3/` |
| `diff`, `info` | `gc_layer_p3.diff` `cca4bb18`, 2 407줄, e3faf02 대비, 거꾸로 적용 확인 `[측정]` | `diff_p3.log`, `info_p3.txt` |

## 빌드 스크립트 diff

`agent_gc_p3/build_gc_p3.sh`(861줄)는 `agent_gc_p2b/build_gc_p2b.sh`(b820d481) 사본에 키 p3를 더한 것이다: `DI` 기본 `agent_gc_p3/pin`(worktree HEAD 입력 + 2b와 p3 헤더 요청 적용), `TI` 기본 `agent_gc_p3/testpin`, 머리 커밋 "gin-control + 2b (gc_layer_p2b.diff fa3f1b48)", p3는 p1, p2, p2b의 영역 자르기와 시험을 모두 돌린 뒤 `gc_unit_p3.cc`(launcher core를 `-DGL_NO_MAIN -DGL_NO_VERBS`로 ASan, UBSan 빌드해 링크, 짧은 작업 디렉터리에서 실행), 영역 "gin-control (launcher): link" 자르기, `api`에 launcher 헤더 붙임의 바이트 비교, `unitp3`, `info`의 p3 파일. worktree `build_gc.sh`(5eaaf11e) 대비 전문은 `logs_p3/build_script.diff`(192줄), p2b 스크립트 대비는 `logs_p3/build_script_vs_p2b.diff`(155줄).

## 파일 md5 (worktree `control/impl/`, 이 작업이 만든 것)

| 파일 | md5 | 줄 |
|---|---|---|
| `gc_layer_p3.diff` | `cca4bb185489a3d1b077b0a1aa174558` | 2 407 |
| `gc_unit_p3.cc` | `7c15d2e7480c535b5d4e9c222e440a77` | 1 007 |
| `rs_ctrl_api_p3.diff` | `a68f92ec54d6c4d46f4794742e36931c` | 79 |
| `notes_p3.md` | (이 문서) | |
| 스크래치 `agent_gc_p3/build_gc_p3.sh` | `911eb3b1b2c93dc62a149e5829b8d063` | 861 |

바탕(고치지 않음): `rs_ctrl_api.h` 948b3ecf, `gc_layer_int.diff` 60ca3cd9, `gc_layer_p2b.diff` fa3f1b48, `rs_ctrl_api_p2b.diff` 216ba84a, `launcher/*`(launcher_msg.h 897641f3, gin_launcher.c 56c10d8e), `test/*`, `EXPERIMENT.md`, `../../mirror/*`, `build_gc.sh` 5eaaf11e.

## 미확인과 열린 것

- 장치와 클러스터에서 한 번도 돌지 않았다 `[미확인]`: 실제 launcher 프로그램(verbs 전송)과의 Unix 소켓, SCM_RIGHTS pidfd의 pid 검사(단위 시험은 같은 커널의 fork한 자식으로만), ERR QP의 순번 질의, sunny(6.8)의 pidfd.
- rdma 빌드는 2a-2 전에는 무장되지 않는다(launcher와 짝 맺기 길이 없음): 지금 rdma 빌드로 복원 셀을 돌리면 모두 무장 없음 fail-fast다 `[추론]`.
- 되살린 짝의 STORE_ACK 비트(설계 v3 5.4 7, 재검토 S14: w는 "w 노드 launcher와 짝 맺음" 비트가 있는 STORE_ACK을 받은 뒤에만 무장)는 넣지 않았다. 지금 무장 조건의 `allPaired`는 이 rank 자신의 짝 맺기만 본다.
- 9.8절 "판을 올린 `rs_store_api.h` 사본" 대신 주소 칸에 등록을 실었다(위 결정 3). 문서 문장을 고칠지 조율 세션이 정한다.
- FENCE_NAK 시행을 제외로 칠지 실패로 칠지(8절 열린 것)는 그대로다.

## EXPERIMENT.md 11절과 12절에 넣을 줄 (안)

- 11절: `- [ ] 3단계(rank 쪽 launcher: 등록과 LEAVING, 무장 = gl_path_exists, STORE_REQ 꼬리의 launcher 길, 펜스(FENCE, FENCED, 펜스 낱말, 줄 셋), FENCED만 요구하는 관문, launcher 중계 활성화(LATER 한 번, 한도 셋, ABORT), 예비 프로세스의 READY와 FETCH 중계, 되살린 rank의 다시 등록과 다시 무장): 빌드와 CPU 시험까지 — 2026-10-17, impl/gc_layer_p3.diff cca4bb18(int+fix12+2b 커밋 위). launcher와의 RNIC 길(짝 맺기 전송, launcher 봉투 받기, outbox, 페이지 끌어 읽기)은 TODO(2a-2); 되살린 짝의 STORE_ACK 비트는 남음`
- 12절: `| 2026-10-17 | 3단계 rank 쪽 구현(실행 없음, CPU와 빌드만). int+fix12+2b 커밋 위의 impl/gc_layer_p3.diff(cca4bb18, 2 407줄, 호스트 파일만, 장치 코드 0줄): launcher 헤더를 바이트 그대로 붙이고, Unix 소켓 등록(자기 pidfd, CLOEXEC, fork 때 닫음), LEAVING, 무장 = gl_path_exists, STORE_REQ 꼬리의 launcher 길 등록, 펜스 낱말을 launcher link가 쥐고 rdma 관문은 /proc 없이 FENCED만, 짝의 FENCE와 줄 셋, launcher 중계 활성화(LATER 한 번, LATER 뒤 1 000 ms, 첫 답 1 000 ms, 박동 1 000 ms, ABORT와 fallback), 예비 프로세스의 READY와 기록 검사(FENCED를 싣는 기록)와 FETCH 중계, 되살린 rank의 다시 등록. 헤더 요청은 impl/rs_ctrl_api_p3.diff. gc, gcp, gct, gctp 빌드됨(경고 0). tcp 전처리는 gct, gctp가 ln4와 hunk 0, gctc는 RST 간격 2 hunk만 [측정]. 단위 시험 두 빌드 통과, gc_unit_p3 11 장면 3 255 검사 실패 0(launcher 상태 기계와 실제 자식 프로세스) [측정, n 1]. 장치 동일성: 프로그램 16/16, 장치 객체는 다시 빌드되지 않은 사본(gcp, gctp의 device_glue.o 하나는 병렬 비교 출력이 달랐으나 바이트 같고 다시 뽑은 SASS 같음) [측정]. launcher와의 RNIC 길은 TODO(2a-2)라 이 빌드는 아직 무장되지 않음. 클러스터 실행 없음 | impl/notes_p3.md, 스크래치 agent_gc_p3/logs_p3/ |`
