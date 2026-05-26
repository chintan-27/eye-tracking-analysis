import React, { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'

const REG_COLOR = {
  Frontal:'#5B70A8', Central:'#55A87C', Temporal:'#C49055',
  Parietal:'#9B67A0', Occipital:'#4A7DA0', Unknown:'#888',
  FP1:'#E76F51', FPZ:'#E76F51',  // blink channel = coral
}

function demean(arr) {
  const m = arr.reduce((a,b)=>a+b,0)/arr.length
  return arr.map(v=>v-m)
}
function p95(arr) {
  const a=[...arr].map(Math.abs).sort((a,b)=>a-b)
  return a[Math.floor(a.length*.95)]||10
}

/**
 * EegChart — interactive stacked/butterfly EEG using Apache ECharts.
 *
 * Props:
 *   data: { times, channels:[{name,region,color,y}], blink_times, events }
 *   mode: 'stacked' | 'butterfly'
 *   height: number (px)
 */
export default function EegChart({ data, mode = 'stacked', height = 420, onTimeClick, cursor }) {
  const option = useMemo(() => {
    if (!data?.channels?.length || !data.times?.length) return null
    const { times, channels, blink_times = [], events = [] } = data

    if (mode === 'butterfly') {
      return makeButterflyOption(times, channels, blink_times, events, cursor)
    }
    return makeStackedOption(times, channels, blink_times, events, cursor)
  }, [data, mode, cursor])

  if (!option) return <div className="loading"><div className="spin"/>No data</div>

  return (
    <ReactECharts
      option={option}
      style={{ height }}
      opts={{ renderer: 'canvas' }}
      onEvents={{
        click: (p) => onTimeClick?.(p.value?.[0] ?? p.data?.[0])
      }}
    />
  )
}

function makeStackedOption(times, channels, blinkTimes, events, cursor) {
  const OFFSET = 3.0   // z-score units between channels
  const processed = channels.map((ch, i) => {
    const y = demean(ch.y)
    const s = p95(y) || 10
    const normed = y.map(v => Math.max(-1.4, Math.min(1.4, v/s)) + i * OFFSET)
    return { ...ch, normed, scale: s }
  })

  const blinkAreas = blinkTimes.flatMap(bt => [[{xAxis: bt-0.15},{xAxis: bt+0.2}]])
  const eventLines = events.map(ev => ({
    xAxis: ev.t_s,
    label: { formatter: ev.label, fontSize: 9, color: '#E76F51' },
    lineStyle: { color: '#E76F51', type: 'dashed', width: 1.2, opacity: .7 }
  }))
  if (cursor != null) {
    eventLines.push({
      xAxis: cursor,
      label: { formatter: '▶', fontSize: 10, color: '#2ec87a', position: 'end' },
      lineStyle: { color: '#2ec87a', width: 1.5, opacity: .9 }
    })
  }

  return {
    animation: false,
    backgroundColor: 'transparent',
    grid: { left: 58, right: 10, top: 10, bottom: 40, containLabel: false },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', label: { backgroundColor: '#111' } },
      backgroundColor: 'rgba(17,19,24,.92)',
      borderColor: 'transparent',
      textStyle: { color: '#fff', fontSize: 11 },
      formatter: (params) => {
        const t = params[0]?.axisValue
        let html = `<b>${Number(t).toFixed(3)}s</b><br/>`
        params.forEach(p => {
          const ch = processed[p.seriesIndex]
          if (!ch) return
          const raw = (p.data[1] - p.seriesIndex * OFFSET) * ch.scale
          html += `<span style="color:${ch.color||REG_COLOR[ch.region]||'#888'}">${ch.name}</span>: ${raw.toFixed(1)}µV<br/>`
        })
        return html
      }
    },
    toolbox: {
      right: 10, top: 5,
      feature: { dataZoom: { yAxisIndex: 'none' }, restore: {}, saveAsImage: {} }
    },
    dataZoom: [
      { type: 'inside', xAxisIndex: 0, filterMode: 'none' },
      { type: 'slider', xAxisIndex: 0, height: 20, bottom: 8, handleSize: '80%',
        borderColor: 'transparent', fillerColor: 'rgba(26,122,74,.2)' }
    ],
    xAxis: {
      type: 'value', min: times[0], max: times[times.length-1],
      axisLabel: { formatter: v => v.toFixed(1)+'s', fontSize: 10 },
      splitLine: { lineStyle: { color: 'rgba(17,19,24,.05)' } },
    },
    yAxis: {
      type: 'value',
      min: -OFFSET,
      max: (channels.length - 1) * OFFSET + OFFSET,
      axisLabel: {
        formatter: (v) => {
          const idx = Math.round(v / OFFSET)
          return channels[idx]?.name || ''
        },
        fontSize: 10, color: (v) => {
          const idx = Math.round(v / OFFSET)
          const ch = channels[idx]
          return ch ? (REG_COLOR[ch.name] || REG_COLOR[ch.region] || '#888') : 'transparent'
        }
      },
      splitLine: { show: false },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: processed.map((ch, i) => ({
      name: ch.name,
      type: 'line',
      symbol: 'none',
      lineStyle: { color: REG_COLOR[ch.name] || REG_COLOR[ch.region] || '#888', width: 1.3 },
      data: times.map((t, j) => [t, ch.normed[j]]),
      markArea: i === 0 ? {
        silent: true,
        itemStyle: { color: 'rgba(160,130,255,.28)' },
        data: blinkAreas
      } : undefined,
      markLine: i === 0 ? {
        silent: true,
        symbol: 'none',
        data: eventLines
      } : undefined,
    }))
  }
}

function makeButterflyOption(times, channels, blinkTimes, events, cursor) {
  const allY = channels.flatMap(ch => ch.y.filter(isFinite).map(Math.abs))
  const scale = Math.max(5, allY.sort((a,b)=>a-b)[Math.floor(allY.length*.7)] || 50)
  const blinkAreas = blinkTimes.flatMap(bt => [[{xAxis: bt-0.15},{xAxis: bt+0.2}]])
  const cursorLine = cursor != null ? [{
    xAxis: cursor,
    label: { formatter: '▶', fontSize: 10, color: '#2ec87a', position: 'end' },
    lineStyle: { color: '#2ec87a', width: 1.5, opacity: .9 }
  }] : []

  return {
    animation: false,
    backgroundColor: 'transparent',
    grid: { left: 60, right: 10, top: 10, bottom: 40 },
    legend: {
      bottom: 32, type: 'scroll', textStyle: { fontSize: 10 },
      itemWidth: 16, itemHeight: 3,
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      backgroundColor: 'rgba(17,19,24,.92)',
      borderColor: 'transparent',
      textStyle: { color: '#fff', fontSize: 11 },
      formatter: (params) => {
        const t = params[0]?.axisValue
        let html = `<b>${Number(t).toFixed(3)}s</b><br/>`
        params.forEach(p => {
          html += `<span style="color:${p.color}">${p.seriesName}</span>: ${Number(p.value[1]).toFixed(1)}µV<br/>`
        })
        return html
      }
    },
    toolbox: { right:10, top:5, feature: { dataZoom:{yAxisIndex:'none'}, restore:{}, saveAsImage:{} } },
    dataZoom: [
      { type: 'inside', xAxisIndex: 0, filterMode: 'none' },
      { type: 'slider', xAxisIndex: 0, height: 20, bottom: 8, borderColor:'transparent', fillerColor:'rgba(26,122,74,.2)' }
    ],
    xAxis: { type: 'value', min: times[0], max: times[times.length-1], axisLabel:{formatter:v=>v.toFixed(1)+'s',fontSize:10}, splitLine:{lineStyle:{color:'rgba(17,19,24,.05)'}} },
    yAxis: {
      type: 'value',
      axisLabel: { formatter: v => v.toFixed(0)+'µV', fontSize: 10 },
      splitLine: { lineStyle: { color: 'rgba(17,19,24,.05)' } },
    },
    series: channels.map(ch => {
      const y = demean(ch.y)
      const col = REG_COLOR[ch.name] || REG_COLOR[ch.region] || '#888'
      return {
        name: ch.name,
        type: 'line',
        symbol: 'none',
        lineStyle: { color: col, width: 0.9, opacity: .7 },
        data: times.map((t,j) => [t, Math.max(-scale, Math.min(scale, y[j]))]),
        markArea: ch === channels[0] ? { silent:true, itemStyle:{color:'rgba(110,100,200,.12)'}, data:blinkAreas } : undefined,
        markLine: ch === channels[0] && cursorLine.length ? { silent:true, symbol:'none', data:cursorLine } : undefined,
      }
    })
  }
}
