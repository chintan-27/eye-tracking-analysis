"""
db/ingest/phantom.py

Reads every Phantom high-speed camera XML file and:
  1. Parses header metadata from CineFileHeader, BitmapInfoHeader, CameraSetup
  2. Extracts per-frame timestamps and exposure values from TIMEBLOCK/EXPOSUREBLOCK
  3. Writes frame data to a zstd-compressed Parquet file in dataserver/phantom_frames/
  4. Inserts one row into phantom_recordings

The .avi video files are not touched — they stay on disk as-is.
video_path in phantom_recordings points to the .avi alongside the XML.

Parquet columns written:
  frame_number   int32    — Phantom frame index (starts at first_frame, not 0)
  timestamp      str      — Phantom internal clock "HH:MM:SS.mmm microseconds"
                            e.g. "09:10:55.685 294.02"
                            NOTE: Phantom clock is set to year 2000, not wall clock.
                            Sync to EEG/Tobii is done via PhanFrame column in EEG.
  exposure_us    float32  — exposure duration in microseconds for this frame

Run directly to ingest all Phantom XML files:
    python -m db.ingest.phantom
"""

from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
import xml.etree.ElementTree as ET
import pandas as pd
console = Console()
from db.database import get_db, save_parquet
from db.config import DATA_ROOT, PARADIGM_MAP, PARQUET_DIRS, MAX_WORKERS
from db.models import PhantomRecording

PARQUET_DIR = PARQUET_DIRS["PhantomFrames"]


# ---------------------------------------------------------------------------
# _parse_xml()
# ---------------------------------------------------------------------------
# Parses the XML file and returns:
#   - header: dict of scalar metadata fields
#   - df: DataFrame of per-frame data (frame_number, timestamp, exposure_us)
#
# The XML has three relevant sections:
#   CineFileHeader  — recording-level info (frame count, trigger time)
#   BitmapInfoHeader — image dimensions and bit depth
#   CameraSetup    — camera hardware info (fps, serial, versions)
#   TIMEBLOCK      — <Date frame="N"> and <Time frame="N"> for every frame
#   EXPOSUREBLOCK  — <Exp frame="N"> for every frame

def _parse_xml(xml_path: Path) -> tuple[dict, pd.DataFrame]:
    tree = ET.parse(xml_path)
    root = tree.getroot()

    def get(path):
        val = root.findtext(path)
        return val.strip() if val else None

    def get_int(path):
        val = get(path)
        try:
            return int(val) if val else None
        except ValueError:
            return None

    # --- scalar header metadata ---
    header = {
        "fps":              get_int("CameraSetup/FrameRateDouble"),
        "n_frames":         get_int("CineFileHeader/TotalImageCount"),
        "first_frame":      get_int("CineFileHeader/FirstImageNo"),
        "image_width":      get_int("BitmapInfoHeader/biWidth"),
        "image_height":     get_int("BitmapInfoHeader/biHeight"),
        "bit_depth":        get_int("BitmapInfoHeader/biBitCount"),
        "trigger_time":     (
            (get("CineFileHeader/TriggerTime/Date") or "") + " " +
            (get("CineFileHeader/TriggerTime/Time") or "")
        ).strip(),
        "camera_serial":    get_int("CameraSetup/Serial"),
        "camera_version":   get_int("CameraSetup/CameraVersion"),
        "firmware_version": get_int("CameraSetup/FirmwareVersion"),
        "software_version": get_int("CameraSetup/SoftwareVersion"),
    }

    # --- per-frame data from TIMEBLOCK and EXPOSUREBLOCK ---
    # Build dicts keyed by frame number, then merge into a DataFrame.
    timeblock  = root.find("TIMEBLOCK")
    expblock   = root.find("EXPOSUREBLOCK")

    times = {el.get("frame"): el.text for el in timeblock.findall("Time")}
    exps  = {el.get("frame"): el.text for el in expblock.findall("Exp")}

    # Sort by frame number (they are strings — convert to int for sort)
    frames_sorted = sorted(times.keys(), key=lambda x: int(x))

    frame_numbers = [int(f) for f in frames_sorted]
    timestamps    = [times[f] for f in frames_sorted]
    exposures     = [float(exps[f]) if exps.get(f) else None for f in frames_sorted]

    df = pd.DataFrame({
        "frame_number": pd.array(frame_numbers, dtype="int32"),
        "timestamp":    timestamps,
        "exposure_us":  pd.array(exposures, dtype="float32"),
    })

    return header, df


