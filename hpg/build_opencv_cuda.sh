#!/usr/bin/env bash
# Build opencv with CUDA support for the project venv.
# Run interactively on a GPU node — takes ~20-30 min.
#
# Usage:
#   srun --partition=hpg-turin --gpus=l4:1 --ntasks=1 \
#        --cpus-per-task=8 --mem=32gb --time=60:00 \
#        bash hpg/build_opencv_cuda.sh
#
# If the build fails with numpy 2.x, retry with numpy<2:
#   NUMPY_VERSION="<2" bash hpg/build_opencv_cuda.sh
#
# HiPerGator notes:
#   - GCC 14 lives at /apps/compilers/gcc/14.2.0 (not /apps/gcc/14.2.0)
#   - system opencv/4.7.0 is CPU-only; this script builds a CUDA version
#   - do NOT load opencv/4.7.0 here — we're replacing it
#   - LD_PRELOAD of GCC 14 libstdc++ is required at runtime because
#     /apps/python/3.11 embeds an older libstdc++ via RPATH

set -euo pipefail

ROOT="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$ROOT"

[[ -f .venv/bin/activate ]] || { echo "ERROR: .venv not found at $ROOT/.venv"; exit 1; }

echo "========================================"
echo " build_opencv_cuda"
echo " root    : $ROOT"
echo " started : $(date)"
echo "========================================"

# ── Load modules — do NOT load opencv/4.7.0 (CPU-only, would pollute paths) ──
module load cuda/12.8.1 gcc/14.2.0 cmake ffmpeg/4.3.1 2>/dev/null || {
  module load cuda/12.8.1 2>/dev/null || true
  module load gcc/14.2.0  2>/dev/null || true
  module load cmake        2>/dev/null || true
  module load ffmpeg/4.3.1 2>/dev/null || true
}
# gcc/14.2.0 auto-loads openmpi/5.0.7, whose libmpi.so has unresolved hcoll
# symbols that break CMake's compiler checks. OpenCV doesn't need MPI.
module unload openmpi 2>/dev/null || true
unset MPI_HOME OMPI_MCA_btl 2>/dev/null || true

# ffmpeg module only sets PATH, not PKG_CONFIG_PATH — cmake needs pkg-config
export PKG_CONFIG_PATH="/apps/ffmpeg/4.3.1/lib/pkgconfig:${PKG_CONFIG_PATH:-}"
export LD_LIBRARY_PATH="/apps/ffmpeg/4.3.1/lib:${LD_LIBRARY_PATH:-}"

echo ""
echo "--- build env ---"
echo "  CUDA_HOME     = ${CUDA_HOME:-<unset>}"
echo "  HPC_GCC_DIR   = ${HPC_GCC_DIR:-<unset>}"
nvcc --version 2>/dev/null | head -1 || echo "  nvcc: not found"
cmake --version | head -1
gcc --version   | head -1

COMPUTE_CAP=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null \
              | head -1 | tr -d ' ')
if [[ -z "$COMPUTE_CAP" ]]; then
  echo "  WARN: could not detect compute cap, defaulting to 8.9 (L4)"
  COMPUTE_CAP="8.9"
fi
echo "  compute cap   = $COMPUTE_CAP"

# ── Activate venv ─────────────────────────────────────────────────────────────
source .venv/bin/activate
PYTHON=$(which python3)
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
SITE_PACKAGES=$(python3 -c "import site; print(site.getsitepackages()[0])")
echo "  python        = $PYTHON ($(python3 --version))"
echo "  numpy         = $(python3 -c 'import numpy; print(numpy.__version__)')"
echo "  site-packages = $SITE_PACKAGES"

# ── Numpy: prefer 2.x; fall back to <2 if the build later fails ──────────────
# OpenCV 4.10.0 supports numpy 2.x; building from source compiles against
# whatever is installed here, so pin it before cmake runs.
# If the build fails with numpy 2.x, re-run with: NUMPY_VERSION="<2"
NUMPY_VERSION="${NUMPY_VERSION:->=2.0}"
echo ""
echo "--- numpy ---"
pip install "numpy${NUMPY_VERSION}" --quiet
echo "  numpy = $(python3 -c 'import numpy; print(numpy.__version__)')"

# ── Clean any existing cv2 artifacts from the venv ───────────────────────────
echo ""
echo "--- cleaning old cv2 from venv ---"
pip uninstall -y opencv-python opencv-python-headless opencv-contrib-python 2>/dev/null || true
rm -rf  "$SITE_PACKAGES/cv2" "$SITE_PACKAGES/cv2_backup"
find "$SITE_PACKAGES" -name "cv2*.so" -delete 2>/dev/null || true
echo "  done"

# ── Source / build dirs (persistent — skip clone/configure if already done) ───
SRC_DIR="$ROOT/cv2_temp"
BUILD_DIR="$SRC_DIR/build"
INSTALL_DIR="$ROOT/.opencv_cuda"
mkdir -p "$SRC_DIR" "$ROOT/logs"

OPENCV_VERSION="4.10.0"

echo ""
if [[ -d "$SRC_DIR/opencv/.git" ]]; then
  echo "--- opencv sources already present, skipping clone ---"
else
  echo "--- cloning opencv $OPENCV_VERSION ---"
  git clone --depth 1 --branch "$OPENCV_VERSION" \
    https://github.com/opencv/opencv.git "$SRC_DIR/opencv"
  git clone --depth 1 --branch "$OPENCV_VERSION" \
    https://github.com/opencv/opencv_contrib.git "$SRC_DIR/opencv_contrib"
