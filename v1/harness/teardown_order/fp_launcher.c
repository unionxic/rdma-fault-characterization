/* fp_launcher.c - runs on the responder node; forks and kills the victim.
 *
 * usage: fp_launcher -p ctrl_port -k marker_port [-t idle_s]
 *
 * One requester session at a time on TCP ctrl_port (any address). Commands:
 *   T                          -> "T <now_ns>"          (clock-offset ping)
 *   SPAWN <log> <argv...>      -> "PID <pid>"            fork+exec, stdout/stderr -> <log>
 *   KILL                       -> "KILLED <t_ns>"        kill(pid, SIGKILL), t taken just before
 *   REPORT <wait_ms>           -> "MK <label> <fd> <t_open> <t_close>" per marker,
 *                                 "RP <t_kill> <t_reap> <wstatus>", "END"
 *                                 (waits until the victim is reaped and every marker has
 *                                 closed, or wait_ms)
 *   BYE                        -> ends the session (a still-running victim is SIGKILLed and reaped)
 * Markers: the victim connects to 127.0.0.1:marker_port and sends
 * "M <label> <fd> <t>"; the time at which each marker connection reads EOF is the
 * moment the kernel released that fd (FIN on loopback is immediate).
 * t_reap = the pidfd became readable = the whole thread group finished exiting.
 * Exits after idle_s seconds without a session (default 300).
 */
#define _GNU_SOURCE
#include "fp_common.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <unistd.h>
#include <getopt.h>
#include <sys/wait.h>
#include <sys/socket.h>
#include <sys/syscall.h>

#ifndef SYS_pidfd_open
#define SYS_pidfd_open 434
#endif

#define MAXMK 32
typedef struct {
    int fd;
    char label[32];
    int resp_fd;
    uint64_t t_open, t_close;
    char buf[128];
    int blen;
} mk_t;

static mk_t mk[MAXMK];
static int nmk;
static pid_t child = -1;
static int pidfd = -1;
static uint64_t t_kill, t_reap;
static int wstatus = -1;

static void reap_now(void) {
    int st = 0;
    pid_t r = waitpid(child, &st, WNOHANG);
    if (r == child) {
        t_reap = fp_now_ns();
        wstatus = st;
        close(pidfd);
        pidfd = -1;
        child = -1;
    }
}

static void session_reset(void) {
    if (child > 0) {
        kill(child, SIGKILL);
        waitpid(child, NULL, 0);
        child = -1;
    }
    if (pidfd >= 0) { close(pidfd); pidfd = -1; }
    for (int i = 0; i < nmk; i++) if (mk[i].fd >= 0) close(mk[i].fd);
    nmk = 0;
    t_kill = t_reap = 0;
    wstatus = -1;
}

static int spawn(char *args, int cfd) {
    char *argv[64];
    int ac = 0;
    char *save = NULL, *tok = strtok_r(args, " ", &save);
    const char *log = tok;
    while ((tok = strtok_r(NULL, " ", &save)) && ac < 63) argv[ac++] = tok;
    argv[ac] = NULL;
    if (!log || ac == 0) return fp_send_line(cfd, "ERR bad_spawn");
    session_reset();
    pid_t p = fork();
    if (p < 0) return fp_send_line(cfd, "ERR fork");
    if (p == 0) {
        int lf = open(log, O_WRONLY | O_CREAT | O_TRUNC, 0644);
        int nf = open("/dev/null", O_RDONLY);
        if (nf >= 0) { dup2(nf, 0); close(nf); }
        if (lf >= 0) { dup2(lf, 1); dup2(lf, 2); close(lf); }
        signal(SIGPIPE, SIG_DFL);
        execv(argv[0], argv);
        _exit(127);
    }
    child = p;
    pidfd = (int)syscall(SYS_pidfd_open, p, 0);
    if (pidfd >= 0) fp_set_cloexec(pidfd);
    return fp_send_line(cfd, "PID %d", p);
}

static int report_ready(void) {
    if (child > 0) return 0;
    for (int i = 0; i < nmk; i++) if (mk[i].fd >= 0) return 0;
    return 1;
}

static int send_report(int cfd) {
    for (int i = 0; i < nmk; i++)
        if (fp_send_line(cfd, "MK %s %d %lu %lu", mk[i].label, mk[i].resp_fd,
                         (unsigned long)mk[i].t_open, (unsigned long)mk[i].t_close) < 0) return -1;
    if (fp_send_line(cfd, "RP %lu %lu %d", (unsigned long)t_kill, (unsigned long)t_reap, wstatus) < 0) return -1;
    return fp_send_line(cfd, "END");
}

