// mi_unit_store.cc - CPU unit test of gin-mirror's store branch (impl/PARALLEL.md row exp/gin-mirror-store; EXPERIMENT.md
// 9.4 "RDMA 체크포인트 저장소", 9.6, 9.7). No NCCL, no CUDA, no network.
// Built by impl/build_mi.sh unit (BR=store): impl/rs_store_api.h and impl/rs_mirror_api.h (their blocks, without the entry
// points), impl/rs_hold_api.h and impl/rs_ckpt_api.h, gin-restore's region "gin-restore ckpt: pure functions"
// (rs_ckpt_pure.inc: the TCP path's buddy store, v1) and this branch's region "gin-mirror (store): pure"
// (mi_pure_store.inc), cut from the working tree's gin_host_gdaki.cc; g++ -std=c++17, ASan and UBSan.
// What it checks:
//   1. the slots' arithmetic: slot size, blob offset, used bytes, the MR's two slots, the receiving slot, the pieces of a
//      transfer, the layout key, the training shape's sizes (9.4: about 2 x 31 MiB per ward), the buddy's bound on a
//      ward's MR (NCCL_GIN_RESTORE_STORE_MAX_MB, outside the interface);
//   2. CKPT_STABLE's store payload: its encoding through gdakiTsMsg::executed, impl/rs_store_api.h's verdict (every
//      reason), the pad flags (the armable bit unchanged next to the store bit), the buddy's record of it;
//   3. STORE_REQ and STORE_ACK: their checks (every reason), the spare registration after the request (outside the
//      interface), the payloads' fit, the requests of a declined or held ward that are not served;
//   4. the uploader's request machine: every reason for a request and their order, the ready rule (the IDLE refusal),
//      the WRITE's begin and end, the stable slot's view, the buddy's restore, the back-offs;
//   5. the buddy's record of a ward: the MR's reuse and replacement (current -> old while it holds the stable slot), the
//      generation, a new incarnation, the release of the old MR, the activation's rkey and offset;
//   6. a model of both sides with injected failures (lost and stale answers, refused requests, failed connects, WRITE
//      errors and bounds, the buddy's death and restore, the ward's restore, layout changes, a CKPT_STABLE that cannot be
//      sent, a CKPT_STABLE buffered on a helper socket that is then lost and reinstalled), many seeds: whenever the ward
//      is armed, the buddy's stable slot holds that checkpoint completely, in a live MR; the record's invariants; and the
//      store gets ready again after the failures stop. The same model without the socket rule (no request after a
//      reinstall, no stable view from the answer) must break the invariant, else the test proves nothing about the rule.
//      The model's buddy holds the ward's hold cell (gdakiHoldPack) and drops STORE_REQs as gdakiStoreDropNow does: a
//      ward's death is HELD of the dead incarnation i, its restore PUBLISHED(i) until INJECTED while the accepted REJOIN
//      already made i + 1 the known incarnation (mirror on); the dead process's requests (any seq, also late ones read
//      during PUBLISHED) are dropped, the restored process's are served there. A fixed sequence checks the caller's case
//      of pilot 1's defect A: STORE_REQ(i + 1, seq 1) during PUBLISHED(i) is served and the store gets ready before
//      INJECTED, STORE_REQ(i, any seq) is dropped; the pre-fix caller (the known incarnation as the hold's) must drop the
//      restored process's request there, else the sequence proves nothing about the caller;
//   7. the TCP path's base (mirror off, 9.6) as a model on gin-restore's own buddy store (gdakiCkptStore v1): with v1's
//      rule an upload that ended without an ack, or a restored buddy, keeps a base the buddy no longer holds and the
//      checkpoints are refused in a row; with this branch's rule never, and the next upload after any failure is whole;
//   8. mirror off: gin-restore's buddy store (v1) behaves as before (begin, blocks, finish, markStable).
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <deque>
#include <random>
#include <string>
#include <vector>
#define GDAKI_HOLD_API_NO_ENTRY_DECLS
#define GDAKI_MI_API_NO_ENTRY_DECLS
#include "rs_hold_api.h"
#include "rs_ckpt_api.h"
#include "rs_mirror_api.h"
#include "rs_store_api.h"
#include "rs_ckpt_pure.inc"
#include "mi_pure_store.inc"

static long gChecks = 0, gFailed = 0;
#define CHECK(c)                                                                     \
  do {                                                                               \
    gChecks++;                                                                       \
    if (!(c)) {                                                                      \
      gFailed++;                                                                     \
      if (gFailed <= 40) fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); \
    }                                                                                \
  } while (0)

static const uint64_t MiB = 1ull << 20;

// ---- 1. slots ----
static void testSlots() {
  CHECK(sizeof(struct gdakiCkptHdr) <= GDAKI_STORE_HDR_BYTES);
  const uint64_t imgs[] = {1, 255, 4095, 4096, 4097, 65536, 30 * MiB, 30 * MiB + 1, 123456789ull, 1ull << 33};
  for (uint64_t img : imgs) {
    const uint64_t sb = gdakiStoreSlotBytes(img);
    CHECK(sb % 4096 == 0);
    CHECK(gdakiStoreBlobOff(img) >= GDAKI_STORE_HDR_BYTES + img);
    CHECK(gdakiStoreBlobOff(img) - (GDAKI_STORE_HDR_BYTES + img) < 4096);
    CHECK(gdakiStoreUsedBytes(img, 0) == gdakiStoreBlobOff(img));
    CHECK(gdakiStoreUsedBytes(img, GDAKI_CKPT_MAX_BLOB) == sb);
    CHECK(gdakiStoreUsedBytes(img, 1234) <= sb);
    CHECK(gdakiStoreMrBytes(sb) == 2 * sb);
    CHECK(gdakiStoreSlotOff(sb, 0) == 0 && gdakiStoreSlotOff(sb, 1) == sb);
    const uint64_t off[2] = {gdakiStoreSlotOff(sb, 0), gdakiStoreSlotOff(sb, 1)};
    CHECK(gdakiStoreSlotsSane(off, sb));
    CHECK(off[1] + sb == gdakiStoreMrBytes(sb));  // the second slot ends at the MR's end
  }
  // the training shape (9.4, 9.8): 30 MiB image -> a slot of 64 KiB + 30 MiB + 1 MiB, the MR about 2 x 31 MiB
  CHECK(gdakiStoreSlotBytes(30 * MiB) == 64 * 1024 + 30 * MiB + MiB);
  CHECK(gdakiStoreMrBytes(gdakiStoreSlotBytes(30 * MiB)) / MiB == 62);
  // slots that overlap, are empty or overflow
  {
    const uint64_t a[2] = {0, 100}, b[2] = {100, 0}, c[2] = {0, 0}, d[2] = {~0ull - 10, 0};
    CHECK(!gdakiStoreSlotsSane(a, 101));
    CHECK(gdakiStoreSlotsSane(a, 100) && gdakiStoreSlotsSane(b, 100));
    CHECK(!gdakiStoreSlotsSane(c, 1) && !gdakiStoreSlotsSane(a, 0));
    CHECK(!gdakiStoreSlotsSane(d, 100));
  }
  // the receiving slot is never the stable one
  CHECK(gdakiStoreRecvSlot(-1) == 0 && gdakiStoreRecvSlot(0) == 1 && gdakiStoreRecvSlot(1) == 0);
  // pieces
  std::mt19937_64 rng(7);
  for (int it = 0; it < 2000; it++) {
    const uint64_t chunk = 1 + rng() % (it % 3 == 0 ? 64 : 1ull << 31);
    const uint64_t bytes = it % 5 == 0 ? 0 : rng() % (chunk * 9 + 3);
    const uint64_t n = gdakiStoreNChunks(bytes, chunk);
    uint64_t sum = 0;
    for (uint64_t i = 0; i < n; i++) {
      const uint64_t len = gdakiStoreChunkLen(i, bytes, chunk);
      CHECK(len > 0 && len <= chunk);
      sum += len;
    }
    CHECK(sum == bytes);
    CHECK(gdakiStoreChunkLen(n, bytes, chunk) == 0);
    CHECK(n == (bytes + chunk - 1) / chunk);
  }
  CHECK(gdakiStoreNChunks(30 * MiB + 64 * 1024, GDAKI_STORE_WRITE_CHUNK) == 1);  // the training upload: one WRITE
  CHECK(gdakiStoreNChunks(3ull << 30, GDAKI_STORE_WRITE_CHUNK) == 3);
  CHECK(gdakiStoreNChunks(150 * MiB, GDAKI_STORE_READ_CHUNK) == 5);
  CHECK(gdakiStoreNChunks(5, 0) == 0 && gdakiStoreChunkLen(0, 5, 0) == 0);
  // the layout key: the region table and the image size
  struct gdakiCkptRegion t[3] = {{GDAKI_CKPT_REGION_WINDOW, 0, 0, 6 * MiB},
                                 {GDAKI_CKPT_REGION_WINDOW, 1, 6 * MiB, 24 * MiB},
                                 {GDAKI_CKPT_REGION_SIGNALS, 0, 30 * MiB, 4096}};
  const uint64_t h0 = gdakiStoreLayoutHash(t, 3, 30 * MiB + 4096);
  CHECK(h0 == gdakiStoreLayoutHash(t, 3, 30 * MiB + 4096));
  CHECK(h0 != gdakiStoreLayoutHash(t, 2, 30 * MiB + 4096));
  CHECK(h0 != gdakiStoreLayoutHash(t, 3, 30 * MiB + 8192));
  struct gdakiCkptRegion u[3];
  memcpy(u, t, sizeof(t));
  u[1].id = 2;
  CHECK(h0 != gdakiStoreLayoutHash(u, 3, 30 * MiB + 4096));
  memcpy(u, t, sizeof(t));
  u[2].offset += 256;
  CHECK(h0 != gdakiStoreLayoutHash(u, 3, 30 * MiB + 4096));
  // the records' payloads fit gdakiTsMsg::executed (256 bytes), the spare part after the request, the stable view after
  // the answer
  CHECK(sizeof(struct gdakiStoreReq) == 80 && GDAKI_STORE_SPARE_OFF == 80);
  CHECK(GDAKI_STORE_SPARE_OFF + sizeof(struct gdakiStoreReqSpare) <= 256);
  CHECK(sizeof(struct gdakiStoreAck) == 160 && GDAKI_STORE_ACKS_OFF == 160 && sizeof(struct gdakiStoreAckStable) == 32);
  CHECK(GDAKI_STORE_ACKS_OFF + sizeof(struct gdakiStoreAckStable) <= 256);
  CHECK(sizeof(struct gdakiStoreAck) <= 256 && sizeof(struct gdakiStoreStable) <= 256);
  // the buddy's bound on a ward's MR (NCCL_GIN_RESTORE_STORE_MAX_MB, default 4096; 0 or less: none)
  CHECK(gdakiStoreMrFits(gdakiStoreMrBytes(gdakiStoreSlotBytes(30 * MiB)), 4096));  // the training shape
  CHECK(gdakiStoreMrFits(4096 * MiB, 4096) && !gdakiStoreMrFits(4096 * MiB + 1, 4096));
  CHECK(!gdakiStoreMrFits(gdakiStoreMrBytes(gdakiStoreSlotBytes(1ull << 40)), 4096));  // the largest image refused
  CHECK(!gdakiStoreMrFits(MiB + 1, 1) && gdakiStoreMrFits(MiB, 1));
  CHECK(gdakiStoreMrFits(~0ull, 0) && gdakiStoreMrFits(~0ull, -1) && gdakiStoreMrFits(~0ull, (int64_t)1 << 43));
  CHECK(!gdakiStoreMrFits(~0ull, ((int64_t)1 << 43) - 1));  // no shift overflow just below the "no bound" edge
}

