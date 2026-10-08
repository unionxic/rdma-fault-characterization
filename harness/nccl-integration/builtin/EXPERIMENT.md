# NCCL 내장 복원력과 다중 요청 복구의 비교 (nccl-builtin)

**목적:** 노드마다 활성 RoCE 포트가 하나인 rain–sunny 테스트베드에서 NCCL 2.32.3의 내장 복원력(port failover, port recovery)과 이
저장소의 다중 요청 복구(NCCL 2.23.4, CPU 프록시 IB 경로)를 같은 주입 장애 네 가지로 돌린다. 각자 무엇을 하고 앱이 무엇을 보는지, 장애가
없을 때 얼마의 비용을 내는지를 사전 등록한 예측으로 잰다.

| 항목 | 값 |
|---|---|
| 상태 | `DRAFT` |
| 담당자 | @unionxic |
| 작성일 | 2026-10-09 |
| 기준 브랜치와 커밋 | `exp/nccl-builtin` @ `d834f86c` |
| 사전 등록 태그 | 없음. 메인 세션의 pilot 뒤 `prereg/nccl-builtin-v1`을 달 예정(3절) |
| 마지막 갱신 | 2026-10-09 01:00, 초안(1–12절), 훅과 빌드, 스크립트, 오프라인 채점 시험 |

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
  0.013–0.030 ms에 올라왔다(A5). 플래그를 끈 `78f96f38` 3/3은 생존 rank가 통신기 준비 줄 뒤 아무 줄도 남기지 않았고, 실행기가 60 s에
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
1. **켜는 조건.** `NCCL_IB_RESILIENCY_PORT_FAILOVER=1`이 아니면 통신기마다 복원력 문맥을 만들지 않는다(`p2p_resiliency.cc` 618–623행).
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
5. **장치가 하나면.** 연결 때 송신, 수신 통신기 모두 "... with a single device. This does not make sense since there is no other device
   to fail over to."를 경고한다(840–844행). 오류 CQE 하나가 곧 "모든 장치 실패"라서 치명 판정이 먼저 난다. QP 교체, 확인 읽기, port
   recovery는 어느 것도 시작되지 않는다 `[추론]`.
6. **앱이 보는 것.** 복원력이 없을 때와 같은 ncclRemoteError다. 프록시가 그 값을 통신기의 비동기 오류로 둔다(`proxy.cc` 980행).
   로그만 다르다. 복원력이 없으면 "Got CQE with error"와 "Got completion from peer ... status=...(n)"이 남고, 있으면 "Got completion with
   error"(INFO)와 치명 판정 줄이 남는다.
7. **상대 프로세스의 죽음.** 이 경로에는 CQE로만 보인다. RAS는 통신기 상태를 읽기만 한다(`ras/collectives.cc` 725–731행).

**이 테스트베드** `[측정]`. 2026-10-09 00:45 rain sysfs에서 mlx5_0 port 1은 DOWN(Disabled), mlx5_1은 ACTIVE였다. NCCL은 ACTIVE가 아닌
포트를 쓰지 않는다(`init.cc` 505행) `[소스]`. 이전 실험처럼 rank마다 `NCCL_IB_HCA`로 한 장치만 쓴다(rain mlx5_1, sunny mlx5_0). sunny의
다른 포트 상태는 `[미확인]`이고 hold 스냅숏에 남긴다.

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

## 2. 가설

