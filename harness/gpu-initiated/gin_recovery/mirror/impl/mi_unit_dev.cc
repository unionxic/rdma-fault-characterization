// mi_unit_dev.cc - gin-mirror's dev branch CPU unit test (impl/PARALLEL.md, build_mi.sh unit). build_mi.sh cuts the
// working tree's pure regions out of gin_host_gdaki.cc (gin-restore's "pure functions" and "log, suppress and replay,
// pure", and this branch's "gin-mirror (dev): pure") into .inc files and compiles them here with ASan and UBSan, so the
// test runs the library's own text; the working tree's device-host common header is included as it is (the pasted
// device layout and device helpers: the mirror's position arithmetic the send path uses). No NCCL, no CUDA, no network.
// What it tests: the pool and lane arithmetic and the cursor (device helpers), the MIRROR log entry, the two QP sets,
// the side table v4's layout, the export v2's parse, the step-aligned import's plan, its signal check and its pacing,
// the rkey verdict; with the mirror off, gin-restore's verdicts (layout, QP set, export v1) are unchanged.
#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <random>
#include <string>
#include <thread>
#include <vector>
#include <stddef.h>
#include <stdint.h>

enum { GDAKI_POLICY_FAILFAST = 0, GDAKI_POLICY_HOLD = 1 };  // hk's line (rs_pure.inc needs it)
#include "nccl_device/gin/gdaki/gin_gdaki_device_host_common.h"  // the working tree's: device layout v4, device helpers
#include "rs_pure.inc"
typedef int ncclResult_t;
typedef struct {
  unsigned int magic, nqp, qpn[64], remoteQpn[64], sqPsn[64];
  unsigned long long epochWqes[64];
} ncclGinRecoverToken_t;
#define GDAKI_MI_API_NO_ENTRY_DECLS
#define GDAKI_HOLD_API_NO_ENTRY_DECLS
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-function"
// the log API block v2 (the tree's text byte for byte, build_mi.sh api) with its records; its functions are declared and
// never defined here
#include "rs_log_api.h"
#include "rs_dev_pure.inc"
// the spare branch's records (the rkey list), as the host file has them before this branch's pure region
#include "rs_spare_api.h"
// the mirror's host API block and the store API block (gdakiMiFetched, gdakiMiFetchedAt): their device blocks repeat the
// tree header's text (identical macros; the types land in this namespace), so they are kept apart
namespace mif {
#include "rs_mirror_api.h"
#include "rs_store_api.h"
}  // namespace mif
#pragma GCC diagnostic pop
#include "mi_pure_dev.inc"

static int nChecks = 0, nFail = 0;
#define CHECK(c)                                                                         \
  do {                                                                                   \
    nChecks++;                                                                           \
    if (!(c)) {                                                                          \
      nFail++;                                                                           \
      fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c);                       \
    }                                                                                    \
  } while (0)

// ---------------------------------------------------------------------------------------------------------------------
// 1. the pool, the lanes and the cursor (the device helpers block: the send path and the host share it)
// ---------------------------------------------------------------------------------------------------------------------
static void testBuddyWards() {
  CHECK(ncclGinMiBuddyOf(0, 1) == -1 && ncclGinMiBuddyOf(0, 0) == -1);
  CHECK(ncclGinMiBuddyOf(0, 4) == 1 && ncclGinMiBuddyOf(1, 4) == 0 && ncclGinMiBuddyOf(2, 4) == 3 &&
        ncclGinMiBuddyOf(3, 4) == 2);
  CHECK(ncclGinMiBuddyOf(4, 5) == 0 && ncclGinMiBuddyOf(0, 5) == 1 && ncclGinMiBuddyOf(1, 5) == 0);
  for (int n = 2; n <= 64; n++) {
    for (int p = 0; p < n; p++) {
      const int b = ncclGinMiBuddyOf(p, n);
      CHECK(b >= 0 && b < n && b != p);
      // the same rule as the hold machine's (rs_hold_api.h gdakiHoldBuddyOf: p xor 1, or 0 for the odd count's last)
      const int ref = (p ^ 1) < n ? (p ^ 1) : (p == 0 ? 1 : 0);
      CHECK(b == ref);
    }
    for (int b = 0; b < n; b++) {
      int w[2] = {-7, -7};
      const int k = ncclGinMiWardsOf(b, n, w);
      std::vector<int> ref;
      for (int p = 0; p < n; p++)
        if (ncclGinMiBuddyOf(p, n) == b) ref.push_back(p);
      CHECK(k == (int)ref.size() && k <= 2);
      for (int i = 0; i < k && i < (int)ref.size(); i++) CHECK(w[i] == ref[(size_t)i]);
      if (k == 2) CHECK(w[0] < w[1]);
    }
    for (int d = 0; d < n; d++) {
      const int b = ncclGinMiBuddyOf(d, n);
      int w[2];
      const int k = ncclGinMiWardsOf(b, n, w);
      const int wi = ncclGinMiWardIdx(d, n);
      CHECK(wi >= 0 && wi < k && w[wi] == d);
    }
  }
  CHECK(ncclGinMiWardIdx(0, 1) == -1);
  // rank 0 of an odd count keeps two wards (1 and n - 1); every other rank one
  int w[2];
  CHECK(ncclGinMiWardsOf(0, 7, w) == 2 && w[0] == 1 && w[1] == 6);
  CHECK(ncclGinMiWardsOf(3, 7, w) == 1 && w[0] == 2);
}
static void testLanes() {
  for (int n = 2; n <= 16; n++)
    for (int d = 0; d < n; d++) {
      std::vector<int> seen((size_t)(n - 1), 0);
      for (int s = 0; s < n; s++) {
        if (s == d) continue;
        const int l = ncclGinMiLaneOf(s, d);
        CHECK(l >= 0 && l < n - 1);
        if (l >= 0 && l < n - 1) seen[(size_t)l]++;
      }
      for (int c : seen) CHECK(c == 1);  // every sender its own lane, n - 1 lanes in rank order
    }
  // the pool of a buddy: wards x S slots x (n - 1) lanes x L, disjoint, inside the pool, multiples of L
  const uint64_t Ls[] = {64, 4096, 1u << 20, 80ull << 20};
  for (int n = 2; n <= 9; n++)
    for (uint64_t S = 2; S <= 4; S++)
      for (uint64_t L : Ls)
        for (int b = 0; b < n; b++) {
          int w[2];
          const int nw = ncclGinMiWardsOf(b, n, w);
          const uint64_t pool = ncclGinMiPoolBytes(nw, S, n, L);
          CHECK(pool == (uint64_t)nw * S * (uint64_t)(n - 1) * L);
          std::vector<uint64_t> offs;
          for (int wi = 0; wi < nw; wi++)
            for (uint64_t slot = 0; slot < S; slot++)
              for (int lane = 0; lane < n - 1; lane++) {
                const uint64_t o = ncclGinMiLaneOff(wi, slot, lane, n, S, L);
                CHECK(o % L == 0 && o + L <= pool);
                offs.push_back(o);
              }
          std::sort(offs.begin(), offs.end());
          CHECK(std::adjacent_find(offs.begin(), offs.end()) == offs.end());
          CHECK(offs.size() == (size_t)(pool / L));
        }
  // the activation blob's extent offset rule (impl/rs_store_api.h gdakiMiActExt: ncclGinMiLaneOff(wardIdx, seg mod S, ...))
  CHECK(ncclGinMiLaneOff(1, 2, 3, 4, 3, 1 << 20) == (((1ull * 3 + 2) * 3 + 3) << 20));
  CHECK(ncclGinMiQpIdx(4, 8, 3) == 35u && ncclGinMiQpIdx(0, 8, 0) == 0u);
}
static void testCursor() {
  CHECK(ncclGinMiRound64(0) == 0 && ncclGinMiRound64(1) == 64 && ncclGinMiRound64(64) == 64 &&
        ncclGinMiRound64(65) == 128 && ncclGinMiRound64(4096) == 4096);
  // fits: off <= L and round64(bytes) <= L - off; a cursor past L never fits (no wrap)
  const uint64_t L = 1 << 20;
  CHECK(ncclGinMiFits(0, L, L) && !ncclGinMiFits(0, L + 1, L) && ncclGinMiFits(L - 64, 1, L) && ncclGinMiFits(L - 64, 64, L));
  CHECK(!ncclGinMiFits(L - 64, 65, L) && !ncclGinMiFits(L, 1, L) && ncclGinMiFits(L, 0, L) && !ncclGinMiFits(L + 64, 0, L));
  CHECK(!ncclGinMiFits(~0ull - 63, 64, L));
  // the interface's round-up wraps for a byte count above 2^64 - 64 (then "fits" at 0): the send path (rsMiPut) checks
  // bytes <= L before it takes the cursor, so such a put is a break, never a mirror
  CHECK(ncclGinMiRound64(~0ull - 10) == 0 && ncclGinMiFits(0, ~0ull - 10, L));
  // the device's sequence (the cursor's atomic add returns off; a put that does not fit is a break and leaves the cursor
  // past it): random puts, mirrored data never overlap, stay inside the lane, 64-byte aligned; the lane word (off / 64)
  // in the entry gives the offset back (gdakiMiEntryLaneOff); the cursor only grows
  std::mt19937_64 rng(7);
  for (int run = 0; run < 2000; run++) {
    const uint64_t lane = (uint64_t)(1 + rng() % 64) << 12;
    uint64_t cursor = 0;
    std::vector<std::pair<uint64_t, uint64_t>> got;
    int breaks = 0;
    for (int i = 0; i < 64; i++) {
      const uint64_t bytes = 1 + rng() % (lane / 4);
      const uint64_t off = cursor;
      cursor += ncclGinMiRound64(bytes);
      if (!ncclGinMiFits(off, bytes, lane)) {
        breaks++;
        continue;
      }
      CHECK(off % 64 == 0 && off + bytes <= lane);
      struct ncclGinRsLogEntry e;
      memset(&e, 0, sizeof(e));
      e.csum = (uint32_t)(off >> 6);
      CHECK(gdakiMiEntryLaneOff(e) == off);
      got.push_back({off, bytes});
    }
    std::sort(got.begin(), got.end());
    for (size_t k = 1; k < got.size(); k++) CHECK(got[k - 1].first + got[k - 1].second <= got[k].first);
    CHECK(breaks == 0 || cursor > lane);
  }
  // the lane word holds 32 bits: a lane of 256 GiB still round-trips
  struct ncclGinRsLogEntry e;
  memset(&e, 0, sizeof(e));
  e.csum = 0xffffffffu;
  CHECK(gdakiMiEntryLaneOff(e) == (0xffffffffull << 6));
  // the cell's layout (the host writes it over the NIC by these offsets)
  CHECK(sizeof(struct ncclGinMiCell) == 64 && offsetof(struct ncclGinMiCell, cursor) == 32 &&
        offsetof(struct ncclGinMiCell, broken) == 40);
  CHECK(offsetof(struct ncclGinRsSide, miOn) == 40 && offsetof(struct ncclGinRsQp, miUse) == 48);
  CHECK(NCCL_GIN_RS_SIDE_MAGIC == 0x34535352u);
}

