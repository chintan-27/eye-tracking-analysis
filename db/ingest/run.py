"""
db/ingest/run.py

Master ingest script — orchestrates all 6 pipeline steps in order.
Each step calls the run() function from its own ingest module.

Usage:
    python -m db.ingest.run          # full ingest (skips already-done work)
    python -m db.ingest.run --fresh  # delete DB + parquet files, start clean
"""

import time
import shutil
import argparse

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from sqlalchemy import func

from db.config import DATASERVER, DB_PATH, PARQUET_DIRS
from db.database import get_db
from db.ingest.state import RunState, STATE_PATH
from db.models import (
    Subject, FacialLandmark, Session as SessionModel, SessionAlertness,
    Task, EEGRecording, TobiiRecording, PhantomRecording, Trial,
)

import db.ingest.subjects as subjects_mod
import db.ingest.sessions as sessions_mod
import db.ingest.eeg      as eeg_mod
import db.ingest.tobii    as tobii_mod
import db.ingest.phantom  as phantom_mod
import db.ingest.trials   as trials_mod

console = Console()


def step_header(n: int, total: int, title: str):
    console.print()
    console.rule(f"[bold cyan]Step {n}/{total} — {title}[/bold cyan]")


def print_summary(step_times: dict):
    Session = get_db()
    with Session() as db:
        counts = {
            "Subjects":           db.query(func.count(Subject.id)).scalar(),
            "Facial landmarks":   db.query(func.count(FacialLandmark.subject_id)).scalar(),
            "Sessions":           db.query(func.count(SessionModel.id)).scalar(),
            "Alertness rows":     db.query(func.count(SessionAlertness.session_id)).scalar(),
            "Tasks":              db.query(func.count(Task.session_id)).scalar(),
            "EEG recordings":     db.query(func.count(EEGRecording.id)).scalar(),
            "Tobii recordings":   db.query(func.count(TobiiRecording.id)).scalar(),
            "Phantom recordings": db.query(func.count(PhantomRecording.id)).scalar(),
            "Trials":             db.query(func.count(Trial.id)).scalar(),
        }

    console.print()
    console.rule("[bold green]Ingest Complete[/bold green]")
    console.print()

    counts_table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
    counts_table.add_column("Table", style="white")
    counts_table.add_column("Rows", justify="right", style="green")
    for name, count in counts.items():
        counts_table.add_row(name, f"{count:,}")
    console.print(counts_table)

    console.print()
    timing_table = Table(box=box.SIMPLE, show_header=False)
    timing_table.add_column("Step", style="dim")
    timing_table.add_column("Time", justify="right", style="dim")
    for step, elapsed in step_times.items():
        timing_table.add_row(step, f"{elapsed:.1f}s")
    timing_table.add_row("[bold]Total[/bold]", f"[bold]{sum(step_times.values()):.1f}s[/bold]")
    console.print(timing_table)

    console.print()
    console.print(f"  [dim]Database:[/dim]   {DB_PATH}")
    console.print(f"  [dim]Parquet:[/dim]    {DATASERVER}/eeg/  tobii/  phantom_frames/")
    console.print(f"  [dim]Run state:[/dim]  {STATE_PATH}")
    console.print()


def main():
    parser = argparse.ArgumentParser(description="Eye-BCI ingest pipeline")
    parser.add_argument("--fresh", action="store_true",
                        help="Delete existing DB and parquet files before ingesting")
    args = parser.parse_args()

    if args.fresh:
        console.print(Panel(
            "[yellow]--fresh flag detected[/yellow]\n"
            "Deleting existing database and parquet files...",
            title="Fresh Start", border_style="yellow",
        ))
        if DB_PATH.exists():
            DB_PATH.unlink()
            console.print(f"  [dim]Deleted {DB_PATH}[/dim]")
        for subdir in PARQUET_DIRS.values():
            p = DATASERVER / subdir
            if p.exists():
                shutil.rmtree(p)
                console.print(f"  [dim]Deleted {p}[/dim]")

    console.print()
    console.print(Panel(
        "[bold]Eye-BCI Multimodal Dataset[/bold]\nIngest pipeline — 6 steps",
        title="[bold cyan]Eye-Tracking DB[/bold cyan]",
        border_style="cyan",
        width=50,
    ))

    STEPS = [
        ("Subjects & Landmarks",   "subjects", subjects_mod.run),
        ("Sessions & Alertness",   "sessions", sessions_mod.run),
        ("EEG Recordings",         "eeg",      eeg_mod.run),
        ("Tobii + Task Order",     "tobii",    tobii_mod.run),
        ("Phantom Frame Metadata", "phantom",  phantom_mod.run),
        ("Trials",                 "trials",   trials_mod.run),
    ]

    state = RunState(fresh=args.fresh)

    # show previous run state if resuming
    prev = state.summary()
    if any(s != "pending" for s in prev.values()):
        console.print()
        resume_table = Table(box=box.SIMPLE, show_header=False, title="[dim]Previous run state[/dim]")
        resume_table.add_column("Step", style="dim")
        resume_table.add_column("Status")
        STATUS_STYLE = {
            "completed": "[green]✓ completed[/green]",
            "failed":    "[red]✗ failed[/red]",
            "running":   "[yellow]⚡ interrupted[/yellow]",
            "pending":   "[dim]· pending[/dim]",
        }
        for _, key, _ in STEPS:
            resume_table.add_row(key, STATUS_STYLE.get(prev[key], prev[key]))
        console.print(resume_table)

    step_times = {}

    for i, (title, key, fn) in enumerate(STEPS, 1):
        step_header(i, len(STEPS), title)

        if state.is_completed(key):
            console.print(f"  [dim]↷ Already completed — skipping[/dim]")
            step_times[title] = 0.0
            continue

        t0 = time.time()
        try:
            with state.step(key):
                fn()
            elapsed = time.time() - t0
            step_times[title] = elapsed
            console.print(f"  [bold green]✓ Done[/bold green]  [dim]({elapsed:.1f}s)[/dim]")
        except Exception:
            elapsed = time.time() - t0
            step_times[title] = elapsed
            console.print(f"  [bold red]✗ Failed[/bold red] after {elapsed:.1f}s")
            console.print_exception()
            console.print(f"  [dim]State saved to {STATE_PATH} — re-run to resume from this step.[/dim]")
            console.print("[yellow]Continuing to next step...[/yellow]")

    print_summary(step_times)


if __name__ == "__main__":
    main()
