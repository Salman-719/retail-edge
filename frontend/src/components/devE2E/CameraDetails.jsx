import React, { useEffect, useRef } from 'react'

const fmtNum = (v, dp = 2) => (v == null ? '—' : Number(v).toFixed(dp))
const fmtTs = (ms) => (ms == null ? '—' : new Date(ms).toLocaleTimeString())
const shortId = (v) => (v ? String(v).slice(0, 8) : '—')

// Foot-point snapshot — last frame with bbox + foot dots, colored by identity.
function FootPointSnapshot({ frameUrl, rows, identity, globalOf }) {
  const ref = useRef(null)
  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    const draw = (img) => {
      if (img) { canvas.width = img.naturalWidth; canvas.height = img.naturalHeight; ctx.drawImage(img, 0, 0) }
      else { ctx.clearRect(0, 0, canvas.width, canvas.height) }
      for (const r of rows) {
        if (r.bbox_x1 == null) continue
        const gid = globalOf(r.local_id)
        const color = gid ? identity.get(gid).color : '#f59e0b'
        ctx.strokeStyle = color; ctx.lineWidth = 2
        ctx.strokeRect(r.bbox_x1, r.bbox_y1, (r.bbox_x2 - r.bbox_x1), (r.bbox_y2 - r.bbox_y1))
      }
    }
    if (frameUrl) { const img = new window.Image(); img.crossOrigin = 'anonymous'; img.onload = () => draw(img); img.onerror = () => draw(null); img.src = frameUrl }
    else draw(null)
  }, [frameUrl, rows, identity, globalOf])
  if (!frameUrl) return null
  return <canvas ref={ref} className="w-full mt-2 rounded border border-gray-200" />
}

// Details expander (VD2): tracking table (global# via shared identity) + replay
// scrubber + foot-point snapshot. Presentational — owns no fetching.
export default function CameraDetails({ rows, frameUrl, identity, globalOf, inReplay, replayIdx, frameCount, onSeek }) {
  const sorted = [...rows].sort(
    (a, b) => ((b.frame_number ?? 0) - (a.frame_number ?? 0)) || ((b.timestamp_ms ?? 0) - (a.timestamp_ms ?? 0))
  )
  return (
    <div className="border-t border-gray-100 bg-gray-50">
      {inReplay && (
        <div className="px-3 py-2 flex items-center gap-2 border-b border-gray-100">
          <button onClick={() => onSeek(replayIdx - 1)} className="px-2 py-0.5 text-xs rounded border border-gray-300 bg-white">◀</button>
          <input type="range" min={0} max={Math.max(0, frameCount - 1)} value={replayIdx}
            onChange={(e) => onSeek(Number(e.target.value))} className="flex-1 accent-blue-600" />
          <button onClick={() => onSeek(replayIdx + 1)} className="px-2 py-0.5 text-xs rounded border border-gray-300 bg-white">▶</button>
        </div>
      )}
      <div className="overflow-y-auto" style={{ maxHeight: 200 }}>
        {!rows.length ? (
          <div className="py-4 text-center text-gray-400 text-sm">No tracking rows yet</div>
        ) : (
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-white border-b border-gray-100">
              <tr>{['Frame', 'ID', 'Time', 'floor_x', 'floor_y', 'Zone', 'Conf'].map((h) => <th key={h} className="px-2 py-1.5 text-left font-semibold text-gray-500">{h}</th>)}</tr>
            </thead>
            <tbody>
              {sorted.map((r, i) => {
                const gid = globalOf(r.local_id)
                const id = identity.get(gid)
                return (
                  <tr key={`${r.local_id}-${r.timestamp_ms}-${i}`} className={i % 2 ? 'bg-gray-50' : 'bg-white'}>
                    <td className="px-2 py-1 font-mono text-gray-700">{r.frame_number ?? '—'}</td>
                    <td className="px-2 py-1 font-mono font-semibold" style={{ color: gid ? id.color : '#9ca3af' }}>{gid ? `#${id.number}` : 'pending'}</td>
                    <td className="px-2 py-1 font-mono text-gray-500">{fmtTs(r.timestamp_ms)}</td>
                    <td className="px-2 py-1 text-gray-700">{fmtNum(r.floor_x)}</td>
                    <td className="px-2 py-1 text-gray-700">{fmtNum(r.floor_y)}</td>
                    <td className="px-2 py-1 font-mono text-gray-500">{shortId(r.zone_id)}</td>
                    <td className="px-2 py-1 text-gray-700">{fmtNum((r.bbox_confidence ?? 0) * 100, 0)}%</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
      <div className="px-3 py-2">
        <FootPointSnapshot frameUrl={frameUrl} rows={rows} identity={identity} globalOf={globalOf} />
      </div>
    </div>
  )
}
