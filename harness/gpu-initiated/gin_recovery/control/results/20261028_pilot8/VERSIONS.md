# gin-control pilot 8: 판과 설정 (2026-10-28)

모든 md5는 이번 세션에서 파일을 다시 읽어 셌다 `[측정]`.

## 묶음 (pilot 7과 같음, 다시 배포하지 않음)

`RS_SET=gc_pilot7`, 두 노드의 `~/rs-bundle/gc_pilot7/`을 그대로 썼다. 판의 출처와 빌드는 [../20261028_pilot7/VERSIONS.md](../20261028_pilot7/VERSIONS.md)다.

| 파일 | md5 (rain, sunny 같음) |
|---|---|
| `lib/gc/libnccl.so.2.32.3` | `ed13666bacdf07dcc2e16ef4028561e3` |
| `gctest/gin_mi` | `0565a677eb68b304540e6518f16bd48e` |
| `gctest/gin_launcher` | `d1aceaf68f00d99eafa4d585195f3348` |

- 돌리기 전에 두 노드에서 읽기만 해서 셌다(rain은 로컬, sunny는 ssh) `[측정: md5chk.txt]`. 세 시행의 meta가 모두 `rs_set=gc_pilot7 lib_md5=ed13666b… driver_md5=0565a677…`다 `[측정: a1/raw/*_meta.txt]`.

## 트리

| 무엇 | 값 |
|---|---|
| worktree | `/home/unionxic/rdma-error-wt/gin-control`, 시작 때 HEAD `90c61553` + 커밋 안 된 pilot 7 파일 |
| 실행 뒤 HEAD 바뀜 | 조율 세션이 hold가 끝난 뒤(02:53:51) 02:54:16에 `d6f4cfa4` "exp(gin-control): pilot 7 on the abort-decision library: …"를 커밋했다. 이 세션은 git을 건드리지 않았고 고친 것은 이 폴더뿐이다 |

## 셀 env (`cells_gc.json` `59291a4f`의 그 셀 항목 그대로)

| 셀 | env | 주입 | bound_s |
|---|---|---|--:|
| `gc4_fdhold_uverbs_kill3@gc` | `OVERWRITE=1 MIRROR=1 CKPT_STEPS=20 KILL_RANK=3 SPARE=0 FDHOLD=1 R3_ENV=NCCL_GIN_TS_TEST_FD_HOLDER=uverbs` | `fd_holder_kill` (rank 3이 gin_fdhold를 fork해 증인 소켓과 uverbs fd를 넘긴 뒤 rank 3 SIGKILL) | 60 |
| `gc4_kill3_ow_spareabsent@gc` | `OVERWRITE=1 MIRROR=1 CKPT_STEPS=20 KILL_RANK=3 SPARE=1 KILL_KIND=spare_then_rank SPARE_GAP_MS=5` | `spare_kill_then_kill` (생존 셋이 `armed` 줄을 낸 뒤 예비 SIGKILL, 5 ms 뒤 rank 3 SIGKILL) | 60 |
| `gc4_stop12000_none@gc` | `OVERWRITE=1 MIRROR=1 CKPT_STEPS=20 SPARE=1 STOP_RANK=3 STOP_MS=12000 FENCE=none SPARE_RANK=3` | `sigstop` (rank 3 SIGSTOP, 12 000 ms 뒤 SIGCONT) | 60 |

## 실행기와 채점기 (바꾸지 않음)

| 파일 | md5 |
|---|---|
| `impl/test/hold_gc.sh` | `1113382149995f6d6ce8a5b734395c1a` (pilot 7에서 고친 판) |
| `impl/test/chain_gc.sh` | `b79551c45323cac4891006ea689aa015` |
| `impl/test/run_gc.sh` | `5fae8381be720a2f7411d59bf6996361` |
| `impl/test/cells_gc.json` | `59291a4fd2109141de28a6c3b093fec3` |
| `impl/test/predictions_gc.csv` | `da1a5c45fdfe7c5ee81c45f18ca7b001` |
| `impl/test/rows_gc.py` | `9b9035f391879fb49ff1402ccc742678` |
| `impl/test/score_gc.py` | `7b36c065a8f913a19aca04651da05307` |
| `harness/gpu-initiated/common/cluster_run.sh` | `a80afb39388645b0c32792e10a0d8515` |

모두 pilot 7 VERSIONS.md의 값과 같다.
