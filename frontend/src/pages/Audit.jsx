import React, { useEffect, useState, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { useAuth } from '../store'
import { getAuditLog } from '../api'

function CopyableId({ id }) {
  const [copied, setCopied] = useState(false)
  function handleCopy() {
    navigator.clipboard.writeText(id).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }
  return (
    <span className="relative group/id inline-block">
      <button
        onClick={handleCopy}
        title={id}
        className="text-xs text-gray-400 font-mono hover:text-blue-600 transition-colors cursor-pointer"
      >
        {id.slice(0, 8)}…
      </button>
      {copied && (
        <span className="absolute -top-6 left-0 bg-gray-800 text-white text-xs px-2 py-0.5 rounded whitespace-nowrap z-10">
          Copied!
        </span>
      )}
    </span>
  )
}

const ACTION_GROUPS = {
  Auth: ['login', 'logout', 'password_reset'],
  Store: ['store_created', 'store_updated'],
  Members: ['member_invited', 'member_removed', 'member_role_changed', 'permission_changed'],
  Config: ['draft_created', 'draft_discarded', 'draft_expired', 'config_edited', 'version_activated', 'version_rolled_back'],
  Employees: ['employee_created', 'employee_updated', 'employee_deleted', 'employee_section_assigned', 'employee_section_removed'],
  Shifts: ['shift_pattern_created', 'shift_pattern_updated', 'shift_pattern_deleted', 'shift_created', 'shift_updated', 'shift_deleted', 'shift_employee_assigned', 'shift_attendance_updated', 'break_created'],
}

function actionBadgeClass(action) {
  const label = actionLabel(action)
  if (label.includes('Deleted') || label.includes('Removed')) return 'bg-red-100 text-red-700'
  if (label.includes('Created') || label.includes('Activated') || label.includes('Login')) return 'bg-green-100 text-green-700'
  if (label.includes('Updated') || label.includes('Assigned') || label.includes('Changed')) return 'bg-amber-100 text-amber-700'
  return 'bg-gray-100 text-gray-600'
}

const ENTITY_TYPES = ['store', 'store_config_version', 'member', 'employee', 'employee_section', 'shift_pattern', 'shift_instance', 'shift_assignment', 'break_record']

function actionLabel(action) {
  return action.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function formatDate(iso) {
  const d = new Date(iso)
  return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

function StatePopover({ data, label }) {
  const [open, setOpen] = useState(false)
  if (!data || Object.keys(data).length === 0) return <span className="text-gray-300">—</span>
  return (
    <div className="relative inline-block">
      <button onClick={() => setOpen(o => !o)} className="text-xs text-blue-600 hover:underline">
        {label}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-5 z-50 bg-white border border-gray-200 rounded-lg shadow-lg p-3 w-64 max-h-48 overflow-auto">
            <pre className="text-xs text-gray-700 whitespace-pre-wrap">{JSON.stringify(data, null, 2)}</pre>
          </div>
        </>
      )}
    </div>
  )
}

const PAGE_SIZE = 50

export default function Audit() {
  const { slug } = useParams()
  const { state } = useAuth()
  const role = state.currentMember?.role || (state.user?.account_type === 'owner' ? 'owner' : null)

  const [entries, setEntries] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [filters, setFilters] = useState({ action: '', entity_type: '', since: '', until: '' })

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const params = { page, page_size: PAGE_SIZE }
      if (filters.action) params.action = filters.action
      if (filters.entity_type) params.entity_type = filters.entity_type
      if (filters.since) params.since = new Date(filters.since).toISOString()
      if (filters.until) params.until = new Date(filters.until).toISOString()
      const data = await getAuditLog(slug, params)
      setEntries(data.items)
      setTotal(data.total)
    } catch (err) {
      setError(err.response?.data?.detail?.error || 'Failed to load audit log')
    } finally {
      setLoading(false)
    }
  }, [slug, page, filters])

  useEffect(() => { fetchData() }, [fetchData])

  function handleFilterChange(e) {
    setFilters(f => ({ ...f, [e.target.name]: e.target.value }))
    setPage(1)
  }

  function clearFilters() {
    setFilters({ action: '', entity_type: '', since: '', until: '' })
    setPage(1)
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const hasFilters = Object.values(filters).some(v => v !== '')

  if (role === 'viewer') {
    return (
      <div className="flex flex-col items-center justify-center h-full text-gray-400">
        <p className="text-lg font-medium text-gray-500">Access Restricted</p>
        <p className="text-sm mt-1">You don't have permission to view the audit log.</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full overflow-auto">
      <header className="px-6 py-4 border-b border-gray-200 bg-white flex items-center justify-between shrink-0">
        <div>
          <h1 className="font-semibold text-gray-900">Audit Log</h1>
          <p className="text-xs text-gray-400 mt-0.5">{total} total events</p>
        </div>
        <button onClick={fetchData}
          className="text-sm text-gray-500 hover:text-gray-700 px-3 py-1.5 rounded-lg border border-gray-200 hover:bg-gray-50 transition-colors">
          Refresh
        </button>
      </header>

      {/* Filters */}
      <div className="px-6 py-3 border-b border-gray-100 bg-white flex flex-wrap items-end gap-3 shrink-0">
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Action</label>
          <select name="action" value={filters.action} onChange={handleFilterChange}
            className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="">All actions</option>
            {Object.entries(ACTION_GROUPS).map(([group, actions]) => (
              <optgroup key={group} label={group}>
                {actions.map(a => <option key={a} value={a}>{actionLabel(a)}</option>)}
              </optgroup>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Entity Type</label>
          <select name="entity_type" value={filters.entity_type} onChange={handleFilterChange}
            className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="">All types</option>
            {ENTITY_TYPES.map(t => <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>)}
          </select>
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">From</label>
          <input type="datetime-local" name="since" value={filters.since} onChange={handleFilterChange}
            className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Until</label>
          <input type="datetime-local" name="until" value={filters.until} onChange={handleFilterChange}
            className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>

        {hasFilters && (
          <button onClick={clearFilters}
            className="text-sm text-gray-500 hover:text-gray-700 px-3 py-1.5 rounded-lg border border-gray-200 hover:bg-gray-50 transition-colors">
            Clear filters
          </button>
        )}
      </div>

      {/* Table */}
      <div className="flex-1 p-6 min-h-0">
        {error && (
          <div className="bg-red-50 text-red-700 text-sm px-4 py-3 rounded-lg border border-red-200 mb-4">{error}</div>
        )}

        {loading ? (
          <div className="text-sm text-gray-400 py-8 text-center">Loading…</div>
        ) : entries.length === 0 ? (
          <div className="text-sm text-gray-400 py-8 text-center">
            {hasFilters ? 'No events match your filters.' : 'No audit events yet.'}
          </div>
        ) : (
          <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase tracking-wide">Time</th>
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase tracking-wide">Action</th>
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase tracking-wide hidden md:table-cell">Entity</th>
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase tracking-wide hidden lg:table-cell">User</th>
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase tracking-wide hidden lg:table-cell">Changes</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry, i) => (
                  <tr key={entry.id} className={`${i < entries.length - 1 ? 'border-b border-gray-100' : ''} hover:bg-gray-50 transition-colors`}>
                    <td className="px-4 py-3 text-gray-500 whitespace-nowrap text-xs">{formatDate(entry.created_at)}</td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${actionBadgeClass(entry.action)}`}>
                        {actionLabel(entry.action)}
                      </span>
                    </td>
                    <td className="px-4 py-3 hidden md:table-cell">
                      {entry.entity_type ? (
                        <div>
                          <span className="text-xs text-gray-600">{entry.entity_type.replace(/_/g, ' ')}</span>
                          {entry.entity_id && (
                            <p><CopyableId id={entry.entity_id} /></p>
                          )}
                        </div>
                      ) : <span className="text-gray-300">—</span>}
                    </td>
                    <td className="px-4 py-3 hidden lg:table-cell">
                      {entry.user_id
                        ? <CopyableId id={entry.user_id} />
                        : <span className="text-gray-300">—</span>}
                    </td>
                    <td className="px-4 py-3 hidden lg:table-cell">
                      <div className="flex gap-2">
                        {entry.before_state && <StatePopover data={entry.before_state} label="Before" />}
                        {entry.after_state && <StatePopover data={entry.after_state} label="After" />}
                        {!entry.before_state && !entry.after_state && <span className="text-gray-300">—</span>}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination */}
        {!loading && totalPages > 1 && (
          <div className="flex items-center justify-between mt-4">
            <p className="text-sm text-gray-500">
              Page {page} of {totalPages} · {total} events
            </p>
            <div className="flex gap-2">
              <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}
                className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
                Previous
              </button>
              <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page === totalPages}
                className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
                Next
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
