# GIN 투명 복구: 남은 세 문제(순환 대기, 상대를 모르는 대기, application의 CUDA 호출) (gin-remaining)

**목적:** 앞 실험들이 남긴 세 문제(시작 쪽 셋 이상의 순환 대기, 랭크 3개 이상에서 풀리지 않는 상대를 모르는 대기, application의 CUDA 호출에
막히는 복구 복사)를 라이브러리 계층 하나로 고치고, 고친 동작과 바뀌지 않아야 할 동작을 사전 등록한 예측으로 잰다.

| 항목 | 값 |
|---|---|
| 상태 | `COMPLETE` |
| 담당자 | @unionxic |
| 작성일 | 2026-10-09 |
| 기준 브랜치와 커밋 | `exp/gin-remaining` @ `ae3dafc9` (master) |
| 사전 등록 태그 | `prereg/gin-remaining-v1` (`b0489048`, 상태를 `PREREGISTERED`로 바꾼 바로 그 커밋) |
| 마지막 갱신 | 2026-10-09, 마감: 본 실행 H1–H5, 채점(34개 중 33개 맞음), 독립 재계산, 코드 리뷰, Release(10–20절) |

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

**고정 시점.** 예측은 메인 세션이 pilot(9절의 hold P0, P1, 그리고 P0, P1 뒤에 더한 NIC 게이트 시험의 P2)을 돌린 뒤 확정한다. pilot 시행은 채점하지 않으며, 그 결과 폴더(`results/<날짜>_pilot/`)는
채점 대상 폴더와 따로 둔다. pilot은 판정이 아니라 셀 조건과 열 읽기를 확인하는 데만 쓴다. pilot에서 예측과 다른 결과가 나와도 예측 문장, 판정식,
기준 수는 바꾸지 않고 의심만 적는다. 읽기 오류(열 정의, 파서)와 셀 조건(장애 시각, 셀이 조건을 만들지 못함)은 고칠 수 있고, 고친 셀은 태그 전에
pilot을 한 번 더 돈다(8절). 예측은 태그 `prereg/gin-remaining-v1`을 단 커밋에서 고정되고, 그 뒤에는 2, 3, 7, 8절과 `predictions.csv`를 고치지
않는다.

예측 원문은 [predictions.csv](predictions.csv)이고 34줄이다. `kind`는 N(새 동작), C(대조), R(회귀)다. 호출 하나씩 셀(H4)과 호스트 메모리
벤치마크(H6)는 이 테스트베드에서 잰 적이 없어 문서에서 이끈 예측이다. 33줄은 pilot 전에 썼고 pilot 뒤에 바꾸지 않았다. NG1(NIC 게이트 시험)은
재리뷰 M-B를 받아 P0, P1 뒤에 시험과 함께 더했고, 그 시험을 한 번도 돌리기 전에 썼다(12절).

### 3.1 판정에 쓰는 열

시행마다 한 줄이다.
- 랭크 2개 시행: 열은 `../scripts/ts2/rows.py`, `../s2_close/rows_extra.py`, `../pair_check/rows_pc.py`, `../oneway/rows_ow.py`,
  `../harden/rows_hd.py`, `../handoff/rows_hf.py`, `../peer/rows_pq.py`가 원래 정의 그대로 만들고(각 실험 3.1절), 이 폴더의 [rows_hr.py](rows_hr.py)
  `extra_hr2()`가 새 열을 붙인다.
- 랭크 4개 시행: `../multirank/rows_mr.py`의 `rows_of()`와 `../peer/rows_pq.py`의 `extra_pq4()`에 `extra_hr4()`가 새 열을 붙인다.
- 벤치마크 시행: `bench_row()`. NIC 게이트 시험(9절 5번): `ngt_row()`.
- 새 열의 정의 원문은 `rows_hr.py` 머리말이다. 요약:

| 열 | 정의 |
|---|---|
| `hr_on_r*`, `copy_path_r*`, `lb_on_r*`, `lb_off_r*` | 이 실험 시작 줄(`GIN/TS: remaining=1 rank=<r> copy_path=<nic\|stream> ...`)의 수와 복사 경로, NIC 복사 경로를 켠 줄과 끈 줄의 수 |
| `td_path_r*`, `td_stream_copies_r*` | 정리 때 줄 `GIN/TS: rank <r> copy path at teardown: path=... stream_copies=<d> ...`의 경로와, helper가 스트림으로 한 복사의 수 |
| `hog_calls_after_r*`, `drvkey` | 드라이버 kv `hog_calls_after`(GIN 커널 뒤에 한 호출), 실행기 meta의 드라이버 번들 |
| `served`, `n_served`, `kept`, `n_kept` | 기다림 안 응답 줄과 미룬 REQ 줄, "R-P"(rank R이 rank P의 REQ에 답함, 미룸) 목록. 기다림 안에서 REQ를 거부한 것(NACK 12, 2, 16)도 응답으로 센다 |
| `served_rec`, `n_served_rec` | 그중 중첩 라운드가 R의 응답 쪽 복구 줄(상대 P)로 끝난 것(`back to round` 줄 전). 판정에 쓰지 않는 설명용 열이다(재리뷰 L-A, 12절) |
| `n_degraded`, `degr_ranks`, `degr_after_dead_ms_r*`, `dead_ms_r*` | why=degraded인 칸 0 해제 줄의 수와 rank, 그 줄 − 그 rank의 첫 죽음 판정 줄(같은 프로세스의 시계) |
| `rel_dead_r*`, `rel_after_dead_ms_r*`, `n_rel_dead`, `n_rel_surv` | 드라이버 kv(9절 2번): 생존 rank의 죽은 rank 받기가 풀렸는지, 풀린 것을 호스트가 본 시각 − 죽음 판정 줄, 그런 생존 rank 수, 생존 rank 사이 받기 중 풀린 것의 수 |
| `surv_tx_ok`, `n_kdone_surv`, `n_stuck_surv`, `rx_untimed` | 생존 rank 사이 보내기 중 끝까지 성공한 것, 커널이 끝난 생존 rank, application이 포기한 생존 rank, 시간 제한 없는 받기 표시 |
| `host_native_atomic_*`, `lat_*_ns_*`, `race_*_*` | 벤치마크 kv(노드별 `_rain`, `_sunny`, 9절 4번) |
| `ng_result_*`, `ng_rounds_*`, `ng_lost_writes_*`, `ng_lost_inc_*`, `ng_dekker_*`, `ng_inside_nonzero_*`, `ng_quiesce_timeouts_*`, `ng_idx_ok_*`, `ng_mr_*`, `ng_gid_kind_*`, `ng_error_*` | NIC 게이트 시험 kv(노드별, 9절 5번): 판정(PASS, FAIL), 두 단계 중 작은 라운드 수, 두 단계 합의 위반 수, 색인 단어 갱신을 모두 지켰는지, GPU MR 종류, 루프백 GID 종류, 준비나 NIC 요청 실패의 이유 |

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
`nic_gate_test`: 9절 5번.

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
| NIC 루프백의 4 B 에폭 쓰기와 읽기(이 계층의 NIC 복사 경로와 같은 방식)로 돈 게이트 규약에서 두 GPU 모두 쓰기 손실, 개수 손실, Dekker 위반, 정지 시간 초과가 없음(단계마다 라운드 1 000 이상) | NG1 | `nic_gate@hr` | 5/5 | L2가 NIC의 PCIe 쓰기와 SM 원자 연산을 함께 처리함, 복사 엔진은 gin-s2 `gate_ce_test` 14/14 두 번 `[추론, 복사 엔진은 측정]` |

벤치마크의 `race_lost_host_writes`(호스트가 쓴 높은 절반을 장치의 읽고-고쳐-쓰기가 되돌린 횟수)는 예측 없이 잰다. 이 플랫폼에서 장치가 호스트
메모리 원자 연산을 PCIe 원자 연산으로 하는지 모른다 `[미확인]`.

판정식을 읽을 때의 주의(재리뷰, 12절).
- CY3은 기다림 안에서 REQ를 거부한 것도 응답으로 센다(L-A). 순환을 새 규칙이 끊었다는 근거는 CY1(handshake timeout도 거절도 없이 세 쌍 모두
  복구)이 진다. 중첩 라운드가 실제로 복구로 끝난 수는 설명용 열 `n_served_rec`로 따로 보고한다.
- degraded 시계는 죽음 판정 줄이 아니라 그 뒤의 거절에서 시작한다(L-B, `gdakiUaRaisePeer`). DG1, DG2의 열은 죽음 판정 줄부터 잰다. 이 실험의 kill
  셀에는 겹치는 라운드가 없어 거절이 판정 직후에 온다(pilot 6.0–8.5 ms, 9절 1번 (c)). 라운드 도중의 죽음은 그 라운드가 끝날 때까지 거절이 늦고
  해제도 그만큼 늦는다. 이 실험의 셀에는 없다.

## 4. 범위

**포함.**
- 9절 1번의 라이브러리 계층 하나([hr_layer.diff](hr_layer.diff), `hq` 트리 기준, 3개 파일)와 그 운영 빌드.
- 드라이버: `../gin_ts2.cu`의 세 호출 나누기(`GIN_TS_HOG_CALLS`), 이 폴더의 [gin_mr.cu](gin_mr.cu)(시간 제한 없는 받기), 새 벤치마크
  [hm_bench.cu](hm_bench.cu), 새 NIC 게이트 시험 [nic_gate_test.cu](nic_gate_test.cu)(pilot 뒤에 더함, 9절 5번).
- 이 실험의 실행기([run_trial_hr.sh](run_trial_hr.sh), [run_mr_hr.sh](run_mr_hr.sh), [run_bench_hr.sh](run_bench_hr.sh),
  [run_ngt_hr.sh](run_ngt_hr.sh))와 포트 고르기([portpick.sh](portpick.sh), gin-peer의 복사). 앞 실험의 실행기는 고치지 않는다.
- 7절의 셀 키 30개.

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
| GPU 드라이버와 모듈 | rain: NVIDIA open kernel module 570.211.01, `nvidia_peermem` 적재됨, `gdrdrv` 없음, `RegistryDwords: "PeerMappingOverride=1;"` | `[측정]` 2026-10-09 rain(`lsmod`, `/proc/driver/nvidia/params`, `/proc/driver/nvidia/version`, 읽기만). sunny의 모듈은 `[미확인]`. 두 노드 모두 NIC 복사 경로의 GPU MR이 dmabuf로 등록되고 자체 시험을 통과했다 `[측정: pilot, 12절]` |
| `hq`, `hqp` 번들 | libnccl `c1311625c7a06c785bc313558504f982`, `4fa076e113e43774a9dc2f46298df43b`, 드라이버 `3e053ff2`, `gin_mr` `7f0fc272` | gin-peer 배포 확인(`../peer/deploy_check.txt`) `[측정, 이전 실험]`. 스크래치 `agent_ts2hq/out/`에서 같은 md5 `[측정]` 2026-10-09 |
| `hr`, `hrp`, 새 드라이버 | 12절의 마지막 빌드 줄. [deploy_hr.sh](deploy_hr.sh)의 기대 md5와 같다. 배포 확인은 [deploy_check.txt](deploy_check.txt) | `[측정]` 빌드 때 rain(세션 스크래치 `agent_ts2hr/out/`, `out/build_info.txt`), 배포 2026-10-09 13:55:57–13:56:28 |
| NIC 게이트 시험 | `nic_gate_test` `abb2af4cb61a8075242f348c599b407a`(소스 `4d87f2b8`), 새 디렉터리 `ngt/`. [deploy_ngt.sh](deploy_ngt.sh)의 기대 md5와 같다 | `[측정]` 빌드 때 rain(`agent_ts2hr/out/ngt/build_info.txt`). 배포 전 (이 칸을 쓴 때의 상태. 14:44 배포, [deploy_ngt_check.txt](deploy_ngt_check.txt), 13절) |
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
| `nic_gate` | rain(mlx5_1)과 sunny(mlx5_0)의 GPU 0에서 `nic_gate_test` 한 번씩, 단계 a와 b 각 5 s(9절 5번). 재리뷰 M-B로 pilot 뒤에 더함 | `@hr` 5 | 새 셀 |

