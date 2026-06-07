/*
 * DEV-ONLY end-to-end pipeline tester.
 * Route: /store/:slug/dev/e2e  (only mounted when import.meta.env.DEV)
 *
 * Split screen: pick Camera 1 (left) and Camera 2 (right), press Start once,
 * and both cameras run in parallel through the real IEP1 → IEP2 → IEP3 pipeline
 * using the stream URLs in the active store config. Each panel shows the live
 * feed with detection overlay + that camera's tracking_history table. A shared
 * table at the bottom shows IEP3 (global_tracking_history) output.
 *
 * Backend: DEBUG_MODE dev-pipeline endpoints (see services/eep/app/api/routers/dev_pipeline.py).
 * Live frames: Live Bridge ws://…/ws/live/{camera_id} (base64-embedded in dev).
 */
import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { usePageTitle } from '../components/PageMeta'
import {
  getStore, listCameras,
  devPipelineStart, devPipelineStop,
  getDevTracking, getDevIep3, getDevGpuStatus,
} from '../api'

const BRIDGE_URL = import.meta.env.VITE_LIVE_BRIDGE_URL || 'ws://localhost:8010'

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
function shortId(v) {
  return v ? String(v).slice(0, 8) : null
}

// Maps opaque IDs (UUIDs) to stable sequential display numbers 1,2,3… in the
// order first seen. UI-only — the real IDs are unchanged in the DB.
function makeNumberer() {
  const map = new Map()
  let next = 1
  return (id) => {
    if (id == null || id === '') return null
    const k = String(id)
    if (!map.has(k)) map.set(k, next++)
    return map.get(k)
  }
}

/* ─────────────────────────────────────────────────────────────────────────
 * One camera window: live canvas + per-camera tracking_history table.
 * ───────────────────────────────────────────────────────────────────────── */
