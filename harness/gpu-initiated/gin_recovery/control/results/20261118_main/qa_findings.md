# gin-control 본 실행(2026-11-18) QA 조사: 맞지 않은 판정 셋과 STOP_left 둘

읽기만 했다. 클러스터, git, 작업 트리 수정 없음. 코드는 바꾸지 않았다.

- 자료: `agent_gc_main1/main/`(이하 `main/`): `SCORE.md`, `trials_scored.csv`(402행), `raw/`, `hold_*.out`, `stops/`, `chain.out`, `skipped.txt`
- 작업 트리: `/home/unionxic/rdma-error-wt/gin-control/harness/gpu-initiated/gin_recovery/control/`(이하 `ctl/`)
- 라이브러리 소스: `agent_gc_p2a2/nccl-src/src/transport/net_ib/gdaki/gin_host_gdaki.cc`(이하 `gdaki.cc`, 39 052줄)
- 비교: gin-mirror 본 실행 `../mirror/results/20261015_main/trials_scored.csv`, pilot `ctl/results/2026102*/a*/trials.csv`와 raw
- 표시: `[측정]` 원자료에서 이 조사가 다시 셈, `[소스]` 코드를 읽음, `[추론]` 해석, `[미확인]` 확인 안 함
- 시각은 따로 적지 않으면 로그 첫 열(받은 쪽 단조 시계, rain)의 차다.

## 요약

| 항목 | 판정 | 분류 |
|---|---|---|
| 1. 복원 시간과 관문(`restore_time_rdma`) 틀림 | 아홉 키 가운데 `mi4_kill3_ckpt_ow@gc` 하나만 1/5, kill → 마지막 게시가 하한 154.5 ms **아래**(빠름) | (c) 예측 띠가 틀림 |
| 2. 살아서 도는 프로세스의 펜스(`freeze_fence_restore`) 재검토 | n1, n3, n5가 게시 뒤 장치 한도(21 000 ms)에 fallback | (a) 라이브러리 결함 |
| 3. helper만 멈춘 rank의 펜스(`helper_stall_fence`) 재검토 | n5, 항목 2와 같은 길 | (a) 라이브러리 결함 |
| 4. STOP_left 둘 | 실행기의 snapshot subshell을 `kill`할 때 그 자식 python 대기 프로세스가 남음 | (b) 실행기 결함, 시행 자료 영향 없음 |

## 1. 복원 시간과 관문 (`restore_time_rdma`): 틀림

### 어느 키, 어느 항

- 판정식은 키마다 `120 <= judge_to_publish_ms <= 197 and 154.5 <= kill_to_publish_ms <= 240.5 and restore_time_ms <= 2000 and fence_order_ok == 1 and la_later_n <= 1`(학습 셀은 195–286, 229.6–318.0, ≤ 1 000) `[소스: ctl/impl/test/predictions_gc.csv:26]`.
- **틀린 키는 `mi4_kill3_ckpt_ow@gc` 하나다**(1/5 < 4). 나머지 여덟 키(`mi4_kill3_ow` 10/10, `mi4_kill1_ow`, `mi4_seg_4k`, `mi4_seg_32k`, `mi4_seg_128k`, `mi4_pull`, `rs4_kill3_mion` 5/5씩, `mi4_train_kill3` 10/10)는 맞음 `[측정: main/SCORE.md:438–464, trials_scored.csv에서 다시 셈]`. 요청문이 아홉 셀을 모두 틀린 것처럼 적었으나 예측 전체가 틀림인 것은 키 하나 때문이다.
- 그 키에서 어긋난 항은 **kill → 게시의 하한 154.5 ms 하나**다. n1–n4의 `kill_to_publish_ms` 145.6, 150.4, 152.0, 153.7 ms. 같은 시행의 판정 → 게시 124.9–133.1 ms(띠 120–197 안), 복원 시간 ≤ 2 000, `fence_order_ok` 1, `la_later_n` 0(활성화 관문의 'later' 답 0) `[측정: trials_scored.csv]`. n5는 167.2 ms로 통과.

### 실제 분포 (n, 무엇의 범위인지)

본 실행, 키마다 모든 시행의 범위(ms) `[측정: trials_scored.csv]`:

