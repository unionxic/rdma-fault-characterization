// rs_store_api.h - gin-mirror, shared interface of the RDMA checkpoint store and the spare's RDMA FETCH (EXPERIMENT.md
// 9.4 "RDMA 체크포인트 저장소", "활성화 덩어리와 끝점 갱신", 9.6; impl/PARALLEL.md): the store slot's layout, the helper records 50
// STORE_REQ and 51 STORE_ACK, CKPT_STABLE's store payload, the activation blob v2 (the address and incarnation table,
// the store slot, the pool extents, the FETCH endpoint, READY), what the spare's FETCH hands to the import, and the
// function boundaries inside gin-restore's checkpoint machine. Only with the mirror on (gdakiMiOn): with it off the TCP
// UPLOAD and FETCH of impl/rs_ckpt_api.h stay as they are, but for 9.6's base reset (below).
//
// Base and line numbers as impl/rs_mirror_api.h (a number NNNN is a line of ../../restore/impl/rs_layer.diff, md5
// f005bb67). One block is pasted verbatim: "gin-mirror: store API" goes into
// src/transport/net_ib/gdaki/gin_host_gdaki.cc right after the end of the checkpoint's shared text (diff 4978, inside
// the region "gin-restore (rs, work package 5): checkpoint state"), so it sees struct gdakiCkptHdr. Every branch pastes
// it in its first commit; build_mi.sh `api` checks it. The block holds types, constants and pure static inline
// functions only; the entry points after it are restated declarations with their owner (impl/rs_mirror_api.h's rule).
//
// ---- the path in one paragraph (EXPERIMENT.md 9.4) ----
// After Resume (and after a restore of its buddy, and after its own restore) rank r sends STORE_REQ to b = buddy(r)
// with its slot size and its upload QP's endpoint. b registers (or reuses) a host MR of two slots for r in the GIN PD
// (zero based, no relaxed ordering), creates its side of the upload QP (a host RC QP, not a rec QP: no watch, round,
// budget or executed count), moves it to RTR toward r's endpoint, and answers STORE_ACK (rkey, slot offsets, its
// endpoint, generation). r connects its QP (RTS: timeout 12, retry_cnt 7) and is store-ready. r takes no checkpoint
// while not store-ready. In the input pause (after the drain and the fence) r's application thread copies the regions
// D2H into r's registered pinned host buffer (header, image, blob) and ends the pause (COPIED; the helper sends
// CKPT_RESUME); then, outside the pause, the same thread posts RDMA WRITEs from that buffer into b's receiving slot
// (the slot that is not stable) and polls them; ncclGinRestoreStep returns after the WRITEs completed. With every WRITE
// complete and every confirmation, r sends CKPT_STABLE with the store payload to b first, then to the rest
// (gin-restore's order); b moves its stable slot without reading the memory. A WRITE that fails or passes
// NCCL_GIN_RESTORE_STORE_WRITE_MS voids the checkpoint (after the publish: impl/rs_mirror_api.h's restart rule covers
// the segments) and an upload QP in ERR is replaced by a new STORE_REQ before the next checkpoint (meanwhile no
// checkpoint). The spare of r reads the stable slot and r's segments after K with RDMA READ (the FETCH QP, outside
// every executed-count book) before its first REJOIN.
#ifndef GIN_MIRROR_RS_STORE_API_H_
#define GIN_MIRROR_RS_STORE_API_H_

#include <stddef.h>
#include <stdint.h>
#include <vector>

// A standalone syntax check needs gin-restore's checkpoint header (in the host file the block follows it); use
// impl/rs_ckpt_api.h's shared text.
#include "rs_ckpt_api.h"
#include "rs_mirror_api.h"

