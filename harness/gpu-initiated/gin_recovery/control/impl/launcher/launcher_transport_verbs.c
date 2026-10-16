/* launcher_transport_verbs.c - the launcher's RNIC transport over libibverbs (gin-control, EXPERIMENT.md 9.1, 9.5).
 *
 * One PD, one CQ with a completion channel (the launcher's single thread polls its fd), one UD QP with the launcher's
 * own Q_Key, one RC QP per paired rank (design v2 2.1: the launcher QP is "like the record QP": timeout 14, retry 7,
 * rnr_retry 3, REMOTE_READ only), one REMOTE_READ MR for the state page. Every SEND and datagram carries the 64 B
 * control envelope (launcher_msg.h glCtrlEnv) before the 256 B launcher message.
 *
 * Credit (design v2 2.2): the launcher posts GL_V_RQ RECVs per RC QP and reposts each at once; it sends to a rank only
 * while seq - ackSeq < GL_V_RQ, where ackSeq is the count the rank put into its last envelope. Past that it queues
 * (bounded) and logs. It sends no credit-only message.
 *
 * Built only when <infiniband/verbs.h> exists; never executed by this folder's build script (no device is opened
 * there). The unit test uses the in-process transport of launcher_unit.cc instead.
 */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <infiniband/verbs.h>

#include "launcher_transport.h"

#define GL_V_PEERS 256
#define GL_V_RQ 64          /* RC RECVs per QP (= the rank's credit window toward the launcher) */
#define GL_V_SQ 96          /* RC send slots per QP */
#define GL_V_READS 4        /* concurrent READs per QP */
#define GL_V_PENDQ 4096     /* queued sends per QP past the credit window */
#define GL_V_UD_RQ 64
#define GL_V_UD_SQ 64
#define GL_V_GRH 40
#define GL_V_EVQ 512
#define GL_V_CQ 1024
#define GL_V_TIMEOUT 14
#define GL_V_RETRY 7
#define GL_V_RNR_RETRY 3

enum { WR_UD_RECV = 1, WR_UD_SEND = 2, WR_RC_RECV = 3, WR_RC_SEND = 4, WR_RC_READ = 5, WR_RC_CREDIT = 6 };
static uint64_t wr_id(int type, int peer, int slot) {
  return ((uint64_t)type << 56) | ((uint64_t)(uint32_t)peer << 24) | (uint64_t)(uint32_t)slot;
}
static int wr_type(uint64_t id) { return (int)(id >> 56); }
static int wr_peer(uint64_t id) { return (int)((id >> 24) & 0xffffffffu); }
static int wr_slot(uint64_t id) { return (int)(id & 0xffffffu); }

struct glVRead {
  int used;
  struct ibv_mr* mr;
  uint64_t cookie;
};

struct glVPeer {
  int used, broken;
  int kind;             /* GL_PAIR_RECORD or GL_PAIR_PROBE */
  int connected;
  struct ibv_qp* qp;
  uint32_t localPsn;
  uint32_t gen;
  uint64_t nonce;
  uint64_t seqOut;      /* messages posted */
  uint64_t ackIn;       /* the rank's consumed count of ours (its envelopes' ackSeq) */
  uint64_t consumed;    /* how many of the rank's this side took (our envelopes' ackSeq) */
  uint64_t seqIn;       /* the last seq received (gen-local order check) */
  uint8_t* sbuf;        /* GL_V_SQ x GL_WIRE_BYTES */
  uint8_t* rbuf;        /* GL_V_RQ x GL_WIRE_BYTES */
  struct ibv_mr *smr, *rmr;
  int sNext, sInflight;
  struct glMsg* pend;   /* past the window */
  int pHead, pCount;
  struct glVRead rd[GL_V_READS];
  struct glRegion creditPage; /* the rank's page and the offset of its consumed count of our messages */
  uint32_t creditOff;
  uint64_t* creditWord;       /* READ target (8 B) */
  struct ibv_mr* creditMr;
  int creditReading;
};

struct glVerbs {
  struct ibv_context* ctx;
  struct ibv_pd* pd;
  struct ibv_comp_channel* ch;
  struct ibv_cq* cq;
  struct ibv_qp* ud;
  int port, gidIndex;
  union ibv_gid gid;
  struct ibv_port_attr pa;
  uint32_t qkey, node, udPsn;
  uint8_t *udRbuf, *udSbuf;
  struct ibv_mr *udRmr, *udSmr;
  struct ibv_ah* udAh[GL_V_UD_SQ];
  int udNext;
  struct ibv_mr* pageMr;
  struct glVPeer peer[GL_V_PEERS];
  struct glTpEvent ev[GL_V_EVQ];
  int evHead, evCount;
};

