# gin-control 본 실행 독립 재계산 (QA, 2026-11-18)

채점기(`rows_gc.py`, `score_gc.py`, `test_rows_gc.py`)를 읽거나 돌리지 않고, 본 실행 원자료(`agent_gc_main1/main/raw/`, `reg/`, `cost_probe_*/`, `hold_*.out`, `chain.out`, `stops/`)를 이 폴더의 스크립트로 다시 셌다.
`SCORE.md`와 `trials_scored.csv`는 내 숫자를 다 낸 뒤 비교 표(9절)에만 썼다. 클러스터, git, 이 폴더 밖 파일은 건드리지 않았다.

표시: `[측정]` 원자료에서 내 스크립트로 다시 셈, `[추론]` 해석, `[미확인]` 확인 못 함. 시각은 그 시행의 주입 줄 뒤 ms이고, sunny 프로세스의 `mono_ms`는 meta의 두 시계 차 가운데 왕복이 짧은 쪽으로 rain 시계에 옮겼다(pilot 7 `events.py`와 같은 방식).

## 스크립트

| 파일 | 하는 일 |
|---|---|
| `ev_gc.py` | 시행 하나의 로그(rank, 예비, launcher, kill/inject 출력)에서 사건 줄을 정규식으로 읽어 rain 시계로 맞춤 |
| `recount_gc.py` | 시행마다 한 행: 주입, 판정(관측자, 원인, 시각), 펜스 순서, 복원, 풀림, 데이터, 대기 결과 → `trials_qa.csv` |
| `cellsum.py`, `tables_qa.py` | 셀마다 묶음, 아래 표 1–4 |
| `finjudge.py` | 증인 FIN/RST 줄 → 자기 판정 줄 |
| `hold_qa.py` | hold 시작 → INJECTED 또는 포기(given up) |
| `extra_qa.py` | 입력 멈춤 최대, 기다리는 rank 셀 줄, 관리망과 QP 오류, UD, credit 셀 줄 |
| `cost_qa.py` | 비용 팔의 `lat_p50_us`(r0.kv)와 `lat_raw.csv.gz`에서 다시 낸 p50 |
| `compare_qa.py`, `compare2_qa.py` | 내 열과 `trials_scored.csv` 열 비교 → `compare_out.txt` |

정의(내 것): "판정"은 생존 rank 자기 로그의 `rank 3 judged dead (cause=…)` 또는 `(incarnation 0) judged stalled (… (원인))` 줄(관측자마다 첫 줄). "복원 시간"은 첫 판정 → 생존 rank의 마지막 `rank N restored as incarnation` 줄. "게시"는 생존 rank의 `restore round with rank N published` 줄. "데이터 같음"은 끝까지 간 모든 프로세스(생존 rank와 되살린 rank)의 kv가 `x_match=1`, `sig_exact=1`, `recv_bad=0`, `dev_bad=0`, `xhist_bad=0`, 독 값 0, `xchg=ok`. "FENCE"는 launcher의 `FENCE of rank 3 … SIGKILL sent`(또는 `already ended; FENCED`), "FENCED"는 launcher의 `FENCED` 줄, "활성화"는 launcher의 `activation … ACCEPTED|REFUSED`.

## 1. 시행 수와 제외

- 본 실행 셀 28개(@gc 27, @gct 1)는 모두 계획 n을 채웠다. 시행 번호는 셀마다 빈틈 없이 n1부터다 `[측정: raw/*_meta.txt 358개]`.
- hold C10은 시간 한도로 세 시행을 건너뛰었고(`skipped.txt` 1–3행), 같은 이름의 다시 돈 hold C10-r2가 남은 13 시행을 채웠다(C10 22 + C10-r2 13 = 35; C10-r3, C10-r4는 새로 돈 시행 0). RG-gc-G1도 `mi4_kill3_ow_sampled` n5 하나를 RG-gc-G1-r2에서 채웠다 `[측정: hold_C10*.out의 "already done" 줄 수, meta의 hold 열]`.
- 원자료로 볼 때 제외할 시행은 본 실행 셀에 없다 `[측정]`: 링 live 줄(`the records go on the ring from now (live)`)이 @gc 시행 모두 rank 넷에 있음(@gct는 이 줄이 없는 빌드), 주입 줄이 장애 셀 모두 시행마다 하나, `resume_rc`가 0이 아닌 시행 0.
- 회귀(gin-mirror, gin-restore) 셀도 모두 cells_mi.json의 hold 계획 n을 채웠다. 거절 셀 일곱(시행 21)은 모든 rank가 설계대로 Resume 거절(`resume_rc=5`)이고 링 live rank 수는 0–4로 시행마다 다르다. `mi4_kill3_ow_sampled` 5/5는 예비의 `resume_rc=2`(복원 실패)로 끝났다(보고만 하는 셀) `[측정: trials_qa.csv resume_rcs, ring_live_ranks]`.

### 표 1. 시행 수

| 셀 | 계획 n | 실행 n | 시행 | hold | 링 live(rank 4개) | 주입 줄 | Resume 거절 |
|---|--:|--:|---|---|---|---|---|
| `gc4_credit_stall@gc` | 5 | 5 | n1–n5 | C11 | 5/5 | 5/5 | 0 |
| `gc4_fdhold_sock_kill3@gc` | 10 | 10 | n1–n10 | C3 | 10/10 | 10/10 | 0 |
| `gc4_fdhold_sock_kill3_noreport@gc` | 5 | 5 | n1–n5 | C6 | 5/5 | 5/5 | 0 |
| `gc4_fdhold_uverbs_kill3@gc` | 5 | 5 | n1–n5 | C5 | 5/5 | 5/5 | 0 |
| `gc4_freeze12000_fence@gc` | 5 | 5 | n1–n5 | C10 | 5/5 | 5/5 | 0 |
| `gc4_gpuhang12000_ctx1_fence@gc` | 5 | 5 | n1–n5 | C10+C10-r2 | 5/5 | 5/5 | 0 |
| `gc4_gpuhang12000_fence@gc` | 5 | 5 | n1–n5 | C10 | 5/5 | 5/5 | 0 |
| `gc4_gpuhang12000_waitpend_fence@gc` | 5 | 5 | n1–n5 | C10-r2 | 5/5 | 5/5 | 0 |
| `gc4_helper_freeze12000@gc` | 5 | 5 | n1–n5 | C10 | 5/5 | 5/5 | 0 |
| `gc4_kill3_noreport_nofdhold@gc` | 5 | 5 | n1–n5 | C6 | 5/5 | 5/5 | 0 |
| `gc4_kill3_ow@gc` | 10 | 10 | n1–n10 | C1 | 10/10 | 10/10 | 0 |
| `gc4_kill3_ow_nowitness@gc` | 5 | 5 | n1–n5 | C1 | 5/5 | 5/5 | 0 |
| `gc4_kill3_ow_spareabsent@gc` | 5 | 5 | n1–n5 | C1 | 5/5 | 5/5 | 0 |
| `gc4_mgmt_mute8@gc` | 5 | 5 | n1–n5 | C11 | 5/5 | 5/5 | 0 |
| `gc4_none_ow@gc` | 5 | 5 | n1–n5 | C1 | 5/5 | 없음(장애 없는 셀) | 0 |
| `gc4_none_probe@gc` | 10 | 10 | n1–n10 | C2 | 10/10 | 없음(장애 없는 셀) | 0 |
| `gc4_qperr_record@gc` | 5 | 5 | n1–n5 | C11 | 5/5 | 5/5 | 0 |
| `gc4_quiet12000@gc` | 5 | 5 | n1–n5 | C10-r2 | 5/5 | 5/5 | 0 |
| `gc4_rst_kill3@gc` | 10 | 10 | n1–n10 | C3 | 10/10 | 10/10 | 0 |
| `gc4_rstgap_live300@gc` | 5 | 5 | n1–n5 | C3 | 5/5 | 5/5 | 0 |
| `gc4_slow_duty@gc` | 5 | 5 | n1–n5 | C8 | 5/5 | 5/5 | 0 |
| `gc4_stop12000_fence@gc` | 10 | 10 | n1–n10 | C9 | 10/10 | 10/10 | 0 |
| `gc4_stop12000_none@gc` | 5 | 5 | n1–n5 | C10 | 5/5 | 5/5 | 0 |
| `gc4_stop1500@gc` | 10 | 10 | n1–n10 | C7 | 10/10 | 10/10 | 0 |
| `gc4_stop4000@gc` | 10 | 10 | n1–n10 | C7 | 10/10 | 10/10 | 0 |
| `gc4_stop8000@gc` | 10 | 10 | n1–n10 | C8 | 10/10 | 10/10 | 0 |
| `gc4_ud_drop_rejoin@gc` | 5 | 5 | n1–n5 | C11 | 5/5 | 5/5 | 0 |
| `gct4_mgmt_mute8@gct` | 5 | 5 | n1–n5 | C11 | 0/5 | 5/5 | 0 |


