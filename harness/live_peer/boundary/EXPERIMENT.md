# 오판이 시작되는 경계 (live_boundary)

**목적:** 살아 있는 상대가 멈춘 시간을 마감 근처에서 촘촘히 바꿔 가며, 판정이 "살아 있음 또는 복구"에서 "응답 없음 또는 복구
불가"로 바뀌는 경계가 어디인지, 그 경계를 소스의 상수와 커널의 타이머 동작만으로 미리 맞힐 수 있는지 잰다.

| 항목 | 값 |
|---|---|
| 상태 | `QA` |
| 담당자 | @unionxic |
| 작성일 | 2026-10-08 |
| 기준 브랜치와 커밋 | `exp/live-boundary` @ `613003e9` (master) |
| 사전 등록 태그 | `prereg/live-boundary-v1` (이 상태로 바꾼 커밋) |
| 마지막 갱신 | 2026-10-08 14:50, 본 실행 110회, 채점, 결과 요약(14, 15절). 16–19절은 독립 재계산 뒤 |

표시: `[측정]` 원자료에서 확인, `[소스]` 코드나 문서에서 읽음, `[추론]` 해석, `[미확인]` 확인 안 함. 이 문서를 쓰는 동안
클러스터에서 아무것도 실행하지 않았고 빌드도 하지 않았다. 측정값은 live_peer의 원자료(Release `data-20261007`의
`harness__live_peer__results__20261007.tar.xz`, 체크섬 확인)와 rain의 로컬 설정 읽기에서만 왔다.

## 1. 배경과 연구 질문

### 1.1 live_peer가 남긴 것

- `[측정]` live_peer([../EXPERIMENT.md](../EXPERIMENT.md), 태그 `prereg/live-peer-v1`)는 마감의 양쪽에 정지 시간을 하나씩만
  쟀다.
  - CPU 하네스: 응답 QP 오류 + 프로세스 8 s 정지 → "응답 없음" 10/10. 생존 확인의 대기는 1 s다.
  - GIN GDAKI 복구 v2: 복구 요청을 받을 때 1 s 정지 → 복구 10/10, 6 s 정지 → 거절 10/10. 핸드셰이크 마감은 3 s다.
- `MODEL.md` 규칙 3의 한계(`MODEL.md:126`, `:200`)도 "경계 자체는 재지 않았다"고 적는다.
- live_peer에서 유일하게 틀린 예측은 6 s 정지 GIN 셀의 거절 시각이었다(`../EXPERIMENT.md` 15절). 거절은 장애 조회 뒤
  2999.2–3002.2 ms(n=10)였고, 두 시행이 예측 하한 3000 ms보다 일렀다. 원인은 마감이 Prepare와 요청 전송 뒤에 걸리고, 남은
  대기가 두 번 정수 ms로 잘리기 때문이었다. 10개 값은 2999.24–2999.33 ms(2개)와 3002.14–3002.23 ms(8개) 두 무리로 갈렸고, 그
  이유는 확인하지 않았다(`[미확인]`).

### 1.2 소스에서 읽은 두 마감의 실제 길이

- **CPU 하네스 생존 확인(1 s).** `[소스]`
  - 요청 쪽은 제어 연결에 `SO_RCVTIMEO` 1 s를 걸고 PROBE를 보낸 뒤 한 바이트씩 `recv`한다
    (`harness/client/probe_client.c:519-522`, `harness/common/probe.c:150`).
  - 커널은 1 s를 jiffy로 바꾼다(`tv_sec * HZ`, 리눅스 6.10.8 `net/core/sock.c:451-453`). rain은 `CONFIG_HZ=250`이라 250 jiffy다
    (`[측정]` `/boot/config-5.15.0-97-generic`, 2026-10-08).
  - TCP `recv`는 `sk_wait_data`(`net/core/sock.c:3024-3031`)에서 `schedule_timeout`으로 잔다. 이 타이머는 고해상도 타이머가
    아니라 타이머 휠에 들어간다.
  - 타이머 휠은 250 jiffy 앞의 타이머를 단계 1(간격 8 jiffy, HZ=250에서 32 ms)에 넣고, 만료를 다음 8 jiffy 경계로 올린다
    (`kernel/time/timer.c:129-133` 표, `:154-168`, `:567-593`). 5.4 소스도 같은 반올림이다(`linux-source-5.4.0`
    `kernel/time/timer.c:492-506`). rain의 5.15 소스는 로컬에 없다(`[추론]` 두 판 사이라 같다).
  - `[추론]` 그래서 1 s 대기는 실제로 250–258 jiffy, 즉 1000–1032 ms 뒤에 끝난다. 끝나는 시점은 PROBE를 보낸 순간의 jiffy
    위상에 따라 이 범위에 거의 고르게 퍼진다. 이 32 ms 폭이 CPU 하네스 경계의 불확실 구간이다.
- **GIN 복구 핸드셰이크(3 s).** `[소스]`
  - rank 0은 Prepare를 마치고 요청(REQ)을 보낸 뒤 마감 `dl = now + 3000`을 건다(`gin_recovery/gin_rec.cu:489`).
  - 남은 시간은 바깥 루프에서 한 번(`:492`, 2999 ms), `recv()` 안에서 또 한 번(`:172`, 2998 ms) 정수로 잘린 뒤 `poll`에
    들어간다(`:175`).
  - `poll`은 nice 0 작업에 타임아웃의 1/1000을 여유(slack)로 준다(리눅스 6.10.8 `fs/select.c:53-94`). 2998 ms면 2.998 ms다.
    타이머는 [2998.0, 3001.0] ms 구간 어디선가 끝난다.
  - 시간 초과면 abort와 FAIL 전송 뒤 거절을 기록한다(`gin_rec.cu:500`).
  - `[추론]` live_peer 거절 시각의 두 무리(간격 약 2.9 ms)는 이 여유 구간의 앞 끝과 뒤 끝이다. 앞 끝은 장애 조회 + Prepare
    (1.03–1.18 ms) + 2998.0 + 기록(약 0.1–0.2 ms) ≈ 2999.2 ms, 뒤 끝은 ≈ 3002.2 ms다.
