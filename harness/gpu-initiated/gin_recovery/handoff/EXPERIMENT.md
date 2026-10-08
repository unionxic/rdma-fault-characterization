# GIN 투명 복구: shrink 넘기기와 GPU가 가득 찬 동안의 복사 (gin-handoff)

**목적:** gin-harden pilot에서 틀린 두 동작을 다룬다. 복구가 거절한 장애 뒤 죽은 rank를 빼는 중단 shrink가 되게 라이브러리를 고치고, GPU가 가득 찬
동안 helper의 장치 상태 복사가 멈추는 원인을 잰다.

| 항목 | 값 |
|---|---|
| 상태 | `COMPLETE` |
| 담당자 | @unionxic |
| 작성일 | 2026-10-09 |
| 기준 브랜치와 커밋 | `exp/gin-handoff` @ `692ff591`(태그 `prereg/gin-harden-v1`의 커밋. gin-harden의 실행기, 채점 함수, `hd` 소스를 그대로 쓰려고 그 위에서 시작) |
| 사전 등록 태그 | `prereg/gin-handoff-v1` (상태를 `PREREGISTERED`로 바꾼 바로 그 커밋) |
| 마지막 갱신 | 2026-10-09, 본 실행, 채점, 독립 재계산, 코드 리뷰, Release 뒤 마감(12–19절) |

표시: `[측정]` 원자료에서 확인, `[소스]` 코드에서 읽음, `[추론]` 해석, `[미확인]` 확인 안 함.

이 문서의 코드는 함수 이름으로 가리킨다. 파일은 따로 적지 않으면 `src/transport/net_ib/gdaki/gin_host_gdaki.cc`다. 용어(helper, 사용자 devComm,
abort 단어, 거절, 죽음, 라운드, 첫 분류 기록)는 [../harden/EXPERIMENT.md](../harden/EXPERIMENT.md) 머리말과 같다. 이 실험에서 더 쓰는 말:
- 중단 shrink: `ncclCommShrink(..., NCCL_SHRINK_ABORT)`. 부모의 진행 중인 작업을 끝내고 남은 rank로 새 통신기를 만든다.
- GIN 오류: `ncclCommGetAsyncError`가 GIN 쪽에서 얻는 `ncclRemoteError`(GDAKI 문맥의 오류 표시, GIN 비동기 결과).
- 오류 올림: 라이브러리가 GIN 오류를 세우는 곳 하나하나(거절, 감시의 드러냄, 투명 복구가 없을 때의 분류, QUERY_QP 확인).
- GPU 채우기 커널: 드라이버가 SM 수 × SM당 최대 블록 수만큼의 블록(256 스레드)을 띄워 3 s 동안 도는 커널(`GIN_TS_HOG_MS`).
- 하드웨어 작업 큐: 호스트가 GPU에 일을 넘기는 큐. CUDA는 스트림을 이 큐(`CUDA_DEVICE_MAX_CONNECTIONS`개, 기본 8)에 나누어 싣는다 `[미확인: CUDA 문서의 설명, 이 테스트베드에서 확인 안 함]`.

예측 id와 셀 이름은 원자료를 찾는 키로만 괄호나 표의 열에 둔다.

빌드 키는 넷이다. 모두 번들 디렉터리 `$HOME/gi-bundle/gin_ts2/<키>/`다.

| 키 | 내용 | 쓰는 곳 |
|---|---|---|
| `hf` | 이 실험의 연구 빌드: gin-harden `hd` 소스 위에 9절 1번의 계층. 이 실험의 드라이버 | 새 셀, 회귀 셀 |
| `hfp` | 같은 소스를 `-DNCCL_GIN_TS_PRODUCTION`으로 컴파일한 운영 빌드. 같은 드라이버 | shrink 운영 셀, 운영 kill, 지연 |
| `hd` | gin-harden 연구 빌드(배포된 번들 그대로: libnccl `e2090323`, 드라이버 `c0b73e09`) | shrink 대조, 지연 기준 |
| `hdp` | gin-harden 운영 빌드(배포된 번들 그대로: libnccl `4818e30b`, 드라이버 `c0b73e09`) | 지연 기준 |

## 1. 배경과 연구 질문

gin-harden은 GIN GDAKI 투명 복구를 다지는 계층(`hd`)을 만들고, 사전 등록 전에 pilot을 돌렸다(2026-10-09 03:24:59–03:31:02, 셀마다 1회, 채점
안 함). 두 예측이 pilot과 어긋났고, gin-harden은 예측을 고치지 않고 의심만 적었다(`../harden/EXPERIMENT.md` 3절 머리, 9절 1번 (g)의 pilot 두 줄).
아래 수치는 모두 그 pilot 원자료(`../harden/results/20261009_pilot/`)에서 다시 셌다 `[측정, n=1씩]`.

**1. shrink 넘기기.** 상대 kill 뒤 rank 0은 FIN에서 죽음을 판정하고 1.3 ms 뒤 거절했다(`hd_shrink_b_n1_r0.log`의 닫힘 줄과 거절 줄). 그 뒤 응용이
부른 중단 shrink는 0.0 ms에 `ncclRemoteError`를 돌려주었다(`hd`, `ow2` 각 1회, kv `ho_shrink_rc`, `ho_shrink_ms`). 원인 `[소스]`:
`ncclCommShrink`는 abort 플래그를 올렸다 내린 뒤 `ncclCommInitChildComm`을 부르고, 그 함수는 순정 코드 그대로 `ncclCommEnsureReady`로 부모의
`ncclCommGetAsyncError`를 확인한다(`init.cc`, 이 함수는 순정과 같음: 순정 트리와 비교). 그 값은 GDAKI 문맥의 오류 표시(`q4->hasError`,
`ncclGinGdakiQueryLastError`)에서 오는 `ncclRemoteError`다. 그래서 순정 NCCL 2.32.3은 GIN 오류가 난 통신기를 그대로는 shrink할 수 없다. 오류를
낸 rank를 빼려는 shrink도 마찬가지다. 응용이 먼저 devComm을 없애면(`ncclDevCommDestroy`는 그 확인을 부르지 않고, `ncclGinDevCommFree`가 devComm을
목록에서 빼므로 그 GDAKI 문맥의 오류도 함께 사라진다) 순정 확인을 지날 것으로 읽힌다 `[소스, 독립 리뷰. 미확인]`. 그 길은 살아 있는 상대에 대한
오류까지 모두 지우고 응용을 바꿔야 한다. 이 실험은 그 길도 대조로 잰다(7절).

**2. GPU가 가득 찬 동안의 복구.** GPU 채우기 커널이 도는 동안 두 rank 모두 복구가 거절로 끝났다(`hd_hog_f1_b_n1`). 원자료에서 다시 센 순서(rank 0
시계, ms는 GIN 커널 시작 기준):
- GPU 채우기 커널을 0.2 ms에 띄웠다(kv `hog_launch_after_launch_ms`). 블록 192개(48 SM × 4).
- helper가 4 B 장치→호스트 복사를 62.7 ms에 냈다(시간 초과 줄의 시각 − 2 000 ms). 장애 전이므로 쉬는 중의 게이트 점검(`gdakiTsScan`)이다 `[추론]`.
- 장애 훅이 599.7 ms에 발사했다. 감시가 1 061.6 ms에 "helper가 1 s 넘게 돌지 않음"으로 오류를 드러냈다.
- 복사 상한(2 000 ms)이 2 062.7 ms에 지나 두 rank가 거절했다. 거절이 사용자 abort 단어를 올린 지 0.04 ms 뒤 "늦은 복사가 끝남" 줄이 나왔고,
  GIN 커널은 그 근처(비동기 오류 뒤 1 002.2 ms, 1 ms 간격 확인)에 끝났다.
- GPU 채우기 커널은 그때도 돌고 있었다(0.2 ms에 시작했다면 3 000 ms까지 돈다. kv `hog_running_at_end=1`, 2 365 ms에 확인).

rank 1도 4 B 복사가 64.1 ms에 나가 2 s 안에 끝나지 않았다. rank 1은 GIN 커널 뒤 커널 하나(마지막 신호 읽기)를 더 띄우는데, 그 뒤의
`ncclCommAbort`가 GIN 커널 끝 3 300.2 ms 뒤에 시작했다 `[측정]`. 3 000 ms(GPU 채우기 블록의 길이)와 300 ms(끝 대기)의 합이다. GPU 채우기 블록이
0.2 ms에 시작했다면 3 000.2 ms에 끝났을 것이고(GIN 커널 끝 907.8 ms 뒤), 그때 신호 읽기 커널이 자리를 얻어 abort는 GIN 커널 끝 약 1 208 ms 뒤에
시작했어야 한다. 실제로는 3 300.2 ms 뒤였고 abort 직전에 GPU 채우기 커널은 이미 끝나 있었다(kv `hog_running_at_end=0`). 그러므로 GPU 채우기
커널의 블록은 (거의) 모두 GIN 커널이 끝난 무렵에야 시작했다 `[측정, 추론. 독립 리뷰가 이 셈을 바로잡음, 12절]`. GIN 커널 뒤에 커널을 띄우지 않는
rank 0은 GIN 커널 끝 301.0 ms 뒤 abort를 시작했다 `[측정]`. 이 값으로는 rank 0의 GPU 채우기 커널이 언제 시작했는지 알 수 없다.

원인 후보를 소스에서 좁혔다 `[소스]`(자세한 근거는 9절 2번).
- 레거시 기본 스트림과 동기화하는 blocking 스트림: 아니다. helper의 복구 스트림은 `cudaStreamNonBlocking`이다(`gdakiRecRegister`). 드라이버의 GIN
  커널 스트림 둘과 GPU 채우기 커널 스트림도 그렇다(`../gin_ts2.cu`).
- 동기 `cudaMemcpy`: 아니다. 시간 초과 줄은 `gdakiRecCopyWait`만 내고, 그 복사는 `cudaMemcpyAsync` 뒤 event를 확인한다(`gdakiRecD2H`).
- 커널로 하는 장치 간 복사: 아니다. 멈춘 복사는 장치→호스트 4 B이고 대상은 `cudaHostAlloc`으로 잡은 고정 메모리다. helper는 memset 커널도 쓰지
  않는다(`gdakiTsZeroDev`는 복사).
- 복사 엔진 스케줄링: 남는다. 복사 엔진은 SM을 쓰지 않고, 같은 복사가 보통의 복구에서는 끝난다. 그러므로 자원이 아니라 순서가 막는다고 본다.
  순서를 만드는 것으로 읽히는 후보는 둘이다 `[추론, 미확인]`.
  - 두 커널 사이의 호출: gin-harden 드라이버는 GIN 커널을 띄운 뒤, GPU 채우기 커널을 띄우기 전에 그 커널의 점유율을 묻고(지연 적재에서 이때 커널
    코드가 올라감) `cudaMalloc`과 스트림 생성을 한다. CUDA 프로그래밍 가이드는 장치 메모리와 고정 호스트 메모리 할당을 서로 다른 스트림의 명령이
    함께 돌지 못하게 하는 호출로 적는다 `[문서, 이 테스트베드에서 미확인]`. 이것이 그 뒤의 모든 GPU 명령(GPU 채우기 커널, helper의 복사)을 돌던 GIN
    커널이 끝날 때까지 묶는다는 읽기다. rank 1의 위 셈(커널 전체가 늦게 시작)과 맞는다.
  - 다 올라갈 수 없는 격자와 하드웨어 작업 큐: SM 수 × SM당 최대 블록 수의 격자는 상주한 1-블록 GIN 커널 옆에 다 올라갈 수 없어 블록 하나가 남고,
    같은 큐에서 그 뒤에 들어간 명령이 묶인다는 읽기다. 이 읽기는 블록 대부분이 바로 시작한다고 보므로 rank 1의 셈과 맞지 않는다.
- 이전 실험의 관측: gin-s2에서 돌고 있는 GIN 받는 커널 옆에 나중에 띄운 GIN 보내는 커널은 받는 커널이 끝날 때까지 시작하지 않았고, 지연 적재, 지역
  메모리 예약, 하드웨어 큐 수(`CUDA_DEVICE_MAX_CONNECTIONS=32`)로는 설명되지 않았다(`../TRANSPARENT_S2.md`, 원인 못 찾음) `[측정, 이전 실험]`. 같은
  일이 GIN 받는 커널 옆의 보통 커널에도 일어난다면 rank 1에서는 두 커널 사이에 아무것도 없어도 GPU 채우기 커널이 시작하지 않는다.

**질문.**
1. 중단 shrink가, 부모의 GIN 오류가 모두 빼는 rank를 상대로 낸 것일 때 그 오류를 넘어가 1-rank 통신기를 돌려주는가. 그 통신기의 allreduce가
   맞고, 새 통신기에 부모의 오류가 따라오지 않는가. 상대를 적지 않은 오류가 있거나 스위치를 끄면 순정 판정(실패)을 지키는가. 응용이 devComm을
   먼저 없애는 길은 순정 확인으로도 통하는가.
2. GPU가 가득 찬 동안 helper 복사가 멈추는 것은 GIN 커널과 GPU 채우기 커널 사이의 할당과 커널 적재 때문인가, 다 올라갈 수 없는 격자 때문인가.
   두 커널 사이에 아무것도 없게 하거나 격자를 블록 하나 줄이면(GPU는 그대로 가득 참) 복구가 투명해지는가. 그때 새 스트림의 복사는 끝나는가.
3. 이 계층이 투명 복구, 거절, 통계 API와 빠른 경로의 지연을 바꾸지 않는가.

## 2. 가설

| id | 가설 | 다음이 관측되면 틀린 것이다 |
|---|---|---|
| H1 | 라이브러리가 GIN 오류를 올릴 때마다 그 상대를 적어 두면, 중단 shrink는 응용을 바꾸지 않고도 그 상대가 모두 빠졌을 때만 오류를 넘어간다. 아이 통신기는 부모와 자원을 나누지 않으므로(중단 shrink) 오류를 물려받지 않고, 1-rank allreduce가 맞다 | `hf`의 shrink 셀에서 shrink, 그 통신기의 allreduce, 오류 없음이 9/10 미만이다. 또는 대조(`hd`, 스위치 끔)에서 shrink가 성공한 시행이 2회 이상이다. 또는 상대를 적지 않은 오류가 있는 셀에서 shrink가 넘어간 시행이 2회 이상이다 |
| H2 | GIN 커널을 띄운 뒤 같은 프로세스가 한 할당과 커널 적재가 그 뒤의 모든 GPU 명령(GPU 채우기 커널, helper와 새 스트림의 복사)을 돌던 GIN 커널이 끝날 때까지 묶는다. GPU가 가득 찬 것, 격자의 크기, 하드웨어 큐는 복사를 막지 않는다 | gin-harden 순서의 두 셀에서 GPU 채우기 커널이 GIN 커널 옆에서 시작하거나 새 스트림 복사가 200 ms 안에 끝난 시행이 2회 이상이다. 또는 두 커널 사이에 아무것도 없는 두 셀에서 투명 복구나 복사 완료가 4/5 미만이다 |
| H3 | 이 계층은 오류의 기록과 중단 shrink의 판정만 바꾸므로 기존 셀의 판정과 빠른 경로의 지연이 그대로다 | 회귀 셀에서 예측과 다른 시행이 나온다. 또는 지연 차이가 예측 범위 밖이다 |

