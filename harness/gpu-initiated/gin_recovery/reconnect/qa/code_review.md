# Code review: helper-socket reconnect layer (gin-reconnect)

Independent review, 2026-10-08. Read-only: no file of the study was changed, nothing was built or run on the cluster.

**What was reviewed.** [rc_layer.diff](../rc_layer.diff) (md5 `fb72ffd3`) on top of the gin-s2-close tree, read in full context in
the session scratch tree `agent_ts2rc/nccl-src` [measured]:
- `git diff` of that tree against its `s2r` commit is byte-identical to `rc_layer.diff`.
- The source file (mtime 10:50:13) predates the object and the library (10:50:19, 10:50:20). The built `libnccl.so.2.32.3` has md5
  `8354411f198e9d980b8b3459918afbea`, the library deployed and measured ([deploy_check.txt](../deploy_check.txt)).

Line numbers are in `src/transport/net_ib/gdaki/gin_host_gdaki.cc` of that tree. Tags: [measured] counted from the raw logs under
`results/20261008/`, [source] read in the code, [inferred] reasoning (Linux TCP behaviour included, not checked against kernel
source), [unverified].

## Summary, ranked

| # | Severity | Where | Finding | Could it have changed the measured results? |
|---|---|---|---|---|
| 1 | risk (high) | 2318–2322, 2343–2345, 2402 | A kernel RST sent after the other side timed out counts as death. With loss in one direction (rank 0 to rank 1) the lower rank lands in "dead" and never re-dials, the higher rank waits for a dial forever: a live peer is declined on both sides, permanently | No. In every mute trial both ranks closed with ETIMEDOUT at least 3 198.9 ms before their own mute ended (or the mute never ended) |
| 2 | risk (medium) | 2417–2420, 2472–2482 | The lower rank installs the new socket as soon as its HELLO is in the send buffer, before the higher rank accepts it. Any refusal, or a HELLO slower than 500 ms, makes the higher rank close it; the lower rank then reads FIN and marks a live peer dead, permanently | No. Every rank 0 reconnect line has a rank 1 line (20/20 trials) |
| 3 | bug (latent) | 3682, 3737 | The context number is a process-wide creation counter, now checked at setup. Processes that create GIN devComms for different numbers or orders of communicators disagree: the higher rank refuses the setup HELLO, stalls 15 s and runs with recovery OFF while the lower rank runs ON and declines every later fault "shows FIN". Regression against s2r | No. One helper per process in all 220 rank logs, recovery OFF in none |
| 4 | risk (medium) | 2400–2459 | Only the lower rank can get death evidence after an outage (ECONNREFUSED on a re-dial). A lower rank that dies during an outage, or any peer whose host goes down, stays "unknown" forever; every fault waits the full bound, then declines "peer liveness unknown". The kill cell only killed rank 1 | No (path not run) |
| 5 | risk (medium) | 2461–2484, 3747 | The accept path blocks the helper up to 500 ms per pending connection, in an unbounded loop, and the listen socket now stays open on every rank for the life of the communicator. Two stray connections with a queued fault stop the heartbeat for over 1 s and the watchdog surfaces the fault; a crafted or stale HELLO replaces a live connection | No (no foreign connections expected; refusals are INFO and were not logged, see 9) |
| 6 | risk (low) | 3251–3271, 3866 | The wait runs before quiesce, so the gate stays open for up to the bound while device posters flush into the ERR QP; the clamp `hold − handshake − 1000` leaves no room for the round's own bounds. The failure mode is a decline, not corruption [inferred] | No. Waits were 2 848.2–3 037.4 ms under a blocking workload (one put and wait every 15 ms) |
| 7 | nit | 3257, 3269, 3280 | Teardown during the wait logs `ended=bound` with a short `wait_ms` and declines "no reconnect within 10000 ms" | No. All 10 `bound` waits lasted 10 000.0–10 001.0 ms |
| 8 | nit | 2318–2322 | ICMP-derived errors on an established socket (EHOSTDOWN, ENONET, and ECONNREFUSED from a REJECT rule) count as dead; ECONNREFUSED is dead on every path, not only on a re-dial as section 9 says | No |
| 9 | nit | 2402, 2477, 4023 | A dial in flight when the peer is declined stays open until teardown; refusals are logged at INFO only, which the runs did not record | No |
| 10 | nit | 3402, 2354 | Decline texts can name a stale or empty cause; `cannot send REQ (send failed)` for a send timeout | No |
| 11 | nit | 3864, 2476, 2482 | Env and widths: `(int)` cast before the clamp, `RECONNECT_MS=0` runs no reconnect step, `NCCL_GIN_TS_RECONNECT` is not checked to match across ranks, 64-bit HELLO round against 32-bit gen | No |
| 12 | nit | 1964, 2222 | Comments still describe the old policy | No |

