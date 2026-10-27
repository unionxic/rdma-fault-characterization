# gin-control pilot 5 (2026-10-27 14:21–14:29, 채점 안 함)

멈춘 rank를 기다리는 rank는 원인이 풀릴 때까지 판정하지 않는 새 규칙(라이브러리 wp2, gc `54e7ddec`; [../../impl/notes_waitpeer.md](../../impl/notes_waitpeer.md))을 실제 RNIC, launcher, 두 노드에서 처음 돌렸다.
hold P6(셀 B 2, 기다리는 rank도 멈춤 2, 두 rank 고리 1, GPU hang 대조 1, 조용한 긴 계산 1)과, 조율 세션이 더한 kill 1, SIGSTOP 1(같은 묶음)이다.
pilot은 본 실험에 들지 않고 채점하지 않는다. 판과 셀 env는 [VERSIONS.md](VERSIONS.md)다.

표시: `[측정]` 원자료에서 다시 셈, `[소스]` 코드를 읽음, `[추론]` 해석, `[미확인]` 확인 안 함. 시각은 모두 그 시행의 첫 주입 줄(GPU hang 셀은 rank 3의 `GINRS gpuhang` 줄, 조용한 셀은
`GINRS quiet`, kill은 실행기의 `GINRS killed`, SIGSTOP은 `GINRS stop`) 뒤 ms이고, sunny 쪽 줄은 meta의 노드 시계 차(왕복 0.172–0.191 ms)로 rain 시계에 옮겼다.
시행마다의 사건 목록은 [events/](events/)(만든 스크립트 [events.py](events.py), pilot 4 판에 기다림 줄, 자기 줄, kill/stop 기록을 더함)다. 범위는 그 시행 안의 관측자 사이 최소–최대다.

## 시도

`harness/gpu-initiated/common/cluster_run.sh` 안에서 `chain_gc.sh` → `hold_gc.sh`로 돌렸고 STOP 규칙이 켜져 있었다. 시도 1번(한도 10), 클러스터 시간 약 7분 20초(한도 3 h).

| 시도 | 시각 | hold | 시행 | 결과 |
|---|---|---|--:|---|
| [a1](a1/) | 14:21:31–14:27:18 | `P6` (315 s, 한 hold로 840 s 안에 듦) | 7 | STOP 0, 건너뜀 0 |
| [a1](a1/) | 14:27:18–14:28:51 | `PCELL-gc4_kill3_ow+gc4_stop12000_fence` (61 s) | 2 | STOP 0 |

- 두 hold 모두 새 mlx5 커널 줄 0, rain 펌웨어 명령 실패 합 31 그대로, rain mlx5 cmd_err 2 그대로, 남은 프로세스 0, QUERY_QP 상한 넘음 0(`qp_over.txt` 없음) `[측정: a1/snap_*, a1/mlx5_new_*]`.
- launcher STOP 줄 0, launcher QP 잃음 0(아홉 시행 `la_stop_n` 0, `la_qp_err_n` 0) `[측정]`.
- 실행기 쪽 기록 둘: [hang_watchdog.txt](hang_watchdog.txt)(기다리는 rank도 멈춘 셀의 rank 1이 자기 watchdog으로 끝남, 두 줄, 설계대로 STOP 아님), [spare_wait.txt](spare_wait.txt)(같은 두 시행의 예비 프로세스 kv가 watchdog; 아래 문제 1).
- 조율 세션은 kill/stop을 `PRC-` 꼴로 돌리라고 했으나 `PRC-`는 회귀 hold(gin-mirror 셀)만 받는다(`hold_gc.sh` `json_hold`). 두 셀은 `cells_gc.json`의 셀이라 pilot 3과 같은 `PCELL-` 꼴로 돌렸다 `[소스]`.
- 실행기, 채점기, 셀 파일은 고치지 않았다.

## 시행마다

