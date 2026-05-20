"""
db/ingest/tobii.py

Reads every Tobii eye-tracking CSV and:
  1. Extracts start_time and end_time from LocalTimeStamp (first/last rows)
  2. Determines task_order by sorting all 5 tasks by start_time within a session
  3. Creates Task rows (one per paradigm per session)
  4. Cleans and type-casts the signal columns
  5. Writes to a zstd-compressed Parquet file in dataserver/tobii/
  6. Inserts one row into tobii_recordings

Parquet columns written:
  timestamp_ms    int64    — ms since Tobii recording start (RecordingTimestamp)
  event_type      str      — "Fixation" | "Saccade" | "Unclassified"
  event_duration  int32    — duration of current gaze event in ms (-1 if NaN)
  gaze_x          float32  — gaze point x on screen in pixels (monitor coords)
  gaze_y          float32  — gaze point y on screen in pixels
  fixation_x      float32  — fixation centroid x (-1.0 during saccades)
  fixation_y      float32  — fixation centroid y
  pupil_left      float32  — left pupil diameter in mm (NaN if invalid)
  pupil_right     float32  — right pupil diameter in mm
  validity_left   int8     — 0=valid, 4=lost
  validity_right  int8     — 0=valid, 4=lost
  saccade_amp     float32  — saccadic amplitude in degrees (NaN during fixations)
  saccade_dir     float32  — absolute saccadic direction in degrees
  distance_left   float32  — distance of left eye from tracker in mm
  distance_right  float32  — distance of right eye from tracker in mm

Run directly to ingest all Tobii files:
    python -m db.ingest.tobii
"""

import pandas as pd
from concurrent.futures import ProcessPoolExecutor, as_completed
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from db.database import get_db, save_parquet

console = Console()
from db.config import DATA_ROOT, PARADIGM_MAP, TOBII_KEEP_COLS, TOBII_RENAME, PARQUET_DIRS, TOBII_SAMPLING_RATE, MAX_WORKERS
from db.models import Task, TobiiRecording

PARQUET_DIR = PARQUET_DIRS["Tobii"]
KEEP_COLS   = TOBII_KEEP_COLS
RENAME      = TOBII_RENAME


# ---------------------------------------------------------------------------
# _get_timestamps()
# ---------------------------------------------------------------------------
# Reads only LocalTimeStamp from the CSV (fast — one column, first+last row).
# Returns (start_time, end_time) as strings "HH:MM:SS.mmm".

def _get_timestamps(csv_path: Path) -> tuple[str, str]:
    df = pd.read_csv(csv_path, usecols=['LocalTimeStamp'])
    valid = df['LocalTimeStamp'].dropna()
    valid = valid[valid.astype(str).str.strip() != '']
    return str(valid.iloc[0]).strip(), str(valid.iloc[-1]).strip()


# ---------------------------------------------------------------------------
# _clean()
# ---------------------------------------------------------------------------
# Selects only the columns we need, renames them, and applies type casts.

def _clean(df: pd.DataFrame) -> pd.DataFrame:
    # drop LocalTimeStamp — we already extracted start/end from it
    cols = [c for c in KEEP_COLS if c != 'LocalTimeStamp']
    df = df[cols].rename(columns=RENAME)

    # timestamp_ms → int64 (always populated, no NaN expected)
    df['timestamp_ms'] = df['timestamp_ms'].astype('int64')

    # event_type → str, fill NaN with empty string
    df['event_type'] = df['event_type'].fillna('').astype(str)

    # event_duration → int32, NaN → -1
    df['event_duration'] = pd.to_numeric(df['event_duration'], errors='coerce') \
                             .fillna(-1).astype('int32')

    # gaze_x/y → float32 (NaN stays as NaN — means tracking lost)
    for col in ['gaze_x', 'gaze_y', 'fixation_x', 'fixation_y',
                'pupil_left', 'pupil_right',
                'saccade_amp', 'saccade_dir',
                'distance_left', 'distance_right']:
        df[col] = pd.to_numeric(df[col], errors='coerce').astype('float32')

    # validity → int8 (0=valid, 4=lost). NaN means tracking completely lost → 4
    df['validity_left']  = df['validity_left'].fillna(4).astype('int8')
    df['validity_right'] = df['validity_right'].fillna(4).astype('int8')

    return df


# ---------------------------------------------------------------------------
# process_session()
# ---------------------------------------------------------------------------
# Processes all 5 Tobii files for one session together so we can determine
# task_order by comparing their start timestamps.
#
# Returns a list of (Task, TobiiRecording) pairs, one per paradigm.

