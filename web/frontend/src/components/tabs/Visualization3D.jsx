import React, { useState } from 'react'
import { useStore } from '../../store'
import { useTobiiWindow, useTobiiWindowByFrame, usePipelineTimeseries } from '../../api/hooks'
import ScanpathViewer3D from '../charts/ScanpathViewer3D'
import PhaseSpace3D from '../charts/PhaseSpace3D'
import EyeAnatomy3D from '../charts/EyeAnatomy3D'

const VIEWS = [
  { id: 'scanpath',  label: 'Gaze Scanpath',  sub: 'x · y · time (Tobii)' },
  { id: 'phasespace', label: 'Phase Space',   sub: 'aperture · pupil · CR velocity' },
  { id: 'anatomy',   label: 'Eye Anatomy',    sub: 'Three.js animated model' },
]

export default function Visualization3D() {
  const recId = useStore(s => s.recId)
  const [view, setView] = useState('scanpath')

  // Load up to 120s of Tobii data; prefer phan_frame-aligned if available
  const { data: tobiiByFrame } = useTobiiWindowByFrame(recId, 0, 20000)
  const { data: tobiiByTime }  = useTobiiWindow(recId, 0, 120)
  const tobii = tobiiByFrame?.rows?.length ? tobiiByFrame : tobiiByTime
  const { data: ts } = usePipelineTimeseries(recId)

  if (!recId) return <div className="empty-state">Select a subject to view 3D visualizations</div>

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>

      {/* view selector */}
      <div className="card" style={{ flexShrink: 0 }}>
        <div style={{ padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <div className="pill-grp">
            {VIEWS.map(v => (
              <button key={v.id} className={`pill ${view === v.id ? 'active' : ''}`}
                      onClick={() => setView(v.id)}>
                {v.label}
              </button>
            ))}
          </div>
          <div style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--ink-3)' }}>
            {VIEWS.find(v => v.id === view)?.sub}
          </div>
        </div>
      </div>

      {/* chart area */}
      <div className="card" style={{ flex: 1, minHeight: 460 }}>
        <div style={{ padding: 12, height: '100%' }}>
          {view === 'scanpath'   && <ScanpathViewer3D data={tobii} height={460} />}
          {view === 'phasespace' && <PhaseSpace3D ts={ts} height={460} />}
          {view === 'anatomy'    && <AnatomyPanel ts={ts} />}
        </div>
      </div>

    </div>
  )
}

// Anatomy panel: shows 3D eye + current metric readout
function AnatomyPanel({ ts }) {
  // Pick the mid-session frame for a representative value
  const mid = ts ? Math.floor(ts.aperture_mm.length / 2) : null
  const ap = mid != null ? (ts.aperture_mm[mid] ?? 8.0)         : null
  const pd = mid != null ? (ts.pupil_diameter_mm[mid] ?? 4.0)   : null

  return (
    <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
      <div style={{ flex: 1 }}>
        <EyeAnatomy3D apertureMm={ap} pupilMm={pd} height={460} />
      </div>
      <div style={{ width: 180, flexShrink: 0 }}>
        <div style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase',
                      letterSpacing: '.09em', color: 'var(--ink-3)', marginBottom: 10 }}>
          Mid-session values
        </div>
        {[
          { label: 'Aperture',    val: ap,  unit: 'mm', color: '#30d980' },
          { label: 'Pupil Diam',  val: pd,  unit: 'mm', color: '#60a5fa' },
        ].map(({ label, val, unit, color }) => (
          <div key={label} style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 10, color: 'var(--ink-3)' }}>{label}</div>
            <div style={{ fontSize: 20, fontFamily: 'var(--mono)', color, fontWeight: 700 }}>
              {val != null ? val.toFixed(2) : '—'}
              <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--ink-3)', marginLeft: 4 }}>{unit}</span>
            </div>
          </div>
        ))}
        {!ts && (
          <div style={{ marginTop: 16, padding: 10, borderRadius: 8,
                        background: 'rgba(251,191,36,.1)', border: '1px solid rgba(251,191,36,.2)' }}>
            <div style={{ fontSize: 10.5, color: '#fbbf24', fontWeight: 600, marginBottom: 4 }}>
              Pending HPG output
            </div>
            <div style={{ fontSize: 10, color: 'rgba(255,255,255,.4)' }}>
              Eye shows resting pose until pipeline data is available
            </div>
          </div>
        )}
        <div style={{ marginTop: 12, fontSize: 10, color: 'var(--ink-3)', lineHeight: 1.5 }}>
          Drag to rotate · Scroll to zoom
        </div>
      </div>
    </div>
  )
}
