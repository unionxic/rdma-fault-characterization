# gin-control: 생존 낱말을 GPU 진행으로 (사용자 결정 2026-10-22, 작업 기록)

기준: `agent_gc_p2a2/nccl-src`를 `agent_gc_live/nccl-src`로 복사하고 커밋 `acfede7` "gin-control 2a-2-C step 1 (gc_layer_int.diff 3219c376)"을 checkout(작업 트리 깨끗), 빌드 넷은 `agent_gc_p2a2`의 것을 복사하고 경로를 바꿈. 입력과 시험은 worktree 커밋 `886bc62c`(2a-2-C 1단계)의 것을 `agent_gc_live/pin/`에 고정. 스크립트는 `agent_gc_live/build_gc_live.sh`(키 `live`, `build_gc_p2a2.sh`의 int2/p2a2c 단계에 얹음). 호스트 파일 하나, 장치 코드 0줄. 클러스터, ssh, verbs 장치, GPU 실행 없음. 표시: `[측정]` 돌려서 봄, `[추론]` 해석, `[미확인]` 확인 안 함.

## 1. 장치 줄이 무엇인가

gpu-detect가 장치 진행 카운터를 새로 만든 적은 없다(그 계층 `hw_layer.diff`, `hk_layer.diff`는 호스트 파일만 바꿈) `[소스]`. 그래서 새 카운터를 만들지 않고, 이미 있고 GPU가 연산마다 쓰는 낱말을 읽는다.

- 줄: GIN 문맥 0의 장치 QP 배열. DOCA `doca_gpu_verbs_export_multi_qps_dev`가 `nranks x struct doca_gpu_dev_verbs_qp`를 GPU 메모리 하나로, GPU 페이지(64 KiB) 정렬로 잡는다(`doca-gpunetio/src/doca_gpunetio.cpp:1144`, 원소 k = 이 rank가 rank k로 가는 QP, 1162). 호스트에서는 `gin_gdaki_gpu_ctx_host_staging[0].gdqp`(`gin_host_gdaki.cc:34632`의 export 결과).
- 낱말: 원소마다 `sq_rsvd_index`(바이트 0, `doca_gpunetio_verbs_dev.h:174`; GPU가 post마다 atomic add, `doca_gpunetio_dev_verbs_qp.cuh:143`)와 `cq_sq.cqe_ci`(바이트 184, 같은 파일 160; GPU가 poll마다 atomic max, `doca_gpunetio_dev_verbs_cq.cuh:179`, 274). 둘은 같은 WQE 번호 공간이다: [cqe_ci, sq_rsvd_index)가 post됐고 GPU poll이 아직 끝을 보지 못한 창이다(gpu-detect QP 감시가 같은 창을 읽음, `gin_host_gdaki.cc:14015`). 원소 크기 296 B(`sizeof`, 64의 배수가 아님; 낱말은 모두 8 B 정렬) `[측정: 컴파일한 sizeof와 offsetof]`.
- 판정에 쓰는 값: 원소 전체의 post 합, poll 합, 남은 일(원소마다 max(0, post − poll)의 합). post나 poll 합이 바뀌면 GPU가 움직였고, 남은 일이 0이면 GPU가 "조용함"(보낼 것이 없는 계산 구간, 커널 끝, 첫 커널 전)이다. 조용한 줄은 멈춤으로 세지 않는다(코디네이터 정정: "보내지 않는 긴 계산 구간"과 "멈춘 GPU"를 가름).
- 투명 복구의 다시 내기(호스트가 `sq_rsvd_index`를 0으로 다시 씀, 3066, 3087)는 값의 바뀜이라 진행으로 친다.

## 2. MR 등록, all-gather 칸, 페이지 낱말

