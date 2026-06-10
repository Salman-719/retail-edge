import React, { useState, useRef, useEffect } from 'react'
import { ChevronDown, Check } from 'lucide-react'

// Multi-select dropdown. Empty selection = "all". Shared by the top control bar
// (zones) and the Employees widget (employees).
export function MultiSelect({ label, options, selected, onChange }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])
  const toggle = (id) =>
    onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id])
  const summary = selected.length === 0 ? `All ${label.toLowerCase()}` : `${selected.length} ${label.toLowerCase()}`

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        disabled={!options.length}
        className="flex items-center gap-1.5 border border-gray-300 rounded-lg px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
      >
        {summary}
        <ChevronDown size={14} className="text-gray-400" />
      </button>
      {open && (
        <div className="absolute right-0 z-20 mt-1 w-56 max-h-64 overflow-y-auto bg-white border border-gray-200 rounded-lg shadow-lg py-1">
          {selected.length > 0 && (
            <button onClick={() => onChange([])} className="w-full text-left px-3 py-1.5 text-xs text-blue-600 hover:bg-blue-50">
              Clear (show all)
            </button>
          )}
          {options.map((o) => (
            <button
              key={o.id}
              onClick={() => toggle(o.id)}
              className="w-full flex items-center justify-between px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
            >
              <span className="truncate">{o.name}</span>
              {selected.includes(o.id) && <Check size={14} className="text-blue-600 shrink-0" />}
            </button>
          ))}
          {!options.length && <p className="px-3 py-2 text-xs text-gray-400">None available</p>}
        </div>
      )}
    </div>
  )
}

export function ProvisionalBadge() {
  return (
    <span
      title="Partial period — not yet complete"
      className="ml-1.5 inline-block text-[9px] font-semibold uppercase tracking-wide text-amber-700 bg-amber-100 px-1 py-0.5 rounded"
    >
      provisional
    </span>
  )
}

// columns: [{ key, label, render?(row), align? }]. Rows flagged is_complete===false
// get a "provisional" badge on their first cell.
export function DataTable({ columns, rows, rowKey }) {
  return (
    <div className="overflow-x-auto border border-gray-100 rounded-lg max-h-96 overflow-y-auto">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 sticky top-0">
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                className={`px-3 py-2 font-medium text-gray-500 text-xs ${c.align === 'right' ? 'text-right' : 'text-left'}`}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr key={rowKey ? rowKey(row, ri) : ri} className="border-t border-gray-100">
              {columns.map((c, ci) => (
                <td
                  key={c.key}
                  className={`px-3 py-2 text-gray-700 ${c.align === 'right' ? 'text-right tabular-nums' : 'text-left'}`}
                >
                  {c.render ? c.render(row) : row[c.key]}
                  {ci === 0 && row.is_complete === false && <ProvisionalBadge />}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
