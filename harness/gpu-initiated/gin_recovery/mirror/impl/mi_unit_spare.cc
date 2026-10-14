// mi_unit_spare.cc - CPU unit test of the spare branch's pure functions (gin-mirror, impl/PARALLEL.md row
// exp/gin-mirror-spare; EXPERIMENT.md 9.4). build_mi.sh `unit` (BR=spare) cuts the region between the two
// "gin-mirror (spare): pure" markers of gin_host_gdaki.cc into mi_pure_spare.inc and compiles it here against the six
// shared headers of impl/ (as build_mi.sh `api` compiles them together), so the test runs the library's own text. No
// NCCL, no CUDA, no network.
// Coverage (the five the task names, then the rest of the region):
//   1. the activation blob v2: encode and decode, the header's sanity, gdakiMiActCheck on what was decoded, and the FETCH
//      buffer's layout against the check's bound;
//   2. the address table: gdakiMiAddrRule (keep, take, warn, bad), the restored rank's own entry, a table applied to a
//      four-rank job with one survivor restored before;
//   3. the QPN comparisons by incarnation (survivor and spare sides; which QPN the spare connects with), and that the
//      mirror-off answers are v1's;
//   4. the rkey list merge with the pool (keep, warn, take, pool, coverage);
//   5. the order on the activation connection (READY before the READs, FETCH before the first REJOIN);
//   then HOLDING's payload, the extents and the drain set, the drain verdicts (the self loop modulo 2^24 from its connect
//   base), the export v2's entry tags and its stream.
// The "mirror off = v1" cases below exercise the pure helpers only; the library's call sites branch on gdakiMiOn before
// they reach them (gdakiRsRejoinAccept, gdakiRsSpareRun), so they do not show that the call sites are v1's (the review
// read those; the spare branch's notes are in EXPERIMENT.md section 12 since the integration).
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include <algorithm>
#include <atomic>

// What the six headers need from nccl.h (as build_mi.sh `api`'s headers.cc).
typedef enum { ncclSuccess = 0, ncclSystemError = 2, ncclInternalError = 3, ncclInvalidUsage = 5 } ncclResult_t;
typedef struct {
  unsigned int magic, nqp, qpn[64], remoteQpn[64], sqPsn[64];
  unsigned long long epochWqes[64];
} ncclGinRecoverToken_t;
#define GDAKI_MI_API_NO_ENTRY_DECLS
#define GDAKI_HOLD_API_NO_ENTRY_DECLS
#include "rs_hold_api.h"
#include "rs_mirror_api.h"
#include "rs_log_api.h"
#include "rs_ckpt_api.h"
#include "rs_store_api.h"
#include "rs_spare_api.h"
// The log entry's kinds and decoders: copies of gin_gdaki_device_host_common.h (rs_layer.diff 1216-1250), which the
// region uses and which the six headers do not carry.
#define NCCL_GIN_RS_LOG_PUT 1u
#define NCCL_GIN_RS_LOG_PUTVALUE 2u
#define NCCL_GIN_RS_LOG_SIGNAL 3u
#define NCCL_GIN_RS_LOGF_SIGNAL 0x01u
static inline uint32_t ncclGinRsEntryKind(uint32_t qpKf) { return (qpKf >> 24) & 3u; }
static inline uint32_t ncclGinRsEntryFlags(uint32_t qpKf) { return qpKf >> 26; }
static inline uint32_t ncclGinRsQpKf(uint32_t qp, uint32_t kind, uint32_t flags) {
  return (qp & 0xffffffu) | ((kind & 3u) << 24) | (flags << 26);
}

#include "mi_pure_spare.inc"

static int nChecks = 0, nFail = 0;
#define CHECK(c) do { nChecks++; if (!(c)) { nFail++; fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)
static bool has(const char* s, const char* sub) { return strstr(s, sub) != nullptr; }

// A blob as a buddy of rank d = 2 in a 4-rank job sends it: checkpoint 40, its store slot, two extents.
static void makeBlob(struct gdakiMiActHdr* h, std::vector<struct gdakiMiActAddr>* addr, std::vector<struct gdakiMiActExt>* ext) {
  const int n = 4, d = 2;
  memset(h, 0, sizeof(*h));
  h->magic = GDAKI_MI_ACTB_MAGIC;
  h->version = GDAKI_MI_WIRE_VERSION;
  h->rank = d;
  h->incarnation = 1;
  h->nonce = 0x1234567890abcdefull;
  h->ckpt = 40;
  h->nranks = h->nAddr = n;
  h->flags = GDAKI_MI_ACTB_F_STORE | GDAKI_MI_ACTB_F_POOL;
  h->storeRkey = 0x1111;
  h->storeSlot = 1;
  h->imageBytes = 30u << 20;
  h->blobBytes = 4096;
  h->storeOff = gdakiStoreSlotBytes(h->imageBytes);
  h->usedBytes = gdakiStoreUsedBytes(h->imageBytes, h->blobBytes);
  h->layoutHash = 77;
  h->poolRkey = 0x2222;
  h->laneBytes = 1u << 20;
  h->slots = 3;
  h->wardIdx = ncclGinMiWardIdx(d, n);
  h->fetch.qpn = 0x99;
  addr->assign(n, gdakiMiActAddr());
  for (int q = 0; q < n; q++) {
    struct gdakiMiActAddr& e = (*addr)[(size_t)q];
    memset(&e, 0, sizeof(e));
    e.rank = q == d ? -1 : q;
    if (q != d) {
      e.incarnation = q == 1 ? 1u : 0u;
      e.listenAddr[0] = 2;  // AF_INET's family byte, then a port and an address that differ per rank
      e.listenAddr[2] = (uint8_t)(10 + q);
      e.listenAddr[4] = (uint8_t)q;
    }
  }
  ext->clear();
  struct gdakiMiActExt e;
  memset(&e, 0, sizeof(e));
  e.seg = 7; e.sender = 0; e.lane = (uint32_t)ncclGinMiLaneOf(0, d); e.fill = 4096; e.closedAt = 45;
  e.poolOff = ncclGinMiLaneOff(h->wardIdx, e.seg % h->slots, (int)e.lane, n, h->slots, h->laneBytes);
  ext->push_back(e);
  e.seg = 8; e.sender = 3; e.lane = (uint32_t)ncclGinMiLaneOf(3, d); e.fill = 100; e.closedAt = GDAKI_MI_OPEN;
  e.poolOff = ncclGinMiLaneOff(h->wardIdx, e.seg % h->slots, (int)e.lane, n, h->slots, h->laneBytes);
  ext->push_back(e);
  h->nExt = (uint32_t)ext->size();
}

