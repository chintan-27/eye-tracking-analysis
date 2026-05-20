"""
db/ingest/subjects.py

Reads data/Info/all info subjects.csv and populates two tables:
  - subjects          (one row per subject, 31 rows)
  - facial_landmarks  (one row per landmark point per subject, 2108 rows)

Run directly to ingest:
    python -m db.ingest.subjects
"""

import re
import pandas as pd
from rich.console import Console
from db.database import get_db
from db.config import DATA_ROOT
from db.models import Subject, FacialLandmark

console = Console()


# ---------------------------------------------------------------------------
# Column name → region mapping for facial landmarks
# ---------------------------------------------------------------------------
# The CSV uses column names like x_Jaw_1, y_Right_Eyebrow_18, x_Left_eye_43.
# We parse the region out of the column name with a regex.
#
# The regex ^[xy]_(.+)_(\d+)$ breaks down as:
#   ^[xy]_   — starts with "x_" or "y_"
#   (.+)     — capture group 1: the region name (e.g. "Jaw", "Right_Eyebrow")
#   _(\d+)$  — underscore then capture group 2: the point number at the end
#
# We normalise region names to a consistent set of 7 values.

REGION_MAP = {
    "Jaw":             "Jaw",
    "Right_Eyebrow":   "Right_Eyebrow",
    "Left_Eyebrow":    "Left_Eyebrow",
    "Nose":            "Nose",
    "Right_Eye":       "Right_Eye",
    "Left_eye":        "Left_Eye",   # CSV uses lowercase "eye" here — normalise
    "Mouth":           "Mouth",
}

LANDMARK_RE = re.compile(r"^x_(.+)_(\d+)$")


def _parse_landmark_columns(columns):
    """
    Returns a list of (col_x, col_y, region, point_id) tuples for every
    landmark column pair found in the DataFrame columns.

    We only look at x_ columns — the matching y_ column is inferred.
    """
    landmarks = []
    for col in columns:
        m = LANDMARK_RE.match(col)
        if m:
            raw_region = m.group(1)
            point_id   = int(m.group(2))
            region     = REGION_MAP.get(raw_region, raw_region)
            col_y      = col.replace("x_", "y_", 1)
            landmarks.append((col, col_y, region, point_id))
    # sort by point_id so they're inserted in order 1–68
    landmarks.sort(key=lambda t: t[3])
    return landmarks


def _to_float_or_none(value):
    """
    Converts a value to float, returning None for NaN/NA.
    SQLAlchemy stores None as NULL in SQLite.
    """
    try:
        f = float(value)
        import math
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def run():
    """
    Read all info subjects.csv and insert all subjects and facial landmarks
    into the database. Safe to re-run — existing rows are skipped.
    """
    Session = get_db()

    df = pd.read_csv(DATA_ROOT / "Info" / "all info subjects.csv")

    # identify all landmark column pairs once, before looping over rows
    landmark_cols = _parse_landmark_columns(df.columns.tolist())

    with Session() as session:
        for _, row in df.iterrows():
            subject_id = row["Subjects"]  # e.g. "S01"

            # ------------------------------------------------------------------
            # Skip if this subject is already in the database.
            # session.get() looks up a row by primary key — returns None if not found.
            # ------------------------------------------------------------------
            if session.get(Subject, subject_id) is not None:
                console.print(f"  [dim]↷ {subject_id} (already exists)[/dim]")
                continue

            # ------------------------------------------------------------------
            # Build the Subject row.
            # _to_float_or_none handles the 3 subjects (S28, S30, S31) who have
            # no eye correction recorded — stored as NULL rather than 0.
            # ------------------------------------------------------------------
            subject = Subject(
                id                       = subject_id,
                age                      = int(row["Age"]),
                sex                      = row["Gender"],          # "Male" | "Female"
                height_cm                = float(row["Height"]),
                head_circumference_cm    = _to_float_or_none(row["Head circumference"]),
                nasion_inion_cm          = _to_float_or_none(row["Nasion – Inion"]),
                handedness_score         = float(row["Laterality_Index_Handedness"]),
                handedness_decile        = row["Decile_Handedness"],
                handedness_augmented     = float(row["Augmented_(15_item)_index"]),
                eye_correction_left      = _to_float_or_none(row["Eye_correction_Left"]),
                eye_correction_right     = _to_float_or_none(row["Eye_correction_Right"]),
                mother_tongue            = row["Mother_tongue"],
                familiarity_displays     = int(row["Familiarity_with_fast_displays"]),
                familiarity_bci          = int(row["Familiarity with BCI"]),
                jaw_width_px             = float(row["Jaw_Width_Px"]),
                upper_nose_lower_chin_px = float(row["Upper_Nose_Lower_Chin"]),
                left_eye_width_px        = float(row["Left_Eye_Width"]),
                right_eye_width_px       = float(row["Right_Eye_Width"]),
                inner_canthi_px          = float(row["Inner_Canthi"]),
                outer_canthi_px          = float(row["Outer_Canthi"]),
            )
            session.add(subject)

            # ------------------------------------------------------------------
            # Build one FacialLandmark row per point (68 points per subject).
            # landmark_cols is a list of (col_x, col_y, region, point_id) tuples
            # pre-computed above — we reuse it for every subject.
            # ------------------------------------------------------------------
            for col_x, col_y, region, point_id in landmark_cols:
                landmark = FacialLandmark(
                    subject_id = subject_id,
                    point_id   = point_id,
                    region     = region,
                    x          = float(row[col_x]),
                    y          = float(row[col_y]),
                )
                session.add(landmark)

            console.print(f"  [green]✓[/green] {subject_id}  [dim](68 landmarks)[/dim]")

        session.commit()


if __name__ == "__main__":
    run()
