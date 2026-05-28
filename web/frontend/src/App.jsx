import React, { useState, lazy, Suspense } from 'react'
import { useStore } from './store'
import Sidebar from './components/Sidebar'
import SessionHeader from './components/SessionHeader'
import Timeline from './components/Timeline'
import SubjectGrid from './components/tabs/SubjectGrid'
import SubjectInfo from './components/tabs/SubjectInfo'
import EegViewer from './components/tabs/EegViewer'
import VideoSync from './components/tabs/VideoSync'
import BlinkAtlas from './components/tabs/BlinkAtlas'
import GazeMap from './components/tabs/GazeMap'
import Analysis from './components/tabs/Analysis'
import EyeFeatures from './components/tabs/EyeFeatures'
import MultimodalViewer from './components/tabs/MultimodalViewer'
import ErrorBoundary from './components/ErrorBoundary'
const Visualization3D = lazy(() => import('./components/tabs/Visualization3D'))
import './App.css'

export default function App() {
  const [activeTab, setActiveTab] = useState('info')
  const recId = useStore(s => s.recId)

  // When a subject is selected from the picker, land on Subject Info tab first
  const handleSubjectSelected = () => setActiveTab('info')

  // ── No recording selected: full-screen subject picker ─────────────────────
  if (!recId) {
    return (
      <div className="app-picker">
        <div className="picker-brand">
          <div className="logo-box" style={{ width: 40, height: 40, borderRadius: 12 }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 strokeWidth="2.5" strokeLinecap="round">
              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
              <circle cx="12" cy="12" r="3"/>
            </svg>
          </div>
          <div>
            <div style={{ fontWeight: 700, fontSize: 18, letterSpacing: '-.03em' }}>Iris</div>
            <div style={{ fontSize: 10, color: 'rgba(48,217,128,.75)', fontWeight: 500,
                          letterSpacing: '.08em', textTransform: 'uppercase' }}>
              Eye · BCI · EEG
            </div>
          </div>
        </div>
        <div className="picker-body">
          <SubjectGrid onSelect={handleSubjectSelected} />
        </div>
      </div>
    )
  }

  // ── Recording selected: full dashboard ─────────────────────────────────────
  return (
    <div className="app">
      <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} />
      <div className="shell">
        <SessionHeader />
        <Timeline />
        <main className="main">
          {activeTab === 'info'        && <SubjectInfo />}
          {activeTab === 'eeg'         && <EegViewer />}
          {activeTab === 'video'       && <VideoSync />}
          {activeTab === 'blinks'      && <BlinkAtlas />}
          {activeTab === 'gaze'        && <GazeMap />}
          {activeTab === 'analysis'    && <Analysis />}
          {activeTab === 'eyefeatures' && <EyeFeatures />}
          {activeTab === 'multimodal'  && (
            <ErrorBoundary key="multimodal">
              <MultimodalViewer />
            </ErrorBoundary>
          )}
          {activeTab === 'viz3d'       && (
            <ErrorBoundary key="viz3d">
              <Suspense fallback={<div className="loading"><div className="spin"/>Loading 3D…</div>}>
                <Visualization3D />
              </Suspense>
            </ErrorBoundary>
          )}
        </main>
      </div>
    </div>
  )
}