| 키 (n) | 판정 → 게시 | kill → 게시 | 활성화(`activate_ms`) | SIGKILL → FENCED(launcher) | 활성화 뒤(`post_activate_ms`) |
|---|---|---|---|---|---|
| `mi4_kill3_ow` (10) | 144.1–150.4 | 165.2–171.1 | 81.9–87.7 | 73.6–79.5 | 61.2–63.3 |
| `mi4_kill1_ow` (5) | 147.8–150.2 | 168.5–171.0 | 85.4–86.9 | 76.8–78.9 | 61.4–62.8 |
| `mi4_kill3_ckpt_ow` (5) | 124.9–146.2 | **145.6–167.2** | 80.2–89.5 | 71.6–80.0 | **40.8–62.8** (넷이 40.8–42.4) |
| `mi4_seg_4k` (5) | 147.5–152.4 | 168.4–173.7 | 85.3–89.6 | 77.4–81.3 | 61.1–62.4 |
| `mi4_seg_32k` (5) | 135.9–153.7 | 156.4–175.1 | 87.4–91.4 | 77.4–82.7 | 44.7–62.6 (둘이 44.7, 44.9) |
| `mi4_seg_128k` (5) | 157.8–161.2 | 178.9–182.3 | 94.1–97.5 | 85.9–89.3 | 61.8–63.2 |
| `mi4_pull` (5) | 140.8–146.0 | 162.0–166.5 | 79.1–83.7 | 70.3–74.7 | 60.8–62.0 |
| `rs4_kill3_mion` (5) | 147.3–151.0 | 168.3–173.1 | 83.8–87.8 | 75.8–79.9 | 62.1–63.4 |
| `mi4_train_kill3` (10) | 214.8–237.8 | 235.2–258.3 | 152.6–158.2 | 140.2–145.0 | 58.4–81.0 |

- 판정은 모두 kill 뒤 20.3–22.1 ms(확인 창 W 20 ms; 아홉 키 55 시행)이고 kill → 게시 = 그 값 + 판정 → 게시다 `[측정]`.
- gin-mirror 본 실행(같은 셀, `@mi`): 복원 시간 174.5–220.5 ms(4 KiB; `mi4_pull` n5의 1 079.0 ms 하나는 뺌, 그 시행은 활성화 3.0 ms에 'later' 0), 활성화 105.3–146.6 ms에 'later' 답 5–7번(같은 시행 뺌), 활성화 뒤 67.2–71.4 ms; `mi4_kill3_ckpt_ow` 178.0–199.1, 활성화 뒤 68.5–71.0 `[측정: mirror/results/20261015_main/trials_scored.csv]`.
- pilot(채점 아님, 셀마다 n 1): pilot 2 `mi4_kill3_ckpt_ow` 판정 → 게시 154.7, kill → 게시 175.2, 활성화 109.0, 활성화 뒤 43.2 ms; pilot 2 4 KiB 다른 셀 kill → 게시 185.3–207.7; pilot 7 `gc4_kill3_ow` 187.0(PILOT.md는 첫 판정 → 마지막 `restored` 166.8) `[측정: ctl/results/20261023_pilot2/a*/trials.csv, ctl/results/20261028_pilot7/a1/trials.csv; ctl/results/20261028_pilot7/PILOT.md:35]`.

### 인과 길

