import React from 'react'
import { useSubjects } from '../../api/hooks'
import { useStore } from '../../store'

// Alertness levels (1–4) → color
const AL_COL   = { 1: '#6DB87A', 2: '#E8B840', 3: '#E07A36', 4: '#CC3F3A' }
const AL_LABEL = { 1: 'Rested', 2: 'Slightly tired', 3: 'Moderate fatigue', 4: 'Extreme fatigue' }

// All paradigms in order
const PARADIGMS = ['ME', 'MI', 'SSVEP', 'P3004L', 'P3005L']
const P_SHORT   = { ME: 'ME', MI: 'MI', SSVEP: 'SSVEP', P3004L: 'P300', P3005L: 'P300+' }
const P_LABEL   = {
  ME:     'Motor Execution — actual hand grasp',
  MI:     'Motor Imagery — imagined hand grasp',
  SSVEP:  'Steady-State Visual Evoked Potentials — flickering checkerboard',
  P3004L: 'P300 Speller — 4-letter oddball',
  P3005L: 'P300 Speller — 5-letter oddball',
}

export default function SubjectGrid({ onSelect }) {
  const { data: subjects = [], isLoading } = useSubjects()
  const { loadRecording, recId } = useStore()

  const handleSelect = (subject) => {
    const sess = subject.sessions[0]
    if (!sess) return
    const paradigm = sess.paradigms[0] || 'ME'
    loadRecording(`${sess.session_id}_${paradigm}`, subject.id, sess.session_id, paradigm)
    onSelect()
  }

  if (isLoading) return <div className="loading"><div className="spin" />Loading subjects…</div>

  return (
    <div className="card">
      <div className="card-hd">
        <div className="card-hd-l">
          <div className="card-title">Subjects</div>
          <div className="card-sub">
            {subjects.length} subjects · {subjects.reduce((s, x) => s + x.n_sessions, 0)} sessions
          </div>
        </div>
      </div>

      {/* Legend */}
      <div style={{
        padding: '6px 16px 10px',
        borderBottom: '1px solid var(--hair)',
        display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center',
      }}>
        <span style={{ fontSize: 10, color: 'var(--ink-3)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.06em' }}>
          Alertness rating:
        </span>
        {[1, 2, 3, 4].map(lv => (
          <span key={lv} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 10.5 }}>
            <span style={{
              display: 'inline-block', width: 10, height: 10, borderRadius: 2,
              background: AL_COL[lv],
            }} />
            <span style={{ color: 'var(--ink-2)' }}>{AL_LABEL[lv]}</span>
          </span>
        ))}
        <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 10.5 }}>
          <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: 'var(--sb-hover)' }} />
          <span style={{ color: 'var(--ink-3)' }}>No data</span>
        </span>

        <span style={{ marginLeft: 12, fontSize: 10, color: 'var(--ink-3)', fontWeight: 600,
                       textTransform: 'uppercase', letterSpacing: '.06em' }}>
          Paradigms:
        </span>
        {PARADIGMS.map(p => (
          <span key={p} title={P_LABEL[p]}
                style={{ fontSize: 10, color: 'var(--ink-2)', cursor: 'default' }}>
            <strong>{P_SHORT[p]}</strong> = {P_LABEL[p].split(' — ')[0]}
          </span>
        ))}
      </div>

      <div className="card-body">
        <div className="subject-grid">
          {subjects.map(s => (
            <div
              key={s.id}
              className={`subject-card ${recId?.startsWith(s.id) ? 'selected' : ''}`}
              onClick={() => handleSelect(s)}
            >
              <div className="sc-id">{s.id}</div>
              <div className="sc-meta">
                {s.age && `${s.age}y`}{s.age && s.sex && ' · '}{s.sex?.[0]}
              </div>

              {/* Paradigm chips colored by alertness */}
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3, margin: '6px 0 4px' }}>
                {PARADIGMS.filter(p => s.alertness[p] != null).map(p => {
                  const lv = Math.round(s.alertness[p])
                  const col = AL_COL[lv] || '#888'
                  return (
                    <span
                      key={p}
                      title={`${P_LABEL[p]}\nMean alertness: ${AL_LABEL[lv]}`}
                      style={{
                        fontSize: 8.5, fontWeight: 700, padding: '1px 4px', borderRadius: 3,
                        background: col + '22', border: `1px solid ${col}66`, color: col,
                        letterSpacing: '.03em',
                      }}
                    >
                      {P_SHORT[p]}
                    </span>
                  )
                })}
              </div>

              <div className="sc-sessions">
                ● {s.n_sessions} session{s.n_sessions !== 1 ? 's' : ''}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
