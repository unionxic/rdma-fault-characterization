// synd.c: injects one fault on a loopback RC QP pair (A requests, B responds, same port, one process) and
// prints what the NIC reports: CQEs on both sides, the error syndrome the NIC keeps in each QP context
// (QUERY_QP with qpc_ext, the value the kernel prints as "QP N error: ..."), async events, port hw_counters that moved.
// usage: synd <device> <gid_index> <case> [gap_ms|T timeout retry]      build: gcc -O2 -o synd synd.c -libverbs -lmlx5
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <infiniband/mlx5dv.h>
#include <infiniband/verbs.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define CHK(x) do { if (!(x)) { printf("case=%s setup failed: %s (errno %d)\n", name, #x, errno); exit(2); } } while (0)
#define SZ 4096
#define K 8  // writes per direction and phase in the psn_* cases
static const char *name;
static int tmo = 14, retry = 2;  // RTS ack timeout, retry_cnt and rnr_retry (argv[5], argv[6])
// ibv_wc_status -> mlx5 CQE syndrome, as mapped by the mlx5 provider (mlx5dv.h names).
static const int synd[] = {0, 0x01, 0x02, -1, 0x04, 0x05, 0x06, 0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, -1, -1, 0x22};

#define NCNT 64
static char cdir[256], cname[NCNT][64];
static long long cval[NCNT];
static int ncnt;
static void counters(int after) {
  DIR *d = opendir(cdir);
  struct dirent *e;
  for (int i = 0; d && (e = readdir(d));) {
    char p[512];
    long long v = 0;
    if (e->d_name[0] == '.' || !strcmp(e->d_name, "lifespan")) continue;
    snprintf(p, sizeof p, "%s/%s", cdir, e->d_name);
    FILE *f = fopen(p, "r");
    if (!f || fscanf(f, "%lld", &v) != 1) v = 0;
    if (f) fclose(f);
    if (!after && ncnt < NCNT) { snprintf(cname[ncnt], 64, "%s", e->d_name); cval[ncnt++] = v; }
    for (i = 0; after && i < ncnt; i++)
      if (!strcmp(cname[i], e->d_name) && v != cval[i]) printf(" %s+%lld", cname[i], v - cval[i]);
  }
  if (d) closedir(d);
}

static void connect_qp(struct ibv_qp *q, uint32_t dqpn, union ibv_gid *gid, int gidx, int access, int rd, int drd, uint32_t rpsn, uint32_t spsn) {
  struct ibv_qp_attr a = {.qp_state = IBV_QPS_INIT, .port_num = 1, .qp_access_flags = access};
  CHK(!ibv_modify_qp(q, &a, IBV_QP_STATE | IBV_QP_PKEY_INDEX | IBV_QP_PORT | IBV_QP_ACCESS_FLAGS));
  memset(&a, 0, sizeof a);
  a.qp_state = IBV_QPS_RTR; a.path_mtu = IBV_MTU_1024; a.dest_qp_num = dqpn; a.max_dest_rd_atomic = drd; a.min_rnr_timer = 12; a.rq_psn = rpsn;
  a.ah_attr.is_global = 1; a.ah_attr.port_num = 1; a.ah_attr.grh.dgid = *gid; a.ah_attr.grh.sgid_index = gidx; a.ah_attr.grh.hop_limit = 1;
  CHK(!ibv_modify_qp(q, &a, IBV_QP_STATE | IBV_QP_AV | IBV_QP_PATH_MTU | IBV_QP_DEST_QPN | IBV_QP_RQ_PSN | IBV_QP_MAX_DEST_RD_ATOMIC | IBV_QP_MIN_RNR_TIMER));
  memset(&a, 0, sizeof a);
  a.qp_state = IBV_QPS_RTS; a.timeout = tmo; a.retry_cnt = retry; a.rnr_retry = retry; a.max_rd_atomic = rd; a.sq_psn = spsn;
  CHK(!ibv_modify_qp(q, &a, IBV_QP_STATE | IBV_QP_TIMEOUT | IBV_QP_RETRY_CNT | IBV_QP_RNR_RETRY | IBV_QP_SQ_PSN | IBV_QP_MAX_QP_RD_ATOMIC));
}

static int drain(struct ibv_cq *cq, const char *side) {
  struct ibv_wc wc;
  int n = 0;
  while (ibv_poll_cq(cq, 1, &wc) > 0) {
    n++;
    printf(" | %s: wr=%d status=%d(%s) syndrome=%#x vendor_err=%#x", side, (int)wc.wr_id, wc.status, ibv_wc_status_str(wc.status),
           wc.status < 17 ? synd[wc.status] : -1, wc.status ? wc.vendor_err : 0);  // vendor_err is not set on success
  }
  return n;
}

static uint8_t qpc_saved[256];  // qpc of the last qp_query, for sqctr*

