# 실제 application에서 눈가림으로 재는 복구 라이브러리 (blind-apps)

**목적:** 수정하지 않은 실제 application 셋(PyTorch DDP로 학습하는 nanoGPT, NCCL 2.32.3 GIN 공식 예제, NVSHMEM 3.8.0 공식 예제)을 이 저장소의
복구 라이브러리로 돌리고, 다른 에이전트가 무작위로 고르고 봉인한 장애를 넣은 뒤, 장애를 모르는 평가 에이전트의 판단과 기계 판정을 봉인을 연 뒤
측정 전에 고정한 예측과 맞춰 본다.

| 항목 | 값 |
|---|---|
| 상태 | `DRAFT` |
| 담당자 | @unionxic |
| 작성일 | 2026-10-09 |
| 기준 브랜치와 커밋 | `exp/blind-apps` @ `ae3dafc9` (master) |
| 사전 등록 태그 | 없음(예정: `prereg/blind-apps-v1`, 상태를 `PREREGISTERED`로 바꾸는 바로 그 커밋) |
| 마지막 갱신 | 2026-10-09 13:55, pilot P3 검토, 시각 대응 확정, 첫 봉인 폐기와 새 봉인 순서(12, 18절). 상태는 `DRAFT` |

표시: `[측정]` 원자료나 파일에서 확인, `[소스]` 코드에서 읽음, `[추론]` 해석, `[미확인]` 확인 안 함.

**용어.**
- 투명: 살아남은 모든 rank가 종료 코드 0으로 끝나고, 오류 줄이 없고, 결과 검사가 맞다(복구 줄은 있어도 된다).
- 거절: 살아남은 rank가 오류 줄을 남기거나 0이 아닌 코드로 끝났다(시간 제한 오류는 멈춤).
- 멈춤: 살아남은 rank를 하네스가 끝냈거나(유예 시간이나 시간 상한), 첫 오류 줄이 시간 제한 오류다.
- 조용한 틀림: 오류 줄 없이 모두 0으로 끝났는데 결과 검사가 틀리다.
- 결과 검사: 시행의 결과가 맞는지 정하는 기준. 작업마다 3.1절.
- 살아남은 rank: 일정이 kill한 rank를 뺀 rank.
- 장애 에이전트: 일정을 만들고 봉인하는 별도 에이전트. 평가 에이전트: 장애를 모른 채 평가 폴더만 보고 판단하는 별도 에이전트. 메인 세션: 배포, 실행,
  채점을 하는 세션.
- 봉인: 장애 에이전트가 만든 일정 파일. 저장소 밖(`~/blind-seal/`)에 두고 sha256만 사전 등록 커밋에 넣는다.
- 기준 실행: 장애 없이 돈 실행. 평가 에이전트에게 장애 없는 모습으로 보여 주고, DDP 결과 검사의 기준 해시를 정한다.

작업과 장애 종류의 키는 원자료와 스크립트를 찾는 키로만 쓴다(괄호나 표의 열).

| 작업 | 키 | application(수정 없음) | 라이브러리(이 저장소의 복구 빌드) |
|---|---|---|---|
| DDP 학습 | `ddp` | nanoGPT `train.py`(커밋 `3adf61e1`), PyTorch 2.4.1 DDP, 노드마다 프로세스 하나 | 다중 요청 복구, NCCL 2.23.4(`9ed03e1d`), CPU 프록시 IB 경로 |
| GIN 예제 | `gin` | NCCL 2.32.3 `docs/examples/09_gin_optimizations/01_ring_exchange` | GIN 투명 복구 `hq`(gin-peer, `c1311625`) |
| NVSHMEM 예제 | `nvs` | NVSHMEM 3.8.0 `examples/ring-reduce.cu` | NVSHMEM 투명 복구(t1_380, transport `d6ae3699`) |

| 장애 | 키 | 어디에 | 작업 |
|---|---|---|---|
| 없음 | `none` | | 셋 다 |
| 송신 QP를 ERR로(라이브러리 훅) | `sqp` | 대상 rank의 NCCL 연결 하나 | `ddp` |
| 수신 QP를 ERR로, 상대에게 알림 | `rqp` | 같음 | `ddp` |
| 수신 QP를 ERR로, 알리지 않음 | `srq` | 같음 | `ddp` |
| 대상 rank의 GPU 주도 통신 QP를 모두 ERR로 | `qperr` | 대상 rank | `gin`, `nvs` |
| 대상 rank의 QP에서 원격 접근 권한을 거둠 | `remacc` | 대상 rank | `nvs` |
| 프로세스 SIGKILL | `kill` | 대상 rank의 application 프로세스 | 셋 다 |
| SIGSTOP 뒤 몇 초 지나 SIGCONT | `stop` | 같음 | 셋 다 |
| 관리망 끊김(이 시행의 연결만, 양방향 또는 sunny→rain만) | `mute` | rain의 iptables | 셋 다 |

## 1. 배경과 연구 질문

**왜 하는가.** 지금까지의 사전 등록 실험(nccl-builtin, t1_380, gin-harden, gin-handoff, gin-peer 등)은 우리가 만든 드라이버(`nb_ct`, `gin_ts2`,
`gin_mr`, `nvt1_drv`)와 우리가 정한 장애 시각으로 쟀다. 예측은 pilot을 본 뒤 확정했고(예: `../gpu-initiated/gin_recovery/peer/EXPERIMENT.md` 3절
"고정 시점"), 대부분 고친 동작이 설계대로 도는지를 확인했다 `[소스]`. 그래서 남는 질문이 둘이다. 모르는 사람이 짠 application에서도 같은가. 장애를
우리가 고르지 않으면 어떤가. 이 실험은 둘 다를 바꾼다.
- application은 수정하지 않는다. 다중 노드 부트스트랩이 MPI를 요구하는 예제에는 고유 ID만 옮기는 작은 대체 파일을 붙인다(9.2절).
- 장애의 종류, 시각, 대상은 장애 에이전트가 `/dev/urandom` 시드로 뽑고 봉인한다. 예측은 일정이 생기기 전에 고정한다.
- 무슨 일이 일어났는지는 장애를 모르는 평가 에이전트가 훅 줄을 지운 출력만 보고 판단한다. 기계 판정은 원자료에서 따로 한다.

**이미 아는 것** `[측정, 이전 실험]`. 숫자는 각 실험의 README와 채점표에서 옮겼다(다시 세지 않았다. 재계산은 QA 몫이다).
- 다중 요청 복구(`../nccl-integration/stage2/README.md`, `../nccl-integration/builtin/README.md`): 송신 QP 주입 30/30, 수신 QP 주입 30/30 투명(최종
  이전 빌드), 최종 빌드 경우마다 3/3. 받는 중 상대 kill은 FIN을 보고 약 50 ms에 오류. 12 s 관리망 끊김 양방향 3/3, 단방향 5/5 통과. 알리지 않은
  수신 QP 오류는 256 KiB all-reduce에서 시간 제한까지 멈춤 5/5, 64 MiB 방송에서 투명 5/5. 모든 복구 444번에서 결과 불일치 0.
- GIN 투명 복구 `hq`(`../gpu-initiated/gin_recovery/peer/README.md`): 사전 등록 37개 예측 37개 맞음. 랭크 2개 회귀(로컬 QP 오류, 상대 QP 오류, 양방향)
  셀마다 5/5 투명, kill 2 s 안 죽음 거절 5/5. gin-harden 운영 빌드 8 s 관리망 끊김 5/5 투명.
- NVSHMEM 투명 복구 t1_380(`../gpu-initiated/nvshmem_ft/t1_380/README.md`, `../gpu-initiated/nvshmem_ft/TRANSPARENT_T1.md`): 로컬 QP 오류 10/10, 상대 QP
  오류 5/5 투명. 앱의 heap 밖 쓰기(원격 접근 오류) 10/10 거절, 상대 kill 5/5 거절. 라이브러리 소켓 8 s 끊김 5/5 투명.

**비어 있는 것.**
- 세 라이브러리 모두 이 저장소 밖의 application으로 돈 적이 없다. 특히 다중 요청 복구는 PyTorch와 함께 돈 적이 없다 `[미확인]`.
- 장애 시각이 application의 진행과 무관하게 무작위인 적이 없다. 장애 종류와 대상도 늘 실행기 설정으로 정해졌다.
- 출력만 보고 무슨 장애였고 어떻게 끝났는지 가릴 수 있는지(관측 가능성)를 독립적으로 잰 적이 없다.

**질문.**
1. 복구할 수 있다고 설계한 장애(QP 오류, 멈춘 상대, 관리망 끊김)를 실제 application에서 무작위 시각에 넣으면 투명한 비율이 얼마인가.
2. 복구할 수 없는 장애(상대의 죽음, 원격 접근 권한 회수, 알리지 않은 수신 QP 오류)는 정해 둔 시간 안에 오류나 시간 제한으로 드러나는가.
3. 어느 작업, 어느 장애에서든 조용히 틀린 결과가 나오는가.
4. 훅 줄을 지운 출력만으로 평가 에이전트가 장애 종류와 결과를 얼마나 맞히는가.

## 2. 가설

| id | 가설 | 다음이 관측되면 틀린 것이다 |
|---|---|---|
| H1 | 세 라이브러리는 수정하지 않은 application에서도 QP 오류를 투명하게 복구한다 | QP 오류 훅 셀(`ddp` `sqp`, `rqp`, `gin` `qperr`, `nvs` `qperr`)에서 3.3절의 비율(90%, 85%)에 못 미친다 |
| H2 | 멈춘 상대와 관리망 끊김은 라이브러리가 상대의 죽음으로 보지 않고, application은 늦어질 뿐 같은 결과로 끝난다 | `stop`, `mute` 셀에서 투명하지 않거나 죽음 줄이 있는 시행이 3.3절의 허용(1회, GIN `mute` 2회)을 넘는다 |
| H3 | 복구할 수 없는 장애는 정해 둔 시간 안에 드러난다 | `kill`, `remacc`, `srq` 셀에서 투명한 시행이 있거나, 오류가 3.3절의 시간(3 s, 5 s, 45 s) 안에 오지 않은 시행이 허용을 넘는다 |
| H4 | 조용히 틀린 결과는 없다 | 유효 시행 하나라도 조용한 틀림이다 |
| H5 | 라이브러리 로그와 종료 기록만으로 결과와 대부분의 장애 종류를 가릴 수 있다 | 평가 에이전트의 판단이 3.3절의 비율(85%, 80%, 90%, 75%, 60%)에 못 미친다 |

## 3. 사전 예측 (측정 전에 작성)

**고정 시점.** 예측 원문은 [predictions.csv](predictions.csv)(25줄)다.
- 이 예측은 pilot보다, 그리고 일정보다 먼저 고정한다. 메인 세션이 예측을 커밋한 뒤에야 장애 에이전트가 일정을 만든다. `schedule_gen.py make`는
  `predictions.csv`와 `schedule_config.json`이 커밋되어 있고 작업 트리에서 바뀌지 않았을 때만 돌고, 그 두 파일의 sha256과 git 커밋을 봉인 머리에
  적는다 `[소스]`.
