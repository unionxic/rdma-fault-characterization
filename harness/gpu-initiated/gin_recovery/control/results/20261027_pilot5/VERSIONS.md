# gin-control pilot 5: 판과 설정 (2026-10-27)

모든 md5는 이번 세션에서 파일을 다시 읽어 셌다 `[측정]`. 배포 출력은 [deploy.txt](deploy.txt)다.

## 트리

| 무엇 | 값 |
|---|---|
| worktree | `/home/unionxic/rdma-error-wt/gin-control`, HEAD `b8365790` "fix(gin-control): dependent waiters are not judged while their source is unresolved; the source is judged first" |
| worktree의 바뀐 파일 | 없음(추적 파일 수정 0; 실행기, 채점기, 셀 파일 모두 HEAD 판) |
| 스크래치 트리 | `agent_gc_p2a2/nccl-src` HEAD `0b622ed` "gin-control: dependent waiters are not judged while their source is unresolved"(작성자 build), 작업 트리 깨끗함 |
| `f53e5d2` 대비 patience diff | `279b5c90d5bc596f5a60e0742068169b` = `impl/gc_layer_int.diff` (같은 md5) |
| `impl/gc_layer_waitpeer.diff` | `0d30bee6b3d566b0d66ecf008aa83a8a` |
| 호스트 파일 `gin_host_gdaki.cc` (스크래치 트리) | `a4f1be412a6e1f61747e07b555a00ee6` (`impl/notes_waitpeer.md`의 값과 같음) |
| driver 머리 digest (`agent_gc_p2a2/build/include`) | `65fdf19b302d19d593a81886871900ba` (`build_driver_gc.sh info`; pilot 4와 같음) |

## 배포한 것 (묶음 `~/rs-bundle/gc_pilot5/`, 두 노드)

| 파일 | md5 | 출처 |
|---|---|---|
| `lib/gc/libnccl.so.2.32.3` | `54e7ddec95945a655ec87688718378f3` | `agent_gc_p2a2/out/gc_wp2/` (wp2, = `build/lib`; notes_waitpeer.md의 값) |
| `gctest/gin_mi` | `7efe38adfd133356d4158ee9397fe739` | `agent_gc_cx/out/mi_wp2/gin_mi`, 이번에 빌드됨(`build_driver_gc.sh mi`, MIOUT `mi_wp2`, 경고 0). `gin_mi.build.txt`: src `8270cce3`, include `65fdf19b`, lib `54e7ddec` |
| `gctest/gin_launcher` | `d1aceaf68f00d99eafa4d585195f3348` | `lb-fix/gin_launcher` (smoke 6, pilot 1–4와 같음) |

- 두 노드의 새 파일 md5가 서로 같고 원본과 같다. ldd의 libnccl은 묶음의 것이다. 다른 묶음의 기존 파일(rain 985, sunny 1 040)은 바뀌지 않았다 `[측정: deploy.txt]`.
- 아홉 시행의 meta `lib_md5`, `driver_md5`가 위 두 값이고 `rs_set=gc_pilot5`이다 `[측정]`.
- driver를 다시 빌드한 까닭: 지시가 wp2 gc 머리에 맞춰 다시 빌드하라고 했다. 머리 digest는 pilot 4와 같아(`65fdf19b`) 소스와 머리가 같은 빌드이고, 링크한 라이브러리만 다르다(pf2 `39024bef` → wp2 `54e7ddec`). 앞 판 `mi_wd1/gin_mi`는 `8ea4b4500acad7cd9c166c6411ad9602`(쓰지 않음).
- 배포하지 않음(쓰는 셀 없음): `gcp` `bbb7e334ca819797aae353e9bd083b30`, `gct` `7dbbed96e481c53cc17f8cb08a9c3502`(둘 다 `agent_gc_p2a2/out/*_wp2`, 참고로 다시 셈; notes_waitpeer.md와 같음).

## 소스와 실행기