// ---- gin-mirror: store API (begin; impl/rs_store_api.h, byte for byte) ----
// ---- helper-socket records 50, 51 (the store; impl/rs_mirror_api.h has the record ranges) ----
#define GDAKI_TS_STORE_REQ 50u   // r -> buddy(r): store my checkpoints (slot size, my upload QP)
#define GDAKI_TS_STORE_ACK 51u   // buddy(r) -> r: the store MR and its side of the upload QP
// Both: from, nonce as every record; arg = r (the ward); round = the request's seq; pad = 0; nqp = 0; the payload below
// memcpy'd into gdakiTsMsg::executed. The buddy's helper takes STORE_REQ (gdakiHoldTakeMsg) and hands the registration
// and the QP to its data (serve) thread, which must not block the helper; the helper sends STORE_ACK once the serve
// thread is done (the helper socket is the helper's only). r's helper takes STORE_ACK and connects its QP. An endpoint
// of a host RC QP (the store's upload QP, the FETCH QP), on the GIN context's HCA and port.
struct gdakiMiQpEndpoint {
  uint32_t qpn, psn;     // QP number, initial send PSN
  uint32_t lid;
  int32_t mtu;           // enum ibv_mtu
  uint8_t gid[16];       // RoCE/IB GID
  int32_t gidIndex;
  uint32_t pad;
};
static_assert(sizeof(struct gdakiMiQpEndpoint) == 40, "a host QP endpoint is 40 bytes");
struct gdakiStoreReq {
  uint32_t version;      // GDAKI_MI_WIRE_VERSION
  uint32_t incarnation;  // r's own incarnation (the buddy refuses a request of an older one)
  uint64_t seq;          // r's request number (from 1; = round); a later one supersedes every earlier one
  uint64_t slotBytes;    // gdakiStoreSlotBytes(imageBytes)
  uint64_t imageBytes;
  uint64_t layoutHash;   // gdakiStoreLayoutHash over r's region table
  struct gdakiMiQpEndpoint up;  // r's upload QP (state INIT)
};
struct gdakiStoreAck {
  uint32_t version;      // GDAKI_MI_WIRE_VERSION
  uint32_t ok;           // 1: stored; 0: refused (why)
  uint64_t seq;          // the request it answers (a stale answer is dropped)
  uint64_t gen;          // the buddy's store generation for r: new with every MR or QP it makes for r
  uint32_t rkey;         // the store MR's rkey (host order); the MR is zero-based (iova 0)
  uint32_t pad;
  uint64_t slotOff[2];   // the two slots' offsets in the MR
  uint64_t slotBytes;    // each slot's size (>= the request's)
  struct gdakiMiQpEndpoint up;  // the buddy's side, already RTR toward the request's endpoint
  char why[64];
};
static_assert(sizeof(struct gdakiStoreReq) <= 256 && sizeof(struct gdakiStoreAck) <= 256,
              "the store records' payloads fit gdakiTsMsg::executed");

// ---- a store slot ----
// [gdakiCkptHdr (impl/rs_ckpt_api.h, version 1, baseCkpt ~0, nChanged 0: the whole image), zero padded to
// GDAKI_STORE_HDR_BYTES] [the image: imageBytes, regions at the header's offsets] [the blob: blobBytes <=
// GDAKI_CKPT_MAX_BLOB]. The uploader fills the header in its pinned buffer (peerP from the PAUSED records, as
// gin-restore's UPLOAD header) and WRITEs header, image and blob in one or more WRITEs (each <= 1 GiB) to the receiving
// slot. No block hashes, no base: every checkpoint is the whole image (9.4). No end hash either: the spare checks the
// header against the activation's (ckpt, imageBytes, layoutHash, blobBytes).
#define GDAKI_STORE_HDR_BYTES 65536u
static_assert(sizeof(struct gdakiCkptHdr) <= GDAKI_STORE_HDR_BYTES, "the checkpoint header fits a slot's header room");
static inline uint64_t gdakiStoreRound4k(uint64_t v) { return (v + 4095u) & ~(uint64_t)4095u; }
static inline uint64_t gdakiStoreBlobOff(uint64_t imageBytes) {
  return GDAKI_STORE_HDR_BYTES + gdakiStoreRound4k(imageBytes);
}
static inline uint64_t gdakiStoreSlotBytes(uint64_t imageBytes) {
  return gdakiStoreBlobOff(imageBytes) + (uint64_t)GDAKI_CKPT_MAX_BLOB;
}
// The bytes a stable slot holds (what CKPT_STABLE says and the spare READs).
static inline uint64_t gdakiStoreUsedBytes(uint64_t imageBytes, uint32_t blobBytes) {
  return gdakiStoreBlobOff(imageBytes) + blobBytes;
}
// The layout hash: gdakiCkptHash over the region table (nRegions entries of struct gdakiCkptRegion), seeded with the
// image size. Equal hashes: the same layout (the store need not be requested again).
static inline uint64_t gdakiStoreLayoutHash(const struct gdakiCkptRegion* reg, uint32_t nRegions, uint64_t imageBytes) {
  return gdakiCkptHash(reg, (size_t)nRegions * sizeof(struct gdakiCkptRegion), GDAKI_CKPT_HASH_SEED ^ imageBytes);
}

