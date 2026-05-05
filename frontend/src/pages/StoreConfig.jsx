/**
 * StoreConfig — per-store configuration viewer & editor.
 *
 * Select any store from the list, load its saved config from the DB,
 * and edit zones, obstacles, and cameras inline.
 */
import React, { useState, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  listStores, setCurrentStoreId,
  updateZone, deleteZone,
  updateObstacle, deleteObstacle,
  updateCamera, deleteCamera,
} from '../api'

// ── Inline editable text ──────────────────────────────────────────────────────

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
        className="border-b border-blue-400 outline-none text-sm font-medium bg-transparent px-0.5 w-full"
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

// ── Section wrapper ───────────────────────────────────────────────────────────

function Section({ title, count, children }) {
  return (
    <div className="bg-white border rounded-xl p-4">
      <h4 className="font-semibold text-gray-700 mb-3 text-sm">
        {title} <span className="text-gray-400 font-normal">({count})</span>
      </h4>
      {children}
    </div>
  )
}

// ── Config panel for one store ────────────────────────────────────────────────

function ConfigPanel({ storeId }) {
  const [loading, setLoading] = useState(true)
  const [floorPlan, setFloorPlan] = useState(null)
  const [zones, setZones] = useState([])
  const [obstacles, setObstacles] = useState([])
  const [cameras, setCameras] = useState([])
  const [error, setError] = useState(null)

  const ZONE_TYPES = ['aisle', 'checkout', 'entrance', 'display', 'storage', 'other']

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    setCurrentStoreId(storeId)
    try {
      const [fp, z, o, c] = await Promise.all([
        fetch(`/api/stores/${storeId}/floor-plan`).then(r => r.ok ? r.json() : null),
        fetch(`/api/stores/${storeId}/zones`).then(r => r.ok ? r.json() : []),
        fetch(`/api/stores/${storeId}/obstacles`).then(r => r.ok ? r.json() : []),
        fetch(`/api/stores/${storeId}/cameras`).then(r => r.ok ? r.json() : []),
      ])
      setFloorPlan(fp)
      setZones(z ?? [])
      setObstacles(o ?? [])
      setCameras(c ?? [])
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [storeId])

  useEffect(() => { load() }, [load])

  if (loading) return <p className="text-sm text-gray-400 py-6 text-center">Loading…</p>
  if (error) return <p className="text-sm text-red-500 py-6 text-center">{error}</p>

  const hasFloorPlan = floorPlan?.s3_key

  return (
    <div className="space-y-4">
      {/* Floor plan info */}
      <Section title="Floor Plan" count={hasFloorPlan ? 1 : 0}>
        {hasFloorPlan ? (
          <div className="flex gap-6 text-sm">
            <div className="w-32 h-20 rounded-lg overflow-hidden border bg-gray-50 shrink-0">
              <img
                src={`/api/stores/${storeId}/floor-plan/image`}
                alt="floor plan"
                className="w-full h-full object-contain"
              />
            </div>
            <div className="space-y-1 text-gray-600">
              <p><span className="text-gray-400">Size:</span> {floorPlan.width_px} × {floorPlan.height_px} px</p>
              {floorPlan.pixels_per_meter && (
                <p><span className="text-gray-400">Scale:</span> {floorPlan.pixels_per_meter.toFixed(1)} px/m</p>
              )}
              {floorPlan.origin_x != null && (
                <p><span className="text-gray-400">Origin:</span> ({floorPlan.origin_x.toFixed(0)}, {floorPlan.origin_y.toFixed(0)}) px</p>
              )}
            </div>
          </div>
        ) : (
          <p className="text-sm text-gray-400">No floor plan uploaded.</p>
        )}
      </Section>

      {/* Zones */}
      <Section title="Zones" count={zones.length}>
        {zones.length === 0
          ? <p className="text-sm text-gray-400">No zones defined.</p>
          : <div className="space-y-1">
              {zones.map(z => (
                <div key={z.id} className="flex items-center gap-2 py-1.5 border-b last:border-0">
                  <div className="flex-1 flex items-center gap-2 min-w-0">
                    <EditableText
                      value={z.name}
                      onSave={async name => {
                        await updateZone(z.id, { name })
                        setZones(prev => prev.map(x => x.id === z.id ? { ...x, name } : x))
                      }}
                      className="font-medium text-gray-800 text-sm"
                    />
                    <select
                      value={z.type}
                      onChange={async e => {
                        const type = e.target.value
                        await updateZone(z.id, { type })
                        setZones(prev => prev.map(x => x.id === z.id ? { ...x, type } : x))
                      }}
                      className="text-xs text-gray-500 border rounded px-1 py-0.5 bg-gray-50"
                    >
                      {ZONE_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                    </select>
                    <span className="text-xs text-gray-400">{z.points?.length} pts</span>
                  </div>
                  <button
                    onClick={async () => {
                      await deleteZone(z.id)
                      setZones(prev => prev.filter(x => x.id !== z.id))
                    }}
                    className="text-red-400 hover:text-red-600 text-xs shrink-0"
                  >✕</button>
                </div>
              ))}
            </div>
        }
      </Section>

      {/* Obstacles */}
      <Section title="Obstacles" count={obstacles.length}>
        {obstacles.length === 0
          ? <p className="text-sm text-gray-400">No obstacles defined.</p>
          : <div className="space-y-1">
              {obstacles.map(o => (
                <div key={o.id} className="flex items-center gap-2 py-1.5 border-b last:border-0">
                  <div className="flex-1">
                    <EditableText
                      value={o.name ?? 'Unnamed'}
                      onSave={async name => {
                        await updateObstacle(o.id, { name })
                        setObstacles(prev => prev.map(x => x.id === o.id ? { ...x, name } : x))
                      }}
                      className="text-sm text-gray-700"
                    />
                  </div>
                  <span className="text-xs text-gray-400">{o.points?.length} pts</span>
                  <button
                    onClick={async () => {
                      await deleteObstacle(o.id)
                      setObstacles(prev => prev.filter(x => x.id !== o.id))
                    }}
                    className="text-red-400 hover:text-red-600 text-xs"
                  >✕</button>
                </div>
              ))}
            </div>
        }
      </Section>

      {/* Cameras */}
      <Section title="Cameras" count={cameras.length}>
        {cameras.length === 0
          ? <p className="text-sm text-gray-400">No cameras registered.</p>
          : <div className="space-y-2">
              {cameras.map(c => (
                <div key={c.id} className="py-2 border-b last:border-0">
                  <div className="flex items-center justify-between gap-2">
                    <EditableText
                      value={c.name}
                      onSave={async name => {
                        await updateCamera(c.id, { name })
                        setCameras(prev => prev.map(x => x.id === c.id ? { ...x, name } : x))
                      }}
                      className="font-medium text-gray-800 text-sm"
                    />
                    <button
                      onClick={async () => {
                        await deleteCamera(c.id)
                        setCameras(prev => prev.filter(x => x.id !== c.id))
                      }}
                      className="text-red-400 hover:text-red-600 text-xs shrink-0"
                    >✕</button>
                  </div>
                  <div className="text-xs text-gray-400 mt-0.5 flex flex-wrap gap-x-3">
                    <span>({c.position_x?.toFixed(1)}m, {c.position_y?.toFixed(1)}m)</span>
                    <span>{c.height_meters}m high</span>
                    {c.video_duration ? <span>{c.video_duration.toFixed(1)}s video</span> : <span className="text-orange-400">no video</span>}
                    {c.calibration?.status
                      ? <span className={c.calibration.status === 'ok' ? 'text-green-600' : 'text-orange-500'}>
                          homography: {c.calibration.status}
                          {c.calibration.reprojection_error != null && ` (err ${c.calibration.reprojection_error.toFixed(3)}px)`}
                        </span>
                      : <span className="text-orange-400">no calibration</span>
                    }
                  </div>
                </div>
              ))}
            </div>
        }
      </Section>

      <button
        onClick={load}
        className="text-xs text-blue-600 hover:underline"
      >
        🔄 Refresh from DB
      </button>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function StoreConfig() {
  const [searchParams] = useSearchParams()
  const [stores, setStores] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [loadingStores, setLoadingStores] = useState(true)

  useEffect(() => {
    listStores()
      .then(s => {
        setStores(s)
        const paramId = searchParams.get('store')
        if (paramId && s.find(x => x.id === paramId)) {
          setSelectedId(paramId)
        } else if (s.length === 1) {
          setSelectedId(s[0].id)
        }
      })
      .catch(() => {})
      .finally(() => setLoadingStores(false))
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const selected = stores.find(s => s.id === selectedId)

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <header className="bg-white border-b px-8 py-4">
        <h2 className="text-lg font-semibold text-gray-800">Store Configuration</h2>
        <p className="text-sm text-gray-500">View and edit saved configuration for any store</p>
      </header>

      <div className="flex-1 flex overflow-hidden">
        {/* Store list */}
        <aside className="w-56 border-r bg-white p-4 overflow-y-auto shrink-0">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Stores</p>
          {loadingStores
            ? <p className="text-xs text-gray-400">Loading…</p>
            : stores.length === 0
              ? <p className="text-xs text-gray-400">No stores yet.</p>
              : stores.map(s => (
                  <button
                    key={s.id}
                    onClick={() => setSelectedId(s.id)}
                    className={`w-full text-left px-3 py-2.5 rounded-lg text-sm mb-1 transition-colors ${
                      s.id === selectedId
                        ? 'bg-blue-600 text-white font-semibold'
                        : 'text-gray-700 hover:bg-gray-100'
                    }`}
                  >
                    <span className="block truncate">{s.name}</span>
                    <span className={`text-xs ${s.id === selectedId ? 'text-blue-200' : 'text-gray-400'}`}>
                      {new Date(s.created_at).toLocaleDateString()}
                    </span>
                  </button>
                ))
          }
        </aside>

        {/* Config detail */}
        <div className="flex-1 overflow-y-auto p-6">
          {!selectedId
            ? (
              <div className="flex items-center justify-center h-full">
                <p className="text-gray-400 text-sm">Select a store to view its configuration</p>
              </div>
            )
            : (
              <div className="max-w-2xl">
                <div className="flex items-center justify-between mb-5">
                  <h3 className="text-lg font-semibold text-gray-800">{selected?.name}</h3>
                </div>
                <ConfigPanel key={selectedId} storeId={selectedId} />
              </div>
            )
          }
        </div>
      </div>
    </div>
  )
}
