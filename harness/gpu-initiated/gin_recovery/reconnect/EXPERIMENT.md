# GIN 투명 복구 관리망 소켓 재연결 (gin-reconnect)

**목적:** GIN 투명 복구의 helper 소켓 오류를 "죽음", "모름", "증거 없음"으로 나누고 끊긴 소켓을 다시 연결한다. 그러면 관리망이
잠깐 끊긴 뒤에도 복구가 되는지, 끊김 중의 재시도 초과를 더 이상 "상대가 끊었다"로 판정하지 않는지, 정말 죽은 상대는 여전히
죽음으로 거절하는지를 사전 등록한 예측으로 잰다.

| 항목 | 값 |
|---|---|
| 상태 | `QA` |
| 담당자 | @unionxic |
| 작성일 | 2026-10-08 |
| 기준 브랜치와 커밋 | `exp/gin-reconnect` @ `90731cdb` (master) |
| 사전 등록 태그 | `prereg/gin-reconnect-v1` (상태를 `PREREGISTERED`로 바꾼 바로 그 커밋) |
| 마지막 갱신 | 2026-10-08 11:45, 본 실행과 채점 끝(상태 `QA`) |

표시: `[측정]` 원자료에서 확인, `[소스]` 코드에서 읽음, `[추론]` 해석, `[미확인]` 확인 안 함.

이 문서의 소스 줄 번호는 gin-s2-close 라이브러리 트리 기준이다. 그 트리는 pristine NCCL v2.32.3-1에
`../s2_close/gin_transparent_s2r.diff`를 적용한 것과 같다(세션 스크래치 `agent_ts2r/nccl-src`, libnccl `ba4984bd`).

장애 기호와 셀 이름은 원자료를 찾는 키로만 괄호나 표의 id 열에 둔다.

| 장애 | 기호 |
|---|---|
| 로컬 QP 오류 | F1 |
| 원격 접근 오류 | F2 |
| 상대 QP 오류 | F3 |
| 상대 프로세스 kill | F4 |

빌드 키는 두 가지다.

| 빌드 | 키 | 내용 |
|---|---|---|
| gin-s2-close 라이브러리 | `s2r` | libnccl `ba4984bd`와 최종 2단계 드라이버 `d4b1f082`(`$HOME/gi-bundle/gin_ts2/s2r/`). 같은 hold의 지연 기준으로만 쓴다 |
| 이 실험의 라이브러리 | `rc` | `s2r` 위에 9절의 재연결 변경을 더한 libnccl과 같은 드라이버 `d4b1f082`(`$HOME/gi-bundle/gin_ts2/rc/`, 새 디렉터리) |

## 1. 배경과 연구 질문

**바꾸기 전의 동작.** gin-s2-close가 같은 끊김 스위치로 쟀다 `[측정]`. 근거는
`../s2_close/results/20261007/SCORE.md`, `../s2_close/results/20261007/trials_scored.csv`, Release `data-20261007`이다.
- 두 rank의 helper 소켓에 8 s 동안 모든 세그먼트를 버리는 필터를 걸었다. 소켓은 끊김 시작 4 575–4 600 ms 뒤 ETIMEDOUT으로
  닫혔다(10회의 범위).
  - 뒤의 로컬 QP 오류는 10/10 "no helper socket to the peer"로 거절됐다. 투명 0/10이다.
- 30 s 끊김 중의 상대 QP 오류는 상대가 살아 있는데 10/10 "RETRY_EXC and the peer's socket shows FIN/RST"로 거절됐다. 소켓을
  닫은 원인은 10/10 ETIMEDOUT이었다.
- 1 s 끊김은 소켓을 닫지 않았다(0/5).
- 상대 프로세스 kill(끊김 없음)에서는 rank 0 소켓이 FIN으로 닫혔고 5/5 위와 같은 문구로 거절됐다.
- `MODEL.md` 규칙 3은 이 결과를 "살아 있는 상대를 잃은 것으로 판정하는 오판"으로 인용한다.

**원인** `[소스]`(`transport/net_ib/gdaki/gin_host_gdaki.cc`).
- `gdakiTsAlive`(2288–2296행)는 FIN과 모든 TCP 오류를 똑같이 "죽음"으로 본다.
- 쉬는 중 소켓이 닫히면 그 상대와의 복구를 끈다(3323–3330행).
- 수신 소켓은 준비가 끝나면 닫는다(3479행). 그래서 다시 연결할 길이 없다.
- 재시도 초과의 거절 문구는 원인과 상관없이 늘 "FIN/RST"다(3046행). 소켓이 없으면 "no helper socket to the peer"다(3052행).

**질문.**
1. 소켓 오류를 세 가지로 나누고 끊긴 소켓을 다시 연결하면, 관리망이 잠깐 끊긴 뒤의 로컬 QP 오류가 다시 투명하게 복구되는가.
2. 끊김 중의 재시도 초과는 더 이상 "상대가 끊었다"로 판정되지 않는가.
   - 끊김이 기다림 상한 안에 끝나면 복구되는가.
   - 상한을 넘으면 "상대 생존 모름"으로 거절되는가.
3. 정말 죽은 상대는 여전히 죽음으로 거절되는가. 끊김 없이 죽은 경우와 끊김 중에 죽은 경우를 본다.
4. 기존 복구, 거절, 받는 쪽 abort 해제가 그대로이고, 장애 없는 지연이 그대로인가.

## 2. 가설

| id | 가설 | 다음이 관측되면 틀린 것이다 |
|---|---|---|
| H1 | 시간 초과로 닫힌 소켓을 "모름"으로 두고 다시 연결하면, 끊김이 끝난 뒤의 로컬 QP 오류는 끊김이 없던 것처럼 투명하게 복구된다. 끊김과 재연결은 앱에 보이지 않는다 | 8 s 끊김 셀의 투명 복구가 9/10 미만이다. 또는 끊김이 끝난 뒤 1.5 s 안에 재연결되지 않은 시행이 2회 이상이다. 또는 장애 전에 비동기 오류가 나온다 |
| H2 | 끊김 중의 재시도 초과는 죽음으로 판정되지 않는다. 끊김이 기다림 상한(10 s) 안에 끝나면 복구되고, 넘으면 "상대 생존 모름"으로 거절된다 | 짧은 끊김 셀의 투명 복구가 9/10 미만이다. 또는 긴 끊김 셀에서 "모름" 거절이 9/10 미만이다. 또는 두 셀 어디서든 죽음 원인 문구로 거절된 시행이 있다 |
| H3 | 죽음의 증거(FIN, 연결 거부)가 있으면 여전히 죽음으로 거절되고, 상한까지 기다리지 않는다 | 끊김 없는 kill이 죽음 원인 문구로 거절되지 않는다. 또는 끊김 중 kill이 "모름"으로 거절되거나 복구된다. 또는 그 거절이 첫 분류 기록 뒤 2 s를 넘는다 |
| H4 | 재연결 변경은 기존 동작과 빠른 경로를 바꾸지 않는다 | 회귀 셀에서 투명하지 않은 시행이 나온다. 또는 받는 쪽 abort 해제가 회귀한다. 또는 지연 차이가 예측 범위 밖이다 |

## 3. 사전 예측 (측정 전에 작성)

예측 원문은 [predictions.csv](predictions.csv)이고, 해시는 [PREREG.txt](PREREG.txt)에 있다. 20줄이다.
`kind`는 N(새 셀), R(재현), C(대조)다. 아래 판정 열, 로그 형식, 셀 키, 판정식 문법은 지금 고정한다.

### 3.1 판정에 쓰는 열

시행마다 한 줄이다. 열은 세 곳에서 온다.
- `../scripts/ts2/rows.py`의 열.
- gin-s2-close의 `../s2_close/rows_extra.py`가 붙이는 열. 정의는 `../s2_close/EXPERIMENT.md` 3.1절 그대로다.
- 이 폴더의 `rows_rc.py`가 붙이는 새 열.

