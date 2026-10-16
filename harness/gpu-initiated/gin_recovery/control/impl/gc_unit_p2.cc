// gc_unit_p2.cc - CPU unit test of gin-control's phase 2a-1 (EXPERIMENT.md 9.8 "CPU 단위 모형", 링): the record ring's
// model (credit, generations, the sender's queue, the inbox bound, the framing) and the UD pairing model, cut out of the
// working tree's host file (region "gin-control (ring): model", gc_ring_model.inc) by build_gc_p2.sh `unit`, with the
// tree's ctrl API block (gc_api.inc), ln4's TCP back end (gc_ln4_sock.inc: the TCP model the ring is compared with),
// gc_unit_prep.cc's record generator (gc_prep_gen.inc: kTypes and fillRandom, cut as they are) and the tree's hold region
// (rs_hold_pure.inc: the park). No NCCL, no CUDA, no verbs, no network: the NIC is a model in this file, the TCP model's
// sockets are AF_UNIX stream pairs. g++ with ASan and UBSan.
#include <atomic>
#include <cerrno>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
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

// What gin-mirror's headers and the cut text need from nccl.h and the host file (as gc_unit_prep.cc).
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

namespace ln4 {
#include "gc_ln4_sock.inc"
}
#include "gc_prep_gen.inc"  // gc_unit_prep.cc's kTypes and fillRandom
#include "gc_api.inc"
#include "gc_ring_model.inc"
#include "rs_hold_pure.inc"  // the tree's hold region (gdakiHoldPark)

static int nChecks = 0, nFail = 0;
#define CHECK(c) do { nChecks++; if (!(c)) { nFail++; fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)

#if !NCCL_GIN_CTRL_TCP
static void testWrId(std::mt19937_64& rng) {
  for (int i = 0; i < 10000; i++) {
    const uint32_t w = 1 + (uint32_t)(rng() % 6), p = (uint32_t)(rng() % GDAKI_CTRL_WR_MAX_PEERS), g = (uint32_t)rng(),
                   s = (uint32_t)(rng() % 65536);
    const uint64_t id = gdakiCtrlWrId(w, p, g, s);
    CHECK(gdakiCtrlWrWhat(id) == w && gdakiCtrlWrPeer(id) == p && gdakiCtrlWrGen(id) == g && gdakiCtrlWrSlot(id) == s);
  }
}

// ---- the NIC, modelled: one RC QP pair between side 0 and side 1 ----
// A posted SEND lands in the receiver's oldest posted RECV (RC order); none posted is an RNR (the credit's bug: counted
// and checked to stay 0). Completions wait in each side's CQ until the test collects them (random batches), so a
// generation change finds successful completions of the old generation still uncollected. A generation change moves the
// QP to ERR: every posted RECV and SEND and READ completes with a flush, then the ring starts the new generation.
struct NicSide {
  struct Rq { uint32_t gen, slot; };
  struct Sq { uint32_t gen, sslot; std::vector<uint8_t> frame; };
  struct Cqe { uint64_t wr; bool ok; uint32_t len; uint64_t word; };
  struct gdakiCtrlRingPair p;
  struct gdakiCtrlRingOps ops;
  std::deque<Rq> rq;
  std::deque<Sq> sq;
  std::deque<uint32_t> reads;  // the READs of the peer's consumed word in flight (their generation)
  std::deque<Cqe> cq;
  std::vector<std::vector<uint8_t>> slots;  // the ring slots' memory
  uint64_t rnr = 0, maxInbox = 0, maxDeferred = 0;
};
static int nicPostSend(void* ctx, int, uint32_t gen, uint32_t sslot, const uint8_t* frame, uint32_t bytes) {
  NicSide* s = (NicSide*)ctx;
  s->sq.push_back({gen, sslot, std::vector<uint8_t>(frame, frame + bytes)});
  return 0;
}
static int nicPostRecv(void* ctx, int, uint32_t gen, uint32_t slot) {
  NicSide* s = (NicSide*)ctx;
  s->rq.push_back({gen, slot});
  return 0;
}
static int nicReadCredit(void* ctx, int, uint32_t gen) {
  ((NicSide*)ctx)->reads.push_back(gen);
  return 0;
}
struct Nic {
  NicSide s[2];
  Nic(uint64_t nonce) {
    for (int i = 0; i < 2; i++) {
      gdakiCtrlRingInit(&s[i].p, 1 - i, i, nonce, 7, GDAKI_TS_MAGIC);
      s[i].ops.ctx = &s[i];
      s[i].ops.postSend = nicPostSend;
      s[i].ops.postRecv = nicPostRecv;
      s[i].ops.readCredit = nicReadCredit;
      s[i].slots.assign(GDAKI_CTRL_RING_SLOTS, std::vector<uint8_t>(GDAKI_CTRL_SLOT_BYTES));
    }
  }
  // the invariant of the credit: in the generation of the QP, the RECVs posted at the receiver cover every SEND in flight
  void checkCover(int from) {
    const NicSide& a = s[from];
    const NicSide& b = s[1 - from];
    uint64_t sends = 0, recvs = 0;
    for (const auto& x : a.sq) sends += x.gen == a.p.gen;
    for (const auto& x : b.rq) recvs += x.gen == b.p.gen;
    if (a.p.gen == b.p.gen) CHECK(recvs >= sends);
  }
  // one SEND of side `from` lands (false: nothing in flight)
  bool deliver(int from) {
    NicSide& a = s[from];
    NicSide& b = s[1 - from];
    if (a.sq.empty()) return false;
    checkCover(from);
    if (b.rq.empty()) {  // RNR: the sender would retry rnr_retry (3) times and go to ERR
      a.rnr++;
      return false;
    }
    NicSide::Sq x = a.sq.front();
    a.sq.pop_front();
    const NicSide::Rq y = b.rq.front();
    b.rq.pop_front();
    CHECK(x.gen == y.gen);  // one QP generation at both ends
    memcpy(b.slots[y.slot].data(), x.frame.data(), x.frame.size());
    b.cq.push_back({gdakiCtrlWrId(GDAKI_CTRL_WR_RECV, 0, y.gen, y.slot), true, (uint32_t)x.frame.size(), 0});
    a.cq.push_back({gdakiCtrlWrId(GDAKI_CTRL_WR_SEND, 0, x.gen, x.sslot), true, 0, 0});
    return true;
  }
  bool readDone(int at) {  // a READ of the peer's consumed word executes at the peer now
    NicSide& a = s[at];
    if (a.reads.empty()) return false;
    const uint32_t g = a.reads.front();
    a.reads.pop_front();
    a.cq.push_back({gdakiCtrlWrId(GDAKI_CTRL_WR_READ_CREDIT, 0, g, 0), true, 8, gdakiCtrlRingConsumedWord(&s[1 - at].p)});
    return true;
  }
  void collect(int at, int n) {  // the helper collects up to n completions
    NicSide& a = s[at];
    for (int k = 0; k < n && !a.cq.empty(); k++) {
      const NicSide::Cqe c = a.cq.front();
      a.cq.pop_front();
      switch (gdakiCtrlWrWhat(c.wr)) {
        case GDAKI_CTRL_WR_RECV:
          (void)gdakiCtrlRingOnRecvCqe(&a.p, a.ops, c.wr, c.ok, a.slots[gdakiCtrlWrSlot(c.wr)].data(), c.len);
          break;
        case GDAKI_CTRL_WR_SEND: gdakiCtrlRingOnSendCqe(&a.p, c.wr, c.ok, false); break;
        case GDAKI_CTRL_WR_READ_CREDIT: gdakiCtrlRingOnCreditWord(&a.p, gdakiCtrlWrGen(c.wr), c.ok, c.word); break;
        default: CHECK(false);
      }
      a.maxInbox = std::max<uint64_t>(a.maxInbox, a.p.inbox.size());
      a.maxDeferred = std::max<uint64_t>(a.maxDeferred, a.p.deferred.size());
    }
  }
  // ERR: everything posted completes with a flush (behind what is already in the CQ)
  void toErr() {
    for (int i = 0; i < 2; i++) {
      NicSide& a = s[i];
      for (const auto& y : a.rq) a.cq.push_back({gdakiCtrlWrId(GDAKI_CTRL_WR_RECV, 0, y.gen, y.slot), false, 0, 0});
      for (const auto& x : a.sq) a.cq.push_back({gdakiCtrlWrId(GDAKI_CTRL_WR_SEND, 0, x.gen, x.sslot), false, 0, 0});
      for (uint32_t g : a.reads) a.cq.push_back({gdakiCtrlWrId(GDAKI_CTRL_WR_READ_CREDIT, 0, g, 0), false, 0, 0});
      a.rq.clear();
      a.sq.clear();
      a.reads.clear();
    }
  }
  // the pairing of generation g (initiator `ini`): each side starts g, collects its old completions until its K RECVs can
  // go (the ring refuses before), posts them, goes RTS; the initiator's CONNECTED goes first
  void pairing(uint32_t g, int ini, std::mt19937_64& rng) {
    for (int i = 0; i < 2; i++) {
      gdakiCtrlRingNewGen(&s[i].p, g, i == ini);
      int guard = 0;
      while (gdakiCtrlRingPostInitial(&s[i].p, s[i].ops) < 0 && guard++ < 100000) collect(i, 1 + (int)(rng() % 4));
      CHECK(gdakiCtrlRingOldRecvs(&s[i].p) == 0 && s[i].rq.size() == GDAKI_CTRL_RING_SLOTS);
    }
    for (int i = 0; i < 2; i++) s[i].p.rts = true;
  }
};

