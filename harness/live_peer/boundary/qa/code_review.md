# Code review: live_stop_probe, probe_ms, sweep runner and scorer

Independent review, 2026-10-08. Commits: `b5657f88` (new fault and `probe_ms` column) and `67a9c668`
(`run_points.sh`, `deploy.sh`, `score.py`). Read-only: nothing was built, nothing was run on the cluster.
Raw data read: `results/20261008/` (CPU 65 trials: stop on PROBE 45, stop from the fault 20; GIN 45) and
`results/20261008_smoke/` (not scored). Markers: [measured] recomputed here from raw files with my own parser,
[source] read in code, [inferred], [unverified].

## Summary

No code defect that changes a verdict was found. `score.py` implements the frozen grammar correctly for all 14
measured rows, and an independent re-parse of the raw CSV, server logs and kv files reproduces every verdict.
Ranked findings:

| # | Severity | Where | Finding | Could it have affected the results? |
|---|---|---|---|---|
| 1 | risk, materialized once | `probe_server.c:417-437` | Stop from the fault: a blocking stderr write and the helper's wake-up sit between the GOACK timestamp and SIGSTOP; the gap is not recorded | Yes: it is the whole miss of the answer-time prediction for the stop-from-the-fault series (CGc), `lb_cg4600_t6`, gap 10.852 ms. Verdict rows unaffected |
| 2 | risk, interpretation | `probe_client.c:518-531`, `run_points.sh:125-142` | The PROBE send phase on the kernel's 32 ms timer grid is not random: the first CQE comes on a 268.435456 ms NIC grid and the trial cadence is fixed, so the phase sweeps deterministically | Yes, for interpretation: explains the empty 1027–1032 ms region; all 45 stop-on-PROBE verdicts follow from the phase; the answered counts at 1008 and 1024 ms (CPb, CPc) are not independent draws |
| 3 | risk | `probe_server.c:473-475` | Stop on PROBE: two log writes between the stop end and the PROBED answer | No: answer minus stop 0.934–1.053 ms (n=20) |
| 4 | risk | `score.py:227-230`, `:284` | Missing fields: NONE treats them as not true; a `where` filter drops them silently (false-pass direction) | No: no blank scored field in 110 trials |
| 5 | risk | `score.py:104-111`, `:122` | The -1 sentinels of `probe_ms` and `cqe_ns` are parsed as real values (false-fail direction) | No: cqe 3501.5–3746.2 ms, probe_ms 0.710 ms or more, all 65 rows |
| 6 | risk | `run_points.sh:104`, `score.py:119-121` | Stop-on-PROBE validity needs `stall_end`, which exists only after a RETRY_EXC or remote-NAK CQE: an outcome decides the exclusion | No: all 65 rows status 12, vendor_err 0x81; 0 excluded, 0 extra |
| 7 | risk | `run_points.sh:91` | The state poller runs `ps` on sunny every 0.2 s through GOACK and the stop start | Unknown; possible contributor to 1 [inferred] |
| 8 | nit | `probe_server.c:464-468`, `probe_client.c:521-527` | No server time at PROBE receipt, no PROBE send time in CLOCK_MONOTONIC, untimed `ibv_query_port` before the PROBE | Two of 28 wait ends cannot be placed (see 2) |
| 9 | nit | `probe.c:452-460`, `probe.c:150` | Mixed clocks; SO_RCVTIMEO applies per 1-byte recv | No |
| 10 | nit | `score.py:213-218`, `:92-95`, `:128` | No missed-trial list for COUNT failures; first-glob file pick; GIN runs without r0.kv are invisible | Reporting only (decline-time row Gd shows "-") |
| 11 | nit | `lp_stall.h`, `run_points.sh:46-60`, GIN `run_trial.sh:117,119` | Remaining ways to leave a stopped process | No: no stopped or leftover process after any of 65 CPU trials |
| 12 | nit, pre-existing | `probe_client.c:533-546` | A non-PROBED reply line is classified as a dead peer | No |

## 1. Stop from the fault can start late

