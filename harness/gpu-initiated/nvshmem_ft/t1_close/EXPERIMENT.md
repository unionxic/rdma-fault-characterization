# NVSHMEM 투명 복구 마무리 (t1_close)

**목적:** NVSHMEM IBGDA 투명 복구의 남은 항목 가운데 하루 안에 닫을 수 있는 것을 고치고 사전 등록한 예측으로 잰다.
대상은 복구 시간 회귀, 응답 쪽 실행 수로 fetch를 다시 보내는 규칙, 셋째 리뷰에서 돌리지 못한 셀, 상대당 RC QP 4개, 회귀 재현이다.

| 항목 | 값 |
|---|---|
| 상태 | `RUNNING` |
| 담당자 | @unionxic |
| 작성일 | 2026-10-07 |
| 기준 브랜치와 커밋 | `exp/nvshmem-t1-close` @ `3dbf995e` (master) |
| 사전 등록 태그 | `prereg/nvshmem-t1-close-v1` (이 상태로 바꾼 커밋) |
| 마지막 갱신 | 2026-10-07 19:13, 본 실행 시작 |

표시: `[측정]` 원자료나 파일에서 확인, `[소스]` 코드나 문서에서 확인, `[추론]` 해석, `[미확인]` 확인 안 함.
장애와 셀의 기호(F1, N1 등)는 원자료를 찾는 키로만 괄호나 id 열에 둔다. 파일과 환경변수 이름의 T1은 그대로 둔다.

## 1. 배경과 연구 질문

- 투명 복구는 QP 오류를 라이브러리 안에서 고쳐 앱 커널이 오류를 보지 않게 한다. 설계와 결과는
  [../TRANSPARENT_T1.md](../TRANSPARENT_T1.md)에 있고 "진행 중이라 결과로 쓰지 않는다"로 남아 있다
  ([../README.md](../README.md)). 남은 항목은 PR #6 본문의 체크리스트와 같은 문서의 Limits 절이다 `[소스]`.
- 패치는 NVSHMEM devel `7bb2e99c` 위에 장애 주입 diff와 CPU 프록시 record 수정 knob diff를 얹은 전체 diff다
  (`../nvshmem_ibgda_transparent.diff` 머리말) `[소스]`. 이 실험도 이 기반에 머문다.
- 이 실험 전에 원자료에서 다시 확인한 사실:
  - 커밋된 diff는 scratch 소스 트리의 작업 트리와 바이트 단위로 같고, 그 빌드(이하 final3: transport `82737569`,
    host `3d630308`, 드라이버 `e2bb70be`)가 2026-10-01 14:56–15:36에 108회 돌았다 `[측정]`(`cluster_run.log`,
    Release `data-20261006`의 `20260930_t1` 묶음 안 `reg_final3`, `flap_final3`, `review5`). 이 108회는
    `../results/20260930_t1/trials_t1.csv`와 투명 복구 문서에 없다. 문서 표는 이전 빌드 final2(`c69d6cc4`)다.
  - final3 다시 세기 `[측정]`: 회귀 85회 중 투명 70, 거절 15(예측대로), 주소 끊김 15/15 투명, 꽉 찬 GPU 8/8 거절.
  - final3에서 복구 1회가 느려졌다. 로컬 QP 오류(F1) 복구 중앙값 4.64 ms [4.18–5.46](final2, n=20)에서
    7.35 ms [6.97–8.33](final3, n=20) `[측정]`. 준비 0.12→0.32, 커밋 0.82→1.34, 마무리 0.03→0.45 ms다.
    final3의 `t1_sync()`가 bounded 복사를 `cudaStreamQuery`와 `sleep_for(20 µs)`로 기다린다 `[소스]`.
    timer slack까지 더하면 복사 한 번이 약 70 µs라는 것이 단계별 증가와 맞는다 `[추론]`.
  - 꽉 찬 GPU(앱의 둘째 커널이 남은 SM을 모두 차지)에서 final3은 기록 0.33–1.17 s 뒤에 거절했다(8/8). final2는
    82.0–94.7 s 뒤였다(24/24) `[측정]`. 투명 복구는 두 빌드 모두 0회다.
  - 미완료 구간에 fetch AMO가 있으면 지금은 무조건 거절한다 `[소스]`(diff 4635–4696줄). 그런데 상대 QP 오류(F3) +
    fetch 10/10 거절에서 PE 1 카운터는 모두 "정확히 돌아온 fetch 수"와 같았다. 즉 거절된 fetch는 실행되지 않았다
    `[측정]`(review4). 무간격 로컬 QP 오류 + fetch 12회에서는 3회만 fetch가 실행돼 있었다 `[측정]`(`fetch_fixed`).
  - 셋째 리뷰의 셀 가운데 연결 32개의 꽉 찬 GPU, 받는 방향만 끊긴 소켓, 소켓 끊김 두 셀(final3), finalize 없는 종료는
    돌지 않았다 `[측정]`(로그에 hold 없음).
  - FT v2.2에서는 상대 QP 오류와 상대 kill을 다시 돌리지 않았다(`../README.md` 한계 절) `[소스]`.
- 질문:
  1. final3의 복구 시간 회귀는 bounded 복사의 대기 방식 때문인가. 바꾸면 final2 시간으로 돌아오는가.
  2. 응답 쪽이 실행한 요청 수로 fetch를 다시 보낼지 정하면, 다시 보낸 fetch는 한 번만 적용되는가. 거절은 정확히
     응답 쪽이 그 fetch를 실행한 경우에만 나는가.
  3. 셋째 리뷰 수정이 주장대로 동작하는가: 받는 방향만 끊긴 소켓의 재연결, finalize 없는 종료의 helper join,
     꽉 찬 GPU의 빠른 거절. 꽉 찬 GPU의 멈춤은 하드웨어 작업 큐 공유 때문인가.
  4. 상대당 RC QP 4개에서도 한 라운드로 투명한가.
  5. 바뀐 빌드가 회귀 결과와 지연 비용을 유지하는가. v2.2도 상대 QP 오류를 복구하고 상대 kill을 거절하는가.

