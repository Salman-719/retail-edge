/**
 * CalibStep6_TestMode — Method 2 Step 6
 *
 * Run YOLO + ByteTrack on calibration-file cameras.
 *   - Readiness guard: cam?.calibrationMethod === 'calibration_files'
 *   - VirtualTrajectoryView: HTML5 canvas, WildTrack dark aesthetic, adaptive grid,
 *     camera triangles, scale bar, pan (drag) + zoom (scroll wheel)
 *   - HeatmapView: dark-themed with pan/zoom
 */
import React, { useState, useEffect, useRef, useCallback } from 'react'
import useStore from '../store'
import {
  startTracking,
  getTrackingProgress,
  getTrajectory,
  trackingStreamUrl,
} from '../api'

// WildTrack track colors
const TRACK_COLORS = [
  '#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4',
  '#FFEAA7', '#DDA0DD', '#98D8C8', '#F7DC6F',
  '#BB8FCE', '#85C1E9', '#82E0AA', '#F0B27A',
]

// Camera colors (matching CalibStep2/3)
const CAM_COLORS = [
  '#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4',
  '#FFEAA7', '#DDA0DD', '#98D8C8', '#F7DC6F',
]

// Zone colors (matching CalibStep3)
const ZONE_COLORS = {
  entrance:   '#00FF9D',
  checkout:   '#00D4FF',
  aisle:      '#FFEAA7',
  staff_only: '#FF6B6B',
  general:    '#DDA0DD',
}

// ── Canvas helpers ────────────────────────────────────────────────────────────

function wToC(wx, wy, t) { return { x: wx*t.scale + t.offsetX, y: -wy*t.scale + t.offsetY } }
function cToW(cx, cy, t) { return { x: (cx - t.offsetX)/t.scale, y: -(cy - t.offsetY)/t.scale } }

function fitWorldBounds(xMin, xMax, yMin, yMax, W, H, pad=48) {
  const rangeX = Math.max(xMax-xMin, 1), rangeY = Math.max(yMax-yMin, 1)
  const scale  = Math.min((W-pad*2)/rangeX, (H-pad*2)/rangeY)
  return { scale, offsetX: W/2 - ((xMin+xMax)/2)*scale, offsetY: H/2 + ((yMin+yMax)/2)*scale }
}

function drawAdaptiveGrid(ctx, t, W, H) {
  const wLeft   = cToW(0, 0, t).x, wRight  = cToW(W, 0, t).x
  const wTop    = cToW(0, 0, t).y, wBottom = cToW(0, H, t).y
  const yLo = Math.min(wTop, wBottom), yHi = Math.max(wTop, wBottom)
  const rawStep = 80 / t.scale
  if (rawStep <= 0 || !isFinite(rawStep)) return
  const mag      = Math.pow(10, Math.floor(Math.log10(Math.abs(rawStep)||1)))
  const norm     = rawStep / mag
  const niceNorm = norm < 1.5 ? 1 : norm < 3.5 ? 2 : norm < 7.5 ? 5 : 10
  const major = niceNorm * mag, minor = major / 5
  // minor
  ctx.lineWidth = 0.5; ctx.strokeStyle = '#1E2235'
  for (let x = Math.floor(wLeft/minor)*minor; x <= wRight; x += minor) {
    if (Math.abs(x%major) < minor*0.01) continue
    const cx = wToC(x,0,t).x; ctx.beginPath(); ctx.moveTo(cx,0); ctx.lineTo(cx,H); ctx.stroke()
  }
  for (let y = Math.floor(yLo/minor)*minor; y <= yHi; y += minor) {
    if (Math.abs(y%major) < minor*0.01) continue
    const cy = wToC(0,y,t).y; ctx.beginPath(); ctx.moveTo(0,cy); ctx.lineTo(W,cy); ctx.stroke()
  }
  // major
  ctx.lineWidth = 1; ctx.strokeStyle = '#2D3142'
  for (let x = Math.floor(wLeft/major)*major; x <= wRight; x += major) {
    const cx = wToC(x,0,t).x; ctx.beginPath(); ctx.moveTo(cx,0); ctx.lineTo(cx,H); ctx.stroke()
  }
  for (let y = Math.floor(yLo/major)*major; y <= yHi; y += major) {
    const cy = wToC(0,y,t).y; ctx.beginPath(); ctx.moveTo(0,cy); ctx.lineTo(W,cy); ctx.stroke()
  }
  // axes
  ctx.lineWidth = 1.5; ctx.strokeStyle = '#3D4562'
  const ox = wToC(0,0,t).x, oy = wToC(0,0,t).y
  ctx.beginPath(); ctx.moveTo(ox,0); ctx.lineTo(ox,H); ctx.stroke()
  ctx.beginPath(); ctx.moveTo(0,oy); ctx.lineTo(W,oy); ctx.stroke()
  // labels
  ctx.fillStyle = '#6B7280'; ctx.font = '9px monospace'
  const fmt = v => Number.isInteger(v) ? String(v) : v.toPrecision(2)
  ctx.textAlign = 'center'
  for (let x = Math.floor(wLeft/major)*major; x <= wRight; x += major) {
    ctx.fillText(fmt(x), wToC(x,0,t).x, H-4)
  }
  ctx.textAlign = 'right'
  for (let y = Math.floor(yLo/major)*major; y <= yHi; y += major) {
    ctx.fillText(fmt(y), 30, wToC(0,y,t).y+3)
  }
}