static void gl_v_push(struct glVerbs* v, const struct glTpEvent* e) {
  if (v->evCount == GL_V_EVQ) {
    fprintf(stderr, "GIN/LA: verbs transport: event queue full, one event dropped\n");
    return;
  }
  v->ev[(v->evHead + v->evCount) % GL_V_EVQ] = *e;
  v->evCount++;
}
static void gl_v_error(struct glVerbs* v, int peer, int status) {
  if (peer < 0 || peer >= GL_V_PEERS || !v->peer[peer].used || v->peer[peer].broken) return;
  v->peer[peer].broken = 1;
  struct glTpEvent e;
  memset(&e, 0, sizeof(e));
  e.type = GL_TP_RC_ERROR;
  e.peer = peer;
  e.status = status;
  gl_v_push(v, &e);
}

static int gl_v_post_ud_recv(struct glVerbs* v, int slot) {
  struct ibv_sge sg;
  sg.addr = (uintptr_t)(v->udRbuf + (size_t)slot * (GL_V_GRH + GL_WIRE_BYTES));
  sg.length = GL_V_GRH + GL_WIRE_BYTES;
  sg.lkey = v->udRmr->lkey;
  struct ibv_recv_wr wr, *bad = NULL;
  memset(&wr, 0, sizeof(wr));
  wr.wr_id = wr_id(WR_UD_RECV, 0, slot);
  wr.sg_list = &sg;
  wr.num_sge = 1;
  return ibv_post_recv(v->ud, &wr, &bad);
}
static int gl_v_post_rc_recv(struct glVerbs* v, int peer, int slot) {
  struct glVPeer* p = &v->peer[peer];
  struct ibv_sge sg;
  sg.addr = (uintptr_t)(p->rbuf + (size_t)slot * GL_WIRE_BYTES);
  sg.length = GL_WIRE_BYTES;
  sg.lkey = p->rmr->lkey;
  struct ibv_recv_wr wr, *bad = NULL;
  memset(&wr, 0, sizeof(wr));
  wr.wr_id = wr_id(WR_RC_RECV, peer, slot);
  wr.sg_list = &sg;
  wr.num_sge = 1;
  return ibv_post_recv(p->qp, &wr, &bad);
}

static void gl_v_ah_attr(struct glVerbs* v, const struct glEp* to, struct ibv_ah_attr* ah) {
  memset(ah, 0, sizeof(*ah));
  ah->is_global = 1;
  memcpy(ah->grh.dgid.raw, to->gid, 16);
  ah->grh.sgid_index = (uint8_t)v->gidIndex;
  ah->grh.hop_limit = 64;
  ah->dlid = (uint16_t)to->lid;
  ah->port_num = (uint8_t)v->port;
}

/* ------------------------------------------------------------------------------------------------- ops */

static int gl_v_fds(struct glTransport* tp, int* fds, int max) {
  struct glVerbs* v = (struct glVerbs*)tp->impl;
  int n = 0;
  if (n < max) fds[n++] = v->ch->fd;
  if (n < max) fds[n++] = v->ctx->async_fd;
  return n;
}

static int gl_v_post_send(struct glVerbs* v, int peer, const struct glMsg* m) {
  struct glVPeer* p = &v->peer[peer];
  const int slot = p->sNext;
  p->sNext = (p->sNext + 1) % GL_V_SQ;
  uint8_t* buf = p->sbuf + (size_t)slot * GL_WIRE_BYTES;
  struct glCtrlEnv e;
  gl_env_pack(&e, GL_ENV_KIND_LAUNCHER, (int32_t)(GL_FROM_LAUNCHER | (int32_t)v->node), p->gen, p->seqOut + 1,
              p->consumed, p->nonce, 0);
  memcpy(buf, &e, sizeof(e));
  memcpy(buf + sizeof(e), m, sizeof(*m));
  struct ibv_sge sg;
  sg.addr = (uintptr_t)buf;
  sg.length = GL_WIRE_BYTES;
  sg.lkey = p->smr->lkey;
  struct ibv_send_wr wr, *bad = NULL;
  memset(&wr, 0, sizeof(wr));
  wr.wr_id = wr_id(WR_RC_SEND, peer, slot);
  wr.sg_list = &sg;
  wr.num_sge = 1;
  wr.opcode = IBV_WR_SEND;
  wr.send_flags = IBV_SEND_SIGNALED;
  if (ibv_post_send(p->qp, &wr, &bad) != 0) return -1;
  p->seqOut++;
  p->sInflight++;
  return 0;
}
/* The send window is shut: READ the rank's consumed-count word once (design v2 2.2 path 3), no credit-only SEND. */
static void gl_v_credit_read(struct glVerbs* v, int peer) {
  struct glVPeer* p = &v->peer[peer];
  if (p->creditReading || !p->creditMr || p->creditPage.rkey == 0 || p->sInflight >= GL_V_SQ) return;
  struct ibv_sge sg;
  sg.addr = (uintptr_t)p->creditWord;
  sg.length = 8;
  sg.lkey = p->creditMr->lkey;
  struct ibv_send_wr wr, *bad = NULL;
  memset(&wr, 0, sizeof(wr));
  wr.wr_id = wr_id(WR_RC_CREDIT, peer, 0);
  wr.sg_list = &sg;
  wr.num_sge = 1;
  wr.opcode = IBV_WR_RDMA_READ;
  wr.send_flags = IBV_SEND_SIGNALED;
  wr.wr.rdma.remote_addr = p->creditPage.addr + p->creditOff;
  wr.wr.rdma.rkey = p->creditPage.rkey;
  if (ibv_post_send(p->qp, &wr, &bad) == 0) {
    p->creditReading = 1;
    p->sInflight++;
  }
}
static void gl_v_flush(struct glVerbs* v, int peer) {
  struct glVPeer* p = &v->peer[peer];
  while (p->pCount > 0 && !p->broken && p->seqOut - p->ackIn < GL_V_RQ && p->sInflight < GL_V_SQ - GL_V_READS) {
    if (gl_v_post_send(v, peer, &p->pend[p->pHead]) != 0) {
      gl_v_error(v, peer, -1);
      return;
    }
    p->pHead = (p->pHead + 1) % GL_V_PENDQ;
    p->pCount--;
  }
}

