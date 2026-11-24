// synd.c: injects one fault on a loopback RC QP pair (A requests, B responds, same port, one process) and
// prints what the NIC reports: CQEs on both sides, the error syndrome the NIC keeps in each QP context
// (QUERY_QP with qpc_ext, the value the kernel prints as "QP N error: ..."), async events, port hw_counters that moved.
// usage: synd <device> <gid_index> <case>      build: gcc -O2 -o synd synd.c -libverbs -lmlx5
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
static const char *name;
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

static void connect_qp(struct ibv_qp *q, uint32_t dqpn, union ibv_gid *gid, int gidx, int access, int rd, int drd) {
  struct ibv_qp_attr a = {.qp_state = IBV_QPS_INIT, .port_num = 1, .qp_access_flags = access};
  CHK(!ibv_modify_qp(q, &a, IBV_QP_STATE | IBV_QP_PKEY_INDEX | IBV_QP_PORT | IBV_QP_ACCESS_FLAGS));
  memset(&a, 0, sizeof a);
  a.qp_state = IBV_QPS_RTR; a.path_mtu = IBV_MTU_1024; a.dest_qp_num = dqpn; a.max_dest_rd_atomic = drd; a.min_rnr_timer = 12;
  a.ah_attr.is_global = 1; a.ah_attr.port_num = 1; a.ah_attr.grh.dgid = *gid; a.ah_attr.grh.sgid_index = gidx; a.ah_attr.grh.hop_limit = 1;
  CHK(!ibv_modify_qp(q, &a, IBV_QP_STATE | IBV_QP_AV | IBV_QP_PATH_MTU | IBV_QP_DEST_QPN | IBV_QP_RQ_PSN | IBV_QP_MAX_DEST_RD_ATOMIC | IBV_QP_MIN_RNR_TIMER));
  memset(&a, 0, sizeof a);
  a.qp_state = IBV_QPS_RTS; a.timeout = 14; a.retry_cnt = 2; a.rnr_retry = 2; a.max_rd_atomic = rd;
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

// QUERY_QP with qpc_ext=1: the QP context extension holds one error record (layout: mlx5_ifc.h,
// qp_context_extension.error_syndrome, at byte 284 of the output).
static void qp_query(struct ibv_qp *q, const char *side) {
  uint8_t in[16] = {0x05, 0x0b}, out[464] = {0};
  const uint32_t w = htobe32(0x80000000u | q->qp_num);
  memcpy(in + 8, &w, 4);
  const int rc = mlx5dv_devx_qp_query(q, in, sizeof in, out, sizeof out);
  if (rc) printf(" %s=query failed rc=%d cmd_status=%#x", side, rc, out[0]);
  else {
    // qpc starts at byte 24 of the output; offsets inside it from mlx5_ifc.h (qpc_bits)
    const uint8_t *c = out + 24;
    printf(" %s=syndrome=%#x vendor_err=%#x hw_type=%#x hw_err=%#x sq_hw=%u sq_sw=%u acked_psn=%u next_psn=%u rcv_psn=%u", side,
           out[287], out[286], out[285] >> 4, out[284], c[180] << 8 | c[181], c[182] << 8 | c[183],
           c[137] << 16 | c[138] << 8 | c[139], c[121] << 16 | c[122] << 8 | c[123], c[149] << 16 | c[150] << 8 | c[151]);
  }
}

int main(int argc, char **argv) {
  if (argc < 4) return fprintf(stderr, "usage: synd <device> <gid_index> <case>\n"), 1;
  const int gidx = atoi(argv[2]);
  name = argv[3];
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
  connect_qp(qa, qb->qp_num, &gid, gidx, all, IS("read_req0") ? 0 : 1, 1);
  connect_qp(qb, qa->qp_num, &gid, gidx, IS("qp_no_write") ? IBV_ACCESS_REMOTE_READ : all, 1, IS("read_resp0") ? 0 : 1);

  char *ba = aligned_alloc(4096, SZ), *bb = aligned_alloc(4096, SZ);
  struct ibv_mr *ma = ibv_reg_mr(pd, ba, SZ, IBV_ACCESS_LOCAL_WRITE);
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
    connect_qp(qa, qb->qp_num, &gid, gidx, all, 1, 1); connect_qp(qb, qa->qp_num, &gid, gidx, all, 1, 1);
    clock_gettime(CLOCK_MONOTONIC, &t1);
    printf(" | reset_both_us=%.0f", (t1.tv_sec - t0.tv_sec) * 1e6 + (t1.tv_nsec - t0.tv_nsec) / 1e3);
    wr.wr.rdma.rkey = mb->rkey;
    for (int i = 0; i < 8; i++) { wr.wr_id = 30 + i; CHK(!ibv_post_send(qa, &wr, &bad)); }
    usleep(200000);
    printf(" | after_reset:"); na += drain(cqa, "A");
  }
  if (!na) printf(" | A: no CQE in 8 s");
  if (!nb) printf(" | B: no CQE");
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
