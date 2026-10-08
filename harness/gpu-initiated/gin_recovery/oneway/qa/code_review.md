# Code review: one-way outage liveness fix (gin-oneway)

Independent review, 2026-10-08. Read-only: only this file was added; nothing was built or run on the cluster.

**What was reviewed** [measured].
- [pcm_layer.diff](../pcm_layer.diff) (md5 `c2fc15fb`, the two test switches, on the gin-pair-check tree) and
  [ow_layer.diff](../ow_layer.diff) (md5 `06f450ec`, the fix, on the `pcm` tree), read in full context in the session scratch tree
  `agent_ts2ow/nccl-src`. In that tree `git diff HEAD^ HEAD` and `git diff HEAD` are byte-identical to the two layer diffs.
  The working file (md5 `b63f505d`, mtime 15:17:06) predates its object (15:17:23) and the library (15:17:25). `out/ow` and
  `out/pcm` have md5 `b4af65c5` and `cd72f67a`, the libraries in [deploy_check.txt](../deploy_check.txt).
- The runner change, commit `b5993795` (`../../scripts/ts2/run_trial.sh` 99–123), and its only caller, [cells.sh](../cells.sh)
  line 37.
- Raw logs, kv, meta and kill files under `results/20261008/` (125 trials: `ow` 80, `pcm` 20, `pc` 5, latency 20) and
  `results/20261008_smoke/` (15).

Line numbers are in `src/transport/net_ib/gdaki/gin_host_gdaki.cc` of the `ow` tree unless a file is named. Tags: [measured]
counted from the raw logs, [source] read in the code, [inferred] reasoning (Linux TCP behaviour included, not checked against
kernel source), [unverified].

## Summary, ranked

