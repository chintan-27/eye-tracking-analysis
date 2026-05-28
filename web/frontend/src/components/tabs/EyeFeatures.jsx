import React, { useMemo, useState } from 'react'
import ReactECharts from 'echarts-for-react'
import { useStore } from '../../store'
import { usePipelineTimeseries, usePipelineBiomarkers, useBlinkAlignment } from '../../api/hooks'
import BlinkAlignChart from '../charts/BlinkAlignChart'

// Build blink closed-state markArea bands (state=2 = fully closed)
function blinkBands(tArr, stateArr) {
  if (!tArr || !stateArr) return []
  const bands = []
  let i = 0
  while (i < stateArr.length) {
    const s = stateArr[i]
    if (s !== 0) {
      const startT = tArr[i]
      let j = i + 1
      while (j < stateArr.length && stateArr[j] !== 0) j++
      const endT = tArr[Math.min(j, stateArr.length - 1)]
      const color = s === 2
        ? 'rgba(167,139,250,0.22)'
        : 'rgba(167,139,250,0.10)'
      bands.push([{ xAxis: startT, itemStyle: { color } }, { xAxis: endT }])
      i = j
    } else {
      i++
    }
  }
  return bands
}

function baseChartOpt(title, yLabel, seriesList, tArr, stateArr) {
  return {
    backgroundColor: 'transparent',
    animation: false,
    grid: { top: 36, bottom: 40, left: 60, right: 24, containLabel: false },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', lineStyle: { color: 'rgba(255,255,255,.25)' } },
      backgroundColor: '#131829',
      borderColor: 'rgba(255,255,255,.15)',
      textStyle: { color: '#fff', fontSize: 11 },
    },
    toolbox: { show: true, right: 24, top: 4, feature: { dataZoom: { yAxisIndex: 'none' }, restore: {}, saveAsImage: {} } },
    dataZoom: [
      { type: 'inside', xAxisIndex: 0 },
      { type: 'slider', xAxisIndex: 0, bottom: 2, height: 16, borderColor: 'rgba(255,255,255,.1)', fillerColor: 'rgba(48,217,128,.08)', handleStyle: { color: '#30d980' } },
    ],
    xAxis: {
      type: 'value',
      name: 'Time (s)',
      nameTextStyle: { color: 'rgba(255,255,255,.45)', fontSize: 10 },
      axisLine: { lineStyle: { color: 'rgba(255,255,255,.15)' } },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,.05)' } },
      axisLabel: { color: 'rgba(255,255,255,.5)', fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      name: yLabel,
      nameTextStyle: { color: 'rgba(255,255,255,.45)', fontSize: 10 },
      axisLine: { show: false },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,.05)' } },
      axisLabel: { color: 'rgba(255,255,255,.5)', fontSize: 10 },
    },
    title: { text: title, textStyle: { color: 'rgba(255,255,255,.80)', fontSize: 12, fontWeight: 600 }, top: 8, left: 10 },
    series: seriesList.map(s => ({
      ...s,
      data: s.data ? tArr.map((t, i) => [t, s.data[i]]) : s.rawData,
      type: 'line',
      symbol: 'none',
      lineWidth: 1.5,
      markArea: stateArr ? { silent: true, data: blinkBands(tArr, stateArr) } : undefined,
    })),
  }
}

function fmt(v, decimals = 2, unit = '') {
  if (v == null || !isFinite(v)) return '—'
  return v.toFixed(decimals) + unit
}

const BM_CARDS = [
  { key: 'blink_rate_per_min',  label: 'Blink Rate',         decimals: 1, unit: '/min' },
  { key: 'blink_dur_mean_ms',   label: 'Blink Duration',     decimals: 0, unit: ' ms'  },
  { key: 'blink_dur_p95_ms',    label: 'Blink P95',          decimals: 0, unit: ' ms'  },
  { key: 'r_slow_mean',         label: 'R-slow (mean)',      decimals: 3, unit: ''     },
  { key: 'pupil_diam_mean_mm',  label: 'Pupil Diameter',     decimals: 2, unit: ' mm'  },
  { key: 'pupil_diam_var_mm',   label: 'Pupil Variability',  decimals: 4, unit: ' mm²' },
  { key: 'tremor_power',        label: 'Tremor Power',       decimals: 3, unit: ''     },
  { key: 'aperture_norm_mean',  label: 'Aperture Norm',      decimals: 3, unit: ''     },
]

