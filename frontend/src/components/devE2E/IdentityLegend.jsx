import React from 'react'
import { ZONE_COLORS } from '../store/storeSetup'

// One key for the whole screen (VD2): zone colors, camera colors, global numbers.
export default function IdentityLegend({ identity, camColorById = {}, camLabelById = {}, zoneTypes = [] }) {
  const globals = identity.entries()
  const Swatch = ({ color, label }) => (
    <span className="inline-flex items-center gap-1 text-xs text-gray-600">
      <span className="w-3 h-3 rounded-sm" style={{ background: color }} />{label}
    </span>
  )
  return (
    <div className="bg-white border border-gray-200 rounded-xl px-4 py-3 flex flex-wrap items-center gap-x-5 gap-y-2">
      <span className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">Legend</span>
      {Object.entries(camColorById).map(([cid, color]) => <Swatch key={cid} color={color} label={camLabelById[cid] || 'cam'} />)}
      {zoneTypes.map((t) => <Swatch key={t} color={ZONE_COLORS[t] || '#888'} label={t} />)}
      <span className="inline-flex items-center gap-1.5 flex-wrap">
        {globals.length === 0 ? (
          <span className="text-xs text-gray-400">No global IDs yet</span>
        ) : globals.map((g) => (
          <span key={g.global_id} className="inline-flex items-center justify-center w-5 h-5 rounded-full text-[10px] font-bold text-white" style={{ background: g.color }} title={g.global_id}>{g.number}</span>
        ))}
      </span>
      <span className="text-[11px] text-gray-400">✓ matched · ✗ pending</span>
    </div>
  )
}
