#!/usr/bin/env bash
# GPU job — L4 / B200 with CUDA Farneback optical flow.
# Uses HiPerGator's system opencv/4.7.0 (CUDA-enabled).
# A locally built .opencv_cuda/ (from build_opencv_cuda.sh) takes precedence
# if present, enabling version overrides without touching this script.
#
# Submit (L4):   sbatch hpg/run_gpu.sh
# Submit (B200): sbatch --partition=hpg-b200 --gpus=b200:1 hpg/run_gpu.sh
# Monitor:       tail -f logs/iris_gpu_latest.out

#SBATCH --job-name=iris_gpu
#SBATCH --account=ruogu.fang
#SBATCH --qos=ruogu.fang
#SBATCH --partition=hpg-turin
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64gb
#SBATCH --gpus=2
#SBATCH --time=48:00:00
#SBATCH --output=logs/iris_gpu_%j.out
#SBATCH --error=logs/iris_gpu_%j.err

set -euo pipefail
unset PYTHONPATH  # clear any inherited module PYTHONPATH

RUN_ID="${RUN_ID:-full_dataset_v1}"
COMBINATION="${COMBINATION:-stable_match_farneback}"
WORKERS="${WORKERS:-${SLURM_CPUS_PER_TASK:-16}}"

ROOT="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$ROOT"
mkdir -p logs dataserver/video_runs output/video_runs

[[ -f dataserver/rec_ids.txt ]] || { echo "ERROR: missing dataserver/rec_ids.txt"; exit 1; }
[[ -f .venv/bin/activate    ]] || { echo "ERROR: .venv not found";                 exit 1; }

module load cuda/12.8.1 gcc/14.2.0 ffmpeg/4.3.1 opencv/4.7.0 2>/dev/null || {
  module load cuda/12.8.1 opencv/4.7.0 2>/dev/null || \
  { module load cuda/12.8.1 2>/dev/null || true; }
}
source .venv/bin/activate

# opencv libs — .opencv_cuda/lib64 confirmed by diagnostic (no plain lib/ dir)
# ffmpeg libs — module only sets PATH, not LD_LIBRARY_PATH
export LD_LIBRARY_PATH="$ROOT/.opencv_cuda/lib64:/apps/ffmpeg/4.3.1/lib:${LD_LIBRARY_PATH:-}"

# GCC 14 libstdc++ — hardcoded path confirmed by diagnostic
# Needed because /apps/python/3.11 has an older libstdc++ baked in via RPATH;
# LD_PRELOAD overrides RPATH. libstdc++.so.6 is a symlink → .so.6.0.33, both work.
export LD_PRELOAD="/apps/compilers/gcc/14.2.0/lib64/libstdc++.so.6${LD_PRELOAD:+:$LD_PRELOAD}"

ln -sf "iris_gpu_${SLURM_JOB_ID}.out" logs/iris_gpu_latest.out
ln -sf "iris_gpu_${SLURM_JOB_ID}.err" logs/iris_gpu_latest.err

TOTAL=$(wc -l < dataserver/rec_ids.txt | tr -d ' ')

# ── logging helpers ───────────────────────────────────────────────────────────
hr()   { echo "================================================"; }
kv()   { printf "  %-18s %s\n" "$1" "$2"; }

# ── banner ────────────────────────────────────────────────────────────────────
hr
echo "  iris_gpu"
kv "job"        "$SLURM_JOB_ID"
kv "started"    "$(date '+%Y-%m-%d %H:%M:%S')"
kv "recordings" "$TOTAL"
kv "workers"    "$WORKERS"
kv "run_id"     "$RUN_ID"
kv "combo"      "$COMBINATION"
hr

# ── GPU info ──────────────────────────────────────────────────────────────────
echo ""
echo "  gpu"
GPU_ROW=$(nvidia-smi --query-gpu=name,memory.total,driver_version,compute_cap \
                     --format=csv,noheader 2>/dev/null | head -1 \
          || echo "unavailable")
kv "device"    "$GPU_ROW"
kv "CUDA_HOME" "${CUDA_HOME:-<unset>}"
kv "visible"   "${CUDA_VISIBLE_DEVICES:-<unset>}"

# ── opencv probe ──────────────────────────────────────────────────────────────
echo ""
echo "  opencv"
python3 - <<'PY'
try:
    import cv2
except ImportError as e:
    print(f"  {'IMPORT ERROR':<18} {e}")
    raise SystemExit(1)
def _di_attr(d, attr):
    v = getattr(d, attr, None)
    return v() if callable(v) else v

try:
    n = cv2.cuda.getCudaEnabledDeviceCount()
    if n > 0:
        devs = [f"{_di_attr(cv2.cuda.DeviceInfo(i),'name')} CC{_di_attr(cv2.cuda.DeviceInfo(i),'majorVersion')}.{_di_attr(cv2.cuda.DeviceInfo(i),'minorVersion')} {_di_attr(cv2.cuda.DeviceInfo(i),'totalMemory')//1024//1024}MB"
                for i in range(n)]
        print(f"  {'version':<18} {cv2.__version__}")
        print(f"  {'CUDA devices':<18} {n}  ({', '.join(devs)})")
    else:
        print(f"  {'version':<18} {cv2.__version__}")
        print(f"  {'CUDA devices':<18} 0  [no devices visible]")
except Exception as e:
    print(f"  {'version':<18} {cv2.__version__}")
    print(f"  {'CUDA probe':<18} error: {e}")
PY

GPU_COUNT=$(python3 -c "
try:
    import cv2
    print(cv2.cuda.getCudaEnabledDeviceCount())
except: print(0)
")

# ── flow backend ──────────────────────────────────────────────────────────────
echo ""
if [[ "$GPU_COUNT" -gt 0 ]]; then
  DEV=$(python3 -c "
import cv2
d = cv2.cuda.DeviceInfo(0)
def a(d,k): v=getattr(d,k,None); return v() if callable(v) else v
print(f\"{a(d,'name')}  CC {a(d,'majorVersion')}.{a(d,'minorVersion')}  {a(d,'totalMemory')//1024//1024} MB\")
" 2>/dev/null || echo "GPU")
  echo "  flow  CUDA Farneback  [$DEV]"
else
  echo "  flow  CPU Farneback  (no CUDA devices visible)"
fi
echo ""
hr

# ── background heartbeat ──────────────────────────────────────────────────────
_heartbeat() {
  while true; do
    sleep 120
    DONE=$(find "dataserver/video_runs/$RUN_ID" -name "per_frame.parquet" 2>/dev/null | wc -l)
    printf "  [heartbeat]  %3d / %d done  %s\n" "$DONE" "$TOTAL" "$(date '+%H:%M:%S')"
  done
}
_heartbeat &
HEARTBEAT_PID=$!
trap 'kill "$HEARTBEAT_PID" 2>/dev/null || true' EXIT

# ── run pipeline ──────────────────────────────────────────────────────────────
# Must call a real .py file (not heredoc/stdin) so multiprocessing spawn mode
# can re-import __main__ by file path when forking CUDA worker processes.
python3 hpg/run_pipeline.py

# ── finish ────────────────────────────────────────────────────────────────────
DONE=$(find "dataserver/video_runs/$RUN_ID" -name "per_frame.parquet" 2>/dev/null | wc -l)
hr
kv "finished" "$DONE / $TOTAL recordings"
kv "ended"    "$(date '+%Y-%m-%d %H:%M:%S')"
hr
