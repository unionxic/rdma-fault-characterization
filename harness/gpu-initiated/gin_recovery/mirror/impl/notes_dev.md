# dev 갈래 기록 (12절에 옮길 행)

[PARALLEL.md](PARALLEL.md)의 규칙대로 이 갈래는 `EXPERIMENT.md`를 고치지 않고, 12절에 들어갈 행을 여기에 쌓는다. 통합 때 메인 세션이
12절로 옮기고 이 파일을 지운다. 표시: `[측정]` 빌드나 시험 출력에서 확인, `[소스]` 코드에서 읽음, `[추론]` 해석, `[미확인]` 확인 안 함.
"빌드됨"은 컴파일만, "시험함"은 CPU 단위 시험을 돌린 것이다. 클러스터 실행, GPU나 RDMA 프로그램 실행은 없다.

빌드 트리는 세션 스크래치 `agent_mi_dev/`(`build_mi.sh setup`이 i5를 복사하고 rs 계층을 커밋 하나로 만든 것, 그 커밋 위 작업 트리가 이 갈래의
diff)다. 줄 번호는 따로 적지 않으면 `rs_layer.diff`(md5 `f005bb67`)의 줄이다. 바탕 libnccl은 i5(연구 `4811f28f`, 운영 `be91b270`)다.

## 행

