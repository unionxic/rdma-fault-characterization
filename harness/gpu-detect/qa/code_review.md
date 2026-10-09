# gpu-detect: independent review of the measurement code (read-only)

> 리뷰 에이전트의 보고 원문이다(본 실행 중 21:53, G1과 G2가 끝난 때). `$SCR`는 그 세션의 스크래치다. 본 실행 뒤 각 항목을 어떻게
> 확인하고 처리했는지는 맨 끝 절과 [../EXPERIMENT.md](../EXPERIMENT.md) 13, 16절에 덧붙였다.

Reviewer: subagent, 2026-10-09, during the main run. Scope: `harness/gpu-detect/` at `prereg/gpu-detect-v1` (1891614e):
apprun.py, rows_gd.py, score.py, cells.json, schedule.json, cells_reg.sh, hold.sh, chain.sh, plus the called runners
`../gpu-initiated/gin_recovery/remaining/run_trial_hr.sh`, `run_mr_hr.sh`, gin-remaining `score.py`, s2_close `score.py`
(grammar), `../blind/node_agent.py`. Nothing in the worktree or on the cluster was written or run.

## What I ran

- `sha256sum` of the 12 frozen files: all equal PREREG.txt. `git status` of the worktree clean.
- Live folder, read-only `ls`/`cat` only (no script run on it): `schedule_sha256.txt` shows G1 and G2 ran with schedule
  sha256 `7a5e4875...` = PREREG; `chain.out` G1, G2 pass 1 rc=0, iptables 0 -> 0; 68 raw trial dirs, no `.partial*`.
- Copies of `results/20261009_pilot` and `_pilot2` plus a copy of `harness/` (without results) under
  `$SCR/gd_review_h/`; ran `score.py` from the copied tree with `PYTHONDONTWRITEBYTECODE=1` (no pycache in the worktree).
  Both rc=0, every prediction "자료 부족" as expected for pilots; app and regression columns match the values in
  EXPERIMENT.md 12 (e.g. pilot 2 `gin_qperr.hk.n2` det_by watch 8.322 ms, det_src cq; w0 det1_s 3.757 r1:device,
  rec_rx_s 3.767; rm4_gap@hk gap_cause peer-dead, gap_n_rel23 3; rm4_gap@hw unknown, gap_resp_stuck 1).
- Every identifier used in the 41 acceptance formulas exists as a column (checked against the pilot 2 trials_scored.csv).
- Differential test: removed every hk/hw-only line (detect=1, fault policy, QP watch, policy WARN) from the 13 pilot 2
  regression trials and recomputed the gin-remaining columns via `score.reg_rows()`: all gin-remaining columns identical,
  only the status moved to config_detect. So the inherited gin-remaining regexes are not perturbed by the new lines.
- Grammar probes with synthetic rows through `score.evaluate`: GD4's `cell == "gin_qperr_w1"` ternary works per cell;
  GD5 behaviour with empty/one-value cells (below); GD2 with negative det_ms (below).

## Verified correct (no action)

- Clocks. det_ms, rec_ms: target process CLOCK_MONOTONIC on both sides (fire `done_mono_ms`, watch/Q4 `mono_ms`,
  `t_resumed` share the per-node base; checked on rain 2703... and sunny 1572... lines). gap_relms: survivor's own clock
  (kv `rx_<X><s>_rel_mono_ms` vs its `judged dead mono_ms`). dt_err, dt_end, det1_s, rec_rx_s, verdict_s: rain receipt
  clock on both ends (t_ack / fire-line receipt / agent exit receipt). Rain receipt clock = rain CLOCK_MONOTONIC, same
  base as rain process mono_ms.
- Columns from the right rank: det_*/rec_ms target only; det1_s either rank after the fire line; surv_rc, verdict_s,
  n_fin_verdict, n_death survivors only; ms_* PE 0; gap_* from the meta kill_rank or the exit-after-ACK line.
- Regex double counting: none that matters; all count columns are used only as `>= 1` / `== 0` / `== 2` (WT1) and the
  FIN-verdict regex does not also match the DECLINE reason text. RE_Q4/RE_WATCH greedy `.*mono_ms=` hits the trailing
  mono_ms (gtimer_ns precedes it).
- N_SCORED: substituted per cell for "per cell:" rules, first key otherwise; never inside count(); 75% rule
  `ceil(0.75 x planned)` as 3.2. PLANNED totals equal section 7 (app 130: GIN 68, NVSHMEM 62; reg 118: 33 + 40 + 45).
