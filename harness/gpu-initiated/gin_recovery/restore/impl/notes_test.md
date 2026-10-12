# notes_test.md: 작업 묶음 10(시험 프로그램, 실행기, 셀, 채점기)의 12절 행

병렬 분담 규칙(PARALLEL.md)대로 이 브랜치(`exp/gin-restore-test`)는 `EXPERIMENT.md`를 고치지 않는다. 아래 행은 통합 때
메인 세션이 12절로 옮긴다. 표시: `[빌드됨]`은 컴파일만 함(실행 아님), `[시험함]`은 CPU 자체 시험을 돌림.

| 시각 | 무엇을 했나 | 결과와 근거 |
|---|---|---|
| 2026-10-12 | 충돌 확인(코드 전): 이 묶음은 `impl/test/` 아래 새 파일과 이 파일만 만든다. dev, host, spare 브랜치의 소유 파일(장치 헤더, 호스트 파일, `bootstrap.cc` 등)은 읽기만 한다. 시험 프로그램은 공개 API(`nccl.h.in`의 Resume, Step, Register)와 9.8절 workload만 본다. 클러스터 안전: 실행기는 메인 세션만 `cluster_run.sh` 안에서 돌리고, 이 브랜치는 클러스터 행동을 하지 않는다 | 막는 충돌 없음 |
| 2026-10-12 | 시험 workload `impl/test/gin_rs.cu`(9.8절): 4-rank GIN, 받는 rank마다 컨텍스트 하나(`ctx=dst`), 상대를 모르는 untimed `waitSignal`. 단계마다 보내는 칸을 장치가 window 안의 상태 이력 x(s)에서 만들고 put + 신호 1, 받은 칸 N−1개로 x(s+1). 끝에서 호스트가 모든 받은 칸, 상태 이력, 두 신호의 최종 값을 같은 함수로 계산한 기준과 비트 단위로 비교하고, 비동기 오류를 폴링한다. 체크포인트 hook(`ncclGinRestoreStep`)을 커널 사이에, `ncclGinRestoreResume`을 devComm 생성 뒤에, 단계 실행 수 버퍼를 `ncclGinRestoreRegister`로. 빌드 둘: `gin_rs`(이 계층 헤더, `-DNCCL_GIN_RESTORE_DEVICE`)와 `gin_rs_hk`(hk 헤더, 매크로 없음, 복원 API는 dlsym; 복원 없는 대조용) | `[빌드됨]` rain, nvcc 12.8, sm_75+sm_86, 경고 0. 마지막 빌드 gin_rs `db13fb7e`(include `2882a4be`, lib `1e19d678`), gin_rs_hk `a42374bc`(include `a27dac89`, lib `2913c777` = hk). 두 바이너리 모두 정의 안 된 복원 기호 0. `impl/test/build_rs_test.sh` |
| 2026-10-12 | 9.8절 workload에서 찾은 경합과 바꾼 것(메인 세션이 9.8절에 반영할 것): 신호 하나(신호 0)를 모든 단계가 함께 쓰면, 한 단계 앞선 rank의 다음 단계 put이 느린 다른 rank의 이번 단계 put보다 먼저 세어져, 이번 단계의 칸이 비어 있는데 문턱이 채워질 수 있다(9.7절 1번 위반) `[추론]`. 앞선 rank는 많아야 한 단계 앞이므로 단계 s의 put은 신호 s mod 2에 더하고 단계 s는 신호 (s mod 2) ≥ (N−1)(s/2 + 1)을 기다린다(여전히 상대를 모름). `ginSignalCount = 2` | 코드(`gin_rs.cu` 머리말). 9.8절의 "신호 0" 문장과 다름 |
| 2026-10-12 | 실행기(첫 판; kill의 차례와 체크포인트 멈춤 kill은 아래 두 행에서 바뀜): `run_rs.sh`(4-rank 복원 trial; 예비 프로세스는 kill 대상과 같은 노드·GPU; 기록한 PID로만 kill, 대상의 100단계 줄이 rain에 닿은 뒤 500 µs; 체크포인트 멈춤 셀은 `GIN_RS_DIE_IN_STEP`으로 자기에게 SIGKILL; 모든 줄을 rain의 수신 시각으로 찍음; 호출자의 NCCL_/GIN_ 변수 지움; IPv4 가림). `run_cost.sh`(비용 팔 여덟: 로그 넷, 무장 전 둘, fail-fast 분기 둘; 9.15.6 driver). `cells_rs.sh`, `cells_rs.json`, `hold_rs.sh`(snapshot, STOP, BAR1 Free 128 MiB 시작 문턱, 시행마다 QUERY_QP 상한, 남은 프로세스 셈), `chain_rs.sh`, `deploy_rs.sh`(새 디렉터리는 `~/rs-bundle` 아래에만, 앞뒤 md5, ldd, 산출물마다 md5 필수). 회귀 셀은 `../../../remaining/run_mr_hr.sh`를 고치지 않고 재사용하고, gin_mr은 이 계층 헤더로 다시 빌드(fail-fast는 매크로 없이, hold 변형은 매크로와 함께; 옛 hr 헤더 빌드는 hold 갈래를 조용히 지나침) | `[빌드됨]` cost gin_ts2 `360cb98b`(매크로), gin_ts2_ff `6ed24f6a`, mr ff `0c4d0d86`, mr hold `a5f32e38`, 모두 `-Werror` 경고 0. 클러스터 실행 없음 |
| 2026-10-12 | 채점기: `rows_rs.py`(원자료와 수신 시각 줄 → trial 행), `score.py`(3절 판정식을 `../../../s2_close` 문법 그대로, "자료 부족" 규칙(계획의 75% 미만 또는 라이브러리 열이 모두 빔), 셀별 제외 표, 회귀는 gin-remaining의 행 코드와 status4를 그대로 쓰고 판정은 gpu-detect RG8, RG9의 꼴, 비용은 9.15.6의 "갈림"), `predictions_rs.csv`(3절 예측의 초안 판정식, 찾는 키 그대로), `selftest_rs.py` | `[시험함]` `python3 selftest_rs.py`: 파서 명령 통과, 채점기 사례 A(통합 가정, 모두 맞음, 로그·무장 전 비용은 문턱 대기), B(통합 전: kill 셀과 라이브러리 열 예측은 자료 부족, strict와 refuse는 맞음), C(실패 넷은 틀림), D(파서 규칙: 죽음 판정 줄은 거절이 아님, 이유가 다르면 다름, 강제 아래 strict=0, 끝내지 못한 생존 rank는 붙잡힘이 아님, exit 137은 kill 적용) 통과 |
| 2026-10-12 | 독립 검토(같은 모델의 읽기 전용 에이전트): 막는 문제 열하나(상대 경로 셋이 틀림, stem 변경 뒤 stop 검사 둘이 안 맞음, 보내는 칸을 호스트가 다시 써서 9.7절 12번 위반, 받은 칸의 기준 비교와 신호·비동기 검사 없음, 파서 셋(거절 정규식, 이유 정규식, fall-through 셈), hk 대조가 복원 기호 없이 못 돎, strict와 회귀 판정식, 수신 시각 없음, 배포 확인이 늘 "바뀜", 8절 문턱(BAR1, QUERY_QP), 여러 낱말 env가 쪼개짐)와 메모 | 모두 반영(위 행들). 재검토는 아래 행 |
| 2026-10-12 | 메인 세션이 전한 다른 브랜치의 이름(`rs_spare_api.h`, `rs_hold_api.h`, `rs_ckpt_api.h`, `rs_log_api.h`를 읽기만 하고 확인)에 맞춤: hold rank마다 `NCCL_GIN_RESTORE_RECORD`(노드 안 시행 전용 경로, 시행 뒤 지움, 옮기지 않음), 예비 프로세스는 kill할 rank의 Resume 줄 뒤에 `NCCL_GIN_RESTORE_REPLAY`로 그 기록을 재생하며 뜨고(`GINRS spare_ready` 줄을 냄), 정상 중 kill은 그 준비 줄 뒤로 미룸. 체크포인트 멈춤 중 kill은 hook이 돌아온 뒤가 아니라 hook 안(들어간 뒤 300 µs, 노드 안 파일로 무장)으로 고침(앞 판은 멈춤이 끝난 뒤였음). 되살린 rank의 시작 단계는 자기 덩어리로 정함. Resume 거절의 이유는 `ncclGetLastError`(kv `resume_why`)로 비교 | `[빌드됨]` gin_rs `abb897fe`, gin_rs_hk `fe8f3207`(경고 0), `[시험함]` 자체 시험 통과 |
| 2026-10-12 | 재검토(같은 모델의 읽기 전용 에이전트): 첫 검토의 막는 문제 열하나는 모두 풀림. 새 막는 문제 셋: 활성화되지 않은 예비 프로세스의 watchdog이 STOP_nic를 씀, 8절의 "예비 프로세스가 활성화 전에 시작에 실패함" 제외가 없음, 복원을 기대하는 셀의 Resume 거절이 "틀림"으로 셈. 모두 반영: 오류 키는 살아 있는 rank의 kv에서만 보고 예비 프로세스의 watchdog은 `spare_wait.txt`에 적기만; `spare_start_fail` 제외(meta `spare_wanted`, `spare_ready`); 그런 거절은 설정 실패로 빼고 hold는 STOP_nic. 막지 않는 것도 반영: 시행 한도 240 s, 되살림 조건을 예비 프로세스와 덩어리로, kill 셀의 생존 rank는 abort 전 3000 ms 기다림, hold 고리의 입력을 fd 3으로, 비용 실행의 유효성(win_flags 0x3, tx_done = 반복 수), 시행 시작 때 GPU의 다른 프로세스(`foreign_gpu` 제외). 회귀 판정은 gpu-detect처럼 RG9의 꼴(gin-remaining DG1과 DG3)이고 DG2, DG4는 넣지 않음 | `[시험함]` 자체 시험 통과 |
| 2026-10-12 | 메인 세션이 전한 예비 프로세스 브랜치(작업 묶음 8)의 요구: 모든 프로세스 `NCCL_GIN_Q4_QPWATCH_MS=0`(실행기 셋 모두); 예비 프로세스의 env(`NCCL_GIN_RESTORE_SPARE`, 같은 노드의 기록 파일을 `NCCL_GIN_RESTORE_REPLAY`로, `NCCL_GIN_RESTORE_SPARE_PORT`, `NCCL_MULTI_RANK_GPU_ENABLE=1`)는 이미 맞음. pilot 항목 셋을 더함: 4 rank에서 예비 프로세스의 재생과 활성화 시간(`spare_replay_ms`, `spare_activate_ms`), 예비 프로세스의 strace(`SPARE_STRACE=1`: 준비 전후의 상대 connect, 자기 rank와 다른 rank의 proxy UDS를 따로; 원문은 노드에서 셈으로만 바꾸고 지움), 음성 대조 둘(`NEG_REPLAY=1`: 자른 사본, 크기 칸을 바꾼 사본; 9.15.4 B1의 같은 자리). hold `P3`(`rs4_kill3_strace`, `rs4_spare_neg`) | `[빌드됨]`, `[시험함]` 자체 시험 통과(셈 프로그램은 합성 trace로도 시험) |
| 2026-10-12 | 마지막 확인(같은 모델의 읽기 전용 에이전트): 막는 문제 없음. 메모 반영: 음성 대조의 재생 실패 판정을 예비 프로세스 브랜치의 실제 WARN 줄(잘림, diverged, 쓸 수 없는 기록, 끝 뒤의 호출, 허용 밖의 바이트)로 좁힘(정보 줄 `replay ON`, `replay mark=`은 실패가 아님; 합성 시험 더함); Resume이 덩어리 없이 돌아온 예비 프로세스는 단계 0부터 돌지 않고 abort와 exit 3; kill 셀(예비 프로세스 있음)에서 rank 0이 출발 문(`RS_START_GATE`)에서 예비 프로세스의 준비를 기다리고 barrier가 다른 rank를 붙잡음(느린 재생에 kill이 놓치지 않게), 그래서 그 셀의 watchdog 200 s, hold의 시행 한도 300 s. 남은 pilot 확인: 시행 시작 때의 `foreign_gpu`가 앞 시행의 끝난 프로세스를 세지 않는지, 살아 있는 rank가 끝난 뒤 기록 파일이 남아 음성 대조가 도는지 | `[빌드됨]` gin_rs `db13fb7e`, gin_rs_hk `a42374bc`(경고 0), `[시험함]` 자체 시험 통과 |
| 2026-10-12 | 메인 세션 결정(초안, 사전 등록 전): 예비 프로세스 없음 셀을 둘로 나눔. (1) `rs4_kill3_nospare`, 예측 `nospare_failfast`: 예비 프로세스를 등록하지 않음(`NCCL_GIN_RESTORE_SPARE_ADDR` 없음) → 무장되지 않음 → hk와 같은 fail-fast(hold 시작 줄 없음, 거절 줄, 죽음 판정 + 2000–2500 ms에 degraded로 풀림); 무장이 필요 없어 통합 전에도 채점. (2) `rs4_kill3_spareabsent`, 예측 `spare_absent_fallback`: 예비 프로세스를 등록하고 준비시킨 뒤 rank 3보다 먼저 기록한 PID로 끔(`SPARE_KILL_FIRST=1`) → hold → hold 시작 뒤 약 1 s(초안 500–1500 ms)에 fallback → 그 뒤 2000–2500 ms에 degraded로 풀림. 시각 열 `hold_to_fallback_ms`, `spare_absent_ok`, `nospare_failfast_ok`, `hold_started`; 예비 프로세스가 rank보다 먼저 꺼지지 않으면 제외(`spare_not_killed`). host 브랜치의 실제 줄(`hold of rank P started`, `the restore of rank P (incarnation I) is given up`, `rank P restored as incarnation`)에 맞춤(앞서 가정한 fallback과 복원 줄의 꼴은 틀렸음). 창은 초안이고 host 브랜치가 `notes_host.md`에 적을 규칙과 pilot으로 고정 | `[시험함]` 자체 시험 통과(사례 A 둘 다 맞음, B 등록 없음은 맞음과 등록했으나 없음은 자료 부족, C 늦은 fallback은 틀림, D 늦게 꺼진 예비 프로세스는 제외) |
| 2026-10-12 | 사전 상태: `impl/test/PILOT.md`(셀마다 pilot이 보일 것, pilot이 고정하는 문턱과 n, 보류 중인 overhead 예산, 메인 세션 명령, 통합 뒤 확인할 것) | 문서 |