- pilot(9.4절 4단계)은 하네스와 시각 대응표(`calib.json`)만 고친다. pilot을 보고 예측, 셀, 반복 수, 제외 기준을 바꾸지 않는다. 바꿀 일이 생기면
  13절에 적고 그 예측은 따로 보고한다.
- 사전 등록 커밋은 상태 `PREREGISTERED`, 12절 기록, `PREREG.txt`(예측, 설정, 시각 대응표, 봉인, 스크립트의 sha256)를 함께 담고, 그 커밋에
  `prereg/blind-apps-v1`을 단다.
- 판정은 일정을 연 뒤에만 한다. 평가 에이전트의 판단 파일을 sha256과 함께 커밋한 다음에 일정을 열고 채점한다(9.4절 7, 8단계).

`kind`는 S(시스템 동작, 기계 판정)와 E(평가 에이전트의 판단)다.

### 3.1 판정에 쓰는 열

시행마다 한 줄이다. [rows_blind.py](rows_blind.py)가 결과 폴더의 `raw/<시행 id>/`에서 만든다. 로그 줄의 시각은 rain의 CLOCK_MONOTONIC으로 실행기가
줄을 받은 시각이다(rank 1의 줄은 ssh를 거친다). 정규식 원문은 그 파일 머리에 있다.

| 열 | 정의 |
|---|---|
| `id`, `kind`, `hold`, `workload`, `cls`, `target`, `dir` | 시행 id(봉인의 무작위 8자리 16진수), 종류(blind, baseline, demo), hold, 작업, 장애, 대상 rank, 끊김 방향 |
| `k`, `t_ms`, `t_after_anchor_s`, `d_s` | 장애 매개변수: DDP 훅의 순번 k, GIN과 NVSHMEM 훅의 지연(ms), 기준 줄 뒤 kill, stop, mute 시각(s), 멈춤과 끊김 길이(s) |
| `applied` | 장애가 실제로 걸렸으면 1. 훅: 대상 rank 로그에 그 훅의 발화 줄(NVSHMEM과 GIN은 옮긴 QP 수가 1 이상인 줄)이 있음. kill, stop: 에이전트가 `rc=0`으로 신호를 보냈다고 답함. mute: 규칙을 하나 이상 넣음 |
| `void` | 시작 실패: rank 0이 작업의 기준 줄(`ddp` `iter 0: loss`, `gin` `=== Comparing GIN ring-exchange implementations ===`, `nvs` `[nvshmem-t1] PE0 <t> enabled:`)을 남기지 않았거나 어느 rank든 시작 실패 줄(`nvs`: `nvshmemi_setup_transport failed`, `heap registration setup failed`. `nvs`의 기준 줄은 연결 직후라 heap 등록보다 먼저 나온다)을 남겼고, 그보다 먼저 걸린 장애가 없음. pilot 뒤 시작 실패 줄을 더했다(12절) |
| `config_ok` | 줄을 남긴 모든 rank에 빌드 확인 줄이 있고, 복구가 꺼졌다는 줄이 어느 rank에도 없음. `ddp`: `NCCL version 2.23.4`와 `[FAULT-RECOVERY2] recovery on for`가 있고 `recovery off for this`가 없음(QP 하나, NIC 하나, AR 없음인 연결만 복구한다). `gin`: `GIN/TS: transparent recovery ON rank=`가 있고 `transparent recovery OFF`가 없음. `nvs`: `[nvshmem-t1] PE<p> <t> enabled:`가 있고 `transparent mode off`가 없음 |
| `valid` | `applied == 1`, `void == 0`, `config_ok == 1` |
| `killed_rank`, `rc0`, `rc1`, `end0`, `end1` | kill된 rank. rank마다 종료 코드(음수는 신호)와 하네스가 끝냈는지(`grace`, `wall`, 빈칸) |
| `n_err0`, `n_err1`, `err0`, `err1`, `timeout_first` | 오류 줄 수와 첫 줄. 살아남은 rank의 첫 오류 줄이 시간 제한 오류면 1 |
| `n_rec`, `n_death`, `n_mgmt` | 복구 줄 수(두 rank), 살아남은 rank의 상대 죽음 줄 수, 관리망 손실과 재연결 줄 수 |
| `result` | 결과 검사: `correct`, `wrong`, `none`(결과 줄 없음), `unknown`(DDP 기준 해시가 성립하지 않음) |
| `outcome` | `TRANSPARENT`, `DECLINED`, `HUNG`, `SILENT_WRONG`, `OTHER`, `UNKNOWN`. 규칙은 아래 |
| `dt_err`, `dt_end` | 장애 시각(훅 발화 줄, 신호 응답, 규칙 삽입)에서 살아남은 rank의 첫 오류 줄까지, 마지막 살아남은 rank의 종료까지(s) |
| `max_gap0` | 기준 줄 뒤 rank 0 출력 줄 사이 가장 긴 간격(s) |
| `j_class`, `j_target`, `j_outcome`, `j_ok_outcome`, `j_ok_class` | 평가 에이전트의 판단과, 그것이 `outcome`, `cls`와 같은지(1, 0). 채점 때만 붙는다 |

**오류 줄**(작업마다, `rows_blind.py` `ERR`).
- `ddp`: torch 감시 스레드의 시간 제한과 NCCL 오류(`Watchdog caught collective operation timeout`, `ProcessGroupNCCL ... Exception/error`,
  `DistBackendError`, `NCCL error`, `ncclRemoteError` 등), `terminate called`, Python traceback, 다중 요청 복구의 실패(`FAILED in`, `peer process gone`),
  원본 오류 CQE 줄.
- `gin`: 거절(`GIN/TS: declined rank=`), 죽음 판정, 오류로 풀린 장치 대기(`why=declined|peer-dead|fw-watchdog`), 감시의 드러냄, 예제의
  `Failed, NCCL error`, `Failed: Cuda error`, `ERROR:`, 복구 실패(`GIN/REC: commit failed|recovery aborted|prepare declined`), 원본 오류 CQE 줄.
- `nvs`: `DECLINE`, `marked failed`, `transparent mode off`, CUDA 오류, NVSHMEM 오류 줄. 예제의 검증 줄(`PE <p> error, data[...]`)은 오류 줄이
  아니다(결과 검사다).

**시간 제한 오류**: `ddp`만 있다(torch 집합 연산 시간 제한 30 s, 다중 요청 복구의 WAITREQ). `gin`, `nvs` 예제에는 시간 제한이 없어 멈춤은 하네스가
끝낸 것으로만 드러난다.

**결과 검사.**
- `ddp`: 살아남은 모든 rank가 `[ddp-entry] rank=<r> final iter=<n> parameters sha256=<h>`를 남기고, `h`가 같은 결과 폴더의 기준 실행
  (`ref-ddp-*`)에서 그 rank의 해시와 같으면 맞음. 기준 실행들의 해시가 rank마다 하나로 모이지 않으면 `unknown`이다. 해시는 학습된 모델의
  `state_dict` 텐서를 이름순으로 이은 바이트의 SHA-256이다(`ddp/ddp_entry.py`). 결정성은 8절의 조건이다.
- `gin`: rank 0이 `GIN Ring Exchange result: PASSED`를 남기고 어느 rank도 `mismatch at CTA` 줄이 없으면 맞음. `FAILED`나 mismatch 줄이면 틀림.
- `nvs`: PE 0이 세 크기 줄(16, 32, 64 MiB)을 모두 남기고 어느 PE도 검증 줄이 없으면 맞음. 검증 줄이 하나라도 있으면 틀림.

**결과 규칙**(`rows_blind.py` 머리말, 위에서부터 먼저 맞는 것).
1. `UNKNOWN`: 결과가 `unknown`이고 멈춤, 오류 줄, 0이 아닌 종료가 모두 없음.
2. `HUNG`: 살아남은 rank를 하네스가 끝냈거나 첫 오류 줄이 시간 제한 오류.
3. `SILENT_WRONG`: 결과가 틀리고, 살아남은 rank에 오류 줄이 없고, 모두 0으로 끝남.
4. `DECLINED`: 살아남은 rank에 오류 줄이 있거나 0이 아닌 종료.
5. `TRANSPARENT`: 결과가 맞음.
6. `OTHER`: 그 밖.

### 3.2 판정식 문법

[score.py](score.py)가 `predictions.csv`의 `acceptance`를 `select`로 고른 유효 눈가림 시행에 적용한다.
- `select`: `<작업>:<장애>`를 `+`로 잇는다. `*`는 아무것.
- `acceptance`: Python 식. `n`은 고른 유효 시행 수, `count(<식>)`은 그 가운데 `<식>`이 참인 수, `ceil`은 올림이다. `count` 안에서는 3.1절의 열 이름을
  쓴다. 빈 칸은 어떤 비교도 거짓이고 산술은 실패한다(그 시행은 세지 않는다).
- 판정은 맞음, 틀림, 자료 부족이다. 자료 부족: 유효 시행이 `n_min`(계획의 75%, 올림)보다 적음, 고른 시행에 `UNKNOWN`이 있음, E 예측에서 판단이 없는
  시행이 있음.
- 제외(8절)는 다시 채우지 않는다. 제외 수는 셀마다 따로 보고한다.

### 3.3 예측 요약

계획 n은 7절, 전체 판정식은 [predictions.csv](predictions.csv)에 있다.

