// UI formatting. Durations arrive from the API in milliseconds; format here only.

export function formatDuration(ms) {
  if (ms == null) return '—'
  const s = ms / 1000
  if (s < 60) return `${s < 10 ? s.toFixed(1) : Math.round(s)}s`
  const m = s / 60
  if (m < 60) return `${m.toFixed(1)}m`
  return `${(m / 60).toFixed(1)}h`
}

export function formatNumber(n) {
  return n == null ? '—' : Number(n).toLocaleString()
}

export function formatRatio(r) {
  return r == null ? '—' : `${(r * 100).toFixed(0)}%`
}
