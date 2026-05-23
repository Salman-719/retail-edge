import React, { useEffect, useState, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { useAuth } from '../store'
import {
  listEmployees, createEmployee, patchEmployee, deleteEmployee,
  listEmployeeSections, assignEmployeeSection, removeEmployeeSection,
  listShiftPatterns, createShiftPattern, patchShiftPattern, deleteShiftPattern,
  listSections,
} from '../api'

const ROLES = ['cashier', 'shelf_stocker', 'supervisor', 'security', 'cleaner', 'manager', 'delivery', 'customer_service']
const ROLE_LABEL = Object.fromEntries(ROLES.map(r => [r, r.replace('_', ' ').replace(/\b\w/g, c => c.toUpperCase())]))
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const ROLE_BADGE = {
  manager: 'bg-blue-100 text-blue-700',
  supervisor: 'bg-purple-100 text-purple-700',
  cashier: 'bg-green-100 text-green-700',
  security: 'bg-red-100 text-red-700',
  shelf_stocker: 'bg-yellow-100 text-yellow-700',
  cleaner: 'bg-gray-100 text-gray-600',
  delivery: 'bg-orange-100 text-orange-700',
  customer_service: 'bg-teal-100 text-teal-700',
}

function EmployeeModal({ slug, employee, onClose, onDone }) {
  const editing = !!employee
  const [form, setForm] = useState({
    name: employee?.name || '',
    role: employee?.role || 'cashier',
    employee_code: employee?.employee_code || '',
    phone: employee?.phone || '',
    email: employee?.email || '',
  })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  function onChange(e) {
    setForm(f => ({ ...f, [e.target.name]: e.target.value }))
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    const body = {
      name: form.name.trim(),
      role: form.role,
      employee_code: form.employee_code.trim() || null,
      phone: form.phone.trim() || null,
      email: form.email.trim() || null,
    }
    try {
      if (editing) {
        await patchEmployee(slug, employee.id, body)
      } else {
        await createEmployee(slug, body)
      }
      onDone()
      onClose()
    } catch (err) {
      const detail = err.response?.data?.detail
      setError(typeof detail === 'object' ? detail.error : (detail || 'Request failed'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <h3 className="font-semibold text-gray-900">{editing ? 'Edit Employee' : 'Add Employee'}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
        </div>

        <form onSubmit={handleSubmit} className="px-6 py-4 space-y-3">
          {error && (
            <div className="bg-red-50 text-red-700 text-sm px-3 py-2 rounded-lg border border-red-200">{error}</div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Name <span className="text-red-500">*</span></label>
            <input name="name" required value={form.name} onChange={onChange}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Role</label>
            <select name="role" value={form.role} onChange={onChange}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              {ROLES.map(r => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Employee Code</label>
            <input name="employee_code" value={form.employee_code} onChange={onChange} placeholder="e.g. EMP001"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Phone</label>
              <input name="phone" value={form.phone} onChange={onChange} type="tel"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
              <input name="email" value={form.email} onChange={onChange} type="email"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
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
              {loading ? 'Saving…' : (editing ? 'Save' : 'Add Employee')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function SectionsPanel({ slug, employee, sections, onClose }) {
  const [assignments, setAssignments] = useState([])
  const [loading, setLoading] = useState(true)
  const [adding, setAdding] = useState(false)
  const [selectedSection, setSelectedSection] = useState('')
  const [isPrimary, setIsPrimary] = useState(false)
  const [error, setError] = useState('')

  const fetchAssignments = useCallback(async () => {
    setLoading(true)
    try {
      const data = await listEmployeeSections(slug, employee.id)
      setAssignments(data)
    } catch {}
    setLoading(false)
  }, [slug, employee.id])

  useEffect(() => { fetchAssignments() }, [fetchAssignments])

  const assignedIds = new Set(assignments.map(a => a.section_id))
  const availableSections = sections.filter(s => !assignedIds.has(s.id))

  async function handleAssign() {
    if (!selectedSection) return
    setError('')
    try {
      await assignEmployeeSection(slug, employee.id, {
        section_id: selectedSection,
        is_primary: isPrimary,
      })
      setAdding(false)
      setSelectedSection('')
      setIsPrimary(false)
      fetchAssignments()
    } catch (err) {
      const detail = err.response?.data?.detail
      setError(typeof detail === 'object' ? detail.error : (detail || 'Failed'))
    }
  }

  async function handleRemove(sectionId) {
    try {
      await removeEmployeeSection(slug, employee.id, sectionId)
      setAssignments(prev => prev.filter(a => a.section_id !== sectionId))
    } catch (err) {
      alert(err.response?.data?.detail?.error || 'Failed to remove section')
    }
  }

  function getSectionName(sectionId) {
    return sections.find(s => s.id === sectionId)?.name || sectionId.slice(0, 8)
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <div>
            <h3 className="font-semibold text-gray-900">Section Assignments</h3>
            <p className="text-xs text-gray-400 mt-0.5">{employee.name}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
        </div>

        <div className="px-6 py-4 space-y-3">
          {loading ? (
            <p className="text-sm text-gray-400 text-center py-4">Loading…</p>
          ) : assignments.length === 0 ? (
            <p className="text-sm text-gray-400">No sections assigned yet.</p>
          ) : (
            <div className="space-y-1">
              {assignments.map(a => (
                <div key={a.id} className="flex items-center justify-between bg-gray-50 rounded-lg px-3 py-2">
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-gray-900">{getSectionName(a.section_id)}</span>
                    {a.is_primary && (
                      <span className="text-xs bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded font-medium">Primary</span>
                    )}
                  </div>
                  <button onClick={() => handleRemove(a.section_id)}
                    className="text-xs text-red-500 hover:text-red-700 px-2 py-1 rounded hover:bg-red-50">
                    Remove
                  </button>
                </div>
              ))}
            </div>
          )}

          {error && <div className="bg-red-50 text-red-700 text-sm px-3 py-2 rounded-lg border border-red-200">{error}</div>}

          {adding ? (
            <div className="border border-gray-200 rounded-lg p-3 space-y-2">
              <select value={selectedSection} onChange={e => setSelectedSection(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option value="">Select section…</option>
                {availableSections.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
              <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                <input type="checkbox" checked={isPrimary} onChange={e => setIsPrimary(e.target.checked)}
                  className="rounded" />
                Set as primary section
              </label>
              <div className="flex gap-2">
                <button onClick={() => { setAdding(false); setError('') }}
                  className="flex-1 py-1.5 text-sm border border-gray-300 rounded-lg text-gray-600 hover:bg-gray-50">
                  Cancel
                </button>
                <button onClick={handleAssign} disabled={!selectedSection}
                  className="flex-1 py-1.5 text-sm font-semibold text-white rounded-lg disabled:opacity-40"
                  style={{ backgroundColor: '#1B3A5C' }}>
                  Assign
                </button>
              </div>
            </div>
          ) : (
            availableSections.length > 0 && (
              <button onClick={() => setAdding(true)}
                className="w-full py-2 text-sm border-2 border-dashed border-gray-300 rounded-lg text-gray-500 hover:border-gray-400 hover:text-gray-700 transition-colors">
                + Assign Section
              </button>
            )
          )}
        </div>
      </div>
    </div>
  )
}

function ShiftPatternsPanel({ slug, employee, sections, onClose }) {
  const [patterns, setPatterns] = useState([])
  const [loading, setLoading] = useState(true)
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState({ section_id: '', day_of_week: 0, start_time: '09:00', end_time: '17:00', break_duration_min: 0 })
  const [error, setError] = useState('')

  const fetchPatterns = useCallback(async () => {
    setLoading(true)
    try {
      const data = await listShiftPatterns(slug, { employee_id: employee.id })
      setPatterns(data)
    } catch {}
    setLoading(false)
  }, [slug, employee.id])

  useEffect(() => { fetchPatterns() }, [fetchPatterns])

  async function handleCreate() {
    if (!form.section_id) { setError('Select a section'); return }
    setError('')
    try {
      await createShiftPattern(slug, {
        employee_id: employee.id,
        section_id: form.section_id,
        day_of_week: Number(form.day_of_week),
        start_time: form.start_time,
        end_time: form.end_time,
        break_duration_min: Number(form.break_duration_min),
      })
      setAdding(false)
      setForm({ section_id: '', day_of_week: 0, start_time: '09:00', end_time: '17:00', break_duration_min: 0 })
      fetchPatterns()
    } catch (err) {
      const detail = err.response?.data?.detail
      setError(typeof detail === 'object' ? detail.error : (detail || 'Failed'))
    }
  }

  async function handleToggle(pattern) {
    try {
      await patchShiftPattern(slug, pattern.id, { is_active: !pattern.is_active })
      setPatterns(prev => prev.map(p => p.id === pattern.id ? { ...p, is_active: !p.is_active } : p))
    } catch {}
  }

  async function handleDelete(patternId) {
    if (!confirm('Delete this shift pattern?')) return
    try {
      await deleteShiftPattern(slug, patternId)
      setPatterns(prev => prev.filter(p => p.id !== patternId))
    } catch {}
  }

  function getSectionName(sectionId) {
    return sections.find(s => s.id === sectionId)?.name || sectionId.slice(0, 8)
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <div>
            <h3 className="font-semibold text-gray-900">Shift Patterns</h3>
            <p className="text-xs text-gray-400 mt-0.5">{employee.name}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
        </div>

        <div className="px-6 py-4 space-y-3 max-h-[60vh] overflow-y-auto">
          {loading ? (
            <p className="text-sm text-gray-400 text-center py-4">Loading…</p>
          ) : patterns.length === 0 ? (
            <p className="text-sm text-gray-400">No shift patterns yet.</p>
          ) : (
            <div className="space-y-2">
              {patterns.map(p => (
                <div key={p.id} className={`flex items-center gap-3 rounded-lg px-3 py-2 border ${p.is_active ? 'border-gray-200 bg-gray-50' : 'border-gray-100 bg-white opacity-50'}`}>
                  <div className="w-10 text-center">
                    <span className="text-xs font-semibold text-gray-700 bg-gray-200 rounded px-1.5 py-0.5">{DAYS[p.day_of_week]}</span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-gray-900">{getSectionName(p.section_id)}</p>
                    <p className="text-xs text-gray-400">
                      {p.start_time.slice(0, 5)} – {p.end_time.slice(0, 5)}
                      {p.break_duration_min > 0 && ` · ${p.break_duration_min}min break`}
                    </p>
                  </div>
                  <div className="flex gap-1 shrink-0">
                    <button onClick={() => handleToggle(p)}
                      className={`text-xs px-2 py-1 rounded transition-colors ${p.is_active ? 'text-gray-500 hover:bg-gray-100' : 'text-blue-600 hover:bg-blue-50'}`}>
                      {p.is_active ? 'Disable' : 'Enable'}
                    </button>
                    <button onClick={() => handleDelete(p.id)}
                      className="text-xs px-2 py-1 rounded text-red-500 hover:bg-red-50">
                      Delete
                    </button>
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
                  <label className="block text-xs font-medium text-gray-600 mb-1">Section</label>
                  <select value={form.section_id} onChange={e => setForm(f => ({ ...f, section_id: e.target.value }))}
                    className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                    <option value="">Select…</option>
                    {sections.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Day</label>
                  <select value={form.day_of_week} onChange={e => setForm(f => ({ ...f, day_of_week: e.target.value }))}
                    className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                    {DAYS.map((d, i) => <option key={i} value={i}>{d}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Start</label>
                  <input type="time" value={form.start_time} onChange={e => setForm(f => ({ ...f, start_time: e.target.value }))}
                    className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">End</label>
                  <input type="time" value={form.end_time} onChange={e => setForm(f => ({ ...f, end_time: e.target.value }))}
                    className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Break (minutes)</label>
                <input type="number" min="0" max="480" value={form.break_duration_min}
                  onChange={e => setForm(f => ({ ...f, break_duration_min: e.target.value }))}
                  className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div className="flex gap-2">
                <button onClick={() => { setAdding(false); setError('') }}
                  className="flex-1 py-1.5 text-sm border border-gray-300 rounded-lg text-gray-600 hover:bg-gray-50">
                  Cancel
                </button>
                <button onClick={handleCreate}
                  className="flex-1 py-1.5 text-sm font-semibold text-white rounded-lg"
                  style={{ backgroundColor: '#1B3A5C' }}>
                  Add Pattern
                </button>
              </div>
            </div>
          ) : (
            <button onClick={() => setAdding(true)}
              className="w-full py-2 text-sm border-2 border-dashed border-gray-300 rounded-lg text-gray-500 hover:border-gray-400 hover:text-gray-700 transition-colors">
              + Add Shift Pattern
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export default function Employees() {
  const { slug } = useParams()
  const { state } = useAuth()
  const role = state.currentMember?.role || (state.user?.account_type === 'owner' ? 'owner' : null)

  const [employees, setEmployees] = useState([])
  const [sections, setSections] = useState([])
  const [loading, setLoading] = useState(true)
  const [showAll, setShowAll] = useState(false)
  const [modal, setModal] = useState(null) // null | 'create' | { type: 'edit'|'sections'|'patterns', employee }
  const [search, setSearch] = useState('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const [emps, secs] = await Promise.all([
        listEmployees(slug, { active_only: showAll ? false : true }),
        listSections(slug),
      ])
      setEmployees(emps)
      setSections(secs)
    } catch {}
    setLoading(false)
  }, [slug, showAll])

  useEffect(() => { fetchData() }, [fetchData])

  if (role === 'viewer') {
    return (
      <div className="flex flex-col items-center justify-center h-full text-gray-400">
        <p className="text-lg font-medium text-gray-500">Access Restricted</p>
        <p className="text-sm mt-1">You don't have permission to view employees.</p>
      </div>
    )
  }

  async function handleDeactivate(emp) {
    if (!confirm(`Deactivate ${emp.name}?`)) return
    try {
      await patchEmployee(slug, emp.id, { is_active: false })
      fetchData()
    } catch (err) {
      alert(err.response?.data?.detail?.error || 'Failed to deactivate')
    }
  }

  async function handleReactivate(emp) {
    try {
      await patchEmployee(slug, emp.id, { is_active: true })
      fetchData()
    } catch {}
  }

  async function handleDelete(emp) {
    if (!confirm(`Permanently delete ${emp.name}? This cannot be undone.`)) return
    try {
      await deleteEmployee(slug, emp.id)
      fetchData()
    } catch (err) {
      alert(err.response?.data?.detail?.error || 'Failed to delete')
    }
  }

  const filtered = employees.filter(e =>
    e.name.toLowerCase().includes(search.toLowerCase()) ||
    (e.employee_code || '').toLowerCase().includes(search.toLowerCase()) ||
    e.role.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div className="flex flex-col h-full overflow-auto">
      <header className="px-6 py-4 border-b border-gray-200 bg-white flex items-center justify-between shrink-0">
        <div>
          <h1 className="font-semibold text-gray-900">Employees</h1>
          <p className="text-xs text-gray-400 mt-0.5">Manage staff, sections and schedules</p>
        </div>
        <button
          onClick={() => setModal('create')}
          className="px-3 py-1.5 rounded-lg text-sm font-semibold text-white"
          style={{ backgroundColor: '#1B3A5C' }}>
          + Add Employee
        </button>
      </header>

      <div className="px-6 py-3 border-b border-gray-100 bg-white flex items-center gap-3 shrink-0">
        <input
          type="search"
          placeholder="Search by name, code or role…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="flex-1 border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer whitespace-nowrap">
          <input type="checkbox" checked={showAll} onChange={e => setShowAll(e.target.checked)} className="rounded" />
          Show inactive
        </label>
      </div>

      <div className="flex-1 p-6">
        {loading ? (
          <div className="text-sm text-gray-400 py-8 text-center">Loading…</div>
        ) : filtered.length === 0 ? (
          <div className="text-sm text-gray-400 py-8 text-center">
            {search ? 'No employees match your search.' : 'No employees yet. Add one to get started.'}
          </div>
        ) : (
          <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase tracking-wide">Name</th>
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase tracking-wide">Role</th>
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase tracking-wide hidden sm:table-cell">Code</th>
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase tracking-wide hidden md:table-cell">Status</th>
                  <th className="px-4 py-2.5"></th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((emp, i) => (
                  <tr key={emp.id} className={`${i < filtered.length - 1 ? 'border-b border-gray-100' : ''} ${!emp.is_active ? 'opacity-50' : ''}`}>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2.5">
                        <div className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold text-white shrink-0"
                          style={{ backgroundColor: emp.is_active ? '#1B3A5C' : '#9ca3af' }}>
                          {emp.name[0].toUpperCase()}
                        </div>
                        <div className="min-w-0">
                          <p className="font-medium text-gray-900 truncate">{emp.name}</p>
                          {emp.email && <p className="text-xs text-gray-400 truncate">{emp.email}</p>}
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${ROLE_BADGE[emp.role] || 'bg-gray-100 text-gray-600'}`}>
                        {ROLE_LABEL[emp.role] || emp.role}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-500 hidden sm:table-cell">{emp.employee_code || '—'}</td>
                    <td className="px-4 py-3 hidden md:table-cell">
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${emp.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
                        {emp.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          onClick={() => setModal({ type: 'sections', employee: emp })}
                          className="text-xs px-2 py-1 rounded text-gray-600 hover:bg-gray-100 transition-colors">
                          Sections
                        </button>
                        <button
                          onClick={() => setModal({ type: 'patterns', employee: emp })}
                          className="text-xs px-2 py-1 rounded text-gray-600 hover:bg-gray-100 transition-colors">
                          Shifts
                        </button>
                        <button
                          onClick={() => setModal({ type: 'edit', employee: emp })}
                          className="text-xs px-2 py-1 rounded text-blue-600 hover:bg-blue-50 transition-colors">
                          Edit
                        </button>
                        {emp.is_active ? (
                          <button
                            onClick={() => handleDeactivate(emp)}
                            className="text-xs px-2 py-1 rounded text-orange-500 hover:bg-orange-50 transition-colors">
                            Deactivate
                          </button>
                        ) : (
                          <button
                            onClick={() => handleReactivate(emp)}
                            className="text-xs px-2 py-1 rounded text-green-600 hover:bg-green-50 transition-colors">
                            Reactivate
                          </button>
                        )}
                        <button
                          onClick={() => handleDelete(emp)}
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
        <EmployeeModal slug={slug} onClose={() => setModal(null)} onDone={fetchData} />
      )}
      {modal?.type === 'edit' && (
        <EmployeeModal slug={slug} employee={modal.employee} onClose={() => setModal(null)} onDone={fetchData} />
      )}
      {modal?.type === 'sections' && (
        <SectionsPanel slug={slug} employee={modal.employee} sections={sections} onClose={() => setModal(null)} />
      )}
      {modal?.type === 'patterns' && (
        <ShiftPatternsPanel slug={slug} employee={modal.employee} sections={sections} onClose={() => setModal(null)} />
      )}
    </div>
  )
}