| 파일 | md5 |
|---|---|
| `impl/test/driver/gin_mi.cu` | `8270cce39caa1f4ebe013b89fc23d04f` |
| `impl/test/driver/build_driver_gc.sh` | `410a3531773d7ea5e593734aeb872d28` |
| `impl/launcher/gin_launcher.c` | `5b62a1f5d1fca3ff0f30527e5a70f140` |
| `impl/launcher/launcher_transport_verbs.c` | `1b7b70e73f486663ea8fc0363c6b0157` |
| `impl/test/run_gc.sh` | `5fae8381be720a2f7411d59bf6996361` |
| `impl/test/hold_gc.sh` | `2b09ef876955bcb06a42943f0976fedd` |
| `impl/test/cells_gc.sh` | `3ef72699c7fb1639e8bb3e8704a81b60` |
| `impl/test/chain_gc.sh` | `b79551c45323cac4891006ea689aa015` |
| `impl/test/deploy_gc.sh` | `b3b331efd12333194ddbdf274dad3da7` |
| `impl/test/remote_gc.sh` | `ebc7bd8fda9ce9f07f583bb68dc40b01` |
| `impl/test/launcher_gc.sh` | `919d1874bd20a49952123e3f416a1560` |
| `impl/test/cells_gc.json` | `e3bf87584436034700a1f9d3740cc72b` |
| `impl/test/predictions_gc.csv` | `1ad680672e3ee2e6f5dd52388244de89` |
| `impl/test/rows_gc.py` | `47260fee2df306bccd4e856563bc1872` |
| `impl/test/score_gc.py` | `7b36c065a8f913a19aca04651da05307` |
| `impl/test/test_rows_gc.py` | `c1266d6f54530388566621b356877b21` |
| `impl/test/check_cells_gc.py` | `0a93122c852f183d033b0b93afd506cb` |
| `harness/gpu-initiated/common/cluster_run.sh` (worktree와 `~/rdma-error` 같음) | `a80afb39388645b0c32792e10a0d8515` |

시작 전 확인 `[측정: 로컬 실행]`: `test_rows_gc.py` 233 검사 실패 0, `check_cells_gc.py` drift 0(7절 30행, 셀 28, pilot 전용 행 2, 3절 키 33).

## 셀 env (시행 meta에서 그대로 옮김)

모든 시행에 공통인 값(meta): `lib=gc ctrl=rdma n=4 steps=600 bytes=4096 policy=hold restore=1 mirror=1 overwrite=1 ckpt_steps=20 witness=1 fence=lineage confirm_ms= probe_ms= subject_rank=3 spare=1 spare_rank=3 launcher_scope=trial launcher_env_rain=- launcher_env_sunny=- driver=gin_mi`.

| 시행 | hold | 셀마다 다른 meta 줄 |
|---|---|---|
| `gc4_gpuhang12000_waitpend_fence_gc_n1`, `_n2` (셀 B) | P6 | `waiter_rank=1 hung_ranks=- r1_env=GC_WAITPEND=1 r3_env=GC_GPUHANG_IT=155 watchdog_s=60` |
| `gc4_gpuhang12000_waiter_hung_gc_n1`, `_n2` | P6 | `waiter_rank=1 hung_ranks=3,1 r1_env=GC_GPUHANG_IT=156+GC_GPUHANG_CTX=3 r3_env=GC_GPUHANG_IT=155 watchdog_s=60` |
| `gc4_gpuhang12000_cycle_gc_n1` | P6 | `waiter_rank=1 hung_ranks=- r1_env=GC_WAITPEND=1 r3_env=GC_GPUHANG_IT=155+GC_GPUHANG_CTX=1 watchdog_s=60` |
| `gc4_gpuhang12000_fence_gc_n1` (대조) | P6 | `waiter_rank=- r3_env=GC_GPUHANG_IT=155 watchdog_s=200` |
| `gc4_quiet12000_gc_n1` | P6 | `waiter_rank=- r3_env=GC_QUIET_IT=155@12000 watchdog_s=200` |
| `gc4_kill3_ow_gc_n1` | PCELL-gc4_kill3_ow+gc4_stop12000_fence | `kill_rank=3 kill_kind=traffic kill_at_step=100 kill_delay_us=500 watchdog_s=200` |
| `gc4_stop12000_fence_gc_n1` | PCELL-gc4_kill3_ow+gc4_stop12000_fence | `stop_rank=3 stop_ms=12000 watchdog_s=200` |

(meta는 env 값 안의 빈칸을 `+`로 적는다. 비어 있는 `r0_env`, `r2_env`, `spare_env`는 줄였다.)

- kv 확인 `[측정]`: 셀 B rank 1 `waitpend=1 waitpend_marker=nonzero`, rank 3 `gpuhang_it=155 gpuhang_ctx=all`; waiter-hung rank 1 `gpuhang_it=156 gpuhang_ctx=3 gpuhang_seen=1`, rank 3 `gpuhang_it=155 gpuhang_ctx=all`; 고리 rank 3 `gpuhang_it=155 gpuhang_ctx=1`(줄 `GINRS gpuhang rank=3 step=155 spin=1 ctx=1`), rank 1 `waitpend=1`.

## probe, 확인 창, 정체 설정

- 생존 rank와 예비 프로세스 로그 36개 모두 `status page up (… probe_ms=100 stall_ms=10000 W=20 …)` `[측정: grep]`. meta의 빈 `confirm_ms=`, `probe_ms=`는 라이브러리 기본값이라는 뜻이다.
- 노드 시계: sunny − rain `mono_off_sunny_ms` −1 131 059 120.4 – −1 131 059 119.2 ms, 왕복 0.172–0.191 ms(아홉 시행의 범위) `[측정: meta]`.