**합계.** 셀별 계획 수의 원문은 [score.py](score.py)의 `PLANNED`다.

| 종류 | 랭크 2개 시행 | 랭크 4개 시행 | 지연 실행 | 벤치마크 실행 | NIC 게이트 시험 실행 |
|---|--:|--:|--:|--:|--:|
| 새 셀 | 34(`hr`: GPU 가득 참 10, 호출 하나씩 9; `hq`: 호출 하나씩 15) | 25(`hr`: 순환 10, 시간 제한 없는 받기 10, gin-peer kill 셀 5) | | 5 | 5 |
| 대조 | 10(GPU 가득 참 `hq` 5, `hr` 스트림 복사 5) | 10(`hq`: 순환 5, 시간 제한 없는 받기 5) | 20(`hrp` 10, `hqp` 10) | | |
| 회귀 | 35(`hr` 30, `hrp` 5) | 15(사슬, 장애 없음, 한 쌍 로컬 QP 오류 각 5) | | | |
| 합 | 79 | 50 | 20 | 5 | 5 |

셀 키 30개(지연 4개 포함). 예측 34줄: 새 동작 19(벤치마크 셋, NIC 게이트 시험 하나 포함), 대조 6(지연 2 포함), 회귀 9.

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
- NIC 게이트 시험: 어느 노드든 판정 없이 끝나면(종료 코드가 0, 1이 아님: 준비 실패 2, 단계 중 NIC 요청 실패 3, CUDA 오류 6, 감시 종료 7, 시간 초과
  137) 제외하고 따로 센다. 판정 FAIL(종료 코드 1)은 제외가 아니라 결과다. 쓰기를 잃어도 다시 써서 이어 가므로, 잃은 쓰기는 감시 종료가 아니라 FAIL로
  나온다.
- 채우려고 다시 돈 시행이 셀 키마다 계획의 50%를 넘으면 그 셀 키는 멈추고 "자료 부족"으로 둔다.

**설정 확인.** 하나라도 어긋나면 제외가 아니라 그 블록을 멈춘다.
- 랭크 2개 `hr` 시행: 두 rank(kill된 rank 빼고)에 gin-harden 시작 줄(`production=0`), gin-handoff 시작 줄, gin-peer 시작 줄, 이 실험 시작 줄, 투명 복구
  시작 줄, 사용자 devComm abort 단어 줄. 복사 경로가 셀과 같고(`rh_hog_copystream_f1_b`만 stream, 나머지 nic), nic 셀에 NIC 경로 끔 줄이 없음.
  meta의 드라이버 번들이 `hr`.
- 랭크 2개 `hq` 시행: 이 실험 시작 줄만 없음. 드라이버 번들 `hr`.
- `hrp`, `hqp`: 시작 줄이 WARN에 없고 kv에 `rs_api=1`, `rs_contexts >= 1`. 드라이버 번들은 자기 번들.
- 시험 스위치 줄이 없음(이 실험의 랭크 2개 셀은 시험 스위치를 쓰지 않음). GPU 가득 참 셀은 kv `hog_calls_after`가 셀과 같음.
- NIC 게이트 시험: 두 노드 모두 kv `mr=dmabuf`, `gid_kind=link-local`(`config_ngt`).
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
  벤치마크와 NIC 게이트 시험은 `timeout -s KILL 90` 안에서만 돈다. 시행 뒤 남은 프로세스는 읽기만 해서 세고, 두 시행 연속이면 `STOP_left`. 다음
  hold는 남은 `gin_ts2`, `gin_mr`, `hm_bench`, `nic_gate_test`가 없어질 때까지 150 s까지 기다리고, 그래도 있으면 시행을 돌지 않는다.
- **CUDA 메모리 오류.** hold 안의 어느 시행이든 rank나 벤치마크의 종료 코드 139이거나 로그, kv에 illegal address, illegal memory access, unspecified
  launch failure가 보이면 그 hold 뒤로 멈춘다(`STOP_cuda`).
- **mlx5 오류.** hold 앞뒤에 두 노드의 mlx5 커널 줄 전체와 rain의 펌웨어 명령 계수를 남긴다. 새 명령 오류 줄이나 펌웨어 명령 실패 계수 증가가 보이면
  그 hold 뒤로 멈춘다(`STOP_mlx5`).
- **배포.** 새 번들은 새 디렉터리 `hr/`, `hrp/`, `mr/hr/`, NIC 게이트 시험은 `ngt/`에만 둔다. 대상 파일이 이미 있거나 소스가 기대 md5와
  다르면 배포 스크립트가 멈춘다. 배포 뒤 기존 번들 파일의 md5가 두 노드에서 그대로인지 확인한다. `hq/`, `hqp/`는 읽기만 한다(다른 실험 blind-apps가 같은 때 쓴다).

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
- NIC 경로는 pilot에서 `hr`의 모든 rank에서 link-local GID(색인 1)로 켜졌고 끈 줄은 없었다 `[측정: pilot, 문맥 28개, 12절]`. 실패하면 GIN GID로,
  그것도 실패하면 스트림 경로다(시작 줄로 보임). 오류로 꺼진 NIC 경로는 그 문맥에서 다시 켜지지 않는다.
- NIC 경로의 4 B 게이트 쓰기의 원자성은 위 (d)의 `[미확인]`이다. NIC 게이트 시험(9절 5번, NG1)이 이것을 따로 잰다.
- 장치 대기의 abort 탈출(`tsPoll`)은 QP를 오염 표시하지 않는다(앞 빌드와 같음). degraded 뒤의 안전은 위 (c)의 게시 전 확인에 기댄다 `[소스]`.

(f) **재리뷰가 남긴 점**(리뷰 반영 뒤의 계층, 판정 "조건부로 그대로 실행 가능", 막는 결함과 높음 없음, 12절). 계층은 고치지 않았다(배포한 라이브러리
그대로). 줄 번호는 `hr_layer.diff`를 적용한 트리의 `gin_host_gdaki.cc`다.
- 중간 M-A: `gdakiTsServeLower`는 중첩 가능 여부(`gdakiTsCanNest`)를 한 번 훑을 때 한 번만 보고, 중첩 라운드 뒤에도 다음 상대로 넘어간다. 한 번에
  낮은 rank의 REQ 둘이 오면 첫 중첩의 정지가 최대 5 s 돌고(바깥 시간으로 잘리지 않음), 둘째가 8 s가 안 남은 채 시작해 바깥 라운드가 25 s를 넘길 수
  있다. 그러면 감시가 드러내고 그 문맥의 다음 라운드는 모두 거절된다. 사전 등록한 셀에서는 생기지 않는다(순환과 사슬 셀에서 한 rank에 낮은 rank의
  REQ는 하나) `[추론]`. 나중에 고칠 것: 중첩 라운드 뒤 돌아가거나 상대마다 다시 보기.
- 중간 M-B: NIC의 4 B 게이트 단어 쓰기와 SM 64비트 원자 연산의 관계는 확인하지 않았다. 회귀 셀의 모든 라운드가 이 쓰기를 한다. 잃은 갱신은 드문
  정지 시간 초과나 거절로만 보이고 n=5로는 잡지 못할 수 있다. `hm_bench`는 호스트 매핑 메모리를 재지 NIC의 GPU 메모리 쓰기를 재지 않는다. 그래서
  NIC 게이트 시험(9절 5번)을 더했다. 그 결과가 나오기 전까지 이 점은 `[미확인]`이다.
- 중간 M-C: 앞 헤더로 빌드한 장치 코드는 알아낼 수 없다(`gin_gdaki.h` `tsWaitWord`가 없음). degraded 뒤 그 코드의 건강한 상대 대기가 오류로 끝나고, 그
  상대와의 다음 라운드가 그 연산을 다시 낼 수 있다(위 (c)). 이 실험의 드라이버는 모두 `hr` 헤더라 생기지 않는다. 나중에 고칠 것: 새 경로가 세우는 게이트
  깃발, 또는 운영 빌드에서 degraded를 켤 때만 쓰기.
- 낮음 L-A: CY3은 거부(NACK 12, 2, 16)도 기다림 안 응답으로 센다(3.3 주의). 설명용 열 `n_served_rec`를 더했다.
- 낮음 L-B: degraded 시계는 거절에서 시작한다(3.3 주의). 라운드 도중의 죽음은 그 라운드가 끝날 때까지 상대 표시만 남는다.
- 낮음 L-C: 자체 시험은 문맥을 만들 때 스트림 복사를 쓴다. application이 이미 GPU를 붙잡은 채 devComm을 만들면 자체 시험이 시간을 넘겨 NIC 경로가
  꺼질 수 있다. 이 실험의 셀은 GIN 커널 전에 devComm을 만든다.
- 낮음 L-D: 잘못된 죽음 판정(살아 있는 rank를 죽었다고 봄)도 2 s 뒤 그 communicator의 상대를 모르는 대기를 모두 푼다. 설계의 대가로 둔다.
- 첫 리뷰 반영 확인: H1, H2(코드. 루프백은 pilot에서 처음 돔), M2, L1–L6, 사소 넷은 맞음. M1은 부분(위 M-A). L8은 부분: 게이트를 처음 쓸 때 NIC
  요청이 시간을 넘기면(오류 완료가 아니라) 그 rank의 투명 복구가 꺼진다.
- 맞다고 확인한 것: 중첩 라운드의 상태, 멈춤 수, 잠금, 범위 복원, 바깥 상대의 ACK, 펌웨어 번호, 교착 없음 논증(16.5 s 뒤에는 앞 빌드처럼 시간 초과로
  돌아감), 미룬 REQ, degraded 계수와 장치 읽기, 루프백 수명과 스트림으로 이어 하기. flush READ의 순서 보장은 relaxed ordering이 꺼져 있다는 가정에
  기댄다 `[미확인: 이 하드웨어]`. `hrp`는 새 코드를 더하지 않고 로그 수준만 다르다.

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
- [run_ngt_hr.sh](run_ngt_hr.sh): `run_bench_hr.sh`의 복사본. `nic_gate_test`를 rain(mlx5_1)에서 한 번, sunny(mlx5_0)에서 ssh로 한 번 돌린다. 각 실행은
  `timeout -s KILL 90` 안이다.
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

### 5. NIC 게이트 시험 ([nic_gate_test.cu](nic_gate_test.cu))

재리뷰 M-B(9절 1번 (f))를 받아 P0, P1 뒤에 더했다. 계층과 배포한 번들은 바꾸지 않는 독립 프로그램이다. NCCL 없음. 노드마다 GPU 0과 그 노드의
HCA(rain mlx5_1, sunny mlx5_0) 포트 1을 쓰고, 트래픽은 NIC 밖으로 나가지 않는다(루프백).
- gin-s2의 `../gate_ce_test.cu`(복사 엔진으로 같은 규약을 확인한 시험, 14/14 두 번)와 같은 게이트 규약과 확인이다. 다른 점은 호스트의 GPU 메모리 읽기와
  쓰기를 모두 이 계층의 NIC 복사 경로와 같은 방식으로 한다는 것이다(`gdakiLbXfer`): 4 B 쓰기는 스테이징 버퍼에서 RDMA WRITE 하나와 같은 MR의 8 B
  RDMA READ(신호), 읽기는 RDMA READ 하나. 루프백 RC QP 쌍은 자기 PD에 있고 RoCE v2 link-local GID로 연결한다. GPU 메모리는 dmabuf MR(안 되면
  nvidia-peermem), relaxed ordering 없음.
- 장치: 스레드가 게이트 단어(GPU 메모리 64비트)에 `atom.acquire.gpu.add` 1로 들어가고 `red.release.gpu.add` −1로 나온다(`gin_gdaki.h`
  `tsWordEnter`, `tsWordLeave`와 같은 명령). 에폭이 홀수면 물러나 쉰다. 게이트 단어는 이 계층처럼 128 B 줄의 88 B 자리에 있고, 안에 들어간 스레드는
  같은 줄의 0 B와 8 B 자리 색인 단어 둘(보내기가 들어가 있는 동안 원자 연산으로 고치는 `sq_rsvd_index`, `sq_ready_index` 자리)에 1씩 더한다.
