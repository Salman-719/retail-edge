/*
 * DEV-ONLY end-to-end pipeline tester.
 * Route: /store/:slug/dev/e2e  (only mounted when import.meta.env.DEV)
 *
 * Up to 1/2/4/6 cameras in parallel through the real IEP1 → IEP2 → IEP3
 * pipeline. Only cameras in the active store config version are selectable.
 * Each panel shows live feed + bounding boxes + foot-point dots, a TrackMap
 * with zone overlays, and a FootPointFrame snapshot after Stop.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { usePageTitle } from '../components/PageMeta'
import {
  getStore, listCameras, getActiveVersion,
  devPipelineStart, devPipelineStop,
  getDevTracking, getDevIep3, getDevGpuStatus,
} from '../api'

const BRIDGE_URL        = import.meta.env.VITE_LIVE_BRIDGE_URL || 'ws://localhost:8010'
const NUM_CAMS_OPTIONS  = [1, 2, 4, 6]

const ZONE_FILL = {
  entrance:   'rgba(59,130,246,0.15)',
  checkout:   'rgba(245,158,11,0.15)',
  aisle:      'rgba(16,185,129,0.15)',
  staff_only: 'rgba(239,68,68,0.15)',
  general:    'rgba(139,92,246,0.15)',
}
const ZONE_STROKE = {
  entrance:   'rgba(59,130,246,0.75)',
  checkout:   'rgba(245,158,11,0.75)',
  aisle:      'rgba(16,185,129,0.75)',
  staff_only: 'rgba(239,68,68,0.75)',
  general:    'rgba(139,92,246,0.75)',
}
const TRACK_COLOURS = ['#60a5fa', '#f59e0b', '#34d399', '#f472b6', '#a78bfa', '#fb923c']

const STATUS_CFG = {
  connected:    { dot: 'bg-green-400 animate-pulse', text: 'Live' },
  connecting:   { dot: 'bg-yellow-400',              text: 'Connecting…' },
  disconnected: { dot: 'bg-gray-400',                text: 'Idle' },
  error:        { dot: 'bg-red-500',                 text: 'Error' },
}

function fmtTs(ms) {
  if (!ms) return '—'
  const d = new Date(Number(ms))
  return d.toLocaleTimeString('en-GB', { hour12: false }) + '.' + String(d.getMilliseconds()).padStart(3, '0')
}
function fmtNum(v, dp = 2) {
  return (v === null || v === undefined) ? '—' : Number(v).toFixed(dp)
}
function shortId(v) { return v ? String(v).slice(0, 8) : null }

function makeNumberer() {
  const map = new Map(); let next = 1
  return (id) => {
    if (id == null || id === '') return null
    const k = String(id)
    if (!map.has(k)) map.set(k, next++)
    return map.get(k)
  }
}

/* ─── TrackMap ─────────────────────────────────────────────────────────────── */
function TrackMap({ rows = [], zones = [], title }) {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx  = canvas.getContext('2d')
    const W = canvas.width, H = canvas.height
    ctx.clearRect(0, 0, W, H)
    ctx.fillStyle = '#111827'
    ctx.fillRect(0, 0, W, H)

    const allX = [], allY = []
    rows.forEach(r  => { if (r.floor_x != null) allX.push(r.floor_x); if (r.floor_y != null) allY.push(r.floor_y) })
    zones.forEach(z => (z.points || []).forEach(([px, py]) => { allX.push(px); allY.push(py) }))

    if (allX.length === 0) {
      ctx.fillStyle = '#4b5563'; ctx.font = '11px monospace'
      ctx.fillText('no data', W / 2 - 22, H / 2)
      return
    }

    const pad  = 18
    const minX = Math.min(...allX), maxX = Math.max(...allX)
    const minY = Math.min(...allY), maxY = Math.max(...allY)
    const rx   = maxX - minX || 1,  ry  = maxY - minY || 1
    const wx   = x => pad + (x - minX) / rx * (W - 2 * pad)
    const wy   = y => H - pad - (y - minY) / ry * (H - 2 * pad)

    // Zone polygons
    for (const zone of zones) {
      const pts = zone.points || []
      if (pts.length < 2) continue
      ctx.beginPath()
      ctx.moveTo(wx(pts[0][0]), wy(pts[0][1]))
      for (let i = 1; i < pts.length; i++) ctx.lineTo(wx(pts[i][0]), wy(pts[i][1]))
      ctx.closePath()
      ctx.fillStyle   = ZONE_FILL[zone.type]   || 'rgba(107,114,128,0.15)'
      ctx.strokeStyle = ZONE_STROKE[zone.type] || 'rgba(107,114,128,0.5)'
      ctx.lineWidth   = 1.5
      ctx.fill(); ctx.stroke()
      // label at centroid
      const cx = pts.reduce((s, p) => s + p[0], 0) / pts.length
      const cy = pts.reduce((s, p) => s + p[1], 0) / pts.length
      ctx.fillStyle = ZONE_STROKE[zone.type] || 'rgba(156,163,175,0.9)'
      ctx.font = '9px monospace'
      ctx.fillText(zone.type || '', wx(cx) - 14, wy(cy))
    }

    // Track dots
    const colMap = new Map(); let colIdx = 0
    let inZone = 0, offCanvas = 0
    for (const r of rows) {
      if (r.floor_x == null || r.floor_y == null) { offCanvas++; continue }
      const px = wx(r.floor_x), py = wy(r.floor_y)
      if (px < 0 || px > W || py < 0 || py > H) { offCanvas++; continue }
      if (r.inZone) inZone++
      let colour
      if (r.inZone) {
        colour = 'rgba(34,197,94,0.85)'
      } else {
        const k = String(r.local_id)
        if (!colMap.has(k)) colMap.set(k, TRACK_COLOURS[colIdx++ % TRACK_COLOURS.length])
        colour = colMap.get(k)
      }
      ctx.beginPath(); ctx.arc(px, py, 3.5, 0, 2 * Math.PI)
      ctx.fillStyle = colour; ctx.fill()
    }

    ctx.fillStyle = 'rgba(156,163,175,0.8)'; ctx.font = '9px monospace'
    ctx.fillText(`${rows.length} pts · ${inZone} in zone · ${offCanvas} off-canvas`, 4, H - 5)
  }, [rows, zones])

  return (
    <div className="mt-2">
      {title && <p className="text-[11px] font-medium text-gray-500 mb-1">{title}</p>}
      <canvas ref={canvasRef} width={300} height={180}
        className="rounded border border-gray-700 block w-full" style={{ background: '#111827' }} />
    </div>
  )
}

