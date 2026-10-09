# GIN 투명 복구: 남은 세 문제(순환 대기, 상대를 모르는 대기, application의 CUDA 호출) (gin-remaining)

**목적:** 앞 실험들이 남긴 세 문제(시작 쪽 셋 이상의 순환 대기, 랭크 3개 이상에서 풀리지 않는 상대를 모르는 대기, application의 CUDA 호출에
막히는 복구 복사)를 라이브러리 계층 하나로 고치고, 고친 동작과 바뀌지 않아야 할 동작을 사전 등록한 예측으로 잰다.

| 항목 | 값 |
|---|---|
| 상태 | `DRAFT` |
| 담당자 | @unionxic |
| 작성일 | 2026-10-09 |
| 기준 브랜치와 커밋 | `exp/gin-remaining` @ `ae3dafc9` (master) |
| 사전 등록 태그 | 없음. 메인 세션의 pilot 뒤 `prereg/gin-remaining-v1`을 상태를 `PREREGISTERED`로 바꾼 바로 그 커밋에 단다(3절) |
| 마지막 갱신 | 2026-10-09, 초안: 계층 구현, 빌드, 실행기와 채점기, 예측 초안, 독립 리뷰와 반영, 마지막 빌드(1–12절) |

표시: `[측정]` 원자료나 시행별 표에서 확인, `[소스]` 코드에서 읽음, `[문서]` CUDA 문서의 설명, `[추론]` 해석, `[미확인]` 확인 안 함.

이 문서의 코드는 함수 이름으로 가리킨다. 파일은 따로 적지 않으면 `src/transport/net_ib/gdaki/gin_host_gdaki.cc`(빌드 트리는 세션 스크래치
`agent_ts2hr/nccl-src`)다. 용어(helper, 사용자 devComm, abort 단어, 상대별 단어, 거절, 죽음, 라운드, 커밋, 첫 분류 기록, 원인 분류)는
[../peer/EXPERIMENT.md](../peer/EXPERIMENT.md) 머리말과 같다. 이 실험에서 더 쓰는 말:
- 상대를 모르는 대기: 장치 API 중 어느 rank를 기다리는지 모르는 대기. `waitSignal`, `waitCounter`, LSA와 CFT 배리어, ll_a2a, void 판. 모두
  devComm의 abort 단어(상대별 단어 배열의 칸 0)만 읽는다.
- 상대별 대기: QP 하나에 걸린 장치 대기. `wait(request)`, `flush`, `flushAsync(peer)` 뒤의 `wait`, 게이트에서 쉬는 보내기.
- 스트림 복사 경로: 앞 빌드의 장치 상태 복사. helper의 non-blocking 스트림에 낸 `cudaMemcpyAsync`를 event로 확인한다.
- NIC 복사 경로: 이 계층의 장치 상태 복사. helper의 루프백 RC QP 쌍에 낸 RDMA READ와 WRITE다(9절 1번 (d)).
- 기다림 안 응답: 시작 쪽이 ACK를 기다리는 동안 더 낮은 rank의 REQ에 응답 쪽으로 답하는 라운드(중첩 라운드).
- 미룬 REQ: 시작 쪽이 ACK를 기다리는 동안 읽은 더 높은 rank의 REQ. 자기 라운드가 끝난 뒤 helper 루프가 답한다.
- degraded: 상대 하나가 죽음으로 판정된 communicator의 상태. 판정 `NCCL_GIN_TS_DEGRADED_MS`(기본 2000 ms) 뒤 칸 0이 올라간다(why=degraded).
- 세 호출: gin-harden 드라이버가 GIN 커널 실행과 GPU 채우기 커널 실행 사이에 하던 호출. GPU 채우기 커널의 점유율 질의(지연 적재에서 그 커널의
  첫 적재), `cudaMalloc`, 스트림 생성. 하나씩 나눈 셀에서는 적재, 할당, 스트림 생성이라 부른다.

예측 id, 셀 이름, 빌드 키는 원자료를 찾는 키로만 괄호나 표의 열에 둔다.

빌드 키는 다섯이다. 모두 번들 디렉터리 `$HOME/gi-bundle/gin_ts2/<키>/`다.

| 키 | 내용 | 쓰는 곳 |
|---|---|---|
| `hr` | 이 실험의 연구 빌드: gin-peer `hq` 소스 위에 9절 1번의 계층. 이 실험의 `gin_ts2`와 `hm_bench` | 새 셀, 회귀 셀 |
| `hrp` | 같은 소스를 `-DNCCL_GIN_TS_PRODUCTION`으로 컴파일한 운영 빌드. 같은 `gin_ts2` | 운영 kill, 지연 |
| `hq`, `hqp` | gin-peer 연구, 운영 빌드(배포된 번들 그대로, 읽기만. 다른 실험 blind-apps도 같은 때 쓴다) | 대조, 지연 기준 |
| `mr/hr` | 이 실험의 `gin_mr`(이 폴더의 [gin_mr.cu](gin_mr.cu), `hr` 헤더로 빌드). libnccl은 실행기가 고른 번들(`hr` 또는 `hq`)에서 씀 | 랭크 4개 셀 전부 |

랭크 2개 `hq` 대조도 이 실험의 `gin_ts2`(번들 `hr`)를 `hq` libnccl과 쓴다(9절 2번). `hqp`는 gin-peer 번들 자기 `gin_ts2`를 쓴다.

## 1. 배경과 연구 질문

사용자가 고치라고 한 것은 셋이다. 모두 앞 실험의 측정이나 리뷰가 짚었고, 수는 그 실험의 `trials_scored.csv`에서 다시 셌다.

**1. 시작 쪽 셋 이상의 순환 대기.**
- 시작 쪽은 ACK를 기다리는 동안 그 상대의 소켓만 읽는다(`gdakiTsInitiate`) `[소스]`. 다른 상대의 REQ는 helper 루프로 돌아올 때까지 소켓에 남는다.
- 그래서 시작 쪽 셋이 0에서 1, 1에서 2, 2에서 0으로 동시에 라운드를 열면 셋 모두 오지 않을 ACK를 한도(라운드 시작 + 24 500 ms)까지 기다린다.
- gin-multirank가 순환 셀(helper가 정지 뒤 300 ms 멈추는 시험 스위치로 세 라운드를 겹치게 함)에서 쟀다: 5회 모두 "handshake timeout" 거절이
  시행마다 3개, 첫 거절이 첫 라운드 줄 24 504.5–24 507.2 ms 뒤, 시행마다 거절 6개, 복구 0, 투명 0이었다. 라운드 시작의 퍼짐은 3.3–14.8 ms다
  `[측정: ../multirank/results/20261009/trials_scored.csv에서 다시 셈, n=5]`. 순환이 없는 사슬(0에서 1, 1에서 2)은 투명했고 마지막 재개가 첫 라운드 줄
  2 080.8–2 089.4 ms 뒤였다 `[측정, 같은 표, n=5]`.
- gin-harden, gin-peer의 계층은 이 대기 구조를 바꾸지 않았다(`hd`, `hq`) `[소스]`. 그 실험들의 18–19절이 이 문제를 남겼다.

**2. 상대를 모르는 대기가 풀리지 않음.**
- gin-peer는 abort 단어를 상대별로 나눴다. 거절과 죽음은 그 상대의 단어만 올리고, 칸 0(devComm 단어)은 그 rank의 모든 상대가 거절되었을 때와
  `ncclCommAbort`, 중단 shrink, revoke에서만 올라간다(`gdakiUaRaisePeer`, `ncclGinTsUserAbortRaise`) `[소스]`.
- 상대를 모르는 대기는 칸 0만 읽는다. 장치 API가 `this->comm.abortFlag`를 넘긴다(`nccl_device/impl/gin__funcs.h`의 `waitSignal`,
  `waitCounter`) `[소스]`. 그래서 랭크 3개 이상에서 상대 하나가 죽으면 그 상대의 신호를 기다리는 `waitSignal`은 자기 시간 제한까지, 시간 제한이
  없으면 application이 abort를 부를 때까지 돈다.
- gin-peer는 이 대기를 10 s 장치 시간 제한이 있는 형태로만 쟀다: rank 3 kill 셀에서 생존 rank의 rank 3 받기 3개가 10회 모두 한도("timeout")로
  끝났다 `[측정: ../peer/results/20261009/trials_scored.csv에서 다시 셈, n=10]`. 시간 제한 없는 대기는 재지 않았다(gin-peer 리뷰 M1,
  `../peer/qa/code_review.md`).

**3. application의 CUDA 호출에 막히는 복구.**
- helper의 장치 상태 복사는 helper의 non-blocking 스트림에 낸 `cudaMemcpyAsync`이고, 2 000 ms 안에 event가 끝나지 않으면 라운드가 거절된다
  (`gdakiRecD2H`, `gdakiRecH2D`, `gdakiRecCopyWait`) `[소스]`.
- gin-handoff의 GPU 가득 참 2 × 2: GIN 커널을 띄운 뒤 세 호출을 하면(`hf_hog_f1_b`) 5회 모두 rank 0의 복사가 시간을 넘겨 거절되었고 투명은 0이었다.
  두 rank 모두 새 스트림의 4 B 확인 복사 8개가 200 ms 안에 하나도 끝나지 않았다. 세 호출을 GIN 커널 앞으로 옮기면(`hf_hogpre_f1_b`) GPU가 똑같이
  가득 차도 확인 복사 8개가 모두 끝나고 5회 모두 투명했다 `[측정: ../handoff/results/20261009/trials_scored.csv에서 다시 셈, 셀마다 n=5]`.
- gin-handoff는 세 호출을 묶음으로만 갈랐고 하나씩은 가르지 않았다(그 실험 리뷰 L6) `[미확인]`.
- CUDA 문서는 서로 다른 스트림의 두 명령 사이에 장치 메모리 할당이 있으면 둘이 함께 돌지 못한다고 적고(implicit synchronization), 지연 적재는
  커널을 적재할 때 문맥 동기화가 필요할 수 있다고 적는다 `[문서]`. 이 테스트베드에서 어느 호출이 막는지는 재지 않았다 `[미확인]`.
- gin-peer는 상대별 abort 단어를 호스트 고정 메모리에 두어 거절이 복사 없이 장치 대기를 풀게 했다. 라운드의 나머지(게이트, QP 상태, 링,
  사본 영역)는 여전히 GPU 메모리를 복사로 읽고 쓴다 `[소스]`.

**질문.**
1. 시작 쪽이 ACK를 기다리는 동안 더 낮은 rank의 REQ에 답하고 더 높은 rank의 REQ는 미루면, 시작 쪽 셋의 순환이 시간 초과 없이 보통 라운드 시간
   안에 투명하게 풀리는가. 순환 없는 사슬과 기존 셀은 그대로인가.
2. 상대 하나가 죽음으로 판정되고 일정 시간이 지나면 칸 0을 올리고(degraded), 상대별 대기는 칸 0 대신 자기 상대의 단어를 읽게 하면, 시간 제한
   없는 `waitSignal`이 그 시간 안에 오류로 풀리고 건강한 상대와의 상대별 통신은 계속되는가. 그 대가(건강한 상대를 기다리던 `waitSignal`도
   풀림)는 얼마인가.
3. 라운드의 장치 상태 복사를 CUDA 호출 없이(NIC 루프백 RDMA) 하면, gin-handoff 순서(세 호출 뒤)에서도 복구가 투명한가. 세 호출 중 어느 것이 스트림
   복사를 막는가. 게이트를 호스트 메모리로 옮기는 대안은 얼마나 비싸고 안전한가.
4. 이 계층이 빠른 경로의 지연과 기존 셀의 판정을 바꾸지 않는가.

## 2. 가설

