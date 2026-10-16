/* gin_launcher.c - the per-node launcher of gin-control (EXPERIMENT.md 9.5; design v2 5.2, 5.4, 4.4; REVIEW2 5).
 *
 * One process per node, one thread, one poll loop. It
 *   - accepts registrations of the node's recovery-layer processes on a Unix socket (SOCK_SEQPACKET, mode 0700
 *     directory), each carrying the process's own pidfd by SCM_RIGHTS, only from its own uid (SO_PEERCRED), and only
 *     when the pidfd's pid is the connecting process and that pid's start time is the one seen at connect (always on);
 *   - keeps one entry per registered process (rank, incarnation, nonce, pidfd, state) and watches the pidfds (readable =
 *     the thread group ended); reports one message per exit to every paired rank of that communicator: FENCED when a
 *     FENCE had come, else LEFT after a LEAVING notice, else EXITED (the test switch NO_EXIT_REPORT drops EXITED only);
 *   - executes FENCE: SIGKILL through a pidfd it holds (never a pid, never a pidfd it was not given), FENCED when the
 *     pidfd is readable; a FENCE of something already ended gets FENCED at once; a FENCE of something not held gets
 *     FENCE_NAK and a "refused to signal" line;
 *   - relays an ACTIVATE to the pre-launched spare of (rank, incarnation): when the spare said HELLO but not READY it
 *     answers LATER exactly once and hands over at READY. It sets no limit of its own on that wait (the HELLO and READY
 *     limits are gin-dynamic's); it ends at READY, a replay failure, the spare's exit or the buddy's ABORT, and the rank
 *     side bounds it from what the LATER and the page say (the spare's state and age, the beat);
 *   - answers SPAWN with REFUSED "spawn not built";
 *   - pairs over UD: record QP and liveness-READ QP apart, either side may start, fresh PSNs; it starts the re-pairing
 *     of a rank's record QP itself when that QP fails;
 *   - keeps its state page: beat, per-registration state word and spare word, per-rank consumed count (credit).
 *
 * The RNIC is behind launcher_transport.h. -DGL_NO_MAIN builds the state machine alone (the unit test);
 * -DGL_NO_VERBS builds a program without the verbs transport (it refuses to start).
 */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

#include "gin_launcher.h"

#ifndef SYS_pidfd_send_signal
#define SYS_pidfd_send_signal 424
#endif

#define GL_MAX_CONNS 128
#define GL_MAX_ENTRIES 64
#define GL_MAX_TOMBS 1024
#define GL_MAX_PEERS GL_PAGE_CREDITS
#define GL_PEER_QUEUE 64
#define GL_MAX_TP_FDS 4
#define GL_E_ORIG 1
#define GL_E_SPARE 2
#define GL_ACT_NONE 0
#define GL_ACT_WAIT 1  /* ACTIVATE taken, the spare is not READY */
#define GL_ACT_READ 2  /* reading the blob from the buddy's outbox */
#define GL_ACT_GIVEN 3 /* the bytes went to the spare; its answer pending (or given) */

struct glConn {
  int used;
  int fd;
  pid_t pid;            /* SO_PEERCRED at accept */
  uid_t uid;
  uint64_t start;       /* that pid's start time (/proc/<pid>/stat field 22) at accept; 0 unreadable */
};

struct glEntry {
  int used, kind;
  uint64_t id;          /* unique per entry life (a freed slot or fd number may be reused within one pass) */
  int32_t rank;
  uint32_t inc;
  uint64_t nonce;
  int pidfd;
  pid_t pid;
  int conn;             /* index into conn[], -1 when closed */
  int leaving;
  int fenceAsked, signalled;
  uint64_t fenceNs;
  int dead;             /* spare: pidfd readable seen, kept for its answer */
  int sp;               /* GL_SP_* (spare) */
  double spSinceMs;     /* when sp last changed */
  uint32_t spReason;
  int act;
  int laterSent;
  int actPeer;          /* index into peer[] */
  uint32_t actReqSeq;
  uint32_t serial;      /* READ cookie check */
  int readBusy;         /* a READ into blobBuf is in flight on readHandle (REVIEW_PREP fix 10: the buffer is never freed
                           before its completion or the close of that QP) */
  int readHandle;
  struct glRsActivate rec;
  struct glRegion blob;
  uint8_t* blobBuf;
  double killAtMs;      /* > 0: SIGKILL through the pidfd at this time (aborted or failed spare) */
};

#define GL_MAX_ORPHANS 64
struct glOrphan {
  int used;
  int handle;           /* the QP the READ is on */
  uint64_t cookie;
  uint8_t* buf;
};

struct glTomb {
  int32_t rank;
  uint32_t inc;
  uint64_t nonce;
  uint32_t how;         /* GL_K_EXITED, GL_K_LEFT, GL_K_FENCED */
};

struct glQp {
  int handle;           /* -1: none */
  uint32_t gen;
  struct glEp remote;
  struct glMsg ack;     /* the PAIR_ACK sent for it (the same PAIR again gets it again) */
  int haveAck;
};

struct glPeer {          /* one paired rank (nonce, rank); bound to page credit slot of the same index */
  int used;
  int32_t rank;
  uint32_t inc;
  uint64_t nonce;
  struct glEp ud;
  uint32_t qkey;
  struct glRegion page;
  uint32_t creditOff;
  struct glQp rec, probe;
  int connected;        /* record QP: CONNECTED seen (rank started) or sent (launcher started) */
  uint64_t consumed;    /* record-QP messages taken from the rank in rec.gen */
  int repair;           /* the launcher started a re-pairing of the record QP */
  uint32_t repairGen;
  int repairHandle;
  struct glEp repairLocal;
  struct glMsg repairPair;
  double repairNextMs, repairEndMs;
  struct glMsg q[GL_PEER_QUEUE];
  int nq;
};

struct glCore {
  struct glConfig cfg;
  struct glTransport* tp;
  FILE* log;
  int listenFd;
  char sockPath[sizeof(((struct sockaddr_un*)0)->sun_path)];
  struct glConn conn[GL_MAX_CONNS];
  struct glEntry ent[GL_MAX_ENTRIES];
  struct glTomb tomb[GL_MAX_TOMBS];
  int nTomb;
  struct glPeer peer[GL_MAX_PEERS];
  struct glOrphan orphan[GL_MAX_ORPHANS];  /* READ buffers whose entry let go while the READ was in flight */
  int fatal;            /* the transport reported a failure of its own (GL_TP_FATAL): the loop stops */
  struct glPage* page;
  struct glRegion pageReg;
  struct glEp ud;
  uint32_t seq, serial;
  uint64_t nextId;
  struct glStats st;
  uint8_t rbuf[sizeof(struct glUnixMsg) + GL_U_MAX_PAYLOAD] __attribute__((aligned(64)));  /* read as glUnixMsg */
};

/* ------------------------------------------------------------------------------------------------- small helpers */

static uint64_t gl_mono_ns(void) {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return (uint64_t)t.tv_sec * 1000000000ull + (uint64_t)t.tv_nsec;
}
static double gl_mono_ms(void) { return (double)gl_mono_ns() / 1e6; }

static void gl_log(struct glCore* c, const char* fmt, ...) __attribute__((format(printf, 2, 3)));
static void gl_log(struct glCore* c, const char* fmt, ...) {
  char line[768];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(line, sizeof(line), fmt, ap);
  va_end(ap);
  fprintf(c->log, "GIN/LA: node %u: %s mono_ms=%.3f\n", c->cfg.node, line, gl_mono_ms());
  fflush(c->log);
}

static int gl_readable(int fd) {
  struct pollfd p;
  p.fd = fd;
  p.events = POLLIN;
  p.revents = 0;
  return poll(&p, 1, 0) > 0 && (p.revents & (POLLIN | POLLHUP | POLLERR)) != 0;
}

static void gl_close_pidfd(struct glCore* c, int* fd) {
  if (*fd >= 0) {
    close(*fd);
    c->st.nPidfdClosed++;
  }
  *fd = -1;
}

int gl_pidfd_pid(int fd) {
  char p[64], l[128];
  snprintf(p, sizeof(p), "/proc/self/fd/%d", fd);
  char tgt[64];
  const ssize_t n = readlink(p, tgt, sizeof(tgt) - 1);
  if (n <= 0) return -2;
  tgt[n] = '\0';
  if (strcmp(tgt, "anon_inode:[pidfd]") != 0) return -2;
  snprintf(p, sizeof(p), "/proc/self/fdinfo/%d", fd);
  FILE* f = fopen(p, "r");
  if (!f) return -2;
  int pid = -2;
  while (fgets(l, sizeof(l), f))
    if (strncmp(l, "Pid:", 4) == 0) {
      pid = atoi(l + 4);
      break;
    }
  fclose(f);
  return pid;
}

uint64_t gl_pid_start(pid_t pid) {
  char p[64], b[1024];
  snprintf(p, sizeof(p), "/proc/%d/stat", (int)pid);
  FILE* f = fopen(p, "r");
  if (!f) return 0;
  const size_t n = fread(b, 1, sizeof(b) - 1, f);
  fclose(f);
  b[n] = '\0';
  const char* q = strrchr(b, ')');  // the command name may hold spaces: count the fields after its ')'
  int field = 2;
  for (; q && *q; q++)
    if (*q == ' ' && ++field == 22) return strtoull(q + 1, NULL, 10);
  return 0;
}

int gl_default_sock_path(char* out, size_t len) {
  const char* x = getenv("XDG_RUNTIME_DIR");
  int n;
  if (x && *x) n = snprintf(out, len, "%s/gin-launcher/launcher.sock", x);
  else n = snprintf(out, len, "/tmp/gin-launcher-%u/launcher.sock", (unsigned)getuid());
  return (n > 0 && (size_t)n < len) ? 0 : -1;
}

/* The only place a signal is sent: the entry's own pidfd (a pidfd the launcher was given at registration). */
static int gl_signal(struct glCore* c, struct glEntry* e, int sig) {
  if (e->pidfd < 0) return -1;
  const int rc = (int)syscall(SYS_pidfd_send_signal, e->pidfd, sig, NULL, 0);
  const int err = errno;
  c->st.nSignals++;
  if (c->cfg.onSignal) c->cfg.onSignal(c->cfg.onSignalArg, e->pid, sig, rc);
  errno = err;
  return rc;
}

/* ------------------------------------------------------------------------------------------------- lookups */

static struct glEntry* gl_find(struct glCore* c, int kind, uint64_t nonce, int32_t rank) {
  for (int i = 0; i < GL_MAX_ENTRIES; i++) {
    struct glEntry* e = &c->ent[i];
    if (e->used && e->kind == kind && e->nonce == nonce && e->rank == rank) return e;
  }
  return NULL;
}
static struct glEntry* gl_find_spare(struct glCore* c, uint64_t nonce, int32_t rank, uint32_t inc) {
  for (int i = 0; i < GL_MAX_ENTRIES; i++) {
    struct glEntry* e = &c->ent[i];
    if (e->used && e->kind == GL_E_SPARE && e->nonce == nonce && e->rank == rank && e->inc == inc) return e;
  }
  return NULL;
}
static const struct glTomb* gl_tomb_of(const struct glCore* c, uint64_t nonce, int32_t rank, uint32_t inc) {
  for (int i = c->nTomb; i-- > 0;)
    if (c->tomb[i].nonce == nonce && c->tomb[i].rank == rank && c->tomb[i].inc == inc) return &c->tomb[i];
  return NULL;
}
static const struct glTomb* gl_tomb_last(const struct glCore* c, uint64_t nonce, int32_t rank) {
  const struct glTomb* t = NULL;
  for (int i = 0; i < c->nTomb; i++)
    if (c->tomb[i].nonce == nonce && c->tomb[i].rank == rank && (!t || c->tomb[i].inc >= t->inc)) t = &c->tomb[i];
  return t;
}
static void gl_tomb_add(struct glCore* c, const struct glEntry* e, uint32_t how) {
  struct glTomb* t;
  if (c->nTomb < GL_MAX_TOMBS) t = &c->tomb[c->nTomb++];
  else {  // keep the newest: drop the oldest
    memmove(&c->tomb[0], &c->tomb[1], sizeof(c->tomb[0]) * (GL_MAX_TOMBS - 1));
    t = &c->tomb[GL_MAX_TOMBS - 1];
  }
  t->rank = e->rank;
  t->inc = e->inc;
  t->nonce = e->nonce;
  t->how = how;
}
/* The entry lets go of its blob buffer. A READ still in flight into it keeps it alive: it moves to the orphan list and is
 * freed at that READ's completion or when its QP closes (REVIEW_PREP fix 10; the verbs transport's NIC would otherwise
 * DMA into freed heap). */