function drawScaleBar(ctx, t, W, H) {
  const raw = 80/t.scale
  const mag = Math.pow(10, Math.floor(Math.log10(Math.max(raw,1e-10))))
  const nice = ((raw/mag)<1.5?1:(raw/mag)<3.5?2:(raw/mag)<7.5?5:10)*mag
  const barPx = nice*t.scale, barX = W-barPx-16, barY = H-22
  ctx.save(); ctx.strokeStyle='#6B7280'; ctx.lineWidth=2
  ctx.beginPath()
  ctx.moveTo(barX,barY); ctx.lineTo(barX+barPx,barY)
  ctx.moveTo(barX,barY-4); ctx.lineTo(barX,barY+4)
  ctx.moveTo(barX+barPx,barY-4); ctx.lineTo(barX+barPx,barY+4)
  ctx.stroke()
  ctx.fillStyle='#9CA3AF'; ctx.font='9px monospace'; ctx.textAlign='center'
  ctx.fillText(`${Number.isInteger(nice)?nice:nice.toPrecision(2)} m`, barX+barPx/2, barY+13)
  ctx.restore()
}

function drawCameraTriangle(ctx, x, y, color) {
  const sz = 9
  ctx.save(); ctx.beginPath()
  ctx.moveTo(x, y-sz*1.2); ctx.lineTo(x-sz*0.8, y+sz*0.8); ctx.lineTo(x+sz*0.8, y+sz*0.8)
  ctx.closePath(); ctx.fillStyle=color; ctx.strokeStyle='rgba(0,0,0,0.7)'; ctx.lineWidth=1.5
  ctx.fill(); ctx.stroke(); ctx.restore()
}

// ── Virtual Trajectory Canvas ─────────────────────────────────────────────────

const TRAJ_HEIGHT = 480

