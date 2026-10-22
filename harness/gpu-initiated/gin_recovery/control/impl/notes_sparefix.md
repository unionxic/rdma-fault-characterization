# gin-control sparefix: 따뜻한 예비 프로세스의 두 결함 (작업 기록, 2026-10-22)

첫 하드웨어 smoke([../results/20261022_smoke1/SMOKE.md](../results/20261022_smoke1/SMOKE.md), [notes_smoke.md](notes_smoke.md))의 a4와 a6이 보인 결함 둘을
고쳤다. 클러스터는 쓰지 않았고 CPU 단위 시험만 돌렸다. 표시: `[측정]` 돌려서 봄, `[소스]` 코드를 읽음, `[추론]` 해석, `[미확인]` 확인 안 함.

| 결함 | 어디서 보았나 | 고친 곳 |
|---|---|---|
| 예비 프로세스가 rank의 기록 파일(transcript)보다 먼저 떠서 `cannot open the transcript`로 네 번 끝나고 다시 띄우기 한도(STOP_launcher) | a4 | launcher: `--spare-wait-for`, 그리고 세지 않는 규칙 |
| HELLO 뒤 예비 프로세스 자신의 Resume이 조건 41로 거절(1 001.6 ms 기다린 뒤) | a6 | 호스트 파일: 활성화 전 예비 역할에는 41을 묻지 않음 |

## 1. 띄우는 때: launcher의 `--spare-wait-for` (a4)

**고른 길과 까닭.** 맡김 글의 안 (1)대로 launcher 쪽에 두었다. 예비 프로세스가 스스로 기다리는 안은 고르지 않았다.

- 기록 파일은 rank의 초기화 맨 앞(`rsBeginComm`)에서 `O_EXCL`로 만들어지고, 그 뒤 항목마다 덧붙여진다(항목마다 `fflush`). 끝났다는 표시는 없다
  `[소스: nccl-src/src/misc/rs_spike.cc:191–221, 86–104]`. 그래서 "파일이 있음"을 기다리는 것만으로는 다 쓰지 않은 기록을 읽을 수 있다. 이 점은 어느 쪽이 기다리든 같다.
  launcher 쪽이면 무엇을 기다릴지(패턴)를 실행기가 고를 수 있다.
- 예비 프로세스 쪽 기다림은 `misc/rs_spike.cc`를 고쳐야 한다. 이 층이 고치는 파일(`gin_host_gdaki.cc` 하나) 밖이다.
- 예비 프로세스는 기록을 읽은 뒤(초기화 replay 뒤)에야 HELLO한다. 그래서 그 안에서 기다리면 launcher의 HELLO 한도(`--spare-hello-ms`)가 SIGKILL한다
  `[소스: gin_launcher.c gl_kid_deadlines]`. launcher 쪽은 기다린 뒤에 띄우므로 HELLO 한도를 띄운 때부터 그대로 센다.

**바뀐 것**(`impl/launcher/`; `launcher_msg.h`는 그대로, md5 `fb11b235`).

- 옵션 `--spare-wait-for GLOB`(`gin_launcher.c:2482`). 주지 않으면 `--spare-env`의 `NCCL_GIN_RESTORE_REPLAY` 값이 기본이다(`gin_launcher.c:2516`). 그 값도 없으면 기다리지 않는다.
  `-`는 기다리지 않음이고, 빈 값은 거절한다. `glConfig.spareWaitFor`는 `gin_launcher.h:45`에 있다.
- 띄우기 앞의 기다림: 띄우기는 모두 `gl_spare_spawn`(`gin_launcher.c:930`)을 거친다. 시작, 활성화 뒤, 다시 띄우기, HELLO 재시도가 다 그렇다.
  - 패턴이 맞으면 곧바로 띄운다(`gl_spare_spawn_now`, `:817`).
  - 맞지 않으면 `gl_spare_wait_step`(`:947`, 부르는 곳 `:2240`, poll 시한 `:2211`)이 100 ms마다 `glob(3)`으로 다시 본다(`gl_wait_match`, `:920`).
  - 맞으면 띄운다. `--spare-hello-ms`가 지나도 맞지 않으면 그래도 띄우고, 그 띄움에 "기다림이 다 됨"(`waitUnmet`)을 적는다.
