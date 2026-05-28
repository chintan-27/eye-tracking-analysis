"""
video/output.py

CombinedVideoWriter: writes the combined analysis video.

Normal mode — each frame is the HSV motion map with overlays:
  - Green circle  — tracked pupil boundary
  - Yellow dots   — inner and outer canthi anchor points
  - Top-left HUD  — blink state label + frame number
  - Red outline   — added by optical_flow.py during Closed blink frames

Side-by-side mode (--side-by-side) — original raw frame on the left,
processed output on the right. Both panels are the same size.
A white divider line separates them. Labels "INPUT" / "OUTPUT" identify each side.

Output: MP4 via cv2.VideoWriter (codec: mp4v).
"""

from __future__ import annotations

import cv2
import numpy as np

from video.pupil import PupilResult

_STATE_LABELS = {0: "OPEN", 1: "CLOSING", 2: "CLOSED", 3: "OPENING"}
_STATE_COLORS = {
    0: (0, 200, 0),     # green
    1: (0, 165, 255),   # orange
    2: (0, 0, 200),     # red
    3: (255, 165, 0),   # blue
}


class CombinedVideoWriter:
    """
    Parameters
    ----------
    path : str
        Output file path.
    fps : float
        Frame rate for the output video.
    width, height : int
        Dimensions of ONE panel in pixels.
        In side-by-side mode the output video is 2×width wide.
    side_by_side : bool
        If True, write [raw input | processed output] panels per frame.
    """

    def __init__(
        self,
        path: str,
        fps: float,
        width: int,
        height: int,
        side_by_side: bool = False,
    ) -> None:
        self._width       = width
        self._height      = height
        self._side_by_side = side_by_side
        self._frame_idx   = 0

        out_width = width * 2 if side_by_side else width
        fourcc    = cv2.VideoWriter_fourcc(*"mp4v")
        self._writer = cv2.VideoWriter(path, fourcc, fps, (out_width, height))
        if not self._writer.isOpened():
            raise RuntimeError(f"Failed to open VideoWriter at {path!r}")

    def write_frame(
        self,
        hsv_bgr: np.ndarray,
        pupil: PupilResult | None,
        canthi: list[tuple[float, float]],
        blink_state: int,
        raw_frame: np.ndarray | None = None,
    ) -> None:
        """
        Composite one output frame and write it.

        Parameters
        ----------
        hsv_bgr : np.ndarray
            BGR uint8 HSV motion map.
        pupil : PupilResult | None
        canthi : list of (x, y) canthus points.
        blink_state : int  (0–3)
        raw_frame : np.ndarray | None
            Original input frame (grayscale or BGR). Required in side-by-side mode.
        """
        processed = self._build_processed(hsv_bgr, pupil, canthi, blink_state)

        if self._side_by_side:
            left = self._build_raw_panel(raw_frame)
            # White 1-pixel divider
            divider = np.full((self._height, 1, 3), 220, dtype=np.uint8)
            combined = np.concatenate([left, divider, processed[:, :self._width - 1]], axis=1)
            self._writer.write(combined)
        else:
            self._writer.write(processed)

        self._frame_idx += 1

    # ------------------------------------------------------------------
    # Internal panel builders
    # ------------------------------------------------------------------

    def _build_processed(
        self,
        hsv_bgr: np.ndarray,
        pupil: PupilResult | None,
        canthi: list,
        blink_state: int,
    ) -> np.ndarray:
        frame = hsv_bgr.copy()
        if frame.dtype != np.uint8:
            frame = np.clip(frame, 0, 255).astype(np.uint8)
        if frame.ndim == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        if frame.shape[:2] != (self._height, self._width):
            frame = cv2.resize(frame, (self._width, self._height))

        # Pupil circle
        if pupil is not None and pupil.valid and pupil.r > 0:
            cv2.circle(frame,
                       (int(round(pupil.x)), int(round(pupil.y))),
                       int(round(pupil.r)), (0, 255, 0), 2)
            cv2.circle(frame,
                       (int(round(pupil.x)), int(round(pupil.y))),
                       2, (0, 255, 0), -1)
            if pupil.cr_x >= 0:
                cv2.circle(frame,
                           (int(round(pupil.cr_x)), int(round(pupil.cr_y))),
                           3, (0, 255, 255), -1)

        # Canthi dots
        for pt in canthi:
            if pt is not None:
                cv2.circle(frame, (int(round(pt[0])), int(round(pt[1]))),
                           4, (0, 255, 255), -1)

        # HUD
        label = _STATE_LABELS.get(blink_state, "?")
        color = _STATE_COLORS.get(blink_state, (200, 200, 200))
        cv2.putText(frame, f"{label} #{self._frame_idx}",
                    (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)

        if self._side_by_side:
            cv2.putText(frame, "OUTPUT",
                        (4, self._height - 6), cv2.FONT_HERSHEY_SIMPLEX,
                        0.4, (180, 180, 180), 1, cv2.LINE_AA)
        return frame

    def _build_raw_panel(self, raw_frame: np.ndarray | None) -> np.ndarray:
        """Convert raw input frame to a labelled BGR panel."""
        if raw_frame is None:
            panel = np.zeros((self._height, self._width, 3), dtype=np.uint8)
        else:
            f = raw_frame.copy()
            if f.dtype != np.uint8:
                f = np.clip(f, 0, 255).astype(np.uint8)
            if f.ndim == 2:
                f = cv2.cvtColor(f, cv2.COLOR_GRAY2BGR)
            if f.shape[:2] != (self._height, self._width):
                f = cv2.resize(f, (self._width, self._height))
            panel = f

        cv2.putText(panel, f"INPUT #{self._frame_idx}",
                    (4, 16), cv2.FONT_HERSHEY_SIMPLEX,
                    0.45, (200, 200, 200), 1, cv2.LINE_AA)
        cv2.putText(panel, "INPUT",
                    (4, self._height - 6), cv2.FONT_HERSHEY_SIMPLEX,
                    0.4, (180, 180, 180), 1, cv2.LINE_AA)
        return panel

    def close(self) -> None:
        self._writer.release()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