| 시각 | 무엇을 했나 | 결과와 근거(경로, 커밋, 실행 ID) |
|---|---|---|
| 2026-10-13 15:33 | `build_mi.sh setup`: i5를 `agent_mi_dev/`로 복사, rs 계층을 커밋 "gin-restore i5 (rs_layer.diff f005bb67)"로 | `[측정]` 복사한 libnccl이 i5의 md5와 같음(setup이 검사) |
| 2026-10-13 15:48 | 인터페이스 커밋: `build_mi.sh paste`(hold shared text는 v1), `api` 통과 | 커밋 `9434a824`, `mi_layer_dev.diff` md5 `a1beff20`(712줄, 인터페이스만) |
| 2026-10-13 15:48–16:10 | 장치 mirror 구현: `rsMiPut`(hold 보내기 길의 둘째 put), `rsLogPut`의 lane 낱말과 MIRROR 표시, `rsMiWait`와 flush, wait 끝의 기다림; 측 표 v4(`gdakiMiSideLayoutOf`, `gdakiRsStart`의 머리와 칸); QP 묶음 함수와 루프백 쌍 잠금; 가져오기 영역 첫 판; 한 줄 고침 셋; 자리표시 셋 | `[소스]` 작업 트리 diff(아래 `mi_layer_dev.diff`). 첫 빌드 `mi_d1` libnccl `f9422c3c`(16:10), `mip_d1` `b06620e0`(16:24); 이 계층의 세 파일에 경고 0(`build_mi_d1.log`, `build_mip_d1.log`; 남은 경고 1은 i5에도 있는 `symmetric_sched.cc:327`) → **빌드됨** |
| 2026-10-13 16:16–16:30 | 독립 리뷰 1(같은 모델, 읽기만; `agent_mi_dev/review1/`): 장치 길과 가져오기 첫 판 | 찾은 것을 접음(아래 "리뷰 1에서 고친 것"). 리뷰의 본문은 앞 세션이 한도에 걸려 남지 않았고 고친 diff만 남았다(`review2/fixes.diff`, 431줄) `[소스]` |
| 2026-10-13 16:47–16:51 | 리뷰 1 반영: 자기 루프의 오류 CQE 확인, rkey 0은 깨짐, `rsMiWait`의 끝 조건 셋(miUse 0, swErr, 창 밖에서 멈춘 소비 색인), 가져오기의 Prepare와 Step을 통째로 다시 씀(잠금 밖 INJECTED, 실패한 Step은 helper가 끝냄, rkey 목록의 자리 검사, FETCH 결과 검사, 측 표 머리에서 칸 자리) | `[소스]` `review2/fixes.diff`. `build_mi.sh unit`: `mi_unit_dev` 568 994 checks, 0 failed(ASan, UBSan) → **시험함**(16:51) |
| 2026-10-13 17:02–17:14 | 둘째 빌드 | `mi_d2` libnccl `df76e815`(17:08), `mip_d2` `96be0696`(17:14); 세 파일에 경고 0(`build_mi_d2.log`, `build_mip_d2.log`) → **빌드됨** |
| 2026-10-13 17:16–17:34 | `build_mi.sh ident`(`ff_cmp_mi.sh`, `exact_cmp_mi.sh`: gin-restore의 `ff_cmp_dev.sh`, `exact_cmp_dev.sh`를 새 이름으로 옮겨 hk와 i5 둘 다와 견줌) | `[측정]` `ident_d2.log`(rc 0): 매크로 없는 프로그램 넷 × sm_75, sm_86 = 8/8이 hk와도 i5와도 SASS 전체와 -res-usage 같음; 라이브러리 장치 객체 207개가 i5와 같음(205 그대로, 2는 컴파일 해시만 다름, 다른 것 0; 연구와 운영 둘 다); hk와는 183 + 2 같고 22 다름(gin-restore 12절에 적힌 hk 트리의 낡은 symmetric 객체 22개, i5도 같음); libnccl -res-usage는 i5, hk와 같음. 매크로 변형(m)은 경고 0으로 컴파일되고 자원이 i5의 m과 다름(ff 22 중 11, gin_ts2 20 중 4, gin_mr 4 중 1, ring 8 중 8): mirror 기다림의 비용, test 갈래의 비용 팔이 잼 |
| 2026-10-14 15:50–16:00 | 이어서(앞 세션이 한도에 걸림): 작업 트리가 d2 빌드의 원본임을 확인(파일 mtime 16:50 < 빌드 17:08), `api` 다시 통과, `unit` 다시 568 994 / 0 | `[측정]` 그 세션의 출력 |
| 2026-10-14 16:04–16:19 | 독립 리뷰 3(같은 모델, 읽기만; 입력 `review2/dev_only.diff` = d2의 원본): MUST-FIX 0, SHOULD-FIX 4, NOTE 10 | 본문 `agent_mi_dev/review3/review.txt`(31줄; 2026-10-15에 세션 기록에서 옮겨 둠). 접은 것은 아래 "리뷰 3에서 고친 것", 넘긴 것은 "통합 때 할 일" `[소스]` |
| 2026-10-14 16:19–16:29 | 리뷰 3 반영(아래). 호스트 파일 문법 검사(`hostsyn.sh`) 통과, 매크로 장치 프로그램 `ff_ops.cu`를 sm_75, sm_86에서 매크로 있음과 없음으로 컴파일해 경고 0(`devchk/run.sh`), `unit` 568 999 checks, 0 failed(ASan, UBSan; 검사 5개 더함) | `[측정]` 그 세션의 출력 → **시험함** |
| 2026-10-14 16:29–16:45 | 셋째 빌드, `diff` | `mi_d3` libnccl `728b8f08`(16:37), `mip_d3` `c753116f`(16:45); 경고는 각 1(i5에도 있는 `symmetric_sched.cc:327`), 이 계층의 세 파일에 0(`build_mi_d3.log`, `build_mip_d3.log`) → **빌드됨**. `mi_layer_dev.diff` md5 `b9ecd9fa`(2 261줄). 그 세션은 기록을 쓰기 전에 한도에 걸림 |
| 2026-10-15 07:02–07:06 | 이어서: 작업 트리가 d3의 원본임을 확인(파일 mtime 16:26–16:27 < 빌드 시작; 트리의 diff md5 = 저장한 `mi_layer_dev.diff` `b9ecd9fa`), `api` 통과(붙인 블록 다섯이 헤더와 바이트까지 같음, 여섯 헤더가 함께 컴파일됨), `unit` 568 999 checks, 0 failed(ASan, UBSan) | `[측정]` 이 세션의 출력 → **시험함** |
| 2026-10-15 07:05–07:24 | `build_mi.sh ident`(`MIOUT=mi_d3`, 운영은 `mip_d3`) | `[측정]` `agent_mi_dev/ident_d3.log`(rc 0), d2와 같은 결과: 매크로 없는 프로그램 넷 × sm_75, sm_86 = 8/8이 hk와도 i5와도 SASS 전체와 -res-usage 같음; 라이브러리 장치 객체가 i5와 205 그대로, 2(`device_glue.o`, `onerank.cu.o`)는 컴파일 해시만 다름, 다른 것 0(연구와 운영 둘 다); hk와는 183 + 2 같고 22 다름(모두 `genobj/symmetric`, i5도 같음); libnccl -res-usage(해시 가린 이름)는 i5, hk와 같음(1 472 같음, 다름 0). 매크로 변형(m)은 경고 0, 자원이 i5의 m과 다름(ff 22 중 11, gin_ts2 20 중 4, gin_mr 4 중 1, ring 8 중 8) |
| 2026-10-15 07:24 | `build_mi.sh info` | `[측정]` `agent_mi_dev/out/build_info.txt`: 바탕 `8ffb609`(i5 커밋의 diff md5 `f005bb67` = `rs_layer.diff`), 작업 트리 diff `b9ecd9fa` = `mi_layer_dev.diff`, `mi_unit_dev.cc` `10d3ffa8`, 공유 헤더 여섯과 `PARALLEL.md`, `build_mi.sh`의 md5 |