// QUERY_QP with qpc_ext=1: the QP context extension holds one error record (layout: mlx5_ifc.h,
// qp_context_extension.error_syndrome, at byte 284 of the output). Returns {acked_psn, next_psn, rcv_psn}.
static const uint32_t *qp_query(struct ibv_qp *q, const char *side) {
  static uint32_t p[3];
  uint8_t in[16] = {0x05, 0x0b}, out[464] = {0};
  const uint32_t w = htobe32(0x80000000u | q->qp_num);
  memcpy(in + 8, &w, 4);
  const int rc = mlx5dv_devx_qp_query(q, in, sizeof in, out, sizeof out);
  if (rc) printf(" %s=query failed rc=%d cmd_status=%#x", side, rc, out[0]);
  else {
    // qpc starts at byte 24 of the output; offsets inside it from mlx5_ifc.h (qpc_bits)
    const uint8_t *c = out + 24;
    memcpy(qpc_saved, c, sizeof qpc_saved);
    p[0] = c[137] << 16 | c[138] << 8 | c[139]; p[1] = c[121] << 16 | c[122] << 8 | c[123]; p[2] = c[149] << 16 | c[150] << 8 | c[151];
    if (*side) printf(" %s=syndrome=%#x vendor_err=%#x hw_type=%#x hw_err=%#x sq_hw=%u sq_sw=%u acked_psn=%u next_psn=%u rcv_psn=%u", side,
           out[287], out[286], out[285] >> 4, out[284], c[180] << 8 | c[181], c[182] << 8 | c[183], p[0], p[1], p[2]);
  }
  return p;
}

// Reads the QP's own record and moves it to RESET. ps gets {rq_psn, sq_psn} that continue its sequence when it is
// connected again: its next expected receive PSN and its last acknowledged PSN + 1.
static void reset_qp(struct ibv_qp *q, const char *side, uint32_t *ps) {
  const uint32_t *p = qp_query(q, side);
  struct ibv_qp_attr r = {.qp_state = IBV_QPS_RESET};
  ps[0] = p[2]; ps[1] = (p[0] + 1) & 0xffffff;
  CHK(!ibv_modify_qp(q, &r, IBV_QP_STATE));
  printf(" -> rq_psn=%u sq_psn=%u", ps[0], ps[1]);
}

// sqctr*: one QP transition by devx from a saved context (rst2init/init2rtr/rtr2rts_qp_in: qpc at byte 24) with
// hw_sq_wqebb_counter and sw_sq_wqebb_counter (qpc bytes 180-183) set to x.
static void devx_mod(struct ibv_qp *q, uint16_t op, uint32_t x) {
  uint8_t in[24 + 256 + 16] = {op >> 8, op & 0xff}, out[16] = {0}, *c = in + 24;
  const uint32_t w = htobe32(q->qp_num);
  memcpy(in + 8, &w, 4); memcpy(c, qpc_saved, 256);
  c[180] = c[182] = x >> 8; c[181] = c[183] = x & 0xff;
  const int rc = mlx5dv_devx_qp_modify(q, in, sizeof in, out, sizeof out);
  printf(" | op %#x rc=%d status=%#x syndrome=%#x:", op, rc, out[0], be32toh(*(uint32_t *)(out + 4)));
}

// sqctr*, noplap: a hand-made WQE in SQ slot `slot` whose ctrl segment carries index `idx`: a 16-byte RDMA write with a
// CQE, or with dst NULL an unsignaled NOP. Returns the SQ size.
static uint32_t wqe_raw(struct ibv_qp *q, uint32_t slot, uint32_t idx, void *src, uint32_t lkey, void *dst, uint32_t rkey) {
  struct mlx5dv_qp d;
  struct mlx5dv_obj o = {.qp = {q, &d}};
  CHK(!mlx5dv_init_obj(&o, MLX5DV_OBJ_QP));
  uint32_t *w = (uint32_t *)((char *)d.sq.buf + (slot & (d.sq.wqe_cnt - 1)) * d.sq.stride);
  memset(w, 0, 64);
  w[0] = htobe32(idx << 8 | (dst ? 0x08 : 0)); w[1] = htobe32(q->qp_num << 8 | (dst ? 3 : 1)); w[2] = htobe32(dst ? 0x08 : 0);
  *(uint64_t *)(w + 4) = htobe64((uintptr_t)dst); w[6] = htobe32(rkey);
  w[8] = htobe32(16); w[9] = htobe32(lkey); *(uint64_t *)(w + 10) = htobe64((uintptr_t)src);
  return d.sq.wqe_cnt;
}