| 무엇을 예측했나 | id | 선택 | 판정 기준(요약) | 근거 |
|---|---|---|---|---|
| DDP, 장애 없음: 투명 | D1 | `ddp:none` | n − 1 이상 | 다중 요청 복구 장애 없음 20/20 `[측정, 이전 실험]` |
| DDP, 송신 QP 오류: 복구 줄과 함께 투명 | D2 | `ddp:sqp` | 90% 이상 | 30/30, 3/3, 5/5 `[측정, 이전 실험]` |
| DDP, 수신 QP 오류(알림): 복구 줄과 함께 투명 | D3 | `ddp:rqp` | 90% 이상 | 30/30, 3/3, 5/5 `[측정, 이전 실험]` |
| DDP, 알리지 않은 수신 QP 오류: 멈춘 뒤 torch 시간 제한이 훅 뒤 45 s 안에 끝냄. 결과는 멈춤이나 투명뿐 | D4 | `ddp:srq` | 멈춤 n − 2 이상, 나머지는 투명 | all-reduce 멈춤 5/5 `[측정]`, DDP도 같다 `[추론]` |
| DDP, kill: 살아남은 rank가 5 s 안에 오류, 20 s 안에 종료 | D5 | `ddp:kill` | n − 1 이상 | FIN 약 50 ms, kill 0.30–0.31 s 5/5 `[측정]`, torch 감시 `[추론]` |
| DDP, 2–12 s 멈춤: 투명, 죽음 줄 없음 | D6 | `ddp:stop` | n − 1 이상 | 죽음 판정은 FIN뿐 `[소스]`, 잰 적 없음 `[미확인]` |
| DDP, 관리망 6–14 s 끊김: 투명, 죽음 줄 없음 | D7 | `ddp:mute` | n − 1 이상 | 12 s 끊김 3/3, 5/5 `[측정]` |
| GIN, 장애 없음: 투명 | G1 | `gin:none` | n − 1 이상 | `[측정, 이전 실험]`, 예제는 처음 `[미확인]` |
| GIN, QP 오류: 복구 줄과 함께 투명 | G2 | `gin:qperr` | 85% 이상 | 회귀 셀 15/15 `[측정]`, 예제의 장치 API는 처음 `[추론]` |
| GIN, kill: 투명이나 조용한 틀림 없음, 5 s 안 오류 | G3 | `gin:kill` | 모두 거절이나 멈춤, n − 1 이상 5 s 안 | 2 s 안 죽음 거절 5/5 `[측정]` |
| GIN, 1–8 s 멈춤: 투명, 죽음 줄 없음 | G4 | `gin:stop` | n − 1 이상 | `[소스, 추론]` |
| GIN, helper 포트 2–8 s 끊김: 투명, 죽음 줄 없음 | G5 | `gin:mute` | n − 2 이상 | 8 s 끊김 5/5 `[측정]`, 종료와 겹침은 처음 `[추론]` |
| NVSHMEM, 장애 없음: 투명 | N1 | `nvs:none` | n − 1 이상 | 5/5 `[측정]`, 예제와 플러그인은 처음 `[미확인]` |
| NVSHMEM, QP 오류: 복구 줄과 함께 투명 | N2 | `nvs:qperr` | 85% 이상 | 10/10, 5/5, 20/20 `[측정]` |
| NVSHMEM, 원격 접근 권한 회수: 투명이나 조용한 틀림 없음, 3 s 안 오류 | N3 | `nvs:remacc` | 모두 거절이나 멈춤, n − 1 이상 3 s 안 | 앱의 원격 접근 오류 10/10 거절 `[측정]`, 훅으로는 처음 `[미확인]` |
| NVSHMEM, kill: 같음 | N4 | `nvs:kill` | 같음 | 5/5 거절 `[측정]` |
| NVSHMEM, 1–8 s 멈춤: 투명, 죽음 줄 없음 | N5 | `nvs:stop` | n − 1 이상 | `[소스, 추론]` |
| NVSHMEM, 관리망 4–10 s 끊김: 투명, 죽음 줄 없음 | N6 | `nvs:mute` | n − 1 이상 | 소켓 8 s 끊김 5/5 `[측정]` |
| GIN과 NVSHMEM: 조용한 틀림 0 | X1 | `gin:*+nvs:*` | 0회 | `[측정, 이전 실험]` |
| DDP: 조용한 틀림 0 | X2 | `ddp:*` | 0회 | 복구 444번 불일치 0 `[측정]` |
| 평가 에이전트의 결과 판단이 기계 판정과 같음 | E1 | `*:*` | 85% 이상 | `[추론]` |
| QP 오류 훅 시행의 장애 종류를 맞힘 | E2 | QP 오류 넷 | 80% 이상 | 복구 줄이 연결과 상태를 남긴다 `[소스]` |
| kill 시행의 장애 종류를 맞힘 | E3 | `kill` 셋 | 90% 이상 | 종료 신호 9 `[추론]` |
| 장애 없는 시행을 장애 없음으로 판단 | E4 | `*:none` | 75% 이상 | `[추론]` |
| DDP 멈춤과 끊김의 장애 종류를 맞힘 | E5 | `ddp:stop+ddp:mute` | 60% 이상 | 반복 줄 간격, OOB 손실 줄 `[소스, 추론]` |

## 4. 범위

**포함.**
- 9.2절의 작업 셋, 7절의 장애 종류와 반복 수, 9.1절의 눈가림 절차, 평가 에이전트의 판단 하나.
- 이 실험이 새로 만든 것: 실행기와 에이전트(`blindrun.py`, `node_agent.py`), 일정 생성기, 훅 줄 필터, 평가 폴더 생성기, 채점기, DDP 진입 파일,
  두 부트스트랩 대체 파일(`boot/`), 설치, 빌드, 배포 스크립트. 라이브러리는 기존 빌드를 그대로 쓴다.

**제외와 그 이유.**
- 실제 link down, flap, RoCE 주소 변경, 재부팅, 드라이버 재적재: 클러스터 규칙(8절).
- GIN의 원격 접근 오류: `hq`에는 이 오류를 만드는 라이브러리 훅이 없다. 앞 실험의 원격 접근 오류 셀은 드라이버가 일부러 틀린 오프셋으로 put했다
  (`../gpu-initiated/gin_recovery/gin_ts2.cu`의 모드 `F2`, `GIN_TS_F2_IT`) `[소스]`. 수정하지 않은 예제로는 만들 수 없다.
- GIN과 NVSHMEM에서 로컬 QP 오류와 상대 QP 오류의 구분: 두 훅 모두 대상 rank의 QP를 ERR로 옮길 뿐이다(`ncclGinGdakiFaultFire`,
  `ibgda_fi_all_qps_to_err`) `[소스]`. 두 예제는 양방향으로 보내므로 한 번의 훅이 대상 rank에게는 로컬 오류, 상대에게는 상대 QP 오류가 된다
  `[추론]`. 그래서 한 종류(`qperr`)로 두고 대상 rank를 무작위로 고른다.
- 다중 요청 복구의 rkey 훅(`NCCL_RDMA_FAULT_INJECT_RKEY`): 이번 장애 목록에 없다.
- NVSHMEM perftest: 대부분 데이터를 검증하지 않는다(대역폭, 지연 측정). 공식 예제 가운데 데이터를 검증하는 것은 `ring-bcast`, `ring-reduce`,
  `put-block` 등이다 `[소스]`. `ring-bcast`는 128 B put 하나라 장애가 트래픽에 걸릴 시간이 없다 `[소스, 추론]`. `ring-reduce`는 명령줄 인수로 크기와
  반복을 정할 수 있어 수 초의 트래픽을 만든다.
- 다른 GIN 예제(`06_device_api/02_alltoall_gin`, `07_kernel_fusion/03_rmsnorm_gin`)는 커널을 한 번만 띄워 트래픽이 짧다 `[소스]`.
- 장애 두 개 이상을 한 시행에: 하지 않는다.
- PE 2개, 노드마다 GPU 하나, 활성 RoCE 포트 하나.

## 5. 테스트베드와 버전

| 항목 | 값 | 확인 방법과 날짜 |
|---|---|---|
| 노드, NIC, GPU | rain(rank 0, Quadro RTX 5000, sm_75, 드라이버 570.211.01, Ubuntu 20.04, glibc 2.31), sunny(rank 1, RTX A4000, sm_86), ConnectX-6, RoCE v2, rain `mlx5_1` GID 4가 RoCE v2 | rain `[측정]` 2026-10-09(`nvidia-smi` 조회, sysfs). sunny는 앞 실험의 기록(`../gpu-initiated/gin_recovery/peer/EXPERIMENT.md` 5절) `[측정, 이전 실험]` |
| 임시 포트 범위와 이 실험의 포트 | rain `ip_local_port_range` 32768–60999. 이 실험은 30000–31999에서 고르고 두 노드에서 어떤 상태의 TCP 소켓도 쓰지 않을 때만 쓴다. 확인 때 rain에는 그 범위를 원격 포트로 쓰는 TIME-WAIT 소켓 1개뿐이었다 | `[측정]` 2026-10-09 12:5x rain(`/proc`, `ss`). sunny는 실행기가 시행마다 확인 `[미확인]` |
| Python과 PyTorch | 두 노드 같은 독립 실행형 CPython 3.10.15(python-build-standalone 20241016, sha256 확인), torch 2.4.1+cu121, numpy 1.26.4, `~/blind-venv/py310`(5.1 GB, 파일 18 856개). rain의 시스템 Python은 3.8.10이고 sunny는 3.10.12라 같은 인터프리터를 따로 둔다. sunny에는 rain의 트리를 그대로 복사한다 | `[측정]` rain `~/blind-venv/install_info.txt`, MANIFEST md5 `9dca7f6a` |
| torch와 NCCL 2.23.4 | torch 2.4.1은 NCCL 2.20.5 헤더로 빌드됐다(`torch.cuda.nccl.version()`은 컴파일 때 값 (2, 20, 5)). `libtorch_cuda.so`는 `libnccl.so.2`를 NEEDED로, 찾는 길을 DT_RPATH로 갖는다. 그래서 `LD_LIBRARY_PATH`로는 바뀌지 않고 `LD_PRELOAD`로 바꾼다. Stage 2 라이브러리를 `LD_PRELOAD`하면 프로세스에 매핑된 libnccl은 그 파일 하나다. torch가 가져오는 NCCL 심볼 26개가 모두 그 라이브러리에 있고, `ncclConfig_t` 정의는 2.20.5와 2.23.4 헤더에서 같다 | `[측정]` 2026-10-09 rain(`readelf -d`, `nm -D`, `/proc/self/maps`, 헤더 diff). CUDA 호출 없음. 이 조합으로 NCCL communicator를 만들어 본 적은 없다 `[미확인]` |
| 다중 요청 복구 | `libnccl.so.2.23.4` md5 `9ed03e1d4b9833c0c2e01f3aa1f84d1c`(a037de42 + 쓰지 않는 rkey 훅), SASS sm_75, sm_86. rain에서는 `<scratch>/nccl_rkey_build/lib`과 `~/nb-bundle/s2`에 있다. 지시문의 `~/nccl-ct/stage2rkey`는 rain에 없고 sunny의 디렉터리다(`../nccl-integration/perf/ctlib.py` `PEER_DIR`) | `[측정]` md5sum, cuobjdump. `[소스]` ctlib.py |
| GIN `hq` | libnccl `c1311625c7a06c785bc313558504f982`, 헤더 `<scratch>/agent_ts2hq/build/include`(include digest `26f38f43`, gin-peer 빌드 기록과 같음) | `[측정]` |
| NVSHMEM t1_380 | `~/gi-bundle/nvshmem_t1_380/lib`: transport `d6ae3699`, host `825443f8`, UID 부트스트랩 `26da2c31`, 설치 `<scratch>/agent_t1_380/install`과 같음 | `[측정]` md5sum |
| GPU BAR1 | rain Quadro RTX 5000 BAR1 256 MiB(쓰는 중 5 MiB). 그래서 256 MiB 대칭 heap은 GPUDirect 등록에 실패한다(12절 P1). t1_380은 160 MiB heap을 두 노드에서 썼다. sunny의 BAR1 크기는 `[미확인]` | `[측정]` 2026-10-09 rain `nvidia-smi -q -d MEMORY`, `[측정, 이전 실험]` t1_380 hold 사양 |
| nanoGPT와 데이터 | 커밋 `3adf61e154c3fe3fca428ad6bc3818b27a3b8291`(수정 없음), `data/shakespeare_char/prepare.py`가 만든 학습 1 003 854 토큰, 검증 111 540 토큰, 어휘 65 | `[측정]` install_info.txt |
| 빌드한 실행 파일(빌드됨, 돌리지 않음) | `blind_gin_ring` `074ee68c`(main.cu `d7e8a7f1`, kernels.cuh `f919b590` 그대로), `blind_nvs_rr` `26187ab9`(ring-reduce.cu `16a2d9c3` 그대로), `blind_nvs_boot.so` `e3264e83`. 모두 SASS sm_75, sm_86 | `[측정]` `<scratch>/agent_blind/out/build_info.txt` |

