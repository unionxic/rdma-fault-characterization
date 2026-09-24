/* fp_responder.c - the victim of the teardown-fingerprint experiment.
 *
 * Brings up one RC QP whose target MR covers either host memory, GPU memory
 * registered through nvidia_peermem (cudaMalloc + ibv_reg_mr), or GPU memory
 * registered as a dma-buf (cuMemGetHandleForAddressRange + ibv_reg_dmabuf_mr).
 * The creation order is selectable:
 *   -c none|cuda_first|ibv_first  CUDA context before/after ibv_open_device
 *                                 (decides which files get the lower fd numbers)
 *   -o mr_first|qp_first          MR registered before/after the QP is created
 *                                 (decides the order of the uverbs objects)
 * Between the steps it opens "marker" TCP connections to fp_launcher on
 * 127.0.0.1:<-K>. Each marker is one more file in the fd table; its FIN, seen by
 * the launcher, timestamps the moment the kernel released that fd at exit.
 *   -U <n>   dup2(uverbs cmd_fd, n): the uverbs file is then released at position n
 *   -V <b>   dup2 every /dev/nvidia* fd to b, b+1, ...: same for the CUDA files
 *   -X <n>   register n extra host MRs (-Y bytes each, default 4 MiB) right before the
 *            data MR, i.e. between QP and data MR when -o qp_first: at teardown they are
 *            destroyed after the data MR and before the QP (a longer window)
 * Then it serves the requester on TCP <-P>: exchanges QP info, says READY, and
 * waits. "ACT <x>" performs an explicit teardown step while the process stays
 * alive (x = dereg_mr | destroy_qp | cuda_free | cuda_reset | reset_then_dereg | qp_err).
 * The fault itself (SIGKILL) comes from fp_launcher.
 */
#define _GNU_SOURCE
#include "fp_common.h"
#include "fp_devx.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <getopt.h>
#include <dirent.h>
#include <signal.h>
#include <limits.h>
#include <cuda.h>
#include <cuda_runtime.h>

enum { MEM_HOST, MEM_GPU, MEM_DMABUF };
enum { ORD_MR_FIRST, ORD_QP_FIRST };
enum { CU_NONE, CU_FIRST, CU_AFTER_IBV };

static int g_marker_port = -1;
static int g_nmarkers = 0;

/* open a marker connection; the launcher reads "M <label> <fd> <t_ns>" from it */
static void marker(const char *label) {
    if (g_marker_port < 0) return;
    int fd = fp_connect("127.0.0.1", g_marker_port);
    if (fd < 0) { fprintf(stderr, "[resp] marker %s: connect failed\n", label); return; }
    fp_send_line(fd, "M %s %d %lu", label, fd, (unsigned long)fp_now_ns());
    g_nmarkers++;
    fprintf(stderr, "[resp] MARK %s fd=%d\n", label, fd);
}

static const char *fd_kind(const char *t) {
    if (!strncmp(t, "/dev/nvidiactl", 14)) return "nvctl";
    if (!strncmp(t, "/dev/nvidia-uvm", 15)) return "uvm";
    if (!strncmp(t, "/dev/nvidia", 11)) return "nvdev";
    if (!strncmp(t, "/dev/infiniband/uverbs", 22)) return "uverbs";
    if (strstr(t, "infinibandevent")) return "ibevt";
    if (!strncmp(t, "socket:", 7)) return "sock";
    if (!strncmp(t, "anon_inode:", 11)) return "anon";
    if (!strncmp(t, "pipe:", 5)) return "pipe";
    if (!strncmp(t, "/dev/pts", 8) || !strncmp(t, "/dev/null", 9)) return "tty";
    return "other";
}

/* print the fd table to stderr and build a compact "fd:kind,..." summary */
static void fd_table(char *summary, size_t cap) {
    size_t off = 0;
    summary[0] = 0;
    int fds[1024], n = 0;
    DIR *d = opendir("/proc/self/fd");
    if (!d) return;
    int dfd = dirfd(d);
    struct dirent *e;
    while ((e = readdir(d)) && n < 1024) {
        if (e->d_name[0] == '.') continue;
        int fd = atoi(e->d_name);
        if (fd == dfd) continue;
        fds[n++] = fd;
    }
    closedir(d);
    for (int i = 0; i < n; i++)          /* sort ascending */
        for (int j = i + 1; j < n; j++)
            if (fds[j] < fds[i]) { int t = fds[i]; fds[i] = fds[j]; fds[j] = t; }
    for (int i = 0; i < n; i++) {
        char p[64], t[PATH_MAX];
        snprintf(p, sizeof(p), "/proc/self/fd/%d", fds[i]);
        ssize_t l = readlink(p, t, sizeof(t) - 1);
        if (l < 0) continue;
        t[l] = 0;
        fprintf(stderr, "[resp] FD %d %s\n", fds[i], t);
        if (off + 32 < cap)
            off += (size_t)snprintf(summary + off, cap - off, "%s%d:%s", off ? "," : "", fds[i], fd_kind(t));
    }
}

