// rs_spare_api.h - gin-restore, work package 8 (spare branch, EXPERIMENT.md 9.3, 9.10.7, 9.11.1 D4, 9.11.3 M4):
// what the hold state machine (host branch, work package 7) calls on the survivor side, the messages the spare process
// and the survivors exchange, and what this branch reads from the host branch (impl/rs_hold_api.h).
//
// Binding interface between branches (impl/PARALLEL.md). The definitions are static functions of
// src/transport/net_ib/gdaki/gin_host_gdaki.cc, in the region fenced
//   "// ==== gin-restore (rs, work package 8): REJOIN and endpoint (begin) ===="  ...  "(end) ===="
// placed after gdakiTsReconnectStep and before the hold state machine's region, so the state machine (same file, later)
// sees them. This file restates their declarations for the other branches (it is not included anywhere: ncclResult_t,
// ncclGinRecoverToken_t come from nccl.h, struct gdakiRecHost and struct gdakiTsMsg from the host file); a definition that
// differs from them is a bug of the spare branch.
// Every function here runs on the survivor's helper thread (gdakiTsInHelper), never on another thread, and never on a
// fail-fast process (no peer is ever held there; the accept step parks nothing because no REJOIN arrives).
//
// Order of one restore of logical rank p, seen from survivor q (9.11.3 M4; the hold start, HOLDING, ACTIVATE and the
// state transfer of work packages 5, 7 and 9 are not here):
//   0. q holds p (state HELD; QPs to p in ERR, gates odd).
//   1. The spare of p dials q's kept listen socket and sends REJOIN (incarnation i+1, nonce, its QPNs, its send PSNs,
//      its GID/LID/MTU/ordering, its new listen address). q's accept step (gdakiTsReconnectStep) parks it per peer.
//   2. q's state machine, on the held peer: gdakiRsRejoinAccept(r, p)  -> ACCEPTED: the socket is installed (death marks
//      cleared, pe.addr = the spare's listen address, a new connection generation, REJOIN_ACK sent).
//   3. (work packages 5 and 9: X_q, the log, the checkpoint.) The spare sends its rkey list on the data socket right after
//      REJOIN_ACK, before it waits for TOKEN; q reads it (gdakiRsRkeysRecv) any time before step 7.
//   4. q: ncclGinRecoverPrepare(comm, p, &tok) (helper thread), then gdakiRsSendToken(r, p, &tok).
//   5. The spare connects each of its QPs to q RTR/RTS (receive PSN = q's new send PSN from the token, send PSN = the one
//      it announced in REJOIN) and sends READY. q hands the READY record to gdakiRsTakeReady.
//   6. q: gdakiRsSwapEndpoint(r, p, &remote)  (rq.exch of every QP to p := the spare's endpoint, under opMu; `remote` is
//      the token for Commit: the spare's QPNs and send PSNs), then ncclGinRecoverCommit(comm, p, &remote, ...).
//   7. q: gdakiTsBaseline(r, p) (the new incarnation's responder MSN), then gdakiRsSwapRkeys(r, p, &list).
//   8. q: CAS HELD -> COMMITTING, publish (gdakiTsRepostApply with U = S, n = 0; work package 9), then gdakiRsSendDone.
//   9. The spare, after every survivor's DONE_RS, starts its helper and sends RESTORED to every survivor; q's state
//      machine hands it to gdakiRsTakeRestored (PUBLISHED -> ARMED or OFF is the state machine's).
// Any refusal on q's side is the state machine's fallback (FALLBACK(p, i): the record carries the dead incarnation i, as
// the host branch's HOLDING/NOHOLD/FALLBACK do in `round`; the declined incarnation is i + 1 once a REJOIN was accepted,
// PeerDead decline). The spare ends without BYE when anything fails (closing its sockets with a FIN), so q reads death, not
// "left".
// The spare's driver serves the survivors one at a time (in rank order): survivor q's REJOIN may come only after every
// earlier survivor's round has finished (DONE_RS). A survivor's hold deadline must therefore cover the earlier survivors'
// rounds as well as its own; the host branch's state machine owns that deadline.
#ifndef GIN_RESTORE_RS_SPARE_API_H_
#define GIN_RESTORE_RS_SPARE_API_H_

#include <stddef.h>
#include <stdint.h>
#include <vector>

