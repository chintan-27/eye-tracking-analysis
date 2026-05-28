"""
web/routers/video.py

Phantom high-speed video endpoints:
  GET /api/video/{rec_id}/info           — recording metadata
  GET /api/video/{rec_id}/frame?n={n}    — JPEG bytes of frame n
  GET /api/video/{rec_id}/eeg_at_frame   — EEG + blinks synced to a video frame
"""

from __future__ import annotations

import functools
from collections import OrderedDict
import threading
from pathlib import Path

import cv2
import numpy as np
import pyarrow.parquet as pq

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from db.database import get_db
from db.models import PhantomRecording, Trial

router = APIRouter(prefix="/api/video", tags=["video"])

# VideoCapture cache — one handle per video path.
# IMPORTANT: VideoCapture is NOT thread-safe. The blink atlas loads many frames
# concurrently (one request per card). Protect every seek+read with a per-path lock.
_MAX_CAP = 5
_cap_cache: OrderedDict[str, cv2.VideoCapture] = OrderedDict()
_cap_locks: dict[str, threading.Lock] = {}


def _get_cap(video_path: str) -> tuple[cv2.VideoCapture, threading.Lock]:
    """Return (cap, lock) for video_path. Creates cap and lock on first call."""
    if video_path not in _cap_locks:
        _cap_locks[video_path] = threading.Lock()
    if video_path in _cap_cache:
        _cap_cache.move_to_end(video_path)
        return _cap_cache[video_path], _cap_locks[video_path]
    if len(_cap_cache) >= _MAX_CAP:
        old_path, old_cap = _cap_cache.popitem(last=False)
        old_cap.release()
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise HTTPException(500, f"Cannot open video: {video_path}")
    _cap_cache[video_path] = cap
    return cap, _cap_locks[video_path]


def _get_recording(rec_id: str) -> PhantomRecording:
    S = get_db()
    with S() as db:
        rec = db.get(PhantomRecording, rec_id)
    if not rec:
        raise HTTPException(404, f"Phantom recording {rec_id!r} not found")
    if not rec.video_path or not Path(rec.video_path).exists():
        raise HTTPException(404, f"Video file not found for {rec_id}")
    return rec


