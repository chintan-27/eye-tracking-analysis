#!/usr/bin/env bash
# Quick sanity check — run interactively on a GPU node:
#
#   srun --partition=hpg-turin --gpus=l4:1 --ntasks=1 \
#        --cpus-per-task=2 --mem=8gb --time=10:00 \
#        bash hpg/test_cv2_cuda.sh

set -euo pipefail

ROOT="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$ROOT"

module load cuda/12.8.1 gcc/14.2.0 opencv/4.7.0 2>/dev/null || {
  module load cuda/12.8.1 opencv/4.7.0 2>/dev/null || \
  { module load cuda/12.8.1 2>/dev/null || true; }
}

[[ -f .venv/bin/activate ]] || { echo "ERROR: .venv not found"; exit 1; }
source .venv/bin/activate

# Library path — prefer local build, fall back to system
if [[ -d "$ROOT/.opencv_cuda/lib64" ]]; then
  export LD_LIBRARY_PATH="$ROOT/.opencv_cuda/lib64:$ROOT/.opencv_cuda/lib:${LD_LIBRARY_PATH:-}"
elif [[ -d "$ROOT/.opencv_cuda/lib" ]]; then
  export LD_LIBRARY_PATH="$ROOT/.opencv_cuda/lib:${LD_LIBRARY_PATH:-}"
elif [[ -d "/apps/opencv/4.7.0/lib64" ]]; then
  export LD_LIBRARY_PATH="/apps/opencv/4.7.0/lib64:/apps/opencv/4.7.0/lib:${LD_LIBRARY_PATH:-}"
elif [[ -d "/apps/opencv/4.7.0/lib" ]]; then
  export LD_LIBRARY_PATH="/apps/opencv/4.7.0/lib:${LD_LIBRARY_PATH:-}"
fi

# Expose system cv2.so to the venv if not already installed there
_HPG_CV2=$(find /apps/opencv/4.7.0 -name "cv2*.so" 2>/dev/null | head -1 || true)
if [[ -n "$_HPG_CV2" ]] && ! find "$ROOT/.venv" -name "cv2*.so" -quit 2>/dev/null; then
  export PYTHONPATH="$(dirname "$_HPG_CV2"):${PYTHONPATH:-}"
fi

_GCC14_STDCXX=$(find /apps/gcc/14.2.0/lib64 /apps/gcc/14.2.0/lib -name "libstdc++.so.6" \
                     -not -type l 2>/dev/null | head -1 || true)
[[ -n "$_GCC14_STDCXX" ]] && export LD_PRELOAD="${_GCC14_STDCXX}:${LD_PRELOAD:-}"

echo "================================================"
echo "  cv2 CUDA test"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "================================================"
nvidia-smi --query-gpu=name,driver_version,compute_cap --format=csv,noheader 2>/dev/null \
  | awk '{printf "  gpu             %s\n", $0}' || echo "  gpu             unavailable"
echo ""

python3 - <<'PY'
import sys

# -- import
try:
    import cv2
    print(f"  import          OK")
    print(f"  version         {cv2.__version__}")
    print(f"  path            {cv2.__file__}")
except ImportError as e:
    print(f"  import          FAILED: {e}")
    sys.exit(1)

# -- cuda device count
try:
    n = cv2.cuda.getCudaEnabledDeviceCount()
    print(f"  CUDA devices    {n}")
except Exception as e:
    print(f"  CUDA devices    ERROR: {e}")
    sys.exit(1)

if n == 0:
    print("  result          FAIL — no CUDA devices visible")
    sys.exit(1)

# -- per-device info
for i in range(n):
    d = cv2.cuda.DeviceInfo(i)
    mem = d.totalMemory() // 1024 // 1024
    print(f"  device[{i}]       {d.name()}  CC {d.majorVersion()}.{d.minorVersion()}  {mem} MB")

# -- actual Farneback on GPU
import numpy as np
h, w = 240, 320
f1 = np.random.randint(0, 256, (h, w), dtype=np.uint8)
f2 = np.random.randint(0, 256, (h, w), dtype=np.uint8)
try:
    g1 = cv2.cuda_GpuMat(); g1.upload(f1)
    g2 = cv2.cuda_GpuMat(); g2.upload(f2)
    farn = cv2.cuda_FarnebackOpticalFlow.create(
        numLevels=3, pyrScale=0.5, fastPyramids=False,
        winSize=15, numIters=3, polyN=5, polySigma=1.2, flags=0,
    )
    flow_gpu = farn.calc(g1, g2, None)
    flow = flow_gpu.download()
    print(f"  Farneback GPU   OK  (flow shape {flow.shape})")
    print(f"  result          PASS")
except Exception as e:
    print(f"  Farneback GPU   FAILED: {e}")
    sys.exit(1)
PY
