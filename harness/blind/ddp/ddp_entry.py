#!/usr/bin/env python3
"""ddp_entry.py - blind-apps DDP workload: run nanoGPT's train.py unchanged under DDP and report the final weights.

usage (blindrun.py sets the environment): python3.10 ddp_entry.py <nanoGPT>/train.py <train.py arguments ...>

The script itself (nanoGPT at a pinned commit, installed by install_venv.sh) is not modified. Before running it this
wrapper only sets what the oracle needs and what a launcher would set:
  - determinism: torch.use_deterministic_algorithms(True) (CUBLAS_WORKSPACE_CONFIG comes from the runner), cuDNN
    deterministic, and scaled-dot-product attention restricted to the math kernel (the flash and memory-efficient
    backward passes accumulate with atomics). nanoGPT seeds itself (1337 + rank) and draws its batches from that seed;
  - the collective timeout of the process group: init_process_group() gets timeout=BLIND_PG_TIMEOUT_S unless the
    script passes one (nanoGPT does not), the way a launcher configures it. The rendezvous is env://
    (RANK, LOCAL_RANK, WORLD_SIZE, MASTER_ADDR, MASTER_PORT), one process per node, no torchrun agent;
  - after the script returns, a SHA-256 over every tensor of the trained model's state_dict (names sorted, raw bytes),
    printed as one line. With exactly-once delivery a recovered fault leaves these bytes equal to a fault-free run's.
Nothing here touches NCCL or the fault hooks; the runner loads the Stage 2 libnccl with LD_PRELOAD.
"""
import datetime
import hashlib
import os
import runpy
import sys

import torch
import torch.distributed as dist

torch.use_deterministic_algorithms(True)
torch.backends.cudnn.benchmark = False
torch.backends.cudnn.deterministic = True
torch.backends.cuda.enable_flash_sdp(False)
torch.backends.cuda.enable_mem_efficient_sdp(False)
torch.backends.cuda.enable_math_sdp(True)
if hasattr(torch.backends.cuda, "enable_cudnn_sdp"):
    torch.backends.cuda.enable_cudnn_sdp(False)

_timeout = datetime.timedelta(seconds=float(os.environ.get("BLIND_PG_TIMEOUT_S", "30")))
_init_process_group = dist.init_process_group


def _init_with_timeout(*args, **kwargs):
    kwargs.setdefault("timeout", _timeout)
    return _init_process_group(*args, **kwargs)


dist.init_process_group = _init_with_timeout  # train.py does `from torch.distributed import init_process_group`

script = os.path.abspath(sys.argv[1])
os.chdir(os.path.dirname(script))  # nanoGPT reads configurator.py, config/ and data/ relative to its directory
sys.path.insert(0, os.path.dirname(script))
sys.argv = sys.argv[1:]
g = runpy.run_path(script, run_name="__main__")

model = g.get("raw_model")
if model is None:
    print("[ddp-entry] no trained model to report", flush=True)
    sys.exit(4)
h = hashlib.sha256()
for name, t in sorted(model.state_dict().items()):
    h.update(name.encode())
    h.update(t.detach().to("cpu").contiguous().numpy().tobytes())
print("[ddp-entry] rank=%s final iter=%s parameters sha256=%s" % (os.environ.get("RANK"), g.get("iter_num"),
                                                                 h.hexdigest()), flush=True)
