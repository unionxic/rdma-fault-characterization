// xnode.c: one side of an RC QP pair between two hosts (one process per host), driven by one-line commands on stdin,
// one reply line each (commands: see run()). It measures what a failed QP's own record (QUERY_QP in the error state)
// says against what the peer executed, and whether rebuilding the QP alone from that record and re-posting what did
// not complete delivers every request exactly once. A consumer overwrites each message of dst once it has landed, so a
// re-executed duplicate write puts old data back where the marker was.
// Buffer layout, the same on both hosts: src (nwr*sz, message m word w = (m+1)<<32 | w) | dst (nwr*sz) | res (nwr*8) | ctr.
// usage: xnode <device> <gid_index> <nwr> <msg_bytes> <timeout> <retry>   build: gcc -O2 -o xnode xnode.c -libverbs -lmlx5
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <infiniband/mlx5dv.h>
#include <infiniband/verbs.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define CHK(x) do { if (!(x)) { printf("fail %s (errno %d)\n", #x, errno); exit(2); } } while (0)
#define M24 0xffffffu
// ibv_wc_status -> mlx5 CQE syndrome, as mapped by the mlx5 provider (mlx5dv.h names).
static const int synd[] = {0, 0x01, 0x02, -1, 0x04, 0x05, 0x06, 0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, -1, -1, 0x22};
static struct ibv_context *ctx;
static struct ibv_qp *qp;
static struct ibv_mr *mr;
static int nwr, sz, mtu, mtu_enum, tmo, retry, rdat, gidx, top, in_reset, nok, wk[2] = {-1, -1}, wn[2], pnext, pend_n;
static char pop;  // a watch's burst still being posted: WRs pnext..pend_n-1 of op pop, one chain of 256 per step
static char wact[2], wop[2], wtxt[1024], qtxt[256], cdir[256], *cons;
static uint64_t *src, *dst, *res, *ctr, rbase;
static union ibv_gid dgid;
static uint32_t dqpn, rkey, rq0, npsn, rec[3], *psn_of;  // rec: the record read just before the last RESET
static int *st, *vend;                                     // per WR: -2 never posted, -1 posted, else its CQE status

static double us_since(const struct timespec *t0) {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return (t.tv_sec - t0->tv_sec) * 1e6 + (t.tv_nsec - t0->tv_nsec) / 1e3;
}

// QUERY_QP with qpc_ext=1 (as synd.c): fills qtxt and returns {last_acked_psn, next_send_psn, next_rcv_psn}.
static const uint32_t *qp_query(void) {
  static uint32_t p[3];
  uint8_t in[16] = {0x05, 0x0b}, out[464] = {0};
  const uint32_t w = htobe32(0x80000000u | qp->qp_num);
  memcpy(in + 8, &w, 4);
  const int rc = mlx5dv_devx_qp_query(qp, in, sizeof in, out, sizeof out);
  const uint8_t *c = out + 24;  // qpc; offsets from mlx5_ifc.h (qpc_bits)
  p[0] = c[137] << 16 | c[138] << 8 | c[139]; p[1] = c[121] << 16 | c[122] << 8 | c[123]; p[2] = c[149] << 16 | c[150] << 8 | c[151];
  if (rc) snprintf(qtxt, sizeof qtxt, " query_failed=%d/%#x", rc, out[0]);
  else snprintf(qtxt, sizeof qtxt, " st=%d synd=%#x vendor=%#x acked=%u next=%u rcv=%u", c[0] >> 4, out[287], out[286], p[0], p[1], p[2]);
  return p;
}

static void modify(enum ibv_qp_state s) {
  struct ibv_qp_attr a = {.qp_state = s};
  CHK(!ibv_modify_qp(qp, &a, IBV_QP_STATE));
}

// Reads the QP's record into rec and moves it to RESET.
static void reset_qp(void) {
  memcpy(rec, qp_query(), sizeof rec);
  modify(IBV_QPS_RESET);
  in_reset = 1;
}