- 세지 않는 규칙(`gin_launcher.c:1075–1083`). 기다림이 다 된 띄움이 HELLO 전에 끝났고 그 로그 파일(끝 64 KiB)에 `GIN/RS: replay: cannot open the transcript`가 있으면
  다시 띄우기 한도에 세지 않는다(`gl_log_says_no_transcript`, `:972`; 글은 `gin_launcher.h:52`). 그때 줄 하나를 남기고 같은 화신을 다시 기다려 띄운다.
  - 그래서 이 되풀이는 `--spare-hello-ms`마다 많아야 한 번이다.
  - 기다림이 맞은 뒤 띄운 것이 같은 줄로 끝나면 센다. 패턴이 기록 파일이 아닐 때 그 되풀이가 한도에서 멈추게 하려는 것이다(시험 장면 (3)).
- 줄 다섯: 시작 때 `warm spare wait-for <GLOB> (...)`, `spare spawn waits (...)`, `spare wait-for matched after <X> ms (...)`, `... matched nothing within <H> ms (...): spawning anyway`,
  세지 않음 줄, shutdown 때 기다리던 띄움의 줄. 정확한 글은 [launcher/README_launcher.md](launcher/README_launcher.md) "줄"에 있다. 옛 줄의 글은 그대로다.
- 단위 시험(`launcher_unit.cc`): 계획 `t`(`:2321`)는 자기 `NCCL_GIN_RESTORE_REPLAY` 파일이 있으면 HELLO하고, 없으면 a4의 줄을 쓰고 2로 끝난다. 장면 `spare_wait_for`(`:2924`)는 넷이다.
  - (1) 파일이 없으면 시작 때 띄우지 않는다. 파일을 만들면 한 번 보는 사이에 띄우고 HELLO가 온다. 그 뒤 다시 띄우기는 기다리지 않는다.
  - (2) 400 ms 안에 파일이 없으면 그래도 띄운다. 세지 않음이 두 번 나와도 한도 1에서 포기하지 않는다. 그 뒤 파일이 생기면 셋째가 HELLO한다.
  - (3) 음성 대조: 기다림 패턴이 이미 있는 다른 파일이면 같은 끝남을 센다.
  - (4) 기다리는 동안 shutdown하면 줄 하나가 나오고, 띄움과 신호는 0이다.
  - `spare_opts`에 옵션 검사 13을 더했다.

**실행기에 줄 것**(`test/`는 고치지 않았다. 조율 세션이 적용한다).

- 최소: `test/run_gc.sh`의 `spare_opts`(442행 `SOPTS=(...)`)에 `--spare-hello-ms 30000`을 더한다. 그러면 기다림의 한도와 HELLO의 한도가 함께 30 s가 된다. 실행기가 이미
  `--spare-env NCCL_GIN_RESTORE_REPLAY=$(npath "$nd" "r$r.rec")`를 주므로 기본 패턴은 그 rank의 기록 파일이다(447행).
- 권함: `--spare-wait-for "$(npath "$nd" spare)/.go" --spare-hello-ms 30000`. 실행기는 그 rank의 `GINRS resume` 줄을 본 뒤 그 노드에서 `.go`를 만든다(a6 진단 사본의
  넷째 hunk, [../results/20261022_smoke1/run_gc_smokediag.diff](../results/20261022_smoke1/run_gc_smokediag.diff)). 그러면 사본 둘째 hunk인 `spare_exec.sh`의 기다림은 필요 없다.
  - 까닭 `[추론]`: 기본 패턴(기록 파일)은 rank가 초기화를 시작하자마자 맞는다. 예비 프로세스는 띄운 뒤 HELLO까지 397.9–448.5 ms였다(a6에서 다시 띄운 셋의 범위) `[측정: a6]`.
    기록은 그보다 앞서 읽는다. 그 사이 rank의 초기화(4 rank의 bootstrap, GIN 준비)가 끝나지 않았으면 덜 쓴 기록을 읽는다. 그러면 replay가 "a call after the end of the
    transcript"로 끝나고, 이 끝남은 센다(규칙은 "cannot open"만 뺀다). rank 초기화에 걸리는 시간은 재지 않았다 `[미확인]`.
  - `GINRS resume` 뒤에 만든 go 파일로는 a6에서 HELLO와 `spare_ready`까지 갔다 `[측정: a6, n 1]`.

