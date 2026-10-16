// gc_unit_p2b.cc - CPU unit test of gin-control's phase 2b (EXPERIMENT.md 9.1 "큰 자료", 9.7 decision 7, 9.8 phase 2;
// design v3 2.3, 2.8, 3.5; impl/notes_p2b.md): mi_unit_store.cc's approach widened in a file of its own. Cut out of the
// working tree's host file by build_gc_p2b.sh `unit` (BR=p2b): the region "gin-control (store): pure" (gc_store_pure.inc),
// the ctrl API block (gc_api.inc), phase 2a-1's ring model (gc_ring_model.inc: the outbox's halves), gin-mirror's store and
// spare pure regions (mi_pure_store.inc, mi_pure_spare.inc), gin-restore's checkpoint pure region (rs_ckpt_pure.inc: the
// TCP path's buddy store), ln4's TCP back end (gc_ln4_sock.inc: struct gdakiTsMsg and gdakiTsSend) and the tree's rkey
// list text with its TCP send and receive (gc_p2b_rs.inc). No NCCL, no CUDA, no verbs, no network: the NIC and the
// outbox are models in this file, the TCP text runs on AF_UNIX stream pairs. g++ -std=c++17 with ASan and UBSan.
// What it checks:
//   1. the outbox transfer head: pack and check round trip; every refusal code reached by one change;
//   2. the outbox halves (gdakiCtrlOutboxSt of phase 2a-1) carrying one transfer of any size, with the receiver late,
//      a repeated or foreign XFER refused, and the payload whole;
//   3. the STATE sequence (STATE_REQ, STATE, RKEYS) of one survivor and the spare over that model: the bytes the spare
//      keeps are ln4's data-socket bytes (n, then the export), the record is ln4's answer record byte for byte, the rkey
//      list is gdakiRsRkeysSend's bytes and gdakiRsRkeysRecv reads them back (the round trip through an outbox XFER);
//      the refusals (another incarnation, another pair, another nonce, a refused request, another checkpoint, a damaged
//      payload); the turn order (a survivor whose turn has not come sees nothing pending);
//   4. gdakiStoreWardToErr at the hold start: the rule over every (rank, dead) of n = 2..9, and a model of the buddies'
//      ward QPs with gin-mirror's ward record: the dead owner's QP is in ERR, a late WRITE of the dead process lands
//      nowhere, the stable slot and the FETCH stay, the owners that are alive keep their QPs, the hook is idempotent, the
//      successor's request gives a new QP that works;
//   5. the upload: for one checkpoint sequence (random block changes, blobs, layouts, failed uploads, a restored buddy)
//      the store path's stable slot (the whole image) and the TCP path's buddy store (changed blocks on its base,
//      gdakiCkptStore v1) hold the same image and blob after every stable checkpoint, and both FETCHes give those bytes;
//   6. the store-only activation blob (mirror off): the activation v2 rule, gin-mirror's encode, decode and check, the
//      store-only mode rule, the FETCH buffer's layout;
//   7. the host memory line's arithmetic (design v3 3.5: about 3I + 5 MiB per rank).
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
#include <thread>
#include <vector>

#include <fcntl.h>
#include <netinet/in.h>
#include <poll.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

// What gin-mirror's headers and the cut text need from nccl.h and the host file (as gc_unit_p2.cc).
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
// the device header's entry packing (as mi_unit_spare.cc: gin-mirror's spare pure region uses them)
static inline uint32_t ncclGinRsEntryKind(uint32_t qpKf) { return (qpKf >> 24) & 3u; }
static inline uint32_t ncclGinRsEntryFlags(uint32_t qpKf) { return qpKf >> 26; }

static int nChecks = 0, nFail = 0;
#define CHECK(c) do { nChecks++; if (!(c)) { nFail++; if (nFail <= 40) fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)

#if !NCCL_GIN_CTRL_TCP
#include "gc_ln4_sock.inc"   // struct gdakiTsMsg, gdakiTsSend (ln4's text)
#include "gc_p2b_rs.inc"     // gdakiRsIoAll, gdakiRsRkeysRecv, gdakiRsRkeysSend (the tree's text; the types: rs_spare_api.h)
#include "rs_ckpt_pure.inc"  // gdakiCkptStore v1, gdakiCkptChanged
#include "mi_pure_store.inc"
#include "mi_pure_spare.inc"
#include "gc_api.inc"
#include "gc_ring_model.inc"  // gdakiCtrlOutboxSt
#include "gc_store_pure.inc"

static const uint64_t MiB = 1ull << 20;
static const uint64_t HALF = GDAKI_CTRL_OUTBOX_HALF_BYTES;

static std::vector<uint8_t> randomBytes(std::mt19937_64& rng, size_t n) {
  std::vector<uint8_t> v(n);
  for (size_t i = 0; i < n; i++) v[i] = (uint8_t)rng();
  return v;
}