// ---------------------------------------------------------------------------------------------------------------------
// 2. the MIRROR entry
// ---------------------------------------------------------------------------------------------------------------------
static struct ncclGinRsLogEntry entry(uint32_t qp, uint32_t kind, uint32_t flags, uint32_t dstWin, uint64_t dstOff,
                                      uint64_t bytes, uint32_t srcWin = 1, uint64_t src = 0, uint32_t csum = 0) {
  struct ncclGinRsLogEntry e;
  memset(&e, 0, sizeof(e));
  e.qpKf = ncclGinRsQpKf(qp, kind, flags);
  e.dstWin = dstWin;
  e.dstOff = dstOff;
  e.bytes = bytes;
  e.srcWin = kind == NCCL_GIN_RS_LOG_PUT ? srcWin : 0;
  e.src = src;
  e.csum = csum;
  return e;
}
static void testEntry() {
  // the device's encoding: flags in bits 26..31 (6 bits); MIRROR is the sixth (0x20), apart from SIGNAL, SPLIT, NOBASE
  // and the checksum scheme (bits 3..4)
  CHECK(NCCL_GIN_RS_LOGF_MIRROR == 0x20u);
  CHECK((NCCL_GIN_RS_LOGF_MIRROR & (NCCL_GIN_RS_LOGF_SIGNAL | NCCL_GIN_RS_LOGF_SPLIT | NCCL_GIN_RS_LOGF_NOBASE |
                                    (3u << NCCL_GIN_RS_LOGF_CSUM_SHIFT))) == 0);
  const uint32_t kf = ncclGinRsQpKf(0xabcdef, NCCL_GIN_RS_LOG_PUT, NCCL_GIN_RS_LOGF_SIGNAL | NCCL_GIN_RS_LOGF_MIRROR);
  CHECK(ncclGinRsEntryQp(kf) == 0xabcdef && ncclGinRsEntryKind(kf) == NCCL_GIN_RS_LOG_PUT);
  CHECK(ncclGinRsEntryFlags(kf) == (NCCL_GIN_RS_LOGF_SIGNAL | NCCL_GIN_RS_LOGF_MIRROR) && gdakiMiEntryMirrored(kf));
  CHECK(!gdakiMiEntryMirrored(ncclGinRsQpKf(1, NCCL_GIN_RS_LOG_PUT, NCCL_GIN_RS_LOGF_SIGNAL)));
  // MIRROR does not change the request messages (the mirror WRITE is counted on the mirror QP, not on the user QP)
  CHECK(ncclGinRsEntryMsgs(kf, 4096) == 2 && ncclGinRsEntryMsgs(ncclGinRsQpKf(1, NCCL_GIN_RS_LOG_PUT,
                                                                              NCCL_GIN_RS_LOGF_MIRROR), (3ull << 30) + 1) == 4);
  // no checksum on a MIRROR entry (gdakiRsEntryCsumScheme reads the scheme bits only)
  CHECK(gdakiRsEntryCsumScheme(kf) == NCCL_GIN_RS_CSUM_OFF);
  const uint32_t M = NCCL_GIN_RS_LOGF_MIRROR;
  CHECK(gdakiMiEntryCheck(entry(1, NCCL_GIN_RS_LOG_PUT, M, 2, 0, 4096)) == nullptr);
  CHECK(gdakiMiEntryCheck(entry(1, NCCL_GIN_RS_LOG_PUT, M | NCCL_GIN_RS_LOGF_SIGNAL, 2, 0, 4096)) == nullptr);
  CHECK(gdakiMiEntryCheck(entry(1, NCCL_GIN_RS_LOG_PUT, 0, 2, 0, 4096)) != nullptr);          // not mirrored
  CHECK(gdakiMiEntryCheck(entry(1, NCCL_GIN_RS_LOG_PUT, NCCL_GIN_RS_LOGF_SIGNAL, 2, 0, 0)) == nullptr);  // 0 bytes
  CHECK(gdakiMiEntryCheck(entry(1, NCCL_GIN_RS_LOG_PUT, M, 2, 0, 0)) != nullptr);             // MIRROR on 0 bytes
  CHECK(gdakiMiEntryCheck(entry(1, NCCL_GIN_RS_LOG_PUTVALUE, 0, 2, 0, 8)) == nullptr);
  CHECK(gdakiMiEntryCheck(entry(1, NCCL_GIN_RS_LOG_PUTVALUE, M, 2, 0, 8)) != nullptr);
  CHECK(gdakiMiEntryCheck(entry(1, NCCL_GIN_RS_LOG_SIGNAL, NCCL_GIN_RS_LOGF_SIGNAL, 0, 0, 0)) == nullptr);
  CHECK(gdakiMiEntryCheck(entry(1, NCCL_GIN_RS_LOG_SIGNAL, NCCL_GIN_RS_LOGF_SIGNAL | M, 0, 0, 0)) != nullptr);
  CHECK(gdakiMiEntryCheck(entry(1, NCCL_GIN_RS_LOG_PUT, M | NCCL_GIN_RS_LOGF_SPLIT, 2, 0, 64)) != nullptr);
  CHECK(gdakiMiEntryCheck(entry(1, NCCL_GIN_RS_LOG_PUT, M | NCCL_GIN_RS_LOGF_NOBASE, 2, 0, 64)) != nullptr);
  CHECK(gdakiMiEntryCheck(entry(1, NCCL_GIN_RS_LOG_PUT, M | (1u << NCCL_GIN_RS_LOGF_CSUM_SHIFT), 2, 0, 64)) != nullptr);
  CHECK(gdakiMiEntryCheck(entry(1, NCCL_GIN_RS_LOG_PUT, M, 0, 0, 64)) != nullptr);  // v1's check: no target window
  CHECK(gdakiMiEntryCheck(entry(1, 0, 0, 2, 0, 64)) != nullptr);                     // v1's check: no kind
}

