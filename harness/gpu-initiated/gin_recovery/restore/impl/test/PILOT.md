# gin-restore pilot 준비 (work package 10)

이 문서는 pilot이 셀마다 무엇을 보여야 하는지, pilot이 어떤 문턱과 반복 수(n)를 고정하는지 미리 적는다. pilot은
모든 셀을 작은 n으로 돌려(hold `P1`, `P2`, `P3`, `COSTPILOT-<노드>`) 2, 3, 7, 8절의 초안 값을 정하고, 그 뒤 사전 등록한다.
문턱과 n은 지금 모두 초안(DRAFT)이다. `score.py`는 `predictions_rs.csv`의 초안 판정식을 그대로 적용한다.

표시: `[측정]` 원자료에서 확인, `[미확인]` 아직 확인하지 않음, `[추론]` 해석.

## 지금 상태 (통합 뒤, 2026-10-12)

복원 라이브러리 계층(작업 묶음 1–10)을 네 갈래에서 하나로 합쳤다(`EXPERIMENT.md` 12절의 통합 행, `impl/rs_layer.diff`).
라이브러리와 시험 프로그램은 빌드만 됐고 GPU에서 돌리지 않았다("빌드됨"). 순수 함수는 CPU 단위 시험을 했고("시험함"),
호스트 쪽의 소켓, 스레드, NIC 복사 경로와 CUDA의 길(입력 멈춤, drain 확인, FETCH와 STATE, 복원 라운드, 로그 내보내기와
가져오기, 예비 프로세스의 활성화와 handshake)은 단위 시험 밖이라 pilot에서 처음 돈다. 모든 hold rank는 초기화
기록(`NCCL_GIN_RESTORE_RECORD`)을 그 노드의 시행 전용 경로에 남기고, 실행기가 시행 뒤 지운다(관리 주소가 들어 있어 노드
밖으로 옮기지 않음). 예비 프로세스는 `NCCL_GIN_RESTORE_SPARE`, `NCCL_GIN_RESTORE_REPLAY`, `NCCL_GIN_RESTORE_SPARE_PORT`로
뜨고, `ncclGinRestoreResume` 안에서 활성화를 기다린다(`NCCL_GIN_RESTORE_SPARE_WAIT_MS`, 기본 1시간; 실행기는 따로 주지
않음). 통합의 빌드와 드라이버의 md5는 아래 "메인 세션 명령"에 있다.

## 셀마다 pilot이 보여야 할 것

셀마다 돌릴 빌드를 `cells_rs.json`의 `driver`로 정한다(2026-10-12 사용자의 설계 바꿈: 측 표 포인터는 Resume이 성공해야
장치에 실리고, 매크로 없이 빌드한 프로그램이 부른 Resume은 모든 rank에서 같은 이유로 거절됨). 복원 셀은 모두 매크로로 빌드한
`gin_rs`, 복원 없는 대조는 hk 헤더의 `gin_rs_hk`, 회귀 셀은 fail-fast가 `mr/ff`(매크로 없음)이고 hold 변형이 `mr/hold`(매크로)다.
다른 빌드로 돈 시행은 뺀다(`config_driver`).


- `rs4_none` (@rs): 모든 rank가 장애 없이 600단계를 끝내고(exit 0), 받은 칸과 상태 이력과 최종 신호 값이 호스트 기준과
  비트 단위로 같다(`data_equal`). 라이브러리의 window 등록 보고 줄이 모든 등록을 strict로 강제한다(`strict_forced`).
  통합 뒤: 체크포인트마다 생존 rank의 입력 멈춤 시간(`ckpt_pause_ms`)과 복원 0.
