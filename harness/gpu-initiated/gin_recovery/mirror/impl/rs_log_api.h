// rs_log_api.h v2 - gin-mirror (impl/PARALLEL.md; EXPERIMENT.md 9.4, 9.5): gin-restore's rs_log_api.h (copied unchanged
// in commit 6cde95d6, md5 bd2d0233) with the mirror's changes. What v2 changes, in short:
//   - the side table's layout is impl/rs_mirror_api.h's (magic "RSS4", the mirror fields at 40..63, miUse in the QP
//     entry, the cell array between the QP entries and the ring; the MIRROR flag 0x20); the layout notes below follow
//     it;
//   - every per-peer function of the block works on the "user only" QP set (gdakiRsQpsOfPeer narrowed; the mirror QP is
//     read on its own, impl/rs_mirror_api.h);
//   - the export v2 (mirror on): entries with their step and segment, no source bytes, the mirror QP's X and M, the
//     survivor's own rkey list after the trailer; the step of an entry (gdakiRsStepOfPos);
//   - the step-aligned import (mirror on) and the loopback pair's lock;
//   - with the mirror off every function and format of v1 stays as it was (the export stays version 1).
// Line numbers NNNN are lines of ../../restore/impl/rs_layer.diff (md5 f005bb67). The rest of this head comment is
// v1's.
//
// v1: rs_log_api.h - gin-restore, dev branch (impl/PARALLEL.md: work packages 4 again, 6 and 9; EXPERIMENT.md 9.4, 9.5,
// 9.6, 9.11.3 M2): the send-side log as one ring per rank, and the host functions the checkpoint (host branch, work
// package 5) and the restore round (integration) call.
//
// Binding interface between branches. The block between the two "gin-restore (dev): log API" markers below is in
// src/transport/net_ib/gdaki/gin_host_gdaki.cc byte for byte (since work package 6; the dev branch's region, early in the
// file so that every later region sees it); build_mi.sh `api` checks that the two are equal (v1: build_rs_dev.sh). The
// definitions are static functions
// of the same file, in the dev branch's regions fenced "gin-restore (dev): log, suppress and replay" (host) and
// "gin-restore (dev): log, suppress and replay, pure" (no NCCL, unit-tested on the CPU). This file is not included
// anywhere in the build; outside the block it only adds what a standalone syntax check needs.
//
// ---- device layout (src/include/nccl_device/gin/gdaki/gin_gdaki_device_host_common.h; the host reads it over the NIC
//      copy path by these offsets) ----
// One device allocation per GDAKI context of a process that asks for the restore (NCCL_GIN_FAULT_POLICY=hold with
// NCCL_GIN_RESTORE != 0, or a spare process); the restore needs exactly one such context per communicator (9.10.4), so
// in a restorable communicator the ring is one per rank. The device reaches it through the context's classification block
// (ncclGinGdakiQ4::restore, appended to that block; the GPU context keeps hk's layout and stride), which stays null until
// ncclGinRestoreResume succeeds and then holds the side table's address (one synchronous write; in the log measurement
// mode, a test mode, at the context's creation). The side table, its MRs and the strict window MRs are set up at creation.
//   struct ncclGinRsSide (128 B, offset 0)
//      0 magic u32 "RSS4" (v1: "RSS3") | 4 nqp u32 | 8 fence u64 (the drain check's READ target) | 16 csum u32
//     (checksum scheme) | 20 nEntries u32 (ring entries, a power of two; 0: no ring) | 24 entries ptr (the ring) |
//     32 pairTest u64 (the loopback pair's self-test word) | 40 miOn u32 | 44 miCtx u32 | 48 miCellsOff u64 |
//     56 miNCells u32 | 60 reserved (v1: 32..63 reserved; impl/rs_mirror_api.h)
//     64 head u64   positions reserved so far (device: CAS, only while the reservation fits; so every position below
//                   head is written once its post leaves the gate, and an overflow takes no position)
//     72 tail u64   first position kept (host, over the NIC; the device reads it to see the room left)
//     80 ovfCount u64  operations of every QP that could not be logged (device, on overflow only)
//     88..127 reserved
//   struct ncclGinRsQp (128 B each, offset 128 + 128 x qp; qp = context x nranks + peer, the host's qp index)
//      0 msgs u64      request messages the hold path posted on the QP (device atomic add, every post, logged or not;
//                      a get's READs count; a 0-byte put's NOP and a suppressed message do not): 9.4's M
//      8 suppress u64  request messages the spare process still holds back (host sets it before the replay; device CAS)
//     16 ovfCount u64  this QP's operations that could not be logged (device, on overflow only)
//     24 ovfHead u64   1 + the ring head when this QP last overflowed (device atomic max; diagnostic)
//     32 logOn u32     the device logs this QP's operations only while it is 1 (host, over the NIC, in a pause)
//     36 getRefused u32  a get was asked while suppress was not 0 (device; read only once the QP's gate count is 0)
//     40 gets u64     gets with data the hold path posted on the QP (device atomic add): a survivor's get toward a peer
//                     it may have to restore DISARMs that peer (9.7 item 8, 9.10.4)
//     48..127 reserved
//   the ring: nEntries entries of 64 B, 256-byte aligned after the QP entries; position p lives in slot p mod nEntries.
//   struct ncclGinRsLogEntry (64 B):
//      0 pos u32     low 32 bits of the entry's position  } one 8-byte store: the entry's identity word. A slot whose
//      4 qpKf u32    qp (bits 0..23) | kind (24..25)       } pos is not the position asked for, or whose kind is 0 (the
//                    | flags (26..31)                      } ring starts zeroed), holds an older entry or one still being
//                    written. The device writes the word with one 8-byte store; that a NIC read never sees it half
//                    written is an inference (an aligned 8-byte store served from L2), not measured.
//      8 csum u32    checksum of a put's data as posted (scheme in the flags; 0: off)
//     12 sigWin u32  the signal's window: 0 = the context's signal table (an indexed signal), else the VA signal window's
//                    number (ncclGinGdakiMemHandle::rsWinId)
//     16 dstWin u32  target window's number (0: none) | 20 srcWin u32 put: source window's number (0: none)
//     24 dstOff u64 | 32 bytes u64 (put: bytes posted; putValue: the value's size) | 40 src u64 (put: source offset;
//     putValue: the value, zero-extended) | 48 sigOff u64 | 56 sigVal u64
//   kind: 1 put with data, 2 putValue, 3 a signal alone. flags: SIGNAL 0x01, SPLIT 0x02 (the suppress budget held the
//   first messages back), NOBASE 0x04 (no source address: no checksum), checksum scheme in bits 3..4 (of the 6 flag
//   bits). The request messages of an entry follow from kind, flags and bytes (ncclGinRsEntryMsgs; 9.6's units).
// Per rank: pages(256-aligned(128 + 128 x nqp) + 64 x nEntries) bytes (4 ranks, 4 contexts, 4 096 entries: 266 240 B).
// v2 (gin-mirror): with the mirror nqp counts the mirror context's QPs too ((user contexts + 1) x nranks; the mirror QP
// to peer b is QP miCtx x nranks + b, entry field 48 miUse), and nranks cells of 64 B (struct ncclGinMiCell) follow the
// QP entries at miCellsOff = 128 + 128 x nqp; the ring then starts at 256-aligned(miCellsOff + 64 x nranks). The mirror
// QPs never log (logOn stays 0; the setup leaves them out of rsLogged) and their gets and overflows stay 0. A MIRROR
// entry (flag 0x20, kind 1, bytes > 0) has, in place of `csum`, its data's offset in the sender's lane in 64-byte
// units; the mirror and a checksum scheme are never on together (Resume condition 36).
//
// ---- build-time opt-in (user decisions 2026-10-12, (나), then the direction that removed the trap) ----
// The device hold path exists only in programs compiled with -DNCCL_GIN_RESTORE_DEVICE (every translation unit of one
// device link unit alike; mixing is not supported). Such a program's put, putValue and get load the classification
// block's side-table pointer and take the hold path when it is not null. Compiled without the macro they are hk's code,
// instruction for instruction (no load, no branch). nccl.h's ncclGinRestoreResume is a static inline wrapper that passes
// whether the calling translation unit defines the macro to the library's ncclGinRestoreResumeBuilt; without it the
// restore is refused ("program not built with NCCL_GIN_RESTORE_DEVICE", the same on every rank) and the pointer is never
// published. NCCL's own kernels are built without the macro. The log measurement mode (NCCL_GIN_RESTORE_LOG_MEASURE=<ms>)
// publishes at the context's creation and needs a macro-built program; NCCL_GIN_RESTORE_LOG_MEASURE_LOG=0 keeps the log
// off there (the hold path's cost without the log).
//
// ---- helper-socket message types ----
// hk uses 1..10, the host branch 11..20 (rs_hold_api.h), the spare branch 32..47 (rs_spare_api.h); this branch 21..31
// (the split the host branch published). gin-mirror: 38 INJECTED (rs_hold_api.h v2), 48 MIRROR_SETUP, 49 CKPT_PULL
// (rs_mirror_api.h), 50 STORE_REQ, 51 STORE_ACK (rs_store_api.h); 52..63 are free. This branch uses none so far: the
// log export goes over the data socket (format below), which work package 5's data server carries. A record of 21..31
// that a wait parks (gdakiHoldDefer) is taken by this branch's code with gdakiHoldTakeMsg.
#ifndef GIN_RESTORE_RS_LOG_API_H_
#define GIN_RESTORE_RS_LOG_API_H_

