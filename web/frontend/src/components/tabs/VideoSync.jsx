import React, { useState, useRef, useEffect, useCallback } from 'react'
import { useStore } from '../../store'
import { useVideoInfo, useVideoEeg, useBlinks } from '../../api/hooks'
import EegChart from '../charts/EegChart'

const SPEEDS = [1, 4, 10, 30]
const EEG_INTERVAL_MS = 200   // max 5 EEG fetches/sec during playback

export default function VideoSync() {
  const { recId, video, updateVideo, setTCurrent, tFollow, updateEeg } = useStore()
  const { data: info } = useVideoInfo(recId)
  const { data: blinksData } = useBlinks(recId)
  const [speed, setSpeed] = useState(4)
  const timerRef = useRef(null)
  const lastEegFetch = useRef(0)

  // eegFrame is decoupled from video.frame:
  // - updates immediately on manual seek/step/scrub
  // - throttled to EEG_INTERVAL_MS during playback
  const [eegFrame, setEegFrame] = useState(null)

  const frame = video.frame
  const fps = info?.fps || 153
  const nFrames = info?.n_frames || 0
  const startFrame = info?.video_start_frame || 0
  const eegAtStart = info?.eeg_at_start || 0
  const videoT = (frame - startFrame) / fps
  const dur = (nFrames - startFrame) / fps

  // EEG is driven by eegFrame (throttled), never by raw frame
  const { data: eegData } = useVideoEeg(recId, eegFrame ?? startFrame)

  // Seed eegFrame as soon as info arrives so EEG starts loading immediately
  useEffect(() => {
    if (!info) return
    const sf = info.video_start_frame || 0
    updateVideo({
      fps: info.fps,
      nFrames: info.n_frames,
      startFrame: sf,
      eegAtStart: info.eeg_at_start || 0,
    })
    const cur = useStore.getState().video.frame
    const initial = cur < sf ? sf : cur
    if (cur < sf) updateVideo({ frame: initial })
    setEegFrame(initial)
    lastEegFetch.current = Date.now()
  }, [info])

  const seek = useCallback((n, immediate = false) => {
    const clamped = Math.max(startFrame, Math.min(nFrames - 1, n))
    updateVideo({ frame: clamped })
    const vt = (clamped - startFrame) / fps
    setTCurrent(vt)
    if (tFollow) {
      updateEeg({ tStart: Math.max(0, eegAtStart + vt - useStore.getState().eeg.win * 0.7) })
    }
    const now = Date.now()
    if (immediate || now - lastEegFetch.current >= EEG_INTERVAL_MS) {
      setEegFrame(clamped)
      lastEegFetch.current = now
    }
  }, [startFrame, nFrames, fps, eegAtStart, tFollow])

  const play = useCallback(() => {
    if (timerRef.current) return
    const step = Math.max(1, Math.round(speed))
    const intervalMs = Math.max(50, (1000 * step) / fps)
    timerRef.current = setInterval(() => {
      seek(useStore.getState().video.frame + step, false)
    }, intervalMs)
    updateVideo({ playing: true })
  }, [speed, fps, seek])

  const pause = useCallback(() => {
    clearInterval(timerRef.current)
    timerRef.current = null
    updateVideo({ playing: false })
    // Sync EEG to exact paused frame
    const cur = useStore.getState().video.frame
    setEegFrame(cur)
    lastEegFetch.current = Date.now()
  }, [])

  const toggle = () => video.playing ? pause() : play()
  useEffect(() => () => clearInterval(timerRef.current), [])

  // Blink positions: map closed_frame → EEG time using phan_frame index
  // This places the band exactly when the eye is closed in the video.
  const blinkFrames = blinksData?.blinks?.filter(b => b.in_video && b.closed_frame >= 0) || []

  const eegChartData = React.useMemo(() => {
    if (!eegData?.regions?.length || !eegData.times) return null
    const channels = eegData.regions.map(r => ({ name: r.name, region: r.name, y: r.y }))
    // Convert closed_frame to absolute EEG time: eegAtStart + (frame - startFrame) / fps
    const blinkTimes = blinkFrames
      .map(b => eegAtStart + (b.closed_frame - startFrame) / fps)
      .filter(t => t >= (eegData.t_start_s || 0) && t <= (eegData.t_end_s || 9999))
    return {
      times: eegData.times,
      channels,
      blink_times: blinkTimes.length ? blinkTimes : (eegData.blink_times || []),
      events: [],
    }
  }, [eegData, blinkFrames, eegAtStart, startFrame, fps])

  const trial = eegData?.trial

  return (
    <div className="card">
      <div className="card-hd">
        <div className="card-hd-l">
          <div className="card-title">Phantom Video + EEG Sync</div>
          <div className="card-sub">
            {info
              ? `${fps.toFixed(1)} fps · ${nFrames.toLocaleString()} frames · ${dur.toFixed(1)}s`
              : 'Loading…'}
          </div>
        </div>
        <div className="ctrl-row">
          <span className="ctrl-lbl">Speed:</span>
          <div className="pill-grp">
            {SPEEDS.map(s => (
              <button
                key={s}
                className={`pill ${speed === s ? 'active' : ''}`}
                onClick={() => {
                  setSpeed(s)
                  if (video.playing) { pause(); setTimeout(play, 50) }
                }}
              >
                {s}×
              </button>
            ))}
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 18, padding: '14px 18px' }}>
        {/* Video frame */}
        <div style={{ width: 380, flexShrink: 0 }}>
          <div className="video-frame-box">
            {recId && (
              <img
                key={recId}
                src={`/api/video/${recId}/frame?n=${frame}`}
                alt=""
                style={{ width: '100%' }}
              />
            )}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <span className="vm-label">FRAME</span>
              <span className="vm-val">{frame.toLocaleString()}</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <span className="vm-label">TIME</span>
              <span className="vm-val">{videoT.toFixed(3)}s</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <span className="vm-label">FPS</span>
              <span className="vm-val">{fps.toFixed(1)}</span>
            </div>
            {trial && (
              <div className={`trial-badge${trial.missed ? ' missed' : ''}`}>
                Trial {trial.trial_number} · <strong>{trial.cue}</strong>
              </div>
            )}
          </div>
        </div>

        {/* EEG panel */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 11, color: 'var(--ink-3)', marginBottom: 4 }}>
            EEG · 4s trailing window · FP1 = blink channel
            {eegData && (
              <span style={{ float: 'right', fontFamily: 'var(--mono)' }}>
                video {(eegData.video_t_s || 0).toFixed(2)}s → EEG {(eegData.t_center_s || 0).toFixed(2)}s
              </span>
            )}
          </div>
          {eegChartData
            ? <EegChart data={eegChartData} mode="stacked" height={280} cursor={eegData?.t_center_s} />
            : <div className="loading" style={{ minHeight: 280 }}><div className="spin" />Syncing EEG…</div>}
        </div>
      </div>

      {/* Controls */}
      <div className="video-controls" style={{ padding: '10px 18px' }}>
        <button className="v-btn" onClick={() => seek(frame - 1000, true)} title="−1000">⏮</button>
        <button className="v-btn" onClick={() => seek(frame - 1, true)}>◀</button>
        <button className="v-btn primary" onClick={toggle}>{video.playing ? '⏸' : '▶'}</button>
        <button className="v-btn" onClick={() => seek(frame + 1, true)}>▶</button>
        <button className="v-btn" onClick={() => seek(frame + 1000, true)}>⏭</button>
        <input
          type="range"
          min={startFrame}
          max={nFrames - 1}
          value={frame}
          onChange={e => { pause(); seek(parseInt(e.target.value), true) }}
          style={{ flex: 1, margin: '0 8px' }}
        />
        <span className="v-time">{videoT.toFixed(2)}s / {dur.toFixed(1)}s</span>
      </div>
    </div>
  )
}