- `[측정]` live_peer 원자료에서 다시 셌다(Release `data-20261007`, 이 설계 중 재계산).
  - rank 0의 Prepare 시간(장애 조회부터 Prepare 끝까지): 1.034–1.176 ms(n=15, 정지 없는 셀과 1 s 셀).
  - rank 1이 정지에서 깨어난 뒤 ACK가 rank 0에 닿기까지: 4.43–4.95 ms(n=10, 1 s 셀). 정지 없는 셀은 4.16–4.35 ms(n=5).
  - 도우미가 잰 정지 길이는 설정값보다 0.070–0.109 ms 길었다(n=20).
  - CPU 하네스의 첫 CQE(재시도 초과)까지: 3494.7–3755.9 ms(n=55, 재시도 초과 일곱 셀).

### 1.3 연구 질문

1. CPU 하네스에서 생존 확인의 실제 마감은 언제인가. 응답 지연이 얼마일 때 판정이 "살아 있음"에서 "응답 없음"으로 바뀌는가.
2. 장애 순간부터 멈춘 상대(live_peer와 같은 조건)에서는, 정지 시간이 "첫 CQE + 실제 마감"을 넘을 때 판정이 바뀌는가.
3. GIN 복구에서 정지 시간이 얼마일 때 "복구"에서 "거절"로 바뀌는가. 그 경계와 거절 시각의 두 무리를 소스의 절삭과 `poll`
   여유로 맞힐 수 있는가.

## 2. 가설

- **생존 확인의 실제 마감은 1000–1032 ms다(가설 1).** 1 s 소켓 타임아웃은 타이머 휠의 8 jiffy 반올림 때문에 1000 ms보다 일찍
  끝나지 않고, 1032 ms(+ 깨우는 지연)보다 늦게 끝나지 않는다. 판정은 응답과 마감 중 먼저 오는 쪽으로 정해진다.
  - 반증: 응답이 1000 ms 안에 왔는데 "응답 없음"이 나온다. 응답 없음 시행의 대기가 1000 ms보다 짧거나 1033 ms보다 길다. 응답
    없음 시행들의 대기 끝이 한 값에 몰린다(퍼짐 16 ms 미만).
- **장애 순간부터 멈춘 상대의 경계는 첫 CQE + 실제 마감이다(가설 2).** 상대가 첫 CQE 뒤에도 x ms 더 멈춰 있으면 x가 995 ms
  이하일 때 살아 있음, 1034 ms 이상일 때 응답 없음이다.
  - 반증: x ≤ 995 ms인 시행에서 응답 없음, x ≥ 1034 ms인 시행에서 살아 있음.
- **GIN 복구의 경계는 Prepare 뒤 2998–3001 ms에 ACK가 닿느냐로 정해진다(가설 3).** rank 1의 정지 + 4.4–5.0 ms가 이 구간보다
  짧으면 복구, 길면 거절이다. 그래서 정지 2992 ms 이하는 늘 복구, 2998 ms 이상은 늘 거절이고, 그 사이는 `poll` 타이머가 여유
  구간의 어디서 끝나느냐에 달렸다. 거절 시각은 여유 구간의 앞 끝이나 뒤 끝에 모인다.
  - 반증: 2992 ms 이하에서 거절, 2998 ms 이상에서 복구. 2995 ms에서 뒤 끝 거절. 거절 시각이 2998.8–3002.8 ms 밖이거나, 두 끝
    사이에 10%보다 많이 몰린다.

## 3. 사전 예측

예측 원문은 [predictions.csv](predictions.csv)(측정 14줄, 소스 3줄)이고 해시는 [PREREG.txt](PREREG.txt)에 있다. 이 절의 표는
요약이다. 판정은 `acceptance` 열을 아래 규칙으로 그대로 계산한다.

### 3.0 판정 규칙과 필드

**판정식의 구조.** `acceptance`는 `; `로 나뉜 절의 묶음이고, 모든 절이 참일 때 맞음이다.
- 절은 `[범위:] 식`이다. 범위가 없으면 그 줄의 `cells`에 적힌 셀마다 따로 계산한다. `cells`의 셀은 첫 `:` 앞(없으면 열 전체)에 적힌 셀 키다.
- 범위 `<셀>, <셀>, ...:`는 적힌 셀마다 따로 계산한다. 범위 `pooled <셀>, ...:`는 적힌 셀의 시행을 한 묶음으로 계산한다. 범위 끝에
  `where <조건>`이 있으면 그 조건이 참인 시행만 남긴다.
- 식은 아래 함수를 `and`, `or`, 비교, 사칙연산으로 묶는다.
  - `ALL(e)`: 범위의 시행 모두에서 e가 참.
  - `MOST(e)`: e가 참인 시행이 ceil(0.9 x n) 이상이고, e의 필드가 모두 기록됐는데 거짓인 시행이 0.
  - `NONE(e)`: e가 참인 시행이 0.
  - `COUNT(e)`: e가 참인 시행 수. `N()`: 범위의 시행 수 n. `MAX(e)`, `MIN(e)`: e가 기록된 시행에서 e의 최댓값, 최솟값.
- n은 8절의 제외 뒤 남은 시행 수다. 필드가 없는 시행은 `ALL`에서는 거짓, `COUNT`에서는 세지 않음, `MAX`와 `MIN`에서는 뺀다.
- 결과는 맞음, 틀림, 자료 없음(범위의 n이 0) 셋이다. 놓친 시행은 모두 목록으로 낸다.

**CPU 하네스 필드.** 시행마다 `CP/runs/<tag>/`, `CG/runs/<tag>/`에 `run.sh`가 쓰는 CSV 한 줄과 서버 로그가 있다.
- `sub_cause`, `status`, `vendor_err`, `cqe_ns`(게시부터 첫 CQE까지 ns): live_peer와 같은 열.
- `probe_ms`(새 열): 요청 쪽이 PROBE를 보낸 순간부터 답을 다 읽거나 대기가 끝날 때까지 ms. PROBE를 보내지 않았으면 -1.
- `stall_meas_ms`: 서버 로그의 `stall_end ... measured_ms=` 값. 설정한 정지가 0이면 0.

