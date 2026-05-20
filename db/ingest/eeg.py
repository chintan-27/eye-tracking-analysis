"""
db/ingest/eeg.py

Reads every Neuroscan EEG CSV file and:
  1. Cleans and type-casts the data
  2. Writes it to a zstd-compressed Parquet file in dataserver/eeg/
  3. Inserts one row into eeg_recordings for each file

Parquet columns written:
  timestamp_s          float64  — seconds from start of recording (renamed from 'Time')
  FP1 … CB2           float32  — 64 electrode voltages in µV
  HEO                  float32  — horizontal eye ocular channel
  trig                 int16    — trial number (0 when between trials / welcome / goodbye)
  cue                  str      — stimulus label ("Fixation", "Left", etc.), "" when absent
  phan_frame           int32    — Phantom video frame index (-1 when unavailable)
  recording_timestamp  int64    — sparse Tobii sync marker (-1 when absent)
  blink                int8     — 0 or 1

Columns dropped:
  PhanTime        — frame timestamp string (frame data lives in phantom_frames parquet)
  RelTime         — relative time offset (redundant given timestamp_s)
  LocalTimeStamp  — wall clock string (stored in tasks table)

Run directly to ingest all EEG files:
    python -m db.ingest.eeg
"""

from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np
import pandas as pd
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from db.database import get_db, save_parquet
from db.config import DATA_ROOT, PARADIGM_MAP, ELECTRODE_COLS, PARQUET_DIRS, EEG_SAMPLING_RATE, MAX_WORKERS
from db.models import EEGRecording

console = Console()

# dtype hints — tell pandas exactly what type each column is so it skips
# type inference. Speeds up read_csv by ~30% on large EEG files.
_EEG_DTYPES = {col: "float32" for col in ELECTRODE_COLS + ["HEO"]}
_EEG_DTYPES.update({
    "Time":               "float64",
    "Trig":               "object",
    "Cues":               "object",
    # PhanFrame absent in some files — don't force dtype
    # "PhanFrame":        "object",
    "PhanTime":           "object",
    "RelTime":            "object",
    "RecordingTimestamp": "object",
    "LocalTimeStamp":     "object",
    "Blinks":             "int8",
})

PARQUET_DIR = PARQUET_DIRS["EEG"]


# ---------------------------------------------------------------------------
# _clean()
# ---------------------------------------------------------------------------
# Applies all type casts and NA handling in one pass.
# Returns a clean DataFrame ready to be written to Parquet.
#
# Why float32 for electrodes?
#   EEG voltages have enough precision at float32 (~7 decimal digits).
#   Each file has ~450k rows × 65 columns. float32 halves memory vs float64
#   and compresses better in Parquet.
#
# Why int16 for trig?
#   Trial numbers are 1–50 and special codes 41/300. int16 holds –32768 to
#   32767 — more than enough. 0 is used for "no trial" (between tasks).
#
# Why int32 for phan_frame?
#   Frame numbers can reach ~50,000. int16 max is 32767, so we use int32.
#   -1 signals "unavailable".
#
# Why int64 for recording_timestamp?
#   Tobii timestamps are millisecond integers that can reach into the
#   hundreds of thousands. int32 max is ~2M which would be fine, but int64
#   is the pandas default and avoids any overflow risk.

def _clean(df: pd.DataFrame) -> pd.DataFrame:
    # --- rename ---
    df = df.rename(columns={
        'Time':               'timestamp_s',
        'Blinks':             'blink',
        'RecordingTimestamp': 'recording_timestamp',
    })

    # --- electrode columns → float32 ---
    for col in ELECTRODE_COLS + ['HEO']:
        df[col] = df[col].astype('float32')

    # --- trig: NaN or non-trial codes → 0, rest → int16 ---
    # Trig encodes trial numbers (1–50) but also uses special codes:
    #   41  → Welcome / Goodbye marker (Cues column will say "Welcome"/"Goodbye")
    #   300 → session sync trigger
    # We zero out rows where Cues is Welcome or Goodbye before keeping 1–50,
    # so that Trig=41 is preserved as a real trial number in P3005L (which has
    # 50 trials) but zeroed out when it appears as the Welcome code.
    is_meta = df['Cues'].isin(['Welcome', 'Goodbye'])
    trig = pd.to_numeric(df['Trig'], errors='coerce').fillna(0)
    trig = trig.where(~is_meta, other=0)          # zero out Welcome/Goodbye rows
    trig = trig.where(trig.between(1, 50), other=0)  # zero out sync codes (300 etc.)
    df['trig'] = trig.astype('int16')
    df = df.drop(columns=['Trig'])

    # --- cue: NaN → empty string ---
    df['cue'] = df['Cues'].fillna('').astype(str)
    df = df.drop(columns=['Cues'])

    # --- phan_frame: NaN → -1, float → int32 ---
    # Some files (e.g. S10, S18) don't have PhanFrame at all — default to -1.
    if 'PhanFrame' in df.columns:
        df['phan_frame'] = pd.to_numeric(df['PhanFrame'], errors='coerce') \
                             .fillna(-1).astype('int32')
        df = df.drop(columns=['PhanFrame'])
    else:
        df['phan_frame'] = pd.array([-1] * len(df), dtype='int32')

    # --- recording_timestamp: NaN → -1, float → int64 ---
    # Some files (e.g. S06) don't have this column at all — default to -1.
    if 'recording_timestamp' not in df.columns:
        df['recording_timestamp'] = -1
    df['recording_timestamp'] = pd.to_numeric(df['recording_timestamp'], errors='coerce') \
                                   .fillna(-1).astype('int64')

    # --- blink → int8 ---
    df['blink'] = df['blink'].astype('int8')

    # --- drop columns not needed in parquet ---
    df = df.drop(columns=['PhanTime', 'RelTime', 'LocalTimeStamp'], errors='ignore')

    # --- reorder: timestamp first, electrodes, then derived columns ---
    ordered = ['timestamp_s'] + ELECTRODE_COLS + ['HEO',
               'trig', 'cue', 'phan_frame', 'recording_timestamp', 'blink']
    df = df[ordered]

    return df


