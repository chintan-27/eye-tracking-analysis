"""
video/export_meta.py

Export all recording metadata from the local DB to:
  dataserver/hpg_meta.json  — one entry per rec_id, video_path stored relative to ROOT
  dataserver/rec_ids.txt    — one rec_id per line, sorted (used as SLURM array index)

Run before syncing to HiPerGator:
    python -m video.export_meta
"""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console

from db.config import DATASERVER, ROOT
from db.database import get_db
from db.models import EEGRecording, PhantomRecording, Subject

console = Console()

META_PATH = DATASERVER / "hpg_meta.json"
IDS_PATH  = DATASERVER / "rec_ids.txt"


def export() -> None:
    S = get_db()
    records: dict[str, dict] = {}

    with S() as db:
        for rec in db.query(PhantomRecording).order_by(PhantomRecording.id).all():
            subject = db.get(Subject, rec.subject_id)
            eeg     = db.get(EEGRecording, rec.id)

            video_path = rec.video_path
            if video_path:
                try:
                    video_path = str(Path(video_path).relative_to(ROOT))
                except ValueError:
                    pass  # already relative

            records[rec.id] = {
                "rec_id":          rec.id,
                "subject_id":      rec.subject_id,
                "session_id":      rec.session_id,
                "paradigm":        rec.paradigm,
                "video_path":      video_path,
                "fps":             float(rec.fps or 167.0),
                "n_frames":        int(rec.n_frames or 0),
                "first_frame":     int(rec.first_frame or 0),
                "width":           int(rec.image_width or 320),
                "height":          int(rec.image_height or 240),
                "inner_canthi_px": float(subject.inner_canthi_px or 60.0) if subject else 60.0,
                "eeg_file_path":   eeg.file_path if eeg else None,
                "eeg_hmac":        eeg.hmac if eeg else None,
            }

    META_PATH.write_text(json.dumps(records, indent=2), encoding="utf-8")
    IDS_PATH.write_text("\n".join(sorted(records)) + "\n", encoding="utf-8")

    console.print(f"[green]✓[/green] {len(records)} recordings → {META_PATH}")
    console.print(f"[green]✓[/green] rec_ids.txt → {IDS_PATH}")


if __name__ == "__main__":
    export()
