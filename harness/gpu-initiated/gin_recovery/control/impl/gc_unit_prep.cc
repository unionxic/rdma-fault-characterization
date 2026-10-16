// gc_unit_prep.cc - CPU unit test of gin-control's preparation stage (EXPERIMENT.md 9.8 "CPU 단위 모형", 준비). build_gc.sh
// `unit` cuts out of gin-mirror ln4's host file and out of the working tree's host file the TCP back end (struct
// gdakiTsMsg, struct gdakiTsPeer, gdakiTsErrName, gdakiTsSend, gdakiTsPumpRaw, gdakiTsPump: gc_ln4_sock.inc,
// gc_tree_sock.inc), the tree's two pasted blocks (gc_api.inc, gc_seams.inc) and the swap points' default-build bodies
// (gc_prep_fn.inc), and compiles them here twice: without the switch (rdma: gdakiCtrlSend and gdakiCtrlPump are the
// preparation stage's functions) and with -DNCCL_GIN_CTRL_TCP=1 (tcp: they are the macros that expand to today's calls).
// No NCCL, no CUDA, no verbs, no network: the sockets are AF_UNIX stream pairs in this process.
//   1. the same record sequence (every record type of ln4 and 52-55, random bodies, every channel) sent through ln4's
//      gdakiTsSend and through the tree's swap point gives the same bytes at the other end, byte for byte, also with a
//      reader that drains slowly (partial sends, EAGAIN); the sender's record after the send is the same too;
//   2. the same byte stream (records in random pieces, then a record with a bad magic, then a FIN) read through ln4's
//      gdakiTsPump and through the tree's gdakiCtrlPump gives the same results, records and close causes;
//   3. (rdma) the header's pure functions: the envelope, the order rule, the credit, the page layout and its words, the
//      seqlock line under a concurrent writer, the fence word, the endpoint versions, the pairing rule, the REJOIN nrp,
//      the confirmation window, the busy word, the thresholds, the QP attributes and the CQ sizes, the launcher's words;
//      and, when launcher/launcher_msg.h is present, that its envelope bytes are this one's and its relayed sizes are
//      gin-mirror's structs'.
#include <atomic>
#include <cerrno>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <random>
#include <string>
#include <thread>
#include <vector>
#include <algorithm>

#include <fcntl.h>
#include <netinet/in.h>
#include <poll.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

// What gin-mirror's headers and the cut text need from nccl.h and the host file (as build_mi.sh `api`'s headers.cc).
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
enum class gdakiCause : int { Local = 0, PeerDead = 1, PeerLeft = 2, PeerReported = 3, Unknown = 4 };  // host file 1336
static double gdakiQ4MonoMs() {  // host file 1313
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
#include "rs_ctrl_api.h"  // the header itself (the pure tests; the launcher cross-checks)

namespace ln4 {
#include "gc_ln4_sock.inc"
}
namespace tree {
#include "gc_tree_sock.inc"
#include "gc_api.inc"
#include "gc_seams.inc"
#if !NCCL_GIN_CTRL_TCP
#include "gc_prep_fn.inc"
#endif
}  // namespace tree

static int nChecks = 0, nFail = 0;
#define CHECK(c) do { nChecks++; if (!(c)) { nFail++; fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)

static void pairOf(int fd[2]) {
  if (socketpair(AF_UNIX, SOCK_STREAM, 0, fd) != 0) { perror("socketpair"); exit(2); }
  for (int i = 0; i < 2; i++) fcntl(fd[i], F_SETFL, fcntl(fd[i], F_GETFL, 0) | O_NONBLOCK);
}
static void readAll(int fd, std::vector<uint8_t>& out, size_t n) {
  out.resize(n);
  size_t off = 0;
  while (off < n) {
    struct pollfd pf = {fd, POLLIN, 0};
    (void)poll(&pf, 1, 1000);
    const ssize_t k = recv(fd, out.data() + off, n - off, MSG_DONTWAIT);
    if (k > 0) off += (size_t)k;
    else if (k == 0 || (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)) { out.resize(off); return; }
  }
}
// Every record type ln4 sends (1-19, 20, 32-38, 48-51) and the preparation stage's 52-55.
static const uint32_t kTypes[] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
                                  32, 33, 34, 35, 36, 37, 38, 48, 49, 50, 51, 52, 53, 54, 55};
