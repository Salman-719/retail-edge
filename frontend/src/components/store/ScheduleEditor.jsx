import React, { useState } from 'react'
import { putOperatingHours } from '../../api'
import { DAY_LABELS } from './storeSetup'

// Edit Schedule (C3) — live, non-versioned (C2 PUT /operating-hours). Modal.
function initRows(hours) {
  const byDay = {}
  for (const d of hours?.days || []) byDay[d.day_of_week] = d
  return DAY_LABELS.map((_, dow) => {
    const d = byDay[dow]
    return {
      day_of_week: dow,
      is_open: !!d?.is_open,
      open_time: (d?.open_time || '09:00').slice(0, 5),
      close_time: (d?.close_time || '17:00').slice(0, 5),
    }
  })
}

export default function ScheduleEditor({ hours, slug, onClose, onSaved }) {
  const [rows, setRows] = useState(() => initRows(hours))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const set = (dow, k, v) => setRows((rs) => rs.map((r) => (r.day_of_week === dow ? { ...r, [k]: v } : r)))

  function validate() {
    for (const r of rows) {
      if (r.is_open) {
        if (!r.open_time || !r.close_time) return `${DAY_LABELS[r.day_of_week]}: set open and close times`
        if (r.open_time === r.close_time) return `${DAY_LABELS[r.day_of_week]}: open and close must differ`
      }
    }
    return ''
  }

  async function save() {
    const v = validate()
    if (v) { setError(v); return }
    setSaving(true); setError('')
    try {
      const days = rows.map((r) => ({
        day_of_week: r.day_of_week,
        is_open: r.is_open,
        open_time: r.is_open ? r.open_time : null,
        close_time: r.is_open ? r.close_time : null,
      }))
      await putOperatingHours(slug, { days })
      onSaved()
    } catch (e) {
      const d = e.response?.data?.detail
      setError(typeof d === 'string' ? d : d?.error || 'Failed to save schedule')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <h3 className="font-semibold text-gray-900">Edit Schedule</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
        </div>
        <div className="px-6 py-4 space-y-2">
          {error && <div className="bg-red-50 text-red-700 text-sm px-3 py-2 rounded-lg border border-red-200">{error}</div>}
          {rows.map((r) => (
            <div key={r.day_of_week} className="flex items-center gap-3">
              <span className="w-10 text-sm text-gray-600">{DAY_LABELS[r.day_of_week]}</span>
              <label className="flex items-center gap-1.5 text-xs text-gray-600 w-16">
                <input type="checkbox" checked={r.is_open} onChange={(e) => set(r.day_of_week, 'is_open', e.target.checked)} />
                Open
              </label>
              <input type="time" value={r.open_time} disabled={!r.is_open}
                onChange={(e) => set(r.day_of_week, 'open_time', e.target.value)}
                className="border border-gray-300 rounded px-2 py-1 text-sm disabled:bg-gray-100 disabled:text-gray-400" />
              <span className="text-gray-400 text-xs">–</span>
              <input type="time" value={r.close_time} disabled={!r.is_open}
                onChange={(e) => set(r.day_of_week, 'close_time', e.target.value)}
                className="border border-gray-300 rounded px-2 py-1 text-sm disabled:bg-gray-100 disabled:text-gray-400" />
            </div>
          ))}
          <p className="text-[10px] text-gray-400 pt-1">Overnight hours (close before open) wrap past midnight.</p>
        </div>
        <div className="px-6 py-4 border-t border-gray-100 flex gap-2">
          <button onClick={onClose} className="flex-1 py-2 px-4 rounded-lg text-sm font-medium border border-gray-300 text-gray-700 hover:bg-gray-50">Cancel</button>
          <button onClick={save} disabled={saving} className="btn-primary flex-1">{saving ? 'Saving…' : 'Save schedule'}</button>
        </div>
      </div>
    </div>
  )
}
