/*
 * nvs_boot.cc - blind-apps: an NVSHMEM 3.8.0 bootstrap plugin for 2 nodes without MPI or a PMI launcher.
 *
 * The official examples call plain nvshmem_init(), whose default bootstrap is PMI (a launcher such as nvshmrun or
 * mpirun). With NVSHMEM_BOOTSTRAP=plugin and NVSHMEM_BOOTSTRAP_PLUGIN=<this .so>, nvshmem_init() calls this plugin
 * instead (src/host/bootstrap/bootstrap.cpp, bootstrap_loader.cpp). The plugin does what the library's own
 * unique-ID path does (nvshmemx_get_uniqueid + nvshmemx_init_attr(NVSHMEMX_INIT_WITH_UNIQUEID)) with NVSHMEM's own
 * UID bootstrap module (nvshmem_bootstrap_uid.so.3 of the same install):
 *   1. pre-init of the UID module (network discovery, its get_unique_id operation);
 *   2. rank 0 gets a unique ID; the 128 bytes go to the other ranks over the verified rendezvous of rdv.h;
 *   3. init of the UID module with {id, BLIND_RANK, BLIND_NRANKS}; it fills the bootstrap handle (allgather,
 *      alltoall, barrier, global_exit, finalize), which NVSHMEM then uses as usual.
 * The example sources are compiled unchanged. BLIND_NVS_UID_PLUGIN overrides the UID module's file name.
 */
#include <dlfcn.h>

#include "internal/bootstrap_host_transport/nvshmemi_bootstrap_defines.h"
#include "bootstrap_device_host/nvshmem_uniqueid.h"
#include "rdv.h"

static_assert(sizeof(nvshmemx_uniqueid_t) == BLIND_RDV_ID_BYTES, "nvshmemx_uniqueid_t must be 128 bytes");

typedef int (*blind_preinit_fn)(bootstrap_handle_t*, int);
typedef int (*blind_init_fn)(void*, bootstrap_handle_t*, int);

static void* blind_uid_lib = nullptr;
static blind_preinit_fn blind_uid_preinit = nullptr;
static blind_init_fn blind_uid_init = nullptr;

static int blind_load_uid(void) {
  if (blind_uid_lib) return 0;
  const char* name = getenv("BLIND_NVS_UID_PLUGIN");
  if (!name || !*name) name = "nvshmem_bootstrap_uid.so.3";
  blind_uid_lib = dlopen(name, RTLD_NOW | RTLD_LOCAL);
  if (!blind_uid_lib) {
    fprintf(stderr, "[blind-boot] cannot load %s: %s\n", name, dlerror());
    return -1;
  }
  blind_uid_preinit = (blind_preinit_fn)dlsym(blind_uid_lib, "nvshmemi_bootstrap_plugin_pre_init");
  blind_uid_init = (blind_init_fn)dlsym(blind_uid_lib, "nvshmemi_bootstrap_plugin_init");
  if (!blind_uid_preinit || !blind_uid_init) {
    fprintf(stderr, "[blind-boot] %s lacks the plugin entry points\n", name);
    return -1;
  }
  return 0;
}

extern "C" int nvshmemi_bootstrap_plugin_pre_init(bootstrap_handle_t* handle, const int abi_version) {
  if (blind_load_uid()) return -1;
  return blind_uid_preinit(handle, abi_version);
}

extern "C" int nvshmemi_bootstrap_plugin_init(void* arg, bootstrap_handle_t* handle, const int abi_version) {
  (void)arg;  // NULL in plugin mode
  if (blind_load_uid()) return -1;
  const int rank = blind_rdv_env_int("BLIND_RANK", -1);
  const int nranks = blind_rdv_env_int("BLIND_NRANKS", -1);
  if (rank < 0 || nranks < 1 || rank >= nranks) {
    fprintf(stderr, "[blind-boot] BLIND_RANK and BLIND_NRANKS must be set\n");
    return -1;
  }
  int status = blind_uid_preinit(handle, abi_version);
  if (status != 0 || handle->pre_init_ops == nullptr || handle->pre_init_ops->get_unique_id == nullptr) {
    fprintf(stderr, "[blind-boot] UID pre-init failed (%d)\n", status);
    return status ? status : -1;
  }
  nvshmemx_uniqueid_t id = NVSHMEMX_UNIQUEID_INITIALIZER;
  if (rank == 0) {
    status = handle->pre_init_ops->get_unique_id((void*)&id);
    if (status != 0) {
      fprintf(stderr, "[blind-boot] get_unique_id failed (%d)\n", status);
      return status;
    }
  }
  blind_rdv_bcast(&id);
  nvshmemx_uniqueid_args_t args = NVSHMEMX_UNIQUEID_ARGS_INITIALIZER;
  args.id = &id;
  args.myrank = rank;
  args.nranks = nranks;
  return blind_uid_init(&args, handle, abi_version);
}