function VirtualTrajectoryView({ worldBounds, cameras, zones, trajectoryMeters }) {
  const canvasRef    = useRef()
  const containerRef = useRef()
  const [size, setSize]       = useState({ width: 680, height: TRAJ_HEIGHT })
  const [transform, setTransform] = useState({ scale: 50, offsetX: 340, offsetY: 240 })
  const [mouseWorld, setMouseWorld] = useState(null)
  const isPanning    = useRef(false)
  const panStart     = useRef({ x: 0, y: 0, ox: 0, oy: 0 })
  const transformRef = useRef(transform)
  const minScaleRef  = useRef(1)

  const updateTransform = useCallback(fn => {
    setTransform(prev => {
      const next = typeof fn === 'function' ? fn(prev) : fn
      transformRef.current = next
      return next
    })
  }, [])

  // Resize observer
  useEffect(() => {
    if (!containerRef.current) return
    const ro = new ResizeObserver(es => {
      const { width, height } = es[0].contentRect
      setSize({ width: Math.round(width), height: Math.round(height || TRAJ_HEIGHT) })
    })
    ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [])

  // Auto-fit on mount / bounds change + update minScale
  useEffect(() => {
    if (!worldBounds) return
    const { xMin, xMax, yMin, yMax } = worldBounds
    const t = fitWorldBounds(xMin, xMax, yMin, yMax, size.width, size.height)
    transformRef.current = t
    setTransform(t)
    const rangeX = Math.max(xMax - xMin, 1), rangeY = Math.max(yMax - yMin, 1)
    minScaleRef.current = Math.min((size.width - 80) / rangeX, (size.height - 80) / rangeY) * 0.65
  }, [worldBounds, size.width, size.height])

  // Draw
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    canvas.width  = size.width
    canvas.height = size.height

    // Background
    ctx.fillStyle = '#0F1117'
    ctx.fillRect(0, 0, size.width, size.height)

    if (!worldBounds) {
      ctx.fillStyle = '#2D3142'; ctx.font = '12px monospace'; ctx.textAlign = 'center'
      ctx.fillText('World bounds not configured', size.width/2, size.height/2)
      return
    }

    drawAdaptiveGrid(ctx, transform, size.width, size.height)

    // Zone fills
    if (zones) {
      for (const z of zones) {
        const color = ZONE_COLORS[z.type] || '#DDA0DD'
        if (!z.points?.length) continue
        ctx.save()
        ctx.beginPath()
        const first = wToC(z.points[0].x, z.points[0].y, transform)
        ctx.moveTo(first.x, first.y)
        for (let i = 1; i < z.points.length; i++) {
          const p = wToC(z.points[i].x, z.points[i].y, transform)
          ctx.lineTo(p.x, p.y)
        }
        ctx.closePath()
        ctx.fillStyle = color + '1A'
        ctx.fill()
        ctx.strokeStyle = color
        ctx.lineWidth = 1.5
        ctx.stroke()
        // Zone label
        const cx = z.points.reduce((s, p) => s + p.x, 0) / z.points.length
        const cy = z.points.reduce((s, p) => s + p.y, 0) / z.points.length
        const labelPt = wToC(cx, cy, transform)
        ctx.fillStyle = color
        ctx.font = 'bold 10px monospace'
        ctx.textAlign = 'center'
        ctx.fillText(z.name, labelPt.x, labelPt.y + 4)
        ctx.restore()
      }
    }

    // Trajectory dots
    if (trajectoryMeters) {
      for (const pt of trajectoryMeters) {
        const { x, y } = wToC(pt.x, pt.y, transform)
        ctx.beginPath()
        ctx.arc(x, y, 3, 0, Math.PI*2)
        ctx.fillStyle = TRACK_COLORS[(pt.trackId || 0) % TRACK_COLORS.length]
        ctx.globalAlpha = 0.78
        ctx.fill()
        ctx.globalAlpha = 1
      }
    }

    // Camera triangles
    if (cameras) {
      cameras.filter(c => c.cameraWorldXYZ).forEach((cam, ci) => {
        const { x, y } = wToC(cam.cameraWorldXYZ[0], cam.cameraWorldXYZ[1], transform)
        const color = CAM_COLORS[ci % CAM_COLORS.length]
        drawCameraTriangle(ctx, x, y, color)
        ctx.fillStyle = color
        ctx.font = 'bold 9px monospace'
        ctx.textAlign = 'center'
        ctx.fillText(cam.name, x, y + 20)
      })
    }

    drawScaleBar(ctx, transform, size.width, size.height)
  }, [worldBounds, cameras, zones, trajectoryMeters, transform, size])

  // Wheel zoom (with zoom-out limit)
  const handleWheel = useCallback(e => {
    e.preventDefault()
    const rect  = canvasRef.current.getBoundingClientRect()
    const cx    = e.clientX - rect.left, cy = e.clientY - rect.top
    const delta = e.deltaY > 0 ? 0.85 : 1.18
    updateTransform(t => {
      const attempted = t.scale * delta
      if (delta < 1 && attempted < minScaleRef.current) return t
      return {
        scale:   attempted,
        offsetX: cx + (t.offsetX - cx) * delta,
        offsetY: cy + (t.offsetY - cy) * delta,
      }
    })
  }, [updateTransform])

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    el.addEventListener('wheel', handleWheel, { passive: false })
    return () => el.removeEventListener('wheel', handleWheel)
  }, [handleWheel])

  function handleMouseMove(e) {
    const rect = canvasRef.current.getBoundingClientRect()
    setMouseWorld(cToW(e.clientX-rect.left, e.clientY-rect.top, transformRef.current))
    if (isPanning.current) {
      const dx = e.clientX - panStart.current.x, dy = e.clientY - panStart.current.y
      updateTransform({ ...transformRef.current, offsetX: panStart.current.ox+dx, offsetY: panStart.current.oy+dy })
    }
  }
  function handleMouseDown(e) {
    isPanning.current = true
    panStart.current  = { x: e.clientX, y: e.clientY, ox: transformRef.current.offsetX, oy: transformRef.current.offsetY }
    e.preventDefault()
  }
  function handleMouseUp()    { isPanning.current = false }
  function handleMouseLeave() { isPanning.current = false; setMouseWorld(null) }

  function handleFit() {
    if (!worldBounds) return
    const { xMin, xMax, yMin, yMax } = worldBounds
    const t = fitWorldBounds(xMin, xMax, yMin, yMax, size.width, size.height)
    transformRef.current = t; setTransform(t)
  }

  const wb = worldBounds || {}

  return (
    <div>
      {/* Controls bar */}
      <div className="flex gap-2 mb-2 items-center">
        <button onClick={handleFit}
          className="text-xs px-2 py-1 font-mono rounded transition-colors"
          style={{ background: '#1A1D27', border: '1px solid #2D3142', color: '#9CA3AF' }}
          onMouseEnter={e => { e.currentTarget.style.color='#00D4FF'; e.currentTarget.style.borderColor='#00D4FF' }}
          onMouseLeave={e => { e.currentTarget.style.color='#9CA3AF'; e.currentTarget.style.borderColor='#2D3142' }}>
          Fit
        </button>
        <span className="text-xs font-mono" style={{ color: '#4B5563' }}>
          scroll=zoom · drag=pan
        </span>
        {mouseWorld && (
          <span className="ml-auto text-xs font-mono" style={{ color: '#6B7280' }}>
            X={mouseWorld.x.toFixed(3)}  Y={mouseWorld.y.toFixed(3)}
          </span>
        )}
      </div>

      {/* Canvas */}
      <div ref={containerRef}
        className="rounded-xl overflow-hidden"
        style={{ background: '#0F1117', border: '1px solid #2D3142', height: TRAJ_HEIGHT, position: 'relative' }}>
        <canvas
          ref={canvasRef}
          style={{ display: 'block', cursor: isPanning.current ? 'grabbing' : 'crosshair' }}
          onMouseMove={handleMouseMove}
          onMouseDown={handleMouseDown}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseLeave}
          onContextMenu={e => e.preventDefault()}
        />
      </div>

      <div className="text-xs font-mono text-center mt-1" style={{ color: '#4B5563' }}>
        {wb.xMax != null
          ? `${(wb.xMax-wb.xMin).toFixed(1)} m × ${(wb.yMax-wb.yMin).toFixed(1)} m world space`
          : 'world space'}
      </div>
    </div>
  )
}

