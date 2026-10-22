# gin-control launcher (노드마다 하나)

[../../EXPERIMENT.md](../../EXPERIMENT.md) 9.5절의 launcher 프로그램이다. 같은 노드의 복구 계층 프로세스를 Unix 소켓으로 등록받아 pidfd를 쥐고,
끝나면 다른 rank에 알리고, 펜스를 집행하고, 미리 띄운 예비 프로세스에 활성화를 중계한다. `--spare-cmd`를 주면 노드마다 예비 프로세스 하나를 스스로 띄워 둔다
(아래 "따뜻한 예비 프로세스"). 단일 스레드, poll 하나로 돈다.

## 하는 일

- **등록.** Unix 소켓(SOCK_SEQPACKET, 경로의 디렉터리는 자기 uid의 0700)으로 (rank, 화신, nonce)와 그 프로세스 자신의 pidfd(SCM_RIGHTS)를 받는다.
  `SO_PEERCRED`의 uid가 같고, pidfd의 pid(`/proc/self/fdinfo`)가 접속한 쪽의 pid이며, 그 pid의 시작 시각이 접속 때와 같을 때만 받는다. 이 검사는 끌 수 없다.
- **종료 보고.** pidfd가 읽히면(스레드 그룹이 끝남) 그 communicator의 모든 rank에 한 사건 한 말로 알린다: FENCE가 왔으면 FENCED, 아니면 LEAVING 뒤면 LEFT,
  아니면 EXITED. 끝난 프로세스가 보낸 LEAVING은 판정 전에 먼저 읽는다. 시험 스위치 `NCCL_GIN_CTRL_TEST_NO_EXIT_REPORT=1`은 EXITED만 끈다.
- **펜스.** FENCE(rank, 화신)를 받으면 그 등록의 pidfd에만 SIGKILL을 보내고, 읽히면 FENCED. 이미 끝났으면 곧바로 FENCED. 쥔 것이 없으면 FENCE_NAK과
  "refused to signal … (STOP_launcher)" 줄이며 아무 신호도 보내지 않는다. pid로 신호를 보내는 길은 없다.
- **활성화 중계.** 짝의 ACTIVATE를 등록 표로 먼저 본다(nonce, rank, 화신 = 끝난 화신 + 1). 예비 프로세스가 HELLO 전이면 곧바로 REFUSED, HELLO 뒤 READY 전이면
  LATER를 한 번만 보내고, READY가 오면 짝의 outbox에서 덩어리를 READ해 기록과 함께 넘긴다. 예비 프로세스의 답, FETCH 끝점, READY, DONE을 중계한다.
  - READ가 나가 있는 동안 ABORT, 예비 프로세스의 끝남, 짝 QP의 잃음이 와도 덩어리 버퍼는 그 READ가 끝나거나 그 QP를 닫은 뒤에만 푼다(독립 리뷰 REVIEW_PREP 고칠 것 10).
  - ACCEPTED 뒤에는 짝의 launcher QP가 잠깐 끊기거나 다시 짝 맺어져도 그 활성화를 그만두지 않고 SIGKILL도 보내지 않는다. 중계할 FETCH 말은 대기열에서 기다렸다가
    다시 맺은 QP로 간다. ACCEPTED 뒤의 활성화를 끝내는 것은 짝의 ABORT나 FENCE뿐이다(고칠 것 12). ACCEPTED 전(기다림, READ, 넘김)에는 지금처럼 그만둔다.
- **SPAWN**은 REFUSED "spawn not built"(따로 된 종류 `GL_K_REFUSED`; 활성화 답이 아니므로 짝은 이것으로 fallback하지 않는다). `--spare-cmd`가 있어도 같다:
  hold 시작에 띄우기는 나중의 스위치다.
- **따뜻한 예비 프로세스.** 시작 때 하나를 띄우고, 그것이 활성화되면 곧바로 다음 것(화신 + 1)을 띄운다. 아래 절.
- **짝 맺기.** 기록 QP와 생존 READ QP를 따로 짝 맺는다. 어느 쪽이든 시작할 수 있고 QP마다 새 PSN이다. 기록 QP가 깨지면 launcher가 PAIR(gen + 1)을 500 ms마다,
  10 000 ms까지 보낸다. 둘이 같이 시작하면 rank의 것이 이긴다. 지금 세대보다 낮은 PAIR는 QP가 있든 없든 버리고, 이미 잃은 QP의 세대와 같은 PAIR도 버린다(nit 13).