#include <stddef.h>
#include <stdint.h>
#include <atomic>
#include <vector>
#ifndef NCCL_GIN_RECOVERY_MAX_QPS
#define NCCL_GIN_RECOVERY_MAX_QPS 64  // nccl.h.in (the host file has it)
#endif
#ifndef NCCL_GIN_RS_LOG_PUT  // v2: the device-host common header has the entry (diff 1216-1250); a standalone check needs it
struct ncclGinRsLogEntry {
  uint32_t pos, qpKf, csum, sigWin, dstWin, srcWin;
  uint64_t dstOff, bytes, src, sigOff, sigVal;
};
#endif

// ---- gin-restore (dev): log API (begin; impl/rs_log_api.h, byte for byte) ----
// gin-mirror (v2): every function below that takes a peer works on the QPs of the user contexts to it ("user only",
// gdakiRsQpsOfPeer; impl/rs_mirror_api.h); the mirror QP is read on its own (gdakiMiExecReadMirror,
// gdakiMiReadMsgsMirror).
// Positions are 64-bit counts of entries reserved on this rank's ring before the entry (the ring's head when it was
// reserved). Threads: "helper" = the context's helper thread only (the NIC copy path has one user at a time); "app" = the
// application thread (CUDA calls allowed); "any" = any thread. A process that does not ask for the restore has no ring:
// gdakiRsLogReady is false and every other call returns ncclInvalidUsage (or does nothing).
struct gdakiRecHost;
struct gdakiTsRepostPlan;
#define GDAKI_RS_POS_INF (~0ULL)             // "every position": the cover of a peer whose log broke (until its next pause)
#define GDAKI_RS_MSG_FIRST 21                // helper-socket message types of this branch: 21..31 (none used yet)
#define GDAKI_RS_MSG_LAST 31

