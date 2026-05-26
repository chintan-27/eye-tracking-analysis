import React, { useState } from 'react'
import { useStore } from '../../store'
import { useBlinks } from '../../api/hooks'
import ReactECharts from 'echarts-for-react'

const AL_COL = {1:'#6DB87A',2:'#E8B840',3:'#E07A36',4:'#CC3F3A'}

function SparkLine({ recId, blinkId, tPeak }) {
  const [opt, setOpt] = useState(null)
  React.useEffect(() => {
    if (!recId) return
    fetch(`/api/eeg/${recId}/window?t_start_s=${tPeak-0.6}&t_end_s=${tPeak+0.6}&channels=FP1&band=raw&scale=raw`)
      .then(r=>r.json()).then(d=>{
        const ch = d.channels?.[0]
        if (!ch) return
        const y = ch.y.map((v,i,a)=>v-(a.reduce((s,x)=>s+x,0)/a.length))
        const s = Math.max(10, [...y].map(Math.abs).sort((a,b)=>a-b)[Math.floor(y.length*.95)])
        setOpt({
          animation:false, grid:{left:0,right:0,top:0,bottom:0},
          xAxis:{type:'value',show:false,min:d.times[0],max:d.times[d.times.length-1]},
          yAxis:{type:'value',show:false,min:-s,max:s},
          series:[{type:'line',symbol:'none',lineStyle:{color:'#E76F51',width:1.5},data:d.times.map((t,i)=>[t,y[i]])}]
        })
      }).catch(()=>{})
  }, [recId, blinkId])
  if (!opt) return <div style={{height:36,background:'var(--bg)',borderRadius:4}}/>
  return <ReactECharts option={opt} style={{height:36}} opts={{renderer:'canvas'}} />
}

