/**
 * Vision Debug Console — dev-only page. Remove this file and its route in
 * App.jsx before shipping. All traces are isolated to:
 *   - frontend/src/pages/VisionDebugConsole.jsx  (this file)
 *   - frontend/src/App.jsx                        (one conditional Route)
 *   - frontend/.env.example                       (VITE_IEP2_DEV_API_URL)
 */
import React, { useRef, useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { getStore, listCameras } from '../api'

const IEP2_URL = import.meta.env.VITE_IEP2_DEV_API_URL || 'http://localhost:8002'
const WS_URL   = IEP2_URL.replace(/^http/, 'ws') + '/ws'

const COLORS = [
  '#ff5252', '#40c4ff', '#69f0ae', '#ffd740', '#e040fb', '#ffab40',
  '#ff6d00', '#00e5ff', '#76ff03', '#ff4081', '#18ffff', '#b2ff59',
]

function trackColor(id) {
  return COLORS[id % COLORS.length]
}

// Ported verbatim from ui/index.html — plain function, not a React component.
function drawRecord(ctx, canvas, record) {
  const img = new Image()
  img.onload = () => {
    canvas.width  = img.naturalWidth
    canvas.height = img.naturalHeight
    ctx.drawImage(img, 0, 0)
    ;(record.tracks || []).forEach(t => {
      const [x1, y1, x2, y2] = t.bbox
      const nx = (x1 / img.naturalWidth)  * canvas.width
      const ny = (y1 / img.naturalHeight) * canvas.height
      const nw = ((x2 - x1) / img.naturalWidth)  * canvas.width
      const nh = ((y2 - y1) / img.naturalHeight) * canvas.height

      const isPending = t.local_id == null
      const color = isPending ? '#ffd740' : trackColor(t.local_id)
      const label = isPending
        ? `? T:${t.track_id}`
        : `L:${t.local_id} T:${t.track_id}`

      ctx.strokeStyle = color
      ctx.lineWidth   = 2
      ctx.strokeRect(nx, ny, nw, nh)

      ctx.font = 'bold 12px sans-serif'
      const tw = ctx.measureText(label).width + 8
      const th = 16
      ctx.fillStyle = '#000'
      ctx.fillRect(nx, ny - th, tw, th)
      ctx.fillStyle = color
      ctx.fillText(label, nx + 4, ny - 4)
    })
  }
  img.src = 'data:image/jpeg;base64,' + record.frame_b64
}

export default function VisionDebugConsole() {
  const { slug } = useParams()

  const framesRef         = useRef([])
  const liveCanvasRef     = useRef(null)
  const playbackCanvasRef = useRef(null)
  const socketRef         = useRef(null)
  const flashTimersRef    = useRef({})   // local_id → timer id

  const [storeId,          setStoreId]          = useState(null)
  const [cameras,          setCameras]          = useState([])
  const [selectedCameraId, setSelectedCameraId] = useState('')
  const [playbackIdx,      setPlaybackIdx]      = useState(0)
  const [totalFrames,      setTotalFrames]      = useState(0)
  const [isDone,           setIsDone]           = useState(false)
  const [isProcessing,     setIsProcessing]     = useState(false)
  const [uploadStatus,     setUploadStatus]     = useState('')
  const [persons,          setPersons]          = useState(new Map())
  const [newPersonIds,     setNewPersonIds]     = useState(new Set())
  const [dbRows,           setDbRows]           = useState([])
  const [dbTotal,          setDbTotal]          = useState(0)
  const [file,             setFile]             = useState(null)

  // Resolve store UUID and fetch registered cameras on mount.
  useEffect(() => {
    getStore(slug)
      .then(s => {
        setStoreId(s.id)
        return listCameras(slug)
      })
      .then(cams => {
        const active = (cams || []).filter(c => c.is_active)
        setCameras(active)
        if (active.length === 1) setSelectedCameraId(active[0].id)
      })
      .catch(() => setUploadStatus('Could not load store cameras — check API connection.'))
  }, [slug])

  // Close WS on unmount to avoid lingering connections on navigation.
  useEffect(() => {
    return () => {
      socketRef.current?.close()
      socketRef.current = null
      Object.values(flashTimersRef.current).forEach(clearTimeout)
    }
  }, [])

  // Playback: redraw whenever slider index changes.
  useEffect(() => {
    if (!isDone || !playbackCanvasRef.current) return
    const record = framesRef.current[playbackIdx]
    if (!record) return
    drawRecord(playbackCanvasRef.current.getContext('2d'), playbackCanvasRef.current, record)
  }, [playbackIdx, isDone])

  function updatePersons(tracks, newEntries) {
    const newEntrySet = new Set(newEntries || [])

    setPersons(prev => {
      const next = new Map(prev)
      tracks.forEach(t => {
        if (t.local_id == null) return
        if (!next.has(t.local_id)) {
          next.set(t.local_id, t.label || String(t.local_id))
        }
      })
      return next
    })

    // Flash green for 2s when a track_id resolves to a new local_id.
    tracks.forEach(t => {
      if (!newEntrySet.has(t.track_id) || t.local_id == null) return
      setNewPersonIds(prev => new Set([...prev, t.local_id]))
      if (flashTimersRef.current[t.local_id]) clearTimeout(flashTimersRef.current[t.local_id])
      flashTimersRef.current[t.local_id] = setTimeout(() => {
        setNewPersonIds(prev => { const n = new Set(prev); n.delete(t.local_id); return n })
        delete flashTimersRef.current[t.local_id]
      }, 2000)
    })
  }

  function openSocket() {
    try { socketRef.current?.close() } catch (_) {}
    const sock = new WebSocket(WS_URL)
    socketRef.current = sock

    sock.onmessage = evt => {
      const msg = JSON.parse(evt.data)

      if (msg.type === 'frame') {
        framesRef.current.push(msg)
        if (liveCanvasRef.current) {
          drawRecord(liveCanvasRef.current.getContext('2d'), liveCanvasRef.current, msg)
        }
        updatePersons(msg.tracks || [], msg.new_entries || [])
      }

      if (msg.type === 'db_snapshot') {
        setDbRows(msg.rows)
        setDbTotal(msg.total_rows)
      }

      if (msg.type === 'done') {
        setTotalFrames(framesRef.current.length)
        setIsProcessing(false)
        setIsDone(true)
      }
    }
  }

  async function handleUpload(usePhysicalLayer = true) {
    if (!storeId)          { setUploadStatus('Store not loaded yet — try again.'); return }
    if (!selectedCameraId) { setUploadStatus('Select a camera first.');            return }
    if (!file)             { setUploadStatus('Pick a video first.');               return }

    // Reset all state for a fresh run.
    framesRef.current = []
    setPersons(new Map())
    setNewPersonIds(new Set())
    setDbRows([])
    setDbTotal(0)
    setIsDone(false)
    setPlaybackIdx(0)
    setTotalFrames(0)
    setIsProcessing(true)
    setUploadStatus('Uploading…')

    openSocket()

    const form = new FormData()
    form.append('file',               file)
    form.append('physical_camera_id', selectedCameraId)
    form.append('store_id',           storeId)
    form.append('use_physical_layer', usePhysicalLayer ? 'true' : 'false')

    try {
      const res  = await fetch(`${IEP2_URL}/upload`, { method: 'POST', body: form })
      const data = await res.json()
      setUploadStatus(`Uploaded "${data.filename}" — processing…`)
    } catch (err) {
      setUploadStatus(`Upload failed: ${err.message}`)
    }
  }

  async function handleStop() {
    try {
      await fetch(`${IEP2_URL}/stop`, { method: 'POST' })
      setUploadStatus('Stopping…')
    } catch (err) {
      setUploadStatus(`Stop failed: ${err.message}`)
    }
  }

  return (
    <div className="flex-1 flex flex-col bg-[#111] text-gray-200 overflow-hidden" style={{ fontFamily: 'system-ui, sans-serif' }}>

      {/* Header */}
      <header className="px-6 py-4 border-b border-gray-700 shrink-0">
        <h1 className="text-lg font-semibold">Vision Debug Console</h1>
        <p className="text-xs text-gray-500 mt-0.5">Dev only · IEP2 upload · live bbox overlay · DB log</p>
      </header>

      {/* Upload bar */}
      <div className="px-6 py-3 border-b border-gray-800 flex items-center gap-4 flex-wrap shrink-0">
        {cameras.length === 0 ? (
          <span className="text-xs text-amber-400">
            {storeId ? 'No active cameras registered for this store.' : 'Loading cameras…'}
          </span>
        ) : (
          <label className="text-sm text-gray-400 flex items-center gap-2">
            Camera
            <select
              value={selectedCameraId}
              onChange={e => setSelectedCameraId(e.target.value)}
              className="px-2 py-1 bg-gray-800 border border-gray-600 rounded text-sm text-gray-200 focus:outline-none focus:border-blue-500"
            >
              <option value="">— select —</option>
              {cameras.map(c => (
                <option key={c.id} value={c.id}>
                  {c.name}{c.brand ? ` (${c.brand})` : ''}
                </option>
              ))}
            </select>
          </label>
        )}
        <input
          type="file"
          accept="video/*"
          onChange={e => setFile(e.target.files[0] || null)}
          className="text-sm text-gray-400"
        />
        <button
          onClick={() => handleUpload(true)}
          disabled={cameras.length === 0 || !selectedCameraId || isProcessing}
          className="px-4 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm rounded"
          title="Run with homography + floor projection + zone detection"
        >
          Run — Physical Layer
        </button>
        <button
          onClick={() => handleUpload(false)}
          disabled={cameras.length === 0 || !selectedCameraId || isProcessing}
          className="px-4 py-1.5 bg-gray-600 hover:bg-gray-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm rounded"
          title="Run ReID-only, no homography or floor projection"
        >
          Run — ReID Only
        </button>
        {isProcessing && (
          <button
            onClick={handleStop}
            className="px-4 py-1.5 bg-red-600 hover:bg-red-500 text-white text-sm rounded"
          >
            Stop
          </button>
        )}
        {uploadStatus && <span className="text-xs text-gray-400">{uploadStatus}</span>}
      </div>

      {/* Three-column body */}
      <div className="flex flex-1 overflow-hidden">

        {/* Left — live canvas */}
        <div className="flex-1 p-5 min-w-0 flex flex-col gap-2 overflow-auto">
          <h2 className="text-xs uppercase tracking-widest text-gray-500">Live View</h2>
          <canvas
            ref={liveCanvasRef}
            width={640}
            height={360}
            className="bg-black border border-gray-700 max-w-full block"
          />
        </div>

        {/* Center — playback (hidden until done) */}
        {isDone && (
          <div className="flex-1 p-5 min-w-0 border-l border-gray-800 flex flex-col gap-3 overflow-auto">
            <h2 className="text-xs uppercase tracking-widest text-gray-500">Playback</h2>
            <input
              type="range"
              min={0}
              max={Math.max(0, totalFrames - 1)}
              value={playbackIdx}
              onChange={e => setPlaybackIdx(parseInt(e.target.value, 10))}
              className="w-full"
            />
            <canvas
              ref={playbackCanvasRef}
              width={640}
              height={360}
              className="bg-black border border-gray-700 max-w-full block"
            />
            <p className="text-xs text-gray-500">
              Frame {playbackIdx} / {totalFrames - 1}
              {' · '}
              {(framesRef.current[playbackIdx]?.tracks || []).length} track(s)
            </p>
          </div>
        )}

        {/* Right — persons + DB log */}
        <div className="w-60 shrink-0 bg-[#1a1a1a] border-l border-gray-700 p-4 flex flex-col gap-6 overflow-y-auto">

          {/* Persons */}
          <div>
            <h2 className="text-xs uppercase tracking-widest text-gray-500 mb-2">Persons</h2>
            <div className="text-3xl font-bold text-green-400 mb-3">{persons.size}</div>
            <ul className="space-y-1 max-h-[40vh] overflow-y-auto">
              {[...persons.entries()].map(([localId, label]) => (
                <li
                  key={localId}
                  className={`text-xs px-2 py-1 rounded transition-colors duration-200 ${
                    newPersonIds.has(localId)
                      ? 'bg-green-900 text-green-300 font-bold'
                      : 'bg-gray-800 text-gray-300'
                  }`}
                >
                  L:{localId} — {label}
                </li>
              ))}
            </ul>
          </div>

          {/* DB log */}
          <div>
            <h2 className="text-xs uppercase tracking-widest text-gray-500 mb-1">DB Log</h2>
            <p className="text-xs text-gray-400 mb-2">{dbTotal} rows in tracking_history</p>
            <div className="overflow-auto max-h-[300px] border border-gray-700 rounded">
              <table className="w-full text-xs border-collapse">
                <thead className="sticky top-0 bg-[#1a1a1a]">
                  <tr className="text-gray-500 border-b border-gray-700">
                    <th className="text-left p-1">id</th>
                    <th className="text-left p-1">ts</th>
                    <th className="text-left p-1">x</th>
                    <th className="text-left p-1">y</th>
                    <th className="text-left p-1">zone</th>
                    <th className="text-left p-1">conf</th>
                  </tr>
                </thead>
                <tbody>
                  {dbRows.map((row, i) => (
                    <tr key={i} className="border-b border-gray-800 text-gray-300 hover:bg-gray-800">
                      <td className="p-1 font-mono">{row.local_id ? row.local_id.slice(0, 8) : '—'}</td>
                      <td className="p-1">{row.timestamp_ms}</td>
                      <td className="p-1">{row.floor_x  != null ? row.floor_x.toFixed(1)         : '—'}</td>
                      <td className="p-1">{row.floor_y  != null ? row.floor_y.toFixed(1)         : '—'}</td>
                      <td className="p-1">{row.zone_id  ? row.zone_id.slice(0, 8)                : '—'}</td>
                      <td className="p-1">{row.bbox_confidence != null ? row.bbox_confidence.toFixed(2) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

        </div>
      </div>
    </div>
  )
}
