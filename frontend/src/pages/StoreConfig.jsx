import React, { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Stage, Layer, Image as KonvaImage, Line, Circle, Text } from 'react-konva'
import { Plus, Pencil, Trash2, Check, X, Warehouse } from 'lucide-react'
import {
  getDraft, getActiveVersion, listSections, listVersions, reactivateVersion,
  createSection, patchSection, deleteSection, getSyncEvent,
} from '../api'
import { usePageTitle } from '../components/PageMeta'
import SectionTabs from '../components/SectionTabs'

const ZONE_COLORS = {
  entrance: '#3b82f6',
  checkout: '#f59e0b',
  aisle: '#10b981',
  staff_only: '#ef4444',
  general: '#8b5cf6',
}

function useImage(url) {
  const [image, setImage] = useState(null)
  useEffect(() => {
    if (!url) return
    const img = new window.Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => setImage(img)
    img.src = url
  }, [url])
  return image
}

function FloorPlanCanvas({ floorPlan, zones, obstacles, cameraConfigs }) {
  const containerRef = useRef(null)
  const [size, setSize] = useState({ w: 800, h: 500 })
  const bgImage = useImage(floorPlan?.display_url)

  useEffect(() => {
    if (!containerRef.current) return
    const ro = new ResizeObserver(([entry]) => {
      setSize({ w: entry.contentRect.width, h: entry.contentRect.height })
    })
    ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [])

  if (!floorPlan?.image_uploaded) {
    return (
      <div className="flex flex-col items-center justify-center h-64 bg-gray-50 rounded-lg text-gray-400 text-sm gap-2 border border-dashed border-gray-200">
        <span className="text-3xl">🗺️</span>
        <span>No floor plan uploaded for this section</span>
      </div>
    )
  }

  const imgW = floorPlan.width_px || 1
  const imgH = floorPlan.height_px || 1
  const scale = Math.min(size.w / imgW, size.h / imgH)

  return (
    <div ref={containerRef} className="w-full" style={{ height: Math.round(imgH * scale) }}>
      <Stage width={size.w} height={Math.round(imgH * scale)}>
        <Layer>
          {bgImage && (
            <KonvaImage image={bgImage} width={imgW * scale} height={imgH * scale} />
          )}
          {zones.map(zone => (
            <React.Fragment key={zone.id}>
              <Line
                points={zone.points.flatMap(([x, y]) => [x * scale, y * scale])}
                closed
                fill={ZONE_COLORS[zone.type] + '33'}
                stroke={ZONE_COLORS[zone.type]}
                strokeWidth={2}
              />
              {zone.points.length > 0 && (
                <Text
                  x={zone.points[0][0] * scale + 4}
                  y={zone.points[0][1] * scale + 4}
                  text={zone.name}
                  fontSize={12}
                  fill={ZONE_COLORS[zone.type]}
                />
              )}
            </React.Fragment>
          ))}
          {obstacles.map(obs => (
            <Line
              key={obs.id}
              points={obs.points.flatMap(([x, y]) => [x * scale, y * scale])}
              closed fill="#6b728033" stroke="#6b7280" strokeWidth={2} dash={[6, 3]}
            />
          ))}
          {cameraConfigs.map(cc => (
            <React.Fragment key={cc.id}>
              <Circle
                x={cc.position_x * scale} y={cc.position_y * scale}
                radius={8}
                fill={cc.status === 'verified' ? '#10b981' : cc.status === 'calibrated' ? '#f59e0b' : '#6b7280'}
                stroke="#fff" strokeWidth={2}
              />
              <Text
                x={cc.position_x * scale + 12} y={cc.position_y * scale - 6}
                text={cc.physical_camera_name} fontSize={11} fill="#1f2937"
              />
            </React.Fragment>
          ))}
        </Layer>
      </Stage>
    </div>
  )
}

// ─── Section step progress ────────────────────────────────────────────────────

const STEPS = [
  { label: 'Floor Plan', done: s => !!s?.floor_plan?.image_uploaded },
  { label: 'Zones',      done: s => (s?.zones?.length ?? 0) > 0 },
  { label: 'Cameras',    done: s => (s?.camera_configs?.length ?? 0) > 0 },
  { label: 'Obstacles',  done: s => (s?.obstacles?.length ?? 0) > 0 },
]

function SectionStepProgress({ section }) {
  const completions = STEPS.map(step => step.done(section))
  const currentIdx = completions.findIndex(c => !c)

  return (
    <div className="mb-4">
      <div className="flex items-center">
        {STEPS.map((step, i) => {
          const done = completions[i]
          const current = i === currentIdx
          return (
            <React.Fragment key={step.label}>
              <div className="flex flex-col items-center gap-1">
                <div className={`w-6 h-6 rounded-full text-xs font-bold flex items-center justify-center ${
                  done    ? 'bg-blue-600 text-white' :
                  current ? 'bg-blue-100 text-blue-700 ring-2 ring-blue-400' :
                            'bg-gray-100 text-gray-400'
                }`}>
                  {i + 1}
                </div>
                <span className="text-[10px] text-gray-400 whitespace-nowrap">{step.label}</span>
              </div>
              {i < STEPS.length - 1 && (
                <div className="flex-1 h-px bg-gray-200 mx-1 mb-3.5" />
              )}
            </React.Fragment>
          )
        })}
      </div>
    </div>
  )
}

// ─── Sections panel ───────────────────────────────────────────────────────────

function SectionsPanel({ slug, sections, selectedSectionId, onSelect, onSectionsChanged, versionSections = [], onRequestAdd }) {
  // Build a lookup map from version data (has camera_configs, zones, floor_plan)
  const versionMap = Object.fromEntries(versionSections.map(s => [s.id, s]))
  const [adding, setAdding] = useState(false)
  const [newName, setNewName] = useState('')
  const [editingId, setEditingId] = useState(null)
  const [editName, setEditName] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const addInputRef = useRef(null)
  const editInputRef = useRef(null)

  useEffect(() => { if (adding) addInputRef.current?.focus() }, [adding])
  useEffect(() => { if (editingId) editInputRef.current?.focus() }, [editingId])
  useEffect(() => {
    if (onRequestAdd) { onRequestAdd(() => { setAdding(true); setEditingId(null) }) }
  }, [])

  async function handleCreate(e) {
    e.preventDefault()
    const name = newName.trim()
    if (!name) return
    setBusy(true); setErr('')
    try {
      const created = await createSection(slug, { name, type: 'floor', display_order: sections.length })
      setNewName(''); setAdding(false)
      onSectionsChanged(created)
    } catch (e) {
      setErr(e.response?.data?.detail?.error || 'Failed to create section')
    } finally { setBusy(false) }
  }

  async function handleRename(section) {
    const name = editName.trim()
    if (!name || name === section.name) { setEditingId(null); return }
    setBusy(true); setErr('')
    try {
      const updated = await patchSection(slug, section.id, { name })
      setEditingId(null)
      onSectionsChanged(updated)
    } catch (e) {
      setErr(e.response?.data?.detail?.error || 'Failed to rename section')
    } finally { setBusy(false) }
  }

  async function handleDelete(section) {
    if (!window.confirm(`Delete section "${section.name}"? This cannot be undone.`)) return
    setBusy(true); setErr('')
    try {
      await deleteSection(slug, section.id)
      onSectionsChanged(null, section.id)
    } catch (e) {
      setErr(e.response?.data?.detail?.error || 'Failed to delete section')
    } finally { setBusy(false) }
  }

  function startEdit(section) {
    setEditingId(section.id)
    setEditName(section.name)
    setAdding(false)
  }

  function cancelEdit() { setEditingId(null); setErr('') }
  function cancelAdd() { setAdding(false); setNewName(''); setErr('') }

  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden shadow-sm">
      <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-700">Sections</h3>
        <button
          onClick={() => { setAdding(true); setEditingId(null) }}
          disabled={busy || adding}
          className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800 font-medium disabled:opacity-40"
        >
          <Plus size={13} /> Add
        </button>
      </div>

      <div className="divide-y divide-gray-50">
        {sections.map(s => (
          <div
            key={s.id}
            className={`flex items-center gap-2 px-3 py-2.5 group transition-colors ${
              s.id === selectedSectionId ? 'bg-blue-50' : 'hover:bg-gray-50'
            }`}
          >
            {editingId === s.id ? (
              <form onSubmit={e => { e.preventDefault(); handleRename(s) }} className="flex-1 flex items-center gap-1.5">
                <input
                  ref={editInputRef}
                  value={editName}
                  onChange={e => setEditName(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Escape') cancelEdit() }}
                  className="flex-1 text-sm border border-blue-400 rounded px-2 py-0.5 focus:outline-none focus:ring-2 focus:ring-blue-200 min-w-0"
                  disabled={busy}
                />
                <button type="submit" disabled={busy} className="text-green-600 hover:text-green-800 p-0.5">
                  <Check size={14} />
                </button>
                <button type="button" onClick={cancelEdit} className="text-gray-400 hover:text-gray-600 p-0.5">
                  <X size={14} />
                </button>
              </form>
            ) : (
              <>
                <button
                  onClick={() => onSelect(s.id)}
                  className="flex-1 text-left min-w-0"
                >
                  <div className="flex items-center gap-1.5 min-w-0">
                    <span className={`text-sm truncate ${s.id === selectedSectionId ? 'text-blue-700 font-semibold' : 'text-gray-700'}`}>
                      {s.name}
                    </span>
                    {versionMap[s.id] && !versionMap[s.id].floor_plan?.image_uploaded && (
                      <span className="text-[10px] text-amber-600 bg-amber-50 rounded px-1.5 shrink-0 whitespace-nowrap">
                        No floor plan
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
                    {s.is_default && (
                      <span className="text-[10px] text-gray-400 uppercase tracking-wide">Default</span>
                    )}
                    {versionMap[s.id] && (
                      <span className="text-xs text-gray-400">
                        {versionMap[s.id].camera_configs?.length ?? 0} cameras · {versionMap[s.id].zones?.length ?? 0} zones
                      </span>
                    )}
                  </div>
                </button>
                <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                  <button
                    onClick={() => startEdit(s)}
                    disabled={busy}
                    className="p-1 rounded text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-colors"
                    title="Rename"
                  >
                    <Pencil size={12} />
                  </button>
                  {!s.is_default && (
                    <button
                      onClick={() => handleDelete(s)}
                      disabled={busy}
                      className="p-1 rounded text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors"
                      title="Delete"
                    >
                      <Trash2 size={12} />
                    </button>
                  )}
                </div>
              </>
            )}
          </div>
        ))}

        {adding && (
          <form onSubmit={handleCreate} className="px-3 py-2.5 flex items-center gap-1.5 bg-blue-50/50">
            <input
              ref={addInputRef}
              value={newName}
              onChange={e => setNewName(e.target.value)}
              onKeyDown={e => { if (e.key === 'Escape') cancelAdd() }}
              placeholder="Section name…"
              className="flex-1 text-sm border border-blue-400 rounded px-2 py-0.5 focus:outline-none focus:ring-2 focus:ring-blue-200 bg-white min-w-0"
              disabled={busy}
            />
            <button type="submit" disabled={busy || !newName.trim()} className="text-green-600 hover:text-green-800 p-0.5 disabled:opacity-40">
              <Check size={14} />
            </button>
            <button type="button" onClick={cancelAdd} className="text-gray-400 hover:text-gray-600 p-0.5">
              <X size={14} />
            </button>
          </form>
        )}
      </div>

      {err && (
        <div className="px-3 py-2 text-xs text-red-600 bg-red-50 border-t border-red-100">{err}</div>
      )}
    </div>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function StoreConfig() {
  const { slug } = useParams()
  const navigate = useNavigate()
  usePageTitle('Store Config')

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [version, setVersion] = useState(null)
  const [versions, setVersions] = useState([])
  const [sections, setSections] = useState([])
  const [selectedSectionId, setSelectedSectionId] = useState(null)
  const [draft, setDraft] = useState(null)
  const [restoring, setRestoring] = useState(null)
  const [pendingSyncEvent, setPendingSyncEvent] = useState(null)
  const syncPollRef = useRef(null)
  const startAddingSectionRef = useRef(null)

  function reload() {
    setLoading(true)
    setError(null)
    Promise.all([
      getActiveVersion(slug).catch(() => null),
      listVersions(slug).catch(() => []),
      listSections(slug).catch(() => []),
      getDraft(slug).catch(() => null),
    ]).then(([v, vs, sects, d]) => {
      setVersion(v)
      setVersions(vs)
      setSections(sects)
      setDraft(d)
      setSelectedSectionId(prev => {
        // keep selection if still valid, else default to first
        if (prev && sects.some(s => s.id === prev)) return prev
        return v?.sections?.[0]?.id || sects[0]?.id || null
      })
      setLoading(false)
    }).catch(err => {
      setError(err.message)
      setLoading(false)
    })
  }

  useEffect(() => { reload() }, [slug])

  // Poll pending sync event for the draft version (shows progress bar in version history)
  useEffect(() => {
    clearInterval(syncPollRef.current)
    const draftVersion = versions.find(v => v.status === 'draft')
    if (!draftVersion?.pending_sync_event_id) { setPendingSyncEvent(null); return }
    const eventId = draftVersion.pending_sync_event_id
    getSyncEvent(slug, eventId).then(setPendingSyncEvent).catch(() => {})
    syncPollRef.current = setInterval(async () => {
      try {
        const ev = await getSyncEvent(slug, eventId)
        setPendingSyncEvent(ev)
        if (ev.status !== 'pending') {
          clearInterval(syncPollRef.current)
          if (ev.status === 'executed') reload()
        }
      } catch { clearInterval(syncPollRef.current) }
    }, 2000)
    return () => clearInterval(syncPollRef.current)
  }, [versions, slug])

  // Called by SectionsPanel after create/rename/delete
  function handleSectionsChanged(updated, deletedId) {
    if (deletedId) {
      setSections(prev => {
        const next = prev.filter(s => s.id !== deletedId)
        // If we deleted the selected one, fall back to first remaining
        if (selectedSectionId === deletedId) {
          setSelectedSectionId(next[0]?.id || null)
        }
        return next
      })
    } else if (updated) {
      setSections(prev => {
        const exists = prev.some(s => s.id === updated.id)
        const next = exists
          ? prev.map(s => s.id === updated.id ? updated : s)
          : [...prev, updated]
        // Auto-select newly created section
        if (!exists) setSelectedSectionId(updated.id)
        return next
      })
    }
  }

  async function handleRestore(versionId) {
    if (!window.confirm('Restore this version as active? The current active version will be archived.')) return
    setRestoring(versionId)
    try {
      await reactivateVersion(slug, versionId)
      reload()
    } catch (err) {
      const detail = err?.response?.data?.detail
      const msg = (typeof detail === 'object' ? detail?.error : detail)
        || err?.response?.data?.error
        || err.message
      const status = err?.response?.status
      if (status === 409) {
        setError('Cannot restore: a draft configuration already exists. Discard the current draft first.')
      } else {
        setError(msg || 'Failed to restore version.')
      }
    } finally {
      setRestoring(null)
    }
  }

  if (loading) {
    return (
      <div className="p-6 space-y-4 max-w-4xl">
        <div className="skeleton h-8 w-48" />
        <div className="skeleton h-64 w-full rounded-xl" />
        <div className="skeleton h-32 w-full rounded-xl" />
      </div>
    )
  }

  if (error) {
    return <div className="p-6 text-red-500">Error: {error}</div>
  }

  // No active config yet
  if (!version) {
    return (
      <div className="page-enter flex flex-col h-full overflow-auto">
        <header className="px-6 py-4 border-b border-gray-200 bg-white shrink-0 flex items-center justify-between">
          <div>
            <h1 className="page-title">Store Configuration</h1>
            <p className="page-subtitle">No active configuration</p>
          </div>
          <button onClick={() => navigate(`/store/${slug}/config/edit`)} className="btn-primary">
            {draft ? 'Continue Setup' : 'Start Onboarding'}
          </button>
        </header>

        <div className="flex-1 p-6 grid grid-cols-1 lg:grid-cols-4 gap-6">
          {/* Sections panel — available even with no active config */}
          <div className="lg:col-span-1 space-y-4">
            <SectionsPanel
              slug={slug}
              sections={sections}
              selectedSectionId={selectedSectionId}
              onSelect={setSelectedSectionId}
              onSectionsChanged={handleSectionsChanged}
              onRequestAdd={fn => { startAddingSectionRef.current = fn }}
            />
          </div>

          <div className="lg:col-span-3 space-y-4">
            {draft && (
              <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 flex items-center justify-between">
                <div>
                  <p className="text-blue-800 font-semibold text-sm">Setup in progress</p>
                  <p className="text-blue-600 text-xs mt-0.5">You have an unfinished configuration draft.</p>
                </div>
                <button
                  onClick={() => navigate(`/store/${slug}/config/edit`)}
                  className="btn-primary text-xs py-1.5"
                >
                  Continue
                </button>
              </div>
            )}
            {sections.length === 0 ? (
              <div className="bg-white border border-gray-200 rounded-xl p-8 flex flex-col items-center justify-center text-center gap-4">
                <div className="w-14 h-14 rounded-full bg-blue-50 flex items-center justify-center">
                  <Warehouse size={28} className="text-blue-500" />
                </div>
                <div>
                  <h2 className="text-base font-semibold text-gray-800 mb-1">Set up your first section</h2>
                  <p className="text-sm text-gray-500 max-w-sm">
                    Sections represent distinct physical areas of your store, each covered by a dedicated camera group.
                    Add a section to start mapping your floor plan, zones, and cameras.
                  </p>
                </div>
                <button
                  onClick={() => startAddingSectionRef.current?.()}
                  className="btn-primary"
                >
                  Add Section
                </button>
              </div>
            ) : (
              <div className="bg-amber-50 border border-amber-200 rounded-xl p-6 text-center">
                <p className="text-amber-800 font-semibold mb-1">No active configuration</p>
                <p className="text-amber-700 text-sm">
                  Complete the onboarding wizard to configure floor plans, cameras and zones for each section.
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    )
  }

  // Merge version sections with raw sections list so the panel always reflects latest state
  const mergedSections = sections.length > 0 ? sections : (version.sections || [])
  const selectedSection = version.sections?.find(s => s.id === selectedSectionId)
    || (selectedSectionId ? null : version.sections?.[0])
    || null

  return (
    <div className="page-enter flex flex-col h-full overflow-auto">
      {/* Header */}
      <header className="px-6 py-4 border-b border-gray-200 bg-white shrink-0 flex items-center justify-between">
        <div>
          <h1 className="page-title">Store Configuration</h1>
          <p className="page-subtitle">
            Active version{version.label ? `: ${version.label}` : ''} · Since{' '}
            {version.active_from ? new Date(version.active_from).toLocaleDateString() : '—'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {draft && (
            <span className="text-xs text-amber-700 bg-amber-50 border border-amber-200 px-2.5 py-1 rounded-lg">
              Draft in progress
            </span>
          )}
          <button
            onClick={() => navigate(`/store/${slug}/config/edit${selectedSectionId ? `?section=${selectedSectionId}` : ''}`)}
            className="btn-primary"
          >
            {draft ? 'Continue Draft' : 'Edit Configuration'}
          </button>
        </div>
      </header>

      <div className="flex-1 p-6 space-y-6">
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">

          {/* Left panel */}
          <div className="lg:col-span-1 space-y-4">

            {/* Sections — full management panel */}
            <SectionsPanel
              slug={slug}
              sections={mergedSections}
              selectedSectionId={selectedSectionId}
              onSelect={setSelectedSectionId}
              onSectionsChanged={handleSectionsChanged}
              versionSections={version?.sections || []}
            />

            {/* Zone legend for selected section */}
            {selectedSection?.zones?.length > 0 && (
              <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
                <h3 className="text-sm font-semibold text-gray-700 mb-3">
                  Zones <span className="text-gray-400 font-normal">({selectedSection.zones.length})</span>
                </h3>
                <div className="space-y-2">
                  {selectedSection.zones.map(z => (
                    <div key={z.id} className="flex items-center gap-2 text-sm">
                      <span className="w-3 h-3 rounded-sm flex-shrink-0" style={{ background: ZONE_COLORS[z.type] }} />
                      <span className="text-gray-700 truncate">{z.name}</span>
                      <span className="text-gray-400 text-xs capitalize ml-auto">{z.type}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Camera list for selected section */}
            {selectedSection?.camera_configs?.length > 0 && (
              <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
                <h3 className="text-sm font-semibold text-gray-700 mb-3">
                  Cameras <span className="text-gray-400 font-normal">({selectedSection.camera_configs.length})</span>
                </h3>
                <div className="space-y-2">
                  {selectedSection.camera_configs.map(cc => (
                    <div key={cc.id} className="flex items-center gap-2 text-sm">
                      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                        cc.status === 'verified' ? 'bg-green-500' :
                        cc.status === 'calibrated' ? 'bg-yellow-500' : 'bg-gray-400'
                      }`} />
                      <span className="text-gray-700 truncate">{cc.physical_camera_name}</span>
                      {(!cc.position_x || cc.position_x === 0) && (!cc.position_y || cc.position_y === 0) && (
                        <span className="text-[10px] bg-amber-50 text-amber-600 border border-amber-200 rounded px-1.5 py-0.5 ml-2 shrink-0">No position</span>
                      )}
                      <span className="text-gray-400 text-xs capitalize ml-auto">{cc.status}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Empty state for section with no config data */}
            {selectedSection && !selectedSection.zones?.length && !selectedSection.camera_configs?.length && (
              <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm text-center">
                <p className="text-xs text-gray-400">
                  No zones or cameras configured for this section yet.
                </p>
                <button
                  onClick={() => navigate(`/store/${slug}/config/edit?section=${selectedSectionId}`)}
                  className="mt-2 text-xs text-blue-600 hover:text-blue-800 font-medium"
                >
                  Configure →
                </button>
              </div>
            )}
          </div>

          {/* Floor plan canvas */}
          <div className="lg:col-span-3 bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
            {selectedSection && <SectionStepProgress section={selectedSection} />}
            <div className="flex items-center justify-between mb-3 gap-3">
              <div className="flex items-center gap-3 min-w-0 flex-1">
                <h3 className="text-sm font-semibold text-gray-700 shrink-0">
                  {selectedSection?.name || 'Floor Plan'}
                </h3>
                <SectionTabs
                  sections={mergedSections}
                  selectedId={selectedSectionId}
                  onChange={setSelectedSectionId}
                  onAdd={() => startAddingSectionRef.current?.()}
                />
              </div>
              {selectedSection?.floor_plan?.scale_defined && (
                <span className="text-xs text-gray-400 bg-gray-50 px-2 py-0.5 rounded border border-gray-200 shrink-0">
                  {selectedSection.floor_plan.pixels_per_meter?.toFixed(1)} px/m
                </span>
              )}
            </div>
            {selectedSection ? (
              <FloorPlanCanvas
                floorPlan={selectedSection.floor_plan}
                zones={selectedSection.zones || []}
                obstacles={selectedSection.obstacles || []}
                cameraConfigs={selectedSection.camera_configs || []}
              />
            ) : (
              <div className="flex items-center justify-center h-64 text-gray-400 text-sm">
                Select a section to view its floor plan
              </div>
            )}
          </div>
        </div>

        {/* Version history */}
        {versions.length > 0 && (
          <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
            <h3 className="text-sm font-semibold text-gray-700 mb-3">Version History</h3>
            {error && (
              <div className="mb-3 p-2 bg-red-50 border border-red-200 rounded text-xs text-red-700 flex items-center justify-between">
                <span>{error}</span>
                <button onClick={() => setError(null)} className="ml-2 text-red-400 hover:text-red-600">✕</button>
              </div>
            )}
            <div className="divide-y divide-gray-100">
              {versions.map(v => {
                const isPending = v.status === 'draft' && pendingSyncEvent?.status === 'pending' && v.pending_sync_event_id
                const countdown = isPending ? (pendingSyncEvent?.remaining_seconds ?? 0) : null
                const totalSec = isPending ? (pendingSyncEvent?.countdown_sec ?? 30) : 30
                const progress = isPending ? Math.min(100, 100 - (Math.max(0, countdown) / totalSec) * 100) : 0
                return (
                <div key={v.id} className="py-2.5 space-y-1.5">
                  <div className="flex items-center gap-3 text-sm">
                  <span className={`px-2 py-0.5 rounded-full text-xs font-medium flex-shrink-0 ${
                    v.status === 'active' ? 'bg-green-100 text-green-700' :
                    isPending ? 'bg-yellow-100 text-yellow-700' :
                    v.status === 'draft' ? 'bg-blue-100 text-blue-700' :
                    'bg-gray-100 text-gray-500'
                  }`}>{isPending ? 'Pending' : v.status}</span>
                  <span className="text-gray-700 font-medium truncate">{v.label || '(unlabeled)'}</span>
                  <span className="text-gray-400 text-xs ml-auto flex-shrink-0">
                    {v.active_from ? new Date(v.active_from).toLocaleDateString() : new Date(v.created_at).toLocaleDateString()}
                  </span>
                  {v.status === 'archived' && (
                    <button
                      onClick={() => handleRestore(v.id)}
                      disabled={restoring === v.id}
                      className="text-xs text-blue-600 hover:text-blue-800 flex-shrink-0 disabled:opacity-50 font-medium"
                    >
                      {restoring === v.id ? 'Restoring…' : 'Restore'}
                    </button>
                  )}
                </div>
                  {isPending && (
                    <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-yellow-400 rounded-full transition-all"
                        style={{ width: `${progress}%`, transitionDuration: '2000ms' }}
                      />
                    </div>
                  )}
                </div>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