**GIN 필드.** 시행마다 `G/logs/rec1_F3_timeout_<tag>_{r0.kv,r1.kv,meta.txt}`. live_peer와 같은 정의다.
- `rec_outcome`, `rec_reason`, `rec_t_prep`, `rec_t_ack`, `rec_t_decl`: r0 kv 첫 `rec ev=` 기록의 값(ms, rank 0 시계).
- `fault_t_query`: r0 kv 첫 `fault ev=` 기록의 `t_query`.
- `r0rc`: meta의 `r0rc`.
- `r1_stall_ms`: r1 kv `stall` 기록의 `measured_ms`.
- `r1_stall_end_r0clock`: r1 kv `stall` 기록의 `end_mono_ms` - r0 kv `clock_offset_ms`.
- `r1_n_rxrec_after_stall`: r1 kv에서 `stall` 기록 뒤의 `rxrec` 기록 수.

### 3.1 소스 예측 `[소스]`

| id | 무엇 | 예측 | 근거 |
|---|---|---|---|
| S1 | CPU 하네스 생존 확인 대기 | 1 s `SO_RCVTIMEO`는 250 jiffy, 타이머 휠 단계 1에서 다음 8 jiffy 경계로 올라가 1000–1032 ms 뒤에 끝난다 | `net/core/sock.c:451-453`, `:3024-3031`, `kernel/time/timer.c:129-133`, `:154-168`, `:567-593`, 5.4 `timer.c:492-506`, rain `CONFIG_HZ=250` |
| S2 | GIN rank 0의 `poll` | 타임아웃 t ms에 t/1000 ms 여유: 2998 ms면 [2998.0, 3001.0] ms 안에서 끝난다 | `fs/select.c:53-94`, `:902-907` |
| S3 | GIN 핸드셰이크 마감 | Prepare와 요청 전송 뒤에 걸리고, 두 번 정수로 잘려 `poll(2998)`이 된다. 거절 기록은 abort와 FAIL 뒤다 | `gin_rec.cu:489-500`, `:169-175` |

### 3.2 측정 예측 요약

| id | 셀 | 예측 | 판정 요약(원문은 csv) |
|---|---|---|---|
| CPa | PROBE를 받으면 0, 900, 990 ms 정지 | 모두 살아 있음, 답은 정지 끝 뒤 0–5 ms | 모두 |
| CPb | PROBE를 받으면 1008 ms 정지 | 10회 중 4회 이상 살아 있음(확률 약 0.7) | 개수 |
| CPc | PROBE를 받으면 1024 ms 정지 | 10회 중 6회 이하 살아 있음(확률 약 0.2) | 개수 |
| CPd | PROBE를 받으면 1040, 1100 ms 정지 | 모두 응답 없음, 대기는 1000–1033 ms | 모두 |
| CPe | PROBE 정지 셀 전체 | 시행마다 답(정지 + 0–5 ms)과 대기 끝(1000–1033 ms) 중 먼저 오는 쪽이 판정을 정한다 | 모두 |
| CPf | 응답 없음 시행 전체(두 CPU 묶음) | 대기 끝이 1000–1033 ms에 있고, 퍼짐(최대 - 최소)이 16 ms 이상 | 모두와 퍼짐 |
| CGa | 장애 순간부터 4300, 5000 ms 정지 | 4300 ms는 모두 살아 있음, 5000 ms는 모두 응답 없음 | 모두 |
| CGb | 장애 순간부터 정지한 셀 전체 | 첫 CQE 뒤 남은 정지 x가 995 ms 이하면 살아 있음, 1034 ms 이상이면 응답 없음 | 모두 |
| CGc | 장애 순간부터 정지, 살아 있음 시행 | 답은 PROBE 뒤 (x - 1)–(x + 6) ms 안 | 모두 |
| Ga | GIN, 복구 요청 때 2900, 2985, 2992 ms 정지 | 모두 복구, ACK는 정지 끝 뒤 4.0–5.5 ms | 모두 |
| Gb | GIN, 2995 ms 정지 | 뒤 끝 거절 0, 10회 중 5회 이상 복구, 복구된 ACK는 Prepare 뒤 3001.2 ms 안 | 개수와 모두 |
| Gc | GIN, 2998, 3010, 3100 ms 정지 | 모두 핸드셰이크 시간 초과로 거절, rank 0 종료 코드 9 | 모두 |
| Gd | GIN 거절 시행 전체 | 거절은 장애 조회 뒤 2998.8–3002.8 ms, 두 끝 사이(2999.9–3001.7 ms)는 10% 이하 | 모두와 개수 |
| Ge | GIN 2998 ms의 뒤 끝 거절, GIN 거절 전체 | 2998 ms 뒤 끝 거절에서 rank 1은 거절 전에 이미 깨어 있었다. 거절된 시행마다 rank 1은 깨어난 뒤 요청을 처리한다 | 모두 |

### 3.3 경계 예측(요약) `[추론]`

- CPU 하네스, PROBE를 받을 때 정지: 답이 PROBE 뒤 1000 ms 안에 오면 늘 살아 있음, 1033 ms보다 늦으면 늘 응답 없음. 정지 길이로는
  약 995 ms 이하는 늘 살아 있음, 1033 ms 이상은 늘 응답 없음, 그 사이는 확률적이다(1008 ms에서 약 0.7, 1024 ms에서 약 0.2).
- CPU 하네스, 장애 순간부터 정지: 경계는 정지 길이 = 첫 CQE 시각 + 1000–1032 ms다. 이 하네스의 첫 CQE가 3.49–3.76 s에 퍼져
  있으므로 정지 길이로는 약 4.5–4.8 s다.
- GIN 복구: 경계는 정지 길이 2993.0–2996.6 ms다(앞 끝 2998.0 ms - ACK 4.95 ms - 정지 오차 0.11 ms, 뒤 끝 3001.0 ms - 4.43 ms -
  0.07 ms). 이 구간 안의 판정은 `poll` 타이머가 어디서 끝나느냐에 달렸다.

## 4. 범위

