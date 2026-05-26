import React, { useState, useMemo, useEffect, useRef } from 'react'
import { useStore } from '../../store'
import { useGazeSummary, useTobiiWindow } from '../../api/hooks'
import GazeHeatmap from '../charts/GazeHeatmap'
import PupilChart from '../charts/PupilChart'
import ReactECharts from 'echarts-for-react'

const TRAIL_S = 4
const ANIM_STEP_S = 0.08  // seconds advanced per animation tick
const ANIM_MS = 80        // ms per tick → ~12.5fps of gaze time

// Detect fixations: runs of consecutive points within radius px for >= minMs
function detectFixations(xs, ys, ts, radius = 50, minMs = 120) {
  const fixations = []
  let i = 0
  while (i < xs.length) {
    if (xs[i] == null) { i++; continue }
    let j = i + 1
    while (j < xs.length && xs[j] != null &&
           Math.hypot(xs[j] - xs[i], ys[j] - ys[i]) < radius) j++
    const dur = (ts[j - 1] - ts[i]) * 1000
    if (dur >= minMs) {
      const mx = xs.slice(i, j).reduce((a, b) => a + b, 0) / (j - i)
      const my = ys.slice(i, j).reduce((a, b) => a + b, 0) / (j - i)
      fixations.push({ x: mx, y: my, dur })
    }
    i = j
  }
  return fixations
}

function Scanpath({ data, dw, dh }) {
  const pts = useMemo(() => {
    if (!data?.gaze_x?.length) return { segments: [], fixations: [] }
    const { gaze_x: xs, gaze_y: ys, times_s: ts } = data
    const n = xs.length

    // Build segments with opacity by index fraction
    const segments = []
    for (let i = 1; i < n; i++) {
      if (xs[i] == null || xs[i - 1] == null) continue
      const alpha = (i / n) * 0.85 + 0.05
      segments.push({ x1: xs[i-1], y1: ys[i-1], x2: xs[i], y2: ys[i], alpha })
    }

    const fixations = detectFixations(xs, ys, ts)
    const lastX = xs.findLast(v => v != null)
    const lastY = ys.findLast(v => v != null)
    return { segments, fixations, lastX, lastY }
  }, [data])

  return (
    <svg
      viewBox={`0 0 ${dw} ${dh}`}
      preserveAspectRatio="xMidYMid meet"
      style={{ width: '100%', height: '100%', display: 'block' }}
    >
      <rect width={dw} height={dh} fill="#0d0e1a" />
      {/* grid lines */}
      {[1,2,3].map(i => (
        <line key={'h'+i} x1={0} y1={dh*i/4} x2={dw} y2={dh*i/4}
          stroke="rgba(255,255,255,.04)" strokeWidth={1} />
      ))}
      {[1,2,3].map(i => (
        <line key={'v'+i} x1={dw*i/4} y1={0} x2={dw*i/4} y2={dh}
          stroke="rgba(255,255,255,.04)" strokeWidth={1} />
      ))}
      {/* centre cross */}
      <line x1={dw/2-16} y1={dh/2} x2={dw/2+16} y2={dh/2} stroke="rgba(255,255,255,.12)" strokeWidth={1}/>
      <line x1={dw/2} y1={dh/2-16} x2={dw/2} y2={dh/2+16} stroke="rgba(255,255,255,.12)" strokeWidth={1}/>

      {/* trail */}
      {pts.segments.map((s, i) => (
        <line key={i} x1={s.x1} y1={s.y1} x2={s.x2} y2={s.y2}
          stroke={`rgba(85,168,124,${s.alpha.toFixed(2)})`} strokeWidth={1.5} />
      ))}

      {/* fixation circles */}
      {pts.fixations.map((f, i) => {
        const r = Math.min(40, Math.max(8, Math.sqrt(f.dur) * 1.4))
        return (
          <circle key={i} cx={f.x} cy={f.y} r={r}
            fill="none" stroke={`rgba(85,168,124,.5)`} strokeWidth={1.5}
          />
        )
      })}

      {/* current position — pulsing rings */}
      {pts.lastX != null && <>
        <circle cx={pts.lastX} cy={pts.lastY} r={20}
          fill="none" stroke="#30d980" strokeWidth={1.5} opacity={0.3}>
          <animate attributeName="r" values="14;28;14" dur="1.6s" repeatCount="indefinite" />
          <animate attributeName="opacity" values="0.4;0;0.4" dur="1.6s" repeatCount="indefinite" />
        </circle>
        <circle cx={pts.lastX} cy={pts.lastY} r={8}
          fill="none" stroke="#30d980" strokeWidth={2} opacity={0.6} />
        <circle cx={pts.lastX} cy={pts.lastY} r={4} fill="#30d980" />
      </>}

      {!pts.segments.length &&
        <text x={dw/2} y={dh/2} textAnchor="middle" dominantBaseline="middle"
          fill="rgba(255,255,255,.25)" fontSize={28}>
          Drag scrubber to explore gaze
        </text>
      }
    </svg>
  )
}

