#ifndef MULTI_COMMON_H
#define MULTI_COMMON_H

/*
 * multi_common.h -- Extended definitions for multi-WR / multi-QP
 * fault injection experiments.
 *
 * Supplements common.h (which is included first by multi_client.c).
 * Keeps common.h pristine for the single-WR experiment.
 */

#include "common.h"

/* ------------------------------------------------------------------ */
/*  Multi-experiment parameters                                       */
/* ------------------------------------------------------------------ */

#define MULTI_WR_COUNT        8     /* normal WRs before faulty WR    */
#define LARGE_BUF_SIZE        (256 * 1024)   /* 256 KB                */
#define MULTI_QP_COUNT        4
#define MULTI_CQ_DEPTH        64    /* enough for multi-WR + flush    */
#define MULTI_MAX_WR          32
#define MULTI_MAX_CQE         64    /* drain limit per poll loop      */

/* ------------------------------------------------------------------ */
/*  New TCP commands (server must implement these)                    */
/* ------------------------------------------------------------------ */

/*
 * SERVER PROTOCOL SPECIFICATION FOR MULTI-CLIENT
 * ================================================
 *
 * The multi_client uses the same TCP control socket as the original
 * client.  All existing commands (SETUP, CLEANUP, INJECT, SHUTDOWN, etc.)
 * remain unchanged.  The following NEW commands are added:
 *
 * 1. SETUP_MULTI_QP <count>
 *    ----------------------------------------------------------
 *    Client sends: "SETUP_MULTI_QP 4\n"
 *    Server action:
 *      - Allocate one ibv_context, one PD (reuse if exists).
 *      - Create <count> CQs and QPs (RC, with remote write).
 *      - Register a single MR (BUF_SIZE=4096) shared by all QPs.
 *      - For each QP i (0..count-1):
 *          - Exchange QP info via tcp_exchange_qp_info(conn, &local[i],
 *            &remote[i], is_server=1)   [one exchange per QP, in order]
 *          - Connect QP to RTS (retry_cnt=7, rnr_retry=7, timeout=14).
 *      - Send "READY\n" after all QPs are connected.
 *    Cleanup:
 *      - On CLEANUP command, destroy all <count> QPs, CQs, deregister
 *        MR, dealloc PD, close context.
 *
 * 2. SETUP_LARGE <buf_size>
 *    ----------------------------------------------------------
 *    Client sends: "SETUP_LARGE 262144\n"
 *    Server action:
 *      - Allocate buffer of <buf_size> bytes (e.g. 256KB).
 *      - Register MR over the full buffer with LOCAL_WRITE |
 *        REMOTE_WRITE | REMOTE_READ.
 *      - Create a single QP (RC) and CQ (depth=16 is fine).
 *      - Exchange QP info as usual (one exchange).
 *      - Connect QP to RTS (retry_cnt=7, rnr_retry=7, timeout=14).
 *      - Send "READY\n".
 *    The raddr/rkey exchanged must cover the full <buf_size> MR.
 *
 * 3. SETUP_LARGE_NOREMOTE <buf_size>
 *    ----------------------------------------------------------
 *    Same as SETUP_LARGE but MR registered with LOCAL_WRITE only
 *    (no REMOTE_WRITE).  Used for REM_INV_REQ with large messages.
 *
 * 4. SETUP_MULTI_QP_SEND <count>
 *    ----------------------------------------------------------
 *    Same as SETUP_MULTI_QP but QPs set up for SEND/RECV (no
 *    remote write).  Used for RNR_RETRY_EXC multi-QP test.
 *    No recv WQEs posted (so SEND will get RNR NAK).
 *
 * 5. INJECT_QP <qp_index> <scenario_id>
 *    ----------------------------------------------------------
 *    Client sends: "INJECT_QP 0 8\n"
 *    Server action:
 *      - Apply injection to QP[qp_index] only.
 *      - For RETRY_EXC_QP_ERR: ibv_modify_qp(qp[qp_index], ERR).
 *      - Send "DONE\n".
 *
 * All other existing commands (SNAPSHOT, QUERY_STATE, etc.) work
 * unchanged.
 */

#define CMD_SETUP_MULTI_QP      "SETUP_MULTI_QP"
#define CMD_SETUP_LARGE         "SETUP_LARGE"
#define CMD_SETUP_LARGE_NOREMOTE "SETUP_LARGE_NOREMOTE"
#define CMD_SETUP_MULTI_QP_SEND "SETUP_MULTI_QP_SEND"
#define CMD_INJECT_QP           "INJECT_QP"

