/**
 * RetailVision API client.
 * Axios instance with JWT Bearer injection and automatic token refresh on 401.
 * All store-scoped calls use /api/store/{slug}/... per the spec.
 */
import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

function getTokens() {
  try { return JSON.parse(localStorage.getItem('rv_tokens') || 'null') } catch { return null }
}

function saveTokens(tokens) {
  localStorage.setItem('rv_tokens', JSON.stringify(tokens))
}

function clearTokens() {
  localStorage.removeItem('rv_tokens')
}

// Inject access token
api.interceptors.request.use(config => {
  const tokens = getTokens()
  if (tokens?.access_token) {
    config.headers.Authorization = `Bearer ${tokens.access_token}`
  }
  return config
})

// Auto-refresh on 401
let _refreshing = null
api.interceptors.response.use(
  res => res,
  async err => {
    const original = err.config
    if (err.response?.status === 401 && !original._retry) {
      original._retry = true
      const tokens = getTokens()
      if (tokens?.refresh_token) {
        if (!_refreshing) {
          _refreshing = axios.post('/api/auth/refresh', { refresh_token: tokens.refresh_token })
            .then(r => {
              const newTokens = { ...tokens, ...r.data }
              saveTokens(newTokens)
              _refreshing = null
              return newTokens.access_token
            })
            .catch(() => { clearTokens(); _refreshing = null; window.location.href = '/login' })
        }
        const newAccessToken = await _refreshing
        if (newAccessToken) {
          original.headers.Authorization = `Bearer ${newAccessToken}`
          return api(original)
        }
      } else {
        clearTokens()
        window.location.href = '/login'
      }
    }
    return Promise.reject(err)
  }
)

export { saveTokens, clearTokens, getTokens }

// ─── Auth ─────────────────────────────────────────────────────────────────────

export const register = (name, email, password) =>
  api.post('/auth/register', { name, email, password }).then(r => r.data)

export const login = (email, password) =>
  api.post('/auth/login', { email, password }).then(r => r.data)

export const storeLogin = (slug, email, password) =>
  api.post(`/store/${slug}/auth/login`, { email, password }).then(r => r.data)

export const refreshTokens = (refresh_token) =>
  api.post('/auth/refresh', { refresh_token }).then(r => r.data)

export const logout = (refresh_token) =>
  api.post('/auth/logout', { refresh_token }).then(r => r.data)

export const forgotPassword = (email) =>
  api.post('/auth/forgot-password', { email }).then(r => r.data)

export const resetPassword = (token, new_password) =>
  api.post('/auth/reset-password', { token, new_password }).then(r => r.data)

export const acceptInvite = (slug, token, name, password) =>
  api.post(`/store/${slug}/accept-invite`, { token, name, password }).then(r => r.data)

// ─── Stores ──────────────────────────────────────────────────────────────────

export const listStores = () =>
  api.get('/stores').then(r => r.data)

export const createStore = (body) =>
  api.post('/stores', body).then(r => r.data)

export const getStore = (slug) =>
  api.get(`/store/${slug}`).then(r => r.data)

export const patchStore = (slug, body) =>
  api.patch(`/store/${slug}`, body).then(r => r.data)

export const deleteStore = (slug) =>
  api.delete(`/store/${slug}`).then(r => r.data)

export const getMe = (slug) =>
  api.get(`/store/${slug}/me`).then(r => r.data)

// ─── Members ─────────────────────────────────────────────────────────────────

export const listMembers = (slug) =>
  api.get(`/store/${slug}/members`).then(r => r.data)

export const inviteMember = (slug, body) =>
  api.post(`/store/${slug}/members/invite`, body).then(r => r.data)

export const listInvitations = (slug) =>
  api.get(`/store/${slug}/members/invitations`).then(r => r.data)

export const cancelInvitation = (slug, invitationId) =>
  api.delete(`/store/${slug}/members/invitations/${invitationId}`).then(r => r.data)

export const patchMember = (slug, memberId, body) =>
  api.patch(`/store/${slug}/members/${memberId}`, body).then(r => r.data)

export const removeMember = (slug, memberId) =>
  api.delete(`/store/${slug}/members/${memberId}`).then(r => r.data)

// ─── Sections ────────────────────────────────────────────────────────────────

export const listSections = (slug) =>
  api.get(`/store/${slug}/sections`).then(r => r.data)

export const createSection = (slug, body) =>
  api.post(`/store/${slug}/sections`, body).then(r => r.data)