## 2. 가설

| 가설 | 내용 | 틀렸다고 볼 관측 |
|---|---|---|
| 복구 시간 (H1) | 회귀의 원인은 bounded 복사를 sleep으로 기다리는 방식이다. 처음 200 µs를 쉬지 않고 확인하면 복구가 final2 시간대로 돌아온다 | 새 빌드의 로컬 QP 오류 복구 중앙값이 5.5 ms를 넘음, 또는 옛 대기 방식 knob에서 6.5 ms 미만 |
| fetch 규칙 (H2) | 응답 쪽이 실행하지 않은 fetch만 다시 보내면 한 번만 적용된다. 실행 여부를 모르는 fetch는 정확히 응답 쪽이 실행한 것이다 | 투명 시행에서 fetch 값이나 PE 1 카운터 불일치 1회, 또는 거절 시행에서 카운터가 실행 안 됨을 보임 1회, 또는 failed 1회 |
| 셋째 리뷰 수정 (H3) | 받는 방향만 끊겨도 재연결해 앱은 오류를 보지 않는다. finalize 없이 끝나도 두 PE가 5 s 안에 helper를 join한다. 꽉 찬 GPU는 3 s 안에 거절한다 | 각 셀에서 예측과 다른 결과 1회 |
| 작업 큐 (H4) | 꽉 찬 GPU의 복사 멈춤은 helper 스트림이 앱 커널과 하드웨어 작업 큐를 같이 써서 생긴다. 연결 32개면 복구된다 | 연결 32개에서도 복사 상한 거절이 10회 중 8회 이상 |
| 여러 QP (H5) | 상대당 RC QP 4개도 라운드 하나가 모두 다시 세워 투명하다 | failed나 거절 1회, 라운드 2개 이상, 또는 라운드의 QP 수가 4가 아님 |
| 회귀 없음 (H6) | 바뀐 빌드는 final2와 final3의 회귀 결과, 지연 비용 폭을 유지한다 | 재현 칸에서 예측과 다른 결과 1회, 또는 지연 차이가 폭 밖 |

## 3. 사전 예측 (측정 전에 작성)

예측 원문과 기계 채점 규칙은 [predictions.csv](predictions.csv)(새 칸 8, 재현 칸 13, 대조 4), 해시는 [PREREG.txt](PREREG.txt).

**공통 판정 규칙**
- 칸은 시행 태그의 TAG 부분으로 고른다(`<fault>_<mode>_ft<ft>_t1<t1>_<TAG>_t<k>`).
- 칸마다 "유효 시행"을 predictions.csv에 정의했다. void(PE 0이 커널을 시작하지 못함)와 장애가 걸리지 않은 시행은 유효가 아니다.
- 유효 시행이 새 칸 8회, 재현 칸과 대조 4회보다 적으면 그 칸은 "자료 부족"이다. 보충 시행은 하지 않는다.
- 판정은 "유효 시행 모두"에 대해 한다. 판정 기준을 채워도 예측 밖 결과가 하나라도 있으면 그 칸은 틀림이다.
- 필드는 `../scripts/t1/rows_t1.py`(trials.csv, rounds.csv)와 `../scripts/v2/rows_v2.py`의 출력이다.

**이번에 고정하는 새 필드와 로그 형식** (구현은 9절, 이름은 바꾸지 않는다)

| 어디 | 이름 | 뜻 |
|---|---|---|
| 라이브러리 RECOVERED 줄 | `nqps=`, `fetch_cr=`, `fetch_exec=`, `fetch_reposted=` | 라운드의 QP 수, 미완료 구간 [C, R)의 fetch WQE 수, 그중 응답 쪽이 실행한 구간 [C, U_exec)에 든 수, 다시 보낸 수(QP 합) |
| 라이브러리 DECLINE 줄 | `fetch_cr=`, `fetch_exec=`, `fetch_reposted=` | 같음. 계산 전에 거절하면 -1 |
| DECLINE 사유 | `executed by the responder` | 실행된 fetch 때문에 거절할 때의 사유 문구(부분 문자열) |
| 라이브러리 atexit | `[nvshmem-t1] PE<p> <mono_ms> ATEXIT helper=joined join_ms=<x>`, 멈추지 못하면 `helper=detached` | finalize 없는 종료에서 helper를 멈춘 결과 |
| 드라이버 | `T1EXIT rank <r> mono_ms=<t>` | `--no-finalize`로 main을 떠나는 시각 |
| rows_t1 trials.csv | `t1_fetch_cr0`, `t1_fetch_exec0`, `t1_fetch_reposted0` | PE 0의 첫 RECOVERED(시작 쪽) 또는 DECLINE 줄의 값. 그런 줄이 없으면 빈칸 |
| rows_t1 trials.csv | `exit_mono0/1`, `atexit_mono0/1`, `atexit_join_ms0/1`, `atexit_detached0/1` | 위 두 줄에서. detached면 1, joined면 0, 줄이 없으면 빈칸 |
| rows_t1 trials.csv | `nofin`, `rc_per_pe`, `rc_map`, `xenv`, `sock_dir`, `bundle` | `.meta`에서 |
| rows_t1 rounds.csv | `nqps`, `fetch_cr`, `fetch_exec`, `fetch_reposted` | RECOVERED 줄에서 |
| 시험용 knob | `NVSHMEM_IBGDA_FT_T1_TEST_SKIP`의 토큰 `spin`, `fetchrepost`, `fetchexec` | 옛 대기 방식, 옛 fetch 규칙, 실행된 fetch도 다시 보냄(음성 대조). 쉼표로 나눈 토큰을 정확히 비교한다 |
| 실행기 knob | `NOFIN=1`, `RC_PER_PE=<n>`, `RC_MAP=cta` 또는 `RC_MAP=none` | `--no-finalize`, `NVSHMEM_IBGDA_NUM_RC_PER_PE`, `NVSHMEM_IBGDA_RC_MAP_BY` |