- Pilot holds excluded from PLANNED; pilots live in separate folders; `hold.sh` calls `rows_gd.py --progress` only (no
  writes). `.partial*` dirs never contain trial.meta, so they are never scored.
- Exclusions match section 8 (app: applied/void/config; regression: gin-remaining status as hr, plus status4_new fires,
  stall knob, kill in traffic, gap window, exit line, spread <= 250 ms, then detect and policy lines).
- Retry: `chain.sh` re-runs only G*/N*/P1 trials without trial.meta (max 2 more passes); ids are unique, so no double
  counting.
- Safety: no kill by name anywhere (pgrep only counts); regression runners kill only recorded PIDs; node_agent signals
  its own child/group; iptables only read (`sudo -n iptables -S | grep -c`); ports 29000-30999 checked free on both nodes.

## Findings

### M1 (medium) GD5 median over a filtered subset: an empty cell gives "틀림", one value decides
- score.py:198 (`short` from scored-trial counts) + s2_close/score.py:177-180 (`median` returns NIL on no values; NIL
  comparisons are False).
- GD5 compares medians of `det_wcq_ms`, which is filled only when the watch came first and its class came from a root
  CQE (rows_gd.py:290-291). "자료 부족" is decided by the cell's scored-trial count, not by how many trials feed the
  median. Probe: w100 cell with 0 qualifying values -> "틀림"; with 1 value -> verdict decided by that one trial.
- Pilots: det_src cq in 6 of 7 watch detections, so an empty cell is unlikely, but small-n medians are likely.
- Can change GD5's verdict (a mechanical 틀림 with no data). Record: per cell, n of non-empty det_wcq_ms; if any cell has
  0, log in 13 that the mechanical verdict is 틀림 because the median is empty and report it as not evaluable beside it.

### M2 (medium) LC1 (and PH1's policy terms) cannot fail: violations become config exclusions
- rows_gd.py:262-264 (gin hk app: every present rank needs `lbs[r] >= 1`, else config_ok 0) and gin-remaining
  status2 for build "hr" (copy_path nic, lb_off 0 on both ranks) via score.py:101.
- LC1 asks "on every rank" but uses `min` over ranks that printed the line (rows_gd.py:253, :429); a trial where a rank
  lacks the NIC-path line is excluded as config, never counted against LC1. Same for PH1 `pol_n == 4 and pol_eff_ff == 1`
  (config_policy).
- Verdict effect: LC1 can only be 맞음 or 자료 부족. Record: next to LC1 (and PH1), list the config / config_policy
  exclusions of gin_none@hk, f1_b@hk, rm4_kill3_hold@hk with `config_why`; any such exclusion is a substantive LC1
  counterexample and per section 8 also a block stop that must be logged.

### M3 (medium) NC1 and NC2 acceptance weaker than the predicted text
- predictions.csv NC1: text "hangs ... with no error line", observable `n_err0, n_err1`, acceptance
  `outcome == "HUNG" and n_death == 0` (n_death = FIN-verdict / peer_fin lines only). NC2: text "both PEs decline and
  still hang until the wall cap", acceptance `HUNG and n_declines >= 1` (one PE suffices; grace end also counts).
- A t1_380 trial with a survivor error line, or with one PE declining, or ended by grace passes the formula but not the
  text. blind-apps data make this unlikely (DECLINE 0 on kill; 8/8 both PEs on remacc).
- Verdict per formula is unaffected; the stated claim could be overstated. Record per trial: survivor n_err, DECLINE per
  PE, end0/end1 == wall, and note any trial that satisfies the formula but not the text.

### M4 (medium, operational, no verdict effect) the 880 s KILL orphans the rain-side app and skips post-hold checks
- chain.sh:21 `timeout -s KILL 880` (no --foreground: SIGKILL to the whole group, incl. apprun.py and the local
  node_agent.py); node_agent.py:64-65 starts the app with `start_new_session=True` and has no watchdog. The sunny side is
  cleaned (ssh EOF -> kill_group); the rain app is not. A hung control (hr/hq, t1_380) or a SIGSTOPped app would stay
  forever; next hold waits 150 s then writes STOP_left (hold.sh:53-60). Regression runners are safe (own inner timeout,
  files written only at the end, so a cut trial leaves no files).
