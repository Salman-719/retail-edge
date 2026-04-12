/**
 * CalibStep3_Zones — Method 2 Step 3
 *
 * Same HTML5 canvas as CalibStep2 (adaptive grid, scale bar, camera triangles,
 * pan / zoom-with-limit). Compact layout so the whole step fits without scrolling.
 *
 * Zone drawing:
 *   • Click to place vertices.
 *   • Move cursor near the first vertex — a snap ring appears.
 *   • Click within SNAP_SCREEN_PX of the first vertex to auto-close.
 *   • No "Close Polygon" button.
 */
import React, { useState, useEffect, useRef, useCallback } from 'react'
import useStore from '../store'
import { createZone, deleteZone, createObstacle, deleteObstacle } from '../api'

// ── Constants ─────────────────────────────────────────────────────────────────
const SNAP_SCREEN_PX = 18

const CAM_COLORS = [
  '#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4',
  '#FFEAA7', '#DDA0DD', '#98D8C8', '#F7DC6F',
]
const ZONE_COLORS = {
  entrance:   '#00FF9D',
  checkout:   '#00D4FF',
  aisle:      '#FFEAA7',
  staff_only: '#FF6B6B',
  general:    '#DDA0DD',
}
const ZONE_TYPES = ['entrance', 'checkout', 'aisle', 'staff_only', 'general']

// ── Canvas helpers (identical to CalibStep2) ──────────────────────────────────

function wToC(wx, wy, t) { return { x: wx*t.scale + t.offsetX, y: -wy*t.scale + t.offsetY } }
function cToW(cx, cy, t) { return { x: (cx - t.offsetX)/t.scale, y: -(cy - t.offsetY)/t.scale } }

function fitScene(allX, allY, W, H, pad = 56) {
  if (!allX.length) return { scale: 50, offsetX: W/2, offsetY: H/2 }
  const xMin = Math.min(...allX), xMax = Math.max(...allX)
  const yMin = Math.min(...allY), yMax = Math.max(...allY)
  const scale = Math.min((W-pad*2)/Math.max(xMax-xMin,1), (H-pad*2)/Math.max(yMax-yMin,1))
  return { scale, offsetX: W/2 - ((xMin+xMax)/2)*scale, offsetY: H/2 + ((yMin+yMax)/2)*scale }
}

function drawAdaptiveGrid(ctx, t, W, H) {
  const wLeft   = cToW(0,0,t).x,  wRight  = cToW(W,0,t).x
  const wTop    = cToW(0,0,t).y,  wBottom = cToW(0,H,t).y
  const yLo = Math.min(wTop,wBottom), yHi = Math.max(wTop,wBottom)
  const rawStep = 80/t.scale
  if (rawStep<=0||!isFinite(rawStep)) return
  const mag = Math.pow(10, Math.floor(Math.log10(Math.abs(rawStep)||1)))
  const norm = rawStep/mag
  const niceNorm = norm<1.5?1:norm<3.5?2:norm<7.5?5:10
  const major = niceNorm*mag, minor = major/5
  ctx.lineWidth=0.5; ctx.strokeStyle='#1E2235'
  for (let x=Math.floor(wLeft/minor)*minor; x<=wRight; x+=minor) {
    if (Math.abs(x%major)<minor*0.01) continue
    const cx=wToC(x,0,t).x; ctx.beginPath(); ctx.moveTo(cx,0); ctx.lineTo(cx,H); ctx.stroke()
  }
  for (let y=Math.floor(yLo/minor)*minor; y<=yHi; y+=minor) {
    if (Math.abs(y%major)<minor*0.01) continue
    const cy=wToC(0,y,t).y; ctx.beginPath(); ctx.moveTo(0,cy); ctx.lineTo(W,cy); ctx.stroke()
  }
  ctx.lineWidth=1; ctx.strokeStyle='#2D3142'
  for (let x=Math.floor(wLeft/major)*major; x<=wRight; x+=major) {
    const cx=wToC(x,0,t).x; ctx.beginPath(); ctx.moveTo(cx,0); ctx.lineTo(cx,H); ctx.stroke()
  }
  for (let y=Math.floor(yLo/major)*major; y<=yHi; y+=major) {
    const cy=wToC(0,y,t).y; ctx.beginPath(); ctx.moveTo(0,cy); ctx.lineTo(W,cy); ctx.stroke()
  }
  ctx.lineWidth=1.5; ctx.strokeStyle='#3D4562'
  const ox=wToC(0,0,t).x, oy=wToC(0,0,t).y
  ctx.beginPath(); ctx.moveTo(ox,0); ctx.lineTo(ox,H); ctx.stroke()
  ctx.beginPath(); ctx.moveTo(0,oy); ctx.lineTo(W,oy); ctx.stroke()
  ctx.fillStyle='#6B7280'; ctx.font='9px monospace'
  const fmt = v => Number.isInteger(v)?String(v):v.toPrecision(2)
  ctx.textAlign='center'
  for (let x=Math.floor(wLeft/major)*major; x<=wRight; x+=major)
    ctx.fillText(fmt(x), wToC(x,0,t).x, H-4)
  ctx.textAlign='right'
  for (let y=Math.floor(yLo/major)*major; y<=yHi; y+=major)
    ctx.fillText(fmt(y), 30, wToC(0,y,t).y+3)
}

