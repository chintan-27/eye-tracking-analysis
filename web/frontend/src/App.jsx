import React, { useState } from 'react'
import { useStore } from './store'
import Sidebar from './components/Sidebar'
import SessionHeader from './components/SessionHeader'
import Timeline from './components/Timeline'
import SubjectGrid from './components/tabs/SubjectGrid'
import EegViewer from './components/tabs/EegViewer'
import VideoSync from './components/tabs/VideoSync'
import BlinkAtlas from './components/tabs/BlinkAtlas'
import GazeMap from './components/tabs/GazeMap'
import Analysis from './components/tabs/Analysis'
import './App.css'

export default function App() {
  const [activeTab, setActiveTab] = useState('home')
  const recId = useStore(s => s.recId)

  const showTab = (tab) => {
    if (!recId && tab !== 'home') return
    setActiveTab(tab)
  }

  return (
    <div className="app">
      <Sidebar activeTab={activeTab} showTab={showTab} />
      <div className="shell">
        <SessionHeader />
        {recId && <Timeline />}
        <main className="main">
          {activeTab === 'home'     && <SubjectGrid onSelect={() => setActiveTab('eeg')} />}
          {activeTab === 'eeg'      && <EegViewer />}
          {activeTab === 'video'    && <VideoSync />}
          {activeTab === 'blinks'   && <BlinkAtlas />}
          {activeTab === 'gaze'     && <GazeMap />}
          {activeTab === 'analysis' && <Analysis />}
        </main>
      </div>
    </div>
  )
}