static void gl_v_on_wc(struct glVerbs* v, const struct ibv_wc* wc) {
  const int type = wr_type(wc->wr_id), peer = wr_peer(wc->wr_id), slot = wr_slot(wc->wr_id);
  struct glTpEvent e;
  memset(&e, 0, sizeof(e));
  e.peer = -1;
  switch (type) {
    case WR_UD_RECV: {
      if (wc->status == IBV_WC_SUCCESS && wc->byte_len >= GL_V_GRH + GL_WIRE_BYTES) {
        const uint8_t* b = v->udRbuf + (size_t)slot * (GL_V_GRH + GL_WIRE_BYTES) + GL_V_GRH;
        struct glCtrlEnv env;
        memcpy(&env, b, sizeof(env));
        if (gl_env_check(&env, GL_ENV_KIND_PAIR) == GL_R_NONE) {
          e.type = GL_TP_UD_RECV;
          memcpy(&e.msg, b + sizeof(env), sizeof(e.msg));
          gl_v_push(v, &e);
        }
      }
      if (wc->status != IBV_WC_WR_FLUSH_ERR) gl_v_post_ud_recv(v, slot);
      return;
    }
    case WR_UD_SEND:
      if (v->udAh[slot]) {
        ibv_destroy_ah(v->udAh[slot]);
        v->udAh[slot] = NULL;
      }
      return;
    case WR_RC_RECV: {
      if (peer < 0 || peer >= GL_V_PEERS || !v->peer[peer].used) return;
      struct glVPeer* p = &v->peer[peer];
      if (wc->status != IBV_WC_SUCCESS) {
        if (wc->status != IBV_WC_WR_FLUSH_ERR) gl_v_error(v, peer, (int)wc->status);
        return;
      }
      const uint8_t* b = p->rbuf + (size_t)slot * GL_WIRE_BYTES;
      struct glCtrlEnv env;
      memcpy(&env, b, sizeof(env));
      const int ok = wc->byte_len == GL_WIRE_BYTES && gl_env_check(&env, GL_ENV_KIND_LAUNCHER) == GL_R_NONE &&
                     env.gen == p->gen && env.seq == p->seqIn + 1;
      if (!ok) {  // a gap or another generation's message on this QP: the connection is lost (design v2 2.4)
        gl_v_error(v, peer, -2);
        return;
      }
      p->seqIn = env.seq;
      p->consumed++;
      if (env.ackSeq > p->ackIn && env.ackSeq <= p->seqOut) p->ackIn = env.ackSeq;
      e.type = GL_TP_RC_RECV;
      e.peer = peer;
      memcpy(&e.msg, b + sizeof(env), sizeof(e.msg));
      gl_v_push(v, &e);
      if (gl_v_post_rc_recv(v, peer, slot) != 0) gl_v_error(v, peer, -3);
      gl_v_flush(v, peer);
      return;
    }
    case WR_RC_SEND: {
      if (peer < 0 || peer >= GL_V_PEERS || !v->peer[peer].used) return;
      v->peer[peer].sInflight--;
      if (wc->status != IBV_WC_SUCCESS && wc->status != IBV_WC_WR_FLUSH_ERR) gl_v_error(v, peer, (int)wc->status);
      else gl_v_flush(v, peer);
      return;
    }
    case WR_RC_CREDIT: {  // the rank's consumed count of our messages: ((gen << 32) | count)
      if (peer < 0 || peer >= GL_V_PEERS || !v->peer[peer].used) return;
      struct glVPeer* p = &v->peer[peer];
      p->creditReading = 0;
      p->sInflight--;
      if (wc->status != IBV_WC_SUCCESS) {
        if (wc->status != IBV_WC_WR_FLUSH_ERR) gl_v_error(v, peer, (int)wc->status);
        return;
      }
      const uint64_t w = *p->creditWord;
      const uint64_t cnt = (uint32_t)w;
      if ((uint32_t)(w >> 32) == p->gen && cnt > p->ackIn && cnt <= p->seqOut) p->ackIn = cnt;  // another gen: ignored
      gl_v_flush(v, peer);
      return;
    }
    case WR_RC_READ: {
      if (peer < 0 || peer >= GL_V_PEERS || !v->peer[peer].used || slot >= GL_V_READS) return;
      struct glVPeer* p = &v->peer[peer];
      struct glVRead* r = &p->rd[slot];
      if (!r->used) return;
      p->sInflight--;
      e.type = GL_TP_READ_DONE;
      e.peer = peer;
      e.cookie = r->cookie;
      e.status = wc->status == IBV_WC_SUCCESS ? 0 : (int)wc->status;
      ibv_dereg_mr(r->mr);
      r->used = 0;
      gl_v_push(v, &e);
      if (wc->status != IBV_WC_SUCCESS && wc->status != IBV_WC_WR_FLUSH_ERR) gl_v_error(v, peer, (int)wc->status);
      return;
    }
    default: return;
  }
}