1. **활성화가 pilot보다 약 20 ms 짧다.** 이 빌드의 활성화 = 판정 → FENCE 보냄(약 5 ms) → launcher의 SIGKILL → "the group ended"(FENCED) → 활성화 넘김(약 4 ms)이다. 4 KiB 셀의 SIGKILL → FENCED가 본 실행 70.3–89.3 ms인데 pilot들의 같은 줄은 82.5–177.8 ms(모든 pilot launcher 로그, 4 KiB와 학습 섞임)였다 `[측정: raw/*_launcher_sunny.log "FENCED: the group ended … after SIGKILL", ctl/results/*/a*/raw/*launcher*.log]`. 예: `mi4_kill3_ckpt_ow` n1 71.6 ms, pilot 7 `gc4_kill3_ow` 90.8 ms. 이 시간은 죽은 프로세스 묶음이 커널에서 끝나는 시간이고 라이브러리 논리가 아니다 `[추론]`. 본 실행에서 왜 짧았는지는 `[미확인]`.
2. **ckpt 셀은 활성화 뒤 부분이 짧은 모드를 탄다.** 예비 프로세스 로그에서 마지막 STATE 받음 → 첫 "import step" 간격이 `mi4_kill3_ckpt_ow` n1–n4 0.0–0.1 ms, n5 20.4 ms; `mi4_kill3_ow` 10회 15.2–20.4 ms; `mi4_seg_32k` n3, n5 0.0–0.1 ms, 나머지 15.3 ms `[측정: raw/*_spare.log]`. 짧은 모드의 시행이 바로 활성화 뒤 40.8–44.9 ms인 시행이다. 생존 rank 쪽에서는 "state of checkpoint … sent … (… 18.3 ms" 대 "0.5 ms"로 보인다 `[측정: raw/mi4_kill3_ow_gc_n1_r2.log, raw/mi4_kill3_ckpt_ow_gc_n1_r2.log; 줄은 gdaki.cc:28325]`. 짧은 모드가 왜 생기는지(가져오기 첫 단계의 위상)는 `[미확인]`. pilot 2의 ckpt 셀도 43.2 ms였다.
3. 둘이 겹쳐 ckpt 셀의 넷이 kill → 게시 145.6–153.7 ms가 됐다. 하한 154.5는 "gin-mirror의 지금 값 174.5 ms − 20 ms"에서 왔다 `[소스: ctl/EXPERIMENT.md:267]`. gin-mirror에는 'later' 답의 약 20 ms 단위 대기가 있었고 ckpt 셀의 활성화 뒤 부분도 다른 셀과 같았다(68.5–71.0). 이 빌드는 그 대기를 FENCED 대기로 바꿨고 ckpt 셀이 짧은 모드를 타므로, gin-mirror에서 옮긴 하한은 이 셀에 맞지 않았다 `[추론]`. pilot 2의 ckpt 셀(175.2 ms, n 1)은 띠 안이었지만 그때는 FENCED가 약 100 ms였다.
4. 안전성 쪽 이상은 없다: `fence_order_ok` 9키 모두 실패 0, 같은 셀의 gin-mirror 회귀 `ckpt_kill_ow` 5/5 `[측정: SCORE.md:466, 636]`.

### 분류와 글

- **(c) 예측 띠가 틀림(빠른 쪽).** 라이브러리 결함 아님, 실행기나 채점기 산물 아님 `[추론]`.
- 다른 키도 하한에 가깝다: `mi4_seg_32k` 최소 156.4(여유 1.9 ms), `mi4_pull` 162.0 `[측정]`. 사전 등록 띠는 고치지 않는다.
- 결과 글(제안): "복원 시간과 관문(`restore_time_rdma`): 틀림. 아홉 키 가운데 ckpt 죽음 셀(`mi4_kill3_ckpt_ow@gc`)만 1/5였고, 어긋난 넷은 모두 kill → 마지막 게시가 하한 154.5 ms보다 **짧았다**(145.6–153.7 ms, n 4; 그 셀 n 5의 범위 145.6–167.2). 판정 → 게시, 상한, 펜스 순서, 'later' 수는 아홉 키 모두 맞았다. 하한은 gin-mirror 값에서 W를 뺀 것이라 이 빌드의 FENCED 대기(본 실행 4 KiB 70.3–89.3 ms, pilot 82.5 ms 이상)와 ckpt 셀의 짧은 활성화 뒤 부분(40.8–42.4 ms, n 4)을 넣지 못했다."

## 2. 살아서 도는 프로세스의 펜스 (`freeze_fence_restore`): 재검토 3/5

### 측정된 길 (n1; n3, n5도 같은 꼴)

`raw/gc4_freeze12000_fence_gc_n1_{r0,r1,r2,spare}.log`, 시각은 rank 0의 판정 뒤 ms `[측정]`.

