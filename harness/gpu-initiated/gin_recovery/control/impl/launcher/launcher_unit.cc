// launcher_unit.cc - CPU unit test of the launcher's state machine (gin-control, EXPERIMENT.md 9.5, 9.8 "launcher:
// state machine model"). Built with ASan and UBSan by build_launcher.sh; no verbs, no CUDA, no network.
//
// The state machine is gin_launcher.c itself (compiled with -DGL_NO_MAIN). The RNIC side is the in-process test
// transport below (it records what the launcher sends and lets a test inject UD and RC messages, READ completions and QP
// errors). The node side is real: the launcher listens on a Unix socket in the working directory, and every "rank" or
// "spare" is a forked child that connects, sends its own pidfd (pidfd_open(getpid())) by SCM_RIGHTS, and then only sends,
// receives, sleeps or exits on the parent's command. pidfds, exits, SIGSTOP and SIGKILL are real.
//
// Scenes (EXPERIMENT.md 9.8 and the task): pidfd facts on this kernel; registration and its refusals; EXITED; LEFT vs
// BYE; FENCE and EXITED interleavings (FENCE after the exit still gives FENCED); no signal to a pidfd it does not hold;
// SPAWN -> REFUSED "spawn not built"; LATER then hand-over (the hand-over gap); spare exits before activation; the
// early-answer bound (no answer but LATER until READY, failure, exit or ABORT); the lost ACCEPTED; second connection
// with the same incarnation; re-registration swaps the pidfd and closes the old one; pairing; the registration oracle
// (the path's every condition against the launcher's own words); the socket directory; malformed messages; the page;
// (REVIEW_PREP) an ABORT, an exit or a QP loss while the blob READ is in flight (the buffer outlives the READ: ASan sees a
// write into freed heap otherwise); a closed QP's queued events never reach a newer QP that took its slot; after
// ACCEPTED a blip of the buddy's QP does not SIGKILL the revived process; the nonce-free INFO (same launcher fields as
// HELLO_ACK, no entry or page slot, a stray fd refused and closed, REGISTER after it on the same connection, kind 10
// still unknown).
//
// The warm spare (user decision 2026-10-17): the launcher itself forks and execs the spare. The spare is this binary run
// as "launcher_unit --fake-spare [--fork]": it reports what it inherited (session, fds, stdio, environment) over a
// control socket of the test (glctl.sock), takes one plan byte (h: HELLO, then the kid commands above; n: no HELLO;
// e: HELLO then exit; q: exit at once; t: as h when its NCCL_GIN_RESTORE_REPLAY file exists, else the replay's "cannot open
// the transcript" line and exit 2, as the smoke's a4 spare) and then obeys the same single-byte commands as a forked kid. Scenes: spawn at
// start and HELLO within the bound (also through a wrapper that forks, as `timeout` does); activation -> the next spare
// with the incarnation + 1 (by DONE, and by the re-registration), the page's spare word through the cycle; an unused
// spare's exit -> respawn, the cap, an exec failure; HELLO timeout -> one line, one retry, then no more; no signal to a
// process the launcher did not spawn or register; the options. The wait-for (sparefix): a spawn waits until its pattern
// matches (then spawns within a poll), or spawns anyway after the bound; an exit "cannot open the transcript" of such a
// spawn is not counted against the respawn cap; the same exit of a spawn whose wait was met is (the bound of the rule).
#include <cerrno>
#include <cinttypes>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <algorithm>
#include <deque>
#include <map>
#include <string>
#include <vector>

#include <dirent.h>
#include <fcntl.h>
#include <poll.h>
#include <pthread.h>
#include <signal.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#include "gin_launcher.h"

static int nChecks = 0, nFail = 0;
#define CHECK(c)                                                                     \
  do {                                                                               \
    nChecks++;                                                                       \
    if (!(c)) {                                                                      \
      nFail++;                                                                       \
      fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c);                   \
    }                                                                                \
  } while (0)

static double now_ms() {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return t.tv_sec * 1e3 + t.tv_nsec / 1e6;
}
static int sys_pidfd_open(pid_t p) { return (int)syscall(SYS_pidfd_open, p, 0); }
static int sys_pidfd_signal(int fd, int sig) { return (int)syscall(SYS_pidfd_send_signal, fd, sig, nullptr, 0); }
static bool readable(int fd) {
  struct pollfd p = {fd, POLLIN, 0};
  return poll(&p, 1, 0) > 0 && (p.revents & POLLIN);
}
static char proc_state(pid_t p) {
  char f[64], b[512];
  snprintf(f, sizeof(f), "/proc/%d/stat", (int)p);
  FILE* x = fopen(f, "r");
  if (!x) return '-';
  const size_t n = fread(b, 1, sizeof(b) - 1, x);
  fclose(x);
  b[n] = 0;
  const char* q = strrchr(b, ')');
  return q && q[1] && q[2] ? q[2] : '?';
}

// ------------------------------------------------------------------------------------------------ test transport

struct Sent {
  int peer;
  glMsg m;
};
struct TT {
  glTransport tp;
  std::deque<glTpEvent> in;
  std::vector<Sent> rc;
  std::vector<std::pair<glEp, glMsg>> ud;
  std::vector<uint32_t> udQkey;
  int nextHandle = 0;
  std::map<int, bool> open, connected;
  std::map<int, int> kind;
  std::map<int, glEp> remote;
  std::map<int, std::pair<glRegion, uint32_t>> credit;
  std::map<uint32_t, std::pair<uint8_t*, uint32_t>> mem;  // rkey -> region
  struct Read {
    int peer;
    uint64_t addr;
    uint32_t rkey, len;
    void* dst;
    uint64_t cookie;
  };
  std::vector<Read> reads;
  bool failRead = false;
  bool holdReads = false;   // READs stay in flight until release_reads (the verbs transport's real timing)
  int nRcOpen = 0;
  // handle numbering: by default every QP a new number (nextHandle++). slotMode: as the verbs transport, a slot is reused
  // and the handle is (serial << 8) | slot; noSerial (the negative control): the handle is the slot alone, reused.
  bool slotMode = false, noSerial = false;
  uint32_t serial = 0;
  int nReadsDropped = 0;
};
static TT* tt_of(glTransport* tp) { return (TT*)tp->impl; }
static int tt_fds(glTransport*, int*, int) { return 0; }
static void tt_complete_reads(TT* t) {
  for (const TT::Read& r : t->reads) {
    glTpEvent e;
    memset(&e, 0, sizeof(e));
    e.type = GL_TP_READ_DONE;
    e.peer = r.peer;
    e.cookie = r.cookie;
    auto it = t->mem.find(r.rkey);
    const bool ok = !t->failRead && it != t->mem.end() && r.addr >= (uint64_t)(uintptr_t)it->second.first &&
                    r.addr + r.len <= (uint64_t)(uintptr_t)it->second.first + it->second.second;
    if (ok) memcpy(r.dst, (const void*)(uintptr_t)r.addr, r.len);
    e.status = ok ? 0 : 5;
    t->in.push_back(e);
  }
  t->reads.clear();
}
static int tt_poll(glTransport* tp, glTpEvent* ev, int max) {
  TT* t = tt_of(tp);
  if (!t->holdReads) tt_complete_reads(t);  // complete READs on the next poll
  int k = 0;
  while (k < max && !t->in.empty()) {
    ev[k++] = t->in.front();
    t->in.pop_front();
  }
  return k;
}
static int tt_local_ud(glTransport*, glEp* ud) {
  memset(ud, 0, sizeof(*ud));
  ud->qpn = 4242;
  ud->psn = 0x1234567;  // its Q_Key
  ud->gidIndex = 3;
  ud->version = GL_EP_VERSION;
  ud->qpType = GL_QPT_UD;
  return 0;
}
static int tt_page(glTransport*, void* page, size_t len, glRegion* out) {
  out->addr = (uint64_t)(uintptr_t)page;
  out->rkey = 0x9a9e;
  out->len = (uint32_t)len;
  return 0;
}
static int tt_ud_send(glTransport* tp, const glEp* to, uint32_t qkey, const glMsg* m) {
  tt_of(tp)->ud.push_back({*to, *m});
  tt_of(tp)->udQkey.push_back(qkey);
  return 0;
}
static int tt_rc_create(glTransport* tp, int kind, uint32_t, uint64_t, glEp* local) {
  TT* t = tt_of(tp);
  int h = t->nextHandle++;
  if (t->slotMode) {  // the lowest slot not open, as the verbs transport picks its slot
    int slot = 0;
    for (;; slot++) {
      bool busy = false;
      for (const auto& o : t->open)
        if (o.second && (o.first & 0xff) == slot) busy = true;
      if (!busy) break;
    }
    t->serial = (t->serial + 1) & 0x3fffffu;
    h = t->noSerial ? slot : (int)((t->serial << 8) | (uint32_t)slot);
    t->connected[h] = false;
    t->remote.erase(h);
  }
  t->open[h] = true;
  t->kind[h] = kind;
  t->nRcOpen++;
  memset(local, 0, sizeof(*local));
  local->qpn = 5000 + (uint32_t)h;
  local->psn = 0x10000u + (uint32_t)h * 7919u;  // a different PSN for every QP
  local->version = GL_EP_VERSION;
  local->qpType = GL_QPT_RC;
  return h;
}
static int tt_rc_connect(glTransport* tp, int h, const glEp* remote) {
  TT* t = tt_of(tp);
  if (!t->open[h] || t->connected[h]) return -1;
  t->connected[h] = true;
  t->remote[h] = *remote;
  return 0;
}
static void tt_credit_at(glTransport* tp, int h, const glRegion* page, uint32_t off) { tt_of(tp)->credit[h] = {*page, off}; }
static int tt_rc_send(glTransport* tp, int peer, const glMsg* m) {
  TT* t = tt_of(tp);
  if (!t->open[peer] || !t->connected[peer] || t->kind[peer] != GL_PAIR_RECORD) return -1;
  t->rc.push_back({peer, *m});
  return 0;
}
static int tt_rc_read(glTransport* tp, int peer, uint64_t addr, uint32_t rkey, uint32_t len, void* dst,
                      uint64_t cookie) {
  tt_of(tp)->reads.push_back({peer, addr, rkey, len, dst, cookie});
  return 0;
}
// The contract (launcher_transport.h): after rc_close no event of that QP comes and no READ writes into its buffer.
static void tt_rc_close(glTransport* tp, int peer) {
  TT* t = tt_of(tp);
  t->open[peer] = false;
  for (size_t i = t->reads.size(); i-- > 0;)
    if (t->reads[i].peer == peer) {
      t->reads.erase(t->reads.begin() + (long)i);
      t->nReadsDropped++;
    }
  if (!t->noSerial)  // the negative control keeps the old behaviour: the queued events stay
    for (size_t i = t->in.size(); i-- > 0;)
      if (t->in[i].peer == peer && t->in[i].type != GL_TP_UD_RECV) t->in.erase(t->in.begin() + (long)i);
}
static void tt_close(glTransport*) {}
static const glTransportOps tt_ops = {tt_fds,        tt_poll,    tt_local_ud,  tt_page,     tt_ud_send, tt_rc_create,
                                      tt_rc_connect, tt_rc_send, tt_rc_read, tt_credit_at, tt_rc_close, tt_close};

// ------------------------------------------------------------------------------------------------ the launcher under test

static const char* kSock = "glsock/launcher.sock";  // relative: sun_path is 108 bytes, the build dir is long

struct SigRec {
  pid_t pid;
  int sig, rc;
};
static std::vector<SigRec> gSignals;
static void on_signal(void*, pid_t pid, int sig, int rc) { gSignals.push_back({pid, sig, rc}); }

struct L {
  TT* t;
  glCore* c;
};
static L mk_launcher(uint32_t node, uid_t uid, int noExitReport = 0, const char* sock = kSock) {
  L l;
  l.t = new TT();
  l.t->tp.ops = &tt_ops;
  l.t->tp.impl = l.t;
  glConfig cfg;
  memset(&cfg, 0, sizeof(cfg));
  cfg.node = node;
  cfg.qkey = 0x1234567;
  cfg.uid = uid;
  cfg.noExitReport = noExitReport;
  cfg.graceMs = 200;
  static FILE* logf = nullptr;
  if (!logf) logf = fopen("launcher_unit.log", "a");
  cfg.log = logf;
  cfg.onSignal = on_signal;
  l.c = gl_core_new(&cfg, &l.t->tp);
  char why[256] = {0};
  const int rc = gl_core_listen(l.c, sock, why, sizeof(why));
  if (rc != 0) fprintf(stderr, "listen: %s\n", why);
  CHECK(rc == 0);
  return l;
}
static void rm_launcher(L& l) {
  gl_core_shutdown(l.c);
  gl_core_free(l.c);
  delete l.t;
  l.c = nullptr;
  l.t = nullptr;
}
static void pump(L& l, int ms) {
  const double end = now_ms() + ms;
  do gl_core_step(l.c, 1);
  while (now_ms() < end);
}
template <class F>
static bool pump_until(L& l, F pred, int ms = 3000) {
  const double end = now_ms() + ms;
  while (now_ms() < end) {
    gl_core_step(l.c, 1);
    if (pred()) return true;
  }
  return pred();
}

static glMsg mk(uint16_t kind, int32_t rank, uint32_t inc, uint64_t nonce, int32_t from) {
  static uint32_t seq = 1000;
  glMsg m;
  memset(&m, 0, sizeof(m));
  m.h.magic = GL_MAGIC;
  m.h.version = GL_WIRE_VERSION;
  m.h.kind = kind;
  m.h.rank = rank;
  m.h.incarnation = inc;
  m.h.nonce = nonce;
  m.h.from = from;
  m.h.seq = ++seq;
  return m;
}
static void rc_in(L& l, int h, const glMsg& m) {
  glTpEvent e;
  memset(&e, 0, sizeof(e));
  e.type = GL_TP_RC_RECV;
  e.peer = h;
  e.msg = m;
  l.t->in.push_back(e);
}
static void ud_in(L& l, const glMsg& m) {
  glTpEvent e;
  memset(&e, 0, sizeof(e));
  e.type = GL_TP_UD_RECV;
  e.peer = -1;
  e.msg = m;
  l.t->in.push_back(e);
}
static glMsg mk_pair(int32_t rank, uint32_t inc, uint64_t nonce, uint32_t gen, uint32_t sub, uint32_t qpn) {
  glMsg m = mk(GL_K_PAIR, rank, inc, nonce, rank);
  m.h.sub = sub;
  glPairBody b;
  memset(&b, 0, sizeof(b));
  b.gen = gen;
  b.qkey = (uint32_t)(nonce & 0x7fffffff);
  b.qp.qpn = qpn;
  b.qp.psn = 0x200000u + qpn;
  b.ud.qpn = 900 + (uint32_t)rank;
  b.page.addr = 0x7000;
  b.page.rkey = 0x500 + (uint32_t)rank;
  b.page.len = 4096;
  b.creditOff = 64 + 8 * 4;
  memcpy(m.body, &b, sizeof(b));
  m.h.bodyBytes = sizeof(b);
  return m;
}
// Pair rank `rank` (gen) with the launcher (record QP), then CONNECTED. Returns its record-QP handle.
static int pair_rank(L& l, int32_t rank, uint32_t inc, uint64_t nonce, uint32_t gen = 1, bool connect = true) {
  const int h = l.t->nextHandle;
  ud_in(l, mk_pair(rank, inc, nonce, gen, GL_PAIR_RECORD, 100 + (uint32_t)rank * 10 + gen + inc * 100));
  gl_core_step(l.c, 0);
  if (connect) {
    rc_in(l, h, mk(GL_K_CONNECTED, rank, inc, nonce, rank));
    gl_core_step(l.c, 0);
  }
  return h;
}
static int count_kind(L& l, int h, uint16_t kind) {
  int n = 0;
  for (const Sent& s : l.t->rc)
    if ((h < 0 || s.peer == h) && s.m.h.kind == kind) n++;
  return n;
}
static const glMsg* last_kind(L& l, int h, uint16_t kind) {
  for (size_t i = l.t->rc.size(); i-- > 0;)
    if (l.t->rc[i].peer == h && l.t->rc[i].m.h.kind == kind) return &l.t->rc[i].m;
  return nullptr;
}

// ------------------------------------------------------------------------------------------------ children

struct Kid {
  pid_t pid = -1;
  int cmd = -1, res = -1;
};
enum KidMode { K_REGISTER = 1, K_SPARE = 2, K_BADFD = 3, K_NOFD = 4, K_OTHERPID = 5, K_TWOFD = 6, K_NONE = 7 };

static int kid_send(int s, uint16_t kind, uint32_t sub, int32_t rank, uint32_t inc, uint64_t nonce, const void* body,
                    size_t blen, int fd, int fd2 = -1) {
  glUnixMsg u;
  memset(&u, 0, sizeof(u));
  u.h.magic = GL_U_MAGIC;
  u.h.version = GL_WIRE_VERSION;
  u.h.kind = kind;
  u.h.sub = sub;
  u.h.rank = rank;
  u.h.incarnation = inc;
  u.h.nonce = nonce;
  u.h.pid = getpid();
  if (blen) memcpy(u.body, body, blen);
  u.h.bodyBytes = (uint16_t)blen;
  struct iovec iov = {&u, sizeof(u)};
  struct msghdr mh;
  memset(&mh, 0, sizeof(mh));
  mh.msg_iov = &iov;
  mh.msg_iovlen = 1;
  union {
    char b[CMSG_SPACE(sizeof(int) * 2)];
    struct cmsghdr a;
  } cb;
  memset(&cb, 0, sizeof(cb));
  if (fd >= 0) {
    const int nf = fd2 >= 0 ? 2 : 1;
    mh.msg_control = cb.b;
    mh.msg_controllen = CMSG_SPACE(sizeof(int) * nf);
    struct cmsghdr* cm = CMSG_FIRSTHDR(&mh);
    cm->cmsg_level = SOL_SOCKET;
    cm->cmsg_type = SCM_RIGHTS;
    cm->cmsg_len = CMSG_LEN(sizeof(int) * nf);
    int fds[2] = {fd, fd2};
    memcpy(CMSG_DATA(cm), fds, sizeof(int) * nf);
  }
  return sendmsg(s, &mh, MSG_NOSIGNAL) == (ssize_t)sizeof(u) ? 0 : -1;
}
static int kid_connect() {
  const int s = socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0);
  struct sockaddr_un a;
  memset(&a, 0, sizeof(a));
  a.sun_family = AF_UNIX;
  snprintf(a.sun_path, sizeof(a.sun_path), "%s", kSock);
  if (connect(s, (struct sockaddr*)&a, sizeof(a)) != 0) return -1;
  struct timeval tv = {5, 0};
  setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
  return s;
}
static void kid_forward(int res, const void* b, uint32_t n) {
  if (write(res, &n, 4) != 4) _exit(9);
  if (n && write(res, b, n) != (ssize_t)n) _exit(9);
}
static void* kid_thread(void*) {
  usleep(300000);
  return nullptr;
}
// The last thread of a process whose leader already exited ends it with _exit: ASan's thread teardown reads
// /proc/self/maps, which is empty once the leader is a zombie (an ASan CHECK, seen in the first run).
static void* kid_thread_exit(void*) {
  usleep(300000);
  _exit(0);
}
static int kid_hello(int mode, int32_t rank, uint32_t inc, uint64_t nonce) {
  const int s = kid_connect();
  if (s < 0) _exit(8);
  const uint16_t kind = mode == K_SPARE ? GL_U_SPARE_HELLO : GL_U_REGISTER;
  int pfd = -1, extra = -1;
  if (mode == K_REGISTER || mode == K_SPARE || mode == K_TWOFD) pfd = sys_pidfd_open(getpid());
  if (mode == K_TWOFD) extra = sys_pidfd_open(getpid());
  if (mode == K_OTHERPID) pfd = sys_pidfd_open(getppid());
  int pp[2] = {-1, -1};
  if (mode == K_BADFD) {
    if (pipe(pp) != 0) _exit(8);
    pfd = pp[0];
  }
  if (mode != K_NONE) kid_send(s, kind, 0, rank, inc, nonce, nullptr, 0, mode == K_NOFD ? -1 : pfd, extra);
  if (pfd >= 0) close(pfd);
  if (extra >= 0) close(extra);
  return s;
}
// The child: connect, hello (forward its answer), then obey single-byte commands.
static void kid_main(int cmd, int res, int mode, int32_t rank, uint32_t inc, uint64_t nonce) {
  int s = kid_hello(mode, rank, inc, nonce);
  alignas(64) static uint8_t buf[sizeof(glUnixMsg) + GL_U_MAX_PAYLOAD];
  if (mode != K_NONE) {
    const ssize_t n = recv(s, buf, sizeof(buf), 0);
    kid_forward(res, buf, n > 0 ? (uint32_t)n : 0);
  }
  glRsActivate lastRec;
  memset(&lastRec, 0, sizeof(lastRec));
  for (;;) {
    char op;
    const ssize_t r = read(cmd, &op, 1);
    if (r <= 0) _exit(0);
    switch (op) {
      case 'x': _exit(0);
      case 'L':  // LEAVING, then exit at once
        kid_send(s, GL_U_LEAVING, 0, rank, inc, nonce, nullptr, 0, -1);
        _exit(0);
      case 'l': kid_send(s, GL_U_LEAVING, 0, rank, inc, nonce, nullptr, 0, -1); break;
      case 'R': kid_send(s, GL_U_SPARE_STATUS, GL_US_READY, rank, inc, nonce, nullptr, 0, -1); break;
      case 'F': {
        const char why[] = "replay mismatch";
        kid_send(s, GL_U_SPARE_STATUS, GL_US_REPLAY_FAILED, rank, inc, nonce, why, sizeof(why), -1);
        _exit(3);
      }
      case 'h': {  // receive one message and forward it
        const ssize_t n = recv(s, buf, sizeof(buf), 0);
        if (n >= (ssize_t)sizeof(glUnixMsg)) {
          const glUnixMsg* u = (const glUnixMsg*)buf;
          if (u->h.kind == GL_U_ACT_BYTES) memcpy(&lastRec, u->body, sizeof(lastRec));
        }
        kid_forward(res, buf, n > 0 ? (uint32_t)n : 0);
        break;
      }
      case 'a':
      case 'r':
      case 'z': {  // answer the last activation: ACCEPTED, REFUSED, LATER
        glRsActivate a = lastRec;
        a.kind = op == 'a' ? GL_RS_ACT_ACCEPTED : op == 'r' ? GL_RS_ACT_REFUSED : GL_RS_ACT_LATER;
        kid_send(s, GL_U_ACT_TALK, GL_UT_ANSWER, rank, inc, nonce, &a, sizeof(a), -1);
        break;
      }
      case 'E':
      case 'D': {
        uint8_t b[GL_FETCH_EP_BYTES];
        for (unsigned i = 0; i < sizeof(b); i++) b[i] = (uint8_t)(op + i);
        kid_send(s, GL_U_ACT_TALK, op == 'E' ? GL_UT_FETCH_EP : GL_UT_FETCH_DONE, rank, inc, nonce, b,
                 op == 'E' ? GL_FETCH_EP_BYTES : GL_FETCH_DONE_BYTES, -1);
        break;
      }
      case 'G': {  // re-register (rank, inc) with a fresh pidfd on the same connection
        const int pfd = sys_pidfd_open(getpid());
        kid_send(s, GL_U_REGISTER, 0, rank, inc, nonce, nullptr, 0, pfd);
        close(pfd);
        const ssize_t n = recv(s, buf, sizeof(buf), 0);
        kid_forward(res, buf, n > 0 ? (uint32_t)n : 0);
        break;
      }
      case '2': {  // a second connection with the same hello
        const int s2 = kid_hello(mode, rank, inc, nonce);
        const ssize_t n = recv(s2, buf, sizeof(buf), 0);
        kid_forward(res, buf, n > 0 ? (uint32_t)n : 0);
        break;
      }
      case 'V': {  // LEAVING on a second connection (not the registering one)
        const int s2 = kid_connect();
        kid_send(s2, GL_U_LEAVING, 0, rank, inc, nonce, nullptr, 0, -1);
        usleep(20000);
        close(s2);
        kid_forward(res, "v", 1);
        break;
      }
      case 'T': {  // multi-threaded exit: another thread lives 300 ms, the leader exits now
        pthread_t t;
        pthread_create(&t, nullptr, kid_thread_exit, nullptr);
        kid_forward(res, "t", 1);
        pthread_exit(nullptr);
      }
      case 'C': close(s); s = -1; kid_forward(res, "c", 1); break;
      case 'I': {  // the nonce-free INFO on this connection (no fd, nonce 0, incarnation 0), forward its answer
        kid_send(s, GL_U_INFO, 0, rank, 0, 0, nullptr, 0, -1);
        const ssize_t n = recv(s, buf, sizeof(buf), 0);
        kid_forward(res, buf, n > 0 ? (uint32_t)n : 0);
        break;
      }
      default: break;
    }
  }
}
static Kid spawn_kid(int mode, int32_t rank, uint32_t inc, uint64_t nonce) {
  int c[2], r[2];
  if (pipe(c) != 0 || pipe(r) != 0) abort();
  fflush(nullptr);
  const pid_t p = fork();
  if (p == 0) {
    for (int fd = 3; fd < 1024; fd++)
      if (fd != c[0] && fd != r[1]) close(fd);
    kid_main(c[0], r[1], mode, rank, inc, nonce);
    _exit(0);
  }
  close(c[0]);
  close(r[1]);
  Kid k;
  k.pid = p;
  k.cmd = c[1];
  k.res = r[0];
  fcntl(k.res, F_SETFL, O_NONBLOCK);
  return k;
}
static void kid_cmd(Kid& k, char op) {
  if (write(k.cmd, &op, 1) != 1) fprintf(stderr, "kid_cmd failed\n");
}
// Wait for the kid's next forwarded message while the launcher runs.
static std::vector<uint8_t> kid_res(L& l, Kid& k, int ms = 3000) {
  std::vector<uint8_t> out;
  uint32_t n = 0;
  size_t got = 0;
  bool haveLen = false;
  const double end = now_ms() + ms;
  while (now_ms() < end) {
    if (l.c) gl_core_step(l.c, 1);
    else usleep(1000);
    if (!haveLen) {
      const ssize_t r = read(k.res, ((uint8_t*)&n) + got, 4 - got);
      if (r > 0) got += (size_t)r;
      if (got == 4) {
        haveLen = true;
        out.resize(n);
        got = 0;
        if (n == 0) return out;
      }
    } else {
      const ssize_t r = read(k.res, out.data() + got, n - got);
      if (r > 0) got += (size_t)r;
      if (got == n) return out;
    }
  }
  out.clear();
  out.push_back(0xee);  // timeout marker (no real message is 1 byte except the acks)
  return out;
}
static const glUnixMsg* as_u(const std::vector<uint8_t>& v) {
  return v.size() >= sizeof(glUnixMsg) ? (const glUnixMsg*)v.data() : nullptr;
}
static glUHelloAck ack_of(const std::vector<uint8_t>& v) {
  glUHelloAck a;
  memset(&a, 0, sizeof(a));
  a.status = 99;
  const glUnixMsg* u = as_u(v);
  if (u && u->h.kind == GL_U_HELLO_ACK) memcpy(&a, u->body, sizeof(a));
  return a;
}
static uint32_t ack_reason(const std::vector<uint8_t>& v) {
  const glUnixMsg* u = as_u(v);
  return u ? u->h.reason : 999;
}
static std::vector<pid_t> gKids;
static Kid kid_registered(L& l, int mode, int32_t rank, uint32_t inc, uint64_t nonce, uint32_t* status = nullptr,
                          uint32_t* reason = nullptr) {
  Kid k = spawn_kid(mode, rank, inc, nonce);
  gKids.push_back(k.pid);
  std::vector<uint8_t> a = kid_res(l, k);
  if (status) *status = ack_of(a).status;
  if (reason) *reason = ack_reason(a);
  return k;
}
static void reap(Kid& k) {
  if (k.pid > 0) {
    kill(k.pid, SIGKILL);  // the test's own children only
    waitpid(k.pid, nullptr, 0);
  }
  if (k.cmd >= 0) close(k.cmd);
  if (k.res >= 0) close(k.res);
  k.pid = -1;
  k.cmd = k.res = -1;
}
static bool entry(L& l, uint64_t nonce, int32_t rank, int kind, uint32_t inc, glEntryView* v) {
  return gl_core_entry(l.c, nonce, rank, kind, inc, v) == 1;
}