/* ─── FootPointFrame ─────────────────────────────────────────────────────── */
function FootPointFrame({ title, frameUrl, rows = [] }) {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')

    const draw = (img) => {
      canvas.width  = img ? img.naturalWidth  : 640
      canvas.height = img ? img.naturalHeight : 360
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      if (img) {
        ctx.drawImage(img, 0, 0)
      } else {
        ctx.fillStyle = '#1f2937'; ctx.fillRect(0, 0, canvas.width, canvas.height)
        ctx.fillStyle = '#4b5563'; ctx.font = '13px monospace'
        ctx.fillText('no frame available', 20, canvas.height / 2)
      }
      ctx.lineWidth = 1.5
      for (const r of rows) {
        if (r.bbox_x1 == null || r.bbox_x2 == null || r.bbox_y2 == null) continue
        const u = (r.bbox_x1 + r.bbox_x2) / 2
        const v = r.bbox_y2
        ctx.beginPath(); ctx.arc(u, v, 5, 0, 2 * Math.PI)
        ctx.fillStyle = 'rgba(239,68,68,0.85)'; ctx.strokeStyle = '#fff'
        ctx.fill(); ctx.stroke()
      }
    }

    if (frameUrl) {
      const img = new window.Image()
      img.crossOrigin = 'anonymous'
      img.onload  = () => draw(img)
      img.onerror = () => draw(null)
      img.src = frameUrl
    } else {
      draw(null)
    }
  }, [frameUrl, rows])

  return (
    <div className="mt-2">
      {title && <p className="text-[11px] font-medium text-gray-500 mb-1">{title}</p>}
      <canvas ref={canvasRef}
        className="rounded border border-gray-200 block w-full"
        style={{ maxHeight: 320, objectFit: 'contain' }} />
    </div>
  )
}