## 3. 사전 예측 (측정 전에 작성)

**고정 시점.** 예측은 메인 세션이 pilot(9절의 hold H0)을 돌린 뒤 태그 `prereg/gin-handoff-v1`을 단 커밋에서만 고정된다. 그 전까지 이 절과
[predictions.csv](predictions.csv)는 고칠 수 있다. pilot에서 셀 조건이 의도대로 만들어지지 않거나 판정식의 경계가 pilot과 맞지 않으면 고친다(예: S3의
5 s 상한). GPU 가득 참 셀의 pilot이 가설과 어긋나도 그 예측은 고치지 않고 의심만 적는다(gin-harden과 같은 규칙). pilot 시행은 채점하지 않는다. 그 결과 폴더(`results/<날짜>_pilot/`)는 채점 대상 폴더와 따로 두고, 무엇을 보고 무엇을
고쳤는지 12절과 13절에 적는다. 태그 뒤에는 2, 3, 7, 8절과 `predictions.csv`를 고치지 않는다.

**pilot 뒤 확정 (2026-10-09).** 예측과 셀, 반복 수, 제외 기준은 pilot H0(05:04:28–05:05:52 KST, 14회, 채점 안 함, 12절) 뒤에 확정했다. pilot의 시행
14개는 모두 설정 확인을 통과했고 제외에 걸린 것이 없다. 판정식의 조건(`count(...)` 안의 식)은 셀이 pilot에 있던 예측 19개 모두에서 그 시행 하나가
만족했다(n=1씩, 계획 수에 못 미쳐 판정은 아님) `[측정]`. 어긋난 예측은 없다. pilot을 보고 바꾼 것은 하나뿐이다.
- S3의 shrink 시간 상한: 5 000 ms(설계 때의 짐작)를 500 ms로. pilot에서 shrink는 `hf` 17.3 ms, `hfp` 17.2 ms, devComm을 먼저 없앤 셀 16.5 ms였다(n=1씩)
  `[측정]`. 500 ms는 그 약 29배다.
그 밖에 판정식, 셀, 반복 수, 제외 기준은 그대로다. 열 설명 하나를 바로잡았다(3.1의 `hog_*_start_rel_ms`: 노드마다 일정한 시계 차가 있어 판정식에 쓰지
않음). 확정한 `predictions.csv`는 24줄이고 sha256은 12절에 적었다.

GPU 가득 참 2 × 2의 pilot(셀마다 n=1, 채점 안 함)은 H2와 맞았다 `[측정, 추론]`. 자세한 값은 12절.
- 두 커널 사이에 gin-harden의 호출이 있으면 격자 크기와 상관없이(가득, 하나 작게) 두 rank 모두 GPU 채우기 블록이 확인 때 0개 시작했고, 새 스트림 복사
  8개가 모두 200 ms 안에 끝나지 않았으며, 끝에서 블록들의 시작 간격은 0.0 ms(모두 함께 시작)였고, 복구는 복사 시간 초과로 거절됐다.
- 호출을 GIN 커널 전으로 옮기면 두 크기 모두 복사 8개가 0.08 ms 안에 끝나고 투명하게 복구됐다. 가득 채운 격자는 블록 하나(rank 0 192개 중 191개
  시작, rank 1 288개 중 287개 시작)가 GIN 커널이 끝날 때까지 남았지만(시작 간격 1 816.9 ms, 1 801.9 ms, 각 rank의 GIN 커널 시간 1 817.5 ms,
  1 802.6 ms와 거의 같음) 복사도 복구도 막지 않았다. 그래서 큐 읽기의 막힘은 나타나지 않았다. 돌고 있는 GIN 받는 커널 옆에서도 보통 커널은 시작했다
  (gin-s2의 관측은 이 경우 재현되지 않음).

예측 원문은 [predictions.csv](predictions.csv)이고 24줄이다. `kind`는 N(새 동작), R(회귀), C(대조)다.

### 3.1 판정에 쓰는 열

시행마다 한 줄이다. 열은 여섯 곳에서 온다. 앞의 다섯 곳의 열은 원래 정의 그대로다 `[소스]`.
- `../scripts/ts2/rows.py`: `transparent_ok`, `r1_outcome`, `rx_rc`, `rec_init_r*`, `decl_r*`, `teardown_r*`, `teardown_ms_r*`, `lat_p50_us`,
  `ts_on_r*`, `n_fires_r*`, `killed`, `bind_fail`, `trigger_miss`, `fault_mono_r0`.
- `../s2_close/rows_extra.py`: `ua_r*`.
- `../pair_check/rows_pc.py`, `../oneway/rows_ow.py`: `ow_mode_r*`, `knob_uto_r*`, `knob_refuse_r*`, `n_mute_on_r*`, `r0_killed`.
- `../harden/rows_hd.py`(정의는 `../harden/EXPERIMENT.md` 3.1절): `hd_on_r*`, `prod_r*`, `hk_*_r*`, `n_judged_r*`, `n_copyto_r*`, `n_fwdog_r*`,
  `rs_*_r*`, `rx_phantom_r*`, `ho_*`(gin-harden 정의 8개), `hog_blocks_r*`, `hog_sms_r*`, `hog_launch_err_r*`, `hog_launch_after_launch_ms_r*`,
  `fault_after_launch_r0_ms`, `release_after_kill_ms_r1`, `async_after_kill_ms_r1`, `decl_after_kill_ms_r0`, `left_rules`.
- 이 폴더의 [rows_hf.py](rows_hf.py)가 붙이는 새 열. 정의는 그 파일 머리말이 원문이다. 요약:

| 열 | 정의 |
|---|---|
| `hf_on_r*`, `hf_switch_r*` | `GIN/TS: handoff=1 rank=<r> shrink_handoff=<0\|1>` 줄이 있으면 1, 그 값 |
| `n_hoff_ok_r0`, `hoff_ranks_r0` | `GIN/TS: rank 0: aborting shrink proceeds past the parent's GIN error, raised for rank(s) <목록>, all excluded` 줄 수와 첫 줄의 목록 |
| `n_hoff_keep_r0`, `hoff_why_r0` | `GIN/TS: rank 0: aborting shrink keeps the parent's error (<사유>)` 줄 수와 첫 줄의 사유 |
| `n_surface_r*`, `surface_why_r*` | `GIN/TS: watchdog rank=<r>: <사유>; the fault surfaces` 줄 수(상대를 적지 않은 오류 올림)와 첫 사유 |
| `n_late_copy_r*` | "the late device-state copy completed" 줄 수 |
| `ho_parent_async_after`, `ho_newcomm_async`, `ho_newcomm_destroy_rc`, `ho_check_ms`, `ho_allreduce_done`, `ho_allreduce_rc` | rank 0 kv: shrink 직후 부모의 비동기 오류, 새 통신기의 비동기 오류, 새 통신기 해제 결과, allreduce 확인 |
| `ho_devcomm_destroy_rc`, `ho_devcomm_destroy_ms` | rank 0 kv: shrink 전 `ncclDevCommDestroy`의 결과와 시간(devComm을 먼저 없애는 셀) |
| `hog_slack_r*`, `hog_prealloc_r*`, `hog_local_bytes_r*` | kv: GPU 채우기 격자에서 뺀 블록 수, 두 커널 사이의 호출을 GIN 커널 전에 했는지, 그 커널의 지역 메모리(앞당긴 셀만) |
| `hog_started_probe_r*`, `hog_started_end_r*`, `hog_start_spread_ms_r*`, `hog_first_start_rel_ms_r*`, `hog_last_start_rel_ms_r*` | kv: 확인 때와 끝에 시작한 블록 수, 마지막 시작 − 첫 시작, 첫과 마지막 시작의 globaltimer − 띄운 때의 호스트 `CLOCK_REALTIME`. 뒤의 둘은 노드마다 일정한 시계 차를 품는다(pilot에서 블록이 바로 시작한 셀: rain 3 358.6–3 358.7 ms, sunny 3 672.6 ms, n=2씩 `[측정]`). 같은 노드끼리 비교할 때만 뜻이 있고, 판정식에는 쓰지 않는다 |
| `probe_n_r*`, `probe_done_200ms_r*`, `probe_stuck_r*`, `probe_max_ms_r*`, `probe_done_end_r*` | kv: 새 스트림 복사 수, 200 ms 안에 끝난 수, 아직 도는 번호(없으면 `none`), 끝난 것 중 가장 늦은 시간, 끝에 끝난 수 |

**새 로그 줄** `[소스, 9절의 변경으로 고정]`.

| 줄 | 수준(`hf` / `hfp`) | 형식 |
|---|---|---|
| 시작 | WARN / INFO | `GIN/TS: handoff=1 rank=<r> shrink_handoff=<0\|1>`(gin-harden 시작 줄 바로 뒤) |
| 넘김 | WARN / INFO | `GIN/TS: rank <r>: aborting shrink proceeds past the parent's GIN error, raised for rank(s) <목록>, all excluded mono_ms=<t>` |
| 유지 | WARN / WARN | `GIN/TS: rank <r>: aborting shrink keeps the parent's error (<사유>) mono_ms=<t>` |

유지 줄의 사유는 `NCCL_GIN_SHRINK_HANDOFF=0`, `the error is not ncclRemoteError`, `the communicator or its proxy has an error of its own`,
`a group job of the communicator is not completed`, `no GIN state`, `GIN progress threads (their error names no peer)`,
`the GIN state is shared with another communicator`, `a GIN backend other than GDAKI`, `no record of the GIN error`,
`the GIN error was raised for more than 64 peers`, `a GIN error was raised without a peer`, `no peer recorded`,
`the GIN ranks cannot be mapped to communicator ranks`, `it was raised for rank <w> (GIN rank <p>), which is not excluded` 중 하나다.

**드라이버 kv**(이 실험의 드라이버, 9절 3번): `hog_slack`, `hog_prealloc`, `hog_preloaded`, `hog_local_bytes`, `hog_regs`, `hog_started_probe`,
`probe_n`, `probe_done_200ms`, `probe_stuck`, `probe_max_ms`, `probe_after_hog_ms`, `hog_started_end`, `hog_start_spread_ms`,
`hog_first_start_rel_ms`, `hog_last_start_rel_ms`, `probe_done_end`, `ho_parent_async_after`, `ho_devcomm_destroy_rc`, `ho_devcomm_destroy_ms`,
`final_signal_read`.

### 3.2 셀 키와 판정식 문법

셀 키(`cell@build`), 판정 대상(8절 제외를 거친 시행), "자료 부족" 규칙, 판정식 문법은 `../harden/EXPERIMENT.md` 3.2절과 같다(곧
`../s2_close/EXPERIMENT.md` 3.2절). 이 실험의 [score.py](score.py)는 `../s2_close/score.py`의 판정식 평가 함수를 그대로 불러 쓴다. 숫자로 읽히는
값(`hoff_ranks_r0`의 `1`)은 숫자로 비교한다. 판정은 맞음, 틀림, 자료 부족 중 하나다.

### 3.3 예측 요약

전체 판정식은 [predictions.csv](predictions.csv)에 있다. "n"은 계획한 판정 시행 수다.

| 예측 | id | 셀 | 판정 기준(요약) | 근거 |
|---|---|---|---|---|
| 죽은 rank를 뺀 중단 shrink가 1-rank 통신기를 돌려주고, allreduce가 맞고, 새 통신기에 비동기 오류가 없다 | S1 | `hd_shrink_b@hf` | ≥9/10 | 9절 1번 `[소스]`. 1-rank 아이 통신기는 이 테스트베드에서 처음 `[미확인]` |
| 넘김 줄이 rank 1만 적고, 유지 줄이 없으며, 부모는 shrink 뒤에도 GIN 오류를 보고한다 | S2 | `hd_shrink_b@hf` | ≥9/10 | 거절은 상대를 적은 뒤 오류를 세운다 `[소스]` |
| shrink가 500 ms 안에 돌아오고, 새 통신기 해제와 부모 abort가 오류 없이 끝난다 | S3 | `hd_shrink_b@hf` | ≥9/10 | pilot 16.5–17.3 ms(셀 셋, n=1씩) `[측정]`. pilot 뒤 5 s에서 고침 |
| 대조: gin-harden 라이브러리에서는 shrink가 GIN 오류로 바로(100 ms 안) 실패한다 | S4 | `hd_shrink_b@hd` | ≥4/5 | gin-harden pilot 0.0 ms(n=1) `[측정]` |
| 대조: 스위치를 끄면 shrink가 실패하고 유지 줄이 스위치를 사유로 적는다 | S5 | `hf_shrinkoff_b@hf` | ≥4/5 | `[소스]` |
| 운영 빌드도 같은 shrink를 넘기고, 넘김 줄은 WARN에 보이지 않는다 | S6 | `hd_shrink_b@hfp` | ≥4/5 | `[소스]` |
| 상대를 적지 않은 오류(감시의 드러냄)가 있으면, 살아 있는 rank 1을 빼는 shrink도 순정 판정을 지킨다 | S7 | `hf_hog_f1_b@hf` | ≥4/5 | gin-harden pilot에서 rank 0 감시가 장애 461.9 ms 뒤 드러냄(n=1) `[측정]` |
| 대조(스위치 끔): devComm을 먼저 없앤 응용은 순정 확인으로도 1-rank 통신기를 얻는다(넘김, 유지 줄 없음) | S8 | `hf_shrinkdc_b@hf` | ≥4/5 | `[소스, 독립 리뷰]`. 대칭 창 해제가 죽은 rank를 찾는지 `[미확인]` |
| 대조: 두 커널 사이에 gin-harden의 호출(커널 적재, `cudaMalloc`, 스트림)이 있으면 pilot의 실패(복사 시간 초과, 복구 없음)가 다시 난다 | G1 | `hf_hog_f1_b@hf` | ≥4/5 | gin-harden pilot(n=1) `[측정]` |
| 그 순서에서는 GPU 채우기 커널이 두 rank 모두 GIN 커널 옆에서 시작하지 못하고, 새 스트림 8개의 4 B 복사도 200 ms 안에 하나도 끝나지 않으며, GIN 커널이 끝난 뒤 모두 끝난다 | G2 | `hf_hog_f1_b@hf` | ≥4/5 | H2. 1절의 rank 1 셈 `[측정, 추론]` |
| 그 순서에서는 격자를 블록 하나 줄여도 시작하지 못하고 pilot의 실패가 다시 난다 | G3 | `hf_hogslack_f1_b@hf` | ≥4/5 | H2 `[추론]`. 큐 읽기는 반대를 예측 |
| 두 커널 사이에 아무것도 없으면 가득 채우는 격자도 GIN 커널 옆에서 시작하고(많아야 한 블록 빼고), 복사가 모두 200 ms 안에 끝나며, 복사 시간 초과 없이 투명하게 복구된다 | G4 | `hf_hogpre_f1_b@hf` | ≥4/5 | H2 `[추론]`. gin-s2의 관측이 보통 커널에도 맞으면 rank 1에서 틀린다 |
| 두 커널 사이에 아무것도 없고 격자가 블록 하나 작으면 모든 블록이 바로 시작하고, 복사가 끝나며, 투명하게 복구된다 | G5 | `hf_hogpreslack_f1_b@hf` | ≥4/5 | H2와 큐 읽기 모두 이것을 예측 `[추론]` |
| 복구 재현 셀이 그대로 투명하다 | R1 | `f1_b`, `f3_b`, `bidirf_sym_b`(모두 `@hf`) | 셀마다 5/5 | gin-oneway 5/5씩 `[측정, 이전 실험]` |
| 끊김 없는 kill이 2 s 안에 죽음 원인으로 거절되고 abort가 돌아온다 | R2 | `f4_b@hf` | 5/5 | gin-harden pilot에서 kill 뒤 1.6 ms(n=1) `[측정]` |
| 원격 접근 오류를 거절하고, 받는 쪽 대기가 오류로 풀리며 abort가 5 s 안에 돌아온다 | R3 | `f2rel_b@hf` | 5/5 | gin-harden 예측 그대로 `[소스]` |
| 받기만 하는 rank가 죽은 상대를 2 s 안에 드러내고 abort가 돌아온다 | R4 | `hd_rxdeath_b@hf` | ≥4/5 | gin-harden pilot 20.2 ms, 1.9 ms(n=1) `[측정]` |
| 운영 빌드가 kill된 상대를 2 s 안에 죽음으로 거절하고 죽음 1을 센다 | R5 | `hdp_kill_b@hfp` | 5/5 | gin-harden pilot 1.6 ms(n=1) `[측정]` |
| 통계 API가 두 rank에서 라운드 1, 복구 1, 거절 0을 센다 | R6 | `f1_b@hf` | 5/5 | `[소스]` |
| kill 뒤 통계 API가 죽음 1, 거절 1을 센다 | R7 | `f4_b@hf` | 5/5 | `[소스]` |
| 4 KiB 지연: 이 실험 운영 빌드와 gin-harden 운영 빌드 차이 0.40 µs 이하 | P1 | `lat_4k@hfp` 대 `lat_4k@hdp` | 같은 hold의 실행 중앙값 | 장치 코드가 같다 `[소스]` |
| 256 KiB 지연: 차이 0.30 µs 이하 | P2 | `lat_256k@hfp` 대 `lat_256k@hdp` | 같음 | 같음 |
| 4 KiB 지연: 이 실험 운영 빌드와 gin-harden 연구 빌드 차이 0.40 µs 이하 | P3 | `lat_4k@hfp` 대 `lat_4k@hd` | 같음 | 같음 |
| 256 KiB 지연: 차이 0.30 µs 이하 | P4 | `lat_256k@hfp` 대 `lat_256k@hd` | 같음 | 같음 |

