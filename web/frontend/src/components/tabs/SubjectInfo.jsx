import React from 'react'
import { useStore } from '../../store'
import { useSessionDetail } from '../../api/hooks'

const AL_COL   = { 1: '#6DB87A', 2: '#E8B840', 3: '#E07A36', 4: '#CC3F3A' }
const AL_LABEL = { 1: 'Rested', 2: 'Slightly tired', 3: 'Moderate fatigue', 4: 'Extreme fatigue' }

const PARADIGMS = ['ME', 'MI', 'SSVEP', 'P3004L', 'P3005L']
const P_FULL = {
  ME:     { short: 'ME',    title: 'Motor Execution',  desc: 'Participant physically grasped a hand gripper, 40 trials. 2s fixation → cue → 4s task → 1–1.5s rest.' },
  MI:     { short: 'MI',    title: 'Motor Imagery',    desc: 'Participant imagined grasping a hand gripper without moving, 40 trials. Same timing as ME.' },
  SSVEP:  { short: 'SSVEP', title: 'SSVEP',            desc: 'Flickering checkerboards at 10, 11, 12, 13 Hz. Brain responds at the flicker frequency. 40 trials.' },
  P3004L: { short: 'P300',  title: 'P300 Speller (4L)', desc: '4-letter oddball paradigm. Participant counts rare target letters. 40 trials, P300 ERP expected ~300ms post-target.' },
  P3005L: { short: 'P300+', title: 'P300 Speller (5L)', desc: '5-letter oddball variant. 50 trials, otherwise identical to P3004L.' },
}

// Edinburgh Handedness Inventory score → label
function ehi_label(score) {
  if (score == null) return '—'
  if (score >= 80)  return `Right-handed (EHI ${score})`
  if (score >= 20)  return `Weak right-handed (EHI ${score})`
  if (score > -20)  return `Ambidextrous (EHI ${score})`
  if (score > -80)  return `Weak left-handed (EHI ${score})`
  return `Left-handed (EHI ${score})`
}

function Stat({ label, value, color }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ fontSize: 10, color: 'var(--ink-3)', textTransform: 'uppercase', letterSpacing: '.07em', marginBottom: 2 }}>
        {label}
      </div>
      <div style={{ fontSize: 17, fontFamily: 'var(--mono)', fontWeight: 700, color: color || 'var(--ink)' }}>
        {value ?? '—'}
      </div>
    </div>
  )
}

function AlertnessBadge({ level }) {
  if (!level) return <span style={{ color: 'var(--ink-3)' }}>—</span>
  const lv = Math.round(level)
  return (
    <span style={{
      padding: '2px 8px', borderRadius: 4, fontSize: 10.5, fontWeight: 600,
      background: AL_COL[lv] + '22', border: `1px solid ${AL_COL[lv]}66`, color: AL_COL[lv],
    }}>
      {AL_LABEL[lv]} ({lv}/4)
    </span>
  )
}

