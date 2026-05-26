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

// Tobii window
export const useTobiiWindow = (recId, tStart, win) =>
  useQuery({ queryKey: ['tobii', recId, tStart, win],
             queryFn: () => fetch_json(`/api/tobii/${recId}/window?t_start_s=${tStart}&t_end_s=${tStart + win}`),
             enabled: !!recId, staleTime: 30_000, placeholderData: keepPreviousData })

// Alertness distributions
export const useAlertness = () =>
  useQuery({ queryKey: ['alertness'], queryFn: () => fetch_json('/api/alertness/distributions'), staleTime: Infinity })