- [source] For `live_stop_err` the server takes `t_goack` (`probe_server.c:418`) right after the GOACK send, writes
  `fault_applied` to stderr (`:419-421`; stderr is the file `/tmp/lb_probe_srv.log`, `run.sh:54`, unbuffered), then calls
  `lp_stall_self` (`:434`). The helper reads its clock for `stall_begin` (`lp_stall.h:71`) only after it is scheduled,
  has read the command and called `getppid`. So `stall_begin - fault_applied` = file write + AF_UNIX send + helper
  wake-up. A write stall (journal commit, page allocation) or a run-queue delay of the helper both push the stop late.
  There is no timestamp between the write and the send, so the recorded data cannot tell the two apart.
- [measured] `stall_begin - fault_applied` (server log mono_ns): 0.060–0.138 ms in 19 of 20 main trials, 10.852 ms in
  `lb_cg4600_t6`; smoke 0.063–0.067 ms (n=3). In t6, probe_ms - x = 11.855 ms = 10.852 + 1.003, and the other 11
  answered trials give 1.034–1.128 ms. The late start explains the miss completely.
- Effect: only the answer-time prediction (CGc) failed. t6 had x = 901.6 ms and was answered, so the verdict rows for
  this series (CGa, CGb) hold. A gap near 100 ms in a trial with x near 900 ms would have turned "answered" into "no
  answer" (false fail). A late start only lengthens the stop, so it cannot create a false pass.
- [unverified] Which cause it was. sunny's `/tmp` filesystem and load at 14:27:23 were not checked (no cluster access).
- Suggested: send the stop command first and log afterwards with the saved `t_goack`; record `stall_begin - t_goack`
  per trial and flag values above 1 ms. The code path is live_peer's, so live_peer's data has the same exposure.

## 2. The PROBE phase is set by the NIC's timer, not drawn at random

- [source] `t_pr0` follows the first CQE (`probe_client.c:518-527`). The 1 s `SO_RCVTIMEO` ends on the 8-jiffy (32 ms)
  timer-wheel grid.
- [measured] From `t_post_mono_ns + cqe_ns` of the 65 CPU rows:
  - All 65 first-CQE times lie on one grid of 268.435456 ms (4.096 µs × 2^16, and its divisors such as
    67.108864 ms) within 0.19 ms over 614 s. A 536.87 ms grid does not fit. Consecutive stop-on-PROBE trials are 36
    periods apart (9663.7 ms), 32 periods after the no-stop trial.
  - 26 of 28 no-answer waits end at 15.99–16.04 ms modulo 32 ms of rain's CLOCK_MONOTONIC. So probe_ms = 1040 - p
    for p of 8 ms or more and 1008 - p below 8 ms, where p is the PROBE phase modulo 32 ms.
  - p moves by -0.31 to -0.33 ms per trial (36 × 268.435456 mod 32 = -0.324). The 65 phases never fell in
    7.1–12.9 ms or 19.1–23.4 ms. The longest wait, 1027.114 ms, is the trial with p = 12.886 ms.
  - From p alone (answer = stop + 0.95 ms) all 45 stop-on-PROBE verdicts are reproduced, 45 of 45. Smallest margins:
    0.52 ms (`lb_cp1008_t5`), 0.88 ms (`lb_cp1024_t1`). At 1024 ms, 6 of 10 trials had p = 26.1–28.8 ms.
  - Two waits (`lb_cp1100_t2`, `_t3`) end 4 ms after the grid point. Either the PROBE left 28 ms after the CQE (the
    `ibv_query_port` at `probe_client.c:521` is not timed) or the timer fired one tick late [unverified].
- [inferred] The NIC reports transport-retry exhaustion on a 268 ms tick; that would also explain why first-CQE times
  spread over about one period (3501.5–3746.2 ms here, 3494.7–3755.9 ms in live_peer).
- Effect: the verdicts stand as measured. But the empty top of the wait range (EXPERIMENT.md 15.1, marked unverified)
  is a gap in the sampled phases, not a kernel property. The answered counts at 1008 and 1024 ms (CPb, CPc) and the
  spread of no-answer waits (CPf) came from a slow deterministic sweep, so the "probability about 0.7 and 0.2" model was
  not tested as independent draws.
- Suggested: wait a random 0–268 ms before the PROBE, and write `t_pr0` in CLOCK_MONOTONIC to the CSV.

## 3. Log writes inside the stop-on-PROBE answer path

