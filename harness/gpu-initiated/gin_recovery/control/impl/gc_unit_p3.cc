// gc_unit_p3.cc - CPU unit test of gin-control's phase 3, the rank side of the launcher (EXPERIMENT.md 9.4, 9.5, 9.8 "CPU
// 단위 모형", launcher): the tree's region "gin-control (launcher): link" (gc_la_link.inc, cut by build_gc_p3.sh) driven
// against the launcher's own state machine (impl/launcher/gin_launcher.c built with -DGL_NO_MAIN, as launcher_unit.cc
// does), with gin-control (ring)'s pairing model (gc_ring_model.inc) and the tree's ctrl API block (gc_api.inc).
//
// The node side is real: each launcher listens on a Unix socket in the working directory; a registered rank is a forked
// child (or this process) that sends its own pidfd by SCM_RIGHTS through the link's code; exits, SIGSTOP and the
// launcher's SIGKILL through the pidfd are real. The RNIC side is a bridge in this file: the launcher's in-process test
// transport (launcher_transport.h) on one end, the link's transport table (struct gdakiCtrlLaTx) on the other; the
// launcher's READ of a buddy's outbox reads this file's buffer. No verbs, no CUDA, no NCCL. g++ with ASan and UBSan.
//
// Scenes (the task's list): registration with a real pidfd of a forked child (CLOEXEC; the connection closed in a
// forked grandchild); LEAVING -> LEFT (the fence word stays); kill -> EXITED -> the word, FENCED line "by EXITED" at the
// hold start, no FENCE sent; SIGSTOP -> FENCE -> SIGKILL -> FENCED and the word, the FENCING, FENCED and window lines;
// FENCE_NAK -> fall back; SPAWN -> REFUSED, a line, never a fallback; activation with LATER then ACCEPTED and the FETCH
// talk through the relay; LATER then 1000 ms -> ABORT and the fallback (the launcher aborts and kills the spare); the
// launcher's beat stale 1000 ms -> its STOP_launcher line and the fallback; arming with and without a noted spare; a
// revived rank pairs with both launchers before it re-arms; the spare's record checks; the Unix socket's loss line.
#include <atomic>
#include <cerrno>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <map>
#include <mutex>
#include <random>
#include <string>
#include <thread>
#include <vector>
#include <algorithm>

#include <fcntl.h>
#include <netinet/in.h>
#include <poll.h>
#include <signal.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/wait.h>
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

namespace ln4 {
#include "gc_ln4_sock.inc"
}
#include "gc_prep_gen.inc"
#include "gc_api.inc"
#include "gc_ring_model.inc"
#include "gin_launcher.h"  // the launcher's state machine and wire (launcher_msg.h), its transport table
#if !NCCL_GIN_CTRL_TCP
#include "gc_la_link.inc"
#endif

static int nChecks = 0, nFail = 0, nScenes = 0;
#define CHECK(c) do { nChecks++; if (!(c)) { nFail++; fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)

#if !NCCL_GIN_CTRL_TCP
static double nowMs() { return gdakiQ4MonoMs(); }
static void msleep(int ms) { usleep((useconds_t)ms * 1000); }

// ------------------------------------------------------------------------------------------------ the bridge
struct Rank;
struct Core {  // one launcher and its test transport
  glTransport tp;
  glCore* c = nullptr;
  uint32_t node = 0;
  std::string sock;
  std::deque<glTpEvent> in;                     // to the launcher
  struct Out { int h; bool ud; glEp to; glMsg m; };
  std::deque<Out> out;                          // from the launcher (delivered after its step)
  int nextHandle = 0;
  std::map<int, int> rankOf;                    // handle -> rank index (record QPs)
  std::map<int, bool> open, connected;
  std::map<int, int> kind;
  struct Read { int h; uint64_t addr; uint32_t rkey, len; void* dst; uint64_t cookie; };
  std::vector<Read> reads;
  int signals = 0;
};
struct Rank {
  gdakiCtrlLaLink k;
  int idx = 0;
  std::vector<std::string> lines;
  std::vector<Core*>* cores = nullptr;          // by launcher index li
  std::map<int, int> hOf;                       // li -> the launcher's handle of this rank's record QP
  std::vector<uint8_t> outbox;                  // the buddy's outbox (the launcher READs the blob from here)
  uint32_t outRkey = 0;
  int rcFail = 0;                               // the next rcSend fails (the QP's error)
  gdakiCtrlLaRelay relayForTest;                // a spare's FETCH relay
};
static std::vector<Rank*> gRanks;
static Core* coreOf(glTransport* tp) { return (Core*)tp->impl; }
static int tFds(glTransport*, int*, int) { return 0; }
static int tPoll(glTransport* tp, glTpEvent* ev, int max) {
  Core* c = coreOf(tp);
  for (const Core::Read& r : c->reads) {  // a READ completes on the next poll
    glTpEvent e;
    memset(&e, 0, sizeof(e));
    e.type = GL_TP_READ_DONE;
    e.peer = r.h;
    e.cookie = r.cookie;
    e.status = 5;
    for (Rank* x : gRanks)
      if (x->outRkey == r.rkey && r.addr >= (uint64_t)(uintptr_t)x->outbox.data() &&
          r.addr + r.len <= (uint64_t)(uintptr_t)x->outbox.data() + x->outbox.size()) {
        memcpy(r.dst, (const void*)(uintptr_t)r.addr, r.len);
        e.status = 0;
      }
    c->in.push_back(e);
  }
  c->reads.clear();
  int k = 0;
  while (k < max && !c->in.empty()) {
    ev[k++] = c->in.front();
    c->in.pop_front();
  }
  return k;
}
static int tLocalUd(glTransport* tp, glEp* ud) {
  memset(ud, 0, sizeof(*ud));
  ud->qpn = 4000 + coreOf(tp)->node;
  ud->psn = 0x1234567;
  ud->version = GL_EP_VERSION;
  ud->qpType = GL_QPT_UD;
  ud->mtu = 5;
  return 0;
}
static int tPage(glTransport*, void* page, size_t len, glRegion* out) {
  out->addr = (uint64_t)(uintptr_t)page;
  out->rkey = 0x9a9e;
  out->len = (uint32_t)len;
  return 0;
}
static int tUdSend(glTransport* tp, const glEp* to, uint32_t, const glMsg* m) {
  Core::Out o;
  o.h = -1;
  o.ud = true;
  o.to = *to;
  o.m = *m;
  coreOf(tp)->out.push_back(o);
  return 0;
}
static int tRcCreate(glTransport* tp, int kind, uint32_t, uint64_t, glEp* local) {
  Core* c = coreOf(tp);
  const int h = c->nextHandle++;
  c->open[h] = true;
  c->kind[h] = kind;
  memset(local, 0, sizeof(*local));
  local->qpn = 5000 + (uint32_t)h;
  local->psn = 0x10000u + (uint32_t)h * 7919u;
  local->version = GL_EP_VERSION;
  local->qpType = GL_QPT_RC;
  local->mtu = 5;
  return h;
}
static int tRcConnect(glTransport* tp, int h, const glEp* remote) {
  Core* c = coreOf(tp);
  if (!c->open[h]) return -1;
  c->connected[h] = true;
  const int ri = (int)(remote->qpn / 1000) - 20;  // a rank's record QP: 20000 + 1000 x rank index + ...
  if (ri >= 0 && ri < (int)gRanks.size()) c->rankOf[h] = ri;
  return 0;
}
static int tRcSend(glTransport* tp, int h, const glMsg* m) {
  Core* c = coreOf(tp);
  if (!c->open[h] || !c->connected[h]) return -1;
  Core::Out o;
  o.h = h;
  o.ud = false;
  o.m = *m;
  c->out.push_back(o);
  return 0;
}
static int tRcRead(glTransport* tp, int h, uint64_t addr, uint32_t rkey, uint32_t len, void* dst, uint64_t cookie) {
  coreOf(tp)->reads.push_back({h, addr, rkey, len, dst, cookie});
  return 0;
}
static void tCredit(glTransport*, int, const glRegion*, uint32_t) {}
static void tRcClose(glTransport* tp, int h) {
  Core* c = coreOf(tp);
  c->open[h] = false;
  for (size_t i = c->reads.size(); i-- > 0;)
    if (c->reads[i].h == h) c->reads.erase(c->reads.begin() + (long)i);
  for (size_t i = c->in.size(); i-- > 0;)
    if (c->in[i].peer == h && c->in[i].type != GL_TP_UD_RECV) c->in.erase(c->in.begin() + (long)i);
}
static void tClose(glTransport*) {}
static const glTransportOps kOps = {tFds, tPoll, tLocalUd, tPage, tUdSend, tRcCreate, tRcConnect, tRcSend, tRcRead,
                                    tCredit, tRcClose, tClose};