// RESET -> INIT -> RTR -> RTS with the given PSNs; NCCL GIN's settings apart from timeout and retry (argv).
static void connect_qp(uint32_t rq, uint32_t sq) {
  struct ibv_qp_attr a = {.qp_state = IBV_QPS_INIT, .port_num = 1,
                          .qp_access_flags = IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE | IBV_ACCESS_REMOTE_READ | IBV_ACCESS_REMOTE_ATOMIC};
  CHK(!ibv_modify_qp(qp, &a, IBV_QP_STATE | IBV_QP_PKEY_INDEX | IBV_QP_PORT | IBV_QP_ACCESS_FLAGS));
  memset(&a, 0, sizeof a);
  a.qp_state = IBV_QPS_RTR; a.path_mtu = mtu_enum; a.dest_qp_num = dqpn; a.max_dest_rd_atomic = rdat; a.min_rnr_timer = 12; a.rq_psn = rq;
  a.ah_attr.is_global = 1; a.ah_attr.port_num = 1; a.ah_attr.grh.dgid = dgid; a.ah_attr.grh.sgid_index = gidx; a.ah_attr.grh.hop_limit = 64;
  CHK(!ibv_modify_qp(qp, &a, IBV_QP_STATE | IBV_QP_AV | IBV_QP_PATH_MTU | IBV_QP_DEST_QPN | IBV_QP_RQ_PSN | IBV_QP_MAX_DEST_RD_ATOMIC | IBV_QP_MIN_RNR_TIMER));
  memset(&a, 0, sizeof a);
  a.qp_state = IBV_QPS_RTS; a.timeout = tmo; a.retry_cnt = retry; a.rnr_retry = 7; a.max_rd_atomic = rdat; a.sq_psn = sq;
  CHK(!ibv_modify_qp(qp, &a, IBV_QP_STATE | IBV_QP_TIMEOUT | IBV_QP_RETRY_CNT | IBV_QP_RNR_RETRY | IBV_QP_SQ_PSN | IBV_QP_MAX_QP_RD_ATOMIC));
  npsn = sq; in_reset = 0;
}

// WR j of op o: 'w' write of message j, 'b' the same with a bad rkey, 'r' read of the peer's src message j into dst,
// 'a' fetch-add 1 on the peer's ctr into res[j], 'x' write of message j/2 (even j) and fetch-add into res[j/2] (odd j), as a
// put followed by its signal. Posted in chains of 256 so that the NIC starts on the first while the rest is written.
static void post(char o, int first, int n) {
  struct ibv_sge *s = calloc(n, sizeof *s);
  struct ibv_send_wr *w = calloc(n, sizeof *w), *bad;
  for (int i = 0; i < n; i++) {
    const int j = first + i, at = o == 'a' || (o == 'x' && j % 2), m = o == 'x' ? j / 2 : j;
    s[i] = at ? (struct ibv_sge){(uintptr_t)(res + m), 8, mr->lkey} : (struct ibv_sge){(uintptr_t)src + (size_t)m * sz, sz, mr->lkey};
    w[i] = (struct ibv_send_wr){.wr_id = j, .next = (i + 1) % 256 && i + 1 < n ? w + i + 1 : NULL, .sg_list = s + i, .num_sge = 1, .send_flags = IBV_SEND_SIGNALED};
    if (at) {
      w[i].opcode = IBV_WR_ATOMIC_FETCH_AND_ADD; w[i].wr.atomic.compare_add = 1; res[m] = ~0ull;
      w[i].wr.atomic.remote_addr = rbase + 2 * (size_t)nwr * sz + nwr * 8; w[i].wr.atomic.rkey = rkey;
    } else if (o == 'r') {
      w[i].opcode = IBV_WR_RDMA_READ; s[i].addr = (uintptr_t)dst + (size_t)m * sz;
      w[i].wr.rdma.remote_addr = rbase + (size_t)m * sz; w[i].wr.rdma.rkey = rkey;
    } else {
      w[i].opcode = IBV_WR_RDMA_WRITE;
      w[i].wr.rdma.remote_addr = rbase + (size_t)(nwr + m) * sz; w[i].wr.rdma.rkey = o == 'b' ? 0xdeadbeef : rkey;
    }
    psn_of[j] = npsn; npsn = (npsn + (at ? 1 : (sz + mtu - 1) / mtu)) & M24; st[j] = -1;
  }
  for (int i = 0; i < n; i += 256) CHK(!ibv_post_send(qp, w + i, &bad));
  if (first + n > top) top = first + n;
  free(s); free(w);
}

