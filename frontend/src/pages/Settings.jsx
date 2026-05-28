import React, { useEffect, useState, useCallback, useRef } from 'react'
import { useParams } from 'react-router-dom'
import { Cpu, Bell, AlertTriangle } from 'lucide-react'
import { useAuth } from '../store'
import { getSettings, patchSettings, getAlertConfig, patchAlertConfig } from '../api'
import { usePageTitle } from '../components/PageMeta'
import { FormSkeleton } from '../components/Skeletons'

// ── Sub-components ────────────────────────────────────────────────────────────

function UnitBadge({ unit }) {
  return (
    <span className="ml-2 text-xs font-medium text-gray-400 bg-gray-100 px-2 py-0.5 rounded-md whitespace-nowrap">
      {unit}
    </span>
  )
}

function NumberInput({ value, onChange, min, max, unit }) {
  return (
    <div className="flex items-center">
      <input
        type="number"
        value={value}
        onChange={e => onChange(Number(e.target.value))}
        min={min}
        max={max}
        className="w-24 border border-gray-200 rounded-lg px-3 py-1.5 text-sm text-center font-mono focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 transition-shadow"
      />
      {unit && <UnitBadge unit={unit} />}
    </div>
  )
}

function FieldRow({ label, description, children }) {
  return (
    <div className="flex items-center gap-4 py-4 border-b border-gray-50 last:border-0">
      {/* Left: 60% */}
      <div style={{ flex: '0 0 60%' }}>
        <p className="text-sm font-medium text-gray-800">{label}</p>
        {description && (
          <p className="text-sm text-gray-400 italic mt-0.5 leading-snug">{description}</p>
        )}
      </div>
      {/* Right: 40% */}
      <div style={{ flex: '0 0 40%' }} className="flex justify-end">
        {children}
      </div>
    </div>
  )
}

function Section({ title, description, icon: Icon, iconColor, children }) {
  return (
    <div
      className="bg-white border border-gray-100 rounded-xl shadow-sm overflow-hidden mb-6"
      style={{ borderTop: '4px solid #3b82f6' }}
    >
      <div className="px-6 py-5 border-b border-gray-100 flex items-center gap-3">
        <div
          className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
          style={{ backgroundColor: `${iconColor}18` }}
        >
          <Icon size={18} style={{ color: iconColor }} />
        </div>
        <div>
          <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
          {description && <p className="text-xs text-gray-400 mt-0.5">{description}</p>}
        </div>
      </div>
      <div className="px-6">{children}</div>
    </div>
  )
}

// ── Sticky save bar ───────────────────────────────────────────────────────────