- 등록: `gdakiCtrlDevSetup`(`gin_host_gdaki.cc:20390`), setup all-gather 앞(`gdakiTsSetup`의 `#if !NCCL_GIN_CTRL_TCP` 칸, 28300). GIN PD(`collComm->ib.pd`, 페이지 MR과 생존 READ QP와 같은 PD)에 `gdakiRegMr(..., IBV_ACCESS_REMOTE_READ, strict)`로: GIN 창과 같은 길(DMA-BUF, 안 되면 peer memory), iova 0. 그래서 줄의 원격 주소는 0이다. 실패하면 WARN 한 줄, 이 rank는 줄 없음(읽는 쪽은 호스트 박동으로 되돌아감).
- BAR1 `[추론]`: 배열 하나가 GPU 페이지 하나(4 rank 1 184 B, 221 rank까지 64 KiB 한 장). NIC 복사 길(gin-remaining)이 같은 할당을 자기 PD에 이미 등록했다. 두 번째 등록이 BAR1을 더 쓰는지(peer memory는 등록마다, DMA-BUF는 붙임마다) `[미확인]`. 256 MiB인 rain에서 64 KiB라 문제 크기는 아니다 `[추론]`.
- all-gather 칸: `gdakiCtrlSetupAddr::dev`(`struct gdakiCtrlRegion`, 바이트 152; 전의 `rsv[4]` 자리라 168 B와 다른 칸 자리는 그대로). 엄격 비교 아님(예비 프로세스의 것은 자기 것). 받은 쪽은 `gdakiCtrlDevAgTake`(20416, 28340)로 rank마다 보관.
- 페이지 낱말: 줄 0의 `rsv`(바이트 56)를 `devLine` = (rkey << 32) | bytes로(0: 줄 없음). 페이지가 서기 전에 한 번 쓰고 바꾸지 않는다. 페이지 배치(`gdakiCtrlPageLayoutOf`)와 크기(4 rank, launcher 2: 320 B)는 그대로다.
- 왜 둘 다인가: all-gather는 setup 때 한 번뿐이라 되살린 화신(예비 프로세스)의 새 MR은 생존 rank에 닿지 않는다. 페이지는 PAIR가 이미 싣고(그 rank의 프로세스 것), READ한 페이지의 `incNonce`가 맞을 때 그 페이지가 이름 댄 줄만 읽는다. all-gather 값은 교차 확인(다르면 `dev_ag_diff` 하나와 줄 하나)이다. 이렇게 하면 낡은 rkey로 READ해 원격 접근 오류(16행, 다시 짝 맺기)를 부르는 일이 없다. PAIR 몸통(ring 영역, 144 B 꽉 참)과 REJOIN은 고치지 않았다.

## 3. READ 둘 probe와 SQ 한도

- 주기마다 짝: 페이지 READ(`PW_PERIODIC`, 전처럼 layout.bytes) 뒤에 줄 READ(`PW_DEV`=4, 같은 순번, 원격 주소 0, 그 페이지가 준 rkey, n x 296 B). 한 걸음에 둘을 post하고, 둘 다 끝나야 판정하고 다음 짝을 낸다(`gdakiCtrlProbeIo::periodicLeft`, `gdakiCtrlProbeIsPeriodic`). 짝의 첫 오류 분류가 그 주기의 `lastCls`다(다음은 flush). 줄이 없는 상대와 짝 맺기 뒤 첫 주기(줄을 아직 모름)는 페이지 READ 하나다.
- 한도: 짝 2 + 확인 창 2 = `GDAKI_CTRL_PROBE_SQ` 4. 값은 그대로이고 뜻이 바뀌었다(전에는 1 + 2 + 여유 1). `gdakiCtrlProbePeriodicDue`가 `need`(2 또는 1)와 창이 남긴 자리를 함께 본다. 모형이 "동시에 4 이하, 짝은 2 이하"를 단언한다. QP의 `max_rd_atomic` 1이라 둘은 차례로 나간다 `[소스]`.
- 받는 쪽 버퍼: 상대마다 줄 칸 셋(주기, 창 READ1, READ2), 각 n x 296 B를 64 B로 올림, READ 버퍼 MR 안. 4 rank면 상대마다 3 648 B `[추론: 셈]`.
- 비용 `[추론: 셈]`: 4 rank에서 rank마다 주기당 (320 + 1 184) B x 3 상대 x 초당 10번 ≈ 45 KB/s(전에는 9.6 KB/s). 줄 크기가 n에 비례해 rank 112면 상대마다 33 KB, 받는 쪽 버퍼 11 MB가 된다. 큰 n에서는 원소마다 낱말 둘만 읽는 방법이 필요하다(이 단계 범위 밖).

## 4. 판정 표의 행이 읽는 입력 (표 21행과 1 170점은 그대로)

R 값을 고르는 순수 함수 `gdakiCtrlRDerive`(20126, `if (f.devMode)` 20133). 상대 페이지가 줄을 이름 대면(devMode):