| 시각 | 사건 |
|---|---|
| 0.0 / 1.1 / 94.9 | rank 0, rank 2, rank 1이 rank 3을 STALL_HELPER로 판정(rank 1은 rank 3과 같은 sunny, 약 95 ms 늦음) |
| 4.2 | rank 0 hold 시작: 그때 rank 0이 rank 3에 보낸 mirror 메시지 수 `msgs=1363`; rank 2 `1364`; rank 1(늦은 hold) `1365` |
| 97.9 → 207.7 | FENCE → FENCED(launcher SIGKILL → 끝 109.7 ms) |
| 211.7 | 예비 프로세스 활성화(체크포인트 1360) |
| 229–252 | REJOIN, STATE, export: rank 0 `last_step=1363`, rank 1 `1365`, rank 2 `1364`; 예비의 import plan `last_step=1365` |
| 239.6–279.0 | 생존 셋이 복원 라운드 게시, `rank 3 restored as incarnation 1 … on time` |
| 예비 | import step 1361–1364를 하고 앱이 step 1364에서 멈춤: `GINRS step rank=3 step=1364 released=1 got=2048 want=2049`(20.8 s 뒤 풀릴 때 찍힘); "import done"과 "INJECTED sent" 없음 |
| 21 000.5 | rank 0: "passed its deadline after its publish without RESTORED", "given up (no INJECTED from the revived rank before the deadline after the restore round's publish)", FALLBACK을 셋에게; rank 1, 2는 그 FALLBACK을 받아 decline |
| 21 002–23 063 | 생존 셋 rc 4(`xchg=released`), 예비 rc 4 |

- 다섯 시행과 helper 셀 다섯의 비교 `[측정]`:

| 시행 | 판정 시각(멈춤 시작 뒤 ms) | hold 때 보낸 걸음(r0/r1/r2) | 예비가 기다린 걸음과 모자란 신호 | 결과 |
|---|---|---|---|---|
| freeze n1 | 10 005.5–10 101.1 | 1363 / 1365 / 1364 | 1364, got 2048 want 2049 | fallback |
| freeze n2 | 10 005.8–10 008.3 | 1368 / 1368 / 1368 | 없음, INJECTED 1368 | 복원 |
| freeze n3 | 10 007.0–10 101.0 | 1368 / 1370 / 1368 | 1369, 2053/2055 | fallback |
| freeze n4 | 10 099.6–10 101.9 | 1376 / 1376 / 1376 | 없음, INJECTED 1376 | 복원 |
| freeze n5 | 10 005.7–10 101.2 | 1360 / 1362 / 1360 | 1361, 2041/2043 | fallback |
| helper n1–n4 | 판정 퍼짐 1.4–4.7 ms | 차 0–1 | 없음, INJECTED | 복원 |
| helper n5 | 10 005.1–10 102.7 | 1368 / 1370 / 1368 | 1369, 2053/2055 | fallback |

  fallback 네 시행은 모두 (가) 생존 rank의 판정이 약 95 ms 퍼졌고 (나) hold 때 보낸 걸음의 차가 2였다. 복원된 여섯은 차가 0 또는 1이다. 모자란 신호 수는 그 걸음을 export에 담지 못한 생존 rank 수(n1 하나, 나머지 둘)와 같다.
- 늦은 생존 rank의 그 걸음 메시지는 hold 내내 장치에 묶여 있었다: rank 0의 `GINRS step rank=0 step=1364 released=0 tx_err=3` 줄이 fallback 직후(21 005 ms)에야 찍혔다(n3, n5, helper n5의 rank 0, 2도 같은 꼴, 걸음 min + 1) `[측정]`. 복원된 시행에는 이 `tx_err` 줄이 없다.

### 소스

