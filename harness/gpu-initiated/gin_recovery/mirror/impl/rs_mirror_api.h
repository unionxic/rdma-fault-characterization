// rs_mirror_api.h - gin-mirror, shared interface (EXPERIMENT.md 9.2, 9.3, 9.4's include/exclude table, 9.5;
// impl/PARALLEL.md): the side table v4 (the mirror fields and the per-destination cells), the log entry's MIRROR flag,
// the pool layout, the helper records 48 MIRROR_SETUP and 49 CKPT_PULL, the HOLDING payload, the two QP sets and the
// include/exclude table, the order of the fault-record hooks, the mirror part of PAUSED's armable verdict, the segment
// rules, and the line keys the test branch reads. The checkpoint store, CKPT_STABLE's fields and the activation blob v2
// are in impl/rs_store_api.h; INJECTED (38) and PUBLISHED's end in impl/rs_hold_api.h v2; the export v2 and the import
// in impl/rs_log_api.h v2.
//
// Base: gin-restore's final layer, ../../restore/impl/rs_layer.diff (md5 f005bb67, build i5). Every number "NNNN" or
// "NNNN-NNNN" below is a line of that diff; "rs tree NNNN" is a line of gin_host_gdaki.cc in the tree that diff gives
// (EXPERIMENT.md 머리말). The mirror layer is a diff ON TOP of that tree.
//
// The invariant (EXPERIMENT.md 9.3, user decision 2026-10-13): the mirror is an auxiliary path. Every failure of it (a
// full lane, a closed mirror gate, an unconfirmed flush, a fault record of a mirror QP, a self-loop error, a count that
// went wrong) only turns off the restore of the destinations it serves (their lane broken, their DISARM). It never
// fails a send, a flush or a wait of the application, never declines the buddy, never touches another rank's
// protection.
//
// Binding interface between branches. Three blocks of this file are pasted verbatim; build_mi.sh `api` checks each:
//   - "gin-mirror: device layout": src/include/nccl_device/gin/gdaki/gin_gdaki_device_host_common.h, in place of
//     diff 1168-1215 (gin-restore's NCCL_GIN_RS_SIDE_MAGIC .. the QP entry's static_assert; the checksum defines
//     1169-1172 move into the block unchanged). Pasted by the dev branch.
//   - "gin-mirror: device helpers": the same header, after ncclGinRsCsumBuf (diff 1452), before struct
//     ncclGinGdakiGPUContext. Pasted by the dev branch.
//   - "gin-mirror: host API": src/transport/net_ib/gdaki/gin_host_gdaki.cc, right after the end marker of gin-restore's
//     log API block (diff 2417). Pasted by EVERY branch in its first commit (identical edits merge cleanly).
// The blocks hold only types, constants and pure static inline functions (no unused-function warning in a tree that
// does not call them). The entry points after the blocks are restated declarations (as impl/rs_spare_api.h): the owner
// named at each defines it with exactly this signature; a branch that calls another branch's entry point before the
// integration keeps a placeholder definition in its own region (impl/PARALLEL.md). Nothing here is included by the
// build; outside the blocks the file only adds what a standalone syntax check needs (g++ -fsyntax-only,
// impl/PARALLEL.md).
#ifndef GIN_MIRROR_RS_MIRROR_API_H_
#define GIN_MIRROR_RS_MIRROR_API_H_

#include <stddef.h>
#include <stdint.h>
#include <vector>
#ifndef NCCL_GIN_RECOVERY_MAX_QPS
#define NCCL_GIN_RECOVERY_MAX_QPS 64  // nccl.h.in
#endif

