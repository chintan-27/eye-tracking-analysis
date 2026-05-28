import React from 'react'
import { useStore } from '../store'

const ICONS = {
  info: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10"/>
      <line x1="12" y1="16" x2="12" y2="12"/>
      <line x1="12" y1="8" x2="12.01" y2="8"/>
    </svg>
  ),
  eeg: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="2,12 5,12 7,4 9,20 11,10 13,14 15,12 18,12 20,8 22,12"/>
    </svg>
  ),
  video: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="6" width="14" height="12" rx="2"/>
      <path d="m16 10 5.414-2.707A1 1 0 0 1 23 8.17v7.66a1 1 0 0 1-1.586.818L16 14"/>
    </svg>
  ),
  blinks: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 12s3-8 10-8 10 8 10 8-3 8-10 8-10-8-10-8z"/>
      <circle cx="12" cy="12" r="3"/>
    </svg>
  ),
  gaze: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10"/>
      <circle cx="12" cy="12" r="4"/>
      <line x1="12" y1="2" x2="12" y2="6"/>
      <line x1="12" y1="18" x2="12" y2="22"/>
      <line x1="2" y1="12" x2="6" y2="12"/>
      <line x1="18" y1="12" x2="22" y2="12"/>
    </svg>
  ),
  analysis: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
    </svg>
  ),
  eyefeatures: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 12s3-8 10-8 10 8 10 8-3 8-10 8-10-8-10-8z"/>
      <circle cx="12" cy="12" r="3"/>
      <line x1="12" y1="16" x2="12" y2="21"/>
      <line x1="8" y1="17" x2="6" y2="21"/>
      <line x1="16" y1="17" x2="18" y2="21"/>
    </svg>
  ),
  multimodal: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="2" width="9" height="9" rx="1"/>
      <rect x="13" y="2" width="9" height="9" rx="1"/>
      <rect x="2" y="13" width="9" height="9" rx="1"/>
      <rect x="13" y="13" width="9" height="9" rx="1"/>
    </svg>
  ),
  viz3d: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2L2 7l10 5 10-5-10-5z"/>
      <path d="M2 17l10 5 10-5"/>
      <path d="M2 12l10 5 10-5"/>
    </svg>
  ),
}

const NAV = [
  { id: 'info',        label: 'Subject Info' },
  { id: 'eeg',         label: 'EEG'          },
  { id: 'video',       label: 'Video Sync'   },
  { id: 'blinks',      label: 'Blink Atlas'  },
  { id: 'gaze',        label: 'Gaze'         },
  { id: 'analysis',    label: 'Analysis'     },
  { id: 'eyefeatures', label: 'Eye Features' },
  { id: 'multimodal',  label: 'Multimodal'   },
  { id: 'viz3d',       label: '3D View'      },
]

export default function Sidebar({ activeTab, setActiveTab }) {
  const { subjectId, sessionId, paradigm, clearRecording } = useStore()

  return (
    <aside className="sidebar">
      {/* Brand */}
      <div className="brand">
        <div className="logo-box">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
            <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
            <circle cx="12" cy="12" r="3"/>
          </svg>
        </div>
        <div className="brand-name">
          Iris
          <small>Eye · BCI · EEG</small>
        </div>
      </div>

      {/* Active recording chip */}
      <div style={{ padding: '6px 8px 10px', borderBottom: '1px solid var(--sb-hair)', marginBottom: 8 }}>
        <div style={{ fontSize: 9, fontWeight: 700, textTransform: 'uppercase',
                      letterSpacing: '.1em', color: 'rgba(255,255,255,.3)', marginBottom: 5 }}>
          Recording
        </div>
        <div style={{ fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--pri)',
                      fontWeight: 600, marginBottom: 6, overflow: 'hidden',
                      textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {subjectId} · {sessionId?.replace(/^.*_/, '')} · {paradigm}
        </div>
        <button
          onClick={clearRecording}
          style={{
            width: '100%', padding: '5px 0', borderRadius: 7, border: '1px solid var(--hair-2)',
            background: 'transparent', fontSize: 10.5, color: 'var(--ink-3)',
            cursor: 'pointer', transition: 'all .12s', fontWeight: 500,
          }}
          onMouseEnter={e => { e.target.style.background = 'var(--sb-hover)'; e.target.style.color = 'var(--ink)' }}
          onMouseLeave={e => { e.target.style.background = 'transparent'; e.target.style.color = 'var(--ink-3)' }}
        >
          ← Change recording
        </button>
      </div>

      <div className="nav-section-label">Modules</div>

      {NAV.map(n => (
        <button
          key={n.id}
          className={`nav-btn ${activeTab === n.id ? 'active' : ''}`}
          onClick={() => setActiveTab(n.id)}
          aria-label={n.label}
          aria-current={activeTab === n.id ? 'page' : undefined}
        >
          <span className="ico">{ICONS[n.id]}</span>
          <span className="lbl">{n.label}</span>
        </button>
      ))}
    </aside>
  )
}
