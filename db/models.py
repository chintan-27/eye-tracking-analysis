"""
db/models.py

Defines every table in the SQLite database using SQLAlchemy.

SQLAlchemy lets us define tables as Python classes (called "mapped classes").
Each class = one table. Each class attribute = one column.
We never write CREATE TABLE SQL by hand — SQLAlchemy generates it from these
class definitions when we call Base.metadata.create_all(engine).

How the import chain works:
  Base      — a shared base class that all our table classes inherit from.
              SQLAlchemy uses it to track every table we define.
  Column    — marks a class attribute as a database column.
  ForeignKey— declares that a column references the primary key of another table.
  The type classes (Text, Integer, Float, SmallInteger) map to SQLite column types.
"""

from sqlalchemy import (
    Column,
    ForeignKey,
    Float,
    Integer,
    SmallInteger,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------
# Every table class inherits from Base.
# SQLAlchemy uses this to know which classes represent database tables.

class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# subjects
# ---------------------------------------------------------------------------
# One row per subject (S01–S31).
# Source: data/Info/all info subjects.csv

class Subject(Base):
    __tablename__ = "subjects"

    id                    = Column(Text, primary_key=True)  # "S01", "S02", …
    age                   = Column(Integer)
    sex                   = Column(Text)                    # "Male" | "Female"
    height_cm             = Column(Float)
    head_circumference_cm = Column(Float)
    nasion_inion_cm       = Column(Float)                   # front-to-back skull length
    handedness_score      = Column(Float)                   # -100 (left) to +100 (right)
    handedness_decile     = Column(Text)                    # e.g. "10th-right"
    eye_correction_left   = Column(Float)                   # diopters
    eye_correction_right  = Column(Float)
    mother_tongue         = Column(Text)                    # "FR" | "ZH" | "ES" | "EN" | "RU"
    familiarity_displays  = Column(SmallInteger)            # 1 | 2 | 3
    familiarity_bci       = Column(SmallInteger)            # 0 | 1
    jaw_width_px               = Column(Float)
    upper_nose_lower_chin_px   = Column(Float)              # nose-to-chin distance in pixels
    left_eye_width_px          = Column(Float)
    right_eye_width_px         = Column(Float)
    inner_canthi_px            = Column(Float)              # distance between inner eye corners
    outer_canthi_px            = Column(Float)              # distance between outer eye corners
    handedness_augmented       = Column(Float)              # augmented 15-item Edinburgh score

    sessions              = relationship("Session", back_populates="subject")
    landmarks             = relationship("FacialLandmark", back_populates="subject")
    eeg_recordings        = relationship("EEGRecording", back_populates="subject")
    tobii_recordings      = relationship("TobiiRecording", back_populates="subject")
    phantom_recordings    = relationship("PhantomRecording", back_populates="subject")


# ---------------------------------------------------------------------------
# facial_landmarks
# ---------------------------------------------------------------------------
# Stores the 68 face points from the iBUG 300-W detector separately.
# 136 columns on subjects would be unmanageable — one row per point is cleaner.
# 31 subjects × 68 points = 2,108 rows total.
# Source: data/Info/all info subjects.csv (x_Jaw_1, y_Jaw_1, … columns)

class FacialLandmark(Base):
    __tablename__ = "facial_landmarks"

    subject_id = Column(Text, ForeignKey("subjects.id"), primary_key=True)
    point_id   = Column(Integer, primary_key=True)  # 1–68, iBUG 300-W numbering
    region     = Column(Text)   # "Jaw" | "Right_Eyebrow" | "Left_Eyebrow" |
                                # "Nose" | "Right_Eye" | "Left_Eye" | "Mouth"
    x          = Column(Float)  # pixel coordinate from the photograph
    y          = Column(Float)

    subject    = relationship("Subject", back_populates="landmarks")


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------
# One row per session (a subject can have 1–3 sessions on different days).
# Source: data/S{id}/Sess{n}/s{id}_sess{n}.xlsx — "BEFORE EXPERIMENT" section

class Session(Base):
    __tablename__ = "sessions"

    id               = Column(Text, primary_key=True)  # "S01_Sess01"
    subject_id       = Column(Text, ForeignKey("subjects.id"))
    session_number   = Column(SmallInteger)            # 1 | 2 | 3
    date             = Column(Text)                    # "2018-06-08"
    time_of_recording = Column(Text)                   # "17:30"
    headset_number   = Column(Text)                    # which EEG cap was used
    sleep_hours      = Column(Float)
    alertness_before = Column(Text)                    # "Rested" | "Slightly tired" | …
    caffeine         = Column(SmallInteger)            # 0 | 1
    tobacco          = Column(SmallInteger)            # 0 | 1
    medication       = Column(SmallInteger)            # 0 | 1
    exercise         = Column(SmallInteger)            # 0 | 1
    hungry           = Column(SmallInteger)            # 0 | 1
    remarks          = Column(Text)                    # free-text from experimenter

    subject            = relationship("Subject", back_populates="sessions")
    alertness          = relationship("SessionAlertness", back_populates="session")
    tasks              = relationship("Task", back_populates="session")
    trials             = relationship("Trial", back_populates="session")
    eeg_recordings     = relationship("EEGRecording", back_populates="session")
    tobii_recordings   = relationship("TobiiRecording", back_populates="session")
    phantom_recordings = relationship("PhantomRecording", back_populates="session")


# ---------------------------------------------------------------------------
# session_alertness
# ---------------------------------------------------------------------------
# One row per paradigm per session — the "AFTER EACH TASK" questionnaire block.
# 5 paradigms × 63 sessions = 315 rows total.
# Source: data/S{id}/Sess{n}/s{id}_sess{n}.xlsx

class SessionAlertness(Base):
    __tablename__ = "session_alertness"

    session_id    = Column(Text, ForeignKey("sessions.id"), primary_key=True)
    paradigm      = Column(Text, primary_key=True)  # "ME"|"MI"|"SSVEP"|"P3004L"|"P3005L"
    alertness     = Column(Text)          # "Rested" | "Slightly tired" | "Moderate fatigue" | …
    noise         = Column(Text)          # "No" | "Yes: doors" | …
    interruptions = Column(Text)          # "No" | "Yes: door closed during first trial" | …
    breakdown     = Column(SmallInteger)  # 0 | 1 — technical breakdown during task
    missed_any    = Column(SmallInteger)  # 0 | 1
    missed_which  = Column(Text)          # e.g. "T in WHAT, F and O in FROM"

    session       = relationship("Session", back_populates="alertness")


# ---------------------------------------------------------------------------
# tasks
# ---------------------------------------------------------------------------
# One row per paradigm per session — captures the actual execution order of
# the 5 tasks within a session.
#
# Task order was randomised per session, so ME might be task 1 in one session
# and task 4 in another. We derive the order from the Tobii file timestamps:
# the file with the earliest LocalTimeStamp was the first task done.
#
# Exception: S03 Sess02 had P3004L and P3005L at 3pm and the rest at 5-6pm
# (two sittings). Timestamps are still the ground truth in this case.
#
# start_time is the wall clock time when the Tobii recording for this task
# started (HH:MM:SS.mmm from the first row of the Tobii CSV). This is the
# most precise marker we have for when each task began.

class Task(Base):
    __tablename__ = "tasks"

    session_id  = Column(Text, ForeignKey("sessions.id"), primary_key=True)
    paradigm    = Column(Text, primary_key=True)  # "ME"|"MI"|"SSVEP"|"P3004L"|"P3005L"
    task_order  = Column(SmallInteger)            # 1–5: position in the session
    start_time  = Column(Text)                    # "17:48:40.579" — from first Tobii row
    end_time    = Column(Text)                    # "18:00:21.432" — from last Tobii row

    session     = relationship("Session", back_populates="tasks")


# ---------------------------------------------------------------------------
# trials
# ---------------------------------------------------------------------------
# One row per trial. Sources: EEG files (Trig/Cues/PhanFrame columns) +
# E-Prime txt files (randomTime, Stimulus.OnsetDelay, Stimulus.DurationError).
#
# Each paradigm is split into repeated chunks called trials (40 per paradigm,
# 50 for P3005L). A trial is one complete cycle: fixation cross → cue → task → rest.
# Storing trial windows here means we can slice the parquet files by timestamp
# without loading the entire recording.
#
# phan_frame_start/end are the Phantom video frame numbers that correspond to
# the start and end of this trial — the anchor for video synchronisation.
#
# random_time_ms is the actual rest duration for this specific trial (varies
# 1000–1500ms per trial). Source: E-Prime randomTime field. More precise than
# estimating the trial end from the EEG Trig column alone.
#
# onset_delay_ms is how many milliseconds late the stimulus actually appeared
# on screen (E-Prime targets exact frame timing but sometimes misses by 1-2 frames).
# Source: E-Prime Stimulus.OnsetDelay field.
#
# duration_error flags whether E-Prime detected a frame timing error for this
# trial (1 = error occurred, 0 = clean). Source: E-Prime Stimulus.DurationError.

class Trial(Base):
    __tablename__ = "trials"

    id                = Column(Text, primary_key=True)  # "S01_Sess01_ME_001"
    session_id        = Column(Text, ForeignKey("sessions.id"))
    paradigm          = Column(Text)         # "ME" | "MI" | "SSVEP" | "P3004L" | "P3005L"
    trial_number      = Column(Integer)
    cue               = Column(Text)         # "Left"|"Right"|"F10 Hz"|"Stimulus"|letter…
    start_ts          = Column(Float)        # seconds from start of EEG recording
    end_ts            = Column(Float)        # derived from start_ts + timeFixation + timeStimulus + random_time_ms
    duration_s        = Column(Float)
    phan_frame_start  = Column(Integer)      # Phantom video frame at trial start (sync anchor)
    phan_frame_end    = Column(Integer)      # Phantom video frame at trial end
    random_time_ms    = Column(Integer)      # actual rest period duration — from E-Prime randomTime
    onset_delay_ms    = Column(Integer)      # ms late the stimulus appeared — from E-Prime Stimulus.OnsetDelay
    duration_error    = Column(SmallInteger) # 0 | 1 — frame timing error — from E-Prime Stimulus.DurationError
    missed            = Column(SmallInteger) # 0 | 1

    session           = relationship("Session", back_populates="trials")


# ---------------------------------------------------------------------------
# eeg_recordings
# ---------------------------------------------------------------------------
# One row per EEG parquet file (one per paradigm per session).
# 5 paradigms × 63 sessions = 315 rows total.
# Source: data/S{id}/Sess{n}/Neuroscan/{paradigm}{id}{n}.csv

class EEGRecording(Base):
    __tablename__ = "eeg_recordings"

    id            = Column(Text, primary_key=True)  # "S01_Sess01_ME"
    subject_id    = Column(Text, ForeignKey("subjects.id"))
    session_id    = Column(Text, ForeignKey("sessions.id"))
    paradigm      = Column(Text)
    file_path     = Column(Text)    # relative path: "eeg/S01_Sess01_ME.parquet"
    hmac          = Column(Text)    # SHA-256 of the parquet file — detects corruption
    sampling_rate = Column(Float)   # always 1000 Hz
    n_samples     = Column(Integer) # number of millisecond rows
    duration_s    = Column(Float)
    n_trials      = Column(Integer) # number of trials found in Trig column
    n_blinks      = Column(Integer) # total blink events (sum of Blinks column)

    subject       = relationship("Subject", back_populates="eeg_recordings")
    session       = relationship("Session", back_populates="eeg_recordings")


# ---------------------------------------------------------------------------
# tobii_recordings
# ---------------------------------------------------------------------------
# One row per Tobii parquet file (one per paradigm per session).
# Source: data/S{id}/Sess{n}/Tobii/{paradigm}{id}{n}.csv

class TobiiRecording(Base):
    __tablename__ = "tobii_recordings"

    id            = Column(Text, primary_key=True)  # "S01_Sess01_ME"
    subject_id    = Column(Text, ForeignKey("subjects.id"))
    session_id    = Column(Text, ForeignKey("sessions.id"))
    paradigm      = Column(Text)
    file_path     = Column(Text)    # relative path: "tobii/S01_Sess01_ME.parquet"
    hmac          = Column(Text)
    sampling_rate      = Column(Float)    # always 300 Hz
    n_samples          = Column(Integer)
    duration_s         = Column(Float)
    validity_pct       = Column(Float)    # % of rows where both eyes were tracked
    validity_left_pct  = Column(Float)    # % of rows where left eye was tracked
    validity_right_pct = Column(Float)    # % of rows where right eye was tracked
    # administrative metadata from first row of the CSV
    studio_version     = Column(Text)     # e.g. "3.4.8"
    recording_duration = Column(Integer)  # total recording length in ms
    resolution         = Column(Text)     # e.g. "1920 x 1080"
    fixation_filter    = Column(Text)     # e.g. "I-VT filter"
    export_date        = Column(Text)     # e.g. "8/6/2018"

    subject       = relationship("Subject", back_populates="tobii_recordings")
    session       = relationship("Session", back_populates="tobii_recordings")


# ---------------------------------------------------------------------------
# phantom_recordings
# ---------------------------------------------------------------------------
# One row per Phantom parquet file (frame timestamps parsed from XML).
# The .avi video files are not stored in the DB — too large, always on disk.
# Source: data/S{id}/Sess{n}/Phantom/{paradigm}{id}{n}.xml

class PhantomRecording(Base):
    __tablename__ = "phantom_recordings"

    id               = Column(Text, primary_key=True)  # "S01_Sess01_ME"
    subject_id       = Column(Text, ForeignKey("subjects.id"))
    session_id       = Column(Text, ForeignKey("sessions.id"))
    paradigm         = Column(Text)
    file_path        = Column(Text)     # relative path: "phantom_frames/S01_Sess01_ME.parquet"
    hmac             = Column(Text)
    video_path       = Column(Text)     # relative path to the .avi file on disk
    # recording properties
    fps              = Column(Float)    # always 167
    n_frames         = Column(Integer)
    first_frame      = Column(Integer)  # frame number where recording starts (not always 0)
    image_width      = Column(Integer)  # 320 px
    image_height     = Column(Integer)  # 240 px
    bit_depth        = Column(Integer)  # 16-bit
    trigger_time     = Column(Text)     # Phantom internal clock at hardware trigger
    # camera metadata
    camera_serial    = Column(Integer)
    camera_version   = Column(Integer)
    firmware_version = Column(Integer)
    software_version = Column(Integer)

    subject       = relationship("Subject", back_populates="phantom_recordings")
    session       = relationship("Session", back_populates="phantom_recordings")