| id | 가설 | 다음이 관측되면 틀린 것이다 |
|---|---|---|
| H1 | 장치가 하나면 내장 복원력은 어떤 장애도 숨기지 못한다. 주입한 QP 장애는 복원력 없는 2.32.3과 같은 ncclRemoteError로 1 s 안에 올라오고, 장치 실패 표시, QP 교체, 확인 읽기, port recovery는 시작되지 않는다 | failover나 failover와 recovery 셀에서 투명한 시행이 하나라도 있다. 또는 복구 동작 줄이 하나라도 있다. 또는 송신, 수신 QP 셀(셀마다 10회)에서 치명 판정과 1 s 안 ncclRemoteError가 9/10 미만이다 |
| H2 | port recovery 변수만 켜면 데이터 경로가 바뀌지 않는다 | `sqp@rec`에서 failover 경고, 치명 판정, 복구 동작 줄이 나오거나 원본 오류 경로가 4/5 미만이다 |
| H3 | 다중 요청 복구는 같은 날 같은 실행기에서도 이전 결과를 재현한다 | 예측 S1–S5 중 하나라도 틀린다 |
| H4 | 플래그를 끈 다중 요청 복구와 복원력 없는 2.32.3은 송신, 수신 QP 장애를 1 s 안의 오류로, 받는 중 상대의 죽음을 멈춤으로 보인다 | 예측 B1–B3, S6–S8 중 하나라도 틀린다 |
| H5 | 2.32.3에서는 "조용한" 수신 QP 장애도 rank 1 자신이 1 s 안에 오류로 올린다. 다중 요청 복구는 rank 1에서 조용히 둔다 | 예측 B4, F4, S4 중 하나라도 틀린다 |
| H6 | 장애가 없을 때의 비용은 작다 | 예측 O1–O4 중 하나라도 틀린다 |

## 3. 사전 예측