// ---- 1. the head ----
static void testHead(std::mt19937_64& rng) {
  CHECK(sizeof(struct gdakiCtrlXferHdr) == 64);
  CHECK(gdakiCtrlXferMax(GDAKI_CTRL_XK_STATE_REQ) == sizeof(struct gdakiTsMsg));
  CHECK(gdakiCtrlXferMax(GDAKI_CTRL_XK_RKEYS) == 32u + 4096u * 16u);  // 9.1: the rkey list <= 64 KiB (+ its header)
  CHECK(gdakiCtrlXferMax(0) == 0 && gdakiCtrlXferMax(5) == 0);
  for (int it = 0; it < 400; it++) {
    const uint16_t kind = (uint16_t)(1 + rng() % 4);
    const size_t n = (size_t)(rng() % std::min<uint64_t>(gdakiCtrlXferMax(kind), 9000));
    const std::vector<uint8_t> p = randomBytes(rng, n);
    const int from = (int)(rng() % 8), to = (int)(rng() % 8);
    const uint32_t inc = (uint32_t)rng();
    const uint64_t nonce = rng(), ckpt = rng();
    std::vector<uint8_t> b;
    gdakiCtrlXferPack(&b, kind, from, to, inc, nonce, ckpt, p.data(), p.size());
    CHECK(b.size() == 64 + n);
    struct gdakiCtrlXferHdr h;
    const uint8_t* pl = nullptr;
    CHECK(gdakiCtrlXferCheck(b.data(), b.size(), kind, from, to, nonce, inc, &h, &pl) == GDAKI_CTRL_XC_OK);
    CHECK(pl == b.data() + 64 && h.ckpt == ckpt && h.bytes == n && (n == 0 || memcmp(pl, p.data(), n) == 0));
    // every refusal by one change
    CHECK(gdakiCtrlXferCheck(b.data(), 63, kind, from, to, nonce, inc, &h, &pl) == GDAKI_CTRL_XC_SHORT);
    CHECK(gdakiCtrlXferCheck(b.data(), b.size(), (uint16_t)(kind % 4 + 1), from, to, nonce, inc, &h, &pl) == GDAKI_CTRL_XC_KIND);
    CHECK(gdakiCtrlXferCheck(b.data(), b.size(), kind, from + 1, to, nonce, inc, &h, &pl) == GDAKI_CTRL_XC_PEER);
    CHECK(gdakiCtrlXferCheck(b.data(), b.size(), kind, from, to + 1, nonce, inc, &h, &pl) == GDAKI_CTRL_XC_PEER);
    CHECK(gdakiCtrlXferCheck(b.data(), b.size(), kind, from, to, nonce + 1, inc, &h, &pl) == GDAKI_CTRL_XC_NONCE);
    CHECK(gdakiCtrlXferCheck(b.data(), b.size(), kind, from, to, nonce, inc + 1, &h, &pl) == GDAKI_CTRL_XC_INC);
    std::vector<uint8_t> c = b;
    c[0] ^= 1;
    CHECK(gdakiCtrlXferCheck(c.data(), c.size(), kind, from, to, nonce, inc, &h, &pl) == GDAKI_CTRL_XC_MAGIC);
    c = b;
    c[4] ^= 2;  // the version
    CHECK(gdakiCtrlXferCheck(c.data(), c.size(), kind, from, to, nonce, inc, &h, &pl) == GDAKI_CTRL_XC_MAGIC);
    c = b;
    c.push_back(0);  // a byte more than the head says
    CHECK(gdakiCtrlXferCheck(c.data(), c.size(), kind, from, to, nonce, inc, &h, &pl) == GDAKI_CTRL_XC_BYTES);
    if (n > 0) {
      c = b;
      c[64 + rng() % n] ^= (uint8_t)(1 + rng() % 255);
      CHECK(gdakiCtrlXferCheck(c.data(), c.size(), kind, from, to, nonce, inc, &h, &pl) == GDAKI_CTRL_XC_HASH);
    }
  }
  {  // above the kind's bound (a head that says so, with the bytes there)
    std::vector<uint8_t> p(sizeof(struct gdakiTsMsg) + 1, 7), b;
    gdakiCtrlXferPack(&b, GDAKI_CTRL_XK_STATE_REQ, 0, 1, 0, 0, 0, p.data(), p.size());
    struct gdakiCtrlXferHdr h;
    const uint8_t* pl;
    CHECK(gdakiCtrlXferCheck(b.data(), b.size(), GDAKI_CTRL_XK_STATE_REQ, 0, 1, 0, 0, &h, &pl) == GDAKI_CTRL_XC_BYTES);
  }
  for (uint32_t c = 0; c <= GDAKI_CTRL_XC_PAYLOAD; c++) CHECK(strcmp(gdakiCtrlXferWhy(c), "?") != 0);
}

// ---- 2. the outbox model: one transfer through the two halves of the giver's outbox ----
struct Wire {  // one direction of a pair: the giver's outbox, its XFERs in flight, the receiver's XFER_DONEs
  std::vector<uint8_t> outbox = std::vector<uint8_t>(2 * HALF);
  uint32_t rkey = 0x1234;
  struct gdakiCtrlOutboxSt giver, recv;
  std::deque<struct gdakiCtrlXfer> xfers, dones;
};
struct XferFaults {
  bool repeat = false, foreignRkey = false;
  int lateRecv = 0;  // the receiver skips this many turns first
};
// Moves `data` from giver to receiver; false when the model refused (the bytes then are not taken).
static bool xferRun(Wire& w, const std::vector<uint8_t>& data, std::vector<uint8_t>* out, std::mt19937_64& rng,
                    const XferFaults& f, int* refusals) {
  out->clear();
  uint64_t off = 0;
  bool first = true, end = false, sentAll = false;
  int late = f.lateRecv;
  for (int turn = 0; turn < 100000 && !end; turn++) {
    // giver: the next piece into a free half, or the XFER_DONEs
    if (!sentAll && (rng() & 1)) {
      const uint64_t piece = std::min<uint64_t>(HALF, data.size() - off);
      struct gdakiCtrlXfer x;
      const int h = gdakiCtrlOutboxTake(&w.giver, piece, w.rkey, off + piece >= data.size(), &x);
      if (h >= 0) {
        if (piece) memcpy(w.outbox.data() + (size_t)h * HALF, data.data() + off, piece);
        w.xfers.push_back(x);
        if (f.repeat && first) w.xfers.push_back(x);  // a repeated XFER (the model refuses the second)
        off += piece;
        first = false;
        if (off >= data.size()) sentAll = true;
      }
    }
    while (!w.dones.empty()) {
      CHECK(gdakiCtrlOutboxDone(&w.giver, w.dones.front()));
      w.dones.pop_front();
    }
    // receiver: one XFER (READ of the half, XFER_DONE)
    if (late > 0) { late--; continue; }
    if (!w.xfers.empty() && (rng() % 3) != 0) {
      const struct gdakiCtrlXfer x = w.xfers.front();
      w.xfers.pop_front();
      const uint32_t want = f.foreignRkey ? w.rkey + 1 : w.rkey;
      if (!gdakiCtrlOutboxAccept(&w.recv, x, want)) {
        (*refusals)++;
        if (f.foreignRkey) return false;
        continue;  // a repeat: dropped, the transfer goes on
      }
      out->insert(out->end(), w.outbox.data() + (size_t)x.half * HALF, w.outbox.data() + (size_t)x.half * HALF + x.bytes);
      w.dones.push_back(x);
      if (x.flags & GDAKI_CTRL_XFER_F_END) end = true;
    }
  }
  while (!w.xfers.empty()) {  // a stray XFER after the END (the repeat of the last piece): never READ
    CHECK(!gdakiCtrlOutboxAccept(&w.recv, w.xfers.front(), w.rkey));
    (*refusals)++;
    w.xfers.pop_front();
  }
  while (!w.dones.empty()) {
    CHECK(gdakiCtrlOutboxDone(&w.giver, w.dones.front()));
    w.dones.pop_front();
  }
  CHECK(!w.giver.busy[0] && !w.giver.busy[1]);  // every half free again at its XFER_DONE
  return end;
}
static void testOutbox(std::mt19937_64& rng) {
  const uint64_t sizes[] = {0, 1, 64, 1871, HALF - 1, HALF, HALF + 1, 2 * HALF, 3 * HALF + 77, 5 * MiB / 2};
  for (uint64_t n : sizes) {
    for (int k = 0; k < 3; k++) {
      Wire w;
      const std::vector<uint8_t> d = randomBytes(rng, (size_t)n);
      std::vector<uint8_t> got;
      int refused = 0;
      XferFaults f;
      f.repeat = k == 1;
      f.lateRecv = k == 2 ? 50 : 0;
      CHECK(xferRun(w, d, &got, rng, f, &refused));
      CHECK(got == d);
      CHECK(refused == (f.repeat ? 1 : 0));
      // two transfers in a row on the same pair: the ids go on
      std::vector<uint8_t> d2 = randomBytes(rng, 100), got2;
      CHECK(xferRun(w, d2, &got2, rng, XferFaults(), &refused) && got2 == d2);
    }
  }
  Wire w;
  std::vector<uint8_t> got;
  int refused = 0;
  XferFaults f;
  f.foreignRkey = true;  // an XFER with another outbox's rkey is never READ
  CHECK(!xferRun(w, randomBytes(rng, 10), &got, rng, f, &refused) && refused == 1 && got.empty());
}