## 2. 대상 판정 (누가, 원인, 주입 → 판정)

표 2는 셀마다 시행 모두의 관측자별 첫 판정을 모은 최소–최대다(대표 시행 하나가 아님). `[측정: trials_qa.csv judges, judge_min, judge_max]`

- 모든 대상 셀에서 생존 rank 셋이 모두 스스로 판정했다. 예외는 `gc4_stop12000_none` n3–n5: rank 1만 판정하고 rank 0, 2는 rank 1의 확정된 중단 결정(`ABORT_DECIDED(rank 3, …, cause STALL_HELPER) of rank 1 … applied`)을 적용했다(예: `gc4_stop12000_none_gc_n3_r0.log` 390행, `_r2.log` 391행). 3절 `fdhold_uverbs_refuse` 행의 2026-11-18 결정 (가)대로 세면 판정을 마친 생존 rank는 셋 모두다.
- 원인은 셀마다 하나로 모였다: kill 셀 FIN+STALE, 증인 끈 kill과 fd 보관 kill EXITED, READ 실패 셀 NORESP, SIGSTOP과 freeze 셋 STALL_HELPER, GPU hang 셋 STALL(문맥 1 셀의 판정 줄 15개 모두 `ctx=1`).
- 증인 FIN(또는 RST 셀의 `ECONNRESET`) 줄 → 같은 rank의 판정 줄: `gc4_kill3_ow` 20.647–21.891 ms(30/30이 W–W + 2), `gc4_rst_kill3` 20.766–21.018 ms(30/30), rdma 빌드 gin-mirror kill 셀 일곱 20.129–22.038 ms. W + 2 ms를 넘은 판정은 `mi4_seg_32k` n4 r1 하나(22.038 ms)다 `[측정: finjudge.py]`.
- 시각 띠와 견줌: kill 확인 창 20.2–23.5 ms, 증인 끈 kill EXITED 95.1–98.3 ms(띠 40–200), fd 보관 kill EXITED 53.8–55.4 ms(띠 40–200), READ 실패 3 643.4–3 825.5 ms(띠 3 500–4 500), 물려받은 매핑 셀 10 006.4–10 083.4 ms(띠 10 000–10 500), 긴 SIGSTOP 10 005.6–10 094.2 ms(띠 10 000–10 300), freeze 10 005.5–10 101.9 ms와 helper freeze 10 003.6–10 102.7 ms(띠 10 000–10 300), GPU hang 셋 10 005.2–10 104.5 ms(띠 10 000–10 500). 모두 띠 안이다.
- READ 실패 셀은 시행마다 판정 앞에 `probe of rank 3 timed out (no CQE in 500 ms)` 줄이 생존 rank마다 하나(3개)다. 물려받은 매핑 셀은 판정 앞 READ 실패 줄 0이다 `[측정: probe_to_before_judge, readfail_before_judge]`.
- 판정 없는 셀(장애 없음 둘, 짧은 SIGSTOP 셋, 느린 상대, 조용한 계산, 관리망 끊김 둘, QP 오류, credit, RST gap)은 시행 모두 판정 0이다. 의심 줄은 `gc4_stop4000`, `gc4_stop8000`에서 시행마다 3개, 나머지는 0이다(`gc4_quiet12000` 어느 rank에 대한 의심도 0) `[측정: suspect_any_n]`.
- 기다리는 rank 셀(`gc4_gpuhang12000_waitpend_fence`)에서 rank 1 대상 판정 줄 0, rank 1의 FENCE/FENCED 0, 기다림 줄이 이름 댄 상대는 rank 3 하나, `wait ended (progress: it left the stalled …)` 시행마다 2줄, rank 1 kv `waitpend=1`, `waitpend end … result=satisfied` 5/5다 `[측정: extra_qa.py]`.
- 참고(판정과 무관): `gc4_rstgap_live300`의 주입 줄은 다섯 시행 모두 `test switch RST_GAP: 0 socket(s) reset, listener closed for 0 ms (the line only in this build; asked 3000:300)`이다(예: `gc4_rstgap_live300_gc_n1_r1.log` 490행). 이 빌드에서는 RST와 포트 닫힘이 실제로 나지 않았다는 뜻으로 읽힌다 `[추론]`.

### 표 2. 대상 판정

