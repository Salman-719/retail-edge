import React from 'react'

export const shortId = (v) => (v ? String(v).slice(0, 8) : '—')
export const pct = (v) => (v == null ? '—' : `${(v * 100).toFixed(0)}%`)

// Shown when the dev trace was off / no rows (panels are trace-dependent).
export function TraceOff() {
  return (
    <div className="py-6 text-center text-sm text-gray-400 bg-gray-50 rounded-lg">
      Enable the trace (start a run from this page) to see merge reasoning for the selected batch.
    </div>
  )
}

export function PanelCard({ title, subtitle, children }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-700">{title}</h3>
        {subtitle && <span className="text-xs text-gray-400">{subtitle}</span>}
      </div>
      {children}
    </div>
  )
}