export const patchSection = (slug, sectionId, body) =>
  api.patch(`/store/${slug}/sections/${sectionId}`, body).then(r => r.data)

export const deleteSection = (slug, sectionId) =>
  api.delete(`/store/${slug}/sections/${sectionId}`).then(r => r.data)

// ─── Config Versions (read-only) ─────────────────────────────────────────────

export const getActiveVersion = (slug) =>
  api.get(`/store/${slug}/versions/active`).then(r => r.data)

export const listVersions = (slug) =>
  api.get(`/store/${slug}/versions`).then(r => r.data)

// ─── Cameras (physical) ──────────────────────────────────────────────────────

export const listCameras = (slug) =>
  api.get(`/store/${slug}/cameras`).then(r => r.data)

export const createCamera = (slug, body) =>
  api.post(`/store/${slug}/cameras`, body).then(r => r.data)

export const patchCamera = (slug, cameraId, body) =>
  api.patch(`/store/${slug}/cameras/${cameraId}`, body).then(r => r.data)

export const deleteCamera = (slug, cameraId) =>
  api.delete(`/store/${slug}/cameras/${cameraId}`).then(r => r.data)

// ── DEV-ONLY pipeline control (DEBUG_MODE endpoints) ────────────────────────
export const devPipelineStart = (body) =>
  api.post('/debug/dev/pipeline/start', body).then(r => r.data)

export const devPipelineStop = (body) =>
  api.post('/debug/dev/pipeline/stop', body).then(r => r.data)

export const getDevTracking = (cameraId, limit = 50) =>
  api.get('/debug/dev/tracking', { params: { camera_id: cameraId, limit } }).then(r => r.data)

export const getDevIep3 = (storeId, limit = 50) =>
  api.get('/debug/dev/iep3', { params: { store_id: storeId, limit } }).then(r => r.data)

export const getDevGpuStatus = () =>
  api.get('/debug/dev/gpu-status').then(r => r.data)

// ─── Draft lifecycle ──────────────────────────────────────────────────────────

export const getDraft = (slug) =>
  api.get(`/store/${slug}/versions/draft`).then(r => r.data)

export const createDraft = (slug, label, cloneFromActive = false) =>
  api.post(`/store/${slug}/versions/draft`, { label, clone_from_active: cloneFromActive }).then(r => r.data)

export const deleteDraft = (slug) =>
  api.delete(`/store/${slug}/versions/draft`).then(r => r.data)

// ─── Floor Plan ───────────────────────────────────────────────────────────────

export const uploadFloorPlan = (slug, sectionId, file) => {
  const fd = new FormData()
  fd.append('file', file)
  return api.post(`/store/${slug}/draft/sections/${sectionId}/floor-plan/upload`, fd).then(r => r.data)
}

export const getDraftFloorPlan = (slug, sectionId) =>
  api.get(`/store/${slug}/draft/sections/${sectionId}/floor-plan`).then(r => r.data)

export const setFloorPlanScale = (slug, sectionId, body) =>
  api.put(`/store/${slug}/draft/sections/${sectionId}/floor-plan/scale`, body).then(r => r.data)

export const setFloorPlanWorldBounds = (slug, sectionId, body) =>
  api.put(`/store/${slug}/draft/sections/${sectionId}/floor-plan/world-bounds`, body).then(r => r.data)

// ─── Zones ────────────────────────────────────────────────────────────────────

export const getDraftZones = (slug, sectionId) =>
  api.get(`/store/${slug}/draft/sections/${sectionId}/zones`).then(r => r.data)

export const createZone = (slug, sectionId, body) =>
  api.post(`/store/${slug}/draft/sections/${sectionId}/zones`, body).then(r => r.data)

export const updateZone = (slug, sectionId, zoneId, body) =>
  api.put(`/store/${slug}/draft/sections/${sectionId}/zones/${zoneId}`, body).then(r => r.data)

export const deleteZone = (slug, sectionId, zoneId) =>
  api.delete(`/store/${slug}/draft/sections/${sectionId}/zones/${zoneId}`).then(r => r.data)

// ─── Obstacles ────────────────────────────────────────────────────────────────

export const getDraftObstacles = (slug, sectionId) =>
  api.get(`/store/${slug}/draft/sections/${sectionId}/obstacles`).then(r => r.data)

export const createObstacle = (slug, sectionId, body) =>
  api.post(`/store/${slug}/draft/sections/${sectionId}/obstacles`, body).then(r => r.data)

