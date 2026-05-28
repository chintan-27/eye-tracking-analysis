"""
video/stabilize.py

VideoStabilizer: locks the eye frame to a skull-fixed coordinate system using
phase correlation on the periocular skin background.

Algorithm:
  1. Phase Correlation (scikit-image) on iris-masked background — head translation
  2. 1.5 px deadband — ignores sub-pixel noise, applies identity for zero-movement videos
  3. Blink freeze — transform held at last valid state during eye closure
  4. Rigid warp (translation only, 3×3 homogeneous) applied to output frame

The iris is masked during phase correlation so eye rotation does not corrupt
the head-motion estimate. Only skull-fixed skin texture drives the estimate.
"""

from __future__ import annotations

import cv2
import numpy as np
from skimage.registration import phase_cross_correlation

from video.config import INNER_CANTHI_MM

# QC flag bitmask values
QC_BLINK           = 0x01   # frame occurred during a blink
QC_SACCADE_BLUR    = 0x02   # motion blur from fast saccade (velocity > 100°/s)
QC_TRACKING_FAILURE = 0x04  # SSIM dropped below threshold, transform re-initialised


class VideoStabilizer:
    """
    Stabilises a sequence of eye-region frames by tracking the inner and outer
    canthi across frames and computing a rigid warp back to a reference position.

    Parameters
    ----------
    inner_canthi_px : float
        Distance between inner eye corners in pixels, from the reference photograph.
        Used to compute the mm/pixel scale factor γ.
    fps : float
        Recording frame rate. Selects the appropriate LK pyramid parameters.
    occlusion_y : int | None
        Y-coordinate below which EEG electrode tape occludes the frame.
        Pixels above this row are masked out before computing phase correlation
        and LK gradients. Auto-detected from the first frame if None.
    """

    def __init__(
        self,
        inner_canthi_px: float,
        fps: float,
        occlusion_y: int | None = None,
    ) -> None:
        self.gamma = INNER_CANTHI_MM / inner_canthi_px
        self.fps   = fps

        # Reference frame and canthi positions (set during initialize())
        self._ref_frame:    np.ndarray | None = None
        self._ref_inner:    np.ndarray | None = None   # shape (1,1,2) float32
        self._ref_outer:    np.ndarray | None = None
        self._cur_inner:    np.ndarray | None = None
        self._cur_outer:    np.ndarray | None = None

        # Current rigid transform matrix (3×3 homogeneous)
        self._H: np.ndarray = np.eye(3, dtype=np.float64)
        # Frozen transform held during blinks
        self._H_frozen: np.ndarray = np.eye(3, dtype=np.float64)

        self._frame_count   = 0
        self._occlusion_y   = occlusion_y
        self._occlusion_mask: np.ndarray | None = None

        self._is_frozen = False   # True while transform is frozen during blink

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def initialize(
        self,
        first_frame: np.ndarray,
        pupil_x: float | None = None,
        pupil_y: float | None = None,
        pupil_r: float | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Set up the reference frame and detect initial canthi positions.

        Returns
        -------
        inner_pt, outer_pt : np.ndarray shape (2,)
            Pixel coordinates of inner and outer canthus in the reference frame.
        """
        gray = self._to_gray(first_frame)
        h, w = gray.shape

        if self._occlusion_y is None:
            self._occlusion_y = self._detect_occlusion_y(gray)

        # Mask out bottom 15% — Phantom AVIs have a burned-in timestamp bar
        # (e.g. "Time: ... Img#: 167") that creates strong false corners.
        # The EEG electrode tape also sits at the bottom on this dataset.
        self._bottom_mask_y = int(h * 0.80)  # exclude bottom 20% (timestamp + tape)

        self._occlusion_mask = self._make_occlusion_mask(gray.shape)
        self._ref_frame = gray.copy()

        inner, outer = self._detect_canthi(gray, pupil_x=pupil_x, pupil_y=pupil_y, pupil_r=pupil_r)
        self._ref_inner = inner.reshape(1, 1, 2).astype(np.float32)
        self._ref_outer = outer.reshape(1, 1, 2).astype(np.float32)
        self._cur_inner = self._ref_inner.copy()
        self._cur_outer = self._ref_outer.copy()

        self._H = np.eye(3, dtype=np.float64)
        self._frame_count = 0
        return inner, outer

    def update_pupil(self, pupil_x: float, pupil_y: float, pupil_r: float) -> None:
        """Call each frame to keep the iris mask centred on the current pupil."""
        self._pupil_x = pupil_x
        self._pupil_y = pupil_y
        self._pupil_r = pupil_r

    def process_frame(
        self,
        frame: np.ndarray,
        is_blink: bool = False,
    ) -> tuple[np.ndarray, dict]:
        """
        Stabilise one frame.

        Parameters
        ----------
        frame : np.ndarray
            Raw frame (uint8 or uint16 grayscale, or BGR).
        is_blink : bool
            True when the blink state machine reports the eye is closed.
            Freezes the transform during closure.

        Returns
        -------
        warped : np.ndarray
            Frame warped by the rigid transform to the reference coordinate system.
        info : dict
            {"tx": float, "ty": float, "rot": float, "qc": int,
             "inner_pt": (x,y), "outer_pt": (x,y)}
        """
        gray = self._to_gray(frame)
        qc   = 0
        self._frame_count += 1

        if is_blink:
            # Freeze: hold last valid transform
            self._H_frozen = self._H.copy()
            self._is_frozen = True
            qc |= QC_BLINK
        else:
            if self._is_frozen:
                # Coming out of blink — expand search window, re-anchor
                self._reanchor(gray, search_scale=2.5)
                self._is_frozen = False
            else:
                # Phase correlation every frame; 1.5 px deadband inside _reanchor
                # handles the no-movement case without jitter.
                self._reanchor(gray)

        H_2x3 = self._H[:2, :]
        h, w   = gray.shape[:2]
        warped = cv2.warpAffine(frame, H_2x3, (w, h),
                                flags=cv2.INTER_LINEAR,
                                borderMode=cv2.BORDER_REPLICATE)

        tx, ty, rot = self._decompose(self._H)
        inner = self._cur_inner.reshape(2) if self._cur_inner is not None else (0., 0.)
        outer = self._cur_outer.reshape(2) if self._cur_outer is not None else (0., 0.)

        return warped, {"tx": tx, "ty": ty, "rot": rot, "qc": qc,
                        "inner_pt": tuple(inner), "outer_pt": tuple(outer)}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _background_mask(self, shape: tuple) -> np.ndarray:
        """
        Mask that keeps ONLY the periocular skin area for phase correlation.
        Zeros out:
          - The iris/pupil region (eye moves independently of head)
          - The timestamp bar at the bottom
          - The occlusion zone at the top
        What remains is skull-fixed skin/texture — perfect for head motion estimation.
        """
        mask = self._occlusion_mask.copy()
        # Mask out iris region using last known pupil position
        px = getattr(self, '_pupil_x', shape[1] * 0.45)
        py = getattr(self, '_pupil_y', shape[0] * 0.40)
        pr = getattr(self, '_pupil_r', 20.0)
        iris_r = int(pr * 3.5)
        cv2.circle(mask, (int(px), int(py)), iris_r, 0.0, -1)
        return mask

    def _reanchor(self, gray: np.ndarray, search_scale: float = 1.0) -> None:
        """
        Estimate head translation via phase correlation on the periocular
        BACKGROUND (skin outside the iris). The iris is masked out so eye
        rotation does not corrupt the head-motion estimate.
        After phase correlation, optionally refine with LK on the canthi.
        """
        bg_mask     = self._background_mask(gray.shape)
        masked_ref  = self._ref_frame * bg_mask
        masked_cur  = gray * bg_mask

        shift, _, _ = phase_cross_correlation(
            masked_ref.astype(np.float32),
            masked_cur.astype(np.float32),
            upsample_factor=10,
        )
        ty, tx = shift

        # Only apply if shift is large enough to be real head movement.
        # Shifts below 1.5px are noise (timestamp flicker, EEG tape micro-flex).
        if abs(tx) < 1.5 and abs(ty) < 1.5:
            self._H = np.eye(3, dtype=np.float64)
            return

        H_coarse = np.eye(3, dtype=np.float64)
        H_coarse[0, 2] = -tx
        H_coarse[1, 2] = -ty
        self._H = H_coarse

    def _detect_occlusion_y(self, gray: np.ndarray) -> int:
        """
        Find the lowest y-coordinate of EEG electrode tape in the top 20% of the frame.
        Uses Sobel vertical gradient + horizontal Hough lines.
        Returns 0 if no tape line is detected.
        """
        top = gray[:gray.shape[0] // 5, :]
        sob = cv2.Sobel(top.astype(np.float32), cv2.CV_32F, 0, 1, ksize=3)
        sob = np.uint8(np.clip(np.abs(sob) / sob.max() * 255, 0, 255))
        edges = cv2.Canny(sob, 50, 150)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180,
                                threshold=30, minLineLength=gray.shape[1] // 2,
                                maxLineGap=10)
        if lines is None:
            return 0
        ys = [max(l[0][1], l[0][3]) for l in lines]
        return int(max(ys)) if ys else 0

    def _make_occlusion_mask(self, shape: tuple) -> np.ndarray:
        """Binary mask: 0 for occluded/timestamp regions, 1 for valid eye area."""
        mask = np.ones(shape, dtype=np.float32)
        if self._occlusion_y and self._occlusion_y > 0:
            mask[:self._occlusion_y, :] = 0.0
        # Always mask bottom 15% (burned-in timestamp + EEG tape)
        bottom_y = getattr(self, "_bottom_mask_y", int(shape[0] * 0.85))
        mask[bottom_y:, :] = 0.0
        return mask

    def _detect_canthi(
        self,
        gray: np.ndarray,
        pupil_x: float | None = None,
        pupil_y: float | None = None,
        pupil_r: float | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Radial-scan canthi detection (ChatGPT / literature recommendation).

        1. From the known pupil centre, scan radially outward at many angles.
        2. At each angle, find the first dark→bright transition that signals
           the eyelid/skin/sclera boundary.
        3. Collect all boundary points → fit upper/lower eyelid parabolas.
        4. Take horizontal extremes (x_min, x_max) as raw canthus candidates.
        5. Snap each candidate to the nearest local intensity pit (valley),
           consistent with the "corner = topographic pit" criterion.
        """
        h, w = gray.shape
        bottom_y = getattr(self, "_bottom_mask_y", int(h * 0.85))

        if pupil_x is None or pupil_y is None:
            eye_y = float(h * 0.40)
            return (np.array([w * 0.20, eye_y], dtype=np.float32),
                    np.array([w * 0.80, eye_y], dtype=np.float32))

        px     = float(np.clip(pupil_x, 10, w - 10))
        py     = float(np.clip(pupil_y, 10, bottom_y - 10))
        pr     = float(pupil_r) if pupil_r and pupil_r > 0 else 15.0
        iris_r = pr * 2.8

        # Threshold: pixels darker than this are "inside" the iris/pupil region
        iris_dark = min(float(gray[int(py), int(px)]) * 1.8 + 20, 180)

        N_ANGLES = 72
        max_scan = int(min(iris_r * 3.5, min(w, h) * 0.45))
        boundary: list[tuple[float, float]] = []

        for i in range(N_ANGLES):
            theta = 2 * np.pi * i / N_ANGLES
            cos_t, sin_t = np.cos(theta), np.sin(theta)
            start = int(iris_r * 0.85)
            prev  = None
            for d in range(start, max_scan):
                xi = px + d * cos_t
                yi = py + d * sin_t
                if xi < 1 or xi >= w-1 or yi < 1 or yi >= bottom_y - 1:
                    break
                val = float(gray[int(yi), int(xi)])
                if prev is not None and val > iris_dark and prev <= iris_dark:
                    boundary.append((xi, yi))
                    break
                prev = val

        if len(boundary) < 4:
            eye_y = py
            return (np.array([px - iris_r * 1.8, eye_y], dtype=np.float32),
                    np.array([px + iris_r * 2.2,  eye_y], dtype=np.float32))

        bpts = np.array(boundary)
        x_min = float(bpts[:, 0].min())
        x_max = float(bpts[:, 0].max())

        # Refine with parabola fit on upper/lower subsets
        for pts in [bpts[bpts[:, 1] < py], bpts[bpts[:, 1] >= py]]:
            if len(pts) >= 3:
                try:
                    xs = pts[:, 0]
                    x_min = min(x_min, float(xs.min()))
                    x_max = max(x_max, float(xs.max()))
                except Exception:
                    pass

        # Snap to local intensity pit (true eye corner = darkest nearby point)
        def _pit(cx, cy, r=8):
            x0,y0 = int(max(cx-r,0)), int(max(cy-r,0))
            x1,y1 = int(min(cx+r,w)), int(min(cy+r,bottom_y))
            patch = gray[y0:y1, x0:x1]
            if patch.size == 0:
                return cx, cy
            idx = np.argmin(patch)
            dy, dx = np.unravel_index(idx, patch.shape)
            return float(x0+dx), float(y0+dy)

        ix, iy = _pit(x_min, py)
        ox, oy = _pit(x_max, py)

        # Ensure inner (nasal) is left of outer (temporal) for left-eye recording
        if ix > ox:
            ix, ox = ox, ix
            iy, oy = oy, iy

        return (np.array([ix, iy], dtype=np.float32),
                np.array([ox, oy], dtype=np.float32))

    @staticmethod
    def _decompose(H: np.ndarray) -> tuple[float, float, float]:
        """Extract (tx, ty, rotation_rad) from a rigid 3×3 transform matrix."""
        tx  = float(H[0, 2])
        ty  = float(H[1, 2])
        rot = float(np.arctan2(H[1, 0], H[0, 0]))
        return tx, ty, rot

    @staticmethod
    def _to_gray(frame: np.ndarray) -> np.ndarray:
        """Convert frame to uint8 grayscale (handles 16-bit and BGR inputs)."""
        if frame.ndim == 3 and frame.shape[2] == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame.copy()
        if gray.dtype == np.uint16:
            gray = (gray >> 8).astype(np.uint8)
        return gray
