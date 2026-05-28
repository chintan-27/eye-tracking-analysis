import React, { useState, useRef, useCallback, useEffect } from 'react'
import ReactECharts from 'echarts-for-react'
import { useStore } from '../../store'
import {
  useMultimodalAtFrame,
  useSyncQuality,
  useSaccades,
  usePipelineVideos,
} from '../../api/hooks'
import GazeScreen from '../charts/GazeScreen'

const SPEEDS = [0.25, 0.5, 1, 2, 4]

// ── HPG pending placeholders ───────────────────────────────────────────────

function PendingBadge({ show }) {
  if (!show) return null
  return (
    <span style={{
      fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.08em',
      padding: '2px 7px', borderRadius: 4,
      background: 'rgba(251,191,36,.14)', color: '#fbbf24',
      border: '1px solid rgba(251,191,36,.28)',
    }}>
      pending HPG
    </span>
  )
}

function HpgPendingPlaceholder({ label, detail }) {
  return (
    <div style={{
      flex: 1, display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center', gap: 8,
      padding: 20, textAlign: 'center',
    }}>
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none"
           stroke="rgba(251,191,36,.55)" strokeWidth="1.5" strokeLinecap="round">
        <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
      </svg>
      <div style={{ fontSize: 12, fontWeight: 600, color: 'rgba(251,191,36,.8)' }}>{label}</div>
      <div style={{ fontSize: 10.5, color: 'rgba(255,255,255,.35)', maxWidth: 240 }}>{detail}</div>
    </div>
  )
}

// ── helpers ────────────────────────────────────────────────────────────────

function SyncBadge({ data }) {
  if (!data) return <span className="sync-badge grey">no sync</span>
  const pct = data.pct_covered ?? data.pct_tobii_covered
  const col = pct == null ? 'grey' : pct > 80 ? 'green' : pct > 50 ? 'amber' : 'red'
  return (
    <span className={`sync-badge ${col}`}>
      {data.n_anchors} anchors{pct != null ? ` · ${pct.toFixed(0)}% covered` : ''}
    </span>
  )
}

// EEG mini-chart (stacked channels from at_frame response)
// API shape: { t_s: [...], channels: { FP1: [...], FZ: [...], ... } }
function EegMini({ eegData, height = 200 }) {
  if (!eegData?.t_s?.length) {
    return <div className="loading" style={{ height }}>no EEG</div>
  }
  const times = eegData.t_s
  // channels may be a dict {FP1:[...]} or an array [{name,y}]
  const channelEntries = Array.isArray(eegData.channels)
    ? eegData.channels
    : Object.entries(eegData.channels ?? {}).map(([name, y]) => ({ name, y }))

  const colors = ['#6C8EE8','#30d980','#E8A84C','#B87FD4','#5BA8D4']
  const channels = channelEntries
  const series = channels.map((ch, i) => {
    const offset = i * 100
    return {
      name: ch.name,
      type: 'line',
      data: ch.y.map((v, j) => [times[j], (v ?? 0) + offset]),
      lineStyle: { width: 1, color: colors[i % colors.length] },
      symbol: 'none',
      animation: false,
    }
  })

  const option = {
    backgroundColor: 'transparent',
    animation: false,
    grid: { top: 8, bottom: 24, left: 44, right: 10 },
    xAxis: {
      type: 'value', min: times[0], max: times[times.length - 1],
      axisLabel: { color: 'rgba(255,255,255,.4)', fontSize: 9,
                   formatter: v => `${v.toFixed(1)}s` },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,.05)' } },
      axisLine: { show: false }, axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      axisLabel: {
        color: 'rgba(255,255,255,.4)', fontSize: 9,
        formatter: (v) => {
          const idx = Math.round(v / 100)
          return channels[idx]?.name ?? ''
        },
      },
      splitLine: { show: false }, axisLine: { show: false }, axisTick: { show: false },
    },
    tooltip: { show: false },
    series,
  }

  return (
    <ReactECharts
      option={option}
      style={{ width: '100%', height }}
      opts={{ renderer: 'canvas' }}
    />
  )
}

