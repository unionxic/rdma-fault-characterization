# gin-control pilot 1 (2026-10-23, 채점 안 함)

pilot hold P0–P4, tcp 회귀 대조 `mi4_kill3_ow@gct` 한 번(새 pilot hold `PRG-gct-G1`), 비용 pilot 두 노드를 셀마다 n 1로 돌렸다. pilot은 본 실험에 들지 않고 채점하지 않는다.
아래 "규칙" 열은 `score_gc.py`를 세션 스크래치 사본에서 pilot 표시를 끄고 계획 n을 1로 둔 채 돌린 결과다. 판정이 아니라, 예측의 시행 조건이 이 시행 하나에서 참인지만 본 것이다.
표시: `[측정]` 원자료에서 다시 셈, `[소스]` 코드를 읽음, `[추론]` 해석, `[미확인]` 확인 안 함. 시각은 모두 `rows_gc.py`가 원자료에서 다시 셈한 값이다.

## 고침과 빌드 (맨 먼저)

- **멈춤과 고침.** 첫 빌드(트리 HEAD `39545f5`)에서 `gct`의 호스트 파일 전처리 결과가 ln4와 1 hunk, 6줄 달랐다.
  - 원인 `[소스]`: ctxall이 더한 `gdakiMiUserCtxOf`의 정의가 `#if !NCCL_GIN_CTRL_TCP` 밖에 있었다.
  - 조율 세션의 승인으로 그 정의 앞뒤에 `#if !NCCL_GIN_CTRL_TCP`/`#endif` 두 줄을 넣었다. 스크래치 트리 커밋은 `725254b`다.
  - 고침 diff는 [../../impl/gc_layer_pilot1fix.diff](../../impl/gc_layer_pilot1fix.diff)(`ac764734`)다.
  - [../../impl/gc_layer_int.diff](../../impl/gc_layer_int.diff)는 ln4 `f53e5d2` 대비 patience diff로 다시 냈다: `f4819515` → `1b0a40c8`.
  - 설명과 검사 출력은 [../../impl/notes_pilot1fix.md](../../impl/notes_pilot1fix.md)에 있다.
- **고친 뒤 검사** `[측정: 스크래치 agent_gc_p2a2/logs_p2a2/*_pf1.log]`.

| 검사 | 결과 |
|---|---|
| `gct` 전처리 | ln4와 0 hunk |
| `gctp` 전처리 | ln4와 0 hunk |
| `gctc` 전처리 | 2 hunk 3줄(RST 간격 매개변수만, 9.8절대로) |
| sites | 149행 맞음, tcp 갈래 49개가 ln4 줄 그대로 |
| api | 통과 |
| unit | rdma, tcp 모두 실패 0 |
| 매크로 없는 프로그램 | 16/16이 SASS와 자원 모두 `mi`와 같음 |
| 장치 객체 | `gc`, `gct`, `gcp` 각 207/207이 바이트까지 같음 |
| 자원 사용, 설치 헤더 | ln4와 같음 |

| 무엇 | md5 | 비고 |
|---|---|---|
| libnccl `gc` | `cd4ee767eef3ce7a4c467e9caf2363bd` | `gc_pf1`, 경고 0 |
| libnccl `gct` | `0e31fa0c4350ef968327c913e6752713` | `gct_pf1`, `-DNCCL_GIN_CTRL_TCP=1` |
| libnccl `gcp` | `5cffdcd6d80a22fe599c1b4b262a90fb` | `gcp_pf1`, `-DNCCL_GIN_TS_PRODUCTION` |
| `gin_mi` | `2c57f99f3b6fa6428c5bb4c2439bfc88` | smoke 6의 것, 머리 digest `65fdf19b` 그대로라 다시 빌드 안 함 |
| `gin_ts2_mi` | `b9789b0b21d0aaf55c4e7fd59d3883a0` | gin-mirror `build_mi_test.sh cost` 단계를 스크래치 `agent_gc_pilot1/build_cost_pl1.sh`로 옮겨, gc 머리(`65fdf19b`)와 `gcp` libnccl로 빌드 |
| `gin_launcher` | `d1aceaf68f00d99eafa4d585195f3348` | smoke 6의 것 |

