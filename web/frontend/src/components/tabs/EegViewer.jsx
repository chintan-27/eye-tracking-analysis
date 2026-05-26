import React, { useState, useCallback } from 'react'
import { useStore } from '../../store'
import { useEegWindow, useEegMinimap, useEegEvents } from '../../api/hooks'
import EegChart from '../charts/EegChart'
import ReactECharts from 'echarts-for-react'

const REGIONS = { Frontal:'FP1,FPZ,FP2,AF3,F7,F5,F3,FZ,F2,AF4', Central:'F4,F8,FC5,FC3,FC1,FCZ,FC2,FC4,FC6,CZ', Parietal:'CP3,CP1,CPZ,CP2,CP4,P3,P1,PZ,P2,P4', Temporal:'T7,C5,C3,C1,C2,C4,C6,T8,TP7,TP8', Occipital:'PO3,POZ,PO4,O1,OZ,O2,CB1,CB2' }
const BANDS = ['raw','delta','theta','alpha','beta','gamma']
const MODES = ['separate','butterfly']

export default function EegViewer() {
  const { recId, eeg, updateEeg, tCurrent, tFollow } = useStore()
  const { tStart, win, region, band, mode } = eeg
  const [activeRegion, setActiveRegion] = useState(region)

  const channels = mode === 'separate' || mode === 'butterfly'
    ? Object.values(REGIONS).join(',')
    : REGIONS[region]

  const { data, isLoading, error } = useEegWindow(recId, tStart, win, band, channels)
  const { data: mm } = useEegMinimap(recId)
  const { data: evData } = useEegEvents(recId)

  const events = evData?.events || []
  const blinks = data?.blink_times || []
  const duration = mm?.duration_s || 0

  // Build ECharts data per-region for separate mode
  const regionData = React.useMemo(() => {
    if (!data?.regions && !data?.channels) return []
    if (data.regions) return data.regions
    // channels mode — group by region
    return []
  }, [data])

  // Minimap ECharts option
  const mmOption = React.useMemo(() => {
    if (!mm?.envelope) return null
    const env = mm.envelope
    const dur = mm.duration_s
    const winStart = tStart, winEnd = tStart + win
    return {
      animation:false, backgroundColor:'transparent',
      grid:{left:0,right:0,top:0,bottom:0},
      tooltip:{ show:false },
      xAxis:{type:'value',min:0,max:dur,show:false},
      yAxis:{type:'value',show:false},
      series:[
        { type:'bar', barWidth:'100%', itemStyle:{color:'rgba(85,168,124,.5)'},
          data:env.map((v,i)=>[dur*i/env.length,v]) },
        { type:'line', symbol:'none', lineStyle:{color:'rgba(17,19,24,.6)',width:2},
          areaStyle:{color:'rgba(17,19,24,.18)'},
          data:[[winStart,0],[winStart,1],[winEnd,1],[winEnd,0]] },
      ]
    }
  }, [mm, tStart, win])

  const handlePan = (dir) => updateEeg({ tStart: Math.max(0, tStart + dir * win * 0.5) })

  // Flatten channels for EegChart
  const chartData = React.useMemo(() => {
    if (!data) return null
    let chs = []
    if (data.channels) chs = data.channels
    else if (data.regions) chs = data.regions.flatMap(r => r.channels.map(c => ({...c, region:r.name, color:r.color})))
    return { times: data.times, channels: chs, blink_times: blinks, events }
  }, [data, blinks, events])

  return (
    <div className="card" style={{display:'flex',flexDirection:'column'}}>
      <div className="card-hd">
        <div className="card-hd-l">
          <div className="card-title">EEG Viewer</div>
          <div className="card-sub">Raw µV · demeaned · blink bands (−150ms / +200ms)</div>
        </div>
        <div className="ctrl-row">
          <div className="pill-grp">
            {MODES.map(m => <button key={m} className={`pill ${mode===m?'active':''}`} onClick={()=>updateEeg({mode:m})}>{m}</button>)}
          </div>
          <div className="ctrl-sep"/>
          {mode==='separate' && <div className="pill-grp">
            {Object.keys(REGIONS).map(r=><button key={r} className={`pill ${activeRegion===r?'active':''}`} onClick={()=>{setActiveRegion(r);updateEeg({region:r})}}>{r}</button>)}
          </div>}
          <div className="ctrl-sep"/>
          <div className="pill-grp">
            {BANDS.map(b=><button key={b} className={`pill ${band===b?'active':''}`} onClick={()=>updateEeg({band:b})}>{b==='raw'?'Raw':''+b[0].toUpperCase()+b.slice(1)}</button>)}
          </div>
        </div>
      </div>

      <div style={{padding:'0 0 8px', flexShrink:0}}>
        {error && <div className="error-msg">Error loading EEG: {error.message}</div>}
        {isLoading && <div className="loading" style={{minHeight:300}}><div className="spin"/>Loading EEG…</div>}
        {chartData && !isLoading && (
          <EegChart data={chartData} mode={mode} height={420} />
        )}
      </div>

      <div style={{borderTop:'1px solid var(--hair)',padding:'10px 18px 12px',flexShrink:0}}>
        <div className="ctrl-row" style={{marginBottom:8}}>
          <span className="ctrl-lbl">Window:</span>
          <div className="pill-grp">
            {[2,5,10,20].map(w=><button key={w} className={`pill ${win===w?'active':''}`} onClick={()=>updateEeg({win:w})}>{w}s</button>)}
          </div>
          <div className="ctrl-sep"/>
          <button className="pill" onClick={()=>handlePan(-1)}>◀ 1s</button>
          <button className="pill" onClick={()=>handlePan(1)}>1s ▶</button>
          <div className="ctrl-sep"/>
          <button className={`pill ${tFollow?'active':''}`} style={{background:tFollow?'var(--pri-soft)':''}} onClick={()=>useStore.getState().setTFollow(!tFollow)}>⟳ Follow</button>
        </div>
        {mmOption && (
          <div style={{cursor:'crosshair'}} onClick={e=>{
            const r=e.currentTarget.getBoundingClientRect()
            const f=(e.clientX-r.left)/r.width
            updateEeg({tStart:Math.max(0,f*duration-win/2)})
          }}>
            <ReactECharts option={mmOption} style={{height:40}} opts={{renderer:'canvas'}} />
          </div>
        )}
        <div style={{display:'flex',justifyContent:'space-between',fontSize:'10.5px',color:'var(--ink-3)',marginTop:2}}>
          <span>0s</span><span>{duration.toFixed(1)}s</span>
        </div>
      </div>
    </div>
  )
}
