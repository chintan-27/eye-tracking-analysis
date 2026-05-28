"""
video/optical_flow.py

RLOFMotionMap: computes dense optical flow using RLOF (Robust Local Optical Flow)
and renders it as an HSV-encoded motion map video frame.

Why RLOF over alternatives:
  - Farneback: polynomial expansion smooths subpixel tremor oscillations (4–6 Hz)
  - DeepFlow / RAFT: spatial regularisation similarly averages micro-oscillations
  - RLOF: Hampel M-estimator on local patches — preserves high-frequency boundary
    motion without cross-pixel spatial smoothing (Senst et al., TU Berlin)

HSV encoding:
  - Hue    → direction (angle of flow vector)
  - Saturation → 255 (max) for full colour visibility
  - Value   → logarithmically compressed magnitude
               V = clip(255 × ln(1+κA) / ln(1+κ×A_max), 0, 255)
               κ=10, A_max=20 px/frame handles slow drift (<0.1) and fast blinks (>15)

During blinks: saturation is set to 0 (grayscale) and a red outline is overlaid
to flag the frame without skewing direction-colour analysis.

Physical units: raw pixel/frame flow is multiplied by γ × fps to give mm/s.
This normalises across the four FPS regimes (24/90/100/167).
"""

from __future__ import annotations

import cv2
import numpy as np

try:
    from cv2 import optflow as cv2_optflow
    _HAS_RLOF = hasattr(cv2_optflow, "calcOpticalFlowDenseRLOF")
except ImportError:
    _HAS_RLOF = False

try:
    _HAS_CUDA = cv2.cuda.getCudaEnabledDeviceCount() > 0
except (cv2.error, AttributeError):
    _HAS_CUDA = False

from video.config import HSV_KAPPA, HSV_A_MAX, FLOW_DEAD_ZONE, FLOW_EXAG_GAIN


class FlowResult:
    __slots__ = ("u", "v", "U_phys", "V_phys", "hsv_bgr")

    def __init__(self, u, v, U_phys, V_phys, hsv_bgr):
        self.u       = u        # horizontal flow, pixels/frame
        self.v       = v        # vertical flow, pixels/frame
        self.U_phys  = U_phys  # horizontal flow, mm/s
        self.V_phys  = V_phys  # vertical flow, mm/s
        self.hsv_bgr = hsv_bgr  # uint8 BGR visualisation frame