**고정 시점.** 예측 원문은 [predictions.csv](predictions.csv)(26줄)다. 예측은 사전 등록 태그를 달 때 고정한다. 메인 세션이 pilot(9절의
P1, P2)을 돌린 뒤, 상태를 `PREREGISTERED`로 바꾸고 `predictions.csv`의 sha256을 `PREREG.txt`에 적은 커밋 하나에
`prereg/nccl-builtin-v1`을 단다. **pilot 시행은 어떤 경우에도 채점하지 않는다.** pilot을 보고 태그 전에 예측, 셀, 반복 수, 판정식을
고치면 무엇을 왜 고쳤는지, pilot의 어느 관측이 근거인지 12절에 적는다. 태그 뒤에는 13절 규칙을 따른다.

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
| `mism` | 두 rank의 `MISMATCH` 줄 수 합 |
| `outcome` | `MISMATCH`(mism > 0), `TRANSPARENT`(두 rank 종료 코드 0, 두 rank 모두 `ok == iters`), `ERROR`(아니고 어느 rank든 오류 줄), `HANG`(아니고 TIMEOUT 줄이 있거나 실행 상한에 닿음), `OTHER`(그 밖) |
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
| B1 | `sqp@off` | 복원력 없는 2.32.3: 송신 QP 장애가 rank 0에서 1 s 안에 ncclRemoteError로 올라온다. 원본 오류 CQE 줄과 WR_FLUSH_ERR가 남는다 | ≥4/5 | `ncclIbTest` `[소스]`, 다중 요청 복구 끔 0.055–0.242 ms(3회) `[측정]` |
| B2 | `rqp@off` | 수신 QP 장애가 rank 1 자신에게서 1 s 안에 ncclRemoteError로 올라온다 | ≥4/5 | 걸어 둔 수신과 다음 CTS가 비워짐 `[소스]` |
| B3 | `kill@off` | 받는 중 상대가 죽으면 생존 rank는 12 s 반복 제한까지 오류를 보지 못한다 | 멈춤 ≥4/5 | 1절 7번 `[소스]`, 2.23.4 끔 3/3 `[측정]` |
| B4 | `slbc@off`, `slar@off` | "조용한" 장애도 rank 1 자신이 1 s 안에 ncclRemoteError로 올린다 | 셀마다 ≥4/5 | 걸어 둔 수신이 비워짐 `[소스]` |
| R1 | `sqp@rec` | recovery 변수만 켜면 `off`와 같다. 원본 오류 경로이고 failover 경고, 치명 판정, 복구 동작 줄이 없다 | ≥4/5 | 1절 1번 `[소스]` |
| F1 | `sqp@fo`, `sqp@forec` | 첫 오류 CQE에서 곧바로 치명 판정, rank 0에 1 s 안 ncclRemoteError. 원본 오류 CQE 줄과 복구 동작 줄이 없다 | 셀마다 ≥9/10 | 1절 4, 5번 `[소스]` |
| F2 | `rqp@fo`, `rqp@forec` | 같은 판정이 rank 1에서 | 셀마다 ≥9/10 | 같음 |
| F3 | `kill@fo`, `kill@forec` | 생존 rank는 12 s 반복 제한까지 오류를 보지 못한다 | 셀마다 멈춤 ≥4/5 | 1절 3, 7번 `[소스]` |
| F4 | `slbc@fo`, `slbc@forec`, `slar@fo`, `slar@forec` | rank 1 자신이 치명으로 판정해 1 s 안에 올린다 | 셀마다 ≥4/5 | B4와 F1 `[소스]` |
| F5 | failover를 켠 셀 14개(장애 10, 장애 없음 4) | 모든 시행에서 두 rank가 연결 때 "넘겨 갈 다른 장치가 없다"고 경고한다(WARN 줄이라 모든 셀에서 보인다) | 셀마다 예외 0 | 1절 5번 `[소스]` |
| F6 | 2.32.3 장애 셀 16개 | 어느 설정도 어느 장애도 투명하게 만들지 못한다 | 셀마다 투명 0 | H1 |
| F7 | 2.32.3 장애 셀 16개 | 장치 실패 표시, QP 교체, 확인 읽기, port recovery 줄이 없다. kill 셀은 WARN이라 이 중 장치 실패 표시 줄만 보인다 | 셀마다 0 | 1절 4, 5번 `[소스]` |
| S1 | `sqp@s2on`, `rqp@s2on` | 다중 요청 복구가 두 QP 장애를 투명하게 복구한다 | 셀마다 5/5 | 30/30, 30/30, 최종 빌드 3/3, 3/3 `[측정]` |
| S2 | 같음 | 복구 시간(송신 통신기 `total`) 중앙값이 두 셀 모두 1.8–3.0 ms | 셀 중앙값 | 2.152–2.400 ms(최종 빌드 6회) `[측정]` |
| S3 | `kill@s2on` | OOB 소켓의 FIN으로 상대의 죽음을 알아 kill 뒤 1 s 안에 생존 rank에 오류를 올린다 | 5/5 | 3/3 `[측정]` |
| S4 | `slbc@s2on` | rank 1은 1 s 안에 오류를 올리지 않는다. 작업은 투명하게 복구되거나 멈춘다 | 5/5 | 3회 `[측정]` |
| S5 | `slar@s2on` | 보내는 쪽이 할 일이 없어 12 s 반복 제한까지 멈춘다 | 5/5 | 5회와 1회 `[측정]` |
| S6 | `sqp@s2off` | 1 s 안 ncclRemoteError, WR_FLUSH_ERR, 복구 줄 없음 | 5/5 | 3/3 `[측정]` |
| S7 | `rqp@s2off` | rank 1에서 1 s 안 ncclRemoteError, 복구 줄 없음 | ≥4/5 | `[소스]`, 이전 대조 없음 `[미확인]` |
| S8 | `kill@s2off` | 생존 rank는 12 s 반복 제한까지 오류를 보지 못한다 | 멈춤 ≥4/5 | 3/3 `[측정]` |
| I1 | 셀 34개 모두 | 어느 시행도 틀린 결과를 내지 않는다(MISMATCH 없음) | 셀마다 0 | `[추론]` |
| O1 | `ovh16m@fo` 대 `ovh16m@off` | failover가 rank 0 반복 시간 중앙값을 2 % 넘게 바꾸지 않는다 | 실행 중앙값의 차이 | 1절 2번 `[소스]`, 크기는 `[추론]` |
| O2 | `ovh64k@fo` 대 `ovh64k@off` | 5 % 넘게 바꾸지 않는다 | 같음 | 같음 |
| O3 | `forec` 대 `fo`, 두 크기 | port recovery를 더해도 2 % 넘게 바뀌지 않는다 | 같음 | 쉬는 스레드와 QP뿐 `[소스]` |
| O4 | `s2on` 대 `s2off`, 16 MiB와 64 KiB | 2 %, 3 % 안 | 같음 | +1.27 %, −0.22 %(3회씩) `[측정]` |
| O5 | 장애 없는 셀 10개 | 모든 실행이 투명하다 | 셀마다 5/5 | `[추론]` |