## 2. Resume 조건 41: 활성화 전 예비 역할 (a6)

**규칙**(맡김 글의 결정 (2)). 예비 역할의 프로세스는 활성화 전에는 조건 41을 묻지 않는다. 설계상 그때는 자기 launcher와 짝을 맺지 않기 때문이다. helper는 REJOIN 뒤에야
돈다(설계 9.6 차례 (4)). 활성화와 다시 등록 뒤에는 다른 rank처럼 묻는다.

**바뀐 것**(호스트 파일 하나, `gc_layer_sparefix.diff`, smokefix 커밋 대비). 줄 번호는 스크래치 트리 `agent_gc_sparefix/nccl-src`의
`src/transport/net_ib/gdaki/gin_host_gdaki.cc`다.

- `:27273`: `gdakiCtrlLauncher::spare`를 `std::atomic<bool>`로 바꿨다. Resume이 `L->mu` 없이 읽기 때문이다. 쓰는 곳 둘은 그대로다: `gdakiCtrlLaMake`의 `L->spare = spare`,
  `gdakiCtrlLaSpareDone`의 `L->spare = false`(`:31928`, 활성화가 된 뒤 다시 등록 앞).
- `:33779–33781`(smoke 고침 1의 기다림): 그 context의 launcher 링크가 예비 역할이면 걸쇠를 기다리지 않는다. a6에서 쓴 1 000 ms가 여기서 없어진다.
- `:33824–33833`(`gdakiCtrlResumeFacts` 다음): 41이 섰고 그 링크가 예비 역할이면 41을 지운다. 그리고 INFO 줄 하나를 남긴다:
  `GIN/RC: rank %d: Resume condition 41 not asked: a spare before its activation pairs with no launcher`.
  - 42–44와 다른 조건은 그대로다.
  - `gdakiCtrlResumeConds`(순수 함수, `gc_unit_p2a2.cc`가 시험함)와 `gdakiCtrlResumeFacts`는 바꾸지 않았다. 그 둘이 있는 자리에서는 `struct gdakiCtrlLauncher`가 아직
    정의되지 않았고, 그 시험 파일은 다른 작업이 고치는 중이라 손대지 않았다.
- 활성화 뒤: 이 driver에서 예비 프로세스의 Resume 판정은 활성화 전에 한 번뿐이다. 판정 뒤 `gdakiRsSpareResume` 안에서 활성화되고, 둘째 부름은 첫 결과를 돌려준다(`:33701`)
  `[소스]`. 그래서 "활성화 뒤에는 41을 묻는다"는 같은 프로세스가 뒤에 하는 다른 Resume 판정에 닿는다. 되살린 rank의 다시 무장은 지금처럼 다시 등록과 짝 맺기를 기다린다
  (`gdakiHoldRespareRegistered`) `[소스]`.
- 실제 NIC에서 예비 프로세스의 Resume이 41 뒤의 조건을 다 지나는지는 돌리지 않았다 `[미확인]`.
- 이 고침을 부르는 CPU 시험은 없다(Resume 함수는 어느 단위 시험도 컴파일하지 않는다). 그래서 이 부분은 "빌드됨"이다.

## 트리, 빌드, 시험

- 트리: `agent_gc_sparefix/nccl-src`(세션 스크래치)다. `agent_gc_smoke/nccl-src`를 `cp -a`로 복사했다.
  - 그 HEAD는 `acfede7` "gin-control 2a-2-C step 1 (gc_layer_int.diff 3219c376)"이고, 트리 객체가 `agent_gc_p2a2`의 같은 커밋과 같다 `[측정: git rev-parse]`.
  - smoke 작업 트리의 호스트 파일을 되돌린 뒤 `gc_layer_smokefix.diff`(md5 `10f7e810`)를 적용했다. 그리고 브랜치 `sparefix`에 커밋 `dfa387b`
    "gin-control smokefix (gc_layer_smokefix.diff 10f7e810)"로 남겼다. 고침은 그 위 작업 트리에 있다.
  - p2a2 트리의 작업 트리(다른 작업의 2a-2-C 다음 단계)는 쓰지 않았다.
- 빌드 디렉터리: `agent_gc_smoke/build`(gc_smoke3, libnccl `97980dfb`)를 복사하고 `.d`와 manifest의 경로를 다시 썼다. 그래서 `gc`는 호스트 파일과 `git_version.cc`만
  컴파일했다 `[측정: logs/gc.log]`.