// ---- CKPT_STABLE (gin-restore's record 15) with the store ----
// pad |= GDAKI_CKPT_STABLE_STORE and this payload memcpy'd into executed, the same record to the buddy and to the rest
// (only the buddy reads the payload). The buddy makes `slot` its stable slot when gen is its current generation for r,
// slot < 2 and usedBytes <= its slotBytes; else, as gin-restore's "no complete upload of it here" (8236-8248): not
// trimmed, DISARM r. It never reads the slot.
#define GDAKI_CKPT_STABLE_STORE 0x2u
struct gdakiStoreStable {
  uint32_t version;      // GDAKI_MI_WIRE_VERSION
  uint32_t slot;         // 0 or 1: the slot the WRITEs filled
  uint64_t gen;          // the STORE_ACK generation the WRITEs used
  uint64_t usedBytes;    // gdakiStoreUsedBytes(imageBytes, blobBytes)
  uint64_t imageBytes;
  uint64_t layoutHash;
  uint32_t blobBytes;
  uint32_t pad;
};
static_assert(sizeof(struct gdakiStoreStable) <= 256, "CKPT_STABLE's store payload fits gdakiTsMsg::executed");
// The buddy's verdict over a CKPT_STABLE payload: 0 = take it as the stable slot.
static inline int gdakiStoreStableVerdict(const struct gdakiStoreStable& s, uint64_t curGen, uint64_t slotBytes) {
  if (s.version != GDAKI_MI_WIRE_VERSION) return 1;
  if (s.gen != curGen) return 2;
  if (s.slot > 1u) return 3;
  if (s.usedBytes != gdakiStoreUsedBytes(s.imageBytes, s.blobBytes) || s.usedBytes > slotBytes) return 4;
  if (s.blobBytes > GDAKI_CKPT_MAX_BLOB) return 5;
  return 0;
}