static void gl_blob_release(struct glCore* c, struct glEntry* e) {
  if (e->readBusy && e->blobBuf) {
    int k = -1;
    for (int i = 0; i < GL_MAX_ORPHANS && k < 0; i++)
      if (!c->orphan[i].used) k = i;
    if (k >= 0) {
      c->orphan[k].used = 1;
      c->orphan[k].handle = e->readHandle;
      c->orphan[k].cookie = ((uint64_t)(e - c->ent) << 32) | e->serial;
      c->orphan[k].buf = e->blobBuf;
    } else {  // never expected (64 READs in flight): keep the memory rather than free it under a DMA
      gl_log(c, "orphan table full: a READ buffer of %u bytes is leaked, not freed under its READ", e->blob.len);
    }
  } else {
    free(e->blobBuf);
  }
  e->blobBuf = NULL;
  e->readBusy = 0;
  e->readHandle = -1;
}
/* A READ's QP closed (rc_close: no completion follows) or its READ completed: its orphaned buffers go. */
static void gl_orphans_free(struct glCore* c, int handle, int byCookie, uint64_t cookie) {
  for (int i = 0; i < GL_MAX_ORPHANS; i++) {
    struct glOrphan* o = &c->orphan[i];
    if (!o->used || o->handle != handle || (byCookie && o->cookie != cookie)) continue;
    free(o->buf);
    memset(o, 0, sizeof(*o));
  }
}
static void gl_entry_reset(struct glCore* c, struct glEntry* e) {
  gl_blob_release(c, e);
  memset(e, 0, sizeof(*e));
  e->used = 1;
  e->pidfd = -1;
  e->conn = -1;
  e->actPeer = -1;
  e->readHandle = -1;
  e->id = ++c->nextId;
  e->spSinceMs = gl_mono_ms();
}
static struct glEntry* gl_entry_new(struct glCore* c) {
  for (int i = 0; i < GL_MAX_ENTRIES; i++)
    if (!c->ent[i].used) {
      c->ent[i].blobBuf = NULL;
      gl_entry_reset(c, &c->ent[i]);
      return &c->ent[i];
    }
  for (int i = 0; i < GL_MAX_ENTRIES; i++)  // reuse a dead spare's slot
    if (c->ent[i].used && c->ent[i].kind == GL_E_SPARE && c->ent[i].dead) {
      gl_entry_reset(c, &c->ent[i]);
      return &c->ent[i];
    }
  return NULL;
}
static void gl_entry_free(struct glCore* c, struct glEntry* e) {
  gl_close_pidfd(c, &e->pidfd);
  gl_blob_release(c, e);
  memset(e, 0, sizeof(*e));
  e->pidfd = -1;
  e->conn = -1;
  e->actPeer = -1;
  e->readHandle = -1;
}
static void gl_sp_set(struct glEntry* s, int sp) {
  if (s->sp != sp) s->spSinceMs = gl_mono_ms();
  s->sp = sp;
}
static struct glPeer* gl_peer_of_handle(struct glCore* c, int handle, int* kind) {
  for (int i = 0; i < GL_MAX_PEERS; i++) {
    struct glPeer* p = &c->peer[i];
    if (!p->used || handle < 0) continue;
    if (p->rec.handle == handle) return *kind = GL_PAIR_RECORD, p;
    if (p->probe.handle == handle) return *kind = GL_PAIR_PROBE, p;
    if (p->repair && p->repairHandle == handle) return *kind = 0, p;
  }
  return NULL;
}
static struct glPeer* gl_peer_find(struct glCore* c, uint64_t nonce, int32_t rank) {
  for (int i = 0; i < GL_MAX_PEERS; i++)
    if (c->peer[i].used && c->peer[i].nonce == nonce && c->peer[i].rank == rank) return &c->peer[i];
  return NULL;
}

/* ------------------------------------------------------------------------------------------------- page */

/* Every page word is written with one 8 B release store (REVIEW_PREP nit 11): a reader's READ sees each word whole, and a
 * slot's key (its nonce) is stored after its other words, so the compiler cannot move it ahead of them. */
static void gl_pw(uint64_t* w, uint64_t v) { __atomic_store_n(w, v, __ATOMIC_RELEASE); }

/* The registration slot of (nonce, rank): bound at first use, never rebound. -1 when the page is full. */
static int gl_page_slot(struct glCore* c, uint64_t nonce, int32_t rank) {
  for (int i = 0; i < GL_PAGE_REGS; i++)
    if (c->page->reg[i].nonce == nonce && nonce != 0 && gl_page_word_rank(c->page->reg[i].reg) == (rank & 0xffffff))
      return i;
  for (int i = 0; i < GL_PAGE_REGS; i++)
    if (c->page->reg[i].nonce == 0) {
      gl_pw(&c->page->reg[i].reg, gl_page_word(GL_RS_NONE, rank, 0));
      gl_pw(&c->page->reg[i].spare, gl_page_word(GL_SP_NONE, rank, 0));
      gl_pw(&c->page->reg[i].spareSinceMs, 0);
      gl_pw(&c->page->reg[i].nonce, nonce);  // the key last (a release store): a reader never matches a half-bound slot
      gl_pw(&c->page->nRegs, c->page->nRegs + 1);
      return i;
    }
  return -1;
}
/* The registration and spare words of (nonce, rank) from the entries and the records of ended ones. */
static void gl_reg_words(struct glCore* c, uint64_t nonce, int32_t rank, struct glRegNoteBody* b) {
  memset(b, 0, sizeof(*b));
  const struct glEntry* o = gl_find(c, GL_E_ORIG, nonce, rank);
  if (o) {
    b->regState = GL_RS_ALIVE;
    b->regInc = o->inc;
  } else {
    const struct glTomb* t = gl_tomb_last(c, nonce, rank);
    if (t) {
      b->regState = t->how == GL_K_LEFT ? GL_RS_LEFT : t->how == GL_K_FENCED ? GL_RS_FENCED : GL_RS_EXITED;
      b->regInc = t->inc;
    }
  }
  const struct glEntry* best = NULL;
  for (int i = 0; i < GL_MAX_ENTRIES; i++) {
    const struct glEntry* e = &c->ent[i];
    if (e->used && e->kind == GL_E_SPARE && e->nonce == nonce && e->rank == rank && (!best || e->inc >= best->inc))
      best = e;
  }
  if (best) {
    b->spareState = (uint32_t)(best->dead && best->sp != GL_SP_ABORTED ? GL_SP_FAILED : best->sp);
    b->spareInc = best->inc;
    const double age = gl_mono_ms() - best->spSinceMs;
    b->spareAgeMs = age > 0 ? (uint32_t)age : 0;
  }
}
static void gl_page_update(struct glCore* c, uint64_t nonce, int32_t rank) {
  const int i = gl_page_slot(c, nonce, rank);
  if (i < 0) return;
  struct glRegNoteBody b;
  gl_reg_words(c, nonce, rank, &b);
  const struct glEntry* best = NULL;
  for (int k = 0; k < GL_MAX_ENTRIES; k++) {
    const struct glEntry* e = &c->ent[k];
    if (e->used && e->kind == GL_E_SPARE && e->nonce == nonce && e->rank == rank && (!best || e->inc >= best->inc))
      best = e;
  }
  gl_pw(&c->page->reg[i].spareSinceMs, best ? (uint64_t)best->spSinceMs : 0);
  gl_pw(&c->page->reg[i].spare, gl_page_word(b.spareState, rank, b.spareInc));
  gl_pw(&c->page->reg[i].reg, gl_page_word(b.regState, rank, b.regInc));
}
static void gl_page_credit(struct glCore* c, const struct glPeer* p) {
  struct glPageCredit* k = &c->page->credit[p - c->peer];
  gl_pw(&k->peer, ((uint64_t)((uint32_t)p->rank & 0xffffffu) << 32) | p->inc);
  gl_pw(&k->consumed, ((uint64_t)p->rec.gen << 32) | (uint32_t)p->consumed);
  gl_pw(&k->nonce, p->nonce);
}

/* ------------------------------------------------------------------------------------------------- RNIC side out */

static void gl_msg_init(struct glCore* c, struct glMsg* m, uint16_t kind, int32_t rank, uint32_t inc, uint64_t nonce) {
  memset(m, 0, sizeof(*m));
  m->h.magic = GL_MAGIC;
  m->h.version = (uint16_t)GL_WIRE_VERSION;
  m->h.kind = kind;
  m->h.rank = rank;
  m->h.incarnation = inc;
  m->h.nonce = nonce;
  m->h.from = (int32_t)(GL_FROM_LAUNCHER | (int32_t)c->cfg.node);
  m->h.node = c->cfg.node;
  m->h.seq = ++c->seq;
  m->h.monoNs = gl_mono_ns();
}

static void gl_rec_lost(struct glCore* c, struct glPeer* p, const char* why);

static void gl_peer_send(struct glCore* c, struct glPeer* p, const struct glMsg* m) {
  if (!p->connected || p->rec.handle < 0) {  // nothing on the record QP before CONNECTED (design v2 2.5 step 3)
    if (p->nq < GL_PEER_QUEUE) p->q[p->nq++] = *m;
    else gl_log(c, "queue to rank %d full before CONNECTED: kind %u dropped", p->rank, m->h.kind);
    return;
  }
  if (c->tp->ops->rc_send(c->tp, p->rec.handle, m) != 0) gl_rec_lost(c, p, "a send failed");
}

static void gl_bcast(struct glCore* c, uint64_t nonce, const struct glMsg* m) {
  for (int i = 0; i < GL_MAX_PEERS; i++)
    if (c->peer[i].used && c->peer[i].nonce == nonce) gl_peer_send(c, &c->peer[i], m);
}

static void gl_reg_note_build(struct glCore* c, uint64_t nonce, int32_t rank, struct glMsg* m) {
  struct glRegNoteBody b;
  gl_reg_words(c, nonce, rank, &b);
  gl_msg_init(c, m, GL_K_REG_NOTE, rank, b.regInc, nonce);
  memcpy(m->body, &b, sizeof(b));
  m->h.bodyBytes = (uint16_t)sizeof(b);
}
static void gl_reg_note(struct glCore* c, uint64_t nonce, int32_t rank) {
  struct glMsg m;
  gl_page_update(c, nonce, rank);
  gl_reg_note_build(c, nonce, rank, &m);
  gl_bcast(c, nonce, &m);
}

static void gl_exit_note(struct glCore* c, uint16_t kind, int32_t rank, uint32_t inc, uint64_t nonce, uint32_t reason,
                         uint64_t seenNs, uint64_t fenceNs) {
  struct glMsg m;
  gl_msg_init(c, &m, kind, rank, inc, nonce);  // (rank, incarnation, nonce) of the ended process
  m.h.reason = reason;
  struct glExitBody b;
  b.observedMonoNs = seenNs;
  b.fenceMonoNs = fenceNs;
  memcpy(m.body, &b, sizeof(b));
  m.h.bodyBytes = (uint16_t)sizeof(b);
  gl_bcast(c, nonce, &m);
}

/* An activation answer to the buddy. rec: the record to send (the spare's, or the buddy's echoed). s: the spare (its
 * state and age go into the answer), or NULL. */