template <typename M>
static void fillRandom(M* m, std::mt19937_64& rng, uint32_t type) {
  uint8_t* p = (uint8_t*)m;
  for (size_t i = 0; i < sizeof(*m); i++) p[i] = (uint8_t)rng();
  m->type = type;
  m->magic = (uint32_t)rng();  // gdakiTsSend writes the magic itself
}
// tree's swap point with one channel (the macro form ignores r, peer and ch; the function form takes them)
static int treeSend(uint32_t ch, int peer, int fd, tree::gdakiTsMsg* m, int tmo) {
  (void)peer;  // the tcp macro drops it
  switch (ch) {
    case 1: return tree::gdakiCtrlSend(nullptr, peer, GDAKI_CTRL_CH_RECORD, fd, m, tmo);
    case 2: return tree::gdakiCtrlSend(nullptr, peer, GDAKI_CTRL_CH_REJOIN, fd, m, tmo);
    default: return tree::gdakiCtrlSend(nullptr, -1, GDAKI_CTRL_CH_DATA, fd, m, tmo);
  }
}

// ---- 1. sends: the same bytes ----
static void testSend(std::mt19937_64& rng) {
  static_assert(sizeof(ln4::gdakiTsMsg) == 1872 && sizeof(tree::gdakiTsMsg) == 1872, "a record is 1872 B");
  int a[2], b[2];
  pairOf(a);
  pairOf(b);
  int nRec = 0;
  for (int round = 0; round < 40; round++) {
    for (uint32_t t : kTypes) {
      ln4::gdakiTsMsg m1;
      fillRandom(&m1, rng, t);
      tree::gdakiTsMsg m2;
      memcpy(&m2, &m1, sizeof(m2));
      const uint32_t ch = 1u + (uint32_t)(rng() % 3);
      const int r1 = ln4::gdakiTsSend(a[0], &m1, 1000);
      const int r2 = treeSend(ch, (int)(rng() % 4), b[0], &m2, 1000);
      CHECK(r1 == 0 && r2 == 0);
      CHECK(memcmp(&m1, &m2, sizeof(m1)) == 0);  // the sender's record after the send (the magic written)
      std::vector<uint8_t> x, y;
      readAll(a[1], x, sizeof(m1));
      readAll(b[1], y, sizeof(m2));
      CHECK(x.size() == sizeof(m1) && y.size() == sizeof(m2) && x == y);
      CHECK(memcmp(x.data(), &m1, sizeof(m1)) == 0);
      nRec++;
    }
  }
  // a burst bigger than the socket buffer with a reader that drains slowly: partial sends and EAGAIN on both paths
  for (int burst = 0; burst < 4; burst++) {
    const int n = 600;
    std::vector<ln4::gdakiTsMsg> seq(n);
    for (int i = 0; i < n; i++) fillRandom(&seq[i], rng, kTypes[rng() % (sizeof(kTypes) / sizeof(kTypes[0]))]);
    std::vector<uint8_t> gotA, gotB;
    std::atomic<bool> done{false};
    auto drain = [&](int fd, std::vector<uint8_t>* out) {
      std::vector<uint8_t> buf(777);
      while (true) {
        const ssize_t k = recv(fd, buf.data(), buf.size(), MSG_DONTWAIT);
        if (k > 0) {
          out->insert(out->end(), buf.begin(), buf.begin() + k);
          std::this_thread::sleep_for(std::chrono::microseconds(30));
        } else if (done.load() && out->size() >= (size_t)n * sizeof(ln4::gdakiTsMsg)) {
          return;
        } else {
          std::this_thread::sleep_for(std::chrono::microseconds(50));
        }
      }
    };
    std::thread ta(drain, a[1], &gotA), tb(drain, b[1], &gotB);
    int bad = 0;
    for (int i = 0; i < n; i++) {
      ln4::gdakiTsMsg m1 = seq[i];
      tree::gdakiTsMsg m2;
      memcpy(&m2, &seq[i], sizeof(m2));
      if (ln4::gdakiTsSend(a[0], &m1, 5000) != 0) bad++;
      if (treeSend(1u + (uint32_t)(i % 3), i % 4, b[0], &m2, 5000) != 0) bad++;
    }
    done.store(true);
    ta.join();
    tb.join();
    CHECK(bad == 0);
    CHECK(gotA.size() == (size_t)n * sizeof(ln4::gdakiTsMsg) && gotA == gotB);
    nRec += n;
  }
  // a closed peer: both fail alike (EPIPE through MSG_NOSIGNAL)
  close(a[1]);
  close(b[1]);
  ln4::gdakiTsMsg m1;
  fillRandom(&m1, rng, 2);
  tree::gdakiTsMsg m2;
  memcpy(&m2, &m1, sizeof(m2));
  CHECK(ln4::gdakiTsSend(a[0], &m1, 100) == -1 && treeSend(1, 1, b[0], &m2, 100) == -1);
  close(a[0]);
  close(b[0]);
  printf("send: %d records through ln4's gdakiTsSend and the tree's gdakiCtrlSend (%s): the same bytes\n", nRec,
         NCCL_GIN_CTRL_TCP ? "the tcp macro" : "the preparation stage's function");
}

