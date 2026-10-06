/*
 * common.h — 05_counter_mapping 공유 인프라 헤더 (224 사본)
 *
 * 시나리오 ID(11개 fault 유형), TCP 제어 프로토콜(CMD_*), 하드웨어 카운터 스냅샷/델타,
 * RDMA 연결 보일러플레이트(setup_rdma → qp_info 교환 → connect_qp)를 담은
 * 단일 헤더 라이브러리. 06_recovery도 include한다.
 *
 * 225 사본과 형제 관계지만 완전 동일하지는 않다: 225 쪽에는 NIC udev rename
 * (mlx5_0 → rocep1s0f0) 대응용 런타임 장치명 탐색 주석/코드가 더 들어가 있다.
 * 프로토콜(CMD_*, scenario enum)을 바꿀 때는 반드시 양쪽을 같이 고칠 것 —
 * 안 그러면 client(225)와 server(224)가 서로 다른 명령 문자열을 쓰게 된다.
 */
#ifndef COMMON_H
#define COMMON_H

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <time.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <netinet/tcp.h>
#include <infiniband/verbs.h>

/* ------------------------------------------------------------------ */
/*  Network configuration                                             */
/* ------------------------------------------------------------------ */

#define RDMA_SERVER_IP   "10.0.0.3"
#define RDMA_CLIENT_IP   "10.0.0.2"
#define MGMT_SERVER_IP   "SERVER_224_ADDR"
#define TCP_CTRL_PORT    18515
#define DAEMON_PORT      18516

#define IB_DEV_NAME      "mlx5_0"
#define IB_PORT          1
#define GID_INDEX        3

/* ------------------------------------------------------------------ */
/*  RDMA parameters                                                   */
/* ------------------------------------------------------------------ */

#define BUF_SIZE         4096
#define MR_SIZE          4096
#define BOUNDARY_BUF_SIZE (MR_SIZE * 2)
#define CQ_DEPTH         16
#define MAX_WR           16
#define MAX_SGE          1

/* Large in-bounds buffer for interrupted-write (timeout/peer-death) test.
 * Both the server backing buffer and its MR span LARGE_BUF_SIZE, so a
 * LARGE_WRITE_LEN WRITE is fully inside the MR (NOT an address violation).
 * The fault is a mid-transfer responder QP->ERR, producing a partial write
 * that should be whole-PMTU-packet granular. PMTU here is IBV_MTU_1024. */
#define LARGE_BUF_SIZE   (8 * 1024 * 1024)   /* 8 MB MR + backing buffer   */
#define LARGE_WRITE_LEN  (4 * 1024 * 1024)   /* 4 MB WRITE = 4096 PMTU pkts */
#define PMTU_BYTES       1024                 /* matches IBV_MTU_1024 in RTR */

/* ------------------------------------------------------------------ */
/*  Scenario IDs                                                      */
/* ------------------------------------------------------------------ */

enum scenario {
	SCENARIO_NONE = 0,
	LOC_PROT_LEN,       /* SGE length > MR size */
	LOC_PROT_LKEY,      /* invalid lkey */
	LOC_PROT_PERM,      /* MR permission violation */
	WR_FLUSH,           /* QP -> ERR flush */
	REM_INV_REQ,        /* remote WRITE flag disabled */
	REM_ACCESS_RKEY,    /* invalid rkey */
	RNR_RETRY_EXC,          /* recv buffer exhaustion (SEND/RECV) */
	RETRY_EXC_QP_ERR,      /* server QP -> ERR */
	RETRY_EXC_PROC_KILL,   /* server process killed */
	RETRY_EXC_LINK_DOWN,   /* server link down */
	REM_ACCESS_ADDR,    /* address out of bounds */
	SCENARIO_MAX
};

