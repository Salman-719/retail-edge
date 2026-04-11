/**
 * RetailVision API client — store-scoped.
 *
 * Call setCurrentStoreId(id) once a store is selected before
 * invoking any store-scoped function.
 */

let _storeId = null

export function setCurrentStoreId(id) { _storeId = id }
export function getCurrentStoreId() { return _storeId }

function base() {
  if (!_storeId) throw new Error('No store selected. Call setCurrentStoreId() first.')
  return `/api/stores/${_storeId}`
}

async function _json(r) {
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

// ─── Stores ──────────────────────────────────────────────────────────────────

export async function listStores() {
  return _json(await fetch('/api/stores'))
}

export async function createStore(name, onboardingMethod = 'standard') {
  return _json(await fetch('/api/stores', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, onboarding_method: onboardingMethod }),
  }))
}

// ─── Floor plan ──────────────────────────────────────────────────────────────

export async function uploadFloorplan(file) {
  const fd = new FormData()
  fd.append('file', file)
  const data = await _json(await fetch(`${base()}/floor-plan/upload`, { method: 'POST', body: fd }))
  // Normalise to the shape Step1 expects (FloorPlanResponse has no url field — construct it)
  return {
    url: `/api/stores/${_storeId}/floor-plan/image`,
    width: data.width_px,
    height: data.height_px,
    notice: null,
  }
}

export async function saveScale({ originPx, scalePoint1Px, scalePoint2Px, realWorldDistanceM, pixelsPerMeter }) {
  // ScaleConfig schema uses nested Point objects
  return _json(await fetch(`${base()}/floor-plan/scale`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      origin_px: { x: originPx.x, y: originPx.y },
      scale_point1_px: { x: scalePoint1Px.x, y: scalePoint1Px.y },
      scale_point2_px: { x: scalePoint2Px.x, y: scalePoint2Px.y },
      real_world_distance_m: realWorldDistanceM,
      pixels_per_meter: pixelsPerMeter,
    }),
  }))
}

// ─── Zones ───────────────────────────────────────────────────────────────────

export async function createZone(zone) {
  return _json(await fetch(`${base()}/zones`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: zone.id, name: zone.name, type: zone.type, points: zone.points }),
  }))
}

export async function updateZone(id, patch) {
  return _json(await fetch(`${base()}/zones/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  }))
}

export async function deleteZone(id) {
  const r = await fetch(`${base()}/zones/${id}`, { method: 'DELETE' })
  if (!r.ok) throw new Error(await r.text())
}

// ─── Obstacles ───────────────────────────────────────────────────────────────

export async function createObstacle(obs) {
  return _json(await fetch(`${base()}/obstacles`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: obs.id, name: obs.name, points: obs.points }),
  }))
}

export async function deleteObstacle(id) {
  const r = await fetch(`${base()}/obstacles/${id}`, { method: 'DELETE' })
  if (!r.ok) throw new Error(await r.text())
}

// ─── Cameras ─────────────────────────────────────────────────────────────────

export async function createCamera(cam) {
  return _json(await fetch(`${base()}/cameras`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      id: cam.id,
      name: cam.name,
      position_x: cam.position?.x,
      position_y: cam.position?.y,
      height_meters: cam.heightMeters,
    }),
  }))
}

export async function updateCamera(cameraId, patch) {
  return _json(await fetch(`${base()}/cameras/${cameraId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  }))
}

export async function deleteCamera(cameraId) {
  const r = await fetch(`${base()}/cameras/${cameraId}`, { method: 'DELETE' })
  if (!r.ok) throw new Error(await r.text())
}