| id | 가설 | 다음이 관측되면 틀린 것이다 |
|---|---|---|
| H1 | 기다리는 시작 쪽이 더 낮은 rank의 REQ에 중첩 라운드로 답하면 대기 관계가 언제나 높은 rank에서 낮은 rank로만 이어져 순환이 생기지 않는다. 그래서 시작 쪽 셋의 순환은 ACK 한도를 기다리지 않고 몇 초 안에 투명하게 복구된다 | 순환 셀(`hr`)에서 "handshake timeout"이나 거절이 있는 시행, 또는 마지막 복구가 첫 라운드 줄 5 s 뒤인 시행이 2회 이상이다 |
| H2 | 첫 죽음 판정 뒤 정해진 시간에 칸 0을 올리면 상대를 모르는 대기는 그 시간 안에 오류로 풀린다. 상대별 대기가 칸 0 대신 자기 상대의 단어를 읽으면 건강한 상대와의 보내기, flush, 요청 대기는 풀리지 않는다 | 시간 제한 없는 받기 셀(`hr`)에서 rank 3 받기가 죽음 판정 2–3 s 안에 풀리지 않은 시행, 또는 생존 rank 사이 보내기 6개가 모두 끝나지 않은 시행이 2회 이상이다 |
| H3 | gin-handoff 순서에서 복구를 막은 것은 helper의 CUDA 스트림 복사다. 복사를 NIC 루프백 RDMA로 하면 CUDA 스트림이 묶여 있어도 복구가 투명하다 | GPU 가득 참 셀(`hr`)에서 투명하지 않거나 복사 시간 초과가 있는 시행이 2회 이상이다. 또는 같은 빌드에서 스트림 복사로 바꾼 대조가 투명하다 |
| H4 | 세 호출 중 막는 것은 문서가 동기화를 적은 둘(첫 커널 적재, `cudaMalloc`)이고 스트림 생성은 막지 않는다 | 호출 하나씩 셀(`hq`)에서 예측과 다른 시행이 2회 이상이다 |
| H5 | 이 계층은 빠른 경로를 바꾸지 않아(게이트와 QP 상태는 GPU 메모리에 그대로) 지연이 같고, 상대가 하나뿐인 랭크 2개와 기존 랭크 4개 셀에서 앞 빌드와 같게 동작한다 | 회귀 셀에서 예측과 다른 시행이 나온다. 또는 지연 차이가 예측 범위 밖이다 |
| H6 | 게이트 단어를 호스트 메모리로 옮기는 대안은 이 테스트베드에서 비싸다(장치 원자 연산마다 PCIe 왕복) | 호스트 매핑 메모리의 원자적 더하기가 장치 메모리보다 400 ns 이상 느리지 않은 실행이 있다 |

## 3. 사전 예측 (측정 전에 작성)

**고정 시점.** 예측은 메인 세션이 pilot(9절의 hold P0, P1)을 돌린 뒤 확정한다. pilot 시행은 채점하지 않으며, 그 결과 폴더(`results/<날짜>_pilot/`)는
채점 대상 폴더와 따로 둔다. pilot은 판정이 아니라 셀 조건과 열 읽기를 확인하는 데만 쓴다. pilot에서 예측과 다른 결과가 나와도 예측 문장, 판정식,
기준 수는 바꾸지 않고 의심만 적는다. 읽기 오류(열 정의, 파서)와 셀 조건(장애 시각, 셀이 조건을 만들지 못함)은 고칠 수 있고, 고친 셀은 태그 전에
pilot을 한 번 더 돈다(8절). 예측은 태그 `prereg/gin-remaining-v1`을 단 커밋에서 고정되고, 그 뒤에는 2, 3, 7, 8절과 `predictions.csv`를 고치지
않는다.

예측 원문은 [predictions.csv](predictions.csv)이고 33줄이다. `kind`는 N(새 동작), C(대조), R(회귀)다. 호출 하나씩 셀(H4)과 호스트 메모리
벤치마크(H6)는 이 테스트베드에서 잰 적이 없어 문서에서 이끈 예측이다.

### 3.1 판정에 쓰는 열

시행마다 한 줄이다.
- 랭크 2개 시행: 열은 `../scripts/ts2/rows.py`, `../s2_close/rows_extra.py`, `../pair_check/rows_pc.py`, `../oneway/rows_ow.py`,
  `../harden/rows_hd.py`, `../handoff/rows_hf.py`, `../peer/rows_pq.py`가 원래 정의 그대로 만들고(각 실험 3.1절), 이 폴더의 [rows_hr.py](rows_hr.py)
  `extra_hr2()`가 새 열을 붙인다.
- 랭크 4개 시행: `../multirank/rows_mr.py`의 `rows_of()`와 `../peer/rows_pq.py`의 `extra_pq4()`에 `extra_hr4()`가 새 열을 붙인다.
- 벤치마크 시행: `bench_row()`.
- 새 열의 정의 원문은 `rows_hr.py` 머리말이다. 요약:

| 열 | 정의 |
|---|---|
| `hr_on_r*`, `copy_path_r*`, `lb_on_r*`, `lb_off_r*` | 이 실험 시작 줄(`GIN/TS: remaining=1 rank=<r> copy_path=<nic\|stream> ...`)의 수와 복사 경로, NIC 복사 경로를 켠 줄과 끈 줄의 수 |
| `td_path_r*`, `td_stream_copies_r*` | 정리 때 줄 `GIN/TS: rank <r> copy path at teardown: path=... stream_copies=<d> ...`의 경로와, helper가 스트림으로 한 복사의 수 |
| `hog_calls_after_r*`, `drvkey` | 드라이버 kv `hog_calls_after`(GIN 커널 뒤에 한 호출), 실행기 meta의 드라이버 번들 |
| `served`, `n_served`, `kept`, `n_kept` | 기다림 안 응답 줄과 미룬 REQ 줄, "R-P"(rank R이 rank P의 REQ에 답함, 미룸) 목록 |
| `n_degraded`, `degr_ranks`, `degr_after_dead_ms_r*`, `dead_ms_r*` | why=degraded인 칸 0 해제 줄의 수와 rank, 그 줄 − 그 rank의 첫 죽음 판정 줄(같은 프로세스의 시계) |
| `rel_dead_r*`, `rel_after_dead_ms_r*`, `n_rel_dead`, `n_rel_surv` | 드라이버 kv(9절 2번): 생존 rank의 죽은 rank 받기가 풀렸는지, 풀린 것을 호스트가 본 시각 − 죽음 판정 줄, 그런 생존 rank 수, 생존 rank 사이 받기 중 풀린 것의 수 |
| `surv_tx_ok`, `n_kdone_surv`, `n_stuck_surv`, `rx_untimed` | 생존 rank 사이 보내기 중 끝까지 성공한 것, 커널이 끝난 생존 rank, application이 포기한 생존 rank, 시간 제한 없는 받기 표시 |
| `host_native_atomic_*`, `lat_*_ns_*`, `race_*_*` | 벤치마크 kv(노드별 `_rain`, `_sunny`, 9절 4번) |

**새 로그 줄** `[소스, 9절의 변경으로 고정]`. 연구 빌드(`hr`)에서는 모두 WARN이다. 운영 빌드(`hrp`)에서 "정보" 줄은 INFO다.

| 줄 | 수준(운영) | 형식 |
|---|---|---|
| 시작 | 정보 | `GIN/TS: remaining=1 rank=<r> copy_path=<nic\|stream> lb_mrs=<n> serve_wait=<0\|1> degraded_ms=<g>` |
| NIC 경로 켬 | 정보 | `GIN/TS: rank <r>: NIC copy path on: loopback qpn <a>-><b>, own PD, gid_index <i> (<link-local\|gin\|lid>), <n> GPU MR(s) (dmabuf <x>, peermem <y>), self-test ok (<b> B read and written back, <z> nonzero), setup_ms=<t> mono_ms=<t>` |
| NIC 경로 끔 | WARN | `GIN/TS: rank <r>: the NIC copy path is off (<why>); device-state copies use the private stream[ from now mono_ms=<t>]`(문맥을 만들 때의 실패, 또는 라운드 안의 오류 완료와 보내기 실패. 뒤의 경우 그 복사는 스트림으로 이어 함) |
| NIC 복사 시간 초과 | WARN | `GIN/TS: rank <r>: device-state copy (over the NIC, <dir>, <n> B) not complete after <ms> ms (NCCL_GIN_TS_COPY_MS); the round declines mono_ms=<t>` (앞 빌드의 스트림 복사 줄과 같은 꼴: 기존 파서가 센다) |
| 정리 때 복사 | 정보 | `GIN/TS: rank <r> copy path at teardown: path=<nic\|nic-off\|stream\|orphan> nic_ops=<a> nic_bytes=<b> nic_timeouts=<c> stream_copies=<d> served_in_wait=<e> kept=<f> fallbacks=<g>[ why=<w>]` |
| 기다림 안 응답 | 정보 | `GIN/TS: rank <r>: answering REQ round <k> from rank <p> while waiting for the ACK of round <j> from rank <t> (a lower rank is answered at once) mono_ms=<t>`와 끝에 `back to round <j> with rank <t> after answering rank <p> (<x> ms)` |
| 미룬 REQ | 정보 | `GIN/TS: rank <r>: REQ round <k> from rank <p> kept until round <j> with rank <t> ends (a higher rank waits) mono_ms=<t>`, 뒤에 `answering the kept REQ round <k> from rank <p> (kept <x> ms)` 또는 `the kept REQ round <k> from rank <p> is dropped (<이유>)`(이유: 연결이 없어짐, 그 상대와 라운드가 시작함, 더 새 REQ, 그 상대가 거절함, 떠남) |
| degraded 예약 | 정보 | `GIN/TS: rank <r>: communicator degraded in <g> ms: rank <p> was judged dead; waits that name no peer are released then (NCCL_GIN_TS_DEGRADED_MS) mono_ms=<t>` |
| degraded 해제 | WARN과 정보 | `GIN/TS: user devComm waits released rank=<r> why=degraded mono_ms=<t>`(형식은 앞 빌드의 칸 0 줄) 뒤에 정보 줄 `GIN/TS: rank <r>: communicator degraded: rank <p> was judged dead <x> ms ago; ...` |

**드라이버 kv.** `gin_ts2`: `hog_calls_after=<load,malloc,stream의 부분 목록|none>`. `gin_mr`: `rx_untimed`, 받기 간선마다 `rx_<ab>_rel`,
`rx_<ab>_rel_it`, `rx_<ab>_rel_mono_ms`, 그리고 `kernel_end_mono_ms`(기존 `kernel_done` 줄에 덧붙임). `hm_bench`: 9절 4번.

### 3.2 셀 키와 판정식 문법

셀 키(`cell@build`, 랭크 4개는 `build` = libnccl 키), 판정 대상(8절 제외를 거친 시행), "자료 부족" 규칙, 판정식 문법은 `../peer/EXPERIMENT.md`
3.2절과 같다(곧 `../s2_close/EXPERIMENT.md` 3.2절). [score.py](score.py)는 `../s2_close/score.py`의 판정식 평가 함수를 그대로 불러 쓴다.

### 3.3 예측 요약

전체 판정식은 [predictions.csv](predictions.csv)에 있다. "n"은 계획한 판정 시행 수다.