static __attribute__((unused)) const char *scenario_names[] = {
	[SCENARIO_NONE]       = "NONE",
	[LOC_PROT_LEN]    = "LOC_PROT_LEN",
	[LOC_PROT_LKEY]   = "LOC_PROT_LKEY",
	[LOC_PROT_PERM]   = "LOC_PROT_PERM",
	[WR_FLUSH]        = "WR_FLUSH",
	[REM_INV_REQ]     = "REM_INV_REQ",
	[REM_ACCESS_RKEY] = "REM_ACCESS_RKEY",
	[RNR_RETRY_EXC]       = "RNR_RETRY_EXC",
	[RETRY_EXC_QP_ERR]   = "RETRY_EXC_QP_ERR",
	[RETRY_EXC_PROC_KILL]= "RETRY_EXC_PROC_KILL",
	[RETRY_EXC_LINK_DOWN]= "RETRY_EXC_LINK_DOWN",
	[REM_ACCESS_ADDR] = "REM_ACCESS_ADDR",
};

/* ------------------------------------------------------------------ */
/*  TCP control protocol                                              */
/* ------------------------------------------------------------------ */

#define CMD_SETUP          "SETUP"
#define CMD_SETUP_SEND     "SETUP_SEND"
#define CMD_SETUP_NOREMOTE "SETUP_NOREMOTE"
#define CMD_INJECT         "INJECT"
#define CMD_READY          "READY"
#define CMD_DONE           "DONE"
#define CMD_CLEANUP        "CLEANUP"
#define CMD_SHUTDOWN       "SHUTDOWN"
#define CMD_SNAPSHOT       "SNAPSHOT"
#define CMD_QUERY_STATE    "QUERY_STATE"
#define CMD_SETUP_BOUNDARY "SETUP_BOUNDARY"
#define CMD_INIT_BUFFER    "INIT_BUFFER"
#define CMD_CHECK_BUFFER   "CHECK_BUFFER"

/* Interrupted-write (timeout/peer-death) test commands */
#define CMD_SETUP_LARGE    "SETUP_LARGE"   /* register 8MB buf+MR, connect QP */
#define CMD_INIT_LARGE     "INIT_LARGE"    /* zero the large buffer            */
#define CMD_INTERRUPT      "INTERRUPT"     /* responder QP -> ERR (the fault)  */
#define CMD_CHECK_LARGE    "CHECK_LARGE"   /* "CHECK_LARGE <write_len>" scan    */

/* A/B recovery-strategy comparison commands (REM_ACCESS_ERR address overrun).
 * The server backs a buffer of AB_BUF_SIZE but registers an MR of only
 * mr_size bytes (mr_size <= AB_BUF_SIZE). The in-MR prefix [0, mr_size) is a
 * valid WRITE target; [mr_size, AB_BUF_SIZE) is backing memory that an
 * address-overrun WRITE can partially DMA into before the boundary packet
 * NAKs (REM_ACCESS_ERR). After exchanging qp_info, the server sends an extra
 * line "mr_base,mr_size" so strategy B can range-check locally. */
#define CMD_SETUP_AB       "SETUP_AB"      /* "SETUP_AB <mr_size>": reg MR, send bounds */
#define CMD_RECOVER_AB     "RECOVER_AB"    /* QP-only recovery over live socket */
#define CMD_INIT_AB        "INIT_AB"       /* zero the AB backing buffer        */
#define CMD_CHECK_AB       "CHECK_AB"      /* "CHECK_AB <off> <len> <mr_size>" scan */

/* AB backing buffer: large enough to hold any test message landing past the
 * registered MR boundary, plus a correct in-MR target for the resend. */
#define AB_BUF_SIZE        (1 * 1024 * 1024)  /* 1 MB backing buffer */

/* ------------------------------------------------------------------ */
/*  Strategy-C: silent partial-write commit-protocol comparison        */
/* ------------------------------------------------------------------ */

