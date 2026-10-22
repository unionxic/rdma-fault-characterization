# gin-control int3: 2a-2-C 1–3단계와 병렬 조각 넷을 한 트리로, 그리고 둘째 하드웨어 smoke (작업 기록, 2026-10-22)

트리는 세션 스크래치 `agent_gc_p2a2/nccl-src`이고 제자리에서 했다(복사 없음). 호스트 파일 하나, 장치 코드 0줄. 저장소에는 `git add`, commit, push를 하지 않았다.
`EXPERIMENT.md`, `launcher/*`, `test/*`는 고치지 않았다. smoke 결과는 [../results/20261022_smoke2/SMOKE.md](../results/20261022_smoke2/SMOKE.md).
표시: `[측정]` 돌려서 봄, `[소스]` 코드를 읽어 확인, `[추론]` 해석, `[미확인]` 확인 안 함.

## 단계

1. 작업 트리(2a-2-C 3단계)를 커밋 `7c21390` "gin-control 2a-2-C step 3 (gc_layer_int.diff c884c86c)"로(ln4 대비 diff md5 c884c86c 확인) `[측정]`
2. 조각마다 그 바탕에서 가지를 만들고 diff를 `git apply`(넷 모두 그대로 적용) `[측정]`:
   `smokefix` = acfede7 + `gc_layer_smokefix.diff`(10f7e810) → `5dea832`, + `gc_layer_sparefix.diff`(99b6eb47) → `8d4acb5`;
   `live` = acfede7 + `gc_layer_live.diff`(6a4cbf92) → `fecc6e5`; `snap` = 45274b6 + `gc_layer_snap.diff`(17892f1f) → `04be5e1`
3. 그 차례로 3-way 합침(`git merge --no-ff`): `c7a1dd0` + smokefix + sparefix, `00135cc` + live, `0f6c96f` "gin-control int3: + snap". 글자 충돌 0, 0, 0 `[측정]`
4. 헤더 요청을 worktree `rs_ctrl_api.h`에: 023f013d + `rs_ctrl_api_p2a2c.diff`(→ c1bd61d8) + `rs_ctrl_api_live.diff`(→ d6b329a2, hunk 다섯 모두 offset 17–26줄로 적용). live 요청만 023f013d에 얹으면 live의 pin 헤더(789e5425)와 바이트 같음 `[측정]`. 그다음 `repaste`(seams 176줄, API 1 015줄)
5. 합침의 접착(작업 트리): p2a2c 헤더 요청이 적은 대로 호스트의 ring model 영역에 있던 사본(`GDAKI_TS_CTRL_PATH`, `GDAKI_CTRL_PM_*`, `struct gdakiCtrlPathMark`와 그 static_assert)을 지우고 주석 두 줄로, `offsetof(struct gdakiCtrlEnv, rsv)`와 `e.env.rsv` 두 곳을 `pathMark`로
6. `build_gc.sh`에 키 `int3`(아래), 검사, 빌드, smoke, smoke 고침, 검사 다시

## 충돌과 해결

글자 충돌은 셋 모두 0이었다. 뜻이 겹치는 자리는 다음을 읽어 확인했다 `[소스]`.

| 자리(맡김 글의 영역) | 겹친 것 | 해결 |
|---|---|---|
| Resume(smokefix, sparefix) | smokefix의 걸쇠 기다림, sparefix의 활성화 전 예비 역할(기다림 없음, 41 지움) 대 2a-2-C의 `gdakiCtrlResumeFacts` | 둘 다 그대로. 기다림 고리 → 사실 모으기 → 41 지움 순서 유지 |
| page/probe(live) 대 smokefix | `gdakiCtrlProbeSummary`(live의 `dev_*` 열과 smokefix의 한 번만), `gdakiCtrlPageStep`(smokefix `sumReq` 뒤 READ 멈춤, live의 READ 짝은 `gdakiProbePeerStep` 안) | 그대로 맞음. 요약은 teardown이나 free에서 한 번, 요약 뒤에는 박동만 |
| page/probe(live) 대 2a-2-C ring/seams | live는 page 영역과 all-gather 칸(`dev`, 전의 `rsv[4]`), 2a-2-C는 ring 영역과 REJOIN | 글자 겹침 없음. `syn`과 시험이 통과 |
| store(snap) 대 ring 1–3단계 | `gdakiCtrlStoreMemLine`(snap의 장치 staging 열, 단계들의 `ring up` 열) | 한 줄에 둘 다 |
| 헤더 블록 | p2a2c(봉투의 `pathMark`, 기록 56과 표지), live(`devLine`, `dev` 칸, R과 SQ 주석) | 헤더를 합친 뒤 `repaste`; 호스트의 표지 사본 지움과 `rsv` → `pathMark`(위 5) |