// ---- 3. the STATE sequence over the model, against ln4's data-socket bytes ----
static std::vector<uint8_t> readAll(int fd, size_t n) {
  std::vector<uint8_t> v(n);
  size_t off = 0;
  while (off < n) {
    struct pollfd pf = {fd, POLLIN, 0};
    if (poll(&pf, 1, 1000) != 1) break;
    const ssize_t k = recv(fd, v.data() + off, n - off, 0);
    if (k <= 0) break;
    off += (size_t)k;
  }
  v.resize(off);
  return v;
}
static void nonBlock(int fd) { (void)fcntl(fd, F_SETFL, fcntl(fd, F_GETFL) | O_NONBLOCK); }
// ln4's answer record (gdakiCkptSpareDataFd) through ln4's gdakiTsSend: its bytes on the socket.
static std::vector<uint8_t> ln4AnswerBytes(int me, uint64_t nonce, uint64_t step) {
  int sv[2];
  if (socketpair(AF_UNIX, SOCK_STREAM, 0, sv) != 0) return {};
  struct gdakiTsMsg a;
  memset(&a, 0, sizeof(a));
  a.type = GDAKI_TS_DATA;
  a.from = me;
  a.nonce = nonce;
  a.arg = me;
  a.round = step;
  const int rc = gdakiTsSend(sv[0], &a, 1000);
  std::vector<uint8_t> v = rc == 0 ? readAll(sv[1], sizeof(a)) : std::vector<uint8_t>();
  close(sv[0]);
  close(sv[1]);
  return v;
}
// ln4's rkey list on the data socket (gdakiRsRkeysSend): its bytes; and gdakiRsRkeysRecv over given bytes.
static std::vector<uint8_t> ln4RkeyBytes(const struct gdakiRsRkeys& k) {
  int sv[2];
  if (socketpair(AF_UNIX, SOCK_STREAM, 0, sv) != 0) return {};
  nonBlock(sv[0]);
  const size_t n = sizeof(struct gdakiRsRkeysHdr) + k.e.size() * sizeof(struct gdakiRsRkeyEntry);
  std::vector<uint8_t> v;
  std::thread rd([&] { v = readAll(sv[1], n); });
  const ncclResult_t rc = gdakiRsRkeysSend(sv[0], k, 2000);
  rd.join();
  close(sv[0]);
  close(sv[1]);
  if (rc != ncclSuccess) v.clear();
  return v;
}
static bool ln4RkeysRecv(const std::vector<uint8_t>& bytes, struct gdakiRsRkeys* out) {
  int sv[2];
  if (socketpair(AF_UNIX, SOCK_STREAM, 0, sv) != 0) return false;
  nonBlock(sv[1]);
  std::thread wr([&] {
    size_t off = 0;
    while (off < bytes.size()) {
      const ssize_t k = send(sv[0], bytes.data() + off, bytes.size() - off, 0);
      if (k <= 0) break;
      off += (size_t)k;
    }
  });
  char why[128];
  const bool ok = gdakiRsRkeysRecv(sv[1], 2000, out, why, sizeof(why)) == ncclSuccess;
  wr.join();
  close(sv[0]);
  close(sv[1]);
  return ok;
}
static struct gdakiRsRkeys randomKeys(std::mt19937_64& rng, int rank, uint32_t inc, uint64_t nonce, size_t n) {
  struct gdakiRsRkeys k;
  k.rank = rank;
  k.incarnation = inc;
  k.nonce = nonce;
  k.e.resize(n);
  for (auto& e : k.e) {
    e.kind = 1 + (uint32_t)(rng() % 3);
    e.id = (uint32_t)(rng() % 64);
    e.rkeyBe = (uint32_t)rng();
    e.pad = 0;
  }
  return k;
}
struct StateCase {
  int badInc = 0;       // 1: the spare's request names an older incarnation than the survivor knows
  bool refused = false; // the request's record has pad != 0
  bool otherCkpt = false;  // the STATE names another checkpoint than the request's
  bool otherPeer = false;  // a STATE of another survivor reaches the spare
  bool corrupt = false;    // a byte of the STATE's payload changed on the way
  bool otherNonce = false; // the request is another context's
};
// One survivor s and spare d: 0 done (exports and rkeys taken, compared), else the stage that refused (1 the request at
// the survivor, 2 the STATE at the spare, 3 the rkeys at the survivor).
static int stateRun(std::mt19937_64& rng, const StateCase& sc, int* sentStateBytes) {
  const int s = 1, d = 0;
  const uint64_t nonce = 0x5eed0000ull | (rng() & 0xffff), K = 40 + rng() % 200;
  const uint32_t incD = 1 + (uint32_t)(rng() % 5);  // the spare's own incarnation (the successor's)
  Wire toS, toD;  // d -> s (the spare's outbox), s -> d (the survivor's)
  int refusals = 0;
  // 1. d -> s STATE_REQ
  struct gdakiTsMsg a;
  gdakiCtrlStateReqFill(&a, d, sc.otherNonce ? nonce + 1 : nonce, K);
  if (sc.refused) a.pad = 7;
  std::vector<uint8_t> wire, got;
  gdakiCtrlXferPack(&wire, GDAKI_CTRL_XK_STATE_REQ, d, s, sc.badInc ? incD - 1 : incD, sc.otherNonce ? nonce + 1 : nonce, K,
                    &a, sizeof(a));
  CHECK(xferRun(toS, wire, &got, rng, XferFaults(), &refusals) && got == wire);
  // the record is ln4's answer record byte for byte
  if (!sc.refused && !sc.otherNonce) CHECK(memcmp(wire.data() + 64, ln4AnswerBytes(d, nonce, K).data(), sizeof(a)) == 0);
  struct gdakiTsMsg ra;
  uint32_t c = gdakiCtrlStateReqTake(got.data(), got.size(), d, s, nonce, incD, &ra);
  if (sc.badInc) { CHECK(c == GDAKI_CTRL_XC_INC); return 1; }
  if (sc.otherNonce) { CHECK(c == GDAKI_CTRL_XC_NONCE); return 1; }
  if (sc.refused) { CHECK(c == GDAKI_CTRL_XC_REFUSED); return 1; }
  CHECK(c == GDAKI_CTRL_XC_OK && ra.round == K);
  // 2. s -> d STATE: the export (random bytes standing for gdakiRsLogExport's or gdakiMiLogExport's)
  const size_t xn = (size_t)(rng() % 4 == 0 ? rng() % (3 * HALF) : rng() % 5000);
  const std::vector<uint8_t> x = randomBytes(rng, xn);
  gdakiCtrlStatePack(&wire, sc.otherPeer ? s + 1 : s, d, incD, nonce, sc.otherCkpt ? K + 1 : K, x);
  if (sc.corrupt && xn > 0) wire[64 + 8 + rng() % xn] ^= 0x40;
  CHECK(xferRun(toD, wire, &got, rng, XferFaults(), &refusals) && got == wire);
  *sentStateBytes = (int)std::min<size_t>(wire.size(), 1u << 30);
  // its payload is ln4's data-socket stream: n (8 bytes) then the export
  {
    uint64_t n = 0;
    memcpy(&n, wire.data() + 64, 8);
    CHECK(n == xn && wire.size() == 64 + 8 + xn);
    if (!sc.corrupt) CHECK(xn == 0 || memcmp(wire.data() + 72, x.data(), xn) == 0);
  }
  std::vector<uint8_t> kept;
  c = gdakiCtrlStateTake(got.data(), got.size(), s, d, nonce, incD, K, &kept);
  if (sc.otherPeer) { CHECK(c == GDAKI_CTRL_XC_PEER && kept.empty()); return 2; }
  if (sc.otherCkpt) { CHECK(c == GDAKI_CTRL_XC_CKPT); return 2; }
  if (sc.corrupt && xn > 0) { CHECK(c == GDAKI_CTRL_XC_HASH); return 2; }
  CHECK(c == GDAKI_CTRL_XC_OK && kept == x);
  // 3. d -> s RKEYS: gdakiRsRkeysSend's bytes, read back by gdakiRsRkeysRecv
  const struct gdakiRsRkeys keys = randomKeys(rng, d, incD, nonce, (size_t)(rng() % 70));
  std::vector<uint8_t> kb;
  gdakiCtrlRkeysBytes(keys, &kb);
  const std::vector<uint8_t> tcp = ln4RkeyBytes(keys);
  CHECK(!tcp.empty() && kb == tcp);
  gdakiCtrlXferPack(&wire, GDAKI_CTRL_XK_RKEYS, d, s, keys.incarnation, nonce, 0, kb.data(), kb.size());
  CHECK(xferRun(toS, wire, &got, rng, XferFaults(), &refusals) && got == wire);
  struct gdakiRsRkeys back, viaTcp;
  c = gdakiCtrlRkeysTake(got.data(), got.size(), d, s, nonce, incD, &back);
  CHECK(c == GDAKI_CTRL_XC_OK);
  CHECK(back.rank == keys.rank && back.incarnation == keys.incarnation && back.nonce == keys.nonce &&
        back.e.size() == keys.e.size() &&
        (keys.e.empty() || memcmp(back.e.data(), keys.e.data(), keys.e.size() * sizeof(keys.e[0])) == 0));
  // the outbox payload through ln4's receiver gives the same list (the round trip)
  CHECK(ln4RkeysRecv(std::vector<uint8_t>(got.begin() + 64, got.end()), &viaTcp));
  CHECK(viaTcp.rank == keys.rank && viaTcp.e.size() == keys.e.size() &&
        (keys.e.empty() || memcmp(viaTcp.e.data(), keys.e.data(), keys.e.size() * sizeof(keys.e[0])) == 0));
  return 0;
}
static void testState(std::mt19937_64& rng) {
  int sent = 0;
  for (int i = 0; i < 60; i++) CHECK(stateRun(rng, StateCase(), &sent) == 0);
  StateCase c;
  c.badInc = 1;
  for (int i = 0; i < 5; i++) CHECK(stateRun(rng, c, &sent) == 1);
  c = StateCase(); c.refused = true;
  CHECK(stateRun(rng, c, &sent) == 1);
  c = StateCase(); c.otherNonce = true;
  CHECK(stateRun(rng, c, &sent) == 1);
  c = StateCase(); c.otherPeer = true;
  CHECK(stateRun(rng, c, &sent) == 2);
  c = StateCase(); c.otherCkpt = true;
  CHECK(stateRun(rng, c, &sent) == 2);
  c = StateCase(); c.corrupt = true;
  int damaged = 0;
  for (int i = 0; i < 20; i++) {
    const int r = stateRun(rng, c, &sent);  // an empty export has nothing to damage: then it goes through
    CHECK(r == 2 || r == 0);
    damaged += r == 2 ? 1 : 0;
  }
  CHECK(damaged > 10);
  {  // the request's record and the head disagree on K; the export's n is not its length; an rkey list too long
    struct gdakiTsMsg a;
    gdakiCtrlStateReqFill(&a, 0, 9, 50);
    std::vector<uint8_t> b;
    gdakiCtrlXferPack(&b, GDAKI_CTRL_XK_STATE_REQ, 0, 1, 3, 9, 51, &a, sizeof(a));
    struct gdakiTsMsg ra;
    CHECK(gdakiCtrlStateReqTake(b.data(), b.size(), 0, 1, 9, 3, &ra) == GDAKI_CTRL_XC_CKPT);
    a.type = GDAKI_TS_DATA + 1;
    gdakiCtrlXferPack(&b, GDAKI_CTRL_XK_STATE_REQ, 0, 1, 3, 9, 50, &a, sizeof(a));
    CHECK(gdakiCtrlStateReqTake(b.data(), b.size(), 0, 1, 9, 3, &ra) == GDAKI_CTRL_XC_RECORD);
    std::vector<uint8_t> pl(8 + 10, 1);
    uint64_t n = 11;
    memcpy(pl.data(), &n, 8);
    gdakiCtrlXferPack(&b, GDAKI_CTRL_XK_STATE, 1, 0, 3, 9, 50, pl.data(), pl.size());
    std::vector<uint8_t> x;
    CHECK(gdakiCtrlStateTake(b.data(), b.size(), 1, 0, 9, 3, 50, &x) == GDAKI_CTRL_XC_PAYLOAD);
    gdakiCtrlXferPack(&b, GDAKI_CTRL_XK_STATE, 1, 0, 3, 9, 50, pl.data(), 4);
    CHECK(gdakiCtrlStateTake(b.data(), b.size(), 1, 0, 9, 3, 50, &x) == GDAKI_CTRL_XC_PAYLOAD);
    struct gdakiRsRkeysHdr kh;
    memset(&kh, 0, sizeof(kh));
    kh.magic = GDAKI_RS_RKEYS_MAGIC;
    kh.version = 1;
    kh.count = GDAKI_RS_RKEYS_MAX + 1;
    gdakiCtrlXferPack(&b, GDAKI_CTRL_XK_RKEYS, 0, 1, 3, 9, 0, &kh, sizeof(kh));
    struct gdakiRsRkeys k;
    CHECK(gdakiCtrlRkeysTake(b.data(), b.size(), 0, 1, 9, 3, &k) == GDAKI_CTRL_XC_PAYLOAD);
    kh.count = 2;  // says 2, carries none
    gdakiCtrlXferPack(&b, GDAKI_CTRL_XK_RKEYS, 0, 1, 3, 9, 0, &kh, sizeof(kh));
    CHECK(gdakiCtrlRkeysTake(b.data(), b.size(), 0, 1, 9, 3, &k) == GDAKI_CTRL_XC_PAYLOAD);
    kh.count = 0;
    kh.version = 2;
    gdakiCtrlXferPack(&b, GDAKI_CTRL_XK_RKEYS, 0, 1, 3, 9, 0, &kh, sizeof(kh));
    CHECK(gdakiCtrlRkeysTake(b.data(), b.size(), 0, 1, 9, 3, &k) == GDAKI_CTRL_XC_PAYLOAD);
  }
  {  // the turn order: the spare takes survivors one at a time (rank order); a survivor's pair has nothing pending
     // until the spare's request on it, and the spare reads each survivor's STATE only on its own pair
    const int n = 6, d = 3;
    std::vector<int> pending(n, 0), done(n, 0);
    int turn = 0;
    std::vector<int> order;
    for (int q = 0; q < n; q++) if (q != d) order.push_back(q);
    pending[(size_t)order[0]] = 1;  // the spare starts the first turn (its STATE_REQ on that pair)
    int notYet = 0;
    for (int step = 0; step < 5000 && turn < (int)order.size(); step++) {
      const int q = order[(size_t)(rng() % order.size())];  // some survivor's helper step
      if (!pending[(size_t)q]) { CHECK(!done[(size_t)q] || turn > 0); notYet++; continue; }  // "not yet" (1)
      done[(size_t)q] = 1;  // its STATE goes, the spare takes it, sends the rkeys and moves on
      pending[(size_t)q] = 0;
      CHECK(q == order[(size_t)turn]);
      turn++;
      if (turn < (int)order.size()) pending[(size_t)order[(size_t)turn]] = 1;
    }
    CHECK(notYet > 0);
    CHECK(turn == (int)order.size());
    for (int q : order) CHECK(done[(size_t)q] == 1);
  }
}