// the link's side of the bridge (gdakiCtrlLaTx; arg = the Rank)
static int xUd(void* arg, int li, const glEp* to, uint32_t, const glMsg* m) {
  Rank* x = (Rank*)arg;
  Core* c = (*x->cores)[(size_t)li];
  if (to->qpn != 4000 + c->node) return -1;
  glTpEvent e;
  memset(&e, 0, sizeof(e));
  e.type = GL_TP_UD_RECV;
  e.peer = -1;
  e.msg = *m;
  c->in.push_back(e);
  return 0;
}
static int xCreate(void* arg, int li, uint32_t gen, glEp* local) {
  Rank* x = (Rank*)arg;
  memset(local, 0, sizeof(*local));
  local->qpn = 20000 + 1000u * (uint32_t)x->idx + 100u * (uint32_t)li + (gen & 63u);
  local->psn = 0x300000u + gen * 131u + (uint32_t)li;
  local->version = GL_EP_VERSION;
  local->qpType = GL_QPT_RC;
  local->mtu = 5;
  x->hOf.erase(li);
  return 0;
}
static int xConnect(void* arg, int li, const glEp* remote) {
  Rank* x = (Rank*)arg;
  if (remote->qpn < 5000) return -1;
  const int h = (int)remote->qpn - 5000;
  x->hOf[li] = h;
  (*x->cores)[(size_t)li]->rankOf[h] = x->idx;
  return 0;
}
static int xSend(void* arg, int li, const glMsg* m) {
  Rank* x = (Rank*)arg;
  if (x->rcFail > 0) {
    x->rcFail--;
    return -1;
  }
  auto it = x->hOf.find(li);
  if (it == x->hOf.end()) return -1;
  Core* c = (*x->cores)[(size_t)li];
  if (!c->open[it->second]) return -1;
  glTpEvent e;
  memset(&e, 0, sizeof(e));
  e.type = GL_TP_RC_RECV;
  e.peer = it->second;
  e.msg = *m;
  c->in.push_back(e);
  return 0;
}
static void noteLine(void* arg, const char* line) {
  Rank* x = (Rank*)arg;
  x->lines.push_back(line);
  if (getenv("GC_UNIT_P3_VERBOSE")) printf("  [rank %d] %s\n", x->k.me, line);
}
static bool gLnOk = true;
static bool lnOk(void*, int, uint32_t) { return gLnOk; }
static int nLines(const Rank& x, const char* sub) {
  int n = 0;
  for (const auto& l : x.lines)
    if (l.find(sub) != std::string::npos) n++;
  return n;
}

static Core* mkCore(uint32_t node, const char* dir) {
  Core* c = new Core();
  c->node = node;
  c->tp.ops = &kOps;
  c->tp.impl = c;
  c->sock = std::string(dir) + "/launcher.sock";
  glConfig cfg;
  memset(&cfg, 0, sizeof(cfg));
  cfg.node = node;
  cfg.qkey = 0x1234567;
  cfg.uid = geteuid();
  cfg.graceMs = 200;
  static FILE* logf = nullptr;
  if (!logf) logf = fopen("gc_unit_p3_launcher.log", "a");
  cfg.log = logf;
  cfg.onSignal = [](void* a, pid_t, int, int) { ((Core*)a)->signals++; };
  cfg.onSignalArg = c;
  c->c = gl_core_new(&cfg, &c->tp);
  char why[256] = {0};
  const int rc = gl_core_listen(c->c, c->sock.c_str(), why, sizeof(why));
  if (rc != 0) fprintf(stderr, "listen %s: %s\n", c->sock.c_str(), why);
  CHECK(rc == 0);
  return c;
}
static void rmCore(Core* c) {
  gl_core_shutdown(c->c);
  gl_core_free(c->c);
  delete c;
}
static Rank* mkRank(int idx, int me, int nranks, uint32_t inc, uint64_t nonce, std::vector<Core*>* cores, int nLaunchers) {
  Rank* x = new Rank();
  x->idx = idx;
  x->cores = cores;
  gdakiCtrlLaInit(&x->k, me, nranks, inc, nonce, nLaunchers);
  x->k.ud.qpn = 900 + (uint32_t)idx;
  x->k.ud.version = GL_EP_VERSION;
  x->k.ud.qpType = GL_QPT_UD;
  x->k.ud.mtu = 5;
  x->k.page.addr = 0x7000;
  x->k.page.rkey = 0x500 + (uint32_t)idx;
  x->k.page.len = 4096;
  x->k.creditOff0 = 64 + 8 * (uint32_t)nranks;
  x->k.log.fn = noteLine;
  x->k.log.arg = x;
  x->k.lnOk = lnOk;
  x->k.tx.arg = x;
  x->k.tx.udSend = xUd;
  x->k.tx.rcCreate = xCreate;
  x->k.tx.rcConnect = xConnect;
  x->k.tx.rcSend = xSend;
  x->outbox.assign(4096, 0);
  x->outRkey = 0x0b0 + (uint32_t)idx;
  for (size_t li = 0; li < cores->size(); li++) {
    glEp ud;
    tLocalUd(&(*cores)[li]->tp, &ud);
    const glRegion pg = {(uint64_t)(uintptr_t)gl_core_page((*cores)[li]->c), 0x9a9e, 4096};
    CHECK(gdakiCtrlLaAddLauncher(&x->k, (*cores)[li]->node, ud, 0x1234567, pg) == (int)li);
  }
  gRanks.push_back(x);
  return x;
}
static void rmRanks() {
  for (Rank* x : gRanks) {
    gdakiCtrlLaUnixClose(&x->k.unix);
    delete x;
  }
  gRanks.clear();
}
// One round: every launcher steps, what it sent goes to the ranks, the ranks' pairing clocks tick.
static void pump(std::vector<Core*>& cores, int ms = 0) {
  const double end = nowMs() + ms;
  do {
    for (size_t li = 0; li < cores.size(); li++) {
      Core* c = cores[li];
      gl_core_step(c->c, 1);
      while (!c->out.empty()) {
        const Core::Out o = c->out.front();
        c->out.pop_front();
        for (Rank* x : gRanks) {
          if (o.ud && x->k.ud.qpn == o.to.qpn) gdakiCtrlLaOnUd(&x->k, o.m, nowMs());
          if (!o.ud && c->rankOf.count(o.h) && c->rankOf[o.h] == x->idx) gdakiCtrlLaOnRc(&x->k, (int)li, o.m, nowMs());
        }
      }
    }
    for (Rank* x : gRanks) gdakiCtrlLaPairTick(&x->k, nowMs());
  } while (nowMs() < end);
}
template <class F>
static bool pumpUntil(std::vector<Core*>& cores, F pred, int ms = 3000) {
  const double end = nowMs() + ms;
  while (nowMs() < end) {
    pump(cores);
    if (pred()) return true;
  }
  return pred();
}
// The beat a READ of the launcher page would give (its line 0).
static void feedBeat(Rank* x, std::vector<Core*>& cores) {
  for (size_t li = 0; li < cores.size(); li++) gdakiCtrlLaOnBeat(&x->k, (int)li, gl_core_page(cores[li]->c)->beat, nowMs());
}