// ------------------------------------------------------------------------------------------------ 0. pidfd facts

static void test_pidfd_facts() {
  // (1) a non-leader thread's TID is refused (no PIDFD_THREAD on 5.15)
  {
    int r[2];
    if (pipe(r) != 0) abort();
    const pid_t c = fork();
    if (c == 0) {
      pthread_t t;
      pthread_create(&t, nullptr, kid_thread, nullptr);
      const pid_t tid = (pid_t)syscall(SYS_gettid);
      (void)tid;
      usleep(100000);
      _exit(0);
    }
    usleep(50000);
    char d[64];
    snprintf(d, sizeof(d), "/proc/%d/task", (int)c);
    int other = -1;
    for (int tries = 0; tries < 50 && other < 0; tries++) {
      char cmdline[96];
      snprintf(cmdline, sizeof(cmdline), "ls %s", d);
      FILE* q = popen(cmdline, "r");
      int tid;
      while (q && fscanf(q, "%d", &tid) == 1)
        if (tid != c) other = tid;
      if (q) pclose(q);
      if (other < 0) usleep(2000);
    }
    errno = 0;
    const int f = sys_pidfd_open(other);
    const int err = errno;
    CHECK(other > 0 && f == -1 && err == EINVAL);
    printf("FACT pidfd_open(non-leader tid) = %d errno=%s\n", f, strerror(err));
    if (f >= 0) close(f);
    waitpid(c, nullptr, 0);
    close(r[0]);
    close(r[1]);
  }
  // (2) the leader exits (pthread_exit), another thread lives 300 ms: /proc shows Z, the pidfd is not readable until
  //     the last thread ends; (3) it is readable before the reap; (4) a signal to that zombie returns 0; after the reap
  //     ESRCH and fdinfo Pid: -1
  {
    int r[2];
    if (pipe(r) != 0) abort();
    const pid_t c = fork();
    if (c == 0) {
      pthread_t t;
      pthread_create(&t, nullptr, kid_thread_exit, nullptr);
      if (write(r[1], "t", 1) != 1) _exit(9);
      pthread_exit(nullptr);
    }
    const int fd = sys_pidfd_open(c);
    char b;
    if (read(r[0], &b, 1) != 1) abort();
    const double t0 = now_ms();
    usleep(100000);
    const char st = proc_state(c);
    const bool rd100 = readable(fd);
    CHECK(st == 'Z');
    CHECK(!rd100);
    while (!readable(fd) && now_ms() - t0 < 3000) usleep(500);
    const double t1 = now_ms() - t0;
    CHECK(t1 >= 250);
    siginfo_t si;
    memset(&si, 0, sizeof(si));
    const int w = waitid(P_PID, (id_t)c, &si, WEXITED | WNOHANG | WNOWAIT);
    CHECK(w == 0 && si.si_pid == c);  // exited, not reaped
    const int z = sys_pidfd_signal(fd, SIGKILL);
    CHECK(z == 0);
    printf("FACT leader pthread_exit + thread 300 ms: /proc state %c at +100 ms, pidfd readable %d at +100 ms, "
           "readable at +%.1f ms; zombie: signal rc %d\n",
           st, (int)rd100, t1, z);
    waitpid(c, nullptr, 0);
    errno = 0;
    const int a = sys_pidfd_signal(fd, SIGKILL);
    const int err = errno;
    CHECK(a == -1 && err == ESRCH);
    const int fp = gl_pidfd_pid(fd);
    CHECK(fp == -1);
    printf("FACT after reap: pidfd_send_signal rc %d errno=%s, fdinfo Pid %d\n", a, strerror(err), fp);
    close(fd);
    close(r[0]);
    close(r[1]);
  }
  // (5) SIGKILL through a pidfd reaches a stopped process
  {
    const pid_t c = fork();
    if (c == 0)
      for (;;) pause();
    const int fd = sys_pidfd_open(c);
    kill(c, SIGSTOP);
    for (int i = 0; i < 200 && proc_state(c) != 'T'; i++) usleep(1000);
    const char st = proc_state(c);
    const double t0 = now_ms();
    const int rc = sys_pidfd_signal(fd, SIGKILL);
    while (!readable(fd) && now_ms() - t0 < 2000) usleep(100);
    const double dt = now_ms() - t0;
    CHECK(st == 'T' && rc == 0 && readable(fd));
    printf("FACT stopped (state %c) process: SIGKILL through its pidfd rc %d, readable after %.2f ms\n", st, rc, dt);
    waitpid(c, nullptr, 0);
    close(fd);
  }
  // (6) a pidfd is a "anon_inode:[pidfd]" whose fdinfo names the pid; another fd is not one
  {
    const int fd = sys_pidfd_open(getpid());
    CHECK(gl_pidfd_pid(fd) == getpid());
    int p[2];
    if (pipe(p) != 0) abort();
    CHECK(gl_pidfd_pid(p[0]) == -2);
    close(p[0]);
    close(p[1]);
    close(fd);
  }
}

// ------------------------------------------------------------------------------------------------ 1. registration

static const uint64_t N1 = 0x1111222233334444ull, N2 = 0x5555666677778888ull;

static void test_registration() {
  L l = mk_launcher(7, getuid());
  const int hb = pair_rank(l, 1, 0, N1);
  const int hx = pair_rank(l, 0, 0, N2);  // another communicator
  uint32_t st = 9, why = 0;
  Kid o = kid_registered(l, K_REGISTER, 3, 0, N1, &st, &why);
  CHECK(st == GL_UA_OK);
  glEntryView v;
  CHECK(entry(l, N1, 3, 1, 0, &v));
  CHECK(v.pid == o.pid);
  CHECK(gl_pidfd_pid(v.pidfd) == o.pid);  // the launcher holds the child's own pidfd (SCM_RIGHTS)
  const glMsg* n = last_kind(l, hb, GL_K_REG_NOTE);
  CHECK(n && n->h.rank == 3);
  glRegNoteBody nb;
  memcpy(&nb, n ? n->body : (const uint8_t*)"", sizeof(nb));
  CHECK(n && nb.regState == GL_RS_ALIVE && nb.regInc == 0);
  CHECK(count_kind(l, hx, GL_K_REG_NOTE) == 0);  // only that communicator's ranks
  // the HELLO_ACK content
  {
    Kid k = spawn_kid(K_REGISTER, 2, 0, N1);
    gKids.push_back(k.pid);
    std::vector<uint8_t> a = kid_res(l, k);
    glUHelloAck ha = ack_of(a);
    CHECK(ha.status == GL_UA_OK && ha.node == 7 && ha.qkey == 0x1234567 && ha.ud.qpn == 4242 &&
          ha.ud.psn == 0x1234567 && ha.ud.version == GL_EP_VERSION && ha.ud.qpType == GL_QPT_UD);
    CHECK(ha.page.rkey == 0x9a9e && ha.page.len == 4096 && ha.pageSlot < (uint32_t)GL_PAGE_REGS);
    reap(k);
    pump(l, 5);
  }
  // refusals: not a pidfd, no fd, two fds, another process's pidfd
  Kid b1 = kid_registered(l, K_BADFD, 4, 0, N1, &st, &why);
  CHECK(st == GL_UA_REFUSED && why == GL_R_BAD_FD);
  Kid b2 = kid_registered(l, K_NOFD, 4, 0, N1, &st, &why);
  CHECK(st == GL_UA_REFUSED && why == GL_R_BAD_FD);
  Kid b3 = kid_registered(l, K_TWOFD, 4, 0, N1, &st, &why);
  CHECK(st == GL_UA_REFUSED && why == GL_R_BAD_FD);
  Kid b4 = kid_registered(l, K_OTHERPID, 4, 0, N1, &st, &why);
  CHECK(st == GL_UA_REFUSED && why == GL_R_PID_MISMATCH);
  CHECK(!entry(l, N1, 4, 1, 0xffffffffu, &v));
  // page words: rank 3's registration slot says ALIVE incarnation 0
  const glPage* pg = gl_core_page(l.c);
  int slot3 = -1;
  for (int i = 0; i < GL_PAGE_REGS; i++)
    if (pg->reg[i].nonce == N1 && gl_page_word_rank(pg->reg[i].reg) == 3) slot3 = i;
  CHECK(slot3 >= 0 && pg->reg[slot3].reg == gl_page_word(GL_RS_ALIVE, 3, 0));
  CHECK(pg->magicVer == (((uint64_t)GL_PAGE_MAGIC << 32) | ((uint64_t)GL_WIRE_VERSION << 16) | GL_PAGE_LAYOUT));
  const uint64_t beat0 = pg->beat;
  pump(l, 30);
  CHECK(pg->beat > beat0);
  reap(o);
  reap(b1);
  reap(b2);
  reap(b3);
  reap(b4);
  rm_launcher(l);
  // another uid: everything refused
  L u = mk_launcher(7, getuid() + 1);
  Kid ku = kid_registered(u, K_REGISTER, 3, 0, N1, &st, &why);
  CHECK(st == GL_UA_REFUSED && why == GL_R_UID);
  CHECK(!entry(u, N1, 3, 1, 0xffffffffu, &v));
  reap(ku);
  rm_launcher(u);
}

// ------------------------------------------------------------------------------------------------ 2. EXITED, LEFT

static void test_exit_and_left() {
  L l = mk_launcher(1, getuid());
  const int hb = pair_rank(l, 1, 0, N1), hc = pair_rank(l, 0, 0, N1), hx = pair_rank(l, 0, 0, N2);
  Kid o = kid_registered(l, K_REGISTER, 3, 0, N1);
  glEntryView v;
  CHECK(entry(l, N1, 3, 1, 0, &v));
  const int heldFd = v.pidfd;
  const unsigned closed0 = gl_core_stats(l.c)->nPidfdClosed;
  kid_cmd(o, 'x');
  CHECK(pump_until(l, [&] { return count_kind(l, hb, GL_K_EXITED) == 1; }));
  CHECK(count_kind(l, hc, GL_K_EXITED) == 1);  // every rank of that nonce
  CHECK(count_kind(l, hx, GL_K_EXITED) == 0);  // not another communicator
  const glMsg* e = last_kind(l, hb, GL_K_EXITED);
  CHECK(e && e->h.rank == 3 && e->h.incarnation == 0 && e->h.reason == GL_R_SELF_EXIT);
  uint32_t how = 0;
  CHECK(gl_core_tomb(l.c, N1, 3, 0, &how) && how == GL_K_EXITED);
  CHECK(!entry(l, N1, 3, 1, 0xffffffffu, &v));
  CHECK(gl_core_stats(l.c)->nPidfdClosed == closed0 + 1);
  CHECK(fcntl(heldFd, F_GETFD) == -1 || gl_pidfd_pid(heldFd) != o.pid);
  reap(o);
  // LEAVING then an immediate exit: always LEFT, never EXITED (the queued LEAVING is read before the exit is judged)
  int lefts = 0, exits = 0;
  for (int i = 0; i < 20; i++) {
    const unsigned e0 = gl_core_stats(l.c)->nExited, l0 = gl_core_stats(l.c)->nLeft;
    Kid k = kid_registered(l, K_REGISTER, 10 + i, 0, N1);
    kid_cmd(k, 'L');
    pump_until(l, [&] { return gl_core_stats(l.c)->nExited + gl_core_stats(l.c)->nLeft > e0 + l0; });
    lefts += gl_core_stats(l.c)->nLeft - l0;
    exits += gl_core_stats(l.c)->nExited - e0;
    reap(k);
  }
  CHECK(lefts == 20 && exits == 0);
  printf("INFO LEAVING then exit at once: LEFT %d/20, EXITED %d/20\n", lefts, exits);
  // LEAVING, the process lives on, exits later: LEFT
  Kid k2 = kid_registered(l, K_REGISTER, 40, 0, N1);
  kid_cmd(k2, 'l');
  pump_until(l, [&] { return entry(l, N1, 40, 1, 0, &v) && v.leaving; });
  CHECK(v.leaving);
  pump(l, 30);
  kid_cmd(k2, 'x');
  CHECK(pump_until(l, [&] { return gl_core_tomb(l.c, N1, 40, 0, &how); }));
  CHECK(how == GL_K_LEFT);
  reap(k2);
  // LEAVING on a connection that is not the registering one: ignored; the exit is EXITED
  Kid k3 = kid_registered(l, K_REGISTER, 41, 0, N1);
  kid_cmd(k3, 'V');
  kid_res(l, k3);
  pump(l, 10);
  CHECK(entry(l, N1, 41, 1, 0, &v) && !v.leaving);
  kid_cmd(k3, 'x');
  CHECK(pump_until(l, [&] { return gl_core_tomb(l.c, N1, 41, 0, &how); }));
  CHECK(how == GL_K_EXITED);
  reap(k3);
  // the registering connection closes, the process lives: the entry stays (it lives as long as its pidfd)
  Kid k4 = kid_registered(l, K_REGISTER, 42, 0, N1);
  kid_cmd(k4, 'C');
  kid_res(l, k4);
  CHECK(pump_until(l, [&] { return entry(l, N1, 42, 1, 0, &v) && v.conn == -1; }));
  kid_cmd(k4, 'x');
  CHECK(pump_until(l, [&] { return gl_core_tomb(l.c, N1, 42, 0, &how); }));
  CHECK(how == GL_K_EXITED);
  reap(k4);
  rm_launcher(l);
  // the test switch: no EXITED (LEFT stays)
  L q = mk_launcher(1, getuid(), 1);
  const int hq = pair_rank(q, 1, 0, N1);
  Kid a = kid_registered(q, K_REGISTER, 3, 0, N1);
  kid_cmd(a, 'x');
  CHECK(pump_until(q, [&] { return gl_core_tomb(q.c, N1, 3, 0, &how); }));
  CHECK(count_kind(q, hq, GL_K_EXITED) == 0);
  Kid bq = kid_registered(q, K_REGISTER, 4, 0, N1);
  kid_cmd(bq, 'L');
  CHECK(pump_until(q, [&] { return count_kind(q, hq, GL_K_LEFT) == 1; }));
  // the switch never drops FENCED (REVIEW2 fix 16): a FENCE of a live process, and of one that ended before it
  Kid fq = kid_registered(q, K_REGISTER, 5, 0, N1);
  rc_in(q, hq, mk(GL_K_FENCE, 5, 0, N1, 1));
  CHECK(pump_until(q, [&] { return count_kind(q, hq, GL_K_FENCED) == 1; }));
  CHECK(last_kind(q, hq, GL_K_FENCED)->h.reason == GL_R_FENCE_KILLED);
  rc_in(q, hq, mk(GL_K_FENCE, 3, 0, N1, 1));  // rank 3 exited above (no EXITED was sent for it)
  CHECK(pump_until(q, [&] { return count_kind(q, hq, GL_K_FENCED) == 2; }));
  CHECK(last_kind(q, hq, GL_K_FENCED)->h.rank == 3 && last_kind(q, hq, GL_K_FENCED)->h.reason == GL_R_ALREADY_EXITED);
  Kid gq = kid_registered(q, K_REGISTER, 6, 0, N1);  // exited, not yet seen, FENCE first in the pass
  const int pf = sys_pidfd_open(gq.pid);
  kid_cmd(gq, 'x');
  for (int i = 0; i < 2000 && !readable(pf); i++) usleep(500);
  rc_in(q, hq, mk(GL_K_FENCE, 6, 0, N1, 1));
  gl_core_step(q.c, 0);
  CHECK(count_kind(q, hq, GL_K_FENCED) == 3 && last_kind(q, hq, GL_K_FENCED)->h.rank == 6);
  CHECK(count_kind(q, hq, GL_K_EXITED) == 0);
  close(pf);
  reap(a);
  reap(bq);
  reap(fq);
  reap(gq);
  rm_launcher(q);
}

// The receiving rank's model (design v2 4.2's last two rows, 5.2): LEFT, or a report of a rank whose BYE arrived, is
// "left", never a hold; an EXITED without BYE is death. The ring BYE and the launcher message are not ordered.
enum { R_NONE = 0, R_EXITED = 1, R_LEFT = 2 };
static int rank_view(bool byeSeen, int report) {  // 0 nothing, 1 left, 2 death (hold)
  if (report == R_LEFT) return 1;
  if (byeSeen) return 1;
  if (report == R_EXITED) return 2;
  return 0;
}
static void test_left_bye_model() {
  // For a leaving rank the launcher's report is LEFT (shown above, 20/20). Every interleaving of the ring's BYE and
  // that report at a survivor: never a hold.
  for (int order = 0; order < 2; order++) {
    bool bye = false;
    int report = R_NONE, worst = 0;
    for (int stepI = 0; stepI < 2; stepI++) {
      if ((stepI == 0) == (order == 0)) bye = true;
      else report = R_LEFT;
      const int vv = rank_view(bye, report);
      if (vv > worst) worst = vv;
    }
    CHECK(worst == 1);
  }
  // A rank that did not leave: EXITED without BYE = death, in either arrival position.
  CHECK(rank_view(false, R_EXITED) == 2);
  CHECK(rank_view(true, R_EXITED) == 1);  // BYE arrived first: the report is a leaving one (design v2 4.2)
}

// ------------------------------------------------------------------------------------------------ 3. FENCE

