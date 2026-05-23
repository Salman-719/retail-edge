import React, { useEffect, useState, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { useAuth } from '../store'
import {
  listShifts, createShift, patchShift, deleteShift, generateShifts,
  listShiftAssignments, createShiftAssignment, patchShiftAssignment, deleteShiftAssignment,
  listBreaks, createBreak, patchBreak, deleteBreak,
  listEmployees, listSections,
} from '../api'

const SHIFT_STATUS = ['scheduled', 'active', 'completed', 'absent', 'cancelled']
const ATTENDANCE_STATUS = ['scheduled', 'present', 'absent', 'on_break']
const BREAK_TYPES = ['taken', 'scheduled']

const STATUS_BADGE = {
  scheduled: 'bg-blue-100 text-blue-700',
  active: 'bg-green-100 text-green-700',
  completed: 'bg-gray-100 text-gray-600',
  absent: 'bg-red-100 text-red-700',
  cancelled: 'bg-orange-100 text-orange-700',
}

const ATTENDANCE_BADGE = {
  scheduled: 'bg-blue-100 text-blue-700',
  present: 'bg-green-100 text-green-700',
  absent: 'bg-red-100 text-red-700',
  on_break: 'bg-yellow-100 text-yellow-700',
}

function fmt(dt) {
  if (!dt) return '—'
  return new Date(dt).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' })
}

function fmtTime(dt) {
  if (!dt) return '—'
  return new Date(dt).toLocaleTimeString(undefined, { timeStyle: 'short' })
}

function toLocalInput(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// ── Create/Edit Shift Modal ───────────────────────────────────────────────────

function ShiftModal({ slug, shift, employees, sections, onClose, onDone }) {
  const editing = !!shift
  const now = new Date()
  const inOneHour = new Date(now.getTime() + 3600000)

  const [form, setForm] = useState({
    employee_id: shift?.employee_id || '',
    section_id: shift?.section_id || '',
    scheduled_start: shift ? toLocalInput(shift.scheduled_start) : toLocalInput(now.toISOString()),
    scheduled_end: shift ? toLocalInput(shift.scheduled_end) : toLocalInput(inOneHour.toISOString()),
    break_duration_min: shift?.break_duration_min ?? 0,
    status: shift?.status || 'scheduled',
  })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const body = {
        employee_id: form.employee_id,
        section_id: form.section_id,
        scheduled_start: new Date(form.scheduled_start).toISOString(),
        scheduled_end: new Date(form.scheduled_end).toISOString(),
        break_duration_min: Number(form.break_duration_min),
        status: form.status,
      }
      if (editing) {
        await patchShift(slug, shift.id, body)
      } else {
        await createShift(slug, body)
      }
      onDone()
      onClose()
    } catch (err) {
      const d = err.response?.data?.detail
      setError(typeof d === 'object' ? d.error : (d || 'Request failed'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <h3 className="font-semibold text-gray-900">{editing ? 'Edit Shift' : 'Create Shift'}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
        </div>
        <form onSubmit={handleSubmit} className="px-6 py-4 space-y-3">
          {error && <div className="bg-red-50 text-red-700 text-sm px-3 py-2 rounded-lg border border-red-200">{error}</div>}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Employee <span className="text-red-500">*</span></label>
            <select required value={form.employee_id} onChange={e => setForm(f => ({ ...f, employee_id: e.target.value }))}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value="">Select employee…</option>
              {employees.map(emp => <option key={emp.id} value={emp.id}>{emp.name}</option>)}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Section <span className="text-red-500">*</span></label>
            <select required value={form.section_id} onChange={e => setForm(f => ({ ...f, section_id: e.target.value }))}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value="">Select section…</option>
              {sections.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Start <span className="text-red-500">*</span></label>
              <input type="datetime-local" required value={form.scheduled_start}
                onChange={e => setForm(f => ({ ...f, scheduled_start: e.target.value }))}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">End <span className="text-red-500">*</span></label>
              <input type="datetime-local" required value={form.scheduled_end}
                onChange={e => setForm(f => ({ ...f, scheduled_end: e.target.value }))}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Break (min)</label>
              <input type="number" min="0" max="480" value={form.break_duration_min}
                onChange={e => setForm(f => ({ ...f, break_duration_min: e.target.value }))}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Status</label>
              <select value={form.status} onChange={e => setForm(f => ({ ...f, status: e.target.value }))}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                {SHIFT_STATUS.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
          </div>

          <div className="flex gap-2 pt-2">
            <button type="button" onClick={onClose}
              className="flex-1 py-2 px-4 rounded-lg text-sm font-medium border border-gray-300 text-gray-700 hover:bg-gray-50">
              Cancel
            </button>
            <button type="submit" disabled={loading}
              className="flex-1 py-2 px-4 rounded-lg text-sm font-semibold text-white disabled:opacity-50"
              style={{ backgroundColor: '#1B3A5C' }}>
              {loading ? 'Saving…' : (editing ? 'Save' : 'Create Shift')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Shift Detail Panel (assignments + breaks) ─────────────────────────────────

function BreaksPanel({ slug, shift, assignment, onClose }) {
  const [breaks, setBreaks] = useState([])
  const [loading, setLoading] = useState(true)
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState({ break_start: '', break_end: '', break_type: 'taken' })
  const [error, setError] = useState('')

  const fetchBreaks = useCallback(async () => {
    setLoading(true)
    try {
      const data = await listBreaks(slug, shift.id, assignment.id)
      setBreaks(data)
    } catch {}
    setLoading(false)
  }, [slug, shift.id, assignment.id])

  useEffect(() => { fetchBreaks() }, [fetchBreaks])

  async function handleCreate() {
    if (!form.break_start) { setError('Break start is required'); return }
    setError('')
    try {
      await createBreak(slug, shift.id, assignment.id, {
        break_start: new Date(form.break_start).toISOString(),
        break_end: form.break_end ? new Date(form.break_end).toISOString() : null,
        break_type: form.break_type,
      })
      setAdding(false)
      setForm({ break_start: '', break_end: '', break_type: 'taken' })
      fetchBreaks()
    } catch (err) {
      const d = err.response?.data?.detail
      setError(typeof d === 'object' ? d.error : (d || 'Failed'))
    }
  }

  async function handleEndBreak(br) {
    const now = new Date().toISOString()
    try {
      await patchBreak(slug, shift.id, assignment.id, br.id, { break_end: now })
      fetchBreaks()
    } catch {}
  }

  async function handleDeleteBreak(brId) {
    try {
      await deleteBreak(slug, shift.id, assignment.id, brId)
      setBreaks(prev => prev.filter(b => b.id !== brId))
    } catch {}
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <div>
            <h3 className="font-semibold text-gray-900">Break Records</h3>
            <p className="text-xs text-gray-400 mt-0.5">Assignment {assignment.id.slice(0, 8)}…</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
        </div>
        <div className="px-6 py-4 space-y-3 max-h-[60vh] overflow-y-auto">
          {loading ? (
            <p className="text-sm text-gray-400 text-center py-4">Loading…</p>
          ) : breaks.length === 0 ? (
            <p className="text-sm text-gray-400">No breaks recorded.</p>
          ) : (
            <div className="space-y-2">
              {breaks.map(br => (
                <div key={br.id} className="flex items-center gap-3 bg-gray-50 rounded-lg px-3 py-2">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-gray-900">{fmtTime(br.break_start)} – {br.break_end ? fmtTime(br.break_end) : <span className="text-yellow-600">ongoing</span>}</p>
                    <p className="text-xs text-gray-400">{br.break_type}</p>
                  </div>
                  <div className="flex gap-1 shrink-0">
                    {!br.break_end && (
                      <button onClick={() => handleEndBreak(br)}
                        className="text-xs px-2 py-1 rounded text-green-600 hover:bg-green-50">End</button>
                    )}
                    <button onClick={() => handleDeleteBreak(br.id)}
                      className="text-xs px-2 py-1 rounded text-red-500 hover:bg-red-50">Delete</button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {error && <div className="bg-red-50 text-red-700 text-sm px-3 py-2 rounded-lg border border-red-200">{error}</div>}

          {adding ? (
            <div className="border border-gray-200 rounded-lg p-3 space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Start</label>
                  <input type="datetime-local" value={form.break_start}
                    onChange={e => setForm(f => ({ ...f, break_start: e.target.value }))}
                    className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">End (optional)</label>
                  <input type="datetime-local" value={form.break_end}
                    onChange={e => setForm(f => ({ ...f, break_end: e.target.value }))}
                    className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Type</label>
                <select value={form.break_type} onChange={e => setForm(f => ({ ...f, break_type: e.target.value }))}
                  className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                  {BREAK_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
              <div className="flex gap-2">
                <button onClick={() => { setAdding(false); setError('') }}
                  className="flex-1 py-1.5 text-sm border border-gray-300 rounded-lg text-gray-600 hover:bg-gray-50">Cancel</button>
                <button onClick={handleCreate}
                  className="flex-1 py-1.5 text-sm font-semibold text-white rounded-lg" style={{ backgroundColor: '#1B3A5C' }}>
                  Add Break
                </button>
              </div>
            </div>
          ) : (
            <button onClick={() => setAdding(true)}
              className="w-full py-2 text-sm border-2 border-dashed border-gray-300 rounded-lg text-gray-500 hover:border-gray-400 hover:text-gray-700 transition-colors">
              + Add Break
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

function AssignmentsPanel({ slug, shift, employees, onClose }) {
  const [assignments, setAssignments] = useState([])
  const [loading, setLoading] = useState(true)
  const [adding, setAdding] = useState(false)
  const [selectedEmployee, setSelectedEmployee] = useState('')
  const [error, setError] = useState('')
  const [breaksFor, setBreaksFor] = useState(null)

  const fetchAssignments = useCallback(async () => {
    setLoading(true)
    try {
      const data = await listShiftAssignments(slug, shift.id)
      setAssignments(data)
    } catch {}
    setLoading(false)
  }, [slug, shift.id])

  useEffect(() => { fetchAssignments() }, [fetchAssignments])

  const assignedIds = new Set(assignments.map(a => a.employee_id))
  const available = employees.filter(e => !assignedIds.has(e.id))

  function getEmployeeName(id) {
    return employees.find(e => e.id === id)?.name || id.slice(0, 8)
  }

  async function handleAssign() {
    if (!selectedEmployee) return
    setError('')
    try {
      await createShiftAssignment(slug, shift.id, { employee_id: selectedEmployee })
      setAdding(false)
      setSelectedEmployee('')
      fetchAssignments()
    } catch (err) {
      const d = err.response?.data?.detail
      setError(typeof d === 'object' ? d.error : (d || 'Failed'))
    }
  }

  async function handleAttendance(assignment, status) {
    try {
      await patchShiftAssignment(slug, shift.id, assignment.id, { attendance_status: status })
      setAssignments(prev => prev.map(a => a.id === assignment.id ? { ...a, attendance_status: status } : a))
    } catch {}
  }

  async function handleRemove(assignmentId) {
    if (!confirm('Remove this assignment?')) return
    try {
      await deleteShiftAssignment(slug, shift.id, assignmentId)
      setAssignments(prev => prev.filter(a => a.id !== assignmentId))
    } catch {}
  }

  return (
    <>
      <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4">
        <div className="bg-white rounded-xl shadow-xl w-full max-w-lg">
          <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
            <div>
              <h3 className="font-semibold text-gray-900">Assignments & Attendance</h3>
              <p className="text-xs text-gray-400 mt-0.5">{fmt(shift.scheduled_start)} – {fmtTime(shift.scheduled_end)}</p>
            </div>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
          </div>

          <div className="px-6 py-4 space-y-3 max-h-[60vh] overflow-y-auto">
            {loading ? (
              <p className="text-sm text-gray-400 text-center py-4">Loading…</p>
            ) : assignments.length === 0 ? (
              <p className="text-sm text-gray-400">No assignments yet.</p>
            ) : (
              <div className="space-y-2">
                {assignments.map(a => (
                  <div key={a.id} className="border border-gray-100 rounded-lg px-3 py-2">
                    <div className="flex items-center gap-3">
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-gray-900">{getEmployeeName(a.employee_id)}</p>
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${ATTENDANCE_BADGE[a.attendance_status] || 'bg-gray-100 text-gray-600'}`}>
                          {a.attendance_status}
                        </span>
                      </div>
                      <div className="flex gap-1 shrink-0">
                        <button onClick={() => setBreaksFor(a)}
                          className="text-xs px-2 py-1 rounded text-gray-600 hover:bg-gray-100">Breaks</button>
                        <button onClick={() => handleRemove(a.id)}
                          className="text-xs px-2 py-1 rounded text-red-500 hover:bg-red-50">Remove</button>
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-1 mt-2">
                      {ATTENDANCE_STATUS.map(s => (
                        <button key={s} onClick={() => handleAttendance(a, s)}
                          className={`text-xs px-2 py-0.5 rounded border transition-colors ${
                            a.attendance_status === s
                              ? 'border-blue-500 text-blue-700 bg-blue-50'
                              : 'border-gray-200 text-gray-500 hover:border-gray-400'
                          }`}>
                          {s}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {error && <div className="bg-red-50 text-red-700 text-sm px-3 py-2 rounded-lg border border-red-200">{error}</div>}

            {adding ? (
              <div className="border border-gray-200 rounded-lg p-3 space-y-2">
                <select value={selectedEmployee} onChange={e => setSelectedEmployee(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                  <option value="">Select employee…</option>
                  {available.map(e => <option key={e.id} value={e.id}>{e.name}</option>)}
                </select>
                <div className="flex gap-2">
                  <button onClick={() => { setAdding(false); setError('') }}
                    className="flex-1 py-1.5 text-sm border border-gray-300 rounded-lg text-gray-600 hover:bg-gray-50">Cancel</button>
                  <button onClick={handleAssign} disabled={!selectedEmployee}
                    className="flex-1 py-1.5 text-sm font-semibold text-white rounded-lg disabled:opacity-40"
                    style={{ backgroundColor: '#1B3A5C' }}>
                    Assign
                  </button>
                </div>
              </div>
            ) : (
              available.length > 0 && (
                <button onClick={() => setAdding(true)}
                  className="w-full py-2 text-sm border-2 border-dashed border-gray-300 rounded-lg text-gray-500 hover:border-gray-400 hover:text-gray-700 transition-colors">
                  + Assign Employee
                </button>
              )
            )}
          </div>
        </div>
      </div>

      {breaksFor && (
        <BreaksPanel slug={slug} shift={shift} assignment={breaksFor} onClose={() => setBreaksFor(null)} />
      )}
    </>
  )
}

// ── Generate Shifts Modal ─────────────────────────────────────────────────────

function GenerateModal({ slug, onClose, onDone }) {
  const today = new Date().toISOString().slice(0, 10)
  const [form, setForm] = useState({ week_start_date: today })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function handleGenerate(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await generateShifts(slug, { week_start_date: form.week_start_date })
      onDone()
      onClose()
    } catch (err) {
      const d = err.response?.data?.detail
      setError(typeof d === 'object' ? d.error : (d || 'Failed to generate shifts'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-sm">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <h3 className="font-semibold text-gray-900">Generate Shifts from Patterns</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
        </div>
        <form onSubmit={handleGenerate} className="px-6 py-4 space-y-3">
          {error && <div className="bg-red-50 text-red-700 text-sm px-3 py-2 rounded-lg border border-red-200">{error}</div>}
          <p className="text-sm text-gray-600">This will create shift instances for the selected week based on all active shift patterns.</p>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Week starting (Monday)</label>
            <input type="date" required value={form.week_start_date}
              onChange={e => setForm({ week_start_date: e.target.value })}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div className="flex gap-2 pt-2">
            <button type="button" onClick={onClose}
              className="flex-1 py-2 px-4 rounded-lg text-sm font-medium border border-gray-300 text-gray-700 hover:bg-gray-50">
              Cancel
            </button>
            <button type="submit" disabled={loading}
              className="flex-1 py-2 px-4 rounded-lg text-sm font-semibold text-white disabled:opacity-50"
              style={{ backgroundColor: '#1B3A5C' }}>
              {loading ? 'Generating…' : 'Generate'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function Shifts() {
  const { slug } = useParams()
  const { state } = useAuth()
  const role = state.currentMember?.role || (state.user?.account_type === 'owner' ? 'owner' : null)

  const [shifts, setShifts] = useState([])
  const [employees, setEmployees] = useState([])
  const [sections, setSections] = useState([])
  const [loading, setLoading] = useState(true)

  const [filterStatus, setFilterStatus] = useState('')
  const [filterDate, setFilterDate] = useState('')

  const [modal, setModal] = useState(null)
  // modal: null | 'create' | 'generate' | { type: 'edit', shift } | { type: 'assignments', shift }

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const params = {}
      if (filterStatus) params.status = filterStatus
      if (filterDate) {
        params.since = new Date(filterDate).toISOString()
        const next = new Date(filterDate)
        next.setDate(next.getDate() + 1)
        params.until = next.toISOString()
      }
      const [sh, emps, secs] = await Promise.all([
        listShifts(slug, params),
        listEmployees(slug, { active_only: true }),
        listSections ? listSections(slug) : Promise.resolve([]),
      ])
      setShifts(sh)
      setEmployees(emps)
      setSections(secs)
    } catch {}
    setLoading(false)
  }, [slug, filterStatus, filterDate])

  useEffect(() => { fetchData() }, [fetchData])

  if (role === 'viewer') {
    return (
      <div className="flex flex-col items-center justify-center h-full text-gray-400">
        <p className="text-lg font-medium text-gray-500">Access Restricted</p>
        <p className="text-sm mt-1">You don't have permission to view shifts.</p>
      </div>
    )
  }

  function getEmployeeName(id) {
    return employees.find(e => e.id === id)?.name || id?.slice(0, 8) || '—'
  }

  function getSectionName(id) {
    return sections.find(s => s.id === id)?.name || id?.slice(0, 8) || '—'
  }

  async function handleDelete(shift) {
    if (!confirm(`Delete shift for ${getEmployeeName(shift.employee_id)}?`)) return
    try {
      await deleteShift(slug, shift.id)
      setShifts(prev => prev.filter(s => s.id !== shift.id))
    } catch (err) {
      alert(err.response?.data?.detail?.error || 'Failed to delete shift')
    }
  }

  return (
    <div className="flex flex-col h-full overflow-auto">
      <header className="px-6 py-4 border-b border-gray-200 bg-white flex items-center justify-between shrink-0">
        <div>
          <h1 className="font-semibold text-gray-900">Shifts</h1>
          <p className="text-xs text-gray-400 mt-0.5">Manage shift instances, assignments and attendance</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => setModal('generate')}
            className="px-3 py-1.5 rounded-lg text-sm font-medium border border-gray-300 text-gray-700 hover:bg-gray-50 transition-colors">
            Generate from Patterns
          </button>
          <button onClick={() => setModal('create')}
            className="px-3 py-1.5 rounded-lg text-sm font-semibold text-white"
            style={{ backgroundColor: '#1B3A5C' }}>
            + Create Shift
          </button>
        </div>
      </header>

      {/* Filters */}
      <div className="px-6 py-3 border-b border-gray-100 bg-white flex items-end gap-3 shrink-0">
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Status</label>
          <select value={filterStatus} onChange={e => { setFilterStatus(e.target.value) }}
            className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="">All statuses</option>
            {SHIFT_STATUS.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Date</label>
          <input type="date" value={filterDate} onChange={e => setFilterDate(e.target.value)}
            className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
        {(filterStatus || filterDate) && (
          <button onClick={() => { setFilterStatus(''); setFilterDate('') }}
            className="text-sm text-gray-500 hover:text-gray-700 px-3 py-1.5 rounded-lg border border-gray-200 hover:bg-gray-50">
            Clear
          </button>
        )}
      </div>

      {/* Table */}
      <div className="flex-1 p-6">
        {loading ? (
          <div className="text-sm text-gray-400 py-8 text-center">Loading…</div>
        ) : shifts.length === 0 ? (
          <div className="text-sm text-gray-400 py-8 text-center">
            No shifts found. Create one manually or generate from shift patterns.
          </div>
        ) : (
          <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase tracking-wide">Employee</th>
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase tracking-wide hidden sm:table-cell">Section</th>
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase tracking-wide">Scheduled</th>
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase tracking-wide hidden md:table-cell">Actual</th>
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase tracking-wide">Status</th>
                  <th className="px-4 py-2.5"></th>
                </tr>
              </thead>
              <tbody>
                {shifts.map((shift, i) => (
                  <tr key={shift.id} className={`${i < shifts.length - 1 ? 'border-b border-gray-100' : ''} hover:bg-gray-50 transition-colors`}>
                    <td className="px-4 py-3 font-medium text-gray-900">{getEmployeeName(shift.employee_id)}</td>
                    <td className="px-4 py-3 text-gray-500 hidden sm:table-cell">{getSectionName(shift.section_id)}</td>
                    <td className="px-4 py-3 text-gray-500 text-xs whitespace-nowrap">
                      {fmt(shift.scheduled_start)}<br />
                      <span className="text-gray-400">→ {fmtTime(shift.scheduled_end)}</span>
                    </td>
                    <td className="px-4 py-3 text-gray-500 text-xs hidden md:table-cell">
                      {shift.actual_start ? (
                        <>{fmtTime(shift.actual_start)} → {shift.actual_end ? fmtTime(shift.actual_end) : <span className="text-green-600">ongoing</span>}</>
                      ) : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_BADGE[shift.status] || 'bg-gray-100 text-gray-600'}`}>
                        {shift.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-1">
                        <button onClick={() => setModal({ type: 'assignments', shift })}
                          className="text-xs px-2 py-1 rounded text-gray-600 hover:bg-gray-100 transition-colors">
                          Assignments
                        </button>
                        <button onClick={() => setModal({ type: 'edit', shift })}
                          className="text-xs px-2 py-1 rounded text-blue-600 hover:bg-blue-50 transition-colors">
                          Edit
                        </button>
                        <button onClick={() => handleDelete(shift)}
                          className="text-xs px-2 py-1 rounded text-red-500 hover:bg-red-50 transition-colors">
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {modal === 'create' && (
        <ShiftModal slug={slug} employees={employees} sections={sections} onClose={() => setModal(null)} onDone={fetchData} />
      )}
      {modal === 'generate' && (
        <GenerateModal slug={slug} onClose={() => setModal(null)} onDone={fetchData} />
      )}
      {modal?.type === 'edit' && (
        <ShiftModal slug={slug} shift={modal.shift} employees={employees} sections={sections} onClose={() => setModal(null)} onDone={fetchData} />
      )}
      {modal?.type === 'assignments' && (
        <AssignmentsPanel slug={slug} shift={modal.shift} employees={employees} onClose={() => setModal(null)} />
      )}
    </div>
  )
}
