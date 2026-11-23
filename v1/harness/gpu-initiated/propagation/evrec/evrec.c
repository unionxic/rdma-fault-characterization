/*
 * evrec.c - record the async events of one RDMA device and its port counters.
 *
 * Opens one RDMA device, logs every async event delivered to this context as one
 * line with CLOCK_MONOTONIC and CLOCK_REALTIME nanoseconds, and writes every file of
 * the port's hw_counters/ and counters/ sysfs directories at start and at end.
 * The end is SIGTERM, SIGINT or SIGHUP, or the -T bound. evrec creates no PD, CQ,
 * QP or MR and writes nothing to the device or to sysfs: it only reads.
 *
 * What it can see: port and device events (PORT_ACTIVE, PORT_ERR, GID_CHANGE,
 * LID_CHANGE, DEVICE_FATAL, ...). QP-, CQ-, SRQ- and WQ-affiliated events go to the
 * context that owns the object, so the events of other processes' QPs never arrive
 * here.
 *
 * usage: evrec -d dev [-p port] [-o out] [-T max_seconds] [-s sample_ms -c name,name,...]
 *
 * -s/-c (live_peer study, 2026-10-07): every sample_ms milliseconds, read only the named files of
 * hw_counters/ (at most 16) and write one "smp" line. Without -s nothing changes in the output.
 *
 * Output: one record per line, "<kind> key=value ...":
 *   start  dev= port= pid= max_s= mono_ns= real_ns=
 *   port   phase=start|end state= phys_state=
 *   snap   phase=start|end dir=hw_counters|counters mono_ns= real_ns= files=
 *   ctr    phase=start|end dir= name= value=   (value=? err=<errno> if unreadable)
 *   event  seq= mono_ns= real_ns= type=IBV_EVENT_* code= elem=port|device|qp|cq|srq|wq|unknown
 *          [port=N | qpn=0x.. | wqn=0x..]
 *   end    reason=sigterm|sigint|sighup|timeout|error events= mono_ns= real_ns=
 *   smp    mono_ns= <name>=<value> ...   (only with -s; value ? if unreadable)
 *
 * Exit status: 0 normal end (signal or -T), 1 device/IO error, 2 bad arguments.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <time.h>
#include <dirent.h>
#include <getopt.h>
#include <inttypes.h>
#include <sys/stat.h>
#include <infiniband/verbs.h>

static volatile sig_atomic_t g_stop_sig = 0;   /* the signal that ends the recording */

static void on_signal(int sig) { g_stop_sig = sig; }