static void test_fence() {
  L l = mk_launcher(2, getuid());
  const int hb = pair_rank(l, 1, 0, N1), hc = pair_rank(l, 0, 0, N1);
  uint32_t how = 0;
  glEntryView v;
  // (a) live: SIGKILL through its pidfd, FENCED (killed), no EXITED
  {
    Kid o = kid_registered(l, K_REGISTER, 3, 0, N1);
    const size_t s0 = gSignals.size();
    rc_in(l, hb, mk(GL_K_FENCE, 3, 0, N1, 1));
    CHECK(pump_until(l, [&] { return count_kind(l, hc, GL_K_FENCED) == 1; }));
    CHECK(gSignals.size() == s0 + 1 && gSignals.back().pid == o.pid && gSignals.back().sig == SIGKILL);
    const glMsg* f = last_kind(l, hb, GL_K_FENCED);
    CHECK(f && f->h.reason == GL_R_FENCE_KILLED && f->h.rank == 3 && f->h.incarnation == 0);
    CHECK(count_kind(l, hb, GL_K_EXITED) == 0);
    CHECK(gl_core_tomb(l.c, N1, 3, 0, &how) && how == GL_K_FENCED);
    // a FENCE after that: FENCED from the record, no signal
    rc_in(l, hb, mk(GL_K_FENCE, 3, 0, N1, 1));
    pump(l, 5);
    CHECK(count_kind(l, hb, GL_K_FENCED) == 2 && gSignals.size() == s0 + 1);
    reap(o);
  }
  // (b) exited first (EXITED seen), FENCE later: FENCED already exited, no signal
  {
    Kid o = kid_registered(l, K_REGISTER, 4, 0, N1);
    kid_cmd(o, 'x');
    CHECK(pump_until(l, [&] { return gl_core_tomb(l.c, N1, 4, 0, &how); }));
    const size_t s0 = gSignals.size();
    const int f0 = count_kind(l, hb, GL_K_FENCED);
    rc_in(l, hb, mk(GL_K_FENCE, 4, 0, N1, 1));
    pump(l, 5);
    CHECK(count_kind(l, hb, GL_K_FENCED) == f0 + 1 && gSignals.size() == s0);
    const glMsg* f = last_kind(l, hb, GL_K_FENCED);
    CHECK(f && f->h.reason == GL_R_ALREADY_EXITED && f->h.rank == 4);
    reap(o);
  }
  // (c) exited, not yet seen by the launcher, the FENCE is handled first in that pass: FENCED (it replaces EXITED), no
  //     signal
  {
    Kid o = kid_registered(l, K_REGISTER, 5, 0, N1);
    const int pf = sys_pidfd_open(o.pid);
    kid_cmd(o, 'x');
    for (int i = 0; i < 2000 && !readable(pf); i++) usleep(500);
    CHECK(readable(pf));
    const size_t s0 = gSignals.size();
    const size_t r0 = l.t->rc.size();
    rc_in(l, hb, mk(GL_K_FENCE, 5, 0, N1, 1));
    gl_core_step(l.c, 0);  // the transport's events come first in a pass
    std::vector<uint16_t> kinds;
    for (size_t i = r0; i < l.t->rc.size(); i++)
      if (l.t->rc[i].peer == hb && l.t->rc[i].m.h.rank == 5 && l.t->rc[i].m.h.kind != GL_K_REG_NOTE)
        kinds.push_back(l.t->rc[i].m.h.kind);
    CHECK(kinds.size() >= 1 && kinds.back() == GL_K_FENCED);  // one event, one message: no EXITED
    CHECK(std::count(kinds.begin(), kinds.end(), (uint16_t)GL_K_EXITED) == 0);
    CHECK(gSignals.size() == s0);
    const glMsg* f = last_kind(l, hb, GL_K_FENCED);
    CHECK(f && f->h.reason == GL_R_ALREADY_EXITED);
    close(pf);
    reap(o);
  }
  // (d) stopped: SIGKILL reaches it, FENCED
  {
    Kid o = kid_registered(l, K_REGISTER, 6, 0, N1);
    kill(o.pid, SIGSTOP);  // the test's own child
    for (int i = 0; i < 200 && proc_state(o.pid) != 'T'; i++) usleep(1000);
    CHECK(proc_state(o.pid) == 'T');
    rc_in(l, hb, mk(GL_K_FENCE, 6, 0, N1, 1));
    CHECK(pump_until(l, [&] { return gl_core_tomb(l.c, N1, 6, 0, &how); }));
    CHECK(how == GL_K_FENCED);
    const glMsg* f = last_kind(l, hb, GL_K_FENCED);
    CHECK(f && f->h.rank == 6 && f->h.reason == GL_R_FENCE_KILLED);
    reap(o);
  }
  // (e) two FENCEs while it dies: one signal, one FENCED
  {
    Kid o = kid_registered(l, K_REGISTER, 7, 0, N1);
    const size_t s0 = gSignals.size();
    const int f0 = count_kind(l, hb, GL_K_FENCED);
    rc_in(l, hb, mk(GL_K_FENCE, 7, 0, N1, 1));
    rc_in(l, hc, mk(GL_K_FENCE, 7, 0, N1, 0));
    CHECK(pump_until(l, [&] { return gl_core_tomb(l.c, N1, 7, 0, &how); }));
    pump(l, 5);
    CHECK(gSignals.size() == s0 + 1 && count_kind(l, hb, GL_K_FENCED) == f0 + 1);
    reap(o);
  }
  // (f) LEAVING, then FENCE: one FENCED (it replaces LEFT)
  {
    Kid o = kid_registered(l, K_REGISTER, 8, 0, N1);
    kid_cmd(o, 'l');
    pump_until(l, [&] { return entry(l, N1, 8, 1, 0, &v) && v.leaving; });
    const int left0 = count_kind(l, hb, GL_K_LEFT);
    rc_in(l, hb, mk(GL_K_FENCE, 8, 0, N1, 1));
    CHECK(pump_until(l, [&] { return gl_core_tomb(l.c, N1, 8, 0, &how); }));
    CHECK(how == GL_K_FENCED);
    const glMsg* f = last_kind(l, hb, GL_K_FENCED);
    CHECK(f && f->h.rank == 8 && f->h.reason == GL_R_FENCE_KILLED);
    CHECK(count_kind(l, hb, GL_K_LEFT) == left0);
    reap(o);
  }
  // (g) multi-threaded: the leader exits, another thread lives 300 ms. No report while it lives (/proc shows Z, the old
  //     gate would have said "gone"); EXITED when the last thread ends. Then the same with a FENCE in the window.
  {
    Kid o = kid_registered(l, K_REGISTER, 9, 0, N1);
    kid_cmd(o, 'T');
    kid_res(l, o);
    const double t0 = now_ms();
    pump(l, 120);
    const char st = proc_state(o.pid);
    CHECK(st == 'Z');
    CHECK(!gl_core_tomb(l.c, N1, 9, 0, &how));
    CHECK(pump_until(l, [&] { return gl_core_tomb(l.c, N1, 9, 0, &how); }));
    const double dt = now_ms() - t0;
    CHECK(how == GL_K_EXITED && dt >= 250);
    printf("FACT launcher: leader exited, thread alive 300 ms: /proc state %c at +120 ms, EXITED at +%.1f ms\n", st, dt);
    reap(o);
    Kid p = kid_registered(l, K_REGISTER, 11, 0, N1);
    kid_cmd(p, 'T');
    kid_res(l, p);
    pump(l, 50);
    const size_t s0 = gSignals.size();
    const double t1 = now_ms();
    rc_in(l, hb, mk(GL_K_FENCE, 11, 0, N1, 1));
    CHECK(pump_until(l, [&] { return gl_core_tomb(l.c, N1, 11, 0, &how); }));
    const double dt1 = now_ms() - t1;
    CHECK(how == GL_K_FENCED && gSignals.size() == s0 + 1 && dt1 < 200);
    printf("FACT launcher: FENCE of a zombie leader with a live thread: SIGKILL, FENCED after %.2f ms\n", dt1);
    reap(p);
  }
  rm_launcher(l);
}

// ------------------------------------------------------------------------------------------------ 4. foreign pidfds

static void test_no_foreign_signal() {
  L l = mk_launcher(3, getuid());
  const int hb = pair_rank(l, 1, 0, N1);
  Kid o = kid_registered(l, K_REGISTER, 3, 0, N1);
  Kid stranger = spawn_kid(K_NONE, 5, 0, N1);  // forked, connected, never registered
  gKids.push_back(stranger.pid);
  const size_t s0 = gSignals.size();
  const unsigned nak0 = gl_core_stats(l.c)->nFenceNak;
  rc_in(l, hb, mk(GL_K_FENCE, 5, 0, N1, 1));  // a rank nobody registered
  rc_in(l, hb, mk(GL_K_FENCE, 3, 1, N1, 1));  // a future incarnation of a held rank
  rc_in(l, hb, mk(GL_K_FENCE, 3, 0, N2, 1));  // another communicator's nonce (the asker's pairing is N1)
  pump(l, 20);
  CHECK(gSignals.size() == s0);
  CHECK(gl_core_stats(l.c)->nFenceNak == nak0 + 2);
  CHECK(count_kind(l, hb, GL_K_FENCE_NAK) == 3);
  const glMsg* n = last_kind(l, hb, GL_K_FENCE_NAK);
  CHECK(n && n->h.reason == GL_R_NONCE);
  CHECK(proc_state(stranger.pid) != 'Z' && proc_state(stranger.pid) != '-');
  CHECK(proc_state(o.pid) != 'Z' && proc_state(o.pid) != '-');
  glEntryView v;
  CHECK(entry(l, N1, 3, 1, 0, &v) && !v.signalled);
  // a spare that never became the rank: FENCE of its incarnation is not honoured
  Kid s = kid_registered(l, K_SPARE, 3, 1, N1);
  rc_in(l, hb, mk(GL_K_FENCE, 3, 1, N1, 1));
  pump(l, 10);
  CHECK(gSignals.size() == s0);
  // every signal the launcher ever sent in this test binary went to a child it registered
  for (const SigRec& r : gSignals) {
    bool ours = false;
    for (pid_t p : gKids) ours |= p == r.pid;
    CHECK(ours);
  }
  reap(o);
  reap(s);
  reap(stranger);
  rm_launcher(l);
}

// ------------------------------------------------------------------------------------------------ 5. SPAWN

static void test_spawn() {
  L l = mk_launcher(4, getuid());
  const int hb = pair_rank(l, 1, 0, N1);
  rc_in(l, hb, mk(GL_K_SPAWN, 3, 1, N1, 1));
  pump(l, 5);
  const glMsg* r = last_kind(l, hb, GL_K_REFUSED);
  CHECK(r && r->h.sub == GL_K_SPAWN && r->h.reason == GL_R_SPAWN_NOT_BUILT && r->h.rank == 3 && r->h.incarnation == 1);
  CHECK(r && strcmp((const char*)r->body, "spawn not built") == 0);
  CHECK(gl_core_stats(l.c)->nSpawnRefused == 1);
  // an unknown kind and a launcher-to-rank kind sent to the launcher: REFUSED unknown
  glMsg m = mk(GL_K_EXITED, 3, 0, N1, 1);
  rc_in(l, hb, m);
  pump(l, 5);
  r = last_kind(l, hb, GL_K_REFUSED);
  CHECK(r && r->h.sub == GL_K_EXITED && r->h.reason == GL_R_UNKNOWN_KIND);
  rm_launcher(l);
}

// ------------------------------------------------------------------------------------------------ 6. activation

static uint8_t gBlob[3000];
static glMsg mk_activate(int32_t d, uint32_t ni, uint64_t nonce, uint32_t blobLen, uint32_t rkey = 77) {
  glMsg m = mk(GL_K_ACTIVATE, d, ni, nonce, 1);
  glActivateBody b;
  memset(&b, 0, sizeof(b));
  b.record.magic = GL_RS_ACT_MAGIC;
  b.record.version = 2;
  b.record.kind = GL_RS_ACT_ACTIVATE;
  b.record.rank = d;
  b.record.incarnation = ni;
  b.record.nonce = nonce;
  b.record.step = 1234;
  b.blob.addr = (uint64_t)(uintptr_t)gBlob;
  b.blob.rkey = rkey;
  b.blob.len = blobLen;
  memcpy(m.body, &b, sizeof(b));
  m.h.bodyBytes = sizeof(b);
  return m;
}
static uint32_t answer_kind(const glMsg* m) { return m ? m->h.sub : 0; }
// Original (3, 0) killed and seen EXITED; spare (3, 1) said HELLO.
struct Act {
  L l;
  int hb, hc;
  Kid o, s;
};
static Act act_setup(bool spare = true) {
  Act a;
  a.l = mk_launcher(5, getuid());
  for (unsigned i = 0; i < sizeof(gBlob); i++) gBlob[i] = (uint8_t)(i * 7 + 3);
  a.l.t->mem[77] = {gBlob, (uint32_t)sizeof(gBlob)};
  a.hb = pair_rank(a.l, 2, 0, N1);  // the buddy of rank 3 (p xor 1 is 2)
  a.hc = pair_rank(a.l, 0, 0, N1);
  a.o = kid_registered(a.l, K_REGISTER, 3, 0, N1);
  uint32_t st = 9;
  if (spare) {
    a.s = kid_registered(a.l, K_SPARE, 3, 1, N1, &st);
    CHECK(st == GL_UA_OK);
  }
  kid_cmd(a.o, 'x');
  uint32_t how;
  CHECK(pump_until(a.l, [&] { return gl_core_tomb(a.l.c, N1, 3, 0, &how); }));
  return a;
}
// The spare says READY and the launcher has taken it (a READY and an ACTIVATE in the same pass would meet the order
// "transport events first": the ACTIVATE would see REPLAYING and get its one LATER, which other scenes test).
static void spare_ready(Act& a) {
  glEntryView v;
  kid_cmd(a.s, 'R');
  CHECK(pump_until(a.l, [&] { return entry(a.l, N1, 3, 2, 1, &v) && v.sp == GL_SP_READY; }));
}
static void act_done(Act& a) {
  reap(a.o);
  reap(a.s);
  rm_launcher(a.l);
}

static void test_later_then_handover() {
  Act a = act_setup();
  L& l = a.l;
  glEntryView v;
  CHECK(entry(l, N1, 3, 2, 1, &v) && v.sp == GL_SP_REPLAYING);
  rc_in(l, a.hb, mk_activate(3, 1, N1, 300));
  pump(l, 5);
  CHECK(count_kind(l, a.hb, GL_K_ACT_ANSWER) == 1);
  const glMsg* m = last_kind(l, a.hb, GL_K_ACT_ANSWER);
  CHECK(answer_kind(m) == GL_RS_ACT_LATER && m->h.reason == GL_R_SPARE_REPLAYING);
  glActAnswerBody ab;
  memcpy(&ab, m->body, sizeof(ab));
  CHECK(ab.record.rank == 3 && ab.record.incarnation == 1 && ab.record.nonce == N1 && ab.record.step == 1234 &&
        ab.record.kind == GL_RS_ACT_LATER && ab.record.magic == GL_RS_ACT_MAGIC);  // gdakiLnActAnswerOk's echo
  CHECK(ab.spareState == GL_SP_REPLAYING && ab.pageSlot < (uint32_t)GL_PAGE_REGS);
  // the wait is visible to the rank side: the spare word and its age move on the page while the launcher waits
  const glPage* pg = gl_core_page(l.c);
  const uint32_t ps = ab.pageSlot < (uint32_t)GL_PAGE_REGS ? ab.pageSlot : 0;
  CHECK(pg->reg[ps].spare == gl_page_word(GL_SP_REPLAYING, 3, 1));
  CHECK(pg->reg[ps].reg == gl_page_word(GL_RS_EXITED, 3, 0));
  // the hand-over gap: the spare is between replay and Resume; the buddy has no per-attempt timeout, nothing more comes
  const uint64_t beat0 = pg->beat;
  pump(l, 80);
  CHECK(count_kind(l, a.hb, GL_K_ACT_ANSWER) == 1);
  CHECK(entry(l, N1, 3, 2, 1, &v) && v.act == 1 && v.laterSent == 1 && v.spAgeMs >= 80);
  CHECK(pg->beat > beat0 && pg->monoMs - pg->reg[ps].spareSinceMs >= 80);
  // READY: the launcher reads the blob from the buddy's outbox and hands record + blob over
  kid_cmd(a.s, 'R');
  kid_cmd(a.s, 'h');
  std::vector<uint8_t> got = kid_res(l, a.s);
  const glUnixMsg* u = as_u(got);
  CHECK(u && u->h.kind == GL_U_ACT_BYTES && u->h.payloadBytes == 300 && got.size() == sizeof(glUnixMsg) + 300);
  if (u && got.size() == sizeof(glUnixMsg) + 300) {
    glRsActivate rec;
    memcpy(&rec, u->body, sizeof(rec));
    CHECK(rec.kind == GL_RS_ACT_ACTIVATE && rec.rank == 3 && rec.incarnation == 1 && rec.step == 1234);
    CHECK(memcmp(got.data() + sizeof(glUnixMsg), gBlob, 300) == 0);
  }
  CHECK(entry(l, N1, 3, 2, 1, &v) && v.sp == GL_SP_OFFERED);
  CHECK(pg->reg[ps].spare == gl_page_word(GL_SP_OFFERED, 3, 1));
  // the spare accepts: relayed once, final
  kid_cmd(a.s, 'a');
  CHECK(pump_until(l, [&] { return count_kind(l, a.hb, GL_K_ACT_ANSWER) == 2; }));
  m = last_kind(l, a.hb, GL_K_ACT_ANSWER);
  CHECK(answer_kind(m) == GL_RS_ACT_ACCEPTED);
  int laters = 0;
  for (const Sent& s : l.t->rc)
    if (s.peer == a.hb && s.m.h.kind == GL_K_ACT_ANSWER && s.m.h.sub == GL_RS_ACT_LATER) laters++;
  CHECK(laters == 1);
  // a spare's own LATER after the launcher's one is not relayed (still exactly one LATER)
  // (sent before ACCEPTED in the variant below)
  // the FETCH talk: endpoint, READY, DONE
  kid_cmd(a.s, 'E');
  CHECK(pump_until(l, [&] { return count_kind(l, a.hb, GL_K_FETCH_EP) == 1; }));
  m = last_kind(l, a.hb, GL_K_FETCH_EP);
  bool epOk = m && m->h.bodyBytes == GL_FETCH_EP_BYTES;
  for (unsigned i = 0; epOk && i < GL_FETCH_EP_BYTES; i++) epOk = m->body[i] == (uint8_t)('E' + i);
  CHECK(epOk);
  glMsg fr = mk(GL_K_FETCH_READY, 3, 1, N1, 2);
  for (unsigned i = 0; i < GL_FETCH_READY_BYTES; i++) fr.body[i] = (uint8_t)(0x40 + i);
  fr.h.bodyBytes = GL_FETCH_READY_BYTES;
  rc_in(l, a.hb, fr);
  kid_cmd(a.s, 'h');
  got = kid_res(l, a.s);
  u = as_u(got);
  CHECK(u && u->h.kind == GL_U_ACT_TALK && u->h.sub == GL_UT_FETCH_READY && u->h.bodyBytes == GL_FETCH_READY_BYTES &&
        u->body[0] == 0x40 && u->body[GL_FETCH_READY_BYTES - 1] == 0x40 + GL_FETCH_READY_BYTES - 1);
  kid_cmd(a.s, 'D');
  CHECK(pump_until(l, [&] { return count_kind(l, a.hb, GL_K_FETCH_DONE) == 1; }));
  // the FETCH talk of another rank's buddy is not relayed
  rc_in(l, a.hc, fr);
  pump(l, 5);
  // re-registration of the revived process: the pidfd swaps, the HELLO's pidfd is closed
  CHECK(entry(l, N1, 3, 2, 1, &v) && v.sp == GL_SP_ACCEPTED);
  const int oldFd = v.pidfd;
  const unsigned closed0 = gl_core_stats(l.c)->nPidfdClosed;
  kid_cmd(a.s, 'G');
  got = kid_res(l, a.s);
  CHECK(ack_of(got).status == GL_UA_OK);
  glEntryView w;
  CHECK(entry(l, N1, 3, 1, 1, &w) && w.pid == a.s.pid && w.pidfd != oldFd);
  CHECK(gl_pidfd_pid(w.pidfd) == a.s.pid);
  CHECK(fcntl(oldFd, F_GETFD) == -1 || gl_pidfd_pid(oldFd) == -2);
  CHECK(gl_core_stats(l.c)->nPidfdClosed == closed0 + 1 && gl_core_stats(l.c)->nPromoted == 1);
  CHECK(!entry(l, N1, 3, 2, 1, &v));
  const glMsg* n = last_kind(l, a.hb, GL_K_REG_NOTE);
  glRegNoteBody nb;
  memcpy(&nb, n ? n->body : (const uint8_t*)"", sizeof(nb));
  CHECK(n && nb.regState == GL_RS_ALIVE && nb.regInc == 1 && nb.spareState == GL_SP_NONE);
  // the revived rank's exit is an EXITED of incarnation 1
  kid_cmd(a.s, 'x');
  uint32_t how;
  CHECK(pump_until(l, [&] { return gl_core_tomb(l.c, N1, 3, 1, &how); }));
  const glMsg* e = last_kind(l, a.hb, GL_K_EXITED);
  CHECK(how == GL_K_EXITED && e && e->h.incarnation == 1);
  act_done(a);

  // READY before the ACTIVATE: no LATER at all
  Act b = act_setup();
  kid_cmd(b.s, 'R');
  CHECK(pump_until(b.l, [&] { return entry(b.l, N1, 3, 2, 1, &v) && v.sp == GL_SP_READY; }));
  rc_in(b.l, b.hb, mk_activate(3, 1, N1, 64));
  kid_cmd(b.s, 'h');
  got = kid_res(b.l, b.s);
  CHECK(as_u(got) && as_u(got)->h.kind == GL_U_ACT_BYTES);
  CHECK(count_kind(b.l, b.hb, GL_K_ACT_ANSWER) == 0);
  // the spare's own LATER: relayed (none sent yet), then ACCEPTED; one LATER in all
  kid_cmd(b.s, 'z');
  kid_cmd(b.s, 'z');
  kid_cmd(b.s, 'a');
  CHECK(pump_until(b.l, [&] { return count_kind(b.l, b.hb, GL_K_ACT_ANSWER) == 2; }));
  pump(b.l, 10);
  int lat = 0, acc = 0;
  for (const Sent& s : b.l.t->rc)
    if (s.peer == b.hb && s.m.h.kind == GL_K_ACT_ANSWER) {
      lat += s.m.h.sub == GL_RS_ACT_LATER;
      acc += s.m.h.sub == GL_RS_ACT_ACCEPTED;
    }
  CHECK(lat == 1 && acc == 1);
  // a second ACTIVATE of the same (rank, incarnation): REFUSED already offered
  rc_in(b.l, b.hb, mk_activate(3, 1, N1, 64));
  pump(b.l, 5);
  const glMsg* r = last_kind(b.l, b.hb, GL_K_ACT_ANSWER);
  CHECK(answer_kind(r) == GL_RS_ACT_REFUSED && r->h.reason == GL_R_ALREADY_OFFERED);
  act_done(b);
}

