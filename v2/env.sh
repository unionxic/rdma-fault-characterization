#!/bin/bash
# Per-host runtime environment for both libraries; mpirun starts every rank through this.
# RR_ROOT=$HOME/rdma-recovery/base selects the unmodified builds (LD_LIBRARY_PATH wins over the binaries' RUNPATH).
R=${RR_ROOT:-$HOME/rdma-recovery}
export PATH=/usr/local/cuda/bin:$HOME/opt/openmpi-4.1.8/bin:$PATH
export LD_LIBRARY_PATH=$HOME/opt/gdrcopy/lib:$R/nccl/build/lib:$R/nvshmem/build/src/lib:/usr/local/cuda/lib64:$HOME/opt/openmpi-4.1.8/lib:$LD_LIBRARY_PATH
exec "$@"
