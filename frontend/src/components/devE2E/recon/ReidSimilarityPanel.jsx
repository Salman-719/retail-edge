import React from 'react'
import { PanelCard, TraceOff, shortId } from './reconShared'

// Cross-camera ReID fallback cosines vs threshold (trace reid_fallback). Within-
// camera reid_sim is shown live on each feed's bbox labels (VD2).
export default function ReidSimilarityPanel({ events = [], camLabel, hasTrace }) {
  const reid = events.filter((e) => e.event_type === 'reid_fallback').map((e) => e.detail)
  return (
    <PanelCard title="ReID Similarity (cross-camera)" subtitle="within-camera sims shown on feeds">
      {!hasTrace ? <TraceOff /> : !reid.length ? (
        <div className="py-6 text-center text-sm text-gray-400">No appearance-fallback comparisons this batch</div>
      ) : (
        <div className="overflow-y-auto" style={{ maxHeight: 240 }}>
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-white border-b border-gray-100">
              <tr>{['Pair', 'Cosine', 'Threshold', 'Result'].map((h) => <th key={h} className="px-2 py-1.5 text-left font-semibold text-gray-500">{h}</th>)}</tr>
            </thead>
            <tbody>
              {reid.map((d, i) => (
                <tr key={i} className={i % 2 ? 'bg-gray-50' : 'bg-white'}>
                  <td className="px-2 py-1 font-mono text-gray-500">{camLabel(d.cam_a)}:{shortId(d.local_a)} → {camLabel(d.cam_b)}:{shortId(d.local_b)}</td>
                  <td className="px-2 py-1 font-mono" style={{ color: d.matched ? '#16a34a' : '#dc2626' }}>{Number(d.cosine).toFixed(3)}</td>
                  <td className="px-2 py-1 font-mono text-gray-500">{Number(d.threshold).toFixed(2)}</td>
                  <td className="px-2 py-1">{d.matched ? <span className="text-green-700">✓ matched</span> : <span className="text-red-600">✗ below</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PanelCard>
  )
}
