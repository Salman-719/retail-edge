import React, { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Stage, Layer, Image as KonvaImage, Line, Circle, Text } from 'react-konva'
import { Warehouse } from 'lucide-react'
import {
  getDraft, getActiveVersion, listVersions, reactivateVersion,
  patchCamera, updateCameraConfig,
} from '../api'
import { usePageTitle } from '../components/PageMeta'

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
        <span>No floor plan uploaded yet</span>
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

// ─── Setup step progress ──────────────────────────────────────────────────────

const STEPS = [
  { label: 'Floor Plan', done: v => !!v?.floor_plan?.image_uploaded },
  { label: 'Zones',      done: v => (v?.zones?.length ?? 0) > 0 },
  { label: 'Cameras',    done: v => (v?.camera_configs?.length ?? 0) > 0 },
  { label: 'Obstacles',  done: v => (v?.obstacles?.length ?? 0) > 0 },
]

function SetupProgress({ version }) {
  const completions = STEPS.map(step => step.done(version))
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

// ─── Main page ────────────────────────────────────────────────────────────────

export default function StoreConfig() {
  const { slug } = useParams()
  const navigate = useNavigate()
  usePageTitle('Store Config')

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [version, setVersion] = useState(null)
  const [versions, setVersions] = useState([])
  const [draft, setDraft] = useState(null)
  const [restoring, setRestoring] = useState(null)
  const [editingCameraId, setEditingCameraId] = useState(null)
  const [editCameraForm, setEditCameraForm] = useState({ height_meters: '', stream_url: '' })
  const [savingCamera, setSavingCamera] = useState(false)

  function reload() {
    setLoading(true)
    setError(null)
    Promise.all([
      getActiveVersion(slug).catch(() => null),
      listVersions(slug).catch(() => []),
      getDraft(slug).catch(() => null),
    ]).then(([v, vs, d]) => {
      setVersion(v)
      setVersions(vs)
      setDraft(d)
      setLoading(false)
    }).catch(err => {
      setError(err.message)
      setLoading(false)
    })
  }

  useEffect(() => { reload() }, [slug])

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

        <div className="flex-1 p-6">
          {draft && (
            <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 flex items-center justify-between mb-4 max-w-2xl">
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
          <div className="bg-white border border-gray-200 rounded-xl p-8 flex flex-col items-center justify-center text-center gap-4 max-w-2xl">
            <div className="w-14 h-14 rounded-full bg-blue-50 flex items-center justify-center">
              <Warehouse size={28} className="text-blue-500" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-gray-800 mb-1">Set up your store</h2>
              <p className="text-sm text-gray-500 max-w-sm">
                Run the onboarding wizard to map your floor plan, draw zones, and place
                and calibrate cameras.
              </p>
            </div>
            <button onClick={() => navigate(`/store/${slug}/config/edit`)} className="btn-primary">
              {draft ? 'Continue Setup' : 'Start Onboarding'}
            </button>
          </div>
        </div>
      </div>
    )
  }

  const zones = version.zones || []
  const cameraConfigs = version.camera_configs || []

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
            onClick={() => navigate(`/store/${slug}/config/edit`)}
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

            {/* Zone legend */}
            {zones.length > 0 && (
              <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
                <h3 className="text-sm font-semibold text-gray-700 mb-3">
                  Zones <span className="text-gray-400 font-normal">({zones.length})</span>
                </h3>
                <div className="space-y-2">
                  {zones.map(z => (
                    <div key={z.id} className="flex items-center gap-2 text-sm">
                      <span className="w-3 h-3 rounded-sm flex-shrink-0" style={{ background: ZONE_COLORS[z.type] }} />
                      <span className="text-gray-700 truncate">{z.name}</span>
                      <span className="text-gray-400 text-xs capitalize ml-auto">{z.type}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Camera list */}
            {cameraConfigs.length > 0 && (
              <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
                <h3 className="text-sm font-semibold text-gray-700 mb-3">
                  Cameras <span className="text-gray-400 font-normal">({cameraConfigs.length})</span>
                </h3>
                <div className="space-y-1">
                  {cameraConfigs.map(cc => (
                    <div key={cc.id} className="rounded border border-gray-100 text-sm">
                      <div className="flex items-center gap-2 px-3 py-2">
                        <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                          cc.status === 'verified' ? 'bg-green-500' :
                          cc.status === 'calibrated' ? 'bg-yellow-500' : 'bg-gray-400'
                        }`} />
                        <span className="text-gray-700 font-medium truncate">{cc.physical_camera_name}</span>
                        {cc.height_meters != null && (
                          <span className="text-xs text-gray-400">{cc.height_meters}m</span>
                        )}
                        {cc.stream_url && (
                          <span className="text-xs text-gray-400 font-mono truncate max-w-[200px]">{cc.stream_url}</span>
                        )}
                        {(!cc.position_x || cc.position_x === 0) && (!cc.position_y || cc.position_y === 0) && (
                          <span className="text-[10px] bg-amber-50 text-amber-600 border border-amber-200 rounded px-1.5 py-0.5 shrink-0">No position</span>
                        )}
                        <span className="text-gray-400 text-xs capitalize ml-auto">{cc.status}</span>
                        <button
                          onClick={() => {
                            if (editingCameraId === cc.id) { setEditingCameraId(null); return }
                            setEditingCameraId(cc.id)
                            setEditCameraForm({ height_meters: cc.height_meters ?? '', stream_url: cc.stream_url ?? '' })
                          }}
                          className="text-xs text-blue-500 hover:text-blue-700 flex-shrink-0"
                        >
                          {editingCameraId === cc.id ? 'Cancel' : 'Edit'}
                        </button>
                      </div>
                      {editingCameraId === cc.id && (
                        <form
                          onSubmit={async e => {
                            e.preventDefault()
                            setSavingCamera(true)
                            try {
                              const configBody = {}
                              if (editCameraForm.height_meters !== '') configBody.height_meters = parseFloat(editCameraForm.height_meters)
                              await Promise.all([
                                Object.keys(configBody).length ? updateCameraConfig(slug, cc.id, configBody) : Promise.resolve(),
                                patchCamera(slug, cc.physical_camera_id, { cloud_stream_url: editCameraForm.stream_url.trim() || null }),
                              ])
                              const patchCc = c => c.id === cc.id
                                ? { ...c, height_meters: editCameraForm.height_meters ? parseFloat(editCameraForm.height_meters) : c.height_meters, stream_url: editCameraForm.stream_url.trim() || null }
                                : c
                              setVersion(v => ({ ...v, camera_configs: v?.camera_configs?.map(patchCc) }))
                              setEditingCameraId(null)
                            } catch (err) {
                              setError(err?.response?.data?.detail?.error || err?.response?.data?.error || err.message)
                            } finally {
                              setSavingCamera(false)
                            }
                          }}
                          className="border-t border-gray-100 px-3 py-2 space-y-2"
                        >
                          <div className="flex items-center gap-3 flex-wrap">
                            <div className="flex items-center gap-1.5">
                              <label className="text-xs text-gray-500">Height (m):</label>
                              <input
                                type="number" step="0.1" min="0.1"
                                value={editCameraForm.height_meters}
                                onChange={e => setEditCameraForm(f => ({ ...f, height_meters: e.target.value }))}
                                className="w-20 border border-gray-300 rounded px-2 py-1 text-xs"
                                placeholder="e.g. 3.5"
                              />
                            </div>
                            <button
                              type="submit"
                              disabled={savingCamera}
                              className="px-3 py-1 bg-blue-600 text-white rounded text-xs font-medium disabled:opacity-50"
                            >
                              {savingCamera ? 'Saving…' : 'Save'}
                            </button>
                          </div>
                          <div className="flex items-center gap-1.5">
                            <label className="text-xs text-gray-500 flex-shrink-0">Stream URL:</label>
                            <input
                              type="text"
                              value={editCameraForm.stream_url}
                              onChange={e => setEditCameraForm(f => ({ ...f, stream_url: e.target.value }))}
                              className="flex-1 border border-gray-300 rounded px-2 py-1 text-xs font-mono"
                              placeholder="rtsp://host.docker.internal:8554/cam1"
                            />
                          </div>
                        </form>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Empty state when no zones or cameras configured */}
            {!zones.length && !cameraConfigs.length && (
              <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm text-center">
                <p className="text-xs text-gray-400">
                  No zones or cameras configured yet.
                </p>
                <button
                  onClick={() => navigate(`/store/${slug}/config/edit`)}
                  className="mt-2 text-xs text-blue-600 hover:text-blue-800 font-medium"
                >
                  Configure →
                </button>
              </div>
            )}
          </div>

          {/* Floor plan canvas */}
          <div className="lg:col-span-3 bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
            <SetupProgress version={version} />
            <div className="flex items-center justify-between mb-3 gap-3">
              <h3 className="text-sm font-semibold text-gray-700 shrink-0">Floor Plan</h3>
              {version.floor_plan?.scale_defined && (
                <span className="text-xs text-gray-400 bg-gray-50 px-2 py-0.5 rounded border border-gray-200 shrink-0">
                  {version.floor_plan.pixels_per_meter?.toFixed(1)} px/m
                </span>
              )}
            </div>
            <FloorPlanCanvas
              floorPlan={version.floor_plan}
              zones={zones}
              obstacles={version.obstacles || []}
              cameraConfigs={cameraConfigs}
            />
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
              {versions.map(v => (
                <div key={v.id} className="py-2.5">
                  <div className="flex items-center gap-3 text-sm">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium flex-shrink-0 ${
                      v.status === 'active'             ? 'bg-green-100 text-green-700'  :
                      v.status === 'pending_activation' ? 'bg-yellow-100 text-yellow-700' :
                      v.status === 'draft'              ? 'bg-blue-100 text-blue-700'    :
                      'bg-gray-100 text-gray-500'
                    }`}>
                      {v.status === 'pending_activation' ? 'Scheduled' : v.status}
                    </span>
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
                  {v.status === 'pending_activation' && v.activate_at && (
                    <p className="text-xs text-yellow-600 mt-1 pl-0.5">
                      Activates {new Date(v.activate_at).toLocaleString()}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
