# NCCL 내장 복원력과 다중 요청 복구의 비교 (nccl-builtin)

**목적:** 노드마다 활성 RoCE 포트가 하나인 rain–sunny 테스트베드에서 NCCL 2.32.3의 내장 복원력(port failover, port recovery)과 이
저장소의 다중 요청 복구(NCCL 2.23.4, CPU 프록시 IB 경로)를 같은 주입 장애 네 가지로 돌린다. 각자 무엇을 하고 앱이 무엇을 보는지, 장애가
없을 때 얼마의 비용을 내는지를 사전 등록한 예측으로 잰다.

| 항목 | 값 |
|---|---|
| 상태 | `COMPLETE` |
| 담당자 | @unionxic |
| 작성일 | 2026-10-09 |
| 기준 브랜치와 커밋 | `exp/nccl-builtin` @ `d834f86c` |
| 사전 등록 태그 | `prereg/nccl-builtin-v1` (상태를 `PREREGISTERED`로 바꾼 바로 그 커밋) |
| 마지막 갱신 | 2026-10-09 06:50, 본 실행 기록, 결과, QA, 결론, README, 상태 `COMPLETE` |

표시: `[측정]` 원자료에서 확인, `[소스]` 코드에서 읽음, `[추론]` 해석, `[미확인]` 확인 안 함.

소스 줄 번호는 NCCL v2.32.3-1(upstream 커밋 `12df1a11`)의 `src/` 기준이다. 따로 적지 않으면 `transport/net_ib/` 아래 파일이다.

**용어.**
- 다중 요청 복구: [`../stage2/`](../stage2/README.md)의 NCCL 2.23.4 IB 전송 안 복구. 플래그 `NCCL_RDMA_FAULT_RECOVERY`.
- 내장 복원력: NCCL의 port failover(`NCCL_IB_RESILIENCY_PORT_FAILOVER`)와 port recovery(`NCCL_IB_RESILIENCY_PORT_RECOVERY`).
- 주입 훅: 데이터 QP를 강제로 ERR로 옮기는 시험 전용 코드. 다중 요청 복구 빌드에 들어 있던 것을 2.32.3에 복구 없이 옮겼다(9절 1번).
- 투명: 두 rank가 모든 반복을 마치고 결과 버퍼가 매 반복 bit 단위로 맞다. 오류: 어느 rank의 앱이든 NCCL 오류를 받았다. 멈춤: 오류 없이
  드라이버의 반복 제한(12 s)이나 실행기의 실행 상한에 닿았다.
- 치명 판정: 내장 복원력이 오류 CQE를 받고 "The error is fatal (No functional devices left)"로 끝내는 것.

셀 이름과 설정 키는 원자료를 찾는 키로만 쓴다.

| 장애(작업) | 셀 |
|---|---|
| rank 0의 송신 QP를 ERR로(기본 설정, 16 MiB all-reduce) | `sqp` |
| rank 1의 수신 QP를 ERR로(같은 작업) | `rqp` |
| rank 0이 받는 중 rank 1을 SIGKILL(1채널, 256 KiB all-reduce) | `kill` |
| rank 1의 수신 QP를 조용히 ERR로(1채널, 64 MiB 방송) | `slbc` |
| 같은 장애(1채널, 256 KiB all-reduce) | `slar` |
| 장애 없는 all-reduce 시간(기본 설정, 64 KiB와 16 MiB) | `ovh64k`, `ovh16m` |

| 설정 | 키 |
|---|---|
| NCCL 2.32.3 + 주입 훅, 내장 복원력 끔 | `off` |
| 같은 라이브러리, port recovery 변수만 켬 | `rec` |
| 같은 라이브러리, port failover 켬 | `fo` |
| 같은 라이브러리, port failover와 port recovery 켬 | `forec` |
| 다중 요청 복구 빌드, 플래그 켬 | `s2on` |
| 같은 빌드, 플래그 끔 | `s2off` |

## 1. 배경과 연구 질문

**다중 요청 복구가 이미 보인 것** `[측정]`. `../stage2/results/20260925/*/results.csv`와 Release `data-20261006`의
`harness__nccl-integration__stage2__results__20260925.tar.xz`(sha256 앞 12자 `27bbf767eb65`) 원시 로그에서 다시 셌다(세션 스크래치
`agent_nb/x/`). 시각은 그 실행기의 줄 수신 시각이다. 괄호 안 기호는 원자료의 시험과 측정 회차 이름이다.
- 기본 설정 송신 QP 주입(T2): 빌드 `f7f45278`에서 30/30 투명 복구, 복구 시간 중앙값 2.264 ms(2.220–2.346 ms, 30회의 범위, A). 최종
  빌드 `a037de42`에서 3/3, 2.308–2.400 ms(A5).
- 수신 QP 주입(T3): `f7f45278` 30/30, 중앙값 2.154 ms(2.114–2.271 ms, A). `a037de42` 3/3, 2.152–2.290 ms(A5).
- 받는 중 상대 SIGKILL(T8): `a037de42` 3/3에서 생존 rank 0의 오류가 상대의 마지막 반복 줄 뒤 50.144–50.183 ms, OOB 소켓의 FIN 줄 뒤
  0.013–0.030 ms에 올라왔다(A5). 플래그를 끈 `78f96f38` 3/3은 생존 rank가 communicator 준비 줄 뒤 아무 줄도 남기지 않았고, 실행기가 60 s에
  죽였다(C7, 실행 61.2 s).
- 수신 QP를 조용히 ERR로, 64 MiB 방송(T4, `78f96f38`, C6): 훅 3/3. rank 1은 3/3 모두 비우기만 하고 알리지 않았다. rank 0의
  RETRY_EXC는 1/3이고(훅 뒤 3 557.7 ms), 그 회차는 1.935 ms에 복구했다. 나머지 2/3은 오류 없이 실행 제한(91.2 s)까지 갔다.
- 같은 장애, 256 KiB all-reduce: `f7f45278` 5회(B) 모두 훅이 발사되고 실행 제한까지 오류가 없었다. `78f96f38` 1회(C4)는 훅 뒤
  120 000.99 ms(rank 0)와 120 001.08 ms(rank 1)에 받는 쪽 대기 상한으로 실패했다.
- 플래그를 끈 송신 QP 주입(관리망 차단 뒤의 원본 경로 대조 T12d, `a037de42`): 3/3 오류가 훅 뒤 0.055–0.242 ms에 올라왔다.
- 장애 없는 비용(`../perf`, 빌드 `3b0b760d`, 키마다 3회): 기본 설정 64 KiB에서 플래그 켬이 끔보다 +1.27 %, 16 MiB에서 −0.22 %였다.
  플래그 끔끼리의 흩어짐((최대−최소)/중앙값)은 여덟 키에서 0.2–1.7 %다. Release `data-20261006`의
  `harness__nccl-integration__perf__results__20260925.tar.xz`의 `overhead_stage2` 원시 로그에서 다시 셌다.

**NCCL 내장 복원력이 들어온 버전** `[소스]`. upstream 태그를 받아 변수 이름을 찾았다. port failover는 v2.29.7-1에 처음 있고(v2.29.3-1에는
없음), port recovery는 v2.30.3-1에 처음 있다(v2.29.7-1에는 없음). GID_CHANGE 처리와 재설정 때 GID 다시 읽기는 v2.31.2-1에 처음
있다(v2.30.7-1에는 없음). 이 실험은 v2.32.3-1을 쓴다.

**v2.32.3-1이 하는 일** `[소스]`.
1. **켜는 조건.** `NCCL_IB_RESILIENCY_PORT_FAILOVER=1`이 아니면 communicator마다 복원력 문맥을 만들지 않는다(`p2p_resiliency.cc` 618–623행).
   port recovery는 그 문맥 안에서만 쓰인다. `NCCL_IB_RESILIENCY_PORT_RECOVERY=1`만 켜면 복구 스레드만 뜨고(`p2p_resiliency_recovery.cc`
   1470–1488행, `init.cc` 682행) 데이터 경로는 그대로다.
2. **failover가 바꾸는 데이터 경로.** 수신 매칭을 ID 방식으로 바꾸고(`common.cc` 76–81행), 수신 WR을 미리 걸어 두고(93–98행), CTS
   쓰기를 모두 signaled로 보낸다(`p2p.cc`의 `ncclIbPostFifo`). 장치마다 확인 읽기용 QP와 CQ를 만든다. recovery를 켜면 장치마다 UC QP가
   하나 더 생긴다.
3. **무엇이 복구를 시작하나.** 데이터 CQ의 오류 CQE뿐이다(`p2p.cc`의 `ncclIbTest`에서 `ncclIbResiliencyHandleCompletionError`,
   `p2p_resiliency.cc` 1201–1220행). 포트 이벤트(PORT_ERR, PORT_ACTIVE)는 비동기 스레드가 경고 줄만 남긴다(`common.cc` 218–231행).
   GID_CHANGE는 장치의 GID 정보만 다시 읽는다(116–145행).
4. **오류 CQE의 처리 순서.** 먼저 치명 여부를 본다(`p2p_resiliency.cc` 23–65행). 이번 장치를 포함해 실패한 장치 수가 장치 수와 같으면
   "No functional devices left"로 ncclRemoteError를 돌려준다. 상태가 WR_FLUSH_ERR, RETRY_EXC_ERR가 아니어도 치명이다. 치명이 아닐 때만
   다음으로 간다.
   - 장치를 실패로 표시하고 그 장치의 QP를 다른 장치의 QP로 바꾼다(68–124행, 376–405행).
   - 보내는 쪽은 10 ms 뒤 받는 쪽 완료 기록을 RDMA READ로 읽어 빠진 QP만 다시 보낸다(458–545행, 414–456행).
   - recovery를 켰으면 실패한 장치를 비동기 스레드에 넣는다. 200 ms 뒤 QP를 다시 설정하고, "살아 있음" 메시지를 500 ms 간격으로
     주고받아(응답 상한 4 000 ms와 5 000 ms, 20회) 성공하면 원래 QP를 되돌린다(`p2p_resiliency_recovery.cc` 10–19행, 1234–1308행).
5. **장치가 하나면.** 연결 때 송신, 수신 communicator 모두 "... with a single device. This does not make sense since there is no other device
   to fail over to."를 경고한다(840–844행). 오류 CQE 하나가 곧 "모든 장치 실패"라서 치명 판정이 먼저 난다. QP 교체, 확인 읽기, port
   recovery는 어느 것도 시작되지 않는다 `[추론]`.
6. **앱이 보는 것.** 복원력이 없을 때와 같은 ncclRemoteError다. 프록시가 그 값을 communicator의 비동기 오류로 둔다(`proxy.cc` 980행).
   로그만 다르다. 복원력이 없으면 "Got CQE with error"와 "Got completion from peer ... status=...(n)"이 남고, 있으면 "Got completion with
   error"(INFO)와 치명 판정 줄이 남는다.
7. **상대 프로세스의 죽음.** 이 경로에는 CQE로만 보인다. RAS는 communicator 상태를 읽기만 한다(`ras/collectives.cc` 725–731행).
8. **오류 뒤의 진행 스레드와 abort.** 2.32.3의 프록시 진행 스레드는 첫 오류를 비동기 오류로 두고 루프를 빠져나간다(`proxy.cc`
   978–983행). 그래서 오류를 받은 rank는 그 뒤 어떤 연결로도 더 보내지 않는다. 2.23.4는 오류를 기록하고 루프를 계속 돈다(v2.23.4-1
   `proxy.cc` 894–899행). 두 버전 모두 앱이 `ncclCommAbort`를 부르면 GPU 커널이 오지 않을 데이터를 기다리던 루프를 빠져나와 다음 단계로
   간다(v2.23.4-1 `device/prims_simple.h` 128–133행, v2.32.3-1 111행). 그래서 2.23.4에서는 오류를 받아 abort한 rank가 아직 살아 있는
   다른 연결로 덜 만든 데이터를 보낼 수 있고, 그것을 기다리던 상대는 틀린 결과로 연산을 마칠 수 있다 `[추론]`. 이 항목은 pilot의
   `rqp@s2off` 결과를 보고 소스를 다시 읽어 더했다(12절).

**이 테스트베드** `[측정]`. 2026-10-09 00:45 rain sysfs에서 mlx5_0 port 1은 DOWN(Disabled), mlx5_1은 ACTIVE였다. NCCL은 ACTIVE가 아닌
포트를 쓰지 않는다(`init.cc` 505행) `[소스]`. 이전 실험처럼 rank마다 `NCCL_IB_HCA`로 한 장치만 쓴다(rain mlx5_1, sunny mlx5_0). sunny의
포트는 2026-10-09 pilot hold 스냅숏에서 mlx5_0 ACTIVE, mlx5_1 DOWN이었다 `[측정]`. 두 노드 모두 활성 포트가 하나다.

**비어 있는 것.**
- NCCL 내장 복원력을 이 테스트베드에서 돌려 본 적이 없다.
- 다중 요청 복구와 같은 날, 같은 실행기로 나란히 잰 적이 없다.
- 다중 요청 복구의 수신 QP 장애에는 플래그 끔 대조가 없다.

**질문.**
1. 노드마다 활성 포트가 하나일 때 NCCL 2.32.3의 port failover와 port recovery는 네 장애에서 무엇을 하고, 앱은 무엇을 보는가? 복원력을
   끈 2.32.3과 다른 것은 로그뿐인가?
2. port recovery 변수만 켜면 무엇이 바뀌는가?
3. 같은 장애, 같은 날, 같은 실행기에서 다중 요청 복구는 이전 결과를 재현하는가? 플래그를 끄면 어떻게 실패하는가?
4. 2.32.3의 "조용한" 수신 QP 장애는 조용히 남는가, 장애를 낸 rank 자신이 알아채는가?
5. 장애가 없을 때 failover, failover와 recovery, 다중 요청 복구를 켜면 all-reduce 시간이 얼마나 바뀌는가?
6. 한 rank의 장애가 상대에게 틀린 결과로 새어 나가는가? (pilot 뒤 더한 질문, 12절)

## 2. 가설