export default function GazeMap() {
  const { recId } = useStore()
  const [gazeT, setGazeT] = useState(30)
  const [playing, setPlaying] = useState(false)
  const playRef = useRef(null)
  const { data: summary, isLoading } = useGazeSummary(recId)
  const tStart = Math.max(0, gazeT - TRAIL_S)
  const { data: trailData } = useTobiiWindow(recId, tStart, TRAIL_S)

  const duration = summary?.pupil_times_s?.at(-1) || 0

  useEffect(() => {
    if (playing) {
      playRef.current = setInterval(() => {
        setGazeT(t => {
          const next = t + ANIM_STEP_S
          if (next >= duration) { setPlaying(false); return duration }
          return next
        })
      }, ANIM_MS)
    } else {
      clearInterval(playRef.current)
    }
    return () => clearInterval(playRef.current)
  }, [playing, duration])

  const dw = summary?.display_w || 1012
  const dh = summary?.display_h || 547

  const polarOption = useMemo(() => {
    if (!summary?.saccade_dirs?.length) return null
    const dirs = summary.saccade_dirs
    const n = dirs.length
    return {
      animation: false, backgroundColor: 'transparent',
      polar: { center: ['50%', '50%'], radius: '78%' },
      angleAxis: {
        type: 'category',
        data: Array.from({ length: n }, (_, i) => `${Math.round(i * 360 / n)}°`),
        startAngle: 90,
        axisLabel: { fontSize: 9, color: 'var(--ink-3)' },
        axisLine: { lineStyle: { color: 'var(--hair-2)' } },
        splitLine: { lineStyle: { color: 'rgba(17,19,24,.2)' } },
      },
      radiusAxis: {
        min: 0,
        axisLabel: { show: false },
        axisLine: { show: false },
        splitLine: { lineStyle: { color: 'rgba(17,19,24,.15)' } },
      },
      tooltip: { trigger: 'item', formatter: p => `${p.name}: ${(p.value * 100).toFixed(0)}%` },
      series: [{
        type: 'bar', data: dirs, coordinateSystem: 'polar',
        itemStyle: { color: '#55A87C', opacity: 0.8 }, barMaxWidth: 14,
      }],
    }
  }, [summary])

  if (!recId) return <div className="loading">Select a recording</div>
  if (isLoading) return <div className="loading"><div className="spin" />Loading gaze data…</div>

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>

      {/* Row 1: Scanpath + Heatmap — both spatial, same aspect ratio */}
      <div style={{ display: 'flex', gap: 10, alignItems: 'stretch' }}>

        {/* Scanpath — interactive window explorer */}
        <div className="card" style={{ flex: 5, minWidth: 0 }}>
          <div className="card-hd">
            <div className="card-hd-l">
              <div className="card-title">Gaze Scanpath</div>
              <div className="card-sub">
                {TRAIL_S}s window · hollow circles = fixations (size ∝ duration)
              </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-3)' }}>
                {gazeT.toFixed(1)}s / {duration.toFixed(0)}s
              </span>
              <button
                className={`v-btn${playing ? '' : ' primary'}`}
                onClick={() => {
                  if (gazeT >= duration) setGazeT(0)
                  setPlaying(p => !p)
                }}
                title={playing ? 'Pause' : 'Animate gaze path'}
                style={{ width: 28, height: 28, fontSize: 10 }}
              >
                {playing ? '⏸' : '▶'}
              </button>
            </div>
          </div>
          <div style={{ padding: '0 14px 12px' }}>
            <div style={{
              background: '#0d0e1a', borderRadius: 8, overflow: 'hidden',
              aspectRatio: `${dw}/${dh}`, width: '100%',
            }}>
              <Scanpath data={trailData} dw={dw} dh={dh} />
            </div>
            <input
              type="range" min={0} max={Math.round(duration * 10)} step={1}
              value={Math.round(gazeT * 10)}
              onChange={e => { setPlaying(false); setGazeT(parseInt(e.target.value) / 10) }}
              style={{ width: '100%', marginTop: 8 }}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--ink-3)', fontFamily: 'var(--mono)' }}>
              <span>0s</span><span>{duration.toFixed(0)}s</span>
            </div>
          </div>
        </div>

        {/* Heatmap — full-session aggregate, same proportions as scanpath */}
        <div className="card" style={{ flex: 3, minWidth: 0 }}>
          <div className="card-hd">
            <div className="card-hd-l">
              <div className="card-title">Fixation Heatmap</div>
              <div className="card-sub">Full session · aggregated fixation density</div>
            </div>
          </div>
          <div style={{ padding: '0 14px 12px' }}>
            <div style={{
              background: '#0d0e1a', borderRadius: 8, overflow: 'hidden',
              aspectRatio: `${dw}/${dh}`, width: '100%',
            }}>
              <GazeHeatmap data={summary} height={null} />
            </div>
          </div>
        </div>

      </div>

      {/* Row 2: Pupil timeline (wide) + Saccade polar + stats */}
      <div style={{ display: 'flex', gap: 10, alignItems: 'stretch' }}>

        <div className="card" style={{ flex: 3, minWidth: 0 }}>
          <div className="card-hd">
            <div className="card-title">Pupil Diameter</div>
            <div className="card-sub">Left + right · full session · drag to zoom</div>
          </div>
          <div style={{ padding: '4px 0 0' }}>
            <PupilChart
              data={summary ? {
                times_s: summary.pupil_times_s,
                pupil_left: summary.pupil_left,
                pupil_right: summary.pupil_right,
              } : null}
              height={180}
            />
          </div>
        </div>

        <div className="card" style={{ flex: 1, minWidth: 200 }}>
          <div className="card-hd">
            <div className="card-hd-l">
              <div className="card-title">Saccade Directions</div>
              <div className="card-sub">{summary?.n_saccades?.toLocaleString()} saccades</div>
            </div>
          </div>
          <div className="card-body">
            {polarOption
              ? <ReactECharts option={polarOption} style={{ height: 180 }} opts={{ renderer: 'canvas' }} />
              : <div className="loading" style={{ minHeight: 180 }}>No saccade data</div>}
            <div style={{ borderTop: '1px solid var(--hair-2)', paddingTop: 10, marginTop: 6 }}>
              {[
                ['Fixations', summary?.n_fixations?.toLocaleString()],
                ['Saccades', summary?.n_saccades?.toLocaleString()],
                ['Amp mean', summary?.sac_amp_mean ? `${summary.sac_amp_mean.toFixed(1)}°` : '—'],
              ].map(([k, v]) => (
                <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 5 }}>
                  <span style={{ color: 'var(--ink-3)' }}>{k}</span>
                  <span style={{ fontFamily: 'var(--mono)', color: 'var(--ink)' }}>{v}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

      </div>

    </div>
  )
}
