# Code review: gin-multirank driver, runner, parser and scorer

| item | value |
|---|---|
| Scope | `gin_mr.cu`, `build_mr.sh`, `deploy_mr.sh`, `run_mr.sh`, `cells.sh`, `hold.sh`, `chain.sh`, `rows_mr.py`, `score.py` (and `../s2_close/score.py`, whose grammar `score.py` imports) |
| Code version | tag `prereg/gin-multirank-v1` = commit `460488de` = worktree HEAD. No tracked change after the tag (see the last section) |
| Library read where the driver depends on it | hd tree `agent_ts2hd/nccl-src` (session scratch), `gin_host_gdaki.cc` md5 `36995301` (the value in EXPERIMENT.md 1), installed headers `agent_ts2hd/build/include`; `hd_layer.diff` of gin-harden |
| Data used for spot checks | `results/20261009/` (137 trials, read-only; local Python over the raw kv, log and meta files) |
| Not done | no cluster action, no program run on the cluster, no file changed except this one |

Tags: `[측정]` counted from the raw files, `[소스]` read in the code, `[추론]` inference, `[미확인]` not checked.

## Verdict

**No finding biases or invalidates the 42 scored verdicts.** No blocker, no high finding.

- Two medium findings.
  - One was seen in the run: two trials failed to bind the rendezvous port. The cause sits in the port choice. It did not bias the scored set.
  - One is latent: an exclusion order in `score.py` that would hide an initialization failure in a fault cell. It did not occur.
- The rest are low: rules that are weaker than they read, gaps in the runtime stop rules, and column details. Each was checked against the data and none changes a verdict.
- Every zero-count rule (I3, R1, Y3 and the `n_decl == 0` / `n_refused == 0` / `n_notrts == 0` parts of others) counts a log string whose format I checked against the hd source. Where possible I also checked it against lines that do occur in this run. None passes because a pattern never matches.

## Findings, ranked

### M1 (medium, observed): the rendezvous port is drawn from rain's ephemeral port range

- **Where.** `run_mr.sh:42` draws `PORT = 46000 + ($$ + RANDOM) % 3000`. `gin_mr.cu:441-447` has rank 0 bind `INADDR_ANY:PORT` with `SO_REUSEADDR` and exit on failure. `gin_mr.cu:464-470` has ranks 1 to N-1 retry connect for up to 120 s.
- **Cause.** rain's `ip_local_port_range` is 32768–60999 `[측정]` (read on rain, 2026-10-09). So 46000–48999 lies wholly inside the range the kernel hands out for outgoing connections and `bind(0)`. A bind fails with `EADDRINUSE` if any socket on rain holds that local port. Examples:
  - the runner's own ssh/scp sessions to sunny, which start just before rank 0;
  - the NCCL bootstrap, proxy and helper sockets of rank 2 and of other jobs;
  - TIME_WAIT remnants of the previous trial's connections.

  `SO_REUSEADDR` does not help when the holder lacks it or is a listener `[추론]`: Linux bind-conflict rules, not tested on this kernel. Both failed ports are even (47564, 46790), and Linux since 4.6 prefers even ports for `connect()`. That fits a clash with an outgoing connection. It is weak evidence (2 of 2 by chance is 1 in 4) `[추론]`.
- **What happened.** `h3/mr4_f1_01_n4` and `h5/mr4_f1all0_n3` show rank 0's whole log is `bind: Address already in use`. Ranks 1–3 hit the 60 s global watchdog (`rc=1,7,7,7`, wall 60.3 s, `left=0`) `[측정]`. That is 2 of 137 trials.
- **Effect on results.** None on the verdicts `[추론]`.
  - The failure happens before CUDA and NCCL initialization, so it cannot depend on the cell's fault or outcome.
  - `score.py` excludes it as `bind`, which is section 8's rule.
  - Each cell was filled with trial `n11` (fill hold 05:42–05:53).

  Side effects:
  - The two refills ran about 1.5 h after their cells' interleaved holds, outside the planned order (a minor time confound).
  - If the socket holding the port is a listener of another process, ranks 1–3 connect to it and write their 4-byte rank number into it before the watchdog ends them. That is a cluster-safety concern under the "do not touch other users' work" rule. The logs cannot tell a refused connect from a hung one, so whether this happened is `[미확인]`.
