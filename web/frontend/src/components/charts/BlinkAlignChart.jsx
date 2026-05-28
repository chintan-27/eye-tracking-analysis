import React, { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'

/**
 * BlinkAlignChart — averaged multimodal curves aligned to blink onset (t=0).
 *
 * Props:
 *   data — from useBlinkAlignment: {t_ms, aperture, eeg_fp1, tobii_pupil, n_blinks}
 *     Each stream: {mean, sem}
 *   height — px
 */
export default function BlinkAlignChart({ data, height = 260 }) {
  const option = useMemo(() => {
    if (!data?.t_ms?.length) return null

    const t = data.t_ms
    const ap = data.aperture
    const fp = data.eeg_fp1
    const pu = data.tobii_pupil

    const semBand = (mean, sem, color) => mean && sem ? {
      type: 'line', symbol: 'none', animation: false,
      lineStyle: { opacity: 0 },
      areaStyle: { color, opacity: 0.15 },
      data: mean.map((v, i) => [t[i], v != null && sem[i] != null ? v + sem[i] : null]),
      stack: undefined,
    } : null

    const line = (mean, color, name, yAxis = 0) => ({
      name, type: 'line', symbol: 'none', yAxisIndex: yAxis,
      animation: false,
      lineStyle: { color, width: 2 },
      itemStyle: { color },
      data: mean?.map((v, i) => [t[i], v]) ?? [],
    })

    const series = [
      line(ap?.mean,  '#30d980', 'Aperture (mm)', 0),
      line(pu?.mean,  '#60a5fa', 'Tobii Pupil (mm)', 0),
      line(fp?.mean,  '#a78bfa', 'EEG FP1 (µV)', 1),
    ]

    // Add SEM bands
    if (ap?.mean && ap?.sem) {
      series.push({
        name: '_ap_sem', type: 'line', symbol: 'none', animation: false,
        lineStyle: { opacity: 0 },
        areaStyle: { color: '#30d980', opacity: 0.12 },
        data: ap.mean.map((v, i) => [t[i], v != null && ap.sem[i] != null ? v + ap.sem[i] : null]),
      }, {
        name: '_ap_sem_lo', type: 'line', symbol: 'none', animation: false,
        lineStyle: { opacity: 0 },
        areaStyle: { color: '#30d980', opacity: 0 },
        data: ap.mean.map((v, i) => [t[i], v != null && ap.sem[i] != null ? v - ap.sem[i] : null]),
        stack: '_ap_stack',
      })
    }

    return {
      backgroundColor: 'transparent',
      animation: false,
      grid: { top: 32, bottom: 44, left: 56, right: 60, containLabel: false },
      legend: {
        data: ['Aperture (mm)', 'Tobii Pupil (mm)', 'EEG FP1 (µV)'],
        textStyle: { color: 'rgba(255,255,255,.6)', fontSize: 10 },
        top: 4, right: 10,
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'line', lineStyle: { color: 'rgba(255,255,255,.25)' } },
        backgroundColor: '#131829',
        borderColor: 'rgba(255,255,255,.15)',
        textStyle: { color: '#fff', fontSize: 11 },
        formatter: (params) => {
          const tMs = params[0]?.axisValue?.toFixed(0)
          const lines = params
            .filter(p => !p.seriesName.startsWith('_'))
            .map(p => `${p.marker}${p.seriesName}: ${p.value[1]?.toFixed(3) ?? '—'}`)
          return `t = ${tMs} ms<br>${lines.join('<br>')}`
        },
      },
      xAxis: {
        type: 'value',
        name: 'ms from blink onset',
        nameLocation: 'center', nameGap: 28,
        nameTextStyle: { color: 'rgba(255,255,255,.45)', fontSize: 10 },
        axisLine: { lineStyle: { color: 'rgba(255,255,255,.15)' } },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,.05)' } },
        axisLabel: { color: 'rgba(255,255,255,.5)', fontSize: 10 },
        // Blink onset marker at t=0
        markLine: undefined,
      },
      yAxis: [
        {
          type: 'value', name: 'mm', position: 'left',
          nameTextStyle: { color: 'rgba(255,255,255,.45)', fontSize: 10 },
          axisLine: { show: false },
          splitLine: { lineStyle: { color: 'rgba(255,255,255,.05)' } },
          axisLabel: { color: 'rgba(255,255,255,.5)', fontSize: 10 },
        },
        {
          type: 'value', name: 'µV', position: 'right',
          nameTextStyle: { color: 'rgba(167,139,250,.7)', fontSize: 10 },
          axisLine: { show: false },
          splitLine: { show: false },
          axisLabel: { color: 'rgba(167,139,250,.6)', fontSize: 10 },
        },
      ],
      series: [
        ...series,
        // t=0 vertical dashed line
        {
          name: '_onset', type: 'line', symbol: 'none',
          markLine: {
            silent: true,
            lineStyle: { color: 'rgba(255,255,255,.35)', type: 'dashed', width: 1 },
            label: { show: true, formatter: 'onset', color: 'rgba(255,255,255,.5)', fontSize: 9 },
            data: [{ xAxis: 0 }],
          },
          data: [],
        },
      ],
    }
  }, [data])

  if (!option) {
    return (
      <div className="loading" style={{ height }}>
        no blink alignment data
      </div>
    )
  }

  return (
    <div>
      {data?.n_blinks != null && (
        <div style={{ fontSize: 10.5, color: 'var(--ink-3)', padding: '0 16px 4px',
                      fontFamily: 'var(--mono)' }}>
          {data.n_blinks} blink epochs averaged · ±{Math.abs(data.t_ms[0])} ms window
        </div>
      )}
      <ReactECharts option={option} style={{ height }} opts={{ renderer: 'canvas' }} />
    </div>
  )
}
