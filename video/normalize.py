"""
video/normalize.py

Four approaches to removing illumination flicker from Phantom video frames.

Step 1   — EqualizeHist    : maps every frame to a uniform histogram
Step 1.1 — HistMatch       : maps every frame to match the first frame's histogram
Step 1.2 — Retinex         : divides by large Gaussian blur (removes local illumination)
Step 1.3 — TemporalDeflicker: per-pixel EMA of illumination, divides it out each frame

Use preview.py --step=1 to compare all four side by side against the original.
"""

from __future__ import annotations
import cv2
import numpy as np


# ---------------------------------------------------------------------------
# Shared utility
# ---------------------------------------------------------------------------

def to_gray8(frame: np.ndarray) -> np.ndarray:
    if frame.dtype == np.uint16:
        frame = (frame >> 8).astype(np.uint8)
    if frame.ndim == 3:
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return frame.copy()


# ---------------------------------------------------------------------------
# Step 1 — EqualizeHist
# ---------------------------------------------------------------------------

class EqualizeNorm:
    """
    Per-frame histogram equalisation.
    Flattens every frame to a uniform histogram → means become identical.
    Downside: different tone-mapping curve per frame → texture flicker remains.
    """
    def apply(self, frame: np.ndarray) -> np.ndarray:
        gray = to_gray8(frame)
        return cv2.equalizeHist(gray)

    def reset(self): pass


# ---------------------------------------------------------------------------
# Step 1.1 — Histogram Matching
# ---------------------------------------------------------------------------

class HistMatchNorm:
    """
    Matches every frame's histogram to the first frame seen.
    All frames get the same tone-mapping curve → no flicker from curve changes.
    Much better than equalizeHist because the reference is a natural image.
    """

    def __init__(self) -> None:
        self._reference: np.ndarray | None = None   # cumulative distribution of ref

    def apply(self, frame: np.ndarray) -> np.ndarray:
        gray = to_gray8(frame)

        if self._reference is None:
            self._reference = self._cdf(gray)
            return gray   # first frame is the reference — return as-is

        # Build CDF of current frame
        src_cdf = self._cdf(gray)

        # Build look-up table: for each intensity in source, find the matching
        # intensity in the reference that has the closest CDF value
        lut = np.zeros(256, dtype=np.uint8)
        j = 0
        for i in range(256):
            while j < 255 and self._reference[j] < src_cdf[i]:
                j += 1
            lut[i] = j

        return lut[gray]

    def reset(self):
        self._reference = None

    @staticmethod
    def _cdf(gray: np.ndarray) -> np.ndarray:
        hist, _ = np.histogram(gray.flatten(), bins=256, range=(0, 256))
        cdf = hist.cumsum().astype(np.float64)
        cdf /= cdf[-1]   # normalise to [0, 1]
        return cdf


# ---------------------------------------------------------------------------
# Step 1.2 — Retinex
# ---------------------------------------------------------------------------

class RetinexNorm:
    """
    Single-scale Retinex: divides each frame by its own large-scale Gaussian
    blur (the estimated 'illumination' component). What remains is the
    'reflectance' — the texture, independent of lighting.

    Works in log domain: log(I) = log(R) + log(L)
    Subtracting log(L_estimate) gives log(R), which is illumination-invariant.
    """

    def __init__(self, sigma: float = 100.0, target_mean: float = 127.0) -> None:
        self.sigma       = sigma
        self.target_mean = target_mean

    def apply(self, frame: np.ndarray) -> np.ndarray:
        gray = to_gray8(frame).astype(np.float32) + 1.0   # avoid log(0)

        # Estimate illumination via large Gaussian blur
        illum = cv2.GaussianBlur(gray, (0, 0), self.sigma)

        # Subtract in log domain = divide in linear domain
        retinex = np.log(gray) - np.log(illum)

        # Normalise to 0–255 with target mean
        retinex -= retinex.mean()
        std = retinex.std()
        if std > 0:
            retinex = retinex / std * 40   # spread ≈ 40 DN std
        retinex += self.target_mean
        return np.clip(retinex, 0, 255).astype(np.uint8)

    def reset(self): pass


# ---------------------------------------------------------------------------
# Step 1.3 — Temporal Deflicker
# ---------------------------------------------------------------------------