- 호스트: 에폭을 홀수로 쓰고, 단어를 읽어 개수 0을 기다리고(2 s 한도), 0.2 ms 동안 증인을 다시 읽고, 다음 짝수 에폭을 쓰기를 되풀이한다.
- 확인: 쓴 뒤 읽은 위 절반이 쓴 값과 다름(NIC 쓰기 손실; 멈춤 깃발 쓰기도 다시 읽음; 손실은 세고 다시 써서 시험을 이어 감), 끝난 뒤 개수 절반이
  0이 아님(장치 갱신 손실), 끝난 뒤 색인 단어가 들어간 수와 다름, 개수 0을 본 뒤 옛 에폭으로 들어간 스레드(Dekker 위반), 홀수 에폭 동안 안에 있는
  스레드, 정지 시간 초과. 통과에는 시험이 돌았다는 근거도 든다: 라운드, 들어간 스레드, NIC가 쓴 홀수 에폭을 보고 물러난 스레드가 모두 0보다 크고,
  커널이 끝난 뒤 `cudaMemcpy`로 읽은 위 절반이 마지막 NIC 쓰기와 같아야 한다.
- 이 계층과 다른 점(시험의 판정이 계층에 대해 말하는 범위): 계층은 드문 느린 길에서 게이트 단어에 `atomicOr`(`tsPoison`)와 CAS 반복(`tsLateFail`)도
  쓰는데 이 시험은 더하기만 한다. 쉬는 스레드는 `.gpu` 범위로 읽는다(계층은 `.sys`). 호스트는 쉬지 않고 돈다(계층은 양보하거나 잠듦) `[소스]`.
- 단계 a: 64 블록 × 256 스레드, 안에서 일 없음(단어에 원자 연산이 가장 많음). 단계 b: 8 블록 × 256 스레드, 안에서 2 000 ns(정지 때 안에 스레드가 있음).
  각 5 s. 시행 하나는 rain과 sunny에서 한 번씩이다. 프로그램 감시 75 s, 실행기 `timeout -s KILL 90`.
- kv와 종료 코드: 프로그램 머리말. 열: 3.1절 `ng_*`. 예측: NG1. 설정 확인(8절): 두 노드 모두 GPU MR이 dmabuf이고 루프백 GID가 link-local이어야
  한다(pilot에서 계층이 쓴 것). 다르면 그 블록을 멈춘다.

### 빌드 ([build_hr.sh](build_hr.sh), 세션 스크래치)

1. `setup`: `agent_ts2hq`의 소스, `build/`, `build-hqp/`를 `agent_ts2hr`로 복사한다(`build-hqp/`는 `build-hrp/`가 됨). 의존 파일과 장치 manifest의
   경로를 바꾸고 원래 시각을 돌려준다. `agent_ts2hq` 작업 트리(= `../peer/hq_layer.diff`, md5 `34ab6201`)를 스크래치 저장소에 "gin-peer hq (libnccl
   c1311625)" 커밋으로 남긴다. 복사 직후 `make -n`은 버전 표시만 다시 컴파일한다 `[측정]`.
2. `hr`: 이 계층을 작업 트리에 두고 증분 빌드. 바뀐 장치 헤더는 NCCL 자신의 장치 객체가 포함하지 않아 장치 객체는 다시 컴파일하지 않는다
   `[측정]`. libnccl → `out/hr`.
3. `hrp`: `build-hrp/`에서 `CXXFLAGS=-DNCCL_GIN_TS_PRODUCTION`으로 증분 빌드. 두 빌드의 설치된 장치 헤더가 같은지 확인한다. libnccl → `out/hrp`.
4. `drivers`: `../gin_ts2.cu`, `gin_mr.cu`, `hm_bench.cu`를 `build/` 헤더로 컴파일(경고를 오류로). `out/drv/gin_ts2`, `out/drv/hm_bench`,
   `out/mr/gin_mr`, `out/build_info.txt`. nvcc 출력은 바이트 단위로 재현되지 않아 다시 돌리면 md5가 바뀐다. 배포한 값은 12절에 있다.
5. `ngt`: `nic_gate_test.cu`(libibverbs, libcuda)를 따로 컴파일. `out/ngt/nic_gate_test`, `out/ngt/build_info.txt`. 배포한 드라이버를 그대로 두려고
   `drivers`와 나눴다.

빌드는 nice 19, 유휴 I/O 우선순위, 8 작업으로 돌렸다(다른 실험이 같은 노드에서 돈다).

### 배포 ([deploy_hr.sh](deploy_hr.sh), 메인 세션)

두 노드의 새 디렉터리 `hr/`(libnccl, `gin_ts2`, `hm_bench`), `hrp/`(libnccl, `gin_ts2`), `mr/hr/`(`gin_mr`)에 둔다(8절 배포). 확인 출력은 파일로만
받는다. 배포 전에 sunny에서 포트 범위가 비어 있는지 읽기만 해서 확인한다. blind-apps가 같은 번들 트리에 새 디렉터리를 배포하는 중이면 "기존 번들 그대로"
확인이 틀리게 나오므로 그때는 피한다.

```
ssh <sunny> "ss -Htan '( sport >= :29000 and sport <= :30999 )' | wc -l"   # 0이어야 함(메인 세션)
cd /home/unionxic/rdma-error-wt/gin-remaining/harness/gpu-initiated/gin_recovery/remaining
bash deploy_hr.sh deploy_check.txt
bash deploy_ngt.sh deploy_ngt_check.txt     # NIC 게이트 시험(새 디렉터리 ngt/), pilot P2 전
```

`deploy_ngt.sh`는 `ngt/nic_gate_test` 하나를 두 노드에 두고 md5, `ldd`(libibverbs, libcuda), 기존 번들 그대로를 확인한다. 포트를 쓰지 않는다.

### 실행 ([hold.sh](hold.sh), [chain.sh](chain.sh), [cells.sh](cells.sh))

hold마다 `chain.sh`가 `cluster_run.sh -w 10800 -t grm-<hold>`에 넣는다. 결과 폴더 아래 랭크 2개 시행은 빌드별 폴더(`hr/`, `hq/`, `hrp/`, `hqp/`)에,
랭크 4개 시행은 `mr_hr/`, `mr_hq/`에, 벤치마크는 `bench/`에, NIC 게이트 시험은 `ngt/`에 쌓인다.

| hold | 내용 | 시간 어림 |
|---|---|---|
| P0 pilot | 랭크 2개 새 셀과 대조 한 번씩(GPU 가득 참 `hr`, `hq`, 스트림 복사 대조, 호출 하나씩 셋 × 두 빌드), `f1_b`, `f4_b`, 4 KiB 지연 두 빌드(13회). 채점 안 함 | 약 2.5분 |
| P1 pilot | 랭크 4개 새 셀과 대조 한 번씩(순환 두 빌드, 시간 제한 없는 받기 두 빌드, gin-peer kill 셀, 사슬), 벤치마크 한 번(7회). 채점 안 함 | 약 3.5분 |
| P2 pilot | NIC 게이트 시험 한 번(P0, P1 뒤에 더함). 채점 안 함 | 약 1분 |
| H1 | 랭크 2개 회귀 6셀 × 5, `hdp_kill_b` 5, 지연 20실행 | 약 6분 |
| H2 | GPU 가득 참 `hr` 10과 `hq` 5(2:1), 스트림 복사 대조 5, 호출 하나씩 `hq` 15와 `hr` 9(섞어서) | 약 7분 |
| H3 | 순환 `hr` 10과 `hq` 5(2:1), 사슬 5 | 약 9분 |
| H4 | 시간 제한 없는 받기 `hr` 10과 `hq` 5(2:1), gin-peer kill 셀 `hr` 5 | 약 8분 |
| H5 | 랭크 4개 회귀 2셀 × 5, 벤치마크 5, NIC 게이트 시험 5 | 약 7분 |

시간 어림 `[측정, 추론]`. hold 하나 = 시행마다 (`wall_s` + 2.7 s) + 31 s다(gin-peer pilot에서 잰 시행 사이 비용과 유휴 링크 대기).
- `wall_s`: 랭크 2개 회귀는 gin-peer 본 실행의 값(`f1_b` 3.8 s, `f3_b` 7.3–7.8 s, `bidirf_sym_b`와 `f2rel_b` 2.3 s, `f4_b`와 `hdp_kill_b` 5.3–5.8 s,
  `hd_rxdeath_b` 3.1 s, 4 KiB 지연 1.8 s, 256 KiB 2.3 s, 각 n=5), GPU 가득 참은 gin-handoff의 4.0–6.1 s(셀마다 n=5) `[측정]`.
- 랭크 4개는 gin-peer pilot의 kill 셀 18.1–20.1 s와 gin-multirank의 장애 없음 18.0 s, 순환 33.6 s(`hq` 대조), 사슬 약 20 s다 `[측정, 추론]`. `hr`의 순환과
  시간 제한 없는 받기는 약 19 s, 그 `hq` 대조는 kill 9 s + application 15 s + 정리로 약 28 s로 어림한다 `[추론]`.
- pilot으로 다시 본 값 `[측정: 12절, 셀마다 n=1]`: 랭크 4개 `hr` 순환 18.6 s, 사슬 18.5 s, 시간 제한 없는 받기와 gin-peer kill 셀 18.1 s, `hq` 순환
  33.1 s, `hq` 시간 제한 없는 받기 25.6 s, GPU 가득 참 5.8–6.1 s, 벤치마크 5.7 s. pilot hold P0(13회)는 99 s, P1(7회)은 155 s 돌았다.
- NIC 게이트 시험 시행 하나는 노드마다 준비와 두 단계(각 5.2 s)로 약 12 s, 둘이면 약 26 s로 어림한다 `[추론]`.
- 가장 긴 H3도 880 s 안이다. 본 실행(H1–H5)의 클러스터 시간은 잠금 대기를 빼고 약 37분이다 `[추론]`.

```
cd /home/unionxic/rdma-error-wt/gin-remaining/harness/gpu-initiated/gin_recovery/remaining
bash chain.sh results/<날짜>_pilot P0 P1          # pilot, 채점 안 함
bash chain.sh results/<날짜>_pilot2 P2            # NIC 게이트 시험 pilot(deploy_ngt.sh 뒤), 채점 안 함
bash chain.sh results/<날짜> H1 H2 H3 H4 H5        # 본 실행(태그 뒤)
bash chain.sh results/<날짜> fill:<폴더>:<셀>@<빌드>:<수>:<시작번호>[,...]   # 제외된 시행 채우기
```

### 채점

```
python3 score.py results/<날짜>
```

`results/<날짜>/SCORE.md`와 `results/<날짜>/trials_scored.csv`가 나온다. 원시 로그는 Release에 올린다.

## 10. 완료 조건과 QA 기준

- [x] 메인 세션이 pilot(P0, P1, P2)을 돌리고 결과를 12절에 적은 뒤, 고칠 것을 고치고 태그를 달았다(P0, P1은 12절에 적음, P2와 태그는 아직). P2는
  14:48:24–14:48:50에 돌았고, 태그는 사전 등록 커밋 `b0489048`에 달렸다(13절).
- [x] 모든 셀이 계획한 반복 수만큼 실행됐다. 제외와 실패를 따로 센 표가 있다([SCORE.md](results/20261009/SCORE.md) 끝 표). 시행 159, 제외 0.
- [x] 예측 34줄마다 판정(맞음, 틀림, 자료 부족)과 놓친 시행 목록이 있다([SCORE.md](results/20261009/SCORE.md)).
- [x] 다른 에이전트가 `score.py`를 보지 않고 원자료에서 핵심 수치를 다시 셌다(handshake timeout과 복구 시각, 기다림 안 응답, degraded 해제와 받기 해제
  시각, 생존 간선, 복사 경로와 스트림 복사 수, 복사 시간 초과, 확인 복사, 지연, 벤치마크)([qa_recount.md](results/20261009/qa_recount.md)).