- **전송(verbs).** QP 손잡이는 (일련번호 << 8) | 칸이라, 닫은 QP의 번호는 다른 QP가 받지 않는다. 닫은 QP의 완료와 대기열의 사건은 새 QP에 닿지 않는다(고칠 것 11).
  UD 주소 핸들은 목적지(GID, LID)마다 한 번 만들어 두고, RC와 UD 길 모두 GIN QP와 같은 traffic class를 쓴다(`--tc`, 기본 `NCCL_IB_TC`; 고칠 것 13). 공유 CQ(1 024)에
  다 들지 않는 QP는 만들지 않는다. QP를 없앤 뒤 그 MR과 버퍼를 푼다. CQ 오류는 launcher를 멈추고(STOP_launcher), UD QP 오류는 UD QP를 다시 세운다(nit 12).
- **상태 페이지(4 KiB, REMOTE_READ).** 박동, 등록마다 등록 낱말과 예비 자리 낱말과 그 상태의 나이, rank마다 소비 수(credit). 모두 정렬된 8 B 낱말 하나씩이고,
  낱말마다 release 저장 하나로 쓴다. 칸의 열쇠(nonce)는 다른 낱말 뒤에 쓴다(nit 11).

## 메시지

노드 안 Unix 소켓(9.5절 표의 일곱 행과 nonce 없는 INFO 둘, 모두 256 B; 활성화 바이트만 뒤에 덩어리가 붙음, 한도 64 KiB).

| 종류 | 방향 | 내용 |
|---|---|---|
| `GL_U_REGISTER` 1 | rank → launcher | (rank, 화신, nonce) + 자기 pidfd |
| `GL_U_HELLO_ACK` 2 | launcher → rank, 예비 | 받음/거절(까닭), 노드 번호, UD 끝점, Q_Key, 페이지와 자기 칸 번호 |
| `GL_U_LEAVING` 3 | rank → launcher | (rank, 화신). 등록한 연결로만 |
| `GL_U_SPARE_HELLO` 4 | 예비 → launcher | (rank, 새 화신, nonce) + 자기 pidfd. 같은 (rank, 화신)의 둘째는 거절 |
| `GL_U_SPARE_STATUS` 5 | 예비 → launcher | 준비됨(READY) 또는 재생 실패 |
| `GL_U_ACT_BYTES` 6 | launcher → 예비 | `gdakiRsActivate` 64 B + 활성화 덩어리 |
| `GL_U_ACT_TALK` 7 | 예비 ↔ launcher | 답(64 B 기록), FETCH 끝점 112 B, READY 72 B, DONE 80 B, ABORT |
| `GL_U_INFO` 8 | rank → launcher | 머리만(본문 0 B, fd 없음, nonce 0, 화신 0). all-gather 앞, 어느 연결에서든. 항목과 페이지 칸을 만들지 않음 |
| `GL_U_INFO_ACK` 9 | launcher → rank | 머리 되풀이, `sub` 8. 본문 `glUHelloAck`: HELLO_ACK와 같은 노드 번호, UD 끝점, Q_Key, 페이지, 칸 0xffffffff. 거절은 다른 uid, fd, 본문이나 nonce |

RNIC 쪽(봉투 64 B + 말 256 B = 320 B; 봉투는 설계 v2 칸 순서 그대로, 칸 합이 56 B라 `rsv[16]`으로 64 B).

| 종류 | 방향 | 뜻 |
|---|---|---|
| PAIR 1, PAIR_ACK 2 | 양쪽, UD | sub 기록 QP 또는 생존 READ QP, 세대, 새 PSN, UD 끝점과 Q_Key, 페이지와 credit 낱말 자리 |
| CONNECTED 3 | 시작한 쪽 → 상대, RC | 기록 QP의 첫 말. 그 전에는 상대가 보내지 않음 |
| REG_NOTE 4 | launcher → rank | 등록 낱말, 예비 자리 낱말과 나이 |
| EXITED 5, LEFT 6, FENCED 8 | launcher → rank | 머리의 (rank, 화신, nonce)가 끝남 |
| FENCE 7 / FENCE_NAK 9 | 짝 → launcher / 답 | 종료 요청 / 쥔 것 없음 |
| ACTIVATE 10 / ACT_ANSWER 11 | 짝 → launcher / 답 | 기록 64 B + 덩어리 자리 / LATER(한 번), ACCEPTED, REFUSED + 예비의 상태와 나이 |
| FETCH_EP 12, FETCH_READY 13, FETCH_DONE 14 | 중계 | 지금 활성화 연결의 바이트 그대로 |
| ABORT 15 | 짝 → launcher | 그 활성화를 그만둠(hold 시한). 뒤에 온 ACCEPTED는 버림(`late_accept`) |
| SPAWN 16 / REFUSED 17 | 짝 → launcher / 답 | "spawn not built" |

배치와 크기는 [launcher_msg.h](launcher_msg.h)의 `static_assert`가 고정한다.

## 빌드와 단위 시험

