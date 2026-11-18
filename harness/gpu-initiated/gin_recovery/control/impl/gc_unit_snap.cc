// gc_unit_snap.cc - CPU unit test of gin-control's mirror-off checkpoint pause as a GPU-side snapshot (the user's choice
// of 2026-10-22; impl/notes_snap.md). Cut out of the working tree's host file by build_gc_snap.sh `unit` (BR=snap): the
// region "gin-control (snap): pure" (gc_snap_pure.inc: the pause's and the after-pause copy plans, their byte counts,
// the device staging's busy state), gin-mirror's store pure region (mi_pure_store.inc: the uploader's machine
// gdakiStoreUp with its slot alternation, the buddy's ward record, the slot layout) and gin-restore's checkpoint pure
// region (rs_ckpt_pure.inc: gdakiCkptLayout). No NCCL, no CUDA, no verbs: a fake copy stream (copies queued, run at its
// synchronize, a synchronize that fails leaves them queued) and a fake store (the buddy's MR of two slots, the old MR
// kept while it holds the stable slot). g++ -std=c++17 with ASan and UBSan.
// What it checks:
//   1. the pause holds only the D2D step: over every take of 2. its copies are the plan's D2D copies, one per region,
//      their bytes the image's regions, and the pinned slot is not written in the pause (0 host-side bytes);
//   2. CKPT_STABLE's order over 200 random checkpoint sequences (the generator of gc_unit_p2b.cc's upload test: block
//      changes, blobs, new layouts, a restored buddy, failed WRITEs; here also several regions, a skipped or given-up
//      pause, a failed pause copy, a missing arm, a failed D2H, a missing confirmation, and the application's writes
//      right after the pause): a CKPT_STABLE of checkpoint k only after k's D2H and WRITE ended well, the WRITE never
//      into the buddy's stable slot, the stable slot always the full image of its checkpoint as it was in its pause, and
//      no pause while the device staging is busy;
//   3. the staging-busy scene: a D2H whose synchronize fails leaves the staging busy; the next checkpoint waits for the
//      copy stream before its pause (the old copies end first), and when the stream fails again no pause starts;
//   4. byte identity with 2b: the same sequences (the snapshot's own faults off) on 2b's path (D2H in the pause) and on
//      the snapshot path give the same bytes in every WRITE and the same stable slot;
//   5. the pause-byte model: a 20 MiB image of four regions: 2b's pause moves 20 MiB device-to-host, the snapshot's pause
//      0 B host-side and 20 MiB device-to-device; the ratio is printed; the device staging of the memory line.
#include <algorithm>
#include <atomic>
#include <cerrno>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <map>
#include <random>
#include <string>
#include <vector>

#include <fcntl.h>
#include <netinet/in.h>
#include <poll.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

// What gin-mirror's headers and the cut text need from nccl.h and the host file (as gc_unit_p2b.cc).
typedef enum { ncclSuccess = 0, ncclSystemError = 2, ncclInternalError = 3, ncclInvalidUsage = 5 } ncclResult_t;
typedef struct {
  unsigned int magic, nqp, qpn[64], remoteQpn[64], sqPsn[64];
  unsigned long long epochWqes[64];
} ncclGinRecoverToken_t;
#define NCCL_GIN_RECOVERY_MAX_QPS 64
union ncclSocketAddress {  // nccl socket.h
  struct sockaddr sa;
  struct sockaddr_in sin;
  struct sockaddr_in6 sin6;
};
enum class gdakiCause : int { Local = 0, PeerDead = 1, PeerLeft = 2, PeerReported = 3, Unknown = 4 };  // host file
static double gdakiQ4MonoMs() {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return t.tv_sec * 1e3 + t.tv_nsec * 1e-6;
}
#define GDAKI_MI_API_NO_ENTRY_DECLS
#define GDAKI_HOLD_API_NO_ENTRY_DECLS
#include "rs_hold_api.h"
#include "rs_mirror_api.h"
#include "rs_log_api.h"
#include "rs_ckpt_api.h"
#include "rs_store_api.h"
#include "rs_spare_api.h"
#include "rs_lineage_api.h"
#define NCCL_GIN_RS_LOG_PUT 1u
#define NCCL_GIN_RS_LOG_PUTVALUE 2u
#define NCCL_GIN_RS_LOG_SIGNAL 3u
#define NCCL_GIN_RS_LOGF_SIGNAL 0x01u
static inline uint32_t ncclGinRsEntryKind(uint32_t qpKf) { return (qpKf >> 24) & 3u; }
static inline uint32_t ncclGinRsEntryFlags(uint32_t qpKf) { return qpKf >> 26; }

