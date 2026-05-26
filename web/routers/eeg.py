"""
web/routers/eeg.py

EEG data endpoints:
  GET /api/eeg/{rec_id}/window   — time-windowed waveforms (channels, band filter, scale)
  GET /api/eeg/{rec_id}/minimap  — full-session amplitude envelope
  GET /api/eeg/{rec_id}/events   — trial event markers (from DB)
  GET /api/eeg/{rec_id}/topo     — single-timestamp 64-channel values for topography
  GET /api/eeg/{rec_id}/erp      — event-related potential averages per cue type
  GET /api/eeg/{rec_id}/psd      — power spectral density per brain region
  GET /api/eeg/{rec_id}/trials   — list of trials with timing for this recording
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Optional

import numpy as np
import pyarrow.parquet as pq
from fastapi import APIRouter, HTTPException
from scipy.signal import butter, sosfiltfilt, welch

from db.database import get_db
from db.models import EEGRecording, Trial, TobiiRecording

router = APIRouter(prefix="/api/eeg", tags=["eeg"])

REGIONS: dict[str, list[str]] = {
    "Frontal":   ["FP1","FPZ","FP2","AF3","AF4","F7","F5","F3","F1","FZ","F2"],
    "Central":   ["F4","F6","F8","FT7","FC5","FC3","FC1","FCZ","FC2","FC4","FC6","FT8","CZ"],
    "Temporal":  ["T7","C5","C3","C1","C2","C4","C6","T8","M1","M2","TP7","TP8","CP5","CP6"],
    "Parietal":  ["CP3","CP1","CPZ","CP2","CP4","P7","P5","P3","P1","PZ","P2","P4","P6"],
    "Occipital": ["P8","PO7","PO5","PO3","POZ","PO4","PO6","PO8","CB1","O1","OZ","O2","CB2"],
}
ALL_EEG_CHANNELS = [ch for chs in REGIONS.values() for ch in chs]

REGION_COLORS = {
    "Frontal":   "#6B7FB0",
    "Central":   "#6FAE89",
    "Temporal":  "#D4A574",
    "Parietal":  "#B580A8",
    "Occipital": "#5689A8",
}

# Recommended channels for ERP display (one representative per region)
DEFAULT_VIEWER_CHANNELS = ["FP1", "FZ", "F3", "FCZ", "CZ", "C3", "C4", "CPZ", "PZ", "P3", "POZ", "O1"]


def _get_recording(rec_id: str) -> tuple[EEGRecording, Path]:
    S = get_db()
    with S() as db:
        rec = db.get(EEGRecording, rec_id)
    if not rec:
        raise HTTPException(404, f"EEG recording {rec_id!r} not found")
    path = Path("dataserver/eeg") / f"{rec_id}.parquet"
    if not path.exists():
        raise HTTPException(404, f"Parquet file not found: {path}")
    return rec, path


def _decimate(arr: np.ndarray, target: int = 400) -> np.ndarray:
    n = len(arr)
    if n <= target:
        return arr
    idx = np.round(np.linspace(0, n - 1, target)).astype(int)
    return arr[idx]


def _apply_band(data: np.ndarray, band: str, fs: float = 1000.0) -> np.ndarray:
    """Apply a Butterworth bandpass filter. data shape: (n_samples,)"""
    if not band or band == "raw":
        return data
    nyq = fs / 2.0
    band_ranges = {
        "alpha": (8.0, 12.0),
        "beta":  (12.0, 30.0),
        "gamma": (30.0, 80.0),
        "theta": (4.0, 8.0),
        "delta": (0.5, 4.0),
    }
    if band not in band_ranges:
        return data
    lo, hi = band_ranges[band]
    sos = butter(4, [lo / nyq, hi / nyq], btype="band", output="sos")
    return sosfiltfilt(sos, data).astype(np.float32)


# ── /window ───────────────────────────────────────────────────────────────────

@router.get("/{rec_id}/window")
def eeg_window(
    rec_id: str,
    t_start_s: float = 0.0,
    t_end_s: float = 5.0,
    channels: Optional[str] = None,
    band: str = "raw",
    scale: str = "raw",
):
    """
    Return decimated EEG waveforms for a time window.

    channels: comma-separated list (e.g. 'FZ,CZ,PZ'). If omitted, returns all regions.
    band:     'raw' | 'alpha' | 'beta' | 'gamma' | 'theta' | 'delta'
    scale:    'raw' → μV values | 'zscore' → z-scored ±4 clip (legacy)
    """
    rec, path = _get_recording(rec_id)
    duration_s = float(rec.duration_s or 0)
    t_start_s = max(0.0, t_start_s)
    t_end_s   = min(duration_s, t_end_s)
    if t_start_s >= t_end_s:
        raise HTTPException(400, "t_start_s must be < t_end_s")

    # Determine which channels to load
    if channels:
        ch_list = [c.strip() for c in channels.split(",") if c.strip()]
        # Keep only valid EEG channel names
        ch_list = [c for c in ch_list if c in ALL_EEG_CHANNELS]
    else:
        ch_list = None  # load all

    load_cols = ["timestamp_s", "blink"] + (ch_list if ch_list else ALL_EEG_CHANNELS)
    table = pq.read_table(
        path,
        columns=load_cols,
        filters=[
            ("timestamp_s", ">=", t_start_s),
            ("timestamp_s", "<=", t_end_s),
        ],
    )

    n = len(table)
    if n == 0:
        raise HTTPException(404, "No EEG data in requested window")

    target = 600
    idx = np.round(np.linspace(0, n - 1, min(n, target))).astype(int)
    times_raw = table["timestamp_s"].to_numpy(zero_copy_only=False)
    times = times_raw[idx].tolist()

    # Filter: only return blinks where phan_frame >= 0 (in-video, visually confirmed).
    # Also correct the -1.05s lag: blink column marks recovery, not onset.
    BLINK_LAG_S = 1.05
    blink_times: list[float] = []
    try:
        pf_table = pq.read_table(path, columns=["timestamp_s", "blink", "phan_frame"],
                                  filters=[("timestamp_s", ">=", t_start_s),
                                           ("timestamp_s", "<=", t_end_s)])
        pf_arr = pf_table["phan_frame"].to_numpy(zero_copy_only=False).astype(np.int32)
        bl_arr = pf_table["blink"].to_numpy(zero_copy_only=False).astype(np.int8)
        ts_pf  = pf_table["timestamp_s"].to_numpy(zero_copy_only=False)
        blink_times = [round(float(ts_pf[j]) - BLINK_LAG_S, 4)
                       for j in range(len(bl_arr)) if bl_arr[j] > 0 and pf_arr[j] >= 0]
    except Exception:
        blink_col = table["blink"].to_numpy(zero_copy_only=False).astype(np.int8)
        blink_times = [round(t - BLINK_LAG_S, 4) for t in times_raw[blink_col > 0].tolist()]

    def process_channel(col_name: str) -> list[float]:
        raw = np.array(table[col_name].to_numpy(zero_copy_only=False), dtype=np.float32)
        if band != "raw":
            raw = _apply_band(raw, band)
        dec = raw[idx]
        if scale == "zscore":
            std = dec.std()
            if std > 1e-9:
                dec = np.clip((dec - dec.mean()) / std, -4, 4)
        return [round(float(v), 3) for v in dec]

    if ch_list:
        # Return flat channel list (for EEG viewer with explicit channel selection)
        ch_out = []
        for ch in ch_list:
            # Find which region this channel belongs to
            region = next((r for r, chs in REGIONS.items() if ch in chs), "Unknown")
            ch_out.append({
                "name":   ch,
                "region": region,
                "color":  REGION_COLORS.get(region, "#888"),
                "y":      process_channel(ch),
            })
        return {
            "t_start_s": t_start_s, "t_end_s": t_end_s,
            "duration_s": duration_s, "times": times,
            "blink_times": blink_times,
            "channels": ch_out,
        }
    else:
        # Return grouped by region (legacy format)
        regions_out = []
        for region, region_chs in REGIONS.items():
            ch_out = []
            for ch in region_chs:
                ch_out.append({"name": ch, "y": process_channel(ch)})
            regions_out.append({
                "name": region, "color": REGION_COLORS[region], "channels": ch_out,
            })
        return {
            "t_start_s": t_start_s, "t_end_s": t_end_s,
            "duration_s": duration_s, "times": times,
            "blink_times": blink_times,
            "regions": regions_out,
        }


# ── /minimap ──────────────────────────────────────────────────────────────────

@functools.lru_cache(maxsize=32)
def _compute_minimap(path_str: str, duration_s: float):
    path = Path(path_str)
    sample_chs = ALL_EEG_CHANNELS[:12]
    table = pq.read_table(path, columns=sample_chs)
    arr = np.zeros(len(table), dtype=np.float32)
    for col in sample_chs:
        arr += np.abs(np.array(table[col].to_numpy(zero_copy_only=False), dtype=np.float32))
    return arr / 12


@router.get("/{rec_id}/minimap")
def eeg_minimap(rec_id: str):
    """Return full-session amplitude envelope, decimated to 800 points."""
    rec, path = _get_recording(rec_id)
    arr = _compute_minimap(str(path), float(rec.duration_s or 0))
    dec = _decimate(arr, 800)
    mx = dec.max()
    if mx > 0:
        dec = dec / mx
    return {"duration_s": float(rec.duration_s or 0), "envelope": dec.tolist()}


# ── /events ───────────────────────────────────────────────────────────────────

@router.get("/{rec_id}/events")
def eeg_events(rec_id: str):
    """Return trial event markers (start_ts, cue label) for this recording."""
    parts = rec_id.rsplit("_", 1)
    if len(parts) != 2:
        return {"events": []}
    session_id, paradigm = parts[0], parts[1]
    S = get_db()
    with S() as db:
        trials = (
            db.query(Trial)
            .filter(Trial.session_id == session_id, Trial.paradigm == paradigm)
            .order_by(Trial.trial_number)
            .all()
        )
    events = [
        {"t_s": float(tr.start_ts), "label": tr.cue or f"Trial {tr.trial_number}"}
        for tr in trials if tr.start_ts is not None
    ]
    return {"events": events}


# ── /topo ─────────────────────────────────────────────────────────────────────

@router.get("/{rec_id}/topo")
def eeg_topo(rec_id: str, t_ms: float = 238.0):
    """Return 64-channel amplitude values at a specific millisecond."""
    rec, path = _get_recording(rec_id)
    t_s = t_ms / 1000.0
    table = pq.read_table(
        path,
        columns=["timestamp_s"] + ALL_EEG_CHANNELS,
        filters=[("timestamp_s", ">=", t_s - 0.002), ("timestamp_s", "<=", t_s + 0.002)],
    )
    if len(table) == 0:
        raise HTTPException(404, f"No EEG data at t={t_ms}ms")
    mid = len(table) // 2
    channels = [{"name": ch, "value_uv": round(float(table[ch][mid].as_py() or 0.0), 4)}
                for ch in ALL_EEG_CHANNELS]
    return {"t_ms": t_ms, "channels": channels}


# ── /trials ───────────────────────────────────────────────────────────────────

@router.get("/{rec_id}/trials")
def eeg_trials(rec_id: str):
    """Return all trials for this recording with timing and cue info."""
    parts = rec_id.rsplit("_", 1)
    if len(parts) != 2:
        return {"trials": []}
    session_id, paradigm = parts[0], parts[1]
    S = get_db()
    with S() as db:
        trials = (
            db.query(Trial)
            .filter(Trial.session_id == session_id, Trial.paradigm == paradigm)
            .order_by(Trial.trial_number)
            .all()
        )
    return {
        "trials": [
            {
                "trial_id":     tr.id,
                "trial_number": tr.trial_number,
                "cue":          tr.cue or "",
                "start_s":      float(tr.start_ts) if tr.start_ts else None,
                "end_s":        float(tr.end_ts) if tr.end_ts else None,
                "duration_s":   float(tr.duration_s) if tr.duration_s else None,
                "missed":       bool(tr.missed),
                "phan_frame_start": tr.phan_frame_start,
                "phan_frame_end":   tr.phan_frame_end,
            }
            for tr in trials
        ]
    }


# ── /erp ──────────────────────────────────────────────────────────────────────

@functools.lru_cache(maxsize=16)
def _load_eeg_channels(path_str: str, channels_key: str) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Load EEG timestamps + specified channels for the full session. Cached."""
    channels = list(channels_key.split(","))
    valid_chs = [c for c in channels if c in ALL_EEG_CHANNELS]
    path = Path(path_str)
    table = pq.read_table(path, columns=["timestamp_s"] + valid_chs)
    ts = table["timestamp_s"].to_numpy(zero_copy_only=False).astype(np.float64)
    data = {ch: table[ch].to_numpy(zero_copy_only=False).astype(np.float32) for ch in valid_chs}
    return ts, data