```
OUT=<출력 디렉터리> ./build_launcher.sh          # build + unit
OUT=<출력 디렉터리> ./build_launcher.sh build    # gin_launcher, 헤더 검사(C11, C++17), launcher_unit
OUT=<출력 디렉터리> ./build_launcher.sh unit     # launcher_unit 실행, 로그 $OUT/unit.log
```

- `/usr/include/infiniband/verbs.h`가 있으면 verbs 전송까지 빌드하고(실행하지 않음), 없으면 `-DGL_NO_VERBS`로 빌드한다(그 프로그램은 시작을 거절한다).
- 스크립트는 `gin_launcher`를 실행하지 않고, verbs 장치나 GPU를 열지 않는다. 단위 시험은 프로세스 안 시험 전송과, 스스로 fork한 자식(실제 pidfd, 실제 SIGSTOP과
  SIGKILL)만 쓴다. ASan과 UBSan으로 빌드한다.
- 장면(27개): pidfd 사실, 등록과 거절, EXITED, LEFT와 BYE, FENCE와 EXITED의 엇갈림, 남의 pidfd에 신호 없음, SPAWN 거절, LATER 뒤 넘기기, 예비 프로세스가 활성화 전에
  끝남, 이른 답의 한도, 잃는 ACCEPTED와 ACCEPTED 뒤 QP 끊김, READ 중 ABORT와 끝남과 QP 잃음, 손잡이 칸의 다시 씀(음성 대조 포함), 같은 화신 둘째 접속, pidfd 바꿈,
  짝 맺기와 다시 짝 맺기, credit 낱말, 등록 oracle(장면 14개, 장면마다 검사 하나), 소켓 디렉터리, 잘못된 말, nonce 없는 INFO, 그리고 따뜻한 예비 프로세스 여섯
  (옵션, 시작 때 띄우기와 HELLO 한도, 활성화 뒤 다음 것, 쓰이지 않은 것의 다시 띄우기와 한도, HELLO 한도 넘김, 남의 프로세스에 신호 없음; 아래 절).
- 시험 전송은 손잡이를 verbs 전송과 같은 꼴로 줄 수 있고(칸 다시 씀 + 일련번호), READ를 붙잡아 두었다가 늦게 끝낼 수 있으며, `rc_close` 뒤에는 그 QP의 READ와
  사건을 버린다(전송 계약).

## 따뜻한 예비 프로세스 (2026-10-17 사용자 결정)

노드마다 예비 프로세스 하나를 launcher가 늘 띄워 둔다. 지금까지는 실행기가 띄웠다. 하나가 활성화되면 곧바로 다음 것을 띄우므로 같은 노드의 둘째 죽음도 예비 프로세스를
찾는다. 띄운 것은 등록받은 것과 똑같이 다룬다: HELLO의 pidfd를 쥐고, rank가 된 뒤의 끝남은 지금처럼 EXITED, LEFT, FENCED로 알린다. 페이지의 예비 자리 낱말의 뜻은
그대로다(HELLO 이상이면 쓸 수 있음). 그래서 rank 쪽 `gl_path_exists`는 바뀌지 않았고 `launcher_msg.h`도 바뀌지 않았다(새 종류 없음).

**옵션.**

| 옵션 | 기본 | 뜻 |
|---|---|---|
| `--spare-cmd "ARGV..."` | 없음 | 예비 프로세스의 명령. 빈칸과 탭에서 나누고 shell도 따옴표도 없다. `execvpe`로 실행(PATH 찾기) |
| `--spare-env KEY=VAL` | 없음 | 되풀이. 예비 프로세스 환경에 더한다. 같은 KEY를 다시 주면 바꾼다 |
| `--spare-log DIR` | 없음(`--spare-cmd`가 있으면 필수) | 띄울 때마다 로그 파일 하나: `DIR/spare_n<노드>_s<띄운 번호>_i<화신>_p<launcher pid>.log`(이미 있으면 `_1`–`_9`를 붙임) |
| `--spare 0\|1` | `--spare-cmd`가 있으면 1 | 0이면 띄우지 않는다(줄 `warm spare off (--spare 0)`) |
| `--spare-hello-ms N` | 5 000 | 띄운 때부터 HELLO까지의 한도 |
| `--spare-respawn-max N` | 3 | 쓰이지 않고 끝난 예비 프로세스를 60 000 ms 안에 다시 띄우는 최대 횟수 |

- 예비 프로세스의 환경: launcher 자신의 환경에서 `NCCL_*`와 `GIN_*`를 모두 뺀 것, 그 위에 `--spare-env`, 그 위에 launcher가 정하는 셋
  (`NCCL_GIN_CTRL_LAUNCHER_SOCK` = 자기 소켓 경로, `NCCL_GIN_CTRL_LAUNCHER_NODE` = 자기 노드 번호, `NCCL_GIN_RESTORE_SPARE_INC` = 이번 화신).