function CameraPanel({ title, cameraId, cameraName, running }) {
  const canvasRef = useRef(null)
  const wsRef     = useRef(null)
  const framesRef = useRef([])                 // buffered {frame_b64|frame_url, detections}
  const localNumRef = useRef(makeNumberer())   // local_id → 1,2,3… (UI display only)
  const [status, setStatus]       = useState('disconnected')
  const [detections, setDetections] = useState([])
  const [rows, setRows]           = useState([])
  const [total, setTotal]         = useState(0)
  const [frameCount, setFrameCount] = useState(0)   // # frames received this run
  const [replayIdx, setReplayIdx]   = useState(null) // null = live; number = replay position

  // Render one frame item (image + detection overlay) to the canvas.
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
        ctx.strokeStyle = d.local_id ? '#22c55e' : '#f59e0b'
        ctx.strokeRect(d.x1, d.y1, d.x2 - d.x1, d.y2 - d.y1)
        const label = d.local_id ? `ID ${localNumRef.current(d.local_id)}` : 'pending'
        const tw = ctx.measureText(label).width
        const ly = d.y1 > 16 ? d.y1 - 4 : d.y2 + 14
        ctx.fillStyle = 'rgba(0,0,0,0.65)'
        ctx.fillRect(d.x1 - 1, ly - 12, tw + 8, 15)
        ctx.fillStyle = '#fff'
        ctx.fillText(label, d.x1 + 3, ly - 1)
      })
    }

    if (data.frame_b64 || data.frame_url) {
      const img = new window.Image()
      if (data.frame_url) img.crossOrigin = 'anonymous'
      img.onload = () => {
        if (canvas.width !== img.naturalWidth)  canvas.width  = img.naturalWidth
        if (canvas.height !== img.naturalHeight) canvas.height = img.naturalHeight
        ctx.drawImage(img, 0, 0)
        paintBoxes()
      }
      img.onerror = () => {}
      img.src = data.frame_b64 ? `data:image/jpeg;base64,${data.frame_b64}` : data.frame_url
    } else {
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      paintBoxes()
    }
  }, [])

  // Live WebSocket — connect while running; buffer every frame for replay.
  useEffect(() => {
    if (!running || !cameraId) {
      setStatus('disconnected')
      return
    }
    framesRef.current = []
    localNumRef.current = makeNumberer()    // restart numbering at 1 for the new run
    setFrameCount(0); setReplayIdx(null); setDetections([])
    setStatus('connecting')
    const ws = new WebSocket(`${BRIDGE_URL}/ws/live/${cameraId}`)
    wsRef.current = ws
    ws.onopen    = () => setStatus('connected')
    ws.onerror   = () => setStatus('error')
    ws.onclose   = () => setStatus('disconnected')
    ws.onmessage = (e) => {
      try {
        const item = JSON.parse(e.data)
        const buf = framesRef.current
        buf.push(item)
        if (buf.length > 2000) buf.shift()       // cap memory (~2000 frames)
        setFrameCount(buf.length)
        renderItem(item)                          // live: always show newest
      } catch {}
    }
    return () => ws.close()
  }, [running, cameraId, renderItem])

  // On Stop: enter replay at the last buffered frame.
  useEffect(() => {
    if (running) return
    const n = framesRef.current.length
    if (n > 0) {
      setReplayIdx(n - 1)
      renderItem(framesRef.current[n - 1])
    }
  }, [running, renderItem])

  const seekReplay = (i) => {
    const n = framesRef.current.length
    if (n === 0) return
    const idx = Math.max(0, Math.min(i, n - 1))
    setReplayIdx(idx)
    renderItem(framesRef.current[idx])
  }

  // tracking_history poll — while running.
  useEffect(() => {
    if (!running || !cameraId) { return }
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

  const st = STATUS_CFG[status]
  const inReplay = !running && replayIdx !== null && frameCount > 0
  const frameLabel = inReplay ? `Frame ${replayIdx + 1} / ${frameCount}` : `Frame ${frameCount}`

  return (
    <div className="flex flex-col bg-white border border-gray-200 rounded-xl overflow-hidden">
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

      <div className="relative bg-gray-900 flex items-center justify-center" style={{ minHeight: 200 }}>
        <canvas ref={canvasRef} width={640} height={360} className="block max-w-full" />
        <div className="absolute top-2 left-2 bg-black/60 text-white text-[11px] font-mono px-2 py-0.5 rounded">
          {frameLabel}
        </div>
      </div>

      {/* ── Replay scrubber (shown after Stop) ──────────────────────────────── */}
      {inReplay && (
        <div className="px-3 py-2 border-t border-gray-100 flex items-center gap-2 bg-gray-50">
          <button onClick={() => seekReplay(replayIdx - 1)} className="px-2 py-0.5 text-xs rounded border border-gray-300 bg-white hover:bg-gray-100">◀</button>
          <input
            type="range" min={0} max={Math.max(0, frameCount - 1)} value={replayIdx}
            onChange={e => seekReplay(Number(e.target.value))}
            className="flex-1 accent-blue-600"
          />
          <button onClick={() => seekReplay(replayIdx + 1)} className="px-2 py-0.5 text-xs rounded border border-gray-300 bg-white hover:bg-gray-100">▶</button>
        </div>
      )}

      <div className="px-3 py-1.5 border-b border-t border-gray-100 text-xs text-gray-500 flex justify-between shrink-0">
        <span>{inReplay ? 'Replay detections' : 'Live detections'}: <b className="text-gray-700">{detections.length}</b></span>
        <span>tracking_history rows: <b className="text-gray-700">{total}</b></span>
      </div>

      <div className="overflow-y-auto" style={{ maxHeight: 220 }}>
        {rows.length === 0 ? (
          <div className="py-6 text-center text-gray-400 text-sm">No tracking rows yet</div>
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
                  <td className="px-2 py-1 text-right text-gray-700">{fmtNum(r.bbox_confidence * 100, 0)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

/* ───────────────────────────────────────────────────────────────────────── */
export default function DevE2E() {
  usePageTitle('Dev E2E Pipeline')
  const { slug } = useParams()

  const [storeId, setStoreId] = useState('')
  const [cameras, setCameras] = useState([])
  const [cam1, setCam1] = useState('')
  const [cam2, setCam2] = useState('')
  const [running, setRunning] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [iep3, setIep3] = useState({ summary: {}, rows: [] })
  const [device, setDevice] = useState('cpu')          // 'cpu' | 'gpu'
  const [gpu, setGpu] = useState(null)                 // {gpu_available, detector, reid}
  const globalNumRef = useRef(makeNumberer())          // global_id → 1,2,3… (UI display)

  // Load store + cameras.
  useEffect(() => {
    (async () => {
      try {
        const [store, cams] = await Promise.all([getStore(slug), listCameras(slug)])
        setStoreId(store.id)
        const active = (cams || []).filter(c => c.is_active !== false)
        setCameras(active)
        if (active[0]) setCam1(active[0].id)
        if (active[1]) setCam2(active[1].id)
      } catch (e) {
        setError('Failed to load store/cameras')
      }
      try {
        const g = await getDevGpuStatus()
        setGpu(g)
        if (g.gpu_available) setDevice('gpu')   // prefer GPU when the machine has one
      } catch { setGpu({ gpu_available: false }) }
    })()
  }, [slug])

  // IEP3 poll — while running.
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

  const nameOf = (id) => cameras.find(c => c.id === id)?.name || id

  const handleStart = async () => {
    setError('')
    if (!cam1 || !cam2) { setError('Select a camera in both windows'); return }
    if (cam1 === cam2)  { setError('Pick two different cameras'); return }
    globalNumRef.current = makeNumberer()   // restart global-ID numbering for the new run
    setBusy(true)
    try {
      const res = await devPipelineStart({
        store_id: storeId,
        camera_ids: [cam1, cam2],
        target_fps: 5.0,
        window_seconds: 60.0,
        device,
      })
      const failed = (res.cameras || []).filter(c => !c.ok)
      if (failed.length) {
        setError('Some cameras failed: ' + failed.map(f => `${shortId(f.camera_id)} (${f.stage}: ${f.error})`).join('; '))
      }
      setRunning(true)
    } catch (e) {
      const detail = e?.response?.data?.detail
      if (detail && detail.code === 'NO_GPU') {
        setError('This machine has no usable GPU — switch to CPU, or run on a GPU machine.')
        setDevice('cpu')
      } else {
        setError(typeof detail === 'string' ? detail : (detail?.error || 'Start failed'))
      }
    } finally {
      setBusy(false)
    }
  }

  const handleStop = async () => {
    setBusy(true)
    try {
      await devPipelineStop({ store_id: storeId, camera_ids: [cam1, cam2] })
    } catch {}
    setRunning(false)
    setBusy(false)
  }

  const s = iep3.summary || {}

  return (
    <div className="page-enter flex flex-col h-full overflow-hidden">
      <header className="bg-white border-b border-gray-200 px-6 py-4 shrink-0 flex items-center justify-between">
        <div>
          <h1 className="page-title">Dev E2E Pipeline</h1>
          <p className="page-subtitle">IEP1 → IEP2 → IEP3 · both cameras in parallel</p>
        </div>
        <div className="flex items-center gap-3">
          {error && <span className="text-xs text-red-600 max-w-md truncate" title={error}>{error}</span>}

          {/* ── CPU / GPU toggle ─────────────────────────────────────────────── */}
          <div className="flex items-center gap-2">
            <span
              className="text-[11px] text-gray-400"
              title={gpu ? `detector: ${JSON.stringify(gpu.detector)} · reid: ${JSON.stringify(gpu.reid)}` : ''}
            >
              GPU: {gpu ? (gpu.gpu_available ? 'available' : 'none') : '…'}
            </span>
            <div className="inline-flex rounded-lg border border-gray-300 overflow-hidden text-sm">
              {['cpu', 'gpu'].map(d => (
                <button
                  key={d}
                  onClick={() => !running && setDevice(d)}
                  disabled={running}
                  className={`px-3 py-1.5 font-semibold uppercase ${
                    device === d ? 'bg-blue-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'
                  } ${running ? 'opacity-60 cursor-not-allowed' : ''}`}
                >
                  {d}
                </button>
              ))}
            </div>
          </div>

          {!running ? (
            <button
              onClick={handleStart}
              disabled={busy || !storeId}
              className="px-5 py-2 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 disabled:opacity-50"
            >
              {busy ? 'Starting…' : 'Start'}
            </button>
          ) : (
            <button
              onClick={handleStop}
              disabled={busy}
              className="px-5 py-2 rounded-lg bg-red-600 text-white text-sm font-semibold hover:bg-red-700 disabled:opacity-50"
            >
              {busy ? 'Stopping…' : 'Stop'}
            </button>
          )}
        </div>
      </header>

      <div className="flex-1 overflow-auto p-5 space-y-4">
        {/* ── Camera selectors ─────────────────────────────────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {[{ v: cam1, set: setCam1, label: 'Window 1 — Camera' },
            { v: cam2, set: setCam2, label: 'Window 2 — Camera' }].map((sel, i) => (
            <div key={i} className="flex items-center gap-3">
              <label className="text-sm font-medium text-gray-700 shrink-0">{sel.label}</label>
              <select
                value={sel.v}
                onChange={e => sel.set(e.target.value)}
                disabled={running}
                className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm bg-white disabled:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">— select —</option>
                {cameras.map(c => (
                  <option key={c.id} value={c.id}>{c.name || c.id}</option>
                ))}
              </select>
            </div>
          ))}
        </div>

        {/* ── Split-screen camera windows ──────────────────────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <CameraPanel title="Camera 1" cameraId={cam1} cameraName={nameOf(cam1)} running={running} />
          <CameraPanel title="Camera 2" cameraId={cam2} cameraName={nameOf(cam2)} running={running} />
        </div>

        {/* ── IEP3 output table ────────────────────────────────────────────── */}
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
                {running ? 'Waiting for IEP3 reconciliation (fires after both cameras report a batch)…' : 'Not running'}
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
                    <tr key={`${r.global_id}-${r.timestamp_ms}-${i}`} className={i % 2 ? 'bg-gray-50' : 'bg-white'}>
                      <td className="px-3 py-1 font-mono text-gray-700">{globalNumRef.current(r.global_id) ?? '—'}</td>
                      <td className="px-3 py-1 font-mono text-gray-500">{fmtTs(r.timestamp_ms)}</td>
                      <td className="px-3 py-1 text-right text-gray-700">{fmtNum(r.floor_x)}</td>
                      <td className="px-3 py-1 text-right text-gray-700">{fmtNum(r.floor_y)}</td>
                      <td className="px-3 py-1 font-mono text-gray-500">{shortId(r.zone_id) || '—'}</td>
                      <td className="px-3 py-1 font-mono text-gray-500">
                        {r.source_camera === cam1 ? 'Cam 1' : r.source_camera === cam2 ? 'Cam 2' : shortId(r.source_camera)}
                      </td>
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