static void test_spare_exits_and_refusals() {
  glEntryView v;
  // spare exits before any ACTIVATE: no exit report for it; the ACTIVATE gets REFUSED (spare exited)
  {
    Act a = act_setup();
    const int ex0 = count_kind(a.l, a.hb, GL_K_EXITED);
    kid_cmd(a.s, 'x');
    CHECK(pump_until(a.l, [&] { return entry(a.l, N1, 3, 2, 1, &v) && v.dead; }));
    CHECK(count_kind(a.l, a.hb, GL_K_EXITED) == ex0);
    rc_in(a.l, a.hb, mk_activate(3, 1, N1, 64));
    pump(a.l, 5);
    const glMsg* m = last_kind(a.l, a.hb, GL_K_ACT_ANSWER);
    CHECK(answer_kind(m) == GL_RS_ACT_REFUSED && m->h.reason == GL_R_SPARE_EXITED);
    CHECK(gl_core_stats(a.l.c)->nLater == 0);
    act_done(a);
  }
  // spare exits after the LATER: the final REFUSED follows; one LATER
  {
    Act a = act_setup();
    rc_in(a.l, a.hb, mk_activate(3, 1, N1, 64));
    pump(a.l, 5);
    kid_cmd(a.s, 'x');
    CHECK(pump_until(a.l, [&] { return count_kind(a.l, a.hb, GL_K_ACT_ANSWER) == 2; }));
    const glMsg* m = last_kind(a.l, a.hb, GL_K_ACT_ANSWER);
    CHECK(answer_kind(m) == GL_RS_ACT_REFUSED && m->h.reason == GL_R_SPARE_EXITED);
    CHECK(gl_core_stats(a.l.c)->nLater == 1);
    act_done(a);
  }
  // replay failure after the LATER: REFUSED replay failed
  {
    Act a = act_setup();
    rc_in(a.l, a.hb, mk_activate(3, 1, N1, 64));
    pump(a.l, 5);
    kid_cmd(a.s, 'F');
    CHECK(pump_until(a.l, [&] { return count_kind(a.l, a.hb, GL_K_ACT_ANSWER) == 2; }));
    const glMsg* m = last_kind(a.l, a.hb, GL_K_ACT_ANSWER);
    CHECK(answer_kind(m) == GL_RS_ACT_REFUSED && m->h.reason == GL_R_REPLAY_FAILED);
    act_done(a);
  }
  // the spare refuses after the hand-over: relayed REFUSED, the spare is SIGKILLed after the grace if it stays
  {
    Act a = act_setup();
    spare_ready(a);
    rc_in(a.l, a.hb, mk_activate(3, 1, N1, 64));
    kid_cmd(a.s, 'h');
    kid_res(a.l, a.s);
    const size_t s0 = gSignals.size();
    kid_cmd(a.s, 'r');
    CHECK(pump_until(a.l, [&] { return count_kind(a.l, a.hb, GL_K_ACT_ANSWER) == 1; }));
    const glMsg* m = last_kind(a.l, a.hb, GL_K_ACT_ANSWER);
    CHECK(answer_kind(m) == GL_RS_ACT_REFUSED && m->h.reason == GL_R_SPARE_REFUSED);
    CHECK(pump_until(a.l, [&] { return gSignals.size() == s0 + 1; }, 1500));
    CHECK(gSignals.size() == s0 + 1 && gSignals.back().pid == a.s.pid);
    act_done(a);
  }
  // no spare at all: REFUSED at once (spare_absent_refused), in the same pass
  {
    Act a = act_setup(false);
    rc_in(a.l, a.hb, mk_activate(3, 1, N1, 64));
    gl_core_step(a.l.c, 0);
    const glMsg* m = last_kind(a.l, a.hb, GL_K_ACT_ANSWER);
    CHECK(answer_kind(m) == GL_RS_ACT_REFUSED && m->h.reason == GL_R_NO_SPARE);
    act_done(a);
  }
  // early checks, before any LATER (dynamic review (b) 4): wrong nonce, wrong incarnation, not registered, blob too big,
  // original still alive
  {
    Act a = act_setup();
    glMsg m = mk_activate(3, 1, N2, 64);  // the record's nonce differs from the asker's pairing
    m.h.nonce = N1;                       // (the head's nonce agrees: the record check answers)
    rc_in(a.l, a.hb, m);
    glMsg hm = mk_activate(3, 1, N2, 64);  // the head's nonce differs too: refused before any record check
    rc_in(a.l, a.hb, hm);
    rc_in(a.l, a.hb, mk_activate(3, 2, N1, 64));
    rc_in(a.l, a.hb, mk_activate(9, 1, N1, 64));
    rc_in(a.l, a.hb, mk_activate(3, 1, N1, GL_U_MAX_PAYLOAD + 1));
    pump(a.l, 5);
    std::vector<uint32_t> why;
    for (const Sent& s : a.l.t->rc)
      if (s.peer == a.hb && s.m.h.kind == GL_K_ACT_ANSWER) {
        CHECK(s.m.h.sub == GL_RS_ACT_REFUSED);
        why.push_back(s.m.h.reason);
      }
    CHECK(why.size() == 4 && why[0] == GL_R_NONCE && why[1] == GL_R_INCARNATION && why[2] == GL_R_NOT_REGISTERED &&
          why[3] == GL_R_BLOB_TOO_BIG);
    const glMsg* hr = last_kind(a.l, a.hb, GL_K_REFUSED);
    CHECK(hr && hr->h.sub == GL_K_ACTIVATE && hr->h.reason == GL_R_NONCE);
    CHECK(gl_core_stats(a.l.c)->nLater == 0);
    act_done(a);
    Act b = act_setup();
    Kid o2 = kid_registered(b.l, K_REGISTER, 5, 0, N1);
    Kid s2 = kid_registered(b.l, K_SPARE, 5, 1, N1);
    rc_in(b.l, b.hb, mk_activate(5, 1, N1, 64));
    pump(b.l, 5);
    const glMsg* r = last_kind(b.l, b.hb, GL_K_ACT_ANSWER);
    CHECK(answer_kind(r) == GL_RS_ACT_REFUSED && r->h.reason == GL_R_ORIGINAL_ALIVE);
    reap(o2);
    reap(s2);
    act_done(b);
  }
  // the READ of the blob fails: REFUSED
  {
    Act a = act_setup();
    a.l.t->failRead = true;
    kid_cmd(a.s, 'R');
    pump_until(a.l, [&] { return entry(a.l, N1, 3, 2, 1, &v) && v.sp == GL_SP_READY; });
    rc_in(a.l, a.hb, mk_activate(3, 1, N1, 64));
    CHECK(pump_until(a.l, [&] { return count_kind(a.l, a.hb, GL_K_ACT_ANSWER) == 1; }));
    const glMsg* m = last_kind(a.l, a.hb, GL_K_ACT_ANSWER);
    CHECK(answer_kind(m) == GL_RS_ACT_REFUSED && m->h.reason == GL_R_BLOB_READ_FAILED);
    act_done(a);
  }
}

// The early-answer bound: after the LATER nothing but READY, a failure, the spare's exit or the buddy's ABORT ends it.
static void test_early_answer_bound() {
  Act a = act_setup();
  glEntryView v;
  rc_in(a.l, a.hb, mk_activate(3, 1, N1, 64));
  pump(a.l, 300);  // no READY: no timer of the launcher's own (gin-control has no HELLO or READY limit)
  CHECK(count_kind(a.l, a.hb, GL_K_ACT_ANSWER) == 1);
  CHECK(entry(a.l, N1, 3, 2, 1, &v) && v.sp == GL_SP_REPLAYING && v.spAgeMs >= 300);  // the wait the rank side bounds
  printf("INFO no READY after the LATER: the launcher keeps waiting (spare age %u ms, no answer of its own)\n", v.spAgeMs);
  CHECK(answer_kind(last_kind(a.l, a.hb, GL_K_ACT_ANSWER)) == GL_RS_ACT_LATER);
  // the buddy's hold deadline: ABORT. The spare is told; no answer goes to the buddy; SIGKILL after the grace
  const size_t s0 = gSignals.size();
  rc_in(a.l, a.hb, mk(GL_K_ABORT, 3, 1, N1, 2));
  kid_cmd(a.s, 'h');
  std::vector<uint8_t> got = kid_res(a.l, a.s);
  const glUnixMsg* u = as_u(got);
  CHECK(u && u->h.kind == GL_U_ACT_TALK && u->h.sub == GL_UT_ABORT);
  CHECK(pump_until(a.l, [&] { return entry(a.l, N1, 3, 2, 1, &v) && v.dead; }, 1500));
  CHECK(gSignals.size() == s0 + 1 && gSignals.back().pid == a.s.pid);
  CHECK(count_kind(a.l, a.hb, GL_K_ACT_ANSWER) == 1);
  CHECK(count_kind(a.l, a.hb, GL_K_EXITED) == 1);  // only the original's
  // READY after the ABORT changes nothing
  act_done(a);
}

// The lost ACCEPTED: the buddy gave up (ABORT, or its launcher QP failed) before the spare's ACCEPTED reached it.
static void test_lost_accepted() {
  glEntryView v;
  {
    Act a = act_setup();
    spare_ready(a);
    rc_in(a.l, a.hb, mk_activate(3, 1, N1, 64));
    kid_cmd(a.s, 'h');
    kid_res(a.l, a.s);  // handed over (OFFERED)
    rc_in(a.l, a.hb, mk(GL_K_ABORT, 3, 1, N1, 2));
    gl_core_step(a.l.c, 0);
    kid_cmd(a.s, 'a');  // ACCEPTED after the ABORT
    CHECK(pump_until(a.l, [&] { return gl_core_stats(a.l.c)->nLateAccept == 1; }));
    CHECK(count_kind(a.l, a.hb, GL_K_ACT_ANSWER) == 0);  // never relayed
    kid_cmd(a.s, 'h');
    std::vector<uint8_t> got = kid_res(a.l, a.s);
    CHECK(as_u(got) && as_u(got)->h.sub == GL_UT_ABORT);
    act_done(a);
  }
  // REVIEW_PREP fix 12: after ACCEPTED the buddy's launcher QP fails (a blip): the revived process is not aborted or
  // SIGKILLed; its FETCH endpoint waits in the queue and goes out on the re-paired QP after CONNECTED. Only the buddy's
  // explicit ABORT (or a FENCE) ends an ACCEPTED activation.
  {
    Act a = act_setup();
    spare_ready(a);
    rc_in(a.l, a.hb, mk_activate(3, 1, N1, 64));
    kid_cmd(a.s, 'h');
    kid_res(a.l, a.s);
    kid_cmd(a.s, 'a');
    CHECK(pump_until(a.l, [&] { return count_kind(a.l, a.hb, GL_K_ACT_ANSWER) == 1; }));
    const size_t s0 = gSignals.size();
    glTpEvent e;
    memset(&e, 0, sizeof(e));
    e.type = GL_TP_RC_ERROR;
    e.peer = a.hb;
    a.l.t->in.push_back(e);  // the buddy's launcher QP fails after ACCEPTED
    pump(a.l, 5);
    CHECK(!a.l.t->open[a.hb]);
    kid_cmd(a.s, 'E');  // its FETCH endpoint: queued, not lost
    pump(a.l, 300);     // longer than the grace (200 ms): nothing is signalled
    CHECK(entry(a.l, N1, 3, 2, 1, &v) && v.sp == GL_SP_ACCEPTED && !v.dead);
    CHECK(gSignals.size() == s0 && proc_state(a.s.pid) != 'Z' && proc_state(a.s.pid) != '-');
    glPeerView pv;
    CHECK(gl_core_peer(a.l.c, N1, 2, &pv) && pv.repair == 1 && pv.queued >= 1);
    // the buddy re-pairs (its PAIR of the next generation) and says CONNECTED: the queued FETCH_EP goes out
    const int h2 = pair_rank(a.l, 2, 0, N1, 2, true);
    CHECK(pump_until(a.l, [&] { return count_kind(a.l, h2, GL_K_FETCH_EP) == 1; }));
    // a second blip, then the buddy's explicit ABORT: that one ends it (the spare is told; SIGKILL after the grace)
    memset(&e, 0, sizeof(e));
    e.type = GL_TP_RC_ERROR;
    e.peer = h2;
    a.l.t->in.push_back(e);
    pump(a.l, 5);
    CHECK(entry(a.l, N1, 3, 2, 1, &v) && v.sp == GL_SP_ACCEPTED);
    const int h3 = pair_rank(a.l, 2, 0, N1, 3, true);
    rc_in(a.l, h3, mk(GL_K_ABORT, 3, 1, N1, 2));
    kid_cmd(a.s, 'h');
    std::vector<uint8_t> got = kid_res(a.l, a.s);
    CHECK(as_u(got) && as_u(got)->h.sub == GL_UT_ABORT);
    CHECK(pump_until(a.l, [&] { return gSignals.size() == s0 + 1; }, 1500) && gSignals.back().pid == a.s.pid);
    act_done(a);
  }
}

// REVIEW_PREP fix 10: the blob READ is in flight (the verbs transport's NIC writes into the buffer when it completes).
// An ABORT, the spare's exit or the QP's loss in that window must not free the buffer before the completion (or before
// the QP is closed, after which no write comes). ASan reports a heap-use-after-free on the late write otherwise, and
// LeakSanitizer a buffer never freed.
static void test_abort_during_read() {
  glEntryView v;
  // (1) ABORT while the READ is in flight, then the READ completes into the buffer: no hand-over, no answer
  {
    Act a = act_setup();
    a.l.t->holdReads = true;
    spare_ready(a);
    rc_in(a.l, a.hb, mk_activate(3, 1, N1, 3000));
    pump(a.l, 5);
    CHECK(entry(a.l, N1, 3, 2, 1, &v) && v.act == 2 && a.l.t->reads.size() == 1);  // reading
    rc_in(a.l, a.hb, mk(GL_K_ABORT, 3, 1, N1, 2));
    pump(a.l, 5);
    CHECK(entry(a.l, N1, 3, 2, 1, &v) && v.sp == GL_SP_ABORTED && a.l.t->reads.size() == 1);
    tt_complete_reads(a.l.t);  // the late write: into a buffer that must still be the launcher's
    a.l.t->holdReads = false;
    pump(a.l, 5);
    kid_cmd(a.s, 'h');
    std::vector<uint8_t> got = kid_res(a.l, a.s);
    CHECK(as_u(got) && as_u(got)->h.kind == GL_U_ACT_TALK && as_u(got)->h.sub == GL_UT_ABORT);  // no ACT_BYTES first
    CHECK(count_kind(a.l, a.hb, GL_K_ACT_ANSWER) == 0);
    act_done(a);
  }
  // (2) the spare exits while the READ is in flight: REFUSED (spare exited); the late completion frees the buffer;
  //     then a new HELLO of the same (rank, incarnation) reuses the dead spare's slot
  {
    Act a = act_setup();
    a.l.t->holdReads = true;
    spare_ready(a);
    rc_in(a.l, a.hb, mk_activate(3, 1, N1, 2000));
    pump(a.l, 5);
    kid_cmd(a.s, 'x');
    CHECK(pump_until(a.l, [&] { return count_kind(a.l, a.hb, GL_K_ACT_ANSWER) == 1; }));
    CHECK(answer_kind(last_kind(a.l, a.hb, GL_K_ACT_ANSWER)) == GL_RS_ACT_REFUSED && a.l.t->reads.size() == 1);
    reap(a.s);
    Kid s2 = kid_registered(a.l, K_SPARE, 3, 1, N1);  // the dead spare's slot is reset while its READ is in flight
    CHECK(entry(a.l, N1, 3, 2, 1, &v) && v.sp == GL_SP_REPLAYING && !v.dead);
    tt_complete_reads(a.l.t);
    a.l.t->holdReads = false;
    pump(a.l, 5);
    CHECK(entry(a.l, N1, 3, 2, 1, &v) && v.sp == GL_SP_REPLAYING && v.act == 0);  // the old READ's end changes nothing
    reap(s2);
    act_done(a);
  }
  // (3) the buddy's QP is lost while the READ is in flight: the activation aborts, the QP closes (the transport drops
  //     the READ: no completion, no write) and the buffer goes with the close
  {
    Act a = act_setup();
    a.l.t->holdReads = true;
    spare_ready(a);
    rc_in(a.l, a.hb, mk_activate(3, 1, N1, 1000));
    pump(a.l, 5);
    const int dropped0 = a.l.t->nReadsDropped;
    glTpEvent e;
    memset(&e, 0, sizeof(e));
    e.type = GL_TP_RC_ERROR;
    e.peer = a.hb;
    a.l.t->in.push_back(e);
    pump(a.l, 5);
    CHECK(a.l.t->nReadsDropped == dropped0 + 1 && a.l.t->reads.empty() && !a.l.t->open[a.hb]);
    CHECK(entry(a.l, N1, 3, 2, 1, &v) && v.sp == GL_SP_ABORTED);
    a.l.t->holdReads = false;
    act_done(a);
  }
}

// REVIEW_PREP fix 11: a closed QP's handle is never another QP's. The test transport numbers handles as the verbs
// transport does (a reused slot, a new serial). Events of the old record QP that were queued when the rank re-paired it
// (an RC_RECV and an RC_ERROR) must not reach the new QP in the same slot. The negative control (noSerial: the slot
// number alone, the queued events kept) shows the scene would catch it: there the old error re-pairs the new QP.
static void test_handle_reuse() {
  for (int control = 0; control <= 1; control++) {
    L l = mk_launcher(12, getuid());
    l.t->slotMode = true;
    l.t->noSerial = control == 1;
    glPeerView pv;
    pair_rank(l, 1, 0, N1, 1, false);
    CHECK(gl_core_peer(l.c, N1, 1, &pv));
    const int h1 = pv.recHandle;
    rc_in(l, h1, mk(GL_K_CONNECTED, 1, 0, N1, 1));
    gl_core_step(l.c, 0);
    // one batch of events: the rank's PAIR of generation 2 (it replaces the QP), then the old QP's leftovers (an error
    // and a message, as a CQ drained after the new QP was made would give them)
    glTpEvent e;
    memset(&e, 0, sizeof(e));
    e.type = GL_TP_RC_ERROR;
    e.peer = h1;
    ud_in(l, mk_pair(1, 0, N1, 2, GL_PAIR_RECORD, 222));
    l.t->in.push_back(e);
    rc_in(l, h1, mk(GL_K_SPAWN, 3, 1, N1, 1));
    const unsigned rs0 = gl_core_stats(l.c)->nRepairStarted, sp0 = gl_core_stats(l.c)->nSpawnRefused;
    gl_core_step(l.c, 0);
    CHECK(gl_core_peer(l.c, N1, 1, &pv));
    if (control == 0) {  // a new handle in the old slot: the leftovers reach nothing
      const int h2 = pv.recHandle;
      CHECK(h2 >= 0 && (h2 & 0xff) == (h1 & 0xff) && h2 != h1 && l.t->open[h2] && pv.recGen == 2 && pv.repair == 0 &&
            gl_core_stats(l.c)->nRepairStarted == rs0 && gl_core_stats(l.c)->nSpawnRefused == sp0 && pv.consumed == 0);
    } else {  // the same number: the old QP's error is taken for the new QP's, which is torn down and re-paired
      CHECK(gl_core_stats(l.c)->nRepairStarted == rs0 + 1 && pv.recHandle == -1 && pv.repair == 1);
    }
    rm_launcher(l);
  }
}

// ------------------------------------------------------------------------------------------------ 7. duplicates, swaps

static void test_duplicates_and_swaps() {
  L l = mk_launcher(6, getuid());
  pair_rank(l, 2, 0, N1);
  uint32_t st = 9, why = 0;
  glEntryView v, w;
  Kid o = kid_registered(l, K_REGISTER, 3, 0, N1);
  CHECK(entry(l, N1, 3, 1, 0, &v));
  // the same process, a second connection, the same (rank, incarnation): refused, the first entry intact
  kid_cmd(o, '2');
  std::vector<uint8_t> a = kid_res(l, o);
  CHECK(ack_of(a).status == GL_UA_REFUSED && ack_reason(a) == GL_R_DUPLICATE);
  CHECK(entry(l, N1, 3, 1, 0, &w) && w.pidfd == v.pidfd && w.pid == o.pid);
  // another process with the same (rank, incarnation): refused
  Kid d = kid_registered(l, K_REGISTER, 3, 0, N1, &st, &why);
  CHECK(st == GL_UA_REFUSED && why == GL_R_DUPLICATE);
  // a later incarnation while the older one lives: refused
  Kid d2 = kid_registered(l, K_REGISTER, 3, 1, N1, &st, &why);
  CHECK(st == GL_UA_REFUSED && why == GL_R_OLDER_ALIVE);
  // spares: a second HELLO of the same (rank, incarnation) refused; a wrong incarnation refused
  Kid s = kid_registered(l, K_SPARE, 3, 1, N1, &st);
  CHECK(st == GL_UA_OK);
  kid_cmd(s, '2');
  a = kid_res(l, s);
  CHECK(ack_of(a).status == GL_UA_REFUSED && ack_reason(a) == GL_R_DUPLICATE);
  Kid s2 = kid_registered(l, K_SPARE, 3, 1, N1, &st, &why);
  CHECK(st == GL_UA_REFUSED && why == GL_R_DUPLICATE);
  Kid s3 = kid_registered(l, K_SPARE, 3, 2, N1, &st, &why);
  CHECK(st == GL_UA_REFUSED && why == GL_R_INCARNATION);
  // the spare re-registering before its activation was accepted: refused
  kid_cmd(s, 'G');
  a = kid_res(l, s);
  CHECK(ack_of(a).status == GL_UA_REFUSED && ack_reason(a) == GL_R_SPARE_NOT_ACTIVATED);
  // after (3, 0) ended: a stale re-registration of 0 refused; 1 without an accepted spare... the spare entry exists and
  // is not accepted, so a different process registering (3, 1) is refused (only the activated spare may take it)
  kid_cmd(o, 'x');
  uint32_t how;
  CHECK(pump_until(l, [&] { return gl_core_tomb(l.c, N1, 3, 0, &how); }));
  Kid r0 = kid_registered(l, K_REGISTER, 3, 0, N1, &st, &why);
  CHECK(st == GL_UA_REFUSED && why == GL_R_STALE);
  Kid r1 = kid_registered(l, K_REGISTER, 3, 1, N1, &st, &why);
  CHECK(st == GL_UA_REFUSED && why == GL_R_SPARE_NOT_ACTIVATED);
  // a rank with no spare: the next incarnation registers fresh after the older one ended
  Kid p0 = kid_registered(l, K_REGISTER, 6, 0, N1);
  kid_cmd(p0, 'x');
  CHECK(pump_until(l, [&] { return gl_core_tomb(l.c, N1, 6, 0, &how); }));
  Kid p1 = kid_registered(l, K_REGISTER, 6, 1, N1, &st);
  CHECK(st == GL_UA_OK && entry(l, N1, 6, 1, 1, &v) && v.pid == p1.pid);
  for (Kid* k : {&o, &d, &d2, &s, &s2, &s3, &r0, &r1, &p0, &p1}) reap(*k);
  rm_launcher(l);
}

// ------------------------------------------------------------------------------------------------ 8. pairing