// ---- the credit model: random batches, re-posting, generation changes ----
// Both directions carry numbered records (the number in `round`); per generation each side's taken records are a prefix
// of what the other side posted in it, in order, each once, with its bytes; at the end of a run (no change) everything
// enqueued in the last generation arrived. Older generations' completions are dropped, never taken.
static void testCredit(std::mt19937_64& rng) {
  uint64_t taken = 0, oldCqes = 0, oldTaken = 0, reads = 0, genChanges = 0, dropped = 0;
  for (int run = 0; run < 60; run++) {
    Nic nic(0x1234567800000000ull + (uint64_t)run);
    uint32_t g = 1;
    nic.pairing(g, (int)(rng() % 2), rng);
    // per side: what it enqueued in the current generation (bytes as they must arrive) and what it took
    std::vector<std::vector<uint8_t>> sentG[2];
    size_t gotG[2] = {0, 0};
    uint64_t nextId = 1;
    const int steps = 4000 + (int)(rng() % 4000);
    for (int step = 0; step < steps; step++) {
      const int i = (int)(rng() % 2);
      NicSide& a = nic.s[i];
      switch (rng() % 8) {
        case 0:
        case 1: {  // a batch of records into the queue
          const int n = 1 + (int)(rng() % 40);
          for (int k = 0; k < n; k++) {
            ln4::gdakiTsMsg m;
            fillRandom(&m, rng, kTypes[rng() % (sizeof(kTypes) / sizeof(kTypes[0]))]);
            m.round = nextId++;
            if (gdakiCtrlRingEnqueue(&a.p, GDAKI_CTRL_K_RECORD, &m, sizeof(m)) != 0) break;
            m.magic = GDAKI_TS_MAGIC;
            const uint8_t* b = (const uint8_t*)&m;
            sentG[i].emplace_back(b, b + sizeof(m));
          }
          break;
        }
        case 2: gdakiCtrlRingKick(&a.p, a.ops, (double)step); break;
        case 3: for (int k = (int)(rng() % 30); k > 0 && nic.deliver(i); k--) {} break;
        case 4: nic.collect(i, 1 + (int)(rng() % 50)); break;
        case 5: {  // the application reads a batch of the inbox
          struct gdakiCtrlInEnt e;
          for (int k = (int)(rng() % 50); k > 0 && gdakiCtrlRingPop(&a.p, a.ops, &e) == 1; k--) {
            CHECK(e.env.gen == a.p.gen && e.env.kind == GDAKI_CTRL_K_RECORD);
            if (e.env.gen != a.p.gen) oldTaken++;
            const std::vector<std::vector<uint8_t>>& want = sentG[1 - i];
            CHECK(gotG[i] < want.size() && memcmp(e.body, want[gotG[i]].data(), sizeof(ln4::gdakiTsMsg)) == 0);
            gotG[i]++;
            taken++;
          }
          break;
        }
        case 6: nic.readDone(i); break;
        default:
          if (rng() % 400 == 0) {  // ERR and a new pairing (either side starts)
            nic.toErr();
            dropped += nic.s[0].p.q.size() + nic.s[1].p.q.size();
            nic.pairing(++g, (int)(rng() % 2), rng);
            for (int k = 0; k < 2; k++) {
              sentG[k].clear();
              gotG[k] = 0;
            }
            genChanges++;
          }
          break;
      }
    }
    // the end: drive everything until both queues and inboxes are empty
    for (int round = 0; round < 100000; round++) {
      bool any = false;
      for (int i = 0; i < 2; i++) {
        NicSide& a = nic.s[i];
        any |= gdakiCtrlRingKick(&a.p, a.ops, 1e9 + round) > 0;
        while (nic.deliver(i)) any = true;
        while (nic.readDone(i)) any = true;
        if (!a.cq.empty()) any = true;
        nic.collect(i, 1 << 20);
        struct gdakiCtrlInEnt e;
        while (gdakiCtrlRingPop(&a.p, a.ops, &e) == 1) {
          const std::vector<std::vector<uint8_t>>& want = sentG[1 - i];
          CHECK(gotG[i] < want.size() && memcmp(e.body, want[gotG[i]].data(), sizeof(ln4::gdakiTsMsg)) == 0);
          gotG[i]++;
          taken++;
          any = true;
        }
      }
      if (!any && nic.s[0].p.q.empty() && nic.s[1].p.q.empty()) break;
    }
    for (int i = 0; i < 2; i++) {
      CHECK(gotG[i] == sentG[1 - i].size());  // nothing lost, nothing twice in the last generation
      CHECK(nic.s[i].rnr == 0 && !nic.s[i].p.lost);
      CHECK(nic.s[i].p.sent - nic.s[i].p.peerConsumed <= GDAKI_CTRL_RING_SLOTS);
      oldCqes += nic.s[i].p.oldRecvCqes + nic.s[i].p.oldSendCqes;
      reads += nic.s[i].p.creditReads;
    }
  }
  CHECK(oldTaken == 0 && genChanges > 0 && oldCqes > 0 && reads > 0);
  printf("credit: %llu records taken, %llu generation changes, %llu old-generation completions dropped, %llu queued "
         "dropped at a change, %llu consumed-word READs (window shut); RNR 0\n",
         (unsigned long long)taken, (unsigned long long)genChanges, (unsigned long long)oldCqes,
         (unsigned long long)dropped, (unsigned long long)reads);
}