지연 경계는 gin-oneway가 같은 장치 코드에 쓴 값이다(4 KiB 10.56 − 10.56 = 0, 256 KiB 38.91 − 38.91 = 0, 실행 5씩, `../oneway/EXPERIMENT.md` 15절)
`[측정, 이전 실험. 원자료에서 다시 세지 않음]`.

**GPU 가득 참 2 × 2에서 읽기마다 예상하는 것** `[추론]`. 예측(G1–G5)은 H2의 열이다. 다른 열은 결과를 읽을 때 쓰려고 미리 적는다.

| 셀 | 두 커널 사이의 호출, 격자 | H2(할당과 커널 적재) | 큐 읽기(다 올라갈 수 없는 격자) | gin-s2 관측이 보통 커널에도 맞음 |
|---|---|---|---|---|
| `hf_hog_f1_b` | 있음, 가득 | 시작 안 함, 새 스트림 복사 모두 멈춤, 거절 | 한 블록 빼고 시작, 복사 일부만 멈춤, helper가 큐를 나누면 거절 | rank 1에서 시작 안 함 |
| `hf_hogslack_f1_b` | 있음, 하나 작게 | 위와 같음 | 모두 시작, 복사 끝남, 투명 | rank 1에서 시작 안 함 |
| `hf_hogpre_f1_b` | 없음, 가득 | 한 블록 빼고 시작, 복사 끝남, 투명 | `hf_hog_f1_b`와 같음 | rank 1에서 시작 안 함 |
| `hf_hogpreslack_f1_b` | 없음, 하나 작게 | 모두 시작, 복사 끝남, 투명 | 모두 시작, 복사 끝남, 투명 | rank 1에서 시작 안 함 |

## 4. 범위

**포함.**
- 9절 1번의 라이브러리 계층 하나([hf_layer.diff](hf_layer.diff), `hd` 트리 기준, 2개 파일)와 그 운영 빌드.
- 9절 3번의 드라이버 선택(GPU 채우기 블록의 시작 시각, 두 커널 사이의 호출 앞당기기, 블록 줄이기, 새 스트림 복사 확인, shrink 뒤 부모 오류,
  shrink 전 devComm 없애기).
- 7절의 셀 키: 새 셀 2개(`hd_shrink_b@hf`, `@hfp`), 진단 셀 4개, 대조 3개(`hd_shrink_b@hd`, `hf_shrinkoff_b`, `hf_shrinkdc_b`), 회귀 7개, 지연 6개.

**제외.**
- GPU가 가득 찬 동안의 복사를 라이브러리에서 고치기. 9절 2번에 이유를 적었다. 요약: 원인이 아직 확인되지 않았다. H2가 맞다면 복사를 묶는 것은
  같은 프로세스의 할당과 커널 적재라서 라이브러리가 막을 수 없다. GPU 명령 없이 장치 상태에 닿는 길도 없다: 게이트 단어는 게시와 대기마다 장치가
  원자적으로 고치므로 장치 메모리에 있어야 하고, CPU가 GPU 메모리를 직접 읽고 쓰려면 gdrdrv 커널 모듈이 필요한데 rain에 올라와 있지 않으며
  (`/dev/gdrdrv` 없음, 2026-10-09 확인 `[측정]`) 클러스터 규칙상 모듈을 올리지 않는다. 막힌 쓰기를 다른 스트림으로 다시 내면 늦게 도착한 옛 쓰기가
  새 값을 덮는다. 그래서 이 실험은 원인만 잰다.
- 중단하지 않는 shrink(`NCCL_SHRINK_DEFAULT`), split, revoke 뒤 shrink: 판정을 바꾸지 않는다(순정 그대로).
  정정(본 실행 뒤, 코드 리뷰 L7): revoke 뒤의 shrink라도 `NCCL_SHRINK_ABORT`이면 넘김 규칙이 걸린다. 코드는 revoke 여부를 보지 않는다
  (`commShrinkAbortReady`) `[소스]`. revoke 셀은 없다(13절).
- 3 rank 이상(gin-multirank의 몫): 상대 번호를 통신기 rank로 옮기는 식은 일반 경우로 썼지만 2 rank로만 잰다. 살아남은 rank들이 서로 다른 판정을 내릴 때(한
  rank는 넘기고 다른 rank는 유지) 생기는 일도 재지 않는다(18절).
- GIN progress 스레드가 있는 백엔드(CPU proxy doorbell), GDAKI가 아닌 GIN 백엔드: 넘기지 않고 순정 판정을 지킨다 `[소스]`. 이 테스트베드는 GPU
  doorbell만 쓴다 `[측정: gin-harden pilot 로그 doorbell mode=GPU]`.
- 실제 link down, flap, 재부팅, 드라이버 재적재, 커널 모듈 적재, RoCE 주소 변경, iptables: 하지 않는다(8절).

## 5. 테스트베드와 버전

| 항목 | 값 | 확인 방법과 날짜 |
|---|---|---|
| 노드, NIC, 펌웨어, GPU, CUDA | gin-harden과 같다: rain(rank 0, Quadro RTX 5000, 48 SM), sunny(rank 1, RTX A4000, 48 SM), ConnectX-6 fw 20.43.4100, CUDA 12.8 | `../harden/EXPERIMENT.md` 5절. SM 수는 gin-harden pilot kv `hog_sms`(n=1씩) `[측정]` |
| rain 드라이버, 커널 | NVIDIA 570.211.01, 5.15.0-97-generic, `PeerMappingOverride=1`, `nvidia_peermem` 적재, gdrdrv 없음 | `[측정]` 2026-10-09 rain(`nvidia-smi` 한 번, `/proc/driver/nvidia/params`, `lsmod`, `/dev/gdrdrv`). sunny `[미확인]` |
| `hd`, `hdp` 번들 | libnccl `e209032310a2cefd5d71e86533674bd6`, `4818e30bb9c4b935edd1604fec0c3f6a`, 드라이버 `c0b73e0966c8350209d8dc71c8fa8c3b` | gin-harden 배포 확인(`../harden/deploy_check.txt`) `[측정, 이전 실험]` |
| `hf`, `hfp`, 새 드라이버 | libnccl `hf` `b6372d8622f6a7eceb9fd4528c00e707`, `hfp` `1ae4ce9aecb1727248db7eb3699ad110`. 드라이버 `9493584d5a321277c61863f4ed6ac379`(`hf`, `hfp`가 씀). 소스 `../gin_ts2.cu` md5 `1e4fd2f48ef9f42343ea672d3388fa23`. [deploy_hf.sh](deploy_hf.sh)가 이 md5를 확인한다 | `[측정]` 2026-10-09 독립 리뷰 반영 뒤 다시 빌드 때 rain(세션 스크래치 `agent_ts2hf/out/`). 배포 04:50:54–04:51:18 뒤 두 노드 md5가 소스와 같음([deploy_check.txt](deploy_check.txt)) |
| 변경분 | [hf_layer.diff](hf_layer.diff)(`hd` 트리 기준, md5 `a2bcaf69`, 2개 파일 +176/−1), 전체 diff [gin_transparent_hf.diff](gin_transparent_hf.diff)(pristine 기준, md5 `882dfff7`). 순정에 전체 diff를, 그리고 gin-oneway 전체 diff + gin-harden 계층 + 이 계층을 더하면 각각 이 트리와 같다 | `[측정]` 2026-10-09 [make_diff_hf.sh](make_diff_hf.sh) |

## 6. 변수

- **독립변수.**
  - 빌드: `hf`, `hfp`, `hd`, `hdp`.
  - 넘김 스위치: `NCCL_GIN_SHRINK_HANDOFF`(기본 1, 대조 셀에서 0).
  - devComm 먼저 없애기: 없음, 있음(`GIN_TS_SHRINK_DEVCOMM_DESTROY=1`, 스위치 끈 대조 셀).
  - GIN 커널과 GPU 채우기 커널 사이의 호출: gin-harden 순서(점유율 질의로 커널 적재, `cudaMalloc`, 스트림 생성), 없음(`GIN_TS_HOG_PREALLOC=1`: 그
    호출을 GIN 커널 전에).
  - GPU 채우기 격자 크기: SM 수 × SM당 최대 블록 수(가득), 그보다 1 적게(`GIN_TS_HOG_SLACK=1`).
  - 장애: rank 1 kill, rank 0 kill, rank 0 로컬 QP 오류, rank 1 상대 QP 오류, 양방향 로컬 QP 오류, 원격 접근 오류.
- **종속변수.** 3.1의 열: shrink 결과와 시간, 새 통신기의 rank 수와 allreduce 확인과 비동기 오류, 부모의 비동기 오류, 넘김과 유지 줄과 사유, 감시의
  드러냄, 복사 시간 초과, 복구와 거절, GPU 채우기 블록의 시작 수와 시각, 새 스트림 복사의 완료 수와 번호, devComm 없애기의 결과, 통계 API 값,
  지연 p50.
- **통제변수.** gin-harden과 같다: IB 타임아웃 14, GPU doorbell, 투명 복구와 재연결과 범위 스위치 기본값, 복사 상한 2 000 ms, 펌웨어 단계 상한
  3 000 ms, abort의 helper 대기 3 000 ms. 기존 셀 정의는 `../harden/cells.sh` 그대로다(빌드만 바꿈). 시행마다 프로세스를 새로 띄운다. GPU 채우기
  커널은 3 000 ms, 새 스트림 복사는 그 커널을 띄운 20 ms 뒤에 8개(스트림, event, 버퍼는 GIN 커널 전에 만듦).

## 7. 실험 셀, 반복 수, 대조군

반복 수: 새 셀 10(운영 빌드 shrink는 5), 진단 셀 5, 대조 5, 회귀 5. 지연 셀의 반복은 실행 수다(실행마다 3000번). 정의 원문은 [cells.sh](cells.sh)이고,
gin-harden에서 가져온 셀은 `../harden/cells.sh`의 정의를 그대로 부른다.

| 셀 | 조건 | 빌드와 반복 수 | 종류 |
|---|---|---|---|
| `hd_shrink_b` | gin-harden 정의 그대로: 양방향, rank 1 kill 3 500 ms, rank 0이 주 대기 뒤 `ncclCommShrink(comm, {1}, NCCL_SHRINK_ABORT)`, 새 통신기에서 1024개 float allreduce(5 s 상한) 확인, 해제. 16 KiB × 400 | `@hf` 10, `@hfp` 5, `@hd` 5 | 새 셀(`hf`, `hfp`), 대조(`hd`) |
| `hf_shrinkoff_b` | `hd_shrink_b`에 rank 0만 `NCCL_GIN_SHRINK_HANDOFF=0` | `@hf` 5 | 대조 |
| `hf_shrinkdc_b` | `hf_shrinkoff_b`에 rank 0이 shrink 전 `ncclDevCommDestroy`(옛 커널이 끝났을 때만) | `@hf` 5 | 대조 |
| `hf_hog_f1_b` | `f1_b`(rank 0 로컬 QP 오류, 256 KiB × 120)에 두 rank의 GPU 채우기 커널 3 000 ms(가득). 두 커널 사이의 호출은 gin-harden 순서. 새 스트림 복사 확인. rank 0은 주 대기 뒤 살아 있는 rank 1을 빼는 중단 shrink | `@hf` 5 | 진단, 넘김 규칙의 대조 |
| `hf_hogslack_f1_b` | 같고 격자 블록 1 적게, shrink 없음 | `@hf` 5 | 진단 |
| `hf_hogpre_f1_b` | `f1_b`에 GPU 채우기 커널(가득), 두 커널 사이의 호출을 GIN 커널 전에(`GIN_TS_HOG_PREALLOC=1`), 새 스트림 복사 확인 | `@hf` 5 | 진단 |
| `hf_hogpreslack_f1_b` | 같고 격자 블록 1 적게 | `@hf` 5 | 진단 |
| `f1_b`, `f3_b`, `bidirf_sym_b`, `f4_b`, `f2rel_b`, `hd_rxdeath_b` | gin-harden 정의 그대로 | `@hf` 각 5 | 회귀 |
| `hdp_kill_b` | gin-harden 정의 그대로(`f4_b`와 같고 훅 없음) | `@hfp` 5 | 회귀 |
| `lat_4k`, `lat_256k` | 투명 복구 켬, 장애 없음, 3000번 반복. 같은 hold에서 세 빌드를 섞어 돈다 | `@hfp`, `@hdp`, `@hd` 각 5 | 대조 |

**합계.**

| 종류 | 셀 시행 | 지연 실행 |
|---|--:|--:|
| 새 셀(`hd_shrink_b@hf`, `@hfp`) | 15 | |
| 진단(GPU 채우기 2 × 2) | 20 | |
| 대조(`hd_shrink_b@hd`, `hf_shrinkoff_b`, `hf_shrinkdc_b`) | 15 | 30 |
| 회귀(`hf`, `hfp`) | 35 | |
| 합 | 85 | 30 |

예측 24줄: 새 동작 9, 대조 8(지연 4 포함), 회귀 7. 주제로 나누면 넘김 8, GPU 가득 참 5, 회귀 7, 지연 4.

## 8. 제외 기준과 중단 기준

