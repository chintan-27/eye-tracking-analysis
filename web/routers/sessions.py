"""
web/routers/sessions.py

GET /api/sessions  — list of all sessions with per-paradigm alertness labels.
GET /api/sessions/{session_id} — single session detail.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from db.database import get_db
from db.models import Session, SessionAlertness, Subject

subjects_router = APIRouter(prefix="/api/subjects", tags=["subjects"])

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

PARADIGMS = ["ME", "MI", "SSVEP", "P3004L", "P3005L"]

# Normalize the messy alertness strings from the DB to 1-4
_AL_MAP: dict[str | None, int | None] = {
    "Rested":                       1,
    "1: rested, 1bis: slightly tired": 1,
    "Slightly tired":               2,
    "Slighly tired":                2,  # typo in source data
    "Moderate fatigue":             3,
    "Extreme fatigue":              4,
    "NA":                           None,
    None:                           None,
}


def _norm_alertness(raw: str | None) -> int | None:
    return _AL_MAP.get(raw, None)


def _build_session_row(sess: Session, alertness_rows: list[SessionAlertness]) -> dict:
    al_map = {a.paradigm: _norm_alertness(a.alertness) for a in alertness_rows}
    return {
        "session_id":     sess.id,
        "subject_id":     sess.subject_id,
        "session_number": sess.session_number,
        "date":           str(sess.date) if sess.date else None,
        "alertness": {p: al_map.get(p) for p in PARADIGMS},
    }


@subjects_router.get("")
def list_subjects():
    """Return all subjects with aggregated alertness and session info."""
    S = get_db()
    with S() as db:
        subjects = db.query(Subject).order_by(Subject.id).all()
        sessions = db.query(Session).all()
        alertness = db.query(SessionAlertness).all()

    # Map session_id → alertness per paradigm
    al_by_sess: dict[str, dict] = {}
    for a in alertness:
        al_by_sess.setdefault(a.session_id, {})[a.paradigm] = _norm_alertness(a.alertness)

    # Map subject_id → sessions
    sess_by_subj: dict[str, list] = {}
    for s in sessions:
        sess_by_subj.setdefault(s.subject_id, []).append(s)

    out = []
    for subj in subjects:
        subj_sessions = sess_by_subj.get(subj.id, [])
        # Per-paradigm mean alertness across all sessions
        para_al: dict[str, list] = {p: [] for p in PARADIGMS}
        for sess in subj_sessions:
            al = al_by_sess.get(sess.id, {})
            for p in PARADIGMS:
                v = al.get(p)
                if v is not None:
                    para_al[p].append(v)
        mean_al = {}
        for p, vals in para_al.items():
            mean_al[p] = round(sum(vals) / len(vals), 1) if vals else None

        out.append({
            "id":         subj.id,
            "age":        subj.age,
            "sex":        subj.sex,
            "n_sessions": len(subj_sessions),
            "alertness":  mean_al,
            "sessions": [
                {
                    "session_id":     s.id,
                    "session_number": s.session_number,
                    "date":           str(s.date) if s.date else None,
                    "paradigms":      [p for p in PARADIGMS if al_by_sess.get(s.id, {}).get(p) is not None],
                    "alertness":      {p: al_by_sess.get(s.id, {}).get(p) for p in PARADIGMS},
                }
                for s in sorted(subj_sessions, key=lambda x: x.session_number)
            ],
        })
    return out


@router.get("")
def list_sessions():
    """Return all sessions with alertness labels, sorted by subject then session number."""
    S = get_db()
    with S() as db:
        sessions = (
            db.query(Session)
            .order_by(Session.subject_id, Session.session_number)
            .all()
        )
        alertness = db.query(SessionAlertness).all()

    al_by_sess: dict[str, list] = {}
    for a in alertness:
        al_by_sess.setdefault(a.session_id, []).append(a)

    return [_build_session_row(s, al_by_sess.get(s.id, [])) for s in sessions]


@router.get("/{session_id}")
def get_session(session_id: str):
    """Return one session with alertness and subject metadata."""
    S = get_db()
    with S() as db:
        sess = db.get(Session, session_id)
        if not sess:
            raise HTTPException(404, f"Session {session_id!r} not found")
        subj = db.get(Subject, sess.subject_id)
        al_rows = (
            db.query(SessionAlertness)
            .filter(SessionAlertness.session_id == session_id)
            .all()
        )

    row = _build_session_row(sess, al_rows)
    row["subject"] = {
        "age":        subj.age if subj else None,
        "sex":        subj.sex if subj else None,
        "handedness": subj.handedness_score if subj else None,
    }
    return row
