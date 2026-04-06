import React, { useEffect, useState, useRef } from 'react'
import useStore from '../store'
import { listStores, createStore, setCurrentStoreId, loadProject } from '../api'

import Step1_Upload from '../steps/Step1_Upload'
import Step2_Scale from '../steps/Step2_Scale'
import Step3_Zones from '../steps/Step3_Zones'
import Step4_Cameras from '../steps/Step4_Cameras'
import Step5_Videos from '../steps/Step5_Videos'
import Step6_Correspondence from '../steps/Step6_Correspondence'
import Step7_Homography from '../steps/Step7_Homography'
import Step8_Save from '../steps/Step8_Save'
import Step9_TestMode from '../steps/Step9_TestMode'

const STEPS = [
  { n: 1, label: 'Floor Plan Upload' },
  { n: 2, label: 'Scale & Origin' },
  { n: 3, label: 'Zones & Obstacles' },
  { n: 4, label: 'Camera Registration' },
  { n: 5, label: 'Camera Videos' },
  { n: 6, label: 'Point Correspondence' },
  { n: 7, label: 'Compute Homography' },
  { n: 8, label: 'Save Configuration' },
  { n: 9, label: 'Test Mode & Heatmap' },
]

const STEP_COMPONENTS = {
  1: Step1_Upload,
  2: Step2_Scale,
  3: Step3_Zones,
  4: Step4_Cameras,
  5: Step5_Videos,
  6: Step6_Correspondence,
  7: Step7_Homography,
  8: Step8_Save,
  9: Step9_TestMode,
}

// ── Store selector overlay ────────────────────────────────────────────────────

function StoreSelector({ onSelected }) {
  const [stores, setStores] = useState([])
  const [newName, setNewName] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    listStores().then(setStores).catch(() => {})
  }, [])

  const handleCreate = async () => {
    if (!newName.trim()) return
    setLoading(true)
    setError(null)
    try {
      const store = await createStore(newName.trim())
      onSelected(store)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex-1 flex items-center justify-center p-12 bg-gray-50">
      <div className="bg-white rounded-2xl shadow-lg border p-8 max-w-md w-full">
        <h2 className="text-2xl font-bold text-gray-800 mb-1">Select a Store</h2>
        <p className="text-gray-500 text-sm mb-6">Choose an existing store or create a new one to begin onboarding.</p>

        {stores.length > 0 && (
          <div className="mb-6">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Existing Stores</p>
            <div className="space-y-2">
              {stores.map(s => (
                <button
                  key={s.id}
                  onClick={() => onSelected(s)}
                  className="w-full text-left px-4 py-3 rounded-xl border border-gray-200 hover:border-blue-400 hover:bg-blue-50 transition flex items-center gap-3"
                >
                  <span className="text-xl">🏪</span>
                  <span className="font-medium text-gray-800">{s.name}</span>
                </button>
              ))}
            </div>
            <div className="flex items-center gap-3 my-4">
              <div className="flex-1 border-t" /><span className="text-xs text-gray-400">or</span><div className="flex-1 border-t" />
            </div>
          </div>
        )}

        <div className="flex gap-2">
          <input
            type="text"
            placeholder="New store name…"
            value={newName}
            onChange={e => setNewName(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleCreate()}
            className="flex-1 border rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
          />
          <button
            onClick={handleCreate}
            disabled={loading || !newName.trim()}
            className="px-5 py-2.5 bg-blue-600 text-white rounded-xl text-sm font-medium disabled:opacity-40 hover:bg-blue-700 transition"
          >
            {loading ? '…' : 'Create'}
          </button>
        </div>
        {error && <p className="text-red-600 text-xs mt-2">{error}</p>}
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function StoreOnboarding() {
  const {
    activeStoreId, activeStoreName, setActiveStore,
    currentStep, setStep, maxReachedStep,
    loadProject: hydrateProject,
    resetOnboarding,
    floorPlanUrl,
  } = useStore()
  const importRef = useRef()

  const handleStoreSelected = async (store) => {
    setCurrentStoreId(store.id)
    setActiveStore(store.id, store.name)
    resetOnboarding()

    // Load existing project data from backend
    try {
      const data = await loadProject()
      if (data) hydrateProject(data)
    } catch (_) {}
  }

  const handleImportFile = (e) => {
    const file = e.target.files[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (ev) => {
      try {
        const data = JSON.parse(ev.target.result)
        hydrateProject(data)
      } catch {
        alert('Invalid project file — expected JSON.')
      }
    }
    reader.readAsText(file)
    e.target.value = ''
  }

  if (!activeStoreId) {
    return (
      <div className="flex-1 flex flex-col">
        <header className="bg-white border-b px-8 py-4">
          <h2 className="text-lg font-semibold text-gray-800">Store Onboarding</h2>
          <p className="text-sm text-gray-500">Configure floor plan, zones, cameras and run tracking tests</p>
        </header>
        <StoreSelector onSelected={handleStoreSelected} />
      </div>
    )
  }

  const StepComponent = STEP_COMPONENTS[currentStep]

  return (
    <div className="flex flex-1 overflow-hidden">
      {/* Wizard sidebar */}
      <aside className="w-56 flex flex-col py-5 px-3 border-r bg-white shrink-0 overflow-y-auto">
        <div className="mb-4 px-1">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Store</p>
          <p className="text-sm font-semibold text-gray-800 mt-0.5 truncate">{activeStoreName}</p>
          <button
            onClick={() => setActiveStore(null, null)}
            className="text-xs text-blue-500 hover:underline"
          >
            Switch store
          </button>
        </div>

        <nav className="flex flex-col gap-0.5 flex-1">
          {STEPS.map(step => {
            const active = step.n === currentStep
            const done = step.n < maxReachedStep
            const accessible = step.n <= maxReachedStep
            return (
              <button
                key={step.n}
                onClick={() => accessible && setStep(step.n)}
                className={`flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-xs text-left transition-colors ${
                  active ? 'bg-blue-600 text-white font-semibold' :
                  done ? 'text-gray-600 hover:bg-gray-100 cursor-pointer' :
                  accessible ? 'text-gray-500 hover:bg-gray-100 cursor-pointer' :
                  'text-gray-300 cursor-not-allowed'
                }`}
              >
                <span className={`w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${
                  active ? 'bg-white text-blue-600' :
                  done ? 'bg-green-500 text-white' :
                  accessible ? 'bg-blue-100 text-blue-700' :
                  'bg-gray-200 text-gray-400'
                }`}>
                  {done ? '✓' : step.n}
                </span>
                <span className="truncate">{step.label}</span>
              </button>
            )
          })}
        </nav>

        <div className="pt-3 border-t mt-3">
          <button
            onClick={() => importRef.current?.click()}
            className="w-full text-xs px-2.5 py-2 rounded-lg text-left text-gray-500 hover:bg-gray-100 transition flex items-center gap-2"
          >
            <span>📂</span> Import JSON
          </button>
          <input ref={importRef} type="file" accept=".json" className="hidden" onChange={handleImportFile} />
        </div>
      </aside>

      {/* Step content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <header className="bg-white border-b px-8 py-3 flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-gray-800">
              Step {currentStep}: {STEPS[currentStep - 1].label}
            </h2>
            <p className="text-xs text-gray-500">Step {currentStep} of 9</p>
          </div>
          {floorPlanUrl && (
            <span className="text-xs text-green-600 font-medium">● Floor plan loaded</span>
          )}
        </header>
        <div className="flex-1 overflow-auto p-6">
          <StepComponent />
        </div>
      </div>
    </div>
  )
}