static int landed(int m) { return dst[(size_t)(m + 1) * sz / 8 - 1] != 0; }  // last word written (data or marker)

// Consumer: in order, a message whose last word holds data is checked word by word and overwritten with the marker ~0.
// One message per call, so that an armed watch is checked between messages.
static int cnext, ncorrupt, cm = -1, cw;
static uint64_t cv;
static void consume(void) {
  const int nw = sz / 8;
  if (cnext < nwr && landed(cnext) && dst[(size_t)(cnext + 1) * nw - 1] != ~0ull) {
    uint64_t *d = dst + (size_t)cnext * nw;
    for (int w = 0; w < nw; w++)
      if (d[w] != ((uint64_t)(cnext + 1) << 32 | w)) {
        if (!d[w]) return;  // not all there yet (a packet not yet placed)
        if (!ncorrupt++) cm = cnext, cw = w, cv = d[w];
        break;
      }
    memset(d, 0xff, sz);
    cons[cnext++] = 1;
  }
}

static int poll_cq(void) {
  struct ibv_wc wc[64];
  const int n = ibv_poll_cq(qp->send_cq, 64, wc);
  for (int i = 0; i < n; i++) st[wc[i].wr_id] = wc[i].status, vend[wc[i].wr_id] = wc[i].vendor_err, nok += !wc[i].status;
  return n;
}

// Watch i fired (message wk[i] landed or ctr reached it): 'p' post WRs 0..wn-1 of op wop (from step(), a chain of 256 at a
// time, so that the other watch is still checked while they go out); 'e' this QP to ERR; 'r' read the
// record and RESET; 'b' ERR, collect the flush CQEs, then rebuild alone from the record at once (rq = rcv, sq = acked+1).
// Its text, keys prefixed by the action, goes into the q reply.
static void fire(int i) {
  struct timespec t0;
  const char a = wact[i];
  const int k = wk[i];
  wk[i] = -1;
  clock_gettime(CLOCK_MONOTONIC, &t0);
  if (a != 'p' && pend_n > pnext) pend_n = pnext;  // the rest of a burst is not posted to a failed QP; resend covers it
  if (a == 'p') pop = wop[i], pnext = 0, pend_n = wn[i];
  else if (a == 'r') reset_qp();
  else modify(IBV_QPS_ERR), memcpy(rec, qp_query(), sizeof rec);
  const double us = us_since(&t0);
  int m = 0, l = strlen(wtxt);
  while (m < nwr && landed(m)) m++;
  l += snprintf(wtxt + l, sizeof wtxt - l, " %c_fired=%d %c_us=%.0f %c_landed=%d %c_ctr=%llu", a, k, a, us, a, m, a, (unsigned long long)*ctr);
  if (a != 'p') l += snprintf(wtxt + l, sizeof wtxt - l, " %c_acked=%u %c_next=%u %c_rcv=%u", a, rec[0], a, rec[1], a, rec[2]);
  if (a == 'r') {
    const uint32_t *p = qp_query();  // what a RESET QP still reports
    snprintf(wtxt + l, sizeof wtxt - l, " r_reset_acked=%u r_reset_next=%u r_reset_rcv=%u", p[0], p[1], p[2]);
  } else if (a == 'b') {
    int pend = 1;
    while (pend && us_since(&t0) < 200000) { poll_cq(); for (pend = 0, m = 0; m < top; m++) pend += st[m] == -1; }
    reset_qp();
    connect_qp(rec[2], (rec[0] + 1) & M24);
    snprintf(wtxt + l, sizeof wtxt - l, " b_rq=%u b_sq=%u b_rebuilt_us=%.0f b_pend=%d", rec[2], (rec[0] + 1) & M24, us_since(&t0), pend);
  }
}

