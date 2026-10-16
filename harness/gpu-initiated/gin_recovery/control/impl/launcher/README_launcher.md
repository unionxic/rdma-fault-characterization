# gin-control launcher (노드마다 하나)

[../../EXPERIMENT.md](../../EXPERIMENT.md) 9.5절의 launcher 프로그램이다. 같은 노드의 복구 계층 프로세스를 Unix 소켓으로 등록받아 pidfd를 쥐고,
끝나면 다른 rank에 알리고, 펜스를 집행하고, 미리 띄운 예비 프로세스에 활성화를 중계한다. 단일 스레드, poll 하나로 돈다.

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
- **SPAWN**은 REFUSED "spawn not built"(따로 된 종류 `GL_K_REFUSED`; 활성화 답이 아니므로 짝은 이것으로 fallback하지 않는다).
- **짝 맺기.** 기록 QP와 생존 READ QP를 따로 짝 맺는다. 어느 쪽이든 시작할 수 있고 QP마다 새 PSN이다. 기록 QP가 깨지면 launcher가 PAIR(gen + 1)을 500 ms마다,
  10 000 ms까지 보낸다. 둘이 같이 시작하면 rank의 것이 이긴다. 지금 세대보다 낮은 PAIR는 QP가 있든 없든 버리고, 이미 잃은 QP의 세대와 같은 PAIR도 버린다(nit 13).
- **전송(verbs).** QP 손잡이는 (일련번호 << 8) | 칸이라, 닫은 QP의 번호는 다른 QP가 받지 않는다. 닫은 QP의 완료와 대기열의 사건은 새 QP에 닿지 않는다(고칠 것 11).
  UD 주소 핸들은 목적지(GID, LID)마다 한 번 만들어 두고, RC와 UD 길 모두 GIN QP와 같은 traffic class를 쓴다(`--tc`, 기본 `NCCL_IB_TC`; 고칠 것 13). 공유 CQ(1 024)에
  다 들지 않는 QP는 만들지 않는다. QP를 없앤 뒤 그 MR과 버퍼를 푼다. CQ 오류는 launcher를 멈추고(STOP_launcher), UD QP 오류는 UD QP를 다시 세운다(nit 12).
- **상태 페이지(4 KiB, REMOTE_READ).** 박동, 등록마다 등록 낱말과 예비 자리 낱말과 그 상태의 나이, rank마다 소비 수(credit). 모두 정렬된 8 B 낱말 하나씩이고,
  낱말마다 release 저장 하나로 쓴다. 칸의 열쇠(nonce)는 다른 낱말 뒤에 쓴다(nit 11).

## 메시지

노드 안 Unix 소켓(9.5절 표의 일곱 행, 모두 256 B; 활성화 바이트만 뒤에 덩어리가 붙음, 한도 64 KiB).

| 종류 | 방향 | 내용 |
|---|---|---|
| `GL_U_REGISTER` 1 | rank → launcher | (rank, 화신, nonce) + 자기 pidfd |
| `GL_U_HELLO_ACK` 2 | launcher → rank, 예비 | 받음/거절(까닭), 노드 번호, UD 끝점, Q_Key, 페이지와 자기 칸 번호 |
| `GL_U_LEAVING` 3 | rank → launcher | (rank, 화신). 등록한 연결로만 |
| `GL_U_SPARE_HELLO` 4 | 예비 → launcher | (rank, 새 화신, nonce) + 자기 pidfd. 같은 (rank, 화신)의 둘째는 거절 |
| `GL_U_SPARE_STATUS` 5 | 예비 → launcher | 준비됨(READY) 또는 재생 실패 |
| `GL_U_ACT_BYTES` 6 | launcher → 예비 | `gdakiRsActivate` 64 B + 활성화 덩어리 |
| `GL_U_ACT_TALK` 7 | 예비 ↔ launcher | 답(64 B 기록), FETCH 끝점 112 B, READY 72 B, DONE 80 B, ABORT |

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
- 장면(20개): pidfd 사실, 등록과 거절, EXITED, LEFT와 BYE, FENCE와 EXITED의 엇갈림, 남의 pidfd에 신호 없음, SPAWN 거절, LATER 뒤 넘기기, 예비 프로세스가 활성화 전에
  끝남, 이른 답의 한도, 잃는 ACCEPTED와 ACCEPTED 뒤 QP 끊김, READ 중 ABORT와 끝남과 QP 잃음, 손잡이 칸의 다시 씀(음성 대조 포함), 같은 화신 둘째 접속, pidfd 바꿈,
  짝 맺기와 다시 짝 맺기, credit 낱말, 등록 oracle(장면 14개, 장면마다 검사 하나), 소켓 디렉터리, 잘못된 말.
- 시험 전송은 손잡이를 verbs 전송과 같은 꼴로 줄 수 있고(칸 다시 씀 + 일련번호), READ를 붙잡아 두었다가 늦게 끝낼 수 있으며, `rc_close` 뒤에는 그 QP의 READ와
  사건을 버린다(전송 계약).

## 만들지 않은 것

- SPAWN 실행(예비 프로세스 띄우기), 띄운 예비 프로세스의 두 한도(HELLO 2 000 ms, READY 5 000 ms), 그 시험 스위치. gin-dynamic에서 한다.
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

## 열린 질문

- **LATER 뒤의 한도를 무엇으로 사전 등록할까.** 지금 launcher 쪽 한도가 없어서, READY를 보내지 않는 예비 프로세스는 생존 rank를 hold 시한(20 s)까지 붙잡는다.
  옛 TCP 길은 약 1 s에 fallback했다 `[추론: 독립 재검토 고칠 것 13]`. 안: (가) 짝이 LATER를 받은 때부터 자기 시계로 `NCCL_GIN_RESTORE_SPARE_START_MS`(5 000)를 센다, (나) LATER에 실린 예비
  프로세스의 나이(HELLO부터)를 더해 HELLO 기준으로 센다, (다) 옛 길과 같은 1 000 ms. 어느 것이든 짝(rank 쪽)이 세고 넘으면 ABORT를 보낸다. launcher 페이지의
  박동이 `LAUNCHER_STALL_MS` 동안 그대로이면 launcher 잃음으로 친다.
