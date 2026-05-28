#!/usr/bin/env bash
# Run locally to export metadata and sync everything needed to HiPerGator.
# Usage: bash hpg/run.sh
set -euo pipefail

# ── Configure ─────────────────────────────────────────────────────────────────
HPG_USER="chintan.acharya"
HPG_HOST="hpg.rc.ufl.edu"
HPG_GROUP="ruogu.fang"
HPG_DIR="/blue/$HPG_GROUP/$HPG_USER/eye-tracking"
HPG="$HPG_USER@$HPG_HOST:$HPG_DIR"
SSH_CONTROL_PATH="/tmp/eye-tracking-hpg-%r@%h:%p"
SSH_OPTS=(-o ControlMaster=auto -o ControlPath="$SSH_CONTROL_PATH" -o ControlPersist=10m)
RSYNC_SSH="ssh ${SSH_OPTS[*]}"
RSYNC_PROGRESS=(--info=progress2,stats2 --human-readable)
# ─────────────────────────────────────────────────────────────────────────────

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "▶ Exporting metadata..."
source .venv/bin/activate
python -m video.export_meta

N=$(wc -l < dataserver/rec_ids.txt | tr -d ' ')
echo "  $N recordings"

if [[ "$HPG_GROUP" == "<your_group>" ]]; then
  echo "Set HPG_GROUP in hpg/run.sh before running."
  exit 1
fi

echo "▶ Opening SSH connection..."
ssh "${SSH_OPTS[@]}" -MNf "$HPG_USER@$HPG_HOST" || true
cleanup_ssh() {
  ssh "${SSH_OPTS[@]}" -O exit "$HPG_USER@$HPG_HOST" >/dev/null 2>&1 || true
}
trap cleanup_ssh EXIT

echo "▶ Creating remote directories..."
ssh "${SSH_OPTS[@]}" "$HPG_USER@$HPG_HOST" "mkdir -p '$HPG_DIR'/video '$HPG_DIR'/db '$HPG_DIR'/hpg '$HPG_DIR'/dataserver/eeg '$HPG_DIR'/data '$HPG_DIR'/logs '$HPG_DIR'/output/video_runs '$HPG_DIR'/dataserver/video_runs"

echo "▶ Syncing code..."
rsync -az --delete "${RSYNC_PROGRESS[@]}" -e "$RSYNC_SSH" \
  --exclude='__pycache__' --exclude='*.pyc' \
  video/ "$HPG/video/"
rsync -az --delete "${RSYNC_PROGRESS[@]}" -e "$RSYNC_SSH" \
  --exclude='__pycache__' --exclude='*.pyc' \
  db/ "$HPG/db/"
rsync -az "${RSYNC_PROGRESS[@]}" -e "$RSYNC_SSH" \
  hpg/ "$HPG/hpg/"

echo "▶ Syncing metadata..."
rsync -az "${RSYNC_PROGRESS[@]}" -e "$RSYNC_SSH" \
  dataserver/hpg_meta.json \
  dataserver/rec_ids.txt \
  "$HPG/dataserver/"

echo "▶ Syncing EEG Parquets..."
rsync -az --delete "${RSYNC_PROGRESS[@]}" -e "$RSYNC_SSH" \
  dataserver/eeg/ "$HPG/dataserver/eeg/"

echo "▶ Syncing video files (AVIs only)..."
rsync -az "${RSYNC_PROGRESS[@]}" -e "$RSYNC_SSH" \
  --include='*/' --include='*.avi' --exclude='*' \
  data/ "$HPG/data/"

echo ""
echo "✓ Sync complete → $HPG_DIR"
echo ""
echo "On HiPerGator, first time only:"
echo "  cd $HPG_DIR"
echo "  module load python"
echo "  python -m venv .venv && source .venv/bin/activate"
echo "  pip install opencv-python-headless numpy pandas scipy pyarrow zarr numcodecs \\"
echo "              scikit-image sqlalchemy rich pupil-detectors pywavelets filterpy"
echo ""
echo "Then submit:"
echo "  sbatch hpg/run_all.sh"
echo ""
echo "Or with more CPUs (faster, uses more allocation):"
echo "  sbatch --cpus-per-task=64 --mem=256gb hpg/run_all.sh"
echo ""
echo "Check progress while running:"
echo "  bash hpg/fetch_results.sh --status"
echo ""
echo "Fetch results when done:"
echo "  bash hpg/fetch_results.sh"