| 무엇을 예측했나 | id | 셀 | 판정 기준(요약) | 근거 |
|---|---|---|---|---|
| 순환하는 시작 쪽 셋이 handshake timeout도 거절도 없이 복구, 모든 간선 정상, 세 쌍 모두 시작 쪽 복구 줄 | CY1 | `mr4_cyc_stall@hr` | ≥9/10 | 9절 1번 (b) `[소스]`. gin-multirank 0/5 `[측정]` |
| 마지막 복구가 첫 라운드 줄 5 000 ms 안 | CY2 | `mr4_cyc_stall@hr` | ≥9/10 | 사슬 2.08–2.09 s, 거부 뒤 전체 범위 라운드 `[측정, 추론]` |
| 적어도 한 REQ를 다른 라운드의 ACK 기다림 안에서 답함 | CY3 | `mr4_cyc_stall@hr` | ≥9/10 | `[소스]` |
| 대조: 순환이 ACK 한도까지 기다려 24.3–24.8 s 뒤 handshake timeout, 투명 아님 | CY4 | `mr4_cyc_stall@hq` | ≥4/5 | gin-multirank Y1, Y2 5/5 `[측정]` |
| 순환 없는 사슬은 투명하고 5 000 ms 안(회귀) | CY5 | `mr4_chain_stall@hr` | ≥4/5 | gin-multirank Z1 5/5 `[측정]` |
| 시간 제한 없는 받기: 생존 rank마다 rank 3 받기가 죽음 판정 2 000–3 000 ms 뒤 오류로 풀림 | DG1 | `rm4_kill3_untimed@hr` | ≥9/10 | 9절 1번 (c) `[소스]` |
| 생존 rank마다 degraded 해제 줄 하나, 죽음 판정 2 000–2 500 ms 뒤 | DG2 | `rm4_kill3_untimed@hr` | ≥9/10 | `[소스, 추론]` |
| 생존 rank 사이 상대별 보내기 6개가 끝까지 성공하고 생존 rank의 커널이 모두 끝남 | DG3 | `rm4_kill3_untimed@hr` | ≥9/10 | `tsWaitWord` `[소스]` |
| 대가: 생존 rank 사이 받기 6개도 오류로 풀림 | DG4 | `rm4_kill3_untimed@hr` | ≥9/10 | 트래픽이 죽음 판정 2 s 뒤에도 남음 `[추론]` |
| 대조: rank 3 받기가 풀리지 않고 application이 15 s 뒤 포기할 때까지 생존 rank 커널이 돎 | DG5 | `rm4_kill3_untimed@hq` | ≥4/5 | gin-peer 리뷰 M1 `[소스]` |
| gin-peer의 셀(받기 한도 10 s)을 `hr`로: 생존 rank 보내기 성공, 받기 6개는 degraded 단어로 실패 | DG6 | `mr4_kill3_peer@hr` | ≥4/5 | gin-peer K1이 `hr`에서 설계로 달라짐 `[소스]` |
| gin-handoff 순서(세 호출 뒤, GPU 가득): NIC 복사로 시간 초과 없이 투명 | GR1 | `rh_hog_f1_b@hr` | ≥9/10 | 9절 1번 (d) `[소스]`. gin-handoff 0/5 `[측정]` |
| 그래도 CUDA 스트림은 묶여 있었음(확인 복사 0/8, GPU 채우기 블록 0) | GR2 | `rh_hog_f1_b@hr` | ≥9/10 | gin-handoff G2 5/5 `[측정]` |
| helper의 복사가 하나도 스트림을 쓰지 않음 | GR3 | `rh_hog_f1_b@hr` | ≥9/10 | `[소스]` |
| 대조: 같은 드라이버와 `hq` 라이브러리는 복사 시간 초과로 거절 | GC1 | `rh_hog_f1_b@hq` | ≥4/5 | gin-handoff G1 5/5 `[측정]` |
| 대조: `hr`에서 스트림 복사로 바꾸면 거절 | GC2 | `rh_hog_copystream_f1_b@hr` | ≥4/5 | `[소스]` |
| 적재만 GIN 커널 뒤: 확인 복사가 묶이고 `hq`는 거절 | GS1 | `rh_hogcall_load_f1_b@hq` | ≥4/5 | `[문서, 추론]` |
| `cudaMalloc`만 뒤: 같음 | GS2 | `rh_hogcall_malloc_f1_b@hq` | ≥4/5 | `[문서, 추론]` |
| 스트림 생성만 뒤: 확인 복사가 끝나고 `hq`도 투명 | GS3 | `rh_hogcall_stream_f1_b@hq` | ≥4/5 | `[문서, 추론]` |
| `hr`은 세 호출 중 어느 하나만 있어도 투명 | GS4 | 세 셀 `@hr` | 셀마다 3/3 | `[소스]` |
| 회귀: 복구 재현 셀이 투명 | RG1 | `f1_b`, `f3_b`, `bidirf_sym_b`(`@hr`) | 셀마다 5/5 | gin-peer R1 `[측정]` |
| 그 라운드의 복사가 모두 NIC로 감 | RG2 | 같은 셀 | 셀마다 5/5 | `[소스]` |
| 랭크 2개 kill: 2 s 안 peer-dead 거절, 칸 0이 바로 peer-dead(degraded 예약 없음) | RG3 | `f4_b@hr` | 5/5 | gin-peer R2 `[측정]` |
| 랭크 2개 받기만 하는 rank의 `waitSignal`이 2 s 안에 풀림 | RG4 | `hd_rxdeath_b@hr` | 5/5 | gin-peer R3 `[측정]` |
| 원격 접근 오류: 거절, 오류 해제, abort 5 s 안 | RG5 | `f2rel_b@hr` | 5/5 | gin-peer R4 `[측정]` |
| 운영 빌드 kill: 2 s 안 거절, 죽음 1, WARN에 정보성 줄 없음 | RG6 | `hdp_kill_b@hrp` | 5/5 | gin-peer R5 `[측정]` |
| 통계 API: 라운드 1, 복구 1, 거절 0 | RG7 | `f1_b@hr` | 5/5 | gin-peer R7 `[측정]` |
| 랭크 4개 장애 없음, 한 쌍 로컬 QP 오류: 투명 | RG8 | `mr4_none@hr`, `mr4_f1_01@hr` | 셀마다 5/5 | gin-peer R6 `[측정]` |
| 4 KiB 지연: 운영 빌드와 gin-peer 운영 빌드 차이 0.40 µs 이하 | LT1 | `lat_4k@hrp` 대 `@hqp` | 실행 중앙값 | 빠른 경로 그대로 `[소스]` |
| 256 KiB 지연: 차이 0.30 µs 이하 | LT2 | `lat_256k@hrp` 대 `@hqp` | 실행 중앙값 | 같음 |
| 두 플랫폼 모두 호스트 원자 연산 기본 지원 없음 | HB1 | `hm_bench@hr` | 5/5 | PCIe GPU `[추론]` |
| 호스트 매핑 메모리 원자적 더하기가 장치 메모리보다 400 ns 이상 느림 | HB2 | `hm_bench@hr` | 5/5 | PCIe 왕복 `[추론]` |
| 경합 단계가 정상으로 끝나고 개수 절반의 장치 갱신을 잃지 않음 | HB3 | `hm_bench@hr` | 5/5 | `[문서]` |

벤치마크의 `race_lost_host_writes`(호스트가 쓴 높은 절반을 장치의 읽고-고쳐-쓰기가 되돌린 횟수)는 예측 없이 잰다. 이 플랫폼에서 장치가 호스트
메모리 원자 연산을 PCIe 원자 연산으로 하는지 모른다 `[미확인]`.

## 4. 범위

**포함.**
- 9절 1번의 라이브러리 계층 하나([hr_layer.diff](hr_layer.diff), `hq` 트리 기준, 3개 파일)와 그 운영 빌드.
- 드라이버: `../gin_ts2.cu`의 세 호출 나누기(`GIN_TS_HOG_CALLS`), 이 폴더의 [gin_mr.cu](gin_mr.cu)(시간 제한 없는 받기), 새 벤치마크
  [hm_bench.cu](hm_bench.cu).
- 이 실험의 실행기([run_trial_hr.sh](run_trial_hr.sh), [run_mr_hr.sh](run_mr_hr.sh), [run_bench_hr.sh](run_bench_hr.sh))와 포트 고르기
  ([portpick.sh](portpick.sh), gin-peer의 복사). 앞 실험의 실행기는 고치지 않는다.
- 7절의 셀 키 29개.

**제외와 이 테스트베드가 할 수 없는 것.**
- 실제 link down, flap, 재부팅, 드라이버 재적재, 커널 모듈 적재(gdrdrv 포함), iptables: 하지 않는다(8절).
- 상대를 모르는 대기를 상대별로 푸는 것: 장치 API가 그 대기의 상대를 모른다(신호는 어느 rank든 더할 수 있다) `[소스]`. 이 계층은 그런 대기를
  degraded로 한꺼번에 푼다(대가는 9절 1번 (c)).
- 게이트와 QP 상태를 호스트 메모리로 옮기는 것: 빠른 경로를 바꾸므로 하지 않고, 대안의 비용과 안전성만 벤치마크로 잰다(9절 1번 (d), 4번).
- GPU 메모리를 CPU 주소 공간에 매핑하는 것(gdrcopy): gdrdrv 모듈이 없고 모듈 적재는 금지다 `[측정: rain lsmod에 gdrdrv 없음, 2026-10-09]`.
- 순환 셀은 helper 멈춤 시험 스위치로 만든다. 자연 타이밍의 순환 빈도는 재지 않는다.
- gin-peer가 남긴 다른 항목(shrink 순간의 경합, rank 사이 shrink 판정 맞추기, 포트 잔여, 채점기 보강): 이 실험의 몫이 아니다.

## 5. 테스트베드와 버전

| 항목 | 값 | 확인 방법과 날짜 |
|---|---|---|
| 노드, NIC, 펌웨어, GPU, CUDA | gin-peer와 같다: rain(rank 0, 랭크 4개에서는 0과 2, Quadro RTX 5000), sunny(rank 1, 랭크 4개에서는 1과 3, RTX A4000), ConnectX-6 fw 20.43.4100, CUDA 12.8 | `../peer/EXPERIMENT.md` 5절 |
| GPU 드라이버와 모듈 | rain: NVIDIA open kernel module 570.211.01, `nvidia_peermem` 적재됨, `gdrdrv` 없음, `RegistryDwords: "PeerMappingOverride=1;"` | `[측정]` 2026-10-09 rain(`lsmod`, `/proc/driver/nvidia/params`, `/proc/driver/nvidia/version`, 읽기만). sunny는 `[미확인]`(NIC 복사 경로의 자체 시험이 시작 줄로 알림) |
| `hq`, `hqp` 번들 | libnccl `c1311625c7a06c785bc313558504f982`, `4fa076e113e43774a9dc2f46298df43b`, 드라이버 `3e053ff2`, `gin_mr` `7f0fc272` | gin-peer 배포 확인(`../peer/deploy_check.txt`) `[측정, 이전 실험]`. 스크래치 `agent_ts2hq/out/`에서 같은 md5 `[측정]` 2026-10-09 |
| `hr`, `hrp`, 새 드라이버 | 12절의 마지막 빌드 줄. [deploy_hr.sh](deploy_hr.sh)의 기대 md5와 같다 | `[측정]` 빌드 때 rain(세션 스크래치 `agent_ts2hr/out/`, `out/build_info.txt`) |
| 변경분 | [hr_layer.diff](hr_layer.diff)(`hq` 트리 기준), 전체 diff [gin_transparent_hr.diff](gin_transparent_hr.diff)(pristine 기준). 순정에 전체 diff를, 그리고 gin-oneway 전체 diff + gin-harden, gin-handoff, gin-peer 계층 + 이 계층을 더하면 각각 이 트리와 같다 | [make_diff_hr.sh](make_diff_hr.sh), 12절 |

## 6. 변수

