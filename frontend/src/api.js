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

// ─── Sections (Phase 2+) ─────────────────────────────────────────────────────

export const listSections = (slug) =>
  api.get(`/store/${slug}/sections`).then(r => r.data)

// ─── Config Versions (Phase 2+) ──────────────────────────────────────────────

export const getActiveVersion = (slug) =>
  api.get(`/store/${slug}/versions/active`).then(r => r.data)

export const listVersions = (slug) =>
  api.get(`/store/${slug}/versions`).then(r => r.data)

// ─── Cameras (Phase 2+) ──────────────────────────────────────────────────────

export const listCameras = (slug) =>
  api.get(`/store/${slug}/cameras`).then(r => r.data)

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

// ─── Settings (Phase 7+) ─────────────────────────────────────────────────────

export const getSettings = (slug) =>
  api.get(`/store/${slug}/settings`).then(r => r.data)

export const patchSettings = (slug, body) =>
  api.patch(`/store/${slug}/settings`, body).then(r => r.data)

// ─── Audit (Phase 7+) ────────────────────────────────────────────────────────

export const getAuditLog = (slug, params) =>
  api.get(`/store/${slug}/audit`, { params }).then(r => r.data)

export default api