function drawScaleBar(ctx, t, W, H) {
  const raw=80/t.scale
  const mag=Math.pow(10,Math.floor(Math.log10(Math.max(raw,1e-10))))
  const nice=((raw/mag)<1.5?1:(raw/mag)<3.5?2:(raw/mag)<7.5?5:10)*mag
  const barPx=nice*t.scale, barX=W-barPx-16, barY=H-22
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
  const sz=9; ctx.save(); ctx.beginPath()
  ctx.moveTo(x,y-sz*1.2); ctx.lineTo(x-sz*0.8,y+sz*0.8); ctx.lineTo(x+sz*0.8,y+sz*0.8)
  ctx.closePath(); ctx.fillStyle=color; ctx.strokeStyle='rgba(0,0,0,0.7)'; ctx.lineWidth=1.5
  ctx.fill(); ctx.stroke(); ctx.restore()
}

// ── Main component ────────────────────────────────────────────────────────────

export default function CalibStep3_Zones({ onBack, onNext }) {
  const { worldBounds, cameras, zones, obstacles, addZone, removeZone, addObstacle, removeObstacle } = useStore()

  const canvasRef    = useRef()
  const containerRef = useRef()
  const [size, setSize]         = useState({ width: 900, height: 460 })
  const [transform, setTransform] = useState({ scale: 50, offsetX: 450, offsetY: 230 })
  const [mouseWorld, setMouseWorld] = useState(null)  // display-only world coords
  const [mouseCanvas, setMouseCanvas] = useState(null)  // canvas pixel coords for ghost line

  const transformRef  = useRef(transform)
  const minScaleRef   = useRef(1)
  const isPanning     = useRef(false)
  const panStart      = useRef({ x:0, y:0, ox:0, oy:0 })

  const updateTransform = useCallback(fn => {
    setTransform(prev => {
      const next = typeof fn === 'function' ? fn(prev) : fn
      transformRef.current = next
      return next
    })
  }, [])

  // Zone drawing state
  const [drawMode,       setDrawMode]       = useState('zone')
  const [currentPoints,  setCurrentPoints]  = useState([])  // [{ x, y }] world metres
  const [snapHint,       setSnapHint]       = useState(false)
  const [modal,          setModal]          = useState(null)
  const [form,           setForm]           = useState({ name: '', type: 'general' })
  const [toast,          setToast]          = useState(null)

  const showToast = msg => { setToast(msg); setTimeout(()=>setToast(null), 3000) }

  // ── Resize observer ───────────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return
    const ro = new ResizeObserver(es => {
      const { width, height } = es[0].contentRect
      setSize({ width: Math.round(width), height: Math.round(height || 460) })
    })
    ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [])

  // ── Auto-fit when bounds / size first become available ────────────────────
  useEffect(() => {
    const { xMin=0, xMax=10, yMin=0, yMax=10 } = worldBounds || {}
    const t = fitScene([xMin, xMax], [yMin, yMax], size.width, size.height)
    transformRef.current = t
    setTransform(t)
  }, [worldBounds])   // only re-fit when bounds change, not on every size change

  // ── Update minimum scale (zoom-out limit) ─────────────────────────────────
  useEffect(() => {
    const { xMin=0, xMax=10, yMin=0, yMax=10 } = worldBounds || {}
    const rangeX = Math.max(xMax-xMin, 1), rangeY = Math.max(yMax-yMin, 1)
    minScaleRef.current = Math.min(
      (size.width  - 80) / rangeX,
      (size.height - 80) / rangeY,
    ) * 0.65
  }, [worldBounds, size])

  // ── Draw ──────────────────────────────────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    canvas.width  = size.width
    canvas.height = size.height

    // Background
    ctx.fillStyle = '#0F1117'
    ctx.fillRect(0, 0, size.width, size.height)

    drawAdaptiveGrid(ctx, transform, size.width, size.height)

    // ── Existing zones ──
    for (const zone of zones) {
      const color = ZONE_COLORS[zone.type] || '#DDA0DD'
      if (!zone.points?.length) continue
      const pts = zone.points.map(p => wToC(p.x, p.y, transform))
      ctx.save()
      ctx.beginPath()
      ctx.moveTo(pts[0].x, pts[0].y)
      for (let i=1; i<pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y)
      ctx.closePath()
      ctx.fillStyle = color + '28'; ctx.fill()
      ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.stroke()
      const cx = pts.reduce((s,p)=>s+p.x,0)/pts.length
      const cy = pts.reduce((s,p)=>s+p.y,0)/pts.length
      ctx.fillStyle = color; ctx.font = 'bold 11px monospace'; ctx.textAlign = 'center'
      ctx.fillText(zone.name, cx, cy+4)
      ctx.restore()
    }

    // ── Existing obstacles ──
    for (const obs of obstacles) {
      if (!obs.points?.length) continue
      const pts = obs.points.map(p => wToC(p.x, p.y, transform))
      ctx.save()
      ctx.beginPath()
      ctx.moveTo(pts[0].x, pts[0].y)
      for (let i=1; i<pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y)
      ctx.closePath()
      ctx.strokeStyle = '#4B5563'; ctx.lineWidth = 2
      ctx.setLineDash([6,3]); ctx.stroke(); ctx.setLineDash([])
      ctx.restore()
    }

    // ── Camera triangles ──
    cameras.filter(c => c.cameraWorldXYZ).forEach((cam, ci) => {
      const { x, y } = wToC(cam.cameraWorldXYZ[0], cam.cameraWorldXYZ[1], transform)
      const color = CAM_COLORS[ci % CAM_COLORS.length]
      drawCameraTriangle(ctx, x, y, color)
      ctx.fillStyle = color; ctx.font = 'bold 9px monospace'; ctx.textAlign = 'center'
      ctx.fillText(cam.name, x, y + 20)
    })

    // ── Current polygon being drawn ──
    if (currentPoints.length > 0) {
      const color = drawMode === 'zone' ? '#00D4FF' : '#9CA3AF'
      const pts = currentPoints.map(p => wToC(p.x, p.y, transform))

      // Filled preview
      if (currentPoints.length >= 3) {
        ctx.save(); ctx.beginPath()
        ctx.moveTo(pts[0].x, pts[0].y)
        for (let i=1; i<pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y)
        ctx.closePath(); ctx.fillStyle = color+'18'; ctx.fill(); ctx.restore()
      }

      // Dashed outline
      ctx.save(); ctx.strokeStyle = color; ctx.lineWidth = 2
      ctx.setLineDash([6,3]); ctx.beginPath()
      ctx.moveTo(pts[0].x, pts[0].y)
      for (let i=1; i<pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y)
      ctx.stroke(); ctx.setLineDash([]); ctx.restore()

      // Ghost line to cursor
      if (mouseCanvas) {
        ctx.save(); ctx.strokeStyle = color; ctx.lineWidth = 1; ctx.globalAlpha = 0.5
        ctx.setLineDash([4,4]); ctx.beginPath()
        ctx.moveTo(pts[pts.length-1].x, pts[pts.length-1].y)
        ctx.lineTo(mouseCanvas.x, mouseCanvas.y)
        ctx.stroke(); ctx.setLineDash([]); ctx.restore()
      }

      // Vertices
      for (let i=0; i<pts.length; i++) {
        // Snap ring on first vertex
        if (i===0 && snapHint) {
          ctx.save(); ctx.beginPath()
          ctx.arc(pts[0].x, pts[0].y, 16, 0, Math.PI*2)
          ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.globalAlpha = 0.55
          ctx.stroke(); ctx.restore()
        }
        const r = (i===0 && currentPoints.length>=2) ? 6 : 4
        ctx.beginPath(); ctx.arc(pts[i].x, pts[i].y, r, 0, Math.PI*2)
        ctx.fillStyle = i===0 ? color : color+'BB'
        ctx.fill()
        ctx.strokeStyle = 'white'; ctx.lineWidth = 1.5; ctx.stroke()
      }
    }

    drawScaleBar(ctx, transform, size.width, size.height)
  }, [zones, obstacles, cameras, currentPoints, mouseCanvas, snapHint, transform, size, worldBounds, drawMode])

  // ── Wheel zoom with limit ─────────────────────────────────────────────────
  const handleWheel = useCallback(e => {
    e.preventDefault()
    const rect  = canvasRef.current.getBoundingClientRect()
    const cx    = e.clientX - rect.left, cy = e.clientY - rect.top
    const delta = e.deltaY > 0 ? 0.85 : 1.18
    updateTransform(t => {
      const attempted = t.scale * delta
      if (delta < 1 && attempted < minScaleRef.current) return t
      return { scale: attempted, offsetX: cx+(t.offsetX-cx)*delta, offsetY: cy+(t.offsetY-cy)*delta }
    })
  }, [updateTransform])

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    el.addEventListener('wheel', handleWheel, { passive: false })
    return () => el.removeEventListener('wheel', handleWheel)
  }, [handleWheel])

  // ── Mouse events ──────────────────────────────────────────────────────────
  function handleMouseMove(e) {
    const rect = canvasRef.current.getBoundingClientRect()
    const cx = e.clientX - rect.left, cy = e.clientY - rect.top
    const t = transformRef.current
    setMouseCanvas({ x: cx, y: cy })
    setMouseWorld(cToW(cx, cy, t))

    // Snap hint: is cursor near first vertex?
    if (currentPoints.length >= 2) {
      const first = wToC(currentPoints[0].x, currentPoints[0].y, t)
      const dx = cx-first.x, dy = cy-first.y
      setSnapHint(Math.sqrt(dx*dx+dy*dy) < SNAP_SCREEN_PX)
    } else {
      setSnapHint(false)
    }

    // Pan
    if (isPanning.current) {
      const dx = e.clientX - panStart.current.x, dy = e.clientY - panStart.current.y
      updateTransform({ scale: t.scale, offsetX: panStart.current.ox+dx, offsetY: panStart.current.oy+dy })
    }
  }

  function handleMouseDown(e) {
    if (e.button === 1 || e.button === 2) {
      e.preventDefault()
      isPanning.current = true
      panStart.current = {
        x: e.clientX, y: e.clientY,
        ox: transformRef.current.offsetX, oy: transformRef.current.offsetY,
      }
    }
  }

  function handleMouseUp()    { isPanning.current = false }
  function handleMouseLeave() {
    isPanning.current = false
    setMouseCanvas(null); setMouseWorld(null); setSnapHint(false)
  }

  function handleClick(e) {
    if (e.button !== 0) return
    const rect = canvasRef.current.getBoundingClientRect()
    const cx = e.clientX - rect.left, cy = e.clientY - rect.top
    const t = transformRef.current
    const world = cToW(cx, cy, t)

    // Auto-close when near first point
    if (currentPoints.length >= 2) {
      const first = wToC(currentPoints[0].x, currentPoints[0].y, t)
      const dx = cx-first.x, dy = cy-first.y
      if (Math.sqrt(dx*dx+dy*dy) < SNAP_SCREEN_PX) {
        closePoly(drawMode)
        return
      }
    }

    setCurrentPoints(pts => [...pts, { x: world.x, y: world.y }])
  }

  // ── Polygon close & save ──────────────────────────────────────────────────
  function closePoly(type) {
    if (currentPoints.length < 3) { showToast('Need at least 3 points'); return }
    if (type === 'zone') {
      setModal({ type: 'zone', points: currentPoints })
    } else {
      saveObstacle(currentPoints)
    }
    setCurrentPoints([])
    setSnapHint(false)
  }

  async function saveZone() {
    if (!form.name.trim()) return
    const id   = crypto.randomUUID()
    const zone = { id, name: form.name.trim(), type: form.type, points: modal.points }
    try { await createZone(zone); addZone(zone); showToast(`Zone "${zone.name}" added`) }
    catch (e) { showToast(`Error: ${e.message}`) }
    setModal(null); setForm({ name: '', type: 'general' })
  }

  async function saveObstacle(pts) {
    const id  = crypto.randomUUID()
    const obs = { id, name: 'Obstacle', points: pts }
    try { await createObstacle(obs); addObstacle(obs); showToast('Obstacle added') }
    catch (e) { showToast(`Error: ${e.message}`) }
  }

  async function handleDeleteZone(id) {
    try { await deleteZone(id) } catch (_) {}
    removeZone(id)
  }
  async function handleDeleteObstacle(id) {
    try { await deleteObstacle(id) } catch (_) {}
    removeObstacle(id)
  }

  function handleFit() {
    const { xMin=0, xMax=10, yMin=0, yMax=10 } = worldBounds || {}
    const t = fitScene([xMin, xMax], [yMin, yMax], size.width, size.height)
    transformRef.current = t; setTransform(t)
  }

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col px-4 pt-3 pb-2" style={{ height: '100%', maxWidth: 1200, margin: '0 auto' }}>

      {/* ── Top bar: title + toolbar ── */}
      <div className="flex items-center gap-4 mb-2 shrink-0 flex-wrap">
        <div>
          <h2 className="text-base font-bold text-gray-800 leading-tight">Draw Zones</h2>
          <p className="text-gray-500 text-xs">
            Click to place vertices · click near the <strong>first vertex</strong> to close · scroll=zoom · middle-drag=pan
          </p>
        </div>

        {/* Mode toggle */}
        <div className="flex rounded-lg border border-gray-200 overflow-hidden">
          {['zone', 'obstacle'].map(m => (
            <button key={m}
              onClick={() => { setDrawMode(m); setCurrentPoints([]); setSnapHint(false) }}
              className={`px-3 py-1.5 text-xs font-medium transition-colors ${drawMode===m?'bg-blue-600 text-white':'bg-white text-gray-600 hover:bg-gray-50'}`}>
              {m === 'zone' ? 'Zone' : 'Obstacle'}
            </button>
          ))}
        </div>

        {/* In-progress indicator */}
        {currentPoints.length > 0 && (
          <>
            <span className="text-xs font-mono px-2 py-1 rounded"
              style={{ background: '#0F1117', color: '#9CA3AF', border: '1px solid #2D3142' }}>
              {currentPoints.length} pt{currentPoints.length!==1?'s':''} — click first vertex to close
            </span>
            <button onClick={() => { setCurrentPoints([]); setSnapHint(false) }}
              className="px-3 py-1.5 rounded-lg border text-xs text-gray-600 hover:bg-gray-50">
              Cancel
            </button>
          </>
        )}

        {/* Fit + coords */}
        <div className="ml-auto flex items-center gap-3">
          {mouseWorld && (
            <span className="text-xs font-mono" style={{ color: '#6B7280' }}>
              ({mouseWorld.x.toFixed(2)}, {mouseWorld.y.toFixed(2)}) m
            </span>
          )}
          <button onClick={handleFit}
            className="px-2 py-1 text-xs font-mono rounded transition-colors"
            style={{ background: '#1A1D27', border: '1px solid #2D3142', color: '#9CA3AF' }}
            onMouseEnter={e => { e.currentTarget.style.color='#00D4FF'; e.currentTarget.style.borderColor='#00D4FF' }}
            onMouseLeave={e => { e.currentTarget.style.color='#9CA3AF'; e.currentTarget.style.borderColor='#2D3142' }}>
            Fit
          </button>
        </div>
      </div>

      {/* ── Canvas ── */}
      <div
        ref={containerRef}
        className="flex-1 relative rounded-xl overflow-hidden"
        style={{ border: '1px solid #2D3142', cursor: 'crosshair', minHeight: 320 }}
      >
        <canvas
          ref={canvasRef}
          style={{ display: 'block' }}
          onMouseMove={handleMouseMove}
          onMouseDown={handleMouseDown}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseLeave}
          onClick={handleClick}
          onContextMenu={e => e.preventDefault()}
        />
        {/* Mouse coord bottom-left */}
        {mouseWorld && (
          <div className="absolute bottom-2 left-2 text-xs font-mono bg-black/60 px-2 py-1 rounded pointer-events-none"
            style={{ color: '#9CA3AF' }}>
            X={mouseWorld.x.toFixed(3)}  Y={mouseWorld.y.toFixed(3)}
          </div>
        )}
      </div>

      {/* ── Bottom: zone chips + navigation ── */}
      <div className="shrink-0 mt-2 space-y-2">
        {/* Zone / obstacle chips */}
        {(zones.length > 0 || obstacles.length > 0) && (
          <div className="flex flex-wrap gap-1.5">
            {zones.map(z => {
              const col = ZONE_COLORS[z.type] || '#DDA0DD'
              return (
                <span key={z.id} className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium"
                  style={{ background: col+'22', color: col, border: `1px solid ${col}44` }}>
                  {z.name}
                  <span className="opacity-50 text-xs">{z.type}</span>
                  <button onClick={() => handleDeleteZone(z.id)} className="ml-0.5 opacity-60 hover:opacity-100">×</button>
                </span>
              )
            })}
            {obstacles.map((obs, i) => (
              <span key={obs.id} className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium"
                style={{ background: '#ffffff12', color: '#9CA3AF', border: '1px solid #2D3142' }}>
                Obstacle {i+1}
                <button onClick={() => handleDeleteObstacle(obs.id)} className="ml-0.5 opacity-60 hover:opacity-100">×</button>
              </span>
            ))}
          </div>
        )}

        {/* Navigation */}
        <div className="flex gap-3">
          <button onClick={onBack}
            className="flex-1 py-2.5 rounded-lg border border-gray-300 text-gray-600 text-sm font-medium hover:bg-gray-50">
            ← Back
          </button>
          <button onClick={() => onNext && onNext()}
            className="flex-1 py-2.5 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700">
            Next: Upload Videos →
          </button>
        </div>
      </div>

      {/* ── Zone naming modal ── */}
      {modal?.type === 'zone' && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-xl p-6 w-80">
            <h3 className="font-semibold text-gray-800 mb-4">Name this Zone</h3>
            <div className="space-y-3 mb-4">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Zone Name</label>
                <input
                  value={form.name}
                  onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                  onKeyDown={e => e.key==='Enter' && saveZone()}
                  className="w-full border rounded px-3 py-2 text-sm"
                  placeholder="e.g. Entrance"
                  autoFocus />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Zone Type</label>
                <select
                  value={form.type}
                  onChange={e => setForm(f => ({ ...f, type: e.target.value }))}
                  className="w-full border rounded px-3 py-2 text-sm bg-white">
                  {ZONE_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
            </div>
            <div className="flex gap-3">
              <button onClick={() => { setModal(null); setForm({ name: '', type: 'general' }) }}
                className="flex-1 py-2 rounded-lg border text-sm text-gray-600 hover:bg-gray-50">
                Cancel
              </button>
              <button disabled={!form.name.trim()} onClick={saveZone}
                className="flex-1 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-40">
                Save Zone
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Toast ── */}
      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 text-white text-sm px-5 py-2 rounded-full shadow-lg z-50 font-mono"
          style={{ background: '#1A1D27', border: '1px solid #2D3142' }}>
          {toast}
        </div>
      )}
    </div>
  )
}
