"""
video/experiments.py

Experiment runner for Phantom video pipeline combinations.

Each run writes a manifest, per-frame features, biomarkers, and optional QC
videos for one or more recordings. The frame processing itself is delegated to
VideoPipelineState so batch output and interactive preview use the same stages.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn

from db.config import DATASERVER, DB_PATH, ROOT
from db.database import get_db, load_parquet, save_parquet
from db.models import EEGRecording, PhantomRecording, Subject
from video.blink import BlinkStateMachine
from video.biomarkers import aggregate_window, cast_frame_df, extract_per_frame
from video.config import GAMMA_MAX_SANE_MM_PER_PX, INNER_CANTHI_MM, PHANTOM_GAMMA_FALLBACK_MM_PER_PX
from video.pipeline_state import PipelineOptions, VideoPipelineState

console = Console()

VIDEO_RUNS_DIR = "video_runs"
DEFAULT_COMBINATION = "stable_match_farneback"


@dataclass(frozen=True)
class PipelineCombination:
    name: str
    options: PipelineOptions
    description: str


PIPELINE_COMBINATIONS: dict[str, PipelineCombination] = {
    "stable_match_farneback": PipelineCombination(
        name="stable_match_farneback",
        options=PipelineOptions(
            normalize="match",
            stabilize=True,
            post_norm=True,
            flow="farneback",
            eye_mask=True,
            overlay=True,
        ),
        description="Default robust pipeline: histogram match, phase stabilization, post Retinex, Farneback flow.",
    ),
    "stable_hybrid_farneback": PipelineCombination(
        name="stable_hybrid_farneback",
        options=PipelineOptions(
            normalize="hybrid",
            stabilize=True,
            post_norm=True,
            flow="farneback",
            eye_mask=True,
            overlay=True,
        ),
        description="More aggressive normalization for flickery recordings.",
    ),
    "stable_match_rlof": PipelineCombination(
        name="stable_match_rlof",
        options=PipelineOptions(
            normalize="match",
            stabilize=True,
            post_norm=True,
            flow="rlof",
            eye_mask=True,
            overlay=True,
        ),
        description="RLOF variant for high-frequency boundary motion when OpenCV optflow is available.",
    ),
    "fast_noflow": PipelineCombination(
        name="fast_noflow",
        options=PipelineOptions(
            normalize="match",
            stabilize=True,
            post_norm=False,
            flow="none",
            eye_mask=False,
            overlay=False,
        ),
        description="Fast: skip optical flow and Retinex. Keeps blink kinematics, pupil, aperture, tremor.",
    ),
}


def run_experiment(
    rec_id: str,
    combination: str = DEFAULT_COMBINATION,
    run_id: str | None = None,
    max_frames: int | None = None,
    save_videos: bool = True,
    save_stage_grid: bool = True,
    save_step_videos: bool = False,
    only_missing: bool = False,
    quiet: bool = False,
) -> dict:
    combo = _get_combination(combination)
    run_id = run_id or _make_run_id(combo.name)
    run_root = DATASERVER / VIDEO_RUNS_DIR / run_id
    rec_root = run_root / rec_id / combo.name
    video_root = Path("output/video_runs") / run_id / rec_id / combo.name

    feature_rel = f"{VIDEO_RUNS_DIR}/{run_id}/{rec_id}/{combo.name}/per_frame.parquet"
    biomarker_rel = f"{VIDEO_RUNS_DIR}/{run_id}/{rec_id}/{combo.name}/biomarkers.parquet"
    manifest_path = rec_root / "manifest.json"

    if only_missing and manifest_path.exists() and (DATASERVER / feature_rel).exists() and (DATASERVER / biomarker_rel).exists():
        return {
            "rec_id": rec_id,
            "combination": combo.name,
            "run_id": run_id,
            "skipped": True,
            "manifest": str(manifest_path),
        }

    rec_root.mkdir(parents=True, exist_ok=True)
    if save_videos:
        video_root.mkdir(parents=True, exist_ok=True)

    meta = _load_recording_metadata(rec_id)
    fps = _derive_fps(meta["fps"], meta["eeg_file_path"], meta["eeg_hmac"])
    gamma = _scale_factor(meta["inner_canthi_px"])
    first_frame = int(meta["first_frame"] or 0)
    video_path = Path(meta["video_path"])

    eeg_blinks = _load_eeg_blinks(meta["eeg_file_path"], meta["eeg_hmac"])
    phan_to_eeg = _load_phan_to_eeg(meta["eeg_file_path"], meta["eeg_hmac"])

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or int(meta["width"] or 320)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or int(meta["height"] or 240)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or int(meta["n_frames"] or 0)
    if max_frames is not None:
        total_frames = min(total_frames, max_frames)

    from video.optical_flow import _HAS_CUDA
    import os
    if combo.options.flow == "farneback":
        flow_backend = "CUDA" if _HAS_CUDA else "CPU"
    else:
        flow_backend = combo.options.flow or "none"
    print(
        f"[{rec_id}] start · combo={combo.name} · frames={total_frames:,}"
        f" · fps={fps:.1f} · flow={flow_backend} · pid={os.getpid()}",
        flush=True,
    )

    state = VideoPipelineState(gamma, fps, meta["inner_canthi_px"], combo.options)
    blink_sm = BlinkStateMachine(fps, eeg_blinks)
    metric_state: dict = {}
    rows: list[dict] = []

    writers = _StageWriters(
        root=video_root,
        fps=fps,
        width=width,
        height=height,
        enabled=save_videos,
        save_stage_grid=save_stage_grid,
        save_step_videos=save_step_videos,
    )

    if not quiet:
        console.print(f"[bold]{rec_id}[/bold] · {combo.name} · {total_frames:,} frames")
    with writers:
        progress_ctx = Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=34),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
            disable=quiet,
        )
        with progress_ctx as progress:
            task = progress.add_task("processing", total=total_frames) if not quiet else None
            frame_idx = 0
            _t0 = time.monotonic()
            while frame_idx < total_frames:
                ok, raw = cap.read()
                if not ok:
                    break

                current_state = blink_sm.state
                pf = first_frame + frame_idx
                frame = state.process(raw, blink_state=current_state)
                new_state = blink_sm.update(frame.aperture.aperture_mm, frame.aperture.velocity_mms, pf)
                qc_flag = int(frame.qc_flag)
                if new_state == 2:
                    qc_flag |= 0x01

                flow_eyelid, flow_pupil = _flow_stats(frame.flow)
                micro = _compute_micro_metrics(frame.pupil, frame.aperture.aperture_mm, gamma, fps, metric_state)
                rows.append(extract_per_frame(
                    frame_number=frame_idx,
                    phan_frame=pf,
                    timestamp_eeg_ms=phan_to_eeg.get(pf, -1),
                    fps=fps,
                    aperture_mm=frame.aperture.aperture_mm,
                    aperture_delta_mm=micro["aperture_delta_mm"],
                    aperture_velocity=frame.aperture.velocity_mms,
                    aperture_norm=frame.aperture.aperture_norm,
                    blink_state=new_state,
                    pupil_x=frame.pupil.x,
                    pupil_y=frame.pupil.y,
                    pupil_radius_px=frame.pupil.r,
                    pupil_diameter_mm=frame.pupil.diameter_mm,
                    pupil_diameter_delta_mm=micro["pupil_diameter_delta_mm"],
                    pupil_diameter_velocity_mms=micro["pupil_diameter_velocity_mms"],
                    pupil_area_mm2=micro["pupil_area_mm2"],
                    pupil_area_delta_pct=micro["pupil_area_delta_pct"],
                    pupil_center_velocity_mms=micro["pupil_center_velocity_mms"],
                    cr_x=frame.pupil.cr_x,
                    cr_y=frame.pupil.cr_y,
                    p_cr_x=frame.pupil.p_cr_x,
                    p_cr_y=frame.pupil.p_cr_y,
                    p_cr_velocity_mms=micro["p_cr_velocity_mms"],
                    flow_eyelid=flow_eyelid,
                    flow_pupil=flow_pupil,
                    transform_tx=frame.transform["tx"],
                    transform_ty=frame.transform["ty"],
                    transform_rot=frame.transform["rot"],
                    qc_flag=qc_flag,
                ))
                writers.write(frame_idx, frame, new_state)
                frame_idx += 1
                if task is not None:
                    progress.advance(task)
                if quiet and frame_idx % 100 == 0 and frame_idx > 0:
                    _elapsed = time.monotonic() - _t0
                    _fps = frame_idx / _elapsed
                    _pct = 100.0 * frame_idx / total_frames
                    _eta = (total_frames - frame_idx) / _fps if _fps > 0 else 0
                    print(
                        f"  {rec_id}  {frame_idx:>7,}/{total_frames:,}"
                        f"  ({_pct:4.1f}%)  {_fps:5.1f} fps  ETA {_eta/60:.0f}min",
                        flush=True,
                    )

    cap.release()

    df = cast_frame_df(rows)
    feature_hmac = save_parquet(df, feature_rel)
    biomarkers = aggregate_window(df, blink_sm, fps)
    biomarkers.update({
        "rec_id": rec_id,
        "run_id": run_id,
        "combination": combo.name,
    })
    biomarker_hmac = save_parquet(pd.DataFrame([biomarkers]), biomarker_rel)

    manifest = {
        "run_id": run_id,
        "rec_id": rec_id,
        "combination": combo.name,
        "description": combo.description,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "pipeline_options": asdict(combo.options),
        "recording": {
            "video_path": str(video_path),
            "fps": fps,
            "nominal_fps": meta["fps"],
            "first_frame": first_frame,
            "frames_requested": total_frames,
            "frames_processed": len(df),
            "width": width,
            "height": height,
        },
        "outputs": {
            "per_frame": feature_rel,
            "per_frame_hmac": feature_hmac,
            "biomarkers": biomarker_rel,
            "biomarkers_hmac": biomarker_hmac,
            "videos": writers.outputs,
        },
        "qc": {
            "pupil_valid_pct": float((df["pupil_radius_px"] > 0).mean() * 100.0) if len(df) else 0.0,
            "blink_frames": int((df["blink_state"] == 2).sum()) if len(df) else 0,
            "track_fail_frames": int((df["qc_flag"] & 0x04).sum()) if len(df) else 0,
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if not quiet:
        console.print(f"[green]saved[/green] {feature_rel} · {biomarker_rel}")
    return manifest


def _run_experiment_kwargs(kwargs: dict) -> dict:
    """Top-level wrapper so ProcessPoolExecutor can pickle the call."""
    return run_experiment(**kwargs)


def run_many(
    rec_ids: list[str],
    combinations: list[str],
    run_id: str | None = None,
    max_frames: int | None = None,
    save_videos: bool = True,
    save_stage_grid: bool = True,
    save_step_videos: bool = False,
    only_missing: bool = False,
    workers: int = 1,
) -> list[dict]:
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor, as_completed

    resolved_run_id = run_id or _make_run_id("experiment")
    run_root = DATASERVER / VIDEO_RUNS_DIR / resolved_run_id
    _write_run_manifest(run_root, resolved_run_id)

    tasks = [
        dict(
            rec_id=r, combination=c, run_id=resolved_run_id, max_frames=max_frames,
            save_videos=save_videos, save_stage_grid=save_stage_grid,
            save_step_videos=save_step_videos, only_missing=only_missing,
            quiet=workers > 1,
        )
        for r in rec_ids for c in combinations
    ]

    if workers <= 1:
        results = []
        for kw in tasks:
            try:
                results.append(run_experiment(**kw))
            except Exception as exc:
                console.print(f"[red]failed[/red] {kw['rec_id']} · {kw['combination']}: {exc}")
                results.append({"rec_id": kw["rec_id"], "combination": kw["combination"],
                                "run_id": resolved_run_id, "error": str(exc)})
        return results

    n = len(tasks)
    console.print(f"[bold]Parallel: {workers} workers · {n} tasks[/bold]")
    results = []
    done = 0
    with ProcessPoolExecutor(max_workers=workers,
                             mp_context=multiprocessing.get_context("spawn")) as pool:
        future_map = {pool.submit(_run_experiment_kwargs, kw): kw for kw in tasks}
        for future in as_completed(future_map):
            kw = future_map[future]
            done += 1
            try:
                result = future.result()
                tag = "[dim]skipped[/dim]" if result.get("skipped") else "[green]done[/green]"
                console.print(f"[{done}/{n}] {kw['rec_id']} · {kw['combination']} {tag}")
                results.append(result)
            except Exception as exc:
                console.print(f"[{done}/{n}] [red]failed[/red] {kw['rec_id']} · {kw['combination']}: {exc}")
                results.append({"rec_id": kw["rec_id"], "combination": kw["combination"],
                                "run_id": resolved_run_id, "error": str(exc)})
    return results


class _StageWriters:
    def __init__(
        self,
        root: Path,
        fps: float,
        width: int,
        height: int,
        enabled: bool,
        save_stage_grid: bool,
        save_step_videos: bool,
    ) -> None:
        self.root = root
        self.fps = _writer_fps(fps)
        self.width = width
        self.height = height
        self.enabled = enabled
        self.save_stage_grid = save_stage_grid
        self.save_step_videos = save_step_videos
        self._writers: dict[str, cv2.VideoWriter] = {}
        self.outputs: dict[str, str] = {}

    def __enter__(self):
        if not self.enabled:
            return self
        if self.save_stage_grid:
            self._open("stages_grid", (self.width * 2, self.height * 2))
        self._open("processed_overlay", (self.width, self.height))
        if self.save_step_videos:
            for name in ("raw", "normalized", "stabilized", "flow"):
                self._open(name, (self.width, self.height))
        return self

    def __exit__(self, *_):
        for writer in self._writers.values():
            writer.release()

    def write(self, frame_idx: int, frame, blink_state: int) -> None:
        if not self.enabled:
            return
        raw = _panel(frame.raw, self.width, self.height, f"RAW #{frame_idx}")
        normalized = _panel(frame.normalized, self.width, self.height, "NORMALIZED")
        stabilized = _panel(frame.processed, self.width, self.height, "STABILIZED")
        flow = _panel(frame.flow_bgr, self.width, self.height, "FLOW")
        overlay = flow.copy()
        VideoPipelineState.draw_overlay(overlay, frame.pupil, frame.canthi)
        cv2.putText(overlay, _blink_label(blink_state), (4, self.height - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 220, 0), 1, cv2.LINE_AA)

        if "stages_grid" in self._writers:
            grid = np.vstack([np.hstack([raw, normalized]), np.hstack([stabilized, overlay])])
            self._writers["stages_grid"].write(grid)
        if "processed_overlay" in self._writers:
            self._writers["processed_overlay"].write(overlay)
        for name, panel in (("raw", raw), ("normalized", normalized), ("stabilized", stabilized), ("flow", flow)):
            if name in self._writers:
                self._writers[name].write(panel)

    def _open(self, name: str, size: tuple[int, int]) -> None:
        path = self.root / f"{name}.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(path), fourcc, self.fps, size)
        if not writer.isOpened():
            raise RuntimeError(f"Failed to open VideoWriter at {path}")
        self._writers[name] = writer
        self.outputs[name] = str(path)


def _panel(frame: np.ndarray | None, width: int, height: int, label: str) -> np.ndarray:
    if frame is None:
        out = np.zeros((height, width, 3), dtype=np.uint8)
    else:
        out = frame.copy()
        if out.dtype != np.uint8:
            out = np.clip(out, 0, 255).astype(np.uint8)
        if out.ndim == 2:
            out = cv2.cvtColor(out, cv2.COLOR_GRAY2BGR)
        if out.shape[:2] != (height, width):
            out = cv2.resize(out, (width, height), interpolation=cv2.INTER_AREA)
    cv2.putText(out, label, (4, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (220, 220, 220), 1, cv2.LINE_AA)
    return out


def _writer_fps(fps: float) -> float:
    rounded = round(float(fps))
    if rounded < 1:
        return 30.0
    return float(min(240, rounded))


def _blink_label(blink_state: int) -> str:
    return {0: "OPEN", 1: "CLOSING", 2: "CLOSED", 3: "OPENING"}.get(int(blink_state), "UNKNOWN")


def _load_recording_metadata(rec_id: str) -> dict:
    if not DB_PATH.exists():
        return _load_metadata_from_json(rec_id)

    Session = get_db()
    with Session() as db:
        rec = db.get(PhantomRecording, rec_id)
        if rec is None:
            raise ValueError(f"PhantomRecording not found: {rec_id}")
        subject = db.get(Subject, rec.subject_id)
        if subject is None:
            raise ValueError(f"Subject not found: {rec.subject_id}")
        eeg = db.get(EEGRecording, rec_id)
        return {
            "rec_id": rec_id,
            "subject_id": rec.subject_id,
            "session_id": rec.session_id,
            "paradigm": rec.paradigm,
            "video_path": rec.video_path,
            "fps": float(rec.fps or 167.0),
            "n_frames": int(rec.n_frames or 0),
            "first_frame": int(rec.first_frame or 0),
            "width": int(rec.image_width or 320),
            "height": int(rec.image_height or 240),
            "inner_canthi_px": float(subject.inner_canthi_px or 60.0),
            "eeg_file_path": eeg.file_path if eeg else None,
            "eeg_hmac": eeg.hmac if eeg else None,
        }


def _load_metadata_from_json(rec_id: str) -> dict:
    import json
    meta_path = DATASERVER / "hpg_meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"No DB and no {meta_path} — run `python -m video.export_meta` locally first")
    all_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if rec_id not in all_meta:
        raise ValueError(f"{rec_id!r} not found in hpg_meta.json")
    meta = dict(all_meta[rec_id])
    if meta.get("video_path") and not Path(meta["video_path"]).is_absolute():
        meta["video_path"] = str(ROOT / meta["video_path"])
    return meta


def _scale_factor(inner_canthi_px: float) -> float:
    gamma = INNER_CANTHI_MM / inner_canthi_px if inner_canthi_px > 0 else PHANTOM_GAMMA_FALLBACK_MM_PER_PX
    if gamma > GAMMA_MAX_SANE_MM_PER_PX:
        return PHANTOM_GAMMA_FALLBACK_MM_PER_PX
    return float(gamma)


def _load_eeg_blinks(eeg_file_path: str | None, eeg_hmac: str | None):
    if not eeg_file_path or not eeg_hmac:
        return None
    try:
        df = load_parquet(eeg_file_path, eeg_hmac, columns=["phan_frame", "blink"])
        valid = df[df["phan_frame"] >= 0]
        return valid.set_index("phan_frame")["blink"]
    except Exception as exc:
        console.print(f"[yellow]EEG blink sync unavailable:[/yellow] {exc}")
        return None


def _load_phan_to_eeg(eeg_file_path: str | None, eeg_hmac: str | None) -> dict[int, int]:
    if not eeg_file_path or not eeg_hmac:
        return {}
    try:
        df = load_parquet(eeg_file_path, eeg_hmac, columns=["phan_frame", "timestamp_s"])
        valid = df[df["phan_frame"] >= 0]
        return dict(zip(valid["phan_frame"].astype(int), (valid["timestamp_s"] * 1000).astype(int)))
    except Exception:
        return {}


def _derive_fps(nominal_fps: float, eeg_file_path: str | None, eeg_hmac: str | None) -> float:
    if not eeg_file_path or not eeg_hmac:
        return float(nominal_fps)
    try:
        df = load_parquet(eeg_file_path, eeg_hmac, columns=["phan_frame", "timestamp_s"])
        valid = df[df["phan_frame"] >= 0]
        if len(valid) > 100:
            i0, i1 = int(len(valid) * 0.05), int(len(valid) * 0.95)
            pf0, pf1 = float(valid["phan_frame"].iloc[i0]), float(valid["phan_frame"].iloc[i1])
            ts0, ts1 = float(valid["timestamp_s"].iloc[i0]), float(valid["timestamp_s"].iloc[i1])
            fps = (pf1 - pf0) / (ts1 - ts0) if ts1 > ts0 else nominal_fps
            if 10.0 <= fps <= 250.0:
                return float(fps)
    except Exception:
        pass
    return float(nominal_fps)


def _flow_stats(flow) -> tuple[dict, dict]:
    empty = {"mag_mean": 0.0, "mag_p95": 0.0, "vert_mean": 0.0}
    if flow is None:
        return empty, empty
    h, w = flow.U_phys.shape[:2]
    pupil_roi = (w // 4, h // 4, w // 2, h // 2)
    eyelid_roi = (w // 6, h // 6, 2 * w // 3, h // 3)
    return _roi_stats(flow, eyelid_roi), _roi_stats(flow, pupil_roi)


def _roi_stats(flow, roi: tuple[int, int, int, int]) -> dict:
    x, y, w, h = roi
    mag = np.sqrt(flow.U_phys[y:y + h, x:x + w] ** 2 + flow.V_phys[y:y + h, x:x + w] ** 2)
    vert = flow.V_phys[y:y + h, x:x + w]
    return {
        "mag_mean": float(mag.mean()) if mag.size else 0.0,
        "mag_p95": float(np.percentile(mag, 95)) if mag.size else 0.0,
        "vert_mean": float(vert.mean()) if vert.size else 0.0,
    }


def _compute_micro_metrics(pupil, aperture_mm: float, gamma: float, fps: float, state: dict) -> dict:
    dt = 1.0 / fps if fps > 0 else 0.0
    diameter_mm = float(pupil.diameter_mm) if pupil.r > 0 else 0.0
    area_mm2 = float(np.pi * (diameter_mm * 0.5) ** 2) if diameter_mm > 0 else 0.0
    valid = bool(pupil.valid and pupil.r > 0)
    p_cr_valid = bool(valid and pupil.cr_x >= 0 and pupil.cr_y >= 0)
    prev = state.get("prev")
    out = {
        "aperture_delta_mm": 0.0,
        "pupil_diameter_delta_mm": 0.0,
        "pupil_diameter_velocity_mms": 0.0,
        "pupil_area_mm2": area_mm2,
        "pupil_area_delta_pct": 0.0,
        "pupil_center_velocity_mms": 0.0,
        "p_cr_velocity_mms": 0.0,
    }
    if prev is not None and dt > 0:
        out["aperture_delta_mm"] = float(aperture_mm - prev["aperture_mm"])
        if valid and prev["pupil_valid"]:
            d_diam = diameter_mm - prev["diameter_mm"]
            out["pupil_diameter_delta_mm"] = float(d_diam)
            out["pupil_diameter_velocity_mms"] = float(d_diam / dt)
            if prev["area_mm2"] > 1e-9:
                out["pupil_area_delta_pct"] = float((area_mm2 - prev["area_mm2"]) / prev["area_mm2"] * 100.0)
            dx_mm = (float(pupil.x) - prev["pupil_x"]) * gamma
            dy_mm = (float(pupil.y) - prev["pupil_y"]) * gamma
            out["pupil_center_velocity_mms"] = float(np.hypot(dx_mm, dy_mm) / dt)
        if p_cr_valid and prev["p_cr_valid"]:
            dx_mm = (float(pupil.p_cr_x) - prev["p_cr_x"]) * gamma
            dy_mm = (float(pupil.p_cr_y) - prev["p_cr_y"]) * gamma
            out["p_cr_velocity_mms"] = float(np.hypot(dx_mm, dy_mm) / dt)
    state["prev"] = {
        "aperture_mm": float(aperture_mm),
        "pupil_valid": valid,
        "diameter_mm": diameter_mm,
        "area_mm2": area_mm2,
        "pupil_x": float(pupil.x),
        "pupil_y": float(pupil.y),
        "p_cr_valid": p_cr_valid,
        "p_cr_x": float(pupil.p_cr_x),
        "p_cr_y": float(pupil.p_cr_y),
    }
    return out


def _get_combination(name: str) -> PipelineCombination:
    try:
        return PIPELINE_COMBINATIONS[name]
    except KeyError as exc:
        available = ", ".join(sorted(PIPELINE_COMBINATIONS))
        raise ValueError(f"Unknown combination {name!r}. Available: {available}") from exc


def _make_run_id(label: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}_{label}"


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return None


def _write_run_manifest(run_root: Path, run_id: str) -> None:
    run_root.mkdir(parents=True, exist_ok=True)
    rows = []
    for combo in PIPELINE_COMBINATIONS.values():
        rows.append({
            "run_id": run_id,
            "combination": combo.name,
            "description": combo.description,
            **asdict(combo.options),
        })
    pd.DataFrame(rows).to_parquet(run_root / "combinations.parquet", compression="zstd", index=False)


def _all_recordings() -> list[str]:
    if not DB_PATH.exists():
        ids_path = DATASERVER / "rec_ids.txt"
        if not ids_path.exists():
            raise FileNotFoundError(f"No DB and no {ids_path} — run `python -m video.export_meta` locally first")
        return [line.strip() for line in ids_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    Session = get_db()
    with Session() as db:
        return [r.id for r in db.query(PhantomRecording).order_by(PhantomRecording.id).all()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run versioned Phantom video pipeline experiments.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--rec-id")
    target.add_argument("--all", action="store_true")
    parser.add_argument("--combination", action="append", choices=sorted(PIPELINE_COMBINATIONS), help="Can be passed multiple times.")
    parser.add_argument("--run-id")
    parser.add_argument("--max-frames", type=int)
    parser.add_argument("--only-missing", action="store_true")
    parser.add_argument("--no-videos", action="store_true")
    parser.add_argument("--no-stage-grid", action="store_true")
    parser.add_argument("--save-step-videos", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    rec_ids = _all_recordings() if args.all else [args.rec_id]
    combinations = args.combination or [DEFAULT_COMBINATION]
    results = run_many(
        rec_ids=rec_ids,
        combinations=combinations,
        run_id=args.run_id,
        max_frames=args.max_frames,
        save_videos=not args.no_videos,
        save_stage_grid=not args.no_stage_grid,
        save_step_videos=args.save_step_videos,
        only_missing=args.only_missing,
        workers=args.workers,
    )
    failed = [r for r in results if "error" in r]
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