// What the sender's helper reads in a checkpoint's input pause toward `peer` (9.4 step 2), every QP to the peer
// quiesced (gate odd, count 0, held WQEs rung): the cut and the counts PAUSED carries. The caller keeps it until the
// checkpoint is stable (CKPT_STABLE) or abandoned.
struct gdakiRsLogPause {
  uint64_t head = 0;      // L: the ring's head with the peer's QPs quiesced; every entry of the peer is below it
  int nqp = 0;            // QPs to the peer, in GIN-context order (gdakiRecForPeer)
  uint64_t msgs[NCCL_GIN_RECOVERY_MAX_QPS] = {};  // M per QP: request messages posted to the peer (the device's count)
  uint64_t ovf[NCCL_GIN_RECOVERY_MAX_QPS] = {};   // per QP: operations not logged (ring full), so far
  uint64_t gets[NCCL_GIN_RECOVERY_MAX_QPS] = {};  // per QP: gets with data posted to the peer, so far (the get rule)
  bool logComplete = false;  // the log toward the peer is kept from this pause on (logOn set and read back on every QP to
                             // it): the log's part of PAUSED's "armable" (an overflow or a get later DISARMs, gdakiRsLogPoll)
  bool firstPause = false;   // this pause set the QPs' logOn: the peer's log starts at `head`
};

// any. The side table and the ring are set up on this context (a process that asks for the restore, setup succeeded).
static bool gdakiRsLogReady(struct gdakiRecHost* r);

// helper, in the input pause toward `peer` (its QPs quiesced), before the pause's even epoch is published: sets the
// QPs' logOn over the NIC if not set (and reads it back), then reads the head, the per-QP msgs and overflow counts.
// A peer whose log broke (overflow since its last stable cut) is covered up to here and its log restarts at `head`.
static ncclResult_t gdakiRsLogPauseRead(struct gdakiRecHost* r, int peer, struct gdakiRsLogPause* out, char* why,
                                        size_t whyLen);