// ---- the inbox bound: a reader that stops; the sender stops behind it, nothing is lost ----
static void testInbox(std::mt19937_64& rng) {
  Nic nic(0x77ull);
  nic.pairing(3, 0, rng);
  NicSide& a = nic.s[0];
  NicSide& b = nic.s[1];
  const uint64_t total = GDAKI_CTRL_INBOX_MAX + 3000;
  uint64_t queued = 0;
  for (int round = 0; round < 200000 && (queued < total || !a.p.q.empty()); round++) {
    for (int k = 0; k < 64 && queued < total; k++) {
      ln4::gdakiTsMsg m;
      fillRandom(&m, rng, 2);
      m.round = queued;
      const int r = gdakiCtrlRingEnqueue(&a.p, GDAKI_CTRL_K_RECORD, &m, sizeof(m));
      if (r != 0) break;
      queued++;
    }
    gdakiCtrlRingKick(&a.p, a.ops, round * 2.0);
    while (nic.deliver(0)) {}
    nic.readDone(0);
    nic.collect(0, 1 << 20);
    nic.collect(1, 1 << 20);
    CHECK(b.p.inbox.size() <= GDAKI_CTRL_INBOX_MAX + GDAKI_CTRL_RING_SLOTS);
    if (b.p.inbox.size() >= GDAKI_CTRL_INBOX_MAX + GDAKI_CTRL_RING_SLOTS) break;  // the reader is stopped: so is the sender
  }
  // the sender stopped: all of the receiver's slots wait for the inbox, the window is shut, the queue holds the rest
  CHECK(b.p.deferred.size() == GDAKI_CTRL_RING_SLOTS && b.rq.empty() && a.sq.empty());
  CHECK(!gdakiCtrlCanSend(a.p.gen, a.p.sent, gdakiCtrlGenCount(a.p.gen, (uint32_t)a.p.peerConsumed)));
  CHECK(b.p.consumed == GDAKI_CTRL_INBOX_MAX + 1 && a.p.creditReads > 0);  // CONNECTED + 4096 records given back
  CHECK(a.rnr == 0 && !a.p.lost && !b.p.lost && queued == total);
  const uint64_t heldAtStop = b.p.inbox.size();
  // the reader comes back: everything arrives in order
  uint64_t next = 0;
  for (int round = 0; round < 200000 && next < total; round++) {
    struct gdakiCtrlInEnt e;
    for (int k = (int)(rng() % 200); k > 0 && gdakiCtrlRingPop(&b.p, b.ops, &e) == 1; k--) {
      ln4::gdakiTsMsg m;
      memcpy(&m, e.body, sizeof(m));
      CHECK(m.round == next);
      next++;
    }
    gdakiCtrlRingKick(&a.p, a.ops, 1e6 + round * 2.0);
    while (nic.deliver(0)) {}
    nic.readDone(0);
    nic.collect(0, 1 << 20);
    nic.collect(1, 1 << 20);
  }
  CHECK(next == total && a.rnr == 0);
  printf("inbox: the reader stopped at %llu messages in the inbox (bound %u + %u landed slots), the sender stopped with "
         "%llu queued; %llu arrived in order after it came back\n",
         (unsigned long long)heldAtStop, GDAKI_CTRL_INBOX_MAX, GDAKI_CTRL_RING_SLOTS,
         (unsigned long long)(total - heldAtStop), (unsigned long long)next);
}