// ── HeatmapView ───────────────────────────────────────────────────────────────

function HeatmapView({ heatmapUrl }) {
  const [zoom, setZoom]   = useState(1)
  const [pan,  setPan]    = useState({ x: 0, y: 0 })
  const isPanning = useRef(false)
  const lastMouse = useRef({ x: 0, y: 0 })
  const containerRef = useRef()

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const onWheel = e => {
      if (!e.ctrlKey) return
      e.preventDefault()
      setZoom(z => Math.min(6, Math.max(0.3, e.deltaY < 0 ? z*1.12 : z/1.12)))
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  useEffect(() => {
    const onUp = () => { isPanning.current = false }
    window.addEventListener('mouseup', onUp)
    return () => window.removeEventListener('mouseup', onUp)
  }, [])

  if (!heatmapUrl) {
    return (
      <div className="rounded-xl p-12 text-center text-sm font-mono"
        style={{ background: '#0F1117', border: '1px solid #2D3142', color: '#4B5563', maxWidth: 680 }}>
        Heatmap not yet generated.
      </div>
    )
  }

  return (
    <div style={{ maxWidth: 720 }}>
      <div className="flex gap-2 mb-2 items-center">
        <button onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }) }}
          className="text-xs px-2 py-1 font-mono rounded transition-colors"
          style={{ background: '#1A1D27', border: '1px solid #2D3142', color: '#9CA3AF' }}
          onMouseEnter={e => { e.currentTarget.style.color='#00D4FF'; e.currentTarget.style.borderColor='#00D4FF' }}
          onMouseLeave={e => { e.currentTarget.style.color='#9CA3AF'; e.currentTarget.style.borderColor='#2D3142' }}>
          Reset
        </button>
        <span className="text-xs font-mono" style={{ color: '#4B5563' }}>
          Ctrl+scroll=zoom · drag=pan
        </span>
      </div>
      <div ref={containerRef}
        className="rounded-xl overflow-hidden"
        style={{
          background: '#0F1117', border: '1px solid #2D3142',
          cursor: 'grab', userSelect: 'none', maxHeight: 480,
        }}
        onMouseDown={e => { isPanning.current = true; lastMouse.current = { x: e.clientX, y: e.clientY } }}
        onMouseMove={e => {
          if (!isPanning.current) return
          setPan(p => ({ x: p.x + (e.clientX-lastMouse.current.x), y: p.y + (e.clientY-lastMouse.current.y) }))
          lastMouse.current = { x: e.clientX, y: e.clientY }
        }}
      >
        <div style={{ transform: `translate(${pan.x}px,${pan.y}px) scale(${zoom})`, transformOrigin: '50% 0%', lineHeight: 0 }}>
          <img src={`${heatmapUrl}?t=${Date.now()}`} alt="Heatmap" draggable={false}
            style={{ width: '100%', display: 'block' }} />
        </div>
      </div>
    </div>
  )
}

