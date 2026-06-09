import React from 'react'
import { Clock } from 'lucide-react'
import { DAY_LABELS, formatTime } from './storeSetup'

// Read-only 7-day operating hours (C2). hours = GET /operating-hours { days: [...] }.
// Null when C2 unavailable → a graceful "unavailable" note.
export default function SchedulePanel({ hours }) {
  const byDay = {}
  for (const d of hours?.days || []) byDay[d.day_of_week] = d

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-1.5">
          <Clock size={14} className="text-gray-400" /> Operating Hours
        </h3>
        <span className="text-[10px] text-gray-400">Edit via the Edit menu</span>
      </div>
      {!hours ? (
        <p className="text-xs text-gray-400">Schedule unavailable.</p>
      ) : (
        <div className="space-y-1">
          {DAY_LABELS.map((label, dow) => {
            const d = byDay[dow]
            const isOpen = d?.is_open && d.open_time && d.close_time
            return (
              <div key={dow} className="flex items-center justify-between text-sm py-0.5">
                <span className="text-gray-600 w-10">{label}</span>
                {isOpen ? (
                  <span className="text-gray-700">{formatTime(d.open_time)} – {formatTime(d.close_time)}</span>
                ) : (
                  <span className="text-gray-400">Closed</span>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