| 시행 | wall | 끝 | 판정(대상: 관측자, 원인, 시각 ms) | 기다림 줄(대상 rank 1) | hold | 펜스 | 복원 | 데이터 같음 |
|---|--:|---|---|---|---|---|---|---|
| 셀 B n1 | 21.1 s | 모두 rc 0 | rank 3: r1, r0, r2 STALL 10 046.0–10 047.1. rank 1: 없음 | `waiting (peer=3)` r2, r0, r3; `wait ended (progress…)` r2, r0 | 3 | SIGKILL → FENCED | 됨 | 1 |
| 셀 B n2 | 21.1 s | 모두 rc 0 | rank 3: r1, r0, r2 STALL 10 026.6–10 028.8. rank 1: 없음 | 같음(r0, r2, r3 / r0, r2) | 3 | SIGKILL → FENCED | 됨 | 1 |
| 기다리는 rank도 멈춤 n1 | 61.6 s | r0, r2 rc 4(released), r1, 예비 rc 7(watchdog) | rank 3: r0, r2, r1 STALL 10 060.1–10 062.5. rank 1: r0 12 261.0, r2 12 357.5 STALL | `waiting` r0, r2, r3; `wait ended (its peers resolved, no progress within G…)` r2, r0 | 3(rank 3) | rank 3만 | rank 3 됨, rank 1은 거절 | 0 |
| 기다리는 rank도 멈춤 n2 | 61.6 s | 같음 | rank 3: r0, r2, r1 STALL 10 012.8–10 015.0. rank 1: r2 12 311.6, r0 12 312.7 STALL | 같음 | 3(rank 3) | rank 3만 | 같음 | 0 |
| 고리 1↔3 n1 | 19.1 s | 생존 셋 rc 4(released), rank 3 펜스 | rank 3: r1, r0, r2 STALL 10 010.2–10 013.4. rank 1: r0, r2 STALL 10 110.9 | 없음 | 3(rank 3), 모두 포기 | rank 3 SIGKILL → FENCED | 없음(fallback) | 0 |
| GPU hang 대조 n1 | 21.1 s | 모두 rc 0 | rank 3: r0, r1, r2 STALL 10 067.5–10 069.7 | 없음 | 3 | SIGKILL → FENCED | 됨 | 1 |
| 조용한 긴 계산 n1 | 22.6 s | 모두 rc 0 | 없음(의심 0) | 없음 | 0 | 없음 | 없음 | 1 |
| kill n1 | 11.1 s | 모두 rc 0 | rank 3: r1, r0, r2 FIN+STALE 20.8–21.0 | 없음 | 3 | SIGKILL → FENCED | 됨 | 1 |
| SIGSTOP 12 s n1 | 21.1 s | 모두 rc 0 | rank 3: r2, r1, r0 STALL_HELPER 10 100.6–10 101.7 | 없음 | 3 | SIGKILL → FENCED | 됨 | 1 |

열 값은 `rows_gc.py`가 원자료에서 다시 셈한 시행 표 [a1/trials.csv](a1/trials.csv)와 사건 목록에서 읽었다 `[측정]`. 본 셀 일곱은 `scored`, pilot 전용 셀 셋(기다리는 rank도 멈춤 2, 고리 1)은 본 셀
목록에 없어 `config` 상태다(설계대로, 채점 대상 아님). 아홉 시행 모두 `inject_ok` 1, `probe_timeout_n` 0이다. 모든 rank와 예비 프로세스가 시작 때 `own device line read locally (4 context(s) …)`를
냈고 `not read locally`는 0줄, `stall verdict … dropped`는 0줄이다 `[측정: grep]`. 판정 줄에는 판정 표의 행 번호가 없다(원인 낱말 STALL만; 판정 표 14행이라는 것은 원인에서 읽은 것) `[추론]`.

## 셀 B: 멈춘 rank 3을 기다리는 정상 rank 1 (n 2)

**pilot 4에서는 rank 1이 먼저 판정되어 communicator 전체가 fallback했다. 새 규칙에서는 두 시행 모두 rank 1이 한 번도 판정되지 않았고, rank 3이 생존 셋 모두에게 판정되어 펜스와 복원이 됐다** `[측정]`.