**예측 요약**

| id | 셀 | 예측 | 판정 기준(요지) | 근거 |
|---|---|---|---|---|
| N1 | 로컬 QP 오류, 새 빌드 | 투명, 라운드 1개, 복구 빨라짐 | 모두 투명, 시작 쪽 복구 중앙값 ≤ 5.5 ms, 최대 ≤ 10 ms | final2 4.64 ms, final3 7.35 ms `[측정]` |
| C4 | 같은 셀, 옛 대기 방식 | 투명, 느림 | 모두 투명, 중앙값 ≥ 6.5 ms | final3 `[측정]` |
| N2 | 상대 QP 오류 + 매 반복 fetch | 투명, fetch 값과 카운터 정확, 실행 안 된 fetch를 다시 보냄 | 모두 투명, 라운드 1개, 실행된 fetch 0, 다시 보낸 fetch ≥ 1 | review4 카운터 10/10 `[측정]` |
| N3 | 연산 사이 로컬 QP 오류 + 매 반복 fetch | 투명 | 모두 투명, 실행된 fetch 0 | b3 묶음 8/8 미실행 `[측정]` |
| N4 | 진행 중 로컬 QP 오류 + 매 반복 fetch | 투명과 거절이 응답 쪽 실행 여부와 정확히 맞는다 | failed 0, 시행마다 (투명이고 실행 0이고 카운터 = fetch 수) 또는 (거절이고 실행 ≥ 1이고 카운터 = 정확한 수 + 1이고 사유 문구) | `fetch_fixed` 실행 3/12 `[측정]` |
| C2 | N2와 같음, 옛 규칙 | 거절, fetch 미실행 | 모두 거절, 사유 "cannot be re-posted", 카운터 = 정확한 수 | review4 `[측정]` |
| C3 | N4와 같음, 실행된 fetch도 다시 보냄 | 실행된 fetch가 있는 시행은 두 번 적용돼 failed | 그런 시행은 failed, 카운터 = fetch 수 + 1, 신호는 정확. 나머지는 투명. 그런 시행이 없으면 그 부분은 자료 없음 | `MODEL.md` 규칙 5 |
| N5 | 받는 방향만 8 s 끊김, 12 s에 로컬 QP 오류 | 투명, PE 0 재연결, PE 1 재수락 | 모두 투명, 소켓 잃음과 양쪽 복구 줄, 라운드 1개, 남은 iptables 규칙 0 | final3 소스(매 루프 수락) |
| N6 | 꽉 찬 GPU, 연결 32개 | 복구됨 | 투명 ≥ 8/10이면 맞음, 복사 상한 거절 ≥ 8/10이면 틀림, 그 밖은 판정 불가 | 단독 시험에서는 복사가 3–13 µs `[측정]` |
| N7 | finalize 없는 종료 | 투명, 두 PE 모두 5 s 안에 helper join | 모두 투명, 라운드 1개, 두 PE 모두 ATEXIT − T1EXIT ≤ 5000 ms, detached 0 | join 상한 copy_ms + 3 s `[소스]` |
| N8 | 상대당 RC QP 4개, CTA마다 QP | 투명, 라운드 1개가 QP 4개를 처리 | 모두 투명, 라운드 1개, 라운드마다 nqps = 4 | 상대당 8개까지 처리 `[소스]` |
| R1, R3–R8 | 장애 없음, 진행 중 로컬 QP 오류, 상대 QP 오류, 다섯 번 장애, 4 CTA, 앱의 heap 밖 쓰기, 상대 kill | final2, final3과 같음 | 칸마다 투명 또는 거절, 라운드 수, 거절 칸은 finalize ≤ 1000 ms | reg_final2, reg_final3 `[측정]` |
| R9, R10 | 소켓 양방향 끊김, 그 뒤 로컬 QP 오류 | 투명 | 모두 투명, 소켓 줄, 남은 규칙 0 | review4 `[측정]` |
| R11 | 꽉 찬 GPU, 기본 연결 | 빠른 거절 | 모두 거절, 기록→거절 ≤ 3000 ms, finalize ≤ 1000 ms | final3 0.33–1.17 s `[측정]` |
| R12 | 장애 없음 지연 8칸 | final2와 같은 비용 폭 | best-run p50 차이: 4 KiB 투명 켬 [1.0, 2.6], 4 KiB 끔 [0.2, 1.2], 256 KiB 켬 [0.8, 2.4] µs | 앞선 4세션 `[측정]` |
| R13, R14 | FT v2.2, 상대 QP 오류 / 상대 kill | 복구 / 거절 | rows_v2 필드로 복구와 검증, 거절과 정리 반환 | v2, v2.1 `[측정]` |
| C1 | 투명 스위치 끔(FT와 ring은 켬), 로컬 QP 오류 | 앱이 오류를 봄 | 모두 status_bad ≥ 1, 라운드 0, 투명 아님 | 스위치 끈 주소 끊김 6/6 `[측정]` |

## 4. 범위

- **포함:**
  - NVSHMEM devel `7bb2e99c` 기반 투명 복구 빌드 하나(final3 + 9절의 변경), 그 빌드의 시험용 knob.
  - FT v2.2 묶음 그대로(R13, R14).
  - 소켓 끊김은 이 실험이 띄운 PE 0의 T1 소켓 포트에만 거는 iptables 규칙.