static int gl_v_poll(struct glTransport* tp, struct glTpEvent* out, int max) {
  struct glVerbs* v = (struct glVerbs*)tp->impl;
  struct ibv_cq* cq;
  void* cctx;
  while (ibv_get_cq_event(v->ch, &cq, &cctx) == 0) {  // the channel fd is non-blocking
    ibv_ack_cq_events(cq, 1);
    ibv_req_notify_cq(cq, 0);
  }
  struct ibv_wc wc[32];
  for (;;) {  // poll, re-arm (above), poll once more: nothing slips between
    const int n = ibv_poll_cq(v->cq, 32, wc);
    if (n <= 0) break;
    for (int i = 0; i < n; i++) gl_v_on_wc(v, &wc[i]);
  }
  struct ibv_async_event ae;
  while (ibv_get_async_event(v->ctx, &ae) == 0) {  // the async fd is non-blocking
    if (ae.event_type == IBV_EVENT_QP_FATAL || ae.event_type == IBV_EVENT_QP_REQ_ERR ||
        ae.event_type == IBV_EVENT_QP_ACCESS_ERR) {
      for (int i = 0; i < GL_V_PEERS; i++)
        if (v->peer[i].used && v->peer[i].qp == ae.element.qp) gl_v_error(v, i, -(int)ae.event_type);
    }
    ibv_ack_async_event(&ae);
  }
  int k = 0;
  while (k < max && v->evCount > 0) {
    out[k++] = v->ev[v->evHead];
    v->evHead = (v->evHead + 1) % GL_V_EVQ;
    v->evCount--;
  }
  return k;
}

static int gl_v_local_ud(struct glTransport* tp, struct glEp* ud) {
  struct glVerbs* v = (struct glVerbs*)tp->impl;
  memset(ud, 0, sizeof(*ud));
  ud->qpn = v->ud->qp_num;
  ud->psn = v->udPsn;
  ud->lid = v->pa.lid;
  ud->mtu = (int32_t)v->pa.active_mtu;
  memcpy(ud->gid, v->gid.raw, 16);
  ud->gidIndex = v->gidIndex;
  ud->psn = v->qkey;  // a UD endpoint's psn carries its Q_Key (endpoint version 2)
  ud->version = GL_EP_VERSION;
  ud->qpType = GL_QPT_UD;
  return 0;
}

static int gl_v_page_register(struct glTransport* tp, void* page, size_t len, struct glRegion* out) {
  struct glVerbs* v = (struct glVerbs*)tp->impl;
  v->pageMr = ibv_reg_mr(v->pd, page, len, IBV_ACCESS_REMOTE_READ);
  if (!v->pageMr) return -1;
  out->addr = (uint64_t)(uintptr_t)page;
  out->rkey = v->pageMr->rkey;
  out->len = (uint32_t)len;
  return 0;
}