// ---- messages on the helper socket (struct gdakiTsMsg, fixed size, magic GDAKI_TS_MAGIC) ----
// hk uses types 1..10. This branch uses 32..37; the other branches must not use 32..47 (host and dev: please take 48 and
// above, or below 32 above 10).
enum {
  GDAKI_TS_RS_REJOIN = 32,      // spare -> survivor: the first record on a new connection to the survivor's listen socket
  GDAKI_TS_RS_REJOIN_ACK = 33,  // survivor -> spare: accepted and installed; round = the connection generation
  GDAKI_TS_RS_TOKEN = 34,       // survivor -> spare: the survivor's Prepare token (tok: its QPNs, its new send PSNs)
  GDAKI_TS_RS_READY = 35,       // spare -> survivor: the spare's QPs to this survivor are RTS (tok: the spare's QPNs, PSNs)
  GDAKI_TS_RS_DONE = 36,        // survivor -> spare (DONE_RS): Commit, Baseline, rkey swap and publish are done
  GDAKI_TS_RS_RESTORED = 37,    // spare -> every survivor: every DONE_RS arrived; the spare replays from its step
};
// Every record of these six types: magic, type, from = the sender's rank, nonce = the GIN context's nonce (the spare
// replays the recorded salt, so it is the first incarnation's), pad = the incarnation of the restored rank (i + 1).
// executed[0] = GDAKI_RS_WIRE_VERSION, executed[1] = the sender's own incarnation; REJOIN adds its endpoint in
// executed[2 ..] (struct gdakiRsEndpoint, below). nqp and tok: REJOIN, TOKEN and READY (token order = the QPs to that
// peer in GIN-context order, as gdakiRecForPeer walks them).
#define GDAKI_RS_WIRE_VERSION 1u
struct gdakiRsEndpoint {     // the spare's endpoint (the same for every QP of its context), in gdakiTsMsg::executed[2 ..]
                             // (named gdakiRsRejoinInfo in commit 28f1262e; same 72-byte layout)
  uint32_t lid;
  int32_t activeMtu;         // enum ibv_mtu
  int32_t ordering;          // enum doca_verbs_qp_ordering_semantic
  int32_t gidIndex;
  uint8_t gid[16];           // RoCE/IB GID (also the DOCA vgid)
  uint8_t listenAddr[32];    // union ncclSocketAddress of the spare's new helper listen socket (28 bytes used)
  uint64_t step;             // the checkpoint step it restores from (diagnostic)
};
// Existing types the spare branch also uses: FAIL (6) answers a REJOIN of a peer this survivor declined (the
// FAIL-on-reconnect rule of gin-peer); BYE (10) is never sent by a spare that gives up.
// HELLO (1), HELLO_ACK (7), PROBE (8) and PROBE_ACK (9) now carry the sender's own incarnation in pad (hk: 0, so the
// wire of a fail-fast job is hk's). In a process that asks for the restore, a receiver that knows an incarnation above 0
// for that sender (gdakiRsPeerInc, after a REJOIN) accepts them only when pad equals it; other incarnations are refused
// as a foreign nonce is (HELLO and PROBE at the listen socket, HELLO-ACK and PROBE-ACK at the dialer).

// ---- survivor side: called by the hold state machine on a held peer (helper thread) ----
enum { GDAKI_RS_REJOIN_NONE = 0, GDAKI_RS_REJOIN_ACCEPTED = 1, GDAKI_RS_REJOIN_REFUSED = 2 };
struct gdakiRecHost;  // the host file
struct gdakiTsMsg;    // the host file

// The REJOIN acceptance entry point (RL6). Call on the helper thread for a peer this rank holds (HELD), as often as
// wanted (every step of the held state).
//   NONE      no REJOIN of `peer` is parked, or the parked one is older than 1000 ms (closed then). The accept step parks
//             the latest one per peer; one nobody takes within 1000 ms is closed (a FIN), and the spare dials again until
//             its deadline. The spare waits for REJOIN_ACK, a FIN or its deadline, with no timeout of its own, so it never
//             abandons a REJOIN the survivor still holds.
//   REFUSED   a parked REJOIN did not qualify and was closed (FIN; the spare retries): `why` says why. Qualifies: the
//             hold state says HELD (gdakiRsHoldIsHeld, below; checked again here), the peer is not declined, its
//             incarnation is gdakiRsPeerInc(r, peer) + 1, the nonce is this context's, the QP count and the spare's
//             view of this rank's QPNs match this rank's QPs to the peer.
//   ACCEPTED  REJOIN_ACK went out (generation pe.gen + 1, the survivor's own incarnation in executed[1]); only then: the
//             socket is this peer's helper socket: gone, deadJudged, refusals, left, peerFailed, failedPending, lostCause,
//             closeCause, the kept REQ are cleared; dialFd, pendFd, probeFd closed; pe.addr = the spare's listen
//             address; gdakiRsPeerInc(r, peer) = i + 1; the spare's endpoint and token are kept for the swap;
//             gdakiTsInstall (which clears lostAfterCommit). If REJOIN_ACK cannot be sent nothing changes (REFUSED).
// A REJOIN of a peer this rank declined is answered with FAIL by the accept step itself (no call needed), and by
// gdakiRsRejoinAccept when the peer was declined after the REJOIN was parked; a spare that reads FAIL gives up (no
// further dial to anybody).
static int gdakiRsRejoinAccept(struct gdakiRecHost* r, int peer, char* why, size_t whyLen);