static void gl_act_answer(struct glCore* c, struct glPeer* p, uint32_t reqSeq, uint32_t kind, uint32_t reason,
                          const struct glRsActivate* rec, const struct glEntry* s, const char* why) {
  if (!p) return;
  struct glMsg m;
  gl_msg_init(c, &m, GL_K_ACT_ANSWER, rec->rank, rec->incarnation, rec->nonce);
  m.h.reqSeq = reqSeq;
  m.h.sub = kind;
  m.h.reason = reason;
  struct glActAnswerBody b;
  memset(&b, 0, sizeof(b));
  b.record = *rec;
  b.record.kind = kind;
  b.pageSlot = 0xffffffffu;
  if (s) {
    b.spareState = (uint32_t)s->sp;
    const double age = gl_mono_ms() - s->spSinceMs;
    b.spareAgeMs = age > 0 ? (uint32_t)age : 0;
    const int slot = gl_page_slot(c, s->nonce, s->rank);
    if (slot >= 0) b.pageSlot = (uint32_t)slot;
  }
  snprintf(b.why, sizeof(b.why), "%s", why ? why : gl_reason_text(reason));
  memcpy(m.body, &b, sizeof(b));
  m.h.bodyBytes = (uint16_t)sizeof(b);
  if (kind == GL_RS_ACT_LATER) c->st.nLater++;
  else if (kind == GL_RS_ACT_REFUSED) c->st.nActRefused++;
  else if (kind == GL_RS_ACT_ACCEPTED) c->st.nActAccepted++;
  gl_log(c, "activation of rank %d incarnation %d for rank %d: %s (%s)", rec->rank, (int)rec->incarnation, p->rank,
         kind == GL_RS_ACT_LATER ? "LATER" : kind == GL_RS_ACT_ACCEPTED ? "ACCEPTED" : "REFUSED", b.why);
  gl_peer_send(c, p, &m);
}
static struct glPeer* gl_act_peer(struct glCore* c, const struct glEntry* s) {
  if (s->actPeer < 0 || s->actPeer >= GL_MAX_PEERS || !c->peer[s->actPeer].used) return NULL;
  return &c->peer[s->actPeer];
}
/* The final REFUSED of a spare's pending activation, if any; the spare goes FAILED. */
static void gl_spare_fail(struct glCore* c, struct glEntry* s, uint32_t reason, int killLater) {
  gl_sp_set(s, GL_SP_FAILED);
  s->spReason = reason;
  if (s->act != GL_ACT_NONE) {
    gl_act_answer(c, gl_act_peer(c, s), s->actReqSeq, GL_RS_ACT_REFUSED, reason, &s->rec, s, NULL);
    s->act = GL_ACT_NONE;
  }
  if (killLater && !s->dead && s->pidfd >= 0 && s->killAtMs == 0) s->killAtMs = gl_mono_ms() + c->cfg.graceMs;
  gl_reg_note(c, s->nonce, s->rank);
}

/* ------------------------------------------------------------------------------------------------- Unix side out */

static int gl_unix_send(struct glCore* c, int ci, const struct glUnixMsg* u, const void* payload, size_t plen) {
  if (ci < 0 || ci >= GL_MAX_CONNS || !c->conn[ci].used) return -1;
  struct iovec iov[2];
  iov[0].iov_base = (void*)u;
  iov[0].iov_len = sizeof(*u);
  iov[1].iov_base = (void*)payload;
  iov[1].iov_len = plen;
  struct msghdr mh;
  memset(&mh, 0, sizeof(mh));
  mh.msg_iov = iov;
  mh.msg_iovlen = plen ? 2 : 1;
  const ssize_t n = sendmsg(c->conn[ci].fd, &mh, MSG_DONTWAIT | MSG_NOSIGNAL);
  return n == (ssize_t)(sizeof(*u) + plen) ? 0 : -1;
}
static void gl_unix_init(struct glUnixMsg* u, uint16_t kind, int32_t rank, uint32_t inc, uint64_t nonce) {
  memset(u, 0, sizeof(*u));
  u->h.magic = GL_U_MAGIC;
  u->h.version = (uint16_t)GL_WIRE_VERSION;
  u->h.kind = kind;
  u->h.rank = rank;
  u->h.incarnation = inc;
  u->h.nonce = nonce;
  u->h.pid = (int64_t)getpid();
  u->h.monoNs = gl_mono_ns();
}
static void gl_hello_ack(struct glCore* c, int ci, const struct glUnixMsg* req, uint32_t status, uint32_t reason) {
  struct glUnixMsg u;
  gl_unix_init(&u, GL_U_HELLO_ACK, req->h.rank, req->h.incarnation, req->h.nonce);
  u.h.sub = req->h.kind;
  u.h.reason = reason;
  struct glUHelloAck a;
  memset(&a, 0, sizeof(a));
  a.status = status;
  a.node = c->cfg.node;
  a.qkey = c->cfg.qkey;
  a.pageSlot = 0xffffffffu;
  if (status == GL_UA_OK) {
    const int slot = gl_page_slot(c, req->h.nonce, req->h.rank);
    if (slot >= 0) a.pageSlot = (uint32_t)slot;
  }
  a.ud = c->ud;
  a.page = c->pageReg;
  snprintf(a.why, sizeof(a.why), "%s", status == GL_UA_OK ? "ok" : gl_reason_text(reason));
  memcpy(u.body, &a, sizeof(a));
  u.h.bodyBytes = (uint16_t)sizeof(a);
  if (gl_unix_send(c, ci, &u, NULL, 0) != 0)
    gl_log(c, "answer to %s of rank %d could not be sent", req->h.kind == GL_U_REGISTER ? "REGISTER" : "HELLO",
           req->h.rank);
}
static void gl_to_spare(struct glCore* c, struct glEntry* s, uint32_t sub, const void* body, size_t bodyLen) {
  struct glUnixMsg u;
  gl_unix_init(&u, GL_U_ACT_TALK, s->rank, s->inc, s->nonce);
  u.h.sub = sub;
  if (bodyLen > GL_U_BODY_BYTES) bodyLen = GL_U_BODY_BYTES;
  if (bodyLen) memcpy(u.body, body, bodyLen);
  u.h.bodyBytes = (uint16_t)bodyLen;
  if (gl_unix_send(c, s->conn, &u, NULL, 0) != 0)
    gl_log(c, "talk %u to the spare of rank %d incarnation %u could not be sent", sub, s->rank, s->inc);
}

/* ------------------------------------------------------------------------------------------------- exits */

static void gl_conn_drain(struct glCore* c, int ci);

/* The entry's pidfd is readable: its thread group ended. Messages it wrote before the exit are read first (a LEAVING
 * written before exit(2) is in the socket's queue by then), so LEFT never loses to EXITED. One event, one message
 * (REVIEW2 nit 5): FENCED when a FENCE had come, else LEFT after LEAVING, else EXITED. */
static void gl_exit_seen(struct glCore* c, struct glEntry* e) {
  const uint64_t id = e->id;
  if (e->conn >= 0) gl_conn_drain(c, e->conn);
  if (!e->used || e->id != id) return;  // the drain ended it already (a re-registration saw it gone)
  const uint64_t seen = gl_mono_ns();
  if (e->kind == GL_E_SPARE && e->sp != GL_SP_ACCEPTED) {
    // a spare that never became the rank: no exit report to the ranks (REVIEW2 fix 12), only its activation answer and
    // the page's spare word
    e->dead = 1;
    gl_close_pidfd(c, &e->pidfd);
    gl_log(c, "spare of rank %d incarnation %u ended (state %d)", e->rank, e->inc, e->sp);
    if (e->sp == GL_SP_ABORTED) {
      e->act = GL_ACT_NONE;
      gl_reg_note(c, e->nonce, e->rank);
      return;
    }
    if (e->sp != GL_SP_FAILED) gl_spare_fail(c, e, GL_R_SPARE_EXITED, 0);
    else gl_reg_note(c, e->nonce, e->rank);
    return;
  }
  // a registered rank (or a spare accepted as the rank's next incarnation and not yet re-registered)
  uint32_t how;
  if (e->fenceAsked) {
    how = GL_K_FENCED;
    c->st.nFenced++;
    const uint32_t r = e->signalled ? GL_R_FENCE_KILLED : e->leaving ? GL_R_ALREADY_LEFT : GL_R_ALREADY_EXITED;
    gl_exit_note(c, GL_K_FENCED, e->rank, e->inc, e->nonce, r, seen, e->signalled ? e->fenceNs : 0);
    if (e->signalled)
      gl_log(c, "rank %d incarnation %u FENCED: the group ended %.3f ms after SIGKILL through its pidfd", e->rank,
             e->inc, (double)(seen - e->fenceNs) / 1e6);
    else gl_log(c, "rank %d incarnation %u FENCED: it had ended before the FENCE (%s)", e->rank, e->inc, gl_reason_text(r));
  } else if (e->leaving) {
    how = GL_K_LEFT;
    c->st.nLeft++;
    gl_exit_note(c, GL_K_LEFT, e->rank, e->inc, e->nonce, GL_R_NONE, seen, 0);
    gl_log(c, "rank %d incarnation %u left (LEAVING, then the group ended)", e->rank, e->inc);
  } else {
    how = GL_K_EXITED;
    if (c->cfg.noExitReport) {
      gl_log(c, "rank %d incarnation %u exited; EXITED not sent (test switch NO_EXIT_REPORT)", e->rank, e->inc);
    } else {
      c->st.nExited++;
      gl_exit_note(c, GL_K_EXITED, e->rank, e->inc, e->nonce, GL_R_SELF_EXIT, seen, 0);
      gl_log(c, "rank %d incarnation %u EXITED (its pidfd is readable: the thread group ended)", e->rank, e->inc);
    }
  }
  gl_tomb_add(c, e, how);
  const uint64_t nonce = e->nonce;
  const int32_t rank = e->rank;
  gl_entry_free(c, e);
  gl_reg_note(c, nonce, rank);
}

/* ------------------------------------------------------------------------------------------------- activation */

static void gl_handover(struct glCore* c, struct glEntry* s) {
  struct glUnixMsg u;
  gl_unix_init(&u, GL_U_ACT_BYTES, s->rank, s->inc, s->nonce);
  memcpy(u.body, &s->rec, sizeof(s->rec));
  u.h.bodyBytes = (uint16_t)sizeof(s->rec);
  u.h.payloadBytes = s->blob.len;
  if (gl_unix_send(c, s->conn, &u, s->blobBuf, s->blob.len) != 0) {
    gl_log(c, "the activation bytes could not be handed to the spare of rank %d incarnation %u", s->rank, s->inc);
    gl_spare_fail(c, s, GL_R_SEND_FAILED, 1);
    return;
  }
  gl_blob_release(c, s);  // the READ completed: no READ in flight
  s->act = GL_ACT_GIVEN;
  gl_sp_set(s, GL_SP_OFFERED);
  gl_log(c, "activation of rank %d incarnation %u handed to its spare (%u blob bytes)", s->rank, s->inc, s->blob.len);
  gl_reg_note(c, s->nonce, s->rank);
}
static void gl_offer(struct glCore* c, struct glEntry* s) {
  struct glPeer* p = gl_act_peer(c, s);
  if (s->blob.len == 0) {
    gl_handover(c, s);
    return;
  }
  gl_blob_release(c, s);
  s->blobBuf = (uint8_t*)malloc(s->blob.len);
  if (!s->blobBuf || !p || p->rec.handle < 0) {
    gl_spare_fail(c, s, GL_R_BLOB_READ_FAILED, 1);
    return;
  }
  s->act = GL_ACT_READ;
  s->serial = ++c->serial;
  const uint64_t cookie = ((uint64_t)(s - c->ent) << 32) | s->serial;
  if (c->tp->ops->rc_read(c->tp, p->rec.handle, s->blob.addr, s->blob.rkey, s->blob.len, s->blobBuf, cookie) != 0) {
    gl_spare_fail(c, s, GL_R_BLOB_READ_FAILED, 1);
    return;
  }
  s->readBusy = 1;
  s->readHandle = p->rec.handle;
}
static void gl_read_done(struct glCore* c, int handle, uint64_t cookie, int status) {
  gl_orphans_free(c, handle, 1, cookie);  // an orphaned buffer's READ ended: now it may go
  const uint64_t idx = cookie >> 32;
  if (idx >= GL_MAX_ENTRIES) return;
  struct glEntry* s = &c->ent[idx];
  if (!s->used || s->kind != GL_E_SPARE || s->serial != (uint32_t)cookie || !s->readBusy) return;
  s->readBusy = 0;
  s->readHandle = -1;
  if (s->act != GL_ACT_READ) {  // aborted or failed while the READ was in flight: the buffer goes now
    gl_blob_release(c, s);
    return;
  }
  if (status != 0) {
    gl_spare_fail(c, s, GL_R_BLOB_READ_FAILED, 1);
    return;
  }
  gl_handover(c, s);
}

