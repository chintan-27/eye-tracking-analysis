"""
web/routers/pipeline.py

Interactive preview endpoints for configuring and visualizing the Phantom video
pipeline without running a full recording.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
from uuid import uuid4

import cv2
import numpy as np
import pyarrow.parquet as pq
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from db.database import get_db
from db.models import PhantomRecording, Subject, TobiiRecording
from video.config import (
    GAMMA_MAX_SANE_MM_PER_PX,
    INNER_CANTHI_MM,
    PHANTOM_GAMMA_FALLBACK_MM_PER_PX,
)
from video.pipeline_state import PipelineOptions, VideoPipelineState

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])
PREVIEW_DIR      = Path("output/pipeline_preview")
VIDEO_RUNS_DIR   = Path("dataserver/video_runs")
OUTPUT_RUNS_DIR  = Path("output/video_runs")
DEFAULT_RUN_ID   = "full_dataset_v1"
DEFAULT_COMBINATION = "stable_match_farneback"
_JOBS: dict[str, dict] = {}

_VALID_VIDEO_NAMES = {"stages_grid", "processed_overlay"}


def _find_video(rec_id: str, run_id: str | None, combination: str, name: str) -> tuple[Path, str]:
    """Locate a pipeline output MP4 in output/video_runs/; return (path, actual_run_id)."""
    if name not in _VALID_VIDEO_NAMES:
        raise HTTPException(400, f"Unknown video name {name!r}. Valid: {sorted(_VALID_VIDEO_NAMES)}")
    candidates = [run_id] if run_id else []
    if OUTPUT_RUNS_DIR.exists():
        candidates += [
            d.name for d in sorted(
                OUTPUT_RUNS_DIR.iterdir(),
                key=lambda x: x.stat().st_mtime,
                reverse=True,
            )
            if d.is_dir()
        ]
    for rid in candidates:
        p = OUTPUT_RUNS_DIR / rid / rec_id / combination / f"{name}.mp4"
        if p.exists():
            return p, rid
    raise HTTPException(404, f"No pipeline video '{name}' for {rec_id!r} — run the HPG job first")


# ── Pre-computed pipeline result endpoints ────────────────────────────────────

def _find_parquet(rec_id: str, run_id: str | None, combination: str, filename: str) -> tuple[Path, str]:
    """Locate a pipeline result parquet; return (path, actual_run_id)."""
    candidates = []
    if run_id:
        candidates = [run_id]
    else:
        candidates = [DEFAULT_RUN_ID]
        if VIDEO_RUNS_DIR.exists():
            candidates += [
                d.name for d in sorted(
                    VIDEO_RUNS_DIR.iterdir(),
                    key=lambda x: x.stat().st_mtime,
                    reverse=True,
                )
                if d.is_dir()
            ]
    for rid in candidates:
        p = VIDEO_RUNS_DIR / rid / rec_id / combination / filename
        if p.exists():
            return p, rid
    raise HTTPException(404, f"No pipeline results for {rec_id!r} — run the HPG job first")


@router.get("/runs")
def pipeline_list_runs():
    """List available pipeline run IDs with recording counts."""
    if not VIDEO_RUNS_DIR.exists():
        return []
    runs = []
    for d in sorted(VIDEO_RUNS_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if not d.is_dir():
            continue
        count = sum(1 for _ in d.rglob("per_frame.parquet"))
        runs.append({"run_id": d.name, "n_recordings": count, "mtime": int(d.stat().st_mtime)})
    return runs


@router.get("/{rec_id}/timeseries")
def pipeline_timeseries(
    rec_id: str,
    run_id: str | None = None,
    combination: str = DEFAULT_COMBINATION,
    downsample: int = 3000,
):
    """Return a downsampled per-frame time series for visualization."""
    pf_path, actual_run = _find_parquet(rec_id, run_id, combination, "per_frame.parquet")

    all_cols = [
        "timestamp_eeg_ms", "aperture_mm", "aperture_norm", "blink_state",
        "pupil_diameter_mm", "flow_mag_mean_eyelid", "flow_mag_mean_pupil",
        "transform_tx", "transform_ty", "p_cr_velocity_mms",
    ]
    # Only read columns that exist in this parquet (older runs may lack p_cr_velocity_mms)
    schema_names = set(pq.read_schema(pf_path).names)
    cols = [c for c in all_cols if c in schema_names]
    table = pq.read_table(pf_path, columns=cols)
    n = len(table)
    stride = max(1, n // downsample)
    idx = np.arange(0, n, stride)

    def _col(name: str):
        if name not in schema_names:
            return None
        arr = table[name].to_numpy(zero_copy_only=False)
        sampled = arr[idx]
        if sampled.dtype.kind == "f":
            return [None if not np.isfinite(v) else round(float(v), 4) for v in sampled]
        return [int(v) for v in sampled]

    ts_ms = table["timestamp_eeg_ms"].to_numpy(zero_copy_only=False)[idx].astype(np.float64)
    t0 = float(ts_ms[0]) if len(ts_ms) else 0.0
    t_s = [round((float(t) - t0) / 1000.0, 3) for t in ts_ms]

    return {
        "rec_id": rec_id,
        "run_id": actual_run,
        "combination": combination,
        "n_frames": n,
        "n_points": len(idx),
        "t_s": t_s,
        "aperture_mm": _col("aperture_mm"),
        "aperture_norm": _col("aperture_norm"),
        "blink_state": _col("blink_state"),
        "pupil_diameter_mm": _col("pupil_diameter_mm"),
        "flow_mag_mean_eyelid": _col("flow_mag_mean_eyelid"),
        "flow_mag_mean_pupil": _col("flow_mag_mean_pupil"),
        "transform_tx": _col("transform_tx"),
        "transform_ty": _col("transform_ty"),
        "p_cr_velocity_mms": _col("p_cr_velocity_mms"),
    }


@router.get("/{rec_id}/biomarkers")
def pipeline_biomarkers(
    rec_id: str,
    run_id: str | None = None,
    combination: str = DEFAULT_COMBINATION,
):
    """Return the aggregated biomarker row for this recording."""
    bm_path, actual_run = _find_parquet(rec_id, run_id, combination, "biomarkers.parquet")
    table = pq.read_table(bm_path)
    row = table.to_pydict()
    result = {k: (v[0] if v else None) for k, v in row.items()}
    result["_run_id"] = actual_run
    return result


@router.get("/recordings")
def pipeline_recordings():
    """Return Phantom recordings available for interactive preview."""
    S = get_db()
    with S() as db:
        rows = (
            db.query(PhantomRecording)
            .order_by(PhantomRecording.subject_id, PhantomRecording.session_id, PhantomRecording.paradigm)
            .all()
        )

    out = []
    for rec in rows:
        path = Path(rec.video_path) if rec.video_path else None
        out.append({
            "rec_id": rec.id,
            "subject_id": rec.subject_id,
            "session_id": rec.session_id,
            "paradigm": rec.paradigm,
            "fps": float(rec.fps or 0),
            "n_frames": int(rec.n_frames or 0),
            "width": rec.image_width,
            "height": rec.image_height,
            "available": bool(path and path.exists()),
        })
    return out


@router.get("/{rec_id}/preview")
def pipeline_preview(
    rec_id: str,
    frame: int = 0,
    normalize: str = "match",
    stabilize: bool = True,
    post_norm: bool = True,
    flow: str = "farneback",
    eye_mask: bool = True,
    overlay: bool = True,
):
    """Return a labeled JPEG grid for one configured pipeline preview frame."""
    rec, subject = _get_recording(rec_id)
    video_path = Path(rec.video_path)
    if not video_path.exists():
        raise HTTPException(404, f"Video file not found for {rec_id}")

    fps = float(rec.fps or 167.0)
    n_frames = int(rec.n_frames or 0)
    frame = max(0, min(frame, max(n_frames - 1, 0)))
    gamma = _gamma_for(subject)

    raw_ref = _read_frame(video_path, 0)
    state = _new_pipeline_state(subject, gamma, fps, normalize, stabilize, post_norm, flow, eye_mask, overlay)
    state.process(raw_ref)
    warmup_start = max(0, frame - int(round(fps * 0.35)))
    for warm_frame in range(warmup_start, frame, max(1, int(round(fps / 30.0)))):
        if warm_frame > 0:
            state.process(_read_frame(video_path, warm_frame))
    result = state.process(_read_frame(video_path, frame))
    grid = _compose_preview_frame(
        result.raw,
        result.normalized,
        result.processed,
        result.flow_bgr,
        rec_id,
        frame,
        result.pupil,
        result.aperture,
    )

    ok, buf = cv2.imencode(".jpg", grid, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise HTTPException(500, "JPEG encoding failed")
    return Response(content=buf.tobytes(), media_type="image/jpeg")


@router.get("/{rec_id}/gaze_at_frame")
def pipeline_gaze_at_frame(rec_id: str, frame: int = 0):
    """
    Return Tobii gaze/pupil sample synchronized to a Phantom video frame.

    Sync method:
      1. Convert local video frame index to Phantom frame number using
         phantom_recordings.first_frame.
      2. Interpolate Tobii RecordingTimestamp from EEG rows where both
         phan_frame and recording_timestamp are present.
      3. Return the nearest Tobii sample.
    """
    rec, _ = _get_recording(rec_id)
    phan_frame = int(frame + (rec.first_frame or 0))

    eeg_path = Path("dataserver/eeg") / f"{rec_id}.parquet"
    tobii_path = Path("dataserver/tobii") / f"{rec_id}.parquet"
    if not eeg_path.exists() or not tobii_path.exists():
        raise HTTPException(404, "EEG or Tobii parquet missing for this recording")

    anchors = pq.read_table(eeg_path, columns=["timestamp_s", "phan_frame", "recording_timestamp"])
    pf = anchors["phan_frame"].to_numpy(zero_copy_only=False).astype(np.int32)
    ts = anchors["timestamp_s"].to_numpy(zero_copy_only=False).astype(np.float64)
    rt = anchors["recording_timestamp"].to_numpy(zero_copy_only=False).astype(np.int64)
    valid = (pf >= 0) & (rt >= 0)
    if int(valid.sum()) < 2:
        raise HTTPException(404, "Not enough EEG↔Tobii sync anchors")

    pf_valid = pf[valid]
    ts_valid = ts[valid]
    rt_valid = rt[valid]
    order = np.argsort(pf_valid)
    pf_valid = pf_valid[order]
    ts_valid = ts_valid[order]
    rt_valid = rt_valid[order]

    if phan_frame < int(pf_valid[0]) or phan_frame > int(pf_valid[-1]):
        sync_quality = "outside_anchor_range"
    else:
        sync_quality = "interpolated"

    target_tobii_ms = float(np.interp(phan_frame, pf_valid, rt_valid))
    target_eeg_s = float(np.interp(phan_frame, pf_valid, ts_valid))

    sample = _nearest_tobii_sample(tobii_path, target_tobii_ms)
    display_w, display_h = _display_size(rec_id, tobii_path)

    return {
        "rec_id": rec_id,
        "video_frame": frame,
        "phan_frame": phan_frame,
        "eeg_t_s": round(target_eeg_s, 4),
        "tobii_t_ms": round(target_tobii_ms, 1),
        "sync_quality": sync_quality,
        "anchor_count": int(valid.sum()),
        "display_w": display_w,
        "display_h": display_h,
        **sample,
    }


@router.post("/{rec_id}/process_clip")
def pipeline_process_clip(
    rec_id: str,
    start_frame: int = 0,
    seconds: float = 5.0,
    output_fps: float = 30.0,
    normalize: str = "match",
    stabilize: bool = True,
    post_norm: bool = True,
    flow: str = "farneback",
    eye_mask: bool = True,
    overlay: bool = True,
    job_id: str | None = None,
):
    """
    Process a short continuous preview clip with stateful pipeline objects and
    return an MP4 URL. This avoids frame-by-frame JPEG flicker.
    """
    job_id = job_id or uuid4().hex
    _JOBS[job_id] = {"status": "running", "done": 0, "total": 0, "url": None, "error": None}
    try:
        result = _process_clip_impl(
            rec_id, start_frame, seconds, output_fps, normalize, stabilize,
            post_norm, flow, eye_mask, overlay, job_id,
        )
        _JOBS[job_id].update(result)
        _JOBS[job_id]["status"] = "complete"
        return {"job_id": job_id, **result}
    except Exception as e:
        _JOBS[job_id]["status"] = "error"
        _JOBS[job_id]["error"] = str(e)
        raise


@router.get("/jobs/{job_id}")
def pipeline_job_status(job_id: str):
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Pipeline job not found")
    return job


def _process_clip_impl(
    rec_id: str,
    start_frame: int,
    seconds: float,
    output_fps: float,
    normalize: str,
    stabilize: bool,
    post_norm: bool,
    flow: str,
    eye_mask: bool,
    overlay: bool,
    job_id: str,
) -> dict:
    rec, subject = _get_recording(rec_id)
    video_path = Path(rec.video_path)
    if not video_path.exists():
        raise HTTPException(404, f"Video file not found for {rec_id}")

    src_fps = float(rec.fps or 167.0)
    output_fps = float(np.clip(output_fps, 1.0, 60.0))
    seconds = float(np.clip(seconds, 1.0, 30.0))
    n_frames = int(rec.n_frames or 0)
    start_frame = max(0, min(start_frame, max(n_frames - 1, 0)))
    source_stride = max(1, int(round(src_fps / output_fps)))
    n_out = max(1, int(round(seconds * output_fps)))
    source_frames = [
        min(n_frames - 1, start_frame + i * source_stride)
        for i in range(n_out)
        if start_frame + i * source_stride < n_frames
    ]
    if not source_frames:
        raise HTTPException(400, "No source frames in requested clip")
    warmup_frames = _warmup_frames(start_frame, src_fps, source_stride)
    _JOBS[job_id].update({"done": 0, "total": len(warmup_frames) + len(source_frames)})

    gamma = _gamma_for(subject)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise HTTPException(500, f"Cannot open video: {video_path}")

    try:
        state = _new_pipeline_state(subject, gamma, src_fps, normalize, stabilize, post_norm, flow, eye_mask, overlay)
        done = 0
        for warm_frame in warmup_frames:
            state.process(_read_cap_frame(cap, warm_frame))
            done += 1
            _JOBS[job_id]["done"] = done

        first_raw = _read_cap_frame(cap, source_frames[0])
        first_result = state.process(first_raw)
        done += 1
        _JOBS[job_id]["done"] = done
        first_out = _compose_preview_frame(
            first_result.raw,
            first_result.normalized,
            first_result.processed,
            first_result.flow_bgr,
            rec_id,
            source_frames[0],
            first_result.pupil,
            first_result.aperture,
        )

        PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"{rec_id}_{uuid4().hex}.mp4"
        out_path = PREVIEW_DIR / filename
        tmp_path = PREVIEW_DIR / f".{filename}.tmp.mp4"
        h, w = first_out.shape[:2]
        writer = cv2.VideoWriter(
            str(tmp_path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            output_fps,
            (w, h),
        )
        if not writer.isOpened():
            raise HTTPException(500, "Could not open preview VideoWriter")

        writer.write(first_out)
        for source_frame in source_frames[1:]:
            raw = _read_cap_frame(cap, source_frame)
            result = state.process(raw)
            out = _compose_preview_frame(
                result.raw,
                result.normalized,
                result.processed,
                result.flow_bgr,
                rec_id,
                source_frame,
                result.pupil,
                result.aperture,
            )
            writer.write(out)
            done += 1
            _JOBS[job_id]["done"] = done
        writer.release()
        out_path = _transcode_for_browser(tmp_path, out_path)
        filename = out_path.name
    finally:
        cap.release()

    return {
        "url": f"/api/pipeline/preview_video/{filename}",
        "start_frame": source_frames[0],
        "end_frame": source_frames[-1],
        "source_stride": source_stride,
        "source_fps": round(src_fps, 3),
        "output_fps": output_fps,
        "frames": len(source_frames),
        "warmup_frames": len(warmup_frames),
        "seconds": round(len(source_frames) / output_fps, 3),
    }


@router.get("/preview_video/{filename}")
def pipeline_preview_video(filename: str):
    path = PREVIEW_DIR / Path(filename).name
    if not path.exists():
        raise HTTPException(404, "Preview video not found")
    media_type = "video/webm" if path.suffix == ".webm" else "video/mp4"
    return FileResponse(path, media_type=media_type)


def _get_recording(rec_id: str) -> tuple[PhantomRecording, Subject]:
    S = get_db()
    with S() as db:
        rec = db.get(PhantomRecording, rec_id)
        if rec is None:
            raise HTTPException(404, f"Phantom recording {rec_id!r} not found")
        subject = db.get(Subject, rec.subject_id)
        if subject is None:
            raise HTTPException(404, f"Subject {rec.subject_id!r} not found")
    return rec, subject


def _nearest_tobii_sample(tobii_path: Path, target_ms: float) -> dict:
    window = 80.0
    table = pq.read_table(
        tobii_path,
        columns=[
            "timestamp_ms", "event_type", "gaze_x", "gaze_y", "fixation_x", "fixation_y",
            "pupil_left", "pupil_right", "validity_left", "validity_right",
        ],
        filters=[
            ("timestamp_ms", ">=", target_ms - window),
            ("timestamp_ms", "<=", target_ms + window),
        ],
    )
    if len(table) == 0:
        raise HTTPException(404, "No Tobii sample near synchronized timestamp")

    times = table["timestamp_ms"].to_numpy(zero_copy_only=False).astype(np.float64)
    idx = int(np.argmin(np.abs(times - target_ms)))

    def val(name: str):
        item = table[name][idx].as_py()
        if isinstance(item, float) and np.isnan(item):
            return None
        return item

    vl = int(val("validity_left") or 0)
    vr = int(val("validity_right") or 0)
    gx = val("gaze_x")
    gy = val("gaze_y")
    return {
        "sample_tobii_ms": int(val("timestamp_ms")),
        "sync_error_ms": round(float(times[idx] - target_ms), 2),
        "event_type": str(val("event_type") or ""),
        "gaze_x": None if gx is None else round(float(gx), 2),
        "gaze_y": None if gy is None else round(float(gy), 2),
        "fixation_x": None if val("fixation_x") is None else round(float(val("fixation_x")), 2),
        "fixation_y": None if val("fixation_y") is None else round(float(val("fixation_y")), 2),
        "pupil_left": None if val("pupil_left") is None else round(float(val("pupil_left")), 3),
        "pupil_right": None if val("pupil_right") is None else round(float(val("pupil_right")), 3),
        "validity_left": vl,
        "validity_right": vr,
        "valid": vl == 0 and vr == 0 and gx is not None and gy is not None,
    }


def _display_size(rec_id: str, tobii_path: Path) -> tuple[float, float]:
    S = get_db()
    with S() as db:
        tobii = db.get(TobiiRecording, rec_id)
        resolution = tobii.resolution if tobii else None
    if resolution and "x" in resolution.lower():
        parts = resolution.lower().replace(" ", "").split("x", 1)
        try:
            return float(parts[0]), float(parts[1])
        except ValueError:
            pass

    table = pq.read_table(tobii_path, columns=["gaze_x", "gaze_y", "validity_left", "validity_right"])
    vl = table["validity_left"].to_numpy(zero_copy_only=False).astype(np.int8)
    vr = table["validity_right"].to_numpy(zero_copy_only=False).astype(np.int8)
    gx = table["gaze_x"].to_numpy(zero_copy_only=False).astype(np.float32)
    gy = table["gaze_y"].to_numpy(zero_copy_only=False).astype(np.float32)
    valid = (vl == 0) & (vr == 0) & ~np.isnan(gx) & ~np.isnan(gy)
    if int(valid.sum()) > 10:
        return float(np.nanpercentile(gx[valid], 99)), float(np.nanpercentile(gy[valid], 99))
    return 1920.0, 1080.0


def _gamma_for(subject: Subject) -> float:
    inner_canthi = float(subject.inner_canthi_px or 0.0)
    gamma = INNER_CANTHI_MM / inner_canthi if inner_canthi > 0 else PHANTOM_GAMMA_FALLBACK_MM_PER_PX
    if gamma > GAMMA_MAX_SANE_MM_PER_PX:
        return PHANTOM_GAMMA_FALLBACK_MM_PER_PX
    return gamma


def _read_frame(video_path: Path, frame: int) -> np.ndarray:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise HTTPException(500, f"Cannot open video: {video_path}")
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
    ok, img = cap.read()
    cap.release()
    if not ok:
        raise HTTPException(500, f"Could not read frame {frame}")
    return img


def _read_cap_frame(cap: cv2.VideoCapture, frame: int) -> np.ndarray:
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
    ok, img = cap.read()
    if not ok:
        raise HTTPException(500, f"Could not read frame {frame}")
    return img


def _transcode_for_browser(src: Path, dst: Path) -> Path:
    """
    OpenCV's mp4v output is not reliably playable in browsers. Prefer H.264
    with OpenH264 when available; fall back to WebM/VP8 if this ffmpeg build
    lacks an H.264 encoder.
    """
    attempts = [
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-an",
            "-c:v", "libopenh264", "-b:v", "4M", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(dst),
        ],
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-an",
            "-c:v", "libvpx", "-b:v", "4M", "-pix_fmt", "yuv420p",
            str(dst.with_suffix(".webm")),
        ],
    ]
    for cmd in attempts:
        try:
            subprocess.run(cmd, check=True)
            src.unlink(missing_ok=True)
            return Path(cmd[-1])
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    src.replace(dst)
    return dst


def _new_pipeline_state(
    subject: Subject,
    gamma: float,
    fps: float,
    normalize: str,
    stabilize: bool,
    post_norm: bool,
    flow: str,
    eye_mask: bool,
    overlay: bool,
) -> VideoPipelineState:
    return VideoPipelineState(
        gamma=gamma,
        fps=fps,
        inner_canthi_px=float(subject.inner_canthi_px or 60.0),
        options=PipelineOptions(
            normalize=normalize,
            stabilize=stabilize,
            post_norm=post_norm,
            flow=flow,
            eye_mask=eye_mask,
            overlay=overlay,
        ),
    )


def _warmup_frames(start_frame: int, fps: float, stride: int) -> list[int]:
    warmup_start = max(0, start_frame - int(round(fps * 0.75)))
    if warmup_start >= start_frame:
        return []
    return list(range(warmup_start, start_frame, max(1, stride)))


def _compose_preview_frame(
    raw: np.ndarray,
    norm: np.ndarray,
    processed: np.ndarray,
    flow_img: np.ndarray | None,
    rec_id: str,
    frame: int,
    pupil,
    aperture,
) -> np.ndarray:
    panels = [
        _label(_crop_timestamp(_to_bgr(raw)), "RAW"),
        _label(_crop_timestamp(_to_bgr(norm)), "NORMALIZED"),
        _label(_crop_timestamp(_to_bgr(processed)), "STABILIZED"),
    ]
    flow_panel = flow_img if flow_img is not None else np.zeros_like(_to_bgr(processed))
    panels.append(_label(_crop_timestamp(flow_panel), "FLOW"))
    grid = _grid(panels)
    hud = f"{rec_id}  frame={frame}  pupil_d={pupil.diameter_mm:.3f}mm  aperture={aperture.aperture_mm:.3f}mm"
    cv2.putText(grid, hud, (8, grid.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (230, 230, 230), 1, cv2.LINE_AA)
    return grid


def _crop_timestamp(frame: np.ndarray) -> np.ndarray:
    """Remove the burned-in Phantom timestamp strip before making preview grids."""
    h = frame.shape[0]
    return frame[:int(h * 0.80), :]


def _to_bgr(frame: np.ndarray) -> np.ndarray:
    if frame.dtype != np.uint8:
        frame = np.clip(frame, 0, 255).astype(np.uint8)
    if frame.ndim == 2:
        return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    return frame.copy()


def _label(frame: np.ndarray, label: str) -> np.ndarray:
    out = _to_bgr(frame)
    cv2.rectangle(out, (0, 0), (out.shape[1], 22), (0, 0, 0), -1)
    cv2.putText(out, label, (7, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (230, 230, 230), 1, cv2.LINE_AA)
    return out


def _grid(panels: list[np.ndarray]) -> np.ndarray:
    h = max(p.shape[0] for p in panels)
    w = max(p.shape[1] for p in panels)
    resized = [cv2.resize(p, (w, h)) if p.shape[:2] != (h, w) else p for p in panels]
    if len(resized) <= 2:
        return np.concatenate(resized, axis=1)
    top = np.concatenate(resized[:2], axis=1)
    bottom_panels = resized[2:]
    if len(bottom_panels) == 1:
        bottom_panels.append(np.zeros_like(resized[0]))
    bottom = np.concatenate(bottom_panels[:2], axis=1)
    return np.concatenate([top, bottom], axis=0)


# ── Pre-computed output video endpoints ──────────────────────────────────────

@router.get("/{rec_id}/videos")
def pipeline_list_videos(
    rec_id:      str,
    run_id:      str | None = None,
    combination: str = DEFAULT_COMBINATION,
):
    """List available pre-computed MP4 videos for a recording."""
    result = []
    for name in sorted(_VALID_VIDEO_NAMES):
        try:
            path, actual_run = _find_video(rec_id, run_id, combination, name)
            stat = path.stat()
            result.append({
                "name":     name,
                "run_id":   actual_run,
                "url":      f"/api/pipeline/{rec_id}/video/{name}",
                "size_mb":  round(stat.st_size / 1_048_576, 2),
                "mtime":    int(stat.st_mtime),
            })
        except HTTPException:
            pass
    return result


@router.get("/{rec_id}/video/{video_name}")
def pipeline_serve_video(
    rec_id:      str,
    video_name:  str,
    run_id:      str | None = None,
    combination: str = DEFAULT_COMBINATION,
):
    """
    Stream a pre-computed pipeline MP4.
    Supports HTTP range requests so the browser video element can seek.

    video_name: 'stages_grid' or 'processed_overlay'
    """
    path, _ = _find_video(rec_id, run_id, combination, video_name)
    return FileResponse(
        path=str(path),
        media_type="video/mp4",
        filename=f"{rec_id}_{video_name}.mp4",
    )