// ------------------------------------------------------------------------------------------------ children
// A child runs the link's Unix code against the launcher: REGISTER or SPARE_HELLO with its own pidfd, then commands on
// a pipe: 'l' LEAVING, 'x' exit, 'f' fork a grandchild that reports whether the registering connection is closed in it.
struct Kid {
  pid_t pid = -1;
  int cmd = -1, res = -1;
};
static Kid spawnKid(const char* sock, int role, int32_t rank, uint32_t inc, uint64_t nonce) {
  int c[2], r[2];
  CHECK(pipe(c) == 0 && pipe(r) == 0);
  Kid k;
  k.pid = fork();
  if (k.pid == 0) {
    close(c[1]);
    close(r[0]);
    gdakiCtrlLaUnix u;
    char why[160];
    char res = '0';
    if (gdakiCtrlLaUnixOpen(&u, sock, why, sizeof(why)) && gdakiCtrlLaUnixHello(&u, role, rank, inc, nonce, why, sizeof(why)))
      res = '1';
    const int fdflags = u.fd >= 0 ? fcntl(u.fd, F_GETFD) : 0;
    char cx = (fdflags & FD_CLOEXEC) ? 'c' : 'n';
    if (write(r[1], &res, 1) != 1 || write(r[1], &cx, 1) != 1) _exit(2);
    gdakiCtrlLaLog nolog;
    for (;;) {
      char op = 0;
      struct pollfd pf = {c[0], POLLIN, 0};
      if (poll(&pf, 1, 5) == 1) {
        if (read(c[0], &op, 1) != 1) _exit(0);
      }
      (void)gdakiCtrlLaUnixPoll(&u, nolog, rank);
      if (op == 'a') {  // the HELLO_ACK's status
        const double end = nowMs() + 2000;
        while (!u.acked && nowMs() < end) {
          (void)gdakiCtrlLaUnixPoll(&u, nolog, rank);
          msleep(1);
        }
        const char s = u.acked ? (u.ackStatus == GL_UA_OK ? 'K' : 'R') : '?';
        if (write(r[1], &s, 1) != 1) _exit(2);
      } else if (op == 'l') {
        const char s = gdakiCtrlLaUnixLeaving(&u) ? 'L' : '?';
        if (write(r[1], &s, 1) != 1) _exit(2);
      } else if (op == 'f') {  // the registering connection in a forked grandchild: closed (atfork)
        const int fd = u.fd;
        const pid_t g = fork();
        if (g == 0) _exit(fcntl(fd, F_GETFD) == -1 && errno == EBADF ? 0 : 1);
        int st = 0;
        waitpid(g, &st, 0);
        const char s = WIFEXITED(st) && WEXITSTATUS(st) == 0 ? 'C' : 'O';
        if (write(r[1], &s, 1) != 1) _exit(2);
      } else if (op == 'x') {
        _exit(0);
      }
    }
  }
  close(c[0]);
  close(r[1]);
  k.cmd = c[1];
  k.res = r[0];
  return k;
}
static char kidRes(std::vector<Core*>& cores, Kid& k, int ms = 3000) {
  const double end = nowMs() + ms;
  while (nowMs() < end) {
    pump(cores);
    struct pollfd pf = {k.res, POLLIN, 0};
    if (poll(&pf, 1, 0) == 1) {
      char c = 0;
      if (read(k.res, &c, 1) == 1) return c;
      return 0;
    }
  }
  return 0;
}
static void kidCmd(Kid& k, char op) { CHECK(write(k.cmd, &op, 1) == 1); }
static void reap(Kid& k) {
  if (k.pid > 0) {
    kill(k.pid, SIGKILL);  // our own child (it may be gone already)
    waitpid(k.pid, nullptr, 0);
  }
  if (k.cmd >= 0) close(k.cmd);
  if (k.res >= 0) close(k.res);
  k = Kid();
}
// Register this process as (rank, inc) through the link (its own pidfd): the HELLO_ACK's status.
static bool selfHello(std::vector<Core*>& cores, Rank* x, int li, int role, uint32_t inc) {
  char why[160] = {0};
  if (x->k.unix.fd < 0 && !gdakiCtrlLaUnixOpen(&x->k.unix, cores[(size_t)li]->sock.c_str(), why, sizeof(why))) return false;
  if (!gdakiCtrlLaUnixHello(&x->k.unix, role, x->k.me, inc, x->k.nonce, why, sizeof(why))) return false;
  pumpUntil(cores, [&] {
    (void)gdakiCtrlLaUnixPoll(&x->k.unix, x->k.log, x->k.me);
    return x->k.unix.acked;
  });
  return x->k.unix.acked && x->k.unix.ackStatus == GL_UA_OK;
}