# ---------------------------------------------------------------------------
# process_file()
# ---------------------------------------------------------------------------
# Processes one EEG CSV: cleans it, saves parquet, returns the recording row.

def process_file(csv_path: Path, subject_id: str, session_id: str, paradigm: str) -> dict:
    """
    Read one EEG CSV, clean it, write parquet, return a metadata dict.
    Returns a plain dict (not ORM object) so it can cross process boundaries.
    """
    rec_id      = f"{session_id}_{paradigm}"
    parquet_rel = f"{PARQUET_DIR}/{rec_id}.parquet"

    # dtype hints skip type inference → ~30% faster CSV read
    df = pd.read_csv(csv_path, dtype=_EEG_DTYPES, low_memory=False)
    df = _clean(df)

    n_samples  = len(df)
    # drop trailing NaN timestamps from truncated recordings before computing duration
    valid_ts   = df['timestamp_s'].dropna()
    duration_s = float(valid_ts.iloc[-1] - valid_ts.iloc[0]) if len(valid_ts) > 1 else 0.0
    n_trials   = int(df['trig'][df['trig'] > 0].nunique())
    n_blinks   = int(df['blink'].sum())
    hmac       = save_parquet(df, parquet_rel)

    return {
        "id":            rec_id,
        "subject_id":    subject_id,
        "session_id":    session_id,
        "paradigm":      paradigm,
        "file_path":     parquet_rel,
        "hmac":          hmac,
        "sampling_rate": EEG_SAMPLING_RATE,
        "n_samples":     n_samples,
        "duration_s":    duration_s,
        "n_trials":      n_trials,
        "n_blinks":      n_blinks,
    }


def _worker(args: tuple) -> dict:
    """Top-level worker for ProcessPoolExecutor (must be importable at module level)."""
    return process_file(*args)


# ---------------------------------------------------------------------------
# run()
# ---------------------------------------------------------------------------

def run():
    Session = get_db()

    # --- collect all files that still need processing ---
    pending = []
    with Session() as db:
        for subj_dir in sorted(DATA_ROOT.glob('S*')):
            subject_id = subj_dir.name
            for sess_dir in sorted(subj_dir.glob('Sess*')):
                sess_num   = int(sess_dir.name.replace('Sess', ''))
                session_id = f"{subject_id}_Sess{sess_num:02d}"
                neuro_dir  = sess_dir / 'Neuroscan'
                if not neuro_dir.exists():
                    continue
                for csv_path in sorted(neuro_dir.glob('*.csv')):
                    paradigm = next((v for k, v in PARADIGM_MAP.items()
                                     if csv_path.stem.startswith(k)), None)
                    if not paradigm:
                        continue
                    rec_id = f"{session_id}_{paradigm}"
                    if db.get(EEGRecording, rec_id) is not None:
                        console.print(f"  [dim]↷ {rec_id} (already exists)[/dim]")
                        continue
                    pending.append((csv_path, subject_id, session_id, paradigm))

    if not pending:
        return

    console.print(f"  Processing {len(pending)} EEG files with {MAX_WORKERS} workers...")

    # --- parallel: read CSV + write parquet (heavy I/O, no DB) ---
    results = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("  EEG", total=len(pending))
        with ProcessPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(_worker, args): args for args in pending}
            for future in as_completed(futures):
                args = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                    _, _, session_id, paradigm = args
                    progress.advance(task)
                    console.print(
                        f"  [green]✓[/green] {result['id']:<24} "
                        f"{result['n_samples']:>9,} rows  "
                        f"{result['duration_s']:>6.1f}s  "
                        f"{result['n_trials']:>2} trials  "
                        f"{result['n_blinks']:>3} blinks"
                    )
                except Exception as e:
                    _, _, session_id, paradigm = args
                    progress.advance(task)
                    console.print(f"  [red]✗[/red] {session_id} {paradigm}: {e}")

    # --- serial: write all metadata to DB ---
    with Session() as db:
        for meta in results:
            db.add(EEGRecording(**meta))
        db.commit()
    console.print(f"  [dim]{len(results)} recordings written to DB[/dim]")


if __name__ == "__main__":
    run()
