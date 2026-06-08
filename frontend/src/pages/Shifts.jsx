import React, { useEffect, useState, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { Calendar, RefreshCw } from 'lucide-react'
import { useAuth } from '../store'
import { usePageTitle } from '../components/PageMeta'
import { TableSkeleton } from '../components/Skeletons'
import {
  listShifts, createShift, patchShift, deleteShift, generateShifts,
  listShiftAssignments, createShiftAssignment, patchShiftAssignment, deleteShiftAssignment,
  listBreaks, createBreak, patchBreak, deleteBreak,
  listEmployees,
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

// Role badge colours reused on calendar cards
const ROLE_CAL_BADGE = {
  cashier: 'bg-green-100 text-green-700',
  supervisor: 'bg-purple-100 text-purple-700',
  security: 'bg-red-100 text-red-700',
  shelf_stocker: 'bg-yellow-100 text-yellow-700',
  manager: 'bg-blue-100 text-blue-700',
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

// Monday of the week containing `date`
function weekStart(date) {
  const d = new Date(date)
  const day = d.getDay() // 0=Sun
  const diff = (day === 0 ? -6 : 1 - day)
  d.setDate(d.getDate() + diff)
  d.setHours(0, 0, 0, 0)
  return d
}

function addDays(date, n) {
  const d = new Date(date)
  d.setDate(d.getDate() + n)
  return d
}

function isoDate(date) {
  const pad = n => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth()+1)}-${pad(date.getDate())}`
}

// ── Mock calendar shifts ──────────────────────────────────────────────────────
// Offsets are relative to the Monday of whatever week is displayed.
// MOCK: replace with real shifts from listShifts filtered by week range.
function buildMockCalendarShifts(monday) {
  return [
    { id: 'mock-1', dayOffset: 0, employee: 'Sara K.',    role: 'cashier',      start: '08:00', end: '16:00' },
    { id: 'mock-2', dayOffset: 1, employee: 'James T.',   role: 'supervisor',   start: '09:00', end: '17:00' },
    { id: 'mock-3', dayOffset: 2, employee: 'Lena M.',    role: 'shelf_stocker',start: '06:00', end: '14:00' },
    { id: 'mock-4', dayOffset: 4, employee: 'Omar R.',    role: 'security',     start: '14:00', end: '22:00' },
    { id: 'mock-5', dayOffset: 6, employee: 'Priya N.',   role: 'cashier',      start: '10:00', end: '18:00' },
  ]
}

// ── Calendar view ─────────────────────────────────────────────────────────────

const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function CalendarView({ shifts }) {
  const [monday, setMonday] = useState(() => weekStart(new Date()))

  const mockShifts = buildMockCalendarShifts(monday)

  const weekLabel = (() => {
    const sun = addDays(monday, 6)
    const fmtD = d => d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
    return `${fmtD(monday)} – ${fmtD(sun)}, ${monday.getFullYear()}`
  })()

  const today = isoDate(new Date())

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Week navigation */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-gray-100 bg-white shrink-0">
        <button
          onClick={() => setMonday(d => addDays(d, -7))}
          className="p-1.5 rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-50 transition-colors"
          aria-label="Previous week"
        >
          ‹
        </button>
        <span className="text-sm font-medium text-gray-700">{weekLabel}</span>
        <button
          onClick={() => setMonday(d => addDays(d, 7))}
          className="p-1.5 rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-50 transition-colors"
          aria-label="Next week"
        >
          ›
        </button>
      </div>

      {/* 7-column grid */}
      <div className="flex-1 overflow-auto p-4">
        <div className="grid grid-cols-7 gap-2 min-w-[640px]">
          {DAY_LABELS.map((label, i) => {
            const date = addDays(monday, i)
            const dateStr = isoDate(date)
            const isToday = dateStr === today
            const dayShifts = mockShifts.filter(s => s.dayOffset === i)

            return (
              <div key={i} className="flex flex-col gap-1.5">
                {/* Day header */}
                <div className={`text-center py-1.5 rounded-lg text-xs font-semibold ${
                  isToday
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-100 text-gray-600'
                }`}>
                  <div>{label}</div>
                  <div className={`text-xs font-normal mt-0.5 ${isToday ? 'text-blue-100' : 'text-gray-400'}`}>
                    {date.getDate()}
                  </div>
                </div>

                {/* Shift cards */}
                {dayShifts.length === 0 ? (
                  <div className="h-12 rounded-lg border border-dashed border-gray-200" />
                ) : (
                  dayShifts.map(s => (
                    <div
                      key={s.id}
                      className="bg-white border border-gray-200 rounded-lg px-2 py-2 shadow-sm hover:shadow transition-shadow"
                    >
                      <p className="text-xs font-semibold text-gray-900 truncate">{s.employee}</p>
                      <p className="text-xs text-gray-500 mt-0.5">{s.start} – {s.end}</p>
                      <span className={`inline-block mt-1 text-xs px-1.5 py-0.5 rounded-full font-medium ${ROLE_CAL_BADGE[s.role] || 'bg-gray-100 text-gray-600'}`}>
                        {s.role.replace('_', ' ')}
                      </span>
                    </div>
                  ))
                )}
              </div>
            )
          })}
        </div>
        {/* MOCK: replace buildMockCalendarShifts with listShifts filtered by week */}
        <p className="text-xs text-gray-400 italic mt-3 text-center">
          Calendar shows mock data — connect to listShifts API when backend is available.
        </p>
      </div>
    </div>
  )
}

// ── View toggle (segmented control) ──────────────────────────────────────────

function ViewToggle({ view, onChange }) {
  return (
    <div className="flex rounded-lg border border-gray-300 overflow-hidden shrink-0">
      {['list', 'calendar'].map(v => (
        <button
          key={v}
          onClick={() => onChange(v)}
          className={`px-3 py-1.5 text-sm font-medium capitalize transition-colors ${
            view === v
              ? 'bg-gray-800 text-white'
              : 'bg-white text-gray-600 hover:bg-gray-50'
          }`}
        >
          {v === 'list' ? 'List' : 'Calendar'}
        </button>
      ))}
    </div>
  )
}

// ── Tooltip wrapper ───────────────────────────────────────────────────────────

function Tooltip({ text, children }) {
  return (
    <div className="relative group">
      {children}
      <div className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 px-3 py-2 bg-gray-800 text-white text-xs rounded-lg leading-snug text-center opacity-0 group-hover:opacity-100 transition-opacity z-20">
        {text}
        <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-gray-800" />
      </div>
    </div>
  )
}

// ── Create/Edit Shift Modal ───────────────────────────────────────────────────

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function dateForWeekday(startDateStr, targetDay) {
  const d = new Date(startDateStr + 'T00:00:00')
  const jsDay = d.getDay()
  const currentDay = jsDay === 0 ? 6 : jsDay - 1
  const diff = (targetDay - currentDay + 7) % 7
  d.setDate(d.getDate() + diff)
  return d.toISOString().slice(0, 10)
}

function ShiftModal({ slug, shift, employees, onClose, onDone }) {
  const editing = !!shift
  const now = new Date()
  const inOneHour = new Date(now.getTime() + 3600000)
  const today = now.toISOString().slice(0, 10)

  const [form, setForm] = useState({
    employee_id: shift?.employee_id || '',
    // edit-only fields
    scheduled_start: shift ? toLocalInput(shift.scheduled_start) : toLocalInput(now.toISOString()),
    scheduled_end: shift ? toLocalInput(shift.scheduled_end) : toLocalInput(inOneHour.toISOString()),
    // create-only fields
    start_date: today,
    selected_days: [0],
    start_time: '09:00',
    end_time: '17:00',
    break_start: '',
    break_end: '',
    status: shift?.status || 'scheduled',
  })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  function toggleDay(i) {
    setForm(f => {
      const has = f.selected_days.includes(i)
      return { ...f, selected_days: has ? f.selected_days.filter(d => d !== i) : [...f.selected_days, i] }
    })
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      let break_duration_min = 0
      if (form.break_start && form.break_end) {
        const [sh, sm] = form.break_start.split(':').map(Number)
        const [eh, em] = form.break_end.split(':').map(Number)
        break_duration_min = Math.max(0, (eh * 60 + em) - (sh * 60 + sm))
      }
      if (editing) {
        await patchShift(slug, shift.id, {
          employee_id: form.employee_id,
          scheduled_start: new Date(form.scheduled_start).toISOString(),
          scheduled_end: new Date(form.scheduled_end).toISOString(),
          break_duration_min,
          status: form.status,
        })
      } else {
        if (form.selected_days.length === 0) { setError('Select at least one day'); setLoading(false); return }
        const st = form.start_time.length === 5 ? form.start_time + ':00' : form.start_time
        const et = form.end_time.length === 5   ? form.end_time   + ':00' : form.end_time
        await Promise.all(form.selected_days.map(day => {
          const dateStr = dateForWeekday(form.start_date, day)
          const scheduled_start = new Date(dateStr + 'T' + st).toISOString()
          const endDateStr = et <= st ? (() => { const d = new Date(dateStr + 'T00:00:00'); d.setDate(d.getDate() + 1); return d.toISOString().slice(0, 10) })() : dateStr
          const scheduled_end = new Date(endDateStr + 'T' + et).toISOString()
          return createShift(slug, {
            employee_id: form.employee_id,
            scheduled_start,
            scheduled_end,
            break_duration_min,
            status: form.status,
          })
        }))
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

          {editing ? (
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
          ) : (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Start Date <span className="text-red-500">*</span></label>
                <input type="date" required value={form.start_date}
                  onChange={e => setForm(f => ({ ...f, start_date: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Days</label>
                <div className="flex gap-1 flex-wrap">
                  {DAYS.map((d, i) => (
                    <button key={i} type="button" onClick={() => toggleDay(i)}
                      className={`px-2.5 py-1 rounded-full text-xs font-medium border transition-colors ${
                        form.selected_days.includes(i)
                          ? 'bg-blue-500 border-blue-500 text-white'
                          : 'bg-white border-gray-300 text-gray-600 hover:border-gray-400'
                      }`}>
                      {d}
                    </button>
                  ))}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Start Time <span className="text-red-500">*</span></label>
                  <input type="time" required value={form.start_time}
                    onChange={e => setForm(f => ({ ...f, start_time: e.target.value }))}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">End Time <span className="text-red-500">*</span></label>
                  <input type="time" required value={form.end_time}
                    onChange={e => setForm(f => ({ ...f, end_time: e.target.value }))}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
              </div>
            </>
          )}

          <div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Break Start</label>
                <input type="time" value={form.break_start}
                  onChange={e => setForm(f => ({ ...f, break_start: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Break End</label>
                <input type="time" value={form.break_end}
                  onChange={e => setForm(f => ({ ...f, break_end: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
            </div>
            <p className="text-xs text-gray-400 mt-1">Leave empty for no break</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Status</label>
            <select value={form.status} onChange={e => setForm(f => ({ ...f, status: e.target.value }))}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              {SHIFT_STATUS.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>

          <div className="flex gap-2 pt-2">
            <button type="button" onClick={onClose}
              className="flex-1 py-2 px-4 rounded-lg text-sm font-medium border border-gray-300 text-gray-700 hover:bg-gray-50">
              Cancel
            </button>
            <button type="submit" disabled={loading}
              className="btn-primary flex-1">
              {loading ? 'Saving…' : (editing ? 'Save' : 'Create Shift')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Breaks panel ──────────────────────────────────────────────────────────────

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
    try {
      await patchBreak(slug, shift.id, assignment.id, br.id, { break_end: new Date().toISOString() })
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
                    <p className="text-sm text-gray-900">
                      {fmtTime(br.break_start)} – {br.break_end
                        ? fmtTime(br.break_end)
                        : <span className="text-yellow-600">ongoing</span>
                      }
                    </p>
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
                  className="btn-primary flex-1 py-1.5">
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

// ── Assignments panel ─────────────────────────────────────────────────────────

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
                    className="btn-primary flex-1 py-1.5">
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
  const [success, setSuccess] = useState(null)

  async function handleGenerate(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await generateShifts(slug, { week_start_date: form.week_start_date })
      const count = Array.isArray(res) ? res.length : (res?.count ?? null)
      const msg = count !== null ? `${count} shift${count !== 1 ? 's' : ''} generated successfully.` : 'Shifts generated successfully.'
      setSuccess(msg)
      onDone()
      setTimeout(onClose, 2000)
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
          <p className="text-sm text-gray-600">This will create shift instances for the selected week based on all active shift patterns.</p>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Week starting (Monday)</label>
            <input type="date" required value={form.week_start_date}
              onChange={e => setForm({ week_start_date: e.target.value })}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          {error && <div className="bg-red-50 text-red-700 text-sm px-3 py-2 rounded-lg border border-red-200">{error}</div>}
          {success && <div className="bg-green-50 text-green-700 text-sm px-3 py-2 rounded-lg border border-green-200">{success}</div>}
          <div className="flex gap-2 pt-2">
            <button type="button" onClick={onClose}
              className="flex-1 py-2 px-4 rounded-lg text-sm font-medium border border-gray-300 text-gray-700 hover:bg-gray-50">
              {success ? 'Done' : 'Cancel'}
            </button>
            {!success && (
              <button type="submit" disabled={loading}
                className="btn-primary flex-1">
                {loading ? 'Generating…' : 'Generate'}
              </button>
            )}
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
  usePageTitle('Shifts')

  const [view, setView] = useState('list')
  const [shifts, setShifts] = useState([])
  const [employees, setEmployees] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [filterStatus, setFilterStatus] = useState('')
  const [filterDate, setFilterDate] = useState('')

  const [modal, setModal] = useState(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const params = {}
      if (filterStatus) params.status = filterStatus
      if (filterDate) {
        params.from_date = filterDate
        params.to_date = filterDate
      }
      const [sh, emps] = await Promise.all([
        listShifts(slug, params),
        listEmployees(slug, { active_only: true }),
      ])
      setShifts(sh)
      setEmployees(emps)
    } catch (err) {
      setError(err.response?.data?.detail?.error || err.message || 'Failed to load shifts')
    }
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
    <div className="page-enter flex flex-col h-full overflow-hidden">
      {/* Header */}
      <header className="px-6 py-4 border-b border-gray-200 bg-white flex items-center justify-between shrink-0">
        <div>
          <h1 className="page-title">Shifts</h1>
          <p className="page-subtitle">Manage shift instances, assignments and attendance</p>
        </div>
        <div className="flex items-center gap-2">
          <ViewToggle view={view} onChange={setView} />
          <Tooltip text="Automatically creates shift instances for the next 4 weeks based on saved shift pattern templates.">
            <button
              onClick={() => setModal('generate')}
              className="px-3 py-1.5 rounded-lg text-sm font-medium border border-gray-300 text-gray-700 hover:bg-gray-50 transition-colors"
            >
              Generate from Patterns
            </button>
          </Tooltip>
          <button
            onClick={() => setModal('create')}
            className="btn-primary"
          >
            + Create Shift
          </button>
        </div>
      </header>

      {/* Calendar view */}
      {view === 'calendar' ? (
        <div className="flex-1 overflow-hidden bg-gray-50">
          <CalendarView shifts={shifts} />
        </div>
      ) : (
        <>
          {/* List view filters */}
          <div className="px-6 py-3 border-b border-gray-100 bg-white flex items-end gap-3 shrink-0">
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Status</label>
              <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)}
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

          {/* List view table */}
          <div className="flex-1 overflow-auto p-6">
            {error ? (
              <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-center space-y-3">
                <RefreshCw size={28} className="mx-auto text-red-400" />
                <p className="text-sm font-medium text-red-700">{error}</p>
                <button onClick={fetchData} className="btn-outline text-xs py-1.5 border-red-300 text-red-600 hover:bg-red-100">
                  Retry
                </button>
              </div>
            ) : loading ? (
              <TableSkeleton rows={6} cols={6} />
            ) : shifts.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 text-center">
                <div className="w-16 h-16 rounded-full bg-blue-50 flex items-center justify-center mb-4">
                  <Calendar size={28} className="text-blue-400" />
                </div>
                <p className="text-base font-semibold text-gray-700 mb-1">No shifts found</p>
                <p className="text-sm text-gray-400 mb-5">
                  Create a shift manually or generate from saved shift patterns.
                </p>
                <div className="flex gap-2">
                  <button onClick={() => setModal('generate')}
                    className="btn-outline text-xs py-1.5">
                    Generate from Patterns
                  </button>
                  <button onClick={() => setModal('create')} className="btn-primary text-xs py-1.5">
                    + Create Shift
                  </button>
                </div>
              </div>
            ) : (
              <div className="bg-white border border-gray-100 rounded-xl overflow-hidden shadow-sm">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-gray-50 border-b border-gray-200">
                      <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">Employee</th>
                      <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">Scheduled</th>
                      <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider hidden md:table-cell">Actual</th>
                      <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">Status</th>
                      <th className="px-4 py-3"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {(() => {
                      // Group shifts by employee, preserving order of first appearance
                      const groups = []
                      const seen = {}
                      shifts.forEach(shift => {
                        const eid = shift.employee_id
                        if (!seen[eid]) { seen[eid] = []; groups.push({ eid, rows: seen[eid] }) }
                        seen[eid].push(shift)
                      })
                      return groups.flatMap(({ eid, rows }) =>
                        rows.map((shift, j) => (
                          <tr key={shift.id} className={`border-b border-gray-100 last:border-0 hover:bg-blue-50 transition-colors bg-white`}>
                            {j === 0 && (
                              <td rowSpan={rows.length} className="px-4 py-3 font-medium text-gray-900 align-top border-r border-gray-100">
                                {getEmployeeName(eid)}
                              </td>
                            )}
                            <td className="px-4 py-3 text-gray-500 text-xs whitespace-nowrap">
                              {fmt(shift.scheduled_start)}<br />
                              <span className="text-gray-400">→ {fmtTime(shift.scheduled_end)}</span>
                            </td>
                            <td className="px-4 py-3 text-gray-500 text-xs hidden md:table-cell">
                              {shift.actual_start ? (
                                <>{fmtTime(shift.actual_start)} → {shift.actual_end
                                  ? fmtTime(shift.actual_end)
                                  : <span className="text-green-600">ongoing</span>
                                }</>
                              ) : '—'}
                            </td>
                            <td className="px-4 py-3">
                              <span className={`text-xs px-3 py-1 rounded-full font-medium ${STATUS_BADGE[shift.status] || 'bg-gray-100 text-gray-600'}`}>
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
                        ))
                      )
                    })()}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}

      {/* Modals */}
      {modal === 'create' && (
        <ShiftModal slug={slug} employees={employees} onClose={() => setModal(null)} onDone={fetchData} />
      )}
      {modal === 'generate' && (
        <GenerateModal slug={slug} onClose={() => setModal(null)} onDone={fetchData} />
      )}
      {modal?.type === 'edit' && (
        <ShiftModal slug={slug} shift={modal.shift} employees={employees} onClose={() => setModal(null)} onDone={fetchData} />
      )}
      {modal?.type === 'assignments' && (
        <AssignmentsPanel slug={slug} shift={modal.shift} employees={employees} onClose={() => setModal(null)} />
      )}
    </div>
  )
}
