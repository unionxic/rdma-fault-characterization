# gin-control pilot 7: 판과 설정 (2026-10-28)

모든 md5는 이번 세션에서 파일을 다시 읽어 셌다 `[측정]`. 배포 출력은 [deploy.txt](deploy.txt)다.

## 트리

| 무엇 | 값 |
|---|---|
| worktree | `/home/unionxic/rdma-error-wt/gin-control`, HEAD `1ad05eb8` "docs(gin-control): record the abort-propagation and per-element-veto design review: …" |
| 실행 중 HEAD 바뀜 | 조율 세션이 piece ① 파일을 `90c61553` "fix(gin-control): confirmed abort decisions reach every peer and later incarnations, …"로 커밋했다(실행 뒤 확인; `gc_layer_int.diff` md5 그대로 `3ae8f572`). 이 세션이 고친 것은 `hold_gc.sh`, `notes_test.md`, 이 폴더뿐이다 |
| 시작 때 worktree의 커밋 안 된 piece ① 파일(조율 세션 몫, 이 세션은 읽기만) | `impl/gc_layer_int.diff` `3ae8f572e991c32f60878cb740ef5e3e`, `impl/gc_layer_abortdec.diff` `87edebb14c344068a7e99e546ad5f12f`, `impl/gc_unit_abortdec.cc` `729005da06ffe5087f4ef397539295e2`, `impl/build_gc.sh` `a925784e1d62d5db6ed17e9013b3c701`, `impl/gc_sites.tsv` `1f863729894b5e437c923e2dea52ca7f`, `impl/notes_abortdec.md` |
| 스크래치 트리 | `agent_gc_p2a2/nccl-src` HEAD `05f5a97` "gin-control: confirmed abort decisions reach peers and later incarnations"(작성자 build), 작업 트리 깨끗함(`git status --porcelain` 0줄) |
| `f53e5d2` 대비 patience diff | `3ae8f572e991c32f60878cb740ef5e3e` = `impl/gc_layer_int.diff` |
| `0b622ed`..HEAD patience diff | `87edebb14c344068a7e99e546ad5f12f` = `impl/gc_layer_abortdec.diff` |
| 호스트 파일 `src/transport/net_ib/gdaki/gin_host_gdaki.cc` | `5f03db2ce947e9fbe2045fb6774f1618` (notes_abortdec.md의 값과 같음) |
| driver 머리 digest (`agent_gc_p2a2/build/include`) | `65fdf19b302d19d593a81886871900ba` (`build_driver_gc.sh info`; pilot 2, 4, 5와 같음. piece ①은 호스트 파일만 바꿈) |

## 라이브러리 (piece ① `ad` 사슬의 출력, 다시 빌드하지 않음)

| 무엇 | md5 | 경로 |
|---|---|---|
| libnccl `gc` | `ed13666bacdf07dcc2e16ef4028561e3` | `agent_gc_p2a2/out/gc_ad/` (= `build/lib`) |
| libnccl `gcp` | `55ffb80e1ac74e58b05666fbd08176e8` | `agent_gc_p2a2/out/gcp_ad/` (= `build-gcp/lib`) |
| libnccl `gct` | `df1d091bb8ba6ec391604e4933c9c56d` | `agent_gc_p2a2/out/gct_ad/` |

세 값 모두 notes_abortdec.md 표와 같다.

## driver (이번에 빌드됨, `build_driver_gc.sh` `3cf014a5`, `OUTROOT=agent_gc_cx/out MIOUT=mi_ad`)

rain에서 nvcc(nice 19, idle I/O), 경고 0(빌드 로그가 md5 줄뿐). 머리 digest는 넷 모두 `65fdf19b`.

| driver | md5 | 소스 | 링크한 라이브러리 |
|---|---|---|---|
| `mi_ad/gin_mi` (macro=1) | `0565a677eb68b304540e6518f16bd48e` | `gin_mi.cu` `8270cce39caa1f4ebe013b89fc23d04f` | gc `ed13666b` |
| `mi_ad/gin_mi_nomacro` (macro=0) | `e8530bcc33920690191f86afec6dd3e6` | `gin_mi.cu` `8270cce3` | gc `ed13666b` |
| `mi_ad/mr/ff/gin_mr` (macro=0) | `ac1a419b9c5995e92397c0d12f5aadb4` | `remaining/gin_mr.cu` `a6a526ad3df1b853efd48d53a0a11ca7` | gc `ed13666b` |
| `mi_ad/mr/hold/gin_mr` (macro=1) | `23b33c94be24c718b4af70d0569c7dfe` | 같음 | gc `ed13666b` |
| `mi_ad/gin_ts2_mi` (macro=1) | `2bf3b36aef636ddf2b91682a905f596a` | `gin_ts2.cu` `1779db9d` + winflags `fb9d2d8d` + mi `0e5aef6c`(패치된 것 `a26bec9c`) | gcp `55ffb80e` |

빌드 줄은 같은 폴더의 `*.build.txt`. 본 실행 driver 묶음(notes_test.md "본 실행 driver 빌드", `mi_wp2`)과 소스, 머리가 같고 라이브러리만 다르다(wp2 → ad).
이 pilot의 셀은 `gin_mi`만 쓴다.