| 시각 (ms) | n1 | n2 |
|---|---|---|
| rank 1 긴 기다림 줄(걸음 156, dest 3) | 1 008.6 | 1 007.8 |
| `waiting (peer=3)`(대상 rank 1, stale_ms 1 800.x, ctx 3), 관측자 | 1 843.3 (r2), 1 844.1 (r0), 1 939.1 (r3) | 1 824.0 (r0), 1 825.5 (r2), 1 919.6 (r3) |
| rank 1 의심(gpu, ctx 3; 막이 "no other survivor readable") | 2 040.1 (r3), 2 040.6 (r2), 2 044.1 (r0) | 2 019.0 (r0), 2 019.2 (r2), 2 020.5 (r3) |
| rank 3 의심(gpu) | 2 042.7 (r1), 2 043.3 (r2), 2 043.8 (r0) | 2 023.3 (r1), 2 024.0 (r0), 2 025.5 (r2) |
| **rank 3 판정**(STALL) | **10 046.0 (r1), 10 047.1 (r0, r2)** | **10 026.6 (r1), 10 027.8 (r0), 10 028.8 (r2)** |
| hold 시작 | 10 050.0–10 052.0 | 10 030.6–10 034.4 |
| launcher FENCE(SIGKILL) / FENCED / 활성화 ACCEPTED | 10 052.6 / 10 155.1 / 10 157.0 | 10 034.4 / 10 145.7 / 10 147.7 |
| 창 줄 셋(`base=fenced sample=rejoin changed=0`) | 10 168.1–10 195.3 | 10 159.6–10 186.1 |
| 복원 게시(`restore round … published`) / `restored as incarnation 1` | 10 182.1–10 224.5 / 10 224.5–10 224.6 | 10 173.1–10 215.3 / 10 215.3–10 216.2 |
| rank 1 칸 기다림 끝(`result=satisfied`, `wait_ms`) | 10 368.9 (10 360.7) | 10 362.7 (10 354.6) |
| rank 1 걸음 156 끝(`released=0 tx_err=0`) | 10 368.1 | 10 362.1 |
| `wait ended (progress: it left the stalled set)`, waited | 10 444.0 (r2, 8 600.7), 10 447.4 (r0, 8 603.3) | 10 422.1 (r0, 8 598.2), 10 422.9 (r2, 8 597.4) |

- **rank 3을 누가 언제.** 셋 모두 STALL, 10 026.6–10 047.1 ms(`stop_judge_ms` 띠 10 000–10 500 안). 두 시행 모두 첫 판정은 rank 1이다(rank 1 자신도 기다리는 중인데 rank 3을 SOURCE로 판정: 자기 줄의 로컬 읽기로 자기 Z를 정하는 길이 장치에서 돌았다) `[측정]`.
- **rank 1은 판정되지 않았다**(`waiter_judge_n` 0, rank 1 대상 STALL/DEAD 줄 0, hold 0, 거절 0). 의심 줄(18행)은 셋 다 냈다(규칙대로 의심과 기다림 줄만) `[측정]`.
- 기다림 문: r0, r2의 probe summary `wait_n=1`, `wait_ms_max` 8 597.4–8 603.3, `role_dep_n` 85–86. 멈춘 옛 rank 3(r3)도 `waiting (peer=3)`을 냈으나 펜스로 죽어 `wait ended`는 없다 `[측정]`.
  r2(n1)와 r0, r2(n2)의 rank 1 `role_src_n`이 1이다(rank 1이 SOURCE로 보인 판정 하나). 그 한 번이 언제인지는 줄이 없어 보지 않았다 `[미확인]`. 판정으로 이어지지 않았다.
- **rank 1의 `tx_err`와 flush.** 칸 기다림은 복원된 rank 3의 put으로 풀렸고(`satisfied`, `restored` 줄 뒤 144.3 ms, 146.5 ms) 걸음 156이 `tx_err=0`으로 끝났다. kv `tx_err=0 rx_err=0 steps_done=600 xchg=ok exit=0` `[측정]`.
  pilot 4에서 볼 수 없던 "복원 뒤 그 걸음의 flush"는 오류 없이 돌았다.
- 데이터 같음(`data_equal` 1, `ow_data_equal` 1), 예비 사용 1, `restore_count` 3 `[측정]`.
- pilot 4의 WARN 줄 넘침은 사라졌다: 이 셀의 rank 로그는 150 KB 안팎이고(pilot 4 rank 3 약 100 MB), 아홉 시행 원자료 전체가 5.0 MB다. 오류 확인 간격을 늘린 driver와 복원(멈춘 rank가 펜스됨) 둘 다의 결과다 `[측정: 크기]`, `[추론: 원인 나눔]`.

## 기다리는 rank도 멈춤: rank 3 hang, rank 1이 rank 3 쪽 context에서만 hang (n 2)

