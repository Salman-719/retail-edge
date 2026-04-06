import React, { useState, useRef, useEffect, useCallback } from 'react'
import { Stage, Layer, Image as KImage, Line, Circle, Text } from 'react-konva'
import useImage from 'use-image'
import useStore from '../store'
import { getVideoFrame } from '../api'

function useContainerWidth(ref) {
  const [width, setWidth] = useState(400)
  useEffect(() => {
    if (!ref.current) return
    const ro = new ResizeObserver(e => setWidth(e[0].contentRect.width || 400))
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [])
  return width
}

function FloorPlanPanel({ origin, pixelsPerMeter, floorPlanUrl, floorPlanWidth, floorPlanHeight, zones, obstacles, correspondences, waitingForFloor, onFloorClick }) {
  const containerRef = useRef()
  const containerWidth = useContainerWidth(containerRef)
  const [image] = useImage(floorPlanUrl)
  const displayScale = floorPlanWidth > 0 ? containerWidth / floorPlanWidth : 1
  const stageHeight = floorPlanHeight * displayScale

  const metersToDisplay = (p) => ({
    x: (origin.x + p.x * pixelsPerMeter) * displayScale,
    y: (origin.y - p.y * pixelsPerMeter) * displayScale,
  })

  const handleClick = (e) => {
    if (!waitingForFloor) return
    const pos = e.target.getStage().getPointerPosition()
    const rawX = pos.x / displayScale
    const rawY = pos.y / displayScale
    const meters = {
      x: (rawX - origin.x) / pixelsPerMeter,
      y: (origin.y - rawY) / pixelsPerMeter,
    }
    onFloorClick(meters)
  }

  return (
    <div ref={containerRef} className={`border-2 rounded-xl overflow-hidden ${waitingForFloor ? 'border-blue-500 shadow-blue-200 shadow-lg' : 'border-gray-200'}`}>
      {waitingForFloor && <div className="bg-blue-500 text-white text-xs text-center py-1 font-medium">👆 Click the corresponding location on the floor plan</div>}
      <Stage width={containerWidth} height={stageHeight || 300} onClick={handleClick} style={{ cursor: waitingForFloor ? 'crosshair' : 'default' }}>
        <Layer>
          {image && <KImage image={image} width={containerWidth} height={stageHeight} />}
          {/* Grid */}
          {(() => {
            const lines = []
            const spacing = pixelsPerMeter * displayScale
            const ox = origin.x * displayScale, oy = origin.y * displayScale
            for (let x = ox % spacing; x < containerWidth; x += spacing)
              lines.push(<Line key={`v${x}`} points={[x, 0, x, stageHeight]} stroke="#2E75B6" strokeWidth={0.5} opacity={0.25} />)
            for (let y = oy % spacing; y < stageHeight; y += spacing)
              lines.push(<Line key={`h${y}`} points={[0, y, containerWidth, y]} stroke="#2E75B6" strokeWidth={0.5} opacity={0.25} />)
            return lines
          })()}
          {zones.map(z => {
            const pts = z.points.flatMap(p => { const d = metersToDisplay(p); return [d.x, d.y] })
            return <Line key={z.id} points={pts} closed fill="#3b82f620" stroke="#3b82f6" strokeWidth={1} />
          })}
          {correspondences.map((c, i) => {
            if (!c.floorM) return null
            const d = metersToDisplay(c.floorM)
            return (
              <React.Fragment key={i}>
                <Circle x={d.x} y={d.y} radius={8} fill="#f59e0b" stroke="white" strokeWidth={2} />
                <Text x={d.x + 10} y={d.y - 8} text={`${i + 1}`} fontSize={11} fill="#f59e0b" fontStyle="bold" />
              </React.Fragment>
            )
          })}
        </Layer>
      </Stage>
    </div>
  )
}

export default function Step6_Correspondence() {
  const { cameras, zones, floorPlanUrl, floorPlanWidth, floorPlanHeight, origin, pixelsPerMeter, obstacles, updateCamera, setStep } = useStore()
  const [selectedCam, setSelectedCam] = useState(cameras[0]?.id || null)

  const cam = cameras.find(c => c.id === selectedCam)
  const correspondences = cam?.correspondences || []

  const [frameUrl, setFrameUrl] = useState(null)
  const [timestamp, setTimestamp] = useState(0)
  const [loadingFrame, setLoadingFrame] = useState(false)
  const [waitingForFloor, setWaitingForFloor] = useState(false)
  const [pendingCamPoint, setPendingCamPoint] = useState(null)
  const imgRef = useRef()

  const fetchFrame = useCallback(async (t) => {
    if (!cam) return
    setLoadingFrame(true)
    try {
      const url = await getVideoFrame(cam.id, t)
      setFrameUrl(url)
    } catch (e) {
      console.error(e)
    } finally {
      setLoadingFrame(false)
    }
  }, [cam?.id])

  useEffect(() => {
    if (cam?.id) fetchFrame(0)
  }, [cam?.id])

  const handleImgClick = (e) => {
    if (waitingForFloor) return
    if (correspondences.length >= 8) return
    const rect = e.target.getBoundingClientRect()
    const x = (e.clientX - rect.left) * (cam.videoWidth / rect.width)
    const y = (e.clientY - rect.top) * (cam.videoHeight / rect.height)
    setPendingCamPoint({ x, y })
    setWaitingForFloor(true)
  }

  const handleFloorClick = (meters) => {
    if (!pendingCamPoint) return
    const newPair = { camPx: pendingCamPoint, floorM: meters }
    updateCamera(cam.id, { correspondences: [...correspondences, newPair] })
    setPendingCamPoint(null)
    setWaitingForFloor(false)
  }

  const removeLast = () => {
    if (correspondences.length === 0) return
    updateCamera(cam.id, { correspondences: correspondences.slice(0, -1) })
    setWaitingForFloor(false)
    setPendingCamPoint(null)
  }

  const clearAll = () => {
    updateCamera(cam.id, { correspondences: [] })
    setWaitingForFloor(false)
    setPendingCamPoint(null)
  }

  const allReady = cameras.every(c => (c.correspondences || []).length >= 4)

  return (
    <div>
      <h3 className="text-xl font-semibold mb-2 text-gray-800">Point Correspondence</h3>
      <p className="text-gray-500 mb-4 text-sm">Select 4–8 matching point pairs between the camera frame and floor plan.</p>

      {cameras.length > 1 && (
        <div className="flex gap-2 mb-4">
          {cameras.map(c => (
            <button key={c.id} onClick={() => { setSelectedCam(c.id); setWaitingForFloor(false); setPendingCamPoint(null) }}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium ${selectedCam === c.id ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}>
              {c.name} {(c.correspondences || []).length >= 4 ? '✓' : `(${(c.correspondences || []).length}/4)`}
            </button>
          ))}
        </div>
      )}

      {cam && (
        <>
          <div className="mb-3 flex items-center gap-3">
            <label className="text-sm text-gray-600">Seek to:</label>
            <input type="range" min="0" max={cam.videoDuration || 100} step="0.5" value={timestamp}
              onChange={e => { setTimestamp(parseFloat(e.target.value)); fetchFrame(parseFloat(e.target.value)) }}
              className="w-48" />
            <span className="text-sm text-gray-500">{timestamp.toFixed(1)}s</span>
            <button onClick={() => fetchFrame(timestamp)} className="text-xs px-2 py-1 bg-gray-100 rounded hover:bg-gray-200">Refresh</button>
            <div className="ml-auto flex gap-2">
              <button onClick={removeLast} disabled={correspondences.length === 0} className="text-xs px-3 py-1 border rounded hover:bg-gray-50 disabled:opacity-40">Remove Last</button>
              <button onClick={clearAll} disabled={correspondences.length === 0} className="text-xs px-3 py-1 border border-red-200 text-red-600 rounded hover:bg-red-50 disabled:opacity-40">Clear All</button>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            {/* Camera frame */}
            <div>
              <p className="text-xs font-medium text-gray-500 mb-1">Camera Frame — {waitingForFloor ? 'Waiting for floor click...' : 'Click to add point'}</p>
              <div className="relative border rounded-xl overflow-hidden" style={{ cursor: waitingForFloor ? 'not-allowed' : correspondences.length < 8 ? 'crosshair' : 'default' }}>
                {loadingFrame && <div className="absolute inset-0 bg-white bg-opacity-70 flex items-center justify-center z-10 text-sm text-blue-600">Loading...</div>}
                {frameUrl && (
                  <img ref={imgRef} src={frameUrl} alt="Camera frame" className="w-full block" onClick={handleImgClick} draggable={false} />
                )}
                {/* Overlay markers */}
                {frameUrl && imgRef.current && correspondences.map((c, i) => {
                  if (!c.camPx) return null
                  const rect = imgRef.current.getBoundingClientRect()
                  const scaleX = rect.width / cam.videoWidth
                  const scaleY = rect.height / cam.videoHeight
                  return (
                    <div key={i} className="absolute w-6 h-6 -ml-3 -mt-3 rounded-full bg-amber-400 border-2 border-white flex items-center justify-center text-xs font-bold text-white pointer-events-none"
                      style={{ left: c.camPx.x * scaleX, top: c.camPx.y * scaleY }}>
                      {i + 1}
                    </div>
                  )
                })}
              </div>
            </div>

            {/* Floor plan */}
            <div>
              <p className="text-xs font-medium text-gray-500 mb-1">Floor Plan — {waitingForFloor ? '👆 Click corresponding point' : 'Waiting for camera click'}</p>
              <FloorPlanPanel
                origin={origin} pixelsPerMeter={pixelsPerMeter}
                floorPlanUrl={floorPlanUrl} floorPlanWidth={floorPlanWidth} floorPlanHeight={floorPlanHeight}
                zones={zones} obstacles={[]}
                correspondences={correspondences}
                waitingForFloor={waitingForFloor}
                onFloorClick={handleFloorClick}
              />
            </div>
          </div>

          {/* Correspondence list */}
          {correspondences.length > 0 && (
            <div className="mt-4">
              <h4 className="text-sm font-semibold text-gray-700 mb-2">Pairs ({correspondences.length}/8, min 4)</h4>
              <div className="grid grid-cols-2 gap-1">
                {correspondences.map((c, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs bg-white rounded border px-2 py-1">
                    <span className="w-5 h-5 bg-amber-400 rounded-full text-white flex items-center justify-center font-bold shrink-0">{i + 1}</span>
                    <span className="text-gray-500">Cam: ({c.camPx.x.toFixed(0)}, {c.camPx.y.toFixed(0)})</span>
                    <span className="text-gray-500">Floor: ({c.floorM.x.toFixed(2)}m, {c.floorM.y.toFixed(2)}m)</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      <div className="mt-6 flex justify-between">
        <button onClick={() => setStep(5)} className="px-4 py-2 text-gray-600 border rounded-lg hover:bg-gray-50">← Back</button>
        <button onClick={() => setStep(7)} disabled={!allReady} className="px-6 py-2 bg-blue-600 text-white rounded-lg font-medium disabled:opacity-40 hover:bg-blue-700 transition">
          Next: Compute Homography →
        </button>
      </div>
    </div>
  )
}