**배포.** 묶음 `~/rs-bundle/gc_pilot1/`를 `impl/test/deploy_gc.sh`로 배포했다.
- 두 노드의 새 파일 md5가 서로 같고 원본과도 같다.
- ldd는 묶음의 libnccl을 가리킨다.
- 다른 묶음의 기존 파일(rain 948, sunny 1 003)은 바뀌지 않았다.
- 출력은 스크래치 `agent_gc_pilot1/deploy.txt`에 있다.

## 시도

`harness/gpu-initiated/common/cluster_run.sh` 안에서 `chain_gc.sh` → `hold_gc.sh`로 돌렸고, hold의 STOP 규칙이 켜져 있었다.
- 시도는 9번(한도 10)이다.
- 클러스터 시간은 21:52:24–22:15:35, 약 23분이다. hold 자체는 합 949 s다.

| 시도 | hold | 시행 | 결과 |
|---|---|--:|---|
| [a1](a1/) | P0 | 2 | 통과 |
| [a2](a2/) | P1 | 1 | **STOP_nic**: `gc4_none_probe` (아래 문제 1). 남은 20셀은 STOP으로 건너뜀 |
| [a3](a3/) | P1 다시(한 번) | 20 | 통과. STOP 파일은 [a2/stopped_a2_P1_nic.txt](a2/stopped_a2_P1_nic.txt)로 옮겼다. P0와 같은 이름의 두 셀은 "already done"으로 P0의 시행을 썼다 |
| [a4](a4/) | P2 | 1 | 통과 |
| [a5](a5/) | P3 | 2 | 통과 |
| [a6](a6/) | P4 | 1 | 통과 |
| [a7](a7/) | PRG-gct-G1 | 1 | 통과 |
| [a8](a8/) | COSTPILOT-rain | 2 | 실행은 됨. probe-on 팔은 무효(문제 6) |
| [a9](a9/) | COSTPILOT-sunny | 2 | 실행은 됨. probe-on 팔은 무효(문제 6) |

모든 hold의 새 mlx5 커널 줄은 0, rain 펌웨어 명령 실패 합은 31 그대로였다. 남은 프로세스는 0, `la_stop_n` 0, `la_qp_err_n` 0이다 `[측정]`.

## 셀마다 (n 1씩)

시각표는 주입 줄 뒤 ms이고 대상 노드의 생존 rank 기준이다: 의심 / 판정 / hold 시작 / 펜스 / 게시 / 첫 걸음. 사본 상태 열은 제외 규칙이 이 시행에 준 상태다.