// ---- gin-mirror: device layout (begin; impl/rs_mirror_api.h, byte for byte) ----
// The side table of one GDAKI context (gin-restore 1158-1167; v4 = gin-restore's "RSS3" + the mirror). A 128-byte
// header, nqp QP entries of 128 bytes, then (mirror on) one ncclGinMiCell per rank, then the log ring 256-byte aligned.
// With the mirror the context array has one more GIN context, the mirror context, after the user contexts (its index
// miCtx = the number of user contexts), so nqp = (user contexts + 1) x nranks and the mirror QP to peer b is QP miCtx x
// nranks + b: in GIN-context order the mirror QP is the LAST QP to every peer. Without the mirror nothing of the layout
// moves but the magic: miOn 0, miCellsOff 0, no cells.
#define NCCL_GIN_RS_SIDE_MAGIC 0x34535352u  // "RSS4" (gin-mirror: the mirror fields at 40..63 and the cell array)
// Overwrite detection of a put's source (NCCL_GIN_RESTORE_CHECKSUM): the scheme the sending thread uses.
#define NCCL_GIN_RS_CSUM_OFF 0u
#define NCCL_GIN_RS_CSUM_SAMPLED 1u  // the first 64 bytes of every 4 KiB of the data and its last 64 bytes
#define NCCL_GIN_RS_CSUM_FULL 2u     // every byte
// The header. Written by the host before the side table is published (plain device loads): magic, nqp, csum, nEntries,
// entries, miOn, miCtx, miCellsOff, miNCells (none changes after the publish, 9.7's publish row). The ring's control
// words as gin-restore: head (device CAS inside the gate), tail (host, over the NIC), ovfCount (device, on overflow
// only).
struct ncclGinRsSide {
  uint32_t magic;
  uint32_t nqp;          // QP entries that follow (the device skips the side table for an index at or above it)
  uint64_t fence;        // the 8-byte READ target of the checkpoint's drain check (9.4 step 3; strict loopback MR)
  uint32_t csum;         // NCCL_GIN_RS_CSUM_* (host, before the context is handed out); never with miOn (condition 36)
  uint32_t nEntries;     // ring entries, a power of two (0: no ring)
  void* entries;         // the ring: nEntries entries of 64 bytes; position p in slot p mod nEntries
  uint64_t pairTest;     // 32: the GIN-PD loopback pair's self-test word (+1 then -1; gin-restore's reserved0[0], 2405)
  uint32_t miOn;         // 40: 1 = this context mirrors (the setup agreement turned the mirror on); 0: the device never
                         //     mirrors and never waits for a mirror QP
  uint32_t miCtx;        // 44: the mirror context's index (= user GIN contexts); valid when miOn
  uint64_t miCellsOff;   // 48: byte offset of the cell array from the side table's start (0: none)
  uint32_t miNCells;     // 56: cells (= nranks when miOn, else 0)
  uint32_t miRsv;        // 60: 0
  uint64_t head;         // positions reserved so far (gin-restore: a CAS only when the entry fits; overflow: none)
  uint64_t tail;         // first position kept (host: the stable cuts of the peers; the measurement mode's helper)
  uint64_t ovfCount;     // operations of every QP not logged because the ring was full (device, overflow only)
  uint64_t reserved1[5];
};
// One QP's entry (gin-restore's fields unchanged; miUse added at 48 for the mirror context's QPs).
struct ncclGinRsQp {
  uint64_t msgs;         // request messages the hold path posted on this QP (device atomic add, every post, logOn
                         // or not; a get's READ counts, a 0-byte put's NOP and a suppressed operation do not): 9.4's
                         // M_q. On a mirror QP: the mirror WRITEs (one per 1 GiB chunk), M_mir of EXPERIMENT.md 9.4
  uint64_t suppress;     // request messages the spare process still holds back on this QP (0 on every mirror QP)
  uint64_t ovfCount;     // this QP's operations not logged because the ring was full (device atomic add, overflow only)
  uint64_t ovfHead;      // 1 + the ring's head when this QP last overflowed (device atomic max; 0: never; diagnostic)
  uint32_t logOn;        // the helper sets it in a checkpoint input pause toward the peer (never on a mirror QP)
  uint32_t getRefused;   // device: a get was asked while suppress was not 0
  uint64_t gets;         // gets with data the hold path posted on this QP (device atomic add)
  uint32_t miUse;        // 48: mirror context QPs only: 1 = the device may post mirror WRITEs on it and the macro
                         //     build's flush and wait wait for it; 0 = not connected, or given up (a fault record
                         //     absorbed, a count invalidated). Host writes it over the NIC; device: system-scope loads
  uint32_t miRsv;        // 52: 0
  uint64_t reserved[9];
};
static_assert(sizeof(struct ncclGinRsSide) == 128, "the side table header is 128 bytes");
static_assert(offsetof(struct ncclGinRsSide, fence) == 8 && offsetof(struct ncclGinRsSide, csum) == 16 &&
                offsetof(struct ncclGinRsSide, nEntries) == 20 && offsetof(struct ncclGinRsSide, entries) == 24 &&
                offsetof(struct ncclGinRsSide, pairTest) == 32 && offsetof(struct ncclGinRsSide, miOn) == 40 &&
                offsetof(struct ncclGinRsSide, miCtx) == 44 && offsetof(struct ncclGinRsSide, miCellsOff) == 48 &&
                offsetof(struct ncclGinRsSide, miNCells) == 56 && offsetof(struct ncclGinRsSide, head) == 64 &&
                offsetof(struct ncclGinRsSide, tail) == 72 && offsetof(struct ncclGinRsSide, ovfCount) == 80,
              "the side table header layout (the host reads it over the NIC by these offsets)");
static_assert(sizeof(struct ncclGinRsQp) == 128, "a side table QP entry is 128 bytes");
static_assert(offsetof(struct ncclGinRsQp, msgs) == 0 && offsetof(struct ncclGinRsQp, suppress) == 8 &&
                offsetof(struct ncclGinRsQp, ovfCount) == 16 && offsetof(struct ncclGinRsQp, ovfHead) == 24 &&
                offsetof(struct ncclGinRsQp, logOn) == 32 && offsetof(struct ncclGinRsQp, getRefused) == 36 &&
                offsetof(struct ncclGinRsQp, gets) == 40 && offsetof(struct ncclGinRsQp, miUse) == 48,
              "the side table QP entry layout (the host reads it over the NIC by these offsets)");