int main(int argc, char **argv) {
    int cport = 18931, kport = 18933, idle_s = 300, opt;
    while ((opt = getopt(argc, argv, "p:k:t:")) != -1) {
        switch (opt) {
            case 'p': cport = atoi(optarg); break;
            case 'k': kport = atoi(optarg); break;
            case 't': idle_s = atoi(optarg); break;
            default: fprintf(stderr, "usage: %s -p ctrl_port -k marker_port [-t idle_s]\n", argv[0]); return 2;
        }
    }
    signal(SIGPIPE, SIG_IGN);
    int lc = fp_listen(NULL, cport), lk = fp_listen("127.0.0.1", kport);
    if (lc < 0 || lk < 0) return 1;
    fp_set_cloexec(lc);
    fp_set_cloexec(lk);
    fprintf(stderr, "[launcher] pid %d ctrl %d markers %d\n", getpid(), cport, kport);

    int cfd = -1;
    uint64_t last_active = fp_now_ns(), report_deadline = 0;
    int report_pending = 0;
    char cbuf[4096];
    int clen = 0;

    for (;;) {
        struct pollfd pf[4 + MAXMK];
        int n = 0, i_lc = -1, i_lk, i_c = -1, i_pid = -1, i_mk0;
        if (cfd < 0) { pf[n].fd = lc; pf[n].events = POLLIN; i_lc = n++; }
        pf[n].fd = lk; pf[n].events = POLLIN; i_lk = n++;
        if (cfd >= 0) { pf[n].fd = cfd; pf[n].events = POLLIN; i_c = n++; }
        if (pidfd >= 0) { pf[n].fd = pidfd; pf[n].events = POLLIN; i_pid = n++; }
        i_mk0 = n;
        for (int i = 0; i < nmk; i++) { pf[n].fd = mk[i].fd; pf[n].events = POLLIN; n++; }

        int r = poll(pf, (nfds_t)n, 50);
        uint64_t now = fp_now_ns();
        if (r < 0 && errno != EINTR) { perror("poll"); break; }

        if (cfd < 0 && (now - last_active) / 1000000000ull > (uint64_t)idle_s) {
            fprintf(stderr, "[launcher] idle %d s, exiting\n", idle_s);
            break;
        }
        if (r <= 0) goto check_report;

        /* markers first: their close time is the measurement */
        for (int i = 0; i < nmk; i++) {
            struct pollfd *p = &pf[i_mk0 + i];
            if (mk[i].fd < 0 || !(p->revents & (POLLIN | POLLHUP | POLLERR))) continue;
            char tmp[128];
            ssize_t k = recv(mk[i].fd, tmp, sizeof(tmp), 0);
            if (k <= 0) {
                mk[i].t_close = now;
                close(mk[i].fd);
                mk[i].fd = -1;
            } else {
                for (ssize_t j = 0; j < k && mk[i].blen < (int)sizeof(mk[i].buf) - 1; j++)
                    mk[i].buf[mk[i].blen++] = tmp[j];
                mk[i].buf[mk[i].blen] = 0;
                if (strchr(mk[i].buf, '\n') && !mk[i].label[0]) {
                    unsigned long t = 0;
                    sscanf(mk[i].buf, "M %31s %d %lu", mk[i].label, &mk[i].resp_fd, &t);
                }
            }
        }
        if (i_pid >= 0 && (pf[i_pid].revents & POLLIN)) reap_now();
        if (pf[i_lk].revents & POLLIN) {
            int fd = fp_accept(lk);
            if (fd >= 0 && nmk < MAXMK) {
                fp_set_cloexec(fd);
                memset(&mk[nmk], 0, sizeof(mk[nmk]));
                mk[nmk].fd = fd;
                mk[nmk].t_open = now;
                mk[nmk].resp_fd = -1;
                nmk++;
            } else if (fd >= 0) close(fd);
        }
        if (i_lc >= 0 && (pf[i_lc].revents & POLLIN)) {
            cfd = fp_accept(lc);
            if (cfd >= 0) fp_set_cloexec(cfd);
            clen = 0;
            last_active = now;
        }
        if (i_c >= 0 && (pf[i_c].revents & (POLLIN | POLLHUP | POLLERR))) {
            ssize_t k = recv(cfd, cbuf + clen, sizeof(cbuf) - 1 - (size_t)clen, 0);
            if (k <= 0) {
                session_reset();
                close(cfd);
                cfd = -1;
                report_pending = 0;
                last_active = now;
                goto check_report;
            }
            clen += (int)k;
            cbuf[clen] = 0;
            char *nl;
            while ((nl = strchr(cbuf, '\n'))) {
                *nl = 0;
                char *line = cbuf;
                if (!strcmp(line, "T")) {
                    fp_send_line(cfd, "T %lu", (unsigned long)fp_now_ns());
                } else if (!strncmp(line, "SPAWN ", 6)) {
                    spawn(line + 6, cfd);
                } else if (!strcmp(line, "KILL")) {
                    if (child > 0) {
                        t_kill = fp_now_ns();
                        kill(child, SIGKILL);
                        fp_send_line(cfd, "KILLED %lu", (unsigned long)t_kill);
                    } else {
                        fp_send_line(cfd, "ERR no_child");
                    }
                } else if (!strncmp(line, "REPORT", 6)) {
                    long w = 5000;
                    sscanf(line, "REPORT %ld", &w);
                    report_pending = 1;
                    report_deadline = fp_now_ns() + (uint64_t)w * 1000000ull;
                } else if (!strcmp(line, "BYE")) {
                    session_reset();
                    fp_send_line(cfd, "BYE");
                    close(cfd);
                    cfd = -1;
                    report_pending = 0;
                    last_active = fp_now_ns();
                    clen = 0;
                    break;
                }
                size_t rest = (size_t)clen - (size_t)(nl + 1 - cbuf);
                memmove(cbuf, nl + 1, rest);
                clen = (int)rest;
                cbuf[clen] = 0;
            }
            last_active = now;
        }
check_report:
        if (child > 0 && pidfd < 0) reap_now();     /* no pidfd: fall back to polling */
        if (report_pending && cfd >= 0 && (report_ready() || fp_now_ns() > report_deadline)) {
            send_report(cfd);
            report_pending = 0;
        }
    }
    session_reset();
    return 0;
}