// Aperture + pupil timeseries mini-chart
function ApertureMini({ pipeline, eegData, height = 200 }) {
  if (!pipeline) {
    return <div className="loading" style={{ height }}>no pipeline data</div>
  }

  const { aperture_mm, pupil_diameter_mm, phan_frame } = pipeline
  if (!phan_frame?.length) return <div className="loading" style={{ height }}>no frames</div>

  const apSeries = {
    name: 'aperture_mm', type: 'line', symbol: 'none', animation: false,
    data: phan_frame.map((f, i) => [f, aperture_mm[i]]),
    lineStyle: { width: 1.5, color: '#30d980' },
    areaStyle: { color: 'rgba(48,217,128,.08)' },
  }
  const puSeries = {
    name: 'pupil_mm', type: 'line', symbol: 'none', animation: false,
    data: phan_frame.map((f, i) => [f, pupil_diameter_mm?.[i] ?? null]),
    lineStyle: { width: 1, color: '#60a5fa', type: 'dashed' },
  }

  const option = {
    backgroundColor: 'transparent',
    animation: false,
    grid: { top: 8, bottom: 24, left: 44, right: 10 },
    xAxis: {
      type: 'value',
      axisLabel: { color: 'rgba(255,255,255,.4)', fontSize: 9,
                   formatter: v => `f${v}` },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,.05)' } },
      axisLine: { show: false }, axisTick: { show: false },
    },
    yAxis: {
      type: 'value', name: 'mm', nameTextStyle: { color: 'rgba(255,255,255,.3)', fontSize: 9 },
      axisLabel: { color: 'rgba(255,255,255,.4)', fontSize: 9 },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,.05)' } },
      axisLine: { show: false }, axisTick: { show: false },
    },
    legend: {
      data: ['aperture_mm','pupil_mm'],
      textStyle: { color: 'rgba(255,255,255,.55)', fontSize: 9 },
      top: 2, right: 10,
    },
    tooltip: { show: false },
    series: [apSeries, puSeries],
  }

  return (
    <ReactECharts
      option={option}
      style={{ width: '100%', height }}
      opts={{ renderer: 'canvas' }}
    />
  )
}

// ── saccade comparison table ───────────────────────────────────────────────