**제외 기준.** 제외한 시행은 셀별로 따로 세어 보고한다([score.py](score.py) `status_of`).
- pilot(`results/<날짜>_pilot/`)은 채점하지 않는다.
- NCCL 초기화 전 실패(`bind_fail == 1`)는 제외하고 다음 번호로 계획한 반복 수를 채운다.
- 장애 미적용은 제외하고 다음 번호로 채운다: rank 0 훅 셀(`f1_b`와 GPU 채우기 셀 넷)에서 `n_fires_r0 == 0`, rank 1 훅 셀(`f3_b`)에서
  `n_fires_r1 == 0`, 두 rank 훅 셀(`bidirf_sym_b`)에서 어느 하나가 0, `trigger_miss > 0`, rank 1 kill 셀(`f4_b`, `hd_shrink_b`, `hf_shrinkoff_b`,
  `hf_shrinkdc_b`, `hdp_kill_b`)에서 `killed != 1`, rank 0 kill 셀(`hd_rxdeath_b`)에서 `r0_killed != 1`.
- 순서 미적용은 제외하고 다음 번호로 채운다: GPU 채우기 셀에서 rank 0 훅이 그 커널의 3 s 창 밖(`fault_after_launch_r0_ms`가
  `hog_launch_after_launch_ms_r0` 초과, 그 + 3 000 미만이 아님).
- 펌웨어 초과는 제외하고 다음 번호로 채운다: 어느 rank든 펌웨어 감시 줄(`n_fwdog_r*`)이나 `rs_fw_overruns_r*`가 0이 아님(gin-harden 8절과 같은
  이유: 명령 하나가 느리면 감시가 그 문맥에 영구히 발동한다).
- 채우려고 다시 돈 시행이 셀 키마다 계획의 50%를 넘으면 그 셀 키는 멈추고 "자료 부족"으로 둔다.

**설정 확인.** 하나라도 어긋나면 제외가 아니라 그 블록을 멈춘다.
- `hf` 시행: 두 rank(kill된 rank 빼고)에 gin-harden 시작 줄(`harden=1 ... production=0`), 이 실험 시작 줄(`handoff=1`), 투명 복구 시작 줄, 사용자
  devComm abort 단어 줄, `oneway=1` 줄이 있고, `shrink_handoff`가 1이다(`hf_shrinkoff_b`, `hf_shrinkdc_b`의 rank 0만 0).
- `hd` 시행: gin-harden 시작 줄, 투명 복구 시작 줄, abort 단어 줄, `oneway=1` 줄이 있고 이 실험 시작 줄은 없다.
- `hfp`, `hdp` 시행: 두 시작 줄이 WARN에 없고(`hd_on == 0`, `hf_on == 0`), kv에 `rs_api=1`, `rs_contexts >= 1`.
- `hf`, `hd` 시행에 시험 스위치 줄(gin-harden과 그 전 실험의 것)과 끊김 줄이 없다.
- 실행기 meta의 `left_rules`(시행 뒤 남은 `gin-harden-` iptables 규칙)가 0이다.

**pilot에서 보이는 결함.** 태그 전이므로 고칠 수 있다. 고친 것은 12절과 13절에 적고, 고친 뒤에는 그 셀의 pilot을 다시 돈다. 예:
- 셀 조건이 만들어지지 않음: `hf_hog_f1_b`에서 rank 0 감시가 드러내지 않음(그러면 S7의 조건이 없다), `hf_hogpreslack_f1_b`에서 블록이 모두
  시작하지 않았는데 rank 0에서도 그럼(GIN 커널이 블록 자리 둘 이상을 막음: 줄일 블록 수를 바꾼다), 새 스트림 복사 수가 8이 아님, `hf_shrinkdc_b`에서
  옛 커널이 shrink 전에 끝나지 않아 devComm을 없애지 못함.
- 판정식 경계: shrink 시간(S3의 5 s. pilot 뒤 500 ms로 고침, 12절).
- 구현 결함: 회귀 셀이나 새 셀에서 예측과 다른 동작이 구현 탓으로 보이면 고치고 다시 빌드, 배포(새 디렉터리)한다.

**중단 기준.**
- **잠금.** 모든 클러스터 명령은 `harness/gpu-initiated/common/cluster_run.sh -w 10800` 안에서 돈다([chain.sh](chain.sh), 꼬리표 `ghf-<hold>`).
  10 800 s 안에 잠금이나 유휴 링크를 얻지 못하면(종료 코드 75) 그 hold를 미룬다. `prio-` 작업에는 양보한다. hold 하나는 15분 이하이고
  `timeout -s KILL 880`으로 묶는다.
- **하지 않는 것.** 실제 link down이나 flap, 재부팅, 드라이버 재적재, 커널 모듈 적재, RoCE 주소 변경, 시스템 TCP 설정 변경, iptables 규칙 추가. 실행기
  `../harden/run_trial_hd.sh`의 iptables 끊김(`MGMT_MUTE`)은 어느 셀도 켜지 않는다. [hold.sh](hold.sh)는 hold 앞뒤에 `gin-harden-` 꼬리표 규칙 수를
  세고, 늘었으면 `STOP_iptables`로 멈춘다(다른 실험의 규칙은 지우지 않는다).
- **프로세스.** 실행기는 gin-harden 것 그대로다: 우리가 띄운 프로세스만 기록한 PID로 끄고, 원격 PID는 명령줄에 그 시행의 고유 꼬리표가 있을 때만
  신호한다. 이름으로 끄지 않는다. 다른 사용자 작업(gds-kv, NVMe-oF, gdsio, mooncake, `prio-` 작업)은 건드리지 않는다. `left > 0`이 두 시행
  연속이면 멈춘다.
- **CUDA 메모리 오류.** hold 안의 어느 시행이든 rank 종료 코드 139이거나 로그나 kv에 illegal address, illegal memory access, unspecified launch failure가
  보이면 그 hold 뒤로 멈춘다(`STOP_cuda`).
- **mlx5 오류.** hold 앞뒤에 두 노드의 mlx5 커널 줄 전체와 rain의 펌웨어 명령 계수를 남긴다. 새 mlx5 명령 오류 줄이나 펌웨어 명령 실패 계수 증가가
  보이면 그 hold 뒤로 멈춘다(`STOP_mlx5`). 판정은 gin-harden 8절과 같다.
- **배포.** 새 번들은 새 디렉터리 `hf/`, `hfp/`에만 둔다. 대상 파일이 이미 있거나 소스가 5절의 md5와 다르면 배포 스크립트가 멈춘다. 배포 뒤 기존 번들
  파일의 md5가 두 노드에서 그대로인지 확인한다. `hd/`, `hdp/`는 읽기만 한다.

## 9. 실행 방법과 경로

### 1. 라이브러리 계층 (`hf`, `hfp`)

[hf_layer.diff](hf_layer.diff)(`hd` 트리 기준)와 전체 diff [gin_transparent_hf.diff](gin_transparent_hf.diff). 바뀐 파일(+/−줄):

| 파일 | +/− | 무엇 |
|---|--:|---|
| `src/transport/net_ib/gdaki/gin_host_gdaki.cc` | +74/−0 | 오류 올림의 상대 기록, 스위치, 시작 줄 |
| `src/init.cc` | +102/−1 | 중단 shrink의 준비 확인(`commShrinkAbortReady`), 기록 지우기 |

(a) **오류 올림마다 상대를 적는다**(`gdakiBlameNote`). 기록은 통신기 GIN 상태의 비동기 결과 칸 주소(`&sharedRes->ginState.asyncResult`, 그 통신기의
GDAKI 문맥마다 `q4->asyncResult`)를 키로 한다. `ncclCommGetAsyncError`가 GDAKI 쪽에서 오류를 얻는 길은 넷이고 `[소스]`, 넷 모두 오류 표시를 세우기
전에 적는다.
- 거절(`gdakiTsDecline`): 그 상대. 사용자 abort 단어, 비동기 결과와 같은 자물쇠 안(`gdakiTsToComm`)에서.
- 투명 복구가 맡지 않는 분류 기록(`gdakiQ4Handle`, 게이트 없는 QP 포함): 그 QP의 상대.
- 감시의 드러냄(`gdakiTsSurface`): 상대 없음.
- QUERY_QP로 찾은 오류(`ncclGinGdakiQueryLastError`의 확인 경로, 분류기가 없거나 투명 복구가 꺼진 때): 상대 없음.
키가 없는 올림(GDAKI 문맥에 칸이 없음)은 이 프로세스 전체에서 넘김을 끈다. 기록은 GIN 상태를 풀 때 지운다(`init.cc` `commFree`,
`ncclGinTsBlameForget`). 지우기 전에 같은 주소를 다른 통신기가 받는 경우는 없고, 남은 기록은 상대를 더할 뿐 빼지 않는다 `[소스]`.

(b) **중단 shrink의 준비 확인**(`commShrinkAbortReady`, `ncclCommInitChildComm`에서 `NCCL_SHRINK_ABORT`일 때만 `ncclCommEnsureReady` 대신). 먼저
순정 확인을 그대로 부른다. 오류가 없거나 초기화 중이면 그 답을 돌려준다. 오류가 있으면 아래를 모두 만족할 때만 넘긴다(성공을 돌려준다). 하나라도
아니면 순정 답(그 오류)을 돌려주고 유지 줄에 사유를 적는다.
- 스위치 `NCCL_GIN_SHRINK_HANDOFF`가 1(기본).
- 오류가 `ncclRemoteError`이고, 통신기와 proxy의 비동기 결과는 성공(오류가 GIN 쪽에서만 옴).
- 통신기에 끝나지 않은 그룹 작업이 없음(순정은 오류가 없을 때만 그 작업을 마무리한다).
- GIN이 연결됐고 GIN progress 스레드가 없음(그 스레드의 오류는 상대를 모름).
- GIN 상태를 다른 통신기와 나누지 않음(`sharedRes->owner == comm`, 참조 1).
- 그 GIN 상태의 모든 devComm이 GDAKI 백엔드(`ncclGinIbGdaki`).
- 기록이 있고, 상대 없는 올림이 없고, 적힌 상대가 1–64개이며, 각 상대를 통신기 rank로 옮긴 값(`ncclGinConnectOnce`가 연결한 팀: 전체 연결이면 그대로,
  아니면 `rank + (상대 − rank / stride) × stride`, stride는 `contiguousRanksPerHost`)이 자기 아닌 범위 안의 rank이고 빼는 목록에 있음.
넘기면 넘김 줄에 그 rank 목록을 적는다(연구 빌드 WARN, 운영 빌드 INFO).

(c) **아이 통신기는 부모의 오류를 물려받지 않는다** `[소스]`. 중단 shrink에서는 `shareResources`가 거짓이라(`ncclCommInitChildComm`) 아이가 자기
`sharedRes`(GIN 상태 포함), abort 플래그, 비동기 결과(0으로 시작)를 새로 만든다(`commAlloc`). 아이 GIN 상태는 devComm을 만들 때까지 연결되지 않는다
(`ncclGinConnectOnce`는 devComm 생성에서만). 부모의 오류는 지우지 않는다. 응용은 부모를 abort하거나 없애야 한다. 1-rank 아이의 `bootstrapSplit`은 부모
bootstrap으로 자기 자신에게만 보내므로 빠진 rank에 연결하지 않는다 `[소스, 추론]`. 독립 리뷰가 이 셋(자원, 비동기 결과, 스레드 지역 변수)을 소스에서
다시 확인했다(12절).

응용 쪽의 다른 길: devComm을 모두 없앤 뒤 shrink하면 순정 확인도 지날 것으로 읽힌다(1절). 넘김과 다른 점은 둘이다: 응용을 바꿔야 하고, 그 devComm의
모든 오류(살아 있는 상대에 대한 것까지)가 함께 사라진다. 대조 셀 `hf_shrinkdc_b`가 이 길을 잰다.

(d) **남는 점** `[추론]`.
- 판정은 rank마다다. 3 rank 이상에서 살아남은 rank 하나만 유지하면(그 rank의 오류가 살아 있는 상대 탓) 다른 rank의 shrink는 그 rank를 기다린다. 순정에서
  어느 rank든 shrink가 실패할 때와 같다.
- 감시의 드러냄처럼 상대를 적지 않은 올림이 한 번이라도 있으면, 나중에 거절이 상대를 적어도 넘기지 않는다(보수적).
- 기록은 오류 표시가 지워져도(응용 스레드 복구 API의 커밋) 남는다. 그 뒤 새 오류가 나면 옛 상대까지 빼야 넘긴다(보수적).
- 2 rank, 노드마다 GPU 하나에서는 올림의 상대가 언제나 rank 1이고 stride가 1이라, "빼지 않은 rank" 사유와 rank 옮기기 식은 소스로만 확인했다. 이
  실험이 실제로 지나는 유지 경로는 스위치 끔(S5)과 상대 없는 올림(S7) 둘뿐이다.

### 2. GPU가 가득 찬 동안의 복사: 원인 분석과 고치지 않는 이유

1절의 후보 셋을 지운 근거 `[소스]`.
- helper의 복사는 모두 문맥마다 하나인 복구 스트림에서 낸다: `gdakiRecRegister`가 `cudaStreamCreateWithFlags(&r->stream, cudaStreamNonBlocking)`과
  `cudaHostAlloc(..., cudaHostAllocDefault)`(고정 메모리 staging)로 만든다. `gdakiRecD2H`, `gdakiRecH2D`, `gdakiTsZeroDev`는 그 스트림에
  `cudaMemcpyAsync`를 내고 `gdakiRecCopyWait`이 event를 2 000 ms까지 확인한다. 라운드 중에 할당이나 커널은 내지 않는다.
- 드라이버는 GIN 커널을 `cudaStreamNonBlocking` 스트림 둘에, GPU 채우기 커널을 또 다른 `cudaStreamNonBlocking` 스트림에 띄운다(`../gin_ts2.cu`).
  레거시 기본 스트림에는 그 사이 아무것도 내지 않는다.

남은 읽기 둘 `[추론, 미확인]`.
- **H2: 두 커널 사이의 할당과 커널 적재.** gin-harden 드라이버는 GIN 커널을 띄운 뒤 GPU 채우기 커널의 점유율을 묻고(지연 적재에서 이때 그 커널
  코드가 올라감), `cudaMalloc`과 스트림 생성을 한 다음 그 커널을 띄운다. CUDA 프로그래밍 가이드의 "implicit synchronization"은 장치 메모리와 고정
  호스트 메모리 할당이 그 사이에 있으면 서로 다른 스트림의 두 명령이 함께 돌지 못한다고 적는다 `[문서]`. 이것이 그 뒤의 GPU 명령을 돌던 GIN 커널이
  끝날 때까지 묶는다면 1절의 관측이 모두 설명된다: GPU 채우기 커널 전체가 늦게 시작했고(rank 1), helper의 복사가 GIN 커널이 끝난 순간 끝났다(rank 0).
  보통의 복구에서는 GIN 커널을 띄운 뒤 할당이 없으므로 복사가 끝난다.