// The incarnation this rank knows for `peer` (0 at setup; i + 1 after an accepted REJOIN). The state machine puts it in
// HOLDING and FALLBACK and compares it with theirs. This rank's own incarnation: gdakiRsPeerInc(r, own rank).
static uint32_t gdakiRsPeerInc(struct gdakiRecHost* r, int peer);

// After ncclGinRecoverPrepare(comm, peer, &local) on the helper thread: sends TOKEN (local as it is) on the installed
// socket. Needs an accepted REJOIN of the current incarnation. ncclSuccess or ncclSystemError (socket).
static ncclResult_t gdakiRsSendToken(struct gdakiRecHost* r, int peer, const ncclGinRecoverToken_t* local);

// A READY record read on `peer`'s installed socket (the state machine takes it with gdakiHoldTakeMsg and hands it here):
// true if it is the spare's READY for the accepted incarnation and its token is the one REJOIN announced (same count,
// QPNs and send PSNs); it is then marked taken (the swap needs it). False: `why`; the state machine falls back.
static bool gdakiRsTakeReady(struct gdakiRecHost* r, int peer, const struct gdakiTsMsg* m, char* why, size_t whyLen);

// The endpoint swap (RL7), after TOKEN and READY, before ncclGinRecoverCommit: under r->opMu, rq.exch of every QP to
// `peer` takes the spare's QPN, LID, GID (gid and vgid), GID index, MTU and ordering semantic (rank, host and device names
// stay: same node and GPU); *remote is the token Commit takes: magic, nqp, qpn[i] = the spare's QPN, remoteQpn[i] = this
// rank's QPN, sqPsn[i] = the spare's send PSN, epochWqes[i] = 0. Needs: accepted REJOIN, READY taken, the peer prepared
// (gdakiRecPrepared == 1), the same QP count. Nothing else of the QP is touched (it stays in ERR until Commit).
// ncclSuccess, or ncclInvalidUsage with `why` (nothing changed then). It takes r->opMu itself: call it outside opMu, and
// ncclGinRecoverCommit after it returns.
static ncclResult_t gdakiRsSwapEndpoint(struct gdakiRecHost* r, int peer, ncclGinRecoverToken_t* remote, char* why,
                                        size_t whyLen);

// The spare's rkeys (handed over the data socket; work package 5's data server owns that socket, this branch only the
// format). One entry per window registered on the context's collComm (by its number, ncclGinGdakiMemHandle::rsWinId), the
// signal table and the counter table.
enum { GDAKI_RS_RKEY_WINDOW = 1, GDAKI_RS_RKEY_SIGNALS = 2, GDAKI_RS_RKEY_COUNTERS = 3 };
#define GDAKI_RS_RKEYS_MAGIC 0x4b525347u  // "GSRK"
#define GDAKI_RS_RKEYS_MAX 4096
struct gdakiRsRkeyEntry { uint32_t kind, id, rkeyBe, pad; };  // id: the window number (0 for the two tables); big-endian rkey
struct gdakiRsRkeysHdr { uint32_t magic, version; int32_t rank; uint32_t incarnation; uint64_t nonce; uint32_t count, pad; };
// On the wire: one gdakiRsRkeysHdr, then `count` entries, little-endian host order except rkeyBe.
// Receive and check on a data-socket fd (bounded); the decoded list goes to gdakiRsSwapRkeys.
struct gdakiRsRkeys {
  int rank = -1;
  uint32_t incarnation = 0;
  uint64_t nonce = 0;
  std::vector<struct gdakiRsRkeyEntry> e;
};
static ncclResult_t gdakiRsRkeysRecv(int fd, int timeoutMs, struct gdakiRsRkeys* out, char* why, size_t whyLen);
// The rkey swap (RL9), after Commit and gdakiTsBaseline, before the publish: slot `peer` of every window rkey table of
// this context's collComm, of the signal table's and of the counter table's rkey table is written over the NIC copy path
// (no CUDA call), read back and compared; the windows' host copies too (the two tables' host copies are read only at
// setup and stay). Needs: the list from `peer`, for this context (nonce) and the accepted incarnation; every window still
// registered on the collComm named in it (checked before anything is written); the NIC copy path on. The window slots are
// written under the window registry's lock, which a deregistration takes before it frees a table. ncclSuccess, or an error
// with `why` (some slots may be written then: the state machine falls back, which declines the peer).
static ncclResult_t gdakiRsSwapRkeys(struct gdakiRecHost* r, int peer, const struct gdakiRsRkeys* list, char* why,
                                     size_t whyLen);

