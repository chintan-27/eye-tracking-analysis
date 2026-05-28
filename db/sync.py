"""
db/sync.py

Core alignment utilities: maps Tobii timestamps to Phantom frame numbers
using sparse sync anchors embedded in the EEG parquet.

How the sync works (from the paper):
  - E-Prime emits a trigger every 6.6ms → Arduino → square wave → Phantom shutter + Neuroscan EEG.
    This gives EEG rows where phan_frame >= 0 (direct hardware sync).
  - The Cedrus StimTracker detects a light event on screen → fires a pulse into Tobii.
    Tobii's RecordingTimestamp at that moment is written into EEG rows as recording_timestamp.
  - Result: EEG rows where BOTH phan_frame >= 0 AND recording_timestamp >= 0 are sync anchors:
      phan_frame <--> recording_timestamp (Tobii ms)
  - Linear interpolation between anchors maps any Tobii timestamp → phan_frame (and vice versa).

sync_error_ms measures distance to the nearest anchor in Tobii-clock space.
Values > 500ms indicate the interpolation is crossing a long gap and may be unreliable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# Tobii timestamps outside the anchor range are always marked phan_frame = -1.
# Within range, we only mask if the nearest anchor gap is unreasonably large (>60s),
# which would indicate a missing sync signal rather than normal inter-anchor spacing.
# Typical max gaps are 5–20s (trial boundary triggers); linear interpolation is
# accurate to <20ms even over 20s with crystal-oscillator clocks.
SYNC_ERROR_THRESHOLD_MS = 60_000.0


def extract_anchors(eeg_df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """
    Extract (phan_frame, tobii_ms) anchor pairs from an EEG DataFrame.

    Args:
        eeg_df: DataFrame with at least columns phan_frame (int32) and
                recording_timestamp (int64). Typically loaded with only
                these two columns for efficiency.

    Returns:
        pf_anchors:  int32 array of Phantom frame numbers, sorted ascending.
        rt_anchors:  int64 array of Tobii RecordingTimestamps in ms, same order.

    Raises:
        ValueError: if fewer than 2 valid anchor pairs exist.
    """
    pf = eeg_df["phan_frame"].to_numpy(dtype=np.int32)
    rt = eeg_df["recording_timestamp"].to_numpy(dtype=np.int64)

    valid = (pf >= 0) & (rt >= 0)
    if int(valid.sum()) < 2:
        raise ValueError(
            f"Only {int(valid.sum())} valid anchor(s) found "
            "(need at least 2 for interpolation). "
            "This recording may be missing EEG↔Tobii sync markers."
        )

    pf_valid = pf[valid]
    rt_valid = rt[valid]

    order = np.argsort(rt_valid)
    return pf_valid[order].astype(np.int32), rt_valid[order].astype(np.int64)


def anchor_stats(pf_anchors: np.ndarray, rt_anchors: np.ndarray, fps: float) -> dict:
    """
    Compute quality metrics for a set of sync anchors.

    Returns dict with:
      n_anchors             — number of anchor pairs
      anchor_interval_mean_s — mean gap between consecutive anchors in seconds
      anchor_interval_max_s  — worst-case gap
      anchor_density_per_min — anchors per minute
    """
    n = len(rt_anchors)
    if n < 2:
        return {
            "n_anchors": n,
            "anchor_interval_mean_s": float("nan"),
            "anchor_interval_max_s": float("nan"),
            "anchor_density_per_min": 0.0,
        }

    intervals_ms = np.diff(rt_anchors.astype(np.float64))
    total_span_s = float(rt_anchors[-1] - rt_anchors[0]) / 1000.0

    return {
        "n_anchors": int(n),
        "anchor_interval_mean_s": float(np.mean(intervals_ms)) / 1000.0,
        "anchor_interval_max_s": float(np.max(intervals_ms)) / 1000.0,
        "anchor_density_per_min": float(n) / (total_span_s / 60.0) if total_span_s > 0 else 0.0,
    }


def tobii_ms_to_phan_frame(
    tobii_ms: np.ndarray,
    pf_anchors: np.ndarray,
    rt_anchors: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Map an array of Tobii timestamps → phan_frame indices via linear interpolation.

    tobii_ms is on the X axis (rt_anchors), phan_frame is on the Y axis (pf_anchors).
    np.interp clamps at boundary values for out-of-range inputs; we detect and
    mask those separately using sync_error_ms.

    Args:
        tobii_ms:   int64 or float64 array of Tobii RecordingTimestamps.
        pf_anchors: sorted int32 anchor array (from extract_anchors).
        rt_anchors: sorted int64 anchor array (from extract_anchors).

    Returns:
        phan_frame:    int32 array, -1 where sync_error_ms > SYNC_ERROR_THRESHOLD_MS.
        sync_error_ms: float32 array, NaN where phan_frame == -1.
    """
    tobii_float = tobii_ms.astype(np.float64)
    rt_float = rt_anchors.astype(np.float64)
    pf_float = pf_anchors.astype(np.float64)

    # Interpolate phan_frame from Tobii timestamp
    pf_interp = np.interp(tobii_float, rt_float, pf_float)

    # Compute sync_error_ms: distance to nearest anchor in Tobii-clock space
    # searchsorted gives the insertion point; we check both neighbors
    idx = np.searchsorted(rt_float, tobii_float, side="left")
    idx = np.clip(idx, 0, len(rt_float) - 1)
    idx_prev = np.clip(idx - 1, 0, len(rt_float) - 1)
    dist_right = np.abs(tobii_float - rt_float[idx])
    dist_left = np.abs(tobii_float - rt_float[idx_prev])
    sync_error = np.minimum(dist_right, dist_left).astype(np.float32)

    # Mark as invalid if error exceeds threshold or outside anchor range
    outside = (tobii_float < rt_float[0]) | (tobii_float > rt_float[-1])
    bad = outside | (sync_error > SYNC_ERROR_THRESHOLD_MS)

    pf_out = np.round(pf_interp).astype(np.int32)
    pf_out[bad] = -1
    sync_error[bad] = np.nan

    return pf_out, sync_error


def add_phan_frame_to_tobii(
    tobii_df: pd.DataFrame,
    pf_anchors: np.ndarray,
    rt_anchors: np.ndarray,
) -> pd.DataFrame:
    """
    Add phan_frame (int32) and sync_error_ms (float32) columns to a Tobii DataFrame.

    Modifies a copy — does not alter the input.
    """
    df = tobii_df.copy()
    pf_col, err_col = tobii_ms_to_phan_frame(
        df["timestamp_ms"].to_numpy(dtype=np.int64),
        pf_anchors,
        rt_anchors,
    )
    df["phan_frame"] = pf_col.astype(np.int32)
    df["sync_error_ms"] = err_col.astype(np.float32)
    return df