- A KILL also skips that pass's after-snapshot, mlx5 diff and CUDA scan (hold.sh:91-108). Snapshot files of pass 2 of the
  same hold overwrite pass 1's (same names; the counts survive in `hold_<H>_p<n>.out`).
- Budget math: apprun stops before `elapsed + wall_s + 15 > 800`, typical overrun 1-3 s, hold pre/post about 10-20 s each,
  so about 830 s; KILL only with slow ssh or a stale-process wait. Check: any `rc=137` in chain.out; if so, look for the
  rain app by the PID in that trial's a0.log `AGENT start pid=`, and compare mlx5/fwcmd snapshots around that pass by hand.

### L1 (low) GD2 lower bound `0 <= det_ms`
- predictions.csv GD2; rows_gd.py:289 uses `done_mono_ms` (end of the hook, about 1.1 ms after fire). A device-classified
  CQE logged while the hook is still moving the other QPs gives det_ms < 0 and fails the GD2 condition (probe: 2 such
  trials of 16 -> 틀림). The target is normally inside waitSignal (blind-apps 14/16 no line), so rare. Check: any GD2
  failing trial with det_ms < 0; if present, note it.

### L2 (low) gap window exclusion depends on one decline-reason prefix
- rows_gd.py:496 + score.py:123-124. Only "peer closed the socket before DONE" counts as hitting the window; a loss after
  the responder's Commit through "cannot send ACK (...)" (hk_layer.diff, gdakiTsDeclineAfterCommit with sendFailed) or
  "DONE timeout" is excluded as "창 밖". This is the section 8 rule as written. Check: for each cond_window_gap exclusion
  print rank 0's decline reason and `gap_lac`; a nonzero gap_lac there means the window was hit and should be noted.

### L3 (low) stop cells: CONT acknowledgement not checked
- apprun.py:365-371 records `cont_ack`; rows_gd.py never reads it. A missed CONT would make a GF1/NF1 trial HUNG by the
  harness. Pilots: all cont_ack rc=0. Check `fault.cont_ack` contains ` rc=0 ` for every gin_stop/nvs_stop trial.

### L4 (low) re-run of interrupted app trials
- apprun.py:305-311 renames an interrupted `raw/<id>` to `.partial<k>` and re-runs the same id (column `rerun`). Not
  double counted and pre-registered (9.3), but the partial attempt may have applied its fault. List any `rerun > 0`.
  None so far (G1, G2).

### L5 (low) hash checks at scoring time
- score.py:233-244 checks only predictions.csv; cells.json (PLANNED source), schedule.json, rows_gd.py, and the imported
  gin-remaining / s2_close / blind code are not checked. apprun's md5 check compares rain vs sunny only, not the recorded
  hk md5 (2913c777...). Check at QA: `sha256sum` vs PREREG.txt for all 12 files, `git diff prereg/gpu-detect-v1 --
  harness/gpu-initiated harness/blind` empty, every line of `schedule_sha256.txt` = 7a5e4875... (G1, G2 already are),
  deployed hk libnccl md5 on both nodes = PREREG (read-only, after the run).

### L6 (low) score.py crashes (NameError) when a referenced column is absent from every row
- s2_close/score.py:130-138 catches TypeError/ValueError only. Seen on a reg-only copy (LC1 `lb_shadow`). Harmless on the
  full main folder; do not score partial folders.

### L7 (low) four-rank detect check is a line count, not per rank
- score.py:153 `n_det_on >= n`; one rank printing two lines can hide a rank with none. All ranks load the same library, so
  no realistic verdict effect.

### L8 (low) cells never exercised on hw/hk through this pipeline before the main run
- f3_b, bidirf_sym_b (RG1), hd_rxdeath_b (RG4), mr4_none, mr4_f1_01 (RG8), rm4_kill3_untimed (RG9; only its hold copy
  ran), mr4_cyc_stall (RG10), lat_256k_* (LT2, LT4). The differential test above shows the inherited columns are not
  disturbed by the new lines, but these cells' statuses were never seen on hk. After R1/R2 finish, look at their
  status column before scoring (a copy is fine) to catch a config exclusion early.

### L9 (low) frozen text vs frozen schedule: target ranks not balanced
- EXPERIMENT.md 6 says targets are "0과 1 반씩"; apprun.py:494 draws each target uniformly, so schedule.json has e.g.
  gin_qperr@hr 1/5 (rank 0/1), gin_qperr_w100@hk 6/2, nvs_kill_rel 1/4, nvs_remacc_rel 4/1, nvs_qperr 1/5, gin_kill 2/4.
  Section 7 ("대상 ... 고르게 뽑음") matches the code. Log in 13 as a clarification (schedule.json governs). No verdict
  effect expected; report results split by target rank where n allows.