/* how many mappings of each device file the process holds: a mapped file's last
 * reference can be its VMA rather than its fd (released at mm teardown, not at close) */
static void maps_summary(void) {
    const char *keys[] = { "/dev/infiniband/uverbs", "/dev/nvidiactl", "/dev/nvidia-uvm", "/dev/nvidia0" };
    int cnt[4] = { 0, 0, 0, 0 };
    char line[512];
    FILE *f = fopen("/proc/self/maps", "r");
    if (!f) return;
    while (fgets(line, sizeof(line), f))
        for (int k = 0; k < 4; k++)
            if (strstr(line, keys[k])) { cnt[k]++; break; }
    fclose(f);
    fprintf(stderr, "[resp] MAPS uverbs=%d nvidiactl=%d nvidia-uvm=%d nvidia0=%d\n", cnt[0], cnt[1], cnt[2], cnt[3]);
}

static void cuda_init(void) {
    uint64_t t0 = fp_now_ns();
    cudaError_t e = cudaSetDevice(0);
    if (e == cudaSuccess) e = cudaFree(0);
    if (e != cudaSuccess) { fprintf(stderr, "[resp] CUDA init: %s\n", cudaGetErrorString(e)); exit(3); }
    fprintf(stderr, "[resp] cuda init %.1f ms\n", (fp_now_ns() - t0) / 1e6);
}