static const glMsg* last_ud(L& l, uint16_t kind) {
  for (size_t i = l.t->ud.size(); i-- > 0;)
    if (l.t->ud[i].second.h.kind == kind) return &l.t->ud[i].second;
  return nullptr;
}
static void test_pairing() {
  L l = mk_launcher(8, getuid());
  Kid o = kid_registered(l, K_REGISTER, 3, 0, N1);
  const size_t ud0 = l.t->ud.size();
  const int h = pair_rank(l, 1, 0, N1, 1, false);  // PAIR (record) only
  CHECK(l.t->ud.size() == ud0 + 1 && l.t->nRcOpen == 1 && l.t->kind[h] == GL_PAIR_RECORD && l.t->connected[h]);
  const glMsg a1 = l.t->ud.back().second;
  glPairAckBody ab;
  memcpy(&ab, a1.body, sizeof(ab));
  glPeerView pv;
  CHECK(gl_core_peer(l.c, N1, 1, &pv));
  CHECK(a1.h.kind == GL_K_PAIR_ACK && a1.h.sub == GL_PAIR_RECORD && ab.status == 0 && ab.gen == 1 &&
        ab.qp.qpn == 5000u + (uint32_t)h && ab.qkey == 0x1234567 && ab.page.rkey == 0x9a9e &&
        ab.creditOff == GL_PAGE_CREDIT_OFF(pv.slot));
  CHECK(l.t->ud.back().first.qpn == 901 && l.t->udQkey.back() == (uint32_t)(N1 & 0x7fffffff));  // the rank's Q_Key
  CHECK(l.t->remote[h].qpn == 100u + 10u + 1u && l.t->remote[h].psn == 0x200000u + 111u);
  CHECK(l.t->credit[h].first.rkey == 0x501 && l.t->credit[h].second == 64 + 8 * 4);  // where its credit word is
  // the same PAIR again: the same answer, no new QP
  pair_rank(l, 1, 0, N1, 1, false);
  CHECK(l.t->ud.size() == ud0 + 2 && l.t->nRcOpen == 1);
  CHECK(memcmp(&l.t->ud.back().second, &a1, sizeof(a1)) == 0);
  // nothing goes on the QP before CONNECTED; queued messages follow it in order
  kid_cmd(o, 'x');
  uint32_t how;
  CHECK(pump_until(l, [&] { return gl_core_tomb(l.c, N1, 3, 0, &how); }));
  CHECK(count_kind(l, h, GL_K_EXITED) == 0);
  rc_in(l, h, mk(GL_K_CONNECTED, 1, 0, N1, 1));
  gl_core_step(l.c, 0);
  CHECK(count_kind(l, h, GL_K_EXITED) == 1);
  // the credit word: every record-QP message taken from the rank is counted on the page, (gen << 32) | count
  const glPage* pg = gl_core_page(l.c);
  CHECK(gl_core_peer(l.c, N1, 1, &pv) && pv.consumed == 1);
  CHECK(pg->credit[pv.slot].nonce == N1 && pg->credit[pv.slot].consumed == ((1ull << 32) | 1u));
  CHECK(pg->credit[pv.slot].peer == ((1ull << 32) | 0u));
  rc_in(l, h, mk(GL_K_SPAWN, 3, 1, N1, 1));
  gl_core_step(l.c, 0);
  CHECK(pg->credit[pv.slot].consumed == ((1ull << 32) | 2u));
  // the liveness-READ QP pairs apart (its own kind and generation) and does not touch the record QP
  const int hp = l.t->nextHandle;
  ud_in(l, mk_pair(1, 0, N1, 1, GL_PAIR_PROBE, 777));
  gl_core_step(l.c, 0);
  const glMsg* pa = last_ud(l, GL_K_PAIR_ACK);
  CHECK(pa && pa->h.sub == GL_PAIR_PROBE && l.t->kind[hp] == GL_PAIR_PROBE && l.t->open[h] && l.t->open[hp]);
  glPairAckBody pb;
  memcpy(&pb, pa->body, sizeof(pb));
  CHECK(pb.qp.qpn == 5000u + (uint32_t)hp && pb.qp.psn != ab.qp.psn);  // its own QP and fresh PSN
  CHECK(pb.qp.version == GL_EP_VERSION && pb.qp.qpType == GL_QPT_RC);
  // the probe QP fails: only it goes; the record QP stays and keeps working
  glTpEvent e;
  memset(&e, 0, sizeof(e));
  e.type = GL_TP_RC_ERROR;
  e.peer = hp;
  l.t->in.push_back(e);
  gl_core_step(l.c, 0);
  CHECK(!l.t->open[hp] && l.t->open[h]);
  CHECK(gl_core_peer(l.c, N1, 1, &pv) && pv.probeHandle == -1 && pv.recHandle == h && pv.connected);
  // re-pair the probe at generation 2: a new QP
  const int hp2 = l.t->nextHandle;
  ud_in(l, mk_pair(1, 0, N1, 2, GL_PAIR_PROBE, 778));
  gl_core_step(l.c, 0);
  CHECK(l.t->open[hp2] && l.t->kind[hp2] == GL_PAIR_PROBE && l.t->open[h]);
  // REVIEW_PREP nit 13: the probe QP of generation 2 is lost; a late copy of its generation-2 PAIR is dropped (no new
  // QP), generation 3 pairs
  {
    memset(&e, 0, sizeof(e));
    e.type = GL_TP_RC_ERROR;
    e.peer = hp2;
    l.t->in.push_back(e);
    gl_core_step(l.c, 0);
    const int nOpen = l.t->nRcOpen;
    ud_in(l, mk_pair(1, 0, N1, 2, GL_PAIR_PROBE, 778));
    gl_core_step(l.c, 0);
    CHECK(l.t->nRcOpen == nOpen && gl_core_peer(l.c, N1, 1, &pv) && pv.probeHandle == -1 && pv.probeGen == 2);
  }
  const int hp3 = l.t->nextHandle;
  ud_in(l, mk_pair(1, 0, N1, 3, GL_PAIR_PROBE, 779));
  gl_core_step(l.c, 0);
  CHECK(l.t->open[hp3] && gl_core_peer(l.c, N1, 1, &pv) && pv.probeHandle == hp3 && pv.probeGen == 3);
  // an older record generation: dropped; a newer one: the old record QP is closed, a new one opened
  const size_t ud1 = l.t->ud.size();
  pair_rank(l, 1, 0, N1, 0, false);
  CHECK(l.t->ud.size() == ud1 && l.t->open[h]);
  const int h2 = pair_rank(l, 1, 0, N1, 2, true);
  CHECK(!l.t->open[h] && l.t->open[h2] && l.t->open[hp3]);
  CHECK(gl_core_peer(l.c, N1, 1, &pv) && pv.recGen == 2 && pv.consumed == 1);  // a new generation counts from 0
  CHECK(pg->credit[pv.slot].consumed == ((2ull << 32) | 1u));
  // the launcher starts the re-pairing when its record QP fails (REVIEW2 block 4: either side starts)
  const unsigned rs0 = gl_core_stats(l.c)->nRepairStarted;
  const int hr = l.t->nextHandle;
  memset(&e, 0, sizeof(e));
  e.type = GL_TP_RC_ERROR;
  e.peer = h2;
  l.t->in.push_back(e);
  gl_core_step(l.c, 0);
  CHECK(gl_core_stats(l.c)->nRepairStarted == rs0 + 1 && !l.t->open[h2] && l.t->open[hr]);
  const glMsg* lp = last_ud(l, GL_K_PAIR);
  glPairBody lb;
  memcpy(&lb, lp ? lp->body : (const uint8_t*)"", sizeof(lb));
  CHECK(lp && lp->h.sub == GL_PAIR_RECORD && lp->h.from == (int32_t)(GL_FROM_LAUNCHER | 8) && lb.gen == 3 &&
        lb.qp.qpn == 5000u + (uint32_t)hr && lb.qkey == 0x1234567 && l.t->ud.back().first.qpn == 901);
  CHECK(!l.t->connected[hr]);  // waits for the rank's PAIR_ACK
  // it resends the same PAIR every 500 ms
  const size_t u2 = l.t->ud.size();
  pump(l, 560);
  CHECK(l.t->ud.size() >= u2 + 1 && memcmp(&l.t->ud.back().second, lp, sizeof(glMsg)) == 0);
  // messages to the rank wait in the queue meanwhile
  rc_in(l, hr, mk(GL_K_CONNECTED, 1, 0, N1, 1));  // nothing arrives on a QP before it is connected; ignored here
  Kid k = kid_registered(l, K_REGISTER, 4, 0, N1);
  CHECK(gl_core_peer(l.c, N1, 1, &pv) && pv.repair == 1 && pv.queued >= 1);
  // the rank's PAIR_ACK: the launcher connects, sends CONNECTED first, then the queue
  glMsg ack = mk(GL_K_PAIR_ACK, 1, 0, N1, 1);
  ack.h.sub = GL_PAIR_RECORD;
  glPairAckBody rb;
  memset(&rb, 0, sizeof(rb));
  rb.gen = 3;
  rb.qp.qpn = 4444;
  rb.qp.psn = 0x31337;
  rb.page.rkey = 0x501;
  rb.creditOff = 72;
  memcpy(ack.body, &rb, sizeof(rb));
  ack.h.bodyBytes = sizeof(rb);
  const size_t r0 = l.t->rc.size();
  ud_in(l, ack);
  gl_core_step(l.c, 0);
  CHECK(l.t->connected[hr] && l.t->remote[hr].qpn == 4444 && gl_core_stats(l.c)->nRepaired == 1);
  CHECK(l.t->rc.size() > r0 && l.t->rc[r0].peer == hr && l.t->rc[r0].m.h.kind == GL_K_CONNECTED);
  CHECK(count_kind(l, hr, GL_K_REG_NOTE) >= 1);
  CHECK(gl_core_peer(l.c, N1, 1, &pv) && pv.repair == 0 && pv.recGen == 3 && pv.queued == 0);
  // both start: the rank's PAIR of the same generation wins over the launcher's own
  memset(&e, 0, sizeof(e));
  e.type = GL_TP_RC_ERROR;
  e.peer = hr;
  l.t->in.push_back(e);
  gl_core_step(l.c, 0);
  CHECK(gl_core_peer(l.c, N1, 1, &pv) && pv.repair == 1 && pv.repairGen == 4);
  const int own = pv.repairHandle;
  const int h4 = pair_rank(l, 1, 0, N1, 4, true);
  CHECK(!l.t->open[own] && l.t->open[h4] && gl_core_peer(l.c, N1, 1, &pv) && pv.repair == 0 && pv.recGen == 4);
  // the revived incarnation pairs again (incarnation 1): new QPs; the old incarnation's PAIR is then stale
  const int h5 = pair_rank(l, 1, 1, N1, 1, true);
  CHECK(!l.t->open[h4] && !l.t->open[hp3] && l.t->open[h5]);
  const size_t ud2 = l.t->ud.size();
  pair_rank(l, 1, 0, N1, 9, false);
  CHECK(l.t->ud.size() == ud2);
  reap(o);
  reap(k);
  rm_launcher(l);
}

// ------------------------------------------------------------------------------------------------ 9. registration oracle

// Today's decision (gdakiCkptOnStable, ln4 14981): armable = allArmable && haveSpare.
static int today_armable(int allArmable, int haveSpare) { return allArmable && haveSpare; }

struct RankSide {  // what a rank learns from its own launcher (and the other launcher's pairing)
  glArmView v;
};
static void view_from(L& l, int h, const std::vector<uint8_t>& helloAck, uint32_t inc, bool otherPaired,
                      bool leaving, glArmView* v) {
  memset(v, 0, sizeof(*v));
  v->inc = inc;
  const glUnixMsg* u = as_u(helloAck);
  glUHelloAck a = ack_of(helloAck);
  v->regAcked = u && u->h.kind == GL_U_HELLO_ACK && a.status == GL_UA_OK;
  v->regAckInc = u ? u->h.incarnation : 0;
  v->ownPaired = h >= 0 && l.t->open[h] && l.t->connected[h];  // PAIR_ACK came; pair_rank sent CONNECTED
  const glMsg* n = h >= 0 ? last_kind(l, h, GL_K_REG_NOTE) : nullptr;
  if (n) {
    glRegNoteBody b;
    memcpy(&b, n->body, sizeof(b));
    v->notedReg = b.regState;
    v->notedInc = b.regInc;
    v->notedSpare = b.spareState;
    v->notedSpareInc = b.spareInc;
  }
  v->allPaired = v->ownPaired && otherPaired;
  v->leaving = leaving;
}
// One check per scene (REVIEW_PREP nit 10: the former four of five per call compared gl_armable with the same expression):
// the scene's ground truth (written by hand from what the scene did) against the launcher's words through the path test,
// and the arming bit against today's decision with that ground truth for both values of allArmable.
static int gOracleScenes = 0;
static void oracle_check(const glArmView& v, int expectPath, const char* scene) {
  gOracleScenes++;
  const int path = gl_path_exists(&v);
  const bool ok = path == expectPath && gl_armable(1, &v) == today_armable(1, expectPath) &&
                  gl_armable(0, &v) == today_armable(0, expectPath);
  CHECK(ok);
  if (!ok) fprintf(stderr, "oracle scene %s: path %d, expected %d\n", scene, path, expectPath);
}
static void test_registration_oracle() {
  L l = mk_launcher(9, getuid());
  glArmView v;
  // S0: registered, paired, CONNECTED, but no spare: no path (REVIEW2 fix 8: a spare-less rank stays fail-fast)
  Kid k = spawn_kid(K_REGISTER, 3, 0, N1);
  gKids.push_back(k.pid);
  std::vector<uint8_t> ack = kid_res(l, k);
  const int h = pair_rank(l, 3, 0, N1);
  view_from(l, h, ack, 0, true, false, &v);
  oracle_check(v, 0, "no spare");
  // S1: its pre-launched spare said HELLO (REPLAYING): path
  Kid sp = spawn_kid(K_SPARE, 3, 1, N1);
  gKids.push_back(sp.pid);
  kid_res(l, sp);
  pump(l, 5);
  view_from(l, h, ack, 0, true, false, &v);
  oracle_check(v, 1, "registered + spare");
  // the page carries the same words a READ of it gives the rank
  {
    const glPage* pg = gl_core_page(l.c);
    glUHelloAck ha = ack_of(ack);
    CHECK(ha.pageSlot < (uint32_t)GL_PAGE_REGS);
    const glPageReg& r = pg->reg[ha.pageSlot < (uint32_t)GL_PAGE_REGS ? ha.pageSlot : 0];
    CHECK(r.nonce == N1 && r.reg == gl_page_word(GL_RS_ALIVE, 3, 0) && r.spare == gl_page_word(GL_SP_REPLAYING, 3, 1));
  }
  // S1b: a HELLO for incarnation 2 while 0 is registered: refused by the launcher (not the next incarnation); the noted
  //      spare stays incarnation 1's: path
  {
    uint32_t st2 = 9;
    Kid bad = kid_registered(l, K_SPARE, 3, 2, N1, &st2);
    pump(l, 5);
    CHECK(st2 == GL_UA_REFUSED);
    view_from(l, h, ack, 0, true, false, &v);
    oracle_check(v, 1, "a HELLO two incarnations ahead is refused");
    reap(bad);
  }
  // S1c: the view of incarnation 1 against the launcher's words for 0 (a stale REGISTER answer): no path
  view_from(l, h, ack, 1, true, false, &v);
  oracle_check(v, 0, "registered incarnation is not the view's");
  // S1d: the spare is READY: still a usable spare: path
  kid_cmd(sp, 'R');
  pump_until(l, [&] { glEntryView w; return entry(l, N1, 3, 2, 1, &w) && w.sp == GL_SP_READY; });
  pump(l, 5);
  view_from(l, h, ack, 0, true, false, &v);
  oracle_check(v, 1, "spare READY");
  // S2: the other launcher not paired yet: no path
  view_from(l, h, ack, 0, false, false, &v);
  oracle_check(v, 0, "other launcher unpaired");
  // S3: leaving: no path
  view_from(l, h, ack, 0, true, true, &v);
  oracle_check(v, 0, "leaving");
  // S4: a refused registration (second connection, same incarnation): no path for that one
  kid_cmd(k, '2');
  std::vector<uint8_t> ack2 = kid_res(l, k);
  view_from(l, h, ack2, 0, true, false, &v);
  oracle_check(v, 0, "refused duplicate");
  // S5: registered but not paired with its own launcher: no path
  Kid k5 = spawn_kid(K_REGISTER, 5, 0, N1);
  gKids.push_back(k5.pid);
  std::vector<uint8_t> ack5 = kid_res(l, k5);
  view_from(l, -1, ack5, 0, true, false, &v);
  oracle_check(v, 0, "unpaired");
  // S6: the spare failed its replay: no path any more
  kid_cmd(sp, 'F');
  pump_until(l, [&] { glEntryView w; return entry(l, N1, 3, 2, 1, &w) && w.sp == GL_SP_FAILED; });
  pump(l, 5);
  view_from(l, h, ack, 0, true, false, &v);
  oracle_check(v, 0, "spare failed");
  // S8: the registered process exited: the launcher says EXITED: no path (a dead rank does not arm)
  kid_cmd(k, 'x');
  uint32_t how;
  pump_until(l, [&] { return gl_core_tomb(l.c, N1, 3, 0, &how); });
  view_from(l, h, ack, 0, true, false, &v);
  oracle_check(v, 0, "exited");
  reap(k);
  reap(k5);
  reap(sp);
  rm_launcher(l);  // the nested scene below runs its own launcher on the same socket path
  // S7: the revived rank: before its re-registration no path; after the swap and a new spare for incarnation 2: path
  {
    Act a = act_setup();
    spare_ready(a);
    rc_in(a.l, a.hb, mk_activate(3, 1, N1, 16));
    kid_cmd(a.s, 'h');
    kid_res(a.l, a.s);
    kid_cmd(a.s, 'a');
    pump_until(a.l, [&] { return count_kind(a.l, a.hb, GL_K_ACT_ANSWER) == 1; });
    const int hr = pair_rank(a.l, 3, 1, N1);  // the revived process pairs (incarnation 1)
    std::vector<uint8_t> none;
    view_from(a.l, hr, none, 1, true, false, &v);  // no REGISTER of incarnation 1 answered yet
    oracle_check(v, 0, "revived before re-registration");
    kid_cmd(a.s, 'G');
    std::vector<uint8_t> ackR = kid_res(a.l, a.s);
    pump(a.l, 5);
    view_from(a.l, hr, ackR, 1, true, false, &v);
    oracle_check(v, 0, "revived, re-registered, no spare for incarnation 2");
    Kid s2 = kid_registered(a.l, K_SPARE, 3, 2, N1);
    pump(a.l, 5);
    view_from(a.l, hr, ackR, 1, true, false, &v);
    oracle_check(v, 1, "revived, re-registered, spare for incarnation 2");
    reap(s2);
    act_done(a);
  }
}

// ------------------------------------------------------------------------------------------------ 10. socket, malformed

static void test_socket_dir() {
  glConfig cfg;
  memset(&cfg, 0, sizeof(cfg));
  TT t;
  t.tp.ops = &tt_ops;
  t.tp.impl = &t;
  cfg.uid = getuid();
  cfg.log = fopen("launcher_unit.log", "a");
  glCore* c = gl_core_new(&cfg, &t.tp);
  char why[256];
  mkdir("glopen", 0755);
  chmod("glopen", 0755);
  CHECK(gl_core_listen(c, "glopen/l.sock", why, sizeof(why)) != 0);  // a group/other-readable directory
  rmdir("glnew");
  CHECK(gl_core_listen(c, "glnew/l.sock", why, sizeof(why)) == 0);  // created 0700
  struct stat st;
  CHECK(stat("glnew", &st) == 0 && (st.st_mode & 0777) == 0700);
  CHECK(stat("glnew/l.sock", &st) == 0 && S_ISSOCK(st.st_mode) && (st.st_mode & 0777) == 0600);
  glCore* c2 = gl_core_new(&cfg, &t.tp);
  CHECK(gl_core_listen(c2, "glnew/l.sock", why, sizeof(why)) != 0);  // another launcher listens there
  CHECK(strstr(why, "another launcher") != nullptr);
  gl_core_free(c);  // closes without unlinking: a stale socket file stays
  CHECK(gl_core_listen(c2, "glnew/l.sock", why, sizeof(why)) == 0);  // stale: replaced
  CHECK(gl_core_listen(c2, "/l.sock", why, sizeof(why)) != 0);
  gl_core_shutdown(c2);
  CHECK(stat("glnew/l.sock", &st) != 0);
  gl_core_free(c2);
  fclose(cfg.log);
  char p[256];
  CHECK(gl_default_sock_path(p, sizeof(p)) == 0 && strstr(p, "launcher.sock") != nullptr);
}

static void test_malformed() {
  L l = mk_launcher(10, getuid());
  const int s = kid_connect();  // the test process itself as a peer
  CHECK(s >= 0);
  const unsigned bad0 = gl_core_stats(l.c)->nBadMsg;
  // short message
  char shortMsg[10] = {0};
  CHECK(send(s, shortMsg, sizeof(shortMsg), 0) == 10);
  // bad magic
  glUnixMsg u;
  memset(&u, 0, sizeof(u));
  u.h.magic = 0xdeadbeef;
  CHECK(send(s, &u, sizeof(u), 0) == (ssize_t)sizeof(u));
  // payload on a kind that carries none
  std::vector<uint8_t> big(sizeof(glUnixMsg) + 16, 0);
  glUnixMsg* b = (glUnixMsg*)big.data();
  b->h.magic = GL_U_MAGIC;
  b->h.version = GL_WIRE_VERSION;
  b->h.kind = GL_U_LEAVING;
  b->h.payloadBytes = 16;
  CHECK(send(s, big.data(), big.size(), 0) == (ssize_t)big.size());
  // a launcher-only kind
  memset(&u, 0, sizeof(u));
  u.h.magic = GL_U_MAGIC;
  u.h.version = GL_WIRE_VERSION;
  u.h.kind = GL_U_ACT_BYTES;
  CHECK(send(s, &u, sizeof(u), 0) == (ssize_t)sizeof(u));
  // talk for a spare from a connection that is not its own
  u.h.kind = GL_U_SPARE_STATUS;
  u.h.sub = GL_US_READY;
  u.h.rank = 3;
  u.h.incarnation = 1;
  u.h.nonce = N1;
  CHECK(send(s, &u, sizeof(u), 0) == (ssize_t)sizeof(u));
  pump(l, 20);
  CHECK(gl_core_stats(l.c)->nBadMsg >= bad0 + 4);
  close(s);
  // a REGISTER whose pidfd is the sender's own (this test process): accepted (the pid check passes); its fd is held
  const int s2 = kid_connect();
  const int pf = sys_pidfd_open(getpid());
  CHECK(kid_send(s2, GL_U_REGISTER, 0, 50, 0, N1, nullptr, 0, pf) == 0);
  close(pf);
  glEntryView v;
  CHECK(pump_until(l, [&] { return entry(l, N1, 50, 1, 0, &v); }));
  CHECK(v.pid == getpid());
  close(s2);
  pump(l, 5);
  CHECK(entry(l, N1, 50, 1, 0, &v) && v.conn == -1);  // the connection closed; the entry stays
  rm_launcher(l);  // shutdown never signals a registered original (only unused spares)
}

// ------------------------------------------------------------------------------------------------ INFO (nonce-free)