- **Fix.** Draw the port below 32768 (for example 20000–29999). Alternatively, have rank 0 try a short port list that the clients walk in the same order, or have `run_mr.sh` relaunch on a bind failure. Any of these still counts the failed attempt as a `bind` exclusion. Reserving ports with `ip_local_reserved_ports` is a system change and is not allowed here.

### M2 (medium, latent): an initialization failure in a fault, kill or stalled cell would be excluded, not scored

- **Where.** `score.py:100-111`. The checks for "fault not applied" (`no_fault`), "no kill in the traffic" (`no_kill`) and "rounds not overlapping" (`cond_order`) run before `init_fail` is looked at.
- **Failure scenario.** Two processes on one GPU fail to create the devComm in, say, `mr4_f1_02`. Then:
  - the hook never fires, because its timer starts at the GDAKI context creation;
  - `fires` is empty, so the trial becomes `no_fault`;
  - section 8 says to fill it, so it gets silently replaced.

  The same failure in a kill cell gives `kill_in_traffic = 0`, so `no_kill`. In a stalled cell it gives an empty `cyc_spread_ms`, so `cond_order`. Section 8 says "초기화 실패(`init_fail == 1`)는 제외하지 않는다". Only `mr4_none` (I1) would ever count such a failure. This hides the failure mode the study is about, and it hides it in the favourable direction.
- **Effect on this run.** None: `init_fail = 0` in all 135 non-bind trials, and both `init_fail = 1` trials are the bind failures `[측정]`.
- **Fix.** Test `init_fail` (as "candidate, scored") before the fault, kill and order exclusions. Alternatively, report init failures of every cell in SCORE.md even when they are excluded.

### L1 (low): `surv_tx_failed` and `surv_rx_failed` count an empty result as "not failed"

- **Where.** `rows_mr.py:373-374` use `not in ("no error", "")`. Section 3.1 defines the columns as "결과가 `no error`가 아닌 수". An empty result is not `no error`.
- **Effect.**
  - On the context-wide flush kill rule (K3, needs 6), an empty result can only lower the count, so it is conservative.
  - On the per-peer flush kill rule (K5, needs `surv_tx_failed == 0`), a missing sender line would pass that half. It cannot make K5 pass vacuously. The per-edge lines of a rank are written together and only when its kernel finished (`gin_mr.cu:645-737`). A rank without sender lines also lacks receiver lines, so `surv_rx_failed == 6` fails.
  - All 60 survivor sender results per kill cell are present `[측정]`. In the per-peer cell they are `tx_done=1000`, `no error`. In the context-wide cell they are 521–527 iterations with `remote process exited ...`.
- **Fix.** Count `""` as failed, or add a column for missing edge lines.

### L2 (low): the "no overlap" rules for one helper (E2, and `init_overlap_r0` in F3) are close to true by construction

- **Where.** `rows_mr.py:363-366` take `[t_req, t_resumed]` from the responder's recovered line. In the hd source, `t_req` is `t0 = gdakiQ4MonoMs()` at the start of `gdakiTsRespond` (hd `gin_host_gdaki.cc:4759`). That is when the single helper thread starts handling the REQ, not when the REQ reached the socket `[소스]`.
- **Effect.**
  - Two intervals of one helper overlap only if that helper handles two REQs at once. So the rule tests single-threadedness. It cannot see a REQ that waited in the socket.
  - The verdict (10/10) stands as a statement about the column, but it is weak evidence for hypothesis H3's "two rounds of one helper do not overlap in time".
  - The informative number is the gap. In `h5/mr4_f1_10_30_n1`, the second `t_req` comes 1.1 ms after the first `t_resumed` `[측정]`: the second REQ waited.

### L3 (low): the "not transparent" half of the cycle rule (Y1) is guaranteed by the driver