// ---- the activation v2 (buddy -> the spare's activation port; impl/rs_spare_api.h's gdakiRsActivate) ----
// With the mirror the buddy sends gdakiRsActivate with version GDAKI_RS_ACT_VERSION_MI and, on the same connection
// right after it, the blob: gdakiMiActHdr, nAddr x gdakiMiActAddr (one per rank, index = rank; the restored rank's own
// entry all zero), nExt x gdakiMiActExt. The spare reads record and blob within 500 ms (the record's bound) and answers
// the record as gin-restore does (ACCEPTED, LATER, REFUSED; REFUSED is final, also for a blob that is missing,
// malformed, or larger than its FETCH buffer). Only after ACCEPTED, on the same connection:
//   spare -> buddy  gdakiMiActAnswer: the spare's FETCH QP endpoint (its QP in INIT, created now); the buddy reads it
//                   within 1000 ms
//   buddy           connects its FETCH QP (RTR, RTS) to that endpoint
//   buddy -> spare  gdakiMiActReady (READY, or FAIL with why); the spare reads it within 3000 ms (the handshake bound)
//   spare           connects its QP, READs the slot and every extent into its FETCH buffer, in that order, then
//   spare -> buddy  gdakiMiActDone, and closes. The buddy's data (serve) thread holds the connection after READY and
//                   destroys its FETCH QP at DONE, at a FIN, or at the end of the hold.
// The buddy creates its FETCH QP once per hold (a LATER answer makes it send record and blob again every 20 ms, with
// the same endpoint). With the mirror off nothing changes (version 1, no blob, TCP FETCH).
#define GDAKI_RS_ACT_VERSION_MI 2u
#define GDAKI_MI_ACTB_MAGIC 0x42415247u  // "GRAB"
#define GDAKI_MI_ACT_MAX_EXT 256u        // extents at most (senders x live segments: n - 1 x S <= 63 x 4)
#define GDAKI_MI_ACTB_F_STORE 0x1u       // the store part is valid (always with the mirror)
#define GDAKI_MI_ACTB_F_POOL 0x2u        // the pool part is valid (else every MIRROR entry is refused later)
struct gdakiMiActHdr {
  uint32_t magic, version;   // GDAKI_MI_ACTB_MAGIC, GDAKI_MI_WIRE_VERSION
  int32_t rank;              // the restored rank (= the record's)
  uint32_t incarnation;      // its new incarnation (= the record's)
  uint64_t nonce;            // = the record's
  uint64_t ckpt;             // K: the stable checkpoint (= the record's step)
  uint32_t nranks, nAddr;    // nAddr = nranks
  uint32_t nExt, flags;      // GDAKI_MI_ACTB_F_*
  uint32_t storeRkey;        // the store MR's rkey (host order, zero based)
  uint32_t storeSlot;        // the stable slot (0, 1)
  uint64_t storeOff;         // the slot's offset in the store MR
  uint64_t usedBytes;        // bytes to READ from storeOff (header, image, blob)
  uint64_t imageBytes, layoutHash;
  uint32_t blobBytes;
  uint32_t poolRkey;         // the buddy's pool rkey (host order, zero based)
  uint64_t laneBytes;        // L
  uint32_t slots;            // S
  int32_t wardIdx;           // the restored rank's index among the buddy's wards (ncclGinMiWardIdx)
  struct gdakiMiQpEndpoint fetch;  // the buddy's FETCH QP (INIT)
};
struct gdakiMiActAddr {
  int32_t rank;              // = the index (the restored rank's entry: -1)
  uint32_t incarnation;      // its current incarnation as the buddy knows it (gdakiRsPeerInc; its own for itself)
  uint8_t listenAddr[32];    // union ncclSocketAddress of its helper listen socket now (the buddy's pe.addr; its own)
};
struct gdakiMiActExt {       // one live segment after K of one sender's lane for the restored rank
  uint64_t seg;              // the sender's segment number
  int32_t sender;            // the sender's rank (the buddy for its own lane)
  uint32_t lane;             // ncclGinMiLaneOf(sender, rank)
  uint64_t poolOff;          // ncclGinMiLaneOff(wardIdx, seg mod S, lane, nranks, S, L)
  uint64_t fill;             // bytes to READ from poolOff (<= L)
  uint64_t closedAt;         // the checkpoint whose pause closed it (> K), or GDAKI_MI_OPEN
};
struct gdakiMiActAnswer {
  uint32_t magic, ok;        // GDAKI_MI_ACTB_MAGIC; 1: fetch is valid
  struct gdakiMiQpEndpoint fetch;  // the spare's FETCH QP (INIT)
  char why[64];
};
enum : uint32_t { GDAKI_MI_ACT_READY = 1, GDAKI_MI_ACT_FAIL = 2 };
struct gdakiMiActReady {
  uint32_t magic, kind;      // GDAKI_MI_ACTB_MAGIC, GDAKI_MI_ACT_READY or GDAKI_MI_ACT_FAIL
  char why[64];
};
struct gdakiMiActDone {
  uint32_t magic, ok;        // GDAKI_MI_ACTB_MAGIC; 1: every READ completed
  uint64_t bytes;            // bytes read
  char why[64];
};
static_assert(sizeof(struct gdakiMiActAddr) == 40 && sizeof(struct gdakiMiActExt) == 40, "activation blob entries");
// The spare's check of the blob before its answer (0: usable; else a REFUSED reason code). fetchCap: its FETCH buffer.
static inline int gdakiMiActCheck(const struct gdakiMiActHdr& h, const struct gdakiMiActExt* ext, uint32_t nExt,
                                  int rank, uint32_t incarnation, uint64_t nonce, uint64_t step, uint64_t fetchCap) {
  if (h.magic != GDAKI_MI_ACTB_MAGIC || h.version != GDAKI_MI_WIRE_VERSION) return 1;
  if (h.rank != rank || h.incarnation != incarnation || h.nonce != nonce || h.ckpt != step) return 2;
  if (h.nAddr != h.nranks || h.nExt != nExt || nExt > GDAKI_MI_ACT_MAX_EXT) return 3;
  if (!(h.flags & GDAKI_MI_ACTB_F_STORE)) return 3;
  if (h.usedBytes != gdakiStoreUsedBytes(h.imageBytes, h.blobBytes) || h.blobBytes > GDAKI_CKPT_MAX_BLOB) return 4;
  uint64_t total = gdakiStoreRound4k(h.usedBytes);
  for (uint32_t i = 0; i < nExt; i++) {
    if (ext[i].fill > h.laneBytes || ext[i].sender < 0 || ext[i].sender == rank) return 5;
    if (ext[i].closedAt != GDAKI_MI_OPEN && ext[i].closedAt <= h.ckpt) return 6;
    total += (ext[i].fill + 63u) & ~(uint64_t)63u;
  }
  return total <= fetchCap ? 0 : 7;
}