/* A silent (timeout / peer-death) partial WRITE gives no NAK: the responder QP
 * is driven to ERR mid-transfer (CMD_INTERRUPT) and the requester only sees a
 * flushed WQE. Unlike the NAK path (ab_recovery), sq_psn cannot recover the torn
 * boundary (sq_psn == transmitted, not committed). Since a WRITE requester always
 * still holds the source, the real hazard is a CONSUMER reading a torn prefix as
 * complete. This experiment compares three ways to make the torn prefix SAFE and
 * measures their normal-path overhead vs post-fault judging/recovery cost:
 *   C1 commit-flag : payload WRITE(unsignaled) + 8B flag WRITE(signaled) on the
 *                    same QP. RC in-order execution => the flag lands ONLY if the
 *                    whole payload landed. Judging is O(1) (flag present?).
 *   C2 crc32c      : 16B header [seq|len|crc|reserved] + payload in ONE WRITE;
 *                    crc32c covers the payload. Judging = recompute crc, O(len).
 *   C3 read-back   : plain WRITE (zero normal-path overhead); after the fault,
 *                    RDMA READ the region back, diff against the local original to
 *                    find the written boundary, then resend ONLY the missing tail.
 * The server backs LARGE_BUF_SIZE (8MB) and registers an 8MB MR that INCLUDES
 * REMOTE_READ (needed for C3's read-back). The payload target is offset 0; the
 * 8B commit-flag slot is the aligned tail. CMD_INTERRUPT injects the fault. */
#define CMD_SETUP_C    "SETUP_C"      /* reg 8MB buf+MR (REMOTE_READ), connect QP */
#define CMD_INIT_C     "INIT_C"       /* zero the large buffer incl. flag slot     */
#define CMD_CHECK_FLAG "CHECK_FLAG"   /* return the 8B commit-flag slot value       */
#define CMD_VERIFY_CRC "VERIFY_CRC"   /* "VERIFY_CRC <seq>": recompute+judge crc32c */
#define CMD_RECOVER_C  "RECOVER_C"    /* QP-only recovery over the live socket       */
#define CMD_CHECK_C    "CHECK_C"      /* "CHECK_C <off> <len>": ground-truth scan    */
/* (CMD_INTERRUPT, defined above, is reused as the responder QP->ERR fault.)         */

/* C1 commit-flag slot: 8 bytes at the tail of the 8MB MR. LARGE_BUF_SIZE is 8B
 * aligned, so LARGE_BUF_SIZE-8 is too. Kept far from the [0, LARGE_WRITE_LEN)
 * payload so they never overlap. Flag value = magic in the high 32 bits, trial
 * seq in the low 32 bits; a consumer treats the payload as valid iff
 * (flag >> 32) == C_FLAG_MAGIC && (uint32_t)flag == expected_seq. */
#define C_FLAG_OFFSET  (LARGE_BUF_SIZE - 8)
#define C_FLAG_MAGIC   0xC0DE0000u

/* C2 per-message header, prepended to the payload and written in the SAME WRITE.
 * crc covers exactly `len` payload bytes (NOT the header itself). */
struct c2_header {
	uint32_t seq;
	uint32_t len;
	uint32_t crc;
	uint32_t reserved;
};
#define C2_HEADER_SIZE 16   /* == sizeof(struct c2_header); fixed on the wire */

/* ------------------------------------------------------------------ */
/*  QP exchange info                                                  */
/* ------------------------------------------------------------------ */

struct qp_info {
	uint32_t qpn;
	uint32_t psn;
	uint32_t rkey;
	uint64_t raddr;
	union ibv_gid gid;
};

/* ------------------------------------------------------------------ */
/*  Counter definitions                                               */
/* ------------------------------------------------------------------ */

#define HW_COUNTERS_PATH  "/sys/class/infiniband/mlx5_0/ports/1/hw_counters"
#define PORT_COUNTERS_PATH "/sys/class/infiniband/mlx5_0/ports/1/counters"

static const char *hw_counter_names[] = {
	"local_ack_timeout_err",
	"out_of_sequence",
	"packet_seq_err",
	"implied_nak_seq_err",
	"rnr_nak_retry_err",
	"req_cqe_error",
	"resp_cqe_error",
	"req_cqe_flush_error",
	"resp_cqe_flush_error",
	"req_remote_invalid_request",
	"req_remote_access_errors",
	"resp_remote_access_errors",
	"resp_local_length_error",
	"duplicate_request",
	"out_of_buffer",
	"rx_icrc_encapsulated",
	"req_transport_retries_exceeded",
	"req_rnr_retries_exceeded",
	"roce_adp_retrans",
	"roce_adp_retrans_to",
	"roce_slow_restart",
	NULL
};