## 6. 변수

- **독립변수.** 장애 종류(작업마다 `none` 포함 5–7가지), 대상 rank, 장애 시각(봉인의 `u_t`), 멈춤과 끊김 길이(`u_d`), 끊김 방향. 모두 장애 에이전트가 뽑는다.
- **종속변수.** 3.1절의 열: 결과 분류, 결과 검사, 오류까지와 종료까지의 시간, 복구 줄, 죽음 줄, 관리망 줄. 평가 에이전트의 판단(장애 종류, 대상, 결과,
  결과가 맞는지, 첫 오류 시각, 확신).
- **통제변수.**
  - 시행마다 프로세스를 새로 띄운다. rank 0은 rain, rank 1은 sunny. 대상 rank는 0과 1 반씩의 확률.
  - `ddp`: nanoGPT `config/train_shakespeare_char.py`에 명령줄 덮어쓰기만(`--compile=False --dtype=float32 --max_iters=300 --lr_decay_iters=300
    --warmup_iters=30 --eval_interval=1000 --eval_iters=10 --log_interval=1 --batch_size=16 --block_size=128 --n_layer=4 --n_head=4 --n_embd=256
    --dropout=0.1 --gradient_accumulation_steps=2 --always_save_checkpoint=False`). 평가는 반복 0에서 한 번, 체크포인트 없음. rendezvous는 env://,
    노드마다 프로세스 하나(torchrun 없음). `TORCH_NCCL_ASYNC_ERROR_HANDLING=3`(오류 때 abort를 부르지 않고 프로세스를 끝낸다. 2.23.4의
    `ncclCommAbort`는 오류 뒤 돌아오지 않는다), 집합 연산 시간 제한 30 s, `NCCL_RDMA_FAULT_RECOVERY=1`, `NCCL_IB_TIMEOUT=14`, `NCCL_DEBUG=INFO`
    (`INIT,NET`), NCCL 소켓은 `eno1`(관리망).
  - `gin`: gin-peer 실행기와 같은 NCCL 환경(`NCCL_GIN_TYPE=3`, 분류, 복구, 투명 복구 켬, IB 타임아웃 14, `NCCL_DEBUG=WARN`), helper 포트
    `NCCL_GIN_TS_PORT`는 시행마다 고른 16개 묶음.
  - `nvs`: t1_380의 `env_t1.sh` 설정(IBGDA, GPU NIC 처리, RC QP 하나, 링 CQ, 투명 복구 켬, IB 타임아웃 14), 대칭 heap 160 MiB,
    `ring-reduce -b 16M -e 64M -n 150 -w 2`(크기마다 준비 2번, 측정 150번, 크기마다 검증). 처음 정한 256 MiB heap과 `-n 30`은 pilot 뒤 바꿨다(12절).
  - `ddp`의 출력 양: NCCL 2.23.4는 오류 뒤 실패한 프록시 호출마다 INFO 추적 줄(`<file>:<line> -> <code>`)을 남긴다(pilot kill 데모에서 0.4 s에
    88 247줄). 에이전트가 이 꼴의 줄을 200줄까지만 넘기고 나머지는 센다. 평가 폴더에는 남기지 않은 줄 수가 적힌다(pilot 뒤 추가, 12절).
  - 하네스의 끝내기: 한 rank가 끝난 뒤 유예 `ddp` 45 s, `gin`과 `nvs` 20 s. 시행 시간 상한 `ddp` 150 s, `gin`과 `nvs` 60 s.
  - application의 환경: 에이전트의 작은 기본 환경(PATH, HOME 등)에 작업의 변수만 더하고, 노드의 LD_LIBRARY_PATH(GDRCopy 등)는 작업의 경로 뒤에
    붙인다(앞 실험의 실행기와 같다). C 표준 출력은 `stdbuf -oL -eL`로 줄 단위로 받는다.

## 7. 실험 셀, 반복 수, 대조군

반복 수는 [schedule_config.json](schedule_config.json)이 원문이다. 장애 에이전트는 작업마다 이 목록을 무작위 순서로 섞고, 시행마다 대상 rank,
`u_t`, `u_d`, 끊김 방향을 뽑는다. 평가 에이전트에게는 반복 수를 알려 주지 않는다.

| 작업 | `none` | 훅 | `kill` | `stop` | `mute` | 합 | hold |
|---|--:|---|--:|--:|--:|--:|---|
| `ddp` | 8 | `sqp` 10, `rqp` 10, `srq` 6 | 8 | 8 | 6 | 56 | D1–D4(14개씩) |
| `gin` | 8 | `qperr` 16 | 10 | 10 | 12 | 56 | G1, G2(28개씩) |
| `nvs` | 8 | `qperr` 14, `remacc` 8 | 8 | 8 | 8 | 54 | N1, N2(27개씩) |
| 합 | 24 | 64 | 26 | 26 | 26 | 166 | 8 |

대조군은 장애 없는 시행(`none`, 눈가림 안에 섞임)과 기준 실행이다. 기준 실행은 눈가림 밖이다: B0(본 실행 앞, 작업마다 3회)와 B9(본 실행 뒤, 작업마다
1회).

**시각 대응**(`blindrun.py` `derive()`).
- `kill`, `stop`, `mute`(`gin`, `nvs`): rank 0의 기준 줄 뒤 `lo + u_t (hi − lo)` s. `[lo, hi]`는 `calib.json`의 `anchor_window_s`.
- `kill`, `stop`, `mute`(`ddp`): rank 0이 `iter <n>: loss`를 찍을 때. `n = lo + u_t (hi − lo)`(반올림), `[lo, hi]`는 `calib.json`의 `iter_window`.
  pilot 뒤 초에서 반복 번호로 바꿨다(12절).
- GIN과 NVSHMEM 훅: 라이브러리의 시계(GDAKI 문맥 생성, NVSHMEM 연결)로 `hook_ms` 구간.
- DDP 훅: 순번 k(송신은 multi-send, 수신은 receive post, 알리지 않는 수신은 첫 수신 연결의 수신 완료)를 `k_send`, `k_recv`, `k_silent` 구간에서.
- 길이: `stop` `ddp` 2–12 s, `gin`과 `nvs` 1–8 s. `mute` `ddp` 6–14 s, `gin` 2–8 s, `nvs` 4–10 s. 방향은 양방향과 sunny→rain 반씩.
- `calib.json`은 pilot의 장애 없는 실행에서 기준 줄부터 끝 줄까지의 시간 T(중앙값)로 `calib.py`가 정한다: `ddp` 0.05–0.80 T, `gin` 0.02–0.85 T,
  `nvs` 0.10–0.85 T. 이 규칙은 pilot 전에 고정했다(`calib.py` 머리말).
- DDP만 pilot 뒤 바꿨다(12절). 같은 300 반복이 실행마다 5.2–15.0 s 걸려, 초로 정한 구간은 실행 안에 머물지 않는다. 같은 비율을 반복 수에 적용한다:
  `iter_window` = 0.05–0.80 × 300 = 반복 15–240. 훅의 k는 탐침 두 시행(k가 다른 데모 `ddp-<sqp|rqp|srq>-k<K>`)에서 발화 줄 전에 rank 0이 찍은
  마지막 반복 번호를 지나는 직선 k(i)로 반복 15–240에 맞춘다.

**시간 어림** `[추론]`. 시행 사이 비용(포트 확인, ssh, 남은 프로세스 확인) 약 3 s, hold마다 스냅숏과 유휴 링크 대기 약 45 s.
- `ddp`: 시작 약 6 s(import, CUDA, NCCL 초기화) + 300 반복(반복 약 25 ms, 짐작) + 종료 약 2 s ≈ 16 s. `srq`는 시간 제한 30 s가 더해져 약 50 s,
  `stop`은 길이만큼 더해진다. 56회 ≈ 26분(4 hold).
- `gin`: 시작 약 4 s, 트래픽 1 s 안, 종료 1 s ≈ 7 s. `kill`에서 살아남은 rank가 멈추면 유예 20 s. 56회 ≈ 13–17분(2 hold).
  pilot에서는 장애 없는 실행 1.6–1.7 s, `qperr` 데모 1회가 시간 상한 60 s까지 멈췄다(12절). `qperr` 16회가 모두 멈추면 약 16분이 더 든다.
- `nvs`: pilot P3(`-n 150`)에서 장애 없는 실행 6.3 s(2회), `qperr` 6.3 s, `stop` 9.6 s, `mute` 9.4 s, `kill` 22.3 s(유예까지 멈춤), `remacc` 60.1 s(시간
  상한까지 멈춤) `[측정, 데모마다 n=1]`. 54회 ≈ 19분(2 hold), `remacc` 8회가 모두 상한까지 가는 경우를 넣은 값.
- 기준 실행 12회 ≈ 2분. pilot(P1 12회, P2 12회, P3 12회) 실제 약 12분 `[측정]`. hold의 고정 비용(스냅숏, 유휴 링크 대기, 예산을 넘긴 hold의 두 번째
  pass) ≈ 13분.
- pilot 뒤 다시 어림한 본 실행: `ddp` ≈ 18분, `gin` ≈ 24분(`qperr` 16회가 모두 상한까지 멈추는 경우), `nvs` ≈ 19분, 기준 2분, 고정 비용 13분, 합계 약
  75분, 나쁜 경우 약 95분 `[추론]`. pilot을 더해 2.5시간 안이다. hold 하나는 800 s 예산을 넘기 전에 멈추고, 남은 시행은 `chain.sh`가 같은 hold로 다시
  돈다(두 번까지).

## 8. 제외 기준과 중단 기준

**제외 기준.** 제외한 시행은 다시 채우지 않고 셀마다 따로 센다(`SCORE.md` 끝 표).
- 걸리지 않은 장애(`applied == 0`): 훅 발화 줄이 없음, 에이전트가 신호를 보내지 못함(대상이 이미 끝남), 끊김을 건너뜀(`sudo iptables` 실패, 대상 포트를
  다른 프로세스가 씀, rank 0의 연결이 없음), 장애 시각 전에 application이 끝남.
- 시작 실패(`void == 1`). 빌드 확인 실패(`config_ok == 0`).
- pilot과 demo 시행은 채점하지 않는다. 기준 실행은 눈가림 시행이 아니다.

**유효성 조건.**
- DDP 결과 검사: B0의 DDP 기준 실행 3회가 rank마다 같은 해시를 내야 한다. B9도 같아야 한다. 아니면 DDP 시행의 결과가 `unknown`이 되어 D1–D7, X2,
  E1이 자료 부족이 된다(3.2절). pilot의 장애 없는 DDP 2회가 이미 다르면 태그 전에 하네스를 고친다(9.4절 4단계).
