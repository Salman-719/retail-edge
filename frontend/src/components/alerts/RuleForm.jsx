import React, { useState } from 'react'
import { MultiSelect } from '../analytics/widgetParts'
import { RULE_TYPES, SEVERITY_ORDER, defaultsFor } from './alertMeta'

function initialForm(rule, defaults) {
  if (rule) {
    return {
      type: rule.type,
      name: rule.name,
      severity: rule.severity,
      threshold_minutes: rule.threshold_minutes,
      cooldown_minutes: rule.cooldown_minutes,
      followup_interval_minutes: rule.followup_interval_minutes,
      only_during_shift: rule.only_during_shift,
      people_threshold: rule.people_threshold ?? '',
      min_employees: rule.min_employees ?? '',
      employee_id: rule.employee_id || '',
      zone_ids: (rule.zones || []).map((z) => z.id),
    }
  }
  return { type: 'queue_buildup', name: '', employee_id: '', zone_ids: [], ...defaultsFor('queue_buildup', defaults) }
}

export default function RuleForm({ rule, defaults, zoneOptions, employeeOptions, onSubmit, onCancel, submitting, serverError }) {
  const [form, setForm] = useState(() => initialForm(rule, defaults))
  const [err, setErr] = useState('')
  const isEdit = !!rule
  const typeMeta = RULE_TYPES[form.type]
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))

  // On a NEW rule, switching type re-applies that type's defaults for the numeric fields.
  function changeType(type) {
    setForm((f) => ({ ...f, type, ...defaultsFor(type, defaults) }))
  }

  function validate() {
    if (!form.name.trim()) return 'Name is required'
    for (const k of ['threshold_minutes', 'cooldown_minutes', 'followup_interval_minutes']) {
      if (!(Number(form[k]) > 0)) return `${k.replace(/_/g, ' ')} must be > 0`
    }
    if (Number(form.cooldown_minutes) < Number(form.threshold_minutes))
      return 'Cooldown must be ≥ threshold'
    if (form.type === 'queue_buildup' && !(Number(form.people_threshold) > 0)) return 'People threshold required'
    if (form.type === 'staff_absence_zone' && !(Number(form.min_employees) > 0)) return 'Min employees required'
    if (form.type === 'staff_absence_employee' && !form.employee_id) return 'Select an employee'
    if (typeMeta.zones === 'required' && form.zone_ids.length === 0) return 'Select at least one zone'
    return ''
  }

  function submit(e) {
    e.preventDefault()
    const v = validate()
    if (v) { setErr(v); return }
    setErr('')
    const body = {
      type: form.type,
      name: form.name.trim(),
      severity: form.severity,
      threshold_minutes: Number(form.threshold_minutes),
      cooldown_minutes: Number(form.cooldown_minutes),
      followup_interval_minutes: Number(form.followup_interval_minutes),
      only_during_shift: form.only_during_shift,
      people_threshold: form.type === 'queue_buildup' ? Number(form.people_threshold) : null,
      min_employees: form.type === 'staff_absence_zone' ? Number(form.min_employees) : null,
      employee_id: form.type === 'staff_absence_employee' ? form.employee_id : null,
      zone_ids: typeMeta.zones === 'none' ? [] : form.zone_ids,
    }
    onSubmit(body)
  }

  const numInput = (k, label) => (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
      <input type="number" min="1" value={form[k]} onChange={(e) => set(k, e.target.value)}
        className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
    </div>
  )

  return (
    <form onSubmit={submit} className="space-y-4">
      {(err || serverError) && (
        <div className="bg-red-50 text-red-700 text-sm px-3 py-2 rounded-lg border border-red-200">{err || serverError}</div>
      )}

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Type</label>
          <select value={form.type} disabled={isEdit}
            onChange={(e) => changeType(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm disabled:bg-gray-100">
            {Object.entries(RULE_TYPES).map(([k, m]) => <option key={k} value={k}>{m.label}</option>)}
          </select>
          {isEdit && <p className="text-[10px] text-gray-400 mt-1">Type can't be changed; create a new rule instead.</p>}
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Severity</label>
          <select value={form.severity} onChange={(e) => set('severity', e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm capitalize">
            {SEVERITY_ORDER.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
      </div>

      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">Name</label>
        <input value={form.name} onChange={(e) => set('name', e.target.value)}
          placeholder="e.g. Checkout queue too long"
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
      </div>

      <div className="grid grid-cols-3 gap-4">
        {numInput('threshold_minutes', 'Threshold (min)')}
        {numInput('cooldown_minutes', 'Cooldown (min)')}
        {numInput('followup_interval_minutes', 'Follow-up (min)')}
      </div>

      {/* Type-driven fields */}
      {form.type === 'queue_buildup' && numInput('people_threshold', 'People threshold')}
      {form.type === 'staff_absence_zone' && numInput('min_employees', 'Min employees')}
      {form.type === 'staff_absence_employee' && (
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Employee</label>
          <select value={form.employee_id} onChange={(e) => set('employee_id', e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm">
            <option value="">Select…</option>
            {employeeOptions.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
          </select>
        </div>
      )}

      {typeMeta.zones === 'required' && (
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Zones</label>
          <MultiSelect label="Zones" options={zoneOptions} selected={form.zone_ids} onChange={(v) => set('zone_ids', v)} />
        </div>
      )}

      <label className="flex items-center gap-2 text-sm text-gray-700">
        <input type="checkbox" checked={form.only_during_shift} onChange={(e) => set('only_during_shift', e.target.checked)} />
        Only during shift
      </label>

      <div className="flex gap-2 pt-2">
        <button type="button" onClick={onCancel}
          className="flex-1 py-2 px-4 rounded-lg text-sm font-medium border border-gray-300 text-gray-700 hover:bg-gray-50">Cancel</button>
        <button type="submit" disabled={submitting} className="btn-primary flex-1">
          {submitting ? 'Saving…' : isEdit ? 'Save changes' : 'Create rule'}
        </button>
      </div>
    </form>
  )
}