**rank 3이 먼저 판정, 펜스, 복원되고, 그 뒤 G(2 000 ms) 동안 rank 1의 원소에 진행이 없어 문이 열리고 rank 1이 STALL로 판정됐다. rank 1에는 예비가 없어 거절(degraded)되고 r0, r2는 오류로 끝났다.** 숨김은 없었다 `[측정]`.

| 시각 (ms) | n1 | n2 |
|---|---|---|
| rank 1 hang 줄(걸음 156, ctx 3) | 7.5 | 7.5 |
| `waiting (peer=3)`(대상 rank 1) | 1 856.9 (r0), 1 857.6 (r2), 1 952.8 (r3) | 1 809.2 (r0), 1 905.6 (r3), 1 906.9 (r2) |
| rank 3 판정(STALL) | 10 060.1 (r0), 10 061.2 (r2), 10 062.5 (r1) | 10 012.8 (r0, r2), 10 015.0 (r1) |
| FENCE / FENCED | 10 067.8 / 10 170.2 | 10 019.1 / 10 120.6 |
| `restored as incarnation 1`(생존 셋) | 10 239.7–10 239.9 | 10 189.8–10 189.9 |
| `wait ended (its peers resolved, no progress within G: the 10 s rule judges it)`, waited | 12 256.8 (r2, 10 399.2), 12 258.9 (r0, 10 401.9) | 12 210.7 (r2, 10 303.8), 12 212.2 (r0, 10 403.0) |
| **rank 1 판정**(STALL, ctx 3) | **12 261.0 (r0), 12 357.5 (r2)** | **12 311.6 (r2), 12 312.7 (r0)** |
| 거절(`declined … liveness stall judged (STALL)`, degraded) | 12 262.8 (r0), 12 360.2 (r2) | 12 313.3 (r2), 12 315.6 (r0) |
| r0, r2 풀림(걸음 157, `released=1 tx_err=0`) | 14 263.5, 14 361.6 | 14 314.8, 14 316.1 |
| 예비 프로세스(복원된 rank 3)가 rank 1 FIN+STALE 판정 / rank 1 EXITED / 예비 EXITED | 57 224.2 / 57 305.5 / 58 462.2 | 57 296.8 / 57 377.7 / 58 508.5 |

- **복원 게시 → rank 1 판정**: 2 021.3–2 117.8 ms(n1), 2 121.7–2 122.8 ms(n2). 문이 열린 줄은 복원 줄 뒤 2 017.1–2 022.4 ms, 판정은 그 뒤 2.1–100.9 ms(probe 한 주기 안)다. CPU 모형의 기대 "restoredAt + G와 + G + 700 ms 사이"와 맞는다 `[측정]`.
- rank 1 판정 관측자는 r0, r2 둘이다. 복원된 rank 3(예비 프로세스)은 r0, r2의 STALLED를 받았으나(12 261.2, 12 357.7) 스스로 판정하지 않았고, 약 57 s 뒤 rank 1 프로세스가 watchdog으로 끝날 때 FIN+STALE로 판정했다.
  그래서 채점기 열 `judged_ranks`는 `1:12261.0:3`, `waiter_judge_causes`는 `FIN+STALE:1+STALL:2`다(열 정의대로 센 것) `[측정]`.
- r0, r2의 probe summary: rank 1 `wait_n=1`, `wait_ms_max` 10 303.8–10 403.0, `role_dep_n` 103, `role_src_n` 52–53(문이 열린 뒤 SOURCE) `[측정]`.
- **communicator 오류.** r0, r2는 degraded 2 000 ms 뒤 걸음 157에서 풀려 `xchg=released exit=4`. rank 1은 GPU에서 돈 채 자기 watchdog(60 s)으로 끝났다(`watchdog=1 exit=7`, hang_watchdog.txt). **복원된 rank 3도 watchdog으로 끝났다**(`watchdog=1 exit=7`, 아래 문제 1) `[측정]`.

## 두 rank 고리: rank 3은 rank 1 쪽 context에서만 hang, rank 1은 `GC_WAITPEND` (n 1)

**rank 3과 rank 1 모두 STALL로 판정됐고(rank 3 10 010.2–10 013.4 ms, rank 1 10 110.9 ms), hold는 rank 1의 판정으로 포기되어 fallback했다. 숨김은 없다** `[측정]`.

