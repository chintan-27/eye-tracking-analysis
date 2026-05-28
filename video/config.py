"""
video/config.py

Physical constants and per-FPS algorithm parameters for the eye video pipeline.
All parameters are derived from the Gemini Deep Research document
(notes/video_pipeline_research.md) and the Neuroscience Video Analysis Pipeline PDF.
"""

# ---------------------------------------------------------------------------
# Per-FPS algorithm parameters
# ---------------------------------------------------------------------------
# LK pyramid levels and iteration counts scale with frame rate:
# higher FPS → smaller inter-frame displacement → fewer pyramid levels needed,
# but more iterations to converge at finer scale.
# Blink freeze duration scales to cover ~100ms of closed-eye time.

FPS_PARAMS = {
    24:  {"lk_levels": 2, "lk_iters": 10, "blink_freeze_frames": 3},
    90:  {"lk_levels": 3, "lk_iters": 15, "blink_freeze_frames": 10},
    100: {"lk_levels": 3, "lk_iters": 15, "blink_freeze_frames": 11},
    167: {"lk_levels": 4, "lk_iters": 20, "blink_freeze_frames": 18},
}

def get_fps_params(fps: float) -> dict:
    """Return the parameter set for the closest known FPS regime."""
    known = sorted(FPS_PARAMS.keys())
    closest = min(known, key=lambda k: abs(k - fps))
    return FPS_PARAMS[closest]

# ---------------------------------------------------------------------------
# Stabilisation
# ---------------------------------------------------------------------------

REANCHOR_INTERVAL = 1000   # re-anchor LK tracker to keyframe every N frames
SSIM_THRESHOLD    = 0.85   # SSIM below this outside a blink → tracking failure → re-init
W_SEARCH_MM       = 10.0   # search window half-width in mm; pixels = round(10 / γ)

# LK optical flow termination criteria
LK_TERM_CRITERIA = (3, 30, 0.01)  # (COUNT | EPS, max_iter, epsilon)
LK_WIN_SIZE      = (21, 21)        # patch window for LK gradient computation

# ---------------------------------------------------------------------------
# Scale factor γ (mm/pixel)
# ---------------------------------------------------------------------------
# γ = INNER_CANTHI_MM / subject.inner_canthi_px
# inner_canthi_px is measured from the reference photograph.
# INNER_CANTHI_MM uses the population mean for healthy adults (29–34 mm range).
# Per-subject calibration would improve accuracy if mm measurements are available.

INNER_CANTHI_MM = 31.0

# Phantom close-up fallback scale when subject photograph landmarks are not in
# the same pixel coordinate system as the high-speed video.
PHANTOM_GAMMA_FALLBACK_MM_PER_PX = 0.1
GAMMA_MAX_SANE_MM_PER_PX = 1.0

# ---------------------------------------------------------------------------
# Dense optical flow (RLOF) and HSV motion map
# ---------------------------------------------------------------------------

HSV_KAPPA = 10      # logarithmic compression factor: prevents blink transients saturating
HSV_A_MAX = 20.0    # pixels/frame — magnitude above this maps to maximum brightness

# Motion exaggeration filter
# FLOW_DEAD_ZONE: movements below this (px/frame) are zeroed out — treats camera noise as still.
# FLOW_EXAG_GAIN: remaining motion is multiplied by this factor before rendering.
# net effect: small jitter disappears, real eye movements pop as vivid colour.
FLOW_DEAD_ZONE = 0.0    # default off; set e.g. 0.3 to suppress noise
FLOW_EXAG_GAIN = 1.0    # default off; set e.g. 3.0 for 3× exaggeration

# ---------------------------------------------------------------------------
# Pupil tracking — Hough Circle initialisation
# ---------------------------------------------------------------------------
# All radii are in pixels, derived from physical pupil diameter range (2–8 mm)
# via γ at runtime: minRadius = round(1.0 / γ), maxRadius = round(4.0 / γ)

HOUGH_DP     = 1.5   # inverse ratio of accumulator resolution (1.5 = lower res, faster)
HOUGH_PARAM1 = 100   # upper hysteresis threshold for internal Canny edge detection
HOUGH_PARAM2 = 20    # accumulator threshold; darkest-center selection filters remaining FPs

PUPIL_ROI_SCALE = 3  # ROI width/height = PUPIL_ROI_SCALE × predicted radius

# ---------------------------------------------------------------------------
# Kalman filter — pupil state [x, y, r, ẋ, ẏ, ṙ]
# ---------------------------------------------------------------------------

KALMAN_SIGMA_Q = 0.5   # process noise std (pixels/s²) — expected acceleration variation
KALMAN_SIGMA_R = 0.1   # measurement noise std (pixels) — subpixel edge fitting uncertainty

# ---------------------------------------------------------------------------
# Corneal reflection (CR) removal
# ---------------------------------------------------------------------------
# IR illuminator creates a bright glint inside the pupil ROI.
# Threshold at 95% of max 16-bit intensity → binary mask → dilate → inpaint.

CR_THRESHOLD_FACTOR = 0.95   # fraction of I_max (65535 for 16-bit)
CR_DILATE_PX        = 2      # dilation radius in pixels to capture blurred boundary

# ---------------------------------------------------------------------------
# Blink state machine
# ---------------------------------------------------------------------------

BLINK_CLOSE_VEL_TH = -15.0   # mm/s — velocity below this triggers Closing state
BLINK_OPEN_VEL_TH  =  10.0   # mm/s — velocity above this triggers Opening state

# ---------------------------------------------------------------------------
# Rolling aperture baseline (fatigue compensation)
# ---------------------------------------------------------------------------
# Baseline = P95 of aperture over the preceding 30 seconds of Open frames.
# Normalised aperture = raw / baseline — removes progressive eyelid droop.

ROLLING_BASELINE_SECS = 30