| 시도 | 셀 | 판정 원인(행) | 시각표 (ms) | 자료 | 사본 상태 | 규칙(시행 하나) |
|---|---|---|---|---|---|---|
| a1 | `gc4_none_ow@gc` | 판정 0 | – | 데이터 같음, READ 100 % | smoke(P0) | `none_probe_clean` 맞음 |
| a2 | `gc4_none_probe@gc` | – | – | rank 0 devcomm 실패, 나머지 watchdog | void | 돌지 못함(문제 1) |
| a1 | `gc4_kill3_ow@gc` | FIN+STALE ×3 | 0.4 / 20.9 / 25.2 / 116.6 / 153.3 / 348.6 | 복원, 데이터 같음 | smoke(P0) | `kill_judge_rdma` 맞음 |
| a3 | `gc4_kill3_ow_nowitness@gc` | EXITED ×3 | – / 126.7 / 131.8 / 131.1 / 171.1 / 360.6 | 복원, 데이터 같음 | 유효 | `kill_no_witness` 맞음 |
| a3 | `gc4_rst_kill3@gc` | FIN+STALE ×3 | 0.2 / 21.0 / 25.3 / 124.9 / 161.9 / 335.0 | 복원, 데이터 같음 | 유효 | `rst_judge_rdma` 맞음 |
| a3 | `gc4_rstgap_live300@gc` | 판정 0 | – | 거절 0 | 유효 | `rstgap_live_rdma` 맞음 |
| a3 | `gc4_fdhold_sock_kill3@gc` | EXITED ×3 | – / 62.0 / 66.9 / 66.3 / 105.0 / 322.7 | 복원, 데이터 같음 | 유효 | `finless_exit_report` **어긋남**(`100 <= kill_judge_ms_min`: 62.0 ms) |
| a3 | `gc4_fdhold_uverbs_kill3@gc` | EXITED ×3 | 76.9 / 77.0 / – | 거절 9, 복원 0 | 유효 | `fdhold_uverbs_refuse` 맞음 |
| a5 | `gc4_fdhold_sock_kill3_noreport@gc` | STALL_HELPER ×3 | 2 021.6 / 10 025.2 / 10 029.5 / 10 031.8 / 10 070.6 / 10 263.1 | 복원, 데이터 같음 | 유효 | `fdhold_sock_helper_stall` 맞음 |
| a5 | `gc4_kill3_noreport_nofdhold@gc` | NORESP ×3 | 582.5 / 3 708.0 / 3 712.1 / 3 722.3 / 3 759.2 / 3 959.0 | 복원, READ 99.888 % | 유효 | `finless_read_fail` 맞음 |
| a3 | `gc4_stop1500@gc` | 판정 0 | – | 데이터 같음 | 유효 | `stop_transparent` 맞음 |
| a3 | `gc4_stop4000@gc` | 판정 0, 의심 2 095.9 | – | 데이터 같음 | 유효 | `stop_transparent` 맞음 |
| a3 | `gc4_stop8000@gc` | 판정 0, 의심 2 076.8 | – | 데이터 같음 | 유효 | `stop_transparent` 맞음 |
| a3 | `gc4_stop12000_fence@gc` | STALL_HELPER ×3 | 2 014.5 / 10 018.1 / 10 021.9 / 10 138.6 / 10 176.5 / 10 398.5 | 복원, 데이터 같음 | 유효 | `stall_fence_restore` 맞음 |
| a3 | `gc4_stop12000_none@gc` | STALL_HELPER ×3 | 2 002.3 / 10 005.3 / – | 거절 16 | 유효 | `stall_none_refuse` **어긋남**(`surv_released == n_surv`: 4 대 3, `win_verified` 빈칸; 문제 5) |
| a3 | `gc4_slow_duty@gc` | 판정 0, 의심 0 | – | 데이터 같음 | 유효 | `slow_no_judge` 맞음 |
| a3 | `gc4_freeze12000_fence@gc` | 판정 0, 의심 2 003.8 | – | 판정 전에 실행이 끝남 | `kill_before_ckpt` | 어긋남(판정 없음; 문제 2) |
| a3 | `gc4_helper_freeze12000@gc` | 판정 0, 의심 2 003.9 | – | 같음 | `kill_before_ckpt` | 어긋남(같음; 문제 2) |
| a3 | `gc4_gpuhang12000_fence@gc` | STALL ×3, `stall_ctx=0+1` | 2 030.2 / 10 033.8 / 10 038.1 / 10 144.8 / 10 182.1 / 10 355.1 | 복원, 데이터 같음 | 유효 | `gpuhang_fence_restore` 맞음 |
| a3 | `gc4_gpuhang12000_ctx1_fence@gc` | STALL ×3, `stall_ctx=1` | 2 028.5 / 10 032.4 / 10 036.4 / 10 142.7 / 10 180.9 / 10 354.9 | 복원, 데이터 같음 | 유효 | `gpuhang_ctx1_fence_restore` 맞음 |
| a3 | `gc4_mgmt_mute8@gc` | 판정 0 | – | 데이터 같음 | 유효 | `mgmt_mute_transparent` 맞음 |
| a4 | `gct4_mgmt_mute8@gct` | 판정 0 | – | 데이터 같음 | 유효 | `mgmt_mute_tcp` 맞음 |
| a3 | `gc4_qperr_record@gc` | 판정 0 | – | 다시 짝 맺기 gen 2, 기록 잃음 0 | 유효 | `qp_err_repair` **어긋남**(`qperr_rec_gen_delta == 1`: 열 값 2; 문제 4) |
| a3 | `gc4_ud_drop_rejoin@gc` | FIN+STALE ×3 | 0.5 / 20.8 / 25.1 / 136.1 / 375.3 / 582.4 | 복원, 데이터 같음 | 유효 | `ud_drop_rejoin` 맞음 |
| a3 | `gc4_credit_stall@gc` | 판정 0 | – | `sendq_deferred` 0 | 유효 | `credit_stall_no_loss` **어긋남**(`sendq_deferred >= 1`; 문제 3) |
| a3 | `gc4_kill3_ow_spareabsent@gc` | FIN+STALE ×3 | 1.1 / 21.6 / 25.5 / 204.4 / – | 거절 9, 복원 0 | `inject_late`(간격 5.032 ms) | `spare_absent_refused` 맞음(제외라 채점 밖; 문제 7) |
| a6 | `gc4_stop12000_pilot@gc` | STALL_HELPER ×3 | 2 085.5 / 10 088.6 / – | 거절 16, `xchg=released` | pilot 셀 | 예측 없음 |
| a7 | `mi4_kill3_ow@gct` | FIN ×3 | – / 0.4 / 2.8 / – / 144.7 / 329.8 | 복원, 데이터 같음 | 유효 | gin-mirror 규칙 일곱(`regression_tcp`) 모두 시행 조건 참 |

