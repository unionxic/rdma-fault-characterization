/*
 * rdv.h - blind-apps: the verified 2-node rendezvous shared by the two bootstrap shims (gin_boot.cc, nvs_boot.cc).
 *
 * It only moves one opaque 128-byte unique ID (ncclUniqueId or nvshmemx_uniqueid_t) from rank 0 to the other ranks,
 * replacing the MPI_Bcast of the official examples' MPI build. The example code itself is not changed.
 *
 * Environment (set by blindrun.py for every rank):
 *   BLIND_RANK, BLIND_NRANKS   this rank and the number of ranks
 *   BLIND_RDV_ADDR             rank 0's management address (rank 0 binds it, the others connect to it)
 *   BLIND_RDV_PORT             a port below 32768 that the runner found free on both nodes
 *   BLIND_RDV_NONCE            16 hex digits, a fresh random value per trial
 *
 * Protocol (the same rule as gin-peer's verified rendezvous): rank 0 greets every connection with 16 bytes
 * "BLNDRDV1" + nonce; a connecting rank sends nothing before it has read that greeting with the right nonce
 * (otherwise it closes and retries after 200 ms), then sends its rank and the nonce (12 bytes) and reads the ID.
 * Rank 0 drops any connection that does not answer with a valid rank and the nonce. Bounded: 60 s.
 */
#ifndef BLIND_RDV_H_
#define BLIND_RDV_H_

#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#define BLIND_RDV_ID_BYTES 128
#define BLIND_RDV_TIMEOUT_S 60.0

static double blind_rdv_now(void) {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return t.tv_sec + t.tv_nsec * 1e-9;
}

static int blind_rdv_env_int(const char* k, int dflt) {
  const char* v = getenv(k);
  return (v && *v) ? atoi(v) : dflt;
}

static void blind_rdv_die(const char* what) {
  fprintf(stderr, "[blind-boot] rendezvous failed: %s (errno %d)\n", what, errno);
  fflush(stderr);
  exit(3);
}

/* full read/write with a deadline; 0 on success */
static int blind_rdv_io(int fd, void* buf, size_t n, int wr, double deadline) {
  char* p = (char*)buf;
  while (n > 0) {
    double left = deadline - blind_rdv_now();
    if (left <= 0) return -1;
    struct pollfd q;
    q.fd = fd;
    q.events = wr ? POLLOUT : POLLIN;
    q.revents = 0;
    int r = poll(&q, 1, (int)(left * 1000) + 1);
    if (r < 0 && errno == EINTR) continue;
    if (r <= 0) return -1;
    ssize_t k = wr ? send(fd, p, n, MSG_NOSIGNAL) : recv(fd, p, n, 0);
    if (k < 0 && (errno == EINTR || errno == EAGAIN)) continue;
    if (k <= 0) return -1;
    p += k;
    n -= (size_t)k;
  }
  return 0;
}

static void blind_rdv_nonce(unsigned char out[8]) {
  const char* s = getenv("BLIND_RDV_NONCE");
  if (!s || strlen(s) != 16) blind_rdv_die("BLIND_RDV_NONCE must be 16 hex digits");
  for (int i = 0; i < 8; i++) {
    unsigned v;
    if (sscanf(s + 2 * i, "%2x", &v) != 1) blind_rdv_die("BLIND_RDV_NONCE is not hex");
    out[i] = (unsigned char)v;
  }
}