int main(int argc, char **argv) {
    const char *dev = "mlx5_0";
    int port = 1, gid = -1, oob_port = 18932, dup_uverbs = -1, dup_nv = -1, n_extra = 0;
    size_t extra_bytes = 4u << 20;
    int mem = MEM_HOST, ord = ORD_MR_FIRST, cu = CU_NONE, keep_dmabuf_fd = 0, devx = 0;
    fp_devx_qp_t dq;
    memset(&dq, 0, sizeof(dq));
    size_t bytes = 8u << 20;
    int opt;
    while ((opt = getopt(argc, argv, "d:i:g:P:K:m:o:c:B:U:V:kq:r:X:Y:")) != -1) {
        switch (opt) {
            case 'd': dev = optarg; break;
            case 'i': port = atoi(optarg); break;
            case 'g': gid = atoi(optarg); break;
            case 'P': oob_port = atoi(optarg); break;
            case 'K': g_marker_port = atoi(optarg); break;
            case 'm': mem = !strcmp(optarg, "gpu") ? MEM_GPU : !strcmp(optarg, "dmabuf") ? MEM_DMABUF : MEM_HOST; break;
            case 'o': ord = !strcmp(optarg, "qp_first") ? ORD_QP_FIRST : ORD_MR_FIRST; break;
            case 'c': cu = !strcmp(optarg, "cuda_first") ? CU_FIRST : !strcmp(optarg, "ibv_first") ? CU_AFTER_IBV : CU_NONE; break;
            case 'B': bytes = (size_t)strtoull(optarg, NULL, 0); break;
            case 'U': dup_uverbs = atoi(optarg); break;
            case 'V': dup_nv = atoi(optarg); break;
            case 'k': keep_dmabuf_fd = 1; break;
            case 'q': devx = !strcmp(optarg, "devx"); break;
            case 'r': fp_min_rnr_timer = atoi(optarg); break;
            case 'X': n_extra = atoi(optarg); break;
            case 'Y': extra_bytes = (size_t)strtoull(optarg, NULL, 0); break;
            default:
                fprintf(stderr, "usage: %s -d dev [-g gid] -P oob_port -K marker_port -m host|gpu|dmabuf "
                                "-o mr_first|qp_first -c none|cuda_first|ibv_first [-q verbs|devx] [-r min_rnr_timer] [-X n_extra_mrs] [-Y extra_bytes] [-B bytes] [-U fd] [-V fd] [-k]\n", argv[0]);
                return 2;
        }
    }
    if (mem != MEM_HOST && cu == CU_NONE) cu = CU_FIRST;
    signal(SIGPIPE, SIG_IGN);
    fprintf(stderr, "[resp] pid %d qp=%s mem=%s order=%s cuda=%s bytes=%zu min_rnr_timer=%d\n", getpid(), devx ? "devx" : "verbs",
            mem == MEM_HOST ? "host" : mem == MEM_GPU ? "gpu" : "dmabuf",
            ord == ORD_MR_FIRST ? "mr_first" : "qp_first",
            cu == CU_NONE ? "none" : cu == CU_FIRST ? "cuda_first" : "ibv_first", bytes, fp_min_rnr_timer);

    marker("start");
    if (cu == CU_FIRST) { cuda_init(); marker("after_cuda"); }

    fp_ep_t ep;
    if (fp_open(&ep, dev, port, gid, devx) < 0) return 1;
    fprintf(stderr, "[resp] uverbs cmd_fd=%d async_fd=%d\n", ep.ctx->cmd_fd, ep.ctx->async_fd);
    marker("after_ibv");
    if (cu == CU_AFTER_IBV) { cuda_init(); marker("after_cuda"); }

    void *buf = NULL;
    struct ibv_mr *mr = NULL;
    int dmabuf_fd = -1;
    const int acc = IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE | IBV_ACCESS_REMOTE_READ;
    for (int step = 0; step < 2; step++) {
        int do_mr = (ord == ORD_MR_FIRST) ? (step == 0) : (step == 1);
        if (!do_mr) {
            if (devx ? fp_devx_qp_create(ep.ctx, ep.pd, ep.cq, &dq) : fp_create_qp(&ep, 64)) return 1;
            if (devx) fprintf(stderr, "[resp] DEVX QP qpn 0x%x\n", dq.qpn);
            marker("after_qp");
            continue;
        }
        for (int x = 0; x < n_extra; x++) {
            void *xb = aligned_alloc(4096, extra_bytes);
            if (!xb) return 1;
            memset(xb, 0, extra_bytes);
            if (!ibv_reg_mr(ep.pd, xb, extra_bytes, acc)) { perror("extra ibv_reg_mr"); return 1; }
        }
        if (n_extra) fprintf(stderr, "[resp] %d extra host MRs of %zu bytes registered\n", n_extra, extra_bytes);
        if (mem == MEM_HOST) {
            buf = aligned_alloc(4096, bytes);
            if (!buf) return 1;
            memset(buf, 0, bytes);
            mr = ibv_reg_mr(ep.pd, buf, bytes, acc);
        } else {
            cudaError_t e = cudaMalloc(&buf, bytes);
            if (e != cudaSuccess) { fprintf(stderr, "[resp] cudaMalloc: %s\n", cudaGetErrorString(e)); return 3; }
            cudaMemset(buf, 0, bytes);
            cudaDeviceSynchronize();
            if (mem == MEM_GPU) {
                mr = ibv_reg_mr(ep.pd, buf, bytes, acc);
            } else {
                int sup = 0;
                CUdevice cd;
                cuDeviceGet(&cd, 0);
                cuDeviceGetAttribute(&sup, CU_DEVICE_ATTRIBUTE_DMA_BUF_SUPPORTED, cd);
                CUresult r = cuMemGetHandleForAddressRange(&dmabuf_fd, (CUdeviceptr)buf, bytes,
                                                           CU_MEM_RANGE_HANDLE_TYPE_DMA_BUF_FD, 0);
                fprintf(stderr, "[resp] dma_buf supported=%d get_handle rc=%d fd=%d\n", sup, (int)r, dmabuf_fd);
                if (r != CUDA_SUCCESS) return 4;
                mr = ibv_reg_dmabuf_mr(ep.pd, 0, bytes, (uint64_t)(uintptr_t)buf, dmabuf_fd, acc);
                if (mr && !keep_dmabuf_fd) { close(dmabuf_fd); dmabuf_fd = -1; }   /* as NCCL does */
            }
        }
        if (!mr) { fprintf(stderr, "[resp] MR registration failed: %s\n", strerror(errno)); return 1; }
        fprintf(stderr, "[resp] MR lkey=0x%x rkey=0x%x addr=%p len=%zu\n", mr->lkey, mr->rkey, buf, bytes);
        marker("after_mr");
    }

    if (dup_uverbs >= 0) {
        if (dup2(ep.ctx->cmd_fd, dup_uverbs) < 0) perror("dup2 uverbs");
        else fprintf(stderr, "[resp] dup uverbs fd %d -> %d\n", ep.ctx->cmd_fd, dup_uverbs);
    }
    if (dup_nv >= 0) {
        int k = 0;
        for (int fd = 0; fd < dup_nv && fd < 1024; fd++) {
            char p[64], t[PATH_MAX];
            snprintf(p, sizeof(p), "/proc/self/fd/%d", fd);
            ssize_t l = readlink(p, t, sizeof(t) - 1);
            if (l < 0) continue;
            t[l] = 0;
            if (strncmp(t, "/dev/nvidia", 11)) continue;
            if (dup2(fd, dup_nv + k) >= 0) fprintf(stderr, "[resp] dup %s fd %d -> %d\n", t, fd, dup_nv + k);
            k++;
        }
    }

    int lfd = fp_listen(NULL, oob_port);
    if (lfd < 0) return 1;
    fprintf(stderr, "[resp] listening on %d\n", oob_port);
    int cfd = fp_accept(lfd);
    if (cfd < 0) return 1;
    marker("last");

    fp_dest_t me, peer;
    memset(&me, 0, sizeof(me));
    me.qpn = devx ? dq.qpn : ep.qp->qp_num;
    me.psn = (uint32_t)(fp_now_ns() & 0xffffff);
    me.rkey = mr->rkey;
    me.addr = (uint64_t)(uintptr_t)buf;
    me.size = bytes;
    me.gid = ep.gid;
    if (fp_send_all(cfd, &me, sizeof(me)) < 0 || fp_recv_all(cfd, &peer, sizeof(peer)) < 0) return 1;
    if (devx ? fp_devx_qp_connect(&dq, ep.pd, ep.port, ep.gid_index, ep.port_attr.active_mtu, &peer, me.psn)
             : fp_qp_to_rts(&ep, &peer, me.psn)) return 1;

    char fds[2048];
    fd_table(fds, sizeof(fds));
    maps_summary();
    if (fp_send_line(cfd, "READY %d %d %d %s", getpid(), ep.ctx->cmd_fd, g_nmarkers, fds) < 0) return 1;

    char line[256];
    while (fp_recv_line(cfd, line, sizeof(line)) >= 0) {
        char act[64] = "";
        if (sscanf(line, "ACT %63s", act) != 1) continue;
        int rc = 0;
        uint64_t t0 = fp_now_ns();
        if (!strcmp(act, "dereg_mr")) {
            rc = ibv_dereg_mr(mr);
            mr = NULL;
        } else if (!strcmp(act, "destroy_qp")) {
            rc = devx ? fp_devx_qp_destroy(&dq) : ibv_destroy_qp(ep.qp);
            ep.qp = NULL;
        } else if (!strcmp(act, "qp_err") && !devx) {
            struct ibv_qp_attr a;
            memset(&a, 0, sizeof(a));
            a.qp_state = IBV_QPS_ERR;
            rc = ibv_modify_qp(ep.qp, &a, IBV_QP_STATE);
        } else if (!strcmp(act, "cuda_free")) {
            rc = (int)cudaFree(buf);
        } else if (!strcmp(act, "cuda_reset")) {
            rc = (int)cudaDeviceReset();
        } else if (!strcmp(act, "reset_then_dereg")) {
            /* destroy the CUDA context first (the MR's pages stay pinned by nvidia_peermem),
             * then time only the deregistration: t0/t1 bracket ibv_dereg_mr */
            uint64_t r0 = fp_now_ns();
            rc = (int)cudaDeviceReset();
            fprintf(stderr, "[resp] ACT reset part rc=%d %.3f ms\n", rc, (fp_now_ns() - r0) / 1e6);
            t0 = fp_now_ns();
            rc = rc ? rc : ibv_dereg_mr(mr);
            mr = NULL;
        } else {
            rc = -1;
        }
        uint64_t t1 = fp_now_ns();
        fprintf(stderr, "[resp] ACT %s rc=%d %.3f ms\n", act, rc, (t1 - t0) / 1e6);
        fp_send_line(cfd, "ACTED %s %d %lu %lu", act, rc, (unsigned long)t0, (unsigned long)t1);
    }
    fprintf(stderr, "[resp] requester closed; exiting\n");
    return 0;
}
