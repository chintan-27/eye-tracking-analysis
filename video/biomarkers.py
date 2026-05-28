"""
video/biomarkers.py

Per-frame feature extraction and per-task-window aggregation.

extract_per_frame(): converts one frame's raw tracking outputs into a flat dict
  matching the per-frame Parquet schema.

aggregate_window(): collapses a DataFrame of per-frame rows (one task clip)
  into one summary feature row → the 315 rows used for alertness classification.

Feature categories (per window):
  Blink Rates and Durations — mean, variance, P95 of durations; blink rate/min
  Kinematic Ratios          — mean and median R_slow
  Pupil Dynamics            — mean, median, variance of diameter; P90 constriction velocity
  Micro-Movement Energy     — mean and P95 of U_phys, V_phys in pupil + eyelid ROIs
  Tremor Power              — integrated spectral energy in 40-80 Hz band of P-CR vector (CWT)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

try:
    import pywt
    _HAS_PYWT = True
except ImportError:
    _HAS_PYWT = False

from video.blink import BlinkStateMachine

# Per-frame Parquet column order and dtypes
FRAME_SCHEMA: dict[str, str] = {
    "frame_number":       "int32",
    "phan_frame":         "int32",
    "timestamp_eeg_ms":   "int64",
    "fps":                "float32",
    "aperture_mm":        "float32",
    "aperture_delta_mm":  "float32",
    "aperture_velocity":  "float32",
    "aperture_norm":      "float32",
    "blink_state":        "int8",
    "pupil_x":            "float32",
    "pupil_y":            "float32",
    "pupil_radius_px":    "float32",
    "pupil_diameter_mm":  "float32",
    "pupil_diameter_delta_mm": "float32",
    "pupil_diameter_velocity_mms": "float32",
    "pupil_area_mm2":     "float32",
    "pupil_area_delta_pct": "float32",
    "pupil_center_velocity_mms": "float32",
    "cr_x":               "float32",
    "cr_y":               "float32",
    "p_cr_x":             "float32",
    "p_cr_y":             "float32",
    "p_cr_velocity_mms":  "float32",
    "flow_mag_mean_eyelid": "float32",
    "flow_mag_p95_eyelid":  "float32",
    "flow_vert_eyelid":     "float32",
    "flow_mag_mean_pupil":  "float32",
    "flow_mag_p95_pupil":   "float32",
    "transform_tx":       "float32",
    "transform_ty":       "float32",
    "transform_rot":      "float32",
    "qc_flag":            "int8",
}


def extract_per_frame(
    frame_number:     int,
    phan_frame:       int,
    timestamp_eeg_ms: int,
    fps:              float,
    aperture_mm:      float,
    aperture_delta_mm: float,
    aperture_velocity: float,
    aperture_norm:    float,
    blink_state:      int,
    pupil_x:          float,
    pupil_y:          float,
    pupil_radius_px:  float,
    pupil_diameter_mm: float,
    pupil_diameter_delta_mm: float,
    pupil_diameter_velocity_mms: float,
    pupil_area_mm2:   float,
    pupil_area_delta_pct: float,
    pupil_center_velocity_mms: float,
    cr_x:             float,
    cr_y:             float,
    p_cr_x:           float,
    p_cr_y:           float,
    p_cr_velocity_mms: float,
    flow_eyelid:      dict,
    flow_pupil:       dict,
    transform_tx:     float,
    transform_ty:     float,
    transform_rot:    float,
    qc_flag:          int,
) -> dict:
    """Build one per-frame feature dict. All values are Python scalars."""
    return {
        "frame_number":         int(frame_number),
        "phan_frame":           int(phan_frame),
        "timestamp_eeg_ms":     int(timestamp_eeg_ms),
        "fps":                  float(fps),
        "aperture_mm":          float(aperture_mm),
        "aperture_delta_mm":    float(aperture_delta_mm),
        "aperture_velocity":    float(aperture_velocity),
        "aperture_norm":        float(aperture_norm),
        "blink_state":          int(blink_state),
        "pupil_x":              float(pupil_x),
        "pupil_y":              float(pupil_y),
        "pupil_radius_px":      float(pupil_radius_px),
        "pupil_diameter_mm":    float(pupil_diameter_mm),
        "pupil_diameter_delta_mm": float(pupil_diameter_delta_mm),
        "pupil_diameter_velocity_mms": float(pupil_diameter_velocity_mms),
        "pupil_area_mm2":       float(pupil_area_mm2),
        "pupil_area_delta_pct": float(pupil_area_delta_pct),
        "pupil_center_velocity_mms": float(pupil_center_velocity_mms),
        "cr_x":                 float(cr_x),
        "cr_y":                 float(cr_y),
        "p_cr_x":               float(p_cr_x),
        "p_cr_y":               float(p_cr_y),
        "p_cr_velocity_mms":    float(p_cr_velocity_mms),
        "flow_mag_mean_eyelid": float(flow_eyelid.get("mag_mean", 0.0)),
        "flow_mag_p95_eyelid":  float(flow_eyelid.get("mag_p95",  0.0)),
        "flow_vert_eyelid":     float(flow_eyelid.get("vert_mean", 0.0)),
        "flow_mag_mean_pupil":  float(flow_pupil.get("mag_mean",  0.0)),
        "flow_mag_p95_pupil":   float(flow_pupil.get("mag_p95",   0.0)),
        "transform_tx":         float(transform_tx),
        "transform_ty":         float(transform_ty),
        "transform_rot":        float(transform_rot),
        "qc_flag":              int(qc_flag),
    }


def cast_frame_df(rows: list[dict]) -> pd.DataFrame:
    """Convert a list of per-frame dicts to a typed DataFrame."""
    df = pd.DataFrame(rows)
    for col, dtype in FRAME_SCHEMA.items():
        if col in df.columns:
            df[col] = df[col].astype(dtype)
    return df


def aggregate_window(
    df: pd.DataFrame,
    blink_sm: BlinkStateMachine,
    fps: float,
) -> dict:
    """
    Collapse one task clip's per-frame DataFrame into a single feature row.

    Parameters
    ----------
    df : per-frame DataFrame (output of cast_frame_df)
    blink_sm : BlinkStateMachine — call get_blink_kinematics() to get blink features
    fps : recording frame rate (used for tremor CWT)

    Returns
    -------
    dict of scalar features — one row in the 315-row model training set.
    """
    open_frames  = df[df["blink_state"] == 0]
    close_frames = df[df["blink_state"] == 1]

    # Blink rate and duration from BlinkStateMachine events
    blink_kin = blink_sm.get_blink_kinematics()
    n_blinks  = blink_kin["n_blinks"]
    duration_min = len(df) / (fps * 60.0)
    blink_rate   = n_blinks / max(duration_min, 1e-6)

    events = blink_sm.blink_events
    blink_dur_vals = [e.duration_ms for e in events] if events else [0.0]

    # Pupil dynamics (open frames only)
    diam = open_frames["pupil_diameter_mm"]
    constriction_vel = open_frames["aperture_velocity"]  # proxy for pupil velocity

    # Micro-movement energy
    flow_e_mean = df["flow_mag_mean_eyelid"].mean()
    flow_e_p95  = df["flow_mag_p95_eyelid"].quantile(0.95)
    flow_p_mean = df["flow_mag_mean_pupil"].mean()
    flow_p_p95  = df["flow_mag_p95_pupil"].quantile(0.95)

    # Tremor power from P-CR vector (CWT in 40–80 Hz band if fps allows)
    tremor_power = _compute_tremor_power(df, fps)

    feat: dict = {}

    # Blink rates and durations
    feat["blink_rate_per_min"]   = blink_rate
    feat["blink_dur_mean_ms"]    = float(np.mean(blink_dur_vals))
    feat["blink_dur_var_ms"]     = float(np.var(blink_dur_vals))
    feat["blink_dur_p95_ms"]     = float(np.percentile(blink_dur_vals, 95))

    # Kinematic ratios
    feat["r_slow_mean"]          = blink_kin.get("r_slow_mean",   0.0)
    feat["r_slow_median"]        = blink_kin.get("r_slow_median", 0.0)
    feat["v_close_max_mean"]     = blink_kin.get("v_close_max",   0.0)
    feat["v_open_max_mean"]      = blink_kin.get("v_open_max",    0.0)

    # Pupil dynamics
    feat["pupil_diam_mean_mm"]   = float(diam.mean())   if len(diam) > 0 else 0.0
    feat["pupil_diam_median_mm"] = float(diam.median()) if len(diam) > 0 else 0.0
    feat["pupil_diam_var_mm"]    = float(diam.var())    if len(diam) > 0 else 0.0
    feat["pupil_constrict_p90"]  = float(constriction_vel.quantile(0.90)) if len(constriction_vel) > 0 else 0.0

    # Micro-movement energy
    feat["flow_eyelid_mean"]     = float(flow_e_mean) if not np.isnan(flow_e_mean) else 0.0
    feat["flow_eyelid_p95"]      = float(flow_e_p95)  if not np.isnan(flow_e_p95)  else 0.0
    feat["flow_pupil_mean"]      = float(flow_p_mean) if not np.isnan(flow_p_mean) else 0.0
    feat["flow_pupil_p95"]       = float(flow_p_p95)  if not np.isnan(flow_p_p95)  else 0.0

    # Tremor
    feat["tremor_power"]         = tremor_power

    # Aperture variability
    feat["aperture_norm_mean"]   = float(open_frames["aperture_norm"].mean()) if len(open_frames) > 0 else 0.0
    feat["aperture_norm_var"]    = float(open_frames["aperture_norm"].var())  if len(open_frames) > 0 else 0.0

    return feat


def _compute_tremor_power(df: pd.DataFrame, fps: float) -> float:
    """
    Compute integrated power in the 40–80 Hz band of the high-pass filtered P-CR vector.

    At fps < 90 (Nyquist < 45 Hz) the 40–80 Hz band is not resolvable —
    returns 0.0 in those cases.

    Uses CWT with complex Morlet wavelet (ω₀=6) if PyWavelets is available;
    falls back to FFT power in the target band otherwise.
    """
    if fps < 90:
        return 0.0  # 40–80 Hz not resolvable below 90fps

    p_cr = df["p_cr_x"].values.astype(np.float64)
    if len(p_cr) < 64:
        return 0.0

    # High-pass filter P-CR above 35 Hz to isolate tremor
    from scipy.signal import butter, filtfilt
    nyq    = fps / 2.0
    b, a   = butter(4, 35.0 / nyq, btype="high")
    p_cr_hp = filtfilt(b, a, p_cr)

    if _HAS_PYWT:
        # CWT: scales corresponding to 40–80 Hz
        freqs_target = np.array([40.0, 80.0])
        scales = pywt.frequency2scale("cmor1.5-1.0", freqs_target / fps)
        scales_range = np.linspace(scales[1], scales[0], 20)
        coef, _ = pywt.cwt(p_cr_hp, scales_range, "cmor1.5-1.0")
        return float(np.mean(np.abs(coef) ** 2))
    else:
        # FFT fallback
        fft  = np.fft.rfft(p_cr_hp)
        freq = np.fft.rfftfreq(len(p_cr_hp), d=1.0/fps)
        band = (freq >= 40) & (freq <= 80)
        return float(np.mean(np.abs(fft[band])**2)) if band.sum() > 0 else 0.0