// Rings the SQ as GIN does: doorbell record and doorbell both carry the producer index n.
static void ring_raw(struct ibv_qp *q, uint32_t n) {
  struct mlx5dv_qp d;
  struct mlx5dv_obj o = {.qp = {q, &d}};
  CHK(!mlx5dv_init_obj(&o, MLX5DV_OBJ_QP));
  const uint32_t db[2] = {htobe32((n & 0xffff) << 8), htobe32(q->qp_num << 8)};
  uint64_t v;
  memcpy(&v, db, sizeof v);
  __sync_synchronize();
  d.dbrec[MLX5_SND_DBR] = htobe32(n & 0xffff);
  __sync_synchronize();
  *(volatile uint64_t *)d.bf.reg = v;
}

// sqctr*, noplap: waits up to 2 s for the CQE after consumer index ci of cq and prints its opcode and wqe_counter (CQE64 bytes 60-61).
static void raw_cqe(struct ibv_cq *cq, uint32_t ci) {
  struct mlx5dv_cq d;
  struct mlx5dv_obj o = {.cq = {cq, &d}};
  CHK(!mlx5dv_init_obj(&o, MLX5DV_OBJ_CQ));
  volatile uint8_t *e = (uint8_t *)d.buf + (ci & (d.cqe_cnt - 1)) * d.cqe_size + d.cqe_size - 64;
  for (int ms = 0; ms < 2000 && ((e[63] >> 4) == 0xf || (e[63] & 1) != !!(ci & d.cqe_cnt)); ms++) usleep(1000);
  printf(" | raw CQE: opcode=%#x wqe_counter=%#x syndrome=%#x", e[63] >> 4, e[60] << 8 | e[61], e[55]);
}

static double ms_since(const struct timespec *t0) {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return (t.tv_sec - t0->tv_sec) * 1e3 + (t.tv_nsec - t0->tv_nsec) / 1e6;
}

// Write n of one direction: 16 bytes (n+1, n+1) from slot n of the sender's lower half to word n of the receiver's
// upper half. Write n+1 overwrites word n+1, so a lost write n leaves word n != n+1 and a late one shows in word n+1.
static void put(struct ibv_qp *q, uint64_t *src, uint32_t lkey, uint64_t *dst, uint32_t rkey, int n) {
  struct ibv_sge s = {(uintptr_t)(src + 2 * n), 16, lkey};
  struct ibv_send_wr w = {.wr_id = 100 + n, .sg_list = &s, .num_sge = 1, .opcode = IBV_WR_RDMA_WRITE, .send_flags = IBV_SEND_SIGNALED}, *bad;
  src[2 * n] = src[2 * n + 1] = n + 1;
  w.wr.rdma.remote_addr = (uintptr_t)(dst + n); w.wr.rdma.rkey = rkey;
  CHK(!ibv_post_send(q, &w, &bad));
}

// Polls until n CQEs or max_ms; prints them and how long it took.
static void poll_n(struct ibv_cq *cq, const char *side, int n, int max_ms) {
  struct timespec t0;
  int got = 0;
  clock_gettime(CLOCK_MONOTONIC, &t0);
  while (got < n && ms_since(&t0) < max_ms) got += drain(cq, side), usleep(100);
  printf(" | %s: %d/%d CQEs in %.1f ms", side, got, n, ms_since(&t0));
}

// The receiver's memory after writes 0..n-1 of one direction: word i must be i+1, and word n must be n.
static void check(const char *side, const uint64_t *d, int n) {
  int i = 0;
  while (i < n && d[i] == (uint64_t)i + 1) i++;
  if (i == n && d[n] == (uint64_t)n) printf(" | %s_mem=ok(%d writes)", side, n);
  else printf(" | %s_mem=BAD word %d = %llu (want %d)", side, i, (unsigned long long)d[i], i < n ? i + 1 : n);
}