// ---- an older generation's envelope in a RECV of the current one (overlapping PSN windows): dropped, not consumed ----
static void testOldEnvelope(std::mt19937_64& rng) {
  Nic nic(0x99ull);
  nic.pairing(5, 0, rng);
  NicSide& b = nic.s[1];
  const NicSide::Rq y = b.rq.front();
  b.rq.pop_front();
  ln4::gdakiTsMsg m;
  fillRandom(&m, rng, 3);
  uint8_t frame[GDAKI_CTRL_FRAME_MAX];
  const uint32_t n = gdakiCtrlFrame(frame, GDAKI_CTRL_K_RECORD, 0, 4, 9, 0, 0x99ull, 7, &m, sizeof(m), GDAKI_TS_MAGIC);
  memcpy(b.slots[y.slot].data(), frame, n);
  const uint64_t c0 = b.p.consumed;
  CHECK(gdakiCtrlRingOnRecvCqe(&b.p, b.ops, gdakiCtrlWrId(GDAKI_CTRL_WR_RECV, 0, 5, y.slot), true, b.slots[y.slot].data(),
                               n) == GDAKI_CTRL_RX_OLD);
  CHECK(b.p.consumed == c0 && b.p.oldEnvelopes == 1 && !b.p.lost && b.p.inbox.empty() && b.rq.size() == 64);
  // a gap in gen is a lost connection; so is a message before CONNECTED, a bad magic, another sender
  struct Case { uint64_t seq; int32_t from; uint32_t magic; const char* cause; };
  const Case cs[] = {{2, 0, GDAKI_TS_MAGIC, "SEQ"}, {1, 0, GDAKI_TS_MAGIC, "EARLY"}, {1, 0, GDAKI_TS_MAGIC ^ 1u, "BADMAGIC"},
                     {1, 3, GDAKI_TS_MAGIC, "BADENV"}};
  for (const Case& c : cs) {
    Nic x(0x99ull);
    x.pairing(5, 0, rng);
    NicSide& r = x.s[1];
    const NicSide::Rq z = r.rq.front();
    r.rq.pop_front();
    const uint32_t k = gdakiCtrlFrame(frame, GDAKI_CTRL_K_RECORD, c.from, 5, c.seq, 0, 0x99ull, 7, &m, sizeof(m), c.magic);
    memcpy(r.slots[z.slot].data(), frame, k);
    CHECK(gdakiCtrlRingOnRecvCqe(&r.p, r.ops, gdakiCtrlWrId(GDAKI_CTRL_WR_RECV, 0, 5, z.slot), true, r.slots[z.slot].data(),
                                 k) == GDAKI_CTRL_RX_LOST);
    CHECK(r.p.lost && strcmp(r.p.lostCause, c.cause) == 0);
    struct gdakiCtrlInEnt e;
    CHECK(gdakiCtrlRingPop(&r.p, r.ops, &e) == -1);
  }
}

// ---- the framing against the TCP model, and the park ----
// gc_unit_prep.cc's generator makes the record sequence; the TCP model is ln4's gdakiTsSend on a stream socket, read
// once as raw bytes and once through ln4's gdakiTsPump; the ring carries the same records (random batches, the window
// shut now and then). The ring's records, laid end to end, are the TCP model's byte stream; each record then goes where
// the helper puts it (a restore record into the peer's park, gdakiHoldPark of the hold region; the rest to its reader),
// and both paths leave the same park and the same reader's list, byte for byte.
static void readAll(int fd, std::vector<uint8_t>& out, size_t n) {
  size_t off = out.size();
  out.resize(off + n);
  const size_t end = off + n;
  while (off < end) {
    struct pollfd pf = {fd, POLLIN, 0};
    (void)poll(&pf, 1, 1000);
    const ssize_t k = recv(fd, out.data() + off, end - off, MSG_DONTWAIT);
    if (k > 0) off += (size_t)k;
    else if (k == 0 || (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)) { out.resize(off); return; }
  }
}
static void testFraming(std::mt19937_64& rng) {
  uint64_t nRec = 0, nParked = 0, nRead = 0;
  for (int run = 0; run < 20; run++) {
    int a[2], b[2];
    if (socketpair(AF_UNIX, SOCK_STREAM, 0, a) != 0 || socketpair(AF_UNIX, SOCK_STREAM, 0, b) != 0) { perror("socketpair"); exit(2); }
    for (int i = 0; i < 2; i++) {
      fcntl(a[i], F_SETFL, fcntl(a[i], F_GETFL, 0) | O_NONBLOCK);
      fcntl(b[i], F_SETFL, fcntl(b[i], F_GETFL, 0) | O_NONBLOCK);
    }
    Nic nic(0xabcdef01ull + (uint64_t)run);
    nic.pairing(1 + (uint32_t)run, (int)(rng() % 2), rng);
    NicSide& s = nic.s[0];
    NicSide& r = nic.s[1];
    std::vector<uint8_t> tcpStream, ringStream;
    gdakiHoldPark<ln4::gdakiTsMsg> parkTcp, parkRing;
    std::vector<std::vector<uint8_t>> readTcp, readRing;
    ln4::gdakiTsPeer pe;
    pe.fd = b[1];
    auto route = [&](const ln4::gdakiTsMsg& m, gdakiHoldPark<ln4::gdakiTsMsg>& park,
                     std::vector<std::vector<uint8_t>>& reader, double t) {
      uint32_t droppedType = 0;
      if (gdakiHoldIsRestoreRecord(m.type)) {
        (void)park.push(m, t, &droppedType);
      } else {
        const uint8_t* p = (const uint8_t*)&m;
        reader.emplace_back(p, p + sizeof(m));
      }
    };
    const int n = 200 + (int)(rng() % 600);
    int ringGot = 0;
    for (int i = 0; i < n || ringGot < n; i++) {
      if (i < n) {
        ln4::gdakiTsMsg m;
        fillRandom(&m, rng, kTypes[rng() % (sizeof(kTypes) / sizeof(kTypes[0]))]);
        ln4::gdakiTsMsg m1 = m, m2 = m;
        CHECK(ln4::gdakiTsSend(a[0], &m1, 1000) == 0 && ln4::gdakiTsSend(b[0], &m2, 1000) == 0);
        readAll(a[1], tcpStream, sizeof(m1));
        ln4::gdakiTsMsg got;
        int k = 0;
        for (int tries = 0; tries < 1000 && (k = ln4::gdakiTsPump(pe, &got)) == 0; tries++) {}
        CHECK(k == 1);
        if (k == 1) {
          route(got, parkTcp, readTcp, (double)i);
          nRec++;
        }
        CHECK(gdakiCtrlRingEnqueue(&s.p, GDAKI_CTRL_K_RECORD, &m, sizeof(m)) == 0);  // the record before its magic
      }
      // the ring: random batches of posts, landings, completions and reads (the window shut at times)
      gdakiCtrlRingKick(&s.p, s.ops, (double)i);
      gdakiCtrlRingKick(&r.p, r.ops, (double)i);  // the receiver's CONNECTED when it started the pairing
      while (nic.deliver(1)) {}
      for (int k = (int)(rng() % 70); k > 0 && nic.deliver(0); k--) {}
      if (rng() % 3 == 0) nic.readDone(0);
      nic.collect(0, (int)(rng() % 80));
      nic.collect(1, (int)(rng() % 80));
      struct gdakiCtrlInEnt e;
      for (int k = (int)(rng() % 90); k > 0 && gdakiCtrlRingPop(&r.p, r.ops, &e) == 1; k--) {
        CHECK(e.env.kind == GDAKI_CTRL_K_RECORD && e.env.bodyBytes == sizeof(ln4::gdakiTsMsg) && e.env.seq == ringGot + 1u + (s.p.initiator ? 1u : 0u));
        ringStream.insert(ringStream.end(), e.body, e.body + e.env.bodyBytes);
        ln4::gdakiTsMsg m;
        memcpy(&m, e.body, sizeof(m));
        route(m, parkRing, readRing, (double)ringGot);
        ringGot++;
      }
      if (i > 100000) break;
    }
    CHECK(ringGot == n && tcpStream.size() == (size_t)n * sizeof(ln4::gdakiTsMsg));
    CHECK(ringStream == tcpStream);  // the ring's records end to end are the TCP model's bytes
    CHECK(readTcp == readRing);
    CHECK(parkTcp.q.size() == parkRing.q.size());
    nParked += parkRing.q.size();
    nRead += readRing.size();
    for (size_t k = 0; k < parkTcp.q.size() && k < parkRing.q.size(); k++)
      CHECK(memcmp(&parkTcp.q[k].m, &parkRing.q[k].m, sizeof(ln4::gdakiTsMsg)) == 0 && parkTcp.q[k].atMs == parkRing.q[k].atMs);
    // the owners take their records out of both parks alike
    for (uint32_t t : kTypes) {
      ln4::gdakiTsMsg x, y;
      bool gx, gy;
      do {
        gx = parkTcp.take(t, &x);
        gy = parkRing.take(t, &y);
        CHECK(gx == gy && (!gx || memcmp(&x, &y, sizeof(x)) == 0));
      } while (gx && gy);
    }
    CHECK(parkTcp.q.empty() && parkRing.q.empty() && parkTcp.dropped == parkRing.dropped);
    for (int i = 0; i < 2; i++) {
      close(a[i]);
      close(b[i]);
    }
  }
  printf("framing: %llu records of gc_unit_prep.cc's generator through ln4's gdakiTsSend and through the ring: the same "
         "bytes, the same records to their readers (%llu) and the same parks (%llu parked)\n",
         (unsigned long long)nRec, (unsigned long long)nRead, (unsigned long long)nParked);
}