| id | 가설 | 다음이 관측되면 틀린 것이다 |
|---|---|---|
| H1 | 장치가 하나면 내장 복원력은 어떤 장애도 숨기지 못한다. 주입한 QP 장애는 복원력 없는 2.32.3과 같은 ncclRemoteError로 1 s 안에 올라오고, 장치 실패 표시, QP 교체, 확인 읽기, port recovery는 시작되지 않는다 | failover나 failover와 recovery 셀에서 투명한 시행이 하나라도 있다. 또는 복구 동작 줄이 하나라도 있다. 또는 송신, 수신 QP 셀(셀마다 10회)에서 치명 판정과 1 s 안 ncclRemoteError가 9/10 미만이다 |
| H2 | port recovery 변수만 켜면 데이터 경로가 바뀌지 않는다 | `sqp@rec`에서 failover 경고, 치명 판정, 복구 동작 줄이 나오거나 원본 오류 경로가 4/5 미만이다 |
| H3 | 다중 요청 복구는 같은 날 같은 실행기에서도 이전 결과를 재현한다 | 예측 S1–S5 중 하나라도 틀린다 |
| H4 | 플래그를 끈 다중 요청 복구와 복원력 없는 2.32.3은 송신, 수신 QP 장애를 1 s 안의 오류로, 받는 중 상대의 죽음을 멈춤으로 보인다 | 예측 B1–B3, S6–S8 중 하나라도 틀린다 |
| H5 | 2.32.3에서는 "조용한" 수신 QP 장애도 rank 1 자신이 1 s 안에 오류로 올린다. 다중 요청 복구는 rank 1에서 조용히 둔다 | 예측 B4, F4, S4 중 하나라도 틀린다 |
| H6 | 장애가 없을 때의 비용은 작다 | 예측 O1–O4 중 하나라도 틀린다 |
| H7 | 2.23.4의 원본 오류 경로에서는 오류를 받아 abort한 rank 때문에, 살아 있는 상대가 장애 난 집합 연산을 오류 없이 틀린 결과로 마칠 수 있다. 2.32.3에서는 그런 일이 없다 | 예측 S9나 I1이 틀린다 |

## 3. 사전 예측

**고정 시점.** 예측 원문은 [predictions.csv](predictions.csv)(27줄)다. 예측은 사전 등록 태그를 달 때 고정한다.
- 메인 세션이 pilot(9절의 P1, P2, 2026-10-09 01:03:42–01:10:21, 34회)을 돌렸다. **이 절의 예측과 판정식, 7절의 반복 수는 그 pilot을 검토한
  뒤 확정했다.** 바꾼 것과 그 근거가 된 pilot 관측은 12절에 있다.
- 바꾼 것은 세 종류뿐이다. 소스를 덜 읽어 생긴 예측의 고침(S7, I1, 새 예측 S9), pilot에서 시행이 싸게 끝나 늘린 반복 수와 그에 맞춘 기준
  (B1–B4, F3, F4, O5), 하네스 정의의 고침(3.1의 `outcome`과 새 열)이다. pilot에 맞추려고 바꾼 예측은 없다. pilot과 어긋났지만 소스로
  설명하지 못한 예측(O3)은 그대로 두고 의문을 12절에 적었다.
- 상태를 `PREREGISTERED`로 바꾸고 `predictions.csv`의 sha256을 `PREREG.txt`에 적은 커밋 하나에 `prereg/nccl-builtin-v1`을 단다.
- **pilot 시행은 어떤 경우에도 채점하지 않는다.** 태그 뒤에는 13절 규칙을 따른다.

`kind`는 N(2.32.3의 새 셀), R(다중 요청 복구 재현), C(대조), A(모든 셀)다.

### 3.1 판정에 쓰는 열

시행마다 한 줄이다. [rows_nb.py](rows_nb.py)가 시행 파일(`<cell>.<cfg>_n<k>_r0.log`, `_r1.log`, `_meta.txt`)에서 만든다. 로그의 모든
줄에는 실행기가 받은 시각(rain의 CLOCK_MONOTONIC)이 붙는다. rank 1의 줄은 ssh로 온다. 두 rank 모두 NCCL의 출력과 드라이버의 출력이 한
파이프로 오므로, 같은 rank 안에서 줄의 순서는 쓴 순서다. 열 이름 끝의 `_r<r>`은 rank `r`의 로그에서 읽는다는 뜻이다.

| 열 | 정의 |
|---|---|
| `cell`, `cfg`, `trial` | 셀, 설정 키, 시행 번호(`n<k>`) |
| `rc0`, `rc1` | 실행기가 받은 종료 코드(rank 1은 ssh의 종료 코드) |
| `ready_r<r>` | 드라이버의 `comm ready:` 줄 수. `launch_fail`은 어느 rank든 0이면 1 |
| `ver_r0` | rank 0의 `NCCL version <x.y.z>` 줄의 버전 |
| `inj_r<r>`, `inj_kind` | `[FAULT-INJECT] forced (send\|recv) QP` 줄 수, 첫 줄의 종류(`send`, `recv`, 줄에 `[silent]`가 있으면 `silent`) |
| `t_fault` | 장애 시각: kill 셀은 실행기가 kill을 보내기 직전(`t_kill_req`), 주입 셀은 첫 훅 줄을 받은 시각 |
| `kill_rtt_ms` | kill 셀에서 kill을 보낸 ssh 명령이 돌아오기까지(ms). kill은 이 사이에 일어난다(pilot 5회 246–250 ms) |
| `err_r<r>`, `errcode_r<r>` | 그 rank 드라이버의 첫 NCCL 오류 줄: `async`(`async NCCL error`), `call`(호출이 오류를 돌려줌). 오류 문자열을 결과 이름으로 바꾼 값(예: `ncclRemoteError`) |
| `dt_err_r<r>` | 그 오류 줄의 수신 시각 − `t_fault`(ms). `dt_to_r<r>`은 `TIMEOUT after` 줄의 같은 값 |
| `first_err_rank` | 오류 줄이 먼저 온 rank |
| `wc_status_r<r>` | 그 rank 로그의 첫 오류 CQE 상태 번호. 2.32.3 원본 줄 `status=<이름>(<n>)`, 2.32.3 복원력 INFO 줄 `wc->status=(<이름>)<n>`, 2.23.4 원본 줄 `status=<n>`, 다중 요청 복구 줄 `incident via <x>: status=<n>(` 중 처음 나온 것. 5는 WR_FLUSH_ERR, 12는 RETRY_EXC_ERR |
| `stock_cqe_r<r>` | 원본 오류 CQE 줄(`NET/IB: Got CQE with error`, `NET/IB: Got completion from peer`) 수 |
| `single_dev_r<r>` | `no other device to fail over to` 줄 수 |
| `fatal_nfd_r<r>` | `The error is fatal (No functional devices left)` 줄 수 |
| `prec_activity_r<r>` | 복원력 동작 줄 수: `marked as failed. Initiating recovery`, `into the recovery queue`, `Starting port recovery for`, `Port recovery succeeded`, `Port recovery failed`, `Replacing QP`, `Posting probe` |
| `res_init_r<r>`, `res_disabled_r<r>`, `prec_enabled_r<r>`, `prec_disabled_ctx_r<r>`, `prec_thread_r<r>` | 설정 확인 줄 수: `Resiliency context was initialized on the`, `Resiliency is disabled on the`, `Port recovery is enabled for the resiliency context`, `Port recovery is disabled for the resiliency context`, `Starting port recovery async thread` |
| `n232_mark_r<r>` | `Receive work requests will be` 줄 수(2.32.3만 남기는 INFO 줄. rank 1이 어느 라이브러리를 읽었는지 확인) |
| `env_fo`, `env_rec`, `env_s2`, `debug` | 실행기가 두 rank에 준 환경(meta 파일)의 `NCCL_IB_RESILIENCY_PORT_FAILOVER`, `NCCL_IB_RESILIENCY_PORT_RECOVERY`, `NCCL_RDMA_FAULT_RECOVERY`, `NCCL_DEBUG` 값, `<rank 0>/<rank 1>` 형식 |
| `s2_on_r<r>`, `s2_rec`, `s2_rec_ms`, `s2_fin_r<r>` | 다중 요청 복구: `[FAULT-RECOVERY2] recovery on for` 줄 수, 두 rank의 `comm: recovered` 줄 수, 첫 송신 통신기 복구 줄의 `total` ms, `closed its OOB socket (FIN)` 줄 수 |
| `ok_r<r>`, `iters_r<r>`, `med_ms_r<r>` | 드라이버 `SUMMARY` 줄의 `ok`, `iters`, `med_ms`(반복 한 번 시간의 중앙값) |
| `timeout_r<r>`, `abort_ret_r<r>`, `abort_hang_r<r>` | `TIMEOUT after`, `ncclCommAbort returned`, `ABORT-HANG` 줄 수 |
| `mism_r<r>`, `mism`, `dt_mism_r<r>` | 그 rank의 `MISMATCH` 줄 수, 두 rank의 합, 첫 `MISMATCH` 줄의 수신 시각 − `t_fault`(ms) |
| `mism_pre_to` | 어느 rank든 첫 `TIMEOUT after` 줄보다 먼저 받은 `MISMATCH` 줄 수(TIMEOUT이 없으면 `mism`과 같다) |
| `outcome` | `MISMATCH`(`mism_pre_to > 0`), `TRANSPARENT`(두 rank 종료 코드 0, 두 rank 모두 `ok == iters`), `ERROR`(아니고 어느 rank든 오류 줄), `HANG`(아니고 TIMEOUT 줄이 있거나 실행 상한에 닿음), `OTHER`(그 밖). 드라이버는 TIMEOUT 뒤 `ncclCommAbort`를 부른다. abort한 커널이 덜 만든 데이터를 상대에게 넘길 수 있으므로(1절 8번) TIMEOUT 뒤의 `MISMATCH`는 하네스가 끝내는 방식의 산물로 보고 결과 분류에 넣지 않는다. 그런 줄도 `mism`에는 남는다(pilot 뒤 고침, 12절) |
| `kill_ok`, `wallcap`, `grace_kill_r<r>` | kill이 PID 확인을 거쳐 보내졌으면 1. 실행 상한에 닿았으면 1. 다른 rank가 0이 아닌 코드로 끝난 뒤 6 s가 지나 실행기가 끝냈으면 1 |

### 3.2 셀 키와 판정식 문법

셀 키는 `cell@cfg`다. 판정 대상은 8절 제외를 거친 시행이다. 판정식 문법(`count`, 빈칸 규칙, `has`, `nonempty`, `median`, `abs`,
`per cell:`)은 `../../gpu-initiated/gin_recovery/s2_close/EXPERIMENT.md` 3.2절과 같고, `count(...)`와 `median(...)` 밖은 Python의 산술과
비교다. [score.py](score.py)는 `../../gpu-initiated/gin_recovery/s2_close/score.py`의 평가 함수를 그대로 불러 쓴다. 계획한 반복 수(7절)를
채우지 못한 셀 키가 하나라도 있는 예측은 "자료 부족"이다. 판정은 맞음, 틀림, 자료 부족 중 하나다.

### 3.3 예측 요약

전체 판정식과 근거는 [predictions.csv](predictions.csv)에 있다. 아래는 요약이다.

| id | 셀 | 예측 | 판정 기준(요약) | 근거 |
|---|---|---|---|---|
| B1 | `sqp@off` | 복원력 없는 2.32.3: 송신 QP 장애가 rank 0에서 1 s 안에 ncclRemoteError로 올라온다. 원본 오류 CQE 줄과 WR_FLUSH_ERR가 남는다 | ≥9/10 | `ncclIbTest` `[소스]`, 다중 요청 복구 끔 0.055–0.242 ms(3회) `[측정]` |
| B2 | `rqp@off` | 수신 QP 장애가 rank 1 자신에게서 1 s 안에 ncclRemoteError로 올라온다 | ≥9/10 | 걸어 둔 수신과 다음 CTS가 비워짐 `[소스]` |
| B3 | `kill@off` | 받는 중 상대가 죽으면 생존 rank는 12 s 반복 제한까지 오류를 보지 못한다 | 멈춤 ≥9/10 | 1절 7번 `[소스]`, 2.23.4 끔 3/3 `[측정]` |
| B4 | `slbc@off`, `slar@off` | "조용한" 장애도 rank 1 자신이 1 s 안에 ncclRemoteError로 올린다 | 셀마다 ≥9/10 | 걸어 둔 수신이 비워짐 `[소스]` |
| R1 | `sqp@rec` | recovery 변수만 켜면 `off`와 같다. 원본 오류 경로이고 failover 경고, 치명 판정, 복구 동작 줄이 없다 | ≥4/5 | 1절 1번 `[소스]` |
| F1 | `sqp@fo`, `sqp@forec` | 첫 오류 CQE에서 곧바로 치명 판정, rank 0에 1 s 안 ncclRemoteError. 원본 오류 CQE 줄과 복구 동작 줄이 없다 | 셀마다 ≥9/10 | 1절 4, 5번 `[소스]` |
| F2 | `rqp@fo`, `rqp@forec` | 같은 판정이 rank 1에서 | 셀마다 ≥9/10 | 같음 |
| F3 | `kill@fo`, `kill@forec` | 생존 rank는 12 s 반복 제한까지 오류를 보지 못한다 | 셀마다 멈춤 ≥9/10 | 1절 3, 7번 `[소스]` |
| F4 | `slbc@fo`, `slbc@forec`, `slar@fo`, `slar@forec` | rank 1 자신이 치명으로 판정해 1 s 안에 올린다 | 셀마다 ≥9/10 | B4와 F1 `[소스]` |
| F5 | failover를 켠 셀 14개(장애 10, 장애 없음 4) | 모든 시행에서 두 rank가 연결 때 "넘겨 갈 다른 장치가 없다"고 경고한다(WARN 줄이라 모든 셀에서 보인다) | 셀마다 예외 0 | 1절 5번 `[소스]` |
| F6 | 2.32.3 장애 셀 16개 | 어느 설정도 어느 장애도 투명하게 만들지 못한다 | 셀마다 투명 0 | H1 |
| F7 | 2.32.3 장애 셀 16개 | 장치 실패 표시, QP 교체, 확인 읽기, port recovery 줄이 없다. kill 셀은 WARN이라 이 중 장치 실패 표시 줄만 보인다 | 셀마다 0 | 1절 4, 5번 `[소스]` |
| S1 | `sqp@s2on`, `rqp@s2on` | 다중 요청 복구가 두 QP 장애를 투명하게 복구한다 | 셀마다 5/5 | 30/30, 30/30, 최종 빌드 3/3, 3/3 `[측정]` |
| S2 | 같음 | 복구 시간(송신 통신기 `total`) 중앙값이 두 셀 모두 1.8–3.0 ms | 셀 중앙값 | 2.152–2.400 ms(최종 빌드 6회) `[측정]` |
| S3 | `kill@s2on` | OOB 소켓의 FIN으로 상대의 죽음을 알아 kill 뒤 1 s 안에 생존 rank에 오류를 올린다 | 5/5 | 3/3 `[측정]` |
| S4 | `slbc@s2on` | rank 1은 1 s 안에 오류를 올리지 않는다. 작업은 투명하게 복구되거나 멈춘다 | 5/5 | 3회 `[측정]` |
| S5 | `slar@s2on` | 보내는 쪽이 할 일이 없어 12 s 반복 제한까지 멈춘다(TIMEOUT 뒤의 틀린 결과는 결과 분류에 넣지 않는다, 3.1) | 5/5 | 5회와 1회 `[측정]` |
| S6 | `sqp@s2off` | 1 s 안 ncclRemoteError, WR_FLUSH_ERR, 복구 줄 없음 | 5/5 | 3/3 `[측정]` |
| S7 | `rqp@s2off` | rank 1에서 1 s 안 ncclRemoteError, 복구 줄 없음. 결과 분류는 묻지 않는다(S9) | ≥4/5 | `[소스]`, 이전 대조 없음 `[미확인]`, pilot 뒤 고침 |
| S8 | `kill@s2off` | 생존 rank는 12 s 반복 제한까지 오류를 보지 못한다 | 멈춤 ≥4/5 | 3/3 `[측정]` |
| S9 | `rqp@s2off` | rank 1이 오류를 받아 abort한 뒤, rank 0은 장애 난 all-reduce를 자기 오류 없이 틀린 결과로 마친다. 틀린 결과는 rank 1의 오류보다 뒤에 온다 | ≥4/5 | 1절 8번 `[소스, 추론]`, pilot 1/1 `[측정, pilot, 채점 안 함]`, pilot 뒤 더함 |
| I1 | `rqp@s2off`, `slar@s2on`을 뺀 셀 32개 | 어느 시행도 틀린 결과를 내지 않는다(MISMATCH 없음) | 셀마다 0 | 1절 8번 `[소스, 추론]`, pilot 뒤 고침 |
| O1 | `ovh16m@fo` 대 `ovh16m@off` | failover가 rank 0 반복 시간 중앙값을 2 % 넘게 바꾸지 않는다 | 실행 중앙값의 차이 | 1절 2번 `[소스]`, 크기는 `[추론]` |
| O2 | `ovh64k@fo` 대 `ovh64k@off` | 5 % 넘게 바꾸지 않는다 | 같음 | 같음 |
| O3 | `forec` 대 `fo`, 두 크기 | port recovery를 더해도 2 % 넘게 바뀌지 않는다 | 같음 | 쉬는 스레드와 QP뿐 `[소스]` |
| O4 | `s2on` 대 `s2off`, 16 MiB와 64 KiB | 2 %, 3 % 안 | 같음 | +1.27 %, −0.22 %(3회씩) `[측정]` |
| O5 | 장애 없는 셀 10개 | 모든 실행이 투명하다 | 셀마다 10/10 | `[추론]` |

