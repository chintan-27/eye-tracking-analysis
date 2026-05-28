#!/usr/bin/env bash
# Diagnostic script — run on a GPU node, paste full output back.
# Usage: bash hpg/diagnose_cv2.sh

ROOT="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$ROOT"

echo "======== modules ========"
module load cuda/12.8.1 gcc/14.2.0 opencv/4.7.0 2>/dev/null || true
module list

echo ""
echo "======== loaded env vars ========"
printenv | grep -E "^(LD_LIBRARY_PATH|LD_PRELOAD|PYTHONPATH|CUDA_HOME|HPC_GCC_DIR|HPC_OPENCV_DIR|HPC_OPENMPI_DIR|MPI_HOME|PATH)=" | sort

echo ""
echo "======== libstdc++ — all copies, symlink or not ========"
find /apps/compilers/gcc/14.2.0 -name "libstdc++.so*" 2>/dev/null | sort
ls  -la /apps/compilers/gcc/14.2.0/lib64/libstdc++.so.6 2>/dev/null || echo "not found"
readlink -f /apps/compilers/gcc/14.2.0/lib64/libstdc++.so.6 2>/dev/null || echo "readlink failed"

echo ""
echo "======== cv2.so in venv ========"
find .venv -name "cv2*.so" 2>/dev/null || echo "not found"

echo ""
echo "======== .opencv_cuda layout ========"
ls .opencv_cuda/ 2>/dev/null || echo ".opencv_cuda not found"
find .opencv_cuda -name "libopencv*.so" 2>/dev/null | head -5
find .opencv_cuda -name "cv2*.so"       2>/dev/null

echo ""
echo "======== ldd on cv2.so ========"
CV2=$(find .venv -name "cv2*.so" 2>/dev/null | head -1)
if [[ -n "$CV2" ]]; then
  ldd "$CV2" | sort
else
  echo "cv2.so not found in venv"
fi

echo ""
echo "======== system opencv python path ========"
find /apps/opencv/4.7.0 -name "cv2*.so" 2>/dev/null || echo "not found"

echo ""
echo "======== numpy version in venv ========"
[[ -f .venv/bin/activate ]] && source .venv/bin/activate
python3 -c "import numpy; print(numpy.__version__, numpy.__file__)" 2>/dev/null || echo "numpy import failed"

echo ""
echo "======== quick cv2 import test ========"
export LD_LIBRARY_PATH=".opencv_cuda/lib64:.opencv_cuda/lib:${LD_LIBRARY_PATH:-}"
export LD_PRELOAD="/apps/compilers/gcc/14.2.0/lib64/libstdc++.so.6"
python3 -c "
import cv2
print('cv2 version:', cv2.__version__)
print('cv2 path:   ', cv2.__file__)
n = cv2.cuda.getCudaEnabledDeviceCount()
print('cuda devices:', n)
" 2>&1 || echo "cv2 import failed"