- `no_tcp_control`의 시행 조건은 유효한 rdma 시행 21개 모두에서 참이다 `[측정]`.
  - `tcp_ctrl_bytes` 0, `ss_tx_delta_bytes` 0이다.
  - `witness_pairs`는 `witness_expected`와 같다(6 또는 증인 끔 0).
  - MTU는 4 096이다.
- tcp 빌드 시행 둘은 트래픽 중 TCP로 보낸 바이트가 37 439(`gct4_mgmt_mute8`), 333 216(`mi4_kill3_ow`)이다.
- `long_hold_lane`은 자료가 없다. hold 최대가 1 000 ms를 넘은 시행이 없다(최대 380.5 ms, `gc4_ud_drop_rejoin`).
- 9.9절 끝의 물음, 판정 전 장치 대기:
  - 12 000 ms 멈춤 셋(a3 fence, a3 none, a6 pilot)에서 생존 rank는 판정(10 005–10 089 ms)까지 hold 한도 줄 없이 기다렸다.
  - 펜스를 켠 셀은 복원되고 데이터가 같았다 `[측정, n 1씩]`.
  - pilot 셀은 판정 뒤 `declined (fence=none or no launcher)`, `xchg=released`, exit 4로 끝났다.

## 사전 등록 전 값의 제안 (정하지 않음)

