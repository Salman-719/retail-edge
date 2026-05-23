import React, { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Stage, Layer, Image as KonvaImage, Line, Circle, Text } from 'react-konva'
import { getDraft, getActiveVersion, listSections, listVersions, reactivateVersion } from '../api'

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
      <div className="flex items-center justify-center h-64 bg-gray-100 rounded text-gray-400 text-sm">
        No floor plan uploaded
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
            <KonvaImage
              image={bgImage}
              width={imgW * scale}
              height={imgH * scale}
            />
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
              closed
              fill="#6b728033"
              stroke="#6b7280"
              strokeWidth={2}
              dash={[6, 3]}
            />
          ))}
          {cameraConfigs.map(cc => (
            <React.Fragment key={cc.id}>
              <Circle
                x={cc.position_x * scale}
                y={cc.position_y * scale}
                radius={8}
                fill={cc.status === 'verified' ? '#10b981' : cc.status === 'calibrated' ? '#f59e0b' : '#6b7280'}
                stroke="#fff"
                strokeWidth={2}
              />
              <Text
                x={cc.position_x * scale + 12}
                y={cc.position_y * scale - 6}
                text={cc.physical_camera_name}
                fontSize={11}
                fill="#1f2937"
              />
            </React.Fragment>
          ))}
        </Layer>
      </Stage>
    </div>
  )
}