// ---- the UD pairing: two sides, one QP kind each run (the record QP or the liveness READ QP) ----
// The network loses, repeats and reorders datagrams; the record QP's CONNECTED is an RC SEND (it arrives, once). Each
// side does what the model's actions ask: a fresh PSN for each prepared QP (the model checks it differs), the PAIR,
// PAIR_ACK and PAIR_DONE bodies. In the end both sides are UP in one generation, each connected to the other's endpoint
// (QPN, PSN) of that generation.
struct PairSide {
  struct gdakiCtrlPairSt st;
  int32_t id = 0;
  uint32_t inc = 0;
  uint32_t qpn = 0, psn = 0, qpGen = 0;  // this side's QP of the kind as last prepared
  uint32_t remoteQpn = 0, remotePsn = 0, remoteGen = 0;
  uint64_t freshPsns = 0, reuses = 0;
};
struct Dgram {
  int to;
  double at;
  struct gdakiCtrlPairBody b;
};
struct PairNet {
  PairSide side[2];
  std::vector<Dgram> net;
  std::mt19937_64* rng = nullptr;
  uint32_t qk = GDAKI_CTRL_PAIR_QP_RECORD;
  double loss = 0, dup = 0;
  uint32_t nextQpn = 0x100;
  std::mt19937 psnRng{12345};
  std::vector<Dgram> captured;  // every datagram, for replays of old ones
  uint64_t sent = 0, lost = 0;
  void prepare(PairSide& s, uint32_t gen) {  // a fresh PSN (drawn again while equal to the last one), a QPN
    uint32_t p;
    do p = psnRng() & 0xffffffu; while (!gdakiCtrlPairPsnFresh(&s.st, p));
    s.psn = p;
    s.qpn = nextQpn++;
    s.qpGen = gen;
    s.freshPsns++;
  }
  struct gdakiCtrlPairBody body(PairSide& s, uint32_t step, uint32_t gen) {
    struct gdakiCtrlEndpoint qp, ud;
    memset(&qp, 0, sizeof(qp));
    qp.qpn = s.qpn;
    qp.psn = s.psn;
    qp.mtu = 5;
    qp.version = GDAKI_CTRL_EP_VERSION;
    qp.qpType = GDAKI_CTRL_QPT_RC;
    ud = qp;
    ud.qpn = 0x9000 + (uint32_t)(s.id & 0xfff);
    ud.psn = 0x1234;
    ud.qpType = GDAKI_CTRL_QPT_UD;
    struct gdakiCtrlRegion z;
    memset(&z, 0, sizeof(z));
    return gdakiCtrlPairBodyOf(&s.st, step, gen, s.inc, 0x5eedull, qp, ud, z, z);
  }
  void send(int from, const struct gdakiCtrlPairBody& b, double now, bool reliable) {
    Dgram d{1 - from, now + (double)((*rng)() % 300), b};
    captured.push_back(d);
    sent++;
    if (!reliable && (double)((*rng)() % 1000) < loss * 1000) {
      lost++;
      return;
    }
    net.push_back(d);
    if (!reliable && (double)((*rng)() % 1000) < dup * 1000) {
      d.at += (double)((*rng)() % 700);
      net.push_back(d);
    }
  }
  void act(int i, uint32_t a, double now) {
    PairSide& s = side[i];
    switch (a) {
      case GDAKI_CTRL_PA_SEND_PAIR:
        prepare(s, s.st.mine);
        send(i, body(s, GDAKI_CTRL_PAIR_STEP_PAIR, s.st.mine), now, false);
        break;
      case GDAKI_CTRL_PA_RESEND_PAIR: send(i, body(s, GDAKI_CTRL_PAIR_STEP_PAIR, s.st.mine), now, false); break;
      case GDAKI_CTRL_PA_RESEND_ACK: send(i, s.st.ack, now, false); break;
      case GDAKI_CTRL_PA_RESEND_DONE: send(i, body(s, GDAKI_CTRL_PAIR_STEP_DONE, s.st.cur), now, false); break;
      default: break;
    }
  }
  void deliver(const Dgram& d, double now) {
    PairSide& s = side[d.to];
    const int i = d.to;
    CHECK(gdakiCtrlPairBodyOk(d.b, s.id, 0x5eedull));
    if (d.b.step == GDAKI_CTRL_PAIR_STEP_PAIR) {
      const bool prepared = s.st.state == GDAKI_CTRL_PS_STARTED && s.st.mine == d.b.gen;
      const uint32_t a = gdakiCtrlPairOnPair(&s.st, d.b.gen, d.b.incarnation, now);
      if (a == GDAKI_CTRL_PA_TAKE) {
        CHECK(s.st.reusedMine == prepared);
        if (s.st.reusedMine) s.reuses++;
        else prepare(s, s.st.cur);
        s.remoteQpn = d.b.qp.qpn;
        s.remotePsn = d.b.qp.psn;
        s.remoteGen = d.b.gen;
        gdakiCtrlPairStoreAck(&s.st, body(s, GDAKI_CTRL_PAIR_STEP_ACK, s.st.cur));
        send(i, s.st.ack, now, false);
      } else {
        act(i, a, now);
      }
    } else if (d.b.step == GDAKI_CTRL_PAIR_STEP_ACK) {
      const uint32_t a = gdakiCtrlPairOnAck(&s.st, d.b.gen, d.b.incarnation);
      if (a == GDAKI_CTRL_PA_CONNECT) {
        CHECK(s.qpGen == s.st.cur);
        s.remoteQpn = d.b.qp.qpn;
        s.remotePsn = d.b.qp.psn;
        s.remoteGen = d.b.gen;
        // record: CONNECTED on the RC QP (reliable); probe: PAIR_DONE over UD
        send(i, body(s, GDAKI_CTRL_PAIR_STEP_DONE, s.st.cur), now, qk == GDAKI_CTRL_PAIR_QP_RECORD);
      } else {
        act(i, a, now);
      }
    } else {
      (void)gdakiCtrlPairOnDone(&s.st, d.b.gen);
    }
  }
  // run until both are UP and the network is quiet (or the bound)
  void run(double& now, double until) {
    for (; now < until; now += 1.0) {
      std::shuffle(net.begin(), net.end(), *rng);  // reordering
      for (size_t k = 0; k < net.size();) {
        if (net[k].at <= now) {
          const Dgram d = net[k];
          net.erase(net.begin() + (long)k);
          deliver(d, now);
        } else {
          k++;
        }
      }
      for (int i = 0; i < 2; i++) act(i, gdakiCtrlPairTick(&side[i].st, now), now);
      if (net.empty() && side[0].st.state == GDAKI_CTRL_PS_UP && side[1].st.state == GDAKI_CTRL_PS_UP) return;
    }
  }
  bool agreed() const {
    const PairSide &a = side[0], &b = side[1];
    return a.st.state == GDAKI_CTRL_PS_UP && b.st.state == GDAKI_CTRL_PS_UP && a.st.cur == b.st.cur &&
           a.qpGen == a.st.cur && b.qpGen == b.st.cur && a.remoteQpn == b.qpn && a.remotePsn == b.psn &&
           b.remoteQpn == a.qpn && b.remotePsn == a.psn && a.remoteGen == a.st.cur && b.remoteGen == b.st.cur;
  }
};
static void testPairing(std::mt19937_64& rng) {
  uint64_t runs = 0, ok = 0, crossings = 0, reuses = 0, fresh = 0, lostN = 0, sentN = 0, gaveUp = 0, launcherRuns = 0;
  for (int run = 0; run < 2000; run++) {
    PairNet pn;
    pn.rng = &rng;
    pn.qk = run % 2 ? GDAKI_CTRL_PAIR_QP_PROBE : GDAKI_CTRL_PAIR_QP_RECORD;
    pn.loss = (double)(rng() % 40) / 100.0;
    pn.dup = (double)(rng() % 30) / 100.0;
    const bool launcher = run % 7 == 3;  // side 1 a launcher (from 0x40000000 | node): the rank's PAIR wins
    launcherRuns += launcher;
    pn.side[0].id = (int32_t)(rng() % 4);
    pn.side[1].id = launcher ? (int32_t)(GDAKI_CTRL_FROM_LAUNCHER | 1) : pn.side[0].id + 1 + (int32_t)(rng() % 3);
    if (rng() % 2 && !launcher) std::swap(pn.side[0].id, pn.side[1].id);
    for (int i = 0; i < 2; i++) {
      gdakiCtrlPairInit(&pn.side[i].st, pn.qk, pn.side[i].id, pn.side[1 - i].id);
      pn.side[i].inc = 3 + (uint32_t)i;
    }
    for (int i = 0; i < 2; i++) gdakiCtrlPairSetPeerInc(&pn.side[i].st, pn.side[1 - i].inc);
    double now = 0;
    const int lo = pn.side[0].id < pn.side[1].id ? 0 : 1;  // the setup: the lower id starts
    pn.act(lo, gdakiCtrlPairStart(&pn.side[lo].st, now, 15000), now);
    pn.run(now, 15000);
    if (!pn.agreed()) {
      CHECK(pn.loss >= 0.3);  // only a lossy network may exhaust the bound
      gaveUp++;
      continue;
    }
    // re-pairings after ERR: side 0 alone, side 1 alone, or both (crossing PAIRs of one generation)
    for (int k = 0; k < 6; k++) {
      const uint32_t g = pn.side[0].st.cur;
      const int who = (int)(rng() % 3);
      const double t0 = now;
      if (who != 1) pn.act(0, gdakiCtrlPairOnQpErr(&pn.side[0].st, g, now, 10000), now);
      if (who != 0) pn.act(1, gdakiCtrlPairOnQpErr(&pn.side[1].st, g, now, 10000), now);
      crossings += who == 2;
      // an older generation's flush after the re-pairing started: no second re-pairing
      CHECK(gdakiCtrlPairOnQpErr(&pn.side[0].st, g - 1, now, 10000) == GDAKI_CTRL_PA_NONE);
      pn.run(now, t0 + 10000);
      runs++;
      if (!pn.agreed()) {
        CHECK(pn.loss >= 0.3);
        gaveUp++;
        break;
      }
      ok++;
      CHECK(pn.side[0].st.cur == g + 1);
      // every old datagram again (repeats from the past, any order): nothing changes
      const uint32_t cur = pn.side[0].st.cur;
      std::vector<Dgram> old = pn.captured;
      std::shuffle(old.begin(), old.end(), rng);
      for (const Dgram& d : old)
        if (d.b.gen < cur || (d.b.gen == cur && d.b.step != GDAKI_CTRL_PAIR_STEP_PAIR)) pn.deliver(d, now);
      pn.net.clear();
      CHECK(pn.agreed() && pn.side[0].st.cur == cur && pn.side[1].st.cur == cur);
      // another incarnation's PAIR(cur + 1): dropped
      CHECK(gdakiCtrlPairOnPair(&pn.side[0].st, cur + 1, pn.side[1].inc - 1, now) == GDAKI_CTRL_PA_DROP);
      CHECK(pn.side[0].st.cur == cur && pn.side[0].st.droppedInc > 0 && pn.agreed());
    }
    for (int i = 0; i < 2; i++) {
      reuses += pn.side[i].reuses;
      fresh += pn.side[i].freshPsns;
    }
    lostN += pn.lost;
    sentN += pn.sent;
  }
  CHECK(crossings > 0 && reuses > 0 && ok * 10 > runs * 9);
  // the rules one by one: the crossing, the rank against a launcher, the resend and the bound
  struct gdakiCtrlPairSt lo, hi, ln;
  gdakiCtrlPairInit(&lo, GDAKI_CTRL_PAIR_QP_RECORD, 1, 2);
  gdakiCtrlPairInit(&hi, GDAKI_CTRL_PAIR_QP_RECORD, 2, 1);
  gdakiCtrlPairInit(&ln, GDAKI_CTRL_PAIR_QP_RECORD, 2, (int32_t)(GDAKI_CTRL_FROM_LAUNCHER | 0));
  CHECK(gdakiCtrlPairStart(&lo, 0, 1000) == GDAKI_CTRL_PA_SEND_PAIR && gdakiCtrlPairStart(&hi, 0, 1000) == GDAKI_CTRL_PA_SEND_PAIR);
  CHECK(gdakiCtrlPairStart(&lo, 1, 1000) == GDAKI_CTRL_PA_NONE);  // started already: the same attempt
  CHECK(gdakiCtrlPairOnPair(&lo, 1, 0, 1) == GDAKI_CTRL_PA_DROP);  // the lower keeps its own
  CHECK(gdakiCtrlPairOnPair(&hi, 1, 0, 1) == GDAKI_CTRL_PA_TAKE && hi.reusedMine);
  CHECK(gdakiCtrlPairStart(&ln, 0, 1000) == GDAKI_CTRL_PA_SEND_PAIR);
  CHECK(gdakiCtrlPairOnPair(&ln, 1, 0, 1) == GDAKI_CTRL_PA_DROP);  // the rank's PAIR wins against the launcher's
  CHECK(gdakiCtrlPairTick(&lo, 499) == GDAKI_CTRL_PA_NONE && gdakiCtrlPairTick(&lo, 500) == GDAKI_CTRL_PA_RESEND_PAIR);
  CHECK(gdakiCtrlPairTick(&lo, 1000) == GDAKI_CTRL_PA_GIVE_UP && lo.state == GDAKI_CTRL_PS_GAVE_UP);
  CHECK(gdakiCtrlPairOnAck(&lo, 1, 0) == GDAKI_CTRL_PA_DROP);  // an answer after the bound: dropped
  printf("pairing: %llu re-pairings after the setup's pairing (%llu with crossing PAIRs; a launcher as one side in %llu "
         "of 2000 runs), %llu agreed on one generation and each other's endpoint; %llu gave up at the bound on a lossy "
         "network; %llu fresh PSNs, %llu answers on the own prepared QP; %llu datagrams, %llu lost; replays of old "
         "datagrams and another incarnation's PAIR changed nothing\n",
         (unsigned long long)runs, (unsigned long long)crossings, (unsigned long long)launcherRuns, (unsigned long long)ok,
         (unsigned long long)gaveUp, (unsigned long long)fresh, (unsigned long long)reuses, (unsigned long long)sentN,
         (unsigned long long)lostN);
}