// One cell per destination rank d (cell d; the own rank's cell is never valid): this rank's lane for d in the pool of
// d's buddy b = ncclGinMiBuddyOf(d, nranks). Who writes what:
//   - valid, rkeyBe, seg, laneBase, laneBytes, cursor: the host, over the NIC, only while every user QP to d has its
//     gate odd with count 0 (d's input pause, a hold of d), and in b's restore round (gdakiMiPoolRekey, valid 0, before
//     the mirror QP to b is published); read back after the write. One more exception: a fault record's absorption
//     writes valid = 0 at any time (a device thread that read 1 just before finds the mirror gate closed or posts on a
//     QP in ERR: either way a break, never a wrong lane).
//   - cursor: also the device, atomic add of the put's bytes rounded up to 64 (ncclGinMiRound64), inside d's gate.
//   - broken: the device only (atomic add): a full lane, a closed mirror gate, a failed or timed-out mirror wait.
//     Cumulative: the host never writes it and compares it with the value it read at the segment's switch.
// The device reads valid and rkeyBe with system-scope relaxed loads (written over the NIC), the rest with plain loads
// after valid (they change only while d's gates are odd).
struct ncclGinMiCell {
  uint32_t valid;        //  0: 1 = mirror the puts with data to d
  uint32_t rkeyBe;       //  4: the pool rkey of buddy(d), big-endian as the WQE takes it
  uint64_t seg;          //  8: the segment number of this rank's lane for d (host; on the device diagnostic only)
  uint64_t laneBase;     // 16: the lane's offset in the pool for that segment (ncclGinMiLaneOff)
  uint64_t laneBytes;    // 24: L (NCCL_GIN_RESTORE_MIRROR_LANE)
  uint64_t cursor;       // 32: bytes of the lane taken; may pass laneBytes (that put is a break, no mirror)
  uint64_t broken;       // 40: breaks of this lane, cumulative
  uint64_t reserved[2];  // 48
};
static_assert(sizeof(struct ncclGinMiCell) == 64, "a mirror cell is 64 bytes");
static_assert(offsetof(struct ncclGinMiCell, rkeyBe) == 4 && offsetof(struct ncclGinMiCell, seg) == 8 &&
                offsetof(struct ncclGinMiCell, laneBase) == 16 && offsetof(struct ncclGinMiCell, laneBytes) == 24 &&
                offsetof(struct ncclGinMiCell, cursor) == 32 && offsetof(struct ncclGinMiCell, broken) == 40,
              "the mirror cell layout (the host reads and writes it over the NIC by these offsets)");
// The log entry's sixth flag bit (flags are bits 26..31 of qpKf; gin-restore uses 0x01, 0x02, 0x04 and bits 3..4 for
// the checksum scheme, 1222-1226): the put's data was mirrored. Then word 8..11 (`csum`) holds the data's offset in
// this rank's lane for the destination in 64-byte units (the cursor's value before the add, / 64). Never with a
// checksum scheme (Resume condition 36), never with SPLIT (a spare's cells are invalid while it holds messages back),
// only on kind PUT with bytes > 0. The segment is not in the entry: the exporter derives it from the entry's position
// and the cuts of the destination's pauses (gdakiMiSegOfPos, the host API block).
#define NCCL_GIN_RS_LOGF_MIRROR 0x20u
// ---- gin-mirror: device layout (end) ----

#ifndef NCCL_GIN_RS_HD  // the device-host common header defines it (diff 1256-1262); a standalone check needs it here
#define NCCL_GIN_RS_HD inline
#endif

// ---- gin-mirror: device helpers (begin; impl/rs_mirror_api.h, byte for byte) ----
// The pool and the lanes, pure (the device's send path and the host compute the same offsets). Buddy of logical rank p
// (= gdakiHoldBuddyOf, impl/rs_hold_api.h): p xor 1, or rank 0 for the last rank of an odd count.
NCCL_GIN_RS_HD int ncclGinMiBuddyOf(int p, int n) {
  if (n < 2) return -1;
  const int b = p ^ 1;
  return b < n ? b : (p == 0 ? 1 : 0);
}
// The wards of rank b (the ranks whose buddy is b: their checkpoint and their pool lanes live at b), increasing, into
// w[0..1]; returns how many (0, 1, or 2: rank 0 of an odd count keeps 1 and n - 1).
NCCL_GIN_RS_HD int ncclGinMiWardsOf(int b, int n, int* w) {
  int k = 0;
  const int c0 = b ^ 1, c1 = n - 1;
  if (c0 >= 0 && c0 < n && c0 != b && ncclGinMiBuddyOf(c0, n) == b) w[k++] = c0;
  if (c1 >= 0 && c1 != c0 && c1 != b && ncclGinMiBuddyOf(c1, n) == b) w[k++] = c1;
  return k;
}
// d's index among its buddy's wards (0 or 1); -1 when d has no buddy.
NCCL_GIN_RS_HD int ncclGinMiWardIdx(int d, int n) {
  const int b = ncclGinMiBuddyOf(d, n);
  if (b < 0) return -1;
  int w[2];
  const int k = ncclGinMiWardsOf(b, n, w);
  for (int i = 0; i < k; i++)
    if (w[i] == d) return i;
  return -1;
}
// Sender s's lane for destination d: every rank but d sends, n - 1 lanes in rank order (the buddy's own lane included).
NCCL_GIN_RS_HD int ncclGinMiLaneOf(int s, int d) { return s < d ? s : s - 1; }
// The pool of a buddy: wards x S slots x (n - 1) lanes x L bytes, zero-based (iova 0): segment `seg` of a lane uses
// slot seg mod S. The lane's offset of (ward index, slot, lane):
NCCL_GIN_RS_HD uint64_t ncclGinMiLaneOff(int wardIdx, uint64_t slot, int lane, int n, uint64_t slots,
                                         uint64_t laneBytes) {
  return (((uint64_t)wardIdx * slots + slot) * (uint64_t)(n - 1) + (uint64_t)lane) * laneBytes;
}
NCCL_GIN_RS_HD uint64_t ncclGinMiPoolBytes(int nWards, uint64_t slots, int n, uint64_t laneBytes) {
  return (uint64_t)nWards * slots * (uint64_t)(n - 1) * laneBytes;
}
// The cursor's step for a put of `bytes` (the lane keeps every put 64-byte aligned).
NCCL_GIN_RS_HD uint64_t ncclGinMiRound64(uint64_t bytes) { return (bytes + 63u) & ~(uint64_t)63u; }
// A put whose cursor add returned `off` fits the lane.
NCCL_GIN_RS_HD bool ncclGinMiFits(uint64_t off, uint64_t bytes, uint64_t laneBytes) {
  return off <= laneBytes && ncclGinMiRound64(bytes) <= laneBytes - off;
}
// The side table's QP index of the mirror QP to `peer`.
NCCL_GIN_RS_HD uint32_t ncclGinMiQpIdx(uint32_t miCtx, uint32_t nranks, uint32_t peer) { return miCtx * nranks + peer; }
// ---- gin-mirror: device helpers (end) ----