export async function updateObstacle(obsId, patch) {
  return _json(await fetch(`${base()}/obstacles/${obsId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  }))
}

export async function uploadVideo(cameraId, file) {
  const fd = new FormData()
  fd.append('file', file)
  const data = await _json(await fetch(`${base()}/cameras/${cameraId}/video`, { method: 'POST', body: fd }))
  return {
    videoPath: data.video_s3_key,
    duration: data.video_duration,
    fps: data.video_fps,
    width: data.video_width,
    height: data.video_height,
  }
}

export async function getVideoFrame(cameraId, timestampSec) {
  const r = await fetch(`${base()}/cameras/${cameraId}/frame?timestamp_sec=${timestampSec}`)
  if (!r.ok) throw new Error(await r.text())
  return URL.createObjectURL(await r.blob())
}

// ─── Calibration Files (Method 2) ────────────────────────────────────────────

/**
 * Fetch all cameras for the current store including their full calibration matrices
 * (intrinsic_matrix, rotation_matrix, translation_vector, image size).
 * Used by CalibStep2 to do client-side pixel→world projection.
 */
export async function listCamerasWithCalibration() {
  const cameras = await _json(await fetch(`${base()}/cameras`))
  return (cameras ?? []).map(c => ({
    id: c.id,
    name: c.name,
    calibration: c.calibration
      ? {
          method: c.calibration.method,
          intrinsic_matrix: c.calibration.intrinsic_matrix,
          rotation_matrix: c.calibration.rotation_matrix,
          translation_vector: c.calibration.translation_vector,
          image_width: c.calibration.image_width,
          image_height: c.calibration.image_height,
        }
      : null,
  }))
}

/**
 * Parse intr_*.xml + extr_*.xml server-side. No DB write.
 * @param {string} cameraId  (unused by the endpoint URL, kept for caller context)
 * @param {File}   intrFile  Intrinsic XML file
 * @param {File}   extrFile  Extrinsic XML file
 * @param {number} scaleFactor  Multiplier applied to tvec (e.g. 0.001 for mm→m)
 */
export async function parseCalibrationFiles(cameraId, intrFile, extrFile, scaleFactor = 1.0) {
  const fd = new FormData()
  fd.append('intr_file', intrFile)
  fd.append('extr_file', extrFile)
  fd.append('scale_factor', scaleFactor)
  return _json(await fetch(`${base()}/calibration-files/parse`, { method: 'POST', body: fd }))
}

/**
 * Persist previously-parsed calibration data to the DB for the given camera.
 */
export async function saveCalibrationFiles(cameraId, parsedData) {
  return _json(await fetch(`${base()}/cameras/${cameraId}/calibration-files`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(parsedData),
  }))
}

/**
 * Auto-compute world bounds from all calibrated cameras (Method 2).
 */
export async function getWorldBoundsFromCameras() {
  return _json(await fetch(`${base()}/calibration-files/world-bounds-from-cameras`))
}

/**
 * Save world bounds for the virtual map canvas (Method 2).
 * @param {{ xMin, xMax, yMin, yMax }} bounds  World metres
 */
export async function saveWorldBounds(bounds) {
  return _json(await fetch(`${base()}/floor-plan/world-bounds`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      world_x_min: bounds.xMin,
      world_x_max: bounds.xMax,
      world_y_min: bounds.yMin,
      world_y_max: bounds.yMax,
    }),
  }))
}

// ─── Calibration ─────────────────────────────────────────────────────────────

/**
 * Step7 calls: computeHomography(cam.id, corr.map(c => c.camPx), corr.map(c => c.floorM))
 * Returns a normalised result shape.
 */
export async function computeHomography(cameraId, camPoints, floorPoints) {
  const correspondences = camPoints.map((cp, i) => ({
    camPx: { x: cp.x, y: cp.y },
    floorM: { x: floorPoints[i].x, y: floorPoints[i].y },
  }))
  const data = await _json(await fetch(`${base()}/cameras/${cameraId}/calibrate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ correspondences }),
  }))
  return {
    status: data.status,
    matrix: data.homography_matrix,
    reprojectionError: data.reprojection_error,
    perPointErrors: data.per_point_errors ?? null,
  }
}

// ─── Tracking ────────────────────────────────────────────────────────────────

export async function startTracking(storeId, cameraId, modelSize = 'yolov8n') {
  return _json(await fetch(
    `/api/stores/${storeId}/cameras/${cameraId}/tracking/start?model_size=${modelSize}`,
    { method: 'POST' },
  ))
}

export async function getTrackingProgress(storeId, cameraId) {
  const data = await _json(await fetch(`/api/stores/${storeId}/cameras/${cameraId}/tracking/progress`))
  // Normalise to the shape Step9 expects
  return {
    status: data.status,
    progress: (data.progress ?? 0) / 100,   // Step9 expects 0..1
    processedFrames: Math.round(((data.progress ?? 0) / 100) * (data.total_frames ?? 0)),
    totalFrames: data.total_frames ?? 0,
    zoneOccupancy: data.zone_occupancy ?? {},
    heatmapUrl: data.heatmap_url ?? null,
    error: data.error ?? null,
  }
}

export function trackingStreamUrl(storeId, cameraId, key = 0) {
  return `/api/stores/${storeId}/cameras/${cameraId}/tracking/stream?k=${key}`
}

export async function getTrajectory(storeId, cameraId) {
  const data = await _json(await fetch(`/api/stores/${storeId}/cameras/${cameraId}/tracking/trajectory`))
  return data.trajectory ?? []
}

// ─── Project save / load (Step8) ─────────────────────────────────────────────

/**
 * Persist the full Zustand project state to the new backend.
 * Called by Step8 "Save Project".
 */