- **포함:**
  - CPU verbs 하네스: 응답 QP 오류 뒤 (가) PROBE를 받는 순간부터 정지, (나) 장애 순간(GOACK 직후)부터 정지. 정지 길이를 바꾼다.
  - GIN GDAKI 복구 v2(번들 `gin_recovery_gpudb_stall`, live_peer와 같은 빌드): 복구 요청을 받는 순간부터 정지. 정지 길이를 바꾼다.
- **제외:**
  - 다른 탐지기(NCCL net_ib 복구 2단계, GIN 투명 복구, NVSHMEM 장애 대응판과 투명 복구): 마감이 5–35 s라 시간이 들고, 이번
    질문(마감의 실제 길이와 경계의 위치)은 두 탐지기로 답할 수 있다.
  - 마감 상수 자체를 바꾸는 시험(`GIN_REC_HANDSHAKE_MS` 등): 이번에는 기본값의 경계만 잰다.
  - 커널 설정(HZ, 타이머 여유)을 바꾸는 시험: 호스트 설정 변경이다.
  - 실제 link down, 링크 흔들기, 재부팅, 드라이버 재적재, 커널 모듈 적재, RoCE 주소 변경, NIC 펌웨어나 스위치 설정 변경.

## 5. 테스트베드와 버전

| 항목 | 값 | 확인 방법과 날짜 |
|---|---|---|
| 노드 | rain(요청, rank 0), sunny(응답, rank 1), 100 GbE RoCE v2 직결 | 루트 `README.md` |
| NIC와 펌웨어 | ConnectX-6, 20.43.4100 | live_peer 5절(2026-10-07). 실행 전 다시 읽는다 |
| rain 커널 | 5.15.0-97, `CONFIG_HZ=250`, `CONFIG_NO_HZ_IDLE=y`, `CONFIG_HIGH_RES_TIMERS=y` | `[측정]` `/boot/config-5.15.0-97-generic`, 2026-10-08 |
| sunny 커널 | 6.8.0-138 | live_peer 5절. 서버 쪽 타이머는 판정에 쓰이지 않는다 |
| GIN 번들 | `~/gi-bundle/gin_recovery_gpudb_stall`: `gin_rec` md5 `fac97c8c`, `libnccl.so.2.32.3` md5 `1ed8e0a1` | `[측정]` 두 노드 md5sum, 2026-10-08 14:03 배포 블록 |
| evrec | `~/gi-bundle/evrec2/evrec` md5 `3f93b3a9`(표본 없이 시작과 끝만) | `[측정]` 두 노드 md5sum, 같은 배포 블록 |
| CPU 하네스 | 소스 커밋 `b5657f88`(master `613003e9` + 9.1절의 변경). rain `probe_client` `a9c481f2`, `probe_server` `c3f24990` / sunny(`~/rdma-error-lb/harness`) `probe_client` `3c06e360`, `probe_server` `413c52e6`. `run.sh`가 시행마다 다시 빌드한다 | `[측정]` md5sum, 같은 배포 블록 |
| 커널 로그 | sunny `dmesg`는 sudo 없이 읽히지 않아 8절대로 rain만 검사한다 | `[측정]` 2026-10-08 14:08 실행기 시작 기록 |

## 6. 변수

- **독립변수:**
  - CPU 하네스 PROBE 정지 길이: 0, 900, 990, 1008, 1024, 1040, 1100 ms.
  - CPU 하네스 장애 순간부터의 정지 길이: 4300, 4600, 5000 ms.
  - GIN 복구 요청 때 정지 길이: 2900, 2985, 2992, 2995, 2998, 3010, 3100 ms.
- **종속변수:**
  - CPU 하네스: 판정(`sub_cause`), PROBE부터 답이나 대기 끝까지 시간(`probe_ms`), 첫 CQE 시각(`cqe_ns`), 도우미가 잰 정지 길이.
  - GIN: 복구 결과와 이유, Prepare 뒤 ACK 시각, 장애 조회 뒤 거절 시각, rank 0 종료 코드, rank 1의 정지 끝 시각(rank 0 시계).
- **통제변수:** live_peer와 같다. IB 타임아웃 14, 재시도 7, PMTU 4096, CPU 하네스 4 KiB 쓰기 하나와 복구 방식 `qp_only`,
  GIN 반복 120, 간격 15 ms, `INJECT=600`, 대기 방식 `timeout`, `WATCHDOG_S=60`, 핸드셰이크 마감 기본값 3000 ms. 시행마다 새
  프로세스 쌍. `cluster_run.sh` 락과 유휴 링크.
- **기준 시각(anchor).**
  - CPU 하네스: PROBE를 보낸 순간(요청 쪽 시계). 정지는 서버가 PROBE를 받는 순간 시작한다. 장애 순간 정지 묶음은 x = 정지 길이 -
    첫 CQE 시각(게시 기준)으로 PROBE 기준으로 옮긴다.
  - GIN: rank 0의 Prepare 끝(`rec_t_prep`). 마감은 그 직후 요청 전송 뒤에 걸린다. 거절 시각은 장애 조회(`fault_t_query`)
    기준으로 잰다(거절 기록에는 `t_prep`이 없다).

## 7. 실험 셀, 반복 수, 대조군

반복 규칙: 점마다 5회, 예측 경계에 가장 가까운 두 점은 10회. 모든 시행은 새 프로세스 쌍이다.

| 셀 | 조건 | 반복 수 | 대조군 여부 |
|---|---|--:|---|
| CP0 | 응답 QP 오류, PROBE 정지 없음(답 시간 기준점) | 5 | 대조 |
| CP900 | PROBE를 받으면 900 ms 정지 | 5 | |
| CP990 | 990 ms | 5 | |
| CP1008 | 1008 ms | 10 | 경계 안 |
| CP1024 | 1024 ms | 10 | 경계 안 |
| CP1040 | 1040 ms | 5 | |
| CP1100 | 1100 ms | 5 | |
| CG4300 | 응답 QP 오류, 장애 순간(GOACK 직후)부터 4300 ms 정지 | 5 | |
| CG4600 | 4600 ms | 10 | 경계 안(시행마다 첫 CQE에 따라 갈림) |
| CG5000 | 5000 ms | 5 | |
| G2900 | GIN 상대 QP 오류, 복구 요청을 받으면 2900 ms 정지 | 5 | |
| G2985 | 2985 ms | 5 | |
| G2992 | 2992 ms | 5 | |
| G2995 | 2995 ms | 10 | 경계 안 |
| G2998 | 2998 ms | 10 | 경계 바로 위 |
| G3010 | 3010 ms | 5 | |
| G3100 | 3100 ms | 5 | |

