import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import useStore from '../store'
import {
  saveProject, loadProject,
  updateZone, deleteZone,
  updateObstacle, deleteObstacle,
  updateCamera, deleteCamera,
} from '../api'

// ── Inline editable field ────────────────────────────────────────────────────

function EditableText({ value, onSave, className = '' }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)

  const commit = async () => {
    if (draft.trim() && draft !== value) await onSave(draft.trim())
    setEditing(false)
  }

  if (editing) {
    return (
      <input
        autoFocus
        value={draft}
        onChange={e => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={e => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') setEditing(false) }}
        className="border-b border-blue-400 outline-none text-sm font-medium bg-transparent px-0.5"
      />
    )
  }
  return (
    <span
      className={`cursor-pointer hover:text-blue-600 ${className}`}
      title="Click to rename"
      onClick={() => { setDraft(value); setEditing(true) }}
    >
      {value}
    </span>
  )
}

// ── Sections ─────────────────────────────────────────────────────────────────

function ZonesSection({ zones, obstacles, updateZone: patchZone, removeZone, updateObstacle: patchObstacle, removeObstacle }) {
  const ZONE_TYPES = ['aisle', 'checkout', 'entrance', 'display', 'storage', 'other']

  const handleRenameZone = async (id, name) => {
    await updateZone(id, { name })
    patchZone(id, { name })
  }

  const handleTypeZone = async (id, type) => {
    await updateZone(id, { type })
    patchZone(id, { type })
  }

  const handleDeleteZone = async (id) => {
    await deleteZone(id)
    removeZone(id)
  }

  const handleRenameObstacle = async (id, name) => {
    await updateObstacle(id, { name })
    patchObstacle(id, { name })
  }

  const handleDeleteObstacle = async (id) => {
    await deleteObstacle(id)
    removeObstacle(id)
  }

  return (
    <div className="bg-white border rounded-xl p-4">
      <h4 className="font-semibold text-gray-700 mb-3 text-sm">Zones ({zones.length})</h4>
      {zones.length === 0
        ? <p className="text-sm text-gray-400">No zones defined.</p>
        : <div className="space-y-1">
            {zones.map(z => (
              <div key={z.id} className="flex items-center justify-between py-1.5 border-b last:border-0 gap-2">
                <div className="flex items-center gap-2 min-w-0">
                  <EditableText
                    value={z.name}
                    onSave={name => handleRenameZone(z.id, name)}
                    className="font-medium text-gray-800 text-sm"
                  />
                  <select
                    value={z.type}
                    onChange={e => handleTypeZone(z.id, e.target.value)}
                    className="text-xs text-gray-500 border rounded px-1 py-0.5 bg-gray-50"
                  >
                    {ZONE_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                  </select>
                  <span className="text-xs text-gray-400">{z.points?.length} pts</span>
                </div>
                <button onClick={() => handleDeleteZone(z.id)} className="text-red-400 hover:text-red-600 text-xs shrink-0">✕</button>
              </div>
            ))}
          </div>
      }

      {obstacles.length > 0 && (
        <>
          <h4 className="font-semibold text-gray-700 mt-4 mb-2 text-sm">Obstacles ({obstacles.length})</h4>
          <div className="space-y-1">
            {obstacles.map(o => (
              <div key={o.id} className="flex items-center justify-between py-1.5 border-b last:border-0 gap-2">
                <EditableText
                  value={o.name ?? 'Unnamed'}
                  onSave={name => handleRenameObstacle(o.id, name)}
                  className="text-sm text-gray-700"
                />
                <button onClick={() => handleDeleteObstacle(o.id)} className="text-red-400 hover:text-red-600 text-xs shrink-0">✕</button>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function CamerasSection({ cameras, updateCamera: patchCamera, removeCamera }) {
  const handleRename = async (id, name) => {
    await updateCamera(id, { name })
    patchCamera(id, { name })
  }

  const handleDelete = async (id) => {
    await deleteCamera(id)
    removeCamera(id)
  }

  return (
    <div className="bg-white border rounded-xl p-4">
      <h4 className="font-semibold text-gray-700 mb-3 text-sm">Cameras ({cameras.length})</h4>
      {cameras.length === 0
        ? <p className="text-sm text-gray-400">No cameras registered.</p>
        : <div className="space-y-1">
            {cameras.map(c => (
              <div key={c.id} className="py-1.5 border-b last:border-0">
                <div className="flex items-center justify-between gap-2">
                  <EditableText
                    value={c.name}
                    onSave={name => handleRename(c.id, name)}
                    className="font-medium text-gray-800 text-sm"
                  />
                  <button onClick={() => handleDelete(c.id)} className="text-red-400 hover:text-red-600 text-xs shrink-0">✕</button>
                </div>
                <p className="text-xs text-gray-400 mt-0.5">
                  ({c.position?.x?.toFixed(1)}m, {c.position?.y?.toFixed(1)}m) · {c.heightMeters}m high
                  {c.videoDuration ? ` · ${c.videoDuration.toFixed(1)}s video` : ' · no video'}
                  {' · '}
                  <span className={c.homographyStatus === 'ok' ? 'text-green-600' : 'text-orange-500'}>
                    {c.homographyStatus ?? 'no homography'}
                  </span>
                  {c.reprojectionError != null && ` · err ${c.reprojectionError.toFixed(3)}px`}
                </p>
              </div>
            ))}
          </div>
      }
    </div>
  )
}

// ── Main ─────────────────────────────────────────────────────────────────────

export default function Step8_Save() {
  const navigate = useNavigate()
  const store = useStore()
  const {
    setStep,
    loadProject: hydrateProject,
    floorPlanWidth, floorPlanHeight, pixelsPerMeter, origin,
    zones, obstacles, cameras,
    activeStoreName,
    updateZone, removeZone,
    updateObstacle, removeObstacle,
    updateCamera, removeCamera,
  } = store

  const getProjectData = store.getProjectData

  const [saved, setSaved] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  const handleSave = async () => {
    setSaving(true)
    setError(null)
    try {
      await saveProject(getProjectData())
      setSaved(true)
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const handleExport = () => {
    const data = getProjectData()
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'project.json'
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleLoad = async () => {
    try {
      const data = await loadProject()
      if (data) hydrateProject(data)
      else alert('No project found on the server for this store.')
    } catch (e) {
      alert(e.message)
    }
  }

  return (
    <div className="max-w-3xl">
      <h3 className="text-xl font-semibold mb-1 text-gray-800">Configuration</h3>
      <p className="text-gray-500 mb-6 text-sm">
        Review and edit your configuration. Click any name to rename it inline. Changes to zones and cameras are saved immediately to the database.
      </p>

      <div className="space-y-4 mb-8">
        {/* Floor plan */}
        <div className="bg-white border rounded-xl p-4">
          <h4 className="font-semibold text-gray-700 mb-2 text-sm">Floor Plan</h4>
          <div className="text-sm text-gray-600 space-y-0.5">
            <div className="flex justify-between border-b py-0.5">
              <span className="text-gray-500">Dimensions</span>
              <span>{floorPlanWidth} × {floorPlanHeight} px</span>
            </div>
            <div className="flex justify-between border-b py-0.5">
              <span className="text-gray-500">Scale</span>
              <span>{pixelsPerMeter ? `${pixelsPerMeter.toFixed(1)} px/m` : '—'}</span>
            </div>
            <div className="flex justify-between py-0.5">
              <span className="text-gray-500">Origin</span>
              <span>{origin ? `(${origin.x.toFixed(0)}, ${origin.y.toFixed(0)}) px` : '—'}</span>
            </div>
          </div>
          <button onClick={() => setStep(2)} className="mt-2 text-xs text-blue-600 hover:underline">Edit scale →</button>
        </div>

        {/* Zones & obstacles — inline editable */}
        <ZonesSection
          zones={zones}
          obstacles={obstacles}
          updateZone={updateZone}
          removeZone={removeZone}
          updateObstacle={updateObstacle}
          removeObstacle={removeObstacle}
        />

        {/* Cameras — inline editable */}
        <CamerasSection
          cameras={cameras}
          updateCamera={updateCamera}
          removeCamera={removeCamera}
        />
      </div>

      <div className="flex gap-3 flex-wrap">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-5 py-2.5 bg-blue-600 text-white rounded-lg font-medium disabled:opacity-40 hover:bg-blue-700 transition"
        >
          {saving ? 'Saving…' : '💾 Save to Database'}
        </button>
        <button
          onClick={handleExport}
          className="px-5 py-2.5 bg-gray-100 text-gray-700 rounded-lg font-medium hover:bg-gray-200 transition"
        >
          📥 Export JSON
        </button>
        <button
          onClick={handleLoad}
          className="px-5 py-2.5 bg-gray-100 text-gray-700 rounded-lg font-medium hover:bg-gray-200 transition"
        >
          📂 Reload from DB
        </button>
      </div>

      {error && <p className="mt-3 text-red-600 text-sm">{error}</p>}

      {!saved && (
        <div className="mt-6 flex justify-between">
          <button onClick={() => setStep(7)} className="px-4 py-2 text-gray-600 border rounded-lg hover:bg-gray-50">← Back</button>
        </div>
      )}

      {saved && (
        <div className="mt-8 bg-green-50 border border-green-200 rounded-2xl p-6">
          <div className="flex items-center gap-3 mb-4">
            <span className="text-3xl">✅</span>
            <div>
              <h3 className="text-lg font-bold text-green-800">Store setup complete!</h3>
              <p className="text-sm text-green-600">{activeStoreName} is ready to use.</p>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-3 mb-6 text-center">
            <div className="bg-white rounded-xl border border-green-100 py-3 px-2">
              <p className="text-2xl font-bold text-gray-800">{cameras.length}</p>
              <p className="text-xs text-gray-500 mt-0.5">Camera{cameras.length !== 1 ? 's' : ''}</p>
            </div>
            <div className="bg-white rounded-xl border border-green-100 py-3 px-2">
              <p className="text-2xl font-bold text-gray-800">{zones.length}</p>
              <p className="text-xs text-gray-500 mt-0.5">Zone{zones.length !== 1 ? 's' : ''}</p>
            </div>
            <div className="bg-white rounded-xl border border-green-100 py-3 px-2">
              <p className="text-2xl font-bold text-gray-800">{pixelsPerMeter ? `${pixelsPerMeter.toFixed(0)}` : '—'}</p>
              <p className="text-xs text-gray-500 mt-0.5">px / metre</p>
            </div>
          </div>

          <div className="flex flex-col sm:flex-row gap-3">
            <button
              onClick={() => navigate(`/config?store=${store.activeStoreId}`)}
              className="flex-1 px-5 py-3 bg-blue-600 text-white rounded-xl font-semibold hover:bg-blue-700 transition text-sm"
            >
              Go to Store Config →
            </button>
            <button
              onClick={() => setStep(9)}
              className="flex-1 px-5 py-3 bg-white border border-gray-300 text-gray-700 rounded-xl font-medium hover:bg-gray-50 transition text-sm"
            >
              Optionally run tracking test
            </button>
          </div>
          <p className="text-xs text-gray-400 mt-3 text-center">
            The tracking test is optional — you can always run it later from Store Config.
          </p>
        </div>
      )}
    </div>
  )
}
