import React from 'react'
import { PanelCard, shortId } from './reconShared'

// (camera, local) → global#, from persisted global_local_mapping. Needs NO trace.
export default function LocalGlobalPanel({ mapping = [], identity, camLabel }) {
  return (
    <PanelCard title="Local → Global" subtitle={`${mapping.length} links`}>
      <div className="overflow-y-auto" style={{ maxHeight: 240 }}>
        {!mapping.length ? (
          <div className="py-6 text-center text-sm text-gray-400">No links yet</div>
        ) : (
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-white border-b border-gray-100">
              <tr>{['Camera', 'Local', 'Global', 'Active'].map((h) => <th key={h} className="px-2 py-1.5 text-left font-semibold text-gray-500">{h}</th>)}</tr>
            </thead>
            <tbody>
              {mapping.map((m, i) => {
                const id = identity.get(m.global_id)
                return (
                  <tr key={`${m.camera_id}-${m.local_id}-${i}`} className={i % 2 ? 'bg-gray-50' : 'bg-white'}>
                    <td className="px-2 py-1 text-gray-600">{camLabel(m.camera_id)}</td>
                    <td className="px-2 py-1 font-mono text-gray-500">{shortId(m.local_id)}</td>
                    <td className="px-2 py-1 font-mono font-semibold" style={{ color: id.color }}>#{id.number}</td>
                    <td className="px-2 py-1 text-gray-500">{m.is_active ? '●' : '○'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </PanelCard>
  )
}
