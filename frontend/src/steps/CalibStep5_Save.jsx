/**
 * CalibStep5_Save — Method 2 Step 5
 *
 * Review & save configuration. Like Step8_Save but shows world bounds
 * instead of floor plan image info, and shows "Calibration Files" badge
 * per camera instead of homography status.
 */
import React, { useState } from 'react'
import useStore from '../store'
import {
  saveProject, loadProject,
  updateZone, deleteZone,
  updateObstacle, deleteObstacle,
  updateCamera, deleteCamera,
} from '../api'

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

function CalibCamerasSection({ cameras, updateCamera: patchCamera, removeCamera }) {
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
                  <div className="flex items-center gap-2 shrink-0">
                    {c.calibrationMethod === 'calibration_files' && (
                      <span className="text-xs bg-indigo-100 text-indigo-700 px-1.5 py-0.5 rounded font-medium">Calibration Files</span>
                    )}
                    <button onClick={() => handleDelete(c.id)} className="text-red-400 hover:text-red-600 text-xs">✕</button>
                  </div>
                </div>
                <p className="text-xs text-gray-400 mt-0.5">
                  {c.cameraWorldXYZ
                    ? `World position: (${c.cameraWorldXYZ.map(v => v.toFixed(2)).join(', ')}) m`
                    : `${c.heightMeters}m high`
                  }
                  {c.videoDuration ? ` · ${c.videoDuration.toFixed(1)}s video` : ' · no video'}
                  {' · '}
                  <span className={c.calibrationStatus === 'ok' ? 'text-green-600' : 'text-orange-500'}>
                    {c.calibrationStatus ?? 'uncalibrated'}
                  </span>
                </p>
              </div>
            ))}
          </div>
      }
    </div>
  )
}

export default function CalibStep5_Save({ onBack, onNext }) {
  const store = useStore()
  const {
    loadProject: hydrateProject,
    worldBounds,
    zones, obstacles, cameras,
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
    <div className="max-w-2xl mx-auto py-6 px-4">
      <h2 className="text-xl font-bold text-gray-800 mb-1">Save Configuration</h2>
      <p className="text-gray-500 text-sm mb-6">
        Review and save your calibration configuration. Click any name to rename it inline.
      </p>

      <div className="space-y-4 mb-8">
        {/* World Bounds */}
        <div className="bg-white border rounded-xl p-4">
          <h4 className="font-semibold text-gray-700 mb-2 text-sm">Virtual Map Bounds</h4>
          {worldBounds ? (
            <div className="text-sm text-gray-600 space-y-0.5">
              <div className="flex justify-between border-b py-0.5">
                <span className="text-gray-500">X range</span>
                <span>{worldBounds.xMin.toFixed(2)} m → {worldBounds.xMax.toFixed(2)} m ({(worldBounds.xMax - worldBounds.xMin).toFixed(2)} m wide)</span>
              </div>
              <div className="flex justify-between border-b py-0.5">
                <span className="text-gray-500">Y range</span>
                <span>{worldBounds.yMin.toFixed(2)} m → {worldBounds.yMax.toFixed(2)} m ({(worldBounds.yMax - worldBounds.yMin).toFixed(2)} m deep)</span>
              </div>
              <div className="flex justify-between py-0.5">
                <span className="text-gray-500">Method</span>
                <span className="text-indigo-600 font-medium">Calibration Files</span>
              </div>
            </div>
          ) : (
            <p className="text-sm text-gray-400">World bounds not set.</p>
          )}
        </div>

        <ZonesSection
          zones={zones}
          obstacles={obstacles}
          updateZone={updateZone}
          removeZone={removeZone}
          updateObstacle={updateObstacle}
          removeObstacle={removeObstacle}
        />

        <CalibCamerasSection
          cameras={cameras}
          updateCamera={updateCamera}
          removeCamera={removeCamera}
        />
      </div>

      <div className="flex gap-3 flex-wrap mb-6">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-5 py-2.5 bg-blue-600 text-white rounded-lg font-medium disabled:opacity-40 hover:bg-blue-700 transition"
        >
          {saving ? 'Saving…' : 'Save to Database'}
        </button>
        <button
          onClick={handleExport}
          className="px-5 py-2.5 bg-gray-100 text-gray-700 rounded-lg font-medium hover:bg-gray-200 transition"
        >
          Export JSON
        </button>
        <button
          onClick={handleLoad}
          className="px-5 py-2.5 bg-gray-100 text-gray-700 rounded-lg font-medium hover:bg-gray-200 transition"
        >
          Reload from DB
        </button>
      </div>

      {saved && <p className="mb-4 text-green-600 text-sm font-medium">✓ Configuration saved to database.</p>}
      {error && <p className="mb-4 text-red-600 text-sm">{error}</p>}

      <div className="flex gap-3">
        <button onClick={onBack} className="flex-1 py-3 rounded-lg border border-gray-300 text-gray-600 text-sm font-medium hover:bg-gray-50">
          ← Back
        </button>
        <button
          onClick={() => onNext && onNext()}
          className="flex-1 py-3 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700"
        >
          Next: Test Mode →
        </button>
      </div>
    </div>
  )
}
