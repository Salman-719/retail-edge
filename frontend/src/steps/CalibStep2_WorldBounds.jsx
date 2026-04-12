/**
 * CalibStep2_WorldBounds — Method 2 Step 2
 *
 * Interactive world-bounds editor matching the WildTrack ground-mapping-tool aesthetic:
 *   • Dark theme (#0F1117 background, #1A1D27 surface, #2D3142 borders)
 *   • Camera panels: dark surface, circle markers with sequence numbers and tooltips
 *   • World map: HTML5 canvas with adaptive minor/major grid, scale bar,
 *     camera triangle icons, pan (middle-click drag) and zoom (scroll wheel)
 *   • Auto-fit when bounds are computed
 *
 * Projection math (OpenCV convention):
 *   C  = −Rᵀ · t        (camera centre in world)
 *   d  = normalise(Rᵀ · K⁻¹ · [u,v,1]ᵀ)   (ray direction)
 *   s  = −C_z / d_z      (parameter to ground Z=0)
 *   P  = C + s · d       → (world_x, world_y)
 */
import React, { useState, useEffect, useRef, useCallback } from 'react'
import useStore from '../store'
import { listCamerasWithCalibration, saveWorldBounds } from '../api'

// ── WildTrack color palette ────────────────────────────────────────────────────
const CAM_COLORS = [
  '#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4',
  '#FFEAA7', '#DDA0DD', '#98D8C8', '#F7DC6F',
  '#BB8FCE', '#85C1E9', '#82E0AA', '#F0B27A',
]

// ── 3×3 matrix helpers ────────────────────────────────────────────────────────

function mv(M, v) {
  return [
    M[0][0]*v[0] + M[0][1]*v[1] + M[0][2]*v[2],
    M[1][0]*v[0] + M[1][1]*v[1] + M[1][2]*v[2],
    M[2][0]*v[0] + M[2][1]*v[1] + M[2][2]*v[2],
  ]
}
function mtranspose(M) {
  return [
    [M[0][0], M[1][0], M[2][0]],
    [M[0][1], M[1][1], M[2][1]],
    [M[0][2], M[1][2], M[2][2]],
  ]
}
function minv3(M) {
  const [[a,b,c],[d,e,f],[g,h,k]] = M
  const det = a*(e*k-f*h) - b*(d*k-f*g) + c*(d*h-e*g)
  if (Math.abs(det) < 1e-12) return null
  return [
    [(e*k-f*h)/det, (c*h-b*k)/det, (b*f-c*e)/det],
    [(f*g-d*k)/det, (a*k-c*g)/det, (c*d-a*f)/det],
    [(d*h-e*g)/det, (b*g-a*h)/det, (a*e-b*d)/det],
  ]
}

function projectToGround(u, v, K, R, t) {
  const Rt   = mtranspose(R)
  const Kinv = minv3(K)
  if (!Kinv) return null
  const Rtt  = mv(Rt, t)
  const C    = [-Rtt[0], -Rtt[1], -Rtt[2]]
  const rayCam   = mv(Kinv, [u, v, 1.0])
  const rayWorld = mv(Rt, rayCam)
  const norm = Math.sqrt(rayWorld.reduce((s, x) => s + x*x, 0))
  if (norm < 1e-10) return null
  const d = rayWorld.map(x => x/norm)
  if (Math.abs(d[2]) < 1e-4) return null
  const s = -C[2] / d[2]
  if (s <= 0) return null
  return { wx: C[0] + s*d[0], wy: C[1] + s*d[1] }
}

// ── Canvas transform helpers ──────────────────────────────────────────────────

function wToC(wx, wy, t) {
  return { x: wx * t.scale + t.offsetX, y: -wy * t.scale + t.offsetY }
}
function cToW(cx, cy, t) {
  return { x: (cx - t.offsetX) / t.scale, y: -(cy - t.offsetY) / t.scale }
}
function fitScene(allX, allY, W, H, pad = 48) {
  if (!allX.length) return { scale: 50, offsetX: W/2, offsetY: H/2 }
  const xMin = Math.min(...allX), xMax = Math.max(...allX)
  const yMin = Math.min(...allY), yMax = Math.max(...allY)
  const rangeX = Math.max(xMax - xMin, 1)
  const rangeY = Math.max(yMax - yMin, 1)
  const scale  = Math.min((W - pad*2) / rangeX, (H - pad*2) / rangeY)
  const midX   = (xMin + xMax) / 2
  const midY   = (yMin + yMax) / 2
  return { scale, offsetX: W/2 - midX*scale, offsetY: H/2 + midY*scale }
}