- **큐 읽기: 다 올라갈 수 없는 격자.** SM 수 × SM당 최대 블록 수의 격자는 이미 상주한 1-블록 GIN 커널 옆에 다 올라갈 수 없다(rank 0의 GIN 커널은
  1 스레드라 그 SM에 256 스레드 블록 3개만 더 들어가고, rank 1의 GIN 커널은 256 스레드라 5개만 더 들어간다: Turing SM당 1 024 스레드, Ampere 1 536
  스레드). 같은 하드웨어 작업 큐에서 그 격자 뒤에 들어간 명령은 격자가 다 올라갈 때까지 묶인다는 읽기다. 이 읽기는 블록 대부분이 바로 시작한다고
  보므로 rank 1의 셈과 맞지 않는다. gin-s2에서 `CUDA_DEVICE_MAX_CONNECTIONS=32`가 비슷한 지연을 풀지 못한 것도 이 읽기에 불리하다(1절).
- 7절의 2 × 2가 이 둘과 gin-s2의 미해결 관측을 가른다(3.3의 두 번째 표). pilot(셀마다 n=1, 채점 안 함)은 H2와 맞았다(3절 머리, 12절) `[측정]`.

H2가 맞다면 뜻하는 것 `[추론]`: GIN 커널이 복구 중에 기다리는 동안 같은 프로세스의 어느 스레드든 `cudaMalloc`, `cudaHostAlloc`을 하거나 처음 쓰는 커널을
지연 적재하면, helper의 복사가 GIN 커널이 끝날 때까지 묶이고 복구는 복사 상한(2 s) 뒤 거절로 끝난다. 문제는 "GPU가 바쁨"이 아니라 "기다리는 GIN
커널 뒤의 암묵적 동기화"다. 응용 쪽 대책은 GIN 커널을 띄우기 전에 할당하고 커널을 미리 적재하는 것이다.

라이브러리에서 고치지 않는 이유.
- H2가 맞다면 복사를 묶는 호출은 라이브러리 밖에 있다. 라이브러리의 복사 자체는 이미 non-blocking 스트림의 비동기 복사다.
- 게이트 단어를 호스트 매핑 메모리로 옮기기: 장치는 게시와 대기마다 게이트에 원자적 더하기를 한다(`gin_gdaki_device_host_common.h`의 게이트 설명)
  `[소스]`. 호스트 메모리로 옮기면 빠른 경로의 매 연산이 PCIe 왕복을 탄다 `[추론]`. 라운드는 게이트 말고도 장치 QP 구조체, SQ와 CQ 링, 사본 영역을
  읽고 쓴다(`ncclGinRecoverPrepare`의 QP 상태 읽기, `gdakiTsReplayResume`의 SQ 링 읽기와 다시 보내기) `[소스]`. 이것들은 NIC와 GPU가 쓰는 GPU 메모리다.
- CPU가 GPU 메모리를 직접 읽고 쓰기(BAR1 매핑, gdrcopy): DOCA에 그 길이 있지만(`doca_gpunetio_gdrcopy.cpp`) gdrdrv 모듈이 rain에 없다 `[측정]`. 모듈
  적재는 클러스터 규칙으로 금지다.
- 막힌 복사를 다른 스트림으로 다시 내기: 읽기는 되지만(H2라면 다른 스트림도 묶인다), 쓰기(게이트의 epoch 절반, 다시 보낼 WQE, 인덱스)는 막힌 옛 쓰기가
  큐에 남아 나중에 도착하며 새 값을 덮는다 `[추론]`. 라운드는 쓰기가 필요하다.
- 부분 완화(독립 리뷰의 제안): 쉬는 중 점검이 읽는 두 칸(`abandoned`, `reported`)을 장치가 호스트 매핑 단어에도 쓰게 하면 점검에 복사가 필요 없다.
  그러면 helper가 점검에서 멈추지 않아 감시가 상대 없이 드러내는 일은 없어지지만, 라운드의 복사는 그대로 묶인다 `[추론]`. 이 실험에서는 하지 않는다
  (S7이 지금 동작을 잰다).
- NIC로 GPU 메모리를 읽고 쓰기(자기 자신으로의 RDMA): GPU의 큐를 거치지 않지만 메모리 등록이 새로 필요하고, 게이트 단어에서 SM 원자 연산과 맞서는
  쓰기의 원자성을 따로 확인해야 한다(gin-s2의 `gate_ce_test.cu`는 복사 엔진 쓰기만 확인). 다른 실험의 몫이다(19절).

그래서 이 실험은 원인을 잰다: 9절 3번의 블록 시작 시각, 새 스트림 복사 확인, 두 커널 사이 호출 앞당기기, 블록 하나 줄인 격자(예측 G1–G5).

### 3. 드라이버 (`../gin_ts2.cu`)

응용 코드에 복구는 넣지 않는다. 선택 몇 개만 더했다(설정하지 않으면 동작은 그대로이고 지연 루프는 바뀌지 않았다 `[소스]`).
- GPU 채우기 블록은 시작할 때 자기 시작 시각(globaltimer)을 호스트 매핑 배열에 쓴다. 배열은 GIN 커널 전에 만든다. kv `hog_started_probe`(확인 때
  시작한 블록 수), 주 대기 뒤 `hog_started_end`, `hog_start_spread_ms`, `hog_first_start_rel_ms`, `hog_last_start_rel_ms`(띄운 때의 호스트 실시간
  기준, 어림).
- 두 커널 사이의 호출: 기본은 gin-harden 그대로(점유율 질의, `cudaMalloc`, 스트림 생성)다. `GIN_TS_HOG_PREALLOC=1`이면 그 호출과 커널 속성 읽기를
  GIN 커널 전에 한다(kv `hog_prealloc`, `hog_local_bytes`). 그러면 두 커널 사이에는 첫 반복을 기다리는 확인과 띄우기만 남는다.
- `GIN_TS_HOG_SLACK=<k>`: 격자를 SM 수 × SM당 최대 블록 수보다 k개 적게(kv `hog_slack`).
- `GIN_TS_HOG_PROBE=1`: GIN 커널 전에 non-blocking 스트림 P개(P = `CUDA_DEVICE_MAX_CONNECTIONS`, 기본 8), event, 장치 단어, staging을 만든다. GPU
  채우기 커널을 띄운 20 ms 뒤 스트림마다 4 B 장치→호스트 복사와 event를 내고 200 ms까지 확인한다(kv `probe_*`). 띄운 뒤 확인이 끝날 때까지 커널,
  할당, 레거시 기본 스트림 호출은 없다.
- `GIN_TS_SHRINK=1`: shrink 직후 부모의 `ncclCommGetAsyncError`(kv `ho_parent_async_after`).
- `GIN_TS_SHRINK_DEVCOMM_DESTROY=1`: shrink 전에 옛 커널이 끝났으면 `ncclDevCommDestroy`(kv `ho_devcomm_destroy_*`). 그 뒤 그 devComm으로 띄우던
  마지막 신호 읽기 커널은 건너뛴다(kv `final_signal_read`).
- 이 드라이버는 `hf` 헤더로 컴파일한다. 장치 헤더는 `hd`와 같다(빌드 스크립트가 확인). `hd`, `hdp` 셀은 gin-harden 드라이버(`c0b73e09`)를 그대로
  쓴다. 지연 셀의 두 드라이버는 지연 루프의 소스가 같다 `[소스]`.

### 4. 실행기

gin-harden의 [../harden/run_trial_hd.sh](../harden/run_trial_hd.sh)를 그대로 쓴다(같은 인자, 같은 시행 파일, `BUILD`만 `hf`, `hfp`, `hd`, `hdp`).
iptables 끊김(`MGMT_MUTE`)은 쓰지 않는다.

### 빌드 ([build_hf.sh](build_hf.sh), 세션 스크래치)

1. `setup`: `agent_ts2hd`의 소스, 연구 빌드 디렉터리 `build/`, 운영 빌드 디렉터리 `build-hdp/`를 `agent_ts2hf`로 복사한다(`build-hdp/`는
   `build-hfp/`가 됨). 의존 파일과 장치 manifest의 경로를 바꾸고 원래 시각을 돌려준다. 복사된 git worktree 등록(`agent_ts2hd`의 순정 트리)은 지운다.
   `agent_ts2hd` 작업 트리(= `../harden/hd_layer.diff`, md5 `2226872e`)를 스크래치 저장소에 "gin-harden hd" 커밋으로 남긴다. 복사 직후 `make -n`은 버전
   표시(`git_version.o`)만 다시 컴파일한다 `[측정]`.
2. `hf`: 이 계층을 작업 트리에 두고 증분 빌드. 다시 컴파일하는 객체는 `init.o`, `gin_host_gdaki.o`, `git_version.o`뿐이고 장치 객체는 없다 `[측정]`.
   libnccl → `out/hf`.
3. `hfp`: `build-hfp/`(모든 호스트 객체가 `hd`의 운영 플래그로 컴파일됨)에서 `CXXFLAGS=-DNCCL_GIN_TS_PRODUCTION`으로 증분 빌드. 다시 컴파일하는 객체는
   같은 셋이다 `[측정]`. libnccl → `out/hfp`.
4. `driver`: `../gin_ts2.cu`를 `build/` 헤더로 컴파일(→ `out/drv`). 경고를 오류로 다룬다.

빌드는 nice 19, 유휴 I/O 우선순위, 8 작업으로 돌렸다(다른 실험이 같은 노드에서 돈다).

### 배포 ([deploy_hf.sh](deploy_hf.sh))

두 노드의 새 디렉터리 `hf/`, `hfp/`에 둔다(8절 배포). 확인 출력은 파일로만 받는다. 메인 세션이 돌린다. 예상 30 s `[추론]`.

```
cd /home/unionxic/rdma-error-wt/gin-handoff/harness/gpu-initiated/gin_recovery/handoff
bash deploy_hf.sh deploy_check.txt
```

### 실행 ([hold.sh](hold.sh), [chain.sh](chain.sh), [cells.sh](cells.sh))

hold마다 `chain.sh`가 `cluster_run.sh -w 10800 -t ghf-<hold>`에 넣는다. 결과 폴더 아래 빌드별 폴더(`hf/`, `hfp/`, `hd/`, `hdp/`)에 시행 파일이 쌓인다.

| hold | 내용 | 추정 `[추론]` |
|---|---|---|
| H0 pilot | `hd_shrink_b` 세 빌드 1회씩, `hf_shrinkoff_b`, `hf_shrinkdc_b`, GPU 채우기 셀 넷, `f1_b`, `f4_b` 1회씩(`hf`), 4 KiB 지연 세 빌드 1회씩(14회). 채점 안 함 | 실제 1분 24초 `[측정]` |
| H1 | `hd_shrink_b` `hf` 10, `hd` 5, `hfp` 5, `hf_shrinkoff_b` 5, `hf_shrinkdc_b` 5(섞어서) | 4분 |
| H2 | GPU 채우기 2 × 2 각 5(섞어서) | 3분 |
| H3 | 회귀 `f1_b`, `f3_b`, `bidirf_sym_b`, `f4_b`, `f2rel_b`, `hd_rxdeath_b`(`hf`) × 5, `hdp_kill_b`(`hfp`) × 5 | 4분 |
| H4 | 지연 30실행(세 빌드, 두 크기, 섞어서) | 2분 |

시행 시간은 이 pilot에서 어림했다 `[측정, 추론]`: hold H0은 14회에 84 s(앞뒤 스냅숏 포함)였고 시행 `wall_s`의 합은 61.9 s라, 시행마다 약 1.5 s가 더
든다. 셀별 `wall_s`(n=1씩): shrink 셀 4.8–5.3 s, GPU 채우기 셀 3.9–6.1 s, `f1_b` 3.8 s, `f4_b` 5.3 s, 4 KiB 지연 1.8 s. pilot에 없는 회귀 셀은
gin-harden pilot의 값(`hd_rxdeath_b` 3.1 s, `hdp_kill_b` 5.3 s)이나 약 5 s로 잡았다. hold마다 잠금과 유휴 확인에 약 30 s가 더 든다. 본 실행(H1–H4,
115회)의 클러스터 시간은 잠금 대기를 빼고 약 13분이다 `[추론]`. pilot은 다른 실험의 hold 뒤에서 잠금을 12분 35초 기다렸다(04:51:22 대기 시작,
05:03:57 잠금) `[측정]`.

```
cd /home/unionxic/rdma-error-wt/gin-handoff/harness/gpu-initiated/gin_recovery/handoff
bash chain.sh results/<날짜>_pilot H0          # pilot, 채점 안 함
bash chain.sh results/<날짜> H1 H2 H3 H4        # 본 실행(태그 뒤)
```

### 채점

1. `../scripts/ts2/rows.py`로 빌드 폴더마다 시행 CSV를 만든다.
2. `../s2_close/rows_extra.py`, `../pair_check/rows_pc.py`, `../oneway/rows_ow.py`, `../harden/rows_hd.py`, 이 폴더의 `rows_hf.py`가 3.1의 열을 붙인다.
3. `score.py`가 [predictions.csv](predictions.csv)의 판정식을 3.2 문법대로 적용한다. 결과는 `results/<날짜>/SCORE.md`와
   `results/<날짜>/trials_scored.csv`다.

```
python3 score.py results/<날짜>
```

**출력.** 결과 폴더 `results/<날짜>/<빌드>/`. 원시 로그는 Release에 올린다.

## 10. 완료 조건과 QA 기준

- [x] 메인 세션이 pilot(H0)을 돌리고 결과를 12절에 적은 뒤, 고칠 것을 고치고 태그를 달았다.
- [x] 모든 셀이 계획한 반복 수만큼 실행됐다. 제외와 실패를 따로 센 표가 있다([SCORE.md](results/20261009/SCORE.md) 끝 표).
- [x] 예측 24줄마다 판정(맞음, 틀림, 자료 부족)과 놓친 시행 목록이 있다([SCORE.md](results/20261009/SCORE.md)).
- [x] 다른 에이전트가 `score.py`를 보지 않고 원자료에서 핵심 수치를 다시 셌다(shrink 결과와 시간, 넘김과 유지 줄, 부모와 아이의 비동기 오류, 복사 시간
  초과, 블록 시작 수와 간격, 새 스트림 복사, 통계 값, 지연)([qa_recount.md](results/20261009/qa_recount.md)).
- [x] 다른 에이전트가 `hf_layer.diff`와 드라이버 변경을 읽고 리뷰했다(설계 단계 리뷰는 12절, 본 실행 뒤 리뷰는 [qa/code_review.md](qa/code_review.md)).
- [x] smoke와 pilot, 제외 시행이 결과에 섞이지 않았다.
- [x] 새 빌드의 md5, 전체 diff, pristine + diff 확인, 운영 빌드의 strings 확인을 5절과 12절에 적었다.
- [x] 원자료를 Release에 올렸다(`data-20261009`, 14절). `DATA.md` 항목은 상위 문서와 함께 묶음 PR에서 적는다.
- [x] hold 전후 mlx5 스냅숏에 새 명령 오류가 없었다. hold 밖(H3과 H4 사이)에 sunny의 FWTracer 줄 하나가 생겼다(12절). `gin-harden-` iptables 규칙이 늘지 않았다.
- [x] 모든 시행에서 CUDA 메모리 오류(종료 코드 139, illegal address)가 없었다(`STOP_cuda` 없음).

## 11. 작업 체크리스트

