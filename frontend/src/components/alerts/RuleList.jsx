import React from 'react'
import { Pencil, Trash2 } from 'lucide-react'
import { SEVERITY, RULE_TYPES } from './alertMeta'

export default function RuleList({ rules, onToggle, onEdit, onDelete, busyId }) {
  if (!rules.length) {
    return <div className="text-sm text-gray-400 bg-gray-50 rounded-lg p-6 text-center">No alert rules yet. Create one to start monitoring.</div>
  }
  return (
    <div className="overflow-x-auto border border-gray-100 rounded-lg">
      <table className="w-full text-sm">
        <thead className="bg-gray-50">
          <tr>
            {['Name', 'Type', 'Severity', 'Zones', 'Active', ''].map((h) => (
              <th key={h} className="px-3 py-2 text-left font-medium text-gray-500 text-xs">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rules.map((r) => {
            const sev = SEVERITY[r.severity] || SEVERITY.medium
            const busy = busyId === r.id
            return (
              <tr key={r.id} className="border-t border-gray-100">
                <td className="px-3 py-2 text-gray-800 font-medium">{r.name}</td>
                <td className="px-3 py-2 text-gray-600">{RULE_TYPES[r.type]?.label || r.type}</td>
                <td className="px-3 py-2">
                  <span className={`text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded border ${sev.cls}`}>{sev.label}</span>
                </td>
                <td className="px-3 py-2 text-gray-500 text-xs">
                  {r.employee_id ? (r.employee_name || 'employee') : (r.zones || []).map((z) => z.name).join(', ') || '—'}
                </td>
                <td className="px-3 py-2">
                  <button
                    onClick={() => onToggle(r)} disabled={busy}
                    className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors disabled:opacity-50 ${r.is_active ? 'bg-blue-600' : 'bg-gray-300'}`}
                    title={r.is_active ? 'Active' : 'Inactive'}
                  >
                    <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${r.is_active ? 'translate-x-4' : 'translate-x-0.5'}`} />
                  </button>
                </td>
                <td className="px-3 py-2 text-right whitespace-nowrap">
                  <button onClick={() => onEdit(r)} className="text-gray-400 hover:text-gray-700 p-1" title="Edit"><Pencil size={14} /></button>
                  <button onClick={() => onDelete(r)} disabled={busy} className="text-gray-400 hover:text-red-600 p-1 disabled:opacity-40" title="Delete"><Trash2 size={14} /></button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