## 리뷰 1에서 고친 것 (`review2/fixes.diff`, `[소스]`)

- `rsMiPut`: 자기 루프(이 rank가 짝)에는 게이트가 없어 DOCA의 자리 기다림이 오류 CQE 뒤 영영 돌 수 있다 → 내기 전에 가장 오래된 미완료 완료를
  한 번 폴링해 오류면 깨짐으로 하고 내지 않음. 게이트 진입 뒤 읽은 pool rkey가 0("모름")이면 깨짐.
- `rsMiWait`: 끝내는 조건을 더함(mirror QP가 쓰지 않음으로 바뀜 miUse 0, 자리 기다림이 본 오류 swErr, 표가 CQ 창 밖인데 소비 색인이 두 확인
  사이에 움직이지 않음), 시한은 `timeoutCycles`가 0이 아닐 때만(`tsExpired`와 같음).
- 가져오기: Prepare를 잠금(`gdakiRsWinMu` → `appMu`) 안의 `gdakiMiImportPrepareLocked`와 잠금 밖의 INJECTED 알림으로 나눔; 실패한 Step은
  application 스레드가 소켓을 닫지 않고 `endAsked`만 세우고 helper의 `gdakiMiImportHelperStep`이 `gdakiHoldSelfEnd`(FALLBACK 알림, FIN)로 끝냄;
  rkey 목록의 window, 신호와 카운터 표에 이 rank의 자리가 있는지 검사(화신 > 0은 거절, 0은 WARN); FETCH 결과의 체크포인트와 extent 수 검사; 칸의
  자리는 가정하지 않고 장치의 측 표 머리(`miCellsOff`, `miNCells`)에서 읽음; 생존 rank들의 마지막 단계가 1보다 멀면 WARN.

## 리뷰 3에서 고친 것 (`[소스]`, `mi_layer_dev.diff` `b9ecd9fa`)