// ── Canvas draw helpers ───────────────────────────────────────────────────────

function drawAdaptiveGrid(ctx, t, W, H) {
  const wLeft   = cToW(0, 0, t).x
  const wRight  = cToW(W, 0, t).x
  const wBottom = cToW(0, H, t).y   // lower in world (canvas bottom)
  const wTop    = cToW(0, 0, t).y   // upper in world (canvas top)

  const rawStep = 80 / t.scale
  if (rawStep <= 0 || !isFinite(rawStep)) return
  const mag      = Math.pow(10, Math.floor(Math.log10(Math.abs(rawStep) || 1)))
  const norm     = rawStep / mag
  const niceNorm = norm < 1.5 ? 1 : norm < 3.5 ? 2 : norm < 7.5 ? 5 : 10
  const major    = niceNorm * mag
  const minor    = major / 5

  const yLo = Math.min(wTop, wBottom)
  const yHi = Math.max(wTop, wBottom)

  // minor lines
  ctx.lineWidth = 0.5
  ctx.strokeStyle = '#1E2235'
  for (let x = Math.floor(wLeft/minor)*minor; x <= wRight; x += minor) {
    if (Math.abs(x % major) < minor * 0.01) continue
    const cx = wToC(x, 0, t).x
    ctx.beginPath(); ctx.moveTo(cx, 0); ctx.lineTo(cx, H); ctx.stroke()
  }
  for (let y = Math.floor(yLo/minor)*minor; y <= yHi; y += minor) {
    if (Math.abs(y % major) < minor * 0.01) continue
    const cy = wToC(0, y, t).y
    ctx.beginPath(); ctx.moveTo(0, cy); ctx.lineTo(W, cy); ctx.stroke()
  }
  // major lines
  ctx.lineWidth = 1
  ctx.strokeStyle = '#2D3142'
  for (let x = Math.floor(wLeft/major)*major; x <= wRight; x += major) {
    const cx = wToC(x, 0, t).x
    ctx.beginPath(); ctx.moveTo(cx, 0); ctx.lineTo(cx, H); ctx.stroke()
  }
  for (let y = Math.floor(yLo/major)*major; y <= yHi; y += major) {
    const cy = wToC(0, y, t).y
    ctx.beginPath(); ctx.moveTo(0, cy); ctx.lineTo(W, cy); ctx.stroke()
  }
  // axes
  ctx.lineWidth = 1.5
  ctx.strokeStyle = '#3D4562'
  const ox = wToC(0, 0, t).x, oy = wToC(0, 0, t).y
  ctx.beginPath(); ctx.moveTo(ox, 0); ctx.lineTo(ox, H); ctx.stroke()
  ctx.beginPath(); ctx.moveTo(0, oy); ctx.lineTo(W, oy); ctx.stroke()
  // labels
  ctx.fillStyle = '#6B7280'
  ctx.font = '9px monospace'
  const fmt = v => Number.isInteger(v) ? String(v) : v.toPrecision(2)
  ctx.textAlign = 'center'
  for (let x = Math.floor(wLeft/major)*major; x <= wRight; x += major) {
    const cx = wToC(x, 0, t).x
    ctx.fillText(fmt(x), cx, H - 4)
  }
  ctx.textAlign = 'right'
  for (let y = Math.floor(yLo/major)*major; y <= yHi; y += major) {
    const cy = wToC(0, y, t).y
    ctx.fillText(fmt(y), 30, cy + 3)
  }
}

function drawScaleBar(ctx, t, W, H) {
  const raw  = 80 / t.scale
  const mag  = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 1e-10))))
  const norm = raw / mag
  const nice = norm < 1.5 ? 1 : norm < 3.5 ? 2 : norm < 7.5 ? 5 : 10
  const barLen = nice * mag
  const barPx  = barLen * t.scale
  const barX   = W - barPx - 16
  const barY   = H - 22
  ctx.save()
  ctx.strokeStyle = '#6B7280'
  ctx.lineWidth = 2
  ctx.beginPath()
  ctx.moveTo(barX, barY);     ctx.lineTo(barX + barPx, barY)
  ctx.moveTo(barX, barY-4);   ctx.lineTo(barX, barY+4)
  ctx.moveTo(barX+barPx, barY-4); ctx.lineTo(barX+barPx, barY+4)
  ctx.stroke()
  ctx.fillStyle = '#9CA3AF'
  ctx.font = '9px monospace'
  ctx.textAlign = 'center'
  const label = Number.isInteger(barLen) ? `${barLen} m` : `${barLen.toPrecision(2)} m`
  ctx.fillText(label, barX + barPx/2, barY + 13)
  ctx.restore()
}