static const uint64_t NONCE = 0x1111222233334444ull;
// a buddy's activation record of (rank, newInc), FENCED carried as the host writes it (gdakiCtrlLaActFencedMark)
static glRsActivate actRecord(int32_t rank, uint32_t newInc, uint64_t step) {
  glRsActivate a;
  memset(&a, 0, sizeof(a));
  a.magic = GL_RS_ACT_MAGIC;
  a.version = 2;
  a.kind = GL_RS_ACT_ACTIVATE;
  a.rank = rank;
  a.incarnation = newInc;
  a.nonce = NONCE;
  a.step = step;
  a.reserved = gdakiCtrlLaActFencedMark(newInc);
  return a;
}
static uint32_t noCells(void*, int, uint32_t* unreadable) {
  *unreadable = 0;
  return 0;
}

// ------------------------------------------------------------------------------------------------ scenes
// Two launchers (node 0 rain, node 1 sunny), four ranks: 0, 1 on node 0, 2, 3 on node 1 (the testbed's layout); rank 2
// is rank 3's buddy (p xor 1). Rank 3's process is a forked child, rank 2 is a link in this process paired with both.
struct World {
  std::vector<Core*> cores;
  Rank* b = nullptr;  // rank 2, the buddy of rank 3
};
static World mkWorld() {
  World w;
  mkdir("gls0", 0700);
  mkdir("gls1", 0700);
  chmod("gls0", 0700);
  chmod("gls1", 0700);
  w.cores.push_back(mkCore(0, "gls0"));
  w.cores.push_back(mkCore(1, "gls1"));
  w.b = mkRank(0, 2, 4, 0, NONCE, &w.cores, 2);
  for (int r = 0; r < 4; r++) gdakiCtrlLaSetRankNode(&w.b->k, r, r < 2 ? 0u : 1u);
  return w;
}
static void rmWorld(World& w) {
  rmRanks();
  for (Core* c : w.cores) rmCore(c);
  w.cores.clear();
}
// The buddy (in this process) registers as rank 2 at node 1 and pairs with both launchers.
static void buddyUp(World& w) {
  CHECK(selfHello(w.cores, w.b, 1, GDAKI_CTRL_LA_ROLE_RANK, 0));
  w.b->k.own = 1;
  CHECK(pumpUntil(w.cores, [&] { return gdakiCtrlLaAllPaired(&w.b->k); }));
  CHECK(nLines(*w.b, "record QP to the launcher of node 0 paired (gen 1)") == 1);
  CHECK(nLines(*w.b, "record QP to the launcher of node 1 paired (gen 1)") == 1);
}

static void sceneRegistration() {
  World w = mkWorld();
  buddyUp(w);
  Kid k = spawnKid(w.cores[1]->sock.c_str(), GDAKI_CTRL_LA_ROLE_RANK, 3, 0, NONCE);
  CHECK(kidRes(w.cores, k) == '1');
  CHECK(kidRes(w.cores, k) == 'c');  // the registering connection is FD_CLOEXEC
  kidCmd(k, 'a');
  CHECK(kidRes(w.cores, k) == 'K');  // the launcher took the child's own pidfd (pid check: SO_PEERCRED = fdinfo Pid:)
  glEntryView v;
  CHECK(gl_core_entry(w.cores[1]->c, NONCE, 3, 1, 0, &v) == 1 && v.pid == k.pid && v.pidfd >= 0);
  kidCmd(k, 'f');
  CHECK(kidRes(w.cores, k) == 'C');  // closed in a forked child (pthread_atfork)
  // the buddy sees rank 3's registration word ALIVE in the REG_NOTE (node 1)
  CHECK(pumpUntil(w.cores, [&] {
    return w.b->k.la[1].haveNote[3] && w.b->k.la[1].note[3].regState == GL_RS_ALIVE && w.b->k.la[1].note[3].regInc == 0;
  }));
  // a REGISTER with a zero nonce is refused by the link itself (a spare HELLO needs one)
  gdakiCtrlLaUnix u;
  char why[160];
  CHECK(!gdakiCtrlLaUnixHello(&u, GDAKI_CTRL_LA_ROLE_SPARE, 3, 1, 0, why, sizeof(why)));
  reap(k);
  rmWorld(w);
  nScenes++;
}

static void sceneLeavingLeft() {
  World w = mkWorld();
  buddyUp(w);
  Kid k = spawnKid(w.cores[1]->sock.c_str(), GDAKI_CTRL_LA_ROLE_RANK, 3, 0, NONCE);
  CHECK(kidRes(w.cores, k) == '1' && kidRes(w.cores, k) == 'c');
  kidCmd(k, 'a');
  CHECK(kidRes(w.cores, k) == 'K');
  kidCmd(k, 'l');
  CHECK(kidRes(w.cores, k) == 'L');
  pump(w.cores, 20);  // the launcher reads LEAVING
  kidCmd(k, 'x');
  waitpid(k.pid, nullptr, 0);
  k.pid = -1;
  uint32_t how = 0;
  CHECK(pumpUntil(w.cores, [&] { return gl_core_tomb(w.cores[1]->c, NONCE, 3, 0, &how) == 1; }));
  CHECK(how == GL_K_LEFT);
  pump(w.cores, 20);
  CHECK(w.b->k.fencedPlus1[3] == GDAKI_CTRL_FENCE_NONE);  // LEFT is a leave, never a fence
  CHECK(w.b->k.la[1].note[3].regState == GL_RS_LEFT);
  reap(k);
  rmWorld(w);
  nScenes++;
}

static void sceneKillExited() {
  World w = mkWorld();
  buddyUp(w);
  Kid k = spawnKid(w.cores[1]->sock.c_str(), GDAKI_CTRL_LA_ROLE_RANK, 3, 0, NONCE);
  CHECK(kidRes(w.cores, k) == '1' && kidRes(w.cores, k) == 'c');
  kidCmd(k, 'a');
  CHECK(kidRes(w.cores, k) == 'K');
  CHECK(w.b->k.fencedPlus1[3] == GDAKI_CTRL_FENCE_NONE);  // right after the setup: no fence
  kill(k.pid, SIGKILL);  // our own child
  waitpid(k.pid, nullptr, 0);
  k.pid = -1;
  CHECK(pumpUntil(w.cores, [&] { return w.b->k.fencedPlus1[3] == gdakiCtrlFenceWord(0); }));
  // the hold start: armed, the word already says FENCED: the FENCED line "by EXITED" now, no FENCE
  gdakiCtrlLaFenceArm(&w.b->k, 3, 0);
  gdakiCtrlLaFenceReport(&w.b->k, 3, true, noCells, nullptr);
  CHECK(gdakiCtrlLaFence(&w.b->k, 3, 0, nowMs(), true) == 1);
  CHECK(!w.b->k.fence[3].sent);
  CHECK(nLines(*w.b, "rank 2: rank 3 (incarnation 0) fence FENCED (by EXITED from node 1)") == 1);
  CHECK(nLines(*w.b, "window check after the judgement of rank 3: changed=0 cells against=snapshot_at_judgement") == 1);
  // an older incarnation's end never fences a newer one: FENCED of 0 does not say 1 is fenced
  CHECK(!gdakiCtrlFencedIs(w.b->k.fencedPlus1[3], 1));
  // a FUTURE or STALE end (the lineage says no) leaves the word
  gLnOk = false;
  glMsg m;
  gdakiCtrlLaMsgInit(&w.b->k, &m, GL_K_EXITED, 1, 7, 0);
  gdakiCtrlLaOnRc(&w.b->k, 0, m, nowMs());
  CHECK(w.b->k.fencedPlus1[1] == GDAKI_CTRL_FENCE_NONE);
  CHECK(nLines(*w.b, "is not this lineage's") == 1);
  gLnOk = true;
  reap(k);
  rmWorld(w);
  nScenes++;
}

