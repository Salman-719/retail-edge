import React, { useState, useEffect, useRef, useCallback } from 'react'
import { Stage, Layer, Image as KImage, Circle, Line } from 'react-konva'
import useImage from 'use-image'
import useStore from '../store'

// ── Constants ────────────────────────────────────────────────────────────────

const TRACK_COLORS = [
  '#ef4444', '#3b82f6', '#22c55e', '#f59e0b',
  '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16',
  '#f97316', '#14b8a6',
]

// Direct backend URL for MJPEG stream — bypasses Vite proxy buffering.
const BACKEND = 'http://localhost:8000'

// ── Tiny helpers ──────────────────────────────────────────────────────────────

function useContainerWidth(ref) {
  const [width, setWidth] = useState(600)
  useEffect(() => {
    if (!ref.current) return
    const ro = new ResizeObserver(e => setWidth(e[0].contentRect.width || 600))
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [])
  return width
}

function ProgressBar({ value }) {
  return (
    <div className="w-full bg-gray-200 rounded-full h-3 overflow-hidden">
      <div className="h-full bg-blue-500 transition-all duration-300 rounded-full"
        style={{ width: `${Math.round(value * 100)}%` }} />
    </div>
  )
}

// ── Zone occupancy table ──────────────────────────────────────────────────────

function ZoneTable({ zones, zoneOccupancy, trajectoryMeters, effectiveFps }) {
  const totalInZones = Object.values(zoneOccupancy || {}).reduce((s, z) => s + (z.seconds || 0), 0)
  const outsideSec = Math.max(
    0,
    trajectoryMeters ? (trajectoryMeters.length / Math.max(effectiveFps || 8, 1)) - totalInZones : 0
  )
  const grandTotal = totalInZones + outsideSec

  const barColor = (pct) => pct < 20 ? '#22c55e' : pct < 50 ? '#f59e0b' : '#ef4444'

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="bg-gray-100 text-gray-600 text-xs uppercase tracking-wide">
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
              <tr key={z.id} className="border-t border-gray-100 hover:bg-gray-50">
                <td className="px-3 py-2 font-medium text-gray-800">{z.name}</td>
                <td className="px-3 py-2 text-gray-400 text-xs">{z.type}</td>
                <td className="px-3 py-2 text-right font-mono">{occ.seconds.toFixed(1)}</td>
                <td className="px-3 py-2">
                  <div className="h-2 bg-gray-200 rounded-full overflow-hidden w-full">
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
          <tr className="border-t-2 border-gray-200 bg-gray-50 text-gray-500">
            <td className="px-3 py-2 italic">Outside zones</td>
            <td className="px-3 py-2 text-xs">—</td>
            <td className="px-3 py-2 text-right font-mono">{outsideSec.toFixed(1)}</td>
            <td className="px-3 py-2">
              <div className="h-2 bg-gray-200 rounded-full overflow-hidden w-full">
                <div className="h-full rounded-full bg-gray-400"
                  style={{ width: grandTotal > 0 ? `${(outsideSec / grandTotal) * 100}%` : '0%' }} />
              </div>
            </td>
            <td className="px-3 py-2 text-right font-mono">
              {grandTotal > 0 ? ((outsideSec / grandTotal) * 100).toFixed(1) : 0}%
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}

// ── Trajectory view (Konva, Ctrl+scroll to zoom) ──────────────────────────────

function TrajectoryView({ floorPlanUrl, floorPlanWidth, floorPlanHeight, origin, pixelsPerMeter, zones, trajectoryMeters }) {
  const containerRef = useRef()
  const containerWidth = useContainerWidth(containerRef)
  const [image] = useImage(floorPlanUrl)
  const displayScale = floorPlanWidth > 0 ? containerWidth / floorPlanWidth : 1
  const stageHeight = floorPlanHeight * displayScale

  const [view, setView] = useState({ scale: 1, x: 0, y: 0 })

  const toDisplay = (mX, mY) => ({
    x: (origin.x + mX * pixelsPerMeter) * displayScale,
    y: (origin.y - mY * pixelsPerMeter) * displayScale,
  })

  const handleWheel = (e) => {
    if (!e.evt.ctrlKey) return   // allow normal scroll
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

  return (
    <div>
      <div className="flex gap-2 mb-2 items-center">
        <button onClick={() => setView({ scale: 1, x: 0, y: 0 })}
          className="text-xs px-2 py-1 bg-gray-100 rounded hover:bg-gray-200">⊙ Reset</button>
        <span className="text-xs text-gray-400">
          Ctrl+scroll to zoom · drag to pan
          {view.scale !== 1 && ` · ${(view.scale * 100).toFixed(0)}%`}
        </span>
      </div>
      <div ref={containerRef} className="border rounded-xl overflow-hidden shadow bg-gray-100">
        <Stage
          width={containerWidth} height={stageHeight || 400}
          scaleX={view.scale} scaleY={view.scale} x={view.x} y={view.y}
          draggable
          onWheel={handleWheel}
          onDragEnd={e => setView(v => ({ ...v, x: e.target.x(), y: e.target.y() }))}
        >
          <Layer>
            {image && <KImage image={image} width={containerWidth} height={stageHeight} />}
            {(zones || []).map(z => {
              const pts = z.points.flatMap(p => {
                const d = toDisplay(p.x, p.y)
                return [d.x, d.y]
              })
              return (
                <Line key={z.id} points={pts} closed
                  stroke="#3b82f6" strokeWidth={1.5 / view.scale} opacity={0.7} />
              )
            })}
            {(trajectoryMeters || []).map((pt, i) => {
              const d = toDisplay(pt.x, pt.y)
              return (
                <Circle key={i} x={d.x} y={d.y}
                  radius={3 / view.scale}
                  fill={TRACK_COLORS[pt.trackId % TRACK_COLORS.length]}
                  opacity={0.75} />
              )
            })}
          </Layer>
        </Stage>
      </div>
    </div>
  )
}

// ── Heatmap view (CSS zoom, Ctrl+scroll only) ─────────────────────────────────

function HeatmapView({ heatmapUrl }) {
  const [ts, setTs] = useState(Date.now())
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const isPanning = useRef(false)
  const lastMouse = useRef({ x: 0, y: 0 })
  const containerRef = useRef()

  useEffect(() => { setTs(Date.now()) }, [heatmapUrl])

  // Attach wheel listener as non-passive so we can conditionally preventDefault
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const onWheel = (e) => {
      if (!e.ctrlKey) return   // let normal scroll pass through
      e.preventDefault()
      const scaleBy = 1.12
      setZoom(z => Math.min(6, Math.max(0.3, e.deltaY < 0 ? z * scaleBy : z / scaleBy)))
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  // Pan via mouse drag
  useEffect(() => {
    const onUp = () => { isPanning.current = false }
    window.addEventListener('mouseup', onUp)
    return () => window.removeEventListener('mouseup', onUp)
  }, [])

  const handleMouseDown = (e) => {
    isPanning.current = true
    lastMouse.current = { x: e.clientX, y: e.clientY }
  }

  const handleMouseMove = (e) => {
    if (!isPanning.current) return
    const dx = e.clientX - lastMouse.current.x
    const dy = e.clientY - lastMouse.current.y
    setPan(p => ({ x: p.x + dx, y: p.y + dy }))
    lastMouse.current = { x: e.clientX, y: e.clientY }
  }

  const resetView = () => { setZoom(1); setPan({ x: 0, y: 0 }) }

  if (!heatmapUrl) {
    return (
      <div className="border rounded-xl p-12 text-center text-gray-400 bg-gray-50" style={{ maxWidth: 680 }}>
        Heatmap not yet generated.
      </div>
    )
  }

  return (
    <div style={{ maxWidth: 720 }}>
      <div className="flex gap-2 mb-2 items-center">
        <button onClick={resetView}
          className="text-xs px-2 py-1 bg-gray-100 rounded hover:bg-gray-200">⊙ Reset</button>
        <span className="text-xs text-gray-400">
          Ctrl+scroll to zoom · drag to pan
          {zoom !== 1 && ` · ${(zoom * 100).toFixed(0)}%`}
        </span>
      </div>

      {/* Clipping wrapper — fixed height so it doesn't dominate the page */}
      <div
        ref={containerRef}
        className="border rounded-xl shadow bg-gray-50"
        style={{
          overflow: 'hidden',
          cursor: isPanning.current ? 'grabbing' : 'grab',
          userSelect: 'none',
          maxHeight: 480,
        }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
      >
        {/* Zoom + pan transform applied to image wrapper */}
        <div
          style={{
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
            transformOrigin: '50% 0%',
            transition: 'none',
            lineHeight: 0,
          }}
        >
          <img
            src={`${BACKEND}${heatmapUrl}?t=${ts}`}
            alt="Zone occupancy heatmap"
            draggable={false}
            style={{ width: '100%', display: 'block' }}
          />
        </div>
      </div>
    </div>
  )
}

function HeatmapLegend() {
  const stops = [
    { label: '0%',   color: '#D7EDFF' },
    { label: '25%',  color: '#64C3EB' },
    { label: '50%',  color: '#FFEB78' },
    { label: '75%',  color: '#FFA54B' },
    { label: '100%', color: '#F5645F' },
  ]
  return (
    <div className="flex items-center gap-3 text-xs text-gray-500 mt-2 flex-wrap">
      <span className="font-medium text-gray-600">Zone occupancy:</span>
      {stops.map(s => (
        <span key={s.label} className="flex items-center gap-1">
          <span className="w-3 h-3 rounded-sm inline-block border border-gray-300"
            style={{ background: s.color }} />
          {s.label}
        </span>
      ))}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function Step9_TestMode() {
  const {
    cameras, zones,
    floorPlanUrl, floorPlanWidth, floorPlanHeight,
    origin, pixelsPerMeter,
    updateCamera, setStep,
  } = useStore()

  const [selectedCamId, setSelectedCamId] = useState(cameras[0]?.id || null)
  const [modelSize, setModelSize] = useState('n')

  const [isTracking, setIsTracking] = useState(false)
  const [trackingDone, setTrackingDone] = useState(false)
  const [progress, setProgress] = useState(null)
  const [liveOccupancy, setLiveOccupancy] = useState({})
  const [error, setError] = useState(null)
  const [results, setResults] = useState(null)
  const [viewMode, setViewMode] = useState('stream')
  const [streamKey, setStreamKey] = useState(0)

  const cam = cameras.find(c => c.id === selectedCamId)

  // ── Polling ───────────────────────────────────────────────────────────────
  const pollRef = useRef(null)

  const stopPolling = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }, [])

  useEffect(() => {
    if (!isTracking || !cam) return
    pollRef.current = setInterval(async () => {
      try {
        const r = await fetch(`/api/tracking/progress/${cam.id}`)
        if (!r.ok) return
        const data = await r.json()
        setProgress(data)
        setLiveOccupancy(data.zoneOccupancy || {})

        if (data.status === 'done') {
          stopPolling()
          setIsTracking(false)
          setTrackingDone(true)
          setResults(data)
          setViewMode('heatmap')
          updateCamera(cam.id, {
            trackingResults: {
              trajectoryMeters: data.trajectoryMeters,
              trajectoryPixels: data.trajectoryPixels,
              zoneOccupancy: data.zoneOccupancy,
              heatmapUrl: data.heatmapUrl,
            },
          })
        }
        if (data.status === 'error') {
          stopPolling()
          setIsTracking(false)
          setError(data.error || 'Unknown tracking error')
        }
      } catch (_) { /* network hiccup — keep polling */ }
    }, 800)
    return stopPolling
  }, [isTracking, cam?.id])

  // ── Start tracking ────────────────────────────────────────────────────────
  const handleStart = async () => {
    if (!cam?.homographyMatrix) return
    stopPolling()
    setError(null)
    setProgress(null)
    setResults(null)
    setLiveOccupancy({})
    setTrackingDone(false)
    setViewMode('stream')

    try {
      const r = await fetch(`/api/tracking/start/${cam.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          homography_matrix: cam.homographyMatrix,
          zones,
          model_size: modelSize,
          pixels_per_meter: pixelsPerMeter,
          origin_px: origin,
        }),
      })
      if (!r.ok) throw new Error(await r.text())
      setIsTracking(true)
      setStreamKey(k => k + 1)
    } catch (e) {
      setError(e.message)
    }
  }

  // ── Exports ───────────────────────────────────────────────────────────────
  const handleDownloadHeatmap = () => {
    if (!results?.heatmapUrl) return
    const a = document.createElement('a')
    a.href = `${BACKEND}${results.heatmapUrl}`
    a.download = `heatmap_${cam.id}.png`
    a.click()
  }

  const handleExportCSV = () => {
    const traj = results?.trajectoryMeters
    if (!traj?.length) return
    const lines = ['frameIdx,x,y,trackId',
      ...traj.map(t => `${t.frameIdx},${t.x.toFixed(3)},${t.y.toFixed(3)},${t.trackId}`)]
    const blob = new Blob([lines.join('\n')], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = `trajectory_${cam.id}.csv`; a.click()
    URL.revokeObjectURL(url)
  }

  // ── Render ────────────────────────────────────────────────────────────────
  const pct = progress ? Math.round(progress.progress * 100) : 0
  const streamSrc = `${BACKEND}/api/tracking/stream/${cam?.id}?k=${streamKey}`

  return (
    <div className="max-w-4xl">
      <h3 className="text-xl font-semibold mb-1 text-gray-800">Test Mode & Heatmap</h3>
      <p className="text-gray-500 mb-4 text-sm">
        Run YOLO + ByteTrack on your video. Watch the live stream, then explore
        trajectory dots and the zone-coloured heatmap.
      </p>

      {/* Camera selector */}
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
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition
                ${selectedCamId === c.id ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}>
              {c.name} {c.trackingResults ? '✓' : ''}
            </button>
          ))}
        </div>
      )}

      {cam && (
        <>
          {/* ── Controls ──────────────────────────────────────────────── */}
          <div className="bg-white border rounded-xl p-4 mb-4 flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-2">
              <label className="text-sm font-medium text-gray-600">Model:</label>
              <select value={modelSize} onChange={e => setModelSize(e.target.value)}
                disabled={isTracking}
                className="border rounded-lg px-2 py-1.5 text-sm disabled:opacity-50">
                <option value="n">Nano (fastest)</option>
                <option value="s">Small</option>
                <option value="m">Medium</option>
              </select>
            </div>

            <button
              onClick={handleStart}
              disabled={isTracking || !cam.homographyMatrix}
              className="px-5 py-2 rounded-lg font-medium text-sm text-white transition disabled:opacity-40"
              style={{ background: isTracking ? '#6b7280' : '#1B3A5C' }}
            >
              {isTracking ? '⏳ Running…' : trackingDone ? '↺ Re-run' : '▶ Start Tracking'}
            </button>

            {!cam.homographyMatrix && (
              <p className="text-yellow-600 text-sm">⚠ Compute homography first (Step 7).</p>
            )}

            {isTracking && progress && (
              <div className="flex-1 min-w-48">
                <ProgressBar value={progress.progress} />
                <p className="text-xs text-gray-500 mt-1 text-right">
                  {pct}% — frame {progress.processedFrames} / {progress.totalFrames}
                </p>
              </div>
            )}

            {trackingDone && (
              <div className="flex gap-2 ml-auto">
                <button onClick={handleDownloadHeatmap}
                  className="text-sm px-3 py-1.5 border rounded-lg hover:bg-gray-50">
                  ⬇ Heatmap PNG
                </button>
                <button onClick={handleExportCSV}
                  className="text-sm px-3 py-1.5 border rounded-lg hover:bg-gray-50">
                  ⬇ Trajectory CSV
                </button>
              </div>
            )}
          </div>

          {error && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
              ✗ {error}
            </div>
          )}

          {/* ── View toggle ────────────────────────────────────────────── */}
          {(isTracking || trackingDone) && (
            <div className="flex gap-2 mb-4">
              <button onClick={() => setViewMode('stream')}
                className={`px-4 py-1.5 rounded-lg text-sm font-medium transition
                  ${viewMode === 'stream' ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}>
                📹 Live Stream {isTracking && <span className="ml-1 text-xs animate-pulse">●</span>}
              </button>
              <button onClick={() => setViewMode('trajectory')}
                disabled={!trackingDone}
                className={`px-4 py-1.5 rounded-lg text-sm font-medium transition disabled:opacity-40
                  ${viewMode === 'trajectory' ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}>
                📍 Trajectory
              </button>
              <button onClick={() => setViewMode('heatmap')}
                disabled={!trackingDone}
                className={`px-4 py-1.5 rounded-lg text-sm font-medium transition disabled:opacity-40
                  ${viewMode === 'heatmap' ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}>
                🔥 Heatmap
              </button>
            </div>
          )}

          {/* ── Main view ─────────────────────────────────────────────── */}
          {(isTracking || trackingDone) && (
            <div className="mb-6">
              {viewMode === 'stream' && (
                <div className="border rounded-xl overflow-hidden shadow bg-black"
                  style={{ maxWidth: 720, maxHeight: 480 }}>
                  {isTracking ? (
                    <img key={streamKey} src={streamSrc} alt="Live tracking"
                      className="w-full block" style={{ maxHeight: 480, objectFit: 'contain' }} />
                  ) : (
                    <div className="flex items-center justify-center p-12 text-center" style={{ minHeight: 180 }}>
                      <div>
                        <div className="text-4xl mb-2">✅</div>
                        <p className="font-medium text-white">Tracking complete</p>
                        <p className="text-gray-400 text-sm mt-1">Switch to Trajectory or Heatmap view above.</p>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {viewMode === 'trajectory' && trackingDone && (
                <div style={{ maxWidth: 720 }}>
                  <TrajectoryView
                    floorPlanUrl={floorPlanUrl}
                    floorPlanWidth={floorPlanWidth}
                    floorPlanHeight={floorPlanHeight}
                    origin={origin}
                    pixelsPerMeter={pixelsPerMeter}
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

          {/* ── Zone occupancy table ──────────────────────────────────── */}
          {(isTracking || trackingDone) && (
            <div className="bg-white border rounded-xl overflow-hidden shadow-sm" style={{ maxWidth: 720 }}>
              <div className="px-4 py-2 bg-gray-50 border-b flex items-center justify-between">
                <h4 className="text-sm font-semibold text-gray-700">Zone Occupancy</h4>
                {isTracking && (
                  <span className="text-xs text-blue-500 animate-pulse font-medium">● Live</span>
                )}
              </div>
              <ZoneTable
                zones={zones}
                zoneOccupancy={isTracking ? liveOccupancy : results?.zoneOccupancy}
                trajectoryMeters={results?.trajectoryMeters}
                effectiveFps={(cam.videoFps || 25) / 3}
              />
            </div>
          )}

          {/* Idle placeholder */}
          {!isTracking && !trackingDone && (
            <div className="border-2 border-dashed border-gray-200 rounded-xl p-12 text-center text-gray-400"
              style={{ maxWidth: 720 }}>
              <div className="text-4xl mb-3">🎬</div>
              <p className="font-medium">Click <strong>Start Tracking</strong> to begin.</p>
              <p className="text-sm mt-1">
                The video will stream live with bounding boxes as the model processes each frame.
              </p>
            </div>
          )}
        </>
      )}

      <div className="mt-6 flex justify-between" style={{ maxWidth: 720 }}>
        <button onClick={() => setStep(8)}
          className="px-4 py-2 text-gray-600 border rounded-lg hover:bg-gray-50">
          ← Back
        </button>
        {trackingDone && (
          <span className="text-sm text-green-600 font-medium flex items-center gap-1">
            🎉 All steps complete!
          </span>
        )}
      </div>
    </div>
  )
}