- **제외:**
  - 공식 3.8.0으로 옮기기: 기반과 코드를 한꺼번에 바꾸면 회귀 원인을 가를 수 없다. 다음 단계로 따로 한다.
  - RoCE 주소 끊김: 공유 포트의 주소를 바꾸므로 사용자 승인 없이는 하지 않는다(설계의 해당 칸을 뺐다).
  - 꽉 찬 GPU에서의 근본 수정(BAR1 매핑): gdrcopy 커널 모듈이 필요하고 rain에 없다 `[측정]`(`/dev/gdrdrv` 없음).
    모듈 적재는 하지 않는다.
  - 기능을 끈 빌드의 지연 +0.5–0.7 µs, 받는 쪽 앱 대기 해제, DCI 트래픽, PE 3개 이상, 응답 쪽을 건드리지 않는 복구,
    커밋 지점 뒤 둘째 포기 핸드셰이크: 하루로 되지 않거나 의미 결정이 필요하다.
  - RDMA READ와 이미 성공 CQE가 있는 실행된 fetch 받기: 드라이버 모드가 없거나 재현 창이 좁다.
  - 투명 복구 문서와 표의 정리(final3 표기, 78 s와 93 s 충돌 등): 별도 커밋으로 나중에 한다.

## 5. 테스트베드와 버전

| 항목 | 값 | 확인 방법과 날짜 |
|---|---|---|
| 노드 | rain(PE 0, 시작 쪽, `mlx5_1`), sunny(PE 1, 받는 쪽, `mlx5_0`) | `[소스]` `../scripts/t1/env_t1.sh` |
| NIC와 펌웨어 | ConnectX-6, fw 20.43.4100, RoCE v2, IB 타임아웃 14, 재시도 7 | `[측정]` 2026-10-06 15:40(`../../nvshmem_rootcause/cq380/EXPERIMENT.md` 5절), 타임아웃은 `env_t1.sh` `[소스]` |
| 커널, OFED | rain 5.15.0-97-generic, OFED-internal-23.10-7.1.8. sunny는 `[미확인]` | `[측정]` 2026-10-07 18:50 rain |
| GPU와 드라이버, CUDA | rain Quadro RTX 5000(sm_75) 드라이버 570.211.01, PeerMappingOverride=1, CUDA 12.8(nvcc 12.8.93). sunny RTX A4000(sm_86), 드라이버 `[미확인]` | `[측정]` 2026-10-07 18:50 rain(`nvidia-smi`, `/proc/driver/nvidia/params`) |
| 라이브러리 빌드 | 이 실험 빌드: 빌드 전, md5는 배포 때 12절에 적는다 `[미확인]` | |
| 기준 빌드 final3 | `~/gi-bundle/nvshmem_t1`: transport `82737569`, host `3d630308`, `nvt1_drv` `e2bb70be`(바꾸지 않음) | `[측정]` 2026-10-07 md5sum |
| 지연 기준 v2.2 | `~/gi-bundle/nvshmem_t1/v22ref`: transport `6913dea6`, host `54a9d23a`, `nvt1v22_drv` `f1d4d304` | `[측정]` 2026-10-07 md5sum |
| FT v2.2 묶음 | `~/gi-bundle/nvshmem_ft2`: transport `6913dea6`, host `54a9d23a`, `nvft2_drv` `3d51a958` | `[측정]` 2026-10-07 md5sum |

## 6. 변수

- **독립변수:**
  - 빌드와 knob: 이 실험 빌드(새 대기, 새 fetch 규칙), 옛 대기(`spin`), 옛 fetch 규칙(`fetchrepost`), 실행된 fetch도
    다시 보냄(`fetchexec`), 투명 스위치 끔, FT v2.2 묶음.
  - 장애: 없음, 로컬 QP 오류(한 번, 다섯 번, 진행 중), 상대 QP 오류, 앱의 heap 밖 쓰기, 상대 kill, 소켓 끊김(양방향,
    받는 방향만).
  - 환경과 부하: 매 반복 fetch, 4 CTA × 8 스레드, 상대당 RC QP 1개와 4개, 남은 SM을 채우는 둘째 커널, 연결 수 8과 32,
    finalize 있음과 없음.
- **종속변수:** 시행 결과(투명, 거절, failed, void), 라운드 수와 단계별 시간, fetch 값과 PE 1 카운터, 거절 사유와
  기록→거절 시간, finalize 시간, 소켓 잃음과 복구 줄, 남은 iptables 규칙, atexit join 시각, 장애 없는 지연 p50.
- **통제변수:** IB 타임아웃 14, 재시도 7, `NVSHMEM_IBGDA_NUM_DCI=1`, 정적 heap(`NVSHMEM_DISABLE_CUDA_VMM=1`),
  GPU NIC 처리 방식, ring CQ, 시행마다 두 프로세스를 새로 띄움, hold 안에서 칸을 번갈아 실행(소켓과 꽉 찬 GPU hold 제외).

## 7. 실험 셀, 반복 수, 대조군