def process_session(
    sess_dir: Path,
    subject_id: str,
    session_id: str,
) -> list[tuple[Task, TobiiRecording]]:

    tobii_dir = sess_dir / 'Tobii'
    if not tobii_dir.exists():
        return []

    # --- step 1: collect start/end times for all 5 paradigm files ---
    file_info = {}  # paradigm → (csv_path, start_time, end_time)
    for csv_path in tobii_dir.glob('*.csv'):
        paradigm = None
        for prefix, name in PARADIGM_MAP.items():
            if csv_path.stem.startswith(prefix):
                paradigm = name
                break
        if paradigm is None:
            continue
        start_time, end_time = _get_timestamps(csv_path)
        file_info[paradigm] = (csv_path, start_time, end_time)

    if len(file_info) != 5:
        console.print(f"  [yellow]⚠[/yellow]  only {len(file_info)}/5 Tobii files found — skipping session")
        return []

    # --- step 2: sort by start_time → derive task_order ---
    ordered = sorted(file_info.items(), key=lambda x: x[1][1])  # sort by start_time
    # ordered is [(paradigm, (path, start, end)), ...] in chronological order

    results = []
    for order_idx, (paradigm, (csv_path, start_time, end_time)) in enumerate(ordered):
        task_order = order_idx + 1  # 1-based
        rec_id     = f"{session_id}_{paradigm}"
        parquet_rel = f"{PARQUET_DIR}/{rec_id}.parquet"

        # read full CSV, extract admin metadata from first row
        df_full = pd.read_csv(csv_path, low_memory=False)
        first   = df_full.iloc[0]

        studio_version     = str(first.get('StudioVersionRec', '')).strip()
        recording_duration = int(first.get('RecordingDuration', 0)) if pd.notna(first.get('RecordingDuration')) else None
        resolution         = str(first.get('RecordingResolution', '')).strip()
        fixation_filter    = str(first.get('FixationFilter', '')).strip()
        export_date        = str(first.get('ExportDate', '')).strip()

        df = df_full[KEEP_COLS].copy()
        df = _clean(df)

        n_samples          = len(df)
        duration_s         = n_samples / TOBII_SAMPLING_RATE
        validity_pct       = float(((df['validity_left'] == 0) & (df['validity_right'] == 0)).mean() * 100)
        validity_left_pct  = float((df['validity_left']  == 0).mean() * 100)
        validity_right_pct = float((df['validity_right'] == 0).mean() * 100)
        hmac               = save_parquet(df, parquet_rel)

        results.append({
            "task": {
                "session_id": session_id,
                "paradigm":   paradigm,
                "task_order": task_order,
                "start_time": start_time,
                "end_time":   end_time,
            },
            "recording": {
                "id":                 rec_id,
                "subject_id":         subject_id,
                "session_id":         session_id,
                "paradigm":           paradigm,
                "file_path":          parquet_rel,
                "hmac":               hmac,
                "sampling_rate":      TOBII_SAMPLING_RATE,
                "n_samples":          n_samples,
                "duration_s":         duration_s,
                "validity_pct":       validity_pct,
                "validity_left_pct":  validity_left_pct,
                "validity_right_pct": validity_right_pct,
                "studio_version":     studio_version,
                "recording_duration": recording_duration,
                "resolution":         resolution,
                "fixation_filter":    fixation_filter,
                "export_date":        export_date,
            },
        })

    return results


def _worker(args: tuple) -> list[dict]:
    return process_session(*args)


# ---------------------------------------------------------------------------
# run()
# ---------------------------------------------------------------------------

def run():
    Session = get_db()

    # collect sessions that still need processing
    pending = []
    with Session() as db:
        for subj_dir in sorted(DATA_ROOT.glob('S*')):
            subject_id = subj_dir.name
            for sess_dir in sorted(subj_dir.glob('Sess*')):
                sess_num   = int(sess_dir.name.replace('Sess', ''))
                session_id = f"{subject_id}_Sess{sess_num:02d}"
                existing   = db.query(Task).filter_by(session_id=session_id).count()
                if existing == 5:
                    console.print(f"  [dim]↷ {session_id} (already exists)[/dim]")
                    continue
                if (sess_dir / 'Tobii').exists():
                    pending.append((sess_dir, subject_id, session_id))

    if not pending:
        return

    console.print(f"  Processing {len(pending)} sessions with {MAX_WORKERS} workers...")

    all_results = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        ptask = progress.add_task("  Tobii", total=len(pending))
        with ProcessPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(_worker, args): args for args in pending}
            for future in as_completed(futures):
                args = futures[future]
                try:
                    results = future.result()
                    all_results.extend(results)
                    progress.advance(ptask)
                    session_id = args[2]
                    for r in results:
                        t = r["task"]
                        rec = r["recording"]
                        console.print(
                            f"  [green]✓[/green] [{t['task_order']}] "
                            f"{session_id} {t['paradigm']:<8}  "
                            f"{t['start_time']} → {t['end_time']}  "
                            f"{rec['n_samples']:>9,} rows  "
                            f"validity {rec['validity_pct']:>5.1f}%"
                        )
                except Exception as e:
                    progress.advance(ptask)
                    console.print(f"  [red]✗[/red] {args[2]}: {e}")

    with Session() as db:
        for r in all_results:
            db.merge(Task(**r["task"]))
            db.merge(TobiiRecording(**r["recording"]))
        db.commit()
    console.print(f"  [dim]{len(all_results)} recordings written to DB[/dim]")


if __name__ == "__main__":
    run()
