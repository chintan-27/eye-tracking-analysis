import React from 'react'
import { useStore } from '../store'
import { useSubjects } from '../api/hooks'

export default function SessionHeader() {
  const { recId, subjectId, sessionId, paradigm, loadRecording } = useStore()
  const { data: subjects = [] } = useSubjects()
  if (!recId) return null

  const subject = subjects.find(s => s.id === subjectId)
  const sessions = subject?.sessions || []

  return (
    <div className="sess-header visible">
      <div className="subj-badge mono">{subjectId}</div>
      <div className="sess-divider" />
      <div className="sess-label">Session</div>
      <div className="sess-pills">
        {sessions.map(s => (
          <button
            key={s.session_id}
            className={`sess-pill ${s.session_id === sessionId ? 'active' : ''}`}
            onClick={() => {
              const p = s.paradigms[0]
              if (p) loadRecording(`${s.session_id}_${p}`, subjectId, s.session_id, p)
            }}
          >
            Sess{s.session_number}
          </button>
        ))}
      </div>
      <div className="sess-divider" />
      <div className="sess-label">Paradigm</div>
      <div className="para-pills">
        {(sessions.find(s => s.session_id === sessionId)?.paradigms || []).map(p => (
          <button
            key={p}
            className={`para-pill ${p === paradigm ? 'active' : ''}`}
            onClick={() => loadRecording(`${sessionId}_${p}`, subjectId, sessionId, p)}
          >
            {p}
          </button>
        ))}
      </div>
      <div className="rec-info mono">{recId}</div>
    </div>
  )
}
