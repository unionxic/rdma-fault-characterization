// gc_unit_p2a2.cc - CPU unit test of gin-control's phase 2a-2-A (EXPERIMENT.md 9.1 "짝 맺기", 9.6 "작업 시작"; design v3
// 2.1, 2.5, 5.1; impl/notes_p2a2.md): the ring made at the setup, the setup agreement and the first pairing, over a fake
// NIC. Cut out of the working tree's host file by build_gc_p2a2.sh `unit` (p2a2regions): the region "gin-control (ring):
// setup, pure" (gc_setup_pure.inc), the liveness READ QP's pairing link (gc_ring_link.inc), the verbs back end without its
// libibverbs lookups (gc_ring_backend.inc), the host state they read (gc_p2a2_host.inc: struct gdakiMiHostQp,
// gdakiCtrlCq, the probe handoff, struct gdakiCtrlPage, gdakiPageOf, gdakiPageUp, gdakiCtrlProbeAsk/Answer/ErrTake), with
// the ctrl API block (gc_api.inc), the ring model (gc_ring_model.inc), phase 1's pure region (gc_page_pure.inc) and ln4's
// record (gc_ln4_sock.inc). Everything below the template is this file's: the fake verbs (wrap_ibv_*, the host QP
// template, the CQ, the address handles; RC delivery with retransmission until the responder is RTR, RNR, READ with rkey
// and range checks, UD with the Q_Key), the watch thread's answers to the link's requests, the lineage (every rank its
// first incarnation). No NCCL, no CUDA, no verbs device, no network. g++ -std=c++17 with ASan and UBSan.
// What it checks:
//   1. the setup fields and the agreement: this rank's fields (gdakiCtrlSetupMine), the verdict (match, an MTU below
//      2048, a path mismatch, a rank without the ring, thresholds that differ, a rank without transparent recovery not
//      counted), the spare's strict fields, Resume's 41-44 (the fork flag's three values and a missing symbol);
//   2. the same through the setup glue (gdakiCtrlRingSetup, gdakiCtrlRingAgree) on 4 in-process ranks: every rank reaches
//      the same verdict; a ring made on every rank otherwise;
//   3. the first pairing of 2 and of 4 in-process ranks through the back end (the helper's step): both kinds paired in
//      generation 1 on every pair, the record QP's first SEND is CONNECTED (kind 6) from the lower rank, no RC RECV posted
//      before the ring's consumed words are the page's (a late page: the lower rank resends, the pair still forms), the
//      page's rxConsumed[] words are the ring's, a one-way burst of records needs the consumed word's READ of the peer's
//      page and arrives whole and in order, gdakiCtrlChanUp's ring answer stays off until `live`;
//   4. record 55 PROBE_SETUP: an incoming one is dropped with one line per sender, nothing else changes;
// phase 2a-2-B (the regions "live seams" (gc_live.inc), the swap points' bodies (gc_seam_bodies.inc), gdakiTsCauseLiveness
// and gdakiTsMakeUnknown (gc_ts_live.inc), the TCP counters (gc_tcpcount.inc), cut as they are):
//   5. 2 and 4 ranks: the TCP branch before live (bytes counted), live on every rank once both pairings of every peer are
//      up (one line each), the channel answers off the witness's socket state; records both ways on every pair through
//      gdakiCtrlSend and gdakiCtrlPump, byte for byte the stream ln4's gdakiTsSend/gdakiTsPump deliver; gdakiCtrlRecv's
//      timeout, stop and record, gdakiCtrlRecvOn (_RECORD on the ring, _REJOIN on TCP), DATA on TCP counted; a generation
//      change inside a round (the responder's record QP to ERR after it took the REQ): one -1 on each side with a QP
//      cause, the round cancelled as gdakiTsCancelRound does with the witness untouched (MakeUnknown, CauseLiveness:
//      unknown), the re-pairing the peer started, the retry and its ACK, the other pairs unaffected; the witness's BYE,
//      a late record and FIN with the ring live; the control and ring summary lines;
//   6. the switches QP_ERR, CREDIT_STALL, DROP_UD, and malformed values;
// the integration int2 (impl/notes_int2.md; the back end's "launchers' record QPs", the ring's side of phase 3's
// transport table):
//   7. the launcher count into the ring's page layout (rxConsumedL before staleMs, capped at 16), a fake launcher's record
//      QP and UD QP: no QP before the binding, the create (64 RECVs, the consumed word gen << 32), 70 messages through a
//      window of 64 and 32 send slots (envelope kind LAUNCHER, gen, seq 1..70 in order, ackSeq), the launcher's message
//      back (its ackSeq opens the window, the consumed word, the link's queue), the page's beat READ (at most every 50
//      ms), datagrams both ways (Q_Key, a malformed one counted bad), the blob slot READ by the launcher (and one too
//      big), a gap in the launcher's sequence (the loss, taken once; no send after it), a new generation.
#include <algorithm>
#include <atomic>
#include <cerrno>
#include <cstdarg>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <map>
#include <mutex>
#include <random>
#include <set>
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
enum { GDAKI_POLICY_FAILFAST = 0, GDAKI_POLICY_HOLD = 1 };
enum { GDAKI_RS_ACT_GO = 0, GDAKI_RS_ACT_WAIT = 1 };
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

#include "gc_ln4_sock.inc"  // ln4's struct gdakiTsMsg, gdakiTsPeer (the record and the peer the host file has)
#include "gc_api.inc"
#include "gc_ring_model.inc"

static long gChecks = 0, gFailed = 0;
#define CHECK(c)                                                                      \
  do {                                                                                \
    gChecks++;                                                                        \
    if (!(c)) {                                                                       \
      gFailed++;                                                                      \
      if (gFailed <= 60) fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); \
    }                                                                                 \
  } while (0)

#if !NCCL_GIN_CTRL_TCP
#include "gc_page_pure.inc"
#include "ibvcore.h"  // NCCL's verbs types (no libibverbs)

// ---- the log: every line kept (the checks count lines) ----
static std::vector<std::string> gLog;
static bool gEcho = false;
static void logLine(const char* lvl, const char* fmt, ...) __attribute__((format(printf, 2, 3)));
static void logLine(const char* lvl, const char* fmt, ...) {
  char b[1024];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(b, sizeof(b), fmt, ap);
  va_end(ap);
  gLog.push_back(std::string(lvl) + " " + b);
  if (gEcho) printf("  [%s] %s\n", lvl, b);
}
#define WARN(...) logLine("WARN", __VA_ARGS__)
#define INFO(flag, ...) logLine("INFO", __VA_ARGS__)
#define GIN_TS_NOTE(...) logLine("NOTE", __VA_ARGS__)
#define NCCL_NET 0
#define DEFAULT_HOP_LIMIT 255
static size_t logCount(const char* needle) {
  size_t n = 0;
  for (const auto& l : gLog) n += l.find(needle) != std::string::npos;
  return n;
}

// ---- the host file's types this text reads (the fields it reads; the rest is the host file's) ----
struct ncclIbStats {
  int fatalErrorCount = 0;
};
static ncclResult_t ncclIbStatsInit(struct ncclIbStats* s) {
  s->fatalErrorCount = 0;
  return ncclSuccess;
}
struct ncclGinIbCollComm {
  struct {
    struct ibv_pd* pd = nullptr;
    struct ibv_context* context = nullptr;
  } ib;
};
struct gdaki_context {
  int rank = 0;
  struct ncclGinIbCollComm* collComm = nullptr;
  struct ibv_port_attr port_attr;
};
struct gdakiTs {
  std::vector<struct gdakiTsPeer> peers;
  uint64_t nonce = 0;
};
#include "gc_tcpcount.inc"  // 2a-2-B: the TCP branch's counters (the host file's, before its struct gdakiRecHost)
struct gdakiRecHost {
  struct gdaki_context* ctx = nullptr;
  struct gdakiCtrlState* ctrl = nullptr;
  struct gdakiTs* ts = nullptr;
  int nranks = 0;
  struct gdakiCtrlTcpCount ctrlTcp;
};
// the host file's record types and liveness classes this text reads (ln4's values)
enum { GDAKI_TS_REQ = 2, GDAKI_TS_ACK = 3, GDAKI_TS_DONE = 5, GDAKI_TS_BYE = 10 };
enum { GDAKI_TS_LV_NOEVIDENCE = 0, GDAKI_TS_LV_UNKNOWN = 1, GDAKI_TS_LV_DEAD = 2, GDAKI_TS_LV_LEFT = 3 };
// int2 (the watch-thread fix merged): gdakiCtrlProbeAnswer runs the helper's part of the handoff first; the fake watch
// step below takes, does and returns a request in one step, so the helper's part has nothing to do here.
struct gdakiCtrlPage;
static void gdakiProbeHandHelper(struct gdakiRecHost*, struct gdakiCtrlPage*, int) {}
#include "gc_p2a2_host.inc"

// ---- the parameters (the defaults; the threshold of one rank may be moved: gThreshRank, gThreshBump) ----
static int gCurRank = -1, gThreshRank = -1;
static int64_t gThreshBump = 0;
static int64_t ncclParamGinCtrlPage() { return 1; }
static int64_t ncclParamGinTsProbeMs() { return GDAKI_CTRL_PROBE_MS_DEFAULT; }
static int64_t ncclParamGinCtrlProbeTimeoutMs() { return GDAKI_CTRL_PROBE_TIMEOUT_MS_DEFAULT; }
static int64_t ncclParamGinCtrlConfirmMs() { return GDAKI_CTRL_CONFIRM_MS_DEFAULT; }
static int64_t ncclParamGinTsSuspectMs() { return GDAKI_CTRL_SUSPECT_MS_DEFAULT; }
static int64_t ncclParamGinTsStallMs() {
  return GDAKI_CTRL_STALL_MS_DEFAULT + (gCurRank == gThreshRank ? gThreshBump : 0);
}
static int64_t ncclParamGinRestoreMs() { return 20000; }
static int64_t ncclParamGinTsConnectMs() { return 15000; }
static int64_t ncclParamGinTsReconnectMs() { return 10000; }
static int64_t ncclParamIbTimeout() { return 14; }

// ---- the lineage and the incarnation (every rank its first incarnation) ----
static uint32_t gdakiRsSelfInc(struct gdakiRecHost*) { return 0; }
static struct gdakiLnView gdakiLnOf(struct gdakiRecHost*, int) { return gdakiLnSelfView(0); }

// ---- the fake NIC ----
enum { QS_RESET = 0, QS_INIT = 1, QS_RTR = 2, QS_RTS = 3, QS_ERR = 4 };
struct FakeCq {
  struct ibv_cq cq;  // first: the ibv_cq* the text holds is this object
  std::deque<struct ibv_wc> q;
};
struct FakeRwr {
  uint64_t id;
  uint64_t addr;
  uint32_t len, lkey;
};
struct FakeSwr {
  uint64_t id;
  int op;  // IBV_WR_SEND, IBV_WR_RDMA_READ
  std::vector<uint8_t> data;
  uint64_t laddr;
  uint32_t llen;
  uint64_t raddr;
  uint32_t rkey;
  uint32_t dqpn, qkey;  // UD
};
struct FakeQp {
  struct ibv_qp qp;  // first
  int rank = -1;
  uint32_t type = GDAKI_CTRL_QPT_RC, qkey = 0, access = 0;
  FakeCq* cq = nullptr;
  int state = QS_INIT;
  uint32_t remoteQpn = 0;
  std::deque<FakeRwr> rq;
  std::deque<FakeSwr> pend;  // RC: not delivered yet (the responder is not RTR): the NIC retransmits
  bool firstSendSeen = false;
};
struct FakeMr {
  uint32_t access;
  struct ibv_mr* mr;
};
static std::map<uint32_t, FakeQp*> gQps;    // by QP number
static std::map<uint32_t, FakeMr> gMrs;     // by key (lkey = rkey)
static uint32_t gNextQpn = 0x100, gNextKey = 0x1000;
static std::set<FakeCq*> gCqs;
static std::set<struct ibv_ah*> gAhs;
static std::set<int> gChanFds;
// what the checks count
static uint64_t gRcRecvBeforeBound = 0, gRcRecvPosts = 0, gConnectedFirst = 0, gNotConnectedFirst = 0,
                gConnectedFromHigher = 0, gUdSent = 0, gUdDropped = 0, gRnr = 0, gReads = 0, gReadErr = 0;
static std::vector<const bool*> gBoundOf;  // by rank: the ring's `bound` (the check that nothing posts before it)

