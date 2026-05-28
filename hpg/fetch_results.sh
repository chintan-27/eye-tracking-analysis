#!/usr/bin/env bash
# Run locally after HiPerGator jobs finish to pull processed outputs back.
#
# Usage:
#   bash hpg/fetch_results.sh               # rsync results
#   bash hpg/fetch_results.sh --status      # check progress without syncing
#   RUN_ID=full_dataset_v1 bash hpg/fetch_results.sh
set -euo pipefail

# ── Configure to match hpg/run.sh ────────────────────────────────────────────
HPG_USER="chintan.acharya"
HPG_HOST="hpg.rc.ufl.edu"
HPG_GROUP="ruogu.fang"
HPG_DIR="/blue/$HPG_GROUP/$HPG_USER/eye-tracking"
RUN_ID="${RUN_ID:-full_dataset_v1}"
# ─────────────────────────────────────────────────────────────────────────────

SSH_CONTROL_PATH="/tmp/eye-tracking-hpg-%r@%h:%p"
SSH_OPTS=(-o ControlMaster=auto -o ControlPath="$SSH_CONTROL_PATH" -o ControlPersist=10m)

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# ── --status mode: check job/completion state without syncing ─────────────────
if [[ "${1:-}" == "--status" ]]; then
  echo "▶ Checking HiPerGator status for run: $RUN_ID"
  ssh "${SSH_OPTS[@]}" "$HPG_USER@$HPG_HOST" bash <<REMOTE
set -euo pipefail
echo ""
echo "=== SLURM jobs (iris_video) ==="
squeue -u "$HPG_USER" -n iris_video \
  --format="%-18i %-12j %-10T %-10M %-10L %-6C %R" 2>/dev/null || echo "(none running)"

echo ""
echo "=== Completed recordings (per_frame.parquet present) ==="
DONE=\$(find "$HPG_DIR/dataserver/video_runs/$RUN_ID" -name "per_frame.parquet" 2>/dev/null | wc -l)
TOTAL=\$(wc -l < "$HPG_DIR/dataserver/rec_ids.txt" 2>/dev/null | tr -d ' ')
echo "  \$DONE / \$TOTAL recordings finished"

echo ""
echo "=== Recent job timing (sacct, last 24h) ==="
sacct -u "$HPG_USER" --name iris_video \
  --starttime=\$(date -d '24 hours ago' +%Y-%m-%dT%H:%M:%S) \
  --format="JobID%-15,State%-10,Elapsed%-10,CPUTime%-10,MaxRSS%-10,NodeList%-12" \
  --noheader 2>/dev/null | tail -20 || echo "(no sacct data)"
REMOTE
  exit 0
fi

# ── Rsync results back locally ────────────────────────────────────────────────
echo "▶ Opening SSH connection..."
ssh "${SSH_OPTS[@]}" -MNf "$HPG_USER@$HPG_HOST" || true
cleanup_ssh() {
  ssh "${SSH_OPTS[@]}" -O exit "$HPG_USER@$HPG_HOST" >/dev/null 2>&1 || true
}
trap cleanup_ssh EXIT

mkdir -p "dataserver/video_runs/$RUN_ID" "output/video_runs/$RUN_ID"

echo "▶ Fetching data outputs (parquets) for $RUN_ID..."
rsync -az --info=progress2,stats2 --human-readable \
  -e "ssh ${SSH_OPTS[*]}" \
  "$HPG_USER@$HPG_HOST:$HPG_DIR/dataserver/video_runs/$RUN_ID/" \
  "dataserver/video_runs/$RUN_ID/"

echo "▶ Fetching video outputs for $RUN_ID..."
rsync -az --info=progress2,stats2 --human-readable \
  -e "ssh ${SSH_OPTS[*]}" \
  "$HPG_USER@$HPG_HOST:$HPG_DIR/output/video_runs/$RUN_ID/" \
  "output/video_runs/$RUN_ID/" || true

# Show local completion count
DONE=$(find "dataserver/video_runs/$RUN_ID" -name "per_frame.parquet" 2>/dev/null | wc -l)
echo ""
echo "✓ Fetch complete — $DONE recordings have per_frame.parquet locally"