static void gl_activate(struct glCore* c, struct glPeer* p, const struct glMsg* m) {
  struct glActivateBody ab;
  memcpy(&ab, m->body, sizeof(ab));
  const struct glRsActivate* rec = &ab.record;
  const uint32_t rq = m->h.seq;
  if (rec->magic != GL_RS_ACT_MAGIC || rec->kind != GL_RS_ACT_ACTIVATE)
    return gl_act_answer(c, p, rq, GL_RS_ACT_REFUSED, GL_R_BAD_MSG, rec, NULL, NULL);
  if (rec->nonce != p->nonce) return gl_act_answer(c, p, rq, GL_RS_ACT_REFUSED, GL_R_NONCE, rec, NULL, NULL);
  if (ab.blob.len > GL_U_MAX_PAYLOAD)
    return gl_act_answer(c, p, rq, GL_RS_ACT_REFUSED, GL_R_BLOB_TOO_BIG, rec, NULL, NULL);
  const int32_t d = rec->rank;
  const uint32_t ni = rec->incarnation;
  // the registration: the dead original must be (rank, ni - 1), and gone
  struct glEntry* o = gl_find(c, GL_E_ORIG, rec->nonce, d);
  if (o) {
    if ((uint64_t)o->inc + 1u != (uint64_t)ni)
      return gl_act_answer(c, p, rq, GL_RS_ACT_REFUSED, GL_R_INCARNATION, rec, NULL, NULL);
    if (!gl_readable(o->pidfd))
      return gl_act_answer(c, p, rq, GL_RS_ACT_REFUSED, GL_R_ORIGINAL_ALIVE, rec, NULL, NULL);
    gl_exit_seen(c, o);  // its exit report first
  } else {
    const struct glTomb* t = gl_tomb_last(c, rec->nonce, d);
    if (!t) return gl_act_answer(c, p, rq, GL_RS_ACT_REFUSED, GL_R_NOT_REGISTERED, rec, NULL, NULL);
    if ((uint64_t)t->inc + 1u != (uint64_t)ni)
      return gl_act_answer(c, p, rq, GL_RS_ACT_REFUSED, GL_R_INCARNATION, rec, NULL, NULL);
  }
  struct glEntry* s = gl_find_spare(c, rec->nonce, d, ni);
  if (!s) return gl_act_answer(c, p, rq, GL_RS_ACT_REFUSED, GL_R_NO_SPARE, rec, NULL, NULL);
  if (s->dead || s->sp == GL_SP_FAILED)
    return gl_act_answer(c, p, rq, GL_RS_ACT_REFUSED, s->spReason ? s->spReason : GL_R_SPARE_EXITED, rec, s, NULL);
  if (s->act != GL_ACT_NONE || s->sp == GL_SP_OFFERED || s->sp == GL_SP_ACCEPTED || s->sp == GL_SP_ABORTED)
    return gl_act_answer(c, p, rq, GL_RS_ACT_REFUSED, GL_R_ALREADY_OFFERED, rec, s, NULL);
  s->act = GL_ACT_WAIT;
  s->actPeer = (int)(p - c->peer);
  s->actReqSeq = rq;
  s->rec = *rec;
  s->blob = ab.blob;
  if (s->sp == GL_SP_REPLAYING) {
    if (!s->laterSent) {  // exactly once per activation (decision 4); the final answer follows READY
      s->laterSent = 1;
      gl_act_answer(c, p, rq, GL_RS_ACT_LATER, GL_R_SPARE_REPLAYING, rec, s, NULL);
    }
    return;
  }
  gl_offer(c, s);  // READY
}

static void gl_abort(struct glCore* c, struct glEntry* s, const char* why) {
  if (s->sp == GL_SP_FAILED || s->sp == GL_SP_ABORTED || s->dead) return;
  gl_log(c, "activation of rank %d incarnation %u aborted (%s); the spare is told and SIGKILLed through its pidfd "
            "after %d ms if still there",
         s->rank, s->inc, why, c->cfg.graceMs);
  if (s->conn >= 0) gl_to_spare(c, s, GL_UT_ABORT, NULL, 0);
  gl_sp_set(s, GL_SP_ABORTED);
  s->spReason = GL_R_ABORTED;
  s->act = GL_ACT_NONE;
  if (!s->readBusy) gl_blob_release(c, s);  // a READ in flight keeps the buffer until it completes (gl_read_done)
  s->killAtMs = gl_mono_ms() + c->cfg.graceMs;
  gl_reg_note(c, s->nonce, s->rank);
}
/* The buddy's launcher QP failed, was re-paired or the buddy was replaced: an activation still in flight (WAIT, READ,
 * OFFERED) is aborted. An ACCEPTED one is not (REVIEW_PREP fix 12): the spare is becoming the rank, and a connectivity
 * blip of the buddy's QP must not SIGKILL it; only the buddy's explicit ABORT or a FENCE of (rank, inc) ends it. The
 * relayed FETCH talk waits in the peer's queue until the QP is re-paired. */
static void gl_abort_of_peer(struct glCore* c, struct glPeer* p, const char* why) {
  const int pi = (int)(p - c->peer);
  for (int i = 0; i < GL_MAX_ENTRIES; i++) {
    struct glEntry* s = &c->ent[i];
    if (!s->used || s->kind != GL_E_SPARE || s->actPeer != pi) continue;
    if (s->sp == GL_SP_ACCEPTED) {
      gl_log(c, "activation of rank %d incarnation %u is ACCEPTED: kept although %s (an ABORT or a FENCE ends it)", s->rank,
             s->inc, why);
      continue;
    }
    if (s->act != GL_ACT_NONE || s->sp == GL_SP_OFFERED) gl_abort(c, s, why);
  }
}

/* ------------------------------------------------------------------------------------------------- fence */

static void gl_fence(struct glCore* c, struct glPeer* p, const struct glMsg* m) {
  const int32_t r = m->h.rank;
  const uint32_t inc = m->h.incarnation;
  const uint64_t nonce = m->h.nonce;
  struct glEntry* e = gl_find(c, GL_E_ORIG, nonce, r);
  if (e && e->inc != inc) e = NULL;
  if (!e) {
    struct glEntry* s = gl_find_spare(c, nonce, r, inc);
    if (s && !s->dead && s->sp == GL_SP_ACCEPTED) e = s;  // the accepted next incarnation, not yet re-registered
  }
  if (e) {
    e->fenceAsked = 1;
    if (gl_readable(e->pidfd)) {  // gone already: one FENCED for that exit (it replaces EXITED and LEFT)
      gl_exit_seen(c, e);
      return;
    }
    if (e->signalled) return;  // a second FENCE: the first one's FENCED comes when the group ends
    if (gl_signal(c, e, SIGKILL) == 0) {
      e->signalled = 1;
      e->fenceNs = gl_mono_ns();
      gl_log(c, "FENCE of rank %d incarnation %u from rank %d: SIGKILL sent through its pidfd (pid %d)", r, inc,
             p->rank, (int)e->pid);
    } else {
      gl_log(c, "FENCE of rank %d incarnation %u: pidfd_send_signal failed (%s); waiting for its pidfd", r, inc,
             strerror(errno));
    }
    return;
  }
  const struct glTomb* t = gl_tomb_of(c, nonce, r, inc);
  if (t) {
    c->st.nFenced++;
    gl_exit_note(c, GL_K_FENCED, r, inc, nonce,
                 t->how == GL_K_LEFT ? GL_R_ALREADY_LEFT : t->how == GL_K_FENCED ? GL_R_FENCE_KILLED
                                                                                 : GL_R_ALREADY_EXITED,
                 gl_mono_ns(), 0);
    gl_log(c, "FENCE of rank %d incarnation %u from rank %d: already ended; FENCED", r, inc, p->rank);
    return;
  }
  struct glMsg n;
  gl_msg_init(c, &n, GL_K_FENCE_NAK, r, inc, nonce);
  n.h.reqSeq = m->h.seq;
  n.h.reason = GL_R_NOT_HELD;
  c->st.nFenceNak++;
  gl_log(c, "FENCE of rank %d incarnation %u from rank %d: refused to signal: no pidfd held for it (STOP_launcher)", r,
         inc, p->rank);
  gl_peer_send(c, p, &n);
}

/* ------------------------------------------------------------------------------------------------- pairing */

static void gl_abort(struct glCore* c, struct glEntry* s, const char* why);
/* rc_close: no completion of that QP follows, and no DMA: the READ buffers on it can go. An entry still reading on it is
 * aborted (every caller aborted it first; this is the guard, and it sends nothing on the closing QP). */
static void gl_rc_close(struct glCore* c, int handle) {
  if (handle < 0) return;
  c->tp->ops->rc_close(c->tp, handle);
  for (int i = 0; i < GL_MAX_ENTRIES; i++) {
    struct glEntry* s = &c->ent[i];
    if (!s->used || !s->readBusy || s->readHandle != handle) continue;
    s->readBusy = 0;
    s->readHandle = -1;
    if (s->act == GL_ACT_READ) gl_abort(c, s, "the QP of its blob READ closed");
    gl_blob_release(c, s);
  }
  gl_orphans_free(c, handle, 0, 0);
}
static void gl_qp_close(struct glCore* c, struct glQp* q) {
  gl_rc_close(c, q->handle);
  q->handle = -1;
  q->haveAck = 0;
}
static void gl_repair_stop(struct glCore* c, struct glPeer* p) {
  if (p->repair && p->repairHandle >= 0) gl_rc_close(c, p->repairHandle);
  p->repair = 0;
  p->repairHandle = -1;
}
static void gl_peer_clear(struct glCore* c, struct glPeer* p) {
  gl_qp_close(c, &p->rec);
  gl_qp_close(c, &p->probe);
  gl_repair_stop(c, p);
  memset(p, 0, sizeof(*p));
  p->rec.handle = p->probe.handle = p->repairHandle = -1;
}

/* The launcher starts the re-pairing of p's record QP (REVIEW2 block 4: the side that sees the error starts). */
static void gl_repair_start(struct glCore* c, struct glPeer* p) {
  if (p->ud.qpn == 0) return;  // never paired over UD: nowhere to send
  gl_repair_stop(c, p);
  p->repairGen = p->rec.gen + 1u;
  memset(&p->repairLocal, 0, sizeof(p->repairLocal));
  p->repairHandle = c->tp->ops->rc_create(c->tp, GL_PAIR_RECORD, p->repairGen, p->nonce, &p->repairLocal);
  if (p->repairHandle < 0) return;
  p->repair = 1;
  struct glMsg* m = &p->repairPair;
  gl_msg_init(c, m, GL_K_PAIR, p->rank, p->inc, p->nonce);
  m->h.sub = GL_PAIR_RECORD;
  struct glPairBody b;
  memset(&b, 0, sizeof(b));
  b.gen = p->repairGen;
  b.qkey = c->cfg.qkey;
  b.qp = p->repairLocal;
  b.ud = c->ud;
  b.page = c->pageReg;
  b.creditOff = GL_PAGE_CREDIT_OFF(p - c->peer);
  memcpy(m->body, &b, sizeof(b));
  m->h.bodyBytes = (uint16_t)sizeof(b);
  const double now = gl_mono_ms();
  p->repairEndMs = now + GL_REPAIR_MS;
  p->repairNextMs = now + GL_REPAIR_EVERY_MS;
  c->tp->ops->ud_send(c->tp, &p->ud, p->qkey, m);
  c->st.nRepairStarted++;
  gl_log(c, "record QP of rank %d lost: re-pairing started (generation %u)", p->rank, p->repairGen);
}

static void gl_rec_lost(struct glCore* c, struct glPeer* p, const char* why) {
  gl_log(c, "record QP of rank %d (incarnation %u, generation %u) lost: %s", p->rank, p->inc, p->rec.gen, why);
  gl_abort_of_peer(c, p, "the buddy's launcher QP failed");
  gl_qp_close(c, &p->rec);
  p->connected = 0;
  p->consumed = 0;
  gl_repair_start(c, p);
}

static struct glPeer* gl_peer_bind(struct glCore* c, uint64_t nonce, int32_t rank) {
  struct glPeer* p = gl_peer_find(c, nonce, rank);
  if (p) return p;
  for (int i = 0; i < GL_MAX_PEERS; i++)
    if (!c->peer[i].used) {
      p = &c->peer[i];
      memset(p, 0, sizeof(*p));
      p->used = 1;
      p->nonce = nonce;
      p->rank = rank;
      p->rec.handle = p->probe.handle = p->repairHandle = -1;
      return p;
    }
  return NULL;
}

static void gl_send_connected(struct glCore* c, struct glPeer* p);