## 통합자에게: 이름과 가정한 줄

시험 프로그램과 실행기는 공개 API와 9.8절 workload만 본다(PARALLEL.md). 아래 이름은 `impl/rs_layer.diff`와 다른 브랜치가
공개한 헤더(`rs_spare_api.h`, `rs_hold_api.h`, `rs_ckpt_api.h`, 스페어 브랜치의 `rs_layer_spare.diff`; 읽기만)에서 확인했다.

- 확인됨: `NCCL_GIN_FAULT_POLICY=hold`, `NCCL_GIN_RESTORE`, `NCCL_GIN_RESTORE_MS`, `NCCL_GIN_RESTORE_RESUME_MS`,
  `NCCL_GIN_RESTORE_LOG_ENTRIES`, `NCCL_GIN_RESTORE_LOG_MEASURE`, `NCCL_GIN_RESTORE_CHECKSUM`(off, sampled, full),
  `NCCL_GIN_RESTORE_CKPT_STEPS`(체크포인트는 그 단계 이름으로 찍힘), `NCCL_GIN_RESTORE_RECORD`(hold rank마다 초기화 기록 파일;
  라이브러리가 0600, O_EXCL로 만듦; 관리 주소가 들어 있어 노드 밖으로 옮기지 않고 시행 뒤 지움; 없으면 Resume이 거절),
  `NCCL_GIN_RESTORE_REPLAY`(예비 프로세스가 같은 노드의 그 기록을 재생), `NCCL_GIN_RESTORE_SPARE`, `NCCL_GIN_RESTORE_SPARE_PORT`
  (예비 프로세스의 활성화 포트; 짝이 원래 프로세스의 PID와 시작 시각을 실어 보냄), `NCCL_GIN_RESTORE_SPARE_ADDR`(원래 rank에만
  줌), 빌드 매크로 `NCCL_GIN_RESTORE_DEVICE`. 공개 API: `ncclGinRestoreResume(comm, devComm, &step, blob, &bytes)`(예비
  프로세스의 Resume이 활성화를 기다림), `ncclGinRestoreStep(comm, step, blob, bytes, &stableStep)`,
  `ncclGinRestoreRegister(comm, buff, size)`, `NCCL_GIN_RESTORE_STEP_NONE`; window 보고 줄
  `GIN/RS: window MR rank=.. strict=.. forced=.. flag_strict=.. ro=..`; Resume 거절의 이유는 모든 rank에서 `ncclGetLastError`
  (시험 프로그램이 kv `resume_why`로 적고 채점기가 rank 사이에서 비교).