// ---- 2. CKPT_STABLE's store payload ----
static void testStable() {
  const uint64_t img = 30 * MiB + 4096, sb = gdakiStoreSlotBytes(img);
  const struct gdakiStoreStable s = gdakiStoreStableOf(1, 7, img, 0x1234, 100);
  CHECK(s.version == GDAKI_MI_WIRE_VERSION && s.slot == 1 && s.gen == 7 && s.imageBytes == img &&
        s.layoutHash == 0x1234 && s.blobBytes == 100 && s.pad == 0);
  CHECK(s.usedBytes == gdakiStoreUsedBytes(img, 100));
  // through the record's payload words and back
  uint32_t executed[64];
  memset(executed, 0xab, sizeof(executed));
  memcpy(executed, &s, sizeof(s));
  struct gdakiStoreStable r;
  memcpy(&r, executed, sizeof(r));
  CHECK(memcmp(&r, &s, sizeof(s)) == 0);
  CHECK(gdakiStoreStableVerdict(r, 7, sb) == 0);
  // every reason, in impl/rs_store_api.h's order
  struct gdakiStoreStable x = s;
  x.version = 2;
  CHECK(gdakiStoreStableVerdict(x, 7, sb) == 1);
  CHECK(gdakiStoreStableVerdict(s, 8, sb) == 2);
  x = s;
  x.slot = 2;
  CHECK(gdakiStoreStableVerdict(x, 7, sb) == 3);
  x = s;
  x.usedBytes += 1;
  CHECK(gdakiStoreStableVerdict(x, 7, sb) == 4);
  CHECK(gdakiStoreStableVerdict(s, 7, s.usedBytes - 1) == 4);  // a smaller slot than the payload says
  CHECK(gdakiStoreStableVerdict(s, 7, s.usedBytes) == 0);
  x = gdakiStoreStableOf(0, 7, img, 0x1234, GDAKI_CKPT_MAX_BLOB + 1);
  CHECK(gdakiStoreStableVerdict(x, 7, ~0ull) == 5);
  for (int k = 0; k < 7; k++) CHECK(strcmp(gdakiStoreStableWhy(k), "?") != 0);
  // the pad: the store bit next to gin-restore's armable bit; the receiver's armable test sees only its own bit
  CHECK((GDAKI_CKPT_STABLE_STORE & GDAKI_CKPT_STABLE_ARMABLE) == 0);
  for (uint32_t armable : {0u, 1u}) {
    uint32_t pad = armable ? GDAKI_CKPT_STABLE_ARMABLE : 0u;  // 8548 / 8560
    pad |= GDAKI_CKPT_STABLE_STORE;                           // gdakiStoreFillStable
    CHECK(((pad & GDAKI_CKPT_STABLE_ARMABLE) != 0) == (armable != 0));
    CHECK((pad & GDAKI_CKPT_STABLE_STORE) != 0);
  }
  // the armable verdict (8543: every PAUSED armable and the buddy holds the spare) does not involve the store
  struct gdakiCkptReplies rep;
  rep.reset(4, 0);
  for (int q = 1; q < 4; q++) rep.armable[(size_t)q] = 1;
  CHECK(rep.allArmable());
  rep.armable[2] = 0;
  CHECK(!rep.allArmable());
  // the buddy's record of it
  struct gdakiStoreWardRec w;
  bool freeOld = true;
  CHECK(gdakiStoreWardStable(&w, s, 40, &freeOld) == 6 && !freeOld);  // nothing served yet
  (void)gdakiStoreWardServe(&w, 0, 1, 7, true, 0x99, sb);
  CHECK(gdakiStoreWardStable(&w, gdakiStoreStableOf(1, 6, img, 0x1234, 100), 40, &freeOld) == 2);  // older generation
  CHECK(!w.haveStable);
  CHECK(gdakiStoreWardStable(&w, s, 40, &freeOld) == 0 && !freeOld);
  CHECK(w.haveStable && w.stableSlot == 1 && w.stableCkpt == 40 && w.stableOff == sb && w.usedBytes == s.usedBytes &&
        w.imageBytes == img && w.layoutHash == 0x1234 && w.blobBytes == 100 && w.stableGen == 7);
  CHECK(gdakiStoreWardStableRkey(w) == 0x99);
}