### 3.4 탐색 관찰(채점하지 않음)

다음은 예측 없이 기록만 하고 15절에 서술한다.
- 2.32.3 장애 셀에서 장애를 내지 않은 rank가 겪는 일: 상대가 끝난 뒤 RETRY_EXC를 받는지, 실행기의 6 s 유예 뒤에 끝나는지.
- 2.32.3에서 오류 뒤 `ncclCommAbort`가 돌아오는지(`abort_ret_r<r>`, `abort_hang_r<r>`). 2.23.4에서는 1절의 원시 로그 중 오류 뒤 abort를
  부른 rank 로그 14개(A5의 T8과 T9, C4, T12d) 모두 감시 시간에 끝났고 돌아온 것은 0이다 `[측정]`.
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
| NIC와 포트 | ConnectX-6, fw 20.43.4100. rain mlx5_0 port 1 DOWN(Disabled), mlx5_1 ACTIVE(Ethernet). 쓰는 장치는 rain mlx5_1, sunny mlx5_0(`NCCL_IB_HCA`) | rain `[측정]` 2026-10-09 00:45 sysfs. sunny `[미확인]`, hold 스냅숏에 남긴다 |
| 커널 | rain 5.15.0-97-generic | rain `[측정]` 2026-10-09. sunny는 hold 스냅숏 |
| GPU, 드라이버, CUDA | rain Quadro RTX 5000, 드라이버 570.211.01, CUDA 12.8(nvcc 12.8.93). sunny RTX A4000 | rain `[측정]` 2026-10-09. sunny는 루트 README `[미확인]` |
| 관리망 소켓 | `NCCL_SOCKET_IFNAME=eno1` | `cells.py` |
| IB 타임아웃 | `NCCL_IB_TIMEOUT=14`, 재시도 횟수는 기본(7) | `cells.py` |
| 2.32.3 + 훅(`n232`) | libnccl md5 `9269cc75b0a75cbdc327b075cd26234c`. upstream v2.32.3-1(`12df1a11`) + [inject_232.diff](inject_232.diff)(md5 `c4709b2e`, `p2p.cc` 96줄 추가) | `[측정]` 2026-10-09 00:36 빌드됨. [build_nb.sh](build_nb.sh)가 빌드 전에 소스 트리가 태그 + diff와 같은지 확인했다. 내 스크래치 트리와 upstream 태그는 `bindings/nccl4py/.git_archival.txt`만 다르다. 실행은 하지 않았다 |
| 다중 요청 복구(`s2`) | libnccl md5 `9ed03e1d4b9833c0c2e01f3aa1f84d1c`(최종 빌드 `a037de42` + 쓰지 않는 원격 접근 훅) | `[측정]` v2.23.4-1의 `net_ib.cc`에 `../stage2/net_ib_stage2.diff`를 적용하면 git hash-object `18d998a8`로 diff 머리말과 같다. 이 바이너리가 그 소스에서 나왔다는 것은 `../stage2/NOTES.md`의 기록이다 `[미확인]` |
| 드라이버 `nb_ct` | md5 `523fd8637c185caa39987f10543b893f`. `../perf/nccl_ct.cu`를 고치지 않고 2.23.4의 `nccl.h`로 sm_75, sm_86 컴파일 | `[측정]` 빌드됨. rain에서 `ldd -r`로 두 라이브러리 모두 해결 안 된 기호가 없음을 확인(정적 확인, 실행 안 함) |

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