// ---- 1. the activation blob v2 ----
static void testBlob() {
  struct gdakiMiActHdr h, h2;
  std::vector<struct gdakiMiActAddr> addr, addr2;
  std::vector<struct gdakiMiActExt> ext, ext2;
  makeBlob(&h, &addr, &ext);
  std::vector<uint8_t> bytes;
  CHECK(gdakiMiActBlobEncode(h, addr, ext, &bytes));
  CHECK(bytes.size() == sizeof(h) + 4 * sizeof(struct gdakiMiActAddr) + 2 * sizeof(struct gdakiMiActExt));
  CHECK(bytes.size() == sizeof(h) + gdakiMiActRestBytes(h));
  CHECK(gdakiMiActBlobDecode(bytes.data(), bytes.size(), 4, &h2, &addr2, &ext2) == 0);
  CHECK(memcmp(&h, &h2, sizeof(h)) == 0);
  CHECK(addr2.size() == 4 && memcmp(addr.data(), addr2.data(), 4 * sizeof(addr[0])) == 0);
  CHECK(ext2.size() == 2 && memcmp(ext.data(), ext2.data(), 2 * sizeof(ext[0])) == 0);
  // the counts must be the lists'
  struct gdakiMiActHdr bad = h;
  bad.nExt = 3;
  CHECK(!gdakiMiActBlobEncode(bad, addr, ext, &bytes));
  CHECK(gdakiMiActBlobEncode(h, addr, ext, &bytes));
  // cut, longer, another job size, a damaged magic or version, too many extents or ranks
  CHECK(gdakiMiActBlobDecode(bytes.data(), bytes.size() - 1, 4, &h2, &addr2, &ext2) == 3);
  CHECK(gdakiMiActBlobDecode(bytes.data(), sizeof(h) - 1, 4, &h2, &addr2, &ext2) == 3);
  std::vector<uint8_t> longer = bytes;
  longer.push_back(0);
  CHECK(gdakiMiActBlobDecode(longer.data(), longer.size(), 4, &h2, &addr2, &ext2) == 3);
  CHECK(gdakiMiActBlobDecode(bytes.data(), bytes.size(), 5, &h2, &addr2, &ext2) == 3);
  CHECK(gdakiMiActBlobDecode(bytes.data(), bytes.size(), 0, &h2, &addr2, &ext2) == 3);
  std::vector<uint8_t> dam = bytes;
  dam[0] ^= 1;
  CHECK(gdakiMiActBlobDecode(dam.data(), dam.size(), 4, &h2, &addr2, &ext2) == 1);
  bad = h;
  bad.version = 2;
  CHECK(gdakiMiActHdrSane(bad, 4) == 1);
  bad = h;
  bad.nExt = GDAKI_MI_ACT_MAX_EXT + 1;
  CHECK(gdakiMiActHdrSane(bad, 4) == 3);
  bad = h;
  bad.nAddr = 3;
  CHECK(gdakiMiActHdrSane(bad, 4) == 3);
  bad = h;
  bad.nranks = bad.nAddr = GDAKI_MI_ACT_MAX_ADDR + 1;
  CHECK(gdakiMiActHdrSane(bad, (int)bad.nranks) == 3);
  CHECK(gdakiMiActHdrSane(h, 4) == 0);
  // the spare's check on what it decoded, and the FETCH buffer's layout against that check's bound
  CHECK(gdakiMiActBlobDecode(bytes.data(), bytes.size(), 4, &h2, &addr2, &ext2) == 0);  // (the refusals above overwrote h2)
  uint64_t off[2];
  const uint64_t total = gdakiMiFetchLayout(h.usedBytes, ext2.data(), 2, off);
  CHECK(off[0] == gdakiStoreRound4k(h.usedBytes) && off[0] % 4096 == 0 && off[1] == off[0] + 4096);
  CHECK(total == off[1] + 128 && total % 64 == 0);  // 100 bytes take 128
  CHECK(off[0] >= h.usedBytes && off[1] >= off[0] + ext2[0].fill);
  CHECK(gdakiMiActCheck(h2, ext2.data(), 2, 2, 1, h.nonce, 40, total) == 0);
  CHECK(gdakiMiActCheck(h2, ext2.data(), 2, 2, 1, h.nonce, 40, total - 1) == 7);    // the buffer is one byte short
  CHECK(gdakiMiActCheck(h2, ext2.data(), 2, 2, 2, h.nonce, 40, total) == 2);        // another incarnation
  CHECK(gdakiMiActCheck(h2, ext2.data(), 2, 2, 1, h.nonce, 41, total) == 2);        // another checkpoint
  CHECK(gdakiMiActCheck(h2, ext2.data(), 2, 2, 1, h.nonce ^ 1, 40, total) == 2);    // another context
  std::vector<struct gdakiMiActExt> e3 = ext2;
  e3[1].sender = 2;  // the restored rank never sends to itself
  CHECK(gdakiMiActCheck(h2, e3.data(), 2, 2, 1, h.nonce, 40, total) == 5);
  e3 = ext2;
  e3[0].closedAt = 40;  // closed by the checkpoint itself: in the image
  CHECK(gdakiMiActCheck(h2, e3.data(), 2, 2, 1, h.nonce, 40, total) == 6);
  e3 = ext2;
  e3[0].fill = h.laneBytes + 1;
  CHECK(gdakiMiActCheck(h2, e3.data(), 2, 2, 1, h.nonce, 40, ~0ull) == 5);
  bad = h2;
  bad.usedBytes += 1;
  CHECK(gdakiMiActCheck(bad, ext2.data(), 2, 2, 1, h.nonce, 40, total) == 4);
  bad = h2;
  bad.flags = GDAKI_MI_ACTB_F_POOL;
  CHECK(gdakiMiActCheck(bad, ext2.data(), 2, 2, 1, h.nonce, 40, total) == 3);
  // sizes no sum may wrap with: the slot or a lane past the buffer, an image past 2^40 (REFUSED 7 before the check adds)
  CHECK(gdakiMiActFits(h2, total) == 0);
  bad = h2;
  bad.laneBytes = ~0ull - 10;  // with fill near 2^64 the check's sum would wrap under the buffer
  CHECK(gdakiMiActFits(bad, total) == 7);
  bad = h2;
  bad.usedBytes = total + 1;
  CHECK(gdakiMiActFits(bad, total) == 7);
  bad = h2;
  bad.imageBytes = (1ull << 40) + 1;
  CHECK(gdakiMiActFits(bad, ~0ull >> 14) == 7);
  // the extent limit: GDAKI_MI_ACT_MAX_EXT pass, one more is refused (3) by the header and by the check
  bad = h2;
  bad.nExt = GDAKI_MI_ACT_MAX_EXT;
  CHECK(gdakiMiActHdrSane(bad, 4) == 0);
  std::vector<struct gdakiMiActExt> many(GDAKI_MI_ACT_MAX_EXT + 1, ext2[1]);
  CHECK(gdakiMiActCheck(bad, many.data(), GDAKI_MI_ACT_MAX_EXT, 2, 1, h.nonce, 40, ~0ull >> 14) == 0);
  bad.nExt = GDAKI_MI_ACT_MAX_EXT + 1;
  CHECK(gdakiMiActCheck(bad, many.data(), GDAKI_MI_ACT_MAX_EXT + 1, 2, 1, h.nonce, 40, ~0ull >> 14) == 3);
  // no extents: only the slot
  struct gdakiMiActHdr h0 = h;
  h0.nExt = 0;
  CHECK(gdakiMiFetchLayout(h0.usedBytes, nullptr, 0, off) == gdakiStoreRound4k(h0.usedBytes));
  CHECK(gdakiMiActCheck(h0, nullptr, 0, 2, 1, h.nonce, 40, gdakiStoreRound4k(h0.usedBytes)) == 0);
  // the extents' pool offsets are the device's lanes: inside the pool, one lane per (ward, slot, sender)
  const uint64_t pool = ncclGinMiPoolBytes(1, h.slots, 4, h.laneBytes);
  for (const auto& e : ext2) CHECK(e.poolOff + e.fill <= pool && e.poolOff % h.laneBytes == 0);
  CHECK(ext2[0].poolOff != ext2[1].poolOff);
}