export default function EyeFeatures() {
  const recId = useStore(s => s.recId)
  const { data: ts, isLoading, error } = usePipelineTimeseries(recId)
  const { data: bm }   = usePipelineBiomarkers(recId)
  const { data: align } = useBlinkAlignment(recId)
  const [showFlow, setShowFlow] = useState(true)

  const apertureOpt = useMemo(() => {
    if (!ts) return null
    return baseChartOpt(
      'Eyelid Aperture',
      'mm',
      [{ name: 'Aperture', data: ts.aperture_mm, lineStyle: { color: '#30d980' }, itemStyle: { color: '#30d980' } }],
      ts.t_s,
      ts.blink_state,
    )
  }, [ts])

  const pupilOpt = useMemo(() => {
    if (!ts) return null
    return baseChartOpt(
      'Pupil Diameter',
      'mm',
      [{ name: 'Pupil', data: ts.pupil_diameter_mm, lineStyle: { color: '#60a5fa' }, itemStyle: { color: '#60a5fa' } }],
      ts.t_s,
      ts.blink_state,
    )
  }, [ts])

  const flowOpt = useMemo(() => {
    if (!ts) return null
    return baseChartOpt(
      'Optical Flow Energy (micro-movement)',
      'px/frame',
      [
        { name: 'Eyelid', data: ts.flow_mag_mean_eyelid, lineStyle: { color: '#fbbf24' }, itemStyle: { color: '#fbbf24' } },
        { name: 'Pupil',  data: ts.flow_mag_mean_pupil,  lineStyle: { color: '#a78bfa' }, itemStyle: { color: '#a78bfa' } },
      ],
      ts.t_s,
      null,
    )
  }, [ts])

  const motionOpt = useMemo(() => {
    if (!ts) return null
    return baseChartOpt(
      'Head Stabilization Residual',
      'px',
      [
        { name: 'tx', data: ts.transform_tx, lineStyle: { color: '#f87171' }, itemStyle: { color: '#f87171' } },
        { name: 'ty', data: ts.transform_ty, lineStyle: { color: '#fb923c' }, itemStyle: { color: '#fb923c' } },
      ],
      ts.t_s,
      null,
    )
  }, [ts])

  if (!recId) return <div className="empty-state">Select a subject to view Eye Features</div>

  if (error) return (
    <div className="card" style={{ padding: 24 }}>
      <div style={{ color: 'var(--acc)', fontWeight: 600, marginBottom: 8 }}>No pipeline data available</div>
      <div style={{ color: 'var(--ink-3)', fontSize: 12 }}>
        Run the HiPerGator pipeline job and fetch results.<br />
        Results path: <code style={{ fontFamily: 'var(--mono)' }}>dataserver/video_runs/full_dataset_v1/{recId}/</code>
      </div>
    </div>
  )

  if (isLoading) return <div className="loading">Loading pipeline data…</div>

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>

      {/* Biomarker cards */}
      {bm && (
        <div className="card">
          <div className="card-hd">
            <div className="card-hd-l">
              <div className="card-title">Biomarker Summary</div>
              <div className="card-sub">Aggregated features from {ts?.n_frames?.toLocaleString()} processed frames · run: {bm._run_id}</div>
            </div>
          </div>
          <div className="card-body">
            <div className="stat-row">
              {BM_CARDS.map(({ key, label, decimals, unit }) => (
                <div key={key} className="stat-chip">
                  <div className="sv">{fmt(bm[key], decimals, unit)}</div>
                  <div className="sl">{label}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Aperture chart */}
      <div className="card">
        <div className="card-hd">
          <div className="card-hd-l">
            <div className="card-title">Eyelid Aperture</div>
            <div className="card-sub">Eyelid opening in mm over the session · purple bands = blink events</div>
          </div>
          <div style={{ fontSize: 10, color: 'var(--ink-3)', fontFamily: 'var(--mono)' }}>
            {ts?.n_points?.toLocaleString()} pts / {ts?.n_frames?.toLocaleString()} frames
          </div>
        </div>
        <div className="card-body" style={{ padding: '8px 0 0' }}>
          {apertureOpt && <ReactECharts option={apertureOpt} style={{ height: 200 }} />}
        </div>
      </div>

      {/* Pupil chart */}
      <div className="card">
        <div className="card-hd">
          <div className="card-hd-l">
            <div className="card-title">Pupil Diameter</div>
            <div className="card-sub">Corneal-reflection–corrected pupil size in mm · purple bands = blink events</div>
          </div>
        </div>
        <div className="card-body" style={{ padding: '8px 0 0' }}>
          {pupilOpt && <ReactECharts option={pupilOpt} style={{ height: 200 }} />}
        </div>
      </div>

      {/* Blink alignment validation */}
      <div className="card">
        <div className="card-hd">
          <div className="card-hd-l">
            <div className="card-title">Blink Alignment Validation</div>
            <div className="card-sub">
              Aperture · EEG FP1 · Tobii pupil averaged around blink onset — confirms cross-stream sync
            </div>
          </div>
        </div>
        <div className="card-body" style={{ padding: '8px 0 0' }}>
          {align
            ? <BlinkAlignChart data={align} height={220} />
            : <div className="loading" style={{ height: 100 }}>
                {error ? 'requires HPG pipeline output' : 'loading blink alignment…'}
              </div>
          }
        </div>
      </div>

      {/* Flow + motion side-by-side */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
        <div className="card">
          <div className="card-hd">
            <div className="card-hd-l">
              <div className="card-title">Optical Flow Energy</div>
              <div className="card-sub">Dense flow magnitude — proxy for micro-tremor</div>
            </div>
          </div>
          <div className="card-body" style={{ padding: '8px 0 0' }}>
            {flowOpt && <ReactECharts option={flowOpt} style={{ height: 200 }} />}
          </div>
        </div>

        <div className="card">
          <div className="card-hd">
            <div className="card-hd-l">
              <div className="card-title">Head Stabilization</div>
              <div className="card-sub">Phase-correlation residual translation (tx, ty)</div>
            </div>
          </div>
          <div className="card-body" style={{ padding: '8px 0 0' }}>
            {motionOpt && <ReactECharts option={motionOpt} style={{ height: 200 }} />}
          </div>
        </div>
      </div>

    </div>
  )
}