**앞의 두 곳에서 쓰는 열.** 의미는 원래 정의 그대로다 `[소스]`.

| 열 | 내용 |
|---|---|
| `cell`, `build`, `iters` | 셀 이름, 빌드, 반복 수 |
| `transparent_ok` | 1 또는 0 |
| `r0rc`, `r1rc`, `r0_outcome`, `r1_outcome` | rank별 종료 코드와 드라이버 결과 |
| `r0_async`, `r1_async` | 첫 비동기 오류. 없으면 `none` |
| `decl_r0` | rank 0의 거절 사유. 여럿이면 `;`로 잇는다 |
| `teardown_r0`, `teardown_r1`, `teardown_ms_r1` | `ncclCommAbort` 반환 문자열(성공은 `no error`)과 걸린 시간 |
| `lat_p50_us` | 지연 p50 |
| `n_fires_r0`, `n_fires_r1`, `trigger_miss`, `bind_fail`, `ts_on_r0`, `ts_on_r1`, `fault_mono_r0` | 장애 훅, 트리거, 랑데부 포트 충돌, 투명 복구 시작 줄, 장애 시각 |
| `ua_r0`, `ua_r1` | 받는 쪽 abort 플래그 줄 수 |
| `n_mute_on_r0`, `mute_on_ms_r0` | rank 0 끊김 시작 줄 수와 첫 줄 시각 |
| `n_sock_close_r0`, `sock_close_ms_r0`, `sock_close_cause_r0` | rank 0 소켓 닫힘 줄 수, 첫 줄의 시각과 원인 |
| `decl_mono_r0` | rank 0 첫 거절 줄의 시각 |
| `killed` | 상대 kill 기록이 있으면 1 |
| `async_before_fault` | 어느 rank든 첫 비동기 오류가 장애보다 앞서면 1 |
| `r1_alive_at_decline` | 거절 시각에 rank 1이 살아 있었으면 1 |

**`rows_rc.py`가 붙이는 열.** 새 로그 줄의 형식도 여기서 고정한다. 모든 시각은 `mono_ms`(CLOCK_MONOTONIC, ms)다.

| 열 | 출처와 정의 |
|---|---|
| `rc_mode_r0`, `rc_mode_r1` | rank별 WARN `GIN/TS: helper socket reconnect=<0\|1> bound_ms=<b> rank=<r>`(helper 시작 때 한 번)의 `reconnect` 값. 줄이 없으면 빈칸 |
| `sock_close_liveness_r0` | rank 0 첫 소켓 닫힘 줄의 `liveness` 값. 닫힘 줄 형식은 `GIN/TS: rank <r>: socket to rank <p> closed cause=<NAME> mono_ms=<t> liveness=<dead\|unknown>`이다(gin-s2-close 형식 뒤에 `liveness`를 더함) |
| `mute_off_ms_r0` | rank 0 첫 WARN `GIN/TS: TEST socket mute off rank=<r> peers=<n> mono_ms=<t>`의 `mono_ms` |
| `n_reconnect_r0`, `reconnect_ms_r0` | rank 0 WARN `GIN/TS: rank <r>: socket to rank <p> reconnected gen=<g> attempts=<n> mono_ms=<t>`의 줄 수와 첫 줄 `mono_ms` |
| `n_reconnect_r1` | rank 1의 같은 줄 수(받아들이는 쪽은 `attempts=0`) |
| `rc_wait_end_r0`, `rc_wait_ms_r0` | rank 0 첫 WARN `GIN/TS: rank <r>: reconnect wait for rank <p> ended=<reconnected\|dead\|bound\|off> wait_ms=<x> mono_ms=<t>`의 `ended`와 `wait_ms` |
| `q4_mono_r0` | rank 0 첫 "device-classified error CQE" 줄(장치 쪽 분류기의 기존 WARN)의 `mono_ms` |

**거절 사유 문구** `[소스, 9절의 변경으로 고정]`.

| 경우 | 문구 |
|---|---|
| 재시도 초과, 소켓이 죽음 | `RETRY_EXC and the peer's socket shows <CAUSE>`. `<CAUSE>`는 `FIN`, `ECONNRESET`, `EPIPE`, `ECONNREFUSED`, `BADMAGIC` 또는 그 밖의 errno 이름 |
| 재시도 초과, 소켓이 모름 | `RETRY_EXC and peer liveness unknown (<CAUSE>, no reconnect within <B> ms)`, 재연결을 끄면 `(<CAUSE>, reconnect off)` |
| 로컬 QP 오류, 소켓이 죽음 | `no helper socket to the peer (<CAUSE>)` |
| 로컬 QP 오류, 소켓이 모름 | `no helper socket to the peer: peer liveness unknown (<CAUSE>, no reconnect within <B> ms)`, 재연결을 끄면 `(<CAUSE>, reconnect off)` |

### 3.2 셀 키와 판정식 문법

셀 키(`cell@build`), 판정 대상(8절 제외를 거친 시행), "자료 부족" 규칙, 판정식 문법(`count`, 빈칸 규칙, `has`,
`nonempty`, `median`, `abs`, `per cell:`)은 `../s2_close/EXPERIMENT.md` 3.2절과 같다. 이 실험의 `score.py`는 그 구현
(`../s2_close/score.py`의 판정식 평가 함수)을 그대로 불러 쓴다. 판정은 맞음, 틀림, 자료 부족 중 하나다.

### 3.3 예측 요약

전체 판정식은 [predictions.csv](predictions.csv)에 있다. 아래는 요약이다.

| id | 셀 | 예측 | 판정 기준(요약) | 근거 |
|---|---|---|---|---|
| M1a | `rc_mute8_f1_b@rc` | 8 s 끊김 뒤 로컬 QP 오류가 투명하게 복구된다 | ≥9/10 | 바꾸기 전 0/10 `[측정]` |
| M1b | `rc_mute8_f1_b@rc` | 소켓이 시간 초과로 닫히고 "모름"으로 분류된다 | ≥9/10 | 바꾸기 전 원인 10/10 ETIMEDOUT `[측정]` |
| M1c | `rc_mute8_f1_b@rc` | 끊김이 끝난 뒤 1.5 s 안에 다시 연결된다 | ≥9/10 | 500 ms마다 다시 연결 시도(9절의 설계) |
| M1d | `rc_mute8_f1_b@rc` | 끊김과 재연결은 장애 전까지 앱에 알려지지 않는다 | 0/10 | 쉬는 중 소켓 처리는 오류를 올리지 않는다 `[소스]` |
| M2a | `rc_mutef3s_b@rc` | 상한 안에 끝나는 끊김 중의 상대 QP 오류가 투명하게 복구된다 | ≥9/10 | 재연결 뒤 같은 라운드 진행 |
| M2b | `rc_mutef3s_b@rc` | 시작 쪽은 재연결을 기다렸고, 기다림은 재연결로 끝났다(0–10 s) | ≥9/10 | 9절 |
| M3a | `rc_mutef3l_b@rc` | 상한을 넘는 끊김 중의 상대 QP 오류는 "상대 생존 모름"으로 거절된다 | ≥9/10 | 9절 |
| M3b | `rc_mutef3l_b@rc` | 죽음 원인 문구("the peer's socket shows")로 거절된 시행이 없다 | 0/10 | 바꾸기 전 10/10 "FIN/RST" `[측정]` |
| M3c | `rc_mutef3l_b@rc` | 거절은 첫 분류 기록 뒤 10.0–11.5 s에 온다 | ≥9/10 | 상한 10 s |
| M3d | `rc_mutef3l_b@rc` | 거절 시각에 rank 1은 살아 있다 | ≥9/10 | rank 1 수신 대기 30 s |
| M4a | `rc_mutekill_b@rc` | 끊김 중 kill된 상대는 재연결이 거부되어(ECONNREFUSED) 죽음으로 거절된다 | ≥9/10 | 수신 소켓이 사라진 포트는 RST로 답한다 `[추론]` |
| M4b | `rc_mutekill_b@rc` | "모름"으로 거절되거나 복구된 시행이 없다 | 0/10 | 9절 |
| M4c | `rc_mutekill_b@rc` | 거절은 첫 분류 기록 뒤 2 s 안에 온다(상한까지 기다리지 않음) | ≥9/10 | 9절 |
| G1 | 회귀 셀 여섯 개(`f1_b`, `f3_b`, `f1g0_b`, `mt256_f1_b`, `bidirf_f1both_b`, `bidirf_sym_b`, 모두 `@rc`) | 복구 결과가 그대로다 | 셀마다 5/5 투명 | gin-s2-close 새 라이브러리 25/25 `[측정]` |
| G2 | `f4_b@rc` | 끊김 없는 kill은 죽음 원인(FIN 또는 ECONNRESET)으로 거절되고 살아남은 쪽 abort가 돌아온다 | 5/5 | 바꾸기 전 원인 FIN 5/5 `[측정]` |
| G3 | `f2rel_b@rc` | 받는 쪽 abort 해제가 그대로다 | 5/5 | gin-s2-close 10/10 `[측정]` |
| C1 | `rc_mute1_f1_b@rc` | 1 s 끊김은 소켓을 닫지 않고 재연결도 없으며 복구는 투명하다 | 5/5 | 바꾸기 전 0/5 닫힘 `[측정]` |
| C2 | `rc_mute8off_b@rc` | 재연결을 끄면 8 s 끊김 뒤 로컬 QP 오류는 "no helper socket"으로 거절된다 | 5/5 | 바꾸기 전과 같은 동작 |
| L1 | `lat_rc_on_4k@rc` 대 `lat_s2r_on_4k@s2r` | 4 KiB 지연 차이 0.40 µs 이하 | 같은 hold의 실행 중앙값 | 장치 코드가 같다 `[소스]` |
| L2 | `lat_rc_on_256k@rc` 대 `lat_s2r_on_256k@s2r` | 256 KiB 지연 차이 0.30 µs 이하 | 같음 | 같음 |