- SHOULD-FIX 1, 자기 루프의 자리 기다림: DOCA의 stock 자리 기다림은 예약 색인 − SQ 크기의 CQE가 창 `[ci, ci + cqe_num)` 밖이면 소비 색인이 움직일
  때까지 돌고, 오류 CQE가 소비 색인을 멈추면 영영 돈다(`doca_gpu_dev_verbs_wait_until_slot_available`, `doca_priv_gpu_dev_verbs_poll_cq_device_at`).
  가장 오래된 완료의 오류 폴링은 그대로 두고, 이 put의 예약이 그 창을 벗어나면(`rsvd + chunks > ci + sq_wqe_num + cqe_num`) 내지 않고 깨짐으로 센다.
  읽기와 원자 더하기 사이의 경쟁은 경쟁한 스레드들의 조각 수만큼만 더 나아가므로 받아들였다. 리뷰가 글자로 제안한 조건(`rsvd + chunks <= ci +
  sq_wqe_num`)은 쓰지 않았다: 게이트 없는 QP의 소비 색인은 뒤 예약의 자리 기다림이 성공할 때만 오르고(`atomic_max`; 비대기 폴링
  `poll_one_cq_at`은 올리지 않음) 정상 상태에서 늘 예약보다 고리 하나 뒤에 있어, 그 조건은 첫 고리가 찬 뒤 모든 mirror를 깨뜨린다
  `[소스: doca_gpunetio_dev_verbs_cq.cuh의 poll_cq_device_at와 poll_one_cq_at; 실행하지 않음]`.
- SHOULD-FIX 2, `rsMiWait`의 "창 밖에서 멈춘 소비 색인" 끝 조건: 1 024걸음 두 번 사이의 정지(수백 µs)는 바쁜 QP에서도 일어나 거짓 깨짐을 낼 수 있다 →
  시간으로 묶음: 표가 창 밖이고 소비 색인이 `NCCL_GIN_MI_STUCK_NS`(20 ms, `%globaltimer`) 동안 그대로일 때만 깨짐. 게이트 있는 QP의 자리 기다림
  (`doca_priv_gpu_dev_verbs_nccl_ts_slot_wait`)은 성공한 CQE마다 소비 색인을 올리고 오류면 swErr를 적으므로 그 전에 swErr, miUse 0, 라운드가 끝내고,
  이 조건은 자기 루프(아무도 보고하지 않는 오류 CQE)의 뒷받침이다 `[소스]`.
- SHOULD-FIX 3, 되살린 rank의 mirror QP `miUse`: 가져오기는 생존 rank의 mirror 셈이 무효(`mirValid 0`)일 때만 `miUse 0`을 쓰고 유효할 때 1을 쓰지 않는다
  (잇지 않은 QP에 1을 쓸 수 없고, 잇는 쪽은 spare와 host 갈래). 새 함수 `gdakiMiImportMirrorUnusable(r, peer)`로 그 결정을 읽을 수 있게 했다(리뷰의 둘째
  안). 차례는 통합 조건(아래 2).
- SHOULD-FIX 4, test 갈래의 열쇠 줄 "import step", "import done"을 `GIN_TS_NOTE`(운영 빌드에서 INFO)에서 WARN으로: 다른 갈래의 열쇠 줄과 같이 두 빌드
  모두 WARN이다.
- NOTE 5: WARN 네 줄(rkey 목록 셋, 생존 rank 단계 간격)에 ` mono_ms=%.3f`를 붙여 헤더의 줄 규칙에 맞춤.
- NOTE 6: `gdakiMiReadMsgsMirror(r, 자기 rank)`는 자기 루프 QP의 항목(`miCtx × nranks + 자기 rank`)을 읽는다(`gdakiMiQpOfPeer`는 헤더대로 자기 rank에
  −1). 장치는 자기가 맡은 rank로 가는 mirror를 그 항목의 msgs에 세므로, 짝이 HOLDING의 자기 값을 "지역에서" 읽을 때 이 함수를 쓴다(spare의 미정 항목
  "자기 rank의 gdakiMiReadMsgsMirror 뜻"을 이렇게 정함).
- NOTE 14: 단위 시험에 window 둘에 걸친 겹침 검사(한 window의 데이터 끝이 다음 window로 넘어가지 않음; 허용 하나, 거절 하나)와 rkey 목록 수의 경계
  (`GDAKI_RS_RKEYS_MAX`는 통과, 하나 위는 거절)를 더함. MIRROR 항목의 SPLIT, NOBASE, checksum 비트 거절은 이미 있었다(`testEntry`).