/* ─── CameraPanel ─────────────────────────────────────────────────────────── */
function CameraPanel({ title, cameraId, cameraName, running, zones, frameUrl }) {
  const canvasRef   = useRef(null)
  const wsRef       = useRef(null)
  const framesRef   = useRef([])
  const localNumRef = useRef(makeNumberer())

  const [status,     setStatus]     = useState('disconnected')
  const [detections, setDetections] = useState([])
  const [rows,       setRows]       = useState([])
  const [total,      setTotal]      = useState(0)
  const [frameCount, setFrameCount] = useState(0)
  const [replayIdx,  setReplayIdx]  = useState(null)

  // Derive inZone flag for TrackMap
  const trackRows = rows.map(r => ({ ...r, inZone: !!r.zone_id }))

  const renderItem = useCallback((data) => {
    const dets = Array.isArray(data.detections) ? data.detections : []
    setDetections(dets)
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')

    const paintBoxes = () => {
      ctx.lineWidth = 2
      ctx.font = 'bold 12px monospace'
      dets.forEach(d => {
        // bounding box
        ctx.strokeStyle = d.local_id ? '#22c55e' : '#f59e0b'
        ctx.strokeRect(d.x1, d.y1, d.x2 - d.x1, d.y2 - d.y1)
        // label
        const label = d.local_id ? `ID ${localNumRef.current(d.local_id)}` : 'pending'
        const tw = ctx.measureText(label).width
        const ly = d.y1 > 16 ? d.y1 - 4 : d.y2 + 14
        ctx.fillStyle = 'rgba(0,0,0,0.65)'; ctx.fillRect(d.x1 - 1, ly - 12, tw + 8, 15)
        ctx.fillStyle = '#fff'; ctx.fillText(label, d.x1 + 3, ly - 1)
        // foot-point dot at bottom-centre of bbox
        ctx.beginPath(); ctx.arc((d.x1 + d.x2) / 2, d.y2, 5, 0, 2 * Math.PI)
        ctx.fillStyle = '#ef4444'; ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5
        ctx.fill(); ctx.stroke()
        ctx.lineWidth = 2
      })
    }

    if (data.frame_b64 || data.frame_url) {
      const img = new window.Image()
      if (data.frame_url) img.crossOrigin = 'anonymous'
      img.onload = () => {
        if (canvas.width  !== img.naturalWidth)  canvas.width  = img.naturalWidth
        if (canvas.height !== img.naturalHeight) canvas.height = img.naturalHeight
        ctx.drawImage(img, 0, 0); paintBoxes()
      }
      img.onerror = () => {}
      img.src = data.frame_b64 ? `data:image/jpeg;base64,${data.frame_b64}` : data.frame_url
    } else {
      ctx.clearRect(0, 0, canvas.width, canvas.height); paintBoxes()
    }
  }, [])

  // WebSocket — connect while running
  useEffect(() => {
    if (!running || !cameraId) { setStatus('disconnected'); return }
    framesRef.current = []
    localNumRef.current = makeNumberer()
    setFrameCount(0); setReplayIdx(null); setDetections([])
    setStatus('connecting')
    const ws = new WebSocket(`${BRIDGE_URL}/ws/live/${cameraId}`)
    wsRef.current = ws
    ws.onopen  = () => setStatus('connected')
    ws.onerror = () => setStatus('error')
    ws.onclose = () => setStatus('disconnected')
    ws.onmessage = (e) => {
      try {
        const item = JSON.parse(e.data)
        const buf  = framesRef.current
        buf.push(item)
        if (buf.length > 2000) buf.shift()
        setFrameCount(buf.length)
        renderItem(item)
      } catch {}
    }
    return () => ws.close()
  }, [running, cameraId, renderItem])

  // On Stop: freeze on last frame
  useEffect(() => {
    if (running) return
    const n = framesRef.current.length
    if (n > 0) { setReplayIdx(n - 1); renderItem(framesRef.current[n - 1]) }
  }, [running, renderItem])

  const seekReplay = (i) => {
    const n = framesRef.current.length
    if (n === 0) return
    const idx = Math.max(0, Math.min(i, n - 1))
    setReplayIdx(idx); renderItem(framesRef.current[idx])
  }

  // Tracking history poll
  useEffect(() => {
    if (!running || !cameraId) return
    let alive = true
    const tick = async () => {
      try {
        const d = await getDevTracking(cameraId, 40)
        if (alive) { setRows(d.rows || []); setTotal(d.total || 0) }
      } catch {}
    }
    tick()
    const id = setInterval(tick, 2000)
    return () => { alive = false; clearInterval(id) }
  }, [running, cameraId])

  const st       = STATUS_CFG[status]
  const inReplay = !running && replayIdx !== null && frameCount > 0
  const frameLabel = inReplay ? `Frame ${replayIdx + 1} / ${frameCount}` : `Frame ${frameCount}`

  return (
    <div className="flex flex-col bg-white border border-gray-200 rounded-xl overflow-hidden">
      {/* header */}
      <div className="px-4 py-2.5 border-b border-gray-100 flex items-center justify-between shrink-0">
        <h3 className="text-sm font-semibold text-gray-700">
          {title}
          <span className="ml-2 text-xs font-normal text-gray-400">{cameraName || cameraId || '—'}</span>
        </h3>
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-mono text-gray-500">{frameLabel}</span>
          <span className={`w-2 h-2 rounded-full ${st.dot}`} />
          <span className="text-xs text-gray-500">{inReplay ? 'Replay' : st.text}</span>
        </div>
      </div>

      {/* live canvas */}
      <div className="relative bg-gray-900 flex items-center justify-center" style={{ minHeight: 180 }}>
        <canvas ref={canvasRef} width={640} height={360} className="block max-w-full" />
        <div className="absolute top-2 left-2 bg-black/60 text-white text-[11px] font-mono px-2 py-0.5 rounded">
          {frameLabel}
        </div>
      </div>

      {/* snapshot */}
      <div className="px-3 py-1.5 border-t border-gray-100 flex justify-end bg-gray-50 shrink-0">
        <button
          onClick={() => {
            if (!canvasRef.current) return
            const a = document.createElement('a')
            a.href     = canvasRef.current.toDataURL('image/jpeg', 0.92)
            a.download = `snapshot_${shortId(cameraId)}_${Date.now()}.jpg`
            a.click()
          }}
          className="text-xs px-3 py-1 rounded border border-gray-300 bg-white hover:bg-gray-100 text-gray-600"
        >
          ⬇ Save frame as JPEG
        </button>
      </div>

      {/* replay scrubber */}
      {inReplay && (
        <div className="px-3 py-2 border-t border-gray-100 flex items-center gap-2 bg-gray-50">
          <button onClick={() => seekReplay(replayIdx - 1)} className="px-2 py-0.5 text-xs rounded border border-gray-300 bg-white hover:bg-gray-100">◀</button>
          <input type="range" min={0} max={Math.max(0, frameCount - 1)} value={replayIdx}
            onChange={e => seekReplay(Number(e.target.value))} className="flex-1 accent-blue-600" />
          <button onClick={() => seekReplay(replayIdx + 1)} className="px-2 py-0.5 text-xs rounded border border-gray-300 bg-white hover:bg-gray-100">▶</button>
        </div>
      )}

      {/* stats */}
      <div className="px-3 py-1.5 border-t border-gray-100 text-xs text-gray-500 flex justify-between shrink-0">
        <span>{inReplay ? 'Replay' : 'Live'} dets: <b className="text-gray-700">{detections.length}</b></span>
        <span>tracking rows: <b className="text-gray-700">{total}</b></span>
      </div>

      {/* tracking table */}
      <div className="overflow-y-auto" style={{ maxHeight: 200 }}>
        {rows.length === 0 ? (
          <div className="py-4 text-center text-gray-400 text-sm">No tracking rows yet</div>
        ) : (
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-white border-b border-gray-100">
              <tr>
                <th className="px-2 py-1.5 text-left font-semibold text-gray-500">Local ID</th>
                <th className="px-2 py-1.5 text-left font-semibold text-gray-500">Time</th>
                <th className="px-2 py-1.5 text-right font-semibold text-gray-500">floor_x</th>
                <th className="px-2 py-1.5 text-right font-semibold text-gray-500">floor_y</th>
                <th className="px-2 py-1.5 text-left font-semibold text-gray-500">Zone</th>
                <th className="px-2 py-1.5 text-right font-semibold text-gray-500">Conf</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={`${r.local_id}-${r.timestamp_ms}-${i}`} className={i % 2 ? 'bg-gray-50' : 'bg-white'}>
                  <td className="px-2 py-1 font-mono text-gray-700">{localNumRef.current(r.local_id) ?? '—'}</td>
                  <td className="px-2 py-1 font-mono text-gray-500">{fmtTs(r.timestamp_ms)}</td>
                  <td className="px-2 py-1 text-right text-gray-700">{fmtNum(r.floor_x)}</td>
                  <td className="px-2 py-1 text-right text-gray-700">{fmtNum(r.floor_y)}</td>
                  <td className="px-2 py-1 font-mono text-gray-500">{shortId(r.zone_id) || '—'}</td>
                  <td className="px-2 py-1 text-right text-gray-700">{fmtNum((r.bbox_confidence ?? 0) * 100, 0)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* TrackMap + FootPointFrame */}
      <div className="px-3 py-2 border-t border-gray-100 bg-gray-50">
        <TrackMap rows={trackRows} zones={zones} title="Track map" />
        {!running && rows.length > 0 && (
          <FootPointFrame
            title="Foot-point overlay"
            frameUrl={frameUrl || null}
            rows={rows}
          />
        )}
      </div>
    </div>
  )
}

/* ─── DevE2E ──────────────────────────────────────────────────────────────── */
export default function DevE2E() {
  usePageTitle('Dev E2E Pipeline')
  const { slug } = useParams()

  const [storeId,    setStoreId]    = useState('')
  const [cameras,    setCameras]    = useState([])          // active cams only
  const [camSlots,   setCamSlots]   = useState(Array(6).fill(''))
  const [numCams,    setNumCams]    = useState(2)           // 1 | 2 | 4 | 6
  const [zones,      setZones]      = useState([])
  const [frameUrls,  setFrameUrls]  = useState({})          // physical_camera_id → frame_url
  const [running,    setRunning]    = useState(false)
  const [busy,       setBusy]       = useState(false)
  const [error,      setError]      = useState('')
  const [iep3,       setIep3]       = useState({ summary: {}, rows: [] })
  const [device,     setDevice]     = useState('cpu')
  const [gpu,        setGpu]        = useState(null)
  const globalNumRef = useRef(makeNumberer())

  // Load store, active-version cameras, zones, frame URLs
  useEffect(() => {
    (async () => {
      try {
        const [store, cams, version] = await Promise.all([
          getStore(slug),
          listCameras(slug),
          getActiveVersion(slug).catch(() => null),
        ])
        setStoreId(store.id)

        const urls = {}, activePcIds = new Set()
        for (const cc of (version?.camera_configs || [])) {
          const pid = String(cc.physical_camera_id)
          activePcIds.add(pid)
          if (cc.frame_url) urls[pid] = cc.frame_url
        }
        setFrameUrls(urls)
        setZones(version?.zones || [])

        // Only cameras that appear in the active version (or is_active fallback)
        const activeCams = (cams || []).filter(c =>
          activePcIds.size > 0 ? activePcIds.has(String(c.id)) : c.is_active
        )
        setCameras(activeCams)

        // Auto-fill slots 0…n with available cameras
        const slots = Array(6).fill('')
        activeCams.slice(0, 6).forEach((c, i) => { slots[i] = String(c.id) })
        setCamSlots(slots)
      } catch {
        setError('Failed to load store / cameras')
      }
      try {
        const g = await getDevGpuStatus()
        setGpu(g)
        if (g.gpu_available) setDevice('gpu')
      } catch { setGpu({ gpu_available: false }) }
    })()
  }, [slug])

  // IEP3 poll while running
  useEffect(() => {
    if (!running || !storeId) return
    let alive = true
    const tick = async () => {
      try {
        const d = await getDevIep3(storeId, 60)
        if (alive) setIep3(d)
      } catch {}
    }
    tick()
    const id = setInterval(tick, 2500)
    return () => { alive = false; clearInterval(id) }
  }, [running, storeId])

  const nameOf   = (id) => cameras.find(c => String(c.id) === String(id))?.name || shortId(id)
  const camLabel = (id) => {
    const idx = camSlots.findIndex(s => String(s) === String(id))
    return idx >= 0 ? `Cam ${idx + 1}` : shortId(id)
  }

  // Only slots within [0, numCams) that have a value
  const activeCamIds = () => camSlots.slice(0, numCams).filter(Boolean)

  const handleStart = async () => {
    setError('')
    const ids = activeCamIds()
    if (ids.length === 0) { setError('Select at least one camera'); return }
    const dupes = ids.filter((id, i) => ids.indexOf(id) !== i)
    if (dupes.length) { setError('Each camera can only be selected once'); return }
    globalNumRef.current = makeNumberer()
    setBusy(true)
    try {
      const res = await devPipelineStart({
        store_id: storeId, camera_ids: ids,
        target_fps: 5.0, window_seconds: 60.0, device,
      })
      const failed = (res.cameras || []).filter(c => !c.ok)
      if (failed.length)
        setError('Some cameras failed: ' + failed.map(f => `${shortId(f.camera_id)} (${f.stage}: ${f.error})`).join('; '))
      setRunning(true)
    } catch (e) {
      const detail = e?.response?.data?.detail
      if (detail?.code === 'NO_GPU') {
        setError('No usable GPU — switch to CPU or run on a GPU machine.')
        setDevice('cpu')
      } else {
        setError(typeof detail === 'string' ? detail : (detail?.error || 'Start failed'))
      }
    } finally { setBusy(false) }
  }

  const handleStop = async () => {
    setBusy(true)
    try { await devPipelineStop({ store_id: storeId, camera_ids: activeCamIds() }) } catch {}
    setRunning(false); setBusy(false)
  }

  const updateSlot = (i, v) => setCamSlots(prev => prev.map((x, j) => j === i ? v : x))

  // Grid class based on numCams
  const gridClass = numCams === 6 ? 'grid-cols-1 md:grid-cols-2 xl:grid-cols-3'
                  : numCams >= 2  ? 'grid-cols-1 lg:grid-cols-2'
                                  : 'grid-cols-1'

  const slots = camSlots.slice(0, numCams)
  const s     = iep3.summary || {}

  return (
    <div className="page-enter flex flex-col h-full overflow-hidden">
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <header className="bg-white border-b border-gray-200 px-6 py-4 shrink-0 flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="page-title">Dev E2E Pipeline</h1>
          <p className="page-subtitle">IEP1 → IEP2 → IEP3 · up to {numCams} camera{numCams > 1 ? 's' : ''}</p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          {error && (
            <span className="text-xs text-red-600 max-w-sm truncate" title={error}>{error}</span>
          )}

          {/* cam-count toggle */}
          <div className="inline-flex rounded-lg border border-gray-300 overflow-hidden text-sm">
            {NUM_CAMS_OPTIONS.map(n => (
              <button key={n} onClick={() => !running && setNumCams(n)} disabled={running}
                className={`px-3 py-1.5 font-semibold ${
                  numCams === n ? 'bg-blue-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'
                } ${running ? 'opacity-60 cursor-not-allowed' : ''}`}>
                {n}
              </button>
            ))}
          </div>

          {/* CPU / GPU toggle */}
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-gray-400"
              title={gpu ? `detector: ${JSON.stringify(gpu.detector)} · reid: ${JSON.stringify(gpu.reid)}` : ''}>
              GPU: {gpu ? (gpu.gpu_available ? 'available' : 'none') : '…'}
            </span>
            <div className="inline-flex rounded-lg border border-gray-300 overflow-hidden text-sm">
              {['cpu', 'gpu'].map(d => (
                <button key={d} onClick={() => !running && setDevice(d)} disabled={running}
                  className={`px-3 py-1.5 font-semibold uppercase ${
                    device === d ? 'bg-blue-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'
                  } ${running ? 'opacity-60 cursor-not-allowed' : ''}`}>
                  {d}
                </button>
              ))}
            </div>
          </div>

          {!running ? (
            <button onClick={handleStart} disabled={busy || !storeId}
              className="px-5 py-2 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 disabled:opacity-50">
              {busy ? 'Starting…' : 'Start'}
            </button>
          ) : (
            <button onClick={handleStop} disabled={busy}
              className="px-5 py-2 rounded-lg bg-red-600 text-white text-sm font-semibold hover:bg-red-700 disabled:opacity-50">
              {busy ? 'Stopping…' : 'Stop'}
            </button>
          )}
        </div>
      </header>

      <div className="flex-1 overflow-auto p-5 space-y-4">
        {/* ── Camera selectors ─────────────────────────────────────────────── */}
        <div className={`grid ${gridClass} gap-2`}>
          {slots.map((slot, i) => (
            <div key={i} className="flex items-center gap-3">
              <label className="text-sm font-medium text-gray-700 shrink-0 w-16">Cam {i + 1}</label>
              <select value={slot} onChange={e => updateSlot(i, e.target.value)} disabled={running}
                className="flex-1 border border-gray-300 rounded-lg px-3 py-1.5 text-sm bg-white disabled:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option value="">— none —</option>
                {cameras.map(c => (
                  <option key={c.id} value={String(c.id)}>{c.name || shortId(c.id)}</option>
                ))}
              </select>
            </div>
          ))}
        </div>

        {/* ── Camera panels (only for slots with a selection) ───────────────── */}
        {slots.some(Boolean) && (
          <div className={`grid ${gridClass} gap-4`}>
            {slots.map((slot, i) => !slot ? null : (
              <CameraPanel
                key={`panel-${i}-${slot}`}
                title={`Camera ${i + 1}`}
                cameraId={slot}
                cameraName={nameOf(slot)}
                running={running}
                zones={zones}
                frameUrl={frameUrls[slot] || null}
              />
            ))}
          </div>
        )}

        {/* ── IEP3 output ──────────────────────────────────────────────────── */}
        <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          <div className="px-4 py-2.5 border-b border-gray-100 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-700">IEP3 — Reconciled Global Positions</h3>
            <div className="text-xs text-gray-500 flex gap-4">
              <span>positions: <b className="text-gray-700">{s.positions ?? 0}</b></span>
              <span>unique global IDs: <b className="text-gray-700">{s.unique_globals ?? 0}</b></span>
              <span>cameras: <b className="text-gray-700">{s.cameras ?? 0}</b></span>
            </div>
          </div>
          <div className="overflow-y-auto" style={{ maxHeight: 260 }}>
            {(iep3.rows || []).length === 0 ? (
              <div className="py-8 text-center text-gray-400 text-sm">
                {running
                  ? 'Waiting for IEP3 reconciliation (fires after cameras report a batch)…'
                  : 'Not running'}
              </div>
            ) : (
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-white border-b border-gray-100">
                  <tr>
                    <th className="px-3 py-1.5 text-left font-semibold text-gray-500">Global ID</th>
                    <th className="px-3 py-1.5 text-left font-semibold text-gray-500">Time</th>
                    <th className="px-3 py-1.5 text-right font-semibold text-gray-500">floor_x</th>
                    <th className="px-3 py-1.5 text-right font-semibold text-gray-500">floor_y</th>
                    <th className="px-3 py-1.5 text-left font-semibold text-gray-500">Zone</th>
                    <th className="px-3 py-1.5 text-left font-semibold text-gray-500">Source cam</th>
                    <th className="px-3 py-1.5 text-right font-semibold text-gray-500">Score</th>
                  </tr>
                </thead>
                <tbody>
                  {iep3.rows.map((r, i) => (
                    <tr key={`${r.global_id}-${r.timestamp_ms}-${i}`}
                      className={i % 2 ? 'bg-gray-50' : 'bg-white'}>
                      <td className="px-3 py-1 font-mono text-gray-700">{globalNumRef.current(r.global_id) ?? '—'}</td>
                      <td className="px-3 py-1 font-mono text-gray-500">{fmtTs(r.timestamp_ms)}</td>
                      <td className="px-3 py-1 text-right text-gray-700">{fmtNum(r.floor_x)}</td>
                      <td className="px-3 py-1 text-right text-gray-700">{fmtNum(r.floor_y)}</td>
                      <td className="px-3 py-1 font-mono text-gray-500">{shortId(r.zone_id) || '—'}</td>
                      <td className="px-3 py-1 font-mono text-gray-500">{camLabel(r.source_camera)}</td>
                      <td className="px-3 py-1 text-right text-gray-700">{fmtNum(r.selection_score)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
