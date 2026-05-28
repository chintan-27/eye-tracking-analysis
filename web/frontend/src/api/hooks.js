import { useQuery, keepPreviousData } from '@tanstack/react-query'

const fetch_json = url => fetch(url).then(r => { if (!r.ok) throw new Error(r.statusText); return r.json() })

// Subjects list (cached indefinitely — doesn't change)
export const useSubjects = () =>
  useQuery({ queryKey: ['subjects'], queryFn: () => fetch_json('/api/subjects'), staleTime: Infinity })

// Sessions list
export const useSessions = () =>
  useQuery({ queryKey: ['sessions'], queryFn: () => fetch_json('/api/sessions'), staleTime: Infinity })

// Session timeline (trials + blinks, cached per recording)
export const useTimeline = (recId) =>
  useQuery({ queryKey: ['timeline', recId], queryFn: () => fetch_json(`/api/eeg/${recId}/timeline`),
             enabled: !!recId, staleTime: Infinity })

// Video info (fps, n_frames, startFrame)
export const useVideoInfo = (recId) =>
  useQuery({ queryKey: ['videoInfo', recId], queryFn: () => fetch_json(`/api/video/${recId}/info`),
             enabled: !!recId, staleTime: Infinity })

// EEG window (refetches on t_start/win/band change)
export const useEegWindow = (recId, tStart, win, band, channels) =>
  useQuery({
    queryKey: ['eegWindow', recId, tStart, win, band, channels],
    queryFn:  () => fetch_json(
      `/api/eeg/${recId}/window?t_start_s=${tStart}&t_end_s=${tStart + win}` +
      (channels ? `&channels=${channels}` : '') +
      `&band=${band}&scale=raw`
    ),
    enabled:   !!recId,
    staleTime: 30_000,
  })

// EEG minimap (full session envelope, cached)
export const useEegMinimap = (recId) =>
  useQuery({ queryKey: ['minimap', recId], queryFn: () => fetch_json(`/api/eeg/${recId}/minimap`),
             enabled: !!recId, staleTime: Infinity })

// EEG events (trial markers)
export const useEegEvents = (recId) =>
  useQuery({ queryKey: ['events', recId], queryFn: () => fetch_json(`/api/eeg/${recId}/events`),
             enabled: !!recId, staleTime: Infinity })

// EEG trials table
export const useTrials = (recId) =>
  useQuery({ queryKey: ['trials', recId], queryFn: () => fetch_json(`/api/eeg/${recId}/trials`),
             enabled: !!recId, staleTime: Infinity })

// ERP
export const useErp = (recId, channels) =>
  useQuery({ queryKey: ['erp', recId, channels], queryFn: () => fetch_json(`/api/eeg/${recId}/erp?channels=${channels}`),
             enabled: !!recId, staleTime: Infinity })

// PSD
export const usePsd = (recId, region) =>
  useQuery({ queryKey: ['psd', recId, region], queryFn: () => fetch_json(`/api/eeg/${recId}/psd?region=${region}`),
             enabled: !!recId, staleTime: Infinity })

// Video EEG sync (per frame — short stale time)
export const useVideoEeg = (recId, frame) =>
  useQuery({ queryKey: ['videoEeg', recId, frame], queryFn: () => fetch_json(`/api/video/${recId}/eeg_at_frame?n=${frame}&window_s=4`),
             enabled: !!recId && frame >= 0, staleTime: 5_000, refetchOnWindowFocus: false,
             placeholderData: keepPreviousData })

// All blinks (cached — heavy, only fetches once per recording)
export const useBlinks = (recId) =>
  useQuery({ queryKey: ['blinks', recId], queryFn: () => fetch_json(`/api/video/${recId}/blinks`),
             enabled: !!recId, staleTime: Infinity })

// Blink detail
export const useBlinkDetail = (recId, blinkId) =>
  useQuery({ queryKey: ['blinkDetail', recId, blinkId], queryFn: () => fetch_json(`/api/video/${recId}/blinks/${blinkId}/detail`),
             enabled: !!recId && blinkId != null, staleTime: Infinity })

// Gaze summary (heavy, cached)
export const useGazeSummary = (recId) =>
  useQuery({ queryKey: ['gazeSummary', recId], queryFn: () => fetch_json(`/api/tobii/${recId}/gaze_summary`),
             enabled: !!recId, staleTime: Infinity })