static int gl_v_ud_send(struct glTransport* tp, const struct glEp* to, uint32_t qkey, const struct glMsg* m) {
  struct glVerbs* v = (struct glVerbs*)tp->impl;
  const int slot = v->udNext;
  v->udNext = (v->udNext + 1) % GL_V_UD_SQ;
  if (v->udAh[slot]) return -1;  // the ring wrapped onto an unfinished send
  struct ibv_ah_attr aa;
  gl_v_ah_attr(v, to, &aa);
  v->udAh[slot] = ibv_create_ah(v->pd, &aa);
  if (!v->udAh[slot]) return -1;
  uint8_t* buf = v->udSbuf + (size_t)slot * GL_WIRE_BYTES;
  struct glCtrlEnv e;
  gl_env_pack(&e, GL_ENV_KIND_PAIR, (int32_t)(GL_FROM_LAUNCHER | (int32_t)v->node), 0, 0, 0, m->h.nonce, 0);
  memcpy(buf, &e, sizeof(e));
  memcpy(buf + sizeof(e), m, sizeof(*m));
  struct ibv_sge sg;
  sg.addr = (uintptr_t)buf;
  sg.length = GL_WIRE_BYTES;
  sg.lkey = v->udSmr->lkey;
  struct ibv_send_wr wr, *bad = NULL;
  memset(&wr, 0, sizeof(wr));
  wr.wr_id = wr_id(WR_UD_SEND, 0, slot);
  wr.sg_list = &sg;
  wr.num_sge = 1;
  wr.opcode = IBV_WR_SEND;
  wr.send_flags = IBV_SEND_SIGNALED;
  wr.wr.ud.ah = v->udAh[slot];
  wr.wr.ud.remote_qpn = to->qpn;
  wr.wr.ud.remote_qkey = qkey;
  if (ibv_post_send(v->ud, &wr, &bad) != 0) {
    ibv_destroy_ah(v->udAh[slot]);
    v->udAh[slot] = NULL;
    return -1;
  }
  return 0;
}

static void gl_v_peer_free(struct glVerbs* v, struct glVPeer* p) {
  for (int i = 0; i < GL_V_READS; i++)
    if (p->rd[i].used) ibv_dereg_mr(p->rd[i].mr);
  if (p->creditMr) ibv_dereg_mr(p->creditMr);
  free(p->creditWord);
  if (p->qp) ibv_destroy_qp(p->qp);
  if (p->smr) ibv_dereg_mr(p->smr);
  if (p->rmr) ibv_dereg_mr(p->rmr);
  free(p->sbuf);
  free(p->rbuf);
  free(p->pend);
  memset(p, 0, sizeof(*p));
  (void)v;
}