static const char *port_counter_names[] = {
	"port_rcv_errors",
	"local_link_integrity_errors",
	"link_error_recovery",
	"link_downed",
	NULL
};

#define MAX_COUNTERS 32

struct counter_snapshot {
	char names[MAX_COUNTERS][64];
	long long values[MAX_COUNTERS];
	int count;
};

/* ------------------------------------------------------------------ */
/*  Counter read/delta functions                                      */
/* ------------------------------------------------------------------ */

static int read_sysfs_counter(const char *dir, const char *name, long long *val)
{
	char path[256];
	snprintf(path, sizeof(path), "%s/%s", dir, name);
	FILE *f = fopen(path, "r");
	if (!f)
		return -1;
	if (fscanf(f, "%lld", val) != 1) {
		fclose(f);
		return -1;
	}
	fclose(f);
	return 0;
}

static int snapshot_local_counters(struct counter_snapshot *snap)
{
	int idx = 0;

	for (int i = 0; hw_counter_names[i]; i++) {
		strncpy(snap->names[idx], hw_counter_names[i], 63);
		if (read_sysfs_counter(HW_COUNTERS_PATH, hw_counter_names[i],
				       &snap->values[idx]) < 0) {
			snap->values[idx] = -1;
		}
		idx++;
	}
	for (int i = 0; port_counter_names[i]; i++) {
		strncpy(snap->names[idx], port_counter_names[i], 63);
		if (read_sysfs_counter(PORT_COUNTERS_PATH, port_counter_names[i],
				       &snap->values[idx]) < 0) {
			snap->values[idx] = -1;
		}
		idx++;
	}
	snap->count = idx;
	return 0;
}

static __attribute__((unused)) void print_counter_delta(const char *label,
				const struct counter_snapshot *before,
				const struct counter_snapshot *after,
				FILE *out)
{
	for (int i = 0; i < before->count && i < after->count; i++) {
		long long delta = after->values[i] - before->values[i];
		if (delta != 0 || out != stdout) {
			fprintf(out, "%s,%s,%lld,%lld,%lld\n",
				label, before->names[i],
				before->values[i], after->values[i], delta);
		}
		if (delta != 0 && out != stdout) {
			printf("  [%s] %s: %lld -> %lld (delta=%lld)\n",
			       label, before->names[i],
			       before->values[i], after->values[i], delta);
		}
	}
}

/* ------------------------------------------------------------------ */
/*  Daemon counter snapshot via TCP                                   */
/* ------------------------------------------------------------------ */

static __attribute__((unused)) int request_daemon_snapshot(const char *daemon_ip, int daemon_port,
				   struct counter_snapshot *snap)
{
	int sock = socket(AF_INET, SOCK_STREAM, 0);
	if (sock < 0)
		return -1;

	struct sockaddr_in addr = {
		.sin_family = AF_INET,
		.sin_port = htons(daemon_port),
	};
	inet_pton(AF_INET, daemon_ip, &addr.sin_addr);