- [x] 다른 에이전트가 `hr_layer.diff`를 읽고 리뷰했다(12절). 반영 뒤의 계층도 다른 에이전트가 다시 리뷰했다(12절).
- [x] 다른 에이전트가 `nic_gate_test.cu`와 그 실행기, 배포, 채점 부분을 리뷰했다(12절).
- [x] 다른 에이전트가 드라이버, 실행기, 채점 코드를 리뷰했다([qa/code_review.md](qa/code_review.md)).
- [x] smoke와 pilot, 제외 시행이 결과에 섞이지 않았다(pilot은 다른 결과 폴더, 본 실행 폴더의 시행 파일은 모두 사전 등록 뒤에 생김, 제외 0).
- [x] 새 빌드의 md5, 전체 diff, pristine + diff 확인을 5절과 12절에 적었다. 운영 빌드는 strings 대신 로그로 확인했다(`hrp` WARN에 이 실험의 시작
  줄 0, `rs_api=1`, 재계산 3절).
- [x] 원자료를 Release에 올렸다(`data-20261009`, 14절). `DATA.md`는 루트와 상위 README와 함께 한 PR에서 메인 세션이 적는다.
- [x] hold 전후 mlx5 스냅숏에 새 명령 오류가 없었고(다섯 hold 모두 새 mlx5 줄 0), iptables 규칙이 늘지 않았고, CUDA 메모리 오류가 없었다.

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
- [x] sunny 포트 범위 확인과 배포(메인 세션, 12절)
- [x] pilot P0, P1(메인 세션, 채점 안 함), 점검(12절). 실행기와 파서 결함 없음
- [x] 재리뷰 반영: NIC 게이트 시험, `n_served_rec`, 9절 1번 (f)
- [x] NIC 게이트 시험 배포(`deploy_ngt.sh`)와 pilot P2(메인 세션, 12절)
- [x] 고정 절 완성, 상태 `PREREGISTERED`, 해시 기록을 커밋 하나로 만들고 그 커밋에 `prereg/` 태그
- [x] 본 실행 H1–H5 (`RUNNING`, 14:53:27–15:33:14)
- [x] 채점 (`QA`)
- [x] 독립 재계산과 측정 코드 리뷰
- [x] 결과 정리, 원자료 Release(`data-20261009`). PR은 메인 세션이 연다
- [x] 결론 확정 (`COMPLETE`)

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
| 2026-10-09 | (초안까지) 클러스터에서는 아무것도 돌리지 않았다. 배포, pilot, 본 실행은 메인 세션이 한다 | 커밋 `defdde26` |
| 2026-10-09 13:55–13:56 | 배포(메인 세션). 13:55 sunny의 29000–30999 포트에 소켓 2개: 그때 돌던 blind-apps 시행(같은 범위, 시행마다 portpick) `[메인 세션 보고]`. `deploy_hr.sh` 13:55:57–13:56:28, rc 0: "deployed md5 == source on both nodes", "existing bundle unchanged on both nodes (51 files each)" `[측정]` | [deploy_check.txt](deploy_check.txt) |
| 2026-10-09 13:56–14:14 | pilot P0, P1(메인 세션, 채점 안 함). `chain.sh results/20261009_pilot P0 P1` 13:56:49 시작. 잠금은 blind-apps hold 사이에 14:07:44(P0)와 14:10:57(P1)에 얻음. P0 14:08:14–14:09:53(13회), P1 14:11:28–14:14:03(7회), 둘 다 rc 0. iptables `gin-` 규칙 0/0, 두 hold 모두 새 mlx5 줄 0, rain 명령 오류 줄 2와 sunny 0, 펌웨어 명령 실패 계수 31이 앞뒤 같음, 모든 시행 `left=0`, STOP 파일 없음 `[측정]` | `results/20261009_pilot/`(`chain.out`, `hold_P0.out`, `hold_P1.out`, `snap_*`), 세션 스크래치 `cluster_run.log` |
| 2026-10-09 | pilot 점검(이 에이전트, 원자료와 채점기 사본; 채점 아님, 셀 키마다 n=1). 랭크 2개 `[측정]`: `rh_hog_f1_b@hr` 투명(rank 0 시작 쪽 라운드 1 복구), 두 rank 복사 경로 NIC, 스트림 복사 0, 복사 시간 초과 0, 그래도 확인 복사 0/8과 GPU 채우기 블록 시작 0(스트림은 묶임). `@hq`와 `rh_hog_copystream_f1_b@hr`은 4 B 장치에서 호스트 복사가 2 000 ms를 넘겨 거절(그 1 s 전 감시 줄 "fault records are queued and the recovery helper is not running", 거절 이유 "the watchdog surfaced a fault earlier"), 120번 중 41번에서 오류, 스트림 경로 `hr`의 helper 스트림 복사 13. 호출 하나씩: 적재만 뒤면 `hq` 거절, 확인 복사 0/8, `hr` 투명. 할당만 뒤, 스트림 생성만 뒤면 두 빌드 모두 투명, 확인 복사 8/8, GPU 채우기 블록 191(rank 0)과 287(rank 1) 시작. GPU 가득 참 다섯 셀 모두 rank 0 장애가 GIN 실행 597.7–598.8 ms 뒤, GPU 채우기 실행 0.2 ms 뒤로 3 s 창 안. `f1_b@hr` 투명, 통계 API 두 rank 라운드 1 복구 1. `f4_b@hr` kill 1.7 ms 뒤 peer-dead 거절, 칸 0 바로 peer-dead, degraded 줄 없음. 4 KiB 지연 p50 `hrp` 10.46 µs, `hqp` 10.75 µs(3 000번씩) | `results/20261009_pilot/hr/`, `hq/`, `hrp/`, `hqp/` |
| 2026-10-09 | pilot 점검, NIC 복사 경로 `[측정]`: `hr`의 모든 문맥(랭크 2개 6회 × 2, 랭크 4개 4회 × 4, 28개)에서 켜짐 줄, link-local GID 색인 1, GPU MR 모두 dmabuf(랭크 2개 10개, 랭크 4개 18개, nvidia-peermem 0), 자체 시험 580 B(0 아님 93)와 1 092 B(0 아님 269–277), 준비 3.5–6.5 ms. 끔 줄, 이어 하기(`fallbacks`), NIC 복사 시간 초과 0, NIC 경로 시행의 helper 스트림 복사 0 | 같은 폴더의 `*_r*.log` |
| 2026-10-09 | pilot 점검, 랭크 4개와 벤치마크 `[측정]`: `mr4_cyc_stall@hr` 투명, 시작 쪽 복구 0-1, 1-2, 2-0, 거절 0, handshake timeout 0, 마지막 복구가 첫 라운드 줄 696.5 ms 뒤, 퍼짐 3.9 ms. 라운드 1(한 쌍 범위)은 기다림 안에서 받은 REQ를 거부(not_rts, NACK 12)해 전체 재설정으로 다시 돌았고, 라운드 2에서 rank 1이 rank 0의 REQ에 자기 기다림 안에서 답하고(중첩 42.7 ms), rank 2가 rank 1의 REQ에 답하고(56.9 ms), rank 0은 rank 2의 REQ를 41.2 ms 미뤘다가 rank 1과의 라운드 뒤 답함(기다림 안 응답 4, 그중 복구로 끝난 것 2, 미룸 1, 미룬 것 답 1). `@hq`: handshake timeout 3, 첫 것이 라운드 시작 24 504.8 ms 뒤, 거절 6, 복구 0, 33.1 s. `mr4_chain_stall@hr` 투명, 650.9 ms(기다림 안 응답 1은 거부). `rm4_kill3_untimed@hr`: 생존 rank마다 죽음 판정 6.0–8.5 ms 뒤 거절, 그 거절 2 000.0–2 000.1 ms 뒤 degraded(죽음 판정부터 2 006.1–2 008.6 ms), 받기 9개 모두 풀림(죽은 rank 3, 생존 rank 사이 6, 판정부터 2 007.4–2 011.6 ms), 생존 rank 사이 보내기 6/6 성공, 커널 3/3 끝남. `@hq`: 풀림 0, 생존 rank 커널 3/3이 application 포기까지 돎, 25.6 s. `mr4_kill3_peer@hr`: 생존 rank 받기 6/6이 한도(10 s)가 아니라 degraded로 실패(반복 653–659에서 "remote exited"), 보내기 6/6 성공, degraded 2 006.7–2 008.3 ms. `hm_bench`: 기본 호스트 원자 연산 없음(두 GPU), 의존 원자 더하기 장치 178.3 ns 대 호스트 매핑 604.2 ns(rain), 186.2 대 612.3 ns(sunny), 경합에서 호스트 쓰기 26 396번 중 4 009번(rain), 26 000번 중 3 971번(sunny)을 장치의 읽고-고쳐-쓰기가 되돌림, 개수 절반 손실 0 | `results/20261009_pilot/mr_hr/`, `mr_hq/`, `bench/` |
| 2026-10-09 | pilot과 예측(판정 아님: 예측마다 판정식 안의 시행 조건을 pilot 시행에 대 봄). 조건이 맞음: CY1–CY5, DG1–DG6, GR1–GR3, GC1, GC2, GS1, GS3, GS4, RG3, RG7, LT1, HB1–HB3. 안 맞음: GS2(할당만 GIN 실행 뒤에 해도 `hq`의 스트림이 묶이지 않음. 드라이버의 할당은 8 B `cudaMalloc`이고 이미 잡힌 메모리에서 나왔을 수 있다 `[추론]`). 3절 규칙대로 예측은 그대로 두고 의심만 적는다. pilot에 셀이 없음: RG1(`f3_b`, `bidirf_sym_b`), RG2, RG4–RG6, RG8, LT2. HB2는 기준 400 ns에 여유가 적다(+425.9, +426.1 ns). DG4가 말한 대가는 그대로 보였다: rank 0의 rank 1 받기는 끝에 신호 1 000/1 000을 다 받았지만 반복 650–655에서 풀렸다. `mr4_kill3_peer@hr`의 받기 0/3은 DG6의 예측 그대로다. `gin_mr`의 받기 간선은 상대를 모르는 `waitSignal`이고, 상대별 대기(보내기의 `flushAsync(peer)` 뒤 `wait`)는 6/6 끝났다. gin-peer K1(생존 rank 간선 6개 모두 정상)은 `hr`에서 설계대로 성립하지 않는다(9절 1번 (c)) `[측정, 추론]` | 세션 스크래치 `hr_work/pilot/trials_scored.csv`(채점기 사본, 계획 수 1과 시행 조건만 본 판정식) |
| 2026-10-09 | 재리뷰(다른 에이전트, 읽기만, 리뷰 반영 뒤의 계층 = `hr_layer.diff` `66f61272`이 빌드한 트리와 같음). 판정 "조건부로 그대로 실행 가능", 막는 결함과 높음 없음. 중간 3(M-A 한 번 훑을 때 중첩 둘, M-B NIC 4 B 쓰기와 SM 원자 연산 미확인, M-C 앞 헤더의 장치 코드), 낮음 4(L-A CY3이 거부도 셈, L-B degraded 시계는 거절에서, L-C 자체 시험의 스트림 복사, L-D 잘못된 죽음 판정의 범위). 첫 리뷰 반영은 H1, H2, M2, L1–L6, 사소가 맞고 M1, L8이 부분. 처리: 계층은 고치지 않음(배포한 번들 그대로, 리뷰도 그대로 실행 가능이라 함), M-B는 NIC 게이트 시험을 더함, L-A는 설명용 열 `n_served_rec`, L-B는 DG 열과 대 봄(이 셀은 판정 직후 거절, 3.3 주의), 나머지는 9절 1번 (f)에 남는 점으로 적음 | 리뷰 보고는 메인 세션이 전함(파일 없음) |
| 2026-10-09 | NIC 게이트 시험 리뷰(다른 에이전트, 읽기만). 판정 "먼저 고칠 것": (1) `deploy_ngt.sh`의 기대 md5가 다시 빌드한 것과 달라 배포가 멈춤, (2) 멈춤 깃발의 NIC 쓰기를 다시 읽지 않아, 그 쓰기를 잃으면 감시 종료로 제외되어 NG1이 "틀림"이 아니라 "자료 부족"이 됨, (3) 정지 기다림 안의 쓰기 손실이 정지 시간 초과로도 세짐, (4) dmabuf가 아니거나 link-local GID가 아닌 실행도 채점됨, (5) 계층과 다른 점(게이트 줄의 다른 원자 연산, 드문 `atomicOr`와 CAS, 읽기 범위). 맞다고 본 것: QP 준비, GID 고르기, dmabuf 등록, CUDA 문맥, 모든 기다림의 한도, 쓰기 경로가 `gdakiLbXfer`와 같음, 장치 원자 연산이 `tsWordEnter`, `tsWordLeave`와 같음, Dekker와 안 확인이 NIC 읽기에도 맞음, 실행기와 채점 열, NG1 식, H5 시간. 반영: (1) 마지막 빌드로 기대 md5를 고침, (2) 모든 NIC 쓰기(에폭, 멈춤)를 다시 읽고 잃으면 세고 다시 씀, (3) 정지 기다림 안에서 다시 쓰고 이어 기다림(시간 초과는 2 s에만), (4) `score.py`의 설정 확인 `config_ngt`, (5) 게이트를 88 B 자리에 두고 같은 줄의 색인 단어 둘을 들어간 스레드가 고침(`ng_idx_ok`), 나머지는 9절 5번에 적음 | 리뷰 보고는 이 세션의 에이전트 응답(파일 없음) |
| 2026-10-09 | pilot 뒤, 태그 전 바꾼 것. pilot에서 실행기나 파서 결함은 찾지 못했다. 더한 것: NIC 게이트 시험([nic_gate_test.cu](nic_gate_test.cu), [run_ngt_hr.sh](run_ngt_hr.sh), [deploy_ngt.sh](deploy_ngt.sh), `build_hr.sh ngt`), 셀 `nic_gate`, hold P2와 H5의 `nic_gate` 5회, hold의 남은 프로세스 확인에 `nic_gate_test`, `rows_hr.py`의 `ngt_row()`와 `served_rec`, `score.py`의 `ngt/` 폴더와 제외 이유, 예측 NG1(34줄, 앞 33줄은 그대로). `nic_gate_test` 빌드 `abb2af4cb61a8075242f348c599b407a`(소스 `4d87f2b8`), 경고 0 `[측정]`. 채점기 사본을 pilot 사본에 만든 NIC 게이트 시행 하나(측정 아님)와 함께 돌려 NG1이 평가되고 열이 나옴을 확인 | 이 커밋, 세션 스크래치 `agent_ts2hr/out/ngt/build_info.txt` |
| 2026-10-09 14:44 | NIC 게이트 시험 배포(`deploy_ngt.sh`, rc 0): 두 노드의 md5가 소스와 같음, 기존 번들 57개 파일 그대로 | [deploy_ngt_check.txt](deploy_ngt_check.txt) |
| 2026-10-09 14:48:24–14:48:50 | pilot P2(메인 세션, 채점 안 함): `chain.sh results/20261009_pilot2 P2`, rc 0. NIC 게이트 시험이 두 노드에서 PASS(결과 줄 12개), `mr=dmabuf`, `gid_kind=link-local`, 라운드 a 8677, 8749와 b 8797, 8806, 물러남 1802만–1억4334만. 새 mlx5 줄 0, iptables 0/0 | `results/20261009_pilot2/`(원자료는 Release) |
| 2026-10-09 14:49:16 | 사전 등록 | [PREREG.txt](PREREG.txt), 태그 `prereg/gin-remaining-v1` |
| 2026-10-09 14:49–15:33 | 본 실행(메인 세션): `chain.sh results/20261009 H1 H2 H3 H4 H5`, 14:49:23 시작. blind-apps hold 사이에 잠금을 얻음. 잠금과 실행(유휴 링크 확인 뒤부터 끝까지): H1 14:52:56, 14:53:27–14:58:28; H2 15:02:21, 15:02:52–15:09:04; H3 15:10:11, 15:10:42–15:18:55; H4 15:18:55, 15:19:26–15:26:55; H5 15:26:55, 15:27:26–15:33:14. 다섯 hold 모두 rc 0, STOP 파일 없음, iptables `gin-` 규칙 0/0, 새 mlx5 줄 0, rain 명령 오류 줄 2와 sunny 0, 펌웨어 명령 실패 31이 앞뒤 같음, 모든 시행 `left=0`, 종료 코드 139 없음. 시행 159(랭크 2개 79, 지연 실행 20, 랭크 4개 50, 벤치마크 5, NIC 게이트 시험 5), 채움 hold 없음 `[측정]` | `results/20261009/`(`chain.out`, `hold_H*.out`, 원자료는 Release), 세션 스크래치 `cluster_run.log` |
| 2026-10-09 15:33:59 | 채점(`score.py`): 시행 159, 판정 159, 제외 0. 예측 34개 중 33개 맞음, GS2(`cudaMalloc`만 GIN 실행 뒤) 틀림 0/5 `[측정]` | [SCORE.md](results/20261009/SCORE.md), [trials_scored.csv](results/20261009/trials_scored.csv) |
| 2026-10-09 | 독립 재계산(다른 에이전트, `score.py`, `rows_hr.py`, `SCORE.md`, `trials_*.csv`, 앞 실험의 열 추출기를 읽지 않음): 맞음 33, 틀림 1, 자료 부족 0, 제외 0, 설정 확인 0건, 무결성 모두 통과(태그, 예측 해시, 고정 절, 드라이버 소스, hold 출력 159줄과 시행 파일, SIGKILL 줄 35개와 `kill.out` 35개). EXPERIMENT.md와 다른 것 일곱(13절) | [qa/recount.py](qa/recount.py), [qa_recount.md](results/20261009/qa_recount.md) |
| 2026-10-09 | 본 실행 뒤 코드 리뷰(다른 에이전트, 읽기만): 막는 결함과 높음 없음, 판정은 그대로. 중간 2(M1 적재가 뒤인 셀은 SM이 차 있지 않았음, M2 `cudaMalloc` 셀은 8 B 할당), 낮음 11. 처리는 13, 15, 17, 18절 | [qa/code_review.md](qa/code_review.md) |
| 2026-10-09 | 내 확인(이 에이전트, 독립 확인 아님): `trials_scored.csv`와 원시 로그, kv에서 핵심 수치를 따로 셌고 재계산과 같았다. 순환 `hr`의 기다림 안 응답 38(복구로 끝난 중첩 19, 39.6–58.7 ms; 1라운드 거부 19, 0.7–0.9 ms), 미룬 REQ 17과 그 답 17(1.0–310.7 ms), 버린 것 0; 시간 제한 없는 받기 `hr`의 생존 rank 사이 받기 60개가 반복 649–660에서 풀림, 그중 40개는 끝에 신호 1 000/1 000; NIC 경로 켬 줄 258(link-local 색인 1, MR 모두 dmabuf), 끔 줄 0, 정리 줄 `nic` 233(스트림 복사 0, NIC 시간 초과 0)과 `stream` 10(스트림 복사 13씩); 스트림 경로 대조 세 셀의 rank 0 거절 이유 15/15 "the watchdog surfaced a fault earlier"; NIC 게이트 시험 10노드 실행 모두 PASS, 라운드 8 669–8 820, 잃은 쓰기 0; 벤치마크 차이와 되돌린 쓰기 비율, 지연 p50, 회귀 셀의 시각 `[측정]` | 이 커밋 |
| 2026-10-09 16:03:35 | Release `data-20261009`에 원자료 세 묶음(본 실행, pilot P0과 P1, pilot P2). 메인 세션이 내려받아 확인: `sha256sum -c` 통과, 관리망 주소를 바꾼 것 말고는 원본과 같음, 실제 주소 접두 없음 | 14절 |
| 2026-10-09 | 마감: 13–19절, README, 상태 `COMPLETE` | 이 커밋 |

