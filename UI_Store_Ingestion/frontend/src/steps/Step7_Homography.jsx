import React, { useState } from 'react'
import useStore from '../store'
import { computeHomography } from '../api'

export default function Step7_Homography() {
  const { cameras, updateCamera, setStep } = useStore()
  const [loading, setLoading] = useState({})
  const [errors, setErrors] = useState({})

  const handleCompute = async (cam) => {
    const corr = cam.correspondences || []
    if (corr.length < 4) return
    setLoading(l => ({ ...l, [cam.id]: true }))
    setErrors(e => ({ ...e, [cam.id]: null }))
    try {
      const result = await computeHomography(
        cam.id,
        corr.map(c => c.camPx),
        corr.map(c => c.floorM),
      )
      updateCamera(cam.id, {
        homographyMatrix: result.matrix,
        reprojectionError: result.reprojectionError,
        homographyStatus: result.status,
        perPointErrors: result.perPointErrors,
        homographyResult: result,
      })
    } catch (e) {
      setErrors(err => ({ ...err, [cam.id]: e.message }))
    } finally {
      setLoading(l => ({ ...l, [cam.id]: false }))
    }
  }

  const removePair = (camId, idx) => {
    const cam = cameras.find(c => c.id === camId)
    if (!cam) return
    const newCorr = cam.correspondences.filter((_, i) => i !== idx)
    updateCamera(camId, { correspondences: newCorr, homographyStatus: 'pending', homographyMatrix: null })
  }

  const allOk = cameras.every(c => c.homographyStatus === 'ok')

  return (
    <div>
      <h3 className="text-xl font-semibold mb-2 text-gray-800">Compute Homography</h3>
      <p className="text-gray-500 mb-6 text-sm">Compute the homography matrix for each camera. All must pass (error &lt; 5.0m) to continue.</p>

      <div className="space-y-6">
        {cameras.map(cam => {
          const corr = cam.correspondences || []
          const status = cam.homographyStatus
          const result = cam.homographyResult

          return (
            <div key={cam.id} className="bg-white border rounded-xl p-5 shadow-sm">
              <div className="flex items-center justify-between mb-3">
                <h4 className="font-semibold text-gray-800">{cam.name}</h4>
                {status === 'ok' && <span className="text-xs font-medium text-green-700 bg-green-100 px-2 py-1 rounded-full">✓ OK — Error: {cam.reprojectionError?.toFixed(3)}m</span>}
                {status === 'rejected' && <span className="text-xs font-medium text-red-700 bg-red-100 px-2 py-1 rounded-full">✗ Rejected — Error: {cam.reprojectionError?.toFixed(3)}m (threshold 5.0m)</span>}
                {status === 'failed' && <span className="text-xs font-medium text-red-700 bg-red-100 px-2 py-1 rounded-full">✗ Failed — Collinear points?</span>}
              </div>

              <p className="text-sm text-gray-500 mb-3">{corr.length} correspondence pairs</p>

              {result?.perPointErrors && (
                <div className="mb-3 overflow-x-auto">
                  <table className="text-xs w-full border-collapse">
                    <thead>
                      <tr className="bg-gray-50">
                        <th className="border px-2 py-1 text-left">#</th>
                        <th className="border px-2 py-1 text-left">Cam Pixel</th>
                        <th className="border px-2 py-1 text-left">Floor (m)</th>
                        <th className="border px-2 py-1 text-left">Error</th>
                        <th className="border px-2 py-1"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {corr.map((c, i) => {
                        const err = result.perPointErrors[i]
                        const worst = err === Math.max(...result.perPointErrors)
                        return (
                          <tr key={i} className={worst && status !== 'ok' ? 'bg-red-50' : ''}>
                            <td className="border px-2 py-1">{i + 1}</td>
                            <td className="border px-2 py-1">({c.camPx.x.toFixed(0)}, {c.camPx.y.toFixed(0)})</td>
                            <td className="border px-2 py-1">({c.floorM.x.toFixed(2)}, {c.floorM.y.toFixed(2)})</td>
                            <td className={`border px-2 py-1 font-mono ${worst && status !== 'ok' ? 'text-red-600 font-bold' : ''}`}>{err?.toFixed(3)}</td>
                            <td className="border px-2 py-1">
                              <button onClick={() => removePair(cam.id, i)} className="text-red-400 hover:text-red-600">✕</button>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}

              {errors[cam.id] && <p className="text-red-600 text-sm mb-3">{errors[cam.id]}</p>}

              <button
                onClick={() => handleCompute(cam)}
                disabled={corr.length < 4 || loading[cam.id]}
                className="px-4 py-2 bg-navy-700 text-white rounded-lg text-sm font-medium disabled:opacity-40 hover:opacity-90 transition"
                style={{ background: '#1B3A5C' }}
              >
                {loading[cam.id] ? 'Computing...' : 'Compute Homography'}
              </button>
            </div>
          )
        })}
      </div>

      <div className="mt-6 flex justify-between">
        <button onClick={() => setStep(6)} className="px-4 py-2 text-gray-600 border rounded-lg hover:bg-gray-50">← Back</button>
        <button onClick={() => setStep(8)} disabled={!allOk} className="px-6 py-2 bg-blue-600 text-white rounded-lg font-medium disabled:opacity-40 hover:bg-blue-700 transition">
          Next: Save Configuration →
        </button>
      </div>
    </div>
  )
}