### 3.4 탐색 관찰(채점하지 않음)

다음은 예측 없이 기록만 하고 15절에 서술한다.
- 2.32.3 장애 셀에서 장애를 내지 않은 rank가 겪는 일: 상대가 끝난 뒤 RETRY_EXC를 받는지, 실행기의 6 s 유예 뒤에 끝나는지.
- 2.32.3에서 오류 뒤 `ncclCommAbort`가 돌아오는지(`abort_ret_r<r>`, `abort_hang_r<r>`). 2.23.4에서는 1절의 원시 로그 중 오류 뒤 abort를
  부른 rank 로그 14개(A5의 T8과 T9, C4, T12d) 모두 감시 시간에 끝났고 돌아온 것은 0이다 `[측정]`. pilot에서는 2.32.3으로 abort를 부른 rank
  로그 22개 모두 돌아왔고, 2.23.4로 부른 7개는 모두 감시 시간에 끝났다 `[측정, pilot]`.
- TIMEOUT 뒤의 틀린 결과(`mism`과 `mism_pre_to`의 차): 특히 `slar@s2on`에서 rank 1이 먼저 시간 초과하는 경우.
- `slbc@s2on`에서 투명 복구된 비율.
- 장애에서 앱 오류까지의 시간 분포(설정별).

## 4. 범위

**포함.**
- 9절 1번의 주입 훅 하나(2.32.3 `p2p.cc` 한 파일, 복구 없음).
- 7절의 셀 34개: 장애 셀 24개(2.32.3 설정 네 가지, 다중 요청 복구 두 가지)와 장애 없는 셀 10개.
- 9절 3번의 실행기(`nbrun.py`, `cells.py`). 다중 요청 복구의 드라이버(`../perf/nccl_ct.cu`)를 그대로 쓴다.

**제외.**
- 관리망 차단: iptables 같은 방화벽 변경이 필요하다. 이 실험은 하지 않는다.
- RoCE 주소 제거와 재추가(다중 요청 복구의 주소 재구성 시험): 주소 변경은 하지 않는다.
- 실제 link down과 flap, 두 번째 포트를 켜는 것(rain mlx5_0을 올리는 것은 링크 변경이다). 그래서 내장 복원력이 장치를 넘겨 가는 경로는
  재지 못한다. 이 실험은 장치가 하나일 때의 동작만 잰다.
- sunny에서만 장치를 둘 쓰는 비대칭 구성, 3 rank 이상, GPU가 직접 거는 GIN 경로.
- 내장 복원력의 다른 변수(확인 읽기 지연, 최대 시도 수, recovery 시각)의 기본값이 아닌 값.
- 다중 요청 복구 끔의 조용한 장애 셀(`slbc@s2off`, `slar@s2off`): 그 빌드의 조용한 훅은 플래그를 켰을 때만 걸린다(`net_ib_stage2.diff`의
  `fr2Attach`) `[소스]`.
- 원격 접근 오류, 답하지 않는 상대(다중 요청 복구의 F2, T9): 내장 복원력은 WR_FLUSH_ERR, RETRY_EXC_ERR 밖의 상태를 모두 치명으로 본다
  `[소스]`.

## 5. 테스트베드와 버전

| 항목 | 값 | 확인 방법과 날짜 |
|---|---|---|
| 노드 | rain(rank 0), sunny(rank 1) | 루트 `README.md` 테스트베드 표 |
| NIC와 포트 | ConnectX-6, fw 20.43.4100(두 노드). rain mlx5_0 port 1 DOWN(Disabled), mlx5_1 ACTIVE(Ethernet). sunny mlx5_0 ACTIVE, mlx5_1 DOWN. 쓰는 장치는 rain mlx5_1, sunny mlx5_0(`NCCL_IB_HCA`). NCCL이 만든 가상 장치는 `ndevs=1` | rain `[측정]` 2026-10-09 00:45 sysfs. 두 노드 `[측정]` pilot hold 스냅숏 4개(01:04–01:10)에서 같음. `ndevs=1`은 pilot rank 0의 INFO 줄 `Made virtual device [0] name=mlx5_1 ... ndevs=1` `[측정]` |
| 커널 | rain 5.15.0-97-generic, sunny 6.8.0-138-generic | `[측정]` pilot hold 스냅숏 |
| GPU, 드라이버, CUDA | rain Quadro RTX 5000, 드라이버 570.211.01, CUDA 12.8(nvcc 12.8.93). sunny RTX A4000 | rain `[측정]` 2026-10-09. sunny는 루트 README `[미확인]` |
| 관리망 소켓 | `NCCL_SOCKET_IFNAME=eno1` | `cells.py` |
| IB 타임아웃 | `NCCL_IB_TIMEOUT=14`, 재시도 횟수는 기본(7) | `cells.py` |
| 2.32.3 + 훅(`n232`) | libnccl md5 `9269cc75b0a75cbdc327b075cd26234c`. upstream v2.32.3-1(`12df1a11`) + [inject_232.diff](inject_232.diff)(md5 `c4709b2e`, `p2p.cc` 96줄 추가) | `[측정]` 2026-10-09 00:36 빌드됨. [build_nb.sh](build_nb.sh)가 빌드 전에 소스 트리가 태그 + diff와 같은지 확인했다. 내 스크래치 트리와 upstream 태그는 `bindings/nccl4py/.git_archival.txt`만 다르다. 배포 뒤 두 노드의 md5가 같다([deploy_check.txt](deploy_check.txt), pilot hold 스냅숏 4개) |
| 다중 요청 복구(`s2`) | libnccl md5 `9ed03e1d4b9833c0c2e01f3aa1f84d1c`(최종 빌드 `a037de42` + 쓰지 않는 원격 접근 훅) | `[측정]` v2.23.4-1의 `net_ib.cc`에 `../stage2/net_ib_stage2.diff`를 적용하면 git hash-object `18d998a8`로 diff 머리말과 같다. 이 바이너리가 그 소스에서 나왔다는 것은 `../stage2/NOTES.md`의 기록이다 `[미확인]`. 배포 뒤 두 노드의 md5가 같다 `[측정]` |
| 드라이버 `nb_ct` | md5 `523fd8637c185caa39987f10543b893f`. `../perf/nccl_ct.cu`를 고치지 않고 2.23.4의 `nccl.h`로 sm_75, sm_86 컴파일 | `[측정]` rain에서 `ldd -r`로 두 라이브러리 모두 해결 안 된 기호가 없음을 확인. 두 노드 두 번들에서 md5가 같다. pilot 34회에서 두 라이브러리 모두로 돌았다 |

## 6. 변수

- **독립변수.** 설정(`off`, `rec`, `fo`, `forec`, `s2on`, `s2off`), 장애(송신 QP ERR, 수신 QP ERR, 받는 중 상대 SIGKILL, 수신 QP를 조용히
  ERR), 작업(기본 설정 16 MiB all-reduce, 1채널 256 KiB all-reduce, 1채널 64 MiB 방송), 장애 없는 작업의 크기(64 KiB, 16 MiB).
- **종속변수.** 3.1의 열. 결과 분류, 앱이 받은 오류와 그 시각, 오류 CQE 상태, 치명 판정과 복원력 동작 줄, 다중 요청 복구의 복구 줄과 시간,
  abort가 돌아왔는지, 반복 시간 중앙값.
- **통제변수.**
  - IB 타임아웃 14, 드라이버 반복 제한 12 s(`--timeout 12`), abort 감시 10 s(`NCCL_CT_ABORT_WATCHDOG_S=10`), 실행 상한(장애 셀 40 s,
    장애 없는 셀 15 s), 한 rank가 0이 아닌 코드로 끝난 뒤의 유예 6 s.
  - 로그 수준: QP 장애 셀(`sqp`, `rqp`, `slbc`, `slar`)은 `NCCL_DEBUG=INFO`, `NCCL_DEBUG_SUBSYS=INIT,NET`(복원력의 INFO 줄과 설정 확인
    줄을 보기 위함). kill 셀과 장애 없는 셀은 `NCCL_DEBUG=WARN`. failover를 켜면 CTS 완료가 이미 끝난 요청을 찾을 때마다 INFO 줄을
    남길 수 있어(`p2p.cc`의 `ncclIbCompletionEventProcess`) `[소스]`, 반복마다 시간이 들 수 있는 셀에서는 INFO를 쓰지 않는다 `[추론]`.
    NCCL 버전 줄과 단일 장치 경고는 WARN에서도 보인다.
  - 주입 위치는 다중 요청 복구 시험과 같다: 송신 301번째 multi-send, 수신 301번째 수신 게시, 조용한 장애는 301번째(방송)와 403번째
    (all-reduce) 수신 완료 뒤.
  - 장애 셀은 warmup 없이(`--warmup 0`) 모든 반복을 검사한다. 그래서 장애가 검사하는 반복 안에 든다. kill 셀만 warmup 5회다.
  - 시행마다 두 프로세스를 새로 띄운다. GID 인덱스는 시행마다 sysfs에서 읽는다(첫 RoCE v2 IPv4 GID).

## 7. 실험 셀, 반복 수, 대조군

반복 수는 pilot을 본 뒤 확정했다(12절). 2.32.3의 새 장애 셀(`off`, `fo`, `forec`) 10회, 대조(`rec`, `s2off`)와 다중 요청 복구 재현(`s2on`)
5회, 장애 없는 셀은 모두 10회다(oneway의 새 셀 10, 재현과 대조 5 규칙). 장애 없는 셀의 반복은 실행 수다.

| 셀 | 조건 | 설정과 반복 수 | 종류 |
|---|---|---|---|
| `sqp` | 기본 설정, 16 MiB all-reduce 150회, warmup 0. rank 0에 `NCCL_RDMA_FAULT_INJECT=301` | `off`, `fo`, `forec` 각 10, `rec`, `s2on`, `s2off` 각 5 | N, N, N, C, R, C |
| `rqp` | 같은 작업. rank 1에 `NCCL_RDMA_FAULT_INJECT_RECV=301` | `off`, `fo`, `forec` 각 10, `s2on`, `s2off` 각 5 | N, N, N, R, C |
| `kill` | 1채널, 256 KiB all-reduce 300 000회(`--quiet`), warmup 5. rank 0을 띄운 뒤 5 s에 실행기가 rank 1을 PID로 SIGKILL | `off`, `fo`, `forec` 각 10, `s2on`, `s2off` 각 5 | N, N, N, R, C |
| `slbc` | 1채널, 64 MiB 방송 60회, warmup 0. rank 1에 `NCCL_RDMA_FAULT_INJECT_RECV=301`, `NCCL_RDMA_FAULT_INJECT_RECV_SILENT=1` | `off`, `fo`, `forec` 각 10, `s2on` 5 | N, N, N, R |
| `slar` | 1채널, 256 KiB all-reduce 1 000회, warmup 0. rank 1에 같은 조용한 훅, 403번째 | `off`, `fo`, `forec` 각 10, `s2on` 5 | N, N, N, R |
| `ovh64k` | 기본 설정, 64 KiB all-reduce 2 000회, warmup 20, 장애 없음 | `off`, `fo`, `forec`, `s2on`, `s2off` 각 10 | N, N, N, R, R |
| `ovh16m` | 기본 설정, 16 MiB all-reduce 200회, warmup 5, 장애 없음 | 같음 | 같음 |

1채널은 `NCCL_MAX_NCHANNELS=1`, `NCCL_MIN_NCHANNELS=1`, `NCCL_ALGO=Ring`, `NCCL_PROTO=Simple`, `NCCL_IB_QPS_PER_CONNECTION=1`이다
(`../stage2/run_tests.py`와 같다). 기본 설정은 NCCL이 고른다.

**합계.**

| 종류 | 장애 셀 시행 | 장애 없는 실행 |
|---|--:|--:|
| 2.32.3(`off`, `rec`, `fo`, `forec`) | 155 | 60 |
| 다중 요청 복구 켬 | 25 | 20 |
| 다중 요청 복구 끔 | 15 | 20 |
| 합 | 195 | 100 |

장애 셀 시행 195회는 셀 키 24개의 합이다(`sqp` 45, `rqp` 40, `kill` 40, `slbc` 35, `slar` 35). 장애 없는 실행 100회는 셀 키 10개의 합이다.
pilot은 따로 34회다(셀 키마다 1회, 9절, 채점 안 함).

## 8. 제외 기준과 중단 기준

**제외 기준.** 제외한 시행은 셀별로 따로 세어 보고하고, 다음 번호로 계획한 반복 수를 채운다.
- pilot 실행(`results/<날짜>_pilot/`)은 채점하지 않는다.
- 시작 실패: 어느 rank든 통신기 준비 줄이 없다(`launch_fail == 1`). 포트 충돌, 초기화 실패.
- 장애 미적용: 주입 셀에서 장애를 낼 rank의 훅 줄이 없다(`sqp`는 `inj_r0 == 0`, `rqp`, `slbc`, `slar`는 `inj_r1 == 0`).
- kill 미적용: PID 확인을 거친 kill이 없다(`kill_ok != 1`). 또는 생존 rank가 1 000회를 마치기 전에 kill했다(`ok_r0 < 1000`).
- 채우려고 다시 돈 시행이 셀 키마다 계획의 50 %를 넘으면 그 셀 키는 멈추고 "자료 부족"으로 둔다.

