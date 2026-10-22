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
  /* Observer of every signal the launcher sends (after the call): the target's pid (from the pidfd at registration, or
   * the spawned process's own), the signal, the syscall's result. For the unit test; NULL in the program. */
  void (*onSignal)(void* arg, pid_t pid, int sig, int rc);
  void* onSignalArg;
  /* The warm spare (user decision 2026-10-17): the launcher spawns one spare when it starts listening and the next one
   * as soon as the current one is activated. NULL spareArgv: none (a spare started by someone else still says HELLO and
   * is relayed as before). The pointers stay the caller's and must outlive the core. */
  char* const* spareArgv;  /* the spare's command, NULL-terminated, run with execvpe (no shell) */
  char* const* spareEnv;   /* "KEY=VAL" entries added to its environment, NULL-terminated (may be NULL) */
  const char* spareLogDir; /* one log file per spawn there (its stdout and stderr) */
  int spareHelloMs;        /* the bound from spawn to its HELLO (<= 0: 5000) */
  int spareRespawnMax;     /* respawns of spares that ended unused, within GL_SPARE_RESPAWN_WINDOW_MS (0: none) */
  uint32_t spareFirstInc;  /* the first spare's incarnation (0: 1) */
};

#define GL_SPARE_RESPAWN_WINDOW_MS 60000
#define GL_SPARE_MAX_ARGS 64
#define GL_SPARE_MAX_ENV 64
/* The program's spare options (--spare-cmd, --spare-env, --spare-log, --spare, --spare-hello-ms, --spare-respawn-max),
 * parsed apart from main so the unit test can run them. */
struct glSpareOpts {
  int want;                /* --spare: -1 not given, 0, 1 */
  char* cmdBuf;            /* the --spare-cmd copy, split in place at spaces and tabs */
  char* argv[GL_SPARE_MAX_ARGS + 1];
  int argc;
  char* env[GL_SPARE_MAX_ENV + 1];
  int nenv;
  const char* logDir;
  int helloMs, respawnMax;
  uint32_t firstInc;       /* NCCL_GIN_RESTORE_SPARE_INC of --spare-env, else 1 */
};
void gl_spare_opts_init(struct glSpareOpts* o);
/* 1: opt was a spare option and took val; 0: not a spare option; -1: refused (why). */
int gl_spare_opt(struct glSpareOpts* o, const char* opt, const char* val, char* why, size_t whyLen);
/* Checks the whole set and fills cfg's spare fields (pointers into o). 0 ok, -1 refused (why). */
int gl_spare_opts_apply(struct glSpareOpts* o, struct glConfig* cfg, char* why, size_t whyLen);
void gl_spare_opts_free(struct glSpareOpts* o);

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
  unsigned nPidfdClosed;   /* pidfds the launcher closed (exit seen, swap, refusal, an fd sent with INFO) */
  unsigned nInfo;          /* INFO taken and answered GL_UA_OK (no entry, no page slot, no registration count; the
                              answer may find the asker gone: a log line only) */
  unsigned nInfoRefused;   /* INFO answered GL_UA_REFUSED (uid, an fd with it, a body or nonce, malformed) */
  /* the warm spare */
  unsigned nSpareSpawned;  /* fork + exec attempts that made a child */
  unsigned nSpareExecFailed;
  unsigned nSpawnedHello;  /* HELLOs matched to a spawned spare */
  unsigned nSpareHelloTimeout;
  unsigned nSpareRespawned;/* respawns after an unused spare ended (capped) */
  unsigned nSpareActivated;/* activations that spawned the next spare */
  unsigned nSpareReaped;   /* spawned children reaped (waitpid) */
  unsigned spareGaveUp;    /* 1: no more spares (spawn failure, HELLO retry timed out, respawn cap) */
};

struct glCore;

struct glCore* gl_core_new(const struct glConfig* cfg, struct glTransport* tp);
void gl_core_free(struct glCore* c);
/* Create the socket's directory (mode 0700, the uid's own; an existing one must be so), bind, listen. 0 ok. */
int gl_core_listen(struct glCore* c, const char* path, char* why, size_t whyLen);
/* One loop pass: poll up to timeoutMs (bounded by the beat and the grace deadlines), then handle what is ready. */
int gl_core_step(struct glCore* c, int timeoutMs);
/* SIGKILL every spare that never became a rank (through its pidfd; a spawn without HELLO through its spawn pidfd), reap
 * the spawned ones (up to 1 s; an activated one is a rank and is left running), close every fd, unlink the socket. */
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
/* Spawned children (the warm spare and the spares it activated, until reaped). */
enum { GL_KID_WAIT = 1, GL_KID_WARM = 2, GL_KID_USED = 3, GL_KID_KILLED = 4 };
struct glKidView {
  pid_t pid;               /* the spawned process */
  pid_t helloPid;          /* the process that said HELLO (pid, or one in its session), 0 before */
  uint32_t inc;
  int state;               /* GL_KID_* */
  unsigned seq;            /* spawn number, from 1 */
  int retry, accepted, held; /* held: its pidfd is open */
};
int gl_core_kids(const struct glCore* c, struct glKidView* out, int max); /* returns how many are in use */
const struct glStats* gl_core_stats(const struct glCore* c);
const struct glPage* gl_core_page(const struct glCore* c);

#ifdef __cplusplus
}
#endif

#endif /* GIN_LAUNCHER_H */