| # | Severity | Where | Finding | Could it have changed the measured results? |
|---|---|---|---|---|
| 1 | risk (medium) | 2536, 2672–2677, 2699–2702, 2738–2744, 2765–2769 | One refused connect is taken as proof that the peer process is gone. A firewall REJECT rule refuses too. With the immediate probe, a live lower rank behind such a rule is now dead on the higher rank within one round trip of the loss (the lower rank's re-dial already did this); neither side ever revives the other | No. All 15 refusals are in the two kill cells, each with a kill record |
| 2 | risk (medium) | 3529, 3539, 3685, 3703, 3804 | A reset that first shows up inside a round still ends the pair for good (`gone`, then a terminal decline). Section 4 excludes this path but names one trigger; there are three, and one of them (the 1000 ms HELLO-ACK bound) is new | No. No round in any trial failed on its socket |
| 3 | risk (low) | 2787–2790 | The lower rank closes a PROBE without looking at its own socket to the prober. A probe means the higher rank has lost the connection; a lower rank that still holds its side keeps it until its keepalive draws a reset (≈2–3 s), which delays the reconnect and opens a window for 2 | No. In every outage trial both ranks logged their own loss before the reconnect |
| 4 | risk (low) | 2725–2737, 2633–2634, 2792–2822 | An answered connect is not proof of a live peer: the dead peer's port taken by another listener, or the listen socket inherited by a forked child. The dead peer then stays unknown for good. HELLO and HELLO-ACK carry no nonce, so a re-dial that reaches another job's helper with matching rank and context number is accepted on both sides | No (no foreign listener expected; every unknown in `ow` ended) |
| 5 | nit | 2629, 3339 | A pending re-dial (and a dial, as before) stays open when the peer is declined. If the higher rank already installed it, it holds a live, silent socket and its next fault ends "handshake timeout" after the round bound (≈24.5 s) | No. No decline in `ow` while a peer was unknown |
| 6 | nit | 2603–2610, 2687–2690, 2754–2757, 2786 | No cap on retries: a refused re-dial logs one WARN per attempt every 500 ms for as long as the higher rank refuses; probes and dials run every 500 ms for as long as the peer is unknown | No. 11 "not accepted" lines in all, one per HELLO refusal trial (10 main, 1 smoke) |
| 7 | nit | 2430–2442, 3359–3366 | A failed send on a reset socket consumes the socket error; the idle loop's next read then reports `cause=FIN liveness=dead` | No. Every FIN death line follows the peer's teardown or kill |
| 8 | nit | 2051, 2056–2057, 2412, 3619, 4008–4010, 4175–4180 | Outdated comments and one decline wording; the listen socket is now load-bearing on every rank | No |
| 9 | nit | 2400–2407, 2800–2806, 4267–4274 | Test switches: not reachable by accident in practice; a few sharp edges | No. Switch lines only on the intended rank of the three intended cells |
| 10 | nit | `run_trial.sh` 107–122 | `KILL_R0` can only hit a direct child named `gin_ts2` of the runner's own `timeout`. Residual PID-reuse window of one Python start-up; `meta.txt` does not record the switch | No. 18/18 kill records name the PID in the rank 0 log |

## Details

### 1. A refused connect is taken as proof of death (risk, medium)

- [source] `connectRefused` makes `gdakiTsSocketLost` return dead (2536). It is set at four connect sites: the lower rank's re-dial
  (2672–2677 asynchronous, 2699–2702 synchronous, as before this change) and the new probe (2738–2744, 2765–2769). One refusal
  decides; there is no second attempt.
- [inferred] A connecting socket reports ECONNREFUSED for a TCP reset to its SYN (no listener), and also for an ICMP port
  unreachable, the default answer of an iptables `REJECT` rule (`--reject-with tcp-reset` gives the reset itself). An address now
  held by another host gives the same.
- **Scenario.** A host firewall reload or an isolation rule rejects the management traffic between rain and sunny for 10 s.
  - Both helper sockets time out (ETIMEDOUT, or ECONNREFUSED as a soft error): unknown on both. Correct.
  - Rank 1 probes at once: refused, rank 0 is dead. Rank 0 re-dials at once: refused, rank 1 is dead. Rank 0 then stops dialing
    (`!pe.unknown`, 2629), so the HELLO that would revive rank 1's view (the accept path ignores `gone`) never comes.
  - Both ranks were alive throughout. In `pc` the higher rank stayed unknown and declined after the bound; now both decline at
    once as dead, for good.
- Section 4 keeps firewall changes out of the measurement, but section 9 item 1 justifies the rule as "no listener on the port",
  which is only one source of the error.
- **Suggestion.** Set `IP_RECVERR` on dial and probe sockets and read `MSG_ERRQUEUE` after a refusal: `SO_EE_ORIGIN_ICMP` means the
  network, a plain reset means the host. Or count death only after refusals on two attempts at least one interval apart, and let a
  refused lower rank keep dialing at a slower rate.

### 2. A reset seen inside a round still ends the pair (risk, medium)

- [source] Inside a round every socket failure sets `gone` and declines: REQ send (3685), handshake read (3703), ACK send (3529),
  DONE read (3539). A failed DONE send sets `gone` without a decline (3804). A decline is terminal (`declined`, 3339) whatever the
  cause. The new table (2519–2525) is used only by the idle loop and the liveness peek.
- Three ways a live peer's reset reaches a round [inferred]:
  - **(a) A HELLO-ACK later than 1000 ms (new).** The higher rank installs and, with a fault waiting in its reconnect wait, starts
    its round at once (3605–3609). If the HELLO-ACK reaches the lower rank more than 1000 ms after the HELLO (the ACK segment
    retransmitted twice, or a new outage starting right after the reconnect), the lower rank resets the attempt (2643, 2596–2600)
    and the higher rank reads ECONNRESET during the handshake: dead. Before the fix the same sequence ended reconnected.
  - **(b) A side that never saw the loss.** A symmetric outage that ends between the two ranks' timeouts (tens of ms apart in the
    gin-reconnect runs) leaves one side holding a socket whose other end is gone (that end's reset was lost). Until this side's next
    keepalive draws a reset (≤1 s in probe mode) or a re-dial replaces the socket, a fault on it sends a REQ into a closed
    connection: reset, dead. The liveness peek (2558–2579) cannot see it, because nothing has arrived yet.
  - **(c) A stale accepted attempt whose reset was lost.** The HELLO-ACK send (2813) rejects an attempt that the lower rank has
    already reset, but only if the reset arrived. If it was lost, the attempt is installed and a round on it fails the same way.
- Section 4 names (a) only, as "the higher rank still uses a connection whose HELLO-ACK the lower rank lost"; (b) and (c) are not
  mentioned.
- **Suggestion.** For reset-class errors inside a round (the unknown set), abort the round as the pair-check rerun does
  (`ncclGinRecoverAbort`, requeue), mark the peer unknown and let the requeued fault wait for the reconnect; keep the decline for
  FIN. At least widen section 4's exclusion to (b) and (c).

### 3. A PROBE tells the lower rank nothing (risk, low)

- [source] The accept path closes a PROBE before any check (2787–2790). Only a higher rank with no socket to this rank probes
  (2711), so a lower rank that still holds `pe.fd` to the prober holds a dead connection.
- **Scenario** [inferred]: path (b) of finding 2 with the higher rank the first to time out. The higher rank probes every 500 ms
  and is answered; the lower rank does not re-dial until its keepalive (idle 2 s, interval 1 s) draws a reset from the higher
  rank's kernel. A fault on the lower rank in that window sends a REQ into the dead connection (finding 2).
- A lower rank that has declined the prober also answers every probe, so the higher rank waits the full bound for each fault
  before declining "unknown" (as before the fix, which did not probe).
- **Suggestion.** Put the prober's current generation in the PROBE (`round`). When `from` is a gated higher peer with `pe.fd >= 0`
  and the same generation, treat the PROBE as a reset: close the socket as unknown and re-dial at once. The generation guards
  against a PROBE that waited in the accept queue past a reconnect. Answer a probe from a declined peer with FAIL.

### 4. An answered connect is not proof of a live peer (risk, low)

- [source] An answered probe changes nothing (2725–2737) and probes repeat every 500 ms while the peer is unknown; a re-dial that
  connects but gets no matching HELLO-ACK is retried. The sockets are not close-on-exec (no `SOCK_CLOEXEC` or `FD_CLOEXEC` in the
  file).
- [inferred] After a rank dies, its ephemeral listen port can be taken by any later listener on that host. The dead peer then
  never becomes dead: every fault waits the full bound and declines "unknown", and probes or dials continue until a decline.
  - If the new owner is another job's GIN helper, a PROBE is closed quietly. A HELLO passes 2792–2799 if its `from`, context number
    (0 in most jobs) and generation fit; that helper then sends a HELLO-ACK and replaces its own live connection to rank `from`
    (closed with a FIN, so a live peer of the other job becomes dead). Our lower rank installs too when that helper's rank equals
    the dead peer's (2633–2634). The HELLO-ACK echoes only values the receiver sent, so it authenticates nothing (gin-reconnect
    review items 3 and 5).
  - A forked child that inherited the listen socket keeps the port answering after the rank dies; it also keeps the established
    sockets open, so no FIN or reset arrives at all (as before the fix).
