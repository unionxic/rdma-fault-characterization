/*
 * rdma_conn.c — rdma_conn.h 구현.
 *
 * 분류(librdma_fault)는 "무엇을 해야 하는가"(action)만 알려준다. 여기서는 그
 * action을 실제 복구 절차로 옮긴다: bilateral QP reset + PSN 재협상(QP_RECOVERY),
 * 거기에 server MR 재등록 + rkey 재교환(QP_RECOVERY_MR), control channel로 peer
 * 생사 확인 후 분기(PROBE_PEER), 그리고 자동복구 불가 보고(NOTIFY_BUG).
 */
#include "rdma_conn.h"
#include "../06_recovery/recovery_common.h"   /* reset_qp_to_reset, drain_cq */

/* ------------------------------------------------------------------ */
/*  in-flight WR 추적                                                  */
/* ------------------------------------------------------------------ */

static void inflight_add(struct rdma_conn *c, uint64_t wr_id, int opcode,
			 uint32_t len)
{
	if (c->n_inflight < RDMA_CONN_MAX_INFLIGHT) {
		c->inflight[c->n_inflight].wr_id  = wr_id;
		c->inflight[c->n_inflight].opcode = opcode;
		c->inflight[c->n_inflight].length = len;
		c->n_inflight++;
	}
}

static void inflight_remove(struct rdma_conn *c, uint64_t wr_id)
{
	for (int i = 0; i < c->n_inflight; i++) {
		if (c->inflight[i].wr_id == wr_id) {
			c->inflight[i] = c->inflight[--c->n_inflight];
			return;
		}
	}
}

/* opcode별로 WR 하나 post. in-flight 기록은 호출자 책임. */
static int post_one(struct rdma_conn *c, const struct inflight_wr *w)
{
	struct ibv_sge sge = {
		.addr   = (uint64_t)c->res.buf,
		.length = w->length,
		.lkey   = c->res.mr->lkey,
	};
	struct ibv_send_wr wr = {
		.wr_id      = w->wr_id,
		.sg_list    = &sge,
		.num_sge    = 1,
		.opcode     = w->opcode,
		.send_flags = IBV_SEND_SIGNALED,
	};
	if (w->opcode == IBV_WR_RDMA_WRITE) {
		/* recovery로 remote_info(rkey/raddr)가 갱신됐을 수 있으므로 항상
		 * 현재 값을 쓴다 — MR refresh 후 재전송이 새 rkey를 타게 된다. */
		wr.wr.rdma.remote_addr = c->res.remote_info.raddr;
		wr.wr.rdma.rkey        = c->res.remote_info.rkey;
	}
	struct ibv_send_wr *bad;
	return ibv_post_send(c->res.qp, &wr, &bad);
}

int rdma_conn_send(struct rdma_conn *c, uint64_t wr_id, uint32_t len)
{
	struct inflight_wr w = { wr_id, IBV_WR_SEND, len };
	int rc = post_one(c, &w);
	if (rc == 0)
		inflight_add(c, wr_id, IBV_WR_SEND, len);
	return rc;
}

int rdma_conn_write(struct rdma_conn *c, uint64_t wr_id, uint32_t len)
{
	struct inflight_wr w = { wr_id, IBV_WR_RDMA_WRITE, len };
	int rc = post_one(c, &w);
	if (rc == 0)
		inflight_add(c, wr_id, IBV_WR_RDMA_WRITE, len);
	return rc;
}

int rdma_conn_poll(struct rdma_conn *c, struct ibv_wc *wc,
		   struct rdma_fault_info *fi, int timeout_ms)
{
	struct timespec start, now;
	clock_gettime(CLOCK_MONOTONIC, &start);
	while (1) {
		int n = rdma_poll(c->res.cq, 1, wc, fi);   /* 라이브러리: poll+classify */
		if (n < 0)
			return n;
		if (n > 0) {
			if (fi->error_class == RDMA_CLASS_OK)
				inflight_remove(c, wc->wr_id);
			return n;
		}
		clock_gettime(CLOCK_MONOTONIC, &now);
		long ms = (now.tv_sec - start.tv_sec) * 1000 +
			  (now.tv_nsec - start.tv_nsec) / 1000000;
		if (timeout_ms > 0 && ms > timeout_ms)
			return 0;
	}
}

/* ------------------------------------------------------------------ */
/*  server control channel I/O                                        */
/* ------------------------------------------------------------------ */