반복 수는 내장 복원력의 송신, 수신 QP 셀(가설 H1의 중심) 10회, 나머지 5회다. 장애 없는 셀의 반복은 실행 수다.

| 셀 | 조건 | 설정과 반복 수 | 종류 |
|---|---|---|---|
| `sqp` | 기본 설정, 16 MiB all-reduce 150회, warmup 0. rank 0에 `NCCL_RDMA_FAULT_INJECT=301` | `off` 5, `rec` 5, `fo` 10, `forec` 10, `s2on` 5, `s2off` 5 | N, C, N, N, R, C |
| `rqp` | 같은 작업. rank 1에 `NCCL_RDMA_FAULT_INJECT_RECV=301` | `off` 5, `fo` 10, `forec` 10, `s2on` 5, `s2off` 5 | N, N, N, R, C |
| `kill` | 1채널, 256 KiB all-reduce 300 000회(`--quiet`), warmup 5. rank 0을 띄운 뒤 5 s에 실행기가 rank 1을 PID로 SIGKILL | `off`, `fo`, `forec`, `s2on`, `s2off` 각 5 | N, N, N, R, C |
| `slbc` | 1채널, 64 MiB 방송 60회, warmup 0. rank 1에 `NCCL_RDMA_FAULT_INJECT_RECV=301`, `NCCL_RDMA_FAULT_INJECT_RECV_SILENT=1` | `off`, `fo`, `forec`, `s2on` 각 5 | N, N, N, R |
| `slar` | 1채널, 256 KiB all-reduce 1 000회, warmup 0. rank 1에 같은 조용한 훅, 403번째 | `off`, `fo`, `forec`, `s2on` 각 5 | N, N, N, R |
| `ovh64k` | 기본 설정, 64 KiB all-reduce 2 000회, warmup 20, 장애 없음 | `off`, `fo`, `forec`, `s2on`, `s2off` 각 5 | N, N, N, R, R |
| `ovh16m` | 기본 설정, 16 MiB all-reduce 200회, warmup 5, 장애 없음 | 같음 | 같음 |

1채널은 `NCCL_MAX_NCHANNELS=1`, `NCCL_MIN_NCHANNELS=1`, `NCCL_ALGO=Ring`, `NCCL_PROTO=Simple`, `NCCL_IB_QPS_PER_CONNECTION=1`이다
(`../stage2/run_tests.py`와 같다). 기본 설정은 NCCL이 고른다.

**합계.**

| 종류 | 장애 셀 시행 | 장애 없는 실행 |
|---|--:|--:|
| 2.32.3(`off`, `rec`, `fo`, `forec`) | 100 | 30 |
| 다중 요청 복구 켬 | 25 | 10 |
| 다중 요청 복구 끔 | 15 | 10 |
| 합 | 140 | 50 |

장애 셀 시행 140회는 셀 키 24개의 합이다(`sqp` 40, `rqp` 35, `kill` 25, `slbc` 20, `slar` 20). 장애 없는 실행 50회는 셀 키 10개의 합이다.
pilot은 따로 34회다(셀 키마다 1회, 9절).

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
- `NCCL_RDMA_FAULT_INJECT=k`: 프로세스의 k번째 첫 multi-send 직전(`ncclIbIsend`에서 `ncclIbMultiSend` 앞), 그 송신 통신기의 데이터 QP를
  모두 ERR로.
- `NCCL_RDMA_FAULT_INJECT_RECV=k`: 프로세스의 k번째 수신 게시 직전(`ncclIbIrecv` 앞부분), 그 수신 통신기의 데이터 QP를 모두 ERR로.
- `NCCL_RDMA_FAULT_INJECT_RECV_SILENT=1`과 함께: 처음 수신을 완료한 수신 통신기에서, k번째 수신 완료부터 다른 수신이 하나 이상 걸려
  있을 때 그 통신기의 데이터 QP를 모두 ERR로. 상대에게 알리지 않는다(`ncclIbCompletionEventProcess`의 수신 완료 처리 뒤).