int main(int argc, char **argv) {
  if (argc < 4) return fprintf(stderr, "usage: synd <device> <gid_index> <case>\n"), 1;
  const int gidx = atoi(argv[2]);
  name = argv[3];
  if (argc > 6) tmo = atoi(argv[5]), retry = atoi(argv[6]);
#define IS(s) (!strcmp(name, s))
  struct ibv_device **list = ibv_get_device_list(NULL), *dev = NULL;
  for (int i = 0; list && list[i]; i++) if (!strcmp(ibv_get_device_name(list[i]), argv[1])) dev = list[i];
  CHK(dev);
  struct mlx5dv_context_attr dva = {.flags = MLX5DV_CONTEXT_FLAGS_DEVX};  // devx is needed for QUERY_QP
  struct ibv_context *ctx = mlx5dv_open_device(dev, &dva);
  CHK(ctx);
  snprintf(cdir, sizeof cdir, "/sys/class/infiniband/%s/ports/1/hw_counters", argv[1]);
  fcntl(ctx->async_fd, F_SETFL, fcntl(ctx->async_fd, F_GETFL) | O_NONBLOCK);
  struct ibv_pd *pd = ibv_alloc_pd(ctx);
  struct ibv_cq *cqa = ibv_create_cq(ctx, 16, NULL, NULL, 0), *cqb = ibv_create_cq(ctx, 16, NULL, NULL, 0);
  CHK(pd && cqa && cqb);
  struct ibv_qp_init_attr ia = {.send_cq = cqa, .recv_cq = cqa, .qp_type = IBV_QPT_RC, .cap = {16, 16, 1, 1, 0}};
  struct ibv_qp *qa = ibv_create_qp(pd, &ia);
  ia.send_cq = ia.recv_cq = cqb;
  struct ibv_qp *qb = ibv_create_qp(pd, &ia);
  CHK(qa && qb);
  union ibv_gid gid;
  CHK(!ibv_query_gid(ctx, 1, gidx, &gid));
  const int all = IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE | IBV_ACCESS_REMOTE_READ | IBV_ACCESS_REMOTE_ATOMIC;
  connect_qp(qa, qb->qp_num, &gid, gidx, all, IS("read_req0") ? 0 : 1, 1, 0, 0);
  connect_qp(qb, qa->qp_num, &gid, gidx, IS("qp_no_write") ? IBV_ACCESS_REMOTE_READ : all, 1, IS("read_resp0") ? 0 : 1, 0, 0);

  char *ba = aligned_alloc(4096, SZ), *bb = aligned_alloc(4096, SZ);
  struct ibv_mr *ma = ibv_reg_mr(pd, ba, SZ, all);  // remote access for the psn_* writes B -> A
  struct ibv_mr *ma_ro = ibv_reg_mr(pd, ba, SZ, 0);  // no LOCAL_WRITE
  struct ibv_mr *mb = ibv_reg_mr(pd, bb, SZ, all);
  struct ibv_mr *mb_ro = ibv_reg_mr(pd, bb, SZ, IBV_ACCESS_REMOTE_READ);  // no REMOTE_WRITE
  CHK(ma && ma_ro && mb && mb_ro);

  // Default request: 64-byte RDMA write A -> B, valid. Each case changes one thing.
  struct ibv_sge sge = {(uintptr_t)ba, 64, ma->lkey}, rsge = {(uintptr_t)bb, 64, mb->lkey};
  struct ibv_send_wr wr = {.wr_id = 1, .sg_list = &sge, .num_sge = 1, .opcode = IBV_WR_RDMA_WRITE, .send_flags = IBV_SEND_SIGNALED}, *bad;
  wr.wr.rdma.remote_addr = (uintptr_t)bb;
  wr.wr.rdma.rkey = mb->rkey;
  struct ibv_recv_wr rwr = {.wr_id = 2, .sg_list = &rsge, .num_sge = 1}, *rbad;
  int rc = 0, second = 0, recv = 0;
  counters(0);

  if (IS("ok")) ;
  else if (IS("bad_lkey")) sge.lkey = 0xdeadbeef;
  else if (IS("sge_len")) sge.length = 2 * SZ;                       // runs past the local MR
  else if (IS("loc_perm")) { wr.opcode = IBV_WR_RDMA_READ; sge.lkey = ma_ro->lkey; }
  else if (IS("bad_rkey")) wr.wr.rdma.rkey = 0xdeadbeef;
  else if (IS("rem_range")) wr.wr.rdma.remote_addr += SZ;            // past the remote MR
  else if (IS("rem_perm")) wr.wr.rdma.rkey = mb_ro->rkey;
  else if (IS("qp_no_write")) ;                                      // B was set up without REMOTE_WRITE
  else if (IS("atomic_align")) { wr.opcode = IBV_WR_ATOMIC_FETCH_AND_ADD; sge.length = 8; wr.wr.atomic.remote_addr = (uintptr_t)bb + 1; wr.wr.atomic.rkey = mb->rkey; wr.wr.atomic.compare_add = 1; }
  else if (IS("read_req0") || IS("read_resp0")) wr.opcode = IBV_WR_RDMA_READ;
  // Attempts at the syndromes the cases above do not produce (0x02, 0x11, 0x06).
  else if (IS("atomic_len")) { wr.opcode = IBV_WR_ATOMIC_FETCH_AND_ADD; sge.length = 16; wr.wr.atomic.remote_addr = (uintptr_t)bb; wr.wr.atomic.rkey = mb->rkey; wr.wr.atomic.compare_add = 1; }
  else if (IS("sge_inline_bit")) sge.length = 0x80000040;            // mlx5 reads bit 31 of byte_count as "inline data"
  else if (IS("zero_sge_read")) { wr.opcode = IBV_WR_RDMA_READ; wr.num_sge = 0; }
  else if (IS("imm_bad_rkey")) { wr.opcode = IBV_WR_RDMA_WRITE_WITH_IMM; wr.wr.rdma.rkey = 0xdeadbeef; recv = 1; }
  else if (IS("imm_recv_bad_lkey")) { wr.opcode = IBV_WR_RDMA_WRITE_WITH_IMM; rsge.lkey = 0xdeadbeef; recv = 1; }
  else if (IS("recv_small")) { wr.opcode = IBV_WR_SEND; rsge.length = 16; recv = 1; }
  else if (IS("recv_bad_lkey")) { wr.opcode = IBV_WR_SEND; rsge.lkey = 0xdeadbeef; recv = 1; }
  else if (IS("recv_ro")) { wr.opcode = IBV_WR_SEND; rsge.lkey = mb_ro->lkey; recv = 1; }
  else if (IS("no_recv")) wr.opcode = IBV_WR_SEND;
  else if (IS("peer_gone")) CHK(!ibv_destroy_qp(qb));
  else if (IS("peer_err") || IS("peer_reset")) { struct ibv_qp_attr a = {.qp_state = IS("peer_err") ? IBV_QPS_ERR : IBV_QPS_RESET}; CHK(!ibv_modify_qp(qb, &a, IBV_QP_STATE)); }
  else if (IS("local_err")) { struct ibv_qp_attr a = {.qp_state = IBV_QPS_ERR}; CHK(!ibv_modify_qp(qa, &a, IBV_QP_STATE)); }
  else if (IS("flush_after")) { wr.wr.rdma.rkey = 0xdeadbeef; second = 1; }
  // Where did it stop: 8 writes in flight, the 4th (burst_bad) is rejected, or B fails first (burst_peer_err).
  else if (IS("burst_bad") || IS("burst_ok") || IS("burst_peer_err") || IS("reset_reuse")) {
    if (IS("burst_peer_err")) { struct ibv_qp_attr a = {.qp_state = IBV_QPS_ERR}; CHK(!ibv_modify_qp(qb, &a, IBV_QP_STATE)); }
    for (int i = 0; i < 7; i++) {
      wr.wr_id = 10 + i;
      wr.wr.rdma.rkey = ((IS("burst_bad") || IS("reset_reuse")) && i == 3) ? 0xdeadbeef : mb->rkey;
      CHK(!ibv_post_send(qa, &wr, &bad));
    }
    wr.wr_id = 17; wr.wr.rdma.rkey = mb->rkey;  // the 8th is posted below
  }
  // psn_*: K writes A -> B and K/2 B -> A, A's QP fails, and the failed QP(s) are rebuilt alone from their own record (reset_qp)
  // while the other side does nothing. psn_a: A moved to ERR idle; psn_a_inflight: with writes posted around the ERR,
  // which A re-posts from its new sq_psn (here the PSN is the write's number); psn_a0: as psn_a but restarted at 0; psn_both:
  // a bad rkey from A fails both; psn_late_{err,reset}: as psn_both, but A posts at once and B (in ERR or RESET
  // meanwhile) is brought up gap_ms (argv[4]) later. Then K new writes each way and both memories checked.
  else if (!strncmp(name, "psn_", 4)) {
    const int late = !strncmp(name, "psn_late", 8), gap = argc > 4 ? atoi(argv[4]) : 0, one = !strncmp(name, "psn_a", 5);
    uint64_t *sa = (uint64_t *)ba, *sb = (uint64_t *)bb, *da = sa + SZ / 16, *db = sb + SZ / 16;
    uint32_t pa[2], pb[2];
    int n_a = 0, n_b = 0, got = 0, up = !late;
    struct ibv_qp_attr e = {.qp_state = IBV_QPS_ERR};
    struct timespec t0;
    memset(ba, 0, SZ); memset(bb, 0, SZ);
    printf("case=%s gap_ms=%d timeout=%d retry=%d | traffic:", name, gap, tmo, retry);
    for (int i = 0; i < K; i++) put(qa, sa, ma->lkey, db, mb->rkey, n_a++);
    for (int i = 0; i < K / 2; i++) put(qb, sb, mb->lkey, da, ma->rkey, n_b++);  // fewer: the two PSN pairs differ
    poll_n(cqa, "A", K, 2000); poll_n(cqb, "B", K / 2, 2000);
    printf(" | fault:");
    if (IS("psn_a_inflight")) for (int i = 0; i < K; i++) put(qa, sa, ma->lkey, db, mb->rkey, n_a++);  // just before ERR
    if (one) CHK(!ibv_modify_qp(qa, &e, IBV_QP_STATE));
    if (IS("psn_a_inflight")) for (int i = 0; i < K; i++) put(qa, sa, ma->lkey, db, mb->rkey, n_a++);  // after: flushed
    if (!one) put(qa, sa, ma->lkey, db, 0xdeadbeef, n_a);  // not counted: skipped after the rebuild
    usleep(100000); drain(cqa, "A"); drain(cqb, "B");
    printf(" | before:"); qp_query(qb, "B");
    printf(" | rebuild:"); reset_qp(qa, "A", pa);
    if (IS("psn_both") || IS("psn_late_reset")) reset_qp(qb, "B", pb);
    if (IS("psn_a0")) pa[0] = pa[1] = 0;
    connect_qp(qa, qb->qp_num, &gid, gidx, all, 1, 1, pa[0], pa[1]);
    if (IS("psn_both")) connect_qp(qb, qa->qp_num, &gid, gidx, all, 1, 1, pb[0], pb[1]);
    const int re = IS("psn_a0") ? n_a : (int)pa[1], want = n_a - re + K;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    for (int i = re; i < n_a; i++) put(qa, sa, ma->lkey, db, mb->rkey, i);  // not acknowledged by A's record
    for (int i = 0; i < K; i++) put(qa, sa, ma->lkey, db, mb->rkey, n_a++);
    printf(" | after: A re-posted %d", want - K);
    while ((got < want || !up) && ms_since(&t0) < gap + 90000) {  // A's CQEs; B is brought up gap ms after A posted
      const int g = drain(cqa, "A");
      if (g && (got += g) == want) printf(" | A: %d/%d CQEs at %.1f ms", got, want, ms_since(&t0));
      if (!up && ms_since(&t0) >= gap) {
        printf(" | B up at %.1f ms:", ms_since(&t0));
        if (IS("psn_late_err")) reset_qp(qb, "B", pb);
        connect_qp(qb, qa->qp_num, &gid, gidx, all, 1, 1, pb[0], pb[1]);
        up = 1;
      }
      usleep(100);
    }
    if (got < want) printf(" | A: only %d/%d CQEs", got, want);
    for (int i = 0; i < K; i++) put(qb, sb, mb->lkey, da, ma->rkey, n_b++);
    poll_n(cqb, "B", K, 10000);
    check("B", db, n_a); check("A", da, n_b);
    goto report;
  }
  // sqctr*: can a rebuilt QP keep the SQ indices its WQEs already carry? A sends K writes, its context is saved, A goes
  // ERR -> RESET and back by devx from the saved context with the SQ WQE counters set to X (sqctr), set to X with a WQE
  // whose ctrl index is X+5 (sqctr_mis), or set to 0 with a WQE in slot 0 carrying index X (sqctr0). Prints the counters
  // after each step, the CQE's wqe_counter and whether the write landed.
  else if (!strncmp(name, "sqctr", 5)) {
    const uint32_t X = 0x1235, x = IS("sqctr0") ? 0 : X;
    uint64_t *sa = (uint64_t *)ba, *db = (uint64_t *)bb + SZ / 16;
    struct ibv_qp_attr e = {.qp_state = IBV_QPS_ERR}, r = {.qp_state = IBV_QPS_RESET};
    const uint16_t ops[3] = {0x502, 0x503, 0x504};  // RST2INIT, INIT2RTR, RTR2RTS
    uint8_t keep[256];
    memset(ba, 0, SZ); memset(bb, 0, SZ);
    printf("case=%s", name);
    for (int i = 0; i < K; i++) put(qa, sa, ma->lkey, db, mb->rkey, i);
    poll_n(cqa, "A", K, 2000);
    printf(" | saved:"); qp_query(qa, "A");
    memcpy(keep, qpc_saved, 256);
    CHK(!ibv_modify_qp(qa, &e, IBV_QP_STATE)); usleep(100000); drain(cqa, "A");
    CHK(!ibv_modify_qp(qa, &r, IBV_QP_STATE));
    printf(" | reset:"); qp_query(qa, "A");
    for (int i = 0; i < 3; i++) memcpy(qpc_saved, keep, 256), devx_mod(qa, ops[i], x), qp_query(qa, "A");
    struct mlx5dv_cq dc;
    struct mlx5dv_obj o = {.cq = {cqa, &dc}};
    CHK(!mlx5dv_init_obj(&o, MLX5DV_OBJ_CQ));
    const uint32_t ci = be32toh(dc.dbrec[0]) & 0xffffff;
    sa[100] = sa[101] = 0x5a5a;
    const uint32_t idx = IS("sqctr_mis") ? X + 5 : X, n = wqe_raw(qa, x, idx, sa + 100, ma->lkey, db + 100, mb->rkey);
    printf(" | posted slot=%u (of %u) idx=%#x, rang %#x", x & (n - 1), n, idx, x + 1);
    ring_raw(qa, x + 1);
    raw_cqe(cqa, ci); poll_n(cqa, "A", 1, 100);
    printf(" | B_mem=%s", db[100] == 0x5a5a ? "written" : "not written");
    goto report;
  }
  // noplap, noplap_once: can the NIC's SQ counter be brought to a given index after a reset? A is rebuilt from its record
  // (reset_qp), every SQ slot gets an unsignaled NOP (ctrl index = slot), and the doorbell names 3, then T (argv[4], laps of
  // the ring), then a write is posted in slot T with index T. Prints the NIC's counter, how long T took, and the write's CQE.
  else if (IS("noplap") || IS("noplap_once")) {
    const uint32_t T = argc > 4 ? atoi(argv[4]) : 65000;
    uint64_t *sa = (uint64_t *)ba, *db = (uint64_t *)bb + SZ / 16;
    struct ibv_qp_attr e = {.qp_state = IBV_QPS_ERR};
    uint32_t pa[2], n = 0;
    struct timespec t0;
    memset(ba, 0, SZ); memset(bb, 0, SZ);
    printf("case=%s T=%u", name, T);
    for (int i = 0; i < K; i++) put(qa, sa, ma->lkey, db, mb->rkey, i);
    poll_n(cqa, "A", K, 2000);
    CHK(!ibv_modify_qp(qa, &e, IBV_QP_STATE)); usleep(100000); drain(cqa, "A");
    printf(" | rebuild:"); reset_qp(qa, "A", pa);
    connect_qp(qa, qb->qp_num, &gid, gidx, all, 1, 1, pa[0], pa[1]);
    do wqe_raw(qa, n, n, NULL, 0, NULL, 0); while (++n < wqe_raw(qa, 0, 0, NULL, 0, NULL, 0));
    ring_raw(qa, 3); usleep(10000);
    printf(" | rang 3:"); qp_query(qa, "A"); drain(cqa, "A");
    clock_gettime(CLOCK_MONOTONIC, &t0);
    for (uint32_t c = 3; c != T;) {  // noplap: doorbells at most 2^15 - 1 ahead; noplap_once: one doorbell
      c = IS("noplap") && T - c > 32767 ? c + 32767 : T;
      ring_raw(qa, c);
      while (ms_since(&t0) < 2000 && (qpc_saved[180] << 8 | qpc_saved[181]) != (c & 0xffff)) qp_query(qa, "");
    }
    printf(" | rang %u: counter there after %.2f ms:", T, ms_since(&t0)); qp_query(qa, "A"); drain(cqa, "A");
    if (argc == 6) {  // argv[5]: one more doorbell naming T + it (mod 2^16); a value above 2^15 is behind the counter
      ring_raw(qa, T + atoi(argv[5])); usleep(50000);
      printf(" | rang T+%s:", argv[5]); qp_query(qa, "A"); drain(cqa, "A");
    }
    struct mlx5dv_cq dc;
    struct mlx5dv_obj o = {.cq = {cqa, &dc}};
    CHK(!mlx5dv_init_obj(&o, MLX5DV_OBJ_CQ));
    const uint32_t ci = be32toh(dc.dbrec[0]) & 0xffffff;
    sa[100] = sa[101] = 0x5a5a;
    wqe_raw(qa, T, T, sa + 100, ma->lkey, db + 100, mb->rkey);
    ring_raw(qa, T + 1);
    raw_cqe(cqa, ci); poll_n(cqa, "A", 1, 100);
    printf(" | B_mem=%s", db[100] == 0x5a5a ? "written" : "not written");
    goto report;
  }
  // psnmap: what the QP context says about message boundaries. Writes of 1, 4 and 3 packets (MTU 1024), each polled, then
  // a 4 MiB write (4096 packets, PSNs 8-4103) and a 16-byte one (4104), with A moved to ERR argv[4] us after posting them.
  // Prints acked/next PSN, ssn (qpc bytes 141-143) and the SQ counters after each step.
  else if (IS("psnmap")) {
    const size_t big = 4 << 20;
    const uint32_t len[5] = {16, 4096, 3000, big, 16};
    char *xa = aligned_alloc(4096, big), *xb = aligned_alloc(4096, big);
    struct ibv_mr *mxa = ibv_reg_mr(pd, xa, big, all), *mxb = ibv_reg_mr(pd, xb, big, all);
    struct ibv_qp_attr e = {.qp_state = IBV_QPS_ERR};
    CHK(mxa && mxb);
    printf("case=%s delay_us=%d", name, argc > 4 ? atoi(argv[4]) : 0);
    for (int i = 0; i < 5; i++) {
      struct ibv_sge s = {(uintptr_t)xa, len[i], mxa->lkey};
      struct ibv_send_wr w = {.wr_id = 200 + i, .sg_list = &s, .num_sge = 1, .opcode = IBV_WR_RDMA_WRITE, .send_flags = IBV_SEND_SIGNALED};
      w.wr.rdma.remote_addr = (uintptr_t)xb; w.wr.rdma.rkey = mxb->rkey;
      CHK(!ibv_post_send(qa, &w, &bad));
      if (i == 3) continue;
      if (i < 3) poll_n(cqa, "A", 1, 1000);
      else { usleep(argc > 4 ? atoi(argv[4]) : 0); CHK(!ibv_modify_qp(qa, &e, IBV_QP_STATE)); }
      printf(" | after %u B:", len[i]); qp_query(qa, "A");
      printf(" ssn=%u", qpc_saved[141] << 16 | qpc_saved[142] << 8 | qpc_saved[143]);
    }
    usleep(100000); drain(cqa, "A");
    printf(" | settled:"); qp_query(qa, "A"); printf(" ssn=%u", qpc_saved[141] << 16 | qpc_saved[142] << 8 | qpc_saved[143]);
    goto report;
  }
  else if (IS("mw_bind") || IS("mw_range") || IS("mw_len") || IS("mw_other_pd")) {
    struct ibv_mw *mw = ibv_alloc_mw(pd, IBV_MW_TYPE_1);
    if (!mw) return printf("case=%s ibv_alloc_mw failed errno=%d: did not reach the NIC\n", name, errno), 0;
    struct ibv_mw_bind b = {.wr_id = 1, .send_flags = IBV_SEND_SIGNALED, .bind_info = {mb_ro, (uintptr_t)bb, 64, IBV_ACCESS_REMOTE_WRITE}};
    if (IS("mw_range")) b.bind_info.addr += 2 * SZ;                  // outside the MR
    if (IS("mw_len")) b.bind_info.length = 2 * SZ;
    if (IS("mw_other_pd")) { struct ibv_pd *pd2 = ibv_alloc_pd(ctx); CHK(pd2 && (b.bind_info.mr = ibv_reg_mr(pd2, bb, SZ, all | IBV_ACCESS_MW_BIND))); }
    rc = ibv_bind_mw(qa, mw, &b);  // mw_bind: mb_ro has no MW_BIND access and no REMOTE_WRITE
    goto posted;
  } else return printf("unknown case %s\n", name), 1;

  if (recv) CHK(!ibv_post_recv(qb, &rwr, &rbad));
  rc = ibv_post_send(qa, &wr, &bad);
posted:
  printf("case=%s post_rc=%d", name, rc);
  int na = 0, nb = 0;
  for (int ms = 0; ms < 8000 && (!na || ms % 100); ms++) {  // until A has a CQE (8 s), then to the next 100 ms
    na += drain(cqa, "A");
    if (!IS("peer_gone")) nb += drain(cqb, "B");
    usleep(1000);
    if (second && na == 1) { second = 0; wr.wr_id = 3; wr.wr.rdma.rkey = mb->rkey; ibv_post_send(qa, &wr, &bad); }
  }
  usleep(300000);
  na += drain(cqa, "A");
  if (!IS("peer_gone")) nb += drain(cqb, "B");
  // Can the pair be used again: both QPs to RESET and back to RTS, then 8 more writes.
  if (IS("reset_reuse")) {
    struct timespec t0, t1;
    struct ibv_qp_attr r = {.qp_state = IBV_QPS_RESET};
    printf(" | before_reset:"); qp_query(qa, "A"); qp_query(qb, "B");
    clock_gettime(CLOCK_MONOTONIC, &t0);
    CHK(!ibv_modify_qp(qa, &r, IBV_QP_STATE)); CHK(!ibv_modify_qp(qb, &r, IBV_QP_STATE));
    connect_qp(qa, qb->qp_num, &gid, gidx, all, 1, 1, 0, 0); connect_qp(qb, qa->qp_num, &gid, gidx, all, 1, 1, 0, 0);
    clock_gettime(CLOCK_MONOTONIC, &t1);
    printf(" | reset_both_us=%.0f", (t1.tv_sec - t0.tv_sec) * 1e6 + (t1.tv_nsec - t0.tv_nsec) / 1e3);
    wr.wr.rdma.rkey = mb->rkey;
    for (int i = 0; i < 8; i++) { wr.wr_id = 30 + i; CHK(!ibv_post_send(qa, &wr, &bad)); }
    usleep(200000);
    printf(" | after_reset:"); na += drain(cqa, "A");
  }
  if (!na) printf(" | A: no CQE in 8 s");
  if (!nb) printf(" | B: no CQE");
report:
  printf(" | qp_query:");
  qp_query(qa, "A");
  if (!IS("peer_gone")) qp_query(qb, "B");
  struct ibv_async_event ev;
  printf(" | events:");
  while (!ibv_get_async_event(ctx, &ev)) {
    printf(" %s=%s", ev.element.qp == qa ? "A" : "B", ibv_event_type_str(ev.event_type));
    ibv_ack_async_event(&ev);
  }
  printf(" | counters:");
  counters(1);
  printf("\n");
  return 0;
}
