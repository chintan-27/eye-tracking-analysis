import React, { useState } from 'react'
import { useStore } from '../../store'
import { useErp, usePsd, useTrials } from '../../api/hooks'
import ErpChart from '../charts/ErpChart'
import PsdChart from '../charts/PsdChart'

const ERP_PRESETS = [
  { label: 'Parietal', channels: 'CZ,CPZ,PZ',  desc: 'P300 target (CZ/CPZ/PZ)' },
  { label: 'Motor',    channels: 'C3,CZ,C4',    desc: 'Motor cortex (C3/CZ/C4)' },
  { label: 'Frontal',  channels: 'FZ,FCZ,CZ',   desc: 'Executive / attention (FZ/FCZ/CZ)' },
  { label: 'Occipital',channels: 'O1,OZ,O2',    desc: 'Visual cortex (O1/OZ/O2)' },
]
const REGIONS = ['Frontal', 'Central', 'Parietal', 'Occipital', 'Temporal']

export default function Analysis() {
  const { recId, updateEeg } = useStore()
  const [erpChs, setErpChs] = useState('CZ,CPZ,PZ')
  const [psdReg, setPsdReg] = useState('Central')

  const { data: erp, isLoading: erpLoading } = useErp(recId, erpChs)
  const { data: psd, isLoading: psdLoading } = usePsd(recId, psdReg)
  const { data: trialsData } = useTrials(recId)
  const trials = trialsData?.trials || []

  const presetDesc = ERP_PRESETS.find(p => p.channels === erpChs)?.desc || ''

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>

      {/* Intro banner */}
      <div className="card" style={{ borderLeft: '3px solid var(--pri)' }}>
        <div style={{ padding: '10px 16px', display: 'flex', gap: 24, flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: 220 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--ink)', marginBottom: 4 }}>
              What is this tab?
            </div>
            <div style={{ fontSize: 11, color: 'var(--ink-2)', lineHeight: 1.55 }}>
              This tab analyzes the EEG signal across every trial of the session.
              Two complementary views: <strong>ERP</strong> shows the average brain response
              time-locked to each stimulus, while <strong>PSD</strong> shows the overall
              distribution of brain oscillation frequencies.
            </div>
          </div>
          <div style={{ flex: 1, minWidth: 220 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--ink)', marginBottom: 4 }}>
              What to look for
            </div>
            <div style={{ fontSize: 11, color: 'var(--ink-2)', lineHeight: 1.55 }}>
              In ERP: a positive peak ~300ms after stimulus onset (the <em>P300</em>) indicates
              cognitive recognition. Stronger P300 = more attentive. In PSD: a clear alpha
              peak at 8–13 Hz is normal; a slow alpha or absent peak can indicate fatigue or
              neurological change.
            </div>
          </div>
        </div>
      </div>

      <div className="card-row">
        {/* ERP */}
        <div className="card" style={{ flex: 1, minWidth: 0 }}>
          <div className="card-hd">
            <div className="card-hd-l">
              <div className="card-title">Average Stimulus Response (ERP)</div>
              <div className="card-sub">
                Trials averaged &amp; baseline-corrected · −200ms to 0ms · shading = ±1 SEM
              </div>
            </div>
            <div className="pill-grp">
              {ERP_PRESETS.map(p => (
                <button key={p.label}
                        className={`pill ${erpChs === p.channels ? 'active' : ''}`}
                        onClick={() => setErpChs(p.channels)}
                        title={p.desc}>
                  {p.label}
                </button>
              ))}
            </div>
          </div>
          <div className="card-body">
            <div className="explain-box">
              <strong>Reading this:</strong> Time 0 = when the stimulus appeared on screen. Each
              coloured line is one EEG channel ({presetDesc}). A <em>positive deflection peaking
              ~300ms</em> is the P300 — the brain recognising the target stimulus. Negative values
              are normal before the event. Flat lines or missing peaks may indicate noise or missed
              trials.
            </div>
            {erpLoading
              ? <div className="loading"><div className="spin" />Computing ERP…</div>
              : <ErpChart data={erp} height={260} />}
            {erp && (
              <div style={{ fontSize: 10.5, color: 'var(--ink-3)', marginTop: 6 }}>
                {erp.n_trials != null && `${erp.n_trials} trials averaged · `}
                Channels: {erp.channels?.join(', ')}
              </div>
            )}
          </div>
        </div>

        {/* PSD */}
        <div className="card" style={{ flex: 1, minWidth: 0 }}>
          <div className="card-hd">
            <div className="card-hd-l">
              <div className="card-title">Brain Oscillation Spectrum (PSD)</div>
              <div className="card-sub">
                Welch method · full session · each line = one electrode
              </div>
            </div>
            <div className="pill-grp">
              {REGIONS.map(r => (
                <button key={r}
                        className={`pill ${psdReg === r ? 'active' : ''}`}
                        onClick={() => setPsdReg(r)}>
                  {r}
                </button>
              ))}
            </div>
          </div>
          <div className="card-body">
            <div className="explain-box">
              <strong>Brain rhythms (x-axis bands):</strong>&nbsp;
              δ 0.5–4 Hz (deep sleep) · θ 4–8 Hz (drowsy/memory) ·
              <strong> α 8–13 Hz</strong> (relaxed, eyes closed) · β 13–30 Hz (focused, active) ·
              γ 30+ Hz (high cognition). The <em>alpha peak</em> is the most reliable resting
              marker — its frequency shifts lower with fatigue or disease.
            </div>
            {psdLoading
              ? <div className="loading"><div className="spin" />Computing PSD…</div>
              : <PsdChart data={psd} height={248} />}
          </div>
        </div>
      </div>

      {/* Trial table */}
      <div className="card">
        <div className="card-hd">
          <div className="card-hd-l">
            <div className="card-title">All Trials</div>
            <div className="card-sub">
              {trials.length} trials · click any row to jump EEG viewer to that trial
            </div>
          </div>
        </div>
        <div className="explain-box" style={{ margin: '0 16px 8px' }}>
          Each row is one trial epoch. <strong>Missed</strong> = no valid EEG epoch detected
          (e.g. movement artefact). Click a row to navigate the EEG viewer to that moment.
        </div>
        <div style={{ maxHeight: 240, overflowY: 'auto' }}>
          <table className="trial-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Stimulus</th>
                <th>Start time</th>
                <th>Duration</th>
                <th>Missed</th>
              </tr>
            </thead>
            <tbody>
              {trials.map(t => (
                <tr key={t.trial_id}
                    onClick={() => updateEeg({ tStart: Math.max(0, (t.start_s || 0) - 0.5) })}>
                  <td style={{ fontFamily: 'JetBrains Mono', color: 'var(--ink-3)' }}>
                    {t.trial_number}
                  </td>
                  <td style={{ fontWeight: 600 }}>{t.cue}</td>
                  <td style={{ fontFamily: 'JetBrains Mono', textAlign: 'right' }}>
                    {t.start_s?.toFixed(2)}s
                  </td>
                  <td style={{ fontFamily: 'JetBrains Mono', textAlign: 'right' }}>
                    {t.duration_s?.toFixed(2)}s
                  </td>
                  <td style={{ textAlign: 'center', color: 'var(--acc)' }}>
                    {t.missed ? '●' : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