static void gl_on_pair(struct glCore* c, const struct glMsg* m) {
  struct glPairBody b;
  memcpy(&b, m->body, sizeof(b));
  const int kind = (int)m->h.sub;
  if (kind != GL_PAIR_RECORD && kind != GL_PAIR_PROBE) {
    c->st.nBadMsg++;
    return;
  }
  struct glPeer* p = gl_peer_find(c, m->h.nonce, m->h.rank);
  if (p && m->h.incarnation < p->inc) {
    gl_log(c, "PAIR of rank %d incarnation %u older than the paired %u: dropped", m->h.rank, m->h.incarnation, p->inc);
    return;
  }
  if (p && m->h.incarnation > p->inc) {  // the revived process: its old QPs go
    gl_abort_of_peer(c, p, "the buddy was replaced");
    gl_qp_close(c, &p->rec);
    gl_qp_close(c, &p->probe);
    gl_repair_stop(c, p);
    p->connected = 0;
    p->consumed = 0;
    p->nq = 0;
    p->rec.gen = p->probe.gen = 0;
  }
  if (!p) p = gl_peer_bind(c, m->h.nonce, m->h.rank);
  struct glMsg a;
  gl_msg_init(c, &a, GL_K_PAIR_ACK, m->h.rank, m->h.incarnation, m->h.nonce);
  a.h.reqSeq = m->h.seq;
  a.h.sub = (uint32_t)kind;
  struct glPairAckBody ab;
  memset(&ab, 0, sizeof(ab));
  ab.gen = b.gen;
  ab.page = c->pageReg;
  ab.qkey = c->cfg.qkey;
  if (!p) {
    ab.status = 1;
    a.h.reason = GL_R_TABLE_FULL;
    memcpy(a.body, &ab, sizeof(ab));
    a.h.bodyBytes = (uint16_t)sizeof(ab);
    c->tp->ops->ud_send(c->tp, &b.ud, b.qkey, &a);
    gl_log(c, "PAIR of rank %d refused (%s)", m->h.rank, gl_reason_text(a.h.reason));
    return;
  }
  ab.creditOff = GL_PAGE_CREDIT_OFF(p - c->peer);
  struct glQp* q = kind == GL_PAIR_RECORD ? &p->rec : &p->probe;
  // REVIEW_PREP nit 13: an older generation is dropped whether or not its QP is still there, and so is the generation of
  // a QP already lost (a late copy of its PAIR; a new pairing is gen + 1)
  if (b.gen < q->gen || (q->handle < 0 && q->gen != 0 && b.gen == q->gen)) {
    gl_log(c, "PAIR (%s) of rank %d generation %u, the paired one %u%s: dropped",
           kind == GL_PAIR_RECORD ? "record" : "probe", m->h.rank, b.gen, q->gen, q->handle < 0 ? " (lost)" : "");
    return;
  }
  if (q->handle >= 0 && b.gen == q->gen && b.qp.qpn == q->remote.qpn && q->haveAck) {
    c->tp->ops->ud_send(c->tp, &b.ud, b.qkey, &q->ack);  // the same PAIR again: the same answer
    c->st.nPairAck++;
    return;
  }
  if (kind == GL_PAIR_RECORD && p->repair) {
    if (b.gen < p->repairGen) {
      gl_log(c, "PAIR of rank %d generation %u older than the launcher's own re-pairing %u: dropped", m->h.rank, b.gen,
             p->repairGen);
      return;
    }
    gl_repair_stop(c, p);  // both started: the rank's PAIR wins (the lower `from`)
  }
  if (kind == GL_PAIR_RECORD && q->handle >= 0) {  // a newer generation replaces the record QP: in-flight is lost
    gl_abort_of_peer(c, p, "the buddy re-paired its launcher QP");
  }
  gl_qp_close(c, q);
  struct glEp local;
  memset(&local, 0, sizeof(local));
  int h = c->tp->ops->rc_create(c->tp, kind, b.gen, m->h.nonce, &local);
  if (h >= 0 && c->tp->ops->rc_connect(c->tp, h, &b.qp) != 0) {
    gl_rc_close(c, h);
    h = -1;
  }
  if (h < 0) {
    ab.status = 1;
    a.h.reason = GL_R_BAD_MSG;
    memcpy(a.body, &ab, sizeof(ab));
    a.h.bodyBytes = (uint16_t)sizeof(ab);
    c->tp->ops->ud_send(c->tp, &b.ud, b.qkey, &a);
    gl_log(c, "PAIR of rank %d refused: the QP could not be set up", m->h.rank);
    return;
  }
  p->inc = m->h.incarnation;
  p->ud = b.ud;
  p->qkey = b.qkey;
  p->page = b.page;
  p->creditOff = b.creditOff;
  q->handle = h;
  q->gen = b.gen;
  q->remote = b.qp;
  ab.qp = local;
  memcpy(a.body, &ab, sizeof(ab));
  a.h.bodyBytes = (uint16_t)sizeof(ab);
  q->ack = a;
  q->haveAck = 1;
  if (kind == GL_PAIR_RECORD) {
    p->connected = 0;  // the rank started: its CONNECTED comes first
    p->consumed = 0;
    c->tp->ops->rc_credit_at(c->tp, h, &b.page, b.creditOff);
    gl_page_credit(c, p);
  }
  c->tp->ops->ud_send(c->tp, &b.ud, b.qkey, &a);
  c->st.nPairAck++;
  gl_log(c, "paired (%s) with rank %d (incarnation %u, generation %u)", kind == GL_PAIR_RECORD ? "record" : "probe",
         p->rank, p->inc, q->gen);
}

/* The answer to the launcher's own PAIR (its re-pairing of a record QP). */
static void gl_on_pair_ack(struct glCore* c, const struct glMsg* m) {
  struct glPairAckBody b;
  memcpy(&b, m->body, sizeof(b));
  struct glPeer* p = gl_peer_find(c, m->h.nonce, m->h.rank);
  if (!p || !p->repair || m->h.sub != GL_PAIR_RECORD || b.gen != p->repairGen) return;
  if (b.status != 0) {
    gl_log(c, "re-pairing of rank %d refused by it (%s); trying again", p->rank, gl_reason_text(m->h.reason));
    return;
  }
  if (c->tp->ops->rc_connect(c->tp, p->repairHandle, &b.qp) != 0) {
    gl_log(c, "re-pairing of rank %d: the QP could not be connected", p->rank);
    return;
  }
  gl_qp_close(c, &p->rec);
  p->rec.handle = p->repairHandle;
  p->rec.gen = p->repairGen;
  p->rec.remote = b.qp;
  p->rec.haveAck = 0;
  p->repair = 0;
  p->repairHandle = -1;
  p->page = b.page;
  p->creditOff = b.creditOff;
  p->consumed = 0;
  c->tp->ops->rc_credit_at(c->tp, p->rec.handle, &b.page, b.creditOff);
  gl_page_credit(c, p);
  c->st.nRepaired++;
  gl_log(c, "record QP of rank %d re-paired (generation %u)", p->rank, p->rec.gen);
  gl_send_connected(c, p);  // the launcher started: it sends CONNECTED first
}

static void gl_flush(struct glCore* c, struct glPeer* p) {
  for (int i = 0; i < p->nq; i++)
    if (c->tp->ops->rc_send(c->tp, p->rec.handle, &p->q[i]) != 0) {
      p->nq = 0;
      gl_rec_lost(c, p, "a send failed");
      return;
    }
  p->nq = 0;
}
/* Every registration this launcher holds for p's communicator. */
static void gl_notes_to(struct glCore* c, struct glPeer* p) {
  int32_t seen[GL_MAX_ENTRIES + GL_PAGE_REGS];
  int ns = 0;
  for (int i = 0; i < GL_PAGE_REGS; i++)
    if (c->page->reg[i].nonce == p->nonce && ns < (int)(sizeof(seen) / sizeof(seen[0]))) {
      const int32_t r = gl_page_word_rank(c->page->reg[i].reg);
      struct glMsg m;
      gl_reg_note_build(c, p->nonce, r, &m);
      seen[ns++] = r;
      gl_peer_send(c, p, &m);
      if (!p->used || !p->connected) return;
    }
}
static void gl_send_connected(struct glCore* c, struct glPeer* p) {
  struct glMsg m;
  gl_msg_init(c, &m, GL_K_CONNECTED, p->rank, p->inc, p->nonce);
  if (c->tp->ops->rc_send(c->tp, p->rec.handle, &m) != 0) {
    gl_rec_lost(c, p, "CONNECTED could not be sent");
    return;
  }
  p->connected = 1;
  gl_flush(c, p);
  if (p->connected) gl_notes_to(c, p);
}
static void gl_on_connected(struct glCore* c, struct glPeer* p) {
  p->connected = 1;
  gl_flush(c, p);
  if (p->connected) gl_notes_to(c, p);
}

/* ------------------------------------------------------------------------------------------------- RNIC side in */

static void gl_on_rc(struct glCore* c, int handle, const struct glMsg* m) {
  int kind = 0;
  struct glPeer* p = gl_peer_of_handle(c, handle, &kind);
  if (!p || kind != GL_PAIR_RECORD) return;  // nothing arrives on a probe QP (no RQ)
  p->consumed++;
  gl_page_credit(c, p);
  const uint32_t bad = gl_msg_check(m);
  if (bad == GL_R_BAD_MSG) {
    c->st.nBadMsg++;
    return;
  }
  if (!p->connected) {
    gl_on_connected(c, p);
    if (!p->used || !p->connected) return;
    if (m->h.kind == GL_K_CONNECTED) return;
  }
  struct glMsg r;
  if (bad == GL_R_UNKNOWN_KIND) goto refuse_kind;
  if (m->h.kind != GL_K_CONNECTED && m->h.nonce != p->nonce) {
    gl_msg_init(c, &r, m->h.kind == GL_K_FENCE ? GL_K_FENCE_NAK : GL_K_REFUSED, m->h.rank, m->h.incarnation, m->h.nonce);
    r.h.reqSeq = m->h.seq;
    r.h.sub = m->h.kind;
    r.h.reason = GL_R_NONCE;
    gl_peer_send(c, p, &r);
    return;
  }
  switch (m->h.kind) {
    case GL_K_CONNECTED: return;
    case GL_K_FENCE: gl_fence(c, p, m); return;
    case GL_K_ACTIVATE: gl_activate(c, p, m); return;
    case GL_K_ABORT: {
      struct glEntry* s = gl_find_spare(c, m->h.nonce, m->h.rank, m->h.incarnation);
      if (s) gl_abort(c, s, "the buddy's ABORT");
      else gl_log(c, "ABORT of rank %d incarnation %u: no spare here", m->h.rank, m->h.incarnation);
      return;
    }
    case GL_K_FETCH_READY: {
      struct glEntry* s = gl_find_spare(c, m->h.nonce, m->h.rank, m->h.incarnation);
      if (s && s->sp == GL_SP_ACCEPTED && s->actPeer == (int)(p - c->peer))
        gl_to_spare(c, s, GL_UT_FETCH_READY, m->body, GL_FETCH_READY_BYTES);
      else gl_log(c, "FETCH READY for rank %d incarnation %u without an accepted activation: dropped", m->h.rank,
                  m->h.incarnation);
      return;
    }
    case GL_K_SPAWN: {
      gl_msg_init(c, &r, GL_K_REFUSED, m->h.rank, m->h.incarnation, m->h.nonce);
      r.h.reqSeq = m->h.seq;
      r.h.sub = GL_K_SPAWN;
      r.h.reason = GL_R_SPAWN_NOT_BUILT;
      snprintf((char*)r.body, GL_BODY_BYTES, "%s", gl_reason_text(GL_R_SPAWN_NOT_BUILT));
      r.h.bodyBytes = (uint16_t)(strlen((char*)r.body) + 1);
      c->st.nSpawnRefused++;
      gl_log(c, "SPAWN of rank %d incarnation %u from rank %d: REFUSED (spawn not built)", m->h.rank, m->h.incarnation,
             p->rank);
      gl_peer_send(c, p, &r);
      return;
    }
    default: break;
  }
refuse_kind:
  gl_msg_init(c, &r, GL_K_REFUSED, m->h.rank, m->h.incarnation, m->h.nonce);
  r.h.reqSeq = m->h.seq;
  r.h.sub = m->h.kind;
  r.h.reason = GL_R_UNKNOWN_KIND;
  c->st.nBadMsg++;
  gl_peer_send(c, p, &r);
}

