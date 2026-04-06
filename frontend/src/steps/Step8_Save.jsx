import React, { useState } from 'react'
import useStore from '../store'
import { saveProject, loadProject } from '../api'

export default function Step8_Save() {
  const store = useStore()
  const {
    setStep, loadProject: hydrateProject,
    floorPlanWidth, floorPlanHeight, pixelsPerMeter, origin,
    zones, obstacles, cameras,
  } = store
  const [saved, setSaved] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const getProjectData = store.getProjectData

  const handleSave = async () => {
    setLoading(true)
    setError(null)
    try {
      await saveProject(getProjectData())
      setSaved(true)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const handleExport = () => {
    const data = getProjectData()
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'project.json'
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleLoad = async () => {
    try {
      const data = await loadProject()
      if (data) hydrateProject(data)
      else alert('No project found on the server for this store.')
    } catch (e) {
      alert(e.message)
    }
  }

  return (
    <div className="max-w-3xl">
      <h3 className="text-xl font-semibold mb-2 text-gray-800">Save Configuration</h3>
      <p className="text-gray-500 mb-6 text-sm">Review your configuration and save it to the database.</p>

      <div className="space-y-4 mb-8">
        <Section title="Floor Plan">
          <Row label="Dimensions" value={`${floorPlanWidth} × ${floorPlanHeight} px`} />
          <Row label="Scale" value={pixelsPerMeter ? `${pixelsPerMeter.toFixed(1)} px/m` : '—'} />
          <Row label="Origin" value={origin ? `(${origin.x.toFixed(0)}, ${origin.y.toFixed(0)}) px` : '—'} />
        </Section>

        <Section title={`Zones (${zones.length})`}>
          {zones.length === 0
            ? <p className="text-sm text-gray-400 py-1">No zones defined.</p>
            : zones.map(z => <Row key={z.id} label={z.name} value={`${z.type} · ${z.points.length} vertices`} />)}
        </Section>

        <Section title={`Obstacles (${obstacles.length})`}>
          {obstacles.length === 0
            ? <p className="text-sm text-gray-400 py-1">No obstacles defined.</p>
            : obstacles.map(o => <Row key={o.id} label={o.name ?? '—'} value={`${o.points.length} vertices`} />)}
        </Section>

        <Section title={`Cameras (${cameras.length})`}>
          {cameras.map(c => (
            <div key={c.id} className="py-1 text-sm border-b last:border-0">
              <span className="font-medium">{c.name}</span>
              <span className="text-gray-400 ml-2">
                {c.position?.x?.toFixed(1)}m, {c.position?.y?.toFixed(1)}m · {c.heightMeters}m high ·
                {c.videoDuration ? ` ${c.videoDuration}s video` : ' no video'} ·
                <span className={c.homographyStatus === 'ok' ? 'text-green-600' : 'text-red-500'}>
                  {' '}{c.homographyStatus || 'no homography'}
                </span>
              </span>
            </div>
          ))}
        </Section>
      </div>

      <div className="flex gap-3 flex-wrap">
        <button
          onClick={handleSave}
          disabled={loading}
          className="px-5 py-2.5 bg-blue-600 text-white rounded-lg font-medium disabled:opacity-40 hover:bg-blue-700 transition"
        >
          {loading ? 'Saving…' : '💾 Save to Database'}
        </button>
        <button
          onClick={handleExport}
          className="px-5 py-2.5 bg-gray-100 text-gray-700 rounded-lg font-medium hover:bg-gray-200 transition"
        >
          📥 Export JSON
        </button>
        <button
          onClick={handleLoad}
          className="px-5 py-2.5 bg-gray-100 text-gray-700 rounded-lg font-medium hover:bg-gray-200 transition"
        >
          📂 Reload from DB
        </button>
      </div>

      {saved && (
        <p className="mt-3 text-green-600 text-sm font-medium">✓ Configuration saved to database.</p>
      )}
      {error && <p className="mt-3 text-red-600 text-sm">{error}</p>}

      <div className="mt-6 flex justify-between">
        <button onClick={() => setStep(7)} className="px-4 py-2 text-gray-600 border rounded-lg hover:bg-gray-50">
          ← Back
        </button>
        <button
          onClick={() => setStep(9)}
          className="px-6 py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 transition"
        >
          Next: Test Mode & Heatmap →
        </button>
      </div>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div className="bg-white border rounded-xl p-4">
      <h4 className="font-semibold text-gray-700 mb-2 text-sm">{title}</h4>
      {children}
    </div>
  )
}

function Row({ label, value }) {
  return (
    <div className="flex justify-between py-0.5 text-sm border-b last:border-0">
      <span className="text-gray-500">{label}</span>
      <span className="text-gray-800 font-medium">{value}</span>
    </div>
  )
}