// helper, on the peer's CKPT_STABLE for the checkpoint taken at `atPause`: the peer's entries below atPause->head are
// covered (the trim of 9.5), and the tail advances over every covered entry from the tail on (written to the device over
// the NIC). ncclInvalidUsage (with why) when one of the peer's QPs overflowed after the pause (read now): the log since
// this cut is broken, the caller must not arm the peer on it (gdakiRsLogPoll reports it for DISARM too).
static ncclResult_t gdakiRsLogStable(struct gdakiRecHost* r, int peer, const struct gdakiRsLogPause* atPause,
                                     char* why, size_t whyLen);

// helper: the ring's head over the NIC.  app: the same with a synchronous CUDA copy (ncclGinRestoreStep, after the step's
// kernels and their last flush: every entry of the step is below it).
static ncclResult_t gdakiRsLogReadHead(struct gdakiRecHost* r, uint64_t* head);
static ncclResult_t gdakiRsLogReadHeadApp(struct gdakiRecHost* r, uint64_t* head);

// helper: per QP to `peer` (GIN-context order), the request messages posted (M). Exact only while the peer's QPs are
// quiesced; otherwise a value the count has passed.
static ncclResult_t gdakiRsLogReadMsgs(struct gdakiRecHost* r, int peer, uint64_t* msgs, int* nqp);
// helper: per QP to `peer`, the suppress budget left (request messages the spare still holds back; 0 on a survivor and
// once the spare's replay passed it: a pause answers BUSY while any is left), and the gets with data posted so far.
static ncclResult_t gdakiRsLogReadSuppress(struct gdakiRecHost* r, int peer, uint64_t* left, int* nqp);
static ncclResult_t gdakiRsLogReadGets(struct gdakiRecHost* r, int peer, uint64_t* gets, int* nqp);

// any: every logged entry below this position is covered (max of the tail and the lowest cut over the QPs that log;
// GDAKI_RS_POS_INF when no QP logs). ncclGinRestoreStep: step t is stable once this is >= the head read at Step(t).
static uint64_t gdakiRsLogCoveredUpTo(struct gdakiRecHost* r);

// pure: the highest step whose head is covered, over `n` (step, head) pairs in increasing order; `none` if none.
static uint64_t gdakiRsStableStepOf(const uint64_t* steps, const uint64_t* heads, int n, uint64_t coveredUpTo,
                                    uint64_t none);

// helper, periodic (the host branch's helper step, every 10 ms; nobody else calls it): the peers to DISARM are appended to
// *broke, each once per cause: a peer whose QP lost an operation since its cut (overflow, 9.5; its entries are covered
// until its next pause, or from its last pause on when nothing was lost since that one), a peer toward which this rank
// posted a get since its stable cut (the get rule, 9.7 item 8 and 9.10.4: the per-QP get count moved past the count read
// at that cut's pause), and every peer once a second user transparent-recovery context exists on this communicator (one
// ring per context is then no longer one per rank). The caller DISARMs them (gdakiHoldDisarm). Also the tail's advance
// over covered entries (a slot still being written stops it until the next call) and an occupancy sample.
static ncclResult_t gdakiRsLogPoll(struct gdakiRecHost* r, std::vector<int>* broke);

// helper: whether the peer's log is complete since its last stable cut (every QP to it logs from a stable cut, no break,
// no get reported since; false before the peer's first stable checkpoint).
static bool gdakiRsLogComplete(struct gdakiRecHost* r, int peer);

// helper: the peer's entries at positions [from, to) in position order (the export of 9.6). `to` must have been read
// with the peer's QPs quiesced (a hold start, or a pause), so each of the peer's entries is complete. `from` may be the
// cut of any checkpoint this rank confirmed since the peer's last stable one (at or above the kept cut). Refused (with
// why) when an entry of the peer from `from` on may be gone: `from` below the kept cut, an operation lost or a get posted
// toward the peer since the cut (counts read now), or [from, to) not inside the ring.
static ncclResult_t gdakiRsLogCollect(struct gdakiRecHost* r, int peer, uint64_t from, uint64_t to,
                                      std::vector<struct ncclGinRsLogEntry>* out, char* why, size_t whyLen);

// any: the ring's use, from host counters only (no device cost; the helper samples head - tail in gdakiRsLogPoll).
struct gdakiRsLogOcc {
  uint64_t nEntries = 0, samples = 0, occSum = 0, occMax = 0, trims = 0, tail = 0, headSeen = 0, ovfOps = 0;
  uint64_t blockedPending = 0;  // tail advances stopped by a slot still being written
};
static void gdakiRsLogOccupancy(struct gdakiRecHost* r, struct gdakiRsLogOcc* out);