class RLOFMotionMap:
    """
    Dense optical flow on stabilised frames.

    Parameters
    ----------
    gamma : float
        mm/pixel scale factor (= INNER_CANTHI_MM / inner_canthi_px).
    fps : float
        Recording frame rate. Used to convert pixels/frame → mm/s.
    """

    def __init__(
        self,
        gamma:     float,
        fps:       float,
        use_rlof:  bool  = False,
        dead_zone: float = FLOW_DEAD_ZONE,
        exag_gain: float = FLOW_EXAG_GAIN,
    ) -> None:
        self.gamma     = gamma
        self.fps       = fps
        self.use_rlof  = use_rlof and _HAS_RLOF
        self._dead_zone = dead_zone   # px/frame — motion below this → rendered as still
        self._exag_gain = exag_gain   # multiply motion above dead_zone by this factor
        self._prev_frame: np.ndarray | None = None
        self._smooth_flow: np.ndarray | None = None
        self._alpha      = 0.35
        self._blink_fade = 0.0
        self._FADE_RATE  = 0.2
        # CLAHE for illumination normalisation — handles multiplicative brightness
        # oscillations (camera AGC, flickering ambient light) without introducing
        # cross-frame scaling artifacts like global mean normalisation does.
        self._clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        # CUDA Farneback — auto-detected; falls back to CPU if unavailable
        self._fb_cuda = None
        if _HAS_CUDA and not use_rlof:
            try:
                self._fb_cuda = cv2.cuda.FarnebackOpticalFlow.create(
                    numLevels=5, pyrScale=0.5, fastPyramids=False,
                    winSize=15, numIters=3, polyN=5, polySigma=1.2, flags=0,
                )
            except Exception:
                self._fb_cuda = None

        import os
        pid = os.getpid()
        if self._fb_cuda is not None:
            try:
                dev = cv2.cuda.DeviceInfo(0)
                backend_str = f"CUDA Farneback on {dev.name()} ({dev.totalMemory()//1024//1024} MB)"
            except Exception:
                backend_str = "CUDA Farneback (device info unavailable)"
        elif self.use_rlof:
            backend_str = "RLOF (CPU)"
        else:
            backend_str = f"CPU Farneback (CUDA {'not compiled in opencv' if not _HAS_CUDA else 'init failed'})"
        print(f"[flow pid={pid}] backend={backend_str}", flush=True)

    def set_previous(self, frame: np.ndarray) -> None:
        """Explicitly set the previous frame (call after stabiliser initialises)."""
        self._prev_frame = self._to_gray8(frame)

    def compute(
        self,
        prev: np.ndarray,
        curr: np.ndarray,
        blink_state: int = 0,
    ) -> FlowResult:
        """
        Compute RLOF dense optical flow between two consecutive stabilised frames
        and render the HSV motion map.

        Parameters
        ----------
        prev : np.ndarray
            Previous stabilised frame (grayscale or BGR, uint8 or uint16).
        curr : np.ndarray
            Current stabilised frame.
        blink_state : int
            0=Open, 1=Closing, 2=Closed, 3=Opening.
            During 2 (Closed), saturation is zeroed and a red outline added.

        Returns
        -------
        FlowResult
        """
        p8 = self._to_gray8(prev)
        c8 = self._to_gray8(curr)

        # Note: EqualizeHist + Retinex are applied upstream (normalize.py),
        # so no additional normalisation needed here.

        # Remove corneal reflections before computing flow.
        p8 = self._remove_specular(p8)
        c8 = self._remove_specular(c8)

        if _HAS_RLOF and self.use_rlof:
            # RLOF requires 3-channel BGR input
            p_bgr = cv2.cvtColor(p8, cv2.COLOR_GRAY2BGR)
            c_bgr = cv2.cvtColor(c8, cv2.COLOR_GRAY2BGR)
            flow = cv2_optflow.calcOpticalFlowDenseRLOF(p_bgr, c_bgr, None)
        elif self._fb_cuda is not None:
            gpu_p = cv2.cuda_GpuMat(); gpu_p.upload(p8)
            gpu_c = cv2.cuda_GpuMat(); gpu_c.upload(c8)
            flow = self._fb_cuda.calc(gpu_p, gpu_c, None).download()
        else:
            flow = cv2.calcOpticalFlowFarneback(
                p8, c8, None,
                pyr_scale=0.5, levels=3, winsize=15,
                iterations=3, poly_n=5, poly_sigma=1.2, flags=0,
            )

        # Temporal EMA smoothing — reduces frame-to-frame flicker from camera
        # noise and compression artefacts without blurring real motion events.
        # Reset after blinks (state == 0 means eye just re-opened) so the
        # smoothed field doesn't carry over stale blink-motion into open frames.
        if self._smooth_flow is None or blink_state == 3:
            self._smooth_flow = flow.copy()
        else:
            self._smooth_flow = self._alpha * flow + (1 - self._alpha) * self._smooth_flow
        flow_display = self._smooth_flow

        u = flow[..., 0]        # raw flow for biomarker features
        v = flow[..., 1]
        U_phys = u * self.gamma * self.fps
        V_phys = v * self.gamma * self.fps

        hsv_bgr = self._render_hsv(flow_display[..., 0], flow_display[..., 1], blink_state)
        return FlowResult(u, v, U_phys, V_phys, hsv_bgr)

    def apply_eye_mask(
        self,
        hsv_bgr: np.ndarray,
        pupil_x: float,
        pupil_y: float,
        pupil_r: float,
        eye_scale: float = 4.5,
        fade_px: int = 25,
    ) -> np.ndarray:
        """
        Eye-shaped elliptical vignette:
          - Full colour inside the ellipse
          - Linear fade to black over fade_px pixels outside the ellipse edge
          - Fully black beyond that

        eye_scale: how many pupil-radii the ellipse spans (horizontal).
        fade_px:   width of the gradient border in pixels.
        """
        h, w = hsv_bgr.shape[:2]
        cx, cy = pupil_x, pupil_y
        rx = pupil_r * eye_scale
        ry = pupil_r * eye_scale * 0.52   # eye is notably wider than tall

        ys, xs = np.ogrid[:h, :w]
        # Normalised elliptical distance: 1.0 exactly on the ellipse boundary
        dist = np.sqrt(((xs - cx) / rx) ** 2 + ((ys - cy) / ry) ** 2)

        # Convert distance to a pixel-space distance from the ellipse edge
        # dist=1 → edge, dist<1 → inside, dist>1 → outside
        # Scale so that fade_px pixels outside maps to weight=0
        scale = min(rx, ry)   # approximate pixel scale
        px_dist = (dist - 1.0) * scale   # negative inside, positive outside

        weight = np.where(
            px_dist <= 0,
            1.0,                                           # fully inside
            np.where(
                px_dist <= fade_px,
                1.0 - px_dist / fade_px,                  # linear fade
                0.0,                                       # fully outside
            ),
        ).astype(np.float32)

        out = hsv_bgr.astype(np.float32) * weight[:, :, np.newaxis]
        return np.clip(out, 0, 255).astype(np.uint8)

    def roi_stats(
        self,
        result: FlowResult,
        roi: tuple[int, int, int, int],
    ) -> dict:
        """
        Compute mean and P95 of flow magnitude within a rectangular ROI.

        Parameters
        ----------
        roi : (x, y, w, h) in pixels of the stabilised frame.
        """
        x, y, w, h = roi
        mag = np.sqrt(result.U_phys[y:y+h, x:x+w]**2 +
                      result.V_phys[y:y+h, x:x+w]**2)
        vert = result.V_phys[y:y+h, x:x+w]
        return {
            "mag_mean": float(mag.mean()),
            "mag_p95":  float(np.percentile(mag, 95)),
            "vert_mean": float(vert.mean()),
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _remove_specular(self, gray: np.ndarray) -> np.ndarray:
        """
        Remove specular corneal reflections (IR glints) from a uint8 grayscale frame
        before optical flow computation.

        The IR illuminator produces bright spots that are significantly above the
        local mean. We threshold relative to the LOCAL neighbourhood max (not global
        max) so we don't accidentally mask genuinely bright skin regions.

        Steps:
          1. Threshold: pixels where I > 0.92 × local_max in a 30×30 neighbourhood
          2. Dilate mask 3px to capture blurred glint boundary
          3. Inpaint with Navier-Stokes (fills from surrounding pupil/iris texture)
        """
        # CR spots are statistical outliers — far above the frame mean.
        # Threshold at mean + 4×std, which isolates only the brightest glints.
        f32   = gray.astype(np.float32)
        mean  = f32.mean()
        std   = f32.std()
        limit = mean + 4.0 * std
        limit = min(limit, 240.0)   # never go below 240 in uint8 range

        mask = (f32 > limit).astype(np.uint8) * 255
        if mask.sum() == 0:
            return gray

        dilate_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        mask     = cv2.dilate(mask, dilate_k)
        return cv2.inpaint(gray, mask, 3, cv2.INPAINT_NS)

    # Minimum magnitude (px/frame) below which a pixel is shown as grey, not coloured.
    # Prevents hue-flickering in near-static regions from camera noise.
    _SAT_RAMP_LOW  = 0.05   # px/frame — below this: no colour (saturation = 0)
    _SAT_RAMP_HIGH = 0.30   # px/frame — above this: full colour (saturation = 255)

    def _render_hsv(self, u: np.ndarray, v: np.ndarray, blink_state: int) -> np.ndarray:
        """Build BGR uint8 HSV visualisation frame."""
        angle = np.arctan2(v, u)                             # [-π, π]
        hue   = ((angle + np.pi) / (2 * np.pi) * 179).astype(np.uint8)

        mag = np.sqrt(u**2 + v**2)

        # Motion exaggeration filter:
        #   1. Dead-zone: movements below _dead_zone treated as zero (suppress noise).
        #   2. Gain: remaining motion multiplied by _exag_gain to amplify real events.
        # Direction (hue) is preserved unchanged — only the rendered magnitude changes.
        if self._dead_zone > 0.0 or self._exag_gain != 1.0:
            mag_display = np.maximum(0.0, mag - self._dead_zone) * self._exag_gain
        else:
            mag_display = mag

        kappa = HSV_KAPPA
        a_max = HSV_A_MAX
        val   = 255.0 * np.log1p(kappa * mag_display) / np.log1p(kappa * a_max)
        val   = np.clip(val, 0, 255).astype(np.uint8)

        # Fade blink desaturation in/out gradually — avoids a hard flash on blink onset
        if blink_state == 2:
            self._blink_fade = min(1.0, self._blink_fade + self._FADE_RATE)
        else:
            self._blink_fade = max(0.0, self._blink_fade - self._FADE_RATE)

        lo, hi = self._SAT_RAMP_LOW, self._SAT_RAMP_HIGH
        sat_f  = np.clip((mag_display - lo) / (hi - lo), 0.0, 1.0) * 255.0
        sat_f  = sat_f * (1.0 - self._blink_fade)   # smoothly fade to grey during blinks
        sat    = sat_f.astype(np.uint8)

        hsv = np.stack([hue, sat, val], axis=-1)
        bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

        if blink_state == 2:
            cv2.rectangle(bgr, (0, 0), (bgr.shape[1]-1, bgr.shape[0]-1),
                          (0, 0, 200), 2)

        return bgr

    @staticmethod
    def _to_gray8(frame: np.ndarray) -> np.ndarray:
        """Convert to uint8 grayscale; handles uint16 and BGR."""
        if frame.ndim == 3 and frame.shape[2] == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame.copy()
        if gray.dtype == np.uint16:
            gray = (gray >> 8).astype(np.uint8)
        return gray
