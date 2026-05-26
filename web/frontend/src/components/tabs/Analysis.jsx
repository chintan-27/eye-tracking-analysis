import React, { useState } from 'react'
import { useStore } from '../../store'
import { useErp, usePsd, useTrials } from '../../api/hooks'
import ErpChart from '../charts/ErpChart'
import PsdChart from '../charts/PsdChart'

const ERP_PRESETS = [
  { label:'Parietal', channels:'CZ,CPZ,PZ' },
  { label:'Motor', channels:'C3,CZ,C4' },
  { label:'Frontal', channels:'FZ,FCZ,CZ' },
  { label:'Occipital', channels:'O1,OZ,O2' },
]
const REGIONS = ['Frontal','Central','Parietal','Occipital','Temporal']

export default function Analysis() {
  const { recId, updateEeg } = useStore()
  const [erpChs, setErpChs] = useState('CZ,CPZ,PZ')
  const [psdReg, setPsdReg] = useState('Central')

  const { data: erp, isLoading: erpLoading } = useErp(recId, erpChs)
  const { data: psd, isLoading: psdLoading } = usePsd(recId, psdReg)
  const { data: trialsData } = useTrials(recId)
  const trials = trialsData?.trials || []

  return (
    <div style={{display:'flex',flexDirection:'column',gap:10}}>
      <div className="card-row">
        {/* ERP */}
        <div className="card" style={{flex:1,minWidth:0}}>
          <div className="card-hd">
            <div className="card-hd-l">
              <div className="card-title">Brain Response to Stimuli (ERP)</div>
              <div className="card-sub">Average epochs · baseline −200ms to 0ms · SEM shading</div>
            </div>
            <div className="pill-grp">
              {ERP_PRESETS.map(p=><button key={p.label} className={`pill ${erpChs===p.channels?'active':''}`} onClick={()=>setErpChs(p.channels)}>{p.label}</button>)}
            </div>
          </div>
          <div className="card-body">
            <div className="explain-box"><strong>What you're seeing:</strong> The average brain response across all trials of each stimulus type. Signal is baseline-corrected to zero at −200–0ms. A positive peak ~300ms (P300) reflects stimulus recognition.</div>
            {erpLoading ? <div className="loading"><div className="spin"/>Computing ERP…</div> : <ErpChart data={erp} height={260} />}
            {erp && <div style={{fontSize:'10.5px',color:'var(--ink-3)',marginTop:6}}>Channels: {erp.channels?.join(', ')}</div>}
          </div>
        </div>

        {/* PSD */}
        <div className="card" style={{flex:1,minWidth:0}}>
          <div className="card-hd">
            <div className="card-hd-l">
              <div className="card-title">Brain Frequency Content (PSD)</div>
              <div className="card-sub">Welch method · full session · hover for frequency + power</div>
            </div>
            <div className="pill-grp">
              {REGIONS.map(r=><button key={r} className={`pill ${psdReg===r?'active':''}`} onClick={()=>setPsdReg(r)}>{r}</button>)}
            </div>
          </div>
          <div className="card-body">
            <div className="explain-box"><strong>Reading this:</strong> Each band is a brain rhythm. A prominent <strong>alpha peak (8–13Hz)</strong> is normal and rises when relaxed. <strong>Beta (13–30Hz)</strong> increases during focus. Alpha peak frequency slows with fatigue.</div>
            {psdLoading ? <div className="loading"><div className="spin"/>Computing PSD…</div> : <PsdChart data={psd} height={248} />}
          </div>
        </div>
      </div>

      {/* Trial table */}
      <div className="card">
        <div className="card-hd">
          <div className="card-title">All Trials</div>
          <div className="card-sub">{trials.length} trials · click to seek EEG viewer</div>
        </div>
        <div style={{maxHeight:240,overflowY:'auto'}}>
          <table className="trial-table">
            <thead><tr><th>#</th><th>Cue</th><th>Start</th><th>Duration</th><th>Missed</th></tr></thead>
            <tbody>
              {trials.map(t=>(
                <tr key={t.trial_id} onClick={()=>updateEeg({tStart:Math.max(0,(t.start_s||0)-.5)})}>
                  <td style={{fontFamily:'JetBrains Mono',color:'var(--ink-3)'}}>{t.trial_number}</td>
                  <td style={{fontWeight:600}}>{t.cue}</td>
                  <td style={{fontFamily:'JetBrains Mono',textAlign:'right'}}>{t.start_s?.toFixed(2)}s</td>
                  <td style={{fontFamily:'JetBrains Mono',textAlign:'right'}}>{t.duration_s?.toFixed(2)}s</td>
                  <td style={{textAlign:'center',color:'var(--acc)'}}>{t.missed?'●':'—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
