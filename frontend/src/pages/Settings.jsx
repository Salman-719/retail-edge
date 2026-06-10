import React, { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Cpu } from 'lucide-react'
import { useAuth } from '../store'
import { getSettings, patchSettings } from '../api'
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


// ── Page ──────────────────────────────────────────────────────────────────────

export default function Settings() {
  const { slug } = useParams()
  const { state } = useAuth()
  const role = state.currentMember?.role || (state.user?.account_type === 'owner' ? 'owner' : null)
  usePageTitle('Settings')

  const [settings, setSettings] = useState(null)

  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(null) // 'settings' | null
  const [restored, setRestored] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    getSettings(slug)
      .then(s => {
        if (cancelled) return
        setSettings(s)
      })
      .catch(err => {
        if (cancelled) return
        setError(err.response?.data?.detail?.error || 'Failed to load settings')
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [slug])

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
    } catch (err) {
      setError(err.response?.data?.detail?.error || 'Failed to save settings')
    } finally {
      setSaving(null)
    }
  }

  function updateSettings(field, value) {
    setSettings(s => ({ ...s, [field]: value }))
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
        <p className="page-subtitle">Store configuration</p>
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
          </>
        )}
      </div>

    </div>
  )
}
