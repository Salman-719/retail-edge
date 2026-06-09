import React from 'react'
import { PanelCard, TraceOff } from './reconShared'

// "Why this camera's position won" — trace selection events + their components.
export default function SelectionScorePanel({ events = [], camLabel, identity, hasTrace }) {
  const sel = events.filter((e) => e.event_type === 'selection').map((e) => e.detail)
  return (
    <PanelCard title="Selection Scores" subtitle={`${sel.length} positions`}>
      {!hasTrace ? <TraceOff /> : !sel.length ? (
        <div className="py-6 text-center text-sm text-gray-400">No canonical positions this batch</div>
      ) : (
        <div className="overflow-y-auto" style={{ maxHeight: 240 }}>
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-white border-b border-gray-100">
              <tr>{['Global', 'Source', 'Score', 'Area', 'Conf'].map((h) => <th key={h} className="px-2 py-1.5 text-left font-semibold text-gray-500">{h}</th>)}</tr>
            </thead>
            <tbody>
              {sel.map((d, i) => {
                const id = identity.get(d.global_id)
                const c = d.components || {}
                return (
                  <tr key={i} className={i % 2 ? 'bg-gray-50' : 'bg-white'}>
                    <td className="px-2 py-1 font-mono font-semibold" style={{ color: id.color }}>#{id.number}</td>
                    <td className="px-2 py-1 text-gray-600">{camLabel(d.source_camera)}</td>
                    <td className="px-2 py-1 font-mono text-gray-700">{Number(d.score).toFixed(3)}</td>
                    <td className="px-2 py-1 text-gray-500" title={`weight ${c.weight_area ?? '—'}`}>{c.normalized_area != null ? Number(c.normalized_area).toFixed(3) : '—'}</td>
                    <td className="px-2 py-1 text-gray-500" title={`weight ${c.weight_confidence ?? '—'}`}>{c.bbox_confidence != null ? Number(c.bbox_confidence).toFixed(2) : '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </PanelCard>
  )
}
