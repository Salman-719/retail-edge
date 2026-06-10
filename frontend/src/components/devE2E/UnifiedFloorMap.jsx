import React, { useEffect, useRef, useState } from 'react'
import { Stage, Layer, Image as KonvaImage, Line, Circle, Text } from 'react-konva'
import { Layers } from 'lucide-react'
import { worldToImagePx } from '../../lib/floorProjection'
import { ZONE_COLORS } from '../store/storeSetup'

function useImage(url) {
  const [img, setImg] = useState(null)
  useEffect(() => {
    if (!url) { setImg(null); return }
    const i = new window.Image(); i.crossOrigin = 'anonymous'
    i.onload = () => setImg(i); i.onerror = () => setImg(null); i.src = url
    return () => { i.onload = null }
  }, [url])
  return img
}

// The single real-floor-plan view (VD2): zones (image-px) + per-camera IEP2
// foot-points + IEP3 global dots (both world metres → worldToImagePx → ×scale).
// One projection convention; no data-fit TrackMaps.
export default function UnifiedFloorMap({
  floorPlan, zones = [], trackingByCam = {}, globals = [],
  camColorById = {}, camLabelById = {}, identity, focusCam, onFocusCam,
}) {
  const ref = useRef(null)
  const [size, setSize] = useState({ w: 800, h: 500 })
  const [show, setShow] = useState({ zones: true, footpoints: true, globals: true })
  const bg = useImage(floorPlan?.display_url)

  useEffect(() => {
    if (!ref.current) return
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }))
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [])

  if (!floorPlan?.image_uploaded) {
    return <div className="flex items-center justify-center h-64 bg-gray-100 rounded-lg text-gray-400 text-sm">No floor plan configured</div>
  }

  const imgW = floorPlan.width_px || 1
  const imgH = floorPlan.height_px || 1
  const scale = Math.min(size.w / imgW, size.h / imgH)
  const stageH = Math.round(imgH * scale)
  const toPx = worldToImagePx(floorPlan)
  const proj = (wx, wy) => { const [ix, iy] = toPx(wx, wy); return [ix * scale, iy * scale] }

  const LAYERS = [['zones', 'Zones'], ['footpoints', 'Foot-points'], ['globals', 'IEP3 globals']]

  return (
    <div>
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <Layers size={14} className="text-gray-400" />
        {LAYERS.map(([k, label]) => (
          <button key={k} onClick={() => setShow((s) => ({ ...s, [k]: !s[k] }))}
            className={`text-xs px-2 py-1 rounded-full border ${show[k] ? 'bg-blue-50 border-blue-200 text-blue-700' : 'bg-white border-gray-200 text-gray-400'}`}>{label}</button>
        ))}
        {Object.keys(trackingByCam).length > 1 && (
          <div className="flex items-center gap-1 ml-2">
            {Object.keys(trackingByCam).map((cid) => (
              <button key={cid} onClick={() => onFocusCam(focusCam === cid ? null : cid)}
                className={`text-xs px-2 py-0.5 rounded-full border ${focusCam === cid ? 'text-white' : 'bg-white text-gray-600'}`}
                style={focusCam === cid ? { background: camColorById[cid], borderColor: camColorById[cid] } : { borderColor: camColorById[cid] }}>
                {camLabelById[cid] || 'cam'}
              </button>
            ))}
          </div>
        )}
      </div>
      <div ref={ref} className="w-full" style={{ height: stageH }}>
        <Stage width={size.w} height={stageH} style={{ background: '#f3f4f6', borderRadius: 8 }}>
          <Layer listening={false}>
            {bg && <KonvaImage image={bg} width={imgW * scale} height={imgH * scale} opacity={0.9} />}

            {show.zones && zones.map((z) => (
              <React.Fragment key={z.id}>
                <Line points={z.points.flatMap(([x, y]) => [x * scale, y * scale])} closed
                  fill={(ZONE_COLORS[z.type] || '#888') + '22'} stroke={ZONE_COLORS[z.type] || '#888'} strokeWidth={1.5} />
                {z.points[0] && <Text x={z.points[0][0] * scale + 4} y={z.points[0][1] * scale + 4} text={z.name} fontSize={10} fill={ZONE_COLORS[z.type] || '#888'} />}
              </React.Fragment>
            ))}

            {show.footpoints && Object.entries(trackingByCam).map(([cid, rows]) => {
              if (focusCam && focusCam !== cid) return null
              const color = camColorById[cid] || '#64748b'
              return (rows || []).map((r, i) => {
                if (r.floor_x == null || r.floor_y == null) return null
                const [x, y] = proj(r.floor_x, r.floor_y)
                return <Circle key={`${cid}-${i}`} x={x} y={y} radius={3} fill={color} opacity={0.7} />
              })
            })}

            {show.globals && globals.map((g, i) => {
              if (g.floor_x == null || g.floor_y == null) return null
              const [x, y] = proj(g.floor_x, g.floor_y)
              const id = identity.get(g.global_id)
              return (
                <React.Fragment key={`g-${i}`}>
                  <Circle x={x} y={y} radius={6} fill={id.color} stroke="#fff" strokeWidth={1.5} />
                  {id.number != null && <Text x={x + 7} y={y - 6} text={String(id.number)} fontSize={11} fontStyle="bold" fill={id.color} />}
                </React.Fragment>
              )
            })}
          </Layer>
        </Stage>
      </div>
    </div>
  )
}