export async function saveProject(data) {
  const errors = []

  // 1. Scale config
  if (data.scale) {
    try {
      await saveScale({
        originPx: data.scale.originPx,
        scalePoint1Px: data.scale.scalePoint1Px,
        scalePoint2Px: data.scale.scalePoint2Px,
        realWorldDistanceM: data.scale.realWorldDistanceM,
        pixelsPerMeter: data.scale.pixelsPerMeter,
      })
    } catch (e) {
      errors.push(`Scale: ${e.message}`)
    }
  }

  // 2. Zones — upsert, then purge any DB zones not in local state
  for (const zone of data.zones ?? []) {
    try { await createZone(zone) } catch (_) {}
  }
  try {
    const dbZones = await fetch(`${base()}/zones`).then(r => r.ok ? r.json() : [])
    const localIds = new Set((data.zones ?? []).map(z => z.id))
    for (const z of dbZones) {
      if (!localIds.has(z.id)) await deleteZone(z.id).catch(() => {})
    }
  } catch (_) {}

  // 3. Obstacles — upsert, then purge
  for (const obs of data.obstacles ?? []) {
    try { await createObstacle(obs) } catch (_) {}
  }
  try {
    const dbObs = await fetch(`${base()}/obstacles`).then(r => r.ok ? r.json() : [])
    const localIds = new Set((data.obstacles ?? []).map(o => o.id))
    for (const o of dbObs) {
      if (!localIds.has(o.id)) await deleteObstacle(o.id).catch(() => {})
    }
  } catch (_) {}

  // 4. Cameras — upsert, then purge
  for (const cam of data.cameras ?? []) {
    try { await createCamera(cam) } catch (_) {}
    if (data.onboardingMethod === 'calibration') {
      // Method 2: calibration was already persisted during CalibStep1 — nothing to do here
    } else if (cam.homographyMatrix && cam.correspondences?.length >= 4) {
      try {
        await computeHomography(
          cam.id,
          cam.correspondences.map(c => c.camPx),
          cam.correspondences.map(c => c.floorM),
        )
      } catch (_) {}
    }
  }
  try {
    const dbCams = await fetch(`${base()}/cameras`).then(r => r.ok ? r.json() : [])
    const localIds = new Set((data.cameras ?? []).map(c => c.id))
    for (const c of dbCams) {
      if (!localIds.has(c.id)) await deleteCamera(c.id).catch(() => {})
    }
  } catch (_) {}

  if (errors.length) throw new Error(errors.join('; '))
  return { ok: true }
}

/**
 * Load project state from the backend and return it in the shape
 * that Zustand's loadProject() expects.
 * Makes separate calls: floor-plan, zones, obstacles, cameras.
 */
export async function loadProject() {
  try {
    const [fp, zones, obstacles, cameras] = await Promise.all([
      fetch(`${base()}/floor-plan`).then(r => r.ok ? r.json() : null).catch(() => null),
      fetch(`${base()}/zones`).then(r => r.ok ? r.json() : []).catch(() => []),
      fetch(`${base()}/obstacles`).then(r => r.ok ? r.json() : []).catch(() => []),
      fetch(`${base()}/cameras`).then(r => r.ok ? r.json() : []).catch(() => []),
    ])

    // Detect method from floor plan data
    const isCalibMethod = fp?.world_x_min != null
    const onboardingMethod = isCalibMethod ? 'calibration' : 'standard'

    return {
      version: '1.0',
      savedAt: new Date().toISOString(),
      onboardingMethod,
      worldBounds: isCalibMethod ? {
        xMin: fp.world_x_min,
        xMax: fp.world_x_max,
        yMin: fp.world_y_min,
        yMax: fp.world_y_max,
      } : null,
      floorPlan: fp?.s3_key ? {
        url: `/api/stores/${_storeId}/floor-plan/image`,
        widthPx: fp.width_px,
        heightPx: fp.height_px,
      } : null,
      scale: (fp?.pixels_per_meter && !isCalibMethod) ? {
        originPx: { x: fp.origin_x, y: fp.origin_y },
        scalePoint1Px: { x: fp.scale_point1_x, y: fp.scale_point1_y },
        scalePoint2Px: { x: fp.scale_point2_x, y: fp.scale_point2_y },
        realWorldDistanceM: fp.real_world_distance_m,
        pixelsPerMeter: fp.pixels_per_meter,
      } : null,
      zones: zones ?? [],
      obstacles: obstacles ?? [],
      cameras: (cameras ?? []).map(c => ({
        id: c.id,
        name: c.name,
        position: { x: c.position_x ?? 0, y: c.position_y ?? 0 },
        heightMeters: c.height_meters ?? 0,
        videoDuration: c.video_duration ?? null,
        videoFps: c.video_fps ?? null,
        videoWidth: c.video_width ?? null,
        videoHeight: c.video_height ?? null,
        homographyMatrix: c.calibration?.homography_matrix ?? null,
        reprojectionError: c.calibration?.reprojection_error ?? null,
        homographyStatus: c.calibration?.status ?? null,
        correspondences: c.calibration?.correspondences ?? [],
        // Method 2 calibration fields
        calibrationMethod: c.calibration?.method ?? null,
        calibrationStatus: c.calibration?.status ?? null,
        cameraWorldXYZ: (c.calibration?.camera_world_x != null)
          ? [c.calibration.camera_world_x, c.calibration.camera_world_y, c.calibration.camera_world_z]
          : null,
      })),
    }
  } catch {
    return null
  }
}