**설정 확인.** 시행마다 [cells.py](cells.py)의 `config_status`가 확인한다. 하나라도 어긋나면 제외가 아니라 그 hold의 나머지 셀을 멈춘다
(`STOP_config`).
- 모든 셀:
  - 버전: 2.32.3 설정은 `ver_r0 == "2.32.3"`, 다중 요청 복구 설정은 `"2.23.4"`.
  - 환경: `env_fo`, `env_rec`, `env_s2`가 그 설정의 값과 같다(예: `forec`는 `1/1`, `1/1`, `/`).
  - 단일 장치 경고: `fo`, `forec`는 두 rank 모두 `single_dev >= 1`, 나머지는 두 rank 모두 0.
  - 훅: 장애 없는 셀과 kill 셀에는 훅 줄이 없다. 주입 셀의 훅은 정한 rank에서만, 정한 종류(`send`, `recv`, `silent`)로 발사된다.
- INFO 셀(`sqp`, `rqp`, `slbc`, `slar`)만 더:
  - rank 1의 라이브러리: 2.32.3 설정은 두 rank 모두 `n232_mark >= 1`, 다중 요청 복구 설정은 0.
  - failover 문맥: `fo`, `forec`는 두 rank 모두 `res_init >= 1`, 나머지는 0.
  - recovery 스레드: `rec`, `forec`는 두 rank 모두 `prec_thread >= 1`, 나머지는 0. `forec`는 두 rank 모두 `prec_enabled >= 1`. `fo`는
    `prec_disabled_ctx >= 1`이고 `prec_enabled == 0`.
  - 다중 요청 복구 플래그: `s2on`은 두 rank 모두 `s2_on >= 1`, 나머지는 0.

**pilot에서 보이는 결함.** pilot은 태그 전이므로, 결함을 고친 뒤 고친 내용을 12절에 적고 예측을 다시 본다. 예:
- 2.32.3에서 훅이 정한 반복 수 안에 발사되지 않는다(multi-send나 수신 수가 2.23.4와 다름). 주입 번호나 반복 수를 바꾼다.
- 설정 확인 줄의 문구가 소스와 다르다. 열 정의를 고친다.
- kill 시점에 생존 rank의 반복이 아직 시작되지 않았다. `kill_at_s`를 바꾼다.

**중단 기준.**
- **잠금.** 모든 클러스터 명령은 `../../gpu-initiated/common/cluster_run.sh -w 10800` 안에서 돈다. 10 800 s 안에 잠금이나 유휴 링크를
  얻지 못하면(종료 코드 75) 그 hold를 미룬다. `prio-` 작업에는 양보한다. hold 하나는 15분 이하이고 `timeout -s KILL 880`으로 묶는다.
- **하지 않는 것.** 실제 link down이나 flap, 재부팅, 드라이버 재적재, 커널 모듈 적재, RoCE 주소 변경, iptables 같은 방화벽 변경, 시스템
  TCP 설정 변경. 장애는 우리 프로세스 안의 훅(QP 상태 변경)과 우리 rank 1 프로세스의 SIGKILL로만 만든다.
- **프로세스.** 우리가 띄운 프로세스만 PID로 끈다. rank 0은 실행기의 자식이다. rank 1은 `$HOME/nb-bundle/run/r1.pid`에 PID를 남기고,
  그 PID의 `/proc/<pid>/comm`이 `nb_ct`일 때만 끈다. `nb_ct`라는 이름은 이 실험만 쓴다. 다른 사용자의 작업(gds-kv, NVMe-oF, gdsio,
  mooncake, `prio-` 작업)은 건드리지 않는다. 시행 뒤 `nb_ct`가 남은 시행이 두 번 이어지면 멈춘다(`STOP_left`).
- **mlx5 오류.** hold 앞뒤에 두 노드의 mlx5 커널 줄 전체와 rain mlx5_1의 펌웨어 명령 계수를 남긴다. 새로 생긴 mlx5 줄은 수가 아니라
  내용을 12절과 `mlx5_new_<hold>.txt`에 적는다. 두 노드 dmesg에 새 mlx5 명령 오류 줄이 생기거나 rain의 명령 실패 계수가 늘면 그 hold
  뒤로 멈춘다(`STOP_mlx5`).
- **배포.** 새 번들은 새 디렉터리 `$HOME/nb-bundle/`에만 둔다. 그 디렉터리가 어느 노드에든 이미 있으면 배포 스크립트가 멈춘다. 배포
  전후로 기존 번들(`$HOME/gi-bundle`, sunny의 `$HOME/nccl-ct`)의 모든 파일 md5가 같은지 확인한다.

## 9. 실행 방법과 경로

**1. 주입 훅(`n232`).** [inject_232.diff](inject_232.diff), `src/transport/net_ib/p2p.cc` 한 파일. 다중 요청 복구 빌드와 같은 변수 이름과
발사 지점을 쓰고, 복구 코드는 없다. 변수가 모두 꺼져 있으면 v2.32.3-1과 같다 `[소스]`.
- `NCCL_RDMA_FAULT_INJECT=k`: 프로세스의 k번째 첫 multi-send 직전(`ncclIbIsend`에서 `ncclIbMultiSend` 앞), 그 송신 communicator의 데이터 QP를
  모두 ERR로.
- `NCCL_RDMA_FAULT_INJECT_RECV=k`: 프로세스의 k번째 수신 게시 직전(`ncclIbIrecv` 앞부분), 그 수신 communicator의 데이터 QP를 모두 ERR로.
- `NCCL_RDMA_FAULT_INJECT_RECV_SILENT=1`과 함께: 처음 수신을 완료한 수신 communicator에서, k번째 수신 완료부터 다른 수신이 하나 이상 걸려
  있을 때 그 communicator의 데이터 QP를 모두 ERR로. 상대에게 알리지 않는다(`ncclIbCompletionEventProcess`의 수신 완료 처리 뒤).
- 발사마다 WARN 한 줄 `NET/IB: [FAULT-INJECT] forced ...`, 끝에 `mono_ms`. 변수마다 프로세스당 한 번만 발사한다.
- 다중 요청 복구의 훅은 `qps[0]` 하나를 바꿨다. 이 훅은 그 communicator의 데이터 QP를 모두 바꾼다. 연결당 QP 기본값이 1이라 이 실험에서는 같다
  `[소스]`(`connect.cc` 62행).

**2. 빌드.** [build_nb.sh](build_nb.sh). 세션 스크래치 `agent_nb/`에서만 한다.
- `n232`: upstream v2.32.3-1 트리가 태그 + diff와 같은지 확인하고 전체 빌드(sm_75, sm_86).
- `s2`: 빌드 `9ed03e1d`를 복사한다. 이 저장소의 diff가 그 소스를 재현하는지 hash-object로 확인한다.
- `drv`: `../perf/nccl_ct.cu`를 2.23.4의 `nccl.h`로 컴파일해 `nb_ct`로 둔다. 한 바이너리를 두 라이브러리에 쓴다.
- 결과는 `agent_nb/out/`과 `out/MD5SUMS`.

**3. 실행기.** [nbrun.py](nbrun.py)가 시행 하나를 띄우고 끝낸다. [cells.py](cells.py)가 셀과 설정을 정의하고 시행마다 설정을 확인한다.
- rank 0은 rain에서 직접, rank 1은 sunny에서 ssh로 띄운다. 두 rank 모두 `$HOME/nb-bundle/<n232|s2>/`의 라이브러리와 `nb_ct`를 쓴다.
- 랑데부 주소는 hold가 rain eno1에서 읽는다. sunny의 ssh 대상은 hold의 `SUNNY_SSH` 줄이다.
- 끝내는 규칙: 드라이버의 반복 제한 12 s와 abort 감시 10 s, 한 rank가 0이 아닌 코드로 끝난 뒤 6 s 유예(kill한 rank는 빼고), 실행 상한.

**배포.** [deploy_nb.sh](deploy_nb.sh) `deploy_check.txt`. 8절의 확인을 파일로만 받는다. ssh와 scp만 쓰고 RDMA와 GPU는 쓰지 않는다.

**실행.** hold는 [hold.sh](hold.sh)에 두고, [chain.sh](chain.sh)가 hold마다 `cluster_run.sh -w 10800 -t nb-<hold>`에 넣는다. 결과
폴더는 `results/<날짜>/<설정>/`(pilot은 `results/<날짜>_pilot/`). 같은 hold 안에서는 셀 키를 한 번씩 번갈아 돈다.

| hold | 내용 | 시간 |
|---|---|---|
| P1 pilot | 송신, 수신 QP 셀 키 11개 각 1회, 장애 없는 셀 키 10개 각 1회 | `[측정]` 01:04:13–01:06:35(잠금 01:03:42) |
| P2 pilot | 조용한 장애 셀 키 8개, kill 셀 키 5개 각 1회 | `[측정]` 01:07:09–01:10:19(잠금 01:06:38) |
| H1, H2 | 장애 없는 셀 키 10개 × 5회씩(두 hold로 키마다 10회) | 각 4분 |
| H3, H4 | `sqp@off`, `sqp@fo`, `sqp@forec` × 5씩 | 각 3–4분 |
| H5 | `sqp@rec`, `sqp@s2on`, `sqp@s2off` × 5 | 4분 |
| H6, H7 | `rqp@off`, `rqp@fo`, `rqp@forec` × 5씩 | 각 3분 |
| H8 | `rqp@s2on`, `rqp@s2off`, `slbc@s2on`, `slar@s2on` × 5 | 5분 |
| H9, H10 | `slbc@off`, `slbc@fo`, `slbc@forec` × 5씩 | 각 3분 |
| H11, H12 | `slar@off`, `slar@fo`, `slar@forec` × 5씩 | 각 3–4분 |
| H13, H14 | `kill@off`, `kill@fo`, `kill@forec` × 5씩 | 각 6분 |
| H15 | `kill@s2on`, `kill@s2off` × 5 | 5분 |

본 실행 hold의 시간은 pilot의 셀별 실행 시간에 시행마다 약 1.9 s(실행기 시작, GID 읽기, 남은 프로세스 확인)와 hold마다 스냅숏 약 50 s를
더한 추정이다 `[추론]`. pilot의 시행 하나는 1.7–27.4 s였다(34회의 범위) `[측정]`. 본 실행 H1–H15는 시행과 스냅숏 약 57분, hold마다
유휴 링크 확인 약 31 s를 더해 약 65분이다(잠금을 기다리는 시간 제외) `[추론]`. 최악은 모든 시행이 실행 상한에 닿는 경우로, hold 하나에
장애 시행 20회 × 40 s = 800 s 또는 장애 없는 실행 50회 × 15 s = 750 s다. 거기에 시행마다의 준비 시간과 스냅숏이 붙어 880 s 상한에 닿을 수
있다. 그러면 `timeout`이 hold를 끝내고, 남은 셀은 `fill:`로 채운다.

**채점.** `python3 score.py results/<날짜>`. [rows_nb.py](rows_nb.py)가 3.1의 열을 만들고, [score.py](score.py)가 8절의 제외와 설정
확인을 거쳐 [predictions.csv](predictions.csv)의 판정식을 3.2 문법대로 적용한다. 결과는 `results/<날짜>/SCORE.md`와
`results/<날짜>/trials_scored.csv`다. pilot 폴더에는 쓰지 않는다(`score.py`가 거절한다).

**출력.** 시행 파일과 hold 출력은 커밋하지 않고 Release에 올린다. 커밋하는 것은 `SCORE.md`, `trials_scored.csv`, `deploy_check.txt`다.

## 10. 완료 조건과 QA 기준

- [x] 모든 셀 키가 계획한 반복 수만큼 판정됐다. 제외와 설정 확인 실패를 따로 센 표가 있다(제외 0, [SCORE.md](results/20261009/SCORE.md)).
- [x] 예측 27줄마다 판정(맞음, 틀림, 자료 부족)과 놓친 시행 목록이 있다.
- [x] 다른 에이전트가 `score.py`를 보지 않고 원시 로그에서 핵심 수치를 다시 셌다. 대상은 결과 분류, 앱 오류와 시각, 치명 판정과 복원력 동작
  줄, 다중 요청 복구의 복구 줄과 시간, 반복 시간 중앙값이다([qa_recount.md](results/20261009/qa_recount.md)).
- [x] 다른 에이전트가 `inject_232.diff`와 실행기를 읽고 리뷰했다([qa/code_review.md](qa/code_review.md)).
- [x] pilot과 제외 시행이 결과에 섞이지 않았다.
- [x] 새 빌드의 md5와 배포 확인을 5절과 12절에 적었다.
- [x] 원자료를 Release `data-20261009`에 올렸다. `DATA.md` 항목은 메인 세션이 상위 문서와 함께 묶는 PR에서 적는다(이 브랜치에는 없음).
- [x] hold 전후 mlx5 스냅숏에 새 명령 오류가 없었다. 새 커널 줄 하나(H13, FWTracer)의 내용을 12절에 적었다.

## 11. 작업 체크리스트

- [x] 질문, 가설, 셀 작성 (`DRAFT`)
- [x] 2.32.3 소스 읽기(복원력 경로와 그 호출자)
- [x] 주입 훅 작성, 빌드(`n232` 빌드됨), 다중 요청 복구 빌드와 드라이버 준비
- [x] `cells.py`, `nbrun.py`, `hold.sh`, `chain.sh`, `deploy_nb.sh`, `rows_nb.py`, `score.py`
- [x] 실행기와 채점기의 오프라인 시험(클러스터 없이, 12절)
- [x] 배포(메인 세션)
- [x] pilot P1, P2(메인 세션, 채점 제외)
- [x] pilot 검토, 하네스 고침, 예측과 반복 수 확정
- [x] 고정 절 확정, 상태 `PREREGISTERED`, 해시 기록을 커밋 하나로 만들고 그 커밋에 `prereg/` 태그
- [x] 본 실행 H1–H15 (`RUNNING`)
- [x] 채점 (`QA`)
- [x] 독립 재계산과 코드 리뷰
- [x] 결과 정리, 원자료 릴리스
- [x] PR: #54로 합쳤다. `DATA.md`와 상위 README는 뒤의 문서 PR에서 갱신했다
- [x] 결론 확정 (`COMPLETE`)

## 12. 실행 기록 (시간순)