// ---- the REJOIN over UD: the nrp block, the idempotency table while HELD, nothing sent before CONNECTED ----
// The header's gdakiCtrlNrpGet (version 1, the rest zero) and the model's gdakiCtrlRejoinNrpOk (integration: phase
// 2a-1's own get with the isAck argument is the two together).
static bool nrpGet(const ln4::gdakiTsMsg& m, struct gdakiCtrlRejoinNrp* out, bool isAck) {
  return gdakiCtrlNrpGet(m.nrp, sizeof(m.nrp), out) && gdakiCtrlRejoinNrpOk(*out, isAck);
}
static void testRejoin(std::mt19937_64& rng) {
  // the nrp block: put and get through the record's nrp[] with memcpy, every field back; malformed ones refused
  ln4::gdakiTsMsg m;
  fillRandom(&m, rng, 32);
  struct gdakiCtrlRejoinNrp n;
  memset(&n, 0, sizeof(n));
  n.version = GDAKI_CTRL_NRP_VERSION;
  n.gen = 9;
  n.probeGen = 4;  // the liveness READ QP's own counter (the header's probeGen; integration)
  struct gdakiCtrlEndpoint e;
  memset(&e, 0, sizeof(e));
  e.qpn = 0x111;
  e.psn = 0xabcde;
  e.mtu = 5;
  e.version = GDAKI_CTRL_EP_VERSION;
  e.qpType = GDAKI_CTRL_QPT_RC;
  n.rec = e;
  e.qpn = 0x112;
  n.probe = e;
  e.qpn = 0x113;
  e.qpType = GDAKI_CTRL_QPT_UD;
  n.ud = e;
  n.page = {0x7f0000001000ull, 0x55, 4096};
  n.outbox = {0x7f0000100000ull, 0x66, GDAKI_CTRL_OUTBOX_BYTES};
  CHECK(gdakiCtrlNrpPut(m.nrp, sizeof(m.nrp), n));
  struct gdakiCtrlRejoinNrp back;
  CHECK(nrpGet(m, &back, false) && memcmp(&back, &n, sizeof(n)) == 0);
  const uint8_t* tail = (const uint8_t*)m.nrp + sizeof(n);
  bool zero = true;
  for (size_t k = 0; k < sizeof(m.nrp) - sizeof(n); k++) zero = zero && tail[k] == 0;
  CHECK(zero);
  struct gdakiCtrlRejoinNrp bad = n;
  bad.version = 0;  // a tcp-path REJOIN: no block
  CHECK(gdakiCtrlNrpPut(m.nrp, sizeof(m.nrp), bad));
  CHECK(!nrpGet(m, &back, false));
  bad = n;
  bad.probe.qpn = bad.rec.qpn;  // one QP for both kinds
  CHECK(gdakiCtrlNrpPut(m.nrp, sizeof(m.nrp), bad));
  CHECK(!nrpGet(m, &back, false));
  bad = n;
  bad.probeGen = 0;  // no liveness READ QP generation
  CHECK(gdakiCtrlNrpPut(m.nrp, sizeof(m.nrp), bad));
  CHECK(!nrpGet(m, &back, false) && !nrpGet(m, &back, true));
  bad = n;
  bad.ud.qpType = GDAKI_CTRL_QPT_RC;
  CHECK(gdakiCtrlNrpPut(m.nrp, sizeof(m.nrp), bad));
  CHECK(!nrpGet(m, &back, false) && nrpGet(m, &back, true));

  // the table: a spare of rank 3 (incarnation 5, record QPN 0x200) sends REJOIN datagrams that are lost, repeated and
  // reordered, and a stray one with another QPN (an earlier attempt's); the existing rule accepts once (known + 1)
  uint64_t accepted = 0, repeats = 0, dropsQpn = 0, lines = 0, notHeld = 0, old = 0;
  for (int run = 0; run < 2000; run++) {
    struct gdakiCtrlRejoinSt t;
    gdakiCtrlRejoinHold(&t, 3);
    const uint32_t known = 4;
    uint32_t acceptedHere = 0;
    std::vector<std::pair<uint32_t, uint32_t>> dg;  // (incarnation, QPN)
    for (int k = 0; k < 6; k++) dg.push_back({5, 0x200});
    for (int k = (int)(rng() % 4); k > 0; k--) dg.push_back({5, 0x1f0 + (uint32_t)(rng() % 3)});
    for (int k = (int)(rng() % 3); k > 0; k--) dg.push_back({4, 0x100});  // the dead incarnation's
    // the existing rule accepts the first REJOIN that reaches it (here the spare's current one); the table answers
    // everything after it, in any order
    std::shuffle(dg.begin() + 1, dg.end(), rng);
    for (const auto& x : dg) {
      bool log = false;
      const uint32_t r = gdakiCtrlRejoinOn(&t, 3, x.first, x.second, &log);
      if (r == GDAKI_CTRL_RJ_RULES) {
        if (x.first == known + 1) {  // the existing rule: HELD, known + 1, nonce, park check
          ln4::gdakiTsMsg ack;
          fillRandom(&ack, rng, 33);
          gdakiCtrlRejoinAccepted(&t, x.first, x.second, &ack, sizeof(ack));
          CHECK(memcmp(t.ack, &ack, sizeof(ack)) == 0);
          acceptedHere++;
        }
      } else if (r == GDAKI_CTRL_RJ_REPEAT) {
        CHECK(x.second == t.qpn);
        repeats++;
      } else if (r == GDAKI_CTRL_RJ_DROP_QPN) {
        CHECK(x.second != t.qpn);
        dropsQpn++;
        lines += log;
      } else if (r == GDAKI_CTRL_RJ_DROP_OLD) {
        CHECK(x.first < t.inc);
        old++;
      } else {
        CHECK(false);
      }
    }
    CHECK(acceptedHere == 1 && t.qpn == 0x200 && t.inc == 5);
    accepted += acceptedHere;
    // the hold ends (restored): the same REJOIN again is not the table's any more
    gdakiCtrlRejoinEnd(&t);
    bool log = false;
    CHECK(gdakiCtrlRejoinOn(&t, 3, 5, 0x200, &log) == GDAKI_CTRL_RJ_NOT_HELD && !log);
    notHeld++;
  }
  CHECK(lines > 0 && lines <= dropsQpn && repeats > 0 && old > 0);

  // after the acceptance the survivor answers the spare's record QP and holds every record until the spare's CONNECTED
  Nic nic(0x42ull);
  nic.pairing(7, 0, rng);  // side 0: the spare (it started: REJOIN), side 1: the survivor
  NicSide& spare = nic.s[0];
  NicSide& surv = nic.s[1];
  ln4::gdakiTsMsg tok;
  fillRandom(&tok, rng, 34);  // TOKEN
  CHECK(gdakiCtrlRingEnqueue(&surv.p, GDAKI_CTRL_K_RECORD, &tok, sizeof(tok)) == 0);
  CHECK(gdakiCtrlRingKick(&surv.p, surv.ops, 0) == 0 && surv.sq.empty() && !gdakiCtrlRingUp(&surv.p));
  CHECK(gdakiCtrlRingKick(&spare.p, spare.ops, 0) == 1);  // CONNECTED
  nic.deliver(0);
  nic.collect(1, 100);
  CHECK(surv.p.connected && gdakiCtrlRingUp(&surv.p));
  CHECK(gdakiCtrlRingKick(&surv.p, surv.ops, 1) == 1 && surv.sq.size() == 1);  // the TOKEN goes now
  printf("rejoin: the nrp block round trip and its checks; %llu holds: one acceptance each, %llu repeats answered from "
         "the table, %llu other-QPN datagrams dropped with %llu GIN/LN lines, %llu older-incarnation drops, after the "
         "hold no table; the survivor sends nothing before the spare's CONNECTED\n",
         (unsigned long long)accepted, (unsigned long long)repeats, (unsigned long long)dropsQpn,
         (unsigned long long)lines, (unsigned long long)old);
  (void)notHeld;
}
#endif

int main() {
  std::mt19937_64 rng(0x6763703261317031ull);  // "gcp2a1p1"
#if !NCCL_GIN_CTRL_TCP
  testWrId(rng);
  testCredit(rng);
  testInbox(rng);
  testOldEnvelope(rng);
  testFraming(rng);
  testPairing(rng);
  testRejoin(rng);
#else
  (void)rng;
  printf("gc_unit_p2 (tcp): the ring and pairing models are not in the tcp build (the region is empty)\n");
#endif
  printf("gc_unit_p2 (%s): %d checks, %d failed\n", NCCL_GIN_CTRL_TCP ? "tcp" : "rdma", nChecks, nFail);
  return nFail == 0 ? 0 : 1;
}