// The host file's types the host API block names (the host file has them; a standalone check needs a declaration).
struct gdakiRecHost;
struct gdakiTsMsg;
struct gdakiTsFault;

// ---- gin-mirror: host API (begin; impl/rs_mirror_api.h, byte for byte) ----
// ---- helper-socket records of gin-mirror ----
// gin-restore: hk 1..10, host 11..20, dev 21..31, spare 32..47 (rs_hold_api.h). gin-mirror takes 38 (INJECTED, in the
// spare range: the restored rank sends it; impl/rs_hold_api.h v2), 48 and 49 (this block), 50 and 51
// (impl/rs_store_api.h); 52..63 stay free. Every one is a record of the restore (11..63): every wait parks it
// (gdakiHoldDefer) and its owner takes it with gdakiHoldTakeMsg in its helper step, in arrival order per peer.
#define GDAKI_TS_MI_SETUP 48u    // r -> every peer, once, at the setup's end: its mirror QP and pool
#define GDAKI_TS_CKPT_PULL 49u   // s -> d: pull d's next checkpoint (s's lane for d passed the pull threshold)
#define GDAKI_MI_WIRE_VERSION 1u
// MIRROR_SETUP (48), fields: from, nonce as every record; arg = the sender's rank; round = 0; pad = 0; nqp = 1; the
// payload below memcpy'd into gdakiTsMsg::executed (256 bytes). Sent on the installed helper socket after the setup
// agreement decided the mirror (the agreement's policyPad mirror bit, rs tree 9531-9536, 9572-9596), before the helper
// thread starts, by every rank to every peer; each rank reads every peer's record (bounded by NCCL_GIN_TS_HANDSHAKE_MS)
// and only then connects its mirror QP to that peer (RTR with the peer's qpn and sqPsn; LID, GID, MTU and ordering from
// the peer's user context 0 exchange: the same port), then reads its responder MSN base (gdakiRsExecRebase). A record
// that is missing, malformed or says on = 0 leaves that pair's mirror QP unconnected (miUse 0) and is Resume condition
// 38 on the first incarnation. The spare process never exchanges it (it is outside the transcript): the survivors' QPNs
// come from TOKEN and their pool rkeys from STATE's rkey lists (EXPERIMENT.md 9.3, 9.4).
struct gdakiMiSetup {
  uint32_t version;     // GDAKI_MI_WIRE_VERSION
  uint32_t on;          // 1: the sender's mirror QP to the receiver exists (state INIT) and its pool is registered
  uint32_t qpn;         // the sender's mirror QP to the receiver
  uint32_t sqPsn;       // its initial send PSN
  uint32_t poolRkey;    // the sender's pool rkey, host order (0: the sender keeps no ward)
  uint32_t slots;       // S (NCCL_GIN_RESTORE_MIRROR_SLOTS)
  uint64_t laneBytes;   // L (NCCL_GIN_RESTORE_MIRROR_LANE)
  uint64_t poolBytes;   // the sender's pool bytes (ncclGinMiPoolBytes)
  uint32_t nWards;      // the sender's wards (0..2)
  uint32_t pad;
};
static_assert(sizeof(struct gdakiMiSetup) == 48, "MIRROR_SETUP's payload");
// CKPT_PULL (49), fields: arg = the destination d; round = s's segment number for d whose fill passed the threshold;
// pad = that fill in percent of L (diagnostic). At most one per (d, segment). d's next ncclGinRestoreStep takes a
// checkpoint even before NCCL_GIN_RESTORE_CKPT_STEPS steps passed (gdakiMiPullTake ORed into gdakiCkptDue's verdict at
// 9383); a pull that arrives while a checkpoint runs counts for the next Step.