| 값 | 제안 | 근거 `[측정]` |
|---|---|---|
| W (`NCCL_GIN_CTRL_CONFIRM_MS`) | **20 ms** | 장애 없는 `gc4_none_ow`의 READ로 본 박동 간격 최대(`beat_gap_max_ms`)는 1.487 ms(n 1)다. 멈춤, freeze, 느린 상대 셀을 뺀 시행 16개의 최대는 2.775 ms(`gc4_mgmt_mute8`), 그다음 2.612 ms(`gc4_qperr_record`), 나머지는 1.089–1.523 ms다. 5 × 2.775 = 13.9 ms를 20–50 ms 범위로 묶어 20 ms. 확인 창 판정 넷의 FIN → 판정 − W는 0.38–1.92 ms(규칙 W–W + 2 ms 안). 장애 없는 셀이 n 1뿐이라 `gc4_none_probe`(60 s)를 고쳐 돌린 뒤 확정하기를 권한다 |
| `LIVE_BOUND_MS` | **10 000 ms 그대로** | ring live까지 걸린 시간(`ring_live_ms_max`), rdma 시행 25개: 990.1–1 079.0 ms. 여유는 9배 남짓 |
| 멈춤 길이 허용 | **50 ms**(리뷰 권고) | SIGCONT 때 잰 멈춤 − 정한 길이: 1 500 → +1.7, 4 000 → +3.9, 8 000 → +8.2, 12 000 → +5.0, +11.6, +12.2 ms(시행 여섯). 최대 12.2 ms |
| `LAUNCHER_STALL_MS` | **1 000 ms 그대로**, 근거 자료 없음 | launcher 페이지 박동 간격을 싣는 줄이 없다. "launcher 잃음" 줄은 시행 28개에서 0이다. 정하려면 READ 요약에 launcher 페이지 간격 칸이 필요하다 `[미확인]` |
| launcher 보고 띠(kill → EXITED 판정) | **100–150 ms를 그대로 두지 말 것** | fd 자식 없는 `gc4_kill3_ow_nowitness`는 126.7 ms. fd 자식 셀은 62.0 ms(`fdhold_sock`)와 76.9 ms(`fdhold_uverbs`)다. 자식이 fd를 넘겨받으면 부모의 끝이 빨라지는 것으로 본다 `[추론]`. 셀마다 띠를 따로 두거나 하한을 50 ms로 내리는 안을 제안하고, n을 더 보고 정한다 |
| 비용 문턱 | **아직 정할 수 없음** | probe-off p50: rain 수신 13 312 ns(rank 0은 sunny), sunny 수신 13 760 ns(rank 0은 rain), 각 3 000회. rain 수신 팔의 지연 값은 1 024 ns 단위(값 7가지)라 p50로는 2 %(266 ns)를 가를 수 없다. 평균(13 518.2 대 13 459.8 ns)이나 32 ns 단위인 sunny 수신 팔을 쓰는 안을 제안한다. probe-on 팔은 무효다(문제 6) |
| 시행마다 QUERY_QP 한도(`RS_QUERY_CAP` 50 000) | **시행 wall에 비례하게**(예: 4 000 × wall s) | wall 18.6–67.7 s인 시행 여덟이 50 000을 넘었다: +50 422 – +211 069, 2 700–3 100회/s(`a3/qp_over.txt`; a4, a5 시행의 줄도 이 파일에 있음). pilot이라 기록만 했지만 본 실행에서는 STOP_mlx5가 된다 |
| NCCL bootstrap 소켓(`no_tcp_control`의 ss 조건) | 보고값 **34** | 트래픽 중 네 rank PID의 연결 TCP 소켓은 34개(유효 rdma 시행 모두 같음)이고, 두 스냅숏 사이 보낸 바이트는 0이다 |
| 셀 값 `gc4_none_probe` `STEPS` | 12 000 → **6 000 이하**(또는 걸음 사이를 늘림) | 문제 1. `STEPS=6000`(`gc4_slow_duty`, 창 약 74 MB)은 돌았다. 걸음 속도(`gc4_none_ow` 600 걸음에 약 4.7 s)로 보면 약 46 s다 |
| 셀 값 freeze 둘 | `FREEZE_PAGE=12000@<ms>`, `STEPS` 약 3 000 | 문제 2 |

## 문제 (고치지 않음, 결정 필요)

1. **`gc4_none_probe`는 rain에서 돌 수 없다(셀 값).**
   - rank 0이 `ibv_reg_mr_iova2 failed with error Bad address`로 devcomm에 실패했다(`devcomm_rc=2`). 나머지 rank는 watchdog로 끝났다.
   - 받는 창이 148 897 792 B(`STEPS=12000` × 4 KiB × 상대 셋)다.
   - 같은 때 rain dmesg의 `NVRM: dmaAllocMapping_GM107: can't alloc VA space for mapping`이 34줄 늘었다(941 → 975). rain BAR1은 256 MiB다 `[측정]`.
   - 실행기 문제가 아니라서 셀 파일을 고쳐야 한다(위 제안).
2. **freeze 셀 둘은 판정 전에 끝난다(셀 값).**
   - 스위치는 처음 무장 때부터 멈춘다 `[소스: gdakiCtrlFreezeParse, 21290행 부근]`.
   - 셀은 600 걸음이라 실행이 멈춤 시작 약 5.6 s 뒤에 끝났고(`GINRS end`), 판정은 0이다.
   - `ckpt_stable_before_inj=0`이라 `kill_before_ckpt`로 제외된다.
   - 라이브러리는 이미 `@<after ms>`를 받는다. `STEPS`와 시작 지연을 셀에 넣어야 한다.
3. **`gc4_credit_stall`은 창을 채우지 못했다.**
   - `sendq_deferred=0`, `sendq_max=0`이다. 500 ms 멈춤 동안 기록이 64칸을 채우지 않았다.
   - launcher credit READ 재시도도 이번에 걸리지 않았다. `send window … exhausted` 줄은 모든 로그에서 0이다 `[측정: grep]`.
   - 멈춤을 늘리거나 기록을 늘리는 셀 값이 필요하다.