- 고치지 않은 것: NOTE 11(Step이 잠금을 쥐는 동안 helper의 지연)과 13(신호와 카운터 표의 rkey는 장치 사본만)은 아래 "인터페이스 밖에서 정함"에 적고 그대로
  둠; NOTE 7, 8, 9, 10, 12는 아래 "통합 때 할 일"로 넘김.

## 인터페이스 밖에서 정함

- 측 표 v4의 배치: 칸 배열은 QP 항목 바로 뒤(`128 + 128 × nqp`), 고리는 그 뒤 256바이트 정렬, 전체는 4 KiB 올림(`gdakiMiSideLayoutOf`); 칸 수 0이면
  v1과 바이트까지 같음. mirror 문맥의 QP는 로그 집합(`nLogged`)에서 뺌. 머리의 mirror 칸은 `gdakiRsStart` 때 `gdakiMiOn(r) && r->mi.ctx >= 0`일
  때만 씀: host 갈래는 그 전에 `mi.on`, `mi.ctx`를 정해야 한다.
- `rsMiPut`: L보다 큰 put은 커서를 더하지 않고 깨짐(올림이 감기지 않음); 커서 더하기는 `ncclGinMiRound64(bytes)`; 자리 기다림의 오류 CQE는 mirror
  문맥 번호로 보고(`mctx.contextId = miCtx`, `tsPostLeave`); 돌려주는 값은 `1 << 32 | (off >> 6)`이고 lane 낱말은 로그 항목의 `csum` 자리. 자기 루프:
  가장 오래된 완료의 오류 폴링과 예약의 창 검사(위).
- `rsMiWait`: 1 024걸음마다 끝 조건(라운드, miUse 0, swErr, 창 밖 정지 20 ms), 10 000걸음마다 abort 낱말과 상대의 abort 낱말; 오류 CQE는 에폭마다
  한 번 `q4Report`(종류 ERR_CQE, 길 FLUSH_TIMEOUT 또는 FLUSH_BLOCKING, sticky 아님); 성공이면 호출자의 memory_order로 시스템 범위 울타리. flush는
  짝들을 협력 스레드에 나눠 기다림(`rsMiAfterFlush`), wait는 요청의 상대의 짝 하나(`rsMiAfterWait`). `NCCL_GIN_MI_STUCK_NS` 20 ms는 이 갈래의 상수다.
- 가져오기: FETCH 결과의 `ckpt`가 다르면 거절; 화신 0인 생존 rank의 rkey 차이와 자리 없음은 WARN만(기록 값 유지), 화신 > 0은 거절(`gdakiMiRkeyVerdict`);
  pool rkey는 그 생존 rank가 맡은 rank의 칸에 `valid 0`과 함께 씀(host의 segment 바꾸기가 유효로 만듦); 생존 rank의 `mirValid`가 0이면 그 mirror QP에
  `miUse 0`을 쓰고 `mirUnusable`에 적음(`gdakiMiImportMirrorUnusable`); 신호와 카운터 표의 rkey는 장치 사본만 씀(gin-restore의 `gdakiRsSwapRkeys`와
  같음; window는 host 사본도); "import plan" 줄 하나를 더 씀(test 갈래의 열쇠가 아님); 잠금 차례는 `gdakiRsWinMu` → `appMu` → (`gdakiRsAtomicOp` 안)
  `atMu`, 그리고 `opMu` → `execMu`(`gdakiMiExecReadMirror`, `gdakiRsExecRead`와 같음). Step은 그 잠금을 CUDA 복사와 NIC 원자 연산 동안 쥐므로 helper의
  `gdakiRsWinGoneCount`(10 ms 걸음), `gdakiHoldCommCheck`, `gdakiCkptRegions`가 그만큼 기다린다(순환 없음, 지연만) `[소스]`.
