import React, { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Stage, Layer, Image as KonvaImage, Line, Circle, Text } from 'react-konva'
import { getActiveVersion } from '../api'

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

// MOCK: replace with API call to GET /store/{slug}/cameras/health
const MOCK_CAMERAS = [
  { id: 'c1', name: 'CAM-01', online: true },
  { id: 'c2', name: 'CAM-02', online: true },
  { id: 'c3', name: 'CAM-03', online: false },
  { id: 'c4', name: 'CAM-04', online: true },
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

  // MOCK: replace with API call to GET /store/{slug}/live/summary
  const [kpi] = useState(MOCK_KPI)

  // MOCK: replace with API call to GET /store/{slug}/alerts/active + websocket/polling
  const [alerts, setAlerts] = useState(MOCK_ALERTS_INIT)

  // MOCK: replace with API call to GET /store/{slug}/cameras/health
  const [cameras] = useState(MOCK_CAMERAS)

  // MOCK: replace with API call to GET /store/{slug}/live/positions
  const [people] = useState(MOCK_PEOPLE)

  const [section, setSection] = useState(null)
  const [loadingConfig, setLoadingConfig] = useState(true)

  useEffect(() => {
    getActiveVersion(slug)
      .then(v => {
        const defaultSec = v?.sections?.find(s => s.is_default) || v?.sections?.[0] || null
        setSection(defaultSec)
      })
      .catch(() => setSection(null))
      .finally(() => setLoadingConfig(false))
  }, [slug])

  function dismissAlert(id) {
    setAlerts(prev => prev.filter(a => a.id !== id))
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">

      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <header className="bg-white border-b border-gray-200 px-6 py-4 shrink-0 flex items-center justify-between">
        <div>
          <h1 className="font-semibold text-gray-900">Live Monitoring</h1>
          <p className="text-xs text-gray-400 mt-0.5">Real-time multi-camera tracking</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
          <span className="text-xs text-gray-500">Live</span>
        </div>
      </header>

      <div className="flex-1 overflow-auto p-5 space-y-4">

        {/* ── KPI Bar ─────────────────────────────────────────────────────── */}
        {/* MOCK: replace kpi state with API call to GET /store/{slug}/live/summary */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <KpiCard label="Total People"   value={kpi.total_people} />
          <KpiCard label="Customers"      value={kpi.customers} />
          <KpiCard label="Staff On Floor" value={kpi.staff_on_floor} />
          <KpiCard label="Active Alerts"  value={kpi.active_alerts} highlight={kpi.active_alerts > 0} />
        </div>

        {/* ── Main Panel ──────────────────────────────────────────────────── */}
        <div className="flex gap-4 min-h-0" style={{ height: 'calc(100vh - 340px)', minHeight: 320 }}>

          {/* Floor plan — 70% */}
          <div className="bg-white border border-gray-200 rounded-xl p-4 flex flex-col" style={{ flex: '0 0 70%' }}>
            <div className="flex items-center justify-between mb-3 shrink-0">
              <h2 className="text-sm font-semibold text-gray-700">
                {section?.name || 'Floor Plan'}
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
            <div className="flex-1 min-h-0">
              {loadingConfig ? (
                <div className="flex items-center justify-center h-full text-gray-400 text-sm">Loading floor plan…</div>
              ) : (
                <FloorPlanCanvas
                  floorPlan={section?.floor_plan}
                  zones={section?.zones || []}
                  obstacles={section?.obstacles || []}
                  cameraConfigs={section?.camera_configs || []}
                  people={people}
                />
              )}
            </div>
          </div>

          {/* Alerts feed — 30% */}
          <div className="bg-white border border-gray-200 rounded-xl p-4 flex flex-col" style={{ flex: '0 0 calc(30% - 1rem)' }}>
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
        {/* MOCK: replace cameras state with GET /store/{slug}/cameras/health */}
        <div className="bg-white border border-gray-200 rounded-xl px-5 py-3 flex items-center gap-2 flex-wrap shrink-0">
          <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide mr-2">Camera Status</span>
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
