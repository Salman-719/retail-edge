import React, { useEffect, useRef, useState, useCallback } from 'react'
import { usePageTitle } from '../components/PageMeta'

const BRIDGE_URL = import.meta.env.VITE_LIVE_BRIDGE_URL || ''
const CAMERAS = (import.meta.env.VITE_CAMERAS || '')
  .split(',')
  .map(c => c.trim())
  .filter(Boolean)

const CANVAS_W = 640
const CANVAS_H = 360

const STATUS_CFG = {
  connected:    { dot: 'bg-green-400 animate-pulse', text: 'Live' },
  connecting:   { dot: 'bg-yellow-400',              text: 'Connecting…' },
  disconnected: { dot: 'bg-gray-400',                text: 'Disconnected' },
  error:        { dot: 'bg-red-500',                 text: 'Error' },
}

export default function LiveView() {
  usePageTitle('Live View')

  const [selectedCamera, setSelectedCamera] = useState(CAMERAS[0] || '')
  const [detections, setDetections]         = useState([])
  const [status, setStatus]                 = useState('disconnected')

  const canvasRef = useRef(null)
  const wsRef     = useRef(null)

  const drawFrame = useCallback((data) => {
    const dets = Array.isArray(data.detections) ? data.detections : []
    // Update table immediately — don't wait for image to load
    setDetections(dets)

    const canvas = canvasRef.current
    if (!canvas || !data.frame_url) return
    const ctx = canvas.getContext('2d')

    const img = new window.Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => {
      ctx.drawImage(img, 0, 0, CANVAS_W, CANVAS_H)

      dets.forEach(det => {
        const x1 = Math.max(0, Math.min(det.x1, CANVAS_W))
        const y1 = Math.max(0, Math.min(det.y1, CANVAS_H))
        const x2 = Math.max(0, Math.min(det.x2, CANVAS_W))
        const y2 = Math.max(0, Math.min(det.y2, CANVAS_H))

        ctx.strokeStyle = '#22c55e'
        ctx.lineWidth = 2
        ctx.strokeRect(x1, y1, x2 - x1, y2 - y1)

        const label = `#${det.track_id}`
        ctx.font = 'bold 11px monospace'
        const tw = ctx.measureText(label).width
        const lx = x1
        const ly = y1 > 16 ? y1 - 4 : y2 + 14

        ctx.fillStyle = 'rgba(0,0,0,0.65)'
        ctx.fillRect(lx - 1, ly - 12, tw + 8, 15)
        ctx.fillStyle = '#ffffff'
        ctx.fillText(label, lx + 3, ly - 1)
      })
    }
    img.onerror = () => {}
    img.src = data.frame_url
  }, [])

  useEffect(() => {
    if (!BRIDGE_URL || !selectedCamera) return

    setStatus('connecting')
    setDetections([])

    const ws = new WebSocket(`${BRIDGE_URL}/ws/live/${selectedCamera}`)
    wsRef.current = ws

    ws.onopen    = () => setStatus('connected')
    ws.onerror   = () => setStatus('error')
    ws.onclose   = () => setStatus('disconnected')
    ws.onmessage = (e) => {
      try { drawFrame(JSON.parse(e.data)) } catch {}
    }

    return () => { ws.close() }
  }, [selectedCamera, drawFrame])

  const st = STATUS_CFG[status]

  if (!BRIDGE_URL) {
    return (
      <div className="page-enter flex flex-col h-full overflow-hidden">
        <header className="bg-white border-b border-gray-200 px-6 py-4 shrink-0">
          <h1 className="page-title">Live View</h1>
          <p className="page-subtitle">Camera feed with detection overlay</p>
        </header>
        <div className="flex-1 flex items-center justify-center p-5">
          <div className="bg-red-50 border border-red-200 rounded-xl px-6 py-5 text-center max-w-sm">
            <p className="text-red-700 font-semibold text-sm mb-1">VITE_LIVE_BRIDGE_URL not configured</p>
            <p className="text-red-400 text-xs">Set this environment variable and restart the dev server.</p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="page-enter flex flex-col h-full overflow-hidden">

      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <header className="bg-white border-b border-gray-200 px-6 py-4 shrink-0 flex items-center justify-between">
        <div>
          <h1 className="page-title">Live View</h1>
          <p className="page-subtitle">Camera feed with detection overlay</p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${st.dot}`} />
          <span className="text-xs text-gray-500">{st.text}</span>
        </div>
      </header>

      <div className="flex-1 overflow-auto p-5 space-y-4">

        {/* ── Camera selector ─────────────────────────────────────────────── */}
        <div className="flex items-center gap-3">
          <label className="text-sm font-medium text-gray-700 shrink-0">Camera</label>
          {CAMERAS.length === 0 ? (
            <span className="text-sm text-gray-400">No cameras configured</span>
          ) : (
            <select
              value={selectedCamera}
              onChange={e => setSelectedCamera(e.target.value)}
              className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm text-gray-700 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {CAMERAS.map(cam => (
                <option key={cam} value={cam}>{cam}</option>
              ))}
            </select>
          )}
        </div>

        {/* ── Main panel ──────────────────────────────────────────────────── */}
        <div className="flex flex-col lg:flex-row gap-4 items-start">

          {/* Canvas */}
          <div className="relative shrink-0 rounded-xl overflow-hidden bg-gray-900 border border-gray-800"
               style={{ width: CANVAS_W, height: CANVAS_H }}>
            <canvas ref={canvasRef} width={CANVAS_W} height={CANVAS_H} className="block" />

            {/* Status badge overlay */}
            <div className="absolute top-2 right-2 flex items-center gap-1.5 bg-black/60 backdrop-blur-sm rounded-full px-2.5 py-1">
              <span className={`w-2 h-2 rounded-full ${st.dot}`} />
              <span className="text-xs text-white font-medium">{st.text}</span>
            </div>
          </div>

          {/* ── Detections table ──────────────────────────────────────────── */}
          <div className="bg-white border border-gray-200 rounded-xl flex-1 flex flex-col overflow-hidden"
               style={{ maxHeight: CANVAS_H }}>
            <div className="px-4 py-3 border-b border-gray-100 shrink-0">
              <h2 className="text-sm font-semibold text-gray-700">
                Detections
                {detections.length > 0 && (
                  <span className="ml-2 text-xs font-normal text-gray-400">{detections.length} tracked</span>
                )}
              </h2>
            </div>

            <div className="overflow-y-auto flex-1 min-h-0">
              {detections.length === 0 ? (
                <div className="flex items-center justify-center h-full text-gray-400 text-sm">
                  No detections
                </div>
              ) : (
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-white border-b border-gray-100">
                    <tr>
                      <th className="px-4 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Track</th>
                      <th className="px-4 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Local ID</th>
                      <th className="px-4 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Conf</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detections.map((det, i) => (
                      <tr key={det.track_id} className={i % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                        <td className="px-4 py-2 font-mono text-gray-800 text-xs">#{det.track_id}</td>
                        <td className="px-4 py-2 font-mono text-xs text-gray-600">
                          {det.local_id != null
                            ? String(det.local_id).slice(0, 8)
                            : <span className="text-gray-400 italic">pending</span>}
                        </td>
                        <td className="px-4 py-2 text-gray-700 text-xs">{Math.round(det.confidence * 100)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>

        </div>
      </div>
    </div>
  )
}
