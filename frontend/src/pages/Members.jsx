import React, { useEffect, useState, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { Users, Clock, ShieldOff } from 'lucide-react'
import { useAuth } from '../store'
import { usePageTitle } from '../components/PageMeta'
import { TableSkeleton } from '../components/Skeletons'
import {
  listMembers, inviteMember, listInvitations,
  cancelInvitation, patchMember, removeMember,
  requestDraftDiscard, getDraft, listSections,
} from '../api'

const ROLE_COLORS = {
  admin:   'bg-purple-100 text-purple-700',
  manager: 'bg-blue-100 text-blue-700',
  viewer:  'bg-gray-100 text-gray-600',
  owner:   'bg-amber-100 text-amber-700',
}

function InviteModal({ slug, onClose, onDone }) {
  const [form, setForm] = useState({ email: '', role: 'manager', access_scope: 'full_store' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [token, setToken] = useState(null)
  const [sections, setSections] = useState([])
  const [selectedSections, setSelectedSections] = useState([])

  useEffect(() => {
    listSections(slug).then(setSections).catch(() => {})
  }, [slug])

  function onChange(e) {
    setForm(f => ({ ...f, [e.target.name]: e.target.value }))
  }

  function toggleSection(id) {
    setSelectedSections(prev =>
      prev.includes(id) ? prev.filter(s => s !== id) : [...prev, id]
    )
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await inviteMember(slug, {
        email: form.email.trim(),
        role: form.role,
        access_scope: form.access_scope,
        section_ids: form.access_scope === 'section_scoped' ? selectedSections : [],
        permissions: {},
      })
      setToken(res.token || null)
      onDone()
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to send invitation')
    } finally {
      setLoading(false)
    }
  }

  if (token) {
    return (
      <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4">
        <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6">
          <h3 className="font-semibold text-gray-900 mb-2">Invitation Sent</h3>
          <p className="text-sm text-gray-600 mb-3">
            Share this link with the invitee (dev mode — token shown here):
          </p>
          <div className="bg-gray-100 rounded-lg p-3 text-xs font-mono break-all text-gray-700 select-all">
            {`/store/${slug}/accept-invite?token=${token}`}
          </div>
          <button
            onClick={onClose}
            className="btn-primary mt-4 w-full"
          >
            Done
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <h3 className="font-semibold text-gray-900">Invite Member</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
        </div>

        <form onSubmit={handleSubmit} className="px-6 py-4 space-y-4">
          {error && (
            <div className="bg-red-50 text-red-700 text-sm px-3 py-2 rounded-lg border border-red-200">{error}</div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Email <span className="text-red-500">*</span></label>
            <input
              name="email"
              type="email"
              required
              value={form.email}
              onChange={onChange}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Role</label>
            <select
              name="role"
              value={form.role}
              onChange={onChange}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="manager">Manager</option>
              <option value="viewer">Viewer</option>
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Access Scope</label>
            <select
              name="access_scope"
              value={form.access_scope}
              onChange={onChange}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="full_store">All Sections</option>
              <option value="section_scoped">Specific Sections</option>
            </select>
          </div>

          {form.access_scope === 'section_scoped' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Sections</label>
              <div className="border border-gray-300 rounded-lg px-3 py-2 max-h-40 overflow-y-auto space-y-1.5">
                {sections.length === 0 ? (
                  <p className="text-xs text-gray-400">No sections available</p>
                ) : sections.map(s => (
                  <label key={s.id} className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={selectedSections.includes(s.id)}
                      onChange={() => toggleSection(s.id)}
                      className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                    <span className="text-sm text-gray-700">{s.name}</span>
                  </label>
                ))}
              </div>
            </div>
          )}

          <div className="flex gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 py-2 px-4 rounded-lg text-sm font-medium border border-gray-300 text-gray-700 hover:bg-gray-50 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="btn-primary flex-1"
            >
              {loading ? 'Sending…' : 'Send Invite'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function EditMemberModal({ slug, member, onClose, onDone }) {
  const [form, setForm] = useState({ role: member.role, access_scope: member.access_scope || 'full_store' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await patchMember(slug, member.id, form)
      onDone()
      onClose()
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to update member')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-sm">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <h3 className="font-semibold text-gray-900">Edit Member</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
        </div>

        <form onSubmit={handleSubmit} className="px-6 py-4 space-y-4">
          {error && (
            <div className="bg-red-50 text-red-700 text-sm px-3 py-2 rounded-lg border border-red-200">{error}</div>
          )}

          <p className="text-sm text-gray-600">{member.name || member.email}</p>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Role</label>
            <select
              value={form.role}
              onChange={e => setForm(f => ({ ...f, role: e.target.value }))}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="manager">Manager</option>
              <option value="viewer">Viewer</option>
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Access Scope</label>
            <select
              value={form.access_scope}
              onChange={e => setForm(f => ({ ...f, access_scope: e.target.value }))}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="full_store">All Sections</option>
              <option value="section_scoped">Specific Sections</option>
            </select>
          </div>

          <div className="flex gap-2 pt-2">
            <button type="button" onClick={onClose} className="flex-1 py-2 px-4 rounded-lg text-sm font-medium border border-gray-300 text-gray-700 hover:bg-gray-50">
              Cancel
            </button>
            <button type="submit" disabled={loading} className="btn-primary flex-1">
              {loading ? 'Saving…' : 'Save'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function Members() {
  const { slug } = useParams()
  const { state } = useAuth()
  const role = state.currentMember?.role || (state.user?.account_type === 'owner' ? 'owner' : null)
  usePageTitle('Members')

  const [members, setMembers] = useState([])
  const [invitations, setInvitations] = useState([])
  const [loading, setLoading] = useState(true)
  const [showInvite, setShowInvite] = useState(false)
  const [editMember, setEditMember] = useState(null)
  const [activeDraft, setActiveDraft] = useState(null)
  const [discardRequesting, setDiscardRequesting] = useState(false)
  const [discardSent, setDiscardSent] = useState(false)

  const fetchData = useCallback(() => {
    setLoading(true)
    Promise.all([
      listMembers(slug),
      listInvitations(slug),
      getDraft(slug).catch(() => null),
    ])
      .then(([m, inv, draft]) => {
        setMembers(m.members || m)
        setInvitations(inv.invitations || inv)
        setActiveDraft(draft)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [slug])

  async function handleRequestDraftDiscard() {
    if (!window.confirm('Send an email to the draft owner requesting they discard the current draft?')) return
    setDiscardRequesting(true)
    try {
      await requestDraftDiscard(slug)
      setDiscardSent(true)
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to send request')
    } finally {
      setDiscardRequesting(false)
    }
  }

  useEffect(() => { fetchData() }, [fetchData])

  if (role === 'viewer') {
    return (
      <div className="flex flex-col items-center justify-center h-full text-gray-400">
        <ShieldOff size={40} className="text-gray-300 mb-3" />
        <p className="text-lg font-medium text-gray-500">Access Restricted</p>
        <p className="text-sm mt-1">You don't have permission to view the members page.</p>
      </div>
    )
  }

  async function handleRemove(memberId) {
    if (!confirm('Remove this member from the store?')) return
    try {
      await removeMember(slug, memberId)
      setMembers(prev => prev.filter(m => m.id !== memberId))
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to remove member')
    }
  }

  async function handleCancelInvite(invId) {
    try {
      await cancelInvitation(slug, invId)
      setInvitations(prev => prev.filter(i => i.id !== invId))
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to cancel invitation')
    }
  }

  return (
    <div className="page-enter flex flex-col h-full overflow-auto">
      <header className="px-6 py-4 border-b border-gray-200 bg-white flex items-center justify-between shrink-0">
        <div>
          <h1 className="page-title">Members</h1>
          <p className="page-subtitle">Manage store access</p>
        </div>
        <button
          onClick={() => setShowInvite(true)}
          className="btn-primary"
        >
          + Invite
        </button>
      </header>

      <div className="flex-1 p-6 space-y-6">
        {loading ? (
          <TableSkeleton rows={6} />
        ) : (
          <>
            {/* Draft discard request — shown to managers when a draft exists */}
            {activeDraft && role === 'manager' && (
              <div className="bg-yellow-50 border border-yellow-200 rounded-xl px-4 py-3 flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-yellow-800">An active draft exists</p>
                  <p className="text-xs text-yellow-600 mt-0.5">
                    Draft: <span className="font-mono">{activeDraft.label || activeDraft.id}</span>
                  </p>
                </div>
                {discardSent ? (
                  <span className="text-xs text-green-700 bg-green-100 px-3 py-1.5 rounded-lg font-medium">Request sent</span>
                ) : (
                  <button
                    onClick={handleRequestDraftDiscard}
                    disabled={discardRequesting}
                    className="text-xs px-3 py-1.5 rounded-lg border border-yellow-400 text-yellow-800 hover:bg-yellow-100 transition-colors disabled:opacity-50 shrink-0"
                  >
                    {discardRequesting ? 'Sending…' : 'Request discard'}
                  </button>
                )}
              </div>
            )}

            {/* Active Members */}
            <section>
              <h2 className="text-sm font-semibold text-gray-700 mb-3">Active Members ({members.length})</h2>
              {members.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-14 text-center bg-white border border-gray-100 rounded-xl shadow-sm">
                  <div className="w-14 h-14 rounded-full bg-blue-50 flex items-center justify-center mb-3">
                    <Users size={24} className="text-blue-400" />
                  </div>
                  <p className="text-sm font-semibold text-gray-700 mb-1">No members yet</p>
                  <p className="text-xs text-gray-400 mb-4">Invite team members to give them access to this store.</p>
                  <button onClick={() => setShowInvite(true)} className="btn-primary text-xs py-1.5">
                    + Invite Member
                  </button>
                </div>
              ) : (
                <div className="bg-white border border-gray-100 rounded-xl overflow-hidden shadow-sm">
                  {members.map((m, i) => (
                    <div
                      key={m.id}
                      className={`flex items-center gap-3 px-4 py-3 border-b border-gray-100 last:border-0 hover:bg-blue-50 transition-colors ${i % 2 === 1 ? 'bg-gray-50/50' : 'bg-white'}`}
                    >
                      <div className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold text-white shrink-0"
                        style={{ backgroundColor: '#1B3A5C' }}>
                        {(m.name || m.email || '?')[0].toUpperCase()}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-gray-900 truncate">{m.name || '—'}</p>
                        <p className="text-xs text-gray-400 truncate">{m.email}</p>
                      </div>
                      <span className={`text-xs font-semibold px-2 py-0.5 rounded-full inline-block capitalize ${ROLE_COLORS[m.role] || ROLE_COLORS.viewer}`}>
                        {m.role}
                      </span>
                      <span className="text-xs px-3 py-1 rounded-full font-medium bg-green-100 text-green-700">
                        Active
                      </span>
                      {m.role !== 'owner' && String(m.user_id) !== String(state.user?.user_id) && (
                        <div className="flex gap-1 shrink-0">
                          <button
                            onClick={() => setEditMember(m)}
                            className="text-xs px-2 py-1 rounded text-blue-600 hover:bg-blue-100 transition-colors"
                          >
                            Edit
                          </button>
                          <button
                            onClick={() => handleRemove(m.id)}
                            className="text-xs px-2 py-1 rounded text-red-500 hover:bg-red-50 transition-colors"
                          >
                            Remove
                          </button>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </section>

            {/* Pending Invitations */}
            <section>
              <h2 className="text-sm font-semibold text-gray-700 mb-3">Pending Invitations ({invitations.length})</h2>
              {invitations.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-10 text-center bg-white border border-gray-100 rounded-xl shadow-sm">
                  <div className="w-12 h-12 rounded-full bg-blue-50 flex items-center justify-center mb-3">
                    <Clock size={20} className="text-blue-400" />
                  </div>
                  <p className="text-sm font-semibold text-gray-600 mb-1">No pending invitations</p>
                  <p className="text-xs text-gray-400">Invitations you send will appear here.</p>
                </div>
              ) : (
                <div className="bg-white border border-gray-100 rounded-xl overflow-hidden shadow-sm">
                  {invitations.map((inv, i) => (
                    <div
                      key={inv.id}
                      className={`flex items-center gap-3 px-4 py-3 border-b border-gray-100 last:border-0 hover:bg-blue-50 transition-colors ${i % 2 === 1 ? 'bg-gray-50/50' : 'bg-white'}`}
                    >
                      <div className="flex-1 min-w-0">
                        <p className="text-sm text-gray-900 truncate">{inv.email}</p>
                        <p className="text-xs text-gray-400 mt-0.5">
                          {inv.role} · expires {new Date(inv.expires_at).toLocaleDateString()}
                        </p>
                      </div>
                      <span className="text-xs bg-yellow-100 text-yellow-700 px-3 py-1 rounded-full font-medium">Pending</span>
                      <button
                        onClick={() => handleCancelInvite(inv.id)}
                        className="text-xs px-2 py-1 rounded text-red-500 hover:bg-red-50 transition-colors shrink-0"
                      >
                        Cancel
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </>
        )}
      </div>

      {showInvite && (
        <InviteModal
          slug={slug}
          onClose={() => setShowInvite(false)}
          onDone={() => { setShowInvite(false); fetchData() }}
        />
      )}

      {editMember && (
        <EditMemberModal
          slug={slug}
          member={editMember}
          onClose={() => setEditMember(null)}
          onDone={fetchData}
        />
      )}
    </div>
  )
}
