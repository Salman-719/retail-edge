import React from 'react'

const NUM_CAMS_OPTIONS = [1, 2, 4, 6]

// Sticky control bar (VD2): session config on the left, run state + Start/Stop on
// the right. Errors render as a banner (below), never truncated inline.
export default function ControlBar({ numCams, setNumCams, device, setDevice, gpu, running, busy, storeId, onStart, onStop, mode = 'idle', onAttach, onDetach }) {
  return (
    <div className="flex items-center gap-3 flex-wrap">
      <div className="inline-flex rounded-lg border border-gray-300 overflow-hidden text-sm">
        {NUM_CAMS_OPTIONS.map((n) => (
          <button key={n} onClick={() => !running && setNumCams(n)} disabled={running}
            className={`px-3 py-1.5 font-semibold ${numCams === n ? 'bg-blue-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'} ${running ? 'opacity-60 cursor-not-allowed' : ''}`}>{n}</button>
        ))}
      </div>

      <div className="flex items-center gap-2">
        <span className="text-[11px] text-gray-400">GPU: {gpu ? (gpu.gpu_available ? 'available' : 'none') : '…'}</span>
        <div className="inline-flex rounded-lg border border-gray-300 overflow-hidden text-sm">
          {['cpu', 'gpu'].map((d) => (
            <button key={d} onClick={() => !running && setDevice(d)} disabled={running}
              className={`px-3 py-1.5 font-semibold uppercase ${device === d ? 'bg-blue-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'} ${running ? 'opacity-60 cursor-not-allowed' : ''}`}>{d}</button>
          ))}
        </div>
      </div>

      {/* Two distinct modes:
          Attach — observe the pipeline the Edge Agent is already running (cloud).
                   Starts nothing, so it is safe against a live store.
          Start  — spin up a dev pipeline on the EEP host itself (local testing);
                   needs yolo/reid on that machine, so it fails on the cloud box. */}
      {!running ? (
        <>
          <button onClick={onAttach} disabled={busy || !storeId}
            className="px-5 py-2 rounded-lg bg-emerald-600 text-white text-sm font-semibold hover:bg-emerald-700 disabled:opacity-50"
            title="Watch the pipeline the Edge Agent is already running. Starts nothing.">Attach to live</button>
          <button onClick={onStart} disabled={busy || !storeId}
            className="px-5 py-2 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 disabled:opacity-50"
            title="Start a dev pipeline on the EEP host (local testing only).">{busy ? 'Starting…' : 'Start local'}</button>
        </>
      ) : mode === 'attached' ? (
        <button onClick={onDetach}
          className="px-5 py-2 rounded-lg bg-gray-600 text-white text-sm font-semibold hover:bg-gray-700">Detach</button>
      ) : (
        <button onClick={onStop} disabled={busy}
          className="px-5 py-2 rounded-lg bg-red-600 text-white text-sm font-semibold hover:bg-red-700 disabled:opacity-50">{busy ? 'Stopping…' : 'Stop'}</button>
      )}
    </div>
  )
}

export { NUM_CAMS_OPTIONS }
