import React, { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'

export default function PupilChart({ data, events=[], height=160 }) {
  const option = useMemo(() => {
    if (!data?.times_s?.length) return null
    const { times_s, pupil_left, pupil_right } = data
    const allValid = [...(pupil_left||[]), ...(pupil_right||[])].filter(v=>v!=null)
    const yMin = allValid.length ? Math.min(...allValid)-.2 : 0
    const yMax = allValid.length ? Math.max(...allValid)+.2 : 8

    return {
      animation: false, backgroundColor:'transparent',
      grid: { left:48, right:10, top:12, bottom:36 },
      legend: { bottom:28, textStyle:{fontSize:10}, data:['Left','Right'] },
      tooltip: {
        trigger:'axis', backgroundColor:'rgba(17,19,24,.92)', borderColor:'transparent',
        textStyle:{color:'#fff',fontSize:11},
        formatter: p => `<b>${Number(p[0]?.axisValue).toFixed(2)}s</b><br/>${p.map(s=>`<span style="color:${s.color}">${s.seriesName}</span>: ${Number(s.value[1]).toFixed(2)}mm`).join('<br/>')}`
      },
      toolbox:{right:10,top:0,feature:{dataZoom:{yAxisIndex:'none'},restore:{}}},
      dataZoom:[{type:'inside'},{type:'slider',height:18,bottom:8,borderColor:'transparent',fillerColor:'rgba(26,122,74,.2)'}],
      xAxis: {type:'value', min:times_s[0], max:times_s[times_s.length-1], axisLabel:{formatter:v=>v.toFixed(0)+'s',fontSize:10}, splitLine:{lineStyle:{color:'rgba(17,19,24,.05)'}}},
      yAxis: {type:'value', min:yMin, max:yMax, name:'mm', nameTextStyle:{fontSize:10}, axisLabel:{formatter:v=>v.toFixed(1),fontSize:10}, splitLine:{lineStyle:{color:'rgba(17,19,24,.05)'}}},
      series: [
        { name:'Left',  type:'line', symbol:'none', lineStyle:{color:'#5B70A8',width:1.5}, data: times_s.map((t,i)=>[t, pupil_left?.[i]]) },
        { name:'Right', type:'line', symbol:'none', lineStyle:{color:'#55A87C',width:1.5}, data: times_s.map((t,i)=>[t, pupil_right?.[i]]) },
      ]
    }
  }, [data, events])

  if (!option) return <div className="loading"><div className="spin"/>No pupil data</div>
  return <ReactECharts option={option} style={{height}} opts={{renderer:'canvas'}} />
}
