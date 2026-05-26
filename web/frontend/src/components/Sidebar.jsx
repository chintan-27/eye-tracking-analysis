import React from 'react'
import { useStore } from '../store'

const ICONS = {
  home: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>
      <rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>
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
}

const NAV = [
  { id: 'home',     label: 'Subjects' },
  { id: 'eeg',      label: 'EEG' },
  { id: 'video',    label: 'Video Sync' },
  { id: 'blinks',   label: 'Blink Atlas' },
  { id: 'gaze',     label: 'Gaze' },
  { id: 'analysis', label: 'Analysis' },
]

export default function Sidebar({ activeTab, showTab }) {
  const recId = useStore(s => s.recId)
  return (
    <aside className="sidebar">
      <div className="brand" onClick={() => showTab('home')}>
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

      <div className="nav-section-label">Modules</div>

      {NAV.map(n => (
        <button
          key={n.id}
          className={`nav-btn ${activeTab === n.id ? 'active' : ''}`}
          onClick={() => showTab(n.id)}
          disabled={!recId && n.id !== 'home'}
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