- 봉인: 실행기는 봉인의 sha256이 `PREREG.txt`의 값과 다르면 돌지 않는다. 채점기는 봉인의 sha256, 시드로 다시 만든 일정, 시행마다 기록된 항목이 모두
  봉인과 같은지 확인한다.
- 누설 검사: `handoff.py`는 평가 폴더에 남는 줄 가운데 하나라도 `strip_hooks.py`의 누설 정규식(inject, hook armed, fault fired, forced send/recv QP,
  SIGSTOP 등)에 걸리면 폴더를 만들지 않는다. 그러면 평가를 멈추고 13절에 적는다.

**중단 기준.**
- **잠금.** 모든 클러스터 명령은 `../gpu-initiated/common/cluster_run.sh -w 10800` 안에서 돈다([chain.sh](chain.sh), 꼬리표 `blind-<hold>`).
  10 800 s 안에 잠금이나 유휴 링크를 얻지 못하면 그 hold를 미룬다. `prio-` 작업에는 양보한다. hold 하나는 `timeout -s KILL 880`으로 묶는다.
- **하지 않는 것.** 실제 link down이나 flap, 재부팅, 드라이버 재적재, 커널 모듈 적재, RoCE 주소 변경, 시스템 TCP 설정 변경, GPU 컴퓨트 모드 변경.
  다른 사용자의 작업(gds-kv, NVMe-oF, gdsio, mooncake, `prio-`)은 건드리지 않는다.
- **프로세스.** 이름으로는 아무것도 끄지 않는다. application 프로세스에는 그 rank의 `node_agent.py`만 신호를 보낸다(자기가 띄운 PID, 또는 시행이
  끝날 때 그 PID의 프로세스 그룹). 에이전트는 표준 입력이 닫히면 자기 application을 끝낸다. 남은 프로세스는 이 실험만 쓰는 이름(`blind_gin_ring`,
  `blind_nvs_rr`, `ddp_entry.py`)으로 읽기만 해서 세고, 두 시행 연속이면 `STOP_left`.
- **iptables.** rain에서만, 이 시행의 연결만, 주석 `blind-<실행기 pid>-<시행 id>`. 끊김 창의 끝, 시행의 끝, 실행기 종료 때 지우고, hold마다
  `chain.sh`가 남은 `blind-` 규칙을 지운 뒤 0인지 확인한다. 남으면 `STOP_iptables`. 대상 포트에 다른 프로세스의 소켓이 하나라도 있으면 건너뛴다.
- **mlx5.** hold 앞뒤에 두 노드의 mlx5 커널 줄과 rain의 펌웨어 명령 계수를 남긴다. 새 명령 오류 줄이나 실패 계수 증가가 보이면 `STOP_mlx5`.
- **CUDA 메모리 오류.** 어느 rank든 종료 신호 11(또는 코드 139)이거나 로그에 illegal address, illegal memory access, unspecified launch failure가
  보이면 그 시행 뒤로 멈춘다(`STOP_cuda`).
- **배포.** 두 노드의 번들 md5가 다르면 hold가 시행을 돌지 않는다(`STOP_md5`).
- 어느 `STOP_*` 파일이든 생기면 `chain.sh`는 다음 hold를 돌지 않는다. 메인 세션이 원인을 12절에 적고 사용자에게 알린다.

## 9. 실행 방법과 경로

### 9.1 눈가림 절차(역할, 봉인, 평가 폴더, 공개)

| 단계 | 누가 | 무엇을 | 무엇을 보지 않나 |
|---|---|---|---|
| 예측 고정 | 메인 세션 | `predictions.csv`, `schedule_config.json`, 스크립트를 커밋 | |
| 일정 만들기 | 장애 에이전트(별도) | `schedule_gen.py make`: `/dev/urandom` 32바이트 시드, 작업마다 섞기, 대상과 `u_t`, `u_d`, 방향, 무작위 시행 id. `~/blind-seal/schedule.json`(rain, 권한 600)과 `.sha256`. 출력은 sha256과 hold별 시행 수뿐 | 시행별 내용을 출력하지 않는다 |
| pilot, 사전 등록 | 메인 세션 | 일정과 무관한 pilot, `calib.json` 확정, `PREREG.txt`에 봉인의 sha256 | 봉인을 열지 않는다 |
| 본 실행 | 메인 세션(실행기) | `blindrun.py hold`가 봉인을 읽어 시행마다 장애를 건다. 진행 출력에는 시행 id, 시간, 남은 프로세스 수만 쓴다 | 메인 세션은 봉인과 `trial.meta`를 열지 않는다. `rows_blind.py --progress`는 장애 종류 없이 센다 |
| 평가 폴더 | 메인 세션 | `handoff.py`가 저장소 밖에 폴더를 만든다: 시행마다 훅 줄을 지운 두 rank의 출력(시행 시작부터의 초), 종료 기록, 기준 실행, 안내문(9.5절), 빈 판단표 | 봉인, 장애 필드, 실행기와 에이전트 로그는 넣지 않는다 |
| 판단 | 평가 에이전트(별도) | 그 폴더만 읽고 `judgments.csv`를 쓴다 | 저장소, 결과 폴더, 봉인, 다른 에이전트의 기록 |
| 판단 고정 | 메인 세션 | `judgments.csv`와 sha256을 커밋 | |
| 공개와 채점 | 메인 세션 | `score.py`: 봉인 확인, 기계 판정, 판단 대조, `SCORE.md`. 그 뒤 봉인을 결과 폴더로 옮겨 Release에 올린다 | |

**평가 에이전트가 보는 것.** application과 라이브러리가 출력한 줄(훅 줄 제외), 줄마다 시행 시작부터의 시각, rank마다 종료 코드나 신호와 하네스가 끝냈는지,
기준 실행의 같은 자료, 작업과 장애 종류의 목록(9.5절). 시행 id는 무작위라 순서가 실행 순서를 드러내지 않는다.

**훅 줄 지우기**([strip_hooks.py](strip_hooks.py) `HOOK`): 다중 요청 복구의 `[FAULT-INJECT]` 줄과 알리지 않는 수신의 drain 줄, `RDMA_FAULT_TEST`, GIN의
`GIN/FAULT:` 줄과 `GIN/TS: TEST` 줄, NVSHMEM의 `[nvshmem-fault-inject]` 줄과 `FT_TEST`, `T1_TEST`, 훅 변수 이름(`FAULT_INJECT`)이나 하네스 변수
(`BLIND_`)가 나오는 줄, 발화 시각(`fire_mono_ms`)이 있는 줄. 라이브러리가 스스로 본 것(오류 CQE의 분류, 복구, 거절, 소켓 손실)은 남긴다. 남는 줄의
IPv4 주소는 `<ip>`로 바꾼다(판단 파일을 커밋하므로). 훅 줄은 장애
없는 시행에는 원래 없으므로, 지운 뒤에는 장애가 걸린 시행과 걸리지 않은 시행이 훅 줄로는 구별되지 않는다 `[추론]`.

**이 절차가 막지 못하는 것** `[추론]`. 실행기를 돌리는 메인 세션은 봉인을 읽을 수 있는 같은 사용자다. 지키는 것은 순서(예측 고정이 일정보다 먼저,
판단 고정이 공개보다 먼저)와 sha256 기록이다. 평가 에이전트도 같은 사용자 권한이라 안내문으로만 저장소와 봉인을 읽지 않게 한다. 18절에 한계로 남긴다.

### 9.2 작업과 빌드

- **설치(rain).** [install_venv.sh](install_venv.sh): `~/blind-venv/py310`(CPython 3.10.15 + torch 2.4.1 등), `~/blind-venv/nanoGPT`(고정 커밋, 데이터
  준비), `MANIFEST.md5`, `install_info.txt`. 시스템에는 아무것도 깔지 않는다. 2026-10-09 rain에서 끝냈다(12절).
- **DDP 진입 파일**([ddp/ddp_entry.py](ddp/ddp_entry.py)): nanoGPT `train.py`를 고치지 않고 `runpy`로 돌린다. 그 전에 결정성 설정
  (`torch.use_deterministic_algorithms(True)`, cuDNN 결정성, scaled-dot-product attention은 math 커널만), `init_process_group`의 시간 제한(30 s)만
  정하고, 끝나면 학습된 모델의 sha256을 한 줄 찍는다. NCCL은 실행기가 `LD_PRELOAD`로 바꾼다.
- **GIN 예제**([build_blind.sh](build_blind.sh) `gin`): `main.cu`, `kernels.cuh`는 그대로, 예제의 `common/src/utils.cc` 대신
  [boot/gin_boot.cc](boot/gin_boot.cc)를 링크한다. 예제의 다중 노드 경로는 MPI(`MPI_Bcast`)로 고유 ID를 나누는데, 이 테스트베드에는 MPI가 없다.
  대체 파일은 `utils.h`의 두 함수(`util_broadcast`, `run_example`)를 같은 서명으로 만들고, 고유 ID 128바이트만 [boot/rdv.h](boot/rdv.h)의 확인하는
  rendezvous로 옮긴다(gin-peer의 규칙: rank 0의 인사와 시행 고유값을 읽기 전에는 아무것도 보내지 않음).
- **NVSHMEM 예제**(`build_blind.sh nvs`): `ring-reduce.cu`는 그대로. 예제는 `nvshmem_init()`만 부르고 기본 부트스트랩은 PMI 실행기다. t1_380 빌드에는
  hydra도 MPI도 없다(`../gpu-initiated/nvshmem_ft/t1_380/build.sh`) `[소스]`. 그래서 NVSHMEM의 플러그인 부트스트랩(`NVSHMEM_BOOTSTRAP=plugin`)으로
  [boot/nvs_boot.cc](boot/nvs_boot.cc)를 준다. 이 플러그인은 NVSHMEM 자신의 UID 부트스트랩 모듈로, 라이브러리의 고유 ID 경로와 같은 순서(사전 초기화,
  rank 0의 고유 ID, 같은 rendezvous로 전달, 초기화)를 밟는다.
- **배포**([deploy_blind.sh](deploy_blind.sh), 메인 세션): 두 노드의 새 디렉터리 `~/blind-bundle`(라이브러리 사본, 실행 파일, 진입 파일, 에이전트)과
  sunny의 `~/blind-venv`(rain 트리의 바이트 사본). 확인 결과는 파일로만 받는다.

### 9.3 장애를 거는 방법

- **훅**: 대상 rank의 환경에만 넣는다. `ddp` `sqp` `NCCL_RDMA_FAULT_INJECT=k`, `rqp` `NCCL_RDMA_FAULT_INJECT_RECV=k`, `srq` 거기에
  `NCCL_RDMA_FAULT_INJECT_RECV_SILENT=1`. `gin` `qperr` `NCCL_GIN_FAULT_INJECT=local_err:<ms>`. `nvs` `qperr`
  `NVSHMEM_IBGDA_FAULT_INJECT=local_err:<ms>`, `remacc` `rem_access:<ms>`.