| 시각 | 무엇을 했나 | 결과와 근거(경로, 커밋, 실행 ID) |
|---|---|---|
| 2026-10-09 00:15–00:30 | 세션 스크래치의 GIN 트리(`agent_ts2pc/nccl-src`, 고치지 않음)에서 pristine 커밋 `da7a73d`를 `agent_nb/nccl-232`로 복제. upstream 태그 v2.32.3-1(`12df1a11`)을 받아 비교: `src/`는 같고 `bindings/nccl4py/.git_archival.txt`만 다름 `[측정]`. `p2p_resiliency.cc`, `p2p_resiliency_recovery.cc`와 호출자(`p2p.cc`, `common.cc`, `connect.cc`, `init.cc`, `proxy.cc`, `ras/`)를 읽음 `[소스]` | 1절, `agent_nb/nccl-232` |
| 2026-10-09 00:30–00:50 | 다중 요청 복구의 결과 표와 Release `data-20261006` 원시 로그(stage2, perf)를 다시 셈 `[측정]` | 1절, 세션 스크래치 `agent_nb/x/`, `agent_nb/perf/` |
| 2026-10-09 00:32 | `build_nb.sh s2`: 이 저장소의 diff가 `net_ib.cc` hash-object `18d998a8`을 재현함 확인, `9ed03e1d` 복사. `build_nb.sh drv`: `nb_ct` md5 `523fd863` | `agent_nb/out/MD5SUMS` |
| 2026-10-09 00:36 | `build_nb.sh n232`: 트리 확인 뒤 전체 빌드, libnccl md5 `9269cc75`(빌드됨). 경고 1건은 upstream `symmetric_sched.cc`의 것 | `agent_nb/build_n232.log` |
| 2026-10-09 00:38–00:45 | `ldd -r`로 `nb_ct`가 두 라이브러리에서 해결 안 된 기호가 없음을 확인(정적) `[측정]`. upstream 태그 v2.29.3-1, v2.29.7-1, v2.30.3-1, v2.30.7-1, v2.31.2-1에서 변수와 GID 처리가 들어온 버전을 확인 `[소스]` | 1절 |
| 2026-10-09 00:45–00:55 | 채점기 오프라인 시험: 다중 요청 복구의 실제 원시 로그(A5, C6, C7, T12d)를 이 실험의 파일 이름으로 바꾸고, 2.32.3 셀은 소스의 메시지 문구로 만든 가짜 로그로 `score.py`를 끝까지 돌림. 조용한 훅의 종류를 못 읽는 정규식 오류를 찾아 고침. 이 시험은 측정이 아니다 | 세션 스크래치 `agent_nb/scoretest/` |
| 2026-10-09 00:47–00:49 | 실행기 오프라인 시험: 가짜 `nb_ct` 스크립트와 ssh 대신 로컬 bash로 정상 종료, 한 rank 오류 뒤 유예, 실행 상한, rank 1 kill을 돌림. 끝까지 읽지 못한 로그가 비지 않도록 시행 끝에서 로그를 비우게 고침 | 세션 스크래치 `agent_nb/mock/` |
| 2026-10-09 00:48 | 실수: 위 모의 시험의 남은 `sleep` 자식을 지우려고 `pkill -x sleep -u <내 사용자>`를 한 번 실행했다. 이 명령은 이 사용자의 다른 `sleep`도 끌 수 있다. 그때 `cluster_run.sh` 잠금 아래 도는 작업은 없었다(`cluster_run.log` 마지막 줄 00:37:36 종료). 다른 셸(00:45:52 시작)의 180 s 대기가 00:48:52에 끝났는데, 그 대기가 이 명령으로 최대 약 1 s 일찍 끝났을 수 있다 `[미확인]`. 남은 모의 `sleep` 세 개는 PID로 껐다. 이후 이런 명령은 쓰지 않는다 | 이 행 |
| 2026-10-09 00:58 | 훅 diff와 빌드 스크립트, 실행기와 채점기를 커밋 | 브랜치 `exp/nccl-builtin`의 `96ef1b23`, `0bc2641b`(rebase 전 해시) |
| 2026-10-09 01:00 | 1–12절 초안, 예측 26줄. 상태 `DRAFT`. 그때까지 클러스터에서는 아무것도 돌리지 않았다(ssh, 배포, `cluster_run.sh`, GPU나 RDMA 프로그램 실행 모두 없음) | `1cbc2c0b`(rebase 전 해시) |
| 2026-10-09 01:02:37–01:03:28 | 메인 세션이 배포(`deploy_nb.sh`, rc 0). 두 노드의 배포 파일 md5가 소스와 같고, `ldd`가 두 노드 두 번들 모두 번들 안의 libnccl을 가리킨다. 기존 번들(rain 272개, sunny 332개 파일)의 md5가 배포 전후 같다 `[측정]` | [deploy_check.txt](deploy_check.txt) |
| 2026-10-09 01:03:42–01:10:21 | 메인 세션이 pilot을 돌림: `chain.sh results/20261009_pilot P1 P2`. P1은 잠금 01:03:42, 실행 01:04:13–01:06:35(21회). P2는 잠금 01:06:38, 실행 01:07:09–01:10:19(13회). 두 hold rc 0. 34회 모두 설정 확인을 통과하고 8절의 제외에 걸린 시행이 없다. 남은 `nb_ct` 0. mlx5: 새 커널 줄 0, 명령 오류 줄 rain 2, sunny 0, rain 펌웨어 명령 실패 수 31로 전후가 같다. 두 노드에 다른 GPU 사용자 없음 `[측정]`. 채점하지 않는다 | `results/20261009_pilot/`(원시 파일은 커밋하지 않음), `hold_P1.out`, `hold_P2.out`, `mlx5_new_P1.txt`, `mlx5_new_P2.txt` |
| 2026-10-09 01:12–01:26 | pilot 검토(아래 "pilot 검토"). 처음에는 끝 시각을 01:30으로 적었다. 이 일의 커밋이 01:26:08이고 사전 등록 커밋이 01:27:17이라 01:26으로 고쳤다(13절). `rows_nb.py`를 다시 돌려 34회의 줄을 셀마다 원시 로그와 대조함. 하네스 고침과 예측, 반복 수 확정(아래 "pilot 뒤 바꾼 것") | [results/20261009_pilot/trials_pilot.csv](results/20261009_pilot/trials_pilot.csv)(`rows_nb.py`가 만든 34줄, 채점 상태 없음), 세션 스크래치 `agent_nb/pilot_check.py`, 이 커밋 |
| 2026-10-09 01:27:17 | 사전 등록 | [PREREG.txt](PREREG.txt), 태그 `prereg/nccl-builtin-v1` |
| 2026-10-09 01:27:33 | 메인 세션이 본 실행을 걸어 둠: `chain.sh results/20261009 H1 … H15`. 잠금은 다른 사용자의 작업이 03:15:20까지 쥐고 있었다. 그 뒤 hold들은 다른 실험 세 개와 번갈아 잠금을 얻었다 | `results/20261009/chain.out`, 세션 스크래치 `cluster_run.log`(태그 `nb-H1`–`nb-H15`) |
| 2026-10-09 03:20:56–03:24:28 | H1(잠금 03:20:56, 실행 03:21:27–03:24:28): 장애 없는 실행 50회. 본 실행 첫 시행 03:21:30, 상태 `RUNNING`(태그 뒤 상태만 바꾸는 커밋은 만들지 않았다) | `hold_H1.out` |
| 2026-10-09 03:31:02–03:34:35 | H2(실행 03:31:33–03:34:35): 장애 없는 실행 50회 | `hold_H2.out` |
| 2026-10-09 03:34:35–03:37:36 | H3(실행 03:35:06–03:37:36): 송신 QP 오류, `off`, `fo`, `forec` 15회 | `hold_H3.out` |
| 2026-10-09 03:37:36–03:40:38 | H4(실행 03:38:07–03:40:38): 같은 셀 15회 | `hold_H4.out` |
| 2026-10-09 03:40:38–03:43:54 | H5(실행 03:41:09–03:43:54): 송신 QP 오류, `rec`, `s2on`, `s2off` 15회 | `hold_H5.out` |
| 2026-10-09 03:56:48–03:59:11 | H6(실행 03:57:19–03:59:11): 수신 QP 오류, `off`, `fo`, `forec` 15회 | `hold_H6.out` |
| 2026-10-09 04:11:30–04:13:52 | H7(실행 04:12:01–04:13:52): 같은 셀 15회 | `hold_H7.out` |
| 2026-10-09 04:29:29–04:34:07 | H8(실행 04:30:00–04:34:07): 수신 QP 오류 `s2on`, `s2off`, 조용한 방송과 all-reduce `s2on` 20회 | `hold_H8.out` |
| 2026-10-09 04:52:53–04:55:34 | H9(실행 04:53:24–04:55:34): 조용한 방송, `off`, `fo`, `forec` 15회 | `hold_H9.out` |
| 2026-10-09 05:13:40–05:16:18 | H10(실행 05:14:11–05:16:18): 같은 셀 15회 | `hold_H10.out` |
| 2026-10-09 05:31:36–05:34:35 | H11(실행 05:32:07–05:34:35): 조용한 all-reduce, `off`, `fo`, `forec` 15회 | `hold_H11.out` |
| 2026-10-09 05:48:50–05:51:49 | H12(실행 05:49:21–05:51:49): 같은 셀 15회 | `hold_H12.out` |
| 2026-10-09 06:02:56–06:08:26 | H13(실행 06:03:27–06:08:26): 상대 kill, `off`, `fo`, `forec` 15회. 새 mlx5 커널 줄 하나(8절에 따라 내용을 적는다): sunny `mlx5_core 0000:17:00.0: mlx5_fw_tracer_handle_traces:808:(pid 1828991): FWTracer: Events were lost`. 펌웨어 추적 기록이 넘친 것으로, 명령 오류 줄(`cmd`, `command`)이 아니다. 명령 오류 줄 수와 rain 명령 실패 수는 전후가 같아 멈추지 않았다 `[측정]` | `hold_H13.out`, `mlx5_new_H13.txt` |
| 2026-10-09 06:11:48–06:17:18 | H14(실행 06:12:19–06:17:18): 같은 셀 15회 | `hold_H14.out` |
| 2026-10-09 06:17:58–06:22:25 | H15(실행 06:18:29–06:22:25): 상대 kill, `s2on`, `s2off` 10회. 본 실행 끝 | `hold_H15.out` |
| 2026-10-09 03:20:56–06:22:25 | 본 실행 전체 `[측정]`: 15 hold 모두 rc 0, `STOP_*` 파일 없음. 시행 295회(장애 195, 장애 없음 100), 시작 실패, 설정 확인 실패, 실행 상한 도달, 남은 `nb_ct` 모두 0. hold 스냅숏 30개에서 두 노드 번들 md5가 배포 때와 같고, 포트 상태가 5절과 같고, 다른 GPU 사용자가 없다. mlx5 명령 오류 줄(rain 2, sunny 0)과 rain 펌웨어 명령 실패 수(31)는 30개 모두 같다. 새 커널 줄은 H13의 한 줄뿐이다. hold 하나는 잠금부터 끝까지 2:22–5:30분, 15개 합 52.5분이었다(9절 추정 약 65분). 03:20–06:22의 나머지는 잠금 대기다 | `results/20261009/`, 세션 스크래치 `cluster_run.log` |
| 2026-10-09 06:22:32 | `score.py results/20261009`: 295회 모두 판정, 따로 셈 0. 예측 27줄 중 26줄 맞음, 1줄 틀림(O4). 예측 파일 sha256이 `PREREG.txt`와 같다. 상태 `QA` | [SCORE.md](results/20261009/SCORE.md), [trials_scored.csv](results/20261009/trials_scored.csv) |
| 2026-10-09 06:23:50 | 메인 세션이 원자료를 Release `data-20261009`에 올리고 내려받아 확인함: `sha256sum -c` 통과, 원본과 주소 치환 말고는 같음, 실제 주소 앞부분 없음. 본 실행 `harness__nccl-integration__builtin__results__20261009.tar.xz`(1 039개 파일, 1.04 MB, sha256 앞 12자 `5e331f890677`), pilot `harness__nccl-integration__builtin__results__20261009_pilot.tar.xz`(125개 파일, 0.13 MB, `618c9cc3eb41`, 채점 안 함). `DATA.md`는 메인 세션이 상위 문서와 함께 묶는 PR에서 고친다 | Release `data-20261009` |
| 2026-10-09 06:39 | 다른 에이전트가 `score.py`, `rows_nb.py`, 채점 결과를 보지 않고 원시 파일에서 독립 재계산. 판정이 같다(26 맞음, 1 틀림, 자료 부족 0). 제외 0을 확인. 문서와 다른 점 7가지(16절) | [qa_recount.md](results/20261009/qa_recount.md), [qa/recount.py](qa/recount.py) |
| 2026-10-09 06:42 | 다른 에이전트가 훅, 실행기, 파서, 채점기를 리뷰. 막는 결함과 큰 결함 없음, 판정을 바꾸는 것 없음. 중간 3개(M1–M3), 작은 것 5개(L1–L5), 사소한 것 7개(N1–N7) | [qa/code_review.md](qa/code_review.md) |
| 2026-10-09 06:45–06:50 | 13–19절, README를 씀. 15절의 셀별 범위를 `trials_scored.csv`에서 다시 세어 독립 재계산의 값과 같음을 확인 `[측정]`. 상태 `COMPLETE` | 이 커밋 |

**pilot 검토** (2026-10-09, 34회, 채점하지 않음). 수치는 시행 하나씩이다. 시각은 실행기의 수신 시각이다 `[측정]`.
- **훅 위치.** 모든 주입 셀에서 정한 rank의 훅이 정한 종류로 한 번 발사됐다.
  - 송신, 수신 QP 훅은 두 라이브러리 모두 301번째에서 발사됐고 그 rank의 반복 18(150회 중)에서 멈췄다.
  - 2.32.3의 조용한 훅: 방송은 수신 완료 301번째(걸린 수신 4–6개), 반복 2. all-reduce는 403번째(걸린 수신 1개), 반복 100–101.
  - 다중 요청 복구의 조용한 훅은 communicator 준비 뒤 64–69 ms에 발사됐다.
  - 모두 검사하는 반복 안이다.
  - kill은 rank 0을 띄우고 5.0 s 뒤 요청했고, ssh 명령은 246–250 ms에 돌아왔다(5회). 그때 생존 rank는 41 658–44 641회를 마쳤다.
- **파서.** 두 라이브러리의 WARN 줄 종류를 모두 모아 보았다. 3.1의 정규식이 읽는 줄 밖에는 예상하지 못한 경고(비동기 이벤트, RAS)가 없었다.
  - 상태 번호는 2.32.3 원본 줄(`IBV_WC_WR_FLUSH_ERR(5)`, `IBV_WC_RETRY_EXC_ERR(12)`), 2.32.3 복원력 INFO 줄, 2.23.4 원본 줄, 다중 요청
    복구 줄에서 모두 읽혔다.
  - 버전 줄, 단일 장치 경고(`fo`, `forec` 14회 모두 두 rank. 기본 설정은 rank마다 4줄, 1채널은 2줄), 복원력과 recovery 설정 줄이 설정대로
    나왔다.
