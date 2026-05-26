"""
web/routers/tobii.py

Tobii eye-tracking endpoints.
Validity convention: 0 = valid, 1+ = various levels of invalid (Tobii SDK).
"""

from __future__ import annotations

import functools
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from fastapi import APIRouter, HTTPException

from db.database import get_db
from db.models import TobiiRecording

router = APIRouter(prefix="/api/tobii", tags=["tobii"])


def _get_recording(rec_id: str) -> tuple[TobiiRecording, Path]:
    S = get_db()
    with S() as db:
        rec = db.get(TobiiRecording, rec_id)
    if not rec:
        raise HTTPException(404, f"Tobii recording {rec_id!r} not found")
    path = Path("dataserver/tobii") / f"{rec_id}.parquet"
    if not path.exists():
        raise HTTPException(404, f"Parquet file not found: {path}")
    return rec, path


def _decimate(arr: np.ndarray, target: int = 400) -> np.ndarray:
    n = len(arr)
    if n <= target:
        return arr
    idx = np.round(np.linspace(0, n - 1, target)).astype(int)
    return arr[idx]


@router.get("/{rec_id}/window")
def tobii_window(rec_id: str, t_start_s: float = 0.0, t_end_s: float = 5.0):
    """Return decimated Tobii streams for a time window. Invalid samples → null.
    Validity: 0 = valid, anything else = invalid."""
    rec, path = _get_recording(rec_id)
    duration_s = float(rec.duration_s or 0)

    table = pq.read_table(
        path,
        columns=["timestamp_ms", "gaze_x", "gaze_y",
                 "pupil_left", "pupil_right", "validity_left", "validity_right"],
        filters=[
            ("timestamp_ms", ">=", t_start_s * 1000.0),
            ("timestamp_ms", "<=", t_end_s   * 1000.0),
        ],
    )

    n = len(table)
    if n == 0:
        return {"duration_s": duration_s, "times_s": [], "gaze_x": [],
                "gaze_y": [], "pupil_left": [], "pupil_right": []}

    target = 400
    idx = np.round(np.linspace(0, n - 1, min(n, target))).astype(int)

    val_l = table["validity_left"].to_numpy(zero_copy_only=False).astype(np.int8)[idx]
    val_r = table["validity_right"].to_numpy(zero_copy_only=False).astype(np.int8)[idx]
    gx    = table["gaze_x"].to_numpy(zero_copy_only=False).astype(np.float32)[idx]
    gy    = table["gaze_y"].to_numpy(zero_copy_only=False).astype(np.float32)[idx]
    pl    = table["pupil_left"].to_numpy(zero_copy_only=False).astype(np.float32)[idx]
    pr    = table["pupil_right"].to_numpy(zero_copy_only=False).astype(np.float32)[idx]
    ts    = table["timestamp_ms"].to_numpy(zero_copy_only=False).astype(np.float32)[idx]

    def mask(arr, validity):
        # validity == 0 means valid in Tobii SDK
        return [None if (np.isnan(v) or validity[i] != 0) else round(float(v), 3)
                for i, v in enumerate(arr)]

    return {
        "duration_s":  duration_s,
        "times_s":     [round(float(t) / 1000.0, 4) for t in ts],
        "gaze_x":      mask(gx, val_l),
        "gaze_y":      mask(gy, val_l),
        "pupil_left":  mask(pl, val_l),
        "pupil_right": mask(pr, val_r),
    }


