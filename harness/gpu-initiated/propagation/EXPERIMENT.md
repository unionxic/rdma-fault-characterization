# 교차 계층 오류 전파 측정 (propagation)

> **이 문서의 지위.** 이 `EXPERIMENT.md`는 캠페인 실행 도중(2026-10-06)에 도입한 진행 관리
> 문서이며, 그 자체는 사전 등록 산출물이 아니다. 변경할 수 없는 사전 등록 근거는 태그
> `prereg/propagation-v1`의 다음 네 파일이다.
> - [PREDICTIONS.md](PREDICTIONS.md)
> - [predictions.csv](predictions.csv)
> - [REVIEW_20261006.md](REVIEW_20261006.md)
> - [PREREG.txt](PREREG.txt)
>
> 이 문서와 그 파일들이 다르면 태그의 파일이 맞다.

**목적:** 같은 RDMA 장애가 NIC, CQE, 장치 코드, 라이브러리/API, 호스트, 정리(teardown) 단계에서
어떻게 전달되고 합쳐지거나 사라지는지 측정해, 사전 등록한 예측과 비교한다.

| 항목 | 값 |
|---|---|
| 상태 | `COMPLETE` |
| 담당자 | @unionxic |
| 작성일 | 2026-10-06 (이 문서). 사전 등록은 2026-10-06 12:52 |
| 기준 브랜치와 커밋 | 캠페인 실행 커밋 `3eb87407`(로컬 `exp/propagation-campaign`, 트리가 master `c68a981f`와 같음). 문서 작성 시점 master는 `a67d1991` |
| 사전 등록 태그 | `prereg/propagation-v1` → `ddade612` (2026-10-06 13:09) |
| 마지막 갱신 | 2026-10-06 18:45, 계층별 표와 독립 검증, 원자료 릴리스, 결과 요약과 결론 |

표시: `[측정]` 원자료에서 확인, `[추론]` 해석, `[미확인]` 확인 안 함.

## 1. 배경과 연구 질문

- 기존 결과를 다시 정리한 [REVIEW_20261006.md](REVIEW_20261006.md)와 그 근거인
  [review_20261006/](review_20261006/)의 리뷰 네 개가 출발점이다.
  - 장애 F0~F4를 계층 L0~L5에서 얼마나 구분할 수 있는지(분할)를 스택마다 정리했다.
  - 빈 칸도 함께 정리했다. 예: F0 대조, 비동기 이벤트, 수동 쪽(상대 rank), 정리 시간.
- 질문:
  1. 장애 정보가 계층마다 얼마나 전달되는가(전파율). 원인을 몇 가지로 구분할 수 있는가(분할).
  2. 위 계층에서 구분이 늘어나는 것은 새 정보 채널이 더해질 때뿐인가.
  3. DEVX로 만든 QP(GDAKI, NVSHMEM)에는 QP 비동기 오류 경로가 없는가.
  4. 단방향(one-sided) 통신의 수동 쪽은 오류를 알 수 있는가.

## 2. 가설

사전 등록 문서 [PREDICTIONS.md](PREDICTIONS.md)의 "What would count against the frame"이
원문이다. 요약하면 이렇다.

- 원본 스택에서 정보는 위로 갈수록 줄기만 한다. 아래 계층보다 위 계층의 분할이 더 잘게 나뉘는 것은
  새 채널이 더해질 때뿐이다.
- DEVX QP 스택에는 QP 비동기 오류가 생기지 않는다.
- 단방향 GIN의 수동 쪽 API는 오류를 받지 못한다. 양방향 net_ib는 받는다.
- CQE가 생기는지는 doorbell record가 정한다. 누가 doorbell을 울리는지와는 상관없다.

## 3. 사전 예측

고정된 원문: [PREDICTIONS.md](PREDICTIONS.md), [predictions.csv](predictions.csv) (예측 24칸),
해시: [PREREG.txt](PREREG.txt). 이 문서에 복사하지 않는다. 묶음은 이렇다.

| 묶음 | 칸 id | 무엇을 예측하나 |
|---|---|---|
| CPU 응답 쪽 이벤트와 QP 상태 | EV1a~e, EV2a~b | 어떤 장애에서 응답 쪽 QP가 ERR이 되고 비동기 이벤트를 받는가 |
| GIN proxy 수동 쪽 | EV3a~c | 수동 쪽 로그에는 오류가 남지만 API는 모른다 |
| DEVX 스택의 비동기 오류 | EV4 | 모든 시행에서 없다 |
| 포트 카운터 | EV5a~d | DEVX 스택은 +0, verbs 스택은 증가 |
| NCCL net_ib F2 | NET1a~c | 수동 쪽 API까지 오류가 간다. 복구 2단계(Stage 2)는 거절한다 |
| GDAKI doorbell | D1, D2 | GPU doorbell에서도 CQE가 생기고, blocking 대기는 실패를 성공으로 보고한다 |
| 정리 단계 | 정리 예측 T1~T4 | F0에서는 5 s 안에 돌아온다. 공식 3.8.0 F4에서는 finalize가 30 s 넘게 멈춘다 |

판정 기준(사전 등록): 칸마다 시행의 90% 이상이 예측과 같고, 예측 밖 결과가 하나도 없을 것. "모든
시행"으로 적힌 칸은 전부 맞아야 한다.

## 4. 범위

- **포함:**
  - mlx5 기반 GPU-initiated RDMA 스택: NCCL GIN proxy/GDAKI, GDAKI + 장치 쪽 분류기, NVSHMEM IBGDA
    (공식 v3.8.0-0, devel, FT v2.2)
  - 기준선: CPU verbs harness, NCCL 2.23.4 net_ib
- **제외:**
  - 실제 link down과 주소 재설정 장애: 공유 링크라서 하지 않는다.
  - mlx5가 아닌 NIC
  - DeepEP: SM90이 필요하다.
  - 진행 중인 투명 복구 작업(GIN 2단계, NVSHMEM): 아직 결과가 아니다.