- **2.32.3**(`off`, `rec`, `fo`, `forec`, 21회). 소스 예측과 모두 맞았다.
  - 송신 QP: rank 0이 훅 뒤 0.036–0.199 ms에 ncclRemoteError를 받았다(4회). `off`와 `rec`은 원본 오류 CQE 줄과 WR_FLUSH_ERR(5)를 남겼다.
    `fo`와 `forec`은 그 줄 없이 치명 판정 줄을 남겼다. rank 1은 오류를 받지 못하고 실행기의 유예 뒤에 끝났다.
  - 수신 QP: rank 1이 0.027–0.047 ms에 ncclRemoteError를 받았다(3회). rank 0은 3 593–3 667 ms 뒤 RETRY_EXC(12)로 오류를 받았다.
  - 조용한 수신 QP: rank 1 자신이 0.033–0.159 ms에 오류를 받았다(6회). 방송에서는 rank 0도 3 591–3 684 ms 뒤 RETRY_EXC를 받았다.
    all-reduce에서는 rank 0이 오류 없이 유예 뒤에 끝났다.
  - kill: 생존 rank가 kill 요청 뒤 12 243–12 250 ms에 TIMEOUT으로 끝났고 오류는 없었다(3회).
  - 복원력 동작 줄(장치 실패 표시, QP 교체, 확인 읽기, port recovery)은 21회 모두 0이다.
  - `ncclCommAbort`는 2.32.3에서 부른 rank 로그 22개 모두 SUMMARY 뒤 524–553 ms에 돌아왔다. 2.23.4에서는 7개 모두 감시 시간에 끝났다.
- **다중 요청 복구**(10회). 아래 한 셀을 빼고 소스 예측과 맞았다.
  - 켬: 송신, 수신 QP 모두 투명하게 복구했다(복구 시간 2.762 ms, 2.581 ms).
  - 켬, 조용한 방송: rank 1은 알리지 않고 비웠다. rank 0은 훅 뒤 3 591 ms에 RETRY_EXC를 받아 2.116 ms에 복구했고 투명했다.
  - 켬, 조용한 all-reduce: 두 rank가 0.3 ms 차이로 TIMEOUT으로 끝났다.
  - 켬, kill: FIN으로 kill 요청 뒤 295 ms(ssh 명령이 돌아온 뒤 49 ms)에 오류를 받았다.
  - 끔, 송신 QP: rank 0이 0.076 ms에 오류를 받았다.
  - 끔, kill: TIMEOUT으로 끝났다.
- **예측과 어긋난 셀: `rqp@s2off`**(다중 요청 복구 끔, 수신 QP 오류).
  - rank 1은 훅 뒤 0.024 ms에 ncclRemoteError를 받았다(S7의 내용은 맞음).
  - 그런데 rank 0은 오류 없이 반복 18을 마쳤고, 결과 버퍼 4 194 304개 중 524 288개가 틀렸다(첫 위치 3 670 016, 받은 값 2741, 맞는 값
    2485). 이 MISMATCH 줄은 훅 뒤 633 ms에 왔다.
  - 그 뒤 rank 0은 훅 뒤 3.6 s에 RETRY_EXC 경고를 남겼고, 두 rank의 abort는 돌아오지 않았다.
  - 처음 예측(S7의 `outcome == "ERROR"`, I1의 "MISMATCH 없음")은 2.23.4의 오류 뒤 동작을 읽지 않고 세운 것이었다. 소스를 다시 읽어 1절
    8번으로 설명했다 `[소스, 추론]`. 2.23.4의 진행 스레드는 오류 뒤에도 돈다. rank 1이 abort하면 그 커널이 받지 못한 데이터를 기다리지
    않고 넘어간다. 그래서 rank 1의 멀쩡한 송신 연결로 덜 만든 데이터가 rank 0에 간다. 2.32.3의 같은 셀 3회는 rank 0이 3.6 s 뒤 RETRY_EXC
    오류로 끝났고 틀린 결과가 없었다. 2.32.3의 진행 스레드가 첫 오류에서 멈추는 것과 맞는다.
  - 이 설명은 소스와 시행 하나에서 이끈 것이다. 틀린 값이 rank 1의 어느 버퍼에서 왔는지는 확인하지 않았다 `[미확인]`.
- **장애 없는 실행**(실행 하나씩). 실행 순서는 `off`, `fo`, `forec`, `s2on`, `s2off`였다.
  - 64 KiB: 0.0551, 0.0556, 0.0578, 0.0510, 0.0515 ms.
  - 16 MiB: 3.0846, 3.1033, 3.2505, 3.2934, 3.2314 ms.
  - `forec`가 `fo`보다 4.0 %(64 KiB), 4.7 %(16 MiB) 느려 O3의 2 %를 넘었다. 소스에서는 두 설정의 데이터 경로 차이를 찾지 못했다
    (1절 2번, 3.3의 O3 근거) `[소스]`. 16 MiB 값은 실행 순서를 따라 대체로 커졌다. 실행 하나로는 흐름과 효과를 가를 수 없다 `[추론]`.
    O3는 그대로 두고 이 의문을 적는다.
- **기타.** 다중 요청 복구의 복구 시간(2.762, 2.581 ms)은 S2의 범위(1.8–3.0 ms) 안이다. 다만 WARN 수준이던 최종 빌드의 2.152–2.400 ms보다
  위쪽이다. 이 셀은 INFO로 돈다. S2는 그대로 둔다.

**pilot 뒤 바꾼 것**(태그 전, 2026-10-09).

| 무엇을 | 근거가 된 pilot 관측 | 바꾸지 않은 것 |
|---|---|---|
| 1절 8번, 2절 H7과 질문 6, 예측 S9(`rqp@s2off`: rank 1의 오류 뒤 rank 0이 오류 없이 틀린 결과로 마침) 추가 | `rqp@s2off`의 MISMATCH. 2.23.4의 `proxy.cc` 894–899행과 `prims_simple.h` 128–133행을 다시 읽음 | S9의 기준(≥4/5)은 시행 하나에 맞추지 않고, 소스로 정해지는 순서(rank 1의 오류가 먼저)를 담았다 |
| S7: `outcome == "ERROR"` 조건을 뺐다 | 같은 시행. 결과 분류는 MISMATCH를 먼저 매기므로, rank 1의 오류(S7의 내용)와 rank 0의 결과(S9)를 나누었다 | rank 1의 1 s 안 오류, 상태 5, 복구 없음, ≥4/5 |
| I1: `rqp@s2off`와 `slar@s2on`을 셀에서 뺐다(34개에서 32개로) | `rqp@s2off`는 S9로 옮겼다. `slar@s2on`은 같은 abort 경로가 TIMEOUT 뒤에 열릴 수 있어(rank 1이 먼저 시간 초과하면) S5와 결과 분류에 맡겼다. pilot의 `slar@s2on`에는 틀린 결과가 없었다 | 나머지 32개 셀의 "MISMATCH 0" |
| 3.1 `outcome`: TIMEOUT 뒤의 MISMATCH는 결과 분류에 넣지 않는다(`mism_pre_to`). 열 `mism_r<r>`, `dt_mism_r<r>`, `kill_rtt_ms` 추가([rows_nb.py](rows_nb.py)) | 드라이버는 TIMEOUT 뒤 abort하므로 하네스의 끝내는 방식이 틀린 결과를 만들 수 있다. S5의 기준 글은 그대로 두고 근거에 이 정의를 적었다 | 다른 열의 정의 |
| 반복 수: 2.32.3의 새 장애 셀을 모두 10회로(`fo`, `forec`의 송신, 수신 QP는 원래 10회), 장애 없는 셀을 10회로. 기준을 B1–B4, F3, F4는 ≥4/5에서 ≥9/10으로, O5는 5/5에서 10/10으로 맞췄다([score.py](score.py)의 `PLANNED`, [hold.sh](hold.sh)의 H1–H15) | pilot 34회의 두 hold는 실행 5.5분, 잠금과 유휴 확인을 넣어 6.7분이었다(추정 약 12분). 늘린 본 실행이 약 65분으로 1.5시간 안이다. 장애 없는 실행은 실행 하나의 차이가 4.7 %까지 나서, 키마다 실행을 늘려 중앙값의 잡음을 줄인다 | 기준을 늦춘 예측은 없다. 대조와 재현 셀(`rec`, `s2on`, `s2off`)은 5회 그대로 |
| 5절: sunny의 커널과 포트, 배포 확인 | hold 스냅숏, `deploy_check.txt` | |
| 그대로 둔 예측: O3 | `forec`가 `fo`보다 4.0 %, 4.7 % 느림(실행 하나) | 소스로 설명하지 못해 그대로 두고 의문을 위에 적었다 |
| 2026-10-09 | 용어: 본문의 "통신기"를 "communicator"로 바꿈(사용자 요청). 고정 절(2, 3, 7, 8절)과 `predictions.csv`, 채점기가 만든 `SCORE.md`는 그대로 둠 | 이 PR |

## 13. 사전 등록 이후 변경

태그 `prereg/nccl-builtin-v1`(`0ca10eb7`) 뒤의 변경과 바로잡기다. 고정 절(2, 3, 7, 8절)의 문장은 고치지 않고 여기에 덧붙인다. 독립 재계산은
2, 3, 7, 8절이 태그와 바이트까지 같음을 확인했다(16절). 가설, 예측, 판정식, 셀, 반복 수, 제외 기준은 바뀌지 않았다.

| 날짜 | 무엇을 | 이유 | 영향 범위 | 커밋 |
|---|---|---|---|---|
| 2026-10-09 | 12절 pilot 검토 행의 끝 시각을 01:30에서 01:26으로 고쳤다 | 그 일의 커밋이 01:26:08, 사전 등록 커밋이 01:27:17이다 | 기록만 | 이 커밋 |
| 2026-10-09 | 13절 머리말 "아직 사전 등록 전이다"를 이 문단으로 바꿨다 | 태그 뒤라 맞지 않는다(코드 리뷰 N7) | 기록만 | 이 커밋 |
| 2026-10-09 | 상태를 `RUNNING`(03:21), `QA`(06:22)로 바꾼 것은 커밋 없이 12절의 시각으로만 남겼고, 이 커밋에서 `COMPLETE`로 바꿨다 | 본 실행 중 이 브랜치에는 커밋이 없었다 | 기록만 | 이 커밋 |
| 2026-10-09 | 3.4절의 pilot 문장 "2.23.4로 부른 7개는 모두 감시 시간에 끝났다"에 덧붙임: 본 실행에서 2.23.4로 abort를 부른 rank 로그 40개 중 35개가 감시 시간(10 s)에 끝났다. 5개(`sqp@s2off`의 rank 1)는 abort 중에 실행기의 6 s 유예로 끝났다. 돌아온 것은 0이다 `[측정]` | 독립 재계산 3번 | 탐색 관찰만 | 이 커밋 |
| 2026-10-09 | 12절 pilot 검토의 "방송에서는 rank 0도 3 591–3 684 ms 뒤 RETRY_EXC를 받았다"(pilot 3회)에 덧붙임: 본 실행에서는 `slbc@off` 10/10에서만 그렇다. `slbc@fo` 1/10, `slbc@forec` 4/10이고, 나머지 15회는 rank 0이 오류 CQE 없이 유예로 끝났다. 훅이 발사될 때 걸린 수신 수가 `off` 3, `fo`, `forec` 2였다. 원인은 `[미확인]`이다 | 독립 재계산 2번, 코드 리뷰 M2 | 탐색 관찰만. 판정식은 rank 1과 결과 분류만 본다 | 이 커밋 |
| 2026-10-09 | 3.3절 O4의 근거("+1.27 %, −0.22 %(3회씩)")에 덧붙임: 그 측정(`../perf/completion_time.py`, 빌드 `3b0b760d`)은 다른 방식이었다. `--check last --quiet`, 64 KiB 400회, 16 MiB 25회, warmup 20이다(그 원시 로그의 SUMMARY `iters`로 확인) `[측정]`. 이 실험은 `--check every`이고, 반복마다 `IT` 줄을 내고, 2 000회와 200회, 빌드 `9ed03e1d`다 | 코드 리뷰 M1 | O4의 해석만. 판정은 고정한 대로 틀림 | 이 커밋 |
| 2026-10-09 | 3.1절 `s2_rec_ms`의 "첫 송신 communicator 복구 줄"은 시각 순이 아니라 rank 순(rank 0 먼저)의 첫 줄로 구현됐다 | 코드 리뷰 N3 | 없음. 복구한 시행 15회 모두 송신 communicator 복구 줄이 하나다 `[측정]` | 이 커밋 |
| 2026-10-09 | 3.1절 `outcome`은 TIMEOUT 뒤의 오류 줄에도 ERROR를 HANG보다 먼저 매긴다. TIMEOUT 뒤의 MISMATCH를 빼는 규칙과 짝이 맞지 않는다 | 코드 리뷰 N4 | 없음. 295회 중 TIMEOUT 뒤에 오류나 MISMATCH 줄이 있는 시행은 0이다 `[측정]` | 이 커밋 |
| 2026-10-09 | 8절의 "채운 시행이 계획의 50 %를 넘으면 그 셀 키를 멈춤"은 코드에 없다. meta 파일이 없는 시행은 `rows_nb.py`에 보이지 않는다 | 코드 리뷰 L3 | 없음. 제외, 채움, meta 없는 시행 모두 0이다(로그 590개 = meta 295개 × 2) `[측정]` | 이 커밋 |

## 14. 원자료와 결과표

| 무엇 | 경로 또는 Release 자산 | n |
|---|---|--:|
| 채점 결과(예측별 판정, 놓친 시행, 셀별 시행 수와 따로 센 시행) | [results/20261009/SCORE.md](results/20261009/SCORE.md) | 예측 27줄 |
| 시행별 표(3.1의 열, 상태) | [results/20261009/trials_scored.csv](results/20261009/trials_scored.csv) | 시행 295(판정 295, 따로 셈 0) |
| 독립 재계산 | [results/20261009/qa_recount.md](results/20261009/qa_recount.md), [qa/recount.py](qa/recount.py) | 시행 295 |
| 코드 리뷰 | [qa/code_review.md](qa/code_review.md) | |
| 본 실행 원시 파일(시행 로그, meta, hold 출력, 스냅숏, mlx5 줄) | Release `data-20261009`의 `harness__nccl-integration__builtin__results__20261009.tar.xz`(1 039개 파일, sha256 앞 12자 `5e331f890677`) | 시행 295, hold 15 |
| pilot 시행별 표(채점 안 함) | [results/20261009_pilot/trials_pilot.csv](results/20261009_pilot/trials_pilot.csv) | 시행 34 |
| pilot 원시 파일(채점 안 함) | Release `data-20261009`의 `harness__nccl-integration__builtin__results__20261009_pilot.tar.xz`(125개 파일, `618c9cc3eb41`) | 시행 34, hold 2 |
| 배포 확인 | [deploy_check.txt](deploy_check.txt) | |
| 사전 등록 | 태그 `prereg/nccl-builtin-v1`(`0ca10eb7`), [PREREG.txt](PREREG.txt), [predictions.csv](predictions.csv) | 예측 27줄 |

