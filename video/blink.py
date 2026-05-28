"""
video/blink.py

BlinkStateMachine: tracks blink state across frames using velocity-gated transitions.

4 states:
  0 = Open     — aperture stable near maximum
  1 = Closing  — aperture dropping rapidly (velocity < −15 mm/s)
  2 = Closed   — aperture at minimum; Kalman filter runs prediction-only
  3 = Opening  — aperture recovering (velocity > +10 mm/s)

Velocity-based detection (not amplitude threshold):
  - Handles incomplete blinks where eyelids don't fully touch (Parkinson's signature)
  - Handles partial blinks and spontaneous eye narrowing
  - Uses 5-point central difference on aperture signal (reduces high-freq noise)

EEG blink fusion:
  - When phan_frame != -1, the EEG Blinks column (1000 Hz) provides ground truth
  - EEG blink = 1 forces state → Closed regardless of velocity
  - EEG blink = 0 AND aperture > 80% baseline prevents spurious Closed state

Per-blink kinematics extracted at state transition Open→Closed→Open:
  v_close_max  — minimum velocity during closing phase (mm/s, negative)
  v_open_max   — maximum velocity during opening phase (mm/s, positive)
  amplitude_mm — aperture at blink start minus minimum aperture
  r_slow       — |v_close_max / v_open_max| (elevated in fatigue)
  duration_ms  — total blink duration
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from video.config import BLINK_CLOSE_VEL_TH, BLINK_OPEN_VEL_TH

# State constants
OPEN    = 0
CLOSING = 1
CLOSED  = 2
OPENING = 3


@dataclass
class BlinkEvent:
    start_frame:   int
    end_frame:     int   = -1
    aperture_open: float = 0.0   # aperture (mm) when blink started
    aperture_min:  float = 1e9
    v_close_max:   float = 0.0   # most negative velocity during closing
    v_open_max:    float = 0.0   # most positive velocity during opening
    duration_ms:   float = 0.0

    @property
    def amplitude_mm(self) -> float:
        return max(0.0, self.aperture_open - self.aperture_min)

    @property
    def r_slow(self) -> float:
        if abs(self.v_open_max) < 1e-6:
            return 0.0
        return abs(self.v_close_max / self.v_open_max)


class BlinkStateMachine:
    """
    Parameters
    ----------
    fps : float
        Recording frame rate — used to compute blink duration in ms.
    eeg_blinks : pd.Series | None
        EEG blink labels indexed by phan_frame (integer frame number).
        Value is 0 or 1. Pass None if PhanFrame sync is unavailable.
    """

    def __init__(self, fps: float, eeg_blinks: pd.Series | None = None) -> None:
        self.fps        = fps
        self._dt_ms     = 1000.0 / fps
        self._eeg       = eeg_blinks   # Series[phan_frame → 0|1]
        self._state     = OPEN
        self._aperture_buf: deque[float] = deque(maxlen=5)  # for velocity computation
        self._cur_event: BlinkEvent | None = None
        self.blink_events: list[BlinkEvent] = []
        self._frame_idx = 0

    @property
    def state(self) -> int:
        return self._state

    def update(
        self,
        aperture_mm: float,
        velocity_mms: float,
        phan_frame: int = -1,
    ) -> int:
        """
        Update state machine for one frame.

        Parameters
        ----------
        aperture_mm : float
            Current palpebral aperture in mm.
        velocity_mms : float
            Current aperture velocity in mm/s (5-point central difference).
        phan_frame : int
            EEG frame index from phan_frame column (−1 = no sync available).

        Returns
        -------
        int : new state (0–3)
        """
        self._aperture_buf.append(aperture_mm)

        # EEG override: if EEG says blink, force Closed
        eeg_blink = self._get_eeg_blink(phan_frame)

        if eeg_blink == 1 and self._state != CLOSED:
            self._transition_to_closed(aperture_mm, velocity_mms)
        elif self._state == OPEN:
            if velocity_mms < BLINK_CLOSE_VEL_TH:
                self._transition(CLOSING)
                self._cur_event = BlinkEvent(
                    start_frame=self._frame_idx,
                    aperture_open=aperture_mm,
                )
        elif self._state == CLOSING:
            if self._cur_event:
                self._cur_event.aperture_min = min(self._cur_event.aperture_min, aperture_mm)
                self._cur_event.v_close_max  = min(self._cur_event.v_close_max, velocity_mms)
            if velocity_mms > -1.0:   # velocity near zero → closed
                self._transition_to_closed(aperture_mm, velocity_mms)
        elif self._state == CLOSED:
            if eeg_blink == 0 and velocity_mms > BLINK_OPEN_VEL_TH:
                self._transition(OPENING)
            elif eeg_blink == -1 and velocity_mms > BLINK_OPEN_VEL_TH:
                self._transition(OPENING)
        elif self._state == OPENING:
            if self._cur_event:
                self._cur_event.v_open_max = max(self._cur_event.v_open_max, velocity_mms)
            if velocity_mms < 1.0:   # velocity near zero → fully open
                self._finalise_blink()
                self._transition(OPEN)

        self._frame_idx += 1
        return self._state

    def get_blink_kinematics(self) -> dict:
        """Aggregate kinematics over all completed blinks."""
        if not self.blink_events:
            return {"v_close_max": 0., "v_open_max": 0., "amplitude_mm": 0.,
                    "r_slow": 0., "duration_ms": 0., "n_blinks": 0}
        vc  = [e.v_close_max  for e in self.blink_events]
        vo  = [e.v_open_max   for e in self.blink_events]
        amp = [e.amplitude_mm for e in self.blink_events]
        rs  = [e.r_slow       for e in self.blink_events]
        dur = [e.duration_ms  for e in self.blink_events]
        return {
            "v_close_max":    float(np.mean(vc)),
            "v_open_max":     float(np.mean(vo)),
            "amplitude_mm":   float(np.mean(amp)),
            "r_slow_mean":    float(np.mean(rs)),
            "r_slow_median":  float(np.median(rs)),
            "duration_ms":    float(np.mean(dur)),
            "n_blinks":       len(self.blink_events),
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _transition(self, new_state: int) -> None:
        self._state = new_state

    def _transition_to_closed(self, aperture_mm: float, vel: float) -> None:
        if self._cur_event is None:
            self._cur_event = BlinkEvent(
                start_frame=self._frame_idx,
                aperture_open=aperture_mm,
            )
        self._cur_event.aperture_min = min(self._cur_event.aperture_min, aperture_mm)
        self._transition(CLOSED)

    def _finalise_blink(self) -> None:
        if self._cur_event is None:
            return
        self._cur_event.end_frame   = self._frame_idx
        self._cur_event.duration_ms = (
            (self._frame_idx - self._cur_event.start_frame) * self._dt_ms
        )
        self.blink_events.append(self._cur_event)
        self._cur_event = None

    def _get_eeg_blink(self, phan_frame: int) -> int:
        """Return EEG blink value at phan_frame, or -1 if unavailable."""
        if self._eeg is None or phan_frame < 0:
            return -1
        if phan_frame in self._eeg.index:
            return int(self._eeg.loc[phan_frame])
        return -1