- **독립변수.**
  - 빌드: `hr`, `hrp`, `hq`, `hqp`(랭크 4개는 드라이버 `mr/hr`에 libnccl `hr` 또는 `hq`).
  - 복사 경로(`hr` 안에서): NIC(기본), 스트림(`NCCL_GIN_TS_COPY_PATH=stream`).
  - 장애: 로컬 QP 오류(rank 0, 랭크 4개는 순환과 사슬의 문맥 하나씩), 상대 QP 오류, 원격 접근 오류, rank 1 kill, rank 0 kill, rank 3 kill.
  - application: GIN 커널 실행 뒤의 호출(셋 모두, 적재만, 할당만, 스트림 생성만), GPU 채우기 커널 3 s, 받기 대기의 시간 제한(10 s 또는 없음),
    flush 방식(상대별).
  - 시험 스위치: 순환과 사슬 셀의 helper 멈춤 300 ms(정지 뒤).
- **종속변수.** 3.1의 열: handshake timeout과 거절, 복구 줄과 시각, 기다림 안 응답과 미룬 REQ, degraded 해제 시각, 받기 해제 시각, 간선마다 결과,
  복사 경로와 스트림 복사 수, 복사 시간 초과, 확인 복사와 GPU 채우기 블록 시작, 지연 p50, 벤치마크 값.
- **통제변수.** gin-peer와 같다: IB 타임아웃 14, GPU doorbell, 투명 복구 스위치 기본값(handshake 3 000 ms, hold 30 000 ms, 라운드 25 000 ms,
  재연결 10 000 ms, 복사 2 000 ms, 펌웨어 단계 3 000 ms), 이 계층의 기본값(`NCCL_GIN_TS_COPY_PATH=nic`, `NCCL_GIN_TS_SERVE_WAIT=1`,
  `NCCL_GIN_TS_DEGRADED_MS=2000`). 기존 셀 정의는 `../harden/cells.sh`, `../handoff/cells.sh`, `../multirank/cells.sh`, `../peer/cells.sh` 그대로다
  (실행기만 바꿈). 시행마다 프로세스를 새로 띄운다. 랑데부 포트는 29000–30999.

## 7. 실험 셀, 반복 수, 대조군

반복 수: 새 셀 10(호출 하나씩 셀 5, 그 `hr` 형태 3), 대조 5, 회귀 5. 지연 셀의 반복은 실행 수다(실행마다 3000번). 벤치마크는 실행 5회(실행마다 두
노드). 정의 원문은 [cells.sh](cells.sh)다. 훅 시각은 GDAKI 문맥 생성부터, kill 시각은 실행기가 그 rank를 띄운 때부터 잰다.

| 셀 | 조건 | 빌드와 반복 수 | 종류 |
|---|---|---|---|
| `rh_hog_f1_b` | gin-handoff `hf_hog_f1_b`에서 rank 0의 shrink를 뺀 것: `f1_b`(rank 0 로컬 QP 오류, 256 KiB × 120)에 두 rank의 GPU 채우기 커널 3 000 ms와 확인 복사(`GIN_TS_HOG_PROBE=1`), 세 호출은 GIN 커널 뒤(기본) | `@hr` 10, `@hq` 5 | 새 셀, 대조 |
| `rh_hog_copystream_f1_b` | 같고 `NCCL_GIN_TS_COPY_PATH=stream` | `@hr` 5 | 대조 |
| `rh_hogcall_load_f1_b`, `rh_hogcall_malloc_f1_b`, `rh_hogcall_stream_f1_b` | 같고 GIN 커널 뒤의 호출은 적재, 할당, 스트림 생성 중 하나뿐(`GIN_TS_HOG_CALLS`; 나머지 둘은 GIN 커널 앞) | 각 `@hq` 5, `@hr` 3 | 새 셀 |
| `mr4_cyc_stall` | 랭크 4개, rank 0 문맥 0(간선 0>1), rank 1 문맥 4(1>2), rank 2 문맥 6(2>0)에 로컬 QP 오류 6 000 ms, 세 rank에 `NCCL_GIN_TS_TEST_STALL=300@quiesce`(gin-multirank 정의) | `@hr` 10, `@hq` 5 | 새 셀, 대조 |
| `mr4_chain_stall` | 같고 rank 2의 장애 없음(사슬 0>1, 1>2) | `@hr` 5 | 회귀 |
| `rm4_kill3_untimed` | 랭크 4개, rank 3 SIGKILL 9 000 ms, 상대별 flush, 모든 받기 대기에 시간 제한 없음(`GIN_MR_RX_UNTIMED=1`), application은 비동기 오류 15 s 뒤 포기(`GIN_MR_GRACE_S=15`) | `@hr` 10, `@hq` 5 | 새 셀, 대조 |
| `mr4_kill3_peer` | gin-peer 정의(받기 한도 10 s, application 40 s) | `@hr` 5 | 새 셀(바뀐 회귀) |
| `f1_b`, `f3_b`, `bidirf_sym_b`, `f4_b`, `f2rel_b`, `hd_rxdeath_b` | gin-harden 정의 | `@hr` 각 5 | 회귀 |
| `hdp_kill_b` | gin-harden 정의 | `@hrp` 5 | 회귀 |
| `mr4_none`, `mr4_f1_01` | gin-multirank 정의 | `@hr` 각 5 | 회귀 |
| `lat_4k`, `lat_256k` | 장애 없음, 3000번. 같은 hold에서 두 빌드를 섞어 돈다 | `@hrp`, `@hqp` 각 5 | 대조 |
| `hm_bench` | rain과 sunny의 GPU에서 `hm_bench` 한 번씩(9절 4번) | `@hr` 5 | 새 셀 |

**합계.** 셀별 계획 수의 원문은 [score.py](score.py)의 `PLANNED`다.

| 종류 | 랭크 2개 시행 | 랭크 4개 시행 | 지연 실행 | 벤치마크 실행 |
|---|--:|--:|--:|--:|
| 새 셀 | 34(`hr`: GPU 가득 참 10, 호출 하나씩 9; `hq`: 호출 하나씩 15) | 25(`hr`: 순환 10, 시간 제한 없는 받기 10, gin-peer kill 셀 5) | | 5 |
| 대조 | 10(GPU 가득 참 `hq` 5, `hr` 스트림 복사 5) | 10(`hq`: 순환 5, 시간 제한 없는 받기 5) | 20(`hrp` 10, `hqp` 10) | |
| 회귀 | 35(`hr` 30, `hrp` 5) | 15(사슬, 장애 없음, 한 쌍 로컬 QP 오류 각 5) | | |
| 합 | 79 | 50 | 20 | 5 |

셀 키 29개(지연 4개 포함). 예측 33줄: 새 동작 18(벤치마크 셋 포함), 대조 6(지연 2 포함), 회귀 9.

## 8. 제외 기준과 중단 기준

**제외 기준.** 제외한 시행은 셀별로 따로 세어 보고한다([score.py](score.py) `status2`, `status4`, `statusb`).
- pilot(`results/<날짜>_pilot/`)은 채점하지 않는다.
- NCCL 초기화 전 실패(`bind_fail == 1`)는 제외하고 다음 번호로 채운다.
- 장애 미적용은 제외하고 채운다: 훅 셀에서 그 rank의 훅 발사가 없음(랭크 4개는 `fires`가 셀의 기대 "0:0", "0:0;1:4;2:6", "0:0;1:4"와 다르거나
  트래픽 밖), `trigger_miss > 0`, kill 셀에서 kill 기록이 없음(랭크 4개는 트래픽 밖의 kill도).
- 조건 미적용은 제외하고 채운다.
  - GPU 가득 참 셀 다섯: rank 0의 장애가 GPU 채우기 커널을 띄운 뒤 3 000 ms 창 밖(gin-handoff 규칙).
  - 순환과 사슬 셀: 라운드 시작의 퍼짐(`cyc_spread_ms`)이 비었거나 250 ms 초과(gin-multirank 규칙. 라운드가 겹치지 않으면 순환이 생기지 않음).
- 펌웨어 초과는 제외하고 채운다: 어느 rank든 감시 줄이나 `rs_fw_overruns`가 0이 아님(이 실험의 셀은 모두 펌웨어 초과가 주제가 아님).
- 벤치마크: 어느 노드든 종료 코드가 0이 아니면 제외하고 따로 센다(종료 코드 139는 아래 `STOP_cuda`).
- 채우려고 다시 돈 시행이 셀 키마다 계획의 50%를 넘으면 그 셀 키는 멈추고 "자료 부족"으로 둔다.

**설정 확인.** 하나라도 어긋나면 제외가 아니라 그 블록을 멈춘다.
- 랭크 2개 `hr` 시행: 두 rank(kill된 rank 빼고)에 gin-harden 시작 줄(`production=0`), gin-handoff 시작 줄, gin-peer 시작 줄, 이 실험 시작 줄, 투명 복구
  시작 줄, 사용자 devComm abort 단어 줄. 복사 경로가 셀과 같고(`rh_hog_copystream_f1_b`만 stream, 나머지 nic), nic 셀에 NIC 경로 끔 줄이 없음.
  meta의 드라이버 번들이 `hr`.
- 랭크 2개 `hq` 시행: 이 실험 시작 줄만 없음. 드라이버 번들 `hr`.
- `hrp`, `hqp`: 시작 줄이 WARN에 없고 kv에 `rs_api=1`, `rs_contexts >= 1`. 드라이버 번들은 자기 번들.
- 시험 스위치 줄이 없음(이 실험의 랭크 2개 셀은 시험 스위치를 쓰지 않음). GPU 가득 참 셀은 kv `hog_calls_after`가 셀과 같음.
- 랭크 4개: 모든 rank의 투명 복구 시작 줄과 abort 단어 줄이 n 이상, gin-peer 시작 줄이 n, 이 실험 시작 줄이 `hr`에서 n이고 `hq`에서 0, `hr`에서
  NIC 경로 켬 줄이 n 이상이고 끔 줄이 0. 드라이버 키 `hr`. 멈춤 스위치 줄이 순환 셀은 "0:300;1:300;2:300", 사슬 셀은 "0:300;1:300", 나머지는 없음.
  시간 제한 없는 받기 셀은 모든 rank의 kv에 `rx_untimed=1`.

**pilot에서 보이는 결함.** 태그 전이므로 고칠 수 있다. 고친 것은 12절에 적고, 고친 뒤에는 그 셀의 pilot을 다시 돈다. 미리 정해 둔 예:
- NIC 복사 경로가 어느 노드에서 켜지지 않음(자체 시험 실패, MR 등록 실패): 원인을 고치고 다시 빌드, 배포(새 디렉터리). 예측은 그대로다.
- 순환 셀: 라운드가 겹치지 않음(퍼짐 > 250 ms). 멈춤 시간(300 ms)을 한 번 바꿀 수 있다.
- 시간 제한 없는 받기 셀: 생존 rank 사이 트래픽이 죽음 판정 2 s 뒤에 이미 끝남(DG4의 조건이 없음). kill 시각(9 000 ms)을 한 번 바꿀 수 있다.
- 구현 결함: 회귀 셀이나 새 셀에서 예측과 다른 동작이 구현 탓으로 보이면 고치고 다시 빌드, 배포(새 디렉터리 `hr2/` 등)한다.

**중단 기준.**
- **잠금.** 모든 클러스터 명령은 `harness/gpu-initiated/common/cluster_run.sh -w 10800` 안에서 돈다([chain.sh](chain.sh), 꼬리표 `grm-<hold>`).
  10 800 s 안에 잠금이나 유휴 링크를 얻지 못하면 그 hold를 미룬다. `prio-` 작업에는 양보한다. hold 하나는 15분 이하이고 `timeout -s KILL 880`으로
  묶는다.
- **하지 않는 것.** 실제 link down이나 flap, 재부팅, 드라이버 재적재, 커널 모듈 적재, RoCE 주소 변경, 시스템 TCP 설정 변경, iptables 규칙 추가, GPU
  컴퓨트 모드 변경. `chain.sh`는 hold 앞뒤에 `gin-` 꼬리표 iptables 규칙 수를 읽기만 하고, 늘었으면 `STOP_iptables`로 멈춘다.