- **Suggestion.** A per-communicator nonce from the setup all-gather in HELLO, HELLO-ACK and PROBE; a cap on how long a peer may
  stay unknown before it is declined.

### 5. A pending re-dial outlives a decline (nit)

- [source] The lower rank's loop skips declined peers before it looks at `pendFd` or `dialFd` (2629), so both stay open until
  `gdakiTsStop`. The probe loop closes its socket in the same case (2711–2716).
- **Scenario** [inferred]. The path comes back at the end of the lower rank's 10 s wait; the HELLO-ACK arrives one step after the
  bound and the lower rank declines "unknown". The higher rank sent the ACK and installed the socket. It now sees a quiet, healthy
  connection (the lower rank's kernel answers keepalives) and runs its next round on it. Nobody reads the REQ, so the round ends
  "handshake timeout" after the rest of the round bound (`gdakiTsRoundLeftMs`, ≈24.5 s with the defaults), device waiters held,
  instead of the 10 s unknown wait.
- **Suggestion.** On a decline, and whenever the loop skips a peer, close `pendFd` with a reset and close `dialFd`.

### 6. Retries and their log lines have no cap (nit)

- A higher rank that refuses every HELLO (it declined the peer) gets one attempt every 500 ms (2687–2690), and the lower rank
  logs a WARN for each (2608): about 7 200 lines an hour until the lower rank declines too, which needs a fault toward that peer.
- Probes and dials run every 500 ms while the peer is unknown, with no end other than a reconnect, a refusal or a decline. The
  receiver reads each accepted connection with a blocking 500 ms bound (2786), as in gin-reconnect review item 5; the probe adds
  one such connection per unknown pair and interval. Negligible at two ranks [inferred].
- **Suggestion.** Back off after a few failures, and log "not accepted" once per cause per loss.

### 7. A failed send hides the reset from the next read (nit)

- [inferred] `send` on a reset socket returns ECONNRESET or EPIPE and clears the pending socket error. The connection is already
  closed, so the next `recv` returns 0, which `gdakiTsPumpRaw` reports as FIN (2471–2473), and the idle loop logs
  `liveness=dead`.
- The idle-time send that can hit this is the FAIL of a decline (3359–3366). The peer is already declined, so only the log line
  and the `n_dead` columns are affected.
- [measured] Not seen: the 60 FIN death lines on rank 1 in `ow` come 0.7–1.7 ms after rank 0's teardown start (rank 0 clock, kv
  `clock_offset_ms`); the other 5 (rank 0, `f4_b`) follow the rank 1 kill.

### 8. Comments, wording and the listen socket (nit)

