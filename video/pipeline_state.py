"""
video/pipeline_state.py

Continuous, stateful processing wrapper for Phantom eye-video clips.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from video.landmarks import EyelidLandmarks, LandmarkResult
from video.normalize import EqualizeNorm, HistMatchNorm, HybridNorm, PostStabNormalizer, RetinexNorm, TemporalDeflicker, to_gray8
from video.optical_flow import FlowResult, RLOFMotionMap
from video.pupil import PupilResult, PupilTracker
from video.stabilize import VideoStabilizer


@dataclass
class PipelineOptions:
    normalize: str = "match"
    stabilize: bool = True
    post_norm: bool = True
    flow: str = "farneback"
    eye_mask: bool = True
    overlay: bool = True


@dataclass
class PipelineFrame:
    raw: np.ndarray
    normalized: np.ndarray
    processed: np.ndarray
    flow_bgr: np.ndarray | None
    flow: FlowResult | None
    pupil: PupilResult
    aperture: LandmarkResult
    canthi: list
    transform: dict
    qc_flag: int


class VideoPipelineState:
    def __init__(self, gamma: float, fps: float, inner_canthi_px: float, options: PipelineOptions) -> None:
        self.gamma = gamma
        self.fps = fps
        self.options = options
        self._normalizer = self._make_normalizer(options.normalize)
        self._post = PostStabNormalizer() if options.post_norm else None
        self._stabilizer = VideoStabilizer(inner_canthi_px, fps) if options.stabilize else None
        self._pupil = PupilTracker(gamma, fps)
        self._landmarks = EyelidLandmarks(gamma, fps)
        self._flow = RLOFMotionMap(gamma, fps, use_rlof=(options.flow == "rlof"))
        self._initialized = False
        self._prev_processed: np.ndarray | None = None
        self._last_pupil: tuple[float, float, float] | None = None
        self._canthi: list = []
        self._last_transform = {"tx": 0.0, "ty": 0.0, "rot": 0.0}

    def process(self, raw: np.ndarray, blink_state: int = 0) -> PipelineFrame:
        normalized = self._normalizer.apply(raw)

        if not self._initialized:
            if self._stabilizer is not None:
                self._canthi = list(self._stabilizer.initialize(normalized))
            self._initialized = True

        if self._stabilizer is not None:
            if self._last_pupil is not None:
                x, y, r = self._last_pupil
                if r > 0:
                    self._stabilizer.update_pupil(x, y, r)
            stabilized, info = self._stabilizer.process_frame(normalized, is_blink=(blink_state == 2))
            self._canthi = [info["inner_pt"], info["outer_pt"]]
            self._last_transform = {
                "tx": float(info.get("tx", 0.0)),
                "ty": float(info.get("ty", 0.0)),
                "rot": float(info.get("rot", 0.0)),
            }
            qc_flag = int(info.get("qc", 0))
        else:
            stabilized = normalized
            qc_flag = 0

        processed = self._post.apply(stabilized) if self._post is not None else stabilized

        if not self._pupil._initialized:
            self._pupil.initialize(to_gray8(processed))
        pupil = self._pupil.process_frame(to_gray8(processed), blink_state=blink_state)
        if pupil.valid and pupil.r > 0:
            self._last_pupil = (pupil.x, pupil.y, pupil.r)

        aperture = self._landmarks.measure(processed, pupil.x, pupil.y, blink_state=blink_state)

        flow_bgr = None
        flow_result = None
        if self.options.flow != "none":
            prev = self._prev_processed if self._prev_processed is not None else processed
            flow_result = self._flow.compute(prev, processed, blink_state=blink_state)
            flow_bgr = flow_result.hsv_bgr
            if self.options.eye_mask and pupil.r > 0:
                flow_bgr = self._flow.apply_eye_mask(flow_bgr, pupil.x, pupil.y, pupil.r)
            if self.options.overlay:
                self.draw_overlay(flow_bgr, pupil, self._canthi)

        self._prev_processed = processed
        return PipelineFrame(
            raw=raw,
            normalized=normalized,
            processed=processed,
            flow_bgr=flow_bgr,
            flow=flow_result,
            pupil=pupil,
            aperture=aperture,
            canthi=self._canthi,
            transform=self._last_transform,
            qc_flag=qc_flag,
        )

    @staticmethod
    def draw_overlay(frame: np.ndarray, pupil: PupilResult, canthi: list) -> None:
        if pupil.valid and pupil.r > 0:
            cv2.circle(frame, (int(round(pupil.x)), int(round(pupil.y))), int(round(pupil.r)), (0, 255, 0), 1)
            cv2.circle(frame, (int(round(pupil.x)), int(round(pupil.y))), 2, (0, 255, 0), -1)
            if pupil.cr_x >= 0:
                cv2.circle(frame, (int(round(pupil.cr_x)), int(round(pupil.cr_y))), 3, (0, 255, 255), -1)
        for pt in canthi:
            cv2.circle(frame, (int(round(pt[0])), int(round(pt[1]))), 3, (0, 255, 255), -1)

    @staticmethod
    def _make_normalizer(mode: str):
        mode = mode.lower()
        if mode == "none":
            return _NoNorm()
        if mode == "match":
            return HistMatchNorm()
        if mode == "retinex":
            return RetinexNorm()
        if mode == "hybrid":
            return HybridNorm()
        if mode == "temporal":
            return TemporalDeflicker()
        return EqualizeNorm()


class _NoNorm:
    def apply(self, frame: np.ndarray) -> np.ndarray:
        return to_gray8(frame)