## 5. 테스트베드와 버전

| 항목 | 값 | 확인 방법과 날짜 |
|---|---|---|
| 노드 | rain(요청, rank 0), sunny(응답, rank 1) | |
| NIC와 펌웨어 | ConnectX-6 VPI, fw 20.43.4100 (두 노드) | `[측정]` sysfs `fw_ver`, 2026-10-06 15:40 |
| 커널, OFED | rain 5.15.0-97, OFED 23.10-7.1.8 / sunny 6.8.0-138, OFED 25.10-1.7.1 | `[측정]` `uname -r`, `ofed_info -s`, 같은 시각 |
| GPU와 드라이버 | rain Quadro RTX 5000, 570.211.01 / sunny RTX A4000, 580.178.04, PeerMappingOverride=1 | `[측정]` `nvidia-smi`, `/proc/driver/nvidia/params`, 같은 시각 |
| CUDA | 12.8 | `[측정]` `nvcc --version` |
| 라이브러리 | NCCL 2.32.3 GIN 번들, NCCL 2.23.4 net_ib(F2 훅 빌드 md5 9ed03e1d), NVSHMEM v3.8.0-0 원본과 수정본(ibgda 플러그인 md5 4aa4dda2, e5935238), devel 7bb2e99, FT v2.2 번들 | 빌드 기록은 각 PR(#13, #15)과 `../nvshmem_rootcause/official380/README.md`. 캠페인 시점 번들 md5 재확인은 `[미확인]` |
| 배포한 도구 | evrec, nvs_kill_repro, gin_fault, gin_q4 | `[측정]` `campaign/deploy.sh` 출력에서 두 노드 md5 일치, 2026-10-06 캠페인 전 |

## 6. 변수

- **독립변수:**
  - 스택과 변형(CPU, GP, GG, GQ, NC, NG, NX, ND, NF, NET)
  - 장애(F0~F4, CPU의 rem_inv_req, rnr, partial_write)
  - 대기 방식(timeout/blocking)
- **종속변수(계층별 관측):**
  - L0: 응답 쪽 QP 상태, 포트 `hw_counters` 변화
  - L1: 오류 코드(status와 vendor_err)
  - L2: 장치 코드나 프록시가 얻은 결과
  - L3: API 반환
  - L4: 비동기 이벤트, 호스트 오류와 로그
  - L5: 양쪽 rank의 정리 시간
- **통제변수:**
  - IB 타임아웃 14, 재시도 7, PMTU 4096
  - 시행마다 프로세스 쌍을 새로 띄운다
  - `cluster_run.sh` 락과 링크 유휴 확인
  - GIN 정리 상한 30 s

## 7. 실험 셀, 반복 수, 대조군

셀과 반복 수의 원문은 [campaign/cells.sh](campaign/cells.sh)다(사전 등록의 반복 규칙: 새 칸 10, 재현 칸 5,
F0 5).

| 스택 | 셀(장애:대기:반복) | 합계 | 대조군 |
|---|---|--:|---|
| cpu | none 5, local_qp_err, rem_access, rem_inv_req, rnr, retry_server_qp_err, retry_proc_sigkill, partial_write 각 10 | 75 | none |
| gp | none:timeout 5, F1~F4:timeout 각 10 | 45 | none |
| gg | none:timeout 5, F1:blocking 5, F2~F4:blocking 각 10 | 40 | none |
| gq | none:timeout 5, F1~F3:blocking 각 5, F4:timeout 5 | 25 | none |
| nvo | {NC, NG, NX} x {kill 0, kill 1} 각 5, FINALIZE=1 | 30 | kill 0 |
| nvd | {auto, cpu_host_memory} x {F1, F2b, F3} 각 10 | 60 | 없음 |
| nvf | none, F1, F2b, F3, F4 각 5 | 25 | none |
| net | T0s 5, F2 10, F2stock 10 | 25 | T0s, F2stock(복구 끔) |

## 8. 제외 기준과 중단 기준

- **제외 기준:**
  - 사전 등록 문서에는 따로 정한 제외 기준이 없다.
  - 사전 등록 뒤 [DEVIATIONS.md](DEVIATIONS.md)에 정한 것: smoke 실행은 채점에서 뺀다(1번). F4에서 죽은
    응답 쪽은 관측 불가로 따로 센다(4번).
  - 채점기는 필요한 출력이 없는 시행을 "관측 불가"로 세고 판정에서 뺀다.
- **중단 기준:**
  - 사전 등록 문서에는 없다.
  - 실제로 적용되는 것은 세 가지다. `cluster_run.sh`가 락이나 유휴 링크를 3600 s 안에 얻지 못하면
    포기한다. 스택마다 `timeout` 상한이 있다([results/20261006_campaign/run_all.sh](results/20261006_campaign/run_all.sh)).
    다른 사용자의 `prio-` 작업이 기다리면 양보한다.

## 9. 실행 방법과 경로

- **배포:** [campaign/deploy.sh](campaign/deploy.sh). evrec, kill_repro, GIN 드라이버를 빌드하고 두
  노드에 복사한다.
- **시행 감싸기:** [campaign/evrec_pair.sh](campaign/evrec_pair.sh). 시행마다 두 노드에서 evrec을
  켜고 끈다.
- **셀 실행:** [campaign/cells.sh](campaign/cells.sh) `<stack> <outroot>`. 스택마다
  `cluster_run.sh` 안에서 돈다. 캠페인 전체는
  [results/20261006_campaign/run_all.sh](results/20261006_campaign/run_all.sh).
- **채점:** [campaign/score.py](campaign/score.py) `<campaign_root> [--old-gin <dir>]`. 24칸에 사전 등록
  판정 기준을 적용해 `SCORE.md`와 `score.json`을 쓴다. `--old-gin`은 2026-09-23 GIN 로그로 EV3a의
  블라인드 부분을 채점한다.
  - score.py는 로컬 커밋 `9effa191`에만 있고 아직 push하지 않았다.
  - 2026-10-06 16:40 1차 채점, 17:15 최종 채점을 했다(16절). 최종 채점 명령은
    `score.py results/20261006_campaign --f4-rerun results/20261006_f4rerun --old-gin <2026-09-23 GIN 결과 폴더>`다.
  - 계층별 전파율과 분할 표는 아직 구현하지 않았다.
- **입력:** 위 스크립트와 `~/gi-bundle`의 배포본.
- **출력:**
  - [results/20261006_campaign/](results/20261006_campaign/): 채점 결과, 계층별 표, 독립 검증 기록. 스택별
    `trials.log`, 표, 로그, evrec 기록은 Release `data-20261006`의
    `harness__gpu-initiated__propagation__results__20261006_campaign.tar.xz`에 있다.
  - smoke: `results/20261006_smoke/`, 채점 제외. 원자료는 Release `data-20261006`의 `harness__gpu-initiated__propagation__results__20261006_smoke.tar.xz`.

## 10. 완료 조건과 QA 기준

- [x] 8개 스택이 7절의 반복 수만큼 실행됐다. 러너 종료 코드 0은 실험 성공이 아니므로 따로 확인한다.
  (325/325회. gp, gg의 F4 20회는 장애가 걸리지 않아 다시 돌렸다. DEVIATIONS 10, 16절)
- [x] `score.py`로 24칸을 모두 판정했다. 놓친 시행이 목록으로 있다. (최종, 16절)
- [x] EV3a 블라인드 부분(2026-09-23 로그 6개)을 채점했다. (`v2/logs/`, DEVIATIONS 11)
- [x] 계층별 전파율과 분할 표를 만들어 [REVIEW_20261006.md](REVIEW_20261006.md)의 예측 분할과
  비교했다.
- [x] 핵심 수치를 채점기와 다른 경로로 원자료에서 다시 셌다(다른 에이전트, 캠페인 325회와 재실행 20회).
- [x] smoke 2회가 결과에 섞이지 않았다.
- [x] 원자료를 Release에 올리고 DATA.md에 적었다. 결과 표와 SCORE.md를 PR로 합쳤다.

## 11. 작업 체크리스트

- [x] 기존 결과 리뷰 네 개와 계층별 분할 정리 (`review_20261006/`, `REVIEW_20261006.md`)
- [x] 예측 24칸 작성, 해시 기록, 커밋, 태그 `prereg/propagation-v1`
- [x] 계측: evrec, CPU harness 비동기 이벤트와 응답 쪽 QP 상태, SIGKILL 장애, finalize 시간,
  GIN 정리 시간 (PR #13)
- [x] NCCL net_ib F2 주입 훅 (PR #15)
- [x] 캠페인 러너, `DEVIATIONS.md` (PR #16)
- [x] 배포와 smoke 실행 2회(채점 제외)
- [x] 본 캠페인 325회 (16:39 종료, 12절)
- [x] `score.py` push와 PR
- [x] 채점, 블라인드 채점 (최종 17:15)
- [x] 계층별 표
- [x] 독립 재계산(QA)
- [x] 원자료 릴리스, 결과 PR, README 갱신

## 12. 실행 기록 (시간순)

| 시각 (2026-10-06) | 무엇을 했나 | 결과와 근거 |
|---|---|---|
| 12:52 | 예측과 리뷰 파일의 sha256 기록 | [PREREG.txt](PREREG.txt) |
| 13:09 | 사전 등록 커밋과 태그 | `ddade612`, `prereg/propagation-v1` |
| 13:56 | 계측 병합 | master `31d721cf`..`24b35069` (PR #13) |
| 14:02 | CPU smoke 1회차: CPU harness 빌드 실패로 8회 모두 rc=2 | 다시 실행하면서 폴더를 덮어써 파일 기록은 없다. 원인 수정은 `648b417a` |
| 14:03 | CPU smoke 2회차: 8회 | `results/20261006_smoke/cpu/` (`harness__gpu-initiated__propagation__results__20261006_smoke.tar.xz`) |
| 14:04 | F2 주입 훅 병합 | `b2a043b0`, `33a68234` (PR #15) |
| 14:05~14:26 | GPU, net smoke: gp 5, gg 5, gq 5, nvo 6, nvd 6, nvf 5, net 3 | `results/20261006_smoke/` (`harness__gpu-initiated__propagation__results__20261006_smoke.tar.xz`) |
| 14:18 | 러너와 DEVIATIONS 병합 | `c68a981f` (PR #16) |
| 14:27 | 캠페인 시작, 실행 커밋 `3eb87407` | `results/20261006_campaign/run_all.out` |
| 14:33 | cpu 끝: 75/75회 실행, 러너 rc 모두 0 | `cpu/trials.log` |
| 14:46 | gp 끝: 45/45회 | `gp/trials.log` |
| 15:19 | gg 끝: 40/40회 | `gg/trials.log` |
| 15:39 | gq 끝: 25/25회 | `gq/trials.log` |
| 15:56 | nvo 끝: 30/30회 | `nvo/trials.log` |
| 16:20 | nvd 끝: 60/60회 | `nvd/trials.log` |
| 16:23 | nvf 끝: 25/25회 | `nvf/trials.log` |
| 16:39 | net 끝: 25/25회. 캠페인 종료, 8개 스택 모두 러너 rc 0 | `net/trials.log`, `run_all.out` |
| 16:40 | 1차 채점: `score.py`, `--old-gin`은 2026-09-23 `logs/` | `results/20261006_campaign/SCORE.md`, `score.json` |
| 16:43 | 상태를 `QA`로 바꿈. 채점에서 틀림으로 나온 네 줄을 원자료로 확인해 문제 두 가지를 찾음 | 16절 |
| 17:05 | 사용자 결정: gp, gg F4를 원래 설정으로 다시 돌린다. EV3a 블라인드는 `logs/`를 관측 불가로 두고 `v2/logs/`로 판정한다 | [DEVIATIONS.md](DEVIATIONS.md) 10, 11 |
| 17:06 | 독립 재계산(캠페인 325회)이 끝남. 채점기가 판정 기준의 "예측 밖 결과 없음"을 빠뜨린 것을 찾음 | DEVIATIONS 12, 16절 |
| 17:08~17:13 | gp F4 10회, gg F4 10회 재실행. kill은 모두 162~168회째에 걸림 | `results/20261006_f4rerun/`, `campaign/rerun_f4.sh` |
| 17:15 | 최종 채점 | `results/20261006_campaign/SCORE.md`, `score.json` |
| 17:41~18:30 | 계층별 전파율과 분할 표. 다른 에이전트가 같은 표를 따로 만들어 대조함 | [LAYERS.md](results/20261006_campaign/LAYERS.md), 16절 |
| 17:48~18:25 | 원자료 세 묶음을 Release `data-20261006`에 올리고 체크섬 목록을 갱신함 | `DATA.md` |
| 18:45 | 상태를 `COMPLETE`로 바꿈. 결과 PR | 이 문서의 커밋 |

## 13. 사전 등록 이후 변경

변경과 구현 결정은 [DEVIATIONS.md](DEVIATIONS.md)에 있다(2026-10-06 기준 12개). 예측이나 판정 기준을
바꾼 항목은 없다. 10, 11번은 1차 채점을 본 뒤 정했다. 내용은 여기에 복사하지 않는다.

## 14. 원자료와 결과표

| 무엇 | 경로 또는 Release 자산 | n |
|---|---|--:|
| 캠페인 출력 | [results/20261006_campaign/](results/20261006_campaign/) | 325/325회 |
| gp, gg F4 재실행 | `results/20261006_f4rerun/` (`harness__gpu-initiated__propagation__results__20261006_f4rerun.tar.xz`) | 20/20회 |
| smoke 출력(채점 제외) | `results/20261006_smoke/` (`harness__gpu-initiated__propagation__results__20261006_smoke.tar.xz`) | 43회 |
| EV3a 블라인드용 옛 로그 | Release `data-20261006`의 `harness__gpu-initiated__gin__results__20260923.tar.xz` | 6 |
| 1차 채점 결과 | `results/20261006_campaign/SCORE_first.md`, `score_first.json` | 25줄 |
| 최종 채점 결과 | `results/20261006_campaign/SCORE.md`, `score.json` | 25줄(24칸, EV3a는 새 시행과 블라인드 두 줄) |
| 계층별 표 | [LAYERS.md](results/20261006_campaign/LAYERS.md), [layers_trials.csv](results/20261006_campaign/layers_trials.csv), [campaign/layers.py](campaign/layers.py) | 325회, 650줄 |
| 독립 재계산과 검증 | [results/20261006_campaign/qa/](results/20261006_campaign/qa/), 스크립트는 [campaign/qa/](campaign/qa/) | 325회 + 재실행 20회 |

## 15. 결과 요약

캠페인 325회와 재실행 20회의 결과다. 모두 `[측정]`이고, 해석에는 `[추론]`을 붙였다. smoke는 넣지 않았다.

**1. 위로 갈수록 정보가 줄어든다.** 근거: [LAYERS.md](results/20261006_campaign/LAYERS.md)
- GIN 프록시(요청 쪽): CQE와 프록시 스레드에서는 장애가 4묶음으로 갈린다(원격 접근 오류와 상대 kill이
  한 묶음). 앱이 받는 API 값은 "오류 있음/없음" 2묶음뿐이다.
- GIN GDAKI(GPU가 직접 doorbell): blocking 대기에서 로컬 QP 오류, 원격 접근 오류, 재시도 초과는 API에서
  장애 없음과 구분되지 않는다(25/25 조용한 성공). 호스트는 10 s 주기 검사에서야 오류를 안다(25/25).
- NVSHMEM 공식 3.8.0의 GPU 처리 경로와 doorbell record를 고친 CPU 프록시: 상대 kill도 API는 성공으로
  돌아오고(10/10), 정리 단계에서만 멈춘다(10/10).
- NVSHMEM devel의 CPU 프록시 경로: 오류 CQE가 아예 생기지 않았다(0/30). GPU 처리 경로는 30/30에서 생겼다.

**2. 위가 바로 아래 계층보다 잘게 나뉜 곳은 11곳(요청 쪽 8, 상대 쪽 3)이고, 9곳은 설명된다.**
- 채널을 더한 곳(3): CPU 하네스의 상대 생존 확인, GDAKI 장치 쪽 분류기의 원인 CQE 읽기, NVSHMEM FT의
  TCP 생존 확인.
- 아래 계층에서 바로 온 곳(3): GIN 프록시 로그(프록시 스레드가 씀), GDAKI 호스트 오류(10 s 주기 검사),
  GIN 프록시 상대 쪽 로그(NIC의 비동기 QP 이벤트).
- 앞 계층이 이미 멈춘 결과(3): NVSHMEM 3.8.0 CPU 프록시의 정리, GDAKI 두 변형의 상대 쪽 정리. API보다
  잘게 나뉘지는 않는다.
- 이 밖에 GIN GDAKI의 API가 상대 kill만 따로 가른 것은 하네스 드라이버의 TCP 동기화 때문이다(사전 등록
  표가 예측한 아래 계층과 비교한 경우).
- `[추론]` 남은 2곳: NVSHMEM 3.8.0 GPU 처리와 doorbell record 수정본에서 API는 한 묶음인데 정리 단계만
  상대 kill을 가른다. 정리 단계가 죽은 상대와 다시 통신하기 때문으로 보인다. 이 통신을 채널로 보지
  않으면 "채널 없이는 위가 더 잘게 나뉘지 않는다"는 주장의 예외가 된다.

**3. 사전 등록한 계층별 분할은 비교한 20줄 중 19줄이 같았다.**
- 다른 한 줄: NVSHMEM devel GPU 처리 경로에서 읽힌 CQE가 예측(한 묶음)과 달리 3묶음이었다. timeout 모드라
  드라이버 자신의 poll이 원인 CQE를 먼저 읽었다. 예측은 라이브러리의 poll 경로를 기준으로 했다.

**4. 단방향 GIN의 수동 쪽은 원인을 모른다.**
- GIN 프록시 상대 쪽 API는 장애 30/30에서 "신호가 오지 않음"(ncclTimeout) 하나로만 끝났다. 비동기 오류는
  0/30이다. 원격 접근 오류만 로그에 QP 오류 경고를 남겼다(10/10).
- GDAKI 두 변형의 상대 쪽은 blocking 장애 40/40에서 대기와 정리가 모두 멈췄다.
- 양방향 net_ib는 상대 쪽 API까지 오류가 갔다(20/20).

**5. 포트 카운터.**
- verbs로 QP를 만드는 경로(CPU 하네스, GIN 프록시, net_ib)는 장애 130/130에서 오류 카운터가 올랐다.
  DEVX로 QP를 만드는 스택은 0/150이다. `[추론]` 카운터가 DEVX QP를 세지 않기 때문이다.
- 혼잡 알림 처리 카운터(`rp_cnp_handled`)는 재시도 초과와 상대 kill에서만 9~13 올랐다. DEVX 스택을
  포함한 모든 스택에서 그랬고(105/115), 다른 장애와 장애 없음에서는 한 번도 오르지 않았다. 예외는 GIN
  프록시의 상대 kill(0/10)로, 이 경우는 재시도 초과가 아니라 원격 접근 오류로 끝났다. `[미확인]` 왜
  오르는지는 확인하지 않았다.

**6. 예측 24칸 채점: 25줄 중 21줄이 맞았다.** 근거: `results/20261006_campaign/SCORE.md`, 16절
- 틀린 4줄은 모두 예측 자체가 틀린 경우다.
  - 상대 kill 때 요청 쪽 재시도 시간 초과 카운터가 오른다: GIN 프록시는 재시도 초과가 아니라 원격 접근
    오류(10/0x88)를 받아 오르지 않았다(30/40).
  - GDAKI에서 상대 kill 뒤 flush가 성공을 돌려준다(두 줄): 하네스의 TCP 동기화가 상대의 죽음을 먼저
    알았고 flush 대기는 시간 초과로 끝났다(21/30, 1/10).
  - net_ib 복구가 원격 접근 오류를 거절한다: 10회 중 1회는 받는 쪽이 먼저 실패해 다른 경로로 끝났다(9/10).

## 16. QA와 재현성

읽는 법: 괄호 안 기호는 원자료를 찾는 열쇠다. 예측 id(EV5c, D1 등)는 [predictions.csv](predictions.csv)의
`id` 열, 그리고 `results/20261006_campaign/SCORE.md`의 줄 이름과 같다.

- 장애: F0 장애 없음, F1 로컬 QP 오류, F2 원격 접근 오류(MR 밖 주소에 쓰기), F3 재시도 초과(상대 QP를
  오류 상태로), F4 상대 프로세스 kill.
- 스택: cpu CPU verbs 하네스, gp NCCL GIN 프록시, gg NCCL GIN GDAKI(GPU가 직접 doorbell), gq GDAKI +
  장치 쪽 분류기, nvo NVSHMEM 공식 3.8.0(변형 NC, NG, NX), nvd NVSHMEM devel + 장애 주입 훅(변형 ND),
  nvf NVSHMEM FT v2.2, net NCCL 2.23.4 net_ib.
- rank 0은 요청 쪽(rain), rank 1은 응답 쪽(sunny)이다. GIN에서 rank 1은 수동 쪽(target)이다.

**1차 채점(2026-10-06 16:40, QA 전).** `[측정]` 채점기 출력 그대로다. 아직 독립 재계산을 하지 않았다.

- 25줄 중 21줄이 맞음, 4줄이 틀림이다. 25줄은 예측 24칸에 EV3a의 옛 로그 채점 한 줄을 더한 것이다.
- 틀린 4줄은 다음과 같다.
  - GIN 프록시에서 원격 접근 오류 때 수동 쪽 로그에 QP 오류 경고가 남는다는 예측을, 2026-09-23에
    보관한 옛 로그로 채점한 부분 (EV3a 블라인드): 0/6
  - 재시도 초과나 상대 kill 때 요청 쪽 포트 오류 카운터가 오른다는 예측 (EV5c): 30/40
  - GPU가 직접 doorbell을 울려도 실패한 연산의 flush가 성공을 돌려주고 호스트 오류가 난다는 예측 (D1): 20/30
  - GDAKI에서 상대 kill 뒤 첫 flush가 성공을 돌려준다는 예측 (D2): 0/10
- 틀린 시행은 모두 아래 두 문제(문제 1, 2)에서 나왔다. 둘 다 예측이 틀렸다는 근거가 아직 아니다.

**문제 1. GIN 프록시(gp)와 GDAKI(gg)의 상대 kill(F4) 20회는 장애가 통신 중에 걸리지 않았다.** `[측정]`

- 두 rank가 반복 120회를 모두 마치고(`DONE okIters=120 ... exit=0`) 나서 3000 ms에 rank 1이 kill됐다.
  - 예: `gg/logs/gdaki_F4_blocking_t1_r1.log`, `gg/logs/gg_F4_blocking_t1.out`.
  - GIN 프록시 10회(gp F4), GDAKI 10회(gg F4) 모두 같다.
- 원인: [campaign/cells.sh](campaign/cells.sh)가 `gin/scripts/run_trial.sh`를 기본값(반복 120회, 간격
  15 ms, kill 3000 ms)으로 불렀다.
  - 원래 실험의 `gin/scripts/run_matrix.sh`는 상대 kill(F4)에만 반복 400회, 간격 10 ms, kill 2500 ms를
    쓴다.
  - 2026-09-23 `v2/logs`의 F4는 이 설정이다. 예: `gdaki_F4_blocking_t1`은 179회를 마친 뒤 kill이 걸렸다.
- 영향: 다음 시행이 틀림으로 세어졌다.
  - GPU doorbell에서도 CPU doorbell과 같이 오류가 보인다는 예측 (D1)의 상대 kill 10회
  - 상대 kill 뒤 첫 flush가 성공한다는 예측 (D2) 전부
  - 요청 쪽 포트 오류 카운터 예측 (EV5c)의 GIN 프록시 상대 kill 10회(gp F4)
- 장애가 없어서 "맞음"이 된 시행도 있다.
  - GIN 프록시 수동 쪽 로그에 비동기 QP 이벤트가 없다는 예측 (EV3c)의 상대 kill 10회(gp F4)
  - DEVX 스택에 QP 비동기 오류가 없다는 예측 (EV4)과 DEVX 스택의 포트 오류 카운터가 +0이라는 예측
    (EV5a)의 GDAKI 상대 kill 10회(gg F4)
- GDAKI + 장치 쪽 분류기(gq)의 상대 kill(F4, `gin_q4`)은 통신 중에 kill이 걸려 오류 코드 12/0x81이
  나왔다. 영향 없음.
- 처리: 사용자 결정으로 20회를 원래 설정으로 다시 돌렸다(DEVIATIONS 10). 첫 20회도 보관한다.

**문제 2. 옛 로그 채점(EV3a 블라인드)은 어느 로그 묶음을 쓰느냐에 따라 결과가 갈린다.** `[측정]`

- 예측: GIN 프록시에서 원격 접근 오류(F2)를 걸면 수동 쪽(rank 1) 로그에 다음 경고가 남는다.
  `async fatal event on QP ... local access violation`. 블라인드 부분은 2026-09-23에 보관한 로그로
  이것을 채점한다.
- 2026-09-23 GIN 결과에는 GIN 프록시 원격 접근 오류의 rank 1 로그(proxy F2 r1) 묶음이 두 개 있다.
  - `logs/` 6개: NCCL 출력이 한 줄도 없다(`NCCL_DEBUG` 꺼짐). 1차 채점은 이 묶음을 썼고 0/6이다.
  - `v2/logs/` 6개: 6개 모두 `async fatal event on QP ... local access violation`이 있다.
- 사전 등록 문구는 "every retained r1 F2 log"(보관한 rank 1 원격 접근 오류 로그 전부)이고 묶음을
  정하지 않았다.
- [review_20261006/gin.md](review_20261006/gin.md)는 `v2/logs/`를 근거로 쓴다.
- 처리: 사용자 결정으로 `logs/`는 관측 불가, `v2/logs/`로 판정한다(DEVIATIONS 11). 두 결과를 함께
  보고한다.

**문제 3. 1차 채점기가 판정 기준의 절반만 썼다.** `[측정]` 독립 재계산이 찾았다.

- 사전 등록 기준은 "9/10 이상이 예측과 같고, 예측 밖 결과가 하나도 없을 것"이다.
- 1차 채점기는 앞부분만 적용했다. 고친 뒤에는 관측된 miss(예측 밖 결과)가 하나라도 있으면 틀림이다
  (DEVIATIONS 12).
- 이 수정으로 바뀐 판정은 하나다. 복구 패치를 켠 net_ib가 원격 접근 오류에서 복구를 거절한다는 예측
  (NET1c)이 맞음(9/10)에서 틀림으로 바뀌었다.

**최종 채점(2026-10-06 17:15).** `[측정]` 25줄 중 21줄이 맞음, 4줄이 틀림이다.

| 줄 | 예측 내용 | 결과 | 1차 | 무엇이 나왔나 |
|---|---|---|---|---|
| EV5c | CPU verbs 하네스와 GIN 프록시에서 재시도 초과(F3)나 상대 kill(F4) 때, 요청 쪽 노드의 포트 카운터 `local_ack_timeout_err`가 6 이상, `req_cqe_error`가 1 이상 오른다 | 30/40, 틀림 | 30/40 | GIN 프록시 상대 kill 10회(gp F4) 모두 `req_cqe_error` +1, `req_remote_access_errors` +1, `local_ack_timeout_err` +0. 죽은 상대에게서 재시도 초과가 아니라 원격 접근 오류 REM_ACCESS(10/0x88)를 받았다 |
| D1 | GPU가 직접 doorbell을 울리는 GDAKI에서 원격 접근 오류, 재시도 초과, 상대 kill(F2, F3, F4)이 CPU doorbell 때와 같이 보인다. 장치 결과는 `-EIO`, blocking flush는 실패한 연산에도 성공을 돌려주고, 호스트는 다음 10 s 주기에 `GIN Error detected`를 낸다 | 21/30, 틀림 | 20/30 | 원격 접근 오류와 재시도 초과(F2, F3)는 20/20. 상대 kill(gg F4)은 1/10이다. 호스트 오류는 10회 모두 있지만, flush는 성공을 돌려주지 않았다. 상대가 죽은 것을 관리용 TCP 동기화에서 먼저 알고(`peer gone at it N`), 이후 drain 대기가 5 s 상한에서 끝난다(`drain_device_rc=8`) |
| D2 | GDAKI blocking 대기에서 상대 kill(F4) 뒤 첫 flush가 성공을 돌려준다. 오류를 알리지 않는다 | 1/10, 틀림 | 0/10 | 위 줄(D1)의 상대 kill과 같다. 채점기가 맞음으로 센 t10은 판정이 불확실하다(아래 재계산) |
| NET1c | 복구 패치를 켠 NCCL 2.23.4 net_ib에서 원격 접근 오류(F2)를 걸면 복구를 거절하고 `ncclRemoteError`를 돌려주며 재전송하지 않는다 | 9/10, 틀림 | 9/10, 맞음 | `net_F2_t1`에서 받는 쪽(rank 1)이 먼저 flush 오류(5/0xf9)를 받았다. 보내는 쪽(rank 0)은 자기 오류 CQE 없이 "상대 실패 또는 거절"로 끝나, 원격 접근 오류에 대한 거절이 아니라 `CLEAN_FAIL`이 됐다 |
| EV3a 블라인드 | GIN 프록시에서 원격 접근 오류(F2) 때 수동 쪽(rank 1) 로그에 `async fatal event on QP ... local access violation` 경고가 남는다. 2026-09-23에 보관한 로그로 채점한다 | 6/6, 맞음 | 0/6, 틀림 | `v2/logs/` 6개. `logs/` 6개는 관측 불가 |

- 재실행으로 상대 kill(F4)이 실제로 걸린 뒤에도 다음 세 줄은 맞음이다.
  - GIN 프록시에서 로컬 QP 오류, 재시도 초과, 상대 kill 때 수동 쪽 로그에 비동기 QP 이벤트가 없다는
    예측 (EV3c): 30/30
  - DEVX로 QP를 만드는 스택(gg, gq, nvo, nvd, nvf)에서는 어떤 장애에도 두 rank 모두 QP 비동기 오류가
    없다는 예측 (EV4): 180/180
  - DEVX 스택(gg, gq, nvf, nvd)에서는 어떤 장애에도 두 노드의 포트 오류 카운터 4개가 +0이라는 예측
    (EV5a): 150/150
- `[추론]` 요청 쪽 포트 오류 카운터 예측(EV5c), GPU doorbell 예측(D1), 첫 flush 예측(D2)의 상대 kill 부분은
  리뷰 자료와도 어긋난다.
  - [review_20261006/gin.md](review_20261006/gin.md)는 GIN 프록시의 상대 kill을 오류 코드 10/0x88로,
    GDAKI의 상대 kill을 drain 시간 초과로 적고 있다.
  - 예측을 세울 때 이것을 반영하지 못했다.
  - 사전 등록 예측은 고치지 않고 틀린 것으로 보고한다.

**독립 재계산.** `[측정]` 다른 에이전트가 채점기를 보지 않고 원자료에서 다시 셌다.

- 캠페인 325회: 시행 수가 계획과 모두 같다. GIN 프록시와 GDAKI의 상대 kill 20회를 뺀 나머지에서는
  칸마다 n과 맞은 수가 1차 채점기와 같다.
- 채점기가 놓친 판정 기준 절반을 찾았다(문제 3).
- 판정은 바꾸지 않지만 적어 둘 것:
  - net_ib 복구 거절 예측 (NET1c)은 `predictions.csv`의 rank가 "both"(두 rank)다.
    - 두 rank 모두 `ncclRemoteError`를 요구하면 6/10이다.
    - rank 1은 t1, t7, t8, t9에서 `unhandled system error`를 돌려줬다.
    - 어느 쪽으로 읽어도 틀림이다.
  - net_ib 원본에서 원격 접근 오류 때 수동 쪽(target)도 `async fatal event on QP` 경고와 API 오류를 함께
    받는다는 예측 (NET1b)은 예측대로 10/10이지만 근거는 다르다(에이전트 보고, `[미확인]` 직접 확인 안 함).
    - target의 API 오류는 fatal-count 검사가 아니라 target 자신의 flush된 Recv CQE(status 5)에서 나오고,
      9/10에서 async fatal WARN보다 먼저다.
  - 모든 스택에서 장애 없음(F0) 때 어느 계층에도 오류가 없고 두 rank가 5 s 안에 정리를 마친다는 예측
    (T1)에는 NVSHMEM devel + 장애 주입 훅(ND)의 장애 없음 실행이 없다.
    - 이것은 계획대로다. [PREDICTIONS.md](PREDICTIONS.md)의 변형 목록은 이 변형에 로컬 QP 오류, 원격 접근
      오류, 재시도 초과 세 가지만 정해 두었다(7절 표의 "대조군 없음").
  - GPU doorbell 예측 (D1)의 장치 결과 `-EIO`는 원본 드라이버로는 볼 수 없다. GPU doorbell 방식인지는
    로그에 없고 추정이다.
- GIN 프록시와 GDAKI의 상대 kill 재실행 20회(17:30): kill이 20회 모두 통신 중에 걸렸다(반복 400회 중
  162~168회째). 채점기와 판정이 같다. 다른 점은 t10 하나다.
  - 맞음: 수동 쪽 비동기 QP 이벤트 없음(EV3c), DEVX 스택 QP 비동기 오류 없음(EV4), DEVX 스택 포트 오류
    카운터 +0(EV5a).
  - 틀림: 요청 쪽 포트 오류 카운터(EV5c), GPU doorbell(D1), 상대 kill 뒤 첫 flush(D2).
  - 채점기는 `gg_F4_blocking_t10`을 D1, D2에서 맞음으로 센다. rank 0이 rank 1보다 1회 더 성공으로
    셌기 때문이다(`init_silent_iters` = rank 0 성공 수 - rank 1 성공 수 = 1).
  - 재계산은 이 시행을 틀림으로 센다. 그 1회의 쓰기가 실패했는지 로그로는 알 수 없고, kill 뒤 첫 flush인
    drain은 약 4.7 s 뒤 `ncclTimeout`을 돌려줬다.
  - 결과: D1은 21/30 또는 20/30, D2는 1/10 또는 0/10이다. 어느 쪽이든 틀림이다.
- 재계산이 붙인 단서(GPU doorbell 예측 D1, 상대 kill 뒤 첫 flush 예측 D2):
  - blocking 모드에서도 kill 뒤에는 blocking flush가 한 번도 돌지 않았다.
  - 매 회의 TCP 동기화가 죽음을 먼저 알고, drain은 시간 상한이 있는 flush를 쓴다(`gin_fault.cu`의
    `useTimeout=1`).
  - 예측을 "blocking flush가 성공을 돌려준다"로 좁게 읽으면 D2와 D1의 flush 부분은 이 드라이버로는
    시험할 수 없다(자료 없음). `[추론]`

**계층별 표 독립 검증(18:20).** `[측정]` 다른 에이전트가 첫 표를 보지 않고 원자료에서 같은 표를 따로
만들었다. 기록: [qa/layers_qa_TABLE.md](results/20261006_campaign/qa/layers_qa_TABLE.md)

- 변형과 계층마다 구분되는 묶음 수가 같다. 다른 곳은 정의 차이 두 곳뿐이다.
  - NIC 카운터: 검증 쪽은 혼잡 알림 처리 카운터까지 넣어 재시도 초과와 상대 kill을 한 묶음 더 셌다. 첫
    표는 오류 카운터 4개만 봤다. 둘 다 15절 5번에 적었다.
  - GDAKI 장치 쪽 분류기의 "읽은 CQE": poll 자리의 CQE는 20/20에서 뒤따르는 flush(5/0xf9)다. 첫 표는
    사전 등록 표의 정의대로 분류기가 찾은 원인 CQE를 썼다.
- 사전 등록 분할과 다른 곳: 첫 표는 1곳, 검증 쪽은 3곳이다. 늘어난 두 곳은 위 분류기 정의 차이와,
  GDAKI 상대 kill이 API에서 따로 갈린 것이다. 후자는 사전 등록 분할 표에는 상대 kill 칸이 없고, 예측
  채점(D2)에서 이미 틀림으로 보고했다.
- 위가 아래보다 잘게 나뉜 곳의 목록과 설명이 같다. NVSHMEM 3.8.0 정리 단계는 검증 쪽도 "finalize가 죽은
  상대를 필요로 한다"로 설명했다.

## 17. 결론

- `[측정]` 원본 스택에서 장애 정보는 위 계층으로 갈수록 줄어든다. 특히 GIN GDAKI blocking 대기와
  NVSHMEM 3.8.0 GPU 처리 경로는 API에서 실패를 성공으로 돌려준다.
- `[측정]` 위가 바로 아래 계층보다 잘게 나뉜 11곳 중 9곳은 더한 채널, 아래 계층에서 곧장 온 경로, 또는
  앞 계층이 멈춘 결과로 설명된다. 예외 후보는 NVSHMEM 3.8.0 정리 단계 2곳이다.
- `[측정]` 사전 등록한 계층별 분할은 비교한 20줄 중 19줄이 맞았다. 예측 24칸은 25줄 중 21줄이 맞았고,
  틀린 4줄은 상대 kill과 net_ib 복구 경로에 대한 예측이었다.
- `[추론]` 따라서 "정보는 위로 갈수록 줄고, 채널을 더할 때만 늘어난다"는 분석 틀은 이번 자료와 맞는다.
  다만 상대 kill처럼 하네스나 라이브러리가 TCP로 상대 생존을 보는 경우는 채널이 이미 있는 것으로 봐야
  하고, 정리 단계의 통신을 채널로 볼지는 정해야 한다.

## 18. 한계

- NIC 한 종류(ConnectX-6), 노드 한 쌍에서만 잰다. 범위는 mlx5 기반 스택이다.
- 장애는 대부분 소프트웨어로 주입한다.
- evrec은 포트 수준 이벤트만 본다. 다른 프로세스의 QP 이벤트는 볼 수 없어서, EV4는 라이브러리 로그로
  판정한다(DEVIATIONS 9번).
- 포트 카운터는 DEVX QP를 세지 않을 수 있다. +0이 오류가 없었다는 증거는 아니다
  ([evrec/NOTES.md](evrec/NOTES.md)).
- 사전 등록 문서에 제외 기준과 중단 기준이 따로 없다(8절).
- GIN 프록시와 GDAKI의 상대 kill 20회는 러너 실수로 무효였고, 1차 채점을 본 뒤 다시 돌렸다(DEVIATIONS 10).
  옛 로그 채점의 묶음 선택도 1차 채점을 본 뒤 정했다(DEVIATIONS 11).
- GIN GDAKI와 NVSHMEM 3.8.0은 CQE와 장치 결과를 남기지 않아 그 계층을 이번에 재지 못했다.
- NVSHMEM devel은 timeout 모드만 돌려 API 계층을 재지 못했다.
- 상대 kill에서는 죽은 쪽을 관측할 수 없다.

## 19. 다음 작업

1. 정리 단계의 통신을 채널로 볼지 정하고, NVSHMEM 3.8.0 정리 단계가 상대 kill을 어디서 아는지 잰다.
2. 혼잡 알림 처리 카운터가 재시도 초과에서 오르는 이유를 확인한다.
3. 재지 못한 계층(GIN GDAKI와 NVSHMEM 3.8.0의 CQE, NVSHMEM devel의 API)을 재는 계측을 더한다.

## 20. 참고자료

- Hoefler, Belli, "Scientific Benchmarking of Parallel Computing Systems", SC'15. 보고 규칙: n, 분포, 놓친 시행을 적는다. [PREDICTIONS.md](PREDICTIONS.md)의 Method 절이 인용한다.
- Chen, Toueg, Aguilera, "On the Quality of Service of Failure Detectors", IEEE TC 2002. 검출 시간과 오판 지표.
- Hiller, Jhumka, Suri, "PROPANE", ISSTA'02. 모듈 사이 오류 전파 측정.
- Natella, Cotroneo, Madeira, "Assessing Dependability with Software Fault Injection: A Survey", ACM CSUR 2016.
- Huang 외, "Gray Failure", HotOS'17. differential observability.
- Mellanox Adapters PRM Rev 0.40, 7.4.2~7.4.3절(doorbell record와 WQE 소유권).
- [../../../docs/GIT_WORKFLOW.md](../../../docs/GIT_WORKFLOW.md), [../../../DATA.md](../../../DATA.md).