시행 파일(`*_r0.log`, `*_r1.log`, `*_meta.txt`)과 hold 출력은 커밋하지 않는다. 커밋한 것은 위의 `.md`와 `.csv`뿐이다.

## 15. 결과 요약

**채점** `[측정]`. 2026-10-09 06:22:32에 `score.py`가 사전 등록한 판정식을 그대로 적용했다([SCORE.md](results/20261009/SCORE.md)). 본 실행
295회(장애 195, 장애 없음 100)를 모두 판정했고 8절로 따로 센 시행은 없다. pilot 34회는 채점하지 않았다. 예측 파일 sha256은 `PREREG.txt`와
같다. **예측 27줄 중 26줄이 맞았고 1줄이 틀렸다**(다중 요청 복구의 64 KiB 비용, O4). 독립 재계산도 같은 판정이다(16절).

| 예측 | id | 셀 | n | 맞은 시행 | 판정 |
|---|---|---|--:|---|---|
| 복원력 없는 2.32.3: 송신 QP 오류가 rank 0에서 1 s 안에 ncclRemoteError, 원본 오류 줄과 WR_FLUSH_ERR | B1 | `sqp@off` | 10 | 10/10 | 맞음 |
| 수신 QP 오류가 rank 1 자신에게서 1 s 안에 ncclRemoteError | B2 | `rqp@off` | 10 | 10/10 | 맞음 |
| 받는 중 상대가 죽으면 생존 rank는 12 s 반복 제한까지 오류를 보지 못함 | B3 | `kill@off` | 10 | 10/10 | 맞음 |
| "조용한" 수신 QP 오류도 rank 1 자신이 1 s 안에 오류로 올림 | B4 | `slbc@off`, `slar@off` | 셀마다 10 | 셀마다 10/10 | 맞음 |
| port recovery 변수만 켜면 복원력 없는 것과 같음 | R1 | `sqp@rec` | 5 | 5/5 | 맞음 |
| failover(와 recovery): 송신 QP 오류를 곧바로 치명으로 판정, 1 s 안 ncclRemoteError, 복구 동작 없음 | F1 | `sqp@fo`, `sqp@forec` | 셀마다 10 | 셀마다 10/10 | 맞음 |
| 같은 판정이 수신 QP 오류의 rank 1에서 | F2 | `rqp@fo`, `rqp@forec` | 셀마다 10 | 셀마다 10/10 | 맞음 |
| failover(와 recovery)도 상대의 죽음을 보지 못함 | F3 | `kill@fo`, `kill@forec` | 셀마다 10 | 셀마다 10/10 | 맞음 |
| 조용한 오류를 rank 1 자신이 치명으로 판정해 1 s 안에 올림 | F4 | 조용한 장애 셀 4개(`fo`, `forec`) | 셀마다 10 | 셀마다 10/10 | 맞음 |
| failover를 켠 모든 시행에서 두 rank가 "넘겨 갈 다른 장치가 없다"고 경고 | F5 | failover 셀 14개 | 셀마다 10 | 예외 0 | 맞음 |
| 2.32.3의 어느 설정도 어느 장애도 투명하게 만들지 못함 | F6 | 2.32.3 장애 셀 16개 | 10(`sqp@rec` 5) | 투명 0 | 맞음 |
| 장치 실패 표시, QP 교체, 확인 읽기, port recovery가 시작되지 않음 | F7 | 2.32.3 장애 셀 16개 | 10(`sqp@rec` 5) | 동작 줄 0 | 맞음 |
| 다중 요청 복구(켬)가 송신, 수신 QP 오류를 투명하게 복구 | S1 | `sqp@s2on`, `rqp@s2on` | 셀마다 5 | 셀마다 5/5 | 맞음 |
| 그 복구 시간 중앙값이 1.8–3.0 ms | S2 | 같음 | 셀마다 5 | 2.306, 2.233 ms | 맞음 |
| 다중 요청 복구(켬)는 상대의 죽음을 FIN으로 알아 1 s 안에 생존 rank에 오류를 올림 | S3 | `kill@s2on` | 5 | 5/5 | 맞음 |
| 조용한 방송 오류를 rank 1에서 조용히 두고, 작업은 투명 복구 또는 멈춤 | S4 | `slbc@s2on` | 5 | 5/5 | 맞음 |
| 조용한 all-reduce 오류는 12 s 반복 제한까지 멈춤 | S5 | `slar@s2on` | 5 | 5/5 | 맞음 |
| 다중 요청 복구 끔: 송신 QP 오류가 1 s 안 ncclRemoteError | S6 | `sqp@s2off` | 5 | 5/5 | 맞음 |
| 다중 요청 복구 끔: 수신 QP 오류가 rank 1에서 1 s 안 ncclRemoteError | S7 | `rqp@s2off` | 5 | 5/5 | 맞음 |
| 다중 요청 복구 끔: 생존 rank는 12 s 반복 제한까지 오류를 보지 못함 | S8 | `kill@s2off` | 5 | 5/5 | 맞음 |
| 다중 요청 복구 끔: rank 1의 오류 뒤 rank 0이 장애 난 all-reduce를 오류 없이 틀린 결과로 마침 | S9 | `rqp@s2off` | 5 | 5/5 | 맞음 |
| 나머지 32개 셀에 틀린 결과 없음 | I1 | 32개 셀 | 10 또는 5 | MISMATCH 0 | 맞음 |
| 장애 없는 16 MiB: failover의 차이 2 % 이하 | O1 | `ovh16m` `fo` 대 `off` | 실행 10 / 10 | −0.15 % | 맞음 |
| 장애 없는 64 KiB: failover의 차이 5 % 이하 | O2 | `ovh64k` `fo` 대 `off` | 실행 10 / 10 | +1.73 % | 맞음 |
| recovery를 더한 차이 두 크기 모두 2 % 이하 | O3 | `forec` 대 `fo` | 실행 10씩 | −0.07 %(16 MiB), −1.70 %(64 KiB) | 맞음 |
| 다중 요청 복구 켬 대 끔: 16 MiB 2 %, 64 KiB 3 % 이하 | O4 | `s2on` 대 `s2off` | 실행 10씩 | +0.13 %, **+3.75 %** | **틀림** |
| 장애 없는 실행은 모두 투명 | O5 | 장애 없는 셀 10개 | 셀마다 10 | 셀마다 10/10 | 맞음 |

**수치를 센 방법.** 아래 범위는 `trials_scored.csv`(`score.py`의 열)에서 셌고, 독립 재계산(`qa/recount.py`, 원시 로그에서 따로 파싱)과 셀
키마다 같다 `[측정]`. 범위는 따로 적지 않으면 **한 셀 키의 판정한 시행에 걸친 최솟값–최댓값**이다. 시각은 실행기가 줄을 받은 시각(rain의
CLOCK_MONOTONIC)으로, 장애 시각(훅 줄을 받은 시각, kill 셀은 kill을 요청한 시각)부터 잰 ms다. 1 ms보다 짧은 값에는 파이프와 ssh 지연이
들어 있다. 훅 줄은 훅 자신의 시계보다 0.270–0.321 ms 늦게 도착했다(rank 0, 35회). rank 1의 줄은 ssh로 오고, kill 요청 시각은 235–261 ms
걸린 ssh 왕복 앞이다(코드 리뷰 L2). 그래서 1 ms보다 짧은 값을 설정끼리나 라이브러리끼리 비교하지 않는다.

**1. 송신 QP 오류**(`sqp`, rank 0) `[측정]`.
- 2.32.3: rank 0이 ncclRemoteError를 받은 시각은 `off` 0.041–0.103 ms(n=10), `rec` 0.050–0.091 ms(n=5), `fo` 0.030–0.094 ms(n=10),
  `forec` 0.051–0.091 ms(n=10)이다.
  - `off`, `rec`는 원본 오류 줄과 상태 5(WR_FLUSH_ERR)를 남겼다.
  - `fo`, `forec`는 원본 오류 줄 없이 "The error is fatal (No functional devices left)"를 남겼다.
  - rank 1은 35/35 오류 없이 실행기의 유예로 끝났다.
- 다중 요청 복구 켬: 5/5 투명. 송신 communicator 복구 2.270–2.482 ms(중앙값 2.306).
- 끔: rank 0이 0.047–0.096 ms에 오류를 받았다(n=5). rank 1은 11 998.6–11 998.7 ms에 반복 제한(TIMEOUT)에 닿은 뒤 유예로 끝났다.

**2. 수신 QP 오류**(`rqp`, rank 1) `[측정]`.
- 2.32.3: rank 1 자신이 `off` 0.051–0.145 ms, `fo` 0.033–0.104 ms, `forec` 0.049–0.151 ms에 ncclRemoteError를 받았다(셀마다 n=10).
  - rank 0은 상대의 죽은 수신 QP에 쓰다가 RETRY_EXC(12)를 받아 오류가 났다: `off` 3 499.0–3 768.9 ms, `fo` 3 509.0–3 578.8 ms,
    `forec` 3 532.2–3 786.6 ms(셀마다 10/10).
  - 틀린 결과는 30회 중 0이다.
- 다중 요청 복구 켬: 5/5 투명. 복구 2.172–2.392 ms(중앙값 2.233).
- **다중 요청 복구 끔, 틀린 결과**(S9). 5/5에서 같은 일이 일어났다.
  - rank 1은 0.053–0.103 ms에 오류를 받았다.
  - rank 0은 자기 오류 없이 장애 난 반복 18을 마쳤다. 결과 버퍼 4 194 304개 중 524 288개(1/8)가 틀렸다.
  - 그 MISMATCH 줄은 훅 뒤 632.3–649.5 ms에 왔다.
  - rank 0의 첫 오류 CQE(RETRY_EXC)는 3 544.3–3 724.3 ms에, abort 중에 왔고 앱 오류로 이어지지 않았다.
  - 두 rank의 abort는 모두 돌아오지 않았다.
  - 본 실행 전체에서 MISMATCH 줄은 이 5개뿐이다.
- 코드 리뷰는 이 결과가 하네스에서 생긴 것이 아님을 로그로 확인했다(`abort called`는 NCCL이 소켓에 남기는 줄이다).
  - 2.23.4 끔: rank 1의 진행 스레드가 오류 줄을 시행마다 5개 남기며 계속 돌았다. rank 1의 `abort called`는 훅 뒤 631.9–649.0 ms였고,
    rank 0의 MISMATCH(632.3–649.5 ms)와 겹친다(n=5).
  - 2.32.3: 진행 스레드가 오류 줄 하나를 남기고 멈췄다. abort는 훅 뒤 6.6–13.9 ms에 걸렸다. 약 0.5 s의 같은 틈이 있었지만 틀린 결과는
    오지 않았다(n=30).
  - 1절 8번의 설명과 맞는다 `[추론]`. 틀린 값이 rank 1의 어느 버퍼에서 왔는지는 `[미확인]`이다.

**3. 받는 중 상대 SIGKILL**(`kill`) `[측정]`.
- kill은 40/40 PID 확인을 거쳐 보내졌다. 그때 생존 rank 0은 40 655–45 218회를 마친 뒤였다(kill 셀 40회의 범위).
- 2.32.3 `off`, `fo`, `forec`와 다중 요청 복구 끔: 생존 rank는 오류 없이 kill 요청 뒤 12 234.2–12 255.8 ms에 TIMEOUT으로 끝났다(셀
  네 개 35회의 범위. 셀마다 범위는 [qa_recount.md](results/20261009/qa_recount.md)).
- 다중 요청 복구 켬: 5/5 오류. kill 요청 뒤 297.7–310.0 ms, kill의 ssh 명령이 돌아온 뒤 49.24–49.29 ms, rank 0의 FIN 줄 뒤
  0.013–0.021 ms였다. 다중 요청 복구가 상대를 죽음으로 보고 원본 오류를 돌려준 것이다. 50 ms 유예 규칙과 맞는다(1절).

**4. 조용한 수신 QP 오류**(`slbc` 64 MiB 방송, `slar` 256 KiB all-reduce, rank 1) `[측정]`.
- 2.32.3에서는 조용하지 않았다. rank 1 자신이 0.048–0.213 ms에 ncclRemoteError를 받았다(셀 여섯 개 60/60. 셀마다 범위는
  [qa_recount.md](results/20261009/qa_recount.md)). `fo`, `forec`는 치명 판정 줄을 남겼다.
- 방송에서 rank 0(보내는 쪽)이 RETRY_EXC로 오류를 받은 것은 `off` 10/10(3 523.2–3 687.8 ms), `fo` 1/10, `forec` 4/10이다. 나머지는 오류
  CQE 없이 유예로 끝났다. 훅이 발사될 때 걸린 수신 수가 `off` 3, `fo`와 `forec` 2로 달랐다. 이 차이를 failover 탓으로 볼지는
  `[미확인]`이다(코드 리뷰 M2).
- all-reduce에서는 rank 0이 30/30 오류 없이 유예로 끝났다.
- 다중 요청 복구 켬:
  - 방송: rank 1이 5/5 알리지 않고 비웠다. rank 0이 RETRY_EXC를 받아 복구했고(복구 줄은 훅 뒤 3 537.7–3 692.3 ms, 복구 1.928–2.037 ms)
    5/5 투명했다. 1절의 이전 측정은 3회 중 1회였다. S4는 두 경우를 모두 허용한다.
  - all-reduce: 5/5 멈춤. 두 rank가 12 s 반복 제한에 닿았고, 그 뒤에도 틀린 결과는 없었다.

**5. 내장 복원력이 한 일** `[측정]`.
- 복원력 동작 줄(장치 실패 표시, recovery 대기열, port recovery 시작과 성공과 실패, QP 교체, 확인 읽기)은 295회에서 0이다. 독립 재계산이
  더 넓게 찾은 줄("not fatal" 분기, 송수신 처리기, 지원하지 않는 상태)도 0이다.
- 복원력의 오류 처리 함수에는 105번 들어갔고(`fo`, `forec`만), 105번 모두 "No functional devices left" 치명 판정으로 끝났다.
  - 80번은 장애를 낸 rank에서였다(failover QP 장애 시행 80/80).
  - 20번은 `rqp@fo`, `rqp@forec`의 rank 0(RETRY_EXC)에서였다.
  - 5번은 `slbc@fo`, `slbc@forec`의 rank 0에서였다.
- 단일 장치 경고는 failover를 켠 시행 140회 모두 두 rank에 있었다. communicator를 닫을 때 recovery 대기열에서 지운 항목은 close 요청 168개
  모두 0개였다.

**6. ncclCommAbort** `[측정]`.
- 2.32.3: abort를 부른 rank 로그 200개 모두 SUMMARY 뒤 516.9–563.7 ms에 돌아왔다.
- 2.23.4(다중 요청 복구 빌드): 40개 중 돌아온 것이 0이다. 35개는 감시 시간(10 s)에 끝났고, 5개(`sqp@s2off` rank 1)는 abort 중 유예로
  끝났다.

