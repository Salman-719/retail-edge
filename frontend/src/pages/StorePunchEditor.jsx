import React, { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Stage, Layer, Image as KonvaImage, Circle, Text } from 'react-konva'
import { ArrowLeft } from 'lucide-react'
import { usePageTitle } from '../components/PageMeta'
import {
  getDraft, createDraft, getDraftFloorPlan, getDraftCameraConfigs,
  getDraftPunchStation, putDraftPunchStation, activateDraft,
} from '../api'

const CALIBRATED = new Set(['calibrated', 'verified'])

function useImage(url) {
  const [image, setImage] = useState(null)
  useEffect(() => {
    if (!url) { setImage(null); return }
    const img = new window.Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => setImage(img)
    img.onerror = () => setImage(null)
    img.src = url
  }, [url])
  return image
}

function apiError(e, fallback) {
  const d = e?.response?.data?.detail
  return (typeof d === 'string' ? d : d?.error) || e?.message || fallback
}

// ── Floor map: place/move the punch marker (image px) ────────────────────────
function PunchMap({ floorPlan, cameras, selectedCameraId, marker, radiusM, onPlace }) {
  const ref = useRef(null)
  const [size, setSize] = useState({ w: 800, h: 480 })
  const bg = useImage(floorPlan?.display_url)

  useEffect(() => {
    if (!ref.current) return
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }))
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [])

  const imgW = floorPlan.width_px || 1
  const imgH = floorPlan.height_px || 1
  const scale = Math.min(size.w / imgW, size.h / imgH)
  const stageH = Math.round(imgH * scale)
  const ppm = floorPlan.pixels_per_meter || 1

  const handleClick = (e) => {
    const ptr = e.target.getStage().getPointerPosition()
    onPlace(ptr.x / scale, ptr.y / scale) // → image px
  }

  return (
    <div ref={ref} className="w-full" style={{ height: stageH }}>
      <Stage width={size.w} height={stageH} onClick={handleClick} style={{ cursor: 'crosshair', background: '#f3f4f6', borderRadius: 8 }}>
        <Layer>
          {bg && <KonvaImage image={bg} width={imgW * scale} height={imgH * scale} />}
          {cameras.map((cc) => (
            <React.Fragment key={cc.id}>
              <Circle x={cc.position_x * scale} y={cc.position_y * scale} radius={7}
                fill={cc.id === selectedCameraId ? '#2563eb' : '#94a3b8'} stroke="#fff" strokeWidth={2} />
              <Text x={cc.position_x * scale + 10} y={cc.position_y * scale - 6} text={cc.physical_camera_name} fontSize={10} fill="#1f2937" />
            </React.Fragment>
          ))}
          {marker && (
            <>
              <Circle x={marker.x * scale} y={marker.y * scale} radius={radiusM * ppm * scale}
                fill="#a855f733" stroke="#a855f7" strokeWidth={2} dash={[5, 3]} />
              <Circle x={marker.x * scale} y={marker.y * scale} radius={6} fill="#a855f7" stroke="#fff" strokeWidth={2} />
            </>
          )}
        </Layer>
      </Stage>
    </div>
  )
}