// any: windows of this context's collComm deregistered after the context started (their deregistration sequence is above
// the context's registry sequence; 9.11.4 T5, 9.11.9 C2). On a change the caller DISARMs every peer until that peer's next
// stable checkpoint whose pause comes after the change (an entry since a cut may name the window as a put's source).
static uint64_t gdakiRsWinGoneCount(struct gdakiRecHost* r);

// ---- work package 9 (EXPERIMENT.md 9.3, 9.6, 9.11.3 M2) ----
// The cumulative responder executed count per QP (RL13): every QUERY_QP's rmsn of the QP adds (rmsn - last) mod 2^24; a
// Baseline after a Commit restarts `last` at the new rmsn0 without a step; the count starts at the setup's rmsn0. A
// process without the log keeps nothing (the calls return at once). Wiring (integration): G7's hold body calls
// gdakiRsExecObserve with the watch's rmsn, gdakiTsExecuted with every rmsn it reads, gdakiTsBaseline calls
// gdakiRsExecRebase with the rmsn0 it sets; all three are a hard gate of the integration (a missing one gives a wrong X,
// hence a wrong budget, silently). helper, or the application thread before the helper starts (the spare's handshake):
// the reads must be folded in the order they were taken (the watch folds under opMu, as gdakiRsExecRead does). On the
// spare, a Rebase after its QPs connect sets the connected QPs' MSN.
static void gdakiRsExecObserve(struct gdakiRecHost* r, int qpIdx, uint32_t rmsn);
static void gdakiRsExecRebase(struct gdakiRecHost* r, int qpIdx, uint32_t rmsn0);
// helper: the QP's count can no longer be trusted (a read was lost, e.g. the Baseline QUERY_QP after a Commit failed):
// from then on gdakiRsExecRead refuses for its peer, so that peer is never restored on a wrong count (fallback). It is
// permanent and reaches both ranks of the QP: this rank's checkpoints (whose drain reads every peer) and the peer's (whose
// pause this rank answers BUSY) no longer become stable, and each keeps its last stable one until its log toward the other
// is DISARMed.
static void gdakiRsExecInvalidate(struct gdakiRecHost* r, int qpIdx);
// helper: one QUERY_QP per QP to `peer` now, folded in (P at a pause, 9.4 step 2; X at a hold start after 2ERR and again
// before the restore round's Commit, 9.3 step 1). It takes opMu as the watch's QUERY_QP does and folds under it (the
// caller must not hold it); outside the firmware guard. ncclInvalidUsage when a QP's count was invalidated.
static ncclResult_t gdakiRsExecRead(struct gdakiRecHost* r, int peer, uint64_t* cum, int* nqp);
// app (the spare's import): its responder count of the QP starts at the survivor's M read at the hold start (every old
// WQE counts as executed).
static void gdakiRsExecSetBase(struct gdakiRecHost* r, int qpIdx, uint64_t cum);
// app (before the spare's helper and kernels start): per QP to `peer`, msgs = X and suppress = X - P, written with CUDA
// copies on the log state's stream and read back; refused when X < P for a QP. Each such QP gets one suppress line
// (below). The import writes the same values itself for every survivor (it has the budgets from its plan).
static ncclResult_t gdakiRsSuppressSet(struct gdakiRecHost* r, int peer, const uint64_t* x, const uint64_t* p, int nqp,
                                       char* why, size_t whyLen);
// helper: per QP to `peer`, 1 when a get was refused under a suppress budget (the spare's rule: fall back; read once the
// QP's gate count is 0).
static ncclResult_t gdakiRsLogReadGetRefused(struct gdakiRecHost* r, int peer, uint64_t* refused, int* nqp);
// helper (a survivor's restore round, after ncclGinRecoverPrepare): every WQE of the ending epoch counts as executed:
// plans with U = S and n = 0 for gdakiTsRepostApply (RL8), after the checks gdakiTsRepostPlanAll makes first.
static ncclResult_t gdakiRsPlanAllExecuted(struct gdakiRecHost* r, int peer, std::vector<struct gdakiTsRepostPlan>& plans,
                                           const char** why);