function drawCameraTriangle(ctx, x, y, color) {
  const sz = 9
  ctx.save()
  ctx.beginPath()
  ctx.moveTo(x, y - sz * 1.2)
  ctx.lineTo(x - sz * 0.8, y + sz * 0.8)
  ctx.lineTo(x + sz * 0.8, y + sz * 0.8)
  ctx.closePath()
  ctx.fillStyle = color
  ctx.strokeStyle = 'rgba(0,0,0,0.7)'
  ctx.lineWidth = 1.5
  ctx.fill()
  ctx.stroke()
  ctx.restore()
}

// ── World Map Canvas ──────────────────────────────────────────────────────────

const MAP_H = 520

function WorldMapCanvas({ cameras, points, bounds, camColorMap, fitTrigger }) {
  const canvasRef    = useRef()
  const containerRef = useRef()
  const [size, setSize] = useState({ width: 360, height: MAP_H })
  const [transform, setTransform] = useState({ scale: 50, offsetX: 180, offsetY: 260 })
  const [mouseWorld, setMouseWorld] = useState(null)
  const isPanning    = useRef(false)
  const panStart     = useRef({ x: 0, y: 0, ox: 0, oy: 0 })
  const transformRef = useRef(transform)
  const minScaleRef  = useRef(1)   // updated whenever the scene data changes

  const updateTransform = useCallback((fn) => {
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
      setSize({ width: Math.round(width), height: Math.round(height || MAP_H) })
    })
    ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [])

  // Auto-fit
  useEffect(() => {
    const allX = [
      ...points.map(p => p.wx),
      ...cameras.filter(c => c.cameraWorldXYZ).map(c => c.cameraWorldXYZ[0]),
      ...(bounds ? [bounds.xMin, bounds.xMax] : []),
    ]
    const allY = [
      ...points.map(p => p.wy),
      ...cameras.filter(c => c.cameraWorldXYZ).map(c => c.cameraWorldXYZ[1]),
      ...(bounds ? [bounds.yMin, bounds.yMax] : []),
    ]
    if (allX.length > 0) {
      const t = fitScene(allX, allY, size.width, size.height)
      transformRef.current = t
      setTransform(t)
    }
  }, [fitTrigger, size])   // intentionally not including dynamic data — only triggered explicitly

  // Keep min-scale in sync so zoom-out never makes the area of interest tiny
  useEffect(() => {
    const allX = [
      ...points.map(p => p.wx),
      ...cameras.filter(c => c.cameraWorldXYZ).map(c => c.cameraWorldXYZ[0]),
      ...(bounds ? [bounds.xMin, bounds.xMax] : []),
    ]
    const allY = [
      ...points.map(p => p.wy),
      ...cameras.filter(c => c.cameraWorldXYZ).map(c => c.cameraWorldXYZ[1]),
      ...(bounds ? [bounds.yMin, bounds.yMax] : []),
    ]
    if (allX.length > 1) {
      const rangeX = Math.max(Math.max(...allX) - Math.min(...allX), 1)
      const rangeY = Math.max(Math.max(...allY) - Math.min(...allY), 1)
      // Allow zoom-out only to 65 % of the "fit everything" scale
      minScaleRef.current = Math.min(
        (size.width  - 80) / rangeX,
        (size.height - 80) / rangeY,
      ) * 0.65
    }
  }, [points, cameras, bounds, size])

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

    const hasData = points.length > 0 || cameras.some(c => c.cameraWorldXYZ)
    if (!hasData) {
      ctx.fillStyle = '#2D3142'
      ctx.font = '11px monospace'
      ctx.textAlign = 'center'
      ctx.fillText('Upload frames and click floor points to begin', size.width/2, size.height/2)
      return
    }

    drawAdaptiveGrid(ctx, transform, size.width, size.height)

    // Bounds dashed rectangle
    if (bounds) {
      const tl = wToC(bounds.xMin, bounds.yMax, transform)
      const br = wToC(bounds.xMax, bounds.yMin, transform)
      ctx.save()
      ctx.setLineDash([6, 3])
      ctx.strokeStyle = '#00D4FF'
      ctx.lineWidth = 1.5
      ctx.fillStyle = 'rgba(0,212,255,0.04)'
      ctx.fillRect(tl.x, tl.y, br.x - tl.x, br.y - tl.y)
      ctx.strokeRect(tl.x, tl.y, br.x - tl.x, br.y - tl.y)
      ctx.setLineDash([])
      ctx.restore()
    }

    // Camera positions
    for (const cam of cameras.filter(c => c.cameraWorldXYZ)) {
      const { x, y } = wToC(cam.cameraWorldXYZ[0], cam.cameraWorldXYZ[1], transform)
      const color = camColorMap[cam.id] || '#FFEAA7'
      drawCameraTriangle(ctx, x, y, color)
      ctx.fillStyle = color
      ctx.font = 'bold 9px monospace'
      ctx.textAlign = 'center'
      ctx.fillText(cam.name, x, y + 20)
    }

    // Placed ground points
    for (const pt of points) {
      const { x, y } = wToC(pt.wx, pt.wy, transform)
      ctx.beginPath()
      ctx.arc(x, y, 5, 0, Math.PI * 2)
      ctx.fillStyle = pt.color
      ctx.fill()
      ctx.strokeStyle = 'white'
      ctx.lineWidth = 1.5
      ctx.stroke()
    }

    drawScaleBar(ctx, transform, size.width, size.height)
  }, [cameras, points, bounds, camColorMap, transform, size])

  // Wheel zoom — passive:false needed
  const handleWheel = useCallback(e => {
    e.preventDefault()
    const rect = canvasRef.current.getBoundingClientRect()
    const cx = e.clientX - rect.left
    const cy = e.clientY - rect.top
    const delta = e.deltaY > 0 ? 0.85 : 1.18
    updateTransform(t => {
      const attempted = t.scale * delta
      // Block zoom-out past minimum scale
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
    const cx = e.clientX - rect.left
    const cy = e.clientY - rect.top
    setMouseWorld(cToW(cx, cy, transformRef.current))
    if (isPanning.current) {
      const dx = e.clientX - panStart.current.x
      const dy = e.clientY - panStart.current.y
      updateTransform({
        scale:   transformRef.current.scale,
        offsetX: panStart.current.ox + dx,
        offsetY: panStart.current.oy + dy,
      })
    }
  }
  function handleMouseDown(e) {
    if (e.button === 1 || e.button === 2) {
      e.preventDefault()
      isPanning.current = true
      panStart.current = {
        x: e.clientX, y: e.clientY,
        ox: transformRef.current.offsetX,
        oy: transformRef.current.offsetY,
      }
    }
  }
  function handleMouseUp()    { isPanning.current = false }
  function handleMouseLeave() { isPanning.current = false; setMouseWorld(null) }

  return (
    <div ref={containerRef}
      className="relative rounded-xl overflow-hidden"
      style={{ background: '#0F1117', border: '1px solid #2D3142', height: MAP_H }}
    >
      <canvas
        ref={canvasRef}
        style={{ display: 'block', cursor: 'default' }}
        onMouseMove={handleMouseMove}
        onMouseDown={handleMouseDown}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseLeave}
        onContextMenu={e => e.preventDefault()}
      />
      {/* Coordinate readout */}
      {mouseWorld && (
        <div className="absolute bottom-2 left-2 text-xs font-mono bg-black/60 px-2 py-1 rounded pointer-events-none"
          style={{ color: '#9CA3AF' }}>
          X={mouseWorld.x.toFixed(3)}  Y={mouseWorld.y.toFixed(3)}
        </div>
      )}
      {/* Top-right controls */}
      <div className="absolute top-2 right-2">
        <button
          onClick={() => {
            const allX = [...points.map(p => p.wx), ...cameras.filter(c => c.cameraWorldXYZ).map(c => c.cameraWorldXYZ[0]), ...(bounds ? [bounds.xMin, bounds.xMax] : [])]
            const allY = [...points.map(p => p.wy), ...cameras.filter(c => c.cameraWorldXYZ).map(c => c.cameraWorldXYZ[1]), ...(bounds ? [bounds.yMin, bounds.yMax] : [])]
            if (allX.length) { const t = fitScene(allX, allY, size.width, size.height); transformRef.current = t; setTransform(t) }
          }}
          className="px-2 py-1 text-xs font-mono rounded transition-colors"
          style={{ background: '#1A1D27', border: '1px solid #2D3142', color: '#9CA3AF' }}
          onMouseEnter={e => { e.currentTarget.style.color='#00D4FF'; e.currentTarget.style.borderColor='#00D4FF' }}
          onMouseLeave={e => { e.currentTarget.style.color='#9CA3AF'; e.currentTarget.style.borderColor='#2D3142' }}
        >
          Fit
        </button>
      </div>
      {/* Hint: middle click to pan */}
      <div className="absolute bottom-2 right-2 text-xs font-mono pointer-events-none" style={{ color: '#4B5563' }}>
        scroll=zoom · middle-drag=pan
      </div>
    </div>
  )
}

// ── Camera card (dark surface) ────────────────────────────────────────────────

function CameraCard({ cam, color, frame, camPoints, hasCalib, onFrameFile, onFrameClick, onRemovePoint, onUndoLast }) {
  const [mouseCoord, setMouseCoord] = useState(null)
  const containerRef = useRef()

  function handleMouseMove(e) {
    if (!frame) return
    const rect = e.currentTarget.getBoundingClientRect()
    const dx = e.clientX - rect.left
    const dy = e.clientY - rect.top
    const u = Math.round(dx * (frame.naturalWidth / rect.width))
    const v = Math.round(dy * (frame.naturalHeight / rect.height))
    setMouseCoord({ u, v })
  }

  return (
    <div className="rounded-xl overflow-hidden flex flex-col"
      style={{ background: '#1A1D27', border: '1px solid #2D3142' }}>
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b shrink-0"
        style={{ borderColor: '#2D3142' }}>
        <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: color }} />
        <span className="font-mono text-white text-xs font-semibold truncate flex-1">{cam.name}</span>
        {camPoints.length > 0 && (
          <span className="text-xs font-mono px-1.5 py-0.5 rounded"
            style={{ background: color + '22', color }}>
            {camPoints.length} pts
          </span>
        )}
        {camPoints.length > 0 && (
          <>
            <button
              onClick={onUndoLast}
              title="Undo last point"
              className="p-1 rounded transition-colors"
              style={{ color: '#6B7280' }}
              onMouseEnter={e => e.currentTarget.style.color='white'}
              onMouseLeave={e => e.currentTarget.style.color='#6B7280'}
            >
              {/* undo icon */}
              <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8">
                <path d="M3 8a5 5 0 1 0 1.5-3.5L2 7" />
                <path d="M2 4v3h3" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
            <button
              onClick={() => camPoints.forEach(p => onRemovePoint(p.id))}
              title="Clear all points"
              className="p-1 rounded transition-colors"
              style={{ color: '#6B7280' }}
              onMouseEnter={e => e.currentTarget.style.color='#FF4757'}
              onMouseLeave={e => e.currentTarget.style.color='#6B7280'}
            >
              {/* trash icon */}
              <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8">
                <path d="M2 4h12M5 4V2h6v2M3 4l1 10h8l1-10" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </>
        )}
        {!hasCalib && (
          <span className="text-xs font-mono px-2 py-0.5 rounded" style={{ background: '#FFD32A22', color: '#FFD32A' }}>
            no calib
          </span>
        )}
      </div>

      {/* Image / upload area */}
      {!frame ? (
        <button
          onClick={() => onFrameFile(null)}
          disabled={!hasCalib}
          className="w-full py-10 text-xs font-mono transition-colors"
          style={{ color: hasCalib ? '#6B7280' : '#3D4562', cursor: hasCalib ? 'pointer' : 'not-allowed' }}
          onMouseEnter={e => hasCalib && (e.currentTarget.style.color='#00D4FF')}
          onMouseLeave={e => (e.currentTarget.style.color=hasCalib?'#6B7280':'#3D4562')}
        >
          {hasCalib ? '+ Click to upload reference frame' : 'No calibration data in DB'}
        </button>
      ) : (
        <div
          ref={containerRef}
          className="relative select-none"
          style={{ cursor: hasCalib ? 'crosshair' : 'default' }}
          onMouseMove={handleMouseMove}
          onMouseLeave={() => setMouseCoord(null)}
          onClick={hasCalib ? e => onFrameClick(cam, e) : undefined}
        >
          <img
            src={frame.url}
            alt={cam.name}
            className="w-full block"
            draggable={false}
          />

          {/* Point overlay — WildTrack-style circles with sequence numbers */}
          {camPoints.map((pt, idx) => (
            <div
              key={pt.id}
              style={{
                position: 'absolute',
                left:  `${pt.displayPctX}%`,
                top:   `${pt.displayPctY}%`,
                transform: 'translate(-50%, -50%)',
                zIndex: 10,
                pointerEvents: 'auto',
              }}
              onClick={e => { e.stopPropagation(); onRemovePoint(pt.id) }}
              className="cursor-pointer group"
              title={`(${pt.wx.toFixed(3)}, ${pt.wy.toFixed(3)}) m — click to remove`}
            >
              {/* Circle */}
              <div style={{
                width: 20, height: 20, borderRadius: '50%',
                background: color,
                border: '2px solid white',
                boxShadow: '0 1px 6px rgba(0,0,0,0.8)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                transition: 'transform 120ms ease',
              }}
                onMouseEnter={e => e.currentTarget.style.transform='scale(1.4)'}
                onMouseLeave={e => e.currentTarget.style.transform='scale(1)'}
              >
                <span style={{
                  fontSize: 9, fontWeight: 700, color: 'white',
                  fontFamily: 'monospace', lineHeight: 1, userSelect: 'none',
                }}>{idx + 1}</span>
              </div>
              {/* Tooltip */}
              <div className="hidden group-hover:block absolute pointer-events-none"
                style={{
                  left: 24, top: -8, zIndex: 20,
                  background: '#1A1D27', border: '1px solid #2D3142',
                  color: 'white', fontSize: 10, fontFamily: 'monospace',
                  padding: '3px 8px', borderRadius: 4, whiteSpace: 'nowrap',
                  boxShadow: '0 2px 8px rgba(0,0,0,0.6)',
                }}>
                u={Math.round(pt.displayPctX * (frame.naturalWidth/100))},
                v={Math.round(pt.displayPctY * (frame.naturalHeight/100))}
                → ({pt.wx.toFixed(2)}, {pt.wy.toFixed(2)}) m
              </div>
            </div>
          ))}

          {/* Mouse coordinate readout */}
          {mouseCoord && (
            <div className="absolute bottom-1 left-1 text-xs font-mono bg-black/65 px-1.5 py-0.5 rounded pointer-events-none"
              style={{ color: '#9CA3AF' }}>
              u={mouseCoord.u} v={mouseCoord.v}
            </div>
          )}

          {/* Replace button */}
          <button
            onClick={e => { e.stopPropagation(); onFrameFile(null) }}
            className="absolute top-1.5 right-1.5 text-xs font-mono px-1.5 py-0.5 rounded"
            style={{ background: 'rgba(0,0,0,0.55)', color: 'white' }}
            onMouseEnter={e => e.currentTarget.style.background='rgba(0,0,0,0.8)'}
            onMouseLeave={e => e.currentTarget.style.background='rgba(0,0,0,0.55)'}
          >
            Replace
          </button>
        </div>
      )}

      {/* Coordinate list */}
      {camPoints.length > 0 && (
        <div className="border-t px-2 py-1.5 max-h-24 overflow-y-auto"
          style={{ borderColor: '#2D3142' }}>
          {camPoints.map((pt, idx) => (
            <div key={pt.id} className="flex items-center gap-2 text-xs font-mono" style={{ color: '#6B7280' }}>
              <span style={{ color: '#9CA3AF', width: 14 }}>{idx + 1}.</span>
              <span>({pt.wx.toFixed(2)}, {pt.wy.toFixed(2)}) m</span>
              <button onClick={() => onRemovePoint(pt.id)}
                className="ml-auto transition-colors"
                style={{ color: '#4B5563' }}
                onMouseEnter={e => e.currentTarget.style.color='#FF4757'}
                onMouseLeave={e => e.currentTarget.style.color='#4B5563'}
              >✕</button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function CalibStep2_WorldBounds({ onBack, onNext }) {
  const { cameras, worldBounds, setWorldBounds } = useStore()

  const [calibData,    setCalibData]    = useState({})
  const [loadingCalib, setLoadingCalib] = useState(true)
  const [frames,  setFrames]  = useState({})   // camId → { url, naturalWidth, naturalHeight }
  const [points,  setPoints]  = useState([])   // { id, camId, displayPctX, displayPctY, wx, wy, color }
  const [bounds,  setBounds]  = useState(worldBounds ?? null)
  const [saving,  setSaving]  = useState(false)
  const [error,   setError]   = useState(null)
  const [fitTrigger, setFitTrigger] = useState(0)

  const camColorMap = Object.fromEntries(
    cameras.map((c, i) => [c.id, CAM_COLORS[i % CAM_COLORS.length]])
  )

  // Load K, R, t from backend
  useEffect(() => {
    let cancelled = false
    listCamerasWithCalibration()
      .then(cams => {
        if (cancelled) return
        const data = {}
        for (const c of cams) {
          if (c.calibration?.intrinsic_matrix && c.calibration?.rotation_matrix) {
            data[c.id] = {
              K: c.calibration.intrinsic_matrix,
              R: c.calibration.rotation_matrix,
              t: c.calibration.translation_vector,
            }
          }
        }
        setCalibData(data)
      })
      .catch(e => setError(`Could not load calibration: ${e.message}`))
      .finally(() => { if (!cancelled) setLoadingCalib(false) })
    return () => { cancelled = true }
  }, [])

  // Frame upload via hidden file input
  function openFilePicker(camId) {
    const inp = document.createElement('input')
    inp.type = 'file'; inp.accept = 'image/*'
    inp.onchange = e => {
      const file = e.target.files[0]
      if (!file) return
      const url = URL.createObjectURL(file)
      const img = new Image()
      img.onload = () => setFrames(prev => ({
        ...prev, [camId]: { url, naturalWidth: img.naturalWidth, naturalHeight: img.naturalHeight },
      }))
      img.src = url
    }
    inp.click()
  }

  // Click on frame → project to world
  function handleFrameClick(cam, e) {
    const rect = e.currentTarget.getBoundingClientRect()
    const displayX = e.clientX - rect.left
    const displayY = e.clientY - rect.top
    const frame  = frames[cam.id]
    const calib  = calibData[cam.id]
    if (!frame || !calib) return
    const u = displayX * (frame.naturalWidth  / rect.width)
    const v = displayY * (frame.naturalHeight / rect.height)
    const result = projectToGround(u, v, calib.K, calib.R, calib.t)
    if (!result) {
      setError(`Pixel (${u.toFixed(0)}, ${v.toFixed(0)}) does not intersect the ground plane. Click on a flat floor area.`)
      return
    }
    setError(null)
    setPoints(prev => [...prev, {
      id:           `${cam.id}-${Date.now()}`,
      camId:        cam.id,
      displayPctX:  (displayX / rect.width)  * 100,
      displayPctY:  (displayY / rect.height) * 100,
      wx:           result.wx,
      wy:           result.wy,
      color:        camColorMap[cam.id] || '#3b82f6',
    }])
  }

  function removePoint(id)  { setPoints(prev => prev.filter(p => p.id !== id)) }
  function undoLast(camId)  {
    setPoints(prev => {
      const camPts = prev.filter(p => p.camId === camId)
      if (!camPts.length) return prev
      const lastId = camPts[camPts.length - 1].id
      return prev.filter(p => p.id !== lastId)
    })
  }

  // Compute bounds from placed points
  function computeBounds() {
    if (!points.length) return
    const xs = points.map(p => p.wx), ys = points.map(p => p.wy)
    const xMin = Math.min(...xs), xMax = Math.max(...xs)
    const yMin = Math.min(...ys), yMax = Math.max(...ys)
    const padX = Math.max(xMax - xMin, 1) * 0.10
    const padY = Math.max(yMax - yMin, 1) * 0.10
    const nb = { xMin: xMin-padX, xMax: xMax+padX, yMin: yMin-padY, yMax: yMax+padY }
    setBounds(nb)
    setFitTrigger(n => n + 1)
  }

  async function handleSave() {
    if (!bounds) return
    setSaving(true); setError(null)
    try {
      await saveWorldBounds(bounds)
      setWorldBounds(bounds)
      onNext && onNext()
    } catch (e) { setError(e.message) }
    finally { setSaving(false) }
  }

  const calibCameras  = cameras.filter(c => c.calibrationMethod === 'calibration_files')
  const totalPoints   = points.length

  if (loadingCalib) {
    return (
      <div className="max-w-5xl mx-auto py-16 px-4 text-center text-gray-400 text-sm">
        Loading calibration matrices…
      </div>
    )
  }

  return (
    <div className="max-w-7xl mx-auto py-4 px-4">
      <h2 className="text-xl font-bold text-gray-800 mb-1">World Map Bounds</h2>
      <p className="text-gray-500 text-sm mb-4">
        Upload a reference frame for each camera, then click on floor points to project them to
        world coordinates. Compute bounds, then save to continue.
      </p>

      {error && (
        <div className="mb-4 text-sm rounded-lg px-4 py-3"
          style={{ background: '#1A0A0A', border: '1px solid #FF4757', color: '#FF4757' }}>
          {error}
        </div>
      )}

      <div className="flex gap-5 items-start">

        {/* ── Camera frame grid ── */}
        <div className="flex-1 min-w-0 grid grid-cols-1 md:grid-cols-2 gap-4"
          style={{ maxHeight: MAP_H + 40, overflowY: 'auto', paddingRight: 4 }}>
          {calibCameras.length === 0 && (
            <div className="col-span-2 text-center text-gray-400 text-sm py-10 border-2 border-dashed border-gray-200 rounded-xl">
              No calibrated cameras found. Complete Step 1 first.
            </div>
          )}
          {calibCameras.map(cam => (
            <CameraCard
              key={cam.id}
              cam={cam}
              color={camColorMap[cam.id] || '#FF6B6B'}
              frame={frames[cam.id]}
              camPoints={points.filter(p => p.camId === cam.id)}
              hasCalib={!!calibData[cam.id]}
              onFrameFile={() => openFilePicker(cam.id)}
              onFrameClick={handleFrameClick}
              onRemovePoint={removePoint}
              onUndoLast={() => undoLast(cam.id)}
            />
          ))}
        </div>

        {/* ── World map + controls ── */}
        <div className="shrink-0 flex flex-col gap-3" style={{ width: 360 }}>
          <div className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
            World Map
          </div>

          <WorldMapCanvas
            cameras={cameras}
            points={points}
            bounds={bounds}
            camColorMap={camColorMap}
            fitTrigger={fitTrigger}
          />

          {/* Camera legend */}
          <div className="space-y-1">
            {calibCameras.map(cam => {
              const n = points.filter(p => p.camId === cam.id).length
              return (
                <div key={cam.id} className="flex items-center gap-2 text-xs">
                  <span className="w-2.5 h-2.5 rounded-full shrink-0"
                    style={{ background: camColorMap[cam.id] }} />
                  <span className="text-gray-600 truncate">{cam.name}</span>
                  <span className="ml-auto text-gray-400 shrink-0 font-mono">
                    {n} pt{n !== 1 ? 's' : ''}
                  </span>
                </div>
              )
            })}
          </div>

          {/* Action buttons */}
          <div className="flex gap-2">
            <button
              onClick={computeBounds}
              disabled={totalPoints === 0}
              className="flex-1 py-2 text-xs font-semibold rounded-lg text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              style={{ background: totalPoints > 0 ? '#00D4FF22' : '#1A1D27', border: '1px solid #00D4FF44', color: '#00D4FF' }}
              onMouseEnter={e => totalPoints > 0 && (e.currentTarget.style.background='#00D4FF33')}
              onMouseLeave={e => (e.currentTarget.style.background=totalPoints>0?'#00D4FF22':'#1A1D27')}
            >
              ⚡ Compute bounds
            </button>
            <button
              onClick={() => { setPoints([]); setBounds(null) }}
              disabled={totalPoints === 0 && !bounds}
              className="px-3 py-2 text-xs rounded-lg border border-gray-300 text-gray-500 hover:bg-gray-50 disabled:opacity-40"
              title="Clear all"
            >
              Clear
            </button>
          </div>

          {/* Bounds summary */}
          {bounds ? (
            <div className="rounded-lg p-3 text-xs space-y-1.5"
              style={{ background: '#0A1520', border: '1px solid #00D4FF44' }}>
              <div className="font-semibold font-mono" style={{ color: '#00D4FF' }}>
                Bounds (metres)
              </div>
              {[['X', bounds.xMin, bounds.xMax], ['Y', bounds.yMin, bounds.yMax]].map(([ax, mn, mx]) => (
                <div key={ax} className="flex justify-between font-mono" style={{ color: '#9CA3AF' }}>
                  <span style={{ color: '#6B7280' }}>{ax}:</span>
                  <span>
                    {mn.toFixed(2)} → {mx.toFixed(2)}
                    <span style={{ color: '#4B5563' }} className="ml-1">({(mx-mn).toFixed(1)} m)</span>
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-xs text-center py-4 rounded-lg"
              style={{ color: '#4B5563', border: '1px dashed #2D3142' }}>
              Place points then click "Compute bounds"
            </div>
          )}

          <p className="text-xs" style={{ color: '#4B5563' }}>
            Click a dot to remove it. Scroll wheel = zoom · Middle-drag = pan.
          </p>
        </div>
      </div>

      {/* Navigation */}
      <div className="flex gap-3 mt-6">
        <button onClick={onBack}
          className="flex-1 py-3 rounded-lg border border-gray-300 text-gray-600 text-sm font-medium hover:bg-gray-50">
          ← Back
        </button>
        <button
          onClick={handleSave}
          disabled={!bounds || saving}
          className="flex-1 py-3 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {saving ? 'Saving…' : 'Apply & Continue →'}
        </button>
      </div>
    </div>
  )
}