- `rs4_none_off` (@rs): 같은 데이터 결과, 강제 0(`strict_notforced`).
- `rs4_kill3` (@rs, 통합 뒤): 예비 프로세스는 rank 3의 Resume 줄 뒤에 rank 3의 초기화 기록을 재생하며 뜨고, 준비 줄
  (`GINRS spare_ready`) 뒤 rank 3의 100단계 이상 줄이 rain에 닿으면 500 µs 뒤에 기록한 PID로 rank 3을 kill하고 되살린다. 생존 rank의 대기가 풀리지 않고(`wait_held`), 모든 rank의 데이터가 기준과 같고(`data_equal`), 생존 rank는
  다시 실행하지 않고(`no_reexec`), 되살린 rank가 끝까지 가며(`revived_done`), 억제 수가 통로마다 맞고
  (`suppress_exact`), 복원 시간(`restore_time`).
- `rs4_kill3_ckpt` (@rs, 통합 뒤): 예비 프로세스가 준비된 뒤 무장되어, rank 3이 다음 체크포인트 단계(단계 % 20 = 0으로
  가정)의 hook에 들어간 뒤 300 µs에 자기에게 SIGKILL(입력 멈춤 중). kill 앞에 확정된 체크포인트에서 복원(`ckpt_kill`).
  pilot은 그 단계가 실제로 체크포인트를 찍는지와 멈춤이 300 µs보다 긴지를 라이브러리의 체크포인트 줄로 확인한다.
- `rs4_kill1` (@rs, 통합 뒤): rank 1(rank 3과 같은 GPU) kill도 같은 결과(`kill_other`).
- 예비 프로세스가 없는 경우는 두 셀로 나눈다(2026-10-12 메인 세션 결정; 앞의 초안 셀 하나를 대신함).
  - `rs4_kill3_nospare` (@rs): 예비 프로세스를 등록하지 않음. 그 rank는 무장되지 않아 hk와 같은 fail-fast다: hold 시작 줄이
    없고, 거절 줄이 있고, 생존 rank의 대기가 죽음 판정 + 2000–2500 ms 안에 degraded로 풀린다(`nospare_failfast`). 무장이
    필요 없으므로 통합 전에도 잰다.
  - `rs4_kill3_spareabsent` (@rs, 통합 뒤): 예비 프로세스를 등록하고 준비시킨 뒤, rank 3보다 먼저 기록한 PID로 끈다
    (활성화 전에 없음). 생존 rank는 붙잡았다가 hold 시작 뒤 약 1 s(초안 500–1500 ms)에 fallback하고, 그 뒤 2000–2500 ms
    안에 대기가 degraded로 풀린다(`spare_absent_fallback`). 시각은 host 브랜치의 줄(`hold of rank P started`, `the restore
    of rank P ... is given up`)과 GINRS 풀림 줄의 수신 시각으로 잰다. 예비 프로세스가 rank보다 먼저 꺼지지 않은 시행은 뺀다.
- `rs4_kill3` (@hk): 복원이 없는 빌드(`gin_rs_hk`, hk 헤더). 생존 rank의 대기가 죽음 판정 + 2000–2500 ms 안에 degraded로
  풀린다(`control_degraded`). 통합과 상관없이 돈다.
- `rs4_refuse_symgin`, `rs4_refuse_gintype`(GIN 종류 proxy = 2), `rs4_refuse_restoreoff1` (@rs): 모든 rank의 Resume이
  오류를 돌려주고, 이유(`ncclGetLastError`)가 rank 사이에서 같으며, 오류 없이 fail-fast로 넘어간 rank가 없다
  (`refuse_reason`). 작업 묶음 2가 이미 구현했으므로 통합 전에도 확인된다. `rs4_refuse_gintype`은 Resume 전에 devComm 생성이
  실패할 수 있다(그러면 시행은 시작 실패로 빠지고 셀은 자료 부족). pilot이 이 셀이 Resume까지 가는지 확인한다.
- `rs4_refuse_nomacro` (@rs, `gin_rs_nomacro`): 매크로 없이 이 계층의 헤더로 빌드한 프로그램이 hold 정책으로 Resume을
  부른다. 모든 rank가 같은 이유("program not built with NCCL_GIN_RESTORE_DEVICE")의 오류를 받고(`refuse_reason`), 그 뒤
  fail-fast로 끝까지 돌아 trap 없이 결과가 기준과 같다(`refuse_nomacro_clean`). 이 거절은 지역 판정의 29번 조건이다(통합한
  계층에 있음).