// ---------------------------------------------------------------------------------------------------------------------
// 3. the two QP sets
// ---------------------------------------------------------------------------------------------------------------------
// gin-restore's gdakiRsQpsOfPeer (rs_layer.diff 9940), the reference for "mirror off: unchanged"
static int v1QpsOf(int nContexts, int nranks, int peer, const std::vector<int>& used, int rsNqp, int* idx) {
  int n = 0;
  if (peer < 0 || peer >= nranks) return 0;
  for (int c = 0; c < nContexts && n < NCCL_GIN_RECOVERY_MAX_QPS; c++) {
    const int i = peer + c * nranks;
    if (i < (int)used.size() && used[(size_t)i] && i < rsNqp) idx[n++] = i;
  }
  return n;
}
static void testQpSets() {
  std::mt19937 rng(11);
  for (int run = 0; run < 3000; run++) {
    const int nranks = 1 + (int)(rng() % 9), nUser = 1 + (int)(rng() % 5), me = (int)(rng() % nranks);
    const bool mirror = rng() % 2;
    const int miCtx = mirror ? nUser : -1;
    const int nCtxArr = nUser + (mirror ? 1 : 0);  // the context array (the mirror context last)
    const bool countMirror = rng() % 2;            // whether nContexts counts the mirror context (either way)
    const int nContexts = mirror && countMirror ? nCtxArr : nUser;
    std::vector<int> used((size_t)(nCtxArr * nranks), 0);
    for (auto& u : used) u = rng() % 8 != 0;
    const int rsNqp = (int)used.size();
    auto usedF = [&](int i) { return i >= 0 && i < (int)used.size() && used[(size_t)i] && i < rsNqp; };
    for (int peer = -1; peer <= nranks; peer++) {
      int a[NCCL_GIN_RECOVERY_MAX_QPS], b[NCCL_GIN_RECOVERY_MAX_QPS];
      const int na = gdakiMiUserQpsOf(nContexts, miCtx, nranks, peer, usedF, a);
      const int nb = v1QpsOf(nUser, nranks, peer, used, rsNqp, b);  // the user contexts only
      CHECK(na == nb);
      for (int k = 0; k < na && k < nb; k++) CHECK(a[k] == b[k]);
      for (int k = 0; k < na; k++) CHECK(a[k] / nranks != miCtx && a[k] % nranks == peer);
      const int m = gdakiMiMirrorQpOf(miCtx, nranks, me, peer, usedF);
      if (!mirror || peer < 0 || peer >= nranks || peer == me) CHECK(m == -1);
      else CHECK(m == (usedF(miCtx * nranks + peer) ? miCtx * nranks + peer : -1));
      if (m >= 0) CHECK(m / nranks == miCtx && m % nranks == peer && (uint32_t)m == ncclGinMiQpIdx(miCtx, nranks, peer));
    }
    // mirror off: the user set is gin-restore's set over the whole array
    if (!mirror)
      for (int peer = 0; peer < nranks; peer++) {
        int a[NCCL_GIN_RECOVERY_MAX_QPS], b[NCCL_GIN_RECOVERY_MAX_QPS];
        const int na = gdakiMiUserQpsOf(nContexts, -1, nranks, peer, usedF, a);
        const int nb = v1QpsOf(nContexts, nranks, peer, used, rsNqp, b);
        CHECK(na == nb);
        for (int k = 0; k < na && k < nb; k++) CHECK(a[k] == b[k]);
      }
  }
  // the cap: at most NCCL_GIN_RECOVERY_MAX_QPS user QPs
  int idx[NCCL_GIN_RECOVERY_MAX_QPS];
  CHECK(gdakiMiUserQpsOf(100, -1, 2, 1, [](int) { return true; }, idx) == NCCL_GIN_RECOVERY_MAX_QPS);
  CHECK(gdakiMiUserQpsOf(100, 0, 2, 1, [](int) { return true; }, idx) == NCCL_GIN_RECOVERY_MAX_QPS && idx[0] == 3);
}

// ---------------------------------------------------------------------------------------------------------------------
// 4. the side table v4
// ---------------------------------------------------------------------------------------------------------------------
static void testLayout() {
  std::mt19937 rng(3);
  for (int run = 0; run < 20000; run++) {
    const int nqp = (int)(rng() % 600), nLogged = nqp ? (int)(rng() % (nqp + 1)) : 0;
    const long long ent = (long long)(rng() % (1u << 22)) - 10;
    struct gdakiRsSideLayout v1;
    struct gdakiMiSideLayout M;
    const bool a = gdakiRsSideLayoutOf(nqp, nLogged, ent, &v1);
    const bool b = gdakiMiSideLayoutOf(nqp, nLogged, ent, 0, &M);
    CHECK(a == b);  // mirror off: v1's layout, byte for byte
    if (a && b)
      CHECK(M.cellsOff == 0 && M.L.qpOff == v1.qpOff && M.L.ringsOff == v1.ringsOff && M.L.ringBytes == v1.ringBytes &&
            M.L.bytes == v1.bytes && M.L.nEntries == v1.nEntries);
    const int nCells = 1 + (int)(rng() % 64);
    struct gdakiMiSideLayout C;
    const bool c = gdakiMiSideLayoutOf(nqp, nLogged, ent, nCells, &C);
    CHECK(c == a);
    if (c && a) {
      CHECK(C.cellsOff == 128 + 128 * (size_t)nqp);  // impl/rs_mirror_api.h: miCellsOff = 128 + 128 x nqp
      CHECK(C.L.ringsOff % 256 == 0 && C.L.ringsOff >= C.cellsOff + 64 * (size_t)nCells &&
            C.L.ringsOff < C.cellsOff + 64 * (size_t)nCells + 256);
      CHECK(C.L.nEntries == v1.nEntries && C.L.ringBytes == v1.ringBytes && C.L.qpOff == v1.qpOff);
      CHECK(C.L.bytes % 4096 == 0 && C.L.bytes >= C.L.ringsOff + C.L.ringBytes && C.L.bytes < C.L.ringsOff + C.L.ringBytes + 4096);
      CHECK(C.L.ringsOff >= v1.ringsOff);
    }
  }
  struct gdakiMiSideLayout M;
  CHECK(!gdakiMiSideLayoutOf(4, 1, 64, -1, &M));
  CHECK(!gdakiMiSideLayoutOf(-1, 0, 64, 4, &M));
  CHECK(gdakiMiSideLayoutOf(20, 16, 4096, 4, &M) && M.cellsOff == 128 + 128 * 20 && M.L.ringsOff == 3072);
}