// ---- 2. the address table ----
static void testAddr() {
  struct gdakiMiActHdr h;
  std::vector<struct gdakiMiActAddr> addr;
  std::vector<struct gdakiMiActExt> ext;
  makeBlob(&h, &addr, &ext);
  const size_t A = 28;  // sizeof(union ncclSocketAddress)
  uint8_t rec[32];
  // incarnation 0, the same address: keep (no line)
  memcpy(rec, addr[0].listenAddr, sizeof(rec));
  CHECK(gdakiMiAddrRule(0, addr[0], rec, A) == GDAKI_MI_ADDR_KEEP);
  // incarnation 0, another address: the recorded one stays, a WARN only (gin-restore's decision letter for letter)
  rec[4] ^= 0x40;
  CHECK(gdakiMiAddrRule(0, addr[0], rec, A) == GDAKI_MI_ADDR_WARN);
  // a survivor restored before (incarnation 1): the table's address, also when it equals the recorded one
  memcpy(rec, addr[1].listenAddr, sizeof(rec));
  CHECK(gdakiMiAddrRule(1, addr[1], rec, A) == GDAKI_MI_ADDR_TAKE);
  rec[2] ^= 1;
  CHECK(gdakiMiAddrRule(1, addr[1], rec, A) == GDAKI_MI_ADDR_TAKE);
  // bad: the entry is another rank's, a restored survivor without an address, an impossible address length
  CHECK(gdakiMiAddrRule(3, addr[1], rec, A) == GDAKI_MI_ADDR_BAD);
  struct gdakiMiActAddr z = addr[1];
  memset(z.listenAddr, 0, sizeof(z.listenAddr));
  CHECK(gdakiMiAddrRule(1, z, rec, A) == GDAKI_MI_ADDR_BAD);
  z.incarnation = 0;  // incarnation 0 with no address in the table: the recorded address is kept (WARN)
  CHECK(gdakiMiAddrRule(1, z, rec, A) == GDAKI_MI_ADDR_WARN);
  CHECK(gdakiMiAddrRule(1, addr[1], rec, 0) == GDAKI_MI_ADDR_BAD);
  CHECK(gdakiMiAddrRule(1, addr[1], rec, 33) == GDAKI_MI_ADDR_BAD);
  // the restored rank's own entry
  CHECK(gdakiMiAddrSelfOk(addr[2]));
  CHECK(!gdakiMiAddrSelfOk(addr[0]));
  z = addr[2];
  z.listenAddr[3] = 1;
  CHECK(!gdakiMiAddrSelfOk(z));
  // the table applied by the spare of rank 2 (its recorded addresses are the first incarnation's): rank 1 was restored
  // before and listens at a new address; ranks 0 and 3 are of incarnation 0, and rank 3's table address differs
  uint8_t pe[4][32];
  for (int q = 0; q < 4; q++) memcpy(pe[q], addr[(size_t)q].listenAddr, 32);
  pe[1][4] = 0x77;                // the transcript's address of rank 1 (its first incarnation)
  addr[3].listenAddr[5] = 0x55;   // the buddy's view of rank 3 differs (it should not; a WARN)
  int take = 0, warn = 0, keep = 0;
  for (int q = 0; q < 4; q++) {
    if (q == 2) continue;
    const int a = gdakiMiAddrRule(q, addr[(size_t)q], pe[q], A);
    if (a == GDAKI_MI_ADDR_TAKE) { memcpy(pe[q], addr[(size_t)q].listenAddr, A); take++; }
    if (a == GDAKI_MI_ADDR_WARN) warn++;
    if (a == GDAKI_MI_ADDR_KEEP) keep++;
  }
  CHECK(take == 1 && warn == 1 && keep == 1);
  CHECK(memcmp(pe[1], addr[1].listenAddr, A) == 0);  // dialled at its new address
  CHECK(pe[3][5] != 0x55);                           // the recorded address of rank 3 kept
}

