import React, { useState, useRef, useEffect } from 'react'
import { Stage, Layer, Image as KImage, Line, Circle, Text } from 'react-konva'
import useImage from 'use-image'
import useStore from '../store'
import { createCamera } from '../api'

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

export default function Step4_Cameras() {
  const { floorPlanUrl, floorPlanWidth, floorPlanHeight, origin, pixelsPerMeter, zones, cameras, addCamera, removeCamera, setStep } = useStore()
  const containerRef = useRef()
  const containerWidth = useContainerWidth(containerRef)
  const [image] = useImage(floorPlanUrl)

  const displayScale = floorPlanWidth > 0 ? containerWidth / floorPlanWidth : 1
  const stageHeight = floorPlanHeight * displayScale

  // Zoom / pan
  const [view, setView] = useState({ scale: 1, x: 0, y: 0 })

  const [modal, setModal] = useState(null)
  const [form, setForm] = useState({ name: '', heightMeters: '' })

  const toContent = (containerPos) => ({
    x: (containerPos.x - view.x) / view.scale,
    y: (containerPos.y - view.y) / view.scale,
  })
  const metersToDisplay = (p) => ({
    x: (origin.x + p.x * pixelsPerMeter) * displayScale,
    y: (origin.y - p.y * pixelsPerMeter) * displayScale,
  })
  const rawToMeters = (raw) => ({
    x: (raw.x - origin.x) / pixelsPerMeter,
    y: (origin.y - raw.y) / pixelsPerMeter,
  })

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
    const stage = e.target.getStage()
    const pos = stage.getPointerPosition()
    const contentPos = toContent(pos)
    const raw = { x: contentPos.x / displayScale, y: contentPos.y / displayScale }
    const meters = rawToMeters(raw)
    setModal({ positionM: meters })
    setForm({ name: `Camera ${cameras.length + 1}`, heightMeters: '2.8' })
  }

  const handleSave = async () => {
    if (!form.name.trim() || !form.heightMeters) return
    const cam = {
      id: `cam_${Date.now()}`,
      name: form.name.trim(),
      position: modal.positionM,
      heightMeters: parseFloat(form.heightMeters),
    }
    addCamera(cam)
    setModal(null)
    // Persist camera to DB so video upload works in Step 5
    try { await createCamera(cam) } catch (_) { /* ok if store not yet set */ }
  }

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

  return (
    <div>
      <h3 className="text-xl font-semibold mb-2 text-gray-800">Camera Registration</h3>
      <p className="text-gray-500 mb-4 text-sm">
        Click on the floor plan to place a camera. Fill in its name and height.
      </p>

      <div className="flex flex-wrap gap-2 mb-3 items-center">
        <button onClick={() => setView({ scale: 1, x: 0, y: 0 })}
          className="text-xs px-3 py-1 bg-gray-100 rounded hover:bg-gray-200">⊙ Reset View</button>
        <span className="text-xs text-gray-400">Ctrl+scroll to zoom · drag to pan</span>
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
          onWheel={handleWheel}
          onDragEnd={e => setView(v => ({ ...v, x: e.target.x(), y: e.target.y() }))}
          style={{ cursor: 'crosshair' }}
        >
          <Layer>
            {image && <KImage image={image} width={containerWidth} height={stageHeight} />}
            {renderGrid()}

            {/* Zone outlines */}
            {zones.map(zone => {
              const pts = zone.points.flatMap(p => {
                const d = metersToDisplay(p)
                return [d.x, d.y]
              })
              return (
                <Line key={zone.id} points={pts} closed
                  fill="#3b82f620" stroke="#3b82f6" strokeWidth={1 / view.scale} />
              )
            })}

            {/* Camera pins */}
            {cameras.map(cam => {
              const d = metersToDisplay(cam.position)
              const s = view.scale
              return (
                <React.Fragment key={cam.id}>
                  <Circle x={d.x} y={d.y} radius={12 / s} fill="#f59e0b" stroke="white" strokeWidth={2 / s} />
                  <Text x={d.x - 4 / s} y={d.y - 5 / s} text="📷" fontSize={10 / s} />
                  <Text x={d.x + 16 / s} y={d.y - 8 / s}
                    text={cam.name} fontSize={11 / s} fill="#1e293b" fontStyle="bold" />
                </React.Fragment>
              )
            })}
          </Layer>
        </Stage>
      </div>

      <div className="mt-4">
        <h4 className="text-sm font-semibold text-gray-700 mb-2">Registered Cameras ({cameras.length})</h4>
        {cameras.length === 0
          ? <p className="text-sm text-gray-400">No cameras yet. Click on the floor plan to add one.</p>
          : cameras.map(c => (
            <div key={c.id} className="flex items-center justify-between py-2 px-3 bg-white rounded-lg border mb-1 text-sm">
              <span>
                <span className="font-medium">{c.name}</span>
                <span className="text-gray-400 ml-2">
                  ({c.position.x.toFixed(1)}m, {c.position.y.toFixed(1)}m) · {c.heightMeters}m high
                </span>
              </span>
              <button onClick={() => removeCamera(c.id)} className="text-red-400 hover:text-red-600 text-xs">✕</button>
            </div>
          ))
        }
      </div>

      {modal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 w-80 shadow-2xl">
            <h4 className="text-lg font-semibold mb-4">Add Camera</h4>
            <p className="text-xs text-gray-500 mb-4">
              Position: ({modal.positionM.x.toFixed(2)}m, {modal.positionM.y.toFixed(2)}m)
            </p>
            <div className="mb-3">
              <label className="text-sm font-medium text-gray-700 block mb-1">Name *</label>
              <input autoFocus type="text" value={form.name}
                onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                className="w-full border rounded-lg px-3 py-2 text-sm" />
            </div>
            <div className="mb-4">
              <label className="text-sm font-medium text-gray-700 block mb-1">Height (meters) *</label>
              <input type="number" min="0.5" step="0.1" value={form.heightMeters}
                onChange={e => setForm(f => ({ ...f, heightMeters: e.target.value }))}
                className="w-full border rounded-lg px-3 py-2 text-sm" />
            </div>
            <div className="flex gap-3 justify-end">
              <button onClick={() => setModal(null)} className="px-4 py-2 text-gray-600 border rounded-lg text-sm">Cancel</button>
              <button onClick={handleSave} disabled={!form.name.trim() || !form.heightMeters}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm disabled:opacity-40">Add Camera</button>
            </div>
          </div>
        </div>
      )}

      <div className="mt-6 flex justify-between">
        <button onClick={() => setStep(3)} className="px-4 py-2 text-gray-600 border rounded-lg hover:bg-gray-50">← Back</button>
        <button onClick={() => setStep(5)} disabled={cameras.length === 0}
          className="px-6 py-2 bg-blue-600 text-white rounded-lg font-medium disabled:opacity-40 hover:bg-blue-700 transition">
          Next: Upload Videos →
        </button>
      </div>
    </div>
  )
}