// The log export on the data socket (survivor -> the restored rank's spare), after REJOIN: a header, then per entry the
// entry and, for a put with data, its source bytes as read now, then a trailer with the verdict. The receiver reads the
// trailer first and applies nothing unless it says OK.
#define GDAKI_RS_LOGX_MAGIC 0x4c535247u  // "GRSL"
struct gdakiRsLogXHdr {
  uint32_t magic, version;   // GDAKI_RS_LOGX_MAGIC, 1
  int32_t from, to;          // the survivor's rank, the restored rank
  uint32_t incarnation, nqp; // the restored rank's new incarnation; QPs of the survivor to it (GIN-context order)
  uint64_t nonce;            // the GIN context's nonce
  uint64_t ckpt;             // the checkpoint (its step) the spare restores from: the cut is this rank's pause of it
  uint64_t cut, head;        // positions: the restored rank's cut on this survivor's ring, the head at the hold
  uint64_t nEntries;         // entries that follow
  uint64_t x[NCCL_GIN_RECOVERY_MAX_QPS];  // X per QP: this survivor's cumulative executed count of the restored rank's
                                          // messages (responder side), after the hold start's 2ERR
  uint64_t m[NCCL_GIN_RECOVERY_MAX_QPS];  // M per QP: messages this survivor posted to the restored rank (its count at
                                          // the hold start; the spare's responder counts start there)
};
struct gdakiRsLogXEnd {
  uint32_t magic, ok;        // GDAKI_RS_LOGX_MAGIC; 1: every source read and every checksum matched
  char why[120];             // else why (e.g. "source buffer changed")
};
// helper (survivor): writes the export through `put` (bytes in order; false: the stream failed). `ckpt` is the checkpoint
// the spare asked for (it goes into the header; the import checks it against the image), `cut` the head of this rank's
// pause of that checkpoint toward the peer (gdakiRsLogPauseRead; at or above the kept cut); `head`, x and m are read at
// the hold start. Refused before anything is written when the log is not whole since `cut` (gdakiRsLogCollect's rule) or when
// the request messages of its entries per QP differ from m minus M at that pause (kept per QP from the pause on, at most
// 1024 pauses). Each put's source is read over the NIC copy path, a chunk of the staging buffer at a time, under the
// window registry's lock with its window still registered; with a checksum the data is counted again. Returns ncclSuccess
// for a whole OK stream; ncclInvalidUsage (why) when refused before the stream or when the stream ended with ok = 0
// ("source buffer changed", a source window gone); ncclSystemError when a read over the NIC copy path or `put` failed.
static ncclResult_t gdakiRsLogExport(struct gdakiRecHost* r, int peer, uint64_t ckpt, uint64_t cut, uint64_t head,
                                     uint32_t incarnation, const uint64_t* x, const uint64_t* m, int nqp,
                                     bool (*put)(void* arg, const void* p, size_t n), void* arg, char* why,
                                     size_t whyLen);
// The spare's import (app thread: the spare's ncclGinRestoreResume, after its image is written and before its kernels
// and its helper start). exports[q]: the bytes survivor q sent in its STATE (the host branch's
// gdakiCkptSpareData::exports, kept unparsed; empty for this rank and for a rank with no GIN QP to it); peerP, nPeers: the
// survivors' P per QP at the checkpoint the spare restores from (gdakiCkptSpareData::hdr[0].peerP and nPeers,
// impl/rs_ckpt_api.h); ckpt: that checkpoint (hdr[0].ckpt). Every export is parsed and checked (one from every rank with
// QPs to this rank and from no other; to = this rank, the checkpoint, the incarnation, this context's nonce, its trailer
// OK, nqp, a P for its rank, X >= P per QP, every target inside this process's windows or signal table, no put over a
// signal word), the signal additions are summed again from the entries and compared per target and in total, and every
// signal target must be 8-byte aligned inside the GIN MR the survivors' atomics name while the GIN-PD loopback pair passed
// its atomic self-test. Before any device access it waits for the context's device (cudaDeviceSynchronize: the image's
// copies have landed). Then, with the window registry's lock held, in this order: (1) the data (puts, putValues) as CUDA
// copies on the log state's stream (by survivor rank, then position), waited for; (2) the signal additions, summed per
// target, as NIC fetch-and-add on the pair, each completed before the next; (3) per QP to each survivor: msgs = X,
// suppress = X - P, the responder count's base = M. Refused with nothing applied when a check fails; refused part way
// (the restore falls back) when a copy or an atomic fails.
// Why NIC atomics (the main session's decision of 2026-10-12 on review finding B1, option (b)): the spare serves the
// survivors one at a time (impl/rs_spare_api.h), so earlier survivors have published, and send their signal atomics to
// these words, before the import; a host read-add-write would lose one landing in between. With review finding A1 (decided
// the same day) the fetch-and-adds go through a loopback QP pair of their own on the GIN protection domain and name the
// very GIN MRs the survivors' atomics name (the signal table's signals_table->mr, a VA signal window's
// gdaki_mem_handle::mr; zero-based offsets): one memory key, one location, on the same HCA, whose atomics are atomic with
// respect to each other when atomic_cap >= IBV_ATOMIC_HCA. Resume refuses on a rank whose HCA is below that or whose pair
// failed its setup or self-test (+1 then -1 on the side table's first reserved word, offset 32, registered in the GIN PD by
// GIN's own routine), with the reason; the NIC copy path is not involved. The data copies need no such care: by 9.7 item
// 3 (single assignment from the checkpoint to the end of the replay) a survivor's new put never targets a location a
// logged put targets.
// Precondition: the pair has no other user during the import (the spare's application thread, before its helper starts).
// gin-mirror (v2): with the mirror the pair has two users, the step-aligned import (application thread, also after the
// helper started) and a buddy's drain fence (helper: an 8-byte READ of its pool); gdakiRsAtomicOp takes the pair's lock
// (one request at a time, completed under the lock), so neither needs more care.
// The suppress line, WARN, one per QP whose budget the import set (B = 0 included), once the spare's replay used the budget
// (from gdakiRsLogPoll) or at its context's end: "GIN/RS: rank R: suppress peer=P qp=Q budget=B suppressed=S left=L"
// (Q: the side table's QP index, context x nranks + peer; B = X - P, S = B - L).
struct gdakiCkptPeerP;  // impl/rs_ckpt_api.h (host branch)
static ncclResult_t gdakiRsSpareImport(struct gdakiRecHost* r, const struct gdakiCkptPeerP* peerP, uint32_t nPeers,
                                       const std::vector<std::vector<uint8_t>>& exports, uint64_t ckpt,
                                       uint32_t incarnation, char* why, size_t whyLen);