- **kill, stop**: [node_agent.py](node_agent.py)가 rank마다 application을 자기 세션으로 띄우고 표준 입력으로 받은 `KILL`, `STOP`, `CONT`를 그 PID에
  보낸다. sunny의 에이전트는 ssh로 이어져 있어 신호는 ssh 연결을 새로 열지 않는다(nccl-builtin은 kill마다 ssh 왕복 약 0.25 s가 들었다).
- **mute**: `gin`은 helper 포트 묶음(`NCCL_GIN_TS_PORT`부터 16개, gin-harden의 규칙 모양), `ddp`와 `nvs`는 rank 0 application이 sunny 관리망 주소와
  맺은 모든 TCP 연결의 로컬 포트(다중 요청 복구 T12의 규칙 모양). 양방향은 INPUT과 OUTPUT, 한 방향은 INPUT(sunny→rain)만 버린다.

### 9.4 메인 세션의 명령(순서대로)

경로는 이 worktree 기준이다. `R=harness/blind/results`.

1. **sunny 설치**(약 2–5분, 관리망 rsync). sunny에는 네트워크나 pip가 필요 없다. 배포 스크립트가 rain의 `~/blind-venv`를 복사한다(2단계). sunny에서 먼저
   읽기만 할 것: `ssh <sunny> 'ls -d ~/blind-venv ~/blind-bundle 2>&1; df -h ~ | tail -1'`(둘 다 없어야 하고 6 GB 이상 비어 있어야 함).
2. **배포**(약 3–5분): `bash harness/blind/build_blind.sh info` 뒤 `bash harness/blind/deploy_blind.sh harness/blind/deploy_check.txt`. 확인 파일에
   "bundle: rain == sunny", "venv_ok", 두 노드의 libnccl 매핑 하나, "existing bundles unchanged"가 있어야 한다.
3. **예측 커밋과 일정**: 메인 세션이 예측과 설정을 커밋한다(DRAFT). 그다음 장애 에이전트가 rain에서
   `python3 harness/blind/schedule_gen.py make`를 한 번 돈다(약 1 s). 봉인은 `~/blind-seal/schedule.json`과 `schedule.json.sha256`. 에이전트는
   sha256과 hold 목록만 돌려준다.
4. **pilot**(약 10분, 채점 안 함): `bash harness/blind/chain.sh $R/pilot P1`, `python3 harness/blind/calib.py $R/pilot`(`calib.json` 갱신),
   `bash harness/blind/chain.sh $R/pilot P2`. 확인: 장애 없는 DDP 2회의 해시가 rank마다 같다, 데모 장애마다 `applied`, 오류 정규식이 장애 없는
   실행에서 0줄, `python3 harness/blind/handoff.py --results $R/pilot --out <scratch>/blind_pilot_view --include-demo`가 누설 없이 끝난다. 고칠 것은
   하네스와 정규식뿐이다(3절). DDP 탐침이 발화하지 않았거나(k가 실행의 전송 수보다 큼) 두 탐침이 같은 쪽에 몰리면, `blindrun.py demo --workload ddp
   --cls <sqp|rqp|srq> --target <r> --k <K> --name ddp-<cls>-k<K>`로 다른 k를 더 돌리고 `calib.py`를 다시 돈다. 시각 대응을 바꾼 것은 12절에 적는다.
   P1, P2 검토 뒤 고친 것(12절)을 확인하는 pilot P3(약 4분): `bash harness/blind/chain.sh $R/pilot P3`, 그다음 `python3 harness/blind/calib.py $R/pilot`
   (NVSHMEM 구간이 P3의 장애 없는 두 실행에서 정해지고, DDP와 GIN은 P1 자료에서 같은 값이 다시 나온다). 확인: `nvs-none-3`, `nvs-none-4`의 결과
   검사가 맞음, P3 데모마다 `applied`, `ddp-sqp-top`과 `ddp-srq-top`(구간의 맨 위 k)이 발화, 누설 검사.
5. **사전 등록**: `PREREG.txt`를 쓴다. `SEAL`은 장애 에이전트가 알려 준 봉인의 sha256이다(봉인 폴더를 열지 않는다).
   `cd harness/blind && SEAL=<64자리> && { echo "blind-apps pre-registration"; for f in predictions.csv schedule_config.json calib.json schedule_gen.py blindrun.py node_agent.py ddp/ddp_entry.py rows_blind.py strip_hooks.py handoff.py score.py calib.py boot/rdv.h boot/gin_boot.cc boot/nvs_boot.cc hold.sh chain.sh; do echo "$f sha256 $(sha256sum < $f | cut -c1-64)"; done; echo "schedule.json sha256 $SEAL"; } > PREREG.txt`.
   상태 `PREREGISTERED`, 12절 기록과 함께 커밋 하나, 그 커밋에 `prereg/blind-apps-v1`.
6. **본 실행**(약 75–110분): `bash harness/blind/chain.sh $R/<날짜> B0 G1 G2 N1 N2 D1 D2 D3 D4 B9`. hold마다 `rows_blind.py --progress`가 시행 수,
   시작 실패, 남은 프로세스만 찍는다.
7. **평가 넘기기**: `python3 harness/blind/handoff.py --results $R/<날짜> --out <scratch>/blind_eval`. 평가 에이전트를 새로 띄워 그 폴더 경로만 주고
   `README.txt`를 따르게 한다. 돌려받은 `judgments.csv`를 `$R/<날짜>/judgments.csv`로 두고 sha256과 함께 커밋한다.
8. **공개와 채점**: `python3 harness/blind/score.py $R/<날짜> --judgments $R/<날짜>/judgments.csv`. `SCORE.md`, `trials_scored.csv`. 봉인을
   `$R/<날짜>/schedule.json`으로 복사하고(sha256 확인) 원자료와 함께 Release에 올린다.

### 9.5 평가 에이전트에게 주는 글

`handoff.py`가 아래 표시 사이를 평가 폴더의 `README.txt`로 복사한다.

<!-- evaluator-brief:start -->
blind-apps 평가 폴더 안내

당신은 이 시험의 평가자다. 이 폴더 밖의 파일(저장소, 결과 폴더, 봉인된 일정, 다른 에이전트의 기록)은 열지 않는다. 판단은 이 폴더의 내용만으로 한다.
시행은 서로 독립이다. 장애 종류마다 몇 번씩 들어 있는지는 알려 주지 않는다.

폴더
- trials/<작업>/<시행 id>/: 눈가림 시행 하나. r0.txt는 rain(rank 0), r1.txt는 sunny(rank 1)에서 application과 라이브러리가 출력한 줄이다.
  각 줄 앞의 수는 시행 시작부터의 초(rain이 줄을 받은 시각)다. 장애 주입 장치가 쓴 줄은 지웠다. exit.txt는 rank마다 종료 코드나 끝낸 신호와,
  하네스가 끝냈는지(다른 rank가 끝난 뒤의 유예 시간, 또는 시행의 시간 상한)다.
- references/<작업>/<id>/: 장애 없는 기준 실행. 같은 형식.
- judgments_template.csv: 채울 표.

작업
- ddp: PyTorch 2.4.1 DDP로 nanoGPT(문자 단위 셰익스피어, 300 반복)를 두 노드에서 학습한다. NCCL은 이 저장소의 다중 요청 복구(NCCL 2.23.4)다.
  rank 0만 반복마다 "iter <n>: loss ..." 줄을 찍는다. 마지막의 "[ddp-entry] rank=<r> final iter=<n> parameters sha256=<h>"가 그 rank가 학습한
  가중치의 해시다. 결과가 맞다 = 두 rank의 해시가 references의 같은 rank 해시와 같다. torch의 집합 연산 시간 제한은 30 s다.
- gin: NCCL 2.32.3 공식 예제 GIN ring exchange를 이 저장소의 GIN 투명 복구 빌드로 돈다. 결과가 맞다 = rank 0이
  "GIN Ring Exchange result: PASSED"를 찍고 어느 rank도 "mismatch" 줄이 없다.
- nvs: NVSHMEM 3.8.0 공식 예제 ring-reduce(16, 32, 64 MiB)를 이 저장소의 NVSHMEM 투명 복구 빌드로 돈다. 결과가 맞다 = PE 0이 세 크기 줄을 모두
  찍고 어느 PE도 "error, data[" 줄이 없다. 이 예제는 검증 오류가 있어도 종료 코드 0으로 끝난다.

장애 종류(fault_class에 쓰는 키). 시행마다 하나이거나 없다.
- none: 장애 없음.
- sqp (ddp): 한 rank의 NCCL 네트워크 연결 하나에서 송신 queue pair를 강제로 오류 상태로 옮김.
- rqp (ddp): 수신 queue pair를 오류 상태로 옮김. 라이브러리가 상대에게 알린다.
- srq (ddp): 수신 queue pair를 오류 상태로 옮김. 상대에게 알리지 않는다.
- qperr (gin, nvs): 한 rank의 GPU 주도 통신 queue pair를 모두 오류 상태로 옮김.
- remacc (nvs): 한 rank의 queue pair에서 원격 접근 권한을 거둠. 상대의 쓰기가 거부된다.
- kill: 한 rank의 application 프로세스를 SIGKILL.
- stop: 한 rank의 application 프로세스를 몇 초 SIGSTOP한 뒤 SIGCONT.
- mute: 두 노드 사이 관리망 TCP를 몇 초 끊음(이 시행의 연결만, 양방향이거나 sunny에서 rain으로 가는 쪽만). RDMA 경로는 그대로다.
target_rank: 장애를 받은 rank(0 = rain, 1 = sunny). none과 mute는 "-". 모르면 "unknown".

결과 분류(outcome). "살아남은 rank"는 kill로 죽은 rank를 뺀 rank다.
- transparent: 살아남은 모든 rank가 종료 코드 0, 오류 줄 없음, 결과가 맞음. 라이브러리의 복구 줄은 있어도 된다.
- declined: 살아남은 rank가 오류 줄을 남겼거나 0이 아닌 코드나 신호로 스스로 끝남.
- hung: 살아남은 rank를 하네스가 끝냈거나, 첫 오류가 시간 제한 오류(예: torch의 집합 연산 시간 제한).
- silent_wrong: 오류 줄 없이 모두 종료 코드 0으로 끝났는데 결과가 틀림.
- other: 그 밖.

judgments.csv: judgments_template.csv에 시행마다 한 줄을 채운다.
- trial_id, workload: 이미 적혀 있다.
- fault_class: 위의 키 하나.
- target_rank: 0, 1, -, unknown.
- outcome: transparent, declined, hung, silent_wrong, other.
- result_ok: yes, no, unknown.
- first_error_s: 시행 시작부터 첫 오류 줄까지의 초. 오류가 없으면 빈칸.
- confidence: 0.0–1.0.
- evidence: 판단의 근거가 된 파일과 시각, 짧게. 주소는 적지 않는다(평가 폴더의 IPv4 주소는 이미 <ip>로 바뀌어 있다).
다 끝나면 judgments.csv 하나만 돌려준다.
<!-- evaluator-brief:end -->