static void gl_on_rc_error(struct glCore* c, int handle) {
  int kind = 0;
  struct glPeer* p = gl_peer_of_handle(c, handle, &kind);
  if (!p) return;
  if (kind == GL_PAIR_PROBE) {  // the rank re-pairs it (it is the reader); the launcher only drops its end
    gl_log(c, "liveness-READ QP of rank %d failed: closed (the rank re-pairs it)", p->rank);
    gl_qp_close(c, &p->probe);
    return;
  }
  if (kind == 0) {  // the launcher's own re-pairing QP failed: try again with a new one
    gl_repair_start(c, p);
    return;
  }
  gl_rec_lost(c, p, "the QP reported an error");
}

static void gl_transport_events(struct glCore* c) {
  struct glTpEvent ev[16];
  for (;;) {
    const int n = c->tp->ops->poll(c->tp, ev, 16);
    if (n <= 0) return;
    for (int i = 0; i < n; i++) {
      switch (ev[i].type) {
        case GL_TP_UD_RECV:
          if (gl_msg_check(&ev[i].msg) != GL_R_NONE) c->st.nBadMsg++;
          else if (ev[i].msg.h.kind == GL_K_PAIR) gl_on_pair(c, &ev[i].msg);
          else if (ev[i].msg.h.kind == GL_K_PAIR_ACK) gl_on_pair_ack(c, &ev[i].msg);
          else c->st.nBadMsg++;
          break;
        case GL_TP_RC_RECV: gl_on_rc(c, ev[i].peer, &ev[i].msg); break;
        case GL_TP_READ_DONE: gl_read_done(c, ev[i].peer, ev[i].cookie, ev[i].status); break;
        case GL_TP_RC_ERROR: gl_on_rc_error(c, ev[i].peer); break;
        case GL_TP_FATAL:
          if (!c->fatal) gl_log(c, "the RNIC transport failed (status %d): the launcher stops (STOP_launcher)", ev[i].status);
          c->fatal = 1;
          break;
        default: break;
      }
    }
  }
}

/* ------------------------------------------------------------------------------------------------- Unix side in */

/* The passed fd must be a pidfd of the connecting process (SO_PEERCRED pid), whose start time is the one seen at
 * connect (REVIEW2 fix 11: never switched off). */
static uint32_t gl_fd_check(struct glCore* c, int ci, int fd, pid_t* pid) {
  if (c->conn[ci].uid != c->cfg.uid) return GL_R_UID;
  if (fd < 0) return GL_R_BAD_FD;
  const int p = gl_pidfd_pid(fd);
  if (p == -2) return GL_R_BAD_FD;
  if (p != c->conn[ci].pid || c->conn[ci].start == 0 || gl_pid_start((pid_t)p) != c->conn[ci].start)
    return GL_R_PID_MISMATCH;
  *pid = (pid_t)p;
  return GL_R_NONE;
}
static void gl_refuse_hello(struct glCore* c, int ci, const struct glUnixMsg* u, int fd, uint32_t why) {
  if (fd >= 0) {
    close(fd);
    c->st.nPidfdClosed++;
  }
  c->st.nRegRefused++;
  gl_log(c, "%s of rank %d incarnation %u refused: %s%s", u->h.kind == GL_U_REGISTER ? "REGISTER" : "spare HELLO",
         u->h.rank, u->h.incarnation, gl_reason_text(why),
         why == GL_R_PID_MISMATCH ? " (STOP_launcher: a pidfd that is not the peer's own)" : "");
  gl_hello_ack(c, ci, u, GL_UA_REFUSED, why);
}

static void gl_register(struct glCore* c, int ci, const struct glUnixMsg* u, int fd) {
  pid_t pid = -1;
  uint32_t why = gl_fd_check(c, ci, fd, &pid);
  const uint64_t n = u->h.nonce;
  const int32_t d = u->h.rank;
  const uint32_t inc = u->h.incarnation;
  if (why == GL_R_NONE && (d < 0 || n == 0)) why = GL_R_BAD_MSG;
  if (why == GL_R_NONE && gl_page_slot(c, n, d) < 0) why = GL_R_TABLE_FULL;
  struct glEntry* o = why == GL_R_NONE ? gl_find(c, GL_E_ORIG, n, d) : NULL;
  struct glEntry* s = why == GL_R_NONE ? gl_find_spare(c, n, d, inc) : NULL;
  if (s && s->dead) s = NULL;
  if (why == GL_R_NONE && s) {  // the revived rank's re-registration: the accepted spare becomes the registered rank
    if (s->sp != GL_SP_ACCEPTED) why = GL_R_SPARE_NOT_ACTIVATED;
    else if (s->pid != pid) why = GL_R_PID_MISMATCH;
    else if (o && o->inc >= inc) why = GL_R_STALE;
    else if (o && !gl_readable(o->pidfd)) why = GL_R_OLDER_ALIVE;
    if (why == GL_R_NONE) {
      if (o) gl_exit_seen(c, o);
      gl_close_pidfd(c, &s->pidfd);  // the HELLO's pidfd: the new one replaces it
      s->pidfd = fd;
      s->kind = GL_E_ORIG;
      s->conn = ci;
      gl_sp_set(s, GL_SP_NONE);
      s->act = GL_ACT_NONE;
      s->laterSent = 0;
      s->actPeer = -1;
      s->fenceAsked = s->signalled = 0;
      s->killAtMs = 0;
      c->st.nPromoted++;
      c->st.nRegistered++;
      gl_log(c, "rank %d incarnation %u re-registered (the revived process, pid %d): its pidfd swapped", d, inc, (int)pid);
      gl_hello_ack(c, ci, u, GL_UA_OK, GL_R_NONE);
      gl_reg_note(c, n, d);
      return;
    }
  } else if (why == GL_R_NONE && o) {
    if (o->inc == inc) why = GL_R_DUPLICATE;
    else if (o->inc > inc) why = GL_R_STALE;
    else if (!gl_readable(o->pidfd)) why = GL_R_OLDER_ALIVE;
    else gl_exit_seen(c, o);
  }
  if (why == GL_R_NONE) {
    const struct glTomb* t = gl_tomb_last(c, n, d);
    if (t && inc <= t->inc) why = GL_R_STALE;
  }
  struct glEntry* e = NULL;
  if (why == GL_R_NONE && !(e = gl_entry_new(c))) why = GL_R_TABLE_FULL;
  if (why != GL_R_NONE) return gl_refuse_hello(c, ci, u, fd, why);
  e->kind = GL_E_ORIG;
  e->rank = d;
  e->inc = inc;
  e->nonce = n;
  e->pidfd = fd;
  e->pid = pid;
  e->conn = ci;
  c->st.nRegistered++;
  gl_log(c, "rank %d incarnation %u registered (pid %d)", d, inc, (int)pid);
  gl_hello_ack(c, ci, u, GL_UA_OK, GL_R_NONE);
  gl_reg_note(c, n, d);
}

static void gl_spare_hello(struct glCore* c, int ci, const struct glUnixMsg* u, int fd) {
  pid_t pid = -1;
  uint32_t why = gl_fd_check(c, ci, fd, &pid);
  const uint64_t n = u->h.nonce;
  const int32_t d = u->h.rank;
  const uint32_t inc = u->h.incarnation;
  if (why == GL_R_NONE && (d < 0 || n == 0 || inc == 0)) why = GL_R_BAD_MSG;
  if (why == GL_R_NONE && gl_page_slot(c, n, d) < 0) why = GL_R_TABLE_FULL;
  struct glEntry* s = why == GL_R_NONE ? gl_find_spare(c, n, d, inc) : NULL;
  if (why == GL_R_NONE && s && !s->dead) why = GL_R_DUPLICATE;
  if (why == GL_R_NONE) {
    const struct glEntry* o = gl_find(c, GL_E_ORIG, n, d);
    const struct glTomb* t = gl_tomb_last(c, n, d);
    if (o && o->inc >= inc) why = GL_R_STALE;
    else if (o && o->inc + 1u != inc) why = GL_R_INCARNATION;
    else if (!o && t && inc <= t->inc) why = GL_R_STALE;
  }
  if (why == GL_R_NONE) {
    if (s) gl_entry_reset(c, s);  // a dead spare's slot of the same (rank, incarnation)
    else if (!(s = gl_entry_new(c))) why = GL_R_TABLE_FULL;
  }
  if (why != GL_R_NONE) return gl_refuse_hello(c, ci, u, fd, why);
  s->kind = GL_E_SPARE;
  s->rank = d;
  s->inc = inc;
  s->nonce = n;
  s->pidfd = fd;
  s->pid = pid;
  s->conn = ci;
  gl_sp_set(s, GL_SP_REPLAYING);
  s->spSinceMs = gl_mono_ms();
  c->st.nSpareHello++;
  gl_log(c, "spare of rank %d incarnation %u said HELLO (pid %d): replaying", d, inc, (int)pid);
  gl_hello_ack(c, ci, u, GL_UA_OK, GL_R_NONE);
  gl_reg_note(c, n, d);
}

static struct glEntry* gl_spare_of_conn(struct glCore* c, int ci, const struct glUnixMsg* u) {
  struct glEntry* s = gl_find_spare(c, u->h.nonce, u->h.rank, u->h.incarnation);
  if (!s || s->conn != ci) {
    gl_log(c, "talk %u for the spare of rank %d incarnation %u from a connection that is not its own: dropped",
           u->h.kind, u->h.rank, u->h.incarnation);
    c->st.nBadMsg++;
    return NULL;
  }
  return s;
}

static void gl_on_unix(struct glCore* c, int ci, const struct glUnixMsg* u, int fd) {
  if (c->conn[ci].uid != c->cfg.uid) {  // nothing from another uid: refuse
    if (u->h.kind == GL_U_REGISTER || u->h.kind == GL_U_SPARE_HELLO) gl_hello_ack(c, ci, u, GL_UA_REFUSED, GL_R_UID);
    if (fd >= 0) close(fd);
    gl_log(c, "message %u from uid %u (not %u): refused", u->h.kind, (unsigned)c->conn[ci].uid, (unsigned)c->cfg.uid);
    c->st.nRegRefused++;
    return;
  }
  if (u->h.kind != GL_U_REGISTER && u->h.kind != GL_U_SPARE_HELLO && fd >= 0) {
    close(fd);  // an fd only travels with REGISTER and HELLO
    fd = -1;
  }
  switch (u->h.kind) {
    case GL_U_REGISTER: gl_register(c, ci, u, fd); return;
    case GL_U_SPARE_HELLO: gl_spare_hello(c, ci, u, fd); return;
    case GL_U_LEAVING: {
      struct glEntry* e = gl_find(c, GL_E_ORIG, u->h.nonce, u->h.rank);
      if (!e || e->inc != u->h.incarnation) {
        struct glEntry* s = gl_find_spare(c, u->h.nonce, u->h.rank, u->h.incarnation);
        e = (s && s->sp == GL_SP_ACCEPTED) ? s : NULL;
      }
      if (!e || e->conn != ci) {
        gl_log(c, "LEAVING of rank %d incarnation %u not from its registering connection: ignored", u->h.rank,
               u->h.incarnation);
        return;
      }
      e->leaving = 1;
      gl_log(c, "rank %d incarnation %u is leaving", u->h.rank, u->h.incarnation);
      return;
    }
    case GL_U_SPARE_STATUS: {
      struct glEntry* s = gl_spare_of_conn(c, ci, u);
      if (!s) return;
      if (u->h.sub == GL_US_READY) {
        if (s->sp != GL_SP_REPLAYING) return;
        gl_sp_set(s, GL_SP_READY);
        gl_log(c, "spare of rank %d incarnation %u is READY", s->rank, s->inc);
        gl_reg_note(c, s->nonce, s->rank);
        if (s->act == GL_ACT_WAIT) gl_offer(c, s);
      } else if (u->h.sub == GL_US_REPLAY_FAILED) {
        gl_log(c, "spare of rank %d incarnation %u reports a replay failure", s->rank, s->inc);
        if (s->sp == GL_SP_REPLAYING || s->sp == GL_SP_READY) gl_spare_fail(c, s, GL_R_REPLAY_FAILED, 1);
      }
      return;
    }
    case GL_U_ACT_TALK: {
      struct glEntry* s = gl_spare_of_conn(c, ci, u);
      if (!s) return;
      struct glPeer* p = gl_act_peer(c, s);
      if (u->h.sub == GL_UT_ANSWER) {
        struct glRsActivate rec;
        memcpy(&rec, u->body, sizeof(rec));
        if (s->sp == GL_SP_ABORTED) {
          if (rec.kind == GL_RS_ACT_ACCEPTED) {
            c->st.nLateAccept++;
            gl_log(c, "late_accept: ACCEPTED of rank %d incarnation %u after its ABORT: dropped", s->rank, s->inc);
          }
          return;
        }
        if (s->act != GL_ACT_GIVEN || s->sp != GL_SP_OFFERED) return;
        if (rec.kind == GL_RS_ACT_ACCEPTED) {
          gl_sp_set(s, GL_SP_ACCEPTED);
          gl_act_answer(c, p, s->actReqSeq, GL_RS_ACT_ACCEPTED, GL_R_NONE, &rec, s, "accepted by the spare");
          gl_reg_note(c, s->nonce, s->rank);
        } else if (rec.kind == GL_RS_ACT_LATER) {
          if (!s->laterSent) {
            s->laterSent = 1;
            gl_act_answer(c, p, s->actReqSeq, GL_RS_ACT_LATER, GL_R_SPARE_REPLAYING, &rec, s, "the spare answered LATER");
          } else {
            gl_log(c, "the spare of rank %d incarnation %u answered LATER after one LATER: not relayed", s->rank, s->inc);
          }
        } else {
          gl_act_answer(c, p, s->actReqSeq, GL_RS_ACT_REFUSED, GL_R_SPARE_REFUSED, &rec, s, NULL);
          s->act = GL_ACT_NONE;
          gl_spare_fail(c, s, GL_R_SPARE_REFUSED, 1);
        }
        return;
      }
      if (s->sp != GL_SP_ACCEPTED || !p) return;
      if (u->h.sub == GL_UT_FETCH_EP || u->h.sub == GL_UT_FETCH_DONE) {
        struct glMsg m;
        const int ep = u->h.sub == GL_UT_FETCH_EP;
        gl_msg_init(c, &m, ep ? GL_K_FETCH_EP : GL_K_FETCH_DONE, s->rank, s->inc, s->nonce);
        m.h.reqSeq = s->actReqSeq;
        const size_t len = ep ? GL_FETCH_EP_BYTES : GL_FETCH_DONE_BYTES;
        memcpy(m.body, u->body, len);
        m.h.bodyBytes = (uint16_t)len;
        gl_peer_send(c, p, &m);
      }
      return;
    }
    default:
      c->st.nBadMsg++;
      gl_log(c, "Unix message of kind %u is not one the launcher takes: dropped", u->h.kind);
      return;
  }
}

