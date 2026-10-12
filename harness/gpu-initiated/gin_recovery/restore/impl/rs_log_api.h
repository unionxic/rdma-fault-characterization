// rs_log_api.h - gin-restore, dev branch (impl/PARALLEL.md: work packages 4 again, 6 and 9; EXPERIMENT.md 9.4, 9.5, 9.6,
// 9.11.3 M2): the send-side log as one ring per rank, and the host functions the checkpoint (host branch, work package 5)
// and the restore round (integration) call.
//
// Binding interface between branches. The block between the two "gin-restore (dev): log API" markers below is in
// src/transport/net_ib/gdaki/gin_host_gdaki.cc byte for byte (since work package 6; the dev branch's region, early in the
// file so that every later region sees it); build_rs_dev.sh `api` checks that the two are equal. The definitions are static functions
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
//      0 magic u32 "RSS3" | 4 nqp u32 | 8 fence u64 (the drain check's READ target) | 16 csum u32 (checksum scheme) |
//     20 nEntries u32 (ring entries, a power of two; 0: no ring) | 24 entries ptr (the ring) | 32..63 reserved
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
// (the split the host branch published; 48..63 are free). This branch uses none so far: the log export goes over the data
// socket (format below), which work package 5's data server carries. A record of 21..31 that a wait parks
// (gdakiHoldDefer) is taken by this branch's code with gdakiHoldTakeMsg.
#ifndef GIN_RESTORE_RS_LOG_API_H_
#define GIN_RESTORE_RS_LOG_API_H_

#include <stddef.h>
#include <stdint.h>
#include <atomic>
#include <vector>
#ifndef NCCL_GIN_RECOVERY_MAX_QPS
#define NCCL_GIN_RECOVERY_MAX_QPS 64  // nccl.h.in (the host file has it)
#endif

// ---- gin-restore (dev): log API (begin; impl/rs_log_api.h, byte for byte) ----
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

// ---- work package 9 (provisional until its hand-back; the names and meaning are meant to stay) ----
// helper: the cumulative responder executed count per QP (RL13): every QUERY_QP's rmsn of the QP (G7's watch sample,
// gdakiTsExecuted) adds (rmsn - last) mod 2^24; a Baseline after a Commit restarts `last` at the new rmsn0 without a
// step. A process that does not ask for the restore keeps nothing.
static void gdakiRsExecObserve(struct gdakiRecHost* r, int qpIdx, uint32_t rmsn);
static void gdakiRsExecRebase(struct gdakiRecHost* r, int qpIdx, uint32_t rmsn0);
// helper: one QUERY_QP per QP to `peer` now (outside the firmware guard, as the watch), folded in: P at a pause
// (9.4 step 2), X at a hold start after 2ERR and again before the restore round's Commit (9.3 step 1).
static ncclResult_t gdakiRsExecRead(struct gdakiRecHost* r, int peer, uint64_t* cum, int* nqp);
// helper (the spare, before its replay): its responder counts toward `peer` start at the survivor's M read at the hold
// start (every old WQE counts as executed).
static void gdakiRsExecSetBase(struct gdakiRecHost* r, int qpIdx, uint64_t cum);
// helper (the spare, before its replay): per QP to `peer`, suppress = X - P and msgs = X (9.6), over the NIC; refused
// when X < P for a QP.
static ncclResult_t gdakiRsSuppressSet(struct gdakiRecHost* r, int peer, const uint64_t* x, const uint64_t* p, int nqp,
                                       char* why, size_t whyLen);
// helper (a survivor's restore round, after ncclGinRecoverPrepare): every WQE of the ending epoch counts as executed:
// plans with U = S and n = 0 for gdakiTsRepostApply (RL8), with the checks gdakiTsRepostPlanAll makes first.
static ncclResult_t gdakiRsPlanAllExecuted(struct gdakiRecHost* r, int peer, std::vector<struct gdakiTsRepostPlan>& plans,
                                           const char** why);
// The log export on the data socket (survivor -> the restored rank's spare), after REJOIN: a header, then per entry the
// entry and, for a put with data, its source bytes as read now, then a trailer with the verdict. The receiver applies
// nothing unless the trailer says OK.
#define GDAKI_RS_LOGX_MAGIC 0x4c535247u  // "GRSL"
struct gdakiRsLogXHdr {
  uint32_t magic, version;   // GDAKI_RS_LOGX_MAGIC, 1
  int32_t from, to;          // the survivor's rank, the restored rank
  uint32_t incarnation, nqp; // the restored rank's new incarnation; QPs of the survivor to it (GIN-context order)
  uint64_t nonce;            // the GIN context's nonce
  uint64_t cut, head;        // positions: the restored rank's stable cut on this survivor's ring, the head at the hold
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
// helper (survivor): writes the export through `put` (bytes in order; false: the socket failed). Each put's source is
// read over the NIC copy path under the window registry's lock after checking that the window is still registered;
// with a checksum the data is counted again and a mismatch ends the export with ok = 0 and "source buffer changed".
static ncclResult_t gdakiRsLogExport(struct gdakiRecHost* r, int peer, uint64_t cut, uint64_t head, uint32_t incarnation,
                                     const uint64_t* x, const uint64_t* m, int nqp,
                                     bool (*put)(void* arg, const void* p, size_t n), void* arg, char* why,
                                     size_t whyLen);
// The spare's import (app thread: the spare's ncclGinRestoreResume, after its image is written and before its kernels
// and its helper start; CUDA calls are allowed there). exports[q]: the bytes survivor q sent in its STATE (the host
// branch's gdakiCkptSpareData::exports, kept unparsed; empty for this rank); peerP, nPeers: the survivors' P per QP at
// the checkpoint the spare restores from (gdakiCkptSpareData::hdr[0].peerP and nPeers, impl/rs_ckpt_api.h). Every export
// is parsed and checked first (to = this rank, the incarnation, this context's nonce, its verdict OK, a P for its rank,
// X >= P per QP); then the entries are applied to this process's windows and signal table in a fixed order (by survivor
// rank, then position) and per QP to each survivor: suppress = X - P, msgs = X, the responder count's base = M. Refused
// with nothing applied when a check fails; refused part way (the restore falls back) when a copy fails.
// One WARN line per QP with a budget when the spare's replay has used it (or at its context's end): "GIN/RS: rank R:
// suppress peer=P qp=Q budget=B suppressed=S left=L" (B = X - P, S = B - L).
struct gdakiCkptPeerP;  // impl/rs_ckpt_api.h (host branch)
static ncclResult_t gdakiRsSpareImport(struct gdakiRecHost* r, const struct gdakiCkptPeerP* peerP, uint32_t nPeers,
                                       const std::vector<std::vector<uint8_t>>& exports, uint32_t incarnation,
                                       char* why, size_t whyLen);
// ---- gin-restore (dev): log API (end) ----

#endif
