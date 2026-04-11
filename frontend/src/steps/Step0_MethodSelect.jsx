import React, { useState } from 'react'
import useStore from '../store'

const METHODS = [
  {
    id: 'standard',
    title: 'Standard (Floor Plan + Homography)',
    icon: '🗺️',
    description: 'Upload an existing 2D floor plan image, set its scale, and mark point correspondences per camera to compute a homography matrix.',
    pros: ['Works with any existing architectural drawing', 'Simple 4-point calibration per camera'],
    cons: ['Requires a pre-made floor plan image', 'Manual correspondence marking can be tedious'],
  },
  {
    id: 'calibration',
    title: 'Calibration Files (Intrinsics + Extrinsics)',
    icon: '📐',
    description: 'Upload OpenCV XML calibration files (intr_*.xml + extr_*.xml) per camera. The 2D map is automatically generated from the camera geometry.',
    pros: ['No floor plan image needed', 'Physics-accurate ray projection', 'Map auto-generated from camera positions'],
    cons: ['Requires pre-computed calibration XML files', 'Cameras must be calibrated beforehand'],
  },
]

export default function Step0_MethodSelect({ onMethodSelected }) {
  const { setOnboardingMethod } = useStore()
  const [selected, setSelected] = useState(null)
  const [loading, setLoading] = useState(false)

  async function handleConfirm() {
    if (!selected) return
    setLoading(true)
    try {
      setOnboardingMethod(selected)
      onMethodSelected(selected)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-3xl mx-auto py-8 px-4">
      <h2 className="text-2xl font-bold text-gray-800 mb-2">Choose Onboarding Method</h2>
      <p className="text-gray-500 mb-8">
        Select how you'd like to set up camera-to-floor projection for this store.
        This choice cannot be changed after you proceed.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
        {METHODS.map(m => (
          <button
            key={m.id}
            onClick={() => setSelected(m.id)}
            className={[
              'text-left p-6 rounded-xl border-2 transition-all',
              selected === m.id
                ? 'border-blue-500 bg-blue-50 shadow-md'
                : 'border-gray-200 bg-white hover:border-blue-300 hover:bg-gray-50',
            ].join(' ')}
          >
            <div className="flex items-center gap-3 mb-3">
              <span className="text-3xl">{m.icon}</span>
              <span className="font-semibold text-gray-800 text-sm leading-tight">{m.title}</span>
              {selected === m.id && (
                <span className="ml-auto text-blue-500">
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414L8.414 15l-4.121-4.121a1 1 0 011.414-1.414L8.414 12.172l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                  </svg>
                </span>
              )}
            </div>
            <p className="text-gray-600 text-xs mb-4 leading-relaxed">{m.description}</p>
            <div className="space-y-1">
              {m.pros.map(p => (
                <div key={p} className="flex items-start gap-2 text-xs text-green-700">
                  <span className="mt-0.5 shrink-0">✓</span><span>{p}</span>
                </div>
              ))}
              {m.cons.map(c => (
                <div key={c} className="flex items-start gap-2 text-xs text-gray-400">
                  <span className="mt-0.5 shrink-0">–</span><span>{c}</span>
                </div>
              ))}
            </div>
          </button>
        ))}
      </div>

      <button
        disabled={!selected || loading}
        onClick={handleConfirm}
        className="w-full py-3 rounded-lg font-semibold text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed bg-blue-600 hover:bg-blue-700"
      >
        {loading ? 'Setting up…' : selected ? `Continue with ${METHODS.find(m => m.id === selected)?.title}` : 'Select a method to continue'}
      </button>
    </div>
  )
}