합계: CPU 하네스 65회(PROBE 정지 45, 장애 순간 정지 20), GIN 45회, 모두 110회. smoke는 점마다 1회(17회)이고 채점하지 않는다.
CPU 하네스의 장애 순간 정지 묶음은 경계 안 점이 하나뿐이라 그 점을 10회로 둔다.

## 8. 제외 기준과 중단 기준

- **제외 기준:**
  - smoke 실행(`results/<날짜>_smoke/`)은 채점하지 않는다.
  - **장애 미적용:** CPU 하네스 시행의 서버 로그에 `fault_applied`가 없거나, 정지가 0이 아닌데 `stall_end` 기록이 없는 시행.
    GIN 시행의 r0 kv에 `fault ev=` 기록이 없거나 r1 kv에 `stall` 기록(`end_mono_ms` 포함)이 없는 시행. 따로 센다.
  - **실행기 실패:** CSV 행이나 kv가 없는 시행. 따로 센다.
  - 위 두 경우만 실행기가 셀 끝에서 자동으로, 결과 필드를 보지 않고 같은 설정의 추가 시행으로 채운다. 셀마다 계획 n의 30%(올림)까지.
- **중단 기준과 안전 규칙:**
  - 모든 클러스터 명령(배포, smoke, 본 실행)은 `harness/gpu-initiated/common/cluster_run.sh -w 10800` 안에서 돈다. GIN pair-check
    실험이 같은 락을 쓰므로 대기 상한을 10800 s로 둔다. 상한 안에 락이나 유휴 링크를 얻지 못하면 그 묶음을 미룬다. `prio-` 작업이
    기다리면 양보한다.
  - 하지 않는 일: 실제 link down이나 링크 흔들기, 재부팅, 드라이버 재적재, 커널 모듈 적재, RoCE 주소 변경, NIC 펌웨어나 스위치
    설정 변경, 커널 설정 변경.
  - 프로세스는 우리가 띄운 것만, 정확한 이름(`probe_server`, `probe_client`, `gin_rec`, `lp_stall`, `evrec`) 일치나 PID로 끈다.
    `SIGSTOP`은 `lp_stall` 도우미가 자기 부모에게만 보낸다. 시행을 끝내기 전에 두 노드에서 그 이름의 프로세스 중 정지 상태(`ps` 상태
    `T`)인 것에 `kill -CONT`를 먼저 보낸다. 다른 사용자의 작업은 건드리지 않는다.
  - 시행 뒤 5 s가 지나도 우리 프로세스가 남아 있으면 캠페인을 멈춘다. 그 PID에만 `kill -CONT`, `kill`을 보낸다.
  - 커널 로그: 캠페인 시작 전과 시행마다 rain의 `dmesg`에서 mlx5 명령 오류 줄 수를 센다(정규식
    `mlx5.*(mlx5_cmd_out_err|mlx5_cmd_check|wait_func|cmd_work_handler|failed, status|Will cause a leak)`). 줄 수가 늘면 즉시
    멈춘다. sunny는 sudo 없이 `dmesg`가 읽히면 같은 검사를 하고, 읽히지 않으면 12절에 적고 rain만 검사한다.
  - 포트가 ACTIVE가 아니게 되면 즉시 멈춘다.
  - 복구 뒤 검증 실패(`verify_ok=0`)나 GIN `data_check` 실패가 나오면 멈춘다. 그 시행은 그대로 채점한다.
  - 멈춘 뒤 재개는 13절(또는 `DEVIATIONS.md`)에 날짜, 이유, 영향 범위를 적은 뒤에만 한다.

## 9. 실행 방법과 경로

### 9.1 재사용과 변경

- **재사용:** `lp_stall` 도우미(`harness/common/lp_stall.h`), CPU 하네스 실행기(`harness/run.sh`), live_peer의 셀 실행 방식과 안전
  검사(`../run_cells.sh`), evrec 감싸기(`gpu-initiated/propagation/campaign/evrec_pair.sh`, `EVREC_BIN=~/gi-bundle/evrec2/evrec`,
  표본 없음), GIN 실행기(`gin_recovery/scripts/run_trial.sh`)와 번들 `gin_recovery_gpudb_stall`. 새 라이브러리 빌드와 새 GIN 드라이버
  빌드는 없다.
- **CPU 하네스 변경(빌드는 `run.sh`가 시행마다):**
  - `probe.h`, `probe.c`: 새 장애 `live_stop_probe`.
  - `probe_server.c`: GO에서 QP를 ERR로, GOACK, `fault_applied` 기록. 첫 PROBE를 받으면 `LIVE_STOP_MS`가 0보다 클 때
    `lp_stall_self(LIVE_STOP_MS)`로 멈춘 뒤 `stall_begin`, `stall_end` 기록을 쓰고 평소처럼 PROBED를 답한다.
  - `probe_client.c`: `live_stop_probe`는 `live_stop_err`처럼 다룬다(쓰기 하나, 판정 뒤 RESYNC). 모든 장애에서 PROBE 전송부터 답이나
    대기 끝까지를 `now_ns()`로 재서 새 열 `probe_ms`에 쓴다(CSV 끝).
  - 장애 순간 정지 묶음은 기존 `live_stop_err`에 `LIVE_STOP_MS`만 바꿔 쓴다.
- **새 파일(이 폴더):** `run_points.sh`(점과 반복 실행, live_peer `run_cells.sh`의 안전 검사와 추가 시행 규칙을 그대로 옮김),
  `deploy.sh`(sunny에 이 실험의 하네스 사본 `~/rdma-error-lb/harness`를 만들고, 두 노드의 GIN 번들과 evrec2 md5를 확인),
  `score.py`(3.0의 규칙 구현), `qa/`.