| id | 조건 | 반복 수 | 대조군 여부 | hold |
|---|---|--:|---|---|
| N1 | 로컬 QP 오류, 160 × 256 KiB, 15 ms 간격 | 10 | C4 | A |
| C4 | 같음, 옛 대기 방식 | 5 | 대조 | A |
| R1 | 장애 없음 | 5 | | A |
| R3 | 진행 중 로컬 QP 오류, 16000 × 4 KiB, 간격 없음 | 5 | | A |
| R4 | 상대 QP 오류, 420 × 256 KiB | 5 | | A |
| R5 | 로컬 QP 오류 다섯 번, 셋째는 커밋 안 | 5 | | A |
| R6 | 4 CTA × 8 스레드, RC QP 1개 | 5 | | A |
| R7 | 앱의 heap 밖 쓰기 | 5 | | A |
| R8 | 상대 kill | 5 | | A |
| C1 | 투명 스위치 끔, 로컬 QP 오류 | 5 | 대조 | A |
| N2 | 상대 QP 오류 + 매 반복 fetch | 10 | C2 | B |
| N3 | 연산 사이 로컬 QP 오류 + 매 반복 fetch | 10 | | B |
| N4 | 진행 중 로컬 QP 오류 + 매 반복 fetch | 10 | C3 | B |
| C2 | N2와 같음, 옛 fetch 규칙 | 5 | 대조 | B |
| C3 | N4와 같음, 실행된 fetch도 다시 보냄 | 5 | 대조(음성) | B |
| R12 | 장애 없는 지연 8칸(v2.2 끔, 이 빌드 끔, FT와 ring, 투명 켬 × 4 KiB와 256 KiB) | 칸마다 5 | | C |
| R13 | FT v2.2, 상대 QP 오류, 복구 | 5 | | C |
| R14 | FT v2.2, 상대 kill, 거절 | 5 | | C |
| R11 | 꽉 찬 GPU, 기본 연결 | 5 | N6의 비교 | D |
| N6 | 꽉 찬 GPU, 연결 32개 | 10 | R11 | D |
| N7 | finalize 없는 종료 | 10 | | D |
| N8 | 상대당 RC QP 4개 | 10 | R6 | D |
| R9 | 소켓 양방향 끊김, 장애 없음 | 5 | | E |
| R10 | 같은 끊김 뒤 로컬 QP 오류 | 5 | | E |
| N5 | 받는 방향만 끊김 뒤 로컬 QP 오류 | 10 | R10 | E |

모두 새 칸 80회(8칸), 재현 칸 60회(12칸)와 지연 40회(8칸 × 5), 대조 20회(4칸)다. 반복 수는 사전 등록 규칙(새 칸 10,
재현 칸 5, 대조 5)을 따랐다. 로컬 QP 오류의 재현 칸은 따로 두지 않고 새 빌드의 복구 시간 칸(N1, 10회)이 대신한다(그래서 id R2는 비어 있다).

spec 줄(`../scripts/t1/run_matrix_t1.sh` 형식, 모든 줄에 `BUNDLE`은 9절의 새 묶음):

```
# hold A (INTERLEAVE=1, gate_test)
10 F1 loop TAG=n1_round ITERS=160
5 F1 loop TAG=c4_sleep T1SKIP=spin ITERS=160
5 none loop TAG=r1_none ITERS=160
5 F1 loop TAG=r3_inflight ITERS=16000 BYTES=4096 GAP_US=0 FAULT_LO=70 FAULT_HI=250
5 F3 loop TAG=r4_f3 ITERS=420 SYM=160M KTIMEOUT=60 PROC_TIMEOUT=80
5 F1x5 loop TAG=r5_x5 ITERS=260
5 F1 mt TAG=r6_mt CTAS=4 THREADS=8 BURST=16 REPS=100 BYTES=1024 GAP_US=2000 FAULT_LO=70 FAULT_HI=300
5 F2A loop TAG=r7_f2a ITERS=100 SYM=40M BAD_AT=60 KTIMEOUT=8 PROC_TIMEOUT=20
5 F4 loop TAG=r8_f4 ITERS=400 SYM=160M KILL_MS=600 KTIMEOUT=15 PROC_TIMEOUT=30
5 F1 loop TAG=c1_t1off T1=0 ITERS=160 KTIMEOUT=10 PROC_TIMEOUT=25
# hold B (INTERLEAVE=1)
10 F3 loop TAG=n2_fetch_f3 FETCH=1 ITERS=1000 BYTES=4096 GAP_US=20000 KTIMEOUT=60 PROC_TIMEOUT=80
10 F1 loop TAG=n3_fetch_gap15 FETCH=1 ITERS=160 BYTES=262144 GAP_US=15000 KTIMEOUT=10 PROC_TIMEOUT=25
10 F1 loop TAG=n4_fetch_gap0 FETCH=1 ITERS=16000 BYTES=4096 GAP_US=0 FAULT_LO=70 FAULT_HI=250 KTIMEOUT=8 PROC_TIMEOUT=25
5 F3 loop TAG=c2_fetch_old T1SKIP=fetchrepost FETCH=1 ITERS=1000 BYTES=4096 GAP_US=20000 KTIMEOUT=30 PROC_TIMEOUT=50
5 F1 loop TAG=c3_fetch_exec T1SKIP=fetchexec FETCH=1 ITERS=16000 BYTES=4096 GAP_US=0 FAULT_LO=70 FAULT_HI=250 KTIMEOUT=8 PROC_TIMEOUT=25
# hold C (INTERLEAVE=1): ../scripts/t1/specs/lat.txt as is (R12), then the v2 runner (fault mode n VAR=...):
F3 timeout 5 RING=1 RECOVER=1 TAG=r13_v22f3
F4 timeout 5 RING=1 RECOVER=1 TAG=r14_v22f4
# hold D (INTERLEAVE=0)
5 F1 loop TAG=r11_fill FILL=1 ITERS=400 SYM=160M KTIMEOUT=15 PROC_TIMEOUT=40
10 F1 loop TAG=n6_fill32 FILL=1 XENV=CUDA_DEVICE_MAX_CONNECTIONS=32 ITERS=400 SYM=160M KTIMEOUT=15 PROC_TIMEOUT=40
10 F1 loop TAG=n7_atexit NOFIN=1 ITERS=160
10 F1 mt TAG=n8_mqp RC_PER_PE=4 RC_MAP=cta CTAS=4 THREADS=8 BURST=16 REPS=100 BYTES=1024 GAP_US=2000 FAULT_LO=70 FAULT_HI=300
# hold E (INTERLEAVE=0, iptables cleanup and count at the end)
5 SOCK loop TAG=r9_sock SOCK_S=8 SOCK_AT_MS=1500 ITERS=1000 BYTES=65536 GAP_US=20000 KTIMEOUT=60 PROC_TIMEOUT=80
5 SOCK1 loop TAG=r10_sock1 SOCK_S=8 SOCK_AT_MS=1500 FAULT_MS=12000 ITERS=1000 BYTES=65536 GAP_US=20000 KTIMEOUT=60 PROC_TIMEOUT=80
10 SOCK1 loop TAG=n5_sockA SOCK_DIR=in SOCK_S=8 SOCK_AT_MS=1500 FAULT_MS=12000 ITERS=1000 BYTES=65536 GAP_US=20000 KTIMEOUT=60 PROC_TIMEOUT=80
```