셀 조건은 7절에 있다.

## 4. 범위

**포함.**
- 9절의 라이브러리 변경 하나(helper 소켓의 세 가지 분류, 다시 연결, 기다림 상한, 원인을 담은 거절 문구).
- 끊김 스위치를 새로 만든 소켓(다시 연결하는 소켓, 수신 소켓)에도 적용하는 확장.
- 7절의 셀 18개.
  - 새 셀 4개: 8 s 끊김 뒤 로컬 QP 오류, 짧은 끊김 중 상대 QP 오류, 긴 끊김 중 상대 QP 오류, 끊김 중 kill.
  - 회귀 셀 8개.
  - 대조 셀 2개.
  - 지연 셀 4개.

**제외.**
- 라운드 도중(REQ, ACK, DONE을 주고받는 중) 소켓이 끊긴 경우의 재연결: 지금처럼 그 라운드를 거절한다. 거절 문구에는 원인만 더한다.
- 거절한 뒤 다시 연결해서 상대에게 FAIL을 늦게라도 알리는 일: 다음 작업이다.
- 장애 난 QP 쌍만 재설정(설계 문서 항목 C3): 이 실험이 끝난 뒤 따로 한다.
- 실제 관리망 장애(iptables, 링크 내리기, 라우팅 변경): 하지 않는다. 끊김은 우리 프로세스 소켓에 붙이는 필터로만 만든다.
- RoCE 주소 변경, 3 rank 이상, 여러 GDAKI 문맥.

## 5. 테스트베드와 버전

| 항목 | 값 | 확인 방법과 날짜 |
|---|---|---|
| 노드 | rain(rank 0, 보내는 쪽, 낮은 rank라서 다시 거는 쪽), sunny(rank 1, 받는 쪽) | 루트 `README.md` 테스트베드 표 |
| NIC와 펌웨어 | ConnectX-6 VPI, fw 20.43.4100. rain `mlx5_1`, sunny `mlx5_0` | `[측정]` 2026-10-06, `../../completion_contract/EXPERIMENT.md` 5절. hold 스냅숏에서 다시 기록 |
| 커널, OFED | rain 커널 5.15.0-97-generic. OFED | 커널 `[측정]` 2026-10-07. OFED `[미확인]` |
| GPU와 CUDA | rain Quadro RTX 5000(sm_75), sunny RTX A4000(sm_86), PeerMappingOverride=1, CUDA 12.8 | gin-s2-close 5절 |
| 기준 라이브러리 `s2r` | libnccl `ba4984bd`, 드라이버 `d4b1f082` | `[측정]` 2026-10-07 배포 때 두 노드 같음(`../s2_close/deploy_check.txt`) |
| 이 실험의 라이브러리 `rc` | libnccl `8354411f198e9d980b8b3459918afbea`, 드라이버 `d4b1f082e3e3150d8ceff7313475e6aa`(`$HOME/gi-bundle/gin_ts2/rc/`). 변경분 [rc_layer.diff](rc_layer.diff)(md5 `fb72ffd3`), pristine 기준 전체 diff [gin_transparent_rc.diff](gin_transparent_rc.diff)(md5 `411919a4`). smoke 1에만 쓴 빌드는 libnccl `1193a5f8`(`rc_smoke_1193a5f8/`) | `[측정]` 2026-10-08 배포 때 두 노드 md5 같음, 기존 번들 18개 파일 md5 그대로([deploy_check.txt](deploy_check.txt)). pristine v2.32.3-1에 전체 diff를 적용하면 빌드 트리와 같다 `[측정]`([make_diff_rc.sh](make_diff_rc.sh)) |

## 6. 변수

- **독립변수.**
  - 빌드: `s2r`, `rc`.
  - 재연결 스위치 `NCCL_GIN_TS_RECONNECT`(1 기본, 0).
  - 끊김 길이와 시작 시각.
  - 장애 종류와 시각(로컬 QP 오류, 상대 QP 오류, 원격 접근 오류, 상대 프로세스 kill).
- **종속변수.** 3.1의 열이다.
  - 투명 여부, 거절 사유.
  - 소켓 닫힘 원인과 분류, 재연결 시각, 시작 쪽이 재연결을 기다린 시간과 끝난 이유.
  - 장애 전 비동기 오류, 거절 시각에 상대가 살아 있었는지.
  - 지연 p50.
- **통제변수.**
  - IB 타임아웃 14, GPU doorbell.
  - 기존 셀 정의는 `../scripts/ts2/batch.sh`와 `../s2_close/cells.sh` 그대로다.
  - 끊김 셀은 gin-s2-close의 끊김 셀과 크기(16 KiB × 1000, 15 ms 간격), 끊김 시작, 장애 시각을 맞췄다.
  - 시행마다 프로세스를 새로 띄운다.
  - 기다림 상한 `NCCL_GIN_TS_RECONNECT_MS`는 기본 10 000 ms로 둔다.

## 7. 실험 셀, 반복 수, 대조군

반복 수는 사전 등록 규칙(새 셀 10, 재현 5, 대조 5)을 따른다. 지연 셀의 반복은 실행 수다(실행마다 3000번 반복).
끊김 스위치 `NCCL_GIN_TS_TEST_SOCK_MUTE=<시작 ms>:<길이 ms>`는 두 rank에 건다. 시각은 각 rank의 helper 시작부터 잰다. gin-s2-close 끊김 셀 25회에서
끊김 시작 줄은 devComm 생성 기준으로 설정보다 0–15 ms 일렀다 `[측정]`. 장애 훅 시각은 devComm 생성부터, kill 시각(`KILL_DELAY_MS`)은 실행기가 rank 1을 띄운 때부터 잰다.
gin-s2-close 상대 kill 5회에서 kill은 `KILL_DELAY_MS`보다 462–565 ms 이르게(devComm 생성 기준) 일어났다 `[측정]`.

