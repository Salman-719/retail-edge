/**
 * RetailVision API client — store-scoped stubs.
 *
 * All functions are skeleton signatures. Implement each by making the
 * appropriate fetch() call to the EEP service (proxied at /api by nginx).
 *
 * Call setCurrentStoreId(id) once a store is selected before invoking
 * any store-scoped function.
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
  // TODO: GET /api/stores → return array of store objects
  throw new Error('Not implemented')
}

export async function createStore(name, onboardingMethod = 'standard') {
  // TODO: POST /api/stores {name, onboarding_method} → return created store
  throw new Error('Not implemented')
}

// ─── Floor plan ──────────────────────────────────────────────────────────────

export async function uploadFloorplan(file) {
  // TODO: POST ${base()}/floor-plan/upload multipart → return {url, width, height}
  throw new Error('Not implemented')
}

export async function saveScale({ originPx, scalePoint1Px, scalePoint2Px, realWorldDistanceM, pixelsPerMeter }) {
  // TODO: PUT ${base()}/floor-plan/scale {origin_px, scale_point1_px, scale_point2_px, real_world_distance_m, pixels_per_meter}
  throw new Error('Not implemented')
}

export async function saveWorldBounds(bounds) {
  // TODO: PUT ${base()}/floor-plan/world-bounds {world_x_min, world_x_max, world_y_min, world_y_max}
  throw new Error('Not implemented')
}

// ─── Zones ───────────────────────────────────────────────────────────────────

export async function createZone(zone) {
  // TODO: POST ${base()}/zones {id, name, type, points}
  throw new Error('Not implemented')
}

export async function updateZone(id, patch) {
  // TODO: PUT ${base()}/zones/${id} patch
  throw new Error('Not implemented')
}

export async function deleteZone(id) {
  // TODO: DELETE ${base()}/zones/${id}
  throw new Error('Not implemented')
}

// ─── Obstacles ───────────────────────────────────────────────────────────────

export async function createObstacle(obs) {
  // TODO: POST ${base()}/obstacles {id, name, points}
  throw new Error('Not implemented')
}

export async function updateObstacle(id, patch) {
  // TODO: PUT ${base()}/obstacles/${id} patch
  throw new Error('Not implemented')
}

export async function deleteObstacle(id) {
  // TODO: DELETE ${base()}/obstacles/${id}
  throw new Error('Not implemented')
}

// ─── Cameras ─────────────────────────────────────────────────────────────────

export async function createCamera(cam) {
  // TODO: POST ${base()}/cameras {id, name, position_x, position_y, height_meters}
  throw new Error('Not implemented')
}

export async function updateCamera(cameraId, patch) {
  // TODO: PUT ${base()}/cameras/${cameraId} patch
  throw new Error('Not implemented')
}

export async function deleteCamera(cameraId) {
  // TODO: DELETE ${base()}/cameras/${cameraId}
  throw new Error('Not implemented')
}

export async function listCamerasWithCalibration() {
  // TODO: GET ${base()}/cameras → map to {id, name, calibration: {method, intrinsic_matrix, ...}}
  throw new Error('Not implemented')
}

// ─── Videos ──────────────────────────────────────────────────────────────────

export async function uploadVideo(cameraId, file) {
  // TODO: POST ${base()}/cameras/${cameraId}/video multipart
  //       → return {videoPath, duration, fps, width, height}
  throw new Error('Not implemented')
}

export async function getVideoFrame(cameraId, timestampSec) {
  // TODO: GET ${base()}/cameras/${cameraId}/frame?timestamp_sec=${timestampSec}
  //       → return object URL for JPEG blob
  throw new Error('Not implemented')
}

// ─── Calibration Files (Method 2) ────────────────────────────────────────────

export async function parseCalibrationFiles(cameraId, intrFile, extrFile, scaleFactor = 1.0) {
  // TODO: POST ${base()}/calibration-files/parse multipart {intr_file, extr_file, scale_factor}
  //       → return parsed intrinsic + extrinsic matrices
  throw new Error('Not implemented')
}

export async function saveCalibrationFiles(cameraId, parsedData) {
  // TODO: POST ${base()}/cameras/${cameraId}/calibration-files JSON parsedData
  throw new Error('Not implemented')
}

export async function getWorldBoundsFromCameras() {
  // TODO: GET ${base()}/calibration-files/world-bounds-from-cameras
  //       → return {xMin, xMax, yMin, yMax} computed from all calibrated cameras
  throw new Error('Not implemented')
}

// ─── Homography Calibration (Method 1) ───────────────────────────────────────

export async function computeHomography(cameraId, camPoints, floorPoints) {
  // TODO: POST ${base()}/cameras/${cameraId}/calibrate
  //       body: {correspondences: [{camPx: {x,y}, floorM: {x,y}}, ...]}
  //       → return {status, matrix, reprojectionError, perPointErrors}
  throw new Error('Not implemented')
}

// ─── Tracking ────────────────────────────────────────────────────────────────

export async function startTracking(storeId, cameraId, modelSize = 'yolov8n') {
  // TODO: POST /api/stores/${storeId}/cameras/${cameraId}/tracking/start?model_size=${modelSize}
  throw new Error('Not implemented')
}

export async function getTrackingProgress(storeId, cameraId) {
  // TODO: GET /api/stores/${storeId}/cameras/${cameraId}/tracking/progress
  //       → normalise to {status, progress (0..1), processedFrames, totalFrames, zoneOccupancy, heatmapUrl, error}
  throw new Error('Not implemented')
}

export function trackingStreamUrl(storeId, cameraId, key = 0) {
  return `/api/stores/${storeId}/cameras/${cameraId}/tracking/stream?k=${key}`
}

export async function getTrajectory(storeId, cameraId) {
  // TODO: GET /api/stores/${storeId}/cameras/${cameraId}/tracking/trajectory
  //       → return data.trajectory array
  throw new Error('Not implemented')
}

// ─── Project save / load ─────────────────────────────────────────────────────

export async function saveProject(data) {
  // TODO: persist full Zustand project state to backend in sequence:
  //   1. saveScale() if data.scale is set
  //   2. createZone() for each zone, then deleteZone() for any DB zones not in local state
  //   3. createObstacle() for each obstacle, then purge stale DB obstacles
  //   4. createCamera() for each camera + computeHomography() if correspondences are present
  //   5. Collect errors and throw if any step failed
  throw new Error('Not implemented')
}

export async function loadProject() {
  // TODO: parallel fetch floor-plan, zones, obstacles, cameras from backend
  //       reconstruct and return the Zustand project shape:
  //       {version, savedAt, onboardingMethod, worldBounds, floorPlan, scale, zones, obstacles, cameras}
  throw new Error('Not implemented')
}