[source] `probe_server.c:473-475` write `stall_begin` and `stall_end` before the counter reads and the PROBED send
(`:477-485`). A slow write adds directly to the answer time and can turn a boundary trial into "no answer".
[measured] answer - measured stop 0.934–1.053 ms (n=20 answered stopped trials), no-stop answer 0.710–0.756 ms (n=5);
no outlier. Suggested: log after the PROBED send.

## 4. Scorer: missing fields lean toward a pass

- `NONE(e)` (`score.py:227-230`) counts a trial whose e cannot be evaluated as "not true", so a missing field can only
  help NONE pass. Rule 3.0 defines missing fields for ALL, COUNT, MAX and MIN, not for NONE. NONE is used by the
  2995 ms row (Gb, "no decline at the late end").
- A `where` condition that cannot be evaluated drops the trial (`score.py:284`) without counting it in n or listing
  it. A trial without `cqe_ns` would leave both pooled scopes of CGb instead of failing their ALL.
- [measured] No scored field is blank in any of 110 trials, and the one declined 2995 ms trial has its decline time.
  No effect. Suggested: count unevaluable trials as false in NONE and as listed misses in `where` scopes.

## 5. Scorer: -1 sentinels

`probe_client.c` writes `probe_ms` = -1 without a PROBE (`:515`) and `cqe_ns` = -1 without a CQE (`:479`).
`score.py` parses both as numbers (`:104-111`); the frozen x expression `stall_meas_ms-cqe_ns/1e6` then gives x close
to the stop length, which puts a no-CQE trial in CGb's "x of 1034 ms or more" scope and fails it. For the frozen
rules a sentinel can only produce a false fail. [measured] Not present.

## 6. Outcome-dependent exclusion in the stop-on-PROBE series

`run_points.sh:104` and `score.py:119-121` require `stall_end` for stops above 0. In `live_stop_probe` the server
stops only when a PROBE arrives, and the client sends one only after a RETRY_EXC or remote-NAK CQE with an active port
(`probe_client.c:518-521`). A trial whose first CQE had another status would be excluded as "fault not applied" and
replaced, although EXPERIMENT.md 8 says the decision does not read outcome fields. [measured] Not triggered
(`runner_CPU.log`: extra 0 for every point).

## 7. State poller load

`run_points.sh:91` keeps an ssh loop on sunny that runs `ps -C probe_server` every 0.2 s from before the server starts
until it sees state T. It cannot block the server, but it adds CPU work at the moment the helper must be scheduled
[inferred]. [measured] All 60 stopped trials logged "state T seen".

## 8. Missing timestamps (nit)

- No server time at PROBE receipt, so the stop-on-PROBE start is only bounded indirectly. [measured]
  (answer - stop) - (no-stop answer) is at most 1.053 - 0.710 = 0.343 ms in the answered stopped trials, so the stop
  began at most about 0.34 ms after the PROBE arrived. In all 20 no-answer stop-on-PROBE trials the wait ended 2.21 ms
  or more before the stop ended, so a late start cannot have caused any of them. An early start is impossible: the stop
  is triggered by reading the PROBE line (`probe_server.c:464-468`) and `probe_stalled` is per trial (`:460`).
- `t_pr0` exists only in CLOCK_MONOTONIC_RAW, so finding 2 had to rebuild the phase from `t_post_mono_ns + cqe_ns`.
- The `ibv_query_port` between the CQE and `t_pr0` is outside probe_ms but inside x. [measured] probe_ms - x =
  1.034–1.128 ms in the 11 normal answered trials, so no large gap there.

## 9. Clocks and the wait (nit)

`probe_ms` and `cqe_ns` use CLOCK_MONOTONIC_RAW (`probe.c:452-455`); `t_post_mono_ns`, the server and the helper use
CLOCK_MONOTONIC (`probe.c:457-460`, `lp_stall.h:34-38`); the socket timeout runs on jiffies. [measured] The rate
difference against the NIC grid is 0.31 ppm, under 1 µs per wait. x mixes the server's stop start (after GOACK) with
the client's `cqe_ns` (from after `post_write` returns), an offset of about one control-channel one-way delay, inside
the frozen tolerance. probe_ms runs from before `send()` to the return of the recv that delivers the newline or times
out (`probe_client.c:527-531`), as DEVIATIONS.md item 4 says. The timeout applies to each 1-byte recv (`probe.c:150`), so
a reply split across segments could wait longer than 1 s in total; not observed.