- sunny의 하네스 사본은 새 경로 `~/rdma-error-lb/harness`에 둔다. live_peer의 사본과 공용 `~/rdma-error`는 건드리지 않는다.

### 9.2 실행

- 셀 하나의 시행(tag는 CPU PROBE 정지 `lb_cp<ms>_t<n>`, CPU 장애 순간 정지 `lb_cg<ms>_t<n>`, GIN `g<ms>_t<n>`):

```
# CPU, PROBE를 받을 때 정지 (출력 <out>/CP/), 장애 순간 정지는 live_stop_probe 대신 live_stop_err (출력 <out>/CG/)
env RESULTS_DIR=<out>/CP/runs/<tag> ITERS=1 LIVE_STOP_MS=<ms> SERVER_DIR='~/rdma-error-lb/harness' \
    SERVER_LOG=/tmp/lb_probe_srv.log bash harness/run.sh live_stop_probe
# GIN, 복구 요청을 받을 때 정지 (출력 <out>/G/)
env BUNDLE=$HOME/gi-bundle/gin_recovery_gpudb_stall REC=1 CLASSIFY=1 INJECT=600 WATCHDOG_S=60 \
    EXTRA_ENV="GIN_REC_TEST_STALL_MS=<ms> GIN_REC_TEST_STALL_ON=req" \
    bash harness/gpu-initiated/gin_recovery/scripts/run_trial.sh F3 timeout <tag> <out>/G/logs 120 14
```

- 묶음(모두 락 안): `cluster_run.sh -w 10800 -t lb-deploy`, `-t lb-smoke`, `-t lb-cpu`, `-t lb-gin`.
- 채점: `score.py results/<날짜>`가 `SCORE.md`, `trials_scored.csv`를 쓴다. 다른 에이전트가 원자료에서 다시 센다.
- 출력: `results/<날짜>/`에는 해설과 인용한 표만 두고 원자료는 Release에 올린다.
- 예상 클러스터 시간: `[측정]` live_peer에서 CPU 하네스 시행은 평균 8.9 s(95회 14분), GIN 시행은 13.6 s(30회 6분 48초)였다.
  CPU 65회 약 11분, GIN 45회 약 11분, smoke 17회 약 4분, 유휴 확인과 배포 약 3분. 락을 잡는 시간은 모두 약 30분이다.

## 10. 완료 조건과 QA 기준

- [ ] 17셀이 계획한 반복 수만큼 실행됐다. 장애 미적용, 실행기 실패, 추가 시행을 따로 센 표가 있다.
- [ ] 측정 예측 14줄마다 판정과 놓친 시행 목록이 있다.
- [ ] 경계 위치(CPU 대기 끝의 분포, GIN 복구와 거절이 갈리는 정지 길이)를 다른 에이전트가 원자료에서 다시 계산했다.
- [ ] smoke와 제외 시행이 결과에 섞이지 않았다. 여러 시행의 범위와 대표 시행의 범위를 구분했다.
- [ ] 원자료를 Release에 올리고 `DATA.md`에 적었다.
- [ ] `MODEL.md` 규칙 3의 한계("경계 자체는 재지 않았다")를 결과에 맞게 고칠 초안을 만들었다(고치는 것은 사용자 확인 뒤).

## 11. 작업 체크리스트

- [x] 질문, 가설, 셀 작성 (`DRAFT`)
- [x] 고정 절 완성, 상태 `PREREGISTERED`, 해시 기록을 커밋 하나로 만들고 그 커밋에 `prereg/` 태그
- [x] 계측과 실행기 구현(`live_stop_probe`, `probe_ms`, `run_points.sh`, `deploy.sh`, `score.py`), 빌드. 독립 리뷰는 하지 않았고 smoke와 가짜 자료로 채점기를 시험했다
- [x] 배포
- [x] smoke 실행(채점 제외)
- [x] 본 실행 (`RUNNING`)
- [ ] 채점과 재계산 (`QA`): 채점은 끝남(14:40). 독립 재계산은 다른 에이전트가 한다
- [ ] 결과 정리, 원자료 릴리스, PR
- [ ] 결론 확정 (`COMPLETE`)

## 12. 실행 기록 (시간순)

