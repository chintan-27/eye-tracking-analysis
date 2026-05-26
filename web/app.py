"""
web/app.py

FastAPI application for the Iris eye-tracking visualization dashboard.

Run:
    uvicorn web.app:app --reload --port 8000
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from web.routers import alertness, eeg, sessions, tobii, video
from web.routers.sessions import subjects_router

STATIC_DIR = Path(__file__).parent / "static"


def _sanitize(obj: Any) -> Any:
    """Recursively replace NaN/Inf floats with None so JSON serialization never fails."""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


class SafeJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return super().render(_sanitize(content))


app = FastAPI(
    title="Iris · Eye-tracking Explorer",
    docs_url="/api/docs",
    default_response_class=SafeJSONResponse,
)

# ── API routers ──────────────────────────────────────────────────────────────
app.include_router(sessions.router)
app.include_router(subjects_router)
app.include_router(eeg.router)
app.include_router(tobii.router)
app.include_router(alertness.router)
app.include_router(video.router)

# ── Static files (CSS, JS, assets served from /static/...) ──────────────────
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ── Serve index.html at root ─────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
def serve_root():
    return FileResponse(STATIC_DIR / "index.html")