static void gl_conn_close(struct glCore* c, int ci) {
  close(c->conn[ci].fd);
  c->conn[ci].used = 0;
  for (int i = 0; i < GL_MAX_ENTRIES; i++)
    if (c->ent[i].used && c->ent[i].conn == ci) c->ent[i].conn = -1;  // the entry lives as long as its pidfd
}

/* Read every queued message of connection ci (non-blocking). */
static void gl_conn_drain(struct glCore* c, int ci) {
  while (c->conn[ci].used) {
    struct iovec iov;
    iov.iov_base = c->rbuf;
    iov.iov_len = sizeof(c->rbuf);
    union {
      char b[CMSG_SPACE(sizeof(int) * 4)];
      struct cmsghdr align;
    } cb;
    struct msghdr mh;
    memset(&mh, 0, sizeof(mh));
    mh.msg_iov = &iov;
    mh.msg_iovlen = 1;
    mh.msg_control = cb.b;
    mh.msg_controllen = sizeof(cb.b);
    const ssize_t n = recvmsg(c->conn[ci].fd, &mh, MSG_DONTWAIT | MSG_CMSG_CLOEXEC);
    if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)) return;
    int fd = -1, extra = 0;
    for (struct cmsghdr* cm = CMSG_FIRSTHDR(&mh); cm; cm = CMSG_NXTHDR(&mh, cm)) {
      if (cm->cmsg_level != SOL_SOCKET || cm->cmsg_type != SCM_RIGHTS) continue;
      const size_t k = (cm->cmsg_len - CMSG_LEN(0)) / sizeof(int);
      for (size_t j = 0; j < k; j++) {
        int f;
        memcpy(&f, CMSG_DATA(cm) + j * sizeof(int), sizeof(int));
        if (fd < 0) fd = f;
        else {
          close(f);
          extra = 1;
        }
      }
    }
    if (n <= 0) {  // EOF or error: the connection is gone (its entries stay with their pidfds)
      if (fd >= 0) close(fd);
      gl_conn_close(c, ci);
      return;
    }
    const struct glUnixMsg* u = (const struct glUnixMsg*)c->rbuf;
    uint32_t bad = gl_unix_check(u, (size_t)n);
    if (bad == GL_R_NONE && ((mh.msg_flags & (MSG_TRUNC | MSG_CTRUNC)) || extra)) bad = extra ? GL_R_BAD_FD : GL_R_BAD_MSG;
    if (bad != GL_R_NONE) {
      c->st.nBadMsg++;
      if (fd >= 0) close(fd);
      if ((size_t)n >= sizeof(struct glUnixHdr) && u->h.magic == GL_U_MAGIC &&
          (u->h.kind == GL_U_REGISTER || u->h.kind == GL_U_SPARE_HELLO)) {
        c->st.nRegRefused++;
        gl_hello_ack(c, ci, u, GL_UA_REFUSED, bad);
      }
      gl_log(c, "malformed Unix message (%s): dropped", gl_reason_text(bad));
      continue;
    }
    gl_on_unix(c, ci, u, fd);
  }
}

static void gl_accept(struct glCore* c) {
  for (;;) {
    const int fd = accept4(c->listenFd, NULL, NULL, SOCK_NONBLOCK | SOCK_CLOEXEC);
    if (fd < 0) return;
    struct ucred cr;
    socklen_t cl = sizeof(cr);
    if (getsockopt(fd, SOL_SOCKET, SO_PEERCRED, &cr, &cl) != 0) {
      close(fd);
      continue;
    }
    int ci = -1;
    for (int i = 0; i < GL_MAX_CONNS && ci < 0; i++)
      if (!c->conn[i].used) ci = i;
    if (ci < 0) {
      gl_log(c, "too many connections: one refused");
      close(fd);
      continue;
    }
    c->conn[ci].used = 1;
    c->conn[ci].fd = fd;
    c->conn[ci].pid = cr.pid;
    c->conn[ci].uid = cr.uid;
    c->conn[ci].start = gl_pid_start(cr.pid);
    if (cr.uid != c->cfg.uid)
      gl_log(c, "connection from uid %u (not %u): every message will be refused", (unsigned)cr.uid,
             (unsigned)c->cfg.uid);
  }
}

/* ------------------------------------------------------------------------------------------------- public */

struct glCore* gl_core_new(const struct glConfig* cfg, struct glTransport* tp) {
  struct glCore* c = (struct glCore*)calloc(1, sizeof(*c));
  if (!c) return NULL;
  c->cfg = *cfg;
  if (c->cfg.graceMs <= 0) c->cfg.graceMs = 1000;
  c->tp = tp;
  c->log = cfg->log ? cfg->log : stderr;
  c->listenFd = -1;
  for (int i = 0; i < GL_MAX_ENTRIES; i++) {
    c->ent[i].pidfd = -1;
    c->ent[i].conn = -1;
    c->ent[i].actPeer = -1;
    c->ent[i].readHandle = -1;
  }
  for (int i = 0; i < GL_MAX_PEERS; i++) c->peer[i].rec.handle = c->peer[i].probe.handle = c->peer[i].repairHandle = -1;
  if (posix_memalign((void**)&c->page, 4096, sizeof(struct glPage)) != 0) {
    free(c);
    return NULL;
  }
  memset(c->page, 0, sizeof(*c->page));
  c->page->magicVer = ((uint64_t)GL_PAGE_MAGIC << 32) | ((uint64_t)GL_WIRE_VERSION << 16) | GL_PAGE_LAYOUT;
  c->page->node = cfg->node;
  c->page->qkey = cfg->qkey;
  c->page->nCredits = GL_PAGE_CREDITS;
  c->page->monoMs = (uint64_t)gl_mono_ms();
  if (tp->ops->page_register(tp, c->page, sizeof(*c->page), &c->pageReg) != 0 || tp->ops->local_ud(tp, &c->ud) != 0) {
    free(c->page);
    free(c);
    return NULL;
  }
  return c;
}

int gl_core_listen(struct glCore* c, const char* path, char* why, size_t whyLen) {
  struct sockaddr_un a;
  memset(&a, 0, sizeof(a));
  a.sun_family = AF_UNIX;
  if (strlen(path) >= sizeof(a.sun_path)) {
    snprintf(why, whyLen, "socket path too long");
    return -1;
  }
  char dir[sizeof(a.sun_path)];
  snprintf(dir, sizeof(dir), "%s", path);
  char* slash = strrchr(dir, '/');
  if (!slash || slash == dir) {
    snprintf(why, whyLen, "the socket path needs a directory of its own");
    return -1;
  }
  *slash = '\0';
  if (mkdir(dir, 0700) != 0 && errno != EEXIST) {
    snprintf(why, whyLen, "mkdir %s: %s", dir, strerror(errno));
    return -1;
  }
  struct stat st;
  const uid_t me = geteuid();  // the directory and the socket are the launcher's own
  if (lstat(dir, &st) != 0 || !S_ISDIR(st.st_mode) || st.st_uid != me || (st.st_mode & 077) != 0) {
    snprintf(why, whyLen, "%s must be a directory of uid %u with mode 0700", dir, (unsigned)me);
    return -1;
  }
  snprintf(a.sun_path, sizeof(a.sun_path), "%s", path);
  if (lstat(path, &st) == 0) {
    if (!S_ISSOCK(st.st_mode) || st.st_uid != me) {
      snprintf(why, whyLen, "%s exists and is not this uid's socket", path);
      return -1;
    }
    const int t = socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0);
    if (t >= 0 && connect(t, (struct sockaddr*)&a, sizeof(a)) == 0) {
      close(t);
      snprintf(why, whyLen, "another launcher listens on %s", path);
      return -1;
    }
    if (t >= 0) close(t);
    unlink(path);
  }
  const int fd = socket(AF_UNIX, SOCK_SEQPACKET | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
  if (fd < 0 || bind(fd, (struct sockaddr*)&a, sizeof(a)) != 0 || chmod(path, 0600) != 0 || listen(fd, 64) != 0) {
    snprintf(why, whyLen, "socket %s: %s", path, strerror(errno));
    if (fd >= 0) close(fd);
    return -1;
  }
  if (c->listenFd >= 0) close(c->listenFd);
  c->listenFd = fd;
  snprintf(c->sockPath, sizeof(c->sockPath), "%s", path);
  gl_log(c, "listening on its Unix socket (Q_Key 0x%08x)", c->cfg.qkey);
  return 0;
}