// ---- 4. gdakiStoreWardToErr ----
struct WardQp {
  bool exists = false, err = false;
  uint64_t gen = 0;
  uint32_t inc = 0;  // the ward process it serves
};
struct StoreBuddy {  // rank b as a buddy: per ward its record, its slots' bytes, its side of the upload QP
  std::map<int, struct gdakiStoreWardRec> rec;
  std::map<int, WardQp> qp;
  std::map<int, std::vector<uint8_t>> mem;  // two slots
  uint64_t genNext = 1;
};
static void testWardErr(std::mt19937_64& rng) {
  // the rule
  for (int n = 1; n <= 9; n++)
    for (int me = 0; me < n; me++)
      for (int dead = -1; dead <= n; dead++) {
        const int b = (dead >= 0 && dead < n) ? gdakiHoldBuddyOf(dead, n) : -1;
        const bool want = n >= 2 && dead >= 0 && dead < n && dead != me && b == me;
        CHECK(gdakiCtrlStoreWardErrDue(me, n, dead, b) == want);
      }
  for (int n = 2; n <= 9; n++)  // every dead rank has exactly one buddy that acts
    for (int dead = 0; dead < n; dead++) {
      int acts = 0;
      for (int me = 0; me < n; me++) acts += gdakiCtrlStoreWardErrDue(me, n, dead, gdakiHoldBuddyOf(dead, n)) ? 1 : 0;
      CHECK(acts == 1);
    }
  // the model: n ranks, every rank a ward of its buddy; one image per ward in its buddy's store
  for (int n = 2; n <= 8; n++) {
    const uint64_t img = 4096 + (rng() % 8) * 4096;
    const uint64_t sb = gdakiStoreSlotBytes(img);
    std::vector<StoreBuddy> B((size_t)n);
    std::vector<uint32_t> inc((size_t)n, 0);
    auto serve = [&](int w) {  // ward w's STORE_REQ served at its buddy: a new QP (RTS), the MR once
      const int b = gdakiHoldBuddyOf(w, n);
      StoreBuddy& sb_ = B[(size_t)b];
      struct gdakiStoreWardRec& r = sb_.rec[w];
      const bool newMr = gdakiStoreNeedMr(r, sb);
      const uint64_t gen = sb_.genNext++;
      (void)gdakiStoreWardServe(&r, inc[(size_t)w], r.seq + 1, gen, newMr, 0x100u + (uint32_t)w, sb);
      if (newMr) sb_.mem[w].assign((size_t)(2 * sb), 0);
      WardQp& q = sb_.qp[w];
      q.exists = true;
      q.err = false;
      q.gen = gen;
      q.inc = inc[(size_t)w];
    };
    auto write = [&](int w, uint32_t fromInc, uint8_t fill, uint64_t ckpt) -> bool {  // a checkpoint WRITE + CKPT_STABLE
      const int b = gdakiHoldBuddyOf(w, n);
      StoreBuddy& sb_ = B[(size_t)b];
      WardQp& q = sb_.qp[w];
      struct gdakiStoreWardRec& r = sb_.rec[w];
      if (!q.exists || q.err || q.inc != fromInc) return false;  // an ERR QP (or another process's) takes nothing
      const uint32_t slot = gdakiStoreRecvSlot(r.haveStable ? (int)r.stableSlot : -1);
      memset(sb_.mem[w].data() + gdakiStoreSlotOff(r.slotBytes, slot), fill, (size_t)gdakiStoreUsedBytes(img, 0));
      bool freeOld = false;
      const struct gdakiStoreStable st = gdakiStoreStableOf(slot, q.gen, img, 0xabc, 0);
      return gdakiStoreWardStable(&r, st, ckpt, &freeOld) == 0;
    };
    auto fetch = [&](int w, uint8_t* fill) -> bool {  // the spare's FETCH of ward w's stable slot (the FETCH QP)
      const int b = gdakiHoldBuddyOf(w, n);
      StoreBuddy& sb_ = B[(size_t)b];
      const struct gdakiStoreWardRec& r = sb_.rec[w];
      if (!r.haveStable) return false;
      const uint8_t* p = sb_.mem[w].data() + r.stableOff;
      for (uint64_t i = 1; i < r.usedBytes; i++) if (p[i] != p[0]) return false;
      *fill = p[0];
      return true;
    };
    auto holdStart = [&](int dead) {  // every survivor's hold start of `dead`: gdakiCtrlPeerToErr -> gdakiStoreWardToErr
      for (int me = 0; me < n; me++) {
        if (me == dead) continue;
        for (int k = 0; k < 2; k++)  // idempotent: the hook may run twice
          if (gdakiCtrlStoreWardErrDue(me, n, dead, gdakiHoldBuddyOf(dead, n))) {
            WardQp& q = B[(size_t)me].qp[dead];
            if (q.exists && !q.err) q.err = true;
          }
      }
    };
    for (int w = 0; w < n; w++) serve(w);
    for (int w = 0; w < n; w++) CHECK(write(w, inc[(size_t)w], (uint8_t)(10 + w), 1));
    for (int round = 0; round < 6; round++) {
      const int dead = (int)(rng() % n);
      uint8_t before = 0;
      CHECK(fetch(dead, &before));
      holdStart(dead);
      for (int w = 0; w < n; w++) {
        const WardQp& q = B[(size_t)gdakiHoldBuddyOf(w, n)].qp[w];
        CHECK(q.exists && q.err == (w == dead));  // the dead owner's QP only; the owners alive keep theirs
      }
      // a late WRITE of the dead process (its zombie thread) lands nowhere; the other wards go on
      CHECK(!write(dead, inc[(size_t)dead], 0xEE, 100 + round));
      for (int w = 0; w < n; w++)
        if (w != dead) CHECK(write(w, inc[(size_t)w], (uint8_t)(20 + w + round), 100 + round));
      uint8_t after = 0;
      CHECK(fetch(dead, &after) && after == before);  // the stable slot is the FETCH's, untouched
      // the successor: a new incarnation's request, a new QP, its checkpoints land
      inc[(size_t)dead]++;
      serve(dead);
      CHECK(!B[(size_t)gdakiHoldBuddyOf(dead, n)].qp[dead].err);
      CHECK(!write(dead, inc[(size_t)dead] - 1, 0xEE, 200 + round));  // still not the old process's
      CHECK(write(dead, inc[(size_t)dead], (uint8_t)(30 + round), 200 + round));
      CHECK(fetch(dead, &after) && after == (uint8_t)(30 + round));
    }
  }
}