- 기다림 줄 0(둘 다 CYCLE로 분류: r0, r2의 summary rank 1 `role_cycle_n` 85, rank 3 `role_cycle_n` 83, `wait_n` 0) `[측정]`.
- 의심: rank 3 2 006.7–2 010.1(r1, r0, r2; ctx 1), rank 1 2 104.1–2 108.1(r3, r2, r0; ctx 3).
- rank 3 판정 10 010.2 (r1), 10 012.3 (r0), 10 013.4 (r2) → hold 셋 10 014.5–10 018.1 → launcher FENCE 10 018.7.
- rank 1 판정 10 110.9 (r0, r2; rank 3 판정보다 약 100 ms, probe 한 주기 뒤). rank 1의 summary `role_src_n` 48: rank 3이 펜스되어 줄이 사라진 뒤 rank 1은 SOURCE로 보였다 `[추론: summary 정의]`.
- 그 판정의 degraded raise로 r0, r2가 rank 3의 hold를 포기("a fault reached the application meanwhile"), r1은 FALLBACK을 받아 포기했다(10 114.7–10 115.3). 그 뒤 FENCED 10 123.0. 예비 활성화 없음, 창 줄 셋 `base=judgement sample=hold_end changed=0` `[측정]`.
- 생존 셋 걸음 156에서 풀림 12 115.9–12 118.0(`tx_err=0`, `xchg=released exit=4`), rank 1의 칸 기다림은 abort로 풀림(`result=released`, `wait_ms` 12 108.5). rank 3은 펜스의 SIGKILL로 끝났다(watchdog 아님) `[측정]`.
- 결과는 설계 문서의 기대(원인 식별이 아니라 둘 다 STALL_MS에 판정, fallback, 숨김 없음)와 같다. 다만 펜스(rank 3 SIGKILL)는 fallback 전에 이미 보내졌다: rank 3 프로세스는 죽었고 복원은 없다 `[측정]`.

## GPU hang 대조와 조용한 긴 계산 (n 1씩)

- **대조**(`GC_WAITPEND` 없음): 의심은 rank 3 하나(2 064.1–2 066.4, ctx 0), 판정 10 067.5–10 069.7(STALL), hold 셋, FENCE 10 075.2, FENCED 10 186.6, 복원 10 254.9–10 255.8, 데이터 같음.
  rank 3 아닌 rank의 의심, 판정 0(`suspect_any_n` 3) `[측정]`. pilot 4 대조(판정 10 032.7–10 035.9)와 같은 띠다.
- **조용한 긴 계산**: rank 3이 걸음 155 첫머리에서 12 001.1 ms 돌았다(시작과 끝 줄). 네 rank 모두 의심 0, 판정 0, 거절 0, hold 0, 기다림 줄 0. `quiet_periods` 115(`P_w=119 X_0=4 X_1=4 X_2=4`), 데이터 같음, 예비 안 씀 `[측정]`.

## kill과 SIGSTOP (어린 보기 표시가 다른 판정 길을 늦추는지)

새 라이브러리는 관측자가 상대를 짝 맺은 뒤 9 800 ms 동안 본 적이 없으면 그 보기를 "어린 보기"로 표시하고, 분할 막이는 그 보기를 증인에서 뺀다(`notes_waitpeer.md` "어린 보기").
막이는 판정 입력 중 GPU 줄과 호스트 박동(helper, watch)의 정체 길(`gdakiCtrlRofStale`의 `guardOk`)에만 들어간다 `[소스: gin_host_gdaki.cc gdakiCtrlRDerive]`.

| 시행 | 판정 원인과 시각 | 펜스 | 복원 | pilot 3 같은 셀 |
|---|---|---|---|---|
| kill n1 | FIN+STALE 셋, 20.8 (r1), 21.0 (r0, r2) | FENCE 26.7, FENCED 121.6(SIGKILL 뒤 94.9 ms) | 게시 146.6–189.8, `restored` 189.8–190.8 (`t_publish_ms` 160.0) | 판정 20.8–21.1, 복원 183.4 (`t_publish_ms` 175.0) |
| SIGSTOP 12 s n1 | STALL_HELPER 셋, 10 100.6 (r2), 10 100.7 (r1), 10 101.7 (r0) | FENCE 10 107.4, FENCED 10 214.8 | 게시 10 242.4–10 285.3, `restored` 10 285.3–10 285.4 | 판정 10 040.8–10 044.0 |

