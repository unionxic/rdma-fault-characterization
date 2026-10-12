// rs_ckpt_api.h - gin-restore, work package 5 (host branch; EXPERIMENT.md 9.4, 9.11.9 C1): the checkpoint's records on
// the helper socket and the data socket's wire formats, for the other branches (the spare process fetches its image from
// the buddy and receives the survivors' state over the data socket; impl/rs_spare_api.h, impl/rs_log_api.h).
//
// Binding interface between branches (impl/PARALLEL.md). The part between the two "shared text" fences is also in
// src/transport/net_ib/gdaki/gin_host_gdaki.cc, verbatim, at the start of the region
//   "// ==== gin-restore (rs, work package 5): checkpoint state (begin) ===="
// The CPU unit test (impl/rs_unit_host.cc) includes this file. A difference between the two is a bug of the host branch.
//
// ---- the checkpoint of rank r (9.4), in one paragraph ----
// The application calls ncclGinRestoreStep(comm, step, blob, bytes, &stableStep) after the kernels of `step` and their
// last flush. Every NCCL_GIN_RESTORE_CKPT_STEPS steps r takes checkpoint `step` (a checkpoint is named by that step):
// r's helper sends CKPT_PAUSE to every peer q; q quiesces its QPs to r without moving them to ERR (gate odd, count 0, held
// WQEs rung), reads its log's head and messages sent to r (M) and its executed count of r's messages (P) and answers
// PAUSED (or BUSY: then r skips this checkpoint). r waits until its executed count of each q's messages reaches M (QUERY_QP,
// outside the firmware guard), reads the side table's fence word over the NIC loopback (strict MR), copies its windows,
// its ncclGinRestoreRegister buffers and its signal and counter tables into a GPU copy (the application's thread, CUDA),
// reads the executed counts again (unchanged, or the checkpoint is void), and sends CKPT_RESUME. q publishes an empty
// round (its gate epoch + 2, the covered epoch unchanged) when its pause held until then (no round, no decline, no early
// end of the pause) and confirms with PAUSED (GDAKI_CKPT_PAUSED_HELD), else BUSY (VOIDED): 9.11.9 C1, a round during the
// pause wins and the checkpoint is discarded. When r gives a checkpoint up it sends CKPT_RESUME with pad 1 to every peer
// it sent CKPT_PAUSE that did not answer BUSY, and answers a PAUSED it no longer waits for with the same. r's data thread
// meanwhile uploads the changed 64 KiB blocks of the copy to its buddy's host memory over the data socket. With the
// buddy's acknowledgement and every confirmation, r sends CKPT_STABLE to its buddy first (if that send fails, the
// checkpoint is void) and then to every other peer: the buddy marks the image stable (the one a restore uses),
// each peer trims its log toward r to that cut and arms r. A peer that saw the CKPT_STABLE implies the buddy has it before
// any later FIN of r on that socket. Restore: the buddy activates r's spare with its newest stable image; the spare fetches
// it over the data socket, and each survivor sends it the log from its cut for that checkpoint (a survivor keeps the cut of
// every checkpoint it confirmed since its last stable one, so it can serve a checkpoint whose CKPT_STABLE it did not get).
//
// ---- the data socket ----
// A data connection goes to the target's helper listen socket (the same address as HELLO, PROBE and REJOIN: the setup's
// all-gather, or a spare's listen address after its REJOIN). Its first record is a gdakiTsMsg of type GDAKI_TS_DATA
// (magic, from = the sender's rank, nonce = the GIN context's nonce, arg = the subject rank, round and pad as below); the
// receiver's helper checks it and hands the socket to its data thread. Then the purpose's stream:
//   UPLOAD  r -> buddy(r): round = the checkpoint (its step); stream: gdakiCkptHdr, then nChanged x (u64 block index, the
//           block's bytes), then the blob (blobBytes), then a gdakiCkptEnd; the buddy answers one gdakiCkptAck.
//   FETCH   spare of r -> buddy(r): round = the checkpoint the activation named (gdakiRsActivate::step); the buddy answers
//           gdakiCkptHdr (nChanged = every block), every block in index order (u64 index, bytes), the blob, gdakiCkptEnd
//           (imageHash over the whole image); or a gdakiCkptAck with ok = 0 when it does not hold that checkpoint as its
//           stable image. Both start with GDAKI_CKPT_MAGIC; the second u32 (the header's version 1, the ack's ok 0) tells
//           them apart. The spare runs it once, in its first dataFd call (gdakiCkptSpareDataFd, before it takes the first
//           survivor's STATE): the image is in its memory before any survivor publishes toward it.
//   STATE   survivor q -> the spare of r (its listen address after the REJOIN): round = r's new incarnation; the spare
//           answers one gdakiTsMsg of type GDAKI_TS_DATA with round = the checkpoint it restores from (pad 0: go on,
//           pad != 0: refuse); q sends a u64 byte count n (at most GDAKI_CKPT_STATE_MAX), then n bytes: its log export
//           from its cut for that checkpoint (impl/rs_log_api.h: gdakiRsLogXHdr .. gdakiRsLogXEnd, with X and M at the
//           hold start; the count lets the spare keep it without parsing it); the spare answers its rkey list
//           (impl/rs_spare_api.h: gdakiRsRkeysHdr and its entries). Then q closes; the spare keeps the socket until its
//           driver ends (gdakiCkptSpareDataDone). On the spare this is the dataFd of gdakiRsSpareRun
//           (gdakiCkptSpareDataFd: it takes the connection on the spare's listen socket after that survivor's REJOIN_ACK,
//           before the spare sends its rkey list). q does not block its helper on the answer (the spare may first FETCH
//           from q, its buddy): it reads the answer in later helper steps, bounded by its hold's deadline.
// Integers are little-endian host order; every read and write is bounded (NCCL_GIN_TS_HANDSHAKE_MS per record, the hold's
// deadline for a STATE).
#ifndef GIN_RESTORE_RS_CKPT_API_H_
#define GIN_RESTORE_RS_CKPT_API_H_
// ---- shared text (begin) ----
#include <stddef.h>
#include <stdint.h>