## 13. 사전 등록 이후 변경

> 기존 문장을 고치지 않고 여기에 덧붙인다. 태그 뒤 이 실험의 셀, 실행기, 채점기, 예측, 라이브러리, 드라이버, 번들은 바뀌지 않았다(독립 재계산 2절,
> 리뷰 Focus 4: 실행기와 배포 스크립트는 저장소의 주소 필터가 바꾸는 한 줄만 다름).

| 날짜 | 무엇을 | 이유 | 영향 범위 | 커밋 |
|---|---|---|---|---|
| 2026-10-09 | 정정(10절 첫 상자, 11절 P2 상자): "P2와 태그는 아직"은 사전 등록 커밋 자체에 남은 문장이다. P2는 14:48:24–14:48:50에 돌았고(12절), 태그는 그 커밋 `b0489048`에 달렸다. 상자에 이 사실을 덧붙였다 | 독립 재계산 6절 2번 | 문구뿐 | 마감 커밋 |
| 2026-10-09 | 정정(5절 NIC 게이트 시험 줄 "배포 전"): 그 칸은 배포 전에 썼다. 14:44에 배포했다([deploy_ngt_check.txt](deploy_ngt_check.txt), 12절). 칸 끝에 덧붙였다 | 독립 재계산 6절 3번 | 문구뿐 | 마감 커밋 |
| 2026-10-09 | 정정(12절 pilot 점검, 랭크 4개): "받기 9개 모두 풀림(..., 판정부터 2 007.4–2 011.6 ms)"에서 2 007.4–2 011.6 ms는 rank 3에서 오는 받기 3개의 범위다. 받기 9개 전체는 2 007.4–2 013.3 ms다(rank 0의 rank 2 받기가 2 013.3 ms) `[측정: pilot 1회, 받기 9개]` | 독립 재계산 6절 4번 | 예측과 무관 | 마감 커밋 |
| 2026-10-09 | 정정(12절 "pilot과 예측" 줄): "rank 0의 rank 1 받기는 ... 반복 650–655에서 풀렸다"에서 그 받기는 반복 655에서 풀렸다. 650–655는 생존 rank 사이 받기 6개의 범위다 `[측정: pilot 1회]` | 독립 재계산 6절 4번 | 예측과 무관 | 마감 커밋 |
| 2026-10-09 | 정정(12절 pilot P2): "결과 줄 12개"는 틀렸다. hold 줄의 NIC 게이트 시험 결과에 `result=PASS`가 6개(노드마다 `a_result`, `b_result`, `result`) 있고 두 kv 파일에도 같은 6개가 있다. 둘을 더해야 12다 | 독립 재계산 6절 5번 | 문구뿐 | 마감 커밋 |
| 2026-10-09 | 정정(9절 4번 "약 20 µs마다"): 20 µs는 경합 단계 호스트 반복의 잠이다. 다시 읽기 64번을 더한 실제 쓰기 간격은 약 76 µs다(실행마다 2 000 ms에 쓰기 26 001–26 434번) `[측정, 소스]` | 독립 재계산 6절 6번 | 판정 규칙과 무관 | 마감 커밋 |
| 2026-10-09 | 덧붙임(3절 GC1, GC2, GS1 문구, 고정): 예측은 대조가 "복사 시간 초과로 거절"한다고 썼다. 15회 모두 두 rank에 복사 시간 초과 줄이 있지만, rank 0의 거절 이유는 "the watchdog surfaced a fault earlier"다. 감시 줄 "fault records are queued and the recovery helper is not running"이 복사 시간 초과 902.6–1 001.1 ms 전에 왔다(15회) `[측정]`. helper가 라운드 앞의 4 B 복사에 묶여 있는 동안 감시가 먼저 드러낸다. 판정식(복사 시간 초과 1 이상, 복구 없음, 투명 아님)은 맞는다 | 독립 재계산 6절 7번 | 판정 영향 없음 | 마감 커밋 |
| 2026-10-09 | 덧붙임(8절 "감시 줄", 고정): 펌웨어 초과 제외의 "감시 줄"을 펌웨어 단계 감시 줄로만 읽었다. 위 15회의 감시 줄(복사에 묶인 helper)은 펌웨어 초과가 아니라 제외하지 않았다. 채점기와 재계산이 같게 읽었다. 모든 감시 줄을 세면 그 세 셀 키는 판정 시행이 없다 | 독립 재계산 3절 | 판정 영향 없음 | 마감 커밋 |
| 2026-10-09 | 해석의 범위(2절 H3, 3절 GR1–GR3, GC1, GC2, GS1, 7절 셀 설명 "GPU 가득 참", 고정): 적재가 GIN 실행 뒤인 셀 28회(`rh_hog_f1_b` 15, `rh_hog_copystream_f1_b` 5, `rh_hogcall_load_f1_b` 8)에서는 장애와 라운드 동안 GPU 채우기 블록이 하나도 돌지 않았다. 첫 블록은 GIN 커널이 끝나는 때 앞뒤 −2.9–+0.2 ms에 시작했다 `[측정: 리뷰]`. 적재가 GIN 커널을 기다리는 동안 그 뒤의 모든 스트림 명령(채우기 커널 실행, 확인 복사)이 함께 묶였다. 그러므로 GR1이 보인 것은 "application의 커널 적재가 모든 CUDA 스트림을 묶은 동안 NIC로 투명하게 복구"이지 "GPU가 가득 찬 동안"이 아니다. SM이 실제로 가득 찬 것은 할당만, 스트림 생성만 뒤인 셀(블록 191/192, 287/288)이고, 거기서는 `hq`가 스트림으로 10/10, `hr`이 NIC로 6/6 복구했다. 두 조건이 함께 있는 셀은 없다 | 리뷰 M1 | 15, 17절과 README의 문장을 이 범위로 썼다 | 마감 커밋 |
| 2026-10-09 | 해석의 범위(2절 H4, 3절 GS2, 고정): `cudaMalloc`만 뒤인 셀의 할당은 8 B(gin-harden 드라이버의 것)다. GS2의 틀림은 그 크기에서만 할당 규칙을 반박한다. 새 메모리를 매핑하는 할당과 `cudaFree`는 재지 않았다. "적재"는 아직 적재되지 않은 커널의 첫 사용(점유율 질의)이고, 지연 적재 탓이라는 것은 추론이다 | 리뷰 M2, L1 | 17, 18절. H4는 "적재는 스트림을 묶고, 스트림 생성과 8 B `cudaMalloc`은 묶지 않았다"로 읽는다 | 마감 커밋 |
| 2026-10-09 | 덧붙임(3절 판정 경계, 고정): 여유가 적은 판정. HB2 7.9 ns(rain 407.9 ns 대 400 ns), DG2 5.4 ms(2 005.4 ms 대 2 000 ms), DG1 6.7 ms(2 006.7 ms 대 2 000 ms), LT1 0.15 µs(차이 −0.25 µs 대 0.40 µs). LT2의 차이 0.00 µs는 32 ns 타이머 한 칸 안에서 같다는 뜻이다. DG1, DG2의 아래 경계는 죽음 판정 줄부터 재지만 degraded 시계는 거절에서 시작한다(3.3 주의). 거절부터 재면 degraded 줄은 2 000.0–2 000.1 ms 뒤다(생존 rank 45회) `[측정]` | 독립 재계산 4절, 리뷰 L3, L7 | 판정은 그대로. 여유만 적는다 | 마감 커밋 |
| 2026-10-09 | 덧붙임(3절 CY3, DG6, 고정): CY3은 거부도 응답으로 세지만(재리뷰 L-A), 중첩 라운드가 복구로 끝난 것만 세도 10/10이다(`n_served_rec` 1–2). DG6의 "한도가 아니라 degraded로" 부분은 판정식에 없다. 생존 받기 30개 모두 반복 651–659에서 "remote process exited or there was a network error"로 끝났고, 보내는 쪽이 15 ms마다 보내고 있어 10 s 한도가 지날 수 없었다 `[측정]` | 리뷰 L2, L4 | 판정 영향 없음 | 마감 커밋 |
| 2026-10-09 | 해석의 범위(2절 H2): degraded로 풀린 받기의 끝 점검은 보내는 쪽과 맞춰지지 않는다. rank 1은 다른 두 생존 rank보다 약 205 ms 먼저 끝나 점검하므로 신호 989–990/1 000, 12–13칸이 비어 보인다(15회). 보낸 쪽은 1 000/1 000을 오류 없이 마쳤다. 이것을 데이터 손실로도, 데이터가 온전하다는 근거로도 쓰지 않는다 | 리뷰 L5 | 15, 18절 | 마감 커밋 |
| 2026-10-09 | 덧붙임(8절 실행, 고정): 설정 확인 실패는 `config_*`로 표시만 하고 블록을 멈추지 않으며, 채움이 50%를 넘을 때의 자료 부족은 코드에 없다. 벤치마크와 NIC 게이트 시험 실행기는 남은 프로세스 수(`left=`)를 쓰지 않는다. 본 실행에서는 해당 없음: 설정 확인 실패 0, 제외 0, 채움 0, 두 실행기의 종료 코드 10/10 모두 0 `[측정]` | 리뷰 L9, L10 | 영향 없음 | 마감 커밋 |
| 2026-10-09 | 해석의 범위(9절 2번, 대조 드라이버): `hq` 대조는 `hr` 헤더로 빌드한 장치 코드를 쓴다. 대조 예측은 상대별 대기의 결과를 읽지 않으므로 판정에는 영향이 없다. 순수한 `hq` application의 상대별 보내기와 flush가 거절 뒤 어떻게 끝나는지는 이 대조로 말할 수 없다 | 리뷰 L11 | 영향 없음 | 마감 커밋 |

