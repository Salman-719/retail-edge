import React, { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'

// Collapsible version history with restore (existing reactivate logic, passed in).
export default function VersionHistory({ versions = [], onRestore, restoringId, error, onClearError }) {
  const [open, setOpen] = useState(false)
  if (!versions.length) return null

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
      <button onClick={() => setOpen((o) => !o)} className="w-full flex items-center gap-2 text-sm font-semibold text-gray-700">
        {open ? <ChevronDown size={16} className="text-gray-400" /> : <ChevronRight size={16} className="text-gray-400" />}
        Version History <span className="text-gray-400 font-normal">({versions.length})</span>
      </button>
      {open && (
        <div className="mt-3">
          {error && (
            <div className="mb-3 p-2 bg-red-50 border border-red-200 rounded text-xs text-red-700 flex items-center justify-between">
              <span>{error}</span>
              <button onClick={onClearError} className="ml-2 text-red-400 hover:text-red-600">✕</button>
            </div>
          )}
          <div className="divide-y divide-gray-100">
            {versions.map((v) => (
              <div key={v.id} className="py-2.5">
                <div className="flex items-center gap-3 text-sm">
                  <span className={`px-2 py-0.5 rounded-full text-xs font-medium shrink-0 ${
                    v.status === 'active' ? 'bg-green-100 text-green-700' :
                    v.status === 'pending_activation' ? 'bg-yellow-100 text-yellow-700' :
                    v.status === 'draft' ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-500'
                  }`}>
                    {v.status === 'pending_activation' ? 'Scheduled' : v.status}
                  </span>
                  <span className="text-gray-700 font-medium truncate">{v.label || '(unlabeled)'}</span>
                  <span className="text-gray-400 text-xs ml-auto shrink-0">
                    {v.active_from ? new Date(v.active_from).toLocaleDateString() : new Date(v.created_at).toLocaleDateString()}
                  </span>
                  {v.status === 'archived' && onRestore && (
                    <button onClick={() => onRestore(v.id)} disabled={restoringId === v.id}
                      className="text-xs text-blue-600 hover:text-blue-800 shrink-0 disabled:opacity-50 font-medium">
                      {restoringId === v.id ? 'Restoring…' : 'Restore'}
                    </button>
                  )}
                </div>
                {v.status === 'pending_activation' && v.activate_at && (
                  <p className="text-xs text-yellow-600 mt-1 pl-0.5">Activates {new Date(v.activate_at).toLocaleString()}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