static void step(void) {
  poll_cq();
  if (pnext < pend_n) post(pop, pnext, pend_n - pnext < 256 ? pend_n - pnext : 256), pnext += 256;
  for (int i = 0; i < 2; i++) if (wk[i] >= 0 && (landed(wk[i]) || *ctr >= (uint64_t)wk[i])) fire(i);
  consume();
}

// Port hw_counters: the first call takes a snapshot, later calls print what moved since (as synd.c).
#define NCNT 64
static char cname[NCNT][64];
static long long cval[NCNT];
static int ncnt;
static void counters(void) {
  DIR *d = opendir(cdir);
  struct dirent *e;
  const int after = ncnt > 0;
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
      if (!strcmp(cname[i], e->d_name) && v != cval[i]) printf(" %s=%lld", cname[i], v - cval[i]);
  }
  if (d) closedir(d);
}

// The receiver's view of the peer's n WRs of op o: messages consumed in order (msgs), placed packets of the next one
// (part), ctr, the PSN that follows what was executed (exec, valid while executions are a prefix and before re-posts),
// consumed messages holding data again (reexec), unconsumed messages past the prefix holding data (beyond).
static void mem(char o, int n) {
  const int nm = o == 'a' ? 0 : o == 'x' ? (n + 1) / 2 : n, nw = sz / 8, pw = mtu / 8, npk = (sz + mtu - 1) / mtu;
  struct timespec t0;
  clock_gettime(CLOCK_MONOTONIC, &t0);
  while (us_since(&t0) < 2000) step();  // let the consumer catch up
  int msgs = 0, part = 0, reexec = 0, beyond = 0, rm = -1;
  while (msgs < nm && cons[msgs]) msgs++;
  for (const uint64_t *d = dst + (size_t)msgs * nw; msgs < nm && part < npk; part++) {
    const int lw = part + 1 < npk ? (part + 1) * pw - 1 : nw - 1;  // last word of packet `part`
    if (d[lw] != ((uint64_t)(msgs + 1) << 32 | lw)) break;
  }
  for (int m = 0; m < nm; m++)
    for (int w = 0; w < nw; w++) {
      const uint64_t v = dst[(size_t)m * nw + w];
      if (cons[m] ? v != ~0ull : m > msgs && v) { if (cons[m] && !reexec++) rm = m; if (!cons[m]) beyond++; break; }
    }
  const uint32_t e = (uint32_t)((uint64_t)msgs * (o == 'a' ? 0 : npk) + part + *ctr);
  printf("mem msgs=%d part=%d ctr=%llu exec=%u reexec=%d reexec_first=%d beyond=%d corrupt=%d corrupt_at=%d/%d/%#llx", msgs, part,
         (unsigned long long)*ctr, (rq0 + e) & M24, reexec, rm, beyond, ncorrupt, cm, cw, (unsigned long long)cv);
}

// The returned old values of the fetch-adds among the first n WRs of op o: res[m] must be m (ctr starts at 0, adds 1).
static void res_check(char o, int n) {
  const int na = o == 'a' ? n : o == 'x' ? n / 2 : 0;
  int mis = 0, m0 = -1;
  for (int m = 0; m < na; m++) if (res[m] != (uint64_t)m && !mis++) m0 = m;
  printf("res n=%d mismatch=%d first=%d val=%lld", na, mis, m0, m0 < 0 ? 0 : (long long)res[m0]);
}

static int first_bad(void) {
  int f = 0;
  while (f < top && st[f] == 0) f++;
  return f;
}

