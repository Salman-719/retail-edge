import React, { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Stage, Layer, Image as KonvaImage, Line, Circle, Text } from 'react-konva'
import {
  activateDraft, computeHomography, createCamera, createDraft, createObstacle, createZone,
  deleteCameraConfig, deleteCamera, deleteDraft, deleteObstacle, deleteZone,
  getActiveVersion, getDraft, getDraftCameraConfigs, getDraftFloorPlan, getDraftObstacles,
  getDraftZones, getCalibrations, getSyncEvent, listSections, placeCameraConfig,
  setFloorPlanScale, updateCameraConfig, uploadCameraFrame, uploadFloorPlan, verifyCalibration,
} from '../api'

// ─── Constants ────────────────────────────────────────────────────────────────

const STEPS = [
  { n: 1, label: 'Upload Floor Plan' },
  { n: 2, label: 'Set Scale' },
  { n: 3, label: 'Place Cameras' },
  { n: 4, label: 'Camera Frames' },
  { n: 5, label: 'Correspondences' },
  { n: 6, label: 'Compute Homography' },
  { n: 7, label: 'Verify Calibration' },
  { n: 8, label: 'Draw Zones' },
  { n: 9, label: 'Activate' },
]

const ZONE_COLORS = {
  entrance: '#3b82f6', checkout: '#f59e0b', aisle: '#10b981',
  staff_only: '#ef4444', general: '#8b5cf6',
}

const ACTIVATION_COUNTDOWN = 30

// ─── Hooks ────────────────────────────────────────────────────────────────────