// ---- 2. pumps: the same results ----
static void testPump(std::mt19937_64& rng) {
  int nRec = 0, nEnd = 0;
  for (int round = 0; round < 30; round++) {
    int a[2], b[2];
    pairOf(a);
    pairOf(b);
    const int n = 1 + (int)(rng() % 40);
    std::vector<uint8_t> stream;
    for (int i = 0; i < n; i++) {
      ln4::gdakiTsMsg m;
      fillRandom(&m, rng, kTypes[rng() % (sizeof(kTypes) / sizeof(kTypes[0]))]);
      m.magic = GDAKI_TS_MAGIC;
      const uint8_t* p = (const uint8_t*)&m;
      stream.insert(stream.end(), p, p + sizeof(m));
    }
    const bool badMagic = round % 3 == 1;
    if (badMagic) {
      ln4::gdakiTsMsg m;
      fillRandom(&m, rng, 2);
      m.magic = GDAKI_TS_MAGIC ^ 1u;
      const uint8_t* p = (const uint8_t*)&m;
      stream.insert(stream.end(), p, p + sizeof(m));
    }
    ln4::gdakiTsPeer pa;
    tree::gdakiTsPeer pb;
    pa.fd = a[1];
    pb.fd = b[1];
    std::vector<int> ra, rb;
    std::vector<std::vector<uint8_t>> ma, mb;
    size_t off = 0;
    bool closed = false;
    for (int step = 0; step < 100000; step++) {
      if (off < stream.size()) {  // the writer: a random piece to both
        const size_t k = std::min(stream.size() - off, (size_t)(1 + rng() % 3000));
        CHECK(send(a[0], stream.data() + off, k, MSG_NOSIGNAL) == (ssize_t)k);
        CHECK(send(b[0], stream.data() + off, k, MSG_NOSIGNAL) == (ssize_t)k);
        off += k;
      } else if (!closed) {
        close(a[0]);
        close(b[0]);
        closed = true;
      }
      ln4::gdakiTsMsg oa;
      tree::gdakiTsMsg ob;
      const int ga = ln4::gdakiTsPump(pa, &oa);
      const int gb = tree::gdakiCtrlPump(nullptr, 1, pb, &ob);
      CHECK(ga == gb);
      if (ga != 0) {
        ra.push_back(ga);
        rb.push_back(gb);
        ma.emplace_back((const uint8_t*)&oa, (const uint8_t*)&oa + sizeof(oa));
        mb.emplace_back((const uint8_t*)&ob, (const uint8_t*)&ob + sizeof(ob));
        if (ga == 1) nRec++;
      }
      if (ga < 0 || gb < 0) {
        CHECK(strcmp(pa.closeCause, pb.closeCause) == 0);
        CHECK(strcmp(pa.closeCause, badMagic ? "BADMAGIC" : "FIN") == 0);
        nEnd++;
        break;
      }
    }
    CHECK(ra == rb && ma == mb);
    CHECK((int)std::count(ra.begin(), ra.end(), 1) == n);
    close(a[1]);
    close(b[1]);
  }
  printf("pump: %d records and %d ends (FIN, BADMAGIC) through ln4's gdakiTsPump and the tree's gdakiCtrlPump: the same\n",
         nRec, nEnd);
}