- 스크립트: `agent_gc_sparefix/build_gc_sparefix.sh`(`build_gc_smoke.sh` 사본)다.
  - 키 `sparefix`: 머리 이름은 smokefix 커밋이고, `tree`는 작업 트리를 그대로 빌드한다. 단위 시험 묶음은 int2와 같다.
  - `gc_prep_fn.inc`의 링 send 훅 stub은 step 1의 fd 인자 꼴이다(`agent_gc_p2a2/build_gc_p2a2.sh`의 P2A2C stub과 같음).
  - 시험 원본은 작업 공간 HEAD의 것을 `agent_gc_sparefix/testpin/`에 두고 `GCTEST`로 주었다. step 1 커밋 뒤 바뀌지 않았다 `[측정: git diff 886bc62c HEAD]`.
    작업 공간의 `gc_unit_p2a2.cc`는 다른 작업이 고치는 중이라 쓰지 않았다.

| 무엇 | 결과 | md5 |
|---|---|---|
| `gc_layer_sparefix.diff` | 42줄, +15/−2, 호스트 파일 하나, `__device__`/`__global__` 더한 줄 0, 거꾸로 적용 확인 | `99b6eb47` |
| `gc`(rdma, 연구) | 빌드됨, 경고 0 `[측정: 로그 grep]` | libnccl `635a2a62` |
| `gct`, `gcp`, `gctp` | 빌드하지 않음 `[미확인]`. 고친 줄은 모두 `#if !NCCL_GIN_CTRL_TCP` 안이다 `[소스]` | – |
| `build_gc_sparefix.sh unit`(rdma, tcp) | 둘 다 끝 코드 0, 실패 0 `[측정, n 1: logs/unit2.log]`. rdma: `gc_unit_p3` 16 장면 473 검사(고친 launcher core와 함께 컴파일), `gc_unit_p2a2` 4 573, `gc_unit_p2b` 11 114, `gc_unit_p2` 3 993 471, `gc_unit_p1` 10 248 976, `gc_unit_prep` 366, `gate_fenced` 64, gin-mirror와 gin-restore 시험 그대로 통과. 첫 돌림(`logs/unit.log`)은 `gc_prep_fn.inc` stub이 int2 꼴이라 컴파일 실패, stub을 고친 뒤 다시 돌림 | – |
| `launcher/build_launcher.sh`(`all` 한 번, `unit` 두 번) | 세 번 모두 28 장면 762 검사 실패 0, sanitizer 보고 0 `[측정, n 3]`. 새 검사 70(장면 `spare_wait_for` 57, `spare_opts` 13) | `launcher_unit` `62633e51`, `gin_launcher` `daf642e0` |
| 소스 | `gin_launcher.c` `5b62a1f5`, `gin_launcher.h` `ee6a5f5d`, `launcher_unit.cc` `2fbebbf7`, 스크립트 `774c2ee4` | – |

- launcher 빌드 출력은 `agent_gc_sparefix/launcher_out/`(`r1`–`r3/`에 세 번의 `unit.log`와 `work/`)에 있다.
- 장면 (1)의 "파일 만든 뒤 띄움까지"는 시험이 300 ms 안인지만 본다. 줄의 `matched after` 값은 501.2–501.3 ms였다(세 번의 범위; 그중 400 ms는 시험이 파일 없이
  기다린 시간) `[측정, n 3]`.

## 열린 것

- 덜 쓴 기록을 읽는 경우(위 1의 `[추론]`). 기본 패턴만 쓰면 일어날 수 있다. 완료 표시는 실행기의 go 파일로 두기를 권한다. 다른 길은 호스트가 Resume 때
  `<RECORD>.done`을 만드는 것인데, 만들지 않았다.
- launcher의 "spare of rank R incarnation I reports a replay failure" 줄에는 까닭이 아직 실리지 않는다(notes_smoke 요청).
- 실제 NIC 확인: 실행기 옵션을 넣은 smoke에서 예비 프로세스의 HELLO, `spare_ready`, Resume 성공 줄(41을 묻지 않았다는 INFO 줄은 `NCCL_DEBUG=INFO`일 때만 나옴).