static void run(char *l) {
  char o = 0, a[40] = "", b[40] = "";
  int x = 0, y = 0, k = 0;
  uint32_t rq, sq;
  if (sscanf(l, "conn %x %32s %lx %x %u %u", &dqpn, a, &rbase, &rkey, &rq, &sq) == 6) {
    for (int i = 0; i < 16; i++) sscanf(a + 2 * i, "%2hhx", &dgid.raw[i]);
    rq0 = rq;
    connect_qp(rq, sq);
    printf("conn rq=%u sq=%u", rq, sq);
  } else if (sscanf(l, "post %c %d %d %d", &o, &x, &y, &k) >= 3) {  // k > 0: then ERR once k WRs completed successfully
    struct timespec t0;
    const int n0 = nok;
    post(o, x, y);
    clock_gettime(CLOCK_MONOTONIC, &t0);
    if (k > 0) {
      while (nok - n0 < k && us_since(&t0) < 5e6) step();
      const int at = nok - n0;
      modify(IBV_QPS_ERR);
      const uint32_t *p = qp_query();  // the record right at the transition
      printf("post o=%c first=%d n=%d err_at_ok=%d err_us=%.0f rec0_acked=%u rec0_next=%u rec0_rcv=%u", o, x, y, at, us_since(&t0), p[0], p[1], p[2]);
    } else printf("post o=%c first=%d n=%d", o, x, y);
  } else if (sscanf(l, "wait %d %d", &x, &y) == 2) {  // until WRs 0..x-1 all have a CQE, or y ms
    struct timespec t0;
    int ok = 0, fl = 0, pend, e = -1, np = 0;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    do { step(); for (pend = 0, k = 0; k < x; k++) pend += st[k] == -1; } while (pend && us_since(&t0) < y * 1e3);
    for (k = 0; k < x; k++) { ok += !st[k]; np += st[k] == -2; fl += st[k] == IBV_WC_WR_FLUSH_ERR; if (e < 0 && st[k] > 0 && st[k] != IBV_WC_WR_FLUSH_ERR) e = k; }
    const int f = first_bad();
    printf("wait ok=%d flush=%d pend=%d unposted=%d other=%d f=%d fpsn=%u t_ms=%.1f", ok, fl, pend, np, x - ok - fl - pend - np, f, f < top ? psn_of[f] : npsn, us_since(&t0) / 1e3);
    if (e >= 0) printf(" err_wr=%d err=%d err_synd=%#x err_vendor=%#x", e, st[e], st[e] < 17 ? synd[st[e]] : -1, vend[e]);
  } else if (!strcmp(l, "q")) {
    qp_query();
    printf("q%s armed=%d%s events=", qtxt, (wk[0] >= 0) + (wk[1] >= 0), wtxt);
    struct ibv_async_event ev;
    while (!ibv_get_async_event(ctx, &ev)) printf("%d,", ev.event_type), ibv_ack_async_event(&ev);
  } else if (!strcmp(l, "err")) {
    modify(IBV_QPS_ERR);
    printf("err");
  } else if (sscanf(l, "rebuild %39s %39s", a, b) == 2) {  // sq rule: own (acked+1) | msg (first PSN of the first incomplete WR) | init | number; rq: own | init | number
    if (!in_reset) reset_qp();
    const int f = first_bad();
    sq = !strcmp(a, "own") ? (rec[0] + 1) & M24 : !strcmp(a, "msg") ? (f < top ? psn_of[f] : npsn) : !strcmp(a, "init") ? rq0 : (uint32_t)atol(a);
    rq = !strcmp(b, "own") ? rec[2] : !strcmp(b, "init") ? rq0 : (uint32_t)atol(b);
    connect_qp(rq, sq);
    printf("rebuild rec_acked=%u rec_next=%u rec_rcv=%u sq=%u rq=%u", rec[0], rec[1], rec[2], sq, rq);
  } else if (sscanf(l, "resend %c %d", &o, &x) == 2) {  // re-post, in the original order, WRs from the first not known complete
    const int f = first_bad();
    if (f < x) post(o, f, x - f);
    printf("resend from=%d n=%d", f, x - f);
  } else if (sscanf(l, "watch %d %c %c %d", &x, &o, b, &y) >= 2) {  // watch <k> <e|r|b> or watch <k> p <op> <n>
    const int i = wk[0] >= 0;
    CHK(wk[i] < 0);
    wk[i] = x; wact[i] = o; wop[i] = *b; wn[i] = y;
    printf("watch k=%d act=%c", x, o);
  } else if (sscanf(l, "mem %c %d", &o, &x) == 2) mem(o, x);
  else if (sscanf(l, "res %c %d", &o, &x) == 2) res_check(o, x);
  else if (!strcmp(l, "cnt")) { printf("cnt"); counters(); }
  else if (!strcmp(l, "quit")) exit(0);
  else printf("unknown command: %s", l);
  printf("\n");
}