| 셀 | 조건 | 반복 수 | 대조군 여부 |
|---|---|--:|---|
| `rc_mute8_f1_b@rc` | 끊김 500:8000, 로컬 QP 오류 12 000 ms, 16 KiB × 1000, `GIN_TS_RX_WAIT_S=10`, `ABORT_WD_S=20`, `WATCHDOG_S=60` | 10 | 새 셀 |
| `rc_mutef3s_b@rc` | 끊김 300:12000(상한 안에 끝남), 상대 QP 오류 6000 ms, 16 KiB × 1000, `GIN_TS_RX_WAIT_S=30`, `ABORT_WD_S=20`, `WATCHDOG_S=60` | 10 | 새 셀 |
| `rc_mutef3l_b@rc` | 끊김 300:30000(상한을 넘음), 상대 QP 오류 6000 ms, 16 KiB × 1000, `GIN_TS_RX_WAIT_S=30`, `ABORT_WD_S=40`, `WATCHDOG_S=60` | 10 | 새 셀 |
| `rc_mutekill_b@rc` | 끊김 300:8000, 상대 프로세스 kill(`KILL_DELAY_MS=6550`, devComm 생성 뒤 약 6.0 s), 16 KiB × 1000, `GIN_TS_RX_WAIT_S=10`, `ABORT_WD_S=20`, `WATCHDOG_S=60` | 10 | 새 셀 |
| `f1_b@rc`, `f3_b@rc`, `f1g0_b@rc`, `mt256_f1_b@rc`, `bidirf_f1both_b@rc`, `bidirf_sym_b@rc` | `batch.sh`의 기존 정의 | 각 5 | 재현 |
| `f4_b@rc` | `batch.sh`의 기존 정의(끊김 없는 kill) | 5 | 재현 |
| `f2rel_b@rc` | `../s2_close/cells.sh`의 `f2rel_b`와 같은 조건(원격 접근 오류, 받는 쪽 abort 해제), 빌드만 `rc` | 5 | 재현 |
| `rc_mute1_f1_b@rc` | 끊김 500:1000, 로컬 QP 오류 3000 ms, 16 KiB × 300 | 5 | 대조 |
| `rc_mute8off_b@rc` | `rc_mute8_f1_b`와 같고 `NCCL_GIN_TS_RECONNECT=0` | 5 | 대조 |
| `lat_s2r_on_4k@s2r`, `lat_s2r_on_256k@s2r` | `../s2_close/cells.sh`의 정의. 아래 두 셀과 같은 hold에서 섞어 돈다 | 각 5 | 재현(지연 기준) |
| `lat_rc_on_4k@rc`, `lat_rc_on_256k@rc` | 투명 복구 켬, 장애 없음, 3000번 반복 | 각 5 | 대조 |

**합계.**

| 종류 | 셀 시행 | 지연 실행 |
|---|--:|--:|
| 새 셀 | 40 | |
| 재현 | 40 | 10 |
| 대조 | 10 | 10 |
| 합 | 90 | 20 |

## 8. 제외 기준과 중단 기준

**제외 기준.** 제외한 시행은 셀별로 따로 세어 보고한다.
- smoke 실행(`results/<날짜>_smoke/`)은 채점하지 않는다.
- NCCL 초기화 전 실패(`bind_fail == 1`)는 제외하고 다음 번호로 계획한 반복 수를 채운다.
- 장애 미적용은 제외하고 다음 번호로 채운다. 해당하는 경우는 다음과 같다.
  - 로컬 QP 오류 셀에서 `n_fires_r0 == 0`.
  - 상대 QP 오류 셀에서 `n_fires_r1 == 0`.
  - `trigger_miss > 0`.
  - kill 셀에서 `killed != 1`.
- 순서 미적용은 제외하고 다음 번호로 채운다. 끊김 중 상대 QP 오류 두 셀과 끊김 중 kill 셀(`rc_mutef3s_b`, `rc_mutef3l_b`,
  `rc_mutekill_b`)에서, rank 0의 소켓 닫힘 줄이 없거나 첫 분류 기록이 소켓 닫힘보다 앞선 경우다
  (`q4_mono_r0 < sock_close_ms_r0`). 이 셀들의 조건은 "소켓이 이미 닫힌 뒤의 장애"이기 때문이다.
- 채우려고 다시 돈 시행이 셀마다 계획의 50%를 넘으면 그 셀은 멈추고 "자료 부족"으로 둔다.

**설정 확인.** 하나라도 어긋나면 제외가 아니라 그 블록을 멈춘다.
- 투명 복구를 켠 `rc`, `s2r` 시행은 `ts_on_r0 >= 1`, `ts_on_r1 >= 1`, `ua_r0 >= 1`, `ua_r1 >= 1`이어야 한다.
- `rc` 시행은 `rc_mode_r0`, `rc_mode_r1`이 재연결을 끈 대조 셀(`rc_mute8off_b`)에서는 0, 나머지에서는 1이어야 한다.
- 끊김 셀은 `n_mute_on_r0 >= 1`이어야 한다.

**smoke에서 재연결이 동작하지 않을 때.** smoke의 8 s 끊김 2회 모두에서 재연결 줄이 없으면 구현 결함으로 본다. 본 실행 전에 코드를
고칠 수 있고, 그 변경은 `DEVIATIONS.md`에 적는다. 예측, 판정식, 셀 조건은 바꾸지 않는다.

**중단 기준.**
- **잠금.** 모든 클러스터 명령은 `harness/gpu-initiated/common/cluster_run.sh -w 10800` 안에서 돈다. 다른 실험이 같은 잠금을 쓴다.
  - 10 800 s 안에 잠금이나 유휴 링크를 얻지 못하면(종료 코드 75) 그 hold를 미룬다.
  - `prio-` 작업에는 양보한다.
  - hold 하나는 15분 이하이고 `timeout -s KILL 880`으로 묶는다.
- **하지 않는 것.** 실제 link down이나 flap, 재부팅, 드라이버 재적재, 커널 모듈 적재, RoCE 주소 변경, iptables 같은 방화벽 변경.
  - 관리망 끊김은 우리 프로세스의 소켓에 붙이는 필터로만 만든다.
- **프로세스.** 우리가 띄운 프로세스만 정확한 이름(`pkill -x gin_ts2`)이나 PID로 끈다.
  - 다른 사용자의 작업은 건드리지 않는다. 예: gds-kv, NVMe-oF, gdsio, mooncake, `prio-` 작업.
  - `left > 0`이 두 시행 연속이면 멈춘다.
- **mlx5 오류.** rain `mlx5_1`은 펌웨어 명령 슬롯 하나가 새어 있다. hold 앞뒤에 스냅숏을 남긴다. 다음 중 하나가 보이면 그 hold
  뒤로 멈추고 12절에 기록한다.
  - 두 노드 dmesg에 새 mlx5 명령 오류 줄이 생겼다. 명령 오류 줄은 `mlx5`와 함께 `cmd` 또는 `command`, 그리고 `failed`,
    `timeout`, `leak` 중 하나를 담은 줄이다.
  - rain debugfs의 명령 실패 계수(`failed`, `failed_mbox_status`)가 늘었다.

  rain에는 이 실험 전부터 명령 오류 줄 2개(2026-09-25)가 있으므로 hold 앞뒤의 증가로 판단한다.
- **배포.** 새 번들은 새 디렉터리 `$HOME/gi-bundle/gin_ts2/rc/`에만 둔다.
  - 대상 파일이 이미 있으면 배포 스크립트가 멈춘다.
  - 배포 뒤 기존 번들 파일(최종, `s1/`, `base/`, `var_sys/`, `s2r/`, `s2rget/`)의 md5가 두 노드에서 그대로인지 확인한다.