| 시각 | 무엇을 했나 | 결과와 근거(경로, 커밋, 실행 ID) |
|---|---|---|
| 2026-10-08 13:45–14:00 | 설계: 커널 소스(리눅스 6.10.8, 5.4)에서 소켓 타임아웃의 jiffy 변환, 타이머 휠 반올림, `poll` 여유를 읽고 GIN 드라이버의 마감 경로를 다시 읽음. rain의 `CONFIG_HZ` 확인 | 1.2, 3.1 |
| 2026-10-08 13:47–13:50 | Release `data-20261007`의 live_peer 원자료를 받아 체크섬 확인, GIN의 Prepare 시간, ACK 지연, 정지 오차, 거절 시각, CPU 하네스의 첫 CQE 시각을 다시 셈 | 1.2 |
| 2026-10-08 13:57:38 | 사전 등록 | [PREREG.txt](PREREG.txt), 태그 `prereg/live-boundary-v1` |
| 2026-10-08 13:58–14:01 | 구현과 빌드: `live_stop_probe` 장애와 `probe_ms` 열, `run_points.sh`, `deploy.sh`, `score.py`. 빌드됨(`-Werror`). 채점기는 가짜 자료로 모든 판정식이 계산되는 것을 확인 | 커밋 `b5657f88`, `67a9c668`. 구현 결정은 [DEVIATIONS.md](DEVIATIONS.md) 1–4 |
| 2026-10-08 14:03:34–14:03:37 | 배포 블록(`lb-deploy`, 락 대기 14:01–14:03). sunny에 `~/rdma-error-lb/harness`를 만들고 빌드. GIN 정지 번들과 evrec2의 md5가 두 노드에서 사전 등록 값과 같음. 블록 뒤 정지 상태와 남은 프로세스 없음, rain dmesg mlx5 명령 오류 줄 2(이전 것)에서 그대로 | 5절의 md5 |
| 2026-10-08 14:08:00–14:09:36 | smoke CPU(`lb-smoke-cpu`), 점마다 1회, 10회. 러너 rc 모두 0, 따로 센 시행 없음. 블록 뒤 검사 같음. sunny dmesg는 sudo 없이 읽히지 않음 | `results/20261008_smoke/CP/`, `CG/`(채점 제외) |
| 2026-10-08 14:14:27–14:16:04 | smoke GIN(`lb-smoke-gin`), 점마다 1회, 7회. 러너 rc 모두 0, 따로 센 시행 없음. 블록 뒤 검사 같음 | `results/20261008_smoke/G/`(채점 제외) |
| 2026-10-08 14:16:29 | 본 실행 시작. CPU(`lb-cpu`)와 GIN(`lb-gin`)을 각각 `cluster_run.sh -w 10800` 블록으로 대기열에 넣음. 상태 `RUNNING` | `results/20261008/` |
| 2026-10-08 14:17:45–14:28:09 | 본 실행 CPU(`lb-cpu`, 락 대기 14:16–14:17). PROBE 정지 45회, 장애 순간 정지 20회. 러너 rc 모두 0, 추가 시행 0, 따로 센 시행 0, 중단 없음. 정지 시행 60회 모두 sunny `probe_server`의 상태 `T`를 관측. 블록 뒤 정지 상태와 남은 프로세스 없음, rain dmesg mlx5 명령 오류 줄 2에서 그대로 | `results/20261008/CP/`, `CG/`(`trials.log`, `runner_CPU.log`, Release 예정) |
| 2026-10-08 14:28:40–14:38:57 | 본 실행 GIN(`lb-gin`, 락 대기 14:28:09–14:28:40). 45회, 러너 rc 모두 0, 추가 시행 0, 따로 센 시행 0, 중단 없음. 블록 뒤 검사 같음 | `results/20261008/G/`(`trials.log`, `runner_GIN.log`, Release 예정) |
| 2026-10-08 14:40 | 채점(`score.py results/20261008`): 측정 예측 14줄 중 12줄 맞음, 2줄 틀림. 상태 `QA` | [SCORE.md](results/20261008/SCORE.md), [trials_scored.csv](results/20261008/trials_scored.csv) |

## 13. 사전 등록 이후 변경

변경과 구현 결정은 [DEVIATIONS.md](DEVIATIONS.md)에 있다. 예측, 판정식, 셀, 반복 수, 제외와 중단 기준을 바꾼 항목은 없다.

## 14. 원자료와 결과표

| 무엇 | 경로 또는 Release 자산 | n |
|---|---|--:|
| CPU PROBE 정지 원자료: 시행마다 CSV와 서버 로그(`runs/<tag>/`), 실행 로그와 정지 상태 기록(`logs/`), evrec(`evrec/`), `trials.log` | `results/20261008/CP/`(커밋하지 않음, Release 예정) | 45회 |
| CPU 장애 순간 정지 원자료(같은 구성) | `results/20261008/CG/`(Release 예정) | 20회 |
| GIN 원자료: 두 rank의 kv, meta, 로그(`logs/`), evrec(`evrec/`), `trials.log` | `results/20261008/G/`(Release 예정) | 45회 |
| 실행기 기록 | `results/20261008/runner_CPU.log`, `runner_GIN.log`(Release 예정) | 2 |
| smoke(채점 제외) | `results/20261008_smoke/`(Release 예정) | 17회 |
| 채점 결과 | [results/20261008/SCORE.md](results/20261008/SCORE.md) | 14줄 |
| 시행별 값 | [results/20261008/trials_scored.csv](results/20261008/trials_scored.csv) | 110회 |

## 15. 결과 요약

본 실행 110회(CPU 65, GIN 45, 2026-10-08 14:17–14:39)의 결과다. 따로 센 시행과 추가 시행은 없다. smoke는 넣지 않았다.
모두 `[측정]`이고 해석에는 `[추론]`을 붙였다. 판정은 [SCORE.md](results/20261008/SCORE.md), 시행별 값은
[trials_scored.csv](results/20261008/trials_scored.csv)에 있다. 범위는 따로 적지 않으면 그 점(또는 적은 묶음) 시행들의
최솟값–최댓값이다. 독립 재계산 전 값이다.

**예측 판정: 측정 14줄 중 12줄 맞음, 2줄 틀림.** 틀린 두 줄은 아래 3번과 4번 끝에 있다.

**1. CPU 하네스의 생존 확인 마감은 1000 ms가 아니라 그 뒤 약 30 ms 폭에 퍼져 있다(가설 1).**
- 응답 없음으로 끝난 시행 28회(PROBE 정지 20, 장애 순간 정지 8)의 대기 끝: 1001.6–1027.1 ms, 퍼짐 25.5 ms. 1000 ms보다 이른
  것도, 1033 ms보다 늦은 것도 없다.
  - `[추론]` 1 s 타임아웃이 타이머 휠에서 32 ms 간격으로 올림된다는 소스 예측과 맞다. 다만 고른 분포라면 28회 중 최댓값이
    1027.1 ms 이하일 확률은 약 1%다. 위쪽 5 ms가 비어 있는 이유는 확인하지 않았다 `[미확인]`.
- 정지 길이별 판정(PROBE를 받는 순간부터 정지):
  - 0, 900, 990 ms: 살아 있음 15/15.
  - 1008 ms: 살아 있음 9/10(예측 4회 이상). 응답 없음 1회는 대기가 1001.6 ms에 끝났다.
  - 1024 ms: 살아 있음 1/10(예측 6회 이하). 살아 있음 1회는 답이 1025.0 ms에 왔고 그보다 대기가 길었다.
  - 1040, 1100 ms: 응답 없음 10/10. 대기 끝은 1002.2–1026.6 ms.