static void sceneFenceStopped() {
  World w = mkWorld();
  buddyUp(w);
  Kid k = spawnKid(w.cores[1]->sock.c_str(), GDAKI_CTRL_LA_ROLE_RANK, 3, 0, NONCE);
  CHECK(kidRes(w.cores, k) == '1' && kidRes(w.cores, k) == 'c');
  kidCmd(k, 'a');
  CHECK(kidRes(w.cores, k) == 'K');
  kill(k.pid, SIGSTOP);  // the stalled peer (our own child)
  gdakiCtrlLaFenceArm(&w.b->k, 3, 0);
  CHECK(gdakiCtrlLaFence(&w.b->k, 3, 0, nowMs(), true) == 0);  // FENCE sent: not yet fenced
  CHECK(w.b->k.fence[3].sent);
  CHECK(nLines(*w.b, "rank 2: rank 3 (incarnation 0) fence FENCING: FENCE sent to the launcher of node 1") == 1);
  CHECK(gdakiCtrlLaFence(&w.b->k, 3, 0, nowMs(), true) == 0);  // asked again: no second FENCE
  CHECK(pumpUntil(w.cores, [&] { return gdakiCtrlFencedIs(w.b->k.fencedPlus1[3], 0); }));
  CHECK(w.cores[1]->signals == 1);  // the launcher's SIGKILL through the pidfd, once
  gdakiCtrlLaFenceReport(&w.b->k, 3, true, noCells, nullptr);
  CHECK(gdakiCtrlLaFence(&w.b->k, 3, 0, nowMs(), true) == 1);
  CHECK(nLines(*w.b, "rank 2: rank 3 (incarnation 0) fence FENCED (by FENCED from node 1)") == 1);
  CHECK(nLines(*w.b, "window check after the fence of rank 3: changed=0 cells against=snapshot_at_judgement") == 1);
  int st = 0;
  waitpid(k.pid, &st, 0);
  CHECK(WIFSIGNALED(st) && WTERMSIG(st) == SIGKILL);
  k.pid = -1;
  reap(k);
  rmWorld(w);
  nScenes++;
}

static void sceneFenceNak() {
  World w = mkWorld();
  buddyUp(w);
  gdakiCtrlLaFenceArm(&w.b->k, 3, 0);  // rank 3 never registered at node 1: nothing held there
  CHECK(gdakiCtrlLaFence(&w.b->k, 3, 0, nowMs(), true) == 0);
  CHECK(pumpUntil(w.cores, [&] { return w.b->k.fence[3].nak; }));
  CHECK(gdakiCtrlLaFence(&w.b->k, 3, 0, nowMs(), true) == -1);  // fall back at once
  CHECK(w.cores[1]->signals == 0);
  CHECK(gl_core_stats(w.cores[1]->c)->nFenceNak == 1);
  // no launcher of the peer known: fall back
  w.b->k.laOf[1] = -1;
  CHECK(gdakiCtrlLaFence(&w.b->k, 1, 0, nowMs(), true) == -1);
  rmWorld(w);
  nScenes++;
}