- **kill은 늦어지지 않았다**(FIN+STALE 20.8–21.0 ms, 확인 창 READ1 +0.10–0.21 ms, READ2 +10.10–10.16 ms; 복원도 pilot 3과 같은 띠) `[측정]`. 의심 줄 0이라 막이 줄도 없다.
- **SIGSTOP의 판정 시각은 pilot 3보다 약 60 ms 늦지만 막이 때문이 아니다.** 의심(watch, 2 000.6–2 001.1)이 2 096.9–2 098.2 ms(pilot 3 2 037.6)에 섰고 관측자마다 의심 → 판정은 8 003.5–8 003.8 ms로 pilot 3(8 003.2, 관측자 하나)과 같다.
  늦음은 정체 원점(박동의 위상)에서 왔다 `[측정: 차]`, `[추론: 원인]`. `stall_fence_restore`의 띠(10 000–10 300) 안이다.
- **막이 줄은 바뀌었다.** 이번 pilot의 의심 줄 36개 모두(약 2 s; 셀 B, 기다리는 rank도 멈춤, 고리, 대조, SIGSTOP)가 `(partition guard: no other survivor readable; this rank suspects itself)`이다. pilot 3 SIGSTOP과 pilot 4 대조의 같은 줄은
  `(partition guard: another survivor sees it fresh)`였다 `[측정: grep]`. 시작 후 약 2–4 s에서는 모든 보기가 9 800 ms보다 어려 증인이 없기 때문이다 `[추론]`. 의심 줄은 판정이 아니어서 이 pilot의 판정 시각은 바뀌지 않았다.
  `no witness` 꼴의 줄과 `young`이라는 낱말의 줄은 생존 rank 로그에 0줄이다(표시는 페이지 낱말의 bit 62라 줄로 나오지 않음) `[측정: grep]`, `[소스]`.

## 예측이 이 시행에서 읽히는 것 (채점 아님)

`score_gc.py`를 세션 스크래치 사본에서 pilot 표시를 끄고 계획 n을 있는 시행 수로 둔 채 돌렸다(pilot 4의 `score_pilot.py`와 같음; 채점기는 HEAD b8365790, 바꾸지 않음). 출력 전부는 [score_v0/](score_v0/)다. 채점기 결함을 찾지 못해 `score_v1/`은 없다.

| 예측 (ID) | 무엇을 예측했나 | 이 pilot에서 | 시행 조건 |
|---|---|---|---|
| 멈춘 GPU의 펜스와 복원 (`gpuhang_fence_restore`) | 생존 셋 STALL 10 000–10 500 ms, 펜스, 창 검사, 붙잡힘, 데이터 같음, 복원; 셀마다 | 셀 B 2/2(pilot 4 0/2), 대조 1/1 | n < k라 "자료 부족(n<k)" |
| 지금 규칙은 기다리는 정상 rank도 판정함 (`waiter_old_rule`) | rank 1 판정 관측자 ≥ 1, 10 000–12 500 ms | **0/2**: 새 규칙에서 rank 1 판정 0 | 같음 |
| 조용한 긴 계산은 판정하지 않음 (`quiet_compute_no_judge`, safety) | 의심, 판정, hold 0, `quiet_periods` ≥ 100, 데이터 같음 | 1/1 | 사본에서 "맞음" |
| kill의 RDMA 판정 (`kill_judge_rdma`) | FIN+STALE, 확인 창 | `gc4_kill3_ow` 1/1 | 다른 셀 없음 → 자료 부족 |
| 긴 멈춤의 펜스 뒤 복원 (`stall_fence_restore`) | STALL_HELPER 10 000–10 300 ms, 펜스, 복원 | 1/1 | 자료 부족(n<k) |
| RDMA 제어에 TCP 없음 (`no_tcp_control`, safety) | `build:gc` 묶음의 `tcp_ctrl_bytes` 0 | 6/6 | 다른 셀 자료 없음 |

- `waiter_old_rule`은 "지금(옛) 규칙"의 연쇄를 재는 예측이라 라이브러리가 바뀌면 거짓으로 나온다. 이것은 고친 규칙의 기대대로이고 예측 표를 어떻게 할지는 결정이 필요하다(아래).