// ---- what the spare's FETCH hands to its import (impl/rs_log_api.h v2) ----
// The FETCH buffer (pinned host memory registered in the GIN PD at the init replay, NCCL_GIN_RESTORE_MIRROR_FETCH_MB):
// the slot at offset 0 (usedBytes), then every extent at a 64-byte aligned offset, in the blob's order. The spare's
// FETCH also writes the image into the windows and fills gin-restore's gdakiCkptSpareData (hdr[0], blob) from the slot,
// as the TCP FETCH does, so Resume's code after the driver is unchanged but for the import call.
struct gdakiMiFetched {
  uint64_t ckpt = 0;                  // K
  const uint8_t* buf = nullptr;       // the FETCH buffer
  uint64_t usedBytes = 0;             // the slot's bytes at buf
  std::vector<struct gdakiMiActExt> ext;
  std::vector<uint64_t> bufOff;       // ext[i]'s bytes at buf + bufOff[i]
};
// The bytes of sender s's segment `seg` at lane offset [off, off + bytes) in the FETCH buffer, or nullptr when no
// fetched extent holds them (the import refuses then: 9.4 "(segment, lane, 자리 + 바이트)가 FETCH한 채움 안").
static inline const uint8_t* gdakiMiFetchedAt(const struct gdakiMiFetched& f, int sender, uint64_t seg, uint64_t off,
                                              uint64_t bytes) {
  for (size_t i = 0; i < f.ext.size() && i < f.bufOff.size(); i++) {
    const struct gdakiMiActExt& e = f.ext[i];
    if (e.sender != sender || e.seg != seg) continue;
    if (off > e.fill || bytes > e.fill - off) return nullptr;
    return f.buf + f.bufOff[i] + off;
  }
  return nullptr;
}

// ---- parameters (the store branch defines the NCCL_PARAMs) ----
// NCCL_GIN_RESTORE_STORE_WRITE_MS  the WRITEs of one checkpoint at most, default 500 (then void, the QP replaced) The
// upload QP's attributes are fixed: timeout 12 (about 17 ms), retry_cnt 7, rnr_retry 7, max_rd_atomic 1; the FETCH QP
// the same with max_rd_atomic 16 (READs in flight).

// ---- line keys (impl/rs_mirror_api.h's format) ----
//   - "checkpoint %lu stored at buddy rank %d": slot= bytes= d2h_us= write_us=
//   - "store request to buddy rank %d": seq= slot_bytes=  /  "store ready at buddy rank %d": gen=
//   - "store summary" (teardown): writes= failed= requests= tcp_image_bytes= tcp_segment_bytes=
// ---- gin-mirror: store API (end) ----