export const updateObstacle = (slug, sectionId, obstacleId, body) =>
  api.put(`/store/${slug}/draft/sections/${sectionId}/obstacles/${obstacleId}`, body).then(r => r.data)

export const deleteObstacle = (slug, sectionId, obstacleId) =>
  api.delete(`/store/${slug}/draft/sections/${sectionId}/obstacles/${obstacleId}`).then(r => r.data)

// ─── Camera Configs ───────────────────────────────────────────────────────────

export const getDraftCameraConfigs = (slug, sectionId) =>
  api.get(`/store/${slug}/draft/sections/${sectionId}/camera-configs`).then(r => r.data)

export const placeCameraConfig = (slug, sectionId, body) =>
  api.post(`/store/${slug}/draft/sections/${sectionId}/camera-configs`, body).then(r => r.data)

export const updateCameraConfig = (slug, configId, body) =>
  api.put(`/store/${slug}/draft/camera-configs/${configId}`, body).then(r => r.data)

export const deleteCameraConfig = (slug, configId) =>
  api.delete(`/store/${slug}/draft/camera-configs/${configId}`).then(r => r.data)

export const uploadCameraFrame = (slug, configId, file) => {
  const fd = new FormData()
  fd.append('file', file)
  return api.post(`/store/${slug}/draft/camera-configs/${configId}/frame`, fd).then(r => r.data)
}

// ─── Calibration ──────────────────────────────────────────────────────────────

export const computeHomography = (slug, configId, correspondences) =>
  api.post(`/store/${slug}/draft/camera-configs/${configId}/calibration/homography`, { correspondences }).then(r => r.data)

export const uploadCalibrationFiles = (slug, configId, intrinsicFile, extrinsicFile) => {
  const fd = new FormData()
  fd.append('intrinsic', intrinsicFile)
  if (extrinsicFile) fd.append('extrinsic', extrinsicFile)
  return api.post(`/store/${slug}/draft/camera-configs/${configId}/calibration/files`, fd).then(r => r.data)
}

export const verifyCalibration = (slug, configId) =>
  api.post(`/store/${slug}/draft/camera-configs/${configId}/calibration/verify`).then(r => r.data)

export const getCalibrations = (slug, configId) =>
  api.get(`/store/${slug}/draft/camera-configs/${configId}/calibrations`).then(r => r.data)

// ─── Activation ───────────────────────────────────────────────────────────────

export const activateDraft = (slug, body) =>
  api.post(`/store/${slug}/versions/draft/activate`, body).then(r => r.data)

export const reactivateVersion = (slug, versionId) =>
  api.post(`/store/${slug}/versions/${versionId}/reactivate`).then(r => r.data)

export const getSyncEvent = (slug, eventId) =>
  api.get(`/store/${slug}/versions/sync/${eventId}`).then(r => r.data)

export const requestDraftDiscard = (slug) =>
  api.post(`/store/${slug}/members/draft-discard-request`).then(r => r.data)

// ─── Live Monitoring (Phase 5+) ──────────────────────────────────────────────

export const getLiveSummary = (slug) =>
  api.get(`/store/${slug}/live/summary`).then(r => r.data)

export const getActiveAlerts = (slug) =>
  api.get(`/store/${slug}/alerts/active`).then(r => r.data)

export const resolveAlert = (slug, alertId) =>
  api.post(`/store/${slug}/alerts/${alertId}/resolve`).then(r => r.data)

// ─── Analytics (Phase 6+) ────────────────────────────────────────────────────

export const getHeatmap = (slug, params) =>
  api.get(`/store/${slug}/analytics/heatmap`, { params }).then(r => r.data)

export const getZoneTraffic = (slug, params) =>
  api.get(`/store/${slug}/analytics/zone-traffic`, { params }).then(r => r.data)

export const getTrends = (slug, params) =>
  api.get(`/store/${slug}/analytics/trends`, { params }).then(r => r.data)

// ─── Employees (Phase 4+) ────────────────────────────────────────────────────

export const listEmployees = (slug, params) =>
  api.get(`/store/${slug}/employees`, { params }).then(r => r.data)

export const createEmployee = (slug, body) =>
  api.post(`/store/${slug}/employees`, body).then(r => r.data)

export const patchEmployee = (slug, employeeId, body) =>
  api.patch(`/store/${slug}/employees/${employeeId}`, body).then(r => r.data)

export const deleteEmployee = (slug, employeeId) =>
  api.delete(`/store/${slug}/employees/${employeeId}`).then(r => r.data)