static void cqPush(FakeCq* c, uint64_t id, int status, uint32_t len, uint32_t qpn, int opcode) {
  struct ibv_wc w;
  memset(&w, 0, sizeof(w));
  w.wr_id = id;
  w.status = (enum ibv_wc_status)status;
  w.byte_len = len;
  w.qp_num = qpn;
  w.opcode = (enum ibv_wc_opcode)opcode;
  c->q.push_back(w);
}
static void qpToErr(FakeQp* q) {
  if (q->state == QS_ERR) return;
  q->state = QS_ERR;
  for (const FakeRwr& r : q->rq) cqPush(q->cq, r.id, IBV_WC_WR_FLUSH_ERR, 0, q->qp.qp_num, IBV_WC_RECV);
  q->rq.clear();
  for (const FakeSwr& s : q->pend) cqPush(q->cq, s.id, IBV_WC_WR_FLUSH_ERR, 0, q->qp.qp_num, IBV_WC_SEND);
  q->pend.clear();
}
// One request of `s` toward its peer: true when it completed (either way), false: still in flight (the responder not RTR).
static bool deliver(FakeQp* s, const FakeSwr& w) {
  if (s->type == GDAKI_CTRL_QPT_UD) {
    auto it = gQps.find(w.dqpn);
    FakeQp* d = it != gQps.end() ? it->second : nullptr;
    if (d != nullptr && d->type == GDAKI_CTRL_QPT_UD && d->state >= QS_RTR && d->state != QS_ERR && d->qkey == w.qkey &&
        !d->rq.empty() && w.data.size() + GDAKI_CTRL_UD_GRH_BYTES <= d->rq.front().len) {
      const FakeRwr r = d->rq.front();
      d->rq.pop_front();
      memset((void*)(uintptr_t)r.addr, 0, GDAKI_CTRL_UD_GRH_BYTES);
      memcpy((uint8_t*)(uintptr_t)r.addr + GDAKI_CTRL_UD_GRH_BYTES, w.data.data(), w.data.size());
      cqPush(d->cq, r.id, IBV_WC_SUCCESS, (uint32_t)(w.data.size() + GDAKI_CTRL_UD_GRH_BYTES), d->qp.qp_num, IBV_WC_RECV);
    } else {
      gUdDropped++;  // UD: no receiver ready, the datagram is gone
    }
    gUdSent++;
    cqPush(s->cq, w.id, IBV_WC_SUCCESS, 0, s->qp.qp_num, IBV_WC_SEND);
    return true;
  }
  auto it = gQps.find(s->remoteQpn);
  FakeQp* d = it != gQps.end() ? it->second : nullptr;
  if (d == nullptr || d->state == QS_ERR || d->remoteQpn != s->qp.qp_num) {
    cqPush(s->cq, w.id, IBV_WC_RETRY_EXC_ERR, 0, s->qp.qp_num, IBV_WC_SEND);
    qpToErr(s);
    return true;
  }
  if (d->state < QS_RTR) return false;  // retransmitted later
  if (w.op == IBV_WR_RDMA_READ) {
    gReads++;
    auto m = gMrs.find(w.rkey);
    const bool ok = m != gMrs.end() && (m->second.access & IBV_ACCESS_REMOTE_READ) &&
                    w.raddr >= (uint64_t)(uintptr_t)m->second.mr->addr &&
                    w.raddr + w.llen <= (uint64_t)(uintptr_t)m->second.mr->addr + m->second.mr->length;
    if (!ok) {
      gReadErr++;
      cqPush(s->cq, w.id, IBV_WC_REM_ACCESS_ERR, 0, s->qp.qp_num, IBV_WC_RDMA_READ);
      qpToErr(s);
      return true;
    }
    memcpy((void*)(uintptr_t)w.laddr, (const void*)(uintptr_t)w.raddr, w.llen);
    cqPush(s->cq, w.id, IBV_WC_SUCCESS, w.llen, s->qp.qp_num, IBV_WC_RDMA_READ);
    return true;
  }
  if (d->rq.empty()) {
    gRnr++;
    cqPush(s->cq, w.id, IBV_WC_RNR_RETRY_EXC_ERR, 0, s->qp.qp_num, IBV_WC_SEND);
    qpToErr(s);
    return true;
  }
  const FakeRwr r = d->rq.front();
  d->rq.pop_front();
  if (w.data.size() > r.len) {
    cqPush(d->cq, r.id, IBV_WC_LOC_LEN_ERR, 0, d->qp.qp_num, IBV_WC_RECV);
    qpToErr(d);
    cqPush(s->cq, w.id, IBV_WC_REM_OP_ERR, 0, s->qp.qp_num, IBV_WC_SEND);
    qpToErr(s);
    return true;
  }
  if (!s->firstSendSeen && w.data.size() >= sizeof(struct gdakiCtrlEnv)) {  // the QP's first SEND: what it carries
    s->firstSendSeen = true;
    struct gdakiCtrlEnv e;
    memcpy(&e, w.data.data(), sizeof(e));
    if (e.kind == GDAKI_CTRL_K_CONNECTED) {
      gConnectedFirst++;
      if (s->rank > d->rank) gConnectedFromHigher++;
    } else {
      gNotConnectedFirst++;
    }
  }
  memcpy((void*)(uintptr_t)r.addr, w.data.data(), w.data.size());
  cqPush(d->cq, r.id, IBV_WC_SUCCESS, (uint32_t)w.data.size(), d->qp.qp_num, IBV_WC_RECV);
  cqPush(s->cq, w.id, IBV_WC_SUCCESS, 0, s->qp.qp_num, IBV_WC_SEND);
  return true;
}
static void pumpAll() {
  for (auto& kv : gQps) {
    FakeQp* q = kv.second;
    while (!q->pend.empty() && q->state == QS_RTS) {
      if (!deliver(q, q->pend.front())) break;
      if (!q->pend.empty()) q->pend.pop_front();
    }
  }
}
static FakeQp* fqOf(struct ibv_qp* qp) { return (FakeQp*)qp; }
static ncclResult_t wrap_ibv_post_send(struct ibv_qp* qp, struct ibv_send_wr* wr, struct ibv_send_wr** bad) {
  FakeQp* q = fqOf(qp);
  *bad = nullptr;
  if (q->state != QS_RTS) {
    *bad = wr;
    return ncclSystemError;
  }
  FakeSwr s;
  s.id = wr->wr_id;
  s.op = wr->opcode;
  s.laddr = wr->sg_list[0].addr;
  s.llen = wr->sg_list[0].length;
  if (wr->opcode == IBV_WR_SEND)
    s.data.assign((const uint8_t*)(uintptr_t)s.laddr, (const uint8_t*)(uintptr_t)s.laddr + s.llen);
  s.raddr = wr->wr.rdma.remote_addr;
  s.rkey = wr->wr.rdma.rkey;
  if (q->type == GDAKI_CTRL_QPT_UD) {
    s.dqpn = wr->wr.ud.remote_qpn;
    s.qkey = wr->wr.ud.remote_qkey;
    (void)deliver(q, s);
  } else {
    q->pend.push_back(s);
    pumpAll();
  }
  return ncclSuccess;
}
static ncclResult_t wrap_ibv_post_recv(struct ibv_qp* qp, struct ibv_recv_wr* wr, struct ibv_recv_wr** bad) {
  FakeQp* q = fqOf(qp);
  *bad = nullptr;
  if (q->state == QS_ERR || q->state == QS_RESET) {
    *bad = wr;
    return ncclSystemError;
  }
  if (q->type == GDAKI_CTRL_QPT_RC) {
    gRcRecvPosts++;
    if (q->rank >= 0 && q->rank < (int)gBoundOf.size() && gBoundOf[(size_t)q->rank] != nullptr &&
        !*gBoundOf[(size_t)q->rank])
      gRcRecvBeforeBound++;
  }
  q->rq.push_back({wr->wr_id, wr->sg_list[0].addr, wr->sg_list[0].length, wr->sg_list[0].lkey});
  return ncclSuccess;
}
static ncclResult_t wrap_ibv_modify_qp(struct ibv_qp* qp, struct ibv_qp_attr* a, int mask) {
  FakeQp* q = fqOf(qp);
  if (!(mask & IBV_QP_STATE)) return ncclSuccess;
  switch (a->qp_state) {
    case IBV_QPS_ERR: qpToErr(q); break;
    case IBV_QPS_RESET:
      q->state = QS_RESET;
      q->rq.clear();
      q->pend.clear();
      q->firstSendSeen = false;
      break;
    case IBV_QPS_INIT: q->state = QS_INIT; break;
    case IBV_QPS_RTR: q->state = QS_RTR; break;
    case IBV_QPS_RTS: q->state = QS_RTS; break;
    default: break;
  }
  pumpAll();
  return ncclSuccess;
}
static ncclResult_t wrap_ibv_poll_cq(struct ibv_cq* cq, int n, struct ibv_wc* wc, int* got) {
  pumpAll();
  FakeCq* c = (FakeCq*)cq;
  int k = 0;
  while (k < n && !c->q.empty()) {
    wc[k++] = c->q.front();
    c->q.pop_front();
  }
  *got = k;
  return ncclSuccess;
}
static struct ibv_mr* wrap_direct_ibv_reg_mr(struct ibv_pd* pd, void* addr, size_t len, int access) {
  struct ibv_mr* m = new ibv_mr();
  m->pd = pd;
  m->addr = addr;
  m->length = len;
  m->lkey = m->rkey = gNextKey++;
  gMrs[m->lkey] = {(uint32_t)access, m};
  return m;
}
static ncclResult_t wrap_ibv_dereg_mr(struct ibv_mr* m) {
  gMrs.erase(m->lkey);
  delete m;
  return ncclSuccess;
}
static int fakeNotify(struct ibv_cq*, int) { return 0; }
// the host QP template (the host file's gdakiMiHostQpCreate, Connect, Destroy, Psn) on the fake NIC
static uint32_t gdakiMiHostQpPsn() {
  static std::mt19937 rng(12345);
  return (uint32_t)rng() & 0xffffffu;
}
static ncclResult_t gdakiMiHostQpCreate(struct gdakiRecHost* r, int maxRdAtomic, struct gdakiMiHostQp** out,
                                        struct gdakiMiQpEndpoint* local, char* why, size_t whyLen,
                                        const struct gdakiCtrlQpAttr& attr) {
  if (attr.cq == nullptr) {
    snprintf(why, whyLen, "the fake template needs an owner's CQ");
    return ncclInternalError;
  }
  struct gdakiMiHostQp* q = new gdakiMiHostQp();
  FakeQp* f = new FakeQp();
  f->qp.qp_num = gNextQpn++;
  f->qp.context = r->ctx->collComm->ib.context;
  f->rank = r->ctx->rank;
  f->type = attr.qpType;
  f->qkey = attr.qkey;
  f->access = attr.access;
  f->cq = (FakeCq*)attr.cq;
  f->state = QS_INIT;
  gQps[f->qp.qp_num] = f;
  q->attr = attr;
  q->ownCq = false;
  q->cq = (struct ibv_cq*)attr.cq;
  q->qp = &f->qp;
  q->maxRdAtomic = maxRdAtomic;
  q->port = 1;
  q->roce = true;
  q->gidIndex = 3;
  q->mtu = r->ctx->port_attr.active_mtu;
  q->psn = gdakiMiHostQpPsn();
  memset(local, 0, sizeof(*local));
  local->qpn = f->qp.qp_num;
  local->psn = q->psn;
  local->mtu = (int32_t)q->mtu;
  local->gid[15] = (uint8_t)f->rank;
  local->gidIndex = q->gidIndex;
  *out = q;
  return ncclSuccess;
}
static ncclResult_t gdakiMiHostQpConnect(struct gdakiMiHostQp* q, const struct gdakiMiQpEndpoint& remote, char*, size_t) {
  FakeQp* f = fqOf(q->qp);
  if (f->type == GDAKI_CTRL_QPT_RC) f->remoteQpn = remote.qpn;
  f->state = QS_RTS;
  pumpAll();
  return ncclSuccess;
}
static void gdakiMiHostQpDestroy(struct gdakiMiHostQp* q) {
  if (q == nullptr) return;
  if (q->qp != nullptr) {
    FakeQp* f = fqOf(q->qp);
    gQps.erase(f->qp.qp_num);
    delete f;
  }
  delete q;
}
static ncclResult_t gdakiCtrlCqCreate(struct gdakiRecHost* r, int depth, bool withChannel, struct gdakiCtrlCq** out,
                                      char* why, size_t whyLen) {
  (void)depth;
  (void)why;
  (void)whyLen;
  struct gdakiCtrlCq* c = new gdakiCtrlCq();
  FakeCq* f = new FakeCq();
  f->cq.context = r->ctx->collComm->ib.context;
  gCqs.insert(f);
  c->cq = &f->cq;
  if (withChannel) {
    int fds[2];
    if (pipe(fds) != 0) return ncclSystemError;
    close(fds[1]);
    gChanFds.insert(fds[0]);
    c->channel = new ibv_comp_channel();
    c->channel->fd = fds[0];
    c->channel->context = f->cq.context;
  }
  *out = c;
  return ncclSuccess;
}
static bool gdakiCtrlCqDestroy(struct gdakiCtrlCq* c) {
  if (c == nullptr) return true;
  FakeCq* f = (FakeCq*)c->cq;
  gCqs.erase(f);
  delete f;
  if (c->channel != nullptr) {
    gChanFds.erase(c->channel->fd);
    close(c->channel->fd);
    delete c->channel;
  }
  delete c;
  return true;
}
// the libibverbs lookups (the back end's sub-region, cut out): the fake's
static int gForkStatus = GDAKI_CTRL_FORK_UNNEEDED;
static bool gForkMissing = false;
static struct ibv_ah* fakeCreateAh(struct ibv_pd* pd, struct ibv_ah_attr*) {
  struct ibv_ah* a = new ibv_ah();
  a->pd = pd;
  gAhs.insert(a);
  return a;
}
static int fakeDestroyAh(struct ibv_ah* a) {
  gAhs.erase(a);
  delete a;
  return 0;
}
static int fakeGetCqEvent(struct ibv_comp_channel*, struct ibv_cq**, void**) { return -1; }
static void fakeAckCqEvents(struct ibv_cq*, unsigned int) {}
static int fakeIsForkInit(void) { return gForkStatus; }
struct gdakiCtrlVerbs {
  bool tried = false, ok = false;
  struct ibv_ah* (*createAh)(struct ibv_pd*, struct ibv_ah_attr*) = nullptr;
  int (*destroyAh)(struct ibv_ah*) = nullptr;
  int (*getCqEvent)(struct ibv_comp_channel*, struct ibv_cq**, void**) = nullptr;
  void (*ackCqEvents)(struct ibv_cq*, unsigned int) = nullptr;
  int (*isForkInit)(void) = nullptr;
};
static const struct gdakiCtrlVerbs* gdakiCtrlVerbsOf() {
  static struct gdakiCtrlVerbs v;
  v.tried = v.ok = true;
  v.createAh = fakeCreateAh;
  v.destroyAh = fakeDestroyAh;
  v.getCqEvent = fakeGetCqEvent;
  v.ackCqEvents = fakeAckCqEvents;
  v.isForkInit = gForkMissing ? nullptr : fakeIsForkInit;
  return &v;
}