- **Where.** `cells.sh:20` sets `GIN_TS_RX_WAIT_S=10`. The receiver returns `ncclTimeout` after 10 s without its signal (`gin_mr.cu:270-285`).
- **Effect.** The cycle holds its edges for about 24.5 s. The receivers on those edges therefore fail at about 10 s whatever the library does, and `transparent_ok == 0` follows. The informative half of Y1 is `n_hs >= 1`, which is also required. No verdict changes. In the write-up, do not cite "not transparent" as evidence of the cycle.

### L4 (low): a decline after a rank's kernel ended does not change that rank's outcome

- **Where.** The async monitor stops 0.3 s after this rank's kernel is done (`gin_mr.cu:743-752`). There is no barrier among ranks before `ncclCommAbort` (`gin_mr.cu:760-762`), so ranks tear down independently.
- **Effect.** A late decline (for example one caused by teardown order) would leave `outcome=ok` and `transparent_ok=1`. Rules that use `transparent_ok` alone (I2, I4, I5, I6, A2, F2) would not see it.
  - Their sibling rules check `n_decl == 0` in the same cells.
  - `n_decl` is 0 in every scored trial of every fault-free, latency and recovery cell `[측정]`.
  - No effect here.
- **Fix (optional).** Add `n_decl == 0` to the definition of `transparent_ok`, or a final TCP barrier before the abort.

### L5 (low): a duplicate delivery after the final signal read is not seen

- **Where.** The receiver host reads the final signal right after its kernel ends (`gin_mr.cu:716-724`). A replayed duplicate put carries the same data as the original.
- **Effect.** A duplicate is caught only if its signal lands before that read. In this run every recovery round ends seconds before the traffic ends: hooks fire at about 6 s of 15 s and rounds end within 1–3 s. A duplicate would therefore raise the signal above `base + iters` before the read. The open window is the last iteration only. No effect expected `[추론]`.

### L6 (low): the mlx5 stop rule compares counts and accepts an empty snapshot

- **Where.** `hold.sh:24-31` and `hold.sh:87-91`. The stop fires only if the sum of command-error lines and firmware-failure counters grows.
  - If the dmesg ring rotates an old matching line out while a new one comes in, the sum stays equal.
  - If `sudo -n dmesg` or the debugfs read fails, both snapshots give 0 and the rule passes.
- **Effect here.** None. In all 8 holds:
  - the before and after mlx5 files are byte-identical (16 identical md5s per node);
  - `mlx5_new_*.txt` are empty;
  - rain's failure sum was read as 31 before and after every hold `[측정]`.
- **Fix.** Stop on any line in `mlx5_new_<hold>.txt` that matches the filter, and stop when a snapshot file is empty.

### L7 (low): two section 8 rules are not enforced by the code

- **Config checks are scorer-only.** The configuration checks are evaluated only by `score.py` after the run. `cells.sh` and `hold.sh` never stop a hold on them, although section 8 says "그 hold를 멈추고". No config failure occurred: every trial passed the checks, including `n_hd == n_ow == n` `[측정]`.
- **The refill cap is missing.** The rule "채우려고 다시 돈 시행이 셀마다 계획의 50%를 넘으면 자료 부족" is not implemented in `score.py`. Here there was 1 refill of 10 in two cells, so no effect.

### L8 (low): the empty-field rule of the imported grammar makes `!=` vacuous

- **Where.** `score.py:112-123` compare `val(x) != n`. The imported `Nil` returns False for `!=` (`../s2_close/score.py:80`), so an empty field would pass a config check.
- **Effect.** It cannot happen today.
  - `n_ts_on`, `n_ua`, `n_pr`, `n_pc`, `n_ow` and `n_hd` are always integers.
  - `gq_min` and `gq_max` are empty only when `n_ts_on == 0`, which the first check catches.
- **Fix.** Compare with `!= n or not isinstance(...)`. The same `Nil` trap applies to any future rule written with `!=`.

### L9 (low): device wait bounds count SM cycles under GPU time slicing

