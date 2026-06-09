import React from 'react'
import { MapPin } from 'lucide-react'

// Read-only punch-in station of the active version. punch = GET /punch-station, or
// null when not configured (404) / unavailable.
export default function PunchPanel({ punch }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-1.5">
          <MapPin size={14} className="text-gray-400" /> Punch-in Machine
        </h3>
        <span className="text-[10px] text-gray-400">Edit via the Edit menu</span>
      </div>
      {!punch ? (
        <div className="text-xs text-gray-400">
          Punch machine not configured.
          <span className="text-gray-500"> Use “Edit Punch Machine” to set it.</span>
        </div>
      ) : (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
          <div className="flex gap-1.5"><dt className="text-gray-400 text-xs">Camera:</dt><dd className="text-gray-700 truncate">{punch.camera_config_name || '—'}</dd></div>
          <div className="flex gap-1.5"><dt className="text-gray-400 text-xs">Radius:</dt><dd className="text-gray-700">{punch.radius_m} m</dd></div>
        </dl>
      )}
    </div>
  )
}