// The activation: rank 3 (a child) is killed; its spare (this process, rank 3 incarnation 1) said HELLO; the buddy's
// ACTIVATE gets LATER once, the spare's READY lets the launcher hand the bytes over, the spare checks the record and
// ACCEPTs, the FETCH talk goes through the relay; SPAWN's REFUSED is a line only. Then the revived rank (this process)
// registers as incarnation 1 and re-arms only after both pairings and a spare of incarnation 2.
static void sceneActivationLaterAccepted() {
  World w = mkWorld();
  buddyUp(w);
  Rank* s = mkRank(1, 3, 4, 1, NONCE, &w.cores, 2);  // the spare's link (this process)
  s->k.pairOk = false;  // a spare does not pair before its activation (the original's pairing stays)
  Kid k = spawnKid(w.cores[1]->sock.c_str(), GDAKI_CTRL_LA_ROLE_RANK, 3, 0, NONCE);
  CHECK(kidRes(w.cores, k) == '1' && kidRes(w.cores, k) == 'c');
  kidCmd(k, 'a');
  CHECK(kidRes(w.cores, k) == 'K');
  CHECK(selfHello(w.cores, s, 1, GDAKI_CTRL_LA_ROLE_SPARE, 1));
  kill(k.pid, SIGKILL);
  waitpid(k.pid, nullptr, 0);
  k.pid = -1;
  CHECK(pumpUntil(w.cores, [&] { return gdakiCtrlFencedIs(w.b->k.fencedPlus1[3], 0); }));
  gdakiCtrlLaFenceArm(&w.b->k, 3, 0);
  gdakiCtrlLaSpawn(&w.b->k, 3, 1);
  CHECK(pumpUntil(w.cores, [&] { return w.b->k.la[1].spawnRefused == 1; }));
  CHECK(nLines(*w.b, "refused SPAWN of rank 3 (incarnation 1): spawn not built; no fallback on it") == 1);
  CHECK(gdakiCtrlLaFence(&w.b->k, 3, 0, nowMs(), true) == 1);
  // the blob in the buddy's outbox
  for (size_t i = 0; i < 3000; i++) w.b->outbox[i] = (uint8_t)(i * 7 + 1);
  const glRegion blob = {(uint64_t)(uintptr_t)w.b->outbox.data(), w.b->outRkey, 3000};
  CHECK(gdakiCtrlLaActStart(&w.b->k, 3, actRecord(3, 1, 140), blob, 1, nowMs()));
  char why[192];
  CHECK(pumpUntil(w.cores, [&] { return w.b->k.act[3].state == GDAKI_CTRL_LA_ACT_LATER; }));
  CHECK(w.b->k.act[3].nLater == 1 && w.b->k.act[3].spareState == GL_SP_REPLAYING);
  CHECK(gdakiCtrlLaActStep(&w.b->k, 3, nowMs(), why, sizeof(why)) == GDAKI_CTRL_LA_AS_WAIT);
  CHECK(!s->k.unix.haveAct);  // nothing handed over before READY
  CHECK(gdakiCtrlLaUnixStatus(&s->k.unix, true, nullptr));
  CHECK(pumpUntil(w.cores, [&] {
    (void)gdakiCtrlLaUnixPoll(&s->k.unix, s->k.log, 3);
    return s->k.unix.haveAct;
  }));
  CHECK(s->k.unix.blob.size() == 3000 && memcmp(s->k.unix.blob.data(), w.b->outbox.data(), 3000) == 0);
  CHECK(gdakiCtrlLaSpareCheck(s->k.unix.act, 3, NONCE, 1) == 0);  // FENCED carried, the HELLO's incarnation
  {  // the record checks the spare refuses
    glRsActivate bad = s->k.unix.act;
    bad.reserved = 0;
    CHECK(gdakiCtrlLaSpareCheck(bad, 3, NONCE, 1) == 4);
    bad = s->k.unix.act;
    CHECK(gdakiCtrlLaSpareCheck(bad, 3, NONCE, 2) == 3);
    CHECK(gdakiCtrlLaSpareCheck(bad, 2, NONCE, 1) == 2);
    bad.kind = GL_RS_ACT_ABANDON;
    CHECK(gdakiCtrlLaSpareCheck(bad, 3, NONCE, 1) == 1);
  }
  const int blobFd = gdakiCtrlLaBlobFd(s->k.unix.blob);  // what gdakiMiActRecv reads: the blob's bytes, then EOF
  CHECK(blobFd >= 0);
  {
    std::vector<uint8_t> got(4000);
    size_t have = 0;
    for (;;) {
      const ssize_t n = read(blobFd, got.data() + have, got.size() - have);
      if (n <= 0) break;
      have += (size_t)n;
    }
    CHECK(have == 3000 && memcmp(got.data(), w.b->outbox.data(), 3000) == 0);
    close(blobFd);
  }
  glRsActivate ans = s->k.unix.act;
  ans.kind = GL_RS_ACT_ACCEPTED;
  CHECK(gdakiCtrlLaUnixTalk(&s->k.unix, GL_UT_ANSWER, &ans, sizeof(ans)));
  int fetchFd = -1;
  CHECK(gdakiCtrlLaRelayStart(&s->relayForTest, &s->k.unix, s->k.log, 3, &fetchFd));
  CHECK(pumpUntil(w.cores, [&] { return w.b->k.act[3].state == GDAKI_CTRL_LA_ACT_ACCEPTED; }));
  CHECK(gdakiCtrlLaActStep(&w.b->k, 3, nowMs(), why, sizeof(why)) == GDAKI_CTRL_LA_AS_ACCEPTED);
  // the FETCH talk: the spare's endpoint (112 B) out, the buddy's READY (72 B) in, the spare's DONE (80 B) out
  uint8_t ep[GL_FETCH_EP_BYTES], rd[GL_FETCH_READY_BYTES], dn[GL_FETCH_DONE_BYTES], got[GL_FETCH_READY_BYTES];
  for (size_t i = 0; i < sizeof(ep); i++) ep[i] = (uint8_t)(0xe0 + i);
  for (size_t i = 0; i < sizeof(rd); i++) rd[i] = (uint8_t)(0x40 + i);
  for (size_t i = 0; i < sizeof(dn); i++) dn[i] = (uint8_t)(0x90 + i);
  CHECK(write(fetchFd, ep, sizeof(ep)) == (ssize_t)sizeof(ep));
  CHECK(pumpUntil(w.cores, [&] { return w.b->k.act[3].haveEp; }));
  CHECK(memcmp(w.b->k.act[3].ep, ep, sizeof(ep)) == 0);
  CHECK(gdakiCtrlLaFetchReady(&w.b->k, 3, rd));
  size_t have = 0;
  const double end = nowMs() + 3000;
  while (have < sizeof(got) && nowMs() < end) {
    pump(w.cores);
    const ssize_t n = recv(fetchFd, got + have, sizeof(got) - have, MSG_DONTWAIT);
    if (n > 0) have += (size_t)n;
  }
  CHECK(have == sizeof(got) && memcmp(got, rd, sizeof(rd)) == 0);
  CHECK(write(fetchFd, dn, sizeof(dn)) == (ssize_t)sizeof(dn));
  CHECK(pumpUntil(w.cores, [&] { return w.b->k.act[3].haveDone; }));
  CHECK(memcmp(w.b->k.act[3].done, dn, sizeof(dn)) == 0);
  close(fetchFd);
  gdakiCtrlLaRelayEnd(&s->relayForTest);
  CHECK(s->relayForTest.moved == 3 && !s->relayForTest.aborted);
  CHECK(gl_core_stats(w.cores[1]->c)->nLater == 1 && gl_core_stats(w.cores[1]->c)->nActAccepted == 1);
  // the revived rank: REGISTER as incarnation 1 (the launcher swaps the pidfd), then both pairings, then a spare of 2
  s->k.inc = 1;
  s->k.own = 1;
  CHECK(selfHello(w.cores, s, 1, GDAKI_CTRL_LA_ROLE_RANK, 1));
  CHECK(gl_core_stats(w.cores[1]->c)->nPromoted == 1);
  CHECK(!gdakiCtrlLaPathExists(&s->k));  // not paired yet
  gdakiCtrlLaPairStart(&s->k, 1, nowMs());  // the own launcher first
  CHECK(pumpUntil(w.cores, [&] { return s->k.la[1].connected; }));
  CHECK(pumpUntil(w.cores, [&] { return s->k.la[1].haveNote[3] && s->k.la[1].note[3].regInc == 1; }));
  CHECK(gdakiCtrlLaPairedOwn(&s->k));  // the latch's condition
  CHECK(!gdakiCtrlLaPathExists(&s->k));  // only one of the two launchers, and no spare of incarnation 2
  Kid sp2 = spawnKid(w.cores[1]->sock.c_str(), GDAKI_CTRL_LA_ROLE_SPARE, 3, 2, NONCE);
  CHECK(kidRes(w.cores, sp2) == '1' && kidRes(w.cores, sp2) == 'c');
  kidCmd(sp2, 'a');
  CHECK(kidRes(w.cores, sp2) == 'K');
  CHECK(pumpUntil(w.cores, [&] { return s->k.la[1].note[3].spareState == GL_SP_REPLAYING; }));
  CHECK(!gdakiCtrlLaPathExists(&s->k));  // still: node 0 not paired
  gdakiCtrlLaPairStart(&s->k, 0, nowMs());
  CHECK(pumpUntil(w.cores, [&] { return s->k.la[0].connected; }));
  CHECK(gdakiCtrlLaAllPaired(&s->k) && gdakiCtrlLaPathExists(&s->k));  // re-armed only now
  reap(sp2);
  CHECK(pumpUntil(w.cores, [&] { return s->k.la[1].note[3].spareState == GL_SP_FAILED; }));
  CHECK(!gdakiCtrlLaPathExists(&s->k));  // the spare of 2 ended: no path
  reap(k);
  rmWorld(w);
  nScenes++;
}

