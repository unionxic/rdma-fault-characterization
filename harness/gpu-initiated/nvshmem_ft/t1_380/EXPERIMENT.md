# NVSHMEM 투명 복구를 공식 v3.8.0-0으로 옮기기 (t1_380)

**목적:** devel `7bb2e99c` 위에서 잰 NVSHMEM IBGDA 투명 복구(t1_close의 빌드 b2)를 공식 릴리스 v3.8.0-0에 그대로
옮겼을 때 같은 결과가 나오는지 사전 등록한 재현 칸으로 잰다.

| 항목 | 값 |
|---|---|
| 상태 | `COMPLETE` |
| 담당자 | @unionxic |
| 작성일 | 2026-10-08 |
| 기준 브랜치와 커밋 | `exp/nvshmem-t1-380` @ `90731cdb` (master) |
| 사전 등록 태그 | `prereg/nvshmem-t1-380-v1` (이 상태로 바꾼 커밋) |
| 마지막 갱신 | 2026-10-08 11:50, 독립 재계산, Release, PR, 상태 `COMPLETE` |

표시: `[측정]` 원자료나 파일에서 확인, `[소스]` 코드나 문서에서 확인, `[추론]` 해석, `[미확인]` 확인 안 함.
칸과 장애의 기호(R2, F1 등)는 원자료를 찾는 키로만 괄호나 id 열에 둔다. 파일과 환경변수 이름의 T1은 그대로 둔다.

## 1. 배경과 연구 질문