int gl_core_step(struct glCore* c, int timeoutMs) {
  enum { NPF = 1 + GL_MAX_CONNS + GL_MAX_ENTRIES + GL_MAX_TP_FDS };
  struct pollfd pf[NPF];
  int kind[NPF], idx[NPF];
  uint64_t eid[NPF];
  int n = 0;
  if (c->listenFd >= 0) {
    pf[n].fd = c->listenFd;
    pf[n].events = POLLIN;
    kind[n] = 0;
    idx[n++] = 0;
  }
  for (int i = 0; i < GL_MAX_CONNS; i++)
    if (c->conn[i].used) {
      pf[n].fd = c->conn[i].fd;
      pf[n].events = POLLIN;
      kind[n] = 1;
      idx[n++] = i;
    }
  for (int i = 0; i < GL_MAX_ENTRIES; i++)
    if (c->ent[i].used && c->ent[i].pidfd >= 0) {
      pf[n].fd = c->ent[i].pidfd;
      pf[n].events = POLLIN;
      kind[n] = 2;
      eid[n] = c->ent[i].id;
      idx[n++] = i;
    }
  int tfd[GL_MAX_TP_FDS];
  const int nt = c->tp->ops->fds(c->tp, tfd, GL_MAX_TP_FDS);
  for (int i = 0; i < nt; i++) {
    pf[n].fd = tfd[i];
    pf[n].events = POLLIN;
    kind[n] = 3;
    idx[n++] = i;
  }
  double now = gl_mono_ms();
  int to = timeoutMs < GL_BEAT_MS ? timeoutMs : GL_BEAT_MS;
  for (int i = 0; i < GL_MAX_ENTRIES; i++)
    if (c->ent[i].used && c->ent[i].killAtMs > 0) {
      const double left = c->ent[i].killAtMs - now;
      if (left < to) to = left < 0 ? 0 : (int)left + 1;
    }
  if (to < 0) to = 0;
  for (int i = 0; i < n; i++) pf[i].revents = 0;
  const int r = poll(pf, (nfds_t)n, to);
  if (r < 0 && errno != EINTR) return -1;
  gl_pw(&c->page->beat, c->page->beat + 1);
  gl_pw(&c->page->monoMs, (uint64_t)gl_mono_ms());
  gl_transport_events(c);
  for (int i = 0; i < n; i++) {
    if (!pf[i].revents) continue;
    if (kind[i] == 0) gl_accept(c);
    else if (kind[i] == 1 && c->conn[idx[i]].used && c->conn[idx[i]].fd == pf[i].fd) gl_conn_drain(c, idx[i]);
  }
  for (int i = 0; i < n; i++) {
    if (!pf[i].revents || kind[i] != 2) continue;
    struct glEntry* e = &c->ent[idx[i]];
    if (e->used && e->id == eid[i] && e->pidfd == pf[i].fd) gl_exit_seen(c, e);
  }
  now = gl_mono_ms();
  for (int i = 0; i < GL_MAX_ENTRIES; i++) {
    struct glEntry* e = &c->ent[i];
    if (e->used && e->killAtMs > 0 && now >= e->killAtMs) {
      e->killAtMs = 0;
      if (!e->dead && e->pidfd >= 0 && !gl_readable(e->pidfd)) {
        gl_log(c, "spare of rank %d incarnation %u still there after %d ms (state %d): SIGKILL through its pidfd",
               e->rank, e->inc, c->cfg.graceMs, e->sp);
        gl_signal(c, e, SIGKILL);
      }
    }
  }
  for (int i = 0; i < GL_MAX_PEERS; i++) {  // the launcher's own re-pairings: resend, or give up at the bound
    struct glPeer* p = &c->peer[i];
    if (!p->used || !p->repair) continue;
    if (now >= p->repairEndMs) {
      gl_log(c, "re-pairing of rank %d gave up after %d ms (the rank may pair again)", p->rank, GL_REPAIR_MS);
      gl_repair_stop(c, p);
    } else if (now >= p->repairNextMs) {
      p->repairNextMs = now + GL_REPAIR_EVERY_MS;
      c->tp->ops->ud_send(c->tp, &p->ud, p->qkey, &p->repairPair);
    }
  }
  gl_transport_events(c);
  return c->fatal ? -1 : 0;
}

void gl_core_shutdown(struct glCore* c) {
  for (int i = 0; i < GL_MAX_ENTRIES; i++) {
    struct glEntry* e = &c->ent[i];
    if (e->used && e->kind == GL_E_SPARE && e->sp != GL_SP_ACCEPTED && !e->dead && e->pidfd >= 0 &&
        !gl_readable(e->pidfd)) {
      gl_log(c, "shutdown: the unused spare of rank %d incarnation %u is SIGKILLed through its pidfd", e->rank, e->inc);
      gl_signal(c, e, SIGKILL);
    }
  }
  for (int i = 0; i < GL_MAX_ENTRIES; i++)
    if (c->ent[i].used) gl_entry_free(c, &c->ent[i]);
  for (int i = 0; i < GL_MAX_CONNS; i++)
    if (c->conn[i].used) gl_conn_close(c, i);
  for (int i = 0; i < GL_MAX_PEERS; i++)
    if (c->peer[i].used) gl_peer_clear(c, &c->peer[i]);
  if (c->listenFd >= 0) {
    close(c->listenFd);
    c->listenFd = -1;
    unlink(c->sockPath);
  }
}

void gl_core_free(struct glCore* c) {
  if (!c) return;
  for (int i = 0; i < GL_MAX_ENTRIES; i++)
    if (c->ent[i].used) gl_entry_free(c, &c->ent[i]);
  for (int i = 0; i < GL_MAX_PEERS; i++)  // every QP closed before the READ buffers go (gl_core_shutdown did it already)
    if (c->peer[i].used) gl_peer_clear(c, &c->peer[i]);
  for (int i = 0; i < GL_MAX_ORPHANS; i++)
    if (c->orphan[i].used) free(c->orphan[i].buf);
  for (int i = 0; i < GL_MAX_CONNS; i++)
    if (c->conn[i].used) gl_conn_close(c, i);
  if (c->listenFd >= 0) close(c->listenFd);
  free(c->page);
  free(c);
}

int gl_core_entry(const struct glCore* c, uint64_t nonce, int32_t rank, int kind, uint32_t inc,
                  struct glEntryView* out) {
  for (int i = 0; i < GL_MAX_ENTRIES; i++) {
    const struct glEntry* e = &c->ent[i];
    if (!e->used || e->kind != kind || e->nonce != nonce || e->rank != rank) continue;
    if (inc != 0xffffffffu && e->inc != inc) continue;
    out->kind = e->kind;
    out->inc = e->inc;
    out->pidfd = e->pidfd;
    out->pid = e->pid;
    out->conn = e->conn >= 0 ? c->conn[e->conn].fd : -1;
    out->leaving = e->leaving;
    out->fenceAsked = e->fenceAsked;
    out->signalled = e->signalled;
    out->sp = e->sp;
    out->spReason = e->spReason;
    out->act = e->act;
    out->laterSent = e->laterSent;
    out->dead = e->dead;
    const double w = gl_mono_ms() - e->spSinceMs;
    out->spAgeMs = w > 0 ? (uint32_t)w : 0;
    return 1;
  }
  return 0;
}
int gl_core_tomb(const struct glCore* c, uint64_t nonce, int32_t rank, uint32_t inc, uint32_t* how) {
  const struct glTomb* t = gl_tomb_of(c, nonce, rank, inc);
  if (t && how) *how = t->how;
  return t != NULL;
}
int gl_core_peer(const struct glCore* c, uint64_t nonce, int32_t rank, struct glPeerView* out) {
  for (int i = 0; i < GL_MAX_PEERS; i++) {
    const struct glPeer* p = &c->peer[i];
    if (!p->used || p->nonce != nonce || p->rank != rank) continue;
    out->slot = i;
    out->inc = p->inc;
    out->recHandle = p->rec.handle;
    out->recGen = p->rec.gen;
    out->probeHandle = p->probe.handle;
    out->probeGen = p->probe.gen;
    out->connected = p->connected;
    out->repair = p->repair;
    out->repairHandle = p->repairHandle;
    out->repairGen = p->repairGen;
    out->consumed = p->consumed;
    out->queued = p->nq;
    return 1;
  }
  return 0;
}
const struct glStats* gl_core_stats(const struct glCore* c) { return &c->st; }
const struct glPage* gl_core_page(const struct glCore* c) { return c->page; }

/* ------------------------------------------------------------------------------------------------- main */
#ifndef GL_NO_MAIN

#ifndef GL_NO_VERBS
static volatile sig_atomic_t gl_stop = 0;
static void gl_on_term(int s) {
  (void)s;
  gl_stop = 1;
}
#endif

static void gl_usage(const char* a0) {
  fprintf(stderr,
          "usage: %s --node N --dev IBDEV [--port P] [--gid-index G] [--tc TC] [--sock PATH] [--qkey Q]\n"
          "  --tc: the traffic class of its UD datagrams and QPs, the GIN QPs' own (default $NCCL_IB_TC, else 0).\n"
          "  --sock defaults to $%s, else $XDG_RUNTIME_DIR/gin-launcher/launcher.sock, else\n"
          "  /tmp/gin-launcher-<uid>/launcher.sock (directory mode 0700). --node defaults to $%s.\n"
          "  Test switch (research build): NCCL_GIN_CTRL_TEST_NO_EXIT_REPORT=1 sends no EXITED (FENCED and LEFT stay).\n",
          a0, GL_SOCK_ENV, GL_NODE_ENV);
}

int main(int argc, char** argv) {
  const char* sock = getenv(GL_SOCK_ENV);
  const char* nodeEnv = getenv(GL_NODE_ENV);
  const char* dev = NULL;
  long node = nodeEnv ? strtol(nodeEnv, NULL, 0) : -1;
  int port = 1, gidIndex = 3;
  const char* tcEnv = getenv("NCCL_IB_TC");
  int tc = tcEnv ? atoi(tcEnv) : 0;  // design v3 2.5: the GIN QPs' GID index and traffic class
  uint32_t qkey = 0;
  for (int i = 1; i < argc; i++) {
    const char* a = argv[i];
    const char* v = i + 1 < argc ? argv[i + 1] : NULL;
    if (!strcmp(a, "--node") && v) node = strtol(argv[++i], NULL, 0);
    else if (!strcmp(a, "--dev") && v) dev = argv[++i];
    else if (!strcmp(a, "--port") && v) port = atoi(argv[++i]);
    else if (!strcmp(a, "--gid-index") && v) gidIndex = atoi(argv[++i]);
    else if (!strcmp(a, "--tc") && v) tc = atoi(argv[++i]);
    else if (!strcmp(a, "--sock") && v) sock = argv[++i];
    else if (!strcmp(a, "--qkey") && v) qkey = (uint32_t)strtoul(argv[++i], NULL, 0);
    else {
      gl_usage(argv[0]);
      return 2;
    }
  }
  if (node < 0 || node > 0xffff || !dev || tc < 0 || tc > 255) {
    gl_usage(argv[0]);
    return 2;
  }
  char path[sizeof(((struct sockaddr_un*)0)->sun_path)];
  if (sock && *sock) snprintf(path, sizeof(path), "%s", sock);
  else if (gl_default_sock_path(path, sizeof(path)) != 0) {
    fprintf(stderr, "GIN/LA: no socket path\n");
    return 2;
  }
  if (qkey == 0) {  // its own 31-bit value
    uint32_t r = 0;
    const int f = open("/dev/urandom", O_RDONLY | O_CLOEXEC);
    if (f >= 0) {
      if (read(f, &r, sizeof(r)) != (ssize_t)sizeof(r)) r = (uint32_t)gl_mono_ns();
      close(f);
    }
    qkey = (r & 0x7fffffffu) | 1u;
  }
  qkey &= 0x7fffffffu;
#ifdef GL_NO_VERBS
  (void)port;
  (void)gidIndex;
  (void)tc;
  fprintf(stderr, "GIN/LA: built without libibverbs headers (GL_NO_VERBS): this program cannot run\n");
  return 3;
#else
  struct glTransport* tp = gl_transport_verbs_open(dev, port, gidIndex, tc, qkey, (uint32_t)node);
  if (!tp) return 3;
  struct glConfig cfg;
  memset(&cfg, 0, sizeof(cfg));
  cfg.node = (uint32_t)node;
  cfg.qkey = qkey;
  cfg.uid = getuid();
  cfg.graceMs = 1000;
#ifndef GL_PRODUCTION
  const char* nr = getenv("NCCL_GIN_CTRL_TEST_NO_EXIT_REPORT");
  cfg.noExitReport = nr && atoi(nr) == 1;
#endif
  struct glCore* c = gl_core_new(&cfg, tp);
  if (!c) {
    fprintf(stderr, "GIN/LA: the state page could not be registered\n");
    tp->ops->close(tp);
    return 3;
  }
  char why[256];
  if (gl_core_listen(c, path, why, sizeof(why)) != 0) {
    fprintf(stderr, "GIN/LA: %s\n", why);
    gl_core_free(c);
    tp->ops->close(tp);
    return 3;
  }
  struct sigaction sa;
  memset(&sa, 0, sizeof(sa));
  sa.sa_handler = gl_on_term;
  sigaction(SIGTERM, &sa, NULL);
  sigaction(SIGINT, &sa, NULL);
  signal(SIGPIPE, SIG_IGN);
  if (cfg.noExitReport) fprintf(stderr, "GIN/LA: node %ld: test switch NO_EXIT_REPORT on\n", node);
  while (!gl_stop)
    if (gl_core_step(c, GL_BEAT_MS) != 0) break;
  gl_core_shutdown(c);
  gl_core_free(c);
  tp->ops->close(tp);
  return 0;
#endif
}
#endif /* GL_NO_MAIN */