- [x] pilot 원자료에서 두 실패의 순서 다시 세기, 소스에서 원인 좁히기(1절, 9절 2번)
- [x] 라이브러리 계층, 운영 스위치, 드라이버 선택 구현
- [x] 빌드: `hf`, `hfp`, 드라이버. pristine + diff 확인, 운영 빌드 strings 확인
- [x] `cells.sh`, `hold.sh`, `chain.sh`, `deploy_hf.sh`, `rows_hf.py`, `score.py`, `predictions.csv`
- [x] 채점 스크립트 합성 시험(실제 측정 아님)
- [x] 독립 리뷰(다른 에이전트)와 반영
- [x] 질문, 가설, 셀, 예측 초안 (`DRAFT`)
- [x] 배포(메인 세션, 2026-10-09 04:50:54–04:51:18)
- [x] pilot H0(메인 세션, 05:04:28–05:05:52, 채점 안 함), 결과로 고칠 것 고치기(12절)
- [x] 고정 절 완성, 상태 `PREREGISTERED`, 해시 기록을 커밋 하나로 만들고 그 커밋에 `prereg/` 태그
- [x] 본 실행 H1–H4와 채우기 hold (`RUNNING`)
- [x] 채점 (`QA`)
- [x] 독립 재계산과 코드 리뷰
- [x] 결과 정리, 원자료 Release(`data-20261009`). PR은 상위 문서와 묶어 메인 세션이 연다
- [x] 결론 확정 (`COMPLETE`)

## 12. 실행 기록 (시간순)

| 시각 | 무엇을 했나 | 결과와 근거(경로, 커밋, 실행 ID) |
|---|---|---|
| 2026-10-09 | 브랜치 `exp/gin-handoff`를 gin-harden 사전 등록 커밋(`692ff591`, 태그 `prereg/gin-harden-v1`)으로 빨리 감기(fast-forward). 그 커밋의 실행기, 셀 정의, 채점 함수, `hd_layer.diff`, 드라이버 소스를 그대로 쓰기 위함 | `git log` |
| 2026-10-09 | gin-harden pilot 원자료에서 shrink 셀과 GPU 채우기 셀의 순서를 다시 셈(1절). shrink 셀 rank 0의 오류 올림은 거절 한 번(상대 1)뿐이고 감시의 드러냄이 없음. GPU 채우기 셀은 rank 0 감시가 장애 461.9 ms 뒤 드러냄, rank 1의 abort 시작이 GIN 커널 끝 3 300.2 ms 뒤 `[측정, n=1씩]` | `../harden/results/20261009_pilot/hd/hd_shrink_b_n1_*`, `hd_hog_f1_b_n1_*` |
| 2026-10-09 | 스크래치 `agent_ts2hf` 준비(`build_hf.sh setup`): `agent_ts2hd`(작업 트리 md5 `2226872e`, 빌드 `e2090323`, 운영 빌드 `4818e30b`) 복사, 경로 바꿈, "gin-harden hd" 커밋 `[측정]` | [build_hf.sh](build_hf.sh) |
| 2026-10-09 | 계층 구현(9절 1번), 드라이버 선택(9절 3번). 연구, 운영 빌드와 드라이버 모두 경고 없이 컴파일(빌드됨, 실행 안 함). `hf` `e0f46cf0`, `hfp` `43228687`, 드라이버 `1e988dbc`(첫 빌드. 리뷰 반영 뒤 다시 빌드해 바뀜, 아래) `[측정]` | 세션 스크래치 `hf_work/build_hf1.log`, `build_hfp1.log`, `build_drv1.log` |
| 2026-10-09 | 운영 빌드 확인: `strings`에서 `NCCL_GIN_TS_TEST`, `GIN_FAULT_INJECT`, `GIN/FAULT`, `GIN_TS_DIAG`, `GIN_RECOVERY_DIAG`, `Q4_QPWATCH`, `Q4_LATE_READ`, `GDAKI_CQ_TYPE`, `GIN/TS: TEST`가 `hfp`에 0개(`hf`에는 16, 4, 11, 1, 2, 1, 1, 3, 23개, gin-harden의 `hd`와 같은 수). 새 함수는 내보내지 않음(`nm -D`). `init.o`의 운영 빌드 컴파일 명령에 `-DNCCL_GIN_TS_PRODUCTION`이 있음(`make -n`) `[측정]` | |
| 2026-10-09 | `make_diff_hf.sh`: 두 재현 확인 VERIFIED. `hf_layer.diff` md5 `3ee4854b`(2개 파일 +168/−1), 전체 diff md5 `502f8627`(첫 판. 아래에서 바뀜) `[측정]` | [make_diff_hf.sh](make_diff_hf.sh) |
| 2026-10-09 | 채점 스크립트 합성 시험: gin-harden pilot의 실제 시행 파일을 복사해 이 계층과 드라이버가 낼 줄과 kv를 넣은 시행 92개(예상 결과대로, 첫 판의 셀)로 `score.py`를 돌림. 새 열이 모두 뽑히고, 설정 확인을 통과하며, 일부러 넣은 제외 둘(GPU 채우기 창 밖의 장애, kill 기록 없음)이 걸리고, 넣은 셀의 예측이 모두 "맞음"으로 판정됨(넣지 않은 셀 셋의 R1, R3은 "자료 부족") `[측정]`. 실제 측정이 아니므로 형식과 판정 흐름만 보인다 | 세션 스크래치 `hf_work/synth/fab_hf.py` |
| 2026-10-09 | 독립 리뷰(다른 에이전트가 `hf_layer.diff`, 빌드 트리, 드라이버 변경, gin-harden pilot 원자료를 읽음, 코드만): 판정 "조건부로 예". 넘김 계층에서 제외하지 않은 상대의 오류를 넘기는 결함은 없음(오류 올림 넷 모두 표시 전에 기록, 순서와 자물쇠 순서, 아이 통신기의 자원과 스레드 지역 변수, rank 옮기기를 소스에서 확인). 막는 문제 둘은 GPU 가득 참 진단 쪽: (1) pilot의 rank 1 셈은 "블록 하나가 늦게 시작"이 아니라 "커널 (거의) 전체가 GIN 커널 끝 무렵 시작"을 뜻함, (2) 이 드라이버가 두 커널 사이에 할당을 더했음(CUDA 가이드의 암묵적 동기화 대상). 중간: 응용이 devComm을 먼저 없애면 순정 확인을 지날 것으로 읽힘, 진단 셀이 두 읽기를 가르지 못함, 2 rank에서는 "빼지 않은 rank" 경로를 지나지 않음. 낮음: 매크로 인자 안의 `#ifdef`, 64개 넘는 상대의 사유, 끝나지 않은 그룹 작업, 기록의 수명. 제안: 쉬는 중 점검을 복사 없이 하는 부분 완화 | 9절 1, 2번 |
| 2026-10-09 | 리뷰 반영. 계층: 매크로 인자 밖으로 로그 분기, 64개 넘는 상대에 따로 된 사유, 끝나지 않은 그룹 작업이 있으면 유지, 순정 확인에 대한 설명 고침(devComm을 먼저 없애는 길). 드라이버: 새 배열과 새 스트림 확인 준비를 GIN 커널 전으로(두 커널 사이는 gin-harden 그대로), `GIN_TS_HOG_PREALLOC`, 블록 시작 시각의 처음과 끝, `GIN_TS_SHRINK_DEVCOMM_DESTROY`. 셀: GPU 채우기 2 × 2(가득과 하나 작게 × 두 커널 사이 호출 있음과 없음, 각 5), `hf_shrinkdc_b` 5. 예측: G를 다섯으로 다시 쓰고(H2 고침), 스트림 번호 예측(옛 G4) 뺌, S8 더함. 다시 빌드(빌드됨, 실행 안 함): `hf` `b6372d86`, `hfp` `1ae4ce9a`, 드라이버 `9493584d`, 경고 0. `make_diff_hf.sh` 두 재현 VERIFIED, `hf_layer.diff` `a2bcaf69`(+176/−1), 전체 diff `882dfff7`. 운영 빌드 strings 수는 위와 같음 `[측정]`. 합성 시험을 새 셀까지 넣어 다시 돌림: 시행 102개, 판정 100, 예상대로(R1, R3만 자료 부족) `[측정, 실제 측정 아님]` | 세션 스크래치 `hf_work/build_hf2.log`, `build_hfp2.log`, `build_drv3.log`, `synth/fab_hf.py` |
| 2026-10-09 | 클러스터에서는 아무것도 돌리지 않았다(ssh, 배포, cluster_run.sh, GPU와 RDMA 프로그램 모두 없음). 배포, pilot, 본 실행은 메인 세션이 한다 | |
| 2026-10-09 04:50:54–04:51:18 | 배포(메인 세션, `bash deploy_hf.sh deploy_check.txt`, rc 0): 새 디렉터리 `hf/`, `hfp/`. 두 노드 md5가 소스와 같고(libnccl `b6372d86`, `1ae4ce9a`, 드라이버 `9493584d`), 드라이버마다 자기 번들의 libnccl을 쓰며, 기존 번들 42개 파일 md5가 두 노드에서 그대로 `[측정]` | [deploy_check.txt](deploy_check.txt) |
| 2026-10-09 05:04:28–05:05:52 | pilot H0(메인 세션, `bash chain.sh results/20261009_pilot H0`, 04:51:22에 대기 시작, 다른 실험의 hold 뒤 05:03:57에 잠금, 05:04:28에 유휴 확인, hold rc 0, chain 끝 05:05:54). 14회, 채점 안 함. mlx5 새 줄 0, 명령 오류 줄(rain 2, sunny 0)과 rain 펌웨어 명령 실패 수(31) 전후 같음, `gin-harden-` iptables 규칙 0, 모든 시행 `left=0`, STOP 파일 없음, CUDA 메모리 오류 줄 없음 `[측정]` | `results/20261009_pilot/`(hold_H0.out, chain.out, 스냅숏, 빌드별 시행 파일. 원자료는 Release `data-20261009`의 pilot 자산, 14절) |
| 2026-10-09 | pilot 분석(`score.py`를 세션 스크래치의 사본에 계획 수 1로 돌림, 14회 모두 로그와 kv와 대조). 14회 모두 설정 확인 통과, 제외 0. 셀이 있던 예측 19개 모두 판정식 조건 1/1 `[측정]`. 셀별: shrink 셀 셋의 `r0rc=4`는 rank 1 kill로 장치 대기가 오류를 돌려준 때문이고(진행 195–199/400) shrink와 무관하다. `hd_shrink_b@hf` shrink 성공 17.3 ms, 넘김 줄 "raised for rank(s) 1", 새 통신기 1 rank, allreduce 확인 맞음 0.3 ms, 새 통신기 비동기 오류 없음, 부모는 shrink 뒤에도 `ncclRemoteError`, 새 통신기 해제 502.0 ms, abort 오류 없음. `@hfp` 같음(17.2 ms, WARN에 넘김 줄 없음). `@hd` shrink 0.0 ms에 `ncclRemoteError`. 스위치 끔 0.0 ms에 실패, 유지 줄 사유 `NCCL_GIN_SHRINK_HANDOFF=0`. devComm 먼저 없앰: 없애기 11.1 ms, shrink 성공 16.5 ms, 부모 비동기 오류가 사라짐(no error), allreduce 맞음. 죽음 판정 뒤 거절은 kill 1.54–1.64 ms 뒤(shrink 셀 다섯과 `f4_b`, n=6). GPU 가득 참: `hf_hog_f1_b`, `hf_hogslack_f1_b`(gin-harden 순서)는 41/120에서 거절, `hf_hogpre_f1_b`, `hf_hogpreslack_f1_b`(호출을 앞당김)는 120/120 투명(값은 3절 머리). `hf_hog_f1_b`에서 rank 0 감시가 "fault records are queued and the recovery helper is not running"으로 드러냈고 유지 줄 사유가 "a GIN error was raised without a peer". 4 KiB 지연 p50: `hfp`, `hdp`, `hd` 모두 10.69 µs(n=1씩) `[측정]` | 세션 스크래치 `hf_work/pilot/`(사본, `SCORE.md`, `trials_scored.csv`) |
| 2026-10-09 | pilot 뒤 변경(태그 전). 예측: S3 상한 5 000 ms → 500 ms(pilot 16.5–17.3 ms). 다른 판정식, 셀, 반복 수, 제외 기준은 그대로. 열 설명: `hog_first_start_rel_ms`, `hog_last_start_rel_ms`는 노드마다 일정한 시계 차(rain 3 358.6–3 358.7 ms, sunny 3 672.6 ms, 블록이 바로 시작한 셀 n=2씩)를 품으므로 판정에 쓰지 않는다고 적음. 그 차를 빼면 gin-harden 순서 셀의 첫 블록은 GIN 커널 시작 2 063.6–2 092.5 ms 뒤에 시작했고 각 rank의 GIN 커널 시간(2 064.0–2 093.6 ms)과 1.3 ms 안에서 맞는다(n=4 rank-시행) `[측정, 추론]`. 실행 스크립트, 라이브러리, 드라이버, 번들은 그대로. 확정한 `predictions.csv` sha256 `04ac4a66cb4c2ea64bafb9a412d49f0dbd3fff5d26c36fafeecb361ded88799a`(24줄) | [predictions.csv](predictions.csv), [rows_hf.py](rows_hf.py), [score.py](score.py) |
| 2026-10-09 05:12:42 | 사전 등록 | [PREREG.txt](PREREG.txt), 태그 `prereg/gin-handoff-v1` |
| 2026-10-09 05:12:50 | 본 실행 시작(메인 세션, `bash chain.sh results/20261009 H1 H2 H3 H4`). hold마다 다른 실험의 hold와 번갈아 잠금을 기다림 | `results/20261009/chain.out` |
| 2026-10-09 05:21:09–05:24:28 | H1(잠금 05:20:38, 유휴 확인 뒤 시작, 3분 19초, rc 0): shrink 셀 30회(`hd_shrink_b` `hf` 10, `hd` 5, `hfp` 5, `hf_shrinkoff_b` 5, `hf_shrinkdc_b` 5) `[측정]` | `hold_H1.out`, `cluster_run.log`(꼬리표 `ghf-H1`) |
| 2026-10-09 05:42:03–05:45:09 | H2(잠금 05:41:32, 3분 6초, rc 0): GPU 가득 참 2 × 2 20회. `hf_hogpre_f1_b` n1은 rank 0의 랑데부 포트 bind 실패(`bind: Address already in use`, `r0rc=1`)로 rank 1이 자기 45 s 감시까지 기다림 `[측정]` | `hold_H2.out`, `ghf-H2` |
| 2026-10-09 05:53:37–05:57:04 | H3(잠금 05:53:06, 3분 27초, rc 0): 회귀 35회 `[측정]` | `hold_H3.out`, `ghf-H3` |
| 2026-10-09 06:08:57–06:10:43 | H4(잠금 06:08:26, 1분 46초, rc 0): 지연 30실행 `[측정]`. H3 뒤 스냅숏(05:57:03)과 H4 앞 스냅숏(06:08:57) 사이, 어느 hold 밖에서 sunny에 mlx5 줄 하나(`mlx5_fw_tracer_handle_traces ... FWTracer: Events were lost`)가 생김. 명령 오류 줄이 아니고 명령 오류 수는 그대로 `[측정]` | `hold_H4.out`, `ghf-H4`, `mlx5_*` |
| 2026-10-09 06:17:49–06:17:58 | 채우기 hold(`fill:hf:hf_hogpre_f1_b@hf:1:6`, 06:11:00에 대기 시작, 잠금 06:17:18, 9 s, rc 0): bind 실패 시행(8절 제외)을 다음 번호 n6으로 채움. 계획 5에 채움 1(20%), 50% 상한 안 `[측정]` | `hold_fill.out`, `ghf-fill` |
| 2026-10-09 | 본 실행 전체: hold 다섯 모두 rc 0, STOP 파일 없음. hold 안 시간 합 11분 47초(추정 약 13분). 모든 hold 앞뒤로 mlx5 새 줄 0, 명령 오류 줄 rain 2와 sunny 0 그대로, rain 펌웨어 명령 실패 31 그대로, `gin-harden-` iptables 규칙 0, 모든 시행 `left=0`, 종료 코드 139나 illegal address 없음 `[측정]` | 위 hold 출력, [qa_recount.md](results/20261009/qa_recount.md) 3절 |
| 2026-10-09 | 채점(메인 세션, `python3 score.py results/20261009`): 시행 116개(셀 86, 지연 30), 판정 115, 제외 1(bind 실패). 예측 24개 모두 맞음 `[측정]` | [SCORE.md](results/20261009/SCORE.md), [trials_scored.csv](results/20261009/trials_scored.csv) |
| 2026-10-09 | 독립 재계산(다른 에이전트, `score.py`, `rows_hf.py`, `SCORE.md`를 보지 않고 원자료에서 열을 다시 뽑고 자기 판정식 평가기로 셈): 맞음 24, 틀림 0, 자료 부족 0. 무결성(태그 커밋, `predictions.csv` sha256 세 곳 같음, 고정 절과 스크립트가 태그와 같음), 제외와 채움 확인, hold 출력 116줄이 시행 파일과 모두 맞음. 지연 p50을 원시 지연(실행마다 3000개)에서 다시 계산해 kv와 같음. 문서와 다른 점 셋(시계 차가 변함, GPU 가득 참 셀의 거절 사유 문구, 이 문서에 본 실행 기록이 아직 없었음)과 관찰 둘(FWTracer 줄, "cannot set the device error state" 줄)은 13절 `[측정]` | [qa/recount.py](qa/recount.py), [qa_recount.md](results/20261009/qa_recount.md) |
| 2026-10-09 | 본 실행 뒤 코드 리뷰(다른 에이전트, 읽기만): 막는 것과 높음 없음, shrink 변경은 주장한 범위에서 안전. 중간 둘(M1 "올린 상대"와 "원인 상대"의 차이, M2 GIN 상태 없는 아이만 시험), 낮음 여덟(L1 포트 범위, L2 자동화 안 된 8절 규칙 셋, L3 S6과 S8의 전제가 판정식에 없음, L4 복사 확인의 시간 해상도, L5 시계 차의 변화, L6 세 호출 묶음, L7 revoke 문구, L8 채움 시행의 시각). 측정 결과를 바꾸는 것은 없음 `[소스, 측정]` | [qa/code_review.md](qa/code_review.md) |
| 2026-10-09 | 나도 채점기 출력(`trials_scored.csv`)에서 핵심 수치를 따로 셈: shrink 시간, devComm 없애기 시간, kill 뒤 거절(n=40), 받기만 하는 rank, 원격 접근 오류의 rank 1 abort, 2 × 2의 블록 수와 복사 수와 간격, 지연 p50. 독립 재계산의 값과 모두 같음 `[측정]` | [trials_scored.csv](results/20261009/trials_scored.csv) |
| 2026-10-09 06:23:50 | Release `data-20261009`(메인 세션): 본 실행 자산(파일 712개, 0.37 MB)과 pilot 자산(파일 90개, 0.05 MB)을 내려받아 확인. `sha256sum -c` 통과, 주소를 바꾼 뒤 원본과 같고 실제 주소 접두가 없음 `[측정]` | 14절 |
| 2026-10-09 | 마감: 상태 `COMPLETE`, 13–19절, 폴더 [README.md](README.md). 고정 절(2, 3, 7, 8절)은 고치지 않고 정정은 13절에 둠. 클러스터 명령은 이 마감에서 돌리지 않음 | |

