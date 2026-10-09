/*
 * gin_boot.cc - blind-apps: a 2-node bootstrap for the official NCCL 2.32.3 examples without MPI.
 *
 * The examples' MPI build gets the NCCL unique ID to every process with MPI_Bcast
 * (docs/examples/common/src/utils.cc, MPI_SUPPORT). This file is linked in place of that utils.cc and implements the
 * same two functions of docs/examples/common/include/utils.h with one process per node:
 *   util_broadcast()  moves the 128-byte ncclUniqueId from rank 0 over the verified rendezvous of rdv.h
 *   run_example()     reads this process's rank from the environment and calls the example function once, then prints
 *                     what the MPI build prints (the header line and, on rank 0, the final message)
 * The example sources (main.cu, kernels.cuh) are compiled unchanged. One GPU per node: the local device is 0
 * (BLIND_LOCAL_DEVICE overrides).
 */
#include "utils.h"
#include "rdv.h"

static_assert(sizeof(ncclUniqueId) == BLIND_RDV_ID_BYTES, "ncclUniqueId must be 128 bytes");

int util_broadcast(int root, int my_rank, ncclUniqueId* arg) {
  (void)my_rank;
  if (root != 0) {
    fprintf(stderr, "[blind-boot] util_broadcast: only root 0 is supported\n");
    return 1;
  }
  blind_rdv_bcast(arg);
  return 0;
}

int run_example(int argc, char* argv[], void* (*ncclExample)(int, int, int, int)) {
  (void)argc;
  (void)argv;
  const int rank = blind_rdv_env_int("BLIND_RANK", -1);
  const int nranks = blind_rdv_env_int("BLIND_NRANKS", -1);
  const int device = blind_rdv_env_int("BLIND_LOCAL_DEVICE", 0);
  if (rank < 0 || nranks < 1 || rank >= nranks) {
    printf("Failed to initialize backend\n");
    return 1;
  }
  if (rank == 0) {
    printf("NCCL Example: One Device per Process\n");
    printf("====================================\n");
  }
  fflush(stdout);
  if (ncclExample(rank, nranks, device, 1) != NULL) {
    printf("Failed to execute NCCL operations\n");
    return 1;
  }
  if (rank == 0) printf("\nAll NCCL communicators finalized successfully!\n");
  fflush(stdout);
  return 0;
}