def _video_brightness_at_frame(video_path: str, frame: int) -> float:
    """Return mean central brightness at a single frame. Used for blink validation."""
    cap, lock = _get_cap(video_path)
    with lock:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
        ok, img = cap.read()
    if not ok:
        return 0.0
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    h, w = gray.shape
    return float(gray[h//4:3*h//4, w//4:3*w//4].astype(np.float32).mean())


@functools.lru_cache(maxsize=16)
def _load_phan_index(eeg_path: str) -> tuple[np.ndarray, np.ndarray]:
    """
    Load and cache the phan_frame → EEG timestamp index for a recording.
    Only keeps rows where phan_frame >= 0 (~50K rows instead of 368K).
    Called once per recording; subsequent frame requests use the cache.
    """
    table = pq.read_table(eeg_path, columns=["timestamp_s", "phan_frame"])
    pf = table["phan_frame"].to_numpy(zero_copy_only=False).astype(np.int32)
    ts = table["timestamp_s"].to_numpy(zero_copy_only=False).astype(np.float64)
    valid = pf >= 0
    return pf[valid], ts[valid]


@router.get("/{rec_id}/info")
def video_info(rec_id: str):
    """Return video metadata with actual fps computed from phan_frame timing."""
    rec = _get_recording(rec_id)
    nominal_fps = float(rec.fps or 167)
    n_frames    = int(rec.n_frames or 0)

    # Compute actual fps and video time reference from phan_frame index
    eeg_path = Path("dataserver/eeg") / f"{rec_id}.parquet"
    actual_fps   = nominal_fps
    video_start_frame = 0
    eeg_at_start = 0.0
    if eeg_path.exists():
        try:
            pf_arr, ts_arr = _load_phan_index(str(eeg_path))
            if len(pf_arr) > 100:
                # Use first and last 10% of frames for a robust fps estimate
                n = len(pf_arr)
                i0, i1 = int(n * 0.05), int(n * 0.95)
                delta_frames = float(pf_arr[i1] - pf_arr[i0])
                delta_t      = float(ts_arr[i1]  - ts_arr[i0])
                if delta_t > 0 and delta_frames > 0:
                    actual_fps = delta_frames / delta_t
                video_start_frame = int(pf_arr[0])
                eeg_at_start      = float(ts_arr[0])
        except Exception:
            pass

    duration_s = (n_frames - video_start_frame) / actual_fps if actual_fps > 0 else 0

    return {
        "rec_id":            rec_id,
        "fps":               round(actual_fps, 3),
        "nominal_fps":       nominal_fps,
        "n_frames":          n_frames,
        "duration_s":        round(duration_s, 3),
        "width":             rec.image_width,
        "height":            rec.image_height,
        "video_start_frame": video_start_frame,   # first frame number with EEG coverage
        "eeg_at_start":      round(eeg_at_start, 4),  # EEG session time at frame video_start_frame
    }


@router.get("/{rec_id}/frame")
def video_frame(rec_id: str, n: int = 0):
    """Return JPEG bytes for video frame n."""
    rec = _get_recording(rec_id)
    n_frames = int(rec.n_frames or 0)
    n = max(0, min(n, n_frames - 1))

    cap, lock = _get_cap(str(rec.video_path))
    with lock:
        cap.set(cv2.CAP_PROP_POS_FRAMES, n)
        ok, frame = cap.read()
    if not ok:
        raise HTTPException(500, f"Could not read frame {n}")

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    ok2, buf = cv2.imencode(".jpg", gray, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok2:
        raise HTTPException(500, "JPEG encoding failed")
    return Response(content=buf.tobytes(), media_type="image/jpeg")


@router.get("/{rec_id}/eeg_at_frame")
def video_eeg_at_frame(rec_id: str, n: int = 0, window_s: float = 4.0):
    """
    Return EEG + blinks centred on video frame n.
    Uses cached phan_frame index — no full parquet re-read per request.
    Returns 3 regional averages plus blink onset times.
    Also returns trial context if this frame falls within a trial.
    """
    eeg_path = Path("dataserver/eeg") / f"{rec_id}.parquet"
    if not eeg_path.exists():
        raise HTTPException(404, f"No EEG parquet for {rec_id}")

    # Fast cached lookup: find EEG timestamp for this video frame
    pf_arr, ts_arr = _load_phan_index(str(eeg_path))
    if len(pf_arr) == 0:
        raise HTTPException(404, "No phan_frame data in EEG parquet")

    diffs = np.abs(pf_arr - n)
    best_idx = int(np.argmin(diffs))
    if diffs[best_idx] > 500:
        raise HTTPException(404, f"No EEG match near frame {n}")

    t_center = float(ts_arr[best_idx])
    # Trailing window: show the past window_s with a 0.5s lookahead.
    # Current frame at ~88% from left — like a clinical EEG monitor.
    t_start  = max(0.0, t_center - window_s)
    t_end    = t_center + 0.5

    # True video-relative time: offset from first valid phan_frame entry.
    # The actual Phantom fps differs from the DB value (~152 vs 167), so
    # frame/fps is inaccurate. Using phan_frame→EEG time mapping is exact.
    eeg_at_frame_zero = float(ts_arr[0])   # EEG session time when video frame 0 was recorded
    video_t_s = t_center - eeg_at_frame_zero   # seconds into the video recording

    # Display channels: FP1 first (blink channel — large spikes during blinks per paper),
    # then standard midline channels front→back
    DISPLAY_CHS = ["FP1", "FZ", "CZ", "CPZ", "OZ"]

    table = pq.read_table(
        eeg_path,
        columns=["timestamp_s", "blink"] + DISPLAY_CHS,
        filters=[("timestamp_s", ">=", t_start), ("timestamp_s", "<=", t_end)],
    )

    if len(table) == 0:
        raise HTTPException(404, "No EEG data in window")

    n_rows = len(table)
    target = 400
    idx = np.round(np.linspace(0, n_rows - 1, min(n_rows, target))).astype(int)
    times = table["timestamp_s"].to_numpy(zero_copy_only=False)[idx].tolist()

    # Blink onset times within the window
    blink_col = table["blink"].to_numpy(zero_copy_only=False).astype(np.int8)
    ts_col    = table["timestamp_s"].to_numpy(zero_copy_only=False)
    blink_times = ts_col[blink_col > 0].tolist()

    # Raw μV per channel — no z-scoring, proper units
    regions_out = []
    for ch in DISPLAY_CHS:
        arr = np.array(table[ch].to_numpy(zero_copy_only=False), dtype=np.float32)[idx]
        regions_out.append({"name": ch, "y": [round(float(v), 3) for v in arr]})

    # Trial context: which trial does this frame fall in?
    parts = rec_id.rsplit("_", 1)
    trial_ctx = None
    if len(parts) == 2:
        session_id, paradigm = parts[0], parts[1]
        S = get_db()
        with S() as db:
            trials = db.query(Trial).filter(
                Trial.session_id == session_id,
                Trial.paradigm == paradigm,
            ).all()
        for tr in trials:
            pf_s = tr.phan_frame_start or 0
            pf_e = tr.phan_frame_end or 0
            if pf_s <= n <= pf_e:
                trial_ctx = {
                    "trial_number": tr.trial_number,
                    "cue": tr.cue or "",
                    "missed": bool(tr.missed),
                }
                break

    # The pre-computed `blink` column marks the RECOVERY phase of the blink waveform.
    # Measured: FP1 peak (peak artifact = eye fully closed) is 0.91s BEFORE the blink
    # column fires. Shift bands to align with the FP1 peak / actual eyelid closure.
    BLINK_LAG_S = 0.91
    combined_blinks = sorted(set(round(b - BLINK_LAG_S, 4) for b in blink_times))

    return {
        "frame":        n,
        "t_center_s":   round(t_center, 4),
        "video_t_s":    round(video_t_s, 4),
        "t_start_s":    round(t_start, 4),
        "t_end_s":      round(t_end, 4),
        "times":        [round(float(t), 4) for t in times],
        "regions":      regions_out,
        "blink_times":  combined_blinks,
        "trial":        trial_ctx,
    }


# ── /blinks ───────────────────────────────────────────────────────────────────

@functools.lru_cache(maxsize=16)
def _load_blink_state_index(vf_path: str) -> tuple[np.ndarray, np.ndarray]:
    """
    Load frame_number and blink_state from video_features parquet. Cached.
    blink_state: 0=Open, 1=Closing, 2=Closed, 3=Opening
    Returns (frame_numbers, blink_states) arrays.
    """
    table = pq.read_table(vf_path, columns=["frame_number", "blink_state"])
    return (
        table["frame_number"].to_numpy(zero_copy_only=False).astype(np.int32),
        table["blink_state"].to_numpy(zero_copy_only=False).astype(np.int8),
    )


def _find_blink_from_features(vf_path: str, peak_frame: int,
                               fps: float, window_s: float = 1.5) -> dict | None:
    """
    Find the complete blink event (onset/closed/offset) using blink_state from video_features.

    blink_state: 0=Open, 1=Closing, 2=Closed, 3=Opening
    A blink event = a contiguous run of states 1→2→3 near the EEG peak.

    Returns dict with onset_frame, closed_frame, offset_frame, or None if no blink found.
    """
    frames, states = _load_blink_state_index(vf_path)
    search_half = int(window_s * fps)
    f_lo = peak_frame - search_half
    f_hi = peak_frame + search_half

    # Find frames in search window where eye is actively blinking (state 1, 2, or 3)
    mask_window = (frames >= f_lo) & (frames <= f_hi)
    mask_blink  = mask_window & (states >= 1) & (states <= 3)

    blink_frames = frames[mask_blink]
    blink_states = states[mask_blink]
    if len(blink_frames) == 0:
        return None

    # Find the closed (state=2) frames — the core of the blink
    closed_mask   = blink_states == 2
    closed_frames = blink_frames[closed_mask]
    if len(closed_frames) == 0:
        return None

    closed_mid    = int(np.median(closed_frames))   # middle of the closed run

    # Onset = first state≥1 frame just before the closed run
    onset_mask    = blink_frames < closed_frames[0]
    onset_frame   = int(blink_frames[onset_mask][-1]) if onset_mask.any() else int(closed_frames[0])

    # Offset = last state≤3 frame just after the closed run
    offset_mask   = blink_frames > closed_frames[-1]
    offset_frame  = int(blink_frames[offset_mask][0])  if offset_mask.any() else int(closed_frames[-1])

    return {
        "onset_frame":  onset_frame,
        "closed_frame": closed_mid,
        "offset_frame": offset_frame,
    }


def _find_closed_eye_frame_from_video(video_path: str, peak_frame: int, fps: float,
                                       n_frames_total: int, window_s: float = 1.4) -> int:
    """
    Fallback: scan video frames and find the one with highest central brightness
    (closed eyelid covers dark pupil → centre gets brighter).
    """
    search_half = int(window_s * fps)
    f_start = max(0, peak_frame - search_half)
    f_end   = min(n_frames_total - 1, peak_frame + search_half)

    best_frame = peak_frame
    best_score = -1.0

    cap, lock = _get_cap(video_path)
    with lock:
        for f in range(f_start, f_end + 1, 2):
            cap.set(cv2.CAP_PROP_POS_FRAMES, f)
            ok, frame = cap.read()
            if not ok:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
            h, w = gray.shape
            cy0, cy1 = int(h * 0.3), int(h * 0.7)
            cx0, cx1 = int(w * 0.3), int(w * 0.7)
            score = float(gray[cy0:cy1, cx0:cx1].astype(np.float32).mean())
            if score > best_score:
                best_score = score
                best_frame = f

    return best_frame


@functools.lru_cache(maxsize=16)
def _load_all_blinks(eeg_path: str, rec_id: str) -> list[dict]:
    """
    Load all blink peaks for a recording, enriched with phan_frame and trial context.
    Cached — expensive first load, instant thereafter.
    """
    table = pq.read_table(eeg_path, columns=["timestamp_s", "blink", "phan_frame", "FP1"])
    ts  = table["timestamp_s"].to_numpy(zero_copy_only=False).astype(np.float64)
    bl  = table["blink"].to_numpy(zero_copy_only=False).astype(np.int8)
    pf  = table["phan_frame"].to_numpy(zero_copy_only=False).astype(np.int32)
    fp1 = table["FP1"].to_numpy(zero_copy_only=False).astype(np.float32)

    blink_idx = np.where(bl > 0)[0]

    # Get phan_frame index for video time lookup
    valid = pf >= 0
    pf_valid = pf[valid]
    ts_valid = ts[valid]
    eeg_at_start = float(ts_valid[0]) if len(ts_valid) > 0 else 0.0

    # Load trials for context
    parts = rec_id.rsplit("_", 1)
    trial_map = {}  # phan_frame_start → trial info
    if len(parts) == 2:
        session_id, paradigm = parts[0], parts[1]
        S = get_db()
        with S() as db:
            trials = db.query(Trial).filter(
                Trial.session_id == session_id,
                Trial.paradigm == paradigm,
            ).all()
        for tr in trials:
            if tr.phan_frame_start and tr.phan_frame_end:
                trial_map[(tr.phan_frame_start, tr.phan_frame_end)] = {
                    "trial_number": tr.trial_number,
                    "cue": tr.cue or "",
                    "missed": bool(tr.missed),
                }

    # Get video path for closed-eye frame detection
    try:
        rec = _get_recording(rec_id)
        video_path   = str(rec.video_path)
        actual_fps   = float(rec.fps or 167)
        n_vid_frames = int(rec.n_frames or 0)
        # Refine fps using phan_frame timing (more accurate than DB value)
        if len(pf_valid) > 100:
            n = len(pf_valid)
            i0, i1 = int(n * .1), int(n * .9)
            actual_fps = float(pf_valid[i1] - pf_valid[i0]) / float(ts_valid[i1] - ts_valid[i0])
        has_video = True
    except Exception:
        has_video = False
        video_path = ""
        actual_fps = 150.0
        n_vid_frames = 0

    blinks = []
    for i, idx in enumerate(blink_idx):
        t_peak   = float(ts[idx])
        frame    = int(pf[idx])
        in_video = frame >= 0 and has_video

        # Video time
        video_t = None
        if in_video:
            video_t = round(t_peak - eeg_at_start, 4)

        # Trial context
        trial_ctx = None
        if in_video:
            for (pf_s, pf_e), tinfo in trial_map.items():
                if pf_s <= frame <= pf_e:
                    trial_ctx = tinfo
                    break

        # FP1 amplitude at peak (subtract median baseline from ±500ms window)
        w0 = max(0, idx - 500)
        w1 = min(len(fp1), idx + 500)
        fp1_peak = round(float(fp1[idx] - np.median(fp1[w0:w1])), 2)

        # Find exact closed-eye frame.
        # Priority 1: use blink_state from video_features (exact, fast, no scan needed).
        # Priority 2: brightness scan over video frames (slow fallback, ~10s first load).
        closed_frame  = frame
        is_real_blink = not in_video
        if in_video and n_vid_frames > 0:
            try:
                vf_path = Path("dataserver/video_features") / f"{rec_id}.parquet"
                if vf_path.exists():
                    # Fast path: use blink_state from video_features — instant, exact
                    vf_frames, _ = _load_blink_state_index(str(vf_path))
                    frame_covered = len(vf_frames) > 0 and int(vf_frames.min()) <= frame <= int(vf_frames.max())
                    if frame_covered:
                        blink_event = _find_blink_from_features(str(vf_path), frame, actual_fps, window_s=1.5)
                        if blink_event is not None:
                            closed_frame  = blink_event["closed_frame"]
                            is_real_blink = True
                        else:
                            is_real_blink = False
                    else:
                        # Frame outside video_features coverage — fall through to brightness scan
                        vf_path = None  # trigger slow path below
                if not vf_path or not vf_path.exists():
                    # Slow path: pixel brightness scan
                    closed_frame = _find_closed_eye_frame_from_video(
                        video_path, frame, actual_fps, n_vid_frames, window_s=1.4
                    )
                    br_closed = _video_brightness_at_frame(video_path, closed_frame)
                    br_before = _video_brightness_at_frame(video_path, max(0, closed_frame - int(actual_fps * 0.5)))
                    br_after  = _video_brightness_at_frame(video_path, min(n_vid_frames - 1, closed_frame + int(actual_fps * 0.5)))
                    is_real_blink = (br_closed - (br_before + br_after) / 2) >= 2.0
            except Exception:
                closed_frame  = frame
                is_real_blink = False

        # Only keep in-video blinks confirmed by brightness scan.
        # Out-of-video events (phan_frame=-1) are EEG-only artifacts with no visual ground truth.
        if not in_video:
            continue
        if not is_real_blink:
            continue

        blinks.append({
            "id":            i,
            "t_peak_s":      round(t_peak, 4),
            "phan_frame":    frame,
            "closed_frame":  closed_frame,
            "in_video":      in_video,
            "video_t_s":     video_t,
            "fp1_peak_uv":   fp1_peak,
            "trial":         trial_ctx,
            "sync_quality":  "exact" if in_video else "eeg_only",
        })

    return blinks


@router.get("/{rec_id}/blinks")
def video_blinks(rec_id: str):
    """Return all blink events for a recording, enriched with video frame and trial context."""
    eeg_path = Path("dataserver/eeg") / f"{rec_id}.parquet"
    if not eeg_path.exists():
        raise HTTPException(404, f"No EEG parquet for {rec_id}")

    blinks = _load_all_blinks(str(eeg_path), rec_id)

    # Check if video features (aperture) are available
    vf_path = Path("dataserver/video_features") / f"{rec_id}.parquet"
    aperture_available = vf_path.exists()

    return {
        "rec_id":             rec_id,
        "n_blinks":           len(blinks),
        "n_in_video":         sum(1 for b in blinks if b["in_video"]),
        "aperture_available": aperture_available,
        "blinks":             blinks,
    }


@router.get("/{rec_id}/blinks/{blink_id}/detail")
def video_blink_detail(rec_id: str, blink_id: int):
    """
    Return full detail for one blink: EEG window (FP1-centred), surrounding video
    frame numbers, and aperture curve if video_features are available.
    """
    eeg_path = Path("dataserver/eeg") / f"{rec_id}.parquet"
    if not eeg_path.exists():
        raise HTTPException(404, f"No EEG parquet for {rec_id}")

    blinks = _load_all_blinks(str(eeg_path), rec_id)
    if blink_id < 0 or blink_id >= len(blinks):
        raise HTTPException(404, f"Blink {blink_id} not found (total: {len(blinks)})")

    blink = blinks[blink_id]
    t_peak = blink["t_peak_s"]

    # EEG window: −600ms to +600ms around peak
    window_s = 1.2
    t_start = max(0.0, t_peak - window_s / 2)
    t_end   = t_peak + window_s / 2

    eeg_chs = ["FP1", "FZ", "CZ", "CPZ", "OZ"]
    table = pq.read_table(
        eeg_path,
        columns=["timestamp_s"] + eeg_chs,
        filters=[("timestamp_s", ">=", t_start), ("timestamp_s", "<=", t_end)],
    )
    n = len(table)
    target = 300
    idx = np.round(np.linspace(0, n - 1, min(n, target))).astype(int)
    times = table["timestamp_s"].to_numpy(zero_copy_only=False)[idx].tolist()

    eeg_channels = []
    for ch in eeg_chs:
        arr = np.array(table[ch].to_numpy(zero_copy_only=False), dtype=np.float32)[idx]
        arr = arr - float(np.median(arr))   # demean
        eeg_channels.append({"name": ch, "y": [round(float(v), 3) for v in arr]})

    # Surrounding video frames: 15 frames spanning −300ms to +500ms around peak
    video_frames = []
    # Use closed_frame (video-detected closure) as the filmstrip centre; fall back to EEG peak
    frame_at_peak = blink.get("closed_frame", blink["phan_frame"])
    if frame_at_peak < 0:
        frame_at_peak = blink["phan_frame"]
    if frame_at_peak >= 0:
        rec = _get_recording(rec_id)
        fps = float(rec.fps or 167)
        frames_before = int(0.3 * fps)   # 300ms before
        frames_after  = int(0.5 * fps)   # 500ms after
        n_frames = int(rec.n_frames or 0)
        step = max(1, (frames_before + frames_after) // 15)
        f = frame_at_peak - frames_before
        while f <= frame_at_peak + frames_after and len(video_frames) < 16:
            video_frames.append(max(0, min(n_frames - 1, f)))
            f += step

    # Aperture from video_features if available
    aperture = None
    vf_path = Path("dataserver/video_features") / f"{rec_id}.parquet"
    if vf_path.exists() and frame_at_peak >= 0:
        frames_before = int(0.3 * 167)
        frames_after  = int(0.5 * 167)
        try:
            vf = pq.read_table(
                vf_path,
                columns=["frame_number", "timestamp_eeg_ms", "aperture_mm", "blink_state"],
                filters=[
                    ("frame_number", ">=", frame_at_peak - frames_before),
                    ("frame_number", "<=", frame_at_peak + frames_after),
                ],
            )
            if len(vf) > 0:
                vf_fn  = vf["frame_number"].to_numpy(zero_copy_only=False).astype(np.int32)
                vf_ap  = vf["aperture_mm"].to_numpy(zero_copy_only=False).astype(np.float32)
                vf_bs  = vf["blink_state"].to_numpy(zero_copy_only=False)
                aperture = {
                    "frames":       vf_fn.tolist(),
                    "aperture_mm":  [round(float(v), 3) for v in vf_ap],
                    "blink_state":  vf_bs.tolist(),
                }
        except Exception:
            pass

    return {
        "blink":         blink,
        "t_start_s":     round(t_start, 4),
        "t_end_s":       round(t_end, 4),
        "times":         [round(float(t), 4) for t in times],
        "eeg_channels":  eeg_channels,
        "video_frames":  video_frames,
        "aperture":      aperture,
    }
