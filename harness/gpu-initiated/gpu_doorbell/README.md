# GPU-rung doorbells (PeerMappingOverride=1): what changes

> **Since 2026-09-24 13:53 the override is permanent on both nodes** (the user's decision):
> `/etc/modprobe.d/nvidia-peermapping.conf` holds
> `options nvidia NVreg_RegistryDwords="PeerMappingOverride=1;" NVreg_EnableStreamMemOPs=1`,
> applied without a reboot by `apply_peermapping.sh` (one module reload; rain's mooncake_client
> and gdm restarted; CUDA checked on both nodes). The nvidia modules are not in the initramfs, so
> the file also applies at boot. From now on NVSHMEM's default NIC handler is the GPU; to
> reproduce the CPU-proxy results, set `NVSHMEM_IBGDA_NIC_HANDLER=cpu_host_memory`.

> **What the override relaxes (added 2026-09-25 after review).** `PeerMappingOverride=1` lets the
> nvidia driver map peer-device MMIO (here the NIC's UAR doorbell pages) into GPU address spaces
> without the admin-only checks it otherwise applies (`cudaHostRegister(..., IoMemory)` fails with
> error 800 for a non-root user without it). That is what GPU-rung doorbells need, and it is the
> documented requirement of NVSHMEM's GPU NIC handler, but it widens what any CUDA process on the
> node may map. Both nodes are shared (the user's gds-kv / NVMe-oF experiments run there); the
> user chose to keep it on. Results measured before 2026-09-24 13:53 ran without it (CPU-proxy
> doorbells) and results after it with it; every table in this repo that mixes the two now says
> which driver configuration each row used.

Every other result in `../` ran in the CPU-doorbell fallback: without
`NVreg_RegistryDwords="PeerMappingOverride=1;"` the NIC's UAR page cannot be mapped into the
GPU, so a CPU thread rings the doorbell while the GPU still builds the WQEs and polls a CQ in GPU
memory. Here the nvidia modules on both nodes were reloaded with the override for two short
windows (2026-09-24, 11:16-11:26 and 12:00-12:06) and the same binaries and runners were used.

## Procedure (`window.sh`, run under `../common/cluster_run.sh`)

1. Stop every GPU user on rain: the user's `mooncake_client` (command line, environment, cwd and
   log recorded first), two stale `nvidia-smi` monitors started 6 and 8 days earlier whose output
   files had been deleted (not restarted), their `hostmon.sh` parent, and the gdm greeter. sunny
   had no GPU user.
2. On both nodes: `rmmod` the nvidia stack, `modprobe nvidia NVreg_RegistryDwords='PeerMappingOverride=1;' NVreg_EnableStreamMemOPs=1`,
   then the rest of the stack (`/etc/modprobe.d` untouched). Check CUDA on both nodes.
3. Run `experiments.sh` (window 1) or `experiments2.sh` (window 2).
4. Restore from an EXIT trap: reload the stack with the original parameters, start gdm, restart
   `mooncake_client` with its original command line, environment, cwd and log. Verified after
   each window: `RegistryDwords: ""` on both nodes, CUDA OK on both, gdm active, `mooncake_client`
   serving on 30.0.0.3:50052 and re-registered with its master.

### Incidents

- **Window 1, sunny's CUDA broke after the reload.** The reload moved sunny's dynamic char-device
  majors: `nvidia-uvm` went to 511 while `/dev/nvidia-uvm` still pointed to 509, which
  `nvidia-fs` now owned (`nvfs_ioctl: Invalid IOCTL` in dmesg, "cuda failed with unknown error").
  Every NVSHMEM trial and the first five GIN trials of window 1 are invalid for that reason
  (listed below). The node was recreated with the right major mid-window; `window.sh` now checks
  CUDA on both nodes after the reload and restores without running if it fails.
- **The cluster lock stayed held after window 1.** `mooncake_client`, restarted from inside the
  locked run, inherited the lock's fd 9, so every later `cluster_run.sh` waited on it
  (11:26-12:00). Fixed without touching `mooncake_client`: `cluster_run.sh` now uses a new lock
  file and runs its command with fd 9 closed, and `window.sh` restarts `mooncake_client` with
  `9>&-`. After window 2 the old lock is free and `mooncake_client` holds no lock fd.

## Results

### NVSHMEM IBGDA with the GPU handler (window 2; log: "NIC handler will be GPU")

| fault | trials | error CQE in the collapsed slot | time to device detection |
|---|---|---|---|
| none | 2 | - (ok, data exact) | - |
| F2b invalid rkey | 3/3 | 0xd / syndrome 0x13 / vendor_err 0x88 (REM_ACCESS) | 8.7-9.9 ms |
| F1 local ERR | 3/3 | 0xd / 0x05 / 0xf5 (WR_FLUSH, head of queue) | 1.7-1.8 ms |
| F3 peer QP ERR | 3/3 | 0xd / 0x15 / 0x81 (RETRY_EXC) | 3.54-3.72 s |
| F2b, blocking `nvshmem_quiet` | 1 | 0xd / 0x05 / **0xf9** (the trailing signal's flush over-wrote the root cause) | quiet **returned success** |

With the CPU handler the same faults never produced an error CQE in any of the 1024 CQ entries
(`../nvshmem/`). **So NVSHMEM's missing error completions come from its CPU-proxy doorbell path,
not from the collapsed CQ or the QP/CQ context shared by both handlers.** The exact mechanism was
then found in `../nvshmem_rootcause/`: the CPU proxy writes the send producer index into the
receive word of the doorbell record, the GPU handler writes the send word. With the GPU handler
RETRY_EXC arrives after 3.5-3.7 s, as on CPU verbs. (The earlier "F3 leaves the QP in RTS" was
a measurement artifact of a lock-holding watch thread, see `../nvshmem_rootcause/`.) The blocking row shows the two predicted failure modes on
real IBGDA: the collapsed slot ends at the trailing flush 5/0xf9 (Q1), and the release build's
compiled-out assert lets `quiet` report success.

### NCCL GIN GDAKI with GPU doorbells (windows 1 and 2, valid trials only)

| run | result |
|---|---|
| Q4 classifier, F1 (ring 2, collapsed 1) | LOCAL_QP_ERR 5/0xf5, host API at 14.6-15.7 ms |
| Q4 classifier, F2 (ring 1, collapsed 1) | REM_ACCESS 10/0x88, host API at 3.8-4.3 ms |
| Q4 classifier, F3 (ring 2, collapsed 1) | RETRY_EXC 12/0x81, host API at 3.54-3.73 s |
| Q4 classifier, no fault (ring 2, collapsed 1) | ok, data exact |
| stock (classifier off), F1 blocking, 2 trials | initiator reports the failed write as done (init_silent_iters 1 in 2/2); host learns "QP in ERR" at 9.4 s |
| latency, no fault, 256 KiB put+signal+flush | median 36.74 µs (classifier off), 36.86 µs (on) |

The Q4 results match the CPU-doorbell ones (`../gin_q4/`) within noise, and stock GDAKI's silent
success is unchanged, so neither depends on the doorbell path. That GDAKI actually used the GPU
doorbell here is **inferred**: neither NCCL nor DOCA logs the doorbell mode, but the same
`cudaHostRegisterIoMemory` call that failed before succeeded for NVSHMEM in the same window, and
the median latency is about 0.6 µs lower than the CPU-doorbell 37.4 µs.

Possibly perturbed: window 2's NVSHMEM `F2b_timeout_t1` overlapped, from 12:01:04 to 12:01:19, a
short smoke run of the recovery work that had started on the old lock file (reported by that
agent). Its result is identical to t2 and t3.

Invalid (sunny's CUDA broken, window 1): all NVSHMEM trials in `results/20260924/nvshmem/`, and GIN
`ring_c1_none_timeout_t1/t2`, `ring_c1_F1_timeout_t1/t2`, `ring_c1_F2_timeout_t1` in
`results/20260924/gin_q4/`.

## Files

- `window.sh`: stop, reload with the override, check CUDA, run, restore (EXIT trap).
- `experiments.sh`, `experiments2.sh`: the runs of windows 1 and 2.
- `results/20260924/`, `results/20260924_w2/`: CSVs and per-trial logs.
- `results/window.log`: the dry run and both windows (stop, reload, CUDA check, restore).