- `reg_mr4_none`, `reg_rm4_kill3_untimed`와 hold 변형 (@rs): gin-remaining의 `gin_mr.cu`를 이 계층의 헤더로 빌드한
  것(fail-fast는 매크로 없이, hold 변형은 매크로와 함께). 원래 판정(gpu-detect RG8, RG9의 꼴)과 같다(`regression`).
- 예비 프로세스(작업 묶음 8이 넘긴 pilot 항목, hold `P3`와 kill 셀): (1) 4 rank에서 예비 프로세스의 재생 시간(시작 줄 →
  `GINRS spare_ready`, `spare_replay_ms`)과 활성화 시간(kill 줄 → 예비 프로세스의 Resume 줄, `spare_activate_ms`).
  (2) `rs4_kill3_strace`: 예비 프로세스를 strace로 띄워(9.15.4의 방법; 원문 trace는 노드 밖으로 옮기지 않고 셈만 옮김),
  준비 줄 전의 상대 connect가 0이고(초기화 재생은 아무와도 말하지 않음), 준비 뒤의 상대 connect는 REJOIN과 자료 소켓뿐이며,
  NCCL proxy의 UDS(`/tmp/nccl-socket-<rank>-<hash>`) connect를 자기 rank의 것과 다른 rank의 것으로 따로 센다.
  (3) `rs4_spare_neg`: 장애 없는 시행이 끝난 뒤 rank 3의 기록을 반으로 자른 사본과 첫 항목의 크기 칸을 바꾼 사본으로 예비
  프로세스 둘을 재생하면 둘 다 초기화 재생에서 실패하고(`GIN/RS: replay` 줄) 상대 connect가 0이다(`neg_cut_failed`,
  `neg_field_failed`, `neg_peer_connects`). 사본은 기록 옆에 0600으로 만들고 시행 뒤 지운다.
  모든 프로세스는 `NCCL_GIN_Q4_QPWATCH_MS=0`이다.
  pilot이 함께 볼 것: 살아 있는 rank가 끝난 뒤에도 기록 파일이 남아 음성 대조가 도는지(라이브러리가 끝날 때 지우면 `negs`가
  비고 열이 빔), 시행 시작 때 `foreign_gpu`가 앞 시행의 막 끝난 프로세스를 세지 않는지.
- 비용 셀(@rsp, @hkp; 2026-10-12 메인 세션 결정): 복원 길의 팔 다섯은 모두 매크로로 빌드한 driver이고 라이브러리의 재기만
  하는 모드를 쓴다(`NCCL_GIN_RESTORE_LOG_MEASURE`가 Resume 없이 문맥을 만들 때 측 표 포인터를 싣고,
  `NCCL_GIN_RESTORE_LOG_MEASURE_LOG=0|1`이 로그를 끄거나 켬). `off`(fail-fast, 모든 비교의 기준), `ua-hold`(hold 길, 로그 0:
  키 다시 읽기만; `cost_unarmed`), `on`, `sampled`, `full`(로그 1, checksum 끔, 표본, 전부; `cost_log`, 로그만의 몫은 같은
  섞기 안의 `ua-hold`와의 차). 4 KiB, 256 KiB 지연과 대역(256 KiB × 8). fail-fast 분기는 `ffb-hk` 대 `ffb-rs`(매크로 없음,
  갈리지 않음을 판정)와 `ffb-rs-macro`(매크로, 보고만). 9.15.6의 6 대 6 섞기. 7절의 4 KiB get 팔은 다루지 못한다(gin_ts2에
  get 지연 모드가 없음).

## pilot이 고정하는 문턱과 n