## 10. Scorer reporting (nit)

COUNT and N give no missed list (`score.py:213-218`), so the failed decline-time row (Gd) shows "-" in SCORE.md
although its five middle-band declines are known; rule 3.0 asks for every missed trial. `csvs[0]`, `srvs[0]`
(`:92-95`) are taken without checking that there is exactly one ([measured] exactly one in all 65 run dirs). GIN trials
that never wrote `r0.kv` are invisible (`:128`) and would not show as runner failures ([measured] 45 found, 45
planned, rc=0 in all three `trials.log`).

## 11. Stopped process left behind (nit)

Safety nets: `run.sh:42` sends CONT before TERM; `run_points.sh:46-60` continues our T-state processes and kills
leftovers; GNU timeout sends CONT after its TERM; the helper dies with its parent (`lp_stall.h:64-69`). Gaps: (a) if
the helper is killed during a stop, the server stays stopped until one of those sweeps; GIN `run_trial.sh:117,119`
runs an unscoped `pkill -x lp_stall` on both nodes, safe here only because the CPU and GIN blocks are serialized by the
lock; (b) the sweeps match by name with no user filter (`run_points.sh:46-52`); (c) a negative `LIVE_STOP_MS` becomes a
49-day stop for the existing stop faults through the uint32 cast (`probe_server.c:434`; the new fault checks > 0);
(d) `pin_to_cpu` runs before the fork (`probe_server.c:295`, `:298`), so with `SERVER_CPU` set the helper shares the
server's CPU (it is -1 here). [measured] `runner_CPU.log` has no SIGCONT or leftover note.

## 12. Liveness classification (nit, pre-existing)

If the PROBE reply is a line other than PROBED, or empty, errno stays 0 and the trial becomes `proc_kill` and ends the
run (`probe_client.c:533-546`). Not reachable in this protocol, where nothing else is pending before the PROBE.

## Checked and correct

- Fault wiring: the enum value is appended last, so `fault >= FAULT_LIVE_QP_RESET` includes it on both sides
  (`probe_client.c:285`, `probe_server.c:416`); name table entry (`probe.c:43`); QP to ERR on GO (`probe_server.c:398`);
  the stop happens only on the first PROBE and only when `LIVE_STOP_MS` > 0 (`:466`); the path of the existing stop
  faults is unchanged (`:432`).
- Interaction with `live_stop_err` on the client: the new fault joins `live_stop` (`probe_client.c:286-287`), so RESYNC
  runs, and a late PROBED after a no-answer verdict is skipped by QUERY (`:154-158`). [measured] All 20 no-answer
  stop-on-PROBE logs show the skip; `stale_lines` 0 and `resync_ms` 0 in all 65 rows.
- Signal safety: the helper is forked before the device, sockets and async thread (`probe_server.c:298` vs `:305-306`)
  and uses only async-signal-safe calls; the server's control socket has no SO_RCVTIMEO, so stop and continue cannot
  cause EINTR there, and `lp_stall_xfer` retries EINTR. TCP_NODELAY on both ends (`probe.c:93-118`).
- Stop length: [measured] helper-measured minus configured 0.066–0.125 ms over the 60 stopped trials.
- `score.py` grammar: `; ` clause split, scope regex (`:268`) matches every frozen scope, default per-cell scope from
  `cells` before the first colon (`:259-261`), pooled and per-cell groups (`:279`), ALL, MOST, NONE, COUNT, N, MAX, MIN
  (`:193-233`), n = 0 gives no data (`:247-249`), any false clause fails the row (`:289-290`); `ceil(0.9 n)` is exact for
  every n below 1000. [measured] Re-parse reproduces all 14 verdicts: answered 9 of 10 at 1008 ms and 1 of 10 at
  1024 ms; no-answer waits 1001.592–1027.114 ms (n=28 pooled); stop-from-the-fault scopes n = 12 and 6; middle-band
  declines 5 of 21; late-end declines at 2998 ms 9, all after rank 1 resumed.
- `run_points.sh` extra-trial cap `(3N+9)/10` equals ceil(0.3 N); `deploy.sh` compares exact md5sum output.

Scratch scripts used for the recomputation are not part of the repository.
