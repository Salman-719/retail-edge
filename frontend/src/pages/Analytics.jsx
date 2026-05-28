import React, { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  LineChart, Line, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import { Stage, Layer, Image as KonvaImage, Rect } from 'react-konva'
import { getActiveVersion } from '../api'
import { usePageTitle } from '../components/PageMeta'
import SectionTabs from '../components/SectionTabs'

// ─── Mock data ────────────────────────────────────────────────────────────────

// MOCK: replace with GET /store/{slug}/analytics/zone-traffic?from=...&to=...
function buildZoneTrafficMock() {
  const zones = ['Entrance', 'Checkout', 'Produce']
  const peaks = { Entrance: [8, 12, 17], Checkout: [11, 13, 18], Produce: [10, 14, 16] }
  return Array.from({ length: 24 }, (_, h) => {
    const row = { hour: `${String(h).padStart(2, '0')}:00` }
    zones.forEach(z => {
      const base = 5
      const bump = peaks[z].reduce((acc, p) => acc + Math.max(0, 30 - Math.abs(h - p) * 6), 0)
      row[z] = Math.round(base + bump + Math.random() * 8)
    })
    return row
  })
}

// MOCK: replace with GET /store/{slug}/analytics/trends?from=...&to=...
function buildHeadcountMock() {
  const today = new Date()
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(today)
    d.setDate(today.getDate() - (6 - i))
    return {
      day: d.toLocaleDateString('en-US', { weekday: 'short', month: 'numeric', day: 'numeric' }),
      Headcount: Math.round(120 + Math.random() * 180),
    }
  })
}

// MOCK: replace with GET /store/{slug}/analytics/classification?from=...&to=...
const MOCK_CLASSIFICATION = [
  { name: 'Customers', value: 80 },
  { name: 'Staff',     value: 20 },
]

// MOCK: replace with GET /store/{slug}/analytics/heatmap?from=...&to=...
// Grid is COLS × ROWS cells; intensity 0–1
const HEATMAP_COLS = 12
const HEATMAP_ROWS = 8
function buildHeatmapMock() {
  return Array.from({ length: HEATMAP_ROWS }, (_, r) =>
    Array.from({ length: HEATMAP_COLS }, (_, c) => {
      // Simulate two hotspots: entrance (top-left) and checkout (bottom-right)
      const d1 = Math.hypot(c - 1, r - 1) / 6
      const d2 = Math.hypot(c - 10, r - 6) / 5
      const d3 = Math.hypot(c - 6, r - 3) / 7
      return Math.min(1, 0.8 / (d1 + 0.3) + 0.6 / (d2 + 0.3) + 0.4 / (d3 + 0.3))
    })
  )
}

// ─── Palette helpers ──────────────────────────────────────────────────────────

const ZONE_LINE_COLORS = ['#3b82f6', '#f59e0b', '#10b981']
const DONUT_COLORS     = ['#3b82f6', '#1B3A5C']

function heatColor(intensity) {
  // blue (low) → yellow → red (high)
  const t = Math.min(1, Math.max(0, intensity))
  if (t < 0.5) {
    const s = t * 2
    const r = Math.round(s * 255)
    const g = Math.round(s * 200)
    const b = Math.round(255 - s * 255)
    return `rgba(${r},${g},${b},0.55)`
  }
  const s = (t - 0.5) * 2
  const r = 255
  const g = Math.round(200 - s * 200)
  const b = 0
  return `rgba(${r},${g},${b},0.6)`
}

// ─── Section wrapper ──────────────────────────────────────────────────────────

function Section({ title, children }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5">
      <h2 className="text-sm font-semibold text-gray-700 mb-4">{title}</h2>
      {children}
    </div>
  )
}

// ─── Floor plan image hook ────────────────────────────────────────────────────

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

// ─── Heatmap canvas ───────────────────────────────────────────────────────────

function HeatmapCanvas({ floorPlan, grid }) {
  const containerRef = useRef(null)
  const [size, setSize] = useState({ w: 800, h: 400 })
  const bgImage = useImage(floorPlan?.display_url)

  useEffect(() => {
    if (!containerRef.current) return
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }))
    ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [])

  if (!floorPlan?.image_uploaded) {
    return (
      <div className="flex items-center justify-center h-56 bg-gray-100 rounded-lg text-gray-400 text-sm">
        No floor plan configured — heatmap requires an active store configuration
      </div>
    )
  }

  const imgW = floorPlan.width_px || 1
  const imgH = floorPlan.height_px || 1
  const scale = Math.min(size.w / imgW, size.h / imgH)
  const stageW = Math.round(imgW * scale)
  const stageH = Math.round(imgH * scale)
  const cellW  = stageW / HEATMAP_COLS
  const cellH  = stageH / HEATMAP_ROWS

  return (
    <div ref={containerRef} className="w-full">
      <Stage width={stageW} height={stageH}>
        <Layer>
          {bgImage && <KonvaImage image={bgImage} width={stageW} height={stageH} />}
          {/* MOCK: replace grid with GET /store/{slug}/analytics/heatmap */}
          {grid.map((row, r) =>
            row.map((intensity, c) => (
              <Rect
                key={`${r}-${c}`}
                x={c * cellW} y={r * cellH}
                width={cellW} height={cellH}
                fill={heatColor(intensity)}
              />
            ))
          )}
        </Layer>
      </Stage>
    </div>
  )
}