static uint64_t clock_ns(clockid_t c) {
    struct timespec ts;
    clock_gettime(c, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

static const char *event_name(enum ibv_event_type t) {
    switch (t) {
        case IBV_EVENT_CQ_ERR:              return "IBV_EVENT_CQ_ERR";
        case IBV_EVENT_QP_FATAL:            return "IBV_EVENT_QP_FATAL";
        case IBV_EVENT_QP_REQ_ERR:          return "IBV_EVENT_QP_REQ_ERR";
        case IBV_EVENT_QP_ACCESS_ERR:       return "IBV_EVENT_QP_ACCESS_ERR";
        case IBV_EVENT_COMM_EST:            return "IBV_EVENT_COMM_EST";
        case IBV_EVENT_SQ_DRAINED:          return "IBV_EVENT_SQ_DRAINED";
        case IBV_EVENT_PATH_MIG:            return "IBV_EVENT_PATH_MIG";
        case IBV_EVENT_PATH_MIG_ERR:        return "IBV_EVENT_PATH_MIG_ERR";
        case IBV_EVENT_DEVICE_FATAL:        return "IBV_EVENT_DEVICE_FATAL";
        case IBV_EVENT_PORT_ACTIVE:         return "IBV_EVENT_PORT_ACTIVE";
        case IBV_EVENT_PORT_ERR:            return "IBV_EVENT_PORT_ERR";
        case IBV_EVENT_LID_CHANGE:          return "IBV_EVENT_LID_CHANGE";
        case IBV_EVENT_PKEY_CHANGE:         return "IBV_EVENT_PKEY_CHANGE";
        case IBV_EVENT_SM_CHANGE:           return "IBV_EVENT_SM_CHANGE";
        case IBV_EVENT_SRQ_ERR:             return "IBV_EVENT_SRQ_ERR";
        case IBV_EVENT_SRQ_LIMIT_REACHED:   return "IBV_EVENT_SRQ_LIMIT_REACHED";
        case IBV_EVENT_QP_LAST_WQE_REACHED: return "IBV_EVENT_QP_LAST_WQE_REACHED";
        case IBV_EVENT_CLIENT_REREGISTER:   return "IBV_EVENT_CLIENT_REREGISTER";
        case IBV_EVENT_GID_CHANGE:          return "IBV_EVENT_GID_CHANGE";
        case IBV_EVENT_WQ_FATAL:            return "IBV_EVENT_WQ_FATAL";
        default:                            return "IBV_EVENT_UNKNOWN";
    }
}

/* one line per event; the element is printed while the event is still un-acked */
static void log_event(FILE *out, uint64_t seq, const struct ibv_async_event *ev,
                      uint64_t mono, uint64_t real) {
    char elem[48];
    switch (ev->event_type) {
        case IBV_EVENT_QP_FATAL: case IBV_EVENT_QP_REQ_ERR: case IBV_EVENT_QP_ACCESS_ERR:
        case IBV_EVENT_COMM_EST: case IBV_EVENT_SQ_DRAINED: case IBV_EVENT_PATH_MIG:
        case IBV_EVENT_PATH_MIG_ERR: case IBV_EVENT_QP_LAST_WQE_REACHED:
            snprintf(elem, sizeof(elem), "elem=qp qpn=0x%x", ev->element.qp ? ev->element.qp->qp_num : 0u);
            break;
        case IBV_EVENT_CQ_ERR:
            snprintf(elem, sizeof(elem), "elem=cq");
            break;
        case IBV_EVENT_SRQ_ERR: case IBV_EVENT_SRQ_LIMIT_REACHED:
            snprintf(elem, sizeof(elem), "elem=srq");
            break;
        case IBV_EVENT_WQ_FATAL:
            snprintf(elem, sizeof(elem), "elem=wq wqn=0x%x", ev->element.wq ? ev->element.wq->wq_num : 0u);
            break;
        case IBV_EVENT_PORT_ACTIVE: case IBV_EVENT_PORT_ERR: case IBV_EVENT_LID_CHANGE:
        case IBV_EVENT_PKEY_CHANGE: case IBV_EVENT_SM_CHANGE: case IBV_EVENT_CLIENT_REREGISTER:
        case IBV_EVENT_GID_CHANGE:
            snprintf(elem, sizeof(elem), "elem=port port=%d", ev->element.port_num);
            break;
        case IBV_EVENT_DEVICE_FATAL:
            snprintf(elem, sizeof(elem), "elem=device");
            break;
        default:
            snprintf(elem, sizeof(elem), "elem=unknown");
            break;
    }
    fprintf(out, "event seq=%" PRIu64 " mono_ns=%" PRIu64 " real_ns=%" PRIu64 " type=%s code=%d %s\n",
            seq, mono, real, event_name(ev->event_type), (int)ev->event_type, elem);
}

static void log_port(FILE *out, struct ibv_context *ctx, int port, const char *phase) {
    struct ibv_port_attr pa;
    if (ibv_query_port(ctx, (uint8_t)port, &pa)) {
        fprintf(out, "port phase=%s state=? err=%s\n", phase, strerror(errno));
        return;
    }
    fprintf(out, "port phase=%s state=%s phys_state=%d\n", phase,
            ibv_port_state_str(pa.state), (int)pa.phys_state);
}

/* write every regular file of <base>/<dir>, sorted by name, as ctr lines */
static void snapshot_dir(FILE *out, const char *base, const char *dir, const char *phase) {
    char path[512];
    snprintf(path, sizeof(path), "%s/%s", base, dir);
    struct dirent **names = NULL;
    int n = scandir(path, &names, NULL, alphasort);
    uint64_t mono = clock_ns(CLOCK_MONOTONIC), real = clock_ns(CLOCK_REALTIME);
    if (n < 0) {
        fprintf(out, "snap phase=%s dir=%s mono_ns=%" PRIu64 " real_ns=%" PRIu64 " files=0 err=%s\n",
                phase, dir, mono, real, strerror(errno));
        return;
    }
    int files = 0;
    for (int i = 0; i < n; i++) if (names[i]->d_name[0] != '.') files++;
    fprintf(out, "snap phase=%s dir=%s mono_ns=%" PRIu64 " real_ns=%" PRIu64 " files=%d\n",
            phase, dir, mono, real, files);
    for (int i = 0; i < n; i++) {
        const char *name = names[i]->d_name;
        if (name[0] == '.') { free(names[i]); continue; }
        char fpath[768];
        snprintf(fpath, sizeof(fpath), "%s/%s", path, name);
        struct stat sb;
        if (stat(fpath, &sb) != 0 || !S_ISREG(sb.st_mode)) { free(names[i]); continue; }
        char val[128] = "";
        int fd = open(fpath, O_RDONLY);
        ssize_t r = (fd >= 0) ? read(fd, val, sizeof(val) - 1) : -1;
        int e = errno;
        if (fd >= 0) close(fd);
        if (r < 0) {
            fprintf(out, "ctr phase=%s dir=%s name=%s value=? err=%s\n", phase, dir, name, strerror(e));
        } else {
            val[r] = '\0';
            /* keep one token: cut at the first newline, map blanks to '_' */
            for (char *p = val; *p; p++) {
                if (*p == '\n') { *p = '\0'; break; }
                if (*p == ' ' || *p == '\t') *p = '_';
            }
            fprintf(out, "ctr phase=%s dir=%s name=%s value=%s\n", phase, dir, name, val);
        }
        free(names[i]);
    }
    free(names);
}

static void snapshot(FILE *out, const char *dev, int port, const char *phase) {
    char base[256];
    snprintf(base, sizeof(base), "/sys/class/infiniband/%s/ports/%d", dev, port);
    snapshot_dir(out, base, "hw_counters", phase);
    snapshot_dir(out, base, "counters", phase);
}

/* one sample of the named hw_counters files: "smp mono_ns=<n> name=value ..." */
#define SMP_MAX 16
static void sample(FILE *out, const char *base, char names[][64], int n) {
    char line[2048];
    int len = snprintf(line, sizeof(line), "smp mono_ns=%" PRIu64, clock_ns(CLOCK_MONOTONIC));
    for (int i = 0; i < n && len > 0 && (size_t)len < sizeof(line); i++) {
        char fpath[512], val[64] = "?";
        snprintf(fpath, sizeof(fpath), "%s/hw_counters/%s", base, names[i]);
        int fd = open(fpath, O_RDONLY);
        if (fd >= 0) {
            ssize_t r = read(fd, val, sizeof(val) - 1);
            close(fd);
            if (r > 0) {
                val[r] = '\0';
                char *nl = strchr(val, '\n');
                if (nl) *nl = '\0';
            } else {
                snprintf(val, sizeof(val), "?");
            }
        }
        len += snprintf(line + len, sizeof(line) - (size_t)len, " %s=%s", names[i], val);
    }
    fprintf(out, "%s\n", line);
}

static void usage(const char *prog) {
    fprintf(stderr,
            "usage: %s -d dev [-p port] [-o out] [-T max_seconds] [-s sample_ms -c name,...]\n"
            "  records the async events of <dev> and the port's hw_counters/ and counters/\n"
            "  at start and at end (SIGTERM, SIGINT, SIGHUP, or after -T seconds; 0 = no bound)\n",
            prog);
}

int main(int argc, char **argv) {
    const char *dev = NULL, *out_path = NULL;
    int port = 1;
    double max_s = 0;
    long sample_ms = 0;
    char smp_names[SMP_MAX][64];
    int smp_n = 0;
    int opt;
    while ((opt = getopt(argc, argv, "d:p:o:T:s:c:h")) != -1) {
        switch (opt) {
            case 'd': dev = optarg; break;
            case 'p': port = atoi(optarg); break;
            case 'o': out_path = optarg; break;
            case 'T': max_s = atof(optarg); break;
            case 's': sample_ms = atol(optarg); break;
            case 'c': {
                char tmp[1024];
                snprintf(tmp, sizeof(tmp), "%s", optarg);
                for (char *tok = strtok(tmp, ","); tok && smp_n < SMP_MAX; tok = strtok(NULL, ","))
                    snprintf(smp_names[smp_n++], sizeof(smp_names[0]), "%s", tok);
                break;
            }
            case 'h': usage(argv[0]); return 0;
            default:  usage(argv[0]); return 2;
        }
    }
    if (!dev || port < 1 || port > 255 || max_s < 0 || sample_ms < 0 || (sample_ms > 0 && smp_n == 0)) {
        usage(argv[0]); return 2;
    }

    /* Block the end signals before anything else; they are only taken inside ppoll(),
     * so a signal that arrives during setup still ends the run with the end snapshot. */
    sigset_t ends, wait_mask;
    sigemptyset(&ends);
    sigaddset(&ends, SIGTERM); sigaddset(&ends, SIGINT); sigaddset(&ends, SIGHUP);
    sigprocmask(SIG_BLOCK, &ends, &wait_mask);
    sigdelset(&wait_mask, SIGTERM); sigdelset(&wait_mask, SIGINT); sigdelset(&wait_mask, SIGHUP);
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = on_signal;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGHUP, &sa, NULL);
    signal(SIGPIPE, SIG_IGN);

    FILE *out = out_path ? fopen(out_path, "w") : stdout;
    if (!out) { perror("fopen"); return 1; }
    setvbuf(out, NULL, _IOLBF, 0);   /* every record reaches the file as it is written */

    int num = 0;
    struct ibv_device **list = ibv_get_device_list(&num);
    if (!list) { perror("ibv_get_device_list"); return 1; }
    struct ibv_device *d = NULL;
    for (int i = 0; i < num; i++)
        if (strcmp(ibv_get_device_name(list[i]), dev) == 0) { d = list[i]; break; }
    if (!d) { fprintf(stderr, "evrec: device %s not found\n", dev); ibv_free_device_list(list); return 1; }
    struct ibv_context *ctx = ibv_open_device(d);
    ibv_free_device_list(list);
    if (!ctx) { fprintf(stderr, "evrec: ibv_open_device(%s) failed\n", dev); return 1; }

    /* non-blocking async fd (this process's descriptor only), so draining never blocks */
    int fl = fcntl(ctx->async_fd, F_GETFL);
    if (fl < 0 || fcntl(ctx->async_fd, F_SETFL, fl | O_NONBLOCK) < 0) {
        perror("fcntl(async_fd)"); ibv_close_device(ctx); return 1;
    }

    uint64_t mono0 = clock_ns(CLOCK_MONOTONIC);
    fprintf(out, "start dev=%s port=%d pid=%d max_s=%g mono_ns=%" PRIu64 " real_ns=%" PRIu64 "\n",
            dev, port, (int)getpid(), max_s, mono0, clock_ns(CLOCK_REALTIME));
    log_port(out, ctx, port, "start");
    snapshot(out, dev, port, "start");

    const uint64_t deadline = max_s > 0 ? mono0 + (uint64_t)(max_s * 1e9) : 0;
    char smp_base[256];
    snprintf(smp_base, sizeof(smp_base), "/sys/class/infiniband/%s/ports/%d", dev, port);
    const uint64_t smp_step = (uint64_t)sample_ms * 1000000ull;
    uint64_t next_smp = sample_ms > 0 ? clock_ns(CLOCK_MONOTONIC) : 0;
    const char *reason = "error";
    uint64_t events = 0;
    for (;;) {
        if (g_stop_sig) break;
        struct timespec ts, *tsp = NULL;
        uint64_t now = clock_ns(CLOCK_MONOTONIC);
        if (deadline && now >= deadline) { reason = "timeout"; break; }
        if (next_smp && now >= next_smp) {
            sample(out, smp_base, smp_names, smp_n);
            next_smp += smp_step;
            if (next_smp <= now) next_smp = now + smp_step;
            continue;
        }
        uint64_t wake = deadline;
        if (next_smp && (!wake || next_smp < wake)) wake = next_smp;
        if (wake) {
            uint64_t left = wake - now;
            ts.tv_sec = (time_t)(left / 1000000000ull);
            ts.tv_nsec = (long)(left % 1000000000ull);
            tsp = &ts;
        }
        struct pollfd p = { .fd = ctx->async_fd, .events = POLLIN, .revents = 0 };
        int r = ppoll(&p, 1, tsp, &wait_mask);
        if (r < 0) {
            if (errno == EINTR) continue;
            perror("ppoll"); break;
        }
        if (r == 0) continue;
        if (p.revents & POLLIN) {
            struct ibv_async_event ev;
            while (ibv_get_async_event(ctx, &ev) == 0) {
                uint64_t mono = clock_ns(CLOCK_MONOTONIC), real = clock_ns(CLOCK_REALTIME);
                log_event(out, ++events, &ev, mono, real);
                ibv_ack_async_event(&ev);
            }
            if (errno != EAGAIN && errno != EWOULDBLOCK) { perror("ibv_get_async_event"); break; }
        } else if (p.revents & (POLLERR | POLLHUP | POLLNVAL)) {
            fprintf(stderr, "evrec: async fd revents=0x%x\n", (unsigned)p.revents);
            break;
        }
    }
    if (g_stop_sig == SIGTERM) reason = "sigterm";
    else if (g_stop_sig == SIGINT) reason = "sigint";
    else if (g_stop_sig == SIGHUP) reason = "sighup";

    log_port(out, ctx, port, "end");
    snapshot(out, dev, port, "end");
    fprintf(out, "end reason=%s events=%" PRIu64 " mono_ns=%" PRIu64 " real_ns=%" PRIu64 "\n",
            reason, events, clock_ns(CLOCK_MONOTONIC), clock_ns(CLOCK_REALTIME));
    if (out != stdout) fclose(out);
    ibv_close_device(ctx);
    return strcmp(reason, "error") == 0 ? 1 : 0;
}