- **프로세스.** 이름으로는 아무것도 끄지 않는다(`pkill`, `killall` 없음). 실행기는 자기가 기록한 PID와 그 자식만 신호한다(gin-peer 실행기 그대로).
  벤치마크는 `timeout -s KILL 90` 안에서만 돈다. 시행 뒤 남은 프로세스는 읽기만 해서 세고, 두 시행 연속이면 `STOP_left`. 다음 hold는 남은
  `gin_ts2`, `gin_mr`, `hm_bench`가 없어질 때까지 150 s까지 기다리고, 그래도 있으면 시행을 돌지 않는다.
- **CUDA 메모리 오류.** hold 안의 어느 시행이든 rank나 벤치마크의 종료 코드 139이거나 로그, kv에 illegal address, illegal memory access, unspecified
  launch failure가 보이면 그 hold 뒤로 멈춘다(`STOP_cuda`).
- **mlx5 오류.** hold 앞뒤에 두 노드의 mlx5 커널 줄 전체와 rain의 펌웨어 명령 계수를 남긴다. 새 명령 오류 줄이나 펌웨어 명령 실패 계수 증가가 보이면
  그 hold 뒤로 멈춘다(`STOP_mlx5`).
- **배포.** 새 번들은 새 디렉터리 `hr/`, `hrp/`, `mr/hr/`에만 둔다. 대상 파일이 이미 있거나 소스가 기대 md5와 다르면 배포 스크립트가 멈춘다. 배포 뒤
  기존 번들 파일의 md5가 두 노드에서 그대로인지 확인한다. `hq/`, `hqp/`는 읽기만 한다(다른 실험 blind-apps가 같은 때 쓴다).

## 9. 실행 방법과 경로

### 1. 라이브러리 계층 (`hr`, `hrp`)

[hr_layer.diff](hr_layer.diff)(`hq` 트리 기준)와 전체 diff [gin_transparent_hr.diff](gin_transparent_hr.diff). 바뀐 파일:

| 파일 | 무엇 |
|---|---|
| `src/transport/net_ib/gdaki/gin_host_gdaki.cc` | 거의 모든 변경 |
| `src/include/nccl_device/gin/gdaki/gin_gdaki.h` | 상대별 대기가 칸 0 대신 자기 상대의 단어를 읽음(`tsWaitWord`) |
| `src/include/nccl_device/gin/gdaki/gin_gdaki_device_host_common.h` | 게이트 `test` 칸의 새 쓰임(주석만) |

(a) **중첩을 위한 준비** `[소스]`.
- 준비 상태를 상대별로 바꿨다(`gdakiRecHost::prepared[]`, `nPrepared`; 앞 빌드는 상태 하나와 상대 하나). helper는 한 상대와 준비한 라운드를 둔 채
  다른 상대를 준비할 수 있다. 두 상대의 QP는 겹치지 않는다. application의 recovery API(투명 복구가 꺼졌을 때)는 앞처럼 한 번에 한 상대다.
- proxy progress 멈춤은 수로 센다(`gdakiRecPause`, `gdakiRecResume`). 준비마다 한 번 더하고 커밋, 실패한 커밋, abort가 한 번 뺀다.
- helper 안의 `ncclGinRecoverAbort`와 거절은 그 상대의 준비만 푼다. application이 부른 `ncclGinRecoverAbort`는 앞 빌드처럼 그 문맥의 준비를 넘긴
  상대와 상관없이 푼다(application은 한 번에 한 상대만 준비할 수 있다. 리뷰 L5).
- 중첩 라운드는 바깥 라운드의 시계로 돈다(`gdakiTsBusy`가 바깥 시작을 그대로 둠). 그래서 중첩 라운드에서 라운드의 남은 시간으로 잡는 한도(DONE 기다림,
  경로 기다림)는 바깥 라운드의 남은 시간으로 잘리고, 라운드 감시의 25 000 ms는 둘을 합쳐 잰다. 바깥 라운드에 응답 쪽 정지 한도와 handshake 한도를
  합친 시간(기본 8 000 ms)이 남지 않았으면 중첩 라운드를 열지 않고 낮은 rank의 REQ를 소켓에 남긴다(`gdakiTsCanNest`, 기본값에서 바깥 라운드 시작
  16.5 s 뒤부터). 리뷰 M1: 처음 구현은 중첩 라운드에 새 시계를 주고 끝나면 바깥 시작을 돌려줘, 중첩이 길면 바깥 라운드가 라운드 한도를 넘었다고
  감시에 잡힐 수 있었다. 시작 쪽이 교차(양보, 범위 충돌)에서 스스로 도는 응답 쪽 라운드는 앞 빌드처럼 새 시계다. 범위(`gdakiTsScopeGuard`)는 바깥 범위를
  돌려준다(맨 바깥에서는 앞처럼 모든 문맥).
- 중첩 라운드 뒤와 기다림 중 FAIL로 한 거절 뒤에는 바깥 라운드의 펌웨어 라운드 번호를 새로 받는다(`fwRound`): 그 사이 매겨진 초과가 바깥 라운드를
  거절시키지 않고, 번호가 다시 쓰이지 않는다(거절 뒤의 것은 리뷰 L1).

(b) **기다림 안 응답과 미룬 REQ (문제 1)** `[소스]`.
- 시작 쪽의 ACK 기다림이 `gdakiTsRecvServing`으로 바뀌었다. 자기 상대의 소켓을 먼저 읽고, 다른 상대의 소켓을 `gdakiTsServeLower`로 읽는다.
  - 더 낮은 rank의 REQ: 그 자리에서 응답 쪽 라운드(`gdakiTsRespond`)를 돈다. 그 라운드는 다른 REQ에 답하지 않는다(응답 쪽은 DONE을 그 상대의 소켓에서만
    기다린다). 끝나면 자기 상대의 소켓부터 다시 읽는다.
  - 더 높은 rank의 REQ: 그 상대의 칸(`gdakiTsPeer::deferredReq`)에 둔다. helper 루프가 다음 회에 소켓보다 먼저 답한다. 그 사이 연결이 바뀌었으면
    (세대가 다르거나 소켓이 없으면) 버린다(그 라운드는 소켓 끊김으로 취소되어 다시 시도된다). 상대는 답을 기다리므로 칸 하나로 충분하다.
  - 미룬 REQ를 버리는 때(리뷰 H1, L2): 그 상대와 자기 라운드를 시작할 때(낮은 rank인 자기 라운드가 이기므로 상대는 교차에서 양보하거나, 이미 끝났으면
    답한다), 그 상대의 더 새 REQ에 답할 때, 답하기 전에 그 소켓을 읽어 FAIL(거절), BYE(떠남), 끊김, 더 새 REQ(그것에 답함)가 보일 때. 처음 구현은
    상대가 여러 개인 장애에서 방금 복구한 쌍에 낡은 REQ로 다시 답해, 그 쌍을 정지하고 DONE 한도(약 24.5 s) 뒤 거절할 수 있었다.
  - FAIL, BYE, 끊김은 helper 루프와 같이 다루고(거절, 떠남, liveness 판정), 나머지는 무시한다.
- 순환이 끊기는 이유. 기다리는 시작 쪽 X가 상대 Y의 답을 기다릴 때, Y가 X에게 답하지 않는 경우는 Y가 시작 쪽이고 X > Y인 경우뿐이다(낮은 rank의
  REQ는 언제나 답한다). 그러므로 서로를 기다리는 시작 쪽의 순환이 있다면 그 위의 rank가 끝없이 줄어야 하므로 순환은 없다. 중첩 라운드는 자기보다
  낮은 rank 하나(이미 ACK를 받으면 아무도 기다리지 않음)에만 기대고, 중첩은 한 겹이다(중첩 라운드 안에서 시작 쪽이 생기지 않음). 랭크 2개의 동시
  시작(서로에게 REQ)은 앞 빌드의 tie-break 그대로다.
- 순환이 없을 때도 바뀐다. 기다리는 시작 쪽은 더 낮은 rank의 REQ에 바로 답한다(앞 빌드: 자기 라운드가 끝난 뒤). 중첩 라운드가 길면 바깥 라운드의
  남은 시간이 줄어든다(바깥 라운드의 ACK 한도와 라운드 감시는 바깥 라운드의 시작부터 재고, 중첩 라운드의 한도도 그 안으로 잘린다).
- `NCCL_GIN_TS_SERVE_WAIT=0`이면 앞 빌드의 기다림이다.

(c) **degraded (문제 2)** `[소스]`.
- 규칙: 어떤 GIN 상대가 처음으로 죽음으로 판정되면(거절 원인 peer-dead, `GDAKI_UA_PEER_DEAD`. 거절만이나 떠남은 아님) 그 communicator는 degraded가
  된다. `NCCL_GIN_TS_DEGRADED_MS`(기본 2000 ms; 0은 바로; −1은 하지 않음, gin-peer 동작) 뒤 칸 0이 why=degraded로 올라간다. 그 사이에 칸 0이 다른 이유로
  올라가면(모든 상대 거절, abort, shrink, revoke) 아무것도 하지 않는다.
- 실행: `gdakiUaRaisePeer`가 예약하고, 분류 기록 감시 스레드가 매 회 `gdakiUaDegradedStep`으로 시각을 본다(예약이 없으면 원자 변수 하나만 읽음).
  쓰기는 `gdakiUaMu` 안에서 하고, `ncclGinTsUserAbortFree`도 같은 자물쇠 안에서 등록을 지운 뒤에야 단어 배열을 푼다.
- 장치(`gin_gdaki.h`): 게이트가 켜진 QP의 요청 대기와 flush(`waitImplCore`, `flushImplModeCore`)는 호출자가 넘긴 칸 0 대신 그 QP 상대의 단어를 읽는다
  (`tsWaitWord`). 단어를 실제로 읽는 자리에서만 바꾼다: 기다리는 폴링 10 000번마다(`tsPoll`, 앞 빌드의 `testAbort` 주기), 쉬는 대기의 64번마다
  (`tsParkStable`). 그래서 대기의 빠른 경로는 아무것도 더 읽지 않는다. 그 단어는 그 상대의 거절, 죽음, 펌웨어 초과, 그리고 abort, 중단 shrink,
  revoke(모든 단어)로 올라간다. 게이트에 상대 단어가 아직 없으면(devComm을 만든 직후 helper의 다음 루프 전, 시험 분할) 앞처럼 칸 0이다. 보내기는 앞
  빌드에서도 칸 0을 읽지 않았다.
- `ncclGinTsUserAbortRaise`는 칸 0이 이미 올라가 있어도(모든 상대 거절, degraded) 내려 있는 상대 단어를 모두 올린다(`allWhy`. 앞 빌드: 칸 0이 올라가
  있으면 돌아감). 칸 0 줄은 칸 0을 이번에 올릴 때만 쓴다(앞과 같음).
- `gdakiUaPeerRaised`(라운드를 게시하기 전 확인)는 상대별이다. 칸 0만 올라간 것(degraded)은 건강한 상대와의 라운드를 막지 않는다. 그 상대의 장치 대기는
  칸 0을 읽지 않기 때문이다. 단 그 문맥의 모든 게이트에 상대 단어가 들어간 뒤(`gdakiTsPeerWords`: helper의 상대 단어 쓰기가 끝났고 시험 분할이
  아님)에만 그렇다. 그 전에는 장치 대기가 칸 0을 읽으므로 칸 0도 센다(리뷰 M2: 처음 구현은 칸 0을 늘 빼서, 칸 0으로 실패를 들은 대기의 연산을 그
  상대와의 라운드가 다시 낼 수 있었다).