static int gl_v_rc_create(struct glTransport* tp, int kind, uint32_t gen, uint64_t nonce, struct glEp* local) {
  struct glVerbs* v = (struct glVerbs*)tp->impl;
  int pi = -1;
  for (int i = 0; i < GL_V_PEERS && pi < 0; i++)
    if (!v->peer[i].used) pi = i;
  if (pi < 0) return -1;
  struct glVPeer* p = &v->peer[pi];
  memset(p, 0, sizeof(*p));
  p->used = 1;
  p->kind = kind;
  p->gen = gen;
  p->nonce = nonce;
  const int rec = kind == GL_PAIR_RECORD;
  if (rec) {
    p->sbuf = (uint8_t*)calloc(GL_V_SQ, GL_WIRE_BYTES);
    p->rbuf = (uint8_t*)calloc(GL_V_RQ, GL_WIRE_BYTES);
    p->pend = (struct glMsg*)calloc(GL_V_PENDQ, sizeof(struct glMsg));
    p->creditWord = (uint64_t*)calloc(1, sizeof(uint64_t));
    if (!p->sbuf || !p->rbuf || !p->pend || !p->creditWord) goto fail;
    p->smr = ibv_reg_mr(v->pd, p->sbuf, (size_t)GL_V_SQ * GL_WIRE_BYTES, 0);
    p->rmr = ibv_reg_mr(v->pd, p->rbuf, (size_t)GL_V_RQ * GL_WIRE_BYTES, IBV_ACCESS_LOCAL_WRITE);
    p->creditMr = ibv_reg_mr(v->pd, p->creditWord, sizeof(uint64_t), IBV_ACCESS_LOCAL_WRITE);
    if (!p->smr || !p->rmr || !p->creditMr) goto fail;
  }
  struct ibv_qp_init_attr ia;
  memset(&ia, 0, sizeof(ia));
  ia.send_cq = v->cq;
  ia.recv_cq = v->cq;
  ia.qp_type = IBV_QPT_RC;
  ia.cap.max_send_wr = rec ? GL_V_SQ : 1;  // the probe QP is passive: the rank READs the page on it
  ia.cap.max_recv_wr = rec ? GL_V_RQ : 1;
  ia.cap.max_send_sge = 1;
  ia.cap.max_recv_sge = 1;
  p->qp = ibv_create_qp(v->pd, &ia);
  if (!p->qp) goto fail;
  struct ibv_qp_attr a;
  memset(&a, 0, sizeof(a));
  a.qp_state = IBV_QPS_INIT;
  a.pkey_index = 0;
  a.port_num = (uint8_t)v->port;
  a.qp_access_flags = IBV_ACCESS_REMOTE_READ;  // REMOTE_READ only (design v2 2.1)
  if (ibv_modify_qp(p->qp, &a, IBV_QP_STATE | IBV_QP_PKEY_INDEX | IBV_QP_PORT | IBV_QP_ACCESS_FLAGS)) goto fail;
  if (rec)
    for (int s = 0; s < GL_V_RQ; s++)  // RECVs before RTR (design v2 2.2)
      if (gl_v_post_rc_recv(v, pi, s) != 0) goto fail;
  {  // a fresh random PSN for every QP (REVIEW2 block 4: never a RESET QP's old PSN)
    uint32_t psn = 0;
    const int f = open("/dev/urandom", O_RDONLY | O_CLOEXEC);
    if (f >= 0) {
      if (read(f, &psn, sizeof(psn)) != (ssize_t)sizeof(psn)) psn = (uint32_t)(uintptr_t)p;
      close(f);
    }
    p->localPsn = psn & 0xffffffu;
  }
  memset(local, 0, sizeof(*local));
  local->qpn = p->qp->qp_num;
  local->psn = p->localPsn;
  local->lid = v->pa.lid;
  local->mtu = (int32_t)v->pa.active_mtu;
  memcpy(local->gid, v->gid.raw, 16);
  local->gidIndex = v->gidIndex;
  local->version = GL_EP_VERSION;
  local->qpType = GL_QPT_RC;
  return pi;
fail:
  fprintf(stderr, "GIN/LA: verbs transport: an RC QP for a rank could not be set up: %s\n", strerror(errno));
  gl_v_peer_free(v, p);
  return -1;
}

static int gl_v_rc_connect(struct glTransport* tp, int handle, const struct glEp* remote) {
  struct glVerbs* v = (struct glVerbs*)tp->impl;
  if (handle < 0 || handle >= GL_V_PEERS || !v->peer[handle].used || v->peer[handle].connected) return -1;
  struct glVPeer* p = &v->peer[handle];
  struct ibv_qp_attr a;
  memset(&a, 0, sizeof(a));
  a.qp_state = IBV_QPS_RTR;
  a.path_mtu = (enum ibv_mtu)(remote->mtu < (int32_t)v->pa.active_mtu ? remote->mtu : (int32_t)v->pa.active_mtu);
  a.dest_qp_num = remote->qpn;
  a.rq_psn = remote->psn;
  a.max_dest_rd_atomic = 1;
  a.min_rnr_timer = 12;
  gl_v_ah_attr(v, remote, &a.ah_attr);
  if (ibv_modify_qp(p->qp, &a,
                    IBV_QP_STATE | IBV_QP_AV | IBV_QP_PATH_MTU | IBV_QP_DEST_QPN | IBV_QP_RQ_PSN |
                        IBV_QP_MAX_DEST_RD_ATOMIC | IBV_QP_MIN_RNR_TIMER))
    return -1;
  memset(&a, 0, sizeof(a));
  a.qp_state = IBV_QPS_RTS;
  a.timeout = GL_V_TIMEOUT;
  a.retry_cnt = GL_V_RETRY;
  a.rnr_retry = GL_V_RNR_RETRY;
  a.sq_psn = p->localPsn;
  a.max_rd_atomic = 1;
  if (ibv_modify_qp(p->qp, &a,
                    IBV_QP_STATE | IBV_QP_TIMEOUT | IBV_QP_RETRY_CNT | IBV_QP_RNR_RETRY | IBV_QP_SQ_PSN |
                        IBV_QP_MAX_QP_RD_ATOMIC))
    return -1;
  p->connected = 1;
  return 0;
}

static void gl_v_rc_credit_at(struct glTransport* tp, int peer, const struct glRegion* page, uint32_t creditOff) {
  struct glVerbs* v = (struct glVerbs*)tp->impl;
  if (peer < 0 || peer >= GL_V_PEERS || !v->peer[peer].used) return;
  v->peer[peer].creditPage = *page;
  v->peer[peer].creditOff = creditOff;
}