## 13. 사전 등록 이후 변경

> 기존 문장을 고치지 않고 여기에 덧붙인다. 변경이 많으면 `DEVIATIONS.md`에 두고 링크한다.

| 날짜 | 무엇을 | 이유 | 영향 범위 | 커밋 |
|---|---|---|---|---|
| 2026-10-09 | `hf_hogpre_f1_b@hf` n1 제외, n6으로 채움(채우기 hold, 06:17:49–06:17:58). 다른 시행보다 32분 늦게, 섞지 않고 혼자 돌았다(리뷰 L8) | 랑데부 포트 bind 실패(8절 제외 규칙 그대로. 계획 변경 아님) | 그 셀 키 하나. n6의 값은 n2–n5와 같다(191/192, 287/288 블록, 복사 8/8이 0.034–0.057 ms, 투명) `[측정]` | `1ca85fdc` |
| 2026-10-09 | 정정(3.1절, 고정): `hog_first_start_rel_ms`, `hog_last_start_rel_ms`의 노드별 시계 차는 일정하지 않다. 블록이 바로 시작한 셀에서 pilot(05:05) rain 3 358.6–3 358.7 ms, sunny 3 672.6 ms; H2(05:42–05:45, 9 rank-시행씩) rain 3 361.8–3 362.2 ms, sunny 3 692.7–3 693.5 ms; 채우기(06:17) rain 3 372.8 ms, sunny 3 699.2 ms. H2 안에서 rain은 시행마다 약 0.1 ms씩 늘었다(리뷰 L5, 재계산 6절 2번) `[측정]`. 기준이 `CLOCK_REALTIME`이라 NTP 보정을 받는 것으로 본다 `[추론]` | 독립 재계산과 리뷰가 찾음 | 판정식은 이 열을 쓰지 않는다. 블록 시작을 GIN 커널 끝과 비교할 때는 같은 hold의 셀에서 잰 차를 쓰거나 `hog_start_spread_ms`를 쓴다 | `1ca85fdc` |
| 2026-10-09 | 정정(3절 머리, 고정): GPU 가득 참 pilot을 "복구는 복사 시간 초과로 거절됐다"고 적었다. 사건의 순서는 맞다: 복사 시간 초과 줄("...; the round declines")이 먼저 나오고 rank 0의 거절 줄이 1.24–1.30 ms 뒤에 온다(본 실행 n=10). 그러나 거절 줄에 적힌 사유는 "the watchdog surfaced a fault earlier"다(pilot과 본 실행 10/10). 감시는 그보다 먼저(훅 11.8–461.9 ms 뒤) 상대 없이 오류를 드러냈다 `[측정]` | 독립 재계산 6절 3번 | 판정 영향 없음: G1은 복사 시간 초과 줄과 복구 없음만 본다 | `1ca85fdc` |
| 2026-10-09 | 덧붙임(관찰): gin-harden 순서의 GPU 가득 참 셀 10회 모두 적어도 한 rank에 "GIN/TS: cannot set the device error state"가 나오고, 늦은 복사가 끝난 뒤 "the gates to declined rank N failed after the late copy"가 나온다(rank 0의 `hf_hog_f1_b` n2, n5는 늦은 복사가 거절 0.008–0.009 ms 뒤 끝나 앞 줄이 없음). 거절의 장치 오류 상태 쓰기가 복사라서 막혔다가 나중에 다시 쓰인 것이다 `[측정, 소스]` | 독립 재계산 6절 5번 | 판정 영향 없음. 9절 1번 (c)의 "막힌 복사는 helper 점검이 다시 쓴다"가 실제로 일어났다 | `1ca85fdc` |
| 2026-10-09 | 정정(4절): revoke 뒤의 중단 shrink에도 넘김 규칙이 걸린다(리뷰 L7). 4절에 그 문장을 덧붙였다 | 코드와 문서가 다름 | revoke 셀이 없어 측정 영향 없음 | `1ca85fdc` |
| 2026-10-09 | 해석의 범위(2절 H1, H2, 고정): (1) 넘김 규칙은 오류가 "누구를 상대로 올려졌는가"를 보지 원인을 보지 않는다. 거절은 원인이 자기 rank에 있어도(커밋 실패, 펌웨어 단계, 라운드 안 복사 시간 초과 등) 그 상대를 적는다. 2 rank에서는 상대가 하나뿐이라 결과에 영향이 없다(리뷰 M1). (2) 아이 통신기의 격리는 GIN 상태가 없는 아이(devComm을 만들지 않음, 1-rank allreduce는 로컬 복사)에서만 쟀다(리뷰 M2). (3) H2는 "할당과 커널 적재"라고 적었지만 2 × 2가 가른 것은 세 호출(점유율 질의로 부르는 지연 적재, `cudaMalloc`, 스트림 생성)의 묶음이다. 어느 하나를 원인으로 말하지 않는다(리뷰 L6) | 리뷰 M1, M2, L6 | 결론과 README의 문장을 이 범위로 썼다(17절) | `1ca85fdc` |
| 2026-10-09 | 덧붙임(판정식): S6과 S8의 판정식에는 "shrink 전에 부모에 오류가 있었다"는 전제가 없다(리뷰 L3). 데이터에서는 전제가 섰다: S6 셀 5/5 `ho_async_seen=1`이고 shrink 뒤 부모 오류가 `ncclRemoteError`, S8 셀 5/5 `ho_async_seen=1`이고 없애기 뒤 부모 오류가 "no error" `[측정]`. G2의 "GIN 커널이 끝난 뒤 모두 끝난다"는 "200 ms 안에는 하나도 안 끝나고 실행 끝에는 모두 끝났다"로만 뒷받침된다(확인 창 뒤의 완료 시각을 남기지 않음, 리뷰 L4) | 리뷰 L3, L4 | 판정 그대로 | `1ca85fdc` |
| 2026-10-09 | 덧붙임(8절 실행): 8절의 규칙 셋("`left > 0`이 두 시행 연속이면 멈춤", "설정 확인 실패는 블록을 멈춤", "채움이 계획의 50%를 넘으면 자료 부족")은 스크립트가 자동으로 하지 않는다(리뷰 L2). 본 실행에서 셋 다 해당하지 않았다: `left=0` 116/116, 설정 확인 실패 0, 채움 1/5 `[측정]` | 리뷰 L2 | 영향 없음 | `1ca85fdc` |

## 14. 원자료와 결과표

| 무엇 | 경로 또는 Release 자산 | n |
|---|---|--:|
| 채점표(예측별 판정, 놓친 시행, 셀별 제외) | [results/20261009/SCORE.md](results/20261009/SCORE.md) | 예측 24 |
| 시행별 값(채점 상태 포함) | [results/20261009/trials_scored.csv](results/20261009/trials_scored.csv) | 116(판정 115) |
| 독립 재계산 | [results/20261009/qa_recount.md](results/20261009/qa_recount.md), 스크립트 [qa/recount.py](qa/recount.py) | 116 |
| 본 실행 뒤 코드 리뷰 | [qa/code_review.md](qa/code_review.md) | |
| 본 실행 원자료(빌드별 시행 로그와 kv, hold 출력, 스냅숏) | Release `data-20261009`, `harness__gpu-initiated__gin_recovery__handoff__results__20261009.tar.xz`(파일 712개, 0.37 MB, sha256 앞 12자리 `9a7fa309c670`) | 116 |
| pilot 원자료(채점 안 함) | Release `data-20261009`, `harness__gpu-initiated__gin_recovery__handoff__results__20261009_pilot.tar.xz`(파일 90개, 0.05 MB, sha256 앞 12자리 `688ff55d71f0`) | 14 |
| 배포 확인 | [deploy_check.txt](deploy_check.txt) | |
| 사전 등록 | [predictions.csv](predictions.csv), [PREREG.txt](PREREG.txt), 태그 `prereg/gin-handoff-v1`(`c9efc7b9`) | 24 |

빌드별 중간 표(`trials_hf.csv` 등)는 `trials_scored.csv`에 모두 들어 있어 커밋하지 않았다. Release 자산은 메인 세션이 06:23:50에 내려받아
확인했다(12절).

## 15. 결과 요약

판정: **예측 24개 모두 맞음**(판정 시행 115, 제외 1). 채점 [SCORE.md](results/20261009/SCORE.md), 독립 재계산도 24/24
([qa_recount.md](results/20261009/qa_recount.md)) `[측정]`. 아래 범위는 따로 적지 않으면 그 셀 키의 판정 시행 전체에 걸친 범위다.

**shrink 넘기기**(rank 0. 상대 rank 1 kill 뒤 주 대기가 끝난 다음 `ncclCommShrink(comm, {1}, NCCL_SHRINK_ABORT)`) `[측정]`

| 조건 | 셀 키 | n | shrink | 걸린 시간 | 새 통신기(1 rank)의 allreduce | shrink 뒤 부모의 비동기 오류 | 예측 |
|---|---|--:|---|---|---|---|---|
| 이 실험 라이브러리, 연구 빌드 | `hd_shrink_b@hf` | 10 | 성공 10/10. 넘김 줄이 rank 1만 적음 10/10 | 17.0–17.3 ms | 맞음 10/10(확인 0.3 ms), 새 통신기 비동기 오류 없음 10/10 | `ncclRemoteError` 10/10 | S1–S3 맞음 |
| 이 실험 라이브러리, 운영 빌드 | `hd_shrink_b@hfp` | 5 | 성공 5/5. WARN에 넘김 줄 없음 | 16.9–17.3 ms | 맞음 5/5 | `ncclRemoteError` 5/5 | S6 맞음 |
| gin-harden 라이브러리(대조) | `hd_shrink_b@hd` | 5 | `ncclRemoteError` 5/5 | 0.0 ms | 통신기 없음 | 이 드라이버는 기록 안 함 | S4 맞음 |
| 스위치 끔(대조) | `hf_shrinkoff_b@hf` | 5 | `ncclRemoteError` 5/5. 유지 줄 사유 `NCCL_GIN_SHRINK_HANDOFF=0` | 0.0 ms | 통신기 없음 | `ncclRemoteError` 5/5 | S5 맞음 |
| 스위치 끔, devComm을 먼저 없앰(대조) | `hf_shrinkdc_b@hf` | 5 | 성공 5/5. 넘김, 유지 줄 없음 | 16.4–16.9 ms | 맞음 5/5 | 오류 없음 5/5(없애기 10.8–11.1 ms) | S8 맞음 |
| 살아 있는 rank 1을 빼는 shrink, 감시가 상대 없이 오류를 올린 뒤 | `hf_hog_f1_b@hf` | 5 | `ncclRemoteError` 5/5. 유지 줄 사유 "a GIN error was raised without a peer" | 0.0 ms | 통신기 없음 | `ncclRemoteError` 5/5 | S7 맞음 |

- 성공한 shrink를 셋 합치면 16.4–17.3 ms(n=20)다. 새 통신기는 언제나 1 rank였고 allreduce 결과는 20/20 맞았다. 새 통신기 해제는 502.0–502.9 ms
  (`@hf`, `@hfp`, n=15), devComm을 먼저 없앤 셀 503.1–503.2 ms(n=5)다.
- 죽음 판정 뒤 거절: kill 셀 키 7개를 합쳐 kill 뒤 1.51–1.86 ms(n=40), 원인은 모두 상대 소켓의 FIN이다.

**GPU 가득 참 2 × 2**(셀마다 n=5. rank 0은 rain 48 SM × 4 = 192블록, rank 1은 sunny 48 × 6 = 288블록. 장애는 GIN 커널 시작 583.1–1 147.2 ms 뒤로
20회 모두 GPU 채우기 3 s 창 안. 새 스트림 복사는 GPU 채우기를 띄운 20.0–20.1 ms 뒤) `[측정]`