- 장치 코드는 헤더에만 있다. 이 계층보다 앞의 헤더로 빌드한 application은 상대별 대기에서도 칸 0을 읽으므로 degraded 뒤 건강한 상대의 대기도 오류로
  끝나고, helper는 그것을 알 수 없다(그 대기의 연산을 그 상대와의 라운드가 다시 낼 수 있다) `[소스, 추론]`. degraded 뒤에도 상대별 대기가 이어져야 하는
  application은 이 계층의 헤더로 빌드해야 한다. 이 실험의 드라이버는 모두 `hr` 헤더로 빌드했다.
- 장치 API별 의미(이 계층, 랭크 3개 이상에서 상대 p가 죽음으로 판정된 뒤):

| 장치 API | p에 걸렸으면 | 건강한 상대 q에만 걸렸으면 |
|---|---|---|
| `put`, `signal` 등 보내기(게이트) | 보내지 않음(게이트 실패나 p의 단어) | 영향 없음 |
| `flushAsync(peer)` + `wait`, `wait(request)`, `flush` | 오류(p의 단어) | 영향 없음(칸 0을 읽지 않음). 단 blocking 판의 결과는 문맥마다 하나(gin-peer M3) |
| `waitSignal`, `waitCounter`, 배리어, ll_a2a, void 판 | 판정 `NCCL_GIN_TS_DEGRADED_MS` 뒤 오류로 풀림 | 같음: 그 시각에 아직 기다리고 있거나 그 뒤에 부르면 오류 |
| 랭크 2개 | 앞 빌드와 같음: 유일한 상대라 판정 즉시 칸 0(peer-dead), degraded 예약 없음 | 해당 없음 |

- 대가 `[추론]`. degraded 뒤 그 communicator의 상대를 모르는 대기는 모두 오류다. 건강한 rank의 신호를 기다리던 대기도, 늦게 부른 대기도 그렇다.
  application은 상대별 통신을 마치고 shrink하거나 abort해야 한다. 2 s의 유예는 죽음 판정 순간 이미 날아오던 건강한 신호를 기다리는 대기가 끝날 시간을
  주고, 그동안 죽은 rank를 기다리는 대기는 그만큼 늦게 풀린다. 0으로 두면 유예 없이 판정과 함께 풀린다.

(d) **NIC 복사 경로 (문제 3)** `[소스]`.
- 왜 호스트 메모리가 아닌가. 라운드가 읽고 쓰는 것은 장치 QP 구조체(그 안의 게이트 64 B와 게이트 단어 8 B), 보내기 링, 완료 링, doorbell 기록, 사본
  영역, get 표다. 게이트 단어에는 보내기와 대기마다 SM 원자 연산이 둘 있고(들어갈 때 더하기, 나올 때 빼기), DOCA 장치 코드는 QP 구조체의 색인에 매번
  원자 연산을 한다 `[소스]`. 이것들을 호스트 메모리로 옮기면 빠른 경로의 매 연산이 PCIe 왕복을 탄다. 또 호스트가 게이트 단어의 위 절반(에폭)을 쓰는
  동안 장치는 같은 8 B에 읽고-고쳐-쓰기를 하는데, CUDA 문서는 매핑된 호스트 메모리의 원자 연산이 호스트에 대해 원자적이지 않다고 적는다 `[문서]`.
  그러면 정지 프로토콜(호스트가 에폭을 홀수로 쓰고 개수를 0까지 읽음)이 깨질 수 있다. 9절 4번의 벤치마크가 비용과 이 경합을 잰다. gin-peer가 이미
  호스트 메모리로 옮긴 상대별 abort 단어는 장치가 읽기만 하는 단어라 이 문제가 없다.
- 왜 다른 CUDA 길이 아닌가. CPU가 GPU 메모리를 직접 읽고 쓰려면 BAR1 매핑(gdrcopy)이 필요한데 gdrdrv 모듈이 없고 적재는 금지다. `cuMemHostRegister`와
  `cudaHostAlloc`(매핑)은 호스트 메모리를 GPU에 보이게 할 뿐 GPU 메모리를 CPU에 보이게 하지 않는다. 다른 스트림이나 다른 CUDA 문맥의 복사도 CUDA
  명령이라 같은 암묵적 동기화나 시분할에 걸릴 수 있다 `[추론, 미확인]`.
- 그래서 NIC가 GPU 메모리를 읽고 쓴다(GPUDirect RDMA, 이미 데이터 경로가 쓰는 길). helper가 GIN 문맥의 ibv 문맥에 자기 PD를 따로 만들고(리뷰 L4:
  QP 구조체, 링, 게이트에 원격 쓰기를 허락하는 GPU MR의 rkey가 다른 rank와 이어진 QP에서는 통하지 않게), 그 PD에 루프백 RC QP 쌍(같은 포트, NIC 안에서
  되돌아옴), CQ, 스테이징 버퍼의 호스트 MR을 만들고, 라운드가 닿는 GPU 할당을 모두 GPU MR로 등록한다(`gdakiLbSetup`, `gdakiLbAddRange`): QP마다 장치 QP
  구조체, 보내기 링, 완료 링, doorbell 기록, 그리고 사본 영역(이 계층에서 한 블록으로 할당), get 표 둘. 등록은 `cuMemGetAddressRange`로 찾은 할당의
  페이지 정렬 부분을 dmabuf로(iova = 그 GPU 주소), 안 되면 nvidia-peermem으로 한다.
- 루프백의 GID(RoCE, 리뷰 H2): GIN GID와 같은 RoCE 종류의 link-local 항목(fe80::/10, 포트의 MAC에서 나와 주소를 붙였다 지워도 남음)을 먼저, 없거나
  실패하면 GIN 문맥 자신의 GID를 쓴다. 후보마다 연결한 뒤 8 B 루프백 READ가 2 s 안에 끝나야 고른다. 처음 구현은 GIN 문맥의 GID(실험 주소)에 묶여,
  주소를 지웠다 붙이는 셀(gin-s2, 이 실험에 없음)에서 루프백이 실패하고 라운드가 거절될 수 있었다(`hq`는 같은 셀을 3/3 복구) `[추론]`. 시작 줄에 고른
  GID가 나온다(`gid_index <i> (link-local|gin)`).
- 복사(`gdakiLbXfer`): 장치에서 호스트로는 RDMA READ 하나, 호스트에서 장치로는 RDMA WRITE 하나와 같은 MR의 8 B RDMA READ(신호)다. RC에서 READ는
  앞선 WRITE를 앞지르지 못하므로, 그 완료는 쓴 바이트가 GPU 메모리에 있어 SM이 볼 수 있다는 뜻이다(NCCL이 Hopper 전 GPU에 쓰는 flush) `[소스, 추론]`.
  상한은 스트림 복사와 같은 `NCCL_GIN_TS_COPY_MS`(2 000 ms)이고, 상한을 넘으면 라운드가 거절된다(앞과 같음). 늦은 완료가 남아 있으면 그것이 올 때까지
  다음 복사는 실패한다(스테이징 버퍼를 아직 쓸 수 있음). 오류 완료나 보내기 실패는 두 루프백 QP를 ERR로 보내(그 뒤로는 아무것도 닿지 않음) 그 문맥의
  NIC 경로를 끄고, 그 복사와 그 뒤 복사를 스트림으로 한다(WARN "the NIC copy path is off", 정리 줄 `fallbacks`. 리뷰 H2, L8: 처음 구현은 그 복사를
  실패시켜 라운드를 거절했고, 문맥을 만들 때 게이트 쓰기에서 실패하면 그 rank의 투명 복구가 꺼졌다). CUDA 호출은 없다. 그래서 application의 CUDA 호출이
  만든 암묵적 동기화는 라운드에 닿지 않는다 `[소스, 추론]`.
- 자체 시험(문맥을 만들 때, 아직 커널이 이 QP를 쓰지 않음): 게이트의 시험 계수 칸과 사본 블록 첫 64 B를 NIC로 썼다가 스트림 복사로 읽어 확인하고
  되돌린다. 등록한 할당마다 처음 등록한 범위의 앞 64 B까지를 NIC와 스트림으로 읽어 비교하고, 같은 바이트를 NIC로 다시 써서 스트림으로 읽어 확인한다
  (모든 MR을 한 번씩 읽고 씀. 리뷰 L3: 처음 구현은 대개 0인 4 B 읽기만 비교했다). 시작 줄에 비교한 바이트 수와 0이 아닌 바이트 수가 나온다. 하나라도
  실패하면 NIC 경로는 꺼지고 앞처럼 스트림 복사다(WARN과 시작 줄 `copy_path=stream`).
- 게이트 단어의 위 절반 4 B 쓰기는 이제 NIC의 PCIe 쓰기다. 앞 빌드에서는 복사 엔진의 4 B 쓰기였고, 둘 다 GPU L2에서 SM의 64비트 원자 연산과 같은
  자리에 닿는다. 복사 엔진의 경우는 gin-s2의 `gate_ce_test.cu`가 확인했고 NIC의 경우는 확인하지 않았다 `[추론, 미확인]`. 독립 리뷰의 판단도 같다: 둘 다
  L2가 64비트 원자 연산과 차례를 정하는 4 B 부분 쓰기 하나이고, 어느 쪽도 CUDA 메모리 모델이 보장하지는 않는다. 회귀 셀의 모든 라운드가 이 쓰기를 한다.
- 시험 스위치 `NCCL_GIN_TS_TEST_COPY_STALL`은 NIC 경로에서 완료를 그만큼 받지 않는 것으로 바뀐다(앞 빌드: 스트림을 호스트 콜백으로 묶음). 데이터는
  바로 닿고 완료만 늦으므로 앞 빌드의 멈춘 복사와 같은 상황이 아니다(리뷰 L6). 이 실험의 셀은 이 스위치를 쓰지 않는다.
  `NCCL_GIN_TS_COPY_PATH=stream`이면 앞 빌드의 복사다.
- 남는 CUDA 호출: helper가 시작할 때 한 번 `cudaSetDevice`, 문맥을 만들 때의 할당과 자체 시험, application 스레드의 recovery API(투명 복구가 꺼졌을
  때), 정리. 라운드 안에는 없다 `[소스]`.
- 수명: 루프백 자원은 helper가 멈춘 뒤, 등록한 메모리와 스테이징 버퍼를 풀기 전에 푼다(`gdakiTsFree`). 떼어 낸 helper(펌웨어 명령 안)는 문맥을 그대로
  두므로 루프백 자원도 둔다. `ncclDevCommDestroy` 없이 `ncclCommAbort`만 부르면 GDAKI 문맥이 남는 것은 앞 빌드와 같다(DOCA 자원도 남음).

(e) **남는 점** `[소스, 추론]`.
- 순환: 중첩은 한 겹이고 낮은 rank에게만 답하므로, 낮은 rank가 계속 REQ를 보내면 높은 rank의 바깥 라운드는 그만큼 늦어진다. 라운드 시간은 바깥 라운드의
  시작부터 재므로, 중첩이 길면 바깥 라운드가 ACK 한도에서 거절될 수 있다. 바깥 라운드가 16.5 s를 넘긴 뒤 온 낮은 rank의 REQ는 앞 빌드처럼 바깥 라운드가
  끝난 뒤 답한다.
- degraded는 죽음에만 반응한다. 살아 있으나 거절된 상대(예: 펌웨어 초과, 상대가 알린 실패)는 그 상대를 기다리는 상대를 모르는 대기를 풀지 않는다
  (gin-peer와 같음).
- NIC 경로의 link-local GID 루프백은 이 테스트베드에서 아직 돈 적이 없다 `[미확인]`. 실패하면 GIN GID로, 그것도 실패하면 스트림 경로다(시작 줄로 보임).
  오류로 꺼진 NIC 경로는 그 문맥에서 다시 켜지지 않는다.
