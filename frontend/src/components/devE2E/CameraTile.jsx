import React, { useCallback, useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronRight, Download } from 'lucide-react'
import CameraDetails from './CameraDetails'

const BRIDGE_URL = import.meta.env.VITE_LIVE_BRIDGE_URL || 'ws://localhost:8010'
const STATUS_CFG = {
  connected: { dot: 'bg-green-500', text: 'Live' },
  connecting: { dot: 'bg-amber-500', text: 'Connecting' },
  error: { dot: 'bg-red-500', text: 'Error' },
  disconnected: { dot: 'bg-gray-400', text: 'Idle' },
}

// Compact live tile (VD2 progressive disclosure): feed + bboxes labelled with the
// SHARED global identity number/color, a one-line stat, details behind an expander.
export default function CameraTile({ label, cameraId, cameraName, running, rows = [], frameUrl, identity, localGlobal = {}, camColor }) {
  const canvasRef = useRef(null)
  const wsRef = useRef(null)
  const framesRef = useRef([])
  const [status, setStatus] = useState('disconnected')
  const [detCount, setDetCount] = useState(0)
  const [frameCount, setFrameCount] = useState(0)
  const [replayIdx, setReplayIdx] = useState(null)
  const [open, setOpen] = useState(false)

  const globalOf = useCallback((localId) => localGlobal[`${cameraId}:${localId}`], [localGlobal, cameraId])

  const renderItem = useCallback((data) => {
    const dets = Array.isArray(data.detections) ? data.detections : []
    setDetCount(dets.length)
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    const paint = () => {
      ctx.lineWidth = 2; ctx.font = 'bold 12px monospace'
      dets.forEach((d) => {
        const gid = d.local_id ? globalOf(d.local_id) : null
        const id = identity.get(gid)
        const color = gid ? id.color : '#f59e0b'
        ctx.strokeStyle = color
        ctx.strokeRect(d.x1, d.y1, d.x2 - d.x1, d.y2 - d.y1)
        let lbl = gid ? `#${id.number}` : 'pending'
        if (d.reid_sim != null) lbl += ` ${d.reid_sim.toFixed(2)}${d.reid_matched ? '✓' : '✗'}`
        const tw = ctx.measureText(lbl).width
        const ly = d.y1 > 16 ? d.y1 - 4 : d.y2 + 14
        ctx.fillStyle = color; ctx.fillRect(d.x1 - 1, ly - 12, tw + 8, 15)
        ctx.fillStyle = '#fff'; ctx.fillText(lbl, d.x1 + 3, ly - 1)
        ctx.beginPath(); ctx.arc((d.x1 + d.x2) / 2, d.y2, 4, 0, 2 * Math.PI)
        ctx.fillStyle = color; ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5; ctx.fill(); ctx.stroke(); ctx.lineWidth = 2
      })
    }
    if (data.frame_b64 || data.frame_url) {
      const img = new window.Image()
      if (data.frame_url) img.crossOrigin = 'anonymous'
      img.onload = () => {
        if (canvas.width !== img.naturalWidth) canvas.width = img.naturalWidth
        if (canvas.height !== img.naturalHeight) canvas.height = img.naturalHeight
        ctx.drawImage(img, 0, 0); paint()
      }
      img.src = data.frame_b64 ? `data:image/jpeg;base64,${data.frame_b64}` : data.frame_url
    } else { ctx.clearRect(0, 0, canvas.width, canvas.height); paint() }
  }, [globalOf, identity])

  useEffect(() => {
    if (!running || !cameraId) { setStatus('disconnected'); return }
    framesRef.current = []; setFrameCount(0); setReplayIdx(null); setDetCount(0); setStatus('connecting')
    const ws = new WebSocket(`${BRIDGE_URL}/ws/live/${cameraId}`)
    wsRef.current = ws
    ws.onopen = () => setStatus('connected')
    ws.onerror = () => setStatus('error')
    ws.onclose = () => setStatus('disconnected')
    ws.onmessage = (e) => {
      try {
        const item = JSON.parse(e.data); const buf = framesRef.current
        buf.push(item); if (buf.length > 2000) buf.shift()
        setFrameCount(buf.length); renderItem(item)
      } catch {}
    }
    return () => ws.close()
  }, [running, cameraId, renderItem])

  useEffect(() => {
    if (running) return
    const n = framesRef.current.length
    if (n > 0) { setReplayIdx(n - 1); renderItem(framesRef.current[n - 1]) }
  }, [running, renderItem])

  const seek = (i) => {
    const n = framesRef.current.length
    if (!n) return
    const idx = Math.max(0, Math.min(i, n - 1)); setReplayIdx(idx); renderItem(framesRef.current[idx])
  }

  const st = STATUS_CFG[status]
  const inReplay = !running && replayIdx !== null && frameCount > 0
  const frameLabel = inReplay ? `Frame ${replayIdx + 1}/${frameCount}` : `Frame ${frameCount}`

  function saveJpeg() {
    if (!canvasRef.current) return
    const a = document.createElement('a')
    a.href = canvasRef.current.toDataURL('image/jpeg', 0.92)
    a.download = `snapshot_${label}_${Date.now()}.jpg`; a.click()
  }

  return (
    <div className="flex flex-col bg-white border border-gray-200 rounded-xl overflow-hidden">
      <div className="px-3 py-2 border-b border-gray-100 flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2 min-w-0">
          <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: camColor }} />
          {label}<span className="text-xs font-normal text-gray-400 truncate">{cameraName}</span>
        </h3>
        <div className="flex items-center gap-1.5 shrink-0">
          <span className="text-[11px] font-mono text-gray-500">{frameLabel}</span>
          <span className={`w-2 h-2 rounded-full ${st.dot}`} />
          <span className="text-xs text-gray-500">{inReplay ? 'Replay' : st.text}</span>
        </div>
      </div>

      <div className="relative bg-gray-900 flex items-center justify-center" style={{ minHeight: 160 }}>
        <canvas ref={canvasRef} width={640} height={360} className="block max-w-full" />
      </div>

      <div className="px-3 py-1.5 border-t border-gray-100 text-xs text-gray-500 flex items-center justify-between">
        <span>dets <b className="text-gray-700">{detCount}</b> · rows <b className="text-gray-700">{rows.length}</b></span>
        <div className="flex items-center gap-2">
          <button onClick={saveJpeg} title="Save JPEG" className="text-gray-400 hover:text-gray-600"><Download size={13} /></button>
          <button onClick={() => setOpen((o) => !o)} className="flex items-center gap-1 text-gray-500 hover:text-gray-700">
            {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />} Details
          </button>
        </div>
      </div>

      {open && (
        <CameraDetails
          cameraId={cameraId} rows={rows} frameUrl={frameUrl} identity={identity}
          globalOf={globalOf} inReplay={inReplay} replayIdx={replayIdx} frameCount={frameCount} onSeek={seek}
        />
      )}
    </div>
  )
}