- 시행마다 "답과 대기 끝 중 먼저 오는 쪽"으로 판정이 정해졌다(45/45). 답을 받아들인 가장 늦은 시각은 PROBE 뒤 1025.0 ms였다.
- **정지가 끝난 뒤 답이 오기까지(사전 등록 뒤 처음 잰 값).** 사전 등록은 0–5 ms를 허용했다.
  - 정지 없는 점: PROBE부터 답까지 0.710–0.756 ms(n=5). 서버의 PROBE 처리(포트 카운터 두 번, 포트 상태 조회)와 왕복을 합한 값이다.
  - 정지한 점에서 답 - 정지 길이: 0.934–1.053 ms(n=20, 900, 990, 1008, 1024 ms 점의 살아 있음 시행).
  - `[추론]` 허용폭 5 ms보다 4 ms 남짓 작다. 경계는 사실상 "PROBE 뒤 1000–1027 ms에 끝나는 대기에서 약 1 ms를 뺀 정지 길이"다.

**2. 장애 순간부터 멈춘 상대의 경계는 첫 CQE + 실제 마감이다(가설 2).**
- 4300 ms 정지: 살아 있음 5/5. 5000 ms 정지: 응답 없음 5/5. 4600 ms 정지: 살아 있음 7, 응답 없음 3.
- 첫 CQE 뒤 남은 정지 x: 살아 있음 시행은 596.7–921.6 ms(n=12), 응답 없음 시행은 1014.2–1476.8 ms(n=8). x ≤ 995 ms인 시행은
  모두 살아 있음(12/12), x ≥ 1034 ms인 시행은 모두 응답 없음(6/6)이었다. 그 사이(1014.2, 1032.6 ms) 두 시행은 응답 없음이었다.
- 첫 CQE 시각은 65회를 합쳐 3501.5–3746.2 ms였다. `[추론]` 그래서 이 하네스에서 장애 순간부터 멈춘 상대가 오판되기 시작하는
  정지 길이는 약 4.5–4.8 s다.
- **틀림(CGc): 살아 있음 시행의 답 시각.** 예측은 PROBE 뒤 (x - 1)–(x + 6) ms였다. 11회는 x + 1.03–1.13 ms였지만 `lb_cg4600_t6`은
  x + 11.86 ms였다.
  - 원인 `[측정]`: 이 시행에서 서버의 정지는 GOACK 뒤 10.85 ms에 시작했다(서버 로그의 `fault_applied`와 `stall_begin`). 다른 19회는
    0.06–0.14 ms였다. x는 정지가 GOACK 직후 시작한다고 보고 정의했으므로 이 시행의 실제 남은 정지는 x보다 10.85 ms 길었다. 이것을
    빼면 답은 x + 1.00 ms다.
  - `[미확인]` 정지 시작이 왜 늦었는지(서버 쪽 스케줄링 등)는 확인하지 않았다.

**3. GIN 복구의 경계는 정지 2992 ms와 2998 ms 사이다(가설 3).**
- 정지 길이별 결과:
  - 2900, 2985, 2992 ms: 복구 15/15. ACK는 정지 끝 뒤 4.51–4.88 ms(n=15).
  - 2995 ms: 복구 9/10, 거절 1/10. 복구된 ACK는 Prepare 뒤 2999.68–3000.07 ms. 거절 1회는 장애 조회 뒤 2999.19 ms로 여유 구간의 앞
    끝이었다. 뒤 끝 거절은 0이다.
  - 2998, 3010, 3100 ms: 핸드셰이크 시간 초과로 거절 20/20, rank 0 종료 코드 9 20/20.
- 2998 ms의 뒤 끝 거절 9회에서 rank 1은 rank 0이 거절하기 2.53–2.80 ms 전에 이미 깨어나 있었다(rank 0 시계). 거절된 21회 모두에서
  rank 1은 깨어난 뒤 요청을 처리했다.
  - `[추론]` 상대가 이미 살아 움직이는데 ACK가 마감보다 1–2 ms 늦어 복구 불가로 판정되는 경우다. 경계 근처의 오판은 상대의 정지보다
    응답에 드는 4.5–4.9 ms의 일 때문에 생긴다.
- **틀림(Gd): 거절 시각의 분포.** 거절 21회는 모두 장애 조회 뒤 2998.8–3002.8 ms 안이었다(2999.19–3002.22 ms). 그러나 두 끝 사이
  (2999.9–3001.7 ms)에 5회(24%)가 있어 예측(10% 이하)을 넘었다. 앞 끝 1회, 뒤 끝 15회다.
  - `[추론]` `poll` 타이머는 여유 구간의 두 끝에서만이 아니라 구간 안 어디서든 끝날 수 있다(다른 인터럽트가 구간 안에 오면 그때
    만료된다). live_peer의 10회에서 두 끝만 본 것은 표본이 작았던 탓으로 보인다. 소스에서 나온 범위(2998.0–3001.0 ms 뒤 만료)는 맞았다.

**4. 경계를 소스로 맞혔는가.**
- CPU 하네스: 정지 990 ms 이하는 늘 살아 있음, 1040 ms 이상은 늘 응답 없음, 그 사이는 확률적이라는 예측대로였다. 경계 폭(약 30 ms)은
  커널 타이머의 올림 간격에서 나왔다.
- GIN: 2992 ms 이하는 늘 복구, 2998 ms 이상은 늘 거절, 2995 ms는 섞인다는 예측대로였다.
- 틀린 두 줄은 경계의 위치가 아니라 기준 시각의 정의(장애 순간 정지의 시작 지연)와 `poll` 만료 위치의 분포에 대한 것이었다.

## 16. QA와 재현성

> 누가(사람 또는 에이전트) 무엇을 다시 셌고 무엇이 맞거나 달랐는지. 재현에 필요한 빌드와 커밋.

## 17. 결론

## 18. 한계

## 19. 다음 작업

## 20. 참고자료

- T. D. Chandra, S. Toueg. Unreliable Failure Detectors for Reliable Distributed Systems. JACM 1996.
- W. Chen, S. Toueg, M. K. Aguilera. On the Quality of Service of Failure Detectors. IEEE TC 2002.
- T. Gleixner. timers: Switch to a non-cascading wheel (리눅스 4.8, `kernel/time/timer.c`의 단계별 간격 표).
- 이 저장소: [../EXPERIMENT.md](../EXPERIMENT.md), [../../../MODEL.md](../../../MODEL.md),
  [../../gpu-initiated/gin_recovery/RECOVERY_DESIGN.md](../../gpu-initiated/gin_recovery/RECOVERY_DESIGN.md).
