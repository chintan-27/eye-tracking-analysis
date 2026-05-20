"""
db/ingest/state.py

Manages dataserver/run_state.json — a persistent record of which pipeline
steps have completed. On a failed or interrupted run, re-running the pipeline
skips already-completed steps entirely and resumes from where it left off.

State file structure:
{
  "started_at":   "2026-05-20T10:30:00",
  "last_updated": "2026-05-20T11:45:23",
  "steps": {
    "subjects": {
      "status":      "completed",           # pending | running | completed | failed
      "started_at":  "2026-05-20T10:30:00",
      "finished_at": "2026-05-20T10:30:15",
      "elapsed_s":   15.2,
      "error":       null                   # error message if status == failed
    },
    "eeg": {
      "status":     "failed",
      "elapsed_s":  234.5,
      "error":      "recording_timestamp column missing in S06"
    },
    ...
  }
}

A step with status "completed" is skipped on the next run.
A step with status "failed" or "running" (i.e. interrupted mid-step) is
re-run — the per-record skip-checks inside each ingest module handle
resuming at the individual session/subject level.
"""

import json
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from db.config import DATASERVER

STATE_PATH = DATASERVER / "run_state.json"

STEP_KEYS = [
    "subjects",
    "sessions",
    "eeg",
    "tobii",
    "phantom",
    "trials",
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _default_state() -> dict:
    return {
        "started_at":   _now(),
        "last_updated": _now(),
        "steps": {key: {"status": "pending"} for key in STEP_KEYS},
    }


class RunState:
    """
    Loads, updates, and persists the run state JSON file.

    Usage in run.py:
        state = RunState()
        with state.step("eeg"):     # marks running on enter, completed on exit
            eeg_mod.run()           # or failed if an exception is raised
    """

    def __init__(self, fresh: bool = False):
        DATASERVER.mkdir(parents=True, exist_ok=True)
        if fresh or not STATE_PATH.exists():
            self._state = _default_state()
            self._save()
        else:
            self._state = self._load()

    # ── persistence ──────────────────────────────────────────────────────────

    def _load(self) -> dict:
        with open(STATE_PATH) as f:
            data = json.load(f)
        # ensure all step keys exist (handles new steps added after first run)
        for key in STEP_KEYS:
            data["steps"].setdefault(key, {"status": "pending"})
        return data

    def _save(self):
        self._state["last_updated"] = _now()
        with open(STATE_PATH, "w") as f:
            json.dump(self._state, f, indent=2)

    # ── step status ───────────────────────────────────────────────────────────

    def status(self, step: str) -> str:
        return self._state["steps"].get(step, {}).get("status", "pending")

    def is_completed(self, step: str) -> bool:
        return self.status(step) == "completed"

    def summary(self) -> dict:
        """Return a dict of step → status for display."""
        return {k: v.get("status", "pending") for k, v in self._state["steps"].items()}

    # ── step lifecycle ────────────────────────────────────────────────────────

    def _mark(self, step: str, **kwargs):
        self._state["steps"][step].update(kwargs)
        self._save()

    @contextmanager
    def step(self, key: str):
        """
        Context manager that wraps a pipeline step.
        Marks the step as running on entry, completed on exit, or failed on
        exception. The exception is always re-raised so run.py can catch it.

        Usage:
            with state.step("eeg"):
                eeg_mod.run()
        """
        import time
        t0 = time.time()
        self._mark(key, status="running", started_at=_now(), error=None)
        try:
            yield
            elapsed = round(time.time() - t0, 2)
            self._mark(key, status="completed", finished_at=_now(), elapsed_s=elapsed, error=None)
        except Exception as e:
            elapsed = round(time.time() - t0, 2)
            self._mark(key, status="failed", finished_at=_now(), elapsed_s=elapsed,
                       error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
            raise

    def reset_step(self, step: str):
        """Force a completed step back to pending so it will re-run."""
        self._mark(step, status="pending", error=None)