- **Where.** `gin_mr.cu:528-529` convert seconds to cycles with `cudaDevAttrClockRate`. The library's bounded waits compare `clock64()` deltas (`gin__funcs.h` `waitRollingLessEq`).
- **Effect.** How `clock64` behaves while a context is switched out, or if a CTA resumes on another SM, is `[미확인]`. An early timeout could only make an edge fail, so it is conservative. A late one only delays the failure. No spurious timeout was seen: all fault-free trials are transparent `[측정]`.

## Nits

- **Hard-coded node addresses.** `run_mr.sh:36-37`, `hold.sh:15` and `deploy_mr.sh:14` hard-code the node addresses, as the already merged `../oneway/*.sh` scripts do. I did not compare them with the protected management address, because reading `~/.config/rdma-error/` is not allowed `[미확인]`. The pre-push hook is the check.
- **Hook coverage is not recorded.** `RE_FIRE` (`rows_mr.py:74`) parses `moved X/Y` but keeps neither number, so a partial hook would count as applied. All 110 fire lines moved every QP (3/3, 2/2 at three ranks, 36/36 for every context) `[측정]`. A `fire_moved_all` column would make this a rule.
- **Error strings are cut at the next `NAME=`.** `kvfile` (`rows_mr.py:85-91`) splits values at the next ` NAME=`. An `ncclGetErrorString` text that contains `NCCL_DEBUG=INFO` would be cut short. It is never `no error`, so this is harmless.
- **Y2's column measures from the first round line.** `hs_first_after_round_ms` and `decl_after_round_ms_r<r>` (`rows_mr.py:332-344`) measure from the rank's first round line, not from the round that timed out. In `mr4_cyc_stall_n1`, rank 0's timeout belongs to its full-scope rerun: 322 ms after that line, 24 826 ms after its first. Y2 uses the earliest timeout. In all 5 cycle trials that one was the only round line of its rank before it (24 504.5–24 507.2 ms) `[측정]`, so Y2 is unaffected.
- **The idle ranks in the solo latency cell are not inert.** In `mr4_lat_solo`, ranks 2 and 3 have no edge. They start their abort about 300 ms after launch, after rank 0's 38–40 ms latency kernel, so the two do not overlap `[측정]`. Even so, the solo cell's maximum was 207–217 µs in all 5 runs (iterations 184–739), against 15–22 µs in `mr2_lat` `[측정]`. The cause is `[미확인]`. L2 and L3 use p50, so there is no verdict effect. The basis "no GPU sharing" for L2 is slightly too strong.
- **The connect retry outlives the watchdog.** The connect retry bound (`t > 600`, 120 s, `gin_mr.cu:468`) is longer than the 60 s global watchdog, so it never acts.

## Checked and found sound

- **Traffic per edge.** One CTA per directed edge, its own GIN context `ctx(a,b) = a(N-1) + (b<a ? b : b-1)`, at most one outstanding put per edge (put, flush, gap), a per-edge data seed, and a poisoned receive window filled before a TCP barrier. Signal bases are read before that barrier too (`gin_mr.cu:561-606`).
- **CTA ordering.** `flush(coop)` and the timed `waitSignal(coop)` both begin and end with `coop.sync()` (hd `gin__funcs.h:980-988, 1394-1405`) `[소스]`. Thread 0's `put` and `sRc = 0` are therefore visible before any thread flushes. The receiver's device check also runs after the signal is acquired. There is no race on `sRc` or `sBad`.
- **Ok/failed per edge.** An edge is ok only if all of these hold, which is section 3.1's definition (`rows_mr.py:229-231`):
  - sender done == iters and `no error`;
  - receiver done == iters and `no error`;
  - device bad slots 0 and host bad slots 0;
  - the final signal exactly `base + iters`.

  A stuck kernel writes no edge lines, so all its edges are bad. Lost data, a lost signal and a duplicate before the final read each make the edge bad.