**7. 장애 없는 all-reduce 시간** `[측정]`. 실행마다 rank 0의 반복 시간 중앙값(SUMMARY `med_ms`)이고, 셀 값은 실행 10회의 중앙값이다. 범위는
그 셀의 실행 10회에 걸친 범위다. H1이 실행 1–5, H2가 6–10을 돌렸다.

| 크기 | 설정 | 중앙값(ms) | 실행 10회의 범위 | 흩어짐 (최대−최소)/중앙값 |
|---|---|--:|---|--:|
| 64 KiB | `off` | 0.0578 | 0.0533–0.0589 | 9.7 % |
| 64 KiB | `fo` | 0.0588 | 0.0571–0.0600 | 4.9 % |
| 64 KiB | `forec` | 0.0578 | 0.0559–0.0596 | 6.4 % |
| 64 KiB | `s2on` | 0.05395 | 0.0512–0.0609 | 18.0 % |
| 64 KiB | `s2off` | 0.0520 | 0.0511–0.0536 | 4.8 % |
| 16 MiB | `off` | 2.1658 | 2.1561–2.1906 | 1.6 % |
| 16 MiB | `fo` | 2.1626 | 2.1477–2.1895 | 1.9 % |
| 16 MiB | `forec` | 2.1611 | 2.1475–2.1673 | 0.9 % |
| 16 MiB | `s2on` | 2.2668 | 2.2595–2.2767 | 0.8 % |
| 16 MiB | `s2off` | 2.2639 | 2.2559–2.2979 | 1.9 % |

- failover의 비용은 16 MiB −0.15 %, 64 KiB +1.73 %다. recovery를 더한 차이는 −0.07 %, −1.70 %다.
- 다중 요청 복구 켬 대 끔은 16 MiB +0.13 %, 64 KiB **+3.75 %**로 64 KiB가 기준 3 %를 넘었다(O4 틀림).
  - 64 KiB 차이는 hold마다 H1 +1.92 %, H2 +9.27 %였다(5회씩). `s2on`의 중앙값이 0.0532 ms에서 0.0566 ms로 옮겨 갔고, `s2off`는 0.0522,
    0.0518 ms였다.
  - 중앙값을 아래, 위 중앙값으로 바꿔도 +3.28 %, +4.21 %였다.
  - 코드 리뷰의 사후 bootstrap(20 000번, 사전 등록 아님)으로 본 64 KiB 차이의 95 % 구간은 +0.8–+10.4 %다. 3 % 기준이 그 안에 든다. O3의
    64 KiB 구간(−4.6–+0.5 %)도 2 % 기준을 품는다. 16 MiB의 구간들은 ±0.8 % 안이다.
  - 1절의 이전 값 +1.27 %(64 KiB)는 재현되지 않았다. 그 측정은 다른 방식이었다(13절).
- pilot의 `forec` 대 `fo` +4.0 %, +4.7 %(실행 하나)는 재현되지 않았다.
- 예측하지 않은 값: 64 KiB에서 2.23.4 끔이 2.32.3 `off`보다 10.0 % 빠르고, 16 MiB에서는 4.5 % 느리다. 버전과 방식이 섞인 비교라 해석하지
  않는다 `[추론]`.

**8. mlx5** `[측정]`. 30개 스냅숏 모두 명령 오류 줄 rain 2, sunny 0, rain 펌웨어 명령 실패 수 31이다. 새 커널 줄은 H13의 sunny FWTracer 한
줄뿐이다(12절).

## 16. QA와 재현성

- **독립 재계산**([qa_recount.md](results/20261009/qa_recount.md), [qa/recount.py](qa/recount.py)).
  - 다른 에이전트가 `score.py`, `rows_nb.py`, 채점 결과를 읽지도 돌리지도 않고 원시 파일에서 3.1의 열을 다시 만들었다. 8절과 판정식도 따로
    구현했다. 판정이 같다(26 맞음, 1 틀림, 자료 부족 0).
  - 295회의 hold 출력 줄과 모든 비교 항목이 같다.
  - 예측 파일, `PREREG.txt`, 스크립트, `inject_232.diff`, 2, 3, 7, 8절이 태그와 같다. `hold.sh`는 관리망 주소 치환만 다르다.
  - pilot 시행(01:04–01:09)과 본 실행 시행(03:21–06:21)은 섞이지 않았다.
- **코드 리뷰**([qa/code_review.md](qa/code_review.md)). 막는 결함과 큰 결함은 없고, 판정을 바꾸는 것도 없다.
  - 두 라이브러리의 훅은 셀마다 같은 반복에 장애를 냈다. 송신, 수신 QP는 `IT 17` 뒤, 조용한 방송은 `IT 1` 뒤, 조용한 all-reduce는
    `IT 99` 뒤였다. 주입 시행 155회(2.32.3 125, 2.23.4 30) 모두 그렇다. 코드 리뷰는 이를 n=150으로 적었지만 그 표의 합은 155이고,
    이 문서를 쓸 때 원시 로그로 다시 세어 155회를 확인했다 `[측정]`. 2.32.3 훅 줄 125개 모두 `nqps=1, rc=0`이다.
  - S9는 하네스에서 생긴 것이 아니다(15절 2).
  - 중간 결함 세 개는 해석에 관한 것이다.
    - M1: 64 KiB의 O3, O4 기준이 잡음 안에 있다(15절 7).
    - M2: 조용한 방송 오류가 설정마다 보내는 쪽에 다르게 닿는다(15절 4).
    - M3: 6 s 유예가 장애를 내지 않은 rank를 2.32.3에서는 약 6.6 s, 2.23.4에서는 약 16 s에 끊는다. 그래서 그 rank의 운명은 라이브러리끼리
      비교하지 않는다.
  - 작은 것 L1–L5와 사소한 것 N1–N7 가운데 기록에 닿는 것은 13절에 적었다.
- **문서와 다른 점**(독립 재계산의 7가지). 고정 절에 닿는 것은 13절에, 결과는 15절에 적었다.
  1. O4 틀림. 1절의 +1.27 %가 재현되지 않았다.
  2. 12절 pilot 검토의 조용한 방송 rank 0 RETRY_EXC는 `off`에서만 10/10이다.
  3. 3.4절: 2.23.4 abort 40개 중 5개는 감시 시간이 아니라 유예로 끝났다.
  4. pilot의 `forec` 대 `fo` 차이가 재현되지 않았다.
  5. 1절의 조용한 방송 복구 1/3이 본 실행에서는 5/5였다.
  6. 본 실행 중 이 문서의 기록이 사전 등록 상태에 머물러 있었다(이 커밋에서 고침).
  7. 9절의 hold 시간 추정은 모두 지켜졌다(합 52.5분, 추정 약 65분).
- **코드 리뷰와 원자료의 차이 하나.** 코드 리뷰 M1은 O4 근거 측정의 반복 수를 스크립트 기본값으로 200회와 20회라고 적었다. 그 원시 로그의
  SUMMARY에는 400회와 25회가 찍혀 있다 `[측정]`. 방식이 다르다는 결론은 같다.
- **재현.**
  - 2.32.3 + 훅: [inject_232.diff](inject_232.diff)(upstream v2.32.3-1 `12df1a11` 기준)와 [build_nb.sh](build_nb.sh). libnccl md5 `9269cc75`.
  - 다중 요청 복구: `../stage2/net_ib_stage2.diff`(v2.23.4-1 기준). libnccl md5 `9ed03e1d`.
  - 드라이버: `../perf/nccl_ct.cu`. md5 `523fd863`.
  - 실행과 채점: 태그 `prereg/nccl-builtin-v1`의 [cells.py](cells.py), [hold.sh](hold.sh), [score.py](score.py).

## 17. 결론

- **노드마다 활성 포트가 하나인 이 테스트베드에서 NCCL 2.32.3의 내장 복원력은 아무 장애도 막지 못했다.**
  - port failover를 켜든 recovery까지 켜든, 주입한 QP 오류는 첫 오류 CQE에서 "남은 장치 없음"으로 곧바로 치명 판정됐다. 앱은 복원력을 끈
    것과 같은 ncclRemoteError를 받았다.
  - 장치를 넘기는 일도, 확인 읽기도, port recovery도 295회에서 한 번도 시작되지 않았다. port recovery 변수만 켜면 데이터 경로가 그대로다.
  - 받는 중 상대가 죽은 것은 어느 설정에서도 12 s 반복 제한까지 보이지 않았다.
- **이 저장소의 다중 요청 복구는 같은 장애에서 작업을 살렸다.**
  - 송신, 수신 QP 오류를 앱이 모르게 약 2.2–2.3 ms에 복구했다(셀마다 5/5).
  - 상대의 죽음은 관리망 소켓의 FIN으로 약 50 ms 만에 오류로 바꿨다.
- **복구를 끈 2.23.4의 오류 경로는 장애를 틀린 결과로 바꿔 상대에게 넘겼다.**
  - 수신 QP 오류를 받은 rank가 abort하자, 상대 rank는 장애 난 all-reduce를 오류 없이 마쳤다. 결과의 1/8이 틀렸다(5/5).
  - 2.23.4의 진행 스레드는 오류 뒤에도 돌고, abort한 커널은 덜 만든 데이터를 내보낸다.
  - 2.32.3은 진행 스레드가 첫 오류에서 멈춰 같은 장애에서 틀린 결과가 없었다(30/30).
  - 다중 요청 복구 끔의 오류 경로는 원본 2.23.4의 것이므로 원본 NCCL 2.23.4의 동작으로 본다 `[추론]`.
- **abort도 달라졌다.** 2.32.3의 `ncclCommAbort`는 오류 뒤 약 0.52–0.56 s에 모두 돌아왔다(200/200). 2.23.4는 한 번도 돌아오지 않았다(0/40).
- **2.32.3에서는 "조용한" 수신 QP 오류도 조용하지 않다.** 장애를 낸 rank가 자기 수신이 비워진 것을 보고 바로 오류를 올렸다(60/60).
- **장애가 없을 때의 비용.**
  - failover는 16 MiB에서 차이가 없고(−0.15 %) 64 KiB에서 +1.7 %였다. recovery는 비용을 더하지 않았다.
  - 다중 요청 복구는 16 MiB에서 +0.13 %였다. 64 KiB에서는 +3.75 %로 사전 등록 기준 3 %를 넘었다. 다만 실행 사이 흩어짐이 그만큼 커서
    64 KiB의 비용은 이 자료로 가르지 못한다.
- 사전 등록 예측 27개 중 26개가 맞았다.

## 18. 한계

- **노드마다 활성 포트가 하나다.** failover와 recovery가 실제로 동작할 경로는 열리지 않는다. 이 실험은 장치가 하나일 때의 동작만 보였다.
  장치가 둘일 때 넘겨 가기, 확인 읽기, port recovery가 어떻게 되는지는 재지 않았다.
- **port recovery는 실제 포트 이벤트로 시험하지 않았다.** 장애는 소프트웨어로 QP를 ERR로 옮긴 것과 SIGKILL뿐이다. link down, flap, GID
  변경은 클러스터 규칙상 하지 않았다. 내장 복원력은 포트 이벤트로 시작하지 않고 오류 CQE로만 시작한다 `[소스]`.
- **로그 수준이 셀마다 다르다.** QP 장애 셀은 INFO, kill과 장애 없는 셀은 WARN이다. 같은 셀 안의 설정끼리는 같다. WARN 셀에서는 recovery
  동작 줄 중 장치 실패 표시만 보인다. rank 1이 어느 라이브러리를 읽었는지는 환경과 번들 md5로만 확인했다(코드 리뷰 L1, L4).
- **1 ms보다 짧은 시각은 줄을 받은 시각의 차이다.** 파이프와 ssh 지연이 들어 있고 rank 사이에 공유하는 시계가 없다. kill 셀의 시각에는
  약 0.25 s의 ssh 왕복이 들어 있다(코드 리뷰 L2).
- 장애를 내지 않은 rank의 운명은 실행기의 6 s 유예에 잘린다. 그 시점이 라이브러리마다 달라 비교할 수 없다(M3).
- 64 KiB의 비용 비교는 실행 사이 흩어짐(4.8–18.0 %) 안에 있다. hold 스냅숏에 트래픽 계수가 없어 다른 트래픽이 있었는지는 모른다(L5).
- 조용한 방송 오류가 보내는 쪽에 닿는지는 설정마다 달랐고 그 원인은 확인하지 않았다(M2).
- 2.32.3과 2.23.4의 비교는 NCCL 버전과 복구 코드가 함께 다르다. 다중 요청 복구는 시험 스위치가 든 연구 빌드다.
- 2 rank, 노드 한 쌍, ConnectX-6 RoCE 직결 하나다.

## 19. 다음 작업

- **포트가 둘인 구성에서 failover와 recovery를 다시 잰다.** 노드마다 활성 포트가 둘 있어야 한다. rain의 mlx5_0을 켜는 것은 링크를 바꾸는
  일이라 지금 클러스터 규칙으로는 할 수 없다. 사용자의 허락과 배선, 또는 다른 테스트베드가 필요하다.
- port recovery를 실제 포트 이벤트로 시험하는 것도 같은 이유로 지금은 할 수 없다. 공유 링크에서 link flap을 허락받거나 전용 링크가 필요하다.
- 2.32.3에서 시간 초과로 abort할 때(진행 스레드는 멈추지 않는다) 살아 있는 상대에게 틀린 결과가 갈 수 있는지 잰다. 이 실험의 2.32.3
  셀에는 그런 경우가 없었다.
- 64 KiB의 비용을 트래픽 계수와 함께, 섞어 도는 실행을 늘려 다시 잰다.
- 조용한 방송 오류에서 보내는 쪽이 노출되는 조건(걸린 수신 수와 CTS 시각)을 확인한다.

## 20. 참고자료

- [`../stage2/README.md`](../stage2/README.md), [`../stage2/NOTES.md`](../stage2/NOTES.md), `../stage2/DESIGN_stage2.md`(다중 요청 복구)
- [`../perf/README.md`](../perf/README.md)(장애 없는 비용)
- `../../gpu-initiated/gin_recovery/oneway/EXPERIMENT.md`(구조와 스크립트의 본보기), `../../gpu-initiated/gin_recovery/s2_close/EXPERIMENT.md`
  3.2절(판정식 문법)
- NCCL v2.32.3-1 `src/transport/net_ib/p2p_resiliency.cc`, `p2p_resiliency_recovery.cc`, `p2p.cc`, `common.cc`, `src/proxy.cc`;
  NCCL v2.23.4-1 `src/proxy.cc`, `src/device/prims_simple.h`
- [results/20261009/qa_recount.md](results/20261009/qa_recount.md)(독립 재계산), [qa/code_review.md](qa/code_review.md)(코드 리뷰)