// ---- 3. STORE_REQ and STORE_ACK ----
static struct gdakiMiQpEndpoint ep(uint32_t qpn) {
  struct gdakiMiQpEndpoint e;
  memset(&e, 0, sizeof(e));
  e.qpn = qpn;
  e.psn = 0x123456;
  e.mtu = 5;
  return e;
}
static struct gdakiStoreReq req(uint32_t inc, uint64_t seq, uint64_t img) {
  struct gdakiStoreReq q;
  memset(&q, 0, sizeof(q));
  q.version = GDAKI_MI_WIRE_VERSION;
  q.incarnation = inc;
  q.seq = seq;
  q.imageBytes = img;
  q.slotBytes = gdakiStoreSlotBytes(img);
  q.layoutHash = 0x55;
  q.up = ep(0x77);
  return q;
}
static struct gdakiStoreAck ack(uint64_t seq, uint64_t gen, uint64_t sb, uint32_t rkey = 0x42) {
  struct gdakiStoreAck a;
  memset(&a, 0, sizeof(a));
  a.version = GDAKI_MI_WIRE_VERSION;
  a.ok = 1;
  a.seq = seq;
  a.gen = gen;
  a.rkey = rkey;
  a.slotBytes = sb;
  a.slotOff[0] = 0;
  a.slotOff[1] = sb;
  a.up = ep(0x88);
  return a;
}
static void testRecords() {
  const uint64_t img = 30 * MiB;
  struct gdakiStoreReq q = req(0, 1, img);
  CHECK(gdakiStoreReqVerdict(q, 1, true, 0, false, 0, 0) == GDAKI_STORE_Q_OK);
  CHECK(gdakiStoreReqVerdict(q, 1, false, 0, false, 0, 0) == GDAKI_STORE_Q_NOT_WARD);
  CHECK(gdakiStoreReqVerdict(q, 2, true, 0, false, 0, 0) == GDAKI_STORE_Q_VERSION);  // round != seq
  struct gdakiStoreReq x = q;
  x.version = 9;
  CHECK(gdakiStoreReqVerdict(x, 1, true, 0, false, 0, 0) == GDAKI_STORE_Q_VERSION);
  x = q;
  x.seq = 0;
  CHECK(gdakiStoreReqVerdict(x, 0, true, 0, false, 0, 0) == GDAKI_STORE_Q_VERSION);
  x = q;
  x.slotBytes -= 4096;
  CHECK(gdakiStoreReqVerdict(x, 1, true, 0, false, 0, 0) == GDAKI_STORE_Q_SIZE);
  x = req(0, 1, 0);
  CHECK(gdakiStoreReqVerdict(x, 1, true, 0, false, 0, 0) == GDAKI_STORE_Q_SIZE);
  x = req(0, 1, GDAKI_STORE_MAX_IMAGE + 1);
  CHECK(gdakiStoreReqVerdict(x, 1, true, 0, false, 0, 0) == GDAKI_STORE_Q_SIZE);
  CHECK(gdakiStoreReqVerdict(q, 1, true, 1, false, 0, 0) == GDAKI_STORE_Q_OLD_INC);  // this rank knows incarnation 1
  CHECK(gdakiStoreReqVerdict(q, 1, true, 0, true, 1, 5) == GDAKI_STORE_Q_OLD_INC);   // incarnation 1 was served
  CHECK(gdakiStoreReqVerdict(q, 1, true, 0, true, 0, 1) == GDAKI_STORE_Q_STALE);
  CHECK(gdakiStoreReqVerdict(q, 1, true, 0, true, 0, 3) == GDAKI_STORE_Q_STALE);
  x = req(1, 1, img);  // a new incarnation starts its sequence again
  CHECK(gdakiStoreReqVerdict(x, 1, true, 1, true, 0, 9) == GDAKI_STORE_Q_OK);
  x = q;
  x.up.qpn = 0;
  CHECK(gdakiStoreReqVerdict(x, 1, true, 0, false, 0, 0) == GDAKI_STORE_Q_ENDPOINT);
  x = q;
  x.up.qpn = 1u << 24;
  CHECK(gdakiStoreReqVerdict(x, 1, true, 0, false, 0, 0) == GDAKI_STORE_Q_ENDPOINT);
  x = q;
  x.up.mtu = 0;
  CHECK(gdakiStoreReqVerdict(x, 1, true, 0, false, 0, 0) == GDAKI_STORE_Q_ENDPOINT);
  for (int v = 0; v <= 6; v++) CHECK(strcmp(gdakiStoreReqWhy(v), "?") != 0);
  // the request and the spare registration through the payload words
  uint32_t executed[64];
  memset(executed, 0, sizeof(executed));
  struct gdakiStoreReqSpare sp;
  memset(&sp, 0, sizeof(sp));
  sp.magic = GDAKI_STORE_SPARE_MAGIC;
  sp.haveSpare = 1;
  for (int i = 0; i < 32; i++) sp.spareAddr[i] = (uint8_t)(i * 7 + 1);
  sp.pid = 4242;
  sp.pidStart = 987654321;
  memcpy(executed, &q, sizeof(q));
  memcpy((uint8_t*)executed + GDAKI_STORE_SPARE_OFF, &sp, sizeof(sp));
  struct gdakiStoreReq q2;
  struct gdakiStoreReqSpare sp2;
  memcpy(&q2, executed, sizeof(q2));
  memcpy(&sp2, (const uint8_t*)executed + GDAKI_STORE_SPARE_OFF, sizeof(sp2));
  CHECK(memcmp(&q2, &q, sizeof(q)) == 0 && memcmp(&sp2, &sp, sizeof(sp)) == 0);
  // STORE_ACK
  const uint64_t sb = gdakiStoreSlotBytes(img);
  struct gdakiStoreAck a = ack(3, 9, sb);
  CHECK(gdakiStoreAckVerdict(a, 3, true, 3, sb) == GDAKI_STORE_A_OK);
  CHECK(gdakiStoreAckVerdict(a, 3, false, 3, sb) == GDAKI_STORE_A_STALE);  // nothing outstanding
  CHECK(gdakiStoreAckVerdict(a, 3, true, 4, sb) == GDAKI_STORE_A_STALE);   // an older request's answer
  CHECK(gdakiStoreAckVerdict(a, 2, true, 3, sb) == GDAKI_STORE_A_STALE);   // the record's round differs
  struct gdakiStoreAck y = a;
  y.version = 0;
  CHECK(gdakiStoreAckVerdict(y, 3, true, 3, sb) == GDAKI_STORE_A_VERSION);
  y = a;
  y.ok = 0;
  CHECK(gdakiStoreAckVerdict(y, 3, true, 3, sb) == GDAKI_STORE_A_REFUSED);
  CHECK(gdakiStoreAckVerdict(a, 3, true, 3, sb + 4096) == GDAKI_STORE_A_SIZE);  // smaller slots than asked
  CHECK(gdakiStoreAckVerdict(ack(3, 9, sb + 65536), 3, true, 3, sb) == GDAKI_STORE_A_OK);  // larger: kept MR
  y = a;
  y.gen = 0;
  CHECK(gdakiStoreAckVerdict(y, 3, true, 3, sb) == GDAKI_STORE_A_SIZE);
  y = a;
  y.slotOff[1] = sb - 1;
  CHECK(gdakiStoreAckVerdict(y, 3, true, 3, sb) == GDAKI_STORE_A_SIZE);
  y = a;
  y.up.qpn = 0;
  CHECK(gdakiStoreAckVerdict(y, 3, true, 3, sb) == GDAKI_STORE_A_ENDPOINT);
  for (int v = 0; v <= 5; v++) CHECK(strcmp(gdakiStoreAckWhy(v), "?") != 0);
  // the answer and the stable view (its trailer) through the payload words; a trailer left zero has no magic
  memset(executed, 0, sizeof(executed));
  struct gdakiStoreAckStable as;
  memset(&as, 0, sizeof(as));
  as.magic = GDAKI_STORE_ACKS_MAGIC;
  as.haveStable = 1;
  as.stableSlot = 1;
  as.stableGen = 9;
  as.stableCkpt = 1234;
  memcpy(executed, &a, sizeof(a));
  memcpy((uint8_t*)executed + GDAKI_STORE_ACKS_OFF, &as, sizeof(as));
  struct gdakiStoreAck a2;
  struct gdakiStoreAckStable as2;
  memcpy(&a2, executed, sizeof(a2));
  memcpy(&as2, (const uint8_t*)executed + GDAKI_STORE_ACKS_OFF, sizeof(as2));
  CHECK(memcmp(&a2, &a, sizeof(a)) == 0 && memcmp(&as2, &as, sizeof(as)) == 0);
  memset(executed, 0, sizeof(executed));
  memcpy(executed, &a, sizeof(a));
  memcpy(&as2, (const uint8_t*)executed + GDAKI_STORE_ACKS_OFF, sizeof(as2));
  CHECK(as2.magic == 0 && as2.magic != GDAKI_STORE_ACKS_MAGIC);
  // a request taken while its ward is declined or held is not served: a declined ward's never, a held ward's unless it
  // comes from a newer incarnation than the one the hold is about (the hold cell's: the restored process's request)
  CHECK(gdakiStoreDropReq(true, false, 5, 1) && gdakiStoreDropReq(true, true, 5, 1) && gdakiStoreDropReq(true, false, 1, 1));
  CHECK(gdakiStoreDropReq(false, true, 1, 1) && gdakiStoreDropReq(false, true, 0, 1));
  CHECK(!gdakiStoreDropReq(false, true, 2, 1));
  CHECK(!gdakiStoreDropReq(false, false, 0, 1) && !gdakiStoreDropReq(false, false, 1, 1) && !gdakiStoreDropReq(false, false, 2, 1));
  // fix of pilot 1's defect A (2026-10-15): with the mirror on the ward stays PUBLISHED (held) of incarnation i until its
  // INJECTED while the REJOIN already made i + 1 the known incarnation; the caller passes the hold's i, so the restored
  // process's first request (i + 1) is served there and a leftover of the dead process (i or older) is dropped
  for (uint32_t i = 0; i < 4; i++) {
    CHECK(!gdakiStoreDropReq(false, true, i + 1u, i));
    CHECK(gdakiStoreDropReq(false, true, i, i));
    if (i > 0) CHECK(gdakiStoreDropReq(false, true, i - 1u, i));
  }
}