function StickyBar({ dirty, saving, onSave, onDiscard }) {
  return (
    <div
      className="fixed bottom-0 left-0 right-0 z-40 transition-transform duration-300 ease-out"
      style={{ transform: dirty ? 'translateY(0)' : 'translateY(100%)' }}
    >
      <div className="bg-white border-t border-gray-200 shadow-[0_-4px_16px_rgba(0,0,0,0.08)] px-6 py-3.5 flex items-center justify-between">
        <div className="flex items-center gap-2 text-amber-600">
          <AlertTriangle size={15} />
          <span className="text-sm font-medium">You have unsaved changes</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={onDiscard}
            disabled={saving}
            className="btn-outline py-1.5 text-xs disabled:opacity-40"
          >
            Discard
          </button>
          <button
            onClick={onSave}
            disabled={saving}
            className="btn-primary py-1.5 text-xs disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save changes'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Default values ────────────────────────────────────────────────────────────

const DEFAULT_SETTINGS = {
  chunk_duration_sec: 300,
  chunk_overlap_sec: 30,
  frame_sample_rate_fps: 5,
  activation_countdown_sec: 60,
  active_config_cache_ttl_sec: 300,
  shift_start_grace_min: 15,
  absence_threshold_min: 15,
}

// Shallow-equal two plain objects
function shallowEq(a, b) {
  if (!a || !b) return a === b
  return Object.keys(a).every(k => a[k] === b[k])
}

// Keys that belong to each section (for dirty comparison)
const SETTINGS_KEYS = [
  'activation_countdown_sec', 'chunk_duration_sec', 'chunk_overlap_sec',
  'frame_sample_rate_fps', 'active_config_cache_ttl_sec',
]
const ALERTS_KEYS = [
  'shift_start_grace_min', 'absence_threshold_min', 'queue_people_threshold',
  'queue_wait_min_threshold', 'queue_alert_cooldown_min',
]

function pick(obj, keys) {
  if (!obj) return null
  return Object.fromEntries(keys.map(k => [k, obj[k]]))
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Settings() {
  const { slug } = useParams()
  const { state } = useAuth()
  const role = state.currentMember?.role || (state.user?.account_type === 'owner' ? 'owner' : null)
  usePageTitle('Settings')

  const [settings, setSettings] = useState(null)
  const [alertConfig, setAlertConfig] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(null) // 'settings' | 'alerts' | null
  const [restored, setRestored] = useState(null)
  const [error, setError] = useState('')

  // Snapshots of the last saved server values — used to compute dirty state
  const savedSettings = useRef(null)
  const savedAlerts = useRef(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [s, a] = await Promise.all([getSettings(slug), getAlertConfig(slug)])
      setSettings(s)
      setAlertConfig(a)
      savedSettings.current = s
      savedAlerts.current = a
    } catch (err) {
      setError(err.response?.data?.detail?.error || 'Failed to load settings')
    } finally {
      setLoading(false)
    }
  }, [slug])

  useEffect(() => { fetchData() }, [fetchData])

  // Dirty flags — compare current state slices to saved snapshots
  const settingsDirty = !shallowEq(
    pick(settings, SETTINGS_KEYS),
    pick(savedSettings.current, SETTINGS_KEYS)
  )
  const alertsDirty = !shallowEq(
    pick(alertConfig, ALERTS_KEYS),
    pick(savedAlerts.current, ALERTS_KEYS)
  )
  const anyDirty = settingsDirty || alertsDirty

  // Which section's save to call from the unified bar
  const activeSavingSection = settingsDirty ? 'settings' : 'alerts'

  async function handleSaveSettings() {
    setSaving('settings')
    setError('')
    try {
      const updated = await patchSettings(slug, {
        activation_countdown_sec: settings.activation_countdown_sec,
        chunk_duration_sec: settings.chunk_duration_sec,
        chunk_overlap_sec: settings.chunk_overlap_sec,
        frame_sample_rate_fps: settings.frame_sample_rate_fps,
        active_config_cache_ttl_sec: settings.active_config_cache_ttl_sec,
      })
      setSettings(updated)
      savedSettings.current = updated
    } catch (err) {
      setError(err.response?.data?.detail?.error || 'Failed to save settings')
    } finally {
      setSaving(null)
    }
  }

  async function handleSaveAlerts() {
    setSaving('alerts')
    setError('')
    try {
      const updated = await patchAlertConfig(slug, {
        shift_start_grace_min: alertConfig.shift_start_grace_min,
        absence_threshold_min: alertConfig.absence_threshold_min,
        queue_people_threshold: alertConfig.queue_people_threshold,
        queue_wait_min_threshold: alertConfig.queue_wait_min_threshold,
        queue_alert_cooldown_min: alertConfig.queue_alert_cooldown_min,
      })
      setAlertConfig(updated)
      savedAlerts.current = updated
    } catch (err) {
      setError(err.response?.data?.detail?.error || 'Failed to save alert config')
    } finally {
      setSaving(null)
    }
  }

  async function handleSaveAll() {
    if (settingsDirty) await handleSaveSettings()
    if (alertsDirty) await handleSaveAlerts()
  }

  function handleDiscard() {
    if (settingsDirty && savedSettings.current) setSettings({ ...savedSettings.current })
    if (alertsDirty && savedAlerts.current) setAlertConfig({ ...savedAlerts.current })
    setRestored(null)
  }

  function updateSettings(field, value) {
    setSettings(s => ({ ...s, [field]: value }))
  }

  function updateAlert(field, value) {
    setAlertConfig(a => ({ ...a, [field]: value }))
  }

  function resetSettings() {
    setSettings(s => ({
      ...s,
      chunk_duration_sec: DEFAULT_SETTINGS.chunk_duration_sec,
      chunk_overlap_sec: DEFAULT_SETTINGS.chunk_overlap_sec,
      frame_sample_rate_fps: DEFAULT_SETTINGS.frame_sample_rate_fps,
      activation_countdown_sec: DEFAULT_SETTINGS.activation_countdown_sec,
      active_config_cache_ttl_sec: DEFAULT_SETTINGS.active_config_cache_ttl_sec,
    }))
    setRestored('settings')
    setTimeout(() => setRestored(null), 3000)
  }

  function resetAlerts() {
    setAlertConfig(a => ({
      ...a,
      shift_start_grace_min: DEFAULT_SETTINGS.shift_start_grace_min,
      absence_threshold_min: DEFAULT_SETTINGS.absence_threshold_min,
    }))
    setRestored('alerts')
    setTimeout(() => setRestored(null), 3000)
  }

  if (role === 'viewer') {
    return (
      <div className="flex flex-col items-center justify-center h-full text-gray-400">
        <p className="text-lg font-medium text-gray-500">Access Restricted</p>
        <p className="text-sm mt-1">You don't have permission to view settings.</p>
      </div>
    )
  }

  return (
    // pb-20 leaves room so the sticky bar never covers content
    <div className="page-enter flex flex-col h-full overflow-auto pb-20">
      <header className="px-6 py-4 border-b border-gray-200 bg-white shrink-0">
        <h1 className="page-title">Settings</h1>
        <p className="page-subtitle">Store configuration and alert thresholds</p>
      </header>

      <div className="flex-1 p-6 max-w-2xl">
        {error && (
          <div className="bg-red-50 text-red-700 text-sm px-4 py-3 rounded-lg border border-red-200 mb-4">{error}</div>
        )}

        {loading ? (
          <FormSkeleton rows={2} />
        ) : (
          <>
            {/* Processing Settings */}
            <Section
              title="Processing Settings"
              description="Controls video chunk processing and frame sampling behaviour"
              icon={Cpu}
              iconColor="#3b82f6"
            >
              <FieldRow label="Activation countdown" description="Delay before a new config goes live after activation">
                <NumberInput value={settings.activation_countdown_sec} onChange={v => updateSettings('activation_countdown_sec', v)} min={10} max={3600} unit="seconds" />
              </FieldRow>
              <FieldRow label="Chunk duration" description="Length of each video processing chunk">
                <NumberInput value={settings.chunk_duration_sec} onChange={v => updateSettings('chunk_duration_sec', v)} min={30} max={3600} unit="seconds" />
              </FieldRow>
              <FieldRow label="Chunk overlap" description="Overlap between consecutive chunks to avoid missed frames">
                <NumberInput value={settings.chunk_overlap_sec} onChange={v => updateSettings('chunk_overlap_sec', v)} min={0} max={300} unit="seconds" />
              </FieldRow>
              <FieldRow label="Frame sample rate" description="Frames per second to sample from the video stream">
                <NumberInput value={settings.frame_sample_rate_fps} onChange={v => updateSettings('frame_sample_rate_fps', v)} min={1} max={30} unit="fps" />
              </FieldRow>
              <FieldRow label="Config cache TTL" description="How long the active config is cached before re-fetching">
                <NumberInput value={settings.active_config_cache_ttl_sec} onChange={v => updateSettings('active_config_cache_ttl_sec', v)} min={10} max={86400} unit="seconds" />
              </FieldRow>

              <div className="py-4 flex items-center justify-between gap-3">
                <div>
                  {restored === 'settings' && (
                    <span className="text-xs text-amber-600 font-medium">Defaults restored — save to apply.</span>
                  )}
                </div>
                <button onClick={resetSettings} className="btn-outline text-xs py-1.5">
                  Reset to defaults
                </button>
              </div>
            </Section>

            {/* Alert Thresholds */}
            <Section
              title="Alert Thresholds"
              description="Conditions that trigger operational alerts for this store"
              icon={Bell}
              iconColor="#f59e0b"
            >
              <FieldRow label="Shift start grace period" description="How late an employee can clock in before triggering an absence alert">
                <NumberInput value={alertConfig.shift_start_grace_min} onChange={v => updateAlert('shift_start_grace_min', v)} min={0} max={120} unit="minutes" />
              </FieldRow>
              <FieldRow label="Absence threshold" description="Minutes without detection before an employee is marked absent">
                <NumberInput value={alertConfig.absence_threshold_min} onChange={v => updateAlert('absence_threshold_min', v)} min={1} max={120} unit="minutes" />
              </FieldRow>
              <FieldRow label="Queue size threshold" description="Number of people in a queue that triggers an alert">
                <NumberInput value={alertConfig.queue_people_threshold} onChange={v => updateAlert('queue_people_threshold', v)} min={1} max={500} unit="people" />
              </FieldRow>
              <FieldRow label="Queue wait threshold" description="Wait time before a queue alert is raised">
                <NumberInput value={alertConfig.queue_wait_min_threshold} onChange={v => updateAlert('queue_wait_min_threshold', v)} min={1} max={120} unit="minutes" />
              </FieldRow>
              <FieldRow label="Alert cooldown" description="Minimum time between repeated queue alerts">
                <NumberInput value={alertConfig.queue_alert_cooldown_min} onChange={v => updateAlert('queue_alert_cooldown_min', v)} min={1} max={120} unit="minutes" />
              </FieldRow>

              <div className="py-4 flex items-center justify-between gap-3">
                <div>
                  {restored === 'alerts' && (
                    <span className="text-xs text-amber-600 font-medium">Defaults restored — save to apply.</span>
                  )}
                </div>
                <button onClick={resetAlerts} className="btn-outline text-xs py-1.5">
                  Reset to defaults
                </button>
              </div>
            </Section>
          </>
        )}
      </div>

      {/* Sticky unsaved-changes bar */}
      <StickyBar
        dirty={anyDirty}
        saving={saving !== null}
        onSave={handleSaveAll}
        onDiscard={handleDiscard}
      />
    </div>
  )
}
