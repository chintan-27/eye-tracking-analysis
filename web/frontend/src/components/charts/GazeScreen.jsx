import React, { useMemo } from 'react'

const W = 1920
const H = 1080
const TRAIL = 30

/**
 * GazeScreen — SVG representation of a 16:9 monitor with live gaze dot.
 *
 * Props:
 *   tobii    — array of {gaze_x, gaze_y, event_type, validity} (most-recent last)
 *   current  — {gaze_x, gaze_y, event_type, validity, sync_error_ms}
 *   saccades — [{phan_frame_onset, gaze_x_start, gaze_y_start, gaze_x_end, gaze_y_end}]
 *   width    — container width (px); height auto-computed at 9/16
 */
export default function GazeScreen({ tobii = [], current = null, saccades = [], width = 480 }) {
  const height = Math.round(width * 9 / 16)
  const sx = width  / W
  const sy = height / H

  const trail = useMemo(() => tobii.slice(-TRAIL), [tobii])

  const px = (x) => x * sx
  const py = (y) => y * sy

  // `valid` is a boolean from the at_frame API; fallback: validity === 0 for legacy
  const isValid = current?.valid === true || current?.validity === 0
  const dotColor = current == null ? 'transparent'
    : isValid ? '#30d980' : '#64748b'

  const syncOk = current?.sync_error_ms != null && current.sync_error_ms < 200
  const syncBadge = current?.sync_error_ms != null
    ? `${Math.round(current.sync_error_ms)}ms`
    : '—'

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      style={{ display: 'block', background: '#06091a', borderRadius: 6,
               border: '1px solid rgba(255,255,255,.1)' }}
    >
      {/* monitor bezel */}
      <rect x={0} y={0} width={width} height={height} rx={6}
            fill="#06091a" stroke="rgba(255,255,255,.08)" strokeWidth={1} />

      {/* screen area (slight inset to look like a monitor frame) */}
      <rect x={4} y={4} width={width - 8} height={height - 8} rx={4}
            fill="#0a0d18" />

      {/* grid lines (faint) */}
      {[1,2,3].map(i => (
        <line key={`hg${i}`}
          x1={4} y1={4 + (height - 8) * i / 4}
          x2={width - 4} y2={4 + (height - 8) * i / 4}
          stroke="rgba(255,255,255,.04)" strokeWidth={0.5} />
      ))}
      {[1,2,3].map(i => (
        <line key={`vg${i}`}
          x1={4 + (width - 8) * i / 4} y1={4}
          x2={4 + (width - 8) * i / 4} y2={height - 4}
          stroke="rgba(255,255,255,.04)" strokeWidth={0.5} />
      ))}

      {/* centre crosshair */}
      <line x1={width/2} y1={height/2 - 8} x2={width/2} y2={height/2 + 8}
            stroke="rgba(255,255,255,.12)" strokeWidth={0.8} />
      <line x1={width/2 - 8} y1={height/2} x2={width/2 + 8} y2={height/2}
            stroke="rgba(255,255,255,.12)" strokeWidth={0.8} />

      {/* saccade vectors */}
      {saccades.slice(-8).map((s, i) => {
        if (s.gaze_x_start == null || s.gaze_x_end == null) return null
        return (
          <g key={`sac${i}`} opacity={0.5}>
            <line
              x1={px(s.gaze_x_start)} y1={py(s.gaze_y_start)}
              x2={px(s.gaze_x_end)}   y2={py(s.gaze_y_end)}
              stroke="#fbbf24" strokeWidth={1.2}
              markerEnd="url(#arr)"
            />
          </g>
        )
      })}

      {/* gaze trail */}
      {trail.length > 1 && (
        <polyline
          points={trail.map((p, i) =>
            `${px(p.gaze_x)},${py(p.gaze_y)}`
          ).join(' ')}
          fill="none"
          stroke="rgba(48,217,128,.40)"
          strokeWidth={1.5}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      )}

      {/* fixation circles */}
      {trail.filter(p => p.event_type === 'Fixation').slice(-5).map((p, i) => (
        <circle key={`fix${i}`}
          cx={px(p.gaze_x)} cy={py(p.gaze_y)} r={10}
          fill="rgba(96,165,250,.08)"
          stroke="rgba(96,165,250,.35)"
          strokeWidth={1}
        />
      ))}

      {/* current gaze dot */}
      {current != null && (
        <g>
          <circle
            cx={px(current.gaze_x)} cy={py(current.gaze_y)}
            r={6}
            fill={dotColor}
            opacity={isValid ? 0.92 : 0.5}
          />
          {isValid && (
            <circle
              cx={px(current.gaze_x)} cy={py(current.gaze_y)}
              r={11}
              fill="none"
              stroke={dotColor}
              strokeWidth={1}
              opacity={0.35}
            />
          )}
        </g>
      )}

      {/* arrow marker def */}
      <defs>
        <marker id="arr" markerWidth={6} markerHeight={6} refX={3} refY={3} orient="auto">
          <path d="M0,0 L0,6 L6,3 z" fill="#fbbf24" />
        </marker>
      </defs>

      {/* sync quality badge */}
      <rect x={width - 62} y={height - 22} width={58} height={16} rx={4}
            fill={syncOk ? 'rgba(48,217,128,.18)' : 'rgba(251,191,36,.18)'} />
      <text x={width - 62 + 29} y={height - 22 + 11}
            textAnchor="middle"
            fill={syncOk ? '#30d980' : '#fbbf24'}
            fontSize={9} fontFamily="monospace">
        {syncBadge}
      </text>

      {/* no-data overlay */}
      {current == null && (
        <text x={width / 2} y={height / 2}
              textAnchor="middle" dominantBaseline="middle"
              fill="rgba(255,255,255,.2)" fontSize={12} fontFamily="monospace">
          no frame selected
        </text>
      )}
    </svg>
  )
}
