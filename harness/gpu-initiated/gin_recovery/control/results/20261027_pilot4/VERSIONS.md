# gin-control pilot 4: 판과 설정 (2026-10-27)

모든 md5는 이번 세션에서 파일을 다시 읽어 셌다 `[측정]`. 배포 출력은 [deploy.txt](deploy.txt)다.

## 트리

| 무엇 | 값 |
|---|---|
| worktree | `/home/unionxic/rdma-error-wt/gin-control`, HEAD `1f3e8ebf` "exp(gin-control): counterexample cells under the current rule …" |
| worktree의 바뀐 파일 | `impl/test/hold_gc.sh` 하나(+14줄, 실행기 고침; [PILOT.md](PILOT.md) "실행기 고침"). 시도 1은 HEAD 판(`ad86e5bc`), 시도 2는 고친 판(`d7c3c02c`)으로 돌았다 |
| 스크래치 트리 | `agent_gc_p2a2/nccl-src` HEAD `d5aec6e` "gin-control: pilot 2 fixes: two-death REJOIN …", 작업 트리 깨끗함 |
| `f53e5d2` 대비 patience diff | `7a3fbd6672d0de1b69df16f7e20c3fe2` = `impl/gc_layer_int.diff` (같은 md5) |
| driver 머리 digest (`agent_gc_p2a2/build/include`) | `65fdf19b302d19d593a81886871900ba` (`build_driver_gc.sh info`; pilot 3과 같음) |

## 배포한 것 (묶음 `~/rs-bundle/gc_pilot4/`, 두 노드)

| 파일 | md5 | 출처 |
|---|---|---|
| `lib/gc/libnccl.so.2.32.3` | `39024befe7760f00f6a8bf761f28cc5a` | `agent_gc_p2a2/out/gc_pf2/` (pf2, = `build/lib`) |
| `gctest/gin_mi` | `5bd02b276bfb658336c1638f4dd26695` | `agent_gc_cx/out/mi_cx2/gin_mi` (빌드됨 2026-10-27, 다시 빌드하지 않음; `gin_mi.build.txt`: src `a28df3fe`, include `65fdf19b`, lib `39024bef`) |
| `gctest/gin_launcher` | `d1aceaf68f00d99eafa4d585195f3348` | `lb-fix/gin_launcher` (smoke 6, pilot 1–3과 같음) |

- 두 노드의 새 파일 md5가 서로 같고 원본과 같다. ldd의 libnccl은 묶음의 것이다. 다른 묶음의 기존 파일(rain 980, sunny 1 035)은 바뀌지 않았다 `[측정: deploy.txt]`.
- 다섯 시행의 meta `lib_md5`, `driver_md5`가 위 두 값이고 `rs_set=gc_pilot4`이다 `[측정]`.
- 배포하지 않음(쓰는 셀 없음): `gcp` `1b2f741a2f8f548297d953c0d42b790d`, `gct` `54f680e226e9a557533215e1599ab0c3`(둘 다 `agent_gc_p2a2/out/*_pf2`, 참고로만 다시 셈).

## 소스와 실행기

| 파일 | md5 |
|---|---|
| `impl/test/driver/gin_mi.cu` | `a28df3feb4172230b9304099f2c83625` |
| `impl/launcher/gin_launcher.c` | `5b62a1f5d1fca3ff0f30527e5a70f140` |
| `impl/launcher/launcher_transport_verbs.c` | `1b7b70e73f486663ea8fc0363c6b0157` |
| `impl/test/run_gc.sh` | `71a0409ef00d5411ac940432d77f5b04` |
| `impl/test/hold_gc.sh` | HEAD `ad86e5bc44864d46d03c8ca1c6b038a7`, 고친 판 `d7c3c02c9ce6b04164044d827d59be0c` |
| `impl/test/cells_gc.sh` | `3ef72699c7fb1639e8bb3e8704a81b60` |
| `impl/test/chain_gc.sh` | `b79551c45323cac4891006ea689aa015` |
| `impl/test/deploy_gc.sh` | `b3b331efd12333194ddbdf274dad3da7` |
| `impl/test/cells_gc.json` | `c7a5b744b5c99a5df3232627ebe993c4` |
| `impl/test/predictions_gc.csv` | `1ad680672e3ee2e6f5dd52388244de89` |
| `impl/test/rows_gc.py` | `9e003d37d328856463b812b49ead2c50` |
| `impl/test/score_gc.py` | `f826456f82ce8874accb34a677f4f684` |
| `impl/test/test_rows_gc.py` | `6d7d32c34964ec3001a35844598f384b` |