// ---------------------------------------------------------------------------------------------------------------------
// 5. the export v2, the plan, the signal check, the pacing
// ---------------------------------------------------------------------------------------------------------------------
static const uint64_t NONCE = 0x1234abcdull;
struct XEnt {
  struct ncclGinRsLogEntry e;
  uint64_t step, seg;
};
struct XSpec {
  int from = 0, to = 2;
  uint32_t incarnation = 1, nqp = 1;
  uint64_t ckpt = 10, cut = 100, head = 200;
  uint64_t x[NCCL_GIN_RECOVERY_MAX_QPS] = {}, m[NCCL_GIN_RECOVERY_MAX_QPS] = {};
  uint32_t mirValid = 1;
  uint64_t mirX = 5, mirM = 7, lastStep = 14;
  std::vector<struct XEnt> ents;
  bool ok = true;
  uint32_t version = GDAKI_RS_LOGX_VERSION_MI, flags = GDAKI_RS_LOGX_F_MIRROR;
  int64_t nMirrorDelta = 0, mirrorBytesDelta = 0;
  uint32_t rkVersion = 1, rkInc = 0;
  int rkRank = -1;  // -1: = from
  std::vector<struct gdakiRsRkeyEntry> keys;
};
template <typename T>
static void app(std::vector<uint8_t>& b, const T& v) {
  const uint8_t* p = (const uint8_t*)&v;
  b.insert(b.end(), p, p + sizeof(T));
}
static std::vector<uint8_t> buildX(const struct XSpec& s) {
  std::vector<uint8_t> b;
  struct gdakiRsLogXHdr h;
  memset(&h, 0, sizeof(h));
  h.magic = GDAKI_RS_LOGX_MAGIC;
  h.version = s.version;
  h.from = s.from;
  h.to = s.to;
  h.incarnation = s.incarnation;
  h.nqp = s.nqp;
  h.nonce = NONCE;
  h.ckpt = s.ckpt;
  h.cut = s.cut;
  h.head = s.head;
  h.nEntries = s.ents.size();
  for (int k = 0; k < NCCL_GIN_RECOVERY_MAX_QPS; k++) {
    h.x[k] = s.x[k];
    h.m[k] = s.m[k];
  }
  app(b, h);
  struct gdakiRsLogXHdr2 h2;
  memset(&h2, 0, sizeof(h2));
  h2.flags = s.flags;
  h2.mirValid = s.mirValid;
  h2.mirX = s.mirX;
  h2.mirM = s.mirM;
  h2.lastStep = s.lastStep;
  uint64_t nm = 0, mb = 0;
  for (const auto& x : s.ents)
    if (gdakiMiEntryMirrored(x.e.qpKf)) {
      nm++;
      mb += x.e.bytes;
    }
  h2.nMirror = nm + (uint64_t)s.nMirrorDelta;
  h2.mirrorBytes = mb + (uint64_t)s.mirrorBytesDelta;
  app(b, h2);
  for (const auto& x : s.ents) {
    struct gdakiRsLogXEnt2 e;
    e.e = x.e;
    e.step = x.step;
    e.seg = x.seg;
    app(b, e);
  }
  struct gdakiRsLogXEnd end;
  memset(&end, 0, sizeof(end));
  end.magic = GDAKI_RS_LOGX_MAGIC;
  end.ok = s.ok ? 1 : 0;
  if (!s.ok) snprintf(end.why, sizeof(end.why), "the segment broke");
  app(b, end);
  struct gdakiRsRkeysHdr rk;
  memset(&rk, 0, sizeof(rk));
  rk.magic = GDAKI_RS_RKEYS_MAGIC;
  rk.version = s.rkVersion;
  rk.rank = s.rkRank >= 0 ? s.rkRank : s.from;
  rk.incarnation = s.rkInc;
  rk.nonce = NONCE;
  rk.count = (uint32_t)s.keys.size();
  app(b, rk);
  for (const auto& k : s.keys) app(b, k);
  return b;
}
static struct XEnt mput(uint64_t step, uint64_t seg, uint32_t laneWord, uint32_t dstWin, uint64_t dstOff, uint64_t bytes,
                        bool sig = false, uint32_t sigWin = 0, uint64_t sigOff = 0, uint64_t sigVal = 0) {
  struct XEnt x;
  x.e = entry(0, NCCL_GIN_RS_LOG_PUT, NCCL_GIN_RS_LOGF_MIRROR | (sig ? NCCL_GIN_RS_LOGF_SIGNAL : 0u), dstWin, dstOff, bytes,
              1, 999, laneWord);
  x.e.sigWin = sigWin;
  x.e.sigOff = sigOff;
  x.e.sigVal = sigVal;
  x.step = step;
  x.seg = seg;
  return x;
}
static struct XEnt sigOnly(uint64_t step, uint32_t sigWin, uint64_t sigOff, uint64_t val) {
  struct XEnt x;
  x.e = entry(0, NCCL_GIN_RS_LOG_SIGNAL, NCCL_GIN_RS_LOGF_SIGNAL, 0, 0, 0);
  x.e.sigWin = sigWin;
  x.e.sigOff = sigOff;
  x.e.sigVal = val;
  x.step = step;
  x.seg = 0;
  return x;
}
static struct XEnt pval(uint64_t step, uint32_t dstWin, uint64_t dstOff, uint64_t value, uint32_t bytes = 8) {
  struct XEnt x;
  x.e = entry(0, NCCL_GIN_RS_LOG_PUTVALUE, 0, dstWin, dstOff, bytes, 0, value);
  x.step = step;
  x.seg = 0;
  return x;
}
static void testParse() {
  struct XSpec s;
  s.ents.push_back(mput(11, 3, 0, 2, 0, 4096, true, 0, 64, 1));
  s.ents.push_back(mput(12, 3, 64, 2, 4096, 100));
  s.ents.push_back(sigOnly(12, 0, 72, 5));
  s.ents.push_back(pval(13, 2, 8192, 0x55));
  s.keys.push_back({GDAKI_RS_RKEY_WINDOW, 2, 0x11223344u, 0});
  s.keys.push_back({GDAKI_MI_RKEY_POOL, 0, 0x55667788u, 0});
  std::vector<uint8_t> b = buildX(s);
  struct gdakiMiLogXParsed px;
  char why[256];
  CHECK(gdakiMiLogXParse(b.data(), b.size(), &px, why, sizeof(why)));
  CHECK(px.items.size() == 4 && px.keys.size() == 2 && px.nMirror == 2 && px.mirrorBytes == 4196);
  CHECK(px.items[1].step == 12 && px.items[1].seg == 3 && gdakiMiEntryLaneOff(px.items[1].e) == 64 * 64);
  CHECK(px.hdr2.mirX == 5 && px.hdr2.mirM == 7 && px.hdr2.mirValid == 1 && px.rk.rank == 0);
  CHECK(px.keys[1].kind == GDAKI_MI_RKEY_POOL && px.keys[1].rkeyBe == 0x55667788u);
  {  // the rkey list's count at its bound parses, one above is refused
    struct XSpec t = s;
    t.keys.assign(GDAKI_RS_RKEYS_MAX, {GDAKI_RS_RKEY_WINDOW, 2, 1u, 0});
    std::vector<uint8_t> c = buildX(t);
    CHECK(gdakiMiLogXParse(c.data(), c.size(), &px, why, sizeof(why)) && px.keys.size() == GDAKI_RS_RKEYS_MAX);
    t.keys.push_back({GDAKI_RS_RKEY_WINDOW, 3, 1u, 0});
    c = buildX(t);
    CHECK(!gdakiMiLogXParse(c.data(), c.size(), &px, why, sizeof(why)));
  }
  // the v1 parser refuses a v2 export, the v2 parser a v1 one (mirror off keeps gin-restore's import and format)
  struct gdakiRsLogXParsed p1;
  CHECK(!gdakiRsLogXParse(b.data(), b.size(), &p1, why, sizeof(why)));
  {  // gin-restore's own stream (gdakiRsLogXBuild) still parses with gin-restore's parser; this branch's refuses it
    struct gdakiRsLogXHdr h1;
    memset(&h1, 0, sizeof(h1));
    h1.magic = GDAKI_RS_LOGX_MAGIC;
    h1.version = 1;
    h1.from = 0;
    h1.to = 2;
    h1.nqp = 1;
    h1.cut = 10;
    h1.head = 12;
    h1.nEntries = 2;
    struct ncclGinRsLogEntry e1[2] = {entry(0, NCCL_GIN_RS_LOG_PUT, 0, 2, 0, 100), entry(0, NCCL_GIN_RS_LOG_PUTVALUE, 0, 2, 128, 8)};
    std::vector<uint8_t> src(100, 0x5a), v1;
    auto rd = [&](const struct ncclGinRsLogEntry&, uint64_t off, uint64_t, const char**) { return src.data() + off; };
    auto pt = [&](const void* q, size_t n) {
      v1.insert(v1.end(), (const uint8_t*)q, (const uint8_t*)q + n);
      return true;
    };
    CHECK(gdakiRsLogXBuild(h1, e1, 2, 4096, rd, pt, why, sizeof(why)) == GDAKI_RS_LOGX_OK);
    CHECK(gdakiRsLogXParse(v1.data(), v1.size(), &p1, why, sizeof(why)) && p1.items.size() == 2 &&
          p1.items[0].dataOff == sizeof(h1) + sizeof(struct ncclGinRsLogEntry));
    CHECK(!gdakiMiLogXParse(v1.data(), v1.size(), &px, why, sizeof(why)));
  }
  {
    struct XSpec v = s;
    v.version = 1;
    std::vector<uint8_t> x = buildX(v);
    CHECK(!gdakiMiLogXParse(x.data(), x.size(), &px, why, sizeof(why)) && strstr(why, "not an export v2") != nullptr);
  }
  auto refuses = [&](const struct XSpec& v, const char* phrase) {
    std::vector<uint8_t> x = buildX(v);
    struct gdakiMiLogXParsed q;
    char w[256] = {0};
    const bool r = gdakiMiLogXParse(x.data(), x.size(), &q, w, sizeof(w));
    CHECK(!r);
    if (phrase != nullptr && strstr(w, phrase) == nullptr) {
      nFail++;
      fprintf(stderr, "FAIL parse refusal: want '%s', got '%s'\n", phrase, w);
    }
    nChecks++;
  };
  { struct XSpec v = s; v.flags = 0; refuses(v, "mirror flag"); }
  { struct XSpec v = s; v.ok = false; refuses(v, "the survivor refused its export: the segment broke"); }
  { struct XSpec v = s; v.nqp = 0; refuses(v, "out of range"); }
  { struct XSpec v = s; v.cut = 300; refuses(v, "out of range"); }
  { struct XSpec v = s; v.head = v.cut + 2; refuses(v, "out of range"); }  // 4 entries in 2 positions
  { struct XSpec v = s; v.rkVersion = 2; refuses(v, "rkey list"); }
  { struct XSpec v = s; v.rkRank = 1; refuses(v, "rkey list is rank 1's"); }
  { struct XSpec v = s; v.nMirrorDelta = 1; refuses(v, "MIRROR entries"); }
  { struct XSpec v = s; v.mirrorBytesDelta = -1; refuses(v, "MIRROR entries"); }
  { struct XSpec v = s; v.ents[0].seg = 0; refuses(v, "segment is 0"); }
  { struct XSpec v = s; v.ents[2].seg = 4; refuses(v, "not mirrored"); }
  { struct XSpec v = s; v.ents[1].step = GDAKI_RS_STEP_UNKNOWN; refuses(v, "step is unknown"); }
  {
    struct XSpec v = s;
    v.ents[1].e.qpKf = ncclGinRsQpKf(0, NCCL_GIN_RS_LOG_PUT, 0);  // a put with data, not mirrored
    refuses(v, "not mirrored");
  }
  // every truncation and every extension by one byte is refused, never read past the buffer (ASan)
  for (size_t n = 0; n < b.size(); n++) {
    std::vector<uint8_t> t(b.begin(), b.begin() + (long)n);
    CHECK(!gdakiMiLogXParse(t.empty() ? nullptr : t.data(), t.size(), &px, why, sizeof(why)));
  }
  {
    std::vector<uint8_t> t(b);
    t.push_back(0);
    CHECK(!gdakiMiLogXParse(t.data(), t.size(), &px, why, sizeof(why)));
  }
  // the trailer's magic, the rkey list's magic
  {
    std::vector<uint8_t> t(b);
    const size_t endOff = sizeof(struct gdakiRsLogXHdr) + sizeof(struct gdakiRsLogXHdr2) + 4 * sizeof(struct gdakiRsLogXEnt2);
    t[endOff] ^= 1;
    CHECK(!gdakiMiLogXParse(t.data(), t.size(), &px, why, sizeof(why)) && strstr(why, "trailer") != nullptr);
    std::vector<uint8_t> u(b);
    u[endOff + sizeof(struct gdakiRsLogXEnd)] ^= 1;
    CHECK(!gdakiMiLogXParse(u.data(), u.size(), &px, why, sizeof(why)) && strstr(why, "rkey list") != nullptr);
  }
  // random byte flips: refused or parsed, never a fault
  std::mt19937 rng(5);
  for (int run = 0; run < 20000; run++) {
    std::vector<uint8_t> t(b);
    const int k = 1 + (int)(rng() % 4);
    for (int i = 0; i < k; i++) t[rng() % t.size()] ^= (uint8_t)(1u << (rng() % 8));
    (void)gdakiMiLogXParse(t.data(), t.size(), &px, why, sizeof(why));
    CHECK(memchr(why, '\0', sizeof(why)) != nullptr);
  }
}