	if (connect(sock, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
		close(sock);
		return -1;
	}

	if (write(sock, "SNAPSHOT\n", 9) != 9) {
		close(sock);
		return -1;
	}

	char buf[4096] = {};
	int total = 0, n;
	while ((n = read(sock, buf + total, sizeof(buf) - total - 1)) > 0)
		total += n;
	buf[total] = '\0';
	close(sock);

	snap->count = 0;
	char *line = strtok(buf, "\n");
	while (line && snap->count < MAX_COUNTERS) {
		char name[64];
		long long val;
		if (sscanf(line, "%63[^,],%lld", name, &val) == 2) {
			snprintf(snap->names[snap->count],
				 sizeof(snap->names[snap->count]), "%s", name);
			snap->values[snap->count] = val;
			snap->count++;
		}
		line = strtok(NULL, "\n");
	}
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Background noise check                                            */
/* ------------------------------------------------------------------ */

static __attribute__((unused)) int verify_idle(void)
{
	struct counter_snapshot s1, s2;
	snapshot_local_counters(&s1);
	sleep(2);
	snapshot_local_counters(&s2);

	for (int i = 0; i < s1.count; i++) {
		if (s1.values[i] >= 0 && s2.values[i] >= 0 &&
		    s1.values[i] != s2.values[i]) {
			fprintf(stderr, "ERROR: background noise detected on %s "
				"(%lld -> %lld)\n",
				s1.names[i], s1.values[i], s2.values[i]);
			return -1;
		}
	}
	printf("Idle check passed.\n");
	return 0;
}

/* ------------------------------------------------------------------ */
/*  TCP helpers                                                       */
/* ------------------------------------------------------------------ */

static __attribute__((unused)) int tcp_connect(const char *ip, int port)
{
	int sock = socket(AF_INET, SOCK_STREAM, 0);
	if (sock < 0) {
		perror("socket");
		return -1;
	}

	int flag = 1;
	setsockopt(sock, IPPROTO_TCP, TCP_NODELAY, &flag, sizeof(flag));

	struct sockaddr_in addr = {
		.sin_family = AF_INET,
		.sin_port = htons(port),
	};
	inet_pton(AF_INET, ip, &addr.sin_addr);

	if (connect(sock, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
		perror("connect");
		close(sock);
		return -1;
	}
	return sock;
}

/* Listen on `port`, optionally bound to a specific local IP. bind_ip == NULL
 * (or empty) means INADDR_ANY, preserving the original behavior. Used by the
 * swap experiment so the responder can pin its control socket to one RDMA
 * subnet IP if desired; defaults stay wide-open.
 *
 * __attribute__((unused)): common.h is included by several .c files; not all of
 * them call both listen variants. The attribute suppresses -Wunused-function in
 * those units without forcing every translation unit to use both. */
static int tcp_listen_bind(int port, const char *bind_ip) __attribute__((unused));
static int tcp_listen_bind(int port, const char *bind_ip)
{
	int sock = socket(AF_INET, SOCK_STREAM, 0);
	if (sock < 0) {
		perror("socket");
		return -1;
	}
	int opt = 1;
	setsockopt(sock, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

	struct sockaddr_in addr = {
		.sin_family = AF_INET,
		.sin_addr.s_addr = INADDR_ANY,
		.sin_port = htons(port),
	};
	if (bind_ip && bind_ip[0] != '\0') {
		if (inet_pton(AF_INET, bind_ip, &addr.sin_addr) != 1) {
			fprintf(stderr, "tcp_listen_bind: bad bind IP '%s'\n",
				bind_ip);
			close(sock);
			return -1;
		}
	}

	if (bind(sock, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
		perror("bind");
		close(sock);
		return -1;
	}
	listen(sock, 1);
	return sock;
}

/* Back-compat wrapper (INADDR_ANY). Still called by multi_server.c. */
static int tcp_listen(int port) __attribute__((unused));
static int tcp_listen(int port)
{
	return tcp_listen_bind(port, NULL);
}

static int tcp_send_msg(int sock, const char *msg)
{
	char buf[256];
	int len = snprintf(buf, sizeof(buf), "%s\n", msg);
	return write(sock, buf, len);
}

static int tcp_recv_msg(int sock, char *buf, int buflen)
{
	int total = 0, n;
	while (total < buflen - 1) {
		n = read(sock, buf + total, 1);
		if (n <= 0)
			return -1;
		if (buf[total] == '\n') {
			buf[total] = '\0';
			return total;
		}
		total++;
	}
	buf[total] = '\0';
	return total;
}

static int tcp_exchange_qp_info(int sock, struct qp_info *local,
				struct qp_info *remote, int is_server)
{
	char buf[256];
	char gid_str[33];

	for (int i = 0; i < 16; i++)
		sprintf(gid_str + i * 2, "%02x", local->gid.raw[i]);

	snprintf(buf, sizeof(buf), "%u,%u,%u,%lu,%s",
		 local->qpn, local->psn, local->rkey,
		 (unsigned long)local->raddr, gid_str);

	if (is_server) {
		char rbuf[256];
		tcp_recv_msg(sock, rbuf, sizeof(rbuf));
		sscanf(rbuf, "%u,%u,%u,%lu,%32s",
		       &remote->qpn, &remote->psn, &remote->rkey,
		       (unsigned long *)&remote->raddr, gid_str);
		tcp_send_msg(sock, buf);
	} else {
		tcp_send_msg(sock, buf);
		char rbuf[256];
		tcp_recv_msg(sock, rbuf, sizeof(rbuf));
		sscanf(rbuf, "%u,%u,%u,%lu,%32s",
		       &remote->qpn, &remote->psn, &remote->rkey,
		       (unsigned long *)&remote->raddr, gid_str);
	}

	for (int i = 0; i < 16; i++) {
		unsigned int v;
		sscanf(gid_str + i * 2, "%02x", &v);
		remote->gid.raw[i] = v;
	}
	return 0;
}

/* ------------------------------------------------------------------ */
/*  RDMA resource bundle                                              */
/* ------------------------------------------------------------------ */

struct rdma_res {
	struct ibv_context *ctx;
	struct ibv_pd *pd;
	struct ibv_cq *cq;
	struct ibv_qp *qp;
	struct ibv_mr *mr;
	void *buf;
	size_t buf_size;
	int gid_index;

	struct qp_info local_info;
	struct qp_info remote_info;
};

static struct ibv_context *open_ib_device(const char *dev_name)
{
	int num;
	struct ibv_device **devs = ibv_get_device_list(&num);
	if (!devs || num == 0) {
		perror("ibv_get_device_list");
		return NULL;
	}

	struct ibv_context *ctx = NULL;

	/* 1st: exact name match (if dev_name given) */
	for (int i = 0; i < num; i++) {
		if (dev_name &&
		    strcmp(ibv_get_device_name(devs[i]), dev_name) == 0) {
			ctx = ibv_open_device(devs[i]);
			break;
		}
	}

	/* Fallback: first device whose port IB_PORT is ACTIVE.
	 * Device names differ across nodes (e.g. 224=mlx5_0 vs
	 * 225=rocep1s0f0 after udev predictable renaming), so don't
	 * rely on a hardcoded name. */
	for (int i = 0; i < num && !ctx; i++) {
		struct ibv_context *c = ibv_open_device(devs[i]);
		if (!c)
			continue;
		struct ibv_port_attr pattr;
		if (ibv_query_port(c, IB_PORT, &pattr) == 0 &&
		    pattr.state == IBV_PORT_ACTIVE) {
			fprintf(stderr,
				"[open_ib_device] '%s' not found; using '%s' (port ACTIVE)\n",
				dev_name ? dev_name : "(null)",
				ibv_get_device_name(devs[i]));
			ctx = c;
		} else {
			ibv_close_device(c);
		}
	}

	ibv_free_device_list(devs);
	return ctx;
}

static int setup_rdma(struct rdma_res *res, int use_send_recv,
		      int access_flags, int retry_cnt, int rnr_retry,
		      int timeout)
{
	(void)use_send_recv; /* reserved for future use; QP type is always RC */

	res->ctx = open_ib_device(IB_DEV_NAME);
	if (!res->ctx) {
		fprintf(stderr, "Failed to open device %s\n", IB_DEV_NAME);
		return -1;
	}

	res->pd = ibv_alloc_pd(res->ctx);
	if (!res->pd) {
		fprintf(stderr, "ibv_alloc_pd failed\n");
		return -1;
	}

	res->cq = ibv_create_cq(res->ctx, CQ_DEPTH, NULL, NULL, 0);
	if (!res->cq) {
		fprintf(stderr, "ibv_create_cq failed\n");
		return -1;
	}

	struct ibv_qp_init_attr qp_attr = {
		.send_cq = res->cq,
		.recv_cq = res->cq,
		.cap = {
			.max_send_wr = MAX_WR,
			.max_recv_wr = MAX_WR,
			.max_send_sge = MAX_SGE,
			.max_recv_sge = MAX_SGE,
		},
		.qp_type = IBV_QPT_RC,
	};

	res->qp = ibv_create_qp(res->pd, &qp_attr);
	if (!res->qp) {
		fprintf(stderr, "ibv_create_qp failed\n");
		return -1;
	}

	res->buf = calloc(1, BUF_SIZE);
	if (!res->buf)
		return -1;
	res->buf_size = BUF_SIZE;

	res->mr = ibv_reg_mr(res->pd, res->buf, MR_SIZE, access_flags);
	if (!res->mr) {
		fprintf(stderr, "ibv_reg_mr failed: %s\n", strerror(errno));
		return -1;
	}

	union ibv_gid gid;
	int gid_index = -1;
	for (int i = 0; i < 16; i++) {
		union ibv_gid g;
		if (ibv_query_gid(res->ctx, IB_PORT, i, &g))
			break;
		/* Look for RoCEv2 IPv4-mapped GID (::ffff:x.x.x.x) */
		if (g.raw[0] == 0 && g.raw[10] == 0xff && g.raw[11] == 0xff &&
		    (g.raw[12] != 0 || g.raw[13] != 0)) {
			gid_index = i;
			gid = g;
			break;
		}
	}
	if (gid_index < 0) {
		fprintf(stderr, "No valid RoCEv2 GID found\n");
		return -1;
	}
	fprintf(stderr, "[setup] Using GID index %d\n", gid_index);
	res->gid_index = gid_index;

	res->local_info.qpn = res->qp->qp_num;
	res->local_info.psn = rand() & 0xFFFFFF;
	res->local_info.rkey = res->mr->rkey;
	res->local_info.raddr = (uint64_t)res->buf;
	res->local_info.gid = gid;

	return 0;
}

static int modify_qp_to_init(struct ibv_qp *qp, int remote_write)
{
	int flags = IBV_ACCESS_LOCAL_WRITE;
	if (remote_write)
		flags |= IBV_ACCESS_REMOTE_WRITE | IBV_ACCESS_REMOTE_READ;

	struct ibv_qp_attr attr = {
		.qp_state = IBV_QPS_INIT,
		.pkey_index = 0,
		.port_num = IB_PORT,
		.qp_access_flags = flags,
	};
	return ibv_modify_qp(qp, &attr,
			     IBV_QP_STATE | IBV_QP_PKEY_INDEX |
			     IBV_QP_PORT | IBV_QP_ACCESS_FLAGS);
}

static int modify_qp_to_rtr(struct ibv_qp *qp, struct qp_info *remote,
			    int sgid_index)
{
	struct ibv_qp_attr attr = {
		.qp_state = IBV_QPS_RTR,
		.path_mtu = IBV_MTU_1024,
		.dest_qp_num = remote->qpn,
		.rq_psn = remote->psn,
		.max_dest_rd_atomic = 1,
		.min_rnr_timer = 12,
		.ah_attr = {
			.is_global = 1,
			.port_num = IB_PORT,
			.grh = {
				.dgid = remote->gid,
				.sgid_index = sgid_index,
				.hop_limit = 1,
			},
		},
	};
	return ibv_modify_qp(qp, &attr,
			     IBV_QP_STATE | IBV_QP_AV | IBV_QP_PATH_MTU |
			     IBV_QP_DEST_QPN | IBV_QP_RQ_PSN |
			     IBV_QP_MAX_DEST_RD_ATOMIC | IBV_QP_MIN_RNR_TIMER);
}

static int modify_qp_to_rts(struct ibv_qp *qp, uint32_t psn,
			     int retry_cnt, int rnr_retry, int timeout)
{
	struct ibv_qp_attr attr = {
		.qp_state = IBV_QPS_RTS,
		.sq_psn = psn,
		.timeout = timeout,
		.retry_cnt = retry_cnt,
		.rnr_retry = rnr_retry,
		.max_rd_atomic = 1,
	};
	return ibv_modify_qp(qp, &attr,
			     IBV_QP_STATE | IBV_QP_SQ_PSN | IBV_QP_TIMEOUT |
			     IBV_QP_RETRY_CNT | IBV_QP_RNR_RETRY |
			     IBV_QP_MAX_QP_RD_ATOMIC);
}

static int connect_qp(struct rdma_res *res, int remote_write,
		       int retry_cnt, int rnr_retry, int timeout)
{
	if (modify_qp_to_init(res->qp, remote_write)) {
		fprintf(stderr, "modify_qp_to_init failed: %s\n", strerror(errno));
		return -1;
	}
	if (modify_qp_to_rtr(res->qp, &res->remote_info, res->gid_index)) {
		fprintf(stderr, "modify_qp_to_rtr failed: %s\n", strerror(errno));
		return -1;
	}
	if (modify_qp_to_rts(res->qp, res->local_info.psn,
			     retry_cnt, rnr_retry, timeout)) {
		fprintf(stderr, "modify_qp_to_rts failed: %s\n", strerror(errno));
		return -1;
	}
	return 0;
}

static void cleanup_rdma(struct rdma_res *res)
{
	if (res->qp) ibv_destroy_qp(res->qp);
	if (res->mr) ibv_dereg_mr(res->mr);
	if (res->cq) ibv_destroy_cq(res->cq);
	if (res->pd) ibv_dealloc_pd(res->pd);
	if (res->ctx) ibv_close_device(res->ctx);
	free(res->buf);
	memset(res, 0, sizeof(*res));
}

/* ------------------------------------------------------------------ */
/*  RDMA post helpers                                                 */
/* ------------------------------------------------------------------ */

static __attribute__((unused)) int post_rdma_write(struct rdma_res *res, struct ibv_sge *custom_sge)
{
	struct ibv_sge sge;
	if (custom_sge) {
		sge = *custom_sge;
	} else {
		sge.addr = (uint64_t)res->buf;
		sge.length = 64;
		sge.lkey = res->mr->lkey;
	}

	struct ibv_send_wr wr = {
		.wr_id = 1,
		.sg_list = &sge,
		.num_sge = 1,
		.opcode = IBV_WR_RDMA_WRITE,
		.send_flags = IBV_SEND_SIGNALED,
		.wr.rdma = {
			.remote_addr = res->remote_info.raddr,
			.rkey = res->remote_info.rkey,
		},
	};
	struct ibv_send_wr *bad;
	return ibv_post_send(res->qp, &wr, &bad);
}

static __attribute__((unused)) int post_send(struct rdma_res *res)
{
	struct ibv_sge sge = {
		.addr = (uint64_t)res->buf,
		.length = 64,
		.lkey = res->mr->lkey,
	};
	struct ibv_send_wr wr = {
		.wr_id = 1,
		.sg_list = &sge,
		.num_sge = 1,
		.opcode = IBV_WR_SEND,
		.send_flags = IBV_SEND_SIGNALED,
	};
	struct ibv_send_wr *bad;
	return ibv_post_send(res->qp, &wr, &bad);
}

static __attribute__((unused)) int post_recv(struct rdma_res *res)
{
	struct ibv_sge sge = {
		.addr = (uint64_t)res->buf,
		.length = BUF_SIZE,
		.lkey = res->mr->lkey,
	};
	struct ibv_recv_wr wr = {
		.wr_id = 2,
		.sg_list = &sge,
		.num_sge = 1,
	};
	struct ibv_recv_wr *bad;
	return ibv_post_recv(res->qp, &wr, &bad);
}

static __attribute__((unused)) int poll_cq_block(struct ibv_cq *cq, struct ibv_wc *wc, int timeout_ms)
{
	struct timespec start, now;
	clock_gettime(CLOCK_MONOTONIC, &start);

	while (1) {
		int n = ibv_poll_cq(cq, 1, wc);
		if (n > 0)
			return n;
		if (n < 0)
			return n;

		clock_gettime(CLOCK_MONOTONIC, &now);
		long elapsed_ms = (now.tv_sec - start.tv_sec) * 1000 +
				  (now.tv_nsec - start.tv_nsec) / 1000000;
		if (timeout_ms > 0 && elapsed_ms > timeout_ms)
			return 0;
	}
}

/* ------------------------------------------------------------------ */
/*  Timing helper                                                     */
/* ------------------------------------------------------------------ */

static __attribute__((unused)) double elapsed_us(struct timespec *start, struct timespec *end)
{
	return (end->tv_sec - start->tv_sec) * 1e6 +
	       (end->tv_nsec - start->tv_nsec) / 1e3;
}

#endif /* COMMON_H */
