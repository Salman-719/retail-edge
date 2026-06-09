import React, { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Stage, Layer, Image as KonvaImage, Line, Circle, Text } from 'react-konva'
import { usePageTitle } from '../components/PageMeta'
import { StatsSkeleton } from '../components/Skeletons'
import AlertCard from '../components/alerts/AlertCard'
import { getActiveVersion, getLiveOverview, getCameraHealth, getActiveAlerts, resolveAlert } from '../api'
import { worldToImagePx } from '../lib/floorProjection'
import { formatDuration } from '../lib/format'

const POLL_MS = 60000

const ZONE_COLORS = {
  entrance: '#3b82f6', checkout: '#f59e0b', aisle: '#10b981',
  staff_only: '#ef4444', general: '#8b5cf6',
}
const PERSON_FILL = { customer: '#22c55e', staff: '#1B3A5C' }

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

// Floor plan + zones/cameras (already image-px from the backend) + live persons
// (world metres → image-px via the SHARED helper, then ×scale like zones).
function FloorPlanCanvas({ floorPlan, zones = [], obstacles = [], cameraConfigs = [], persons = [] }) {
  const containerRef = useRef(null)
  const [size, setSize] = useState({ w: 800, h: 500 })
  const [hover, setHover] = useState(null)
  const bgImage = useImage(floorPlan?.display_url)

  useEffect(() => {
    if (!containerRef.current) return
    const ro = new ResizeObserver(([entry]) => setSize({ w: entry.contentRect.width, h: entry.contentRect.height }))
    ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [])

  if (!floorPlan?.image_uploaded) {
    return (
      <div className="flex items-center justify-center h-full bg-gray-100 rounded-lg text-gray-400 text-sm">
        No floor plan configured
      </div>
    )
  }

  const imgW = floorPlan.width_px || 1
  const imgH = floorPlan.height_px || 1
  const scale = Math.min(size.w / imgW, size.h / imgH)
  const stageH = Math.round(imgH * scale)
  const toPx = worldToImagePx(floorPlan)

  return (
    <div ref={containerRef} className="w-full h-full" style={{ position: 'relative' }}>
      <Stage width={size.w} height={stageH}>
        <Layer>
          {bgImage && <KonvaImage image={bgImage} width={imgW * scale} height={imgH * scale} />}

          {obstacles.map(obs => (
            <Line key={obs.id} points={obs.points.flatMap(([x, y]) => [x * scale, y * scale])}
              closed fill="#6b728022" stroke="#6b7280" strokeWidth={1.5} dash={[5, 3]} />
          ))}

          {zones.map(zone => (
            <React.Fragment key={zone.id}>
              <Line points={zone.points.flatMap(([x, y]) => [x * scale, y * scale])} closed
                fill={(ZONE_COLORS[zone.type] || '#888') + '28'} stroke={ZONE_COLORS[zone.type] || '#888'} strokeWidth={1.5} />
              {zone.points[0] && (
                <Text x={zone.points[0][0] * scale + 4} y={zone.points[0][1] * scale + 4}
                  text={zone.name} fontSize={11} fill={ZONE_COLORS[zone.type] || '#888'} />
              )}
            </React.Fragment>
          ))}

          {cameraConfigs.map(cc => (
            <Circle key={cc.id} x={cc.position_x * scale} y={cc.position_y * scale}
              radius={7} fill="#1B3A5C" stroke="#fff" strokeWidth={1.5} />
          ))}

          {persons.map(p => {
            const [ix, iy] = toPx(p.world_x, p.world_y)
            return (
              <Circle
                key={p.global_id}
                x={ix * scale} y={iy * scale}
                radius={6}
                fill={PERSON_FILL[p.type] || '#22c55e'}
                stroke="#fff" strokeWidth={1.5} opacity={0.9}
                onMouseEnter={() => setHover({ p, x: ix * scale, y: iy * scale })}
                onMouseLeave={() => setHover(null)}
              />
            )
          })}
        </Layer>
      </Stage>

      {hover && (
        <div
          className="absolute z-10 pointer-events-none bg-gray-900/90 text-white text-xs rounded-lg px-2.5 py-1.5 shadow-lg"
          style={{ left: hover.x + 10, top: Math.max(0, hover.y - 10) }}
        >
          <div className="font-semibold capitalize">{hover.p.type}{hover.p.employee_name ? ` · ${hover.p.employee_name}` : ''}</div>
          <div className="text-gray-300">Zone: {hover.p.current_zone_name || '—'}</div>
          <div className="text-gray-300">Dwell: {formatDuration(hover.p.dwell_ms)}</div>
        </div>
      )}

      {persons.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center text-sm text-gray-400 pointer-events-none">
          No one on the floor right now
        </div>
      )}
    </div>
  )
}