## Details

### 1. An RST after the peer's own timeout is taken as death (risk, high)

- [source] ECONNRESET, EPIPE and every errno outside {ETIMEDOUT, EHOSTUNREACH, ENETUNREACH} are dead (2318–2322). Dead sets `gone`
  (2343–2345). Only `unknown` peers are re-dialled (2402), so a lower rank that reaches dead never dials again, and the higher rank
  never dials at all.
- [inferred] When one side's keepalive or user timeout expires, its kernel resets and drops the connection; any later segment from
  the other side is answered with RST. So whenever one side has timed out and the other still holds the connection with a working
  path back, the other side gets ECONNRESET from a live peer.
- **Scenario (deterministic, not tested).** Segments from rank 0 to rank 1 are lost; the reverse path works.
  - Rank 1 receives nothing and times out after about 4.6 s: ETIMEDOUT, unknown, waits for a dial.
  - Rank 0 still receives rank 1's keepalives, does not time out, and gets rank 1's RST: ECONNRESET, dead.
  - After the path heals nothing changes. Rank 0's faults decline "RETRY_EXC and the peer's socket shows ECONNRESET"; rank 1's faults
    wait 10 s and decline "peer liveness unknown". The peer was alive throughout.
  - The mirror direction (rank 1 to rank 0 lost) marks the higher rank dead. The accept path revives it (2482 does not check
    `gone`), but a fault on it in between still declines as dead.
  - A symmetric outage that ends between the two sides' timeouts (tens of ms apart in these runs) does the same.
- **Why the runs did not see it.** The BPF mute drops incoming RSTs on both ranks, and every mute outlasted both timeouts (below).
- **Suggestion.** After a loss, treat ECONNRESET and EPIPE as unknown and keep re-dialling; count only a refused re-dial, or a FIN on
  a confirmed socket, as death. At minimum, scope the result "a live peer is no longer declined as dead" to symmetric silent outages.

### 2. The lower rank installs before the higher rank accepts (risk, medium)

- [source] The lower rank installs the new fd as generation g+1 as soon as `gdakiTsSend` of the HELLO returns (2417–2420), that is,
  once the bytes are in its own send buffer. The higher rank validates later and closes the fd on any failure (2474–2480): no full
  HELLO within 500 ms, peer `declined`, or a different context number.
- **Scenario.** The HELLO segment is lost once or twice right after an outage and arrives more than 500 ms after the accept, or the
  higher rank had already declined this peer.
  - The higher rank closes the socket. The lower rank's main loop reads FIN, which `gdakiTsSocketLost` classifies as dead
    (2364, 2343).
  - Result: a live peer, dead for good on the lower rank and unknown for good on the higher rank, as in 1.
- So `ended=reconnected` on the lower rank only means that the peer host has a listening socket, not that its helper accepted.
- **Suggestion.** Have the higher rank answer the HELLO (echo the generation) and install on both sides only after that reply; treat
  a FIN on an unconfirmed socket as unknown.

### 3. Context number from a process-wide counter (bug, latent)

