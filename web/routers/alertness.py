"""
web/routers/alertness.py

Alertness correlation endpoints:
  GET /api/alertness/distributions  — per-level stats for blink rate + gaze validity
"""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter

from db.database import get_db
from db.models import EEGRecording, Session, SessionAlertness, TobiiRecording

router = APIRouter(prefix="/api/alertness", tags=["alertness"])

_AL_LABELS = {1: "Rested", 2: "Slightly tired", 3: "Moderate fatigue", 4: "Extreme fatigue"}

_AL_NORM = {
    "Rested": 1, "1: rested, 1bis: slightly tired": 1,
    "Slightly tired": 2, "Slighly tired": 2,
    "Moderate fatigue": 3,
    "Extreme fatigue": 4,
}


@router.get("/distributions")
def alertness_distributions():
    """
    Return per-alertness-level distributions of DB-derived biomarkers:
      - blink_rate (blinks/min, from EEGRecording.n_blinks / duration_s)
      - gaze_validity_pct (from TobiiRecording.validity_pct)

    These are session-level summaries from the DB — no parquet loading required.
    """
    S = get_db()
    with S() as db:
        sessions   = db.query(Session).all()
        alertness  = db.query(SessionAlertness).all()
        eeg_recs   = db.query(EEGRecording).all()
        tobii_recs = db.query(TobiiRecording).all()

    # Build lookup: (session_id, paradigm) → alertness level (1-4)
    al_map: dict[tuple, int] = {}
    for a in alertness:
        level = _AL_NORM.get(a.alertness)
        if level:
            al_map[(a.session_id, a.paradigm)] = level

    # Build lookup: rec_id → (n_blinks, duration_s, validity_pct)
    eeg_lookup: dict[str, dict] = {
        r.id: {"n_blinks": r.n_blinks, "duration_s": r.duration_s}
        for r in eeg_recs
        if r.n_blinks is not None and r.duration_s and r.duration_s > 0
    }
    tobii_lookup: dict[str, float] = {
        r.id: r.validity_pct
        for r in tobii_recs
        if r.validity_pct is not None
    }

    # Group metrics by alertness level
    by_level: dict[int, dict[str, list]] = {
        lvl: {"blink_rate": [], "gaze_validity": []} for lvl in range(1, 5)
    }

    for (sess_id, paradigm), level in al_map.items():
        rec_id = f"{sess_id}_{paradigm}"
        if rec_id in eeg_lookup:
            e = eeg_lookup[rec_id]
            rate = e["n_blinks"] / e["duration_s"] * 60  # blinks/min
            by_level[level]["blink_rate"].append(round(rate, 2))
        if rec_id in tobii_lookup:
            by_level[level]["gaze_validity"].append(round(tobii_lookup[rec_id], 1))

    # Compute per-level summary stats
    def stats(values: list[float]) -> dict:
        if not values:
            return {"mean": None, "median": None, "p25": None, "p75": None,
                    "min": None, "max": None, "n": 0, "values": []}
        import statistics
        s = sorted(values)
        n = len(s)
        return {
            "mean":   round(statistics.mean(s), 3),
            "median": round(statistics.median(s), 3),
            "p25":    round(s[n // 4], 3),
            "p75":    round(s[3 * n // 4], 3),
            "min":    round(s[0], 3),
            "max":    round(s[-1], 3),
            "n":      n,
            "values": s,
        }

    result = {}
    for lvl in range(1, 5):
        result[lvl] = {
            "label":        _AL_LABELS[lvl],
            "blink_rate":   stats(by_level[lvl]["blink_rate"]),
            "gaze_validity": stats(by_level[lvl]["gaze_validity"]),
        }

    return result