class TemporalDeflicker:
    """
    Per-pixel exponential moving average of frame values estimates the slow
    illumination component. Divides it out each frame so only fast local
    motion remains.

    alpha controls the EMA speed:
      Low alpha (0.02) → slow EMA → removes oscillations faster than ~50 frames
      High alpha (0.1) → faster EMA → follows slower oscillations too
    """

    def __init__(self, alpha: float = 0.03, target_mean: float = 110.0) -> None:
        self.alpha        = alpha
        self.target_mean  = target_mean
        self._ema: np.ndarray | None = None

    def apply(self, frame: np.ndarray) -> np.ndarray:
        gray = to_gray8(frame).astype(np.float32)

        if self._ema is None:
            self._ema = gray.copy()
            # First frame: return normalised to target mean
            mean = gray.mean()
            if mean > 0:
                return np.clip(gray * (self.target_mean / mean), 0, 255).astype(np.uint8)
            return gray.astype(np.uint8)

        # Update per-pixel illumination estimate
        self._ema = (1 - self.alpha) * self._ema + self.alpha * gray

        # Divide current frame by the illumination estimate
        normed = gray / (self._ema + 1.0) * self.target_mean
        return np.clip(normed, 0, 255).astype(np.uint8)

    def reset(self):
        self._ema = None


# ---------------------------------------------------------------------------
# Step 1.4 — Hybrid: Retinex (skin) + EqualizeHist (eye region)
# ---------------------------------------------------------------------------

class HybridNorm:
    """
    Retinex removes skin flickering. EqualizeHist preserves the natural eye look.
    Blend them using a soft elliptical mask centred on the eye region:
      - Inside the eye ellipse  → EqualizeHist
      - Outside                 → Retinex
      - 30px gradient border    → smooth blend between both
    """

    # Approximate eye centre in the 320×288 Phantom frame
    _EYE_CX = 140
    _EYE_CY = 120
    _EYE_RX = 95    # horizontal ellipse radius
    _EYE_RY = 50    # vertical ellipse radius
    _FADE   = 30    # gradient width in pixels

    def __init__(self, retinex_sigma: float = 60.0) -> None:
        self._retinex = RetinexNorm(sigma=retinex_sigma)
        self._equalize = EqualizeNorm()
        self._weight: np.ndarray | None = None   # pre-computed blend map

    def apply(self, frame: np.ndarray) -> np.ndarray:
        gray = to_gray8(frame)
        h, w = gray.shape

        # Pre-compute the blend weight map once (eye region = 1, skin = 0)
        if self._weight is None or self._weight.shape != (h, w):
            self._weight = self._build_weight(h, w)

        eq  = self._equalize.apply(frame).astype(np.float32)
        rtx = self._retinex.apply(frame).astype(np.float32)
        wt  = self._weight

        blended = eq * wt + rtx * (1.0 - wt)
        return np.clip(blended, 0, 255).astype(np.uint8)

    def reset(self):
        self._retinex.reset()
        self._equalize.reset()

    def _build_weight(self, h: int, w: int) -> np.ndarray:
        """
        Weight = 1 inside the eye ellipse, fades linearly to 0 over FADE pixels.
        """
        ys, xs = np.ogrid[:h, :w]
        dist = np.sqrt(((xs - self._EYE_CX) / self._EYE_RX) ** 2 +
                       ((ys - self._EYE_CY) / self._EYE_RY) ** 2)
        scale   = min(self._EYE_RX, self._EYE_RY)
        px_dist = (dist - 1.0) * scale   # negative inside, positive outside

        weight = np.where(
            px_dist <= 0,
            1.0,
            np.where(px_dist <= self._FADE,
                     1.0 - px_dist / self._FADE,
                     0.0),
        ).astype(np.float32)
        return weight


# ---------------------------------------------------------------------------
# Pipeline normalizers
# ---------------------------------------------------------------------------

class BrightnessNormalizer(HistMatchNorm):
    """
    Step 1 — applied at READ TIME before any processing.
    Histogram matching uses one stable tone curve anchored to the first frame.
    This suppresses frame-to-frame exposure flicker without the texture flashing
    introduced by per-frame equalizeHist.
    """
    pass


class PostStabNormalizer(RetinexNorm):
    """
    Step 3 — applied AFTER stabilization, BEFORE optical flow.
    Retinex: removes local skin illumination patterns that remain after
    global normalisation. Works better post-stabilization because the
    skin texture is now spatially fixed, so Retinex can cleanly estimate
    the static illumination component vs real motion.
    """

    def __init__(self, sigma: float = 100.0, target_mean: float = 127.0, alpha: float = 0.25) -> None:
        super().__init__(sigma=sigma, target_mean=target_mean)
        self.alpha = alpha
        self._ema: np.ndarray | None = None

    def apply(self, frame: np.ndarray) -> np.ndarray:
        current = super().apply(frame).astype(np.float32)
        if self._ema is None:
            self._ema = current
            return current.astype(np.uint8)
        self._ema = self.alpha * current + (1.0 - self.alpha) * self._ema
        return np.clip(self._ema, 0, 255).astype(np.uint8)

    def reset(self):
        self._ema = None
