import React, { useEffect, useState } from 'react'
import { useNavigate, Navigate } from 'react-router-dom'
import { useAuth } from '../store'
import { listStores, createStore, patchStore, logout } from '../api'

const TIMEZONES = [
  'UTC', 'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles',
  'Europe/London', 'Europe/Paris', 'Europe/Berlin', 'Asia/Dubai', 'Asia/Beirut',
  'Asia/Tokyo', 'Asia/Singapore', 'Australia/Sydney',
]

const CURRENCIES = ['USD', 'LBP']

const STATUS_COLORS = {
  active: 'bg-green-100 text-green-700',
  inactive: 'bg-gray-100 text-gray-500',
  onboarding: 'bg-yellow-100 text-yellow-700',
}

function slugify(name) {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
}

export default function OwnerDashboard() {
  const { state, dispatch } = useAuth()
  const navigate = useNavigate()

  if (state.ready && state.user?.account_type !== 'owner') {
    return <Navigate to="/login" replace />
  }
  const [stores, setStores] = useState([])
  const [loadingStores, setLoadingStores] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [editStore, setEditStore] = useState(null)
  const [form, setForm] = useState({ name: '', slug: '', timezone: 'UTC', currency: 'USD', address: '' })
  const [formError, setFormError] = useState('')
  const [creating, setCreating] = useState(false)
  const [editForm, setEditForm] = useState({ name: '', timezone: 'UTC', currency: 'USD', address: '' })
  const [editError, setEditError] = useState('')
  const [editing, setEditing] = useState(false)

  useEffect(() => {
    listStores()
      .then(data => setStores(data.stores || data))
      .catch(() => {})
      .finally(() => setLoadingStores(false))
  }, [])

  function onFormChange(e) {
    const { name, value } = e.target
    setForm(f => {
      const next = { ...f, [name]: value }
      if (name === 'name') next.slug = slugify(value)
      return next
    })
  }

  function openEditModal(store, e) {
    e.stopPropagation()
    setEditStore(store)
    setEditForm({
      name: store.name,
      timezone: store.timezone || 'UTC',
      currency: store.currency || 'USD',
      address: store.address || '',
    })
    setEditError('')
  }

  async function handleCreate(e) {
    e.preventDefault()
    setFormError('')
    if (!form.name.trim()) { setFormError('Store name is required'); return }
    if (!form.slug.match(/^[a-z0-9-]+$/)) { setFormError('Slug must be lowercase letters, numbers, and hyphens only'); return }
    setCreating(true)
    try {
      await createStore({
        name: form.name.trim(),
        slug: form.slug,
        timezone: form.timezone,
        currency: form.currency,
        address: form.address.trim() || undefined,
      })
      const updated = await listStores()
      setStores(updated.stores || updated)
      setShowModal(false)
      setForm({ name: '', slug: '', timezone: 'UTC', currency: 'USD', address: '' })
    } catch (err) {
      const detail = err.response?.data?.detail
      setFormError(typeof detail === 'string' ? detail : detail?.error || 'Failed to create store')
    } finally {
      setCreating(false)
    }
  }

  async function handleEdit(e) {
    e.preventDefault()
    setEditError('')
    if (!editForm.name.trim()) { setEditError('Store name is required'); return }
    setEditing(true)
    try {
      await patchStore(editStore.slug, {
        name: editForm.name.trim() || undefined,
        timezone: editForm.timezone || undefined,
        currency: editForm.currency || undefined,
        address: editForm.address.trim() || undefined,
      })
      const updated = await listStores()
      setStores(updated.stores || updated)
      setEditStore(null)
    } catch (err) {
      const detail = err.response?.data?.detail
      setEditError(typeof detail === 'string' ? detail : detail?.error || 'Failed to update store')
    } finally {
      setEditing(false)
    }
  }

  async function handleLogout() {
    try {
      if (state.tokens?.refresh_token) await logout(state.tokens.refresh_token)
    } finally {
      dispatch({ type: 'LOGOUT' })
      navigate('/login')
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Top nav */}
      <header className="border-b border-gray-200 bg-white px-6 py-3 flex items-center justify-between">
        <div>
          <h1 className="font-bold text-gray-900">RetailVision AI</h1>
          <p className="text-xs text-gray-500">Owner Dashboard</p>
        </div>
        <button
          onClick={handleLogout}
          className="text-sm text-gray-500 hover:text-gray-800 transition-colors"
        >
          Sign Out
        </button>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-lg font-semibold text-gray-900">Your Stores</h2>
          <button
            onClick={() => setShowModal(true)}
            className="px-4 py-2 rounded-lg text-sm font-semibold text-white"
            style={{ backgroundColor: '#1B3A5C' }}
          >
            + New Store
          </button>
        </div>

        {loadingStores ? (
          <div className="text-sm text-gray-400 py-12 text-center">Loading stores…</div>
        ) : stores.length === 0 ? (
          <div className="text-center py-16 bg-white rounded-xl border border-gray-200">
            <p className="text-gray-500 text-sm">No stores yet.</p>
            <button
              onClick={() => setShowModal(true)}
              className="mt-3 px-4 py-2 rounded-lg text-sm font-semibold text-white"
              style={{ backgroundColor: '#1B3A5C' }}
            >
              Create your first store
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {stores.map(store => (
              <div key={store.id} className="relative group">
                <button
                  onClick={() => {
                    dispatch({ type: 'SET_STORE', payload: store })
                    navigate(`/store/${store.slug}/live`)
                  }}
                  className="w-full text-left bg-white border border-gray-200 rounded-xl p-5 hover:border-blue-400 hover:shadow-sm transition-all"
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1 min-w-0 pr-6">
                      <p className="font-semibold text-gray-900 truncate group-hover:text-blue-700 transition-colors">
                        {store.name}
                      </p>
                      <p className="text-xs text-gray-400 mt-0.5">{store.slug}</p>
                    </div>
                    <span className={`ml-2 shrink-0 text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_COLORS[store.status] || STATUS_COLORS.inactive}`}>
                      {store.status || 'inactive'}
                    </span>
                  </div>
                  {store.address && (
                    <p className="text-xs text-gray-400 mt-2 truncate">{store.address}</p>
                  )}
                  <p className="text-xs text-gray-400 mt-1">{store.timezone} · {store.currency}</p>
                </button>
                <button
                  onClick={(e) => openEditModal(store, e)}
                  title="Edit store"
                  className="absolute top-3 right-3 opacity-0 group-hover:opacity-100 transition-opacity text-gray-400 hover:text-gray-700 bg-white rounded p-1"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        )}
      </main>

      {/* Create Store Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md">
            <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
              <h3 className="font-semibold text-gray-900">New Store</h3>
              <button
                onClick={() => { setShowModal(false); setFormError('') }}
                className="text-gray-400 hover:text-gray-600 text-lg leading-none"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleCreate} className="px-6 py-4 space-y-4">
              {formError && (
                <div className="bg-red-50 text-red-700 text-sm px-3 py-2 rounded-lg border border-red-200">
                  {formError}
                </div>
              )}

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Store Name <span className="text-red-500">*</span></label>
                <input
                  name="name"
                  type="text"
                  required
                  value={form.name}
                  onChange={onFormChange}
                  placeholder="e.g. Main Street Branch"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Slug <span className="text-red-500">*</span></label>
                <input
                  name="slug"
                  type="text"
                  required
                  value={form.slug}
                  onChange={onFormChange}
                  placeholder="e.g. main-street"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
                <p className="text-xs text-gray-400 mt-1">Lowercase letters, numbers, and hyphens only</p>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Timezone</label>
                  <select
                    name="timezone"
                    value={form.timezone}
                    onChange={onFormChange}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    {TIMEZONES.map(tz => <option key={tz} value={tz}>{tz}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Currency</label>
                  <select
                    name="currency"
                    value={form.currency}
                    onChange={onFormChange}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    {CURRENCIES.map(c => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Address <span className="text-gray-400 font-normal">(optional)</span></label>
                <input
                  name="address"
                  type="text"
                  value={form.address}
                  onChange={onFormChange}
                  placeholder="e.g. 123 Main St, City"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>

              <div className="flex gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => { setShowModal(false); setFormError('') }}
                  className="flex-1 py-2 px-4 rounded-lg text-sm font-medium border border-gray-300 text-gray-700 hover:bg-gray-50 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  className="flex-1 py-2 px-4 rounded-lg text-sm font-semibold text-white transition-colors disabled:opacity-50"
                  style={{ backgroundColor: '#1B3A5C' }}
                >
                  {creating ? 'Creating…' : 'Create Store'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Edit Store Modal */}
      {editStore && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md">
            <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
              <h3 className="font-semibold text-gray-900">Edit Store</h3>
              <button
                onClick={() => { setEditStore(null); setEditError('') }}
                className="text-gray-400 hover:text-gray-600 text-lg leading-none"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleEdit} className="px-6 py-4 space-y-4">
              {editError && (
                <div className="bg-red-50 text-red-700 text-sm px-3 py-2 rounded-lg border border-red-200">
                  {editError}
                </div>
              )}

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Store Name <span className="text-red-500">*</span></label>
                <input
                  type="text"
                  required
                  value={editForm.name}
                  onChange={e => setEditForm(f => ({ ...f, name: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Timezone</label>
                  <select
                    value={editForm.timezone}
                    onChange={e => setEditForm(f => ({ ...f, timezone: e.target.value }))}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    {TIMEZONES.map(tz => <option key={tz} value={tz}>{tz}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Currency</label>
                  <select
                    value={editForm.currency}
                    onChange={e => setEditForm(f => ({ ...f, currency: e.target.value }))}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    {CURRENCIES.map(c => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Address <span className="text-gray-400 font-normal">(optional)</span></label>
                <input
                  type="text"
                  value={editForm.address}
                  onChange={e => setEditForm(f => ({ ...f, address: e.target.value }))}
                  placeholder="e.g. 123 Main St, City"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>

              <div className="flex gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => { setEditStore(null); setEditError('') }}
                  className="flex-1 py-2 px-4 rounded-lg text-sm font-medium border border-gray-300 text-gray-700 hover:bg-gray-50 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={editing}
                  className="flex-1 py-2 px-4 rounded-lg text-sm font-semibold text-white transition-colors disabled:opacity-50"
                  style={{ backgroundColor: '#1B3A5C' }}
                >
                  {editing ? 'Saving…' : 'Save Changes'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