export const listEmployeeSections = (slug, employeeId) =>
  api.get(`/store/${slug}/employees/${employeeId}/sections`).then(r => r.data)

export const assignEmployeeSection = (slug, employeeId, body) =>
  api.post(`/store/${slug}/employees/${employeeId}/sections`, body).then(r => r.data)

export const removeEmployeeSection = (slug, employeeId, sectionId) =>
  api.delete(`/store/${slug}/employees/${employeeId}/sections/${sectionId}`).then(r => r.data)

// ─── Shift Patterns (Phase 4+) ───────────────────────────────────────────────

export const listShiftPatterns = (slug, params) =>
  api.get(`/store/${slug}/shift-patterns`, { params }).then(r => r.data)

export const createShiftPattern = (slug, body) =>
  api.post(`/store/${slug}/shift-patterns`, body).then(r => r.data)

export const patchShiftPattern = (slug, patternId, body) =>
  api.patch(`/store/${slug}/shift-patterns/${patternId}`, body).then(r => r.data)

export const deleteShiftPattern = (slug, patternId) =>
  api.delete(`/store/${slug}/shift-patterns/${patternId}`).then(r => r.data)

// ─── Shift Instances (Phase 4+) ──────────────────────────────────────────────

export const listShifts = (slug, params) =>
  api.get(`/store/${slug}/shifts`, { params }).then(r => r.data)

export const createShift = (slug, body) =>
  api.post(`/store/${slug}/shifts`, body).then(r => r.data)

export const getShift = (slug, shiftId) =>
  api.get(`/store/${slug}/shifts/${shiftId}`).then(r => r.data)

export const patchShift = (slug, shiftId, body) =>
  api.patch(`/store/${slug}/shifts/${shiftId}`, body).then(r => r.data)

export const deleteShift = (slug, shiftId) =>
  api.delete(`/store/${slug}/shifts/${shiftId}`).then(r => r.data)

export const generateShifts = (slug, body) =>
  api.post(`/store/${slug}/shifts/generate`, body).then(r => r.data)

// ─── Shift Assignments (Phase 4+) ────────────────────────────────────────────

export const listShiftAssignments = (slug, shiftId) =>
  api.get(`/store/${slug}/shifts/${shiftId}/assignments`).then(r => r.data)

export const createShiftAssignment = (slug, shiftId, body) =>
  api.post(`/store/${slug}/shifts/${shiftId}/assignments`, body).then(r => r.data)

export const patchShiftAssignment = (slug, shiftId, assignmentId, body) =>
  api.patch(`/store/${slug}/shifts/${shiftId}/assignments/${assignmentId}`, body).then(r => r.data)

export const deleteShiftAssignment = (slug, shiftId, assignmentId) =>
  api.delete(`/store/${slug}/shifts/${shiftId}/assignments/${assignmentId}`).then(r => r.data)

// ─── Break Records (Phase 4+) ────────────────────────────────────────────────

export const listBreaks = (slug, shiftId, assignmentId) =>
  api.get(`/store/${slug}/shifts/${shiftId}/assignments/${assignmentId}/breaks`).then(r => r.data)

export const createBreak = (slug, shiftId, assignmentId, body) =>
  api.post(`/store/${slug}/shifts/${shiftId}/assignments/${assignmentId}/breaks`, body).then(r => r.data)

export const patchBreak = (slug, shiftId, assignmentId, breakId, body) =>
  api.patch(`/store/${slug}/shifts/${shiftId}/assignments/${assignmentId}/breaks/${breakId}`, body).then(r => r.data)

export const deleteBreak = (slug, shiftId, assignmentId, breakId) =>
  api.delete(`/store/${slug}/shifts/${shiftId}/assignments/${assignmentId}/breaks/${breakId}`).then(r => r.data)

// ─── Settings (Phase 7+) ─────────────────────────────────────────────────────

export const getSettings = (slug) =>
  api.get(`/store/${slug}/settings`).then(r => r.data)

export const patchSettings = (slug, body) =>
  api.patch(`/store/${slug}/settings`, body).then(r => r.data)

export const getAlertConfig = (slug) =>
  api.get(`/store/${slug}/alert-config`).then(r => r.data)

export const patchAlertConfig = (slug, body) =>
  api.patch(`/store/${slug}/alert-config`, body).then(r => r.data)

// ─── Audit (Phase 7+) ────────────────────────────────────────────────────────

export const getAuditLog = (slug, params) =>
  api.get(`/store/${slug}/audit`, { params }).then(r => r.data)

export default api