// Resume's inputs as far as this text fills them (the host file's struct is gin-restore's, rs_unit_host.cc tests it)
struct gdakiRsLocalIn {
  const char *gc41 = nullptr, *gc42 = nullptr, *gc43 = nullptr, *gc44 = nullptr;
};
#include "gc_setup_pure.inc"
#include "gc_ring_link.inc"
#include "gc_ring_backend.inc"
#include "gc_live.inc"         // 2a-2-B: the live seams (the hooks, the witness pump, the live step, the summary)
#include "gc_seam_bodies.inc"  // 2a-2-B: the swap points' bodies of the "[2] ring" placeholders
#include "gc_ts_live.inc"      // 2a-2-B: gdakiTsCauseLiveness and gdakiTsMakeUnknown with their record-QP lines
static bool gArmed = true;     // the communicator is armed (or has no restore): the switches' origin
static bool gdakiCtrlArmedNow(struct gdakiRecHost*) { return gArmed; }

// ---- in-process ranks ----
static uint64_t mix64(uint64_t x) {  // the host file's gdakiTsMix64
  x += 0x9e3779b97f4a7c15ull;
  x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ull;
  x = (x ^ (x >> 27)) * 0x94d049bb133111ebull;
  return x ^ (x >> 31);
}
struct Rank {
  struct ibv_context ictx;
  struct ibv_pd pd;
  struct ncclGinIbCollComm cc;
  struct gdaki_context ctx;
  struct gdakiRecHost r;
  struct gdakiCtrlState st;
  struct gdakiTs ts;
  struct gdakiCtrlSetupAddr mine;
  uint64_t salt = 0;
  double pageAtMs = 0;  // the status page comes up then (the helper's step binds it)
  uint32_t watchQpn = 0;
  uint64_t watchConnects = 0;
};
static void rankInit(Rank& k, int i, int n, uint32_t mtu) {
  memset(&k.ictx, 0, sizeof(k.ictx));
  k.ictx.ops.req_notify_cq = fakeNotify;
  memset(&k.pd, 0, sizeof(k.pd));
  k.pd.context = &k.ictx;
  k.cc.ib.pd = &k.pd;
  k.cc.ib.context = &k.ictx;
  memset(&k.ctx.port_attr, 0, sizeof(k.ctx.port_attr));
  k.ctx.port_attr.active_mtu = (enum ibv_mtu)mtu;
  k.ctx.rank = i;
  k.ctx.collComm = &k.cc;
  k.r.ctx = &k.ctx;
  k.r.ctrl = &k.st;
  k.r.nranks = n;
  k.salt = mix64(0x5a17ull + (uint64_t)i * 977u);
  k.watchQpn = 0xa00000u + (uint32_t)i * 0x100u;
}
static void pageUp(Rank& k, int n) {
  struct gdakiCtrlPage* pg = new gdakiCtrlPage();
  pg->me = k.ctx.rank;
  CHECK(gdakiCtrlPageLayoutOf((uint32_t)n, 0, &pg->layout));
  CHECK(posix_memalign(&pg->page, 4096, GDAKI_CTRL_PAGE_BYTES) == 0);
  memset(pg->page, 0, GDAKI_CTRL_PAGE_BYTES);
  pg->head = (struct gdakiCtrlPageHead*)pg->page;
  pg->pageMr = wrap_direct_ibv_reg_mr(&k.pd, pg->page, GDAKI_CTRL_PAGE_BYTES, IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_READ);
  pg->peers = std::vector<struct gdakiCtrlPeerProbe>((size_t)n);
  for (int p = 0; p < n; p++) pg->peers[(size_t)p].hasQp = p != k.ctx.rank;
  pg->up.store(true, std::memory_order_release);
  __atomic_store_n(&k.st.page, pg, __ATOMIC_RELEASE);
}
static void pageDown(Rank& k) {
  struct gdakiCtrlPage* pg = k.st.page;
  if (pg == nullptr) return;
  (void)wrap_ibv_dereg_mr(pg->pageMr);
  free(pg->page);
  delete pg;
  k.st.page = nullptr;
}
// The watch thread's side of the link (gdakiCtrlProbeAsk's requests): PREPARE gives a fresh PSN unlike the last one,
// CONNECT takes the peer's endpoint and page. int2: through the handoff's pure steps (struct gdakiCtrlProbeHand: NEW ->
// take -> FW -> done -> BACK -> IDLE, the answer's `done`); the fake QP has no READs in flight, so no DRAIN.
static void watchStep(Rank& k) {
  struct gdakiCtrlPage* pg = gdakiPageOf(&k.r);
  if (!gdakiPageUp(pg)) return;
  for (int p = 0; p < (int)pg->peers.size(); p++) {
    struct gdakiCtrlPeerProbe& pp = pg->peers[(size_t)p];
    std::lock_guard<std::mutex> lk(pg->mu);
    struct gdakiCtrlProbeHand& h = pp.hand;
    if (h.phase != GDAKI_CTRL_PH_NEW) continue;
    (void)gdakiCtrlHandTake(&h, true, false, false, 0, 0);
    CHECK(h.phase == GDAKI_CTRL_PH_FW && h.seq == pp.req.seq);
    struct gdakiMiQpEndpoint v1;
    memset(&v1, 0, sizeof(v1));
    v1.qpn = k.watchQpn + (uint32_t)p;
    do v1.psn = gdakiMiHostQpPsn(); while (pp.req.haveAvoid && v1.psn == pp.req.avoidPsn);
    v1.mtu = 5;
    v1.gidIndex = 3;
    pp.res = gdakiCtrlProbeRes();
    pp.res.seq = pp.req.seq;
    pp.res.ok = true;
    pp.res.gen = pp.req.gen;
    pp.res.local = gdakiCtrlEndpointOf(v1, GDAKI_CTRL_QPT_RC);
    if (pp.req.op == GDAKI_CTRL_PO_CONNECT) {
      pp.remotePage = pp.req.page;
      pp.haveRemote = true;
      k.watchConnects++;
    }
    gdakiCtrlHandFwDone(&h);
    gdakiCtrlHandBack(&h);
    CHECK(h.done == pp.req.seq && h.phase == GDAKI_CTRL_PH_IDLE);
  }
}
static void allGatherAgree(std::vector<Rank>& R, std::vector<const char*>* offs, std::vector<bool> on = {},
                           const struct gdakiCtrlSetupAddr* rec = nullptr, int recRank = -1) {
  const int n = (int)R.size();
  for (int i = 0; i < n; i++) {
    gCurRank = i;
    gdakiCtrlRingSetup(&R[(size_t)i].r, on.empty() ? true : (bool)on[(size_t)i], i, n, R[(size_t)i].salt,
                       &R[(size_t)i].mine);
  }
  gCurRank = -1;
  uint64_t nonce = 0x6e6f6e6365ull;
  for (int i = 0; i < n; i++) nonce = mix64(nonce ^ R[(size_t)i].salt);
  std::vector<const struct gdakiCtrlSetupAddr*> ptr((size_t)n);
  for (int i = 0; i < n; i++) ptr[(size_t)i] = &R[(size_t)i].mine;
  offs->assign((size_t)n, nullptr);
  for (int i = 0; i < n; i++) {
    (*offs)[(size_t)i] = gdakiCtrlRingAgree(&R[(size_t)i].r, i, n, nonce, ptr.data(), i == recRank ? rec : nullptr);
    R[(size_t)i].ts.nonce = nonce;
  }
}
static void teardown(std::vector<Rank>& R) {
  for (auto& k : R) {
    if (k.st.ring != nullptr) gdakiCtrlRdmaDestroy(k.st.ring);
    k.st.ring = nullptr;
    pageDown(k);
  }
  gBoundOf.clear();
}

// ---- 1. the fields and the agreement (pure) ----
static void testAgreePure() {
  const int n = 4;
  struct gdakiCtrlThresholds t;
  struct gdakiCtrlEndpoint ud;
  memset(&ud, 0, sizeof(ud));
  ud.version = GDAKI_CTRL_EP_VERSION;
  ud.qpType = GDAKI_CTRL_QPT_UD;
  ud.mtu = 5;
  struct gdakiCtrlRegion ob = {0x1000, 7, GDAKI_CTRL_OUTBOX_BYTES};
  std::vector<struct gdakiCtrlSetupAddr> a((size_t)n);
  auto reset = [&]() {
    for (int p = 0; p < n; p++) {
      ud.qpn = 0x40u + (uint32_t)p;
      ud.psn = 0x1234u + (uint32_t)p;  // each rank's own Q_Key
      gdakiCtrlSetupMine(&a[(size_t)p], true, ud, ob, 5, GDAKI_CTRL_FORK_UNNEEDED, t);
    }
  };
  auto run = [&](uint32_t want, const char* wantOff, int wantWho, std::vector<bool> skip = {}) {
    std::vector<const struct gdakiCtrlSetupAddr*> ptr((size_t)n);
    for (int p = 0; p < n; p++) ptr[(size_t)p] = (!skip.empty() && skip[(size_t)p]) ? nullptr : &a[(size_t)p];
    struct gdakiCtrlSetupOut o;
    const char* off = nullptr;
    CHECK(gdakiCtrlSetupVerdict(ptr.data(), n, &o, &off) == want);
    CHECK(o.agreed && o.verdict == want);
    CHECK((wantOff == nullptr) == (off == nullptr));
    if (wantOff != nullptr && off != nullptr) CHECK(strcmp(off, wantOff) == 0);
    CHECK(o.who == wantWho);
    return o;
  };
  reset();
  CHECK(sizeof(struct gdakiCtrlSetupAddr) == 168);
  CHECK(a[0].path == GDAKI_CTRL_PATH_RDMA && a[0].launcherNode == GDAKI_CTRL_LAUNCHER_NODE_NONE && a[0].ud.qpn == 0x40u &&
        a[0].outbox.rkey == 7 && a[0].page.addr == 0 && a[0].stallMs == GDAKI_CTRL_STALL_MS_DEFAULT);
  struct gdakiCtrlSetupOut o = run(0, nullptr, -1);  // match
  CHECK(o.minMtu == 5 && o.why[0] == 0);
  a[2].activeMtu = 3;  // IBV_MTU_1024 on rank 2
  o = run(42, GDAKI_CTRL_R42, 2);
  CHECK(o.minMtu == 3 && strstr(o.why, "rank 2") != nullptr);
  a[2].activeMtu = 4;  // exactly 2048 is enough
  run(0, nullptr, -1);
  reset();
  gdakiCtrlSetupMine(&a[1], false, ud, ob, 5, GDAKI_CTRL_FORK_UNNEEDED, t);  // rank 1 without the ring
  CHECK(a[1].path == GDAKI_CTRL_PATH_RDMA_OFF && a[1].ud.qpn == 0 && a[1].outbox.addr == 0);
  run(44, GDAKI_CTRL_R44, 1);
  a[1].path = 7;  // another build's path value
  run(44, GDAKI_CTRL_R44, 1);
  for (int p = 0; p < n; p++) gdakiCtrlSetupMine(&a[(size_t)p], false, ud, ob, 3, 0, t);  // no ring anywhere
  run(0, nullptr, -1);  // nothing to agree on: the records stay on the TCP path (MTU and thresholds not asked)
  reset();
  a[3].stallMs++;  // thresholds differ
  o = run(44, GDAKI_CTRL_R44T, 3);
  CHECK(o.sa == GDAKI_CTRL_SA_THRESH);
  reset();
  a[3].probeTimeoutMs = 1;
  run(44, GDAKI_CTRL_R44T, 3);
  reset();
  a[2].path = GDAKI_CTRL_PATH_RDMA_OFF;  // rank 2 without transparent recovery: not counted
  run(0, nullptr, -1, {false, false, true, false});
  reset();
  a[1].activeMtu = 2;
  a[3].path = GDAKI_CTRL_PATH_RDMA_OFF;
  run(44, GDAKI_CTRL_R44, 3);  // the path before the MTU (the path's own loop first)
  // the spare's strict fields
  reset();
  char w[128];
  struct gdakiCtrlSetupAddr rec = a[0], now = a[0];
  now.ud.qpn = 0x99;  // may differ
  now.outbox.addr = 0x2000;
  now.activeMtu = 4;
  CHECK(gdakiCtrlSpareCtlMatch(rec, now, w, sizeof(w)));
  now.path = GDAKI_CTRL_PATH_RDMA_OFF;
  CHECK(!gdakiCtrlSpareCtlMatch(rec, now, w, sizeof(w)) && strstr(w, "path") != nullptr);
  now.path = rec.path;
  now.launcherNode = 2;
  CHECK(!gdakiCtrlSpareCtlMatch(rec, now, w, sizeof(w)) && strstr(w, "launcher node") != nullptr);
  // Resume's 41-44
  char buf[4][GDAKI_CTRL_RESUME_WHY];
  const char *c41, *c42, *c43, *c44;
  gdakiCtrlResumeConds(nullptr, true, false, buf, &c41, &c42, &c43, &c44);
  CHECK(!c41 && !c42 && !c43 && !c44);  // no ring: none
  struct gdakiCtrlSetupOut so;
  so.agreed = true;
  so.fork = GDAKI_CTRL_FORK_UNNEEDED;
  gdakiCtrlResumeConds(&so, false, false, buf, &c41, &c42, &c43, &c44);
  CHECK(!c41 && !c42 && !c43 && !c44);
  gdakiCtrlResumeConds(&so, true, false, buf, &c41, &c42, &c43, &c44);  // a named launcher not paired
  CHECK(c41 != nullptr && strcmp(c41, GDAKI_CTRL_R41) == 0 && !c42 && !c43 && !c44);
  gdakiCtrlResumeConds(&so, true, true, buf, &c41, &c42, &c43, &c44);
  CHECK(!c41);
  const uint32_t forks[3] = {0u, 1u, 0xffu};  // IBV_FORK_DISABLED, IBV_FORK_ENABLED, the symbol missing
  const char* forkTxt[3] = {"IBV_FORK_DISABLED", "IBV_FORK_ENABLED", "missing"};
  for (int i = 0; i < 3; i++) {
    so.fork = forks[i];
    gdakiCtrlResumeConds(&so, false, false, buf, &c41, &c42, &c43, &c44);
    CHECK(c43 != nullptr && strncmp(c43, GDAKI_CTRL_R43, strlen(GDAKI_CTRL_R43)) == 0 && strstr(c43, forkTxt[i]) != nullptr);
  }
  so.fork = GDAKI_CTRL_FORK_UNNEEDED;
  so.verdict = 42;
  snprintf(so.why, sizeof(so.why), "rank 3's active MTU (enum 3) is below 2048");
  gdakiCtrlResumeConds(&so, false, false, buf, &c41, &c42, &c43, &c44);
  CHECK(c42 != nullptr && strstr(c42, GDAKI_CTRL_R42) == c42 && strstr(c42, "rank 3") != nullptr && !c44);
  so.verdict = 44;
  so.sa = GDAKI_CTRL_SA_THRESH;
  gdakiCtrlResumeConds(&so, false, false, buf, &c41, &c42, &c43, &c44);
  CHECK(c44 != nullptr && strstr(c44, GDAKI_CTRL_R44T) == c44 && !c42);
  so.verdict = 0;
  so.sa = 0;
  so.spareDiffers = true;
  gdakiCtrlResumeConds(&so, false, false, buf, &c41, &c42, &c43, &c44);
  CHECK(c44 != nullptr && strstr(c44, GDAKI_CTRL_R44) == c44);
  // the binding of the consumed words
  uint64_t own[4] = {gdakiCtrlGenCount(1, 5), 0, gdakiCtrlGenCount(1, 64), gdakiCtrlGenCount(2, 1)};
  uint64_t page[4] = {9, 9, 9, 9};
  uint64_t* to = gdakiCtrlBindWords(own, page, 4);
  CHECK(to == page && memcmp(own, page, sizeof(own)) == 0);
  printf("agreement: the fields, match, MTU 1024 (42), 2048 enough, a rank without the ring and an unknown path (44), no "
         "ring anywhere (0), thresholds (44, its own text), a rank without transparent recovery not counted, the spare's "
         "strict fields, Resume's 41-44 with the fork flag's three values\n");
}