// ---- 3. the QPN comparisons by incarnation ----
static void testQpn() {
  char why[192];
  // survivor side: how many leading QPNs of the REJOIN's view are compared
  CHECK(gdakiMiRejoinCmpCount(4, false, 0) == 4 && gdakiMiRejoinCmpCount(4, false, 3) == 4);  // mirror off: v1
  CHECK(gdakiMiRejoinCmpCount(5, true, 0) == 4);   // user QPs; the mirror QP (the last) has no recorded number
  CHECK(gdakiMiRejoinCmpCount(5, true, 1) == 0);   // this survivor was restored itself: the transcript is stale
  CHECK(gdakiMiRejoinCmpCount(0, true, 0) == 0);
  // spare side (TOKEN): 4 user QPs and the mirror QP
  const uint32_t rec[5] = {0x10, 0x11, 0x12, 0x13, 0};
  uint32_t tok[5] = {0x10, 0x11, 0x12, 0x13, 0x9a};
  CHECK(gdakiMiTokenQpnCheck(5, tok, rec, true, 0, why, sizeof(why)) && has(why, "4 of 5"));  // the mirror QPN is new
  tok[2] = 0x22;
  CHECK(!gdakiMiTokenQpnCheck(5, tok, rec, true, 0, why, sizeof(why)) && has(why, "QP 2"));   // a user QP of inc 0
  CHECK(gdakiMiTokenQpnCheck(5, tok, rec, true, 1, why, sizeof(why)) && has(why, "0 of 5"));  // a restored survivor
  // mirror off: every QPN compared at any incarnation (v1: a second restore of a mirror-off job keeps the old limit)
  tok[2] = 0x12;
  CHECK(!gdakiMiTokenQpnCheck(5, tok, rec, false, 0, why, sizeof(why)));  // the last differs too
  const uint32_t tok4[4] = {0x10, 0x11, 0x12, 0x13};
  CHECK(gdakiMiTokenQpnCheck(4, tok4, rec, false, 0, why, sizeof(why)));
  const uint32_t tok4b[4] = {0x10, 0x11, 0x12, 0x14};
  CHECK(!gdakiMiTokenQpnCheck(4, tok4b, rec, false, 2, why, sizeof(why)));
  // which QPN the spare connects with: the token's for the mirror QP always, for every QP of a restored survivor
  CHECK(!gdakiMiQpnFromToken(0, 5, true, 0) && !gdakiMiQpnFromToken(3, 5, true, 0) && gdakiMiQpnFromToken(4, 5, true, 0));
  CHECK(gdakiMiQpnFromToken(0, 5, true, 2) && gdakiMiQpnFromToken(4, 5, true, 2));
  CHECK(!gdakiMiQpnFromToken(4, 5, false, 0) && !gdakiMiQpnFromToken(0, 5, false, 3));
  // the survivor's comparison as gdakiRsRejoinAccept makes it (the view's tail equalized past the count): a stale view of
  // the mirror QP is never a refusal, a stale user QP is one only at incarnation 0
  const uint32_t own[5] = {0x10, 0x11, 0x12, 0x13, 0x77};
  auto accept = [&](const uint32_t* view, uint32_t selfInc) {
    uint32_t v[5];
    memcpy(v, view, sizeof(v));
    for (int i = gdakiMiRejoinCmpCount(5, true, selfInc); i < 5; i++) v[i] = own[i];
    return memcmp(v, own, sizeof(v)) == 0;
  };
  const uint32_t view0[5] = {0x10, 0x11, 0x12, 0x13, 0};
  const uint32_t view1[5] = {0x10, 0x31, 0x12, 0x13, 0};
  CHECK(accept(view0, 0) && !accept(view1, 0) && accept(view1, 1));
}