## 8. 제외 기준과 중단 기준

- **제외 기준:**
  - smoke 실행은 채점하지 않는다. 결과는 별도 폴더(`results/<날짜>_smoke/`)에 둔다.
  - void와 장애가 걸리지 않은 시행은 predictions.csv의 유효 정의대로 따로 센다. 보충하지 않는다. 유효 시행이 부족한
    칸은 "자료 부족"이다.
  - 빌드가 다른 시행은 무효다. 투명 복구 칸의 `md5_transport`, `md5_host`, `md5_bin`은 12절에 적은 이 실험 빌드와 같아야
    한다. 지연의 v2.2 칸은 `6913dea6`, `54a9d23a`, `f1d4d304`, v2 칸(R13, R14)은 `lib_rain` `6913dea6`, `host_rain`
    `54a9d23a`여야 한다. 하나라도 다르면 그 hold를 멈추고 원인을 적는다.
  - hold의 `STOP_AFTER_S` 때문에 돌지 못한 시행은 "실행 안 함"으로 센다.
- **중단 기준:**
  - 모든 클러스터 명령은 `harness/gpu-initiated/common/cluster_run.sh -w 10800` 안에서 돈다. 이 세션의 다른 실험 두 개가
    같은 잠금을 쓴다. 10800 s 안에 잠금이나 유휴 링크를 얻지 못하면 그 hold를 미루고 12절에 적는다. `prio-` 작업이
    기다리면 지금 hold가 끝난 뒤 양보한다.
  - 실제 link down이나 flap, 재부팅, 드라이버 재적재, 커널 모듈 적재(gdrdrv 포함), RoCE 주소 변경은 하지 않는다.
  - 프로세스는 이 실험이 띄운 것만 정확한 이름(`nvt1_drv`, `nvt1v22_drv`, `nvft2_drv`, `pkill -x`) 또는 PID로 끈다.
    다른 사용자의 작업(gds-kv, NVMe-oF, gdsio, mooncake, `prio-` 태그 작업)은 건드리지 않는다.
  - iptables 규칙은 이 실험 시행의 PE 0 T1 소켓 포트에만, 주석 `t1sock`으로 건다. 소켓 hold가 끝나면 그 규칙을 지우고
    `iptables -S`에서 `t1sock` 규칙 수를 센다. 모든 hold 뒤에도 같은 수를 센다. 0이 아니면 이 실험의 규칙만 지우고 소켓
    칸을 멈춘다.
  - hold 앞뒤로 rain dmesg 꼬리(`hold_generic.sh`)와 sunny dmesg 꼬리를 남긴다. 새 mlx5 명령 오류(`mlx5_core` 줄에 명령
    실패나 시간 초과)가 나오면 캠페인을 멈추고 적는다. rain `mlx5_1`은 2026-09-25부터 펌웨어 명령 슬롯 하나가 샌 상태다.
  - smoke에서 재현 칸(R)에 failed가 나오면 본 실행 전에 멈추고 상태를 `BLOCKED`로 둔다.
  - smoke에서 fetch 뒤의 WQE가 NOP나 DUMP가 아니면(로그 `ops_cr`) fetch 칸(N2, N3, N4, C2, C3)은 `BLOCKED`로 둔다.
    규칙이 전제한 WQE 모양이 아니기 때문이다.
  - 상대당 RC QP 4개 칸(N8)의 smoke가 실패하면 그 칸만 `BLOCKED`로 두고 같은 날 디버깅하지 않는다.
  - 시간이 모자라면 hold D나 E를 칸 단위로 통째로 빼고 "실행 안 함"으로 보고한다. 칸의 일부만 돌리지 않는다.

## 9. 실행 방법과 경로

- **배포/빌드:**
  - 소스: scratch 트리 `<scratch>/agent_nvt1/src`(작업 트리 = 커밋된 `../nvshmem_ibgda_transparent.diff`, `cmp`로 같음 `[측정]`).
    먼저 지금 작업 트리를 그 git에 "final3"으로 커밋하고 `git bundle`로 한 벌 남긴다. 파일을 지정해 add한다.
  - 코드 변경(`ibgda.cpp`, 장치 헤더 변경 없음):
    - `t1_sync()`: 처음 200 µs는 쉬지 않고 `cudaStreamQuery`, 그 뒤 `sleep_for(20 µs)`. 상한(`COPY_MS`)은 그대로. 토큰 `spin`이면 final3 방식.
    - `t1_prepare()`의 걷기: fetch AMO(FA, CS, masked, local 주소가 ibuf slot 0이 아님)는 거절하지 않고 `msg=1`, fetch로 표시.
      DUMP(0x23)는 local 연산으로 `msg=0`. READ는 지금처럼 거절. 토큰 `fetchrepost`면 옛 규칙.
    - `t1_prefix()`: `U_exec`를 구한 뒤 [C, U_exec)에 fetch가 있으면 사유 "... executed by the responder ..."로 거절.
      토큰 `fetchexec`면 대신 그 첫 fetch부터 다시 보낸다.
    - RECOVERED와 DECLINE 줄에 3절의 키와 `ops_cr`(첫 QP의 [C, R) opcode 앞 16개, smoke 확인용, 채점에 쓰지 않음)를 찍는다.
      RECOVERED 버퍼(`char per[512]`)는 넘치지 않게 고친다(QP 4–5개에서 `sizeof(per) - o`가 음수가 될 수 있음 `[소스]`).
    - atexit 훅에 ATEXIT 줄.
    - `nvshmem_t1.cu`: `--no-finalize`와 T1EXIT 줄. `env_t1.sh`, `run_trial_t1.sh`: `NOFIN`, `RC_PER_PE`, `RC_MAP`, `.meta` 키.
      `rows_t1.py`: 3절의 새 필드.
  - 빌드: `make -C <scratch>/agent_nvt1/build -j12 install`, `../scripts/t1/build_driver_t1.sh`(-Wall -Wextra).
  - diff: 이 빌드의 전체 diff는 `t1_close/nvshmem_ibgda_t1close.diff`로 따로 만든다(`make_diff_t1.sh`의 출력 경로만 바꿈,
    7bb2e99c 위 재적용 검증). 원래 diff는 final3 기준으로 그대로 둔다.
  - 배포: 새 디렉터리 `~/gi-bundle/nvshmem_t1close/{lib,bin}`과 `v22ref/{lib,bin}`(`~/gi-bundle/nvshmem_t1/v22ref`에서 복사)를
    rain과 sunny에 만든다. 대상 파일이 이미 있으면 배포 스크립트가 멈춘다. 기존 묶음 파일은 덮어쓰지 않는다. 두 노드 md5를
    비교해 12절에 적는다. gate 경합 시험은 기존 `~/gi-bundle/nvshmem_t1/bin/gate_race_test`를 읽기만 한다.