// ─── Heatmap legend ───────────────────────────────────────────────────────────

function HeatmapLegend() {
  return (
    <div className="flex items-center gap-2 mt-3">
      <span className="text-xs text-gray-500">Low</span>
      <div className="flex-1 h-3 rounded" style={{
        background: 'linear-gradient(to right, rgba(0,0,255,0.5), rgba(255,200,0,0.55), rgba(255,0,0,0.6))',
      }} />
      <span className="text-xs text-gray-500">High</span>
    </div>
  )
}

// ─── Donut label ─────────────────────────────────────────────────────────────

function DonutLabel({ cx, cy, midAngle, innerRadius, outerRadius, percent }) {
  const RADIAN = Math.PI / 180
  const r  = innerRadius + (outerRadius - innerRadius) * 0.5
  const x  = cx + r * Math.cos(-midAngle * RADIAN)
  const y  = cy + r * Math.sin(-midAngle * RADIAN)
  return (
    <text x={x} y={y} fill="#fff" textAnchor="middle" dominantBaseline="central" fontSize={13} fontWeight={600}>
      {`${(percent * 100).toFixed(0)}%`}
    </text>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function Analytics() {
  const { slug } = useParams()
  usePageTitle('Analytics')

  const [demoBannerVisible, setDemoBannerVisible] = useState(true)

  const today = new Date().toISOString().slice(0, 10)
  const weekAgo = new Date(Date.now() - 6 * 86400000).toISOString().slice(0, 10)
  const [from, setFrom] = useState(weekAgo)
  const [to,   setTo]   = useState(today)
  const [activePreset, setActivePreset] = useState('7 days')

  const PRESETS = [
    { label: 'Today',   days: 0 },
    { label: '7 days',  days: 6 },
    { label: '30 days', days: 29 },
    { label: '90 days', days: 89 },
  ]

  function applyPreset(preset) {
    const end = new Date()
    const start = new Date(Date.now() - preset.days * 86400000)
    setTo(end.toISOString().slice(0, 10))
    setFrom(start.toISOString().slice(0, 10))
    setActivePreset(preset.label)
  }

  // MOCK: replace with GET /store/{slug}/analytics/zone-traffic
  const [zoneTraffic]    = useState(buildZoneTrafficMock)
  // MOCK: replace with GET /store/{slug}/analytics/trends
  const [headcount]      = useState(buildHeadcountMock)
  // MOCK: replace with GET /store/{slug}/analytics/classification
  const [classification] = useState(MOCK_CLASSIFICATION)
  // MOCK: replace with GET /store/{slug}/analytics/heatmap
  const [heatGrid]       = useState(buildHeatmapMock)

  const [sections, setSections] = useState([])
  const [selectedSectionId, setSelectedSectionId] = useState(null)
  const [floorPlan, setFloorPlan] = useState(null)
  const [loadingFp, setLoadingFp] = useState(true)

  useEffect(() => {
    getActiveVersion(slug)
      .then(v => {
        const secs = v?.sections || []
        setSections(secs)
        const defaultSec = secs.find(s => s.is_default) || secs[0] || null
        setSelectedSectionId(defaultSec?.id || null)
        setFloorPlan(defaultSec?.floor_plan || null)
      })
      .catch(() => { setSections([]); setFloorPlan(null) })
      .finally(() => setLoadingFp(false))
  }, [slug])

  // When the selected section changes, sync the floor plan
  useEffect(() => {
    const sec = sections.find(s => s.id === selectedSectionId)
    if (sec) setFloorPlan(sec.floor_plan || null)
  }, [selectedSectionId, sections])

  const selectedSection = sections.find(s => s.id === selectedSectionId) || sections[0] || null

  return (
    <div className="page-enter flex flex-col h-full overflow-hidden">

      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <header className="bg-white border-b border-gray-200 px-6 py-4 shrink-0">
        <h1 className="page-title">Analytics</h1>
        <p className="page-subtitle">Historical traffic patterns and zone performance</p>
      </header>

      {/* ── Demo data banner ────────────────────────────────────────────────── */}
      {demoBannerVisible && (
        <div className="bg-amber-50 border-b border-amber-200 text-amber-800 text-xs px-6 py-2 flex items-center justify-between shrink-0">
          <span>Showing demo data — live backend not connected.</span>
          <button onClick={() => setDemoBannerVisible(false)} className="ml-4 text-amber-600 hover:text-amber-900 leading-none">✕</button>
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-5 space-y-5">

        {/* ── Date range picker ────────────────────────────────────────────── */}
        <div className="bg-white border border-gray-200 rounded-xl px-5 py-4 space-y-3">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-medium text-gray-500 shrink-0">Quick select</span>
            {PRESETS.map(preset => (
              <button
                key={preset.label}
                onClick={() => applyPreset(preset)}
                className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                  activePreset === preset.label
                    ? 'bg-blue-600 text-white border-blue-600'
                    : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'
                }`}
              >
                {preset.label}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-4 flex-wrap">
            <span className="text-sm font-medium text-gray-600 shrink-0">Date range</span>
            <div className="flex items-center gap-2">
              <label className="text-xs text-gray-500">From</label>
              <input
                type="date"
                value={from}
                max={to}
                onChange={e => { setFrom(e.target.value); setActivePreset(null) }}
                className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div className="flex items-center gap-2">
              <label className="text-xs text-gray-500">To</label>
              <input
                type="date"
                value={to}
                min={from}
                max={today}
                onChange={e => { setTo(e.target.value); setActivePreset(null) }}
                className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            {/* MOCK: wire date range into API calls once backend is available */}
            <span className="text-xs text-gray-400 italic">
              (date range applied when API is connected)
            </span>
          </div>
        </div>

        {/* ── Section selector ─────────────────────────────────────────────── */}
        <SectionTabs
          sections={sections}
          selectedId={selectedSectionId}
          onChange={setSelectedSectionId}
        />

        {/* ── Zone Traffic line chart ──────────────────────────────────────── */}
        {/* MOCK: replace zoneTraffic with GET /store/{slug}/analytics/zone-traffic */}
        <Section title={`Zone Traffic — ${selectedSection?.name || 'Hourly Foot Traffic'}`}>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={zoneTraffic} margin={{ top: 4, right: 24, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis
                dataKey="hour"
                tick={{ fontSize: 11 }}
                interval={2}
                label={{ value: 'Hour of Day', position: 'insideBottom', offset: -2, fontSize: 11, fill: '#6b7280' }}
              />
              <YAxis
                tick={{ fontSize: 11 }}
                label={{ value: 'People', angle: -90, position: 'insideLeft', offset: 10, fontSize: 11, fill: '#6b7280' }}
              />
              <Tooltip
                contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }}
                labelFormatter={l => `Hour: ${l}`}
              />
              <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />
              {['Entrance', 'Checkout', 'Produce'].map((z, i) => (
                <Line
                  key={z}
                  type="monotone"
                  dataKey={z}
                  stroke={ZONE_LINE_COLORS[i]}
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4 }}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </Section>

        {/* ── Headcount trend bar chart + donut ───────────────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">

          {/* Bar chart — 2/3 width */}
          {/* MOCK: replace headcount with GET /store/{slug}/analytics/trends */}
          <div className="lg:col-span-2">
            <Section title="Daily Headcount — Past 7 Days">
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={headcount} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis
                    dataKey="day"
                    tick={{ fontSize: 11 }}
                    label={{ value: 'Date', position: 'insideBottom', offset: -2, fontSize: 11, fill: '#6b7280' }}
                  />
                  <YAxis
                    tick={{ fontSize: 11 }}
                    label={{ value: 'People', angle: -90, position: 'insideLeft', offset: 10, fontSize: 11, fill: '#6b7280' }}
                  />
                  <Tooltip
                    contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }}
                  />
                  <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />
                  <Bar dataKey="Headcount" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </Section>
          </div>

          {/* Donut — 1/3 width */}
          {/* MOCK: replace classification with GET /store/{slug}/analytics/classification */}
          <div className="lg:col-span-1">
            <Section title="People Classification">
              <ResponsiveContainer width="100%" height={240}>
                <PieChart>
                  <Pie
                    data={classification}
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={90}
                    dataKey="value"
                    labelLine={false}
                    label={DonutLabel}
                  >
                    {classification.map((_, i) => (
                      <Cell key={i} fill={DONUT_COLORS[i]} />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(v, n) => [`${v}%`, n]}
                    contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }}
                  />
                  <Legend
                    wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
                    formatter={(value, entry) => (
                      <span style={{ color: '#374151' }}>{value} ({entry.payload.value}%)</span>
                    )}
                  />
                </PieChart>
              </ResponsiveContainer>
            </Section>
          </div>
        </div>

        {/* ── Heatmap ──────────────────────────────────────────────────────── */}
        {/* MOCK: replace heatGrid with GET /store/{slug}/analytics/heatmap */}
        <Section title={`Dwell-Time Heatmap — ${selectedSection?.name || ''}`}>
          {loadingFp ? (
            <div className="skeleton h-48 w-full rounded-lg" />
          ) : (
            <>
              <HeatmapCanvas floorPlan={floorPlan} grid={heatGrid} />
              <HeatmapLegend />
            </>
          )}
        </Section>

      </div>
    </div>
  )
}