## 14. 원자료와 결과표

| 무엇 | 경로 또는 Release 자산 | n |
|---|---|--:|
| 채점표(예측별 판정, 놓친 시행, 셀별 제외) | [results/20261009/SCORE.md](results/20261009/SCORE.md) | 예측 34 |
| 시행별 값(채점 상태 포함) | [results/20261009/trials_scored.csv](results/20261009/trials_scored.csv) | 159(판정 159) |
| 독립 재계산 | [results/20261009/qa_recount.md](results/20261009/qa_recount.md), 스크립트 [qa/recount.py](qa/recount.py) | 159 |
| 본 실행 뒤 코드 리뷰 | [qa/code_review.md](qa/code_review.md) | |
| 본 실행 원자료(빌드별 시행 로그와 kv, 원시 지연, hold 출력, 스냅숏) | Release `data-20261009`, `harness__gpu-initiated__gin_recovery__remaining__results__20261009.tar.xz`(파일 1 109개, 0.42 MB, sha256 앞 12자리 `c7ccdebad261`) | 159 |
| pilot P0, P1 원자료(채점 안 함) | Release `data-20261009`, `harness__gpu-initiated__gin_recovery__remaining__results__20261009_pilot.tar.xz`(파일 152개, 0.06 MB, `200e2da615fa`) | 20 |
| pilot P2 원자료(채점 안 함) | Release `data-20261009`, `harness__gpu-initiated__gin_recovery__remaining__results__20261009_pilot2.tar.xz`(파일 17개, 0.01 MB, `4a3e34390a88`) | 1 |
| 배포 확인 | [deploy_check.txt](deploy_check.txt), [deploy_ngt_check.txt](deploy_ngt_check.txt) | |
| 사전 등록 | [predictions.csv](predictions.csv), [PREREG.txt](PREREG.txt), 태그 `prereg/gin-remaining-v1`(`b0489048`) | 34 |

빌드별 중간 표(`trials_hr.csv` 등)는 `trials_scored.csv`에 모두 들어 있어 커밋하지 않았다. Release 자산은 메인 세션이 16:03:35에 내려받아
확인했다(12절).

## 15. 결과 요약

판정: **예측 34개 중 33개 맞음, 1개 틀림(GS2)**(시행 159, 판정 159, 제외 0). 채점 [SCORE.md](results/20261009/SCORE.md), 독립 재계산도 33/1/0
([qa_recount.md](results/20261009/qa_recount.md)) `[측정]`. 아래 범위는 따로 적지 않으면 그 셀 키의 판정 시행 전체에 걸친 범위다. 수치는 채점표나
독립 재계산에서 왔고, 12절에 적은 것은 내가 원자료에서 따로 세어 같음을 확인했다.

**1. 시작 쪽 셋의 순환** `[측정]`(랭크 4개, 세 rank의 helper가 정지 뒤 300 ms 멈춤)

| 조건 | 셀 키 | n | 결과 | 예측 |
|---|---|--:|---|---|
| 순환 0>1, 1>2, 2>0, 이 실험 | `mr4_cyc_stall@hr` | 10 | 투명 10/10, handshake timeout 0, 거절 0, 시작 쪽 복구 0-1, 1-2, 2-0. 마지막 재개가 첫 라운드 줄 694.6–1 002.8 ms 뒤(중앙값 707.6) | CY1, CY2 맞음 |
| 같음, gin-peer 라이브러리 | `mr4_cyc_stall@hq` | 5 | 시행마다 handshake timeout 3, 거절 6, 복구 0. 첫 handshake timeout이 라운드 시작 24 504.7–24 507.3 ms 뒤 | CY4 맞음 |
| 사슬 0>1, 1>2(순환 없음) | `mr4_chain_stall@hr` | 5 | 투명 5/5, 마지막 재개 652.0–668.1 ms 뒤(gin-multirank의 `hd` 2 080.8–2 089.4 ms, 1절) | CY5 맞음 |

- 순환이 끊긴 과정(`hr`, 10회): 시행마다 먼저 한 쌍 범위의 라운드 셋이 응답 쪽 범위 확인에서 거부되어(not_rts, 30회) 전체 재설정으로 다시 돌았다. ACK를
  기다리는 rank가 낮은 rank의 REQ에 답한 것이 38번이고("1-0", "2-1"), 그중 19번은 중첩 라운드가 응답 쪽 복구로 끝났고(39.6–58.7 ms), 19번은 1라운드의
  거부였다(0.7–0.9 ms). rank 0은 높은 rank 2의 REQ를 17번 미뤘고 17번 모두 자기 라운드 뒤에 답했다(1.0–310.7 ms), 버린 것은 0이다(CY3 맞음).
  1 002.8 ms 시행은 rank 0이 rank 2의 REQ를 310.7 ms 미룬 시행이다.
- 모든 `hr` 순환과 사슬 rank(60)의 복사 경로는 NIC, 스트림 복사 0, NIC 시간 초과 0이었다.

**2. 상대를 모르는 대기: 랭크 4개, rank 3 SIGKILL**(kill 9 000 ms, 생존 rank 0, 1, 2) `[측정]`

| 조건 | 셀 키 | n | 결과 | 예측 |
|---|---|--:|---|---|
| 모든 받기에 시간 제한 없음, 이 실험 | `rm4_kill3_untimed@hr` | 10 | 죽음 판정 5.4–8.5 ms 뒤 rank 3 거절, 그 2 000.0–2 000.1 ms 뒤 degraded 해제(판정부터 2 005.4–2 008.5 ms, 생존 rank 30회). rank 3에서 오는 받기 30개가 판정 2 006.7–2 013.0 ms 뒤 오류로 풀림. 생존 rank 사이 보내기 6/6 성공(10/10), 생존 rank 커널 3/3 끝남(kill 뒤 7 129.8–7 404.9 ms) | DG1–DG3 맞음 |
| 같음, 대가 | 같음 | 10 | 생존 rank 사이 받기 60개도 반복 649–660에서 오류로 풀림. 그중 40개는 끝에 신호 1 000/1 000을 다 받은 받기다 | DG4 맞음 |
| 같음, gin-peer 라이브러리 | `rm4_kill3_untimed@hq` | 5 | 아무것도 풀리지 않음, degraded 줄 없음, 생존 rank 커널 15/15가 application이 포기할 때까지(kill 뒤 15 007.4–15 010.0 ms) 돎 | DG5 맞음 |
| gin-peer의 kill 셀(받기 한도 10 s) | `mr4_kill3_peer@hr` | 5 | 생존 보내기 6/6 성공, 생존 받기 30개 모두 한도가 아니라 degraded로 실패(반복 651–659), degraded 줄 판정 2 005.9–2 008.4 ms 뒤 | DG6 맞음 |

- 장애 없는 상대의 상대별 대기(`flushAsync(peer)` 뒤 `wait`)는 degraded 뒤에도 끝까지 갔다. 상대별 단어는 rank 3의 것("0-3;1-3;2-3")만 올라갔다.
- 끝 점검의 신호 989–990/1 000(rank 1)은 점검 시점 탓이다(13절, 리뷰 L5).

