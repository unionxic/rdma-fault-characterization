/*
 * common.h - Shared definitions for RDMA fault detection latency experiment
 *
 * Part of: GPU-Initiated RDMA Fault Recovery Research
 * Experiment 1: CPU-mediated fault detection baseline latency
 *
 * This file defines constants, message formats, and utility functions
 * shared between the client (Server A) and server (Server B).
 */

#ifndef COMMON_H
#define COMMON_H

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <errno.h>
#include <unistd.h>
#include <time.h>
#include <signal.h>
#include <getopt.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <math.h>

/* ----------------------------------------------------------------
 * Constants
 * ---------------------------------------------------------------- */

/* RDMA buffer size for write operations */
#define RDMA_BUF_SIZE           4096

/* Signal every Nth WR to avoid CQ overflow while keeping polling responsive */
#define SIGNAL_INTERVAL         32

/* Maximum number of outstanding (unsignaled) WRs before we must poll */
#define MAX_SEND_WR             256

/* Maximum CQ entries */
#define MAX_CQ_ENTRIES          512

/* Default number of iterations per fault scenario */
#define DEFAULT_ITERATIONS      100

/* Default TCP control port */
#define DEFAULT_CTRL_PORT       18515

/* Default IB device name */
#define DEFAULT_DEV_NAME        "mlx5_0"

/* Default IB port */
#define DEFAULT_IB_PORT         1

/* Default GID index for RoCEv2 */
#define DEFAULT_GID_INDEX       3

/* Warm-up WRs before measurement begins */
#define WARMUP_COUNT            1000

/* Time to wait after link-up before retrying (seconds) */
#define LINK_UP_SETTLE_SEC      10

/* Maximum time to wait for error CQE (seconds) */
#define ERROR_DETECT_TIMEOUT_SEC 30

/* TCP recv/send timeout (seconds) */
#define TCP_TIMEOUT_SEC         60

/* ----------------------------------------------------------------
 * Control channel message types
 * ---------------------------------------------------------------- */

typedef enum {
    MSG_EXCHANGE_QP_INFO = 1,   /* Exchange QP parameters for connection setup */
    MSG_READY            = 2,   /* Both sides ready, baseline can begin */
    MSG_INJECT_NOW       = 3,   /* Client tells server to inject fault NOW */
    MSG_INJECT_ACK       = 4,   /* Server acknowledges fault was injected */
    MSG_RESET            = 5,   /* Reset for next iteration */
    MSG_RESET_ACK        = 6,   /* Reset acknowledged */
    MSG_DONE             = 7,   /* All iterations complete, shut down */
    MSG_LINK_DOWN_CMD    = 8,   /* Command to bring link down (scenario C) */
    MSG_LINK_UP_CMD      = 9,   /* Command to bring link back up */
    MSG_LINK_UP_ACK      = 10,  /* Link is back up and active */
    MSG_ERROR            = 99,  /* Error occurred */
} ctrl_msg_type_t;

/* Fault scenario types */
typedef enum {
    FAULT_QP_ERR     = 0,   /* (a) Transition remote QP to IBV_QPS_ERR */
    FAULT_KILL       = 1,   /* (b) Kill remote process */
    FAULT_LINK_DOWN  = 2,   /* (c) Bring remote link down */
    FAULT_NUM_TYPES  = 3,
} fault_type_t;

static const char *fault_type_names[]
    __attribute__((unused)) = {
    "QP_TO_ERR",
    "KILL_PROCESS",
    "LINK_DOWN",
};

/* ----------------------------------------------------------------
 * Control channel message structure
 * ---------------------------------------------------------------- */

/* QP info exchanged over TCP for manual QP setup (RoCE: GID-based) */
typedef struct {
    uint32_t qpn;               /* Queue Pair Number */
    uint32_t psn;               /* Packet Sequence Number */
    uint64_t addr;              /* Remote buffer virtual address */
    uint32_t rkey;              /* Remote memory region key */
    uint8_t  gid[16];           /* GID (for RoCE, this is the IPv6/IPv4-mapped addr) */
} qp_info_t;

