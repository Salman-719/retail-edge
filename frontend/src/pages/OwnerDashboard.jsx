import React, { useEffect, useState } from 'react'
import { useNavigate, Navigate } from 'react-router-dom'
import { ArrowRight, Plus, Pencil } from 'lucide-react'
import { useAuth } from '../store'
import { listStores, createStore, patchStore, deleteStore, logout } from '../api'

// Derive initials from a store name (up to 2 chars)
function initials(name) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map(w => w[0].toUpperCase())
    .join('')
}

// Deterministic banner gradient per store (cycles through a palette)
const BANNER_GRADIENTS = [
  'linear-gradient(135deg, #1e40af 0%, #1d4ed8 100%)',
  'linear-gradient(135deg, #065f46 0%, #059669 100%)',
  'linear-gradient(135deg, #7c3aed 0%, #6d28d9 100%)',
  'linear-gradient(135deg, #b45309 0%, #d97706 100%)',
  'linear-gradient(135deg, #be123c 0%, #e11d48 100%)',
  'linear-gradient(135deg, #0e7490 0%, #0891b2 100%)',
]

function bannerGradient(store, index) {
  return BANNER_GRADIENTS[index % BANNER_GRADIENTS.length]
}

function slugify(name) {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
}

function formatLastActive(store) {
  if (store.updated_at) {
    return new Date(store.updated_at).toLocaleDateString(undefined, { dateStyle: 'medium' })
  }
  if (store.created_at) {
    return new Date(store.created_at).toLocaleDateString(undefined, { dateStyle: 'medium' })
  }
  return '—'
}

// ── Store Card ────────────────────────────────────────────────────────────────

function StoreCard({ store, index, onNavigate, onEdit }) {
  // MOCK stats — replace with real counts from API when available
  const stats = [
    { label: 'Cameras', value: store.camera_count ?? '—' },
    { label: 'Zones',   value: store.zone_count   ?? '—' },
    { label: 'Staff',   value: store.staff_count  ?? '—' },
  ]

  return (
    <div className="relative group">
      <button
        onClick={onNavigate}
        className="w-full text-left bg-white border border-gray-100 rounded-2xl shadow-sm hover:shadow-lg transition-all duration-200 overflow-hidden cursor-pointer"
      >
        {/* Banner */}
        <div
          className="h-20 flex items-end px-5 pb-0 relative"
          style={{ background: bannerGradient(store, index) }}
        >
          {/* Avatar circle sits on the border */}
          <div className="absolute -bottom-5 left-5 w-12 h-12 rounded-full bg-white shadow-md flex items-center justify-center border-2 border-white">
            <span className="text-sm font-bold" style={{ color: '#1e40af' }}>
              {initials(store.name)}
            </span>
          </div>
        </div>

        {/* Body */}
        <div className="pt-8 px-5 pb-4">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="font-semibold text-gray-900 text-base leading-snug">{store.name}</p>
              <p className="text-xs text-gray-400 mt-0.5 font-mono">{store.slug}</p>
            </div>
            <span className="shrink-0 mt-0.5 text-xs px-2 py-0.5 rounded-full font-medium bg-green-100 text-green-700">
              active
            </span>
          </div>
          <p className="text-xs text-gray-400 mt-2">
            Last active: {formatLastActive(store)}
          </p>
        </div>

        {/* Mini stats */}
        <div className="border-t border-gray-100 grid grid-cols-3 divide-x divide-gray-100">
          {stats.map(({ label, value }) => (
            <div key={label} className="py-3 flex flex-col items-center">
              <span className="text-sm font-semibold text-gray-800">{value}</span>
              <span className="text-xs text-gray-400 mt-0.5">{label}</span>
            </div>
          ))}
        </div>

        {/* Arrow hint */}
        <div className="absolute bottom-4 right-4 text-gray-300 group-hover:text-blue-500 transition-colors">
          <ArrowRight size={16} />
        </div>
      </button>

      {/* Edit pencil — appears on hover */}
      <button
        onClick={onEdit}
        title="Edit store"
        className="absolute top-3 right-3 opacity-0 group-hover:opacity-100 transition-opacity bg-white/80 hover:bg-white rounded-lg p-1.5 text-gray-500 hover:text-gray-800 shadow-sm"
      >
        <Pencil size={13} />
      </button>
    </div>
  )
}

// ── Add-store card ────────────────────────────────────────────────────────────

