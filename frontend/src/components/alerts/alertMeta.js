// Single source of truth for alert presentation + the per-type field schema that
// drives the rule form (rule 5: don't hardcode the type→fields map in 3 places).

export const SEVERITY = {
  low: { label: 'Low', cls: 'bg-gray-100 text-gray-700 border-gray-200' },
  medium: { label: 'Medium', cls: 'bg-amber-100 text-amber-800 border-amber-200' },
  high: { label: 'High', cls: 'bg-orange-100 text-orange-800 border-orange-200' },
  critical: { label: 'Critical', cls: 'bg-red-100 text-red-800 border-red-200' },
}
export const SEVERITY_ORDER = ['low', 'medium', 'high', 'critical']

// Rule types (configurable in v1) → required extra fields + zone policy.
export const RULE_TYPES = {
  queue_buildup: {
    label: 'Queue buildup',
    extra: ['people_threshold'],
    zones: 'required', // >= 1
  },
  staff_absence_zone: {
    label: 'Staff absence (zone)',
    extra: ['min_employees'],
    zones: 'required',
  },
  staff_absence_employee: {
    label: 'Staff absence (employee)',
    extra: ['employee_id'],
    zones: 'none',
  },
}

// Fired alert types (read path is generic; this only labels the known ones).
export const ALERT_TYPE_LABEL = {
  staff_absence: 'Staff absence',
  queue_buildup: 'Queue buildup',
  camera_offline: 'Camera offline',
  camera_degraded: 'Camera degraded',
}

// Fallback new-rule defaults if GET /alert-rules/defaults (D5) is unavailable.
// Mirrors that endpoint's shape (common + per-type), seeded from old alert_configs.
export const RULE_DEFAULTS = {
  severity: 'medium',
  followup_interval_minutes: 5,
  only_during_shift: true,
  by_type: {
    queue_buildup: { threshold_minutes: 7, cooldown_minutes: 15, people_threshold: 10 },
    staff_absence_zone: { threshold_minutes: 15, cooldown_minutes: 30, min_employees: 1 },
    staff_absence_employee: { threshold_minutes: 15, cooldown_minutes: 30 },
  },
}

// Merge common + per-type defaults into flat form values for a given type.
export function defaultsFor(type, d) {
  const base = d || RULE_DEFAULTS
  const t = (base.by_type && base.by_type[type]) || {}
  return {
    severity: base.severity ?? 'medium',
    followup_interval_minutes: base.followup_interval_minutes ?? 5,
    only_during_shift: base.only_during_shift ?? true,
    threshold_minutes: t.threshold_minutes ?? 5,
    cooldown_minutes: t.cooldown_minutes ?? 30,
    people_threshold: t.people_threshold ?? 3,
    min_employees: t.min_employees ?? 1,
  }
}

export function ageLabel(iso) {
  const ms = Date.now() - new Date(iso).getTime()
  const m = Math.floor(ms / 60000)
  if (m < 1) return 'just now'
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}
