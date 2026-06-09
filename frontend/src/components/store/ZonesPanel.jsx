import React from 'react'
import { ZONE_COLORS, zoneAreaM2 } from './storeSetup'

// Read-only zones: name, type, area m², and alert-rule count (CAT D). ruleCounts
// is null when D is unavailable → the count column is omitted.
export default function ZonesPanel({ zones = [], ppm, ruleCounts }) {
  const hasRules = !!ruleCounts
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
      <h3 className="text-sm font-semibold text-gray-700 mb-3">
        Zones <span className="text-gray-400 font-normal">({zones.length})</span>
      </h3>
      {zones.length === 0 ? (
        <p className="text-xs text-gray-400">No zones configured.</p>
      ) : (
        <div className="space-y-2">
          {zones.map((z) => {
            const area = zoneAreaM2(z.points, ppm)
            return (
              <div key={z.id} className="flex items-center gap-2 text-sm">
                <span className="w-3 h-3 rounded-sm shrink-0" style={{ background: ZONE_COLORS[z.type] || '#888' }} />
                <span className="text-gray-700 truncate">{z.name}</span>
                <span className="text-gray-400 text-xs capitalize">{z.type}</span>
                <span className="text-gray-400 text-xs ml-auto shrink-0">
                  {area != null ? `${area.toFixed(1)} m²` : '—'}
                </span>
                {hasRules && (
                  <span
                    title="Alert rules targeting this zone"
                    className="text-[10px] bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded shrink-0"
                  >
                    {ruleCounts[z.id] || 0} {(ruleCounts[z.id] || 0) === 1 ? 'rule' : 'rules'}
                  </span>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