// ---- the per-context state of the mirror layer ----
// struct gdakiRecHost gets ONE member, `struct gdakiMiState mi;`, as its last member (after `rsLog`, diff 2471), added
// by every branch in its first commit with exactly that text (identical edits merge). Each branch keeps its own state
// behind its own pointer, allocates it in its own setup and frees it in its own teardown; nobody else touches it.
struct gdakiMiHost;          // host branch: setup, pool, cells, segments, pulls, absorption, INJECTED
struct gdakiStoreState;      // store branch: the store (both sides), the upload QP
struct gdakiMiSpareState;    // spare branch: HOLDING's counts, drain, activation v2, FETCH, export v2
struct gdakiMiImport;        // dev branch: the step-aligned import
struct gdakiMiState {
  bool on = false;           // host, at the setup's end: the mirror is on for this context (never changes after)
  int ctx = -1;              // host: the mirror context's index (= the user GIN contexts) when on
  struct gdakiMiHost* host = nullptr;
  struct gdakiStoreState* store = nullptr;
  struct gdakiMiSpareState* spare = nullptr;
  struct gdakiMiImport* imp = nullptr;
};

// ---- parameters (the host branch defines the NCCL_PARAMs; values are read once per context) ----
// NCCL_GIN_RESTORE_MIRROR             0 (default) | 1: ask for the mirror (with NCCL_GIN_RESTORE; every rank alike)
// NCCL_GIN_RESTORE_MIRROR_SLOTS       S, default 3, 2..4: segment slots per lane (GDAKI_MI_SEG_MAX)
// NCCL_GIN_RESTORE_MIRROR_LANE        L in bytes, default 1 MiB: a positive multiple of 64 (condition 37)
// NCCL_GIN_RESTORE_MIRROR_PULL        percent of L that sends CKPT_PULL, default 50, 0 = never
// NCCL_GIN_RESTORE_MIRROR_POOL_MAX_MB this process's pool at most, default 2048 (condition 37)
// NCCL_GIN_RESTORE_MIRROR_FETCH_MB    the spare's FETCH buffer (registered at its init replay), default 512
// NCCL_GIN_RESTORE_LOG_MEASURE_MIRROR 0 (default) | self | peer: the measurement mode's mirror arm (EXPERIMENT.md 7)
// The store's parameters are in impl/rs_store_api.h.

// ---- Resume conditions 34-40 (gdakiRsLocalCheck, 2780-2838; the reason strings, which every rank prints alike) ----
#define GDAKI_MI_R34 "the mirror was asked but the setup agreement turned it off"
#define GDAKI_MI_R35 "the mirror pool could not be registered"
#define GDAKI_MI_R36 "NCCL_GIN_RESTORE_MIRROR and NCCL_GIN_RESTORE_CHECKSUM are both on"
#define GDAKI_MI_R37 "NCCL_GIN_RESTORE_MIRROR_LANE is not a positive multiple of 64, or the pool is above its limit"
#define GDAKI_MI_R38 "a buddy's pool information did not arrive, or a mirror QP could not be connected"
#define GDAKI_MI_R39 "NCCL_GIN_RESTORE_MIRROR_SLOTS or NCCL_GIN_RESTORE_MIRROR_LANE differs between ranks"
#define GDAKI_MI_R40 "the mirror needs one GIN context more than the user's, and the user's are 64"
// 38 is not checked on a spare process (no MIRROR_SETUP there, 9.3). 39 is decided on the Resume exchange (every rank's
// S and L), as gin-restore's gathered conditions; the exchange also carries the mirror bit (a rank whose bit differs:
// 34).

// ---- the two QP sets (EXPERIMENT.md 9.4, the re-review's split) ----
// "User only": the QPs to a peer of the user contexts, GIN-context order (gin-restore's set, unchanged without the
// mirror). "With mirror": the same, then the mirror QP to that peer LAST (its context is the last one). With the mirror
// off the two sets are the same. gdakiRsExecRead refuses when any QP of its set has an invalidated count (10380-10383),
// so the user's restore reads the user set and a mirror QP's count is read on its own (gdakiMiExecReadMirror): an
// invalid mirror count breaks the lanes it serves, never the user's restore. Where each set is used; "who" is the
// branch that edits the site (impl/PARALLEL.md has the line spans):
//   - input pause, user only, host: gdakiCkptQuiesce 7932-7997, gdakiCkptEmptyRound 7998-8025, gdakiCkptPauseState
//     8026-8043 and gdakiCkptOnPause's epochAt walk 8136-8138 walk under gdakiTsScopeGuard(gdakiMiUserScope(r)).
//   - PAUSED's M and P (8145-8167), the drain check 8325-8371: user only, no edit (the narrowed functions below).
//   - gdakiRsLogPauseRead, gdakiRsLogStable, gdakiRsLogReadQpField (msgs, suppress, gets, getRefused),
//     gdakiRsLogCollect, gdakiRsExecRead, gdakiRsSuppressSet (10065-10469): user only, dev (gdakiRsQpsOfPeer narrowed,
//     9940).
//   - the export's check "messages of the entries = m - M": user only, spare (export v2).
//   - hold start, quiesce and 2ERR (hk's walk over every context): with mirror, no edit.
//   - hold start, X and M of the user set (6880-6891): user only, no edit. The mirror QP's X and M_mir and the cell of
//     d: spare (gdakiMiHoldStartRead).
//   - restore round: Prepare, the endpoint swap, Commit, Baseline, the publish (7359-7413): with mirror, no edit (hk
//     walks every context). X again before the Commit (7372-7383): user only, no edit; the mirror QP alone again,
//     spare (gdakiMiCommitCheck: a moved mirror count breaks its lanes, never a fallback).
//   - REJOIN, TOKEN, READY lists (5644-6497): with mirror, spare: the mirror QPN comes from TOKEN and is left out of
//     every QPN comparison (the transcript has none).
//   - the spare's import, msgs = X and the responder base = M: with mirror, dev (the mirror QP's budget is 0).
//   - suppress budgets (gdakiRsSuppressSet): user only, dev.
//   - the QP watch, transparent rounds with a live peer, the scan: with mirror, host (records: the hook order below).
// A transparent round with a live peer b whose scope covers the mirror context makes the mirror gate to b odd for the
// round: senders' mirror puts toward b's wards meanwhile break (9.2 step 4) and those wards are DISARMed. Known, by
// design.

