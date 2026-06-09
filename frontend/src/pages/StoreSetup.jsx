import React, { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { usePageTitle } from '../components/PageMeta'
import { useAuth } from '../store'
import {
  getActiveVersion, listVersions, reactivateVersion, getDraft,
  getCameraHealth, getOperatingHours, getActivePunchStation, listAlertRules,
} from '../api'
import FloorMap from '../components/store/FloorMap'
import CamerasPanel from '../components/store/CamerasPanel'
import ZonesPanel from '../components/store/ZonesPanel'
import SchedulePanel from '../components/store/SchedulePanel'
import PunchPanel from '../components/store/PunchPanel'
import VersionHistory from '../components/store/VersionHistory'
import EditMenu from '../components/store/EditMenu'
import ScheduleEditor from '../components/store/ScheduleEditor'

export default function StoreSetup() {
  const { slug } = useParams()
  const navigate = useNavigate()
  const { state } = useAuth()
  usePageTitle('Store Setup')

  // Edits are owner/manager only (admin via A1); the read view is open to members.
  const canEdit = !!state.user?.is_super_admin
    || state.user?.account_type === 'owner'
    || state.currentMember?.role === 'manager'
    || state.currentMember?.is_owner

  const [loading, setLoading] = useState(true)
  const [version, setVersion] = useState(null)
  const [versions, setVersions] = useState([])
  const [draft, setDraft] = useState(null)
  // Optional deps — each degrades gracefully to null if its endpoint is absent.
  const [cameraHealth, setCameraHealth] = useState(null)
  const [hours, setHours] = useState(null)
  const [punch, setPunch] = useState(null)
  const [rules, setRules] = useState(null)
  const [restoringId, setRestoringId] = useState(null)
  const [error, setError] = useState(null)
  const [showSchedule, setShowSchedule] = useState(false)

  function reload() {
    setLoading(true)
    Promise.all([
      getActiveVersion(slug).catch(() => null),
      listVersions(slug).catch(() => []),
      getDraft(slug).catch(() => null),
    ]).then(([v, vs, d]) => { setVersion(v); setVersions(vs); setDraft(d); setLoading(false) })

    // Optional — never block the page; missing dependency just omits its data.
    getCameraHealth(slug).then(setCameraHealth).catch(() => setCameraHealth(null))
    getOperatingHours(slug).then(setHours).catch(() => setHours(null))
    getActivePunchStation(slug).then(setPunch).catch(() => setPunch(null)) // 404 = not configured
    listAlertRules(slug).then(setRules).catch(() => setRules(null))
  }

  useEffect(() => { reload() }, [slug])

  async function handleRestore(versionId) {
    if (!window.confirm('Restore this version as active? The current active version will be archived.')) return
    setRestoringId(versionId)
    try {
      await reactivateVersion(slug, versionId)
      reload()
    } catch (err) {
      const status = err?.response?.status
      const detail = err?.response?.data?.detail
      setError(status === 409
        ? 'Cannot restore: a draft configuration already exists. Discard the current draft first.'
        : (typeof detail === 'object' ? detail?.error : detail) || err.message || 'Failed to restore version.')
    } finally {
      setRestoringId(null)
    }
  }

  if (loading) {
    return (
      <div className="p-6 space-y-4 max-w-5xl">
        <div className="skeleton h-8 w-48" />
        <div className="skeleton h-64 w-full rounded-xl" />
        <div className="skeleton h-32 w-full rounded-xl" />
      </div>
    )
  }

  if (!version) {
    return (
      <div className="page-enter flex flex-col h-full">
        <header className="px-6 py-4 border-b border-gray-200 bg-white shrink-0 flex items-center justify-between">
          <div>
            <h1 className="page-title">Store Setup</h1>
            <p className="page-subtitle">No active configuration yet</p>
          </div>
          {canEdit && (
            <button onClick={() => navigate(`/store/${slug}/config/edit`)} className="btn-primary">
              {draft ? 'Resume Setup' : 'Start Onboarding'}
            </button>
          )}
        </header>
        <div className="flex-1 p-6">
          <div className="bg-white border border-gray-200 rounded-xl p-8 text-center text-sm text-gray-500 max-w-2xl">
            This store has no active configuration.{canEdit ? ' Start onboarding to map the floor, draw zones, and place cameras.' : ' Ask an owner or manager to run onboarding.'}
          </div>
        </div>
      </div>
    )
  }

  const fp = version.floor_plan
  const ppm = fp?.pixels_per_meter
  const zones = version.zones || []
  const cameras = version.camera_configs || []

  // Live camera status keyed by physical_camera_id (F2) — null if unavailable.
  const cameraStatusById = cameraHealth
    ? Object.fromEntries(cameraHealth.cameras.map((c) => [c.physical_camera_id, c]))
    : null

  // Per-zone alert-rule counts (CAT D) — null if unavailable.
  let ruleCounts = null
  if (Array.isArray(rules)) {
    ruleCounts = {}
    for (const r of rules) for (const z of r.zones || []) ruleCounts[z.id] = (ruleCounts[z.id] || 0) + 1
  }

  return (
    <div className="page-enter flex flex-col h-full overflow-auto">
      <header className="px-6 py-4 border-b border-gray-200 bg-white shrink-0 flex items-center justify-between gap-3">
        <div>
          <h1 className="page-title">Store Setup</h1>
          <p className="page-subtitle">
            Active version{version.label ? `: ${version.label}` : ''} · Since{' '}
            {version.active_from ? new Date(version.active_from).toLocaleDateString() : '—'} · Read-only
          </p>
        </div>
        <div className="flex items-center gap-2">
          {draft && (
            <span className="text-xs text-amber-700 bg-amber-50 border border-amber-200 px-2.5 py-1 rounded-lg">Draft in progress</span>
          )}
          {canEdit && (
            <EditMenu
              hasActiveVersion={!!version}
              hasDraft={!!draft}
              onSchedule={() => setShowSchedule(true)}
              onPunch={() => navigate(`/store/${slug}/config/punch`)}
              onWizard={() => navigate(`/store/${slug}/config/edit`)}
              onResumeDraft={() => navigate(`/store/${slug}/config/edit`)}
            />
          )}
        </div>
      </header>

      <div className="flex-1 p-6 space-y-6">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-1 space-y-4">
            <CamerasPanel cameras={cameras} cameraStatusById={cameraStatusById} />
            <ZonesPanel zones={zones} ppm={ppm} ruleCounts={ruleCounts} />
            <SchedulePanel hours={hours} />
            <PunchPanel punch={punch} />
          </div>

          <div className="lg:col-span-2 bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-gray-700">Floor Map</h3>
              {fp?.scale_defined && (
                <span className="text-xs text-gray-400 bg-gray-50 px-2 py-0.5 rounded border border-gray-200">
                  {ppm?.toFixed(1)} px/m
                </span>
              )}
            </div>
            <FloorMap
              floorPlan={fp}
              zones={zones}
              obstacles={version.obstacles || []}
              cameraConfigs={cameras}
              punch={punch}
              cameraStatusById={cameraStatusById || {}}
            />
          </div>
        </div>

        <VersionHistory
          versions={versions}
          onRestore={canEdit ? handleRestore : null}
          restoringId={restoringId}
          error={error}
          onClearError={() => setError(null)}
        />
      </div>

      {showSchedule && (
        <ScheduleEditor
          hours={hours}
          slug={slug}
          onClose={() => setShowSchedule(false)}
          onSaved={() => { setShowSchedule(false); getOperatingHours(slug).then(setHours).catch(() => {}) }}
        />
      )}
    </div>
  )
}