@router.get("/{rec_id}/erp")
def eeg_erp(rec_id: str, channels: str = "CZ,CPZ,PZ"):
    """
    Event-Related Potential: average EEG epochs time-locked to trial onset.
    Returns per-cue-type mean ± SEM for the requested channels.
    Window: -200ms to +600ms around each trial start.
    Baseline: mean of -200ms to 0ms subtracted.
    """
    rec, path = _get_recording(rec_id)
    parts = rec_id.rsplit("_", 1)
    if len(parts) != 2:
        raise HTTPException(400, "Invalid rec_id format")
    session_id, paradigm = parts[0], parts[1]

    S = get_db()
    with S() as db:
        trials = (
            db.query(Trial)
            .filter(Trial.session_id == session_id, Trial.paradigm == paradigm,
                    Trial.missed == False)
            .order_by(Trial.trial_number)
            .all()
        )

    ch_list = [c.strip() for c in channels.split(",") if c.strip() in ALL_EEG_CHANNELS]
    if not ch_list:
        raise HTTPException(400, "No valid channels specified")

    channels_key = ",".join(sorted(ch_list))
    ts, ch_data = _load_eeg_channels(str(path), channels_key)

    pre_ms  = 200
    post_ms = 600
    n_samples = pre_ms + post_ms  # 800 samples at 1kHz
    time_ms = list(range(-pre_ms, post_ms))

    # Group trials by cue
    cue_epochs: dict[str, list[np.ndarray]] = {}
    for tr in trials:
        if tr.start_ts is None:
            continue
        t0 = float(tr.start_ts)
        i0 = np.searchsorted(ts, t0 - pre_ms / 1000.0)
        i1 = i0 + n_samples
        if i1 > len(ts):
            continue

        # Average selected channels into one trace for the epoch
        epoch = np.mean([ch_data[ch][i0:i1] for ch in ch_list if ch in ch_data], axis=0)

        # Baseline correct: subtract mean of pre-stimulus period
        baseline = epoch[:pre_ms].mean()
        epoch = epoch - baseline

        cue = tr.cue or "Unknown"
        cue_epochs.setdefault(cue, []).append(epoch)

    # Compute mean + SEM per cue
    results = []
    for cue, epochs in cue_epochs.items():
        arr = np.stack(epochs, axis=0)  # (n_trials, 800)
        mean = arr.mean(axis=0)
        sem  = arr.std(axis=0) / np.sqrt(len(epochs))
        results.append({
            "cue":      cue,
            "n_trials": len(epochs),
            "mean":     [round(float(v), 4) for v in mean],
            "sem":      [round(float(v), 4) for v in sem],
            "time_ms":  time_ms,
        })

    return {"rec_id": rec_id, "channels": ch_list, "erps": results}