function HeatmapLegend() {
  const stops = [
    { label: '0%',   color: '#D7EDFF' }, { label: '25%',  color: '#64C3EB' },
    { label: '50%',  color: '#FFEB78' }, { label: '75%',  color: '#FFA54B' },
    { label: '100%', color: '#F5645F' },
  ]
  return (
    <div className="flex items-center gap-3 text-xs mt-2 flex-wrap" style={{ color: '#9CA3AF' }}>
      <span className="font-medium" style={{ color: '#6B7280' }}>Zone occupancy:</span>
      {stops.map(s => (
        <span key={s.label} className="flex items-center gap-1">
          <span className="w-3 h-3 rounded-sm inline-block border" style={{ background: s.color, borderColor: '#2D3142' }} />
          {s.label}
        </span>
      ))}
    </div>
  )
}

// ── Progress bar ──────────────────────────────────────────────────────────────

function ProgressBar({ value }) {
  return (
    <div className="w-full rounded-full h-3 overflow-hidden" style={{ background: '#1A1D27', border: '1px solid #2D3142' }}>
      <div className="h-full rounded-full transition-all duration-300"
        style={{ width: `${Math.round(value*100)}%`, background: '#00D4FF' }} />
    </div>
  )
}

// ── Zone table ────────────────────────────────────────────────────────────────