static int gl_v_rc_send(struct glTransport* tp, int peer, const struct glMsg* m) {
  struct glVerbs* v = (struct glVerbs*)tp->impl;
  if (peer < 0 || peer >= GL_V_PEERS || !v->peer[peer].used || v->peer[peer].broken) return -1;
  struct glVPeer* p = &v->peer[peer];
  if (p->kind != GL_PAIR_RECORD || !p->connected) return -1;
  if (p->pCount == 0 && p->seqOut - p->ackIn < GL_V_RQ && p->sInflight < GL_V_SQ - GL_V_READS)
    return gl_v_post_send(v, peer, m);
  if (p->pCount == GL_V_PENDQ) return -1;
  if (p->pCount == 0)
    fprintf(stderr, "GIN/LA: node %u: send window to a rank exhausted (seq %llu, its ack %llu): queued\n", v->node,
            (unsigned long long)p->seqOut, (unsigned long long)p->ackIn);
  gl_v_credit_read(v, peer);
  p->pend[(p->pHead + p->pCount) % GL_V_PENDQ] = *m;
  p->pCount++;
  return 0;
}

static int gl_v_rc_read(struct glTransport* tp, int peer, uint64_t addr, uint32_t rkey, uint32_t len, void* dst,
                        uint64_t cookie) {
  struct glVerbs* v = (struct glVerbs*)tp->impl;
  if (peer < 0 || peer >= GL_V_PEERS || !v->peer[peer].used || v->peer[peer].broken) return -1;
  struct glVPeer* p = &v->peer[peer];
  int slot = -1;
  for (int i = 0; i < GL_V_READS && slot < 0; i++)
    if (!p->rd[i].used) slot = i;
  if (slot < 0 || p->sInflight >= GL_V_SQ) return -1;
  struct ibv_mr* mr = ibv_reg_mr(v->pd, dst, len, IBV_ACCESS_LOCAL_WRITE);
  if (!mr) return -1;
  struct ibv_sge sg;
  sg.addr = (uintptr_t)dst;
  sg.length = len;
  sg.lkey = mr->lkey;
  struct ibv_send_wr wr, *bad = NULL;
  memset(&wr, 0, sizeof(wr));
  wr.wr_id = wr_id(WR_RC_READ, peer, slot);
  wr.sg_list = &sg;
  wr.num_sge = 1;
  wr.opcode = IBV_WR_RDMA_READ;
  wr.send_flags = IBV_SEND_SIGNALED;
  wr.wr.rdma.remote_addr = addr;
  wr.wr.rdma.rkey = rkey;
  if (ibv_post_send(p->qp, &wr, &bad) != 0) {
    ibv_dereg_mr(mr);
    return -1;
  }
  p->rd[slot].used = 1;
  p->rd[slot].mr = mr;
  p->rd[slot].cookie = cookie;
  p->sInflight++;
  return 0;
}

static void gl_v_rc_close(struct glTransport* tp, int peer) {
  struct glVerbs* v = (struct glVerbs*)tp->impl;
  if (peer < 0 || peer >= GL_V_PEERS || !v->peer[peer].used) return;
  gl_v_peer_free(v, &v->peer[peer]);
}

static void gl_v_close(struct glTransport* tp) {
  struct glVerbs* v = (struct glVerbs*)tp->impl;
  for (int i = 0; i < GL_V_PEERS; i++)
    if (v->peer[i].used) gl_v_peer_free(v, &v->peer[i]);
  if (v->ud) ibv_destroy_qp(v->ud);
  for (int i = 0; i < GL_V_UD_SQ; i++)
    if (v->udAh[i]) ibv_destroy_ah(v->udAh[i]);
  if (v->udRmr) ibv_dereg_mr(v->udRmr);
  if (v->udSmr) ibv_dereg_mr(v->udSmr);
  if (v->pageMr) ibv_dereg_mr(v->pageMr);
  if (v->cq) ibv_destroy_cq(v->cq);
  if (v->ch) ibv_destroy_comp_channel(v->ch);
  if (v->pd) ibv_dealloc_pd(v->pd);
  if (v->ctx) ibv_close_device(v->ctx);
  free(v->udRbuf);
  free(v->udSbuf);
  free(v);
  free(tp);
}

static const struct glTransportOps gl_v_ops = {gl_v_fds,          gl_v_poll,       gl_v_local_ud, gl_v_page_register,
                                               gl_v_ud_send,      gl_v_rc_create,  gl_v_rc_connect, gl_v_rc_send,
                                               gl_v_rc_read,      gl_v_rc_credit_at, gl_v_rc_close, gl_v_close};

static int gl_v_nonblock(int fd) {
  const int fl = fcntl(fd, F_GETFL);
  return fl < 0 ? -1 : fcntl(fd, F_SETFL, fl | O_NONBLOCK);
}