합친 뒤 첫 `syn`, `api`, `unit`이 모두 한 번에 통과했다 `[측정: agent_gc_p2a2/logs_int3/syn_1.log, api_1.log, unit_1.log]`.

## `build_gc.sh` 키 `int3` (fe2936d8 → 6a79837d, 975줄)

`BR=int3`는 int2의 단계를 그대로 쓰고(트리 `agent_gc_p2a2/`, 입력과 시험 이 폴더, `LAYER=gc_layer_int.diff`) 다음을 더한다. 출력은 `gc_int3*`, IDTAG `int3`.

- 머리 커밋 이름 "gin-control int3: + snap"
- `build_gc_p2a2.sh`(23977026)의 p2a2c 몫: `p2a2regions`의 자르기 목록에 `gdakiCtrlRejoinFail`, `gc_unit_prep`의 링 send 훅 stub이 소켓 fd 인자를 받는 꼴
- `build_gc_live.sh`(218b8b4a)의 몫: `unitliveone`(gc_unit_live.cc를 자른 폴더에 복사해 컴파일), 단계 `unitlive`. live의 "RejoinFail 빼기"는 넣지 않음(int3의 시험은 3단계 판)
- `build_gc_snap.sh`(a492ba8f)의 몫: `regions`가 `gin-control (snap): pure`를 `gc_snap_pure.inc`로 자름, `unitsnapone`, 단계 `unitsnap`
- `unit`이 끝에 `gc_unit_live`, `gc_unit_snap`을 돌림. `info`가 새 diff와 시험 파일의 md5를 적음

## smoke 고침 (gc_layer_smoke2fix.diff, 52줄, +14/−1)

a2에서 UD REJOIN이 rank 0에서 늘 REFUSE였다. 받는 단계(`gdakiCtrlRjAcceptStep`)가 청한 생존 READ QP CONNECT를 helper의 넘기기(`gdakiProbeHandHelper`)가 lineage로 거절했다:
ln4는 알려진 incarnation을 REJOIN_ACK 뒤에 올리므로 그때 incarnation 1은 FUTURE다. 고침: `gdakiCtrlPeerProbe::rjAccInc`(페이지 mutex 아래, 받는 단계가 CONNECT 앞에 적음)와 같은
incarnation이 HOLD_WAIT의 dead + 1이면 CURRENT처럼 받음. 자세한 것은 SMOKE.md "고친 것". 이 조합을 부르는 CPU 시험은 없다(가짜 감시 스레드가 helper 몸을 비움) `[소스]`.
그래서 이 고침의 근거는 a3의 실제 NIC 시행 하나다 `[측정, n 1]`.

## 검사 표 (마지막 트리 = 0f6c96f + 접착 + 고침; 로그 스크래치 `agent_gc_p2a2/logs_int3/`, 모두 `build_gc.sh` BR=int3)

| 검사 | 결과 | 로그 |
|---|---|---|
| `api` | ctrl API 8be60f3f, seams fdb6c7ad = `rs_ctrl_api.h` d6b329a2; launcher wire = `launcher_msg.h` fb11b235(554줄); 헤더 단독 rdma와 tcp; `TCP_CELLS` 단독 거절: 통과 | `api_f1.log` |
| `syn` | build, build-gcp, build-gct 통과 | `syn_f1.log` |
| `gc` / `gcp` / `gct` / `gctp` | 빌드됨, 경고 0; libnccl `af8b0b84` / `7f8ea234` / `768fd112` / `2e954c08`(고치기 전 판 `6e34a97a` / `7184ba1e` / `51bda228` / `b0ced446`) | `build_gc_f1.log`, `build_{gcp,gct,gctp}_f1.log` |
| `pre` | gct 0 hunk, gctp 0 hunk, gctc 2 hunk 3줄(RST 간격, 정규화 md5 b1b76e0e로 int2와 같음), gc 111 hunk(기록용) | `pre_f1.log` |
| `sites` | MISMATCH 0, 149행, `#if NCCL_GIN_CTRL_TCP` 갈래 49개 모두 ln4 글, page 1 494, ring 3 759 코드 줄; `gc_sites.tsv` 440d9437 그대로 | `sites_f1.log` |
| `unit` rdma | mi_unit 다섯, rs_unit_host 348 739, rs_spare_unit 171, gc_unit_prep 116 장면 366, gc_unit_p1 10 248 976, gate_fenced 10/10 64, gc_unit_p2 3 993 471, gc_unit_p2b 11 114, gc_unit_p2a2 5 251, gc_unit_p3 16 장면 473, gc_unit_live 273 397, gc_unit_snap 453 402: 모두 실패 0, sanitizer 보고 0 `[n 1]` | `unit_f1.log` |
| `unit` tcp | 옛 일곱 실패 0, gc_unit_prep 48 장면 174, p1, p2, p2b, p2a2, live, snap 0 검사, p3는 rdma만: 통과 | `unit_f1.log` |
| `ident` (IDTAG int3f1) | 설치 헤더 ln4와 같음, 프로그램 16/16 같음, 장치 객체 207 × 4 SASS와 바이트 같음, 라이브러리 넷 자원 같음 | `ident_f1.log` |
| `diff` | `gc_layer_int.diff` 907116f3(12 907줄, ln4 f53e5d2 대비, 거꾸로 적용 확인); 그 가운데 접착과 고침(작업 트리 대 0f6c96f) 192줄 md5 2e4cc6d0; `__device__`/`__global__` 더한 줄 0 | `diff_f1.log` |

