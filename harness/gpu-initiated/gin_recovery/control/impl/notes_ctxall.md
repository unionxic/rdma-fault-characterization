# gin-control ctxall: 모든 GIN context의 GPU 진행 줄 (사용자 결정 2026-10-24 (가), 작업 기록, 2026-10-23)

상태: **코드 수정 완료 / 로컬 단위 검증 완료 / 하드웨어 검증 대기**.

트리는 세션 스크래치 `agent_gc_p2a2/nccl-src`이고 제자리에서 했다(기준 HEAD `2040fe5` "gin-control: ward QP ERR confirmed
before activation", ln4 `f53e5d2` 대비 diff가 `9c16b732`임을 먼저 확인 `[측정]`). 호스트 파일 `gin_host_gdaki.cc` 하나, 장치 코드
0줄. 클러스터, ssh, GPU 실행은 없다. 빌드(gc, 컴파일만), `syn`, `api`, CPU 단위 시험만 했다. worktree에는 commit하지 않았다.
표시: `[측정]` 돌려서 봄, `[소스]` 코드를 읽어 확인, `[추론]` 해석, `[미확인]` 확인 안 함.

## 무엇을, 왜

- 전에는 GIN context 0의 장치 QP 배열 하나만 GPU 진행 줄로 읽었다(`notes_live.md` 7절 3). application이 다른 context만
  쓰면 그 GPU의 멈춤은 보이지 않았다 `[소스]`.
- 이제 rank의 모든 user GIN context c ∈ [0, ginContextCount)의 줄을 등록하고 읽는다. gin-mirror가 그 뒤에 붙이는 mirror
  context는 이 범위가 아니라서 넣지 않았다(`gdakiMiUserCtxOf`: mirror context를 만들었으면 `nUserCtx`, 아니면
  `nContexts`) `[소스]`.

## 판정 규칙 (정확히)

- 읽는 쪽은 상대 p의 context마다 정체 시계 `devStale[c]`를 따로 둔다. 시계 하나의 규칙은 전과 같은
  `gdakiCtrlDevOnRead`이고 그 context의 줄만 본다: 줄이 바뀌면 그 context의 원점을 되돌리고, 그 context에 남은 일이
  없으면(조용함) 역시 그 context의 원점만 되돌린다. 읽는 쪽 간격(> 2 x PROBE_MS) 규칙도 context마다다.
- R (2)-(5)의 입력 `devStaleMs` = max_c (lastMs_c − firstMs_c) (`gdakiCtrlDevStaleOf`). 그래서
  - `pending_any`: 어느 context든 남은 일이 있어야 정체가 0보다 크다.
  - 멈춤(14행)은 남은 일이 있는 **어느 한** context의 줄이 STALL_MS 동안 그대로일 때다(분할 막이와 데이터 경로 거부권은
    그대로 붙음).
  - 조용한 context는 정체가 0이라 max에 들지 않는다. 남은 일이 있는 다른 context의 시계를 가리지도, 되돌리지도 않는다.
  - 진행하는 context는 자기 시계만 되돌린다. context 0이 진행해도 멈춘 context 1은 가려지지 않는다.
  - "진행"(어느 context든 줄이 바뀜)은 보고용 사실이다. R (1)이 되는 것은 어느 context도 정체가 없을 때뿐이다.
    요청의 `progress = any context's line changed`를 시계 되돌림으로 읽으면 장면 2를 놓치므로 이렇게 정했다 `[추론]`.
- 어느 context가 걸렸나: 가장 큰 정체의 context(같으면 낮은 번호), 판정마다 `devCtx`. 전부 0이면 −1.
- `f.devMode`는 페이지가 이름 댄 context가 하나라도 있을 때, `f.devOk`는 이름 댄 context **모두**의 줄 READ가 이 QP 세대에
  한 번 이상 성공했을 때다(아니면 13행). 페이지 낱말 `staleMs[q]`는 context들 가운데 큰 값(`gdakiCtrlDevStaleAt`).
- 데이터 경로 거부권은 고치지 않았다. context 0의 트래픽이 이 rank의 QP에 닿으면 응답자 수가 움직여 context 1의 GPU 멈춤도
  18행에 머문다(한 context일 때와 같은 규칙). 시험 장면 "veto held"가 이것을 보인다 `[측정]`. 그 트래픽이 다른 rank로만
  가거나 QP 감시가 꺼져 있으면 14행이다.

## 바꾼 것 (모두 `#if !NCCL_GIN_CTRL_TCP` 안; ctrl API와 seams 블록은 바이트 그대로)

| 자리 | 무엇 |
|---|---|
| 순수 영역 "gin-control (page)" | `GDAKI_CTRL_DEV_MAX_CTX` 8, `gdakiCtrlDevStaleOf`/`At`, 페이지의 context 줄 낱말(`gdakiCtrlDevxHead`, `gdakiCtrlDevLinesOf`), all-gather 칸 `struct gdakiCtrlDevAgX`(count + 7칸, 120 B), `gdakiCtrlDevCtxFits`, READ 종류 `gdakiCtrlProbeDevKind(c)` = `PW_DEV` + c(context 0은 전과 같은 4), 사슬 `periodicMore`, `gdakiCtrlProbeChainSet`/`Due`/`Drop` |
| MR 등록 `gdakiCtrlDevSetup` | context마다 MR 하나. 배열마다 DOCA의 `doca_gpu_mem_alloc`(GPU 페이지 정렬)이 따로라 이어져 있지 않고, MR 하나로 덮을 수 없다 `[소스: doca_gpunetio.cpp export_multi_qps_dev]`. 전부 아니면 없음: 하나라도 실패하거나 context가 8을 넘으면 줄 없음(호스트 박동으로 되돌아감)과 WARN 한 줄. BAR1은 context마다 GPU 페이지 하나(64 KiB) `[추론]` |
| setup all-gather | context 0은 전처럼 `gdakiCtrlSetupAddr::dev`(168 B 그대로). context 1..는 `gdakiTsAddr::devx`(launcher 칸 뒤, count + 배열). `gdakiCtrlSetupAddr`가 ctrl API 블록(헤더와 바이트 같음) 안이라 그 밖의 `gdakiTsAddr`를 120 B 늘렸다. 예비 프로세스의 transcript 길이가 바뀌어 이전 빌드의 것은 재생되지 않는다 `[소스]` |
| 상태 페이지 | context가 둘 이상이면 layout의 쓰는 부분 바로 뒤 64 B에 context 줄: 낱말 0 = "DEVX" + 개수, 낱말 c = context c의 `gdakiCtrlDevLineWord`. 줄 0의 `devLine`은 context 0 그대로. layout(`gdakiCtrlPageLayoutOf`, 링의 layout 비교)과 PAIR의 길이는 그대로다. 가장 큰 layout 4 032 B + 64 = 4 096 B로 페이지 안 `[측정: 시험]`. context 하나면 이 줄도, 더 읽는 바이트도 없다 |
| 주기 READ | 페이지 READ가 context 줄까지 읽는다(context > 1일 때만 64 B 더). 첫 context의 줄은 전처럼 짝으로, 나머지는 사슬로: 그 주기의 READ가 2개 미만 떠 있고 창이 남긴 자리가 있으면 다음 context를 낸다. 주기는 마지막 완료 뒤 한 번 판정. 사슬은 QP가 감시 스레드 것이 아니거나 RTS가 아니거나 post가 실패하면 그만두고(그 주기의 나머지는 내지 않음), 떠 있는 것이 없으면 그때 판정한다. 페이지가 이름을 바꾸면 그 주기의 나머지를 내지 않는다 |
| SQ와 CQ | `GDAKI_CTRL_PROBE_SQ` 4와 watch CQ 64는 그대로다(헤더 블록 안이고, 올리면 rank 수가 적어도 CQ 한도에 걸림). 사슬이 주기의 동시 READ를 2 이하로 지켜 짝 2 + 창 2 = 4가 유지된다 |
| 완료 처리 | wr_id 종류에서 context를 읽어 그 context의 버퍼(`gdakiPageDevRd(pg, p, c)`, 상대마다 `devCtxN`칸)와 시계에만 넣는다 |
| 판정과 줄 | 의심 줄 `suspected (kind=gpu stale_ms=X ctx=k)`, 멈춤 줄 `judged stalled (...); STALLED to N rank(s); ctx=k; ...`(GPU 멈춤일 때만; 감시 스레드가 메일 앞에 `stallCtx`를 씀). 줄 등록 줄 `ctx=c of n`. `rows_gc.py`의 `CTXTOK`(`\bctx=(\d+)\b`)와 맞는다 `[소스]` |
| probe summary | 끝에 `dev_ctx=n dev_reads_ctx=a/b/.. dev_ok_ctx=a/b/.. dev_peer_more=N` 추가(기존 칸과 차례는 그대로; `dev_reads`, `dev_ok`는 모든 context의 합). status page up 줄에 `contexts=n page_read=B` 추가 |

## READ 수와 비용

- 상대마다 주기당 READ: **2 → 1 + contexts**(context 하나면 2 그대로). 페이지 READ는 하나 그대로다.
- 4 rank, context 4개 `[추론: 셈]`: 주기당 (320 + 64) + 4 x 1 184 B, 상대 3, 초당 10번이면 rank마다 약 154 KB/s(전 약 45 KB/s).
  받는 쪽 버퍼는 상대마다 context 수만큼 늘어난다(112 rank, 8 context면 약 30 MB) `[추론: 셈]`.
- `max_rd_atomic` 1이라 READ는 어차피 차례로 나가므로 사슬이 처리량을 줄이지 않는다. 사슬 한 걸음마다 감시 스레드 한
  step의 지연이 붙을 수 있다(주기 길이 1 + n RTT에 step 몇 번) `[추론]`. PROBE_TIMEOUT_MS에 견준 값은 재지 않았다 `[미확인]`.

## 단위 시험 `gc_unit_livectx.cc` (`build_gc.sh` 키 `unitlivectx`, `unit`에도 포함, BR=int3)

`gc_unit_live.cc`처럼 잘라 낸 page 순수 영역 위에서 돈다. `gc_unit_live.cc`는 고치지 않았다(한 context의 회귀 시험으로 그대로 통과).

1. 낱말: context 줄, all-gather 칸 120 B, 한도 1..8, READ 종류 4..11과 wr_id 왕복, 한 context의 수 그대로(SQ 4, 168 B, 320 B).
2. 시계: 한 context의 바뀜이나 조용함은 그 context만 되돌린다. 정체는 가장 큰 값(같으면 낮은 번호).
3. 규칙(읽는 쪽 하나, 100 ms마다, 호스트 박동 살아 있음): context 0 조용 + context 1 남은 일과 멈춘 줄 → 14행 +10 000 ms,
   ctx=1 / context 0 진행 + context 1 멈춤 → 14행 +10 000 ms, ctx=1(가려지지 않음) / 모두 조용(2개, 8개) → 20행만 / 모두 진행
   → 20행만 / 8개 중 context 5 멈춤 → 14행 ctx=5 / 둘이 멈춤 → 먼저 멈춘 context / +6 000 ms에 되살아남 → 18행만 / 아직 못
   읽은 context → 13행만 / 거부권 걸림 → 18행, 14행 없음 / context 하나 멈춤 → 14행 ctx=0 `[측정]`.
4. 변이(시험 안의 규칙): context 0만 보는 옛 규칙은 장면 1을 놓친다(20행만), 모든 줄에 시계 하나는 장면 2를 놓친다, 조용한
   context가 모든 시계를 되돌리면 장면 1을 놓친다 `[측정]`.
5. 사슬 모형: 64 실행 x 60 s(1..8 context, 셋 중 하나는 QP를 가끔 잃음), 주기 35 728, 끝난 주기 35 720(온전 35 185, 사슬을
   그만둔 535), 창 7 306, 시한 387. 온전한 주기의 READ는 모두 1 + contexts, 동시에 많아야 4(SQ 4), 한 주기는 많아야 2 `[측정]`.

소스 변이 시험(잘린 영역을 고쳐 같은 시험으로): `gdakiCtrlDevStaleOf`가 context 0만 보게 하면 9개 실패(장면 1, 2, 8 context,
둘 멈춤 등), `gdakiCtrlProbeOnCqe`가 사슬을 기다리지 않게 하면 32 465개 실패 `[측정: agent_gc_p2a2/mut_ca/]`.

## 결과

| 항목 | 값 |
|---|---|
| `gc_layer_int.diff` (ln4 commit `f53e5d2` 대비, patience; histogram도 같음) | md5 `f4819515`, 14 165줄, 역적용 검사 통과 `[측정]` (전 `9c16b732`, 13 830줄) |
| `gc_layer_ctxall.diff` (`2040fe5` 대비, patience) | md5 `cacf9f86`, 832줄, hunk 36, 더하기 412, 빼기 85, 호스트 파일 하나, 장치 코드 0줄, 역적용 검사 통과 `[측정]` |
| 호스트 파일 | md5 `710f2b4f`, 37 554줄 (전 `079cce5f`, 37 226줄) `[측정]` |
| libnccl gc (`build_gc.sh gc`, 키 출력 `gc_ca2`) | md5 `ea82cd71`, 빌드 경고 0 `[측정: logs_p2a2/build_gc_ca2.log]`. 첫 빌드 `gc_ca`는 `-Wformat-truncation` 경고 2개(ctx 글 버퍼 16 B)라 24 B로 고치고 다시 빌드했다 `[측정: build_gc_ca.log]` |
| `syn` (build, build-gcp, build-gct) | 셋 모두 통과, 경고 0 `[측정: logs_p2a2/syn_ca.log; 버퍼 고침 전 트리]` |
| `api` | ctrl API와 seams 블록이 `rs_ctrl_api.h`와 바이트 같음(헤더 고치지 않음) `[측정: logs_p2a2/api_ca.log]` |
| `gc_unit_livectx` | rdma 1 078 020 검사 0 실패, tcp 0 검사(영역 없음) `[측정: logs_p2a2/unit_ca2.log]` |
| `unit` 전체(rdma, tcp) | rc 0, 모든 시험 0 실패, 기존 시험의 검사 수는 wardfix의 `unit_wf.log`와 같음(gc_unit_live 293 382, gc_unit_p1 10 376 867, gc_unit_ward 165 735 등). 다른 것은 `gc_unit_p2a2` 하나(5 692 → 5 696): 스레드 시간에 따라 수가 달라지는 시험이고 이전 로그에도 5 692, 5 693, 5 697이 있다 `[측정: logs_p2a2/unit_ca2.log, unit_ca.log, 이전 로그]` |
| `gc_unit_livectx.cc` | md5 `e306962d`, 526줄 |
| `build_gc.sh` | md5 `1dedb151`, 992줄 (키 `unitlivectx`, `unitlivectxone`, `unit`, `info`, 사용법 줄; 스크래치 `build_gc_int3.sh`에도 같은 고침, 둘의 차이는 전과 같은 두 곳) |
| 스크래치 트리 commit | `39545f5` "gin-control: progress line of every GIN context (gc_layer_int.diff f4819515)" (ln4 대비 diff `f4819515`, 작업 트리 깨끗). 이 작업의 첫 commit 시도는 git 이름이 없어 실패했고, 그 사이 같은 트리 내용으로 이 commit이 생겼다(제목 끝의 괄호는 이 작업이 붙인 것이 아님) `[측정]` |

빌드와 시험은 스크래치 `agent_gc_p2a2/chain_ca.sh`(head "gin-control: ward QP ERR confirmed before activation", 출력 `*_ca`)로 돌렸다.

## 하지 않은 것, 남은 것

- gcp, gct, gctp 빌드, `pre`, `sites`, `ident`는 돌리지 않았다(요청 범위 밖) `[미확인]`.
- 하드웨어 검증: context 둘 이상인 실행에서 MR 등록(DMA-BUF, peer memory), 페이지의 context 줄, 사슬의 주기 길이,
  `ctx=` 줄은 클러스터에서 보지 않았다 `[미확인]`.
- 상대가 이 rank보다 context가 많으면 이 rank의 개수까지만 읽고 `dev_peer_more`로 센다. 한 communicator의 rank는 같은
  `nContexts`를 쓰므로 나지 않을 것이다 `[추론]`.
- `notes_live.md` 7절의 위험 1(막힌 대기자의 연쇄), 2(거절된 상대 쪽 원소)는 context마다 그대로 남는다 `[추론]`.