- **실행:** (`harness/gpu-initiated/nvshmem_ft`에서, 모두 `cluster_run.sh` 안)

  ```
  CR=../common/cluster_run.sh; B=$HOME/gi-bundle/nvshmem_t1close; R=t1_close/results/<date>
  $CR -w 10800 -t t1c-A -- timeout -s KILL 880 env BUNDLE=$B INTERLEAVE=1 STOP_AFTER_S=780 \
      bash scripts/t1/hold_generic.sh t1_close/specs/holdA.txt $R/A gate_test
  $CR -w 10800 -t t1c-B -- timeout -s KILL 880 env BUNDLE=$B INTERLEAVE=1 STOP_AFTER_S=780 \
      bash scripts/t1/hold_generic.sh t1_close/specs/holdB.txt $R/B
  $CR -w 10800 -t t1c-C -- timeout -s KILL 880 bash -c "BUNDLE=$B BUNDLE_V22=$B/v22ref INTERLEAVE=1 STOP_AFTER_S=400 \
      bash scripts/t1/hold_generic.sh scripts/t1/specs/lat.txt $R/C_lat; bash scripts/v2/run_matrix_v2.sh t1_close/specs/v22.txt $R/C_v22"
  $CR -w 10800 -t t1c-D -- timeout -s KILL 880 env BUNDLE=$B INTERLEAVE=0 STOP_AFTER_S=780 \
      bash scripts/t1/hold_generic.sh t1_close/specs/holdD.txt $R/D
  $CR -w 10800 -t t1c-E -- timeout -s KILL 880 bash -c "BUNDLE=$B INTERLEAVE=0 STOP_AFTER_S=780 \
      bash scripts/t1/hold_generic.sh t1_close/specs/holdE.txt $R/E; <hold_review4.sh와 같은 t1sock 정리와 개수>"
  ```

  spec 파일 내용은 7절의 줄 그대로다. smoke는 새 칸마다 1회와 장애 없음 1회를 같은 방식으로 `${R}_smoke`에 둔다.
- **예상 클러스터 시간:** smoke 약 4분, A 약 5–6분(final3 회귀 85회가 7 m 8 s `[측정]`), B 약 9–10분, C 약 4분(지연 40회가
  1 m 21 s `[측정]`), D 약 7–8분, E 약 9분(같은 소켓 셀 20회가 8 m 46 s `[측정]`). 실행만 약 40분이다. 잠금을 기다리는 시간은 따로다.
- **채점:** `t1_close/score.py`가 `rows_t1.py`와 `rows_v2.py`의 CSV로 predictions.csv의 규칙을 그대로 적용한다. 칸마다 판정,
  유효 n, 따로 센 시행, 놓친 시행을 `results/<date>/SCORE.md`에 쓴다. 다른 에이전트가 채점기를 보지 않고 원시 로그에서 다시 센다.
- **입력:** 위 spec, 새 묶음, FT v2.2 묶음.
- **출력:** `t1_close/results/<date>/`(시행 표, SCORE.md, 재계산). 원시 로그와 `.meta`는 Release에 올리고 `DATA.md`에 적는다.

## 10. 완료 조건과 QA 기준

- [ ] 모든 셀이 계획한 n만큼 실행됐다(제외와 실패를 따로 센 표 포함).
- [ ] 예측마다 판정(맞음/틀림/자료 없음)과 놓친 시행 목록이 있다.
- [ ] 핵심 수치를 원자료에서 다시 계산했다.
- [ ] smoke와 제외 시행이 결과에 섞이지 않았다.
- [ ] 원자료를 Release에 올리고 DATA.md에 적었다.
- [ ] 모든 시행의 빌드 md5가 12절의 배포 기록과 같다.
- [ ] 모든 hold 뒤 남은 `t1sock` iptables 규칙이 0이다.
- [ ] 이 빌드의 전체 diff가 7bb2e99c 위에 다시 적용되고 트리를 재현한다.

## 11. 작업 체크리스트

- [x] 질문, 가설, 셀 작성 (`DRAFT`)
- [x] 고정 절 완성, 상태 `PREREGISTERED`, 해시 기록을 커밋 하나로 만들고 그 커밋에 `prereg/` 태그
- [x] 계측과 실행기 구현, 빌드, 리뷰(리뷰는 자체 검토만, 12절)
- [x] smoke 실행(채점 제외)
- [ ] 본 실행 (`RUNNING`)
- [ ] 채점과 재계산 (`QA`)
- [ ] 결과 정리, 원자료 릴리스, PR
- [ ] 결론 확정 (`COMPLETE`)

## 12. 실행 기록 (시간순)