fi

# ── CMake configure (skip if Makefile already exists) ────────────────────────
PY_LIB_DIR=$(python3 -c "import sysconfig; print(sysconfig.get_config_var('LIBDIR'))")
PY_INCLUDE=$(python3 -c "import sysconfig; print(sysconfig.get_path('include'))")

mkdir -p "$BUILD_DIR"
cd       "$BUILD_DIR"

echo ""
if [[ -f "$BUILD_DIR/Makefile" ]]; then
  echo "--- cmake already configured, skipping ---"
else
  echo "--- cmake configure ---"
  cmake "$SRC_DIR/opencv" \
  -DCMAKE_BUILD_TYPE=RELEASE \
  -DCMAKE_INSTALL_PREFIX="$INSTALL_DIR" \
  -DOPENCV_EXTRA_MODULES_PATH="$SRC_DIR/opencv_contrib/modules" \
  -DWITH_CUDA=ON \
  -DCUDA_ARCH_BIN="$COMPUTE_CAP" \
  -DCUDA_ARCH_PTX="" \
  -DWITH_CUDNN=OFF \
  -DENABLE_FAST_MATH=ON \
  -DCUDA_FAST_MATH=ON \
  -DWITH_CUBLAS=ON \
  -DBUILD_PYTHON_SUPPORT=ON \
  -DPYTHON3_EXECUTABLE="$PYTHON" \
  -DPYTHON3_LIBRARY="$PY_LIB_DIR/libpython${PY_VER}.so" \
  -DPYTHON3_INCLUDE_DIR="$PY_INCLUDE" \
  -DPYTHON3_PACKAGES_PATH="$SITE_PACKAGES" \
  -DBUILD_opencv_python2=OFF \
  -DBUILD_opencv_python3=ON \
  -DBUILD_TESTS=OFF \
  -DBUILD_PERF_TESTS=OFF \
  -DBUILD_EXAMPLES=OFF \
  -DBUILD_DOCS=OFF \
  -DWITH_GTK=OFF \
  -DWITH_FFMPEG=ON \
  -DWITH_MPI=OFF \
  2>&1 | tee "$ROOT/logs/opencv_cmake.log"
fi  # end cmake configure block

# ── Build & install ───────────────────────────────────────────────────────────
echo ""
echo "--- make (8 jobs) — ~20 min ---"
make -j8 2>&1 | tee "$ROOT/logs/opencv_make.log"

echo ""
echo "--- make install ---"
make install

# ── Copy cv2.so into venv site-packages ──────────────────────────────────────
echo ""
echo "--- installing cv2.so to venv ---"
SO=$(find "$INSTALL_DIR" "$BUILD_DIR" -name "cv2*.so" 2>/dev/null | head -1)
if [[ -z "$SO" ]]; then
  echo "ERROR: cv2.so not found after build"
  find "$INSTALL_DIR" -name "*.so" 2>/dev/null | grep -i python | head -10 || true
  exit 1
fi
# Remove stale artifacts one more time before placing the new .so
rm -rf "$SITE_PACKAGES/cv2" "$SITE_PACKAGES/cv2_backup"
find "$SITE_PACKAGES" -name "cv2*.so" -delete 2>/dev/null || true
cp "$SO" "$SITE_PACKAGES/"
echo "  $SO → $SITE_PACKAGES/"

# ── Verification ──────────────────────────────────────────────────────────────
echo ""
echo "--- verification ---"

# Runtime env: our built libs + GCC 14 libstdc++ to override Python's RPATH
export LD_LIBRARY_PATH="$INSTALL_DIR/lib64:$INSTALL_DIR/lib:${LD_LIBRARY_PATH:-}"
_STDCXX="/apps/compilers/gcc/14.2.0/lib64/libstdc++.so.6"
[[ -f "$_STDCXX" ]] && export LD_PRELOAD="$_STDCXX"

python3 - <<'PYEOF'
import sys
try:
    import cv2
except Exception as e:
    print(f"  import FAILED: {e}"); sys.exit(1)

print(f"  cv2 version  : {cv2.__version__}")
print(f"  cv2 path     : {cv2.__file__}")
try:
    import numpy as np
    print(f"  numpy version: {np.__version__}")
except Exception as e:
    print(f"  numpy import : FAILED: {e}")

try:
    n = cv2.cuda.getCudaEnabledDeviceCount()
    print(f"  cuda devices : {n}")
    for i in range(n):
        d = cv2.cuda.DeviceInfo(i)
        _name = d.name() if callable(getattr(d, 'name', None)) else d.name
        _maj  = d.majorVersion() if callable(getattr(d, 'majorVersion', None)) else d.majorVersion
        _min  = d.minorVersion() if callable(getattr(d, 'minorVersion', None)) else d.minorVersion
        _mem  = d.totalMemory() if callable(getattr(d, 'totalMemory', None)) else d.totalMemory
        print(f"  device[{i}]   : {_name}  CC={_maj}.{_min}  {_mem//1024//1024} MB")
    if n == 0:
        print("  WARN: 0 devices — check CUDA_VISIBLE_DEVICES")
    else:
        print("  SUCCESS: CUDA opencv ready")
except Exception as e:
    print(f"  cuda probe   : ERROR: {e}")
PYEOF

cd "$ROOT"

echo ""
echo "========================================"
echo " build complete : $(date)"
echo " sources        : $SRC_DIR  (kept for incremental rebuilds)"
echo " install dir    : $INSTALL_DIR"
echo " logs           : logs/opencv_cmake.log  logs/opencv_make.log"
echo "========================================"