| 셀 | 판정한 생존 rank(시행 수) | 원인 | 주입 → 판정 ms (관측자별 첫 판정, 최소–최대) | 퍼짐 ms | 주입 줄 |
|---|---|---|---|---|---|
| `gc4_fdhold_sock_kill3@gc` | 3명 10 | EXITED 10 | 53.8–55.4 | 0.0–0.2 | killed |
| `gc4_fdhold_sock_kill3_noreport@gc` | 3명 5 | STALL_HELPER 5 | 10006.4–10083.4 | 1.9–4.8 | killed |
| `gc4_fdhold_uverbs_kill3@gc` | 3명 5 | EXITED 5 | 48.3–52.0 | 0.0–0.6 | killed |
| `gc4_freeze12000_fence@gc` | 3명 5 | STALL_HELPER 5 | 10005.5–10101.9 | 2.3–95.6 | switch |
| `gc4_gpuhang12000_ctx1_fence@gc` | 3명 5 | STALL 5 | 10026.6–10096.5 | 3.2–8.1 | gpuhang |
| `gc4_gpuhang12000_fence@gc` | 3명 5 | STALL 5 | 10006.5–10104.5 | 2.9–98.0 | gpuhang |
| `gc4_gpuhang12000_waitpend_fence@gc` | 3명 5 | STALL 5 | 10005.2–10103.2 | 1.1–96.2 | gpuhang |
| `gc4_helper_freeze12000@gc` | 3명 5 | STALL_HELPER 5 | 10003.6–10102.7 | 1.4–97.6 | switch |
| `gc4_kill3_noreport_nofdhold@gc` | 3명 5 | NORESP 5 | 3643.4–3825.5 | 27.4–30.8 | killed |
| `gc4_kill3_ow@gc` | 3명 10 | FIN+STALE 10 | 20.8–22.9 | 0.0–2.1 | killed |
| `gc4_kill3_ow_nowitness@gc` | 3명 5 | EXITED 5 | 95.1–98.3 | 0.0–0.1 | killed |
| `gc4_kill3_ow_spareabsent@gc` | 3명 5 | FIN+STALE 5 | 20.9–22.0 | 0.1–1.1 | killed |
| `gc4_rst_kill3@gc` | 3명 10 | FIN+STALE 10 | 20.9–21.9 | 0.0–0.9 | switch |
| `gc4_stop12000_fence@gc` | 3명 10 | STALL_HELPER 10 | 10005.6–10094.2 | 0.7–8.0 | stop |
| `gc4_stop12000_none@gc` | 1명 3, 3명 2 | STALL_HELPER 5 | 10019.2–10091.5 | 0.0–1.4 | stop |
| `gc4_ud_drop_rejoin@gc` | 3명 5 | FIN+STALE 5 | 20.7–22.0 | 0.1–1.2 | killed |
| `mi4_kill1_ow@gc` | 3명 5 | FIN+STALE 5 | 20.7–21.0 | 0.1–0.3 | killed |
| `mi4_kill2_kill3_ow@gc` | 3명 5 | FIN+STALE 5 | 20.2–22.7 | 0.2–1.2 | die |
| `mi4_kill3_ckpt_ow@gc` | 3명 5 | FIN+STALE 5 | 20.3–23.5 | 0.1–3.0 | switch |
| `mi4_kill3_ow@gc` | 3명 10 | FIN+STALE 10 | 20.7–22.5 | 0.0–1.7 | killed |
| `mi4_kill3_ow@gct` | 3명 10 | FIN 10 | 0.2–0.3 | 0.0–0.1 | killed |
| `mi4_kill3_ow_nomirror@gc` | 3명 5 | FIN+STALE 5 | 20.3–22.4 | 0.1–1.2 | killed |
| `mi4_kill3_ow_sampled@gc` | 3명 5 | FIN+STALE 5 | 20.4–23.5 | 0.3–2.9 | killed |
| `mi4_overflow@gc` | 3명 5 | FIN+STALE 5 | 20.8–22.0 | 0.1–1.1 | killed |
| `mi4_pull@gc` | 3명 5 | FIN+STALE 5 | 20.5–22.2 | 0.1–1.2 | killed |
| `mi4_seg_128k@gc` | 3명 5 | FIN+STALE 5 | 20.8–21.9 | 0.1–1.1 | killed |
| `mi4_seg_32k@gc` | 3명 5 | FIN+STALE 5 | 20.6–23.2 | 0.1–1.9 | killed |
| `mi4_seg_4k@gc` | 3명 5 | FIN+STALE 5 | 20.8–21.3 | 0.1–0.3 | killed |
| `mi4_train_kill2_kill3@gc` | 3명 5 | FIN+STALE 5 | 20.5–21.5 | 0.2–0.9 | die |
| `mi4_train_kill3@gc` | 3명 10 | FIN+STALE 10 | 20.3–21.5 | 0.0–1.2 | die |
| `rs4_kill1@gc` | 3명 5 | FIN+STALE 5 | 20.5–21.9 | 0.1–1.0 | killed |
| `rs4_kill3@gc` | 3명 10 | FIN+STALE 10 | 20.5–21.6 | 0.1–1.0 | killed |
| `rs4_kill3_ckpt@gc` | 3명 5 | FIN+STALE 5 | 20.9–22.6 | 0.0–1.8 | switch |
| `rs4_kill3_mion@gc` | 3명 5 | FIN+STALE 5 | 20.8–22.2 | 0.1–1.0 | killed |
| `rs4_kill3_nospare@gc` | 3명 5 | FIN+STALE 5 | 20.5–21.8 | 0.0–1.2 | killed |
| `rs4_kill3_spareabsent@gc` | 3명 5 | FIN+STALE 5 | 20.5–21.9 | 0.0–1.3 | killed |


## 3. 펜스 순서와 복원 시간

표 3의 범위는 셀의 모든 시행에 걸친 최소–최대다. `[측정: trials_qa.csv fence_order, la_fenced, restore_ms, judge_to_last_pub, kill_to_last_pub]`

- 펜스를 거친 시행 모두 FENCE → FENCED → 활성화(ACCEPTED) → 첫 게시 순서이고, FENCED 전 활성화 0이다. FIN 없는 두 셀(`NO_EXIT_REPORT`)은 launcher가 이미 끝남을 봐서 `FENCE … already ended; FENCED`(예: `gc4_kill3_noreport_nofdhold_gc_n1_launcher_sunny.log` 25행) 한 줄로 FENCED가 났다.
- 증인 끈 kill과 fd 보관 kill은 판정이 launcher EXITED라 FENCE 줄 없이 활성화됐다.
- 예비 없음 셀(`gc4_kill3_ow_spareabsent`)은 FENCE → FENCED(SIGKILL 뒤 148.7–156.4 ms) → `activation … REFUSED (the spare exited)` 5/5, FENCED → 첫 fallback 줄(given up, declined) 2.2–2.9 ms, 생존 rank 대기는 판정 + 2 000 ms의 degraded 해제로 주입 뒤 2 178.3–2 189.7 ms에 풀렸다.
- 거절 셀의 풀림: `gc4_fdhold_uverbs_kill3` 주입 뒤 2 051.2–2 057.1 ms(생존 셋 모두 `released=1`, `exit=4`), `gc4_stop12000_none` 12 022.0–15 804.9 ms(생존 셋과 SIGCONT 뒤 rank 3까지 4 프로세스 모두 `released=1`).
- **freeze 셀 n1, n3, n5와 helper freeze n5**: 생존 셋이 `restored as incarnation 1` 줄까지 냈으나(예: `gc4_freeze12000_fence_gc_n1_r0.log` 2420행) 되살린 rank의 INJECTED가 오지 않아 hold 시작 20 996–20 998 ms 뒤 `the restore of rank 3 … is given up (no INJECTED from the revived rank before the deadline after the restore round's publish)`(같은 파일 2428행), 그 2 000 ms 뒤 degraded 해제로 끝났다. 네 시행 모두 생존 rank 하나(rank 1, 대상과 같은 sunny)가 다른 둘보다 약 95 ms(probe 한 주기) 늦게 판정했고, 그렇게 늦은 판정이 없던 같은 두 셀의 여섯 시행은 모두 복원됐다(4/4 대 0/6) `[측정]`. 늦은 판정이 원인인지는 `[미확인]`(GPU hang 셀에서는 같은 약 96–98 ms 퍼짐에도 복원됨).

### 표 3. 펜스 순서와 복원