- 투명 복구는 QP 오류를 라이브러리 안에서 고쳐 앱 커널이 오류를 보지 않게 한다. 마지막 결과는
  [../t1_close/EXPERIMENT.md](../t1_close/EXPERIMENT.md)(PR #28)다. 25개 예측 중 23개가 맞았고, 그 빌드 b2의 전체 diff가
  [../t1_close/nvshmem_ibgda_t1close.diff](../t1_close/nvshmem_ibgda_t1close.diff)다 `[소스]`. 기반은 devel 스냅숏 `7bb2e99c`
  (라이브러리 이름 3.9.0)이고 공식 릴리스가 아니다.
- 공식 v3.8.0-0(`270759e5`)과 `7bb2e99c`를 비교한 결과(2026-10-07, 로컬 미러) `[측정]`:
  - 트리 전체로는 197개 파일이 다르다.
  - 패치가 고치는 IBGDA 소스는 include 줄만 다르다: `ibgda_device.cuh` 1줄, `ibgda.cpp` 2줄, `transport.h` 2줄,
    `barrier.cpp` include 묶음.
  - `nvshmem_common_ibgda.h`, `init.cu`는 같다. `mem_heap.cpp`(95줄)와 `nvshmem_internal.h`(54줄)는 내용이 다르다.
- t1_close diff를 pristine v3.8.0-0에 적용해 봤다(2026-10-08, scratchpad, 빌드 없음) `[측정]`:
  - 장애 주입 층과 CPU 프록시 record knob 층은 그대로 붙는다.
  - t1_close diff는 `barrier.cpp`의 hunk 하나(include 문맥)만 거부되고 나머지 8개 파일은 그대로 붙는다.
- devel 빌드와 공식 3.8.0 빌드는 cmake 선택이 같다(GDRCopy 켬, IBGDA와 IBRC 켬, release, 아키텍처 75와 86) `[측정]`(두 CMakeCache).
- NVIDIA는 CPU 프록시 doorbell record 버그(#117)를 내부에서 고쳤다며 2026-10-08에 이슈를 닫았다. 수정은 아직 공개되지 않아
  v3.8.0-0에는 버그가 그대로 있다 `[소스]`(`../../nvshmem_rootcause/README.md`).
  - 투명 복구는 GPU NIC 처리 방식에서만 켜진다(`t1_init`) `[소스]`. 그래서 이 버그는 투명 복구에 영향을 주지 않는다.
  - 이 실험은 두 줄 수정을 넣지 않는다. CPU 프록시에서 투명 복구가 꺼진 채로 남는지, 버그가 여전히 있는지는 따로 확인한다.
- 질문:
  1. 같은 투명 복구 코드를 공식 v3.8.0-0 위에 올리면, t1_close에서 잰 재현 칸의 결과(투명, 거절, fetch 규칙, finalize 없는 종료,
     QP 4개, 스위치 끈 대조)가 같은가.
  2. 진행 중 로컬 QP 오류의 복구 시간이 같은 hold의 devel 빌드와 같은가.
  3. 장애 없는 지연에서 공식 v3.8.0-0 그대로(수정 없음)와 devel의 v2.2 기준이 같은가. 옮긴 빌드의 비용이 devel 빌드와 같은가.
  4. CPU 프록시에서는 투명 복구가 꺼진 채로 남고, record 버그 때문에 오류 완료가 장치에 오지 않는가.

## 2. 가설

| 가설 | 내용 | 틀렸다고 볼 관측 |
|---|---|---|
| 결과 동일 (H1) | IBGDA 코드가 include 줄만 다르므로, 옮긴 빌드는 t1_close 재현 칸과 같은 결과를 낸다 | 재현 칸이나 대조에서 예측과 다른 결과 1회 |
| 복구 시간 동일 (H2) | 진행 중 로컬 QP 오류의 복구 중앙값이 같은 hold의 devel 빌드와 1.0 ms 안이다 | 두 중앙값 차이 > 1.0 ms |
| 지연 동일 (H3) | 공식 3.8.0 그대로와 devel v2.2 기준, 옮긴 빌드와 devel 빌드(FT 끔, 투명 켬)가 best-run p50로 각각 0.5 µs 안이다. 공식 기준 대비 비용은 t1_close 폭 안이다 | 어느 한 쌍이라도 0.5 µs 넘게 다름, 또는 비용이 폭 밖 |
| CPU 프록시 (H4) | CPU 프록시에서는 두 PE 모두 투명 복구를 거부하고, 로컬 QP 오류 뒤 오류 완료가 장치에 하나도 오지 않아 커널이 시간 제한에 걸린다 | 투명 복구가 켜짐, 복구 라운드, 장치 기록 1개 이상, 또는 커널이 제때 끝남 |

## 3. 사전 예측 (측정 전에 작성)

예측 원문과 기계 채점 규칙은 [predictions.csv](predictions.csv)(새 칸 5, 재현 칸 12, 대조 1), 해시는 [PREREG.txt](PREREG.txt).

**공통 판정 규칙**
- 칸은 시행 태그의 TAG 부분으로 고른다(`<fault>_<mode>_ft<ft>_t1<t1>_<TAG>_t<k>`).
- 유효 시행은 예측마다 predictions.csv에 정의했다. void와 장애가 걸리지 않은 시행, 빌드가 다른 시행은 따로 센다.
  유효 시행이 새 칸 8회, 재현 칸과 대조 4회보다 적으면 그 칸은 "자료 부족"이다. 보충 시행은 하지 않는다.
- 판정은 "유효 시행 모두"에 대해 한다. 판정 기준을 채워도 예측 밖 결과가 하나라도 있으면 그 칸은 틀림이다.
- 필드는 `../scripts/t1/rows_t1.py`의 출력이다(t1_close에서 고정한 필드 포함).
- **빌드 묶음(8절의 빌드 확인):**

  | 묶음 | 무엇 | md5(transport, host, 드라이버) |
  |---|---|---|
  | P | 옮긴 빌드, `~/gi-bundle/nvshmem_t1_380` | 배포 때 12절에 적는다 `[미확인]` |
  | D | devel 빌드 b2, `~/gi-bundle/nvshmem_t1close_b2` | `b4b4115ed0e5`, `3d63030802d5`, `278089a4eeda` `[측정]` |
  | V | devel v2.2 기준, `~/gi-bundle/nvshmem_t1close_b2/v22ref` | `6913dea69930`, `54a9d23acf0e`, `f1d4d304bd29` `[측정]` |
  | S | 공식 v3.8.0-0 그대로, `~/gi-bundle/nvshmem_t1_380/stock380` | `4aa4dda2a490`, `80eea986b645` `[측정]`, 드라이버는 빌드 때 12절에 적는다 |

**이번에 고정하는 새 필드** (구현은 9절, 이름은 바꾸지 않는다)

| 어디 | 이름 | 뜻 |
|---|---|---|
| rows_t1 trials.csv | `t1_enabled0`, `t1_enabled1` | 그 PE 로그에 `[nvshmem-t1] PE<p> ... enabled:` 줄이 있으면 1, 없으면 0 |
| rows_t1 trials.csv | `t1_refused0`, `t1_refused1` | 그 PE 로그에 `transparent mode stays off` 줄이 있으면 1, 없으면 0 |
| rows_t1 trials.csv | `ft_handler0`, `ft_handler1` | `[nvshmem-ft] PE<p> enabled:` 줄의 `handler=` 값(`GPU` 또는 `CPU-proxy`) |
| rows_t1 trials.csv | `handler` | `.meta`의 `handler=`(실행기 knob `HANDLER`, 기본 `auto`) |
| 실행기 | `BIN=nvt1st_drv`, `BUNDLE_STOCK` | 공식 3.8.0 그대로에 링크한 지연 기준 드라이버와 그 묶음(기본 `~/gi-bundle/nvshmem_t1_380/stock380`) |

**예측 요약**

| id | 셀 | 예측 | 판정 기준(요지) | 근거 |
|---|---|---|---|---|
| R1 | 장애 없음 | 투명, 라운드 0 | 모두 투명, 라운드 0 | t1_close 5/5 `[측정]` |
| R2 | 진행 중 로컬 QP 오류, 옮긴 빌드 | 투명, 라운드 1 | 모두 투명, 라운드 1 | t1_close 5/5 `[측정]` |
| R3 | 같은 셀, devel 빌드(같은 hold) | 투명, 라운드 1 | 모두 투명, 라운드 1 | t1_close 5/5 `[측정]` |
| N1 | 위 두 칸의 복구 시간 | 같다 | 두 칸의 시작 쪽 복구 중앙값 차이 ≤ 1.0 ms | t1_close 4.45 ms [4.28–4.56] `[측정]` |
| R4 | 상대 QP 오류 | 투명 | 모두 투명, 라운드 1 | t1_close 5/5 `[측정]` |
| R5 | 상대 QP 오류 + 매 반복 fetch | 투명, 실행 안 된 fetch를 다시 보냄 | 모두 투명, 실행된 fetch 0, 다시 보낸 fetch ≥ 1 | t1_close 10/10 `[측정]` |
| R6 | 연산 사이 로컬 QP 오류 + 매 반복 fetch | 투명 | 모두 투명, 실행된 fetch 0 | t1_close 10/10 `[측정]` |
| R7 | 진행 중 로컬 QP 오류 + 매 반복 fetch | 결과가 응답 쪽 실행 여부와 일치 | failed 0, 시행마다 (투명, 실행 0, 카운터 = fetch 수) 또는 (거절, 실행 ≥ 1, 카운터 = 정확한 수 + 1, 사유 문구) | t1_close 10/10 `[측정]` |
| R8 | 앱의 heap 밖 쓰기 | 거절, 정리 반환 | 모두 거절, finalize ≤ 1000 ms | t1_close 5/5 `[측정]` |
| R9 | 상대 kill | 거절, 정리 반환 | 모두 거절, finalize ≤ 1000 ms | t1_close 5/5 `[측정]` |
| R10 | finalize 없는 종료 | 투명, 5 s 안에 helper join | 두 PE 모두 ATEXIT − T1EXIT ≤ 5000 ms, detached 0 | t1_close 10/10 `[측정]` |
| R11 | 상대당 RC QP 4개 | 투명, 라운드 하나가 QP 4개 | 모두 투명, 라운드 1, 라운드마다 QP 4개 | t1_close 10/10 `[측정]` |
| C1 | 투명 스위치 끔 | 앱이 오류를 봄 | 모두 status_bad ≥ 1, 라운드 0, 투명 아님 | t1_close 5/5 `[측정]` |
| N2 | CPU 프록시, 투명 스위치 요청 | 두 PE 모두 투명 복구 거부 | 두 PE 거부 줄, 켜짐 줄 없음, 라운드 0, 투명 아님 | `t1_init` `[소스]` |
| N3 | 같은 시행 | 오류 완료가 장치에 오지 않음 | 장치 기록 0, PE 0 커널 시간 제한 | `MODEL.md` 규칙 1, cq380 `[측정]` |
| N4 | 장애 없는 지연, 공식 3.8.0 그대로 대 devel v2.2 기준 | 같다 | best-run p50 차이 ≤ 0.5 µs(4 KiB, 256 KiB) | 장치 헤더 include 1줄 차이 `[소스]` |
| N5 | 장애 없는 지연, 옮긴 빌드 대 devel 빌드(FT 끔, 투명 켬) | 같다 | 네 쌍 모두 best-run p50 차이 ≤ 0.5 µs | 같은 장치 소스 `[소스]` |
| R12 | 옮긴 빌드의 비용, 공식 3.8.0 그대로 대비 | t1_close 폭 안 | 4 KiB 켬 [1.0, 2.6], 4 KiB 끔 [0.2, 1.2], 256 KiB 켬 [0.8, 2.4] µs | t1_close R12 `[측정]` |

## 4. 범위

- **포함:**
  - 공식 v3.8.0-0 + 장애 주입 층 + CPU 프록시 record knob 층(기본 꺼짐) + t1_close 전체 diff. 거부된 `barrier.cpp` hunk는
    같은 내용을 3.8.0의 include 목록에 손으로 옮긴다. 이 빌드 하나(묶음 P)와 그 시험용 knob.
  - 같은 hold 안에서 비교하려고 devel 빌드 b2(묶음 D, V)를 그대로 읽어 쓴다. 공식 3.8.0 그대로(묶음 S)는
    `~/gi-bundle/nvshmem_off380/lib_stock`을 새 묶음에 복사해 지연 기준으로 쓴다.
- **제외:**
  - CPU 프록시 doorbell record 두 줄 수정(`../../nvshmem_rootcause/official380/fix.diff`): 투명 복구는 CPU 프록시에서 켜지지
    않아 영향이 없다. 넣지 않아야 CPU 프록시 칸(N2, N3)이 v3.8.0-0 그대로의 동작을 보인다. record knob 층은 t1_close diff가
    그 위에 쌓여 있어 넣지만 켜지 않는다.
  - 소켓 끊김 칸: 시행마다 약 25 s로 비싸고, 소켓 경로는 IBGDA 밖의 소스가 같아 이번 질문과 멀다.
  - 꽉 찬 GPU 칸: t1_close에서 원인 미상으로 남았고, 옮기기와 상관없다.
  - 주소 끊김, 실제 link down: 승인 없음, 금지.

## 5. 테스트베드와 버전

| 항목 | 값 | 확인 방법과 날짜 |
|---|---|---|
| 노드 | rain(PE 0, `mlx5_1`), sunny(PE 1, `mlx5_0`) | `[소스]` `../scripts/t1/env_t1.sh` |
| NIC와 펌웨어 | ConnectX-6, fw 20.43.4100, RoCE v2, IB 타임아웃 14, 재시도 7 | `[측정]` 2026-10-06(cq380 5절), 타임아웃은 `env_t1.sh` `[소스]` |
| 커널, OFED | rain 5.15.0-97-generic, OFED-internal-23.10-7.1.8. sunny `[미확인]` | `[측정]` 2026-10-07 rain |
| GPU와 드라이버, CUDA | rain Quadro RTX 5000 드라이버 570.211.01, PeerMappingOverride=1, CUDA 12.8. sunny RTX A4000, 드라이버 `[미확인]` | `[측정]` 2026-10-07 rain |
| NVSHMEM 공식 | v3.8.0-0, 태그 커밋 `270759e5`(2026-09-22) | `[측정]` 로컬 미러 `<scratch>/ibgda/nvshmem` |
| 옮긴 빌드(묶음 P) | 빌드 전 `[미확인]`. md5는 배포 때 12절에 적는다 | |
| 공식 그대로(묶음 S) | `~/gi-bundle/nvshmem_off380/lib_stock`: transport `4aa4dda2`, host `80eea986`(`libnvshmem_host.so.3.8.0`), device `f8306d94`, 설치 헤더는 `<scratch>/off380/install` | `[측정]` 2026-10-08 md5sum |
| devel 빌드(묶음 D, V) | b2와 그 v22ref(3절 표) | `[측정]` 2026-10-07 배포 기록 |

## 6. 변수

- **독립변수:** 기반(공식 v3.8.0-0, devel `7bb2e99c`), 빌드 설정(FT 끔, 투명 켬, 투명 스위치 끔, 공식 그대로), NIC 처리
  방식(GPU, CPU 프록시), 장애(없음, 로컬 QP 오류, 진행 중 로컬 QP 오류, 상대 QP 오류, 앱의 heap 밖 쓰기, 상대 kill), 부하(매 반복
  fetch, QP 4개), 종료 방식(finalize 있음, 없음).
- **종속변수:** 시행 결과(투명, 거절, failed, void), 라운드 수와 시간, fetch 값과 PE 1 카운터, 거절 사유, finalize 시간, atexit
  join 시각, 투명 복구 켜짐과 거부 줄, 장치 오류 기록 수, 커널 시간 제한, 장애 없는 지연 p50.
- **통제변수:** IB 타임아웃 14, 재시도 7, `NVSHMEM_IBGDA_NUM_DCI=1`, 정적 heap, 같은 cmake 선택, 시행마다 두 프로세스를 새로 띄움,
  hold 안에서 칸을 번갈아 실행, 같은 드라이버 소스(`../nvshmem_t1.cu`).

## 7. 실험 셀, 반복 수, 대조군

| id | 조건 | 반복 수 | 대조군 여부 | hold |
|---|---|--:|---|---|
| R1 | 장애 없음 | 5 | | A |
| R2 | 진행 중 로컬 QP 오류, 옮긴 빌드 | 10 | R3과 비교 | A |
| R3 | 같은 셀, devel 빌드 | 10 | 비교 기준 | A |
| R4 | 상대 QP 오류 | 5 | | A |
| R8 | 앱의 heap 밖 쓰기 | 5 | | A |
| R9 | 상대 kill | 5 | | A |
| R10 | finalize 없는 종료 | 5 | | A |
| R11 | 상대당 RC QP 4개 | 5 | | A |
| C1 | 투명 스위치 끔 | 5 | 대조 | A |
| R5 | 상대 QP 오류 + 매 반복 fetch | 5 | | B |
| R6 | 연산 사이 로컬 QP 오류 + 매 반복 fetch | 5 | | B |
| R7 | 진행 중 로컬 QP 오류 + 매 반복 fetch | 5 | | B |
| N2, N3 | CPU 프록시, 투명 스위치 요청, 로컬 QP 오류(같은 시행) | 10 | | B |
| N4, N5, R12 | 장애 없는 지연 12칸: 공식 그대로, 옮긴 빌드 FT 끔과 투명 켬, devel v2.2 기준, devel 빌드 FT 끔과 투명 켬 × 4 KiB와 256 KiB | 칸마다 10 | 공식 그대로가 기준 | C |

모두 200회다. 재현 칸 9개(5회씩)와 대조 1개(5회)가 50회다. 복구 시간 비교(N1)는 새 비교라서 두 칸(R2, R3)을 10회씩, 20회 돌린다.
CPU 프록시 칸은 10회다. 지연 12칸은 공식 3.8.0 그대로와의 비교가 처음이라 120회(칸마다 10회)다. 사전 등록 규칙(새 칸 10,
재현 칸 5, 대조 5)을 따랐다.

spec 줄(`../scripts/t1/run_matrix_t1.sh` 형식; `BUNDLE`의 기본은 묶음 P, devel 칸은 절대 경로로 묶음 D를 준다):

```
# hold A (INTERLEAVE=1, gate_test)
5 none loop TAG=r1_none ITERS=160
10 F1 loop TAG=p_inflight ITERS=16000 BYTES=4096 GAP_US=0 FAULT_LO=70 FAULT_HI=250
10 F1 loop TAG=d_inflight BUNDLE=/home/unionxic/gi-bundle/nvshmem_t1close_b2 ITERS=16000 BYTES=4096 GAP_US=0 FAULT_LO=70 FAULT_HI=250
5 F3 loop TAG=r4_f3 ITERS=420 SYM=160M KTIMEOUT=60 PROC_TIMEOUT=80
5 F2A loop TAG=r8_f2a ITERS=100 SYM=40M BAD_AT=60 KTIMEOUT=8 PROC_TIMEOUT=20
5 F4 loop TAG=r9_f4 ITERS=400 SYM=160M KILL_MS=600 KTIMEOUT=15 PROC_TIMEOUT=30
5 F1 loop TAG=r10_atexit NOFIN=1 ITERS=160
5 F1 mt TAG=r11_mqp RC_PER_PE=4 RC_MAP=cta CTAS=4 THREADS=8 BURST=16 REPS=100 BYTES=1024 GAP_US=2000 FAULT_LO=70 FAULT_HI=300
5 F1 loop TAG=c1_t1off T1=0 ITERS=160 KTIMEOUT=10 PROC_TIMEOUT=25
# hold B (INTERLEAVE=1)
5 F3 loop TAG=r5_fetch_f3 FETCH=1 ITERS=1000 BYTES=4096 GAP_US=20000 KTIMEOUT=60 PROC_TIMEOUT=80
5 F1 loop TAG=r6_fetch_gap15 FETCH=1 ITERS=160 BYTES=262144 GAP_US=15000 KTIMEOUT=10 PROC_TIMEOUT=25
5 F1 loop TAG=r7_fetch_gap0 FETCH=1 ITERS=16000 BYTES=4096 GAP_US=0 FAULT_LO=70 FAULT_HI=250 KTIMEOUT=8 PROC_TIMEOUT=25
10 F1 loop TAG=n2_cpuproxy HANDLER=cpu_host_memory ITERS=160 KTIMEOUT=10 PROC_TIMEOUT=25
# hold C (INTERLEAVE=1)
10 none lat TAG=lat4k_stock BIN=nvt1st_drv FT=0 ITERS=2000 REPS=5 BYTES=4096 KTIMEOUT=40 PROC_TIMEOUT=60
10 none lat TAG=lat4k_t1off FT=0 ITERS=2000 REPS=5 BYTES=4096 KTIMEOUT=40 PROC_TIMEOUT=60
10 none lat TAG=lat4k_t1on ITERS=2000 REPS=5 BYTES=4096 KTIMEOUT=40 PROC_TIMEOUT=60
10 none lat TAG=lat4k_dv22off BIN=nvt1v22_drv BUNDLE_V22=/home/unionxic/gi-bundle/nvshmem_t1close_b2/v22ref FT=0 ITERS=2000 REPS=5 BYTES=4096 KTIMEOUT=40 PROC_TIMEOUT=60
10 none lat TAG=lat4k_dt1off BUNDLE=/home/unionxic/gi-bundle/nvshmem_t1close_b2 FT=0 ITERS=2000 REPS=5 BYTES=4096 KTIMEOUT=40 PROC_TIMEOUT=60
10 none lat TAG=lat4k_dt1on BUNDLE=/home/unionxic/gi-bundle/nvshmem_t1close_b2 ITERS=2000 REPS=5 BYTES=4096 KTIMEOUT=40 PROC_TIMEOUT=60
10 none lat TAG=lat256k_stock BIN=nvt1st_drv FT=0 ITERS=2000 REPS=5 BYTES=262144 KTIMEOUT=40 PROC_TIMEOUT=60
10 none lat TAG=lat256k_t1off FT=0 ITERS=2000 REPS=5 BYTES=262144 KTIMEOUT=40 PROC_TIMEOUT=60
10 none lat TAG=lat256k_t1on ITERS=2000 REPS=5 BYTES=262144 KTIMEOUT=40 PROC_TIMEOUT=60
10 none lat TAG=lat256k_dv22off BIN=nvt1v22_drv BUNDLE_V22=/home/unionxic/gi-bundle/nvshmem_t1close_b2/v22ref FT=0 ITERS=2000 REPS=5 BYTES=262144 KTIMEOUT=40 PROC_TIMEOUT=60
10 none lat TAG=lat256k_dt1off BUNDLE=/home/unionxic/gi-bundle/nvshmem_t1close_b2 FT=0 ITERS=2000 REPS=5 BYTES=262144 KTIMEOUT=40 PROC_TIMEOUT=60
10 none lat TAG=lat256k_dt1on BUNDLE=/home/unionxic/gi-bundle/nvshmem_t1close_b2 ITERS=2000 REPS=5 BYTES=262144 KTIMEOUT=40 PROC_TIMEOUT=60
```

## 8. 제외 기준과 중단 기준

- **제외 기준:**
  - smoke 실행은 채점하지 않는다. 결과는 `results/<날짜>_smoke/`에 둔다.
  - void, 장애가 걸리지 않은 시행, 빌드 md5가 그 칸의 묶음(3절 표)과 다른 시행은 따로 센다. 보충하지 않는다.
  - hold의 `STOP_AFTER_S` 때문에 돌지 못한 시행은 "실행 안 함"으로 센다.
- **중단 기준:**
  - 모든 클러스터 명령은 `harness/gpu-initiated/common/cluster_run.sh -w 10800` 안에서 돈다. GIN 재연결 실험이 같은 잠금을 쓰며
    함께 돈다. 10800 s 안에 잠금이나 유휴 링크를 얻지 못하면 그 hold를 미루고 12절에 적는다. `prio-` 작업이 기다리면 지금 hold가
    끝난 뒤 양보한다.
  - 실제 link down이나 flap, 재부팅, 드라이버 재적재, 커널 모듈 적재(gdrdrv 포함), RoCE 주소 변경은 하지 않는다.
  - 프로세스는 이 실험이 띄운 것만 정확한 이름(`nvt1_drv`, `nvt1v22_drv`, `nvt1st_drv`, `pkill -x`) 또는 PID로 끈다. 다른 사용자의
    작업(gds-kv, NVMe-oF, gdsio, mooncake, `prio-` 태그 작업)과 다른 실험의 프로세스는 건드리지 않는다.
  - hold 앞뒤로 rain과 sunny의 dmesg 전체를 남긴다(sunny는 `sudo -n dmesg`). 새 줄에 mlx5 명령 오류(`mlx5` 줄에 명령 실패나 시간
    초과, FWTracer 제외)가 나오면 캠페인을 멈추고 적는다. rain `mlx5_1`은 2026-09-25부터 펌웨어 명령 슬롯 하나가 샌 상태다.
  - 이 실험은 iptables를 쓰지 않는다. 모든 hold 뒤 rain의 `t1sock` 규칙 수가 0인지 센다.
  - 옮긴 빌드가 컴파일되지 않거나 diff가 v3.8.0-0 위에 다시 적용되지 않으면 상태를 `BLOCKED`로 두고 이유를 적는다.
  - smoke에서 재현 칸(R)에 failed가 나오면 본 실행 전에 멈추고 `BLOCKED`로 둔다.
  - CPU 프록시 칸(N2, N3)의 smoke가 void(초기화 실패)이면 그 칸만 `BLOCKED`로 두고 나머지 hold를 진행한다.
  - 공식 그대로의 지연 드라이버를 만들 수 없으면 그 지연 칸(N4, R12)만 `BLOCKED`로 둔다.

## 9. 실행 방법과 경로

- **배포/빌드:**
  - 소스: `<scratch>/agent_t1_380/src`에 `git archive v3.8.0-0`을 풀고 git에 "pristine v3.8.0-0"으로 커밋한다.
    `../../nvshmem/nvshmem_ibgda_fault_inject.diff`와 `../../nvshmem_rootcause/nvshmem_nrc_proxy_sq_dbr.diff`를 적용해
    "base"로 커밋한다. 그 위에 `../t1_close/nvshmem_ibgda_t1close.diff`를 `git apply --reject`로 적용한다.
    거부된 `barrier.cpp` hunk(include 두 줄과 `nvshmemi_ft_transport_failed`, 장치 barrier 건너뛰기)는 같은 내용을 3.8.0의 include
    목록 아래에 손으로 넣는다.
  - 빌드: `../../nvshmem_rootcause/official380/build.sh`와 같은 cmake 선택으로 `<scratch>/agent_t1_380/build`에 전체 빌드하고
    `<scratch>/agent_t1_380/install`에 설치한다. 공식 3.8.0 전체 빌드는 8 m 9 s였다 `[측정]`(`off380/time.log`).
  - 드라이버:
    - `../nvshmem_t1.cu`를 옮긴 설치에 링크해 `nvt1_drv`로 만든다.
    - 같은 소스를 `-DT1_STOCK`(FT API를 쓰지 않음: 상태 조회는 0, 호스트 오류 조회는 없음)으로 `<scratch>/off380/install`에 링크해
      `nvt1st_drv`로 만든다. 드라이버에 이 매크로를 더한다.
  - 전체 diff: `t1_380/nvshmem_ibgda_t1_380.diff` = base 대비 작업 트리. pristine v3.8.0-0 + 두 층 위에 다시 적용되고 트리를
    재현하는지 확인한다(`t1_380/make_diff.sh`).
  - soname: 3.8.0은 `libnvshmem_host.so.3.8.0`이다 `[측정]`. `run_trial_t1.sh`의 host md5는 `libnvshmem_host.so.3`(심볼릭 링크)에서
    읽게 바꿔 3.9.0과 3.8.0을 함께 다룬다. 배포 스크립트는 `*.so*`를 복사해 이름에 매이지 않는다.
  - 배포: 새 묶음 `~/gi-bundle/nvshmem_t1_380/{lib,bin}`과 `stock380/{lib,bin}`(`~/gi-bundle/nvshmem_off380/lib_stock`의 `*.so*`를
    복사)을 rain과 sunny에 만든다. 대상이 이미 있으면 멈춘다. 두 노드 md5를 비교하고, 기존 묶음 파일 md5를 앞뒤로 비교해 바뀐 것이
    없음을 확인한다(t1_close `deploy.sh` 방식).
  - 실행기와 집계: `run_trial_t1.sh`에 `nvt1st_drv`와 `BUNDLE_STOCK`, `.meta`의 `handler=`를 더한다. `rows_t1.py`에 3절의 새 필드를
    더한다. hold 래퍼는 t1_close의 `hold.sh`를 이 묶음 이름과 `nvt1st_drv`로 옮긴다.
- **실행:** (`harness/gpu-initiated/nvshmem_ft`에서)

  ```
  CR=../common/cluster_run.sh; R=t1_380/results/<date>
  $CR -w 10800 -t t1x-A -- timeout -s KILL 900 bash t1_380/hold.sh $R/A t1:t1_380/specs/holdA.txt:1:780:gate_test
  $CR -w 10800 -t t1x-B -- timeout -s KILL 900 bash t1_380/hold.sh $R/B t1:t1_380/specs/holdB.txt:1:780
  $CR -w 10800 -t t1x-C -- timeout -s KILL 900 bash t1_380/hold.sh $R/C t1:t1_380/specs/holdC.txt:1:780
  ```

  spec 파일은 7절의 줄 그대로다. smoke는 칸마다 1회(지연은 공식 그대로와 옮긴 빌드 투명 켬 4 KiB 1회씩)를 `${R}_smoke`에 둔다.
- **예상 클러스터 시간:** smoke 약 3분, A 약 6–7분(t1_close hold A 55회가 7 m 9 s `[측정]`), B 약 5분, C 약 4–5분(지연 40회가
  1 m 21 s `[측정]`). 실행만 약 20분이다. 잠금을 기다리는 시간은 따로다.
- **채점:** `t1_380/score.py`(t1_close `score.py`를 옮겨 predictions.csv 규칙과 3절의 빌드 묶음을 그대로 적용).
  결과는 `results/<date>/SCORE.md`와 `trials_scored.csv`.
- **입력:** 위 spec, 묶음 P, S와 읽기만 하는 묶음 D, V.
- **출력:** `t1_380/results/<date>/`. 원시 로그는 Release에 올리고 `DATA.md`에 적는다.

## 10. 완료 조건과 QA 기준

- [x] 모든 셀이 계획한 n만큼 실행됐다(제외와 실패를 따로 센 표 포함).
- [x] 예측마다 판정(맞음/틀림/자료 없음)과 놓친 시행 목록이 있다.
- [x] 핵심 수치를 원자료에서 다시 계산했다.
- [x] smoke와 제외 시행이 결과에 섞이지 않았다.
- [x] 원자료를 Release에 올리고 DATA.md에 적었다.
- [x] 옮긴 빌드의 전체 diff가 pristine v3.8.0-0 + 두 층 위에 다시 적용되고 트리를 재현한다.
- [x] 모든 시행의 빌드 md5가 그 칸의 묶음과 같다(rain 쪽 `.meta` 기준). 기존 묶음 파일 가운데 GIN 재연결 실험의 새 묶음 하나가 이 실험 중에 바뀌었다(DEVIATIONS 3, 그 실험의 파일).

## 11. 작업 체크리스트

- [x] 질문, 가설, 셀 작성 (`DRAFT`)
- [x] 고정 절 완성, 상태 `PREREGISTERED`, 해시 기록을 커밋 하나로 만들고 그 커밋에 `prereg/` 태그
- [x] 계측과 실행기 구현, 빌드, 리뷰(리뷰는 자체 검토만, 12절)
- [x] smoke 실행(채점 제외)
- [x] 본 실행 (`RUNNING`)
- [x] 채점과 재계산 (`QA`)
- [x] 결과 정리, 원자료 릴리스, PR
- [x] 결론 확정 (`COMPLETE`)

## 12. 실행 기록 (시간순)

| 시각 | 무엇을 했나 | 결과와 근거(경로, 커밋, 실행 ID) |
|---|---|---|
| 2026-10-07 18:18–18:41 | t1_close 범위 조사에서 공식 3.8.0과 비교: IBGDA 소스 차이, 투명 복구 diff 적용 시험(hunk 하나 거부) | 1절 숫자, 조사 메모는 저장소 밖(scratchpad) |
| 2026-10-08 10:24 | t1_close diff를 pristine v3.8.0-0 + 두 층에 적용 시험(scratchpad, 빌드 없음): 두 층 그대로, `barrier.cpp` hunk 하나 거부. 두 빌드의 cmake 선택과 공식 그대로 묶음 md5 확인 | `<scratch>/agent_t1_380/applycheck`(저장소 밖) |
| 2026-10-08 10:31:23 | 사전 등록 | [PREREG.txt](PREREG.txt), 태그 `prereg/nvshmem-t1-380-v1` |
| 2026-10-08 10:32–10:34 | scratch 소스 트리 `<scratch>/agent_t1_380/src`: pristine v3.8.0-0(`270759e5`) 커밋, 두 층 적용 뒤 "base" 커밋, t1_close diff 적용. 거부된 `barrier.cpp` hunk는 같은 코드를 3.8.0의 include 목록 아래에 손으로 넣음. 넣은 코드 줄이 t1_close diff와 같음(주석 정렬 공백만 다름) | 저장소 밖. 결과 diff는 [nvshmem_ibgda_t1_380.diff](nvshmem_ibgda_t1_380.diff)(5765줄, md5 `187507e0`). pristine v3.8.0-0 + 두 층 위 재적용과 트리 재현 확인(`make_diff.sh`) `[측정]` |
| 2026-10-08 10:32–10:47 | 빌드(`build.sh`): official380과 같은 cmake 선택으로 전체 빌드 14 m 5 s(다른 실험과 CPU를 나눔), 드라이버 둘(`nvt1_drv`, `-DT1_STOCK`의 `nvt1st_drv`). 경고는 nvcc의 옛 아키텍처 안내 4줄뿐 | md5: transport `d6ae3699`, host `825443f8`(`libnvshmem_host.so.3.8.0`), `nvt1_drv` `e309d516`, `nvt1st_drv` `4dae151f` `[측정]` |
| 2026-10-08 10:48:57 | 배포(`deploy.sh`): 새 묶음 `~/gi-bundle/nvshmem_t1_380`(`lib`, `bin`, `stock380/lib`, `stock380/bin`) 두 노드. 두 노드 md5 같음(14파일). 기존 묶음 파일 변경 0건(rain 244, sunny 296파일) | 공식 그대로 묶음 md5: transport `4aa4dda2`, host `80eea986` `[측정]` |
| 2026-10-08 10:49:39–10:51:40 | smoke(`t1x-smoke`, 15회, 채점 제외): 칸마다 1회, 지연은 공식 그대로와 옮긴 빌드 투명 켬 4 KiB 1회씩 | `results/20261008_smoke/smoke/`. 모든 칸이 예측대로(장애 칸 투명, 거절 칸 거절, CPU 프록시는 두 PE 거부 줄과 장치 기록 0, 커널 시간 제한). 중단 규칙 해당 없음. 두 노드 새 dmesg 0줄, mlx5 명령 오류 0, iptables 규칙 0, 남은 프로세스 0 |
| 2026-10-08 10:52:42 | 본 실행 시작(`run_main.sh`, hold A, B, C 차례로, hold마다 `cluster_run.sh -w 10800 -t t1x-<hold>`). 상태 `RUNNING` | `results/20261008/run_main.out` |
| 2026-10-08 10:55:13–11:01:47 | hold A(`t1x-A`, 잠금 10:54:42): 재현 칸 7개, 진행 중 로컬 QP 오류 두 빌드 10회씩, 스위치 끈 대조, 55회 모두 실행. gate 경합 시험 PASS 2/2 | `results/20261008/A/`. 두 노드 새 dmesg 0줄, mlx5 명령 오류 0, iptables 규칙 0, 남은 프로세스 0 `[측정]`(`A/hold.log`) |
| 2026-10-08 11:08:35–11:13:10 | hold B(`t1x-B`, GIN 실험 hold 뒤): fetch 세 칸, CPU 프록시 칸, 25회 모두 실행 | `results/20261008/B/`. 두 노드 새 dmesg 0줄, mlx5 명령 오류 0, iptables 규칙 0, 남은 프로세스 0 `[측정]`(`B/hold.log`) |
| 2026-10-08 11:19:59–11:24:05 | hold C(`t1x-C`, 잠금 11:19:27, GIN 실험 hold 뒤): 장애 없는 지연 12칸, 120회 모두 실행 | `results/20261008/C/`. 두 노드 새 dmesg 0줄, mlx5 명령 오류 0, iptables 규칙 0, 남은 프로세스 0 `[측정]`(`C/hold.log`) |
| 2026-10-08 11:24:05 | 본 실행 끝. 200회 모두 실행, 실행 안 된 시행 0, 따로 센 시행 0 | `results/20261008/run_main.out` |
| 2026-10-08 11:25 | 기존 묶음 파일 md5 재확인: 이 실험의 새 묶음과 기존 파일은 그대로. 다른 실험 묶음의 파일 하나(`gin_ts2/rc/libnccl.so.2.32.3`)가 10:50:44에 바뀜(이 실험이 쓴 것 아님) | [DEVIATIONS.md](DEVIATIONS.md) 3 |
| 2026-10-08 11:27 | 채점(`score.py`, 고정 규칙 그대로). 18개 예측 중 맞음 15, 틀림 3(지연 세 줄). 상태 `QA`. 다른 에이전트의 독립 재계산은 아직 | [results/20261008/SCORE.md](results/20261008/SCORE.md), [results/20261008/trials_scored.csv](results/20261008/trials_scored.csv) |
| 2026-10-08 11:38:56 | 다른 에이전트가 원시 로그에서 독립 재계산. 판정과 수치 같음(15/18). 15절 서술 네 곳을 원자료에 맞게 고침. 위 hold A 줄의 "재현 칸 7개"는 6개가 맞다(6 × 5 + 2 × 10 + 5 = 55). "남은 프로세스 0"은 hold 끝 기준이다(16절) | [results/20261008/qa_recount.md](results/20261008/qa_recount.md) |
| 2026-10-08 11:40:20 | 원자료 묶음 2개(본 실행 641파일, smoke 58파일)로 Release `data-20261008`을 만듦. 받아서 체크섬 확인, 원본과 주소 치환 외 차이 없음(699파일) | [DATA.md](../../../../DATA.md) |
| 2026-10-08 11:50 | README 작성, 상위 문서 링크, 상태 `COMPLETE`, PR | 이 PR |

## 13. 사전 등록 이후 변경

> 기존 문장을 고치지 않고 여기에 덧붙인다. 변경이 많으면 `DEVIATIONS.md`에 두고 링크한다.

| 날짜 | 무엇을 | 이유 | 영향 범위 | 커밋 |
|---|---|---|---|---|

변경은 [DEVIATIONS.md](DEVIATIONS.md)에 적었다. 예측, 셀, 반복 수, 판정 기준을 바꾼 것은 없다. hold 래퍼가 남은 프로세스를 세게 한 것(1),
실행 기록 시각 정정(2), 다른 실험이 기존 묶음 파일 하나를 바꾼 것의 기록(3)이다.

## 14. 원자료와 결과표

| 무엇 | 경로 또는 Release 자산 | n |
|---|---|--:|
| 채점 결과(예측별 판정, 유효 n, 놓친 시행, 따로 센 시행) | [results/20261008/SCORE.md](results/20261008/SCORE.md) | 18 예측 |
| 시행별 값(채점에 쓴 필드, 라운드 시간, 지연 rep p50, md5) | [results/20261008/trials_scored.csv](results/20261008/trials_scored.csv) | 200 |
| 본 실행 원자료(시행별 `.meta`, 두 PE 로그, hold 로그, 두 노드 dmesg 앞뒤) | Release `data-20261008`의 `harness__gpu-initiated__nvshmem_ft__t1_380__results__20261008.tar.xz` | 200 |
| 독립 재계산 | [results/20261008/qa_recount.md](results/20261008/qa_recount.md), [qa/recount.py](qa/recount.py) | 200 |
| smoke 원자료(채점 제외) | Release `data-20261008`의 `..._t1_380__results__20261008_smoke.tar.xz` | 15 |
| 옮긴 빌드의 전체 diff | [nvshmem_ibgda_t1_380.diff](nvshmem_ibgda_t1_380.diff)(md5 `187507e0`) | |

## 15. 결과 요약

본 실행 200회, 따로 센 시행 0, 실행 안 된 시행 0이다. smoke 15회는 채점하지 않았다. 판정은 [SCORE.md](results/20261008/SCORE.md),
시행별 값은 [trials_scored.csv](results/20261008/trials_scored.csv)에 있다. 모두 `[측정]`이다. 범위는 따로 적지 않으면 "그 칸의 모든 유효
시행(또는 라운드)에 걸친 범위"이고, 지연의 best-run은 "그 칸 10회 실행 각각의 rep p50 중앙값 가운데 최솟값"이다. 독립 재계산이 판정과
수치를 모두 확인했고, 재계산이 짚은 서술 네 곳을 원자료에 맞게 고쳤다(16절).

**장애 동작: 18개 중 15개 맞음, 장애 칸은 모두 맞음**

| 칸 | 예측 | 결과 | 판정 |
|---|---|---|---|
| 장애 없음 (R1) | 투명, 라운드 0 | 5/5 투명 | 맞음 |
| 진행 중 로컬 QP 오류, 옮긴 빌드 (R2) | 투명, 라운드 1 | 10/10 투명. 복구 4.21–5.41 ms(라운드 10개, 중앙값 4.79) | 맞음 |
| 같은 셀, devel 빌드 (R3) | 투명, 라운드 1 | 10/10 투명. 복구 4.29–4.60 ms(라운드 10개, 중앙값 4.42) | 맞음 |
| 두 빌드의 복구 시간 (N1) | 중앙값 차이 ≤ 1.0 ms | 차이 +0.37 ms(4.79 대 4.42) | 맞음 |
| 상대 QP 오류 (R4) | 투명 | 5/5 투명, 복구 6.14–6.37 ms(라운드 5개) | 맞음 |
| 상대 QP 오류 + 매 반복 fetch (R5) | 투명, 실행 안 된 fetch를 다시 보냄 | 5/5 투명, fetch 1000개 값과 카운터 정확, 실행된 fetch 0, 다시 보낸 fetch 1 | 맞음 |
| 연산 사이 로컬 QP 오류 + 매 반복 fetch (R6) | 투명 | 5/5 투명, fetch 160개 정확 | 맞음 |
| 진행 중 로컬 QP 오류 + 매 반복 fetch (R7) | 결과가 실행 여부와 일치 | 5/5 투명(실행된 fetch 0, 카운터 16000). 이번 5회에는 거절이 없었다 | 맞음 |
| 앱의 heap 밖 쓰기 (R8) | 거절, 정리 반환 | 5/5 거절(REM_ACCESS), finalize 22.2–22.6 ms | 맞음 |
| 상대 kill (R9) | 거절, 정리 반환 | 5/5 거절(상대 소켓 FIN), finalize 24.5–25.5 ms | 맞음 |
| finalize 없는 종료 (R10) | 5 s 안에 helper join | 5/5 투명, rc 0/0. T1EXIT에서 ATEXIT까지 2.16–2.27 ms(두 PE, 10개), detached 0 | 맞음 |
| 상대당 RC QP 4개 (R11) | 라운드 하나가 QP 4개 | 5/5 투명, 라운드마다 QP 4개, 복구 15.06–18.13 ms(라운드 5개) | 맞음 |
| 투명 스위치 끔 (C1) | 앱이 오류를 봄 | 5/5 status_bad 44–82, 라운드 0, failed(PE 0은 실행 상한에서 kill, rc 137) | 맞음 |
| CPU 프록시, 투명 복구 거부 (N2) | 두 PE 거부 | 10/10 두 PE 모두 "transparent mode stays off", 켜짐 줄 없음, 라운드 0, failed | 맞음 |
| CPU 프록시, 오류 완료가 장치에 오지 않음 (N3) | 장치 기록 0, 커널 시간 제한 | 10/10 장치 기록 0, PE 0 커널 10 s 시간 제한(rc 7/4) | 맞음 |

- 옮긴 빌드의 장애 동작은 t1_close(devel `7bb2e99c`)와 같았다. 투명, 거절, finalize 없는 종료, QP 4개, 스위치 끈 대조가 모두
  같은 결과였다. fetch 규칙은 투명한 쪽만 같다고 확인됐다. 진행 중 fetch 칸(R7)에서 이번에는 실행된 fetch가 나오지 않아 거절이 0회였고,
  "실행된 fetch만 거절"하는 쪽은 이 실험에서 시험되지 않았다. 같은 hold의 devel 빌드와 견준 복구 시간 차이는 0.37 ms였다(짝지은 10회 중
  8회에서 옮긴 빌드가 느렸다).
- CPU 프록시에서는 투명 복구가 켜지지 않았고, 로컬 QP 오류 뒤 오류 완료가 장치에 하나도 오지 않았다(두 PE 모두 오류 완료 줄 0, PE 0 커널
  10.0 s 시간 제한). 공식 v3.8.0-0의 CPU 프록시 record 버그(`MODEL.md` 규칙 1)가 옮긴 빌드에도 그대로 있기 때문으로 본다 `[추론]`.
  두 줄 수정은 넣지 않았다.

**장애 없는 지연: 세 줄 모두 틀림**

best-run p50(µs, 칸마다 10회 실행):

| 크기 | 공식 그대로 | 옮긴 빌드 FT 끔 | 옮긴 빌드 투명 켬 | devel v2.2 기준 | devel FT 끔 | devel 투명 켬 |
|---|--:|--:|--:|--:|--:|--:|
| 4 KiB | 12.224 | 14.048 | 14.624 | 12.384 | 13.376 | 14.656 |
| 256 KiB | 39.648 | 41.344 | 42.496 | 40.160 | 40.960 | 42.336 |

| 예측 | 기준 | 결과 | 판정 |
|---|---|---|---|
| 공식 그대로 대 devel v2.2 기준 (N4) | 두 크기 모두 차이 ≤ 0.5 µs | 4 KiB −0.160, 256 KiB −0.512 | **틀림**(256 KiB, 타이머 한 단위 0.032 µs 차이로 넘음. 공식 그대로의 1번 실행 하나를 빼면 −0.480. 다만 칸 중앙값 차이는 −0.592이고 10회 중 9회가 v2.2의 모든 실행보다 빨라 차이 자체는 실제다) |
| 옮긴 빌드 대 devel 빌드 (N5) | 네 쌍 모두 차이 ≤ 0.5 µs | 4 KiB FT 끔 +0.672, 투명 켬 −0.032. 256 KiB FT 끔 +0.384, 투명 켬 +0.160 | **틀림**(4 KiB FT 끔) |
| 공식 그대로 대비 비용 (R12) | 4 KiB 켬 [1.0, 2.6], 4 KiB 끔 [0.2, 1.2], 256 KiB 켬 [0.8, 2.4] | +2.400, +1.824, +2.848 | **틀림**(4 KiB 끔, 256 KiB 켬) |

- 투명 복구를 켠 지연은 두 빌드가 같았다(4 KiB −0.03, 256 KiB +0.16 µs).
- 틀린 이유는 두 가지다.
  - 옮긴 빌드의 FT 끔이 4 KiB에서 느렸다. 실행 10회 중 8회가 15.52–15.58 µs, 2회가 14.05와 14.72 µs였다. devel의 FT 끔은
    13.38–13.86 µs(1회 15.10)였다. 이 차이는 실행 하나를 빼도 그대로다. 그래도 옮긴 빌드의 FT 끔은 투명 켬보다 0.58 µs(best-run),
    0.62 µs(실행 중앙값) 빨랐다.
  - 4 KiB 투명 켬의 비용(+2.400, 맞음)은 best-run 기준에서만 범위 안이다. 옮긴 빌드 투명 켬의 실행 10회는 빠른 4회와 느린 6회로 갈렸고,
    실행 하나씩만 보면 4회만 범위 안이다.
  - 공식 3.8.0 그대로가 256 KiB에서 devel v2.2 기준보다 0.51 µs 빨랐다.
- 옮긴 빌드의 FT 끔이 왜 느린지는 `[미확인]`이다. IBGDA 장치 소스는 include 한 줄만 다르다 `[소스]`. 장치 코드에 함께 들어가는
  다른 3.8.0 헤더(트리 전체로 197개 파일 차이)가 컴파일 결과를 바꿨을 수 있다 `[추론]`. SASS로 확인하지 않았다.

## 16. QA와 재현성

- **독립 재계산:** 다른 에이전트가 `score.py`, 채점 결과, `rows_t1.py` 출력을 쓰지 않고 원시 로그에서 다시 셌다
  ([results/20261008/qa_recount.md](results/20261008/qa_recount.md), [qa/recount.py](qa/recount.py)). 판정과 15절의 수치가 모두 같다
  (18개 중 15개 맞음). 시행 집합 200회는 7절과 같고, 시행마다 그 칸의 빌드였다(`.meta` md5와 라이브러리 버전 배너). 고정 파일과
  2, 3, 7, 8절은 태그 뒤 바뀌지 않았다.
- **재계산이 바로잡은 서술(판정 영향 없음):** CPU 프록시 칸의 원인 설명은 `[추론]`으로 표시했다. fetch 규칙이 "같다"는 것은 투명한 쪽만
  확인됐다고 고쳤다. FT 끔이 투명 켬과 "거의 같다"는 표현은 0.58–0.62 µs 차이로 고쳤다. 256 KiB 공식 대 v2.2 차이가 타이머 한 단위로
  넘은 것과, 4 KiB 투명 켬 비용이 best-run에서만 범위 안이라는 것을 더했다.
- **남은 프로세스:** 투명 스위치를 끈 칸(C1) 5회 모두 시행 직후 검사에 실행 상한에서 kill된 PE 0이 1개씩 보였다. 다음 시행은 `pkill -x`로
  시작했고 hold 끝에는 0이었다. 끝나는 중인 프로세스로 본다 `[추론]`.
- **확인하지 못한 것:** sunny 쪽 바이너리 md5는 시행마다 확인하지 않았다(배포 때 두 노드 일치 확인). 커널 시간 제한 등 일부 설정은
  `.meta`에 남지 않는다.
- **재현:** [nvshmem_ibgda_t1_380.diff](nvshmem_ibgda_t1_380.diff)(md5 `187507e0`)를 pristine v3.8.0-0(`270759e5`)과 장애 주입, record
  knob 두 층 위에 적용한다. 빌드와 배포는 [build.sh](build.sh), [deploy.sh](deploy.sh).

## 17. 결론

- **투명 복구는 공식 3.8.0에서도 같은 장애 동작을 보였다.** 투명, 거절, finalize 없는 종료, QP 4개, 스위치 끈 대조가 devel `7bb2e99c`와
  같았고(15개 중 15개), 같은 hold에서 잰 복구 시간 차이는 0.37 ms였다. 이제 NVSHMEM 투명 복구 결과를 공식 릴리스 기준으로 말할 수 있다.
- **CPU 프록시에서는 여전히 오류 완료가 오지 않는다.** 이식한 빌드에서도 CPU 프록시는 투명 복구를 거부했고, 장애 뒤 오류 완료가 0개였다
  (10/10). #117의 수정이 공개되기 전까지는 GPU 처리 방식에서만 쓸 수 있다.
- **장애 없는 지연은 예측대로 옮겨지지 않았다.** 투명 복구를 켠 지연은 두 빌드가 같았지만, 기능을 끈 빌드가 4 KiB에서 0.67 µs 느렸다.
  원인은 모른다. 장애 동작에는 영향이 없다.

## 18. 한계

- 재현 칸은 5회씩이다. 진행 중 fetch 칸에서 이번에는 실행된 fetch가 나오지 않아, "실행된 fetch만 거절" 쪽은 3.8.0에서 시험되지 않았다.
- 기능을 끈 이식 빌드가 4 KiB에서 느린 원인을 SASS로 확인하지 않았다.
- 소켓 끊김 칸은 뺐다. PE 2개, 노드당 GPU 1개, RC QP만 쟀다.
- #117의 두 줄 수정은 넣지 않았다. 공개 수정이 나오면 그 릴리스로 다시 옮겨야 CPU 프록시 쪽 결론이 바뀐다.

## 19. 다음 작업

- #117 수정이 공개되면 그 릴리스로 옮기고, CPU 프록시에서 오류 완료가 생기는지와 투명 복구 재현 칸을 다시 잰다.
- 기능을 끈 이식 빌드의 4 KiB 지연 차이를 SASS로 본다.

## 20. 참고자료

- [../t1_close/EXPERIMENT.md](../t1_close/EXPERIMENT.md), [../t1_close/nvshmem_ibgda_t1close.diff](../t1_close/nvshmem_ibgda_t1close.diff).
- [../TRANSPARENT_T1.md](../TRANSPARENT_T1.md).
- [../../nvshmem_rootcause/README.md](../../nvshmem_rootcause/README.md), [../../nvshmem_rootcause/cq380/README.md](../../nvshmem_rootcause/cq380/README.md),
  [../../nvshmem_rootcause/official380/README.md](../../nvshmem_rootcause/official380/README.md).
- [../../../../MODEL.md](../../../../MODEL.md) 규칙 1, 5.