**3. application의 CUDA 호출과 복구 복사** `[측정]`(랭크 2개, rank 0 로컬 QP 오류, 256 KiB × 120, GPU 채우기 커널 3 s; "확인 복사"는 새 스트림 4 B
복사 8개의 200 ms 안 완료 수)

| GIN 실행 뒤의 호출 | 빌드(복사 경로) | n | 확인 복사 | GPU 채우기 블록 | 복구 | 예측 |
|---|---|--:|---|---|---|---|
| 적재, 할당, 스트림 생성(gin-handoff 순서) | `hr`(NIC) | 10 | 0/8 | 0 | 투명 10/10, 복사 시간 초과 0, helper 스트림 복사 0 | GR1–GR3 맞음 |
| 같음 | `hq`(스트림) | 5 | 0/8 | 0 | 복사 시간 초과, 거절 5/5 | GC1 맞음 |
| 같음 | `hr`(스트림, `NCCL_GIN_TS_COPY_PATH=stream`) | 5 | 0/8 | 0 | 복사 시간 초과, 거절 5/5 | GC2 맞음 |
| 적재만 | `hq` / `hr` | 5 / 3 | 0/8 | 0 | 거절 5/5 / 투명 3/3 | GS1, GS4 맞음 |
| 할당만(8 B `cudaMalloc`) | `hq` / `hr` | 5 / 3 | 8/8 | 191(rain), 287(sunny) | 투명 5/5 / 투명 3/3 | **GS2 틀림**, GS4 맞음 |
| 스트림 생성만 | `hq` / `hr` | 5 / 3 | 8/8 | 191, 287 | 투명 5/5 / 투명 3/3 | GS3, GS4 맞음 |

- 스트림 경로의 거절 15회 모두 rank 0의 거절 이유는 "the watchdog surfaced a fault earlier"이고, 감시 줄이 복사 시간 초과 902.6–1 001.1 ms 전에 왔다(13절).
- 적재가 뒤인 셀에서는 라운드 동안 GPU 채우기 블록이 돌지 않았다(13절, 리뷰 M1). 막힌 것은 스트림이지 SM이 아니다.
- NIC 복사 경로: `hr` 문맥 258개 모두 켜짐(랭크 2개 98, MR 10개; 랭크 4개 160, MR 18개), GPU MR 모두 dmabuf, link-local GID 색인 1, 자체 시험 통과,
  준비 3.0–10.9 ms. 끔 줄 0, 스트림으로 이어 하기 0, NIC 시간 초과 0. 정리 줄 233개(kill된 rank 25개는 없음)에서 helper 스트림 복사 0, 스트림 경로 셀의
  10개는 13씩.

**4. 게이트를 호스트 메모리에 둘 때와 NIC의 4 B 쓰기** `[측정]`

| 측정 | 셀 키 | n | rain(Quadro RTX 5000) | sunny(RTX A4000) | 예측 |
|---|---|--:|---|---|---|
| 호스트 원자 연산 기본 지원 | `hm_bench@hr` | 5 | 0 | 0 | HB1 맞음 |
| 의존 원자 더하기, 장치 메모리 | 같음 | 5 | 178.2–178.4 ns | 186.2–186.3 ns | |
| 같음, 호스트 매핑 메모리(차이) | 같음 | 5 | 586.1–602.3 ns(+407.9–423.9) | 601.8–609.3 ns(+415.6–423.1) | HB2 맞음 |
| 경합: 장치의 읽고-고쳐-쓰기가 되돌린 호스트 쓰기 | 같음 | 5 | 4 132–4 498 / 26 343–26 434(15.7–17.0 %) | 4 154–4 739 / 26 001–26 002(16.0–18.2 %) | 예측 없음 |
| 경합: 개수 절반의 장치 갱신 손실 | 같음 | 5 | 0 | 0 | HB3 맞음 |
| NIC 게이트 시험(NIC 4 B 에폭 쓰기 대 SM 64비트 원자 연산) | `nic_gate@hr` | 5 | PASS 5/5, 단계마다 라운드 8 739–8 820, 홀수 에폭 쓰기 87 793번에 잃은 쓰기 0 | PASS 5/5, 8 669–8 798, 87 351번에 0 | NG1 맞음 |

- NIC 게이트 시험의 다른 확인도 모두 0이었다: 개수 손실, Dekker 위반, 홀수 에폭 동안 안에 있는 스레드, 정지 시간 초과, 같은 줄의 색인 단어 손실. 물러난
  스레드 수는 라운드 × 스레드 수와 같아 모든 스레드가 NIC가 쓴 홀수 에폭을 봤다. 가장 긴 정지 0.007–0.133 ms.

**회귀** `[측정]`(n=5씩)
- 투명 5/5: `f1_b`, `f3_b`, `bidirf_sym_b`, `mr4_none`, `mr4_f1_01`(RG1, RG8). 그 라운드의 복사는 모두 NIC(RG2). 통계 API: `f1_b`에서 두 rank가 라운드 1,
  복구 1, 거절 0(RG7).
- kill: `f4_b` kill 뒤 거절 1.58–1.70 ms, 원인 peer-dead, 칸 0 바로 peer-dead, degraded 줄 없음(RG3). 운영 빌드 `hdp_kill_b@hrp` 1.51–1.63 ms, 죽음 1,
  WARN에 시작 줄과 정보성 줄 없음(RG6).
- 받기만 하는 rank(`hd_rxdeath_b`): kill 뒤 비동기 오류 1.8–2.1 ms, 커널 끝 20.2–21.5 ms(RG4).
- 원격 접근 오류(`f2rel_b`): rank 0 거절, rank 1 device_error, rank 1 abort 697.2–758.8 ms(RG5).

**지연**(rank 0 p50, 실행마다 3 000번, 실행 5의 중앙값) `[측정]`

| 크기 | 이 실험 운영 빌드 | gin-peer 운영 빌드 | 차이 | 예측 |
|---|---|---|--:|---|
| 4 KiB | 10.46–10.98 µs(중앙값 10.50) | 10.75 µs(5/5) | −0.25 µs | LT1 맞음(0.40 이하) |
| 256 KiB | 38.88 µs(5/5) | 38.88 µs(5/5) | 0.00 µs | LT2 맞음(0.30 이하) |

p50은 원시 지연 3 000개에서 다시 계산해도 kv와 같다(재계산, 20/20). 비교는 각 운영 빌드의 드라이버 장치 코드까지 포함한다(9절 2번).

## 16. QA와 재현성

- **채점.** 메인 세션이 `score.py`로 셈: 시행 159, 판정 159, 예측 34개 중 33개 맞음, GS2 틀림 `[측정]`.
- **독립 재계산.** 다른 에이전트가 `score.py`, `rows_hr.py`, `SCORE.md`, `trials_*.csv`, 앞 실험의 열 추출기를 읽지 않고 원시 로그와 kv에서 모든 열을
  다시 뽑고, 자기 판정식 평가기로 셌다([qa/recount.py](qa/recount.py), [qa_recount.md](results/20261009/qa_recount.md)).
  - 맞은 것: 판정 33/1/0, 제외 0, 설정 확인 0건, hold 출력 159줄과 시행 파일, SIGKILL 줄 35개와 `kill.out` 35개, 멈춤 기준(STOP 없음, 139 없음, 명령
    오류와 펌웨어 실패 수 그대로, iptables 규칙 0), 지연 p50(원시 3 000개에서 다시 계산). 새 규칙과 대조 규칙의 조건을 같은 이름의 다른 빌드 셀에 대면
    16쌍 중 14쌍이 0건이고 나머지 둘은 예상한 것이다(스트림이 묶인 조건은 `hq`에서도 참, 스트림 생성만 조건은 `hr`에서도 참).
  - 무결성: 태그 `prereg/gin-remaining-v1`이 커밋 `b0489048`, `predictions.csv` sha256이 작업 트리, 태그, `PREREG.txt` 세 곳에서 같음, 고정 절과
    `cells.sh`, `chain.sh`, `portpick.sh`, 드라이버 소스, diff가 태그와 같음(실행기와 배포 스크립트는 관리망 주소 필터가 넣는 한 줄만 다름). 본
    실행의 첫 로그 14:53:30은 사전 등록 14:49:16 뒤.
  - 다른 것: 13절에 옮긴 일곱. 판정을 바꾸는 것은 없다.
  - 한계: `rows_hr.py` 계열을 읽지 않아 열은 문서와 드라이버에서 다시 정의했다. 규칙이 쓰는 값은 모두 경계에서 멀고, 예외는 13절의 여유가 적은 넷이며
    그 값은 kv, 로그 시각, 원시 지연에서 바로 나온다.
- **코드 리뷰.** 설계 단계 리뷰 둘(12절)과 NIC 게이트 시험 리뷰(12절), 본 실행 뒤 리뷰([qa/code_review.md](qa/code_review.md)). 본 실행 뒤 리뷰는
  드라이버 소스 md5와 빌드 기록, rain의 배포 번들 md5가 5, 12절과 같음을 확인했다(sunny는 배포 때 확인만). 빈 열로 맞는 판정이 없고, 태그 뒤 채점에
  닿는 변경이 없다. 찾은 것과 처리는 13, 17, 18, 19절.
- **내 확인.** 채점기 출력과 원시 로그, kv에서 핵심 수치를 따로 세어 재계산과 같음을 확인했다(12절). 이것은 독립 확인이 아니다.
- **재현.** [gin_transparent_hr.diff](gin_transparent_hr.diff)(pristine NCCL v2.32.3-1 기준)로 만든다. `hrp`는 같은 소스에
  `-DNCCL_GIN_TS_PRODUCTION`. 빌드 절차는 [build_hr.sh](build_hr.sh)(`ngt` 단계는 NIC 게이트 시험), 배포는 [deploy_hr.sh](deploy_hr.sh)와
  [deploy_ngt.sh](deploy_ngt.sh)(md5 확인), 실행은 9절. 빌드 md5는 5, 12절. 드라이버 바이너리는 nvcc 출력이 바이트 단위로 재현되지 않아 다시 빌드하면
  md5가 바뀐다.

## 17. 결론

1. **시작 쪽 셋 이상의 순환 대기가 풀렸다.** ACK를 기다리는 rank가 낮은 rank의 REQ에는 그 자리에서 답하고(중첩 응답 라운드) 높은 rank의 REQ는 자기
   라운드 뒤로 미루자, 순환 셀에서 handshake timeout과 거절 없이 세 쌍이 모두 복구됐고 마지막 재개가 첫 라운드 줄 0.69–1.00 s 뒤였다(10/10). gin-peer
   라이브러리는 같은 셀에서 24.5 s 한도까지 기다려 거절했다(5/5) `[측정]`. 대기 관계가 높은 rank에서 낮은 rank로만 이어진다는 논증(9절 1번 (b))은
   설계 단계 리뷰 둘이 확인했다 `[소스]`. 순환 없는 사슬도 투명했고 앞 빌드보다 빨랐다(0.65–0.67 s, `hd`에서 2.08–2.09 s). 거부 답도 기다림 안에서
   바로 오기 때문이다 `[추론]`.
   - 중첩은 바깥 라운드가 8 s 넘게 남았을 때만 한다. 그 뒤에 온 낮은 rank의 REQ는 앞 빌드처럼 바깥 라운드 뒤에 답하므로, 순환이 아주 늦게 생기면 앞의
     시간 초과가 돌아올 수 있다. 한 번에 낮은 rank의 REQ 둘을 받는 경우의 시간 계산(재리뷰 M-A)은 이 셀에 없었다.
