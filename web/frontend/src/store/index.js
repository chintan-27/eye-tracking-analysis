import { create } from 'zustand'

// Global app state — replaces the monolithic ST object
export const useStore = create((set, get) => ({
  // Recording selection
  recId:      null,
  subjectId:  null,
  sessionId:  null,
  paradigm:   null,

  // Global time cursor (video-relative seconds, shared across all tabs)
  tCurrent:  0,
  tFollow:   true,   // EEG viewer follows video time when true

  // EEG viewer
  eeg: {
    tStart:  0,
    win:     5,
    region:  'Central',
    band:    'raw',
    mode:    'separate',
  },

  // Video player
  video: {
    frame:      0,
    playing:    false,
    fps:        153,
    nFrames:    0,
    speed:      4,
    startFrame: 0,
    eegAtStart: 0,
  },

  // Blink atlas
  blinkFilter: 'all',   // 'all' | 'video' | 'strong'
  blinkSort:   'time',  // 'time' | 'amplitude'

  // Multimodal viewer — phan_frame as global cross-stream cursor
  phanFrame:       -1,    // -1 = none selected
  phanFrameFollow: true,  // multimodal viewer scrubs with phanFrame changes

  // Actions
  loadRecording: (recId, subjectId, sessionId, paradigm) =>
    set({ recId, subjectId, sessionId, paradigm, tCurrent: 0,
          video: { ...get().video, frame: 0 }, eeg: { ...get().eeg, tStart: 0 },
          phanFrame: -1 }),

  clearRecording: () =>
    set({ recId: null, subjectId: null, sessionId: null, paradigm: null,
          tCurrent: 0, phanFrame: -1 }),

  setTCurrent: (t) => set({ tCurrent: t }),
  setTFollow:  (v) => set({ tFollow: v }),

  setPhanFrame:       (n) => set({ phanFrame: n }),
  setPhanFrameFollow: (v) => set({ phanFrameFollow: v }),

  updateVideo: (patch) => set(s => ({ video: { ...s.video, ...patch } })),
  updateEeg:   (patch) => set(s => ({ eeg:   { ...s.eeg,   ...patch } })),
}))