| 셀 | 펜스 순서 | 주입 → FENCED ms | 활성화 | 첫 판정 → 마지막 restored ms | 첫 판정 → 마지막 published ms | 주입 → 마지막 published ms | 창 검사(줄 3, 바뀐 칸 0) |
|---|---|---|---|---|---|---|---|
| `gc4_fdhold_sock_kill3@gc` | EXITED(펜스 없음) 10 | - | ACCEPTED 10 | 70.9–81.6 | 70.0–80.7 | 124.3–135.1 | 10/10 |
| `gc4_fdhold_sock_kill3_noreport@gc` | FENCE → FENCED → ACT → PUB 5 | 10015.0–10089.7 | ACCEPTED 5 | 74.2–77.3 | 73.4–77.2 | 10079.8–10156.1 | 5/5 |
| `gc4_fdhold_uverbs_kill3@gc` | EXITED(펜스 없음) 5 | - | - | - | - | - | 0/5 |
| `gc4_freeze12000_fence@gc` | FENCE → FENCED → ACT → PUB 5 | 10128.3–10222.8 | ACCEPTED 5 | 194.5–284.6 | 193.6–283.7 | 10199.5–10293.9 | 5/5 |
| `gc4_gpuhang12000_ctx1_fence@gc` | FENCE → FENCED → ACT → PUB 5 | 10137.9–10201.6 | ACCEPTED 5 | 174.9–179.8 | 174.1–178.9 | 10203.0–10266.4 | 5/5 |
| `gc4_gpuhang12000_fence@gc` | FENCE → FENCED → ACT → PUB 5 | 10123.5–10210.2 | ACCEPTED 5 | 174.0–268.0 | 173.2–268.0 | 10187.9–10274.5 | 5/5 |
| `gc4_gpuhang12000_waitpend_fence@gc` | FENCE → FENCED → ACT → PUB 5 | 10122.5–10210.4 | ACCEPTED 5 | 174.1–268.9 | 174.0–268.9 | 10187.1–10275.8 | 5/5 |
| `gc4_helper_freeze12000@gc` | FENCE → FENCED → ACT → PUB 5 | 10127.8–10219.2 | ACCEPTED 5 | 193.2–284.7 | 192.3–283.9 | 10197.9–10288.9 | 5/5 |
| `gc4_kill3_noreport_nofdhold@gc` | FENCE → FENCED → ACT → PUB 5 | 3677.8–3832.0 | ACCEPTED 5 | 98.1–101.2 | 96.2–100.2 | 3743.5–3895.2 | 5/5 |
| `gc4_kill3_ow@gc` | FENCE → FENCED → ACT → PUB 10 | 100.5–105.6 | ACCEPTED 10 | 144.4–150.7 | 144.2–150.2 | 165.1–171.1 | 10/10 |
| `gc4_kill3_ow_nowitness@gc` | EXITED(펜스 없음) 5 | - | ACCEPTED 5 | 69.6–70.3 | 68.7–70.1 | 164.0–168.4 | 5/5 |
| `gc4_kill3_ow_spareabsent@gc` | FENCE → FENCED 5 | 175.1–183.7 | REFUSED the spare exited 5 | - | - | - | 5/5 |
| `gc4_rst_kill3@gc` | FENCE → FENCED → ACT → PUB 10 | 100.8–106.2 | ACCEPTED 10 | 145.3–160.0 | 145.3–159.1 | 166.2–180.1 | 10/10 |
| `gc4_stop12000_fence@gc` | FENCE → FENCED → ACT → PUB 10 | 10113.5–10198.7 | ACCEPTED 10 | 170.5–179.0 | 170.1–178.7 | 10179.4–10262.1 | 10/10 |
| `gc4_ud_drop_rejoin@gc` | FENCE → FENCED → ACT → PUB 5 | 101.8–106.3 | ACCEPTED 5 | 347.8–355.8 | 347.0–354.9 | 367.8–375.8 | 5/5 |
| `mi4_kill1_ow@gc` | FENCE → FENCED → ACT → PUB 5 | 103.2–104.8 | ACCEPTED 5 | 147.8–154.5 | 147.8–150.2 | 168.5–171.0 | 5/5 |
| `mi4_kill2_kill3_ow@gc` | FENCE → FENCED → ACT → PUB 5 | 126.3–133.7 | ACCEPTED 5 | 176.0–183.4 | 171.0–178.7 | 191.1–199.8 | 5/5 |
| `mi4_kill3_ckpt_ow@gc` | FENCE → FENCED → ACT → PUB 5 | 99.4–108.2 | ACCEPTED 5 | 125.8–146.3 | 124.9–146.2 | 145.6–167.2 | 5/5 |
| `mi4_kill3_ow@gc` | FENCE → FENCED → ACT → PUB 10 | 100.2–105.5 | ACCEPTED 10 | 144.2–151.2 | 144.2–150.4 | 165.2–171.1 | 10/10 |
| `mi4_kill3_ow_nomirror@gc` | FENCE → FENCED → ACT → PUB 5 | 98.3–103.1 | ACCEPTED 5 | 126.7–144.3 | 126.0–143.6 | 146.6–163.9 | 5/5 |
| `mi4_kill3_ow_sampled@gc` | FENCE → FENCED → ACT 5 | 100.2–102.5 | ACCEPTED 5 | - | - | - | 5/5 |
| `mi4_overflow@gc` | EXITED(펜스 없음) 5 | - | - | - | - | - | 0/5 |
| `mi4_pull@gc` | FENCE → FENCED → ACT → PUB 5 | 97.4–101.2 | ACCEPTED 5 | 141.7–146.0 | 140.8–146.0 | 162.0–166.5 | 5/5 |
| `mi4_seg_128k@gc` | FENCE → FENCED → ACT → PUB 5 | 113.2–115.7 | ACCEPTED 5 | 158.4–162.2 | 158.0–161.3 | 178.9–182.3 | 5/5 |
| `mi4_seg_32k@gc` | FENCE → FENCED → ACT → PUB 5 | 104.6–109.8 | ACCEPTED 5 | 135.9–154.6 | 135.9–153.7 | 156.4–175.1 | 5/5 |
| `mi4_seg_4k@gc` | FENCE → FENCED → ACT → PUB 5 | 103.4–107.1 | ACCEPTED 5 | 147.6–153.5 | 147.5–152.7 | 168.4–173.7 | 5/5 |
| `mi4_train_kill2_kill3@gc` | FENCE → FENCED → ACT → PUB 5 | 189.2–201.3 | ACCEPTED 5 | 241.2–264.5 | 241.1–264.4 | 261.7–285.3 | 5/5 |
| `mi4_train_kill3@gc` | FENCE → FENCED → ACT → PUB 10 | 167.6–171.9 | ACCEPTED 10 | 215.7–237.9 | 214.8–237.8 | 235.2–258.3 | 10/10 |
| `rs4_kill1@gc` | FENCE → FENCED → ACT → PUB 5 | 99.4–103.7 | ACCEPTED 5 | 129.7–135.4 | 127.4–131.5 | 148.1–153.1 | 5/5 |
| `rs4_kill3@gc` | FENCE → FENCED → ACT → PUB 10 | 98.8–103.7 | ACCEPTED 10 | 127.6–134.6 | 126.9–133.9 | 147.4–154.5 | 10/10 |
| `rs4_kill3_ckpt@gc` | FENCE → FENCED → ACT → PUB 5 | 100.9–106.4 | ACCEPTED 5 | 122.0–135.7 | 121.3–135.7 | 142.2–156.5 | 5/5 |
| `rs4_kill3_mion@gc` | FENCE → FENCED → ACT → PUB 5 | 101.8–106.9 | ACCEPTED 5 | 147.4–151.1 | 147.4–151.0 | 168.3–173.1 | 5/5 |
| `rs4_kill3_nospare@gc` | EXITED(펜스 없음) 5 | - | - | - | - | - | 0/5 |
| `rs4_kill3_spareabsent@gc` | EXITED(펜스 없음) 5 | - | - | - | - | - | 0/5 |


## 4. 데이터 같음과 장치 대기 결과

### 표 4. 데이터와 대기 결과