function SaccadeComparison({ data, onJump }) {
  if (!data) return null
  const { tobii_saccades, phantom_saccades, comparison, n_tobii, n_phantom, n_matched, match_pct } = data

  const hasPipeline = phantom_saccades?.length > 0

  return (
    <div className="card" style={{ flexShrink: 0 }}>
      <div className="card-hd">
        <div className="card-hd-l">
          <span className="card-title">Saccade Comparison</span>
          <span className="card-sub">
            Tobii labelled vs Phantom CR-velocity threshold detection
          </span>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexShrink: 0 }}>
          <Stat label="Tobii"    val={n_tobii}   color="#60a5fa" />
          <Stat label="Phantom"  val={hasPipeline ? n_phantom : '—'} color="#30d980" />
          <Stat label="Matched"  val={match_pct != null ? `${match_pct}%` : '—'} color={match_pct > 80 ? '#30d980' : match_pct > 50 ? '#fbbf24' : '#f87171'} />
        </div>
      </div>

      {!hasPipeline && (
        <div style={{ padding: '10px 16px', fontSize: 11, color: 'rgba(255,255,255,.4)' }}>
          Phantom saccade detection requires HPG pipeline output (per_frame.parquet).
          Showing Tobii-only list.
        </div>
      )}

      <div style={{
        maxHeight: 200, overflowY: 'auto', borderTop: '1px solid rgba(255,255,255,.08)',
      }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10.5 }}>
          <thead>
            <tr style={{ background: 'rgba(255,255,255,.04)', position: 'sticky', top: 0 }}>
              {['#', 'Tobii frame', 'Amplitude', 'Direction', 'Phantom frame', 'Lag', ''].map(h => (
                <th key={h} style={{ padding: '5px 10px', textAlign: 'left', fontWeight: 600,
                                     color: 'rgba(255,255,255,.45)', borderBottom: '1px solid rgba(255,255,255,.08)' }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tobii_saccades.slice(0, 80).map((s, i) => {
              const cmp = comparison?.[i]
              const matched = cmp?.matched
              return (
                <tr key={i}
                  style={{ borderBottom: '1px solid rgba(255,255,255,.04)',
                           background: i % 2 ? 'transparent' : 'rgba(255,255,255,.02)' }}>
                  <td style={{ padding: '4px 10px', color: 'rgba(255,255,255,.3)', fontFamily: 'var(--mono)' }}>
                    {i + 1}
                  </td>
                  <td style={{ padding: '4px 10px', fontFamily: 'var(--mono)', color: '#60a5fa' }}>
                    {s.phan_frame ?? '—'}
                  </td>
                  <td style={{ padding: '4px 10px', color: 'rgba(255,255,255,.7)' }}>
                    {s.amplitude_deg != null ? `${s.amplitude_deg}°` : '—'}
                  </td>
                  <td style={{ padding: '4px 10px', color: 'rgba(255,255,255,.7)' }}>
                    {s.direction_deg != null ? `${s.direction_deg}°` : '—'}
                  </td>
                  <td style={{ padding: '4px 10px', fontFamily: 'var(--mono)',
                               color: matched == null ? 'rgba(255,255,255,.3)' : matched ? '#30d980' : '#f87171' }}>
                    {cmp?.phantom_phan_frame ?? '—'}
                  </td>
                  <td style={{ padding: '4px 10px', fontFamily: 'var(--mono)',
                               color: cmp?.lag_frames == null ? 'rgba(255,255,255,.3)'
                                    : Math.abs(cmp.lag_frames) <= 5 ? '#30d980'
                                    : Math.abs(cmp.lag_frames) <= 20 ? '#fbbf24' : '#f87171' }}>
                    {cmp?.lag_frames != null ? `${cmp.lag_frames > 0 ? '+' : ''}${cmp.lag_frames}f` : '—'}
                  </td>
                  <td style={{ padding: '4px 10px' }}>
                    {s.phan_frame != null && (
                      <button
                        onClick={() => onJump(s.phan_frame)}
                        style={{ fontSize: 9, padding: '2px 6px', borderRadius: 4, border: 'none',
                                 background: 'rgba(96,165,250,.15)', color: '#60a5fa', cursor: 'pointer' }}>
                        jump
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {tobii_saccades.length > 80 && (
          <div style={{ padding: '6px 10px', fontSize: 10, color: 'rgba(255,255,255,.3)', textAlign: 'center' }}>
            showing first 80 of {tobii_saccades.length}
          </div>
        )}
      </div>
    </div>
  )
}

function Stat({ label, val, color }) {
  return (
    <div style={{ textAlign: 'center', minWidth: 52 }}>
      <div style={{ fontSize: 15, fontFamily: 'var(--mono)', fontWeight: 700, color }}>{val}</div>
      <div style={{ fontSize: 9, color: 'rgba(255,255,255,.4)', textTransform: 'uppercase',
                    letterSpacing: '.07em' }}>{label}</div>
    </div>
  )
}

// ── main component ──────────────────────────────────────────────────────────

export default function MultimodalViewer() {
  const { recId, phanFrame, setPhanFrame } = useStore()
  const [speed, setSpeed]     = useState(1)
  const [playing, setPlaying] = useState(false)
  const [nFrames, setNFrames] = useState(10000)
  const [videoName, setVideoName] = useState('processed_overlay')
  const [videoError, setVideoError] = useState(false)
  const [saccadeIdx, setSaccadeIdx] = useState(-1)
  const playRef = useRef(null)
  const videoRef = useRef(null)

  const { data: syncQuality } = useSyncQuality(recId)
  const { data: mmData }      = useMultimodalAtFrame(recId, phanFrame)
  const { data: saccadeData } = useSaccades(recId)
  const { data: videosData }  = usePipelineVideos(recId)

  const recentSaccades = saccadeData?.tobii_saccades?.slice(-4) ?? []
  const saccadeOnsets  = (saccadeData?.tobii_saccades ?? [])
    .map(s => s.phan_frame)
    .filter(f => f != null)

  // Update nFrames when data arrives
  useEffect(() => {
    if (mmData?.sync?.n_frames) setNFrames(mmData.sync.n_frames)
  }, [mmData])

  // Auto-initialise to first frame when recording changes
  useEffect(() => {
    if (recId) { setPhanFrame(0); setSaccadeIdx(-1) }
  }, [recId])

  // seek must be declared before any callback that references it
  const seek = useCallback((n) => {
    const clamped = Math.max(0, Math.min(nFrames - 1, Number(n)))
    setPhanFrame(clamped)
    if (videoRef.current) {
      const t = clamped / 167
      if (Math.abs(videoRef.current.currentTime - t) > 0.1) {
        videoRef.current.currentTime = t
      }
    }
  }, [nFrames])

  // Saccade navigator helpers
  const jumpToSaccade = useCallback((idx) => {
    const clamped = Math.max(0, Math.min(saccadeOnsets.length - 1, idx))
    setSaccadeIdx(clamped)
    seek(saccadeOnsets[clamped])
  }, [saccadeOnsets, seek])

  const prevSaccade = useCallback(() => {
    const next = saccadeIdx <= 0 ? saccadeOnsets.length - 1 : saccadeIdx - 1
    jumpToSaccade(next)
  }, [saccadeIdx, jumpToSaccade, saccadeOnsets.length])

  const nextSaccade = useCallback(() => {
    const next = saccadeIdx >= saccadeOnsets.length - 1 ? 0 : saccadeIdx + 1
    jumpToSaccade(next)
  }, [saccadeIdx, jumpToSaccade, saccadeOnsets.length])

  // Playback loop
  useEffect(() => {
    if (!playing) { clearInterval(playRef.current); return }
    const msPerFrame = 1000 / (167 * speed)
    playRef.current = setInterval(() => {
      setPhanFrame(f => {
        const next = f + 1
        if (next >= nFrames) { setPlaying(false); return f }
        return next
      })
    }, msPerFrame)
    return () => clearInterval(playRef.current)
  }, [playing, speed, nFrames])

  // videosData is a plain array of {name, url, size_mb, ...}
  const videoAvailable = Array.isArray(videosData) && videosData.some(v => v.name === videoName)
  const videoUrl = videoAvailable ? `/api/pipeline/${recId}/video/${videoName}` : null

  const frameT = phanFrame >= 0 ? `${phanFrame}` : '—'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minHeight: 0 }}>

      {/* ── controls bar ──────────────────────────────────────────────── */}
      <div className="card" style={{ flexShrink: 0 }}>
        <div style={{ padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <span className="ctrl-lbl">Frame</span>
          <span style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--pri)', minWidth: 64 }}>
            {frameT} / {nFrames}
          </span>

          <input
            type="range" min={0} max={nFrames - 1} value={phanFrame >= 0 ? phanFrame : 0}
            onChange={e => seek(e.target.value)}
            style={{ flex: 1, minWidth: 120, accentColor: 'var(--pri)' }}
          />

          <button
            className="pill"
            onClick={() => setPlaying(p => !p)}
            style={{ minWidth: 52 }}
          >
            {playing ? '⏸' : '▶'}
          </button>

          <div className="pill-grp">
            {SPEEDS.map(s => (
              <button key={s} className={`pill ${speed === s ? 'active' : ''}`}
                      onClick={() => setSpeed(s)}>
                {s}×
              </button>
            ))}
          </div>

          <div className="ctrl-sep" />

          <div className="pill-grp">
            {['processed_overlay','stages_grid'].map(n => (
              <button key={n}
                className={`pill ${videoName === n ? 'active' : ''}`}
                onClick={() => { setVideoName(n); setVideoError(false) }}>
                {n === 'processed_overlay' ? 'Overlay' : 'Stages'}
              </button>
            ))}
          </div>

          {saccadeOnsets.length > 0 && (
            <>
              <div className="ctrl-sep" />
              <span className="ctrl-lbl">Saccade</span>
              <button className="pill" onClick={prevSaccade} title="Previous saccade">‹</button>
              <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-3)',
                             minWidth: 52, textAlign: 'center' }}>
                {saccadeIdx >= 0 ? `${saccadeIdx + 1}/${saccadeOnsets.length}` : `${saccadeOnsets.length}`}
              </span>
              <button className="pill" onClick={nextSaccade} title="Next saccade">›</button>
            </>
          )}

          <SyncBadge data={syncQuality} />
        </div>
      </div>

      {/* ── 2×2 grid ──────────────────────────────────────────────────── */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gridTemplateRows: '1fr 1fr',
        gap: 8,
        flex: 1,
        minHeight: 0,
        minWidth: 0,
      }}>

        {/* top-left: Phantom video (requires HPG pipeline MP4 output) */}
        <div className="card" style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <div className="card-hd">
            <div className="card-hd-l">
              <span className="card-title">Phantom Video</span>
              <span className="card-sub" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                {videoUrl ? videoName : 'requires HPG pipeline output'}
                <PendingBadge show={!videoUrl} />
              </span>
            </div>
          </div>
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
                        padding: 10, minHeight: 0 }}>
            {videoUrl && !videoError ? (
              <video
                ref={videoRef}
                src={videoUrl}
                style={{ maxWidth: '100%', maxHeight: '100%', borderRadius: 6,
                         border: '1px solid rgba(255,255,255,.1)' }}
                muted
                preload="metadata"
                onError={() => setVideoError(true)}
                onLoadedMetadata={e => {
                  const dur = e.target.duration
                  if (dur > 0) setNFrames(Math.round(dur * 167))
                }}
              />
            ) : (
              <HpgPendingPlaceholder
                label="Phantom video"
                detail="Run HPG pipeline to generate processed_overlay.mp4 or stages_grid.mp4"
              />
            )}
          </div>
        </div>

        {/* top-right: Tobii gaze screen */}
        <div className="card" style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <div className="card-hd">
            <div className="card-hd-l">
              <span className="card-title">Tobii Gaze</span>
              <span className="card-sub">
                {mmData?.tobii
                  ? `(${mmData.tobii.gaze_x?.toFixed(0)}, ${mmData.tobii.gaze_y?.toFixed(0)}) · ${mmData.tobii.event_type ?? '—'}`
                  : 'no tobii data'}
              </span>
            </div>
          </div>
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
                        padding: 10, minHeight: 0 }}>
            <GazeScreenAuto
              current={mmData?.tobii ?? null}
              saccades={recentSaccades}
            />
          </div>
        </div>

        {/* bottom-left: EEG waveform */}
        <div className="card" style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <div className="card-hd">
            <div className="card-hd-l">
              <span className="card-title">EEG</span>
              <span className="card-sub">
                {mmData?.eeg
                  ? `${mmData.eeg.channels?.length ?? 0} ch · 4s window`
                  : 'FP1 · FZ · CZ · CPZ · OZ'}
              </span>
            </div>
          </div>
          <div style={{ flex: 1, minHeight: 0, paddingBottom: 4 }}>
            <EegMini eegData={mmData?.eeg} height="100%" />
          </div>
        </div>

        {/* bottom-right: aperture + pupil (requires HPG per_frame.parquet) */}
        <div className="card" style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <div className="card-hd">
            <div className="card-hd-l">
              <span className="card-title">Aperture · Pupil</span>
              <span className="card-sub" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                {mmData?.pipeline
                  ? `aperture ${mmData.pipeline.aperture_mm?.toFixed(2) ?? '—'} mm · pupil ${mmData.pipeline.pupil_diameter_mm?.toFixed(2) ?? '—'} mm`
                  : 'requires HPG pipeline output'}
                <PendingBadge show={!mmData?.pipeline} />
              </span>
            </div>
          </div>
          <div style={{ flex: 1, minHeight: 0, paddingBottom: 4 }}>
            {mmData?.pipeline
              ? <ApertureMiniSingle value={mmData.pipeline} />
              : <HpgPendingPlaceholder
                  label="Aperture & pupil metrics"
                  detail="Run HPG pipeline to generate per_frame.parquet for this recording"
                />
            }
          </div>
        </div>
      </div>

      {/* ── saccade comparison ─────────────────────────────────────────── */}
      {saccadeData && (
        <SaccadeComparison data={saccadeData} onJump={seek} />
      )}
    </div>
  )
}

