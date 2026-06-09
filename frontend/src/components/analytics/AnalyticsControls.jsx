import React, { useState } from 'react'
import { MultiSelect } from './widgetParts'

const PRESETS = [
  { label: 'Today', days: 0 },
  { label: '7 days', days: 6 },
  { label: '30 days', days: 29 },
  { label: '90 days', days: 89 },
]

const GRAINS = ['auto', 'day', 'week', 'month']

function isoDay(d) {
  return d.toISOString().slice(0, 10)
}

export default function AnalyticsControls({
  from, to, granularity, zoneOptions, zoneIds,
  onRangeChange, onGranularityChange, onZoneIdsChange,
}) {
  const [activePreset, setActivePreset] = useState('7 days')
  const today = isoDay(new Date())

  function applyPreset(p) {
    const end = new Date()
    const start = new Date(Date.now() - p.days * 86400000)
    onRangeChange(isoDay(start), isoDay(end))
    setActivePreset(p.label)
  }

  return (
    <div className="bg-white border border-gray-200 rounded-xl px-5 py-4 space-y-3 sticky top-0 z-10">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs font-medium text-gray-500 shrink-0">Quick select</span>
        {PRESETS.map((p) => (
          <button
            key={p.label}
            onClick={() => applyPreset(p)}
            className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
              activePreset === p.label
                ? 'bg-blue-600 text-white border-blue-600'
                : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>

      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <label className="text-xs text-gray-500">From</label>
          <input
            type="date" value={from} max={to}
            onChange={(e) => { onRangeChange(e.target.value, to); setActivePreset(null) }}
            className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-gray-500">To</label>
          <input
            type="date" value={to} min={from} max={today}
            onChange={(e) => { onRangeChange(from, e.target.value); setActivePreset(null) }}
            className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div className="flex items-center gap-2">
          <label className="text-xs text-gray-500">Granularity</label>
          <select
            value={granularity}
            onChange={(e) => onGranularityChange(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 capitalize"
          >
            {GRAINS.map((g) => <option key={g} value={g}>{g}</option>)}
          </select>
        </div>

        <MultiSelect label="Zones" options={zoneOptions} selected={zoneIds} onChange={onZoneIdsChange} />
      </div>
    </div>
  )
}
