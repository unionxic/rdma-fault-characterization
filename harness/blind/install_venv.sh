#!/usr/bin/env bash
# install_venv.sh - the Python stack of the blind-apps DDP workload, under $BLIND_VENV (default ~/blind-venv) only.
# Nothing system-wide: no apt, no sudo, no change outside $BLIND_VENV (pip runs with --no-cache-dir).
#
#   py310/          a standalone CPython 3.10.15 (python-build-standalone 20241016, install_only, sha256-checked).
#                   The same interpreter is used on rain and sunny (rain's system Python is 3.8.10, sunny's 3.10.12),
#                   and the tree is relocatable: sunny gets a byte copy of rain's tree (deploy_blind.sh), so both
#                   nodes run the same interpreter, the same wheels and the same bytecode.
#   py310/...       torch 2.4.1 (PyPI cu121 wheel; it pulls nvidia-nccl-cu12 2.20.5, which this study never loads:
#                   the runner LD_PRELOADs the Stage 2 libnccl 2.23.4), numpy 1.26.4, requests (data preparation only)
#   nanoGPT/        karpathy/nanoGPT at a pinned commit (unmodified), with data/shakespeare_char prepared
#   MANIFEST.md5    md5 of every file under py310/ and nanoGPT/ except __pycache__ (deploy_blind.sh compares it on
#                   both nodes)
#   install_info.txt  versions, the wheel list, torch's libnccl dependency, the NCCL headers torch was built with
#
# Never runs a GPU program: `import torch` only (no CUDA call), the NCCL version torch was compiled against is read
# from torch.cuda.nccl.version() with the bundled library, and the Stage 2 library's version string is read with
# `strings`.
#
# usage: install_venv.sh [all|python|torch|nanogpt|manifest]   (default all; each step is skipped when done)
set -euo pipefail
V=${BLIND_VENV:-$HOME/blind-venv}
PBS_TAG=20241016
PBS_FILE="cpython-3.10.15+${PBS_TAG}-x86_64-unknown-linux-gnu-install_only.tar.gz"
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/cpython-3.10.15%2B${PBS_TAG}-x86_64-unknown-linux-gnu-install_only.tar.gz"
NANOGPT_URL=https://github.com/karpathy/nanoGPT.git
NANOGPT_COMMIT=${NANOGPT_COMMIT:-3adf61e154c3fe3fca428ad6bc3818b27a3b8291}
PY=$V/py310/bin/python3.10
what=${1:-all}
mkdir -p "$V/dl"

step_python() {
  [ -x "$PY" ] && { echo "python: present ($($PY -V))"; return 0; }
  cd "$V/dl"
  curl -fsSL -o "$PBS_FILE" "$PBS_URL"
  curl -fsSL -o "$PBS_FILE.sha256" "$PBS_URL.sha256"
  want=$(awk '{print $1}' "$PBS_FILE.sha256")
  got=$(sha256sum "$PBS_FILE" | awk '{print $1}')
  [ "$want" = "$got" ] || { echo "sha256 mismatch for $PBS_FILE: $got != $want" >&2; exit 1; }
  rm -rf "$V/dl/x" && mkdir "$V/dl/x" && tar -xzf "$PBS_FILE" -C "$V/dl/x"
  mv "$V/dl/x/python" "$V/py310"
  rmdir "$V/dl/x"
  echo "python: $($PY -V) sha256 $got"
}

step_torch() {
  if "$PY" -c 'import torch, sys; sys.exit(0 if torch.__version__.startswith("2.4.1") else 1)' 2>/dev/null; then
    echo "torch: present"; return 0
  fi
  "$PY" -m pip install --no-cache-dir --disable-pip-version-check --upgrade "pip==24.2"
  "$PY" -m pip install --no-cache-dir --disable-pip-version-check "torch==2.4.1" "numpy==1.26.4" "requests==2.32.3"
}

step_nanogpt() {
  if [ -f "$V/nanoGPT/data/shakespeare_char/train.bin" ]; then echo "nanoGPT: present"; return 0; fi
  [ -d "$V/nanoGPT/.git" ] || git clone -q "$NANOGPT_URL" "$V/nanoGPT"
  git -C "$V/nanoGPT" -c advice.detachedHead=false checkout -q "$NANOGPT_COMMIT"
  git -C "$V/nanoGPT" status --porcelain | grep -q . && { echo "nanoGPT tree is not clean" >&2; exit 1; }
  # data preparation is the repository's own script (downloads input.txt, about 1.1 MB, and writes train.bin,
  # val.bin and meta.pkl next to it); the tree stays otherwise unmodified
  (cd "$V/nanoGPT/data/shakespeare_char" && "$PY" prepare.py)
}

step_manifest() {
  (cd "$V" && find py310 nanoGPT -path '*/__pycache__' -prune -o -path 'nanoGPT/.git' -prune -o -type f -print0 |
     sort -z | xargs -0 md5sum) > "$V/MANIFEST.md5"
  {
    echo "date: $(date '+%F %T') host: $(hostname -s)"
    echo "python: $($PY -V 2>&1) ($PBS_FILE)"
    echo "nanoGPT: $(git -C "$V/nanoGPT" rev-parse HEAD) clean=$(git -C "$V/nanoGPT" status --porcelain --untracked-files=no | wc -l | sed 's/^0$/yes/')"
    echo "data: $(cd "$V/nanoGPT/data/shakespeare_char" && md5sum input.txt train.bin val.bin meta.pkl | tr '\n' ' ')"
    "$PY" - <<'PY'
import importlib.metadata as md, os, glob, torch
print("torch:", torch.__version__, "cuda:", torch.version.cuda, "cudnn:", torch.backends.cudnn.version())
print("torch built against NCCL (bundled library):", ".".join(map(str, torch.cuda.nccl.version())))
for d in ("torch", "numpy", "nvidia-nccl-cu12", "triton", "requests"):
    try:
        print(f"{d}=={md.version(d)}")
    except md.PackageNotFoundError:
        print(f"{d}: not installed")
lib = os.path.join(os.path.dirname(torch.__file__), "lib", "libtorch_cuda.so")
print("libtorch_cuda.so:", lib)
PY
    lib=$("$PY" -c 'import torch, os; print(os.path.join(os.path.dirname(torch.__file__), "lib", "libtorch_cuda.so"))')
    echo "libtorch_cuda NEEDED/RPATH:"; readelf -d "$lib" | grep -E 'NEEDED|RPATH|RUNPATH' | grep -iE 'nccl|RPATH|RUNPATH'
    echo "nccl symbols libtorch_cuda imports:"; nm -D --undefined-only "$lib" | awk '{print $2}' | grep -E '^nccl|^pnccl' | sort | tr '\n' ' '; echo
    "$PY" -m pip list --format=freeze --disable-pip-version-check
    echo "manifest: $(wc -l < "$V/MANIFEST.md5") files, md5 of the manifest $(md5sum < "$V/MANIFEST.md5" | cut -c1-32)"
  } > "$V/install_info.txt" 2>&1
  cat "$V/install_info.txt"
}

case "$what" in
  all) step_python; step_torch; step_nanogpt; step_manifest ;;
  python) step_python ;; torch) step_torch ;; nanogpt) step_nanogpt ;; manifest) step_manifest ;;
  *) echo "usage: $0 [all|python|torch|nanogpt|manifest]" >&2; exit 2 ;;
esac