// A restore of rank 2 of 4 from checkpoint 10: survivors 0, 1, 3; this rank's windows 1 (64 KiB) and 2 (1 MiB); a
// signal table of 4 KiB; FETCH extents of each sender's segments (mif::gdakiMiFetched).
struct World {
  int me = 2, nranks = 4;
  uint64_t ckpt = 10;
  uint32_t inc = 1;
  std::vector<int> nqpOf{1, 2, 0, 1};
  std::vector<uint64_t> pData[4];
  std::vector<struct gdakiRsImportP> pp;
  std::vector<struct gdakiRsImportWin> wins{{1, 65536}, {2, 1u << 20}};
  uint64_t sigBytes = 4096;
  std::vector<uint8_t> buf;  // the FETCH buffer
  mif::gdakiMiFetched f;
  World() {
    pData[0] = {3};
    pData[1] = {4, 5};
    pData[3] = {6};
    for (int q : {0, 1, 3}) pp.push_back({q, (uint32_t)nqpOf[(size_t)q], pData[q].data()});
    // extents: sender 0 segment 3 (8 KiB), sender 1 segment 7 (4 KiB) and segment 8 (4 KiB), sender 3 segment 1 (4 KiB)
    const struct {
      int s;
      uint64_t seg, fill;
    } ext[] = {{0, 3, 8192}, {1, 7, 4096}, {1, 8, 4096}, {3, 1, 4096}};
    uint64_t off = 1 << 16;  // the slot first
    for (const auto& e : ext) {
      mif::gdakiMiActExt x;
      memset(&x, 0, sizeof(x));
      x.seg = e.seg;
      x.sender = e.s;
      x.fill = e.fill;
      x.closedAt = GDAKI_MI_OPEN;
      f.ext.push_back(x);
      f.bufOff.push_back(off);
      off += (e.fill + 63) & ~63ull;
    }
    buf.assign(off, 0);
    for (size_t i = 0; i < buf.size(); i++) buf[i] = (uint8_t)(i * 131 + 7);
    f.buf = buf.data();
    f.ckpt = ckpt;
  }
  const uint8_t* at(int s, uint64_t seg, uint64_t o) const {  // independent of gdakiMiFetchedAt
    for (size_t i = 0; i < f.ext.size(); i++)
      if (f.ext[i].sender == s && f.ext[i].seg == seg) return buf.data() + f.bufOff[i] + o;
    return nullptr;
  }
  std::vector<std::vector<uint8_t>> exports;
  bool plan(struct gdakiMiImportPlan* out, char* why, size_t whyLen) const {
    auto fetch = [this](int s, uint64_t seg, uint64_t off, uint64_t bytes) {
      return mif::gdakiMiFetchedAt(f, s, seg, off, bytes);
    };
    return gdakiMiImportPlanOf(me, ckpt, inc, NONCE, nqpOf.data(), nranks, pp.data(), (int)pp.size(), exports, wins.data(),
                               (int)wins.size(), sigBytes, fetch, out, why, whyLen);
  }
};
static struct XSpec specFor(const World& w, int q) {
  struct XSpec s;
  s.from = q;
  s.to = w.me;
  s.incarnation = w.inc;
  s.nqp = (uint32_t)w.nqpOf[(size_t)q];
  s.ckpt = w.ckpt;
  for (uint32_t k = 0; k < s.nqp; k++) {
    s.x[k] = w.pData[q][k] + 10 + k;
    s.m[k] = 100 + k;
  }
  s.keys.push_back({GDAKI_RS_RKEY_WINDOW, 1, 0x100u + (uint32_t)q, 0});
  s.keys.push_back({GDAKI_RS_RKEY_WINDOW, 2, 0x200u + (uint32_t)q, 0});
  s.keys.push_back({GDAKI_MI_RKEY_POOL, 0, 0x300u + (uint32_t)q, 0});
  return s;
}
static void build(World& w, const struct XSpec& s0, const struct XSpec& s1, const struct XSpec& s3) {
  w.exports.assign(4, std::vector<uint8_t>());
  w.exports[0] = buildX(s0);
  w.exports[1] = buildX(s1);
  w.exports[3] = buildX(s3);
}
static void testPlan() {
  World w;
  struct XSpec s0 = specFor(w, 0), s1 = specFor(w, 1), s3 = specFor(w, 3);
  // step 11: sender 0's put (segment 3 lane offset 0) with a signal on table word 64; sender 1's put of segment 7
  // step 12: sender 0's second put (segment 3, offset 4096 = word 64) and a putValue; sender 3's put with a VA signal
  // step 14: sender 1's put from segment 8 with a signal on the same table word 64 (summed with nothing in its step)
  s0.ents = {mput(11, 3, 0, 2, 0, 4096, true, 0, 64, 1), mput(12, 3, 64, 2, 4096, 100), pval(12, 1, 0, 0xabc)};
  s1.ents = {mput(11, 7, 0, 2, 8192, 4096), mput(14, 8, 0, 2, 8192, 4000, true, 0, 64, 3), sigOnly(14, 0, 64, 4)};
  s3.ents = {mput(12, 1, 0, 1, 1024, 64, true, 1, 32768, 2), sigOnly(11, 0, 64, 5)};
  build(w, s0, s1, s3);
  struct gdakiMiImportPlan p;
  char why[300];
  CHECK(w.plan(&p, why, sizeof(why)));
  if (nFail) fprintf(stderr, "plan: %s\n", why);
  CHECK(p.steps.size() == 3 && p.steps[0].step == 11 && p.steps[1].step == 12 && p.steps[2].step == 14);
  CHECK(p.entries == 8 && p.nMirror == 5 && p.mirrorBytes == 4096 + 100 + 4096 + 4000 + 64 && p.sigAdds == 5);
  CHECK(p.peers.size() == 3 && p.peers[0].rank == 0 && p.peers[1].rank == 1 && p.peers[2].rank == 3);
  CHECK(p.peers[1].nqp == 2 && p.peers[1].budget[0] == 10 && p.peers[1].budget[1] == 11 && p.peers[1].x[1] == 16 &&
        p.peers[1].m[1] == 101);
  CHECK(p.peers[0].mirValid && p.peers[0].mirX == 5 && p.peers[0].mirM == 7 && p.peers[0].keys.size() == 3);
  if (p.steps.size() == 3) {
    const auto& s11 = p.steps[0];
    // rank order then stream order: sender 0's put, then sender 1's
    CHECK(s11.copies.size() == 2 && s11.copies[0].data == w.at(0, 3, 0) && s11.copies[1].data == w.at(1, 7, 0));
    CHECK(s11.copies[0].win == 2 && s11.copies[0].off == 0 && s11.copies[0].bytes == 4096 && s11.poolBytes == 8192);
    CHECK(s11.sigs.size() == 1 && s11.sigs[0].win == 0 && s11.sigs[0].off == 64 && s11.sigs[0].add == 6);  // 1 + 5
    const auto& s12 = p.steps[1];
    CHECK(s12.copies.size() == 3 && s12.copies[0].data == w.at(0, 3, 4096) && s12.copies[1].data == nullptr &&
          s12.copies[1].value == 0xabc && s12.copies[1].bytes == 8 && s12.copies[2].data == w.at(3, 1, 0));
    CHECK(s12.sigs.size() == 1 && s12.sigs[0].win == 1 && s12.sigs[0].off == 32768 && s12.sigs[0].add == 2);
    CHECK(s12.valueBytes == 8 && s12.poolBytes == 164 && s12.entries == 3);
    const auto& s14 = p.steps[2];
    CHECK(s14.copies.size() == 1 && s14.copies[0].data == w.at(1, 8, 0) && s14.sigs.size() == 1 && s14.sigs[0].add == 7);
    // the data the plan points at is the fetched segment's
    CHECK(memcmp(s11.copies[0].data, w.buf.data() + w.f.bufOff[0], 4096) == 0);
  }
  uint64_t total = 0;
  CHECK(gdakiMiImportSigCheck(w.exports, p, &total, why, sizeof(why)) && total == 15);
  // the signal check against a plan that does not match the entries
  {
    struct gdakiMiImportPlan q = p;
    q.steps[0].sigs[0].add += 1;
    CHECK(!gdakiMiImportSigCheck(w.exports, q, &total, why, sizeof(why)));
    q = p;
    q.steps[2].sigs.clear();
    CHECK(!gdakiMiImportSigCheck(w.exports, q, &total, why, sizeof(why)));
    q = p;
    q.steps[1].sigs.push_back({1, 40000, 0});
    CHECK(!gdakiMiImportSigCheck(w.exports, q, &total, why, sizeof(why)));
    q = p;
    q.steps[0].step = 12;  // the step's signals moved to another step
    CHECK(!gdakiMiImportSigCheck(w.exports, q, &total, why, sizeof(why)));
    q = p;
    q.sigAdds++;
    CHECK(!gdakiMiImportSigCheck(w.exports, q, &total, why, sizeof(why)));
    q = p;
    std::swap(q.steps[0].sigs, q.steps[1].sigs);
    CHECK(!gdakiMiImportSigCheck(w.exports, q, &total, why, sizeof(why)));
  }
  auto refuses = [&](World& v, const char* phrase) {
    struct gdakiMiImportPlan q;
    char w2[300] = {0};
    const bool r = v.plan(&q, w2, sizeof(w2));
    CHECK(!r);
    if (phrase != nullptr && strstr(w2, phrase) == nullptr) {
      nFail++;
      fprintf(stderr, "FAIL plan refusal: want '%s', got '%s'\n", phrase, w2);
    }
    nChecks++;
  };
  // a step at or before the checkpoint
  { World v; struct XSpec a = s0; a.ents[0].step = 10; build(v, a, s1, s3); refuses(v, "not after the checkpoint"); }
  // a MIRROR entry outside the fetched segments: another segment, past the fill, a sender's other segment
  { World v; struct XSpec a = s0; a.ents[0].seg = 4; build(v, a, s1, s3); refuses(v, "not in the fetched segments"); }
  { World v; struct XSpec a = s0; a.ents[1].e.csum = 127; build(v, a, s1, s3); refuses(v, "not in the fetched"); }
  { World v; struct XSpec a = s1; a.ents[0].seg = 3; build(v, s0, a, s3); refuses(v, "not in the fetched segments"); }
  { World v; struct XSpec a = s3; a.ents[0].e.bytes = 4097; a.ents[0].e.dstOff = 0; build(v, s0, s1, a); refuses(v, "fetched"); }
  // a target outside this process's windows; an unaligned signal; a signal past the table
  { World v; struct XSpec a = s0; a.ents[0].e.dstOff = (1u << 20) - 64; build(v, a, s1, s3); refuses(v, "not a window"); }
  { World v; struct XSpec a = s0; a.ents[0].e.dstWin = 9; build(v, a, s1, s3); refuses(v, "not a window"); }
  { World v; struct XSpec a = s0; a.ents[0].e.sigOff = 66; build(v, a, s1, s3); refuses(v, "signal table"); }
  { World v; struct XSpec a = s1; a.ents[2].e.sigOff = 4096; build(v, s0, a, s3); refuses(v, "signal table"); }
  // a put over a signal word of the same step is refused; across steps it is not (the steps are applied in turn)
  {
    World v;
    struct XSpec a = s3;
    a.ents.push_back(mput(12, 1, 2, 1, 32768 - 8, 64));  // window 1 bytes 32760 .. 32823 over step 12's word 32768
    build(v, s0, s1, a);
    refuses(v, "overlaps the signal word");
    World u;
    struct XSpec c = s3;
    c.ents.push_back(mput(13, 1, 2, 1, 32768 - 8, 64));  // step 13: allowed
    build(u, s0, s1, c);
    struct gdakiMiImportPlan q;
    CHECK(u.plan(&q, why, sizeof(why)) && q.steps.size() == 4);
  }
  // the overlap check is per window (the reach of one window's data ranges never carries into the next window): step 12
  // gets a put in window 1 at 40000 (past window 1's signal word 32768) with a signal in window 2 at 4200, just past
  // window 2's step-12 data [4096, 4196): allowed; the same signal at 4192 (inside that range) is refused
  {
    World u;
    struct XSpec c = s3;
    c.ents.push_back(mput(12, 1, 3, 1, 40000, 64, true, 2, 4200, 9));
    build(u, s0, s1, c);
    struct gdakiMiImportPlan q;
    CHECK(u.plan(&q, why, sizeof(why)) && q.steps.size() == 3 && q.steps[1].step == 12 && q.steps[1].sigs.size() == 2);
    World v;
    struct XSpec d = s3;
    d.ents.push_back(mput(12, 1, 3, 1, 40000, 64, true, 2, 4192, 9));
    build(v, s0, s1, d);
    refuses(v, "overlaps the signal word");
  }
  // the export set and the restore's identity, as gin-restore's
  { World v; build(v, s0, s1, s3); v.exports[2] = v.exports[0]; refuses(v, "has no QP to this rank"); }
  { World v; build(v, s0, s1, s3); v.exports[3].clear(); refuses(v, "no log export from rank 3"); }
  { World v; struct XSpec a = s1; a.ckpt = 9; build(v, s0, a, s3); refuses(v, "not for this restore"); }
  { World v; struct XSpec a = s1; a.incarnation = 2; build(v, s0, a, s3); refuses(v, "not for this restore"); }
  { World v; struct XSpec a = s1; a.nqp = 1; build(v, s0, a, s3); refuses(v, "not for this restore"); }
  { World v; struct XSpec a = s1; a.to = 3; build(v, s0, a, s3); refuses(v, "not for this restore"); }
  { World v; struct XSpec a = s1; a.from = 0; build(v, s0, a, s3); refuses(v, "not for this restore"); }
  { World v; struct XSpec a = s1; a.x[1] = 4; build(v, s0, a, s3); refuses(v, "executed 4 at the hold start"); }
  { World v; build(v, s0, s1, s3); v.pp.pop_back(); refuses(v, "no P of rank 3"); }
  { World v; build(v, s0, s1, s3); v.pp.push_back(v.pp[0]); refuses(v, "two P records"); }
  { World v; build(v, s0, s1, s3); v.exports[1].push_back(0); refuses(v, "rank 1's export"); }
  // a survivor that refused its export
  { World v; struct XSpec a = s3; a.ok = false; build(v, s0, s1, a); refuses(v, "the survivor refused its export"); }
  // no entries at all: an empty plan (Resume then sends INJECTED at once)
  {
    World v;
    struct XSpec a = s0, b = s1, c = s3;
    a.ents.clear();
    b.ents.clear();
    c.ents.clear();
    build(v, a, b, c);
    struct gdakiMiImportPlan q;
    CHECK(v.plan(&q, why, sizeof(why)) && q.steps.empty() && q.peers.size() == 3 && q.entries == 0);
    CHECK(gdakiMiImportSigCheck(v.exports, q, &total, why, sizeof(why)) && total == 0);
  }
  // random plans: every entry lands in exactly one step, data from its own segment; the signal check agrees
  std::mt19937 rng(17);
  for (int run = 0; run < 400; run++) {
    World v;
    struct XSpec sp[4] = {specFor(v, 0), specFor(v, 1), XSpec(), specFor(v, 3)};
    uint64_t want = 0, sigs = 0, mirrored = 0;
    for (int q : {0, 1, 3}) {
      const int n = (int)(rng() % 12);
      for (int i = 0; i < n; i++) {
        const uint64_t step = v.ckpt + 1 + rng() % 6;
        const int kind = (int)(rng() % 3);
        if (kind == 0) {
          const uint64_t seg = q == 0 ? 3 : q == 1 ? (rng() % 2 ? 7 : 8) : 1;
          const uint32_t word = (uint32_t)(rng() % 32);
          const uint64_t bytes = 1 + rng() % 2048;
          sp[q].ents.push_back(mput(step, seg, word, 2, (rng() % 256) * 4096, bytes));
          mirrored++;
        } else if (kind == 1) {
          const uint64_t val = rng() % 100;
          sp[q].ents.push_back(sigOnly(step, 0, 8 * (rng() % 4), val));
          want += val;
          sigs++;
        } else {
          sp[q].ents.push_back(pval(step, 1, 8 * (rng() % 16), rng()));
        }
      }
    }
    build(v, sp[0], sp[1], sp[3]);
    struct gdakiMiImportPlan q;
    const bool ok = v.plan(&q, why, sizeof(why));
    CHECK(ok);
    if (!ok) continue;
    uint64_t ents = 0, sum = 0, sigAdds = 0;
    for (size_t k = 0; k < q.steps.size(); k++) {
      if (k > 0) CHECK(q.steps[k - 1].step < q.steps[k].step);
      CHECK(q.steps[k].step > v.ckpt && q.steps[k].entries > 0);
      ents += q.steps[k].entries;
      sigAdds += q.steps[k].sigAdds;
      for (const auto& s : q.steps[k].sigs) sum += s.add;
    }
    CHECK(ents == q.entries && sum == want && sigAdds == sigs && q.nMirror == mirrored);
    CHECK(gdakiMiImportSigCheck(v.exports, q, &total, why, sizeof(why)) && total == want);
  }
}
// the pacing: Resume injects up to ckpt + 1, Step(t) up to t + 1, in order; INJECTED names the last step
static void testPacing() {
  const uint64_t K = 10;
  {
    const std::vector<uint64_t> s{11, 12, 15};
    CHECK(gdakiMiPaceLast(s, K) == 15);
    size_t next = gdakiMiPaceEnd(s, 0, K + 1);
    CHECK(next == 1);
    next = gdakiMiPaceEnd(s, next, 11 + 1);
    CHECK(next == 2);
    CHECK(gdakiMiPaceEnd(s, next, 12 + 1) == 2 && gdakiMiPaceEnd(s, next, 13 + 1) == 2);
    CHECK(gdakiMiPaceEnd(s, next, 14 + 1) == 3);
    CHECK(gdakiMiPaceEnd(s, 0, 100) == 3);  // a Step far ahead takes every queued step at once, in order
  }
  CHECK(gdakiMiPaceLast({}, K) == K + 1 && gdakiMiPaceEnd({}, 0, K + 1) == 0);
  CHECK(gdakiMiPaceLast({K + 1}, K) == K + 1 && gdakiMiPaceEnd({K + 1}, 0, K + 1) == 1);
  CHECK(gdakiMiPaceLast({K + 3}, K) == K + 3 && gdakiMiPaceEnd({K + 3}, 0, K + 1) == 0);
  // an application that calls Step(t) for every t = K + 1, K + 2, ... (requirement 7): each queued step s is injected
  // exactly at Resume (s = K + 1) or at Step(s - 1), so before the kernels of s and not earlier; INJECTED right after the
  // call that injected the last one
  std::mt19937 rng0(29);
  for (int run = 0; run < 5000; run++) {
    std::vector<uint64_t> s;
    for (uint64_t t = K + 1; t < K + 30; t++)
      if (rng0() % 3 == 0) s.push_back(t);
    std::vector<uint64_t> when(s.size(), ~0ull);
    size_t next = gdakiMiPaceEnd(s, 0, K + 1);
    for (size_t i = 0; i < next; i++) when[i] = K;  // K: Resume
    uint64_t readyAt = next == s.size() ? K : ~0ull;
    for (uint64_t t = K + 1; t < K + 40 && next < s.size(); t++) {
      const size_t e = gdakiMiPaceEnd(s, next, t + 1);
      for (size_t i = next; i < e; i++) when[i] = t;
      next = e;
      if (next == s.size()) readyAt = t;
    }
    CHECK(next == s.size());
    for (size_t i = 0; i < s.size(); i++) CHECK(when[i] == s[i] - 1);  // Resume is K = (K + 1) - 1
    const uint64_t last = gdakiMiPaceLast(s, K);
    CHECK(readyAt == last - 1);  // INJECTED at Resume when nothing after K + 1 is queued, else at Step(last - 1)
  }
  // a model: random queued steps and an application that skips some Step calls: every queued step is injected exactly
  // once, in increasing order, never earlier than at Step(s - 1) (when[i] + 1 >= s[i]); INJECTED once, after the last
  std::mt19937 rng(23);
  for (int run = 0; run < 5000; run++) {
    std::vector<uint64_t> s;
    for (uint64_t t = K + 1; t < K + 30; t++)
      if (rng() % 3 == 0) s.push_back(t);
    std::vector<uint64_t> when(s.size(), 0);  // the call that injected it (K: Resume)
    size_t next = gdakiMiPaceEnd(s, 0, K + 1);
    for (size_t i = 0; i < next; i++) when[i] = K;
    int injected = next == s.size() ? 1 : 0;
    uint64_t t = K;
    while (t < K + 40) {
      t += 1 + (rng() % 4 == 0 ? rng() % 3 : 0);
      if (next == s.size()) break;
      const size_t e = gdakiMiPaceEnd(s, next, t + 1);
      for (size_t i = next; i < e; i++) when[i] = t;
      next = e;
      if (next == s.size()) injected++;
    }
    CHECK(next == s.size() && injected == 1);
    for (size_t i = 0; i < s.size(); i++) {
      CHECK(when[i] + 1 >= s[i]);  // in before the kernels of step s[i] (they run after Step(s[i] - 1))
      if (i > 0) CHECK(when[i - 1] <= when[i]);
    }
    CHECK(gdakiMiPaceLast(s, K) == (s.empty() ? K + 1 : std::max(s.back(), K + 1)));
  }
}
static void testRkeyVerdict() {
  CHECK(gdakiMiRkeyVerdict(0, 5, 5) == GDAKI_MI_RKEY_SAME && gdakiMiRkeyVerdict(3, 5, 5) == GDAKI_MI_RKEY_SAME);
  CHECK(gdakiMiRkeyVerdict(0, 5, 6) == GDAKI_MI_RKEY_WARN);   // incarnation 0: the recorded value stays
  CHECK(gdakiMiRkeyVerdict(1, 5, 6) == GDAKI_MI_RKEY_WRITE);  // restored before: the list's value
}

int main() {
  testBuddyWards();
  testLanes();
  testCursor();
  testEntry();
  testQpSets();
  testLayout();
  testParse();
  testPlan();
  testPacing();
  testRkeyVerdict();
  printf("mi_unit_dev: %d checks, %d failed\n", nChecks, nFail);
  return nFail == 0 ? 0 : 1;
}