2. **상대를 모르는 대기가 2 s 뒤 풀린다. 대가는 그 communicator의 상대를 모르는 대기 전부다.** 랭크 3개 이상에서 한 상대가 죽음으로 판정되면 그
   거절 2 000 ms 뒤 devComm 단어(칸 0)를 올리고(degraded), 상대별 대기는 칸 0 대신 자기 상대의 단어를 읽게 했다. 시간 제한 없는 `waitSignal`이 판정
   2.0 s 뒤 오류로 풀렸고(30/30), 생존 rank 사이 상대별 보내기와 flush는 끝까지 갔다(60/60). gin-peer 라이브러리에서는 아무것도 풀리지 않아
   application이 15 s 뒤 포기할 때까지 커널이 돌았다 `[측정]`.
   - 대가: 건강한 rank의 신호를 기다리던 `waitSignal`도 함께 풀렸다(60/60). 그중 40개는 결국 신호를 다 받을 대기였다. gin-peer의 kill 셀에서는 생존
     rank 사이 간선 6개가 정상이었으나(gin-peer K1) 이 계층에서는 그 받기 6개가 실패한다(5/5). application은 degraded 뒤 상대별 통신을 마치고
     shrink하거나 abort해야 한다. `NCCL_GIN_TS_DEGRADED_MS=-1`이면 gin-peer 동작이다.
   - 랭크 2개는 앞 빌드와 같다(유일한 상대라 칸 0이 바로 올라감, 5/5) `[측정]`.
   - 상대별 대기가 칸 0을 읽지 않는 것은 이 계층의 헤더로 빌드한 장치 코드에서만이다(재리뷰 M-C). 앞 헤더로 빌드한 application에서는 건강한 상대의
     대기도 오류로 끝나고 helper는 이를 알 수 없다 `[소스]`.
3. **application의 CUDA 호출이 스트림을 묶어도 복구가 된다.** 라운드의 장치 상태 복사를 CUDA 스트림 대신 helper의 NIC 루프백 RDMA(dmabuf로 등록한 GPU
   메모리)로 하자, gin-handoff 순서(GIN 실행 뒤 적재, 할당, 스트림 생성)에서 새 스트림 복사가 하나도 끝나지 않는 동안에도 복구가 투명했다(10/10).
   같은 순서에서 스트림 복사는 gin-peer 라이브러리와 이 라이브러리 모두 시간을 넘겨 거절됐다(5/5, 5/5) `[측정]`.
   - 막은 것은 스트림이지 SM이 아니다(리뷰 M1). 적재가 GIN 실행 뒤인 셀에서는 채우기 커널도 묶여 라운드 동안 SM이 비어 있었다. SM이 가득 찬 셀(할당만,
     스트림 생성만 뒤)에서는 두 라이브러리 모두 복구했다(`hq` 스트림 10/10, `hr` NIC 6/6). 그러므로 gin-handoff가 본 실패의 원인은 SM 부족이 아니라
     스트림 묶임이다 `[측정, 추론]`.
   - 세 호출 중 스트림을 묶은 것은 GIN 실행 뒤 처음 쓰는(아직 적재되지 않은) 커널이다(`hq` 거절 5/5). 스트림 생성과 8 B `cudaMalloc`은 묶지 않았다
     (5/5, 5/5). 예측은 `cudaMalloc`도 묶는다고 했으나 틀렸다(GS2). 더 큰 할당과 `cudaFree`는 재지 않았고(리뷰 M2), 적재와 점유율 질의는 가르지
     않았다(리뷰 L1).
   - NIC 경로는 문맥 258개에서 모두 켜졌고 꺼지거나 시간을 넘긴 일이 없었다 `[측정]`.
4. **게이트를 호스트 메모리로 옮기는 대안은 비싸고 안전하지 않다. NIC의 4 B 쓰기는 이 시험에서 안전했다.** 호스트 매핑 메모리의 의존 원자 더하기는
   장치 메모리보다 약 0.41–0.42 µs 느렸고(두 GPU, 10실행), 장치가 같은 단어에 원자 연산을 하는 동안 호스트가 쓴 위 절반의 15.7–18.2 %를 장치의
   읽고-고쳐-쓰기가 되돌렸다. 정지 규약(호스트가 에폭을 쓰고 개수를 읽음)은 그런 메모리에서 지켜지지 않는다 `[측정, 추론]`. GPU 메모리의 게이트에 NIC가
   4 B 에폭을 쓰는 이 계층의 방식은, SM 64비트 원자 연산과 겨룬 홀수 에폭 쓰기 약 87 000번(GPU마다)에서 하나도 잃지 않았고 Dekker 확인도 모두
   지켰다 `[측정]`. 증명이 아니라 한계다: 쓰기 하나를 잃을 확률은 95 %에서 약 3.4 × 10⁻⁵보다 작다(리뷰 L8).
5. **기존 동작과 지연은 그대로다.** 회귀 예측 9개가 모두 맞았고(시행 50), 운영 빌드의 지연은 gin-peer 운영 빌드와 4 KiB에서 −0.25 µs, 256 KiB에서
   0.00 µs 달랐다 `[측정]`. 기존 복구 셀의 라운드 복사도 모두 NIC로 갔다.

## 18. 한계

- **degraded의 범위.** 첫 죽음 판정 2 s 뒤 그 communicator의 상대를 모르는 대기가 모두 풀린다. 건강한 rank를 기다리던 대기, 늦게 부른 대기도 오류다.
  잘못된 죽음 판정도 같다(재리뷰 L-D). 죽음이 아닌 거절(펌웨어 초과, 상대가 알린 실패)은 degraded를 만들지 않는다. degraded 시계는 거절에서 시작하므로
  라운드 도중의 죽음은 그 라운드가 끝날 때까지 늦다(재리뷰 L-B, 이 실험의 셀에는 없음).
- **앞 헤더의 장치 코드(재리뷰 M-C).** 상대별 대기가 상대의 단어를 읽는 것은 이 계층의 헤더로 빌드한 코드에서만이다. 이 실험의 드라이버는 모두 그
  헤더로 빌드했다. `hq` 대조도 그렇다(리뷰 L11).
- **"GPU 가득 참"(리뷰 M1).** GR1–GR3, GC1, GC2, GS1은 SM이 아니라 스트림이 묶인 조건이다. 스트림이 묶이고 SM도 가득 찬 조건은 이 드라이버로 만들 수
  없어 재지 않았다.
- **`cudaMalloc`(리뷰 M2, L1).** 8 B 할당 하나만 쟀다. 새 메모리를 매핑하는 할당, `cudaFree`, 적재와 점유율 질의의 구분은 재지 않았다.
- **degraded 뒤 받기 점검(리뷰 L5).** 풀린 받기의 끝 점검은 보내는 쪽과 맞춰지지 않아 rank 1에서 칸이 비어 보인다. 데이터 손실의 근거로도, 온전함의
  근거로도 쓰지 않는다.
- **NIC 게이트 시험(리뷰 L8).** 잃은 쓰기 0은 쓰기 약 87 000번(GPU마다)의 한계다. 계층의 드문 길(`atomicOr`, CAS)과 `.sys` 범위의 쉬는 읽기는 시험에
  없다(9절 5번). flush READ의 순서는 relaxed ordering이 꺼져 있다는 가정에 기댄다 `[미확인: 이 하드웨어]`.
- **NIC 경로의 실패 길.** 오류 완료 뒤 스트림으로 이어 하기, link-local GID가 없을 때 GIN GID로 넘어가기는 한 번도 일어나지 않았다. 주소를 지웠다
  붙이는 셀(gin-s2)은 이 실험에 없다. 게이트를 처음 쓸 때 NIC 요청이 시간을 넘기면 그 rank의 투명 복구가 꺼진다(재리뷰 L8 부분). 자체 시험은 문맥을
  만들 때 스트림 복사를 쓰므로, application이 이미 GPU를 붙잡은 채 devComm을 만들면 NIC 경로가 꺼질 수 있다(재리뷰 L-C).
- **순환.** 순환은 helper 멈춤 시험 스위치(300 ms)로 만들었고 자연 타이밍의 빈도는 재지 않았다. 중첩 한 번에 낮은 rank 둘(재리뷰 M-A)과 바깥 라운드
  16.5 s 뒤의 순환은 재지 않았다.
- **벤치마크(리뷰 L6, L7).** 경합의 장치 쪽은 사실상 경쟁자 둘(warp 둘)이라 HB3는 약한 시험이다. HB2는 400 ns 기준에 7.9 ns 여유로 맞았다.
- **판정 경계.** DG1, DG2, LT1도 여유가 적다(13절).
- **채점과 실행기(리뷰 L9, L10).** 설정 확인 실패와 50% 채움 규칙은 자동으로 블록을 멈추지 않고, 벤치마크와 NIC 게이트 실행기는 남은 프로세스를 세지
  않는다(본 실행에서 해당 없음). 운영 빌드의 복사 경로는 WARN 로그에 보이지 않는다.
- **장비와 장애.** 노드 한 쌍, 랭크 4개는 GPU 둘을 프로세스 둘씩 나눠 썼다. 장애는 소프트웨어로 주입했다. 연구용 패치이고 연구 빌드에는 시험 스위치가
  있다.

## 19. 다음 작업

- **상대를 모르는 대기를 상대별로.** degraded는 모두를 한꺼번에 푼다. 대기에 기다리는 상대를 알리는 장치 API(상대를 받는 `waitSignal`)나, application이
  신호 칸마다 보내는 rank를 등록하는 방식으로 건강한 상대의 대기를 지킨다. 운영 빌드에서는 degraded를 켤 때만 쓰게 하는 것도 검토한다(재리뷰 M-C, L-D).
- **앞 헤더 감지(재리뷰 M-C).** 새 장치 코드가 게이트에 깃발을 세우게 해, 깃발이 없는 문맥에서는 degraded 뒤 게시 전 확인이 칸 0도 세게 한다.
- **중첩 시간 계산(재리뷰 M-A).** 중첩 라운드 뒤 돌아가거나 상대마다 남은 시간을 다시 본다. 낮은 rank 둘이 한 번에 REQ를 보내는 셀을 만든다.
- **CUDA 호출.** 새 메모리를 매핑하는 큰 `cudaMalloc`, `cudaFree`, 적재와 점유율 질의를 가른 셀. 스트림이 묶이고 SM도 가득 찬 조건(미리 적재한 다른 채우기
  커널과 뒤의 적재).
- **NIC 경로의 실패 길.** 주소를 지웠다 붙이는 셀(gin-s2)로 link-local 루프백과 스트림 이어 하기를 실제로 일으킨다. 게이트를 처음 쓸 때의 NIC 시간
  초과도 스트림으로 이어 한다(재리뷰 L8). 자체 시험을 NIC만으로 한다(재리뷰 L-C).
- **NIC 게이트 시험 넓히기.** `atomicOr`와 CAS 길, `.sys` 쉬는 읽기, 더 긴 실행.
- **채점기와 실행기(리뷰 L9, L10).** 설정 확인 실패에서 블록 멈춤, 50% 채움 규칙, 벤치마크와 NIC 게이트 실행기의 남은 프로세스 세기.
- **관련 작업(이 실험의 결과가 아님).** 같은 날 blind 실험(다른 에이전트)의 원인 분석은 GIN `ring_exchange` 예제가 QP 장애에서 16회 중 14회 멈추는 것을
  보았다. signal 대기가 CQ를 폴링하지 않아, 장애 감지가 application의 flush 호출에 달려 있고 호스트 쪽 감지가 없다는 것이다 `[다른 실험의 보고, 미확인]`.
  이 계층의 Q4 분류 기록과 helper가 그 경우를 볼 수 있는지 확인할 일이다.

## 20. 참고자료

- `../multirank/EXPERIMENT.md` 1절(순환 대기), 15, 19절
- `../peer/EXPERIMENT.md` 9절 1번 (b), (h), 18, 19절, `../peer/qa/code_review.md` M1
- `../handoff/EXPERIMENT.md` 9절 2번(GPU 가득 참의 원인과 고치지 않은 이유), 15, 17절, 13절의 리뷰 L6
- `../TRANSPARENT_S2.md`, `../gate_ce_test.cu`(복사 엔진의 게이트 쓰기 시험)
- `../s2_close/EXPERIMENT.md` 3.2절(판정식 문법)
- CUDA C++ Programming Guide: implicit synchronization, lazy loading, mapped memory의 원자 연산 `[문서]`
- [qa/code_review.md](qa/code_review.md), [results/20261009/qa_recount.md](results/20261009/qa_recount.md)(이 실험의 QA)
