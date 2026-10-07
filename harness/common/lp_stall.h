/*
 * lp_stall.h - stop this process for a set time through a helper child (live_peer study,
 * harness/live_peer/EXPERIMENT.md section 9.0). Header only; usable from C and C++.
 *
 * lp_stall_start() forks a helper named "lp_stall" (prctl PR_SET_NAME, so `pkill -x <parent name>`
 * and `pgrep -x <parent name>` do not see it). Call it before the process opens files, devices,
 * threads or CUDA. The helper only reads, writes, sleeps, sends signals and exits:
 *   - on a command (4-byte milliseconds) it sends SIGSTOP to the parent, sleeps, sends SIGCONT,
 *     then replies with the two CLOCK_MONOTONIC times (ns) of the stop and the continue;
 *   - on EOF, on a read error, or when its parent changes, it exits (_exit); PR_SET_PDEATHSIG
 *     also ends it if the parent dies.
 * lp_stall_self() sends the command and blocks until the reply arrives, so the stop always happens
 * inside that call and the call returns after the continue. The channel is a socketpair used with
 * MSG_NOSIGNAL, so a dead helper gives an error, never SIGPIPE.
 * Signals go only to the parent process that forked the helper.
 */
#ifndef LP_STALL_H
#define LP_STALL_H

#include <stdint.h>
#include <errno.h>
#include <signal.h>
#include <time.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/socket.h>
#include <sys/prctl.h>

typedef struct {
    int fd;       /* parent end of the socketpair, -1 if not started */
    pid_t pid;    /* helper pid */
} lp_stall_t;

static inline uint64_t lp_stall_mono_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

static inline int lp_stall_xfer(int fd, void *buf, size_t len, int is_send) {
    char *p = (char *)buf;
    size_t off = 0;
    while (off < len) {
        ssize_t n = is_send ? send(fd, p + off, len - off, MSG_NOSIGNAL) : recv(fd, p + off, len - off, 0);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        off += (size_t)n;
    }
    return 0;
}

/* returns 0 in the parent with s filled, -1 on error; never returns in the helper */
static inline int lp_stall_start(lp_stall_t *s) {
    int sv[2];
    s->fd = -1;
    s->pid = -1;
    if (socketpair(AF_UNIX, SOCK_STREAM, 0, sv) != 0) return -1;
    const pid_t parent = getpid();
    const pid_t pid = fork();
    if (pid < 0) { close(sv[0]); close(sv[1]); return -1; }
    if (pid == 0) {
        close(sv[0]);
        prctl(PR_SET_NAME, "lp_stall", 0, 0, 0);
        prctl(PR_SET_PDEATHSIG, SIGKILL, 0, 0, 0);
        if (getppid() != parent) _exit(0);
        for (;;) {
            uint32_t ms = 0;
            if (lp_stall_xfer(sv[1], &ms, sizeof(ms), 0) != 0) _exit(0);
            if (getppid() != parent) _exit(0);
            uint64_t rep[2];
            rep[0] = lp_stall_mono_ns();
            if (kill(parent, SIGSTOP) != 0) _exit(1);
            struct timespec d;
            d.tv_sec = (time_t)(ms / 1000u);
            d.tv_nsec = (long)(ms % 1000u) * 1000000L;
            while (nanosleep(&d, &d) != 0 && errno == EINTR) {}
            rep[1] = lp_stall_mono_ns();
            kill(parent, SIGCONT);
            if (lp_stall_xfer(sv[1], rep, sizeof(rep), 1) != 0) _exit(0);
        }
    }
    close(sv[1]);
    s->fd = sv[0];
    s->pid = pid;
    return 0;
}

/* stop this process for ms milliseconds; *t_stop / *t_cont = CLOCK_MONOTONIC ns of SIGSTOP and
 * SIGCONT as the helper saw them. Returns 0, or -1 if the helper is gone. */
static inline int lp_stall_self(lp_stall_t *s, uint32_t ms, uint64_t *t_stop, uint64_t *t_cont) {
    if (!s || s->fd < 0) return -1;
    uint64_t rep[2] = {0, 0};
    if (lp_stall_xfer(s->fd, &ms, sizeof(ms), 1) != 0) return -1;
    if (lp_stall_xfer(s->fd, rep, sizeof(rep), 0) != 0) return -1;
    if (t_stop) *t_stop = rep[0];
    if (t_cont) *t_cont = rep[1];
    return 0;
}

#endif /* LP_STALL_H */
