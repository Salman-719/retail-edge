const BASE = ''

export async function uploadFloorplan(file) {
  const fd = new FormData()
  fd.append('file', file)
  const r = await fetch(`${BASE}/api/floorplan/upload`, { method: 'POST', body: fd })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function uploadVideo(cameraId, file) {
  const fd = new FormData()
  fd.append('file', file)
  const r = await fetch(`${BASE}/api/video/upload/${cameraId}`, { method: 'POST', body: fd })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function getVideoFrame(cameraId, timestampSec) {
  const r = await fetch(`${BASE}/api/video/frame/${cameraId}?timestamp_sec=${timestampSec}`)
  if (!r.ok) throw new Error(await r.text())
  const blob = await r.blob()
  return URL.createObjectURL(blob)
}

export async function computeHomography(cameraId, camPoints, floorPoints) {
  const r = await fetch(`${BASE}/api/homography/compute`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ camera_id: cameraId, cam_points: camPoints, floor_points: floorPoints }),
  })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function runTracking(cameraId, payload) {
  const r = await fetch(`${BASE}/api/tracking/run/${cameraId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function saveProject(data) {
  const r = await fetch(`${BASE}/api/project/save`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function loadProject() {
  const r = await fetch(`${BASE}/api/project/load`)
  if (r.status === 404) return null
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}
