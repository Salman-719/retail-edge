import React, { useEffect, useState, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { ExternalLink } from 'lucide-react'
import { useAuth } from '../store'
import { getAuditLog } from '../api'
import { usePageTitle } from '../components/PageMeta'
import { TableSkeleton } from '../components/Skeletons'

// ── Helpers ───────────────────────────────────────────────────────────────────

function actionLabel(action) {
  return action.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function actionBadgeClass(action) {
  const label = actionLabel(action)
  if (label.includes('Deleted') || label.includes('Removed'))
    return 'border-l-4 border-red-500 bg-red-50 text-red-700'
  if (label.includes('Created') || label.includes('Activated') || label.includes('Login'))
    return 'border-l-4 border-green-500 bg-green-50 text-green-700'
  if (label.includes('Updated') || label.includes('Assigned') || label.includes('Changed'))
    return 'border-l-4 border-amber-500 bg-amber-50 text-amber-700'
  return 'border-l-4 border-gray-300 bg-gray-50 text-gray-600'
}

function formatDate(iso) {
  const d = new Date(iso)
  return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

function relativeTime(iso) {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  return `${Math.floor(days / 30)}mo ago`
}

// ── Sub-components ────────────────────────────────────────────────────────────

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

function TimeCell({ iso }) {
  return (
    <span className="relative group/time cursor-default">
      <span className="text-xs text-gray-500 whitespace-nowrap">
        {formatDate(iso)}
      </span>
      {/* Tooltip: relative time */}
      <span className="pointer-events-none absolute bottom-full left-0 mb-1.5 px-2 py-1 bg-gray-800 text-white text-xs rounded whitespace-nowrap opacity-0 group-hover/time:opacity-100 transition-opacity z-10">
        {relativeTime(iso)}
      </span>
    </span>
  )
}

function StatePopover({ data, label }) {
  const [open, setOpen] = useState(false)
  if (!data || Object.keys(data).length === 0) return <span className="text-gray-300">—</span>
  return (
    <div className="relative inline-block">
      <button
        onClick={() => setOpen(o => !o)}
        className="inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800 underline underline-offset-2 transition-colors"
      >
        {label === 'After' ? 'View changes' : label}
        <ExternalLink size={10} />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-6 z-50 bg-white border border-gray-200 rounded-lg shadow-lg p-3 w-64 max-h-48 overflow-auto">
            <pre className="text-xs text-gray-700 whitespace-pre-wrap">{JSON.stringify(data, null, 2)}</pre>
          </div>
        </>
      )}
    </div>
  )
}

// ── Constants ─────────────────────────────────────────────────────────────────

const ACTION_GROUPS = {
  Auth: ['login', 'logout', 'password_reset'],
  Store: ['store_created', 'store_updated'],
  Members: ['member_invited', 'member_removed', 'member_role_changed', 'permission_changed'],
  Config: ['draft_created', 'draft_discarded', 'draft_expired', 'config_edited', 'version_activated', 'version_rolled_back'],
  Employees: ['employee_created', 'employee_updated', 'employee_deleted', 'employee_section_assigned', 'employee_section_removed'],
  Shifts: ['shift_pattern_created', 'shift_pattern_updated', 'shift_pattern_deleted', 'shift_created', 'shift_updated', 'shift_deleted', 'shift_employee_assigned', 'shift_attendance_updated', 'break_created'],
}

const ENTITY_TYPES = ['store', 'store_config_version', 'member', 'employee', 'employee_section', 'shift_pattern', 'shift_instance', 'shift_assignment', 'break_record']

const PAGE_SIZE = 50

const INPUT_CLS = 'border border-gray-200 rounded-lg px-2.5 py-1.5 text-sm bg-white focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 transition-shadow'

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Audit() {
  const { slug } = useParams()
  const { state } = useAuth()
  const role = state.currentMember?.role || (state.user?.account_type === 'owner' ? 'owner' : null)
  usePageTitle('Audit Log')

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
          <h1 className="page-title">Audit Log</h1>
          <p className="page-subtitle">{total} total events</p>
        </div>
        <button onClick={fetchData} className="btn-outline text-xs py-1.5">
          Refresh
        </button>
      </header>

      {/* Filter card */}
      <div className="px-6 py-4 shrink-0">
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 px-5 py-4 flex flex-wrap items-end gap-4">
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1.5">Action</label>
            <select name="action" value={filters.action} onChange={handleFilterChange} className={INPUT_CLS}>
              <option value="">All actions</option>
              {Object.entries(ACTION_GROUPS).map(([group, actions]) => (
                <optgroup key={group} label={group}>
                  {actions.map(a => <option key={a} value={a}>{actionLabel(a)}</option>)}
                </optgroup>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1.5">Entity Type</label>
            <select name="entity_type" value={filters.entity_type} onChange={handleFilterChange} className={INPUT_CLS}>
              <option value="">All types</option>
              {ENTITY_TYPES.map(t => <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>)}
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1.5">From</label>
            <input type="datetime-local" name="since" value={filters.since} onChange={handleFilterChange} className={INPUT_CLS} />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1.5">Until</label>
            <input type="datetime-local" name="until" value={filters.until} onChange={handleFilterChange} className={INPUT_CLS} />
          </div>

          {/* Spacer + clear link */}
          <div className="flex-1 flex justify-end items-end">
            {hasFilters && (
              <button
                onClick={clearFilters}
                className="text-sm text-blue-600 hover:text-blue-800 transition-colors font-medium"
              >
                Clear filters
              </button>
            )}
          </div>
        </div>

        {/* Row count indicator */}
        {!loading && (
          <p className="text-sm text-gray-500 mt-2 pl-1">
            {entries.length > 0
              ? `Showing ${entries.length} of ${total} event${total !== 1 ? 's' : ''}`
              : hasFilters
                ? 'No events match your filters.'
                : 'No audit events yet.'
            }
          </p>
        )}
      </div>

      {/* Table */}
      <div className="flex-1 px-6 pb-6 min-h-0">
        {error && (
          <div className="bg-red-50 text-red-700 text-sm px-4 py-3 rounded-lg border border-red-200 mb-4">{error}</div>
        )}

        {loading ? (
          <TableSkeleton rows={8} cols={5} />
        ) : entries.length > 0 && (
          <div className="bg-white border border-gray-100 rounded-xl overflow-hidden shadow-sm">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">Time</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">Action</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider hidden md:table-cell">Entity</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider hidden lg:table-cell">User</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider hidden lg:table-cell">Changes</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry, i) => (
                  <tr
                    key={entry.id}
                    className={`border-b border-gray-100 last:border-0 hover:bg-blue-50 transition-colors ${i % 2 === 1 ? 'bg-gray-50/50' : 'bg-white'}`}
                  >
                    <td className="px-4 py-3">
                      <TimeCell iso={entry.created_at} />
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-block rounded-r-full px-3 py-1 text-xs font-medium ${actionBadgeClass(entry.action)}`}>
                        {actionLabel(entry.action)}
                      </span>
                    </td>
                    <td className="px-4 py-3 hidden md:table-cell">
                      {entry.entity_type ? (
                        <div>
                          <span className="text-xs text-gray-600 capitalize">{entry.entity_type.replace(/_/g, ' ')}</span>
                          {entry.entity_id && <p><CopyableId id={entry.entity_id} /></p>}
                        </div>
                      ) : <span className="text-gray-300">—</span>}
                    </td>
                    <td className="px-4 py-3 hidden lg:table-cell">
                      {entry.user_id ? <CopyableId id={entry.user_id} /> : <span className="text-gray-300">—</span>}
                    </td>
                    <td className="px-4 py-3 hidden lg:table-cell">
                      <div className="flex flex-col gap-1">
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
              <button
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page === 1}
                className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Previous
              </button>
              <button
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
