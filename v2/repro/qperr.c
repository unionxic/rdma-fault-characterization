// qperr.c: LD_PRELOAD fault injector for the "connection problem" class. It remembers every QP the process
// creates through mlx5dv_devx_obj_create and, QPERR_AFTER_MS after the first of them reaches RTS, moves all of
// them to the error state (2ERR_QP), as a local QP failure does. No library code is changed.
// env: QPERR_RANK (the MPI rank that injects; unset: off)  QPERR_AFTER_MS (default 1000)
// build: gcc -O2 -shared -fPIC -o libqperr.so qperr.c -ldl -lpthread
// NVSHMEM links libmlx5 and is caught by symbol interposition; NCCL loads it with dlopen + dlsym, so dlsym is
// wrapped too.
#define _GNU_SOURCE
#include <dlfcn.h>
#include <endian.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

struct mlx5dv_devx_obj;
struct ibv_context;
typedef struct mlx5dv_devx_obj *(*create_fn)(struct ibv_context *, const void *, size_t, void *, size_t);
typedef int (*modify_fn)(struct mlx5dv_devx_obj *, const void *, size_t, void *, size_t);

enum { CREATE_QP = 0x500, RTR2RTS_QP = 0x504, TO_ERR_QP = 0x507, MAXQP = 256 };
static create_fn real_create;
static modify_fn real_modify;
static struct { struct mlx5dv_devx_obj *obj; uint32_t qpn; } qps[MAXQP];
static int nqps, armed;
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;

static void *real_dlsym(void *h, const char *name) {
  static void *(*f)(void *, const char *);
  if (!f) f = (void *(*)(void *, const char *))dlvsym(RTLD_NEXT, "dlsym", "GLIBC_2.2.5");
  return f(h, name);
}

static int my_rank(void) {
  const char *want = getenv("QPERR_RANK"), *have = getenv("OMPI_COMM_WORLD_RANK");
  return want && have && !strcmp(want, have);
}

static void *inject(void *arg) {
  const char *ms = getenv("QPERR_AFTER_MS");
  usleep(1000 * (ms ? atoi(ms) : 1000));
  pthread_mutex_lock(&lock);
  for (int i = 0; i < nqps; i++) {
    uint8_t in[16] = {TO_ERR_QP >> 8, TO_ERR_QP & 0xff}, out[16] = {0};
    const uint32_t q = htobe32(qps[i].qpn);
    memcpy(in + 8, &q, 4);
    const int rc = real_modify(qps[i].obj, in, sizeof in, out, sizeof out);
    fprintf(stderr, "QPERR rank=%s qpn=%#x moved to ERR rc=%d\n", getenv("OMPI_COMM_WORLD_RANK"), qps[i].qpn, rc);
  }
  pthread_mutex_unlock(&lock);
  return arg;
}

static struct mlx5dv_devx_obj *wrap_create(struct ibv_context *c, const void *in, size_t inlen, void *out, size_t outlen) {
  struct mlx5dv_devx_obj *obj = real_create(c, in, inlen, out, outlen);
  if (obj && inlen >= 2 && outlen >= 12 && be16toh(*(const uint16_t *)in) == CREATE_QP && my_rank()) {
    pthread_mutex_lock(&lock);
    if (nqps < MAXQP) {
      qps[nqps].obj = obj;
      qps[nqps++].qpn = be32toh(*(const uint32_t *)((const char *)out + 8)) & 0xffffff;
    }
    pthread_mutex_unlock(&lock);
  }
  return obj;
}

static int wrap_modify(struct mlx5dv_devx_obj *obj, const void *in, size_t inlen, void *out, size_t outlen) {
  const int rc = real_modify(obj, in, inlen, out, outlen);
  if (!rc && inlen >= 2 && be16toh(*(const uint16_t *)in) == RTR2RTS_QP && my_rank() &&
      !__sync_lock_test_and_set(&armed, 1)) {
    pthread_t t;
    pthread_create(&t, NULL, inject, NULL);
    pthread_detach(t);
  }
  return rc;
}

// Direct callers (NVSHMEM). Its transport module is loaded with dlopen, so libmlx5 is not in the global
// scope that RTLD_NEXT searches: the real functions are taken from the library itself.
static void *mlx5_sym(const char *name) { return real_dlsym(dlopen("libmlx5.so.1", RTLD_NOW), name); }
struct mlx5dv_devx_obj *mlx5dv_devx_obj_create(struct ibv_context *c, const void *in, size_t inlen, void *out, size_t outlen) {
  if (!real_create) real_create = (create_fn)mlx5_sym("mlx5dv_devx_obj_create");
  return wrap_create(c, in, inlen, out, outlen);
}
int mlx5dv_devx_obj_modify(struct mlx5dv_devx_obj *obj, const void *in, size_t inlen, void *out, size_t outlen) {
  if (!real_modify) real_modify = (modify_fn)mlx5_sym("mlx5dv_devx_obj_modify");
  return wrap_modify(obj, in, inlen, out, outlen);
}

// Callers that look the two functions up with dlsym (NCCL's DOCA wrapper).
void *dlsym(void *h, const char *name) {
  void *p = real_dlsym(h, name);
  if (p && !strcmp(name, "mlx5dv_devx_obj_create")) { real_create = (create_fn)p; return (void *)wrap_create; }
  if (p && !strcmp(name, "mlx5dv_devx_obj_modify")) { real_modify = (modify_fn)p; return (void *)wrap_modify; }
  return p;
}