/* Broadcast `id` (BLIND_RDV_ID_BYTES) from rank 0 to every other rank. */
static void blind_rdv_bcast(void* id) {
  const int rank = blind_rdv_env_int("BLIND_RANK", -1);
  const int nranks = blind_rdv_env_int("BLIND_NRANKS", -1);
  const int port = blind_rdv_env_int("BLIND_RDV_PORT", -1);
  const char* addr = getenv("BLIND_RDV_ADDR");
  if (rank < 0 || nranks < 1 || rank >= nranks || port <= 0 || port > 65535 || !addr)
    blind_rdv_die("BLIND_RANK, BLIND_NRANKS, BLIND_RDV_ADDR and BLIND_RDV_PORT must be set");
  if (nranks == 1) return;
  unsigned char nonce[8];
  blind_rdv_nonce(nonce);
  unsigned char greet[16];
  memcpy(greet, "BLNDRDV1", 8);
  memcpy(greet + 8, nonce, 8);
  struct sockaddr_in sa;
  memset(&sa, 0, sizeof(sa));
  sa.sin_family = AF_INET;
  sa.sin_port = htons((uint16_t)port);
  if (inet_pton(AF_INET, addr, &sa.sin_addr) != 1) blind_rdv_die("BLIND_RDV_ADDR is not an IPv4 address");
  const double deadline = blind_rdv_now() + BLIND_RDV_TIMEOUT_S;
  if (rank == 0) {
    int ls = socket(AF_INET, SOCK_STREAM, 0);
    int one = 1;
    if (ls < 0 || setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one)) != 0 ||
        bind(ls, (struct sockaddr*)&sa, sizeof(sa)) != 0 || listen(ls, 16) != 0)
      blind_rdv_die("cannot listen on BLIND_RDV_ADDR:BLIND_RDV_PORT");
    int served = 0, rejected = 0;
    while (served < nranks - 1) {
      double left = deadline - blind_rdv_now();
      if (left <= 0) blind_rdv_die("timeout waiting for the other ranks");
      struct pollfd q;
      q.fd = ls;
      q.events = POLLIN;
      q.revents = 0;
      if (poll(&q, 1, (int)(left * 1000) + 1) <= 0) continue;
      int c = accept(ls, NULL, NULL);
      if (c < 0) continue;
      unsigned char hello[12];
      int32_t who = -1;
      double d = blind_rdv_now() + 5.0;
      if (d > deadline) d = deadline;
      if (blind_rdv_io(c, greet, sizeof(greet), 1, d) == 0 && blind_rdv_io(c, hello, sizeof(hello), 0, d) == 0 &&
          memcmp(hello + 4, nonce, 8) == 0) {
        memcpy(&who, hello, 4);
        if (who > 0 && who < nranks && blind_rdv_io(c, id, BLIND_RDV_ID_BYTES, 1, d) == 0) {
          served++;
          close(c);
          continue;
        }
      }
      rejected++;
      close(c);
    }
    close(ls);
    if (rejected) fprintf(stderr, "[blind-boot] rendezvous: %d connection(s) without the trial's nonce dropped\n", rejected);
    return;
  }
  for (;;) {
    if (blind_rdv_now() > deadline) blind_rdv_die("timeout connecting to rank 0");
    int c = socket(AF_INET, SOCK_STREAM, 0);
    if (c < 0) blind_rdv_die("socket");
    if (connect(c, (struct sockaddr*)&sa, sizeof(sa)) != 0) {
      close(c);
      usleep(200 * 1000);
      continue;
    }
    unsigned char g[16];
    double d = blind_rdv_now() + 2.0;
    if (d > deadline) d = deadline;
    /* read and check the greeting before sending anything */
    if (blind_rdv_io(c, g, sizeof(g), 0, d) != 0 || memcmp(g, greet, sizeof(g)) != 0) {
      close(c);
      usleep(200 * 1000);
      continue;
    }
    unsigned char hello[12];
    int32_t me = rank;
    memcpy(hello, &me, 4);
    memcpy(hello + 4, nonce, 8);
    d = blind_rdv_now() + 5.0;
    if (d > deadline) d = deadline;
    if (blind_rdv_io(c, hello, sizeof(hello), 1, d) != 0 || blind_rdv_io(c, id, BLIND_RDV_ID_BYTES, 0, d) != 0) {
      close(c);
      usleep(200 * 1000);
      continue;
    }
    close(c);
    return;
  }
}

#endif /* BLIND_RDV_H_ */