static int fd_count() {  // entries of /proc/self/fdinfo (the directory's own fd is counted every time alike)
  DIR* d = opendir("/proc/self/fdinfo");
  if (!d) return -1;
  int n = 0;
  while (struct dirent* e = readdir(d))
    if (e->d_name[0] != '.') n++;
  closedir(d);
  return n;
}
// The next message on the test process's own connection s while the launcher runs; empty on timeout.
static std::vector<uint8_t> self_recv(L& l, int s, int ms = 1000) {
  std::vector<uint8_t> b(sizeof(glUnixMsg) + 64);
  const double end = now_ms() + ms;
  while (now_ms() < end) {
    gl_core_step(l.c, 1);
    const ssize_t n = recv(s, b.data(), b.size(), MSG_DONTWAIT);
    if (n > 0) {
      b.resize((size_t)n);
      return b;
    }
  }
  return {};
}
static bool is_info_ack(const std::vector<uint8_t>& v, int32_t rank, uint32_t status, uint32_t reason,
                        glUHelloAck* out = nullptr) {
  const glUnixMsg* u = as_u(v);
  if (!u || v.size() != sizeof(glUnixMsg)) return false;
  glUHelloAck a;
  memcpy(&a, u->body, sizeof(a));
  if (out) *out = a;
  return u->h.magic == GL_U_MAGIC && u->h.version == GL_WIRE_VERSION && u->h.kind == GL_U_INFO_ACK &&
         u->h.sub == GL_U_INFO && u->h.rank == rank && u->h.incarnation == 0 && u->h.nonce == 0 &&
         u->h.reason == reason && u->h.payloadBytes == 0 && u->h.bodyBytes == sizeof(glUHelloAck) &&
         gl_unix_check(u, v.size()) == GL_R_NONE && a.status == status && a.pageSlot == 0xffffffffu &&
         strcmp(a.why, status == GL_UA_OK ? "ok" : gl_reason_text(reason)) == 0;
}
// No page slot is bound to nonce 0 and nRegs counts only the registered (nonce, rank)s.
static bool page_has_no_info(L& l, uint64_t nRegs) {
  const glPage* pg = gl_core_page(l.c);
  int bound = 0;
  for (int i = 0; i < GL_PAGE_REGS; i++)
    if (pg->reg[i].nonce != 0) bound++;
  return pg->nRegs == nRegs && bound == (int)nRegs;
}

static void test_info() {
  L l = mk_launcher(12, getuid());
  const glStats* st = gl_core_stats(l.c);
  glEntryView v;
  // (1) INFO before any REGISTER, from a forked process on a connection that has said nothing else
  Kid k = spawn_kid(K_NONE, 5, 0, N1);
  gKids.push_back(k.pid);
  const size_t rc0 = l.t->rc.size(), ud0 = l.t->ud.size();
  kid_cmd(k, 'I');
  std::vector<uint8_t> a1 = kid_res(l, k);
  glUHelloAck ia;
  CHECK(is_info_ack(a1, 5, GL_UA_OK, GL_R_NONE, &ia));
  CHECK(st->nInfo == 1 && st->nInfoRefused == 0 && st->nRegistered == 0 && st->nRegRefused == 0 && st->nBadMsg == 0);
  CHECK(!entry(l, 0, 5, 1, 0xffffffffu, &v) && !entry(l, 0, 5, 2, 0xffffffffu, &v) && !entry(l, N1, 5, 1, 0xffffffffu, &v));
  CHECK(page_has_no_info(l, 0));
  CHECK(l.t->rc.size() == rc0 && l.t->ud.size() == ud0);  // nothing to the RNIC side
  // (2) the same connection then REGISTERs: accepted; its HELLO_ACK has the same launcher fields as the INFO_ACK
  kid_cmd(k, 'G');
  std::vector<uint8_t> h1 = kid_res(l, k);
  const glUHelloAck ha = ack_of(h1);
  CHECK(ha.status == GL_UA_OK && ha.pageSlot < (uint32_t)GL_PAGE_REGS);
  CHECK(entry(l, N1, 5, 1, 0, &v) && v.pid == k.pid);
  CHECK(ia.node == ha.node && ia.node == 12 && ia.qkey == ha.qkey && ia.qkey == 0x1234567);
  CHECK(memcmp(&ia.ud, &ha.ud, sizeof(ia.ud)) == 0 && ia.ud.qpn == 4242 && ia.ud.qpType == GL_QPT_UD);
  CHECK(memcmp(&ia.page, &ha.page, sizeof(ia.page)) == 0 && ia.page.len == 4096);
  // (3) INFO after the REGISTER on that connection: answered, the entry and the page as they were
  const int pidfd0 = v.pidfd;
  kid_cmd(k, 'I');
  std::vector<uint8_t> a2 = kid_res(l, k);
  CHECK(is_info_ack(a2, 5, GL_UA_OK, GL_R_NONE));
  CHECK(entry(l, N1, 5, 1, 0, &v) && v.pidfd == pidfd0 && v.conn >= 0 && st->nRegistered == 1 && st->nInfo == 2);
  CHECK(page_has_no_info(l, 1));
  // (4) INFO with a stray fd (a pipe end, then the sender's own pidfd): refused GL_R_BAD_FD, the received fd closed
  const int s = kid_connect();
  CHECK(s >= 0);
  pump(l, 5);
  int pp[2];
  if (pipe(pp) != 0) abort();
  const int pf = sys_pidfd_open(getpid());
  const unsigned closed0 = st->nPidfdClosed;
  const int fds0 = fd_count();
  CHECK(kid_send(s, GL_U_INFO, 0, 7, 0, 0, nullptr, 0, pp[0]) == 0);
  CHECK(is_info_ack(self_recv(l, s), 7, GL_UA_REFUSED, GL_R_BAD_FD));
  CHECK(fd_count() == fds0 && st->nPidfdClosed == closed0 + 1);
  CHECK(kid_send(s, GL_U_INFO, 0, 7, 0, 0, nullptr, 0, pf) == 0);
  CHECK(is_info_ack(self_recv(l, s), 7, GL_UA_REFUSED, GL_R_BAD_FD));
  CHECK(fd_count() == fds0 && st->nPidfdClosed == closed0 + 2);
  CHECK(kid_send(s, GL_U_INFO, 0, 7, 0, 0, nullptr, 0, pp[0], pf) == 0);  // two fds: malformed, still answered
  CHECK(is_info_ack(self_recv(l, s), 7, GL_UA_REFUSED, GL_R_BAD_FD));
  CHECK(fd_count() == fds0);
  CHECK(st->nInfoRefused == 3 && st->nInfo == 2 && st->nRegRefused == 0 && !entry(l, 0, 7, 1, 0xffffffffu, &v) &&
        !entry(l, 0, 7, 2, 0xffffffffu, &v));
  close(pp[0]);
  close(pp[1]);
  close(pf);
  // (5) a body or a nonce: refused GL_R_BAD_MSG (INFO is head only and nonce-free); the same connection still answers
  const char junk[] = "x";
  CHECK(kid_send(s, GL_U_INFO, 0, 7, 0, 0, junk, sizeof(junk), -1) == 0);
  CHECK(is_info_ack(self_recv(l, s), 7, GL_UA_REFUSED, GL_R_BAD_MSG));
  CHECK(kid_send(s, GL_U_INFO, 0, 7, 0, N1, nullptr, 0, -1) == 0);
  {
    std::vector<uint8_t> r = self_recv(l, s);
    const glUnixMsg* u = as_u(r);
    CHECK(u && u->h.kind == GL_U_INFO_ACK && u->h.nonce == N1 && u->h.reason == GL_R_BAD_MSG);  // the head is echoed
  }
  CHECK(kid_send(s, GL_U_INFO, 0, 7, 0, 0, nullptr, 0, -1) == 0);
  CHECK(is_info_ack(self_recv(l, s), 7, GL_UA_OK, GL_R_NONE));
  // (6) an unknown kind 10, and kind 9 sent to the launcher, are dropped as before: no answer
  const unsigned bad0 = st->nBadMsg;
  CHECK(kid_send(s, 10, 0, 7, 0, 0, nullptr, 0, -1) == 0);
  CHECK(kid_send(s, GL_U_INFO_ACK, 0, 7, 0, 0, nullptr, 0, -1) == 0);
  CHECK(self_recv(l, s, 50).empty());
  CHECK(st->nBadMsg == bad0 + 2);
  // (7) the asker closes at once without reading: nothing held, the launcher goes on
  for (int i = 0; i < 5; i++) {
    const int q = kid_connect();
    CHECK(q >= 0 && kid_send(q, GL_U_INFO, 0, 8 + i, 0, 0, nullptr, 0, -1) == 0);
    close(q);
  }
  pump(l, 20);
  CHECK(st->nInfo == 3 + 5);  // the INFO is read before the EOF; its answer finds the peer gone (a log line only)
  CHECK(kid_send(s, GL_U_INFO, 0, 7, 0, 0, nullptr, 0, -1) == 0);
  CHECK(is_info_ack(self_recv(l, s), 7, GL_UA_OK, GL_R_NONE));
  for (int i = 0; i < 5; i++) CHECK(!entry(l, 0, 8 + i, 1, 0xffffffffu, &v) && !entry(l, 0, 8 + i, 2, 0xffffffffu, &v));
  CHECK(page_has_no_info(l, 1) && st->nRegistered == 1 && st->nRegRefused == 0);
  close(s);
  reap(k);
  pump(l, 5);
  rm_launcher(l);
  // (8) another uid: INFO refused GL_R_UID, not counted as a refused registration
  L u = mk_launcher(12, getuid() + 1);
  const int s2 = kid_connect();
  CHECK(s2 >= 0 && kid_send(s2, GL_U_INFO, 0, 3, 0, 0, nullptr, 0, -1) == 0);
  CHECK(is_info_ack(self_recv(u, s2), 3, GL_UA_REFUSED, GL_R_UID));
  CHECK(gl_core_stats(u.c)->nInfoRefused == 1 && gl_core_stats(u.c)->nRegRefused == 0 && page_has_no_info(u, 0));
  close(s2);
  rm_launcher(u);
}

static void test_shutdown_kills_unused_spare() {
  L l = mk_launcher(11, getuid());
  Kid o = kid_registered(l, K_REGISTER, 3, 0, N1);
  Kid s = kid_registered(l, K_SPARE, 3, 1, N1);
  const size_t s0 = gSignals.size();
  gl_core_shutdown(l.c);
  CHECK(gSignals.size() == s0 + 1 && gSignals.back().pid == s.pid);  // the spare only, never the registered original
  int stt = 0;
  CHECK(waitpid(s.pid, &stt, 0) == s.pid && WIFSIGNALED(stt) && WTERMSIG(stt) == SIGKILL);
  s.pid = -1;
  CHECK(proc_state(o.pid) != 'Z' && proc_state(o.pid) != '-');
  gl_core_free(l.c);
  delete l.t;
  reap(o);
  reap(s);
}

// ------------------------------------------------------------------------------------------------ the warm spare

// What a spawned fake spare saw at its start (sent over the test's control socket).
struct FakeRep {
  int32_t pid, sid, ppid;
  int32_t nfds;  // open fds at its start (the /proc/self/fd directory's own fd not counted)
  int32_t stdinNull, stdoutFile, stderrSame, sigpipeDfl, leak, passed;
  uint32_t inc;
  int32_t rank;
  char sock[108];
  char node[16];
  char out[256];  // fd 1's path
};
static const char* kCtl = "glctl.sock";
static const char* kSpareLogs = "sparelogs";

static int fake_spare_main(int argc, char** argv) {
  FakeRep r;
  memset(&r, 0, sizeof(r));
  DIR* d = opendir("/proc/self/fd");
  int n = 0;
  for (struct dirent* e; d && (e = readdir(d));)
    if (e->d_name[0] != '.') n++;
  if (d) closedir(d);
  r.nfds = n - 1;
  if (argc > 2 && strcmp(argv[2], "--fork") == 0) {  // a wrapper that forks and waits, as `timeout` does
    const pid_t p = fork();
    if (p > 0) {
      int st = 0;
      while (waitpid(p, &st, 0) < 0 && errno == EINTR) {
      }
      _exit(WIFEXITED(st) ? WEXITSTATUS(st) : 128 + WTERMSIG(st));
    }
  }
  r.pid = getpid();
  r.sid = getsid(0);
  r.ppid = getppid();
  char b[256];
  ssize_t k = readlink("/proc/self/fd/0", b, sizeof(b) - 1);
  r.stdinNull = k > 0 && (b[k] = 0, strcmp(b, "/dev/null") == 0);
  k = readlink("/proc/self/fd/1", r.out, sizeof(r.out) - 1);
  if (k > 0) r.out[k] = 0;
  struct stat s1, s2;
  r.stdoutFile = fstat(1, &s1) == 0 && S_ISREG(s1.st_mode);
  r.stderrSame = fstat(2, &s2) == 0 && r.stdoutFile && s1.st_ino == s2.st_ino && s1.st_dev == s2.st_dev;
  struct sigaction old;
  r.sigpipeDfl = sigaction(SIGPIPE, nullptr, &old) == 0 && old.sa_handler == SIG_DFL;
  r.leak = getenv("NCCL_GIN_UNIT_LEAK") != nullptr || getenv("GIN_UNIT_LEAK") != nullptr;
  r.passed = getenv("NCCL_GIN_UNIT_PASSED") && strcmp(getenv("NCCL_GIN_UNIT_PASSED"), "yes") == 0;
  const char* v = getenv("NCCL_GIN_RESTORE_SPARE_INC");
  r.inc = v ? (uint32_t)strtoul(v, nullptr, 10) : 0;
  v = getenv("NCCL_GIN_RESTORE_SPARE");
  r.rank = v ? atoi(v) : -1;
  v = getenv(GL_SOCK_ENV);
  snprintf(r.sock, sizeof(r.sock), "%s", v ? v : "");
  v = getenv(GL_NODE_ENV);
  snprintf(r.node, sizeof(r.node), "%s", v ? v : "");
  v = getenv("GLU_NONCE");
  const uint64_t nonce = v ? strtoull(v, nullptr, 16) : 0;
  dprintf(1, "fake spare pid %d incarnation %u: started\n", (int)r.pid, r.inc);
  const int s = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
  struct sockaddr_un a;
  memset(&a, 0, sizeof(a));
  a.sun_family = AF_UNIX;
  snprintf(a.sun_path, sizeof(a.sun_path), "%s", getenv("GLU_CTL") ? getenv("GLU_CTL") : kCtl);
  if (s < 0 || connect(s, (struct sockaddr*)&a, sizeof(a)) != 0) _exit(20);
  if (write(s, &r, sizeof(r)) != (ssize_t)sizeof(r)) _exit(21);
  char plan = 0;
  if (read(s, &plan, 1) != 1) _exit(22);
  switch (plan) {
    case 'h': kid_main(s, s, K_SPARE, r.rank, r.inc, nonce); break;
    case 'n': kid_main(s, s, K_NONE, r.rank, r.inc, nonce); break;
    case 'e': {
      const int u = kid_hello(K_SPARE, r.rank, r.inc, nonce);
      alignas(64) static uint8_t buf[sizeof(glUnixMsg)];
      const ssize_t m = recv(u, buf, sizeof(buf), 0);
      kid_forward(s, buf, m > 0 ? (uint32_t)m : 0);
      _exit(0);
    }
    case 't': {  // sparefix: the replay's first look at the transcript (misc/rs_spike.cc rsBeginComm)
      const char* tp = getenv("NCCL_GIN_RESTORE_REPLAY");
      if (tp && access(tp, R_OK) == 0) {
        kid_main(s, s, K_SPARE, r.rank, r.inc, nonce);
        break;
      }
      dprintf(2, "GIN/RS: replay: cannot open the transcript (errno %d)\n", errno);
      _exit(2);
    }
    default: _exit(0);
  }
  _exit(0);
}

struct SpareHold {  // the spare's argv and env for one launcher (the core keeps the pointers)
  std::vector<std::string> a, e;
  std::vector<char*> av, ev;
};
static std::string gSelf;
static std::vector<pid_t> gSpawned;  // every process the launchers of these scenes spawned
static void spare_hold(SpareHold& h, std::vector<std::string> args, std::vector<std::string> env = {}) {
  h.a = args;
  char nb[64];
  snprintf(nb, sizeof(nb), "GLU_NONCE=%" PRIx64, N1);
  h.e = {"NCCL_GIN_RESTORE_SPARE=3", nb, std::string("GLU_CTL=") + kCtl, "NCCL_GIN_UNIT_PASSED=yes"};
  for (auto& x : env) h.e.push_back(x);
  h.av.clear();
  h.ev.clear();
  for (auto& x : h.a) h.av.push_back((char*)x.c_str());
  h.av.push_back(nullptr);
  for (auto& x : h.e) h.ev.push_back((char*)x.c_str());
  h.ev.push_back(nullptr);
}
static int gCtl = -1;
static void ctl_open() {
  unlink(kCtl);
  gCtl = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
  struct sockaddr_un a;
  memset(&a, 0, sizeof(a));
  a.sun_family = AF_UNIX;
  snprintf(a.sun_path, sizeof(a.sun_path), "%s", kCtl);
  CHECK(gCtl >= 0 && bind(gCtl, (struct sockaddr*)&a, sizeof(a)) == 0 && listen(gCtl, 16) == 0);
}
static void ctl_close() {
  close(gCtl);
  gCtl = -1;
  unlink(kCtl);
}
static L mk_launcher_spare(uint32_t node, SpareHold& h, int helloMs, int respawnMax, FILE* log,
                           const char* waitFor = nullptr) {
  L l;
  l.t = new TT();
  l.t->tp.ops = &tt_ops;
  l.t->tp.impl = l.t;
  glConfig cfg;
  memset(&cfg, 0, sizeof(cfg));
  cfg.node = node;
  cfg.qkey = 0x1234567;
  cfg.uid = getuid();
  cfg.graceMs = 200;
  cfg.log = log;
  cfg.onSignal = on_signal;
  cfg.spareArgv = h.av.data();
  cfg.spareEnv = h.ev.data();
  cfg.spareLogDir = kSpareLogs;
  cfg.spareHelloMs = helloMs;
  cfg.spareRespawnMax = respawnMax;
  cfg.spareWaitFor = waitFor;
  l.c = gl_core_new(&cfg, &l.t->tp);
  char why[256] = {0};
  const int rc = gl_core_listen(l.c, kSock, why, sizeof(why));
  if (rc != 0) fprintf(stderr, "listen: %s\n", why);
  CHECK(rc == 0);
  return l;
}
struct Spawned {
  Kid k;
  FakeRep r;
  bool ok = false;
};
// The next spawned fake spare: its report, then its plan byte. The launcher runs meanwhile.
static Spawned next_spawn(L& l, char plan, int ms = 5000) {
  Spawned s;
  memset(&s.r, 0, sizeof(s.r));
  const double end = now_ms() + ms;
  int fd = -1;
  while (now_ms() < end && fd < 0) {
    gl_core_step(l.c, 1);
    fd = accept4(gCtl, nullptr, nullptr, SOCK_CLOEXEC | SOCK_NONBLOCK);
  }
  if (fd < 0) return s;
  size_t got = 0;
  while (now_ms() < end && got < sizeof(s.r)) {
    gl_core_step(l.c, 1);
    const ssize_t r = read(fd, (char*)&s.r + got, sizeof(s.r) - got);
    if (r > 0) got += (size_t)r;
    else if (r == 0) break;
  }
  if (got != sizeof(s.r) || write(fd, &plan, 1) != 1) {
    close(fd);
    return s;
  }
  s.k.pid = s.r.pid;
  s.k.cmd = s.k.res = fd;
  s.ok = true;
  gSpawned.push_back(s.r.pid);
  return s;
}
static void spawned_close(Spawned& s) {
  if (s.k.cmd >= 0) close(s.k.cmd);
  s.k.cmd = s.k.res = -1;
}
static bool no_spawn_within(L& l, int ms) {  // no fake spare connects within ms
  const double end = now_ms() + ms;
  while (now_ms() < end) {
    gl_core_step(l.c, 1);
    const int fd = accept4(gCtl, nullptr, nullptr, SOCK_CLOEXEC);
    if (fd >= 0) {
      close(fd);
      return false;
    }
  }
  return true;
}
static bool kidv(L& l, unsigned seq, glKidView* v) {
  glKidView a[16];
  const int n = gl_core_kids(l.c, a, 16);
  for (int i = 0; i < n && i < 16; i++)
    if (a[i].seq == seq) return *v = a[i], true;
  return false;
}
static std::string slurp(const char* f) {
  std::string s;
  FILE* x = fopen(f, "r");
  if (!x) return s;
  char b[4096];
  size_t n;
  while ((n = fread(b, 1, sizeof(b), x)) > 0) s.append(b, n);
  fclose(x);
  return s;
}
static int count_str(const std::string& s, const std::string& sub) {
  int n = 0;
  for (size_t p = s.find(sub); p != std::string::npos; p = s.find(sub, p + 1)) n++;
  return n;
}
static int page_slot_of(L& l, uint64_t nonce, int32_t rank) {
  const glPage* p = gl_core_page(l.c);
  for (int i = 0; i < GL_PAGE_REGS; i++)
    if (p->reg[i].nonce == nonce && gl_page_word_rank(p->reg[i].reg) == rank) return i;
  return -1;
}
static uint64_t spare_word(L& l) {
  const int i = page_slot_of(l, N1, 3);
  return i < 0 ? 0 : gl_core_page(l.c)->reg[i].spare;
}
static uint64_t reg_word(L& l) {
  const int i = page_slot_of(l, N1, 3);
  return i < 0 ? 0 : gl_core_page(l.c)->reg[i].reg;
}
// gl_path_exists (unchanged) from rank 3's page words, as its rank side would see them with the rest in place.
static int path_from_page(L& l, uint32_t inc) {
  glArmView v;
  memset(&v, 0, sizeof(v));
  v.inc = inc;
  v.regAcked = 1;
  v.regAckInc = inc;
  v.ownPaired = 1;
  v.notedReg = gl_page_word_state(reg_word(l));
  v.notedInc = gl_page_word_inc(reg_word(l));
  v.notedSpare = gl_page_word_state(spare_word(l));
  v.notedSpareInc = gl_page_word_inc(spare_word(l));
  v.allPaired = 1;
  return gl_path_exists(&v);
}
static bool signals_allowed() {  // every signal any launcher of this binary sent: a forked kid or a spawned process
  for (const SigRec& r : gSignals) {
    bool ours = false;
    for (pid_t p : gKids) ours |= p == r.pid;
    for (pid_t p : gSpawned) ours |= p == r.pid;
    if (!ours) return false;
  }
  return true;
}
static std::string log_name(const char* dir, pid_t p, unsigned seq, uint32_t inc, uint32_t node, int sfx = 0) {
  char b[256], x[8] = "";
  if (sfx) snprintf(x, sizeof(x), "_%d", sfx);
  snprintf(b, sizeof(b), "%s/spare_n%u_s%u_i%u_p%d%s.log", dir, node, seq, inc, (int)p, x);
  return b;
}