function useKonvaImage(url) {
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

function fitScale(imgW, imgH, canvasW, canvasH) {
  if (!imgW || !imgH) return 1
  return Math.min(canvasW / imgW, canvasH / imgH)
}

// ─── Floor Plan Canvas ────────────────────────────────────────────────────────

function FloorPlanStage({
  floorPlan,
  zones = [],
  obstacles = [],
  cameraConfigs = [],
  scalePoints = [],
  overlayPoints = [],
  overlayMode = null,
  pendingMarker = null,
  correspondencePoints = [],
  activeConfigId = null,
  onCanvasClick,
  width = 700,
  height = 480,
}) {
  const bgImage = useKonvaImage(floorPlan?.display_url)
  const scale = fitScale(floorPlan?.width_px, floorPlan?.height_px, width, height)
  const stageH = Math.round((floorPlan?.height_px || height) * scale)

  const handleClick = (e) => {
    if (!onCanvasClick) return
    const pos = e.target.getStage().getPointerPosition()
    onCanvasClick(pos.x / scale, pos.y / scale)
  }

  return (
    <Stage
      width={width}
      height={stageH}
      onClick={handleClick}
      style={{ cursor: onCanvasClick ? 'crosshair' : 'default', background: '#f3f4f6', borderRadius: 8 }}
    >
      <Layer>
        {bgImage && (
          <KonvaImage
            image={bgImage}
            width={(floorPlan?.width_px || width) * scale}
            height={(floorPlan?.height_px || height) * scale}
          />
        )}

        {obstacles.map(obs => (
          <Line key={obs.id}
            points={obs.points.flatMap(([x, y]) => [x * scale, y * scale])}
            closed fill="#6b728022" stroke="#6b7280" strokeWidth={2} dash={[5, 3]} />
        ))}

        {zones.map(zone => (
          <React.Fragment key={zone.id}>
            <Line
              points={zone.points.flatMap(([x, y]) => [x * scale, y * scale])}
              closed
              fill={(ZONE_COLORS[zone.type] || '#888') + '33'}
              stroke={ZONE_COLORS[zone.type] || '#888'}
              strokeWidth={2}
            />
            {zone.points[0] && (
              <Text
                x={zone.points[0][0] * scale + 4}
                y={zone.points[0][1] * scale + 4}
                text={zone.name}
                fontSize={11}
                fill={ZONE_COLORS[zone.type] || '#888'}
              />
            )}
          </React.Fragment>
        ))}

        {cameraConfigs.map(cc => (
          <React.Fragment key={cc.id}>
            <Circle
              x={cc.position_x * scale} y={cc.position_y * scale} radius={9}
              fill={
                cc.id === activeConfigId ? '#2563eb' :
                cc.status === 'verified' ? '#10b981' :
                cc.status === 'calibrated' ? '#f59e0b' : '#6b7280'
              }
              stroke="#fff" strokeWidth={2}
            />
            <Text
              x={cc.position_x * scale + 13} y={cc.position_y * scale - 6}
              text={cc.physical_camera_name} fontSize={11} fill="#111"
            />
          </React.Fragment>
        ))}

        {/* Scale overlay: origin (orange), ref A (blue), ref line A→B only */}
        {scalePoints.length > 0 && (
          <>
            <Circle x={scalePoints[0][0] * scale} y={scalePoints[0][1] * scale}
              radius={6} fill="#f97316" stroke="#fff" strokeWidth={2} />
            <Text x={scalePoints[0][0] * scale + 8} y={scalePoints[0][1] * scale - 8}
              text="O" fontSize={11} fill="#f97316" />
          </>
        )}
        {scalePoints.length > 1 && (
          <>
            <Circle x={scalePoints[1][0] * scale} y={scalePoints[1][1] * scale}
              radius={6} fill="#2563eb" stroke="#fff" strokeWidth={2} />
            <Text x={scalePoints[1][0] * scale + 8} y={scalePoints[1][1] * scale - 8}
              text="A" fontSize={11} fill="#2563eb" />
          </>
        )}
        {scalePoints.length > 2 && (
          <>
            <Line
              points={[
                scalePoints[1][0] * scale, scalePoints[1][1] * scale,
                scalePoints[2][0] * scale, scalePoints[2][1] * scale,
              ]}
              stroke="#2563eb" strokeWidth={2} dash={[5, 3]}
            />
            <Circle x={scalePoints[2][0] * scale} y={scalePoints[2][1] * scale}
              radius={6} fill="#2563eb" stroke="#fff" strokeWidth={2} />
            <Text x={scalePoints[2][0] * scale + 8} y={scalePoints[2][1] * scale - 8}
              text="B" fontSize={11} fill="#2563eb" />
          </>
        )}

        {/* Zone/obstacle in-progress drawing */}
        {overlayPoints.length > 0 && (
          <>
            <Line
              points={overlayPoints.flatMap(([x, y]) => [x * scale, y * scale])}
              stroke={overlayMode === 'obstacle' ? '#6b7280' : '#2563eb'}
              strokeWidth={2}
              dash={overlayMode === 'obstacle' ? [5, 3] : undefined}
            />
            {overlayPoints.map(([x, y], i) => (
              <Circle key={i} x={x * scale} y={y * scale} radius={4}
                fill={overlayMode === 'obstacle' ? '#6b7280' : '#2563eb'} />
            ))}
          </>
        )}

        {/* Pending camera placement ghost marker */}
        {pendingMarker && (
          <Circle
            x={pendingMarker.x * scale} y={pendingMarker.y * scale}
            radius={9} fill="#94a3b8" stroke="#fff" strokeWidth={2}
          />
        )}

        {/* Correspondence / verify world points */}
        {correspondencePoints.map((pt, i) => (
          <React.Fragment key={i}>
            <Circle x={pt[0] * scale} y={pt[1] * scale} radius={6} fill="#f97316" stroke="#fff" strokeWidth={2} />
            <Text x={pt[0] * scale + 8} y={pt[1] * scale - 8} text={`${i + 1}`} fontSize={11} fill="#f97316" />
          </React.Fragment>
        ))}
      </Layer>
    </Stage>
  )
}

// ─── Camera Frame Viewer ──────────────────────────────────────────────────────

function FrameStage({ frameUrl, width = 360, height = 260, points = [], onCanvasClick }) {
  const image = useKonvaImage(frameUrl)
  const [imgSize, setImgSize] = useState({ w: width, h: height })

  useEffect(() => {
    if (image) setImgSize({ w: image.width, h: image.height })
  }, [image])

  const scale = fitScale(imgSize.w, imgSize.h, width, height)

  const handleClick = (e) => {
    if (!onCanvasClick) return
    const pos = e.target.getStage().getPointerPosition()
    onCanvasClick(pos.x / scale, pos.y / scale)
  }

  return (
    <Stage
      width={width}
      height={Math.round(imgSize.h * scale)}
      onClick={handleClick}
      style={{ cursor: onCanvasClick ? 'crosshair' : 'default', background: '#111', borderRadius: 8 }}
    >
      <Layer>
        {image && <KonvaImage image={image} width={imgSize.w * scale} height={imgSize.h * scale} />}
        {points.map((pt, i) => (
          <React.Fragment key={i}>
            <Circle x={pt[0] * scale} y={pt[1] * scale} radius={6} fill="#22c55e" stroke="#fff" strokeWidth={2} />
            <Text x={pt[0] * scale + 8} y={pt[1] * scale - 8} text={`${i + 1}`} fontSize={11} fill="#22c55e" />
          </React.Fragment>
        ))}
      </Layer>
    </Stage>
  )
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function StoreConfigEdit() {
  const { slug } = useParams()
  const navigate = useNavigate()

  const [step, setStep] = useState(1)
  const [mode, setMode] = useState(null) // 'onboarding' | 'editing'
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)

  // Core data
  const [draft, setDraft] = useState(null)
  const [sections, setSections] = useState([])
  const [selectedSection, setSelectedSection] = useState(null)
  const [floorPlan, setFloorPlan] = useState(null)
  const [cameraConfigs, setCameraConfigs] = useState([])
  const [zones, setZones] = useState([])
  const [obstacles, setObstacles] = useState([])

  // Step 2 — scale calibration
  // scalePoints = [origin, refA, refB]; not cleared on save so markers stay visible
  const [scalePoints, setScalePoints] = useState([])
  const [realDistance, setRealDistance] = useState('')

  // Step 3 — camera placement
  const [pendingCameraPlacement, setPendingCameraPlacement] = useState(null)
  const [newCameraName, setNewCameraName] = useState('')
  const [newCameraHeight, setNewCameraHeight] = useState('')

  // Steps 4-7 — selected camera; derived from cameraConfigs to avoid stale state
  const [selectedConfigId, setSelectedConfigId] = useState(null)
  const selectedConfig = cameraConfigs.find(cc => cc.id === selectedConfigId) ?? null

  // Step 3 — inline camera config editing
  const [editingConfigId, setEditingConfigId] = useState(null)
  const [editCameraForm, setEditCameraForm] = useState({ height_meters: '', fov_deg: '' })

  // Steps 5-6 — per-camera correspondences and computed calibration results
  const [correspondencesMap, setCorrespondencesMap] = useState({})
  const [calibResultsMap, setCalibResultsMap] = useState({})
  const [pendingPixelPt, setPendingPixelPt] = useState(null)

  // Step 7 — per-camera verification preview
  const [verifyPreviewMap, setVerifyPreviewMap] = useState({})

  // Step 8 — polygon drawing
  const [step8Skipped, setStep8Skipped] = useState(false)
  const [drawMode, setDrawMode] = useState('zone')
  const [inProgressPoints, setInProgressPoints] = useState([])
  // After polygon is closed: holds { points, mode } until user names it
  const [pendingPolygon, setPendingPolygon] = useState(null)
  const [pendingName, setPendingName] = useState('')
  const [pendingZoneType, setPendingZoneType] = useState('general')

  // Step 9 — activation
  const [activationLabel, setActivationLabel] = useState('')
  const [syncEvent, setSyncEvent] = useState(null)
  const pollRef = useRef(null)

  // ─── Step completion ─────────────────────────────────────────────────────

  function isStepComplete(n) {
    switch (n) {
      case 1: return !!floorPlan?.image_uploaded
      case 2: return !!floorPlan?.scale_defined
      case 3: return cameraConfigs.length > 0
      case 4: return cameraConfigs.length > 0 &&
        cameraConfigs.every(cc => cc.status !== 'pending')
      case 5: return cameraConfigs.length > 0 &&
        cameraConfigs.every(cc =>
          (correspondencesMap[cc.id]?.length >= 8) ||
          ['calibrated', 'verified'].includes(cc.status)
        )
      case 6: return cameraConfigs.length > 0 &&
        cameraConfigs.every(cc => ['calibrated', 'verified'].includes(cc.status))
      case 7: return cameraConfigs.length > 0 &&
        cameraConfigs.every(cc => cc.status === 'verified')
      case 8: return zones.length > 0 || obstacles.length > 0 || step8Skipped
      default: return false
    }
  }

  function canNavigateToStep(n) {
    if (mode === 'editing') return true
    if (n === 1) return true
    for (let i = 1; i < n; i++) {
      if (!isStepComplete(i)) return false
    }
    return true
  }

  // ─── Bootstrap ───────────────────────────────────────────────────────────

  useEffect(() => {
    bootstrap()
    return () => clearInterval(pollRef.current)
  }, [slug])

  async function bootstrap() {
    setLoading(true)
    try {
      const [sects, activeVersion] = await Promise.all([
        listSections(slug).catch(() => []),
        getActiveVersion(slug).catch(() => null),
      ])
      setSections(sects)
      const defaultSection = sects.find(s => s.is_default) || sects[0]
      setSelectedSection(defaultSection)

      const isEditing = !!activeVersion
      setMode(isEditing ? 'editing' : 'onboarding')

      // Fetch existing draft; only create one if none exists (404).
      // When editing (active version exists), clone the active version into the new draft.
      let d = null
      try {
        d = await getDraft(slug)
      } catch (err) {
        if (err?.response?.status !== 404) throw err
      }
      if (!d) {
        try {
          d = await createDraft(slug, null, isEditing)
        } catch (err) {
          if (err?.response?.status === 409) {
            d = await getDraft(slug)
          } else {
            throw err
          }
        }
      }
      setDraft(d)

      if (defaultSection) {
        await loadSectionData(defaultSection.id, slug)
      }
    } catch (err) {
      setError(err?.response?.data?.error || err.message)
    } finally {
      setLoading(false)
    }
  }

  async function loadSectionData(sectionId, storeSlug) {
    const s = storeSlug || slug
    const [fp, zs, obs, ccs] = await Promise.all([
      getDraftFloorPlan(s, sectionId).catch(() => null),
      getDraftZones(s, sectionId).catch(() => []),
      getDraftObstacles(s, sectionId).catch(() => []),
      getDraftCameraConfigs(s, sectionId).catch(() => []),
    ])

    setFloorPlan(fp)
    setZones(zs)
    setObstacles(obs)
    setCameraConfigs(ccs)

    // Reconstruct origin marker from stored origin — ref points not stored, so only origin shown
    if (fp?.origin_x != null && fp?.origin_y != null) {
      setScalePoints([[fp.origin_x, fp.origin_y]])
    } else {
      setScalePoints([])
    }

    // Initialise per-camera correspondence map
    const corrMap = {}
    for (const cc of ccs) corrMap[cc.id] = []
    setCorrespondencesMap(corrMap)

    // Load stored calibration data for cameras that were previously calibrated
    const calibMap = {}
    for (const cc of ccs.filter(c => ['calibrated', 'verified'].includes(c.status))) {
      const calibs = await getCalibrations(s, cc.id).catch(() => [])
      const current = calibs.find(c => c.is_current)
      if (current) calibMap[cc.id] = current
    }
    setCalibResultsMap(calibMap)

    setSelectedConfigId(ccs[0]?.id ?? null)
    setPendingPixelPt(null)
    setInProgressPoints([])
    setPendingPolygon(null)
    setVerifyPreviewMap({})
    setPendingCameraPlacement(null)
  }

  async function switchSection(section) {
    setSelectedSection(section)
    setFloorPlan(null)
    setZones([])
    setObstacles([])
    setCameraConfigs([])
    setSelectedConfigId(null)
    setScalePoints([])
    setRealDistance('')
    setCorrespondencesMap({})
    setCalibResultsMap({})
    setInProgressPoints([])
    setPendingPolygon(null)
    setPendingCameraPlacement(null)
    setVerifyPreviewMap({})
    if (draft) await loadSectionData(section.id, slug)
  }

  // ─── Step 1: Floor plan upload ────────────────────────────────────────────

  async function handleFloorPlanUpload(e) {
    const file = e.target.files?.[0]
    if (!file || !selectedSection) return
    setSaving(true)
    try {
      const fp = await uploadFloorPlan(slug, selectedSection.id, file)
      setFloorPlan(fp)
      // Backend cascade-wipes zones/obstacles/configs on re-upload; mirror in state
      setZones([])
      setObstacles([])
      setCameraConfigs([])
      setSelectedConfigId(null)
      setScalePoints([])
      setRealDistance('')
      setCorrespondencesMap({})
      setCalibResultsMap({})
    } catch (err) {
      setError(err?.response?.data?.error || err.message)
    } finally {
      setSaving(false)
      e.target.value = ''
    }
  }

  // ─── Step 2: Scale ────────────────────────────────────────────────────────

  function handleScaleClick(x, y) {
    if (scalePoints.length >= 3) return
    setScalePoints(prev => [...prev, [x, y]])
  }

  // Removing point at index i also removes all points after it and invalidates the saved scale
  function removeScalePoint(i) {
    setScalePoints(prev => prev.slice(0, i))
    setFloorPlan(prev => prev ? { ...prev, scale_defined: false } : null)
  }

  async function handleSetScale() {
    if (scalePoints.length < 3 || !realDistance || !selectedSection) return
    setSaving(true)
    try {
      const updated = await setFloorPlanScale(slug, selectedSection.id, {
        origin_x: scalePoints[0][0],
        origin_y: scalePoints[0][1],
        ref_point_1: scalePoints[1],
        ref_point_2: scalePoints[2],
        real_distance_meters: parseFloat(realDistance),
      })
      setFloorPlan(updated)
      // Keep scalePoints so the markers remain visible on the canvas
    } catch (err) {
      setError(err?.response?.data?.error || err.message)
    } finally {
      setSaving(false)
    }
  }

  // ─── Step 3: Camera placement ─────────────────────────────────────────────

  function handleMapClickForCamera(x, y) {
    if (pendingCameraPlacement) return
    setPendingCameraPlacement({ x, y })
    setNewCameraName('')
    setNewCameraHeight('')
  }

  async function handlePlaceCameraSubmit(e) {
    e.preventDefault()
    if (!newCameraName.trim() || !selectedSection) return
    setSaving(true)
    try {
      const cam = await createCamera(slug, { name: newCameraName.trim() })
      const cc = await placeCameraConfig(slug, selectedSection.id, {
        physical_camera_id: cam.id,
        position_x: pendingCameraPlacement.x,
        position_y: pendingCameraPlacement.y,
        height_meters: newCameraHeight ? parseFloat(newCameraHeight) : null,
      })
      setCameraConfigs(prev => [...prev, cc])
      setCorrespondencesMap(prev => ({ ...prev, [cc.id]: [] }))
      setSelectedConfigId(cc.id)
      setPendingCameraPlacement(null)
    } catch (err) {
      setError(err?.response?.data?.error || err.message)
    } finally {
      setSaving(false)
    }
  }

  async function handleDeleteCamera(cc) {
    try {
      await deleteCameraConfig(slug, cc.id)
      await deleteCamera(slug, cc.physical_camera_id)
      const remaining = cameraConfigs.filter(c => c.id !== cc.id)
      setCameraConfigs(remaining)
      if (selectedConfigId === cc.id) setSelectedConfigId(remaining[0]?.id ?? null)
      setCorrespondencesMap(prev => { const n = { ...prev }; delete n[cc.id]; return n })
      setCalibResultsMap(prev => { const n = { ...prev }; delete n[cc.id]; return n })
    } catch (err) {
      setError(err?.response?.data?.error || err.message)
    }
  }

  async function handleUpdateCameraConfig(e) {
    e.preventDefault()
    if (!editingConfigId) return
    setSaving(true)
    try {
      const body = {}
      if (editCameraForm.height_meters !== '') body.height_meters = parseFloat(editCameraForm.height_meters)
      if (editCameraForm.fov_deg !== '') body.fov_deg = parseFloat(editCameraForm.fov_deg)
      const updated = await updateCameraConfig(slug, editingConfigId, body)
      setCameraConfigs(prev => prev.map(c => c.id === editingConfigId ? { ...c, ...updated } : c))
      setEditingConfigId(null)
    } catch (err) {
      setError(err?.response?.data?.error || err.message)
    } finally {
      setSaving(false)
    }
  }

  // ─── Steps 5-6: Correspondences and homography ───────────────────────────

  function handleFrameClickForCorrespondence(x, y) {
    setPendingPixelPt([x, y])
  }

  function handleMapClickForCorrespondence(x, y) {
    if (!pendingPixelPt || !selectedConfigId) return
    setCorrespondencesMap(prev => ({
      ...prev,
      [selectedConfigId]: [...(prev[selectedConfigId] || []), { pixel: pendingPixelPt, world: [x, y] }],
    }))
    setPendingPixelPt(null)
  }

  function removeCorrespondence(configId, idx) {
    setCorrespondencesMap(prev => ({
      ...prev,
      [configId]: (prev[configId] || []).filter((_, i) => i !== idx),
    }))
  }

  async function handleComputeHomographyFor(configId) {
    const corr = correspondencesMap[configId] || []
    if (corr.length < 8) return
    setSaving(true)
    try {
      const result = await computeHomography(slug, configId, corr)
      setCalibResultsMap(prev => ({ ...prev, [configId]: result }))
      setCameraConfigs(prev => prev.map(c =>
        c.id === configId ? { ...c, status: 'calibrated' } : c
      ))
    } catch (err) {
      setError(err?.response?.data?.error || err.message)
    } finally {
      setSaving(false)
    }
  }

  // ─── Step 7: Verify ───────────────────────────────────────────────────────

  function projectPixelToWorld(configId, px, py) {
    const H = calibResultsMap[configId]?.homography_matrix
    if (!H) return null
    const X = H[0][0] * px + H[0][1] * py + H[0][2]
    const Y = H[1][0] * px + H[1][1] * py + H[1][2]
    const W = H[2][0] * px + H[2][1] * py + H[2][2]
    return [X / W, Y / W]
  }

  function handleFrameClickForVerify(x, y) {
    if (!selectedConfigId) return
    const world = projectPixelToWorld(selectedConfigId, x, y)
    setVerifyPreviewMap(prev => ({ ...prev, [selectedConfigId]: { pixel: [x, y], world } }))
  }

  async function handleVerifyCalibration() {
    if (!selectedConfigId) return
    setSaving(true)
    try {
      await verifyCalibration(slug, selectedConfigId)
      setCameraConfigs(prev => prev.map(c =>
        c.id === selectedConfigId ? { ...c, status: 'verified' } : c
      ))
    } catch (err) {
      setError(err?.response?.data?.error || err.message)
    } finally {
      setSaving(false)
    }
  }

  // ─── Step 8: Drawing zones and obstacles ─────────────────────────────────

  function handleMapClickForDrawing(x, y) {
    if (pendingPolygon) return
    if (inProgressPoints.length >= 3) {
      const [fx, fy] = inProgressPoints[0]
      const s = fitScale(floorPlan?.width_px, floorPlan?.height_px, 700, 480)
      if (Math.hypot(x - fx, y - fy) < 15 / s) {
        // Polygon closed — ask for name before saving
        setPendingPolygon({ points: [...inProgressPoints], mode: drawMode })
        setPendingName('')
        setPendingZoneType('general')
        setInProgressPoints([])
        return
      }
    }
    setInProgressPoints(prev => [...prev, [x, y]])
  }

  async function handlePendingPolygonSubmit(e) {
    e.preventDefault()
    if (!pendingPolygon || !selectedSection) return
    if (pendingPolygon.mode === 'zone' && !pendingName.trim()) {
      setError('Zone name is required')
      return
    }
    setSaving(true)
    try {
      if (pendingPolygon.mode === 'zone') {
        const z = await createZone(slug, selectedSection.id, {
          name: pendingName.trim(),
          type: pendingZoneType,
          points: pendingPolygon.points,
        })
        setZones(prev => [...prev, z])
      } else {
        const obs = await createObstacle(slug, selectedSection.id, {
          name: pendingName.trim() || `Obstacle ${obstacles.length + 1}`,
          points: pendingPolygon.points,
        })
        setObstacles(prev => [...prev, obs])
      }
      setPendingPolygon(null)
      setPendingName('')
    } catch (err) {
      setError(err?.response?.data?.error || err.message)
    } finally {
      setSaving(false)
    }
  }

  async function handleDeleteZone(zoneId) {
    try {
      await deleteZone(slug, selectedSection.id, zoneId)
      setZones(prev => prev.filter(z => z.id !== zoneId))
    } catch (err) {
      setError(err?.response?.data?.error || err.message)
    }
  }

  async function handleDeleteObstacle(obsId) {
    try {
      await deleteObstacle(slug, selectedSection.id, obsId)
      setObstacles(prev => prev.filter(o => o.id !== obsId))
    } catch (err) {
      setError(err?.response?.data?.error || err.message)
    }
  }

  // ─── Step 9: Activation ───────────────────────────────────────────────────

  async function handleActivate() {
    setSaving(true)
    try {
      const event = await activateDraft(slug, {
        countdown_sec: ACTIVATION_COUNTDOWN,
        label: activationLabel || null,
      })
      setSyncEvent(event)
      pollRef.current = setInterval(async () => {
        const updated = await getSyncEvent(slug, event.id)
        setSyncEvent(updated)
        if (updated.status === 'executed') {
          clearInterval(pollRef.current)
          navigate(`/store/${slug}/config`)
        } else if (updated.status === 'failed') {
          clearInterval(pollRef.current)
          setError('Activation failed: ' + (updated.error || 'unknown error'))
        }
      }, 2000)
    } catch (err) {
      setError(err?.response?.data?.error || err.message)
    } finally {
      setSaving(false)
    }
  }

  // ─── Render ───────────────────────────────────────────────────────────────

  if (loading) {
    return <div className="flex items-center justify-center h-64 text-gray-400">Loading wizard…</div>
  }

  const activeCorrespondences = selectedConfigId ? (correspondencesMap[selectedConfigId] || []) : []
  const verifyPreview = selectedConfigId ? (verifyPreviewMap[selectedConfigId] ?? null) : null

  return (
    <div className="flex h-full">

      {/* ── Sidebar ─────────────────────────────────────────────────────── */}
      <aside className="w-52 flex-shrink-0 border-r border-gray-200 bg-gray-50 p-4 flex flex-col">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-4">
          {mode === 'editing' ? 'Edit Configuration' : 'Setup Wizard'}
        </h2>
        <nav className="space-y-1">
          {STEPS.map(s => {
            const complete = isStepComplete(s.n)
            const current = s.n === step
            const navigable = canNavigateToStep(s.n)
            return (
              <button
                key={s.n}
                onClick={() => navigable && setStep(s.n)}
                disabled={!navigable}
                className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors text-left ${
                  current
                    ? 'bg-blue-600 text-white'
                    : navigable && complete
                    ? 'text-green-700 bg-green-50 hover:bg-green-100'
                    : navigable
                    ? 'text-gray-600 hover:bg-gray-100'
                    : 'text-gray-300 cursor-not-allowed'
                }`}
              >
                <span className={`w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 ${
                  current ? 'bg-white text-blue-600' :
                  complete ? 'bg-green-500 text-white' :
                  'bg-gray-200 text-gray-500'
                }`}>
                  {!current && complete ? '✓' : s.n}
                </span>
                <span className="truncate">{s.label}</span>
              </button>
            )
          })}
        </nav>

        {sections.length > 1 && (
          <div className="mt-6">
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-2">Section</label>
            <select
              value={selectedSection?.id || ''}
              onChange={e => {
                const sec = sections.find(s => s.id === e.target.value)
                if (sec) switchSection(sec)
              }}
              className="w-full text-sm border border-gray-200 rounded px-2 py-1.5 bg-white"
            >
              {sections.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>
        )}

        <div className="mt-auto pt-6 space-y-2">
          {mode === 'editing' && (
            <button
              onClick={() => navigate(`/store/${slug}/config`)}
              className="w-full px-3 py-1.5 bg-gray-200 text-gray-700 rounded text-xs font-medium hover:bg-gray-300 text-left"
            >
              Save &amp; Exit
            </button>
          )}
          <button
            onClick={async () => {
              if (!window.confirm('Discard this draft? All changes will be lost.')) return
              try { await deleteDraft(slug) } catch {}
              navigate(`/store/${slug}/config`)
            }}
            className="text-xs text-red-500 hover:text-red-700 text-left px-1"
          >
            Discard draft
          </button>
        </div>
      </aside>

      {/* ── Main content ─────────────────────────────────────────────────── */}
      <main className="flex-1 overflow-auto p-6">
        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700 flex items-center justify-between">
            <span>{error}</span>
            <button onClick={() => setError(null)} className="ml-4 text-red-400 hover:text-red-600 flex-shrink-0">✕</button>
          </div>
        )}

        {/* ─ Step 1 ──────────────────────────────────────────────────────── */}
        {step === 1 && (
          <div className="space-y-6 max-w-2xl">
            <div>
              <h2 className="text-xl font-semibold mb-1">Upload Floor Plan</h2>
              <p className="text-sm text-gray-500">Upload a top-down image of {selectedSection?.name || 'this section'}.</p>
            </div>
            <label className="flex flex-col items-center justify-center w-full h-48 border-2 border-dashed border-gray-300 rounded-xl cursor-pointer bg-gray-50 hover:bg-gray-100 transition-colors">
              <svg className="w-10 h-10 text-gray-400 mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
              </svg>
              <span className="text-sm text-gray-500">
                {saving ? 'Uploading…' : floorPlan?.image_uploaded ? 'Click to replace image' : 'Click to upload PNG, JPG or WebP'}
              </span>
              <input type="file" accept="image/png,image/jpeg,image/webp" className="hidden"
                onChange={handleFloorPlanUpload} disabled={saving} />
            </label>
            {floorPlan?.image_uploaded && (
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-sm text-green-700 font-medium">
                  <span className="w-5 h-5 bg-green-100 rounded-full flex items-center justify-center text-green-600">✓</span>
                  Floor plan uploaded · {floorPlan.width_px} × {floorPlan.height_px} px
                </div>
                <FloorPlanStage floorPlan={floorPlan} />
              </div>
            )}
          </div>
        )}

        {/* ─ Step 2 ──────────────────────────────────────────────────────── */}
        {step === 2 && (
          <div className="space-y-4 max-w-3xl">
            <div>
              <h2 className="text-xl font-semibold mb-1">Set Scale</h2>
              <p className="text-sm text-gray-500">
                Click to place: (1) Origin, (2) Reference point A, (3) Reference point B.
                Then enter the real-world distance A→B in metres.
              </p>
            </div>

            {floorPlan?.scale_defined && (
              <div className="flex items-center gap-2 text-sm text-green-700 bg-green-50 px-3 py-2 rounded">
                <span>✓</span>
                <span>Scale set: {floorPlan.pixels_per_meter?.toFixed(2)} px/m</span>
              </div>
            )}

            {/* Per-point chips with individual remove buttons */}
            <div className="flex gap-2 flex-wrap">
              {[
                { label: 'Origin (O)', placed: 'text-orange-600 bg-orange-50 border-orange-200' },
                { label: 'Ref A', placed: 'text-blue-600 bg-blue-50 border-blue-200' },
                { label: 'Ref B', placed: 'text-blue-600 bg-blue-50 border-blue-200' },
              ].map((item, i) => (
                <div key={i} className={`flex items-center gap-1.5 px-2 py-1 rounded border text-xs ${
                  scalePoints.length > i ? item.placed : 'bg-gray-50 border-gray-200 text-gray-400'
                }`}>
                  <span className="font-bold">{i + 1}.</span>
                  <span>{item.label}</span>
                  {scalePoints.length > i && (
                    <>
                      <span className="text-gray-400">
                        ({scalePoints[i][0].toFixed(0)}, {scalePoints[i][1].toFixed(0)})
                      </span>
                      <button
                        onClick={() => removeScalePoint(i)}
                        title="Remove this point and all after it"
                        className="ml-1 text-gray-400 hover:text-red-500 font-bold leading-none"
                      >✕</button>
                    </>
                  )}
                </div>
              ))}
            </div>

            <FloorPlanStage
              floorPlan={floorPlan}
              scalePoints={scalePoints}
              onCanvasClick={scalePoints.length < 3 ? handleScaleClick : null}
            />

            {scalePoints.length === 3 && (
              <div className="flex items-center gap-3 flex-wrap">
                <label className="text-sm text-gray-700">Distance A→B (metres):</label>
                <input
                  type="number" step="0.01" min="0.01"
                  value={realDistance}
                  onChange={e => setRealDistance(e.target.value)}
                  className="w-28 border border-gray-300 rounded px-2 py-1.5 text-sm"
                  placeholder="e.g. 2.5"
                />
                <button
                  onClick={handleSetScale}
                  disabled={!realDistance || saving}
                  className="px-4 py-1.5 bg-blue-600 text-white rounded text-sm font-medium disabled:opacity-50"
                >
                  {saving ? 'Saving…' : 'Set Scale'}
                </button>
              </div>
            )}
          </div>
        )}

        {/* ─ Step 3 ──────────────────────────────────────────────────────── */}
        {step === 3 && (
          <div className="space-y-4 max-w-4xl">
            <div>
              <h2 className="text-xl font-semibold mb-1">Place Cameras</h2>
              <p className="text-sm text-gray-500">
                Click anywhere on the floor plan to place a camera. Fill in the name and height when prompted.
              </p>
            </div>

            <FloorPlanStage
              floorPlan={floorPlan}
              cameraConfigs={cameraConfigs}
              pendingMarker={pendingCameraPlacement}
              onCanvasClick={!pendingCameraPlacement ? handleMapClickForCamera : null}
            />

            {pendingCameraPlacement && (
              <form
                onSubmit={handlePlaceCameraSubmit}
                className="bg-white border border-blue-200 rounded-lg p-4 space-y-3 max-w-sm shadow-sm"
              >
                <h4 className="text-sm font-medium text-gray-800">New Camera</h4>
                <input
                  autoFocus
                  placeholder="Camera name (e.g. CAM-01)"
                  value={newCameraName}
                  onChange={e => setNewCameraName(e.target.value)}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm"
                />
                <input
                  type="number"
                  placeholder="Mounting height in metres (e.g. 3.5)"
                  value={newCameraHeight}
                  onChange={e => setNewCameraHeight(e.target.value)}
                  step="0.1" min="0.1"
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm"
                />
                <div className="flex gap-2">
                  <button
                    type="submit"
                    disabled={!newCameraName.trim() || saving}
                    className="px-4 py-1.5 bg-blue-600 text-white rounded text-sm font-medium disabled:opacity-50"
                  >
                    {saving ? 'Placing…' : 'Place Camera'}
                  </button>
                  <button
                    type="button"
                    onClick={() => setPendingCameraPlacement(null)}
                    className="px-4 py-1.5 text-gray-600 text-sm hover:text-gray-900"
                  >
                    Cancel
                  </button>
                </div>
              </form>
            )}

            {cameraConfigs.length > 0 && (
              <div className="space-y-1 max-w-lg">
                <p className="text-xs font-medium text-gray-500 uppercase mb-2">Placed Cameras</p>
                {cameraConfigs.map(cc => (
                  <div key={cc.id} className="bg-gray-50 border border-gray-100 rounded text-sm">
                    <div className="flex items-center justify-between px-3 py-2">
                      <span className="font-medium">{cc.physical_camera_name}</span>
                      <span className="text-xs text-gray-400 mx-2">
                        ({Math.round(cc.position_x)}, {Math.round(cc.position_y)})
                        {cc.height_meters != null ? ` · ${cc.height_meters}m` : ''}
                        {cc.fov_deg != null ? ` · ${cc.fov_deg}°` : ''}
                      </span>
                      <div className="flex gap-2 flex-shrink-0">
                        <button
                          onClick={() => {
                            if (editingConfigId === cc.id) { setEditingConfigId(null); return }
                            setEditingConfigId(cc.id)
                            setEditCameraForm({
                              height_meters: cc.height_meters ?? '',
                              fov_deg: cc.fov_deg ?? '',
                            })
                          }}
                          className="text-xs text-blue-500 hover:text-blue-700"
                        >
                          {editingConfigId === cc.id ? 'Cancel' : 'Edit'}
                        </button>
                        <button
                          onClick={() => handleDeleteCamera(cc)}
                          className="text-xs text-red-400 hover:text-red-600"
                        >
                          Delete
                        </button>
                      </div>
                    </div>
                    {editingConfigId === cc.id && (
                      <form
                        onSubmit={handleUpdateCameraConfig}
                        className="border-t border-gray-200 px-3 py-2 flex items-center gap-3 flex-wrap"
                      >
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
                        <div className="flex items-center gap-1.5">
                          <label className="text-xs text-gray-500">FOV (°):</label>
                          <input
                            type="number" step="1" min="1" max="360"
                            value={editCameraForm.fov_deg}
                            onChange={e => setEditCameraForm(f => ({ ...f, fov_deg: e.target.value }))}
                            className="w-20 border border-gray-300 rounded px-2 py-1 text-xs"
                            placeholder="e.g. 90"
                          />
                        </div>
                        <button
                          type="submit"
                          disabled={saving}
                          className="px-3 py-1 bg-blue-600 text-white rounded text-xs font-medium disabled:opacity-50"
                        >
                          {saving ? 'Saving…' : 'Save'}
                        </button>
                      </form>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ─ Step 4 ──────────────────────────────────────────────────────── */}
        {step === 4 && (
          <div className="space-y-4 max-w-2xl">
            <div>
              <h2 className="text-xl font-semibold mb-1">Camera Frames</h2>
              <p className="text-sm text-gray-500">Upload a reference frame for each camera.</p>
            </div>

            {cameraConfigs.length === 0 && (
              <div className="text-sm text-gray-400 p-4 bg-gray-50 rounded">No cameras placed — go back to Step 3.</div>
            )}

            {cameraConfigs.map(cc => (
              <div key={cc.id} className="border border-gray-200 rounded-lg p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <span className="font-medium text-sm">{cc.physical_camera_name}</span>
                    {cc.height_meters != null && (
                      <span className="ml-2 text-xs text-gray-400">Height: {cc.height_meters}m</span>
                    )}
                  </div>
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                    cc.status === 'verified' ? 'bg-green-100 text-green-700' :
                    cc.status === 'calibrated' ? 'bg-yellow-100 text-yellow-700' :
                    cc.status === 'frame_uploaded' ? 'bg-blue-100 text-blue-700' :
                    'bg-gray-100 text-gray-500'
                  }`}>{cc.status}</span>
                </div>

                {cc.frame_url && (
                  <img src={cc.frame_url} alt="Frame" className="h-28 object-cover rounded border border-gray-200" />
                )}

                <label className="inline-flex items-center gap-2 cursor-pointer">
                  <span className="px-3 py-1.5 bg-gray-100 hover:bg-gray-200 rounded border border-gray-300 text-sm transition-colors">
                    {cc.status === 'pending' ? 'Upload Frame' : 'Replace Frame'}
                  </span>
                  <input
                    type="file"
                    accept="image/*"
                    className="hidden"
                    disabled={saving}
                    onChange={async (e) => {
                      const file = e.target.files?.[0]
                      if (!file) return
                      setSaving(true)
                      try {
                        const res = await uploadCameraFrame(slug, cc.id, file)
                        setCameraConfigs(prev => prev.map(c =>
                          c.id === cc.id
                            ? { ...c, frame_url: res.frame_url, status: res.status, frame_captured_at: res.frame_captured_at }
                            : c
                        ))
                      } catch (err) {
                        setError(err?.response?.data?.error || err.message)
                      } finally {
                        setSaving(false)
                        e.target.value = ''
                      }
                    }}
                  />
                </label>
              </div>
            ))}
          </div>
        )}

        {/* ─ Step 5 ──────────────────────────────────────────────────────── */}
        {step === 5 && (
          <div className="space-y-4">
            <div>
              <h2 className="text-xl font-semibold mb-1">Point Correspondences</h2>
              <p className="text-sm text-gray-500">
                For each camera: click a point on its frame, then click the matching spot on the floor plan. Repeat ≥ 8 times, spread across the full frame.
                {pendingPixelPt && (
                  <span className="ml-2 text-blue-600 font-medium">→ Now click the matching location on the floor plan</span>
                )}
              </p>
            </div>

            {cameraConfigs.length > 0 && (
              <div className="flex gap-2 flex-wrap">
                {cameraConfigs.map(cc => {
                  const count = correspondencesMap[cc.id]?.length || 0
                  const done = ['calibrated', 'verified'].includes(cc.status)
                  return (
                    <button
                      key={cc.id}
                      onClick={() => { setSelectedConfigId(cc.id); setPendingPixelPt(null) }}
                      className={`px-3 py-1.5 text-sm rounded border ${
                        selectedConfigId === cc.id
                          ? 'bg-blue-600 text-white border-blue-600'
                          : 'border-gray-300 hover:border-blue-400'
                      }`}
                    >
                      {cc.physical_camera_name}
                      {done
                        ? <span className="ml-1 text-green-400">✓</span>
                        : count > 0
                        ? <span className="ml-1 text-xs opacity-70">({count})</span>
                        : null
                      }
                    </button>
                  )
                })}
              </div>
            )}

            {selectedConfig && (
              <div className="flex gap-4 items-start flex-wrap">
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-gray-500 mb-1 font-medium">
                    Camera Frame — click a point
                    {pendingPixelPt && <span className="text-gray-400"> (waiting for floor plan click)</span>}
                  </p>
                  {selectedConfig.frame_url ? (
                    <FrameStage
                      frameUrl={selectedConfig.frame_url}
                      width={380} height={280}
                      points={activeCorrespondences.map(c => c.pixel)}
                      onCanvasClick={!pendingPixelPt ? handleFrameClickForCorrespondence : null}
                    />
                  ) : (
                    <div className="flex items-center justify-center h-40 bg-gray-100 rounded text-sm text-gray-400">
                      No frame uploaded — go back to Step 4
                    </div>
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-gray-500 mb-1 font-medium">Floor Plan — click matching point</p>
                  <FloorPlanStage
                    floorPlan={floorPlan}
                    cameraConfigs={cameraConfigs}
                    activeConfigId={selectedConfigId}
                    correspondencePoints={activeCorrespondences.map(c => c.world)}
                    onCanvasClick={pendingPixelPt ? handleMapClickForCorrespondence : null}
                    width={380} height={280}
                  />
                </div>
              </div>
            )}

            {activeCorrespondences.length > 0 && (
              <div className="bg-gray-50 rounded p-3 max-w-2xl">
                <p className="text-xs font-medium text-gray-600 mb-2">{activeCorrespondences.length} pair(s):</p>
                <div className="space-y-1 max-h-32 overflow-y-auto">
                  {activeCorrespondences.map((c, i) => (
                    <div key={i} className="flex items-center justify-between text-xs text-gray-600">
                      <span>
                        #{i + 1}: pixel ({c.pixel[0].toFixed(0)}, {c.pixel[1].toFixed(0)})
                        → world ({c.world[0].toFixed(1)}, {c.world[1].toFixed(1)})
                      </span>
                      <button
                        onClick={() => removeCorrespondence(selectedConfigId, i)}
                        className="text-red-400 hover:text-red-600 ml-2"
                      >✕</button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ─ Step 6 ──────────────────────────────────────────────────────── */}
        {step === 6 && (
          <div className="space-y-4 max-w-xl">
            <div>
              <h2 className="text-xl font-semibold mb-1">Compute Homography</h2>
              <p className="text-sm text-gray-500">Compute the pixel-to-world mapping for each camera.</p>
            </div>

            {cameraConfigs.length === 0 && (
              <div className="text-sm text-gray-400 p-4 bg-gray-50 rounded">No cameras placed.</div>
            )}

            {cameraConfigs.map(cc => {
              const corr = correspondencesMap[cc.id] || []
              const calib = calibResultsMap[cc.id]
              const alreadyDone = ['calibrated', 'verified'].includes(cc.status)
              return (
                <div key={cc.id} className="border border-gray-200 rounded-lg p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-sm">{cc.physical_camera_name}</span>
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                      alreadyDone ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
                    }`}>{cc.status}</span>
                  </div>

                  {alreadyDone && !calib && (
                    <p className="text-sm text-green-700">✓ Already calibrated — can proceed to Step 7.</p>
                  )}

                  {!alreadyDone && (
                    <button
                      onClick={() => handleComputeHomographyFor(cc.id)}
                      disabled={corr.length < 8 || saving}
                      className="px-4 py-1.5 bg-blue-600 text-white rounded text-sm disabled:opacity-50"
                    >
                      {saving ? 'Computing…' : `Compute (${corr.length} pairs)`}
                    </button>
                  )}

                  {calib && (
                    <div className="grid grid-cols-2 gap-1.5 text-xs text-gray-600 bg-gray-50 rounded p-3">
                      <span>RMS Error</span>
                      <span className={`font-mono font-medium ${
                        (calib.rms_reprojection_error || 0) < 5 ? 'text-green-600' : 'text-yellow-600'
                      }`}>{calib.rms_reprojection_error?.toFixed(3)} px</span>
                      <span>Max Error</span>
                      <span className="font-mono">{calib.max_reprojection_error?.toFixed(3)} px</span>
                      <span>Coverage</span>
                      <span className="font-mono">{((calib.coverage_score || 0) * 100).toFixed(1)}%</span>
                      <span>Condition #</span>
                      <span className={`font-mono ${
                        (calib.condition_number || 0) < 1000 ? 'text-green-600' : 'text-red-600'
                      }`}>{calib.condition_number?.toFixed(1)}</span>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}

        {/* ─ Step 7 ──────────────────────────────────────────────────────── */}
        {step === 7 && (
          <div className="space-y-4">
            <div>
              <h2 className="text-xl font-semibold mb-1">Verify Calibration</h2>
              <p className="text-sm text-gray-500">
                Click a recognisable point on the camera frame to see its projected location on the floor plan.
                If it looks correct, click "Looks Good".
              </p>
            </div>

            {cameraConfigs.length > 1 && (
              <div className="flex gap-2 flex-wrap">
                {cameraConfigs.map(cc => (
                  <button
                    key={cc.id}
                    onClick={() => setSelectedConfigId(cc.id)}
                    className={`px-3 py-1.5 text-sm rounded border ${
                      selectedConfigId === cc.id
                        ? 'bg-blue-600 text-white border-blue-600'
                        : 'border-gray-300'
                    }`}
                  >
                    {cc.physical_camera_name}{cc.status === 'verified' && ' ✓'}
                  </button>
                ))}
              </div>
            )}

            {selectedConfig && (
              <>
                <div className="flex gap-4 items-start flex-wrap">
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-gray-500 mb-1 font-medium">Camera Frame — click a point to project</p>
                    <FrameStage
                      frameUrl={selectedConfig.frame_url}
                      width={380} height={280}
                      points={verifyPreview?.pixel ? [verifyPreview.pixel] : []}
                      onCanvasClick={handleFrameClickForVerify}
                    />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-gray-500 mb-1 font-medium">Floor Plan — projected location</p>
                    <FloorPlanStage
                      floorPlan={floorPlan}
                      cameraConfigs={cameraConfigs}
                      activeConfigId={selectedConfigId}
                      correspondencePoints={verifyPreview?.world ? [verifyPreview.world] : []}
                      width={380} height={280}
                    />
                  </div>
                </div>

                {verifyPreview?.world && (
                  <p className="text-sm text-gray-600">
                    Projected: ({verifyPreview.world[0].toFixed(2)}, {verifyPreview.world[1].toFixed(2)}) m
                  </p>
                )}

                {!calibResultsMap[selectedConfigId] && ['calibrated', 'verified'].includes(selectedConfig.status) && (
                  <p className="text-sm text-amber-600 bg-amber-50 px-3 py-2 rounded">
                    Calibration loaded from server — live projection preview is unavailable. You can still verify.
                  </p>
                )}

                <div className="flex gap-3 items-center">
                  <button
                    onClick={handleVerifyCalibration}
                    disabled={saving || selectedConfig.status === 'verified'}
                    className="px-5 py-2 bg-green-600 text-white rounded-lg text-sm font-medium disabled:opacity-50"
                  >
                    {saving ? 'Saving…' : selectedConfig.status === 'verified' ? '✓ Verified' : 'Looks Good'}
                  </button>
                  {selectedConfig.status === 'verified' && cameraConfigs.some(cc => cc.status !== 'verified') && (
                    <p className="text-sm text-gray-500">Switch to the next camera above to verify it.</p>
                  )}
                </div>
              </>
            )}
          </div>
        )}

        {/* ─ Step 8 ──────────────────────────────────────────────────────── */}
        {step === 8 && (
          <div className="space-y-4 max-w-4xl">
            <div>
              <h2 className="text-xl font-semibold mb-1">Draw Zones & Obstacles</h2>
              <p className="text-sm text-gray-500">
                Click to place vertices. Click near the first vertex to close the polygon, then name it.
              </p>
            </div>

            <div className="flex gap-3 items-center flex-wrap">
              {['zone', 'obstacle'].map(dm => (
                <button key={dm}
                  onClick={() => { setDrawMode(dm); setInProgressPoints([]) }}
                  className={`px-3 py-1.5 rounded border text-sm capitalize ${
                    drawMode === dm
                      ? 'bg-blue-600 text-white border-blue-600'
                      : 'border-gray-300 hover:border-blue-400'
                  }`}
                >
                  Draw {dm}
                </button>
              ))}
              {inProgressPoints.length > 0 && (
                <button onClick={() => setInProgressPoints([])}
                  className="text-sm text-gray-500 hover:text-gray-700">
                  Cancel ({inProgressPoints.length} pts)
                </button>
              )}
              {zones.length === 0 && obstacles.length === 0 && !step8Skipped && (
                <button
                  onClick={() => setStep8Skipped(true)}
                  className="text-sm text-gray-400 hover:text-gray-600 ml-auto border border-gray-200 px-3 py-1.5 rounded"
                >
                  Skip this step
                </button>
              )}
              {step8Skipped && zones.length === 0 && obstacles.length === 0 && (
                <span className="text-sm text-gray-400 ml-auto">Step skipped</span>
              )}
            </div>

            <FloorPlanStage
              floorPlan={floorPlan}
              zones={zones}
              obstacles={obstacles}
              cameraConfigs={cameraConfigs}
              overlayPoints={inProgressPoints}
              overlayMode={drawMode}
              onCanvasClick={!pendingPolygon ? handleMapClickForDrawing : null}
            />

            {/* Naming form shown after polygon is closed */}
            {pendingPolygon && (
              <form
                onSubmit={handlePendingPolygonSubmit}
                className="bg-white border border-blue-200 rounded-lg p-4 space-y-3 max-w-sm shadow-sm"
              >
                <h4 className="text-sm font-medium text-gray-800 capitalize">
                  Name this {pendingPolygon.mode} ({pendingPolygon.points.length} vertices)
                </h4>
                <input
                  autoFocus
                  placeholder={pendingPolygon.mode === 'zone' ? 'Zone name (required)' : 'Obstacle name (optional)'}
                  value={pendingName}
                  onChange={e => setPendingName(e.target.value)}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm"
                />
                {pendingPolygon.mode === 'zone' && (
                  <select
                    value={pendingZoneType}
                    onChange={e => setPendingZoneType(e.target.value)}
                    className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm"
                  >
                    {['entrance', 'checkout', 'aisle', 'staff_only', 'general'].map(t => (
                      <option key={t} value={t}>{t}</option>
                    ))}
                  </select>
                )}
                <div className="flex gap-2">
                  <button
                    type="submit"
                    disabled={saving || (pendingPolygon.mode === 'zone' && !pendingName.trim())}
                    className="px-4 py-1.5 bg-blue-600 text-white rounded text-sm disabled:opacity-50"
                  >
                    {saving ? 'Saving…' : 'Save'}
                  </button>
                  <button
                    type="button"
                    onClick={() => setPendingPolygon(null)}
                    className="px-4 py-1.5 text-gray-600 text-sm hover:text-gray-900"
                  >
                    Discard polygon
                  </button>
                </div>
              </form>
            )}

            <div className="flex gap-6 flex-wrap">
              {zones.length > 0 && (
                <div className="flex-1 min-w-48">
                  <p className="text-xs font-medium text-gray-600 mb-2">Zones ({zones.length})</p>
                  <div className="space-y-1">
                    {zones.map(z => (
                      <div key={z.id}
                        className="flex items-center justify-between text-sm bg-gray-50 rounded px-3 py-1.5"
                      >
                        <span className="flex items-center gap-2 min-w-0">
                          <span className="w-2 h-2 rounded-sm flex-shrink-0"
                            style={{ background: ZONE_COLORS[z.type] }} />
                          <span className="truncate">{z.name}</span>
                          <span className="text-xs text-gray-400 flex-shrink-0">{z.type}</span>
                        </span>
                        <button onClick={() => handleDeleteZone(z.id)}
                          className="text-xs text-red-400 hover:text-red-600 flex-shrink-0 ml-2">
                          Delete
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {obstacles.length > 0 && (
                <div className="flex-1 min-w-48">
                  <p className="text-xs font-medium text-gray-600 mb-2">Obstacles ({obstacles.length})</p>
                  <div className="space-y-1">
                    {obstacles.map(obs => (
                      <div key={obs.id}
                        className="flex items-center justify-between text-sm bg-gray-50 rounded px-3 py-1.5"
                      >
                        <span className="truncate">{obs.name || '(unnamed)'}</span>
                        <button onClick={() => handleDeleteObstacle(obs.id)}
                          className="text-xs text-red-400 hover:text-red-600 flex-shrink-0 ml-2">
                          Delete
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ─ Step 9 ──────────────────────────────────────────────────────── */}
        {step === 9 && (
          <div className="space-y-6 max-w-lg">
            <div>
              <h2 className="text-xl font-semibold mb-1">
                {mode === 'editing' ? 'Review & Activate' : 'Activate Configuration'}
              </h2>
              <p className="text-sm text-gray-500">
                {mode === 'editing'
                  ? 'Review your changes. Save and exit to keep as draft, or activate to deploy immediately.'
                  : `Review the summary, then activate. The new configuration will go live after a ${ACTIVATION_COUNTDOWN}-second sync countdown.`
                }
              </p>
            </div>

            <div className="bg-gray-50 rounded-lg border border-gray-200 p-4 space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-600">Sections</span>
                <span className="font-medium">{sections.length}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Zones</span>
                <span className="font-medium">{zones.length}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Cameras placed</span>
                <span className="font-medium">{cameraConfigs.length}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Cameras calibrated</span>
                <span className={`font-medium ${
                  cameraConfigs.length > 0 && cameraConfigs.every(c => ['calibrated', 'verified'].includes(c.status))
                    ? 'text-green-600' : 'text-yellow-600'
                }`}>
                  {cameraConfigs.filter(c => ['calibrated', 'verified'].includes(c.status)).length} / {cameraConfigs.length}
                </span>
              </div>
              {floorPlan?.scale_defined && (
                <div className="flex justify-between">
                  <span className="text-gray-600">Scale</span>
                  <span className="font-medium">{floorPlan.pixels_per_meter?.toFixed(2)} px/m</span>
                </div>
              )}
              <div className="flex justify-between border-t border-gray-200 pt-2 mt-2">
                <span className="text-gray-600">Sync countdown</span>
                <span className="font-medium">{ACTIVATION_COUNTDOWN}s</span>
              </div>
            </div>

            {!syncEvent ? (
              <div className="space-y-4">
                <div>
                  <label className="block text-sm text-gray-700 mb-1">Version label (optional)</label>
                  <input
                    value={activationLabel}
                    onChange={e => setActivationLabel(e.target.value)}
                    placeholder="e.g. Initial setup"
                    className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
                  />
                </div>
                <div className="flex gap-3 flex-wrap">
                  {mode === 'editing' && (
                    <button
                      onClick={() => navigate(`/store/${slug}/config`)}
                      className="px-6 py-2.5 bg-gray-200 text-gray-700 rounded-lg text-sm font-semibold hover:bg-gray-300"
                    >
                      Save Draft &amp; Exit
                    </button>
                  )}
                  <button
                    onClick={handleActivate}
                    disabled={saving}
                    className="px-6 py-2.5 bg-green-600 text-white rounded-lg text-sm font-semibold hover:bg-green-700 disabled:opacity-50"
                  >
                    {saving ? 'Scheduling…' : `Activate (${ACTIVATION_COUNTDOWN}s countdown)`}
                  </button>
                </div>
              </div>
            ) : (
              <div>
                {syncEvent.status === 'pending' && (
                  <div className="text-center py-6">
                    <p className="text-5xl font-bold text-blue-600 tabular-nums">
                      {Math.max(0, Math.round(syncEvent.remaining_seconds ?? 0))}s
                    </p>
                    <p className="text-sm text-gray-500 mt-2">Configuration activating…</p>
                    <div className="mt-4 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-blue-500 rounded-full transition-all"
                        style={{
                          width: `${Math.min(100, 100 - ((syncEvent.remaining_seconds ?? 0) / ACTIVATION_COUNTDOWN) * 100)}%`,
                          transitionDuration: '2000ms',
                        }}
                      />
                    </div>
                  </div>
                )}
                {syncEvent.status === 'executed' && (
                  <div className="text-center py-6">
                    <p className="text-3xl">🎉</p>
                    <p className="text-lg font-semibold text-green-700 mt-2">Configuration activated!</p>
                    <p className="text-sm text-gray-500 mt-1">Redirecting…</p>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* ── Navigation ────────────────────────────────────────────────── */}
        <div className="flex items-center justify-between mt-8 pt-4 border-t border-gray-100">
          <button
            onClick={() => setStep(s => Math.max(1, s - 1))}
            disabled={step === 1}
            className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 disabled:opacity-40"
          >
            ← Back
          </button>
          {step < 9 && (
            <button
              onClick={() => setStep(s => s + 1)}
              disabled={mode === 'onboarding' && !isStepComplete(step)}
              className="px-5 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
            >
              Continue →
            </button>
          )}
        </div>
      </main>
    </div>
  )
}