- **Hook targeting.** The hook moves only context `c`'s QPs (`qp_idx = r + c*nranks`, hd `gin_host_gdaki.cc:676-695`) `[소스]`. The device context index maps one-to-one to it here: the teardown epoch and QP-state lines put the round at the intended context in A3, B2, C3, D2, E3 and T1, and the round lines name the intended peer `[측정]`. `fires` matched the planned rank and context in all 110 fire lines.
- **Kill.** The SIGKILL goes only to the recorded `gin_mr` PID after a `/proc/<pid>/stat` name and parent check (`run_mr.sh:81-103`). Survivors declined 5.99–8.95 ms after the kill on rank 0's clock; clock-offset RTT is 0.02–0.11 ms `[측정]`, so K2's lower bound of 0 has margin. `kill_in_traffic = 1` in all 20 kill trials.
- **Two processes per GPU.** Every rank of every non-bind trial reports the node's single GPU (`pci_bus=0000:65:00.0` on both nodes) `[측정]`. Both nodes ran with compute mode `Default` in every snapshot.
- **Settings reached the driver.** Each rank's kv shows the meta's `flush`, `mode`, `iters` and `gap_us`, plus `rx_wait_s=10.0`. `grace_ms` is 40 000 in the kill and stalled cells and 2 000 elsewhere. There is no mismatch in 135 trials, and all 137 trials ran `lib=hd`, `mrkey=hd` `[측정]`. The deployed hd driver comes from source md5 `fd90b11f`, the same as `gin_mr.cu` at the tag.
- **Log patterns behind zero-count rules.**
  - `escalated rank=`, `more than NCCL_GIN_TS_FW_MS`, `(NCCL_GIN_TS_COPY_MS)`, the two `cancelled` lines, `watchdog rank=` and `judged dead` match the hd format strings (hd `gin_host_gdaki.cc:1287, 2754, 2772, 3036, 4224, 4272, 4294`) `[소스]`.
  - The research build prints every `GIN_TS_NOTE` at WARN.
  - `judged dead` occurs 30 times in each kill cell, `refused` once in each chain trial, and `declined` in the kill and cycle cells. So those patterns are live `[측정]`.
- **Teardown lines.** Epoch lines and QP-state lines are printed in the same loop (hd diff 3313-3338). Every rank that was not killed printed n-1 of each in every trial `[측정]`. F3's `n_notrts == 0` is therefore tied to `n_ep_nz == 72`.
- **Leftover processes and bounds.** `left = 0` in all 137 trials and `LEFT_STREAK = 0`. The bounds are:
  - each rank `timeout -s KILL 80` (its own process group);
  - the driver's 60 s watchdog;
  - each hold `timeout -s KILL 880`, inside `cluster_run.sh -w 10800`.

  Nothing is killed by name.
- **Section 3.1 columns.** These match the definitions:
  - `transparent_ok`, `fires`, `fire_in_traffic`, `rounds`, `rec_*`, `decl*`, `n_watchdog`, `n_refused`;
  - `ep_nz`, `notrts`, `q4_first`, `killed`, `kill_ms0`, `kill_in_traffic`, `decl_after_kill_ms_r<r>`;
  - `f3_detect_ms`, `win_edge_r0`, `w_<ab>_in`, `cyc_spread_ms`, `rec_first/last_after_round_ms`, `knob_stall`;
  - `p50_01`, `p50_inter_med`, `max_all`.

  The exceptions are noted under L1 and in the nits.
- **Section 8 exclusions.** Bind, fault not applied, no kill and order are implemented as written, except for the init-failure order in M2. Only the 2 bind trials were excluded. No surplus or config statuses occurred.

## Changes after the tag

- `git -C /home/unionxic/rdma-error-wt/gin-multirank diff prereg/gin-multirank-v1 -- harness/gpu-initiated/gin_recovery/multirank/` is empty, and HEAD is the tag commit `460488de`.
- `../s2_close/score.py`, `../scripts/ts1/fwcmd_snapshot.sh` and `../../common/cluster_run.sh` are also unchanged against the tag. `../s2_close/score.py` is the same on master.
- The only untracked content is `results/`.
- `predictions.csv` sha256 `3a35b6db...` equals `PREREG.txt`.
- The tag was made at 03:40:58. The first main hold started at 03:41:05 (`results/20261009/chain.out`).
- Nothing that affects scoring changed after the tag.