| 셀 | 데이터 같음 | 되살린 rank 끝까지 | 대기 결과 | 끝 xchg | 생존 rank 풀림 시각(주입 뒤 ms) | FENCED → 첫 fallback 줄 ms |
|---|---|---|---|---|---|---|
| `gc4_credit_stall@gc` | 5/5 | -(예비 안 씀) | 판정 없음, 끝까지 5 | ok 5 | - | - |
| `gc4_fdhold_sock_kill3@gc` | 10/10 | 10/10 | held 10 | ok 10 | - | - |
| `gc4_fdhold_sock_kill3_noreport@gc` | 5/5 | 5/5 | held 5 | ok 5 | - | - |
| `gc4_fdhold_uverbs_kill3@gc` | 0/5 | -(예비 안 씀) | released 3 5 | released 5 | 2051.2–2057.1 | - |
| `gc4_freeze12000_fence@gc` | 2/5 | 2/5 | held 2, held → released 3 3 | ok 2, released 3 | 33009.2–33015.2 | 20786.7–20791.5 |
| `gc4_gpuhang12000_ctx1_fence@gc` | 5/5 | 5/5 | held 5 | ok 5 | - | - |
| `gc4_gpuhang12000_fence@gc` | 5/5 | 5/5 | held 5 | ok 5 | - | - |
| `gc4_gpuhang12000_waitpend_fence@gc` | 5/5 | 5/5 | held 5 | ok 5 | - | - |
| `gc4_helper_freeze12000@gc` | 4/5 | 4/5 | held 4, held → released 3 1 | ok 4, released 1 | 33009.4–33012.2 | 20787.3 |
| `gc4_kill3_noreport_nofdhold@gc` | 5/5 | 5/5 | held 5 | ok 5 | - | - |
| `gc4_kill3_ow@gc` | 10/10 | 10/10 | held 10 | ok 10 | - | - |
| `gc4_kill3_ow_nowitness@gc` | 5/5 | 5/5 | held 5 | ok 5 | - | - |
| `gc4_kill3_ow_spareabsent@gc` | 0/5 | -(예비를 실행기가 끝냄) | released 3 5 | released 5 | 2178.3–2189.7 | 2.2–2.9 |
| `gc4_mgmt_mute8@gc` | 5/5 | -(예비 안 씀) | 판정 없음, 끝까지 5 | ok 5 | - | - |
| `gc4_none_ow@gc` | 5/5 | -(예비 안 씀) | 판정 없음, 끝까지 5 | ok 5 | - | - |
| `gc4_none_probe@gc` | 10/10 | -(예비 안 씀) | 판정 없음, 끝까지 10 | ok 10 | - | - |
| `gc4_qperr_record@gc` | 5/5 | -(예비 안 씀) | 판정 없음, 끝까지 5 | ok 5 | - | - |
| `gc4_quiet12000@gc` | 5/5 | -(예비 안 씀) | 판정 없음, 끝까지 5 | ok 5 | - | - |
| `gc4_rst_kill3@gc` | 10/10 | 10/10 | held 10 | ok 10 | - | - |
| `gc4_rstgap_live300@gc` | 5/5 | -(예비 안 씀) | 판정 없음, 끝까지 5 | ok 5 | - | - |
| `gc4_slow_duty@gc` | 5/5 | -(예비 안 씀) | 판정 없음, 끝까지 5 | ok 5 | - | - |
| `gc4_stop12000_fence@gc` | 10/10 | 10/10 | held 10 | ok 10 | - | - |
| `gc4_stop12000_none@gc` | 0/5 | -(예비 안 씀) | released 3 5 | released 5 | 12022.0–15804.9 | - |
| `gc4_stop1500@gc` | 10/10 | -(예비 안 씀) | 판정 없음, 끝까지 10 | ok 10 | - | - |
| `gc4_stop4000@gc` | 10/10 | -(예비 안 씀) | 판정 없음, 끝까지 10 | ok 10 | - | - |
| `gc4_stop8000@gc` | 10/10 | -(예비 안 씀) | 판정 없음, 끝까지 10 | ok 10 | - | - |
| `gc4_ud_drop_rejoin@gc` | 5/5 | 5/5 | held 5 | ok 5 | - | - |
| `gct4_mgmt_mute8@gct` | 5/5 | -(예비 안 씀) | 판정 없음, 끝까지 5 | ok 5 | - | - |

"대기 결과"의 held는 hold가 시작되고 restored 줄까지 간 것, released k는 생존 rank k개의 kv `released=1`이다. `[측정: trials_qa.csv data_equal, revived_done, wait_outcome, xchg_set]`

## 5. 회귀

**gin-mirror 셀 @gc** (복원 시간 = 첫 판정 → 마지막 restored, 범위는 셀의 모든 시행) `[측정]`

| 셀 | n | 데이터 같음 | 첫 판정 → 마지막 restored ms | 첫 판정 → 마지막 게시 ms | 주입 → 마지막 게시 ms |
|---|--:|---|---|---|---|
| `mi4_kill3_ow` | 10 | 10/10 | 144.2–151.2 | 144.2–150.4 | 165.2–171.1 |
| `mi4_kill1_ow` | 5 | 5/5 | 147.8–154.5 | 147.8–150.2 | 168.5–171.0 |
| `mi4_kill3_ckpt_ow` | 5 | 5/5 | 125.8–146.3 | 124.9–146.2 | 145.6–167.2 |
| `mi4_seg_4k` | 5 | 5/5 | 147.6–153.5 | 147.5–152.7 | 168.4–173.7 |
| `mi4_seg_32k` | 5 | 5/5 | 135.9–154.6 | 135.9–153.7 | 156.4–175.1 |
| `mi4_seg_128k` | 5 | 5/5 | 158.4–162.2 | 158.0–161.3 | 178.9–182.3 |
| `mi4_pull` | 5 | 5/5 | 141.7–146.0 | 140.8–146.0 | 162.0–166.5 |
| `rs4_kill3_mion` | 5 | 5/5 | 147.4–151.1 | 147.4–151.0 | 168.3–173.1 |
| `mi4_train_kill3` | 10 | 10/10 | 215.7–237.9 | 214.8–237.8 | 235.2–258.3 |
| `mi4_kill3_ow_nomirror` | 5 | 0/5(`xchg=bad`, mirror 끔 대조) | 126.7–144.3 | 126.0–143.6 | 146.6–163.9 |
| `mi4_kill3_ow_sampled` | 5 | 0/5(예비 `resume_rc=2`, 풀림) | 복원 없음 | - | - |
| `mi4_overflow` | 5 | 0/5(FIN+STALE 판정 뒤 복원 안 함, 생존 셋 풀림) | 복원 없음 | - | - |
| 장애 없는 셀(`mi4_none_ow`, `mi4_train_none`, `mi4_int_10/20/40`, `mi4_pull_none`) | 5, 5, 3×3, 3 | 모두 같음 | - | - | - |

- 둘째 죽음: `mi4_kill2_kill3_ow` 5/5와 `mi4_train_kill2_kill3` 5/5 모두 둘째 대상(rank 3)을 생존 셋(rank 0, 1, 되살린 rank 2)이 둘째 die 줄 뒤 20.3–22.0 ms(4 KiB), 20.4–21.4 ms(학습)에 FIN+STALE로 판정했고 복원, 데이터 같음이다. 복원 시간(첫 판정 → 마지막 restored): 첫 죽음 176.0–183.4 ms, 241.2–264.5 ms; 둘째 죽음 128.6–159.7 ms, 238.0–246.5 ms. 상한(2 000 ms, 학습 1 000 ms) 안이다.
- **@gct** `mi4_kill3_ow` 10/10: 원인 FIN(kill 뒤 0.2–0.3 ms), 펜스 없음, 복원 75.6–174.3 ms, 데이터 같음 10/10.
- gin-restore 셀 @gc: `rs4_kill3` 10/10, `rs4_kill3_ckpt` 5/5, `rs4_kill1` 5/5, `rs4_none` 5/5, `rs4_none_off` 5/5, `rs4_none_mion` 5/5 데이터 같음; `rs4_kill3_nospare`, `rs4_kill3_spareabsent`는 FIN+STALE 판정 뒤 복원 없이 fail-fast(생존 셋 `released=1`) 5/5씩.
- **gin-remaining `reg/`** (시행 20): 끝 줄 `[rankN] DONE outcome=…` `[측정: reg/*_r?.log]`