- mirror 켠 복원 라운드는 게시 뒤에도 사용자 gate를 INJECTED까지 홀수로 둔다: `gdakiHoldAfterPublish`의 `miOdd`(`gdaki.cc:15253–15263`), `gdakiMiKeepGatesOdd`(`gdaki.cc:37382–37384`). 그동안 생존 rank가 되살린 rank에 보내는 put은 gate에서 기다린다 `[소스]`.
- INJECTED는 예비 프로세스가 import plan의 `last_step`까지 가져온 뒤 보낸다("import done" 뒤 "INJECTED sent", `gdaki.cc:37379`; 줄 꼴 `gdaki.cc:34349`). 이 `last_step`은 생존 rank export의 최댓값이다 `[측정: import plan 줄]`.
- 가져오기는 앱 걸음에 맞춰 간다: 예비 로그에서 "import step k+1"은 앱이 걸음 k를 끝낸 뒤 나온다(n1: 1363 import ↔ step 1362, 1364 import ↔ step 1363) `[측정]`. gin-mirror 설계의 "단계 맞춤 가져오기"다 `[소스: mirror/EXPERIMENT.md:92]`.
- 게시 뒤 기한: `gdakiMiPublishedDeadlineUs`(`gdaki.cc:8934–8936`) = min(v1, 장치 한도); v1 = max(게시 + max(`NCCL_GIN_RESTORE_MS` 20 000, round 25 000 + handshake 3 000), REJOIN + 30 000 + 3 000)(`gdaki.cc:5972–5978`); 장치 한도 = gate가 홀수가 된 때 + (`NCCL_GIN_TS_HOLD_MS` 30 000 − shareMs − 1 000)(`gdaki.cc:5956–5958`, `14896–14899`), shareMs = min(round/2 12 500, 4 × `copyMs` 2 000) = 8 000(`gdaki.cc:1898`, 기본값 `gdaki.cc:3567–3568`) → **gate 홀수 뒤 21 000 ms** `[소스]`. 로그의 hold_ms 30000, round_ms 25000, handshake_ms 3000과 맞고 `[측정: r2.log gdakiTsStart 줄]`, 잰 hold 시작 → fallback 20 996.2–20 997.5 ms, FENCED → fallback 20 787.4–20 792.2 ms(FENCED가 hold 뒤 약 208 ms)와 맞는다 `[측정]`. `NCCL_GIN_RESTORE_MS`(20 s)는 묶는 항이 아니다.
- fallback 사유 글: `gdaki.cc:15745–15751`.

### 인과 (추론)

생존 rank 셋의 hold가 약 95 ms 어긋나는 동안 rank 3은 살아서 돌았으므로(박동 쓰기만 멈춤, `ctl/EXPERIMENT.md:254`) 늦게 hold한 rank 1은 걸음을 더 나갔고, 일찍 hold한 rank 0(과 2)은 걸음 m을 보낸 뒤 걸음 m + 1의 put이 홀수 gate에 묶였다. 되살린 rank는 export로 걸음 ≤ m을 다 받지만 걸음 m + 1에는 rank 0의 메시지가 live로 와야 한다. 그 put은 INJECTED가 와야 풀리고, INJECTED는 가져오기가 `last_step` = m + 2에 닿아야 나오며, 걸음 m + 2의 가져오기는 앱이 걸음 m + 1을 끝내야 나온다. 원형 기다림이고, 장치 한도 21 s에서 fallback이 끊는다 `[추론: 위 측정과 소스로 닫힘, 원형의 마지막 고리(가져오기 k+1 ↔ 걸음 k)는 로그 순서로만 확인]`. 차가 1이면 `last_step` = m + 1의 가져오기가 걸음 m(모두 export 안) 뒤에 나와 INJECTED가 오고 묶인 put이 풀린다(복원된 helper n2, n3이 이 꼴) `[측정+추론]`.

- 데이터는 틀리지 않았다: fallback 시행의 kv는 `dev_bad=0 recv_bad=0 xhist_bad=0 recv_poison=0 dev_poison=0`, `x_match=0`은 끝까지 가지 못하고 오류로 풀렸기 때문이다(`released=1`, `exit=4`) `[측정: raw/gc4_freeze12000_fence_gc_n1_r0.kv, _spare.kv]`. 채점기의 "안전성 항 어긋남"은 규칙대로이지만(게시가 있었던 시행이라 성능 실패로만 세지 않음) 실제로는 **복원이 끝나지 못한 성능 실패**다.
- window 검사는 다섯 모두 `changed=0`, `win_verified` 1 `[측정]`. 펜스 자체는 맞게 됐다.

### 분류와 고칠 것