시작 전 확인 `[측정: 로컬 실행]`: `test_rows_gc.py` 221 검사 실패 0, `check_cells_gc.py` drift 0(7절 30행, 셀 28, 3절 키 33). 채점기 셋은 HEAD 그대로이고 이번에 고치지 않았다.

## 셀 env (시행 meta에서 그대로 옮김)

모든 시행에 공통인 값(meta): `lib=gc ctrl=rdma n=4 steps=600 bytes=4096 policy=hold restore=1 overwrite=1 mirror=1 ckpt_steps=20 witness=1 fence=lineage confirm_ms= probe_ms= spare=1 spare_rank=3 subject_rank=3 launcher_scope=trial launcher_env_rain=- launcher_env_sunny=- watchdog_s=200 driver=gin_mi`.

| 시행 | hold | 셀마다 다른 meta 줄 |
|---|---|---|
| `gc4_quiet12000_gc_n1` | P5 | `waiter_rank=- r0_env= r1_env= r2_env= r3_env=GC_QUIET_IT=155@12000 spare_env=` |
| `gc4_quiet12000_gc_n2` | P5 | `waiter_rank=- r0_env= r1_env= r2_env= r3_env=GC_QUIET_IT=155@12000 spare_env=` |
| `gc4_gpuhang12000_waitpend_fence_gc_n1` | P5 | `waiter_rank=1 r0_env= r1_env=GC_WAITPEND=1 r2_env= r3_env=GC_GPUHANG_IT=155 spare_env=` |
| `gc4_gpuhang12000_waitpend_fence_gc_n2` | P5-r2 | `waiter_rank=1 r0_env= r1_env=GC_WAITPEND=1 r2_env= r3_env=GC_GPUHANG_IT=155 spare_env=` |
| `gc4_gpuhang12000_fence_gc_n1` (대조) | PCELL-gc4_gpuhang12000_fence | `waiter_rank=- r0_env= r1_env= r2_env= r3_env=GC_GPUHANG_IT=155 spare_env=` |

- kv 확인 `[측정]`: 셀 A rank 3 `quiet_it=155 quiet_ms=12000`, 셀 B rank 1 `waitpend=1 waitpend_marker=nonzero`, rank 3 `gpuhang_it=155 gpuhang_ctx=all`; 대조 시행은 네 rank 모두 `waitpend=0`.

## probe, 확인 창, 정체 설정

- 생존 rank 로그 20개 모두 `status page up (… probe_ms=100 stall_ms=10000 W=20 …)` `[측정: grep]`. meta의 `confirm_ms=`, `probe_ms=`가 빈 것은 셀이 정하지 않아 라이브러리 기본값이라는 뜻이다.
- `cells_gc.json` `prereg`: `confirm_ms` 20, `probe_ms` 100, `live_bound_ms` 10000, `launcher_stall_ms` 1000, `stop_len_tol_ms` 50, `pair_gap_limit_ms` 10, `query_qp_per_s` 4000 `[소스]`.
- 노드 시계: sunny − rain `mono_off_sunny_ms` −1 131 059 108.1 – −1 131 059 109.8 ms, 왕복 0.172–0.186 ms(다섯 시행의 범위) `[측정: meta]`.
