import React, { useMemo, useState } from 'react'
import Plot from 'plotly.js-dist-min'
import createPlotlyComponent from 'react-plotly.js/factory'

const Plotly = createPlotlyComponent(Plot)

const EVENT_COLOR = {
  Fixation:     '#60a5fa',
  Saccade:      '#f87171',
  Unclassified: '#94a3b8',
}

const MODES = [
  { id: 'heatmap',   label: 'Density Map',   tip: 'Where the eye dwelled most' },
  { id: 'fixations', label: 'Fixation Map',  tip: 'Each circle = one fixation; size = dwell time' },
  { id: '3d',        label: '3D Path',       tip: 'x · y · time spiral — drag to rotate' },
]

function normalise(data) {
  if (!data) return []
  if (data.rows) {
    return data.rows.filter(r => r.gaze_x != null && r.gaze_y != null)
  }
  if (data.times_s) {
    return data.times_s.map((t, i) => ({
      phan_frame: null, gaze_x: data.gaze_x[i], gaze_y: data.gaze_y[i],
      event_type: 'Unclassified', valid: true, z: t,
    })).filter(r => r.gaze_x != null && r.gaze_y != null)
  }
  return []
}

// Group consecutive same-type samples → fixation segments with centroid + count
function computeFixations(rows) {
  const fixations = []
  let cur = null
  for (const r of rows) {
    const isFix = r.event_type === 'Fixation'
    if (isFix) {
      if (!cur) cur = { xs: [], ys: [], start: r.phan_frame }
      cur.xs.push(r.gaze_x)
      cur.ys.push(r.gaze_y)
    } else {
      if (cur && cur.xs.length >= 3) {
        const cx = cur.xs.reduce((a, b) => a + b, 0) / cur.xs.length
        const cy = cur.ys.reduce((a, b) => a + b, 0) / cur.ys.length
        fixations.push({ cx, cy, n: cur.xs.length })
      }
      cur = null
    }
  }
  if (cur && cur.xs.length >= 3) {
    const cx = cur.xs.reduce((a, b) => a + b, 0) / cur.xs.length
    const cy = cur.ys.reduce((a, b) => a + b, 0) / cur.ys.length
    fixations.push({ cx, cy, n: cur.xs.length })
  }
  return fixations
}

const DARK_BG    = '#06091a'
const AXIS_STYLE = {
  titlefont:   { color: 'rgba(255,255,255,.5)', size: 10 },
  tickfont:    { color: 'rgba(255,255,255,.4)', size: 9 },
  gridcolor:   'rgba(255,255,255,.06)',
  zerolinecolor: 'rgba(255,255,255,.1)',
}