// ---- 2. the setup glue on 4 ranks: the same verdict everywhere ----
static void testSetupGlue() {
  struct Case {
    const char* what;
    std::vector<uint32_t> mtu;
    std::vector<bool> on;
    int threshRank;
    const char* want;
    uint32_t verdict;
  };
  const std::vector<Case> cs = {
      {"match", {5, 5, 4, 5}, {}, -1, nullptr, 0},
      {"rank 2 MTU 1024", {5, 5, 3, 5}, {}, -1, GDAKI_CTRL_R42, 42},
      {"rank 1 without the ring", {5, 5, 5, 5}, {true, false, true, true}, -1, GDAKI_CTRL_R44, 44},
      {"rank 3's STALL_MS", {5, 5, 5, 5}, {}, 3, GDAKI_CTRL_R44T, 44},
  };
  for (const Case& c : cs) {
    std::vector<Rank> R(4);
    gBoundOf.assign(4, nullptr);
    for (int i = 0; i < 4; i++) rankInit(R[(size_t)i], i, 4, c.mtu[(size_t)i]);
    gThreshRank = c.threshRank;
    gThreshBump = 1;
    const size_t lines0 = logCount("control setup path=");
    std::vector<const char*> offs;
    allGatherAgree(R, &offs, c.on);
    gThreshRank = -1;
    CHECK(logCount("control setup path=") == lines0 + 4);  // one line per rank, with its active_mtu
    for (int i = 0; i < 4; i++) {
      const bool ringWanted = c.on.empty() || c.on[(size_t)i];
      CHECK((R[(size_t)i].st.ring != nullptr) == ringWanted);
      CHECK((offs[(size_t)i] == nullptr) == (c.want == nullptr));
      if (c.want != nullptr && offs[(size_t)i] != nullptr) CHECK(strcmp(offs[(size_t)i], c.want) == 0);
      if (R[(size_t)i].st.ring != nullptr) {
        const struct gdakiCtrlSetupOut& o = R[(size_t)i].st.ring->setup;
        CHECK(o.agreed && o.verdict == c.verdict && o.activeMtu == c.mtu[(size_t)i] && o.fork == GDAKI_CTRL_FORK_UNNEEDED);
        CHECK(R[(size_t)i].mine.ud.qpn == R[(size_t)i].st.ring->udLocal.qpn && R[(size_t)i].mine.ud.psn == R[(size_t)i].st.ring->qkey);
      }
    }
    teardown(R);
  }
  // the fork flag and a missing symbol through the glue (Resume's 43 on that rank only)
  for (int mode = 0; mode < 2; mode++) {
    std::vector<Rank> R(2);
    gBoundOf.assign(2, nullptr);
    for (int i = 0; i < 2; i++) rankInit(R[(size_t)i], i, 2, 5);
    gForkStatus = mode == 0 ? 1 : GDAKI_CTRL_FORK_UNNEEDED;
    gForkMissing = mode == 1;
    std::vector<const char*> offs;
    allGatherAgree(R, &offs);
    gForkStatus = GDAKI_CTRL_FORK_UNNEEDED;
    gForkMissing = false;
    CHECK(offs[0] == nullptr && offs[1] == nullptr);  // 43 does not turn transparent recovery off at the setup
    char buf[4][GDAKI_CTRL_RESUME_WHY];
    struct gdakiRsLocalIn in;
    gdakiCtrlResumeFacts(&R[0].r, &in, buf);  // the host glue Resume calls
    CHECK(in.gc43 != nullptr && R[0].mine.fork == (mode == 0 ? 1u : 0xffu) && !in.gc42 && !in.gc44);
    teardown(R);
  }
  // a spare whose path is not its transcript's
  {
    std::vector<Rank> R(2);
    gBoundOf.assign(2, nullptr);
    for (int i = 0; i < 2; i++) rankInit(R[(size_t)i], i, 2, 5);
    struct gdakiCtrlSetupAddr rec;
    memset(&rec, 0, sizeof(rec));
    rec.path = GDAKI_CTRL_PATH_RDMA_OFF;  // the first incarnation had no ring
    rec.launcherNode = GDAKI_CTRL_LAUNCHER_NODE_NONE;
    std::vector<const char*> offs;
    allGatherAgree(R, &offs, {}, &rec, 1);
    CHECK(offs[0] == nullptr && offs[1] != nullptr && strcmp(offs[1], GDAKI_CTRL_R44) == 0);
    CHECK(R[1].st.ring->setup.spareDiffers && R[1].st.ring->setup.spare && !R[0].st.ring->setup.spare);
    teardown(R);
  }
  printf("setup glue: 4 ranks, every rank the same verdict (match, 42, 44 path, 44 thresholds), one setup line per rank, "
         "the fork flag (43 at Resume, not at the setup), the spare's path\n");
}

// ---- 3. the first pairing ----
static bool pairedAll(std::vector<Rank>& R) {
  const int n = (int)R.size();
  for (int i = 0; i < n; i++)
    for (int p = 0; p < n; p++) {
      if (p == i) continue;
      const struct gdakiCtrlRdmaPeer& pr = R[(size_t)i].st.ring->peers[(size_t)p];
      if (!gdakiCtrlRingUp(&pr.ring) || pr.pairRec.state != GDAKI_CTRL_PS_UP || pr.prb.st.state != GDAKI_CTRL_PS_UP)
        return false;
    }
  return true;
}
static void testFirstPairing(int n, int lateRank, double lateMs) {
  std::vector<Rank> R((size_t)n);
  gBoundOf.assign((size_t)n, nullptr);
  for (int i = 0; i < n; i++) rankInit(R[(size_t)i], i, n, 5);
  std::vector<const char*> offs;
  allGatherAgree(R, &offs);
  const uint64_t before0 = gRcRecvBeforeBound, posts0 = gRcRecvPosts, conn0 = gConnectedFirst, notConn0 = gNotConnectedFirst,
                 higher0 = gConnectedFromHigher, rnr0 = gRnr, readErr0 = gReadErr;
  const double t0 = gdakiQ4MonoMs();
  for (int i = 0; i < n; i++) {
    CHECK(offs[(size_t)i] == nullptr && R[(size_t)i].st.ring != nullptr);
    gBoundOf[(size_t)i] = &R[(size_t)i].st.ring->bound;
    R[(size_t)i].ts.peers.resize((size_t)n);
    for (int p = 0; p < n; p++) R[(size_t)i].ts.peers[(size_t)p].gated = p != i;
    R[(size_t)i].r.ts = &R[(size_t)i].ts;
    R[(size_t)i].pageAtMs = t0 + (i == lateRank ? lateMs : 0.0);
  }
  bool ok = false;
  double doneMs = 0;
  while (gdakiQ4MonoMs() - t0 < 5000.0) {
    for (int i = 0; i < n; i++) {
      Rank& k = R[(size_t)i];
      if (k.st.page == nullptr && gdakiQ4MonoMs() >= k.pageAtMs) pageUp(k, n);
      gdakiCtrlRingHelperStep(&k.r);
      watchStep(k);
    }
    if (pairedAll(R)) {
      ok = true;
      doneMs = gdakiQ4MonoMs() - t0;
      break;
    }
    std::this_thread::sleep_for(std::chrono::microseconds(200));
  }
  CHECK(ok);
  const int pairs = n * (n - 1) / 2;
  CHECK(gRcRecvBeforeBound == before0);                                        // nothing posted before the binding
  CHECK(gRcRecvPosts - posts0 >= (uint64_t)(2 * pairs) * GDAKI_CTRL_RING_SLOTS);  // K RECVs at both ends of every pair
  CHECK(gConnectedFirst - conn0 == (uint64_t)pairs && gNotConnectedFirst == notConn0 && gConnectedFromHigher == higher0);
  CHECK(gRnr == rnr0 && gReadErr == readErr0);
  for (int i = 0; i < n; i++) {
    struct gdakiCtrlRing* g = R[(size_t)i].st.ring;
    struct gdakiCtrlPage* pg = R[(size_t)i].st.page;
    CHECK(g->bound && g->pairingStarted);  // 2a-2-B: live comes with the last pair up (testLive checks when)
    CHECK(g->rxConsumed == (uint64_t*)((uint8_t*)pg->page + pg->layout.rxConsumedOff));
    for (int p = 0; p < n; p++) {
      if (p == i) continue;
      const struct gdakiCtrlRdmaPeer& pr = g->peers[(size_t)p];
      CHECK(pr.ring.gen == 1 && pr.pairRec.cur == 1 && pr.prb.st.cur == 1 && pr.ring.initiator == (i < p));
      CHECK(pr.local.psn == pr.q->psn && pr.q->psn <= 0xffffffu && pr.local.qpn == pr.q->qp->qp_num);
      CHECK(pr.pairRec.havePsn && pr.pairRec.lastPsn == pr.q->psn);
      CHECK(gQps.count(pr.remote.qpn) == 1 && gQps[pr.remote.qpn]->rank == p && fqOf(pr.q->qp)->remoteQpn == pr.remote.qpn &&
            pr.remote.qpn == R[(size_t)p].st.ring->peers[(size_t)i].local.qpn &&
            pr.remote.psn == R[(size_t)p].st.ring->peers[(size_t)i].local.psn);
      CHECK(pr.remotePage.rkey == R[(size_t)p].st.page->pageMr->rkey && pr.remoteOutbox.len == GDAKI_CTRL_OUTBOX_BYTES);
      // the page's word for p is the ring's (gen 1)
      CHECK(__atomic_load_n(&g->rxConsumed[p], __ATOMIC_ACQUIRE) == gdakiCtrlRingConsumedWord(&pr.ring));
      CHECK(gdakiCtrlGenOf(g->rxConsumed[p]) == 1);
      bool up = true;
      const bool wasLive = g->live;
      g->live = false;
      CHECK(!gdakiCtrlRdmaLiveUp(&R[(size_t)i].r, p, &up) && up);  // not live: the socket's answer stands
      g->live = true;
      CHECK(gdakiCtrlRdmaLiveUp(&R[(size_t)i].r, p, &up) && up);  // 2a-2-B's answer: the pair's ring is up
      g->live = wasLive;
    }
    CHECK(R[(size_t)i].watchConnects == (uint64_t)(n - 1));  // one CONNECT per peer (the liveness READ QP)
  }
  if (lateRank >= 0) {  // the lower ranks resent their PAIR while the late page was not up
    CHECK(doneMs >= lateMs);
    for (int i = 0; i < lateRank; i++) CHECK(R[(size_t)i].st.ring->peers[(size_t)lateRank].pairRec.pairsSent >= 2);
  }
  // a one-way burst 0 -> 1: rank 1 takes nothing until 0's window is shut, then all; 0 learns the credit from rank 1's
  // page (the consumed word's READ) and the rest goes
  {
    struct gdakiCtrlRing* g0 = R[0].st.ring;
    struct gdakiCtrlRing* g1 = R[1].st.ring;
    const int N = 300;
    for (int s = 0; s < N; s++) {
      struct gdakiTsMsg m;
      memset(&m, 0, sizeof(m));
      m.type = 40;
      m.round = (uint64_t)s;
      m.from = 0;
      CHECK(gdakiCtrlRdmaSend(g0, 1, &m, 1000) == 0);
    }
    for (int k = 0; k < 50; k++) gdakiCtrlRdmaPoll(g0, gdakiQ4MonoMs());
    // the window: K beyond what rank 1 consumed (its CONNECTED, seq 1, taken at the pairing), then shut
    CHECK(g0->peers[1].ring.sent == g0->peers[1].ring.peerConsumed + GDAKI_CTRL_RING_SLOTS && g0->peers[1].ring.peerConsumed == 1);
    const uint64_t reads0 = g0->peers[1].ring.creditReads;
    int got = 0;
    bool order = true;
    const double t1 = gdakiQ4MonoMs();
    while (got < N && gdakiQ4MonoMs() - t1 < 5000.0) {
      struct gdakiTsMsg m;
      char cause[32];
      int r;
      while ((r = gdakiCtrlRdmaRecv(g1, 0, &m, cause, sizeof(cause))) == 1) {
        order = order && m.round == (uint64_t)got && m.magic == GDAKI_TS_MAGIC;
        got++;
      }
      CHECK(r == 0);
      gdakiCtrlRdmaPoll(g0, gdakiQ4MonoMs());
      std::this_thread::sleep_for(std::chrono::microseconds(100));
    }
    CHECK(got == N && order);
    CHECK(g0->peers[1].ring.creditReads > reads0);  // the shut window opened through rank 1's page word
    CHECK(__atomic_load_n(&g1->rxConsumed[0], __ATOMIC_ACQUIRE) == gdakiCtrlRingConsumedWord(&g1->peers[0].ring));
    CHECK(gdakiCtrlCountOf(g1->rxConsumed[0]) == (uint32_t)N + 1u);  // the records and the CONNECTED
    CHECK(gRnr == rnr0 && gReadErr == readErr0);
    printf("pairing (%d ranks%s): %d pairs, both kinds in generation 1 after %.1f ms, CONNECTED first from the lower rank "
           "on every pair, no RECV before the binding, page words = ring words; burst %d records 0 -> 1 in order, %llu "
           "consumed-word READs of rank 1's page\n", n, lateRank >= 0 ? ", one late page" : "", pairs, doneMs, N,
           (unsigned long long)(g0->peers[1].ring.creditReads - reads0));
  }
  teardown(R);
}

