/* gin_launcher.h - the launcher's state machine API (gin-control, EXPERIMENT.md 9.5).
 *
 * gin_launcher.c holds the whole program: this state machine (one thread, one poll loop: the Unix listening socket,
 * its connections, every held pidfd, the transport's fds) and main(). Built with -DGL_NO_MAIN it is the library the
 * unit test (launcher_unit.cc) drives through the in-process test transport and real pidfds of forked children.
 */
#ifndef GIN_LAUNCHER_H
#define GIN_LAUNCHER_H

#include <stdint.h>
#include <stdio.h>
#include <sys/types.h>

#include "launcher_msg.h"
#include "launcher_transport.h"

#ifdef __cplusplus
extern "C" {
#endif

struct glConfig {
  uint32_t node;           /* this launcher's node number */
  uint32_t qkey;           /* its UD QP's Q_Key (31 bits) */
  uid_t uid;               /* the only uid accepted on the Unix socket (SO_PEERCRED); the launcher's own. A passed
                              pidfd must always be the connecting process's, with the start time seen at connect
                              (no switch: REVIEW2 fix 11) */
  int noExitReport;        /* test switch NCCL_GIN_CTRL_TEST_NO_EXIT_REPORT=1: no EXITED; LEFT and FENCED stay */
  int graceMs;             /* an aborted or failed spare is SIGKILLed through its pidfd after this (1000) */
  FILE* log;               /* GIN/LA: lines (stderr if NULL) */
  /* Observer of every signal the launcher sends (after the call): the target's pid (from the pidfd at registration),
   * the signal, the syscall's result. For the unit test; NULL in the program. */
  void (*onSignal)(void* arg, pid_t pid, int sig, int rc);
  void* onSignalArg;
};

struct glStats {
  unsigned nSignals;       /* pidfd_send_signal calls (all on held pidfds) */
  unsigned nFenceNak;      /* FENCEs answered FENCE_NAK (nothing held; "refused to signal" lines) */
  unsigned nLater;         /* LATER answers sent */
  unsigned nActRefused;    /* REFUSED activation answers sent */
  unsigned nActAccepted;   /* ACCEPTED answers relayed */
  unsigned nLateAccept;    /* ACCEPTED of an aborted activation, dropped */
  unsigned nExited, nLeft, nFenced;
  unsigned nRegistered, nRegRefused, nPromoted, nSpareHello;
  unsigned nSpawnRefused;
  unsigned nPairAck;
  unsigned nRepairStarted, nRepaired; /* record-QP re-pairings the launcher started, and finished */
  unsigned nBadMsg;
  unsigned nPidfdClosed;   /* pidfds the launcher closed (exit seen, swap, refusal) */
};

struct glCore;

struct glCore* gl_core_new(const struct glConfig* cfg, struct glTransport* tp);
void gl_core_free(struct glCore* c);
/* Create the socket's directory (mode 0700, the uid's own; an existing one must be so), bind, listen. 0 ok. */
int gl_core_listen(struct glCore* c, const char* path, char* why, size_t whyLen);
/* One loop pass: poll up to timeoutMs (bounded by the beat and the grace deadlines), then handle what is ready. */
int gl_core_step(struct glCore* c, int timeoutMs);
/* SIGKILL every spare that never became a rank (through its pidfd), close every fd, unlink the socket. */
void gl_core_shutdown(struct glCore* c);

/* The default socket path for uid: $XDG_RUNTIME_DIR/gin-launcher/launcher.sock, else /tmp/gin-launcher-<uid>/launcher.sock. */
int gl_default_sock_path(char* out, size_t len);
/* The pid a pidfd refers to (from /proc/self/fdinfo; -1 after the process was reaped), or -2 when fd is no pidfd. */
int gl_pidfd_pid(int fd);
/* /proc/<pid>/stat's start time (field 22), 0 when unreadable. */
uint64_t gl_pid_start(pid_t pid);

/* Introspection for the unit test. kind: 1 original (registered rank), 2 pre-launched spare. */
struct glEntryView {
  int kind;
  uint32_t inc;
  int pidfd;
  pid_t pid;
  int conn;                /* registering connection's fd, -1 when closed */
  int leaving;
  int fenceAsked, signalled;
  int sp;                  /* GL_SP_* (spares) */
  uint32_t spReason;
  int act;                 /* 0 none, 1 waiting for READY, 2 reading the blob, 3 handed over */
  int laterSent;
  int dead;                /* a spare whose pidfd became readable (kept for its answer) */
  uint32_t spAgeMs;        /* ms in the current spare state (the wait the rank side bounds) */
};
int gl_core_entry(const struct glCore* c, uint64_t nonce, int32_t rank, int kind, uint32_t inc,
                  struct glEntryView* out); /* inc 0xffffffff: any */
/* 1 and *how (GL_K_EXITED, GL_K_LEFT, GL_K_FENCED) when (nonce, rank, inc) ended here. */
int gl_core_tomb(const struct glCore* c, uint64_t nonce, int32_t rank, uint32_t inc, uint32_t* how);
struct glPeerView {
  int slot;                /* its credit slot on the page */
  uint32_t inc;
  int recHandle, probeHandle;
  uint32_t recGen, probeGen;
  int connected;
  int repair, repairHandle;
  uint32_t repairGen;
  uint64_t consumed;
  int queued;
};
int gl_core_peer(const struct glCore* c, uint64_t nonce, int32_t rank, struct glPeerView* out);
const struct glStats* gl_core_stats(const struct glCore* c);
const struct glPage* gl_core_page(const struct glCore* c);

#ifdef __cplusplus
}
#endif

#endif /* GIN_LAUNCHER_H */