- NIC 경로의 4 B 게이트 쓰기의 원자성은 위 (d)의 `[미확인]`이다.
- 장치 대기의 abort 탈출(`tsPoll`)은 QP를 오염 표시하지 않는다(앞 빌드와 같음). degraded 뒤의 안전은 위 (c)의 게시 전 확인에 기댄다 `[소스]`.

### 2. 드라이버

- `../gin_ts2.cu`(앞 실험들이 고쳐 온 공용 드라이버를 같은 자리에서 고침): `GIN_TS_HOG_CALLS=<load,malloc,stream의 부분 목록|all|none>`. 나열한 호출만
  GIN 커널 뒤에 하고 나머지는 앞에서 한다(앞에서 하는 적재는 커널 속성 읽기가 뒤따름: kv `hog_preloaded`). 기본(all)은 gin-harden 순서이고
  `GIN_TS_HOG_PREALLOC=1`은 none이다. kv `hog_calls_after`. 이 변수가 없으면 앞 드라이버와 같다 `[소스]`.
- [gin_mr.cu](gin_mr.cu)(`../peer/gin_mr.cu`의 복사본, 그 파일은 고치지 않음): `GIN_MR_RX_UNTIMED=1`이면 받기 간선이 시간 제한 없는 void
  `waitSignal`을 쓰고, 돌아온 뒤 신호가 목표보다 작으면 해제로 보고 그 반복에서 `ncclRemoteError`로 끝내며 호스트 매핑 깃발을 세운다. 호스트는 커널을
  기다리는 동안 깃발을 보고 처음 본 시각을 남긴다(kv `rx_<ab>_rel*`). 아이 단계의 받기는 앞처럼 시간 제한이 있다.
- [hm_bench.cu](hm_bench.cu): 9절 4번.
- 대조 빌드의 드라이버: 랭크 2개 `hq` 대조는 이 실험의 `gin_ts2`(번들 `hr`)를 `hq` libnccl과 쓴다(실행기 `DRVKEY=hr`). 장치 코드의 차이는
  `tsWaitWord`뿐인데, `hq` 라이브러리도 게이트에 상대 단어를 쓰고 칸 0만 올리는 일(degraded)이 없으므로 대기의 해제는 `hq`의 것과 같다. 대조의 차이는
  라이브러리다 `[소스]`. 지연의 `hqp`는 gin-peer 번들 자기 `gin_ts2`를 쓴다(지연 비교는 드라이버 장치 코드까지 포함, gin-peer와 같은 방식).
- 랭크 4개 대조(`hq`)는 `mr/hr` 드라이버를 `hq` libnccl과 쓴다. 같은 이유로 대조의 차이는 라이브러리다 `[소스]`.

### 3. 실행기

- [run_trial_hr.sh](run_trial_hr.sh)(랭크 2개): `../peer/run_trial_hq.sh`의 복사본. 다른 점은 드라이버 번들 `DRVKEY`(기본 `BUILD`)와 meta의
  `drvkey`, `drvbin`뿐이다.
- [run_mr_hr.sh](run_mr_hr.sh)(랭크 N개): `../peer/run_mr_hq.sh`의 복사본. `MRKEY` 기본 `hr`, 작업 파일 접두, meta `runner=mrr`만 다르다.
- [run_bench_hr.sh](run_bench_hr.sh): rain에서 `hm_bench`를 한 번, sunny에서 ssh로 한 번 돌린다. 각 실행은 `timeout -s KILL 90` 안이다.
- [portpick.sh](portpick.sh): gin-peer의 복사본(29000–30999, 두 노드 확인, 확인하는 랑데부).
- 앞 실험의 실행기는 고치지 않는다. 이 실험은 iptables를 쓰지 않는다.

### 4. 호스트 메모리 벤치마크 ([hm_bench.cu](hm_bench.cu))

GPU 하나, NCCL과 네트워크 없음. 모든 단계는 정해진 수의 연산이고 호스트 감시가 60 s에서 끝낸다.
- 속성: `cudaDevAttrHostNativeAtomicSupported`, `cudaDevAttrCanMapHostMemory`.
- 지연: 스레드 하나가 앞 결과에 주소가 기대는 연산 20 000번(전역 타이머로 잼): 장치 메모리 `atom.add.gpu`(게이트 단어가 지금 하는 것), 호스트 매핑
  메모리 `atom.add.gpu`와 `atom.add.sys`, 장치와 호스트 메모리의 `ld.relaxed.sys`.
- 경합: 게이트 단어를 호스트 메모리에 둔 꼴. 장치 스레드 64개가 개수 절반에 1을 더하고 1을 빼기를(들어가기는 값을 돌려받는 원자 더하기, 나오기는
  감소) 호스트가 멈출 때까지 하고, 그동안 호스트는 위 절반에 약 20 µs마다 새 값을 쓰고 64번 다시 읽는다. 쓴 값이 아닌 것을 읽으면 장치의
  읽고-고쳐-쓰기가 호스트의 쓰기를 되돌린 것이다(`race_lost_host_writes`). 끝에 개수 절반이 0이 아니면 장치 갱신을 잃은 것이다.

### 빌드 ([build_hr.sh](build_hr.sh), 세션 스크래치)

1. `setup`: `agent_ts2hq`의 소스, `build/`, `build-hqp/`를 `agent_ts2hr`로 복사한다(`build-hqp/`는 `build-hrp/`가 됨). 의존 파일과 장치 manifest의
   경로를 바꾸고 원래 시각을 돌려준다. `agent_ts2hq` 작업 트리(= `../peer/hq_layer.diff`, md5 `34ab6201`)를 스크래치 저장소에 "gin-peer hq (libnccl
   c1311625)" 커밋으로 남긴다. 복사 직후 `make -n`은 버전 표시만 다시 컴파일한다 `[측정]`.
2. `hr`: 이 계층을 작업 트리에 두고 증분 빌드. 바뀐 장치 헤더는 NCCL 자신의 장치 객체가 포함하지 않아 장치 객체는 다시 컴파일하지 않는다
   `[측정]`. libnccl → `out/hr`.
3. `hrp`: `build-hrp/`에서 `CXXFLAGS=-DNCCL_GIN_TS_PRODUCTION`으로 증분 빌드. 두 빌드의 설치된 장치 헤더가 같은지 확인한다. libnccl → `out/hrp`.
4. `drivers`: `../gin_ts2.cu`, `gin_mr.cu`, `hm_bench.cu`를 `build/` 헤더로 컴파일(경고를 오류로). `out/drv/gin_ts2`, `out/drv/hm_bench`,
   `out/mr/gin_mr`, `out/build_info.txt`.

빌드는 nice 19, 유휴 I/O 우선순위, 8 작업으로 돌렸다(다른 실험이 같은 노드에서 돈다).

### 배포 ([deploy_hr.sh](deploy_hr.sh), 메인 세션)

두 노드의 새 디렉터리 `hr/`(libnccl, `gin_ts2`, `hm_bench`), `hrp/`(libnccl, `gin_ts2`), `mr/hr/`(`gin_mr`)에 둔다(8절 배포). 확인 출력은 파일로만
받는다. 배포 전에 sunny에서 포트 범위가 비어 있는지 읽기만 해서 확인한다. blind-apps가 같은 번들 트리에 새 디렉터리를 배포하는 중이면 "기존 번들 그대로"
확인이 틀리게 나오므로 그때는 피한다.

```
ssh <sunny> "ss -Htan '( sport >= :29000 and sport <= :30999 )' | wc -l"   # 0이어야 함(메인 세션)
cd /home/unionxic/rdma-error-wt/gin-remaining/harness/gpu-initiated/gin_recovery/remaining
bash deploy_hr.sh deploy_check.txt
```

### 실행 ([hold.sh](hold.sh), [chain.sh](chain.sh), [cells.sh](cells.sh))

hold마다 `chain.sh`가 `cluster_run.sh -w 10800 -t grm-<hold>`에 넣는다. 결과 폴더 아래 랭크 2개 시행은 빌드별 폴더(`hr/`, `hq/`, `hrp/`, `hqp/`)에,
랭크 4개 시행은 `mr_hr/`, `mr_hq/`에, 벤치마크는 `bench/`에 쌓인다.

| hold | 내용 | 시간 어림 |
|---|---|---|
| P0 pilot | 랭크 2개 새 셀과 대조 한 번씩(GPU 가득 참 `hr`, `hq`, 스트림 복사 대조, 호출 하나씩 셋 × 두 빌드), `f1_b`, `f4_b`, 4 KiB 지연 두 빌드(13회). 채점 안 함 | 약 2.5분 |
| P1 pilot | 랭크 4개 새 셀과 대조 한 번씩(순환 두 빌드, 시간 제한 없는 받기 두 빌드, gin-peer kill 셀, 사슬), 벤치마크 한 번(7회). 채점 안 함 | 약 3.5분 |
| H1 | 랭크 2개 회귀 6셀 × 5, `hdp_kill_b` 5, 지연 20실행 | 약 6분 |
| H2 | GPU 가득 참 `hr` 10과 `hq` 5(2:1), 스트림 복사 대조 5, 호출 하나씩 `hq` 15와 `hr` 9(섞어서) | 약 7분 |
| H3 | 순환 `hr` 10과 `hq` 5(2:1), 사슬 5 | 약 9분 |
| H4 | 시간 제한 없는 받기 `hr` 10과 `hq` 5(2:1), gin-peer kill 셀 `hr` 5 | 약 8.5분 |
| H5 | 랭크 4개 회귀 2셀 × 5, 벤치마크 5 | 약 5분 |

시간 어림 `[측정, 추론]`. hold 하나 = 시행마다 (`wall_s` + 2.7 s) + 31 s다(gin-peer pilot에서 잰 시행 사이 비용과 유휴 링크 대기).
- `wall_s`: 랭크 2개 회귀는 gin-peer 본 실행의 값(`f1_b` 3.8 s, `f3_b` 7.3–7.8 s, `bidirf_sym_b`와 `f2rel_b` 2.3 s, `f4_b`와 `hdp_kill_b` 5.3–5.8 s,
  `hd_rxdeath_b` 3.1 s, 4 KiB 지연 1.8 s, 256 KiB 2.3 s, 각 n=5), GPU 가득 참은 gin-handoff의 4.0–6.1 s(셀마다 n=5) `[측정]`.
- 랭크 4개는 gin-peer pilot의 kill 셀 18.1–20.1 s와 gin-multirank의 장애 없음 18.0 s, 순환 33.6 s(`hq` 대조), 사슬 약 20 s다 `[측정, 추론]`. `hr`의 순환과
  시간 제한 없는 받기는 약 19 s, 그 `hq` 대조는 kill 9 s + application 15 s + 정리로 약 28 s로 어림한다 `[추론]`.
- 가장 긴 H3도 880 s 안이다. 본 실행(H1–H5)의 클러스터 시간은 잠금 대기를 빼고 약 36분이다 `[추론]`.

```
cd /home/unionxic/rdma-error-wt/gin-remaining/harness/gpu-initiated/gin_recovery/remaining
bash chain.sh results/<날짜>_pilot P0 P1          # pilot, 채점 안 함
bash chain.sh results/<날짜> H1 H2 H3 H4 H5        # 본 실행(태그 뒤)
bash chain.sh results/<날짜> fill:<폴더>:<셀>@<빌드>:<수>:<시작번호>[,...]   # 제외된 시행 채우기
```

### 채점

```
python3 score.py results/<날짜>
```

`results/<날짜>/SCORE.md`와 `results/<날짜>/trials_scored.csv`가 나온다. 원시 로그는 Release에 올린다.

## 10. 완료 조건과 QA 기준