// ---- 4. the rkey list merge with the pool ----
static void testRkeys() {
  char why[192];
  // what the spare replayed for survivor q: window 1, window 2, the signal and the counter tables
  const struct gdakiRsRkeyEntry rep[4] = {{GDAKI_RS_RKEY_WINDOW, 1, 0xa1, 0}, {GDAKI_RS_RKEY_WINDOW, 2, 0xa2, 0},
                                          {GDAKI_RS_RKEY_SIGNALS, 0, 0xb0, 0}, {GDAKI_RS_RKEY_COUNTERS, 0, 0xc0, 0}};
  // q's list in its STATE: window 2 differs, the pool is new
  const struct gdakiRsRkeyEntry list[5] = {{GDAKI_RS_RKEY_WINDOW, 1, 0xa1, 0}, {GDAKI_RS_RKEY_WINDOW, 2, 0xf2, 0},
                                           {GDAKI_RS_RKEY_SIGNALS, 0, 0xb0, 0}, {GDAKI_RS_RKEY_COUNTERS, 0, 0xc0, 0},
                                           {GDAKI_MI_RKEY_POOL, 0, 0xd0, 0}};
  std::vector<struct gdakiRsRkeyEntry> w;
  int warns = -1;
  uint32_t pool = 0;
  // incarnation 0: the replayed values stay (one WARN for window 2), only the pool is written
  CHECK(gdakiMiRkeyMerge(list, 5, 0, rep, 4, &w, &warns, &pool, why, sizeof(why)) == 0);
  CHECK(warns == 1 && pool == 0xd0 && w.size() == 1 && w[0].kind == GDAKI_MI_RKEY_POOL && w[0].rkeyBe == 0xd0);
  // a survivor restored before: every entry of its list is written
  CHECK(gdakiMiRkeyMerge(list, 5, 2, rep, 4, &w, &warns, &pool, why, sizeof(why)) == 0);
  CHECK(warns == 0 && w.size() == 5 && pool == 0xd0);
  // no pool in the list (the survivor keeps no ward): nothing for the pool, poolBe 0
  CHECK(gdakiMiRkeyMerge(list, 4, 2, rep, 4, &w, &warns, &pool, why, sizeof(why)) == 0 && pool == 0 && w.size() == 4);
  // coverage (the integration's one rule, as the dev branch's import): a replayed window missing from the list, a list
  // window with no slot here: a survivor restored before is refused, one of incarnation 0 is a WARN (replayed values kept)
  CHECK(gdakiMiRkeyMerge(list + 1, 4, 1, rep, 4, &w, &warns, &pool, why, sizeof(why)) == -1 && has(why, "missing"));
  CHECK(gdakiMiRkeyMerge(list + 1, 4, 0, rep, 4, &w, &warns, &pool, why, sizeof(why)) == 0 && warns == 2 &&
        w.size() == 1 && w[0].kind == GDAKI_MI_RKEY_POOL);
  const struct gdakiRsRkeyEntry extra[2] = {{GDAKI_RS_RKEY_WINDOW, 1, 0xa1, 0}, {GDAKI_RS_RKEY_WINDOW, 9, 0xa9, 0}};
  CHECK(gdakiMiRkeyMerge(extra, 2, 1, rep, 1, &w, &warns, &pool, why, sizeof(why)) == -1 && has(why, "no slot"));
  CHECK(gdakiMiRkeyMerge(extra, 2, 0, rep, 1, &w, &warns, &pool, why, sizeof(why)) == 0 && warns == 1 && w.empty());
  // an unknown kind is skipped
  const struct gdakiRsRkeyEntry odd[3] = {{GDAKI_RS_RKEY_WINDOW, 1, 0xa1, 0}, {GDAKI_RS_RKEY_WINDOW, 2, 0xa2, 0},
                                          {9, 0, 0xee, 0}};
  CHECK(gdakiMiRkeyMerge(odd, 3, 1, rep, 2, &w, &warns, &pool, why, sizeof(why)) == 0 && w.size() == 2);
  // the rule itself
  CHECK(gdakiMiRkeyRule(GDAKI_MI_RKEY_POOL, 0, false, 0, 5) == GDAKI_MI_RK_TAKE);
  CHECK(gdakiMiRkeyRule(GDAKI_RS_RKEY_SIGNALS, 0, true, 5, 5) == GDAKI_MI_RK_KEEP);
  CHECK(gdakiMiRkeyRule(GDAKI_RS_RKEY_SIGNALS, 0, true, 5, 6) == GDAKI_MI_RK_WARN);
  CHECK(gdakiMiRkeyRule(GDAKI_RS_RKEY_SIGNALS, 1, true, 5, 6) == GDAKI_MI_RK_TAKE);
  CHECK(gdakiMiRkeyRule(GDAKI_RS_RKEY_WINDOW, 1, false, 0, 6) == GDAKI_MI_RK_SKIP);
  CHECK(gdakiMiRkeyRule(0, 1, true, 0, 6) == GDAKI_MI_RK_SKIP);
  CHECK(GDAKI_MI_RKEY_POOL == 4u && sizeof(struct gdakiRsRkeyEntry) == 16);
}

// ---- 5. the order on the activation connection ----
static void testOrder() {
  int s = GDAKI_MI_AS_WAIT;
  CHECK(!gdakiMiRejoinAllowed(true, s));
  s = gdakiMiActStep(s, GDAKI_MI_AE_ACCEPT);
  CHECK(s == GDAKI_MI_AS_ACCEPTED && !gdakiMiRejoinAllowed(true, s));
  s = gdakiMiActStep(s, GDAKI_MI_AE_ANSWER);
  CHECK(s == GDAKI_MI_AS_ANSWERED);
  CHECK(gdakiMiActStep(s, GDAKI_MI_AE_READ) == GDAKI_MI_AS_FAIL);  // a READ before READY (the buddy's QP is not RTR yet)
  CHECK(gdakiMiActStep(s, GDAKI_MI_AE_DONE) == GDAKI_MI_AS_FAIL);
  s = gdakiMiActStep(s, GDAKI_MI_AE_READY);
  CHECK(s == GDAKI_MI_AS_READY && !gdakiMiRejoinAllowed(true, s));
  s = gdakiMiActStep(s, GDAKI_MI_AE_READ);
  CHECK(s == GDAKI_MI_AS_READ && !gdakiMiRejoinAllowed(true, s));  // READs done, DONE not sent: no REJOIN yet
  s = gdakiMiActStep(s, GDAKI_MI_AE_DONE);
  CHECK(s == GDAKI_MI_AS_DONE && gdakiMiRejoinAllowed(true, s));
  CHECK(gdakiMiActStep(s, GDAKI_MI_AE_ACCEPT) == GDAKI_MI_AS_FAIL);  // nothing after DONE
  CHECK(gdakiMiActStep(GDAKI_MI_AS_FAIL, GDAKI_MI_AE_ACCEPT) == GDAKI_MI_AS_FAIL);
  CHECK(gdakiMiActStep(GDAKI_MI_AS_WAIT, GDAKI_MI_AE_ANSWER) == GDAKI_MI_AS_FAIL);  // an endpoint before ACCEPTED
  CHECK(gdakiMiActStep(GDAKI_MI_AS_ACCEPTED, GDAKI_MI_AE_ACCEPT) == GDAKI_MI_AS_FAIL);
  CHECK(!gdakiMiRejoinAllowed(true, GDAKI_MI_AS_FAIL));
  // mirror off: the first REJOIN as gin-restore (no FETCH on the activation connection)
  CHECK(gdakiMiRejoinAllowed(false, GDAKI_MI_AS_WAIT) && gdakiMiRejoinAllowed(false, GDAKI_MI_AS_FAIL));
}