- **(a) 라이브러리 결함**(gin-mirror의 "gate는 INJECTED까지 홀수" + "단계 맞춤 가져오기"가 생존 rank 사이 보낸 걸음의 차 ≥ 2를 만나면 막힘). 그 차는 살아서 도는 대상과 생존 rank 사이 판정 시각 퍼짐(약 한 READ 주기)에서 오는 실제 동작이다 `[추론]`. kill, SIGSTOP, GPU hang 셀은 대상이 걸음을 더 못 가 이 차가 생기지 않는다 `[추론]`.
- 가장 작은 고침 후보 `[추론, 설계 검토 필요]`: (1) INJECTED를 생존 rank마다로: 되살린 rank의 가져오기가 그 생존 rank의 export `last_step`에 닿으면 그 rank에게 INJECTED(그 rank의 gate만 짝수로); 또는 (2) 게시 뒤 gate를 홀수로 두는 조건을 "그 생존 rank의 export `last_step` < 가져오기 끝"으로 좁힘. 어느 쪽이든 단위 장면은 "export last_step이 m, m + 1, m + 2로 갈린 셋"이 필요하다.
- 결과 글(제안): "살아서 도는 프로세스의 펜스(`freeze_fence_restore`): 2/5, 재검토. 펜스, window 검사(바뀐 칸 0), 활성화, 게시는 다섯 모두 됐다. 셋은 생존 rank의 판정이 약 95 ms 퍼져 hold 때 보낸 걸음이 2 차이 났고, 되살린 rank가 일찍 hold한 rank의 다음 걸음 메시지를 기다리는 동안 그 메시지는 INJECTED를 기다려 gate에 묶였다. 장치 한도(gate 홀수 뒤 21 s)에서 fallback했고 잘못 전달된 데이터는 없다(손상, 독 값 0)."

## 3. helper만 멈춘 rank의 펜스 (`helper_stall_fence`): 재검토 1/5

- n5는 항목 2와 **같은 길**이다: 판정 10 005.1–10 102.7 ms(rank 1이 약 97 ms 늦음), hold 때 보낸 걸음 1368 / 1370 / 1368, import plan `last_step` 1370, 예비가 걸음 1369에서 `got=2053 want=2055`, rank 0과 2에 걸음 1369 `tx_err=3`이 fallback 뒤에 찍힘, rank 0 "no INJECTED … before the deadline", hold → fallback 20 997.5 ms, FENCED → fallback 20 787.8 ms `[측정: raw/gc4_helper_freeze12000_gc_n5_*.log, trials_scored.csv]`.
- n1–n4는 판정 퍼짐 1.4–4.7 ms, 걸음 차 0–1, 모두 INJECTED 뒤 복원 `[측정]`. 문턱 4/5는 넘어 판정식은 참이지만 안전성 항 셋(`ow_data_equal`, `revived_done`, `wait_held`)이 n5에서 거짓이라 재검토다 `[측정: SCORE.md:266–276]`. n5의 kv도 손상과 독 값 0 `[측정]`.
- **(a) 라이브러리 결함**, 항목 2와 같은 고침이 닫는다 `[추론]`.

## 4. STOP_left 둘 (C1 15:41:58, RG-gc-G2 17:47:18)

### 두 검사가 세는 것이 다름

- 시행마다의 `left=`: `pgrep -x gin_mi`(두 노드)만 센다 `[소스: ctl/impl/test/run_gc.sh:992]`.
- hold 끝의 검사: `pgrep -x gin_mi; pgrep -x gin_mi_nomacro; gin_fdhold; gin_launcher; pgrep -f "[/]tmp/gc_rt"; "[/]tmp/gc_cost"; "[/]tmp/gin_mrr_"`(두 노드), snap 뒤 `[소스: hold_gc.sh:94–96, 406, 417–418]`. 시행의 작업 디렉터리가 `/tmp/gc_rt.XXXXXX`라(`run_gc.sh:224`) 그 경로를 인자로 가진 **모든** 프로세스가 잡힌다.

### 남은 프로세스: snapshot subshell의 자식 python 대기