- 발사마다 WARN 한 줄 `NET/IB: [FAULT-INJECT] forced ...`, 끝에 `mono_ms`. 변수마다 프로세스당 한 번만 발사한다.
- 다중 요청 복구의 훅은 `qps[0]` 하나를 바꿨다. 이 훅은 그 통신기의 데이터 QP를 모두 바꾼다. 연결당 QP 기본값이 1이라 이 실험에서는 같다
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

| hold | 내용 | 추정 `[추론]` |
|---|---|---|
| P1 pilot | 송신, 수신 QP 셀 키 11개 각 1회, 장애 없는 셀 키 10개 각 1회 | 5–6분 |
| P2 pilot | 조용한 장애 셀 키 8개, kill 셀 키 5개 각 1회 | 6분 |
| H1 | 장애 없는 셀 키 10개 × 5회 | 5–6분 |
| H2 | `sqp@off`, `rqp@off`, `sqp@rec`, `sqp@s2on` × 5 | 5–6분 |
| H3 | `sqp@fo`, `sqp@forec` × 10 | 6분 |
| H4 | `rqp@fo`, `rqp@forec` × 10 | 6분 |
| H5 | `rqp@s2on`, `sqp@s2off`, `rqp@s2off`, `kill@s2off` × 5 | 7분 |
| H6 | `slbc@off`, `slbc@fo`, `slbc@forec`, `slbc@s2on` × 5 | 6–7분 |
| H7 | `slar@off`, `slar@fo`, `slar@forec`, `slar@s2on` × 5 | 7분 |
| H8 | `kill@off`, `kill@fo`, `kill@forec`, `kill@s2on` × 5 | 9분 |

시행 하나의 추정 `[추론]`: 투명한 시행 5–6 s, 한 rank가 오류를 받는 시행 10–20 s(abort가 돌아오는지와 6 s 유예에 따라), 멈춤 20–30 s.
최악은 실행 상한(장애 셀 40 s × hold당 20회 = 800 s)이라 hold 하나가 880 s를 넘지 않는다. hold마다 잠금과 유휴 확인, 스냅숏이 약 1분 더
든다. 본 실행 H1–H8은 50–60분, pilot은 약 12분이다 `[추론]`.

**채점.** `python3 score.py results/<날짜>`. [rows_nb.py](rows_nb.py)가 3.1의 열을 만들고, [score.py](score.py)가 8절의 제외와 설정
확인을 거쳐 [predictions.csv](predictions.csv)의 판정식을 3.2 문법대로 적용한다. 결과는 `results/<날짜>/SCORE.md`와
`results/<날짜>/trials_scored.csv`다. pilot 폴더에는 쓰지 않는다(`score.py`가 거절한다).

**출력.** 시행 파일과 hold 출력은 커밋하지 않고 Release에 올린다. 커밋하는 것은 `SCORE.md`, `trials_scored.csv`, `deploy_check.txt`다.

## 10. 완료 조건과 QA 기준

- [ ] 모든 셀 키가 계획한 반복 수만큼 판정됐다. 제외와 설정 확인 실패를 따로 센 표가 있다.
- [ ] 예측 26줄마다 판정(맞음, 틀림, 자료 부족)과 놓친 시행 목록이 있다.
- [ ] 다른 에이전트가 `score.py`를 보지 않고 원시 로그에서 핵심 수치를 다시 셌다. 대상은 결과 분류, 앱 오류와 시각, 치명 판정과 복원력 동작
  줄, 다중 요청 복구의 복구 줄과 시간, 반복 시간 중앙값이다.