// Tobii window (time-based)
export const useTobiiWindow = (recId, tStart, win) =>
  useQuery({ queryKey: ['tobii', recId, tStart, win],
             queryFn: () => fetch_json(`/api/tobii/${recId}/window?t_start_s=${tStart}&t_end_s=${tStart + win}`),
             enabled: !!recId, staleTime: 30_000, placeholderData: keepPreviousData })

// Tobii window by phan_frame range (requires aligned parquet)
export const useTobiiWindowByFrame = (recId, startFrame, endFrame) =>
  useQuery({
    queryKey: ['tobiiByFrame', recId, startFrame, endFrame],
    queryFn:  () => fetch_json(
      `/api/tobii/${recId}/window_by_frame?start_frame=${startFrame}&end_frame=${endFrame}`
    ),
    enabled: !!recId && startFrame != null && endFrame != null && endFrame > startFrame,
    staleTime: Infinity,
    retry: false,
    placeholderData: keepPreviousData,
  })

// Alertness distributions
export const useAlertness = () =>
  useQuery({ queryKey: ['alertness'], queryFn: () => fetch_json('/api/alertness/distributions'), staleTime: Infinity })

// Pipeline timeseries (pre-computed per-frame results from HPG run)
export const usePipelineTimeseries = (recId, runId = null, combination = 'stable_match_farneback') =>
  useQuery({
    queryKey: ['pipelineTs', recId, runId, combination],
    queryFn: () => fetch_json(
      `/api/pipeline/${recId}/timeseries?combination=${combination}` +
      (runId ? `&run_id=${runId}` : '')
    ),
    enabled: !!recId, staleTime: Infinity,
    retry: false,
  })

// Pipeline biomarkers (aggregated feature row)
export const usePipelineBiomarkers = (recId, runId = null, combination = 'stable_match_farneback') =>
  useQuery({
    queryKey: ['pipelineBm', recId, runId, combination],
    queryFn: () => fetch_json(
      `/api/pipeline/${recId}/biomarkers?combination=${combination}` +
      (runId ? `&run_id=${runId}` : '')
    ),
    enabled: !!recId, staleTime: Infinity,
    retry: false,
  })

// Available pipeline runs
export const usePipelineRuns = () =>
  useQuery({ queryKey: ['pipelineRuns'], queryFn: () => fetch_json('/api/pipeline/runs'), staleTime: 60_000 })

// Available MP4 videos for a recording
export const usePipelineVideos = (recId, runId = null) =>
  useQuery({
    queryKey: ['pipelineVideos', recId, runId],
    queryFn: () => fetch_json(
      `/api/pipeline/${recId}/videos` + (runId ? `?run_id=${runId}` : '')
    ),
    enabled: !!recId, staleTime: 60_000, retry: false,
  })

// Multimodal sync quality (anchor count, coverage %) — cached per recording
export const useSyncQuality = (recId) =>
  useQuery({
    queryKey: ['syncQuality', recId],
    queryFn:  () => fetch_json(`/api/multimodal/${recId}/sync_quality`),
    enabled: !!recId, staleTime: Infinity, retry: false,
  })

// All streams at a single phan_frame
export const useMultimodalAtFrame = (recId, phanFrame, eegWinS = 4) =>
  useQuery({
    queryKey: ['mmAtFrame', recId, phanFrame, eegWinS],
    queryFn:  () => fetch_json(
      `/api/multimodal/${recId}/at_frame?n=${phanFrame}&eeg_win_s=${eegWinS}`
    ),
    enabled:  !!recId && phanFrame >= 0,
    staleTime: 10_000,
    placeholderData: keepPreviousData,
    retry: false,
  })

// Saccade event list (Tobii + Phantom) — heavy, cached
export const useSaccades = (recId) =>
  useQuery({
    queryKey: ['saccades', recId],
    queryFn:  () => fetch_json(`/api/multimodal/${recId}/saccades`),
    enabled: !!recId, staleTime: Infinity, retry: false,
  })

// Blink-aligned multi-stream average (±window ms around each blink onset)
export const useBlinkAlignment = (recId, windowMs = 500) =>
  useQuery({
    queryKey: ['blinkAlign', recId, windowMs],
    queryFn:  () => fetch_json(`/api/multimodal/${recId}/blink_alignment?window_ms=${windowMs}`),
    enabled: !!recId, staleTime: Infinity, retry: false,
  })

// Session detail: demographics + alertness per paradigm
export const useSessionDetail = (sessionId) =>
  useQuery({
    queryKey: ['sessionDetail', sessionId],
    queryFn:  () => fetch_json(`/api/sessions/${sessionId}`),
    enabled: !!sessionId, staleTime: Infinity,
  })