### 9.6 출력과 채점

- 결과 폴더 `results/<날짜>/raw/<시행 id>/`: `r0.log`, `r1.log`(application 출력, 줄마다 rain 수신 시각), `a0.log`, `a1.log`(에이전트 줄),
  `trial.meta`(장애의 진실, 평가 폴더에 넣지 않음). hold마다 스냅숏, `runner.log`, `chain.out`. 원자료는 커밋하지 않고 Release에 올린다.
- 채점: 9.4절 8단계. `SCORE.md`(예측마다 판정, n, 대입한 식, 거짓인 시행), `trials_scored.csv`.

## 10. 완료 조건과 QA 기준

- [ ] 모든 셀이 계획한 반복 수만큼 실행됐다. 제외(걸리지 않음, 시작 실패, 빌드 확인 실패)를 셀마다 따로 센 표가 있다.
- [ ] 봉인 확인(sha256이 `PREREG.txt`와 같음, 시드로 다시 만든 일정이 같음, 시행마다 기록된 항목이 봉인과 같음)이 `SCORE.md`에 있다.
- [ ] 판단 파일이 공개 전에 sha256과 함께 커밋됐다.
- [ ] 예측 25줄마다 판정(맞음, 틀림, 자료 부족)과 거짓인 시행 목록이 있다.
- [ ] 다른 에이전트가 `score.py`를 보지 않고 원자료에서 결과 분류, 결과 검사, 오류까지 시간, 평가 판단의 일치를 다시 셌다.
- [ ] pilot과 demo 시행이 결과에 섞이지 않았다.
- [ ] 원자료와 봉인을 Release에 올리고 DATA.md에 적었다.

## 11. 작업 체크리스트

- [x] 질문, 가설, 셀, 예측 초안(`DRAFT`)
- [x] 스크립트: 일정 생성기, 실행기와 에이전트, 훅 줄 필터, 평가 폴더 생성기, 파서와 채점기, 시각 대응, 설치, 빌드, 배포, hold와 chain
- [x] rain 준비: Python 스택 설치, 두 예제와 부트스트랩 빌드(빌드됨, 돌리지 않음)
- [x] 클러스터 없이 할 수 있는 시험: 에이전트(신호, 줄 억제, 표준 입력 종료), 파서와 채점기와 판정식(가짜 결과 폴더)
- [x] sunny 설치와 배포(메인 세션)
- [x] 예측 커밋, 장애 에이전트의 일정 생성
- [x] pilot P1, `calib.py`, pilot P2, 누설 검사(채점 안 함)
- [x] P1, P2 검토와 하네스 수정(NVSHMEM heap과 반복 수, DDP 반복 번호 기준, 출력 억제, 시작 실패 판정)
- [x] pilot P3, `calib.py` 다시, P3 검토와 정규식 수정
- [ ] 첫 봉인 폐기(메인 세션), 장애 에이전트의 새 봉인, 새 sha256으로 `PREREG.txt` 쓰기
- [ ] 고정 절 완성, 상태 `PREREGISTERED`, `PREREG.txt`를 커밋 하나로, 그 커밋에 `prereg/` 태그
- [ ] 본 실행 (`RUNNING`)
- [ ] 평가 폴더, 평가 에이전트의 판단, 판단 커밋
- [ ] 공개와 채점, 재계산 (`QA`)
- [ ] 결과 정리, 원자료 릴리스, PR
- [ ] 결론 확정 (`COMPLETE`)

## 12. 실행 기록 (시간순)