struct glTransport* gl_transport_verbs_open(const char* dev, int port, int gidIndex, uint32_t qkey, uint32_t node) {
  struct glTransport* tp = (struct glTransport*)calloc(1, sizeof(*tp));
  struct glVerbs* v = (struct glVerbs*)calloc(1, sizeof(*v));
  if (!tp || !v) {
    free(tp);
    free(v);
    return NULL;
  }
  tp->ops = &gl_v_ops;
  tp->impl = v;
  v->port = port;
  v->gidIndex = gidIndex;
  v->qkey = qkey & 0x7fffffffu;
  v->node = node;
  int nd = 0;
  struct ibv_device** list = ibv_get_device_list(&nd);
  for (int i = 0; list && i < nd && !v->ctx; i++)
    if (!strcmp(ibv_get_device_name(list[i]), dev)) v->ctx = ibv_open_device(list[i]);
  if (list) ibv_free_device_list(list);
  const char* step = "open the device";
  if (!v->ctx) goto fail;
  step = "query the port";
  if (ibv_query_port(v->ctx, (uint8_t)port, &v->pa) || v->pa.state != IBV_PORT_ACTIVE) goto fail;
  step = "path MTU >= 2048 (decision 9)";
  if (v->pa.active_mtu < IBV_MTU_2048) goto fail;
  step = "query the GID";
  if (ibv_query_gid(v->ctx, (uint8_t)port, gidIndex, &v->gid)) goto fail;
  step = "PD, channel, CQ";
  v->pd = ibv_alloc_pd(v->ctx);
  v->ch = v->pd ? ibv_create_comp_channel(v->ctx) : NULL;
  v->cq = v->ch ? ibv_create_cq(v->ctx, GL_V_CQ, NULL, v->ch, 0) : NULL;
  if (!v->cq || gl_v_nonblock(v->ch->fd) || gl_v_nonblock(v->ctx->async_fd) || ibv_req_notify_cq(v->cq, 0)) goto fail;
  step = "UD buffers";
  v->udRbuf = (uint8_t*)calloc(GL_V_UD_RQ, GL_V_GRH + GL_WIRE_BYTES);
  v->udSbuf = (uint8_t*)calloc(GL_V_UD_SQ, GL_WIRE_BYTES);
  if (!v->udRbuf || !v->udSbuf) goto fail;
  v->udRmr = ibv_reg_mr(v->pd, v->udRbuf, (size_t)GL_V_UD_RQ * (GL_V_GRH + GL_WIRE_BYTES), IBV_ACCESS_LOCAL_WRITE);
  v->udSmr = ibv_reg_mr(v->pd, v->udSbuf, (size_t)GL_V_UD_SQ * GL_WIRE_BYTES, 0);
  if (!v->udRmr || !v->udSmr) goto fail;
  step = "the UD QP";
  {
    struct ibv_qp_init_attr ia;
    memset(&ia, 0, sizeof(ia));
    ia.send_cq = v->cq;
    ia.recv_cq = v->cq;
    ia.qp_type = IBV_QPT_UD;
    ia.cap.max_send_wr = GL_V_UD_SQ;
    ia.cap.max_recv_wr = GL_V_UD_RQ;
    ia.cap.max_send_sge = 1;
    ia.cap.max_recv_sge = 1;
    v->ud = ibv_create_qp(v->pd, &ia);
    if (!v->ud) goto fail;
    struct ibv_qp_attr a;
    memset(&a, 0, sizeof(a));
    a.qp_state = IBV_QPS_INIT;
    a.pkey_index = 0;
    a.port_num = (uint8_t)port;
    a.qkey = v->qkey;  // the launcher's own Q_Key (design v2 2.5)
    if (ibv_modify_qp(v->ud, &a, IBV_QP_STATE | IBV_QP_PKEY_INDEX | IBV_QP_PORT | IBV_QP_QKEY)) goto fail;
    for (int s = 0; s < GL_V_UD_RQ; s++)
      if (gl_v_post_ud_recv(v, s)) goto fail;
    memset(&a, 0, sizeof(a));
    a.qp_state = IBV_QPS_RTR;
    if (ibv_modify_qp(v->ud, &a, IBV_QP_STATE)) goto fail;
    memset(&a, 0, sizeof(a));
    a.qp_state = IBV_QPS_RTS;
    a.sq_psn = 0;
    v->udPsn = 0;
    if (ibv_modify_qp(v->ud, &a, IBV_QP_STATE | IBV_QP_SQ_PSN)) goto fail;
  }
  return tp;
fail:
  fprintf(stderr, "GIN/LA: verbs transport on %s port %d: could not %s (%s)\n", dev, port, step, strerror(errno));
  gl_v_close(tp);
  return NULL;
}