function KpiCard({ label, value, highlight }) {
  return (
    <div className={`bg-white border rounded-xl px-5 py-4 flex flex-col gap-1 ${highlight ? 'border-red-300' : 'border-gray-200'}`}>
      <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</span>
      <span className={`text-3xl font-bold tabular-nums ${highlight ? 'text-red-600' : 'text-gray-900'}`}>{value}</span>
    </div>
  )
}

function cameraStyle(cam) {
  if (cam.online) return 'bg-green-50 border-green-200 text-green-700'
  if (cam.status === 'unknown') return 'bg-gray-50 border-gray-200 text-gray-500'
  return 'bg-amber-50 border-amber-200 text-amber-700'
}
function cameraDot(cam) {
  if (cam.online) return 'bg-green-500'
  if (cam.status === 'unknown') return 'bg-gray-400'
  return 'bg-amber-500'
}

export default function LiveMonitoring() {
  const { slug } = useParams()
  usePageTitle('Live Monitoring')

  const [config, setConfig] = useState(null)
  const [loadingConfig, setLoadingConfig] = useState(true)
  const [overview, setOverview] = useState(null)
  const [alerts, setAlerts] = useState([])
  const [cameraHealth, setCameraHealth] = useState(null)
  const [loadingLive, setLoadingLive] = useState(true)
  const [dismissingId, setDismissingId] = useState(null)
  const [nowTick, setNowTick] = useState(Date.now())

  useEffect(() => {
    getActiveVersion(slug).then(setConfig).catch(() => setConfig(null)).finally(() => setLoadingConfig(false))
  }, [slug])

  async function loadAlerts() {
    try { const a = await getActiveAlerts(slug); setAlerts(Array.isArray(a) ? a : []) } catch { /* keep last */ }
  }

  useEffect(() => {
    let cancelled = false
    async function tick() {
      try { const o = await getLiveOverview(slug); if (!cancelled) setOverview(o) } catch { /* keep last */ }
      try { const c = await getCameraHealth(slug); if (!cancelled) setCameraHealth(c) } catch { /* keep last */ }
      await loadAlerts()
      if (!cancelled) setLoadingLive(false)
    }
    tick()
    const poll = setInterval(tick, POLL_MS)
    const clock = setInterval(() => setNowTick(Date.now()), 1000)
    return () => { cancelled = true; clearInterval(poll); clearInterval(clock) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug])

  async function dismiss(alert) {
    setDismissingId(alert.id)
    setAlerts(list => list.filter(a => a.id !== alert.id)) // optimistic
    try { await resolveAlert(slug, alert.id) } catch { loadAlerts() } finally { setDismissingId(null) }
  }

  const kpi = overview?.kpis
  const persons = overview?.persons || []
  const updatedAgo = overview ? Math.max(0, Math.round((nowTick - overview.generated_at_ms) / 1000)) : null

  return (
    <div className="page-enter flex flex-col h-full overflow-hidden">
      <header className="bg-white border-b border-gray-200 px-6 py-4 shrink-0 flex items-center justify-between">
        <div>
          <h1 className="page-title">Live Monitoring</h1>
          <p className="page-subtitle">Near-live store activity · one update per ~60s window</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
          <span className="text-xs text-gray-500">
            {updatedAgo === null ? 'Connecting…' : `Updated ${updatedAgo}s ago`}
          </span>
        </div>
      </header>

      <div className="flex-1 overflow-auto p-5 space-y-4">

        {/* KPI Bar */}
        {loadingLive && !kpi ? (
          <StatsSkeleton count={4} />
        ) : (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <KpiCard label="Total People"   value={kpi?.total_people ?? 0} />
            <KpiCard label="Customers"      value={kpi?.customers ?? 0} />
            <KpiCard label="Staff On Floor" value={kpi?.staff_on_floor ?? 0} />
            <KpiCard label="Active Alerts"  value={kpi?.active_alerts ?? 0} highlight={(kpi?.active_alerts ?? 0) > 0} />
          </div>
        )}

        <div className="flex flex-col lg:flex-row gap-4">
          {/* Floor plan */}
          <div className="bg-white border border-gray-200 rounded-xl p-4 flex flex-col min-h-[280px] lg:flex-[0_0_70%]">
            <div className="flex items-center justify-between shrink-0">
              <h2 className="text-sm font-semibold text-gray-700">Floor Plan</h2>
              <div className="flex items-center gap-4 text-xs text-gray-500">
                <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-green-500 inline-block" /> Customer</span>
                <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-blue-900 inline-block" /> Staff</span>
                <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-gray-600 inline-block" /> Camera</span>
              </div>
            </div>
            <div className="flex-1 min-h-0 mt-3">
              {loadingConfig ? (
                <div className="flex items-center justify-center h-full text-gray-400 text-sm">Loading floor plan…</div>
              ) : (
                <FloorPlanCanvas
                  floorPlan={config?.floor_plan}
                  zones={config?.zones || []}
                  obstacles={config?.obstacles || []}
                  cameraConfigs={config?.camera_configs || []}
                  persons={persons}
                />
              )}
            </div>
          </div>

          {/* Alerts feed (reuses D1 active alerts + D4 AlertCard + D2 dismiss) */}
          <div className="bg-white border border-gray-200 rounded-xl p-4 flex flex-col max-h-[300px] lg:max-h-none lg:flex-1">
            <div className="flex items-center justify-between mb-3 shrink-0">
              <h2 className="text-sm font-semibold text-gray-700">Active Alerts</h2>
              {alerts.length > 0 && (
                <span className="text-xs bg-red-100 text-red-700 font-semibold px-2 py-0.5 rounded-full">{alerts.length}</span>
              )}
            </div>
            <div className="flex-1 overflow-y-auto space-y-2 min-h-0">
              {alerts.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full text-gray-400 text-sm gap-2">
                  <span className="text-2xl">✓</span><span>No active alerts</span>
                </div>
              ) : (
                alerts.map(a => <AlertCard key={a.id} alert={a} onDismiss={dismiss} dismissing={dismissingId === a.id} />)
              )}
            </div>
          </div>
        </div>

        {/* Camera health + agent */}
        <div className="bg-white border border-gray-200 rounded-xl px-5 py-3 shrink-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide mr-2">Camera Status</span>
            {(cameraHealth?.cameras || []).map(cam => (
              <div key={cam.physical_camera_id} title={cam.status}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-xs font-medium ${cameraStyle(cam)}`}>
                <span className={`w-2 h-2 rounded-full ${cameraDot(cam)}`} />
                {cam.name}
                {!cam.online && <span className="opacity-70">· {cam.status}</span>}
              </div>
            ))}
            {cameraHealth && cameraHealth.cameras.length === 0 && (
              <span className="text-xs text-gray-400">No cameras configured</span>
            )}
          </div>
          {cameraHealth?.agent && (
            <div className="mt-2 text-xs text-gray-500 flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${cameraHealth.agent.online ? 'bg-green-500' : 'bg-red-500'}`} />
              Edge device {cameraHealth.agent.online ? 'online' : 'offline'}
              {cameraHealth.agent.heartbeat_age_seconds != null && (
                <span>· last seen {Math.round(cameraHealth.agent.heartbeat_age_seconds)}s ago</span>
              )}
              {cameraHealth.agent.agent_version && <span>· v{cameraHealth.agent.agent_version}</span>}
            </div>
          )}
        </div>

      </div>
    </div>
  )
}