// ---- 4. record 55 PROBE_SETUP ----
static void test55() {
  std::vector<Rank> R(3);
  gBoundOf.assign(3, nullptr);
  for (int i = 0; i < 3; i++) rankInit(R[(size_t)i], i, 3, 5);
  std::vector<const char*> offs;
  allGatherAgree(R, &offs);
  pageUp(R[0], 3);
  struct gdakiTsMsg m;
  memset(&m, 0, sizeof(m));
  m.type = GDAKI_TS_CTRL_PROBE_SETUP;
  const size_t l0 = logCount("PROBE_SETUP");
  const uint64_t ud0 = gUdSent, posts0 = gRcRecvPosts;
  const uint32_t st1 = R[0].st.ring->peers[1].prb.st.state, st2 = R[0].st.ring->peers[2].prb.st.state;
  for (int k = 0; k < 3; k++) gdakiCtrlProbeSetupRecv(&R[0].r, 1, m);
  gdakiCtrlProbeSetupRecv(&R[0].r, 2, m);
  CHECK(logCount("PROBE_SETUP") == l0 + 2);  // one line per sender
  CHECK(gUdSent == ud0 && gRcRecvPosts == posts0);  // nothing sent, nothing posted
  CHECK(R[0].st.ring->peers[1].prb.st.state == st1 && R[0].st.ring->peers[2].prb.st.state == st2);
  struct gdakiCtrlPage* pg = R[0].st.page;
  for (int p = 1; p < 3; p++) CHECK(pg->peers[(size_t)p].req.seq == 0);  // no request to the watch thread
  teardown(R);
  printf("record 55: 4 dropped from 2 senders, 2 lines, no datagram, no post, no request\n");
}

// ---- 5. 2a-2-B: the live seams over the fake verbs ----
#include "gc_prep_gen.inc"  // gc_unit_prep.cc's kTypes and fillRandom (the same record generator)
static void sockPair(int sv[2]) {
  CHECK(socketpair(AF_UNIX, SOCK_STREAM, 0, sv) == 0);
  for (int i = 0; i < 2; i++) fcntl(sv[i], F_SETFL, fcntl(sv[i], F_GETFL, 0) | O_NONBLOCK);
}
static void stepAll(std::vector<Rank>& R) {
  for (auto& k : R) {
    gdakiCtrlRingHelperStep(&k.r);
    watchStep(k);
  }
}
static bool allLive(std::vector<Rank>& R) {
  for (auto& k : R)
    if (k.st.ring == nullptr || !k.st.ring->live) return false;
  return true;
}
// n ranks paired and live (the helper's step sets live once both pairings of every peer are up). False: they did not.
static bool bringUp(std::vector<Rank>& R, int n) {
  gBoundOf.assign((size_t)n, nullptr);
  for (int i = 0; i < n; i++) rankInit(R[(size_t)i], i, n, 5);
  std::vector<const char*> offs;
  allGatherAgree(R, &offs);
  for (int i = 0; i < n; i++) {
    R[(size_t)i].ts.peers.resize((size_t)n);
    for (int p = 0; p < n; p++) R[(size_t)i].ts.peers[(size_t)p].gated = p != i;
    R[(size_t)i].r.ts = &R[(size_t)i].ts;
    pageUp(R[(size_t)i], n);
  }
  const double t0 = gdakiQ4MonoMs();
  while (!allLive(R) && gdakiQ4MonoMs() - t0 < 5000.0) {
    stepAll(R);
    std::this_thread::sleep_for(std::chrono::microseconds(100));
  }
  return allLive(R);
}
// Every rank's inbox of every peer read through the seam: records appended to got[i][p], -1 counted in neg[i][p].
struct Rx {
  std::vector<std::vector<std::vector<struct gdakiTsMsg>>> got;
  std::vector<std::vector<int>> neg;
  std::vector<std::vector<std::string>> cause;
};
static void rxInit(Rx& x, int n) {
  x.got.assign((size_t)n, std::vector<std::vector<struct gdakiTsMsg>>((size_t)n));
  x.neg.assign((size_t)n, std::vector<int>((size_t)n, 0));
  x.cause.assign((size_t)n, std::vector<std::string>((size_t)n));
}
static void drainAll(std::vector<Rank>& R, Rx& x) {
  const int n = (int)R.size();
  for (int i = 0; i < n; i++)
    for (int p = 0; p < n; p++) {
      if (p == i) continue;
      struct gdakiTsPeer& pe = R[(size_t)i].ts.peers[(size_t)p];
      struct gdakiTsMsg m;
      int k;
      while ((k = gdakiCtrlPump(&R[(size_t)i].r, p, pe, &m)) != 0) {
        if (k == 1) x.got[(size_t)i][(size_t)p].push_back(m);
        else {
          x.neg[(size_t)i][(size_t)p]++;
          x.cause[(size_t)i][(size_t)p] = pe.closeCause;
        }
      }
    }
}
static struct gdakiTsMsg recOf(uint32_t type, int from, uint64_t round) {
  struct gdakiTsMsg m;
  memset(&m, 0, sizeof(m));
  m.type = type;
  m.from = from;
  m.round = round;
  return m;
}
static size_t countSendDeferredTotal(std::vector<Rank>& R) {
  size_t d = 0;
  for (auto& k : R)
    for (const auto& pr : k.st.ring->peers) d += pr.deferred;
  return d;
}

