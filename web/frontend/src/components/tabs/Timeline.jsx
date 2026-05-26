import React from 'react'
import { useStore } from '../../store'

export default function Timeline() {
  const recId = useStore(s => s.recId)
  return (
    <div className="card">
      <div className="card-hd"><div className="card-title">Timeline</div></div>
      <div className="card-body">
        <div className="loading">Migrating from index.html… recId: {recId}</div>
      </div>
    </div>
  )
}