- 첫 화신은 `--spare-env NCCL_GIN_RESTORE_SPARE_INC=N`이면 N, 아니면 1이다.
- `--spare-env`로 받지 않는 것(설계 v2 2.1절의 허용 목록 규칙): `NCCL_GIN_RESTORE_RECORD`, `NCCL_GIN_RESTORE_TEST_DIE_IN_CKPT`, `GIN_RS_DIE_IN_STEP`,
  `GIN_RS_DIE_AT`, 그리고 launcher가 정하는 소켓과 노드 변수. 주면 시작을 거절한다(종료 코드 2).

**수명.**

1. **시작.** 소켓을 listen한 직후 fork와 exec로 띄운다. 자식은 새 session(`setsid`), stdin은 `/dev/null`, stdout과 stderr는 자기 로그 파일이다. 신호
   처리는 기본값, 신호 mask는 비운다. fd 3 이상은 `close_range`로 모두 닫는다(그래서 CLOEXEC가 없는 fd도 넘어가지 않는다; launcher가 여는 fd는 CLOEXEC다). exec 실패는 CLOEXEC 파이프로 알고, 자식은 127로
   끝난다. launcher는 fork 직후 그 pid의 pidfd를 연다(자기 자식이라 거두기 전에는 pid가 다시 쓰이지 않음).
2. **HELLO.** 띄운 것의 HELLO는 HELLO한 프로세스의 pid가 띄운 pid와 같거나, 그 프로세스의 session이 띄운 pid일 때 짝을 맞춘다(`timeout`처럼 fork하는 감싸개 아래의
   예비 프로세스도 맞음). 남이 띄운 예비 프로세스의 HELLO는 지금처럼 받지만 짝을 맞추지 않는다. `--spare-hello-ms` 안에 HELLO가 없으면 띄운 pidfd로 SIGKILL하고
   STOP 줄 하나를 남긴 뒤 한 번 다시 띄운다. 다시 띄운 것도 한도를 넘으면 둘째 STOP 줄과 함께 더는 띄우지 않는다.
3. **활성화.** ACCEPTED만으로는 띄우지 않는다. 그 활성화의 DONE을 짝에게 넘긴 때, 또는 그 예비 프로세스가 새 화신으로 다시 등록한 때(먼저 온 쪽)에 다음 예비 프로세스를
   HELLO의 화신 + 1로 띄운다. ACCEPTED 뒤 DONE과 다시 등록 전에 끝나면 그것은 rank의 끝남이다(EXITED). 그래서 같은 화신을 다시 띄우지 않고(그 화신은 이미 끝난 화신이라 STALE)
   화신 + 1을 띄운다.
4. **쓰이지 않은 끝남.** HELLO 전이든 뒤든 쓰이지 않고 끝나면 같은 화신으로 다시 띄운다. 60 000 ms 안에 `--spare-respawn-max`번까지이고, 넘으면 STOP 줄과 함께 더는
   띄우지 않는다. 활성화가 REFUSED나 ABORT로 끝나 launcher가 grace 뒤 SIGKILL한 예비 프로세스도 여기에 든다.
5. **거둠.** 띄운 것은 모두 launcher의 자식이고 pidfd가 읽히면 `waitpid`로 거둔다. rank가 된 것도 끝나면 거둔다.
6. **끝.** shutdown은 HELLO 전의 것을 띄운 pidfd로, HELLO 뒤 쓰이지 않은 것을 지금처럼 HELLO의 pidfd로 SIGKILL하고 1 s까지 기다려 거둔다. rank가 된 것은 그대로 둔다.

- **신호.** launcher가 신호를 보내는 길은 둘뿐이다: 등록이나 HELLO로 받은 pidfd, 그리고 자기가 띄운 프로세스의 pidfd(HELLO 한도 넘김, shutdown). pid로 보내는 길은 없다.
- `[추론]` HELLO 한도의 SIGKILL은 띄운 프로세스에만 간다. 명령이 `timeout`처럼 fork하는 감싸개면 그 아래 예비 프로세스에는 닿지 않는다(`timeout`은 SIGKILL을 넘기지
  않음). 명령은 exec로만 이어지게(`stdbuf`는 됨) 두기를 권한다.
- `[추론]` verbs 전송이 MR을 등록한 뒤 fork한다. Linux 5.9 이후 커널은 고정(pinned)된 page를 fork 때 자식 쪽에 복사해 부모의 DMA page가 바뀌지 않고, 자식은 곧바로
  exec한다. verbs 전송으로 띄우기는 실행하지 않았다 `[미확인]`.
