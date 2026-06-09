import React from 'react'
import { AlertTriangle, X } from 'lucide-react'
import { SEVERITY, ALERT_TYPE_LABEL, ageLabel } from './alertMeta'

// Generic detail rendering: known top-level context + a key/value list of the
// JSONB `details` so unknown (e.g. camera) types still render (rule 7).
function DetailList({ details }) {
  if (!details || typeof details !== 'object') return null
  const entries = Object.entries(details).filter(([k]) => k !== 'followup')
  if (!entries.length) return null
  return (
    <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-gray-500">
      {entries.map(([k, v]) => (
        <div key={k} className="flex gap-1">
          <dt className="font-medium capitalize">{k.replace(/_/g, ' ')}:</dt>
          <dd className="truncate">{typeof v === 'object' ? JSON.stringify(v) : String(v)}</dd>
        </div>
      ))}
    </dl>
  )
}

export default function AlertCard({ alert, onDismiss, dismissing }) {
  const sev = SEVERITY[alert.severity] || SEVERITY.medium
  const subject = alert.employee_name || alert.zone_name || alert.alert_rule_name || '—'

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 flex items-start gap-3">
      <div className="mt-0.5 text-amber-500 shrink-0"><AlertTriangle size={18} /></div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-semibold text-gray-800 text-sm">
            {ALERT_TYPE_LABEL[alert.type] || alert.type}
          </span>
          <span className={`text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded border ${sev.cls}`}>
            {sev.label}
          </span>
          {alert.is_followup && (
            <span className="text-[10px] font-medium text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded">follow-up</span>
          )}
          <span className="text-xs text-gray-400">· {ageLabel(alert.created_at)}</span>
        </div>
        <p className="text-sm text-gray-600 mt-1">
          {subject}
          {alert.alert_rule_name && subject !== alert.alert_rule_name && (
            <span className="text-gray-400"> · rule: {alert.alert_rule_name}</span>
          )}
        </p>
        <DetailList details={alert.details} />
      </div>
      <button
        onClick={() => onDismiss(alert)}
        disabled={dismissing}
        title="Dismiss"
        className="shrink-0 text-gray-400 hover:text-gray-700 disabled:opacity-40 flex items-center gap-1 text-xs border border-gray-200 rounded-lg px-2 py-1 hover:bg-gray-50"
      >
        <X size={13} /> Dismiss
      </button>
    </div>
  )
}