// ---- gin-mirror (v2): the export v2 and the step of an entry ----
// With the mirror on a survivor's STATE (impl/rs_ckpt_api.h) carries, inside its counted bytes, in this order:
//   gdakiRsLogXHdr (version 2; x and m: the user QPs only) | gdakiRsLogXHdr2 | nEntries x gdakiRsLogXEnt2 (no source
//   bytes ever) | gdakiRsLogXEnd | gdakiRsRkeysHdr + count x gdakiRsRkeyEntry (impl/rs_spare_api.h: the survivor's own
//   keys, windows, signal and counter tables, and its pool as GDAKI_MI_RKEY_POOL; rank = the survivor, incarnation =
//   its own).
// The exporter refuses before the stream (as v1) when: a put with data (kind 1, bytes > 0) toward the restored rank
// after the cut has no MIRROR flag; a MIRROR entry's segment is 0 (below the oldest live segment); a live segment after
// the cut had a break; an entry's step is unknown (no (step, head) pair covers it). The importer checks the same again.
#define GDAKI_RS_LOGX_VERSION_MI 2u
#define GDAKI_RS_LOGX_F_MIRROR 0x1u
#define GDAKI_RS_STEP_UNKNOWN (~0ULL)
struct gdakiRsLogXHdr2 {
  uint32_t flags;          // GDAKI_RS_LOGX_F_MIRROR
  uint32_t mirValid;       // 1: mirX and mirM hold (the survivor's mirror QP to the restored rank was in use, its count
                           // valid at the hold start); 0: the spare leaves its mirror QP to this survivor unused
  uint64_t mirX;           // the mirror QP's X: the survivor's executed count of the restored rank's mirror WRITEs
  uint64_t mirM;           // the mirror QP's M: mirror WRITEs the survivor posted to the restored rank (its msgs)
  uint64_t lastStep;       // the survivor's last ncclGinRestoreStep before the hold (entries after it: lastStep + 1)
  uint64_t nMirror;        // MIRROR entries
  uint64_t mirrorBytes;    // their data bytes
  uint64_t reserved[2];
};
struct gdakiRsLogXEnt2 {
  struct ncclGinRsLogEntry e;  // as logged
  uint64_t step;               // the sender's step the entry belongs to (gdakiRsStepOfPos)
  uint64_t seg;                // MIRROR: the sender's segment number for the restored rank (gdakiMiSegOfPos); else 0
};
static_assert(sizeof(struct gdakiRsLogXHdr2) == 64 && sizeof(struct gdakiRsLogXEnt2) == 80, "the export v2 records");
// The step of the entry at ring position `pos`: the first recorded Step(t) whose head (read after step t's kernels and
// their last flush) is above pos; lastStep + 1 when pos is at or above every head (an entry after the last Step);
// GDAKI_RS_STEP_UNKNOWN with no pair. steps[] and heads[] increasing (the checkpoint's step log, kept from the oldest
// live cut on).
static inline uint64_t gdakiRsStepOfPos(const uint64_t* steps, const uint64_t* heads, int n, uint64_t pos) {
  if (n <= 0) return GDAKI_RS_STEP_UNKNOWN;
  for (int i = 0; i < n; i++)
    if (pos < heads[i]) return steps[i];
  return steps[n - 1] + 1;
}
// ---- gin-restore (dev): log API (end) ----