| 두 커널 사이 호출, 격자 | 셀 키 | 확인 때 시작한 블록(r0 / r1) | 새 스트림 복사 8개 중 200 ms 안(r0 / r1) | 실행 끝 | 복구 | 예측 |
|---|---|---|---|---|---|---|
| gin-harden 순서, 가득 | `hf_hog_f1_b` | 0/192 / 0/288, 5/5 | 0 / 0, 5/5 | 블록 모두 시작(간격 0.0 ms), 복사 8/8 | rank 0 복사 시간 초과 뒤 거절 5/5, 투명 0/5 | G1, G2 맞음 |
| gin-harden 순서, 하나 작게 | `hf_hogslack_f1_b` | 0/191 / 0/287, 5/5 | 0 / 0, 5/5 | 같음 | 거절 5/5, 투명 0/5 | G3 맞음 |
| 없음, 가득 | `hf_hogpre_f1_b` | 191/192 / 287/288, 5/5 | 8 / 8, 5/5(가장 늦은 복사 0.033–0.080 ms) | 남은 블록 하나가 GIN 커널 끝에 시작(시작 간격 rain 1 816.4–1 816.6 ms, sunny 1 801.4–1 801.6 ms. GIN 커널 시간 1 816.9–1 817.1 ms, 1 801.9–1 802.4 ms) | 투명 5/5, 복사 시간 초과 0 | G4 맞음 |
| 없음, 하나 작게 | `hf_hogpreslack_f1_b` | 191/191 / 287/287, 5/5 | 8 / 8, 5/5(0.034–0.104 ms) | 간격 0.0 ms | 투명 5/5, 복사 시간 초과 0 | G5 맞음 |

- gin-harden 순서의 두 셀(n=10)에서 rank 0은 훅 11.8–461.9 ms 뒤 감시가 상대 없이 오류를 드러냈고("fault records are queued and the recovery helper is
  not running"), 훅 915.0–1 463.0 ms 뒤 복사 시간 초과 줄, 그 1.24–1.30 ms 뒤 거절 줄(사유 "the watchdog surfaced a fault earlier")을 남겼다.
  rank 1은 "the peer declined"로 거절했다(10/10) `[측정]`.
- 같은 hold의 시계 차를 빼면 그 두 셀에서 첫 블록은 GIN 커널이 끝난 순간에 시작했다(차이 −1.8–0.0 ms, rank-시행 20) `[측정, 추론]`.

**회귀** `[측정]`(n=5씩)
- 투명 5/5: `f1_b`, `f3_b`, `bidirf_sym_b`(R1). 통계 API: `f1_b`에서 두 rank가 라운드 1, 복구 1, rank 0 거절 0(5/5, R6). `f4_b`에서 죽음 1, 거절 1(5/5, R7).
- kill 거절: `f4_b` kill 뒤 1.58–1.67 ms, 운영 빌드 `hdp_kill_b@hfp` 1.51–1.60 ms, 모두 FIN, abort 오류 없음(R2, R5).
- 원격 접근 오류: rank 0 거절 5/5. rank 1 대기는 `ncclRemoteError`로 풀리고 신호 없이 성공한 대기 0, rank 1 abort 773.3–796.7 ms(R3).
- 받기만 하는 rank: 죽음 판정 5/5, kill 뒤 대기 해제 19.5–21.7 ms, 비동기 오류 1.9–2.2 ms, abort 오류 없음(R4).

**지연**(rank 0 p50, 실행마다 3000번, 실행 5의 중앙값) `[측정]`

| 크기 | 이 실험 운영 빌드 | gin-harden 운영 빌드 | gin-harden 연구 빌드 | 실행별 범위(세 빌드) | 예측 |
|---|--:|--:|--:|---|---|
| 4 KiB | 10.69 µs | 10.69 µs | 10.69 µs | 10.69–10.72 µs | P1, P3 맞음(차이 0.00) |
| 256 KiB | 38.91 µs | 38.88 µs | 38.88 µs | 38.88–38.91 µs | P2, P4 맞음(차이 0.03) |

원시 지연 90 000개가 모두 32 ns의 배수라 0.03 µs 차이는 타이머 한 눈금이다. p50은 원시 지연에서 다시 계산해도 kv와 같다(재계산).

## 16. QA와 재현성

- **채점.** 메인 세션이 `score.py`로 셈: 시행 116, 판정 115, 예측 24 맞음 `[측정]`.
- **독립 재계산.** 다른 에이전트가 `score.py`, `rows_hf.py`, `SCORE.md`, `trials_*.csv`를 읽지 않고 원시 로그와 kv에서 모든 열을 다시 뽑고, 자기
  판정식 평가기로 셌다([qa/recount.py](qa/recount.py), [qa_recount.md](results/20261009/qa_recount.md)).
  - 맞은 것: 판정 24/24, 제외 1과 채움, hold 출력 116줄과 시행 파일, 설정 확인 115/115, 멈춤 기준(새 mlx5 줄 0, 명령 오류와 펌웨어 실패 수 그대로,
    iptables 규칙 0, STOP 없음, 139 없음), 지연 p50(원시 3000개에서 다시 계산).
  - 무결성: 태그 `prereg/gin-handoff-v1`이 커밋 `c9efc7b9`, `predictions.csv` sha256이 작업 트리, 태그, `PREREG.txt` 세 곳에서 같음, 고정 절과
    `cells.sh`, `chain.sh`, 드라이버 소스가 태그와 같음(`hold.sh`와 실행기는 관리망 주소 필터가 넣는 자리만 다름). 본 실행의 첫 로그 05:21:11은 사전
    등록 05:12:42 뒤.
  - 다른 것: 13절에 옮긴 셋(시계 차, 거절 사유 문구, 이 문서의 본 실행 기록 부재)과 관찰 둘. 판정을 바꾸는 것은 없다.
- **코드 리뷰.** 설계 단계 리뷰(12절)와 본 실행 뒤 리뷰([qa/code_review.md](qa/code_review.md)). 본 실행 뒤 리뷰는 rain의 번들 md5가 5절과 같음을
  확인했다(sunny는 `deploy_check.txt`만 `[미확인]`). 찾은 것과 처리는 13, 18, 19절.
- **내 확인.** 채점기 출력에서 핵심 수치를 따로 세어 재계산과 같음을 확인했다(12절). 이것은 독립 확인이 아니다.
- **재현.** [gin_transparent_hf.diff](gin_transparent_hf.diff)(pristine NCCL v2.32.3-1 기준)로 만든다. `hfp`는 같은 소스에
  `-DNCCL_GIN_TS_PRODUCTION`. 빌드 절차는 [build_hf.sh](build_hf.sh), 배포는 [deploy_hf.sh](deploy_hf.sh)(md5 확인), 실행은 9절. 빌드 md5는 5절.

## 17. 결론

1. **GIN 오류 뒤 죽은 rank를 빼는 shrink가 응용을 바꾸지 않고 된다.** 순정 NCCL 2.32.3과 gin-harden 빌드는 GIN 오류가 난 통신기의 중단 shrink를 바로
   `ncclRemoteError`로 돌려준다(대조 5/5, 스위치 끔 5/5). 이 실험의 계층은 라이브러리가 그 GIN 오류를 올릴 때 누구를 상대로 올렸는지 적어 두고, 그
   상대가 모두 빠지면 오류를 넘어간다. 그래서 죽은 rank를 뺀 1-rank 통신기를 약 17 ms에 돌려줬고(연구 빌드 10/10, 운영 빌드 5/5), 그 allreduce는
   맞았으며, 새 통신기는 부모의 오류를 물려받지 않았다. 부모는 오류를 그대로 지녀 여전히 abort해야 한다. 상대를 적지 않은 오류(감시의 드러냄)가
   한 번이라도 있으면 순정 답을 지켰다(5/5) `[측정]`.
   - 한계: 규칙은 오류가 "누구를 상대로 올려졌는가"를 본다. 원인이 자기 rank에 있는 거절도 상대를 적으므로, 3 rank 이상에서는 원인이 남은 채
     넘어갈 수 있다. 2 rank라 "빼지 않은 rank" 거부 경로는 지나지 않았다. 아이 통신기는 GIN 문맥 없이만 썼다(13, 18절) `[추론, 소스]`.
   - 응용이 devComm을 먼저 없애면 순정 확인으로도 shrink가 된다(5/5). 그 길은 devComm의 모든 오류를 지우고 응용을 바꿔야 한다 `[측정, 추론]`.
2. **GPU가 가득 찬 동안 복구가 실패한 원인은 GPU가 가득 찬 것이 아니라, GIN 커널을 띄운 뒤 GPU 채우기 커널을 띄우기 전에 응용이 한 세 호출의 묶음이다.**
   묶음은 그 커널의 점유율 질의(지연 적재로 커널 코드를 올림), `cudaMalloc`, 스트림 생성이다. 묶음이 있으면 격자 크기와 상관없이 그 뒤의 GPU 명령
   (GPU 채우기 커널, helper의 복사, 새 스트림 8개의 복사)이 GIN 커널이 끝날 때까지 시작하지 않았고 복구는 2 s 복사 상한 뒤 거절로 끝났다(10/10).
   묶음을 GIN 커널 전으로 옮기면 GPU가 똑같이 가득 차도 새 스트림 복사는 0.11 ms 안에 끝나고 복구는 투명했다(10/10). 다 올라가지 못한 블록 하나가 1.8 s 동안
   남아도 복사와 복구를 막지 않았으므로, 하드웨어 작업 큐를 나누어 쓴다는 읽기는 맞지 않았다 `[측정]`. 셋 중 어느 호출이 원인인지는 가르지
   못했다. CUDA 문서의 암묵적 동기화(할당)와 지연 적재 경고에 맞는 동작이다 `[추론]`. 응용 쪽 대책은 GIN 커널이 복구 중 기다릴 수 있는 동안
   할당, 첫 커널 적재, 스트림 생성을 하지 않고 미리 해 두는 것이다 `[추론]`. 라이브러리는 이 경우를 고치지 않았다(9절 2번).
3. **기존 동작과 지연은 그대로다.** 회귀 7셀이 모두 예측대로였고(n=35), 운영 빌드의 지연은 gin-harden 빌드와 4 KiB에서 같고 256 KiB에서 타이머
   한 눈금(0.03 µs) 달랐다 `[측정]`.

## 18. 한계

- **2 rank, 노드마다 GPU 하나.** 상대가 하나라 넘김 규칙의 rank 옮기기는 항등식으로만 지났고, "빼지 않은 rank" 거부 경로는 소스로만 확인했다.
  살아남은 rank들의 판정이 엇갈리는 경우도 재지 않았다.
- **"올린 상대"와 "원인"(리뷰 M1).** 거절은 원인이 자기 rank에 있어도 그 상대를 적는다. 3 rank 이상에서는 원인이 남은 rank가 빠진 상대만 빼고
  shrink를 넘길 수 있다.
- **아이 통신기(리뷰 M2).** 아이는 devComm을 만들지 않았고 1-rank allreduce는 로컬 복사다. 넘김 뒤 아이가 자기 GIN 문맥을 여는 실제 쓰임은 재지
  않았다.
- **GPU 가득 참.** 한 테스트베드(Turing과 Ampere, CUDA 12.8, 드라이버 570)의 CUDA 동작이다. 세 호출 묶음만 갈랐고 하나씩은 가르지 않았다(리뷰
  L6). 멈춘 복사가 실행 끝에는 끝나 있었다는 것만 알고 끝난 시각은 남기지 않았다(리뷰 L4). 블록 시작의 절대 시각 열은 시계 차가 변해 같은 hold
  안에서만 쓸 수 있다(리뷰 L5). 라이브러리는 이 경우를 고치지 않아, 복구 중 응용이 그 호출을 하면 helper는 여전히 2 s 뒤 거절한다.
- **판정식.** S6, S8에는 부모 오류의 전제가 없다(데이터에서는 섰다, 리뷰 L3). 8절의 규칙 셋은 자동이 아니다(해당 없음, 리뷰 L2).
- **실행기.** 랑데부 포트를 rain의 임시 포트 범위(32768–60999) 안에서 골라 116회 중 1회가 bind에 실패했다(리뷰 L1). 채운 시행은 32분 늦게 혼자
  돌았다(리뷰 L8, 값은 같음).
- **빌드.** 연구 빌드에는 시험 스위치가 있다. 운영 빌드는 넘김 줄을 INFO로 남겨 `NCCL_DEBUG=WARN`에서는 보이지 않는다. 키 없는 올림 한 번이 이
  프로세스의 넘김을 끝까지 끈다(보수적, 리뷰 nit).

## 19. 다음 작업

- **원인 기준의 넘김 규칙(리뷰 M1).** 원인이 자기 rank에 있는 거절(커밋 실패, 펌웨어 단계, 라운드 안 복사 시간 초과, 계획 거부, 상한 넘김)은
  상대 없는 올림으로 적어, 넘김이 원인이 남은 shrink를 막게 한다. 3 rank 이상에서 "빼지 않은 rank" 거부 경로와 엇갈린 판정을 잰다.
- **자기 devComm을 여는 아이(리뷰 M2).** 넘김 뒤 아이 통신기에서 devComm을 만들고 GIN 커널을 돌려, 부모의 GIN 상태와 오류 기록이 섞이지 않는지 잰다.
- **랑데부 포트(리뷰 L1).** 임시 포트 범위 밖에서 고르거나, rank 0이 포트 0에 bind하고 실제 포트를 rank 1에 넘긴다.
- **CUDA 암묵적 동기화에 대한 라이브러리 쪽 완화.** 세 호출을 하나씩 갈라 원인을 좁힌다. 그다음 helper가 GPU 명령 없이 장치 상태에 닿는 길(쉬는 중
  점검의 두 칸을 장치가 호스트 매핑 단어에도 쓰기, NIC로 자기 GPU 메모리를 읽고 쓰기, gdrdrv가 있는 노드의 BAR1 매핑)과 그 원자성을 확인하고, 막힌
  복사를 감지하면 원인을 알리는 줄을 남긴다. 확인 창 뒤 복사의 완료 시각도 기록한다(리뷰 L4).
- gin-s2의 미해결 관측(돌고 있는 GIN 받는 커널 옆의 새 GIN 커널). 이 실험에서는 보통 커널이 GIN 받는 커널 옆에서 시작했다.

## 20. 참고자료

- `../harden/EXPERIMENT.md`(gin-harden, 기준 빌드 `hd`, pilot의 두 실패)
- [qa/code_review.md](qa/code_review.md), [results/20261009/qa_recount.md](results/20261009/qa_recount.md)(이 실험의 QA)
- CUDA C++ Programming Guide, lazy loading의 동시 실행 경고(커널 적재가 돌고 있는 커널을 기다릴 수 있음)
- `../TRANSPARENT_S2.md`(gin-s2, 돌고 있는 GIN 받는 커널 옆에서 시작하지 않은 커널)
- CUDA C++ Programming Guide, "Implicit Synchronization"(할당이 스트림 사이의 동시 실행을 막는 호출로 적힘)
- `../oneway/EXPERIMENT.md`(지연 경계)
- `../s2_close/EXPERIMENT.md` 3.2절(판정식 문법)