- 실행기의 차례(확인된 이름에 맞춤): hold rank는 모두 `NCCL_GIN_RESTORE_RECORD=<그 노드의 시행 전용 /tmp 경로>`. 예비
  프로세스는 kill할 rank의 `GINRS resume` 줄(기록이 끝남)이 온 뒤에 같은 노드에서 `NCCL_GIN_RESTORE_REPLAY=<그 rank의 기록>`,
  `NCCL_GIN_RESTORE_SPARE`, `NCCL_GIN_RESTORE_SPARE_PORT`로 띄우고, 정상 중 kill은 예비 프로세스의 `GINRS spare_ready` 줄 뒤에
  한다. 체크포인트 멈춤 중 kill은 예비 프로세스가 준비된 뒤 노드 안 파일로 무장하고, 다음 체크포인트 단계(단계 % CKPT_STEPS = 0
  으로 가정, pilot이 확인)의 hook에 들어간 뒤 300 µs에 자기에게 SIGKILL.
- 되살린 rank의 시작 단계는 Resume의 `*step`이 아니라 시험 프로그램 자신의 덩어리(`blob.step` = 체크포인트 k의 다음 단계)로
  정한다. `*step`이 체크포인트의 이름이든 다음 단계든 같게 동작한다(kv `revived`, `start_step`, `blob_step`).