function AddStoreCard({ onClick }) {
  return (
    <button
      onClick={onClick}
      className="w-full h-full min-h-[220px] flex flex-col items-center justify-center gap-3 bg-white border-2 border-dashed border-gray-200 rounded-2xl hover:border-blue-400 hover:bg-blue-50/30 transition-all duration-200 cursor-pointer group"
    >
      <div className="w-12 h-12 rounded-full bg-gray-100 group-hover:bg-blue-100 flex items-center justify-center transition-colors">
        <Plus size={22} className="text-gray-400 group-hover:text-blue-500 transition-colors" />
      </div>
      <span className="text-sm font-medium text-gray-500 group-hover:text-blue-600 transition-colors">
        Add New Store
      </span>
    </button>
  )
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyState({ onCreate }) {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      {/* Store SVG illustration */}
      <svg width="80" height="80" viewBox="0 0 80 80" fill="none" className="mb-6 text-gray-300">
        <rect x="8" y="36" width="64" height="36" rx="4" fill="currentColor" opacity="0.3" />
        <path d="M8 36 L16 16 H64 L72 36" fill="currentColor" opacity="0.5" />
        <rect x="28" y="50" width="24" height="22" rx="2" fill="white" />
        <rect x="34" y="24" width="12" height="12" rx="2" fill="white" opacity="0.7" />
        <path d="M8 36 H72" stroke="white" strokeWidth="1.5" opacity="0.4" />
        <rect x="14" y="44" width="12" height="12" rx="2" fill="white" opacity="0.5" />
        <rect x="54" y="44" width="12" height="12" rx="2" fill="white" opacity="0.5" />
      </svg>
      <h3 className="text-lg font-semibold text-gray-700 mb-1">No stores yet</h3>
      <p className="text-sm text-gray-400 mb-6 max-w-xs">
        Create your first store to start monitoring with RetailVision AI.
      </p>
      <button onClick={onCreate} className="btn-primary flex items-center gap-2">
        <Plus size={15} />
        Create your first store
      </button>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function OwnerDashboard() {
  const { state, dispatch } = useAuth()
  const navigate = useNavigate()

  const isAdmin = !!state.user?.is_super_admin
  if (state.ready && state.user?.account_type !== 'owner' && !isAdmin) {
    return <Navigate to="/login" replace />
  }

  const [stores, setStores] = useState([])
  const [loadingStores, setLoadingStores] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [editStore, setEditStore] = useState(null)
  const [form, setForm] = useState({ name: '', slug: '', address: '' })
  const [formError, setFormError] = useState('')
  const [creating, setCreating] = useState(false)
  const [editForm, setEditForm] = useState({ name: '', address: '' })
  const [editError, setEditError] = useState('')
  const [editing, setEditing] = useState(false)
  const [deleting, setDeleting] = useState(false)

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
      address: store.address || '',
    })
    setEditError('')
  }

  async function handleCreate(e) {
    e.preventDefault()
    setFormError('')
    if (!form.name.trim()) { setFormError('Store name is required'); return }
    if (!form.slug.match(/^[a-z0-9-]+$/)) { setFormError('Slug must be lowercase letters, numbers, and hyphens only'); return }
    if (!form.address.trim()) { setFormError('Address is required'); return }
    setCreating(true)
    try {
      await createStore({
        name: form.name.trim(),
        slug: form.slug,
        address: form.address.trim(),
      })
      const updated = await listStores()
      setStores(updated.stores || updated)
      setShowModal(false)
      setForm({ name: '', slug: '', address: '' })
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
    if (!editForm.address.trim()) { setEditError('Address is required'); return }
    setEditing(true)
    try {
      await patchStore(editStore.slug, {
        name: editForm.name.trim() || undefined,
        address: editForm.address.trim(),
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

  async function handleDelete() {
    if (!window.confirm(`Delete "${editStore.name}"? This cannot be undone.`)) return
    setDeleting(true)
    setEditError('')
    try {
      await deleteStore(editStore.slug)
      setStores(prev => prev.filter(s => s.slug !== editStore.slug))
      setEditStore(null)
    } catch (err) {
      const detail = err.response?.data?.detail
      setEditError(typeof detail === 'string' ? detail : detail?.error || 'Failed to delete store')
    } finally {
      setDeleting(false)
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

  const activeCount = stores.filter(s => s.status === 'active' || !s.status).length
  const inactiveCount = stores.length - activeCount

  return (
    <div className="min-h-screen bg-[#f8fafc]">

      {/* Top nav */}
      <header className="border-b border-gray-200 bg-white px-8 py-3.5 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-7 h-7 rounded-md bg-blue-600 flex items-center justify-center">
            <svg width="14" height="14" viewBox="0 0 18 18" fill="none">
              <circle cx="9" cy="9" r="3.5" fill="white" />
              <circle cx="9" cy="9" r="7" stroke="white" strokeWidth="1.5" strokeDasharray="2.5 2" />
            </svg>
          </div>
          <span className="font-bold text-gray-900 text-sm tracking-tight">RetailVision AI</span>
        </div>
        <button
          onClick={handleLogout}
          className="text-sm text-gray-400 hover:text-gray-700 transition-colors"
        >
          Sign Out
        </button>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-10">

        {/* Page header */}
        <div className="mb-8">
          <h1 className="page-title">{isAdmin ? 'All Stores — Admin' : 'Owner Dashboard'}</h1>
          <p className="page-subtitle">{isAdmin ? 'Fleet-wide view across all owners' : 'Manage your retail locations'}</p>
          {!loadingStores && stores.length > 0 && (
            <p className="text-xs text-gray-400 mt-3 pl-4">
              {stores.length} {stores.length === 1 ? 'Store' : 'Stores'}
              &nbsp;·&nbsp;
              <span className="text-green-600 font-medium">{activeCount} Active</span>
              &nbsp;·&nbsp;
              <span className="text-gray-400">{inactiveCount} Inactive</span>
            </p>
          )}
        </div>

        {loadingStores ? (
          <div className="text-sm text-gray-400 py-16 text-center">Loading stores…</div>
        ) : stores.length === 0 ? (
          <EmptyState onCreate={() => setShowModal(true)} />
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
            {stores.map((store, i) => (
              <StoreCard
                key={store.id}
                store={store}
                index={i}
                onNavigate={() => {
                  dispatch({ type: 'SET_STORE', payload: store })
                  navigate(`/store/${store.slug}/live`)
                }}
                onEdit={e => openEditModal(store, e)}
              />
            ))}
            <AddStoreCard onClick={() => setShowModal(true)} />
          </div>
        )}
      </main>

      {/* ── Create Store Modal ─────────────────────────────────────────────── */}
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
                  name="name" type="text" required value={form.name} onChange={onFormChange}
                  placeholder="e.g. Main Street Branch"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Slug <span className="text-red-500">*</span></label>
                <input
                  name="slug" type="text" required value={form.slug} onChange={onFormChange}
                  placeholder="e.g. main-street"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
                <p className="text-xs text-gray-400 mt-1">Lowercase letters, numbers, and hyphens only</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Address <span className="text-red-500">*</span></label>
                <input
                  name="address" type="text" required value={form.address} onChange={onFormChange}
                  placeholder="e.g. 123 Main St, City"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>

              <div className="flex gap-2 pt-2">
                <button type="button" onClick={() => { setShowModal(false); setFormError('') }}
                  className="flex-1 py-2 px-4 rounded-lg text-sm font-medium border border-gray-300 text-gray-700 hover:bg-gray-50 transition-colors">
                  Cancel
                </button>
                <button type="submit" disabled={creating} className="btn-primary flex-1">
                  {creating ? 'Creating…' : 'Create Store'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── Edit Store Modal ───────────────────────────────────────────────── */}
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
                <input type="text" required value={editForm.name}
                  onChange={e => setEditForm(f => ({ ...f, name: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Address <span className="text-red-500">*</span></label>
                <input type="text" required value={editForm.address}
                  onChange={e => setEditForm(f => ({ ...f, address: e.target.value }))}
                  placeholder="e.g. 123 Main St, City"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>

              <div className="flex gap-2 pt-2">
                <button type="button" onClick={() => { setEditStore(null); setEditError('') }}
                  className="flex-1 py-2 px-4 rounded-lg text-sm font-medium border border-gray-300 text-gray-700 hover:bg-gray-50 transition-colors">
                  Cancel
                </button>
                <button type="submit" disabled={editing || deleting} className="btn-primary flex-1">
                  {editing ? 'Saving…' : 'Save Changes'}
                </button>
              </div>

              <div className="border-t border-gray-100 pt-4 mt-2">
                <button
                  type="button"
                  onClick={handleDelete}
                  disabled={deleting || editing}
                  className="w-full py-2 px-4 rounded-lg text-sm font-medium text-red-600 border border-red-200 hover:bg-red-50 transition-colors disabled:opacity-50"
                >
                  {deleting ? 'Deleting…' : 'Delete Store'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