- `gdakiMiExecReadMirror`: QUERY 실패는 `ncclSystemError`, 셈 무효는 `*valid = false`(거절 없음). `gdakiRsQpsOfPeerAll`은 mirror QP를 마지막에 두고
  `NCCL_GIN_RECOVERY_MAX_QPS`에서 자름. `gdakiMiReadMsgsMirror`의 자기 rank(위 NOTE 6).
- 자리표시(통합이 바꿈): `gdakiMiOn`은 false, `gdakiMiInjectedReady`는 비어 있음, `gdakiMiSpareFetched`는 extent 없는 결과. 그래서 이 갈래의 빌드는
  mirror 끈 gin-restore의 길과 같다 `[추론; 실행하지 않음]`.

## 줄 형식 (이 갈래가 쓰는 줄; test 갈래의 열쇠는 "import step"과 "import done", 둘 다 WARN, 두 빌드 모두)

- `GIN/MI: rank %d: import step %lu: entries=%lu pool_bytes=%lu value_bytes=%lu signals=%lu signal_targets=%zu import_us=%.0f mono_ms=%.3f`(입력이 있는
  단계마다 한 줄; 입력 없는 단계는 줄이 없음)
- `GIN/MI: rank %d: import done: steps=%d pool_bytes=%lu left=%zu last_step=%lu failed=%d mono_ms=%.3f`(한 번; Prepare에서 끝났을 때, 마지막 Step 뒤,
  실패 때, 또는 `gdakiRsLogFree`에서)
- `GIN_TS_NOTE`(연구 빌드 WARN, 운영 빌드 INFO): `GIN/MI: rank %d: import plan: checkpoint=%lu survivors=%zu entries=%lu mirror_entries=%lu mirror_bytes=%lu signal_adds=%lu signal_sum=%lu steps=%zu first_step=%lu last_step=%lu queued=%zu rkeys_written=%d rkeys_warned=%d pool_cells=%d mirror_unusable=%zu incarnation=%u prepare_ms=%.1f mono_ms=%.3f`;
  `GIN/MI: rank %d: side table v4: cells=%d cells_off=%zu mirror_ctx=%d qps=%d mono_ms=%.3f`(mirror 켬일 때 `gdakiRsStart`)
- WARN: `GIN/MI: rank %d: ncclGinRestoreStep(%lu): the import of the queued inputs failed (%s); the helper ends this process's part without BYE mono_ms=%.3f`;
  `GIN/MI: rank %d: rank %d's rkey list misses window %u (incarnation 0: the recorded key stays) mono_ms=%.3f`;
  `GIN/MI: rank %d: rank %d's rkey list %s (kind %u, id %u; incarnation 0: ignored) mono_ms=%.3f`;
  `GIN/MI: rank %d: rank %d (incarnation 0) lists rkey %#x for kind %u id %u, the replayed table has %#x: the recorded value stays mono_ms=%.3f`;
  `GIN/MI: rank %d: the survivors' last steps before the hold span %lu .. %lu (more than one step apart) mono_ms=%.3f`
- 거절 사유(`why`, Resume의 FALLBACK 줄에 실림): `the step-aligned import was refused, nothing applied: ...`(아무것도 쓰기 전), `the step-aligned import
  failed part way (...); the restore falls back`(쓰기 중 실패).

## 통합 때 할 일 (메인 세션에 넘김)

1. 자리표시 셋을 지우고 host의 `gdakiMiOn`, `gdakiMiInjectedReady`, spare의 `gdakiMiSpareFetched`로 바꾼다. `gdakiMiSpareFetched(struct gdakiRecHost*)`가
   `const struct gdakiMiFetched&`를 돌려주는 꼴은 공유 헤더에 없다(rs_store_api.h는 `gdakiMiSpareFetch`만): spare의 접근자 꼴에 맞춘다(리뷰 3 NOTE 12).