// ---- 5. the upload: the store path's slot against the TCP path's buddy store ----
struct Image {
  std::vector<uint8_t> data;
  std::vector<uint8_t> blob;
};
static void fillHdr(struct gdakiCkptHdr* h, uint64_t ckpt, uint64_t base, uint64_t img, uint64_t nChanged, uint32_t blob) {
  memset(h, 0, sizeof(*h));
  h->magic = GDAKI_CKPT_MAGIC;
  h->version = GDAKI_CKPT_VERSION;
  h->rank = 0;
  h->ckpt = ckpt;
  h->baseCkpt = base;
  h->imageBytes = img;
  h->blockBytes = GDAKI_CKPT_BLOCK;
  h->nRegions = 1;
  h->region[0].bytes = img;
  h->nChanged = nChanged;
  h->blobBytes = blob;
}
static void testUploadSame(std::mt19937_64& rng) {
  long tcpBytes = 0, storeBytes = 0;
  int stable = 0, compared = 0;
  for (int seq = 0; seq < 6; seq++) {
    uint64_t img = (uint64_t)(1 + rng() % 12) * GDAKI_CKPT_BLOCK + (rng() % 2 ? rng() % 4096 : 0);
    Image cur;
    cur.data = randomBytes(rng, (size_t)img);
    // TCP path: the uploader's base (block hashes) and the buddy's v1 store
    std::vector<uint64_t> baseHash;
    bool haveBase = false;
    uint64_t baseCkpt = 0;
    struct gdakiCkptStore tcp;
    // store path: the buddy's ward record and MR of two slots; the uploader's view of the stable slot
    struct gdakiStoreWardRec wr;
    std::vector<uint8_t> mr;
    uint64_t gen = 0, layout = 0x1000 + img;
    auto storeServe = [&]() {
      const uint64_t sb = gdakiStoreSlotBytes(img);
      const bool newMr = gdakiStoreNeedMr(wr, sb);
      (void)gdakiStoreWardServe(&wr, 0, wr.seq + 1, ++gen, newMr, 0x77, sb);
      if (newMr) mr.assign((size_t)gdakiStoreMrBytes(sb), 0);
    };
    storeServe();
    for (uint64_t ck = 1; ck <= 30; ck++) {
      // the application's changes: a few blocks, sometimes none, sometimes a new layout (size)
      const int what = (int)(rng() % 10);
      if (what == 0) {  // a new layout: the store is requested again, the TCP base is gone
        img = (uint64_t)(1 + rng() % 12) * GDAKI_CKPT_BLOCK + rng() % 4096;
        cur.data = randomBytes(rng, (size_t)img);
        layout = 0x1000 + img;
        storeServe();
      } else if (what < 8) {
        const int nb = (int)(rng() % 4);
        for (int k = 0; k < nb; k++) {
          const size_t o = (size_t)(rng() % img);
          cur.data[o] ^= (uint8_t)(1 + rng() % 255);
        }
      }
      cur.blob = randomBytes(rng, (size_t)(rng() % 3000));
      // a restored buddy (both paths: a new buddy process, no store of this rank; 9.6's base reset on the TCP path)
      if (rng() % 9 == 0) {
        tcp = gdakiCkptStore();
        haveBase = false;
        wr = gdakiStoreWardRec();
        mr.clear();
        storeServe();
      }
      const bool tcpFail = rng() % 8 == 0, storeFail = rng() % 8 == 0;
      // TCP path (gdakiCkptUploadOne's bytes): changed blocks against the base, the buddy applies them
      std::vector<uint64_t> h((size_t)gdakiCkptNBlocks(img));
      for (uint64_t i = 0; i < h.size(); i++)
        h[(size_t)i] = gdakiCkptHash(cur.data.data() + i * GDAKI_CKPT_BLOCK, (size_t)gdakiCkptBlockLen(i, img), GDAKI_CKPT_HASH_SEED);
      const std::vector<uint64_t> ch = gdakiCkptChanged(baseHash, haveBase, h);
      const bool full = !haveBase || baseHash.size() != h.size();
      struct gdakiCkptHdr hd;
      fillHdr(&hd, ck, full ? ~0ull : baseCkpt, img, ch.size(), (uint32_t)cur.blob.size());
      const char* why = "";
      bool tcpOk = tcp.begin(hd, &why);
      for (uint64_t i : ch) {
        tcpOk = tcpOk && tcp.block(i, cur.data.data() + i * GDAKI_CKPT_BLOCK, gdakiCkptBlockLen(i, img));
        tcpBytes += (long)gdakiCkptBlockLen(i, img);
      }
      if (tcpOk && !tcpFail) {
        tcp.finish(cur.blob.data(), (uint32_t)cur.blob.size());
        tcpOk = tcp.markStable(ck);
      } else {
        tcpOk = false;
      }
      haveBase = gdakiStoreTcpBaseAfterUpload(true, tcpOk);  // 9.6: a base only after an upload that ended stable
      if (tcpOk) { baseHash = h; baseCkpt = ck; }
      // store path (gdakiStoreTake's bytes): header, the whole image, the blob into the receiving slot
      const uint64_t used = gdakiStoreUsedBytes(img, (uint32_t)cur.blob.size());
      std::vector<uint8_t> stage((size_t)used, 0);
      fillHdr((struct gdakiCkptHdr*)stage.data(), ck, ~0ull, img, 0, (uint32_t)cur.blob.size());
      memcpy(stage.data() + GDAKI_STORE_HDR_BYTES, cur.data.data(), (size_t)img);
      if (!cur.blob.empty()) memcpy(stage.data() + gdakiStoreBlobOff(img), cur.blob.data(), cur.blob.size());
      const uint32_t slot = gdakiStoreRecvSlot(wr.haveStable ? (int)wr.stableSlot : -1);
      bool storeOk = false;
      if (!storeFail && wr.slotBytes >= used) {
        memcpy(mr.data() + gdakiStoreSlotOff(wr.slotBytes, slot), stage.data(), (size_t)used);
        storeBytes += (long)used;
        bool freeOld = false;
        storeOk = gdakiStoreWardStable(&wr, gdakiStoreStableOf(slot, gen, img, layout, (uint32_t)cur.blob.size()), ck,
                                       &freeOld) == 0;
      }
      if (tcpOk) stable++;
      // after every checkpoint stable on both paths: the same image and blob at the buddy, and the FETCHes agree
      if (tcpOk && storeOk) {
        compared++;
        CHECK(tcp.haveStable && tcp.stable.ckpt == ck && wr.haveStable && wr.stableCkpt == ck);
        const uint8_t* s = mr.data() + wr.stableOff;
        CHECK(tcp.stable.data.size() == img && memcmp(tcp.stable.data.data(), s + GDAKI_STORE_HDR_BYTES, (size_t)img) == 0);
        CHECK(tcp.stable.data == cur.data);
        CHECK(tcp.stable.blob.size() == cur.blob.size() && wr.blobBytes == cur.blob.size() &&
              (cur.blob.empty() || memcmp(s + gdakiStoreBlobOff(img), tcp.stable.blob.data(), cur.blob.size()) == 0));
        // the spare's FETCH from the store reads usedBytes from storeOff: its header is this checkpoint's
        struct gdakiCkptHdr fh;
        memcpy(&fh, s, sizeof(fh));
        CHECK(fh.ckpt == ck && fh.imageBytes == img && fh.blobBytes == cur.blob.size() &&
              gdakiStoreUsedBytes(fh.imageBytes, fh.blobBytes) == wr.usedBytes);
        CHECK(tcp.stable.hdr.ckpt == fh.ckpt && tcp.stable.hdr.imageBytes == fh.imageBytes &&
              tcp.stable.hdr.blobBytes == fh.blobBytes);
      }
    }
  }
  CHECK(compared > 20 && stable > compared - 1);
  printf("  upload: %d checkpoints compared stable on both paths; bytes uploaded TCP %ld (changed blocks), store %ld (whole "
         "slots)\n", compared, tcpBytes, storeBytes);
}