## 9. 실행 방법과 경로

**코드 변경.** 아직 하지 않았고 빌드도 하지 않았다. 사전 등록 뒤에 한다. 대상은 `src/transport/net_ib/gdaki/gin_host_gdaki.cc`
하나다(헤더와 장치 코드는 그대로). 변경분은 `rc_layer.diff`(`s2r` 트리 기준)와 전체 diff `gin_transparent_rc.diff`(pristine
기준)로 남긴다.
1. **소켓 상태.**
   - `gdakiTsPeer`에 상태(연결, 모름, 죽음), 원인 문자열, 세대 번호, 소켓을 잃은 시각, 다시 걸기 상태를 더한다.
   - 위쪽 rank의 수신 주소는 준비 때 모은 값을 보관한다.
2. **수신 소켓 유지.** `gdakiTsSetup`은 수신 소켓을 닫지 않고 helper가 끝날 때까지 둔다(지금은 3479행에서 닫는다).
3. **HELLO.**
   - `arg`에 문맥 번호를, `round`에 세대 번호를 싣는다. 문맥 번호는 helper를 만든 순서로, 모든 rank에서 같다.
   - 처음 연결은 세대 0이다.
   - 위쪽 rank는 세 조건이 맞을 때만 받아들인다: 보낸 rank가 자기보다 낮다, 문맥 번호가 같다, 세대가 지금보다 크다.
4. **세 가지 분류.**
   - 죽음: FIN, ECONNRESET, EPIPE, 다시 걸 때의 ECONNREFUSED, BADMAGIC, 아래에 없는 errno.
   - 모름: ETIMEDOUT, EHOSTUNREACH, ENETUNREACH.
   - 증거 없음: EAGAIN, EWOULDBLOCK, EINTR.
   - 쉬는 중 소켓을 잃으면 닫힘 줄(3.1 형식, `liveness`)을 남긴다. 죽음이면 지금처럼 그 상대와의 복구를 끈다. 모름이면 소켓을
     닫고 다시 연결을 기다린다.
5. **다시 걸기.**
   - 낮은 rank가 500 ms마다 비차단 connect를 새로 시작한다. 한 번의 시도는 500 ms로 묶는다.
   - 연결되면 HELLO(세대 + 1)를 보내고 연결 상태로 돌아간다. 다시 걸기가 거부되면(ECONNREFUSED) 죽음으로 바꾼다.
   - 위쪽 rank는 helper 루프에서 수신 소켓을 poll해 받아들이고 HELLO를 확인한다. 옛 소켓은 닫는다.
   - 성공하면 두 rank가 재연결 줄(3.1)을 남긴다.
   - 이 일은 `gdakiTsMain` 루프와 아래 기다림 루프가 함께 한다.
6. **`gdakiTsInitiate`의 정책.** 재시도 초과와 로컬 QP 오류 모두에 적용한다.
   - 증거 없음이면 지금처럼 라운드를 시작한다.
   - 죽음이면 3.1의 죽음 문구로 거절한다.
   - 모름이면 재연결을 `NCCL_GIN_TS_RECONNECT_MS`(기본 10 000, 시작 때 `holdMs − handshakeMs − 1000`으로 자르고 WARN)까지
     기다린다.
     - 기다리는 동안 heartbeat를 새로 쓰고 다시 걸기를 진행한다. 기다림은 라운드 시작 전이라 라운드 상한에 들지 않는다.
     - 재연결되면 라운드를 시작한다. 그 핸드셰이크가 상대 생존의 증거다.
     - 죽음의 증거가 오면 죽음 문구로 거절한다.
     - 상한에 닿으면 "peer liveness unknown" 문구로 거절한다.
     - 끝날 때 기다림 줄(3.1)을 남긴다.
   - `NCCL_GIN_TS_RECONNECT=0`이면 다시 걸지 않는다. 모름 상태의 장애는 바로 `reconnect off` 문구로 거절한다(`ended=off`).
7. **문구.** 재시도 초과의 거절 문구에서 늘 "FIN/RST"이던 것을 실제 원인으로 바꾼다. 라운드 도중의 소켓 오류 문구에도 원인을
   괄호로 더한다. 동작은 그대로다.
8. **끊김 스위치.** 끊는 동안에는 필터를 기존 소켓뿐 아니라 수신 소켓과 새로 만드는 다시 걸기 소켓에도 붙인다. 끝날 때 모두에서
   뗀다. 그래야 끊김 중의 다시 걸기도 실패한다(시험 전용).
9. **시작 줄과 정리.**
   - helper 시작 때 `GIN/TS: helper socket reconnect=<0|1> bound_ms=<b> rank=<r>`를 남긴다.
   - `gdakiTsStop`은 수신 소켓과 다시 걸기 소켓도 닫는다.

**빌드.** 세션 스크래치 `$SCR`(`/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad`)에서 한다.
1. `agent_ts2r`의 트리와 빌드 디렉터리를 `agent_ts2rc`로 복사한다. 의존 파일과 장치 manifest의 경로를 바꾸고 원래 시각을
   돌려준다(gin-s2-close `build_s2r.sh`와 같은 방식).
2. 스크래치 저장소에 `s2r` 상태를 커밋하고 `rc_layer.diff`를 적용한다.
3. `make -n`으로 다시 컴파일되는 파일이 `gin_host_gdaki.cc`와 버전 표시뿐인지 확인한 뒤 증분 빌드한다.
4. 드라이버는 새로 빌드하지 않고 최종 드라이버 `d4b1f082`를 복사한다.

이 폴더에 둘 스크립트는 `build_rc.sh`, `make_diff_rc.sh`, `deploy_rc.sh`다.

**배포.** `deploy_rc.sh`로 두 노드의 `$HOME/gi-bundle/gin_ts2/rc/`에 둔다. 대상 파일이 있으면 멈추고, 두 노드 md5, `ldd`, 기존
번들 md5를 확인한다(8절).

**실행.**
- `../scripts/ts2/run_trial.sh`를 그대로 쓴다(`BUILD=rc`).
- 기존 셀은 `BUILD=rc bash ../scripts/ts2/batch.sh`로, `s2r` 지연 셀은 `../s2_close/cells.sh`로 돈다.
- 새 셀, 대조 셀, `rc` 지연 셀, `f2rel_b@rc`는 이 폴더의 `cells.sh`가 7절 조건대로 정의한다.
- hold는 이 폴더의 `hold.sh`에 두고, 각 hold를 `chain.sh`로 따로 `cluster_run.sh -w 10800 -t grc-<hold>`에 넣는다.

| hold | 내용 | 추정 `[추론]` |
|---|---|---|
| H0 smoke | 새 셀과 대조 셀마다 1회, 8 s 끊김 2회, 지연 1회씩, 설정 확인 | 6분 |
| H1 | 지연 4셀 × 5(섞어서), 회귀 셀 8개 × 5 | 8분 |
| H2 | 8 s 끊김 10회, 1 s 대조 5회, 재연결 끈 대조 5회 | 8분 |
| H3 | 짧은 끊김 중 상대 QP 오류 10회, 끊김 중 kill 10회 | 8분 |
| H4 | 긴 끊김 중 상대 QP 오류 10회 | 7분 |

hold마다 잠금과 유휴 확인이 약 1분 더 든다. 클러스터 시간은 모두 40–50분이다 `[추론]`.

**채점.**
1. `../scripts/ts2/rows.py`로 hold 폴더마다 시행 CSV를 만든다.
2. `../s2_close/rows_extra.py`와 이 폴더의 `rows_rc.py`가 3.1의 열을 붙인다.
3. 이 폴더의 `score.py`가 [predictions.csv](predictions.csv)의 판정식을 3.2 문법대로 적용한다. 결과는
   `results/<날짜>/SCORE.md`와 `results/<날짜>/trials_scored.csv`다.