- 실행기는 시행마다 ss snapshot 둘을 뒤에서 기다리는 subshell을 띄운다: `wait_line "$WORK/r0.log" "GINRS step rank=0 step=…" … 30`(걸음 ≥ 30, 한도 30 s) 뒤 `… 15`(걸음 ≥ 80, 한도 15 s) `[소스: run_gc.sh:796–800]`. `wait_line`은 `python3 -c "$WAITPY" "$WORK/r0.log" …`이고 파일을 2 ms마다 다시 읽으며 한도까지 돈다(`run_gc.sh:425–438`). 인자에 `/tmp/gc_rt.XXXXXX/r0.log`가 있다.
- 시행 끝에 실행기는 `kill "$SSPID"`로 subshell(bash)만 끝내고(`run_gc.sh:929`) 남은 job을 `wait`한다(`run_gc.sh:930–932`). 그 자식 python은 죽지 않고 부모를 잃은 채 한도까지 돈다 `[소스+추론]`. 작업 디렉터리는 trap에서 지워지므로(`run_gc.sh:231–232`) 그 뒤로는 없는 파일을 열다 실패하며 돈다.
- 걸음 기준에 못 미친 시행만 이 python을 남긴다 `[측정: raw/*_ss.out의 s1, s2 줄]`: `gc4_kill3_ow_spareabsent` 5(걸음 52에서 끝, s2 없음 → 15 s 대기가 남음), `mi4_refuse_*` 9와 `rs4_refuse_*` 9(걸음 0, s1도 없음 → 30 s 대기가 남음), `mi4_seg_128k` 5(s2 없음).
- 시각이 맞는다 `[측정]`:
  - C1의 마지막 시행 `gc4_kill3_ow_spareabsent_gc_n5`: s1 snapshot 6139268.14, 둘째 대기의 끝 약 6139283.1, launcher `trial_end` 표시 6139275.13, meta 15:41:56.00, 검사 15:41:58(표시 뒤 약 5 s) → 대기 하나가 살아 있음 → **1개**.
  - G2의 마지막 셋 `mi4_refuse_sl` n1–n3: meta 17:46:57.6, 17:47:06.8, 17:47:15.9(약 9.1 s 간격, wall 1.9 s), 각 30 s 대기 → 17:47:18에 셋이 살아 있음(그 앞 `mi4_refuse_mirror1` n3의 대기는 약 17:47:12에 끝) → **3개**.
  - 다른 hold의 마지막 시행(`mi4_overflow`, `rs4_kill3_spareabsent`, `mi4_kill3_ow_sampled`, `gc4_fdhold_uverbs_kill3` 등)은 모두 s2를 찍어 대기가 끝났고 STOP_left가 없었다. 다음 hold 시작 검사(`hold_gc.sh:143–144`)는 1분 45초, 44초 뒤 0이었다(C2 15:43:43, R1 17:48:24 시작) `[측정: chain.out]`.
- 프로세스 종류의 직접 증거(검사 순간의 목록)는 남지 않았다: `left()`가 줄 수만 센다 `[미확인]`. 위 대응은 수와 시각이 두 사건 모두 맞는 유일한 후보다 `[추론]`. launcher 정지는 `gin_launcher` pid가 끝날 때까지(좀비는 끝난 것으로) 기다리고(`launcher_gc.sh:128–153`, `:92`), `trial_end` → meta 간격이 두 마지막 시행 3.0–3.3 s로 전체 시행 2.98–4.20 s 안이라 launcher가 늦게 끝난 흔적은 없다 `[측정: 1초 단위 벽시계로 어림]`.

### 시행 자료 영향

- 없다 `[추론]`. 남은 python은 그 시행의 r0 로그를 읽기만 하고 신호, 네트워크, GPU를 쓰지 않으며 30 s 안에 스스로 끝난다. 다음 1–3 시행 동안 rain에서 2 ms 주기의 파일 열기 실패 고리 1–3개가 같이 돌았다(G2의 거절 셀끼리, C1의 spare 없음 셀끼리; 두 셀 가족의 판정 값은 `spare_absent_refused` 5/5 맞음이고 거절 셀은 예측이 없다). C1, G2의 자료를 그대로 채점한 결정과 맞다.
- s2가 없는 시행은 STOP과 무관하게 걸음 기준 때문이다.

### 분류와 고칠 것

- **(b) 실행기 결함**(라이브러리, 시행 자료와 무관).
- 가장 작은 고침 후보 `[추론, 실행 안 함]`: `WAITPY`가 작업 디렉터리가 없어지면 곧 끝나게(`os.path.isdir(os.path.dirname(f))`가 거짓이면 종료). 또는 `kill "$SSPID"` 앞에 그 subshell의 자식 PID(`pgrep -P "$SSPID"`, 자기 PID로 고른 자기 자식만)를 먼저 끝냄. 글: "STOP_left 둘은 시행 끝에 실행기가 snapshot subshell만 끝내고 그 자식 대기 프로세스(인자에 시행 디렉터리 경로)를 남겨 hold 끝 검사가 잡은 것이다. 시험 프로세스(`gin_mi`, launcher, 예비 프로세스)가 남은 것이 아니고 시행 자료는 영향받지 않았다."

## 그 밖의 이상

