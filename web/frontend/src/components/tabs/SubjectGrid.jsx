import React from 'react'
import { useSubjects } from '../../api/hooks'
import { useStore } from '../../store'

const AL_COL = { 1:'#6DB87A', 2:'#E8B840', 3:'#E07A36', 4:'#CC3F3A' }
const PARADIGMS = ['ME','MI','SSVEP','P3004L','P3005L']

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
          <div className="card-sub">{subjects.length} subjects · {subjects.reduce((s,x)=>s+x.n_sessions,0)} sessions</div>
        </div>
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
              <div className="sc-meta">{s.age}y · {s.sex?.[0]}</div>
              <div className="sc-swatches">
                {PARADIGMS.map(p => (
                  <div
                    key={p}
                    className="sc-swatch"
                    style={{ background: AL_COL[s.alertness[p]] || '#e0dcd6' }}
                    title={`${p}: alertness ${s.alertness[p] || '—'}`}
                  />
                ))}
              </div>
              <div className="sc-sessions">● {s.n_sessions} session{s.n_sessions !== 1 ? 's' : ''}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