// helper-socket record types of the host branch (rs_hold_api.h has 11..19): the data socket's first record
#define GDAKI_TS_DATA 20u
enum : uint32_t { GDAKI_CKPT_UPLOAD = 1, GDAKI_CKPT_FETCH = 2, GDAKI_CKPT_STATE = 3 };  // GDAKI_TS_DATA's pad

// The checkpoint records' fields (helper socket; from, nonce as every record):
//   CKPT_PAUSE   r -> q: arg = r, round = the checkpoint
//   PAUSED       q -> r: arg = r, round = the checkpoint, pad = GDAKI_CKPT_PAUSED_*, nqp = q's QPs to r (GIN-context
//                order); per QP i: tok.epochWqes[i] = M (request messages q posted to r), executed[i] and nrp[i] = the low
//                and high 32 bits of P (q's cumulative executed count of r's messages)
//   BUSY         q -> r: arg = r, round = the checkpoint, pad = GDAKI_CKPT_BUSY_* (r skips this checkpoint)
//   CKPT_RESUME  r -> q: arg = r, round = the checkpoint, pad = 1 when r gave the checkpoint up (q unpauses either way and
//                does not confirm)
//   PAUSED again q -> r, the confirmation after CKPT_RESUME: pad = GDAKI_CKPT_PAUSED_HELD, nqp = 0; or BUSY (VOIDED)
//   CKPT_STABLE  r -> every rank: arg = r, round = the checkpoint, pad = GDAKI_CKPT_STABLE_ARMABLE when every PAUSED was
//                armable and the buddy holds r's spare registration
#define GDAKI_CKPT_PAUSED_ARMABLE 0x1u   // q can take part in restoring r (its arming conditions, its log toward r complete)
#define GDAKI_CKPT_PAUSED_FIRST 0x2u     // this pause started q's log toward r
#define GDAKI_CKPT_PAUSED_HELD 0x4u      // the confirmation: q's pause held until CKPT_RESUME; its empty round is published
enum : uint32_t {
  GDAKI_CKPT_BUSY_HOLD = 1,      // q holds a peer (a restore runs)
  GDAKI_CKPT_BUSY_SUPPRESS = 2,  // q is a restored rank still holding back replayed messages (P4)
  GDAKI_CKPT_BUSY_DECLINED = 3,  // q declined r, or a fault already reached the application on q
  GDAKI_CKPT_BUSY_PAUSE = 4,     // q's pause failed (quiesce, the log's or the executed count's read)
  GDAKI_CKPT_BUSY_OFF = 5,       // q has no hold state (it does not ask for the restore)
  GDAKI_CKPT_BUSY_VOIDED = 6,    // q's pause did not hold until CKPT_RESUME (a round or a decline with r, or its bound
                                 // NCCL_GIN_RESTORE_PAUSE_MS ended it): the checkpoint is discarded
  GDAKI_CKPT_BUSY_ROUND = 7,     // q has a round with r pending (gates odd from an earlier quiesce, or a queued fault)
};
#define GDAKI_CKPT_STABLE_ARMABLE 0x1u