- 2051 ("FIN/RST seen"), 2056–2057 ("`gone` stays the dead state (FIN, reset, refused re-dial...)") and 4008–4010 ("evidence of
  death (FIN, reset, ...)") describe the old rule; 2412 says "within about 5 s", 20 s with the test switch.
- 3619: after a refused probe the decline reads "the peer's socket shows ECONNREFUSED", although the socket was closed as unknown
  and the refusal came from the probe.
- Every rank keeps its listen socket (4175–4180), and the probe now tests exactly that socket. gin-reconnect review item 5
  suggested closing it on ranks with no lower peer; doing so now would turn every probe of rank 0 into a death verdict.

### 9. Test switches (nit)

- Not reachable by accident in practice: both names carry `TEST`, either one prints a WARN line at start (4271–4273), and the
  settings check of `EXPERIMENT.md` section 8 requires that line on the intended rank only. With both unset, `pcm` runs the `pc`
  code path (default timeout 5000 ms, refusal branch skipped) [source].
- Edges [source]:
  - NCCL copies the entries of `NCCL_CONF_FILE`, `$HOME/.nccl.conf` and `/etc/nccl.conf` into the environment (`misc/param.cc`
    27–66), so a conf file can set them too.
  - The timeout is read once per process (2400–2407) and applies to the setup sockets and to every communicator. Any positive
    value is accepted: `1` makes every helper socket time out within milliseconds and every peer unknown for good.
  - The refusal count is per GIN context.
  - Both switches are compiled into `ow` as well (section 9 item 2), so that library is test-only as built.
- [measured] The switch line is in exactly 15 rank logs per cell (10 `ow`, 5 `pcm`): rank 0 of `ow_r1in_f1_b` (`uto_ms=20000`),
  rank 1 of `ow_r0in_f1r1_b` (`uto_ms=20000`), rank 1 of `ow_hello_f1_b` (`refuse_hello=1`); nowhere else.

### 10. Runner `KILL_R0` (nit)

- [source, inferred] `R0PID` (110) is the `timeout` process: bash forks once for the background job, and `env` and `stdbuf`
  exec. `pgrep -P "$R0PID" -x gin_ts2` (112) matches only a direct child of that process with that exact name, so another user's
  job, another `gin_ts2` on rain or rank 1 cannot match. Only [cells.sh](../cells.sh) line 37 sets the switch, as a prefix to a
  function call, which bash keeps to that call.
- Residual:
  - Between `pgrep` (112) and `os.kill` (114) a Python interpreter starts (tens of ms). If rank 0 exits on its own in that window
    and its PID is reused at once, a process of this user could get the SIGKILL. rain's `pid_max` is 4 194 304, so reuse that fast
    is not expected.
  - If rank 0 exits before the delay, `R0PID` may be reaped and reused; `pgrep -P` then needs a `gin_ts2` child of the new process.
  - The kill comes `KILL_DELAY_MS` plus `pgrep` and Python start after launch; `kill_mono_ms` is the time to use.
  - `meta.txt` records neither `KILL_R0` nor `KILL_DELAY_MS`. `FAULT=F4` with `KILL_R0=1` would kill both ranks with the same
    delay, unguarded.
  - The cleanup `pkill -x gin_ts2` (132) is broader than this switch (any `gin_ts2` of this user on rain); it predates this commit.
- [measured] 18 rank 0 kill records (15 main, 3 smoke), all in `ow_kill0_b`; in each, `pid=` equals the PID in the rank 0 log
  prefix. `left=0` and `r0rc=137` in all 15 main trials.

## Observation (not a defect)

Rank 0's re-dials and rank 1's probes both start at the loss and repeat every 500 ms. In the one-way cells the two ranks lost
the socket within 0.15 ms of each other (rank 0 clock, n=25), so after the outage the first re-dial and the next probe are a
near tie [measured]. "probe answered" is in 0/10 `ow_r0in_f1r1_b`, 0/5 `ow_r0in_nat_f1r1_b` and 4/10 `ow_r1in_f1_b` trials, but
10/10 `ow_hello_f1_b` (where the first re-dial is refused). No prediction uses this count; it is not a stable measure.

## Checked and found correct [source]

- **Classification.** Causes on an established socket go through 2519–2525 exactly as the table of section 9 item 1;
  `connectRefused` comes only from the four connect sites. A live helper sends FIN on an installed socket only at teardown:
  refusals close unconfirmed sockets, which the pending path reads as "not accepted" (2642), and `gdakiTsInstall` closes an old
  socket only after a newer HELLO, which the lower rank sends only after it closed its own side. A dying peer that resets instead
  of closing (unread data) is unknown until the immediate re-dial or probe is refused [inferred].
- **HELLO-ACK.** One attempt at a time per peer (dial, then pending, then the next dial). Install only on a record with the peer's
  rank, this context number and the attempt's generation (2633–2634). `gdakiTsPumpRaw` reads at most one record, so a REQ sent
  right after the ACK stays for the main loop. A refusal, a failure or an unexpected reply ends the attempt with a reset
  (2596–2610). The generation grows with every HELLO sent (2659), and the higher rank's generation is always one the lower rank
  sent, so `h.round <= gen` (2794) never refuses a live lower rank's next HELLO. A queued attempt that the lower rank already reset
  fails at the HELLO-ACK send (2813–2817) and is not installed. Only the lower rank dials, so dials never cross. The higher rank
  closes its probe when it installs (2818–2821).
- **Probe.** Only toward gated, unknown, undeclined lower peers with a kept address (2711, 4171–4172); closed when the peer leaves
  that state; one in flight per peer; non-blocking connect bounded by 500 ms; PROBE send bounded by 50 ms; first probe at the loss
  (2546). It runs only from the helper loop and the reconnect wait, never inside a round. In the wait a refusal ends the wait
  `dead` (3606–3608).
- **Teardown and abort.** `gdakiTsStop` closes the pending and probe sockets after the join (4499–4506). No new wait is unbounded;
  the accept read still checks `stop`.
- **Threads.** All new peer state is touched only by the helper thread (`gdakiTsReconnectStep` from `gdakiTsMain` and from the
  wait in `gdakiTsInitiate`). Setup writes the addresses and `gdakiTsTestKnobs` the refusal count before the thread starts;
  `gdakiTsStop` reads after the join. The timeout value is a function-local static (thread-safe initialisation).
- **Mute switch.** Pending and probe sockets get the filter while the mute is on (2760, 3944–3945) and lose it at mute-off
  (3958–3959).

## Effect on the measured results [measured]

Nothing above changes a measured result. Counted from the 125 main and 15 smoke trial pairs:
- **Death lines in `ow`.** 75 in all: 60 FIN on rank 1, each 0.7–1.7 ms after rank 0's teardown start; 5 FIN on rank 0 in `f4_b`
  (rank 1 killed); 15 ECONNREFUSED, 10 on rank 1 in `ow_kill0_b` (probe refused, rank 0 killed) and 5 on rank 0 in
  `rc_mutekill_b` (re-dial refused, rank 1 killed). No other cause is classified dead.
- **Unknown lines in `ow`.** In every outage trial each rank logged exactly one unknown close before its reconnect:
  `ow_r1in_f1_b` rank 0 ECONNRESET and rank 1 ETIMEDOUT (10/10); `ow_r0in_f1r1_b` and `ow_r0in_nat_f1r1_b` rank 0 ETIMEDOUT and
  rank 1 ECONNRESET (15/15); ETIMEDOUT on both ranks in the cells muted on both sides.
- **Rounds.** No decline names a socket failure inside a round ("during the handshake", "before DONE", "cannot send"), in any
  build, main or smoke. `ow` declines: 15 ECONNREFUSED (kill cells), 5 FIN (`f4_b`), 5 REM_ACCESS and 5 "the peer declined"
  (`f2rel_b`); none "unknown". Reconnect waits in `ow`: 15, all `reconnected` (`ow_r0in_f1r1_b`, `ow_r0in_nat_f1r1_b`).
- **Handshake.** "not accepted" 11 (10 main, 1 smoke), all `(FIN)` after the test refusal, each followed by a reconnect at
  `gen=2`; no timeout or unexpected-reply cause.
- **Probes.** Refused 10 (all `ow_kill0_b`), answered 15 (10 `ow_hello_f1_b`, 4 `ow_r1in_f1_b`, 1 `rc_mute8_f1_b`).
- **Switch lines and kills.** As in 9 and 10.

## Paths no trial ran

- A HELLO-ACK later than 1000 ms, an unexpected reply, a failed HELLO-ACK send (findings 2a, 2c).
- A reset or refusal inside a round; a side still holding its socket after the other dropped it (2b, 3).
- ECONNABORTED, EPIPE, ECONNREFUSED, EHOSTDOWN, ENONET, EHOSTUNREACH or ENETUNREACH on an established socket.
- A refusal not caused by a missing listener (1); a reused port or a forked child (4).
- A decline while a re-dial is pending (5); more than one refused HELLO in a row (6).
- The higher rank replacing a socket it still held; a second loss (generation above 2).
- More than two ranks (several unknown lower peers, a probe during a round with another peer).
- The logs do not tell the synchronous refusal sites (2699–2702, 2765–2769) from the asynchronous ones.