- `[추론]` launcher가 SIGKILL로 끝나면(정리 없이) 쓰이지 않은 예비 프로세스는 남는다. 그 경우 예비 프로세스 자신의 대기 한도까지 산다.

**줄**(정확한 글자; 앞에 `GIN/LA: node <노드>: `, 끝에 ` mono_ms=<ms>`가 붙음. `<상태>`는 `exit <n>`, `signal <n>`, `status unknown` 가운데 하나).

```
warm spare on (command <argv0>, HELLO bound <H> ms, respawn cap <M> within 60000 ms, first incarnation <I>, logs <DIR>)
spare spawned (spawn <S>, incarnation <I>, pid <P>, why start|activated|respawn|hello_retry, log <PATH>)
spare exec failed (spawn <S>, incarnation <I>, pid <P>): <strerror>
spare spawn failed (incarnation <I>, why <W>): <까닭>; no more spares (STOP_launcher)
spare spawn <S> (pid <P>): pidfd_open failed (<strerror>): it is reaped by its pid only and never signalled (STOP_launcher)
spawned spare said HELLO (spawn <S>, incarnation <I>, pid <P>, hello pid <Q>, rank <R> incarnation <J>, after <X> ms)
spawned spare said no HELLO within <H> ms (spawn <S>, incarnation <I>, pid <P>): SIGKILL through its pidfd; one retry (STOP_launcher)
spawned spare said no HELLO within <H> ms (spawn <S>, incarnation <I>, pid <P>, the retry): SIGKILL through its pidfd; no more spares (STOP_launcher)
spawned spare activated (spawn <S>, incarnation <I>, pid <P>, by DONE|re-registration|exit after ACCEPTED): next spare incarnation <I+1>
spawned spare ended after ACCEPTED (spawn <S>, incarnation <I>, pid <P>, <상태>)
spawned spare exited unused (spawn <S>, incarnation <I>, pid <P>, before HELLO|after HELLO, <상태>): respawn <k> of <M> within 60000 ms
spawned spare exited unused (spawn <S>, incarnation <I>, pid <P>, before HELLO|after HELLO, <상태>): respawn cap <M> within 60000 ms reached; no more spares (STOP_launcher)
spawned spare exited unused (spawn <S>, incarnation <I>, pid <P>, before HELLO|after HELLO, <상태>): no respawn (no more spares)
spawned process ended (spawn <S>, incarnation <I>, pid <P>, <상태>)
shutdown: the spawned spare (spawn <S>, incarnation <I>, pid <P>) said no HELLO: SIGKILL through its pidfd
shutdown: spawned process (spawn <S>, incarnation <I>, pid <P>) <상태>|left running (not reaped)
```

- `warm spare off (--spare 0)`은 main이 시작 때 `GIN/LA: node <노드>: ` 앞붙임만 달고 쓴다(`mono_ms` 없음).
- 지금 있던 줄(`spare of rank R incarnation I said HELLO`, `... ended`, `re-registered`, `shutdown: the unused spare ...`)은 그대로 나온다. 새 줄에는 `spare of rank`도
  `rank R incarnation I registered`도 없으므로 `test/launcher_gc.sh`의 등록 표 읽기(TABLEPY)는 바뀌지 않는다 `[추론: 정규식을 읽음]`.

**단위 시험의 장면.** `launcher_unit`이 `--fake-spare [--fork]`로 자기 자신을 예비 프로세스로 exec한다. 그것은 받은 session, fd, stdio, 환경을 시험의 제어 소켓으로
알리고, 계획 바이트 하나(h: HELLO 뒤 기존 자식 명령, n: HELLO 없음, e: HELLO 뒤 곧바로 끝남, q: 곧바로 끝남)를 받는다.

- `spare_opts`: 나누기, 빠진 로그 디렉터리, 받지 않는 env, 같은 KEY 바꾸기, `--spare 0`, `--spare 1`만, 범위 밖 수.
- `spare_start`: listen 직후 띄움(rank보다 먼저), 새 session, fd 3개, stdin `/dev/null`, stdout과 stderr가 자기 로그 파일, SIGPIPE 기본값, launcher의 `NCCL_`과
  `GIN_` 변수가 닿지 않음, 셋 변수, HELLO가 한도 안, 페이지 (REPLAYING, 3, 1), 짝의 SPAWN은 여전히 REFUSED이고 띄우지 않음, shutdown의 SIGKILL과 거둠. 감싸개(`--fork`)로
  같은 것을 한 번 더(HELLO pid ≠ 띄운 pid, session = 띄운 pid; 같은 로그 이름이 있어 `_1`).