// ---- 4. the uploader's request machine ----
static void testUploader() {
  const uint64_t img = 30 * MiB, sb = gdakiStoreSlotBytes(img);
  struct gdakiStoreUp u;
  double now = 1000;
  // nothing before the first request; not while busy or not idle
  CHECK(!u.readyNow());
  CHECK(u.nextReq(now, true, 0) == GDAKI_STORE_N_FIRST);
  CHECK(u.nextReq(now, false, 0) == GDAKI_STORE_N_NONE);  // a checkpoint of this rank in flight
  u.writing = true;
  CHECK(u.nextReq(now, true, 0) == GDAKI_STORE_N_NONE);
  u.writing = false;
  // a failed send: back off, then again (the reason kept)
  u.begin();
  u.sent(false, 1, now, img, 0x55, sb, 0);
  CHECK(!u.reqOut && u.seq == 0 && u.need == GDAKI_STORE_N_FIRST);
  CHECK(u.nextReq(now + 10, true, 0) == GDAKI_STORE_N_NONE);
  CHECK(u.nextReq(now + GDAKI_STORE_BACKOFF_MS, true, 0) == GDAKI_STORE_N_FIRST);
  now += GDAKI_STORE_BACKOFF_MS;
  u.begin();
  u.sent(true, 1, now, img, 0x55, sb, 0);
  CHECK(u.reqOut && u.seq == 1 && u.need == GDAKI_STORE_N_NONE && !u.readyNow());
  CHECK(u.nextReq(now + 10, true, 0) == GDAKI_STORE_N_NONE);  // waiting for the answer
  // a stale answer changes nothing
  CHECK(u.onAck(ack(0, 3, sb), 0, now) == GDAKI_STORE_A_STALE && u.reqOut);
  // no answer for GDAKI_STORE_REQ_RETRY_MS: a new request
  CHECK(u.nextReq(now + GDAKI_STORE_REQ_RETRY_MS + 1, true, 0) == GDAKI_STORE_N_RETRY);
  now += GDAKI_STORE_REQ_RETRY_MS + 1;
  u.begin();
  u.sent(true, 2, now, img, 0x55, sb, 0);
  CHECK(u.onAck(ack(1, 3, sb), 1, now) == GDAKI_STORE_A_STALE);  // the first one's late answer
  // refused: back off, then again
  struct gdakiStoreAck no = ack(2, 0, 0);
  no.ok = 0;
  CHECK(u.onAck(no, 2, now) == GDAKI_STORE_A_REFUSED && !u.reqOut && u.need == GDAKI_STORE_N_REFUSED);
  CHECK(u.nextReq(now + 1, true, 0) == GDAKI_STORE_N_NONE);
  now += GDAKI_STORE_BACKOFF_MS;
  CHECK(u.nextReq(now, true, 0) == GDAKI_STORE_N_REFUSED);
  u.begin();
  u.sent(true, 3, now, img, 0x55, sb, 0);
  // accepted; a failed connect: a new request after the back-off
  CHECK(u.onAck(ack(3, 4, sb), 3, now) == GDAKI_STORE_A_OK && !u.reqOut && u.gen == 4 && u.slotBytes == sb);
  u.connected(false, now);
  CHECK(!u.readyNow() && u.need == GDAKI_STORE_N_QP);
  now += GDAKI_STORE_BACKOFF_MS;
  CHECK(u.nextReq(now, true, 0) == GDAKI_STORE_N_QP);
  u.begin();
  u.sent(true, 4, now, img, 0x55, sb, 0);
  CHECK(u.onAck(ack(4, 5, sb), 4, now) == GDAKI_STORE_A_OK);
  u.connected(true, now);
  CHECK(u.readyNow() && u.nextReq(now, true, 0) == GDAKI_STORE_N_NONE);
  // the application wants this layout: ready; another layout: not ready, a request (LAYOUT)
  u.wantValid = true;
  u.wantImage = img;
  u.wantLayout = 0x55;
  CHECK(u.readyNow());
  CHECK(!u.beginWrite(img, 0x56) && !u.beginWrite(img + 1, 0x55));
  CHECK(u.beginWrite(img, 0x55) && u.writing && !u.readyNow());
  CHECK(u.recvSlot() == 0);
  CHECK(!u.beginWrite(img, 0x55));  // one at a time
  CHECK(u.nextReq(now, true, 0) == GDAKI_STORE_N_NONE);  // never under a WRITE
  u.endWrite(true);
  u.stableSent(0, 5);
  CHECK(u.stableSlot == 0 && u.recvSlot() == 1 && u.readyNow());
  u.stableSent(1, 4);  // another generation's: ignored
  CHECK(u.stableSlot == 0);
  CHECK(u.beginWrite(img, 0x55));
  u.endWrite(true);
  u.stableSent(1, 5);
  CHECK(u.stableSlot == 1 && u.recvSlot() == 0);
  // a WRITE that failed: a new request (QP); the stable slot's view stays (same buddy process)
  CHECK(u.beginWrite(img, 0x55));
  u.endWrite(false);
  CHECK(!u.readyNow() && u.need == GDAKI_STORE_N_QP && u.stableSlot == 1);
  CHECK(u.nextReq(now, true, 0) == GDAKI_STORE_N_QP);
  u.begin();
  u.sent(true, 5, now, img, 0x55, sb, 0);
  CHECK(u.onAck(ack(5, 6, sb), 5, now) == GDAKI_STORE_A_OK);
  u.connected(true, now);
  CHECK(u.readyNow() && u.stableSlot == 1);
  // the layout changes: LAYOUT
  u.wantImage = img + 4096;
  u.wantLayout = 0x66;
  CHECK(!u.readyNow() && u.nextReq(now, true, 0) == GDAKI_STORE_N_LAYOUT);
  u.begin();
  u.sent(true, 6, now, u.wantImage, u.wantLayout, gdakiStoreSlotBytes(u.wantImage), 0);
  CHECK(u.onAck(ack(6, 7, gdakiStoreSlotBytes(u.wantImage)), 6, now) == GDAKI_STORE_A_OK);
  u.connected(true, now);
  CHECK(u.readyNow() && u.ackImage == img + 4096 && u.ackLayout == 0x66);
  // the buddy has another incarnation: BUDDY; its new process holds nothing of this rank (the stable view is reset)
  CHECK(u.nextReq(now, true, 1) == GDAKI_STORE_N_BUDDY);
  u.begin();
  u.sent(true, 7, now, u.wantImage, u.wantLayout, gdakiStoreSlotBytes(u.wantImage), 1);
  CHECK(u.stableSlot == -1 && u.reqBuddyInc == 1);
  CHECK(u.onAck(ack(7, 1, gdakiStoreSlotBytes(u.wantImage)), 7, now) == GDAKI_STORE_A_OK && u.buddyInc == 1);
  u.connected(true, now);
  CHECK(u.readyNow() && u.recvSlot() == 0);
  u.stableSent(0, 1);
  // RESTORED of the buddy: everything again, also an outstanding request
  u.buddyRestored();
  CHECK(!u.readyNow() && u.stableSlot == -1 && !u.reqOut && u.need == GDAKI_STORE_N_BUDDY);
  CHECK(u.nextReq(now, true, 1) == GDAKI_STORE_N_BUDDY);
  // the helper socket to the buddy was reinstalled while the store was ready (a CKPT_STABLE may have been lost on it):
  // SOCKET, and the answer's view of the stable slot replaces this rank's
  u.begin();
  u.sent(true, 8, now, u.wantImage, u.wantLayout, gdakiStoreSlotBytes(u.wantImage), 1);
  CHECK(u.onAck(ack(8, 2, gdakiStoreSlotBytes(u.wantImage)), 8, now) == GDAKI_STORE_A_OK);
  u.connected(true, now);
  CHECK(u.readyNow() && u.stableSlot == -1);
  CHECK(u.beginWrite(u.wantImage, u.wantLayout) && u.recvSlot() == 0);
  u.endWrite(true);
  u.stableSent(0, 2);
  CHECK(u.stableSlot == 0);
  CHECK(u.beginWrite(u.wantImage, u.wantLayout) && u.recvSlot() == 1);
  u.endWrite(true);
  u.stableSent(1, 2);              // sent, but say the socket was lost before the buddy read it: the buddy keeps slot 0
  CHECK(u.stableSlot == 1 && u.recvSlot() == 0);  // the diverged view would overwrite the buddy's stable slot 0
  CHECK(u.nextReq(now, true, 1, false) == GDAKI_STORE_N_NONE);
  CHECK(u.nextReq(now, true, 1, true) == GDAKI_STORE_N_SOCKET);
  CHECK(u.nextReq(now, false, 1, true) == GDAKI_STORE_N_NONE);  // never while a checkpoint is in flight
  u.begin();
  CHECK(!u.readyNow());
  u.sent(true, 9, now, u.wantImage, u.wantLayout, gdakiStoreSlotBytes(u.wantImage), 1);
  CHECK(u.onAck(ack(9, 3, gdakiStoreSlotBytes(u.wantImage)), 9, now) == GDAKI_STORE_A_OK);
  u.ackStable(true, 0);            // the trailer: the buddy's stable slot is 0
  u.connected(true, now);
  CHECK(u.readyNow() && u.stableSlot == 0 && u.recvSlot() == 1);
  u.ackStable(false, 0);
  CHECK(u.stableSlot == -1 && u.recvSlot() == 0);
  u.ackStable(true, 2);            // not a slot: none
  CHECK(u.stableSlot == -1);
  u.ackStable(true, 1);
  CHECK(u.stableSlot == 1 && u.recvSlot() == 0);
  for (int k = 0; k <= 7; k++) CHECK(strcmp(gdakiStoreNeedName(k), "?") != 0);
  CHECK(strcmp(gdakiStoreNeedName(GDAKI_STORE_N_SOCKET), "socket") == 0);
}

// ---- 5. the buddy's record of a ward ----
static void testWard() {
  const uint64_t sb1 = gdakiStoreSlotBytes(30 * MiB), sb2 = gdakiStoreSlotBytes(40 * MiB);
  struct gdakiStoreWardRec w;
  CHECK(gdakiStoreNeedMr(w, sb1));
  struct gdakiStoreCommit c = gdakiStoreWardServe(&w, 0, 1, 1, true, 10, sb1);
  CHECK(!c.freeCur && !c.curToOld && !c.freeOld && w.haveMr && w.rkey == 10 && w.gen == 1 && w.slotBytes == sb1);
  // a request of the same or smaller slots keeps the MR: only the QP and the generation are new
  CHECK(!gdakiStoreNeedMr(w, sb1) && !gdakiStoreNeedMr(w, gdakiStoreSlotBytes(1 * MiB)));
  c = gdakiStoreWardServe(&w, 0, 2, 2, false, 0, sb1);
  CHECK(!c.freeCur && !c.curToOld && !c.freeOld && w.rkey == 10 && w.gen == 2);
  bool freeOld = false;
  CHECK(gdakiStoreWardStable(&w, gdakiStoreStableOf(0, 2, 30 * MiB, 1, 0), 20, &freeOld) == 0 && !freeOld);
  CHECK(w.haveStable && !w.stableInOld && w.stableSlot == 0 && gdakiStoreWardStableRkey(w) == 10);
  // a QP-only request keeps the stable slot (same incarnation)
  c = gdakiStoreWardServe(&w, 0, 3, 3, false, 0, sb1);
  CHECK(w.haveStable && w.stableCkpt == 20 && w.gen == 3);
  // larger slots while the current MR holds the stable slot: it becomes the old one (a restore reads it meanwhile)
  CHECK(gdakiStoreNeedMr(w, sb2));
  c = gdakiStoreWardServe(&w, 0, 4, 4, true, 11, sb2);
  CHECK(c.curToOld && !c.freeCur && !c.freeOld && w.haveOld && w.oldRkey == 10 && w.stableInOld && w.rkey == 11);
  CHECK(gdakiStoreWardStableRkey(w) == 10 && w.stableOff == 0 && w.stableCkpt == 20);
  // an old generation's CKPT_STABLE is refused (nothing moves)
  CHECK(gdakiStoreWardStable(&w, gdakiStoreStableOf(1, 3, 30 * MiB, 1, 0), 21, &freeOld) == 2 && w.stableCkpt == 20);
  // larger again before a stable slot in the current MR: the current one goes, the old one stays
  const uint64_t sb3 = gdakiStoreSlotBytes(50 * MiB);
  c = gdakiStoreWardServe(&w, 0, 5, 5, true, 12, sb3);
  CHECK(c.freeCur && !c.curToOld && !c.freeOld && w.haveOld && w.oldRkey == 10 && w.rkey == 12);
  // the next stable slot lands in the current MR: the old one goes
  CHECK(gdakiStoreWardStable(&w, gdakiStoreStableOf(1, 5, 50 * MiB, 2, 7), 22, &freeOld) == 0 && freeOld);
  CHECK(!w.haveOld && !w.stableInOld && w.stableSlot == 1 && w.stableOff == sb3 && gdakiStoreWardStableRkey(w) == 12);
  // a new incarnation of the ward: its stable slot is dropped (P5), the MR is kept when large enough
  c = gdakiStoreWardServe(&w, 1, 1, 6, false, 0, sb1);
  CHECK(!c.freeCur && !c.curToOld && !c.freeOld && !w.haveStable && w.inc == 1 && w.seq == 1 && w.rkey == 12);
  // a new incarnation while an old MR holds the stable slot: both the stable slot and the old MR go
  struct gdakiStoreWardRec v;
  (void)gdakiStoreWardServe(&v, 0, 1, 1, true, 20, sb1);
  CHECK(gdakiStoreWardStable(&v, gdakiStoreStableOf(0, 1, 30 * MiB, 1, 0), 5, &freeOld) == 0);
  (void)gdakiStoreWardServe(&v, 0, 2, 2, true, 21, sb2);
  CHECK(v.haveOld && v.stableInOld);
  c = gdakiStoreWardServe(&v, 1, 1, 3, true, 22, gdakiStoreSlotBytes(60 * MiB));
  CHECK(c.freeOld && c.freeCur && !c.curToOld && !v.haveOld && !v.haveStable && v.rkey == 22);
}