**출력.** 결과 폴더 `results/<날짜>/<hold 폴더>/`. 원시 로그는 Release에 올린다.

## 10. 완료 조건과 QA 기준

- [x] 모든 셀이 계획한 반복 수만큼 실행됐다. 제외와 실패를 따로 센 표가 있다.
- [x] 예측 20줄마다 판정(맞음, 틀림, 자료 부족)과 놓친 시행 목록이 있다.
- [ ] 다른 에이전트가 `score.py`를 보지 않고 원자료에서 핵심 수치를 다시 셌다. 대상은 재연결 시각, 기다림 시간, 거절 사유,
  투명 여부다.
- [ ] 다른 에이전트가 `rc_layer.diff`를 읽고 리뷰했다.
- [x] smoke와 제외 시행이 결과에 섞이지 않았다.
- [x] 새 빌드의 md5, 전체 diff, pristine + diff 확인 결과를 5절에 적었다.
- [ ] 원자료를 Release에 올리고 `DATA.md`에 적었다.
- [x] hold 전후 mlx5 스냅숏에 새 명령 오류가 없었거나, 있었다면 12절에 적었다.

## 11. 작업 체크리스트

- [x] 질문, 가설, 셀 작성 (`DRAFT`)
- [x] 고정 절 완성, 상태 `PREREGISTERED`, 해시 기록을 커밋 하나로 만들고 그 커밋에 `prereg/` 태그
- [x] 코드 변경, 빌드, 배포
- [x] `cells.sh`, `hold.sh`, `chain.sh`, `rows_rc.py`, `score.py`
- [x] smoke 실행(채점 제외)
- [x] 본 실행 (`RUNNING`)
- [x] 채점 (`QA`)
- [ ] 독립 재계산과 코드 리뷰
- [ ] 결과 정리, 원자료 릴리스, PR
- [ ] 결론 확정 (`COMPLETE`)

## 12. 실행 기록 (시간순)

| 시각 | 무엇을 했나 | 결과와 근거(경로, 커밋, 실행 ID) |
|---|---|---|
| 2026-10-08 | gin-s2-close의 원자료(Release `data-20261007`)에서 시각의 기준을 셈 `[측정]`. 상대 kill 5회에서 kill은 `KILL_DELAY_MS`보다 462–565 ms 이르게(devComm 생성 기준) 일어났다. 끊김 셀 25회에서 끊김 시작 줄은 설정 시각보다 0–15 ms 이르게(devComm 생성 기준) 찍혔다 | sha256 앞 12자 `f2d11a86cc83`, 7절 |
| 2026-10-08 | 사용자가 이 후속 실험을 승인 | |
| 2026-10-08 10:35:21 | 사전 등록 | [PREREG.txt](PREREG.txt), 태그 `prereg/gin-reconnect-v1` |
| 2026-10-08 10:36–10:43 | 재연결 계층 작성(`gin_host_gdaki.cc` 한 파일), 증분 빌드(다시 컴파일된 파일은 `gin_host_gdaki.cc`와 버전 표시뿐), 두 노드 배포(libnccl `1193a5f8`) | [build_rc.sh](build_rc.sh), [deploy_check_smoke1.txt](deploy_check_smoke1.txt) |
| 2026-10-08 10:45:18–10:49:02 | smoke 1(`grc-H0`), 12회, 채점 제외. 8 s 끊김 뒤 로컬 QP 오류는 다시 연결되어 투명했다(1회, 다른 1회는 랑데부 포트 충돌). 긴 끊김은 "peer liveness unknown", 끊김 중 kill은 "shows ECONNREFUSED", 끊김 없는 kill은 "shows FIN", 재연결 끈 대조는 "no helper socket to the peer: ...reconnect off"로 거절됐다. 짧은 끊김 중 상대 QP 오류는 rank 0의 끊김이 끝나지 않아(시험 스위치 결함) 상한까지 기다린 뒤 거절됐다 `[측정]`. 새 mlx5 줄 0 | `results/20261008_smoke/smoke/`, `hold_H0.out` |
| 2026-10-08 10:50 | 시험 스위치 결함을 고쳐 다시 빌드(libnccl `8354411f`), smoke 1 번들은 `rc_smoke_1193a5f8/`로 옮기고 새 `rc/`에 배포. 전체 diff로 트리 재현 확인 | [DEVIATIONS.md](DEVIATIONS.md) 2절, [deploy_check.txt](deploy_check.txt), [gin_transparent_rc.diff](gin_transparent_rc.diff), [rc_layer.diff](rc_layer.diff) |
| 2026-10-08 10:52:12–10:54:42 | smoke 2(`grc-H0b`), 끊김 셀 7회, 채점 제외. 짧은 끊김 중 상대 QP 오류 2회 모두 끊김이 끝난 뒤 다시 연결되어(기다림 2 900, 2 950 ms) 투명했다. 나머지 다섯 셀도 smoke 1과 같은 결과다 `[측정]`. 새 mlx5 줄 0 | `results/20261008_smoke/smoke2/`, `hold_H0b.out` |
| 2026-10-08 10:56 | 본 실행 시작(상태 `RUNNING`). H1–H4를 [chain.sh](chain.sh)로 차례로 잡는다(`cluster_run.sh -w 10800`, 태그 `grc-H<k>`) | `results/20261008/chain.out` |
| 2026-10-08 11:02:18–11:08:04 | H1(`grc-H1`, 잠금은 다른 실험 뒤 11:01:47): 지연 20회(`rc`와 `s2r` 섞어서), 회귀 셀 40회(여섯 개 셀, 끊김 없는 kill, 받는 쪽 abort 해제). 상대 QP 오류 1회(n2)가 드라이버 랑데부 포트 충돌로 시작하지 못해 제외, 나중에 채운다. mlx5 명령 오류 줄(rain 2, sunny 0)과 펌웨어 명령 실패 수(31)는 전후가 같고 새 mlx5 줄은 0이다 | `results/20261008/lat/`, `results/20261008/rep_rc/`, `hold_H1.out`, `mlx5_new_H1.txt` |
| 2026-10-08 11:13:41–11:19:27 | H2(`grc-H2`, 잠금 11:13:10): 8 s 끊김 뒤 로컬 QP 오류 10회는 모두 소켓이 "모름"으로 닫힌 뒤 끊김이 끝나고 다시 연결되어 투명했다. 1 s 끊김 5회는 소켓이 닫히지 않고 투명했다. 재연결을 끈 대조 5회는 모두 "no helper socket to the peer: peer liveness unknown (ETIMEDOUT, reconnect off)"로 거절됐다 `[측정]`. 시작 실패 0. mlx5 명령 오류 줄(rain 2, sunny 0)과 펌웨어 명령 실패 수(31)는 전후가 같고 새 mlx5 줄은 0이다 | `results/20261008/mute/`, `hold_H2.out`, `mlx5_new_H2.txt` |
| 2026-10-08 11:24:36–11:31:03 | H3(`grc-H3`, 잠금 11:24:05): 짧은 끊김 중 상대 QP 오류 10회는 모두 rank 0이 재연결을 기다렸고(기다림 끝 `reconnected`) 투명했다. 끊김 중 kill 10회는 모두 소켓이 먼저 ETIMEDOUT("모름")으로 닫히고, 끊김이 끝난 뒤 다시 걸기가 ECONNREFUSED("죽음")를 받고, 분류 기록 뒤 "RETRY_EXC and the peer's socket shows ECONNREFUSED"로 거절됐다 `[측정]`. 시작 실패 0. mlx5 명령 오류 줄(rain 2, sunny 0)과 펌웨어 명령 실패 수(31)는 전후가 같고 새 mlx5 줄은 0이다 | `results/20261008/mute/`, `hold_H3.out`, `mlx5_new_H3.txt` |
| 2026-10-08 11:31:34–11:37:47 | H4(`grc-H4`, 잠금 11:31:03): 긴 끊김 중 상대 QP 오류 10회 중 9회는 소켓이 ETIMEDOUT("모름")으로 닫힌 뒤 rank 0이 상한까지 기다리고(기다림 끝 `bound`) 거절됐다 `[측정]`. 1회(n10)는 드라이버 랑데부 포트 충돌로 시작하지 못해 제외, 나중에 채운다. mlx5 명령 오류 줄(rain 2, sunny 0)과 펌웨어 명령 실패 수(31)는 전후가 같고 새 mlx5 줄은 0이다 | `results/20261008/mute/`, `hold_H4.out`, `mlx5_new_H4.txt` |
| 2026-10-08 11:38:49–11:39:34 | 채우기 hold(`grc-fill`, 잠금 11:38:18): 제외한 두 시행을 다음 번호로 채웠다. 상대 QP 오류 n6은 투명, 긴 끊김 중 상대 QP 오류 n11은 상한까지 기다린 뒤 "peer liveness unknown"으로 거절됐다 `[측정]`. 두 셀 모두 다시 돈 시행은 1회로 계획의 50% 이하다. mlx5 명령 오류 줄(rain 2, sunny 0)과 펌웨어 명령 실패 수(31)는 전후가 같고 새 mlx5 줄은 0이다 | `results/20261008/rep_rc/`, `results/20261008/mute/`, `hold_fill.out`, `mlx5_new_fill.txt` |
| 2026-10-08 11:40 | 채점(`python3 score.py results/20261008`). 시행 112, 판정 110, 제외 2(둘 다 랑데부 포트 충돌). 예측 20개 모두 맞음. 상태 `QA` | [results/20261008/SCORE.md](results/20261008/SCORE.md), [results/20261008/trials_scored.csv](results/20261008/trials_scored.csv) |