// ---- function boundaries in gin-restore's checkpoint machine (who edits which lines; impl/PARALLEL.md) ----
// - gdakiCkptInitStep 8410-8574 (the checkpointing rank's helper):
//   - IDLE 8427-8467: store adds one refusal to the chain 8440-8446, "the checkpoint store is not ready"
//     (!gdakiStoreReady(r) with the mirror on). Nobody else.
//   - PAUSING 8468-8492: nobody.
//   - COPYING 8493-8523: store; 8514 becomes `if (valid) gdakiStoreOn(r) ? gdakiStoreArm(r, ck->ckpt) :
//     gdakiCkptStartUpload(r);` (the WRITE itself is the application thread's, in gdakiCkptTake).
//   - CONFIRMING 8524-8569: store; done and ok (8525-8531) come from gdakiStoreWriteState on the store path, the
//     CKPT_STABLE records (8545-8550, 8557-8562) get gdakiStoreFillStable(r, &m) after their pad, the base (8551-8556)
//     is TCP only. The armable verdict (8543) does not change.
// - The segment package (host) edits nothing in gdakiCkptInitStep. Its rank-r side is CKPT_PULL (gdakiMiPullTake ORed
//   into `due` at 9383, ncclGinGdakiRestoreStep). Its sender side: gdakiCkptOnPause, gdakiMiSegSwitch after the counts
//   (after 8154) and the armable 8157-8158 through gdakiMiPausedArmable; gdakiCkptEndPause 8070-8093,
//   gdakiMiSegPauseEnd with rollback right before its gdakiCkptEmptyRound (the INTACT path) and without it on its ENDED
//   path (a round or a decline ended the pause: its gates were published or failed); gdakiCkptOnResume 8175-8231,
//   gdakiMiSegPauseEnd without rollback in the HELD case (after the empty round) and in the VOIDED case;
//   gdakiCkptOnStable, gdakiMiSegStable at 8249 (after the buddy's branch, before the cut lookup: the buddy holds k,
//   whatever this rank's cut); and the user-only walks of impl/rs_mirror_api.h. gdakiCkptPeerStep's bound ends a pause
//   through gdakiCkptEndPause (covered); gdakiCkptOnHoldStart 8590-8597 keeps the switch (the hold reads the device).
// - gdakiCkptOnPause 8109-8174: the BUSY verdict stays in ONE place. gdakiCkptBusyReason's inputs (8118-8122) do not
//   change; its "suppressLeft" is gdakiCkptSuppressLeft (8096-8107), which the dev branch widens to
//   `|| gdakiMiImportLeft(r)` (inputs still to inject answer BUSY_SUPPRESS, as gin-restore's suppress BUSY; the same
//   function also stops r's own checkpoints at 8443). No new BUSY reason (the draft's "segment full" BUSY is gone: the
//   restart rule).
// - gdakiCkptOnStable 8232-8285: store edits the buddy's branch 8236-8248 (the store path: gdakiStoreOnStable with the
//   payload instead of markStable); segment adds one call at 8249 (above).
// - gdakiCkptTake 9259-9361 (application thread): store owns the store path (D2H into its registered pinned buffer
//   instead of devCopy, the header and the blob into that buffer, COPIED, then the WRITEs after the helper's
//   CKPT_RESUME, bounded, and the write state); the TCP path stays.
// - The TCP path's base reset of 9.6 (mirror off): store, in gdakiCkptUploadOne 8671-8751 (an upload that did not end
//   with an OK ack clears the base) and at RESTORED of this rank's buddy (gdakiStoreOnBuddyRestored, called from
//   gdakiHoldApplyRestored 7039-7083 after gdakiCkptPeerReset).