| R 값 | 읽는 입력 | 행 |
|---|---|---|
| (10)–(12), (13)의 READ 사실 | 짝 READ 둘의 완료와 시한(페이지 READ와 줄 READ 어느 쪽 오류든) | 12, 16, 17, 13, 10, 11 |
| (13) 줄 아직 못 읽음 | 이 QP 세대에 줄 READ 성공 없음 | 13 |
| (2)–(5) 정체 | **장치 줄**(GPU 멈춤 시계, `gdakiCtrlDevOnRead`): 바뀌지 않고 남은 일이 있는 시간. 분할 막이와 데이터 경로 거부권이 그대로 붙음 | 14(멈춤), 18(의심), 20((2)) |
| (6) helper 바쁨 | 호스트 페이지 `helperBusy` | 19 |
| (7)–(9) helper 정체 | **호스트 박동 둘**: `watchBeat`(감시 스레드, 바쁨 한도로 면제 안 됨)와 `helperBeat`(바쁨 한도 뒤부터). 분할 막이만(거부권 없음) | 15(멈춤), 18(의심) |
| (1) 늚 | 줄이 바뀌었거나 조용함, 그리고 호스트 박동 정상 | 20 |

- 둘이 함께 걸리면 표의 차례대로 더 무거운 쪽: (5) 14행 > (9) 15행 > GPU 의심 (3), (4) > 호스트 의심 (7), (8) > (6). 그래서 호스트가 살고 GPU가 멈추면 14행, GPU가 진행(또는 조용)하고 호스트가 멈추면 15행, 둘 다 멈추면 14행, 둘 다 살면 20행.
- 행의 이름과 반응은 그대로다. 뜻의 범위만: 14행 STALL은 "GPU 멈춤", 15행 STALL_HELPER는 "호스트 멈춤(helper 또는 감시 스레드), GPU는 진행"이 된다.
- 줄이 없는 상대(등록 실패, 줄 이름 없음)는 전과 같다: `watchBeat`가 (2)–(5). 이 경우 GPU 멈춤은 보이지 않는다(시험이 대비로 보임).
- 확인 창(4–9행의 W): 줄을 이 세대에 읽은 상대는 READ1, READ2가 줄을 읽는다(`gdakiCtrlWindow::dev`). 판정은 그대로 `gdakiCtrlConfirmVerdict`이고 "늚"만 "줄이 바뀌었거나 READ2에서 조용함"으로 바꿔 넘긴다. 바뀌지 않고 남은 일이 있으면 STALE(4행). 원격 접근 오류, 끝나지 않은 READ, 판정 시각 max(t_F + W, READ2 + W/2), 늦은 읽는 쪽 규칙은 그대로. 줄이 없거나 아직 못 읽었으면 전처럼 줄 0의 `watchBeat`.
- 페이지 `staleMs[q]`(분할 막이의 재료)는 이 rank가 본 q의 세 정체(GPU 줄, 감시 박동, helper 박동) 가운데 큰 것. k의 보기가 유효한지는 전처럼 k의 감시 박동(그 낱말을 쓰는 쪽)으로 본다.

## 5. 수 (`gc_unit_live.cc`, 524줄, rdma 빌드, 한 실행) `[측정: logs/unit_b.log]`

| 장면 | 결과 |
|---|---|
| 배치 | `devLine` 바이트 56, all-gather `dev` 바이트 152 / 168, 페이지 320 B 그대로 |
| 줄 시계 | 원소 4개의 합과 남은 일; 바쁜 줄이 그대로면 정체 5 000 ms; 바뀜, 읽는 쪽 간격(> 2 x PROBE_MS), 조용한 줄(30 000 ms 내내 0)이 시계를 되돌림; 다시 내기(0으로)는 바뀜 |
| 4 rank, rank 0이 rank 3을 판정(100 ms마다) | GPU 멈춤 + 호스트 삶: 14행 멈춤 뒤 +10 000 ms(15행 없음, 18행 먼저); 호스트 박동 둘 멈춤 + GPU post: 15행 +10 000 ms(14행 없음); helper 박동만: 15행 +10 000 ms; 호스트 멈춤 + GPU 조용: 15행 +10 000 ms; 둘 다 멈춤: 14행 +10 000 ms; 둘 다 삶: 20행만; 25 s 조용한 GPU + 호스트 삶: 20행만; 줄 아직 못 읽음: 13행만; 줄 없는 상대: 감시 박동 멈춤 14행 +10 000 ms, GPU 멈춤은 보이지 않음(20행만) |
| R 직접 | 호스트 멈춤이 GPU 의심을 이김, 둘 다면 GPU, 거부권은 GPU 멈춤만 막음, 막이는 둘 다, 바쁨 한도는 감시 스레드 멈춤을 면제하지 않음, READ 사실이 먼저 |
| READ 둘 모형 | 40 실행 x 60 s: 주기 23 281(그 가운데 READ 하나 5 907), 판정 23 277(각각 마지막 완료 뒤 한 번), 창 4 616(모두 판정), 시한 103; 동시에 많아야 4(SQ 4), 짝은 많아야 2 |
| 줄 위 확인 창(W 20) | 바뀜 살아 있음, 바쁜 줄 그대로 STALE(4행), 조용함 살아 있음(8행), READ2 없음 NORESP, READ1 REMACC, 다른 프로세스 확인 못함; 줄 없는 창은 전처럼 |
| 격자 | 1 170점, 행마다 234 468 117 39 39 39 39 39 39 3 1 5 9 9 9 9 9 36 9 18 0(손 센 수와 같음) |
| 합 | 273 397 검사, 실패 0 (tcp 빌드 0 검사) |