static void testLive(int n) {
  std::vector<Rank> R((size_t)n);
  const size_t live0 = logCount("the records go on the ring from now (live)");
  // before live: the swap points take the TCP back end and count its bytes
  gBoundOf.assign((size_t)n, nullptr);
  for (int i = 0; i < n; i++) rankInit(R[(size_t)i], i, n, 5);
  {
    std::vector<const char*> offs;
    allGatherAgree(R, &offs);
    for (int i = 0; i < n; i++) {
      R[(size_t)i].ts.peers.resize((size_t)n);
      for (int p = 0; p < n; p++) R[(size_t)i].ts.peers[(size_t)p].gated = p != i;
      R[(size_t)i].r.ts = &R[(size_t)i].ts;
    }
    int sv[2];
    sockPair(sv);
    struct gdakiTsPeer& pe10 = R[1].ts.peers[0];
    struct gdakiTsPeer& pe01 = R[0].ts.peers[1];
    pe01.fd = sv[0];
    pe10.fd = sv[1];
    struct gdakiTsMsg m = recOf(GDAKI_TS_REQ, 0, 1), in;
    CHECK(gdakiCtrlPollFd(&R[0].r, 1, pe01) == sv[0] && gdakiCtrlChanUp(&R[0].r, 1, pe01));  // the socket's answers
    CHECK(gdakiCtrlSend(&R[0].r, 1, GDAKI_CTRL_CH_RECORD, pe01.fd, &m, 100) == 0);
    CHECK(gdakiCtrlRecv(&R[1].r, 0, pe10, &in, 200, nullptr) == 1 && in.type == GDAKI_TS_REQ && in.magic == GDAKI_TS_MAGIC);
    CHECK(R[0].r.ctrlTcp.recordBytes.load() == sizeof(m) && R[1].r.ctrlTcp.rxPeer[0].load() == sizeof(m));
    close(sv[0]);
    close(sv[1]);
    pe01.fd = pe10.fd = -1;
    for (int i = 0; i < n; i++) pageUp(R[(size_t)i], n);
    const double t0 = gdakiQ4MonoMs();
    while (!allLive(R) && gdakiQ4MonoMs() - t0 < 5000.0) {
      stepAll(R);
      std::this_thread::sleep_for(std::chrono::microseconds(100));
    }
  }
  CHECK(allLive(R));
  CHECK(logCount("the records go on the ring from now (live)") == live0 + (size_t)n);  // one line per rank
  for (int i = 0; i < n; i++) {
    gBoundOf[(size_t)i] = nullptr;
    for (int p = 0; p < n; p++) {
      if (p == i) continue;
      struct gdakiTsPeer& pe = R[(size_t)i].ts.peers[(size_t)p];
      pe.fd = 77;  // a witness socket's number: the record channel's answers no longer look at it
      CHECK(gdakiCtrlPollFd(&R[(size_t)i].r, p, pe) == -1 && gdakiCtrlChanUp(&R[(size_t)i].r, p, pe));
      CHECK(gdakiCtrlChanGen(&R[(size_t)i].r, p, pe) == 1);
      pe.fd = -1;
      pe.gone = true;  // the witness's state does not move the record channel
      CHECK(gdakiCtrlChanUp(&R[(size_t)i].r, p, pe));
      pe.gone = false;
    }
  }
  // records both ways on every pair through the seams (fd -1: a TCP fall-back would fail), and the same records over a
  // socket through ln4's gdakiTsSend and gdakiTsPump: the delivered streams are equal byte for byte
  Rx x;
  rxInit(x, n);
  const int K = 150;
  std::vector<std::vector<std::vector<struct gdakiTsMsg>>> sent((size_t)n, std::vector<std::vector<struct gdakiTsMsg>>((size_t)n));
  std::mt19937_64 rng(0x2a2bull + (uint64_t)n);
  const uint64_t rnr0 = gRnr, tcpRec0 = R[0].r.ctrlTcp.recordBytes.load();
  for (int k = 0; k < K; k++)
    for (int i = 0; i < n; i++)
      for (int j = 0; j < n; j++) {
        if (i == j) continue;
        struct gdakiTsMsg m;
        fillRandom(&m, rng, kTypes[rng() % (sizeof(kTypes) / sizeof(kTypes[0]))]);
        CHECK(gdakiCtrlSend(&R[(size_t)i].r, j, GDAKI_CTRL_CH_RECORD, -1, &m, 1000) == 0);
        sent[(size_t)i][(size_t)j].push_back(m);  // as stamped by the seam (gdakiTsSend's contract)
      }
  {
    const double t0 = gdakiQ4MonoMs();
    bool done = false;
    while (!done && gdakiQ4MonoMs() - t0 < 5000.0) {
      drainAll(R, x);
      done = true;
      for (int i = 0; i < n; i++)
        for (int j = 0; j < n; j++)
          if (i != j && x.got[(size_t)j][(size_t)i].size() < (size_t)K) done = false;
    }
    CHECK(done);
  }
  bool same = true, magic = true;
  int sv[2];
  sockPair(sv);
  struct gdakiTsPeer rd;
  rd.fd = sv[1];
  for (int i = 0; i < n; i++)
    for (int j = 0; j < n; j++) {
      if (i == j) continue;
      const auto& g = x.got[(size_t)j][(size_t)i];
      CHECK(g.size() == (size_t)K && x.neg[(size_t)j][(size_t)i] == 0);
      for (size_t k = 0; k < g.size() && k < (size_t)K; k++) {
        struct gdakiTsMsg t = sent[(size_t)i][(size_t)j][k], o;
        t.magic = 0;  // gdakiTsSend stamps it as the seam did
        same = same && gdakiTsSend(sv[0], &t, 1000) == 0;
        int r = 0;
        for (int w = 0; w < 1000 && (r = gdakiTsPump(rd, &o)) == 0; w++) std::this_thread::sleep_for(std::chrono::microseconds(10));
        same = same && r == 1 && memcmp(&o, &g[k], sizeof(o)) == 0 && memcmp(&o, &sent[(size_t)i][(size_t)j][k], sizeof(o)) == 0;
        magic = magic && g[k].magic == GDAKI_TS_MAGIC;
      }
      const struct gdakiCtrlRdmaPeer& pr = R[(size_t)i].st.ring->peers[(size_t)j];
      CHECK(pr.txRecords == (uint64_t)K && R[(size_t)j].st.ring->peers[(size_t)i].rxRecords == (uint64_t)K);
    }
  close(sv[0]);
  close(sv[1]);
  CHECK(same && magic);
  CHECK(gRnr == rnr0 && R[0].r.ctrlTcp.recordBytes.load() == tcpRec0);  // no RNR, no TCP byte while live
  // gdakiCtrlRecv: gdakiTsRecv's timeout semantics on the ring
  {
    struct gdakiTsPeer& pe = R[0].ts.peers[1];
    struct gdakiTsMsg m;
    double t0 = gdakiQ4MonoMs();
    CHECK(gdakiCtrlRecv(&R[0].r, 1, pe, &m, 30, nullptr) == 0);
    const double el = gdakiQ4MonoMs() - t0;
    CHECK(el >= 29.0 && el < 200.0);
    std::atomic<bool> stop(true);
    t0 = gdakiQ4MonoMs();
    CHECK(gdakiCtrlRecv(&R[0].r, 1, pe, &m, 1000, &stop) == 0 && gdakiQ4MonoMs() - t0 < 50.0);
    struct gdakiTsMsg s = recOf(GDAKI_TS_DONE, 1, 9);
    CHECK(gdakiCtrlSend(&R[1].r, 0, GDAKI_CTRL_CH_RECORD, -1, &s, 100) == 0);
    CHECK(gdakiCtrlRecv(&R[0].r, 1, pe, &m, 1000, nullptr) == 1 && m.type == GDAKI_TS_DONE && m.round == 9);
    s = recOf(GDAKI_TS_DONE, 1, 10);
    CHECK(gdakiCtrlSend(&R[1].r, 0, GDAKI_CTRL_CH_RECORD, -1, &s, 100) == 0);
    CHECK(gdakiCtrlRecvOn(&R[0].r, 1, GDAKI_CTRL_CH_RECORD, -1, &m, 1000, nullptr) == 1 && m.round == 10);
    CHECK(gdakiCtrlRecvOn(&R[0].r, 1, GDAKI_CTRL_CH_REJOIN, -1, &m, 10, nullptr) == -1);  // REJOIN: TCP until 2a-2-C
    int dv[2];
    sockPair(dv);
    const uint64_t d0 = R[0].r.ctrlTcp.dataBytes.load();
    CHECK(gdakiCtrlSend(&R[0].r, 1, GDAKI_CTRL_CH_DATA, dv[0], &s, 100) == 0 && R[0].r.ctrlTcp.dataBytes.load() == d0 + sizeof(s));
    close(dv[0]);
    close(dv[1]);
  }
  // a generation change inside a round: rank 0 (the initiator) sent its REQ, the responder q took it, then q's record QP
  // to 0 goes to ERR (as the hold start's RecordToErr, or QP_ERR): q re-pairs (PAIR(record, gen 2) from q), rank 0's ACK
  // wait ends with -1 exactly once (QP:NEWGEN: a pairing the peer started), q's pump with -1 once (QP:TOERR); the
  // round is cancelled as gdakiTsCancelRound does (the witness reset nothing), retried after the re-pairing and ends
  const int q = n - 1;
  {
    rxInit(x, n);
    const size_t pair0 = logCount("PAIR(record, gen 2) to rank 0 (local ERR)"), rep0 = logCount("re-paired (gen 2)");
    struct gdakiTsMsg req = recOf(GDAKI_TS_REQ, 0, 77), m;
    CHECK(gdakiCtrlSend(&R[0].r, q, GDAKI_CTRL_CH_RECORD, -1, &req, 100) == 0);
    struct gdakiTsPeer& peq = R[(size_t)q].ts.peers[0];
    CHECK(gdakiCtrlRecv(&R[(size_t)q].r, 0, peq, &m, 1000, nullptr) == 1 && m.type == GDAKI_TS_REQ && m.round == 77);
    gdakiCtrlRdmaRecordToErrAsk(&R[(size_t)q].r, 0);
    int wsv[2];
    sockPair(wsv);
    struct gdakiTsPeer& pe0 = R[0].ts.peers[(size_t)q];
    pe0.fd = wsv[0];  // the witness socket of the pair: its state must survive the cancel
    int neg0 = 0, negq = 0, acks = 0, reqs = 0, other = 0;
    bool cancelled = false, retried = false;
    std::string c0, cq;
    const double t0 = gdakiQ4MonoMs();
    while (gdakiQ4MonoMs() - t0 < 4000.0 && acks == 0) {
      stepAll(R);
      // traffic on the other pairs meanwhile (n = 4: 1 <-> 2)
      if (n == 4) {
        struct gdakiTsMsg o = recOf(48, 1, 1);
        (void)gdakiCtrlSend(&R[1].r, 2, GDAKI_CTRL_CH_RECORD, -1, &o, 10);
        while (gdakiCtrlPump(&R[2].r, 1, R[2].ts.peers[1], &o) == 1) other++;
        CHECK(gdakiCtrlPump(&R[2].r, 1, R[2].ts.peers[1], &o) >= 0);
      }
      int k = gdakiCtrlRecv(&R[0].r, q, pe0, &m, 2, nullptr);
      if (k < 0) {
        neg0++;
        c0 = pe0.closeCause;
        // gdakiTsCancelRound's witness steps: the cause, MakeUnknown, its liveness class
        snprintf(pe0.lostCause, sizeof(pe0.lostCause), "%s", pe0.closeCause);
        gdakiTsMakeUnknown(pe0);
        CHECK(pe0.fd == wsv[0] && !pe0.unknown && fcntl(wsv[0], F_GETFD) >= 0);  // the witness untouched
        CHECK(gdakiTsCauseLiveness(pe0.closeCause) == GDAKI_TS_LV_UNKNOWN);    // never an exit
        cancelled = true;
      } else if (k == 1) {
        if (m.type == GDAKI_TS_ACK && m.round == 77 && retried) acks++;
      }
      if (cancelled && !retried && gdakiCtrlChanUp(&R[0].r, q, pe0)) {  // the retry after the re-pairing
        req = recOf(GDAKI_TS_REQ, 0, 77);
        CHECK(gdakiCtrlSend(&R[0].r, q, GDAKI_CTRL_CH_RECORD, -1, &req, 100) == 0);
        retried = true;
      }
      while ((k = gdakiCtrlPump(&R[(size_t)q].r, 0, peq, &m)) != 0) {
        if (k < 0) {
          negq++;
          cq = peq.closeCause;
        } else if (m.type == GDAKI_TS_REQ && m.round == 77) {
          reqs++;
          struct gdakiTsMsg a = recOf(GDAKI_TS_ACK, q, 77);
          CHECK(gdakiCtrlSend(&R[(size_t)q].r, 0, GDAKI_CTRL_CH_RECORD, -1, &a, 100) == 0);
        }
      }
    }
    CHECK(cancelled && retried && acks == 1 && reqs == 1);  // the first REQ was taken once, in gen 1; the retry once
    // q's own -1 names its loss (QP:TOERR) when its pump runs before its re-pairing, else the new generation (QP:NEWGEN):
    // once either way, and a record QP's cause
    CHECK(neg0 == 1 && negq == 1 && c0 == "QP:NEWGEN" && (cq == "QP:TOERR" || cq == "QP:NEWGEN"));
    CHECK(R[0].st.ring->peers[(size_t)q].ring.gen == 2 && R[(size_t)q].st.ring->peers[0].ring.gen == 2);
    CHECK(logCount("PAIR(record, gen 2) to rank 0 (local ERR)") == pair0 + 1);  // q started it
    CHECK(logCount("re-paired (gen 2)") >= rep0 + 2);  // both ends of (0, q)
    CHECK(R[0].st.ring->peers[(size_t)q].repairs == 1 && R[(size_t)q].st.ring->peers[0].repairs == 1);
    if (n == 4) CHECK(other > 0 && R[2].st.ring->peers[1].lossEvents == 0 && R[2].st.ring->peers[1].ring.gen == 1);
    // the negative control: a socket cause resets the witness as ln4 does
    snprintf(pe0.lostCause, sizeof(pe0.lostCause), "ECONNRESET");
    gdakiTsMakeUnknown(pe0);
    CHECK(pe0.fd == -1 && pe0.unknown && gdakiTsCauseLiveness("FIN") == GDAKI_TS_LV_DEAD &&
          gdakiTsCauseLiveness("ECONNRESET") == GDAKI_TS_LV_UNKNOWN && gdakiTsCauseLiveness("QP:SENDERR") == GDAKI_TS_LV_UNKNOWN);
    pe0.unknown = false;
    close(wsv[1]);
  }
  // the witness's socket while the ring is live: BYE, a late record, FIN; the pump reads the ring only
  {
    int wsv[2];
    sockPair(wsv);
    struct gdakiTsPeer& pe = R[1].ts.peers[0];
    pe.fd = wsv[0];
    const size_t bye0 = logCount("rank 0 left the communicator (BYE)");
    struct gdakiTsMsg b = recOf(GDAKI_TS_BYE, 0, 0), m;
    CHECK(gdakiTsSend(wsv[1], &b, 100) == 0);
    struct gdakiTsMsg late = recOf(GDAKI_TS_REQ, 0, 5);
    CHECK(gdakiTsSend(wsv[1], &late, 100) == 0);
    CHECK(gdakiCtrlPump(&R[1].r, 0, pe, &m) == 0 && pe.have == 0);  // the ring's inbox, not the socket
    const uint64_t late0 = R[1].r.ctrlTcp.lateRecords.load();
    CHECK(gdakiCtrlWitnessPump(&R[1].r, 0, pe, &m) == 1 && pe.left && m.type == GDAKI_TS_REQ && m.round == 5);
    CHECK(logCount("rank 0 left the communicator (BYE)") == bye0 + 1 && R[1].r.ctrlTcp.lateRecords.load() == late0 + 1);
    CHECK(gdakiCtrlWitnessPump(&R[1].r, 0, pe, &m) == 0);
    close(wsv[1]);
    CHECK(gdakiCtrlWitnessPump(&R[1].r, 0, pe, &m) == -1 && strcmp(pe.closeCause, "FIN") == 0);
    struct gdakiTsMsg s = recOf(48, 0, 3);
    CHECK(gdakiCtrlSend(&R[0].r, 1, GDAKI_CTRL_CH_RECORD, -1, &s, 100) == 0);  // the ring still carries the records
    CHECK(gdakiCtrlRecv(&R[1].r, 0, pe, &m, 1000, nullptr) == 1 && m.round == 3);
    close(wsv[0]);
    pe.fd = -1;
    pe.left = false;
  }
  // the teardown's lines
  {
    const size_t cs0 = logCount("control summary tcp_record_bytes="), rs0 = logCount(": ring summary peer=");
    for (int i = 0; i < n; i++) gdakiCtrlRingSummary(&R[(size_t)i].r);
    CHECK(logCount("control summary tcp_record_bytes=") == cs0 + (size_t)n);
    CHECK(logCount(": ring summary peer=") == rs0 + (size_t)(n * (n - 1)));
    char want[160];
    snprintf(want, sizeof(want), "GIN/RC: rank %d: control summary tcp_record_bytes=%u tcp_data_bytes=%u tcp_conns=0 "
             "witness_conns=0 records_lost=", 0, (unsigned)sizeof(struct gdakiTsMsg), (unsigned)sizeof(struct gdakiTsMsg));
    CHECK(logCount(want) >= 1);
    const char* keys[] = {" records_dup=", " repairs=", " sendq_deferred=", " sendq_max=", " rnr=0 ", " async=0 ",
                          " active_mtu=5 tcp_rx_bytes_peer", " async_rec=0 async_read=0 async_la=0 ", " live=1 mono_ms="};
    std::string last;
    for (const auto& l : gLog)
      if (l.find("GIN/RC: rank 0: control summary ") != std::string::npos) last = l;
    size_t at = 0;
    for (const char* k : keys) {
      const size_t f = last.find(k, at);
      CHECK(f != std::string::npos);
      if (f != std::string::npos) at = f;
    }
    char rsw[128];
    // to q: the K records, the REQ and its retry (and with 2 ranks the witness scene's record)
    snprintf(rsw, sizeof(rsw), "GIN/RC: rank 0: ring summary peer=%d gen=2 sent=%d received=", q, K + 2 + (q == 1 ? 1 : 0));
    CHECK(logCount(rsw) == 1);
  }
  printf("live (%d ranks): live on every rank after the pairings (one line each), the TCP branch counted before; %d records "
         "each way on %d pairs through the seams, byte for byte ln4's TCP stream; gdakiCtrlRecv's timeout, stop and "
         "record; a generation change in a round: one -1 each side (QP:NEWGEN, QP:TOERR), the witness untouched, cancel "
         "and retry; the witness's BYE, late record and FIN; the summary lines\n", n, K, n * (n - 1) / 2);
  teardown(R);
}