int main(int argc, char **argv) {
  if (argc < 7) return fprintf(stderr, "usage: xnode <device> <gid_index> <nwr> <msg_bytes> <timeout> <retry>\n"), 1;
  gidx = atoi(argv[2]); nwr = atoi(argv[3]); sz = atoi(argv[4]); tmo = atoi(argv[5]); retry = atoi(argv[6]);
  setvbuf(stdout, NULL, _IOLBF, 0);
  alarm(900);  // never outlive a lost driver
  struct ibv_device **list = ibv_get_device_list(NULL), *dev = NULL;
  for (int i = 0; list && list[i]; i++) if (!strcmp(ibv_get_device_name(list[i]), argv[1])) dev = list[i];
  CHK(dev && sz >= 8 && sz % 8 == 0 && nwr > 0);
  struct mlx5dv_context_attr dva = {.flags = MLX5DV_CONTEXT_FLAGS_DEVX};  // devx is needed for QUERY_QP
  CHK(ctx = mlx5dv_open_device(dev, &dva));
  snprintf(cdir, sizeof cdir, "/sys/class/infiniband/%s/ports/1/hw_counters", argv[1]);
  fcntl(ctx->async_fd, F_SETFL, fcntl(ctx->async_fd, F_GETFL) | O_NONBLOCK);
  struct ibv_device_attr da;
  struct ibv_port_attr pa;
  CHK(!ibv_query_device(ctx, &da) && !ibv_query_port(ctx, 1, &pa));
  rdat = da.max_qp_rd_atom; mtu_enum = pa.active_mtu; mtu = 128 << pa.active_mtu;
  struct ibv_pd *pd = ibv_alloc_pd(ctx);
  struct ibv_cq *cq = ibv_create_cq(ctx, 2 * nwr + 64, NULL, NULL, 0);
  CHK(pd && cq);
  struct ibv_qp_init_attr ia = {.send_cq = cq, .recv_cq = cq, .qp_type = IBV_QPT_RC, .cap = {nwr, 1, 1, 1, 0}};
  CHK(qp = ibv_create_qp(pd, &ia));
  const size_t len = ((2 * (size_t)nwr * sz + nwr * 8 + 8) + 4095) & ~4095ul;
  CHK(src = aligned_alloc(4096, len));
  memset(src, 0, len);
  dst = src + (size_t)nwr * sz / 8; res = dst + (size_t)nwr * sz / 8; ctr = res + nwr;
  for (size_t m = 0; m < (size_t)nwr; m++) for (int w = 0; w < sz / 8; w++) src[m * sz / 8 + w] = (m + 1) << 32 | w;
  CHK(mr = ibv_reg_mr(pd, src, len, IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE | IBV_ACCESS_REMOTE_READ | IBV_ACCESS_REMOTE_ATOMIC));
  CHK((psn_of = calloc(nwr, 4)) && (st = calloc(nwr, sizeof *st)) && (vend = calloc(nwr, sizeof *vend)) && (cons = calloc(nwr, 1)));
  for (int i = 0; i < nwr; i++) st[i] = -2;
  union ibv_gid gid;
  CHK(!ibv_query_gid(ctx, 1, gidx, &gid));
  printf("info qpn=%#x gid=", qp->qp_num);
  for (int i = 0; i < 16; i++) printf("%02x", gid.raw[i]);
  printf(" base=%#lx rkey=%#x mtu=%d rd_atomic=%d timeout=%d retry=%d\n", (unsigned long)(uintptr_t)src, mr->rkey, mtu, rdat, tmo, retry);
  char line[1024];
  int n = 0;
  struct pollfd pf = {0, POLLIN, 0};
  for (;;) {
    step();
    if (poll(&pf, 1, 0) <= 0) continue;
    const ssize_t r = read(0, line + n, sizeof line - 1 - n);
    if (r <= 0) return 0;
    line[n += r] = 0;
    for (char *nl; (nl = strchr(line, '\n'));) {
      *nl = 0;
      run(line);
      memmove(line, nl + 1, n -= nl + 1 - line);
      line[n] = 0;
    }
  }
}