- 반복 수(n): 7절의 초안(복원 셀 5–10, 명시적 오류 셀마다 3, 회귀 5, 비용 팔마다 노드마다 6). 한 hold가 840 s 안에
  드는지 보고(`fits`), 넘으면 hold를 나눈다.
- 복원 시간 문턱 T: 초안 10000 ms. pilot의 복원 단계별 시각(죽음 판정 → 활성화 → 초기화 재생 → 상태 적용 → 재연결 →
  게이트 재개)을 보고 고정한다.
- 입력 멈춤 문턱: 초안 5 ms. `rs4_none`의 체크포인트마다 멈춤 시간을 보고 고정한다.
- fallback 창: 초안은 hold 시작 → fallback 500–1500 ms, fallback → 풀림 2000–2500 ms, 등록 없음은 죽음 판정 → 풀림
  2000–2500 ms. 코드의 규칙(`EXPERIMENT.md` 9.2절 끝의 시한 메모: 첫 활성화 시도 뒤 약 1000–1500 ms에 fallback)과 pilot의 실제
  시각을 보고 고정한다.
- kill 시점: 예비 프로세스가 있는 kill 셀은 rank 0이 출발 문에서 예비 프로세스의 준비를 기다린 뒤 시작한다. 준비 뒤 100단계
  이상 + 500 µs(정상 중), 체크포인트 hook 안 300 µs(멈춤 중). 단계 600개,
  단계 사이 쉼 5000 µs. pilot에서 예비 프로세스의 준비 시간과 kill이 traffic 안에 떨어지는지 보고 고정한다.
- QP 감시: 6절은 10 ms다. 문맥 4개 × 상대 3이면 rank마다 초당 약 1200번의 QUERY_QP라 rain(rank 둘)에서 한 시행에
  초안 상한 20 000을 넘을 수 있다 `[추론]`. pilot hold에서는 넘으면 `qp_over.txt`에 적기만 하고, pilot이 100 ms로
  바꿀지, 상한을 바꿀지, 시행을 짧게 할지를 정한다(`QPWATCH` 변수).
- 판정식의 k/n(≥ 9/10 등): 초안 그대로 두고 pilot의 유효 시행 수를 보고 사전 등록에서 고정한다.

## 사용자 보류 중인 overhead 예산 (사용자 확인 대기)

3절 표 아래의 "제안한 비용 한도"다. pilot이 수를 재어 적고, 사용자가 확인하면 비용 예측의 문턱으로 고정한다.
지금은 보류(pending)이고 `score.py`는 `cost_log`, `cost_unarmed`를 "문턱 대기(pilot 뒤)"로 적는다.

- fail-fast: 잴 만한 차이 없음(`cost_ff`, 갈리지 않음을 예측).
- 복원 모드의 put 지연과 대역: 10% 안.
- 4 rank에서 rank마다 더하는 메모리: 64 MiB 이하(rain BAR1의 4분의 1). 설명만 적는 로그에서 항목 4096이면 약 3.0 MiB다
  (9.5절) `[추론]`.

## 메인 세션 명령 (차례대로)

변수: `T`는 이 폴더(`impl/test`)의 절대 경로, `R`은 결과 폴더, `SUNNY_SSH`는 관리망 설정 파일에서(저장소에 적지 않음),
`I`는 세션 스크래치의 `agent_rs_int`. 통합 빌드(2026-10-12): 라이브러리는 `../build_rs.sh`의 `rs_i3`, `rsp_i3`, 시험 드라이버는
`build_rs_test.sh rs|nomacro|hk|cost|mr`(`RSTOUT=i3`, 통합 트리의 헤더)이고 md5는 아래 줄에 그대로 있다(`EXPERIMENT.md` 12절의 통합 행).