// ---- HOLDING's payload, the extents and the drain set ----
static void testHoldingAndExtents() {
  const uint64_t L = 1u << 20;
  // a holder's records: segments 5 (closed by checkpoint 40, in the image) and 6 (closed by 45), the open one 7
  const uint64_t seg[2] = {5, 6}, fill[2] = {2000, 3000}, closedAt[2] = {40, 45}, broken[2] = {3, 0};
  struct gdakiMiHolding p;
  CHECK(gdakiMiHoldingOf(seg, fill, closedAt, broken, 2, 7, 128, 9, 9, L, true, true, 1234, &p));
  CHECK(p.version == GDAKI_MI_WIRE_VERSION && p.nSeg == 3 && p.mirMsgs == 1234 && p.pathOk == 1 && p.cellValid == 1);
  CHECK(p.seg[2].seg == 7 && p.seg[2].closedAt == GDAKI_MI_OPEN && p.seg[2].fill == 128 && p.seg[2].broken == 0);
  CHECK(gdakiMiHoldingVerdict(p, 40) == 0);  // segment 5's breaks are inside checkpoint 40 (dropped by it)
  CHECK(gdakiMiHoldingVerdict(p, 39) == 2);
  // a cursor past L (a break) counts L; breaks since the opening make the open segment unusable
  CHECK(gdakiMiHoldingOf(seg, fill, closedAt, broken, 2, 7, 3 * L, 11, 9, L, true, true, 1, &p));
  CHECK(p.seg[2].fill == L && p.seg[2].broken == 2 && gdakiMiHoldingVerdict(p, 40) == 2);
  // a path not usable is fine while no live segment after k holds bytes
  CHECK(gdakiMiHoldingOf(seg, fill, closedAt, broken, 1, 7, 0, 0, 0, L, false, false, 0, &p));
  CHECK(gdakiMiHoldingVerdict(p, 40) == 0);
  CHECK(gdakiMiHoldingOf(seg, fill, closedAt, broken, 1, 7, 64, 0, 0, L, false, true, 0, &p));
  CHECK(gdakiMiHoldingVerdict(p, 40) == 3);
  // no open segment (the cell never opened one), and more live segments than a payload carries
  CHECK(gdakiMiHoldingOf(seg, fill, closedAt, broken, 2, 0, 0, 0, 0, L, true, true, 0, &p) && p.nSeg == 2);
  const uint64_t s5[5] = {1, 2, 3, 4, 5}, f5[5] = {1, 1, 1, 1, 1}, c5[5] = {41, 42, 43, 44, 46}, b5[5] = {0, 0, 0, 0, 0};
  CHECK(!gdakiMiHoldingOf(s5, f5, c5, b5, 4, 6, 0, 0, 0, L, true, true, 0, &p) && p.version == 0);
  CHECK(gdakiMiHoldingVerdict(p, 40) == 1);  // version 0: the buddy refuses it
  // the buddy of rank 2 (n 4): payloads of senders 0, 1, 3 (3 is the buddy itself: its self loop)
  const int n = 4, d = 2;
  std::vector<struct gdakiMiHolding> pay(n);
  std::vector<uint8_t> have(n, 0);
  const uint64_t sA[1] = {6}, fA[1] = {3000}, cA[1] = {45}, bA[1] = {0};
  CHECK(gdakiMiHoldingOf(sA, fA, cA, bA, 1, 7, 128, 0, 0, L, true, true, 100, &pay[0]));  // two extents
  CHECK(gdakiMiHoldingOf(sA, fA, cA, bA, 0, 4, 0, 0, 0, L, true, true, 50, &pay[1]));     // nothing after k
  CHECK(gdakiMiHoldingOf(sA, fA, cA, bA, 0, 9, 4096, 0, 0, L, true, true, 70, &pay[3]));  // one extent
  have[0] = have[1] = 1;
  std::vector<struct gdakiMiActExt> ext;
  std::vector<uint8_t> drain;
  int bad = 0, verdict = 0;
  const int wi = ncclGinMiWardIdx(d, n);
  CHECK(gdakiMiExtentsOf(pay.data(), have.data(), n, d, 40, wi, 3, L, &ext, &drain, &bad, &verdict) == 1 && bad == 3);
  have[3] = 1;
  CHECK(gdakiMiExtentsOf(pay.data(), have.data(), n, d, 40, wi, 3, L, &ext, &drain, &bad, &verdict) == 0);
  CHECK(ext.size() == 3 && drain[0] == 1 && drain[1] == 0 && drain[2] == 0 && drain[3] == 1);
  CHECK(ext[0].sender == 0 && ext[0].seg == 6 && ext[0].closedAt == 45 && ext[1].seg == 7 && ext[2].sender == 3);
  for (const auto& e : ext) {
    CHECK(e.lane == (uint32_t)ncclGinMiLaneOf(e.sender, d));
    CHECK(e.poolOff == ncclGinMiLaneOff(wi, e.seg % 3, (int)e.lane, n, 3, L));
  }
  // checkpoint 45 drops segment 6 (closed by it): one extent less
  CHECK(gdakiMiExtentsOf(pay.data(), have.data(), n, d, 45, wi, 3, L, &ext, &drain, &bad, &verdict) == 0 && ext.size() == 2);
  // a sender whose lane broke: the restore of d is refused at the buddy
  pay[3].seg[0].broken = 1;
  CHECK(gdakiMiExtentsOf(pay.data(), have.data(), n, d, 40, wi, 3, L, &ext, &drain, &bad, &verdict) == 2 && bad == 3 &&
        verdict == 2);
  pay[3].seg[0].broken = 0;
  // the geometry
  CHECK(gdakiMiExtentsOf(pay.data(), have.data(), n, d, 40, -1, 3, L, &ext, &drain, &bad, &verdict) == 4);
  CHECK(gdakiMiExtentsOf(pay.data(), have.data(), n, d, 40, wi, 0, L, &ext, &drain, &bad, &verdict) == 4);
  // the blob's payload layout and the record's room
  CHECK(sizeof(struct gdakiMiHolding) <= sizeof(uint32_t) * 64);
}

