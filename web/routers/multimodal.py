"""
web/routers/multimodal.py

Multimodal alignment endpoints: all streams keyed by Phantom frame number.

Requires Tobii parquets to have been aligned via: python -m db.align
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from fastapi import APIRouter, HTTPException

from db.database import get_db
from db.models import EEGRecording, PhantomRecording, TobiiRecording
from db.sync import extract_anchors, anchor_stats
from web.routers.pipeline import _find_parquet, DEFAULT_COMBINATION

router = APIRouter(prefix="/api/multimodal", tags=["multimodal"])

DATASERVER   = Path("dataserver")
EEG_DIR      = DATASERVER / "eeg"
TOBII_DIR    = DATASERVER / "tobii"

# EEG channels shown in multimodal viewer
_EEG_CHANNELS = ["FP1", "FZ", "CZ", "CPZ", "OZ"]

# Saccade detection thresholds from per_frame.parquet p_cr_velocity_mms
_SACCADE_VEL_TH    = 0.5    # mm/s
_SACCADE_MIN_FRAMES = 3
_SACCADE_MIN_ISI    = 10    # inter-saccade interval in frames


def _get_eeg_rec(rec_id: str) -> EEGRecording:
    S = get_db()
    with S() as db:
        rec = db.get(EEGRecording, rec_id)
    if not rec:
        raise HTTPException(404, f"EEG recording {rec_id!r} not found")
    return rec


def _get_tobii_rec(rec_id: str) -> TobiiRecording:
    S = get_db()
    with S() as db:
        rec = db.get(TobiiRecording, rec_id)
    if not rec:
        raise HTTPException(404, f"Tobii recording {rec_id!r} not found")
    return rec


def _get_phantom_rec(rec_id: str) -> PhantomRecording:
    S = get_db()
    with S() as db:
        rec = db.get(PhantomRecording, rec_id)
    if not rec:
        raise HTTPException(404, f"Phantom recording {rec_id!r} not found")
    return rec


def _tobii_aligned(rec_id: str) -> bool:
    """Return True if the Tobii parquet for this recording has a phan_frame column."""
    p = TOBII_DIR / f"{rec_id}.parquet"
    if not p.exists():
        return False
    schema = pq.read_schema(p)
    return "phan_frame" in schema.names


# ── sync quality ──────────────────────────────────────────────────────────────

@router.get("/{rec_id}/sync_quality")
def multimodal_sync_quality(rec_id: str):
    """Return EEG↔Tobii sync anchor statistics for this recording."""
    eeg_path   = EEG_DIR   / f"{rec_id}.parquet"
    tobii_path = TOBII_DIR / f"{rec_id}.parquet"

    if not eeg_path.exists():
        raise HTTPException(404, "EEG parquet not found")

    eeg_sync = pd.read_parquet(eeg_path, columns=["phan_frame", "recording_timestamp"])
    try:
        pf_anchors, rt_anchors = extract_anchors(eeg_sync)
        stats = anchor_stats(pf_anchors, rt_anchors, fps=167.0)
    except ValueError as e:
        return {"rec_id": rec_id, "aligned": False, "error": str(e)}

    result: dict = {
        "rec_id":  rec_id,
        "aligned": _tobii_aligned(rec_id),
        **stats,
    }

    if tobii_path.exists() and _tobii_aligned(rec_id):
        tobii = pd.read_parquet(tobii_path, columns=["phan_frame", "sync_error_ms"])
        n = len(tobii)
        n_covered = int((tobii["phan_frame"] >= 0).sum())
        result["n_tobii_rows"]    = n
        result["pct_covered"]     = round(100.0 * n_covered / n, 1) if n else 0.0
        valid_err = tobii["sync_error_ms"].dropna()
        result["sync_error_mean_ms"]   = round(float(valid_err.mean()), 0) if len(valid_err) else None
        result["sync_error_max_ms"]    = round(float(valid_err.max()),  0) if len(valid_err) else None

    return result


# ── at_frame ─────────────────────────────────────────────────────────────────

@router.get("/{rec_id}/at_frame")
def multimodal_at_frame(
    rec_id:      str,
    n:           int,
    eeg_win_s:   float = 4.0,
    run_id:      str | None = None,
    combination: str = DEFAULT_COMBINATION,
):
    """
    Return all streams at Phantom frame n.
    n is the Phantom frame index (phan_frame, not local video frame).
    """
    eeg_path   = EEG_DIR   / f"{rec_id}.parquet"
    tobii_path = TOBII_DIR / f"{rec_id}.parquet"

    result: dict = {"rec_id": rec_id, "phan_frame": n}

    # ── EEG ──────────────────────────────────────────────────────────────────
    if eeg_path.exists():
        eeg_rec = _get_eeg_rec(rec_id)
        eeg = pq.read_table(
            eeg_path,
            columns=["timestamp_s", "phan_frame", "blink"] + _EEG_CHANNELS,
        )
        pf_arr = eeg["phan_frame"].to_numpy(zero_copy_only=False).astype(np.int32)
        ts_arr = eeg["timestamp_s"].to_numpy(zero_copy_only=False).astype(np.float64)

        valid_pf = pf_arr >= 0
        if valid_pf.sum() >= 2:
            pf_v = pf_arr[valid_pf]
            ts_v = ts_arr[valid_pf]
            order = np.argsort(pf_v)
            t_center = float(np.interp(n, pf_v[order], ts_v[order]))
        else:
            t_center = None

        if t_center is not None:
            half = eeg_win_s / 2.0
            mask = (ts_arr >= t_center - half) & (ts_arr <= t_center + half)
            seg = eeg.filter(mask)
            t_rel = (seg["timestamp_s"].to_numpy(zero_copy_only=False) - t_center).tolist()
            result["eeg"] = {
                "t_s":   [round(v, 4) for v in t_rel],
                "blink": seg["blink"].to_pylist(),
                "channels": {
                    ch: [
                        None if not np.isfinite(v) else round(float(v), 2)
                        for v in seg[ch].to_numpy(zero_copy_only=False)
                    ]
                    for ch in _EEG_CHANNELS
                },
                "t_center_s": round(t_center, 4),
            }
        else:
            result["eeg"] = None
    else:
        result["eeg"] = None

    # ── Tobii ────────────────────────────────────────────────────────────────
    if tobii_path.exists() and _tobii_aligned(rec_id):
        tobii_cols = [
            "phan_frame", "sync_error_ms", "timestamp_ms",
            "gaze_x", "gaze_y", "fixation_x", "fixation_y",
            "pupil_left", "pupil_right", "validity_left", "validity_right",
            "event_type", "saccade_amp", "saccade_dir",
        ]
        tobii = pd.read_parquet(tobii_path, columns=tobii_cols)
        # Find closest aligned row to requested phan_frame
        valid_t = tobii[tobii["phan_frame"] >= 0]
        if len(valid_t) > 0:
            diff = np.abs(valid_t["phan_frame"].to_numpy(dtype=np.int32) - n)
            closest_idx = int(diff.argmin())
            row = valid_t.iloc[closest_idx]
            result["tobii"] = {
                "phan_frame":    int(row["phan_frame"]),
                "timestamp_ms":  int(row["timestamp_ms"]),
                "sync_error_ms": None if pd.isna(row["sync_error_ms"]) else round(float(row["sync_error_ms"]), 1),
                "gaze_x":        None if pd.isna(row["gaze_x"]) else round(float(row["gaze_x"]), 1),
                "gaze_y":        None if pd.isna(row["gaze_y"]) else round(float(row["gaze_y"]), 1),
                "fixation_x":    None if pd.isna(row["fixation_x"]) else round(float(row["fixation_x"]), 1),
                "fixation_y":    None if pd.isna(row["fixation_y"]) else round(float(row["fixation_y"]), 1),
                "pupil_left":    None if pd.isna(row["pupil_left"]) else round(float(row["pupil_left"]), 3),
                "pupil_right":   None if pd.isna(row["pupil_right"]) else round(float(row["pupil_right"]), 3),
                "valid":         int(row["validity_left"]) == 0 and int(row["validity_right"]) == 0,
                "event_type":    str(row["event_type"]),
                "saccade_amp":   None if pd.isna(row["saccade_amp"]) else round(float(row["saccade_amp"]), 2),
                "saccade_dir":   None if pd.isna(row["saccade_dir"]) else round(float(row["saccade_dir"]), 1),
            }
        else:
            result["tobii"] = None
    else:
        result["tobii"] = None
        if tobii_path.exists() and not _tobii_aligned(rec_id):
            result["tobii_unaligned"] = True

    # ── Pipeline per-frame ────────────────────────────────────────────────────
    try:
        pf_path, actual_run = _find_parquet(rec_id, run_id, combination, "per_frame.parquet")
        pf_cols = [
            "phan_frame", "frame_number", "timestamp_eeg_ms",
            "aperture_mm", "aperture_norm", "blink_state",
            "pupil_diameter_mm", "pupil_x", "pupil_y",
            "p_cr_x", "p_cr_y", "p_cr_velocity_mms",
            "flow_mag_mean_eyelid", "flow_mag_mean_pupil",
            "transform_tx", "transform_ty",
        ]
        pf_df = pd.read_parquet(pf_path, columns=pf_cols)
        diff = np.abs(pf_df["phan_frame"].to_numpy(dtype=np.int32) - n)
        closest = int(diff.argmin())
        row = pf_df.iloc[closest]

        def _f(v):
            return None if (isinstance(v, float) and not np.isfinite(v)) else round(float(v), 4)

        result["pipeline"] = {
            "phan_frame":          int(row["phan_frame"]),
            "frame_number":        int(row["frame_number"]),
            "timestamp_eeg_ms":    int(row["timestamp_eeg_ms"]),
            "aperture_mm":         _f(row["aperture_mm"]),
            "aperture_norm":       _f(row["aperture_norm"]),
            "blink_state":         int(row["blink_state"]),
            "pupil_diameter_mm":   _f(row["pupil_diameter_mm"]),
            "pupil_x":             _f(row["pupil_x"]),
            "pupil_y":             _f(row["pupil_y"]),
            "p_cr_x":              _f(row["p_cr_x"]),
            "p_cr_y":              _f(row["p_cr_y"]),
            "p_cr_velocity_mms":   _f(row["p_cr_velocity_mms"]),
            "flow_mag_mean_eyelid":_f(row["flow_mag_mean_eyelid"]),
            "flow_mag_mean_pupil": _f(row["flow_mag_mean_pupil"]),
            "transform_tx":        _f(row["transform_tx"]),
            "transform_ty":        _f(row["transform_ty"]),
        }
        result["run_id"] = actual_run
    except HTTPException:
        result["pipeline"] = None

    return result


# ── saccades ──────────────────────────────────────────────────────────────────

@router.get("/{rec_id}/saccades")
def multimodal_saccades(
    rec_id:      str,
    run_id:      str | None = None,
    combination: str = DEFAULT_COMBINATION,
):
    """
    Return saccade events from both Tobii (labeled) and Phantom per_frame
    (p_cr_velocity threshold), plus a frame-level match comparison.
    """
    tobii_path = TOBII_DIR / f"{rec_id}.parquet"

    # ── Tobii saccades ────────────────────────────────────────────────────────
    tobii_saccades = []
    if tobii_path.exists() and _tobii_aligned(rec_id):
        tobii = pd.read_parquet(
            tobii_path,
            columns=["phan_frame", "timestamp_ms", "event_type",
                     "event_duration", "saccade_amp", "saccade_dir",
                     "gaze_x", "gaze_y"],
        )
        sac_df = tobii[tobii["event_type"] == "Saccade"].copy()
        # Group consecutive saccade rows into events (same event_duration value)
        if len(sac_df) > 0:
            sac_df = sac_df[sac_df["phan_frame"] >= 0]
            # Take the first row of each contiguous saccade block as onset
            is_new = sac_df["event_duration"].diff().fillna(1) != 0
            onsets = sac_df[is_new]
            for _, row in onsets.iterrows():
                tobii_saccades.append({
                    "phan_frame":  int(row["phan_frame"]) if row["phan_frame"] >= 0 else None,
                    "timestamp_ms":int(row["timestamp_ms"]),
                    "amplitude_deg": None if pd.isna(row["saccade_amp"]) else round(float(row["saccade_amp"]), 2),
                    "direction_deg": None if pd.isna(row["saccade_dir"]) else round(float(row["saccade_dir"]), 1),
                    "gaze_x": None if pd.isna(row["gaze_x"]) else round(float(row["gaze_x"]), 1),
                    "gaze_y": None if pd.isna(row["gaze_y"]) else round(float(row["gaze_y"]), 1),
                })

    # ── Phantom saccades ──────────────────────────────────────────────────────
    phantom_saccades = []
    try:
        pf_path, _ = _find_parquet(rec_id, run_id, combination, "per_frame.parquet")
        pf_df = pd.read_parquet(pf_path, columns=["phan_frame", "frame_number", "p_cr_velocity_mms"])

        vel = pf_df["p_cr_velocity_mms"].fillna(0.0).to_numpy(dtype=np.float64)
        # 5-frame rolling mean
        kernel = np.ones(5) / 5.0
        vel_smooth = np.convolve(vel, kernel, mode="same")
        pf_frames = pf_df["phan_frame"].to_numpy(dtype=np.int32)
        fn_frames = pf_df["frame_number"].to_numpy(dtype=np.int32)

        above = vel_smooth > _SACCADE_VEL_TH
        in_saccade = False
        onset_frame = -1
        onset_pf = -1
        peak_vel = 0.0
        last_offset = -_SACCADE_MIN_ISI

        for i, (v, flag) in enumerate(zip(vel_smooth, above)):
            if not in_saccade and flag and (int(fn_frames[i]) - last_offset) >= _SACCADE_MIN_ISI:
                in_saccade = True
                onset_frame = int(fn_frames[i])
                onset_pf = int(pf_frames[i])
                peak_vel = float(v)
            elif in_saccade:
                if float(v) > peak_vel:
                    peak_vel = float(v)
                if not flag:
                    duration = int(fn_frames[i]) - onset_frame
                    if duration >= _SACCADE_MIN_FRAMES:
                        phantom_saccades.append({
                            "phan_frame":       onset_pf,
                            "frame_number":     onset_frame,
                            "duration_frames":  duration,
                            "velocity_peak_mms": round(peak_vel, 3),
                        })
                    last_offset = int(fn_frames[i])
                    in_saccade = False
    except HTTPException:
        pass

    # ── comparison ────────────────────────────────────────────────────────────
    comparison = []
    tobii_onsets = [s["phan_frame"] for s in tobii_saccades if s["phan_frame"] is not None]
    phantom_onsets = [s["phan_frame"] for s in phantom_saccades]

    for t_pf in tobii_onsets:
        if not phantom_onsets:
            comparison.append({"tobii_phan_frame": t_pf, "phantom_phan_frame": None, "lag_frames": None, "matched": False})
            continue
        diffs = np.abs(np.array(phantom_onsets, dtype=np.int32) - t_pf)
        best_idx = int(diffs.argmin())
        lag = int(phantom_onsets[best_idx]) - t_pf
        matched = abs(lag) <= 20   # within ~120ms at 167fps
        comparison.append({
            "tobii_phan_frame":   t_pf,
            "phantom_phan_frame": phantom_onsets[best_idx],
            "lag_frames":         lag,
            "matched":            matched,
        })

    n_matched = sum(1 for c in comparison if c["matched"])
    match_pct = round(100.0 * n_matched / len(comparison), 1) if comparison else None

    return {
        "rec_id":           rec_id,
        "tobii_saccades":   tobii_saccades,
        "phantom_saccades": phantom_saccades,
        "comparison":       comparison,
        "n_tobii":          len(tobii_saccades),
        "n_phantom":        len(phantom_saccades),
        "n_matched":        n_matched,
        "match_pct":        match_pct,
    }


# ── blink alignment ───────────────────────────────────────────────────────────

@router.get("/{rec_id}/blink_alignment")
def multimodal_blink_alignment(
    rec_id:      str,
    window_ms:   int = 500,
    run_id:      str | None = None,
    combination: str = DEFAULT_COMBINATION,
):
    """
    Return mean ± SEM curves for aperture, EEG FP1, and Tobii pupil,
    all aligned to blink onset (blink_state transitions 0→1 in per_frame).
    """
    eeg_path   = EEG_DIR   / f"{rec_id}.parquet"
    tobii_path = TOBII_DIR / f"{rec_id}.parquet"

    try:
        pf_path, _ = _find_parquet(rec_id, run_id, combination, "per_frame.parquet")
    except HTTPException:
        raise HTTPException(404, "Pipeline results not found — run HPG job first")

    pf_cols = ["phan_frame", "frame_number", "timestamp_eeg_ms", "aperture_mm", "blink_state", "fps"]
    pf_df = pd.read_parquet(pf_path, columns=pf_cols)

    fps = float(pf_df["fps"].iloc[0]) if len(pf_df) else 167.0
    half_frames = int(window_ms / 1000.0 * fps)

    # Find blink onsets: blink_state transitions from 0 (OPEN) to 1 (CLOSING)
    states = pf_df["blink_state"].to_numpy(dtype=np.int8)
    onsets = []
    for i in range(1, len(states)):
        if states[i - 1] == 0 and states[i] == 1:
            onsets.append(i)

    if not onsets:
        raise HTTPException(404, "No blink onsets found in per_frame data")

    n_steps = 2 * half_frames + 1
    t_ms = np.linspace(-window_ms, window_ms, n_steps).tolist()

    aperture_epochs = []
    eeg_fp1_epochs = []
    tobii_pupil_epochs = []

    # Load EEG FP1 if available
    eeg_fp1 = None
    eeg_ts = None
    if eeg_path.exists():
        eeg_data = pd.read_parquet(eeg_path, columns=["timestamp_s", "FP1"])
        eeg_ts = eeg_data["timestamp_s"].to_numpy(dtype=np.float64)
        eeg_fp1 = eeg_data["FP1"].to_numpy(dtype=np.float32)

    # Load Tobii pupil if aligned
    tobii_pf = None
    tobii_pupil = None
    if tobii_path.exists() and _tobii_aligned(rec_id):
        tobii_data = pd.read_parquet(tobii_path, columns=["phan_frame", "pupil_left"])
        tobii_pf = tobii_data["phan_frame"].to_numpy(dtype=np.int32)
        tobii_pupil = tobii_data["pupil_left"].to_numpy(dtype=np.float32)

    aperture_arr = pf_df["aperture_mm"].to_numpy(dtype=np.float32)
    ts_eeg_ms = pf_df["timestamp_eeg_ms"].to_numpy(dtype=np.int64)
    pf_arr = pf_df["phan_frame"].to_numpy(dtype=np.int32)

    for onset in onsets:
        start = onset - half_frames
        end   = onset + half_frames + 1
        if start < 0 or end > len(pf_df):
            continue

        # Aperture epoch
        ap_epoch = aperture_arr[start:end].astype(np.float64)
        if np.isnan(ap_epoch).any():
            continue
        # Baseline correct: subtract mean of pre-onset window
        baseline = np.mean(ap_epoch[:half_frames]) if half_frames > 0 else 0.0
        aperture_epochs.append(ap_epoch - baseline)

        # EEG FP1 epoch (via timestamp_eeg_ms)
        if eeg_ts is not None and eeg_fp1 is not None:
            t_center_s = ts_eeg_ms[onset] / 1000.0
            t_win_s = window_ms / 1000.0
            mask = (eeg_ts >= t_center_s - t_win_s) & (eeg_ts <= t_center_s + t_win_s)
            seg_fp1 = eeg_fp1[mask]
            seg_ts  = eeg_ts[mask]
            if len(seg_ts) >= n_steps // 2:
                # Resample to n_steps
                t_target = t_center_s + np.linspace(-t_win_s, t_win_s, n_steps)
                fp1_resampled = np.interp(t_target, seg_ts, seg_fp1.astype(np.float64))
                baseline_fp1 = np.mean(fp1_resampled[:half_frames]) if half_frames > 0 else 0.0
                eeg_fp1_epochs.append(fp1_resampled - baseline_fp1)

        # Tobii pupil epoch (via phan_frame)
        if tobii_pf is not None and tobii_pupil is not None:
            pf_center = int(pf_arr[onset])
            pf_start  = int(pf_arr[max(0, start)])
            pf_end    = int(pf_arr[min(len(pf_arr) - 1, end - 1)])
            mask = (tobii_pf >= pf_start) & (tobii_pf <= pf_end) & (tobii_pf >= 0)
            seg_pf  = tobii_pf[mask]
            seg_pup = tobii_pupil[mask].astype(np.float64)
            valid_pup = ~np.isnan(seg_pup)
            if valid_pup.sum() >= n_steps // 4:
                # Map phan_frame → time axis (linear)
                t_target_pf = pf_start + np.linspace(0, pf_end - pf_start, n_steps)
                pup_resampled = np.interp(t_target_pf, seg_pf[valid_pup].astype(np.float64), seg_pup[valid_pup])
                baseline_pup = np.mean(pup_resampled[:half_frames]) if half_frames > 0 else 0.0
                tobii_pupil_epochs.append(pup_resampled - baseline_pup)

    def _mean_sem(epochs: list[np.ndarray]) -> dict:
        if not epochs:
            return {"mean": None, "sem": None}
        mat = np.stack(epochs, axis=0)
        mean = np.mean(mat, axis=0).tolist()
        sem = (np.std(mat, axis=0, ddof=1) / np.sqrt(len(epochs))).tolist()
        return {"mean": [round(v, 4) for v in mean], "sem": [round(v, 4) for v in sem]}

    return {
        "rec_id":    rec_id,
        "t_ms":      [round(v, 1) for v in t_ms],
        "n_blinks":  len(aperture_epochs),
        "aperture":  _mean_sem(aperture_epochs),
        "eeg_fp1":   _mean_sem(eeg_fp1_epochs),
        "tobii_pupil": _mean_sem(tobii_pupil_epochs),
    }
