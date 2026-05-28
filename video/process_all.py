"""
Batch process Phantom recordings through versioned experiment runs.

Usage:
    python -m video.process_all
    python -m video.process_all --no-video
    python -m video.process_all --limit=5
    python -m video.process_all --limit=5 --max-frames=100 --no-video
    python -m video.process_all --only-missing
    python -m video.process_all --workers=8
    python -m video.process_all --run-id full_dataset_v1 --only-missing --no-video --workers=8
"""

from __future__ import annotations

import sys
from rich.console import Console

from video.experiments import DEFAULT_COMBINATION, run_many, _all_recordings

console = Console()


def main() -> None:
    write_video = "--no-video" not in sys.argv
    only_missing = "--only-missing" in sys.argv
    save_step_videos = "--save-step-videos" in sys.argv
    run_id = None
    combinations = [DEFAULT_COMBINATION]
    limit = None
    max_frames = None
    workers = 1
    for arg in sys.argv[1:]:
        if arg.startswith("--limit="):
            limit = int(arg.split("=", 1)[1])
        elif arg.startswith("--max-frames="):
            max_frames = int(arg.split("=", 1)[1])
        elif arg.startswith("--run-id="):
            run_id = arg.split("=", 1)[1]
        elif arg.startswith("--combination="):
            combinations = [arg.split("=", 1)[1]]
        elif arg.startswith("--workers="):
            workers = int(arg.split("=", 1)[1])

    rec_ids = _all_recordings()

    if limit is not None:
        rec_ids = rec_ids[:limit]

    console.print(f"[bold]Processing {len(rec_ids)} Phantom recordings[/bold]")
    run_many(
        rec_ids=rec_ids,
        combinations=combinations,
        run_id=run_id,
        max_frames=max_frames,
        save_videos=write_video,
        save_stage_grid=write_video,
        save_step_videos=save_step_videos,
        only_missing=only_missing,
        workers=workers,
    )


if __name__ == "__main__":
    main()