#if !NCCL_GIN_CTRL_TCP
// ---- 3. the header's pure functions ----
static void testEnvelope(std::mt19937_64& rng) {
  struct gdakiCtrlEnv e;
  gdakiCtrlEnvPack(&e, GDAKI_CTRL_K_RECORD, 3, 7, 11, 5, 0x1234abcdull, 2, GDAKI_CTRL_RECORD_BYTES);
  CHECK(e.magic == GDAKI_CTRL_ENV_MAGIC && memcmp(&e, "GRCE", 4) == 0);
  CHECK(gdakiCtrlEnvCheck(&e, 0x1234abcdull, 64 + GDAKI_CTRL_RECORD_BYTES) == GDAKI_CTRL_ENV_OK);
  CHECK(gdakiCtrlEnvCheck(&e, 0x1234abcdull, 63) == GDAKI_CTRL_ENV_BAD_MAGIC);
  CHECK(gdakiCtrlEnvCheck(&e, 0x1234abcdull, 64 + 100) == GDAKI_CTRL_ENV_BAD_BYTES);
  CHECK(gdakiCtrlEnvCheck(&e, 0x99ull, 64 + GDAKI_CTRL_RECORD_BYTES) == GDAKI_CTRL_ENV_BAD_NONCE);
  struct gdakiCtrlEnv f = e;
  f.version = 2;
  CHECK(gdakiCtrlEnvCheck(&f, 0x1234abcdull, 2048) == GDAKI_CTRL_ENV_BAD_VERSION);
  f = e;
  f.kind = 9;
  CHECK(gdakiCtrlEnvCheck(&f, 0x1234abcdull, 2048) == GDAKI_CTRL_ENV_BAD_KIND);
  f = e;
  f.kind = GDAKI_CTRL_K_LAUNCHER;
  CHECK(gdakiCtrlEnvCheck(&f, 0x1234abcdull, 2048) == GDAKI_CTRL_ENV_BAD_BYTES);
  f.bodyBytes = 256;
  CHECK(gdakiCtrlEnvCheck(&f, 0x1234abcdull, 320) == GDAKI_CTRL_ENV_OK);
  f.kind = GDAKI_CTRL_K_PAIR;
  f.bodyBytes = (uint32_t)sizeof(struct gdakiCtrlPairBody);
  CHECK(gdakiCtrlEnvCheck(&f, 0x1234abcdull, 64 + sizeof(struct gdakiCtrlPairBody)) == GDAKI_CTRL_ENV_OK);
  f.bodyBytes = 0;
  CHECK(gdakiCtrlEnvCheck(&f, 0x1234abcdull, 2048) == GDAKI_CTRL_ENV_BAD_BYTES);
  // the order rule: take seq = last + 1 of gen; drop an older gen; anything else is a loss
  CHECK(gdakiCtrlOrder(7, 10, &e) == GDAKI_CTRL_ORDER_TAKE);
  CHECK(gdakiCtrlOrder(7, 11, &e) == GDAKI_CTRL_ORDER_LOST);
  CHECK(gdakiCtrlOrder(7, 9, &e) == GDAKI_CTRL_ORDER_LOST);
  CHECK(gdakiCtrlOrder(8, 10, &e) == GDAKI_CTRL_ORDER_DROP_OLD);
  CHECK(gdakiCtrlOrder(6, 10, &e) == GDAKI_CTRL_ORDER_LOST);
  // a random in-order stream with old-generation leftovers interleaved: every record of gen taken once, in order
  uint64_t last = 0, taken = 0;
  for (int i = 0; i < 10000; i++) {
    struct gdakiCtrlEnv x;
    const bool old = rng() % 4 == 0;
    gdakiCtrlEnvPack(&x, GDAKI_CTRL_K_RECORD, 1, old ? 6 : 7, old ? rng() % 100 : last + 1, 0, 1, 0, GDAKI_CTRL_RECORD_BYTES);
    const uint32_t v = gdakiCtrlOrder(7, last, &x);
    if (old) CHECK(v == GDAKI_CTRL_ORDER_DROP_OLD);
    else { CHECK(v == GDAKI_CTRL_ORDER_TAKE); last++; taken++; }
  }
  CHECK(taken == last);
}
static void testCredit(std::mt19937_64& rng) {
  // a ring model: the sender posts while gdakiCtrlCanSend says so; the receiver consumes in random batches and publishes
  // its consumed word now and then; never more than K SENDs ahead of the receiver's consumption (no RNR)
  for (int run = 0; run < 50; run++) {
    uint32_t gen = 1 + (uint32_t)run;
    uint64_t sent = 0, consumed = 0, word = gdakiCtrlGenCount(gen - 1, 12345);  // a stale word of the old gen
    for (int step = 0; step < 20000; step++) {
      if (rng() % 2 && gdakiCtrlCanSend(gen, sent, word)) sent++;
      CHECK(sent - consumed <= GDAKI_CTRL_RING_SLOTS);
      if (rng() % 3 == 0 && consumed < sent) consumed += 1 + rng() % (sent - consumed);
      if (rng() % 5 == 0) word = gdakiCtrlGenCount(gen, (uint32_t)consumed);
    }
  }
  CHECK(gdakiCtrlCanSend(3, 63, gdakiCtrlGenCount(2, 0)));
  CHECK(!gdakiCtrlCanSend(3, 64, gdakiCtrlGenCount(2, 0)));
  // the 32-bit count wraps: sent 2^32 + 62 against consumed 2^32 - 1 is 63 in flight (may send), + 63 is 64 (may not)
  CHECK(gdakiCtrlCanSend(3, 0xffffffffull + 63, gdakiCtrlGenCount(3, 0xffffffffu)));
  CHECK(!gdakiCtrlCanSend(3, 0xffffffffull + 64, gdakiCtrlGenCount(3, 0xffffffffu)));
}
static void testPage() {
  struct gdakiCtrlPageLayout l;
  CHECK(gdakiCtrlPageLayoutOf(4, 2, &l));
  CHECK(l.rxConsumedOff == 64 && l.rxConsumedLOff == 96 && l.staleMsOff == 112 && l.lineageOff == 192 && l.holdOff == 256);
  CHECK(l.bytes == 320 && l.nLineageLines == 1 && l.nHoldLines == 1);
  CHECK(gdakiCtrlPageLayoutOf(4, 0, &l) && l.bytes == 256);  // design v2 3.1's 256 B without the launchers' words
  CHECK(gdakiCtrlPageLayoutOf(GDAKI_CTRL_PAGE_MAX_RANKS, GDAKI_CTRL_PAGE_MAX_LAUNCHERS, &l) && l.bytes <= GDAKI_CTRL_PAGE_BYTES);
  CHECK(!gdakiCtrlPageLayoutOf(GDAKI_CTRL_PAGE_MAX_RANKS + 1, 0, &l));
  CHECK(!gdakiCtrlPageLayoutOf(0, 0, &l));
  for (uint32_t n = 1; n <= GDAKI_CTRL_PAGE_MAX_RANKS; n++)
    for (uint32_t nl = 0; nl <= GDAKI_CTRL_PAGE_MAX_LAUNCHERS; nl++) {
      CHECK(gdakiCtrlPageLayoutOf(n, nl, &l));
      CHECK(l.rxConsumedOff % 8 == 0 && l.rxConsumedLOff % 8 == 0 && l.staleMsOff % 8 == 0 && l.lineageOff % 64 == 0 &&
            l.holdOff % 64 == 0 && l.lineageOff >= l.staleMsOff + 8 * n && l.nLineageLines * 7 >= n);
    }
  CHECK(gdakiCtrlIncOf(gdakiCtrlIncNonce(5, 0xdeadbeefcafef00dull)) == 5 &&
        gdakiCtrlNonce32Of(gdakiCtrlIncNonce(5, 0xdeadbeefcafef00dull)) == 0xcafef00du);
  CHECK(gdakiCtrlBusyWord(0, 3000) == 0 && gdakiCtrlBusyNoOf(gdakiCtrlBusyWord(9, 3000)) == 9 &&
        gdakiCtrlBusyBoundOf(gdakiCtrlBusyWord(9, 3000)) == 3000);
  CHECK(gdakiCtrlBusyOf(0, 25000, 0, 3000) == 0);
  const uint64_t b1 = gdakiCtrlBusyOf(1000000, 25000, 0, 3000), b2 = gdakiCtrlBusyOf(0, 25000, 2000000, 3000);
  CHECK(b1 != 0 && gdakiCtrlBusyBoundOf(b1) == 25000 && b2 != 0 && gdakiCtrlBusyBoundOf(b2) == 3000);
  CHECK(gdakiCtrlBusyNoOf(b1) != gdakiCtrlBusyNoOf(b2) && (gdakiCtrlBusyNoOf(b1) & 1u));
  CHECK(gdakiCtrlBusyBoundOf(gdakiCtrlBusyOf(1000000, 25000, 2000000, 3000)) == 25000);
  CHECK((gdakiCtrlPageFlags(true, false, true) >> GDAKI_CTRL_PF_VERSION_SHIFT) == GDAKI_CTRL_PAGE_VERSION &&
        (gdakiCtrlPageFlags(true, false, true) & 7u) == (GDAKI_CTRL_PF_LEAVING | GDAKI_CTRL_PF_MIRROR));
  // this rank's consumed words for the launchers (glPairBody.creditOff): 8 B aligned, inside the launchers' run
  CHECK(gdakiCtrlPageLayoutOf(4, 2, &l));
  CHECK(gdakiCtrlPageCreditOffL(l, 0) == 96 && gdakiCtrlPageCreditOffL(l, 1) == 104 &&
        gdakiCtrlPageCreditOffL(l, 1) + 8 <= l.staleMsOff);
}
// The seqlock line: a writer that writes lines of one value (every word equal to the line's sequence) and readers that
// check every consistent copy is one moment's line (no torn even read).
static void testSeqlock() {
  struct gdakiCtrlReportLine line;
  memset(&line, 0, sizeof(line));
  std::atomic<bool> stop{false};
  std::atomic<uint64_t> good{0}, retry{0}, torn{0};
  std::thread wr([&] {
    uint64_t w7[7];
    for (uint64_t v = 1; !stop.load(std::memory_order_relaxed); v++) {
      for (int i = 0; i < 7; i++) w7[i] = v;
      gdakiCtrlLineWrite(&line, w7);
    }
  });
  std::vector<std::thread> rd;
  for (int t = 0; t < 2; t++)
    rd.emplace_back([&] {
      uint64_t w7[7];
      for (int i = 0; i < 300000; i++) {
        if (!gdakiCtrlLineRead(&line, w7)) { retry++; continue; }
        bool same = true;
        for (int k = 1; k < 7; k++) same = same && w7[k] == w7[0];
        if (same) good++;
        else torn++;
      }
    });
  for (auto& t : rd) t.join();
  stop.store(true);
  wr.join();
  CHECK(torn.load() == 0 && good.load() > 0);
  struct gdakiCtrlReportLine s;
  memset(&s, 0, sizeof(s));
  s.ver = 4;
  CHECK(gdakiCtrlLineSnapshotOk(&s) && !gdakiCtrlLineSnapshotOk2(&s));
  s.w[6] = 4;
  CHECK(gdakiCtrlLineSnapshotOk2(&s));
  s.ver = 5;
  CHECK(!gdakiCtrlLineSnapshotOk(&s));
  printf("seqlock: %llu consistent reads, %llu retries, %llu torn\n", (unsigned long long)good.load(),
         (unsigned long long)retry.load(), (unsigned long long)torn.load());
}
static void testFence() {
  // REVIEW2 막는 문제 1: right after the setup every word is 0 = no fence, so a hold of incarnation 0 is not fenced
  uint64_t word = 0;
  CHECK(!gdakiCtrlFencedIs(word, 0));
  CHECK(!gdakiCtrlFencedIs(word, 1));
  word = gdakiCtrlFenceWord(0);  // FENCED(p, 0)
  CHECK(gdakiCtrlFencedIs(word, 0) && !gdakiCtrlFencedIs(word, 1));
  word = gdakiCtrlFenceWord(1);
  CHECK(gdakiCtrlFencedIs(word, 1) && !gdakiCtrlFencedIs(word, 0) && !gdakiCtrlFencedIs(word, 2));
  CHECK(gdakiCtrlFenceWord(0xffffffffu) == 0x100000000ull && gdakiCtrlFencedIs(0x100000000ull, 0xffffffffu));
}
static void testEndpoint(std::mt19937_64& rng) {
  for (int i = 0; i < 1000; i++) {
    struct gdakiMiQpEndpoint v1;
    uint8_t* p = (uint8_t*)&v1;
    for (size_t k = 0; k < sizeof(v1); k++) p[k] = (uint8_t)rng();
    v1.pad = 0;
    v1.qpn = 1 + (uint32_t)(rng() % 0xfffffe);
    v1.psn = (uint32_t)(rng() & 0xffffff);
    v1.mtu = 1 + (int32_t)(rng() % 5);
    const struct gdakiCtrlEndpoint e = gdakiCtrlEndpointOf(v1, GDAKI_CTRL_QPT_RC);
    CHECK(memcmp(&e, &v1, offsetof(struct gdakiMiQpEndpoint, pad)) == 0 && e.version == GDAKI_CTRL_EP_VERSION);
    CHECK(gdakiCtrlEndpointOk(e));
    const struct gdakiMiQpEndpoint back = gdakiCtrlEndpointV1(e);
    CHECK(memcmp(&back, &v1, sizeof(v1)) == 0);
    struct gdakiCtrlEndpoint u = gdakiCtrlEndpointOf(v1, GDAKI_CTRL_QPT_UD);
    CHECK(gdakiCtrlEndpointOk(u) == (v1.mtu >= 4));
    u.version = 1;
    CHECK(!gdakiCtrlEndpointOk(u));
  }
  struct gdakiMiQpEndpoint z;
  memset(&z, 0, sizeof(z));
  z.mtu = 5;
  CHECK(!gdakiCtrlEndpointOk(gdakiCtrlEndpointOf(z, GDAKI_CTRL_QPT_RC)));  // QPN 0
}
static void testPair() {
  // either side starts; crossing PAIRs of one generation: the lower rank's wins
  CHECK(gdakiCtrlPairResolve(0, 1, 3, 4, 4, false) == GDAKI_CTRL_PAIR_KEEP_MINE);  // rank 0 keeps its PAIR(4)
  CHECK(gdakiCtrlPairResolve(1, 0, 3, 4, 4, false) == GDAKI_CTRL_PAIR_TAKE);       // rank 1 takes rank 0's
  CHECK(gdakiCtrlPairResolve(1, 0, 3, 0, 4, false) == GDAKI_CTRL_PAIR_TAKE);       // the higher rank alone saw ERR: taken
  CHECK(gdakiCtrlPairResolve(0, 1, 3, 0, 4, false) == GDAKI_CTRL_PAIR_TAKE);
  CHECK(gdakiCtrlPairResolve(0, 1, 4, 0, 3, false) == GDAKI_CTRL_PAIR_STALE);
  CHECK(gdakiCtrlPairResolve(0, 1, 4, 0, 4, true) == GDAKI_CTRL_PAIR_REPEAT);       // the same PAIR again: the same answer
  CHECK(gdakiCtrlPairResolve(0, 1, 4, 0, 4, false) == GDAKI_CTRL_PAIR_STALE);
  // a model: two sides, either one or both see ERR and start; in the end exactly one generation is taken by both
  for (int both = 0; both < 3; both++) {
    const uint32_t cur = 5;
    const uint32_t m0 = both != 1 ? cur + 1 : 0, m1 = both != 0 ? cur + 1 : 0;  // 0 starts, 1 starts, or both
    const uint32_t a0 = m1 ? gdakiCtrlPairResolve(0, 1, cur, m0, m1, false) : GDAKI_CTRL_PAIR_STALE;
    const uint32_t a1 = m0 ? gdakiCtrlPairResolve(1, 0, cur, m1, m0, false) : GDAKI_CTRL_PAIR_STALE;
    const int taken = (a0 == GDAKI_CTRL_PAIR_TAKE) + (a1 == GDAKI_CTRL_PAIR_TAKE);
    CHECK(taken == 1);
  }
  CHECK(sizeof(struct gdakiCtrlPairBody) == 144 && sizeof(struct gdakiCtrlRejoinNrp) == 160);
}
static void testConfirm() {
  CHECK(gdakiCtrlConfirmVerdict(false, false, true, true, 1, 2) == GDAKI_CTRL_CW_UNCONFIRMED);
  CHECK(gdakiCtrlConfirmVerdict(true, true, true, true, 1, 2) == GDAKI_CTRL_CW_REMACC);
  CHECK(gdakiCtrlConfirmVerdict(true, false, true, false, 1, 1) == GDAKI_CTRL_CW_NORESP);
  CHECK(gdakiCtrlConfirmVerdict(true, false, false, true, 1, 1) == GDAKI_CTRL_CW_NORESP);
  CHECK(gdakiCtrlConfirmVerdict(true, false, true, true, 7, 7) == GDAKI_CTRL_CW_STALE);
  CHECK(gdakiCtrlConfirmVerdict(true, false, true, true, 7, 9) == GDAKI_CTRL_CW_ALIVE);
}
static void testThresholds() {
  char why[96];
  CHECK(gdakiCtrlThresholdsOk(100, 500, 20, 2000, 10000, 20000, 5000, why, sizeof(why)));  // the defaults, RESTORE_MS 20 s
  CHECK(gdakiCtrlThresholdsOk(0, 500, 20, 2000, 10000, 20000, 5000, why, sizeof(why)));    // PROBE_MS 0: no READ
  CHECK(!gdakiCtrlThresholdsOk(100, 500, 19, 2000, 10000, 20000, 5000, why, sizeof(why)) && strstr(why, "CONFIRM"));
  CHECK(!gdakiCtrlThresholdsOk(100, 500, 500, 2000, 10000, 20000, 5000, why, sizeof(why)) && strstr(why, "CONFIRM"));
  CHECK(!gdakiCtrlThresholdsOk(300, 2000, 20, 2000, 10000, 20000, 5000, why, sizeof(why)) && strstr(why, "SUSPECT"));
  CHECK(!gdakiCtrlThresholdsOk(100, 500, 20, 10000, 10000, 20000, 5000, why, sizeof(why)) && strstr(why, "STALL"));
  CHECK(!gdakiCtrlThresholdsOk(100, 500, 20, 2000, 19500, 20000, 5000, why, sizeof(why)) && strstr(why, "RESTORE"));
  CHECK(!gdakiCtrlThresholdsOk(100, 499, 20, 2000, 10000, 20000, 5000, why, sizeof(why)) && strstr(why, "TIMEOUT"));
  CHECK(!gdakiCtrlThresholdsOk(100, 500, 20, 2000, 10000, 20000, 19500, why, sizeof(why)) && strstr(why, "SPARE"));
}
static void testQpAttr() {
  const struct gdakiCtrlQpAttr d;
  CHECK(gdakiCtrlQpAttrIsLn4(d) && d.sqDepth == 64 && d.rqDepth == 1 && d.cqDepth == 128 && d.timeout == 12 &&
        d.retryCnt == 7 && d.rnrRetry == 7 && d.minRnrTimer == 12 && d.access == 7 && d.qpType == GDAKI_CTRL_QPT_RC);
  int dummyCq = 0;
  const struct gdakiCtrlQpAttr rec = gdakiCtrlQpAttrRecord(14, &dummyCq), pr = gdakiCtrlQpAttrProbe(14, nullptr),
                               ud = gdakiCtrlQpAttrUd(gdakiCtrlQkeyOf(0xffffffffffffffffull), &dummyCq);
  CHECK(!gdakiCtrlQpAttrIsLn4(rec) && rec.sqDepth == 96 && rec.rqDepth == 64 && rec.access == GDAKI_CTRL_ACC_REMOTE_READ &&
        rec.timeout == 14 && rec.retryCnt == 7 && rec.rnrRetry == 3 && rec.cq == &dummyCq);
  CHECK(pr.sqDepth == 4 && pr.rqDepth == 0 && pr.access == GDAKI_CTRL_ACC_REMOTE_READ && pr.cq == nullptr &&
        pr.cqDepth >= pr.sqDepth);
  CHECK(ud.qpType == GDAKI_CTRL_QPT_UD && ud.qkey == 0x7fffffffu && ud.access == 0 && ud.sqDepth == 64 && ud.rqDepth == 64);
  CHECK(gdakiCtrlCqFits(3, 2));    // rank 4, two launchers: 5 x 160 + 128 = 928 <= 1024; 3 x 4 <= 64
  CHECK(!gdakiCtrlCqFits(6, 0));   // 6 x 160 + 128 = 1088 > 1024
  CHECK(!gdakiCtrlCqFits(17, 0));
  CHECK(sizeof(tree::gdakiTsMsg::nrp) == GDAKI_CTRL_NRP_BYTES);
}
static void testRecords() {
  for (uint32_t t = 52; t <= 55; t++) CHECK(gdakiCtrlIsRecord(t) && gdakiHoldIsRestoreRecord(t) && gdakiCtrlRecordName(t)[0] != '?');
  CHECK(!gdakiCtrlIsRecord(51) && !gdakiCtrlIsRecord(56));
  CHECK(strcmp(gdakiCtrlChName(GDAKI_CTRL_CH_RECORD), "record") == 0 && strcmp(gdakiCtrlChName(9), "?") == 0);
}
#if defined(GDAKI_CTRL_HAVE_LAUNCHER_MSG)
static void testLauncher() {
  struct glCtrlEnv g;
  struct gdakiCtrlEnv e;
  gl_env_pack(&g, GL_ENV_KIND_LAUNCHER, GL_FROM_LAUNCHER | 1, 3, 9, 4, 0x55aaull, 2);
  gdakiCtrlEnvPack(&e, GDAKI_CTRL_K_LAUNCHER, GDAKI_CTRL_FROM_LAUNCHER | 1, 3, 9, 4, 0x55aaull, 2, GDAKI_CTRL_LAUNCHER_BYTES);
  CHECK(memcmp(&g, &e, sizeof(e)) == 0);  // the same 64 bytes
  CHECK(gdakiCtrlEnvCheck((const struct gdakiCtrlEnv*)&g, 0x55aaull, 320) == GDAKI_CTRL_ENV_OK);
  // the relayed activation talk: launcher_msg.h's sizes are gin-mirror's structs'
  CHECK(GL_ACT_RECORD_BYTES == sizeof(struct gdakiRsActivate));
  CHECK(GL_FETCH_EP_BYTES == sizeof(struct gdakiMiActAnswer));
  CHECK(GL_FETCH_READY_BYTES == sizeof(struct gdakiMiActReady));
  CHECK(GL_FETCH_DONE_BYTES == sizeof(struct gdakiMiActDone));
  // the launcher's credit word for this rank is a gdakiCtrlGenCount word too (glPageCredit.consumed)
  struct glPageCredit c;
  memset(&c, 0, sizeof(c));
  c.consumed = gdakiCtrlGenCount(4, 17);
  CHECK(gdakiCtrlGenOf(c.consumed) == 4 && gdakiCtrlCountOf(c.consumed) == 17 && GL_PAGE_CREDIT_OFF(0) % 8 == 0);
  // the rank-launcher pairing: the rank's PAIR wins a crossing of one generation (the lower `from`), as rank-rank
  CHECK(gdakiCtrlPairResolve(2, GDAKI_CTRL_FROM_LAUNCHER | 1, 3, 4, 4, false) == GDAKI_CTRL_PAIR_KEEP_MINE);
  printf("launcher_msg.h: present; its envelope's bytes, endpoint, credit word and relayed sizes checked\n");
}
#endif
#endif  // !NCCL_GIN_CTRL_TCP

int main() {
  std::mt19937_64 rng(0x6763707265707031ull);  // "gcprepp1"
  testSend(rng);
  testPump(rng);
#if !NCCL_GIN_CTRL_TCP
  testEnvelope(rng);
  testCredit(rng);
  testPage();
  testSeqlock();
  testFence();
  testEndpoint(rng);
  testPair();
  testConfirm();
  testThresholds();
  testQpAttr();
  testRecords();
#if defined(GDAKI_CTRL_HAVE_LAUNCHER_MSG)
  testLauncher();
#else
  printf("launcher_msg.h: absent (its checks skipped)\n");
#endif
#endif
  printf("gc_unit_prep (%s): %d checks, %d failed\n", NCCL_GIN_CTRL_TCP ? "tcp" : "rdma", nChecks, nFail);
  return nFail == 0 ? 0 : 1;
}