4. **`qperr_rec_gen_delta`의 셈(채점기).**
   - 로그에는 다시 짝 맺기 한 번(gen 1 → 2)이 있다: `PAIR(record, gen 2) to rank 0 (local ERR)`, 그다음 `record QP to rank 0 re-paired (gen 2)`.
   - 그런데 `rows_gc.py` 1251행은 차이가 아니라 새 세대 값(`max(gens)` = 2)을 낸다 `[소스]`. 규칙 `== 1`은 차이를 뜻하는 것으로 보이므로 채점기 쪽 고침이 필요하다 `[추론]`. 이 파일은 고칠 범위 밖이다.
5. **`stall_none_refuse` 규칙(셀 또는 채점기).**
   - `FENCE=none`에서는 SIGCONT 뒤 rank 3도 풀려 `surv_released`가 4(생존 셋 + rank 3)다.
   - 펜스가 없으니 창 줄도 없어 `win_verified`가 빈칸이다.
   - 이 셀에서 두 항의 뜻을 정해야 한다.
6. **비용 probe-on 팔은 증거 규칙상 무효이고 READ를 재지도 못한다.**
   - `gcp`에서 `GIN_TS_NOTE`는 INFO다 `[소스: gin_host_gdaki.cc 86–90행]`. `run_cost_gc.sh`가 `NCCL_DEBUG=WARN`이라 READ 요약 줄이 없다(`cost_probe_evidence=r0:p1:no_summary`).
   - kernel이 45.4–46.5 ms로 `PROBE_MS` 100보다 짧아, kernel 창 안에 READ 주기가 거의 없다.
   - 지표 반복 수나 로그 수준을 바꿀지는 측정 방법의 결정이다.
7. **`gc4_kill3_ow_spareabsent`의 간격은 5.032 ms였다.**
   - 5 ms 넘음 규칙으로 `inject_late`다.
   - 실행기 목표가 정확히 5 ms라 넘기 쉽다. 목표를 4.8 ms로 낮추거나 허용을 5.5 ms로 두는 안이 있다.
8. `gc4_gpuhang12000_fence`의 `stall_ctx=0+1`은 smoke 6과 같다(그 예측은 이 열을 쓰지 않음).
9. 시행마다 READ 지연 최대가 13.3–33.8 ms다(중앙값 약 79 µs). 확인 창 W/2(10 ms)보다 크다. 언제 난 것인지는 가르지 않았다 `[미확인]`.

## 하지 않은 것

- `impl/gate_fenced.cc`의 pid 모드가 없어 `gate_fenced`는 돌지 않았다.
- gin-mirror 회귀 hold의 `@gc` 셀들(`RG-gc-*`)은 pilot 범위 밖이다.
- 비용 팔은 노드마다 한 번씩이라 같은 팔 사이 퍼짐은 재지 못했다.
- `gc4_none_probe`는 다시 돌리지 않았다(셀 값 문제).
- 시도 한도는 1번 남았다.

## 실행기 쪽 바꿈 (이번에 돌았음)

- `impl/test/hold_gc.sh`: pilot 회귀 hold `PRG-<b>-<mirror hold>`를 더했다(`RG-`의 셀을 n 1로, pilot 폴더에서만). a7에서 돌았다.
- `impl/test/deploy_gc.sh`: 기존 파일 md5 목록이 폴더를 가리키는 링크(`~/rs-bundle/gc_smoke*`)에서 `md5sum` 오류를 내 `set -e`로 멈췄다(아무것도 쓰기 전).
  - 이제 일반 파일만 md5를 내고, 링크는 `경로 -> 대상`으로 적는다.
  - 고친 판으로 배포했다.

원자료는 `aN/`에 있고 시행 표는 `aN/trials.csv`다. 모두 IPv4 가림을 거쳤다(IPv4 꼴 0건, 관리망 주소 0건 `[측정: grep]`). 이 폴더 루트에는 다음 둘이 있다.
- 사슬 기록: [chain.out](chain.out)
- 시도 기록: [attempts.txt](attempts.txt)
