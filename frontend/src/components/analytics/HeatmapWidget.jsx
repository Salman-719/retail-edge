import React, { useEffect, useRef, useState } from 'react'
import { Stage, Layer, Image as KonvaImage, Rect } from 'react-konva'
import { getHeatmap } from '../../api'
import { useAnalyticsQuery } from './useAnalyticsQuery'
import WidgetFrame from './WidgetFrame'
import { worldToImagePx } from '../../lib/floorProjection'
import { toCsv, downloadCsv } from '../../lib/csv'

// blue (low) → yellow → red (high)
function heatColor(t) {
  t = Math.min(1, Math.max(0, t))
  if (t < 0.5) {
    const s = t * 2
    return `rgba(${Math.round(s * 255)},${Math.round(s * 200)},${Math.round(255 - s * 255)},0.55)`
  }
  const s = (t - 0.5) * 2
  return `rgba(255,${Math.round(200 - s * 200)},0,0.6)`
}

function useImage(url) {
  const [img, setImg] = useState(null)
  useEffect(() => {
    if (!url) { setImg(null); return }
    const i = new window.Image()
    i.crossOrigin = 'anonymous'
    i.onload = () => setImg(i)
    i.onerror = () => setImg(null)
    i.src = url
  }, [url])
  return img
}

function HeatmapCanvas({ floorPlan, cells }) {
  const containerRef = useRef(null)
  const [w, setW] = useState(800)
  const bg = useImage(floorPlan?.display_url)

  useEffect(() => {
    if (!containerRef.current) return
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width))
    ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [])

  const imgW = floorPlan?.width_px || 1
  const imgH = floorPlan?.height_px || 1
  const scale = w / imgW
  const stageW = Math.round(imgW * scale)
  const stageH = Math.round(imgH * scale)
  const toPx = worldToImagePx(floorPlan)

  return (
    <div ref={containerRef} className="w-full">
      <Stage width={stageW} height={stageH}>
        <Layer listening={false}>
          {bg && <KonvaImage image={bg} width={stageW} height={stageH} />}
          {cells.map((c, i) => {
            // world-metre rect → image px (shared convention) → canvas px
            const [x0, y0] = toPx(c.world_x_min, c.world_y_min)
            const [x1, y1] = toPx(c.world_x_max, c.world_y_max)
            const px = Math.min(x0, x1) * scale
            const py = Math.min(y0, y1) * scale
            return (
              <Rect
                key={i}
                x={px} y={py}
                width={Math.abs(x1 - x0) * scale}
                height={Math.abs(y1 - y0) * scale}
                fill={heatColor(c.intensity)}
              />
            )
          })}
        </Layer>
      </Stage>
      <div className="flex items-center gap-2 mt-3">
        <span className="text-xs text-gray-500">Low</span>
        <div className="flex-1 h-3 rounded" style={{ background: 'linear-gradient(to right, rgba(0,0,255,0.5), rgba(255,200,0,0.55), rgba(255,0,0,0.6))' }} />
        <span className="text-xs text-gray-500">High</span>
      </div>
    </div>
  )
}

export default function HeatmapWidget({ slug, from, to, granularity }) {
  // Heatmap has its own grain set (hour|day|week|month); 'auto' → 'day'.
  const hmGrain = granularity === 'auto' ? 'day' : granularity
  const { data, loading, error } = useAnalyticsQuery(
    () => getHeatmap(slug, { from, to, granularity: hmGrain }),
    [slug, from, to, hmGrain],
  )

  const floorPlan = data?.floor_plan || null
  const cells = data?.cells || []
  const noPlan = data && (!floorPlan || !floorPlan.image_uploaded)

  function exportCsv() {
    downloadCsv(`heatmap_${from}_${to}.csv`, toCsv(cells, [
      { key: 'grid_x', label: 'grid_x' }, { key: 'grid_y', label: 'grid_y' },
      { key: 'hit_count', label: 'hit_count' }, { key: 'intensity', label: 'intensity' },
      { key: 'world_x_min', label: 'world_x_min' }, { key: 'world_y_min', label: 'world_y_min' },
      { key: 'world_x_max', label: 'world_x_max' }, { key: 'world_y_max', label: 'world_y_max' },
    ]))
  }

  return (
    <WidgetFrame
      title="Dwell Heatmap"
      subtitle={data ? `Grain: ${data.grain}` : undefined}
      onExport={exportCsv}
      loading={loading} error={error}
      isEmpty={!loading && !error && !cells.length && !noPlan}
      emptyLabel="No heatmap data for this range yet"
    >
      {noPlan ? (
        <div className="flex items-center justify-center h-48 bg-gray-100 rounded-lg text-gray-400 text-sm text-center px-4">
          Heatmap needs a configured floor plan — upload one in Store Config.
        </div>
      ) : (
        <HeatmapCanvas floorPlan={floorPlan} cells={cells} />
      )}
    </WidgetFrame>
  )
}
