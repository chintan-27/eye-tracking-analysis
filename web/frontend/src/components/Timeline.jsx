import React from 'react'
import { useStore } from '../store'
import { useTimeline } from '../api/hooks'

export default function Timeline() {
  const recId = useStore(s => s.recId)
  const { data } = useTimeline(recId)
  if (!data) return null
  return (
    <div id="timelineStrip" style={{ flexShrink: 0 }}>
      <div style={{ fontSize: 10, color: 'var(--ink-3)', padding: '0 2px 3px' }}>
        Session Timeline · {data.n_blinks} blinks · {data.trials?.length} trials ·{' '}
        <span style={{ color: data.sync_quality === 'synchronized' ? 'var(--pri)' : 'var(--acc)', fontWeight: 600 }}>
          {data.sync_quality === 'synchronized' ? '✓ Synchronized' : '⚠ ' + data.sync_quality}
        </span>
      </div>
    </div>
  )
}
