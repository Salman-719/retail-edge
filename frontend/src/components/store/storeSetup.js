// Shared helpers for the read-only Store Setup view (C1).

export const ZONE_COLORS = {
  entrance: '#3b82f6', checkout: '#f59e0b', aisle: '#10b981',
  staff_only: '#ef4444', general: '#8b5cf6',
}

export const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

// Shoelace polygon area in px², ÷ ppm² → m². points are floor-plan pixels.
export function zoneAreaM2(points, ppm) {
  if (!points || points.length < 3 || !ppm) return null
  let a = 0
  for (let i = 0; i < points.length; i++) {
    const [x1, y1] = points[i]
    const [x2, y2] = points[(i + 1) % points.length]
    a += x1 * y2 - x2 * y1
  }
  return Math.abs(a / 2) / (ppm * ppm)
}

// "09:00:00" / "09:00" → "9:00 AM"
export function formatTime(t) {
  if (!t) return ''
  const [hh, mm] = t.split(':')
  let h = parseInt(hh, 10)
  const ampm = h >= 12 ? 'PM' : 'AM'
  h = h % 12 || 12
  return `${h}:${mm} ${ampm}`
}