변종 셋으로 시험이 틀린 코드를 잡는지 봤다: 조용한 줄의 되돌림을 끔 → 4 실패, R의 두 입력 차례를 바꿈 → 2 실패, 창의 "바뀜" 변환을 끔 → 2 실패 `[측정: agent_gc_live/tmp/mut/]`.

## 6. 검사 (마지막 트리, `SCR=<세션 스크래치> BR=live GCIMPL=<worktree impl> ./build_gc_live.sh <단계>`, 로그 `agent_gc_live/logs/`)

| 검사 | 결과 | 로그 |
|---|---|---|
| `api` | 블록 둘이 고친 헤더(`pin/rs_ctrl_api.h` `789e5425`)와 바이트 같음, launcher wire 같음, 헤더 단독 컴파일 rdma와 tcp, `TCP_CELLS` 단독 거절 | `api_a.log` |
| `syn` | build, build-gcp, build-gct 통과 | `syn_a.log` |
| 빌드 넷 | 빌드됨, 경고 0, 다시 컴파일은 호스트 파일(와 git_version)뿐. libnccl gc `d2741392`, gcp `f6cc032f`, gct `1558abd4`, gctp `41cc4398` | `build_*_a.log` |
| `pre` | gct 0 hunk, gctp 0 hunk, gctc 2 hunk 3줄(RST 간격, 그대로), gc 100 hunk(새 코드, 기록용) | `pre_a.log` |
| `sites` | MISMATCH 0, `#if NCCL_GIN_CTRL_TCP` 갈래 44개 ln4 글 그대로, page 영역 1 465 코드 줄 | `sites_a.log` |
| `unit` 두 빌드 | 모두 실패 0: `gc_unit_p1` 10 248 976(전과 같은 수), `gc_unit_live` 273 397, `gc_unit_p2` 3 993 471, `gc_unit_p2b` 11 114, `gc_unit_p2a2` 4 558, `gc_unit_p3` 473, `gate_fenced` 10/10, gin-mirror와 gin-restore 시험 그대로; tcp는 1단계 이후 0 검사 | `unit_b.log` |
| `ident` | 설치 헤더 ln4와 같음, 매크로 없는 프로그램 16/16 SASS와 자원 같음, 장치 객체 207 x 4 빌드 SASS와 바이트 같음, 라이브러리 넷 자원 같음 | `ident_b.log` |
| `diff` | `gc_layer_live.diff` `6a4cbf92`, 730줄, 40 hunk, 호스트 파일 하나(+324/−51), 1단계 커밋 `acfede7` 대비, 거꾸로 적용 확인 | `diff_a.log` |

- 첫 `unit`(`unit_a.log`)은 `gc_unit_p2a2`에서 컴파일이 멈췄다: `build_gc_p2a2.sh`의 p2a2c 자르기 목록에 다른 에이전트의 다음 걸음 몫(`gdakiCtrlRejoinFail`)이 들어 있고 1단계 시험은 그것을 모른다. 이 작업과 무관하다. `build_gc_live.sh`는 `live` 키에서 그 자르기를 빼고 다시 돌렸다(`unit_b.log`).
- 첫 `ident`(`ident_a.log`)는 결과를 다 낸 뒤 실행 중 스크립트를 고친 탓에 bash 구문 오류로 rc 2였다. 새 IDTAG로 다시 돌렸다.
- `pin/`은 worktree 커밋 `886bc62c`의 입력이다(worktree의 `gc_unit_p2a2.cc`는 다른 에이전트가 고치는 중).

