import React, { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { usePageTitle } from '../components/PageMeta'
import { StatsSkeleton } from '../components/Skeletons'
import SectionTabs from '../components/SectionTabs'
import { Stage, Layer, Image as KonvaImage, Line, Circle, Text } from 'react-konva'
import { getActiveVersion, getCameraHealth } from '../api'

// A camera counts as "online" only if it reported within this window.
const EDGE_ONLINE_WINDOW_MS = 30000

// ─── Constants ────────────────────────────────────────────────────────────────

const ZONE_COLORS = {
  entrance: '#3b82f6', checkout: '#f59e0b', aisle: '#10b981',
  staff_only: '#ef4444', general: '#8b5cf6',
}

const ALERT_COLORS = {
  Queue: { bg: 'bg-amber-50', border: 'border-amber-200', badge: 'bg-amber-100 text-amber-700', dot: 'bg-amber-400' },
  Overcrowding: { bg: 'bg-red-50', border: 'border-red-200', badge: 'bg-red-100 text-red-700', dot: 'bg-red-500' },
  Absence: { bg: 'bg-blue-50', border: 'border-blue-200', badge: 'bg-blue-100 text-blue-700', dot: 'bg-blue-400' },
}

// MOCK: replace with API call to GET /store/{slug}/live/summary
const MOCK_KPI = {
  total_people: 34,
  customers: 29,
  staff_on_floor: 5,
  active_alerts: 3,
}

// MOCK: replace with API call to GET /store/{slug}/live/positions
// Each entry: { id, x, y, type } where x/y are floor-plan pixel coordinates
const MOCK_PEOPLE = [
  { id: 'p1', x: 120, y: 90,  type: 'customer' },
  { id: 'p2', x: 200, y: 140, type: 'customer' },
  { id: 'p3', x: 310, y: 80,  type: 'customer' },
  { id: 'p4', x: 410, y: 210, type: 'staff' },
  { id: 'p5', x: 520, y: 160, type: 'customer' },
  { id: 'p6', x: 180, y: 260, type: 'customer' },
  { id: 'p7', x: 370, y: 310, type: 'customer' },
  { id: 'p8', x: 600, y: 95,  type: 'staff' },
  { id: 'p9', x: 260, y: 190, type: 'customer' },
  { id: 'p10', x: 480, y: 280, type: 'customer' },
]

// MOCK: replace with API call to GET /store/{slug}/alerts/active
const MOCK_ALERTS_INIT = [
  { id: 'a1', type: 'Queue',        zone: 'Checkout 1', ts: '14:22' },
  { id: 'a2', type: 'Overcrowding', zone: 'Entrance',   ts: '14:18' },
  { id: 'a3', type: 'Absence',      zone: 'Aisle B',    ts: '14:05' },
]

// ─── Sub-components ───────────────────────────────────────────────────────────

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

function FloorPlanCanvas({ floorPlan, zones = [], obstacles = [], cameraConfigs = [], people = [] }) {
  const containerRef = useRef(null)
  const [size, setSize] = useState({ w: 800, h: 500 })
  const bgImage = useImage(floorPlan?.display_url)

  useEffect(() => {
    if (!containerRef.current) return
    const ro = new ResizeObserver(([entry]) => {
      setSize({ w: entry.contentRect.width, h: entry.contentRect.height })
    })
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

  return (
    <div ref={containerRef} className="w-full h-full">
      <Stage width={size.w} height={stageH}>
        <Layer>
          {bgImage && (
            <KonvaImage image={bgImage} width={imgW * scale} height={imgH * scale} />
          )}

          {obstacles.map(obs => (
            <Line key={obs.id}
              points={obs.points.flatMap(([x, y]) => [x * scale, y * scale])}
              closed fill="#6b728022" stroke="#6b7280" strokeWidth={1.5} dash={[5, 3]} />
          ))}

          {zones.map(zone => (
            <React.Fragment key={zone.id}>
              <Line
                points={zone.points.flatMap(([x, y]) => [x * scale, y * scale])}
                closed
                fill={(ZONE_COLORS[zone.type] || '#888') + '28'}
                stroke={ZONE_COLORS[zone.type] || '#888'}
                strokeWidth={1.5}
              />
              {zone.points[0] && (
                <Text
                  x={zone.points[0][0] * scale + 4}
                  y={zone.points[0][1] * scale + 4}
                  text={zone.name}
                  fontSize={11}
                  fill={ZONE_COLORS[zone.type] || '#888'}
                />
              )}
            </React.Fragment>
          ))}

          {cameraConfigs.map(cc => (
            <React.Fragment key={cc.id}>
              <Circle
                x={cc.position_x * scale} y={cc.position_y * scale}
                radius={7} fill="#1B3A5C" stroke="#fff" strokeWidth={1.5}
              />
              <Text
                x={cc.position_x * scale + 10} y={cc.position_y * scale - 6}
                text={cc.physical_camera_name} fontSize={10} fill="#1f2937"
              />
            </React.Fragment>
          ))}

          {/* MOCK: replace with live positions from GET /store/{slug}/live/positions */}
          {people.map(p => (
            <Circle
              key={p.id}
              x={p.x * scale} y={p.y * scale}
              radius={6}
              fill={p.type === 'staff' ? '#1B3A5C' : '#22c55e'}
              stroke="#fff" strokeWidth={1.5}
              opacity={0.85}
            />
          ))}
        </Layer>
      </Stage>
    </div>
  )
}

function KpiCard({ label, value, highlight }) {
  return (
    <div className={`bg-white border rounded-xl px-5 py-4 flex flex-col gap-1 ${highlight ? 'border-red-300' : 'border-gray-200'}`}>
      <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</span>
      <span className={`text-3xl font-bold tabular-nums ${highlight ? 'text-red-600' : 'text-gray-900'}`}>
        {value}
      </span>
    </div>
  )
}

function AlertCard({ alert, onDismiss }) {
  const style = ALERT_COLORS[alert.type] || ALERT_COLORS.Queue
  return (
    <div className={`rounded-lg border p-3 ${style.bg} ${style.border}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className={`w-2 h-2 rounded-full flex-shrink-0 mt-0.5 ${style.dot}`} />
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className={`text-xs font-semibold px-1.5 py-0.5 rounded ${style.badge}`}>
                {alert.type}
              </span>
              <span className="text-sm font-medium text-gray-800 truncate">{alert.zone}</span>
            </div>
            <p className="text-xs text-gray-500 mt-0.5">{alert.ts}</p>
          </div>
        </div>
        {/* MOCK: replace onDismiss with POST /store/{slug}/alerts/{id}/resolve */}
        <button
          onClick={() => onDismiss(alert.id)}
          title="Dismiss alert"
          className="text-gray-400 hover:text-gray-600 flex-shrink-0 text-xs leading-none mt-0.5"
        >
          ✕
        </button>
      </div>
    </div>
  )
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function LiveMonitoring() {
  const { slug } = useParams()
  usePageTitle('Live Monitoring')

  const [demoBannerVisible, setDemoBannerVisible] = useState(true)

  // MOCK: replace with API call to GET /store/{slug}/live/summary
  const [kpi] = useState(MOCK_KPI)

  // MOCK: replace with API call to GET /store/{slug}/alerts/active + websocket/polling
  const [alerts, setAlerts] = useState(MOCK_ALERTS_INIT)

  // Live camera health from the edge (Jetson IEP1 → EEP). Polls every 10s.
  const [cameras, setCameras] = useState([])
  useEffect(() => {
    let active = true
    const load = () =>
      getCameraHealth(slug)
        .then(d => {
          if (!active) return
          const now = Date.now()
          setCameras((d?.cameras || []).map(c => {
            const seen = c.last_seen_at ? new Date(c.last_seen_at).getTime() : 0
            const fresh = now - seen < EDGE_ONLINE_WINDOW_MS
            return {
              id: c.camera_id,
              name: c.name,
              online: c.health_status === 'online' && fresh,
              status: c.health_status,
            }
          }))
        })
        .catch(() => {})
    load()
    const t = setInterval(load, 10000)
    return () => { active = false; clearInterval(t) }
  }, [slug])

  // Edge device is "online" if any of its cameras reported online recently.
  const edgeOnline = cameras.some(c => c.online)

  // MOCK: replace with API call to GET /store/{slug}/live/positions
  const [people] = useState(MOCK_PEOPLE)

  const [sections, setSections] = useState([])
  const [selectedSectionId, setSelectedSectionId] = useState(null)
  const [loadingConfig, setLoadingConfig] = useState(true)

  useEffect(() => {
    getActiveVersion(slug)
      .then(v => {
        const secs = v?.sections || []
        setSections(secs)
        const defaultSec = secs.find(s => s.is_default) || secs[0] || null
        setSelectedSectionId(defaultSec?.id || null)
      })
      .catch(() => setSections([]))
      .finally(() => setLoadingConfig(false))
  }, [slug])

  const selectedSection = sections.find(s => s.id === selectedSectionId) || sections[0] || null

  function dismissAlert(id) {
    setAlerts(prev => prev.filter(a => a.id !== id))
  }

  return (
    <div className="page-enter flex flex-col h-full overflow-hidden">

      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <header className="bg-white border-b border-gray-200 px-6 py-4 shrink-0 flex items-center justify-between">
        <div>
          <h1 className="page-title">Live Monitoring</h1>
          <p className="page-subtitle">Real-time multi-camera tracking</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
          <span className="text-xs text-gray-500">Live</span>
        </div>
      </header>

      {/* ── Demo data banner ────────────────────────────────────────────────── */}
      {demoBannerVisible && (
        <div className="bg-amber-50 border-b border-amber-200 text-amber-800 text-xs px-6 py-2 flex items-center justify-between shrink-0">
          <span>Showing demo data — live backend not connected.</span>
          <button onClick={() => setDemoBannerVisible(false)} className="ml-4 text-amber-600 hover:text-amber-900 leading-none">✕</button>
        </div>
      )}

      <div className="flex-1 overflow-auto p-5 space-y-4">

        {/* ── KPI Bar ─────────────────────────────────────────────────────── */}
        {/* MOCK: replace kpi state with API call to GET /store/{slug}/live/summary */}
        {loadingConfig && <StatsSkeleton count={4} />}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <KpiCard label="Total People"   value={kpi.total_people} />
          <KpiCard label="Customers"      value={kpi.customers} />
          <KpiCard label="Staff On Floor" value={kpi.staff_on_floor} />
          <KpiCard label="Active Alerts"  value={kpi.active_alerts} highlight={kpi.active_alerts > 0} />
        </div>

        {/* ── Main Panel ──────────────────────────────────────────────────── */}
        <div className="flex flex-col lg:flex-row gap-4">

          {/* Floor plan — 70% on lg+ */}
          <div className="bg-white border border-gray-200 rounded-xl p-4 flex flex-col min-h-[280px] lg:flex-[0_0_70%]">
            {/* Title row */}
            <div className="flex items-center justify-between shrink-0">
              <h2 className="text-sm font-semibold text-gray-700">
                {selectedSection?.name || 'Floor Plan'}
              </h2>
              <div className="flex items-center gap-4 text-xs text-gray-500">
                <span className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-green-500 inline-block" /> Customer
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-blue-900 inline-block" /> Staff
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-gray-600 inline-block" /> Camera
                </span>
              </div>
            </div>

            {/* Section tab bar — only when multiple sections */}
            <div className="mt-2.5 mb-1 shrink-0">
              <SectionTabs
                sections={sections}
                selectedId={selectedSectionId}
                onChange={setSelectedSectionId}
              />
            </div>

            <div className={`flex-1 min-h-0 ${sections.length > 1 ? '' : 'mt-3'}`}>
              {loadingConfig ? (
                <div className="flex items-center justify-center h-full text-gray-400 text-sm">Loading floor plan…</div>
              ) : (
                <FloorPlanCanvas
                  floorPlan={selectedSection?.floor_plan}
                  zones={selectedSection?.zones || []}
                  obstacles={selectedSection?.obstacles || []}
                  cameraConfigs={selectedSection?.camera_configs || []}
                  people={people}
                />
              )}
            </div>
          </div>

          {/* Alerts feed — 30% on lg+, capped on small screens */}
          <div className="bg-white border border-gray-200 rounded-xl p-4 flex flex-col max-h-[300px] lg:max-h-none lg:flex-1">
            <div className="flex items-center justify-between mb-3 shrink-0">
              <h2 className="text-sm font-semibold text-gray-700">Active Alerts</h2>
              {alerts.length > 0 && (
                <span className="text-xs bg-red-100 text-red-700 font-semibold px-2 py-0.5 rounded-full">
                  {alerts.length}
                </span>
              )}
            </div>
            {/* MOCK: replace alerts state with GET /store/{slug}/alerts/active */}
            <div className="flex-1 overflow-y-auto space-y-2 min-h-0">
              {alerts.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full text-gray-400 text-sm gap-2">
                  <span className="text-2xl">✓</span>
                  <span>No active alerts</span>
                </div>
              ) : (
                alerts.map(a => (
                  <AlertCard key={a.id} alert={a} onDismiss={dismissAlert} />
                ))
              )}
            </div>
          </div>
        </div>

        {/* ── Camera Health Strip ──────────────────────────────────────────── */}
        {/* Live health from the edge (Jetson IEP1 → EEP /vision/camera-health) */}
        <div className="bg-white border border-gray-200 rounded-xl px-5 py-3 flex items-center gap-2 flex-wrap shrink-0">
          <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide mr-2">Camera Status</span>
          {/* Edge device rollup */}
          <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-xs font-semibold mr-1 ${
            edgeOnline
              ? 'bg-green-50 border-green-300 text-green-700'
              : 'bg-gray-50 border-gray-300 text-gray-500'
          }`}>
            <span className={`w-2 h-2 rounded-full ${edgeOnline ? 'bg-green-500 animate-pulse' : 'bg-gray-400'}`} />
            Edge {edgeOnline ? 'Online' : 'Offline'}
          </div>
          {cameras.length === 0 && (
            <span className="text-xs text-gray-400">No cameras reporting yet</span>
          )}
          {cameras.map(cam => (
            <div
              key={cam.id}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-xs font-medium ${
                cam.online
                  ? 'bg-green-50 border-green-200 text-green-700'
                  : 'bg-red-50 border-red-200 text-red-600'
              }`}
            >
              <span className={`w-2 h-2 rounded-full ${cam.online ? 'bg-green-500' : 'bg-red-500'}`} />
              {cam.name}
            </div>
          ))}
        </div>

      </div>
    </div>
  )
}