// ---- 6. a model of both sides with injected failures ----
namespace model {
struct Mem {
  bool alive = true;
  uint64_t slotBytes = 0;
  int64_t ckpt[2] = {-1, -1};
  bool complete[2] = {false, false};
};
struct Buddy {
  bool up = true;
  uint32_t procInc = 0;            // the buddy process's incarnation
  struct gdakiStoreWardRec rec;
  int curMr = -1, oldMr = -1;      // MR ids (rkey = id + 1)
  uint64_t genNext = 1;
  uint64_t qpGen = 0;              // the generation its side of the upload QP belongs to (0: none)
  uint32_t knownWardInc = 0;       // the ward's incarnation this buddy knows
  uint64_t holdCell = 0;           // its hold cell of the ward: gdakiHoldPack(state, the incarnation it concerns)
};
struct Msg {
  int kind;                        // 1 STORE_REQ, 2 CKPT_STABLE
  struct gdakiStoreReq q;
  uint64_t ckpt;
  struct gdakiStoreStable s;
  uint32_t fromInc;                // the ward process that sent it
};
struct Stats {
  long requests = 0, acks = 0, refused = 0, writes = 0, writeFails = 0, stables = 0, stableRefused = 0, buddyDeaths = 0,
       wardDeaths = 0, layoutChanges = 0, readyAgain = 0, checks = 0, stableLost = 0, socketRequests = 0, dropped = 0,
       servedHeld = 0, injected = 0;
};
struct Ans {                       // one STORE_ACK: the answer, its trailer, the ward process it is for
  struct gdakiStoreAck a;
  struct gdakiStoreAckStable s;
  uint32_t forInc;
};
struct World {
  std::mt19937_64 rng;
  double now = 0;
  std::vector<Mem> mrs;
  Buddy b;
  struct gdakiStoreUp u;
  uint32_t wardInc = 0;
  uint64_t image = 30 * MiB, layout = 0x100;
  uint64_t upGen = 0;              // the generation the ward's upload QP was connected for (0: none)
  uint32_t sockGen = 0;            // the helper socket's generation to the buddy (a loss and reinstall bumps it)
  std::deque<Msg> u2b;             // the ward's helper socket to the buddy (in order)
  std::deque<Ans> b2u;             // answers, with the ward process they are for
  int64_t armed = -1;              // the checkpoint every peer would restore the ward from (-1: not armed)
  // the checkpoint in flight (the ward)
  int phase = 0;                   // 0 idle, 1 WRITE running, 2 WRITE done ok (CKPT_STABLE next)
  uint64_t ck = 0, nextCk = 1;
  uint32_t wSlot = 0;
  uint64_t wGen = 0, wImage = 0, wLayout = 0;
  int wMr = -1;
  Stats st;
  bool failures = true;            // inject failures (off for the tail: the store must get ready again)
  bool preFixCaller = false;       // the drop's hold incarnation is the known one (before the fix of defect A)
  bool injectedPending = false;    // the ward was restored and its INJECTED has not reached the buddy yet
  explicit World(uint64_t seed) : rng(seed) {}
  bool p(double x) { return std::uniform_real_distribution<double>(0, 1)(rng) < x; }
  int newMr(uint64_t slotBytes) {
    mrs.push_back(Mem());
    mrs.back().slotBytes = slotBytes;
    return (int)mrs.size() - 1;
  }
  void freeMr(int id) {
    if (id >= 0) mrs[(size_t)id].alive = false;
  }
  // The record's invariants, and the restore's safety: were the ward to die now, its buddy first reads what the ward
  // sent before (the hold machine takes a held peer's checkpoint records before the activation, 11949-11956); then, when
  // the ward is armed, the buddy's stable slot holds that checkpoint completely in a live MR at the right offset.
  void check() {
    st.checks++;
    CHECK(!b.rec.haveOld || b.rec.stableInOld);
    CHECK(b.rec.haveOld == (b.oldMr >= 0));
    CHECK(b.rec.haveMr == (b.curMr >= 0));
    if (b.curMr >= 0) CHECK(mrs[(size_t)b.curMr].alive && b.rec.rkey == (uint32_t)b.curMr + 1);
    if (b.oldMr >= 0) CHECK(mrs[(size_t)b.oldMr].alive && b.rec.oldRkey == (uint32_t)b.oldMr + 1);
    CHECK(u.writing == (phase == 1));
    if (!b.up) return;
    // a STORE_REQ in flight moves no stable slot's bytes (its MR stays while it holds one): draining matters only while a
    // CKPT_STABLE is in flight (then on a copy of the world)
    bool stableInFlight = false;
    for (const Msg& m : u2b) stableInFlight = stableInFlight || m.kind == 2;
    if (!stableInFlight) return checkArmed(*this);
    World c = *this;
    c.failures = false;
    while (!c.u2b.empty()) c.buddyStep();
    checkArmed(c);
  }
  static void checkArmed(const World& c) {
    if (c.armed < 0) return;
    CHECK(c.b.rec.haveStable && (int64_t)c.b.rec.stableCkpt == c.armed);
    if (!c.b.rec.haveStable) return;
    const int id = (int)gdakiStoreWardStableRkey(c.b.rec) - 1;
    CHECK(id >= 0 && id < (int)c.mrs.size());
    if (id < 0 || id >= (int)c.mrs.size()) return;
    const Mem& m = c.mrs[(size_t)id];
    CHECK(m.alive && c.b.rec.stableSlot < 2);
    CHECK(m.ckpt[c.b.rec.stableSlot & 1] == c.armed && m.complete[c.b.rec.stableSlot & 1]);
    CHECK(c.b.rec.stableOff == gdakiStoreSlotOff(m.slotBytes, c.b.rec.stableSlot));
  }
  // the ward's helper step: a request when one is needed
  void wardRequest() {
    if (!b.up) {  // its socket is gone: nothing is sent (the helper's precondition)
      return;
    }
    const bool idle = phase == 0;
    const bool sockMoved = u.ready && sockGen != u.sockGen;  // the helper's rule (gdakiStoreUpStep)
    const int why = u.nextReq(now, idle, b.procInc, sockMoved);
    if (why == GDAKI_STORE_N_NONE) return;
    if (why == GDAKI_STORE_N_SOCKET) st.socketRequests++;
    if (!u.wantValid) {
      u.wantValid = true;
      u.wantImage = image;
      u.wantLayout = layout;
    }
    u.begin();
    upGen = 0;  // the old upload QP is destroyed
    const uint64_t seq = u.seq + 1;
    const bool sent = !(failures && p(0.03));
    struct gdakiStoreReq q;
    memset(&q, 0, sizeof(q));
    q.version = GDAKI_MI_WIRE_VERSION;
    q.incarnation = wardInc;
    q.seq = seq;
    q.imageBytes = u.wantImage;
    q.slotBytes = gdakiStoreSlotBytes(u.wantImage);
    q.layoutHash = u.wantLayout;
    q.up = ep(0x100 + (uint32_t)seq);
    u.sent(sent, seq, now, q.imageBytes, q.layoutHash, q.slotBytes, b.procInc);
    if (!sent) return;
    st.requests++;
    Msg m;
    memset(&m, 0, sizeof(m));
    m.kind = 1;
    m.q = q;
    m.fromInc = wardInc;
    u2b.push_back(m);
  }
  // the buddy's helper and store thread: one record of the ward
  void buddyStep() {
    if (!b.up || u2b.empty()) return;
    const Msg m = u2b.front();
    u2b.pop_front();
    if (m.kind == 1) {
      // the caller's drop (gdakiStoreDropNow): the ward's hold cell read once; the hold's incarnation is the cell's (the
      // fix of pilot 1's defect A), the pre-fix caller passed the known incarnation (preFixCaller)
      const uint32_t hs = gdakiHoldStateOf(b.holdCell), hInc = gdakiHoldIncOf(b.holdCell);
      const bool held = gdakiHoldIsHeldState(hs);
      if (gdakiStoreDropReq(false, held, m.q.incarnation, preFixCaller ? b.knownWardInc : hInc)) {
        st.dropped++;
        CHECK(preFixCaller || m.fromInc < wardInc);  // only a dead process's request is dropped (no answer)
        return;
      }
      CHECK(!held || m.q.incarnation > hInc);  // a held ward's request that is served is the restored process's
      if (held) st.servedHeld++;
      const int v = gdakiStoreReqVerdict(m.q, m.q.seq, true, b.knownWardInc, b.rec.served, b.rec.inc, b.rec.seq);
      Ans ans;
      memset(&ans, 0, sizeof(ans));
      ans.forInc = m.fromInc;
      struct gdakiStoreAck& a = ans.a;
      a.version = GDAKI_MI_WIRE_VERSION;
      a.seq = m.q.seq;
      if (v != GDAKI_STORE_Q_OK || (failures && p(0.04))) {  // a refusal (or the registration failed: memlock)
        a.ok = 0;
        b2u.push_back(ans);
        return;
      }
      b.qpGen = 0;  // the ward's old upload QP goes first
      const bool needMr = gdakiStoreNeedMr(b.rec, m.q.slotBytes);
      const int id = needMr ? newMr(m.q.slotBytes) : -1;
      const uint64_t gen = b.genNext++;
      const struct gdakiStoreCommit c =
        gdakiStoreWardServe(&b.rec, m.q.incarnation, m.q.seq, gen, needMr, needMr ? (uint32_t)id + 1 : 0u, m.q.slotBytes);
      if (c.freeOld) {
        freeMr(b.oldMr);
        b.oldMr = -1;
      }
      if (c.curToOld) b.oldMr = b.curMr;
      else if (c.freeCur) freeMr(b.curMr);
      if (needMr) b.curMr = id;
      b.qpGen = gen;
      a.ok = 1;
      a.gen = gen;
      a.rkey = b.rec.rkey;
      a.slotBytes = b.rec.slotBytes;
      a.slotOff[0] = 0;
      a.slotOff[1] = b.rec.slotBytes;
      a.up = ep(0x900 + (uint32_t)gen);
      ans.s.magic = GDAKI_STORE_ACKS_MAGIC;  // the trailer: the ward's stable slot here, as the commit left it
      ans.s.haveStable = b.rec.haveStable ? 1u : 0u;
      ans.s.stableSlot = b.rec.stableSlot;
      ans.s.stableGen = b.rec.stableGen;
      ans.s.stableCkpt = b.rec.stableCkpt;
      if (!(failures && p(0.03))) b2u.push_back(ans);  // else: lost (the ward's RETRY)
      return;
    }
    // CKPT_STABLE (the buddy first): its slot is the stable one, or DISARM
    bool freeOld = false;
    const int v = gdakiStoreWardStable(&b.rec, m.s, m.ckpt, &freeOld);
    if (freeOld) {
      freeMr(b.oldMr);
      b.oldMr = -1;
    }
    if (v == 0) {
      st.stables++;
      if (m.fromInc == wardInc) armed = (int64_t)m.ckpt;  // every peer arms the ward at it
    } else {
      st.stableRefused++;
      armed = -1;  // the buddy's DISARM
    }
  }
  // the ward's helper: one answer
  void wardAck() {
    if (b2u.empty()) return;
    const Ans e = b2u.front();
    b2u.pop_front();
    if (e.forInc != wardInc) return;  // for a dead process
    const struct gdakiStoreAck a = e.a;
    const int v = u.onAck(a, a.seq, now);
    if (v == GDAKI_STORE_A_STALE) return;
    st.acks++;
    if (v != GDAKI_STORE_A_OK) {
      st.refused++;
      return;
    }
    if (e.s.magic == GDAKI_STORE_ACKS_MAGIC) u.ackStable(e.s.haveStable == 1u, e.s.stableSlot);  // the helper's rule
    const bool connected = !(failures && p(0.03));
    const bool wasReady = u.ready;
    u.connected(connected, now);
    if (connected) {
      upGen = a.gen;
      u.sockGen = sockGen;
    }
    if (connected && !wasReady) st.readyAgain++;
  }
  // the ward's application thread and helper: the checkpoint's steps
  void wardCheckpoint() {
    if (phase == 0) {
      u.wantValid = true;  // the Step publishes its layout first
      u.wantImage = image;
      u.wantLayout = layout;
      wardRequest();              // the helper's order: its store step (a request if one is due) before the IDLE verdict
      if (!u.readyNow()) return;  // the IDLE refusal: not taken
      CHECK(u.beginWrite(image, layout));
      ck = nextCk++;
      wSlot = u.recvSlot();
      wGen = u.gen;
      wImage = image;  // the payload names what was written (gdakiStoreTake keeps it in wStable)
      wLayout = layout;
      wMr = (int)u.rkey - 1;
      // the WRITE starts: the receiving slot is incomplete from the first byte on (only if the QP still reaches it)
      if (upGen == wGen && b.up && b.qpGen == wGen && wMr >= 0 && wMr < (int)mrs.size() && mrs[(size_t)wMr].alive) {
        mrs[(size_t)wMr].ckpt[wSlot] = (int64_t)ck;
        mrs[(size_t)wMr].complete[wSlot] = false;
      }
      phase = 1;
      return;
    }
    if (phase == 1) {  // the WRITE ends: complete only on a QP the buddy still keeps for this generation
      const bool reach = upGen == wGen && b.up && b.qpGen == wGen && wMr >= 0 && mrs[(size_t)wMr].alive;
      const bool ok = reach && !(failures && p(0.06));
      if (ok) mrs[(size_t)wMr].complete[wSlot] = true;
      u.endWrite(ok);
      if (ok) st.writes++;
      else st.writeFails++;
      phase = ok ? 2 : 0;  // a failed WRITE: the checkpoint is void
      return;
    }
    // CONFIRMING: CKPT_STABLE to the buddy (it may not go out: void), then the view of the stable slot
    phase = 0;
    if (!b.up || (failures && p(0.02))) return;
    if (failures && p(0.02)) {  // buffered on the helper socket, then the socket is lost before the buddy reads it and
      u.stableSent(wSlot, wGen);  // reinstalled: the ward's view moved, the buddy's did not (independent review 2)
      st.stableLost++;
      sockGen++;
      return;
    }
    Msg m;
    memset(&m, 0, sizeof(m));
    m.kind = 2;
    m.ckpt = ck;
    m.s = gdakiStoreStableOf(wSlot, wGen, wImage, wLayout, 64);
    m.fromInc = wardInc;
    u2b.push_back(m);
    u.stableSent(wSlot, wGen);
  }
  void buddyDies() {
    b.up = false;
    st.buddyDeaths++;
    b2u.clear();
    u2b.clear();
    if (phase == 1) {  // its WRITE fails at the bound
      u.endWrite(false);
      st.writeFails++;
      phase = 0;
    } else if (phase == 2) {
      phase = 0;  // CKPT_STABLE cannot go: void
    }
  }
  void buddyRestored() {
    for (auto& m : mrs) m.alive = false;  // the dead process's memory is gone
    const uint32_t inc = b.procInc + 1;
    b = Buddy();
    b.procInc = inc;
    b.knownWardInc = wardInc;
    b.holdCell = gdakiHoldPack(GDAKI_HOLD_OFF, wardInc);  // a new buddy process holds nothing of the ward
    injectedPending = false;
    armed = -1;  // the ward took part in the restore: DISARMed until its next stable checkpoint
    u.buddyRestored();
  }
  // a STORE_REQ of the ward process of incarnation inc (its upload endpoint aside, as wardRequest makes them)
  Msg request(uint32_t inc, uint64_t seq) const {
    Msg m;
    memset(&m, 0, sizeof(m));
    m.kind = 1;
    m.q = req(inc, seq, image);
    m.q.layoutHash = layout;
    m.fromInc = inc;
    return m;
  }
  // The ward dies and is restored (mirror on): every survivor holds it, the buddy's cell HELD of the dead incarnation;
  // what the dead process sent before it died is still read there (its STORE_REQs dropped); then PUBLISHED of the dead
  // incarnation until INJECTED, while the accepted REJOIN already makes the restored process's the known one. late: the
  // dead process's requests read only during PUBLISHED (parked; any seq); -1: a random number of them.
  void wardDiesAndIsRestored(int late = -1) {
    st.wardDeaths++;
    const uint32_t dead = wardInc;
    b.holdCell = gdakiHoldPack(GDAKI_HOLD_HELD, dead);
    wardInc++;  // from here on the dead process is not the ward's
    while (!u2b.empty() && b.up) buddyStep();  // what it sent before it died is still read
    u2b.clear();
    b2u.clear();
    armed = -1;  // the restored rank is armed again only at its own next stable checkpoint (P5)
    b.holdCell = gdakiHoldPack(GDAKI_HOLD_PUBLISHED, dead);
    b.knownWardInc = wardInc;  // the buddy accepted its REJOIN
    injectedPending = true;
    const int n = late >= 0 ? late : (int)(rng() % 3);
    for (int k = 0; k < n; k++) u2b.push_back(request(dead, 1 + rng() % 6));
    u = gdakiStoreUp();
    upGen = 0;
    phase = 0;
  }
  // INJECTED of the restored incarnation reaches the buddy: PUBLISHED(i) -> OFF(i + 1) (gdakiHoldInjectedAction)
  void injected() {
    if (!injectedPending) return;
    injectedPending = false;
    st.injected++;
    if (gdakiHoldStateOf(b.holdCell) == GDAKI_HOLD_PUBLISHED && gdakiHoldIncOf(b.holdCell) + 1u == wardInc)
      b.holdCell = gdakiHoldPack(GDAKI_HOLD_OFF, wardInc);
  }
  void step() {
    now += std::uniform_real_distribution<double>(0, 400)(rng);
    if (injectedPending && rng() % 6 == 0) {
      injected();
      check();
      return;
    }
    const int e = (int)(rng() % 100);
    if (e < 20) wardRequest();
    else if (e < 42) buddyStep();
    else if (e < 60) wardAck();
    else if (e < 92) wardCheckpoint();
    else if (failures && e < 94) {
      if (b.up) buddyDies();
      else buddyRestored();
    } else if (failures && e < 95) {
      if (b.up) wardDiesAndIsRestored();
    } else if (failures && e < 97) {
      st.layoutChanges++;
      image += (rng() % 2 ? 4096 : 0) + (rng() % 3 == 0 ? 8 * MiB : 0);
      if (image > 60 * MiB) image = 30 * MiB;
      layout = rng();
    } else if (!b.up && !failures) {
      buddyRestored();
    }
    check();
  }
};
}  // namespace model
static void testModel() {
  model::Stats total;
  long notReadyAtEnd = 0, runs = 0;
  for (uint64_t seed = 1; seed <= 200; seed++) {
    model::World w(seed * 0x9e3779b97f4a7c15ull);
    for (int i = 0; i < 2000; i++) w.step();
    // the failures stop: the store gets ready again and checkpoints become stable, none refused by the buddy
    w.failures = false;
    if (!w.b.up) w.buddyRestored();
    const long stablesBefore = w.st.stables, refusedBefore = w.st.stableRefused;
    for (int i = 0; i < 2000; i++) w.step();
    CHECK(w.st.stableRefused == refusedBefore);
    if (!w.u.readyNow() && w.u.ackImage != w.image) w.step();
    runs++;
    if (w.st.stables == stablesBefore) notReadyAtEnd++;
    CHECK(w.st.stables > stablesBefore);
    total.requests += w.st.requests;
    total.acks += w.st.acks;
    total.refused += w.st.refused;
    total.writes += w.st.writes;
    total.writeFails += w.st.writeFails;
    total.stables += w.st.stables;
    total.stableRefused += w.st.stableRefused;
    total.buddyDeaths += w.st.buddyDeaths;
    total.wardDeaths += w.st.wardDeaths;
    total.layoutChanges += w.st.layoutChanges;
    total.readyAgain += w.st.readyAgain;
    total.checks += w.st.checks;
    total.stableLost += w.st.stableLost;
    total.socketRequests += w.st.socketRequests;
    total.dropped += w.st.dropped;
    total.servedHeld += w.st.servedHeld;
    total.injected += w.st.injected;
  }
  printf("model: %ld runs; requests %ld (after a socket reinstall %ld), answers %ld (refused %ld), WRITEs %ld ok / %ld "
         "failed, stable %ld (refused %ld, lost on the socket %ld), buddy deaths %ld, ward deaths %ld, layout changes %ld, "
         "ready (again) %ld, invariant checks %ld, runs without a stable checkpoint after the failures stopped %ld; "
         "requests of a held ward dropped %ld, served while held %ld, INJECTED %ld\n",
         runs, total.requests, total.socketRequests, total.acks, total.refused, total.writes, total.writeFails,
         total.stables, total.stableRefused, total.stableLost, total.buddyDeaths, total.wardDeaths, total.layoutChanges,
         total.readyAgain, total.checks, notReadyAtEnd, total.dropped, total.servedHeld, total.injected);
  CHECK(total.stables > 0 && total.writeFails > 0 && total.stableRefused >= 0 && total.buddyDeaths > 0 &&
        total.refused > 0 && total.layoutChanges > 0 && total.stableLost > 0 && total.socketRequests > 0);
  CHECK(total.dropped > 0 && total.servedHeld > 0 && total.injected > 0);
}
// The caller's case of pilot 1's defect A (2026-10-15), as a fixed sequence on the model: the ward of incarnation i is
// ready, a request of it is still on the socket when it dies (HELD(i): dropped), the restore leaves the cell PUBLISHED(i)
// with i + 1 known, two late requests of the dead process (seq 1 and a later one) and the restored process's first
// request STORE_REQ(i + 1, seq 1) arrive before INJECTED: the late ones are dropped, the restored one is served and its
// store is ready while the cell is still PUBLISHED(i). The pre-fix caller must drop the restored one too (no answer, not
// ready before INJECTED): else this sequence would not see the defect.
static void testDropWindow() {
  int preFixMissed = 0;
  for (uint32_t i = 0; i < 4; i++) {
    for (int preFix = 0; preFix < 2; preFix++) {
      model::World w(0x5eedull + i);
      w.failures = false;
      w.preFixCaller = preFix == 1;
      w.wardInc = i;
      w.b.knownWardInc = i;
      w.b.holdCell = gdakiHoldPack(GDAKI_HOLD_ARMED, i);
      w.wardRequest();
      w.buddyStep();
      w.wardAck();
      CHECK(w.u.readyNow() && w.b.rec.served && w.b.rec.inc == i && w.b.rec.seq == 1);
      w.u2b.push_back(w.request(i, 2));  // the dead process's request still on the socket
      w.wardDiesAndIsRestored(0);
      CHECK(w.st.dropped == 1 && w.b.rec.inc == i && w.b.rec.seq == 1 && w.b2u.empty());
      CHECK(gdakiHoldStateOf(w.b.holdCell) == GDAKI_HOLD_PUBLISHED && gdakiHoldIncOf(w.b.holdCell) == i &&
            w.b.knownWardInc == i + 1 && w.wardInc == i + 1);
      w.u2b.push_back(w.request(i, 1));
      w.u2b.push_back(w.request(i, 5));
      w.wardRequest();  // the restored process's first request, right after its Resume
      CHECK(w.u2b.size() == 3 && w.u2b.back().q.incarnation == i + 1 && w.u2b.back().q.seq == 1);
      for (int k = 0; k < 3; k++) w.buddyStep();
      w.wardAck();
      const bool stillPublished = gdakiHoldStateOf(w.b.holdCell) == GDAKI_HOLD_PUBLISHED;
      if (!w.preFixCaller) {
        CHECK(w.st.dropped == 3 && w.st.servedHeld == 1);
        CHECK(stillPublished && w.u.readyNow() && w.b.rec.inc == i + 1 && w.b.rec.seq == 1);
        w.injected();
        CHECK(gdakiHoldStateOf(w.b.holdCell) == GDAKI_HOLD_OFF && gdakiHoldIncOf(w.b.holdCell) == i + 1);
        CHECK(w.u.readyNow());
      } else if (stillPublished && !w.u.readyNow() && w.st.dropped == 4 && w.b.rec.inc == i) {
        preFixMissed++;  // the defect: the restored process's request dropped without an answer during PUBLISHED
      }
    }
  }
  printf("drop window: the pre-fix caller dropped the restored process's first request in %d of 4 sequences\n",
         preFixMissed);
  CHECK(preFixMissed == 4);
}
// The same divergence without the two rules (no request after a socket reinstall, no view from the answer): the model's
// invariant must catch it, else the test above proves nothing about them.
static void testModelWithoutSocketRule() {
  long violations = 0;
  for (uint64_t seed = 1; seed <= 40; seed++) {
    model::World w(seed * 0x9e3779b97f4a7c15ull);
    for (int i = 0; i < 2000; i++) {
      w.now += 100;
      const int e = (int)(w.rng() % 100);
      if (e < 30) {  // a request only for the reasons other than the socket (the view from the answer is not taken)
        if (w.b.up && w.u.nextReq(w.now, w.phase == 0, w.b.procInc, false) != GDAKI_STORE_N_NONE) {
          w.u.begin();
          w.upGen = 0;
          const uint64_t seq = w.u.seq + 1;
          struct gdakiStoreReq q;
          memset(&q, 0, sizeof(q));
          q.version = GDAKI_MI_WIRE_VERSION;
          q.incarnation = w.wardInc;
          q.seq = seq;
          q.imageBytes = w.image;
          q.slotBytes = gdakiStoreSlotBytes(w.image);
          q.layoutHash = w.layout;
          q.up = ep(0x100 + (uint32_t)seq);
          w.u.sent(true, seq, w.now, q.imageBytes, q.layoutHash, q.slotBytes, w.b.procInc);
          model::Msg m;
          memset(&m, 0, sizeof(m));
          m.kind = 1;
          m.q = q;
          m.fromInc = w.wardInc;
          w.u2b.push_back(m);
        }
      } else if (e < 50) {
        w.buddyStep();
      } else if (e < 65) {
        if (!w.b2u.empty()) {
          const model::Ans a = w.b2u.front();
          w.b2u.pop_front();
          if (w.u.onAck(a.a, a.a.seq, w.now) == GDAKI_STORE_A_OK) {
            w.u.connected(true, w.now);
            w.upGen = a.a.gen;
          }
        }
      } else {
        // the checkpoint's steps as in the model, but a CKPT_STABLE lost on the socket moves only the ward's view
        if (w.phase == 0) {
          w.u.wantValid = true;
          w.u.wantImage = w.image;
          w.u.wantLayout = w.layout;
          if (!w.u.readyNow()) continue;
          (void)w.u.beginWrite(w.image, w.layout);
          w.ck = w.nextCk++;
          w.wSlot = w.u.recvSlot();
          w.wGen = w.u.gen;
          w.wImage = w.image;
          w.wLayout = w.layout;
          w.wMr = (int)w.u.rkey - 1;
          if (w.upGen == w.wGen && w.b.qpGen == w.wGen && w.wMr >= 0 && w.wMr < (int)w.mrs.size()) {
            w.mrs[(size_t)w.wMr].ckpt[w.wSlot] = (int64_t)w.ck;
            w.mrs[(size_t)w.wMr].complete[w.wSlot] = false;
          }
          w.phase = 1;
        } else if (w.phase == 1) {
          const bool ok = w.upGen == w.wGen && w.b.qpGen == w.wGen && w.wMr >= 0;
          if (ok) w.mrs[(size_t)w.wMr].complete[w.wSlot] = true;
          w.u.endWrite(ok);
          w.phase = ok ? 2 : 0;
        } else {
          w.phase = 0;
          if (w.p(0.1)) {  // lost on the socket
            w.u.stableSent(w.wSlot, w.wGen);
            continue;
          }
          model::Msg m;
          memset(&m, 0, sizeof(m));
          m.kind = 2;
          m.ckpt = w.ck;
          m.s = gdakiStoreStableOf(w.wSlot, w.wGen, w.wImage, w.wLayout, 64);
          m.fromInc = w.wardInc;
          w.u2b.push_back(m);
          w.u.stableSent(w.wSlot, w.wGen);
        }
      }
      // the invariant by hand (no CHECK: this run is expected to break it)
      if (w.armed >= 0 && w.b.rec.haveStable) {
        const int id = (int)gdakiStoreWardStableRkey(w.b.rec) - 1;
        if (id >= 0 && id < (int)w.mrs.size()) {
          const model::Mem& mm = w.mrs[(size_t)id];
          if (!(mm.ckpt[w.b.rec.stableSlot & 1] == w.armed && mm.complete[w.b.rec.stableSlot & 1])) violations++;
        }
      }
    }
  }
  printf("model without the socket rule: %ld states in which the buddy's stable slot no longer held the armed checkpoint\n",
         violations);
  CHECK(violations > 0);
}