/* Control message sent over TCP */
typedef struct {
    uint32_t        type;       /* ctrl_msg_type_t */
    uint32_t        fault_type; /* fault_type_t, valid for MSG_INJECT_NOW */
    uint64_t        timestamp_ns; /* nanosecond timestamp (CLOCK_MONOTONIC on sender) */
    qp_info_t       qp_info;   /* valid for MSG_EXCHANGE_QP_INFO */
    uint32_t        iteration;  /* current iteration number */
    uint32_t        padding;    /* alignment */
} ctrl_msg_t;

/* ----------------------------------------------------------------
 * Timing utilities
 * ---------------------------------------------------------------- */

static inline uint64_t get_time_ns(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
}

static inline double ns_to_us(uint64_t ns)
{
    return (double)ns / 1000.0;
}

static inline double ns_to_ms(uint64_t ns)
{
    return (double)ns / 1000000.0;
}

/* ----------------------------------------------------------------
 * TCP control channel helpers
 * ---------------------------------------------------------------- */

/*
 * Send exactly `len` bytes over a socket.
 * Returns 0 on success, -1 on error.
 */
static inline int tcp_send_exact(int sockfd, const void *buf, size_t len)
{
    const uint8_t *p = (const uint8_t *)buf;
    size_t sent = 0;
    while (sent < len) {
        ssize_t n = send(sockfd, p + sent, len - sent, MSG_NOSIGNAL);
        if (n <= 0) {
            if (n < 0 && errno == EINTR)
                continue;
            return -1;
        }
        sent += (size_t)n;
    }
    return 0;
}

/*
 * Receive exactly `len` bytes from a socket.
 * Returns 0 on success, -1 on error/EOF.
 */
static inline int tcp_recv_exact(int sockfd, void *buf, size_t len)
{
    uint8_t *p = (uint8_t *)buf;
    size_t recvd = 0;
    while (recvd < len) {
        ssize_t n = recv(sockfd, p + recvd, len - recvd, 0);
        if (n <= 0) {
            if (n < 0 && errno == EINTR)
                continue;
            return -1;
        }
        recvd += (size_t)n;
    }
    return 0;
}

static inline int send_ctrl_msg(int sockfd, const ctrl_msg_t *msg)
{
    return tcp_send_exact(sockfd, msg, sizeof(*msg));
}

static inline int recv_ctrl_msg(int sockfd, ctrl_msg_t *msg)
{
    return tcp_recv_exact(sockfd, msg, sizeof(*msg));
}

/* ----------------------------------------------------------------
 * Logging macros
 * ---------------------------------------------------------------- */

#define LOG_INFO(fmt, ...) \
    fprintf(stderr, "[INFO ] %s:%d: " fmt "\n", __FILE__, __LINE__, ##__VA_ARGS__)

#define LOG_WARN(fmt, ...) \
    fprintf(stderr, "[WARN ] %s:%d: " fmt "\n", __FILE__, __LINE__, ##__VA_ARGS__)

#define LOG_ERR(fmt, ...) \
    fprintf(stderr, "[ERROR] %s:%d: " fmt "\n", __FILE__, __LINE__, ##__VA_ARGS__)

#define LOG_FATAL(fmt, ...) do { \
    fprintf(stderr, "[FATAL] %s:%d: " fmt "\n", __FILE__, __LINE__, ##__VA_ARGS__); \
    exit(EXIT_FAILURE); \
} while (0)

/* Check a condition and log + return on failure */
#define CHECK(cond, fmt, ...) do { \
    if (!(cond)) { \
        LOG_ERR("CHECK failed: " fmt, ##__VA_ARGS__); \
        return -1; \
    } \
} while (0)

/* ----------------------------------------------------------------
 * GID formatting utility
 * ---------------------------------------------------------------- */

static inline void gid_to_str(const union ibv_gid *gid, char *buf, size_t len)
{
    /* Format as IPv6-style colon-separated hex */
    snprintf(buf, len,
             "%02x%02x:%02x%02x:%02x%02x:%02x%02x:"
             "%02x%02x:%02x%02x:%02x%02x:%02x%02x",
             gid->raw[0],  gid->raw[1],  gid->raw[2],  gid->raw[3],
             gid->raw[4],  gid->raw[5],  gid->raw[6],  gid->raw[7],
             gid->raw[8],  gid->raw[9],  gid->raw[10], gid->raw[11],
             gid->raw[12], gid->raw[13], gid->raw[14], gid->raw[15]);
}

#endif /* COMMON_H */