## 문제 (고치지 않음; 라이브러리는 보고만)

1. **[라이브러리] 복원된 화신은 기다리던 rank의 판정을 따르지 않고 watchdog까지 멈춘다** (기다리는 rank도 멈춤 2/2). r0, r2가 rank 1을 판정하고 STALLED를 보냈으나 복원된 rank 3은
   스스로 판정하지 않고 degraded로도 가지 않았다. r0, r2가 떠난(BYE) 뒤에도 남아 rank 1 프로세스가 끝난 57 s에야 FIN+STALE로 판정했고, 장치 대기는 풀리지 않아 자기 watchdog(60 s)으로 끝났다 `[측정]`.
   예비 로그(n1): `GIN/RC: rank 3: STALLED(rank 1, incarnation 0) from rank 0 mono_ms=3102714426.336`, `… from rank 2 mono_ms=3102714522.810`, `GIN/TS: rank 3: rank 0 left the communicator (BYE) mono_ms=3102719439.408`,
   `GIN/TS: rank 3: rank 1 judged dead (cause=FIN+STALE)`(57 224 ms), kv `resume_rc=0 revived=1 … watchdog=1 exit=7`. 예비의 probe summary에서 rank 1은 `role_*` 0, `wait_n` 0(그 화신에게 rank 1은 Z 밖) `[측정]`.
   까닭은 notes_waitpeer.md 열린 문제 1과 같은 쪽으로 보인다: 복원 commit이 rank 1의 rank 3 쪽 QP를 (0, 0)으로 만들어 새 화신의 원소 시계에서 rank 1은 조용하고, 그 화신은 그 원소의 다시 쓰기를 붙잡는 문도 없다 `[추론]`.
   결과는 오류 보고가 아니라 복원된 rank의 멈춤이다. 최소 고침의 방향(결정 필요): 받은 STALLED가 같은 상대에 대한 두 생존 rank의 것이면 그 화신도 degraded로 가거나, 복원된 화신이 commit 전의 원소 상태를 넘겨받음.
2. **[라이브러리, 관찰] 셋업 뒤 9.8 s 안의 의심은 모두 막이 SELF다.** 어린 보기 결정의 예상된 결과(notes_waitpeer.md 열린 문제 1의 "남은 것")가 장치에서 보였다. 이번 판정 시각에는 영향이 없었다(위 kill, SIGSTOP 절).
   짝 맺은 뒤 9.8 s 안에 판정 문턱에 닿는 길(예: 복원 직후의 두 번째 장애)에서는 막이가 증인 없이 SELF로 판정한다 `[추론]`, 이 pilot에서는 재지 않았다 `[미확인]`.
3. **[예측 표, 결정 필요] `waiter_old_rule`.** 고친 라이브러리에서 0/2이다. 이 예측을 옛 규칙의 기록으로 남길지(옛 라이브러리로만 채점), 새 규칙의 예측("셀 B의 rank 1 판정 0, rank 3 복원")으로 바꿀지 정해야 한다. 셀 B의 `gpuhang_fence_restore`는 2/2로 바뀌었다.
4. **[보고 열] 고리 셀에서 펜스는 fallback 전에 보내졌다.** 원인을 못 가리는 고리에서도 먼저 판정된 rank 3은 SIGKILL로 끝났고 복원은 없다. 설계 문서의 "fallback"이 이것을 포함하는지는 문서에 없다 `[미확인]`.

## 하지 않은 것

- 기다리는 rank도 멈춘 셀의 복원된 화신 쪽 원소 상태(왜 rank 1이 Z 밖인지)를 줄로 확인하는 것: 라이브러리에 그 줄이 없다.
- 셀 B의 `role_src_n` 1이 언제인지.

원자료는 [a1/raw/](a1/raw/)(IPv4 가림, 5 MB 넘는 로그 없음), 시행 표 [a1/trials.csv](a1/trials.csv), 사슬 기록 [chain.out](chain.out), 시도 기록 [attempts.txt](attempts.txt), 배포 출력 [deploy.txt](deploy.txt), hold 출력 `a1/run_*.out`이다.
IPv4 꼴 0건, 관리망 주소 0건 `[측정: grep]`.