// LATER, then no READY: 1000 ms after LATER the buddy ABORTs and falls back; the launcher tells the spare (a child) and
// SIGKILLs it through its pidfd after its grace.
static void sceneLaterTimeout() {
  World w = mkWorld();
  buddyUp(w);
  Kid k = spawnKid(w.cores[1]->sock.c_str(), GDAKI_CTRL_LA_ROLE_RANK, 3, 0, NONCE);
  CHECK(kidRes(w.cores, k) == '1' && kidRes(w.cores, k) == 'c');
  kidCmd(k, 'a');
  CHECK(kidRes(w.cores, k) == 'K');
  Kid sp = spawnKid(w.cores[1]->sock.c_str(), GDAKI_CTRL_LA_ROLE_SPARE, 3, 1, NONCE);
  CHECK(kidRes(w.cores, sp) == '1' && kidRes(w.cores, sp) == 'c');
  kidCmd(sp, 'a');
  CHECK(kidRes(w.cores, sp) == 'K');
  kill(k.pid, SIGKILL);
  waitpid(k.pid, nullptr, 0);
  k.pid = -1;
  CHECK(pumpUntil(w.cores, [&] { return gdakiCtrlFencedIs(w.b->k.fencedPlus1[3], 0); }));
  const glRegion none = {0, 0, 0};
  CHECK(gdakiCtrlLaActStart(&w.b->k, 3, actRecord(3, 1, 140), none, 1, nowMs()));
  CHECK(pumpUntil(w.cores, [&] { return w.b->k.act[3].state == GDAKI_CTRL_LA_ACT_LATER; }));
  const double tLater = w.b->k.act[3].laterMs;
  char why[192] = {0};
  int s = GDAKI_CTRL_LA_AS_WAIT;
  while (s == GDAKI_CTRL_LA_AS_WAIT && nowMs() - tLater < 3000) {
    pump(w.cores);
    feedBeat(w.b, w.cores);
    s = gdakiCtrlLaActStep(&w.b->k, 3, nowMs(), why, sizeof(why));
  }
  const double tFall = nowMs();
  CHECK(s == GDAKI_CTRL_LA_AS_FALLBACK);
  CHECK(tFall - tLater >= 1000.0 && tFall - tLater < 1100.0);
  CHECK(strstr(why, "not READY 1000 ms after LATER (ABORT sent)") != nullptr);
  CHECK(w.b->k.act[3].state == GDAKI_CTRL_LA_ACT_ABORTED);
  glEntryView v;
  CHECK(pumpUntil(w.cores, [&] { return gl_core_entry(w.cores[1]->c, NONCE, 3, 2, 1, &v) == 1 && v.sp == GL_SP_ABORTED; }));
  int st = 0;
  const double end = nowMs() + 2000;
  pid_t got = 0;
  while (got == 0 && nowMs() < end) {
    pump(w.cores);
    got = waitpid(sp.pid, &st, WNOHANG);
  }
  CHECK(got == sp.pid && WIFSIGNALED(st) && WTERMSIG(st) == SIGKILL);  // the launcher's SIGKILL after its grace
  sp.pid = -1;
  reap(sp);
  reap(k);
  rmWorld(w);
  nScenes++;
}

// The launcher stops (its loop does not run): after LATER its page's beat stands; 1000 ms later the buddy says the
// launcher is lost with (STOP_launcher) and falls back (the LATER bound set above it so the stall rule is what ends it).
static void sceneLauncherStall() {
  World w = mkWorld();
  buddyUp(w);
  w.b->k.laterMs = 5000;
  Kid k = spawnKid(w.cores[1]->sock.c_str(), GDAKI_CTRL_LA_ROLE_RANK, 3, 0, NONCE);
  CHECK(kidRes(w.cores, k) == '1' && kidRes(w.cores, k) == 'c');
  kidCmd(k, 'a');
  CHECK(kidRes(w.cores, k) == 'K');
  Kid sp = spawnKid(w.cores[1]->sock.c_str(), GDAKI_CTRL_LA_ROLE_SPARE, 3, 1, NONCE);
  CHECK(kidRes(w.cores, sp) == '1' && kidRes(w.cores, sp) == 'c');
  kidCmd(sp, 'a');
  CHECK(kidRes(w.cores, sp) == 'K');
  kill(k.pid, SIGKILL);
  waitpid(k.pid, nullptr, 0);
  k.pid = -1;
  CHECK(pumpUntil(w.cores, [&] { return gdakiCtrlFencedIs(w.b->k.fencedPlus1[3], 0); }));
  const glRegion none = {0, 0, 0};
  CHECK(gdakiCtrlLaActStart(&w.b->k, 3, actRecord(3, 1, 140), none, 1, nowMs()));
  CHECK(pumpUntil(w.cores, [&] { return w.b->k.act[3].state == GDAKI_CTRL_LA_ACT_LATER; }));
  feedBeat(w.b, w.cores);
  const double tStall = nowMs();  // from here the launchers do not step: the beat stands
  char why[192] = {0};
  int s = GDAKI_CTRL_LA_AS_WAIT;
  while (s == GDAKI_CTRL_LA_AS_WAIT && nowMs() - tStall < 3000) {
    msleep(5);
    feedBeat(w.b, w.cores);  // the READ of the page: the same beat
    s = gdakiCtrlLaActStep(&w.b->k, 3, nowMs(), why, sizeof(why));
  }
  CHECK(s == GDAKI_CTRL_LA_AS_FALLBACK);
  CHECK(nowMs() - tStall >= 1000.0 && nowMs() - tStall < 1200.0);
  CHECK(nLines(*w.b, "the launcher of node 1 is lost (beat_stale) during rank 3's activation (incarnation 1): falling "
                     "back (STOP_launcher)") == 1);
  CHECK(w.b->k.act[3].state == GDAKI_CTRL_LA_ACT_ABORTED);  // ABORT was put on the QP all the same
  // the first-answer bound: an ACTIVATE that the launcher never answers (its QP takes it, the loop never runs)
  w.b->k.act[3] = gdakiCtrlLaAct();
  w.b->k.la[1].beatMs = -1;
  CHECK(gdakiCtrlLaActStart(&w.b->k, 3, actRecord(3, 1, 140), none, 2, nowMs()));
  const double t0 = nowMs();
  s = GDAKI_CTRL_LA_AS_WAIT;
  while (s == GDAKI_CTRL_LA_AS_WAIT && nowMs() - t0 < 3000) {
    msleep(5);
    s = gdakiCtrlLaActStep(&w.b->k, 3, nowMs(), why, sizeof(why));
  }
  CHECK(s == GDAKI_CTRL_LA_AS_FALLBACK && nowMs() - t0 >= 1000.0 && nowMs() - t0 < 1200.0);
  CHECK(strstr(why, "no answer of the launcher to the activation within 1000 ms") != nullptr);
  // the record QP's error: lost at once
  w.b->k.act[3] = gdakiCtrlLaAct();
  CHECK(gdakiCtrlLaActStart(&w.b->k, 3, actRecord(3, 1, 140), none, 3, nowMs()));
  w.b->k.la[1].qpErr = true;
  CHECK(gdakiCtrlLaActStep(&w.b->k, 3, nowMs(), why, sizeof(why)) == GDAKI_CTRL_LA_AS_FALLBACK);
  CHECK(nLines(*w.b, "is lost (record_QP_error)") == 1);
  reap(sp);
  reap(k);
  rmWorld(w);
  nScenes++;
}