- 가정한 라이브러리 줄(`rows_rs.py`가 읽음; 없으면 그 예측은 자료 부족; 통합 때 실제 줄에 맞춤):
  `GIN/RS: rank R: suppress ... budget=B ... suppressed=S`(억제), `GIN/RS: rank R: ... published`(생존 rank의 게이트 재개),
  `GIN/RS: rank R: checkpoint K stable`(확정 체크포인트),
  `GIN/RS: rank R: ... input pause ... pause_us=U`(입력 멈춤). host 브랜치에서 확인한 줄: `GIN/RS: rank R: hold of rank P
  started`(hold 시작), `GIN/RS: rank R: the restore of rank P (incarnation I) is given up`(fallback), `GIN/RS: rank R: rank P
  restored as incarnation`(복원), `GIN/RS: rank R: restore round with rank P published`(게이트 재개). 죽음 판정 줄 `judged dead`와
  거절 줄 `GIN/TS: declined rank=`, `why=peer-dead|declined|degraded`는 hk에 이미 있다.
- 실행기가 모든 rank에 넣는 설정(9.10.8절): GIN 연결 FULL, `NCCL_GIN_NCONNECTIONS=1`, `NCCL_MULTI_RANK_GPU_ENABLE=1`,
  `NCCL_SYM_GIN_KERNELS_ENABLE=0`, `NCCL_RMA_DISABLE=1`, `NCCL_NUM_RMA_CTX=0`, `NCCL_GIN_TYPE=3`, `NCCL_RAS_ENABLE=0`.
- 셀 이름과 예측 ID는 3절, 7절의 찾는 키를 그대로 쓴다. 회귀 예측은 `regression_none`, `regression_kill3`으로 나눴고 비용
  예측은 `cost_log`, `cost_unarmed`, `cost_ff`다.