// ---- gin-mirror (v2): entry points (restated declarations, not in the block; owner in brackets) ----
#ifndef GDAKI_MI_API_NO_ENTRY_DECLS
struct gdakiMiFetched;  // impl/rs_store_api.h
// [host] application thread or helper: a copy of the (step, head) pairs of the checkpoint's step log (ck->steps, under
// ck->mu) whose head is above `from`, increasing, and the last step recorded (the export v2's step tags).
static void gdakiCkptStepPairs(struct gdakiRecHost* r, uint64_t from, std::vector<uint64_t>* steps,
                               std::vector<uint64_t>* heads, uint64_t* lastStep);
// [spare] helper (survivor): the export v2. As gdakiRsLogExport (x, m: the user QPs at the hold start) plus the mirror
// QP's counts (from gdakiMiHoldStartRead), the step pairs (gdakiCkptStepPairs) and d's segment view (gdakiMiSegViewOf);
// the refusals above. Writes the whole stream through `put` (the rkey list included).
static ncclResult_t gdakiMiLogExport(struct gdakiRecHost* r, int peer, uint64_t ckpt, uint64_t cut, uint64_t head,
                                     uint32_t incarnation, const uint64_t* x, const uint64_t* m, int nqp,
                                     bool (*put)(void* arg, const void* p, size_t n), void* arg, char* why,
                                     size_t whyLen);
// [dev] application thread (the spare's Resume, in place of gdakiRsSpareImport's call at 11152-11157 when the mirror is
// on): every check of gdakiRsSpareImport on the v2 exports, plus: each export is version 2 with its rkey list; every
// entry's step is above ckpt; every MIRROR entry's (sender, segment, lane offset, bytes) lies in `fetched`
// (gdakiMiFetchedAt); no put with data without MIRROR. Then, under the window registry's lock: the rkey lists into this
// rank's tables (window rkey tables, the signal and counter tables' rkey tables, device and host copies; the cells'
// pool rkeys with valid 0); per user QP msgs = X, suppress = X - P, the responder base M; per mirror QP msgs = X,
// suppress 0, base M (miUse 0 when the survivor's mirValid is 0); then step ckpt + 1's inputs (data as CUDA copies from
// the FETCH buffer, signals as NIC fetch-and-add on the pair), waited for. The later steps' inputs stay queued by step.
// Refused with nothing applied when a check fails (the restore falls back as in gin-restore).
static ncclResult_t gdakiMiImportPrepare(struct gdakiRecHost* r, const struct gdakiCkptPeerP* peerP, uint32_t nPeers,
                                         const std::vector<std::vector<uint8_t>>& exports, uint64_t ckpt,
                                         uint32_t incarnation, const struct gdakiMiFetched& fetched, char* why,
                                         size_t whyLen);
// [dev] application thread, the spare's ncclGinRestoreStep(t) (first thing after its blob check, 9370, before the early
// return at 9372): injects step t + 1's inputs and waits for them; after the last queued step it calls
// gdakiMiInjectedReady(r, t + 1) (impl/rs_hold_api.h v2; also from gdakiMiImportPrepare when step ckpt + 1 is the only
// one). Nothing when nothing is queued. A failure ends the spare as gin-restore's no-BYE exit (its helper sockets
// closed with a FIN; ncclGinRestoreStep returns ncclSystemError): the survivors, still PUBLISHED, fall back.
static ncclResult_t gdakiMiImportStep(struct gdakiRecHost* r, uint64_t step, char* why, size_t whyLen);
// [dev] any thread: inputs are still queued. gdakiCkptSuppressLeft (8096-8107) ORs it: BUSY_SUPPRESS to every pause and
// no own checkpoint until the last step is injected.
static bool gdakiMiImportLeft(struct gdakiRecHost* r);
#endif  // GDAKI_MI_API_NO_ENTRY_DECLS

#endif