export default function StorePunchEditor() {
  const { slug } = useParams()
  const navigate = useNavigate()
  usePageTitle('Edit Punch Machine')

  const [loading, setLoading] = useState(true)
  const [fatal, setFatal] = useState('')           // blocks the editor (no draft / no floor scale)
  const [existedDraft, setExistedDraft] = useState(false)
  const [floorPlan, setFloorPlan] = useState(null)
  const [cameras, setCameras] = useState([])
  const [station, setStation] = useState(null)
  const [cameraId, setCameraId] = useState('')
  const [marker, setMarker] = useState(null)        // image px {x,y}
  const [radius, setRadius] = useState(1.5)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [activating, setActivating] = useState(false)

  useEffect(() => {
    let cancelled = false
    async function setup() {
      setLoading(true); setFatal(''); setError('')
      // Ensure a draft: clone the active version if none exists (S2 carries the punch station).
      let d = await getDraft(slug).catch(() => null)
      let existed = !!d
      if (!d) {
        try { d = await createDraft(slug, 'Punch machine update', true) }
        catch (e) { if (!cancelled) { setFatal(apiError(e, 'Could not start a draft from the active version.')); setLoading(false) } return }
      }
      const [fp, cams, st] = await Promise.all([
        getDraftFloorPlan(slug).catch(() => null),
        getDraftCameraConfigs(slug).catch(() => []),
        getDraftPunchStation(slug).catch(() => null), // 404 = none yet
      ])
      if (cancelled) return
      setExistedDraft(existed)
      setFloorPlan(fp)
      setCameras(cams || [])
      setStation(st)
      if (st) { setMarker({ x: st.position_x, y: st.position_y }); setRadius(st.radius_m); setCameraId(st.camera_config_id) }
      setLoading(false)
    }
    setup()
    return () => { cancelled = true }
  }, [slug])

  const calibrated = cameras.filter((c) => CALIBRATED.has(c.status))
  const scaleReady = floorPlan?.image_uploaded && floorPlan?.pixels_per_meter

  async function save() {
    if (!cameraId) { setError('Pick the camera that sees the punch machine.'); return false }
    if (!marker) { setError('Click the map to place the punch marker.'); return false }
    setSaving(true); setError('')
    try {
      const st = await putDraftPunchStation(slug, {
        camera_config_id: cameraId, position_x: marker.x, position_y: marker.y, radius_m: Number(radius),
      })
      setStation(st)
      return true
    } catch (e) {
      setError(apiError(e, 'Failed to save the punch station.'))
      return false
    } finally {
      setSaving(false)
    }
  }

  async function activate() {
    // Persist the current marker first (so a just-placed point is included), then publish.
    if (marker && cameraId) {
      if (!(await save())) return
    } else if (!station) {
      setError('Pick a camera and click the map to place the marker.')
      return
    }
    const msg = existedDraft
      ? 'You have a configuration draft in progress. Activating here publishes ALL of its changes, not just the punch machine. Continue?'
      : 'Activate now? The draft becomes the new active version immediately.'
    if (!window.confirm(msg)) return
    setActivating(true); setError('')
    try {
      await activateDraft(slug, { mode: 'immediate' })
      navigate(`/store/${slug}/config`)
    } catch (e) {
      setError(apiError(e, 'Failed to activate.'))
      setActivating(false)
    }
  }

  const Header = (
    <header className="px-6 py-4 border-b border-gray-200 bg-white shrink-0 flex items-center gap-3">
      <button onClick={() => navigate(`/store/${slug}/config`)} className="text-gray-400 hover:text-gray-700"><ArrowLeft size={18} /></button>
      <div>
        <h1 className="page-title">Edit Punch Machine</h1>
        <p className="page-subtitle">Place the punch-in marker · versioned, activates immediately</p>
      </div>
    </header>
  )

  if (loading) {
    return <div className="page-enter flex flex-col h-full">{Header}<div className="flex-1 p-6"><div className="skeleton h-64 w-full rounded-xl max-w-4xl" /></div></div>
  }

  // Blocking states → guidance to full onboarding.
  const guidance = fatal
    ? fatal
    : !scaleReady
      ? 'The floor plan scale is not set. Complete the floor plan in full onboarding first.'
      : calibrated.length === 0
        ? 'Add and calibrate a camera in full onboarding before setting the punch machine.'
        : null

  if (guidance) {
    return (
      <div className="page-enter flex flex-col h-full">{Header}
        <div className="flex-1 p-6">
          <div className="bg-white border border-gray-200 rounded-xl p-8 max-w-2xl text-center space-y-4">
            <p className="text-sm text-gray-600">{guidance}</p>
            <button onClick={() => navigate(`/store/${slug}/config/edit`)} className="btn-primary">Open full onboarding</button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="page-enter flex flex-col h-full overflow-auto">{Header}
      <div className="flex-1 p-6 space-y-4 max-w-5xl">
        {existedDraft && (
          <div className="bg-amber-50 border border-amber-200 text-amber-800 text-sm px-4 py-3 rounded-lg">
            You have a configuration draft in progress. Activating here will publish <strong>all</strong> of its changes, not just the punch machine.
          </div>
        )}
        {error && <div className="bg-red-50 text-red-700 text-sm px-4 py-3 rounded-lg border border-red-200">{error}</div>}

        <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm space-y-3">
          <div className="flex items-center gap-4 flex-wrap">
            <div className="flex items-center gap-2">
              <label className="text-xs text-gray-500">Punch camera</label>
              <select value={cameraId} onChange={(e) => setCameraId(e.target.value)} className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm">
                <option value="">Select…</option>
                {calibrated.map((c) => <option key={c.id} value={c.id}>{c.physical_camera_name}</option>)}
              </select>
            </div>
            <div className="flex items-center gap-2">
              <label className="text-xs text-gray-500">Radius (m)</label>
              <input type="number" min="0.1" step="0.1" value={radius} onChange={(e) => setRadius(e.target.value)} className="w-24 border border-gray-300 rounded-lg px-3 py-1.5 text-sm" />
            </div>
            <span className="text-xs text-gray-400 ml-auto">Click the map to place the marker</span>
          </div>

          <PunchMap floorPlan={floorPlan} cameras={cameras} selectedCameraId={cameraId} marker={marker} radiusM={Number(radius) || 1.5} onPlace={(x, y) => setMarker({ x, y })} />
        </div>

        <div className="flex items-center gap-2">
          <button onClick={save} disabled={saving || !marker || !cameraId} className="btn-outline">{saving ? 'Saving…' : 'Save marker'}</button>
          <button onClick={activate} disabled={activating || saving || !(station || (marker && cameraId))} className="btn-primary">
            {activating ? 'Activating…' : 'Save & Activate'}
          </button>
        </div>
      </div>
    </div>
  )
}