- [source] `gdakiTsCtxSeqNext.fetch_add(1)` (3682) counts gdakiTsSetup calls in the process. It matches across ranks only if every
  process creates its user GIN contexts in the same order and number. The setup accept loop now rejects a HELLO whose `arg`
  differs (3737) and keeps waiting until `NCCL_GIN_TS_CONNECT_MS`.
- **Scenario.** Three processes. Ranks 0 and 1 first create a devComm on a two-rank communicator X, then all three create one on Y.
  - On Y, rank 2 has context number 0 and ranks 0 and 1 have 1.
  - Rank 2 refuses both HELLOs. Its `ncclDevCommCreate` stalls 15 s, then it runs with "transparent recovery OFF ... accept timed out".
  - Ranks 0 and 1 run with recovery ON over a socket that rank 2 closed. They read FIN (dead) and decline every later fault toward
    rank 2.
  - In s2r this configuration worked, because setup did not check `arg`.
- **Suggestion.** Put a per-context random nonce (for example rank 0's) in the setup all-gather record and carry it in HELLO. That
  also serves the authentication asked for in 5.

### 4. Only the lower rank can learn that the peer died (risk, medium)

- [source] Only the lower rank dials (2400–2459), so only it can see ECONNREFUSED. The higher rank never probes.
- **Scenario.** Rank 0 is killed during an outage, or its host crashes. Rank 1 saw ETIMEDOUT (unknown), receives no dial, and stays
  unknown for the life of the communicator. Every fault waits the full 10 s, then declines "peer liveness unknown".
  - The kill cell (`rc_mutekill_b`) killed only rank 1 ([cells.sh](../cells.sh) line 31). So the result "a peer killed during the
    outage is still declined as dead" (M4a–M4c) covers a dead higher rank only.
- A crashed or powered-off host gives ETIMEDOUT or EHOSTUNREACH on the old socket and on every re-dial, so it stays unknown forever on
  both sides. Before this change it was declined at once (with wrong wording). That matches the intended semantics, but the
  application now sees the error one bound later.
- **Suggestion.** Keep the lower ranks' listen addresses too, and let the higher rank probe-connect while unknown; close the probe
  without a HELLO, and count a refused probe as death. Otherwise, list the asymmetry as a limitation.

### 5. Accept path and the long-lived listen socket (risk, medium)

- [source] `gdakiTsRecv(tmp, &h, 500, &ts->stop)` (2472) blocks for every accepted connection, inside
  `while (poll(...) == 1)` (2463), with no limit on the count. The helper loop and the fault wait call it, and both refresh the
  heartbeat only between calls.
- **Scenario.** A port scanner or a stuck client opens two connections to the listen port while a fault is queued.
  - The heartbeat goes stale for more than 1 s with `nQueued > 0` and `busySinceUs == 0`, so the Q4 watcher surfaces the fault
    (2212–2214).
  - The round then declines "the watchdog surfaced a fault earlier".
- The listen socket used to close after setup. Now every rank keeps it open on the management interface for the life of the
  communicator (3747), rank 0 included, although rank 0 never accepts a reconnect.
- A HELLO that passes 2474–2476 replaces a live connection; 2379 closes the old one. Passing takes a sender rank below this one,
  context number usually 0, and a round above the current gen. A leftover process of an earlier job that is still re-dialling could
  hit a reused ephemeral port this way, because unknown peers are re-dialled forever.
- **Suggestion.**
  - Accept at most one connection per step, and read the HELLO without blocking across steps (keep the pending fd).
  - Close the listen socket on ranks that have no lower gated peer.
  - Authenticate HELLO with the nonce from 3.

### 6. The wait runs before quiesce (risk, low)

- [source] The wait (3251–3271) runs before `gdakiTsQuiesce` (3302). For up to `NCCL_GIN_TS_RECONNECT_MS` the gate epoch stays even,
  device posters keep posting into the ERR QP, and those WQEs flush.
  - The rescue area (32 rings) and the 16-slot mailbox were sized for a round that starts within milliseconds of the fault.
  - Non-blocking posters during a long wait were not exercised; the wait cells posted one put and waited for it every 15 ms.
- The clamp (3866) bounds the wait to `hold − handshake − 1000`, counted from when the helper takes the record rather than from when
  the device waiters began to hold. It leaves no room for quiesce, drain or the path wait. With `RECONNECT_MS` near the clamp, the
  device waiters give up during the round and the round declines.
- Both outcomes are declines, not corruption [inferred]. **Suggestion.** Quiesce first and wait with the gate closed, or clamp
  against the round's own bounds.

### 7–12. Nits

- **7.** On teardown the wait breaks on `stop` (3257), but `ended` stays `bound` and the decline reads "no reconnect within <B> ms"
  (3280). Log `ended=stop` and decline "the communicator is being destroyed".
- **8.** [inferred] Linux reports these ICMP errors on an established socket as soft errors, which surface at the timeout:
  - host unknown as EHOSTDOWN;
  - host isolated as ENONET;
  - port unreachable (the default of an iptables REJECT rule) as ECONNREFUSED.

  All three are network conditions, yet all count as dead (2318–2322). Section 9 counts ECONNREFUSED as dead only on a re-dial, but
  the code classifies by name on every path.
- **9.** The `continue` at 2402 skips the `dialFd` handling once the peer is declined, so an in-flight dial is closed only by
  `gdakiTsStop` (4023).
  - During an outage a dial is almost always in flight, so an "unknown" decline nearly always leaves one open.
  - If the path heals within the SYN timeout, the peer's helper accepts it and blocks 500 ms waiting for a HELLO that never comes
    (see 5).
  - Refusals are logged at INFO (2477), and the runs used `NCCL_DEBUG=WARN` (`../scripts/ts2/run_trial.sh` line 64), so a refusal
    would have left no trace.
- **10.** Only 3402 sets `gone` without declining. It records no cause, so a later fault declines with the dead wording and either
  an older cause from a previous loss (for example ETIMEDOUT) or "no socket" (2354). After a `gdakiTsSend` that timed out, errno is
  EAGAIN, which has no name, so the text reads "send failed".
- **11.**
  - `(int)std::max<int64_t>(0, ...)` (3864) truncates before the clamp, the same pattern as the other parameters.
  - `RECONNECT_MS=0` declines without running one reconnect step.
  - If the ranks set `NCCL_GIN_TS_RECONNECT` differently, the lower rank dials and the higher rank never accepts. The kernel queues
    the connection, the lower rank installs it (see 2), and its round ends in "handshake timeout".
  - `h.round` is 64-bit and `gen` 32-bit (2476, 2482); only crafted input reaches the difference.
- **12.** The comments at 1964 ("recover iff the peer's socket shows no FIN/RST") and 2222 ("a host that dies without FIN/RST is
  detected ... within about 5 s", now unknown rather than dead) describe the old policy.

## Checked and found correct [source]

- **Thread confinement.** Only the helper thread touches mutable peer state (`fd`, `unknown`, `gen`, `dialFd`, `listenFd`, `muteOn`).
  - The Q4 watcher reads only `gated` (2151, 2171), which is fixed after setup. This also removes an s2r race: `gdakiTsRoutes` read
    `fd` from the watcher thread.
  - Teardown closes sockets only after joining the helper (3971, 3991).
- **Generations.** The lower rank's gen is never below the higher rank's, because the higher rank installs only values the lower
  rank sent.
  - So `h.round <= gen` (2476) cannot reject a HELLO from a consistent live peer; it filters only replays and junk.
  - Only the lower rank dials, so the two ranks never dial each other at once.
  - A late second connection is replaced in order (2379).
- **HELLO followed by REQ.** `gdakiTsPump` reads at most one record (2277). A REQ sent right after the HELLO stays in the socket for
  the main loop or the handshake.
- **fd lifecycle.**
  - `dialFd` is closed on success (moved into place), send failure, refusal, other errors and the 500 ms bound (2417–2438).
  - Refused accepts are closed (2479), and `gdakiTsInstall` closes the fd it replaces.
  - `gdakiTsStop` closes fd, dialFd and listenFd. The setup and start failure paths close the listen socket.
  - The only leak is 9.
- **Wait loop.**
  - The heartbeat is refreshed every iteration (3258).
  - `busySinceUs` is 0 during the wait, so the round watchdog does not count it, as section 9 specifies.
  - `stop` is checked every iteration and the accept read checks it too, so a join waits at most about 200 ms (one HELLO send).
- **Mute switch.**
  - While the mute is on, the listen, dial and accepted sockets get the filter (2446, 2467, 3523–3525). Accepted sockets also
    inherit the listener's filter [inferred].
  - Mute off detaches the filter from fd, dialFd and listenFd.
  - The schedule runs in the helper loop and in the wait ([DEVIATIONS.md](../DEVIATIONS.md) section 2). As in s2r, it does not run
    inside a round.

## Effect on the measured results [measured]

Nothing above changes a measured result. Counted from `results/20261008/`: 220 rank logs of the 110 judged trials, plus 4 logs of
the 2 excluded trials.
- **Startup.** Recovery ON appears exactly once in each of the 220 logs. The 4 logs without it belong to the two excluded
  port-collision trials (`f3_b_n2`, `rc_mutef3l_b_n10`).
  - No log has "recovery OFF", "SO_ATTACH_FILTER failed" or a RECONNECT_MS clamp. The 220 clamp lines are the existing PATH_WAIT
    clamp.
- **Reconnect lines.** One per rank per trial in `rc_mute8_f1_b` (10) and `rc_mutef3s_b` (10), all `gen=1`; none elsewhere.
  - Rank 0 shows `attempts=8` in the first cell and `attempts=16` in the second; rank 1 always shows `attempts=0`.
  - Rank 1 accepted every rank 0 install, which rules out 2 in these trials.
- **Wait lines.** `reconnected` 10, `bound` 10, `off` 5, `dead` 0.
- **Close lines.**
  - In all five mute cells, both ranks closed with ETIMEDOUT `liveness=unknown`.
  - The kill cell adds a second rank 0 line, ECONNREFUSED `liveness=dead` (10/10).
  - Every other close line is FIN `liveness=dead`.
- **Margin before the mute ended.** Each rank's ETIMEDOUT close came at least this long before that rank's own mute-off line:

  | Cell | Rank 0 | Rank 1 |
  |---|---|---|
  | `rc_mute8_f1_b` | 3 400.2 ms | 3 376.3 ms |
  | `rc_mute8off_b` | 3 402.3 ms | 3 369.9 ms |
  | `rc_mutef3s_b` | 7 199.8 ms | 7 169.4 ms |
  | `rc_mutekill_b` | 3 198.9 ms | killed before the mute ended |
  | `rc_mutef3l_b` | exited before the mute ended | 25 167.5 ms |

  So no RST could arrive while the other side still held the connection, which rules out 1.
- **Decline reasons, rank 0.**
  - Kill cell, 10/10: "RETRY_EXC and the peer's socket shows ECONNREFUSED".
  - Long-mute cell, 10/10: "RETRY_EXC and peer liveness unknown (ETIMEDOUT, no reconnect within 10000 ms)".

## Paths no trial ran

- A wait that ends `dead`: death evidence arriving during the wait.
- A local QP error that waits (in the 8 s cell the fault came after the reconnect).
- The higher rank as initiator, waiting for an accept.
- ECONNRESET, EPIPE, BADMAGIC, EHOSTUNREACH or ENETUNREACH as a close cause.
- A second loss (gen 2 or higher).
- A non-default or clamped `NCCL_GIN_TS_RECONNECT_MS`.
- More than two ranks.
- Teardown during a wait.