@functools.lru_cache(maxsize=16)
def _compute_gaze_summary(path_str: str) -> dict:
    """Compute full-session gaze aggregates. Cached per recording."""
    path = Path(path_str)
    table = pq.read_table(path, columns=[
        "gaze_x", "gaze_y", "fixation_x", "fixation_y",
        "event_type", "saccade_dir", "saccade_amp",
        "pupil_left", "pupil_right",
        "validity_left", "validity_right", "timestamp_ms",
    ])

    ev_type = table["event_type"].to_numpy(zero_copy_only=False)
    vl      = table["validity_left"].to_numpy(zero_copy_only=False).astype(np.int8)
    vr      = table["validity_right"].to_numpy(zero_copy_only=False).astype(np.int8)
    gx      = table["gaze_x"].to_numpy(zero_copy_only=False).astype(np.float32)
    gy      = table["gaze_y"].to_numpy(zero_copy_only=False).astype(np.float32)
    sdir    = table["saccade_dir"].to_numpy(zero_copy_only=False).astype(np.float32)
    samp    = table["saccade_amp"].to_numpy(zero_copy_only=False).astype(np.float32)
    pl      = table["pupil_left"].to_numpy(zero_copy_only=False).astype(np.float32)
    pr      = table["pupil_right"].to_numpy(zero_copy_only=False).astype(np.float32)
    ts      = table["timestamp_ms"].to_numpy(zero_copy_only=False).astype(np.float64)

    # Valid samples: validity == 0 (Tobii SDK convention)
    valid_mask = (vl == 0) & (vr == 0)

    # Detect display bounds from actual data range (not assumed 1920×1080)
    gx_valid = gx[valid_mask & ~np.isnan(gx)]
    gy_valid = gy[valid_mask & ~np.isnan(gy)]
    if len(gx_valid) > 0:
        display_w = float(np.nanpercentile(gx_valid, 99))
        display_h = float(np.nanpercentile(gy_valid, 99))
    else:
        display_w, display_h = 1024.0, 768.0

    # Fixation heatmap: 48×27 bins over actual display area
    fix_mask = (ev_type == "Fixation") & valid_mask & ~np.isnan(gx)
    fx = gx[fix_mask]
    fy = gy[fix_mask]
    n_bins_x, n_bins_y = 48, 27
    heatmap = []
    if len(fx) > 10:
        H_arr, _, _ = np.histogram2d(
            fx, fy,
            bins=[n_bins_x, n_bins_y],
            range=[[0, display_w], [0, display_h]],
        )
        H_arr = H_arr.astype(np.float32)
        mx = H_arr.max()
        if mx > 0:
            H_arr /= mx
        for xi in range(n_bins_x):
            for yi in range(n_bins_y):
                if H_arr[xi, yi] > 0.01:
                    heatmap.append([xi, yi, round(float(H_arr[xi, yi]), 3)])

    # Tobii stores saccade_dir/saccade_amp in FIXATION rows (incoming saccade before each fixation),
    # not in the saccade event rows themselves.
    sac_mask  = (ev_type == "Fixation") & ~np.isnan(sdir)
    sac_dirs  = sdir[sac_mask]
    sac_amps  = samp[sac_mask]
    n_saccades = int((ev_type == "Saccade").sum())
    dir_bins = np.zeros(16, dtype=np.float32)
    if len(sac_dirs) > 0:
        bin_idx = np.floor((sac_dirs % 360) / (360 / 16)).astype(int).clip(0, 15)
        np.add.at(dir_bins, bin_idx, 1)
        mx = dir_bins.max()
        if mx > 0:
            dir_bins /= mx

    # Pupil timeline (decimated)
    pl_clean = np.where(valid_mask, pl, np.nan)
    pr_clean = np.where(valid_mask, pr, np.nan)
    n = len(ts)
    pidx = np.round(np.linspace(0, n - 1, min(n, 600))).astype(int)

    def _clean(arr):
        return [None if np.isnan(v) else round(float(v), 3) for v in arr[pidx]]

    return {
        "display_w":    round(display_w, 1),
        "display_h":    round(display_h, 1),
        "heatmap":      heatmap,
        "saccade_dirs": dir_bins.tolist(),
        "sac_amp_mean": round(float(sac_amps.mean()), 2) if len(sac_amps) > 0 else 0.0,
        "n_fixations":  int(fix_mask.sum()),
        "n_saccades":   n_saccades,
        "pupil_times_s": [round(float(t) / 1000.0, 3) for t in ts[pidx]],
        "pupil_left":   _clean(pl_clean),
        "pupil_right":  _clean(pr_clean),
    }


@router.get("/{rec_id}/gaze_summary")
def tobii_gaze_summary(rec_id: str):
    """Return full-session gaze aggregates: heatmap, saccade directions, pupil."""
    _, path = _get_recording(rec_id)
    return _compute_gaze_summary(str(path))
