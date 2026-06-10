import React, { useEffect, useRef, useState } from 'react'
import { Stage, Layer, Image as KonvaImage, Line, Circle, Text } from 'react-konva'
import { Layers } from 'lucide-react'
import { ZONE_COLORS } from './storeSetup'

function useImage(url) {
  const [image, setImage] = useState(null)
  useEffect(() => {
    if (!url) { setImage(null); return }
    const img = new window.Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => setImage(img)
    img.onerror = () => setImage(null)
    img.src = url
  }, [url])
  return image
}

const LAYER_DEFS = [
  ['zones', 'Zones'], ['cameras', 'Cameras'], ['obstacles', 'Obstacles'], ['punch', 'Punch'],
]

// Read-only floor map: zoom/pan + layer toggles. Zones/cameras/obstacles/punch all
// arrive as floor-plan pixels (backend pre-projects), so everything is x*scale.
// Punch radius is radius_m × ppm (→ px) × scale.
export default function FloorMap({ floorPlan, zones = [], obstacles = [], cameraConfigs = [], punch = null, cameraStatusById = {} }) {
  const containerRef = useRef(null)
  const [size, setSize] = useState({ w: 800, h: 500 })
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [show, setShow] = useState({ zones: true, cameras: true, obstacles: true, punch: true })
  const drag = useRef(null)
  const bgImage = useImage(floorPlan?.display_url)

  useEffect(() => {
    if (!containerRef.current) return
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }))
    ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [])

  if (!floorPlan?.image_uploaded) {
    return (
      <div className="flex flex-col items-center justify-center h-64 bg-gray-50 rounded-lg text-gray-400 text-sm gap-2 border border-dashed border-gray-200">
        <span className="text-3xl">🗺️</span><span>No floor plan uploaded yet</span>
      </div>
    )
  }

  const imgW = floorPlan.width_px || 1
  const imgH = floorPlan.height_px || 1
  const base = Math.min(size.w / imgW, size.h / imgH)
  const scale = base * zoom
  const stageH = Math.round(imgH * base)
  const ppm = floorPlan.pixels_per_meter || 1
  const tx = (x) => x * scale + pan.x
  const ty = (y) => y * scale + pan.y

  const onWheel = (e) => {
    e.evt.preventDefault()
    const next = Math.min(6, Math.max(1, e.evt.deltaY < 0 ? zoom * 1.12 : zoom / 1.12))
    const ptr = e.target.getStage().getPointerPosition()
    setPan((p) => ({ x: ptr.x - (ptr.x - p.x) * (next / zoom), y: ptr.y - (ptr.y - p.y) * (next / zoom) }))
    setZoom(next)
  }
  const onDown = (e) => { drag.current = { x: e.evt.clientX, y: e.evt.clientY } }
  const onMove = (e) => {
    if (!drag.current) return
    const dx = e.evt.clientX - drag.current.x, dy = e.evt.clientY - drag.current.y
    drag.current = { x: e.evt.clientX, y: e.evt.clientY }
    setPan((p) => ({ x: p.x + dx, y: p.y + dy }))
  }
  const onUp = () => { drag.current = null }

  return (
    <div>
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <Layers size={14} className="text-gray-400" />
        {LAYER_DEFS.map(([k, label]) => (
          <button key={k} onClick={() => setShow((s) => ({ ...s, [k]: !s[k] }))}
            className={`text-xs px-2 py-1 rounded-full border ${show[k] ? 'bg-blue-50 border-blue-200 text-blue-700' : 'bg-white border-gray-200 text-gray-400'}`}>
            {label}
          </button>
        ))}
        {zoom !== 1 && (
          <button onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }) }} className="text-xs px-2 py-1 rounded-full border bg-white border-gray-200 text-gray-500 ml-auto">
            Reset view
          </button>
        )}
      </div>
      <div ref={containerRef} className="w-full" style={{ height: stageH }}>
        <Stage width={size.w} height={stageH} onWheel={onWheel} onMouseDown={onDown} onMouseMove={onMove} onMouseUp={onUp} onMouseLeave={onUp} style={{ cursor: drag.current ? 'grabbing' : 'grab', background: '#f3f4f6', borderRadius: 8 }}>
          <Layer>
            {bgImage && <KonvaImage image={bgImage} x={pan.x} y={pan.y} width={imgW * scale} height={imgH * scale} />}

            {show.obstacles && obstacles.map((obs) => (
              <Line key={obs.id} points={obs.points.flatMap(([x, y]) => [tx(x), ty(y)])} closed
                fill="#6b728033" stroke="#6b7280" strokeWidth={2} dash={[6, 3]} />
            ))}

            {show.zones && zones.map((z) => (
              <React.Fragment key={z.id}>
                <Line points={z.points.flatMap(([x, y]) => [tx(x), ty(y)])} closed
                  fill={(ZONE_COLORS[z.type] || '#888') + '33'} stroke={ZONE_COLORS[z.type] || '#888'} strokeWidth={2} />
                {z.points[0] && <Text x={tx(z.points[0][0]) + 4} y={ty(z.points[0][1]) + 4} text={z.name} fontSize={12} fill={ZONE_COLORS[z.type] || '#888'} />}
              </React.Fragment>
            ))}

            {show.cameras && cameraConfigs.map((cc) => {
              const live = cameraStatusById[cc.physical_camera_id]
              const color = live?.online ? '#10b981' : cc.status === 'verified' ? '#10b981' : cc.status === 'calibrated' ? '#f59e0b' : '#6b7280'
              return (
                <React.Fragment key={cc.id}>
                  <Circle x={tx(cc.position_x)} y={ty(cc.position_y)} radius={8} fill={color} stroke="#fff" strokeWidth={2} />
                  <Text x={tx(cc.position_x) + 12} y={ty(cc.position_y) - 6} text={cc.physical_camera_name} fontSize={11} fill="#1f2937" />
                </React.Fragment>
              )
            })}

            {show.punch && punch && (
              <>
                <Circle x={tx(punch.position_x)} y={ty(punch.position_y)} radius={(punch.radius_m * ppm) * scale} fill="#a855f733" stroke="#a855f7" strokeWidth={2} dash={[5, 3]} />
                <Circle x={tx(punch.position_x)} y={ty(punch.position_y)} radius={6} fill="#a855f7" stroke="#fff" strokeWidth={2} />
                <Text x={tx(punch.position_x) + 10} y={ty(punch.position_y) - 6} text="Punch" fontSize={11} fill="#7e22ce" />
              </>
            )}
          </Layer>
        </Stage>
      </div>
    </div>
  )
}