- `spare_activation_cycle`: 페이지의 예비 자리 낱말이 없음 → REPLAYING → READY → OFFERED → ACCEPTED → (DONE) 다음 것 REPLAYING(3, 2) → 다시 등록 뒤 (ALIVE 1, REPLAYING 2)이고
  `gl_path_exists` 참. ACCEPTED와 FETCH 끝점만으로는 띄우지 않음. 되살린 rank(띄운 프로세스)의 끝남은 EXITED(화신 1)이고 거두며 다시 띄우지 않음. 둘째 활성화는 다시 등록으로
  화신 3을 띄움. 이 동안 신호 0.
- `spare_respawn`: HELLO 뒤 끝남 3번 다시 띄움과 넷째의 한도 줄, 그 뒤 300 ms 띄움 없음, 낱말 FAILED. HELLO 전 끝남(한도 1). exec 실패(127, 한도 1). ACCEPTED 뒤 끝남 →
  EXITED와 화신 2(다시 띄우기로 세지 않음).
- `spare_hello_timeout`: 한도(500 ms) 넘김 → 띄운 pid에만 SIGKILL, STOP 줄 하나, 다시 띄운 것이 HELLO. 다시 띄운 것도 넘기면 둘째 줄, 700 ms 띄움 없음.
- `spare_no_foreign_signal`: 접속만 한 프로세스와 남이 띄운 같은 (rank, 화신)의 예비 프로세스가 있을 때 HELLO 한도의 SIGKILL 둘은 띄운 둘에만 감. 받지 않은 화신과 등록 없는
  rank의 FENCE는 FENCE_NAK이고 신호 없음. 이 시험 바이너리의 launcher가 보낸 모든 신호는 시험이 fork한 자식이나 launcher가 띄운 프로세스에만 감.

**실행기 쪽에 필요한 바꿈**(`test/`는 이 작업 범위 밖이라 고치지 않았다; 조율 세션이 적용). 지금 `test/run_gc.sh`의 `start_spare`는 시행마다 rank의 `GINRS resume`
줄을 본 뒤 `launch`로 예비 프로세스를 띄운다. 명령은 `stdbuf -oL -eL timeout -s KILL <WATCHDOG_S + 20> $RSBIN <rank> $ARGS $WORK/<name>.kv`, 환경은 `NENV`, `hca`,
`la_env`, `RS_ENV`, `RS_RDV_NONCE`, `NCCL_GIN_RESTORE_SPARE=<rank>`, `_PORT`, `_WAIT_MS`, `_REPLAY`, `SPARE_ENV`(같은 rank의 둘째는 `NCCL_GIN_RESTORE_SPARE_INC=2`)다.

1. `test/launcher_gc.sh start`가 `--spare-cmd`, `--spare-env`(되풀이), `--spare-log`을 launcher에 넘기게 한다. 지금 `start`는 K=V로
   `NCCL_GIN_CTRL_TEST_NO_EXIT_REPORT`만 받는다. sunny의 예비 프로세스도 그 노드 launcher가 띄우므로 실행기의 ssh 하나가 준다.
2. launcher 길(`LAUNCHER_SCOPE` ≠ none)에서는 `start_spare`의 두 호출(spare, spare_2nd)을 끈다. 남겨 두면 같은 (rank, 화신)의 둘째 HELLO가 DUPLICATE로 거절되고,
   launcher가 띄운 것이 HELLO 한도에 걸려 STOP 줄 둘 뒤 더 띄우지 않는다 `[추론: 코드]`. 같은 rank의 둘째 예비 프로세스는 이제 launcher가 활성화 뒤 스스로 띄운다.
   다른 rank의 둘째 예비 프로세스는 노드마다 하나라서 같은 노드면 될 수 없다.
3. 예비 프로세스의 줄(`GINRS spare_ready` 등)은 `$WORK/spare.log`가 아니라 launcher 줄 `spare spawned (... log <PATH>)`의 파일에 있다. 이 파일에는 받는 때
   시각(STAMP)이 붙지 않는다. sunny에서는 그 노드의 파일이다.
4. kill 대상의 pid(`rec_pid`, `cpid_of spare`, `SPARE_KILL_FIRST`, `spare_then_rank`)는 launcher 줄 `spawned spare said HELLO (... hello pid <Q> ...)`의 Q다. 그 부모는 이제
   launcher(감싸개가 있으면 감싸개)이므로 `INJPY`의 부모 검사에 넘기는 값도 바뀐다.
5. 명령에서 `timeout -s KILL`을 빼기를 권한다(위 `[추론]`: HELLO 한도의 SIGKILL이 닿지 않음). 남겨도 HELLO 짝 맞춤은 session으로 된다.
6. 조율 세션이 정할 것: launcher는 hold마다 한 번 뜨는데(EXPERIMENT 9.5절), 예비 프로세스의 명령과 환경에는 시행마다 바뀌는 값(`RS_RDV_NONCE`, `$ARGS`의 포트,
   `NCCL_GIN_RESTORE_REPLAY`와 kv 경로)이 있다. launcher에는 명령을 바꾸는 말이 없다(새 종류가 필요해 이번 범위 밖). 그래서 (가) launcher를 시행마다 띄우거나,
   (나) 그 값들을 시행마다 같은 경로와 값으로 두어야 한다.