# ── /psd ──────────────────────────────────────────────────────────────────────

@functools.lru_cache(maxsize=16)
def _compute_psd(path_str: str, region: str) -> tuple[list, list]:
    """Compute Welch PSD averaged over all channels in a region. Cached."""
    channels = REGIONS.get(region, [])
    path = Path(path_str)
    table = pq.read_table(path, columns=channels)

    psd_sum = None
    count = 0
    for ch in channels:
        data = np.array(table[ch].to_numpy(zero_copy_only=False), dtype=np.float64)
        # Remove NaN
        data = data[~np.isnan(data)]
        if len(data) < 2000:
            continue
        freqs, pxx = welch(data, fs=1000.0, window="hann", nperseg=4000, noverlap=2000)
        if psd_sum is None:
            psd_sum = pxx
        else:
            psd_sum = psd_sum + pxx
        count += 1

    if psd_sum is None or count == 0:
        return [], []

    psd_avg = psd_sum / count
    # Restrict to 1-80 Hz
    mask = (freqs >= 1.0) & (freqs <= 80.0)
    freqs_out = freqs[mask].tolist()
    # Convert to dB
    power_db = (10.0 * np.log10(psd_avg[mask] + 1e-12)).tolist()
    return freqs_out, power_db


@router.get("/{rec_id}/psd")
def eeg_psd(rec_id: str, region: str = "Central"):
    """
    Return Power Spectral Density (Welch method) averaged over all channels in a region.
    Frequency range: 1-80 Hz. Power in dB/Hz.
    """
    if region not in REGIONS:
        raise HTTPException(400, f"Unknown region: {region}. Choose from {list(REGIONS.keys())}")
    rec, path = _get_recording(rec_id)
    freqs, power_db = _compute_psd(str(path), region)
    if not freqs:
        raise HTTPException(500, "Could not compute PSD")
    return {
        "rec_id": rec_id,
        "region": region,
        "freqs":  freqs,
        "power_db": power_db,
    }


