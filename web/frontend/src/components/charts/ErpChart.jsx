import React, { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'

const COLORS = ['#55A87C','#E76F51','#5B70A8','#C49055','#9B67A0']

export default function ErpChart({ data, height = 280 }) {
  const option = useMemo(() => {
    if (!data?.erps?.length) return null
    const { erps, channels } = data

    let yMin = Infinity, yMax = -Infinity
    erps.forEach(e => e.mean.forEach((v,i) => {
      yMin = Math.min(yMin, v - e.sem[i])
      yMax = Math.max(yMax, v + e.sem[i])
    }))
    const pad = (yMax - yMin) * 0.12 || 1
    yMin -= pad; yMax += pad

    const series = []
    erps.forEach((erp, ei) => {
      const col = COLORS[ei % COLORS.length]
      const times = erp.time_ms
      // SEM band (upper)
      series.push({
        name: erp.cue + '_upper',
        type: 'line', symbol: 'none', silent: true,
        lineStyle: { opacity: 0 },
        areaStyle: { color: col, opacity: .15 },
        stack: `sem_${ei}`,
        data: times.map((t,i) => [t, erp.mean[i] + erp.sem[i]]),
        tooltip: { show: false }
      })
      // SEM band (lower gap)
      series.push({
        name: erp.cue + '_lower',
        type: 'line', symbol: 'none', silent: true,
        lineStyle: { opacity: 0 },
        areaStyle: { color: '#fff', opacity: 1 },
        stack: `sem_${ei}`,
        data: times.map((t,i) => [t, erp.mean[i] - erp.sem[i]]),
        tooltip: { show: false }
      })
      // Mean trace
      series.push({
        name: erp.cue,
        type: 'line', symbol: 'none',
        lineStyle: { color: col, width: 2 },
        data: times.map((t,i) => [t, erp.mean[i]]),
        markLine: ei === 0 ? {
          silent: true, symbol: 'none',
          data: [{ xAxis: 0, label: { formatter: 'onset', fontSize: 9 }, lineStyle: { color:'rgba(17,19,24,.3)', type:'dashed', width:1.5 } }]
        } : undefined,
      })
    })

    return {
      animation: false,
      backgroundColor: 'transparent',
      grid: { left:52, right:10, top:24, bottom:36 },
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(17,19,24,.92)', borderColor:'transparent',
        textStyle: { color:'#fff', fontSize:11 },
        formatter: (params) => {
          const t = params[0]?.axisValue
          let html = `<b>${Number(t).toFixed(0)}ms</b><br/>`
          params.filter(p=>!p.seriesName.includes('_')).forEach(p => {
            html += `<span style="color:${p.color}">${p.seriesName}</span>: ${Number(p.value[1]).toFixed(2)}µV<br/>`
          })
          return html
        }
      },
      legend: {
        top: 0, right: 10, textStyle:{fontSize:10},
        data: erps.map((e,i) => ({ name: e.cue, itemStyle:{ color: COLORS[i%COLORS.length] } }))
      },
      xAxis: {
        type: 'value', min: -200, max: 600, name: 'Time (ms)', nameLocation:'end', nameTextStyle:{fontSize:10},
        axisLabel: { fontSize:10 },
        splitLine: { lineStyle:{color:'rgba(17,19,24,.05)'} },
        axisLine: { lineStyle:{color:'rgba(17,19,24,.15)'} },
      },
      yAxis: {
        type: 'value', min: yMin, max: yMax, name: 'µV', nameTextStyle:{fontSize:10},
        axisLabel: { formatter:v=>v.toFixed(1), fontSize:10 },
        splitLine: { lineStyle:{color:'rgba(17,19,24,.05)'} },
      },
      series,
    }
  }, [data])

  if (!option) return <div className="loading"><div className="spin"/>No ERP data</div>
  return <ReactECharts option={option} style={{height}} opts={{renderer:'canvas'}} />
}
