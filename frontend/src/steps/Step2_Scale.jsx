import React, { useState, useRef, useEffect } from 'react'
import { Stage, Layer, Image as KImage, Circle, Line, Text, Arrow } from 'react-konva'
import useImage from 'use-image'
import useStore from '../store'

function useContainerWidth(ref) {
  const [width, setWidth] = useState(800)
  useEffect(() => {
    if (!ref.current) return
    const ro = new ResizeObserver(entries => {
      setWidth(entries[0].contentRect.width || 800)
    })
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [])
  return width
}

export default function Step2_Scale() {
  const { floorPlanUrl, floorPlanWidth, floorPlanHeight, origin, scalePoints, realWorldDistance, pixelsPerMeter, setScale, setStep } = useStore()
  const containerRef = useRef()
  const containerWidth = useContainerWidth(containerRef)
  const [image] = useImage(floorPlanUrl)

  const displayScale = floorPlanWidth > 0 ? containerWidth / floorPlanWidth : 1
  const stageHeight = floorPlanHeight * displayScale

  // Zoom / pan state
  const [view, setView] = useState({ scale: 1, x: 0, y: 0 })

  const [mode, setMode] = useState('origin')
  const [localOrigin, setLocalOrigin] = useState(origin)
  const [localP1, setLocalP1] = useState(scalePoints?.p1 || null)
  const [localP2, setLocalP2] = useState(scalePoints?.p2 || null)
  const [distance, setDistance] = useState(realWorldDistance?.toString() || '')
  const [mousePos, setMousePos] = useState(null) // content display pixels

  // Container pixel → content display pixel
  const toContent = (containerPos) => ({
    x: (containerPos.x - view.x) / view.scale,
    y: (containerPos.y - view.y) / view.scale,
  })

  // Content display pixel → floor plan raw pixel
  const toRaw = (contentPos) => ({ x: contentPos.x / displayScale, y: contentPos.y / displayScale })

  // Floor plan raw pixel → content display pixel
  const toDisplay = (p) => ({ x: p.x * displayScale, y: p.y * displayScale })

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
    const raw = toRaw(contentPos)
    if (mode === 'origin') {
      setLocalOrigin(raw)
      setMode('scale')
    } else if (mode === 'scale') {
      if (!localP1) setLocalP1(raw)
      else if (!localP2) setLocalP2(raw)
    }
  }

  const handleMouseMove = (e) => {
    const stage = e.target.getStage()
    const pos = stage.getPointerPosition()
    setMousePos(toContent(pos))
  }

  const pixDist = localP1 && localP2
    ? Math.sqrt((localP2.x - localP1.x) ** 2 + (localP2.y - localP1.y) ** 2)
    : null
  const ppm = pixDist && parseFloat(distance) > 0 ? pixDist / parseFloat(distance) : null
  const canProceed = localOrigin && ppm

  const handleNext = () => {
    setScale({
      origin: localOrigin,
      scalePoints: { p1: localP1, p2: localP2 },
      realWorldDistance: parseFloat(distance),
      pixelsPerMeter: ppm,
    })
    setStep(3)
  }

  const resetView = () => setView({ scale: 1, x: 0, y: 0 })

  // ── Dynamic grid with meter labels ─────────────────────────────────────────
  const renderGrid = () => {
    if (!localOrigin || !ppm) return null

    // Adaptive spacing: choose meter interval so lines are 40–120px apart on screen
    const effectivePPM = ppm * displayScale * view.scale
    let metersPerLine
    if (effectivePPM >= 200) metersPerLine = 0.5
    else if (effectivePPM >= 100) metersPerLine = 1
    else if (effectivePPM >= 50) metersPerLine = 2
    else if (effectivePPM >= 20) metersPerLine = 5
    else metersPerLine = 10

    const spacingPx = ppm * displayScale * metersPerLine // in content px
    const ox = localOrigin.x * displayScale
    const oy = localOrigin.y * displayScale
    const fs = 9 / view.scale       // font size stays ~9px on screen
    const sw = 0.5 / view.scale     // stroke width stays ~0.5px on screen

    const elements = []

    // Vertical lines (fixed X)
    const xMin = Math.floor((-ox) / spacingPx) - 1
    const xMax = Math.ceil((containerWidth - ox) / spacingPx) + 1
    for (let i = xMin; i <= xMax; i++) {
      const x = ox + i * spacingPx
      const mVal = +(i * metersPerLine).toFixed(1)
      const isOrigin = i === 0
      elements.push(
        <Line key={`v${i}`}
          points={[x, 0, x, stageHeight]}
          stroke={isOrigin ? '#ef4444' : '#2E75B6'}
          strokeWidth={isOrigin ? sw * 2 : sw}
          opacity={isOrigin ? 0.6 : 0.35}
        />
      )
      if (!isOrigin) {
        elements.push(
          <Text key={`vt${i}`}
            x={x + 2 / view.scale} y={4 / view.scale}
            text={`${mVal}m`} fontSize={fs} fill="#2E75B6" opacity={0.8}
          />
        )
      }
    }

    // Horizontal lines (fixed Y)
    const yMin = Math.floor((-oy) / spacingPx) - 1
    const yMax = Math.ceil((stageHeight - oy) / spacingPx) + 1
    for (let j = yMin; j <= yMax; j++) {
      const y = oy + j * spacingPx
      const mVal = +(- j * metersPerLine).toFixed(1)
      const isOrigin = j === 0
      elements.push(
        <Line key={`h${j}`}
          points={[0, y, containerWidth, y]}
          stroke={isOrigin ? '#22c55e' : '#2E75B6'}
          strokeWidth={isOrigin ? sw * 2 : sw}
          opacity={isOrigin ? 0.6 : 0.35}
        />
      )
      if (!isOrigin) {
        elements.push(
          <Text key={`ht${j}`}
            x={4 / view.scale} y={y - fs - 2 / view.scale}
            text={`${mVal}m`} fontSize={fs} fill="#2E75B6" opacity={0.8}
          />
        )
      }
    }

    return elements
  }

  return (
    <div>
      <h3 className="text-xl font-semibold mb-2 text-gray-800">Set Scale & Origin</h3>
      <p className="text-gray-500 mb-4 text-sm">
        {mode === 'origin' ? '① Click on the floor plan to set the coordinate origin (0,0).' :
         !localP1 ? '② Click the start of a known-length line.' :
         !localP2 ? '② Click the end of the known-length line.' :
         '✓ Both scale points set. Enter the real-world distance below.'}
      </p>

      <div className="flex flex-wrap gap-2 mb-4 items-center">
        <button onClick={() => { setLocalOrigin(null); setMode('origin') }}
          className="text-xs px-3 py-1 bg-gray-100 rounded hover:bg-gray-200">Reset Origin</button>
        <button onClick={() => { setLocalP1(null); setLocalP2(null); setMode(localOrigin ? 'scale' : 'origin') }}
          className="text-xs px-3 py-1 bg-gray-100 rounded hover:bg-gray-200">Reset Scale Points</button>
        <span className="border-l border-gray-300 h-4 mx-1" />
        <button onClick={resetView}
          className="text-xs px-3 py-1 bg-gray-100 rounded hover:bg-gray-200" title="Reset zoom">⊙ Reset View</button>
        {view.scale !== 1 && (
          <span className="text-xs text-gray-400">Zoom {(view.scale * 100).toFixed(0)}% · Ctrl+scroll to zoom · drag to pan</span>
        )}
        {view.scale === 1 && (
          <span className="text-xs text-gray-400">Ctrl+scroll to zoom · drag to pan</span>
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
          onMouseMove={handleMouseMove}
          onWheel={handleWheel}
          onDragEnd={e => setView(v => ({ ...v, x: e.target.x(), y: e.target.y() }))}
          style={{ cursor: 'crosshair' }}
        >
          <Layer>
            {image && <KImage image={image} width={containerWidth} height={stageHeight} />}

            {renderGrid()}

            {/* Origin marker */}
            {localOrigin && (() => {
              const d = toDisplay(localOrigin)
              const s = view.scale
              return (
                <>
                  <Circle x={d.x} y={d.y} radius={8 / s} fill="#ef4444" stroke="white" strokeWidth={2 / s} />
                  <Arrow points={[d.x, d.y, d.x + 40 / s, d.y]} fill="#ef4444" stroke="#ef4444" strokeWidth={2 / s} />
                  <Arrow points={[d.x, d.y, d.x, d.y - 40 / s]} fill="#22c55e" stroke="#22c55e" strokeWidth={2 / s} />
                  <Text x={d.x + 44 / s} y={d.y - 8 / s} text="X" fill="#ef4444" fontSize={12 / s} fontStyle="bold" />
                  <Text x={d.x - 14 / s} y={d.y - 52 / s} text="Y" fill="#22c55e" fontSize={12 / s} fontStyle="bold" />
                  <Text x={d.x + 10 / s} y={d.y + 10 / s} text="origin (0,0)" fill="#ef4444" fontSize={10 / s} />
                </>
              )
            })()}

            {/* Scale measurement line */}
            {localP1 && (() => {
              const d1 = toDisplay(localP1)
              const d2 = localP2
                ? toDisplay(localP2)
                : (mousePos && mode === 'scale' ? mousePos : null)
              const s = view.scale
              return (
                <>
                  <Circle x={d1.x} y={d1.y} radius={6 / s} fill="#f59e0b" stroke="white" strokeWidth={2 / s} />
                  {d2 && (
                    <Line points={[d1.x, d1.y, d2.x, d2.y]}
                      stroke="#f59e0b" strokeWidth={2 / s} dash={[6 / s, 3 / s]} />
                  )}
                  {localP2 && (() => {
                    const d2d = toDisplay(localP2)
                    return (
                      <>
                        <Circle x={d2d.x} y={d2d.y} radius={6 / s} fill="#f59e0b" stroke="white" strokeWidth={2 / s} />
                        <Text
                          x={(d1.x + d2d.x) / 2} y={(d1.y + d2d.y) / 2 - 16 / s}
                          text={ppm ? `${parseFloat(distance) || '?'}m = ${Math.round(pixDist)}px` : `${Math.round(pixDist || 0)}px`}
                          fill="#f59e0b" fontSize={11 / s} fontStyle="bold"
                        />
                      </>
                    )
                  })()}
                </>
              )
            })()}
          </Layer>
        </Stage>
      </div>

      {localP1 && localP2 && (
        <div className="mt-4 flex items-center gap-4">
          <label className="text-sm font-medium text-gray-700">Real-world distance (meters):</label>
          <input
            type="number" min="0.01" step="0.1" value={distance}
            onChange={e => setDistance(e.target.value)}
            className="w-32 border rounded-lg px-3 py-1.5 text-sm focus:ring-2 focus:ring-blue-300"
            placeholder="e.g. 5.0"
          />
          {ppm && <span className="text-sm text-green-700 font-medium">Scale: {ppm.toFixed(1)} px/m</span>}
        </div>
      )}

      <div className="mt-6 flex justify-between">
        <button onClick={() => setStep(1)} className="px-4 py-2 text-gray-600 border rounded-lg hover:bg-gray-50">← Back</button>
        <button onClick={handleNext} disabled={!canProceed}
          className="px-6 py-2 bg-blue-600 text-white rounded-lg font-medium disabled:opacity-40 hover:bg-blue-700 transition">
          Next: Draw Zones →
        </button>
      </div>
    </div>
  )
}