# ---------------------------------------------------------------------------
# process_file()
# ---------------------------------------------------------------------------

def process_file(xml_path: Path, subject_id: str, session_id: str, paradigm: str) -> dict:
    """Parse XML, write parquet, return a metadata dict (picklable for multiprocessing)."""
    rec_id      = f"{session_id}_{paradigm}"
    parquet_rel = f"{PARQUET_DIR}/{rec_id}.parquet"
    avi_path    = xml_path.with_suffix(".avi")
    video_path  = str(avi_path) if avi_path.exists() else None

    header, df = _parse_xml(xml_path)
    hmac = save_parquet(df, parquet_rel)

    return {
        "id":               rec_id,
        "subject_id":       subject_id,
        "session_id":       session_id,
        "paradigm":         paradigm,
        "file_path":        parquet_rel,
        "hmac":             hmac,
        "video_path":       video_path,
        "fps":              header["fps"],
        "n_frames":         header["n_frames"],
        "first_frame":      header["first_frame"],
        "image_width":      header["image_width"],
        "image_height":     header["image_height"],
        "bit_depth":        header["bit_depth"],
        "trigger_time":     header["trigger_time"],
        "camera_serial":    header["camera_serial"],
        "camera_version":   header["camera_version"],
        "firmware_version": header["firmware_version"],
        "software_version": header["software_version"],
    }


def _worker(args: tuple) -> dict:
    return process_file(*args)


# ---------------------------------------------------------------------------
# run()
# ---------------------------------------------------------------------------

def run():
    Session = get_db()

    # collect pending files
    pending = []
    with Session() as db:
        for subj_dir in sorted(DATA_ROOT.glob("S*")):
            subject_id = subj_dir.name
            for sess_dir in sorted(subj_dir.glob("Sess*")):
                sess_num    = int(sess_dir.name.replace("Sess", ""))
                session_id  = f"{subject_id}_Sess{sess_num:02d}"
                phantom_dir = sess_dir / "Phantom"
                if not phantom_dir.exists():
                    continue
                for xml_path in sorted(phantom_dir.glob("*.xml")):
                    paradigm = next((v for k, v in PARADIGM_MAP.items()
                                     if xml_path.stem.startswith(k)), None)
                    if not paradigm:
                        continue
                    rec_id = f"{session_id}_{paradigm}"
                    if db.get(PhantomRecording, rec_id) is not None:
                        console.print(f"  [dim]↷ {rec_id} (already exists)[/dim]")
                        continue
                    pending.append((xml_path, subject_id, session_id, paradigm))

    if not pending:
        return

    console.print(f"  Processing {len(pending)} Phantom XML files with {MAX_WORKERS} workers...")

    results = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("  Phantom", total=len(pending))
        with ProcessPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(_worker, args): args for args in pending}
            for future in as_completed(futures):
                args = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                    progress.advance(task)
                    console.print(
                        f"  [green]✓[/green] {result['id']:<24} "
                        f"{result['n_frames']:>7,} frames  "
                        f"{result['fps']} fps  "
                        f"{result['image_width']}×{result['image_height']}px"
                    )
                except Exception as e:
                    progress.advance(task)
                    console.print(f"  [red]✗[/red] {args[2]} {args[3]}: {e}")

    with Session() as db:
        for meta in results:
            db.add(PhantomRecording(**meta))
        db.commit()
    console.print(f"  [dim]{len(results)} recordings written to DB[/dim]")


if __name__ == "__main__":
    run()
