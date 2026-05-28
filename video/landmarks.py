"""
video/landmarks.py

EyelidLandmarks: measures palpebral aperture (eyelid opening distance) per frame.

Two modes:

  use_pipnet=False (prototype / default):
    Intensity-based aperture estimation. Scans a narrow vertical band around
    the pupil centre, estimates upper/lower eyelid edges for multiple columns,
    rejects outliers, and computes aperture in mm using γ.
    No model weights required.

  use_pipnet=True (Phase 2 — not yet implemented):
    PIPNet 12-point single-eye landmark detector. Requires a custom-trained model
    checkpoint trained on cropped eye images. Will be integrated in Phase 2.

Aperture velocity uses a 5-point central difference (minimises high-freq noise):
  Ȧ(t) = (−A[t+2] + 8A[t+1] − 8A[t−1] + A[t−2]) / (12Δt)
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class LandmarkResult:
    aperture_mm:    float           # palpebral opening in mm
    velocity_mms:   float           # aperture velocity in mm/s (5-point CD)
    aperture_norm:  float           # aperture / 30-s rolling baseline (0–1)
    points:         np.ndarray | None   # (12, 2) array if PIPNet; None for fallback


class EyelidLandmarks:
    """
    Parameters
    ----------
    gamma : float
        mm/pixel scale factor.
    fps : float
        Recording frame rate.
    use_pipnet : bool
        If True, attempt to load PIPNet (Phase 2). Falls back to intensity method.
    rolling_baseline_secs : float
        Duration of rolling aperture baseline window in seconds.
    """

    def __init__(
        self,
        gamma: float,
        fps: float,
        use_pipnet: bool = False,
        rolling_baseline_secs: float = 30.0,
    ) -> None:
        self.gamma     = gamma
        self.fps       = fps
        self._dt       = 1.0 / fps
        self._use_pipnet = use_pipnet and self._try_load_pipnet()

        self._last_aperture_mm: float = 0.0

        # 5-point central difference buffer [A_{t-2}, A_{t-1}, A_t, A_{t+1}, A_{t+2}]
        self._aperture_buf: deque[float] = deque([0.0] * 5, maxlen=5)

        # Rolling baseline: P95 of aperture over last N Open frames
        self._baseline_n = int(rolling_baseline_secs * fps)
        self._open_apertures: deque[float] = deque(maxlen=self._baseline_n)
        self._baseline_mm: float = 0.0

    def measure(
        self,
        frame: np.ndarray,
        pupil_x: float,
        pupil_y: float,
        blink_state: int = 0,
    ) -> LandmarkResult:
        """
        Measure eyelid aperture and velocity for one stabilised frame.

        Parameters
        ----------
        frame : np.ndarray
            Stabilised eye frame (grayscale or BGR, uint8 or uint16).
        pupil_x, pupil_y : float
            Pupil centre coordinates in the stabilised frame.
        blink_state : int
            Current blink state (0=Open, 1=Closing, 2=Closed, 3=Opening).

        Returns
        -------
        LandmarkResult
        """
        if self._use_pipnet:
            aperture_mm, points = self._pipnet_measure(frame, pupil_x, pupil_y)
        else:
            aperture_mm, points = self._intensity_measure(frame, pupil_x, pupil_y)

        # Push into velocity buffer
        self._aperture_buf.append(aperture_mm)
        velocity = self._five_point_cd()

        # Update rolling baseline with Open-state apertures
        if blink_state == 0 and aperture_mm > 0:
            self._open_apertures.append(aperture_mm)
            if len(self._open_apertures) >= 10:
                self._baseline_mm = float(np.percentile(list(self._open_apertures), 95))

        norm = (aperture_mm / self._baseline_mm) if self._baseline_mm > 1e-3 else 0.0

        return LandmarkResult(
            aperture_mm=aperture_mm,
            velocity_mms=velocity,
            aperture_norm=float(np.clip(norm, 0.0, 1.5)),
            points=points,
        )

    # ------------------------------------------------------------------
    # Intensity-based aperture estimation (prototype)
    # ------------------------------------------------------------------

    def _intensity_measure(
        self, frame: np.ndarray, pupil_x: float, pupil_y: float
    ) -> tuple[float, np.ndarray | None]:
        """
        Scan a small vertical band around the pupil centre instead of one
        column. The median over valid columns is much less sensitive to glints,
        lashes, and one-frame pupil-centre jitter.
        """
        gray = self._to_gray8(frame)
        h, w = gray.shape
        if pupil_x <= 0 or pupil_y <= 0:
            return self._last_aperture_mm, None

        px = int(np.clip(round(pupil_x), 2, w - 3))
        py = int(np.clip(round(pupil_y), 2, h - 3))
        half_band = max(3, min(12, int(round(0.45 / max(self.gamma, 1e-6)))))
        cols = np.arange(max(1, px - half_band), min(w - 1, px + half_band + 1), 2)
        if len(cols) == 0:
            return self._last_aperture_mm, None

        y0 = max(0, py - int(round(7.0 / max(self.gamma, 1e-6))))
        y1 = min(h, py + int(round(7.0 / max(self.gamma, 1e-6))))
        if y1 - y0 < 12:
            return self._last_aperture_mm, None

        apertures = []
        points = []
        kernel = np.array([-1, 0, 1], dtype=np.float32)
        local_py = py - y0
        for col in cols:
            signal = gray[y0:y1, col].astype(np.float32)
            signal = cv2.GaussianBlur(signal[:, None], (1, 5), 0).ravel()
            grad = np.convolve(signal, kernel, mode="same")

            upper_region = grad[:local_py]
            lower_region = grad[local_py:]
            if len(upper_region) < 3 or len(lower_region) < 3:
                continue
            upper_edge = y0 + int(np.argmax(upper_region))
            lower_edge = y0 + local_py + int(np.argmin(lower_region))
            aperture_px = float(lower_edge - upper_edge)
            if 3 <= aperture_px <= h * 0.65:
                apertures.append(aperture_px)
                points.extend([(float(col), float(upper_edge)), (float(col), float(lower_edge))])

        if not apertures:
            return self._last_aperture_mm, None

        vals = np.asarray(apertures, dtype=np.float32)
        med = float(np.median(vals))
        mad = float(np.median(np.abs(vals - med)))
        if mad > 1e-6:
            vals = vals[np.abs(vals - med) <= 2.5 * mad]
        aperture_mm = float(np.median(vals)) * self.gamma
        if self._last_aperture_mm > 0:
            aperture_mm = 0.65 * aperture_mm + 0.35 * self._last_aperture_mm
        self._last_aperture_mm = aperture_mm
        return aperture_mm, np.asarray(points, dtype=np.float32) if points else None

    # ------------------------------------------------------------------
    # PIPNet (Phase 2 stub)
    # ------------------------------------------------------------------

    def _try_load_pipnet(self) -> bool:
        """Attempt to import PIPNet. Returns False if not available."""
        try:
            import torch  # noqa: F401
            # TODO: load custom-trained 12-point PIPNet checkpoint
            return False  # placeholder until checkpoint is available
        except ImportError:
            return False

    def _pipnet_measure(
        self, frame: np.ndarray, pupil_x: float, pupil_y: float
    ) -> tuple[float, np.ndarray | None]:
        """PIPNet inference — not yet implemented."""
        return self._intensity_measure(frame, pupil_x, pupil_y)

    # ------------------------------------------------------------------
    # Velocity computation
    # ------------------------------------------------------------------

    def _five_point_cd(self) -> float:
        """
        5-point central difference on the aperture buffer.
        Requires at least 5 samples; returns 0 before buffer fills.
        Ȧ = (−A[t+2] + 8A[t+1] − 8A[t−1] + A[t−2]) / (12Δt)
        """
        buf = list(self._aperture_buf)
        if len(buf) < 5:
            return 0.0
        a = buf
        return float((-a[4] + 8*a[3] - 8*a[1] + a[0]) / (12 * self._dt))

    @staticmethod
    def _to_gray8(frame: np.ndarray) -> np.ndarray:
        if frame.ndim == 3 and frame.shape[2] == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame.copy()
        if gray.dtype == np.uint16:
            gray = (gray >> 8).astype(np.uint8)
        return gray