function ZoneTable({ zones, zoneOccupancy, trajectoryMeters, effectiveFps }) {
  const totalInZones = Object.values(zoneOccupancy || {}).reduce((s, z) => s + (z.seconds || 0), 0)
  const outsideSec   = Math.max(0, trajectoryMeters
    ? (trajectoryMeters.length / Math.max(effectiveFps || 8, 1)) - totalInZones : 0)
  const grandTotal   = totalInZones + outsideSec
  const barColor = pct => pct < 20 ? '#00FF9D' : pct < 50 ? '#FFEAA7' : '#FF6B6B'

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="text-xs uppercase tracking-wide" style={{ background: '#1A1D27', color: '#6B7280' }}>
            <th className="px-3 py-2 text-left">Zone</th>
            <th className="px-3 py-2 text-left">Type</th>
            <th className="px-3 py-2 text-right">Presence (s)</th>
            <th className="px-3 py-2 text-left w-40">Share</th>
            <th className="px-3 py-2 text-right">%</th>
          </tr>
        </thead>
        <tbody>
          {(zones || []).map(z => {
            const occ = (zoneOccupancy || {})[z.name] || { seconds: 0, percent: 0 }
            return (
              <tr key={z.id} className="border-t" style={{ borderColor: '#2D3142' }}>
                <td className="px-3 py-2 font-medium text-white">{z.name}</td>
                <td className="px-3 py-2 text-xs" style={{ color: '#6B7280' }}>{z.type}</td>
                <td className="px-3 py-2 text-right font-mono" style={{ color: '#9CA3AF' }}>{occ.seconds.toFixed(1)}</td>
                <td className="px-3 py-2">
                  <div className="h-2 rounded-full overflow-hidden w-full" style={{ background: '#2D3142' }}>
                    <div className="h-full rounded-full transition-all duration-500"
                      style={{ width: `${occ.percent}%`, background: barColor(occ.percent) }} />
                  </div>
                </td>
                <td className="px-3 py-2 text-right font-mono font-semibold"
                  style={{ color: barColor(occ.percent) }}>
                  {occ.percent.toFixed(1)}%
                </td>
              </tr>
            )
          })}
          <tr className="border-t-2" style={{ borderColor: '#3D4562', background: '#1A1D27' }}>
            <td className="px-3 py-2 italic" style={{ color: '#4B5563' }}>Outside zones</td>
            <td className="px-3 py-2 text-xs" style={{ color: '#4B5563' }}>—</td>
            <td className="px-3 py-2 text-right font-mono" style={{ color: '#6B7280' }}>{outsideSec.toFixed(1)}</td>
            <td className="px-3 py-2">
              <div className="h-2 rounded-full overflow-hidden w-full" style={{ background: '#2D3142' }}>
                <div className="h-full rounded-full" style={{ background: '#3D4562', width: grandTotal > 0 ? `${(outsideSec/grandTotal)*100}%` : '0%' }} />
              </div>
            </td>
            <td className="px-3 py-2 text-right font-mono" style={{ color: '#6B7280' }}>
              {grandTotal > 0 ? ((outsideSec/grandTotal)*100).toFixed(1) : 0}%
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function CalibStep6_TestMode({ onBack }) {
  const { cameras, zones, worldBounds, updateCamera, activeStoreId } = useStore()

  const [selectedCamId, setSelectedCamId] = useState(cameras[0]?.id || null)
  const [modelSize,     setModelSize]     = useState('yolov8n')
  const [isTracking,    setIsTracking]    = useState(false)
  const [trackingDone,  setTrackingDone]  = useState(false)
  const [progress,      setProgress]      = useState(null)
  const [liveOccupancy, setLiveOccupancy] = useState({})
  const [error,         setError]         = useState(null)
  const [results,       setResults]       = useState(null)
  const [viewMode,      setViewMode]      = useState('stream')
  const [streamKey,     setStreamKey]     = useState(0)

  const cam     = cameras.find(c => c.id === selectedCamId)
  const pollRef = useRef(null)
  const isReady = cam?.calibrationMethod === 'calibration_files'

  const stopPolling = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }, [])

  useEffect(() => {
    if (!isTracking || !cam || !activeStoreId) return
    pollRef.current = setInterval(async () => {
      try {
        const data = await getTrackingProgress(activeStoreId, cam.id)
        setProgress(data)
        setLiveOccupancy(data.zoneOccupancy || {})
        if (data.status === 'done') {
          stopPolling(); setIsTracking(false); setTrackingDone(true)
          const trajectory = await getTrajectory(activeStoreId, cam.id)
          const finalResults = {
            ...data, trajectoryMeters: trajectory,
            heatmapUrl: `/api/stores/${activeStoreId}/cameras/${cam.id}/tracking/heatmap`,
          }
          setResults(finalResults)
          setViewMode('heatmap')
          updateCamera(cam.id, { trackingResults: finalResults })
        }
        if (data.status === 'error') {
          stopPolling(); setIsTracking(false); setError(data.error || 'Unknown tracking error')
        }
      } catch (_) {}
    }, 800)
    return stopPolling
  }, [isTracking, cam?.id, activeStoreId])

  const handleStart = async () => {
    if (!isReady || !activeStoreId) return
    stopPolling()
    setError(null); setProgress(null); setResults(null)
    setLiveOccupancy({}); setTrackingDone(false); setViewMode('stream')
    try {
      await startTracking(activeStoreId, cam.id, modelSize)
      setIsTracking(true); setStreamKey(k => k + 1)
    } catch (e) { setError(e.message) }
  }

  const handleExportCSV = () => {
    const traj = results?.trajectoryMeters
    if (!traj?.length) return
    const lines = ['frameIdx,x,y,trackId',
      ...traj.map(t => `${t.frameIdx},${t.x.toFixed(3)},${t.y.toFixed(3)},${t.trackId}`)]
    const blob = new Blob([lines.join('\n')], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a'); a.href=url; a.download=`trajectory_${cam.id}.csv`; a.click()
    URL.revokeObjectURL(url)
  }

  const pct       = progress ? Math.round(progress.progress*100) : 0
  const streamSrc = cam && activeStoreId ? trackingStreamUrl(activeStoreId, cam.id, streamKey) : ''

  return (
    <div className="max-w-4xl mx-auto py-6 px-4">
      <h2 className="text-xl font-bold text-gray-800 mb-1">Test Mode & Heatmap</h2>
      <p className="text-gray-500 mb-4 text-sm">
        Run YOLO + ByteTrack on your video. Watch the live stream, then explore trajectory dots and the zone heatmap.
      </p>

      {/* Camera tabs */}
      {cameras.length > 1 && (
        <div className="flex gap-2 mb-4 flex-wrap">
          {cameras.map(c => (
            <button key={c.id}
              onClick={() => {
                setSelectedCamId(c.id)
                setProgress(null); setResults(null)
                setIsTracking(false); setTrackingDone(false)
                stopPolling()
              }}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                selectedCamId === c.id ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}>
              {c.name} {c.trackingResults ? '✓' : ''}
            </button>
          ))}
        </div>
      )}

      {cam && (
        <>
          {/* Controls bar */}
          <div className="bg-white border rounded-xl p-4 mb-4 flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-2">
              <label className="text-sm font-medium text-gray-600">Model:</label>
              <select value={modelSize} onChange={e => setModelSize(e.target.value)}
                disabled={isTracking}
                className="border rounded-lg px-2 py-1.5 text-sm disabled:opacity-50">
                <option value="yolov8n">Nano (fastest)</option>
                <option value="yolov8s">Small</option>
                <option value="yolov8m">Medium</option>
              </select>
            </div>

            <button
              onClick={handleStart}
              disabled={isTracking || !isReady}
              className="px-5 py-2 rounded-lg font-medium text-sm text-white transition disabled:opacity-40"
              style={{ background: isTracking ? '#6b7280' : '#1B3A5C' }}>
              {isTracking ? '⏳ Running…' : trackingDone ? '↺ Re-run' : '▶ Start Tracking'}
            </button>

            {!isReady && (
              <p className="text-yellow-600 text-sm">⚠ Camera not calibrated with calibration files.</p>
            )}

            {isTracking && progress && (
              <div className="flex-1 min-w-48">
                <ProgressBar value={progress.progress} />
                <p className="text-xs text-gray-500 mt-1 text-right font-mono">
                  {pct}% — frame {progress.processedFrames}/{progress.totalFrames}
                </p>
              </div>
            )}

            {trackingDone && (
              <button onClick={handleExportCSV}
                className="text-sm px-3 py-1.5 border rounded-lg hover:bg-gray-50 ml-auto">
                ⬇ Trajectory CSV
              </button>
            )}
          </div>

          {error && (
            <div className="mb-4 p-3 rounded-lg text-sm font-mono"
              style={{ background: '#1A0A0A', border: '1px solid #FF4757', color: '#FF4757' }}>
              ✗ {error}
            </div>
          )}

          {/* View tabs */}
          {(isTracking || trackingDone) && (
            <div className="flex gap-2 mb-4">
              {['stream', 'trajectory', 'heatmap'].map(mode => (
                <button key={mode}
                  onClick={() => setViewMode(mode)}
                  disabled={mode !== 'stream' && !trackingDone}
                  className={`px-4 py-1.5 rounded-lg text-sm font-medium transition disabled:opacity-40 ${
                    viewMode === mode ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}>
                  {mode === 'stream'      ? `📹 Live Stream${isTracking ? ' ●' : ''}`
                   : mode === 'trajectory' ? '📍 Trajectory'
                   : '🔥 Heatmap'}
                </button>
              ))}
            </div>
          )}

          {/* View content */}
          {(isTracking || trackingDone) && (
            <div className="mb-6">
              {viewMode === 'stream' && (
                <div className="rounded-xl overflow-hidden shadow" style={{ maxWidth: 720, maxHeight: 480, background: '#000' }}>
                  {isTracking
                    ? <img key={streamKey} src={streamSrc} alt="Live tracking"
                        className="w-full block" style={{ maxHeight: 480, objectFit: 'contain' }} />
                    : <div className="flex items-center justify-center p-12 text-center" style={{ minHeight: 180 }}>
                        <div><div className="text-4xl mb-2">✅</div><p className="font-medium text-white">Tracking complete</p></div>
                      </div>
                  }
                </div>
              )}

              {viewMode === 'trajectory' && trackingDone && (
                <div style={{ maxWidth: 720 }}>
                  <VirtualTrajectoryView
                    worldBounds={worldBounds}
                    cameras={cameras}
                    zones={zones}
                    trajectoryMeters={results?.trajectoryMeters}
                  />
                </div>
              )}

              {viewMode === 'heatmap' && trackingDone && (
                <>
                  <HeatmapView heatmapUrl={results?.heatmapUrl} />
                  <HeatmapLegend />
                </>
              )}
            </div>
          )}

          {/* Zone occupancy table */}
          {(isTracking || trackingDone) && (
            <div className="rounded-xl overflow-hidden" style={{ maxWidth: 720, border: '1px solid #2D3142', background: '#0F1117' }}>
              <div className="px-4 py-2 border-b flex items-center justify-between" style={{ borderColor: '#2D3142', background: '#1A1D27' }}>
                <h4 className="text-sm font-semibold text-white">Zone Occupancy</h4>
                {isTracking && <span className="text-xs font-medium animate-pulse" style={{ color: '#00D4FF' }}>● Live</span>}
              </div>
              <ZoneTable
                zones={zones}
                zoneOccupancy={isTracking ? liveOccupancy : results?.zoneOccupancy}
                trajectoryMeters={results?.trajectoryMeters}
                effectiveFps={(cam.videoFps || 25) / 3}
              />
            </div>
          )}

          {!isTracking && !trackingDone && (
            <div className="rounded-xl p-12 text-center" style={{ maxWidth: 720, border: '2px dashed #2D3142' }}>
              <div className="text-4xl mb-3">🎬</div>
              <p className="font-medium text-gray-700">Click <strong>Start Tracking</strong> to begin.</p>
              <p className="text-sm mt-1 text-gray-400">The video will stream live with bounding boxes as the model processes each frame.</p>
            </div>
          )}
        </>
      )}

      <div className="mt-6 flex items-center justify-between" style={{ maxWidth: 720 }}>
        <button onClick={onBack}
          className="px-4 py-2 text-gray-600 border rounded-lg hover:bg-gray-50">← Back</button>
        {trackingDone && <span className="text-sm text-green-600 font-medium">🎉 All steps complete!</span>}
      </div>
    </div>
  )
}