// ---- entry points (restated declarations; owner in brackets) ----
#ifndef GDAKI_MI_API_NO_ENTRY_DECLS
struct gdakiRecHost;
struct gdakiTsMsg;
struct gdakiRsActivate;  // impl/rs_spare_api.h
// [store] any thread: the store path is on (gdakiMiOn) / this rank is store-ready (STORE_ACK taken, upload QP RTS, no
// error since).
static bool gdakiStoreOn(struct gdakiRecHost* r);
static bool gdakiStoreReady(struct gdakiRecHost* r);
// [store] helper: COPYING of checkpoint ckpt ended valid: the application thread may WRITE now (gdakiCkptTake waits
// for it); and the write state for CONFIRMING (done: the WRITEs ended; ok: all completed).
static void gdakiStoreArm(struct gdakiRecHost* r, uint64_t ckpt);
static void gdakiStoreWriteState(struct gdakiRecHost* r, uint64_t ckpt, bool* done, bool* ok);
// [store] helper: the store payload and flag into a CKPT_STABLE record of the current checkpoint.
static void gdakiStoreFillStable(struct gdakiRecHost* r, struct gdakiTsMsg* m);
// [store] helper, the buddy: CKPT_STABLE from ward `from` on the store path; false: no image here (the caller DISARMs).
static bool gdakiStoreOnStable(struct gdakiRecHost* r, int from, const struct gdakiTsMsg& m);
// [store] helper, the buddy: what the activation blob of ward d needs from the store (false: no stable slot).
struct gdakiStoreActInfo {
  uint32_t rkey = 0, slot = 0, blobBytes = 0;
  uint64_t off = 0, usedBytes = 0, imageBytes = 0, layoutHash = 0, ckpt = 0;
};
static bool gdakiStoreActInfoOf(struct gdakiRecHost* r, int d, struct gdakiStoreActInfo* out);
// [store] helper: every helper step (STORE_REQ, STORE_ACK, a request after the buddy's incarnation changed or the QP
// failed). And at RESTORED of the buddy (both paths; TCP: the base reset of 9.6).
static void gdakiStoreStep(struct gdakiRecHost* r);
static void gdakiStoreOnBuddyRestored(struct gdakiRecHost* r, int buddy);
// [store] a host RC QP of the GIN PD on the GIN context's HCA with its own CQ (the upload QP; the spare branch's FETCH
// QPs use the same functions). Create: state INIT, *local filled. Connect: RTR then RTS (attributes above). Post and
// poll: one thread at a time.
struct gdakiMiHostQp;
static ncclResult_t gdakiMiHostQpCreate(struct gdakiRecHost* r, int maxRdAtomic, struct gdakiMiHostQp** out,
                                        struct gdakiMiQpEndpoint* local, char* why, size_t whyLen);
static ncclResult_t gdakiMiHostQpConnect(struct gdakiMiHostQp* q, const struct gdakiMiQpEndpoint& remote, char* why,
                                         size_t whyLen);
static ncclResult_t gdakiMiHostQpXfer(struct gdakiMiHostQp* q, bool read, void* local, uint32_t lkey, uint64_t remote,
                                      uint32_t rkey, uint64_t bytes, int timeoutMs, char* why, size_t whyLen);
static void gdakiMiHostQpDestroy(struct gdakiMiHostQp* q);
// [spare] the buddy's helper: the activation v2 (record, blob; the answer; after ACCEPTED the FETCH endpoint, the
// connect, READY, then the connection handed to the data thread). Returns the answer kind, or -1.
struct gdakiMiActBlob {
  struct gdakiMiActHdr hdr;
  std::vector<struct gdakiMiActAddr> addr;
  std::vector<struct gdakiMiActExt> ext;
};
static int gdakiMiSendActivate(struct gdakiRecHost* r, int peer, const void* spareAddr, const struct gdakiRsActivate* a,
                               const struct gdakiMiActBlob& blob, int timeoutMs);
// [spare] the spare's driver: after ACCEPTED and READY, the READs into the FETCH buffer, the image into the windows,
// gdakiCkptSpareData's header and blob; before its first REJOIN.
static ncclResult_t gdakiMiSpareFetch(struct gdakiRecHost* r, int fd, const struct gdakiMiActBlob& blob,
                                      struct gdakiMiFetched* out, char* why, size_t whyLen);
#endif  // GDAKI_MI_API_NO_ENTRY_DECLS

#endif  // GIN_MIRROR_RS_STORE_API_H_