// Arming (gl_path_exists through the link): a rank registered and paired with both launchers is armed only with a noted
// spare of the next incarnation; LEAVING takes it away.
static void sceneArming() {
  World w = mkWorld();
  buddyUp(w);  // rank 2 (this process) registered at node 1, paired with both
  CHECK(pumpUntil(w.cores, [&] { return w.b->k.la[1].haveNote[2] && w.b->k.la[1].note[2].regState == GL_RS_ALIVE; }));
  CHECK(gdakiCtrlLaPairedOwn(&w.b->k));
  CHECK(!gdakiCtrlLaPathExists(&w.b->k));  // no spare noted
  {
    const glArmView v = gdakiCtrlLaArmViewOf(&w.b->k);
    CHECK(v.regAcked && v.ownPaired && v.allPaired && v.notedReg == GL_RS_ALIVE && v.notedSpare == GL_SP_NONE);
    CHECK(gl_armable(1, &v) == 0);
  }
  Kid sp = spawnKid(w.cores[1]->sock.c_str(), GDAKI_CTRL_LA_ROLE_SPARE, 2, 1, NONCE);
  CHECK(kidRes(w.cores, sp) == '1' && kidRes(w.cores, sp) == 'c');
  kidCmd(sp, 'a');
  CHECK(kidRes(w.cores, sp) == 'K');
  CHECK(pumpUntil(w.cores, [&] { return gdakiCtrlLaPathExists(&w.b->k); }));
  {
    const glArmView v = gdakiCtrlLaArmViewOf(&w.b->k);
    CHECK(gl_armable(1, &v) == 1 && gl_armable(0, &v) == 0);
  }
  // the registration tail the host writes (STORE_REQ): the launcher path with its flag, and the buddy's check
  gdakiCtrlLaSpareReg g;
  memset(&g, 0, sizeof(g));
  g.magic = GDAKI_CTRL_LA_SPAREREG_MAGIC;
  g.version = GDAKI_CTRL_LA_SPAREREG_VERSION;
  g.path = GDAKI_CTRL_LA_PATH_LAUNCHER;
  g.node = 1;
  g.rank = 2;
  g.inc = 0;
  g.flags = gdakiCtrlLaPathExists(&w.b->k) ? GDAKI_CTRL_LA_REG_F_PATH : 0u;
  CHECK(gdakiCtrlLaSpareRegOk(g, 2, 0) && !gdakiCtrlLaSpareRegOk(g, 2, 1) && !gdakiCtrlLaSpareRegOk(g, 3, 0));
  g.flags = 0;
  CHECK(!gdakiCtrlLaSpareRegOk(g, 2, 0));
  // without a launcher count (the all-gather's) nothing is all paired
  w.b->k.nLaunchers = 0;
  CHECK(!gdakiCtrlLaPathExists(&w.b->k));
  w.b->k.nLaunchers = 2;
  // LEAVING: no path
  CHECK(gdakiCtrlLaUnixLeaving(&w.b->k.unix));
  CHECK(!gdakiCtrlLaPathExists(&w.b->k));
  reap(sp);
  rmWorld(w);
  nScenes++;
}

// The Unix socket's loss: the line once (the launcher's end goes away), then nothing is sent on it.
static void sceneSocketLoss() {
  World w = mkWorld();
  buddyUp(w);
  rmCore(w.cores[1]);  // the launcher of node 1 shuts down (its connections close)
  w.cores.pop_back();
  for (int i = 0; i < 50 && !w.b->k.unix.closed; i++) {
    (void)gdakiCtrlLaUnixPoll(&w.b->k.unix, w.b->k.log, 2);
    msleep(2);
  }
  CHECK(w.b->k.unix.closed);
  CHECK(nLines(*w.b, "rank 2: launcher Unix socket closed (EOF)") == 1);
  (void)gdakiCtrlLaUnixPoll(&w.b->k.unix, w.b->k.log, 2);
  CHECK(nLines(*w.b, "launcher Unix socket closed") == 1);
  CHECK(!gdakiCtrlLaUnixLeaving(&w.b->k.unix));
  rmWorld(w);
  nScenes++;
}

// Pure pieces: the env values, the FENCED mark, the registration layout.
static void scenePure() {
  setenv(GDAKI_CTRL_LA_SPARE_INC_ENV, "2", 1);
  CHECK(gdakiCtrlLaSpareIncEnv() == 2);
  setenv(GDAKI_CTRL_LA_SPARE_INC_ENV, "0", 1);
  CHECK(gdakiCtrlLaSpareIncEnv() == 0);
  unsetenv(GDAKI_CTRL_LA_SPARE_INC_ENV);
  CHECK(gdakiCtrlLaSpareIncEnv() == 1);
  setenv(GL_NODE_ENV, "1", 1);
  CHECK(gdakiCtrlLaNodeEnv() == 1);
  setenv(GL_NODE_ENV, "x", 1);
  CHECK(gdakiCtrlLaNodeEnv() == -2);
  unsetenv(GL_NODE_ENV);
  CHECK(gdakiCtrlLaNodeEnv() == -1);
  char p[108];
  setenv(GL_SOCK_ENV, "/tmp/x/launcher.sock", 1);
  CHECK(gdakiCtrlLaSockPath(p, sizeof(p)) && strcmp(p, "/tmp/x/launcher.sock") == 0);
  unsetenv(GL_SOCK_ENV);
  char d[108];
  CHECK(gdakiCtrlLaSockPath(p, sizeof(p)) && gl_default_sock_path(d, sizeof(d)) == 0 && strcmp(p, d) == 0);
  for (uint32_t inc = 1; inc < 1000; inc++) {
    CHECK(gdakiCtrlLaActFencedOk(gdakiCtrlLaActFencedMark(inc), inc));
    CHECK(!gdakiCtrlLaActFencedOk(gdakiCtrlLaActFencedMark(inc), inc + 1));
    CHECK(!gdakiCtrlLaActFencedOk(0, inc));
  }
  CHECK(!gdakiCtrlLaActFencedOk(0, 0));
  nScenes++;
}
#endif  // !NCCL_GIN_CTRL_TCP

int main(int argc, char** argv) {
#if !NCCL_GIN_CTRL_TCP
  if (argc > 1 && chdir(argv[1]) != 0) return 2;  // sun_path is 108 bytes: a short working directory
  signal(SIGPIPE, SIG_IGN);
  scenePure();
  sceneRegistration();
  sceneLeavingLeft();
  sceneKillExited();
  sceneFenceStopped();
  sceneFenceNak();
  sceneActivationLaterAccepted();
  sceneLaterTimeout();
  sceneLauncherStall();
  sceneArming();
  sceneSocketLoss();
  printf("gc_unit_p3 (rdma): %d scenes, %d checks, %d failed\n", nScenes, nChecks, nFail);
#else
  (void)argc, (void)argv;
  printf("gc_unit_p3 (tcp): the launcher link is not in the tcp build (the region is empty), 0 checks\n");
#endif
  return nFail == 0 ? 0 : 1;
}
