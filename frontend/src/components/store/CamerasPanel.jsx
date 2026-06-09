import React, { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'

// Read-only camera list. Live dot from F2 (cameraStatusById) — omitted entirely
// when F2 is unavailable (cameraStatusById null).
export default function CamerasPanel({ cameras = [], cameraStatusById }) {
  const [open, setOpen] = useState(null)
  const hasLive = !!cameraStatusById

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
      <h3 className="text-sm font-semibold text-gray-700 mb-3">
        Cameras <span className="text-gray-400 font-normal">({cameras.length})</span>
      </h3>
      {cameras.length === 0 ? (
        <p className="text-xs text-gray-400">No cameras configured.</p>
      ) : (
        <div className="space-y-1">
          {cameras.map((cc) => {
            const live = hasLive ? cameraStatusById[cc.physical_camera_id] : null
            const expanded = open === cc.id
            return (
              <div key={cc.id} className="rounded border border-gray-100 text-sm">
                <button onClick={() => setOpen(expanded ? null : cc.id)} className="w-full flex items-center gap-2 px-3 py-2 text-left">
                  {expanded ? <ChevronDown size={14} className="text-gray-400 shrink-0" /> : <ChevronRight size={14} className="text-gray-400 shrink-0" />}
                  {hasLive && (
                    <span
                      title={live ? (live.online ? 'online' : live.status) : 'unknown'}
                      className={`w-2 h-2 rounded-full shrink-0 ${live?.online ? 'bg-green-500' : live && live.status !== 'unknown' ? 'bg-amber-500' : 'bg-gray-300'}`}
                    />
                  )}
                  <span className="text-gray-700 font-medium truncate">{cc.physical_camera_name}</span>
                  <span className="text-gray-400 text-xs capitalize ml-auto">{cc.status}</span>
                </button>
                {expanded && (
                  <dl className="border-t border-gray-100 px-3 py-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                    <Detail label="Status" value={cc.status} />
                    {hasLive && <Detail label="Live" value={live ? (live.online ? 'online' : live.status) : 'unknown'} />}
                    <Detail label="Height" value={cc.height_meters != null ? `${cc.height_meters} m` : '—'} />
                    <Detail label="Target FPS" value={cc.target_fps ?? '—'} />
                    <Detail label="Position" value={cc.position_x != null ? `${Math.round(cc.position_x)}, ${Math.round(cc.position_y)}` : '—'} />
                    <Detail label="FOV" value={cc.fov_deg != null ? `${cc.fov_deg}°` : '—'} />
                    <div className="col-span-2"><Detail label="Stream" value={cc.stream_url || '—'} mono /></div>
                  </dl>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function Detail({ label, value, mono }) {
  return (
    <div className="flex gap-1.5">
      <dt className="text-gray-400">{label}:</dt>
      <dd className={`text-gray-700 truncate ${mono ? 'font-mono' : ''}`}>{value}</dd>
    </div>
  )
}