// ---- the drain verdicts ----
static void testDrain() {
  CHECK(gdakiMiDrainOf(false, 100, 10) == -1);  // an invalidated count: refused, whatever it says
  CHECK(gdakiMiDrainOf(true, 9, 10) == 1 && gdakiMiDrainOf(true, 10, 10) == 0 && gdakiMiDrainOf(true, 11, 10) == 0);
  // the self loop: the responder's 24-bit MSN at or past its connect base + the msgs read at the hold start, mod 2^24
  for (uint32_t base : {0u, 7u, 0xfffff0u, 0x123456u}) {
    auto at = [&](uint64_t executed) { return (uint32_t)((base + executed) & 0xffffffu); };  // the MSN after that many
    CHECK(gdakiMiSelfDrained(0, at(0), base) && gdakiMiSelfDrained(5, at(5), base) && !gdakiMiSelfDrained(5, at(4), base));
    CHECK(gdakiMiSelfDrained((1ull << 24) + 3, at((1ull << 24) + 3), base));   // the MSN wrapped once
    CHECK(gdakiMiSelfDrained((5ull << 24) + 0xfffffe, at((5ull << 24) + 0xfffffe), base));  // and many times
    CHECK(!gdakiMiSelfDrained((1ull << 24) + 3, at((1ull << 24) - 1), base));  // 4 WRITEs not executed yet
    CHECK(gdakiMiSelfDrained(5, at(9), base));  // 4 more WRITEs (to the buddy's other ward) posted and executed since
    // around a wrap: up to a send queue's depth (128) outstanding is never drained; up to 100 000 executed past mSelf is
    int wrong = 0, cases = 0;
    for (uint64_t m = (1ull << 24) - 300; m < (1ull << 24) + 300; m += 7) {
      for (uint64_t out = 1; out <= 128; out++, cases++) wrong += gdakiMiSelfDrained(m, at(m - out), base);
      for (uint64_t past = 0; past <= 100000; past += 997, cases++) wrong += !gdakiMiSelfDrained(m, at(m + past), base);
    }
    CHECK(wrong == 0 && cases > 10000);
  }
  // a base that is not the loop's (the zero-base assumption when the MSN did not start at 0) is wrong both ways
  CHECK(gdakiMiSelfDrained(10, 10 + 5, 5) && !gdakiMiSelfDrained(10, 10 + 5, 9));
}