static void test_spare_start() {
  for (int wrap = 0; wrap < 2; wrap++) {
    SpareHold h;
    if (wrap) spare_hold(h, {gSelf, "--fake-spare", "--fork"});
    else spare_hold(h, {gSelf, "--fake-spare"});
    ctl_open();
    const char* lname = wrap ? "spare_start_wrap.log" : "spare_start.log";
    FILE* lf = fopen(lname, "w");
    const double t0 = now_ms();
    L l = mk_launcher_spare(20, h, 3000, 3, lf);
    glKidView kv;
    // spawned at the start (the listen), before any rank or spare came
    CHECK(gl_core_kids(l.c, &kv, 1) == 1 && kv.seq == 1 && kv.state == GL_KID_WAIT && kv.inc == 1 && kv.held);
    CHECK(gl_core_stats(l.c)->nSpareSpawned == 1);
    const pid_t P = kv.pid;
    Spawned s = next_spawn(l, 'h');
    CHECK(s.ok);
    if (!s.ok) {
      rm_launcher(l);
      fclose(lf);
      ctl_close();
      continue;
    }
    // what it inherited: a new session, stdin /dev/null, stdout and stderr its own log file, no other fd, SIGPIPE default,
    // none of the launcher's own NCCL_ and GIN_ variables, the --spare-env ones, the launcher's socket, node, incarnation
    if (!wrap) CHECK(s.r.pid == P && s.r.sid == P);
    else CHECK(s.r.pid != P && s.r.sid == P && s.r.ppid == P);
    CHECK(s.r.nfds == 3);
    CHECK(s.r.stdinNull && s.r.stdoutFile && s.r.stderrSame && s.r.sigpipeDfl);
    CHECK(!s.r.leak && s.r.passed && s.r.inc == 1 && s.r.rank == 3);
    CHECK(strcmp(s.r.sock, kSock) == 0 && strcmp(s.r.node, "20") == 0);
    const std::string want = log_name(kSpareLogs, getpid(), 1, 1, 20, wrap);  // the second launcher: the name exists
    CHECK(strstr(s.r.out, want.c_str()) != nullptr);
    std::vector<uint8_t> ack = kid_res(l, s.k);
    CHECK(ack_of(ack).status == GL_UA_OK);
    CHECK(pump_until(l, [&] { return kidv(l, 1, &kv) && kv.state == GL_KID_WARM; }));
    CHECK(kv.helloPid == s.r.pid && gl_core_stats(l.c)->nSpawnedHello == 1);
    CHECK(now_ms() - t0 < 3000);  // HELLO within the bound
    const std::string lg = slurp(lname);
    char line[256];
    snprintf(line, sizeof(line), "spare spawned (spawn 1, incarnation 1, pid %d, why start, log %s)", (int)P,
             want.c_str());
    CHECK(count_str(lg, line) == 1);
    snprintf(line, sizeof(line), "spawned spare said HELLO (spawn 1, incarnation 1, pid %d, hello pid %d, rank 3 "
                                 "incarnation 1, after ", (int)P, (int)s.r.pid);
    CHECK(count_str(lg, line) == 1);
    CHECK(count_str(lg, "warm spare on (command ") == 1);
    char fl[64];
    snprintf(fl, sizeof(fl), "fake spare pid %d incarnation 1: started", (int)s.r.pid);
    CHECK(count_str(slurp(want.c_str()), fl) == 1);  // its own output is in its own log file
    // the page: the spare word is (REPLAYING, 3, 1) from its HELLO on
    CHECK(spare_word(l) == gl_page_word(GL_SP_REPLAYING, 3, 1));
    // SPAWN from a buddy: still REFUSED "spawn not built", nothing spawned
    const int hb = pair_rank(l, 2, 0, N1);
    rc_in(l, hb, mk(GL_K_SPAWN, 3, 2, N1, 2));
    pump(l, 20);
    const glMsg* r = last_kind(l, hb, GL_K_REFUSED);
    CHECK(r && r->h.sub == GL_K_SPAWN && r->h.reason == GL_R_SPAWN_NOT_BUILT);
    CHECK(gl_core_stats(l.c)->nSpareSpawned == 1 && gl_core_kids(l.c, &kv, 1) == 1);
    // shutdown: the unused warm spare is SIGKILLed through its HELLO's pidfd and reaped
    const size_t s0 = gSignals.size();
    gl_core_shutdown(l.c);
    CHECK(gSignals.size() == s0 + 1 && gSignals.back().pid == s.r.pid && gSignals.back().sig == SIGKILL);
    CHECK(gl_core_kids(l.c, &kv, 1) == 0 && proc_state(P) == '-');
    snprintf(line, sizeof(line), "shutdown: spawned process (spawn 1, incarnation 1, pid %d) %s", (int)P,
             wrap ? "exit 137" : "signal 9");
    CHECK(count_str(slurp(lname), line) == 1);
    gl_core_free(l.c);
    delete l.t;
    spawned_close(s);
    fclose(lf);
    ctl_close();
  }
}

static void test_spare_activation_cycle() {
  SpareHold h;
  spare_hold(h, {gSelf, "--fake-spare"});
  ctl_open();
  FILE* lf = fopen("spare_activation.log", "w");
  for (unsigned i = 0; i < sizeof(gBlob); i++) gBlob[i] = (uint8_t)(i * 5 + 1);
  L l = mk_launcher_spare(21, h, 3000, 3, lf);
  l.t->mem[77] = {gBlob, (uint32_t)sizeof(gBlob)};
  const size_t sig0 = gSignals.size();
  glKidView kv;
  CHECK(spare_word(l) == 0);  // before the HELLO: no slot, no spare word
  Spawned s1 = next_spawn(l, 'h');
  CHECK(s1.ok && s1.r.inc == 1);
  CHECK(ack_of(kid_res(l, s1.k)).status == GL_UA_OK);
  CHECK(pump_until(l, [&] { return kidv(l, 1, &kv) && kv.state == GL_KID_WARM; }));
  CHECK(spare_word(l) == gl_page_word(GL_SP_REPLAYING, 3, 1));
  // the original rank registers after its spare (the launcher started first)
  const int hb = pair_rank(l, 2, 0, N1);
  Kid o = kid_registered(l, K_REGISTER, 3, 0, N1);
  CHECK(reg_word(l) == gl_page_word(GL_RS_ALIVE, 3, 0) && path_from_page(l, 0) == 1);
  kid_cmd(o, 'x');
  uint32_t how;
  CHECK(pump_until(l, [&] { return gl_core_tomb(l.c, N1, 3, 0, &how); }));
  kid_cmd(s1.k, 'R');
  CHECK(pump_until(l, [&] { return spare_word(l) == gl_page_word(GL_SP_READY, 3, 1); }));
  rc_in(l, hb, mk_activate(3, 1, N1, 64));
  kid_cmd(s1.k, 'h');
  std::vector<uint8_t> got = kid_res(l, s1.k);
  CHECK(as_u(got) && as_u(got)->h.kind == GL_U_ACT_BYTES);
  CHECK(spare_word(l) == gl_page_word(GL_SP_OFFERED, 3, 1));
  kid_cmd(s1.k, 'a');
  CHECK(pump_until(l, [&] { return count_kind(l, hb, GL_K_ACT_ANSWER) == 1; }));
  CHECK(answer_kind(last_kind(l, hb, GL_K_ACT_ANSWER)) == GL_RS_ACT_ACCEPTED);
  CHECK(spare_word(l) == gl_page_word(GL_SP_ACCEPTED, 3, 1));
  pump(l, 20);
  CHECK(kidv(l, 1, &kv) && kv.accepted && kv.state == GL_KID_WARM && gl_core_stats(l.c)->nSpareSpawned == 1);  // not yet
  kid_cmd(s1.k, 'E');
  CHECK(pump_until(l, [&] { return count_kind(l, hb, GL_K_FETCH_EP) == 1; }));
  CHECK(gl_core_stats(l.c)->nSpareSpawned == 1);
  // the activation's DONE: the next spare, incarnation 2
  kid_cmd(s1.k, 'D');
  Spawned s2 = next_spawn(l, 'h');
  CHECK(count_kind(l, hb, GL_K_FETCH_DONE) == 1);
  CHECK(s2.ok && s2.r.inc == 2 && s2.r.pid != s1.r.pid && s2.r.sid == s2.r.pid);
  CHECK(kidv(l, 1, &kv) && kv.state == GL_KID_USED);
  CHECK(gl_core_stats(l.c)->nSpareActivated == 1);
  std::string lg = slurp("spare_activation.log");
  char line[256];
  snprintf(line, sizeof(line), "spawned spare activated (spawn 1, incarnation 1, pid %d, by DONE): next spare "
                               "incarnation 2", (int)s1.r.pid);
  CHECK(count_str(lg, line) == 1);
  snprintf(line, sizeof(line), "spare spawned (spawn 2, incarnation 2, pid %d, why activated, log ", (int)s2.r.pid);
  CHECK(count_str(lg, line) == 1);
  CHECK(ack_of(kid_res(l, s2.k)).status == GL_UA_OK);
  CHECK(pump_until(l, [&] { return kidv(l, 2, &kv) && kv.state == GL_KID_WARM; }));
  CHECK(spare_word(l) == gl_page_word(GL_SP_REPLAYING, 3, 2));  // the newest spare's word
  // the revived process re-registers: incarnation 1 is the rank, the spare word is incarnation 2 -> the path exists
  kid_cmd(s1.k, 'G');
  CHECK(ack_of(kid_res(l, s1.k)).status == GL_UA_OK);
  CHECK(reg_word(l) == gl_page_word(GL_RS_ALIVE, 3, 1) && spare_word(l) == gl_page_word(GL_SP_REPLAYING, 3, 2));
  CHECK(path_from_page(l, 1) == 1 && path_from_page(l, 0) == 0);
  CHECK(gl_core_stats(l.c)->nSpareSpawned == 2);  // the re-registration after DONE spawns nothing more
  // the second death on the same node: the revived rank (a spawned process) ends -> EXITED of incarnation 1, reaped, no
  // respawn; its spare (incarnation 2) is there
  kid_cmd(s1.k, 'x');
  CHECK(pump_until(l, [&] { return gl_core_tomb(l.c, N1, 3, 1, &how); }));
  const glMsg* e = last_kind(l, hb, GL_K_EXITED);
  CHECK(how == GL_K_EXITED && e && e->h.incarnation == 1);
  CHECK(pump_until(l, [&] { return !kidv(l, 1, &kv); }));
  snprintf(line, sizeof(line), "spawned process ended (spawn 1, incarnation 1, pid %d, exit 0)", (int)s1.r.pid);
  CHECK(count_str(slurp("spare_activation.log"), line) == 1);
  CHECK(gl_core_stats(l.c)->nSpareSpawned == 2 && proc_state(s1.r.pid) == '-');
  // the second activation, ended by the re-registration (no DONE relayed): the next spare, incarnation 3
  kid_cmd(s2.k, 'R');
  CHECK(pump_until(l, [&] { return spare_word(l) == gl_page_word(GL_SP_READY, 3, 2); }));
  rc_in(l, hb, mk_activate(3, 2, N1, 64));
  kid_cmd(s2.k, 'h');
  got = kid_res(l, s2.k);
  CHECK(as_u(got) && as_u(got)->h.kind == GL_U_ACT_BYTES);
  kid_cmd(s2.k, 'a');
  CHECK(pump_until(l, [&] { return count_kind(l, hb, GL_K_ACT_ANSWER) == 2; }));
  kid_cmd(s2.k, 'G');
  CHECK(ack_of(kid_res(l, s2.k)).status == GL_UA_OK);
  Spawned s3 = next_spawn(l, 'h');
  CHECK(s3.ok && s3.r.inc == 3);
  snprintf(line, sizeof(line), "spawned spare activated (spawn 2, incarnation 2, pid %d, by re-registration): next "
                               "spare incarnation 3", (int)s2.r.pid);
  CHECK(count_str(slurp("spare_activation.log"), line) == 1);
  CHECK(ack_of(kid_res(l, s3.k)).status == GL_UA_OK);
  CHECK(pump_until(l, [&] { return spare_word(l) == gl_page_word(GL_SP_REPLAYING, 3, 3); }));
  CHECK(reg_word(l) == gl_page_word(GL_RS_ALIVE, 3, 2) && path_from_page(l, 2) == 1);
  CHECK(gSignals.size() == sig0);  // the whole cycle: no signal
  kid_cmd(s2.k, 'x');
  CHECK(pump_until(l, [&] { return gl_core_tomb(l.c, N1, 3, 2, &how) && !kidv(l, 2, &kv); }));
  rm_launcher(l);  // shutdown: s3, unused, SIGKILLed through its pidfd and reaped
  CHECK(gSignals.size() == sig0 + 1 && gSignals.back().pid == s3.r.pid && proc_state(s3.r.pid) == '-');
  CHECK(signals_allowed());
  reap(o);
  spawned_close(s1);
  spawned_close(s2);
  spawned_close(s3);
  fclose(lf);
  ctl_close();
}

static void test_spare_respawn() {
  // (1) a spare that says HELLO and exits unused: respawned with the same incarnation, at most 3 times in 60 s
  {
    SpareHold h;
    spare_hold(h, {gSelf, "--fake-spare"});
    ctl_open();
    FILE* lf = fopen("spare_respawn.log", "w");
    const size_t sig0 = gSignals.size();
    L l = mk_launcher_spare(22, h, 3000, 3, lf);
    std::vector<pid_t> ps;
    for (int i = 0; i < 4; i++) {
      Spawned s = next_spawn(l, 'e');
      CHECK(s.ok && s.r.inc == 1);
      CHECK(ack_of(kid_res(l, s.k)).status == GL_UA_OK);
      ps.push_back(s.r.pid);
      spawned_close(s);
    }
    CHECK(pump_until(l, [&] { return gl_core_stats(l.c)->spareGaveUp == 1; }));
    CHECK(no_spawn_within(l, 300));
    const glStats* st = gl_core_stats(l.c);
    CHECK(st->nSpareSpawned == 4 && st->nSpareRespawned == 3 && st->nSpareReaped == 4);
    const std::string lg = slurp("spare_respawn.log");
    char line[320];
    for (int i = 0; i < 3; i++) {
      snprintf(line, sizeof(line), "spawned spare exited unused (spawn %d, incarnation 1, pid %d, after HELLO, exit 0): "
                                   "respawn %d of 3 within 60000 ms", i + 1, (int)ps[i], i + 1);
      CHECK(count_str(lg, line) == 1);
    }
    snprintf(line, sizeof(line), "spawned spare exited unused (spawn 4, incarnation 1, pid %d, after HELLO, exit 0): "
                                 "respawn cap 3 within 60000 ms reached; no more spares (STOP_launcher)", (int)ps[3]);
    CHECK(count_str(lg, line) == 1);
    CHECK(count_str(lg, "why respawn") == 3);
    CHECK(spare_word(l) == gl_page_word(GL_SP_FAILED, 3, 1) && path_from_page(l, 0) == 0);
    CHECK(gSignals.size() == sig0);  // they ended by themselves
    for (pid_t p : ps) CHECK(proc_state(p) == '-');
    rm_launcher(l);
    fclose(lf);
    ctl_close();
  }
  // (2) a spawn that ends before its HELLO (q), then an exec failure: both are respawns; cap 1
  {
    SpareHold h;
    spare_hold(h, {gSelf, "--fake-spare"});
    ctl_open();
    FILE* lf = fopen("spare_respawn_q.log", "w");
    L l = mk_launcher_spare(23, h, 3000, 1, lf);
    Spawned s = next_spawn(l, 'q');
    CHECK(s.ok);
    spawned_close(s);
    Spawned t = next_spawn(l, 'q');
    CHECK(t.ok);
    spawned_close(t);
    CHECK(pump_until(l, [&] { return gl_core_stats(l.c)->spareGaveUp == 1; }));
    const std::string lg = slurp("spare_respawn_q.log");
    char line[320];
    snprintf(line, sizeof(line), "(spawn 1, incarnation 1, pid %d, before HELLO, exit 0): respawn 1 of 1", (int)s.r.pid);
    CHECK(count_str(lg, line) == 1);
    snprintf(line, sizeof(line), "(spawn 2, incarnation 1, pid %d, before HELLO, exit 0): respawn cap 1", (int)t.r.pid);
    CHECK(count_str(lg, line) == 1);
    rm_launcher(l);
    fclose(lf);
    ctl_close();
    SpareHold x;
    spare_hold(x, {"./no-such-spare-binary"});
    FILE* lx = fopen("spare_exec_fail.log", "w");
    L m = mk_launcher_spare(24, x, 3000, 1, lx);
    CHECK(pump_until(m, [&] { return gl_core_stats(m.c)->spareGaveUp == 1; }));
    const glStats* st = gl_core_stats(m.c);
    CHECK(st->nSpareSpawned == 2 && st->nSpareExecFailed == 2 && st->nSpareReaped == 2);
    const std::string lgx = slurp("spare_exec_fail.log");
    CHECK(count_str(lgx, "spare exec failed (spawn 1, incarnation 1, pid ") == 1 &&
          count_str(lgx, "No such file or directory") == 2);
    CHECK(count_str(lgx, "before HELLO, exit 127): respawn 1 of 1") == 1 &&
          count_str(lgx, "before HELLO, exit 127): respawn cap 1") == 1);
    rm_launcher(m);
    fclose(lx);
  }
  // (3) the spare ends after ACCEPTED, before DONE and its re-registration: it was the rank (EXITED of its incarnation),
  // so it is no unused spare; the next one is its incarnation + 1 (a respawn of the same incarnation would be stale)
  {
    SpareHold h;
    spare_hold(h, {gSelf, "--fake-spare"});
    ctl_open();
    FILE* lf = fopen("spare_accepted_exit.log", "w");
    L l = mk_launcher_spare(29, h, 3000, 3, lf);
    l.t->mem[77] = {gBlob, (uint32_t)sizeof(gBlob)};
    Spawned s = next_spawn(l, 'h');
    CHECK(s.ok && ack_of(kid_res(l, s.k)).status == GL_UA_OK);
    const int hb = pair_rank(l, 2, 0, N1);
    Kid o = kid_registered(l, K_REGISTER, 3, 0, N1);
    kid_cmd(o, 'x');
    uint32_t how;
    CHECK(pump_until(l, [&] { return gl_core_tomb(l.c, N1, 3, 0, &how); }));
    kid_cmd(s.k, 'R');
    CHECK(pump_until(l, [&] { return spare_word(l) == gl_page_word(GL_SP_READY, 3, 1); }));
    rc_in(l, hb, mk_activate(3, 1, N1, 64));
    kid_cmd(s.k, 'h');
    std::vector<uint8_t> got = kid_res(l, s.k);
    CHECK(as_u(got) && as_u(got)->h.kind == GL_U_ACT_BYTES);
    kid_cmd(s.k, 'a');
    CHECK(pump_until(l, [&] { return count_kind(l, hb, GL_K_ACT_ANSWER) == 1; }));
    kid_cmd(s.k, 'x');
    Spawned t = next_spawn(l, 'h');
    CHECK(t.ok && t.r.inc == 2);
    CHECK(gl_core_tomb(l.c, N1, 3, 1, &how) && how == GL_K_EXITED);
    const std::string lg = slurp("spare_accepted_exit.log");
    char line[320];
    snprintf(line, sizeof(line), "spawned spare ended after ACCEPTED (spawn 1, incarnation 1, pid %d, exit 0)",
             (int)s.r.pid);
    CHECK(count_str(lg, line) == 1);
    snprintf(line, sizeof(line), "spawned spare activated (spawn 1, incarnation 1, pid %d, by exit after ACCEPTED): "
                                 "next spare incarnation 2", (int)s.r.pid);
    CHECK(count_str(lg, line) == 1);
    CHECK(gl_core_stats(l.c)->nSpareRespawned == 0 && gl_core_stats(l.c)->nSpareActivated == 1);
    CHECK(ack_of(kid_res(l, t.k)).status == GL_UA_OK);  // incarnation 2 is not stale after the tomb of 1
    rm_launcher(l);
    reap(o);
    spawned_close(s);
    spawned_close(t);
    fclose(lf);
    ctl_close();
  }
}

static void test_spare_hello_timeout() {
  // (1) no HELLO within the bound: SIGKILL through the spawn's pidfd, one STOP line, one retry that says HELLO
  {
    SpareHold h;
    spare_hold(h, {gSelf, "--fake-spare"});
    ctl_open();
    FILE* lf = fopen("spare_hello_timeout.log", "w");
    const size_t sig0 = gSignals.size();
    const double t0 = now_ms();
    L l = mk_launcher_spare(25, h, 500, 3, lf);
    Spawned s = next_spawn(l, 'n');
    CHECK(s.ok);
    Spawned t = next_spawn(l, 'h');
    const double t1 = now_ms();
    CHECK(t.ok && t.r.inc == 1 && t.r.pid != s.r.pid);
    CHECK(t1 - t0 >= 500 && t1 - t0 < 3000);
    CHECK(gSignals.size() == sig0 + 1 && gSignals[sig0].pid == s.r.pid && gSignals[sig0].sig == SIGKILL &&
          gSignals[sig0].rc == 0);
    CHECK(ack_of(kid_res(l, t.k)).status == GL_UA_OK);
    glKidView kv;
    CHECK(pump_until(l, [&] { return kidv(l, 2, &kv) && kv.state == GL_KID_WARM; }));
    CHECK(kv.retry == 1 && kv.helloPid == t.r.pid);
    CHECK(pump_until(l, [&] { return !kidv(l, 1, &kv); }));
    const std::string lg = slurp("spare_hello_timeout.log");
    char line[320];
    snprintf(line, sizeof(line), "spawned spare said no HELLO within 500 ms (spawn 1, incarnation 1, pid %d): SIGKILL "
                                 "through its pidfd; one retry (STOP_launcher)", (int)s.r.pid);
    CHECK(count_str(lg, line) == 1 && count_str(lg, "STOP_launcher") == 1);
    snprintf(line, sizeof(line), "spare spawned (spawn 2, incarnation 1, pid %d, why hello_retry, log ", (int)t.r.pid);
    CHECK(count_str(lg, line) == 1);
    snprintf(line, sizeof(line), "spawned process ended (spawn 1, incarnation 1, pid %d, signal 9)", (int)s.r.pid);
    CHECK(count_str(slurp("spare_hello_timeout.log"), line) == 1);
    CHECK(gl_core_stats(l.c)->nSpareHelloTimeout == 1 && gl_core_stats(l.c)->spareGaveUp == 0);
    rm_launcher(l);
    spawned_close(s);
    spawned_close(t);
    fclose(lf);
    ctl_close();
  }
  // (2) the retry says no HELLO either: a second line, no more spares
  {
    SpareHold h;
    spare_hold(h, {gSelf, "--fake-spare"});
    ctl_open();
    FILE* lf = fopen("spare_hello_timeout2.log", "w");
    L l = mk_launcher_spare(26, h, 500, 3, lf);
    Spawned s = next_spawn(l, 'n');
    Spawned t = next_spawn(l, 'n');
    CHECK(s.ok && t.ok);
    CHECK(pump_until(l, [&] { return gl_core_stats(l.c)->spareGaveUp == 1; }));
    CHECK(no_spawn_within(l, 700));
    CHECK(gl_core_stats(l.c)->nSpareSpawned == 2 && gl_core_stats(l.c)->nSpareHelloTimeout == 2);
    const std::string lg = slurp("spare_hello_timeout2.log");
    char line[320];
    snprintf(line, sizeof(line), "spawned spare said no HELLO within 500 ms (spawn 2, incarnation 1, pid %d, the retry): "
                                 "SIGKILL through its pidfd; no more spares (STOP_launcher)", (int)t.r.pid);
    CHECK(count_str(lg, line) == 1 && count_str(lg, "STOP_launcher") == 2);
    CHECK(spare_word(l) == 0);  // no HELLO ever: no slot
    rm_launcher(l);
    spawned_close(s);
    spawned_close(t);
    fclose(lf);
    ctl_close();
  }
}