| 행 | n | rank 0–2 | rank 3 |
|---|--:|---|---|
| `reg_mr4_none` | 5 | `outcome=ok exit=0 tx_ok=3/3 rx_ok=3/3` 15/15 | 같음 5/5 |
| `reg_mr4_none_hold` | 5 | 같음 15/15 | 같음 5/5 |
| `reg_rm4_kill3_untimed` | 5 | `outcome=device_error exit=4 tx_ok=2/3 rx_ok=0/3` 15/15 | DONE 줄 없음(kill된 rank, meta `r3rc=255`) |
| `reg_rm4_kill3_untimed_hold` | 5 | 같음 15/15 | DONE 줄 없음 |

## 6. 비용 (probe-on 대 probe-off, `lat4k`)

`lat_p50_us`는 r0.kv 값이고 `lat_raw.csv.gz` 150 000개에서 다시 낸 중앙값과 0.01 µs 안에서 같다. probe 설정은 라이브러리 줄 `probe_ms=0`(off), `probe_ms=100`(on)으로 확인했다 `[측정: cost_qa.py]`.

| 팔 이름(받는 쪽) | 팔 | k1 | k2 | k3 | k4 | k5 | k6 | 중앙값 µs |
|---|---|--:|--:|--:|--:|--:|--:|--:|
| rain | probe-off | 13.31 | 12.29 | 13.31 | 13.31 | 13.31 | 13.31 | 13.310 |
| rain | probe-on | 13.31 | 13.31 | 13.31 | 13.31 | 13.31 | 13.31 | 13.310 |
| sunny | probe-off | 12.58 | 12.58 | 12.90 | 12.90 | 12.86 | 12.83 | 12.845 |
| sunny | probe-on | 12.86 | 12.90 | 12.77 | 12.86 | 12.86 | 12.61 | 12.860 |

차: sunny(판정 팔) +0.015 µs = +0.12 %(문턱 2 % 안), rain(보고만) +0.000 µs = 0.00 %. sunny 팔의 r0은 rain 노드에서 돌았다(로그 머리 `rain:`).

## 7. STOP_left 두 건

- `stops/STOP_left.C1-154158.txt`: "hold C1: 1 test process(es) left after the hold"; `hold_C1.out` 105행 같은 줄, `stops/LEFT_STREAK.C1.txt`는 0. `chain.out` 3–25행에서 C2 이후가 "STOP file present"로 건너뛰어졌고 26행(15:43:43)에서 C2부터 다시 돌았다.
- `stops/STOP_left.RG-gc-G2-174718.txt`: "hold RG-gc-G2: 3 test process(es) left after the hold"; `hold_RG-gc-G2.out` 53행, `chain.out` 60–65행 건너뜀, 66행(17:48:24) RG-gc-R1부터 다시 돎.
- 두 hold 출력 모두 남은 프로세스가 무엇인지 적지 않았고, 그 hold의 마지막 시행 launcher 로그는 모든 rank의 `left (LEAVING, then the group ended)`와 `trial_end`로 끝난다. 어떤 프로세스였는지는 `[미확인]`.
- 시행 자신의 `left=` 열: meta 402개(raw 358, reg 20, 비용 24) 모두 `left=0`, raw 358개 모두 `left_stopped=0`, `left_fdhold=0`이다. 비어 있지 않은 `cleanup.out` 0개 `[측정]`.

## 8. hold 길이 (긴 hold의 lane 예측과 관련)

hold 시작 줄 → 그 생존 rank의 `INJECTED from rank N … gate_odd_ms` 줄 또는 포기(given up) 줄 `[측정: hold_qa.py, 시행 170]`.

- 1 000 ms를 넘은 hold는 넷: `gc4_freeze12000_fence` n1(20 996.7 ms), n3(20 996.2), n5(20 996.8), `gc4_helper_freeze12000` n5(20 997.5). 넷 모두 데이터 같음 0이다.
- 나머지 166 시행의 hold 최대는 91.2–426.5 ms다(`gc4_ud_drop_rejoin` 397.3–426.5 ms가 가장 김). hold 줄이 있는 시행은 195개이고, INJECTED 줄이 없는 mirror 끈 셀 25 시행(`rs4_kill3`, `rs4_kill3_ckpt`, `rs4_kill1`, `mi4_kill3_ow_nomirror`)은 restored 줄의 "N ms after the hold start"로 보면 120.1–151.0 ms다.

## 9. 채점기와 비교

내 숫자를 다 낸 뒤 `SCORE.md`(766행)와 `trials_scored.csv`(402 행)를 읽었다. 열 비교는 `compare_qa.py`, `compare2_qa.py`이고 결과는 `compare_out.txt`다. 시각은 0.15 ms 넘게 다르면 어긋남으로 셌다.

### 9.1 예측별 판정