- [ ] 메인 세션이 pilot(P0, P1)을 돌리고 결과를 12절에 적은 뒤, 고칠 것을 고치고 태그를 달았다.
- [ ] 모든 셀이 계획한 반복 수만큼 실행됐다. 제외와 실패를 따로 센 표가 있다(`SCORE.md` 끝 표).
- [ ] 예측 33줄마다 판정(맞음, 틀림, 자료 부족)과 놓친 시행 목록이 있다.
- [ ] 다른 에이전트가 `score.py`를 보지 않고 원자료에서 핵심 수치를 다시 셌다(handshake timeout과 복구 시각, 기다림 안 응답, degraded 해제와 받기 해제
  시각, 생존 간선, 복사 경로와 스트림 복사 수, 복사 시간 초과, 확인 복사, 지연, 벤치마크).
- [x] 다른 에이전트가 `hr_layer.diff`를 읽고 리뷰했다(12절).
- [ ] 다른 에이전트가 드라이버, 실행기, 채점 코드를 리뷰했다.
- [ ] smoke와 pilot, 제외 시행이 결과에 섞이지 않았다.
- [ ] 새 빌드의 md5, 전체 diff, pristine + diff 확인, 운영 빌드의 strings 확인을 5절과 12절에 적었다.
- [ ] 원자료를 Release에 올리고 `DATA.md`에 적었다.
- [ ] hold 전후 mlx5 스냅숏에 새 명령 오류가 없었고, iptables 규칙이 늘지 않았고, CUDA 메모리 오류가 없었다.

## 11. 작업 체크리스트

- [x] 앞 실험의 측정과 리뷰 지적 다시 확인(1절)
- [x] 라이브러리 계층(중첩 준비, 기다림 안 응답, degraded와 `tsWaitWord`, NIC 복사 경로)
- [x] 드라이버: `gin_ts2`의 세 호출 나누기, `gin_mr`의 시간 제한 없는 받기, `hm_bench`
- [x] 빌드: `hr`, `hrp`, 드라이버 셋. pristine + diff 확인(12절)
- [x] 독립 리뷰(다른 에이전트)와 반영(12절)
- [x] `run_trial_hr.sh`, `run_mr_hr.sh`, `run_bench_hr.sh`, `portpick.sh`, `cells.sh`, `hold.sh`, `chain.sh`, `deploy_hr.sh`, `rows_hr.py`, `score.py`,
  `predictions.csv`
- [x] 채점기 합성 시험(실제 측정 아님, 12절)
- [x] 질문, 가설, 셀, 예측 초안 (`DRAFT`)
- [ ] sunny 포트 범위 확인과 배포(메인 세션)
- [ ] pilot P0, P1(메인 세션, 채점 안 함), 결과로 고칠 것 고치기
- [ ] 고정 절 완성, 상태 `PREREGISTERED`, 해시 기록을 커밋 하나로 만들고 그 커밋에 `prereg/` 태그
- [ ] 본 실행 H1–H5 (`RUNNING`)
- [ ] 채점 (`QA`)
- [ ] 독립 재계산과 측정 코드 리뷰
- [ ] 결과 정리, 원자료 Release, PR
- [ ] 결론 확정 (`COMPLETE`)

## 12. 실행 기록 (시간순)

| 시각 | 무엇을 했나 | 결과와 근거(경로, 커밋, 실행 ID) |
|---|---|---|
| 2026-10-09 | 앞 실험의 측정을 다시 셈: gin-multirank 순환 5회(handshake timeout 시행마다 3, 첫 거절 24 504.5–24 507.2 ms, 복구 0), 사슬 5회(투명, 2 080.8–2 089.4 ms), gin-handoff GPU 가득 참 2 × 2(셀마다 5회), gin-peer rank 3 kill 상대별 flush 10회(죽은 rank 받기 3개 모두 한도) `[측정: 세 실험의 trials_scored.csv]`. rain의 모듈과 GPU 드라이버 매개변수를 읽기만 해서 확인 `[측정]` | 1절, 5절 |
| 2026-10-09 | 스크래치 `agent_ts2hr` 준비(`build_hr.sh setup`): `agent_ts2hq`(작업 트리 md5 `34ab6201`, 빌드 `c1311625`, 운영 빌드 `4fa076e1`) 복사, 경로 바꿈, "gin-peer hq" 커밋. 복사 직후 `make -n`의 컴파일 명령 1개(버전 표시) `[측정]` | [build_hr.sh](build_hr.sh) |
| 2026-10-09 | 계층 구현(9절 1번), 드라이버(9절 2번), 벤치마크(9절 4번), 실행기, 셀, hold, 채점기, 예측 초안 | 이 폴더 |
| 2026-10-09 | 첫 빌드(리뷰 전) `hr`, `hrp`, 드라이버. 컴파일 경고 0(NCCL 자체 파일 `symmetric_sched.cc`의 기존 경고 하나 빼고) `[측정]` | 세션 스크래치 `hr_work/build_*.log` |
| 2026-10-09 | 채점기 합성 시험(측정 아님). 앞 실험의 Release 자산에서 실제 시행 다섯(gin-handoff `hf_hog_f1_b` n1과 `hf_hogpre_f1_b` n2, gin-peer `f1_b` n1과 `mr4_kill3_peer` n1, gin-multirank `mr4_cyc_stall` n1)을 이 실험의 셀 이름과 빌드로 옮기고, 이 계층 형식의 줄과 kv를 손으로 붙인 폴더와 만든 벤치마크 kv 하나로 `score.py`를 돌렸다. 예외 없이 33줄을 모두 평가했고(계획 수 그대로면 모두 자료 부족, 계획 수 1로 바꾼 사본에서 판정식이 돎), 설정 확인 다섯 종류가 모두 통과했으며, 붙인 줄에서 나온 열이 기대값과 같았다(예: `served` "1-0", `kept` "0-2", `rel_after_dead_ms_r0` 2015, `degr_after_dead_ms_r0` 2012, `n_rel_surv` 6, `td_stream_copies_r0` 0, `hog_calls_after_r0` "load,malloc,stream") | 세션 스크래치 `hr_work/make_synth.py`, `hr_work/synth_res/` |
| 2026-10-09 | 독립 리뷰(다른 에이전트, 읽기만, `hr_layer.diff`와 스크래치 트리). 판정 "고치면 쓸 수 있음", 막는 결함 없음. 높음 2(H1 낡은 미룬 REQ에 답해 방금 복구한 쌍을 거절, H2 루프백이 실험 GID에 묶여 주소를 지웠다 붙이면 실패), 중간 2(M1 중첩 라운드의 시계, M2 칸 0을 늘 뺀 게시 전 확인), 낮음 8(L1 기다림 중 거절 뒤 펌웨어 번호, L2 미룬 REQ 앞의 FAIL과 BYE, L3 약한 자체 시험, L4 GIN PD의 원격 쓰기 MR, L5 application `ncclGinRecoverAbort`의 의미, L6 복사 멈춤 스위치의 뜻, L7 로그 형식, L8 문맥 생성 때 NIC 실패), 사소 4. 답: 중첩의 준비 상태, 멈춤 수, 범위, 펌웨어 번호는 모든 길에서 맞고 교착 없음 논증이 성립, degraded의 잠금과 수명이 맞음, NIC 경로의 flush, 수명, 덮는 복사 자리가 맞음 | 리뷰 보고는 이 세션의 에이전트 응답(파일 없음) |
| 2026-10-09 | 리뷰 반영(9절 1번에 각 항목): H1(미룬 REQ를 그 상대와 라운드가 시작하거나 더 새 REQ에 답할 때 버림, 답하기 전 소켓을 읽음), H2(link-local GID 후보와 루프백 READ 확인, 오류 때 스트림으로 이어 복사), M1(중첩 라운드는 바깥 시계, 8 000 ms가 안 남으면 중첩 안 함), M2(상대 단어가 모든 게이트에 들어가기 전에는 칸 0도 셈, 헤더 요건을 주석과 9절에 적음), L1, L2, L3(모든 MR 읽기와 되쓰기), L4(자기 PD), L5(application 호출은 앞 빌드 의미), L6(주석과 9절), L7(늦은 완료 줄을 gin-handoff 형식으로, 끔 줄을 한 형식으로, `rows_hr.py`에 `lb_gid_r*`, `td_fallbacks_r*`), L8(H2의 이어 복사로), 사소 넷(이유 없는 끔 줄, 포트 1의 GID, 떼어 낸 helper의 정리 줄은 join 뒤에만 경로 상태를 읽음, 람다 이름). 고치지 않음: `tsPoll`의 abort 탈출이 QP를 오염 표시하지 않는 것(앞 빌드와 같음, M2의 게시 전 확인이 막음) | [hr_layer.diff](hr_layer.diff) |
| 2026-10-09 | 리뷰 반영 뒤 마지막 빌드 `[측정]`: `hr` libnccl `2dee2b5bf36b3477dd85f0197987f028`, `hrp` `786f70bcb82ea21cb678dcb056256ed5`, `gin_ts2` `4e81d8d8e7418f84fe1804284378d618`(소스 `1779db9d`), `gin_mr` `d588e9cecfc05fd114e61d83ce9c3074`(소스 `a6a526ad`), `hm_bench` `a00094b07445f2ddc5baff3a5c5626bb`(소스 `9b13a4b8`). 이 계층 파일의 컴파일 경고 0. `make_diff_hr.sh`: `hr_layer.diff` md5 `66f61272`(1 578줄, 계층 파일 3개 +1 045/−68), `gin_transparent_hr.diff` md5 `de986325`, 두 재구성 모두 VERIFIED. 드라이버 md5는 다시 빌드하면 바뀐다(nvcc가 임시 이름을 넣음) `[측정: 리뷰 전 빌드와 다름]`. 기대 md5는 [deploy_hr.sh](deploy_hr.sh)에 넣음 | 세션 스크래치 `agent_ts2hr/out/build_info.txt` |
| 2026-10-09 | 채점기 합성 시험 다시(리뷰 반영 뒤의 `rows_hr.py`): 33줄 모두 평가, 새 열 `lb_gid_r*`, `td_fallbacks_r*`가 표에 있음. 새 형식의 시작 줄, 끔 줄, 정리 줄, 미룬 REQ 버림 줄, 늦은 완료 줄을 정규식에 넣어 확인 | 세션 스크래치 `hr_work/synth_res/` |
| 2026-10-09 | (초안까지) 클러스터에서는 아무것도 돌리지 않았다. 배포, pilot, 본 실행은 메인 세션이 한다 | |

## 13. 사전 등록 이후 변경

> 기존 문장을 고치지 않고 여기에 덧붙인다.

| 날짜 | 무엇을 | 이유 | 영향 범위 | 커밋 |
|---|---|---|---|---|

## 14. 원자료와 결과표

| 무엇 | 경로 또는 Release 자산 | n |
|---|---|--:|

## 15. 결과 요약

`[미확인]` 아직 측정 전이다.

## 16. QA와 재현성

`[미확인]` 아직 측정 전이다. 재현: [gin_transparent_hr.diff](gin_transparent_hr.diff)(pristine NCCL v2.32.3-1 기준)로 만든다. `hrp`는 같은 소스에
`-DNCCL_GIN_TS_PRODUCTION`. 빌드 절차는 [build_hr.sh](build_hr.sh), 배포는 [deploy_hr.sh](deploy_hr.sh)(md5 확인), 실행은 9절.

## 17. 결론

## 18. 한계

## 19. 다음 작업

## 20. 참고자료

- `../multirank/EXPERIMENT.md` 1절(순환 대기), 15, 19절
- `../peer/EXPERIMENT.md` 9절 1번 (b), (h), 18, 19절, `../peer/qa/code_review.md` M1
- `../handoff/EXPERIMENT.md` 9절 2번(GPU 가득 참의 원인과 고치지 않은 이유), 15, 17절, 13절의 리뷰 L6
- CUDA C++ Programming Guide: implicit synchronization, lazy loading, mapped memory의 원자 연산 `[문서]`