// ---- 6. the three test switches ----
static void testSwitches() {
  // QP_ERR=<ms>:<peer>: rank 0's record QP to rank 1 into ERR 40 ms after the origin (live, armed); rank 1 refuses the
  // same value (its own rank) with one WARN
  {
    setenv(GDAKI_CTRL_T_QP_ERR, "40:1", 1);
    std::vector<Rank> R(2);
    const size_t sw0 = logCount("test switch QP_ERR: record QP to rank 1 moved to ERR"),
                 off0 = logCount("test switch QP_ERR=40:1 is not <ms>:<peer>"),
                 pair0 = logCount("rank 0: PAIR(record, gen 2) to rank 1 (local ERR)");
    CHECK(bringUp(R, 2));
    const double t0 = gdakiQ4MonoMs();
    Rx x;
    rxInit(x, 2);
    while (gdakiQ4MonoMs() - t0 < 3000.0 &&
           !(R[0].st.ring->peers[1].ring.gen == 2 && gdakiCtrlRingUp(&R[0].st.ring->peers[1].ring) &&
             gdakiCtrlRingUp(&R[1].st.ring->peers[0].ring) && x.neg[0][1] == 1 && x.neg[1][0] == 1)) {
      stepAll(R);
      drainAll(R, x);
      std::this_thread::sleep_for(std::chrono::microseconds(200));
    }
    const double el = gdakiQ4MonoMs() - t0;
    CHECK(logCount("test switch QP_ERR: record QP to rank 1 moved to ERR") == sw0 + 1 && el >= 40.0);
    CHECK(logCount("test switch QP_ERR=40:1 is not <ms>:<peer>") == off0 + 1);
    CHECK(logCount("rank 0: PAIR(record, gen 2) to rank 1 (local ERR)") == pair0 + 1);
    CHECK(x.neg[0][1] == 1 && x.cause[0][1] == "QP:TOERR" && x.neg[1][0] == 1 && x.cause[1][0] == "QP:NEWGEN");
    for (int k = 0; k < 50; k++) {
      stepAll(R);
      drainAll(R, x);
    }
    CHECK(x.neg[0][1] == 1 && x.neg[1][0] == 1);  // still once
    struct gdakiTsMsg m = recOf(48, 0, 1);
    CHECK(gdakiCtrlSend(&R[0].r, 1, GDAKI_CTRL_CH_RECORD, -1, &m, 100) == 0);
    CHECK(gdakiCtrlRecv(&R[1].r, 0, R[1].ts.peers[0], &m, 1000, nullptr) == 1 && m.round == 1);
    unsetenv(GDAKI_CTRL_T_QP_ERR);
    teardown(R);
  }
  // CREDIT_STALL=<start>:<len>: no RECV posted again for 300 ms from the origin: rank 0's window shuts, its queue holds
  // the rest (deferred sends), no RNR; after the stall every record arrives in order
  {
    setenv(GDAKI_CTRL_T_CREDIT_STALL, "0:300", 1);
    std::vector<Rank> R(2);
    const size_t sw0 = logCount("test switch CREDIT_STALL: no RECV re-posted for 300 ms");
    CHECK(bringUp(R, 2));
    stepAll(R);  // the origin and the stall's first line
    const uint64_t rnr0 = gRnr;
    const int N = 200;
    const double t0 = gdakiQ4MonoMs();
    for (int s = 0; s < N; s++) {
      struct gdakiTsMsg m = recOf(48, 0, (uint64_t)s);
      CHECK(gdakiCtrlSend(&R[0].r, 1, GDAKI_CTRL_CH_RECORD, -1, &m, 100) == 0);
    }
    Rx x;
    rxInit(x, 2);
    size_t during = 0;
    while (gdakiQ4MonoMs() - t0 < 3000.0 && x.got[1][0].size() < (size_t)N) {
      stepAll(R);
      drainAll(R, x);
      if (gdakiQ4MonoMs() - t0 < 250.0) during = x.got[1][0].size();
      std::this_thread::sleep_for(std::chrono::microseconds(200));
    }
    bool order = x.got[1][0].size() == (size_t)N;
    for (size_t k = 0; order && k < x.got[1][0].size(); k++) order = x.got[1][0][k].round == k;
    CHECK(order && during == 0 && gRnr == rnr0);
    CHECK(logCount("test switch CREDIT_STALL: no RECV re-posted for 300 ms") == sw0 + 2);  // each rank's own RECVs
    CHECK(R[0].st.ring->peers[1].deferred > 0 && R[0].st.ring->sendqMax >= (size_t)(N - (int)GDAKI_CTRL_RING_SLOTS));
    CHECK(countSendDeferredTotal(R) == R[0].st.ring->peers[1].deferred && R[1].st.ring->held.empty());
    unsetenv(GDAKI_CTRL_T_CREDIT_STALL);
    teardown(R);
  }
  // DROP_UD=rejoin:<n>: the first two REJOIN datagrams are dropped (one line each), the third goes, a REJOIN_ACK goes
  {
    setenv(GDAKI_CTRL_T_DROP_UD, "rejoin:2", 1);
    std::vector<Rank> R(2);
    const size_t sw0 = logCount("test switch DROP_UD: the REJOIN datagram to rank 1 dropped");
    CHECK(bringUp(R, 2));
    struct gdakiCtrlRing* g0 = R[0].st.ring;
    struct gdakiTsMsg j = recOf(GDAKI_TS_RS_REJOIN, 0, 1);
    j.magic = GDAKI_TS_MAGIC;
    const uint64_t ud0 = gUdSent;
    const size_t in0 = R[1].st.ring->udIn.size();
    for (int k = 0; k < 3; k++) CHECK(gdakiCtrlRdmaUdSend(g0, 1, GDAKI_CTRL_K_RECORD, 0, &j, (uint32_t)sizeof(j)) == 0);
    CHECK(gUdSent == ud0 + 1 && logCount("test switch DROP_UD: the REJOIN datagram to rank 1 dropped") == sw0 + 2);
    struct gdakiTsMsg a = recOf(GDAKI_TS_RS_REJOIN_ACK, 0, 1);
    CHECK(gdakiCtrlRdmaUdSend(g0, 1, GDAKI_CTRL_K_RECORD, 0, &a, (uint32_t)sizeof(a)) == 0 && gUdSent == ud0 + 2);
    for (int k = 0; k < 5; k++) stepAll(R);
    CHECK(R[1].st.ring->udIn.size() == in0 + 2);
    unsetenv(GDAKI_CTRL_T_DROP_UD);
    teardown(R);
  }
  // malformed values: one WARN each, the switch off
  {
    setenv(GDAKI_CTRL_T_QP_ERR, "soon", 1);
    setenv(GDAKI_CTRL_T_CREDIT_STALL, "5", 1);
    setenv(GDAKI_CTRL_T_DROP_UD, "all", 1);
    std::vector<Rank> R(2);
    const size_t w0 = logCount("test switch QP_ERR=soon is not"), w1 = logCount("test switch CREDIT_STALL=5 is not"),
                 w2 = logCount("test switch DROP_UD=all is not");
    CHECK(bringUp(R, 2));
    stepAll(R);
    CHECK(logCount("test switch QP_ERR=soon is not") == w0 + 2 && logCount("test switch CREDIT_STALL=5 is not") == w1 + 2 &&
          logCount("test switch DROP_UD=all is not") == w2 + 2);
    CHECK(R[0].st.ring->sw.qpErrAtMs < 0 && R[0].st.ring->sw.stallFromMs < 0 && R[0].st.ring->sw.dropUdLeft == 0);
    unsetenv(GDAKI_CTRL_T_QP_ERR);
    unsetenv(GDAKI_CTRL_T_CREDIT_STALL);
    unsetenv(GDAKI_CTRL_T_DROP_UD);
    teardown(R);
  }
  printf("switches: QP_ERR (one line, the re-pairing from the switched side, one -1 each side), CREDIT_STALL (no record "
         "in the stall, the window shut and the queue deferred, no RNR, all in order after it), DROP_UD (two REJOIN "
         "datagrams dropped, the third and a REJOIN_ACK sent), malformed values off with a WARN\n");
}
#endif  // !NCCL_GIN_CTRL_TCP