| 시각 | 무엇을 했나 | 결과와 근거(경로, 커밋, 실행 ID) |
|---|---|---|
| 2026-10-07 18:18–18:41 | 읽기 전용 범위 조사: 남은 항목 목록, final3 원자료 재계산(`rows_t1.py`), 공식 3.8.0과 비교 | 설계 메모와 재계산 CSV는 저장소 밖(scratchpad). 이 문서 1절에 옮긴 숫자는 원자료에서 다시 센 것 |
| 2026-10-07 18:50 | worktree에서 사전 등록 파일 작성. 빌드와 클러스터 실행 없음 | 이 문서, [predictions.csv](predictions.csv) |
| 2026-10-07 18:57:27 | 사전 등록 | [PREREG.txt](PREREG.txt), 태그 `prereg/nvshmem-t1-close-v1` |
| 2026-10-07 18:58–19:05 | scratch 소스 트리의 final3을 커밋하고 git bundle로 보관. 9절의 코드 변경, 빌드 b1(`build.sh`), 전체 diff(`make_diff.sh`, 7bb2e99c 위 재적용 검증), 새 묶음 `~/gi-bundle/nvshmem_t1close`에 배포(`deploy.sh`). 두 노드 md5 같음(14파일). 기존 묶음 파일 변경 0건(rain 207, sunny 259파일). 코드 리뷰는 자체 검토만 | [build.sh](build.sh), [make_diff.sh](make_diff.sh), [deploy.sh](deploy.sh). b1 md5: transport `31fa3a87`, host `3d630308`, `nvt1_drv` `d4b78b17` `[측정]` |
| 2026-10-07 19:05:35–19:06:59 | smoke 1(b1, 9회, 채점 제외). 셀마다 1회와 장애 없음 1회 | `results/20261007_smoke/smoke/`. fetch 세 시행의 [C, R) opcode가 `08-15-12-23`(쓰기, 신호 ADD, fetch, DUMP)라서 fetch 뒤 WQE는 DUMP다. fetch 칸 중단 규칙은 걸리지 않음 `[측정]`. finalize 없는 종료는 두 PE가 helper join 뒤 abort(rc 134/255). 연결 32개의 꽉 찬 GPU는 거절. 나머지는 예측대로. 두 노드 새 dmesg 0줄, 남은 iptables 규칙 0 |
| 2026-10-07 19:07–19:09:07 | 변경 1(DEVIATIONS 1): atexit 훅에서 FT 감시 스레드도 join. 빌드 b2를 새 묶음 `~/gi-bundle/nvshmem_t1close_b2`에 배포. 두 노드 md5 같음, 기존 묶음 파일 변경 0건(rain 225, sunny 277파일) | b2 md5: transport `b4b4115e`, host `3d630308`, `nvt1_drv` `278089a4`, v2.2 기준 `6913dea6`/`54a9d23a`/`f1d4d304` `[측정]`. diff `nvshmem_ibgda_t1close.diff` md5 `e9ff3ac0` |
| 2026-10-07 19:10:43–19:12:07 | smoke 2(b2, 9회, 채점 제외). 잠금은 다른 실험(GIN) hold 뒤 19:10:12에 얻음 | `results/20261007_smoke/b2/smoke/`. finalize 없는 종료: 두 PE rc 0, `ATEXIT helper=joined join_ms=2.2`. 연결 32개의 꽉 찬 GPU는 거절(복사 상한). 나머지는 smoke 1과 같음. 재현 칸(장애 없음) 투명. 중단 규칙 해당 없음. 새 dmesg 0줄, iptables 0 |
| 2026-10-07 19:13 | 본 실행 시작(`run_main.sh`, hold A부터 E까지 차례로, hold마다 `cluster_run.sh -w 10800 -t t1c-<hold>`). 상태 `RUNNING` | `results/20261007/run_main.out` |

## 13. 사전 등록 이후 변경

> 기존 문장을 고치지 않고 여기에 덧붙인다. 변경이 많으면 `DEVIATIONS.md`에 두고 링크한다.

| 날짜 | 무엇을 | 이유 | 영향 범위 | 커밋 |
|---|---|---|---|---|

변경은 [DEVIATIONS.md](DEVIATIONS.md)에 적었다. 요점: smoke 1의 finalize 없는 종료에서 FT 감시 스레드가 정리되지 않아
abort했고, atexit 훅이 그 스레드도 join하도록 고친 빌드 b2를 새 묶음에 배포했다(1). smoke는 두 번 했다(2). hold마다 두 노드
dmesg와 iptables를 기계로 확인하는 래퍼를 썼다(3). 예측과 판정 기준은 바꾸지 않았다.

## 14. 원자료와 결과표

| 무엇 | 경로 또는 Release 자산 | n |
|---|---|--:|

## 15. 결과 요약

> 예측별 판정과 핵심 수치. 수치마다 n과 근거 링크를 붙인다. 아직이면 `[미확인]`.

## 16. QA와 재현성

> 누가(사람 또는 에이전트) 무엇을 다시 셌고 무엇이 맞거나 달랐는지. 재현에 필요한 빌드와 커밋.

## 17. 결론

## 18. 한계

## 19. 다음 작업

## 20. 참고자료

- [../TRANSPARENT_T1.md](../TRANSPARENT_T1.md), [../V2.md](../V2.md), [../README.md](../README.md).
- [../../TRANSPARENT_RECOVERY_DESIGN.md](../../TRANSPARENT_RECOVERY_DESIGN.md) 10–12절.
- [../../../../MODEL.md](../../../../MODEL.md) 규칙 4, 5.
- `../results/20260930_t1/trials_t1.csv`, `rounds_t1.csv`(final2 이전 묶음), Release `data-20261006`의
  `harness__gpu-initiated__nvshmem_ft__results__20260930_t1.tar.xz`(final3 묶음 `reg_final3`, `flap_final3`, `review5` 포함).
