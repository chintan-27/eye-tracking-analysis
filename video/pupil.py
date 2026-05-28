"""
video/pupil.py

PupilTracker: detects and tracks the pupil using pupil-detectors (Pupil Labs)
as the primary detector, with a Kalman filter for temporal smoothing and gap
interpolation.

pupil-detectors uses the Pupil Labs 2D detector — specifically designed for
high-speed IR eye cameras. It returns an ellipse (handles partial eyelid
occlusion) and a confidence score (0-1).

Pipeline per frame:
  1. Run Detector2D on raw grayscale frame
  2. If confidence >= threshold → Kalman update
  3. If confidence < threshold → Kalman predict-only (interpolation)
  4. After REINIT_AFTER consecutive low-confidence frames → re-detect from scratch
  5. Compute P-CR vector: pupil centre − CR centre (pure ocular rotation)

Kalman state: [x, y, r, ẋ, ẏ, ṙ]  (r = mean radius of ellipse)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np
from filterpy.kalman import KalmanFilter

try:
    from pupil_detectors import Detector2D as _Detector2D
    _HAS_PUPIL_DETECTORS = True
except ImportError:
    _HAS_PUPIL_DETECTORS = False

from video.config import (
    PUPIL_ROI_SCALE,
    KALMAN_SIGMA_Q, KALMAN_SIGMA_R,
    CR_THRESHOLD_FACTOR, CR_DILATE_PX,
)

_CONF_THRESHOLD  = 0.4    # below this → skip Kalman update (interpolate)
_REINIT_AFTER    = 15     # consecutive low-conf frames before full re-detect
_PUPIL_MIN_R     = 4      # px minimum radius to accept detection
_PUPIL_MAX_R_MM  = 9.0    # mm maximum pupil diameter / 2


@dataclass
class PupilResult:
    x:           float
    y:           float
    r:           float          # mean semi-axis in pixels
    diameter_mm: float
    cr_x:        float          # -1 if no CR detected
    cr_y:        float
    p_cr_x:      float          # pupil-CR vector (pure rotation)
    p_cr_y:      float
    confidence:  float          # 0-1 from pupil-detectors
    valid:       bool


class PupilTracker:
    """
    Parameters
    ----------
    gamma : float
        mm/pixel scale factor for the Phantom video frame.
    fps : float
        Recording frame rate.
    """

    def __init__(self, gamma: float, fps: float) -> None:
        self.gamma      = gamma
        self.fps        = fps
        self._dt        = 1.0 / fps
        self._max_r     = max(int(round(_PUPIL_MAX_R_MM / gamma)), 10)

        if _HAS_PUPIL_DETECTORS:
            self._detector = _Detector2D()
        else:
            self._detector = None

        self._kf:          KalmanFilter | None = None
        self._initialized  = False
        self._low_conf_streak = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def initialize(self, raw_gray: np.ndarray) -> bool:
        """Detect pupil in one frame. Returns True if found."""
        result = self._detect(raw_gray)
        if result is None:
            return False
        x, y, r, conf = result
        self._init_kalman(x, y, r)
        self._initialized       = True
        self._low_conf_streak   = 0
        return True

    def initialize_from_cap(
        self, cap: "cv2.VideoCapture", max_search_frames: int = 60
    ) -> bool:
        """Scan up to max_search_frames to find an open eye."""
        start = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
        for _ in range(max_search_frames):
            ok, raw = cap.read()
            if not ok:
                break
            gray = self._to_gray8(raw)
            if self.initialize(gray):
                found = int(cap.get(cv2.CAP_PROP_POS_FRAMES)) - 1
                cap.set(cv2.CAP_PROP_POS_FRAMES, found)
                return True
        cap.set(cv2.CAP_PROP_POS_FRAMES, start)
        return False

    def process_frame(
        self,
        raw_gray: np.ndarray,
        blink_state: int = 0,
    ) -> PupilResult:
        """
        Track pupil in one frame.

        raw_gray must be a raw (non-equalised) uint8 grayscale frame.
        blink_state: 0=Open, 1=Closing, 2=Closed, 3=Opening
        """
        # Auto-reinit after too many bad frames
        if self._low_conf_streak >= _REINIT_AFTER:
            self._initialized     = False
            self._low_conf_streak = 0

        if not self._initialized:
            if not self.initialize(raw_gray):
                self._low_conf_streak += 1
                return PupilResult(0, 0, 0, 0, -1, -1, 0, 0, 0.0, False)

        self._kf.predict()
        kx = float(self._kf.x[0, 0])
        ky = float(self._kf.x[1, 0])
        kr = float(self._kf.x[2, 0])

        # Sanity check on Kalman radius
        if kr > self._max_r * 1.5 or kr < 1:
            self._initialized = False
            self._low_conf_streak += 1
            return PupilResult(0, 0, 0, 0, -1, -1, 0, 0, 0.0, False)

        # During closed blink — predict only
        if blink_state == 2:
            self._kf.P += self._kf.Q
            self._low_conf_streak += 1
            return PupilResult(kx, ky, kr, 2*kr*self.gamma,
                               -1, -1, 0, 0, 0.0, False)

        # Run detector
        det = self._detect(raw_gray)
        conf = det[3] if det is not None else 0.0

        if det is not None and conf >= _CONF_THRESHOLD:
            dx, dy, dr, _ = det
            h, w = raw_gray.shape
            # Anatomical sanity: pupil must be in the lower 80% of frame
            # (top 20% = eyebrow territory), not at frame edges, and
            # not jumping more than 2.5× radius from Kalman prediction.
            in_eye_zone  = dy > h * 0.15 and dy < h * 0.90
            in_frame     = dx > 5 and dx < w - 5
            near_predict = np.sqrt((dx-kx)**2 + (dy-ky)**2) < kr * 2.5
            size_ok      = abs(dr - kr) / max(kr, 1) < 0.5
            if in_eye_zone and in_frame and near_predict and size_ok:
                self._kf.update(np.array([[dx], [dy], [dr]]))
                self._low_conf_streak = 0
            else:
                self._low_conf_streak += 1
        else:
            self._low_conf_streak += 1

        px = float(self._kf.x[0, 0])
        py = float(self._kf.x[1, 0])
        pr = float(self._kf.x[2, 0])

        # Corneal reflection
        cr_x, cr_y = self._detect_cr(raw_gray, px, py, pr)
        p_cr_x = px - cr_x if cr_x >= 0 else 0.0
        p_cr_y = py - cr_y if cr_y >= 0 else 0.0

        return PupilResult(
            x=px, y=py, r=pr,
            diameter_mm=2.0 * pr * self.gamma,
            cr_x=cr_x, cr_y=cr_y,
            p_cr_x=p_cr_x, p_cr_y=p_cr_y,
            confidence=conf,
            valid=True,
        )

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def _detect(self, gray: np.ndarray) -> tuple[float, float, float, float] | None:
        """
        Run primary detector. Returns (x, y, r, confidence) or None.
        Falls back to dark-blob CR-first if pupil-detectors not available.
        """
        if self._detector is not None:
            return self._detect_pupil_labs(gray)
        return self._detect_dark_blob(gray)

    def _detect_pupil_labs(
        self, gray: np.ndarray
    ) -> tuple[float, float, float, float] | None:
        """Run Pupil Labs Detector2D."""
        h, w = gray.shape
        # Exclude timestamp bar from detection
        search = gray[:int(h * 0.85), :]
        result = self._detector.detect(search)
        conf   = float(result.get("confidence", 0))
        cx, cy = result["ellipse"]["center"]
        axes   = result["ellipse"]["axes"]
        r      = float((axes[0] + axes[1]) / 4)   # mean semi-axis

        if r < _PUPIL_MIN_R or r > self._max_r:
            return None
        return float(cx), float(cy), r, conf

    def _detect_dark_blob(
        self, gray: np.ndarray
    ) -> tuple[float, float, float, float] | None:
        """CR-first dark blob fallback when pupil-detectors not installed."""
        h, w = gray.shape
        search = gray[:int(h * 0.85), :]
        flat   = search.flatten()
        cr_thresh = max(int(np.percentile(flat, 99.5)), 120)
        _, crb = cv2.threshold(search, cr_thresh, 255, cv2.THRESH_BINARY)
        num, _, stats, cents = cv2.connectedComponentsWithStats(crb, 8)

        border  = 10
        candidates = []
        for ci in range(1, num):
            a = int(stats[ci, 4])
            bx, by, bw, bh = int(stats[ci,0]),int(stats[ci,1]),int(stats[ci,2]),int(stats[ci,3])
            if a < 2 or a > self._max_r**2: continue
            if bx<border or by<border or bx+bw>w-border or by+bh>h-border: continue
            cx_, cy_ = float(cents[ci][0]), float(cents[ci][1])
            nx0,ny0 = int(max(cx_-20,0)),int(max(cy_-20,0))
            nx1,ny1 = int(min(cx_+20,w)),int(min(cy_+20,h))
            nbhd = float(search[ny0:ny1,nx0:nx1].mean())
            candidates.append((nbhd, a, cx_, cy_))
        candidates.sort()

        if not candidates:
            return None

        _, _, cr_cx, cr_cy = candidates[0]
        margin = self._max_r * 2
        x0 = int(max(cr_cx-margin,0)); y0 = int(max(cr_cy-margin,0))
        x1 = int(min(cr_cx+margin,w)); y1 = int(min(cr_cy+margin,h))
        roi = search[y0:y1, x0:x1]

        blob = self._blob_in_roi(roi)
        if blob is None:
            return None
        rx, ry, r = blob
        return float(rx+x0), float(ry+y0), r, 0.5   # fixed confidence for fallback

    def _blob_in_roi(self, roi: np.ndarray) -> tuple[float,float,float] | None:
        flat = roi.flatten(); flat = flat[flat>0]
        if len(flat) == 0: return None
        thresh = min(int(np.percentile(flat, 5)), 60)
        _, binary = cv2.threshold(roi, thresh, 255, cv2.THRESH_BINARY_INV)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5,5))
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, k)
        num, lbl, stats, cents = cv2.connectedComponentsWithStats(binary, 8)
        best, best_score = None, 0.0
        h, w = binary.shape
        min_r = max(int(round(1.5/self.gamma)), 3)
        for i in range(1, num):
            a = int(stats[i,4]); r = float(np.sqrt(a/np.pi))
            if r < min_r or r > self._max_r: continue
            bx,by,bw,bh_ = int(stats[i,0]),int(stats[i,1]),int(stats[i,2]),int(stats[i,3])
            aspect = min(bw,bh_)/max(bw,bh_) if max(bw,bh_)>0 else 0
            if aspect < 0.3: continue
            score = aspect * a
            if score > best_score:
                best_score = score
                best = (float(cents[i][0]), float(cents[i][1]), r)
        return best

    # ------------------------------------------------------------------
    # Corneal reflection
    # ------------------------------------------------------------------

    def _detect_cr(
        self, gray: np.ndarray, px: float, py: float, pr: float
    ) -> tuple[float, float]:
        """Find CR centroid in a ROI around the pupil. Returns (-1,-1) if not found."""
        h, w = gray.shape
        half = int(pr * PUPIL_ROI_SCALE)
        x0 = int(max(px-half, 0)); y0 = int(max(py-half, 0))
        x1 = int(min(px+half, w)); y1 = int(min(py+half, h))
        roi = gray[y0:y1, x0:x1]
        if roi.size == 0:
            return -1.0, -1.0
        i_max = int(roi.max())
        if i_max == 0:
            return -1.0, -1.0
        thresh = int(CR_THRESHOLD_FACTOR * i_max)
        _, mask = cv2.threshold(roi, thresh, 255, cv2.THRESH_BINARY)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                      (2*CR_DILATE_PX+1, 2*CR_DILATE_PX+1))
        mask = cv2.dilate(mask, k)
        m = cv2.moments(mask)
        if m["m00"] == 0:
            return -1.0, -1.0
        return float(m["m10"]/m["m00"]) + x0, float(m["m01"]/m["m00"]) + y0

    # ------------------------------------------------------------------
    # Kalman filter
    # ------------------------------------------------------------------

    def _init_kalman(self, x: float, y: float, r: float) -> None:
        dt = self._dt
        kf = KalmanFilter(dim_x=6, dim_z=3)
        kf.F = np.array([
            [1,0,0,dt,0, 0],
            [0,1,0,0,dt, 0],
            [0,0,1,0, 0,dt],
            [0,0,0,1, 0, 0],
            [0,0,0,0, 1, 0],
            [0,0,0,0, 0, 1],
        ])
        kf.H = np.eye(3, 6)
        q = KALMAN_SIGMA_Q ** 2
        dt2, dt3, dt4 = dt**2, dt**3, dt**4
        Q3 = np.array([[dt4/4, dt3/2],[dt3/2, dt2]])
        kf.Q = q * np.block([
            [np.kron(np.eye(3), Q3[:1,:1]), np.kron(np.eye(3), Q3[:1,1:])],
            [np.kron(np.eye(3), Q3[1:,:1]), np.kron(np.eye(3), Q3[1:,1:])],
        ])
        kf.R = (KALMAN_SIGMA_R ** 2) * np.eye(3)
        kf.x = np.array([[x],[y],[r],[0.],[0.],[0.]])
        kf.P = np.eye(6) * 10.0
        self._kf = kf

    @staticmethod
    def _to_gray8(frame: np.ndarray) -> np.ndarray:
        if frame.ndim == 3:
            return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if frame.dtype == np.uint16:
            return (frame >> 8).astype(np.uint8)
        return frame.copy()