export default function SubjectInfo() {
  const { subjectId, sessionId, paradigm } = useStore()
  const { data: sess, isLoading, error } = useSessionDetail(sessionId)

  if (!subjectId) return <div className="empty-state">No recording selected</div>

  const subj = sess?.subject
  const currentAl = sess?.alertness?.[paradigm]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>

      {/* Subject demographics */}
      <div className="card-row">
        <div className="card" style={{ flex: '0 0 220px' }}>
          <div className="card-hd">
            <div className="card-hd-l">
              <div className="card-title">Subject</div>
              <div className="card-sub">{subjectId}</div>
            </div>
          </div>
          <div className="card-body">
            {isLoading && <div className="loading"><div className="spin" />Loading…</div>}
            {subj && (
              <>
                <Stat label="Age"         value={subj.age != null ? `${subj.age} years` : null} />
                <Stat label="Sex"         value={subj.sex} />
                <Stat label="Handedness"  value={ehi_label(subj.handedness)} />
              </>
            )}
            {error && <div style={{ fontSize: 11, color: 'var(--acc)' }}>Could not load subject data</div>}
          </div>
        </div>

        {/* Current session */}
        <div className="card" style={{ flex: '0 0 240px' }}>
          <div className="card-hd">
            <div className="card-hd-l">
              <div className="card-title">Session</div>
              <div className="card-sub">{sessionId}</div>
            </div>
          </div>
          <div className="card-body">
            <Stat label="Session #"  value={sess?.session_number != null ? `Session ${sess.session_number}` : null} />
            <Stat label="Date"       value={sess?.date || null} />
            <Stat label="Paradigm"   value={paradigm} color="var(--pri)" />
            <div style={{ marginTop: 4 }}>
              <div style={{ fontSize: 10, color: 'var(--ink-3)', textTransform: 'uppercase', letterSpacing: '.07em', marginBottom: 4 }}>
                Alertness this session
              </div>
              <AlertnessBadge level={currentAl} />
              <div style={{ fontSize: 10.5, color: 'var(--ink-3)', marginTop: 6, lineHeight: 1.5 }}>
                Self-reported post-session. Scale: 1 = rested, 4 = extreme fatigue.
              </div>
            </div>
          </div>
        </div>

        {/* All paradigm alertness for this session */}
        {sess?.alertness && (
          <div className="card" style={{ flex: 1 }}>
            <div className="card-hd">
              <div className="card-hd-l">
                <div className="card-title">Alertness by Paradigm</div>
                <div className="card-sub">Self-reported post-task fatigue · session {sess.session_number}</div>
              </div>
            </div>
            <div className="card-body">
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {PARADIGMS.filter(p => sess.alertness[p] != null).map(p => {
                  const lv = sess.alertness[p]
                  const lv_r = Math.round(lv)
                  const col = AL_COL[lv_r] || '#888'
                  return (
                    <div key={p} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <span style={{
                        fontSize: 9.5, fontWeight: 700, minWidth: 44, padding: '2px 5px',
                        borderRadius: 3, background: col + '20', border: `1px solid ${col}50`, color: col,
                        textAlign: 'center',
                      }}>
                        {P_FULL[p]?.short || p}
                      </span>
                      <div style={{
                        flex: 1, height: 6, borderRadius: 3, background: 'var(--sb-hover)', overflow: 'hidden',
                      }}>
                        <div style={{
                          width: `${((lv_r - 1) / 3) * 100}%`, height: '100%',
                          background: col, borderRadius: 3, transition: 'width .4s',
                        }} />
                      </div>
                      <span style={{ fontSize: 10.5, color: col, fontWeight: 600, minWidth: 90 }}>
                        {AL_LABEL[lv_r]}
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Paradigm descriptions */}
      <div className="card">
        <div className="card-hd">
          <div className="card-hd-l">
            <div className="card-title">BCI Paradigms — Reference</div>
            <div className="card-sub">4 task types across the dataset</div>
          </div>
        </div>
        <div className="card-body">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 10 }}>
            {PARADIGMS.map(p => {
              const info = P_FULL[p]
              const isActive = p === paradigm
              return (
                <div key={p} style={{
                  padding: '10px 12px', borderRadius: 8,
                  border: `1px solid ${isActive ? 'var(--pri)' : 'var(--hair)'}`,
                  background: isActive ? 'rgba(48,217,128,.05)' : 'transparent',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <span style={{
                      fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: 3,
                      background: isActive ? 'rgba(48,217,128,.15)' : 'var(--sb-hover)',
                      color: isActive ? 'var(--pri)' : 'var(--ink-2)',
                    }}>
                      {info.short}
                    </span>
                    <span style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--ink)' }}>
                      {info.title}
                      {isActive && <span style={{ color: 'var(--pri)', marginLeft: 6, fontSize: 10 }}>← current</span>}
                    </span>
                  </div>
                  <div style={{ fontSize: 10.5, color: 'var(--ink-2)', lineHeight: 1.55 }}>
                    {info.desc}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {/* Dataset context */}
      <div className="card">
        <div className="card-hd">
          <div className="card-hd-l">
            <div className="card-title">Dataset</div>
            <div className="card-sub">Eye-BCI Multimodal Dataset — Scientific Data 2025</div>
          </div>
        </div>
        <div className="card-body" style={{ fontSize: 11, color: 'var(--ink-2)', lineHeight: 1.7 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <strong>Recording streams:</strong> 64-channel EEG at ~1000 Hz (Neuroscan) · Tobii
              eye-tracker at 300 Hz (gaze, pupil) · Phantom high-speed camera at ~167 fps
            </div>
            <div>
              <strong>Synchronisation:</strong> Arduino sends square-wave trigger to EEG and
              Phantom simultaneously. Tobii is time-aligned via Cedrus StimTracker light-sensor
              pulses recorded in the EEG stream.
            </div>
            <div>
              <strong>Research goal:</strong> Identify eye-movement and blink biomarkers (aperture,
              pupil diameter, blink rate, CR velocity) that correlate with Parkinson's disease,
              tremor, and fatigue.
            </div>
            <div>
              <strong>Trial structure:</strong> Fixation cross (2s) → stimulus cue → task (4s) →
              inter-trial rest (1–1.5s random jitter). 40 trials per paradigm per session.
            </div>
          </div>
          <div style={{ marginTop: 10, padding: '6px 10px', borderRadius: 6,
                        background: 'rgba(255,255,255,.04)', fontSize: 10.5, color: 'var(--ink-3)' }}>
            DOI: 10.1038/s41597-025-04861-9 · 31 subjects · 63 sessions · 46 hours of data
          </div>
        </div>
      </div>
    </div>
  )
}