export default function ScanpathViewer3D({ data, height = 440 }) {
  const [mode, setMode] = useState('heatmap')

  const rows = useMemo(() => normalise(data), [data])

  const traces = useMemo(() => {
    if (!rows.length) return null

    if (mode === 'heatmap') {
      // Bin into 40×23 grid (~48px cells on 1920×1080)
      const BX = 40, BY = 23
      const grid = Array.from({ length: BY }, () => new Array(BX).fill(0))
      for (const r of rows) {
        const bx = Math.min(BX - 1, Math.floor((r.gaze_x / 1920) * BX))
        const by = Math.min(BY - 1, Math.floor((r.gaze_y / 1080) * BY))
        if (bx >= 0 && by >= 0) grid[by][bx]++
      }
      return [{
        type: 'heatmap',
        z: grid,
        x: Array.from({ length: BX }, (_, i) => Math.round((i + 0.5) * 1920 / BX)),
        y: Array.from({ length: BY }, (_, i) => Math.round((i + 0.5) * 1080 / BY)),
        colorscale: [
          [0,    'rgba(6,9,26,0)'],
          [0.05, '#1e3a5f'],
          [0.3,  '#2563eb'],
          [0.6,  '#7c3aed'],
          [0.85, '#dc2626'],
          [1,    '#fbbf24'],
        ],
        showscale: true,
        colorbar: {
          thickness: 10,
          tickfont: { color: 'rgba(255,255,255,.4)', size: 9 },
          title: { text: 'Dwell', side: 'right', font: { color: 'rgba(255,255,255,.4)', size: 9 } },
        },
        hovertemplate: 'x≈%{x}px  y≈%{y}px<br>samples: %{z}<extra></extra>',
      }]
    }

    if (mode === 'fixations') {
      const fixations = computeFixations(rows)
      if (!fixations.length) return null
      const maxN = Math.max(...fixations.map(f => f.n))
      // scanpath line connecting fixation centroids
      const lineTrace = {
        type: 'scatter',
        mode: 'lines',
        x: fixations.map(f => f.cx),
        y: fixations.map(f => f.cy),
        line: { color: 'rgba(255,255,255,.15)', width: 1 },
        showlegend: false,
        hoverinfo: 'skip',
      }
      // fixation circles
      const dotTrace = {
        type: 'scatter',
        mode: 'markers+text',
        x: fixations.map(f => f.cx),
        y: fixations.map(f => f.cy),
        text: fixations.map((_, i) => String(i + 1)),
        textfont: { color: 'rgba(255,255,255,.7)', size: 9 },
        textposition: 'top center',
        marker: {
          color: fixations.map((_, i) => i / Math.max(1, fixations.length - 1)),
          colorscale: [[0,'#60a5fa'],[0.5,'#a78bfa'],[1,'#f87171']],
          size: fixations.map(f => 6 + 18 * (f.n / maxN)),
          opacity: 0.7,
          line: { color: 'rgba(255,255,255,.3)', width: 1 },
          showscale: true,
          colorbar: {
            thickness: 10,
            tickvals: [0, 1], ticktext: ['first', 'last'],
            tickfont: { color: 'rgba(255,255,255,.4)', size: 9 },
            title: { text: 'Order', side: 'right', font: { color: 'rgba(255,255,255,.4)', size: 9 } },
          },
        },
        hovertemplate: 'Fixation %{text}<br>x=%{x:.0f}  y=%{y:.0f}<br>%{customdata} samples<extra></extra>',
        customdata: fixations.map(f => f.n),
        showlegend: false,
      }
      return [lineTrace, dotTrace]
    }

    // 3D scatter path
    const colorFrac = rows.map((_, i) => i / Math.max(1, rows.length - 1))
    return [{
      type: 'scatter3d',
      mode: 'lines+markers',
      x: rows.map(r => r.gaze_x),
      y: rows.map(r => r.gaze_y),
      z: rows.map((r, i) => r.phan_frame ?? r.z ?? i),
      text: rows.map(r => `${r.event_type ?? '?'}<br>${r.phan_frame != null ? 'frame=' + r.phan_frame : ''}`),
      hoverinfo: 'text',
      line: {
        color: colorFrac,
        colorscale: [[0,'#60a5fa'],[0.5,'#a78bfa'],[1,'#f87171']],
        width: 2,
      },
      marker: { color: colorFrac, colorscale: [[0,'#60a5fa'],[1,'#f87171']], size: 2, opacity: 0.6 },
    }]
  }, [rows, mode])

  const layout2D = useMemo(() => ({
    paper_bgcolor: 'transparent',
    plot_bgcolor:  DARK_BG,
    margin: { l: 48, r: 24, t: 8, b: 40 },
    xaxis: {
      ...AXIS_STYLE,
      title: 'Gaze X (px)', range: [0, 1920],
      scaleanchor: mode === 'fixations' ? 'y' : undefined,
    },
    yaxis: {
      ...AXIS_STYLE,
      title: 'Gaze Y (px)', range: [1080, 0],
      scaleratio: mode === 'fixations' ? 1 : undefined,
    },
    shapes: [{
      type: 'rect', x0: 0, x1: 1920, y0: 0, y1: 1080,
      line: { color: 'rgba(255,255,255,.1)', width: 1 },
    }],
  }), [mode])

  const layout3D = useMemo(() => ({
    paper_bgcolor: 'transparent',
    plot_bgcolor:  'transparent',
    margin: { l: 0, r: 0, t: 0, b: 0 },
    scene: {
      bgcolor: DARK_BG,
      xaxis: { ...AXIS_STYLE, title: 'Gaze X (px)', range: [0, 1920] },
      yaxis: { ...AXIS_STYLE, title: 'Gaze Y (px)', range: [1080, 0] },
      zaxis: { ...AXIS_STYLE, title: rows[0]?.phan_frame != null ? 'Phantom Frame' : 'Time (s)' },
      camera: { eye: { x: 1.5, y: -1.5, z: 0.9 } },
    },
  }), [rows])

  const is3D = mode === '3d'
  const noData = !traces || !rows.length

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, height: '100%' }}>
      {/* mode tabs */}
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <div className="pill-grp">
          {MODES.map(m => (
            <button key={m.id} className={`pill ${mode === m.id ? 'active' : ''}`}
                    style={{ fontSize: 10.5 }} onClick={() => setMode(m.id)}>
              {m.label}
            </button>
          ))}
        </div>
        <span style={{ fontSize: 10, color: 'var(--ink-3)', marginLeft: 4 }}>
          {MODES.find(m => m.id === mode)?.tip}
        </span>
        {!noData && (
          <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--ink-3)', fontFamily: 'var(--mono)' }}>
            {rows.length.toLocaleString()} samples
          </span>
        )}
      </div>

      {noData ? (
        <div className="loading" style={{ height: height - 40 }}>
          {rows.length ? 'No plottable data' : 'Loading gaze data…'}
        </div>
      ) : (
        <Plotly
          data={traces}
          layout={is3D ? layout3D : layout2D}
          config={{
            displayModeBar: true, displaylogo: false, responsive: true,
            modeBarButtonsToRemove: ['toImage', 'sendDataToCloud'],
          }}
          style={{ width: '100%', height: height - 40 }}
          useResizeHandler
        />
      )}
    </div>
  )
}