고치기 전 판(접착만)도 같은 검사를 모두 통과했다(`*_1.log`; `gc_layer_int.diff` 그때 55896c95, ident IDTAG int3) `[측정]`. `gc_unit_p2a2`의 수는 기다림 고리 때문에 실행마다 조금 다르다(3단계 5 262, 여기 5 251).

## smoke (요약; 자세한 것은 SMOKE.md)

| 시도 | 라이브러리 | 셀 | 결과 |
|---|---|---|---|
| a1 | `6e34a97a` | 장애 없음 + 예비 프로세스(`SPARE=1 SPARE_RANK=3`) | 통과: go 파일 뒤 띄움(2 818.9 ms 기다림), HELLO 406.3 ms, `spare_ready`, 생존 셋 무장, STOP 0 |
| a2 | `6e34a97a` | `gc4_kill3_ow@gc` | 실패: rank 0의 UD REJOIN REFUSE(lineage), 시한 뒤 FALLBACK |
| a3 | `af8b0b84` | `gc4_kill3_ow@gc` | 통과: kill → 판정 0.312–0.423 ms(`cause=FIN`, ln4 증인 소켓 규칙; 확인 창은 `unconfirmed`, 표 9행 보고만), FENCE → FENCED 113.1 ms, 활성화 122.0 ms(LATER 0), UD REJOIN 셋 try 1, STATE outbox, 판정 → 게시 186.2 ms, 데이터 같음 |
| a4 | `af8b0b84` | 장애 없음 + 예비 프로세스 | 통과(a1과 같은 줄, HELLO 397.3 ms) |

## 2a-2-C와 실행 쪽에 넘길 것

- launcher의 EXITED 보고는 FENCE가 그룹 끝보다 먼저 오면 나오지 않는다(a3: FENCE kill 뒤 5.8 ms, 그룹 끝 113 ms 뒤 FENCED) `[측정]`. 채점 쪽 "launcher 보고" 열을 볼 것.
- 복원 뒤 생존 rank 요약의 `witness_conns=2`, 열 `witness_pairs=9`/12 `[미확인: 다시 걸기가 끝났는지]`.
- 낡은 줄 글 둘(SMOKE.md "남은 것"). 다른 장애 주입은 실제 NIC에서 아직 없다.

## 파일 md5 (worktree `control/impl/`)

| 파일 | md5 | 줄 |
|---|---|---|
| `gc_layer_int.diff` (ln4 대비 전체 층, int3 + 고침) | `907116f3f5fa766aa51dd595206a2cab` | 12 907 |
| `gc_layer_smoke2fix.diff` | `bc12a1446dbda03c7b3d22d10489e980` | 52 |
| `rs_ctrl_api.h` (023f013d + p2a2c + live) | `d6b329a259f651b27818e102f3a7f0ad` | 1 344 |
| `build_gc.sh` (fe2936d8 + 키 int3) | `6a79837dbf525284f978aa7f39b70309` | 975 |
| `gc_sites.tsv` (바뀜 없음) | `440d94377aa715aacaf4318bb3c57bf3` | 178 |
| 시험(바꾸지 않음) | `gc_unit_p2a2.cc` e9fe6ade, `gc_unit_live.cc` 32177505, `gc_unit_snap.cc` 43eabeaf | 2 578, 524, 665 |
| 스크래치 호스트 파일 | `6917aa94f67558a75fd15aa061de1a72` | 36 310 |
| libnccl gc(smoke a3, a4) | `af8b0b84d6ea1f4fe6f293a6be190f2d` | |

입력(바꾸지 않음): `gc_layer_smokefix.diff` 10f7e810, `gc_layer_sparefix.diff` 99b6eb47, `gc_layer_live.diff` 6a4cbf92, `gc_layer_snap.diff` 17892f1f, `rs_ctrl_api_p2a2c.diff` ebcb1090,
`rs_ctrl_api_live.diff` 8bdbcdb2, `launcher/launcher_msg.h` fb11b235, `launcher/gin_launcher.c` 5b62a1f5.