| 시각 | 무엇을 했나 | 결과와 근거(경로, 커밋, 실행 ID) |
|---|---|---|
| 2026-10-09 12:30 | worktree `~/rdma-error-wt/blind-apps`(`exp/blind-apps`, `ae3dafc9`)에서 앞 실험의 실행기, 훅, 예제 소스를 읽음 | `[소스]` 1, 4, 5절의 근거 |
| 2026-10-09 12:41–12:52 | rain 설치: 독립 실행형 CPython 3.10.15(sha256 확인), torch 2.4.1+cu121과 의존 패키지(pip, `--no-cache-dir`), nanoGPT `3adf61e1`과 데이터 준비 | `~/blind-venv/install_info.txt`, MANIFEST 18 856 파일 md5 `9dca7f6a` `[측정]` |
| 2026-10-09 12:49 | 빌드: `blind_gin_ring`(hq 헤더), `blind_nvs_rr`, `blind_nvs_boot.so`. 빌드됨, 돌리지 않음 | `<scratch>/agent_blind/out/build_info.txt` `[측정]` |
| 2026-10-09 13:00 | rain에서 GPU 없이 확인: torch import에 Stage 2 라이브러리를 `LD_PRELOAD`하면 매핑된 libnccl이 그 파일 하나, torch가 쓰는 NCCL 심볼 26개가 모두 있음, `ncclConfig_t` 정의가 같음 | 5절 `[측정]` |
| 2026-10-09 13:05–13:25 | 클러스터 없이 하는 시험: `node_agent.py`(STOP, CONT, KILL, 줄 억제 5줄 남기고 195줄 셈, 표준 입력이 닫히면 자식 종료, 남은 프로세스 0, 작은 기본 환경과 노드의 LD_LIBRARY_PATH 덧붙임), 가짜 결과 폴더(시행 10개)로 `rows_blind.py`, `score.py`(판정식, 봉인 확인, 시드 재생성), `handoff.py`(훅 줄이 평가 폴더에 0줄, 누설 검사), `blindrun.py`의 `derive()`와 `rank_spec()` | 스크래치 `blind_selftest`(저장소 밖). 클러스터에서는 아무것도 돌리지 않았다 |
| 2026-10-09 13:21:11–13:23:06 | 메인 세션: `deploy_blind.sh`(rc 0) | [deploy_check.txt](deploy_check.txt): 번들 13개 파일 rain == sunny, sunny venv `md5sum -c` 18 856개 통과, 두 노드에서 torch 2.4.1+cu121에 매핑된 libnccl은 `~/blind-bundle/s2/libnccl.so.2.23.4` 하나, 기존 번들 바뀜 없음(rain 295, sunny 356개). 주소 없음 `[측정]` |
| 2026-10-09 13:23 | 장애 에이전트: `schedule_gen.py check`, `make`(예측과 설정은 커밋 `0eeca70c`, `5895faa9`에서 바뀌지 않음) | 봉인 sha256 `14ae5e56d31294db2d3837088fa32b5eaceecaa6a8b6d237325aae69ab7bc8a2`, 31 282바이트, 권한 600. hold: `ddp` 56(D1–D4 14개씩), `gin` 56(G1, G2 28개씩), `nvs` 54(N1, N2 27개씩) `[측정, 메인 세션 보고]`. 이 문서의 작성자는 봉인을 열지 않았다 |
| 2026-10-09 13:23:23–13:26:25 | pilot P1(`chain.sh results/pilot P1`, 데모 12회, 채점 안 함) | hold rc 0, 시작 못 한 시행 0, 남은 프로세스 0. mlx5 새 줄 0(명령 오류 줄 rain 2, sunny 0 그대로, 펌웨어 명령 실패 합 31 그대로), `blind-` iptables 0/0 `[측정]` `results/pilot/`(원자료, Release 예정) |
| 2026-10-09 13:26 | 메인 세션: `calib.py results/pilot`(처음 규칙) | `ddp` T 10.407 s(2회: 9.658, 11.157), k 구간 시간 기준(`k_send` 172–12 300 등). `gin` T 0.136 s(0.138, 0.134), `hook_ms` 3–116. `nvs` "kept": 두 장애 없는 실행이 기준 줄 뒤 끝 줄 없이 끝남 `[측정]` |
| 2026-10-09 13:26:39–13:30:05 | pilot P2(데모 12회, 채점 안 함) | hold rc 0, 시작 못 한 시행 0, 남은 프로세스 0, mlx5 그대로, iptables 0/0 `[측정]` |
| 2026-10-09 13:31–13:40 | P1, P2 검토(9.4절 4단계의 확인, `rows_blind.py`로 다시 셈, 이 문서 작성자) | (1) DDP 해시: 끝까지 간 DDP 10회(장애 없음 2, 송신 2, 수신 2, 알리지 않는 수신 2, 멈춤 1, 끊김 1) 모두 두 rank가 같은 `9d051c49…` `[측정]`. 결정성과 복구의 exactly-once가 이 10회에서 성립. (2) 적용: DDP 11회와 GIN 6회 모두 `applied` 1. NVSHMEM 7회는 모두 시작 실패라 장애가 걸리지 않음(아래). (3) 오류와 복구 정규식이 장애 없는 DDP 2회, GIN 2회에서 0줄. GIN의 관리망 정규식은 시작 줄 `helper socket reconnect=1`에도 걸려 장애 없는 실행에서 rank마다 2줄 → 정규식을 고침(아래). (4) `handoff.py --include-demo`: 데모 24회, 누설 0줄, IPv4 0개(스크래치 `blind_pilot_view`) `[측정]` |
| 2026-10-09 13:31–13:40 | NVSHMEM 시작 실패의 원인 | 두 PE 모두 `transport_ib_common.cpp:517 mem registration failed (errno 14)` → `heap registration setup failed` → `nvshmemi_setup_transport failed`, 그 뒤 예제가 `cuda failed with invalid argument`로 종료 코드 255(7회 모두). rain GPU의 BAR1이 256 MiB라 256 MiB 대칭 heap을 GPUDirect로 등록할 수 없다 `[측정, 추론]`. 기준 줄(`[nvshmem-t1] PE0 … enabled:`)은 연결 직후라 heap 등록보다 먼저 나와, 처음 규칙으로는 이 실행들이 시작 실패가 아니라 거절로 셈해졌다 |
| 2026-10-09 13:31–13:40 | pilot의 관찰(예측은 그대로, 채점하지 않음) | DDP 알리지 않는 수신 QP 오류 2/2는 멈추지 않고 보내는 쪽 RETRY_EXC(훅 뒤 3.6–3.7 s)로 복구되어 투명했다. 예측 D4(멈춤)와 다르다. GIN `qperr` 1/1은 복구 줄 없이 두 rank가 시간 상한 60 s까지 멈췄다(rank 0의 QP를 ERR로 옮긴 뒤 어느 rank에도 다른 줄 없음). 예측 G2(투명)와 다르다. 예제 커널은 put 뒤 `waitSignal`로 상대의 신호를 기다린 다음에야 flush로 CQ를 보는데, 두 rank가 모두 신호를 기다리면 오류 CQE를 읽는 장치 스레드가 없어 분류와 복구가 시작되지 않는 것으로 본다 `[추론, n=1]`. GIN kill 1/1은 살아남은 rank가 FIN으로 바로 죽음 판정 뒤 유예 20 s까지 멈춤. DDP kill 1/1 거절 0.05 s, 종료 0.37 s. 멈춤과 끊김 데모는 모두 투명 `[측정, 데모마다 n=1–2]`. 예측은 측정 전에 고정했으므로 바꾸지 않는다(3절) |
| 2026-10-09 13:31–13:40 | DDP 시각 대응의 문제 | 같은 300 반복이 5.16–14.96 s 걸렸다(데모 6회의 반복 0–300 시간). 송신 탐침은 빠른 두 실행에서 나와 시간 기준 직선의 위 끝 k 12 300이 반복 약 512에 해당했다(실행은 300 반복, 송신은 반복당 약 23.9). 그대로면 `sqp`의 절반 가까이가 발화하지 않는다. `kill`, `stop`, `mute`의 초 단위 구간(0.52–8.33 s)도 빠른 실행에서는 학습 뒤에 떨어진다 `[측정, 추론]` |
| 2026-10-09 13:41 | 하네스 수정(태그 전, 예측과 설정은 그대로) | (a) NVSHMEM: `NVSHMEM_SYMMETRIC_SIZE` 256M → 160M(t1_380이 두 노드에서 쓴 값), 앱 인수 `-n 30` → `-n 150`(같은 세 크기, 트래픽을 몇 초로). (b) DDP: `kill`, `stop`, `mute`는 `iter <n>` 줄에서, 훅 k는 반복 번호 기준 직선으로(7절, `calib.py` 머리말). 다시 낸 값: `iter_window` 15–240, `k_send`, `k_recv` 428–5 814(k(i) = 69.1 + 23.94 i), `k_silent` 212–2 912(k(i) = 32.0 + 12.00 i). `calib.py`는 탐침 이름(`demo-ddp-<cls>-k<K>`)인 데모만 탐침으로 쓴다. (c) `rows_blind.py`: 시작 실패 줄(`nvs`)을 `void`에, GIN 관리망 정규식에서 `reconnect` 뺌. 다시 세면 NVSHMEM pilot 7회는 시작 실패(제외), GIN 장애 없는 실행의 관리망 줄 0. (d) DDP 출력: NCCL INFO 추적 줄 억제(200줄 뒤 셈, 6절), 평가 폴더의 안내 문구를 억제한 줄의 종류에 맞춤. (e) `hold.sh`에 pilot P3. (f) 사전 등록의 `PREREG.txt`에 봉인 폴더 대신 장애 에이전트가 알려 준 sha256을 쓰고 `hold.sh`, `chain.sh`도 넣음 | 커밋 `b3f4f451`. GIN `hook_ms` 3–116은 그대로(데모 발화가 기준 줄 뒤 58 ms, 트래픽 안) `[측정]` |
| 2026-10-09 13:42:41–13:47:28 | pilot P3(`chain.sh results/pilot P3`, 데모 12회, 채점 안 함) | hold rc 0, 시작 못 한 시행 0, 남은 프로세스 0. mlx5 새 줄 0(명령 오류 줄 rain 2, sunny 0, 펌웨어 명령 실패 합 31 그대로), `blind-` iptables 0/0 `[측정]` `results/pilot/` |
| 2026-10-09 13:48 | 메인 세션: `calib.py results/pilot`(P3 뒤) | `nvs` T 5.146 s(2회: 5.127, 5.166), `hook_ms` 515–4 374, `anchor_window_s` 0.515–4.374. `ddp`, `gin`은 P1 자료에서 같은 값(`iter_window` 15–240, `k_send`, `k_recv` 428–5 814, `k_silent` 212–2 912, `gin` `hook_ms` 3–116). 이 문서 작성자가 같은 자료로 `calib.py`를 따로 돌려 같은 값을 얻음 `[측정]` [calib.json](calib.json) |
| 2026-10-09 13:48–13:55 | P3 검토(이 문서 작성자, `rows_blind.py`로 다시 셈) | (1) `nvs-none-3`, `nvs-none-4`: 세 크기 줄(16, 32, 64 MiB) 모두, 검증 줄 0, 종료 코드 0 `[측정]`. (2) P3 데모 10회 모두 `applied` 1. `ddp-sqp-top`(k 5 814)과 `ddp-srq-top`(k 2 912)이 발화(반복 기준 구간의 위 끝이 실행 안에 있음). DDP 반복 기준 시작: `ddp-stop-iter` 반복 128, `ddp-kill-iter` 반복 229, `ddp-mute-iter` 반복 128에서 장애가 걸림 `[측정]`. (3) 정규식: 장애 없는 NVSHMEM 2회에서 처음 정규식은 죽음 1줄씩(정상 종료의 `library socket closed (FIN)`)을, `nvs-qperr-2`에서는 오류 1줄씩(복구 줄의 `dci_failed=0`이 `nvshmem.*failed`에 걸림)을 셌다. 둘 다 고침(아래). 고친 뒤 장애 없는 NVSHMEM 2회의 오류, 복구, 죽음, 관리망 줄 모두 0 `[측정]`. (4) 누설 검사: pilot 전체 데모 36회 `handoff.py --include-demo` 통과, 시행 파일에 훅 줄 0, IPv4 0(스크래치 `blind_pilot_view`) `[측정]`. (5) DDP: 끝까지 간 DDP 13회 모두 두 rank가 같은 `9d051c49…`. 출력 억제가 `ddp-kill-iter`에서 추적 줄 25 773개를 셈 `[측정]` |
| 2026-10-09 13:48–13:55 | P3의 관찰(예측은 그대로, 채점하지 않음) | NVSHMEM `qperr` 1/1 투명(시작 쪽 복구 9.7 ms). `remacc` 1/1: 두 PE가 REM_INV_REQ로 7 ms 안에 거절한 뒤 예제가 신호를 기다리며 시간 상한 60 s까지 멈춤. `kill` 1/1: 살아남은 PE는 `library socket closed (FIN)`만 남기고 거절이나 오류 줄 없이 유예 20 s까지 멈춤. 이것이 되풀이되면 예측 N4의 "3 s 안 오류"는 맞지 않는다. `stop`, `mute` 1/1 투명(끊김은 소켓 손실 뒤 다시 연결). DDP `srq-top` 1/1은 멈췄고 torch 집합 연산 시간 제한(30 s)이 두 rank를 끝냄(P1의 2/2는 투명이었다). `sqp-top` 투명, `kill-iter` 거절 0.07 s, `stop-iter`, `mute-iter` 투명(`mute-iter`에서 OOB 소켓 손실 줄) `[측정, 데모마다 n=1]` |
| 2026-10-09 13:55 | 정규식 수정(태그 전, 예측과 설정은 그대로) | `rows_blind.py`: `nvs` 오류 정규식에서 `nvshmem.*failed`를 빼고 NVSHMEM의 오류 출력 형식(`error status: <n> (`, `non-zero status:`)을 넣음. `nvs` 죽음 정규식은 라이브러리의 죽음 판정(`FAULT ... peer_fin=1`)만. 처음 정규식의 `library socket closed (FIN)`은 정상 종료에서도 나온다. 오류 정규식에 FIN 줄을 넣지는 않았다(앱에 드러난 오류가 아니다) |
| 2026-10-09 13:55 | 첫 봉인 폐기 결정(메인 세션) | 첫 봉인(sha256 `14ae5e56d31294db2d3837088fa32b5eaceecaa6a8b6d237325aae69ab7bc8a2`, 13:23 생성)은 그 뒤 하네스의 시각 대응(DDP 반복 기준, `calib.json`), NVSHMEM heap과 실행 길이, 정규식이 바뀌었으므로 쓰지 않는다. 메인 세션이 이 커밋 뒤 `~/blind-seal`을 열지 않은 채 `~/blind-seal-discarded-1`로 옮긴다(옮긴 시각은 메인 세션이 적는다). 새 봉인은 모든 하네스 변경(이 커밋까지) 뒤, 태그 전에 장애 에이전트가 `schedule_gen.py make`로 만든다. `predictions.csv`와 `schedule_config.json`은 첫 봉인 때와 같다(커밋 `0eeca70c` 이후 diff 없음) |

## 13. 사전 등록 이후 변경

| 날짜 | 무엇을 | 이유 | 영향 범위 | 커밋 |
|---|---|---|---|---|

## 14. 원자료와 결과표

| 무엇 | 경로 또는 Release 자산 | n |
|---|---|--:|

## 15. 결과 요약

`[미확인]` 아직 실행 전이다.

## 16. QA와 재현성

## 17. 결론

## 18. 한계

- 9.1절의 "이 절차가 막지 못하는 것": 메인 세션과 평가 에이전트가 같은 사용자 권한이라 봉인을 읽을 수 있다. 순서와 sha256 기록으로만 지킨다.
- pilot이 보인 짧은 실행 `[측정, 추론]`: GIN 예제의 트래픽은 0.13–0.14 s라 2–8 s 관리망 끊김은 거의 모두 트래픽 뒤 정리 단계와 겹치고, 시행이 끝나면
  끊김도 끝난다(실제 끊김 길이는 시행 끝까지). DDP의 6–14 s 끊김도 학습 끝을 넘기면 시행 끝에서 잘린다(pilot 데모: 10 s 중 4.8 s).
- pilot 뒤 바꾼 하네스(12절 13:41, 13:55): 시각 대응의 단위(DDP), NVSHMEM heap과 반복 수, 몇몇 정규식. 예측과 장애 구성은 바꾸지 않았다. 이 변경이
  첫 봉인(sha256 `14ae5e56…`, 13:23) 뒤였으므로 메인 세션이 첫 봉인을 열지 않은 채 폐기했고, 본 실행의 일정은 모든 하네스 변경 뒤, 태그 전에 만든 새
  봉인이다. 다만 하네스 변경은 첫 봉인이 있는 동안 pilot(장애 종류를 고른 데모)을 보고 했다. pilot은 일정과 무관한 데모였다.
- pilot이 보인 예측과 다른 동작 `[측정, 데모마다 n=1–3]`: DDP 알리지 않는 수신 QP 오류 3회 중 2회 투명(D4는 멈춤을 예측), GIN QP 오류 1회 멈춤(G2는
  투명을 예측), NVSHMEM kill 1회는 오류 줄 없이 멈춤(N4는 3 s 안 오류를 예측). 예측은 측정 전에 고정한 그대로 채점한다.
- GIN과 NVSHMEM 예제는 상대의 신호를 기다리는 동안 CQ를 보지 않는다. 그래서 QP 오류나 상대의 죽음이 그 대기 중에 오면 라이브러리가 알아채지 못하고
  application이 멈출 수 있다 `[추론, pilot n=1씩]`. 이것은 이 실험이 재려는 동작이지 하네스 문제가 아니라고 보고 하네스를 바꾸지 않았다.

## 19. 다음 작업

## 20. 참고자료

- `../nccl-integration/stage2/`, `../nccl-integration/builtin/`, `../gpu-initiated/gin_recovery/peer/`, `../gpu-initiated/nvshmem_ft/t1_380/`
- nanoGPT: `https://github.com/karpathy/nanoGPT`(커밋 `3adf61e1`)
- NCCL 2.32.3 예제: 스크래치 `agent_nb/nccl-232/docs/examples/`, NVSHMEM 3.8.0 예제: 스크래치 `agent_t1_380/src/examples/`