7. 띄우는 때가 rank의 resume 뒤에서 launcher 시작 때(rank보다 먼저)로 바뀐다. 기록 파일이 아직 없을 때 예비 프로세스가 기다리는지 끝나는지 `[미확인]`. 끝나면 수명 4번의
   다시 띄우기 한도(60 s에 3번)가 먼저 다 쓰일 수 있다.
8. 시행 끝의 정리: 쓰이지 않은 예비 프로세스는 launcher의 `stop`(SIGTERM → shutdown)이 SIGKILL하고 거둔다. `stop`이 3 s 뒤 SIGKILL로 끝낸 경우에는 남으므로 실행기의 끝 정리
   목록에 넣어야 한다.

## 만들지 않은 것

- SPAWN 실행(hold 시작에 짝이 요청해 띄우기), 띄운 예비 프로세스의 READY 한도(5 000 ms), 그 시험 스위치. gin-dynamic에서 한다. 시작 때와 활성화 뒤에 띄우는 것과 HELLO
  한도(`--spare-hello-ms`, 기본 5 000)는 아래 "따뜻한 예비 프로세스"에 있다.
- 그래서 LATER 뒤의 기다림에 launcher 자신의 한도는 없다. READY, 재생 실패, 예비 프로세스의 끝남, 짝의 ABORT만 끝낸다. 대신 기다림을 드러낸다: LATER에 예비
  프로세스의 상태와 그 상태의 나이를 싣고, 페이지의 예비 자리 낱말과 `spareSinceMs`, 박동, `monoMs`가 그 뒤에도 움직인다.

## Linux 5.15 pidfd에 기대는 사실

rain(5.15.0-97-generic)에서 `launcher_unit`의 pidfd 장면으로 쟀다(fork한 자식, CUDA와 verbs 없음). 범위는 같은 바이너리(`launcher_unit` md5 `50ac6eda`)를 네 번 돌린 값의 범위다(n 4). 로그는 빌드 출력의 `final/unit_run1–4.log`.

- [측정] main thread가 `pthread_exit`하고 다른 thread가 300 ms 더 살면, +100 ms에 `/proc` 상태는 Z이고 pidfd는 읽히지 않는다. 읽히는 때는 마지막 thread가 끝난
  때(+301.1–301.5 ms)다. launcher의 EXITED도 그때(+299.4–300.0 ms, 기준 시각이 조금 늦음)였다. 옛 관문이 Z를 끝남으로 친 창을 pidfd는 닫는다. 그 창 안의
  FENCE는 SIGKILL 뒤 2.13–2.69 ms에 FENCED였다.
- [측정] 끝났고 거두지 않은 프로세스(zombie)의 pidfd는 읽히고, 그것에 `pidfd_send_signal`은 0을 돌려준다. 거둔 뒤에는 -1(ESRCH)이고 fdinfo의 `Pid:`는 -1이다.
- [측정] thread의 TID로 `pidfd_open`하면 EINVAL이다(thread pidfd 없음).
- [측정] SIGSTOP으로 멈춘(T) 프로세스에 pidfd로 SIGKILL을 보내면 0.46–0.62 ms에 pidfd가 읽힌다.
- [측정] LEAVING을 보내고 곧바로 끝난 프로세스는 실행마다 20/20 LEFT, 0/20 EXITED였다(합 80/80).
- [측정] SCM_RIGHTS로 받은 pidfd의 fdinfo `Pid:`가 보낸 프로세스의 pid다(등록 장면).
- [미확인] 여러 thread인 CUDA 프로세스에서 pidfd가 읽힐 때 uverbs fd와 GPU 문맥이 이미 닫혔는지(9.8절 실행 가능성 확인 2). sunny(6.8)에서 같은지.

## 바뀐 것

2026-10-17, nonce 없는 INFO(요청: [../notes_p3.md](../notes_p3.md) "고침"). 한 단계씩, 단계마다 `build_launcher.sh all`(스크래치 출력, 이 폴더 밖).

