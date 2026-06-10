// One stable color + number per global_id, assigned in first-seen order. Built
// ONCE per run at the page level (VD2) so the same person shows the same
// color/number in every camera feed, on the unified map, and in every table.

const PALETTE = [
  '#2563eb', '#f59e0b', '#10b981', '#ec4899', '#8b5cf6',
  '#ef4444', '#06b6d4', '#84cc16', '#f97316', '#14b8a6',
  '#a855f7', '#0ea5e9', '#eab308', '#22c55e', '#f43f5e',
]
const PENDING = { color: '#9ca3af', number: null }

export function makeIdentityMap() {
  const map = new Map() // global_id -> { color, number }
  let next = 1
  return {
    get(globalId) {
      if (globalId == null) return PENDING
      if (!map.has(globalId)) {
        map.set(globalId, { color: PALETTE[(next - 1) % PALETTE.length], number: next })
        next += 1
      }
      return map.get(globalId)
    },
    entries() {
      return [...map.entries()].map(([global_id, v]) => ({ global_id, ...v }))
    },
  }
}

// Stable per-camera color keyed by camera slot index (Cam 1..6).
export const CAMERA_PALETTE = ['#3b82f6', '#f59e0b', '#10b981', '#ec4899', '#8b5cf6', '#ef4444']