1. **SCORE.md 머리 "STOP 파일: 없음"**(`SCORE.md:7`): STOP 파일을 `stops/`로 옮긴 뒤 채점해서다. 두 STOP_left가 있었다는 사실과 위 원인을 결과 글에 따로 적어야 한다 (b).
2. **준비 실패 17은 모두 거절 셀이지만 `mi4_refuse_*`만이 아니다**(`SCORE.md:9–10`): gin-mirror 거절 셀 9(`mi4_refuse_csum`, `mirror1`, `sl` 각 3) + gin-restore 거절 셀 8(`rs4_refuse_gintype` 3, `restoreoff1` 2, `symgin` 3) `[측정]`. EXPERIMENT 12절 2026-11-18 행(`ctl/EXPERIMENT.md:1689`)의 "모두 gin-mirror의 거절 셀 `mi4_refuse_*`"는 틀린 글이다. 설계대로의 거절은 맞다(17 모두 `resume_err_all` 1, `reason_same` 1) `[측정]`.
3. **준비 실패로 가르는 실제 조건은 거절이 아니라 링 live 실패다**: 회귀 셀은 `status_regression`에서 `ring_live_all == 0`이면 `prep_failure`(`score_gc.py:449–450, 422–425`). 그래서 같은 거절 셀 `rs4_refuse_restoreoff1`의 n2는 네 rank 모두 링이 live(`ring_live_pairs` 6)라 "scored", n1, n3은 둘만 live(1쌍)라 준비 실패로 갈렸다 `[측정: trials_scored.csv]`. 시각 경쟁의 차이다 `[추론]`. 이 셀들을 읽는 예측은 없어 판정은 바뀌지 않는다 (b, 보고만).
4. **묶음 키 `build:gc`의 준비 실패 2**(`SCORE.md:548, 524`): 묶음은 채점된 시행이 하나라도 있는 키만 넣어서(`score_gc.py:726–732`) `restoreoff1`의 둘만 들어가고 다른 거절 셀 15는 빠진다. "전체 성공 326/328 = 99.4 %"는 거절 셀이 설계대로라는 점을 반영하지 못한 수다 (b, 보고만; `no_tcp_control`은 채점된 326으로 맞음, `long_hold_lane`은 자료 없음).
5. **`skipped.txt`는 셀마다 처음 건너뛴 시행만 적는다**: `fits`가 실패하면 그 셀의 남은 반복을 `break`로 모두 건너뛴다(`hold_gc.sh:149–152, 340–341`). 그래서 C10 첫 pass에서 실제로 건너뛴 시행은 13(`gpuhang12000_ctx1_fence` n3–n5, `quiet12000` n1–n5, `gpuhang12000_waitpend_fence` n1–n5)인데 줄은 셋이다. C10-r2가 그 13을 돌렸다(`hold_C10-r2.out` 시행 13, 이미 함 22) `[측정]`. RG-gc-G1은 `mi4_kill3_ow_sampled` n5 하나(G1-r2가 1 시행). EXPERIMENT 12절 행의 "C10 셋, RG-gc-G1 하나"는 "C10 세 셀의 13 시행, G1 1 시행"으로 고쳐 적을 것. 완결성(180/180, 회귀 198, 비용 24, 합 402)은 맞다 `[측정: trials_scored.csv 402행]`.
6. **C10을 두 번 더 돌림(C10-r3, C10-r4)**: 시행 0, 모두 "already done"(16:54:31–16:55:42) `[측정: chain.out, hold_C10-r3.out, hold_C10-r4.out]`. 자료 영향 없음, 기록에만 적을 것.
7. 머리의 "예상된 다시 띄우기 한도 줄 10줄"(`SCORE.md:11`)은 spare 없음 셀 두 가족 5 + 5 시행의 launcher 줄로 설계대로다 `[측정: hold_C1.out, hold_RG-gc-R2.out]`.

## 다시 셈과 한계

- 이 문서의 수는 모두 `trials_scored.csv`, raw 로그, meta, hold 출력에서 이 조사가 다시 셌다. 채점기 출력의 수와 어긋난 것은 없다(어긋난 것은 EXPERIMENT 12절 행의 글 둘: 항목 그 밖 2, 5).
- 시각 대응의 벽시계 쪽은 로그의 초 단위 날짜와 파일 수정 시각이라 1 s 안팎의 어림이다(항목 4).
- 항목 2의 고침은 설계 제안이고, 고친 라이브러리를 시험하지 않았다.