export default function StoreConfig() {
  const { slug } = useParams()
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [version, setVersion] = useState(null)
  const [versions, setVersions] = useState([])
  const [sections, setSections] = useState([])
  const [selectedSectionId, setSelectedSectionId] = useState(null)
  const [draft, setDraft] = useState(null)
  const [restoring, setRestoring] = useState(null)

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
      if (v?.sections?.length) {
        setSelectedSectionId(v.sections[0].id)
      }
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
      setError(err?.response?.data?.error || err.message)
    } finally {
      setRestoring(null)
    }
  }

  if (loading) {
    return <div className="flex items-center justify-center h-64 text-gray-400">Loading configuration…</div>
  }

  if (error) {
    return <div className="p-6 text-red-500">Error: {error}</div>
  }

  if (!version) {
    return (
      <div className="p-6">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-semibold text-gray-900">Store Configuration</h1>
          <button
            onClick={() => navigate(`/store/${slug}/config/edit`)}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700"
          >
            {draft ? 'Continue Setup' : 'Start Onboarding'}
          </button>
        </div>
        {draft && (
          <div className="mb-4 bg-blue-50 border border-blue-200 rounded-lg p-4 flex items-center justify-between">
            <div>
              <p className="text-blue-800 font-medium text-sm">Setup in progress</p>
              <p className="text-blue-600 text-xs mt-0.5">You have an unfinished configuration draft.</p>
            </div>
            <button
              onClick={() => navigate(`/store/${slug}/config/edit`)}
              className="px-3 py-1.5 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700"
            >
              Continue
            </button>
          </div>
        )}
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-6 text-center">
          <p className="text-amber-800 font-medium mb-2">No active configuration</p>
          <p className="text-amber-700 text-sm">Complete the onboarding wizard to set up your store configuration.</p>
        </div>
      </div>
    )
  }

  const selectedSection = version.sections?.find(s => s.id === selectedSectionId) || version.sections?.[0]

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Store Configuration</h1>
          <p className="text-sm text-gray-500 mt-1">
            Active version{version.label ? `: ${version.label}` : ''} · Active since{' '}
            {version.active_from ? new Date(version.active_from).toLocaleDateString() : '—'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {draft && (
            <span className="text-xs text-amber-700 bg-amber-50 border border-amber-200 px-2 py-1 rounded">
              Draft in progress
            </span>
          )}
          <button
            onClick={() => navigate(`/store/${slug}/config/edit`)}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700"
          >
            {draft ? 'Continue Draft' : 'Edit Configuration'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Left panel */}
        <div className="lg:col-span-1 space-y-4">
          {/* Section selector */}
          <div className="bg-white border border-gray-200 rounded-lg p-4">
            <h3 className="text-sm font-medium text-gray-700 mb-3">Sections</h3>
            <div className="space-y-1">
              {version.sections?.map(s => (
                <button
                  key={s.id}
                  onClick={() => setSelectedSectionId(s.id)}
                  className={`w-full text-left px-3 py-2 rounded text-sm transition-colors ${
                    s.id === selectedSectionId
                      ? 'bg-blue-50 text-blue-700 font-medium'
                      : 'text-gray-600 hover:bg-gray-50'
                  }`}
                >
                  {s.name}
                  {s.is_default && <span className="ml-1 text-xs text-gray-400">(default)</span>}
                </button>
              ))}
            </div>
          </div>

          {/* Zone legend */}
          {selectedSection?.zones?.length > 0 && (
            <div className="bg-white border border-gray-200 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-700 mb-3">
                Zones ({selectedSection.zones.length})
              </h3>
              <div className="space-y-2">
                {selectedSection.zones.map(z => (
                  <div key={z.id} className="flex items-center gap-2 text-sm">
                    <span
                      className="w-3 h-3 rounded-sm flex-shrink-0"
                      style={{ background: ZONE_COLORS[z.type] }}
                    />
                    <span className="text-gray-700 truncate">{z.name}</span>
                    <span className="text-gray-400 text-xs capitalize ml-auto">{z.type}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Cameras */}
          {selectedSection?.camera_configs?.length > 0 && (
            <div className="bg-white border border-gray-200 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-700 mb-3">
                Cameras ({selectedSection.camera_configs.length})
              </h3>
              <div className="space-y-2">
                {selectedSection.camera_configs.map(cc => (
                  <div key={cc.id} className="flex items-center gap-2 text-sm">
                    <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                      cc.status === 'verified' ? 'bg-green-500' :
                      cc.status === 'calibrated' ? 'bg-yellow-500' : 'bg-gray-400'
                    }`} />
                    <span className="text-gray-700 truncate">{cc.physical_camera_name}</span>
                    <span className="text-gray-400 text-xs capitalize ml-auto">{cc.status}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Floor plan canvas */}
        <div className="lg:col-span-3 bg-white border border-gray-200 rounded-lg p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-gray-700">
              {selectedSection?.name || 'Floor Plan'}
            </h3>
            {selectedSection?.floor_plan?.scale_defined && (
              <span className="text-xs text-gray-400">
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
              Select a section
            </div>
          )}
        </div>
      </div>

      {/* Version history */}
      {versions.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <h3 className="text-sm font-medium text-gray-700 mb-3">Version History</h3>
          {error && (
            <div className="mb-3 p-2 bg-red-50 border border-red-200 rounded text-xs text-red-700 flex items-center justify-between">
              <span>{error}</span>
              <button onClick={() => setError(null)} className="ml-2 text-red-400 hover:text-red-600">✕</button>
            </div>
          )}
          <div className="space-y-2">
            {versions.map(v => (
              <div key={v.id} className="flex items-center gap-3 text-sm py-2 border-b border-gray-100 last:border-0">
                <span className={`px-2 py-0.5 rounded-full text-xs font-medium flex-shrink-0 ${
                  v.status === 'active' ? 'bg-green-100 text-green-700' :
                  v.status === 'draft' ? 'bg-blue-100 text-blue-700' :
                  'bg-gray-100 text-gray-500'
                }`}>{v.status}</span>
                <span className="text-gray-700 font-medium truncate">{v.label || '(unlabeled)'}</span>
                <span className="text-gray-400 text-xs ml-auto flex-shrink-0">
                  {v.active_from ? new Date(v.active_from).toLocaleDateString() : new Date(v.created_at).toLocaleDateString()}
                </span>
                {v.status === 'archived' && (
                  <button
                    onClick={() => handleRestore(v.id)}
                    disabled={restoring === v.id}
                    className="text-xs text-blue-600 hover:text-blue-800 flex-shrink-0 disabled:opacity-50"
                  >
                    {restoring === v.id ? 'Restoring…' : 'Restore'}
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