// ---- 7. the TCP path's base (mirror off; 9.6) on gin-restore's buddy store ----
namespace tcp {
static const uint64_t kBlock = GDAKI_CKPT_BLOCK;
struct Result {
  long uploads = 0, refusedBase = 0, maxRefusedInARow = 0, stable = 0, fullAfterFailure = 0, failures = 0;
};
// fixed: this branch's rule (gdakiStoreTcpBaseAfterUpload at every end, RESTORED of the buddy clears); else v1's
static Result run(uint64_t seed, bool fixed) {
  std::mt19937_64 rng(seed);
  auto p = [&](double x) { return std::uniform_real_distribution<double>(0, 1)(rng) < x; };
  Result res;
  struct gdakiCkptStore store;  // the buddy's (v1, gin-restore's own code)
  bool haveBase = false;
  uint64_t baseCkpt = 0;
  std::vector<uint64_t> baseHashes, curHashes;
  const uint64_t nb = 2, bytes = nb * kBlock;
  std::vector<uint8_t> image((size_t)bytes, 0), blk((size_t)kBlock, 0);
  long inARow = 0;
  bool failedBefore = false;
  struct gdakiCkptHdr* h = new gdakiCkptHdr();
  for (uint64_t k = 1; k <= 250; k++) {
    for (uint64_t i = 0; i < nb; i++)  // the image changes a little every checkpoint
      if (p(0.4)) image[(size_t)(i * kBlock + (rng() % kBlock))] ^= (uint8_t)(1 + rng() % 255);
    std::vector<uint64_t> hashes((size_t)nb);
    for (uint64_t i = 0; i < nb; i++) hashes[(size_t)i] = gdakiCkptHash(&image[(size_t)(i * kBlock)], kBlock, GDAKI_CKPT_HASH_SEED);
    const std::vector<uint64_t> changed = gdakiCkptChanged(baseHashes, haveBase, hashes);
    memset(h, 0, sizeof(*h));
    h->magic = GDAKI_CKPT_MAGIC;
    h->version = GDAKI_CKPT_VERSION;
    h->ckpt = k;
    h->blockBytes = GDAKI_CKPT_BLOCK;
    h->imageBytes = bytes;
    h->baseCkpt = (haveBase && baseHashes.size() == hashes.size()) ? baseCkpt : ~0ULL;
    h->nChanged = changed.size();
    if (failedBefore && h->baseCkpt == ~0ULL) res.fullAfterFailure++;
    res.uploads++;
    // the upload's end, as the uploader sees it
    enum { OK, REFUSED_ACK, NO_ACK, NO_DIAL } end;
    const char* why = "";
    bool refused = false;
    if (p(0.05)) {
      end = NO_DIAL;  // the buddy could not be reached, the D2H failed, ...: nothing reached the buddy
    } else if (!store.begin(*h, &why)) {
      res.refusedBase++;
      refused = true;
      // the buddy refuses the header; for a large image it closes before the uploader reads its ack (9.6, 8734-8737)
      end = p(0.7) ? NO_ACK : REFUSED_ACK;
    } else {
      bool okb = true;
      for (uint64_t c : changed) {
        memcpy(blk.data(), &image[(size_t)(c * kBlock)], kBlock);
        okb = okb && store.block(c, blk.data(), kBlock);
      }
      CHECK(okb);
      store.finish(nullptr, 0);
      end = p(0.05) ? NO_ACK : OK;  // the ack may be lost even when the buddy holds the image
    }
    inARow = refused ? inARow + 1 : 0;
    res.maxRefusedInARow = std::max(res.maxRefusedInARow, inARow);
    const bool ok = end == OK;
    if (fixed) {
      haveBase = gdakiStoreTcpBaseAfterUpload(haveBase, ok);
    } else if (end == REFUSED_ACK) {
      haveBase = false;  // v1: only a refusing ack clears the base (8738-8742)
    }
    failedBefore = !ok;
    if (!ok) {
      res.failures++;
    } else {  // CKPT_STABLE (8552: the base set whatever the buddy did with it)
      curHashes = hashes;
      if (store.markStable(k)) res.stable++;
      haveBase = true;
      baseCkpt = k;
      baseHashes = curHashes;
    }
    if (p(0.03)) {  // the buddy dies and is restored: its new process holds nothing
      store = gdakiCkptStore();
      if (fixed) haveBase = false;  // gdakiStoreOnBuddyRestored (TCP path)
      failedBefore = true;
    }
  }
  delete h;
  return res;
}
}  // namespace tcp
static void testTcpBase() {
  // the rule itself
  CHECK(gdakiStoreTcpBaseAfterUpload(true, true));
  CHECK(!gdakiStoreTcpBaseAfterUpload(true, false));
  CHECK(!gdakiStoreTcpBaseAfterUpload(false, true));
  CHECK(!gdakiStoreTcpBaseAfterUpload(false, false));
  long v1Stuck = 0, fixStuck = 0, v1Max = 0, fixMax = 0, fixFull = 0, fixFail = 0, v1Stable = 0, fixStable = 0;
  for (uint64_t seed = 1; seed <= 120; seed++) {
    const tcp::Result a = tcp::run(seed, false), b = tcp::run(seed, true);
    v1Max = std::max(v1Max, a.maxRefusedInARow);
    fixMax = std::max(fixMax, b.maxRefusedInARow);
    v1Stuck += a.maxRefusedInARow >= 3;
    fixStuck += b.maxRefusedInARow >= 3;
    fixFull += b.fullAfterFailure;
    fixFail += b.failures;
    v1Stable += a.stable;
    fixStable += b.stable;
    // with the rule the buddy never refuses an upload for its base (after any failed upload and after the buddy's
    // restore the next one is whole)
    CHECK(b.refusedBase == 0);
  }
  printf("tcp base (9.6): v1 rule: %ld of 120 runs refused >= 3 uploads in a row (max %ld), %ld stable; this branch's rule: "
         "%ld runs (max %ld), %ld stable, %ld whole uploads after %ld failed ones\n",
         v1Stuck, v1Max, v1Stable, fixStuck, fixMax, fixStable, fixFull, fixFail);
  CHECK(v1Stuck > 0);  // the gap 9.6 describes is real in the model of gin-restore's rule
  CHECK(fixStuck == 0);
  CHECK(fixStable > v1Stable);
}