## 배포한 것 (묶음 `~/rs-bundle/gc_pilot7/`, 두 노드)

| 파일 | md5 | 출처 |
|---|---|---|
| `lib/gc/libnccl.so.2.32.3` | `ed13666bacdf07dcc2e16ef4028561e3` | `agent_gc_p2a2/out/gc_ad/` |
| `gctest/gin_mi` | `0565a677eb68b304540e6518f16bd48e` | `agent_gc_cx/out/mi_ad/gin_mi` |
| `gctest/gin_launcher` | `d1aceaf68f00d99eafa4d585195f3348` | `lb-fix/gin_launcher` (pilot 1–6과 같음) |

- 두 노드의 새 파일 md5가 서로 같고 원본과 같다. ldd의 libnccl은 묶음의 것이다. 다른 묶음의 기존 파일(rain 990, sunny 1 045)은 바뀌지 않았다 `[측정: deploy.txt]`.
- 배포하지 않음(쓰는 셀 없음): `gcp`, `gct`, `gin_mi_nomacro`, `gin_mr`, `gin_ts2_mi`.

- 아홉 시행의 meta가 `rs_set=gc_pilot7 lib_md5=ed13666b… driver_md5=0565a677…`다 `[측정]`.

## 셀 env와 설정

셀 env는 `cells_gc.json`(`59291a4f`)의 그 셀 항목 그대로이고 pilot 5 [VERSIONS.md](../20261027_pilot5/VERSIONS.md) "셀 env" 표와 같다(`gc4_gpuhang12000_ctx1_fence`는 `R3_ENV=GC_GPUHANG_IT=155 GC_GPUHANG_CTX=1`, `bound_s` 60).
`mi4_kill2_kill3_ow@gc`는 `PRC-gc-` 꼴의 회귀 hold 항목이고 시행 번호 n1이라 kill 위치가 pilot 3, 6의 n1과 같다(`DIE_SEED`).

- 생존 rank와 예비 프로세스 로그 55개 모두 한 줄씩 `status page up (… probe_ms=100 stall_ms=10000 W=20 …)` `[측정: grep]`.
- 노드 시계: sunny − rain `mono_off_sunny_ms` −1 131 059 103.291 – −1 131 059 102.734 ms, 왕복 0.170–0.198 ms(아홉 시행의 범위) `[측정: meta]`.

## 소스와 실행기

| 파일 | md5 |
|---|---|
| `impl/test/driver/gin_mi.cu` | `8270cce39caa1f4ebe013b89fc23d04f` |
| `impl/test/driver/build_driver_gc.sh` | `3cf014a5f03281ba3f0457e7cb8f190d` |
| `impl/launcher/gin_launcher.c` | `5b62a1f5d1fca3ff0f30527e5a70f140` |
| `impl/launcher/launcher_transport_verbs.c` | `1b7b70e73f486663ea8fc0363c6b0157` |
| `impl/test/run_gc.sh` | `5fae8381be720a2f7411d59bf6996361` |
| `impl/test/hold_gc.sh` | `1113382149995f6d6ce8a5b734395c1a` (이번에 고침: 앞 판 `2b09ef87`; 아래) |
| `impl/test/cells_gc.sh` | `3ef72699c7fb1639e8bb3e8704a81b60` |
| `impl/test/chain_gc.sh` | `b79551c45323cac4891006ea689aa015` |
| `impl/test/deploy_gc.sh` | `b3b331efd12333194ddbdf274dad3da7` |
| `impl/test/remote_gc.sh` | `ebc7bd8fda9ce9f07f583bb68dc40b01` |
| `impl/test/launcher_gc.sh` | `919d1874bd20a49952123e3f416a1560` |
| `impl/test/cells_gc.json` | `59291a4fd2109141de28a6c3b093fec3` |
| `impl/test/predictions_gc.csv` | `da1a5c45fdfe7c5ee81c45f18ca7b001` |
| `impl/test/rows_gc.py` | `9b9035f391879fb49ff1402ccc742678` |
| `impl/test/score_gc.py` | `7b36c065a8f913a19aca04651da05307` |
| `impl/test/test_rows_gc.py` | `8207dc5e146698c06efd196d6ab4308e` |
| `impl/test/check_cells_gc.py` | `0a93122c852f183d033b0b93afd506cb` |
| `harness/gpu-initiated/common/cluster_run.sh` (worktree와 `~/rdma-error` 같음) | `a80afb39388645b0c32792e10a0d8515` |

- **`hold_gc.sh` 고침(실행기, +5줄).** `PCELL-` 꼴이 같은 셀 이름을 여러 번 받으면 그 수만큼 시행(n1..nk)을 돌린다(`PRC-`와 같은 규칙). 전에는 이름마다 n 1이라 두 번째가 `_n1` meta로 건너뛰어졌다 `[소스]`.
  기다리는 rank도 멈춘 셀을 한 hold에서 두 번 돌리려고 고쳤다. 확인: `bash -n`, `json_hold`만 떼어 돌려 이번 hold 셋의 셀 줄과 n을 봄(waiter_hung n 2, 나머지 n 1), pilot 5의 `PCELL-gc4_kill3_ow+gc4_stop12000_fence`는 전과 같은 줄 `[측정: 로컬 실행]`.
