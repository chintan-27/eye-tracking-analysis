import React, { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'

const BANDS = [
  { name:'Delta', lo:1, hi:4, color:'rgba(107,127,176,.2)', desc:'Deep sleep' },
  { name:'Theta', lo:4, hi:8, color:'rgba(212,165,116,.2)', desc:'Memory' },
  { name:'Alpha', lo:8, hi:13, color:'rgba(85,168,124,.3)', desc:'Relaxed / idle' },
  { name:'Beta',  lo:13,hi:30, color:'rgba(181,128,168,.2)', desc:'Focused / active' },
  { name:'Gamma', lo:30,hi:80, color:'rgba(86,137,168,.15)', desc:'Attention' },
]
const REG_COL = { Frontal:'#5B70A8', Central:'#55A87C', Parietal:'#9B67A0', Occipital:'#4A7DA0', Temporal:'#C49055' }

export default function PsdChart({ data, height = 260 }) {
  const option = useMemo(() => {
    if (!data?.freqs?.length) return null
    const { freqs, power_db: power, region } = data
    const col = REG_COL[region] || '#55A87C'

    // Alpha peak
    const alphaMask = freqs.map((f,i) => f>=7&&f<=14?i:-1).filter(i=>i>=0)
    let peakPt = null
    if (alphaMask.length) {
      const pi = alphaMask.reduce((b,i) => power[i]>power[b]?i:b, alphaMask[0])
      peakPt = { coord: [freqs[pi], power[pi]], name: `α ${freqs[pi].toFixed(1)}Hz` }
    }

    const markAreas = BANDS.map(b => ([
      { xAxis: b.lo, itemStyle:{ color: b.color }, label:{ show:true, position:'insideTop', formatter:b.name+'\n'+b.desc, fontSize:9, color:'rgba(17,19,24,.5)', lineHeight:14 } },
      { xAxis: b.hi }
    ]))

    return {
      animation: false,
      backgroundColor: 'transparent',
      grid: { left:58, right:10, top:16, bottom:36 },
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(17,19,24,.92)', borderColor:'transparent',
        textStyle: { color:'#fff', fontSize:11 },
        formatter: (params) => {
          const f = params[0]?.axisValue
          return `<b>${Number(f).toFixed(1)} Hz</b><br/>${Number(params[0]?.value[1]).toFixed(1)} dB/Hz`
        }
      },
      xAxis: {
        type: 'log', min: 1, max: 80, name: 'Frequency (Hz)', nameLocation:'end', nameTextStyle:{fontSize:10},
        axisLabel: { formatter: v => [1,2,4,8,13,20,30,50,80].includes(v)?`${v}Hz`:'', fontSize:10 },
        splitLine: { lineStyle:{color:'rgba(17,19,24,.05)'} },
      },
      yAxis: {
        type: 'value', name: 'dB/Hz', nameTextStyle:{fontSize:10},
        axisLabel: { formatter:v=>v.toFixed(0), fontSize:10 },
        splitLine: { lineStyle:{color:'rgba(17,19,24,.05)'} },
      },
      series: [{
        type: 'line', symbol: 'none',
        lineStyle: { color: col, width: 2 },
        areaStyle: { color: col, opacity: .08 },
        data: freqs.map((f,i) => [f, power[i]]),
        markArea: { silent:true, data: markAreas },
        markPoint: peakPt ? {
          data: [{ ...peakPt, symbol:'circle', symbolSize:8, itemStyle:{color:col}, label:{formatter:peakPt.name, fontSize:9, position:'top'} }]
        } : undefined,
      }]
    }
  }, [data])

  if (!option) return <div className="loading"><div className="spin"/>No PSD data</div>
  return <ReactECharts option={option} style={{height}} opts={{renderer:'canvas'}} />
}