#if !NCCL_GIN_CTRL_TCP
// ---- 7. int2: the launchers' record QPs ----
static void testLaunchers() {
  const int n = 2;
  std::vector<Rank> R((size_t)n);
  gBoundOf.assign((size_t)n, nullptr);
  for (int i = 0; i < n; i++) rankInit(R[(size_t)i], i, n, 5);
  std::vector<const char*> offs;
  allGatherAgree(R, &offs);
  struct gdakiCtrlRing* g = R[0].st.ring;
  CHECK(g != nullptr && offs[0] == nullptr);
  if (g == nullptr) return;
  const size_t ahs0 = gAhs.size(), mrs0 = gMrs.size();
  CHECK(g->layout.nLaunchers == 0 && gdakiCtrlRingLaunchersOf(&R[0].r) == 0);
  CHECK(gdakiCtrlRingLaunchers(g, 1) && g->la.size() == 1 && g->layout.nLaunchers == 1 &&
        g->layout.staleMsOff == g->layout.rxConsumedLOff + 8u && gdakiCtrlRingLaunchersOf(&R[0].r) == 1);
  CHECK(gdakiCtrlRingLaunchers(g, 1) && g->la.size() == 1);  // again: the same
  // 40 launchers: the layout takes 16; with them the helper's CQ would overrun: no launcher QP (a WARN), the words stay
  const size_t ov0 = logCount("launchers overrun the helper's CQ");
  CHECK(gdakiCtrlRingLaunchers(R[1].st.ring, 40) && R[1].st.ring->nLaunchers == 16 && R[1].st.ring->la.empty() &&
        R[1].st.ring->layout.nLaunchers == 16 && logCount("launchers overrun the helper's CQ") == ov0 + 1);
  CHECK(!gdakiCtrlRingLaunchers(nullptr, 1));
  struct gdakiCtrlEndpoint local;
  CHECK(gdakiCtrlRdmaLaCreate(g, 0, 1, &local) != 0);  // not bound yet: no launcher QP
  // the page with the launcher's word (layout (2, 1)), bound by the helper's step
  R[0].ts.peers.resize((size_t)n);
  R[0].r.ts = &R[0].ts;
  pageUp(R[0], n);
  CHECK(gdakiCtrlPageLayoutOf((uint32_t)n, 1, &R[0].st.page->layout));
  gdakiCtrlRingHelperStep(&R[0].r);
  CHECK(g->bound);
  CHECK(gdakiCtrlRdmaLaCreate(g, 1, 1, &local) != 0 && gdakiCtrlRdmaLaSend(g, -1, nullptr) != 0);  // no such launcher
  // the fake launcher: its CQ, its record QP with 64 RECVs, its UD QP
  Rank L;
  rankInit(L, 9, n, 5);
  struct gdakiCtrlCq* lcq = nullptr;
  CHECK(gdakiCtrlCqCreate(&L.r, 1024, false, &lcq, nullptr, 0) == ncclSuccess);
  struct gdakiMiHostQp *lq = nullptr, *lud = nullptr;
  struct gdakiMiQpEndpoint lv1, luv1;
  char why[128] = {0};
  CHECK(gdakiMiHostQpCreate(&L.r, 1, &lq, &lv1, why, sizeof(why), gdakiCtrlQpAttrRecord(14, lcq->cq)) == ncclSuccess);
  CHECK(gdakiMiHostQpCreate(&L.r, 1, &lud, &luv1, why, sizeof(why), gdakiCtrlQpAttrUd(0x1234567u, lcq->cq)) == ncclSuccess);
  std::vector<uint8_t> lbuf(64u * 512u), lsend(512), lread(65536), lpage(4096, 0);
  struct ibv_mr* lmr = wrap_direct_ibv_reg_mr(&L.pd, lbuf.data(), lbuf.size(), IBV_ACCESS_LOCAL_WRITE);
  struct ibv_mr* rdmr = wrap_direct_ibv_reg_mr(&L.pd, lread.data(), lread.size(), IBV_ACCESS_LOCAL_WRITE);
  struct ibv_mr* pgmr = wrap_direct_ibv_reg_mr(&L.pd, lpage.data(), lpage.size(), IBV_ACCESS_REMOTE_READ);
  auto lrecv = [&](struct gdakiMiHostQp* q, uint32_t s) {
    struct ibv_sge sg;
    sg.addr = (uint64_t)(uintptr_t)(lbuf.data() + (size_t)s * 512u);
    sg.length = 512;
    sg.lkey = lmr->lkey;
    struct ibv_recv_wr wr, *bad = nullptr;
    memset(&wr, 0, sizeof(wr));
    wr.wr_id = s;
    wr.sg_list = &sg;
    wr.num_sge = 1;
    return wrap_ibv_post_recv(q->qp, &wr, &bad) == ncclSuccess;
  };
  auto lsendFrame = [&](struct gdakiMiHostQp* q, uint16_t kind, uint32_t gen, uint64_t seq, uint64_t ack, uint32_t bytes,
                        uint32_t dqpn, uint32_t qkey) {
    std::vector<uint8_t> body(256, 0x5a);
    const uint32_t len = gdakiCtrlFrame(lsend.data(), kind, (int32_t)(GDAKI_CTRL_FROM_LAUNCHER | 7), gen, seq, ack, g->nonce,
                                        0, body.data(), bytes, 0);
    struct ibv_sge sg;
    sg.addr = (uint64_t)(uintptr_t)lsend.data();
    sg.length = len;
    sg.lkey = 0;
    struct ibv_send_wr wr, *bad = nullptr;
    memset(&wr, 0, sizeof(wr));
    wr.wr_id = 0xabc;
    wr.sg_list = &sg;
    wr.num_sge = 1;
    wr.opcode = IBV_WR_SEND;
    wr.wr.ud.remote_qpn = dqpn;
    wr.wr.ud.remote_qkey = qkey;
    return wrap_ibv_post_send(q->qp, &wr, &bad) == ncclSuccess;
  };
  auto lpoll = [&](std::vector<struct ibv_wc>* out) {
    struct ibv_wc wc[64];
    int got = 0;
    while (wrap_ibv_poll_cq(lcq->cq, 64, wc, &got) == ncclSuccess && got > 0)
      for (int k = 0; k < got; k++) out->push_back(wc[k]);
  };
  for (uint32_t s = 0; s < 64; s++) CHECK(lrecv(lq, s));
  CHECK(gdakiCtrlRdmaLaCreate(g, 0, 1, &local) == 0 && local.qpType == GDAKI_CTRL_QPT_RC);
  uint64_t* word = (uint64_t*)((uint8_t*)R[0].st.page->page + R[0].st.page->layout.rxConsumedLOff);
  CHECK(*word == (1ull << 32) && gdakiCtrlRdmaLaWord(g, 0) == word);
  CHECK(gdakiCtrlRdmaLaSend(g, 0, lsend.data()) != 0);  // not connected yet
  CHECK(gdakiCtrlRdmaLaConnect(g, 0, gdakiCtrlEndpointOf(lv1, GDAKI_CTRL_QPT_RC)) == 0);
  CHECK(gdakiMiHostQpConnect(lq, gdakiCtrlEndpointV1(local), why, sizeof(why)) == ncclSuccess);
  // 70 messages: 64 in the launcher's window (32 send slots: the rest after the SEND completions), 6 queued
  for (int i = 0; i < 70; i++) {
    std::vector<uint8_t> m(256, (uint8_t)i);
    CHECK(gdakiCtrlRdmaLaSend(g, 0, m.data()) == 0);
  }
  for (int i = 0; i < 4; i++) gdakiCtrlRdmaPoll(g, gdakiQ4MonoMs());
  struct gdakiCtrlRdmaLa& la = g->la[0];
  CHECK(la.seqOut == 64 && la.pend.size() == 6 && la.queued >= 6 && !la.err);
  std::vector<struct ibv_wc> w;
  lpoll(&w);
  uint64_t seqWant = 1;
  size_t recvs = 0;
  for (const struct ibv_wc& c : w) {
    if (c.opcode != IBV_WC_RECV) continue;
    recvs++;
    struct gdakiCtrlEnv e;
    memcpy(&e, lbuf.data() + (size_t)c.wr_id * 512u, sizeof(e));
    CHECK(c.status == IBV_WC_SUCCESS && c.byte_len == 320 && e.kind == GDAKI_CTRL_K_LAUNCHER && e.from == 0 && e.gen == 1 &&
          e.seq == seqWant && e.ackSeq == 0 && e.nonce == g->nonce && e.bodyBytes == 256 &&
          lbuf[(size_t)c.wr_id * 512u + 64u] == (uint8_t)(seqWant - 1));
    seqWant++;
    CHECK(lrecv(lq, (uint32_t)c.wr_id));
  }
  CHECK(recvs == 64);
  // the launcher's message back: its ackSeq 64 opens the window, the consumed word counts it, the link's queue holds it
  CHECK(lsendFrame(lq, GDAKI_CTRL_K_LAUNCHER, 1, 1, 64, 256, 0, 0));
  for (int i = 0; i < 4; i++) gdakiCtrlRdmaPoll(g, gdakiQ4MonoMs());
  CHECK(la.ackIn == 64 && la.seqIn == 1 && la.seqOut == 70 && la.pend.empty() && *word == ((1ull << 32) | 1u));
  struct gdakiCtrlLaIn x;
  CHECK(gdakiCtrlRdmaLaTake(g, &x) && x.li == 0 && !x.ud && x.env.seq == 1 && x.body[0] == 0x5a);
  CHECK(!gdakiCtrlRdmaLaTake(g, &x));
  w.clear();
  lpoll(&w);
  recvs = 0;
  for (const struct ibv_wc& c : w) {
    if (c.opcode != IBV_WC_RECV) continue;
    recvs++;
    struct gdakiCtrlEnv e;
    memcpy(&e, lbuf.data() + (size_t)c.wr_id * 512u, sizeof(e));
    CHECK(e.seq == seqWant && e.ackSeq == 1);
    seqWant++;
    CHECK(lrecv(lq, (uint32_t)c.wr_id));
  }
  CHECK(recvs == 6 && seqWant == 71);
  // the page's beat: a READ of its first 16 B, at most every 50 ms
  const uint64_t mv = (0x504c5247ull << 32) | (1u << 16) | 2u;  // GL_PAGE_MAGIC, GL_WIRE_VERSION, GL_PAGE_LAYOUT
  memcpy(lpage.data(), &mv, 8);
  uint64_t beat = 1234;
  memcpy(lpage.data() + 8, &beat, 8);
  const uint64_t reads0 = gReads;
  double now = gdakiQ4MonoMs();
  gdakiCtrlRdmaLaBeatAsk(g, 0, (uint64_t)(uintptr_t)lpage.data(), pgmr->rkey, now);
  gdakiCtrlRdmaLaBeatAsk(g, 0, (uint64_t)(uintptr_t)lpage.data(), pgmr->rkey, now);  // in flight: no second
  gdakiCtrlRdmaPoll(g, gdakiQ4MonoMs());
  uint64_t gotMv = 0, gotBeat = 0, nDone = 0;
  CHECK(gdakiCtrlRdmaLaBeatTake(g, 0, &gotMv, &gotBeat, &nDone) && nDone == 1 && gotMv == mv && gotBeat == 1234);
  CHECK(!gdakiCtrlRdmaLaBeatTake(g, 0, &gotMv, &gotBeat, &nDone) && nDone == 0);
  gdakiCtrlRdmaLaBeatAsk(g, 0, (uint64_t)(uintptr_t)lpage.data(), pgmr->rkey, now + 10.0);  // within 50 ms: none
  CHECK(gReads == reads0 + 1);
  gdakiCtrlRdmaLaBeatAsk(g, 0, (uint64_t)(uintptr_t)lpage.data(), pgmr->rkey, now + 60.0);
  CHECK(gReads == reads0 + 2);
  gdakiCtrlRdmaPoll(g, gdakiQ4MonoMs());
  CHECK(gdakiCtrlRdmaLaBeatTake(g, 0, &gotMv, &gotBeat, &nDone) && nDone == 1);
  // datagrams: to the launcher (its Q_Key; a wrong one is lost), from it (the link's queue; a malformed one is bad)
  CHECK(gdakiMiHostQpConnect(lud, luv1, why, sizeof(why)) == ncclSuccess && lrecv(lud, 0));
  const uint64_t drop0 = gUdDropped, bad0 = g->badDgrams;
  std::vector<uint8_t> pm(256, 0x33);
  const struct gdakiCtrlEndpoint lue = gdakiCtrlEndpointOf(luv1, GDAKI_CTRL_QPT_UD);
  CHECK(gdakiCtrlRdmaLaUd(g, 0, lue, 0x1234567u, pm.data()) == 0);
  CHECK(gdakiCtrlRdmaLaUd(g, 0, lue, 0x7654321u, pm.data()) == 0 && gUdDropped == drop0 + 1);
  w.clear();
  lpoll(&w);
  recvs = 0;
  for (const struct ibv_wc& c : w) {
    if (c.opcode != IBV_WC_RECV || c.qp_num != luv1.qpn) continue;
    recvs++;
    struct gdakiCtrlEnv e;
    memcpy(&e, lbuf.data() + GDAKI_CTRL_UD_GRH_BYTES, sizeof(e));
    CHECK(c.byte_len == GDAKI_CTRL_UD_GRH_BYTES + 320 && e.kind == GDAKI_CTRL_K_PAIR && e.from == 0 && e.gen == 0 &&
          e.seq == 0 && e.bodyBytes == 256 && lbuf[GDAKI_CTRL_UD_GRH_BYTES + 64] == 0x33);
  }
  CHECK(recvs == 1 && la.ah != nullptr && gAhs.size() == ahs0 + 1);  // one handle (a changed Q_Key made it again)
  CHECK(lsendFrame(lud, GDAKI_CTRL_K_PAIR, 0, 0, 0, 256, g->udLocal.qpn, g->qkey));
  CHECK(lsendFrame(lud, GDAKI_CTRL_K_PAIR, 0, 0, 0, GDAKI_CTRL_PAIR_BODY_BYTES, g->udLocal.qpn, g->qkey));
  gdakiCtrlRdmaPoll(g, gdakiQ4MonoMs());
  CHECK(gdakiCtrlRdmaLaTake(g, &x) && x.ud && x.li == -1 && (x.env.from & GDAKI_CTRL_FROM_LAUNCHER) != 0);
  CHECK(!gdakiCtrlRdmaLaTake(g, &x) && g->badDgrams == bad0 + 1);
  // the blob slot: the launcher READs it on its record QP; one too big does not fit
  std::vector<uint8_t> blob(3000);
  for (size_t i = 0; i < blob.size(); i++) blob[i] = (uint8_t)(i * 7u);
  struct gdakiCtrlRegion at;
  CHECK(gdakiCtrlRdmaLaBlobPut(g, blob.data(), blob.size(), &at) && at.len == 3000);
  {
    struct ibv_sge sg;
    sg.addr = (uint64_t)(uintptr_t)lread.data();
    sg.length = at.len;
    sg.lkey = rdmr->lkey;
    struct ibv_send_wr wr, *bad = nullptr;
    memset(&wr, 0, sizeof(wr));
    wr.wr_id = 0xb10b;
    wr.sg_list = &sg;
    wr.num_sge = 1;
    wr.opcode = IBV_WR_RDMA_READ;
    wr.wr.rdma.remote_addr = at.addr;
    wr.wr.rdma.rkey = at.rkey;
    CHECK(wrap_ibv_post_send(lq->qp, &wr, &bad) == ncclSuccess);
    w.clear();
    lpoll(&w);
    bool readOk = false;
    for (const struct ibv_wc& c : w)
      if (c.wr_id == 0xb10b) readOk = c.status == IBV_WC_SUCCESS;
    CHECK(readOk && memcmp(lread.data(), blob.data(), blob.size()) == 0);
  }
  std::vector<uint8_t> big(GDAKI_CTRL_LA_BLOB_BYTES + 1u);
  CHECK(!gdakiCtrlRdmaLaBlobPut(g, big.data(), big.size(), &at) && !gdakiCtrlRdmaLaBlobPut(nullptr, blob.data(), 1, &at));
  // a gap in the launcher's sequence (seq 3 after 1): the loss, taken once; nothing is sent after it
  CHECK(!gdakiCtrlRdmaLaErrTake(g, 0));
  CHECK(lsendFrame(lq, GDAKI_CTRL_K_LAUNCHER, 1, 3, 70, 256, 0, 0));
  gdakiCtrlRdmaPoll(g, gdakiQ4MonoMs());
  CHECK(la.err && !la.connected && la.bad == 1 && gdakiCtrlRdmaLaErrTake(g, 0) && !gdakiCtrlRdmaLaErrTake(g, 0));
  CHECK(gdakiCtrlRdmaLaSend(g, 0, pm.data()) != 0);
  CHECK(!gdakiCtrlRdmaLaTake(g, &x));
  // a new generation: a new QP, its counters and word from 0
  CHECK(gdakiCtrlRdmaLaCreate(g, 0, 2, &local) == 0 && la.gen == 2 && la.seqOut == 0 && la.seqIn == 0 && !la.err &&
        *word == (2ull << 32));
  // the fake launcher goes, then the ranks (the ring's destroy takes the launcher QP and its handle)
  (void)wrap_ibv_dereg_mr(lmr);
  (void)wrap_ibv_dereg_mr(rdmr);
  (void)wrap_ibv_dereg_mr(pgmr);
  gdakiMiHostQpDestroy(lq);
  gdakiMiHostQpDestroy(lud);
  CHECK(gdakiCtrlCqDestroy(lcq));
  teardown(R);
  CHECK(gAhs.size() == ahs0 && gMrs.size() <= mrs0);
  printf("launchers: 70 messages through a window of 64, one back, 2 beat READs, datagrams 2 out (1 lost) and 2 in (1 bad), "
         "a 3000 B blob READ, a gap, a second generation\n");
}
#endif  // !NCCL_GIN_CTRL_TCP

int main() {
#if !NCCL_GIN_CTRL_TCP
  testAgreePure();
  testSetupGlue();
  testFirstPairing(2, -1, 0);
  testFirstPairing(4, -1, 0);
  testFirstPairing(4, 3, 700.0);
  test55();
  testLive(2);
  testLive(4);
  testSwitches();
  testLaunchers();
  CHECK(gQps.empty() && gCqs.empty() && gAhs.empty() && gChanFds.empty() && gMrs.empty());  // all destroyed
  printf("fake NIC: %llu UD datagrams (%llu dropped), %llu RC RECVs posted, %llu READs\n", (unsigned long long)gUdSent,
         (unsigned long long)gUdDropped, (unsigned long long)gRcRecvPosts, (unsigned long long)gReads);
  printf("gc_unit_p2a2 (rdma): %ld checks, %ld failed\n", gChecks, gFailed);
#else
  printf("gc_unit_p2a2 (tcp): the ring and its setup are not in the tcp build: %ld checks, %ld failed\n", gChecks, gFailed);
#endif
  return gFailed == 0 ? 0 : 1;
}
