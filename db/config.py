"""
db/config.py

Single source of truth for all constants used across the ingest pipeline.
Import from here instead of defining values in individual scripts.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT        = Path(__file__).parent.parent   # eye-tracking project root
DATA_ROOT   = ROOT / "data"                  # original dataset (never modified)
DATASERVER  = ROOT / "dataserver"            # parquet files + SQLite DB
DB_PATH     = DATASERVER / "eye_tracking.db"

# Parquet subdirectory per modality (relative to DATASERVER)
PARQUET_DIRS = {
    "EEG":           "eeg",
    "Tobii":         "tobii",
    "PhantomFrames": "phantom_frames",
    "VideoFeatures": "video_features",
    "VideoBiomarkers": "video_biomarkers",
}

# Zarr store directories (relative to DATASERVER) for dense array outputs
ZARR_DIRS = {
    "OpticalFlow": "optical_flow",
}

# ---------------------------------------------------------------------------
# Paradigms
# ---------------------------------------------------------------------------

# Maps file name prefix → canonical paradigm name
PARADIGM_MAP = {
    "me":     "ME",
    "mi":     "MI",
    "ssvep":  "SSVEP",
    "p3004l": "P3004L",
    "p3005l": "P3005L",
}

PARADIGMS = list(PARADIGM_MAP.values())  # ['ME', 'MI', 'SSVEP', 'P3004L', 'P3005L']

# ---------------------------------------------------------------------------
# Signal properties
# ---------------------------------------------------------------------------

EEG_SAMPLING_RATE   = 1000.0   # Hz
TOBII_SAMPLING_RATE = 300.0    # Hz
# NOTE: Phantom FPS is NOT constant — it varies by session (24/90/100/167 fps).
# Always read fps from phantom_recordings.fps in the DB, never assume 167.

# ---------------------------------------------------------------------------
# EEG electrode names (64 channels, in file column order)
# ---------------------------------------------------------------------------

ELECTRODE_COLS = [
    "FP1", "FPZ", "FP2", "AF3", "AF4",
    "F7",  "F5",  "F3",  "F1",  "FZ",  "F2",  "F4",  "F6",  "F8",
    "FT7", "FC5", "FC3", "FC1", "FCZ", "FC2", "FC4", "FC6", "FT8",
    "T7",  "C5",  "C3",  "C1",  "CZ",  "C2",  "C4",  "C6",  "T8",
    "M1",  "TP7", "CP5", "CP3", "CP1", "CPZ", "CP2", "CP4", "CP6", "TP8", "M2",
    "P7",  "P5",  "P3",  "P1",  "PZ",  "P2",  "P4",  "P6",  "P8",
    "PO7", "PO5", "PO3", "POZ", "PO4", "PO6", "PO8",
    "CB1", "O1",  "OZ",  "O2",  "CB2",
]

# Electrodes flagged as unreliable in the dataset paper (bridging/defective)
DEFECTIVE_ELECTRODES = ["PO3", "F1", "POZ", "OZ", "F3", "O2", "P8", "PO7", "FC3", "P7", "P4"]

# ---------------------------------------------------------------------------
# Trial cue filtering
# ---------------------------------------------------------------------------

# Generic/structural cue labels that appear in every paradigm.
# Remove these when extracting the paradigm-specific stimulus cue for a trial.
IGNORE_CUES = {"Fixation", "Random", "Break", "Welcome", "Goodbye", "Stimulus", ""}

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Parallelism
# ---------------------------------------------------------------------------

import os
# Number of worker processes for parallel file ingestion.
# Capped at 8 to avoid excessive memory pressure (each EEG file ~130MB in RAM).
MAX_WORKERS = min(os.cpu_count() or 4, 8)

# ---------------------------------------------------------------------------
# Tobii columns
# ---------------------------------------------------------------------------

# The columns we keep from the 86-column Tobii CSV
TOBII_KEEP_COLS = [
    "RecordingTimestamp",
    "LocalTimeStamp",
    "GazeEventType",
    "GazeEventDuration",
    "GazePointX (MCSpx)",
    "GazePointY (MCSpx)",
    "FixationPointX (MCSpx)",
    "FixationPointY (MCSpx)",
    "PupilLeft",
    "PupilRight",
    "ValidityLeft",
    "ValidityRight",
    "SaccadicAmplitude",
    "AbsoluteSaccadicDirection",
    "DistanceLeft",
    "DistanceRight",
]

TOBII_RENAME = {
    "RecordingTimestamp":        "timestamp_ms",
    "GazeEventType":             "event_type",
    "GazeEventDuration":         "event_duration",
    "GazePointX (MCSpx)":        "gaze_x",
    "GazePointY (MCSpx)":        "gaze_y",
    "FixationPointX (MCSpx)":    "fixation_x",
    "FixationPointY (MCSpx)":    "fixation_y",
    "PupilLeft":                 "pupil_left",
    "PupilRight":                "pupil_right",
    "ValidityLeft":              "validity_left",
    "ValidityRight":             "validity_right",
    "SaccadicAmplitude":         "saccade_amp",
    "AbsoluteSaccadicDirection": "saccade_dir",
    "DistanceLeft":              "distance_left",
    "DistanceRight":             "distance_right",
}
