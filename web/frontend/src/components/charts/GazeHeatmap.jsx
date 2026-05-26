import React, { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'

export default function GazeHeatmap({ data, height = 220 }) {
  const option = useMemo(() => {
    if (!data?.heatmap?.length) return null
    const { heatmap } = data

    const nX = 48, nY = 27
    const xCats = Array.from({ length: nX }, (_, i) => String(i))
    const yCats = Array.from({ length: nY }, (_, i) => String(i))

    return {
      animation: false,
      backgroundColor: '#0d0e1a',
      grid: { left: 0, right: 0, top: 0, bottom: 0, containLabel: false },
      tooltip: {
        position: 'top',
        formatter: p => `Fixation density: ${(Number(p.value[2]) * 100).toFixed(0)}%`,
        backgroundColor: 'rgba(17,19,24,.9)',
        textStyle: { color: '#fff', fontSize: 11 },
      },
      visualMap: {
        min: 0, max: 1, show: false,
        inRange: { color: ['#0d0e1a', '#1a1a4e', '#2563eb', '#f59e0b', '#ef4444'] },
      },
      xAxis: {
        type: 'category', data: xCats, show: false,
        splitArea: { show: false },
      },
      yAxis: {
        type: 'category', data: yCats, show: false, inverse: true,
        splitArea: { show: false },
      },
      series: [{
        type: 'heatmap',
        data: heatmap.map(([x, y, v]) => [String(x), String(y), v]),
        itemStyle: { borderWidth: 0 },
      }],
    }
  }, [data])

  if (!option) return <div className="loading"><div className="spin" />No gaze data</div>
  const wrapStyle = height == null
    ? { width: '100%', height: '100%', overflow: 'hidden' }
    : { height, width: '100%', overflow: 'hidden' }
  return (
    <div style={wrapStyle}>
      <ReactECharts option={option} style={{ height: '100%', width: '100%' }} opts={{ renderer: 'canvas' }} />
    </div>
  )
}