export default function BlinkAtlas() {
  const { recId } = useStore()
  const { data, isLoading } = useBlinks(recId)
  const [filter, setFilter] = useState('all')
  const [sort, setSort] = useState('time')
  const [selected, setSelected] = useState(null)
  const [detail, setDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const blinks = React.useMemo(() => {
    if (!data?.blinks) return []
    let b = [...data.blinks]
    if (filter==='video') b=b.filter(x=>x.in_video)
    if (filter==='strong') b=b.filter(x=>Math.abs(x.fp1_peak_uv||0)>=100)
    if (sort==='amplitude') b.sort((a,z)=>Math.abs(z.fp1_peak_uv||0)-Math.abs(a.fp1_peak_uv||0))
    return b
  }, [data, filter, sort])

  const openDetail = async (b) => {
    setSelected(b.id); setDetail(null); setDetailLoading(true)
    try {
      const d = await fetch(`/api/video/${recId}/blinks/${b.id}/detail`).then(r=>r.json())
      setDetail(d)
    } catch(e) {}
    setDetailLoading(false)
  }

  const fps = useStore(s=>s.video.fps) || 153
  const startF = useStore(s=>s.video.startFrame) || 0

  if (isLoading) return <div className="loading"><div className="spin"/>Scanning video for blinks (~10s first load)…</div>

  return (
    <div style={{display:'flex',flexDirection:'column',gap:10}}>
      <div className="card">
        <div className="card-hd">
          <div className="card-hd-l">
            <div className="card-title">Blink Atlas</div>
            <div className="card-sub">{blinks.length} blinks · video-confirmed closed-eye frames</div>
          </div>
          <div className="ctrl-row">
            <span className="ctrl-lbl">Filter:</span>
            <div className="pill-grp">
              {[['all','All'],['video','In-video'],['strong','Strong >100µV']].map(([v,l])=>(
                <button key={v} className={`pill ${filter===v?'active':''}`} onClick={()=>setFilter(v)}>{l}</button>
              ))}
            </div>
            <div className="ctrl-sep"/>
            <span className="ctrl-lbl">Sort:</span>
            <div className="pill-grp">
              {[['time','Time'],['amplitude','Amplitude']].map(([v,l])=>(
                <button key={v} className={`pill ${sort===v?'active':''}`} onClick={()=>setSort(v)}>{l}</button>
              ))}
            </div>
          </div>
        </div>
        <div className="card-body">
          <div className="blink-grid">
            {blinks.map(b => {
              const cf = b.closed_frame ?? b.phan_frame
              const off = Math.round((cf - b.phan_frame) / fps * 1000)
              const amp = Math.abs(b.fp1_peak_uv||0)
              const ampPct = Math.min(100, amp/3)
              const ampCol = amp>=150?'var(--pri)':amp>=100?'#E8B840':'var(--ink-3)'
              return (
                <div key={b.id} className={`blink-card ${b.in_video?'':'eeg-only'} ${selected===b.id?'selected':''}`} onClick={()=>openDetail(b)}>
                  <div className="bc-frames">
                    {b.in_video ? [cf-Math.round(fps*.07), cf, cf+Math.round(fps*.07)].map((f,i)=>(
                      <img key={i} src={`/api/video/${recId}/frame?n=${Math.max(0,f)}`} loading="lazy"
                        style={{flex:1,objectFit:'contain',background:'#111',outline:i===1?'1.5px solid #55A87C':''}}
                        title={i===0?'before':i===1?`closed (${off>0?'+':''}${off}ms)`:'after'} />
                    )) : <div style={{flex:1,display:'grid',placeItems:'center',color:'#555',fontSize:10}}>no video</div>}
                  </div>
                  <SparkLine recId={recId} blinkId={b.id} tPeak={b.t_peak_s} />
                  <div style={{display:'flex',justifyContent:'space-between',marginTop:6,fontSize:'10px'}}>
                    <span style={{background:b.trial?'var(--pri-soft)':'var(--bg)',color:b.trial?'var(--pri-ink)':'var(--ink-3)',borderRadius:4,padding:'1px 6px',fontWeight:600}}>
                      {b.trial?`T${b.trial.trial_number}·${b.trial.cue}`:'—'}
                    </span>
                    <span style={{color:'var(--ink-3)',fontFamily:'JetBrains Mono'}}>{b.in_video?(b.video_t_s||0).toFixed(2)+'s':'EEG'}</span>
                  </div>
                  <div style={{display:'flex',justifyContent:'space-between',marginTop:3,fontSize:'9.5px'}}>
                    <span style={{fontFamily:'JetBrains Mono',color:'var(--ink-3)'}}>FP1 {(b.fp1_peak_uv||0)>0?'+':''}{Math.round(b.fp1_peak_uv||0)}µV</span>
                    <span style={{color:b.sync_quality==='exact'?'var(--pri)':'var(--ink-3)'}}>{b.sync_quality==='exact'?'✓ synced':'~ eeg'}</span>
                  </div>
                  <div style={{height:2,background:'var(--hair-2)',borderRadius:1,marginTop:5}}>
                    <div style={{height:2,width:ampPct+'%',background:ampCol,borderRadius:1}}/>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {/* Detail view */}
      {(selected!=null||detailLoading) && (
        <div className="card">
          <div className="card-hd">
            <div className="card-hd-l">
              <div className="card-title">Blink Detail</div>
              <div className="card-sub">{detail?.blink?.trial?`Trial ${detail.blink.trial.trial_number} · ${detail.blink.trial.cue}`:'Between trials'}</div>
            </div>
            <button className="pill" style={{marginLeft:'auto'}} onClick={()=>{setSelected(null);setDetail(null)}}>✕ Close</button>
          </div>
          <div className="card-body">
            {detailLoading && <div className="loading"><div className="spin"/>Loading…</div>}
            {detail && <>
              {/* Filmstrip */}
              <div style={{display:'flex',gap:4,overflowX:'auto',paddingBottom:8,marginBottom:14}}>
                {(detail.video_frames||[]).map((f,i)=>(
                  <img key={i} src={`/api/video/${recId}/frame?n=${f}`} loading="lazy"
                    style={{height:80,borderRadius:4,background:'#111',outline:f===(detail.blink?.closed_frame)?'2px solid #55A87C':''}} />
                ))}
              </div>
              {/* EEG chart */}
              {detail.eeg_channels?.length > 0 && (() => {
                const chartData = {
                  times: detail.times,
                  channels: detail.eeg_channels.map(ch=>({...ch,region:'Unknown',color:'#55A87C'})),
                  blink_times: [detail.blink?.t_peak_s].filter(Boolean),
                  events:[]
                }
                return <EegChartInline data={chartData} tPeak={detail.blink?.t_peak_s} />
              })()}
              {/* Aperture */}
              {detail.aperture && <ApertureChart data={detail.aperture} peakFrame={detail.blink?.closed_frame} />}
            </>}
          </div>
        </div>
      )}
    </div>
  )
}

// Inline EEG chart for blink detail (1.2s window)
function EegChartInline({ data, tPeak }) {
  const option = React.useMemo(() => {
    if (!data?.channels?.length) return null
    const { times, channels, blink_times } = data
    const OFFSET = 3.0
    const processed = channels.map((ch,i) => {
      const m = ch.y.reduce((a,b)=>a+b,0)/ch.y.length
      const y = ch.y.map(v=>v-m)
      const s = [...y].map(Math.abs).sort((a,b)=>a-b)[Math.floor(y.length*.95)]||10
      const normed = y.map(v=>Math.max(-1.4,Math.min(1.4,v/s))+i*OFFSET)
      return {...ch,normed,scale:s}
    })
    const REG_COL = {FP1:'#E76F51',FZ:'#5B70A8',CZ:'#55A87C',CPZ:'#9B67A0',OZ:'#4A7DA0'}
    return {
      animation:false, backgroundColor:'transparent',
      grid:{left:52,right:10,top:10,bottom:40},
      tooltip:{trigger:'axis',backgroundColor:'rgba(17,19,24,.92)',borderColor:'transparent',textStyle:{color:'#fff',fontSize:11},
        formatter:p=>{const t=p[0]?.axisValue;let h=`<b>${((Number(t)-tPeak)*1000).toFixed(0)}ms</b><br/>`;p.forEach((x,i)=>{const c=processed[x.seriesIndex];if(c)h+=`<span style="color:${REG_COL[c.name]||'#888'}">${c.name}</span>: ${((x.value[1]-i*OFFSET)*c.scale).toFixed(1)}µV<br/>`;});return h}},
      xAxis:{type:'value',min:times[0],max:times[times.length-1],axisLabel:{formatter:v=>`${((v-tPeak)*1000).toFixed(0)}ms`,fontSize:10},splitLine:{lineStyle:{color:'rgba(17,19,24,.05)'}}},
      yAxis:{type:'value',min:-OFFSET,max:(channels.length-1)*OFFSET+OFFSET,axisLabel:{formatter:v=>{const i=Math.round(v/OFFSET);return channels[i]?.name||''},fontSize:10,color:v=>{const i=Math.round(v/OFFSET);return REG_COL[channels[i]?.name]||'transparent'}},splitLine:{show:false},axisLine:{show:false},axisTick:{show:false}},
      series:processed.map((ch,i)=>({
        name:ch.name,type:'line',symbol:'none',
        lineStyle:{color:REG_COL[ch.name]||'#888',width:ch.name==='FP1'?2:1.3},
        data:times.map((t,j)=>[t,ch.normed[j]]),
        markLine:i===0&&tPeak?{silent:true,symbol:'none',data:[{xAxis:tPeak,lineStyle:{color:'rgba(231,111,81,.7)',width:1.5,type:'dashed'},label:{formatter:'peak',fontSize:9}}]}:undefined,
      }))
    }
  }, [data, tPeak])
  if (!option) return null
  return <ReactECharts option={option} style={{height:300}} opts={{renderer:'canvas'}} />
}

function ApertureChart({ data, peakFrame }) {
  const option = React.useMemo(() => {
    if (!data?.frames?.length) return null
    const { frames, aperture_mm } = data
    return {
      animation:false, backgroundColor:'transparent',
      grid:{left:52,right:10,top:8,bottom:36},
      tooltip:{trigger:'axis',backgroundColor:'rgba(17,19,24,.92)',borderColor:'transparent',textStyle:{color:'#fff',fontSize:11},formatter:p=>`Frame ${p[0]?.axisValue}: ${Number(p[0]?.value[1]).toFixed(2)}mm`},
      xAxis:{type:'value',min:frames[0],max:frames[frames.length-1],axisLabel:{fontSize:10},splitLine:{lineStyle:{color:'rgba(17,19,24,.05)'}}},
      yAxis:{type:'value',name:'Aperture (mm)',nameTextStyle:{fontSize:10},min:0,axisLabel:{fontSize:10},splitLine:{lineStyle:{color:'rgba(17,19,24,.05)'}}},
      series:[{type:'line',symbol:'none',lineStyle:{color:'#55A87C',width:2},areaStyle:{color:'#55A87C',opacity:.12},data:frames.map((f,i)=>[f,aperture_mm[i]]),markLine:peakFrame?{silent:true,symbol:'none',data:[{xAxis:peakFrame,lineStyle:{color:'rgba(231,111,81,.7)',type:'dashed',width:1.5},label:{formatter:'peak'}}]}:undefined}]
    }
  }, [data, peakFrame])
  if (!option) return null
  return <>
    <div style={{fontSize:11,color:'var(--ink-3)',margin:'10px 0 4px'}}>Eyelid aperture (mm) · state=2 (closed) at center</div>
    <ReactECharts option={option} style={{height:100}} opts={{renderer:'canvas'}} />
  </>
}