// ---- 6. the store-only activation blob ----
static void testBlob(std::mt19937_64& rng) {
  CHECK(gdakiCtrlStoreActV2Of(true, false) && gdakiCtrlStoreActV2Of(false, true) && gdakiCtrlStoreActV2Of(true, true) &&
        !gdakiCtrlStoreActV2Of(false, false));
  // with the v2 rule the spare REJOINs only after its FETCH's end, mirror or not (gdakiMiRejoinAllowed(mi, state))
  CHECK(!gdakiMiRejoinAllowed(true, GDAKI_MI_AS_WAIT) && gdakiMiRejoinAllowed(true, GDAKI_MI_AS_DONE));
  for (int it = 0; it < 200; it++) {
    const int n = 2 + (int)(rng() % 7), d = (int)(rng() % n);
    struct {  // impl/rs_store_api.h's gdakiMiActBlob (an entry-point type), as gdakiMiActBlobFor builds it with the mirror
              // off: no drain, no pool, no extents
      struct gdakiMiActHdr hdr;
      std::vector<struct gdakiMiActAddr> addr;
      std::vector<struct gdakiMiActExt> ext;
    } b;
    memset(&b.hdr, 0, sizeof(b.hdr));
    b.hdr.magic = GDAKI_MI_ACTB_MAGIC;
    b.hdr.version = GDAKI_MI_WIRE_VERSION;
    b.hdr.rank = d;
    b.hdr.incarnation = 1 + (uint32_t)(rng() % 4);
    b.hdr.nonce = rng();
    b.hdr.ckpt = 1 + rng() % 1000;
    b.hdr.nranks = b.hdr.nAddr = (uint32_t)n;
    b.hdr.nExt = 0;
    b.hdr.flags = GDAKI_MI_ACTB_F_STORE;
    const uint64_t img = (uint64_t)(1 + rng() % 64) * MiB;
    const uint32_t blob = (uint32_t)(rng() % GDAKI_CKPT_MAX_BLOB);
    b.hdr.storeRkey = (uint32_t)rng();
    b.hdr.storeSlot = (uint32_t)(rng() % 2);
    b.hdr.storeOff = b.hdr.storeSlot * gdakiStoreSlotBytes(img);
    b.hdr.imageBytes = img;
    b.hdr.blobBytes = blob;
    b.hdr.usedBytes = gdakiStoreUsedBytes(img, blob);
    b.hdr.wardIdx = ncclGinMiWardIdx(d, n);
    b.addr.assign((size_t)n, gdakiMiActAddr());
    for (int q = 0; q < n; q++) {
      memset(&b.addr[(size_t)q], 0, sizeof(b.addr[0]));
      b.addr[(size_t)q].rank = q == d ? -1 : q;
    }
    CHECK(gdakiCtrlStoreBlobModeOk(b.hdr, false) && gdakiCtrlStoreBlobModeOk(b.hdr, true));
    std::vector<uint8_t> bytes;
    CHECK(gdakiMiActBlobEncode(b.hdr, b.addr, b.ext, &bytes));
    struct gdakiMiActHdr h2;
    std::vector<struct gdakiMiActAddr> a2;
    std::vector<struct gdakiMiActExt> e2;
    CHECK(gdakiMiActBlobDecode(bytes.data(), bytes.size(), n, &h2, &a2, &e2) == 0 && e2.empty() && a2.size() == (size_t)n);
    const uint64_t cap = 512 * MiB;  // NCCL_GIN_RESTORE_MIRROR_FETCH_MB's default
    CHECK(gdakiMiActFits(h2, cap) == 0);
    CHECK(gdakiMiActCheck(h2, e2.data(), 0, d, b.hdr.incarnation, b.hdr.nonce, b.hdr.ckpt, cap) == 0);
    CHECK(gdakiMiAddrSelfOk(a2[(size_t)d]));
    uint64_t off[1];
    CHECK(gdakiMiFetchLayout(h2.usedBytes, nullptr, 0, off) == gdakiStoreRound4k(h2.usedBytes));
    // a pool part at a spare without the mirror: refused (12); with the mirror: gin-mirror's checks decide
    struct gdakiMiActHdr p = b.hdr;
    p.flags |= GDAKI_MI_ACTB_F_POOL;
    CHECK(!gdakiCtrlStoreBlobModeOk(p, false) && gdakiCtrlStoreBlobModeOk(p, true));
    p = b.hdr;
    p.nExt = 1;
    CHECK(!gdakiCtrlStoreBlobModeOk(p, false));
    p = b.hdr;
    p.poolRkey = 5;
    CHECK(!gdakiCtrlStoreBlobModeOk(p, false));
    p = b.hdr;
    p.flags = 0;  // no store part: gin-mirror's check refuses it too
    CHECK(!gdakiCtrlStoreBlobModeOk(p, false) &&
          gdakiMiActCheck(p, e2.data(), 0, d, b.hdr.incarnation, b.hdr.nonce, b.hdr.ckpt, cap) != 0);
  }
}