/*
 * The server ctrl socket carries SO_RCVTIMEO = CTRL_STEP_TIMEOUT_S, so every
 * blocking read() returns within that bound. common.h's tcp_recv_msg folds
 * "timed out", "peer closed" and "error" into one -1 (and tcp_exchange_qp_info
 * ignores even that), so a plain idle timeout used to look like shutdown.
 * The server side therefore uses these variants, which keep them apart:
 *   - waiting for the NEXT command (rdma_conn_serve): a timeout before any
 *     byte arrived only means "no command yet" -> keep waiting, so a healthy
 *     idle connection is served indefinitely;
 *   - inside a started exchange (setup / recovery): any timeout means the
 *     client stalled or died mid-exchange -> fail, so it cannot hang us.
 */
#define CTRL_STEP_TIMEOUT_S  5

#define CTRL_ERR     (-1)   /* I/O error, or timeout after part of a line */
#define CTRL_IDLE    (-2)   /* timeout before the first byte of a line */
#define CTRL_CLOSED  (-3)   /* orderly peer close (read() == 0) */

/* One '\n'-terminated line (same framing as tcp_recv_msg).
 * Returns its length (>= 0) or CTRL_ERR / CTRL_IDLE / CTRL_CLOSED. */
static int ctrl_recv_line(int sock, char *buf, int buflen)
{
	int total = 0;
	while (total < buflen - 1) {
		ssize_t n = read(sock, buf + total, 1);
		if (n == 1) {
			if (buf[total] == '\n') {
				buf[total] = '\0';
				return total;
			}
			total++;
			continue;
		}
		if (n == 0)
			return CTRL_CLOSED;
		if (errno == EINTR)
			continue;
		if ((errno == EAGAIN || errno == EWOULDBLOCK) && total == 0)
			return CTRL_IDLE;
		return CTRL_ERR;
	}
	buf[total] = '\0';
	return total;
}

/* Checked send of one line. MSG_NOSIGNAL: a peer that died mid-recovery must
 * surface as -1 here, not as a SIGPIPE that kills the server. */
static int ctrl_send_line(int sock, const char *msg)
{
	char buf[256];
	int len = snprintf(buf, sizeof(buf), "%s\n", msg);
	if (len < 0 || len >= (int)sizeof(buf))
		return -1;
	for (int off = 0; off < len; ) {
		ssize_t n = send(sock, buf + off, len - off, MSG_NOSIGNAL);
		if (n < 0 && errno == EINTR)
			continue;
		if (n <= 0)
			return -1;
		off += n;
	}
	return 0;
}

/* Server half of tcp_exchange_qp_info (same wire format: receive the client's
 * "qpn,psn,rkey,raddr,gid" line, then send ours), but every step is checked
 * and bounded: a client that closes, stalls (> CTRL_STEP_TIMEOUT_S) or sends a
 * malformed line yields -1 instead of a silently garbage remote_info. */
static int ctrl_exchange_qp_info_server(int sock, const struct qp_info *local,
					struct qp_info *remote)
{
	char rbuf[256], lbuf[256], gid_str[33];
	struct qp_info r;
	unsigned long raddr;

	int n = ctrl_recv_line(sock, rbuf, sizeof(rbuf));
	if (n < 0) {
		fprintf(stderr, "rdma_conn: QP info exchange: %s\n",
			n == CTRL_CLOSED ? "peer closed" :
			n == CTRL_IDLE   ? "peer stalled (timeout)" :
					   "recv error/stall");
		return -1;
	}
	if (sscanf(rbuf, "%u,%u,%u,%lu,%32s", &r.qpn, &r.psn, &r.rkey,
		   &raddr, gid_str) != 5 || strlen(gid_str) != 32) {
		fprintf(stderr, "rdma_conn: QP info exchange: malformed '%s'\n",
			rbuf);
		return -1;
	}
	r.raddr = raddr;
	for (int i = 0; i < 16; i++) {
		unsigned int v;
		if (sscanf(gid_str + i * 2, "%2x", &v) != 1)
			return -1;
		r.gid.raw[i] = v;
	}

	for (int i = 0; i < 16; i++)
		sprintf(gid_str + i * 2, "%02x", local->gid.raw[i]);
	snprintf(lbuf, sizeof(lbuf), "%u,%u,%u,%lu,%s",
		 local->qpn, local->psn, local->rkey,
		 (unsigned long)local->raddr, gid_str);
	if (ctrl_send_line(sock, lbuf) < 0)
		return -1;
	*remote = r;
	return 0;
}

/* ------------------------------------------------------------------ */
/*  lifecycle                                                         */
/* ------------------------------------------------------------------ */