### L10 (low) iptables guard cannot tell "no sudo" from "no rules"
- chain.sh:16: if `sudo -n` fails, both counts read 0. Filter table only. Pilots and G1/G2 show 0 -> 0. Optional
  read-only check that `sudo -n iptables -S | wc -l` is nonzero.

### Minor text/formula gaps (no action beyond noting)
- MA1 text "one nested round per pass" is not in the formula. ND2 text "both PEs decline" is implied by rc 70 only.
  GC1 text "they hang, or recover late" is descriptive; the formula only excludes fast detection/recovery.

## Bottom line

No blocking or high-severity defect. No finding changes how trials are classified for the GIN and NVSHMEM main
predictions; the ones that can move a verdict are GD5's empty-median rule (M1) and, rarely, GD2's lower bound (L1). LC1
cannot come out 틀림 by construction (M2). The main operational risk is an 880 s KILL during an app trial (M4).

## 본 실행 뒤 확인과 처리

이 절은 리뷰어가 아니라 이 문서를 실험 폴더에 넣은 에이전트가 덧붙였다. 값은 본 실행의 원자료와 `trials_scored.csv`에서 다시 셌다 `[측정]`.

| 항목 | 본 실행에서 확인한 것 | 적은 곳 |
|---|---|---|
| M1 | 중앙값에 든 시행(감시가 먼저, 뿌리 CQE로 분류)은 주기 1 ms 3/8, 10 ms 14/16, 100 ms 8/8로 빈 셀이 없다. 판정은 맞음(6.20 < 18.55 < 91.75 ms). 그중 8회는 뿌리 CQE가 있는데도 감시가 약 50 ms(48.9–51.3 ms)를 기다렸다 | EXPERIMENT.md 13절, 17절 H2 |
| M2 | `gin_none@hk`, `f1_b@hk`, `rm4_kill3_hold@hk`의 설정 확인 제외 0(248회 전체도 0). 숨은 반례 없음 | 13절 |
| M3 | 시행마다 문장대로 따짐. NC1 4회: 살아남은 PE의 오류 줄 0, 죽음 줄 0, 하네스 유예로 끝남. NC2 4회: 두 PE가 한 번씩 거절, 두 PE 모두 시간 상한으로 끝남. 문장도 맞음 | 13절 |
| M4 | 880 s KILL 없음. 여덟 hold 모두 첫 회 rc=0, 가장 긴 hold 7분 24초 | 12절 |
| L1 | GD2 셀(`gin_qperr@hk`)에는 음의 지연이 없다(최솟값 0.208 ms). 음수 둘은 주기 1 ms 셀(−0.085 ms, GD4는 아래 한도가 없어 통과)과 감시 끔 셀(−0.364 ms, GC2) | 13절 |
| L2 | 응답 쪽 틈 셀의 창 밖 제외 0. 11회 모두 rank 0이 "peer closed the socket before DONE"로 거절 | 15절 |
| L3 | stop 셀 16회(GIN 8, NVSHMEM 8)의 SIGCONT 응답 모두 `rc=0` | 12절 |
| L4 | 다시 돈 app 시행 0(`rerun` 130회 모두 0) | 12절 |
| L5 | 고정 파일 12개의 sha256 = PREREG.txt. `git diff prereg/gpu-detect-v1 -- predictions.csv cells.json schedule.json`과 `-- harness/gpu-initiated harness/blind` 모두 비어 있음. app hold 넷의 `schedule_sha256.txt` 모두 `7a5e4875…`. rain의 배포된 `hk` libnccl md5 `2913c777…`(= PREREG). sunny의 번들은 다시 보지 않았다 `[미확인]` | 16절 |
| L6 | 전체 본 실행 폴더로만 채점했다 | |
| L7 | 랭크 4개 회귀 셀 모두 판정 가능(제외 0), 판정 영향 없음 | |
| L8 | R1, R2 셀의 상태 모두 `scored`(설정 확인 제외 0) | |
| L9 | 대상 rank의 비율을 셀마다 적음 | 13절 |
| L10 | sudo 실패와 규칙 없음을 가르는 확인은 하지 않았다 `[미확인]` | 18절 |