# ── /timeline ─────────────────────────────────────────────────────────────────

@functools.lru_cache(maxsize=32)
def _load_blink_times(path_str: str) -> list[float]:
    """Load all blink peak timestamps for a recording. Cached."""
    table = pq.read_table(path_str, columns=["timestamp_s", "blink"])
    ts  = table["timestamp_s"].to_numpy(zero_copy_only=False).astype(np.float64)
    bl  = table["blink"].to_numpy(zero_copy_only=False).astype(np.int8)
    return ts[bl > 0].tolist()


@router.get("/{rec_id}/timeline")
def eeg_timeline(rec_id: str):
    """
    Return a compact session-level timeline for the master strip:
    trials, blink peaks, gaze validity envelope, and sync quality.
    """
    rec, path = _get_recording(rec_id)
    parts = rec_id.rsplit("_", 1)
    if len(parts) != 2:
        raise HTTPException(400, "Invalid rec_id")
    session_id, paradigm = parts[0], parts[1]

    # Trials
    S = get_db()
    with S() as db:
        trials = (
            db.query(Trial)
            .filter(Trial.session_id == session_id, Trial.paradigm == paradigm)
            .order_by(Trial.trial_number)
            .all()
        )
        tobii = db.query(TobiiRecording).filter(
            TobiiRecording.session_id == session_id,
            TobiiRecording.paradigm == paradigm,
        ).first()

    # Cue → color mapping for trial bars
    cue_colors = {
        "Left": "#6B7FB0", "Right": "#6FAE89",
        "10 Hz": "#D4A574", "11 Hz": "#B580A8", "12 Hz": "#5689A8", "13 Hz": "#6FAE89",
        "Stimulus": "#E76F51",
    }
    trial_list = [
        {
            "t_start": float(tr.start_ts) if tr.start_ts else None,
            "t_end":   float(tr.end_ts)   if tr.end_ts   else None,
            "cue":     tr.cue or "",
            "color":   cue_colors.get(tr.cue, "#9AA2AE"),
            "missed":  bool(tr.missed),
            "phan_frame_start": tr.phan_frame_start,
        }
        for tr in trials if tr.start_ts
    ]

    # All blink peaks (full session, cached)
    blink_times = _load_blink_times(str(path))

    # Gaze validity (from DB metadata — no parquet read needed)
    gaze_validity = float(tobii.validity_pct) if tobii and tobii.validity_pct else None

    # Sync quality
    if tobii and tobii.validity_pct and tobii.validity_pct > 5.0:
        sync_quality = "synchronized"
    elif tobii and tobii.validity_pct and tobii.validity_pct > 0:
        sync_quality = "gaze_partial"
    else:
        sync_quality = "gaze_unsynced"

    return {
        "rec_id":         rec_id,
        "duration_s":     float(rec.duration_s or 0),
        "paradigm":       paradigm,
        "trials":         trial_list,
        "blink_times":    blink_times,
        "gaze_validity":  gaze_validity,
        "sync_quality":   sync_quality,
        "n_blinks":       len(blink_times),
    }
