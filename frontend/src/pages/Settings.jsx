import React, { useEffect, useState, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { useAuth } from '../store'
import { getSettings, patchSettings, getAlertConfig, patchAlertConfig } from '../api'

function FieldRow({ label, description, children }) {
  return (
    <div className="flex items-start justify-between gap-6 py-4 border-b border-gray-100 last:border-0">
      <div className="min-w-0">
        <p className="text-sm font-medium text-gray-900">{label}</p>
        {description && <p className="text-xs text-gray-400 mt-0.5">{description}</p>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  )
}

function NumberInput({ value, onChange, min, max, unit }) {
  return (
    <div className="flex items-center gap-2">
      <input
        type="number"
        value={value}
        onChange={e => onChange(Number(e.target.value))}
        min={min}
        max={max}
        className="w-24 border border-gray-300 rounded-lg px-3 py-1.5 text-sm text-right focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
      {unit && <span className="text-xs text-gray-400 w-16">{unit}</span>}
    </div>
  )
}

function Section({ title, description, children }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden mb-6">
      <div className="px-6 py-4 border-b border-gray-100">
        <h2 className="font-semibold text-gray-900 text-sm">{title}</h2>
        {description && <p className="text-xs text-gray-400 mt-0.5">{description}</p>}
      </div>
      <div className="px-6">{children}</div>
    </div>
  )
}

const DEFAULT_SETTINGS = {
  chunk_duration_sec: 300,
  chunk_overlap_sec: 30,
  frame_sample_rate_fps: 5,
  activation_countdown_sec: 60,
  active_config_cache_ttl_sec: 300,
  shift_start_grace_min: 15,
  absence_threshold_min: 15,
}

export default function Settings() {
  const { slug } = useParams()
  const { state } = useAuth()
  const role = state.currentMember?.role || (state.user?.account_type === 'owner' ? 'owner' : null)

  const [settings, setSettings] = useState(null)
  const [alertConfig, setAlertConfig] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(null) // 'settings' | 'alerts' | null
  const [saved, setSaved] = useState(null)   // 'settings' | 'alerts' | null
  const [restored, setRestored] = useState(null) // 'settings' | 'alerts' | null
  const [error, setError] = useState('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [s, a] = await Promise.all([getSettings(slug), getAlertConfig(slug)])
      setSettings(s)
      setAlertConfig(a)
    } catch (err) {
      setError(err.response?.data?.detail?.error || 'Failed to load settings')
    } finally {
      setLoading(false)
    }
  }, [slug])

  useEffect(() => { fetchData() }, [fetchData])

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
      setSaved('settings')
      setTimeout(() => setSaved(null), 2000)
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
      setSaved('alerts')
      setTimeout(() => setSaved(null), 2000)
    } catch (err) {
      setError(err.response?.data?.detail?.error || 'Failed to save alert config')
    } finally {
      setSaving(null)
    }
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
    <div className="flex flex-col h-full overflow-auto">
      <header className="px-6 py-4 border-b border-gray-200 bg-white shrink-0">
        <h1 className="font-semibold text-gray-900">Settings</h1>
        <p className="text-xs text-gray-400 mt-0.5">Store configuration and alert thresholds</p>
      </header>

      <div className="flex-1 p-6 max-w-2xl">
        {error && (
          <div className="bg-red-50 text-red-700 text-sm px-4 py-3 rounded-lg border border-red-200 mb-4">{error}</div>
        )}

        {loading ? (
          <div className="text-sm text-gray-400 py-8 text-center">Loading…</div>
        ) : (
          <>
            {/* Processing Settings */}
            <Section
              title="Processing Settings"
              description="Controls video chunk processing and frame sampling behaviour"
            >
              <FieldRow label="Activation countdown" description="Delay before a new config goes live after activation">
                <NumberInput
                  value={settings.activation_countdown_sec}
                  onChange={v => updateSettings('activation_countdown_sec', v)}
                  min={10} max={3600} unit="seconds"
                />
              </FieldRow>
              <FieldRow label="Chunk duration" description="Length of each video processing chunk">
                <NumberInput
                  value={settings.chunk_duration_sec}
                  onChange={v => updateSettings('chunk_duration_sec', v)}
                  min={30} max={3600} unit="seconds"
                />
              </FieldRow>
              <FieldRow label="Chunk overlap" description="Overlap between consecutive chunks to avoid missed frames">
                <NumberInput
                  value={settings.chunk_overlap_sec}
                  onChange={v => updateSettings('chunk_overlap_sec', v)}
                  min={0} max={300} unit="seconds"
                />
              </FieldRow>
              <FieldRow label="Frame sample rate" description="Frames per second to sample from the video stream">
                <NumberInput
                  value={settings.frame_sample_rate_fps}
                  onChange={v => updateSettings('frame_sample_rate_fps', v)}
                  min={1} max={30} unit="fps"
                />
              </FieldRow>
              <FieldRow label="Config cache TTL" description="How long the active config is cached before re-fetching">
                <NumberInput
                  value={settings.active_config_cache_ttl_sec}
                  onChange={v => updateSettings('active_config_cache_ttl_sec', v)}
                  min={10} max={86400} unit="seconds"
                />
              </FieldRow>

              <div className="py-4 flex items-center justify-end gap-3">
                {restored === 'settings' && (
                  <span className="text-sm text-amber-600 font-medium">Defaults restored — click Save to apply.</span>
                )}
                {saved === 'settings' && (
                  <span className="text-sm text-green-600 font-medium">Saved</span>
                )}
                <button
                  onClick={resetSettings}
                  className="px-4 py-2 rounded-lg text-sm font-semibold text-gray-600 border border-gray-300 hover:bg-gray-50 transition-colors">
                  Reset to defaults
                </button>
                <button
                  onClick={handleSaveSettings}
                  disabled={saving === 'settings'}
                  className="px-4 py-2 rounded-lg text-sm font-semibold text-white disabled:opacity-50 transition-colors"
                  style={{ backgroundColor: '#1B3A5C' }}>
                  {saving === 'settings' ? 'Saving…' : 'Save changes'}
                </button>
              </div>
            </Section>

            {/* Alert Config */}
            <Section
              title="Alert Thresholds"
              description="Conditions that trigger operational alerts for this store"
            >
              <FieldRow label="Shift start grace period" description="How late an employee can clock in before triggering an absence alert">
                <NumberInput
                  value={alertConfig.shift_start_grace_min}
                  onChange={v => updateAlert('shift_start_grace_min', v)}
                  min={0} max={120} unit="minutes"
                />
              </FieldRow>
              <FieldRow label="Absence threshold" description="Minutes without detection before an employee is marked absent">
                <NumberInput
                  value={alertConfig.absence_threshold_min}
                  onChange={v => updateAlert('absence_threshold_min', v)}
                  min={1} max={120} unit="minutes"
                />
              </FieldRow>
              <FieldRow label="Queue size threshold" description="Number of people in a queue that triggers an alert">
                <NumberInput
                  value={alertConfig.queue_people_threshold}
                  onChange={v => updateAlert('queue_people_threshold', v)}
                  min={1} max={500} unit="people"
                />
              </FieldRow>
              <FieldRow label="Queue wait threshold" description="Wait time before a queue alert is raised">
                <NumberInput
                  value={alertConfig.queue_wait_min_threshold}
                  onChange={v => updateAlert('queue_wait_min_threshold', v)}
                  min={1} max={120} unit="minutes"
                />
              </FieldRow>
              <FieldRow label="Alert cooldown" description="Minimum time between repeated queue alerts">
                <NumberInput
                  value={alertConfig.queue_alert_cooldown_min}
                  onChange={v => updateAlert('queue_alert_cooldown_min', v)}
                  min={1} max={120} unit="minutes"
                />
              </FieldRow>

              <div className="py-4 flex items-center justify-end gap-3">
                {restored === 'alerts' && (
                  <span className="text-sm text-amber-600 font-medium">Defaults restored — click Save to apply.</span>
                )}
                {saved === 'alerts' && (
                  <span className="text-sm text-green-600 font-medium">Saved</span>
                )}
                <button
                  onClick={resetAlerts}
                  className="px-4 py-2 rounded-lg text-sm font-semibold text-gray-600 border border-gray-300 hover:bg-gray-50 transition-colors">
                  Reset to defaults
                </button>
                <button
                  onClick={handleSaveAlerts}
                  disabled={saving === 'alerts'}
                  className="px-4 py-2 rounded-lg text-sm font-semibold text-white disabled:opacity-50 transition-colors"
                  style={{ backgroundColor: '#1B3A5C' }}>
                  {saving === 'alerts' ? 'Saving…' : 'Save changes'}
                </button>
              </div>
            </Section>
          </>
        )}
      </div>
    </div>
  )
}