- 1: `launcher_msg.h`에 `GL_U_INFO` 8, `GL_U_INFO_ACK` 9, `GL_U_KIND_MAX` 7 → 9(같다는 `static_assert`), 크기와 판 번호는 그대로(256 B). 빌드됨, 단위 시험 통과
- 2: `gin_launcher.c`가 어느 연결에서든(REGISTER 앞, 없이, 뒤) INFO에 INFO_ACK(머리 되풀이, `sub` 8, HELLO_ACK와 같은 노드, Q_Key, UD 끝점, 페이지, 칸 0xffffffff)로 답한다. 항목, 페이지 칸, `nRegRefused`를 건드리지 않는다. 다른 uid, 함께 온 fd(닫음), 본문이나 nonce, 깨진 INFO는 REFUSED. 셈 `nInfo`, `nInfoRefused`. 빌드됨, 옛 시험 통과
- 3: `launcher_unit.cc` 장면 `info`(fork한 프로세스의 REGISTER 앞 INFO, 같은 연결의 REGISTER와 그 뒤 INFO, fd 셋 경우의 거절과 fdinfo 수, 본문과 nonce 거절, 종류 10과 9 버림, 곧바로 닫는 묻는 쪽, 다른 uid)와 `header`의 `gl_unix_check` 검사. 21 장면 472 검사 실패 0 `[측정, n 1]`
- 4: 마지막 빌드(verbs 전송은 빌드만, 실행 없음)와 ASan, UBSan 단위 시험 세 번: 세 번 모두 21 장면 472 검사 실패 0, sanitizer 보고 0 `[측정, n 3]`. `launcher_unit` md5 `162e5b17`, `gin_launcher` `3f3ed6d0`. `rs_ctrl_api.h`는 C++17 단독 컴파일 통과(rdma, tcp)
- 5: 이 README의 메시지 표에 두 종류, 장면 수, 이 목록

2026-10-22, 따뜻한 예비 프로세스(2026-10-17 사용자 결정; 조율 세션의 지시). 빌드 출력은 이 폴더 밖의 스크래치(`launcher_build4`).

- `launcher_msg.h`는 바뀌지 않았다(md5 `fb11b235`, 새 종류 없음). `gin_launcher.h`에 `glConfig`의 예비 칸 여섯(끝에 더함: `memset` 뒤 칸을 채우는 쪽은 그대로 꺼짐),
  셈 여덟, `glSpareOpts`와 옵션 함수, `gl_core_kids`. `gin_launcher.c`에 띄우기, HELLO 짝 맞춤과 한도, 활성화 뒤 다음 것, 다시 띄우기 한도, 거둠, shutdown, main의 옵션.
  짝의 SPAWN 답은 그대로다.
- `launcher_unit.cc`에 장면 여섯(위 절). 빌드됨(verbs 전송은 빌드만, 실행 없음). ASan, UBSan 단위 시험 세 번(`all` 한 번, `unit` 두 번): 세 번 모두 27 장면 692 검사
  실패 0, sanitizer 보고 0(시험 로그와 띄운 예비 프로세스의 로그 파일 모두) `[측정, n 3]`. 새 여섯 장면의 검사는 220개다. `launcher_unit` md5 `b4cbc2f9`, `gin_launcher`
  `47e0c31b`, `gin_launcher.c` `c31e1601`. 로그는 빌드 출력의 `final/run1–3/`.
- `[측정, n 36: 세 번의 실행을 합친 범위]` 띄운 때부터 HELLO 짝 맞춤까지 5.43–5.73 ms. 단위 시험의 가짜 예비 프로세스(ASan 빌드의 시험 바이너리, CUDA와 NCCL 없음)의
  값이라 진짜 예비 프로세스의 HELLO 시각(설계 v2의 어림 약 0.28–0.36 s)과는 다르다.
- `GL_NO_VERBS` 빌드로 옵션 거절 넷(로그 디렉터리 없음, 디렉터리가 아님, 받지 않는 env, `--spare 1`만)이 종료 코드 2, `--spare 0`이 `warm spare off` 줄을 냄을
  봤다(장치를 열기 전에 끝남) `[측정, n 1]`.

## 열린 질문

- **LATER 뒤의 한도를 무엇으로 사전 등록할까.** 지금 launcher 쪽 한도가 없어서, READY를 보내지 않는 예비 프로세스는 생존 rank를 hold 시한(20 s)까지 붙잡는다.
  옛 TCP 길은 약 1 s에 fallback했다 `[추론: 독립 재검토 고칠 것 13]`. 안: (가) 짝이 LATER를 받은 때부터 자기 시계로 `NCCL_GIN_RESTORE_SPARE_START_MS`(5 000)를 센다, (나) LATER에 실린 예비
  프로세스의 나이(HELLO부터)를 더해 HELLO 기준으로 센다, (다) 옛 길과 같은 1 000 ms. 어느 것이든 짝(rank 쪽)이 세고 넘으면 ABORT를 보낸다. launcher 페이지의
  박동이 `LAUNCHER_STALL_MS` 동안 그대로이면 launcher 잃음으로 친다.