static int wait_ready(struct rdma_conn *c)
{
	char buf[64];
	if (tcp_recv_msg(c->ctrl_sock, buf, sizeof(buf)) < 0)
		return -1;
	return strcmp(buf, CMD_READY) == 0 ? 0 : -1;
}

int rdma_conn_client(struct rdma_conn *c, const char *server_ip,
		     int mr_access, int remote_write,
		     int retry_cnt, int rnr_retry, int timeout)
{
	memset(c, 0, sizeof(*c));
	c->is_server   = 0;
	c->mr_access   = mr_access;
	c->remote_write = remote_write;
	c->retry_cnt   = retry_cnt;
	c->rnr_retry   = rnr_retry;
	c->timeout     = timeout;

	c->ctrl_sock = tcp_connect(server_ip, TCP_CTRL_PORT);
	if (c->ctrl_sock < 0)
		return -1;

	/* probe가 link-down에 무한 대기하지 않도록 control sock에 recv timeout. */
	struct timeval tv = { .tv_sec = 5, .tv_usec = 0 };
	setsockopt(c->ctrl_sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

	if (tcp_send_msg(c->ctrl_sock, CMD_MW_SETUP) < 0)
		goto fail;
	if (wait_ready(c) < 0)                     /* #1: server 자원 준비됨 */
		goto fail;

	if (setup_rdma(&c->res, 1, mr_access, retry_cnt, rnr_retry, timeout) < 0)
		goto fail;
	if (tcp_exchange_qp_info(c->ctrl_sock, &c->res.local_info,
				 &c->res.remote_info, 0) < 0)
		goto fail;
	if (connect_qp(&c->res, remote_write, retry_cnt, rnr_retry, timeout) < 0)
		goto fail;
	if (wait_ready(c) < 0)                     /* #2: 연결 완료 */
		goto fail;
	return 0;
fail:
	/* free ctrl socket + any partially-allocated RDMA resources so a
	 * failed connect does not leak an fd / QP / MR / PD / context. */
	rdma_conn_close(c);
	return -1;
}

int rdma_conn_server(struct rdma_conn *c, int listen_sock,
		     int mr_access, int remote_write,
		     int retry_cnt, int rnr_retry, int timeout,
		     int post_recv_initial)
{
	memset(c, 0, sizeof(*c));
	c->is_server        = 1;
	c->mr_access        = mr_access;
	c->remote_write     = remote_write;
	c->retry_cnt        = retry_cnt;
	c->rnr_retry        = rnr_retry;
	c->timeout          = timeout;
	c->post_recv_initial = post_recv_initial;

	struct sockaddr_in caddr;
	socklen_t alen = sizeof(caddr);
	c->ctrl_sock = accept(listen_sock, (struct sockaddr *)&caddr, &alen);
	if (c->ctrl_sock < 0)
		return -1;
	int flag = 1;
	setsockopt(c->ctrl_sock, IPPROTO_TCP, TCP_NODELAY, &flag, sizeof(flag));
	/* Bound each blocking read (mirrors the client-side SO_RCVTIMEO) so a
	 * client that dies mid-setup / mid-recovery cannot hang the server.
	 * This bounds exchange STEPS only: rdma_conn_serve treats a timeout while
	 * waiting for the next command as idleness, not as peer loss. */
	struct timeval tv = { .tv_sec = CTRL_STEP_TIMEOUT_S, .tv_usec = 0 };
	setsockopt(c->ctrl_sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

	char buf[64];
	if (ctrl_recv_line(c->ctrl_sock, buf, sizeof(buf)) < 0 ||
	    strcmp(buf, CMD_MW_SETUP) != 0)
		goto fail;

	if (setup_rdma(&c->res, 1, mr_access, retry_cnt, rnr_retry, timeout) < 0)
		goto fail;
	if (ctrl_send_line(c->ctrl_sock, CMD_READY) < 0)      /* #1 */
		goto fail;
	if (ctrl_exchange_qp_info_server(c->ctrl_sock, &c->res.local_info,
					 &c->res.remote_info) < 0)
		goto fail;
	if (connect_qp(&c->res, remote_write, retry_cnt, rnr_retry, timeout) < 0)
		goto fail;
	if (post_recv_initial && post_recv(&c->res) < 0)
		goto fail;
	if (ctrl_send_line(c->ctrl_sock, CMD_READY) < 0)      /* #2 */
		goto fail;
	return 0;
fail:
	rdma_conn_close(c);
	return -1;
}

void rdma_conn_close(struct rdma_conn *c)
{
	if (c->ctrl_sock >= 0)
		close(c->ctrl_sock);
	cleanup_rdma(&c->res);
	c->ctrl_sock = -1;
}

/* ------------------------------------------------------------------ */
/*  recovery (client 주도)                                            */
/* ------------------------------------------------------------------ */

/* 기록된 in-flight WR을 전부 재post (현재 remote_info 기준 → 새 rkey 반영) */
static int resend_inflight(struct rdma_conn *c)
{
	struct inflight_wr saved[RDMA_CONN_MAX_INFLIGHT];
	int n = c->n_inflight;
	memcpy(saved, c->inflight, sizeof(struct inflight_wr) * n);
	c->n_inflight = 0;
	for (int i = 0; i < n; i++) {
		if (post_one(c, &saved[i]) != 0)
			return -1;
		inflight_add(c, saved[i].wr_id, saved[i].opcode, saved[i].length);
	}
	return 0;
}

/*
 * bilateral QP reset. client가 주도하고 cmd(MW_RECOVER/MW_REFRESH)로 server에
 * 같은 절차를 지시한다. 양쪽이 RESET→RTS로 돌고 PSN을 새로 협상한다.
 */
static int bilateral_qp(struct rdma_conn *c, const char *cmd)
{
	/* Reset first, THEN drain: the ERR->RESET transition can still surface
	 * flush CQEs for sibling in-flight WQEs, so draining after the reset
	 * guarantees no stale completion is left to be misclassified by the
	 * first post-recovery poll. */
	if (reset_qp_to_reset(c->res.qp) < 0)
		return -1;
	drain_cq(c->res.cq);
	c->res.local_info.psn = rand() & 0xFFFFFF;

	if (tcp_send_msg(c->ctrl_sock, cmd) < 0)
		return -1;
	if (tcp_exchange_qp_info(c->ctrl_sock, &c->res.local_info,
				 &c->res.remote_info, 0) < 0)
		return -1;
	if (connect_qp(&c->res, c->remote_write, c->retry_cnt,
		       c->rnr_retry, c->timeout) < 0)
		return -1;
	return wait_ready(c);
}

/* control channel로 peer 생사 확인. 1=alive, 0=dead/무응답. */
static int probe_peer(struct rdma_conn *c)
{
	if (tcp_send_msg(c->ctrl_sock, CMD_MW_PROBE) < 0)
		return 0;
	char buf[64];
	int n = tcp_recv_msg(c->ctrl_sock, buf, sizeof(buf));
	if (n < 0)
		return 0;   /* RST/timeout = 프로세스 종료 또는 link down */
	return strcmp(buf, CMD_READY) == 0;
}

enum rdma_recover_result rdma_conn_recover(struct rdma_conn *c,
					   const struct rdma_fault_info *fi)
{
	switch (fi->action) {
	case RDMA_ACT_NONE:
		return RDMA_RECOVER_NOTREQ;

	case RDMA_ACT_NOTIFY_BUG:
		/* 로컬 보호 위반 — wire 밖 application bug. 복구 시도하지 않는다. */
		return RDMA_RECOVER_BUG;

	case RDMA_ACT_QP_RECOVERY:
		if (bilateral_qp(c, CMD_MW_RECOVER) < 0)
			return RDMA_RECOVER_FAILED;
		break;

	case RDMA_ACT_QP_RECOVERY_MR:
		if (bilateral_qp(c, CMD_MW_REFRESH) < 0)
			return RDMA_RECOVER_FAILED;
		break;

	case RDMA_ACT_PROBE_PEER:
		/* timeout — peer 생사 불명. control channel로 먼저 확인. */
		if (!probe_peer(c))
			return RDMA_RECOVER_PEER_DEAD;
		if (bilateral_qp(c, CMD_MW_RECOVER) < 0)
			return RDMA_RECOVER_FAILED;
		break;

	default:
		return RDMA_RECOVER_FAILED;
	}

	c->recover_count++;
	if (resend_inflight(c) < 0)
		return RDMA_RECOVER_FAILED;
	return RDMA_RECOVER_OK;
}

/* ------------------------------------------------------------------ */
/*  server 협조                                                       */
/* ------------------------------------------------------------------ */

int rdma_conn_handle(struct rdma_conn *c, const char *cmd)
{
	if (strcmp(cmd, CMD_MW_RECOVER) == 0) {
		if (reset_qp_to_reset(c->res.qp) < 0)
			return -1;
		drain_cq(c->res.cq);
		c->res.local_info.psn = rand() & 0xFFFFFF;
		if (ctrl_exchange_qp_info_server(c->ctrl_sock, &c->res.local_info,
						 &c->res.remote_info) < 0)
			return -1;
		if (connect_qp(&c->res, c->remote_write, c->retry_cnt,
			       c->rnr_retry, c->timeout) < 0)
			return -1;
		if (post_recv(&c->res) < 0)
			return -1;
		if (ctrl_send_line(c->ctrl_sock, CMD_READY) < 0)
			return -1;
		return 1;
	}

	if (strcmp(cmd, CMD_MW_REFRESH) == 0) {
		if (reset_qp_to_reset(c->res.qp) < 0)
			return -1;
		drain_cq(c->res.cq);
		/* MR 재등록 → 새 rkey. stale rkey / MR 권한 문제를 해소한다. */
		if (ibv_dereg_mr(c->res.mr) != 0)
			fprintf(stderr, "rdma_conn: ibv_dereg_mr failed: %s\n",
				strerror(errno));
		c->res.mr = ibv_reg_mr(c->res.pd, c->res.buf, MR_SIZE, c->mr_access);
		if (!c->res.mr)
			return -1;
		c->res.local_info.rkey = c->res.mr->rkey;
		c->res.local_info.psn  = rand() & 0xFFFFFF;
		if (ctrl_exchange_qp_info_server(c->ctrl_sock, &c->res.local_info,
						 &c->res.remote_info) < 0)
			return -1;
		if (connect_qp(&c->res, c->remote_write, c->retry_cnt,
			       c->rnr_retry, c->timeout) < 0)
			return -1;
		if (post_recv(&c->res) < 0)
			return -1;
		if (ctrl_send_line(c->ctrl_sock, CMD_READY) < 0)
			return -1;
		return 1;
	}

	if (strcmp(cmd, CMD_MW_PROBE) == 0) {
		/* 살아있음을 응답 */
		if (ctrl_send_line(c->ctrl_sock, CMD_READY) < 0)
			return -1;
		return 1;
	}

	if (strcmp(cmd, CMD_MW_SHUTDOWN) == 0)
		return 0;

	return 0;
}

/*
 * Serve client commands until MW_SHUTDOWN.
 * Returns 0 ONLY on MW_SHUTDOWN; -1 if the peer closed the control channel
 * without it, on a control-channel error, or if a handler failed (including a
 * recovery exchange whose peer stalled > CTRL_STEP_TIMEOUT_S or died).
 * Waiting for the next command is unbounded: SO_RCVTIMEO expiring while idle
 * (e.g. while the client waits out a multi-second RETRY_EXC detection) is not
 * peer loss, so a healthy idle connection is served indefinitely.
 */
int rdma_conn_serve(struct rdma_conn *c)
{
	char cmd[64];
	for (;;) {
		int n = ctrl_recv_line(c->ctrl_sock, cmd, sizeof(cmd));
		if (n == CTRL_IDLE)
			continue;           /* no command yet — keep serving */
		if (n == CTRL_CLOSED) {
			fprintf(stderr, "rdma_conn_serve: peer closed control "
				"channel without %s\n", CMD_MW_SHUTDOWN);
			return -1;
		}
		if (n < 0) {
			fprintf(stderr, "rdma_conn_serve: control channel "
				"error/stall: %s\n", strerror(errno));
			return -1;
		}
		if (strcmp(cmd, CMD_MW_SHUTDOWN) == 0)
			return 0;
		if (rdma_conn_handle(c, cmd) < 0) {
			/* A failed handler leaves the connection desynced (e.g. MR
			 * re-register failed -> res.mr may be NULL, or the peer
			 * vanished mid-exchange). Stop serving rather than run
			 * subsequent commands on broken resources. */
			fprintf(stderr, "rdma_conn_serve: handle '%s' failed, "
				"stopping\n", cmd);
			return -1;
		}
	}
}

const char *rdma_recover_result_str(enum rdma_recover_result r)
{
	switch (r) {
	case RDMA_RECOVER_OK:        return "OK(복구+재전송 완료)";
	case RDMA_RECOVER_NOTREQ:    return "복구 불필요";
	case RDMA_RECOVER_BUG:       return "자동복구 불가(application bug)";
	case RDMA_RECOVER_PEER_DEAD: return "peer 사망(escalate)";
	case RDMA_RECOVER_FAILED:    return "복구 실패";
	default:                     return "?";
	}
}