// ---- the order of the fault-record hooks (EXPERIMENT.md 9.5, decision (8) and the re-review) ----
// G4, gdakiPolicyRoute (5489-5495), becomes, in this order:
//   if (r != nullptr && gdakiMiAbsorb(r, f)) return false;           // a record of the mirror context, any class
//   return r == nullptr || r->hold == nullptr || gdakiHoldRoute(r, f);  // gin-restore unchanged
// gdakiMiAbsorb raises qs[qi].handled to the record's epoch + 2 (as gdakiHoldRoute does, rs tree 11014) so the scan's
// lost-record check never counts it, writes miUse 0 on that mirror QP and valid 0 on the cells of the wards it serves,
// breaks those lanes and DISARMs those wards (broadcast). It runs before gdakiHoldRoute because a PUBLISHED peer's
// record falls back there (rs tree 11019-11024). The scan (gdakiTsScan, rs tree 10065-10085): for a mirror QP the three
// conditions (abandoned, DEV_FAILED, a lost record twice) call gdakiMiAbsorbQp instead of declining the peer (the
// device's mirror path never sets abandoned, poison, DEV_FAILED or a sticky error, so they mean a bug: the lanes break,
// nobody is declined). A mirror QP stays unused until the restore round with its peer reconnects it (miUse 1 again
// after the publish, 9.6's re-arm). With the mirror off gdakiMiAbsorb returns false at once: fail-fast and gin-restore
// are unchanged.

// ---- segments (EXPERIMENT.md 9.3) ----
// Sender s keeps, per destination d, a sequence of segment numbers (from 1; 0 = none) and the live segments: the open
// one and the closed ones not yet dropped. A switch happens in d's input pause, after gdakiRsLogPauseRead (gates odd,
// count 0) and before PAUSED: read the cell (seg, laneBase, cursor, broken), write {seg + 1, the next slot's laneBase,
// cursor 0, valid 1}, read it back; record (closed seg, the pause's ring head = its cut, fill = min(cursor, L), broken
// at close, the checkpoint k). Rollback: a pause that ends WITHOUT a publish of its own end (gdakiCkptEndPause: r gave
// it up with pad 1, the pause's bound, a failed send; and the confirmation that finds the gates not intact) writes the
// old values back before its empty round and forgets the record. A pause that a round or a hold start ended keeps its
// switch (the gates were published or are held: device writes may already be in the new segment); it counts as a void
// after the publish. Drop: CKPT_STABLE(k) of d drops every closed segment whose closing checkpoint is <= k. Restart: a
// switch that would make the live segments more than S DISARMs d (broadcast), drops every live segment, and opens the
// new one; that pause's PAUSED is not armable (so no rank arms d on it; d is armed again at its next stable
// checkpoint). A hold of d keeps its live segments as they are and reads the open one from the device (the hold may
// take over a pause). At d's INJECTED (mirror on) a survivor drops every closed segment of d (the import used them) and
// keeps the open one. When d's buddy b is restored, a survivor's segments for b's wards are dropped and their cells
// written invalid with the new pool rkey (the restore round, before its publish: gdakiMiPoolRekey). The spare process
// starts every destination's sequence at 1 with invalid cells.
enum { GDAKI_MI_SW_OK = 0, GDAKI_MI_SW_RESTART = 1 };
// liveBefore: live segments of (s, d) before the switch, the open one included.
static inline int gdakiMiSwitchVerdict(uint32_t liveBefore, uint32_t slots) {
  return liveBefore + 1u > slots ? GDAKI_MI_SW_RESTART : GDAKI_MI_SW_OK;
}
#define GDAKI_MI_OPEN (~0ULL)  // closedAt of the open segment
// The segment an entry toward d at ring position `pos` was mirrored into: the first closed segment (in closing order)
// whose cut is above pos, else the open one. cuts[] increasing; 0 when pos is below the oldest live segment's start
// (`floor`: the cut the oldest live segment opened at; the export refuses such an entry).
static inline uint64_t gdakiMiSegOfPos(const uint64_t* cuts, const uint64_t* segs, int n, uint64_t openSeg,
                                       uint64_t floor, uint64_t pos) {
  if (pos < floor) return 0;
  for (int i = 0; i < n; i++)
    if (pos < cuts[i]) return segs[i];
  return openSeg;
}
// PAUSED's armable toward checkpointing rank r (8155-8156), with the mirror: gin-restore's verdict AND this rank's
// switch for r succeeded, the mirror path to buddy(r) is usable (its mirror QP miUse 1, or the self loop when this rank
// is buddy(r), without an error), buddy(r)'s pool rkey is known, and this pause did not restart r's segments. The
// store's readiness is r's own (no checkpoint before STORE_ACK, impl/rs_store_api.h), not a part of PAUSED.
static inline bool gdakiMiPausedArmable(bool rsArmable, bool mirrorOn, bool switched, bool pathUsable, bool poolKnown,
                                        bool restarted) {
  if (!mirrorOn) return rsArmable;
  return rsArmable && switched && pathUsable && poolKnown && !restarted;
}

