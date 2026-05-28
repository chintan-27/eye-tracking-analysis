import React, { useMemo } from 'react'
import Plot from 'plotly.js-dist-min'
import createPlotlyComponent from 'react-plotly.js/factory'

const Plotly = createPlotlyComponent(Plot)

// blink_state: 0=open, 1=closing, 2=closed, 3=opening
const STATE_COLOR = ['#30d980', '#fbbf24', '#a78bfa', '#60a5fa']
const STATE_LABEL = ['Open', 'Closing', 'Closed', 'Opening']

/**
 * PhaseSpace3D — Plotly scatter3d: aperture × pupil × p_cr_velocity.
 * Each point = one Phantom frame; color = blink_state.
 * Blink trajectory appears as a loop; tremor = dense cluster.
 *
 * Props:
 *   ts — from usePipelineTimeseries: {aperture_mm, pupil_diameter_mm, p_cr_velocity_mms, blink_state}
 *   height — px
 */
export default function PhaseSpace3D({ ts, height = 420 }) {
  const traces = useMemo(() => {
    if (!ts?.aperture_mm?.length) return null

    const { aperture_mm, pupil_diameter_mm, p_cr_velocity_mms, blink_state } = ts
    if (!p_cr_velocity_mms) return null

    // Build one trace per blink_state for legend
    const byState = [[], [], [], []]
    for (let i = 0; i < aperture_mm.length; i++) {
      const a = aperture_mm[i]
      const p = pupil_diameter_mm[i]
      const v = p_cr_velocity_mms[i]
      const s = blink_state[i] ?? 0
      if (a == null || p == null || v == null) continue
      byState[s].push([a, p, v])
    }

    return byState.map((pts, s) => ({
      type: 'scatter3d',
      mode: 'markers',
      name: STATE_LABEL[s],
      x: pts.map(p => p[0]),
      y: pts.map(p => p[1]),
      z: pts.map(p => p[2]),
      hovertemplate: `aperture=%{x:.2f}mm<br>pupil=%{y:.2f}mm<br>vel=%{z:.3f}mm/s<extra>${STATE_LABEL[s]}</extra>`,
      marker: {
        color: STATE_COLOR[s],
        size: 2,
        opacity: s === 2 ? 0.9 : 0.55,
      },
    })).filter(t => t.x.length > 0)
  }, [ts])

  const layout = useMemo(() => ({
    paper_bgcolor: 'transparent',
    plot_bgcolor:  'transparent',
    margin: { l: 0, r: 0, t: 0, b: 0 },
    legend: {
      font: { color: 'rgba(255,255,255,.65)', size: 10 },
      bgcolor: 'rgba(0,0,0,.4)',
      bordercolor: 'rgba(255,255,255,.1)',
      borderwidth: 1,
    },
    scene: {
      bgcolor: '#0a0d18',
      xaxis: {
        title: 'Aperture (mm)', titlefont: { color: 'rgba(255,255,255,.5)', size: 10 },
        tickfont: { color: 'rgba(255,255,255,.4)', size: 9 },
        gridcolor: 'rgba(255,255,255,.07)', zerolinecolor: 'rgba(255,255,255,.1)',
      },
      yaxis: {
        title: 'Pupil Diam (mm)', titlefont: { color: 'rgba(255,255,255,.5)', size: 10 },
        tickfont: { color: 'rgba(255,255,255,.4)', size: 9 },
        gridcolor: 'rgba(255,255,255,.07)', zerolinecolor: 'rgba(255,255,255,.1)',
      },
      zaxis: {
        title: 'CR Velocity (mm/s)', titlefont: { color: 'rgba(255,255,255,.5)', size: 10 },
        tickfont: { color: 'rgba(255,255,255,.4)', size: 9 },
        gridcolor: 'rgba(255,255,255,.07)', zerolinecolor: 'rgba(255,255,255,.1)',
      },
      camera: { eye: { x: 1.6, y: -1.2, z: 0.7 } },
    },
  }), [])

  if (!traces) {
    return (
      <div style={{
        height, display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center', gap: 8, padding: 20,
      }}>
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none"
             stroke="rgba(251,191,36,.55)" strokeWidth="1.5" strokeLinecap="round">
          <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
        </svg>
        <div style={{ fontSize: 12, fontWeight: 600, color: 'rgba(251,191,36,.8)' }}>
          Requires HPG pipeline output
        </div>
        <div style={{ fontSize: 10.5, color: 'rgba(255,255,255,.35)', maxWidth: 280, textAlign: 'center' }}>
          Run the HPG pipeline to generate per_frame.parquet with aperture, pupil, and CR velocity columns
        </div>
      </div>
    )
  }

  return (
    <Plotly
      data={traces}
      layout={layout}
      config={{ displayModeBar: true, displaylogo: false, responsive: true,
                modeBarButtonsToRemove: ['toImage','sendDataToCloud'] }}
      style={{ width: '100%', height }}
      useResizeHandler
    />
  )
}