static int nChecks = 0, nFail = 0;
#define CHECK(c) \
  do { nChecks++; if (!(c)) { nFail++; if (nFail < 30) printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)

#include "gc_ln4_sock.inc"   // struct gdakiTsMsg (the pure regions below name it)
#include "rs_ckpt_pure.inc"  // gdakiCkptLayout
#include "mi_pure_store.inc"
#include "gc_snap_pure.inc"

#if !NCCL_GIN_CTRL_TCP
static const uint64_t MiB = 1ull << 20;

// ---- the fake CUDA copy stream ----
struct FakeStream {
  struct Op {
    uint8_t* dst;
    const uint8_t* src;
    size_t n;
  };
  std::deque<Op> q;
  int failSyncs = 0;  // the next synchronizes that fail (their copies stay queued)
  void enq(uint8_t* d, const uint8_t* s, size_t n) { q.push_back({d, s, n}); }
  bool sync() {
    if (failSyncs > 0) {
      failSyncs--;
      return false;
    }
    for (const Op& o : q) memcpy(o.dst, o.src, o.n);
    q.clear();
    return true;
  }
};

// ---- the events of one rank (its order is what 2. checks) ----
enum { E_ASK = 1, E_WAIT, E_PAUSE_BEGIN, E_COPY, E_HOSTW, E_PAUSE_END, E_D2H, E_WRITE, E_STABLE };
struct Ev {
  int kind;
  uint64_t ckpt;
  uint32_t copyKind;  // E_COPY, E_D2H: GDAKI_SNAP_D2D, GDAKI_SNAP_D2H
  uint64_t bytes;
  bool ok;
};
struct Faults {  // one checkpoint's faults (drawn for both paths alike; the snapshot's own ones only there)
  bool skip = false, giveUp = false, pauseSyncFail = false, notArmed = false, writeFail = false, noConfirm = false;
  bool d2hFail = false, waitFail = false;  // the snapshot path only
};

static void fillHdr(struct gdakiCkptHdr* h, uint64_t ckpt, uint64_t img, int n, const uint64_t* off, const uint64_t* sz,
                    uint32_t blob) {
  memset(h, 0, sizeof(*h));
  h->magic = GDAKI_CKPT_MAGIC;
  h->version = GDAKI_CKPT_VERSION;
  h->ckpt = ckpt;
  h->baseCkpt = ~0ull;
  h->imageBytes = img;
  h->blockBytes = GDAKI_CKPT_BLOCK;
  h->nRegions = (uint32_t)n;
  for (int i = 0; i < n; i++) {
    h->region[i].kind = 1;
    h->region[i].id = (uint32_t)i;
    h->region[i].offset = off[i];
    h->region[i].bytes = sz[i];
  }
  h->blobBytes = blob;
}

// One mirror-off rank (its GPU regions, the pinned slot, the device staging, the copy stream, the uploader) and its
// buddy's store of it. snap: the snapshot path (this work package), else 2b's (D2H in the pause).
struct Rank {
  bool snap = true;
  std::vector<std::vector<uint8_t>> regions;
  std::vector<std::vector<std::vector<uint8_t>>> retired;
  int n = 0;
  uint64_t off[GDAKI_CKPT_MAX_REGIONS] = {}, sizes[GDAKI_CKPT_MAX_REGIONS] = {}, total = 0, layout = 0;
  std::vector<uint8_t> blob;
  struct gdakiSnapStage st;
  std::vector<uint8_t> dev;    // the device staging's bytes (st.dev points here)
  std::vector<uint8_t> stage;  // the pinned slot (gdakiStoreStage: a new buffer is zeroed, a fitting one reused)
  FakeStream cs;
  struct gdakiStoreUp up;
  struct gdakiStoreWardRec wr;  // the buddy's record of this rank
  std::vector<uint8_t> mr, oldMr;
  uint64_t gen = 0, seq = 0;
  uint32_t inc = 1;
  std::vector<Ev> ev;
  std::map<uint64_t, std::vector<uint8_t>> pauseImage;  // ckpt -> the regions' bytes at its pause, laid out
  std::map<uint64_t, std::vector<uint8_t>> pauseBlob;
  std::vector<uint8_t> lastWrite;  // the bytes of the last WRITE (identity with 2b)
  uint64_t lastWriteCkpt = 0;
  long long nStable = 0, nVoid = 0, nWaits = 0, nBackoffs = 0, nPauses = 0, pauseHostBytes = 0, pauseD2dBytes = 0;
};
static void serve(Rank& k) {  // the buddy serves a store request of this rank's layout (fake STORE_REQ and ACK)
  const uint64_t sb = gdakiStoreSlotBytes(k.total);
  const bool newMr = gdakiStoreNeedMr(k.wr, sb);
  const struct gdakiStoreCommit c = gdakiStoreWardServe(&k.wr, k.inc, ++k.seq, ++k.gen, newMr, 0x77, sb);
  if (c.freeOld) k.oldMr.clear();
  if (c.curToOld) k.oldMr = k.mr;
  if (newMr) k.mr.assign((size_t)gdakiStoreMrBytes(sb), 0);
  // the uploader's machine after an accepted ACK and a connected QP (its fields: the ACK's)
  k.up.reqOut = false;
  k.up.need = GDAKI_STORE_N_NONE;
  k.up.ready = true;
  k.up.gen = k.gen;
  k.up.slotBytes = k.wr.slotBytes;
  k.up.slotOff[0] = gdakiStoreSlotOff(k.wr.slotBytes, 0);
  k.up.slotOff[1] = gdakiStoreSlotOff(k.wr.slotBytes, 1);
  k.up.ackImage = k.total;
  k.up.ackLayout = k.layout;
  k.up.ackStable(k.wr.haveStable && !k.wr.stableInOld, k.wr.stableSlot);
}
static void newLayout(Rank& k, std::mt19937_64& rng, int nRegions) {
  // the old regions stay allocated (a copy still queued after a failed synchronize may read them; the application's
  // buffers outlive the checkpoint calls)
  k.retired.push_back(std::move(k.regions));
  k.n = nRegions;
  k.regions.assign((size_t)k.n, {});
  for (int i = 0; i < k.n; i++) {
    const uint64_t b = (uint64_t)(rng() % 3 ? (1 + rng() % 4) * GDAKI_CKPT_BLOCK : 0) + rng() % 5000 + 1;
    k.sizes[i] = b;
    k.regions[(size_t)i].resize((size_t)b);
    for (auto& x : k.regions[(size_t)i]) x = (uint8_t)rng();
  }
  CHECK(gdakiCkptLayout(k.sizes, k.n, k.off, &k.total) && k.total > 0);
  k.layout = 0x5a5a0000ull + k.total * 31 + (uint64_t)k.n;
}
static std::vector<uint8_t> laidOut(const Rank& k) {  // the regions laid out as the image (gaps 0)
  std::vector<uint8_t> img((size_t)k.total, 0);
  for (int i = 0; i < k.n; i++) memcpy(img.data() + k.off[i], k.regions[(size_t)i].data(), (size_t)k.sizes[i]);
  return img;
}
static const std::vector<uint8_t>& stableMr(const Rank& k) { return k.wr.stableInOld ? k.oldMr : k.mr; }
// The bytes of a slot a reader reads (the spare's FETCH: the header room, every region by the header, the blob).
static std::vector<uint8_t> maskOf(const uint8_t* slot, size_t used) {
  std::vector<uint8_t> m(used, 0);
  struct gdakiCkptHdr h;
  memcpy(&h, slot, sizeof(h));
  for (size_t i = 0; i < GDAKI_STORE_HDR_BYTES && i < used; i++) m[i] = 1;
  for (uint32_t r = 0; r < h.nRegions && r < GDAKI_CKPT_MAX_REGIONS; r++)
    for (uint64_t i = 0; i < h.region[r].bytes; i++)
      if (GDAKI_STORE_HDR_BYTES + h.region[r].offset + i < used) m[(size_t)(GDAKI_STORE_HDR_BYTES + h.region[r].offset + i)] = 1;
  for (uint32_t i = 0; i < h.blobBytes; i++)
    if (gdakiStoreBlobOff(h.imageBytes) + i < used) m[(size_t)(gdakiStoreBlobOff(h.imageBytes) + i)] = 1;
  return m;
}
static std::vector<uint8_t> readMask(const Rank& k) { return maskOf(k.lastWrite.data(), k.lastWrite.size()); }
static std::vector<uint8_t> stableMask(const Rank& k) {
  return maskOf(stableMr(k).data() + k.wr.stableOff, (size_t)k.wr.usedBytes);
}

// The application's writes after the pause (the device resumes): a few bytes of every region change.
static void mutate(Rank& k, std::mt19937_64& rng) {
  for (int i = 0; i < k.n; i++)
    for (int j = 0; j < 3; j++) k.regions[(size_t)i][(size_t)(rng() % k.sizes[i])] ^= (uint8_t)(1 + rng() % 255);
}

// One checkpoint: gdakiStoreTake's steps (the mirror off) with the helper's verdicts drawn in f, then CONFIRMING.
// mrng: the application's writes after the pause (the same draws on both paths). Returns 0 stable, 1 void, 2 backed off.
static int take(Rank& k, uint64_t ck, const Faults& f, std::mt19937_64& mrng) {
  const uint64_t slotBytes = gdakiStoreSlotBytes(k.total);
  const uint64_t used = gdakiStoreUsedBytes(k.total, (uint32_t)k.blob.size());
  if (k.snap) {
    if (k.st.busy) {  // gdakiSnapStageWait
      k.nWaits++;
      k.ev.push_back({E_WAIT, ck, 0, 0, true});
      if (f.waitFail) k.cs.failSyncs = 1;
      const bool synced = k.cs.sync();
      gdakiSnapReleased(&k.st, synced);
      CHECK(k.st.busy == !synced);
      if (!synced) {
        k.nBackoffs++;
        return 2;
      }
    }
  }
  if (k.stage.size() < slotBytes) k.stage.assign((size_t)slotBytes, 0);  // gdakiStoreStage (after the wait: no copy is queued)
  if (k.snap) {
    CHECK(!k.st.busy && k.cs.q.empty());
    if (!gdakiSnapStageFits(k.st, k.total)) {  // gdakiSnapStageAlloc (never while busy: the wait came first)
      CHECK(!k.st.busy && k.cs.q.empty());
      k.dev.assign((size_t)k.total, 0xee);
      k.st.dev = k.dev.data();
      k.st.bytes = k.total;
    }
  }
  k.ev.push_back({E_ASK, ck, 0, 0, true});
  if (f.skip) {
    k.nBackoffs++;
    return 2;
  }
  // inside the pause
  CHECK(!k.snap || (!k.st.busy && k.cs.q.empty()));  // no pause while the staging is busy
  k.nPauses++;
  k.ev.push_back({E_PAUSE_BEGIN, ck, 0, 0, true});
  k.pauseImage[ck] = laidOut(k);
  k.pauseBlob[ck] = k.blob;
  const std::vector<uint8_t> before = k.stage;
  struct gdakiSnapCopy plan[GDAKI_CKPT_MAX_REGIONS];
  int np = 0;
  if (k.snap) {
    np = gdakiSnapPausePlan(k.off, k.sizes, k.n, plan);
    gdakiSnapTaken(&k.st, ck);
    for (int i = 0; i < np; i++) {
      CHECK(plan[i].kind == GDAKI_SNAP_D2D && plan[i].region == (uint32_t)i && plan[i].dstOff == k.off[i] &&
            plan[i].srcOff == 0 && plan[i].bytes == k.sizes[i] && plan[i].dstOff + plan[i].bytes <= k.st.bytes);
      k.ev.push_back({E_COPY, ck, plan[i].kind, plan[i].bytes, true});
      k.cs.enq(k.dev.data() + plan[i].dstOff, k.regions[plan[i].region].data(), (size_t)plan[i].bytes);
    }
  } else {  // 2b: D2H of every region into the slot, the header and the blob, all in the pause
    for (int i = 0; i < k.n; i++) {
      k.ev.push_back({E_COPY, ck, GDAKI_SNAP_D2H, k.sizes[i], true});
      k.cs.enq(k.stage.data() + GDAKI_STORE_HDR_BYTES + k.off[i], k.regions[(size_t)i].data(), (size_t)k.sizes[i]);
    }
    fillHdr((struct gdakiCkptHdr*)k.stage.data(), ck, k.total, k.n, k.off, k.sizes, (uint32_t)k.blob.size());
    if (!k.blob.empty()) memcpy(k.stage.data() + gdakiStoreBlobOff(k.total), k.blob.data(), k.blob.size());
    k.ev.push_back({E_HOSTW, ck, 0, (uint64_t)sizeof(struct gdakiCkptHdr) + k.blob.size(), true});
  }
  if (f.pauseSyncFail) k.cs.failSyncs = 1;
  const bool synced = k.cs.sync();
  const bool ok = synced;
  if (k.snap) CHECK(k.stage == before);  // the pause wrote nothing into the pinned slot
  k.ev.push_back({E_PAUSE_END, ck, 0, 0, ok});
  const bool copied = !f.giveUp;
  if (k.snap && (!copied || !ok)) gdakiSnapReleased(&k.st, synced);
  if (!copied || !ok) {
    k.nVoid++;
    return 1;
  }
  const bool armed = !f.notArmed;
  if (k.snap && !armed) gdakiSnapReleased(&k.st, synced);
  if (!armed) {
    k.nVoid++;
    return 1;
  }
  mutate(k, mrng);  // the pause is over: the application writes its regions again
  if (k.snap) {     // after the pause: the snapshot into the slot, the header, the blob
    struct gdakiSnapCopy after[GDAKI_CKPT_MAX_REGIONS];
    const int na = gdakiSnapAfterPlan(k.off, k.sizes, k.n, after);
    CHECK(na == k.n);
    for (int i = 0; i < na; i++) {
      CHECK(after[i].kind == GDAKI_SNAP_D2H && after[i].dstOff == GDAKI_STORE_HDR_BYTES + k.off[i] &&
            after[i].srcOff == k.off[i] && after[i].bytes == k.sizes[i]);
      k.ev.push_back({E_D2H, ck, after[i].kind, after[i].bytes, true});
      k.cs.enq(k.stage.data() + after[i].dstOff, k.dev.data() + after[i].srcOff, (size_t)after[i].bytes);
    }
    fillHdr((struct gdakiCkptHdr*)k.stage.data(), ck, k.total, k.n, k.off, k.sizes, (uint32_t)k.blob.size());
    if (!k.blob.empty()) memcpy(k.stage.data() + gdakiStoreBlobOff(k.total), k.blob.data(), k.blob.size());
    if (f.d2hFail) k.cs.failSyncs = 1;
    const bool hs = k.cs.sync();
    gdakiSnapReleased(&k.st, hs);
    CHECK(k.st.busy == !hs);
    if (!hs) {  // no WRITE of a partial slot; the store stays ready
      k.ev.push_back({E_WRITE, ck, 0, 0, false});
      k.nVoid++;
      return 1;
    }
  }
  // the WRITE (2b's): into the receiving slot of the current store
  const bool began = k.up.beginWrite(k.total, k.layout);
  const uint32_t slot = k.up.recvSlot();
  bool wok = false;
  if (began) {
    CHECK(!(k.wr.haveStable && !k.wr.stableInOld && slot == k.wr.stableSlot));  // never into the stable slot
    if (!f.writeFail && k.wr.slotBytes >= used) {
      memcpy(k.mr.data() + gdakiStoreSlotOff(k.wr.slotBytes, slot), k.stage.data(), (size_t)used);
      k.lastWrite.assign(k.stage.begin(), k.stage.begin() + (ptrdiff_t)used);
      k.lastWriteCkpt = ck;
      wok = true;
    }
    k.up.endWrite(wok);
  }
  k.ev.push_back({E_WRITE, ck, 0, used, wok});
  if (!wok) {
    k.nVoid++;
    if (!k.up.ready) serve(k);  // the failed WRITE's new request (the QP went to ERR)
    return 1;
  }
  if (f.noConfirm) {  // a peer did not confirm: void; the written slot is not the stable one
    k.nVoid++;
    return 1;
  }
  // CKPT_STABLE: the buddy first
  bool freeOld = false;
  const int v = gdakiStoreWardStable(&k.wr, gdakiStoreStableOf(slot, k.gen, k.total, k.layout, (uint32_t)k.blob.size()), ck,
                                     &freeOld);
  CHECK(v == 0);
  if (freeOld) k.oldMr.clear();
  k.up.stableSent(slot, k.gen);
  k.ev.push_back({E_STABLE, ck, 0, 0, true});
  k.nStable++;
  return 0;
}

// The stable slot is the full image of its checkpoint as it was in its pause, the header and the blob its.
static void checkStable(const Rank& k) {
  if (!k.wr.haveStable) return;
  const std::vector<uint8_t>& m = stableMr(k);
  CHECK(m.size() >= k.wr.stableOff + k.wr.usedBytes);
  if (m.size() < k.wr.stableOff + k.wr.usedBytes) return;
  const uint8_t* s = m.data() + k.wr.stableOff;
  struct gdakiCkptHdr h;
  memcpy(&h, s, sizeof(h));
  CHECK(h.ckpt == k.wr.stableCkpt && h.imageBytes == k.wr.imageBytes && h.blobBytes == k.wr.blobBytes &&
        gdakiStoreUsedBytes(h.imageBytes, h.blobBytes) == k.wr.usedBytes);
  auto im = k.pauseImage.find(h.ckpt);
  auto bl = k.pauseBlob.find(h.ckpt);
  CHECK(im != k.pauseImage.end() && bl != k.pauseBlob.end());
  if (im == k.pauseImage.end() || bl == k.pauseBlob.end()) return;
  CHECK(im->second.size() == h.imageBytes);
  for (uint32_t i = 0; i < h.nRegions && i < GDAKI_CKPT_MAX_REGIONS; i++)
    CHECK(memcmp(s + GDAKI_STORE_HDR_BYTES + h.region[i].offset, im->second.data() + h.region[i].offset,
                 (size_t)h.region[i].bytes) == 0);
  CHECK(bl->second.size() == h.blobBytes &&
        (h.blobBytes == 0 || memcmp(s + gdakiStoreBlobOff(h.imageBytes), bl->second.data(), h.blobBytes) == 0));
}

// The order of one rank's events: the pause holds the D2D copies only; CKPT_STABLE of k after k's D2H and good WRITE.
static void checkOrder(const Rank& k, long long* pauseCopies) {
  std::map<uint64_t, int> st;  // per ckpt: 1 in the pause, 2 after it, 3 D2H seen, 4 WRITE ok
  bool inPause = false;
  for (const Ev& e : k.ev) {
    switch (e.kind) {
      case E_PAUSE_BEGIN: CHECK(!inPause); inPause = true; st[e.ckpt] = 1; break;
      case E_COPY:
        CHECK(inPause && st[e.ckpt] == 1);
        if (k.snap) CHECK(e.copyKind == GDAKI_SNAP_D2D);
        (*pauseCopies)++;
        break;
      case E_HOSTW: CHECK(!k.snap && inPause); break;
      case E_PAUSE_END: CHECK(inPause); inPause = false; st[e.ckpt] = 2; break;
      case E_D2H: CHECK(k.snap && !inPause && st[e.ckpt] >= 2 && st[e.ckpt] <= 3); st[e.ckpt] = 3; break;
      case E_WRITE:
        CHECK(!inPause && st[e.ckpt] == (k.snap ? 3 : 2));
        if (e.ok) st[e.ckpt] = 4;
        break;
      case E_STABLE: CHECK(!inPause && st[e.ckpt] == 4); break;
      case E_WAIT: CHECK(!inPause); break;
      default: break;
    }
  }
  CHECK(!inPause);
}

static Faults drawFaults(std::mt19937_64& frng, bool snapFaults) {
  Faults f;
  f.skip = frng() % 14 == 0;
  f.giveUp = frng() % 16 == 0;
  const bool ps = frng() % 25 == 0;
  f.notArmed = frng() % 15 == 0;
  f.writeFail = frng() % 8 == 0;
  f.noConfirm = frng() % 18 == 0;
  const bool d = frng() % 9 == 0, w = frng() % 3 == 0;  // drawn always (both paths draw alike)
  if (snapFaults) {  // a failed synchronize leaves 2b's copies queued into the slot: not compared with the snapshot
    f.pauseSyncFail = ps;
    f.d2hFail = d;
    f.waitFail = w;
  }
  return f;
}

// ---- 1., 2., 4.: 200 random checkpoint sequences on both paths ----
static void testSequences(std::mt19937_64& rng) {
  long long stable = 0, voids = 0, waits = 0, backoffs = 0, pauses = 0, pauseCopies = 0, compared = 0, stableSame = 0;
  long long writesSnap = 0, wholeSame = 0, padDiff = 0;
  for (int seq = 0; seq < 400; seq++) {
    const bool snapFaults = seq >= 200;  // 0..199: identity with 2b; 200..399: the snapshot's own faults too
    const uint64_t seed = rng();
    std::mt19937_64 grng(seed), frng(seed ^ 0xf00d), mrngA(seed ^ 0xbeef), mrngB(seed ^ 0xbeef);
    Rank a, b;  // a: the snapshot path, b: 2b's
    a.snap = true;
    b.snap = false;
    const int n0 = 1 + (int)(grng() % 4);
    std::mt19937_64 g2 = grng;
    newLayout(a, grng, n0);
    newLayout(b, g2, n0);
    serve(a);
    serve(b);
    for (uint64_t ck = 1; ck <= 30; ck++) {
      // gc_unit_p2b.cc's generator: a new layout now and then, else a few block changes, a blob, a restored buddy
      const int what = (int)(grng() % 10);
      g2 = grng;
      if (what == 0) {
        const int nn = 1 + (int)(grng() % 4);
        g2 = grng;
        newLayout(a, grng, nn);
        newLayout(b, g2, nn);
        serve(a);
        serve(b);
      } else if (what < 8) {
        const int nb = (int)(grng() % 4);
        for (int j = 0; j < nb; j++) {
          const int r = (int)(grng() % a.n);
          const size_t o = (size_t)(grng() % a.sizes[r]);
          const uint8_t x = (uint8_t)(1 + grng() % 255);
          a.regions[(size_t)r][o] ^= x;
          b.regions[(size_t)r][o] ^= x;
        }
      }
      const size_t bl = (size_t)(grng() % 3000);
      a.blob.resize(bl);
      for (auto& x : a.blob) x = (uint8_t)grng();
      b.blob = a.blob;
      if (grng() % 9 == 0) {  // a restored buddy: a new process keeps nothing of this rank
        for (Rank* k : {&a, &b}) {
          k->inc++;
          k->wr = gdakiStoreWardRec();
          k->mr.clear();
          k->oldMr.clear();
          k->up.buddyRestored();
          serve(*k);
        }
      }
      const Faults f = drawFaults(frng, snapFaults);
      const int ra = take(a, ck, f, mrngA);
      checkStable(a);
      if (!snapFaults) {
        const int rb = take(b, ck, f, mrngB);
        checkStable(b);
        CHECK(ra == rb);
        // the same bytes written (the whole used range, the header room and the gaps too) and the same stable slot
        if (ra == 0 || (a.lastWriteCkpt == ck && b.lastWriteCkpt == ck)) {
          compared++;
          CHECK(a.lastWriteCkpt == b.lastWriteCkpt && a.lastWrite.size() == b.lastWrite.size());
          if (a.lastWrite.size() == b.lastWrite.size()) {
            // every byte a reader reads (the header room, every region, the blob) is 2b's; the padding between the
            // regions and after the image holds older checkpoints' bytes on both paths (2b's pause copies of a voided
            // checkpoint land there too, the snapshot's do not): counted, never inside what a reader reads
            const std::vector<uint8_t> mk = readMask(a);
            bool same = true, padSame = true;
            for (size_t i = 0; i < a.lastWrite.size(); i++)
              if (a.lastWrite[i] != b.lastWrite[i]) (mk[i] ? same : padSame) = false;
            CHECK(same);
            wholeSame += same && padSame;
            padDiff += same && !padSame;
          }
        }
        CHECK(a.wr.haveStable == b.wr.haveStable);
        if (a.wr.haveStable && b.wr.haveStable) {
          const std::vector<uint8_t>&ma = stableMr(a), &mb = stableMr(b);
          bool same = a.wr.stableCkpt == b.wr.stableCkpt && a.wr.usedBytes == b.wr.usedBytes;
          if (same) {
            const std::vector<uint8_t> mk = stableMask(a);
            for (size_t i = 0; i < mk.size() && same; i++)
              if (mk[i] && ma[a.wr.stableOff + i] != mb[b.wr.stableOff + i]) same = false;
          }
          CHECK(same);
          stableSame += same;
        }
        CHECK(a.regions == b.regions);  // the application's writes after the pause drew alike
      }
    }
    checkOrder(a, &pauseCopies);
    if (!snapFaults) {
      long long dummy = 0;
      checkOrder(b, &dummy);
    }
    stable += a.nStable;
    voids += a.nVoid;
    waits += a.nWaits;
    backoffs += a.nBackoffs;
    pauses += a.nPauses;
    for (const Ev& e : a.ev) writesSnap += e.kind == E_WRITE && e.ok;
  }
  CHECK(stable > 1000 && waits > 10 && compared > 1000);
  printf("  sequences: 400 x 30 checkpoints (200 against 2b, 200 with the snapshot's own faults): pauses %lld (D2D copies "
         "%lld, nothing else), stable %lld, void %lld, backed off %lld, staging-busy waits %lld, WRITEs %lld; identity "
         "with 2b: %lld WRITEs compared, every byte a reader reads the same (%lld whole slots byte for byte, %lld with "
         "other stale padding), %lld stable slots the same\n",
         pauses, pauseCopies, stable, voids, backoffs, waits, writesSnap, compared, wholeSame, padDiff, stableSame);
}

// ---- 3. the staging-busy scene ----
static void testBusy(std::mt19937_64& rng) {
  Rank k;
  newLayout(k, rng, 3);
  serve(k);
  std::mt19937_64 m(7);
  k.blob = {1, 2, 3};
  Faults f;
  CHECK(take(k, 1, f, m) == 0 && !k.st.busy);
  // checkpoint 2: the D2H's synchronize fails: void, the staging stays busy, its copies stay queued
  f.d2hFail = true;
  CHECK(take(k, 2, f, m) == 1 && k.st.busy && k.st.busyCkpt == 2 && k.cs.q.size() == (size_t)k.n);
  const size_t evBefore = k.ev.size();
  // checkpoint 3: the stream fails again in the wait: no pause (backed off), still busy
  f = Faults();
  f.waitFail = true;
  CHECK(take(k, 3, f, m) == 2 && k.st.busy && k.nWaits == 1);
  CHECK(k.ev.size() == evBefore + 1 && k.ev.back().kind == E_WAIT);  // no ASK, no pause
  // checkpoint 4: the wait ends the old copies first, then the pause; stable, the slot is checkpoint 4's
  f = Faults();
  CHECK(take(k, 4, f, m) == 0 && !k.st.busy && k.nWaits == 2 && k.cs.q.empty());
  size_t w = 0, p = 0;
  for (size_t i = evBefore; i < k.ev.size(); i++) {
    if (k.ev[i].kind == E_WAIT && k.ev[i].ckpt == 4) w = i;
    if (k.ev[i].kind == E_PAUSE_BEGIN && k.ev[i].ckpt == 4) p = i;
  }
  CHECK(w > 0 && p > w);
  CHECK(k.wr.haveStable && k.wr.stableCkpt == 4);
  checkStable(k);
  // a not-armed or given-up checkpoint frees the staging at once (no wait next time)
  f = Faults();
  f.notArmed = true;
  CHECK(take(k, 5, f, m) == 1 && !k.st.busy);
  f = Faults();
  f.giveUp = true;
  CHECK(take(k, 6, f, m) == 1 && !k.st.busy);
  f = Faults();
  f.pauseSyncFail = true;  // the pause's own synchronize fails: busy (the stream's state is not known)
  CHECK(take(k, 7, f, m) == 1 && k.st.busy);
  f = Faults();
  CHECK(take(k, 8, f, m) == 0 && k.nWaits == 3 && !k.st.busy && k.wr.stableCkpt == 8);
  checkStable(k);
  long long dummy = 0;
  checkOrder(k, &dummy);
  // a larger image after a busy staging: the wait first, then the staging grows
  newLayout(k, rng, 4);
  while (k.total <= k.st.bytes) newLayout(k, rng, 4);
  serve(k);
  f = Faults();
  f.d2hFail = true;
  k.st.busy = false;
  (void)take(k, 9, f, m);
  f = Faults();
  newLayout(k, rng, 4);
  while (k.total <= k.st.bytes) newLayout(k, rng, 4);
  serve(k);
  CHECK(take(k, 10, f, m) == 0 && k.st.bytes == k.total && k.wr.stableCkpt == 10);
  checkStable(k);
  printf("  staging busy: a failed D2H leaves the staging busy; the next checkpoint waits for the copy stream before its "
         "pause (%lld waits; a failing stream: no pause), not-armed and given-up checkpoints free it at once\n",
         k.nWaits);
}

// ---- 5. the pause-byte model (20 MiB image) and the memory line's device staging ----
static void testModel() {
  const uint64_t sz[4] = {16 * MiB, 4 * MiB - 8192, 4096, 4096};  // window, registered buffer, signal and counter tables
  uint64_t off[4], total = 0, image = 0;
  for (uint64_t s : sz) image += s;
  CHECK(image == 20 * MiB);
  CHECK(gdakiCkptLayout(sz, 4, off, &total));
  struct gdakiSnapCopy p[GDAKI_CKPT_MAX_REGIONS], a[GDAKI_CKPT_MAX_REGIONS];
  const int np = gdakiSnapPausePlan(off, sz, 4, p), na = gdakiSnapAfterPlan(off, sz, 4, a);
  const struct gdakiSnapBytes pb = gdakiSnapBytesOf(p, np), ab = gdakiSnapBytesOf(a, na);
  const uint64_t b2Pause = image;  // 2b: every region D2H in the pause (gdakiStoreTake's loop)
  CHECK(np == 4 && na == 4 && pb.d2h == 0 && pb.d2d == image && ab.d2h == image && ab.d2d == 0);
  const uint32_t blob = 4096;
  const uint64_t b2HostW = sizeof(struct gdakiCkptHdr) + blob;  // 2b's header and blob writes in the pause (host memory)
  printf("  pause model (20 MiB image, 4 regions, layout %lu B): 2b's pause D2H %lu B (+ header and blob %lu B in host "
         "memory); the snapshot's pause D2D %lu B, host-side %lu B; host-side ratio %lu/%lu = %.3f; D2D bytes / image = "
         "%.3f; after the pause D2H %lu B (2b: 0)\n",
         (unsigned long)total, (unsigned long)b2Pause, (unsigned long)b2HostW, (unsigned long)pb.d2d, (unsigned long)pb.d2h,
         (unsigned long)pb.d2h, (unsigned long)b2Pause, (double)pb.d2h / (double)b2Pause, (double)pb.d2d / (double)image,
         (unsigned long)ab.d2h);
  CHECK(gdakiSnapDevBytes(true, total) == 0 && gdakiSnapDevBytes(false, total) == total);
  printf("  memory line: device staging %.2f MiB at the mirror off (0 at the mirror on), image layout %lu B\n",
         gdakiSnapDevBytes(false, total) / (double)MiB, (unsigned long)total);
  // the state rules alone
  struct gdakiSnapStage s;
  CHECK(!gdakiSnapStageFits(s, 1) && !s.busy);
  int dummy = 0;
  s.dev = &dummy;
  s.bytes = 100;
  CHECK(gdakiSnapStageFits(s, 100) && !gdakiSnapStageFits(s, 101));
  gdakiSnapTaken(&s, 9);
  CHECK(s.busy && s.busyCkpt == 9);
  gdakiSnapReleased(&s, false);
  CHECK(s.busy);
  gdakiSnapReleased(&s, true);
  CHECK(!s.busy);
  CHECK(gdakiSnapPausePlan(off, sz, 0, p) == 0);
}
#endif  // !NCCL_GIN_CTRL_TCP

int main() {
#if NCCL_GIN_CTRL_TCP
  printf("gc_unit_snap (tcp): the snapshot region is not in the tcp build: %d checks, %d failed\n", nChecks, nFail);
  return 0;
#else
  std::mt19937_64 rng(0x5a9a5a9aull);
  testSequences(rng);
  printf("  sequences: %d checks so far\n", nChecks);
  testBusy(rng);
  testModel();
  printf("gc_unit_snap (rdma): %d checks, %d failed\n", nChecks, nFail);
  return nFail == 0 ? 0 : 1;
#endif
}
