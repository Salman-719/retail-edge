import React, { useEffect, useState } from 'react'
import { getAlertHistory } from '../../api'
import { SEVERITY, SEVERITY_ORDER, ALERT_TYPE_LABEL, RULE_TYPES } from './alertMeta'
import { TableSkeleton } from '../Skeletons'

const PAGE = 50
const RESOLUTIONS = ['auto_detected', 'manual_dismiss']
// History filters by the fired-alert type, which collapses both staff_absence_* rules.
const ALERT_TYPES = ['staff_absence', 'queue_buildup', 'camera_offline', 'camera_degraded']

export default function AlertHistoryTable({ slug }) {
  const [filters, setFilters] = useState({ from: '', to: '', type: '', severity: '', resolution: '' })
  const [offset, setOffset] = useState(0)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true); setError(null)
    const params = { limit: PAGE, offset }
    for (const [k, v] of Object.entries(filters)) if (v) params[k] = v
    getAlertHistory(slug, params)
      .then((d) => { if (!cancelled) setData(d) })
      .catch((e) => { if (!cancelled) { setError(e); setData(null) } })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [slug, filters, offset])

  const setFilter = (k, v) => { setFilters((f) => ({ ...f, [k]: v })); setOffset(0) }
  const rows = data?.alerts || []
  const total = data?.total || 0

  const Sel = ({ k, options, label }) => (
    <select
      value={filters[k]} onChange={(e) => setFilter(k, e.target.value)}
      className="border border-gray-300 rounded-lg px-2 py-1.5 text-xs text-gray-700"
    >
      <option value="">{label}</option>
      {options.map((o) => <option key={o} value={o}>{o}</option>)}
    </select>
  )

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 flex-wrap">
        <input type="date" value={filters.from} max={filters.to || undefined}
          onChange={(e) => setFilter('from', e.target.value)}
          className="border border-gray-300 rounded-lg px-2 py-1.5 text-xs" />
        <span className="text-gray-400 text-xs">to</span>
        <input type="date" value={filters.to} min={filters.from || undefined}
          onChange={(e) => setFilter('to', e.target.value)}
          className="border border-gray-300 rounded-lg px-2 py-1.5 text-xs" />
        <Sel k="type" options={ALERT_TYPES} label="All types" />
        <Sel k="severity" options={SEVERITY_ORDER} label="All severities" />
        <Sel k="resolution" options={RESOLUTIONS} label="All resolutions" />
      </div>

      {loading ? (
        <TableSkeleton rows={6} cols={5} />
      ) : error ? (
        <div className="text-sm text-red-600 bg-red-50 rounded-lg p-3">Failed to load history.</div>
      ) : !rows.length ? (
        <div className="text-sm text-gray-400 bg-gray-50 rounded-lg p-6 text-center">No alerts match these filters.</div>
      ) : (
        <>
          <div className="overflow-x-auto border border-gray-100 rounded-lg">
            <table className="w-full text-sm">
              <thead className="bg-gray-50">
                <tr>
                  {['Type', 'Severity', 'Subject', 'Fired', 'Resolved', 'How'].map((h) => (
                    <th key={h} className="px-3 py-2 text-left font-medium text-gray-500 text-xs">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((a) => {
                  const sev = SEVERITY[a.severity] || SEVERITY.medium
                  return (
                    <tr key={a.id} className="border-t border-gray-100">
                      <td className="px-3 py-2 text-gray-700">{ALERT_TYPE_LABEL[a.type] || a.type}</td>
                      <td className="px-3 py-2">
                        <span className={`text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded border ${sev.cls}`}>{sev.label}</span>
                      </td>
                      <td className="px-3 py-2 text-gray-600">{a.employee_name || a.zone_name || a.alert_rule_name || '—'}</td>
                      <td className="px-3 py-2 text-gray-500 text-xs">{new Date(a.created_at).toLocaleString()}</td>
                      <td className="px-3 py-2 text-gray-500 text-xs">{a.resolved_at ? new Date(a.resolved_at).toLocaleString() : '—'}</td>
                      <td className="px-3 py-2 text-gray-500 text-xs">
                        {a.resolution === 'manual_dismiss'
                          ? `dismissed${a.resolved_by_name ? ` by ${a.resolved_by_name}` : ''}`
                          : a.resolution || '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between text-xs text-gray-500">
            <span>{total} total</span>
            <div className="flex gap-2">
              <button disabled={offset === 0} onClick={() => setOffset((o) => Math.max(0, o - PAGE))}
                className="px-2 py-1 border border-gray-200 rounded disabled:opacity-40">Prev</button>
              <button disabled={offset + PAGE >= total} onClick={() => setOffset((o) => o + PAGE)}
                className="px-2 py-1 border border-gray-200 rounded disabled:opacity-40">Next</button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