## 7. 위험과 미확인

1. **막힌 대기자의 연쇄** `[추론]`. 링처럼 서로 기다리는 커널에서 한 rank의 GPU가 멈추면, 그것을 기다리는 rank도 진행이 멎는다. 기다리기 전에 flush하지 않은 put이 있으면(남은 일 > 0) 그 rank의 줄도 "바쁜데 그대로"라 10 s 뒤 14행이 된다. 호스트는 살아 있으므로 분할 막이는 그 보기를 유효로 쳐서 막지 못한다. 조용함 규칙은 flush한 대기자만 막는다. 멈춤 주입 smoke에서 이 경우가 나는지 먼저 본다.
2. **거절된 상대 쪽 원소** `[추론]`. 죽거나 거절된 상대로 가는 QP의 남은 일이 영영 남으면, 그 뒤 그 rank가 조용한 계산 구간에 들어가도 줄이 "바쁨"이라 10 s 뒤 14행이 될 수 있다. 읽는 쪽이 HELD나 거절된 k의 원소를 빼는 규칙이 다음 몫이다. hold가 복원으로 끝나면 다시 내기가 값을 바꾸므로 그 경우는 진행으로 친다.
3. 문맥 0만 읽는다. application이 다른 GIN 문맥만 쓰면 줄이 늘 조용해 GPU 멈춤을 못 보고 호스트 박동만 남는다(거짓 멈춤 쪽은 아님) `[추론]`.
4. NIC이 PCIe로 GPU 메모리의 8 B 낱말을 한 순간 값으로 읽는지 `[미확인]`(호스트 메모리의 x86 근거와 다름). 합만 쓰고 "바뀜"만 보므로 찢긴 값은 한 번의 거짓 바뀜(정체 시계 되돌림)이 될 뿐이다 `[추론]`.
5. GPU 메모리 MR의 해제 차례(죽는 프로세스에서 줄 READ가 원격 접근 오류인지 응답 없음인지)는 잰 적 없다 `[미확인]`. 창은 원격 접근 오류를 REMACC로 받으므로 판정 규칙은 그대로다.
6. 줄 READ 크기가 n에 비례(§3). 장치에서 한 번도 돌지 않았다 `[미확인]`.

## 8. EXPERIMENT.md에 넣을 문장 (조율 세션용; 이 작업은 EXPERIMENT.md를 고치지 않음)

**9.2절(상태 페이지) 끝에 한 항목**

- **GPU 진행 줄**(2026-10-22 사용자 결정). 생존의 "진행"은 상대 GPU가 직접 쓰는 낱말에서 읽는다. 새 장치 코드 없이, GIN 문맥 0의 장치 QP 배열(rank마다 GPU 메모리 하나, 상대마다 296 B; GPU가 post마다 `sq_rsvd_index`, poll마다 `cq_sq.cqe_ci`를 올림)을 GIN PD에 REMOTE_READ로 등록한다(GIN 창과 같은 DMA-BUF 길, iova 0) `[소스: impl/notes_live.md 1, 2절]`. 그 (rkey, 바이트)는 setup all-gather 칸 `dev`와 페이지 줄 0의 `devLine`(전의 `rsv`)에 실린다. 읽는 쪽은 같은 짝 맺기의 페이지 READ가 이름 댄 줄만 읽는다(되살린 화신의 새 MR도 그렇게 닿음). 줄 READ의 합에서 post와 poll이 바뀌면 진행, [poll, post) 창이 모두 비면 "조용함"(보내지 않는 계산 구간)이라 멈춤으로 세지 않는다. 비용은 4 rank에서 주기당 줄 READ 1 184 B가 더해져 rank마다 약 45 KB/s다 `[추론: 셈]`. BAR1은 배열의 GPU 페이지 하나(64 KiB)다 `[추론]`.

**9.2절 "읽는 쪽" 항목의 첫 문장을 이렇게**

- **읽는 쪽.** 감시 스레드가 gated이고 거절 안 된 상대마다 100 ms마다 READ 짝 하나(페이지, 그다음 GPU 진행 줄)를 띄우고, 둘 다 끝나야 판정하고 다음 짝을 낸다. 확인 창의 READ1, READ2는 GPU 진행 줄을 읽는다(줄이 없는 상대는 줄 0). SQ 4 = 짝 2 + 창 2 `[소스: impl/notes_live.md 3절]`.