## 13. 사전 등록 이후 변경

> 기존 문장을 고치지 않고 여기에 덧붙인다. 변경이 많으면 `DEVIATIONS.md`에 두고 링크한다.

사전 등록 내용은 바꾸지 않았다. smoke에서 찾아 고친 시험 스위치 결함과 구현 세부는 [DEVIATIONS.md](DEVIATIONS.md)에 적었다.

| 날짜 | 무엇을 | 이유 | 영향 범위 | 커밋 |
|---|---|---|---|---|
| 2026-10-08 | 끊김 시험 스위치의 일정이 재연결 기다림 중에도 돌게 고침, 빌드를 다시 하고 새 `rc/`에 배포 | smoke 1에서 짧은 끊김 셀의 조건이 만들어지지 않았다 | 시험 스위치뿐, 예측과 셀 조건은 그대로 | `4dd52754` |

## 14. 원자료와 결과표

| 무엇 | 경로 또는 Release 자산 | n |
|---|---|--:|
| 채점 결과(예측별 판정, 대입한 식, 셀별 시행 수와 제외) | [results/20261008/SCORE.md](results/20261008/SCORE.md) | 예측 20 |
| 시행별 판정 열(3.1의 열 전부와 `status`) | [results/20261008/trials_scored.csv](results/20261008/trials_scored.csv) | 112행(판정 110, 제외 2) |
| 끊김 셀 시행 로그(rank별 로그, kv, meta, kill 기록) | `results/20261008/mute/`, Release 예정 | 51 |
| 회귀 셀 시행 로그 | `results/20261008/rep_rc/`, Release 예정 | 41 |
| 지연 실행 로그와 반복별 지연 | `results/20261008/lat/`, Release 예정 | 20 실행 |
| hold 기록과 mlx5, 펌웨어 명령 스냅숏 | `results/20261008/`의 `chain.out`, `hold_*.out`, `snap_*`, `mlx5_*`, `fwcmd_*`, Release 예정 | hold 5(H1–H4, 채우기) |
| smoke(채점 제외) | `results/20261008_smoke/`, Release 예정 | 19(smoke 1 12회, smoke 2 7회) |
| 빌드와 배포 | [rc_layer.diff](rc_layer.diff), [gin_transparent_rc.diff](gin_transparent_rc.diff), [deploy_check.txt](deploy_check.txt), 사전 등록 이후 변경 [DEVIATIONS.md](DEVIATIONS.md) | |

## 15. 결과 요약

> 예측별 판정과 핵심 수치. 수치마다 n과 근거 링크를 붙인다. 아직이면 `[미확인]`.

**판정.** 예측 20개가 모두 맞았다 `[측정]`. 근거는 [results/20261008/SCORE.md](results/20261008/SCORE.md)다. 판정한 시행은 110회다.
제외 2회는 둘 다 드라이버 랑데부 포트 충돌로 시작하지 못한 시행(`f3_b_n2`, `rc_mutef3l_b_n10`)이고, 채우기 hold에서 다음 번호로
채웠다. smoke 19회는 따로 셌고 채점하지 않았다. 아래 범위와 중앙값은 [trials_scored.csv](results/20261008/trials_scored.csv)의
열에서 셌다(`score.py`가 원시 로그에서 만든 열). 끊김 중 kill의 ECONNREFUSED 시각만 rank 0 로그의 닫힘 줄에서 직접 셌다.
다른 에이전트의 독립 재계산은 아직이다(16절).

| 질문 | 예측 | 결과 `[측정]` | n | 판정 | id |
|---|---|---|--:|---|---|
| 잠깐 끊긴 뒤 복구 | 8 s 끊김 뒤 로컬 QP 오류가 투명하게 복구된다 | 10/10 투명 | 10 | 맞음 | M1a |
| 잠깐 끊긴 뒤 복구 | 소켓이 시간 초과로 닫히고 "모름"으로 분류된다 | 10/10 ETIMEDOUT, `liveness=unknown` | 10 | 맞음 | M1b |
| 잠깐 끊긴 뒤 복구 | 끊김이 끝난 뒤 1.5 s 안에 다시 연결된다 | 10/10, 끊김 끝 뒤 75.9–104.4 ms | 10 | 맞음 | M1c |
| 잠깐 끊긴 뒤 복구 | 장애 전까지 앱에 알려지지 않는다 | 장애 전 비동기 오류 0/10 | 10 | 맞음 | M1d |
| 끊김 중 재시도 초과 | 상한 안에 끝나는 끊김이면 투명하게 복구된다 | 10/10 투명 | 10 | 맞음 | M2a |
| 끊김 중 재시도 초과 | 시작 쪽이 기다렸고 기다림이 재연결로 끝났다 | 10/10 `ended=reconnected`, 기다림 2 848.2–3 037.4 ms | 10 | 맞음 | M2b |
| 끊김 중 재시도 초과 | 상한을 넘는 끊김이면 "상대 생존 모름"으로 거절된다 | 10/10 "RETRY_EXC and peer liveness unknown (ETIMEDOUT, no reconnect within 10000 ms)" | 10 | 맞음 | M3a |
| 끊김 중 재시도 초과 | 죽음 원인 문구로 거절된 시행이 없다 | 0/10 | 10 | 맞음 | M3b |
| 끊김 중 재시도 초과 | 거절은 첫 분류 기록 뒤 10.0–11.5 s에 온다 | 10/10, 10 001.7–10 003.0 ms | 10 | 맞음 | M3c |
| 끊김 중 재시도 초과 | 거절 시각에 rank 1이 살아 있다 | 10/10 | 10 | 맞음 | M3d |
| 죽은 상대 | 끊김 중 kill된 상대는 ECONNREFUSED로 죽음 판정된다 | 10/10 "RETRY_EXC and the peer's socket shows ECONNREFUSED" | 10 | 맞음 | M4a |
| 죽은 상대 | 끊김 중 kill이 "모름"으로 거절되거나 복구되지 않는다 | 0/10, 0/10 | 10 | 맞음 | M4b |
| 죽은 상대 | 거절은 첫 분류 기록 뒤 2 s 안에 온다 | 10/10, 1.1–2.1 ms | 10 | 맞음 | M4c |
| 기존 동작 | 회귀 셀 여섯 개가 그대로 투명하다 | 셀마다 5/5 | 30 | 맞음 | G1 |
| 기존 동작 | 끊김 없는 kill은 죽음 원인으로 거절되고 살아남은 쪽 abort가 돌아온다 | 5/5 "RETRY_EXC and the peer's socket shows FIN", rank 0 abort `no error` | 5 | 맞음 | G2 |
| 기존 동작 | 받는 쪽 abort 해제가 그대로다 | 5/5 rank 1 abort `no error` | 5 | 맞음 | G3 |
| 대조 | 1 s 끊김은 소켓을 닫지 않고 재연결도 없으며 투명하다 | 5/5 | 5 | 맞음 | C1 |
| 대조 | 재연결을 끄면 8 s 끊김 뒤 "no helper socket"으로 거절된다 | 5/5 "no helper socket to the peer: peer liveness unknown (ETIMEDOUT, reconnect off)" | 5 | 맞음 | C2 |
| 지연 | 4 KiB 지연 차이 0.40 µs 이하 | `rc` 10.59 µs, `s2r` 10.59 µs, 차이 0.00 µs | 5 + 5 실행 | 맞음 | L1 |
| 지연 | 256 KiB 지연 차이 0.30 µs 이하 | `rc` 38.91 µs, `s2r` 38.88 µs, 차이 0.03 µs | 5 + 5 실행 | 맞음 | L2 |