// Auto-sizing GazeScreen that fills its container
function GazeScreenAuto({ current, saccades }) {
  const ref = useRef(null)
  const [w, setW] = useState(320)
  useEffect(() => {
    if (!ref.current) return
    const ro = new ResizeObserver(entries => {
      const entry = entries[0]
      setW(Math.floor(entry.contentRect.width))
    })
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [])
  return (
    <div ref={ref} style={{ width: '100%' }}>
      <GazeScreen current={current} saccades={saccades} width={Math.max(160, w)} />
    </div>
  )
}

// Single-point display for aperture/pupil when no timeseries available
function ApertureMiniSingle({ value }) {
  if (!value) return <div className="loading">no pipeline data at this frame</div>

  const metrics = [
    { label: 'aperture_mm',       val: value.aperture_mm,       unit: 'mm',   color: '#30d980' },
    { label: 'pupil_diameter_mm', val: value.pupil_diameter_mm, unit: 'mm',   color: '#60a5fa' },
    { label: 'blink_state',       val: value.blink_state,       unit: '',     color: '#a78bfa' },
    { label: 'p_cr_velocity',     val: value.p_cr_velocity_mms, unit: 'mm/s', color: '#fbbf24' },
    { label: 'flow_mag_mean',     val: value.flow_mag_mean_eyelid, unit: '',  color: '#f87171' },
  ]

  return (
    <div style={{ padding: '14px 16px', display: 'grid', gap: 8 }}>
      {metrics.map(m => (
        <div key={m.label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontSize: 11, color: 'rgba(255,255,255,.5)', fontFamily: 'var(--mono)' }}>
            {m.label}
          </span>
          <span style={{ fontSize: 12, fontFamily: 'var(--mono)', color: m.color }}>
            {m.val != null ? `${typeof m.val === 'number' ? m.val.toFixed(3) : m.val}${m.unit ? ' ' + m.unit : ''}` : '—'}
          </span>
        </div>
      ))}
    </div>
  )
}
