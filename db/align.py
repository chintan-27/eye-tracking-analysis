"""
db/align.py

Adds phan_frame and sync_error_ms columns to all Tobii parquet files,
permanently aligning Tobii timestamps to the Phantom frame reference clock.

Usage:
    python -m db.align                    # process all recordings
    python -m db.align S01_Sess01_ME      # single recording
    python -m db.align --dry-run          # check anchors without writing

After running, every Tobii parquet row has:
  phan_frame    (int32)   — Phantom frame index, -1 if alignment failed
  sync_error_ms (float32) — ms to nearest EEG↔Tobii sync anchor
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
from rich.console import Console
from rich.table import Table

from db.config import DATASERVER, PARQUET_DIRS
from db.database import get_db, save_parquet, load_parquet
from db.models import EEGRecording, TobiiRecording
from db.sync import extract_anchors, anchor_stats, add_phan_frame_to_tobii

console = Console()

EEG_DIR   = DATASERVER / PARQUET_DIRS["EEG"]
TOBII_DIR = DATASERVER / PARQUET_DIRS["Tobii"]


def _already_aligned(tobii_path: Path) -> bool:
    """Return True if phan_frame column already exists in this parquet."""
    schema = pq.read_schema(tobii_path)
    return "phan_frame" in schema.names


def align_recording(rec_id: str, dry_run: bool = False) -> dict:
    """
    Align one Tobii parquet to phan_frame. Returns a status dict.
    """
    eeg_path   = EEG_DIR   / f"{rec_id}.parquet"
    tobii_path = TOBII_DIR / f"{rec_id}.parquet"

    if not eeg_path.exists():
        return {"rec_id": rec_id, "status": "skip", "reason": "EEG parquet missing"}
    if not tobii_path.exists():
        return {"rec_id": rec_id, "status": "skip", "reason": "Tobii parquet missing"}

    if not dry_run and _already_aligned(tobii_path):
        return {"rec_id": rec_id, "status": "skip", "reason": "already aligned"}

    # Load only the two sync columns from EEG (fast — avoids reading 65 channels)
    eeg_sync = pd.read_parquet(eeg_path, columns=["phan_frame", "recording_timestamp"])

    try:
        pf_anchors, rt_anchors = extract_anchors(eeg_sync)
    except ValueError as e:
        return {"rec_id": rec_id, "status": "warn", "reason": str(e)}

    stats = anchor_stats(pf_anchors, rt_anchors, fps=167.0)

    if dry_run:
        return {
            "rec_id": rec_id,
            "status": "dry_run",
            **stats,
        }

    # Load full Tobii parquet, add alignment columns, overwrite
    Session = get_db()
    with Session() as db:
        tobii_rec = db.get(TobiiRecording, rec_id)
        if tobii_rec is None:
            return {"rec_id": rec_id, "status": "skip", "reason": "not in DB"}
        tobii_df = load_parquet(tobii_rec.file_path, tobii_rec.hmac)

    tobii_aligned = add_phan_frame_to_tobii(tobii_df, pf_anchors, rt_anchors)

    # Stats about coverage
    n_total     = len(tobii_aligned)
    n_covered   = int((tobii_aligned["phan_frame"] >= 0).sum())
    pct_covered = 100.0 * n_covered / n_total if n_total > 0 else 0.0

    # Write back and update DB hmac
    new_hmac = save_parquet(tobii_aligned, f"{PARQUET_DIRS['Tobii']}/{rec_id}.parquet")
    with Session() as db:
        rec = db.get(TobiiRecording, rec_id)
        rec.hmac = new_hmac
        db.commit()

    return {
        "rec_id":           rec_id,
        "status":           "ok",
        "n_anchors":        stats["n_anchors"],
        "anchor_max_gap_s": round(stats["anchor_interval_max_s"], 2),
        "pct_covered":      round(pct_covered, 1),
    }


def run(rec_ids: list[str] | None = None, dry_run: bool = False) -> None:
    Session = get_db()
    with Session() as db:
        if rec_ids:
            all_ids = rec_ids
        else:
            rows = db.query(TobiiRecording.id).order_by(TobiiRecording.id).all()
            all_ids = [r.id for r in rows]

    console.print(f"\n[bold]Aligning {len(all_ids)} Tobii recording(s) to phan_frame[/bold]"
                  + (" [dim](dry run)[/dim]" if dry_run else ""))

    results = []
    ok = warn = skip = 0
    for rec_id in all_ids:
        result = align_recording(rec_id, dry_run=dry_run)
        results.append(result)
        status = result["status"]
        if status == "ok":
            ok += 1
            console.print(
                f"  [green]✓[/green] {rec_id:<28} "
                f"anchors={result['n_anchors']:<4} "
                f"max_gap={result['anchor_max_gap_s']:.1f}s  "
                f"covered={result['pct_covered']:.0f}%"
            )
        elif status == "warn":
            warn += 1
            console.print(f"  [yellow]⚠[/yellow] {rec_id:<28} {result['reason']}")
        elif status == "dry_run":
            console.print(
                f"  [dim]~[/dim] {rec_id:<28} "
                f"anchors={result['n_anchors']:<4} "
                f"max_gap={result.get('anchor_interval_max_s', 0):.1f}s"
            )
        else:
            skip += 1
            console.print(f"  [dim]↷[/dim] {rec_id:<28} {result['reason']}")

    console.print(
        f"\n  [green]{ok} aligned[/green]  "
        f"[yellow]{warn} warnings[/yellow]  "
        f"[dim]{skip} skipped[/dim]"
    )


if __name__ == "__main__":
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]
    rec_ids = args if args else None
    run(rec_ids=rec_ids, dry_run=dry_run)
