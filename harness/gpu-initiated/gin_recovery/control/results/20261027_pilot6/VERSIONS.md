# gin-control pilot 6: 판과 설정 (2026-10-27)

pilot 5의 묶음을 다시 빌드하거나 다시 배포하지 않고 그대로 썼다. md5는 모두 이번 세션에서 파일을 다시 읽어 셌다 `[측정]`.

## 트리

| 무엇 | 값 |
|---|---|
| worktree | `/home/unionxic/rdma-error-wt/gin-control`, 시작 때 HEAD `b8365790`(pilot 5와 같음). 실행 중 다른 세션이 pilot 5 커밋 `5d84e62c`를 올렸다(`impl/` 아래 바뀐 줄 0) |
| 실행 뒤 worktree의 남의 수정 | 14:44–14:46에 `rows_gc.py`, `predictions_gc.csv`, `test_rows_gc.py`가 커밋 없이 바뀌었다(이 세션이 고친 것 아님; hold는 14:43:30에 끝남). 그래서 시행 표를 `git archive HEAD` 사본(`rows_gc.py` `47260fee`)에서 다시 셌고 앞의 표와 열 하나도 다르지 않았다 `[측정]` |
| 실행기, 채점기, 셀 파일 | pilot 5 [VERSIONS.md](../20261027_pilot5/VERSIONS.md) "소스와 실행기" 표의 md5와 모두 같다: `gin_mi.cu` `8270cce3`, `run_gc.sh` `5fae8381`, `hold_gc.sh` `2b09ef87`, `cells_gc.sh` `3ef72699`, `chain_gc.sh` `b79551c4`, `remote_gc.sh` `ebc7bd8f`, `launcher_gc.sh` `919d1874`, `cells_gc.json` `e3bf8758`, `predictions_gc.csv` `1ad68067`, `rows_gc.py` `47260fee`, `score_gc.py` `7b36c065`, `gin_launcher.c` `5b62a1f5`, `cluster_run.sh` `a80afb39`(worktree와 `~/rdma-error` 같음) |
| 고친 파일 | 없음(라이브러리, 실행기, 채점기, 셀 파일 0줄) |

## 묶음 `~/rs-bundle/gc_pilot5/` (두 노드, 시작 전 md5 확인)

| 파일 | rain | sunny | pilot 5 VERSIONS.md |
|---|---|---|---|
| `lib/gc/libnccl.so.2.32.3` (wp2 gc) | `54e7ddec95945a655ec87688718378f3` | 같음 | 같음 |
| `gctest/gin_mi` | `7efe38adfd133356d4158ee9397fe739` | 같음 | 같음 |
| `gctest/gin_launcher` | `d1aceaf68f00d99eafa4d585195f3348` | 같음 | 같음 |

- 두 노드 모두 `libnccl.so -> libnccl.so.2 -> libnccl.so.2.32.3` 링크, 크기 143 425 976 B `[측정]`.
- 세 시행의 meta가 `rs_set=gc_pilot5 lib_md5=54e7ddec… driver_md5=7efe38ad…`다 `[측정]`.
- `gcp` `bbb7e334`, `gct` `7dbbed96`은 쓰는 셀이 없어 쓰지 않았다(묶음에도 없음).

## 셀 env (meta에서)

공통: `lib=gc ctrl=rdma n=4 policy=hold restore=1 mirror=1 overwrite=1 ckpt_steps=20 witness=1 fence=lineage kill_rank=2 kill2_rank=3 kill_kind=driver inject=kill_driver die_seed=gin-mirror-v1 spare=1 spare2=1 launcher_scope=trial watchdog_s=200`, 빈 `confirm_ms=`, `probe_ms=`(라이브러리 기본 probe_ms=100 stall_ms=10000 W=20).

| 시행 | steps, bytes | qpwatch_ms | die_at (첫 kill: 걸음:µs) | die2_at (둘째 kill) | spare_wait_ms |
|---|---|--:|---|---|--:|
| `mi4_kill2_kill3_ow_gc_n1` | 600, 4 096 | 10 | 205:1941 | 396:151 | 60 000 |
| `mi4_kill2_kill3_ow_gc_n2` | 600, 4 096 | 10 | 189:2908 | 397:2391 | 60 000 |
| `mi4_train_kill2_kill3_gc_n1` | 2 000, 2 097 152 | 50 | 552:348 | 1113:4619 | 120 000 |

- kill 위치는 `DIE_SEED`에서 시행 번호마다 정해지므로 pilot 3의 같은 시행 번호(n1, n2, 학습 n1)와 한 자리도 다르지 않다 `[측정: pilot 3 a2/raw/*_meta.txt]`. 그래서 이 pilot은 같은 kill 위치에서 라이브러리만 바꾼(pf2 `39024bef` → wp2 `54e7ddec`) 대조다.
- 노드 시계: sunny − rain `mono_off` −1 131 059 123.0 – −1 131 059 123.3 ms, 왕복 0.173–0.192 ms(세 시행의 범위) `[측정: meta]`.
