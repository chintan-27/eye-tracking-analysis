"""
video/run.py

Compatibility entrypoint for processing one Phantom recording.

The implementation lives in video.experiments so batch runs, single-recording
runs, and UI-driven previews share the same stateful processing path.
"""

from __future__ import annotations

import sys
from pathlib import Path

from rich.console import Console

from db.config import DATASERVER
from video.experiments import DEFAULT_COMBINATION, run_experiment

console = Console()


def run_clip(
    rec_id: str,
    write_video: bool = True,
    max_frames: int | None = None,
    use_rlof: bool = False,
    save_flow: bool = False,
    side_by_side: bool = False,
    output_fps: float | None = None,
) -> Path:
    """
    Process one recording and return the per-frame feature parquet path.

    Parameters kept for older callers. Dense flow zarr and output_fps are now
    controlled by experiment manifests rather than this wrapper.
    """
    if save_flow:
        console.print("[yellow]--save-flow is ignored by video.run; use video.experiments for run manifests.[/yellow]")
    if output_fps is not None:
        console.print("[yellow]--output-fps is ignored by video.run; output uses sync-derived recording FPS.[/yellow]")

    combination = "stable_match_rlof" if use_rlof else DEFAULT_COMBINATION
    manifest = run_experiment(
        rec_id=rec_id,
        combination=combination,
        max_frames=max_frames,
        save_videos=write_video,
        save_stage_grid=write_video,
        save_step_videos=side_by_side,
    )
    return DATASERVER / manifest["outputs"]["per_frame"]


def main() -> None:
    if len(sys.argv) < 2:
        console.print("[bold]Usage:[/bold] python -m video.run [cyan]<rec_id>[/cyan] [dim][--no-video][/dim]")
        console.print("[bold]Example:[/bold] python -m video.run [cyan]S07_Sess02_ME[/cyan]")
        raise SystemExit(1)

    rec_id = sys.argv[1]
    write_video = "--no-video" not in sys.argv
    use_rlof = "--rlof" in sys.argv
    save_flow = "--save-flow" in sys.argv
    side_by_side = "--side-by-side" in sys.argv
    max_frames = None
    output_fps = None
    for arg in sys.argv[2:]:
        if arg.startswith("--max-frames="):
            max_frames = int(arg.split("=", 1)[1])
        elif arg.startswith("--output-fps="):
            output_fps = float(arg.split("=", 1)[1])

    console.rule(f"[bold cyan]Eye Video Pipeline[/bold cyan] · [bold]{rec_id}[/bold]")
    run_clip(
        rec_id,
        write_video=write_video,
        max_frames=max_frames,
        use_rlof=use_rlof,
        save_flow=save_flow,
        side_by_side=side_by_side,
        output_fps=output_fps,
    )
    console.rule("[bold green]Complete[/bold green]")


if __name__ == "__main__":
    main()