**9.3절 입력 R 항목 끝에 한 문장**

- R의 두 진행 입력(2026-10-22 사용자 결정): (2)–(5)의 정체는 GPU 진행 줄(바뀌지 않고 남은 일이 있는 시간; 분할 막이와 데이터 경로 거부권 그대로)이고, (6)–(9)는 호스트 박동 둘(`watchBeat`는 바쁨 한도로 면제되지 않음, `helperBeat`는 바쁨 한도 뒤부터; 막이만)이다. 함께 걸리면 표의 차례대로 무거운 쪽(14행 > 15행 > GPU 의심 > 호스트 의심 > 바쁨). 그래서 14행 STALL은 "GPU 멈춤", 15행 STALL_HELPER는 "호스트 멈춤, GPU는 진행 또는 조용"이다. 줄이 없는 상대는 전처럼 `watchBeat`가 (2)–(5)다 `[소스: impl/notes_live.md 4절]`. CPU 모형에서 네 장면(GPU 멈춤과 호스트 삶 14행, 호스트 멈춤과 GPU 진행 15행, 둘 다 14행, 둘 다 20행)이 모두 멈춤 뒤 10 000 ms에 판정되거나 20행에 머물고, 25 s 조용한 GPU는 20행에 머문다 `[측정: impl/notes_live.md 5절, 한 실행]`.

**9.3절 "확인 창" 항목 끝에 한 문장**

- 줄이 있는 상대의 창은 READ1, READ2가 GPU 진행 줄을 읽고, 줄이 바뀌었거나 READ2에서 조용하면 살아 있음, 바뀌지 않고 남은 일이 있으면 STALE이다. 나머지 규칙(REMACC가 정함, NORESP, 판정 시각, 늦은 읽는 쪽)은 그대로다.

**11절(작업 체크리스트)**

- [x] 생존 낱말을 GPU 진행으로: 문맥 0의 장치 QP 배열을 MR로(장치 코드 0줄), all-gather `dev`와 페이지 `devLine`, 주기 READ 짝과 줄 위 확인 창, R (2)–(5)는 줄, (6)–(9)는 호스트 박동. `impl/gc_layer_live.diff` `6a4cbf92`(1단계 커밋 대비 730줄, 호스트 파일만), `impl/rs_ctrl_api_live.diff`, `impl/gc_unit_live.cc`. 근거 `impl/notes_live.md`.
- [ ] GPU 진행 줄 smoke(2 rank, 주입 없음, 줄 등록 줄과 `dev_ok`), 그다음 멈춤 주입. 막힌 대기자의 연쇄와 거절된 상대 원소(`impl/notes_live.md` 7절 1, 2)를 먼저 본다.

**12절(실행 기록)**

- 2026-10-22, 생존 낱말을 GPU 진행으로(실행 없음, CPU와 빌드만). 2a-2-C 1단계 트리 위에서 호스트 파일만 고쳤다(+324/−51). 네 빌드가 빌드됨, 경고 0 `[측정: logs/build_*_a.log]`. tcp 전처리는 gct, gctp 0 hunk, gctc 2 hunk 그대로 `[측정: pre_a.log]`. 단위 시험은 두 빌드에서 실패 0: `gc_unit_live` 273 397 검사(4 rank 장면 아홉, READ 둘 모형 23 281 주기에서 동시 4 이하와 짝 2 이하, 줄 위 확인 창, 격자 1 170점의 행마다 수 그대로), `gc_unit_p1` 10 248 976 검사(전과 같음) `[측정: unit_b.log, n 1]`. 장치에서는 돌지 않았다 `[미확인]`.

## 파일 (worktree `control/impl/`)

| 파일 | md5 | 내용 |
|---|---|---|
| `gc_layer_live.diff` (730줄) | `6a4cbf9267ecb786b4582cbdcae7df21` | 1단계 커밋 `acfede7` 대비 작업 트리(호스트 파일 `a8df1f8d`, 35 141줄) |
| `rs_ctrl_api_live.diff` (79줄) | `8bdbcdb232bb39e2628a2dbabc7ac2b0` | 헤더: `devLine`과 그 도움 함수, `gdakiCtrlSetupAddr::dev`, `gdakiCtrlState::dev`, R과 SQ 주석 |
| `gc_unit_live.cc` (524줄) | `3217750532e69a12e33e60a8dec7697c` | 위 5절 |
| `notes_live.md` | | 이 문서 |