// ---- HOLDING (gin-restore's record 18) with the mirror ----
// Holder s of dead rank d sends HOLDING(d) to b = buddy(d) as gin-restore does (6900-6909), with pad |=
// GDAKI_HOLD_F_MIRROR and this payload memcpy'd into executed (read at the hold start, gates of d odd with count 0:
// every mirror of a put to d was posted). The buddy itself, a holder too, takes its own values locally (its lane for d
// goes over its self loop).
#define GDAKI_HOLD_F_MIRROR 0x1u  // HOLDING's pad: the payload below is valid
#define GDAKI_MI_SEG_MAX 4        // live segments a payload carries (at most S <= 4; one more: the restart)
struct gdakiMiHoldSeg {
  uint64_t seg;        // segment number (s's sequence for d)
  uint64_t fill;       // bytes of the lane used: min(cursor, L) for the open one, at its close for a closed one
  uint64_t closedAt;   // d's checkpoint whose pause closed it; GDAKI_MI_OPEN for the open one
  uint32_t broken;     // breaks while it was open (the cell's broken now, or at its close, minus at its opening)
  uint32_t pad;
};
struct gdakiMiHolding {
  uint32_t version;        // GDAKI_MI_WIRE_VERSION
  uint32_t nSeg;           // entries of seg[] used (live segments, oldest first)
  uint64_t mirMsgs;        // M_mir: the msgs of s's mirror QP to b (side table), read at the hold start
  uint32_t pathOk;         // 1: s's mirror QP to b is in use (miUse 1) and its count is valid
  uint32_t cellValid;      // s's cell for d was valid at the hold start
  struct gdakiMiHoldSeg seg[GDAKI_MI_SEG_MAX];
};
static_assert(sizeof(struct gdakiMiHolding) <= 256, "HOLDING's payload fits gdakiTsMsg::executed");
// The buddy's verdict over one sender's payload for a restore from its stable checkpoint k: every live segment closed
// after k or open must have broken 0; pathOk and cellValid must be 1 when such a segment holds bytes. 0: usable.
static inline int gdakiMiHoldingVerdict(const struct gdakiMiHolding& h, uint64_t k) {
  if (h.version != GDAKI_MI_WIRE_VERSION || h.nSeg > GDAKI_MI_SEG_MAX) return 1;
  for (uint32_t i = 0; i < h.nSeg; i++) {
    const struct gdakiMiHoldSeg& g = h.seg[i];
    if (g.closedAt != GDAKI_MI_OPEN && g.closedAt <= k) continue;  // dropped by k (its STABLE not seen there yet)
    if (g.broken != 0) return 2;
    if (g.fill != 0 && (!h.pathOk || !h.cellValid)) return 3;
  }
  return 0;
}

// ---- the pool key in rkey lists ----
// The rkey lists (impl/rs_spare_api.h gdakiRsRkeysHdr/gdakiRsRkeyEntry: the spare's to a survivor, and, with the
// mirror, a survivor's to the spare inside STATE, impl/rs_log_api.h v2) carry the sender's pool as kind
// GDAKI_MI_RKEY_POOL, id 0.
#define GDAKI_MI_RKEY_POOL 4u

// ---- line keys the test branch reads (impl/PARALLEL.md: the test branch reads only these and the public API) ----
// Every line starts "GIN/MI: rank %d: " and ends " mono_ms=%.3f"; the keys below appear as key=value with no space.
//   - "lane to rank %d broken (%s): DISARM" (once per burst of breaks)
//   - "segments of rank %d restarted at its checkpoint %lu"
//   - "CKPT_PULL to rank %d": seg= fill_pct=
//   - "drain for rank %d": senders= queries= drain_us=
//   - "fetch for checkpoint %lu from buddy rank %d": image_bytes= segment_bytes= extents= fetch_us=
//   - "export to rank %d": entries= mirror_entries= mirror_bytes= source_bytes= first_step= last_step=
//   - "import step %lu": entries= pool_bytes= signals= import_us=
//   - "import done": steps= pool_bytes= left=
//   - "INJECTED sent" (the restored rank): step= survivors=
//   - "INJECTED from rank %d" (a survivor): step= state= gate_odd_ms=
//   - "mirror summary" (at the context's teardown): switches= rollbacks= restarts= third_slot= max_live_bytes=
//     pulls_sent= pulls_taken= broken= absorbed=
// ---- gin-mirror: host API (end) ----