표의 범위는 모두 그 셀의 판정한 시행 전부(n열)에 걸친 범위다. 지연 값은 같은 hold(H1)에서 섞어 돈 실행 5개의 p50을 다시 중앙값으로
낸 것이다.

**셀별 시간 경과** `[측정]`. 시각은 rank 0의 `mono_ms`이고, 범위는 그 셀 시행 전부의 범위다.

- **8 s 끊김 뒤 로컬 QP 오류** (`rc_mute8_f1_b@rc`, n=10).
  - 소켓은 끊김 시작 4 573.0–4 599.7 ms 뒤 ETIMEDOUT으로 닫혔다.
  - 두 rank 모두 재연결 줄이 시행마다 1개였다. rank 0은 끊김이 끝난 뒤 75.9–104.4 ms(중앙값 90.7 ms)에 다시 연결됐다.
  - 장애는 끊김이 끝난 뒤 3 501.3–3 504.9 ms에 났고, 거절 없이 투명했다.
- **짧은 끊김 중 상대 QP 오류** (`rc_mutef3s_b@rc`, n=10).
  - 소켓은 끊김 시작 4 772.1–4 801.1 ms 뒤 ETIMEDOUT("모름")으로 닫혔다.
  - 첫 분류 기록은 소켓 닫힘 4 467.1–4 656.8 ms 뒤, 끊김이 끝나기 2 552.8–2 760.9 ms 전에 왔다.
  - rank 0은 2 848.2–3 037.4 ms(중앙값 2 978.4 ms) 기다렸다. 기다림은 끊김이 끝난 뒤 276.9–305.3 ms에 재연결로 끝났고, 그 뒤
    라운드가 진행되어 투명했다.
- **긴 끊김 중 상대 QP 오류** (`rc_mutef3l_b@rc`, n=10).
  - 소켓은 끊김 시작 4 768.1–4 801.5 ms 뒤 ETIMEDOUT("모름")으로 닫혔고, 첫 분류 기록은 그 4 425.8–4 698.6 ms 뒤에 왔다.
  - 기다림은 10 000.0–10 001.0 ms에 상한으로 끝났고(`ended=bound`), 재연결 줄은 0이었다.
  - 거절은 첫 분류 기록 뒤 10 001.7–10 003.0 ms에 왔다. 예측 범위의 아래 끝(10 000 ms)과 2–3 ms 차이다. 기다림이 정확히
    상한만큼이므로 이 간격은 구조상 상한보다 조금 크다 `[추론]`.
- **끊김 중 kill** (`rc_mutekill_b@rc`, n=10).
  - 소켓은 끊김 시작 4 772.7–4 801.3 ms 뒤 먼저 ETIMEDOUT("모름")으로 닫혔다.
  - 끊김이 끝난 뒤 276.0–305.5 ms에 다시 걸기가 ECONNREFUSED를 받아 "죽음"으로 바뀌었다(rank 0 로그의 두 번째 닫힘 줄에서 셈).
  - 첫 분류 기록은 그 1 000.2–1 221.8 ms 뒤에 왔고, 거절은 분류 기록 뒤 1.1–2.1 ms에 왔다.
  - 그래서 이 셀에서는 기다리는 도중 죽음의 증거가 와서 기다림이 끝나는 경로(`ended=dead`)를 한 번도 지나지 않았다. 10/10 기다림
    줄이 없다. 거절은 이미 "죽음"으로 바뀐 소켓을 보고 바로 났다. M4a, M4c의 판정식은 이 경우도 맞음으로 센다.
- **대조.**
  - 1 s 끊김(`rc_mute1_f1_b@rc`, n=5): 닫힘 0, 재연결 0, 장애는 끊김이 끝난 뒤 1 513.1–1 514.1 ms에 났고 5/5 투명했다.
  - 재연결 끔(`rc_mute8off_b@rc`, n=5): 소켓은 끊김 시작 4 586.4–4 597.7 ms 뒤 ETIMEDOUT으로 닫혔고, 기다림 없이(`ended=off`)
    분류 기록 뒤 0.3–1.0 ms에 거절됐다. 거절 시각에 rank 1은 5/5 살아 있었다.
- **기존 동작.**
  - 끊김 없는 kill(`f4_b@rc`, n=5): 소켓 닫힘 원인 5/5 FIN, 거절은 분류 기록 뒤 1.2–2.0 ms.
  - 받는 쪽 abort 해제(`f2rel_b@rc`, n=5): rank 1 abort 854.7–876.4 ms, 5/5 `no error`.
  - 지연 실행별 p50의 범위(각 5 실행): 4 KiB `rc` 10.56–10.59 µs, `s2r` 10.56–10.59 µs. 256 KiB `rc` 38.88–38.91 µs, `s2r` 38.88–38.91 µs.

**재연결 시각이 셀마다 좁게 모인 이유** `[추론]`. 다시 걸기는 소켓을 잃은 시각부터 500 ms마다 새로 시작한다(9절). 소켓을 잃은 시각에서
끊김이 끝날 때까지의 거리가 셀마다 거의 같아서(8 s 끊김은 약 3 410 ms, 끊김 시작 300 ms인 두 셀은 약 3 210 ms나 7 210 ms), 끊김이
끝난 뒤 첫 시도까지의 시간이 약 90 ms와 약 290 ms로 정해진다. 계산 값과 잰 값(75.9–104.4 ms, 276.9–305.3 ms, 276.0–305.5 ms)이 맞는다.

**mlx5.** hold 5개 모두 새 mlx5 줄이 0이었고, 명령 오류 줄(rain 2, sunny 0)과 rain의 펌웨어 명령 실패 수(31)는 hold 전후가 같았다
`[측정]`(`results/20261008/mlx5_new_*.txt`, `snap_*.txt`).

**다른 날의 자료.** 1절의 "바꾸기 전" 수치는 2026-10-07 `s2r` 빌드의 다른 hold에서 잰 것이다. 이 절의 셀과 같은 셀로 놓고
비교하지 않는다.

## 16. QA와 재현성

> 누가(사람 또는 에이전트) 무엇을 다시 셌고 무엇이 맞거나 달랐는지. 재현에 필요한 빌드와 커밋.

## 17. 결론

## 18. 한계

## 19. 다음 작업

## 20. 참고자료