// The data socket's image stream (UPLOAD, FETCH). The image is the concatenation of the regions in this order, each
// starting at a 256-byte boundary of the image; blocks are GDAKI_CKPT_BLOCK bytes of the image (the last one shorter).
#define GDAKI_CKPT_MAGIC 0x43535247u  // "GRSC"
#define GDAKI_CKPT_VERSION 1u
#define GDAKI_CKPT_BLOCK (64u * 1024u)
#define GDAKI_CKPT_MAX_REGIONS 64
#define GDAKI_CKPT_MAX_PEERS 64
#define GDAKI_CKPT_MAX_BLOB (1u << 20)
#define GDAKI_CKPT_QPS 64             // NCCL_GIN_RECOVERY_MAX_QPS
enum : uint32_t {
  GDAKI_CKPT_REGION_WINDOW = 1,     // a window registered on the context's collComm: id = its number (rsWinId)
  GDAKI_CKPT_REGION_REGISTERED = 2, // an ncclGinRestoreRegister buffer: id = its registration order on the communicator
  GDAKI_CKPT_REGION_SIGNALS = 3,    // the context's signal table (this rank's part): id 0
  GDAKI_CKPT_REGION_COUNTERS = 4,   // the context's counter table: id 0
};
struct gdakiCkptRegion {
  uint32_t kind, id;
  uint64_t offset;  // in the image (256-byte aligned)
  uint64_t bytes;
};
struct gdakiCkptPeerP {  // what PAUSED told r: per QP of q to r, P (q's executed count of r's messages at the cut)
  int32_t rank;
  uint32_t nqp;
  uint64_t p[GDAKI_CKPT_QPS];
};
struct gdakiCkptHdr {
  uint32_t magic, version;          // GDAKI_CKPT_MAGIC, GDAKI_CKPT_VERSION
  int32_t rank;                     // r
  uint32_t incarnation;             // r's incarnation
  uint64_t nonce;                   // the GIN context's nonce
  uint64_t ckpt;                    // the checkpoint (= the step it was taken at)
  uint64_t baseCkpt;                // UPLOAD: the stable checkpoint the changed blocks apply to (~0: none, every block)
  uint64_t imageBytes;
  uint32_t blockBytes;              // GDAKI_CKPT_BLOCK
  uint32_t nRegions;
  uint64_t nChanged;                // blocks that follow
  uint32_t blobBytes;               // the application's blob (after the blocks, before the end record)
  uint32_t nPeers;                  // entries of peerP used
  uint8_t spareAddr[32];            // r's spare (NCCL_GIN_RESTORE_SPARE_ADDR), a union ncclSocketAddress (zero: none)
  int64_t pid;                      // r's process (the spare's PID check)
  uint64_t pidStart;                // its start time, /proc/<pid>/stat field 22
  struct gdakiCkptRegion region[GDAKI_CKPT_MAX_REGIONS];
  struct gdakiCkptPeerP peerP[GDAKI_CKPT_MAX_PEERS];
};
struct gdakiCkptEnd {
  uint32_t magic, ok;               // GDAKI_CKPT_MAGIC; 1
  uint64_t imageHash;               // FETCH: a hash of the whole image (gdakiCkptHash over imageBytes)
};
struct gdakiCkptAck {
  uint32_t magic, ok;               // GDAKI_CKPT_MAGIC; 1: stored (UPLOAD) / 0: refused (FETCH: no such checkpoint)
  uint64_t ckpt;
  char why[112];
};
// The block hash (64 bits, FNV-1a over 8-byte words, then a finalizer); the uploader sends the blocks whose hash
// differs from the last stable image's, and the FETCH end record carries the hash of the whole image.
static inline uint64_t gdakiCkptHash(const void* p, size_t n, uint64_t h) {
  const unsigned char* b = (const unsigned char*)p;
  size_t i = 0;
  for (; i + 8 <= n; i += 8) {
    uint64_t w = 0;
    for (int k = 0; k < 8; k++) w |= (uint64_t)b[i + k] << (8 * k);
    h = (h ^ w) * 0x100000001b3ULL;
  }
  for (; i < n; i++) h = (h ^ b[i]) * 0x100000001b3ULL;
  h ^= h >> 33;
  h *= 0xff51afd7ed558ccdULL;
  h ^= h >> 33;
  return h;
}
#define GDAKI_CKPT_HASH_SEED 0xcbf29ce484222325ULL
#define GDAKI_CKPT_STATE_MAX (1ULL << 30)  // a STATE's export, bytes at most
// ---- shared text (end) ----
#endif