2. helper 걸음에서 `gdakiMiImportHelperStep(r)`을 부른다(`gdakiRsLogPoll`, `gdakiMiPoll`과 함께): 실패한 Step의 no-BYE 끝은 helper가 한다. 되살린 rank의
   mirror QP에 `miUse 1`을 쓰는 쪽(spare의 잇기, host의 다시 무장)은 `gdakiMiImportPrepare` 뒤라면 `gdakiMiImportMirrorUnusable(r, peer)`가 참인 QP에는
   쓰지 않는다(가져오기가 쓴 0이 지워지면 생존 rank가 셈을 못 믿는 QP로 mirror를 낸다). 잇기가 Prepare보다 앞서야 0이 남는다.
3. rkey 목록 규칙: spare 갈래의 `gdakiMiRkeyMerge`는 공유 헤더에 없는 spare 영역의 순수 함수라 이 갈래는 같은 규칙을 `gdakiMiRkeyVerdict`와 Prepare의
   검사로 직접 구현했다. 차이 하나: spare의 merge는 자리 없음(목록의 window가 여기 없음, 여기 window가 목록에 없음)을 화신과 상관없이 거절(-1)하고, 이 갈래는
   화신 0이면 WARN만(EXPERIMENT.md 9.4 "화신 0의 새 비교는 WARN 한 줄"), 화신 > 0이면 거절한다. 통합 전에 메인 세션이 하나로 정한다(merge로 바꾸면
   Prepare (1)의 고리를 바꿈; 리뷰 3 NOTE 7).
4. 되살린 rank 자신이 맡은 rank(자기 루프 lane)의 칸: 가져오기는 생존 rank들의 목록만 쓰므로 그 칸의 pool rkey(자기 pool)는 쓰지 않고, host의 segment 바꾸기는
   `rkeyBe`를 쓰지 않는다(rs_mirror_api.h 칸 설명). host나 spare가 자기 pool의 rkey를 그 칸에 써야 한다; 아니면 첫 바꾸기 뒤 그 lane의 mirror가 rkey 0으로 모두
   깨진다(리뷰 3 NOTE 8) `[소스]`.
5. 헤더 글자: rs_log_api.h 388–390 "gdakiMiInjectedReady(r, t + 1)"은 코드와 test 갈래의 채점(`rows_mi.py`: INJECTED의 단계 = 마지막 import step)대로 "마지막
   넣은 단계"로 고친다(코드가 아니라 헤더 글자; 리뷰 3 NOTE 9). test 갈래 `rows_mi.py` 239–240은 import step의 단계가 이어진다고 보지만 이 갈래는 입력이 있는
   단계에만 줄을 쓴다: 채점을 느슨하게 하거나 빈 단계도 줄을 쓰기로 정한다(리뷰 3 NOTE 10).
6. host의 조건(`mi_integration.md`): 측 표 머리의 `miOn`, `miCtx`, `miCellsOff`, 칸 배열(됨), mirror QP를 `rsLogged`에서 뺌(됨), `gdakiRsQpsOfPeer` 좁힘(됨),
   가져오기의 `gdakiMiInjectedReady`(됨). spare의 조건: `gdakiRsAtomicOp`의 쌍 잠금(됨).
7. 이 트리의 hold shared text는 v1이다(host만 v2를 붙임); 통합 트리에서 `api`를 다시 본다.

## 열린 항목

- 자기 루프 lane의 CQ 폴링과 창 검사(`rsMiPut`의 게이트 없는 길)는 DOCA의 `doca_gpu_dev_verbs_poll_one_cq_at`와 자리 기다림의 의미에 기댄다 `[소스; 실행하지
  않음]`: pilot의 mirror 켠 셀이 처음 돌린다. 읽기와 예약 사이의 경쟁은 받아들인 틈이다 `[추론]`.
- `rsMiWait`의 창 밖 정지 20 ms는 바쁜 짝에서 거짓 깨짐을 낼 수 있다(그 받는 rank의 DISARM, 다음 확정 체크포인트에서 다시 무장) `[추론]`.
