#!/usr/bin/env bash
# Single job — all recordings processed in parallel internally.
#
# Submit:
#   sbatch hpg/run_all.sh
#
# Override CPUs at submit time:
#   sbatch --cpus-per-task=64 hpg/run_all.sh
#
# Monitor:
#   tail -f logs/iris_latest.out

#SBATCH --job-name=iris_video
#SBATCH --account=ruogu.fang
#SBATCH --qos=ruogu.fang-b
#SBATCH --partition=hpg-default
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=128gb
#SBATCH --time=24:00:00
#SBATCH --output=logs/iris_%j.out
#SBATCH --error=logs/iris_%j.err

set -euo pipefail

RUN_ID="${RUN_ID:-full_dataset_v1}"
COMBINATION="${COMBINATION:-fast_noflow,stable_match_farneback}"
WORKERS="${WORKERS:-${SLURM_CPUS_PER_TASK:-32}}"

ROOT="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$ROOT"

mkdir -p logs dataserver/video_runs output/video_runs

if [[ ! -f dataserver/rec_ids.txt ]]; then
  echo "Missing dataserver/rec_ids.txt. Run hpg/run.sh locally first."
  exit 1
fi
if [[ ! -f .venv/bin/activate ]]; then
  echo "venv not found. See first-time setup in hpg/run.sh comments."
  exit 1
fi
source .venv/bin/activate

# Symlink logs/iris_latest.out → this job's log for easy tailing
ln -sf "iris_${SLURM_JOB_ID}.out" logs/iris_latest.out
ln -sf "iris_${SLURM_JOB_ID}.err" logs/iris_latest.err

TOTAL=$(wc -l < dataserver/rec_ids.txt | tr -d ' ')
echo "========================================"
echo " iris_video  job=$SLURM_JOB_ID"
echo " recordings : $TOTAL"
echo " workers    : $WORKERS"
echo " run_id     : $RUN_ID"
echo " combos     : $COMBINATION"
echo " started    : $(date)"
echo "========================================"

# ── Background heartbeat: print parquet count every 2 min ────────────────────
_heartbeat() {
  while true; do
    sleep 120
    DONE=$(find "dataserver/video_runs/$RUN_ID" -name "per_frame.parquet" 2>/dev/null | wc -l)
    echo "[heartbeat] $DONE / $TOTAL done at $(date +%H:%M:%S)"
  done
}
_heartbeat &
HEARTBEAT_PID=$!
trap 'kill "$HEARTBEAT_PID" 2>/dev/null || true' EXIT

# ── Process all recordings ────────────────────────────────────────────────────
python - <<PYEOF
from video.experiments import run_many
import json, pathlib

ids_path = pathlib.Path("dataserver/rec_ids.txt")
rec_ids = [l.strip() for l in ids_path.read_text().splitlines() if l.strip()]

run_many(
    rec_ids=rec_ids,
    combinations="$COMBINATION".split(","),
    run_id="$RUN_ID",
    only_missing=True,
    save_videos=True,
    save_stage_grid=True,
    save_step_videos=False,
    workers=$WORKERS,
)
PYEOF

DONE=$(find "dataserver/video_runs/$RUN_ID" -name "per_frame.parquet" 2>/dev/null | wc -l)
echo "========================================"
echo " finished: $DONE / $TOTAL recordings"
echo " ended   : $(date)"
echo "========================================"