| 예측 (ID) | 채점기 | 내 재계산 | 같음 |
|---|---|---|---|
| kill의 RDMA 판정 (`kill_judge_rdma`) | 맞음 | 아홉 셀 모두 3명 FIN+STALE; FIN → 판정이 W–W + 2 밖인 시행은 `mi4_seg_32k` n4 하나(내 기준점으로 2.04 ms), 그 셀도 4/5 ≥ 4 | 맞음, 같음 |
| RST 판정 (`rst_judge_rdma`) | 맞음 | 10/10, `ECONNRESET` → 판정 20.766–21.018 ms | 같음 |
| 살아 있는 상대의 RST (`rstgap_live_rdma`) | 맞음 | 판정 0, 거절 0, 5/5(주입 줄은 "0 socket(s) reset", 2절) | 같음 |
| FIN 없는 죽음, launcher 보고 (`finless_exit_report`) | 맞음 | EXITED 53.8–55.4 ms, 복원, 데이터 10/10 | 같음 |
| FIN 없는 죽음, READ 실패 (`finless_read_fail`) | 맞음 | NORESP 3 643.4–3 825.5 ms, 시한 줄 3, FENCED, 복원, 데이터 5/5 | 같음 |
| 물려받은 매핑의 멈춤 판정 (`fdhold_sock_helper_stall`) | 맞음 | STALL_HELPER 10 006.4–10 083.4 ms, READ 실패 0, 5/5 | 같음 |
| uverbs fd까지 쥐면 거절 (`fdhold_uverbs_refuse`) | 맞음 | EXITED 3명, 복원 0, 거절 3, 풀림 3, 5/5 | 같음 |
| 짧은 멈춤 투명 (`stop_transparent`) | 맞음 | 판정 0, 데이터 30/30, 4 000과 8 000 의심 줄 시행마다 3 | 같음 |
| 느린 상대 (`slow_no_judge`) | 맞음 | 의심 0, 판정 0, 5/5 | 같음 |
| 긴 멈춤의 펜스 뒤 복원 (`stall_fence_restore`) | 맞음 | 10/10 | 같음 |
| 긴 멈춤, 펜스 끔 (`stall_none_refuse`) | 맞음 | 5/5(3 시행은 판정 1 + 결정 적용 2) | 같음 |
| 살아서 도는 프로세스의 펜스 (`freeze_fence_restore`) | 재검토(안전성 항 3/5) | 2/5, 데이터 같음 거짓 3(n1, n3, n5) | 같음 |
| helper만 멈춘 rank (`helper_stall_fence`) | 재검토(안전성 항 1/5) | 4/5, n5가 데이터, 대기, 되살린 rank 셋 모두 거짓 | 같음 |
| 멈춘 GPU의 펜스 (`gpuhang_fence_restore`) | 맞음 | 5/5, 5/5 | 같음 |
| 문맥 0 밖 GPU 멈춤 (`gpuhang_ctx1_fence_restore`) | 맞음 | 5/5, 판정 줄 모두 `ctx=1` | 같음 |
| 조용한 긴 계산 (`quiet_compute_no_judge`) | 맞음 | 의심, 판정, hold 0, 예비 안 씀, 데이터 5/5; `quiet_periods`는 다시 세지 않음 | 센 항은 같음 |
| 기다리는 정상 rank (`waiter_not_judged`) | 맞음 | 5/5 | 같음 |
| 관리망 끊김 (`mgmt_mute_transparent`) | 맞음 | 판정 0, 기록 QP 다시 짝 0, `records_lost=0`, 데이터 5/5; 끊김 중 체크포인트 수는 다시 세지 않음 | 센 항은 같음 |
| 같은 끊김의 옛 길 (`mgmt_mute_tcp`) | 맞음 | 판정 0, 데이터 5/5 | 같음 |
| 기록 QP 오류 (`qp_err_repair`) | 맞음 | 판정 0, rank 1의 `PAIR(record, gen 2)` 시행마다 1, 데이터 5/5; 세대 차 열은 다시 세지 않음 | 센 항은 같음 |
| 잃은 REJOIN (`ud_drop_rejoin`) | 맞음 | DROP_UD 1, REJOIN 받음 생존 rank마다 1, FAIL 0, 복원 5/5 | 같음 |
| credit 멈춤 (`credit_stall_no_loss`) | 맞음 | 판정 0, `rnr=0`, `records_lost=0`, `records_dup=0`, 데이터 5/5 | 같음 |
| 예비 없음의 곧바른 fallback (`spare_absent_refused`) | 맞음 | REFUSED(the spare exited) 5/5, FENCED → fallback 2.2–2.9 ms, 풀림 3 | 같음 |
| 증인 없는 kill (`kill_no_witness`) | 맞음 | EXITED 95.1–98.3 ms, 판정 → 마지막 게시 68.7–70.1 ms, 5/5 | 같음 |
| 복원 시간과 관문 (`restore_time_rdma`) | 틀림 | `mi4_kill3_ckpt_ow` 1/5, 나머지 여덟 셀 모두 통과(10절) | 같음 |
| 장애 없음 (`none_probe_clean`) | 맞음 | 판정, 의심, hold 0, 입력 멈춤 최대 6.6–7.5, 16.4–17.3, 8.7–9.2 ms(≤ 20); READ 성공률과 박동 간격은 다시 세지 않음 | 센 항은 같음 |
| 비용 (`cost_probe_lat4k`) | 맞음(+0.12 %) | +0.12 %, 중앙값 넷 모두 같음 | 같음 |
| **긴 hold의 lane (`long_hold_lane`)** | **자료 없음(실패 아님)** | **hold > 1 000 ms 시행 4개, 넷 모두 데이터 같음 0 → 이 행의 "DISARM이 있어도 데이터는 같아야 함"이 4/4 거짓** | **다름** |
| 회귀 셋 (`regression_tcp`, `regression_rdma`, `regression_rdma_mirror_off`) | 맞음 | 데이터, 복원, 둘째 죽음은 같음; gin-mirror의 억제, 풀, 재실행 열은 다시 세지 않음 | 센 항은 같음 |
| `no_tcp_control`, `gate_fenced` | 맞음, 자료 부족 | 다시 세지 않음(`gate_fenced`의 local 로그는 이 폴더에 없음) | - |

### 9.2 어긋남 목록 (셀, 시행, 열, 내 값, 채점기 값)

판정을 바꿀 수 있는 것:

| 셀 | 시행 | 열 | 내 값 | 채점기 값 | 영향 |
|---|---|---|---|---|---|
| `gc4_freeze12000_fence` | n1 | hold 길이(`hold_ms_max`) | 20 996.7 ms | 275.923 | `long_hold_lane`의 대상 시행 수: 내 셈 4, 채점기 0 |
| `gc4_freeze12000_fence` | n3 | 같음 | 20 996.2 ms | 274.653 | 같음 |
| `gc4_freeze12000_fence` | n5 | 같음 | 20 996.8 ms | 279.933 | 같음 |
| `gc4_helper_freeze12000` | n5 | 같음 | 20 997.5 ms | 279.896 | 같음 |

채점기의 `hold_to_fallback_ms`가 같은 네 시행에서 20 996.2–20 997.5 ms라, 채점기는 hold를 restored 줄에서 끝난 것으로 보는 것으로 읽힌다 `[추론]`. 라이브러리 줄로는 restored 뒤에도 hold 기한(`deadline in 19995 ms`, 예: `gc4_freeze12000_fence_gc_n1_r0.log` 2366행)이 살아 있다가 기한에 `given up (no INJECTED from the revived rank before the deadline after the restore round's publish)`(같은 파일 2428행)이 났다. 어느 쪽이 사전 등록의 "hold가 1 s를 넘는 시행"인지는 사람이 정할 일이다.

판정을 바꾸지 않는 것(정의나 기준점의 차):

| 셀 | 시행 | 열 | 내 값 | 채점기 값 | 비고 |
|---|---|---|---|---|---|
| `mi4_seg_32k` | n4 | FIN → 판정 − W 최대(`fin_judge_dev_max_ms`) | 2.04 ms(r1, 소켓 닫힘 줄 기준) | 1.941 | 채점기는 창 열림 줄(0.06–0.1 ms 뒤)을 기준으로 쓰는 것으로 보임 `[추론]`; 내 기준이면 이 시행이 ≤ 2 항에서 빠지나 셀 4/5 ≥ 4 |
| `gc4_kill3_ow_spareabsent` | n1–n5 | `fence_order_ok` | 순서 맞음(FENCE → FENCED, 활성화는 REFUSED) | 0 | 이 열을 읽는 예측 없음 |
| 거절 셀 일곱 | 21 시행 | 준비 실패 분류 | 21 모두 설계된 Resume 거절(`resume_rc=5`) | 17 준비 실패(링 live 안 됨), 4 판정(`rs4_refuse_restoreoff1` n2, `rs4_refuse_nomacro` n1–n3) | 링 live rank 수가 0–4로 경쟁에 따라 갈려 같은 셀 안에서 분류가 갈림; 보고만 하는 셀 |
| 복원 셀 86 시행 | - | `restore_time_ms` | 첫 판정 → 마지막 restored | 끝점이 마지막 published 줄로 보임 | 차 +0.2–+5.4 ms(최대 `mi4_kill2_kill3_ow` n2) |
| 17 시행(예: `rs4_kill3` n1, `mi4_kill2_kill3_ow` n3) | - | `judge_to_publish_ms` | 가장 이른 판정 → 마지막 게시 | 시작점이 가장 이른 판정이 아닌 시행이 있음(`mi4_kill2_kill3_ow` n3: 21.287 ms의 r0 판정, 가장 이른 것 20.264) | 차 +0.2–+1.0 ms |
| `mi4_kill2_kill3_ow`, `mi4_train_kill2_kill3` | 9 시행 | `restore_time_ms_1`, `_2` | 5절: 176.0–183.4, 128.6–159.7; 241.2–264.5, 238.0–246.5 | 171.3–178.7, 132.0–160.5; 241.3–264.4, 239.6–250.6 | 차 +0.9–+5.4, −1.5–−4.4 ms; 상한 2 000, 1 000 ms와 거리가 멂 |
| freeze, helper, 예비 없음, sampled | 6 시행 | `fenced_to_fallback_ms` | 첫 fallback 줄 기준 | - | 차 −0.8–+0.4 ms |

