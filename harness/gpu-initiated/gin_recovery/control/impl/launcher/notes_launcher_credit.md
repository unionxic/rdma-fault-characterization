# launcher credit 다시 읽기 (2026-10-23)

독립 리뷰(Codex, 2026-10-23)의 지적을 코드 길로 확인하고 고쳤다. 커밋 전, 하드웨어 실행 없음.

## 무엇이 틀렸나

[추론: 코드 길 읽기] `launcher_transport_verbs.c`(고치기 전 HEAD `3336d800`)에서

- `gl_v_rc_send`는 창(`seqOut - ackIn < GL_V_RQ`, 64)이 닫히면 메시지를 큐에 넣고 `gl_v_credit_read`로 rank의 소비 수 낱말을 한 번 READ한다.
- READ 완료(`WR_RC_CREDIT`)는 값이 움직였을 때만 `ackIn`을 올리고 `gl_v_flush`를 부른다. 값이 그대로면 flush는 보낼 수 없고 끝난다.
- 다시 READ하는 곳은 다음 `rc_send`뿐이다. `gl_v_flush`, SEND 완료, `gl_v_poll`, launcher 루프(`gl_core_step`, 10 ms마다 `gl_transport_events`)는 READ를 걸지 않는다.
- rank의 SEND가 오면 그 envelope의 `ackSeq`로 `ackIn`이 오르고 flush되지만, rank가 보낼 것이 없으면(예: FENCED나 활성화 메시지를 기다리는 중) 오지 않는다.

그래서 rank가 나중에 소비 수를 올려도, launcher가 다른 메시지를 보내거나 rank가 SEND하기 전에는 큐에 쌓인 메시지가 멀쩡한 QP에서 나가지 않았다.

## 고친 것

`launcher_transport_verbs.c`만 바뀌었다(전송 계약 `launcher_transport.h`와 `gin_launcher.c`는 그대로).

- 한 번만 울리는 timerfd(`creditTfd`)를 열고 `fds`의 셋째로 낸다. launcher 루프가 poll하는 fd라 울리면 루프가 깬다(`GL_MAX_TP_FDS` 4 안).
- `gl_v_credit_arm`: credit으로 닫힌 큐(큐 있음, 연결됨, 오류 아님, credit 자리 앎, `seqOut - ackIn >= 64`)가 있고 그 QP에 credit READ가 떠 있지 않으면
  `GL_V_CREDIT_RETRY_MS`(1 ms) 뒤로 건다. `gl_v_poll` 끝과 큐에 넣은 `rc_send` 끝에서 부른다.
- `gl_v_credit_retry`: `gl_v_poll`이 완료를 다 처리한 뒤 timerfd가 울렸으면, 그런 QP마다 `gl_v_credit_read`를 다시 부른다.
- READ는 QP마다 한 번에 하나(`creditReading`, 원래 불변식)다. 다시 읽기는 창이 열리거나, QP가 오류 나거나(`broken`), 닫히면(`rc_close`, launcher의 기존 시한이 정함)
  멈춘다. 따로 둔 횟수 한도는 없다. 닫힌 QP 하나에 많아야 1 ms마다 8 B READ 하나다.

## 어떻게 시험했나

- `launcher_unit.cc`에 가짜 libibverbs(파일 안, `GL_UNIT_VERBS`일 때만)와 장면 `verbs_credit_retry`(22 검사). `build_launcher.sh`는 verbs.h가 있으면
  `launcher_transport_verbs.c`를 ASan, UBSan으로 따로 컴파일해 단위 시험에 붙인다. libibverbs는 링크하지 않고 장치를 열지 않는다.
- 장면: SEND 64개로 창을 채우고 완료, 65번째는 큐로, 첫 READ는 그대로 → 곧바로 READ 없음, timerfd가 읽을 수 있게 됨, 다시 읽기 READ를 5 ms 붙잡는 동안 둘째 READ
  없음, 둘째 다시 읽기에서 값이 10으로 움직임 → 65번째 SEND(envelope seq 65, gen 1, 본문 표시 65), READ 모두 3개, 동시에 떠 있는 READ 최대 1, READ마다 앞 완료부터
  0.9 ms 이상, 큐가 빈 뒤 10 ms 동안 READ 없음, 가짜 객체 누수 0.
- 음성 대조: 같은 장면을 고치기 전 `launcher_transport_verbs.c`(HEAD)에 붙이면 5 검사 실패(깨지 않음, 보내지 않음, READ 수 둘, seq) `[측정, n 1]`. fd 수 검사만 그 대조용으로
  느슨하게 했다(스크래치 사본).
- 고친 뒤 `build_launcher.sh all` 한 번과 `unit` 두 번: 세 번 모두 29 장면 784 검사 실패 0, sanitizer 보고 0 `[측정, n 3]`. 앞의 28 장면 762 검사는 그대로다.
  `gin_launcher` md5 `d1aceaf68f00d99eafa4d585195f3348`, `launcher_unit` `df4f52485166f07aae4e24f5ef804ea7`, `launcher_transport_verbs.c` `1b7b70e7`.
- [미확인] 실제 RNIC에서의 동작. 하드웨어 실행 없음(빌드됨).