// ---- entry points (restated declarations, not in a block; owner in brackets; helper = the helper thread only) ----
#ifndef GDAKI_MI_API_NO_ENTRY_DECLS
// [host] any thread: the mirror is on for this context (the setup agreement turned it on; never changes after the
// setup).
static bool gdakiMiOn(struct gdakiRecHost* r);
// [host] any thread: the gdakiTsScope mask of the user contexts (every bit but the mirror context's; GDAKI_TS_SCOPE_ALL
// when the mirror is off). The ckpt machine walks a peer's QPs under gdakiTsScopeGuard(gdakiMiUserScope(r)).
static uint32_t gdakiMiUserScope(struct gdakiRecHost* r);
// [dev] any thread: the QP sets. gdakiRsQpsOfPeer (9940) keeps its name and becomes "user only"; the mirror QP's index
// (or -1: mirror off, no such QP, or peer == own rank); "with mirror" = user only, then the mirror QP.
static int gdakiRsQpsOfPeer(struct gdakiRecHost* r, int peer, int* idx);
static int gdakiMiQpOfPeer(struct gdakiRecHost* r, int peer);
static int gdakiRsQpsOfPeerAll(struct gdakiRecHost* r, int peer, int* idx);
// [dev] helper: the mirror QP's cumulative responder count (as gdakiRsExecRead for one QP; *valid false when its count
// was invalidated: no refusal) and its msgs (the side table, over the NIC).
static ncclResult_t gdakiMiExecReadMirror(struct gdakiRecHost* r, int peer, uint64_t* cum, bool* valid);
static ncclResult_t gdakiMiReadMsgsMirror(struct gdakiRecHost* r, int peer, uint64_t* msgs);
// [host] helper: whether the record is the mirror context's; if so absorbed (above) and true. False with the mirror
// off.
static bool gdakiMiAbsorb(struct gdakiRecHost* r, const struct gdakiTsFault& f);
// [host] helper: the scan's absorption of a mirror QP (why: which condition). True when qpIdx is a mirror QP.
static bool gdakiMiAbsorbQp(struct gdakiRecHost* r, int qpIdx, const char* why);
// [host, segment package] helper: in d's input pause, after gdakiRsLogPauseRead and before PAUSED. *restarted: this
// switch restarted d's segments (PAUSED not armable). False: the switch failed (no NIC copy path, a read-back differs):
// PAUSED not armable, the pause itself goes on.
static bool gdakiMiSegSwitch(struct gdakiRecHost* r, int d, uint64_t ckpt, uint64_t pauseHead, bool* restarted);
// [host, segment package] helper: the pause of d's checkpoint `ckpt` ends. rollback: the pause ends without its own
// publish of a confirmed cut (gdakiCkptEndPause; call it before that function's gdakiCkptEmptyRound); false: the cut
// stays.
static void gdakiMiSegPauseEnd(struct gdakiRecHost* r, int d, uint64_t ckpt, bool rollback);
// [host, segment package] helper: CKPT_STABLE(ckpt) of d (from gdakiCkptOnStable, after the log's trim).
static void gdakiMiSegStable(struct gdakiRecHost* r, int d, uint64_t ckpt);
// [host, segment package] helper: d's segment records for the export (v2) and HOLDING: closed segments (cut, seg, fill,
// closedAt, broken), the open one, and the floor (the cut the oldest live segment opened at). False: none kept for d.
struct gdakiMiSegView {
  std::vector<uint64_t> cuts, segs, fills, closedAt, broken;
  uint64_t openSeg = 0, openCursor = 0, openBroken = 0, floor = 0;
  bool cellValid = false;
};
static bool gdakiMiSegViewOf(struct gdakiRecHost* r, int d, struct gdakiMiSegView* out);
// [host, segment package] helper: drop d's closed segments (INJECTED) / every segment of d and invalidate its cell with
// a new pool rkey (gdakiMiPoolRekey: b's restore round, b = buddy(d), before the publish; rkeyBe 0 = unknown).
static void gdakiMiSegDropClosed(struct gdakiRecHost* r, int d);
static ncclResult_t gdakiMiPoolRekey(struct gdakiRecHost* r, int d, uint32_t rkeyBe, char* why, size_t whyLen);
// [host, segment package] helper, every helper step (with gdakiRsLogPoll): breaks seen since the last call (cells'
// broken moved, self-loop errors) -> destinations to DISARM (each once), and the pulls to send.
static void gdakiMiPoll(struct gdakiRecHost* r, std::vector<int>* disarm);
// [host, segment package] the application thread in ncclGinRestoreStep: a pull arrived for this rank since the last
// checkpoint (consumed).
static bool gdakiMiPullTake(struct gdakiRecHost* r);
// [spare] helper, in gdakiHoldStart after the user set's counts (6891): read the mirror QP to d (X, M, validity) for
// the export and fill HOLDING's payload for buddy(d) (gdakiMiHolding). False: nothing to add (mirror off).
static bool gdakiMiHoldStartRead(struct gdakiRecHost* r, int d, struct gdakiMiHolding* out);
// [spare] helper, in gdakiHoldCommitRound after the user set's X check (7372-7383): the mirror QP's X again; a change
// breaks the lanes it serves (no fallback).
static void gdakiMiCommitCheck(struct gdakiRecHost* r, int d);
#endif  // GDAKI_MI_API_NO_ENTRY_DECLS

#endif  // GIN_MIRROR_RS_MIRROR_API_H_