// After the publish: DONE_RS on the installed socket. ncclSuccess or ncclSystemError.
static ncclResult_t gdakiRsSendDone(struct gdakiRecHost* r, int peer);
// A RESTORED record read on `peer`'s socket: true if it is the spare's, for the accepted incarnation.
static bool gdakiRsTakeRestored(struct gdakiRecHost* r, int peer, const struct gdakiTsMsg* m);

// ---- the spare's activation (buddy -> the spare's port, NCCL_GIN_RESTORE_SPARE_PORT) ----
// The spare finishes its init replay (ncclCommInitRank, window registration, devComm creation: no peer contact, peer QPs
// in RESET, no helper) and waits for this record in its handshake driver, which its ncclGinRestoreResume runs
// (integration; the driver is gdakiRsSpareRun(r, activatePort, activateWaitMs, handshakeMs, dataFd, dataArg, &step) in the
// host file). One record per TCP connection (read within 500 ms); the spare answers with the same struct (kind ACCEPTED or
// REFUSED) and closes. It takes the incarnation and the step from the record. Before activating it checks that the process
// that held the rank is gone (same node: /proc/<pid> absent, or its state Z or X, or its start time differs); never while
// it lives, and never without a PID (refused). A process with NCCL_GIN_RESTORE_SPARE set but no NCCL_GIN_RESTORE_REPLAY
// fails ncclCommInitRank (it never runs a live initialization), and the spare's Resume refuses unless its replay was clean
// (no divergence, nothing past the transcript's end, no own-slot mismatch outside the allowed fields).
// The data fd: for each survivor the driver calls dataFd(dataArg, peer) once, right after that survivor's REJOIN_ACK, and
// writes the rkey list on the fd it returns (bounded by the handshake deadline). The driver never closes that fd, on
// success or on failure (its no-BYE exit closes only the helper sockets): the callback's owner (the host branch's work
// package 5 data path) keeps it and closes it. A return below 0 fails the restore.
#define GDAKI_RS_ACT_MAGIC 0x41535247u  // "GRSA"
enum { GDAKI_RS_ACT_ACTIVATE = 1, GDAKI_RS_ACT_ABANDON = 2, GDAKI_RS_ACT_ACCEPTED = 3, GDAKI_RS_ACT_REFUSED = 4 };
struct gdakiRsActivate {   // 64 bytes
  uint32_t magic, version;   // GDAKI_RS_ACT_MAGIC, 1
  uint32_t kind, pad;        // GDAKI_RS_ACT_*
  int32_t rank;              // the logical rank (= the spare's NCCL_GIN_RESTORE_SPARE)
  uint32_t incarnation;      // the new incarnation (the survivors' gdakiRsPeerInc + 1)
  uint64_t nonce;            // the GIN context's nonce (the spare checks its replay against it)
  uint64_t step;             // the checkpoint step to restore
  int64_t pid;               // the process that held the rank (required: 0 is refused)
  uint64_t pidStart;         // its start time, /proc/<pid>/stat field 22 (0: refused while that PID lives)
  uint64_t reserved;
};
// The buddy's helper sends it (host branch); bounded; returns the spare's answer kind, or -1 (no answer). Without the
// record the spare never activates.
static int gdakiRsSendActivate(const void* spareAddr /* union ncclSocketAddress */, const struct gdakiRsActivate* a,
                               int timeoutMs);

// ---- read from the host branch (impl/rs_hold_api.h, published in commit a3478d84 of the host branch) ----
// Whether `peer` is held (HELD only) on this context; lock-free; false in a process that does not ask for the restore.
// The spare branch calls it in gdakiRsRejoinAccept only. Its build has a placeholder definition that returns false (so
// nothing is accepted there); integration replaces that definition with a forward declaration, since the host branch's
// definition comes later in the file.
static bool gdakiRsHoldIsHeld(struct gdakiRecHost* r, int peer);

#endif