같은 것 `[측정: compare_out.txt]`: 시행마다 `n_judge`(358/358), 판정 원인(220/220), `kill_judge_ms_min/max`와 `stop_judge_ms_min/max`(220/220, 0.15 ms 안), `judge_spread_ms`(220/220), `ow_data_equal`(358/358), `win_verified`(185/185), `win_changed_after`(185/185), `la_fence_sigkill_n`, `surv_released`(358/358), `suspect_any_n`, `probe_timeout_n`, `left`, `la_act_refused_why`(5/5), `n_judge_taken`. 비용 표의 중앙값 넷과 차도 같다. 나머지 "한쪽만 빈칸" 차(대상 없는 셀의 `wait_held`, `revived_done`, `fence_order_ok`, 장애 없는 셀의 `kill_to_publish_ms`)는 빈칸과 0의 표기 차라 어긋남으로 세지 않았다.

## 10. 맞음이 아닌 세 예측의 내 숫자

### `restore_time_rdma` (채점기: 틀림)

시행마다 조건: 첫 판정 → 마지막 게시 120–197 ms(학습 195–286), 주입 → 마지막 게시 154.5–240.5 ms(학습 229.6–318.0), 펜스 순서, LATER ≤ 1. `[측정]`

| 셀 | n | 첫 판정 → 마지막 게시 ms | 주입 → 마지막 게시 ms | LATER | 통과 |
|---|--:|---|---|--:|--:|
| `mi4_kill3_ow` | 10 | 144.2–150.4 | 165.2–171.1 | 0 | 10/10 |
| `mi4_kill1_ow` | 5 | 147.8–150.2 | 168.5–171.0 | 0 | 5/5 |
| `mi4_kill3_ckpt_ow` | 5 | 124.9–146.2 | **145.6, 150.4, 152.0, 153.7**, 167.2 | 0 | **1/5** |
| `mi4_seg_4k` | 5 | 147.5–152.7 | 168.4–173.7 | 0 | 5/5 |
| `mi4_seg_32k` | 5 | 135.9–153.7 | 156.4–175.1 | 0 | 5/5 |
| `mi4_seg_128k` | 5 | 158.0–161.3 | 178.9–182.3 | 0 | 5/5 |
| `mi4_pull` | 5 | 140.8–146.0 | 162.0–166.5 | 0 | 5/5 |
| `rs4_kill3_mion` | 5 | 147.4–151.0 | 168.3–173.1 | 0 | 5/5 |
| `mi4_train_kill3` | 10 | 214.8–237.8 | 235.2–258.3 | 0 | 10/10 |

- `mi4_kill3_ckpt_ow`의 주입 줄은 r3의 `test switch NCCL_GIN_RESTORE_TEST_DIE_IN_CKPT: dying 300 us after the pause request of checkpoint 60`(시행마다 `_r3.log` 263행)이다. n1–n4는 주입 → 마지막 게시가 띠 아래(145.6–153.7 ms)이고, 첫 판정 → 게시는 모두 띠 안이다. 끝점을 restored 줄로 바꿔도 146.5–153.7 ms로 같은 네 시행이 빠진다. 채점기의 시행별 `judge_to_publish_ms`, `kill_to_publish_ms`와 0.05 ms 안에서 같다.
- 띠의 kill 쪽 하한은 traffic kill 셀에서 온 값이라, 체크포인트 멈춤 안의 죽음은 판정 뒤 복원 경로가 더 짧아 하한 아래로 나온 것으로 보인다 `[추론]`.

### `freeze_fence_restore` (채점기: 재검토, 안전성 항 어긋남 3/5)

| 시행 | 판정(관측자:원인:ms) | 퍼짐 | 주입 → FENCED | 복원(첫 판정 → 마지막 restored) | 끝 | 데이터 |
|---|---|--:|--:|--:|---|---|
| n1 | r0 10 005.5, r2 10 006.5, r1 10 101.1 (STALL_HELPER) | 95.6 | 10 215.0 | 281.0 | 포기 20 996.7 ms 뒤, released | 0 |
| n2 | r1 10 005.8, r2 10 008.3, r0 10 008.3 | 2.5 | 10 128.3 | 194.5 | ok | 1 |
| n3 | r0 10 007.0, r2 10 007.0, r1 10 101.0 | 94.0 | 10 216.6 | 280.3 | 포기, released | 0 |
| n4 | r1 10 099.6, r2 10 101.9, r0 10 101.9 | 2.3 | 10 222.8 | 195.2 | ok | 1 |
| n5 | r0 10 005.7, r2 10 006.8, r1 10 101.2 | 95.5 | 10 219.7 | 284.6 | 포기, released | 0 |

판정식 항(3명 STALL_HELPER, 10 000–10 300 ms, SIGKILL과 FENCED 줄, 창 검사)은 5/5 참이고 데이터 같음만 3번 거짓이라 2/5다. 안전성 항(데이터 같음) 거짓 3/5 → 재검토. 채점기와 같다.

### `helper_stall_fence` (채점기: 재검토, 안전성 항 어긋남 1/5)

| 시행 | 판정 ms (3명 STALL_HELPER) | 퍼짐 | 주입 → FENCED | 복원 | 끝 | 데이터 |
|---|---|--:|--:|--:|---|---|
| n1 | 10 006.6–10 008.0 | 1.4 | 10 127.8 | 193.2 | ok | 1 |
| n2 | 10 004.3–10 007.6 | 3.3 | 10 130.0 | 197.8 | ok | 1 |
| n3 | 10 003.6–10 008.2 | 4.6 | 10 130.3 | 199.4 | ok | 1 |
| n4 | 10 004.6–10 008.2 | 3.6 | 10 130.3 | 193.9 | ok | 1 |
| n5 | r0 10 005.1, r2 10 006.2, r1 10 102.7 | 97.6 | 10 219.2 | 284.7 | 포기 20 997.5 ms 뒤(`_r0.log` 2433행), released | 0 |

판정식 4/5 ≥ 4지만 n5에서 대기 붙잡힘, 데이터 같음, 되살린 rank 끝까지가 거짓 → 재검토. 채점기와 같다.

## 11. 하지 않은 것과 미확인

- 다시 세지 않은 열: `no_tcp_control`의 TCP 바이트와 `ss` 차, `none_probe_clean`의 READ 성공률과 박동 간격, `quiet_periods`, `qp_err_repair`의 세대 차, gin-mirror 회귀의 억제(`suppress_ok`), 풀(`from_pool_ok`), 재실행 열, `gate_fenced`(local 로그 없음).
- STOP_left 두 건의 남은 프로세스가 무엇이었는지 `[미확인]`(7절).
- freeze 두 셀의 복원 포기와 늦은 판정(약 95 ms)의 인과 `[미확인]`(3절).