```
# 1. 배포 (새 디렉터리만, ~/rs-bundle 아래; 대상이 있으면 거절)
RS_LIB_SRC=$I/out/rs_i3/libnccl.so.2.32.3 RSP_LIB_SRC=$I/out/rsp_i3/libnccl.so.2.32.3 \
  WANT_RS=ac8d830575e9a194587e43faf76cb21a WANT_RSP=7d418e54e08374d7a359f6e357314d58 \
  WANT_GINRS=303e812dfd4352769bcac89c8f9451c8 WANT_GINRS_NOMACRO=0f0826e6546cfdc927df9a9e6b9dc64a \
  WANT_GINRS_HK=4ec9b84640dc584c1a86f8095023ef33 WANT_COST=dd44e14ef4af4e5a1200706965b1c771 \
  WANT_COST_FF=5e4db845a693f65fd18341fa2e30eb7d WANT_MR_FF=41f3ce3a14923c37d943825034d6467a \
  WANT_MR_HOLD=169f59c55381c5aa5f6040afd43ba672 RSTOUT=i3 bash $T/deploy_rs.sh $I/deploy_check.txt
grep -E "MISMATCH|CHANGED|not found" $I/deploy_check.txt     # 아무 줄도 없어야 함
# 2. 자체 시험 (CPU, 클러스터 없음)
python3 $T/selftest_rs.py
# 3. pilot (결과 폴더를 본 실행과 따로; pilot은 채점하지 않음)
bash $T/chain_rs.sh $R/<날짜>_pilot P1 P2 P3 COSTPILOT-rain COSTPILOT-sunny
python3 $T/score.py $R/<날짜>_pilot        # 열을 읽기만(판정 아님)
# 4. pilot 뒤 고칠 목록 -> 7절 n, 3절 문턱, cells_rs.json, predictions_rs.csv 고정 -> 사전 등록(커밋 하나, 태그)
# 5. 본 실행
bash $T/chain_rs.sh $R/<날짜> G1 G2 R1 \
  COST-log-rain-lat4k COST-log-rain-lat256k COST-log-rain-bw256k COST-log-sunny-lat4k COST-log-sunny-lat256k \
  COST-log-sunny-bw256k COST-ffbranch-rain COST-ffbranch-sunny
# 6. 채점
python3 $T/score.py $R/<날짜>
```

어느 hold든 STOP 파일을 남기면 다음 hold는 돌지 않는다. `skipped.txt`에 줄이 생기면 그 셀만 다시 돈다.

## 설계 바꿈(2026-10-12)이 남긴 물음과 결정

- 비용 셀의 로그 팔과 무장 전 hold 팔: 측 표 포인터는 Resume이 성공해야 실리므로 Resume을 부르지 않는 비용 driver는 hold 길에
  닿지 않았다. 결정(메인 세션): 라이브러리의 재기만 하는 모드가 Resume 없이 포인터를 싣고 새 변수
  `NCCL_GIN_RESTORE_LOG_MEASURE_LOG`(dev 브랜치가 더함, 기본 1)가 로그를 고른다. 위 비용 셀의 팔이 그것이다. pilot은
  `ua-hold`와 `on`이 실제로 hold 길을 지나는지(측 표가 실렸다는 라이브러리 줄)를 본다.
- 회귀 셀의 hold 변형: gin_mr은 Resume을 부르지 않아 매크로로 빌드해도 hold 보내기 길을 지나지 않는다. 결정(메인 세션): 이 행의
  목적을 "hold 정책과 매크로 빌드에서도 결과가 hk와 같음"(정책 설정의 회귀)으로 바꾸고, 장치의 hold 길은 복원 셀이 지나게 한다.

## 통합 뒤 다시 확인할 것 (지금 실행하지 못한 것)

- kill 셀의 복원 반응 전체(붙잡기, 되살림, 억제, 복원 시간, fallback).
- 예비 프로세스의 활성화와 초기화 재생 시간(작업 묶음 8).
- 라이브러리가 내보낼 줄의 꼴(notes_test.md의 "가정한 줄"): 다르면 `rows_rs.py`의 정규식을 맞춘다.
- 예비 프로세스에 넘기는 환경 변수 이름(notes_test.md): 다르면 `run_rs.sh`를 맞춘다.
