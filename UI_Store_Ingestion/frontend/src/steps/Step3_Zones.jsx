import React, { useState, useRef, useEffect } from 'react'
import { Stage, Layer, Image as KImage, Line, Circle, Text } from 'react-konva'
import useImage from 'use-image'
import useStore from '../store'

function useContainerWidth(ref) {
  const [width, setWidth] = useState(800)
  useEffect(() => {
    if (!ref.current) return
    const ro = new ResizeObserver(e => setWidth(e[0].contentRect.width || 800))
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [])
  return width
}

function centroid(points) {
  const cx = points.reduce((s, p) => s + p.x, 0) / points.length
  const cy = points.reduce((s, p) => s + p.y, 0) / points.length
  return { x: cx, y: cy }
}

const ZONE_COLORS = {
  entrance: '#22c55e',
  checkout: '#3b82f6',
  aisle: '#f59e0b',
  staff_only: '#ef4444',
  general: '#8b5cf6',
}

export default function Step3_Zones() {
  const { floorPlanUrl, floorPlanWidth, floorPlanHeight, origin, pixelsPerMeter, zones, obstacles, addZone, removeZone, addObstacle, removeObstacle, setStep } = useStore()
  const containerRef = useRef()
  const containerWidth = useContainerWidth(containerRef)
  const [image] = useImage(floorPlanUrl)

  const displayScale = floorPlanWidth > 0 ? containerWidth / floorPlanWidth : 1
  const stageHeight = floorPlanHeight * displayScale

  // Zoom / pan
  const [view, setView] = useState({ scale: 1, x: 0, y: 0 })

  const [drawMode, setDrawMode] = useState('zone')
  const [currentPoints, setCurrentPoints] = useState([]) // floor plan raw pixels
  const [mousePos, setMousePos] = useState(null)         // content display pixels
  const [modal, setModal] = useState(null)
  const [form, setForm] = useState({ name: '', type: 'general' })
  const [toast, setToast] = useState(null)

  const toContent = (containerPos) => ({
    x: (containerPos.x - view.x) / view.scale,
    y: (containerPos.y - view.y) / view.scale,
  })
  const toRaw = (contentPos) => ({ x: contentPos.x / displayScale, y: contentPos.y / displayScale })
  const toDisplay = (p) => ({ x: p.x * displayScale, y: p.y * displayScale })

  const rawToMeters = (p) => ({
    x: (p.x - origin.x) / pixelsPerMeter,
    y: (origin.y - p.y) / pixelsPerMeter,
  })
  const metersToDisplay = (p) => ({
    x: (origin.x + p.x * pixelsPerMeter) * displayScale,
    y: (origin.y - p.y * pixelsPerMeter) * displayScale,
  })

  const showToast = (msg) => {
    setToast(msg)
    setTimeout(() => setToast(null), 3000)
  }

  const handleWheel = (e) => {
    if (!e.evt.ctrlKey) return   // normal scroll → let page scroll
    e.evt.preventDefault()
    const stage = e.target.getStage()
    const pointer = stage.getPointerPosition()
    const scaleBy = 1.15
    const oldScale = view.scale
    const newScale = Math.min(10, Math.max(0.2, e.evt.deltaY < 0 ? oldScale * scaleBy : oldScale / scaleBy))
    const mousePointTo = {
      x: (pointer.x - view.x) / oldScale,
      y: (pointer.y - view.y) / oldScale,
    }
    setView({
      scale: newScale,
      x: pointer.x - mousePointTo.x * newScale,
      y: pointer.y - mousePointTo.y * newScale,
    })
  }

  const handleStageClick = (e) => {
    if (modal) return
    const stage = e.target.getStage()
    const pos = stage.getPointerPosition()
    const contentPos = toContent(pos)
    const raw = toRaw(contentPos)

    // Check if clicking near first point to close polygon (distance in screen pixels)
    if (currentPoints.length >= 3) {
      const firstDisplay = toDisplay(currentPoints[0])
      const firstScreen = {
        x: firstDisplay.x * view.scale + view.x,
        y: firstDisplay.y * view.scale + view.y,
      }
      const screenPos = pos
      const dist = Math.hypot(screenPos.x - firstScreen.x, screenPos.y - firstScreen.y)
      if (dist < 14) {
        closePoly()
        return
      }
    }
    setCurrentPoints(pts => [...pts, raw])
  }

  const closePoly = () => {
    if (currentPoints.length < 3) return
    const pointsMeters = currentPoints.map(rawToMeters)
    // No overlap validation — new zone overwrites the overlapping area (render order handles it)
    setModal({ points: pointsMeters, mode: drawMode })
    setForm({ name: '', type: 'general' })
    setCurrentPoints([])
  }

  const handleModalSave = () => {
    if (!form.name.trim()) return
    if (modal.mode === 'zone') {
      addZone({ id: `zone_${Date.now()}`, name: form.name.trim(), type: form.type, points: modal.points })
    } else {
      addObstacle({ id: `obs_${Date.now()}`, name: form.name.trim(), points: modal.points })
    }
    setModal(null)
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && currentPoints.length >= 3) closePoly()
    if (e.key === 'Escape') setCurrentPoints([])
  }

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  })

  // ── Dynamic grid with meter labels ─────────────────────────────────────────
  const renderGrid = () => {
    if (!origin || !pixelsPerMeter) return null
    const effectivePPM = pixelsPerMeter * displayScale * view.scale
    let metersPerLine
    if (effectivePPM >= 200) metersPerLine = 0.5
    else if (effectivePPM >= 100) metersPerLine = 1
    else if (effectivePPM >= 50) metersPerLine = 2
    else if (effectivePPM >= 20) metersPerLine = 5
    else metersPerLine = 10

    const spacingPx = pixelsPerMeter * displayScale * metersPerLine
    const ox = origin.x * displayScale
    const oy = origin.y * displayScale
    const fs = 8 / view.scale
    const sw = 0.5 / view.scale

    const elements = []

    const xMin = Math.floor((-ox) / spacingPx) - 1
    const xMax = Math.ceil((containerWidth - ox) / spacingPx) + 1
    for (let i = xMin; i <= xMax; i++) {
      const x = ox + i * spacingPx
      const mVal = +(i * metersPerLine).toFixed(1)
      const isOrigin = i === 0
      elements.push(
        <Line key={`v${i}`} points={[x, 0, x, stageHeight]}
          stroke={isOrigin ? '#ef4444' : '#2E75B6'}
          strokeWidth={isOrigin ? sw * 2 : sw}
          opacity={isOrigin ? 0.5 : 0.2} />
      )
      if (!isOrigin) {
        elements.push(
          <Text key={`vt${i}`} x={x + 2 / view.scale} y={4 / view.scale}
            text={`${mVal}m`} fontSize={fs} fill="#2E75B6" opacity={0.7} />
        )
      }
    }

    const yMin = Math.floor((-oy) / spacingPx) - 1
    const yMax = Math.ceil((stageHeight - oy) / spacingPx) + 1
    for (let j = yMin; j <= yMax; j++) {
      const y = oy + j * spacingPx
      const mVal = +(-j * metersPerLine).toFixed(1)
      const isOrigin = j === 0
      elements.push(
        <Line key={`h${j}`} points={[0, y, containerWidth, y]}
          stroke={isOrigin ? '#22c55e' : '#2E75B6'}
          strokeWidth={isOrigin ? sw * 2 : sw}
          opacity={isOrigin ? 0.5 : 0.2} />
      )
      if (!isOrigin) {
        elements.push(
          <Text key={`ht${j}`} x={4 / view.scale} y={y - fs - 2 / view.scale}
            text={`${mVal}m`} fontSize={fs} fill="#2E75B6" opacity={0.7} />
        )
      }
    }
    return elements
  }

  const renderZones = () => zones.map(zone => {
    const pts = zone.points.flatMap(p => { const d = metersToDisplay(p); return [d.x, d.y] })
    const c = centroid(zone.points.map(metersToDisplay))
    const color = ZONE_COLORS[zone.type] || '#8b5cf6'
    const sw = 2 / view.scale
    return (
      <React.Fragment key={zone.id}>
        <Line points={pts} closed fill={color + '40'} stroke={color} strokeWidth={sw} />
        <Text x={c.x - 30 / view.scale} y={c.y - 8 / view.scale}
          text={zone.name} fontSize={11 / view.scale} fill={color} fontStyle="bold"
          width={60 / view.scale} align="center" />
      </React.Fragment>
    )
  })

  const renderObstacles = () => obstacles.map(obs => {
    const pts = obs.points.flatMap(p => { const d = metersToDisplay(p); return [d.x, d.y] })
    const c = centroid(obs.points.map(metersToDisplay))
    const sw = 2 / view.scale
    return (
      <React.Fragment key={obs.id}>
        <Line points={pts} closed fill="#78716c40" stroke="#78716c" strokeWidth={sw} dash={[6 / view.scale, 3 / view.scale]} />
        <Text x={c.x - 30 / view.scale} y={c.y - 8 / view.scale}
          text={obs.name} fontSize={10 / view.scale} fill="#78716c"
          width={60 / view.scale} align="center" />
      </React.Fragment>
    )
  })

  const currentDisplayPoints = currentPoints.flatMap(p => {
    const d = toDisplay(p)
    return [d.x, d.y]
  })

  return (
    <div>
      {toast && (
        <div className="fixed top-4 right-4 bg-red-600 text-white px-4 py-2 rounded-lg shadow-lg z-50 text-sm">{toast}</div>
      )}

      <h3 className="text-xl font-semibold mb-2 text-gray-800">Draw Zones & Obstacles</h3>
      <p className="text-gray-500 mb-4 text-sm">
        Click to add vertices. Click the first vertex (or press Enter) to close. Press Esc to cancel.
        Zones can overlap — newer zones overwrite shared area.
      </p>

      <div className="flex flex-wrap items-center gap-3 mb-4">
        <span className="text-sm font-medium text-gray-600">Mode:</span>
        <button onClick={() => setDrawMode('zone')}
          className={`px-4 py-1.5 rounded-lg text-sm font-medium transition ${drawMode === 'zone' ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}>
          Zone
        </button>
        <button onClick={() => setDrawMode('obstacle')}
          className={`px-4 py-1.5 rounded-lg text-sm font-medium transition ${drawMode === 'obstacle' ? 'bg-stone-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}>
          Obstacle
        </button>
        <span className="border-l border-gray-300 h-4 mx-1" />
        <button onClick={() => setView({ scale: 1, x: 0, y: 0 })}
          className="text-xs px-3 py-1 bg-gray-100 rounded hover:bg-gray-200">⊙ Reset View</button>
        <span className="text-xs text-gray-400 self-center">Ctrl+scroll to zoom · drag to pan</span>
        {currentPoints.length > 0 && (
          <button onClick={() => setCurrentPoints([])}
            className="ml-auto text-xs px-3 py-1 bg-red-50 text-red-600 border border-red-200 rounded hover:bg-red-100">
            Cancel Drawing
          </button>
        )}
      </div>

      <div ref={containerRef} className="border rounded-xl overflow-hidden shadow bg-gray-100">
        <Stage
          width={containerWidth}
          height={stageHeight || 400}
          scaleX={view.scale}
          scaleY={view.scale}
          x={view.x}
          y={view.y}
          draggable
          onClick={handleStageClick}
          onMouseMove={e => {
            const stage = e.target.getStage()
            const pos = stage.getPointerPosition()
            setMousePos(toContent(pos))
          }}
          onWheel={handleWheel}
          onDragEnd={e => setView(v => ({ ...v, x: e.target.x(), y: e.target.y() }))}
          style={{ cursor: 'crosshair' }}
        >
          <Layer>
            {image && <KImage image={image} width={containerWidth} height={stageHeight} />}
            {renderGrid()}
            {renderZones()}
            {renderObstacles()}

            {/* In-progress polygon */}
            {currentPoints.length > 0 && (
              <>
                {currentDisplayPoints.length >= 4 && (
                  <Line points={currentDisplayPoints}
                    stroke={drawMode === 'zone' ? '#3b82f6' : '#78716c'}
                    strokeWidth={2 / view.scale} dash={[6 / view.scale, 3 / view.scale]} />
                )}
                {mousePos && currentPoints.length > 0 && (() => {
                  const last = toDisplay(currentPoints[currentPoints.length - 1])
                  return (
                    <Line points={[last.x, last.y, mousePos.x, mousePos.y]}
                      stroke="#9ca3af" strokeWidth={1 / view.scale} dash={[4 / view.scale, 4 / view.scale]} />
                  )
                })()}
                {currentPoints.map((p, i) => {
                  const d = toDisplay(p)
                  return (
                    <Circle key={i} x={d.x} y={d.y}
                      radius={(i === 0 ? 8 : 5) / view.scale}
                      fill={drawMode === 'zone' ? '#3b82f6' : '#78716c'}
                      stroke="white" strokeWidth={2 / view.scale} />
                  )
                })}
              </>
            )}
          </Layer>
        </Stage>
      </div>

      {/* Lists */}
      <div className="mt-4 grid grid-cols-2 gap-4">
        <div>
          <h4 className="text-sm font-semibold text-gray-700 mb-2">Zones ({zones.length})</h4>
          {zones.length === 0
            ? <p className="text-xs text-gray-400">No zones yet.</p>
            : zones.map(z => (
              <div key={z.id} className="flex items-center justify-between py-1 px-2 bg-white rounded border mb-1 text-sm">
                <span><span className="font-medium">{z.name}</span> <span className="text-gray-400 text-xs">({z.type})</span></span>
                <button onClick={() => removeZone(z.id)} className="text-red-400 hover:text-red-600 text-xs">✕</button>
              </div>
            ))}
        </div>
        <div>
          <h4 className="text-sm font-semibold text-gray-700 mb-2">Obstacles ({obstacles.length})</h4>
          {obstacles.length === 0
            ? <p className="text-xs text-gray-400">No obstacles yet.</p>
            : obstacles.map(o => (
              <div key={o.id} className="flex items-center justify-between py-1 px-2 bg-white rounded border mb-1 text-sm">
                <span className="font-medium">{o.name}</span>
                <button onClick={() => removeObstacle(o.id)} className="text-red-400 hover:text-red-600 text-xs">✕</button>
              </div>
            ))}
        </div>
      </div>

      {/* Name modal */}
      {modal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 w-80 shadow-2xl">
            <h4 className="text-lg font-semibold mb-4">{modal.mode === 'zone' ? 'Name this Zone' : 'Name this Obstacle'}</h4>
            <div className="mb-4">
              <label className="text-sm font-medium text-gray-700 block mb-1">Name *</label>
              <input
                autoFocus type="text" value={form.name}
                onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                onKeyDown={e => e.key === 'Enter' && handleModalSave()}
                className="w-full border rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-300"
                placeholder={modal.mode === 'zone' ? 'e.g. Checkout Area' : 'e.g. Shelf A'}
              />
            </div>
            {modal.mode === 'zone' && (
              <div className="mb-4">
                <label className="text-sm font-medium text-gray-700 block mb-1">Type</label>
                <select value={form.type} onChange={e => setForm(f => ({ ...f, type: e.target.value }))}
                  className="w-full border rounded-lg px-3 py-2 text-sm">
                  <option value="entrance">Entrance</option>
                  <option value="checkout">Checkout</option>
                  <option value="aisle">Aisle</option>
                  <option value="staff_only">Staff Only</option>
                  <option value="general">General</option>
                </select>
              </div>
            )}
            <div className="flex gap-3 justify-end">
              <button onClick={() => setModal(null)} className="px-4 py-2 text-gray-600 border rounded-lg text-sm hover:bg-gray-50">Cancel</button>
              <button onClick={handleModalSave} disabled={!form.name.trim()}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm disabled:opacity-40 hover:bg-blue-700">Save</button>
            </div>
          </div>
        </div>
      )}

      <div className="mt-6 flex justify-between">
        <button onClick={() => setStep(2)} className="px-4 py-2 text-gray-600 border rounded-lg hover:bg-gray-50">← Back</button>
        <button onClick={() => setStep(4)} className="px-6 py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 transition">
          Next: Camera Registration →
        </button>
      </div>
    </div>
  )
}