- [ ] 다른 에이전트가 `inject_232.diff`와 실행기를 읽고 리뷰했다.
- [ ] pilot과 제외 시행이 결과에 섞이지 않았다.
- [ ] 새 빌드의 md5와 배포 확인을 5절과 12절에 적었다.
- [ ] 원자료를 Release에 올리고 `DATA.md`에 적었다.
- [ ] hold 전후 mlx5 스냅숏에 새 명령 오류가 없었거나, 있었다면 그 줄의 내용을 12절에 적었다.

## 11. 작업 체크리스트

- [x] 질문, 가설, 셀 작성 (`DRAFT`)
- [x] 2.32.3 소스 읽기(복원력 경로와 그 호출자)
- [x] 주입 훅 작성, 빌드(`n232` 빌드됨), 다중 요청 복구 빌드와 드라이버 준비
- [x] `cells.py`, `nbrun.py`, `hold.sh`, `chain.sh`, `deploy_nb.sh`, `rows_nb.py`, `score.py`
- [x] 실행기와 채점기의 오프라인 시험(클러스터 없이, 12절)
- [ ] 배포(메인 세션)
- [ ] pilot P1, P2(메인 세션, 채점 제외)
- [ ] 고정 절 확정, 상태 `PREREGISTERED`, 해시 기록을 커밋 하나로 만들고 그 커밋에 `prereg/` 태그
- [ ] 본 실행 H1–H8 (`RUNNING`)
- [ ] 채점 (`QA`)
- [ ] 독립 재계산과 코드 리뷰
- [ ] 결과 정리, 원자료 릴리스, PR
- [ ] 결론 확정 (`COMPLETE`)

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
| 2026-10-09 01:00 | 1–12절 초안, 예측 26줄. 상태 `DRAFT`. 클러스터에서는 아무것도 돌리지 않았다(ssh, 배포, `cluster_run.sh`, GPU나 RDMA 프로그램 실행 모두 없음) | 이 커밋 |

## 13. 사전 등록 이후 변경

아직 사전 등록 전이다. 태그 뒤의 변경은 기존 문장을 고치지 않고 여기(또는 `DEVIATIONS.md`)에 날짜, 이유, 영향 범위, 커밋을 덧붙인다.

| 날짜 | 무엇을 | 이유 | 영향 범위 | 커밋 |
|---|---|---|---|---|

## 14. 원자료와 결과표

아직 없다 `[미확인]`.

| 무엇 | 경로 또는 Release 자산 | n |
|---|---|--:|

## 15. 결과 요약

아직 없다 `[미확인]`.

## 16. QA와 재현성

아직 없다. 재현에 필요한 것: [inject_232.diff](inject_232.diff)(upstream v2.32.3-1 기준), `../stage2/net_ib_stage2.diff`(v2.23.4-1 기준),
`../perf/nccl_ct.cu`, [build_nb.sh](build_nb.sh).

## 17. 결론

아직 없다.

## 18. 한계

아직 없다. 설계상 알려진 한계: 장치가 하나라 내장 복원력이 장치를 넘겨 가는 경로는 재지 않는다. 주입 장애는 소프트웨어로 QP를 ERR로 옮긴
것이라 실제 경로 장애(RETRY_EXC, 포트 이벤트)와 다르다. 노드 한 쌍, 2 rank다.

## 19. 다음 작업

아직 없다.

## 20. 참고자료

- [`../stage2/README.md`](../stage2/README.md), [`../stage2/NOTES.md`](../stage2/NOTES.md), `../stage2/DESIGN_stage2.md`(다중 요청 복구)
- [`../perf/README.md`](../perf/README.md)(장애 없는 비용)
- `../../gpu-initiated/gin_recovery/oneway/EXPERIMENT.md`(구조와 스크립트의 본보기), `../../gpu-initiated/gin_recovery/s2_close/EXPERIMENT.md`
  3.2절(판정식 문법)
- NCCL v2.32.3-1 `src/transport/net_ib/p2p_resiliency.cc`, `p2p_resiliency_recovery.cc`, `p2p.cc`, `common.cc`