// ---- 7. the memory line ----
static void testMem() {
  const uint64_t imgs[] = {1 * MiB, 20 * MiB, 30 * MiB, 1000 * MiB};
  for (uint64_t I : imgs) {
    const struct gdakiCtrlStoreMem m = gdakiCtrlStoreMemOf(4, I, I, 1, true);
    CHECK(m.staging == gdakiStoreSlotBytes(I) && m.wards == 2 * gdakiStoreSlotBytes(I));
    CHECK(m.total == m.staging + m.wards + m.control);
    const double extra = ((double)m.total - 3.0 * (double)I) / (double)MiB;
    CHECK(extra > 3.0 && extra < 9.0);  // design v3 3.5: about 3I + 5 MiB at rank 4
    if (I == 20 * MiB)
      printf("  memory (rank 4, I = 20 MiB): staging %.2f MiB, ward store %.2f MiB, control %.2f MiB, total %.2f MiB = 3I + "
             "%.2f MiB\n", m.staging / (double)MiB, m.wards / (double)MiB, m.control / (double)MiB, m.total / (double)MiB,
             extra);
  }
  const struct gdakiCtrlStoreMem z = gdakiCtrlStoreMemOf(4, 0, 0, 1, false);
  CHECK(z.total == 0);
  CHECK(gdakiCtrlStoreMemOf(8, MiB, MiB, 1, true).control > gdakiCtrlStoreMemOf(4, MiB, MiB, 1, true).control);
}
#endif  // !NCCL_GIN_CTRL_TCP

int main() {
#if NCCL_GIN_CTRL_TCP
  printf("gc_unit_p2b (tcp): the store region and the outbox are not in the tcp build: %d checks, %d failed\n", nChecks,
         nFail);
  return 0;
#else
  std::mt19937_64 rng(0x2b2b2b2bull);
  testHead(rng);
  printf("  head: %d checks\n", nChecks);
  testOutbox(rng);
  printf("  outbox: %d checks so far\n", nChecks);
  testState(rng);
  printf("  state: %d checks so far\n", nChecks);
  testWardErr(rng);
  printf("  ward to ERR: %d checks so far\n", nChecks);
  testUploadSame(rng);
  testBlob(rng);
  testMem();
  printf("gc_unit_p2b (rdma): %d checks, %d failed\n", nChecks, nFail);
  return nFail == 0 ? 0 : 1;
#endif
}