// ---- the export v2: entry tags and the stream ----
static void testExport() {
  // the step pairs above the cut (steps 41, 42 with heads 120, 150), the last step 42; segments: 6 closed at cut 130
  // (its pause), 7 open; the oldest live segment opened at 100
  const uint64_t steps[2] = {41, 42}, heads[2] = {120, 150}, cuts[1] = {130}, segs[1] = {6};
  auto entry = [](uint32_t kind, uint32_t flags, uint64_t bytes) {
    struct ncclGinRsLogEntry e;
    memset(&e, 0, sizeof(e));
    e.qpKf = ncclGinRsQpKf(2, kind, flags);
    e.bytes = bytes;
    return e;
  };
  struct gdakiRsLogXEnt2 x;
  // a mirrored put at 110: step 41, segment 6; at 140: step 42, segment 7; at 160 (after the last Step): step 43
  CHECK(gdakiMiExportTag(entry(NCCL_GIN_RS_LOG_PUT, NCCL_GIN_RS_LOGF_MIRROR, 4096), 110, 40, steps, heads, 2, 42, cuts, segs,
                         1, 7, 100, &x) == GDAKI_MI_X_OK && x.step == 41 && x.seg == 6);
  CHECK(gdakiMiExportTag(entry(NCCL_GIN_RS_LOG_PUT, NCCL_GIN_RS_LOGF_MIRROR | NCCL_GIN_RS_LOGF_SIGNAL, 64), 140, 40, steps,
                         heads, 2, 42, cuts, segs, 1, 7, 100, &x) == GDAKI_MI_X_OK && x.step == 42 && x.seg == 7);
  CHECK(gdakiMiExportTag(entry(NCCL_GIN_RS_LOG_PUT, NCCL_GIN_RS_LOGF_MIRROR, 64), 160, 40, steps, heads, 2, 42, cuts, segs, 1,
                         7, 100, &x) == GDAKI_MI_X_OK && x.step == 43);
  // a putValue and a signal alone carry their content in the entry: no segment
  CHECK(gdakiMiExportTag(entry(NCCL_GIN_RS_LOG_PUTVALUE, 0, 8), 110, 40, steps, heads, 2, 42, cuts, segs, 1, 7, 100, &x) ==
          GDAKI_MI_X_OK && x.seg == 0 && x.step == 41);
  CHECK(gdakiMiExportTag(entry(NCCL_GIN_RS_LOG_SIGNAL, NCCL_GIN_RS_LOGF_SIGNAL, 0), 110, 40, steps, heads, 2, 42, cuts, segs,
                         1, 7, 100, &x) == GDAKI_MI_X_OK);
  CHECK(gdakiMiExportTag(entry(NCCL_GIN_RS_LOG_PUT, 0, 0), 110, 40, steps, heads, 2, 42, cuts, segs, 1, 7, 100, &x) ==
        GDAKI_MI_X_OK);  // a 0-byte put has no data
  // refusals: a put with data not mirrored, below the oldest live segment, its step unknown or not after the checkpoint,
  // the flag on an entry without data
  CHECK(gdakiMiExportTag(entry(NCCL_GIN_RS_LOG_PUT, 0, 64), 110, 40, steps, heads, 2, 42, cuts, segs, 1, 7, 100, &x) ==
        GDAKI_MI_X_NOMIRROR);
  CHECK(gdakiMiExportTag(entry(NCCL_GIN_RS_LOG_PUT, NCCL_GIN_RS_LOGF_MIRROR, 64), 90, 40, steps, heads, 2, 42, cuts, segs, 1,
                         7, 100, &x) == GDAKI_MI_X_NOSEG);
  CHECK(gdakiMiExportTag(entry(NCCL_GIN_RS_LOG_PUTVALUE, 0, 8), 110, 40, nullptr, nullptr, 0, GDAKI_RS_STEP_UNKNOWN, cuts,
                         segs, 1, 7, 100, &x) == GDAKI_MI_X_NOSTEP);
  CHECK(gdakiMiExportTag(entry(NCCL_GIN_RS_LOG_PUTVALUE, 0, 8), 110, 41, steps, heads, 2, 42, cuts, segs, 1, 7, 100, &x) ==
        GDAKI_MI_X_NOSTEP);  // step 41 is inside checkpoint 41
  CHECK(gdakiMiExportTag(entry(NCCL_GIN_RS_LOG_PUTVALUE, NCCL_GIN_RS_LOGF_MIRROR, 8), 110, 40, steps, heads, 2, 42, cuts, segs,
                         1, 7, 100, &x) == GDAKI_MI_X_BADMIRROR);
  // no pair above the cut: every entry is after the last Step
  CHECK(gdakiMiStepTag(nullptr, nullptr, 0, 42, 500) == 43 && gdakiMiStepTag(nullptr, nullptr, 0, GDAKI_RS_STEP_UNKNOWN, 5) ==
        GDAKI_RS_STEP_UNKNOWN);
  CHECK(has(gdakiMiExportTagName(GDAKI_MI_X_NOMIRROR), "not mirrored"));
  // the 64-bit position from the low 32 bits
  CHECK(gdakiMiPos64(100, 105) == 105);
  CHECK(gdakiMiPos64(0xfffffff0ull, 0x10u) == 0x100000010ull);
  CHECK(gdakiMiPos64(0x3fffffff0ull, 0xfffffff8u) == 0x3fffffff8ull);
  // the stream: header v2, the mirror header, 80-byte entries, the end, the rkey list (as rs_log_api.h v2 says)
  struct gdakiRsLogXHdr h;
  memset(&h, 0, sizeof(h));
  h.magic = GDAKI_RS_LOGX_MAGIC;
  h.version = GDAKI_RS_LOGX_VERSION_MI;
  h.nEntries = 2;
  struct gdakiRsLogXHdr2 h2;
  memset(&h2, 0, sizeof(h2));
  h2.flags = GDAKI_RS_LOGX_F_MIRROR;
  h2.nMirror = 1;
  struct gdakiRsLogXEnt2 ents[2];
  memset(ents, 0, sizeof(ents));
  ents[0].step = 41;
  ents[0].seg = 6;
  ents[1].step = 42;
  struct gdakiRsLogXEnd end;
  memset(&end, 0, sizeof(end));
  end.magic = GDAKI_RS_LOGX_MAGIC;
  end.ok = 1;
  struct gdakiRsRkeysHdr kh;
  memset(&kh, 0, sizeof(kh));
  kh.magic = GDAKI_RS_RKEYS_MAGIC;
  kh.version = 1;
  kh.count = 2;
  const struct gdakiRsRkeyEntry keys[2] = {{GDAKI_RS_RKEY_WINDOW, 1, 0xa1, 0}, {GDAKI_MI_RKEY_POOL, 0, 0xd0, 0}};
  std::vector<uint8_t> s;
  auto put = [&](const void* p, size_t k) {
    s.insert(s.end(), (const uint8_t*)p, (const uint8_t*)p + k);
    return true;
  };
  CHECK(gdakiMiLogXWrite2(h, h2, ents, 2, end, kh, keys, put));
  const size_t want = sizeof(h) + 64 + 2 * 80 + sizeof(end) + sizeof(kh) + 2 * 16;
  CHECK(s.size() == want);
  struct gdakiRsLogXEnt2 back;
  memcpy(&back, s.data() + sizeof(h) + 64, sizeof(back));
  CHECK(back.step == 41 && back.seg == 6);
  struct gdakiRsLogXEnd endBack;
  memcpy(&endBack, s.data() + sizeof(h) + 64 + 160, sizeof(endBack));
  CHECK(endBack.magic == GDAKI_RS_LOGX_MAGIC && endBack.ok == 1);
  struct gdakiRsRkeyEntry kb;
  memcpy(&kb, s.data() + want - 16, sizeof(kb));
  CHECK(kb.kind == GDAKI_MI_RKEY_POOL && kb.rkeyBe == 0xd0);
  // a failing put stops the stream
  int calls = 0;
  auto fail2 = [&](const void*, size_t) { return ++calls < 2; };
  CHECK(!gdakiMiLogXWrite2(h, h2, ents, 2, end, kh, keys, fail2) && calls == 2);
}

int main() {
  testBlob();
  testAddr();
  testQpn();
  testRkeys();
  testOrder();
  testHoldingAndExtents();
  testDrain();
  testExport();
  printf("mi_unit_spare: %d checks, %d failed\n", nChecks, nFail);
  return nFail == 0 ? 0 : 1;
}
