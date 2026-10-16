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
// (when the path exists the arming decision equals today's); the socket directory; malformed messages; the page.
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
  int nRcOpen = 0;
};
static TT* tt_of(glTransport* tp) { return (TT*)tp->impl; }
static int tt_fds(glTransport*, int*, int) { return 0; }
static int tt_poll(glTransport* tp, glTpEvent* ev, int max) {
  TT* t = tt_of(tp);
  for (const TT::Read& r : t->reads) {  // complete READs on the next poll
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
  const int h = t->nextHandle++;
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
static void tt_rc_close(glTransport* tp, int peer) { tt_of(tp)->open[peer] = false; }
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
  {
    Act a = act_setup();
    spare_ready(a);
    rc_in(a.l, a.hb, mk_activate(3, 1, N1, 64));
    kid_cmd(a.s, 'h');
    kid_res(a.l, a.s);
    kid_cmd(a.s, 'a');
    CHECK(pump_until(a.l, [&] { return count_kind(a.l, a.hb, GL_K_ACT_ANSWER) == 1; }));
    glTpEvent e;
    memset(&e, 0, sizeof(e));
    e.type = GL_TP_RC_ERROR;
    e.peer = a.hb;
    a.l.t->in.push_back(e);  // the buddy's launcher QP fails after ACCEPTED
    kid_cmd(a.s, 'h');
    std::vector<uint8_t> got = kid_res(a.l, a.s);
    CHECK(as_u(got) && as_u(got)->h.sub == GL_UT_ABORT);
    CHECK(entry(a.l, N1, 3, 2, 1, &v) && v.sp == GL_SP_ABORTED);
    kid_cmd(a.s, 'E');  // its FETCH endpoint now goes nowhere
    pump(a.l, 20);
    CHECK(count_kind(a.l, a.hb, GL_K_FETCH_EP) == 0);
    CHECK(!a.l.t->open[a.hb]);
    act_done(a);
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
  // an older record generation: dropped; a newer one: the old record QP is closed, a new one opened
  const size_t ud1 = l.t->ud.size();
  pair_rank(l, 1, 0, N1, 0, false);
  CHECK(l.t->ud.size() == ud1 && l.t->open[h]);
  const int h2 = pair_rank(l, 1, 0, N1, 2, true);
  CHECK(!l.t->open[h] && l.t->open[h2] && l.t->open[hp2]);
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
  CHECK(!l.t->open[h4] && !l.t->open[hp2] && l.t->open[h5]);
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
static void oracle_check(const glArmView& v, int expectPath, const char* scene) {
  const int path = gl_path_exists(&v);
  CHECK(path == expectPath);
  for (int all = 0; all <= 1; all++) {
    const int now = gl_armable(all, &v);
    CHECK(now == today_armable(all, path));     // the path plays today's "spare registered"
    if (path) CHECK(now == today_armable(all, 1));  // when the path exists: today's decision
    else CHECK(now == 0);
  }
  if (path != expectPath) fprintf(stderr, "oracle scene %s: path %d, expected %d\n", scene, path, expectPath);
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
  for (uint32_t r = 0; r < GL_R_COUNT; r++) CHECK(strcmp(gl_reason_text(r), "?") != 0);
  CHECK(strcmp(gl_reason_text(GL_R_SPAWN_NOT_BUILT), "spawn not built") == 0);
}

int main(int argc, char** argv) {
  if (argc > 1 && chdir(argv[1]) != 0) {
    perror("chdir");
    return 2;
  }
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
               {"duplicates_and_swaps", test_duplicates_and_swaps},
               {"pairing", test_pairing},
               {"registration_oracle", test_registration_oracle},
               {"socket_dir", test_socket_dir},
               {"malformed", test_malformed},
               {"shutdown_kills_unused_spare", test_shutdown_kills_unused_spare}};
  int nt = 0;
  for (auto& t : tests) {
    const int f0 = nFail, c0 = nChecks;
    t.f();
    printf("TEST %-28s %s (%d checks)\n", t.name, nFail == f0 ? "ok" : "FAILED", nChecks - c0);
    nt++;
  }
  for (pid_t p : gKids) waitpid(p, nullptr, WNOHANG);
  printf("launcher_unit: %d tests, %d checks, %d failed\n", nt, nChecks, nFail);
  return nFail ? 1 : 0;
}