static void test_spare_no_foreign_signal() {
  SpareHold h;
  spare_hold(h, {gSelf, "--fake-spare"});
  ctl_open();
  FILE* lf = fopen("spare_foreign.log", "w");
  L l = mk_launcher_spare(27, h, 500, 3, lf);
  const size_t sig0 = gSignals.size();
  const int hb = pair_rank(l, 2, 0, N1);
  // a process that only connects, and a spare started by someone else for the same (rank, incarnation) as the spawn
  Kid stranger = spawn_kid(K_NONE, 5, 0, N1);
  gKids.push_back(stranger.pid);
  Kid foreign = kid_registered(l, K_SPARE, 3, 1, N1);
  glKidView kv;
  CHECK(kidv(l, 1, &kv) && kv.state == GL_KID_WAIT);  // the foreign HELLO is not taken as the spawned one's
  Spawned s = next_spawn(l, 'n');
  Spawned t = next_spawn(l, 'n');
  CHECK(s.ok && t.ok);
  CHECK(pump_until(l, [&] { return gl_core_stats(l.c)->spareGaveUp == 1; }));
  CHECK(gSignals.size() == sig0 + 2 && gSignals[sig0].pid == s.r.pid && gSignals[sig0 + 1].pid == t.r.pid);
  CHECK(proc_state(stranger.pid) != 'Z' && proc_state(stranger.pid) != '-');
  CHECK(proc_state(foreign.pid) != 'Z' && proc_state(foreign.pid) != '-');
  // FENCE of the spare incarnation (not accepted) and of a rank nobody registered: FENCE_NAK, nothing signalled
  rc_in(l, hb, mk(GL_K_FENCE, 3, 1, N1, 2));
  rc_in(l, hb, mk(GL_K_FENCE, 5, 0, N1, 2));
  pump(l, 20);
  CHECK(count_kind(l, hb, GL_K_FENCE_NAK) == 2 && gSignals.size() == sig0 + 2);
  CHECK(signals_allowed());
  // shutdown: the foreign spare is an unused registered spare (SIGKILL through the pidfd it gave); the stranger is not
  rm_launcher(l);
  CHECK(gSignals.size() == sig0 + 3 && gSignals.back().pid == foreign.pid);
  CHECK(proc_state(stranger.pid) != 'Z' && proc_state(stranger.pid) != '-');
  CHECK(signals_allowed());
  reap(stranger);
  reap(foreign);
  spawned_close(s);
  spawned_close(t);
  fclose(lf);
  ctl_close();
}

// sparefix (smoke a4): the spawn waits for its wait-for; a spawn made after the wait ran out that finds no transcript is
// not counted against the respawn cap; one whose wait was met is.
static void test_spare_wait_for() {
  const char* rec = "wait_r3.rec";  // the transcript the fake spare replays (NCCL_GIN_RESTORE_REPLAY), in the work dir
  char line[320];
  // (1) the pattern matches nothing at the start: no spawn; the transcript appears: spawned within a poll; HELLO. A
  // respawn after that does not wait (the pattern matches).
  {
    unlink(rec);
    SpareHold h;
    spare_hold(h, {gSelf, "--fake-spare"}, {std::string("NCCL_GIN_RESTORE_REPLAY=") + rec});
    ctl_open();
    FILE* lf = fopen("spare_wait.log", "w");
    L l = mk_launcher_spare(30, h, 3000, 3, lf, rec);
    glKidView kv;
    CHECK(gl_core_kids(l.c, &kv, 1) == 0 && gl_core_stats(l.c)->spareWaiting == 1 && gl_core_stats(l.c)->nSpareWaits == 1);
    CHECK(no_spawn_within(l, 400));
    CHECK(gl_core_stats(l.c)->nSpareSpawned == 0);
    FILE* t = fopen(rec, "w");
    CHECK(t != nullptr);
    if (t) fclose(t);
    const double t0 = now_ms();
    Spawned s = next_spawn(l, 'e');  // the transcript exists: HELLO, then it exits unused
    const double dt = now_ms() - t0;
    CHECK(s.ok && s.r.inc == 1 && dt < GL_SPARE_WAIT_POLL_MS + 200);
    CHECK(ack_of(kid_res(l, s.k)).status == GL_UA_OK);
    spawned_close(s);
    Spawned u = next_spawn(l, 't');  // the respawn: no wait (the pattern matches), HELLO
    CHECK(u.ok && u.r.inc == 1);
    CHECK(ack_of(kid_res(l, u.k)).status == GL_UA_OK);
    CHECK(pump_until(l, [&] { return kidv(l, 2, &kv) && kv.state == GL_KID_WARM; }));
    CHECK(kv.waitUnmet == 0);
    const glStats* st = gl_core_stats(l.c);
    CHECK(st->nSpareWaits == 1 && st->nSpareWaitTimeouts == 0 && st->spareWaiting == 0 && st->nSpareRespawned == 1 &&
          st->nSpareNoTranscript == 0);
    const std::string lg = slurp("spare_wait.log");
    snprintf(line, sizeof(line), "warm spare wait-for %s (each spawn waits until it matches: polled every 100 ms, bound "
                                 "3000 ms)", rec);
    CHECK(count_str(lg, line) == 1);
    CHECK(count_str(lg, "spare spawn waits (incarnation 1, why start): the wait-for matches nothing yet") == 1);
    CHECK(count_str(lg, "spare wait-for matched after ") == 1 && count_str(lg, "spawning anyway") == 0);
    CHECK(count_str(lg, "spare spawned (spawn 1, incarnation 1, pid ") == 1 && count_str(lg, "why start, log ") == 1);
    rm_launcher(l);
    spawned_close(u);
    fclose(lf);
    ctl_close();
  }
  // (2) the transcript never comes within the bound: spawned anyway; "cannot open the transcript" -> not counted, the next
  // spawn waits again; twice with a cap of 1 and no give-up; then the transcript appears and the spare says HELLO
  {
    unlink(rec);
    SpareHold h;
    spare_hold(h, {gSelf, "--fake-spare"}, {std::string("NCCL_GIN_RESTORE_REPLAY=") + rec});
    ctl_open();
    FILE* lf = fopen("spare_wait_timeout.log", "w");
    const size_t sig0 = gSignals.size();
    const double t0 = now_ms();
    L l = mk_launcher_spare(31, h, 400, 1, lf, rec);
    std::vector<pid_t> ps;
    for (int i = 0; i < 2; i++) {
      Spawned s = next_spawn(l, 't');
      CHECK(s.ok && s.r.inc == 1);
      ps.push_back(s.r.pid);
      spawned_close(s);
      CHECK(pump_until(l, [&] { return gl_core_stats(l.c)->nSpareNoTranscript == (unsigned)i + 1; }));
    }
    CHECK(now_ms() - t0 >= 800);  // two waits of 400 ms
    CHECK(gl_core_stats(l.c)->spareWaiting == 1 && gl_core_stats(l.c)->spareGaveUp == 0);
    FILE* t = fopen(rec, "w");
    if (t) fclose(t);
    Spawned v = next_spawn(l, 't');
    CHECK(v.ok && v.r.inc == 1);
    CHECK(ack_of(kid_res(l, v.k)).status == GL_UA_OK);
    glKidView kv;
    CHECK(pump_until(l, [&] { return kidv(l, 3, &kv) && kv.state == GL_KID_WARM; }));
    CHECK(kv.waitUnmet == 0);
    const glStats* st = gl_core_stats(l.c);
    CHECK(st->nSpareSpawned == 3 && st->nSpareRespawned == 0 && st->nSpareNoTranscript == 2 && st->nSpareWaits == 3 &&
          st->nSpareWaitTimeouts == 2 && st->spareGaveUp == 0 && st->nSpareHelloTimeout == 0);
    const std::string lg = slurp("spare_wait_timeout.log");
    for (int i = 0; i < 2; i++) {
      snprintf(line, sizeof(line), "spawned spare exited unused (spawn %d, incarnation 1, pid %d, before HELLO, exit 2): "
                                   "cannot open the transcript; not counted against the respawn cap (its spawn did not "
                                   "wait for the match)", i + 1, (int)ps[(size_t)i]);
      CHECK(count_str(lg, line) == 1);
      CHECK(count_str(slurp(log_name(kSpareLogs, getpid(), (unsigned)i + 1, 1, 31).c_str()),
                      "GIN/RS: replay: cannot open the transcript (errno 2)") == 1);
    }
    CHECK(count_str(lg, "spare wait-for matched nothing within 400 ms (incarnation 1): spawning anyway") == 2);
    CHECK(count_str(lg, "spare spawn waits (incarnation 1, why no_transcript)") == 2);
    CHECK(count_str(lg, "why start, log ") == 1 && count_str(lg, "why no_transcript, log ") == 2);  // spawns 2 and 3
    CHECK(count_str(lg, "): respawn ") == 0 && count_str(lg, "STOP_launcher") == 0);
    CHECK(gSignals.size() == sig0);  // they ended by themselves
    rm_launcher(l);  // v, unused: SIGKILLed through its pidfd
    CHECK(gSignals.size() == sig0 + 1 && gSignals.back().pid == v.r.pid);
    for (pid_t p : ps) CHECK(proc_state(p) == '-');
    spawned_close(v);
    fclose(lf);
    ctl_close();
  }
  // (3) the negative control: the wait-for (another file) matches at once but the transcript is not there: the same
  // exit is counted (respawn 1 of 1, then the cap), so a pattern that is not the transcript cannot loop
  {
    unlink(rec);
    const char* go = "wait_go.marker";
    FILE* g = fopen(go, "w");
    if (g) fclose(g);
    SpareHold h;
    spare_hold(h, {gSelf, "--fake-spare"}, {std::string("NCCL_GIN_RESTORE_REPLAY=") + rec});
    ctl_open();
    FILE* lf = fopen("spare_wait_met.log", "w");
    L l = mk_launcher_spare(32, h, 3000, 1, lf, "wait_go.*");
    CHECK(gl_core_stats(l.c)->spareWaiting == 0 && gl_core_stats(l.c)->nSpareSpawned == 1);  // no wait at the start
    Spawned s = next_spawn(l, 't');
    Spawned t = next_spawn(l, 't');
    CHECK(s.ok && t.ok);
    CHECK(pump_until(l, [&] { return gl_core_stats(l.c)->spareGaveUp == 1; }));
    const glStats* st = gl_core_stats(l.c);
    CHECK(st->nSpareNoTranscript == 0 && st->nSpareRespawned == 1 && st->nSpareWaits == 0);
    const std::string lg = slurp("spare_wait_met.log");
    snprintf(line, sizeof(line), "(spawn 1, incarnation 1, pid %d, before HELLO, exit 2): respawn 1 of 1", (int)s.r.pid);
    CHECK(count_str(lg, line) == 1);
    snprintf(line, sizeof(line), "(spawn 2, incarnation 1, pid %d, before HELLO, exit 2): respawn cap 1", (int)t.r.pid);
    CHECK(count_str(lg, line) == 1);
    CHECK(count_str(lg, "not counted against the respawn cap") == 0);
    rm_launcher(l);
    spawned_close(s);
    spawned_close(t);
    fclose(lf);
    ctl_close();
    unlink(go);
  }
  // (4) shutdown while a spawn waits: one line, nothing spawned, nothing signalled
  {
    unlink(rec);
    SpareHold h;
    spare_hold(h, {gSelf, "--fake-spare"}, {std::string("NCCL_GIN_RESTORE_REPLAY=") + rec});
    ctl_open();
    FILE* lf = fopen("spare_wait_shutdown.log", "w");
    const size_t sig0 = gSignals.size();
    L l = mk_launcher_spare(33, h, 3000, 3, lf, rec);
    pump(l, 150);
    CHECK(gl_core_stats(l.c)->spareWaiting == 1);
    rm_launcher(l);
    CHECK(gSignals.size() == sig0);
    CHECK(count_str(slurp("spare_wait_shutdown.log"), "shutdown: the spare spawn waiting for its wait-for (incarnation 1) "
                                                      "ends unspawned") == 1);
    fclose(lf);
    ctl_close();
  }
  CHECK(signals_allowed());
}

static void test_spare_opts() {
  glSpareOpts o;
  gl_spare_opts_init(&o);
  char why[256];
  glConfig cfg;
  memset(&cfg, 0, sizeof(cfg));
  CHECK(gl_spare_opt(&o, "--node", "1", why, sizeof(why)) == 0);
  CHECK(gl_spare_opts_apply(&o, &cfg, why, sizeof(why)) == 0 && cfg.spareArgv == nullptr);  // nothing given: off
  CHECK(gl_spare_opt(&o, "--spare-cmd", "  stdbuf -oL   -eL /bin/x 3 a\tb ", why, sizeof(why)) == 1);
  CHECK(o.argc == 7 && strcmp(o.argv[0], "stdbuf") == 0 && strcmp(o.argv[3], "/bin/x") == 0 &&
        strcmp(o.argv[6], "b") == 0 && o.argv[7] == nullptr);
  CHECK(gl_spare_opts_apply(&o, &cfg, why, sizeof(why)) == -1 && strstr(why, "--spare-log"));  // no log dir
  CHECK(gl_spare_opt(&o, "--spare-log", "no-such-dir", why, sizeof(why)) == 1);
  CHECK(gl_spare_opts_apply(&o, &cfg, why, sizeof(why)) == -1);
  CHECK(gl_spare_opt(&o, "--spare-log", kSpareLogs, why, sizeof(why)) == 1);
  CHECK(gl_spare_opt(&o, "--spare-env", "NCCL_GIN_RESTORE_SPARE_INC=2", why, sizeof(why)) == 1 && o.firstInc == 2);
  CHECK(gl_spare_opt(&o, "--spare-env", "NCCL_GIN_RESTORE_SPARE_INC=0", why, sizeof(why)) == -1);
  CHECK(gl_spare_opt(&o, "--spare-env", "K=1", why, sizeof(why)) == 1);
  CHECK(gl_spare_opt(&o, "--spare-env", "K=2", why, sizeof(why)) == 1 && o.nenv == 2);
  bool k2 = false;
  for (int i = 0; i < o.nenv; i++) k2 |= strcmp(o.env[i], "K=2") == 0;
  CHECK(k2 && o.env[o.nenv] == nullptr);
  for (const char* bad : {"NCCL_GIN_RESTORE_RECORD=/x", "NCCL_GIN_RESTORE_TEST_DIE_IN_CKPT=a:1", "GIN_RS_DIE_AT=5",
                          "GIN_RS_DIE_IN_STEP=1", "NCCL_GIN_CTRL_LAUNCHER_SOCK=/x", "NCCL_GIN_CTRL_LAUNCHER_NODE=1", "=x",
                          "A B=1", "9A=1", "NOEQUALS"})
    CHECK(gl_spare_opt(&o, "--spare-env", bad, why, sizeof(why)) == -1);
  CHECK(gl_spare_opt(&o, "--spare", "2", why, sizeof(why)) == -1);
  CHECK(gl_spare_opt(&o, "--spare-hello-ms", "0", why, sizeof(why)) == -1);
  CHECK(gl_spare_opt(&o, "--spare-hello-ms", "12x", why, sizeof(why)) == -1);
  CHECK(gl_spare_opt(&o, "--spare-respawn-max", "-1", why, sizeof(why)) == -1);
  CHECK(gl_spare_opt(&o, "--spare-cmd", nullptr, why, sizeof(why)) == -1);
  CHECK(gl_spare_opt(&o, "--spare-hello-ms", "250", why, sizeof(why)) == 1);
  CHECK(gl_spare_opt(&o, "--spare-respawn-max", "0", why, sizeof(why)) == 1);
  CHECK(gl_spare_opts_apply(&o, &cfg, why, sizeof(why)) == 0);
  CHECK(cfg.spareArgv == o.argv && cfg.spareEnv == o.env && cfg.spareHelloMs == 250 && cfg.spareRespawnMax == 0 &&
        cfg.spareFirstInc == 2 && strcmp(cfg.spareLogDir, kSpareLogs) == 0);
  CHECK(gl_spare_opt(&o, "--spare", "0", why, sizeof(why)) == 1);
  CHECK(gl_spare_opts_apply(&o, &cfg, why, sizeof(why)) == 0 && cfg.spareArgv == nullptr);  // --spare 0: off
  CHECK(gl_spare_opt(&o, "--spare-cmd", " \t ", why, sizeof(why)) == -1);
  gl_spare_opts_free(&o);
  // sparefix: --spare-wait-for; not given: the NCCL_GIN_RESTORE_REPLAY of --spare-env; "-": none; empty refused
  CHECK(gl_spare_opt(&o, "--spare-cmd", "/bin/x", why, sizeof(why)) == 1);
  CHECK(gl_spare_opt(&o, "--spare-log", kSpareLogs, why, sizeof(why)) == 1);
  CHECK(gl_spare_opts_apply(&o, &cfg, why, sizeof(why)) == 0 && cfg.spareWaitFor == nullptr);  // no REPLAY: no wait
  CHECK(gl_spare_opt(&o, "--spare-env", "NCCL_GIN_RESTORE_REPLAY=/w/r3.rec", why, sizeof(why)) == 1);
  CHECK(gl_spare_opts_apply(&o, &cfg, why, sizeof(why)) == 0 && cfg.spareWaitFor && strcmp(cfg.spareWaitFor, "/w/r3.rec") == 0);
  CHECK(gl_spare_opt(&o, "--spare-wait-for", "", why, sizeof(why)) == -1);
  CHECK(gl_spare_opt(&o, "--spare-wait-for", nullptr, why, sizeof(why)) == -1);
  CHECK(gl_spare_opt(&o, "--spare-wait-for", "/w/go.*", why, sizeof(why)) == 1);
  CHECK(gl_spare_opts_apply(&o, &cfg, why, sizeof(why)) == 0 && cfg.spareWaitFor && strcmp(cfg.spareWaitFor, "/w/go.*") == 0);
  CHECK(gl_spare_opt(&o, "--spare-wait-for", "-", why, sizeof(why)) == 1);
  CHECK(gl_spare_opts_apply(&o, &cfg, why, sizeof(why)) == 0 && cfg.spareWaitFor == nullptr);
  CHECK(gl_spare_opt(&o, "--spare", "0", why, sizeof(why)) == 1);
  CHECK(gl_spare_opts_apply(&o, &cfg, why, sizeof(why)) == 0 && cfg.spareWaitFor == nullptr && cfg.spareArgv == nullptr);
  gl_spare_opts_free(&o);
  CHECK(gl_spare_opt(&o, "--spare", "1", why, sizeof(why)) == 1);
  CHECK(gl_spare_opts_apply(&o, &cfg, why, sizeof(why)) == -1);  // --spare 1 without --spare-cmd
  gl_spare_opts_free(&o);
}

static void test_header() {
  CHECK(sizeof(glMsg) == 256 && sizeof(glUnixMsg) == 256 && sizeof(glCtrlEnv) == 64 && sizeof(glPage) == 4096);
  glCtrlEnv e;
  gl_env_pack(&e, GL_ENV_KIND_LAUNCHER, GL_FROM_LAUNCHER | 1, 3, 9, 4, N1, 0);
  CHECK(gl_env_check(&e, GL_ENV_KIND_LAUNCHER) == GL_R_NONE);
  CHECK(gl_env_check(&e, GL_ENV_KIND_PAIR) == GL_R_BAD_MSG);
  e.bodyBytes = 255;
  CHECK(gl_env_check(&e, GL_ENV_KIND_LAUNCHER) == GL_R_BAD_MSG);
  glMsg m = mk(GL_K_FENCE, 1, 0, N1, 0);
  CHECK(gl_msg_check(&m) == GL_R_NONE);
  m.h.kind = 99;
  CHECK(gl_msg_check(&m) == GL_R_UNKNOWN_KIND);
  glUnixMsg u;
  memset(&u, 0, sizeof(u));
  u.h.magic = GL_U_MAGIC;
  u.h.version = GL_WIRE_VERSION;
  u.h.kind = GL_U_INFO;
  CHECK(GL_U_INFO == 8 && GL_U_INFO_ACK == 9 && GL_U_KIND_MAX == 9);
  CHECK(gl_unix_check(&u, sizeof(u)) == GL_R_NONE);
  u.h.kind = GL_U_INFO_ACK;
  CHECK(gl_unix_check(&u, sizeof(u)) == GL_R_NONE);
  u.h.kind = 10;
  CHECK(gl_unix_check(&u, sizeof(u)) == GL_R_UNKNOWN_KIND);
  u.h.kind = 0;
  CHECK(gl_unix_check(&u, sizeof(u)) == GL_R_UNKNOWN_KIND);
  for (uint32_t r = 0; r < GL_R_COUNT; r++) CHECK(strcmp(gl_reason_text(r), "?") != 0);
  CHECK(strcmp(gl_reason_text(GL_R_SPAWN_NOT_BUILT), "spawn not built") == 0);
}

int main(int argc, char** argv) {
  if (argc > 1 && strcmp(argv[1], "--fake-spare") == 0) return fake_spare_main(argc, argv);  // exec'd by a launcher
  if (argc > 1 && chdir(argv[1]) != 0) {
    perror("chdir");
    return 2;
  }
  char self[512];
  const ssize_t sl = readlink("/proc/self/exe", self, sizeof(self) - 1);
  if (sl <= 0) return 2;
  self[sl] = 0;
  gSelf = self;
  mkdir(kSpareLogs, 0700);
  setenv("NCCL_GIN_UNIT_LEAK", "1", 1);  // the launcher's own NCCL_ and GIN_ variables never reach a spawned spare
  setenv("GIN_UNIT_LEAK", "1", 1);
  signal(SIGPIPE, SIG_IGN);
  setvbuf(stdout, nullptr, _IOLBF, 0);
  struct {
    const char* name;
    void (*f)();
  } tests[] = {{"header", test_header},
               {"pidfd_facts", test_pidfd_facts},
               {"registration", test_registration},
               {"exit_and_left", test_exit_and_left},
               {"left_bye_model", test_left_bye_model},
               {"fence", test_fence},
               {"no_foreign_signal", test_no_foreign_signal},
               {"spawn", test_spawn},
               {"later_then_handover", test_later_then_handover},
               {"spare_exits_and_refusals", test_spare_exits_and_refusals},
               {"early_answer_bound", test_early_answer_bound},
               {"lost_accepted", test_lost_accepted},
               {"abort_during_read", test_abort_during_read},
               {"handle_reuse", test_handle_reuse},
               {"duplicates_and_swaps", test_duplicates_and_swaps},
               {"pairing", test_pairing},
               {"registration_oracle", test_registration_oracle},
               {"socket_dir", test_socket_dir},
               {"malformed", test_malformed},
               {"info", test_info},
               {"shutdown_kills_unused_spare", test_shutdown_kills_unused_spare},
               {"spare_opts", test_spare_opts},
               {"spare_start", test_spare_start},
               {"spare_activation_cycle", test_spare_activation_cycle},
               {"spare_respawn", test_spare_respawn},
               {"spare_hello_timeout", test_spare_hello_timeout},
               {"spare_no_foreign_signal", test_spare_no_foreign_signal},
               {"spare_wait_for", test_spare_wait_for}};
  int nt = 0;
  for (auto& t : tests) {
    const int f0 = nFail, c0 = nChecks;
    t.f();
    printf("TEST %-28s %s (%d checks)\n", t.name, nFail == f0 ? "ok" : "FAILED", nChecks - c0);
    nt++;
  }
  for (pid_t p : gKids) waitpid(p, nullptr, WNOHANG);
  printf("launcher_unit: %d tests, %d checks, %d failed (the registration oracle: %d scenes, one check each)\n", nt,
         nChecks, nFail, gOracleScenes);
  return nFail ? 1 : 0;
}