/* ------------------------------------------------------------------ */
/*  Condition identifiers                                             */
/* ------------------------------------------------------------------ */

enum multi_condition {
	COND_A_MULTI_WR   = 0,   /* multiple WRs in flight          */
	COND_B_LARGE_MSG  = 1,   /* single large (multi-packet) WR  */
	COND_C_MULTI_QP   = 2,   /* multiple QPs, fault on one      */
	COND_MAX          = 3,
};

static const char *condition_names[] = {
	[COND_A_MULTI_WR]  = "MULTI_WR",
	[COND_B_LARGE_MSG] = "LARGE_MSG",
	[COND_C_MULTI_QP]  = "MULTI_QP",
};

/* ------------------------------------------------------------------ */
/*  Extended RDMA resource bundle for multi-QP                        */
/* ------------------------------------------------------------------ */

struct multi_qp_res {
	struct ibv_context *ctx;
	struct ibv_pd      *pd;
	struct ibv_cq      *cq[MULTI_QP_COUNT];
	struct ibv_qp      *qp[MULTI_QP_COUNT];
	struct ibv_mr      *mr;
	void               *buf;
	size_t              buf_size;
	int                 gid_index;
	int                 qp_count;

	struct qp_info      local_info[MULTI_QP_COUNT];
	struct qp_info      remote_info[MULTI_QP_COUNT];
};

/* ------------------------------------------------------------------ */
/*  Large-buffer RDMA resource                                        */
/* ------------------------------------------------------------------ */

struct large_rdma_res {
	struct ibv_context *ctx;
	struct ibv_pd      *pd;
	struct ibv_cq      *cq;
	struct ibv_qp      *qp;
	struct ibv_mr      *mr;
	void               *buf;
	size_t              buf_size;
	int                 gid_index;

	struct qp_info      local_info;
	struct qp_info      remote_info;
};

/* ------------------------------------------------------------------ */
/*  Multi-CQE drain helper                                            */
/* ------------------------------------------------------------------ */

/*
 * Drain all CQEs from a CQ.  Returns total count polled.
 * Fills wc_out (up to max_wc entries).  Does not block -- returns
 * immediately when CQ is empty or timeout_ms elapses.
 */
static int drain_cq(struct ibv_cq *cq, struct ibv_wc *wc_out,
		     int max_wc, int timeout_ms)
{
	struct timespec start, now;
	clock_gettime(CLOCK_MONOTONIC, &start);
	int total = 0;

	while (total < max_wc) {
		int n = ibv_poll_cq(cq, max_wc - total, wc_out + total);
		if (n < 0) {
			fprintf(stderr, "ibv_poll_cq error: %d\n", n);
			return n;
		}
		if (n > 0) {
			total += n;
			/* Reset timeout on each successful poll */
			clock_gettime(CLOCK_MONOTONIC, &start);
			continue;
		}

		/* n == 0: check timeout */
		clock_gettime(CLOCK_MONOTONIC, &now);
		long elapsed_ms = (now.tv_sec - start.tv_sec) * 1000 +
				  (now.tv_nsec - start.tv_nsec) / 1000000;
		if (elapsed_ms > timeout_ms)
			break;
	}
	return total;
}

/* ------------------------------------------------------------------ */
/*  WC status classifier                                              */
/* ------------------------------------------------------------------ */

static void classify_wc_array(const struct ibv_wc *wc, int count,
			       int *n_success, int *n_flush,
			       int *n_error, uint32_t *first_vendor_err,
			       int *first_error_status)
{
	*n_success = 0;
	*n_flush = 0;
	*n_error = 0;
	*first_vendor_err = 0;
	*first_error_status = -1;

	for (int i = 0; i < count; i++) {
		if (wc[i].status == IBV_WC_SUCCESS) {
			(*n_success)++;
		} else if (wc[i].status == IBV_WC_WR_FLUSH_ERR) {
			(*n_flush)++;
		} else {
			if (*n_error == 0) {
				*first_vendor_err = wc[i].vendor_err;
				*first_error_status = wc[i].status;
			}
			(*n_error)++;
		}
	}
}

#endif /* MULTI_COMMON_H */