// ---- 8. mirror off: gin-restore's buddy store as before ----
static void testV1Store() {
  struct gdakiCkptStore st;
  struct gdakiCkptHdr* h = new gdakiCkptHdr();
  memset(h, 0, sizeof(*h));
  h->magic = GDAKI_CKPT_MAGIC;
  h->version = GDAKI_CKPT_VERSION;
  h->blockBytes = GDAKI_CKPT_BLOCK;
  h->ckpt = 5;
  h->imageBytes = 3 * GDAKI_CKPT_BLOCK + 10;
  h->baseCkpt = ~0ULL;
  h->nChanged = gdakiCkptNBlocks(h->imageBytes);
  const char* why = "";
  CHECK(st.begin(*h, &why));
  std::vector<uint8_t> b(GDAKI_CKPT_BLOCK, 7);
  for (uint64_t i = 0; i < h->nChanged; i++) CHECK(st.block(i, b.data(), gdakiCkptBlockLen(i, h->imageBytes)));
  st.finish(b.data(), 3);
  CHECK(!st.markStable(4) && st.markStable(5) && st.haveStable && st.stable.ckpt == 5);
  h->ckpt = 6;
  h->baseCkpt = 4;  // not the stable image
  h->nChanged = 1;
  CHECK(!st.begin(*h, &why) && strstr(why, "base") != nullptr);
  h->baseCkpt = 5;
  CHECK(st.begin(*h, &why));
  h->baseCkpt = ~0ULL;  // without a base every block must come
  h->nChanged = 1;
  CHECK(!st.begin(*h, &why));
  delete h;
}

int main() {
  testSlots();
  testStable();
  testRecords();
  testUploader();
  testWard();
  testModel();
  testModelWithoutSocketRule();
  testDropWindow();
  testTcpBase();
  testV1Store();
  printf("mi_unit_store: %ld checks, %ld failed\n", gChecks, gFailed);
  return gFailed == 0 ? 0 : 1;
}
