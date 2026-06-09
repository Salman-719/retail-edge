import React from 'react'
import { PanelCard, TraceOff, shortId, pct } from './reconShared'

// "Why these merged / why ambiguous" — trace spatial_vote events grouped by pair.
export default function MergeDecisionPanel({ events = [], camLabel, hasTrace }) {
  const votes = events.filter((e) => e.event_type === 'spatial_vote').map((e) => e.detail)
  const byPair = {}
  for (const v of votes) {
    const k = `${v.cam_a}|${v.cam_b}`
    ;(byPair[k] ??= []).push(v)
  }
  return (
    <PanelCard title="Merge Decisions" subtitle={`${votes.length} candidates`}>
      {!hasTrace ? <TraceOff /> : !votes.length ? (
        <div className="py-6 text-center text-sm text-gray-400">No spatial-vote candidates this batch</div>
      ) : (
        <div className="space-y-3 overflow-y-auto" style={{ maxHeight: 240 }}>
          {Object.entries(byPair).map(([k, list]) => {
            const [ca, cb] = k.split('|')
            return (
              <div key={k}>
                <div className="text-xs font-medium text-gray-500 mb-1">{camLabel(ca)} ↔ {camLabel(cb)}</div>
                <table className="w-full text-xs">
                  <tbody>
                    {list.map((v, i) => (
                      <tr key={i} className="border-t border-gray-50">
                        <td className="px-2 py-1 font-mono text-gray-500">{shortId(v.local_a)} → {shortId(v.local_b)}</td>
                        <td className="px-2 py-1 text-right text-gray-700">vr {pct(v.vote_rate)}</td>
                        <td className="px-2 py-1 text-right text-gray-500">{v.votes}/{v.co_visible} votes</td>
                        <td className="px-2 py-1 text-right">
                          <span className={`text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded ${v.class === 'confirmed' ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-700'}`}>{v.class}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          })}
        </div>
      )}
    </PanelCard>
  )
}
