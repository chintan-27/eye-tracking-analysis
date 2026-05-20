"""
db/database.py

Handles two things:
  1. Connecting to the SQLite database and creating all tables.
  2. Reading and writing Parquet files, with HMAC integrity checks.

Why HMAC?
  Each parquet file gets a SHA-256 hash computed from its raw bytes when it is
  first written. That hash is stored in the recordings table (eeg_recordings,
  tobii_recordings, phantom_recordings). Every time we load a file, we recompute
  the hash and compare. If the file was corrupted or accidentally overwritten,
  the hashes won't match and we raise an error immediately rather than silently
  analysing bad data.

Why not store the files in the database itself?
  SQLite can store binary blobs, but signal files are large (EEG alone is ~300MB
  per file as parquet). Keeping them on disk as parquet lets pandas, DuckDB, and
  polars read them directly without any custom loading code.
"""

import hashlib
import os

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base
from db.config import DB_PATH, DATASERVER


# ---------------------------------------------------------------------------
# connect()
# ---------------------------------------------------------------------------
# Creates (or opens) the SQLite database and ensures all tables exist.
#
# create_engine() — SQLAlchemy's entry point. The string "sqlite:///..." tells
# it to use SQLite and where the file lives. If the file doesn't exist yet,
# SQLite creates it automatically.
#
# Base.metadata.create_all(engine) — reads every class that inherits from Base
# in models.py and runs the equivalent of CREATE TABLE IF NOT EXISTS for each
# one. Safe to call multiple times — it never drops or modifies existing tables.
#
# sessionmaker() — a factory that produces Session objects. A Session is how
# SQLAlchemy tracks objects you want to insert, update, or query. Think of it
# as a unit of work: you add objects to the session, then call commit() to
# write them all to the database at once.

def connect():
    """
    Open the SQLite database, create tables if they don't exist, and return
    a Session factory.

    Usage:
        Session = connect()
        with Session() as session:
            session.add(some_object)
            session.commit()
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        f"sqlite:///{DB_PATH}",
        # echo=True would print every SQL statement — useful for debugging
        echo=False,
    )

    # Create all tables defined in models.py (no-op if they already exist)
    Base.metadata.create_all(engine)

    return sessionmaker(bind=engine)


# ---------------------------------------------------------------------------
# compute_hmac()
# ---------------------------------------------------------------------------
# Computes a SHA-256 hash of raw bytes. Used both when writing a file (to
# store the hash in the DB) and when reading (to verify nothing changed).
#
# hashlib.sha256() — Python's built-in SHA-256 implementation. We feed it the
# raw bytes of the file and get back a 64-character hex string.

def compute_hmac(data: bytes) -> str:
    """Return the SHA-256 hex digest of the given bytes."""
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# save_parquet()
# ---------------------------------------------------------------------------
# Writes a DataFrame to a parquet file and returns its SHA-256 hash.
#
# df.to_parquet() — pandas method that serialises the DataFrame into the
# parquet binary format using pyarrow under the hood.
#
# compression="zstd" — zstd (Zstandard) gives the best balance of compression
# ratio and decompression speed for float arrays. EEG data with 64 channels
# compresses to roughly 1/6th of the equivalent CSV size.
#
# index=False — don't write the pandas row index (0, 1, 2, …) as a column.
# We don't need it because timestamps are already a column.
#
# After writing we read the raw bytes back to compute the hash. We read the
# file rather than hashing the in-memory DataFrame because the hash must match
# what's on disk — compression is non-deterministic in theory, so we always
# hash the actual file.

def save_parquet(df: pd.DataFrame, relative_path: str) -> str:
    """
    Write df to dataserver/{relative_path} as a zstd-compressed parquet file.
    Returns the SHA-256 hash of the written file.

    Args:
        df:             The DataFrame to save.
        relative_path:  Path relative to dataserver/, e.g. "eeg/S01_Sess01_ME.parquet"

    Returns:
        SHA-256 hex string — store this in the recordings table as hmac.
    """
    full_path = DATASERVER / relative_path
    full_path.parent.mkdir(parents=True, exist_ok=True)

    df.to_parquet(full_path, compression="zstd", index=False)

    raw_bytes = full_path.read_bytes()
    return compute_hmac(raw_bytes)


# ---------------------------------------------------------------------------
# load_parquet()
# ---------------------------------------------------------------------------
# Reads a parquet file back into a DataFrame, verifying the hash first.
#
# If the hash doesn't match we raise a ValueError immediately. This prevents
# silently analysing a corrupted or accidentally overwritten file.
#
# columns argument — parquet is columnar, so passing a list of column names
# only reads those columns from disk. Useful when you only need e.g. blink
# labels and timestamps from a 64-channel EEG file.

def load_parquet(relative_path: str, expected_hmac: str, columns: list = None) -> pd.DataFrame:
    """
    Load dataserver/{relative_path}, verify its SHA-256 hash, return a DataFrame.

    Args:
        relative_path:  Path relative to dataserver/, e.g. "eeg/S01_Sess01_ME.parquet"
        expected_hmac:  The hash stored in the recordings table when the file was written.
        columns:        Optional list of column names to load. Loads all columns if None.

    Returns:
        pandas DataFrame.

    Raises:
        FileNotFoundError: if the parquet file doesn't exist on disk.
        ValueError:        if the file's hash doesn't match expected_hmac.
    """
    full_path = DATASERVER / relative_path

    if not full_path.exists():
        raise FileNotFoundError(f"Parquet file not found: {full_path}")

    raw_bytes = full_path.read_bytes()
    actual_hmac = compute_hmac(raw_bytes)

    if actual_hmac != expected_hmac:
        raise ValueError(
            f"Integrity check failed for {relative_path}\n"
            f"  expected: {expected_hmac}\n"
            f"  actual:   {actual_hmac}\n"
            f"The file may have been corrupted or overwritten."
        )

    return pd.read_parquet(full_path, columns=columns)


# ---------------------------------------------------------------------------
# delete_parquet()
# ---------------------------------------------------------------------------
# Removes a parquet file from disk. Called when its recording row is deleted
# from the database so nothing is left orphaned on disk.

def delete_parquet(relative_path: str):
    """
    Delete dataserver/{relative_path} from disk.
    Silent no-op if the file doesn't exist.
    """
    full_path = DATASERVER / relative_path
    if full_path.exists():
        os.remove(full_path)


# ---------------------------------------------------------------------------
# get_db()
# ---------------------------------------------------------------------------
# Singleton session factory. All ingest scripts call get_db() instead of
# connect() directly. The engine and session factory are created once on first
# call and reused for every subsequent call in the same process.
#
# Usage (same as before, just use get_db() instead of connect()):
#   with get_db()() as session:
#       session.add(obj)
#       session.commit()

_session_factory = None


def get_db():
    """
    Return the singleton SQLAlchemy session factory, creating it on first call.
    """
    global _session_factory
    if _session_factory is None:
        _session_factory = connect()
    return _session_factory
